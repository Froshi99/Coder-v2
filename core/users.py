"""Mehrere Nutzer an einem Coder: Konten, Rollen, Einladungen und Anmeldung.

Wer direkt an diesem Rechner sitzt, ist der Besitzer und meldet sich nie an. Alle anderen – aus dem LAN oder über
eine Portfreigabe in VS Code (Dev Tunnel) – brauchen ein Konto. Konten legt der Besitzer als Einladung an: Er
bekommt einen Link, der Eingeladene setzt darüber sein eigenes Passwort. Der Besitzer kennt es nie.

Gespeichert wird unter ~/.coder/users.json – Passwörter nur als PBKDF2-Hash, Anmeldungen und Einladungen nur als
SHA-256 ihres Schlüssels. Wer die Datei liest, kann sich damit nicht anmelden.
"""

import copy
import hashlib
import hmac
import json
import re
import secrets
import threading
import time
from pathlib import Path

from . import config as config_mod
from . import personal

# Was ein Konto darf – von wenig nach viel. Jede Stufe enthält die davor.
ROLES = ("chat", "read", "code", "admin")
ROLE_LABELS = {
    "chat": "Nur Chat",
    "read": "Lesen",
    "code": "Mitarbeiten",
    "admin": "Verwalten",
}
ROLE_HINTS = {
    "chat": "Der Tab Chat: reden und im Netz recherchieren. Kein Zugriff auf Projekt und Dateien",
    "read": "Dazu Code-Chats in den Modi Chat und Planen, Dateien nur ansehen",
    "code": "Dazu Dateien ändern und Befehle nach Freigabe – auf diesem Rechner",
    "admin": "Alles, auch Einstellungen, Modelle, Konten und der Modus Autonom",
}
# Welche Modi eine Rolle wählen darf (core/config.PERMISSION_MODES).
ROLE_MODES = {
    "chat": (),
    "read": ("chat", "plan"),
    "code": ("chat", "ask", "auto-edit", "plan"),
    "admin": config_mod.PERMISSION_MODES,
}
# Was ein Nutzer ohne Verwaltungsrecht für sich selbst einstellen darf – der Rest gehört dem Besitzer.
OWN_PREFS = ("permission_mode", "effort", "design", "theme", "palette", "style") + personal.KEYS

NAME_RX = re.compile(r"^[A-Za-z0-9ÄÖÜäöüß][A-Za-z0-9ÄÖÜäöüß ._-]{0,31}$")
MIN_PASSWORD = 8
ITERATIONS = 240_000
TOKEN_DAYS = 30
INVITE_DAYS = 7
# Falsche Passwörter bremsen: nach so vielen Fehlversuchen je Konto eine Pause, die sich verdoppelt.
FREE_TRIES = 5
LOCK_SECONDS = 30

_lock = threading.RLock()
_failures: dict[str, tuple[int, float]] = {}  # Konto → (Fehlversuche, gesperrt bis)


class UserError(ValueError):
    """Etwas, das der Nutzer ändern kann: falsches Passwort, belegter Name, abgelaufene Einladung."""


def path() -> Path:
    return config_mod.HOME / "users.json"


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _hash_password(password: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt), ITERATIONS).hex()


_cache: dict = {"key": None, "data": None}


