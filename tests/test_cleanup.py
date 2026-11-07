"""Removing old installations: finds old copies, never touches this one."""

import os
import stat
from pathlib import Path

from swiss_ru_de import cleanup
from swiss_ru_de.settings import Settings


def make_copy(root: Path, version="1.0.0", venv_bytes=1000, extra=()) -> Path:
    (root / "swiss_ru_de").mkdir(parents=True)
    (root / "swiss_ru_de" / "__init__.py").write_text(f'__version__ = "{version}"\n')
    (root / "pyproject.toml").write_text('[project]\nname = "swiss-ru-de"\n')
    (root / "README.md").write_text("readme")
    if venv_bytes:
        (root / ".venv" / "Scripts").mkdir(parents=True)
        (root / ".venv" / "Scripts" / "python.exe").write_bytes(b"x" * venv_bytes)
    for name in extra:
        (root / name).write_text("mine")
    return root


def test_finds_old_copies_but_not_this_one(tmp_path):
    current = make_copy(tmp_path / "Desktop" / "swiss-ru-de-1.1" / "swiss-ru-de", "1.1.0")
    old = make_copy(tmp_path / "Downloads" / "swiss-ru-de-main", "1.0.0")
    deep = make_copy(tmp_path / "Downloads" / "a" / "b" / "swiss-ru-de")
    other = tmp_path / "Downloads" / "other-project"
    other.mkdir()
    (other / "pyproject.toml").write_text('[project]\nname = "something-else"\n')
    hidden = make_copy(tmp_path / "Downloads" / ".hidden" / "swiss-ru-de")
    found = cleanup.find_copies([(tmp_path, 5)], current)
    assert found == sorted([old, deep], key=lambda p: str(p).lower())
    assert hidden not in found and current not in found
    assert cleanup.find_copies([(tmp_path, 2)], current) == [old]  # depth limit


def test_old_copy_items_and_removal(tmp_path):
    current = make_copy(tmp_path / "new", "1.1.0")
    old = make_copy(tmp_path / "old", "1.0.0", venv_bytes=5_000_000)
    (old / ".git").mkdir()
    ro = old / ".git" / "pack"
    ro.write_text("read-only")
    os.chmod(ro, stat.S_IREAD)  # git objects are read-only on Windows
    items = cleanup.copy_items([old], current)
    assert [i.label.split(" of ")[0].split(" ")[0] for i in items] == ["Python", "Folder"]
    venv, folder = items
    assert venv.size == 5_000_000 and venv.default and folder.default
    assert folder.size < 1_000_000  # the .venv is not counted twice
    assert venv.remove() and not (old / ".venv").exists()
    assert folder.remove() and not old.exists()
    assert (current / ".venv").exists() and (current / "README.md").exists()


def test_user_files_and_newer_copies_are_kept_by_default(tmp_path):
    current = make_copy(tmp_path / "new", "1.1.0")
    with_notes = make_copy(tmp_path / "old", "1.0.0", extra=["transcript.txt"])
    newer = make_copy(tmp_path / "newer", "1.2.0")
    items = {i.label: i for i in cleanup.copy_items([with_notes, newer], current)}
    notes_folder = next(i for l, i in items.items() if l.startswith(f"Folder {with_notes}"))
    assert not notes_folder.default and "transcript.txt" in notes_folder.note
    assert next(i for l, i in items.items() if l.startswith(f"Python environment of {with_notes}")).default
    newer_items = [i for l, i in items.items() if str(newer) in l]
    assert all(not i.default for i in newer_items) and "NEWER" in newer_items[0].label


def test_new_version_unpacked_inside_the_old_folder(tmp_path):
    old = make_copy(tmp_path / "swiss-ru-de", "1.0.0")
    current = make_copy(old / "swiss-ru-de", "1.1.0")  # "Extract all" into the old folder
    assert cleanup.find_copies([(tmp_path, 3)], current) == [old]
    items = cleanup.copy_items([old], current)
    assert len(items) == 1 and items[0].label.startswith("Python environment")  # never the folder
    assert "inside" in items[0].note
    items[0].remove()
    assert current.exists() and (current / ".venv").exists() and not (old / ".venv").exists()


