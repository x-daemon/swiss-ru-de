"""Two-pane live subtitle window.

    ┌───────────────────────────────────────────────┐
    │ ● Listening to PC audio …   Pause Clear Save ⚙ │
    ├───────────────────────────────────────────────┤
    │ SCHWIIZERDÜTSCH  as spoken                    │  top: the dialect as heard
    │ 00:12  Mir gönd hüt uf Grindelwald.           │
    ├────────────── drag to resize ─────────────────┤
    │ РУССКИЙ  перевод                              │  bottom: Russian or Standard
    │ 00:12  Сегодня мы едем в Гриндельвальд.       │  German (Settings)
    └───────────────────────────────────────────────┘

Rows are aligned by time stamp. Every utterance appears as soon as its first part is
ready, and is filled in when the rest arrives.
"""

from __future__ import annotations

import os
import queue
import sys
import threading
from dataclasses import replace
from pathlib import Path

from .config import DIALECTS, MODEL_PRESETS
from .output import TranscriptWriter, clock
from .pipeline import Line, LineBook, LivePipeline, Options, run_file
from .settings import Settings, config_dir, load_settings, save_settings
from .translate import TranslatorHub

C = dict(
    bg="#0d0f13", panel="#14171d", border="#262a33", text="#f3f3f1", old="#9097a3",
    dim="#5d6370", top="#ff5a5f", bottom="#4ea1ff", ok="#3ecf8e", busy="#f5a524", error="#ff4d4f",
    button="#1d212a", button_hover="#2a2f3a",
)
FONT = "Segoe UI" if sys.platform == "win32" else "Helvetica Neue" if sys.platform == "darwin" else "DejaVu Sans"

TS_PAD = "{}   "
TOP_TITLES = {"dialect": ("SCHWIIZERDÜTSCH", "as spoken"), "german": ("HOCHDEUTSCH", "Standard German")}
BOTTOM_TITLES = {"ru": ("РУССКИЙ", "перевод"), "de": ("HOCHDEUTSCH", "Standard German")}


