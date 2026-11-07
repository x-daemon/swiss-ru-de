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
    assert t.model == "gemma3:4b" and t.corrects  # nothing installed: the suggested model
    assert str(t.client.base_url).startswith("http://localhost:1234/v1")
    assert "extra_body" not in t.options  # keep_alive is for Ollama only
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
    with pytest.raises(TranslationError, match="ollama pull gemma3:4b"):
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


def test_local_model_defaults_to_an_installed_one(monkeypatch):
    monkeypatch.setattr(translate, "local_models", lambda url: ["gemma3:12b", "llama3.2:3b"])
    assert OpenAICompatibleTranslator("local").model == "gemma3:12b"
    monkeypatch.setattr(translate, "local_models", lambda url: ["gemma3:12b", "gemma3:4b"])
    assert OpenAICompatibleTranslator("local").model == "gemma3:4b"  # the fast one first
    monkeypatch.setattr(translate, "local_models", lambda url: ["mistral:7b"])
    assert OpenAICompatibleTranslator("local").model == "mistral:7b"
    assert OpenAICompatibleTranslator("local", model="qwen3:14b").model == "qwen3:14b"


def test_local_requests_are_short_and_fast():
    t, fake = make_local(['{"russian": "Два круассана."}'])
    assert t.process("Zwei Gipfeli bitte", correct=False) == (None, "Два круассана.")
    call = fake.calls[0]
    assert call["response_format"]["json_schema"]["schema"]["required"] == ["russian"]  # half the answer
    assert call["reasoning_effort"] == "none"  # no thinking
    assert call["temperature"] == 0.2
    assert call["extra_body"] == {"keep_alive": "30m"}  # stays in the graphics card
    assert call["max_completion_tokens"] == 128 + 6 * 3  # a stuck model cannot run for minutes
    t, fake = make_local(['{"german": "Ja.", "russian": "Да."}'])
    t.process("Ja")
    assert fake.calls[0]["response_format"]["json_schema"]["schema"]["required"] == ["german", "russian"]


def test_local_drops_thinking_option_if_the_model_rejects_it():
    t, fake = make_local([FakeBadRequest('"gemma3:4b" does not support thinking'),
                          '{"german": "Ja.", "russian": "Да."}'])
    assert t.process("Ja") == ("Ja.", "Да.")
    assert "reasoning_effort" not in fake.calls[1] and fake.calls[1]["temperature"] == 0.2


def test_cut_off_answer_keeps_the_translation():
    assert parse_answer('{"german": "Zwei Gipfeli.", "russian": "Два круа', "ru") == \
        ("Zwei Gipfeli.", "Два круа")
    assert parse_answer('{"russian": "Он сказал \\"да\\" и', "ru") == (None, 'Он сказал "да" и')
    assert parse_answer("nothing useful", "ru") == (None, "")


def test_ollama_gpu_share_and_warning(monkeypatch):
    import io
    import json
    import urllib.request

    answer = {"models": [{"name": "gemma3:12b", "model": "gemma3:12b", "size": 10_000, "size_vram": 6_000}]}
    seen = []

    def fake_urlopen(url, timeout=None):
        seen.append(url)
        return io.BytesIO(json.dumps(answer).encode())

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    assert translate.local_gpu_share("http://localhost:11434/v1", "gemma3:12b") == 0.6
    assert seen == ["http://localhost:11434/api/ps"]
    assert translate.local_gpu_share("http://localhost:11434/v1", "qwen3:14b") is None
    t, _ = make_local([])
    t.model = "gemma3:12b"
    warning = t.gpu_warning()
    assert "40 % on the processor" in warning and "gemma3:4b" in warning
    assert t.gpu_warning() is None  # said once
    answer["models"][0]["size_vram"] = 10_000
    t._gpu_checked = False
    assert t.gpu_warning() is None  # all in the graphics card: fine


def test_warm_up_loads_the_local_model():
    t, fake = make_local(["ok"])
    t.warm_up()
    assert fake.calls[0]["max_completion_tokens"] == 1
    assert fake.calls[0]["extra_body"] == {"keep_alive": "30m"}
    t, fake = make_local([ConnectionError("not running")])
    t.warm_up()  # no error: the first sentence reports it
