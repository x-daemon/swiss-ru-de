"""Speech recognition: Swiss German audio -> Standard German text (faster-whisper)."""

from __future__ import annotations

import os
import re
import sys
import time
from collections import deque
from dataclasses import dataclass
from typing import Callable, Iterator

import numpy as np

from .config import FALLBACK_MODEL, MODEL_PRESETS, SAMPLE_RATE

Log = Callable[[str], None]

# Phrases Whisper is known to invent on silence/music (learned from TV subtitles).
_HALLUCINATIONS = [
    re.compile(p, re.IGNORECASE)
    for p in (
        r"untertitel(ung)?\s+(im auftrag|von|der|des|durch)\b",
        r"untertitel(ung)?.{0,40}\b(zdf|ard|wdr|swr|ndr|mdr|br|srf|amara|funk)\b",
        r"\b(copyright|©)\s*(zdf|ard|wdr|swr|ndr|mdr|br|srf)\b",
        r"^\W*(vielen\s+)?dank\s+(fürs|für's|für das|für ihr)\s+zu(schauen|hören|sehen)\W*$",
        r"^\W*(das war'?s|bis zum nächsten mal)\W*(für heute)?\W*$",
        r"abonnier(t|en|e)\b.{0,30}\bkanal",
        r"^\W*(musik|applaus|lachen|stille)\W*$",
    )
]
_REPEAT = re.compile(r"(\b.{3,}?)(?:[\s,.]+\1\b){2,}", re.IGNORECASE)


def is_hallucination(text: str) -> bool:
    t = text.strip()
    if not t or not re.search(r"\w", t):
        return True
    return any(p.search(t) for p in _HALLUCINATIONS)


def clean_text(text: str) -> str:
    """Normalise whitespace, collapse "a a a a" style repetition loops."""
    text = re.sub(r"\s+", " ", text).strip()
    text = _REPEAT.sub(r"\1", text)
    return text.strip()


def _echoes_prompt(text: str, prompt: str) -> bool:
    """On silence Whisper sometimes just repeats its prompt."""
    norm = lambda t: re.sub(r"[^\w ]", "", t.lower()).strip()
    t = norm(text)
    return len(t) > 3 and t in norm(prompt)


# Style prompts that make plain Whisper write what it hears in dialect spelling instead of
# Standard German (Whisper imitates the writing style of its prompt). Spelling of Swiss
# German is not standardised, so the output is an approximation of what was said.
DIALECT_PROMPTS = {
    "auto": "Grüezi mitenand. Hüt isch es schöns Wätter, mir gönd am Namittag no chli go "
            "laufe. Weisch, das han i nöd gwüsst. "
            "Ich ha gseit, mir chömed morn wieder, wenn's dir passt. Das isch würkli nöd so schlimm gsi.",
    "zurich": "Grüezi mitenand. Hüt isch es schöns Wätter, mir gönd am Namittag no chli go "
              "laufe. Weisch, das han i nöd gwüsst. "
              "Ich ha gseit, mir chömed morn wieder, wenn's dir passt. Das isch würkli nöd so schlimm gsi.",
    "bern": "Grüessech mitenand. Hüt isch es schöns Wätter, mir göh am Namittag no chli ga "
            "loufe. Weisch, das hani nid gwüsst. "
            "I ha gseit, mir chöme morn wieder, we's dir passt. Das isch würklech nid so schlimm gsi.",
    "berner-oberland": "Grüessech zäme. Hiitu ischt es schöns Wätter, mier gange am Namittag "
                       "no chli ga loufe. Weischt, das han i nid gwisst. "
                       "I ha gseit, mier chöme morn wider, wes dier passt. Das ischt würklech nid so schlimm gsi.",
    "basel": "Grüezi mitenand. Hüt isch e scheens Wätter, mir gönge am Nomidaag no e bitz go "
             "spaziere. Waisch, das hani nit gwüsst. "
             "Ich ha gsait, mir kömme morn wider, wenn's dr passt. Das isch würgglig nit so schlimm gsi.",
    "wallis": "Grüessu zäme. Hiitu ischt schens Wätter, wier gän am Namittag no as bitzji ga "
              "loufu. Weischt, das hani nit gwisst. "
              "Ich hä gseit, wier chämu morn wider, wenn's dier passt. Das ischt wirklich nit so schlimm gsi.",
    "luzern": "Grüezi mitenand. Hött esch es schöns Wätter, mer gönd am Nomittag no chli go "
              "laufe. Wäisch, das hani ned gwüsst. "
              "Ech ha gseit, mer chömed morn wieder, wenn's der passt. Das esch würklech ned so schlemm gsi.",
    "ostschweiz": "Grüezi mitenand. Hüt isch es schöös Wetter, mir gönd am Namittag no chli go "
                  "laufe. Weisch, da han i nöd gwüsst. "
                  "I ha gseit, mir chömed morn wieder, wenn's dir passt. Da isch würkli nöd so schlimm gsi.",
    "graubuenden": "Grüezi mitanand. Hüt isch as schöns Wätter, miar gönd am Namitag no a bitz "
                   "go laufa. Weisch, das han i nid gwüsst. "
                   "I han gseit, miar kömmand morn wieder, wenn's dir passt. Das isch würkli nid so schlimm gsi.",
    "aargau": "Grüezi mitenand. Hüt isch es schöns Wätter, mer gönd am Namittag no chli go "
              "laufe. Weisch, das hani ned gwüsst. "
              "Ich ha gseit, mer chömed morn wieder, wenn's der passt. Das isch würklich ned so schlimm gsi.",
    "solothurn": "Grüessech mitenand. Hüt isch es schöns Wätter, mir göi am Namittag no chli go "
                 "laufe. Weisch, das hani nid gwüsst. "
                 "I ha gseit, mir chöme morn wieder, wenn's der passt. Das isch würklech nid so schlimm gsi.",
}


