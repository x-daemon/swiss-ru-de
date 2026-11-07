"""German -> Russian translation backends.

* ``claude``  - best quality, understands context and leftover dialect words
                (Anthropic API key: Settings or ANTHROPIC_API_KEY)
* ``deepl``   - very good, fast (DeepL key: Settings or DEEPL_AUTH_KEY, free tier)
* ``offline`` - runs locally, no key, no internet after the first download (NLLB,
                converted to CTranslate2 int8 on first use: ~3x faster than PyTorch)
"""

from __future__ import annotations

import os
import re
import shutil
import threading
from typing import Sequence

from . import keys
from .config import DEFAULT_OFFLINE_MODEL, DIALECTS

# Swiss words the speech model often leaves in its German output. Machine translators
# (offline, DeepL) translate them badly or literally (Gipfeli -> "peaks"), so they get the
# Standard German word first. Claude gets the original text: it knows these words.
# Order matters: plural forms before singular forms.
SWISS_TERMS = [
    # meals
    (r"z['’]?morge[n]?", "Frühstück"),
    (r"z['’]?mittag", "Mittagessen"),
    (r"z['’]?nacht", "Abendessen"),
    (r"z['’]?vieri", "Zwischenmahlzeit"),
    (r"z['’]?nüni", "Znüni-Pause"),
    # bakery, food and drink
    (r"weggli|bürli|brötli", "Brötchen"),
    (r"schoggis?", "Schokolade"),
    (r"kafi|kaffi", "Kaffee"),
    (r"kafi crème|kafi creme|café crème", "Kaffee mit Milch"),
    (r"guetzlis?", "Kekse"),
    (r"rüebli", "Karotten"),
    (r"h[äe]rd[öo]pfel|erdäpfel", "Kartoffeln"),
    (r"nüsslisalat", "Feldsalat"),
    (r"peperonis?", "Paprika"),
    (r"rahm", "Sahne"),
    (r"chäs", "Käse"),
    (r"poulet", "Hähnchen"),
    (r"glace", "Eis"),
    (r"zältli", "Bonbons"),
    (r"konfi", "Marmelade"),
    (r"wähe", "Obstkuchen"),
    (r"cervelat", "Wurst"),
    # everyday words
    (r"velos", "Fahrräder"),
    (r"velo", "Fahrrad"),
    (r"töff", "Motorrad"),
    (r"trottinett", "Tretroller"),
    (r"natel", "Handy"),
    (r"trottoir", "Gehweg"),
    (r"billette|billets", "Fahrkarten"),
    (r"billett?", "Fahrkarte"),
    (r"chuchi", "Küche"),
    (r"lavabo", "Waschbecken"),
    (r"estrich", "Dachboden"),
    (r"pöstler", "Briefträger"),
    (r"spital", "Krankenhaus"),
    (r"coiffeur", "Friseur"),
    (r"znüni", "Pause"),
    (r"büez|chrampf", "Arbeit"),
    (r"grüezi( mitenand)?|grüessech|grüessu|hoi zäme|sali zäme", "Guten Tag"),
    (r"merci vilmal|merci viel ?mal", "vielen Dank"),
    (r"merci", "danke"),
    (r"zäme", "zusammen"),
    (r"uf widerluege|adieu", "auf Wiedersehen"),
]
_SWISS_RE = [(re.compile(rf"\b(?:{k})\b", re.IGNORECASE), v) for k, v in SWISS_TERMS]

# "Gipfel" means a mountain peak - unless people talk about breakfast or a bakery, where the
# speech model often writes "Gipfel" for the Swiss "Gipfeli" (croissant).
_FOOD = re.compile(
    r"\b(frühstück|zmorge|kaffee|kafi|bäcke(rei|r)|beck|essen|isst|esse|gegessen|ässe|butter|"
    r"marmelade|konfi|brot|brötchen|zopf|croissants?|gipfeli|hunger|tee|milch|café|kaufen|"
    r"gekauft|bestellt|frisch|warm|knusprig|schokolade|schoggi|teller|tisch|pause)\b",
    re.IGNORECASE)
_GIPFEL = re.compile(r"\b(Gipfel)(i)?(n|s)?\b", re.IGNORECASE)


def normalize_swiss_terms(text: str, context: Sequence[str] = ()) -> str:
    for pattern, replacement in _SWISS_RE:
        text = pattern.sub(replacement, text)
    food = any(_FOOD.search(t) for t in (text, *context[-2:]))

    def croissant(m: re.Match) -> str:
        if not (m.group(2) or food):  # plain "Gipfel" outside food talk: a mountain peak
            return m.group(0)
        plural = bool(m.group(3)) or _plural_before(text, m)
        return "Croissants" if plural else "Croissant"

    return _GIPFEL.sub(croissant, text)


