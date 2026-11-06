"""Speed (single-pass live decoding, best-effort dialect line, GPU libraries) and
translation quality (keys, Swiss words, fast offline translator)."""

from types import SimpleNamespace

import numpy as np

from swiss_ru_de import asr, keys, translate
from swiss_ru_de.pipeline import LineBook, LivePipeline, _STOP
from swiss_ru_de.segmenter import Segment
from swiss_ru_de.translate import OfflineTranslator, normalize_swiss_terms

from .test_pipeline import FakeSource, FakeTranscriber, FakeRu, silence


def test_live_decoding_is_single_pass_files_keep_fallback():
    t = asr.Transcriber.__new__(asr.Transcriber)
    t.hint, t.prompt = None, None
    assert t._options(1, live=True)["temperature"] == 0.0
    assert t._options(5)["temperature"] == [0.0, 0.2, 0.4, 0.6]


def test_dialect_line_is_skipped_while_speech_is_waiting():
    lines = []
    dialect = FakeTranscriber("Satzli")
    p = LivePipeline(FakeSource(silence(0.1)), FakeTranscriber(), FakeRu(),
                     LineBook(on_line=lines.append), lambda s: None,
                     dialect_transcriber=dialect)
    p.options.dialect = True
    for i in range(3):  # 20 s each: cannot be merged, so a backlog remains
        p.segments.put(Segment(i * 20.0, i * 20.0 + 20, np.zeros(16000, np.float32)))
    p.segments.put(_STOP)
    p.worker.start()
    p._asr_loop()
    p.worker.close()
    assert [l.dialect for l in lines] == [None, None, "Satzli 1"]  # only once idle
    assert all(l.translation for l in lines)  # translation never waits for it


def test_gpu_libraries_missing_is_fine():
    assert isinstance(asr.add_nvidia_libraries(), list)


def test_keys_env_first_then_keychain(monkeypatch, fake_keyring):
    assert keys.get_key("deepl") is None and not keys.has_key("deepl")
    assert keys.set_key("deepl", "abc:fx")
    assert keys.get_key("deepl") == "abc:fx" and keys.saved_in_keychain("deepl")
    monkeypatch.setenv("DEEPL_AUTH_KEY", "from-env")
    assert keys.get_key("deepl") == "from-env"
    assert keys.set_key("deepl", "")  # remove
    assert not keys.saved_in_keychain("deepl")


def test_auto_translator_uses_saved_claude_key():
    keys.set_key("anthropic", "sk-ant-test")
    t = translate.make_translator("auto", "ru")
    assert isinstance(t, translate.ClaudeTranslator)
    assert t.client.api_key == "sk-ant-test"


def test_swiss_words_are_normalised_for_machine_translators():
    assert normalize_swiss_terms("Zmorge mit Gipfeli, dann mit dem Velo ins Spital.") == \
        "Frühstück mit Croissant, dann mit dem Fahrrad ins Krankenhaus."
    assert normalize_swiss_terms("Merci vilmal, Grüezi mitenand!") == "vielen Dank, Guten Tag!"
    assert normalize_swiss_terms("Spitalgasse und Velodrom bleiben.") == "Spitalgasse und Velodrom bleiben."


class FakeTokenizer:
    def encode(self, text, truncation=True, max_length=512):
        return [1, 2, 3]

    def convert_ids_to_tokens(self, ids):
        return [f"t{i}" for i in ids]

    def convert_tokens_to_ids(self, tokens):
        self.decoded_tokens = tokens
        return [7, 8]

    def decode(self, ids, skip_special_tokens=True):
        return " Привет "


def make_offline(nllb=True):
    t = OfflineTranslator.__new__(OfflineTranslator)
    t.nllb, t.log, t.tok = nllb, lambda m: None, FakeTokenizer()
    t._torch_model = None
    return t


def test_offline_ct2_strips_target_language_token():
    t = make_offline()
    calls = {}

    def translate_batch(batch, target_prefix=None, beam_size=2, max_decoding_length=256):
        calls["batch"], calls["prefix"] = batch, target_prefix
        return [SimpleNamespace(hypotheses=[["rus_Cyrl", "▁При", "вет"]])]

    t._ct2 = SimpleNamespace(translate_batch=translate_batch)
    assert t.translate("Zmorge") == "Привет"
    assert calls["batch"] == [["t1", "t2", "t3"]] and calls["prefix"] == [["rus_Cyrl"]]
    assert t.tok.decoded_tokens == ["▁При", "вет"]


def test_offline_falls_back_to_pytorch_when_ct2_fails(monkeypatch):
    t = make_offline()

    def broken(*a, **k):
        raise RuntimeError("bad model")

    t._ct2 = SimpleNamespace(translate_batch=broken)
    monkeypatch.setattr(OfflineTranslator, "_load_torch", lambda self: None)
    monkeypatch.setattr(OfflineTranslator, "_translate_torch", lambda self, text: f"torch:{text}")
    assert t.translate("Velo") == "torch:Fahrrad"
    assert t._ct2 is None  # stays on PyTorch afterwards
