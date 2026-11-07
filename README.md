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

### Windows: the install pack (recommended)

1. Download the project as ZIP (on GitHub: *Code → Download ZIP*, or the archive you were
   sent) and unzip it, e.g. to `C:\swiss-ru-de`.
2. Double-click **`install-windows.bat`**. It does everything, in 10 to 30 minutes (up to
   about 12 GB of downloads):
   1. Python 3.12, only if no Python 3.10+ is installed (via winget);
   2. swiss-ru-de with all translators, plus the CUDA libraries if an NVIDIA graphics card
      is found;
   3. **Local AI**: Ollama and a translation model that fits the graphics card next to the
      speech models (`gemma3:12b` with 16 GB or more, otherwise `gemma3:4b`). Settings are
      switched to it;
   4. the speech models, so the first start is fast;
   5. **"Swiss RU-DE"** shortcuts on the desktop and in the Start menu;
   6. starts the app.
3. From then on, start it with the **Swiss RU-DE** icon.

Running `install-windows.bat` again updates everything (e.g. after downloading a newer
version). `install-local-ai.bat` installs only Ollama and the model; *Settings → Install
Ollama + model…* runs it too. `uninstall-windows.bat` removes shortcuts, the Python
environment and, if you choose, the models and settings.

**Removing old installations.** Every older archive you unpacked has its own Python
environment (1–4 GB). After installing the new version, double-click
**`cleanup-old-installs.bat`** in the new folder. It looks on the Desktop, in Downloads,
Documents, OneDrive and the top folders of every drive. It finds, and asks about each one
before deleting:

* old copies of swiss-ru-de and their `.venv`. A folder that holds files of your own (e.g. a
  saved transcript), or a newer version, is kept unless you say otherwise;
* shortcuts that point to old copies (the *Swiss RU-DE* shortcuts are then pointed to the new
  folder);
* swiss-ru-de installed into a system Python by an older manual install;
* speech models and Ollama models that the current settings no longer use (e.g. `gemma3:12b`
  once you use `gemma3:4b`), the pip download cache and the Ollama installer.

The folder you start it from is never touched, even if you unpacked it inside the old one.
`cleanup-old-installs.bat --list` only shows what it would remove.

`start-windows.bat` remains as a launcher that also shows a console window, which is useful
when something goes wrong.

### Manual install (Windows, Linux, macOS)

```bash
git clone https://github.com/x-daemon/swiss-ru-de && cd swiss-ru-de
python -m venv .venv && source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -e ".[all]"      # add ,gpu for an NVIDIA card: ".[all,gpu]"
swiss-ru-de --gui
```