def dialect_prompt(dialect: str | None) -> str:
    return DIALECT_PROMPTS.get(dialect or "auto", DIALECT_PROMPTS["auto"])


# Words that occur in Swiss German but not in Standard German writing.
_DIALECT_WORDS = {
    "isch", "ischt", "esch", "nöd", "nid", "ned", "nit", "hüt", "hiitu", "hött", "gsi", "gha",
    "öppis", "öppe", "chli", "chlii", "gönd", "göh", "gömmer", "han", "hani", "weisch",
    "weischt", "waisch", "nüt", "nüüt", "nüd", "nüüd", "scho", "gseit", "gsait", "chöme",
    "chömed", "chunnt", "chunsch", "chasch", "chönd", "chönnt", "wotsch", "wott", "zmorge",
    "zmittag", "znacht", "gäll", "bisch", "hesch", "häsch", "hend", "händ", "gits", "emol",
    "eifach", "würkli", "würklech", "lueg", "luege", "mached", "gange", "gaht", "goht",
    "simmer", "mier", "miar", "wier", "ech", "isse", "ässe", "gässe", "poschte",
    "grüezi", "grüessech", "merci", "tschüss", "uf", "d'", "dä", "dr", "es", "en", "e",
}
_COMMON_STANDARD = {"es", "en", "e", "uf", "merci", "tschüss", "d'", "dr"}  # weak hints only


def looks_dialectal(text: str) -> bool:
    """Is this written in Swiss German (as opposed to Standard German)?"""
    words = re.findall(r"[a-zäöüéèàâ']+", text.lower())
    strong = sum(w in _DIALECT_WORDS and w not in _COMMON_STANDARD for w in words)
    return strong >= 2 or (strong == 1 and len(words) <= 6)


@dataclass
class TextSegment:
    start: float
    end: float
    text: str


