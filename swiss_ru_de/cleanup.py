"""Remove old swiss-ru-de installations and what they left behind.

* other copies of the app folder (from older archives), above all their Python
  environments (``.venv``, 1-4 GB each);
* shortcuts that point to them;
* swiss-ru-de installed into a system Python (older manual installs);
* speech and AI models that the app no longer uses, and download caches.

This installation (the folder this file is in) is never touched. Every deletion is asked
first; ``--list`` only shows what would be removed, ``--yes`` takes the suggested answer
for every question.

    python -m swiss_ru_de.cleanup [--list] [--yes]
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import stat
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

from .config import DEFAULT_OFFLINE_MODEL, FALLBACK_MODEL, MODEL_PRESETS
from .settings import Settings, config_dir, load_settings

APP_ROOT = Path(__file__).resolve().parent.parent  # this installation: always kept

# Not searched for old copies (system folders, environments, caches).
SKIP_DIRS = {"appdata", "windows", "program files", "program files (x86)", "programdata",
             "users", "recovery", "perflogs", "system volume information", "msocache",
             "node_modules", "site-packages", "venv", "__pycache__", "hostedtoolcache",
             "library", "applications"}
_NAME = re.compile(r'^\s*name\s*=\s*"swiss-ru-de"', re.M)
_VERSION = re.compile(r'__version__\s*=\s*"([^"]+)"')
_NOT_USER_FILES = {".venv", ".git", "__pycache__", ".pytest_cache", "build", "dist"}

# faster-whisper short names -> Hugging Face repos (as in faster_whisper.utils._MODELS)
WHISPER_REPOS = {
    "large-v3-turbo": "mobiuslabsgmbh/faster-whisper-large-v3-turbo",
    "turbo": "mobiuslabsgmbh/faster-whisper-large-v3-turbo",
    "large-v3": "Systran/faster-whisper-large-v3",
    "large": "Systran/faster-whisper-large-v3",
    "large-v2": "Systran/faster-whisper-large-v2",
    "medium": "Systran/faster-whisper-medium",
    "small": "Systran/faster-whisper-small",
    "base": "Systran/faster-whisper-base",
    "tiny": "Systran/faster-whisper-tiny",
}
# Offline translation models the app may have downloaded.
OFFLINE_REPOS = {DEFAULT_OFFLINE_MODEL, "facebook/nllb-200-distilled-1.3B", "facebook/nllb-200-1.3B",
                 "Helsinki-NLP/opus-mt-de-ru"}


@dataclass
class Item:
    """One thing that can be removed."""

    group: str
    label: str
    size: int
    remove: Callable[[], bool]
    default: bool = True
    note: str = ""


# ----------------------------------------------------------------------- helpers
def human(n: int) -> str:
    return f"{n / 1e9:.1f} GB" if n >= 1e9 else f"{max(n, 0) / 1e6:.0f} MB"


def _key(path) -> str:
    return os.path.normcase(os.path.realpath(str(path)))


def inside(child, parent) -> bool:
    return _key(child).startswith(_key(parent).rstrip("\\/") + os.sep)


def folder_size(path: Path) -> int:
    total = 0
    for dirpath, _dirs, files in os.walk(path):
        for f in files:
            try:
                total += os.lstat(os.path.join(dirpath, f)).st_size
            except OSError:
                pass
    return total


def remove_tree(path: Path) -> bool:
    """Delete a folder, also read-only files (git) and very long paths (Windows)."""
    if not os.path.lexists(path):
        return True
    target = os.path.abspath(str(path))
    if sys.platform == "win32" and not target.startswith("\\\\"):
        target = "\\\\?\\" + target

    def retry(func, p, _exc):
        try:
            os.chmod(p, stat.S_IWRITE)
            func(p)
        except OSError:
            pass

    if sys.version_info >= (3, 12):
        shutil.rmtree(target, onexc=retry)
    else:
        shutil.rmtree(target, onerror=retry)
    return not os.path.lexists(path)


def _run(cmd: list[str], timeout: float = 120) -> str:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                           timeout=timeout, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.SubprocessError):
        return ""
    return r.stdout if r.returncode == 0 else ""


def _powershell_json(script: str) -> list[dict]:
    out = _run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command",
                "[Console]::OutputEncoding = [Text.Encoding]::UTF8; " + script])
    try:
        data = json.loads(out) if out.strip() else []
    except ValueError:
        return []
    return [data] if isinstance(data, dict) else [d for d in data if isinstance(d, dict)]


def _version_tuple(v: str) -> tuple:
    return tuple(int(p) for p in re.findall(r"\d+", v)[:3]) or (0,)


# ------------------------------------------------------------------- old copies
def is_copy(path: Path) -> bool:
    """A swiss-ru-de folder: pyproject.toml of this project and the swiss_ru_de package."""
    try:
        return (path / "swiss_ru_de" / "__init__.py").is_file() and \
            bool(_NAME.search((path / "pyproject.toml").read_text(encoding="utf-8", errors="replace")))
    except OSError:
        return False


def copy_version(path: Path) -> str:
    try:
        m = _VERSION.search((path / "swiss_ru_de" / "__init__.py").read_text(encoding="utf-8"))
    except OSError:
        m = None
    return m.group(1) if m else "0"


def _walk_dirs(root: Path, depth: int) -> Iterable[Path]:
    stack = [(root, 0)]
    while stack:
        path, d = stack.pop()
        yield path
        if d >= depth:
            continue
        try:
            entries = list(os.scandir(path))
        except OSError:
            continue
        for e in entries:
            name = e.name.lower()
            if name.startswith((".", "$")) or name in SKIP_DIRS or name.endswith(".egg-info"):
                continue
            try:
                if not e.is_dir(follow_symlinks=False) or getattr(e, "is_junction", lambda: False)():
                    continue
            except OSError:
                continue
            stack.append((Path(e.path), d + 1))


def default_roots(current: Path = APP_ROOT) -> list[tuple[Path, int]]:
    """Where old copies are usually unpacked: next to this one, Desktop, Downloads,
    Documents, OneDrive, and the top folders of every local drive."""
    home = Path.home()
    roots = [(current.parent, 2), (home, 2)]
    roots += [(home / n, 4) for n in ("Desktop", "Downloads", "Documents")]
    roots += [(p, 4) for p in home.glob("OneDrive*")]
    if sys.platform == "win32":
        roots += [(Path(d), 3) for d in _fixed_drives()]
    return [(p, d) for p, d in roots if p.is_dir()]


def _fixed_drives() -> list[str]:
    import ctypes
    import string

    k = ctypes.windll.kernel32
    mask = k.GetLogicalDrives()
    return [f"{c}:\\" for i, c in enumerate(string.ascii_uppercase)
            if mask >> i & 1 and k.GetDriveTypeW(f"{c}:\\") == 3]  # 3 = fixed disk


def find_copies(roots: Iterable[tuple[Path, int]], current: Path = APP_ROOT) -> list[Path]:
    found, seen = [], {_key(current)}
    for root, depth in roots:
        for path in _walk_dirs(root, depth):
            k = _key(path)
            if k not in seen:
                seen.add(k)
                if is_copy(path):
                    found.append(path)
    return sorted(found, key=lambda p: str(p).lower())


def _app_files(root: Path) -> set[str]:
    files = set()
    for dirpath, dirs, names in os.walk(root):
        dirs[:] = [d for d in dirs if d not in _NOT_USER_FILES and not d.endswith(".egg-info")]
        rel = os.path.relpath(dirpath, root)
        files.update(os.path.normcase(os.path.normpath(os.path.join(rel, n))) for n in names)
    return files


def user_files(copy: Path, known: set[str]) -> list[str]:
    """Files in an old copy that are not part of the app (e.g. saved transcripts)."""
    found = []
    for dirpath, dirs, names in os.walk(copy):
        dirs[:] = [d for d in dirs if d not in _NOT_USER_FILES and not d.endswith(".egg-info")
                   and not is_copy(Path(dirpath, d))]
        rel = os.path.relpath(dirpath, copy)
        for n in names:
            r = os.path.normpath(os.path.join(rel, n))
            if os.path.normcase(r) not in known and not n.endswith((".pyc", ".tmp")):
                found.append(r)
    return sorted(found)


def copy_items(copies: list[Path], current: Path = APP_ROOT) -> list[Item]:
    items, known, mine = [], _app_files(current), _version_tuple(copy_version(current))
    for c in copies:
        version = copy_version(c)
        newer = _version_tuple(version) > mine
        where = f"{c}  (version {version}{', NEWER than this one' if newer else ''})"
        venv = c / ".venv"
        venv_size = folder_size(venv) if venv.is_dir() else 0
        nested = inside(current, c)  # this installation was unpacked inside the old folder
        if venv.is_dir():
            items.append(Item("Old copies of swiss-ru-de", f"Python environment of {where}",
                              venv_size, lambda v=venv: remove_tree(v), default=not newer,
                              note="this installation is inside that folder, so only its old "
                                   "Python environment is removed" if nested else ""))
        if nested:
            continue
        extra = user_files(c, known)
        note = ""
        if extra:
            note = (f"contains {len(extra)} file(s) that are not part of the app, e.g. "
                    + ", ".join(extra[:3]))
        items.append(Item("Old copies of swiss-ru-de", f"Folder {where}",
                          max(0, folder_size(c) - venv_size),  # .venv: counted above
                          lambda c=c: remove_copy(c), default=not (newer or extra), note=note))
    return items


def remove_copy(copy: Path) -> bool:
    """Delete an old copy, and the folder "Extract all" put around it if that is now empty
    (swiss-ru-de-install-pack\\swiss-ru-de -> swiss-ru-de-install-pack)."""
    if not remove_tree(copy):
        return False
    wrapper = copy.parent
    name = wrapper.name.lower()
    if ("swiss-ru-de" in name or "swiss_ru_de" in name) and wrapper != Path.home():
        try:
            wrapper.rmdir()  # only if empty
        except OSError:
            pass
    return True


def process_items(copies: list[Path]) -> list[Item]:
    """swiss-ru-de started from an old copy must be closed before it can be deleted."""
    if sys.platform != "win32" or not copies:
        return []
    procs = _powershell_json("Get-CimInstance Win32_Process | Where-Object ExecutablePath | "
                             "Select-Object ProcessId, ExecutablePath | ConvertTo-Json -Compress")
    items = []
    for p in procs:
        exe = str(p.get("ExecutablePath") or "")
        if any(inside(exe, c) for c in copies):
            pid = str(p.get("ProcessId"))
            items.append(Item("Running from an old copy (must be closed first)",
                              f"Close {exe} (process {pid})", 0,
                              lambda pid=pid: _run(["taskkill", "/PID", pid, "/T", "/F"]) != ""))
    return items


def shortcut_items(copies: list[Path], current: Path = APP_ROOT) -> list[Item]:
    """Shortcuts on the desktop / in the Start menu to old copies or to nothing."""
    if sys.platform != "win32":
        return []
    links = _powershell_json(r"""
