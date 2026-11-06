"""Wire audio -> segments -> text -> translation -> output, using threads so capture,
recognition and translation never block each other.

Every utterance becomes a :class:`Line`. Its parts arrive at different times:

* ``german``      Standard German from the Swiss German model (always first)
* ``translation`` Russian, from the translation thread (target ``ru``)
* ``dialect``     Swiss German as spoken, from the optional second (dialect) model

:class:`LineBook` collects the parts and reports every change (``on_update``, used by
the GUI) and every finished line (``on_line``, used by console and transcript files).
"""

from __future__ import annotations

import queue
import threading
from collections import deque
from dataclasses import dataclass, replace
from typing import Callable

import numpy as np

from .config import SAMPLE_RATE
from .segmenter import Segment, Segmenter
from .translate import TranslationError, Translator

_STOP = object()
MAX_BATCH_S = 25.0  # Whisper sees 30 s windows; merge backlog up to this length


@dataclass
class Line:
    id: int
    start: float
    end: float
    german: str
    target: str = "ru"
    translation: str | None = None  # None when the target is German
    dialect: str | None = None  # Swiss German as spoken, if the dialect model is on
    translation_pending: bool = True
    dialect_pending: bool = False

    @property
    def done(self) -> bool:
        return not (self.translation_pending or self.dialect_pending)


OnLine = Callable[[Line], None]
OnStatus = Callable[[str], None]


@dataclass
class Options:
    """Settings that may change while running (from the GUI settings dialog)."""

    target: str = "ru"  # "ru", "de" or "both"
    dialect: bool = False  # also transcribe the dialect as spoken
    paused: bool = False


class LineBook:
    def __init__(self, on_update: OnLine | None = None, on_line: OnLine | None = None):
        self.on_update = on_update
        self.on_line = on_line
        self._lines: dict[int, Line] = {}
        self._next_id = 0
        self._lock = threading.Lock()

    def new(self, start: float, end: float, german: str, target: str, dialect: bool) -> Line:
        with self._lock:
            line = Line(self._next_id, start, end, german, target, dialect_pending=dialect)
            self._next_id += 1
            self._lines[line.id] = line
            snap = replace(line)
        if self.on_update:
            self.on_update(snap)
        return snap

    def update(self, line_id: int, **fields) -> None:
        with self._lock:
            line = self._lines.get(line_id)
            if line is None:
                return
            for k, v in fields.items():
                setattr(line, k, v)
            snap = replace(line)
            if line.done:
                del self._lines[line_id]
        if self.on_update:
            self.on_update(snap)
        if snap.done and self.on_line:
            self.on_line(snap)


class TranslationWorker:
    """Translates German lines in the background, keeping a little context."""

    def __init__(self, translators: Callable[[str], Translator], book: LineBook,
                 on_status: OnStatus, context_lines: int = 3):
        self.translators = translators
        self.book = book
        self.on_status = on_status
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

    def _error(self, msg: str) -> None:
        if msg != self._last_error:  # don't repeat the same error for every line
            self._last_error = msg
            self.on_status(f"Translation failed: {msg}")

    def _run(self) -> None:
        while (line := self.q.get()) is not _STOP:
            text = None
            if line.target != "de":
                try:
                    text = self.translators(line.target).translate(line.german, list(self.context))
                    self._last_error = ""
                except TranslationError as e:
                    text = ""
                    self._error(str(e))
                except Exception as e:  # keep the subtitles running whatever happens
                    text = ""
                    self._error(repr(e))
            self.context.append(line.german)
            self.book.update(line.id, translation=text, translation_pending=False)


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


def _as_translators(t) -> Callable[[str], Translator]:
    return t if callable(t) and not isinstance(t, Translator) else (lambda target: t)


class LivePipeline:
    """Live mode: capture thread -> recognition thread -> translation thread."""

    def __init__(self, source, transcriber, translators, book: LineBook, on_status: OnStatus,
                 options: Options | None = None, segmenter: Segmenter | None = None,
                 dialect_transcriber=None):
        self.source = source
        self.transcriber = transcriber
        self.dialect_transcriber = dialect_transcriber  # may be set later (loads slowly)
        self.book = book
        self.options = options or Options()
        self.segmenter = segmenter or Segmenter()
        self.on_status = on_status
        self.segments: queue.Queue = queue.Queue()
        self.stop_event = threading.Event()
        self.worker = TranslationWorker(_as_translators(translators), book, on_status)
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

    def stop(self, wait: bool = True) -> None:
        self.stop_event.set()
        if wait:
            self._capture.join(timeout=3)
            self._asr.join(timeout=60)
            self.worker.close()

    def wait(self, timeout: float | None = None) -> bool:
        """Block until the pipeline stops by itself (e.g. audio device error)."""
        return self.stop_event.wait(timeout)

    # -- capture -----------------------------------------------------------------
    def _emit(self, audio: np.ndarray) -> None:
        for seg in self.segmenter.feed(audio):
            if not self.options.paused:
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
            if last is not None and not self.options.paused:
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
                               "A GPU, --model swiss-turbo-int8 or turning off the dialect "
                               "line helps.")
            seg = merge_segments(batch)
            process_segment(seg.start, seg.end, seg.audio, self.transcriber,
                            self.dialect_transcriber if self.options.dialect else None,
                            self.book, self.worker, self.options.target, self.on_status)


def process_segment(start, end, audio, transcriber, dialect_transcriber, book, worker,
                    target, on_status, german: str | None = None) -> None:
    """Standard German first (so translation can start), then the dialect line."""
    if german is None:
        try:
            german = transcriber.transcribe(audio)
        except Exception as e:
            on_status(f"Recognition error: {e!r}")
            return
    if not german:
        return
    line = book.new(start, end, german, target, dialect=dialect_transcriber is not None)
    worker.put(line)
    if dialect_transcriber is not None:
        try:
            dialect = dialect_transcriber.transcribe(audio)
        except Exception as e:
            on_status(f"Dialect recognition error: {e!r}")
            dialect = ""
        book.update(line.id, dialect=dialect or None, dialect_pending=False)


def run_file(transcriber, translators, path: str, book: LineBook, on_status: OnStatus,
             options: Options | None = None, beam_size: int = 5,
             stop: threading.Event | None = None, dialect_transcriber=None,
             load_audio: Callable[[str], np.ndarray] | None = None) -> None:
    """File / URL mode: recognise the whole file, translate while recognising."""
    options = options or Options()
    worker = TranslationWorker(_as_translators(translators), book, on_status).start()
    audio = None
    if dialect_transcriber is not None:
        if load_audio is None:
            from faster_whisper import decode_audio as load_audio
        audio = load_audio(path)
    try:
        for s in transcriber.transcribe_file(path, beam_size=beam_size):
            if stop is not None and stop.is_set():
                break
            chunk = None
            if audio is not None:
                chunk = audio[int(s.start * SAMPLE_RATE) : int(s.end * SAMPLE_RATE)]
            process_segment(s.start, s.end, chunk, transcriber,
                            dialect_transcriber if chunk is not None and chunk.size else None,
                            book, worker, options.target, on_status, german=s.text)
    finally:
        worker.close()