def test_unused_speech_models(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("APPDATA", str(tmp_path / "config"))
    cache = tmp_path / "hub"
    for repo in ("jayr23/whisper-large-v3-turbo-swiss-german-ct2",  # in use (swiss-turbo)
                 "mobiuslabsgmbh/faster-whisper-large-v3-turbo",  # dialect line / fallback
                 "facebook/nllb-200-distilled-600M",  # offline translator
                 "gcoli/whisper-large-v3-swiss-german-mit",  # swiss-large, not used
                 "Systran/faster-whisper-medium",  # not used
                 "someone/unrelated-model"):  # not ours: never touched
        d = cache / ("models--" + repo.replace("/", "--")) / "blobs"
        d.mkdir(parents=True)
        (d / "x").write_bytes(b"m" * 100)
    converted = cleanup.config_dir() / "models"
    (converted / "facebook_nllb-200-distilled-600M-ct2-int8").mkdir(parents=True)
    (converted / "Helsinki-NLP_opus-mt-de-ru-ct2-int8").mkdir(parents=True)
    items = cleanup.model_items(Settings(), cache)
    labels = [i.label for i in items]
    assert [l.split()[0] for l in labels] == ["gcoli/whisper-large-v3-swiss-german-mit",
                                              "Systran/faster-whisper-medium",
                                              "converted"]
    assert "Helsinki-NLP_opus-mt-de-ru" in labels[2]
    for i in items:
        assert i.remove()
    left = sorted((p.name for p in cache.iterdir()), key=str.lower)
    assert left == ["models--facebook--nllb-200-distilled-600M",
                    "models--jayr23--whisper-large-v3-turbo-swiss-german-ct2",
                    "models--mobiuslabsgmbh--faster-whisper-large-v3-turbo",
                    "models--someone--unrelated-model"]
    s = Settings(model="swiss-large")  # the user switched models: the other one is unused
    assert any("jayr23" in i.label for i in cleanup.model_items(s, cache))


OLLAMA_LIST = """NAME                  ID              SIZE      MODIFIED
gemma3:12b            f4031aab637d    8.1 GB    2 days ago
gemma3:4b             a2af6cc3eb7f    3.3 GB    1 hour ago
llama3.2:latest       a80c4f17acd5    2.0 GB    3 weeks ago
"""


def test_ollama_models_not_used_by_the_app():
    assert cleanup.parse_ollama_list(OLLAMA_LIST) == [
        ("gemma3:12b", 8_100_000_000), ("gemma3:4b", 3_300_000_000), ("llama3.2:latest", 2_000_000_000)]
    items = cleanup.ollama_items(Settings(local_model="gemma3:4b"), OLLAMA_LIST, exe="ollama")
    assert [i.label for i in items] == ["gemma3:12b"]  # the user's own llama3.2 stays
    assert "uses gemma3:4b" in items[0].note
    # no model chosen: the app uses the first installed of its list (gemma3:4b)
    assert [i.label for i in cleanup.ollama_items(Settings(), OLLAMA_LIST, exe="ollama")] == ["gemma3:12b"]
    assert cleanup.ollama_items(Settings(local_model="gemma3:12b"), OLLAMA_LIST, exe="ollama")[0].label == "gemma3:4b"


def test_old_shortcuts(tmp_path):
    current, old = tmp_path / "new", tmp_path / "old"
    for d in (current, old):
        d.mkdir()
    (current / "app.exe").write_text("")
    (old / "start-windows.bat").write_text("")
    ours = {"path": "Swiss RU-DE.lnk", "target": str(current / "app.exe"), "args": "", "dir": str(current)}
    to_old = {"path": "Swiss RU-DE.lnk", "target": str(old / "start-windows.bat"), "args": "", "dir": ""}
    via_cmd = {"path": "x.lnk", "target": "C:/Windows/cmd.exe", "args": f'/c "{old}/start-windows.bat"', "dir": ""}
    dangling = {"path": "swiss-ru-de.lnk", "target": str(tmp_path / "gone" / "swiss-ru-de-gui.exe"), "args": "", "dir": ""}
    unrelated = {"path": "Word.lnk", "target": str(tmp_path / "gone.exe"), "args": "", "dir": ""}
    similar = {"path": "y.lnk", "target": "C:/Windows/cmd.exe", "args": f"/c {old}er/run.bat", "dir": ""}
    assert not cleanup.is_old_shortcut(ours, [old], current)
    assert cleanup.is_old_shortcut(to_old, [old], current)
    assert cleanup.is_old_shortcut(via_cmd, [old], current)
    assert cleanup.is_old_shortcut(dangling, [old], current)
    assert not cleanup.is_old_shortcut(unrelated, [old], current)
    assert not cleanup.is_old_shortcut(similar, [old], current)  # "...older" is another folder


def test_run_asks_and_list_only_changes_nothing():
    removed, log = [], []

    def item(name, default=True):
        return cleanup.Item("Group", name, 2_000_000_000, lambda: removed.append(name) or True, default)

    items = [item("a"), item("b", default=False), item("c")]
    assert cleanup.run(items, ask=lambda q, d: True, list_only=True, log=log.append) == 0
    assert removed == [] and "Nothing was removed" in log[-1]
    freed = cleanup.run(items, ask=lambda q, d: d, log=log.append)  # suggested answers
    assert removed == ["a", "c"] and freed == 4_000_000_000
    assert "Freed 4.0 GB" in log[-1]
    cleanup.run([], log=log.append)
    assert "Nothing to clean up" in log[-1]


def test_collect_finds_everything_and_keeps_this_installation(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("APPDATA", str(tmp_path / "config"))
    monkeypatch.setenv("HF_HUB_CACHE", str(tmp_path / "hub"))
    monkeypatch.setattr(cleanup, "system_python_items", lambda copies, current: [])
    monkeypatch.setattr(cleanup, "cache_items", lambda: [])
    monkeypatch.setattr(cleanup, "ollama_exe", lambda: None)
    current = make_copy(tmp_path / "Downloads" / "swiss-ru-de-1.1.0" / "swiss-ru-de", "1.1.0")
    old = make_copy(tmp_path / "Desktop" / "swiss-ru-de", "1.0.0")
    items = cleanup.collect(current, roots=[(tmp_path, 4)], settings=Settings(), log=lambda m: None)
    cleanup.run(items, ask=lambda q, d: d, log=lambda m: None)
    assert not old.exists() and current.exists() and (current / ".venv").exists()


def test_empty_extract_folder_around_an_old_copy_goes_too(tmp_path):
    old = make_copy(tmp_path / "swiss-ru-de-install-pack" / "swiss-ru-de")
    assert cleanup.remove_copy(old) and not (tmp_path / "swiss-ru-de-install-pack").exists()
    kept = make_copy(tmp_path / "Projects" / "swiss-ru-de")  # not a wrapper of ours
    assert cleanup.remove_copy(kept) and (tmp_path / "Projects").exists()
    busy = make_copy(tmp_path / "swiss-ru-de-x" / "swiss-ru-de")
    (tmp_path / "swiss-ru-de-x" / "notes.txt").write_text("mine")
    assert cleanup.remove_copy(busy) and (tmp_path / "swiss-ru-de-x" / "notes.txt").exists()
