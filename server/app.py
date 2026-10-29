"""HTTP- und WebSocket-Server für die Oberfläche."""

import asyncio
import codecs
import ipaddress
import logging
import os
import re
import shutil
import socket
import subprocess
import time
import traceback
import uuid
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import Body, FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from core import (__version__, agents, checkpoints, commands, cowork, folders, imagegen, memory, optimizer,
                  power, preprompt, report, sessions, speech, tools, users, vision)
from core import complete as complete_mod
from core import loop as loop_mod
from core import vllm as vllm_mod
from core import config as config_mod
from core.agent import Agent, AgentError
from core.ollama import OllamaError
from core.runtime import Runtime

WEB = Path(__file__).resolve().parent.parent / "web"
log = logging.getLogger("coder")
LOOPBACK = {"127.0.0.1", "localhost", "::1"}
MAX_QUEUE = 8
MAX_COMPLETE = 20_000  # so viel Text um den Cursor nimmt das Ergänzen entgegen
MAX_FILE = 2 * 1024 * 1024  # so groß darf eine Datei in der Dateiansicht sein
COOKIE = "coder_auth"
# Diese Kopfzeilen setzt ein Vermittler: VS Codes Portfreigabe (Dev Tunnel), ein Reverse-Proxy, Codespaces.
# Wer so hereinkommt, sitzt nicht am Rechner – auch wenn die Verbindung von 127.0.0.1 kommt.
FORWARD_HEADERS = ("x-forwarded-for", "x-forwarded-host", "x-forwarded-proto", "forwarded",
                   "x-original-host", "x-original-for", "x-original-proto")
# Adressen, unter denen Portfreigaben erreichbar sind – falls der Tunnel den Host-Namen nicht umschreibt.
TUNNEL_SUFFIXES = (".devtunnels.ms", ".github.dev", ".githubpreview.dev", ".gitpod.io", ".ngrok-free.app",
                   ".ngrok.app", ".trycloudflare.com")
# Ohne Anmeldung erreichbar: die Anmeldeseite selbst und das, was sie zum Aussehen braucht.
OPEN_PATHS = ("/login", "/api/login", "/api/invite", "/api/logout")


def is_local(request) -> bool:
    """Sitzt, wer fragt, an diesem Rechner? Systemdialoge, Mikrofon und eigene Adressen gibt es nur dann.

    Nicht die Adresse allein entscheidet: Eine Portfreigabe in VS Code liefert jede Anfrage von 127.0.0.1 aus –
    erkennbar ist sie nur an den Kopfzeilen, die der Tunnel dazuschreibt (das prüft LocalGuard).
    """
    return bool(getattr(request.state, "local", False))


def user_of(conn) -> dict:
    """Das Konto hinter einer Anfrage oder einem WebSocket – am Rechner selbst der Besitzer."""
    return getattr(conn.state, "user", None) or {"name": "", "role": ""}  # ohne Guard: niemand, nicht der Besitzer


def hostname(value: str) -> str:
    """Hostname aus einem Host-Header: ohne Port, IPv6 ohne Klammern."""
    try:
        return (urlsplit(f"//{value}").hostname or "").lower()
    except ValueError:
        return ""


def same_origin(origin: str, host: str) -> bool:
    try:
        parts = urlsplit(origin)
    except ValueError:
        return False
    return parts.scheme in ("http", "https") and bool(host) and parts.netloc.lower() == host.lower()


def cookie_of(headers: dict) -> str:
    for part in headers.get("cookie", "").split(";"):
        key, _, value = part.strip().partition("=")
        if key == COOKIE:
            return value.strip()
    return ""


class LocalGuard:
    """Wer darf herein – und als wer?

    Am Rechner selbst (127.0.0.1, ohne Vermittler) ist man der Besitzer und meldet sich nie an. Alle anderen – aus
    dem LAN mit --host 0.0.0.0 oder über eine Portfreigabe in VS Code – brauchen ein Konto (core/users.py). Das
    Ergebnis steht danach in scope["state"]: `user` und `local`.

    Browser dürfen nur von der Oberfläche selbst kommen. WebSockets kennen keine Same-Origin-Regel: Ohne diese
    Prüfung könnte jede geöffnete Webseite Coder Aufträge schicken und Freigaben erteilen, also Befehle auf diesem
    Rechner ausführen. Der Blick auf den Host-Header wehrt zusätzlich DNS-Rebinding ab.

    VS Codes Tunnel schreibt Host und Origin standardmäßig auf „localhost“ um. Dort schützt deshalb das Cookie:
    SameSite=Lax schickt es bei keiner Anfrage mit, die eine fremde Seite auslöst – auch bei keinem WebSocket.
    """

    def __init__(self, app, public: bool = False, share: "Share | None" = None):
        self.app = app
        self.share = share or Share()
        self.public = public  # mit --host 0.0.0.0 gestartet: auch Adressen im LAN
        name = socket.gethostname().lower()
        self.machine = {name, f"{name}.local"}

    def host_allowed(self, host: str, forwarded: bool = False) -> bool:
        name = hostname(host)
        if name in LOOPBACK:
            return True
        if forwarded and name.endswith(TUNNEL_SUFFIXES):
            return True
        if not self.public or not name:
            return False
        try:
            ipaddress.ip_address(name)
            return True
        except ValueError:
            return name in self.machine

    @staticmethod
    def origin_allowed(origin: str | None, host: str, headers: dict, forwarded: bool) -> bool:
        if origin is None or same_origin(origin, host):
            return True
        if not forwarded:
            return False
        outside = headers.get("x-forwarded-host", "").split(",")[0].strip()
        if outside and same_origin(origin, outside):
            return True
        # Der Tunnel hat die Herkunft auf localhost umgeschrieben – dann trägt das Cookie den Schutz (siehe oben).
        try:
            return (urlsplit(origin).hostname or "").lower() in LOOPBACK
        except ValueError:
            return False

    async def __call__(self, scope, receive, send):
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return
        headers = {key.decode("latin-1").lower(): value.decode("latin-1") for key, value in scope.get("headers") or []}
        host, origin = headers.get("host", ""), headers.get("origin")
        forwarded = any(h in headers for h in FORWARD_HEADERS)
        client = (scope.get("client") or ("", 0))[0]
        local = client in LOOPBACK and not forwarded
        if not (self.host_allowed(host, forwarded) and self.origin_allowed(origin, host, headers, forwarded)):
            log.warning("Anfrage abgewiesen: Host %r, Origin %r", host, origin)
            await self.refuse(scope, receive, send, 403, "Coder nimmt nur Anfragen seiner eigenen Oberfläche an.")
            return
        outside = headers.get("x-forwarded-host", "").split(",")[0].strip()
        if forwarded and hostname(outside).endswith(TUNNEL_SUFFIXES):
            self.share.seen(outside)  # für die Einladungslinks: so heißt Coder von außen
        user = users.owner() if local else users.by_token(cookie_of(headers))
        path = scope.get("path", "")
        if user is None and not (path in OPEN_PATHS or path.startswith("/static/")):
            if scope["type"] == "websocket":
                await receive()  # websocket.connect
                # Erst annehmen, dann mit 4401 schließen. Ein Schließen vor dem Annehmen lehnt den Handshake ab: Der
                # Browser sähe nur 1006 statt 4401 und verbände sich endlos neu, statt zur Anmeldung zu gehen.
                await send({"type": "websocket.accept"})
                await send({"type": "websocket.close", "code": 4401})
                return
            if scope.get("method") == "GET" and not path.startswith("/api/"):
                await send({"type": "http.response.start", "status": 303,
                            "headers": [(b"location", b"/login"), (b"content-length", b"0"),
                                        (b"cache-control", b"no-store")]})
                await send({"type": "http.response.body", "body": b""})
                return
            await self.refuse(scope, receive, send, 401, "Bitte zuerst anmelden.")
            return
        state = scope.setdefault("state", {})
        state["user"] = user
        state["local"] = local
        state["secure"] = (headers.get("x-forwarded-proto", "").split(",")[0].strip() == "https"
                           or scope.get("scheme") in ("https", "wss"))
        await self.app(scope, receive, send)

    @staticmethod
    async def refuse(scope, receive, send, status: int, text: str) -> None:
        if scope["type"] == "websocket":
            await receive()  # websocket.connect – ein close davor lehnt den Handshake ab
            await send({"type": "websocket.close", "code": 1008})
            return
        body = text.encode("utf-8")
        await send({"type": "http.response.start", "status": status,
                    "headers": [(b"content-type", b"text/plain; charset=utf-8"),
                                (b"content-length", str(len(body)).encode("ascii"))]})
        await send({"type": "http.response.body", "body": body})


class FreshStatic(StaticFiles):
    """Die Oberfläche liegt als Dateien in web/ und ändert sich mit jedem Update. Ohne Vorgabe hebt der Browser
    app.js und styles.css auf und mischt sie mit der neuen index.html – dann fehlen Knöpfe oder Funktionen.
    no-cache heißt: jedes Mal nachfragen. Ist nichts geändert, kommt nur ein kurzes 304 zurück."""

    async def get_response(self, path: str, scope):
        response = await super().get_response(path, scope)
        response.headers.setdefault("Cache-Control", "no-cache")
        return response


class Share:
    """Wer gerade da ist und unter welcher Adresse Coder von außen erreichbar ist."""

    def __init__(self) -> None:
        self.tunnel = ""  # zuletzt gesehene Adresse einer Portfreigabe, etwa abc123-8765.euw.devtunnels.ms
        self.conns: list["Connection"] = []

    def seen(self, host: str) -> None:
        self.tunnel = host[:200]

    def url(self, cfg: dict) -> str:
        own = str(cfg.get("public_url") or "").strip().rstrip("/")
        return own or (f"https://{self.tunnel}" if self.tunnel else "")

    async def announce(self) -> None:
        """Wer verwaltet, sieht sofort, wer kommt und geht."""
        online = self.online()
        for conn in list(self.conns):
            if users.is_admin(conn.user):
                await conn.send({"type": "presence", "online": online})

    def online(self) -> list[dict]:
        out = []
        for conn in self.conns:
            s = conn.session or {}
            out.append({"name": conn.user.get("name") or "", "role": conn.user.get("role", ""),
                        "local": bool(conn.user.get("local")), "since": conn.since,
                        "kind": sessions.kind_of(s), "busy": conn.busy})
        return out


