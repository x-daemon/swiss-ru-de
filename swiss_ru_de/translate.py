"""German -> Russian translation backends.

* ``claude``  - best quality, understands context and leftover dialect words
                (Anthropic API key: Settings or ANTHROPIC_API_KEY)
* ``deepl``   - very good, fast (DeepL key: Settings or DEEPL_AUTH_KEY, free tier)
* ``offline`` - runs locally, no key, no internet after the first download (NLLB,
                converted to CTranslate2 int8 on first use: ~3x faster than PyTorch)
"""

from __future__ import annotations

import json
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
    # meals ("zum Morgen" is how the speech model writes "Zmorge"; Standard German says
    # "am Morgen", so this only changes the Swiss usage)
    (r"zum morge[n]?", "zum Frühstück"),
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
    (r"blutorangen", "rote Orangen"),
    (r"blutorange", "rote Orange"),
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


_SENTENCE_END = re.compile(r"(?<=[.!?…])\s+(?=[\"'„«(]?[A-ZÄÖÜ0-9])")


def split_sentences(text: str) -> list[str]:
    """Split at . ! ? followed by a capitalised word; very short pieces ("Ja.") are kept
    as their own sentence."""
    return [s.strip() for s in _SENTENCE_END.split(text.strip()) if s.strip()]


def _plural_before(text: str, match: re.Match) -> bool:
    before = text[: match.start()].split()[-1:] or [""]
    word = before[0].lower()
    return word.isdigit() and word != "1" or word in {
        "zwei", "drei", "vier", "fünf", "sechs", "paar", "viele", "einige", "mehrere", "die"}


class TranslationError(RuntimeError):
    pass


class Translator:
    name = "none"
    corrects = False  # True if it can also fix recognition errors (Claude)

    def translate(self, text: str, context: Sequence[str] = ()) -> str:
        raise NotImplementedError

    def process(self, german: str, dialect: str | None = None, context: Sequence[str] = (),
                target: str = "ru") -> tuple[str | None, str | None]:
        """Returns (corrected German or None, translation or None)."""
        if target == "de":
            return None, None
        return None, self.translate(german, context)


class Passthrough(Translator):
    """Target language German: the recogniser already produces Standard German."""

    name = "none (German)"

    def translate(self, text: str, context: Sequence[str] = ()) -> str:
        return text


# ----------------------------------------------------------------------- Claude
_SWISS_HINTS = """Typical traps - use the meaning:
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
- Swiss German often uses the perfect tense ("ich ha gha" = I had): use natural tenses."""

CLAUDE_SYSTEM = f"""You turn live speech recognition of Swiss German into clean subtitles.

For each utterance you get:
- "Recognised": Standard German from a speech model trained on Swiss German. Usually the best \
source for the meaning, but it can mishear or drop words, miss punctuation, leave dialect words \
(öppis, gsi, lueg, äbe, gäll, nöd, nüt, chli, gönd, zäme, Grüezi, Grüessech, merci vilmal) or \
turn Swiss words into the wrong Standard German word.
- Sometimes "As heard": the same audio written closer to the dialect by a second, general \
model. Less accurate overall, but it can keep words the first model changed.
- Earlier lines (already corrected), for context only.

{_SWISS_HINTS}

Answer with JSON:
- "german": the utterance as correct, natural Standard German. Fix clear recognition errors \
using both versions and the context. Keep the speaker's meaning and wording otherwise; do not \
add or summarise; keep names, places and numbers.
- "russian" (only when the schema asks for it): a natural, fluent Russian translation of that \
German sentence. Keep Swiss terms that have no Russian equivalent in their usual form \
(e.g. Rösti -> рёшти)."""

_SCHEMAS = {
    target: {
        "type": "object",
        "properties": {"german": {"type": "string"}, **({"russian": {"type": "string"}} if target == "ru" else {})},
        "required": ["german", "russian"] if target == "ru" else ["german"],
        "additionalProperties": False,
    }
    for target in ("ru", "de")
}

LLM_KINDS = ("claude", "openai", "gemini", "grok", "local")  # these also correct recognition errors


def build_prompt(german: str, dialect: str | None, context: Sequence[str]) -> str:
    prompt = ""
    if context:
        prompt += "Earlier lines (context only):\n" + "\n".join(context) + "\n\n"
    prompt += f"Recognised: {german}"
    if dialect and dialect.strip() and dialect.strip() != german.strip():
        prompt += f"\nAs heard: {dialect}"
    return prompt