def _load() -> dict:
    """Die Datei – zwischengespeichert, solange sie sich nicht ändert: Sie wird bei jeder Anfrage von außen gefragt."""
    try:
        stat = path().stat()
        key = (stat.st_mtime_ns, stat.st_size)
    except OSError:
        key = None
    if key is not None and _cache["key"] == key:
        return copy.deepcopy(_cache["data"])
    try:
        data = json.loads(path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    if key is not None and isinstance(data, dict):
        _cache.update(key=key, data=copy.deepcopy(data))
    if not isinstance(data, dict):
        data = {}
    data.setdefault("users", {})
    data.setdefault("tokens", {})
    return data


def _save(data: dict) -> None:
    target = path()
    target.parent.mkdir(parents=True, exist_ok=True)
    now = time.time()
    # Abgelaufene Anmeldungen fallen beim Schreiben weg – sonst wüchse die Datei mit jedem Besuch.
    data["tokens"] = {k: v for k, v in data["tokens"].items()
                      if v.get("expires", 0) > now and v.get("user") in data["users"]}
    tmp = target.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(target)
    try:
        stat = target.stat()
        _cache.update(key=(stat.st_mtime_ns, stat.st_size), data=copy.deepcopy(data))
    except OSError:
        _cache.update(key=None, data=None)


def _key(name: str) -> str:
    return str(name or "").strip().casefold()


def public(user: dict) -> dict:
    """Was die Oberfläche über ein Konto erfährt – nie Hash, Salz oder Einladung."""
    return {
        "name": user.get("name", ""),
        "role": user.get("role", "chat"),
        "role_label": ROLE_LABELS.get(user.get("role", "chat"), ""),
        "created": user.get("created", 0),
        "last_seen": user.get("last_seen", 0),
        "workspace": user.get("workspace", ""),
        "pending": bool(user.get("invite")),  # eingeladen, aber noch kein Passwort gesetzt
        "self": bool(user.get("self")),
        "local": bool(user.get("local")),
    }


def owner() -> dict:
    """Wer direkt am Rechner sitzt: der Besitzer, ohne Anmeldung, mit allen Rechten."""
    return {"name": "", "role": "admin", "local": True}


def owner_key(user: dict | None) -> str:
    """Unter welchem Namen die Chats eines Kontos liegen: "" für den Besitzer – am Rechner und mit seinem eigenen
    Konto für unterwegs (`self`), damit er dort dieselben Chats sieht."""
    if not user or user.get("local") or user.get("self"):
        return ""
    return _key(user.get("name", ""))


def is_admin(user: dict | None) -> bool:
    return bool(user) and user.get("role") == "admin"


def at_least(user: dict | None, role: str) -> bool:
    """Darf das Konto mindestens so viel wie `role`?"""
    have = (user or {}).get("role", "")
    return have in ROLES and ROLES.index(have) >= ROLES.index(role)


def modes(user: dict | None) -> tuple[str, ...]:
    return ROLE_MODES.get((user or {}).get("role", ""), ())


def listing() -> list[dict]:
    with _lock:
        users = _load()["users"].values()
    return sorted((public(u) for u in users), key=lambda u: u["name"].casefold())


def get(name: str) -> dict | None:
    with _lock:
        return _load()["users"].get(_key(name))


def count() -> int:
    with _lock:
        return len(_load()["users"])


def invite(name: str, role: str = "chat", workspace: str = "", self_: bool = False) -> tuple[dict, str]:
    """Ein neues Konto als Einladung. Gibt das Konto und den Einladungsschlüssel zurück (nur dieses eine Mal).

    self_: das Konto des Besitzers für unterwegs – es sieht dieselben Chats und das Gedächtnis wie am Rechner.
    """
    name = " ".join(str(name or "").split())
    if not NAME_RX.match(name):
        raise UserError("Namen aus Buchstaben, Ziffern, Leerzeichen, Punkt, Binde- oder Unterstrich, höchstens 32 Zeichen.")
    if role not in ROLES:
        raise UserError("Diese Rolle gibt es nicht.")
    code = secrets.token_urlsafe(18)
    with _lock:
        data = _load()
        if _key(name) in data["users"]:
            raise UserError(f"Es gibt schon ein Konto „{name}“.")
        user = {"name": name, "role": role, "created": time.time(), "workspace": str(workspace or ""),
                "prefs": {}, "invite": _digest(code), "invite_expires": time.time() + INVITE_DAYS * 86400,
                "self": bool(self_) and role == "admin"}
        data["users"][_key(name)] = user
        _save(data)
    return public(user), code


def reinvite(name: str) -> str:
    """Neuer Einladungslink – etwa wenn jemand sein Passwort vergessen hat. Das alte Passwort gilt dann nicht mehr."""
    code = secrets.token_urlsafe(18)
    with _lock:
        data = _load()
        user = data["users"].get(_key(name))
        if not user:
            raise UserError("Dieses Konto gibt es nicht.")
        user.pop("salt", None)
        user.pop("hash", None)
        user["invite"] = _digest(code)
        user["invite_expires"] = time.time() + INVITE_DAYS * 86400
        data["tokens"] = {k: v for k, v in data["tokens"].items() if v.get("user") != _key(name)}
        _save(data)
    return code


def invited(code: str) -> dict | None:
    """Zu welchem Konto ein Einladungsschlüssel gehört – solange er gilt."""
    if not code:
        return None
    want = _digest(code)
    with _lock:
        for user in _load()["users"].values():
            if user.get("invite") and hmac.compare_digest(user["invite"], want) \
                    and user.get("invite_expires", 0) > time.time():
                return user
    return None


def accept(code: str, password: str) -> str:
    """Einladung annehmen: Passwort setzen und gleich angemeldet sein. Gibt den Anmeldeschlüssel zurück."""
    if len(password or "") < MIN_PASSWORD:
        raise UserError(f"Das Passwort braucht mindestens {MIN_PASSWORD} Zeichen.")
    with _lock:
        user = invited(code)
        if not user:
            raise UserError("Die Einladung gilt nicht mehr. Bitte um einen neuen Link.")
        data = _load()
        stored = data["users"][_key(user["name"])]
        salt = secrets.token_hex(16)
        stored.update(salt=salt, hash=_hash_password(password, salt))
        stored.pop("invite", None)
        stored.pop("invite_expires", None)
        _save(data)
        return _issue(data, stored)


def _issue(data: dict, user: dict) -> str:
    token = secrets.token_urlsafe(32)
    data["tokens"][_digest(token)] = {"user": _key(user["name"]), "expires": time.time() + TOKEN_DAYS * 86400}
    _save(data)
    return token


def login(name: str, password: str) -> str:
    """Anmelden. Gibt den Anmeldeschlüssel für das Cookie zurück."""
    key = _key(name)
    now = time.time()
    with _lock:
        tries, until = _failures.get(key, (0, 0.0))
        if until > now:
            raise UserError(f"Zu viele Fehlversuche. Noch {int(until - now) + 1} Sekunden warten.")
        data = _load()
        user = data["users"].get(key)
        ok = False
        if user and user.get("hash") and user.get("salt"):
            ok = hmac.compare_digest(user["hash"], _hash_password(str(password or ""), user["salt"]))
        else:
            _hash_password(str(password or ""), "00" * 16)  # gleich lange rechnen: kein Hinweis, ob es den Namen gibt
        if not ok:
            tries += 1
            lock = LOCK_SECONDS * 2 ** (tries - FREE_TRIES) if tries >= FREE_TRIES else 0
            _failures[key] = (tries, now + min(lock, 3600))
            raise UserError("Name oder Passwort stimmt nicht.")
        _failures.pop(key, None)
        return _issue(data, user)


def by_token(token: str) -> dict | None:
    """Das Konto hinter einem Anmeldeschlüssel aus dem Cookie – oder None."""
    if not token or len(token) > 200:
        return None
    with _lock:
        data = _load()
        entry = data["tokens"].get(_digest(token))
        if not entry or entry.get("expires", 0) <= time.time():
            return None
        user = data["users"].get(entry.get("user", ""))
        if not user or user.get("invite"):
            return None
        if time.time() - user.get("last_seen", 0) > 60:  # nicht bei jeder Anfrage schreiben
            user["last_seen"] = time.time()
            _save(data)
        return user


def logout(token: str) -> None:
    with _lock:
        data = _load()
        if data["tokens"].pop(_digest(token or ""), None) is not None:
            _save(data)


def update(name: str, changes: dict) -> dict:
    """Rolle oder Ordner eines Kontos ändern (Verwaltung)."""
    with _lock:
        data = _load()
        user = data["users"].get(_key(name))
        if not user:
            raise UserError("Dieses Konto gibt es nicht.")
        if "role" in changes:
            if changes["role"] not in ROLES:
                raise UserError("Diese Rolle gibt es nicht.")
            user["role"] = changes["role"]
            if user["role"] != "admin":
                user["self"] = False  # nur der Besitzer selbst sieht die Chats vom Rechner
            allowed = ROLE_MODES[user["role"]]
            if user.get("prefs", {}).get("permission_mode") not in allowed:
                user.setdefault("prefs", {}).pop("permission_mode", None)
        if "workspace" in changes:
            user["workspace"] = str(changes["workspace"] or "")
        _save(data)
        return public(user)


def set_prefs(name: str, prefs: dict) -> dict:
    """Die eigenen Einstellungen eines Nutzers: Modus, Aufwand, Aussehen, Antwortstil und eigene Anweisungen."""
    with _lock:
        data = _load()
        user = data["users"].get(_key(name))
        if not user:
            raise UserError("Dieses Konto gibt es nicht.")
        own = user.setdefault("prefs", {})
        for key in OWN_PREFS:
            if key in prefs:
                own[key] = personal.clean(prefs[key]) if key in personal.KEYS else prefs[key]
        if own.get("permission_mode") not in ROLE_MODES.get(user.get("role"), ()):
            own.pop("permission_mode", None)
        if "style" in own and own["style"] not in personal.STYLES:
            own.pop("style")
        _save(data)
        return dict(own)


def remove(name: str) -> None:
    with _lock:
        data = _load()
        if data["users"].pop(_key(name), None) is None:
            raise UserError("Dieses Konto gibt es nicht.")
        _save(data)
    _failures.pop(_key(name), None)


def user_config(cfg: dict, user: dict | None) -> dict:
    """Die Einstellung, mit der ein Nutzer arbeitet: die des Besitzers, darüber seine eigenen Werte.

    Was er nicht darf, bekommt er gar nicht erst: einen Modus außerhalb seiner Rolle, das Gedächtnis des
    Besitzers, einen fremden Ordner.
    """
    if not user or user.get("local") or user.get("self"):
        return cfg
    merged = dict(cfg)
    prefs = user.get("prefs") or {}
    for key in OWN_PREFS:
        if key in prefs:
            merged[key] = prefs[key]
    # Die eigenen Anweisungen des Besitzers („Ich heiße …“) sind seine – ein Gast hat nur seine eigenen oder keine.
    for key in personal.KEYS:
        merged[key] = personal.clean(prefs.get(key))
    merged["style"] = prefs["style"] if prefs.get("style") in personal.STYLES else "normal"
    allowed = modes(user)
    if merged.get("permission_mode") not in allowed:
        merged["permission_mode"] = "ask" if "ask" in allowed else (allowed[0] if allowed else "chat")
    merged["memory"] = False  # die Notizen des Besitzers sind seine – Gäste sehen und schreiben sie nicht
    merged["auto_recall"] = False
    merged["journal"] = False
    workspace = str(user.get("workspace") or "")
    if workspace and Path(workspace).is_dir() and not config_mod.blocked_workspace(workspace):
        merged["workspace"] = workspace
    return merged
