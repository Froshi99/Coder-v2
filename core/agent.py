"""Agent-Schleife: Modell denkt, ruft Werkzeuge auf, bekommt Ergebnisse — bis die Aufgabe erledigt ist."""

import asyncio
import base64
import contextlib
import json
import platform
import re
import time
import uuid
from pathlib import Path
from typing import Awaitable, Callable

import httpx

from . import agents as A
from . import checkpoints, controller, effort, imagegen, memory, optimizer, personal, recall, vision
from . import tools as T
from .config import blocked_workspace
from .ollama import OllamaError

Emit = Callable[[dict], Awaitable[None]]
Ask = Callable[[dict], Awaitable[str]]  # -> "allow" | "always" | "deny" | "refuse" (niemand da, der freigibt)
# Rückfrage an den Nutzer: {question, options, multiple, …} -> {"choices": [...], "text": "...", "skipped": bool}
Question = Callable[[dict], Awaitable[dict]]

PROJECT_FILES = ("CODER.md", "AGENTS.md", "CLAUDE.md")
TOOL_CALL_RX = re.compile(r"<tool_call>\s*(\{.*?\})\s*</tool_call>", re.S)
FENCE_RX = re.compile(r"```[ \t]*(?:json|tool_call|tool|javascript|js)?[ \t]*\r?\n(.*?)```", re.S | re.I)
ANY_FENCE_RX = re.compile(r"```.*?(?:```|\Z)", re.S)
# Qwen3-Coder: <function=glob><parameter=pattern>**/*.kts</parameter></function> – oft ohne öffnendes <tool_call>
XML_CALL_RX = re.compile(r"(?:<tool_call>\s*)?<function=([^>\s]+)>(.*?)</function>(?:\s*</tool_call>)?", re.S)
XML_PARAM_RX = re.compile(r"<parameter=([^>\s]+)>(.*?)</parameter>", re.S)
JSON_START_RX = re.compile(r"(?m)^[ \t]*([\[{])")
CALL_KEYS = {"name", "tool", "tool_name", "arguments", "parameters", "args", "input", "type", "id"}
MENTION_RX = re.compile(r"^\s*@([A-Za-z0-9][\w-]{0,39})(?![\w-])")
CHARS_PER_TOKEN = 3.3
SUBAGENT_STEPS = 30
OVERVIEW_ENTRIES = 60
# Befehle, die Dateien ändern – für Agents ohne Schreibwerkzeuge gesperrt. Grob, fängt aber die üblichen Fälle ab.
MUTATING_RX = re.compile(
    r"(?:^|[;&|(]\s*|\s)(?:touch|new-item|ni|set-content|add-content|out-file|remove-item|rm|del|erase|rmdir|rd"
    r"|move-item|mv|move|copy-item|cp|copy|rename-item|ren|mkdir|md)(?=\s|$)"
    r"|\bgit\s+(?:commit|push|reset|checkout|apply|stash|clean|rebase|merge|add|rm|mv)\b"
    r"|\bsed\s+-i\b|(?:^|[^2&>])>{1,2}\s*[^&\s>]", re.I)
NUDGE_MAIN = "You stopped without an answer. Briefly tell the user the result of your work so far."
NUDGE_SUB = ("You stopped without a final answer. Write your final report for the main agent now: findings or changes "
             "with file paths and line numbers. Do not call more tools unless strictly necessary.")
NUDGE_REPEAT = "You started repeating the same text over and over. Stop that and continue with the next concrete step."
NUDGE_INTENT = ("You announced a next step but did not take it. If you need a tool for it, call the tool now. "
                "Otherwise give your final answer.")
# „… lese ich zuerst die Datei.“ – und Schluss: kleine Modelle kündigen gern an, statt aufzurufen.
INTENT_TAIL_RX = re.compile(r"\b(?:ich werde|werde ich|lass mich|lese ich|schaue ich|prüfe ich|suche ich|sehe ich mir"
                            r"|ich (?:lese|schaue|prüfe|suche) (?:jetzt|zuerst|mal)|let me|i will|i'll)\b", re.I)
REPEAT_PROBE = 80
REPEAT_MIN = 8
GPU_BUSY = 5  # Prozent Auslastung, ab denen ein stilles Modell als „rechnet noch“ gilt
QUESTION_LIMIT = 4  # Rückfragen je Auftrag – danach entscheidet der Agent selbst
MENTION_CHARS = 12_000  # so viel von genannten Dateien liest der Chat gleich mit
CHAT_KINDS = ("read", "web", "memory")  # was der Chat-Modus darf: lesen, nachschlagen, sich merken
CHAT_DENIED = ("Chat mode is active: you cannot change files, run commands or generate images here. Answer in text. "
               "If the user wants changes, tell them to switch to the mode \"Normal\".")
# Der Tab Chat: reden und recherchieren, ohne Projekt – nur das Netz und (beim Besitzer) das Gedächtnis.
TALK_TOOLS = ("web_search", "web_fetch", "web_research")
TALK_DENIED = ("This chat has no access to files, commands or the computer – only web research. Answer in text. "
               "For work on a project the user can open the Code tab.")
UNATTENDED_DENIED = ("This action needs the user's approval, but nobody can approve anything in this task. It was "
                     "not executed. Continue without it and say in your final answer what is left for the user to do.")
NO_QUESTIONS = ("Asking the user is not possible right now (autonomous mode or unattended loop). Decide yourself "
                "with a sensible default and mention your assumption briefly.")

# Bewusst ohne Uhrzeit o. ä.: ein stabiler Prompt-Anfang lässt Ollama den
# KV-Cache zwischen den Schritten wiederverwenden — spart Sekunden pro Schritt.
SYSTEM_PROMPT = """You are Coder, an autonomous coding agent running fully locally. You solve software engineering tasks in the user's workspace by calling tools.

# Environment
- Workspace: {workspace}
- Top level of the workspace: {overview}
- OS: {os}. run_command runs {shell} on the user's machine.

# Capabilities
- Terminal: run_command executes real commands. Run commands yourself instead of asking the user to run them.
- Internet: web_search finds pages, web_fetch reads them. web_research searches several queries, reads the best pages and returns excerpts with numbered sources in one step – use it for questions that need more than one source. Never claim you have no internet access.
- Images: images the user attaches are part of their message. view_image looks at image files in the workspace, such as screenshots.
- Long-running processes such as dev servers or watchers: run_command with background=true, then read the log file it reports.

# How to work
- Explore before changing anything: use glob, grep and read_file. Never guess file contents.
- Always read_file before edit_file. old_string must match exactly, including indentation.
- Prefer edit_file for changes to existing files; use write_file for new files.
- For tasks with three or more steps, maintain a todo list with todo_write and update statuses as you progress.
- After making changes, verify them: run tests, a build, or the program with run_command when possible.
- If a tool fails, read the error and change your approach. Never repeat an identical failing call.
- The user may send more messages while you work. Take them into account at your next step.
- Do not ask for permission in text; the app asks the user automatically before risky actions.
- Be concise. No long preambles. When finished, summarize what you changed in one to three sentences.
- Reply in the language the user writes in. In German, address the user informally with "du", never "Sie".
{extra}"""

CHAT_SYSTEM_PROMPT = """You are Coder in chat mode: a knowledgeable assistant running fully locally. Talk with the user, answer questions, explain code and concepts, brainstorm and review ideas.

# Environment
- Workspace: {workspace}
- Top level of the workspace: {overview}
- OS: {os}

# What you can do in chat mode
- Look things up when it helps the answer: read_file, list_dir, glob and grep read the workspace; web_search, web_fetch and web_research read the internet; memory_search and memory_read read your notes. Never claim you have no internet access.
- You cannot change files, run commands or generate images in chat mode. Never claim that you changed, created or saved anything – you only show changes.
- If the user asks for a change to their project: read the relevant files first, then show the concrete change for exactly their code as a code block, and end with one sentence saying that you can apply it yourself in the mode "Normal" (mode switch at the top right in the app, Shift+Tab in the terminal).

# How to answer
- Questions about the user's project, a file or an error in it: read the files yourself with read_file, glob or grep before you answer. Never ask the user to paste file contents – you can read them.
- General questions (concepts, languages, tools) you answer from your knowledge, without tools.
- Answer directly, without long preambles. Use Markdown: short paragraphs, lists, code blocks with a language.
- If the question is ambiguous, ask a short counter-question in your reply.
- Reply in the language the user writes in. In German, address the user informally with "du", never "Sie".
{extra}"""

TALK_SYSTEM_PROMPT = """You are the chat assistant in Coder: a friendly, knowledgeable conversation partner running fully locally. This chat is separate from any coding project – talk about anything the user brings up: questions, ideas, advice, shopping and style, travel, learning, writing, everyday life.

# Research
- web_search finds pages, web_fetch reads one page, web_research searches several queries and reads the best pages in one step, with numbered sources. Use them whenever the answer depends on current facts, prices, products, availability, reviews, sizes or anything you are not sure about. Never claim you have no internet access.
- A list of search results is only the start. Open the most promising pages with web_fetch (or use web_research) and take the concrete facts from there before you answer. Do not tell the user to search themselves while you can still look.
- For shopping and product questions, deliver concrete results: product name, shop, price, available sizes and the direct link. Compare several options in a small Markdown table. If a page does not show a price or size, say so for that item instead of dropping the link.
- Every link you know from a tool result is usable – never claim you cannot give links. Write links as Markdown links with the full URL.
- End every researched answer with "Quellen:" and a numbered list of the pages you used, each as a Markdown link with its full URL; inline citations [n] must match that list. Say plainly when sources disagree or something could not be verified.

# How to answer
- Answer directly and warmly, without long preambles. Use Markdown: short paragraphs, lists, tables for comparisons.
- If the request is too vague to answer well (budget, size, taste, purpose), ask one short counter-question in your reply – or answer with a sensible assumption and name it.
- Respect the user's identity, body and style choices without judgement or moralizing; give practical, specific advice.
- You have no access to the user's files or projects here and cannot change anything on the computer.
- Reply in the language the user writes in. In German, address the user informally with "du", never "Sie".
{extra}"""