def parse_answer(text: str, target: str) -> tuple[str | None, str | None]:
    """{"german": ..., "russian": ...} -> (corrected German, translation)."""
    empty = (None, "" if target == "ru" else None)
    text = _THINK.sub("", text or "").strip()  # reasoning models may show their thinking
    try:
        data = json.loads(text)
    except ValueError:
        match = re.search(r"\{.*\}", text or "", re.DOTALL)  # JSON inside extra text
        try:
            data = json.loads(match.group(0)) if match else None
        except ValueError:
            data = None
    if not isinstance(data, dict):
        return empty
    fixed = str(data.get("german") or "").strip() or None
    return fixed, (str(data.get("russian") or "").strip() if target == "ru" else None)


# Models that accept output_config.effort / server-side refusal fallbacks.
_EFFORT_MODELS = re.compile(r"^claude-(opus|sonnet|haiku|fable|mythos)-5|^claude-(opus-4-[678]|sonnet-4-6)")
_FALLBACK_MODELS = {"claude-fable-5-1", "claude-opus-5-5", "claude-opus-5", "claude-sonnet-5-5"}


class ClaudeTranslator(Translator):
    """Corrects the recognised German (with the dialect line as a second hearing and the
    earlier sentences as context) and translates it, in one request with JSON output."""

    DEFAULT_MODEL = "claude-opus-5-5"
    corrects = True

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

    def _request(self, german: str, dialect: str | None, context: Sequence[str], target: str) -> dict:
        prompt = build_prompt(german, dialect, context)
        output_config: dict = {"format": {"type": "json_schema", "schema": _SCHEMAS[target]}}
        if _EFFORT_MODELS.match(self.model):
            output_config["effort"] = self.effort  # low = fastest
        return dict(
            model=self.model,
            max_tokens=4096,
            system=self.system,
            messages=[{"role": "user", "content": prompt}],
            output_config=output_config,
        )

    def process(self, german: str, dialect: str | None = None, context: Sequence[str] = (),
                target: str = "ru") -> tuple[str | None, str | None]:
        a = self._anthropic
        target = "de" if target == "de" else "ru"
        req = self._request(german, dialect, context, target)
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
        if resp.stop_reason in ("refusal", "max_tokens"):
            return None, ("" if target == "ru" else None)
        return parse_answer(next((b.text for b in resp.content if b.type == "text"), ""), target)

    def translate(self, text: str, context: Sequence[str] = ()) -> str:
        return self.process(text, None, context, "ru")[1] or ""


# ------------------------------------------------- ChatGPT / Gemini / Grok
# All three offer an OpenAI-compatible Chat Completions API, so one client (the official
# openai SDK) serves them; only the address, key and model differ.
PROVIDERS = {
    "openai": dict(label="ChatGPT (OpenAI)", short="ChatGPT", base_url=None,
                   models=["gpt-6-luna", "gpt-6-sol", "gpt-6-astra"], reasoning_effort="low",
                   where="platform.openai.com → API keys"),
    "gemini": dict(label="Gemini (Google)", short="Gemini",
                   base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
                   models=["gemini-3.8-flash", "gemini-3.5-flash-lite"], reasoning_effort=None,
                   where="aistudio.google.com → Get API key"),
    "grok": dict(label="Grok (xAI)", short="Grok", base_url="https://api.x.ai/v1",
                 models=["grok-4.7"], reasoning_effort=None, where="console.x.ai → API keys"),
    # Runs on this PC (GPU): Ollama or LM Studio serve an OpenAI-compatible API, no key.
    "local": dict(label="Local AI (Ollama / LM Studio)", short="Local AI",
                  base_url="http://localhost:11434/v1",
                  models=["gemma3:12b", "gemma3:4b", "qwen3:14b", "translategemma:12b"],
                  reasoning_effort=None, where="ollama.com, then: ollama pull gemma3:12b"),
}
LOCAL_SERVERS = {"Ollama": "http://localhost:11434/v1", "LM Studio": "http://localhost:1234/v1"}
_THINK = re.compile(r"<think>.*?</think>", re.DOTALL)


def local_models(base_url: str, timeout: float = 1.5) -> list[str]:
    """Models installed in a local Ollama / LM Studio server ([] if it is not running)."""
    try:
        import openai

        client = openai.OpenAI(api_key="local", base_url=base_url, timeout=timeout, max_retries=0)
        return sorted(m.id for m in client.models.list())
    except Exception:
        return []


