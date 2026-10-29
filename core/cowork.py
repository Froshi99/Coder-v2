"""Cowork: mehrere Aufträge gleichzeitig im selben Workspace.

Ein Brett voller Aufträge. Jeder bekommt einen eigenen Chat, einen eigenen Agenten und eine eigene Sicherung –
er lässt sich also einzeln zurücknehmen und hinterher im Chat weiterführen. Das Brett startet so viele
gleichzeitig, wie eingestellt sind, hält die übrigen in der Warteschlange und erzählt jedem offenen Fenster,
was gerade passiert.

Am Brett sitzt niemand, der Freigaben erteilt: Der Modus des Auftrags entscheidet vorher, was erlaubt ist –
*Planen* liest nur, *Dateien ändern* schreibt im Workspace und lehnt Befehle ab, *Alles* führt auch Befehle
aus. Rückfragen stellt der Agent hier nicht; er entscheidet selbst und schreibt es in seine Antwort.
"""

import asyncio
import time
import uuid
from pathlib import Path

from . import checkpoints, power, sessions
from .agent import Agent, AgentError
from .config import blocked_workspace
from .ollama import OllamaError

MAX_TASKS = 40   # so viele Aufträge hält das Brett – ältere fertige fallen hinten heraus
MAX_LOG = 30     # so viele Schritte je Auftrag stehen in der Ansicht
MAX_TEXT = 4000  # so lang darf ein Auftragstext sein
# Was ein Auftrag darf. „edit“ ist der Regelfall: Dateien ja, Befehle nein – dafür säße sonst jemand daneben.
MODES = {"plan": "plan", "edit": "auto-edit", "all": "yolo"}
MODE_LABELS = {"plan": "Planen", "edit": "Dateien ändern", "all": "Alles"}
# Was der Agent über seine Lage wissen muss: Hier sitzt niemand, der eine Freigabe erteilt oder eine Frage
# beantwortet. Beim Planen sagt der Agent sich das ohnehin selbst (core/agent.py), hier fehlt nur der Rest.
ALONE = "\n\n[Cowork: this task runs on its own - nobody can approve anything or answer a question. "
DECIDE = "Decide open questions yourself and say in your answer what you assumed.]"
NOTES = {
    "edit": ALONE + "You may read and change files in the workspace; run_command is not available to you, "
                    "so do not call it. " + DECIDE,
    "all": ALONE + "You may read, change files and run commands in the workspace. " + DECIDE,
    "plan": ALONE + "Decide open questions yourself and say in your plan what you assumed.]",
}
ACTIVE = ("queued", "running")


def last_answer(session: dict) -> str:
    """Der letzte Text des Agenten – das Ergebnis des Auftrags."""
    for m in reversed((session or {}).get("messages", [])):
        if m.get("role") == "assistant" and str(m.get("content") or "").strip():
            return str(m["content"])
    return ""


class Scoped:
    """Ein Laufzeit-Doppel mit eigener Einstellung: derselbe Server, dasselbe Modell – nur ein anderer Modus.

    Der Agent liest seinen Modus aus `rt.cfg`. Ein Cowork-Auftrag darf die Einstellung des Fensters aber nicht
    umstellen, also bekommt er hier seine eigene Kopie; alles andere geht an die echte Laufzeit.
    """

    def __init__(self, rt, cfg: dict):
        self._rt = rt
        self.cfg = cfg

    def __getattr__(self, name):
        return getattr(self._rt, name)


class Task:
    """Ein Auftrag auf dem Brett."""

    def __init__(self, text: str, *, mode: str = "edit", agent: str = "", workspace: str = "",
                 display: str | None = None):
        self.id = uuid.uuid4().hex[:10]
        self.text = text
        self.display = (display or text).strip()
        self.mode = mode if mode in MODES else "edit"
        self.agent = agent
        self.workspace = workspace
        self.status = "queued"
        self.created = time.time()
        self.started = 0.0
        self.ended = 0.0
        self.steps = 0
        self.activity = ""
        self.note = ""
        self.error = ""
        self.answer = ""
        self.model = ""
        self.session_id = ""
        self.files: list[dict] = []
        self.undone = False
        self.log: list[dict] = []
        self.job: asyncio.Task | None = None
        self.session: dict | None = None  # der Chat, solange der Auftrag läuft

    @property
    def title(self) -> str:
        return self.display.splitlines()[0][:80] if self.display.strip() else "Auftrag"

    def seconds(self) -> float:
        if not self.started:
            return 0.0
        return round((self.ended or time.time()) - self.started, 1)

    def public(self) -> dict:
        return {"id": self.id, "title": self.title, "text": self.display, "mode": self.mode, "agent": self.agent,
                "status": self.status, "steps": self.steps, "activity": self.activity, "note": self.note,
                "error": self.error, "answer": self.answer, "model": self.model, "session_id": self.session_id,
                "files": self.files, "undone": self.undone, "seconds": self.seconds(), "created": self.created,
                "log": self.log[-MAX_LOG:], "workspace": self.workspace}