# --------------------------------------------------------------------------- model
def resolve_model(name: str, log: Log = print) -> str:
    """Preset name / HF repo id / local folder -> something WhisperModel can load.

    Some community repos keep the CTranslate2 weights in a subfolder (e.g. ``ct2/``)
    next to the original PyTorch weights; only that folder is downloaded.
    """
    name = MODEL_PRESETS.get(name, name)
    if os.path.isdir(name):
        return _find_ct2_dir(name) or name
    if "/" not in name:  # faster-whisper alias such as "large-v3-turbo"
        return name

    from huggingface_hub import HfApi, snapshot_download

    files = HfApi().list_repo_files(name)
    bins = sorted((f for f in files if f.split("/")[-1] == "model.bin"), key=len)
    if not bins:
        raise RuntimeError(f"{name} has no model.bin - not a CTranslate2/faster-whisper model")
    sub = os.path.dirname(bins[0])
    log(f"Loading speech model {name}{'/' + sub if sub else ''} (first run downloads it) ...")
    pattern = f"{sub}/*" if sub else "*"
    ignore = ["*.safetensors", "*.pt", "*.ckpt", "*.msgpack", "*.h5", "*.onnx"]
    path = snapshot_download(name, allow_patterns=[pattern], ignore_patterns=ignore)
    return os.path.join(path, sub) if sub else path


def _find_ct2_dir(root: str) -> str | None:
    for dirpath, _dirs, files in os.walk(root):
        if "model.bin" in files:
            return dirpath
    return None


def add_nvidia_libraries() -> list[str]:
    """Make CUDA libraries installed with pip (the ``gpu`` extra: nvidia-cublas-cu12,
    nvidia-cudnn-cu12) findable for CTranslate2. Returns the folders that were added."""
    try:
        import nvidia  # namespace package of the pip CUDA wheels
    except ImportError:
        return []
    added = []
    for root in getattr(nvidia, "__path__", []):
        for lib in ("cublas", "cudnn", "cuda_runtime", "cuda_nvrtc"):
            folder = os.path.join(root, lib, "bin" if sys.platform == "win32" else "lib")
            if not os.path.isdir(folder):
                continue
            added.append(folder)
            if sys.platform == "win32":
                os.environ["PATH"] = folder + os.pathsep + os.environ.get("PATH", "")
                try:
                    os.add_dll_directory(folder)
                except OSError:
                    pass
            else:  # Linux: preload so that CTranslate2's dlopen() finds them
                import ctypes
                import glob

                for so in sorted(glob.glob(os.path.join(folder, "*.so*")), key=lambda p: "Lt" not in p):
                    try:
                        ctypes.CDLL(so, mode=ctypes.RTLD_GLOBAL)
                    except OSError:
                        pass
    return added


def pick_device(requested: str) -> str:
    """'auto' -> 'cuda' only when an NVIDIA GPU *and* the CUDA libraries are usable."""
    add_nvidia_libraries()
    if requested != "auto":
        return requested
    try:
        import ctranslate2

        if ctranslate2.get_cuda_device_count() == 0:
            return "cpu"
    except Exception:
        return "cpu"
    if sys.platform == "win32":
        # ctranslate2 crashes hard if cuBLAS/cuDNN DLLs are missing, so check first.
        import ctypes

        try:
            ctypes.WinDLL("cublas64_12.dll")
            ctypes.WinDLL("cudnn_ops64_9.dll")
        except OSError:
            return "cpu"
    return "cuda"


def _fix_mel_bins(model) -> None:
    """large-v3/turbo need 128 mel bins; repos without preprocessor_config.json would
    otherwise get the 80-bin default and produce garbage."""
    n_mels = getattr(model.model, "n_mels", None)
    if n_mels and model.feature_extractor.mel_filters.shape[0] != n_mels:
        from faster_whisper.feature_extractor import FeatureExtractor

        model.feat_kwargs = {**getattr(model, "feat_kwargs", {}), "feature_size": n_mels}
        model.feature_extractor = FeatureExtractor(**model.feat_kwargs)


