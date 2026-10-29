"""Sub-Agents: Spezialisten, an die Coder Teilaufgaben abgibt – oder die du mit @name direkt ansprichst.

Eine Definition ist eine Markdown-Datei mit Frontmatter, im selben Format wie bei Claude Code:

    ---
    name: bug-checker
    description: Prüft Code auf Fehler und meldet sie, ohne etwas zu ändern.
    tools: read_file, grep, glob, run_command
    model: qwen2.5-coder:14b
    ---
    Anweisungen an den Agent …

`model` ist freiwillig: Ohne Angabe arbeitet der Agent mit dem Modell des Hauptagenten. Steht dort ein Name,
den dieser Rechner nicht hat – etwa `sonnet` aus einer Claude-Code-Definition –, gilt ebenfalls das Hauptmodell.

Gesucht wird in ~/.claude/agents (Claude Code), ~/.coder/agents und im Workspace unter .claude/agents und
.coder/agents. Spätere Quellen überschreiben frühere mit gleichem Namen; die eingebauten Agents kommen zuerst.
"""

import os
import re
from dataclasses import dataclass
from pathlib import Path

from . import tools as T
from .config import HOME

CLAUDE_HOME = Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude")
NAME_RX = re.compile(r"^[a-z0-9][a-z0-9_-]{0,39}$")
FRONTMATTER_RX = re.compile(r"\A\ufeff?---[ \t]*\r?\n(.*?)\r?\n---[ \t]*(?:\r?\n|\Z)", re.S)
SCOPES = ("global", "project")
READ = ["read_file", "list_dir", "glob", "grep", "view_image"]

# Werkzeugnamen aus Claude Code auf die von Coder abbilden
CLAUDE_TOOLS = {
    "read": ["read_file", "view_image"], "write": ["write_file"], "edit": ["edit_file"], "multiedit": ["edit_file"],
    "glob": ["glob"], "grep": ["grep"], "ls": ["list_dir"], "bash": ["run_command"], "powershell": ["run_command"],
    "webfetch": ["web_fetch"], "websearch": ["web_search", "web_research"], "todowrite": ["todo_write"],
    "imagegen": ["generate_image"],
}


@dataclass
class AgentDef:
    name: str
    description: str
    prompt: str
    tools: list[str] | None = None  # None: alle Werkzeuge
    model: str = ""  # leer: das Modell des Hauptagenten
    source: str = "builtin"  # builtin · claude · global · claude-project · project
    path: str = ""

    @property
    def editable(self) -> bool:
        return self.source in SCOPES

    def allows(self, tool: str) -> bool:
        return self.tools is None or tool in self.tools

    def public(self) -> dict:
        return {"name": self.name, "description": self.description, "prompt": self.prompt, "tools": self.tools,
                "model": self.model, "source": self.source, "editable": self.editable, "path": self.path}


def _builtin(name: str, description: str, tools: list[str], prompt: str) -> AgentDef:
    return AgentDef(name=name, description=description, prompt=prompt.strip(), tools=tools)


