"""Chatverläufe als JSON unter ~/.coder/sessions/."""

import json
import re
import time
import uuid

from .config import SESSIONS_DIR

_ID = re.compile(r"^[a-f0-9]{12}$")
# code: der Agent im Projekt · talk: der Tab Chat – reden und recherchieren, ohne Projekt und Dateien
KINDS = ("code", "talk")


def new(workspace: str, model: str, owner: str = "", kind: str = "code", incognito: bool = False) -> dict:
    """incognito: Der Chat wird nie gesichert und nutzt kein Gedächtnis – weg, sobald ihn niemand mehr offen hat."""
    now = time.time()
    s = {
        "id": uuid.uuid4().hex[:12],
        "title": "Neuer Chat",
        # Wem der Chat gehört: "" ist der Besitzer am Rechner, sonst der Name eines Kontos (core/users.py).
        "owner": owner,
        "kind": kind if kind in KINDS else "code",
        "created": now,
        "updated": now,
        "workspace": workspace,
        "model": model,
        # Nachrichten im Ollama-Format. Schlüssel mit "_" sind UI-Metadaten
        # und werden vor dem Senden an das Modell entfernt.
        "messages": [],
        "todos": [],
        "allow": [],
        "usage": {"prompt": 0, "completion": 0, "last_prompt": 0},
    }
    if incognito:
        s["incognito"] = True
    return s


def _path(session_id: str):
    if not _ID.match(session_id or ""):
        raise ValueError("Ungültige Session-ID")
    return SESSIONS_DIR / f"{session_id}.json"


def save(session: dict) -> None:
    if session.get("incognito"):
        return  # Inkognito: nichts auf die Platte
    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    session["updated"] = time.time()
    path = _path(session["id"])
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(session, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


AUTOSAVE_GAP = 5.0  # Sekunden zwischen zwei Zwischenständen eines laufenden Auftrags
_autosaved: dict[str, float] = {}


def autosave(session: dict, gap: float = AUTOSAVE_GAP) -> bool:
    """Zwischenstand während der Arbeit – stürzt Coder mitten im Auftrag ab, ist nicht der ganze Verlauf weg.

    Höchstens alle `gap` Sekunden; im selben Thread wie der Agent, damit niemand den Verlauf ändert, während er
    geschrieben wird.
    """
    sid = str(session.get("id") or "")
    now = time.monotonic()
    if session.get("incognito") or not session.get("messages") or now - _autosaved.get(sid, 0.0) < gap:
        return False
    _autosaved[sid] = now
    try:
        save(session)
    except (OSError, ValueError, TypeError):
        return False
    return True


def kind_of(session: dict | None) -> str:
    return "talk" if (session or {}).get("kind") == "talk" else "code"


def owner_of(session: dict | None) -> str:
    return str((session or {}).get("owner") or "")


def load(session_id: str) -> dict | None:
    try:
        return json.loads(_path(session_id).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def delete(session_id: str) -> None:
    try:
        _path(session_id).unlink()
    except (OSError, ValueError):
        pass


_summaries: dict[str, tuple[float, int, dict]] = {}  # Datei → (Änderungszeit, Größe, Kurzfassung)


def list_all(limit: int = 200, owner: str | None = None) -> list[dict]:
    """Die Chats, neueste zuerst. owner: nur die Chats dieses Kontos ("" = der Besitzer am Rechner)."""
    if not SESSIONS_DIR.exists():
        return []
    items = []
    for f in SESSIONS_DIR.glob("*.json"):
        try:
            stat = f.stat()
            cached = _summaries.get(str(f))
            if cached and cached[:2] == (stat.st_mtime, stat.st_size):
                items.append(cached[2])  # unverändert: nicht jedes Mal den ganzen Verlauf parsen
                continue
            s = json.loads(f.read_text(encoding="utf-8"))
            summary = {"id": s["id"], "title": s.get("title", ""), "updated": s.get("updated", 0),
                       "workspace": s.get("workspace", ""), "model": s.get("model", ""),
                       "kind": kind_of(s), "owner": owner_of(s)}
            _summaries[str(f)] = (stat.st_mtime, stat.st_size, summary)
            items.append(summary)
        except (OSError, ValueError, KeyError):
            continue
    if owner is not None:
        items = [s for s in items if s["owner"] == owner]
    items.sort(key=lambda s: s["updated"], reverse=True)
    return items[:limit]