class Pane:
    """One half of the window: a title and a read-only, auto-scrolling list of rows."""

    def __init__(self, tk, parent, accent: str, font_size: int, bold: bool):
        import tkinter.font  # noqa: F401  (makes tk.font available)

        self.tk = tk
        self.bold = bold
        self.frame = tk.Frame(parent, bg=C["panel"])
        head = tk.Frame(self.frame, bg=C["panel"])
        head.pack(fill="x", padx=16, pady=(10, 2))
        tk.Frame(head, bg=accent, width=4, height=16).pack(side="left", padx=(0, 8))
        self.title = tk.Label(head, fg=accent, bg=C["panel"], font=(FONT, 10, "bold"))
        self.title.pack(side="left")
        self.subtitle = tk.Label(head, fg=C["dim"], bg=C["panel"], font=(FONT, 9))
        self.subtitle.pack(side="left", padx=8)

        body = tk.Frame(self.frame, bg=C["panel"])
        body.pack(fill="both", expand=True)
        self.text = tk.Text(body, bg=C["panel"], fg=C["text"], bd=0, highlightthickness=0,
                            wrap="word", padx=16, pady=4, cursor="arrow", insertwidth=0,
                            selectbackground=C["border"], exportselection=False)
        bar = tk.Scrollbar(body, command=self.text.yview, width=10, bd=0, relief="flat",
                           troughcolor=C["panel"], bg=C["border"], activebackground=C["dim"])
        self.text.configure(yscrollcommand=bar.set, state="disabled")
        bar.pack(side="right", fill="y")
        self.text.pack(side="left", fill="both", expand=True)
        self.rows: set[int] = set()
        self.current = -1  # newest finished row, shown bright
        self.set_font(font_size)

    def set_titles(self, title: str, subtitle: str) -> None:
        self.title.config(text=title)
        self.subtitle.config(text=subtitle)

    def set_font(self, size: int) -> None:
        weight = "bold" if self.bold else "normal"
        t = self.text
        t.tag_configure("cur", foreground=C["text"], font=(FONT, size, weight))
        t.tag_configure("old", foreground=C["old"], font=(FONT, size, weight))
        t.tag_configure("pending", foreground=C["dim"], font=(FONT, size, weight))
        ts_font = (FONT, max(8, size * 3 // 5))
        t.tag_configure("ts", foreground=C["dim"], font=ts_font)
        indent = self.tk.font.Font(family=ts_font[0], size=ts_font[1]).measure(TS_PAD.format("00:00"))
        t.tag_configure("row", spacing1=4, spacing3=6, lmargin2=indent)  # wrapped lines align
        t.configure(font=(FONT, size))

    def clear(self) -> None:
        self.text.configure(state="normal")
        self.text.delete("1.0", "end")
        self.text.configure(state="disabled")
        self.rows.clear()
        self.current = -1

    def upsert(self, row_id: int, start: float, text: str, pending: bool) -> None:
        t = self.text
        follow = t.yview()[1] >= 0.999
        t.configure(state="normal")
        tag = f"r{row_id}"
        if pending:
            style = "pending"
        elif row_id >= self.current:  # newest finished row: earlier rows fade to grey
            t.tag_remove("cur", "1.0", "end")
            t.tag_add("old", "1.0", "end")
            self.current = row_id
            style = "cur"
        else:
            style = "old"
        display = text or "…"
        ranges = t.tag_ranges(tag)
        if ranges:
            t.delete(ranges[0], ranges[-1])
            t.insert(ranges[0], display, (tag, style, "row"))
        else:
            t.insert("end", TS_PAD.format(clock(start)), ("ts", "row"))
            t.insert("end", display, (tag, style, "row"))
            t.insert("end", "\n", ("row",))
            self.rows.add(row_id)
        t.configure(state="disabled")
        if follow:
            t.see("end")


class App:
    def __init__(self, settings: Settings, file: str | None = None, url: str | None = None,
                 settings_file: Path | None = None):
        import tkinter as tk

        self.tk = tk
        self.s = settings
        self.settings_file = settings_file
        self.events: queue.Queue = queue.Queue()
        self.options = Options(target=settings.target, dialect=settings.top == "dialect")
        self.hub = TranslatorHub(settings.translator, settings.claude_model or None,
                                 settings.offline_model, settings.dialect, log=self.status)
        self.book = LineBook(on_update=lambda line: self.events.put(("line", line)))
        self.lines: dict[int, Line] = {}
        self.transcriber = None
        self.dialect_transcriber = None
        self.pipeline: LivePipeline | None = None
        self.file_mode = bool(file or url)
        self._file_stop = threading.Event()
        self._dialect_lock = threading.Lock()
        self._fatal = False
        self._build()
        threading.Thread(target=self._startup, args=(file, url), daemon=True).start()
        self.root.after(80, self._poll)

    # ------------------------------------------------------------------- window
    def _build(self) -> None:
        tk, s = self.tk, self.s
        self.root = root = tk.Tk()
        root.title("swiss-ru-de")
        root.configure(bg=C["bg"])
        root.geometry(s.geometry or "920x640")
        root.minsize(420, 320)
        root.attributes("-topmost", s.always_on_top)
        root.protocol("WM_DELETE_WINDOW", self.close)

        bar = tk.Frame(root, bg=C["bg"])
        bar.pack(fill="x", padx=12, pady=8)
        self.dot = tk.Label(bar, text="●", fg=C["busy"], bg=C["bg"], font=(FONT, 12))
        self.dot.pack(side="left")
        self.status_label = tk.Label(bar, text="Starting …", fg=C["old"], bg=C["bg"], anchor="w",
                                     font=(FONT, 10))
        self.status_label.pack(side="left", fill="x", expand=True, padx=6)
        self.pause_button = None
        for label, cmd in (("Settings", self.open_settings), ("Save…", self.save_transcript),
                           ("Clear", self.clear), ("Pause", self.toggle_pause)):
            b = tk.Button(bar, text=label, command=cmd, bg=C["button"], fg=C["text"], bd=0,
                          relief="flat", padx=12, pady=4, font=(FONT, 10), cursor="hand2",
                          takefocus=0,
                          activebackground=C["button_hover"], activeforeground=C["text"])
            b.pack(side="right", padx=3)
            b.bind("<Enter>", lambda e, b=b: b.config(bg=C["button_hover"]))
            b.bind("<Leave>", lambda e, b=b: b.config(bg=C["button"]))
            if label == "Pause":
                self.pause_button = b

        split = tk.PanedWindow(root, orient="vertical", bg=C["border"], sashwidth=6, bd=0,
                               sashrelief="flat", opaqueresize=True)
        split.pack(fill="both", expand=True, padx=12, pady=(0, 12))
        self.top = Pane(tk, split, C["top"], s.font_size, bold=False)
        self.bottom = Pane(tk, split, C["bottom"], s.font_size, bold=True)
        split.add(self.top.frame, stretch="always", minsize=80)
        split.add(self.bottom.frame, stretch="always", minsize=80)
        root.after(60, lambda: split.sash_place(0, 0, max(100, split.winfo_height() // 2)))
        self._set_titles()

        root.bind("<Control-comma>", lambda e: self.open_settings())
        root.bind("<Control-s>", lambda e: self.save_transcript())
        root.bind("<Control-l>", lambda e: self.clear())
        root.bind("<space>", lambda e: self.toggle_pause())
        root.bind("<Control-plus>", lambda e: self._zoom(+2))
        root.bind("<Control-equal>", lambda e: self._zoom(+2))
        root.bind("<Control-minus>", lambda e: self._zoom(-2))

    def _set_titles(self) -> None:
        self.top.set_titles(*TOP_TITLES[self.s.top])
        self.bottom.set_titles(*BOTTOM_TITLES[self.s.target])

    def _zoom(self, delta: int) -> None:
        self.s.font_size = max(10, min(48, self.s.font_size + delta))
        self.top.set_font(self.s.font_size)
        self.bottom.set_font(self.s.font_size)

    def run(self) -> None:
        self.root.mainloop()

    def close(self) -> None:
        try:
            self.s.geometry = self.root.geometry()
            save_settings(self.s, self.settings_file)
        except Exception:
            pass
        try:
            if self.pipeline:
                self.pipeline.stop(wait=False)
        finally:
            self._file_stop.set()
            self.root.destroy()

    # ------------------------------------------------------------ thread-safe API
    def status(self, msg: str) -> None:
        print(f"» {msg}", file=sys.stderr, flush=True)
        self.events.put(("status", msg))

    def _poll(self) -> None:
        for _ in range(300):
            try:
                kind, item = self.events.get_nowait()
            except queue.Empty:
                break
            if kind == "line":
                self._render(item)
            elif kind == "status":
                self.status_label.config(text=item)
            elif kind == "fatal":
                self._fatal = True
                self.status_label.config(text=item.splitlines()[0])
                from tkinter import messagebox

                messagebox.showerror("swiss-ru-de", item, parent=self.root)
        running = self.pipeline is not None and not self.pipeline.stop_event.is_set()
        color = (C["error"] if self._fatal or (self.pipeline and self.pipeline.error)
                 else C["busy"] if self.options.paused or not (running or self.file_mode)
                 else C["ok"])
        self.dot.config(fg=color)
        self.root.after(80, self._poll)

    # ----------------------------------------------------------------- rendering
    def _top_text(self, line: Line) -> tuple[str, bool]:
        if self.s.top == "dialect":
            if line.dialect_pending:
                return "", True
            if line.dialect:
                return line.dialect, False
        return line.german, False  # Standard German (or dialect model not ready yet)

    def _bottom_text(self, line: Line) -> tuple[str, bool]:
        if self.s.target == "de":
            return line.german, False
        if line.translation_pending:
            return "", True
        return line.translation or f"({line.german})", False  # not translated / failed

    def _render(self, line: Line) -> None:
        self.lines[line.id] = line
        self.top.upsert(line.id, line.start, *self._top_text(line))
        self.bottom.upsert(line.id, line.start, *self._bottom_text(line))

    def _rerender(self) -> None:
        self.top.clear()
        self.bottom.clear()
        for line in sorted(self.lines.values(), key=lambda l: l.id):
            self._render(line)

    # ------------------------------------------------------------------- actions
    def toggle_pause(self) -> None:
        self.options.paused = not self.options.paused
        self.pause_button.config(text="Resume" if self.options.paused else "Pause")
        self.status_label.config(text="Paused - audio is ignored." if self.options.paused
                                 else "Listening …")

    def clear(self) -> None:
        self.lines.clear()
        self.top.clear()
        self.bottom.clear()

    def save_transcript(self) -> None:
        from tkinter import filedialog

        done = [l for l in sorted(self.lines.values(), key=lambda l: l.id) if l.done]
        if not done:
            self.status_label.config(text="Nothing to save yet.")
            return
        path = filedialog.asksaveasfilename(
            parent=self.root, defaultextension=".srt", initialfile="transcript.srt",
            filetypes=[("Subtitles", "*.srt"), ("Text", "*.txt")])
        if not path:
            return
        writer = TranscriptWriter(path, target=self.s.target)
        for line in done:
            writer(replace(line, dialect=line.dialect if self.s.top == "dialect" else None))
        writer.close()
        self.status_label.config(text=f"Saved {len(done)} lines to {path}")

    def open_settings(self) -> None:
        SettingsDialog(self)

    def apply_settings(self, new: Settings) -> None:
        old, self.s = self.s, new
        try:
            save_settings(new, self.settings_file)
        except OSError as e:
            self.status(f"Could not save settings: {e}")
        self.options.target = new.target
        self.options.dialect = new.top == "dialect"
        if (new.translator, new.dialect, new.claude_model) != (old.translator, old.dialect, old.claude_model):
            self.hub.configure(kind=new.translator, dialect=new.dialect,
                               claude_model=new.claude_model or None)
        if self.dialect_transcriber is not None:
            from .asr import dialect_prompt

            self.dialect_transcriber.prompt = dialect_prompt(new.dialect)
        if self.options.dialect and self.dialect_transcriber is None and self.transcriber:
            threading.Thread(target=self._load_dialect, daemon=True).start()
        self.root.attributes("-topmost", new.always_on_top)
        self.top.set_font(new.font_size)
        self.bottom.set_font(new.font_size)
        self._set_titles()
        self._rerender()
        if (new.source, new.device) != (old.source, old.device) and self.pipeline:
            threading.Thread(target=self._restart_capture, daemon=True).start()
        if (new.model, new.dialect_model, new.compute) != (old.model, old.dialect_model, old.compute):
            self.status("Speech model changes apply at the next start.")

    # --------------------------------------------------------------- background
    def _startup(self, file: str | None, url: str | None) -> None:
        try:
            from .asr import Transcriber

            self.status("Loading speech model … (the first start downloads about 1.6 GB)")
            self.transcriber = Transcriber(self.s.model, device=self.s.compute, beam_size=1,
                                           log=self.status)
        except Exception as e:
            self.events.put(("fatal", f"Could not load the speech model:\n{e}"))
            return
        if self.file_mode:
            if self.options.dialect:
                self._load_dialect()
            self._run_file(file, url)
            return
        self._start_capture()
        if self.options.dialect:
            self._load_dialect()

    def _load_dialect(self) -> None:
        with self._dialect_lock:
            if self.dialect_transcriber is not None:
                return
            try:
                from .asr import Transcriber, dialect_prompt

                self.status("Loading dialect model for the top line …")
                tr = Transcriber(self.s.dialect_model, device=self.s.compute, beam_size=1,
                                 log=self.status, prompt=dialect_prompt(self.s.dialect))
            except Exception as e:
                self.status(f"Dialect model not available ({e}); showing Standard German on top.")
                return
            self.dialect_transcriber = tr
            if self.pipeline:
                self.pipeline.dialect_transcriber = tr
            self.status("Ready - listening." if self.pipeline else "Dialect model ready.")
            if self.transcriber is not None and self.transcriber.device == "cpu":
                self.status("Running on the CPU: the dialect line is filled in when the CPU is "
                            "free. An NVIDIA graphics card makes it about 10x faster.")

    def _new_source(self):
        from .audio import SoundcardSource

        return SoundcardSource(loopback=self.s.source != "mic", device=self.s.device or None)

    def _start_capture(self) -> None:
        self.pipeline = LivePipeline(self._new_source(), self.transcriber, self.hub.get, self.book,
                                     self.status, options=self.options,
                                     dialect_transcriber=self.dialect_transcriber).start()

    def _restart_capture(self) -> None:
        old = self.pipeline
        if old:
            old.stop(wait=True)
        self._start_capture()

    def _run_file(self, file: str | None, url: str | None) -> None:
        import tempfile

        try:
            with tempfile.TemporaryDirectory(prefix="swiss-ru-de-") as tmp:
                path = file
                if url:
                    from .audio import download_audio

                    self.status("Downloading audio …")
                    p, title = download_audio(url, Path(tmp))
                    path = str(p)
                    self.status(f"Transcribing: {title}")
                run_file(self.transcriber, self.hub.get, path, self.book, self.status,
                         options=self.options, beam_size=5, stop=self._file_stop,
                         dialect_transcriber=self.dialect_transcriber if self.options.dialect else None)
            self.status("Finished.")
        except Exception as e:
            self.events.put(("fatal", f"Could not process the file:\n{e}"))


def _dark_ttk(root) -> None:
    """Dark look for the ttk widgets of the settings dialog."""
    from tkinter import ttk

    style = ttk.Style(root)
    if "clam" in style.theme_names():
        style.theme_use("clam")
    base = dict(background=C["bg"], foreground=C["text"], font=(FONT, 10))
    for w in ("TFrame", "TLabel", "TRadiobutton", "TCheckbutton"):
        style.configure(w, **base)
    for w in ("TRadiobutton", "TCheckbutton"):
        style.configure(w, indicatorbackground=C["button"], indicatorforeground=C["text"],
                        indicatorcolor=C["button"], focuscolor=C["bg"])
        style.map(w, background=[("active", C["bg"])],
                  indicatorcolor=[("selected", C["bottom"]), ("!selected", C["button"])])
    field = dict(fieldbackground=C["button"], background=C["button"], foreground=C["text"],
                 arrowcolor=C["text"], bordercolor=C["border"], lightcolor=C["border"],
                 darkcolor=C["border"], insertcolor=C["text"])
    for w in ("TCombobox", "TSpinbox", "TEntry"):
        style.configure(w, **field)
        style.map(w, fieldbackground=[("readonly", C["button"])], foreground=[("readonly", C["text"])],
                  selectbackground=[("readonly", C["button"])],
                  selectforeground=[("readonly", C["text"])])
    style.configure("TButton", background=C["button"], foreground=C["text"], bordercolor=C["border"],
                    lightcolor=C["button"], darkcolor=C["button"], focuscolor=C["button"],
                    padding=(14, 4), font=(FONT, 10))
    style.map("TButton", background=[("active", C["button_hover"])])
    style.configure("Accent.TButton", background=C["bottom"], foreground="#ffffff")
    style.map("Accent.TButton", background=[("active", "#3a8be6")])
    style.configure("Head.TLabel", foreground=C["old"], font=(FONT, 9, "bold"))
    style.configure("Note.TLabel", foreground=C["dim"], font=(FONT, 9))
    for opt, val in (("background", C["button"]), ("foreground", C["text"]),
                     ("selectBackground", C["bottom"]), ("selectForeground", "#ffffff")):
        root.option_add(f"*TCombobox*Listbox.{opt}", val)


class SettingsDialog:
    def __init__(self, app: App):
        import tkinter as tk
        from tkinter import ttk

        from .audio import device_names

        self.app = app
        s = app.s
        self.win = win = tk.Toplevel(app.root)
        win.title("Settings")
        win.transient(app.root)
        win.configure(bg=C["bg"], padx=18, pady=14)
        win.resizable(False, False)
        _dark_ttk(app.root)

        row = 0

        def head(text):
            nonlocal row
            ttk.Label(win, text=text, style="Head.TLabel").grid(row=row, column=0, columnspan=2,
                                                                sticky="w", pady=(10 if row else 0, 2))
            row += 1

        def field(label, widget, note=None):
            nonlocal row
            ttk.Label(win, text=label).grid(row=row, column=0, sticky="w", padx=(0, 12), pady=3)
            widget.grid(row=row, column=1, sticky="we", pady=2)
            row += 1
            if note:
                ttk.Label(win, text=note, style="Note.TLabel").grid(row=row, column=1, sticky="w")
                row += 1

        head("BOTTOM PANE")
        self.target = tk.StringVar(value=s.target)
        f = ttk.Frame(win)
        ttk.Radiobutton(f, text="Русский (Russian translation)", value="ru",
                        variable=self.target).pack(anchor="w")
        ttk.Radiobutton(f, text="Hochdeutsch (Standard German)", value="de",
                        variable=self.target).pack(anchor="w")
        field("Show", f)

        head("TOP PANE")
        self.top = tk.StringVar(value=s.top)
        f = ttk.Frame(win)
        ttk.Radiobutton(f, text="Swiss German as spoken (dialect)", value="dialect",
                        variable=self.top).pack(anchor="w")
        ttk.Radiobutton(f, text="Standard German", value="german", variable=self.top).pack(anchor="w")
        field("Show", f, "Uses a 2nd speech model; on a CPU it is filled in when there is time.")
        self.dialect_labels = {k: (f"{k} – {v}" if v else "auto – any dialect") for k, v in DIALECTS.items()}
        self.dialect = ttk.Combobox(win, state="readonly", width=48,
                                    values=list(self.dialect_labels.values()))
        self.dialect.set(self.dialect_labels.get(s.dialect, self.dialect_labels["auto"]))
        field("Dialect", self.dialect, "Optional: helps dialect spelling and translation.")

        head("TRANSLATION")
        self.translator = ttk.Combobox(win, state="readonly", width=48,
                                       values=["auto", "claude", "deepl", "offline"])
        self.translator.set(s.translator)
        field("Translator", self.translator,
              "auto = Claude if its key is set, else DeepL, else offline (lowest quality).")
        self.claude_key = tk.StringVar()
        self.deepl_key = tk.StringVar()
        field("Claude API key", ttk.Entry(win, textvariable=self.claude_key, show="•", width=50),
              self._key_note("anthropic", "console.anthropic.com - best translation"))
        field("DeepL API key", ttk.Entry(win, textvariable=self.deepl_key, show="•", width=50),
              self._key_note("deepl", "deepl.com/pro-api - free key available"))

        head("AUDIO")
        speakers, mics = device_names()
        self.sources = {"PC audio – default speaker": ("loopback", "")}
        self.sources.update({f"PC audio – {n}": ("loopback", n) for n in speakers})
        self.sources["Microphone – default"] = ("mic", "")
        self.sources.update({f"Microphone – {n}": ("mic", n) for n in mics})
        current = next((k for k, v in self.sources.items() if v == (s.source, s.device)), None)
        if current is None:
            current = f"{'PC audio' if s.source == 'loopback' else 'Microphone'} – {s.device}"
            self.sources[current] = (s.source, s.device)
        self.source = ttk.Combobox(win, state="readonly", width=48, values=list(self.sources))
        self.source.set(current)
        field("Listen to", self.source, "For Teams pick the speaker/headset Teams plays on.")

        head("DISPLAY")
        self.font_size = tk.IntVar(value=s.font_size)
        field("Font size", ttk.Spinbox(win, from_=10, to=48, textvariable=self.font_size, width=6))
        self.on_top = tk.BooleanVar(value=s.always_on_top)
        field("", ttk.Checkbutton(win, text="Always on top", variable=self.on_top))

        head("SPEECH MODEL (applies at next start)")
        self.model = ttk.Combobox(win, width=48, values=list(MODEL_PRESETS))
        self.model.set(s.model)
        field("Model", self.model)
        self.compute = ttk.Combobox(win, state="readonly", width=48, values=["auto", "cpu", "cuda"])
        self.compute.set(s.compute)
        field("Run on", self.compute)

        buttons = ttk.Frame(win)
        buttons.grid(row=row, column=0, columnspan=2, sticky="e", pady=(16, 0))
        ttk.Button(buttons, text="Cancel", command=win.destroy).pack(side="right", padx=4)
        ttk.Button(buttons, text="Save", command=self.save, style="Accent.TButton").pack(side="right")
        win.bind("<Escape>", lambda e: win.destroy())
        win.bind("<Return>", lambda e: self.save())
        win.update_idletasks()  # centre over the main window
        root = app.root
        x = root.winfo_rootx() + (root.winfo_width() - win.winfo_reqwidth()) // 2
        y = root.winfo_rooty() + max(0, (root.winfo_height() - win.winfo_reqheight()) // 2)
        win.geometry(f"+{max(0, x)}+{max(0, y)}")
        win.grab_set()

    @staticmethod
    def _key_note(name: str, where: str) -> str:
        from . import keys

        if os.environ.get(keys.ENV[name]):
            return f"Set by the {keys.ENV[name]} environment variable."
        if keys.saved_in_keychain(name):
            return "Saved. Type a new key to replace it, or a single - to remove it."
        return f"Not set. Get one at {where}."

    def save_keys(self) -> bool:
        """Store typed keys in the system keychain. True if anything changed."""
        from . import keys

        changed = False
        for name, var in (("anthropic", self.claude_key), ("deepl", self.deepl_key)):
            value = var.get().strip()
            if not value:
                continue
            if not keys.set_key(name, "" if value == "-" else value):
                self.app.status("Could not save the API key: no system keychain available.")
            changed = True
        return changed

    def values(self) -> Settings:
        s = self.app.s
        dialect = next(k for k, v in self.dialect_labels.items() if v == self.dialect.get())
        source, device = self.sources[self.source.get()]
        try:
            font_size = max(10, min(48, int(self.font_size.get())))
        except (ValueError, self.app.tk.TclError):
            font_size = s.font_size
        return replace(s, target=self.target.get(), top=self.top.get(), dialect=dialect,
                       translator=self.translator.get(), source=source, device=device,
                       font_size=font_size, always_on_top=bool(self.on_top.get()),
                       model=self.model.get().strip() or s.model, compute=self.compute.get())

    def save(self) -> None:
        if self.save_keys():
            self.app.hub.reset()  # recreate translators with the new keys
        new = self.values()
        self.win.destroy()
        self.app.apply_settings(new)


def run_app(file: str | None = None, url: str | None = None, settings_file: Path | None = None) -> int:
    try:
        import tkinter  # noqa: F401
    except ImportError:
        print("The window needs Tkinter. Linux: sudo apt install python3-tk; on Windows and "
              "macOS it comes with the python.org installer.", file=sys.stderr)
        return 1
    if sys.stderr is None or sys.stdout is None:  # started without a console (pythonw)
        log_dir = config_dir()
        log_dir.mkdir(parents=True, exist_ok=True)
        sys.stdout = sys.stderr = open(log_dir / "log.txt", "a", encoding="utf-8", buffering=1)
    App(load_settings(settings_file), file=file, url=url, settings_file=settings_file).run()
    return 0


def main() -> int:
    import argparse

    p = argparse.ArgumentParser(prog="swiss-ru-de-gui", description="Two-pane live subtitle window.")
    g = p.add_mutually_exclusive_group()
    g.add_argument("--file")
    g.add_argument("--url")
    p.add_argument("--settings", type=Path, help="settings file (default: user config folder)")
    a = p.parse_args()
    return run_app(a.file, a.url, a.settings)


if __name__ == "__main__":
    raise SystemExit(main())