$s = New-Object -ComObject WScript.Shell
$dirs = 'Desktop','CommonDesktopDirectory','Programs','CommonPrograms','Startup' |
    ForEach-Object { [Environment]::GetFolderPath($_) } | Where-Object { $_ -and (Test-Path $_) }
@(foreach ($d in $dirs) {
  Get-ChildItem -LiteralPath $d -Filter *.lnk -Recurse -ErrorAction SilentlyContinue | ForEach-Object {
    $l = $s.CreateShortcut($_.FullName)
    [pscustomobject]@{ path = $_.FullName; target = $l.TargetPath; args = $l.Arguments; dir = $l.WorkingDirectory }
  }
}) | ConvertTo-Json -Compress""")
    items = []
    for link in links:
        if is_old_shortcut(link, copies, current):
            path = Path(link["path"])
            items.append(Item("Shortcuts to old copies", f"{path}  ->  {link.get('target')}", 0,
                              lambda p=path: (p.unlink(missing_ok=True), True)[1]))
    return items


def _mentions(text: str, folder: Path) -> bool:
    """Does text (shortcut arguments, working folder) name this folder or a file in it?"""
    pattern = re.escape(str(folder).rstrip("\\/")) + r'(?:[\\/"\s]|$)'
    return bool(re.search(pattern, text, re.I))


def is_old_shortcut(link: dict, copies: list[Path], current: Path = APP_ROOT) -> bool:
    target, rest = str(link.get("target") or ""), f"{link.get('args') or ''} {link.get('dir') or ''}"
    if target and inside(target, current) or _mentions(rest, current):
        return False
    if any(target and inside(target, c) or _mentions(rest, c) for c in copies):
        return True
    text = (Path(str(link.get("path", ""))).name + " " + target).lower()
    ours = "swiss-ru-de" in text or "swiss_ru_de" in text or "swiss ru-de" in text
    return ours and bool(target) and not os.path.exists(target)  # points to a deleted copy


# --------------------------------------------------------------- system Python
def system_python_items(copies: list[Path], current: Path = APP_ROOT) -> list[Item]:
    """swiss-ru-de installed with pip into a system Python (not into a .venv)."""
    pythons = set()
    if sys.platform == "win32":
        for line in _run(["py", "-0p"], timeout=20).splitlines():
            m = re.search(r"([A-Za-z]:\\.*?pythonw?\.exe)\s*$", line.strip(), re.I)
            if m:
                pythons.add(m.group(1))
    for name in ("python", "python3"):
        exe = shutil.which(name)
        if exe and "windowsapps" not in exe.lower():
            pythons.add(exe)
    items, seen = [], set()
    for exe in sorted(pythons):
        real = _key(exe)
        if real in seen or inside(exe, current) or any(inside(exe, c) for c in copies) \
                or ".venv" in real or os.sep + "venv" in real:
            continue
        seen.add(real)
        info = _run([exe, "-m", "pip", "show", "swiss-ru-de"], timeout=60)
        if "Name: swiss-ru-de" not in info:
            continue
        items.append(Item("Installed into a system Python",
                          f"swiss-ru-de package in {exe} (its libraries, e.g. torch, stay)", 0,
                          lambda e=exe: bool(_run([e, "-m", "pip", "uninstall", "-y", "swiss-ru-de"]))))
    return items


# ------------------------------------------------------------------------ models
def hub_cache() -> Path:
    env = os.environ
    for name in ("HF_HUB_CACHE", "HUGGINGFACE_HUB_CACHE"):
        if env.get(name):
            return Path(env[name])
    if env.get("HF_HOME"):
        return Path(env["HF_HOME"]) / "hub"
    return Path(env.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "huggingface" / "hub"


def _repo(name: str) -> str:
    name = MODEL_PRESETS.get(name, name)
    return WHISPER_REPOS.get(name, name)


def speech_models_in_use(s: Settings) -> set[str]:
    return {_repo(s.model), _repo(s.dialect_model), _repo(FALLBACK_MODEL), s.offline_model}


def model_items(s: Settings, cache: Path | None = None) -> list[Item]:
    """Speech / offline translation models of this app that the settings no longer use."""
    cache = cache or hub_cache()
    ours = {v for v in MODEL_PRESETS.values() if "/" in v} | set(WHISPER_REPOS.values()) | OFFLINE_REPOS
    used = speech_models_in_use(s)
    items = []
    if cache.is_dir():
        for d in sorted(cache.glob("models--*"), key=lambda p: p.name.lower()):
            repo = d.name[len("models--"):].replace("--", "/", 1)
            if repo in ours and repo not in used:
                items.append(Item("Speech and translation models not used any more",
                                  f"{repo}  ({d})", folder_size(d), lambda d=d: remove_tree(d)))
    converted = config_dir() / "models"
    keep = re.sub(r"[^\w.-]", "_", s.offline_model) + "-ct2-int8"
    if converted.is_dir():
        for d in sorted(converted.iterdir(), key=lambda p: p.name.lower()):
            if d.is_dir() and d.name != keep:
                items.append(Item("Speech and translation models not used any more",
                                  f"converted model {d.name}", folder_size(d), lambda d=d: remove_tree(d)))
    return items


def ollama_exe() -> str | None:
    exe = shutil.which("ollama")
    local = Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Ollama" / "ollama.exe"
    return exe or (str(local) if os.environ.get("LOCALAPPDATA") and local.is_file() else None)


def parse_ollama_list(text: str) -> list[tuple[str, int]]:
    """``ollama list`` -> [(name, size in bytes)]."""
    units = {"B": 1, "KB": 1e3, "MB": 1e6, "GB": 1e9, "TB": 1e12}
    models = []
    for line in text.splitlines()[1:]:
        m = re.match(r"(\S+)\s+\S+\s+([\d.]+)\s*([KMGT]?B)\b", line.strip())
        if m:
            models.append((m.group(1), int(float(m.group(2)) * units[m.group(3)])))
    return models


def local_model_in_use(s: Settings, installed: list[str]) -> str | None:
    from .translate import PROVIDERS

    if s.local_model:
        return s.local_model
    return next((n for n in PROVIDERS["local"]["models"] if n in installed), None)


def ollama_items(s: Settings, listing: str | None = None, exe: str | None = None) -> list[Item]:
    from .translate import PROVIDERS

    exe = exe or ollama_exe()
    if listing is None:
        if not exe:
            return []
        listing = _run([exe, "list"], timeout=30)
    installed = parse_ollama_list(listing)
    names = [n for n, _ in installed]
    used = local_model_in_use(s, names)
    items = []
    for name, size in installed:
        if name in PROVIDERS["local"]["models"] and name != used:
            items.append(Item("Local AI models (Ollama) not used by swiss-ru-de", name, size,
                              lambda n=name: bool(_run([exe or "ollama", "rm", n], timeout=120)),
                              note=f"swiss-ru-de uses {used}" if used else ""))
    return items


def cache_items() -> list[Item]:
    items = []
    out = _run([sys.executable, "-m", "pip", "cache", "dir"], timeout=60).strip()
    if out and Path(out).is_dir():
        size = folder_size(Path(out))
        if size > 50e6:
            items.append(Item("Download caches", f"pip download cache ({out}); refilled when needed",
                              size, lambda: bool(_run([sys.executable, "-m", "pip", "cache", "purge"]))
                              or not Path(out).exists()))
    setup = Path(os.environ.get("TEMP", "/nonexistent")) / "OllamaSetup.exe"
    if setup.is_file():
        items.append(Item("Download caches", f"Ollama installer {setup}", setup.stat().st_size,
                          lambda: (setup.unlink(missing_ok=True), True)[1]))
    return items


# ---------------------------------------------------------------------------- run
def collect(current: Path = APP_ROOT, roots=None, settings: Settings | None = None,
            log=print) -> list[Item]:
    s = settings or load_settings()
    log("Looking for old copies of swiss-ru-de (Desktop, Downloads, Documents, drives) ...")
    copies = find_copies(roots if roots is not None else default_roots(current), current)
    items = process_items(copies) + copy_items(copies, current) + shortcut_items(copies, current)
    log("Looking for old installs in system Python and for unused models ...")
    items += system_python_items(copies, current) + model_items(s) + ollama_items(s) + cache_items()
    return items


def ask_console(question: str, default: bool) -> bool:
    try:
        answer = input(f"{question} [{'Y/n' if default else 'y/N'}] ").strip().lower()
    except EOFError:
        return default
    return default if not answer else answer[0] in "yjд"


def run(items: list[Item], ask: Callable[[str, bool], bool] = ask_console, list_only: bool = False,
        log=print) -> int:
    """Ask for every item, remove the chosen ones. Returns the bytes freed."""
    if not items:
        log("Nothing to clean up: no old copies, shortcuts or unused models found.")
        return 0
    total = sum(i.size for i in items)
    log(f"\nFound {len(items)} item(s), {human(total)} in all.")
    freed, group = 0, None
    for item in items:
        if item.group != group:
            group = item.group
            log(f"\n== {group}")
        size = f"  [{human(item.size)}]" if item.size else ""
        log(f"- {item.label}{size}")
        if item.note:
            log(f"  Note: {item.note}")
        if list_only:
            continue
        if not ask("  Remove?", item.default):
            continue
        try:
            ok = item.remove()
        except Exception as e:  # keep going with the rest
            ok = False
            log(f"  Error: {e}")
        if ok:
            freed += item.size
            log("  Removed.")
        else:
            log("  Could not remove everything (in use? close swiss-ru-de and try again).")
    if list_only:
        log("\nNothing was removed (--list).")
    else:
        log(f"\nDone. Freed {human(freed)}.")
    return freed


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m swiss_ru_de.cleanup", description=__doc__.split("\n\n")[0])
    p.add_argument("--list", action="store_true", help="only show what would be removed")
    p.add_argument("--yes", action="store_true", help="take the suggested answer for every question")
    args = p.parse_args(argv)
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")
    print(f"swiss-ru-de cleanup. This installation stays: {APP_ROOT}\n")
    items = collect()
    ask = (lambda q, default: print(f"{q} {'yes' if default else 'no'}") or default) if args.yes else ask_console
    run(items, ask=ask, list_only=args.list)
    return 0


if __name__ == "__main__":
    sys.exit(main())