def utterance_clips(audio: np.ndarray, sr: int = SAMPLE_RATE, min_pause_s: float = 0.35,
                    min_clip_s: float = 0.8, max_clips: int = 8) -> list[tuple[int, int]]:
    """Sample ranges of the utterances in a segment, split at clear pauses.

    A segment often holds a short answer and the next question ("Orangensaft. - Und am
    Wochenende ...?"). Given both at once, the Swiss German model tends to skip the first,
    short one; each utterance on its own is recognised completely."""
    frame = int(0.03 * sr)
    n = len(audio) // frame
    if n * frame < 2 * min_clip_s * sr:
        return [(0, len(audio))]
    frames = audio[: n * frame].reshape(n, frame).astype(np.float64)
    db = 20 * np.log10(np.sqrt(np.mean(frames * frames, axis=1)) + 1e-10)
    quiet = db < max(np.percentile(db, 80) - 15.0, np.percentile(db, 10) + 3.0)
    run = int(min_pause_s / 0.03)
    cuts, i = [], 0
    while i < n:
        j = i
        while j < n and quiet[j]:
            j += 1
        if j - i >= run and i > 0 and j < n:  # a pause between two utterances
            cuts.append((i + j) // 2 * frame)
        i = max(j, i + 1)
    bounds = [0, *cuts, len(audio)]
    clips: list[tuple[int, int]] = []
    shortest = int(min_clip_s * sr)
    for a, b in zip(bounds, bounds[1:]):
        if clips and (b - a < shortest or clips[-1][1] - clips[-1][0] < shortest):
            clips[-1] = (clips[-1][0], b)  # too short on its own ("Ja."): join a neighbour
        else:
            clips.append((a, b))
    while len(clips) > max_clips:  # join the shortest neighbouring pair
        k = min(range(len(clips) - 1), key=lambda k: clips[k + 1][1] - clips[k][0])
        clips[k:k + 2] = [(clips[k][0], clips[k + 1][1])]
    return clips


class Transcriber:
    split_utterances = False  # see __init__
    _batched = None

    def __init__(
        self,
        model: str,
        device: str = "auto",
        compute_type: str | None = None,
        beam_size: int | None = None,
        hint: str | None = None,
        log: Log = print,
        prompt: str | None = None,
    ):
        from faster_whisper import WhisperModel

        self.hint = hint or None
        self.prompt = prompt  # style prompt; used by the dialect transcriber
        self.log = log
        self.device = pick_device(device)
        # GPU: int8 weights with float16 maths - half the graphics memory of float16, so a
        # local AI translation model (Ollama) still fits next to the speech models.
        compute_type = compute_type or ("int8_float16" if self.device == "cuda" else "int8")
        threads = max(4, (os.cpu_count() or 8) // 2)

        try:
            path = resolve_model(model, log)
        except Exception as e:  # offline, repo renamed, ...
            log(f"Could not load '{model}' ({e}). Falling back to {FALLBACK_MODEL}.")
            path = FALLBACK_MODEL

        def one_pass(m) -> float:
            started = time.perf_counter()
            segments, _ = m.transcribe(np.zeros(SAMPLE_RATE, dtype=np.float32), language="de",
                                       beam_size=1, temperature=0.0, max_new_tokens=24)
            list(segments)
            return time.perf_counter() - started

        def load(device: str, ctype: str):
            m = WhisperModel(path, device=device, compute_type=ctype, cpu_threads=threads)
            _fix_mel_bins(m)
            one_pass(m)  # warm-up: loads all kernels so the first real sentence is fast
            # Every recognition pass costs about the same (a 30 s window), so one timed pass
            # tells how fast this PC is; used to tune live mode (see tuning.py).
            self.pass_seconds = one_pass(m)
            return m

        try:
            self.model = load(self.device, compute_type)
        except Exception as e:
            if self.device == "cpu":
                raise
            log(f"GPU not usable ({e}); using CPU.")
            self.device = "cpu"
            self.model = load("cpu", "int8")
        # Wider search (beam) is more precise; cheap on a GPU, too slow live on a CPU.
        self.beam_size = beam_size or (5 if self.device == "cuda" else 1)
        # Live segments are recognised utterance by utterance, all in one batched pass - on
        # a GPU that costs about as much as one pass; on a CPU every utterance would cost a
        # full pass, so there the segment is recognised as a whole.
        self.split_utterances = self.device == "cuda"
        self._batched = None
        self._recent_dialect: deque[str] = deque(maxlen=2)
        log(f"Speech model ready on {self.device.upper()} ({self.pass_seconds:.1f} s per pass).")

    def _options(self, beam_size: int, live: bool = False) -> dict:
        # Live: one decoding pass only. The temperature fallback re-decodes up to 3 more
        # times whenever the model is unsure - which is often the case for dialect - and
        # made live recognition several times slower. Files keep it (accuracy first).
        temperature = 0.0 if live else [0.0, 0.2, 0.4, 0.6]
        return dict(
            language="de",  # Whisper has no Swiss German token; output is Standard German
            task="transcribe",
            beam_size=beam_size,
            vad_filter=True,
            vad_parameters={"min_silence_duration_ms": 500, "speech_pad_ms": 200},
            condition_on_previous_text=False,  # avoids repetition loops
            temperature=temperature,
            no_speech_threshold=0.6,
            log_prob_threshold=-1.0,
            compression_ratio_threshold=2.4,
            hotwords=self.hint,
            initial_prompt=self.initial_prompt(),
        )

    def initial_prompt(self) -> str | None:
        """The style prompt, plus the last lines this dialect transcriber wrote in dialect:
        Whisper continues the style of the text before it, so dialect keeps it in dialect
        instead of drifting back to Standard German."""
        if not self.prompt:
            return None
        recent = getattr(self, "_recent_dialect", None) or ()
        return " ".join([self.prompt, *recent])

    def remember_style(self, text: str) -> None:
        if self.prompt and text and looks_dialectal(text):
            if getattr(self, "_recent_dialect", None) is None:
                self._recent_dialect = deque(maxlen=2)
            self._recent_dialect.append(text[-200:])

    def transcribe(self, audio: np.ndarray) -> str:
        """Transcribe one short utterance (live mode)."""
        clips = utterance_clips(audio) if self.split_utterances else []
        segments = None
        if len(clips) > 1:
            try:
                segments = self._transcribe_clips(audio, clips)
            except Exception as e:  # e.g. an older faster-whisper: whole segments from now on
                self.split_utterances = False
                self.log(f"Utterance-by-utterance recognition not available ({e!r}).")
        if segments is None:
            segments, _ = self.model.transcribe(
                audio, without_timestamps=True, **self._options(self.beam_size, live=True)
            )
        parts = [clean_text(s.text) for s in segments if s.no_speech_prob < 0.8]
        text = clean_text(" ".join(p for p in parts if not is_hallucination(p)))
        if is_hallucination(text) or self._echoes(text):
            return ""
        self.remember_style(text)
        return text

    def _echoes(self, text: str) -> bool:
        """On silence Whisper sometimes repeats its prompt. Short repeats of a remembered
        line are kept: people do say "Nur Wasser." twice."""
        if not self.prompt:
            return False
        recent = " ".join(getattr(self, "_recent_dialect", None) or ())
        return _echoes_prompt(text, self.prompt) or (
            len(text) >= 25 and bool(recent) and _echoes_prompt(text, recent))

    def _transcribe_clips(self, audio: np.ndarray, clips: list[tuple[int, int]]) -> list:
        if self._batched is None:
            from faster_whisper import BatchedInferencePipeline

            self._batched = BatchedInferencePipeline(model=self.model)
        options = self._options(self.beam_size, live=True)
        for key in ("vad_filter", "vad_parameters"):  # the clips are the speech regions
            options.pop(key)
        segments, _ = self._batched.transcribe(
            audio, clip_timestamps=[{"start": a / SAMPLE_RATE, "end": b / SAMPLE_RATE} for a, b in clips],
            batch_size=len(clips), vad_filter=False, without_timestamps=True, **options)
        return list(segments)

    def transcribe_file(self, path: str, beam_size: int = 5) -> Iterator[TextSegment]:
        """Transcribe a whole audio/video file, yielding sentences as they are ready."""
        segments, info = self.model.transcribe(path, **self._options(beam_size))
        self.log(f"Audio length {info.duration / 60:.1f} min.")
        for s in segments:
            text = clean_text(s.text)
            if s.no_speech_prob < 0.8 and not is_hallucination(text):
                yield TextSegment(s.start, s.end, text)