BUILTIN = [
    _builtin("explorer",
             "Durchsucht die Codebasis und beantwortet Fragen dazu: wo etwas definiert ist und wie Teile "
             "zusammenhängen. Ändert nichts.", READ, """
You are a fast, read-only code explorer.
- Locate relevant files with glob and grep before reading. Read only what you need.
- Answer precisely, citing path:line for every claim.
- Never modify files and never run commands."""),
    _builtin("planer",
             "Entwirft einen konkreten Umsetzungsplan: betroffene Dateien, Schritte in sinnvoller Reihenfolge, "
             "Risiken. Ändert nichts.", READ, """
You are a software architect who plans before anyone codes.
- Study the relevant code first; base every step on what the code actually does.
- Deliver a numbered plan. Each step names the files and functions to change and what exactly to change.
- End with risks and how to verify the result. Never modify files."""),
    _builtin("bug-checker",
             "Prüft Code auf echte Fehler: Bugs, Logikfehler, Randfälle, Sicherheitslücken. Meldet Befunde mit "
             "Datei und Zeile, ändert nichts.", READ + ["run_command"], """
You are a meticulous reviewer hunting real defects, not style issues.
- Trace data flow and edge cases: empty input, None, errors, encodings, concurrency, paths.
- You may run tests or linters with run_command, but never modify files.
- Report each finding as: path:line – what breaks, how to trigger it, severity (hoch, mittel, niedrig).
- If nothing serious turns up, say so plainly."""),
    _builtin("fix-it",
             "Behebt einen konkreten, bekannten Fehler – aus einer Fehlermeldung, einem Traceback oder einem "
             "Bug-Bericht – und prüft die Korrektur.", READ + ["edit_file", "write_file", "run_command"], """
You fix one concrete, known problem.
- Locate or reproduce the problem first, then apply the smallest correct change.
- Always read a file before editing it. Do not refactor unrelated code.
- Verify the fix by running the relevant test, script or command.
- Report the root cause, the change (path:line) and how you verified it."""),
    _builtin("test-runner",
             "Führt Tests, Builds oder das Programm aus und berichtet, was funktioniert und was fehlschlägt. "
             "Ändert keinen Code.", READ + ["run_command"], """
You verify that software works by actually running it.
- Find out how the project is tested or started: README, package.json, pyproject.toml, Makefile.
- Run the tests or the program. Start servers with background=true and read their log.
- Report what passed, what failed, the key error output and the most likely cause. Never modify files."""),
    _builtin("doku-writer",
             "Schreibt und aktualisiert Dokumentation: README, Anleitungen und Kommentare an komplexen Stellen – "
             "passend zum echten Code.", READ + ["edit_file", "write_file"], """
You write accurate, concise documentation.
- Base everything on the actual code: verify commands, paths and options by reading the source.
- Match the language and tone of the existing docs. Prefer short sections, tables and runnable examples.
- Report which files you created or changed."""),
    _builtin("recherche",
             "Recherchiert im Internet: Dokumentation, aktuelle Versionen, Fehlermeldungen. Liefert eine "
             "Zusammenfassung mit Quellen.", ["web_research", "web_search", "web_fetch", "read_file"], """
You research questions on the web.
- Start with web_research: pass the question plus two or three alternative queries (for example in English or with the technical terms). It reads the best pages for you.
- If the excerpts leave gaps, search again with different terms or read a promising source completely with web_fetch. Prefer official documentation, release notes and primary sources.
- Answer with a short, factual summary. Back every claim with its source number [n] and list the sources with URLs at the end.
- Say clearly when sources disagree, are outdated or something could not be verified."""),
    _builtin("test-writer",
             "Schreibt sinnvolle Tests für bestehenden Code, führt sie aus und bessert nach, bis sie laufen.",
             READ + ["edit_file", "write_file", "run_command"], """
You write focused, meaningful tests.
- Detect the test framework and conventions already in use and follow them. Without tests, use the standard one for the language.
- Cover what matters: normal cases, edge cases and error paths. No trivial or duplicate tests.
- Run the tests and fix the tests until they pass – unless they reveal a real bug in the code; then report it.
- Report which tests you added and what they cover."""),
    _builtin("refactorer",
             "Räumt Code auf: klarere Namen, weniger Duplikate, kleinere Funktionen – ohne das Verhalten zu ändern. "
             "Prüft mit den Tests.", READ + ["edit_file", "write_file", "run_command"], """
You improve code structure without changing behaviour.
- Read the code and its callers first. Work in small, safe steps: extract functions, remove duplication, clarify names.
- Keep public interfaces stable unless told otherwise. Do not add features.
- Run the tests before and after. Without tests, verify with a quick run of the affected code.
- Report what you changed and why it is clearer or safer."""),
    _builtin("security-check",
             "Sucht Sicherheitslücken: Injection, unsichere Pfade, Geheimnisse im Code, riskante Abhängigkeiten. "
             "Meldet Befunde, ändert nichts.", READ + ["run_command"], """
You audit code for security problems.
- Look for injection (SQL, shell, templates), path traversal, unsafe deserialization, missing auth checks, weak crypto, SSRF and XSS.
- Search for committed secrets: keys, tokens, passwords, .env files.
- If available, run dependency audits such as pip-audit or npm audit. Never modify files.
- Report each finding with path:line, the attack scenario, severity (hoch, mittel, niedrig) and a concrete fix."""),
    _builtin("perf-check",
             "Findet Performance-Engpässe: unnötige Schleifen, N+1-Abfragen, blockierendes I/O, große Kopien. "
             "Misst, wo möglich. Ändert nichts.", READ + ["run_command"], """
You find performance problems.
- Trace hot paths: loops over large data, repeated I/O or queries, blocking calls in async code, needless copies, missing caching.
- Measure when practical – time a script, run a benchmark or profiler. Never modify files.
- Report each issue with path:line, the expected impact and a concrete improvement, most impactful first."""),
    _builtin("ui-designer",
             "Verbessert Oberflächen: Layout, Abstände, Typografie, Farben, Zustände und Barrierefreiheit – im Stil "
             "des Projekts, nach den Leitfäden der Design-Bibliothek.",
             READ + ["edit_file", "write_file", "generate_image", "memory_search", "memory_read"], """
You improve user interfaces with restraint and precision.
- First read the design library with memory_read: "Design-Prinzipien" and "Kein AI-Slop". Look up "Typografie", "Farbe", "Layout und Abstände", "Komponenten" or "Design-Tokens" when the task touches them.
- Study the existing design tokens, components and style of the project and stay consistent with them.
- Fix alignment, spacing, typographic hierarchy, contrast (at least 4.5:1 for text), focus, hover, active, disabled, loading and empty states.
- Avoid the generic AI look: no decorative gradients, glow, emoji icons, cards around everything or filler copy.
- Prefer small, coherent changes over rewrites. Keep it accessible and responsive.
- Finish by checking your result against "UI-Review-Checkliste" and report what you changed and why in a few bullet points."""),
    _builtin("commit-writer",
             "Liest die aktuellen Änderungen und formuliert eine prägnante Commit-Nachricht. Ändert nichts.",
             READ + ["run_command"], """
You write commit messages from the actual changes.
- Inspect git status, git diff and git diff --staged. Never commit, stage or modify anything.
- Match the language and style of the existing history (git log --oneline -10).
- Write one subject line under 72 characters in the imperative mood, then a short body explaining why, if useful."""),
]


