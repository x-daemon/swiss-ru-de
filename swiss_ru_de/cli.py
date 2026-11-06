"""Command line entry point: ``swiss-ru-de``."""

from __future__ import annotations

import argparse
import sys
import tempfile
import threading
import time
from pathlib import Path

from . import __version__
from .config import DEFAULT_MODEL, DEFAULT_OFFLINE_MODEL, DIALECTS, MODEL_PRESETS

EXAMPLES = """\
examples:
  swiss-ru-de                         live: everything playing on the PC -> Russian
  swiss-ru-de --to de --overlay       live German subtitles in a floating window
  swiss-ru-de --to both               German and Russian
  swiss-ru-de --device Headset        capture a specific speaker/headset (Teams)
  swiss-ru-de --url https://www.youtube.com/watch?v=...   whole video, faster than real time
  swiss-ru-de --file interview.mp4 --save interview.srt
  swiss-ru-de --list-devices
"""


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="swiss-ru-de",
        description="Swiss German speech (PC audio, Teams, YouTube) -> Russian or German text.",
        epilog=EXAMPLES,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    src = p.add_argument_group("input (default: live PC audio)")
    one = src.add_mutually_exclusive_group()
    one.add_argument("--url", help="YouTube or other video URL (downloads the audio track)")
    one.add_argument("--file", help="audio or video file")
    one.add_argument("--mic", action="store_true",
                     help="use a microphone / virtual input instead of the PC speaker output")
    src.add_argument("--device", help="speaker (or with --mic: input) name or part of it")
    src.add_argument("--list-devices", action="store_true", help="show audio devices and exit")

    out = p.add_argument_group("output")
    out.add_argument("--to", choices=["ru", "de", "both"], default="ru",
                     help="output language (default: ru)")
    out.add_argument("--overlay", action="store_true", help="floating always-on-top subtitle window")
    out.add_argument("--font-size", type=int, default=22, help="overlay font size")
    out.add_argument("--save", metavar="FILE", help="also write a transcript (.srt or .txt)")

    tr = p.add_argument_group("translation")
    tr.add_argument("--translator", choices=["auto", "claude", "deepl", "offline"], default="auto",
                    help="auto = Claude if ANTHROPIC_API_KEY is set, else DeepL if DEEPL_AUTH_KEY "
                         "is set, else offline")
    tr.add_argument("--claude-model", default=None, help="Claude model id (default claude-opus-5-5)")
    tr.add_argument("--offline-model", default=DEFAULT_OFFLINE_MODEL,
                    help=f"offline translation model (default {DEFAULT_OFFLINE_MODEL})")
    tr.add_argument("--dialect", choices=list(DIALECTS), default="auto",
                    help="optional dialect hint for the Claude translator; recognition handles "
                         "all dialects automatically")

    asr = p.add_argument_group("speech recognition")
    asr.add_argument("--model", default=DEFAULT_MODEL,
                     help=f"preset ({', '.join(MODEL_PRESETS)}), Hugging Face repo or local folder "
                          f"(default {DEFAULT_MODEL})")
    asr.add_argument("--hint", help="names/terms that occur in the audio, e.g. 'Grindelwald, Eiger'")
    dev = asr.add_mutually_exclusive_group()
    dev.add_argument("--cpu", action="store_true", help="force CPU")
    dev.add_argument("--gpu", action="store_true", help="force NVIDIA GPU (CUDA)")
    asr.add_argument("--compute-type", default=None, help="CTranslate2 type, e.g. int8, float16")
    asr.add_argument("--beam", type=int, default=None,
                     help="beam size: higher = a bit more accurate, slower (default live 1, file 5)")
    asr.add_argument("--pause-ms", type=int, default=600,
                     help="pause that ends a sentence in live mode (default 600)")
    asr.add_argument("--max-seconds", type=float, default=12.0,
                     help="longest live segment before it is cut (default 12)")

    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return p


def log(msg: str) -> None:
    print(f"» {msg}", file=sys.stderr, flush=True)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    from .output import ConsolePrinter, TranscriptWriter, setup_console

    setup_console()

    if args.list_devices:
        from .audio import list_devices

        try:
            print(list_devices())
        except RuntimeError as e:
            log(str(e))
            return 1
        return 0

    from .translate import TranslationError, make_translator

    try:
        translator = make_translator(args.translator, args.to, args.claude_model,
                                     args.offline_model, args.dialect, log=log)
    except TranslationError as e:
        log(str(e))
        return 2
    if args.to != "de":
        log(f"Translation: {translator.name}")

    from .asr import Transcriber

    device = "cpu" if args.cpu else "cuda" if args.gpu else "auto"
    live = not (args.url or args.file)
    beam = args.beam or (1 if live else 5)
    transcriber = Transcriber(args.model, device=device, compute_type=args.compute_type,
                              beam_size=beam, hint=args.hint, log=log)

    sinks = [ConsolePrinter(args.to)]
    writer = TranscriptWriter(args.save, args.to) if args.save else None
    if writer:
        sinks.append(writer)
    overlay = None
    if args.overlay:
        from .overlay import Overlay

        overlay = Overlay(args.to, font_size=args.font_size)
        sinks.append(overlay.push)

    def on_line(line) -> None:
        for sink in sinks:
            sink(line)

    def on_status(msg: str) -> None:
        log(msg)
        if overlay:
            overlay.status(msg)

    try:
        if live:
            return _run_live(args, transcriber, translator, on_line, on_status, overlay)
        return _run_file(args, transcriber, translator, on_line, on_status, overlay, beam)
    finally:
        if writer:
            writer.close()
            log(f"Transcript saved to {args.save}")


def _run_live(args, transcriber, translator, on_line, on_status, overlay) -> int:
    from .audio import SoundcardSource
    from .pipeline import LivePipeline
    from .segmenter import Segmenter

    source = SoundcardSource(loopback=not args.mic, device=args.device)
    segmenter = Segmenter(silence_ms=args.pause_ms, max_segment_s=args.max_seconds)
    pipeline = LivePipeline(source, transcriber, translator, on_line, on_status,
                            translate=args.to != "de", segmenter=segmenter).start()
    log("Press Ctrl+C to stop." if not overlay else "Esc or double-click the subtitles to stop.")
    try:
        if overlay:
            overlay.run(should_stop=pipeline.stop_event.is_set)
        else:
            while not pipeline.wait(0.5):
                pass
    except KeyboardInterrupt:
        pass
    finally:
        pipeline.stop()
    return 1 if pipeline.error else 0


def _run_file(args, transcriber, translator, on_line, on_status, overlay, beam) -> int:
    from .pipeline import run_file

    with tempfile.TemporaryDirectory(prefix="swiss-ru-de-") as tmp:
        if args.url:
            from .audio import download_audio

            on_status("Downloading audio …")
            path, title = download_audio(args.url, Path(tmp))
            on_status(f"Transcribing: {title}")
        else:
            path = Path(args.file)
            if not path.exists():
                log(f"File not found: {path}")
                return 2

        stop = threading.Event()
        started = time.monotonic()

        def work() -> None:
            try:
                run_file(transcriber, translator, str(path), on_line, on_status,
                         translate=args.to != "de", beam_size=beam, stop=stop)
            except Exception as e:
                on_status(f"Failed: {e}")
            finally:
                stop.set()

        if overlay:
            t = threading.Thread(target=work, daemon=True)
            t.start()
            overlay.run()  # keeps the last subtitle visible until closed
            stop.set()
            t.join()
        else:
            try:
                work()
            except KeyboardInterrupt:
                stop.set()
        log(f"Done in {time.monotonic() - started:.0f} s.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
