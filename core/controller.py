"""Kontrolle: Ein zweites Modell – standardmäßig Mistral – schaut dem Agent über die Schulter.

Am Ende einer Aufgabe prüft es selbst nach (Dateien lesen, Tests laufen lassen) und schickt den Agent mit einer
konkreten Anweisung weiter, solange etwas fehlt. Bei langen Aufgaben sieht es zwischendurch nach dem Rechten und
hilft, wenn der Agent sich an fehlschlagenden Aufrufen festbeißt.
"""

import re
import time
import uuid

from . import agents as A
from . import effort

PREFERENCE = ("mistral-nemo", "mistral-small", "ministral", "magistral", "mistral", "devstral")
CHANGE_TOOLS = {"edit_file", "write_file", "run_command", "agent"}
FAIL_STREAK = 4
MAX_STEPS = 12
INTENT_RX = re.compile(r"\b(ich werde|werde ich|als nächstes|lass mich|jetzt (?:noch|werde|mache|prüfe|teste|erstelle)"
                       r"|i will|i'll|let me|next,? i)\b", re.I)
VERDICT_RX = re.compile(r"(?:VERDICT|URTEIL)\s*[:：]\s*\**\s*(DONE|CONTINUE|FERTIG|ERLEDIGT|WEITER)\b\**[ \t]*[-–—:]*[ \t]*(.*)",
                        re.I)

PROMPT = """You are the controller: a strict, practical quality gate watching another coding agent.
- Verify independently. Read the relevant files and run quick checks yourself: tests, a build, a linter, or the changed program. At most about six tool calls.
- Never modify files and never redo work that is clearly fine.
- Judge only what the user asked for. Unverified changes count as not done when a quick check is possible.
- If the agent needs something only the user can provide (a decision, credentials, hardware), count it as done.
End your reply with exactly one line:
VERDICT: DONE – <one short sentence for the user, in German>
or
VERDICT: CONTINUE – <concrete instruction for the agent, in German: what is missing or broken and what to do next>"""

SITUATION = {
    "end": "The agent says it is finished. Check whether the request is really complete and works.",
    "interval": "The agent is still working on a long task. Check whether it is on track. If it is, answer DONE.",
    "stuck": "The agent's last tool calls kept failing. Find the cause and tell it concretely how to get unstuck.",
}
CONTINUE_TEXT = ("[Controller check] The task is not finished yet: {note}\n"
                 "Continue working on it now. When everything is done and verified, summarize the result briefly.")
HINT_TEXT = "[Controller hint] {note}\nTake this into account and continue."
RETRY_VERDICT = ("Give your verdict now. End with exactly one line: VERDICT: DONE – … or VERDICT: CONTINUE – …")

PROFILE = A.AgentDef(name="kontrolle", description="Prüft, testet und hält die Arbeit am Laufen.", prompt=PROMPT,
                     tools=["read_file", "list_dir", "glob", "grep", "run_command"])


def enabled(agent) -> bool:
    """Geprüft wird, wo sich etwas ändern kann – nicht beim Planen, nicht im Chat, nicht auf Aufwand „Niedrig“."""
    cfg = agent.cfg
    return (effort.controller_on(cfg) and agent.parent is None and not agent.read_only
            and cfg.get("permission_mode") not in ("plan", "chat") and not getattr(agent, "talk", False))


def _turn(agent) -> list[dict]:
    return agent.s["messages"][agent.turn_start:]


def _calls(agent) -> list[dict]:
    return [c for m in _turn(agent) for c in m.get("_calls") or []]


def call_count(agent) -> int:
    """Werkzeugaufrufe dieser Aufgabe – ohne neue Aufrufe gibt es auch nichts Neues zu prüfen."""
    return len(_calls(agent))


def _final(agent) -> str:
    return next((m.get("content") or "" for m in reversed(_turn(agent)) if m["role"] == "assistant"), "")


def changed_files(agent) -> list[str]:
    return list(dict.fromkeys(str(c["args"].get("path")) for c in _calls(agent)
                              if c["name"] in ("edit_file", "write_file") and c["args"].get("path")))


def worked(agent) -> bool:
    return any(c["name"] in CHANGE_TOOLS for c in _calls(agent))


def due_at_end(agent) -> bool:
    if not enabled(agent) or agent.stopped or agent.continuations >= effort.controller_rounds(agent.cfg) + 1:
        return False
    if worked(agent) or any(t["status"] != "completed" for t in agent.ctx.todos):
        return True
    return bool(_calls(agent)) and bool(INTENT_RX.search(_final(agent)[-500:]))  # „Ich werde jetzt …“ – und Schluss


def due_while_working(agent) -> str | None:
    if not enabled(agent) or agent.reviews >= effort.controller_rounds(agent.cfg) + 3:
        return None
    if agent.fail_streak >= FAIL_STREAK:
        return "stuck"
    minutes = float(agent.cfg.get("controller_interval") or 0)
    if minutes and time.monotonic() - agent.review_at >= minutes * 60:
        return "interval"
    return None


