"""Rückgängig: Coder sichert jede Datei, bevor eine Aufgabe sie zum ersten Mal ändert.

Eine Sicherung gehört zu einer Aufgabe – einer Nachricht samt Nachbesserungen und Sub-Agents – und liegt unter
~/.coder/checkpoints/<chat>/<aufgabe>/. Zurückgenommen wird immer die jüngste Aufgabe zuerst, damit ein Zurücksetzen
keine spätere Änderung überschreibt. Dateien, die danach noch jemand geändert hat, bleiben unangetastet.
Was Befehle im Terminal verändern, kennt Coder nicht – das lässt sich nicht zurücknehmen.
"""

import difflib
import hashlib
import json
import os
import re
import shutil
import time
from pathlib import Path

from .config import HOME

ROOT = HOME / "checkpoints"
ID_RX = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
MAX_BYTES = 8 * 1024 * 1024  # größere Dateien sichert Coder nicht
STATS_BYTES = 400_000  # bis zu dieser Größe werden geänderte Zeilen gezählt
KEEP = 30  # Sicherungen je Chat

NOTE = ("[Coder note] The user undid the file changes of an earlier request. These files are back to their previous "
        "state: {files}. Do not assume those changes still exist – read the files again before editing them.")


def _sha(data: bytes | None) -> str | None:
    return None if data is None else hashlib.sha256(data).hexdigest()


def _read(path: Path) -> bytes | None:
    try:
        return path.read_bytes() if path.is_file() else None
    except OSError:
        return None


def folder(session_id: str, turn_id: str | None = None) -> Path:
    """Ordner einer Sicherung. Die Kennungen kommen auch aus der Oberfläche – deshalb streng geprüft."""
    for part in (session_id, turn_id):
        if part is not None and not ID_RX.match(str(part)):
            raise ValueError("Ungültige Kennung einer Sicherung.")
    return ROOT / session_id / turn_id if turn_id else ROOT / session_id


def label(path: str | Path, workspace) -> str:
    try:
        return Path(path).relative_to(Path(workspace)).as_posix()
    except (ValueError, TypeError):
        return str(path)


def line_stats(old: bytes | None, new: bytes | None) -> tuple[int, int] | None:
    """Hinzugefügte und entfernte Zeilen – None für Binärdateien und sehr große Dateien."""
    texts = []
    for data in (old, new):
        if data is None:
            texts.append([])
            continue
        if len(data) > STATS_BYTES or b"\0" in data[:8000]:
            return None
        texts.append(data.decode("utf-8", "replace").splitlines())
    added = removed = 0
    for line in list(difflib.unified_diff(texts[0], texts[1], n=0, lineterm=""))[2:]:  # ohne die zwei Kopfzeilen
        if line.startswith("@@"):
            continue
        if line.startswith("+"):
            added += 1
        elif line.startswith("-"):
            removed += 1
    return added, removed