ROLE_DENIED = {
    "read": "Dein Konto darf nur den Chat benutzen.",
    "code": "Dein Konto darf hier nur lesen.",
    "admin": "Das darf nur, wer Coder verwaltet.",
}
MAX_LIST = 20_000   # so viele Dateien kennt die Schnellsuche im Editor höchstens
MAX_HITS = 500      # so viele Treffer liefert die Suche in Dateien höchstens
MAX_SEARCH_FILE = 1024 * 1024  # größere Dateien durchsucht der Editor nicht


def need(conn, role: str) -> dict:
    """Das Konto hinter der Anfrage – sofern es mindestens `role` darf, sonst 403."""
    user = user_of(conn)
    if not users.at_least(user, role):
        raise HTTPException(403, ROLE_DENIED.get(role, "Das darf dein Konto nicht."))
    return user


def walk_files(ws: Path, limit: int = MAX_LIST):
    """Alle Dateien im Workspace, ohne Abhängigkeits- und Build-Ordner – für Schnellsuche und Suche in Dateien."""
    count = 0
    for root, dirs, names in os.walk(ws):
        dirs[:] = sorted(d for d in dirs
                         if d not in tools.IGNORE_DIRS and (not d.startswith(".") or d in tools.HIDDEN_KEEP))
        for name in sorted(names, key=str.lower):
            yield Path(root) / name
            count += 1
            if count >= limit:
                return


def search_files(ws: Path, query: str, regex: bool = False, case: bool = False) -> dict:
    """Suche in Dateien wie in VS Code: Treffer mit Zeile, Spalte und der Zeile selbst."""
    flags = 0 if case else re.IGNORECASE
    try:
        rx = re.compile(query if regex else re.escape(query), flags)
    except re.error as e:
        raise HTTPException(400, f"Ungültiger Ausdruck: {e}")
    hits, files_hit, capped = [], 0, False
    for path in walk_files(ws):
        try:
            if path.stat().st_size > MAX_SEARCH_FILE:
                continue
            text = tools._read_text(path)
        except (OSError, tools.ToolError):
            continue
        found = False
        for number, line in enumerate(text.splitlines(), 1):
            m = rx.search(line)
            if not m or not m.group(0):
                continue
            found = True
            hits.append({"path": path.relative_to(ws).as_posix(), "line": number, "col": m.start() + 1,
                         "len": len(m.group(0)), "text": line[:300]})
            if len(hits) >= MAX_HITS:
                capped = True
                break
        files_hit += found
        if capped:
            break
    return {"hits": hits, "files": files_hit, "capped": capped}


IMAGE_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".gif": "image/gif",
               ".webp": "image/webp", ".bmp": "image/bmp", ".ico": "image/x-icon", ".svg": "image/svg+xml"}
MAX_IMAGE = 20 * 1024 * 1024


