"""Ordnerauswahl für den Workspace: durchsuchen, bekannte Orte, zuletzt genutzte Ordner und der Systemdialog."""

import os
import platform
import string
import subprocess
import sys
from pathlib import Path
from typing import Callable

from . import sessions
from .config import blocked_workspace, normalize_path

IS_WINDOWS = platform.system() == "Windows"
HIDDEN = 0x2 | 0x4  # FILE_ATTRIBUTE_HIDDEN | FILE_ATTRIBUTE_SYSTEM

# Das App-Fenster hängt hier seinen Qt-Dialog ein. Ohne Fenster übernimmt tkinter in einem eigenen Prozess.
_native_dialog: Callable[[str, str], str | None] | None = None

TK_DIALOG = """
import ctypes, sys, tkinter
from tkinter import filedialog
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(1)
except Exception:
    pass
root = tkinter.Tk()
root.withdraw()
root.attributes("-topmost", True)
path = filedialog.askdirectory(parent=root, initialdir=sys.argv[1], title=sys.argv[2], mustexist=True)
sys.stdout.buffer.write((path or "").encode("utf-8"))
"""


def set_native_dialog(fn: Callable[[str, str], str | None] | None) -> None:
    global _native_dialog
    _native_dialog = fn


def listing(raw: str) -> dict:
    path = normalize_path(raw) if raw.strip() else Path.home()
    parent = str(path.parent) if path.parent != path else None
    if not path.is_dir():
        return {"path": str(path), "parent": parent, "error": "Ordner nicht gefunden"}
    dirs = []
    try:
        with os.scandir(path) as entries:
            for entry in entries:
                try:
                    if entry.name.startswith((".", "$")) or not entry.is_dir():
                        continue
                    if IS_WINDOWS and entry.stat(follow_symlinks=False).st_file_attributes & HIDDEN:
                        continue
                except OSError:
                    continue
                dirs.append({"name": entry.name, "path": entry.path})
    except OSError as e:
        return {"path": str(path), "parent": parent,
                "error": f"Kein Zugriff auf diesen Ordner ({e.strerror or e.__class__.__name__})"}
    dirs.sort(key=lambda d: d["name"].lower())
    return {"path": str(path), "parent": parent, "dirs": dirs[:2000], "blocked": blocked_workspace(path)}


def places() -> list[dict]:
    home = Path.home()
    found = [{"name": home.name or str(home), "path": str(home)}]
    for name, options in (("Desktop", ("Desktop", "OneDrive/Desktop")),
                          ("Dokumente", ("Documents", "OneDrive/Documents")),
                          ("Downloads", ("Downloads",))):
        path = next((home / o for o in options if (home / o).is_dir()), None)
        if path:
            found.append({"name": name, "path": str(path)})
    if IS_WINDOWS:
        import ctypes
        mask = ctypes.windll.kernel32.GetLogicalDrives()
        found += [{"name": f"{d}:", "path": f"{d}:\\"} for i, d in enumerate(string.ascii_uppercase) if mask >> i & 1]
    else:
        found.append({"name": "/", "path": "/"})
    return found


def recent(limit: int = 6) -> list[dict]:
    found, seen = [], set()
    for s in sessions.list_all():
        ws = s.get("workspace") or ""
        key = os.path.normcase(ws)
        if not ws or key in seen:
            continue
        seen.add(key)
        if Path(ws).is_dir() and not blocked_workspace(ws):
            found.append({"name": Path(ws).name or ws, "path": ws})
            if len(found) == limit:
                break
    return found


def pick(start: str, title: str = "Workspace wählen") -> str | None:
    """Öffnet den Ordnerdialog des Systems und wartet, bis er zu ist. None heißt abgebrochen."""
    start_dir = normalize_path(start) if start.strip() else Path.home()
    if not start_dir.is_dir():
        start_dir = Path.home()
    if _native_dialog:
        chosen = _native_dialog(str(start_dir), title)
    else:
        try:
            r = subprocess.run([sys.executable, "-c", TK_DIALOG, str(start_dir), title], capture_output=True,
                               timeout=1800, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except (OSError, subprocess.SubprocessError) as e:
            raise RuntimeError(f"Der Ordnerdialog ließ sich nicht öffnen ({e.__class__.__name__}).") from e
        if r.returncode:
            detail = (r.stderr.decode("utf-8", "replace").strip().splitlines() or ["unbekannter Fehler"])[-1]
            raise RuntimeError(f"Der Ordnerdialog ließ sich nicht öffnen: {detail}")
        chosen = r.stdout.decode("utf-8", "replace").strip()
    return str(Path(chosen)) if chosen else None