def _plural_before(text: str, match: re.Match) -> bool:
    before = text[: match.start()].split()[-1:] or [""]
    word = before[0].lower()
    return word.isdigit() and word != "1" or word in {
        "zwei", "drei", "vier", "fünf", "sechs", "paar", "viele", "einige", "mehrere", "die"}


class TranslationError(RuntimeError):
    pass


class Translator:
    name = "none"

    def translate(self, text: str, context: Sequence[str] = ()) -> str:
        raise NotImplementedError


class Passthrough(Translator):
    """Target language German: the recogniser already produces Standard German."""

    name = "none (German)"

    def translate(self, text: str, context: Sequence[str] = ()) -> str:
        return text


# ----------------------------------------------------------------------- Claude
CLAUDE_SYSTEM = """You translate live subtitles into Russian.

The audio is Swiss German. A speech recogniser has already converted it into Standard German, \
sentence by sentence. Its output can contain recognition mistakes, missing punctuation, or \
dialect words it did not convert (for example: öppis, gsi, lueg, äbe, gäll, merci vilmal, \
Chuchichäschtli, Grüessech, Grüezi, ade, hoi, zäme, nöd, nüt, chli, gönd, gang).

Typical traps, translate the meaning:
- "zum Morgen", "Zmorge" = breakfast (Frühstück), not "tomorrow"; "Zmittag" = lunch; \
"Znacht" = dinner; "Zvieri"/"Znüni" = snack.
- Gipfeli = croissant. When people talk about breakfast, coffee or a bakery, "Gipfel" in the \
text is a misrecognised "Gipfeli" (croissants), not a mountain peak.
- Weggli/Bürli = bread roll, Zopf = braided Sunday bread, Schoggi = chocolate, Kafi = coffee, \
Guetzli = biscuits, Peperoni = bell pepper (not salami), Rahm = cream, Anke = butter, \
Rüebli = carrots, Härdöpfel = potatoes, Poulet = chicken, Glace = ice cream, Konfi = jam.
- Velo = bicycle, Töff = motorbike, Trottinett = scooter, Natel = mobile phone, \
Spital = hospital, Billett = ticket, Trottoir = pavement, Estrich = attic, Lavabo = sink, \
Kollege = friend/mate, Büez/Chrampf = work, poschte = to go shopping, parkieren = to park, \
luege = to look, schaffe = to work, gäll = right?, öppe = about/sometimes.
- Swiss German often uses the perfect tense ("ich ha gha" = I had): use natural Russian tense.

Translate only the text under "Translate:" into natural, fluent Russian.
- Use the earlier lines only as context; do not translate them again.
- If a word was clearly misrecognised, translate what the speaker most likely meant.
- Keep names, places, companies and numbers. Keep Swiss terms that have no Russian equivalent \
in their usual form (e.g. Rösti -> рёшти).
- Reply with the Russian translation only: no quotes, notes, or explanations."""

# Models that accept output_config.effort / server-side refusal fallbacks.
_EFFORT_MODELS = re.compile(r"^claude-(opus|sonnet|haiku|fable|mythos)-5|^claude-(opus-4-[678]|sonnet-4-6)")
_FALLBACK_MODELS = {"claude-fable-5-1", "claude-opus-5-5", "claude-opus-5", "claude-sonnet-5-5"}


