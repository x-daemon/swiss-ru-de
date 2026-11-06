"""German -> Russian translation backends.

* ``claude``  - best quality, understands context and leftover dialect words
                (needs ANTHROPIC_API_KEY)
* ``deepl``   - very good, fast (needs DEEPL_AUTH_KEY, free tier available)
* ``offline`` - runs locally, no key, no internet after the first download (NLLB)
"""

from __future__ import annotations

import os
import re
import threading
from typing import Sequence

from .config import DEFAULT_OFFLINE_MODEL, DIALECTS


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

    def __init__(self, model: str | None = None, dialect: str | None = None, effort: str = "low"):
        try:
            import anthropic
        except ImportError as e:
            raise TranslationError('Claude needs: pip install "swiss-ru-de[claude]"') from e
        self._anthropic = anthropic
        self.model = model or self.DEFAULT_MODEL
        self.name = f"Claude ({self.model})"
        self.effort = effort
        self.client = anthropic.Anthropic(timeout=30.0, max_retries=2)
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
            raise TranslationError("Anthropic API key is invalid (ANTHROPIC_API_KEY)") from e
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
        key = auth_key or os.environ.get("DEEPL_AUTH_KEY")
        if not key:
            raise TranslationError("Set DEEPL_AUTH_KEY (free key: https://www.deepl.com/pro-api)")
        self._deepl = deepl
        client_cls = getattr(deepl, "DeepLClient", None) or deepl.Translator
        self.client = client_cls(key)

    def translate(self, text: str, context: Sequence[str] = ()) -> str:
        try:
            result = self.client.translate_text(
                text, source_lang="DE", target_lang="RU", context=" ".join(context) or None
            )
        except self._deepl.DeepLException as e:
            raise TranslationError(f"DeepL error: {e}") from e
        return result.text


# ---------------------------------------------------------------------- offline
class OfflineTranslator(Translator):
    """Local seq2seq model via transformers. Default NLLB-200 (600M); any MarianMT
    German->Russian model also works (``--offline-model``)."""

    def __init__(self, model: str | None = None, log=print):
        try:
            import torch
            from transformers import AutoModelForSeq2SeqLM, AutoTokenizer
        except ImportError as e:
            raise TranslationError('Offline translation needs: pip install "swiss-ru-de[offline]"') from e
        model = model or DEFAULT_OFFLINE_MODEL
        self.name = f"offline ({model})"
        log(f"Loading translation model {model} (first run downloads it) ...")
        self._torch = torch
        nllb = "nllb" in model.lower()
        self.tok = AutoTokenizer.from_pretrained(model, **({"src_lang": "deu_Latn"} if nllb else {}))
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        self.model = AutoModelForSeq2SeqLM.from_pretrained(model).to(self.device).eval()
        self.gen = {"max_new_tokens": 256, "num_beams": 2}
        if nllb:
            self.gen["forced_bos_token_id"] = self.tok.convert_tokens_to_ids("rus_Cyrl")

    def translate(self, text: str, context: Sequence[str] = ()) -> str:
        with self._torch.inference_mode():
            batch = self.tok([text], return_tensors="pt", truncation=True, max_length=512).to(self.device)
            out = self.model.generate(**batch, **self.gen)
        return self.tok.decode(out[0], skip_special_tokens=True).strip()


# ---------------------------------------------------------------------- factory
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
    if kind == "auto":
        if os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"):
            kind = "claude"
        elif os.environ.get("DEEPL_AUTH_KEY"):
            kind = "deepl"
        else:
            kind = "offline"
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