class Checkpoint:
    """Die Sicherung einer Aufgabe: der Inhalt jeder Datei vor ihrer ersten Änderung."""

    def __init__(self, session_id: str, turn_id: str):
        self.session_id, self.turn_id = str(session_id), str(turn_id)
        self.dir = folder(self.session_id, self.turn_id)
        self.files: dict[str, dict] = {}
        try:
            self.files = json.loads((self.dir / "index.json").read_text("utf-8")).get("files") or {}
        except (OSError, ValueError):
            pass

    def capture(self, path: Path) -> None:
        """Vor dem Schreiben aufrufen. Nur die erste Änderung einer Datei zählt – sie hält den Zustand davor fest."""
        path = Path(path)
        key = os.path.normcase(str(path))
        if key in self.files:
            return
        entry: dict = {"path": str(path), "existed": path.is_file()}
        data = None
        if entry["existed"]:
            try:
                if path.stat().st_size > MAX_BYTES:
                    entry["too_big"] = True
                else:
                    data = path.read_bytes()
            except OSError:
                entry["unreadable"] = True
        try:
            self.dir.mkdir(parents=True, exist_ok=True)
            if data is not None:
                entry["blob"] = f"{len(self.files)}.bin"
                entry["sha"] = _sha(data)
                (self.dir / entry["blob"]).write_bytes(data)
            self.files[key] = entry
            self._save()
        except OSError:
            entry.pop("blob", None)
            entry["unreadable"] = True  # ohne Sicherung weiterarbeiten – Zurücknehmen lässt diese Datei dann aus
            self.files[key] = entry

    def _save(self) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        tmp = self.dir / "index.tmp"
        tmp.write_text(json.dumps({"turn": self.turn_id, "saved": time.time(), "files": self.files}, ensure_ascii=False),
                       encoding="utf-8")
        tmp.replace(self.dir / "index.json")

    def seal(self, workspace) -> dict | None:
        """Nach der Aufgabe: den Stand danach festhalten und zusammenfassen, was sich wirklich geändert hat."""
        if not self.files:
            return None
        changed = []
        for entry in self.files.values():
            path = Path(entry["path"])
            now = _read(path)
            entry["after"] = _sha(now)
            if not entry["existed"] and now is None:
                continue  # angelegt und wieder entfernt
            if entry.get("sha") and entry["sha"] == entry["after"]:
                continue  # am Ende wieder wie vorher
            before = None
            if entry.get("blob"):
                try:
                    before = (self.dir / entry["blob"]).read_bytes()
                except OSError:
                    before = None
            stats = line_stats(before, now) if entry.get("blob") or not entry["existed"] else None
            changed.append({"path": label(path, workspace), "created": not entry["existed"], "deleted": now is None,
                            "added": stats[0] if stats else None, "removed": stats[1] if stats else None,
                            "saved": not (entry.get("too_big") or entry.get("unreadable"))})
        try:
            self._save()
        except OSError:
            pass
        if not changed:
            shutil.rmtree(self.dir, ignore_errors=True)
            return None
        prune(self.session_id)
        return {"turn": self.turn_id, "files": changed, "undone": False}


def restore(session_id: str, turn_id: str, workspace=None) -> dict:
    """Setzt die Dateien einer Aufgabe auf den Stand davor zurück."""
    cp = Checkpoint(session_id, turn_id)
    if not cp.files:
        raise ValueError("Diese Sicherung gibt es nicht mehr – Coder behält nur die letzten Sicherungen je Chat.")
    restored, skipped = [], []
    for entry in cp.files.values():
        path = Path(entry["path"])
        now = _read(path)
        if not entry["existed"] and now is None:
            continue
        if entry.get("sha") and entry.get("sha") == entry.get("after"):
            continue  # unverändert
        name = label(path, workspace)
        if "after" in entry and _sha(now) != entry["after"]:
            skipped.append({"path": name, "reason": "danach noch einmal geändert"})
            continue
        if entry.get("too_big") or entry.get("unreadable"):
            skipped.append({"path": name, "reason": "ließ sich nicht sichern"})
            continue
        try:
            if entry["existed"]:
                data = (cp.dir / entry["blob"]).read_bytes()
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(data)
            else:
                path.unlink()
        except OSError as e:
            skipped.append({"path": name, "reason": f"nicht möglich ({e.strerror or e.__class__.__name__})"})
            continue
        restored.append(name)
    return {"turn": turn_id, "restored": restored, "skipped": skipped}


def latest(session: dict) -> dict | None:
    """Die jüngsten Änderungen dieses Chats, die noch nicht zurückgenommen sind."""
    for message in reversed(session.get("messages") or []):
        changes = message.get("_changes")
        if changes and not changes.get("undone"):
            return changes
    return None


def undo(session: dict) -> dict:
    """Nimmt die jüngsten Änderungen zurück und sagt es dem Modell, damit es nicht mit altem Stand weiterplant."""
    changes = latest(session)
    if changes is None:
        raise ValueError("Es gibt keine Änderungen, die sich zurücknehmen lassen.")
    result = restore(session["id"], changes["turn"], session.get("workspace"))
    changes["undone"] = True
    messages = session.setdefault("messages", [])
    messages.append({"role": "event", "_ui": True, "_undo": result})
    if result["restored"]:
        messages.append({"role": "user", "content": NOTE.format(files=", ".join(result["restored"][:30])),
                         "_nudge": True})
    return result


def prune(session_id: str, keep: int = KEEP) -> None:
    try:
        base = folder(session_id)
        dirs = sorted((d for d in base.iterdir() if d.is_dir()), key=lambda d: d.stat().st_mtime, reverse=True)
    except (OSError, ValueError):
        return
    for old in dirs[keep:]:
        shutil.rmtree(old, ignore_errors=True)


def delete_session(session_id: str) -> None:
    try:
        shutil.rmtree(folder(session_id), ignore_errors=True)
    except ValueError:
        pass