QUESTION_PROMPT = """
# Asking the user
- ask_user asks the user a question with answer options and waits for the reply. Use it when a decision really belongs to the user and changes the result: two reasonable approaches, a missing essential detail (a name, a target, a format), or a consequential choice such as deleting data or adding a dependency.
- Explore first: never ask what you can find out yourself with read_file, glob or grep, and never ask for permission – the app does that.
- Offer 2-4 short, concrete options, the recommended one first. One question at a time and only a few per task; for small details make a sensible assumption and mention it instead.
"""

TEXT_TOOLS_PROMPT = """
# Tools
Call a tool by writing exactly this block, then stop and wait for the result:
<tool_call>{{"name": "read_file", "arguments": {{"path": "main.py"}}}}</tool_call>
You may write several blocks in one reply. Results arrive as <tool_result> messages.
Available tools:
{tools}
"""

DELEGATION_PROMPT = """
# Sub-agents
The agent tool hands a self-contained part of the work to a specialist with its own context: searching a large codebase, reviewing code for bugs, running tests, researching online. Write a complete task description, because the specialist cannot see this conversation. Do small, quick steps yourself.
"""

ROLE_PROMPT = """
# Your role: {name}
{prompt}
"""

MEMORY_PROMPT = """
# Memory
You have a persistent vault of linked Markdown notes (like Obsidian) that survives across chats.
- Notes that match the user's message are attached to it automatically. When a topic may have more history, use memory_search and memory_read.
- Save durable knowledge with memory_write: user preferences, project conventions, decisions and their reasons, hard-won fixes. One topic per note, short and factual. Link related notes with [[Title]] and add #tags. Update an existing note instead of creating a duplicate.
- Finished tasks may be logged automatically in the note "Verlauf" – no need to write that yourself.
- The library holds read-only guides. For UI or design work, read "Design-Prinzipien" and "Kein AI-Slop" first.
- Never store secrets such as passwords, tokens or API keys.
{notes}
"""

IMAGE_PROMPT = """
# Generating images
generate_image paints an image from a description with {label} and saves it in the workspace: app icons, logos, textures, placeholder photos, backgrounds, Open-Graph images. Write the prompt in English and name subject, style, colours, background and lighting – short prompts give generic results. It cannot write readable text or reproduce an exact logo, and for icons or diagrams that must scale crisply, hand-written SVG is the better tool. Only generate an image when the user asked for a picture; never as decoration on your own initiative.
"""

NO_IMAGE_PROMPT = """
# Images
You cannot generate images: no local image service is running. If the user asks for a picture, say so in one sentence and mention that Coder paints with ComfyUI or a Stable Diffusion WebUI, to be set under Settings → "Bilder erzeugen".
"""

SUBAGENT_PROMPT = """
# Working as a sub-agent
- The main agent gave you exactly one task. The user does not see your messages; only your final reply is passed back.
- Work autonomously and never ask questions. If something is unclear, make a sensible assumption and mention it.
- Finish with a concise report: findings or changes with file paths and line numbers, plus anything left open.
"""


class StopTurn(Exception):
    pass


class AgentError(RuntimeError):
    """Ein Problem, das der Nutzer selbst beheben kann – wird ohne Traceback angezeigt."""


class ModelStalled(Exception):
    """Das Modell liefert nichts mehr und rechnet auch nicht – der Watchdog lädt es neu."""


class ModelRepeating(Exception):
    """Das Modell wiederholt denselben Text in Schleife."""


def wire_messages(messages: list[dict], native: bool, images: bool = False) -> list[dict]:
    """Entfernt UI-Metadaten und übersetzt bei Bedarf ins Text-Tool-Protokoll.

    images: das Modell sieht selbst – angehängte Bilder gehen dann direkt mit.
    """
    out = []
    for m in messages:
        if m.get("_hidden") or m.get("_ui"):
            continue
        msg = {k: v for k, v in m.items() if not k.startswith("_")}
        if not native and msg["role"] == "tool":
            msg = {"role": "user",
                   "content": f'<tool_result name="{m.get("_name", "")}">\n{msg["content"]}\n</tool_result>'}
        if images and m.get("_images") and not m.get("_vision"):
            encoded = []
            for image_id in m["_images"]:
                path = vision.path_of(image_id)
                with contextlib.suppress(OSError, ValueError):
                    if path:
                        encoded.append(vision.encode(path))
            if encoded:
                msg["images"] = encoded
        out.append(msg)
    return out


def _call_shape(data, names: set[str] | None) -> list[dict] | None:
    """Sieht das JSON wie ein oder mehrere Werkzeugaufrufe aus? Dann im Ollama-Format – sonst None."""
    items = data if isinstance(data, list) else [data]
    calls = []
    for item in items:
        if not isinstance(item, dict):
            return None
        fn = item["function"] if isinstance(item.get("function"), dict) else item
        if set(fn) - CALL_KEYS or (fn is not item and set(item) - CALL_KEYS - {"function"}):
            return None  # weitere Schlüssel: eher Daten als ein Aufruf
        name = fn.get("name") or fn.get("tool") or fn.get("tool_name")
        args = next((fn[key] for key in ("arguments", "parameters", "args", "input") if key in fn), {})
        if isinstance(args, str):
            try:
                args = json.loads(args) if args.strip() else {}
            except ValueError:
                return None
        if not isinstance(name, str) or not isinstance(args, dict) or (names is not None and name not in names):
            return None
        calls.append({"function": {"name": name, "arguments": args}})
    return calls or None


def _xml_value(raw: str) -> str:
    """Parameterwert im Qwen-Format: je ein Zeilenumbruch vorn und hinten gehört zum Format, nicht zum Wert."""
    value = raw[1:] if raw.startswith("\n") else raw
    value = value[:-1] if value.endswith("\n") else value
    return value if "\n" in value else value.strip()


def _decode_sequence(body: str, names: set[str]) -> list[dict] | None:
    """Ein Codeblock zählt nur, wenn er ausschließlich aus Aufrufen besteht."""
    decoder, pos, calls = json.JSONDecoder(), 0, []
    while True:
        while pos < len(body) and body[pos] in " \t\r\n,":
            pos += 1
        if pos >= len(body):
            return calls or None
        try:
            data, pos = decoder.raw_decode(body, pos)
        except ValueError:
            return None
        shape = _call_shape(data, names)
        if not shape:
            return None
        calls += shape


def parse_text_calls(content: str, names: set[str] | None = None) -> tuple[list[dict], str]:
    """Werkzeugaufrufe, die ein Modell als Text schreibt – und der Text ohne sie.

    Erkennt <tool_call>{…}</tool_call> (das Text-Protokoll von Coder) und, nur für bekannte Werkzeugnamen, reines JSON
    wie {"name": "read_file", "arguments": {…}}, auch in ```json-Blöcken. Qwen2.5-Coder antwortet über Ollama oft so,
    obwohl es natives Tool-Calling beherrscht.
    """
    text = content or ""
    calls, spans = [], []
    for match in TOOL_CALL_RX.finditer(text):
        try:
            data = json.loads(match.group(1))
        except ValueError:
            continue
        if isinstance(data, dict) and data.get("name"):
            calls.append({"function": {"name": data["name"], "arguments": data.get("arguments") or {}}})
            spans.append(match.span())
    if not calls:
        for match in XML_CALL_RX.finditer(text):
            args = {p.group(1): _xml_value(p.group(2)) for p in XML_PARAM_RX.finditer(match.group(2))}
            calls.append({"function": {"name": match.group(1).strip(), "arguments": args}})
            spans.append(match.span())
        if calls:  # übrig gebliebene Tags eines halben Aufrufs nicht im Text stehen lassen
            text = re.sub(r"</?tool_call>", lambda m: " " * len(m.group(0)), text)
    if not calls and names:
        for match in FENCE_RX.finditer(text):
            found = _decode_sequence(match.group(1), names)
            if found:
                calls += found
                spans.append(match.span())
        if not calls:
            # JSON in anderen Codeblöcken ist Beispiel oder Daten – nie ein Aufruf.
            fenced = [m.span() for m in ANY_FENCE_RX.finditer(text)]
            decoder, pos = json.JSONDecoder(), 0
            for match in JSON_START_RX.finditer(text):
                start = match.start(1)
                if start < pos or any(a <= start < b for a, b in fenced):
                    continue
                try:
                    data, end = decoder.raw_decode(text, start)
                except ValueError:
                    continue
                shape = _call_shape(data, names)
                if shape:
                    calls += shape
                    spans.append((start, end))
                    pos = end
    if not spans:
        return calls, text
    kept, last = [], 0
    for start, end in sorted(spans):
        kept.append(text[last:start])
        last = end
    kept.append(text[last:])
    return calls, re.sub(r"\n{3,}", "\n\n", "".join(kept)).strip()


def _ui_args(args: dict) -> dict:
    return {k: (v[:2000] + " …" if isinstance(v, str) and len(v) > 2000 else v) for k, v in args.items()}