def observation(agent, reason: str) -> str:
    turn = _turn(agent)
    first = turn[0] if turn else {}
    request = first.get("_text") or first.get("content") or ""
    later = [m.get("_text") or m.get("content") or "" for m in turn[1:] if m["role"] == "user" and m.get("_queued")]
    if later:  # während der Arbeit nachgeschoben – gehört genauso zum Auftrag
        request += "\n\nLater messages from the user:\n" + "\n".join(f"- {text[:600]}" for text in later)
    results = {m.get("_id"): m for m in turn if m["role"] == "tool"}
    steps = []
    for m in turn:
        if m.get("_controller") and m["role"] == "user":
            steps.append(f"- [your earlier instruction] {m['content'].splitlines()[0][:300]}")
        for c in m.get("_calls") or []:
            r = results.get(c["id"])
            status = "no result" if r is None else "ok" if r.get("_ok") else "FAILED"
            line = f"- {c['name']} {agent.summarize(c['name'], c['args'])[:160]} → {status}"
            # Befehle mit Ausgabe, Rückfragen mit der Antwort des Nutzers – die gehört zum Auftrag dazu.
            if r is not None and (c["name"] in ("run_command", "ask_user") or not r.get("_ok")):
                tail = (r.get("content") or "").strip()[-400:]
                if tail:
                    line += "\n    " + tail.replace("\n", "\n    ")
            steps.append(line)
    todos = "\n".join(f"- [{t['status']}] {t['content']}" for t in agent.ctx.todos) or "- none"
    final = _final(agent).strip()
    return (f"# Situation\n{SITUATION[reason]}\n\n# Workspace\n{agent.ctx.workspace}\n\n"
            f"# User request\n{request[:3000]}\n\n# Agent steps in this task\n{chr(10).join(steps[-40:]) or '- none'}\n\n"
            f"# Todo list\n{todos}\n\n# Agent's latest message\n{final[-2500:] or '(none)'}")


def parse(report: str) -> tuple[str, str]:
    matches = list(VERDICT_RX.finditer(report or ""))
    if not matches:
        return "unclear", A.clip(A.squash(report or ""), 400)
    match = matches[-1]  # das letzte Urteil zählt
    note = match.group(2).replace("*", "").strip()
    if not note:  # Anweisung erst in der nächsten Zeile
        rest = report[match.end():].strip()
        note = rest.splitlines()[0] if rest else ""
    word = match.group(1).upper()
    return ("continue" if word in ("CONTINUE", "WEITER") else "done"), A.clip(A.squash(note.replace("*", "")), 700)


async def review(agent, reason: str) -> dict:
    """Lässt das Kontrollmodell prüfen. Ergebnis: {"verdict": done|continue|unclear|error|stopped, "note", …}."""
    from .agent import Agent, AgentError  # zirkulärer Import
    from .ollama import OllamaError

    main = await agent.model_name()
    model = await agent.rt.controller_model(main) if hasattr(agent.rt, "controller_model") else main
    cid = "ctl" + uuid.uuid4().hex[:8]
    agent.reviews += 1
    agent.review_at = time.monotonic()
    agent.fail_streak = 0
    if model != main:
        agent.side_model_used = True
    await agent.emit({"type": "controller", "state": "start", "id": cid, "model": model, "reason": reason})

    steps: dict[str, dict] = {}

    async def emit(ev: dict) -> None:
        if ev.get("type") == "tool_call":
            steps[ev["id"]] = {"id": ev["id"], "name": ev["name"], "summary": ev["summary"], "args": ev["args"]}
        elif ev.get("type") == "tool_result" and ev["id"] in steps:
            steps[ev["id"]].update(ok=ev["ok"], output=ev["output"][:1500], display=ev["display"])
        await agent.emit({**ev, "parent": cid, "agent": "kontrolle"})

    async def ask(request: dict) -> str:
        return await agent.ask({**request, "agent": "kontrolle"})

    session = {"id": cid, "title": "Kontrolle", "workspace": agent.s["workspace"], "messages": [], "todos": [],
               "allow": agent.s.setdefault("allow", [])}
    sub = Agent(agent.rt, session, emit, ask, profile=PROFILE, parent=agent, model=model, steps=MAX_STEPS)
    started = time.perf_counter()
    report = ""
    try:
        await sub.run(observation(agent, reason))
        report = sub.last_answer()
        verdict, note = parse(report)
        if verdict == "unclear" and not sub.stopped:
            await sub.run(RETRY_VERDICT)
            report = sub.last_answer() or report
            verdict, note = parse(report)
    except (OllamaError, AgentError) as e:
        verdict, note = "error", str(e)
    if sub.stopped:
        verdict, note = "stopped", "Du hast eine Prüfung abgelehnt – die Kontrolle hält sich raus."
    display = {"id": cid, "model": model, "reason": reason, "verdict": verdict, "note": note,
               "report": A.clip(report, 4000), "steps": list(steps.values()),
               "seconds": round(time.perf_counter() - started, 1), "round": agent.reviews}
    agent.s["messages"].append({"role": "event", "_ui": True, "_controller": display})
    await agent.emit({"type": "controller", "state": "done", **display})
    return display


def inject(agent, display: dict, hint: bool = False) -> None:
    text = (HINT_TEXT if hint else CONTINUE_TEXT).format(note=display["note"])
    agent.s["messages"].append({"role": "user", "content": text, "_controller": display["id"]})
    if not hint:
        agent.continuations += 1
