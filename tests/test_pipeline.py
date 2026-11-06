import threading
import time
from types import SimpleNamespace

import numpy as np

from swiss_ru_de.config import SAMPLE_RATE
from swiss_ru_de.output import TranscriptWriter
from swiss_ru_de.pipeline import LivePipeline, run_file
from swiss_ru_de.translate import Passthrough, TranslationError, Translator


def tone(seconds, amp=0.2):
    t = np.arange(int(seconds * SAMPLE_RATE)) / SAMPLE_RATE
    return (amp * np.sin(2 * np.pi * 220 * t)).astype(np.float32)


def silence(seconds):
    return np.zeros(int(seconds * SAMPLE_RATE), dtype=np.float32)


class FakeSource:
    """Plays a fixed signal in 100 ms blocks at 10x real time, then stops."""

    def __init__(self, audio):
        self.audio = audio

    def run(self, emit, stop, on_open=None):
        if on_open:
            on_open("fake")
        for i in range(0, len(self.audio), 1600):
            if stop.is_set():
                return
            emit(self.audio[i : i + 1600])
            time.sleep(0.01)


class FakeTranscriber:
    def __init__(self):
        self.calls = []

    def transcribe(self, audio):
        self.calls.append(len(audio) / SAMPLE_RATE)
        return f"Satz {len(self.calls)}"

    def transcribe_file(self, path, beam_size=5):
        for i in range(3):
            yield SimpleNamespace(start=i * 2.0, end=i * 2.0 + 1.5, text=f"Satz {i + 1}")


class FakeRu(Translator):
    name = "fake"

    def __init__(self):
        self.contexts = []

    def translate(self, text, context=()):
        self.contexts.append(list(context))
        return text.replace("Satz", "Предложение")


def run_live(audio, translator, translate=True):
    lines, status = [], []
    p = LivePipeline(FakeSource(audio), FakeTranscriber(), translator, lines.append,
                     status.append, translate=translate).start()
    assert p.wait(10)
    p.stop()
    return lines, status


def test_live_pipeline_end_to_end():
    audio = np.concatenate([silence(0.5), tone(1.2), silence(1.0), tone(1.0), silence(1.0)])
    tr = FakeRu()
    lines, status = run_live(audio, tr)
    assert [l.german for l in lines] == ["Satz 1", "Satz 2"]
    assert [l.translation for l in lines] == ["Предложение 1", "Предложение 2"]
    assert tr.contexts == [[], ["Satz 1"]]  # previous line passed as context
    assert lines[0].start < lines[1].start
    assert "Listening to fake" in status


def test_live_pipeline_german_only_skips_translation():
    audio = np.concatenate([tone(1.0), silence(1.0)])
    lines, _ = run_live(audio, Passthrough(), translate=False)
    assert len(lines) == 1 and lines[0].translation is None


def test_translation_errors_do_not_stop_subtitles():
    class Broken(Translator):
        def translate(self, text, context=()):
            raise TranslationError("no key")

    audio = np.concatenate([tone(1.0), silence(1.0), tone(1.0), silence(1.0)])
    lines, status = run_live(audio, Broken())
    assert len(lines) == 2 and all(l.translation == "" for l in lines)
    assert sum("no key" in s for s in status) == 1  # reported once, not per line


def test_backlog_is_merged_into_one_window():
    p = LivePipeline(FakeSource(silence(0.1)), FakeTranscriber(), Passthrough(),
                     lambda l: None, lambda s: None)
    from swiss_ru_de.segmenter import Segment
    for i in range(4):
        p.segments.put(Segment(i * 8.0, i * 8.0 + 7.0, tone(7.0)))
    batch, done = p._next_batch()
    assert len(batch) == 3 and not done  # 3 x 7 s fit into 25 s
    batch, done = p._next_batch()
    assert [s.start for s in batch] == [24.0] and not done  # 4th was carried over, not lost


def test_run_file_writes_srt(tmp_path):
    out = tmp_path / "x.srt"
    writer = TranscriptWriter(str(out), "both")
    lines = []

    def sink(line):
        lines.append(line)
        writer(line)

    run_file(FakeTranscriber(), FakeRu(), "dummy.wav", sink, lambda s: None)
    writer.close()
    text = out.read_text(encoding="utf-8")
    assert len(lines) == 3
    assert "1\n00:00:00,000 --> 00:00:01,500\nSatz 1\nПредложение 1\n" in text
    assert text.count("-->") == 3


def test_run_file_can_be_stopped():
    stop = threading.Event()
    lines = []

    def sink(line):
        lines.append(line)
        stop.set()

    class Slow(FakeTranscriber):
        def transcribe_file(self, path, beam_size=5):
            for i in range(100):
                yield SimpleNamespace(start=i, end=i + 1, text=f"Satz {i}")
                stop.wait(1)

    run_file(Slow(), Passthrough(), "x", sink, lambda s: None, translate=False, stop=stop)
    assert len(lines) < 100