class ClaudeTranslator(Translator):
    DEFAULT_MODEL = "claude-opus-5-5"

    def __init__(self, model: str | None = None, dialect: str | None = None, effort: str = "low",
                 api_key: str | None = None):
        try:
            import anthropic
        except ImportError as e:
            raise TranslationError('Claude needs: pip install "swiss-ru-de[claude]"') from e
        self._anthropic = anthropic
        self.model = model or self.DEFAULT_MODEL
        self.name = f"Claude ({self.model})"
        self.effort = effort
        api_key = api_key or keys.get_key("anthropic")
        options = {"api_key": api_key} if api_key else {}
        try:
            self.client = anthropic.Anthropic(timeout=30.0, max_retries=2, **options)
        except anthropic.AnthropicError as e:  # no key configured anywhere
            raise TranslationError("Add your Anthropic API key in Settings (or ANTHROPIC_API_KEY)") from e
        self.system = CLAUDE_SYSTEM
        if DIALECTS.get(dialect or "auto"):
            self.system += f"\n\nThe speaker most likely speaks {DIALECTS[dialect]}."

    def _request(self, text: str, context: Sequence[str]) -> dict:
        prompt = ""
        if context:
            prompt += "Earlier lines (context only):\n" + "\n".join(context) + "\n\n"
        prompt += "Translate:\n" + text
        req: dict = dict(
            model=self.model,
            max_tokens=4096,
            system=self.system,
            messages=[{"role": "user", "content": prompt}],
        )
        if _EFFORT_MODELS.match(self.model):
            req["output_config"] = {"effort": self.effort}  # low = fastest
        return req

    def translate(self, text: str, context: Sequence[str] = ()) -> str:
        a = self._anthropic
        req = self._request(text, context)
        try:
            if self.model in _FALLBACK_MODELS:
                # if a request is declined, the API retries it on a fallback model
                resp = self.client.beta.messages.create(
                    betas=["server-side-fallback-2026-07-01"], fallbacks="default", **req
                )
            else:
                resp = self.client.messages.create(**req)
        except a.AuthenticationError as e:
            raise TranslationError("Anthropic API key is invalid (check Settings)") from e
        except a.NotFoundError as e:
            raise TranslationError(f"Unknown Claude model '{self.model}'") from e
        except a.RateLimitError as e:
            raise TranslationError("Claude rate limit reached, try again shortly") from e
        except a.APIStatusError as e:
            raise TranslationError(f"Claude API error {e.status_code}: {e.message}") from e
        except a.APIConnectionError as e:
            raise TranslationError("Cannot reach the Claude API (network)") from e
        if resp.stop_reason == "refusal":
            return ""
        return "".join(b.text for b in resp.content if b.type == "text").strip()


# ------------------------------------------------------------------------ DeepL
class DeepLTranslator(Translator):
    name = "DeepL"

    def __init__(self, auth_key: str | None = None):
        try:
            import deepl
        except ImportError as e:
            raise TranslationError('DeepL needs: pip install "swiss-ru-de[deepl]"') from e
        key = auth_key or keys.get_key("deepl")
        if not key:
            raise TranslationError("Add your DeepL key in Settings (free key: https://www.deepl.com/pro-api)")
        self._deepl = deepl
        client_cls = getattr(deepl, "DeepLClient", None) or deepl.Translator
        self.client = client_cls(key)

    def translate(self, text: str, context: Sequence[str] = ()) -> str:
        try:
            result = self.client.translate_text(
                normalize_swiss_terms(text, context), source_lang="DE", target_lang="RU",
                context=" ".join(context) or None,
            )
        except self._deepl.DeepLException as e:
            raise TranslationError(f"DeepL error: {e}") from e
        return result.text


