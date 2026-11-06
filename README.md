# swiss-ru-de

Live **Swiss German → Russian / German** subtitles for anything you hear on your PC:
Teams or Zoom calls, YouTube, SRF Play, podcasts, or audio and video files.

```
PC audio ─► pause detection ─► Whisper fine-tuned on Swiss German ─► Standard German ─► Russian
(Teams, YouTube, …)                (all dialects)                       (--to de)         (--to ru)
```

* **Dialects.** The default speech model is Whisper large-v3-turbo fine-tuned on Swiss German.
  Its training data (STT4SG-350, SDS-200, SwissDial, Swiss Parliaments Corpus) covers Bern, Basel,
  Zurich, Valais, Grisons, and Central and Eastern Switzerland. You don't need to pick a dialect.
  The model writes what it hears as Standard German.
* **Fast.** It runs locally with [faster-whisper](https://github.com/SYSTRAN/faster-whisper).
  On an NVIDIA GPU a sentence should appear about a second after the speaker pauses; on a modern
  CPU expect a few seconds. If the computer falls behind, waiting sentences are joined and
  recognised together, so it catches up.
* **Simple.** One command. You can show the subtitles in a floating window that stays on top of
  other windows, or save them as `.srt` or `.txt`.

## Install

**Windows:** install [Python 3.10+](https://www.python.org/downloads/) and tick *"Add python.exe
to PATH"*. Then double-click **`start-windows.bat`**. The first start installs everything and
downloads the models (a few GB, once). After that, the subtitle window opens and shows
whatever your PC is playing.

**Manual install (Windows, Linux, macOS):**

```bash
git clone https://github.com/x-daemon/swiss-ru-de && cd swiss-ru-de
python -m venv .venv && source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -e ".[all]"      # or only what you need: ".[claude]", ".[deepl]", ".[offline]"
```

## Use

```bash
swiss-ru-de                          # everything playing on the PC -> Russian, in the terminal
swiss-ru-de --overlay                # ... in a floating subtitle window
swiss-ru-de --to de                  # Standard German only (no translation, fastest)
swiss-ru-de --to both --overlay      # German (small) + Russian (large)
swiss-ru-de --device "Headset"       # listen to a specific speaker or headset, see --list-devices
swiss-ru-de --url "https://www.youtube.com/watch?v=..." --to both --save video.srt
swiss-ru-de --file interview.mp4 --save interview.srt
```

| Source | How |
|---|---|
| **Teams / Zoom / Webex** | Just run it. It captures the speaker or headset that Teams plays on. If that is not your default device, use `--device "<name>"` (see `--list-devices`). |
| **YouTube in the browser** | Just run it and press play. |
| **YouTube link** | `--url <link>` downloads only the audio and processes it faster than real time. |
| **Files** | `--file` takes any audio or video file (mp3, m4a, wav, mp4, mkv, …). |
| **Microphone** | `--mic` (add `--device` to choose one). |

Overlay window: drag it with the mouse, use the mouse wheel to change the font size, and
double-click or press Esc to close it.

> Recording or transcribing a conversation without the consent of the participants is restricted
> in Switzerland (Art. 179bis/ter StGB). Tell the people in your call before you use this.

## Translation to Russian

| `--translator` | Quality | Needs | Notes |
|---|---|---|---|
| `claude` | best | `ANTHROPIC_API_KEY` | Uses the previous sentences as context, fixes obvious recognition errors, handles leftover dialect words (*öppis, gäll, lueg …*). Default model `claude-opus-5-5` at low effort. Use `--claude-model claude-haiku-5-5` for lower cost and latency. |
| `deepl` | very good | `DEEPL_AUTH_KEY` | The [free API key](https://www.deepl.com/pro-api) covers 500 000 characters/month. |
| `offline` | good | nothing | NLLB-200 600M runs locally. Nothing leaves your PC. |

The default is `auto`: it uses Claude if `ANTHROPIC_API_KEY` is set, DeepL if `DEEPL_AUTH_KEY`
is set, and the offline model otherwise.

```bash
# Windows (PowerShell):  $env:ANTHROPIC_API_KEY="sk-ant-..."
export ANTHROPIC_API_KEY=sk-ant-...
swiss-ru-de --to both --dialect berner-oberland
```

## Dialects and accuracy tips

* All dialects are recognised automatically. `--dialect bern|berner-oberland|basel|zurich|wallis|…`
  is only an optional hint for the Claude translator.
* **Highest Alemannic** dialects (Bernese Oberland, e.g. Grindelwald, and Valais) are the hardest
  for every model. For these, try `--model swiss-large` (slower, often more accurate) and
  `--beam 5`.
* Use `--hint "Grindelwald, Eiger, Jungfraubahn, Frau Wyss"` to give the model names and terms
  that come up in the audio.
* Speech models:

  | `--model` | What it is |
  |---|---|
  | `swiss-turbo` (default) | large-v3-turbo + Swiss German fine-tune: fast, good |
  | `swiss-turbo-int8` | the same model, int8 quantised: smaller, for CPU-only PCs |
  | `swiss-large` | large-v3 + Swiss German LoRA (MIT): slower, often more accurate |
  | `turbo`, `large` | original OpenAI Whisper, no Swiss fine-tune |
  | any Hugging Face repo or local folder | must be in faster-whisper (CTranslate2) format |

  If a preset can't be downloaded, the tool falls back to plain `large-v3-turbo`.

## Speed

* **NVIDIA GPU:** the tool uses it automatically when CUDA 12 and cuDNN 9 are installed.
  On Windows, put the [cuBLAS/cuDNN DLLs](https://github.com/Purfview/whisper-standalone-win/releases/tag/libs)
  next to `python.exe` or on `PATH`. To force the GPU, use `--gpu`.
* **CPU only:** this works. Expect a few seconds of delay per sentence. `--model swiss-turbo-int8`
  and the default `--beam 1` are the fastest settings.
* `--to de` skips translation entirely.
* `--pause-ms 400` shows sentences sooner, but cuts them more often.

## Platform notes

* **Windows:** captures system audio directly (WASAPI loopback). Nothing else to install.
* **Linux:** captures PulseAudio or PipeWire "monitor" sources directly.
* **macOS:** macOS can't capture system audio by itself. Install
  [BlackHole](https://github.com/ExistentialAudio/BlackHole), create a *Multi-Output Device*
  (speakers + BlackHole) in Audio MIDI Setup, then run `swiss-ru-de --mic --device BlackHole`.

## Troubleshooting

| Problem | Fix |
|---|---|
| Nothing appears | Run `swiss-ru-de --list-devices` and pick the device that actually plays the sound with `--device`. |
| It crashes at start with a `cudnn`/`cublas` error | Use `--cpu`, or install the CUDA libraries (see Speed). |
| Text appears during music or silence | Known Whisper "hallucinations" (TV subtitle credits and similar) are filtered out. Report others in an issue. |
| Sentences are cut in the middle | Raise `--pause-ms` (e.g. 900). |

## Development

```bash
pip install -e ".[dev,claude,deepl]"
pytest
```

Code layout: `audio.py` (capture), `segmenter.py` (pause detection), `asr.py` (faster-whisper),
`translate.py` (Claude / DeepL / offline), `pipeline.py` (threads), `output.py` / `overlay.py` (display).

**Status (v0.1):** the full pipeline is covered by tests that use simulated audio and a simulated
model. It has not yet been benchmarked on real Swiss German recordings. Feedback per dialect is
welcome.

---

## Кратко по-русски

Программа в реальном времени переводит швейцарский немецкий (все диалекты: Берн, Базель, Цюрих,
Гриндельвальд/Бернский Оберланд, Вале и др.) на русский или литературный немецкий. Она слушает всё,
что звучит на компьютере: Teams, YouTube, файлы.

1. Установите Python 3.10+ (отметьте «Add python.exe to PATH»).
2. Запустите `start-windows.bat`. Первый запуск устанавливает программу и скачивает модели (несколько ГБ).
3. Появится окно с субтитрами поверх всех окон. Чтобы закрыть его, нажмите Esc или дважды щёлкните по нему.

Для лучшего перевода задайте ключ `ANTHROPIC_API_KEY` (Claude) или `DEEPL_AUTH_KEY` (DeepL).
Без ключа работает офлайн-перевод.

## License

MIT. The speech and translation models have their own licences; check them on their model pages
before commercial use.
