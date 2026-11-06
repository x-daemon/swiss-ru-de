# swiss-ru-de

Live **Swiss German → Russian / German** subtitles for anything you hear on your PC:
Teams or Zoom calls, YouTube, SRF Play, podcasts, or audio and video files.

![Window with the Swiss German as spoken on top and the Russian translation below (example text)](docs/window.png)

The window has two parts:

* **Top: Schwiizerdütsch as spoken.** What the speaker said, written in dialect.
* **Bottom: the translation.** Russian or Standard German; you choose in **Settings**.

Each sentence shows up in both parts on the same row, with the same time stamp. Drag the bar
between the parts to resize them.

```
PC audio ─► pause detection ─┬► Whisper fine-tuned on Swiss German ─► Standard German ─► Russian   (bottom)
(Teams, YouTube, …)          └► Whisper + dialect style prompt ─────► dialect as spoken           (top)
```

* **Dialects.** The default speech model is Whisper large-v3-turbo fine-tuned on Swiss German.
  Its training data (STT4SG-350, SDS-200, SwissDial, Swiss Parliaments Corpus) covers Bern, Basel,
  Zurich, Valais, Grisons, and Central and Eastern Switzerland. You don't need to pick a dialect.
  The model writes what it hears as Standard German.
* **Fast.** It runs locally with [faster-whisper](https://github.com/SYSTRAN/faster-whisper).
  On an NVIDIA GPU a sentence should appear about a second after the speaker pauses; on a modern
  CPU expect a few seconds. If the computer falls behind, waiting sentences are joined and
  recognised together, so it catches up.
* **Simple.** Double-click to start. Besides the two-part window, there is a compact
  always-on-top subtitle strip (`--overlay`), terminal output, and `.srt` or `.txt` export.

## iPhone

There is also an iPhone app with the same two-part screen. It runs speech recognition on the
iPhone itself and listens to the microphone, to other apps on the iPhone (YouTube, …) or to
files. It can show floating captions over other apps. See **[ios/README.md](ios/README.md)**
for installing it with Xcode, or with Sideloadly on Windows using the `.ipa` built by
GitHub Actions.

## Install

**Windows:** install [Python 3.10+](https://www.python.org/downloads/) and tick *"Add python.exe
to PATH"*. Then double-click **`start-windows.bat`**. The first start installs everything and
downloads the models (a few GB, once). After that, the two-part window opens and shows
whatever your PC is playing.

**Manual install (Windows, Linux, macOS):**

```bash
git clone https://github.com/x-daemon/swiss-ru-de && cd swiss-ru-de
python -m venv .venv && source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -e ".[all]"      # or only what you need: ".[claude]", ".[deepl]", ".[offline]"
```

## The window

```bash
swiss-ru-de --gui                    # or: swiss-ru-de-gui (no console window), start-windows.bat
swiss-ru-de --gui --url "https://www.youtube.com/watch?v=..."   # a whole video in the window
```

| Button / key | What it does |
|---|---|
| **Settings** (Ctrl+,) | Choose the bottom part: **Русский** or **Hochdeutsch**. Choose the top part: dialect as spoken, or Standard German. Also: dialect hint, translator, which speaker, microphone or headset to listen to, font size, always on top, speech model. Settings are saved and apply immediately. Only the speech model and the GPU/CPU choice need a restart. |
| **Pause** (Space) | Ignore audio for a moment, e.g. during a private side conversation. |
| **Save…** (Ctrl+S) | Export everything to `.srt` subtitles or `.txt`. |
| **Clear** (Ctrl+L) | Empty both parts. |
| Ctrl + / Ctrl − | Change the font size. |

**How the dialect line works.** The Swiss German speech models are trained to write Standard
German, so the top part uses a second model. It is plain Whisper, guided by a short example text
written in the chosen dialect (for example Bärndütsch for `bern`, Baseldytsch for `basel`), so
that it writes what it hears the same way. Swiss German has no fixed spelling, so the top line is
an approximation of what was said. The bottom line (meaning, translation) comes from the Swiss
German model. On CPU-only PCs, the second model roughly doubles the work. If the PC can't keep
up, set the top part to *Standard German*.

## Command line

```bash
swiss-ru-de                          # everything playing on the PC -> Russian, in the terminal
swiss-ru-de --dialect-text           # ... with the dialect as spoken above each line
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

* All dialects are recognised automatically. The dialect setting (`--dialect bern|berner-oberland|basel|zurich|wallis|…`)
  is an optional hint. It sets the spelling style of the dialect line and gives the Claude
  translator context.
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

How fast this runs depends almost entirely on whether there is an **NVIDIA graphics card**:

| Hardware | Delay per sentence |
|---|---|
| NVIDIA GPU (GeForce RTX, …) | well under a second, about 10x faster than CPU |
| Modern CPU only | a few seconds |

* **GPU:** `start-windows.bat` detects an NVIDIA card (`nvidia-smi`) and installs the CUDA
  libraries with pip (about 1 GB, once). Nothing else to install, apart from a current NVIDIA
  driver. Manual install: `pip install -e ".[all,gpu]"`. Check *Settings → Run on*: `auto`
  uses the GPU when it works.
* **CPU only:**
  * Live recognition uses a single decoding pass. The retry passes Whisper does on unclear
    audio are only used for files.
  * The dialect line (2nd model) is filled in only when no other speech is waiting, so the
    translation never falls behind. For the fastest results, set the top part to
    *Standard German*.
  * The offline translator is converted to CTranslate2 int8 on first use. It is about 3x
    faster and leaves the CPU to speech recognition. Claude and DeepL use no local CPU at all.
* `--to de` skips translation entirely.
* `--pause-ms 400` shows sentences sooner, but cuts them more often.

## Translation quality

The offline translator is free, but translates literally. For example it turns *Zmorge*
(breakfast) into "tomorrow". Common Swiss words (Zmorge, Velo, Natel, Gipfeli, Spital, …) are
replaced by Standard German before it translates, which helps somewhat. The real fix is
**Claude** (best: uses the earlier sentences, knows Swiss words, corrects recognition errors)
or **DeepL**. Paste a key in *Settings → Claude API key / DeepL API key*. It is stored in the
Windows Credential Manager, not in a file.

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

Code layout: `audio.py` (capture), `segmenter.py` (pause detection), `asr.py` (faster-whisper,
dialect prompts), `translate.py` (Claude / DeepL / offline), `pipeline.py` (threads),
`gui.py` (two-part window and settings), `settings.py`, `output.py` / `overlay.py` (display).

**Status (v0.2):** the full pipeline is covered by tests that use simulated audio and a simulated
model. The window was checked on a virtual display. It has not yet been benchmarked on real Swiss
German recordings, and how well the dialect line follows each dialect is untested. Feedback per
dialect is welcome.

---

## Кратко по-русски

Программа в реальном времени переводит швейцарский немецкий (все диалекты: Берн, Базель, Цюрих,
Гриндельвальд/Бернский Оберланд, Вале и др.) на русский или литературный немецкий. Она слушает всё,
что звучит на компьютере: Teams, YouTube, файлы.

1. Установите Python 3.10+ (отметьте «Add python.exe to PATH»).
2. Запустите `start-windows.bat`. Первый запуск устанавливает программу и скачивает модели (несколько ГБ).
3. Откроется окно из двух частей. Сверху: швейцарский немецкий, как его произнесли (на диалекте).
   Снизу: перевод на русский или литературный немецкий; выбор в **Settings**.

Для лучшего перевода задайте ключ `ANTHROPIC_API_KEY` (Claude) или `DEEPL_AUTH_KEY` (DeepL).
Без ключа работает офлайн-перевод.

## License

MIT. The speech and translation models have their own licences; check them on their model pages
before commercial use.
