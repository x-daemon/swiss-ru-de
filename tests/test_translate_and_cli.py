from types import SimpleNamespace

import pytest

from swiss_ru_de import translate
from swiss_ru_de.cli import build_parser
from swiss_ru_de.translate import ClaudeTranslator, Passthrough, TranslationError, make_translator


def test_german_target_needs_no_translator(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    assert isinstance(make_translator("auto", "de"), Passthrough)


def test_auto_picks_claude_when_key_present(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    t = make_translator("auto", "ru", dialect="berner-oberland")
    assert isinstance(t, ClaudeTranslator)
    assert t.model == "claude-opus-5-5"
    assert "Grindelwald" in t.system


def test_auto_picks_deepl_then_offline(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    monkeypatch.setenv("DEEPL_AUTH_KEY", "abc:fx")
    assert isinstance(make_translator("auto", "ru"), translate.DeepLTranslator)
    monkeypatch.delenv("DEEPL_AUTH_KEY")
    seen = {}
    monkeypatch.setattr(translate, "OfflineTranslator", lambda model, log: seen.setdefault("m", model))
    make_translator("auto", "ru", offline_model="m1")
    assert seen["m"] == "m1"


def test_deepl_without_key_is_a_clear_error(monkeypatch):
    monkeypatch.delenv("DEEPL_AUTH_KEY", raising=False)
    with pytest.raises(TranslationError, match="DEEPL_AUTH_KEY"):
        make_translator("deepl", "ru")


class FakeMessages:
    def __init__(self, stop_reason="end_turn", text="Привет всем"):
        self.kwargs = None
        self.stop_reason = stop_reason
        self.text = text

    def create(self, **kwargs):
        self.kwargs = kwargs
        return SimpleNamespace(
            stop_reason=self.stop_reason,
            content=[SimpleNamespace(type="thinking", thinking=""),
                     SimpleNamespace(type="text", text=self.text)],
        )


def test_claude_request_shape(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    t = ClaudeTranslator()
    fake = FakeMessages()
    t.client = SimpleNamespace(beta=SimpleNamespace(messages=fake), messages=None)
    assert t.translate("Hoi zäme", ["Guten Morgen"]) == "Привет всем"
    kw = fake.kwargs
    assert kw["model"] == "claude-opus-5-5"
    assert kw["fallbacks"] == "default" and kw["betas"] == ["server-side-fallback-2026-07-01"]
    assert kw["output_config"] == {"effort": "low"}
    content = kw["messages"][0]["content"]
    assert content.endswith("Translate:\nHoi zäme") and "Guten Morgen" in content


def test_claude_other_model_uses_plain_endpoint(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    t = ClaudeTranslator(model="claude-haiku-5-5")
    fake = FakeMessages()
    t.client = SimpleNamespace(beta=None, messages=fake)
    t.translate("Grüezi")
    assert "fallbacks" not in fake.kwargs and fake.kwargs["output_config"] == {"effort": "low"}


def test_claude_refusal_returns_empty(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    t = ClaudeTranslator()
    t.client = SimpleNamespace(beta=SimpleNamespace(messages=FakeMessages("refusal", "")))
    assert t.translate("x") == ""


def test_cli_defaults_and_flags():
    p = build_parser()
    a = p.parse_args([])
    assert (a.to, a.translator, a.model, a.url, a.file, a.mic) == ("ru", "auto", "swiss-turbo", None, None, False)
    a = p.parse_args(["--to", "both", "--url", "https://youtu.be/x", "--dialect", "basel", "--cpu"])
    assert a.to == "both" and a.url and a.dialect == "basel" and a.cpu
    with pytest.raises(SystemExit):
        p.parse_args(["--url", "u", "--file", "f"])  # only one input
    with pytest.raises(SystemExit):
        p.parse_args(["--cpu", "--gpu"])