# --------------------------------------------------------------------------- Dateiformat

def squash(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[:limit - 1].rstrip() + "…"


def _unquote(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] == '"':  # YAML: \n, \t, \" und \\ auflösen
        return re.sub(r"\\(.)", lambda m: {"n": "\n", "t": "\t"}.get(m.group(1), m.group(1)), value[1:-1])
    if len(value) >= 2 and value[0] == value[-1] == "'":
        return value[1:-1].replace("''", "'")
    return value


def clean_description(text: str) -> str:
    """Beschreibungen aus Claude Code enthalten oft <example>-Blöcke. Für Liste und Werkzeug reicht der Kern."""
    text = re.sub(r"<(example|commentary)>.*?</\1>", " ", text, flags=re.S | re.I)
    text = re.sub(r"<example>.*", " ", text, flags=re.S | re.I)  # nicht geschlossener Block
    return re.sub(r"\s*(Examples?|Beispiele?)\s*:?\s*$", "", squash(text), flags=re.I)


def parse_frontmatter(text: str) -> tuple[dict, str]:
    """Liest das Frontmatter von Agents und Befehlen – bewusst ohne PyYAML, tolerant gegenüber Handarbeit."""
    match = FRONTMATTER_RX.match(text)
    if not match:
        return {}, text
    meta: dict = {}
    key = None
    for line in match.group(1).splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        item = re.match(r"^\s*-\s+(.*)$", line)
        field = re.match(r"^([A-Za-z_][\w-]*)\s*:\s*(.*)$", line)
        if key and item:  # Listeneintrag unter dem letzten Schlüssel
            if not isinstance(meta.get(key), list):
                meta[key] = []
            meta[key].append(_unquote(item.group(1)))
        elif field:
            key, value = field.group(1).lower(), field.group(2).strip()
            meta[key] = "" if value in ("|", ">", "|-", ">-") else _unquote(value)
        elif key and isinstance(meta.get(key), str):  # eingerückte Fortsetzung eines Textes
            meta[key] = f"{meta[key]} {line.strip()}".strip()
    return meta, text[match.end():]


def parse_tools(value) -> list[str] | None:
    if isinstance(value, list):
        items = value
    else:
        text = str(value or "").strip()
        if text in ("", "*"):
            return None
        items = re.split(r"[,\s]+", text.strip("[]"))
    names: list[str] = []
    for raw in items:
        key = str(raw).strip().strip("\"'")
        if not key:
            continue
        if key == "*":
            return None
        mapped = [key] if key in T.TOOL_MAP else CLAUDE_TOOLS.get(key.lower().replace("_", ""), [])
        names += [m for m in mapped if m not in names]
    return names


def parse_model(value) -> str:
    """Das Modell aus dem Frontmatter. Claude Codes Stufen kennt dieser Rechner nicht – dann eben das Hauptmodell."""
    name = str(value or "").strip().strip("\"'")
    return "" if name.lower() in ("", "inherit", "sonnet", "opus", "haiku", "default") else name


def parse_agent(text: str, source: str, path: Path) -> AgentDef | None:
    meta, body = parse_frontmatter(text)
    name = str(meta.get("name") or path.stem).strip().lower().replace(" ", "-")
    if not NAME_RX.match(name) or not body.strip():
        return None
    return AgentDef(name=name, description=clean_description(str(meta.get("description") or "")) or f"Agent {name}",
                    prompt=body.strip(), tools=parse_tools(meta.get("tools")), model=parse_model(meta.get("model")),
                    source=source, path=str(path))


# --------------------------------------------------------------------------- Laden und Speichern

def load(workspace: str | Path | None = None, include_claude: bool = True) -> dict[str, AgentDef]:
    ws = Path(workspace) if workspace else None
    sources = [("claude", CLAUDE_HOME / "agents", include_claude), ("global", HOME / "agents", True)]
    if ws:
        sources += [("claude-project", ws / ".claude" / "agents", include_claude),
                    ("project", ws / ".coder" / "agents", True)]
    agents = {a.name: a for a in BUILTIN}
    seen: set[Path] = set()
    for source, folder, enabled in sources:
        try:
            if not enabled or not folder.is_dir() or folder.resolve() in seen:
                continue  # Workspace = Benutzerordner: ~/.claude nicht doppelt lesen
            seen.add(folder.resolve())
            files = sorted(folder.glob("*.md"))[:200]
        except OSError:
            continue
        for path in files:
            try:
                agent = parse_agent(path.read_text("utf-8", errors="replace"), source, path)
            except OSError:
                continue
            if agent:
                agents[agent.name] = agent
    return agents


def folder_for(scope: str, workspace: str | Path | None) -> Path:
    if scope == "global":
        return HOME / "agents"
    if scope == "project" and workspace:
        return Path(workspace) / ".coder" / "agents"
    raise ValueError("Speicherort muss „global“ oder „project“ sein.")


def save(data: dict, workspace: str | Path | None) -> AgentDef:
    name = str(data.get("name") or "").strip().lstrip("@").lower()
    if not NAME_RX.match(name):
        raise ValueError("Name: Kleinbuchstaben, Ziffern, - und _, höchstens 40 Zeichen.")
    description = squash(str(data.get("description") or ""))
    prompt = str(data.get("prompt") or "").strip()
    if not description:
        raise ValueError("Beschreibe kurz, wofür der Agent da ist.")
    if not prompt:
        raise ValueError("Der Agent braucht Anweisungen.")
    tools = data.get("tools")
    if tools is not None:
        tools = [t for t in tools if t in T.TOOL_MAP]
    model = parse_model(data.get("model"))
    scope = str(data.get("scope") or "global")
    folder = folder_for(scope, workspace)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{name}.md"
    head = ["---", f"name: {name}", f"description: {description}"]
    if tools is not None:
        head.append(f"tools: {', '.join(tools) if tools else '[]'}")
    if model:
        head.append(f"model: {model}")
    path.write_text("\n".join(head + ["---", "", prompt, ""]), encoding="utf-8")

    original = str(data.get("original") or "").strip().lower()
    original_scope = str(data.get("original_scope") or scope)
    if original and (original, original_scope) != (name, scope) and NAME_RX.match(original) and original_scope in SCOPES:
        (folder_for(original_scope, workspace) / f"{original}.md").unlink(missing_ok=True)  # umbenannt oder verschoben
    return AgentDef(name, description, prompt, tools, model, scope, str(path))


def delete(scope: str, name: str, workspace: str | Path | None) -> None:
    if not NAME_RX.match(name):
        raise ValueError("Ungültiger Name.")
    (folder_for(scope, workspace) / f"{name}.md").unlink(missing_ok=True)


# --------------------------------------------------------------------------- Werkzeug für den Haupt-Agent

def tool_schema(agents: dict[str, AgentDef]) -> dict:
    listing = "\n".join(f"- {a.name}: {clip(a.description, 120)}" for a in agents.values())  # knapp: jeder Agent kostet Kontext
    return {
        "name": "agent",
        "kind": "agent",
        "description": (
            "Übergibt eine abgeschlossene Teilaufgabe an einen spezialisierten Sub-Agent. Er arbeitet mit eigenem "
            "Kontext und liefert einen Bericht zurück – ideal für Codesuche, Fehlersuche, Tests und Recherche, damit "
            "dein eigener Kontext frei bleibt. Er kennt den Chat nicht: beschreibe die Aufgabe vollständig.\n"
            f"Agents:\n{listing}"),
        "parameters": {"type": "object", "properties": {
            "agent": {"type": "string", "enum": list(agents), "description": "Name des Agents"},
            "task": {"type": "string", "description": "Vollständige Aufgabe mit allen nötigen Details"},
        }, "required": ["agent", "task"]},
    }