def git_status(ws: Path) -> dict:
    """Branch und geänderte Dateien – für die Farben im Explorer und die Statuszeile des Editors.

    Pfade gibt git relativ zum Repository an; der Workspace kann ein Unterordner davon sein.
    """
    def git(*args: str) -> str:
        return subprocess.run(["git", "-c", "core.quotepath=off", *args], cwd=str(ws), capture_output=True,
                              timeout=5, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout.decode(
                                  "utf-8", "replace")
    try:
        top = git("rev-parse", "--show-toplevel").strip()
        if not top:
            return {"repo": False}
        raw = git("status", "--porcelain=v1", "-b", "-z", "--untracked-files=all", "--", ".")
    except (OSError, subprocess.SubprocessError):
        return {"repo": False}
    root = Path(top).resolve()
    branch, ahead, behind, changed = "", 0, 0, {}
    parts = raw.split("\0")
    i = 0
    while i < len(parts):
        entry = parts[i]
        i += 1
        if not entry:
            continue
        if entry.startswith("## "):
            head = entry[3:]
            branch = head.split("...")[0].replace("No commits yet on ", "").strip()
            m = re.search(r"ahead (\d+)", head)
            ahead = int(m.group(1)) if m else 0
            m = re.search(r"behind (\d+)", head)
            behind = int(m.group(1)) if m else 0
            continue
        xy, path = entry[:2], entry[3:]
        if xy[0] in "RC":
            i += 1  # bei Umbenennungen folgt der alte Pfad als eigener Eintrag
        code = ("U" if xy == "??" else "C" if "U" in xy or xy in ("AA", "DD") else "A" if "A" in xy
                else "D" if "D" in xy else "R" if "R" in xy else "M")
        try:
            rel = (root / path).resolve().relative_to(ws).as_posix()
        except ValueError:
            continue
        changed[rel] = code
    return {"repo": True, "branch": branch, "ahead": ahead, "behind": behind, "files": changed}


def create_app(host: str = "127.0.0.1") -> FastAPI:
    runtime = Runtime()
    board = cowork.Board(runtime)  # die Cowork-Aufträge gehören dem Server, nicht einem Fenster
    runs: dict[str, Run] = {}  # laufende Aufträge je Chat – sie überleben ein Neuladen des Fensters
    share = Share()
    reports_by: dict[str, str] = {}  # Bericht → wessen Chat (users.owner_key)

    @asynccontextmanager
    async def lifespan(_app):
        # „Solange Coder offen ist“: Die Anforderung gehört der Event-Loop und wird dort auch wieder freigegeben.
        power.keep_awake.hold(runtime.cfg.get("keep_awake") == "open")
        yield
        power.keep_awake.hold(False)
        for run in list(runs.values()):
            run.release()
        for conn in list(share.conns):
            conn.stop_terminals()
        board.shutdown()
        tools.stop_background()
        await runtime.close()

    app = FastAPI(title="Coder", version=__version__, lifespan=lifespan)
    app.state.runtime = runtime  # für Tests und Werkzeuge, die von außen hineinsehen
    app.state.board = board
    app.state.runs = runs
    app.state.share = share

    def cfg_for(user: dict) -> dict:
        return users.user_config(runtime.cfg, user)

    def visible_config(user: dict) -> dict:
        """Was die Oberfläche von der Einstellung sieht. Gäste bekommen keine Adressen und Namen des Besitzers."""
        cfg = cfg_for(user)
        if users.is_admin(user):
            return cfg
        hidden = ("ollama_url", "vllm_url", "image_url", "speech_input", "report_author", "public_url")
        return {k: v for k, v in cfg.items() if k not in hidden}

    def me(request) -> dict:
        user = user_of(request)
        return {"name": user.get("name", ""), "role": user.get("role", ""), "local": is_local(request),
                "self": bool(user.get("self")), "modes": list(users.modes(user)),
                "role_label": users.ROLE_LABELS.get(user.get("role", ""), "")}

    def with_running(items: list[dict], owner: str) -> list[dict]:
        """Chats mit laufendem Auftrag bekommen ein Zeichen in der Liste – auch wenn gerade kein Fenster zusieht.

        Ein neuer Chat ist erst nach seinem ersten Auftrag gesichert; solange der läuft, steht er trotzdem oben.
        """
        busy = {sid: run for sid, run in runs.items()
                if run.busy and sessions.owner_of(run.session) == owner and not run.session.get("incognito")}
        out = [{**item, "running": True} if item["id"] in busy else item for item in items]
        known = {item["id"] for item in items}
        for sid, run in busy.items():
            s = run.session
            if sid not in known:  # auch ganz frisch: Der Auftrag läuft, die erste Nachricht kommt gleich dazu
                out.insert(0, {"id": sid, "title": s.get("title", ""), "updated": time.time(),
                               "workspace": s.get("workspace", ""), "model": s.get("model", ""),
                               "kind": sessions.kind_of(s), "owner": owner, "running": True})
        return out

    async def own_sessions(user: dict) -> list[dict]:
        """Die Chats eines Kontos. Gelesen wird in einem Thread: Ein großer Chat, der sich gerade geändert hat, muss
        neu eingelesen werden – das darf die laufenden Aufträge und Fenster nicht anhalten."""
        key = users.owner_key(user)
        items = with_running(await asyncio.to_thread(sessions.list_all, 200, key), key)
        if not users.at_least(user, "read"):
            items = [s for s in items if s.get("kind") == "talk"]
        return items

    def owned_session(session_id: str, user: dict) -> dict:
        live = runs.get(session_id)
        s = live.session if live else sessions.load(session_id)
        if not s or sessions.owner_of(s) != users.owner_key(user):
            raise HTTPException(404, "Chat nicht gefunden")  # fremde Chats gibt es für dich nicht – auch nicht als 403
        return s

    app.add_middleware(LocalGuard, public=host.strip("[]").lower() not in LOOPBACK, share=share)
    app.mount("/static", FreshStatic(directory=WEB), name="static")
    no_cache = {"Cache-Control": "no-store"}

    @app.get("/")
    async def index():
        return FileResponse(WEB / "index.html", headers=no_cache)

    # ------------------------------------------------------------------ Anmelden und Konten

    @app.get("/login")
    async def login_page(request: Request):
        return FileResponse(WEB / "login.html", headers=no_cache)

    def signed_in(request: Request, token: str, body: dict) -> JSONResponse:
        response = JSONResponse(body)
        response.set_cookie(COOKIE, token, max_age=users.TOKEN_DAYS * 86400, httponly=True, samesite="lax",
                            secure=bool(getattr(request.state, "secure", False)), path="/")
        return response

    @app.post("/api/login")
    async def login(request: Request, data: dict = Body(...)):
        try:
            token = await asyncio.to_thread(users.login, str(data.get("name") or ""), str(data.get("password") or ""))
        except users.UserError as e:
            raise HTTPException(401, str(e))
        return signed_in(request, token, {"ok": True})

    @app.get("/api/invite")
    async def invite_info(code: str = ""):
        user = users.invited(code)
        if not user:
            raise HTTPException(404, "Die Einladung gilt nicht mehr. Bitte um einen neuen Link.")
        return {"name": user["name"], "role": user["role"], "role_label": users.ROLE_LABELS[user["role"]],
                "min_password": users.MIN_PASSWORD}

    @app.post("/api/invite")
    async def invite_accept(request: Request, data: dict = Body(...)):
        try:
            token = await asyncio.to_thread(users.accept, str(data.get("code") or ""), str(data.get("password") or ""))
        except users.UserError as e:
            raise HTTPException(400, str(e))
        return signed_in(request, token, {"ok": True})

    @app.post("/api/logout")
    async def logout(request: Request):
        users.logout(request.cookies.get(COOKIE, ""))
        response = JSONResponse({"ok": True})
        response.delete_cookie(COOKIE, path="/")
        return response

    @app.get("/api/users")
    async def list_users(request: Request):
        need(request, "admin")
        return {"users": users.listing(), "roles": [{"id": r, "label": users.ROLE_LABELS[r],
                                                     "hint": users.ROLE_HINTS[r]} for r in users.ROLES],
                "url": share.url(runtime.cfg), "tunnel": share.tunnel, "online": share.online(),
                "public": host.strip("[]").lower() not in LOOPBACK}

    @app.post("/api/users")
    async def invite_user(request: Request, data: dict = Body(...)):
        need(request, "admin")
        try:
            user, code = users.invite(str(data.get("name") or ""), str(data.get("role") or "chat"),
                                      str(data.get("workspace") or ""), bool(data.get("self")))
        except users.UserError as e:
            raise HTTPException(400, str(e))
        return {"user": user, "code": code, "path": f"/login?invite={code}"}

    @app.post("/api/users/{name}/invite")
    async def reinvite_user(request: Request, name: str):
        need(request, "admin")
        try:
            code = users.reinvite(name)
        except users.UserError as e:
            raise HTTPException(404, str(e))
        for conn in list(share.conns):  # wer mit dem alten Passwort drin ist, fliegt raus
            if not conn.user.get("local") and users._key(conn.user.get("name", "")) == users._key(name):
                await conn.close_for("Dein Zugang wurde erneuert – bitte über den neuen Link anmelden.")
        return {"code": code, "path": f"/login?invite={code}"}

    @app.patch("/api/users/{name}")
    async def change_user(request: Request, name: str, data: dict = Body(...)):
        user = need(request, "admin")
        if not user.get("local") and users._key(user.get("name", "")) == users._key(name) and "role" in data \
                and data["role"] != "admin":
            raise HTTPException(400, "Die eigene Verwaltung gibt man nicht selbst ab.")
        changes = {k: data[k] for k in ("role", "workspace") if k in data}
        if changes.get("workspace"):
            ws = config_mod.normalize_path(str(changes["workspace"]))
            if not ws.is_dir() or config_mod.blocked_workspace(ws):
                raise HTTPException(400, f"{ws} geht nicht als Ordner.")
            changes["workspace"] = str(ws)
        try:
            return users.update(name, changes)
        except users.UserError as e:
            raise HTTPException(400, str(e))

    @app.delete("/api/users/{name}")
    async def delete_user(request: Request, name: str):
        user = need(request, "admin")
        if not user.get("local") and users._key(user.get("name", "")) == users._key(name):
            raise HTTPException(400, "Das eigene Konto löscht man am Rechner selbst.")
        try:
            users.remove(name)
        except users.UserError as e:
            raise HTTPException(404, str(e))
        for conn in list(share.conns):
            if not conn.user.get("local") and users._key(conn.user.get("name", "")) == users._key(name):
                await conn.close_for("Dieses Konto gibt es nicht mehr.")
        return {"ok": True}

    # ------------------------------------------------------------------ Zustand, Modelle, Einstellungen

    @app.get("/api/state")
    async def state(request: Request):
        user = user_of(request)
        return {
            "version": __version__,
            "native_picker": is_local(request),
            "config": visible_config(user),
            "me": me(request),
            "ollama": await runtime.status(),
            "hardware": await asyncio.to_thread(optimizer.detect_hardware),
            "loaded": await runtime.loaded(),
            "sessions": await own_sessions(user),
        }

    @app.get("/api/models")
    async def models(request: Request):
        need(request, "chat")
        try:
            return await runtime.models()
        except OllamaError as e:
            raise HTTPException(503, str(e))

    @app.post("/api/models/load")
    async def load_model(request: Request, model: str = Body(..., embed=True)):
        need(request, "admin")
        try:
            await runtime.update_config({"model": model})
            plan = await runtime.ensure_loaded(model, force=True)
            return {"model": model, "plan": plan, "loaded": await runtime.loaded()}
        except OllamaError as e:
            raise HTTPException(503, str(e))

    @app.post("/api/models/unload")
    async def unload_model(request: Request, model: str = Body(..., embed=True)):
        need(request, "admin")
        try:
            await runtime.client.unload(model)
            runtime.plans.pop(model, None)
            return {"loaded": await runtime.loaded()}
        except OllamaError as e:
            raise HTTPException(503, str(e))

    @app.get("/api/loaded")
    async def loaded():
        return {"loaded": await runtime.loaded(), "hardware": await asyncio.to_thread(optimizer.detect_hardware)}

    @app.post("/api/images")
    async def upload_image(data: str = Body(..., embed=True)):
        try:
            image_id = await asyncio.to_thread(vision.store_base64, data)
        except ValueError as e:
            raise HTTPException(400, str(e))
        return {"id": image_id, "url": f"/api/images/{image_id}"}

    @app.get("/api/reports/{name}")
    async def get_report(request: Request, name: str):
        """Den fertigen Bericht ausliefern – zum Ansehen und Drucken im Browser."""
        if not report.NAME_RX.match(name):
            raise HTTPException(400, "Ungültiger Name")
        user = user_of(request)
        if not user.get("local") and reports_by.get(name) != users.owner_key(user):
            raise HTTPException(404, "Bericht nicht gefunden")
        path = report.REPORTS_DIR / name
        if not path.is_file():
            raise HTTPException(404, "Bericht nicht gefunden")
        return FileResponse(path, media_type="text/html; charset=utf-8",
                            headers={"Cache-Control": "no-store"})

    @app.get("/api/imagegen")
    async def imagegen_status(request: Request, refresh: bool = False, url: str = ""):
        """Welcher Bilddienst gefunden wurde – für die Einstellungen.

        url prüft eine Adresse, bevor sie gesichert ist. Das darf nur, wer am Rechner selbst sitzt – sonst könnte
        ein Zugriff aus dem LAN den Server beliebige Adressen anfragen lassen.
        """
        need(request, "admin")
        cfg = runtime.cfg
        if url:
            if not is_local(request):
                raise HTTPException(403, "Eine eigene Adresse lässt sich nur am Rechner selbst prüfen.")
            cfg = {**cfg, "image_url": url, "image_backend": "auto"}
        found = await imagegen.detect(cfg, force=bool(refresh or url))
        if found:
            return {"backend": found, "hint": ""}
        # Nichts erreichbar: die Anleitung gleich mitliefern, samt einem Dienst, der nur nicht läuft.
        setup = await asyncio.to_thread(imagegen.setup, cfg)
        return {"backend": None, "hint": setup["hint"], "setup": setup}

    @app.get("/api/vllm")
    async def vllm_status(request: Request, refresh: bool = False, url: str = ""):
        """Läuft ein vLLM – und wenn nicht, wie startet man eins mit den Modellen, die schon da sind?"""
        need(request, "admin")
        cfg = runtime.cfg
        if url:
            if not is_local(request):
                raise HTTPException(403, "Eine eigene Adresse lässt sich nur am Rechner selbst prüfen.")
            cfg = {**cfg, "vllm_url": url}
        found = await vllm_mod.detect(cfg, force=bool(refresh or url))
        if found:
            return {"server": found, "hint": ""}
        setup = await asyncio.to_thread(vllm_mod.setup, cfg)
        return {"server": None, "hint": setup["hint"], "setup": setup}

    @app.get("/api/speech")
    async def speech_status(request: Request):
        """Was das Diktat kann – für die Einstellungen und den Mikrofon-Knopf.

        Aufgenommen wird am Rechner mit dem Server. Aus dem LAN oder über eine Portfreigabe wäre das ein fremdes
        Mikrofon, deshalb gibt es den Knopf dort nicht.
        """
        state = await asyncio.to_thread(speech.status, runtime.cfg)
        return {**state, "local": is_local(request), "enabled": bool(runtime.cfg.get("speech", True))}

    @app.get("/api/images/{image_id}")
    async def get_image(image_id: str):
        path = vision.path_of(image_id)
        if not path:
            raise HTTPException(404, "Bild nicht gefunden")
        return FileResponse(path, headers={"Cache-Control": "private, max-age=31536000, immutable"})

    @app.post("/api/config")
    async def set_config(request: Request, changes: dict = Body(...)):
        user = user_of(request)
        if not users.is_admin(user):
            # Gäste stellen nur für sich selbst etwas ein: Modus (im Rahmen ihrer Rolle), Aufwand, Aussehen.
            own = {k: v for k, v in changes.items() if k in users.OWN_PREFS}
            if len(own) != len(changes):
                raise HTTPException(403, ROLE_DENIED["admin"])
            if "permission_mode" in own and own["permission_mode"] not in users.modes(user):
                raise HTTPException(403, "Diesen Modus gibt dein Konto nicht her.")
            try:
                users.set_prefs(user["name"], own)
            except users.UserError as e:
                raise HTTPException(400, str(e))
            return visible_config(users.get(user["name"]) or user)
        if "workspace" in changes:
            raw = str(changes["workspace"] or "").strip()
            if not raw:
                raise HTTPException(400, "Bitte einen Ordner angeben.")
            ws = config_mod.normalize_path(raw)
            if not ws.is_dir():
                raise HTTPException(400, f"Ordner nicht gefunden: {ws}")
            reason = config_mod.blocked_workspace(ws)
            if reason:
                raise HTTPException(400, f"{ws} geht nicht als Workspace ({reason}). Wähle einen Projektordner.")
            changes["workspace"] = str(ws)
        cfg = await runtime.update_config(changes)
        power.keep_awake.hold(cfg.get("keep_awake") == "open")
        return cfg

    @app.get("/api/folders")
    async def browse_folders(request: Request, path: str = ""):
        need(request, "admin")  # zeigt die ganze Platte – nichts für Gäste
        return await asyncio.to_thread(folders.listing, path)

    @app.get("/api/folders/places")
    async def folder_places(request: Request):
        need(request, "admin")
        places, recent = await asyncio.gather(asyncio.to_thread(folders.places), asyncio.to_thread(folders.recent))
        return {"places": places, "recent": recent}

    @app.post("/api/folders/pick")
    async def pick_folder(request: Request, start: str = Body("", embed=True)):
        need(request, "admin")
        if not is_local(request):
            raise HTTPException(403, "Der Ordnerdialog öffnet sich nur auf dem Rechner, auf dem Coder läuft.")
        try:
            return {"path": await asyncio.to_thread(folders.pick, start)}
        except RuntimeError as e:
            raise HTTPException(501, str(e))

    def workspace_of(raw: str, user: dict | None = None) -> Path:
        """Agents und Befehle hängen vom Ordner des offenen Chats ab; Ungültiges fällt auf den Workspace zurück.

        Gäste arbeiten immer in dem Ordner, den der Besitzer ihnen gegeben hat – was sie schicken, zählt nicht.
        """
        if user is not None and not users.is_admin(user):
            return Path(cfg_for(user)["workspace"])
        ws = config_mod.normalize_path(raw) if raw.strip() else Path(runtime.cfg["workspace"])
        return ws if ws.is_dir() and not config_mod.blocked_workspace(ws) else Path(runtime.cfg["workspace"])

    # ------------------------------------------------------------------ Dateien im Workspace

    def inside(ws: Path, raw_path: str) -> Path:
        """Pfad im Workspace – alles außerhalb wird abgewiesen, auch über .. oder Verknüpfungen."""
        target = (ws / str(raw_path or "")).resolve()
        if target != ws and ws not in target.parents:
            raise HTTPException(400, "Nur Dateien im Workspace.")
        return target

    @app.get("/api/tree")
    async def file_tree(request: Request, path: str = "", workspace: str = ""):
        """Ein Ordner des Workspace: Unterordner zuerst, dann Dateien. Abhängigkeits- und Build-Ordner bleiben weg."""
        user = need(request, "read")
        ws = workspace_of(workspace, user).resolve()
        target = inside(ws, path)
        if not target.is_dir():
            raise HTTPException(404, "Ordner nicht gefunden")
        entries = []
        try:
            for entry in sorted(target.iterdir(), key=lambda e: (not e.is_dir(), e.name.lower())):
                name = entry.name
                is_dir = entry.is_dir()
                if is_dir and (name in tools.IGNORE_DIRS or (name.startswith(".") and name not in tools.HIDDEN_KEEP)):
                    continue
                try:
                    stat = entry.stat()
                except OSError:
                    continue
                entries.append({"name": name, "path": entry.relative_to(ws).as_posix(), "dir": is_dir,
                                "size": 0 if is_dir else stat.st_size, "mtime": stat.st_mtime})
        except OSError as e:
            raise HTTPException(400, str(e))
        return {"path": target.relative_to(ws).as_posix() if target != ws else "", "root": str(ws), "entries": entries}

    @app.get("/api/file")
    async def read_file(request: Request, path: str, workspace: str = ""):
        user = need(request, "read")
        ws = workspace_of(workspace, user).resolve()
        target = inside(ws, path)
        if not target.is_file():
            raise HTTPException(404, "Datei nicht gefunden")
        try:
            size = target.stat().st_size
            if size > MAX_FILE:
                raise HTTPException(413, f"Zu groß zum Anzeigen ({size // 1024} KB) – der Agent liest sie in Stücken.")
            text = await asyncio.to_thread(tools._read_text, target)
        except tools.ToolError as e:
            raise HTTPException(415, str(e))
        except OSError as e:
            raise HTTPException(400, str(e))
        return {"path": target.relative_to(ws).as_posix(), "text": text, "bytes": size,
                "lines": text.count("\n") + 1, "mtime": target.stat().st_mtime,
                "writable": users.at_least(user, "code")}

    @app.post("/api/file")
    async def save_file(request: Request, data: dict = Body(...)):
        """Speichert, was im Editor steht. Nur im Workspace, nur Text.

        mtime: Stand beim Öffnen. Hat sich die Datei seither geändert (Agent, ein zweiter Nutzer, ein anderes
        Programm), sagt der Server das, statt die fremde Änderung still zu überschreiben – außer mit force.
        """
        user = need(request, "code")
        ws = workspace_of(str(data.get("workspace") or ""), user).resolve()
        target = inside(ws, str(data.get("path") or ""))
        text = data.get("text")
        if not isinstance(text, str):
            raise HTTPException(400, "Kein Text zum Speichern.")
        if len(text.encode("utf-8")) > MAX_FILE:
            raise HTTPException(413, "Zu groß zum Speichern.")
        if target.is_dir():
            raise HTTPException(400, "Das ist ein Ordner.")
        seen = data.get("mtime")
        if isinstance(seen, (int, float)) and seen and target.is_file() and not data.get("force"):
            if abs(target.stat().st_mtime - float(seen)) > 0.001:
                raise HTTPException(409, "Die Datei wurde inzwischen woanders geändert.")
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            await asyncio.to_thread(tools._write_text, target, text)
        except OSError as e:
            raise HTTPException(400, f"Speichern ging nicht: {e}")
        return {"ok": True, "path": target.relative_to(ws).as_posix(), "bytes": target.stat().st_size,
                "mtime": target.stat().st_mtime}

    @app.get("/api/files")
    async def all_files(request: Request, workspace: str = ""):
        """Alle Dateien des Workspace als Pfade – für die Schnellsuche (Strg+P) im Editor."""
        user = need(request, "read")
        ws = workspace_of(workspace, user).resolve()
        paths = await asyncio.to_thread(lambda: [p.relative_to(ws).as_posix() for p in walk_files(ws)])
        return {"root": str(ws), "files": paths, "capped": len(paths) >= MAX_LIST}

    @app.get("/api/search")
    async def search(request: Request, q: str, workspace: str = "", regex: bool = False, case: bool = False):
        """Suche in Dateien (Strg+Umschalt+F im Editor)."""
        user = need(request, "read")
        if not q.strip() or len(q) > 500:
            raise HTTPException(400, "Wonach soll gesucht werden?")
        ws = workspace_of(workspace, user).resolve()
        return await asyncio.to_thread(search_files, ws, q, regex, case)

    @app.post("/api/fs")
    async def file_op(request: Request, data: dict = Body(...)):
        """Anlegen, Umbenennen, Löschen im Editor. Gelöschtes landet im Papierkorb von Coder, nicht im Nichts."""
        user = need(request, "code")
        ws = workspace_of(str(data.get("workspace") or ""), user).resolve()
        op = str(data.get("op") or "")
        target = inside(ws, str(data.get("path") or ""))
        if target == ws:
            raise HTTPException(400, "Der Workspace selbst bleibt, wo er ist.")
        rel = lambda p: p.relative_to(ws).as_posix()  # noqa: E731
        try:
            if op in ("file", "dir"):
                if target.exists():
                    raise HTTPException(409, f"{rel(target)} gibt es schon.")
                if op == "dir":
                    target.mkdir(parents=True)
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(b"")
                return {"ok": True, "path": rel(target)}
            if not target.exists():
                raise HTTPException(404, "Nicht gefunden.")
            if op == "rename":
                dest = inside(ws, str(data.get("to") or ""))
                if dest == ws or dest.exists():
                    raise HTTPException(409, f"{rel(dest) if dest != ws else '.'} gibt es schon.")
                dest.parent.mkdir(parents=True, exist_ok=True)
                target.rename(dest)
                return {"ok": True, "path": rel(dest), "from": rel(target)}
            if op == "delete":
                where = config_mod.HOME / "trash" / time.strftime("%Y%m%d-%H%M%S") / rel(target)
                where.parent.mkdir(parents=True, exist_ok=True)
                await asyncio.to_thread(shutil.move, str(target), str(where))
                return {"ok": True, "path": rel(target), "trash": str(where)}
        except OSError as e:
            raise HTTPException(400, str(e))
        raise HTTPException(400, "Unbekannte Aktion.")

    @app.get("/api/raw")
    async def raw_image(request: Request, path: str, workspace: str = ""):
        """Ein Bild aus dem Workspace für die Vorschau im Editor – nur Bilder, nichts anderes."""
        user = need(request, "read")
        ws = workspace_of(workspace, user).resolve()
        target = inside(ws, path)
        kind = IMAGE_TYPES.get(target.suffix.lower())
        if not kind or not target.is_file():
            raise HTTPException(404, "Kein Bild")
        if target.stat().st_size > MAX_IMAGE:
            raise HTTPException(413, "Zu groß für die Vorschau.")
        # SVG kann Skripte enthalten: nur als Bild ausliefern, nie als eigene Seite.
        return FileResponse(target, media_type=kind, headers={"Cache-Control": "no-store",
                                                              "Content-Security-Policy": "script-src 'none'; sandbox",
                                                              "X-Content-Type-Options": "nosniff"})

    @app.get("/api/git")
    async def git_info(request: Request, workspace: str = ""):
        user = need(request, "read")
        ws = workspace_of(workspace, user).resolve()
        return await asyncio.to_thread(git_status, ws)

    @app.get("/api/git/diff")
    async def git_diff(request: Request, path: str, workspace: str = ""):
        """Was sich an einer Datei seit dem letzten Commit geändert hat – für „Änderungen“ im Editor."""
        user = need(request, "read")
        ws = workspace_of(workspace, user).resolve()
        rel = inside(ws, path).relative_to(ws).as_posix()

        def run() -> dict:
            def git(*args: str) -> subprocess.CompletedProcess:
                return subprocess.run(["git", "-c", "core.quotepath=off", *args], cwd=str(ws), capture_output=True,
                                      timeout=10, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            try:
                if git("ls-files", "--error-unmatch", "--", rel).returncode != 0:
                    return {"diff": "", "untracked": True}
                done = git("diff", "--no-color", "--no-ext-diff", "HEAD", "--", rel)
                if done.returncode != 0:  # noch kein Commit: gegen den Index vergleichen
                    done = git("diff", "--no-color", "--no-ext-diff", "--", rel)
            except (OSError, subprocess.SubprocessError) as e:
                raise HTTPException(400, f"git ging nicht: {e}")
            text = done.stdout.decode("utf-8", "replace")
            return {"diff": text[:400_000], "capped": len(text) > 400_000, "untracked": False}

        return await asyncio.to_thread(run)

    @app.post("/api/complete")
    async def complete_code(request: Request, data: dict = Body(...)):
        """Der Vorschlag für die Stelle im Editor.

        Arbeitet der Agent gerade, bleibt es still: Die Anfrage stünde hinter seiner in der Schlange und wäre
        längst überholt, wenn sie an der Reihe wäre.
        """
        user = need(request, "code")
        if runtime.busy_agents:
            return {"text": "", "reason": "busy"}
        ws = workspace_of(str(data.get("workspace") or ""), user).resolve()
        path = str(data.get("path") or "")
        if path:
            inside(ws, path)  # nur Dateien im Workspace – der Pfad geht als Hinweis in den Prompt
        return await complete_mod.complete(
            runtime,
            prefix=str(data.get("prefix") or "")[-MAX_COMPLETE:],
            suffix=str(data.get("suffix") or "")[:MAX_COMPLETE],
            path=path, multiline=bool(data.get("multiline", True)))

    @app.get("/api/agents")
    async def list_agents(request: Request, workspace: str = ""):
        user = need(request, "read")
        include_claude = bool(runtime.cfg.get("claude_extensions", True))
        found = await asyncio.to_thread(agents.load, workspace_of(workspace, user), include_claude)
        return {"agents": [a.public() for a in found.values()], "tools": [t["name"] for t in tools.TOOLS]}

    @app.post("/api/agents")
    async def save_agent(request: Request, data: dict = Body(...)):
        need(request, "admin")
        try:
            return agents.save(data, workspace_of(str(data.get("workspace") or ""))).public()
        except (ValueError, OSError) as e:
            raise HTTPException(400, str(e))

    @app.delete("/api/agents/{scope}/{name}")
    async def delete_agent(request: Request, scope: str, name: str, workspace: str = ""):
        need(request, "admin")
        try:
            agents.delete(scope, name, workspace_of(workspace))
        except (ValueError, OSError) as e:
            raise HTTPException(400, str(e))
        return {"ok": True}

    # Das Gedächtnis gehört dem Besitzer: Gäste sehen seine Notizen nicht (users.user_config schaltet es für sie ab).

    @app.get("/api/memory")
    async def memory_overview(request: Request, workspace: str = ""):
        need(request, "admin")
        return await asyncio.to_thread(memory.overview, workspace_of(workspace))

    @app.get("/api/memory/note")
    async def memory_note(request: Request, title: str, workspace: str = "", vault: str = ""):
        need(request, "admin")
        try:
            return await asyncio.to_thread(memory.read, title, workspace_of(workspace), vault or None)
        except KeyError:
            raise HTTPException(404, f"Keine Notiz „{title}“")

    @app.post("/api/memory/note")
    async def memory_save(request: Request, data: dict = Body(...)):
        need(request, "admin")
        try:
            return await asyncio.to_thread(memory.save, data, workspace_of(str(data.get("workspace") or "")))
        except KeyError as e:
            raise HTTPException(404, f"Keine Notiz „{e.args[0]}“")
        except (ValueError, OSError) as e:
            raise HTTPException(400, str(e))

    @app.delete("/api/memory/note")
    async def memory_delete(request: Request, title: str, vault: str, workspace: str = ""):
        need(request, "admin")
        try:
            await asyncio.to_thread(memory.delete, title, workspace_of(workspace), vault)
        except (ValueError, OSError) as e:
            raise HTTPException(400, str(e))
        return {"ok": True}

    @app.get("/api/commands")
    async def list_commands(request: Request, workspace: str = ""):
        user = need(request, "chat")
        include_claude = bool(runtime.cfg.get("claude_extensions", True))
        found = await asyncio.to_thread(commands.load, workspace_of(workspace, user), include_claude)
        if not users.at_least(user, "read"):
            # Wer nur chatten darf, sieht nichts aus dem Projekt – nur die Prompts für den Tab Chat.
            found = [c for c in commands.for_tab(found, "talk") if c["source"] in ("builtin", "global")]
        return {"commands": found}

    # Eigene Prompts anlegen, ändern, löschen – Dateien wie bei Claude Code, deshalb nur für die Verwaltung.

    @app.post("/api/commands")
    async def save_command(request: Request, data: dict = Body(...)):
        need(request, "admin")
        try:
            return await asyncio.to_thread(commands.save, data, workspace_of(str(data.get("workspace") or "")))
        except (ValueError, OSError) as e:
            raise HTTPException(400, str(e))

    @app.delete("/api/commands/{scope}/{name}")
    async def delete_command(request: Request, scope: str, name: str, workspace: str = ""):
        need(request, "admin")
        try:
            await asyncio.to_thread(commands.delete, scope, name, workspace_of(workspace))
        except (ValueError, OSError) as e:
            raise HTTPException(400, str(e))
        return {"ok": True}

    @app.get("/api/sessions")
    async def list_sessions(request: Request):
        return await own_sessions(user_of(request))

    @app.get("/api/sessions/{session_id}")
    async def get_session(request: Request, session_id: str):
        return owned_session(session_id, user_of(request))

    @app.delete("/api/sessions/{session_id}")
    async def delete_session(request: Request, session_id: str):
        owned_session(session_id, user_of(request))
        run = runs.get(session_id)
        if run and run.busy:  # sonst sicherte der laufende Auftrag den Chat am Ende gleich wieder
            run.task.cancel()
            with suppress(asyncio.CancelledError, Exception):
                await asyncio.wait_for(asyncio.shield(run.task), 10)
        sessions.delete(session_id)
        await asyncio.to_thread(checkpoints.delete_session, session_id)
        return {"ok": True}

    @app.patch("/api/sessions/{session_id}")
    async def rename_session(request: Request, session_id: str, data: dict = Body(...)):
        """Einen Chat umbenennen – der Titel aus der ersten Nachricht trifft es nicht immer."""
        s = owned_session(session_id, user_of(request))
        title = " ".join(str(data.get("title") or "").split())[:80]
        if not title:
            raise HTTPException(400, "Ein Titel braucht mindestens ein Zeichen.")
        s["title"] = title
        if s.get("messages"):
            await asyncio.to_thread(sessions.save, s)
        for run in [r for r in runs.values() if r.session is s]:
            await run.emit({"type": "title", "id": session_id, "title": title})
        return {"ok": True, "title": title}

    @app.websocket("/ws")
    async def ws_endpoint(ws: WebSocket):
        await ws.accept()
        conn = Connection(ws, runtime, board, runs, user=user_of(ws), share=share, reports=reports_by)
        try:
            await conn.loop()
        except (WebSocketDisconnect, RuntimeError):
            # RuntimeError: Das Fenster ist gegangen, während gesendet wurde – dann ist die Leitung schon zu.
            pass
        finally:
            conn.shutdown()

    return app


class Run:
    """Ein laufender Auftrag – er gehört dem Chat, nicht dem Fenster.

    Lädt das Fenster neu oder reißt die Verbindung kurz ab (Handy im LAN, Bildschirm aus), arbeitet der Agent
    weiter. Wer den Chat wieder öffnet, hängt sich an: Er bekommt den Stand, offene Freigaben und Rückfragen
    noch einmal und sieht ab da jeden Schritt. Sieht niemand mehr zu, gilt eine offene Freigabe nach
    ORPHAN_SECONDS als abgelehnt – sonst hielte ein vergessener Tab die Grafikkarte und den Rechner wach.
    """

    ORPHAN_SECONDS = 15 * 60

    def __init__(self, session: dict):
        self.session = session
        self.task: asyncio.Task | None = None
        self.inbox: list[dict] = []  # Nachrichten, die der Agent vor seinem nächsten Schritt liest
        self.pending: dict[str, tuple[asyncio.Future, dict]] = {}  # offene Freigaben samt Anfrage
        self.questions: dict[str, tuple[asyncio.Future, dict]] = {}  # offene Rückfragen samt Anfrage
        self.loop_run: "loop_mod.Loop | None" = None
        self.listeners: list["Connection"] = []
        self.context: dict | None = None  # letzter Stand des Kontextrings – für wer sich später anhängt
        self.orphan: asyncio.Task | None = None

    @property
    def busy(self) -> bool:
        return bool(self.task and not self.task.done())

    async def emit(self, event: dict) -> None:
        if event.get("type") == "context" and not event.get("parent"):
            self.context = event
        if event.get("type") in ("tool_result", "stats") and not event.get("parent"):
            sessions.autosave(self.session)  # ein Absturz mitten im Auftrag kostet nicht den ganzen Verlauf
        for conn in list(self.listeners):
            await conn.send(event)

    def attach(self, conn: "Connection") -> None:
        if conn not in self.listeners:
            self.listeners.append(conn)
        if self.orphan and not self.orphan.done():
            self.orphan.cancel()
        self.orphan = None

    def detach(self, conn: "Connection") -> None:
        if conn in self.listeners:
            self.listeners.remove(conn)
        if not self.listeners:
            # Wartende Nachrichten stehen im Fenster wieder in der Eingabe – hier würden sie sonst doppelt laufen.
            self.inbox.clear()
            self.watch_orphan()

    def watch_orphan(self) -> None:
        """Wartet eine Freigabe oder Rückfrage und niemand sieht zu: nach einer Weile ablehnen."""
        if self.listeners or not (self.pending or self.questions) or (self.orphan and not self.orphan.done()):
            return

        async def expire():
            await asyncio.sleep(self.ORPHAN_SECONDS)
            if self.listeners:
                return
            for fut, _ in list(self.pending.values()):
                if not fut.done():
                    fut.set_result("deny")
            for fut, _ in list(self.questions.values()):
                if not fut.done():
                    fut.set_result({"skipped": True})

        self.orphan = asyncio.create_task(expire())

    async def ask(self, request: dict) -> str:
        fut = asyncio.get_running_loop().create_future()
        self.pending[request["id"]] = (fut, request)
        await self.emit({"type": "permission", **request})
        self.watch_orphan()
        try:
            return await fut
        finally:
            self.pending.pop(request["id"], None)

    async def question(self, request: dict) -> dict:
        """Eine Rückfrage des Agenten: Die Oberfläche zeigt sie mit Antwortknöpfen, der Agent wartet auf die Antwort."""
        fut = asyncio.get_running_loop().create_future()
        self.questions[request["id"]] = (fut, request)
        await self.emit({"type": "question", **request})
        self.watch_orphan()
        try:
            return await fut
        finally:
            self.questions.pop(request["id"], None)

    async def replay(self, conn: "Connection") -> None:
        """Wer sich an einen laufenden Auftrag hängt, bekommt, was er für den Stand braucht."""
        if self.context:
            await conn.send(self.context)
        if self.loop_run:
            await conn.send({"type": "loop", "state": "round", **self.loop_run.public()})
        for _, request in list(self.pending.values()):
            await conn.send({"type": "permission", **request})
        for _, request in list(self.questions.values()):
            await conn.send({"type": "question", **request})

    def release(self) -> None:
        """Server geht zu: Wer noch wartet, bekommt eine Antwort, damit der Auftrag sauber endet."""
        for fut, _ in list(self.pending.values()):
            if not fut.done():
                fut.set_result("deny")
        for fut, _ in list(self.questions.values()):
            if not fut.done():
                fut.set_result({"skipped": True})
        if self.task and not self.task.done():
            self.task.cancel()
        if self.orphan and not self.orphan.done():
            self.orphan.cancel()


def last_answer(session: dict | None, since: int = 0) -> str:
    """Der letzte Text des Agenten – daran erkennt die Schleife, ob nichts mehr zu tun ist."""
    for m in reversed((session or {}).get("messages", [])[since:]):
        if m.get("role") == "assistant" and str(m.get("content") or "").strip():
            return str(m["content"])
    return ""


class UserRuntime:
    """Die Laufzeit, wie ein Gast sie sieht: derselbe Modell-Server, dieselbe Grafikkarte – aber seine Einstellung.

    Der Agent liest Modus, Aufwand und Ordner aus `rt.cfg`. Hier kommt dafür die Einstellung des Besitzers mit den
    eigenen Werten des Gastes darüber (users.user_config) – bei jedem Zugriff frisch, damit eine geänderte Rolle
    sofort gilt. Alles andere geht an die echte Laufzeit.
    """

    def __init__(self, rt: Runtime, name: str):
        self._rt = rt
        self._name = name

    @property
    def cfg(self) -> dict:
        return users.user_config(self._rt.cfg, users.get(self._name) or {"name": self._name, "role": "chat"})

    def __getattr__(self, name):
        return getattr(self._rt, name)


MAX_TERMS = 3             # so viele Befehle laufen je Fenster gleichzeitig im Editor-Terminal
MAX_TERM_OUTPUT = 4_000_000  # danach zeigt das Terminal nichts mehr an, der Befehl läuft aber weiter


class Connection:
    """Ein Browserfenster: ein offener Chat und dessen Auftrag (Run) – der läuft weiter, wenn das Fenster geht."""

    def __init__(self, ws: WebSocket, runtime: Runtime, board: "cowork.Board | None" = None,
                 runs: dict[str, Run] | None = None, user: dict | None = None, share: "Share | None" = None,
                 reports: dict[str, str] | None = None):
        self.ws = ws
        self.rt = runtime
        self.user = user or users.owner()
        # Der Besitzer arbeitet mit der echten Einstellung, Gäste mit ihrer eigenen Sicht darauf.
        self.art = runtime if (self.user.get("local") or self.user.get("self")) else UserRuntime(runtime, self.user["name"])
        self.board = board or cowork.Board(runtime)
        if users.is_admin(self.user):
            self.board.subscribe(self.send)  # was am Cowork-Brett passiert, sieht jedes Fenster, das es verwaltet
        self.runs = runs if runs is not None else {}  # alle Chats mit Fenster oder laufendem Auftrag
        self.share = share
        self.reports = reports if reports is not None else {}
        self.since = time.time()
        self.session: dict | None = None
        self.run: Run | None = None  # der Auftrag des offenen Chats – gibt es für jeden offenen Chat
        self.rec: "speech.Recorder | None" = None  # läuft gerade ein Diktat?
        self.rec_task: asyncio.Task | None = None  # schickt Pegel und Dauer, solange aufgenommen wird
        self.terms: dict[str, asyncio.subprocess.Process] = {}  # laufende Befehle im Editor-Terminal
        self._send_lock = asyncio.Lock()
        if share is not None:
            share.conns.append(self)
            asyncio.get_running_loop().create_task(share.announce())

    @property
    def owner(self) -> str:
        return users.owner_key(self.user)

    def may_open(self, s: dict | None) -> bool:
        """Eigene Chats ja, fremde nie – und Code-Chats nur, wer mehr als chatten darf."""
        return bool(s) and sessions.owner_of(s) == self.owner and (
            sessions.kind_of(s) == "talk" or users.at_least(self.user, "read"))

    async def close_for(self, message: str) -> None:
        """Konto gelöscht oder Zugang erneuert: Das Fenster erfährt es und die Leitung geht zu."""
        await self.send({"type": "auth", "state": "out", "message": message})
        with suppress(Exception):
            await self.ws.close(4401)

    @property
    def busy(self) -> bool:
        return bool(self.run and self.run.busy)

    @property
    def inbox(self) -> list[dict]:
        return self.run.inbox if self.run else []

    @property
    def loop_run(self) -> "loop_mod.Loop | None":
        return self.run.loop_run if self.run else None

    INCOGNITO_GRACE = 120  # so lange hält ein Inkognito-Chat eine gerissene Verbindung aus – nur im Speicher

    def _leave(self, gone: bool = False) -> None:
        """Den bisherigen Chat verlassen – läuft dort nichts mehr und sieht niemand zu, fällt er aus der Liste.

        gone: Das Fenster ist weg (Neuladen, Verbindung gerissen). Ein Inkognito-Chat steht nirgends auf der Platte;
        damit eine kurz gerissene Verbindung ihn nicht löscht, bleibt er dann noch einen Moment im Speicher.
        """
        run, self.run = self.run, None
        if run is None:
            return
        run.detach(self)
        sid = run.session["id"]
        if run.listeners or run.busy or self.runs.get(sid) is not run:
            return
        if not (gone and run.session.get("incognito")):
            self.runs.pop(sid, None)
            return

        async def drop() -> None:
            await asyncio.sleep(self.INCOGNITO_GRACE)
            if not run.listeners and not run.busy and self.runs.get(sid) is run:
                self.runs.pop(sid, None)

        with suppress(RuntimeError):
            asyncio.get_running_loop().create_task(drop())

    def _join(self, session: dict) -> Run:
        run = self.runs.get(session["id"])
        if run is None:
            run = self.runs[session["id"]] = Run(session)
        run.attach(self)
        self.run = run
        self.session = run.session
        return run

    async def send(self, event: dict) -> None:
        async with self._send_lock:
            try:
                await self.ws.send_json(event)
            except (TypeError, ValueError):
                log.error(traceback.format_exc())  # ein Ereignis, das sich nicht als JSON schreiben lässt: ein Fehler hier
            except Exception:  # noqa: BLE001 – Fenster zu: je nach Server RuntimeError, Disconnect oder ClosedResourceError
                pass

    async def loop(self) -> None:
        if users.is_admin(self.user):
            await self.send({"type": "cowork", "state": "board", **self.board.public()})
        while True:
            msg = await self.ws.receive_json()
            if not isinstance(msg, dict):
                continue
            kind = msg.get("type")
            if str(kind or "").startswith("cowork_") and not users.is_admin(self.user):
                await self.send({"type": "error", "message": "Cowork gehört dem, der Coder verwaltet."})
                continue
            if kind in ("send", "compact", "loop", "undo") and self.session is not None \
                    and sessions.kind_of(self.session) == "code" and not users.at_least(self.user, "read"):
                await self.send({"type": "error", "message": "Dein Konto darf nur den Chat benutzen."})
                continue
            if kind == "open":
                sid = str(msg.get("session_id") or "")
                live = self.runs.get(sid)  # läuft gerade: der lebende Stand, nicht der zuletzt gesicherte
                s = live.session if live else sessions.load(sid) if sid else None
                if s is not None and not self.may_open(s):
                    s = None  # fremder Chat: gibt es für dieses Fenster nicht
                await self.set_session(s, str(msg.get("kind") or ""), bool(msg.get("incognito")))
            elif kind == "new":
                await self.set_session(None, str(msg.get("kind") or ""), bool(msg.get("incognito")))
            elif kind == "term_start":
                await self.term_start(str(msg.get("id") or "")[:40], str(msg.get("command") or ""),
                                      str(msg.get("workspace") or ""))
            elif kind == "term_input":
                await self.term_input(str(msg.get("id") or ""), str(msg.get("text") or ""))
            elif kind == "term_stop":
                self.term_stop(str(msg.get("id") or ""))
            elif kind == "send":
                text = str(msg.get("text", ""))
                images = [str(i) for i in msg.get("images") or [] if isinstance(i, str)][:6]
                if self.busy:
                    await self.enqueue(text, msg.get("display"), msg.get("queue_id"), images)
                else:
                    await self.start(lambda run: self.run_agent(run, text, msg.get("display"), images))
            elif kind == "unqueue":
                await self.unqueue(str(msg.get("id") or ""))
            elif kind == "undo":
                await self.undo()
            elif kind == "compact":
                await self.start(self.run_compact)
            elif kind == "cancel":
                if self.loop_run:
                    self.loop_run.stop("user")
                if self.busy:
                    self.run.task.cancel()
            elif kind == "loop":
                await self.start_loop(str(msg.get("text") or ""))
            elif kind == "loop_stop":
                if self.loop_run:
                    self.loop_run.stop("user")
                    await self.run.emit({"type": "loop", "state": "stopping", **self.loop_run.public()})
                if self.busy:
                    self.run.task.cancel()
            elif kind == "sharpen":
                await self.sharpen(str(msg.get("text") or ""), str(msg.get("kind") or "auto"))
            elif kind == "report":
                await self.report(msg)
            elif kind == "permission":
                fut, _ = self.run.pending.get(str(msg.get("id") or ""), (None, None)) if self.run else (None, None)
                if fut and not fut.done():
                    decision = msg.get("decision")
                    fut.set_result(decision if decision in ("allow", "always", "deny") else "deny")
            elif kind == "speech_start":
                await self.speech_start()
            elif kind == "speech_stop":
                await self.speech_stop(keep=True)
            elif kind == "speech_cancel":
                await self.speech_stop(keep=False)
            elif kind == "speech_model":
                await self.speech_fetch(str(msg.get("model") or ""))
            elif kind == "cowork_add":
                await self.board.add(str(msg.get("text") or ""), mode=str(msg.get("mode") or "edit"),
                                     agent=str(msg.get("agent") or "")[:40],
                                     workspace=str(msg.get("workspace") or ""))
            elif kind == "cowork_stop":
                await self.board.stop(str(msg.get("id") or ""))
            elif kind == "cowork_remove":
                await self.board.remove(str(msg.get("id") or ""))
            elif kind == "cowork_retry":
                await self.board.retry(str(msg.get("id") or ""))
            elif kind == "cowork_clear":
                await self.board.clear()
            elif kind == "cowork_undo":
                await self.cowork_undo(str(msg.get("id") or ""))
            elif kind == "cowork_board":
                await self.send({"type": "cowork", "state": "board", **self.board.public()})
            elif kind == "answer":
                fut, _ = self.run.questions.get(str(msg.get("id") or ""), (None, None)) if self.run else (None, None)
                if fut and not fut.done():
                    choices = msg.get("choices") if isinstance(msg.get("choices"), list) else []
                    fut.set_result({"choices": [str(c)[:200] for c in choices[:10]],
                                    "text": str(msg.get("text") or "")[:2000], "skipped": bool(msg.get("skipped"))})

    async def set_session(self, s: dict | None, kind: str = "", incognito: bool = False) -> None:
        """kind gilt für einen neuen Chat: "talk" (Tab Chat) oder "code". Wer nur chatten darf, bekommt immer talk.

        Ein laufender Auftrag im bisherigen Chat arbeitet weiter – er gehört dem Chat, nicht dem Fenster (siehe Run).
        So kann man im Tab Chat reden, während der Agent im Tab Code arbeitet.
        """
        if kind != "talk" and not users.at_least(self.user, "read"):
            kind = "talk"
        self._leave()
        cfg = self.art.cfg
        run = self._join(s or sessions.new(cfg["workspace"], cfg.get("model", ""), owner=self.owner,
                                           kind="talk" if kind == "talk" else "code",
                                           incognito=incognito and kind == "talk"))
        # running: Der Chat hat einen laufenden Auftrag – die Oberfläche zeigt ihn als laufend statt als abgebrochen.
        await self.send({"type": "session", "session": self.session, "running": run.busy})
        if run.busy:
            await self.send({"type": "busy", "busy": True})
            await run.replay(self)

    async def start(self, work) -> None:
        """work(run) ist der Auftrag – er bekommt seinen Run fest mit, denn das Fenster kann jederzeit gehen."""
        if self.busy:
            await self.send({"type": "error", "message": "Der Agent arbeitet bereits."})
            return
        if self.session is None or self.run is None:
            await self.set_session(self.session, sessions.kind_of(self.session) if self.session else "")
        run = self.run

        async def job():
            try:
                await work(run)
            finally:
                if not run.listeners and self.runs.get(run.session["id"]) is run:
                    self.runs.pop(run.session["id"], None)  # fertig, und niemand hat den Chat offen

        run.task = asyncio.create_task(job())

    async def enqueue(self, text: str, display, queue_id, images: list[str]) -> None:
        """Während der Agent arbeitet, wartet eine neue Nachricht – er liest sie vor seinem nächsten Schritt."""
        item_id = str(queue_id or uuid.uuid4().hex[:10])[:40]
        problem = ("Bilder lassen sich erst anhängen, wenn der Agent fertig ist." if images
                   else "Es warten schon genug Nachrichten." if len(self.inbox) >= MAX_QUEUE
                   else "Die Nachricht ist leer." if not text.strip() else "")
        if problem:
            await self.send({"type": "queue_rejected", "id": item_id, "message": problem})
            return
        item = {"id": item_id, "text": text, "display": text if display is None else str(display)}
        self.inbox.append(item)
        await self.send({"type": "queued", "id": item_id, "text": item["display"]})

    async def unqueue(self, item_id: str) -> None:
        before = len(self.inbox)
        self.inbox[:] = [item for item in self.inbox if item["id"] != item_id]
        await self.send({"type": "unqueued", "id": item_id, "ok": len(self.inbox) < before})

    async def undo(self) -> None:
        if self.busy:
            await self.send({"type": "undo_failed", "message": "Erst den laufenden Auftrag stoppen, dann zurücknehmen."})
            return
        if self.session is None:
            await self.send({"type": "undo_failed", "message": "Es gibt keine Änderungen, die sich zurücknehmen lassen."})
            return
        try:
            result = await asyncio.to_thread(checkpoints.undo, self.session)
        except ValueError as e:
            await self.send({"type": "undo_failed", "message": str(e)})
            return
        sessions.save(self.session)
        await self.send({"type": "undone", **result})

    async def cowork_undo(self, task_id: str) -> None:
        """Zurücknehmen, was ein Auftrag geändert hat – jeder hat seine eigene Sicherung."""
        try:
            result = await self.board.undo(task_id)
        except ValueError as e:
            await self.send({"type": "cowork", "state": "undo", "id": task_id, "ok": False, "message": str(e)})
            return
        await self.send({"type": "cowork", "state": "undo", "id": task_id, "ok": True, **result})

    async def run_agent(self, run: Run, text: str, display: str | None = None,
                        images: list[str] | None = None) -> None:
        await self._guarded(run, lambda agent: agent.run(text, None if display is None else str(display), images))

    async def run_compact(self, run: Run) -> None:
        await self._guarded(run, lambda agent: agent.compact())

    async def _guarded(self, run: Run, action, questions: bool = True) -> str:
        """questions=False: niemand sitzt davor (Schleife) – dann gibt es keine Rückfragen.

        Alles geht an run.emit: an jedes Fenster, das den Chat gerade offen hat – auch an eines, das erst
        während der Arbeit dazukommt.
        """
        outcome = "done"
        session = run.session
        awake = self.rt.cfg.get("keep_awake") != "off"
        if awake:
            power.keep_awake.acquire()  # kein Standby mitten in einer langen Aufgabe
        self.rt.busy_agents += 1  # solange ergänzt die Dateiansicht nicht nebenher – die Grafikkarte ist belegt
        await run.emit({"type": "busy", "busy": True})
        try:
            while True:
                await action(Agent(self.art, session, run.emit, run.ask, inbox=run.inbox,
                                   question=run.question if questions else None))
                if not run.inbox:
                    break
                # Kam erst nach dem letzten Schritt an: wird der nächste Auftrag. Weitere liest der Agent unterwegs.
                item = run.inbox.pop(0)
                await run.emit({"type": "queued_taken", "id": item["id"], "text": item["display"]})
                action = (lambda text, shown: lambda agent: agent.run(text, shown))(item["text"], item["display"])
        except asyncio.CancelledError:
            outcome = "cancel"
            await run.emit({"type": "notice", "text": "Gestoppt."})
        except (OllamaError, AgentError) as e:
            outcome = "error"
            await run.emit({"type": "error", "message": str(e)})
        except Exception as e:  # noqa: BLE001
            outcome = "error"
            log.error(traceback.format_exc())
            await run.emit({"type": "error", "message": f"{e.__class__.__name__}: {e}"})
        finally:
            self.rt.busy_agents = max(0, self.rt.busy_agents - 1)
            if awake:
                power.keep_awake.release()
            dropped, run.inbox[:] = list(run.inbox), []
            if dropped:  # gestoppt oder gescheitert: die wartenden Texte gehen zurück in die Eingabe, nicht verloren
                await run.emit({"type": "queue_dropped", "items": dropped})
            if session.get("messages"):
                # Im Thread: Ein langer Chat ist schnell ein paar MB JSON – solange stünden sonst alle Fenster still.
                # Der Auftrag läuft bis hierher noch, also schreibt niemand gleichzeitig in den Verlauf.
                try:
                    await asyncio.shield(asyncio.to_thread(sessions.save, session))
                except asyncio.CancelledError:
                    pass  # zweimal gestoppt, während gesichert wird: Das Sichern läuft zu Ende, „done“ kommt trotzdem
            await run.emit({"type": "done", "session": {"id": session["id"], "title": session["title"],
                                                        "model": session.get("model")}})
        return outcome

    # ------------------------------------------------------------------ Schleife

    async def start_loop(self, text: str) -> None:
        if self.busy:
            await self.send({"type": "error", "message": "Der Agent arbeitet gerade. Erst stoppen."})
            return
        try:
            plan = loop_mod.parse(text)
        except loop_mod.LoopError as e:
            await self.send({"type": "error", "message": str(e)})
            return
        # /loop 3x /review: der Befehl wird wie beim Senden ausgeschrieben, sonst liest das Modell nur „/review“.
        workspace = (self.session or {}).get("workspace") or self.art.cfg["workspace"]
        plan.task, _ = await asyncio.to_thread(commands.resolve, plan.task, workspace,
                                               bool(self.rt.cfg.get("claude_extensions", True)))
        plan.display = f"/loop {text.strip()}"
        await self.start(lambda run: self.run_loop(run, plan))

    async def run_loop(self, run: Run, plan) -> None:
        """Denselben Auftrag Runde für Runde, bis er sitzt, die Runden alle sind oder gestoppt wird."""
        run.loop_run = plan
        try:
            while plan.running:
                mark = len(run.session["messages"])
                prompt = plan.prompt()
                await run.emit({"type": "loop", "state": "round", **plan.public()})
                shown = f"{plan.display} \u00b7 Runde {plan.round}"
                outcome = await self._guarded(run, lambda agent, t=prompt, s=shown: agent.run(t, s), questions=False)
                if outcome != "done":
                    plan.stop("user" if outcome == "cancel" else "error")
                    break
                plan.note(last_answer(run.session, mark))
                if not plan.running or not plan.every:
                    continue
                await run.emit({"type": "loop", "state": "waiting", **plan.public()})
                try:
                    await asyncio.sleep(plan.every)
                except asyncio.CancelledError:
                    plan.stop("user")
                    break
        finally:
            run.loop_run = None
            await run.emit({"type": "loop", "state": "end", "reason": plan.reason, **plan.public()})

    # ------------------------------------------------------------------ Diktat

    @property
    def local(self) -> bool:
        """Sitzt dieses Fenster am selben Rechner? Nur dann ist das Mikrofon hier das richtige."""
        return bool(getattr(self.ws.state, "local", False))  # LocalGuard: am Rechner und ohne Tunnel dazwischen

    async def speech_error(self, message: str, **extra) -> None:
        await self.send({"type": "speech", "state": "error", "message": message, **extra})

    async def speech_start(self) -> None:
        if not self.local:
            return await self.speech_error("Diktiert wird am Rechner, auf dem Coder läuft.")
        if not self.rt.cfg.get("speech", True):
            return await self.speech_error("Das Diktat ist in den Einstellungen abgeschaltet.")
        if self.rec and self.rec.active:
            return
        hindernis = await asyncio.to_thread(speech.blocked, self.rt.cfg)
        if hindernis:
            return await self.speech_error(hindernis)
        rec = speech.Recorder()
        try:
            await asyncio.to_thread(rec.start, speech.input_index(self.rt.cfg))
        except Exception as e:  # noqa: BLE001 – belegtes oder abgezogenes Mikrofon, fehlender Audiodienst
            return await self.speech_error(f"Das Mikrofon lässt sich nicht öffnen: {e}")
        self.rec = rec
        await self.send({"type": "speech", "state": "recording", "level": 0, "seconds": 0})
        self.rec_task = asyncio.create_task(self.speech_meter())

    async def speech_meter(self) -> None:
        """Pegel und Dauer, solange aufgenommen wird – daran sieht man, dass das Mikrofon wirklich hört."""
        try:
            while self.rec and self.rec.active:
                await asyncio.sleep(0.12)
                rec = self.rec
                if not (rec and rec.active):
                    return
                seconds = rec.seconds
                await self.send({"type": "speech", "state": "recording", "level": round(rec.level, 3),
                                 "seconds": round(seconds, 1)})
                if seconds >= speech.MAX_SECONDS:  # Notbremse, falls das Stoppen vergessen wurde
                    await self.speech_stop()
                    return
        except asyncio.CancelledError:
            pass

    def stop_meter(self) -> None:
        task, self.rec_task = self.rec_task, None
        if task and not task.done() and task is not asyncio.current_task():
            task.cancel()

    async def speech_stop(self, keep: bool = True) -> None:
        rec, self.rec = self.rec, None
        self.stop_meter()
        if rec is None:
            return
        audio = await asyncio.to_thread(rec.stop)
        if not keep:
            return await self.send({"type": "speech", "state": "idle"})
        if audio is None or len(audio) / speech.SAMPLE_RATE < speech.MIN_SECONDS:
            return await self.send({"type": "speech", "state": "idle", "message": "Das war zu kurz."})
        await self.send({"type": "speech", "state": "working", "seconds": round(len(audio) / speech.SAMPLE_RATE, 1)})
        try:
            result = await asyncio.to_thread(speech.transcribe, audio, self.rt.cfg)
        except Exception as e:  # noqa: BLE001 – Modell weg, Speicher voll, CUDA-Fehler
            log.error(traceback.format_exc())
            return await self.speech_error(f"Erkennen ging nicht: {e}")
        await self.send({"type": "speech", "state": "done", **result})

    async def speech_fetch(self, name: str) -> None:
        """Ein Erkennungsmodell holen – nur auf ausdrücklichen Wunsch, mit Fortschritt."""
        if not self.local:
            return await self.speech_error("Das Modell lädt der Rechner, auf dem Coder läuft.")
        if name not in speech.MODEL_NAMES:
            return await self.speech_error("Diese Größe gibt es nicht.")
        if speech.has("faster_whisper") is False:
            return await self.speech_error("faster-whisper fehlt noch.")
        loop = asyncio.get_running_loop()
        seen = [-1]

        def progress(done: int, total: int) -> None:
            share = int(100 * done / max(total, 1))
            if share <= seen[0]:  # nur echte Schritte melden, nicht jede halbe Sekunde
                return
            seen[0] = share
            asyncio.run_coroutine_threadsafe(
                self.send({"type": "speech", "state": "loading", "model": name, "done": done, "total": total}), loop)

        await self.send({"type": "speech", "state": "loading", "model": name, "done": 0, "total": 1})
        try:
            await asyncio.to_thread(speech.download, name, progress)
        except Exception as e:  # noqa: BLE001 – kein Netz, keine Platte, falscher Name
            return await self.speech_error(f"Das Modell kam nicht an: {e}")
        state = await asyncio.to_thread(speech.status, self.rt.cfg)
        await self.send({"type": "speech", "state": "ready", "model": name, "status": state})

    # ------------------------------------------------------------------ Schärfen und Drucken

    async def sharpen(self, text: str, kind: str) -> None:
        if self.busy:
            await self.send({"type": "sharpened", "ok": False,
                             "message": "Das geht, sobald der Agent fertig ist."})
            return
        workspace = (self.session or {}).get("workspace") or self.art.cfg["workspace"]
        try:
            sharp = await preprompt.sharpen(self.art, text, workspace=workspace, kind=kind)
        except (OllamaError, ValueError) as e:
            await self.send({"type": "sharpened", "ok": False, "message": str(e)})
            return
        except Exception as e:  # noqa: BLE001
            log.error(traceback.format_exc())
            await self.send({"type": "sharpened", "ok": False, "message": f"{e.__class__.__name__}: {e}"})
            return
        await self.send({"type": "sharpened", "ok": True, **sharp})

    async def report(self, msg: dict) -> None:
        if not self.session or not [m for m in self.session.get("messages") or [] if m.get("role") == "user"]:
            await self.send({"type": "report", "ok": False, "message": "In diesem Chat ist noch nichts passiert."})
            return
        if self.session.get("incognito"):
            await self.send({"type": "report", "ok": False,
                             "message": "Aus einem Inkognito-Chat entsteht keine Datei – kopier ihn stattdessen."})
            return
        fallback = self.rt.cfg.get("report_author") if self.user.get("local") or self.user.get("self") \
            else self.user.get("name")
        author = str(msg.get("author") or fallback or "")
        subject = str(msg.get("subject") or "")
        try:
            path = await asyncio.to_thread(report.save, self.session, None, author=author, subject=subject)
        except OSError as e:
            await self.send({"type": "report", "ok": False, "message": f"Bericht ging nicht: {e}"})
            return
        self.reports[path.name] = self.owner  # ausliefern nur an den, dem der Chat gehört
        await self.send({"type": "report", "ok": True, "name": path.name,
                         "url": f"/api/reports/{path.name}"})

    # ------------------------------------------------------------------ Terminal im Editor

    def term_workspace(self, raw: str) -> Path:
        cfg = self.art.cfg
        if raw.strip() and users.is_admin(self.user):
            ws = config_mod.normalize_path(raw)
            if ws.is_dir() and not config_mod.blocked_workspace(ws):
                return ws
        return Path(cfg["workspace"])

    async def term_start(self, term_id: str, command: str, workspace: str = "") -> None:
        """Ein Befehl im Terminal des Editors. Die Ausgabe kommt Stück für Stück, Eingaben gehen an stdin.

        Das ist ein echter Befehl auf diesem Rechner – deshalb nur für Konten, die auch Dateien ändern dürfen.
        """
        async def fail(message: str) -> None:
            await self.send({"type": "term", "id": term_id, "state": "error", "message": message})

        if not users.at_least(self.user, "code"):
            return await fail("Befehle darf dein Konto nicht ausführen.")
        if not term_id or not command.strip():
            return await fail("Kein Befehl.")
        if term_id in self.terms or len(self.terms) >= MAX_TERMS:
            return await fail(f"Es laufen schon {len(self.terms)} Befehle – erst einen beenden.")
        ws = self.term_workspace(workspace)
        argv, extra = tools._shell(command)
        try:
            proc = await asyncio.create_subprocess_exec(
                *argv, cwd=str(ws), stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT, env=tools._shell_env(PYTHONUNBUFFERED="1"), **extra)
        except OSError as e:
            return await fail(f"Starten ging nicht: {e}")
        self.terms[term_id] = proc
        await self.send({"type": "term", "id": term_id, "state": "start", "pid": proc.pid, "cwd": str(ws)})
        asyncio.create_task(self.term_pump(term_id, proc))

    async def term_pump(self, term_id: str, proc) -> None:
        decoder = codecs.getincrementaldecoder("utf-8")("replace")
        sent = 0
        try:
            while True:
                chunk = await proc.stdout.read(8192)
                if not chunk:
                    break
                text = decoder.decode(chunk).replace("\r\n", "\n")
                if not text or sent > MAX_TERM_OUTPUT:
                    continue
                sent += len(text)
                if sent > MAX_TERM_OUTPUT:
                    text += "\n… [Ausgabe gekürzt – der Befehl läuft weiter]\n"
                await self.send({"type": "term", "id": term_id, "data": text})
            code = await proc.wait()
        except asyncio.CancelledError:
            code = None
        finally:
            self.terms.pop(term_id, None)
        await self.send({"type": "term", "id": term_id, "state": "end", "code": code})

    async def term_input(self, term_id: str, text: str) -> None:
        proc = self.terms.get(term_id)
        if not proc or proc.stdin is None or proc.stdin.is_closing():
            return
        with suppress(OSError, RuntimeError, ConnectionError):
            proc.stdin.write(text.encode("utf-8"))
            await proc.stdin.drain()

    def term_stop(self, term_id: str) -> None:
        proc = self.terms.get(term_id)
        if proc and proc.returncode is None:
            tools._kill_tree(proc.pid)

    def stop_terminals(self) -> None:
        for term_id in list(self.terms):
            self.term_stop(term_id)

    def shutdown(self) -> None:
        """Fenster zu: Der Auftrag läuft weiter (siehe Run) – nur Mikrofon, Terminal und Leitung werden frei."""
        self.stop_terminals()  # ein Befehl ohne Fenster hätte niemanden mehr, der ihn sieht oder beendet
        if self.share is not None and self in self.share.conns:
            self.share.conns.remove(self)
            with suppress(RuntimeError):  # Server fährt gerade herunter
                asyncio.get_running_loop().create_task(self.share.announce())
        self.board.unsubscribe(self.send)
        if self.rec_task and not self.rec_task.done():
            self.rec_task.cancel()
        if self.rec:  # Fenster zu, Mikrofon frei – sonst bliebe die Aufnahme laufen
            self.rec.cancel()
            self.rec = None
        self._leave(gone=True)
