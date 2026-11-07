"""ChatGPT, Gemini and Grok as translators (OpenAI-compatible APIs)."""

from types import SimpleNamespace

import pytest

from swiss_ru_de import keys, translate
from swiss_ru_de.translate import (PROVIDERS, OpenAICompatibleTranslator, Passthrough, TranslationError,
                                   TranslatorHub, parse_answer, resolve_kind)


class FakeBadRequest(Exception):
    pass


FAKE_ERRORS = SimpleNamespace(BadRequestError=FakeBadRequest, AuthenticationError=KeyError,
                              NotFoundError=LookupError, RateLimitError=OverflowError,
                              APIStatusError=ArithmeticError, APIConnectionError=ConnectionError)


class FakeCompletions:
    def __init__(self, answers):
        self.answers = list(answers)
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=answer, refusal=None))])


def make(provider, answers):
    keys.set_key(provider, "test-key")
    t = OpenAICompatibleTranslator(provider)
    t._openai = FAKE_ERRORS
    fake = FakeCompletions(answers)
    t.client = SimpleNamespace(chat=SimpleNamespace(completions=fake))
    return t, fake


@pytest.mark.parametrize("provider,base_url,model", [
    ("openai", None, "gpt-6-luna"),
    ("gemini", "https://generativelanguage.googleapis.com/v1beta/openai/", "gemini-3.8-flash"),
    ("grok", "https://api.x.ai/v1", "grok-4.7"),
])
def test_providers_correct_and_translate(provider, base_url, model):
    keys.set_key(provider, "test-key")
    real = OpenAICompatibleTranslator(provider)
    assert real.model == model
    assert (str(real.client.base_url).rstrip("/") == base_url.rstrip("/")) if base_url else "openai.com" in str(real.client.base_url)
    t, fake = make(provider, ['{"german": "Zwei Gipfeli, bitte.", "russian": "Два круассана, пожалуйста."}'])
    assert t.process("Zwei Gipfel, bitte.", "Zwöi Gipfeli, bitte.", ["Grüezi"], "ru") == \
        ("Zwei Gipfeli, bitte.", "Два круассана, пожалуйста.")
    call = fake.calls[0]
    assert call["model"] == model
    assert call["response_format"]["type"] == "json_schema"
    assert call["response_format"]["json_schema"]["schema"]["required"] == ["german", "russian"]
    assert call["messages"][0]["role"] == "system" and "Gipfeli" in call["messages"][0]["content"]
    assert call["messages"][1]["content"].endswith("As heard: Zwöi Gipfeli, bitte.")
    assert ("reasoning_effort" in call) == (provider == "openai")


def test_unsupported_options_are_dropped_and_remembered():
    t, fake = make("openai", [FakeBadRequest("Unsupported parameter: 'reasoning_effort'"),
                              FakeBadRequest("response_format json_schema is not supported"),
                              '{"german": "Hallo."}', '{"german": "Tschüss."}'])
    assert t.process("Hallo", target="de") == ("Hallo.", None)
    assert "reasoning_effort" not in fake.calls[-1]
    assert fake.calls[-1]["response_format"] == {"type": "json_object"}
    t.process("Tschüss", target="de")
    assert len(fake.calls) == 4  # no more retries once adapted


def test_errors_and_missing_keys_are_clear():
    with pytest.raises(TranslationError, match="Grok API key"):
        OpenAICompatibleTranslator("grok")
    t, _ = make("gemini", [KeyError("401")])
    with pytest.raises(TranslationError, match="Gemini API key is invalid"):
        t.process("x")


def test_answers_with_extra_text_are_still_read():
    assert parse_answer('Sure! {"german": "Ja.", "russian": "Да."} Hope this helps', "ru") == ("Ja.", "Да.")
    assert parse_answer("not json", "ru") == (None, "")


def test_auto_order_and_german_target():
    assert resolve_kind("auto") == "offline"
    keys.set_key("gemini", "g")
    assert resolve_kind("auto") == "gemini"
    keys.set_key("openai", "o")
    assert resolve_kind("auto") == "openai"
    keys.set_key("anthropic", "a")
    assert resolve_kind("auto") == "claude"
    hub = TranslatorHub("grok")
    keys.set_key("grok", "x")
    assert isinstance(hub.get("de"), OpenAICompatibleTranslator)  # also corrects German
    assert isinstance(TranslatorHub("deepl").get("de"), Passthrough)


def test_hub_passes_the_chosen_model():
    keys.set_key("openai", "o")
    hub = TranslatorHub("openai", openai_model="gpt-6-sol")
    assert hub.get("ru").model == "gpt-6-sol"
    assert set(PROVIDERS) == {"openai", "gemini", "grok", "local"}
    assert translate.QUALITY_LABEL["grok"].startswith("Grok")


def test_gemini_key_from_google_api_key(monkeypatch):
    monkeypatch.setenv("GOOGLE_API_KEY", "g-env")
    assert keys.get_key("gemini") == "g-env"


def test_local_ai_needs_no_key_and_uses_the_local_server():
    t = OpenAICompatibleTranslator("local", base_url="http://localhost:1234/v1")
    assert t.model == "gemma3:12b" and t.corrects
    assert str(t.client.base_url).startswith("http://localhost:1234/v1")
    hub = TranslatorHub("local", local_model="qwen3:14b", local_url="http://127.0.0.1:11434/v1")
    tr = hub.get("ru")
    assert tr.model == "qwen3:14b" and tr.base_url == "http://127.0.0.1:11434/v1"
    assert isinstance(hub.get("de"), OpenAICompatibleTranslator)  # corrects German too
    assert resolve_kind("auto") != "local"  # never chosen automatically


def test_local_errors_explain_what_to_do():
    t, _ = make_local([ConnectionError("refused")])
    with pytest.raises(TranslationError, match="Start Ollama"):
        t.process("x")
    t, _ = make_local([LookupError("model not found")])
    with pytest.raises(TranslationError, match="ollama pull gemma3:12b"):
        t.process("x")


def test_thinking_is_ignored_and_translation_models_get_a_plain_prompt():
    t, fake = make_local(['<think>{"german": "no"}</think>{"german": "Ja.", "russian": "Да."}'])
    assert t.process("Ja") == ("Ja.", "Да.")
    t = OpenAICompatibleTranslator("local", model="translategemma:12b")
    t._openai = FAKE_ERRORS
    fake = FakeCompletions(["<think>hm</think>Два круассана."])
    t.client = SimpleNamespace(chat=SimpleNamespace(completions=fake))
    assert not t.corrects
    assert t.process("Zwei Gipfeli.") == (None, "Два круассана.")
    assert "response_format" not in fake.calls[0]
    assert "Croissants" in fake.calls[0]["messages"][0]["content"]  # Swiss words normalised
    assert t.process("Zwei Gipfeli.", target="de") == (None, None)


def make_local(answers):
    t = OpenAICompatibleTranslator("local")
    t._openai = FAKE_ERRORS
    fake = FakeCompletions(answers)
    t.client = SimpleNamespace(chat=SimpleNamespace(completions=fake))
    return t, fake