# ---------------------------------------------------------------------- offline
class OfflineTranslator(Translator):
    """Local translation model. Default NLLB-200 (600M); any MarianMT German->Russian
    model also works (``--offline-model``).

    On first use the model is converted to CTranslate2 int8 (cached in the user config
    folder): about 3x faster than PyTorch on a CPU and it uses only a few CPU threads, so
    it does not slow down speech recognition. Falls back to PyTorch if that fails."""

    def __init__(self, model: str | None = None, log=print):
        try:
            from transformers import AutoTokenizer
        except ImportError as e:
            raise TranslationError('Offline translation needs: pip install "swiss-ru-de[offline]"') from e
        self.model_name = model or DEFAULT_OFFLINE_MODEL
        self.name = f"offline ({self.model_name})"
        self.log = log
        self.nllb = "nllb" in self.model_name.lower()
        log(f"Loading translation model {self.model_name} (first run downloads it) ...")
        self.tok = AutoTokenizer.from_pretrained(
            self.model_name, **({"src_lang": "deu_Latn"} if self.nllb else {}))
        self._ct2 = None
        self._torch_model = None
        try:
            self._ct2 = self._load_ct2()
        except Exception as e:
            log(f"Fast offline translation not available ({e}); using PyTorch.")
            self._load_torch()

    def _load_ct2(self):
        import ctranslate2

        from .settings import config_dir

        out = config_dir() / "models" / (re.sub(r"[^\w.-]", "_", self.model_name) + "-ct2-int8")
        if not (out / "model.bin").exists():
            self.log("Optimising the translation model for this PC (once, about a minute) ...")
            from ctranslate2.converters import TransformersConverter

            tmp = out.with_name(out.name + ".tmp")
            shutil.rmtree(tmp, ignore_errors=True)
            TransformersConverter(self.model_name).convert(str(tmp), quantization="int8", force=True)
            shutil.rmtree(out, ignore_errors=True)
            tmp.rename(out)
        from .asr import pick_device

        device = pick_device("auto")  # NVIDIA GPU if usable: translation in a few ms
        threads = max(1, min(4, (os.cpu_count() or 4) // 4))
        return ctranslate2.Translator(str(out), device=device,
                                      compute_type="int8_float16" if device == "cuda" else "int8",
                                      inter_threads=1, intra_threads=threads)

    def _load_torch(self) -> None:
        import torch
        from transformers import AutoModelForSeq2SeqLM

        torch.set_num_threads(max(1, min(4, (os.cpu_count() or 4) // 4)))
        self._torch = torch
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        self._torch_model = AutoModelForSeq2SeqLM.from_pretrained(self.model_name).to(self.device).eval()
        self.gen = {"max_new_tokens": 256, "num_beams": 2, "repetition_penalty": 1.2,
                    "no_repeat_ngram_size": 3}
        if self.nllb:
            self.gen["forced_bos_token_id"] = self.tok.convert_tokens_to_ids("rus_Cyrl")

    def translate(self, text: str, context: Sequence[str] = ()) -> str:
        text = normalize_swiss_terms(text, context)
        if self._ct2 is not None:
            try:
                return self._translate_ct2(text)
            except Exception as e:
                self.log(f"Fast offline translation failed ({e}); switching to PyTorch.")
                self._ct2 = None
                self._load_torch()
        return self._translate_torch(text)

    def _translate_ct2(self, text: str) -> str:
        source = self.tok.convert_ids_to_tokens(self.tok.encode(text, truncation=True, max_length=512))
        prefix = [["rus_Cyrl"]] if self.nllb else None
        result = self._ct2.translate_batch([source], target_prefix=prefix, beam_size=2,
                                           max_decoding_length=256, repetition_penalty=1.2,
                                           no_repeat_ngram_size=3)  # no "есть есть есть"
        tokens = result[0].hypotheses[0]
        if self.nllb and tokens and tokens[0] == "rus_Cyrl":
            tokens = tokens[1:]
        return self.tok.decode(self.tok.convert_tokens_to_ids(tokens), skip_special_tokens=True).strip()

    def _translate_torch(self, text: str) -> str:
        with self._torch.inference_mode():
            batch = self.tok([text], return_tensors="pt", truncation=True, max_length=512).to(self.device)
            out = self._torch_model.generate(**batch, **self.gen)
        return self.tok.decode(out[0], skip_special_tokens=True).strip()


# ---------------------------------------------------------------------- factory
def resolve_kind(kind: str) -> str:
    """What "auto" means right now: the best translator that has a key."""
    if kind != "auto":
        return kind
    if keys.has_key("anthropic"):
        return "claude"
    if keys.has_key("deepl"):
        return "deepl"
    return "offline"


QUALITY_LABEL = {"claude": "Claude", "deepl": "DeepL", "offline": "offline, basic quality"}


def make_translator(
    kind: str = "auto",
    target: str = "ru",
    claude_model: str | None = None,
    offline_model: str | None = None,
    dialect: str | None = None,
    log=print,
) -> Translator:
    if target == "de":
        return Passthrough()
    kind = resolve_kind(kind)
    if kind == "claude":
        return ClaudeTranslator(model=claude_model, dialect=dialect)
    if kind == "deepl":
        return DeepLTranslator()
    if kind == "offline":
        return OfflineTranslator(model=offline_model, log=log)
    raise ValueError(f"unknown translator {kind!r}")


class TranslatorHub:
    """Creates translators lazily and keeps them, so the GUI can switch translator,
    dialect or target language while running. ``get`` is called from the translation
    thread, so slow model loading never blocks the window."""

    def __init__(self, kind: str = "auto", claude_model: str | None = None,
                 offline_model: str | None = None, dialect: str | None = None, log=print):
        self.config = dict(kind=kind, claude_model=claude_model or None,
                           offline_model=offline_model, dialect=dialect)
        self.log = log
        self._cache: dict[tuple, Translator] = {}
        self._lock = threading.Lock()

    def configure(self, **changes) -> None:
        with self._lock:
            self.config.update(changes)

    def reset(self) -> None:
        """Forget created translators, e.g. after API keys changed."""
        with self._lock:
            self._cache.clear()

    def get(self, target: str) -> Translator:
        if target == "de":
            return Passthrough()
        with self._lock:
            key = tuple(sorted(self.config.items()))
            if key not in self._cache:
                c = self.config
                self._cache[key] = make_translator(c["kind"], target, c["claude_model"],
                                                   c["offline_model"], c["dialect"], log=self.log)
            return self._cache[key]
