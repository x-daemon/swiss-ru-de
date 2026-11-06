# Swiss RU-DE for iPhone

The iPhone version of swiss-ru-de, with the same two-part screen as the desktop window:

* **Top: Schwiizerdütsch as spoken.** What the speaker said, written in dialect.
* **Bottom: the translation.** Русский or Hochdeutsch; you choose in Settings.

Speech recognition runs **on the iPhone** with [WhisperKit](https://github.com/argmaxinc/argmax-oss-swift)
on the Neural Engine. Audio never leaves the phone. Only when you choose Claude or DeepL as
translator is the recognised German text sent to that service.

| Listen to | How |
|---|---|
| **Microphone** | A Teams call on your laptop, the TV, people in the room. |
| **iPhone audio** | YouTube, Safari, podcasts and other apps on the iPhone itself. Choose *iPhone audio*, tap the round broadcast button next to **Start** and pick **Swiss RU-DE Audio**. iOS shows a red status-bar indicator while it runs. |
| **Files** | ⋯ → *Transcribe a file…*: audio or video from the Files app (mp3, m4a, mp4, mov, …). |

**Floating captions** (⋯ menu) show the current dialect line and translation in a
Picture-in-Picture window. That window stays on top while you use YouTube or another app.

Translation to Russian has three options:

* **Apple (on device):** free and private. iOS asks once to download German and Russian.
* **Claude:** best quality. Needs an [Anthropic API key](https://console.anthropic.com), which is stored in the iPhone Keychain.
* **DeepL:** very good. The free key is enough.

## Install on your iPhone

Apple only lets you install your own apps that are signed with your Apple ID. A free Apple ID
works, but a free install has to be renewed every 7 days. A paid developer account
(99 USD/year) lasts a year.

First enable **Developer Mode** on the iPhone: *Settings → Privacy & Security → Developer
Mode → On*, then restart the phone.

### Option A: with a Mac (recommended)

1. Install Xcode from the App Store and [Homebrew](https://brew.sh), then XcodeGen:
   ```bash
   brew install xcodegen
   ```
2. Get the code and generate the Xcode project:
   ```bash
   git clone https://github.com/x-daemon/swiss-ru-de && cd swiss-ru-de/ios
   ```
   Open `Config.xcconfig` and change `BUNDLE_ID_PREFIX = ch.example` to something unique,
   e.g. `ch.yourname`. Then run:
   ```bash
   xcodegen
   ```
   ```bash
   open SwissRuDe.xcodeproj
   ```
3. In Xcode, sign in under *Settings → Accounts* with your Apple ID. Then select the
   **SwissRuDe** target → *Signing & Capabilities* → *Team* (your name), and do the same for
   the **SwissRuDeBroadcast** target.
4. Connect the iPhone by cable, select it at the top of the window, and press **Run (⌘R)**.
5. On the iPhone the first time: *Settings → General → VPN & Device Management* → trust your
   Apple ID.

### Option B: without a Mac (Windows + Sideloadly)

1. Download the ready-built app: on GitHub open **Actions → iOS app**, click the latest green
   run, and download **SwissRuDe-ipa** under *Artifacts*. Unzip it to get
   `SwissRuDe-unsigned.ipa`.
2. Install [Sideloadly](https://sideloadly.io) and iTunes (from apple.com, not the Microsoft
   Store version) on Windows.
3. Connect the iPhone, drag the `.ipa` into Sideloadly, enter your Apple ID and press
   **Start**.
4. On the iPhone: *Settings → General → VPN & Device Management* → trust your Apple ID.

With Option B, *iPhone audio* may not work: it needs an App Group shared between the app and
its broadcast extension, and sideloading tools don't always set that up. Microphone, files,
translation and floating captions work either way.

## First start

The app downloads the speech model (Whisper large-v3 turbo, about 626 MB; use Wi-Fi). Then iOS
prepares the model for the Neural Engine, which takes a few minutes once. After that it
starts in seconds.

## Speech model and dialects

The default model is OpenAI's multilingual Whisper. It understands Swiss German reasonably
well and writes:

* **Bottom:** Standard German.
* **Top:** dialect spelling. The model runs a second time, guided by an example text in the
  dialect chosen in Settings (Bärndütsch, Baseldytsch, Grindelwald, …).

For better Standard German you can convert a Whisper model fine-tuned on Swiss German (for
example `Flurin17/whisper-large-v3-turbo-swiss-german`) to Core ML on a Mac with
[whisperkittools](https://github.com/argmaxinc/whisperkittools) and upload it to your own
Hugging Face repo. Then:

1. Enter that model in *Settings → Speech model*.
2. Turn on *Separate model for the dialect line*, keeping the default model for it.
3. Tap *Load these models*.

The fine-tune only writes Standard German, so the dialect line still needs plain Whisper.

## Limits

* *iPhone audio* uses screen broadcasting. Audio of phone and VoIP calls (Teams, FaceTime,
  WhatsApp calls on the same iPhone) may be excluded by iOS. For calls, run Teams on another
  device and use the microphone.
* Running the dialect line doubles the work per sentence. On older iPhones, switch the top part
  to *Standard German* if the text lags behind.
* With Apple translation, iOS may pause translating while the app is in the background.
  Claude and DeepL keep working there.
* Tell people in a conversation before you transcribe it.

## Project layout

```
ios/
  project.yml            XcodeGen project (app + broadcast extension)
  Config.xcconfig        bundle id prefix, team
  SwissRuDe/App          app entry, AppModel (pipeline: segments -> German -> translation/dialect)
  SwissRuDe/Audio        microphone, iPhone audio reader, files, pause detection (Segmenter)
  SwissRuDe/Speech       WhisperKit recogniser, dialect prompts, hallucination filter
  SwissRuDe/Translation  Apple / Claude / DeepL
  SwissRuDe/UI           two-part screen, settings, floating captions (PiP)
  Broadcast/             ReplayKit extension: other apps' audio -> shared ring buffer
  Shared/                ring buffer + resampler used by app and extension
```

The GitHub Actions workflow `.github/workflows/ios.yml` builds the app on every change and
publishes the unsigned `.ipa`.