class OpenAICompatibleTranslator(Translator):
    """ChatGPT, Gemini or Grok: corrects the recognised German and translates it, like
    ClaudeTranslator, with the same instructions and JSON answer."""

    corrects = True

    def __init__(self, provider: str, model: str | None = None, dialect: str | None = None,
                 api_key: str | None = None, base_url: str | None = None):
        try:
            import openai
        except ImportError as e:
            raise TranslationError('ChatGPT/Gemini/Grok need: pip install "swiss-ru-de[llm]"') from e
        self._openai = openai
        info = PROVIDERS[provider]
        self.provider = provider
        self.model = model or info["models"][0]
        self.name = f"{info['short']} ({self.model})"
        self.base_url = base_url or info["base_url"]
        if provider == "local":
            key = "local"  # Ollama / LM Studio need no key
            # the first request loads the model into the graphics card: allow time
            self.client = openai.OpenAI(api_key=key, base_url=self.base_url, timeout=180.0, max_retries=1)
        else:
            key = api_key or keys.get_key(provider)
            if not key:
                raise TranslationError(f"Add your {info['short']} API key in Settings ({info['where']})")
            self.client = openai.OpenAI(api_key=key, base_url=self.base_url, timeout=30.0, max_retries=2)
        # Translation-only models (TranslateGemma) get a plain translation request.
        self.plain = "translate" in self.model.lower()
        if self.plain:
            self.corrects = False
        self.system = CLAUDE_SYSTEM + "\n\nReply with the JSON object only."
        if DIALECTS.get(dialect or "auto"):
            self.system += f"\n\nThe speaker most likely speaks {DIALECTS[dialect]}."
        # Optional request features; dropped automatically if a model rejects them.
        self.options: dict = {}
        if info["reasoning_effort"]:
            self.options["reasoning_effort"] = info["reasoning_effort"]  # faster answers

    def _request(self, german: str, dialect: str | None, context: Sequence[str], target: str) -> dict:
        schema = {"type": "json_schema",
                  "json_schema": {"name": "subtitle", "schema": _SCHEMAS[target], "strict": True}}
        return dict(
            model=self.model,
            messages=[{"role": "system", "content": self.system},
                      {"role": "user", "content": build_prompt(german, dialect, context)}],
            response_format=self.options.get("response_format", schema),
            max_completion_tokens=4096,
            **{k: v for k, v in self.options.items() if k != "response_format"},
        )

    def _plain_translation(self, german: str, context: Sequence[str]) -> str:
        text = normalize_swiss_terms(german, context)
        resp = self.client.chat.completions.create(model=self.model, messages=[{
            "role": "user",
            "content": f"Translate the following text from German to Russian:\n\n{text}"}])
        return _THINK.sub("", resp.choices[0].message.content or "").strip()

    def process(self, german: str, dialect: str | None = None, context: Sequence[str] = (),
                target: str = "ru") -> tuple[str | None, str | None]:
        o = self._openai
        target = "de" if target == "de" else "ru"
        if self.plain:
            if target == "de":
                return None, None
            try:
                return None, self._plain_translation(german, context)
            except o.APIConnectionError as e:
                raise TranslationError(self._unreachable()) from e
            except o.NotFoundError as e:
                raise TranslationError(self._not_installed()) from e
        for _ in range(3):  # retries only to drop options a model does not support
            try:
                resp = self.client.chat.completions.create(**self._request(german, dialect, context, target))
                break
            except o.BadRequestError as e:
                message = str(e).lower()
                if "reasoning" in message and "reasoning_effort" in self.options:
                    del self.options["reasoning_effort"]
                elif ("response_format" in message or "json_schema" in message) and \
                        "response_format" not in self.options:
                    self.options["response_format"] = {"type": "json_object"}
                else:
                    raise TranslationError(f"{self.name}: {e}") from e
            except o.AuthenticationError as e:
                raise TranslationError(f"{PROVIDERS[self.provider]['short']} API key is invalid (check Settings)") from e
            except o.NotFoundError as e:
                if self.provider == "local":
                    raise TranslationError(self._not_installed()) from e
                raise TranslationError(f"Unknown model '{self.model}' (check Settings)") from e
            except o.RateLimitError as e:
                raise TranslationError(f"{self.name}: rate limit or quota reached") from e
            except o.APIStatusError as e:
                raise TranslationError(f"{self.name} error {e.status_code}") from e
            except o.APIConnectionError as e:
                if self.provider == "local":
                    raise TranslationError(self._unreachable()) from e
                raise TranslationError(f"Cannot reach {PROVIDERS[self.provider]['short']} (network)") from e
        else:
            raise TranslationError(f"{self.name}: request rejected")
        choice = resp.choices[0] if resp.choices else None
        if choice is None or getattr(choice.message, "refusal", None):
            return None, ("" if target == "ru" else None)
        return parse_answer(choice.message.content or "", target)

    def translate(self, text: str, context: Sequence[str] = ()) -> str:
        return self.process(text, None, context, "ru")[1] or ""

    def _unreachable(self) -> str:
        return (f"Local AI not reachable at {self.base_url}. Start Ollama (or LM Studio's "
                f"server) - see Settings.")

    def _not_installed(self) -> str:
        return f"Model '{self.model}' is not installed. Run: ollama pull {self.model}"


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
        # NLLB is trained on single sentences: given several at once it drops most of them,
        # and repeated words across sentences confuse it. So: one sentence at a time.
        sentences, seen = [], list(context)
        for sentence in split_sentences(text):
            fixed = normalize_swiss_terms(sentence, seen)
            sentences.append(fixed[:1].upper() + fixed[1:])
            seen.append(sentence)  # Gipfel at breakfast: earlier sentences count as context
        if not sentences:
            return ""
        if self._ct2 is not None:
            try:
                return " ".join(self._translate_ct2(sentences))
            except Exception as e:
                self.log(f"Fast offline translation failed ({e}); switching to PyTorch.")
                self._ct2 = None
                self._load_torch()
        return " ".join(self._translate_torch(sentences))

    def _translate_ct2(self, sentences: list[str]) -> list[str]:
        sources = [self.tok.convert_ids_to_tokens(self.tok.encode(s, truncation=True, max_length=512))
                   for s in sentences]
        prefix = [["rus_Cyrl"]] * len(sources) if self.nllb else None
        results = self._ct2.translate_batch(sources, target_prefix=prefix, beam_size=2,
                                            max_decoding_length=256, repetition_penalty=1.2,
                                            no_repeat_ngram_size=3)  # no "есть есть есть"
        out = []
        for result in results:
            tokens = result.hypotheses[0]
            if self.nllb and tokens and tokens[0] == "rus_Cyrl":
                tokens = tokens[1:]
            out.append(self.tok.decode(self.tok.convert_tokens_to_ids(tokens), skip_special_tokens=True).strip())
        return out

    def _translate_torch(self, sentences: list[str]) -> list[str]:
        with self._torch.inference_mode():
            batch = self.tok(sentences, return_tensors="pt", padding=True, truncation=True,
                             max_length=512).to(self.device)
            out = self._torch_model.generate(**batch, **self.gen)
        return [self.tok.decode(o, skip_special_tokens=True).strip() for o in out]