def repeating(text: str) -> bool:
    """Kleine Modelle verfangen sich gern in immer demselben Absatz."""
    if len(text) < REPEAT_PROBE * REPEAT_MIN:
        return False
    probe = text[-REPEAT_PROBE:]
    return len(set(probe)) > 8 and text[-REPEAT_PROBE * 40:].count(probe) >= REPEAT_MIN


def clean_answer(reply, item: dict) -> dict:
    """Die Antwort aus der Oberfläche prüfen: nur angebotene Antworten, freier Text gekürzt, sonst übersprungen."""
    reply = reply if isinstance(reply, dict) else {}
    labels = {o["label"].lower(): o["label"] for o in item.get("options") or []}
    choices = []
    for raw in reply.get("choices") or []:
        label = labels.get(str(raw).strip().lower())
        if label and label not in choices:
            choices.append(label)
    if not item.get("multiple"):
        choices = choices[:1]
    text = str(reply.get("text") or "").strip()[:2000]
    skipped = bool(reply.get("skipped")) or not (choices or text)
    return {"choices": [] if skipped else choices, "text": "" if skipped else text, "skipped": skipped}


def trim_repeat(text: str) -> str:
    probe = text[-REPEAT_PROBE:]
    first = text.find(probe)
    second = text.find(probe, first + 1)
    return (text[:second] if second > 0 else text).rstrip() + " …"