For local AI on Linux/macOS, install Ollama from [ollama.com](https://ollama.com) and run
`ollama pull gemma3:4b`.

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

| Translator (*Settings → Translator*) | Quality | Key from | Default model (editable) |
|---|---|---|---|
| **Claude** (Anthropic) | best | console.anthropic.com | `claude-opus-5-5`; `claude-haiku-5-5` is fastest and cheapest |
| **ChatGPT** (OpenAI) | very good | platform.openai.com → API keys | `gpt-6-luna` (fast, cheap); `gpt-6-sol`, `gpt-6-astra` are stronger |
| **Gemini** (Google) | very good | aistudio.google.com → Get API key | `gemini-3.8-flash`; `gemini-3.5-flash-lite` is cheapest |
| **Grok** (xAI) | very good | console.x.ai → API keys | `grok-4.7` |
| **Local AI** (Ollama / LM Studio) | good to very good, **stays on your PC** | no key | `gemma3:4b` (fast, up to 12 GB graphics memory); `gemma3:12b` (16 GB+); `translategemma:12b` translates only |
| **DeepL** | good | deepl.com/pro-api (free key available) | – |
| **offline** | basic | no key | NLLB-200, runs on your PC |

The AI models (Claude, ChatGPT, Gemini, Grok, local AI) do more than translate:

* they also **correct recognition errors**, using the dialect line as a second hearing and the
  earlier sentences as context (see *Translation quality*);
* with the bottom part set to *Hochdeutsch*, they only correct the German.

In *Settings*, pick the translator, paste its API key and choose the model. Keys are stored
in the Windows Credential Manager, one per provider, so you can switch at any time. *auto*
uses the first one with a key, in the order Claude, ChatGPT, Gemini, Grok, DeepL, offline.

ChatGPT, Gemini and Grok all use the official `openai` Python SDK: the three providers offer
the same OpenAI-compatible API. If a model rejects an option (`reasoning_effort` or JSON
schema output), the app retries without it and remembers that.

On the command line use `--translator claude|openai|gemini|grok|deepl|offline`, with
`--translator-model <id>` to pick the model and the environment variables `ANTHROPIC_API_KEY`,
`OPENAI_API_KEY`, `GEMINI_API_KEY` (or `GOOGLE_API_KEY`), `XAI_API_KEY` or `DEEPL_AUTH_KEY`.

### Everything local: AI translation on your graphics card

With an NVIDIA card (8 GB or more), a local AI model can do Claude's job without any cloud.
It corrects the recognised German and translates with context, and nothing leaves the PC.

1. Install **[Ollama](https://ollama.com)** (Windows installer). It runs in the background.
2. In a terminal, download the model (once, about 3 GB):
   ```bash
   ollama pull gemma3:4b
   ```
3. In *Settings → Translator*, choose **Local AI on this PC**. The model list shows the models
   Ollama has installed; pick one and save. With no model chosen, the app uses the first
   installed of `gemma3:4b`, `gemma3:12b`, `qwen3:14b`.

Notes:

* **Graphics memory decides the speed.** The model must fit into the graphics card *next to*
  the two speech models (about 2.5 GB) and Windows. `gemma3:4b` needs about 5 GB, so it fits
  on any 8–12 GB card. `gemma3:12b` needs about 10 GB: on a 12 GB card (e.g. RTX 3060) it
  does not fit, Ollama runs part of it on the processor, and the subtitles fall **minutes**
  behind. Use it only with 16 GB or more. The app checks this when it starts and says so in
  the status line ("runs 40 % on the processor …").
* **Speed settings for local AI:** no "thinking" (Qwen3), temperature 0.2 (literal
  translations), a cap on the answer length (`max_tokens`, which Ollama reads; a small model
  that starts repeating itself cannot run for minutes), and the model is kept loaded for
  30 minutes.
* **Small models get a simpler job.** For Russian only, the local model is asked for plain
  text, not JSON: small models break JSON (curly quotes) and then loop. It gets only the
  recognised German, with Swiss words already replaced (*Buttergipfel* → *Buttercroissant*),
  not the dialect line as well: given two versions, a 4B model translated both and doubled
  sentences. Labels, Latin transliterations in brackets and repetition loops are removed
  from its answers.
* `translategemma:4b` is a translation-only model of the same size (it doesn't correct the
  German). It is an alternative to `gemma3:4b` when only Russian is shown.
* **Only the Russian is asked for** when the corrected German isn't on screen (top part =
  dialect, bottom part = Russian): half the answer, so about twice as fast. Set the top part
  to *Standard German* to see the AI-corrected German.
* **The dialect line never holds anything up.** It runs in its own thread, only when no other
  speech is waiting, and the AI stops waiting for it when it keeps coming late.
* **Lagging behind?** The status line says so (every minute while the subtitles are more than
  15 s behind) and names the slowest step. *Settings → Check this PC* shows the time per step.
* **First sentence:** the model is loaded when the app starts, so the first sentence is fast.
* **LM Studio** works too: start its local server and set *Server* to
  `http://localhost:1234/v1`.
* **Translation-only models** such as `translategemma:12b` get a plain translation prompt. They
  don't correct recognition errors.

The free **offline** translator (NLLB) now translates **sentence by sentence**, because given
several sentences at once it dropped most of them. It also reads *zum Morgen* as *Zmorge*
(breakfast).

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

## Speed and precision: choose the recogniser

| Recogniser (Settings → *Recognise with*) | Speed | Notes |
|---|---|---|
| **Azure cloud (de-CH)** | Text appears *while* people speak; the final sentence ~1 s after the pause | Microsoft's [Swiss German dialect model](https://azure.microsoft.com/en-gb/updates/release-of-swiss-german-dialect-speech-to-text/). Writes Standard German. No CPU load. Free tier: 5 h audio per month, then about 1 USD per hour. Only speech is sent, not silence. |
| **This PC + NVIDIA GPU** | about 1 s per sentence | Free and private. `start-windows.bat` installs the CUDA libraries automatically. |
| **This PC, CPU only** | a few seconds per sentence | Free and private, but slow on weak PCs. |

**Setting up Azure (5 minutes, free tier):**

1. Sign in at [portal.azure.com](https://portal.azure.com) (a free account works).
2. *Create a resource → Speech*.
3. Choose region **Switzerland North** and pricing tier **Free F0**, then create it.
4. Open the resource → *Keys and Endpoint* → copy **Key 1**.
5. In swiss-ru-de *Settings*, set *Recognise with* to **Azure cloud**, paste the key, and
   check that the region is `switzerlandnorth`. Save.

The key is stored in the Windows Credential Manager. On the command line use
`--recognizer azure` with the `AZURE_SPEECH_KEY` environment variable. Names and terms from
`--hint` are passed to Azure as a phrase list. Files and YouTube links always use the local
recogniser.

With Azure, the dialect line (top) still comes from the local model. It is filled in when the
CPU has time; until then the top shows the Standard German, dimmed.

**On this PC (no cloud) it tunes itself.** At start it times one pass of the speech model,
which costs the same for every sentence (a 30 s window). Live mode then picks:

| Time per pass | Mode | What changes |
|---|---|---|
| ≤ 1 s (GPU) | precise | wider search (beam 5), dialect line on, segments from 2 s |
| 1–2.5 s | balanced | dialect line only when idle, segments ≥ 2× the pass time |
| > 2.5 s (slow CPU) | fast | dialect line paused (it would double the work and hold up the next sentence), segments of 2× the pass time (max 8 s), so recognition keeps up |

Force a mode in *Settings → Speed* (or `--speed fast|precise`). *Settings → Check this PC…*
or `swiss-ru-de --benchmark` shows the processor, the graphics card, the measured time per
pass, and what would make this PC faster. For example, an NVIDIA card whose CUDA libraries
are missing.

**Further details:**

* Short utterances are joined (at least ~3 s, up to a 1.5 s pause). Whisper is more precise
  with more context, and every recognition pass costs the same 30 s window, so this is also
  faster. Change it with `--min-seconds`.
* Live mode decodes once (no retry passes). With a GPU it searches wider (beam 5) for more
  precision.
* The dialect line is filled in only when no other speech is waiting.
* GPU: `start-windows.bat` detects an NVIDIA card and installs cuBLAS/cuDNN with pip (about
  1 GB, once). Manual install: `pip install -e ".[all,gpu]"`.

## Translation quality

**With Claude, ChatGPT, Gemini or Grok, recognition errors are corrected too.** Speech
recognition stays on your PC (Whisper on the GPU or CPU), or optionally Azure; the AI model
gets text. For each sentence it gets:

* the recognised Standard German;
* the dialect line, as a second hearing of the same audio (it waits for it at most 1.5 s);
* the previous sentences.

The model returns the **corrected German sentence and its translation** in one request
(JSON output). Misheard words are fixed (*Gipfel* at breakfast → *Gipfeli*), and the corrected
German is what the window, the transcript and the next sentence's context use. With the
bottom part set to *Hochdeutsch*, the model only corrects the German.


The bottom header shows which translator is active (e.g. *перевод · offline, basic
quality*). The offline translator is free, but translates literally. For example it turns *Zmorge*
(breakfast) into "tomorrow". About 45 common Swiss words (Zmorge, Gipfeli, Weggli, Schoggi, Peperoni, Velo, Natel,
Spital, …) are replaced by Standard German before it translates. Context is used too:
*Gipfel* in a sentence about breakfast or a bakery becomes *Croissant*, not a mountain peak.
This helps, but a small offline model still translates word by word. The real fix is
**Claude** (best: uses the earlier sentences, knows Swiss words, corrects recognition errors)
or **DeepL**. Paste a key in *Settings → Claude API key / DeepL API key*. Under *Claude model*,
choose **Opus 5.5** (best) or **Haiku 5.5** (fastest, a fraction of the cost). It is stored in the
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

1. Распакуйте архив и дважды щёлкните **`install-windows.bat`**. Он сам установит:
   Python (если его нет), программу, поддержку видеокарты NVIDIA, локальный ИИ (Ollama +
   модель перевода по объёму видеопамяти: до 12 ГБ `gemma3:4b`, от 16 ГБ `gemma3:12b`), модели распознавания и ярлык **Swiss RU-DE** на
   рабочем столе. Это займёт 10–30 минут, скачивается до 12 ГБ.
2. Дальше запускайте программу ярлыком **Swiss RU-DE**.
3. Откроется окно из двух частей. Сверху: швейцарский немецкий, как его произнесли (на диалекте).
   Снизу: перевод на русский или литературный немецкий; выбор в **Settings**.

Чтобы было **быстро и точно** на компьютере без видеокарты NVIDIA:

1. *Settings → Recognise with → Azure cloud*, ключ Azure Speech (регион Switzerland North,
   5 бесплатных часов в месяц). Текст появляется прямо во время речи.
2. Ключ **Claude** или **DeepL** в *Settings*. Без ключа используется офлайн-перевод,
   а он переводит дословно и с ошибками.

Полностью локально, без облака, программа сама подстраивается под скорость компьютера.
*Settings → Check this PC…* показывает процессор, видеокарту и замеренную скорость, а также
что ускорит работу именно на этом компьютере. Самое большое ускорение (примерно в 10 раз)
даёт видеокарта NVIDIA.

**Старые установки** (каждый распакованный архив занимает 1–4 ГБ): после установки новой
версии дважды щёлкните **`cleanup-old-installs.bat`** в новой папке. Он находит старые копии,
ярлыки на них, неиспользуемые модели (например, `gemma3:12b`) и кэши загрузок и про каждую
спрашивает, удалить ли её. Текущая папка не затрагивается. Папки с вашими файлами
(например, сохранёнными расшифровками) по умолчанию остаются.

**Локальный ИИ (Ollama) отстаёт на минуты?** Почти всегда причина в видеопамяти: модель
должна поместиться в видеокарту *рядом* с двумя моделями распознавания (около 2,5 ГБ).
На карте 12 ГБ (например, RTX 3060) `gemma3:12b` не помещается, Ollama считает часть на
процессоре, и перевод сильно запаздывает. Возьмите **`gemma3:4b`** (*Settings → Model*);
`gemma3:12b` имеет смысл с 16 ГБ видеопамяти. Программа сама проверяет это при запуске и
пишет в строке состояния. Если сверху показан диалект, ИИ пишет только русский перевод:
ответ вдвое короче и вдвое быстрее. *Settings → Check this PC…* показывает, сколько секунд
занимает каждый шаг.

## License

MIT. The speech and translation models have their own licences; check them on their model pages
before commercial use.