# ---------------------------------------------------------------------- factory
def resolve_kind(kind: str) -> str:
    """What "auto" means right now: the best translator that has a key."""
    if kind != "auto":
        return kind
    if keys.has_key("anthropic"):
        return "claude"
    for provider in ("openai", "gemini", "grok"):  # local AI only when chosen explicitly
        if keys.has_key(provider):
            return provider
    if keys.has_key("deepl"):
        return "deepl"
    return "offline"


QUALITY_LABEL = {"claude": "Claude, corrected", "openai": "ChatGPT, corrected",
                 "gemini": "Gemini, corrected", "grok": "Grok, corrected",
                 "local": "local AI, corrected", "deepl": "DeepL",
                 "offline": "offline, basic quality"}


def make_translator(
    kind: str = "auto",
    target: str = "ru",
    claude_model: str | None = None,
    offline_model: str | None = None,
    dialect: str | None = None,
    log=print,
    models: dict | None = None,
) -> Translator:
    if target == "de":
        return Passthrough()
    kind = resolve_kind(kind)
    if kind == "claude":
        return ClaudeTranslator(model=claude_model, dialect=dialect)
    if kind in PROVIDERS:
        return OpenAICompatibleTranslator(kind, model=(models or {}).get(kind), dialect=dialect,
                                          base_url=(models or {}).get("local_url") if kind == "local" else None)
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
                 offline_model: str | None = None, dialect: str | None = None, log=print,
                 openai_model: str | None = None, gemini_model: str | None = None,
                 grok_model: str | None = None, local_model: str | None = None,
                 local_url: str | None = None):
        self.config = dict(kind=kind, claude_model=claude_model or None,
                           offline_model=offline_model, dialect=dialect,
                           openai_model=openai_model or None, gemini_model=gemini_model or None,
                           grok_model=grok_model or None, local_model=local_model or None,
                           local_url=local_url or None)
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
        if target == "de" and resolve_kind(self.config["kind"]) not in LLM_KINDS:
            return Passthrough()  # only the AI models can improve German output
        target = "ru"  # one translator object serves both targets
        with self._lock:
            key = tuple(sorted(self.config.items()))
            if key not in self._cache:
                c = self.config
                models = {p: c.get(f"{p}_model") for p in PROVIDERS}
                models["local_url"] = c.get("local_url")
                self._cache[key] = make_translator(c["kind"], target, c["claude_model"],
                                                   c["offline_model"], c["dialect"], log=self.log,
                                                   models=models)
            return self._cache[key]
