"""Wire audio -> segments -> German text -> translation -> output, using threads so
capture, recognition and translation never block each other."""

from __future__ import annotations

import queue
import threading
from collections import deque
from dataclasses import dataclass
from typing import Callable, Iterable

import numpy as np

from .config import SAMPLE_RATE
from .segmenter import Segment, Segmenter
from .translate import TranslationError, Translator

_STOP = object()
MAX_BATCH_S = 25.0  # Whisper sees 30 s windows; merge backlog up to this length


@dataclass
class Line:
    start: float
    end: float
    german: str
    translation: str | None = None  # None when the target is German


OnLine = Callable[[Line], None]
OnStatus = Callable[[str], None]


class TranslationWorker:
    """Translates German lines in the background, keeping a little context."""

    def __init__(self, translator: Translator, on_line: OnLine, on_status: OnStatus,
                 translate: bool, context_lines: int = 3):
        self.translator = translator
        self.on_line = on_line
        self.on_status = on_status
        self.translate = translate
        self.context: deque[str] = deque(maxlen=context_lines)
        self.q: queue.Queue = queue.Queue()
        self._last_error = ""
        self.thread = threading.Thread(target=self._run, name="translate", daemon=True)

    def start(self) -> "TranslationWorker":
        self.thread.start()
        return self

    def put(self, line: Line) -> None:
        self.q.put(line)

    def close(self, wait: bool = True) -> None:
        self.q.put(_STOP)
        if wait:
            self.thread.join()

    def _run(self) -> None:
        while (line := self.q.get()) is not _STOP:
            if self.translate:
                try:
                    line.translation = self.translator.translate(line.german, list(self.context))
                    self._last_error = ""
                except TranslationError as e:
                    line.translation = ""
                    if str(e) != self._last_error:  # don't repeat the same error per line
                        self._last_error = str(e)
                        self.on_status(f"Translation failed: {e}")
                except Exception as e:  # keep the subtitles running whatever happens
                    line.translation = ""
                    self.on_status(f"Translation failed: {e!r}")
            self.context.append(line.german)
            self.on_line(line)


def merge_segments(segments: list[Segment]) -> Segment:
    """Join several utterances (with short gaps) into one recognition window."""
    if len(segments) == 1:
        return segments[0]
    gap = np.zeros(int(0.3 * SAMPLE_RATE), dtype=np.float32)
    parts: list[np.ndarray] = []
    for i, s in enumerate(segments):
        if i:
            parts.append(gap)
        parts.append(s.audio)
    return Segment(segments[0].start, segments[-1].end, np.concatenate(parts))


class LivePipeline:
    """Live mode: capture thread -> recognition thread -> translation thread."""

    def __init__(self, source, transcriber, translator: Translator, on_line: OnLine,
                 on_status: OnStatus, translate: bool = True, segmenter: Segmenter | None = None):
        self.source = source
        self.transcriber = transcriber
        self.segmenter = segmenter or Segmenter()
        self.on_status = on_status
        self.segments: queue.Queue = queue.Queue()
        self.stop_event = threading.Event()
        self.worker = TranslationWorker(translator, on_line, on_status, translate)
        self._capture = threading.Thread(target=self._capture_loop, name="capture", daemon=True)
        self._asr = threading.Thread(target=self._asr_loop, name="asr", daemon=True)
        self._lag_warned = False
        self._carry: Segment | None = None
        self.error: BaseException | None = None

    def start(self) -> "LivePipeline":
        self.worker.start()
        self._asr.start()
        self._capture.start()
        return self

    def stop(self) -> None:
        self.stop_event.set()
        self._capture.join(timeout=3)
        self._asr.join(timeout=60)
        self.worker.close()

    def wait(self, timeout: float | None = None) -> bool:
        """Block until the pipeline stops by itself (e.g. audio device error)."""
        return self.stop_event.wait(timeout)

    # -- capture -----------------------------------------------------------------
    def _emit(self, audio: np.ndarray) -> None:
        for seg in self.segmenter.feed(audio):
            self.segments.put(seg)

    def _capture_loop(self) -> None:
        try:
            self.source.run(self._emit, self.stop_event,
                            on_open=lambda name: self.on_status(f"Listening to {name}"))
        except Exception as e:
            self.error = e
            self.on_status(f"Audio capture stopped: {e}")
        finally:
            last = self.segmenter.flush()
            if last is not None:
                self.segments.put(last)
            self.segments.put(_STOP)
            self.stop_event.set()

    # -- recognition ---------------------------------------------------------------
    def _next_batch(self) -> tuple[list[Segment], bool]:
        """Take one segment, plus any backlog that fits in one Whisper window."""
        first, self._carry = (self._carry or self.segments.get()), None
        if first is _STOP:
            return [], True
        batch, total = [first], first.duration
        while True:
            try:
                nxt = self.segments.get_nowait()
            except queue.Empty:
                return batch, False
            if nxt is _STOP:
                return batch, True
            if total + nxt.duration > MAX_BATCH_S:
                self._carry = nxt  # keep it for the next round
                return batch, False
            batch.append(nxt)
            total += nxt.duration

    def _asr_loop(self) -> None:
        done = False
        while not done:
            batch, done = self._next_batch()
            if not batch:
                break
            if len(batch) > 2 and not self._lag_warned:
                self._lag_warned = True
                self.on_status("Recognition is slower than real time; merging sentences. "
                               "A GPU or --model swiss-turbo-int8 helps.")
            seg = merge_segments(batch)
            try:
                text = self.transcriber.transcribe(seg.audio)
            except Exception as e:
                self.on_status(f"Recognition error: {e!r}")
                continue
            if text:
                self.worker.put(Line(seg.start, seg.end, text))


def run_file(transcriber, translator: Translator, path: str, on_line: OnLine,
             on_status: OnStatus, translate: bool = True, beam_size: int = 5,
             stop: threading.Event | None = None) -> None:
    """File / URL mode: recognise the whole file, translate while recognising."""
    worker = TranslationWorker(translator, on_line, on_status, translate).start()
    try:
        segments: Iterable = transcriber.transcribe_file(path, beam_size=beam_size)
        for s in segments:
            if stop is not None and stop.is_set():
                break
            worker.put(Line(s.start, s.end, s.text))
    finally:
        worker.close()