class Board:
    """Alle Aufträge eines Rechners. Läuft im Server, nicht im Fenster – ein Neuladen stört die Arbeit nicht."""

    def __init__(self, runtime):
        self.rt = runtime
        self.tasks: dict[str, Task] = {}
        self.order: list[str] = []
        self.listeners: set = set()
        self._awake = False

    # ------------------------------------------------------------------ Zuhören

    def subscribe(self, listener) -> None:
        self.listeners.add(listener)

    def unsubscribe(self, listener) -> None:
        self.listeners.discard(listener)

    async def _tell(self, event: dict) -> None:
        for listener in list(self.listeners):
            try:
                await listener({"type": "cowork", **event})
            except Exception:  # noqa: BLE001 — ein totes Fenster hält das Brett nicht auf
                self.listeners.discard(listener)

    async def _task_changed(self, task: Task) -> None:
        await self._tell({"state": "task", "task": task.public(), "running": self.running, "queued": self.queued})

    async def broadcast(self) -> None:
        await self._tell({"state": "board", **self.public()})

    # ------------------------------------------------------------------ Bestand

    @property
    def parallel(self) -> int:
        try:
            return max(1, min(4, int(self.rt.cfg.get("cowork_parallel", 2))))
        except (TypeError, ValueError):
            return 2

    @property
    def running(self) -> int:
        return sum(1 for t in self.tasks.values() if t.status == "running")

    @property
    def queued(self) -> int:
        return sum(1 for t in self.tasks.values() if t.status == "queued")

    def public(self) -> dict:
        return {"tasks": [self.tasks[i].public() for i in self.order if i in self.tasks],
                "parallel": self.parallel, "running": self.running, "queued": self.queued}

    def _workspace(self, raw: str) -> str:
        """Der Ordner, in dem gearbeitet wird – Unsinniges fällt auf den eingestellten Workspace zurück."""
        candidate = str(raw or "").strip()
        if candidate and not blocked_workspace(candidate) and Path(candidate).is_dir():
            return candidate
        return str(self.rt.cfg["workspace"])

    def _prune(self) -> None:
        """Ältere erledigte Aufträge fallen heraus, wenn das Brett voll ist."""
        while len(self.order) > MAX_TASKS:
            for tid in list(self.order):
                if self.tasks.get(tid) and self.tasks[tid].status not in ACTIVE:
                    self.order.remove(tid)
                    self.tasks.pop(tid, None)
                    break
            else:
                return

    # ------------------------------------------------------------------ Aufträge

    async def add(self, text: str, *, mode: str = "edit", agent: str = "", workspace: str = "",
                  display: str | None = None) -> Task | None:
        text = str(text or "").strip()[:MAX_TEXT]
        if not text:
            await self._tell({"state": "rejected", "message": "Der Auftrag ist leer."})
            return None
        task = Task(text, mode=mode, agent=agent, workspace=self._workspace(workspace), display=display)
        self.tasks[task.id] = task
        self.order.append(task.id)
        self._prune()
        await self.broadcast()
        self.pump()
        return task

    async def stop(self, task_id: str) -> None:
        task = self.tasks.get(task_id)
        if not task:
            return
        if task.status == "queued":
            task.status = "stopped"
            task.ended = time.time()
            await self._task_changed(task)
            self.pump()
        elif task.status == "running" and task.job:
            task.job.cancel()

    async def remove(self, task_id: str) -> None:
        task = self.tasks.get(task_id)
        if not task:
            return
        if task.status in ACTIVE:
            await self.stop(task_id)
            return
        if task_id in self.order:
            self.order.remove(task_id)
        self.tasks.pop(task_id, None)
        await self.broadcast()

    async def retry(self, task_id: str) -> Task | None:
        task = self.tasks.get(task_id)
        if not task or task.status in ACTIVE:
            return None
        return await self.add(task.text, mode=task.mode, agent=task.agent, workspace=task.workspace,
                              display=task.display)

    async def undo(self, task_id: str) -> dict:
        """Nimmt zurück, was dieser Auftrag geändert hat – seine Sicherung gehört ihm allein."""
        task = self.tasks.get(task_id)
        if not task or not task.session_id:
            raise ValueError("Zu diesem Auftrag gibt es nichts zurückzunehmen.")
        if task.status in ACTIVE:
            raise ValueError("Der Auftrag läuft noch. Erst stoppen, dann zurücknehmen.")
        session = sessions.load(task.session_id)
        if session is None:
            raise ValueError("Den Chat dieses Auftrags gibt es nicht mehr.")
        result = await asyncio.to_thread(checkpoints.undo, session)
        sessions.save(session)
        task.undone = True
        await self._task_changed(task)
        return result

    async def clear(self) -> None:
        """Alles Erledigte vom Brett räumen; laufende Aufträge bleiben."""
        for tid in [i for i in self.order if self.tasks.get(i) and self.tasks[i].status not in ACTIVE]:
            self.order.remove(tid)
            self.tasks.pop(tid, None)
        await self.broadcast()

    async def stop_all(self) -> None:
        for tid in list(self.order):
            await self.stop(tid)

    # ------------------------------------------------------------------ Laufen lassen

    def pump(self) -> None:
        """Startet so viele wartende Aufträge, wie noch Plätze frei sind."""
        free = self.parallel - self.running
        for tid in self.order:
            if free <= 0:
                break
            task = self.tasks.get(tid)
            if task and task.status == "queued":
                task.status = "running"
                task.started = time.time()
                task.job = asyncio.create_task(self._run(task))
                free -= 1
        self._keep_awake()

    def _keep_awake(self) -> None:
        """Kein Standby, solange am Brett gearbeitet wird."""
        if self.rt.cfg.get("keep_awake") == "off":
            return
        want = self.running > 0
        if want and not self._awake:
            power.keep_awake.acquire()
            self._awake = True
        elif not want and self._awake:
            power.keep_awake.release()
            self._awake = False

    def scoped(self, task: Task):
        """Die Laufzeit, mit der dieser Auftrag arbeitet: eigener Modus, eigener Ordner."""
        cfg = dict(self.rt.cfg)
        cfg["permission_mode"] = MODES[task.mode]
        cfg["workspace"] = task.workspace
        cfg["unattended"] = True  # Befehle stehen im Modus „Dateien ändern“ gar nicht erst zur Wahl
        # Laufen mehrere gleichzeitig, prüft dasselbe Modell: Ein zweites würde das erste aus dem Speicher drängen.
        if self.parallel > 1 and cfg.get("model"):
            cfg["controller_model"] = cfg["model"]
        return Scoped(self.rt, cfg)

    async def _event(self, task: Task, ev: dict) -> None:
        """Aus dem Strom des Agenten wird die Zeile, die am Brett steht."""
        kind = ev.get("type")
        if kind == "tool_call":
            task.steps += 1
            task.activity = str(ev.get("summary") or ev.get("name") or "")
            task.log.append({"id": ev.get("id"), "name": ev.get("name"), "summary": task.activity, "ok": None})
            del task.log[:-MAX_LOG]
        elif kind == "tool_result":
            for entry in reversed(task.log):
                if entry.get("id") == ev.get("id"):
                    entry["ok"] = bool(ev.get("ok"))
                    break
            if task.session is not None and not ev.get("parent"):
                sessions.autosave(task.session)  # Coder geht mitten im Auftrag zu: der Chat dazu bleibt
        elif kind == "status":
            task.activity = str(ev.get("text") or "")
        elif kind == "assistant_start":
            task.activity = "schreibt …"
        elif kind == "model":
            task.model = str(ev.get("model") or "")
        elif kind == "changes":
            task.files = list(ev.get("files") or [])
            task.undone = False
        elif kind == "notice":
            task.note = str(ev.get("text") or "")
        elif kind == "error":
            task.error = str(ev.get("message") or "")
        else:
            return  # Textstücke, Messwerte, Kontext: am Brett steht das Ergebnis, nicht jeder Buchstabe
        await self._task_changed(task)

    async def _deny(self, request: dict) -> str:
        """Am Brett sitzt niemand: Was eine Freigabe bräuchte, findet nicht statt – der Auftrag läuft ohne weiter."""
        return "refuse"

    async def _run(self, task: Task) -> None:
        session = sessions.new(task.workspace, str(self.rt.cfg.get("model") or ""))
        session["title"] = task.title
        session["cowork"] = True
        task.session_id = session["id"]
        task.session = session
        text = (f"@{task.agent} {task.text}" if task.agent else task.text) + NOTES.get(task.mode, "")
        await self._task_changed(task)
        self.rt.busy_agents += 1  # solange ergänzt die Dateiansicht nicht nebenher – die Grafikkarte ist belegt
        try:
            agent = Agent(self.scoped(task), session, lambda ev: self._event(task, ev), self._deny, question=None)
            await agent.run(text, task.display)
            task.answer = last_answer(session)
            task.status = "done"
        except asyncio.CancelledError:
            task.status = "stopped"
            task.answer = last_answer(session)
            raise
        except (OllamaError, AgentError) as e:
            task.status = "failed"
            task.error = str(e)
        except Exception as e:  # noqa: BLE001 — ein Auftrag darf das Brett nicht mitreißen
            task.status = "failed"
            task.error = f"{e.__class__.__name__}: {e}"
        finally:
            self.rt.busy_agents = max(0, self.rt.busy_agents - 1)
            task.ended = time.time()
            task.activity = ""
            task.job = None
            task.session = None
            if session.get("messages"):
                try:
                    sessions.save(session)
                except OSError:
                    pass
            await self._task_changed(task)
            self.pump()
            await self.broadcast()

    def shutdown(self) -> None:
        for task in self.tasks.values():
            if task.job:
                task.job.cancel()
        if self._awake:
            power.keep_awake.release()
            self._awake = False