class Agent:
    def __init__(self, runtime, session: dict, emit: Emit, ask: Ask, *,
                 profile: "A.AgentDef | None" = None, parent: "Agent | None" = None,
                 model: str | None = None, steps: int | None = None, inbox: list | None = None,
                 question: Question | None = None):
        self.rt = runtime
        self.s = session
        self.emit = emit
        self.ask = ask
        self.question = question  # None: niemand da, der antworten könnte (Sub-Agent, Schleife, Test)
        self.asked = 0
        self.profile = profile  # Rolle: als Sub-Agent gestartet oder per @name angesprochen
        self.parent = parent
        self.model_override = model  # die Kontrolle läuft auf ihrem eigenen Modell
        self.steps_override = steps
        self.inbox = inbox if inbox is not None else []  # Nachrichten, die während der Arbeit eintreffen
        self.stopped = False  # der Nutzer hat eine Aktion abgelehnt
        self.hit_limit = False
        self._agents: dict[str, A.AgentDef] | None = None
        if parent is None and not any(m.get("role") == "user" for m in session.get("messages", [])):
            session["workspace"] = runtime.cfg["workspace"]  # ein leerer Chat folgt dem gerade gewählten Ordner
        self.ctx = T.ToolContext(
            workspace=Path(session["workspace"]),
            max_output=int(runtime.cfg["max_tool_output"]),
            command_timeout=int(runtime.cfg["command_timeout"]),
            todos=session.setdefault("todos", []),
            runtime=runtime,
        )
        self._recent: list[str] = []
        self._system: dict[bool, str] = {}
        self.image_backend: dict | None = None  # der gefundene Bilddienst; None heißt: generate_image gibt es nicht
        # Kontrolle
        self.turn_start = 0
        self.reviews = 0
        self.continuations = 0
        self.fail_streak = 0
        self.review_at = time.monotonic()
        self.side_model_used = False

    @property
    def cfg(self) -> dict:
        if self.s.get("incognito"):
            # Inkognito: nichts erinnern, nichts festhalten – auch keine Notizen, die den Chat überleben würden.
            return {**self.rt.cfg, "memory": False, "auto_recall": False, "journal": False}
        return self.rt.cfg

    # ------------------------------------------------------------------ Agents & Werkzeuge

    def available_agents(self) -> dict[str, "A.AgentDef"]:
        if self._agents is None:
            self._agents = A.load(self.ctx.workspace, include_claude=bool(self.cfg.get("claude_extensions", True)))
        return self._agents

    @property
    def mode(self) -> str:
        return str(self.cfg.get("permission_mode") or "ask")

    @property
    def talk(self) -> bool:
        """Ein Chat aus dem Tab Chat: reden und recherchieren, ohne Projekt, Dateien und Befehle."""
        return self.parent is None and self.s.get("kind") == "talk"

    @property
    def chat(self) -> bool:
        """Chat-Modus: reden, erklären, nachschlagen – nichts ändern. Sub-Agents gibt es darin nicht."""
        return self.parent is None and (self.mode == "chat" or self.talk)

    @property
    def can_ask(self) -> bool:
        """Rückfragen gehen nur, wenn jemand antworten kann – und nicht im Modus Autonom („ohne Rückfrage“)."""
        return (self.question is not None and self.parent is None and self.mode not in ("chat", "yolo")
                and not self.talk)

    @property
    def can_delegate(self) -> bool:
        return (self.parent is None and self.profile is None and not self.chat
                and bool(self.cfg.get("subagents", True)))

    @property
    def read_only(self) -> bool:
        """Rollen ohne Schreibwerkzeuge dürfen auch über das Terminal nichts ändern."""
        return bool(self.profile) and not any(self.profile.allows(t)
                                              for t in ("edit_file", "write_file", "generate_image"))

    def tool_defs(self) -> list[dict]:
        memory_on = bool(self.cfg.get("memory", True))
        defs = []
        for t in T.TOOLS:
            if t["name"] == "ask_user":  # hängt an der Situation, nicht an der Rolle
                if self.can_ask:
                    defs.append(t)
                continue
            if ((self.profile is None or self.profile.allows(t["name"]))
                    and (memory_on or t["kind"] != "memory")
                    and (self.image_backend or t["name"] != "generate_image")
                    and (not self.chat or t["kind"] in CHAT_KINDS)
                    and (not self.talk or t["name"] in TALK_TOOLS or t["kind"] == "memory")
                    and not (self.cfg.get("unattended") and self.mode == "auto-edit" and t["kind"] == "exec")):
                defs.append(t)
        if self.can_delegate and self.available_agents():
            defs.append(A.tool_schema(self.available_agents()))
        return defs

    def schemas(self) -> list[dict]:
        return [{"type": "function", "function": {k: t[k] for k in ("name", "description", "parameters")}}
                for t in self.tool_defs()]

    @staticmethod
    def kind(name: str) -> str:
        return "agent" if name == "agent" else T.kind(name)

    @staticmethod
    def summarize(name: str, args: dict) -> str:
        if name == "agent":
            task = " ".join(str(args.get("task") or "").split())
            return f"{args.get('agent') or '?'} · {task[:160]}"
        return T.summarize(name, args)

    def mentioned_agent(self, text: str) -> "A.AgentDef | None":
        match = MENTION_RX.match(text or "")
        return self.available_agents().get(match.group(1).lower()) if match else None

    def last_answer(self) -> str:
        return next((m["content"].strip() for m in reversed(self.s["messages"])
                     if m["role"] == "assistant" and (m.get("content") or "").strip()), "")

    # ------------------------------------------------------------------ Prompt

    def overview(self) -> str:
        """Die oberste Ebene des Workspace – spart dem Modell den ersten list_dir-Aufruf und ändert sich selten."""
        entries = []
        try:
            for entry in self.ctx.workspace.iterdir():
                try:
                    entries.append((not entry.is_dir(), entry.name))
                except OSError:
                    continue
        except OSError:
            return "(not readable)"
        names = [name + ("" if is_file else "/") for is_file, name in sorted(entries, key=lambda e: (e[0], e[1].lower()))
                 if is_file or not (name in T.IGNORE_DIRS or (name.startswith(".") and name not in T.HIDDEN_KEEP))]
        text = ", ".join(names[:OVERVIEW_ENTRIES]) or "(empty)"
        if len(names) > OVERVIEW_ENTRIES:
            text += f", … {len(names) - OVERVIEW_ENTRIES} more"
        if (self.ctx.workspace / ".git").exists():
            text += " (git repository)"
        return text

    def system_prompt(self, native: bool) -> str:
        if native not in self._system and self.talk:
            self._system[native] = TALK_SYSTEM_PROMPT.format(extra=self.talk_extra(native))
        if native not in self._system:
            extra = ""
            for name in PROJECT_FILES:
                p = self.ctx.workspace / name
                if p.is_file():
                    text = p.read_text("utf-8", errors="replace")[:6000]
                    extra += f"\n# Project instructions ({name})\n{text}\n"
                    break
            if self.profile:
                extra += ROLE_PROMPT.format(name=self.profile.name, prompt=self.profile.prompt[:8000])
            if self.parent:
                extra += SUBAGENT_PROMPT
            elif self.can_delegate and self.available_agents():
                extra += DELEGATION_PROMPT
            if self.parent is None and self.cfg.get("memory", True):
                extra += MEMORY_PROMPT.format(notes=memory.context(self.ctx.workspace))
            if self.chat:
                pass  # malen gehört zu den Änderungen – der Chat-Prompt sagt schon, wohin man dafür wechselt
            elif self.image_backend:
                extra += IMAGE_PROMPT.format(label=self.image_backend["label"])
            elif self.parent is None and str(self.cfg.get("image_backend") or "auto") != "off":
                extra += NO_IMAGE_PROMPT
            if self.can_ask:
                extra += QUESTION_PROMPT
            if not (self.profile and self.profile.name == "kontrolle"):  # die Kontrolle hat ihr eigenes Maß
                extra += effort.prompt(self.cfg, chat=self.chat)
            if self.parent is None:  # eigene Anweisungen und Stil: nur wer mit dem Nutzer redet
                extra += personal.prompt(self.cfg, "code")
            if not native:
                lines = []
                for t in self.tool_defs():
                    props = t["parameters"]["properties"]
                    req = t["parameters"]["required"]
                    params = ", ".join(f"{k}{'' if k in req else '?'}: {v.get('type', 'any')}" for k, v in props.items())
                    lines.append(f"- {t['name']}({params}): {t['description']}")
                extra += TEXT_TOOLS_PROMPT.format(tools="\n".join(lines))
            shell = "PowerShell" if T.IS_WINDOWS else "bash"
            self._system[native] = (CHAT_SYSTEM_PROMPT if self.chat else SYSTEM_PROMPT).format(
                workspace=self.ctx.workspace, overview=self.overview(), os=f"{platform.system()} {platform.release()}",
                shell=shell, extra=extra)
        return self._system[native]

    def tool_lines(self) -> str:
        lines = []
        for t in self.tool_defs():
            props = t["parameters"]["properties"]
            req = t["parameters"]["required"]
            params = ", ".join(f"{k}{'' if k in req else '?'}: {v.get('type', 'any')}" for k, v in props.items())
            lines.append(f"- {t['name']}({params}): {t['description']}")
        return "\n".join(lines)

    def talk_extra(self, native: bool) -> str:
        """Was im Chat-Tab zum Prompt dazukommt: Gedächtnis, Aufwand und – ohne natives Tool-Calling – die Werkzeuge."""
        extra = ""
        if self.cfg.get("memory", True):
            extra += MEMORY_PROMPT.format(notes=memory.context(self.ctx.workspace))
        extra += effort.prompt(self.cfg, chat=True)
        extra += personal.prompt(self.cfg, "talk")
        if not native:
            extra += TEXT_TOOLS_PROMPT.format(tools=self.tool_lines())
        return extra

    # ------------------------------------------------------------------ Modell

    async def talk_model(self) -> str:
        """Der Chat-Tab darf ein eigenes Modell haben – ein Allrounder redet oft besser als ein Code-Modell."""
        want = str(self.cfg.get("talk_model") or "")
        if not want:
            return ""
        installed = await self.rt.installed()
        return want if not installed or want in installed else ""

    async def model_name(self) -> str:
        model = (self.model_override or await self.agent_model() or (self.talk and await self.talk_model())
                 or self.cfg.get("model"))
        if not model:
            model = await self.rt.recommended_model()
            if not model:
                raise OllamaError("Kein Chat-Modell installiert. Beispiel: ollama pull qwen3-coder:30b")
            await self.rt.update_config({"model": model})
        return model

    async def agent_model(self) -> str:
        """Das eigene Modell dieses Agents – etwa ein kleines fürs Suchen, ein großes fürs Prüfen.

        Ist es nicht installiert, arbeitet der Agent mit dem Hauptmodell weiter: Ein Tippfehler in einer
        Agent-Datei oder eine Definition von einem anderen Rechner soll den Auftrag nicht anhalten.
        """
        want = (self.profile.model if self.profile else "") or ""
        if not want:
            return ""
        installed = await self.rt.installed()
        if not installed:
            return want  # Liste gerade nicht abrufbar: dann lieber versuchen als vorschnell meckern
        if want in installed:
            return want
        # Ohne Tag meint „qwen3-coder“ die Fassung, die da ist – wie bei Ollama selbst.
        match = next((name for name in installed if name.split(":")[0] == want.split(":")[0]), "")
        if match:
            return match
        await self.emit({"type": "notice", "text": (
            f"Der Agent @{self.profile.name} möchte {want}, das hier nicht installiert ist – "
            "er arbeitet mit dem Hauptmodell.")})
        return ""

    async def _in_memory(self, model: str) -> bool:
        loaded = getattr(self.rt, "loaded", None)
        return True if loaded is None else any(m["name"] == model for m in await loaded())

    async def resolve_model(self) -> str:
        model = await self.model_name()
        # Alles, was nicht das eingestellte Hauptmodell ist – Kontrolle, Bildmodell, eigenes Agent-Modell –, lädt
        # als Hilfsmodell: kleinerer Kontext, und ein großes Hauptmodell bleibt dabei im Speicher liegen.
        side = bool(self.model_override) or model != (self.cfg.get("model") or model)
        if model not in self.rt.plans or not await self._in_memory(model):
            await self.emit({"type": "status", "text": f"{model} wird {'geladen' if side else 'optimiert geladen'} …"})
        plan = await self.rt.ensure_loaded(model, side=side)
        self.s["model"] = model
        await self.emit({"type": "model", "model": model, "plan": plan})
        # Große Modelle rechnen großteils außerhalb der GPU – das einmal je Modell sagen, statt es aussitzen zu lassen.
        warned = getattr(self.rt, "warned_slow", None)
        if plan.get("slow") and warned is not None and model not in warned:
            warned.add(model)
            await self.emit({"type": "notice", "text": (
                f"{model} läuft nur teilweise auf der GPU – erwartbar rund {plan.get('tokens_per_s')} Token/s. "
                "Antworten dauern entsprechend; ein kleineres Modell oder eine kleinere Quantisierung ist flotter.")})
        return model

    async def side_chat(self, model: str, messages: list[dict]) -> str:
        """Kurze Anfrage ohne Werkzeuge, etwa an ein Bildmodell."""
        think = False if "thinking" in await self.rt.model_caps(model) else None
        text = ""
        async for chunk in self.rt.client.chat_stream(model, messages, options=self.rt.chat_options(model),
                                                      keep_alive=self.cfg["keep_alive"], think=think):
            text += (chunk.get("message") or {}).get("content") or ""
        return text.strip()

    def check_workspace(self) -> None:
        if self.talk:
            return  # der Chat-Tab braucht keinen Ordner
        ws = self.ctx.workspace
        if not ws.is_dir():
            raise AgentError(f"Der Ordner dieses Chats existiert nicht mehr: {ws}. Wähle einen Workspace, "
                             "dann geht es in einem neuen Chat weiter.")
        reason = blocked_workspace(ws)
        if reason:
            raise AgentError(f"{ws} geht nicht als Workspace ({reason}). Wähle einen Projektordner.")

    # ------------------------------------------------------------------ Bilder

    async def describe_images(self, images: list[str], request: str) -> dict | None:
        """Für Hauptmodelle ohne Vision: ein Bildmodell beschreibt die Bilder, bevor das Hauptmodell geladen wird."""
        model = await self.rt.vision_model(await self.model_name())
        if not model:
            await self.emit({"type": "notice", "text": "Kein installiertes Modell erkennt Bilder – das Bild bleibt "
                                                       "unbeachtet. Zum Beispiel: ollama pull gemma3:12b"})
            return None
        count = "das Bild" if len(images) == 1 else f"{len(images)} Bilder"
        await self.emit({"type": "status", "text": f"{model} sieht sich {count} an …"})
        await self.rt.ensure_loaded(model, side=True)
        self.side_model_used = True
        parts = []
        for n, image_id in enumerate(images, 1):
            try:
                data = await asyncio.to_thread(vision.encode, vision.path_of(image_id))
            except (OSError, ValueError, AttributeError) as e:
                parts.append(f"[Image {n} could not be read: {e}]")
                continue
            prompt = vision.DESCRIBE_PROMPT.format(request=request[:1500] or "–")
            text = await self.side_chat(model, [{"role": "user", "content": prompt, "images": [data]}])
            parts.append(f"[Image {n} attached by the user – described by {model}]\n{text or '(no description)'}")
        return {"model": model, "text": "\n\n".join(parts)}

    async def view_image(self, args: dict) -> dict:
        path = T.resolve(self.ctx, str(args.get("path") or ""))
        question = str(args.get("question") or "").strip()
        if not path.is_file():
            return {"ok": False, "display": {}, "content": f"Fehler: Datei nicht gefunden: {path}"}
        if not vision.is_image(path):
            return {"ok": False, "display": {}, "content": f"Fehler: {path.name} ist kein Bild (PNG, JPEG, GIF, WebP, BMP)."}
        main = await self.model_name()
        model = await self.rt.vision_model(main)
        if not model:
            return {"ok": False, "display": {}, "content": "No installed model can see images. Tell the user to "
                                                           "install one, for example: ollama pull gemma3:12b"}
        try:
            data = await asyncio.to_thread(vision.encode, path)
        except (OSError, ValueError) as e:
            return {"ok": False, "display": {}, "content": f"Fehler: {e}"}
        if model != main:
            await self.emit({"type": "status", "text": f"{model} sieht sich {path.name} an …"})
            await self.rt.ensure_loaded(model, side=True)
            self.side_model_used = True
        prompt = (f"Question about this image: {question}\n\n" if question else "") + \
            vision.DESCRIBE_PROMPT.format(request=question or "–")
        text = await self.side_chat(model, [{"role": "user", "content": prompt, "images": [data]}])
        if model != main:
            await self.resolve_model()  # Hauptmodell zurück in den VRAM
        return {"ok": bool(text), "content": f"[{path.name} – seen by {model}]\n{text or '(no description)'}",
                "display": {"image": T.rel(self.ctx, path), "model": model, "chars": len(text)}}

    # ------------------------------------------------------------------ Bilder erzeugen

    async def find_image_backend(self) -> dict | None:
        """Läuft ein lokaler Bilddienst? Nur dann sieht das Modell generate_image überhaupt."""
        if self.profile is not None and not self.profile.allows("generate_image"):
            return None
        return await imagegen.detect(self.cfg)

    async def generate_image(self, args: dict) -> dict:
        backend = self.image_backend or await self.find_image_backend()
        if not backend:
            return {"ok": False, "display": {},
                    "content": "Fehler: " + imagegen.hint(self.cfg) + imagegen.SETTINGS_HINT}
        prompt = " ".join(str(args.get("prompt") or "").split())
        if not prompt:
            return {"ok": False, "display": {}, "content": "Fehler: generate_image braucht eine Beschreibung (prompt)."}

        init_png = None
        reference = str(args.get("reference") or "").strip()
        if reference:
            ref = T.resolve(self.ctx, reference)
            if not ref.is_file() or not vision.is_image(ref):
                return {"ok": False, "display": {},
                        "content": f"Fehler: Vorlage nicht gefunden oder kein Bild: {reference}"}
            try:
                init_png = base64.b64decode(await asyncio.to_thread(vision.encode, ref))
            except (OSError, ValueError) as e:
                return {"ok": False, "display": {}, "content": f"Fehler: Vorlage {ref.name}: {e}"}

        target = T.image_target(self.ctx, args.get("path"), prompt)
        cfg_size = int(self.cfg.get("image_size") or 0)
        opts = {"prompt": prompt, "negative": args.get("negative"),
                "width": args.get("width") or cfg_size, "height": args.get("height") or cfg_size,
                "steps": args.get("steps") or self.cfg.get("image_steps"), "seed": args.get("seed"),
                "strength": args.get("strength"), "model": self.cfg.get("image_model")}

        async def status(text: str) -> None:
            await self.emit({"type": "status", "text": f"{backend['label']} malt … {text}"})

        await status("")
        try:
            made = await imagegen.generate(backend, opts, init_png, status)
        except imagegen.ImageError as e:
            return {"ok": False, "display": {}, "content": f"Fehler: {e}"}
        except httpx.HTTPError as e:
            imagegen.forget()  # der Dienst ist weg – beim nächsten Auftrag neu suchen
            return {"ok": False, "display": {},
                    "content": f"Fehler: {backend['label']} unter {backend['url']} antwortet nicht ({e.__class__.__name__})."}

        data, suffix = imagegen.convert(made["png"], target.suffix)
        if suffix != target.suffix.lower():
            target = target.with_name(target.stem + suffix)
        try:
            await T.save_binary(self.ctx, target, data)
        except OSError as e:
            return {"ok": False, "display": {}, "content": f"Fehler: {target} lässt sich nicht schreiben: {e}"}
        image_id = None
        with contextlib.suppress(OSError, ValueError):
            image_id = await asyncio.to_thread(vision.store, data)

        where = T.rel(self.ctx, target)
        return {"ok": True,
                "content": (f"Bild gespeichert: {where} ({made['width']}×{made['height']}, {made['steps']} Schritte, "
                            f"Seed {made['seed']}, Modell {made['model']}, {made['seconds']} s). "
                            "Mit view_image ansehen, wenn du prüfen willst, ob es passt; mit demselben Seed und einem "
                            "geänderten Prompt entsteht eine Variante."),
                "display": {"path": where, "image_id": image_id, "model": made["model"], "seed": made["seed"],
                            "width": made["width"], "height": made["height"], "steps": made["steps"],
                            "seconds": made["seconds"], "backend": backend["label"], "bytes": len(data)}}

    # ------------------------------------------------------------------ Hauptschleife

    async def run(self, text: str, display: str | None = None, images: list[str] | None = None) -> None:
        """display: was der Chat zeigt, wenn es vom Text fürs Modell abweicht (/befehl statt ausgeschriebenem Prompt)."""
        self.check_workspace()
        shown = text if display is None else display
        if self.parent is None and self.profile is None:
            self.profile = self.mentioned_agent(shown) or self.mentioned_agent(text)  # /review → @bug-checker
        images = [i for i in images or [] if vision.path_of(i)][:6]
        backend = await self.find_image_backend()
        if bool(backend) != bool(self.image_backend):
            self._system.clear()  # ein neu gestarteter Bilddienst gehört auch in den System-Prompt
        self.image_backend = backend

        described = None
        if images and "vision" not in await self.rt.model_caps(await self.model_name()):
            described = await self.describe_images(images, shown)  # vor dem Hauptmodell: nur ein Modellwechsel
            if described:
                await self.emit({"type": "vision", **described})
        model = await self.resolve_model()
        caps = self.rt.capabilities(model)
        native = "tools" in caps
        think = effort.think(self.cfg, caps, model)

        message = {"role": "user", "content": text, "_text": shown, "_ts": time.time()}
        if images:
            message["_images"] = images
        if described:
            message["content"] += "\n\n" + described["text"]
            message["_vision"] = described
        if self.parent is None and self.cfg.get("memory", True):
            await self.attach_memory(message, shown)
        if self.chat and not self.talk:
            await self.attach_files(message, shown)
        if self.mode == "plan" and self.parent is None and not self.talk:
            ask = " Ask the user about open decisions with ask_user before you finalize." if self.can_ask else ""
            message["content"] += ("\n\n[Plan mode: explore read-only, then present a concrete step-by-step plan "
                                   f"with the files to change and how to verify the result.{ask} "
                                   "Do not modify files or run commands.]")
        if self.profile and self.parent is None:
            message["_agent"] = self.profile.name
            await self.emit({"type": "profile", "agent": self.profile.name})
        # Sub-Agents schreiben in die Sicherung der Aufgabe, die sie beauftragt hat.
        self.ctx.checkpoint = self.new_checkpoint(message) if self.parent is None else self.parent.ctx.checkpoint
        self.turn_start = len(self.s["messages"])
        self.s["messages"].append(message)
        if self.s.get("title") in (None, "", "Neuer Chat") and shown.strip():
            self.s["title"] = shown.strip().splitlines()[0][:60]
        self.reviews = self.continuations = self.fail_streak = self.asked = 0
        self.review_at = time.monotonic()

        try:
            outcome = await self.work(model, native, think)
            # Kontrolle: prüft das Ergebnis und schickt den Agent weiter, solange etwas fehlt.
            checked, forced = -1, False  # Aufrufe bei der letzten Prüfung · nach einer Nachbesserung wird immer geprüft
            while outcome == "answer":
                if self.parent is None and self.inbox:  # der Nutzer hat während der letzten Antwort geschrieben
                    model = await self.resolve_model()
                    outcome = await self.work(model, native, think)
                    continue
                calls = controller.call_count(self)
                if not controller.due_at_end(self) or (calls == checked and not forced):
                    break
                verdict = await controller.review(self, "end")
                checked, forced = calls, False
                if verdict["verdict"] != "continue":
                    continue  # abgesegnet – es sei denn, inzwischen kam eine neue Nachricht
                if self.continuations >= effort.controller_rounds(self.cfg):
                    await self.emit({"type": "notice", "text": f"Die Kontrolle sieht noch offene Punkte: {verdict['note']} "
                                                               "Schreib „weiter“, dann geht es daran weiter."})
                    break
                controller.inject(self, verdict)
                forced = True
                model = await self.resolve_model()
                outcome = await self.work(model, native, think)
            if self.parent is None:
                await self.finish_turn(model, outcome)
                await self.offer_plan(outcome)
                await self.offer_apply(outcome)
        finally:
            if self.parent is None:
                await self.record_changes()  # auch nach Abbruch oder Fehler – gerade dann will man zurücknehmen können

    def new_checkpoint(self, message: dict):
        turn = uuid.uuid4().hex[:12]
        message["_turn"] = turn
        try:
            return checkpoints.Checkpoint(str(self.s.get("id") or ""), turn)
        except ValueError:
            return None  # Chat ohne gültige Kennung: ohne Rückgängig weiterarbeiten

    async def record_changes(self) -> None:
        """Hält fest, welche Dateien diese Aufgabe geändert hat, und bietet sie zum Zurücknehmen an."""
        cp = self.ctx.checkpoint
        if cp is None or not cp.files:
            return
        try:
            changes = await asyncio.to_thread(cp.seal, self.ctx.workspace)
        except (OSError, ValueError):
            return
        if changes:
            self.s["messages"].append({"role": "event", "_ui": True, "_changes": changes})
            await self.emit({"type": "changes", **changes})

    async def attach_memory(self, message: dict, shown: str) -> None:
        referenced: set[str] = set()
        if "[[" in shown:
            notes = memory.references(shown, self.ctx.workspace)
            if notes:
                message["content"] += f"\n\n[Notes the user referenced]\n{notes}"
                referenced = {m.group(1).strip() for m in memory.LINK_RX.finditer(shown)}
        if not self.cfg.get("auto_recall", True):
            return
        try:
            found = await recall.recall(shown, self.ctx.workspace, self.rt, exclude=referenced)
        except Exception:  # noqa: BLE001 — Erinnern ist ein Bonus, nie ein Grund zum Abbruch
            found = None
        if found:
            message["content"] += f"\n\n[Notes from memory that may be relevant – use them if they help]\n{found['text']}"
            message["_recall"] = found["titles"]
            await self.emit({"type": "recall", "notes": found["titles"]})

    async def attach_files(self, message: dict, shown: str) -> None:
        """Chat: Dateien, die der Nutzer beim Namen nennt, liest Coder gleich mit – wie @datei in Claude Code.

        Kleine Modelle bitten im Chat sonst gern darum, man möge ihnen den Inhalt schicken, statt selbst zu lesen.
        """
        try:
            paths = await asyncio.to_thread(T.mentioned_files, self.ctx, shown)
        except OSError:
            return
        parts, budget = [], MENTION_CHARS
        for path in paths:
            try:
                text = await asyncio.to_thread(T._read_text, path)
            except (OSError, T.ToolError):
                continue  # Binärdatei, gesperrt oder inzwischen weg
            if len(text) > budget:
                text = text[:budget] + "\n… [cut – read the rest with read_file and offset]"
            budget -= len(text)
            parts.append((T.rel(self.ctx, path), text))
            if budget <= 0:
                break
        if not parts:
            return
        message["content"] += "\n\n[Files the user mentioned – current content]\n" + "\n\n".join(
            f"--- {name}\n{text}" for name, text in parts)
        message["_files"] = [name for name, _ in parts]
        await self.emit({"type": "files", "files": message["_files"]})

    async def take_inbox(self) -> None:
        """Nachrichten, die während der Arbeit eingetroffen sind – das Modell liest sie vor seinem nächsten Schritt."""
        items, self.inbox[:] = list(self.inbox), []
        for item in items:
            text = str(item.get("text") or "").strip()
            if not text:
                continue
            shown = str(item.get("display") or text)
            message = {"role": "user", "content": text, "_text": shown, "_ts": time.time(), "_queued": True}
            if self.cfg.get("memory", True) and "[[" in shown:
                notes = memory.references(shown, self.ctx.workspace)
                if notes:
                    message["content"] += f"\n\n[Notes the user referenced]\n{notes}"
            self.s["messages"].append(message)
            await self.emit({"type": "queued_taken", "id": item.get("id"), "text": shown})

    async def finish_turn(self, model: str, outcome: str) -> None:
        if self.side_model_used and hasattr(self.rt, "preload"):
            self.rt.preload(model)  # Hauptmodell schon wieder bereitlegen
        files = controller.changed_files(self)
        delegated = any(c["name"] == "agent" for m in self.s["messages"][self.turn_start:] for c in m.get("_calls") or [])
        if (outcome == "answer" and (files or delegated) and self.cfg.get("memory", True)
                and self.cfg.get("journal", True)):
            first = self.s["messages"][self.turn_start]
            try:
                await asyncio.to_thread(recall.journal, self.ctx.workspace, first.get("_text") or first["content"],
                                        self.last_answer(), files)
                await self.emit({"type": "memory_changed"})
            except (OSError, ValueError):
                pass

    async def offer_plan(self, outcome: str) -> None:
        """Im Modus Planen steht am Ende ein Plan – die Oberfläche bietet an, ihn umzusetzen."""
        if self.mode != "plan" or outcome != "answer" or self.question is None or self.talk:
            return
        last = next((m for m in reversed(self.s["messages"][self.turn_start:])
                     if m["role"] == "assistant" and (m.get("content") or "").strip()), None)
        if last is None:
            return
        last["_plan"] = True
        await self.emit({"type": "plan_ready", "id": last.get("_id")})

    async def offer_apply(self, outcome: str) -> None:
        """Chat: Zeigt die Antwort Code zu Dateien, die Coder dafür gelesen hat, lässt sich das mit einem Klick
        umsetzen – im Modus Normal. So bleibt klar, dass der Chat selbst nichts geändert hat."""
        if not self.chat or self.talk or outcome != "answer" or self.question is None:
            return
        turn = self.s["messages"][self.turn_start:]
        last = next((m for m in reversed(turn) if m["role"] == "assistant" and (m.get("content") or "").strip()), None)
        if last is None or "```" not in last["content"]:
            return
        looked = bool(turn and turn[0].get("_files")) or any(
            c["name"] in ("read_file", "grep", "glob") for m in turn for c in m.get("_calls") or [])
        if not looked:
            return
        last["_apply"] = True
        await self.emit({"type": "apply_ready", "id": last.get("_id")})

    async def work(self, model: str, native: bool, think) -> str:
        """Arbeitet bis zur nächsten Antwort. Ergebnis: answer · stopped · empty · limit."""
        limit = effort.steps(self.cfg)
        if self.parent is not None:
            limit = min(limit, self.steps_override or effort.steps(self.cfg, SUBAGENT_STEPS))
        nudged, stalls, intent = False, 0, False
        for _ in range(limit):
            if self.parent is None and self.inbox:
                await self.take_inbox()
            await self.compact_if_needed(model, native)
            try:
                calls = await self.model_turn(model, native, think)
            except ModelStalled as e:
                stalls += 1
                if stalls > 2:
                    raise AgentError(f"{model} reagiert wiederholt nicht mehr. Starte Ollama neu oder wähle in den "
                                     "Einstellungen weniger Kontext.") from e
                await self.recover(model, str(e), stalls)
                continue
            except ModelRepeating:
                if self.parent is None:
                    await self.emit({"type": "notice", "text": "Das Modell hat sich wiederholt – abgebrochen und nachgehakt."})
                self.s["messages"].append({"role": "user", "content": NUDGE_REPEAT, "_nudge": True})
                continue
            stalls = 0
            if calls:
                try:
                    for call in calls:
                        await self.handle_call(call)
                except StopTurn:
                    self.stopped = True
                    return "stopped"
                reason = controller.due_while_working(self)
                if reason:
                    verdict = await controller.review(self, reason)
                    if verdict["verdict"] == "continue":
                        controller.inject(self, verdict, hint=True)
                    if verdict["model"] != model:
                        model = await self.resolve_model()
                continue
            said = (self.s["messages"][-1].get("content") or "").strip()
            if said:
                # Nur angekündigt, nicht getan: einmal nachhaken – die Kontrolle sieht das im Chat und auf Niedrig nicht.
                if (not intent and self.parent is None and len(said) < 320
                        and INTENT_TAIL_RX.search(said[-200:]) and self.tool_defs()):
                    intent = True
                    self.s["messages"].append({"role": "user", "content": NUDGE_INTENT, "_nudge": True})
                    continue
                return "answer"
            if nudged:  # auch nach der Nachfrage nichts: aufhören statt endlos zu drehen
                if self.parent is None:
                    await self.emit({"type": "notice", "text": "Das Modell hat keine Antwort geliefert."})
                return "empty"
            # Kleine Modelle hören nach Werkzeugergebnissen gern wortlos auf – einmal nachhaken.
            nudged = True
            self.s["messages"].pop()
            self.s["messages"].append({"role": "user", "content": NUDGE_SUB if self.parent else NUDGE_MAIN, "_nudge": True})
        self.hit_limit = True
        if self.parent is None:
            await self.emit({"type": "notice", "text": "Schrittlimit erreicht. Schreib „weiter“, um fortzufahren."})
        return "limit"

    async def model_turn(self, model: str, native: bool, think: bool | None) -> list[dict]:
        sees = "vision" in self.rt.capabilities(model)
        messages = [{"role": "system", "content": self.system_prompt(native)}] + \
            wire_messages(self.s["messages"], native, images=sees)
        msg = {"role": "assistant", "content": "", "_id": uuid.uuid4().hex[:10]}
        if self.profile and self.parent is None:
            msg["_agent"] = self.profile.name
        self.s["messages"].append(msg)  # früh anhängen, damit ein Abbruch den Teiltext behält
        await self.emit({"type": "assistant_start", "id": msg["_id"]})

        raw_calls: list[dict] = []
        final: dict = {}
        t0 = time.perf_counter()
        first_token = None
        checked = 0
        stream = self.rt.client.chat_stream(
            model, messages,
            tools=self.schemas() if native else None,
            options=self.rt.chat_options(model),
            keep_alive=self.cfg["keep_alive"],
            think=think,
        )
        try:
            while True:
                try:
                    chunk = await self.next_chunk(stream, model, waiting=first_token is None)
                except StopAsyncIteration:
                    break
                m = chunk.get("message") or {}
                if m.get("thinking"):
                    first_token = first_token or time.perf_counter()
                    msg["_thinking"] = msg.get("_thinking", "") + m["thinking"]
                    await self.emit({"type": "thinking", "id": msg["_id"], "text": m["thinking"]})
                if m.get("content"):
                    first_token = first_token or time.perf_counter()
                    msg["content"] += m["content"]
                    await self.emit({"type": "text", "id": msg["_id"], "text": m["content"]})
                if m.get("tool_calls"):
                    raw_calls.extend(m["tool_calls"])
                if chunk.get("done"):
                    final = chunk
                size = len(msg["content"]) + len(msg.get("_thinking", ""))
                if size - checked >= 400:
                    checked = size
                    for key in ("content", "_thinking"):
                        if repeating(msg.get(key, "")):
                            msg[key] = trim_repeat(msg[key])
                            raise ModelRepeating
        finally:
            with contextlib.suppress(Exception):
                await stream.aclose()

        if not raw_calls:
            raw_calls, cleaned = parse_text_calls(msg["content"], {t["name"] for t in self.tool_defs()})
            if raw_calls and cleaned != msg["content"]:
                if native:
                    msg["content"] = cleaned  # im nativen Protokoll gehören Aufrufe in tool_calls, nicht in den Text
                else:
                    msg["_shown"] = cleaned  # Text-Protokoll: das Modell soll seine Aufrufe im Verlauf wiedersehen
                await self.emit({"type": "assistant_text", "id": msg["_id"], "text": cleaned})

        calls = []
        for rc in raw_calls:
            fn = rc.get("function") or {}
            args = fn.get("arguments") or {}
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except ValueError:
                    args = {}
            calls.append({"id": uuid.uuid4().hex[:10], "name": str(fn.get("name", "")), "args": args if isinstance(args, dict) else {}})
        if calls:
            if native:
                msg["tool_calls"] = [{"function": {"name": c["name"], "arguments": c["args"]}} for c in calls]
            msg["_calls"] = calls

        stats = self._stats(final, t0, first_token)
        msg["_stats"] = stats
        usage = self.s.setdefault("usage", {"prompt": 0, "completion": 0, "last_prompt": 0})
        usage["prompt"] += stats["prompt_tokens"]
        usage["completion"] += stats["tokens"]
        await self.emit({"type": "stats", "id": msg["_id"], "stats": stats})
        await self.emit_context(model, native)

        return calls

    async def next_chunk(self, stream, model: str, waiting: bool) -> dict:
        """Nächstes Stück vom Modell – mit Watchdog.

        Stille allein heißt nichts: Prompt-Verarbeitung und lange Werkzeugaufrufe streamen nicht. Erst wenn auch die
        GPU ruht oder das Modell aus dem Speicher verschwunden ist, gilt es als hängend.
        """
        limit = float(self.cfg.get("watchdog") or 0)
        if not limit:
            return await stream.__anext__()
        pending = asyncio.ensure_future(stream.__anext__())
        window, silent = (limit * 2 if waiting else limit), 0.0
        try:
            while True:
                done, _ = await asyncio.wait({pending}, timeout=window)
                if done:
                    return pending.result()
                silent += window
                if not await self.model_alive(model, silent, limit, waiting):
                    raise ModelStalled(f"seit {int(silent)} s keine Antwort")
                window = min(limit, 60.0)
        except BaseException:
            if not pending.done():
                pending.cancel()
                with contextlib.suppress(BaseException):
                    await pending
            raise

    async def model_alive(self, model: str, silent: float, limit: float, waiting: bool) -> bool:
        # Läuft das Modell großteils auf der CPU (30B aufwärts, 120B sowieso), ruht die GPU auch im Normalbetrieb.
        # Ihre Stille darf dann nicht als „hängt“ gelten – sonst lädt der Watchdog ein Riesenmodell grundlos neu.
        share = (self.rt.plans.get(model) or {}).get("gpu_share", 1.0)
        cpu_heavy = share < 0.9
        if silent >= limit * (12 if cpu_heavy else 6):
            return False  # harte Obergrenze
        if not waiting and not await self._in_memory(model):
            return False  # Runner abgestürzt oder entladen
        if cpu_heavy:
            return True
        for attempt in range(2):
            busy = await asyncio.to_thread(optimizer.gpu_utilization)
            if busy is None:
                return silent < limit * 3  # ohne Messung: großzügig warten
            if busy >= GPU_BUSY:
                return True
            if attempt == 0:
                await asyncio.sleep(3)
        return False

    async def recover(self, model: str, reason: str, attempt: int) -> None:
        last = self.s["messages"][-1] if self.s["messages"] else {}
        if last.get("role") == "assistant" and not last.get("_calls"):
            self.s["messages"].pop()
            await self.emit({"type": "assistant_discard", "id": last.get("_id")})
        await self.emit({"type": "watchdog",
                         "text": f"{model} hängt ({reason}) – wird neu geladen, Versuch {attempt} von 2 …"})
        with contextlib.suppress(OllamaError):
            await self.rt.client.unload(model)
        self.rt.plans.pop(model, None)
        await self.resolve_model()

    @staticmethod
    def _stats(final: dict, t0: float, first_token: float | None) -> dict:
        eval_s = (final.get("eval_duration") or 0) / 1e9
        prompt_s = (final.get("prompt_eval_duration") or 0) / 1e9
        return {
            "tokens": final.get("eval_count") or 0,
            "prompt_tokens": final.get("prompt_eval_count") or 0,
            "tokens_per_s": round((final.get("eval_count") or 0) / eval_s, 1) if eval_s else 0,
            "prompt_per_s": round((final.get("prompt_eval_count") or 0) / prompt_s, 1) if prompt_s else 0,
            "load_s": round((final.get("load_duration") or 0) / 1e9, 2),
            "ttft_s": round(first_token - t0, 2) if first_token else None,
            "total_s": round(time.perf_counter() - t0, 2),
            "done_reason": final.get("done_reason"),
        }

    # ------------------------------------------------------------------ Werkzeuge

    def permission(self, name: str, args: dict) -> str:
        kind = self.kind(name)
        mode = self.cfg["permission_mode"]
        allow = self.s.get("allow", [])
        if kind in ("read", "meta", "agent", "memory"):  # Sub-Agents fragen selbst; Notizen sind keine Projektdateien
            return "allow"
        if kind == "web":  # liest nur, schickt aber Daten nach draußen – im Modus „Normal“ also nachfragen
            # Im Chat-Tab ist Recherche der Zweck: dort ohne Rückfrage.
            return "ask" if mode == "ask" and name not in allow and not self.talk else "allow"
        if self.chat:
            return "chat"
        if mode == "plan":
            return "plan"
        if mode == "yolo" or name in allow:
            return "allow"
        if name == "run_command" and T.command_allowed(str(args.get("command", "")), allow):
            return "allow"
        if kind == "write" and mode == "auto-edit":
            if T.inside_workspace(self.ctx, T.resolve(self.ctx, args.get("path"))):
                return "allow"
        return "ask"

    @staticmethod
    def always_label(name: str, args: dict) -> str | None:
        """Wofür „Immer erlauben“ gilt: bei Befehlen nur für Programm und Unterbefehl – None heißt, jedes Mal fragen."""
        if name == "run_command":
            return T.command_prefix(str(args.get("command", "")))
        return name

    def remember_allow(self, name: str, always: str) -> None:
        entry = f"run_command:{always}" if name == "run_command" else name
        allow = self.s.setdefault("allow", [])
        if entry not in allow:
            allow.append(entry)

    async def execute(self, name: str, args: dict) -> dict:
        # Zwei Werkzeuge brauchen den Agent selbst: das eine ein Bildmodell, das andere den Bilddienst.
        handler = {"view_image": self.view_image, "generate_image": self.generate_image}.get(name)
        if handler is None:
            return await T.execute(name, args, self.ctx)
        try:
            return await handler(args)
        except (StopTurn, OllamaError):
            raise  # Abbruch und Ollama-Fehler gehören in die Schleife, nicht zurück ans Modell
        except Exception as e:  # noqa: BLE001 – alles andere ist ein Werkzeugfehler und geht ans Modell
            return {"ok": False, "display": {}, "content": f"Fehler ({e.__class__.__name__}): {e}"}

    async def handle_call(self, call: dict) -> None:
        cid, name = call["id"], call["name"]
        # Erst die Namen der Argumente angleichen, dann prüfen: file_path muss als path in die Freigabe.
        args = call["args"] = T.normalize_args(name, call["args"])
        summary = self.summarize(name, args)
        await self.emit({"type": "tool_call", "id": cid, "name": name, "args": _ui_args(args),
                         "summary": summary, "kind": self.kind(name)})

        signature = json.dumps([name, args], sort_keys=True, default=str)
        self._recent = (self._recent + [signature])[-8:]
        stop = False
        available = {t["name"] for t in self.tool_defs()}

        if self._recent.count(signature) >= 3 and T.kind(name) != "meta":
            result = {"ok": False, "display": {},
                      "content": "You already made this exact call several times. Change your approach."}
        elif (self.chat and name not in available and (name in T.TOOL_MAP or name == "agent")
              and (self.talk or self.kind(name) not in CHAT_KINDS)):  # aus einem früheren Auftrag abgeschaut
            result = {"ok": False, "display": {"denied": True}, "content": TALK_DENIED if self.talk else CHAT_DENIED}
        elif name == "agent":
            result = await self.delegate(cid, args)
            stop = result.pop("stop", False)
        elif name == "ask_user":
            result = (await self.ask_user(cid, args) if name in available
                      else {"ok": False, "display": {}, "content": NO_QUESTIONS})
        elif name not in available:
            content = (f"The tool {name} is not available to you. Use only the tools you were given."
                       if name in T.TOOL_MAP else
                       f"Unknown tool '{name}'. Available tools: {', '.join(sorted(available))}.")
            result = {"ok": False, "display": {}, "content": content}
        elif name == "run_command" and self.read_only and MUTATING_RX.search(str(args.get("command", ""))):
            result = {"ok": False, "display": {"denied": True},
                      "content": "You are a read-only agent and this command looks like it changes files. "
                                 "Use only commands that read or test, and report what should be changed instead."}
        else:
            decision = self.permission(name, args)
            if decision == "chat":
                result = {"ok": False, "display": {"denied": True}, "content": TALK_DENIED if self.talk else CHAT_DENIED}
            elif decision == "plan":
                result = {"ok": False, "display": {"denied": True},
                          "content": "Plan mode is active: no file changes or commands. Present your plan instead."}
            elif decision == "ask":
                always = self.always_label(name, args)
                answer = await self.ask({"id": cid, "name": name, "summary": summary, "kind": T.kind(name),
                                         "args": _ui_args(args), "preview": T.preview(name, args, self.ctx),
                                         "always": always})
                if answer == "deny":
                    result = {"ok": False, "display": {"denied": True},
                              "content": "The user declined this action. Stop and wait for their instructions."}
                    stop = True
                elif answer == "refuse":  # niemand da, der freigeben könnte (Cowork): weiterarbeiten, ohne das hier
                    result = {"ok": False, "display": {"denied": True}, "content": UNATTENDED_DENIED}
                else:
                    if answer == "always" and always:
                        self.remember_allow(name, always)
                    await self.emit({"type": "tool_running", "id": cid})
                    result = await self.execute(name, args)
            else:
                result = await self.execute(name, args)

        if not result["display"].get("denied"):
            self.fail_streak = 0 if result["ok"] else self.fail_streak + 1
        self.s["messages"].append({
            "role": "tool", "content": result["content"], "tool_name": name,
            "_id": cid, "_name": name, "_summary": summary, "_ok": result["ok"], "_display": result["display"],
        })
        await self.emit({"type": "tool_result", "id": cid, "name": name, "ok": result["ok"],
                         "output": result["content"][:8000], "display": result["display"]})
        if name == "todo_write":
            await self.emit({"type": "todos", "todos": self.ctx.todos})
        if stop:
            raise StopTurn

    async def ask_user(self, cid: str, args: dict) -> dict:
        """Rückfrage an den Nutzer – er wählt eine Antwort, schreibt eine eigene oder überspringt."""
        items = T.question_items(args)
        if not items:
            return {"ok": False, "display": {}, "content": "ask_user needs a question and 2-4 answer options."}
        room = QUESTION_LIMIT - self.asked
        if room <= 0:
            return {"ok": False, "display": {"items": [{**i, "answer": None} for i in items], "limit": True},
                    "content": "You have asked enough questions for this task. Decide the rest yourself with "
                               "sensible defaults and mention your assumptions."}
        items = items[:room]
        shown, lines = [], []
        for n, item in enumerate(items, 1):
            self.asked += 1
            request = {"id": cid if len(items) == 1 else f"{cid}-{n}", "step": cid, "index": n, "count": len(items),
                       **item}
            if self.profile:
                request["agent"] = self.profile.name
            answer = clean_answer(await self.question(request), item)
            shown.append({**item, "answer": answer})
            if answer["skipped"]:
                reply = "(skipped – decide yourself with a sensible default and mention your assumption)"
            else:
                reply = "; ".join(answer["choices"] + ([f'"{answer["text"]}"'] if answer["text"] else []))
            lines.append(f"Question: {item['question']}\nAnswer: {reply}")
        skipped = all(i["answer"]["skipped"] for i in shown)
        return {"ok": True, "content": "\n\n".join(lines), "display": {"items": shown, "skipped": skipped}}

    async def delegate(self, cid: str, args: dict) -> dict:
        """Lässt einen Sub-Agent die Aufgabe mit eigenem Kontext erledigen und gibt seinen Bericht zurück."""
        if not self.can_delegate:
            return {"ok": False, "display": {}, "content": "Sub-agents are not available here. Do the work yourself."}
        agents = self.available_agents()
        name = str(args.get("agent") or args.get("name") or "").strip().lstrip("@").lower()
        task = str(args.get("task") or args.get("prompt") or args.get("description") or "").strip()
        profile = agents.get(name)
        if profile is None:
            return {"ok": False, "display": {}, "content": f"Unknown agent '{name}'. Available: {', '.join(agents)}."}
        if not task:
            return {"ok": False, "display": {}, "content": "The task for the agent is missing."}

        steps: dict[str, dict] = {}

        async def emit(ev: dict) -> None:
            if ev.get("type") == "tool_call":
                steps[ev["id"]] = {"id": ev["id"], "name": ev["name"], "summary": ev["summary"], "args": ev["args"]}
            elif ev.get("type") == "tool_result" and ev["id"] in steps:
                steps[ev["id"]].update(ok=ev["ok"], output=ev["output"][:1500], display=ev["display"])
            await self.emit({**ev, "parent": cid, "agent": profile.name})

        async def ask(request: dict) -> str:
            return await self.ask({**request, "agent": profile.name})

        session = {"id": cid, "title": profile.name, "workspace": self.s["workspace"], "messages": [], "todos": [],
                   "allow": self.s.setdefault("allow", [])}
        sub = Agent(self.rt, session, emit, ask, profile=profile, parent=self)
        started = time.perf_counter()
        await sub.run(task)
        report = sub.last_answer()
        display = {"agent": profile.name, "task": task, "steps": list(steps.values()), "report": report,
                   "seconds": round(time.perf_counter() - started, 1),
                   # Arbeitet der Agent mit einem eigenen Modell, steht das hinterher an seinem Schritt.
                   "model": sub.s.get("model") or ""}
        if sub.stopped:
            content = f"The user declined an action of the {profile.name} agent. Stop and wait for their instructions."
        elif report:
            content = f"Report from {profile.name}:\n{report}"
        else:
            log = "\n".join(f"- {s['name']} {s['summary'][:120]} → {'ok' if s.get('ok') else 'failed'}"
                            for s in steps.values())
            content = (f"The {profile.name} agent finished WITHOUT a report, so there are no findings from it. "
                       "Do not invent or assume results: check the code yourself or tell the user the agent "
                       f"returned nothing.\nIts steps:\n{log or '- none'}")
        if sub.hit_limit:
            content += "\n[The agent hit its step limit; the result may be incomplete.]"
        return {"ok": bool(report) and not sub.stopped, "content": content, "display": display, "stop": sub.stopped}

    # ------------------------------------------------------------------ Kontext

    def context_parts(self, native: bool) -> dict:
        """Woraus der Kontext besteht – für die Anzeige beim Klick auf den Kontextring.

        system: Auftrag, Projektanweisungen, Gedächtnisnotizen · tools: die Werkzeug-Schemas ·
        chat: deine Nachrichten und die Antworten · output: was Werkzeuge zurückgegeben haben.
        """
        parts = {"system": len(self.system_prompt(native)), "tools": 0, "chat": 0, "output": 0}
        for m in wire_messages(self.s["messages"], native):
            size = len(m.get("content") or "")
            if m.get("tool_calls"):
                size += len(json.dumps(m["tool_calls"], ensure_ascii=False))
            parts["output" if m["role"] == "tool" else "chat"] += size
        if native:
            parts["tools"] = len(json.dumps(self.schemas(), ensure_ascii=False))
        return {k: int(v / CHARS_PER_TOKEN) for k, v in parts.items()}

    def context_tokens(self, native: bool) -> int:
        return sum(self.context_parts(native).values())

    async def emit_context(self, model: str, native: bool) -> None:
        parts = self.context_parts(native)
        usage = dict(self.s.get("usage") or {})
        usage["turns"] = sum(1 for m in self.s["messages"] if m.get("_stats"))
        await self.emit({"type": "context", "used": sum(parts.values()), "max": self.rt.num_ctx(model),
                         "parts": parts, "usage": usage, "model": model})

    async def compact_if_needed(self, model: str, native: bool, force: bool = False) -> None:
        limit = self.rt.num_ctx(model)
        if force or self.context_tokens(native) > 0.6 * limit:
            self._shrink_tool_outputs(keep_last=6)
        if force or self.context_tokens(native) > 0.8 * limit:
            await self._summarize(model)
            if self.context_tokens(native) > 0.9 * limit:
                self._shrink_tool_outputs(keep_last=2, head=400, tail=200)
            await self.emit_context(model, native)

    def _shrink_tool_outputs(self, keep_last: int, head: int = 700, tail: int = 300) -> None:
        msgs = self.s["messages"]
        for m in msgs[:max(0, len(msgs) - keep_last)]:
            c = m.get("content") or ""
            if m["role"] == "tool" and len(c) > head + tail + 200:
                m["content"] = f"{c[:head]}\n… [ältere Ausgabe gekürzt, {len(c)} Zeichen] …\n{c[-tail:]}"

    async def _summarize(self, model: str) -> None:
        msgs = self.s["messages"]
        user_turns = [i for i, m in enumerate(msgs) if m["role"] == "user" and "_text" in m and not m.get("_hidden")]
        if not user_turns:
            return
        cut = user_turns[-1]
        older = [i for i in range(cut) if not msgs[i].get("_hidden") and not msgs[i].get("_ui")]
        if len(older) < 2:
            return

        parts = []
        for i in older:
            m = msgs[i]
            label = {"user": "USER", "assistant": "ASSISTANT", "tool": f"TOOL {m.get('_name', '')}"}.get(m["role"], m["role"])
            body = (m.get("content") or "")[:1500]
            if m.get("_calls"):
                body += "\n" + "; ".join(f"call {c['name']}({self.summarize(c['name'], c['args'])})" for c in m["_calls"])
            parts.append(f"{label}: {body}")
        budget = int(self.rt.num_ctx(model) * 0.5 * CHARS_PER_TOKEN)
        transcript = "\n\n".join(parts)[-budget:]

        await self.emit({"type": "status", "text": "Verlauf wird verdichtet …"})
        prompt = [
            {"role": "system", "content": "You compress coding-agent conversations into dense, factual summaries."},
            {"role": "user", "content": (
                "Summarize this conversation so work can continue without it. Keep: the user's goals, decisions, "
                "files created or changed (with key details), important findings, errors and how they were solved, "
                "current state and open tasks. Max 350 words, bullet points.\n\n" + transcript)},
        ]
        think = False if "thinking" in self.rt.capabilities(model) else None
        summary = ""
        async for chunk in self.rt.client.chat_stream(model, prompt, options=self.rt.chat_options(model),
                                                      keep_alive=self.cfg["keep_alive"], think=think):
            summary += (chunk.get("message") or {}).get("content") or ""
        summary = summary.strip()
        if not summary:
            return

        for i in older:
            msgs[i]["_hidden"] = True
        msgs[cut:cut] = [
            {"role": "user", "content": f"[Summary of the earlier conversation]\n{summary}", "_summary": True},
            {"role": "assistant", "content": "Understood. Continuing from this summary.", "_summary": True, "_quiet": True},
        ]
        if cut <= self.turn_start:  # der laufende Auftrag rückt nach hinten – sonst gälte die Zusammenfassung als Auftrag
            self.turn_start += 2
        await self.emit({"type": "compacted", "summary": summary})

    async def compact(self) -> None:
        model = await self.resolve_model()
        native = "tools" in self.rt.capabilities(model)
        await self.compact_if_needed(model, native, force=True)
