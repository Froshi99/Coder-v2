"""Werkzeuge, die der Agent aufrufen kann."""

import asyncio
import atexit
import difflib
import json
import os
import platform
import re
import signal
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

from . import web

IGNORE_DIRS = {
    ".git", ".hg", ".svn", "node_modules", "__pycache__", ".venv", "venv", "env",
    "dist", "build", ".next", ".nuxt", ".idea", ".vscode", ".mypy_cache",
    ".pytest_cache", ".ruff_cache", "target", ".gradle", ".cache", "coverage", ".coder",
}
# Versteckte Ordner mit echtem Projektinhalt – alle anderen Punkt-Ordner überspringen glob und grep.
HIDDEN_KEEP = {".github", ".gitlab", ".devcontainer", ".circleci", ".husky", ".storybook"}
MAX_WALK = 200_000  # so viele Dateien durchläuft glob oder grep höchstens
MAX_LINE = 2000  # Zeichen je Zeile in read_file – eine minifizierte Datei sprengt sonst den Kontext
GREP_LIMIT = 250
IS_WINDOWS = platform.system() == "Windows"
SHELL_NAME = "PowerShell" if IS_WINDOWS else "bash"

# Windows PowerShell 5.1 hat Voreinstellungen, an denen ein Agent scheitert.
PS_PRELUDE = "; ".join((
    "[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)",
    "$OutputEncoding = [Text.UTF8Encoding]::new($false)",
    "$ProgressPreference = 'SilentlyContinue'",
    # Ohne UseBasicParsing fragt Invoke-WebRequest (auch als curl/wget) nach – im NonInteractive-Modus ein Abbruch.
    "$PSDefaultParameterValues['Invoke-WebRequest:UseBasicParsing'] = $true",
    "$PSDefaultParameterValues['Invoke-RestMethod:UseBasicParsing'] = $true",
    # „>“ schreibt sonst UTF-16.
    "$PSDefaultParameterValues['Out-File:Encoding'] = 'utf8'",
)) + "\n"
# powershell -Command meldet nur 0 oder 1 – so kommt der echte Exit-Code des letzten Befehls an.
PS_EPILOGUE = "\nif (-not $?) { if ($LASTEXITCODE) { exit $LASTEXITCODE } else { exit 1 } }"

# „Immer erlauben“ gilt bei Befehlen nur für Programm und Unterbefehl („npm test“) – nie fürs ganze Terminal.
COMPOUND_RX = re.compile(r"[;&|<>`\r\n]|\$\(")
NEVER_ALWAYS = {
    "rm", "del", "erase", "rd", "rmdir", "remove-item", "ri", "mv", "move", "move-item", "cp", "copy", "copy-item",
    "format", "diskpart", "shutdown", "restart-computer", "stop-computer", "reg", "regedit", "sudo", "su", "runas",
    "powershell", "pwsh", "cmd", "bash", "sh", "zsh", "wsl", "iex", "invoke-expression", "start-process", "saps",
    "curl", "wget", "invoke-webrequest", "iwr", "invoke-restmethod", "irm", "set-executionpolicy", "takeown",
    "icacls", "chmod", "chown", "kill", "taskkill", "stop-process", "set-content", "add-content", "out-file",
    "new-item", "ni", "set-itemproperty", "schtasks", "sc", "net", "netsh", "setx",
}
SUBCOMMANDS = {
    "git", "npm", "pnpm", "yarn", "bun", "npx", "pip", "pip3", "uv", "poetry", "cargo", "go", "dotnet", "docker",
    "docker-compose", "kubectl", "helm", "make", "mvn", "gradle", "gradlew", "composer", "deno", "rustup", "conda",
    "mamba", "flutter", "dart", "swift", "winget", "choco", "terraform", "ng", "nx", "turbo", "php",
}
SCRIPT_RUNNERS = {("npm", "run"), ("pnpm", "run"), ("yarn", "run"), ("bun", "run"), ("uv", "run"), ("poetry", "run"),
                  ("npm", "exec"), ("pnpm", "exec"), ("docker", "compose"), ("deno", "run")}
INTERPRETERS = {"python", "python3", "py", "node", "ruby", "perl"}

# Kleine Modelle übernehmen gern Parameternamen aus anderen Agenten – file_path statt path, cmd statt command.
ARG_ALIASES = {"file_path": "path", "filepath": "path", "file": "path", "filename": "path", "directory": "path",
               "dir": "path", "folder": "path", "cmd": "command", "old_str": "old_string", "new_str": "new_string",
               "old_text": "old_string", "new_text": "new_string", "regex": "pattern", "text": "content",
               "link": "url"}
ARG_SPECIAL = {"grep": {"glob": "include", "file_pattern": "include", "query": "pattern"},
               "glob": {"glob": "pattern", "query": "pattern"},
               "ask_user": {"text": "question", "prompt": "question", "query": "question", "message": "question",
                            "title": "question", "header": "question", "choices": "options", "answers": "options",
                            "suggestions": "options", "alternatives": "options", "multi": "multiple",
                            "multi_select": "multiple", "multiselect": "multiple", "multiSelect": "multiple",
                            "allow_multiple": "multiple"},
               "generate_image": {"description": "prompt", "text": "prompt", "query": "prompt", "image": "reference",
                                  "init_image": "reference", "source": "reference", "output": "path", "file": "path",
                                  "file_path": "path", "negative_prompt": "negative", "denoise": "strength",
                                  "denoising_strength": "strength", "size": "width"}}

_background: dict[int, subprocess.Popen] = {}


@dataclass
class ToolContext:
    workspace: Path
    max_output: int = 16000
    command_timeout: int = 120
    todos: list = field(default_factory=list)
    runtime: object = None  # für Werkzeuge, die Ollama brauchen: Embeddings fürs Gedächtnis und die Recherche
    checkpoint: object = None  # Sicherung der laufenden Aufgabe – vor jeder Dateiänderung ergänzt


class ToolError(Exception):
    pass


# --------------------------------------------------------------------------- Schemas

def _fn(name, kind, description, properties, required):
    return {
        "name": name,
        "kind": kind,
        "description": description,
        "parameters": {"type": "object", "properties": properties, "required": required},
    }


TOOLS = [
    _fn("read_file", "read",
        "Liest eine Textdatei und gibt sie mit Zeilennummern zurück. Lies Dateien immer, bevor du sie bearbeitest.",
        {"path": {"type": "string", "description": "Pfad, relativ zum Workspace oder absolut"},
         "offset": {"type": "integer", "description": "Startzeile (1-basiert), optional"},
         "limit": {"type": "integer", "description": "Anzahl Zeilen, Standard 400"}},
        ["path"]),
    _fn("list_dir", "read",
        "Listet Dateien und Ordner eines Verzeichnisses.",
        {"path": {"type": "string", "description": "Verzeichnis, Standard: Workspace"}},
        []),
    _fn("glob", "read",
        "Findet Dateien per Glob-Muster, z. B. '**/*.py', 'src/**/*.{ts,tsx}' oder 'README*'. Muster ohne / suchen "
        "in allen Unterordnern. Neueste zuerst.",
        {"pattern": {"type": "string"}, "path": {"type": "string", "description": "Basisordner, optional"}},
        ["pattern"]),
    _fn("grep", "read",
        "Durchsucht Dateiinhalte mit einem regulären Ausdruck. Liefert datei:zeile: text.",
        {"pattern": {"type": "string", "description": "Regex"},
         "path": {"type": "string", "description": "Ordner oder Datei, optional"},
         "include": {"type": "string", "description": "Dateifilter, z. B. '*.py' oder '*.{ts,tsx}'"},
         "ignore_case": {"type": "boolean"},
         "context": {"type": "integer", "description": "Zeilen davor und danach mitliefern, 0 bis 5"},
         "files_only": {"type": "boolean", "description": "Nur Dateien mit Trefferzahl statt der Zeilen"}},
        ["pattern"]),
    _fn("view_image", "read",
        "Sieht sich eine Bilddatei an (PNG, JPEG, GIF, WebP, BMP), etwa einen Screenshot oder ein Diagramm, und "
        "beschreibt sie samt allen sichtbaren Texten. Mit question gezielt nachfragen.",
        {"path": {"type": "string", "description": "Pfad zur Bilddatei"},
         "question": {"type": "string", "description": "Was du über das Bild wissen willst, optional"}},
        ["path"]),
    _fn("web_search", "read",
        "Sucht im Internet. Liefert Titel, URL und Kurztext der Treffer – danach die passende Seite mit web_fetch lesen.",
        {"query": {"type": "string", "description": "Suchbegriffe"},
         "max_results": {"type": "integer", "description": "Anzahl Treffer, Standard 8"}},
        ["query"]),
    _fn("web_fetch", "web",
        "Lädt eine Webseite oder Textdatei aus dem Internet (http/https) und gibt den Inhalt als lesbaren Text "
        "mit Links zurück.",
        {"url": {"type": "string", "description": "Vollständige Adresse, z. B. https://docs.python.org/3/"}},
        ["url"]),
    _fn("web_research", "web",
        "Recherchiert gründlich in einem Schritt: sucht mit mehreren Suchanfragen, liest die besten Seiten und "
        "liefert die passendsten Abschnitte mit nummerierten Quellen. Für Fragen, die mehr als eine Quelle brauchen.",
        {"question": {"type": "string", "description": "Die Frage, möglichst konkret"},
         "queries": {"type": "array", "items": {"type": "string"},
                     "description": "Weitere Suchanfragen, etwa auf Englisch oder mit Fachbegriffen, optional"},
         "max_pages": {"type": "integer", "description": "Seiten zum Lesen, Standard 5, höchstens 8"}},
        ["question"]),
    _fn("memory_search", "memory",
        "Durchsucht das Gedächtnis: verknüpfte Notizen aus früheren Chats – Vorlieben, Entscheidungen, Projektwissen.",
        {"query": {"type": "string", "description": "Suchbegriffe"}},
        ["query"]),
    _fn("memory_read", "memory",
        "Liest eine Notiz aus dem Gedächtnis samt ihren [[Links]] und den Notizen, die auf sie verweisen.",
        {"title": {"type": "string", "description": "Titel der Notiz"}},
        ["title"]),
    _fn("memory_write", "memory",
        "Legt eine Notiz im Gedächtnis an oder ergänzt sie. Markdown; verknüpfe verwandte Notizen mit [[Titel]] und "
        "ordne mit #tags. Für dauerhaftes Wissen – nie für Passwörter oder Schlüssel.",
        {"title": {"type": "string", "description": "Kurzer, eindeutiger Titel"},
         "content": {"type": "string", "description": "Inhalt in Markdown"},
         "scope": {"type": "string", "enum": ["project", "global"],
                   "description": "project: nur dieses Projekt (Standard), global: für alle Projekte"},
         "append": {"type": "boolean", "description": "true hängt an eine bestehende Notiz an, statt sie zu ersetzen"}},
        ["title", "content"]),
    _fn("edit_file", "write",
        "Ersetzt exakt old_string durch new_string in einer Datei. old_string muss eindeutig sein "
        "(inklusive Einrückung) — sonst mehr Kontext angeben oder replace_all nutzen.",
        {"path": {"type": "string"}, "old_string": {"type": "string"}, "new_string": {"type": "string"},
         "replace_all": {"type": "boolean"}},
        ["path", "old_string", "new_string"]),
    _fn("write_file", "write",
        "Erstellt eine Datei oder überschreibt sie vollständig. Für kleine Änderungen edit_file bevorzugen.",
        {"path": {"type": "string"}, "content": {"type": "string"}},
        ["path", "content"]),
    _fn("generate_image", "write",
        "Malt ein Bild aus einer Beschreibung und legt es im Workspace ab – Icons, Logos, Texturen, Platzhalter, "
        "Hintergründe, Open-Graph-Bilder. Beschreibe auf Englisch und konkret: Motiv, Stil, Farben, Hintergrund, "
        "Perspektive. Mit reference wird ein vorhandenes Bild als Vorlage umgemalt. Für Diagramme und Icons, die "
        "scharf skalieren sollen, ist selbst geschriebenes SVG die bessere Wahl.",
        {"prompt": {"type": "string", "description": "Was zu sehen sein soll – auf Englisch, ausführlich"},
         "path": {"type": "string", "description": "Zieldatei, z. B. 'assets/hero.png'. Auch .jpg, .webp und "
                                                   ".ico (Favicon). Ohne Angabe unter generated/"},
         "negative": {"type": "string", "description": "Was nicht vorkommen soll, optional"},
         "width": {"type": "integer", "description": "Breite in Pixeln, Vielfaches von 64"},
         "height": {"type": "integer", "description": "Höhe in Pixeln, Vielfaches von 64"},
         "steps": {"type": "integer", "description": "Rechenschritte, Standard 25 – mehr heißt langsamer"},
         "seed": {"type": "integer", "description": "Gleicher Seed und gleicher Prompt ergeben dasselbe Bild"},
         "reference": {"type": "string", "description": "Bilddatei als Vorlage, optional"},
         "strength": {"type": "number", "description": "Wie stark die Vorlage verändert wird, 0.1 bis 1.0"}},
        ["prompt"]),
    _fn("run_command", "exec",
        f"Führt einen {SHELL_NAME}-Befehl im Workspace aus: Tests, Builds, git, Paketmanager, Skripte. "
        "Jeder Aufruf startet neu im Workspace (cd gilt nicht für spätere Aufrufe). Keine Befehle, die auf "
        "Eingaben warten. Server und Watcher mit background=true starten.",
        {"command": {"type": "string"},
         "timeout": {"type": "integer", "description": "Sekunden, optional"},
         "background": {"type": "boolean",
                        "description": "Läuft weiter; liefert sofort PID, erste Ausgabe und Logdatei"}},
        ["command"]),
    _fn("ask_user", "ask",
        "Stellt dem Nutzer eine Rückfrage und wartet auf seine Antwort. Nur, wenn die Entscheidung wirklich bei ihm "
        "liegt und sich nicht aus dem Code klären lässt: zwei sinnvolle Wege, eine fehlende Angabe, eine folgenreiche "
        "Wahl. Gib 2 bis 4 kurze, konkrete Antworten vor, die empfohlene zuerst – frei antworten kann er immer.",
        {"question": {"type": "string", "description": "Die Frage, kurz und konkret, in der Sprache des Nutzers"},
         "options": {"type": "array", "items": {"type": "string"},
                     "description": "2 bis 4 Antwortmöglichkeiten, die empfohlene zuerst"},
         "multiple": {"type": "boolean", "description": "true: mehrere Antworten dürfen gewählt werden"}},
        ["question"]),
    _fn("todo_write", "meta",
        "Pflegt die Aufgabenliste für mehrstufige Arbeit. Übergib immer die komplette Liste.",
        {"todos": {"type": "array", "items": {"type": "object", "properties": {
            "content": {"type": "string"},
            "status": {"type": "string", "enum": ["pending", "in_progress", "completed"]}},
            "required": ["content", "status"]}}},
        ["todos"]),
]
TOOL_MAP = {t["name"]: t for t in TOOLS}


def schemas() -> list[dict]:
    return [{"type": "function", "function": {k: t[k] for k in ("name", "description", "parameters")}}
            for t in TOOLS]


def kind(name: str) -> str:
    return TOOL_MAP.get(name, {}).get("kind", "exec")


def summarize(name: str, args: dict) -> str:
    if name in ("read_file", "write_file", "edit_file", "list_dir"):
        return str(args.get("path") or ".")
    if name in ("glob", "grep"):
        return str(args.get("pattern", ""))
    if name == "run_command":
        return str(args.get("command", "")) + ("  (im Hintergrund)" if _flag(args.get("background")) else "")
    if name == "web_search":
        return str(args.get("query", ""))
    if name == "web_fetch":
        return str(args.get("url", ""))
    if name == "web_research":
        return str(args.get("question", ""))
    if name == "view_image":
        return str(args.get("path", ""))
    if name in ("memory_read", "memory_write"):
        return str(args.get("title", ""))
    if name == "memory_search":
        return str(args.get("query", ""))
    if name == "todo_write":
        return f"{len(args.get('todos') or [])} Aufgaben"
    if name == "ask_user":
        items = question_items(args)
        return items[0]["question"][:200] if items else ""
    if name == "generate_image":
        prompt = " ".join(str(args.get("prompt") or "").split())
        where = str(args.get("path") or "").strip()
        return f"{prompt[:160]} → {where}" if where else prompt[:180]
    return ""


def normalize_args(name: str, args) -> dict:
    """Übliche Fremdnamen auf die Parameter des Werkzeugs abbilden: file_path → path, cmd → command …

    Muss vor der Rechteprüfung passieren – sonst prüft sie einen anderen Pfad als den, der später geschrieben wird.
    """
    if not isinstance(args, dict):
        return {}
    tool = TOOL_MAP.get(name)
    if tool is None:
        return dict(args)
    params = tool["parameters"]["properties"]
    special = ARG_SPECIAL.get(name, {})
    out: dict = {}
    for key, value in args.items():
        target = key
        if key not in params:
            guess = special.get(key) or ARG_ALIASES.get(str(key).lower())
            if guess in params and guess not in args and guess not in out:
                target = guess
        # Aufrufe im Textformat liefern alles als Text – laut Schema zurückverwandeln.
        want = params.get(target, {}).get("type")
        if isinstance(value, str) and want in ("array", "object"):
            try:
                parsed = json.loads(value)
            except ValueError:
                parsed = None
            if isinstance(parsed, list if want == "array" else dict):
                value = parsed
        elif isinstance(value, str) and want in ("integer", "number", "boolean"):
            value = _scalar(value, want)
        out[target] = value
    return out


def _scalar(value: str, want: str):
    """'1024' wird 1024, 'true' wird True. Was sich nicht umwandeln lässt, bleibt Text – das Werkzeug meldet es dann."""
    text = value.strip().lower()
    if want == "boolean":
        if text in ("true", "1", "yes", "ja", "on"):
            return True
        return False if text in ("false", "0", "no", "nein", "off") else value
    try:
        number = float(text)
    except ValueError:
        return value
    return int(number) if want == "integer" else number


def command_prefix(command: str) -> str | None:
    """Woran „Immer erlauben“ einen Befehl wiedererkennt – etwa „npm test“, „git status“ oder „python -m pytest“.

    None heißt: dafür gibt es keinen Freibrief. Das gilt für zusammengesetzte Befehle und alles, womit sich beliebiger
    Code ausführen, Daten löschen oder Dateien überschreiben lassen – solche Befehle fragen jedes Mal.
    """
    text = str(command or "").strip()
    if not text or COMPOUND_RX.search(text):
        return None
    if text[0] in "\"'":  # "C:\Program Files\nodejs\npm.cmd" test
        end = text.find(text[0], 1)
        if end < 0:
            return None
        first, words = text[1:end], text[end + 1:].split()
    else:
        first, *words = text.split()
    exe = re.sub(r"\.(exe|cmd|bat|ps1|sh)$", "", first.replace("\\", "/").rsplit("/", 1)[-1].lower())
    if not exe or exe.startswith(("-", ".")) or exe in NEVER_ALWAYS:
        return None
    rest = [w.lower() for w in words]
    if exe in INTERPRETERS:
        if not rest or rest[0] in ("-c", "-e", "-p", "--eval", "--print", "-"):
            return None  # python -c "…" führt beliebigen Code aus
        if rest[0] == "-m":
            return f"{exe} -m {rest[1]}" if len(rest) > 1 and not rest[1].startswith("-") else None
        return None if rest[0].startswith("-") else f"{exe} {rest[0]}"
    if exe in SUBCOMMANDS:
        if not rest:
            return exe
        if rest[0].startswith("-"):
            return None
        if (exe, rest[0]) in SCRIPT_RUNNERS:
            return f"{exe} {rest[0]} {rest[1]}" if len(rest) > 1 and not rest[1].startswith("-") else None
        return f"{exe} {rest[0]}"
    return exe


def command_allowed(command: str, allow: list[str]) -> bool:
    prefix = command_prefix(command)
    return prefix is not None and f"run_command:{prefix}" in allow


# --------------------------------------------------------------------------- Genannte Dateien

FILE_MENTION_RX = re.compile(r"(?<![\w/\\.@-])((?:[\w.-]+[/\\])*[\w-][\w.-]*\.[A-Za-z][A-Za-z0-9]{0,7})(?![\w/\\-])")
MENTION_FILES = 3
MENTION_SCAN = 20_000  # so viele Dateien werden für einen bloßen Dateinamen höchstens durchsucht


def mentioned_files(ctx: ToolContext, text: str) -> list[Path]:
    """Dateien, die eine Nachricht beim Namen nennt – „Was macht app.py?“ oder „src/db.py“. Nur im Workspace.

    Ein bloßer Name zählt nur, wenn er genau einmal vorkommt; bei zweien wäre geraten, welche gemeint ist.
    """
    found: list[Path] = []
    names: dict[str, list[Path]] | None = None
    for match in FILE_MENTION_RX.finditer(text or ""):
        raw = match.group(1).replace("\\", "/").rstrip(".")
        path = resolve(ctx, raw)
        if not (path.is_file() and inside_workspace(ctx, path)):
            if "/" in raw:
                continue
            if names is None:
                names = {}
                for n, candidate in enumerate(_walk(ctx.workspace)):
                    if n >= MENTION_SCAN:
                        break
                    names.setdefault(candidate.name.lower(), []).append(candidate)
            hits = names.get(raw.lower(), [])
            if len(hits) != 1:
                continue
            path = hits[0]
        if path not in found:
            found.append(path)
        if len(found) >= MENTION_FILES:
            break
    return found


# --------------------------------------------------------------------------- Rückfragen

MAX_QUESTIONS = 4  # je Aufruf
MAX_OPTIONS = 6
OPTION_MARK_RX = re.compile(r"^\s*(?:[-*•]|\(?[0-9]{1,2}[.):]|\(?[A-Fa-f][.)])\s+")
CONTROL_RX = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]|[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]")  # Steuerzeichen im Etikett
RECOMMENDED_RX = re.compile(r"\s*[(\[](?:recommended|empfohlen|empfehlung)[)\]]\s*|\s+[–-]\s*(?:recommended|empfohlen)\s*$",
                            re.I)


def _option(raw) -> dict | None:
    """Eine Antwortmöglichkeit: Text oder {label, description} – Modelle schicken beides, unter vielen Namen."""
    if isinstance(raw, dict):
        label = next((raw[k] for k in ("label", "text", "option", "value", "title", "name", "answer") if raw.get(k)), "")
        desc = next((raw[k] for k in ("description", "desc", "detail", "details", "hint", "explanation") if raw.get(k)), "")
    else:
        label, desc = raw, ""
    label = OPTION_MARK_RX.sub("", " ".join(CONTROL_RX.sub("", str(label or "")).split()))
    recommended = bool(RECOMMENDED_RX.search(label))
    label = RECOMMENDED_RX.sub(" ", label).strip()
    if not label:
        return None
    return {"label": label[:120], "description": " ".join(str(desc or "").split())[:240], "recommended": recommended}


def _options(raw) -> list[dict]:
    if isinstance(raw, str):
        text = raw.strip()
        if text[:1] in "[{":
            try:
                raw = json.loads(text)
            except ValueError:
                pass
        if isinstance(raw, str):
            raw = re.split(r"\s*(?:\n|;|\|)\s*", text) if re.search(r"[\n;|]", text) else re.split(r",\s*", text)
    if isinstance(raw, dict):
        raw = [{"label": k, "description": v if isinstance(v, str) else ""} for k, v in raw.items()]
    out: list[dict] = []
    for item in raw if isinstance(raw, list) else []:
        option = _option(item)
        if option and option["label"].lower() not in {o["label"].lower() for o in out}:
            out.append(option)
    return out[:MAX_OPTIONS]


def question_items(args) -> list[dict]:
    """Rückfragen aus den Argumenten von ask_user: [{question, options, multiple}], höchstens vier.

    Nimmt auch die Form aus Claude Code ({questions: [{question, options: [{label, description}], multiSelect}]}).
    """
    if not isinstance(args, dict):
        return []
    raw = args.get("questions")
    if isinstance(raw, str) and raw.strip()[:1] == "[":
        try:
            raw = json.loads(raw)
        except ValueError:
            pass
    items = raw if isinstance(raw, list) and raw else [args]
    out = []
    for item in items[:MAX_QUESTIONS]:
        if isinstance(item, str):
            item = {"question": item}
        if not isinstance(item, dict):
            continue
        item = normalize_args("ask_user", item)
        text = " ".join(str(item.get("question") or "").split())
        if not text:
            continue
        out.append({"question": text[:600], "options": _options(item.get("options")),
                    "multiple": _flag(item.get("multiple"))})
    return out


# --------------------------------------------------------------------------- Helfer

def _flag(value) -> bool:
    """Modelle schicken Wahrheitswerte gern als Text."""
    return value is True or str(value).strip().lower() in ("true", "1", "yes", "ja")


def resolve(ctx: ToolContext, path: str | None) -> Path:
    p = Path(os.path.expandvars(os.path.expanduser(str(path or "."))))
    if not p.is_absolute():
        p = ctx.workspace / p
    return p.resolve()


def inside_workspace(ctx: ToolContext, path: Path) -> bool:
    try:
        path.resolve().relative_to(ctx.workspace.resolve())
        return True
    except ValueError:
        return False


def rel(ctx: ToolContext, path: Path) -> str:
    try:
        return path.relative_to(ctx.workspace).as_posix()
    except ValueError:
        return str(path)


def truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    head = int(limit * 0.6)
    tail = limit - head
    cut = len(text) - limit
    return f"{text[:head]}\n\n… [{cut} Zeichen gekürzt] …\n\n{text[-tail:]}"


def _read_text(path: Path) -> str:
    if not path.exists():
        raise ToolError(f"Datei nicht gefunden: {path}")
    if path.is_dir():
        raise ToolError(f"{path} ist ein Verzeichnis – nutze list_dir.")
    raw = path.read_bytes()
    if b"\0" in raw[:8000]:
        raise ToolError(f"{path.name} ist eine Binärdatei.")
    return raw.decode("utf-8", errors="replace")


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(text)


async def _backup(ctx: ToolContext, path: Path) -> None:
    """Vor jeder Änderung: den Zustand davor für „Rückgängig“ sichern."""
    if ctx.checkpoint is not None:
        await asyncio.to_thread(ctx.checkpoint.capture, path)


def _changes(old: str, new: str, name: str, limit: int = 400) -> tuple[str, int, int]:
    """Unified Diff für die Anzeige (gekürzt) und die Zahl geänderter Zeilen (vollständig gezählt)."""
    lines = list(difflib.unified_diff(old.splitlines(), new.splitlines(), f"a/{name}", f"b/{name}", n=2, lineterm=""))
    added = removed = 0
    for line in lines[2:]:  # die zwei Kopfzeilen nicht mitzählen – auch wenn eine Codezeile mit „++“ beginnt
        if line.startswith("@@"):
            continue
        if line.startswith("+"):
            added += 1
        elif line.startswith("-"):
            removed += 1
    if len(lines) > limit:
        lines = lines[:limit] + [f"… {len(lines) - limit} weitere Zeilen"]
    return "\n".join(lines), added, removed


def _diff(old: str, new: str, name: str, limit: int = 400) -> str:
    return _changes(old, new, name, limit)[0]


def _walk(base: Path, keep: set[str] | frozenset = frozenset()):
    """Dateien unterhalb von base – ohne Abhängigkeits-, Build- und versteckte Ordner (außer denen in keep)."""
    seen = 0
    for root, dirs, files in os.walk(base):
        dirs[:] = sorted(d for d in dirs if d in keep or (d not in IGNORE_DIRS and (not d.startswith(".")
                                                                                   or d in HIDDEN_KEEP)))
        for name in sorted(files):
            seen += 1
            if seen > MAX_WALK:
                return
            yield Path(root) / name


GLOB_CHARS = re.compile(r"[*?\[{]")


def _split_braces(body: str) -> list[str]:
    parts, depth, current = [], 0, ""
    for ch in body:
        if ch == "," and not depth:
            parts.append(current)
            current = ""
            continue
        depth += (ch == "{") - (ch == "}")
        current += ch
    return parts + [current]


def _glob_part(pattern: str) -> str:
    """Übersetzt ein Glob-Muster in einen regulären Ausdruck: **, *, ?, [abc], [!abc] und {a,b}."""
    out, i = [], 0
    while i < len(pattern):
        ch = pattern[i]
        if pattern.startswith("**/", i):
            out.append("(?:.*/)?")
            i += 3
        elif pattern.startswith("**", i):
            out.append(".*")
            i += 2
        elif ch == "*":
            out.append("[^/]*")
            i += 1
        elif ch == "?":
            out.append("[^/]")
            i += 1
        elif ch == "[" and pattern.find("]", i + 2) > 0:
            end = pattern.find("]", i + 2)
            body = pattern[i + 1:end]
            out.append("[" + ("^" + body[1:] if body.startswith("!") else body).replace("\\", "\\\\") + "]")
            i = end + 1
        elif ch == "{":
            depth, end = 0, -1
            for j in range(i, len(pattern)):
                depth += (pattern[j] == "{") - (pattern[j] == "}")
                if not depth:
                    end = j
                    break
            if end < 0:
                out.append(re.escape(ch))
                i += 1
            else:
                out.append("(?:" + "|".join(_glob_part(o) for o in _split_braces(pattern[i + 1:end])) + ")")
                i = end + 1
        else:
            out.append(re.escape(ch))
            i += 1
    return "".join(out)


def glob_regex(pattern: str, anchored: bool = False) -> re.Pattern:
    """Regex für Pfade relativ zum Basisordner. Ohne / im Muster zählt der Dateiname in jeder Tiefe."""
    text = pattern.replace("\\", "/")
    while text.startswith("./"):
        text = text[2:]
    if not anchored and "/" not in text:
        text = "**/" + text
    return re.compile("^" + _glob_part(text) + "$", re.I if IS_WINDOWS else 0)


def preview(name: str, args: dict, ctx: ToolContext) -> dict:
    """Vorschau für den Freigabedialog, ohne etwas zu verändern."""
    try:
        if name == "write_file":
            p = resolve(ctx, args.get("path"))
            old = p.read_bytes().decode("utf-8", "replace") if p.is_file() else ""
            return {"diff": _diff(old, str(args.get("content", "")), rel(ctx, p), 200), "created": not p.is_file()}
        if name == "edit_file":
            p = resolve(ctx, args.get("path"))
            text = p.read_bytes().decode("utf-8", "replace")
            planned = _plan_edit(text, str(args.get("old_string", "")), str(args.get("new_string", "")),
                                 _flag(args.get("replace_all")))
            return {"diff": _diff(text, planned[0], rel(ctx, p), 200)}
    except (OSError, ToolError):
        pass
    return {}


# --------------------------------------------------------------------------- Implementierungen

async def execute(name: str, args: dict, ctx: ToolContext) -> dict:
    """Gibt {"ok", "content" (fürs Modell), "display" (für die UI)} zurück."""
    try:
        if name not in TOOL_MAP:
            raise ToolError(f"Unbekanntes Werkzeug '{name}'. Verfügbar: {', '.join(TOOL_MAP)}")
        handler = globals()[f"_t_{name}"]
        clean = {k: v for k, v in normalize_args(name, args).items() if v is not None}
        result = await handler(ctx, **clean)
        result["content"] = truncate(result["content"], ctx.max_output)
        result.setdefault("ok", True)
        return result
    except TypeError as e:
        return {"ok": False, "content": f"Fehlerhafte Argumente für {name}: {e}", "display": {}}
    except (ToolError, web.WebError) as e:
        return {"ok": False, "content": f"Fehler: {e}", "display": {}}
    except Exception as e:  # noqa: BLE001 — Werkzeugfehler gehen ans Modell zurück
        return {"ok": False, "content": f"Fehler ({e.__class__.__name__}): {e}", "display": {}}


async def _t_read_file(ctx, path, offset=1, limit=400):
    p = resolve(ctx, path)
    text = await asyncio.to_thread(_read_text, p)
    lines = text.splitlines()
    start = max(1, int(offset))
    end = min(len(lines), start - 1 + max(1, int(limit)))

    def shown(line: str) -> str:
        return line if len(line) <= MAX_LINE else f"{line[:MAX_LINE]} … [Zeile gekürzt, {len(line)} Zeichen]"

    if not lines:
        body = "(leere Datei)"
    elif start > len(lines):
        body = f"(Die Datei hat nur {len(lines)} Zeilen.)"
    else:
        body = "\n".join(f"{i:>5}\t{shown(lines[i - 1])}" for i in range(start, end + 1))
        if end < len(lines):
            body += f"\n\n[Zeilen {start}–{end} von {len(lines)}. Mit offset={end + 1} weiterlesen.]"
    return {"content": body, "display": {"lines": max(0, end - start + 1) if lines else 0, "total": len(lines)}}


async def _t_list_dir(ctx, path="."):
    p = resolve(ctx, path)
    if not p.is_dir():
        raise ToolError(f"Kein Verzeichnis: {p}")
    entries = sorted(p.iterdir(), key=lambda e: (not e.is_dir(), e.name.lower()))
    out = []
    for e in entries[:500]:
        if e.is_dir():
            out.append(f"{e.name}/" + ("  (ignoriert)" if e.name in IGNORE_DIRS else ""))
        else:
            try:
                out.append(f"{e.name}  ({e.stat().st_size} B)")
            except OSError:
                out.append(e.name)
    if len(entries) > 500:
        out.append(f"… {len(entries) - 500} weitere")
    return {"content": "\n".join(out) or "(leer)", "display": {"count": len(entries)}}


async def _t_glob(ctx, pattern, path="."):
    raw = str(pattern).strip().replace("\\", "/")
    if not raw:
        raise ToolError("Das Muster ist leer.")
    base, anchored = resolve(ctx, path), False
    if re.match(r"^(?:[A-Za-z]:)?/", raw):  # absolutes Muster: der feste Anfang wird zum Basisordner
        parts = raw.split("/")
        fixed = []
        for part in parts:
            if GLOB_CHARS.search(part):
                break
            fixed.append(part)
        base = resolve(ctx, "/".join(fixed) or "/")
        raw, anchored = "/".join(parts[len(fixed):]), True
        if not raw:  # gar kein Platzhalter: ein einzelner Pfad
            return {"content": rel(ctx, base) if base.is_file() else "Keine Treffer.",
                    "display": {"count": int(base.is_file())}}
    if not base.is_dir():
        raise ToolError(f"Kein Verzeichnis: {base}")
    try:
        rx = glob_regex(raw, anchored)
    except re.error as e:
        raise ToolError(f"Ungültiges Muster: {e}")
    # Wer ausdrücklich in node_modules oder .github sucht, soll dort auch Treffer bekommen.
    keep = {part for part in raw.split("/") if part in IGNORE_DIRS or part.startswith(".")}

    def run():
        hits = []
        for f in _walk(base, keep):
            if rx.match(f.relative_to(base).as_posix()):
                try:
                    hits.append((f.stat().st_mtime, f))
                except OSError:
                    continue
        hits.sort(key=lambda h: h[0], reverse=True)
        return [f for _, f in hits]

    hits = await asyncio.to_thread(run)
    listing = "\n".join(rel(ctx, h) for h in hits[:200])
    if len(hits) > 200:
        listing += f"\n… {len(hits) - 200} weitere – Muster eingrenzen"
    return {"content": listing or "Keine Treffer.", "display": {"count": len(hits)}}


async def _t_grep(ctx, pattern, path=".", include=None, ignore_case=False, context=0, files_only=False):
    try:
        rx = re.compile(str(pattern), re.IGNORECASE if _flag(ignore_case) else 0)
    except re.error as e:
        raise ToolError(f"Ungültiger Regex: {e}")
    base = resolve(ctx, path)
    if not base.exists():
        raise ToolError(f"Nicht gefunden: {base}")
    around = max(0, min(int(context or 0), 5))
    only_files = _flag(files_only)
    name_rx = None
    if include:
        try:
            name_rx = re.compile("^" + _glob_part(str(include).replace("\\", "/").rsplit("/", 1)[-1]) + "$",
                                 re.I if IS_WINDOWS else 0)
        except re.error as e:
            raise ToolError(f"Ungültiger Dateifilter: {e}")

    def run():
        out, files, total = [], [], 0
        candidates = [base] if base.is_file() else _walk(base)
        for f in candidates:
            if name_rx and not name_rx.match(f.name):
                continue
            try:
                if f.stat().st_size > 2_000_000:
                    continue
                raw = f.read_bytes()
            except OSError:
                continue
            if b"\0" in raw[:4000]:
                continue
            lines = raw.decode("utf-8", "replace").splitlines()
            hits = [n for n, line in enumerate(lines) if rx.search(line)]
            if not hits:
                continue
            name = rel(ctx, f)
            files.append((name, len(hits)))
            total += len(hits)
            if only_files:
                continue
            hit_set, last = set(hits), -1
            for n in hits:
                start, stop = max(0, n - around, last + 1), min(len(lines), n + around + 1)
                if around and out and last >= 0 and start > last + 1:
                    out.append("--")
                for k in range(start, stop):
                    sep = ":" if k in hit_set else "-"
                    line = lines[k].rstrip() if around else lines[k].strip()
                    out.append(f"{name}{sep}{k + 1}{sep} {line[:240]}")
                last = max(last, stop - 1)
                if len(out) >= GREP_LIMIT:
                    return out, files, total, True
        return out, files, total, False

    out, files, total, capped = await asyncio.to_thread(run)
    if only_files:
        text = "\n".join(f"{name} ({count})" for name, count in files[:500]) or "Keine Treffer."
    else:
        text = "\n".join(out) or "Keine Treffer."
        if capped:
            text += "\n… Trefferlimit erreicht – Suche eingrenzen oder files_only=true nutzen."
    return {"content": text, "display": {"count": total, "files": len(files)}}


async def _t_web_search(ctx, query, max_results=8):
    results = await web.search(str(query), max(1, min(int(max_results), 20)))
    lines = [f"{i}. {r['title']}\n   {r['url']}" + (f"\n   {r['snippet']}" if r["snippet"] else "")
             for i, r in enumerate(results, 1)]
    return {"content": "\n\n".join(lines) or "Keine Treffer.", "display": {"count": len(results)}}


async def _t_web_fetch(ctx, url):
    page = await web.fetch(str(url))
    head = f"# {page['title']}\n" if page["title"] else ""
    return {"content": f"{head}Quelle: {page['url']}\n\n{page['text'] or '(kein lesbarer Text)'}",
            "display": {"chars": len(page["text"]), "status": page["status"], "url": page["url"]}}


async def _t_web_research(ctx, question, queries=None, max_pages=5):
    from . import recall
    if isinstance(queries, str):
        queries = [q.strip() for q in re.split(r"[\n;|]", queries) if q.strip()]
    try:
        embed = await recall.embedder(ctx.runtime)
    except Exception:  # noqa: BLE001 — ohne Embeddings zählen nur Stichworte
        embed = None
    report = await web.research(str(question), [str(q) for q in queries or []], max(1, min(int(max_pages), 8)), embed)
    if not report["sources"]:
        return {"ok": False, "content": "Keine Treffer. Andere Suchbegriffe versuchen.", "display": {"count": 0}}
    lines = [f"Research: {report['question']}", "Queries: " + " · ".join(report["queries"]), "", "Sources:"]
    lines += [f"[{s['n']}] {s['title']} — {s['url']}" for s in report["sources"]]
    if report["failed"]:
        lines.append("Not readable: " + ", ".join(report["failed"][:5]))
    lines += ["", "Excerpts:"]
    lines += [f"[{e['n']}] {e['text']}\n" for e in report["excerpts"]]
    lines.append("Cite claims with [n]. If the excerpts do not answer the question, read a source with web_fetch "
                 "or research again with other queries.")
    return {"content": "\n".join(lines),
            "display": {"count": len(report["sources"]), "sources": report["sources"], "queries": report["queries"]}}


async def _t_view_image(ctx, path, question=None):
    raise ToolError("view_image steht nur im Agenten zur Verfügung.")


async def _t_generate_image(ctx, prompt, **kw):
    raise ToolError("generate_image steht nur im Agenten zur Verfügung.")


async def _t_ask_user(ctx, question, **kw):
    raise ToolError("ask_user steht nur im Agenten zur Verfügung.")


SLUG_RX = re.compile(r"[^a-z0-9]+")
# Endungen, die ein erzeugtes Bild tragen darf – und solche, die durch .png ersetzt werden, statt daran zu kleben.
IMAGE_OUT_EXT = (".png", ".jpg", ".jpeg", ".webp", ".ico")
IMAGE_SWAP_EXT = (".gif", ".bmp", ".tif", ".tiff", ".avif", ".svg", ".heic", ".jfif")


def image_target(ctx: ToolContext, path: str | None, prompt: str) -> Path:
    """Wohin ein erzeugtes Bild kommt: die gewünschte Datei – oder ein benannter Platz unter generated/."""
    slug = SLUG_RX.sub("-", " ".join(str(prompt or "").split()).lower()).strip("-")[:48].strip("-") or "bild"
    wanted = str(path or "").strip()
    if wanted:
        p = resolve(ctx, wanted)
        if p.is_dir() or wanted[-1] in "/\\":
            return p / f"{slug}.png"
        if p.suffix.lower() in IMAGE_OUT_EXT:
            return p
        # .gif wird zu .png, alles andere behält seinen Namen und bekommt .png dazu – „logo.v2“ bleibt erkennbar.
        return p.with_suffix(".png") if p.suffix.lower() in IMAGE_SWAP_EXT else p.with_name(p.name + ".png")
    base = ctx.workspace / "generated"
    p = base / f"{slug}.png"
    for n in range(2, 100):  # ohne Zielangabe nie ein vorhandenes Bild überschreiben
        if not p.exists():
            break
        p = base / f"{slug}-{n}.png"
    return p


async def save_binary(ctx: ToolContext, path: Path, data: bytes) -> None:
    """Binärdatei schreiben – vorher sichern, damit „Rückgängig“ auch erzeugte Bilder zurücknimmt."""
    await _backup(ctx, path)
    await asyncio.to_thread(_write_bytes, path, data)


def _write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


async def _t_write_file(ctx, path, content):
    p = resolve(ctx, path)
    content = str(content)
    existed = p.is_file()
    old = p.read_bytes().decode("utf-8", "replace") if existed else ""
    if "\r\n" in old and "\r\n" not in content:
        content = _adapt(old, content)  # eine Windows-Datei bleibt eine – sonst ändert sich jede Zeile
    await _backup(ctx, p)
    await asyncio.to_thread(_write_text, p, content)
    diff, add, rem = _changes(old, content, rel(ctx, p))
    verb = "überschrieben" if existed else "erstellt"
    return {"content": f"{rel(ctx, p)} {verb} ({len(content.splitlines())} Zeilen).",
            "display": {"diff": diff, "added": add, "removed": rem, "created": not existed}}


NUMBERED_RX = re.compile(r"^ *\d+\t")


def _strip_numbers(text: str) -> str | None:
    """Zeilennummern, die ein Modell aus der Ausgabe von read_file mitkopiert hat – oder None, wenn keine da sind."""
    lines = text.split("\n")
    filled = [line for line in lines if line.strip()]
    if not filled or not all(NUMBERED_RX.match(line) for line in filled):
        return None
    return "\n".join(NUMBERED_RX.sub("", line, count=1) for line in lines)


def _adapt(text: str, snippet: str) -> str:
    """Zeilenenden des Ausschnitts an die Datei angleichen."""
    return snippet.replace("\r\n", "\n").replace("\n", "\r\n") if "\r\n" in text else snippet


def _indent_delta(window: list[str], old_lines: list[str]) -> tuple[str, str] | None:
    """Unterscheidet sich die Einrückung überall um denselben Vorsatz? Dann ("+" oder "-", Vorsatz)."""
    delta = None
    for file_line, old_line in zip(window, old_lines):
        f, o = file_line.rstrip(), old_line.rstrip()
        if not f.strip() and not o.strip():
            continue
        if f.strip() != o.strip():
            return None
        fi, oi = f[:len(f) - len(f.lstrip())], o[:len(o) - len(o.lstrip())]
        if fi.endswith(oi):
            current = ("+", fi[:len(fi) - len(oi)])
        elif oi.endswith(fi):
            current = ("-", oi[:len(oi) - len(fi)])
        else:
            return None  # Tabs gegen Leerzeichen: lieber nichts raten
        if delta is None:
            delta = current
        elif current != delta:
            return None
    return delta if delta and delta[1] else None


def _flexible(text: str, old: str, new: str) -> tuple[str, str] | None:
    """Findet old_string trotz Leerzeichen am Zeilenende oder einheitlich anderer Einrückung – nur eindeutige Treffer.

    Bei anderer Einrückung wird new_string um denselben Versatz verschoben, damit die Struktur erhalten bleibt.
    """
    newline = "\r\n" if "\r\n" in text else "\n"
    file_lines = text.split(newline)
    old_lines = old.replace("\r\n", "\n").strip("\n").split("\n")
    new_lines = new.replace("\r\n", "\n").strip("\n").split("\n")
    size = len(old_lines)
    if not any(line.strip() for line in old_lines) or size > len(file_lines):
        return None
    windows = range(len(file_lines) - size + 1)
    exact = [i for i in windows
             if all(a.rstrip() == b.rstrip() for a, b in zip(file_lines[i:i + size], old_lines))]
    if len(exact) == 1:
        i, replacement, how = exact[0], new_lines, "Leerzeichen am Zeilenende ignoriert"
    elif exact:
        return None
    else:
        shifted = [(i, d) for i in windows if (d := _indent_delta(file_lines[i:i + size], old_lines))]
        if len(shifted) != 1:
            return None
        i, (sign, pad) = shifted[0]
        replacement = []
        for line in new_lines:
            if not line.strip():
                replacement.append(line)
            elif sign == "+":
                replacement.append(pad + line)
            elif line.startswith(pad):
                replacement.append(line[len(pad):])
            else:
                return None
        how = "Einrückung an die Datei angepasst"
    return newline.join(file_lines[:i] + replacement + file_lines[i + size:]), how


def _plan_edit(text: str, old: str, new: str, replace_all: bool) -> tuple[str, int, str]:
    """Neuer Dateiinhalt, Zahl der Ersetzungen und ein Hinweis, falls nicht exakt ersetzt wurde."""
    if not old:
        raise ToolError("old_string ist leer. Für neue Dateien write_file nutzen.")
    if old == new:
        raise ToolError("old_string und new_string sind identisch.")
    attempts = [(old, new, "")]
    unnumbered = _strip_numbers(old)
    if unnumbered is not None:
        attempts.append((unnumbered, _strip_numbers(new) or new, "Zeilennummern aus read_file entfernt"))
    for o, n, why in attempts:
        o2, n2 = _adapt(text, o), _adapt(text, n)
        count = text.count(o2)
        if count > 1 and not replace_all:
            raise ToolError(f"old_string kommt {count}× vor. Mehr Kontext angeben oder replace_all=true setzen.")
        if count:
            return (text.replace(o2, n2) if replace_all else text.replace(o2, n2, 1)), (count if replace_all else 1), why
    for o, n, why in attempts:
        found = _flexible(text, o, n)
        if found:
            return found[0], 1, ", ".join(part for part in (why, found[1]) if part)
    hint = ""
    first = old.strip().splitlines()[0].strip() if old.strip() else ""
    if first:
        for number, line in enumerate(text.splitlines(), 1):
            if first in line:
                hint = f" Ähnliche Zeile {number}: {line.strip()[:160]!r} – Einrückung/Leerzeichen prüfen und Datei neu lesen."
                break
    raise ToolError(f"old_string wurde nicht gefunden.{hint}")


async def _t_edit_file(ctx, path, old_string, new_string, replace_all=False):
    p = resolve(ctx, path)
    text = await asyncio.to_thread(_read_text, p)
    try:
        new_text, count, note = _plan_edit(text, str(old_string), str(new_string), _flag(replace_all))
    except ToolError as e:
        raise ToolError(f"{rel(ctx, p)}: {e}") from None
    if new_text == text:
        raise ToolError(f"{rel(ctx, p)}: Die Ersetzung ändert nichts.")
    await _backup(ctx, p)
    await asyncio.to_thread(_write_text, p, new_text)
    diff, add, rem = _changes(text, new_text, rel(ctx, p))
    message = f"{rel(ctx, p)} bearbeitet ({count} {'Ersetzung' if count == 1 else 'Ersetzungen'})."
    if note:
        message += f" Hinweis: {note} – prüfe das Ergebnis."
    return {"content": message, "display": {"diff": diff, "added": add, "removed": rem}}


def _shell(command: str) -> tuple[list[str], dict]:
    if IS_WINDOWS:
        return (["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", PS_PRELUDE + command + PS_EPILOGUE],
                {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW})
    return ["/bin/bash", "-lc", command], {"start_new_session": True}


def _shell_env(**extra) -> dict:
    return {**os.environ, "PYTHONIOENCODING": "utf-8", "NO_COLOR": "1", **extra}


async def _t_run_command(ctx, command, timeout=None, background=False):
    if _flag(background):
        return await _run_background(ctx, command)
    timeout = max(1, min(int(timeout or ctx.command_timeout), 1800))
    argv, extra = _shell(command)
    proc = await asyncio.create_subprocess_exec(
        *argv, cwd=str(ctx.workspace), stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT, env=_shell_env(), **extra,
    )
    timed_out = False
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), timeout)
    except (asyncio.TimeoutError, asyncio.CancelledError) as e:
        timed_out = isinstance(e, asyncio.TimeoutError)
        _kill_tree(proc.pid)
        try:
            out, _ = await asyncio.wait_for(proc.communicate(), 5)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            out = b""
        if not timed_out:
            raise
    text = out.decode("utf-8", errors="replace").replace("\r\n", "\n").strip()
    code = proc.returncode
    if timed_out:
        status = (f"[Timeout nach {timeout}s – Prozess beendet. Läuft der Befehl dauerhaft (Server, Watcher)? "
                  "Dann mit background=true starten.]")
    else:
        status = f"[Exit-Code {code}]"
    return {"ok": code == 0 and not timed_out,
            "content": f"{text}\n{status}" if text else status,
            "display": {"exit_code": code, "timed_out": timed_out}}


async def _run_background(ctx, command):
    logs = Path(tempfile.gettempdir()) / "coder-logs"
    logs.mkdir(exist_ok=True)
    log = logs / f"{time.strftime('%Y%m%d-%H%M%S')}-{os.getpid()}-{len(_background) + 1}.log"
    argv, extra = _shell(command)
    with open(log, "wb") as out:
        proc = subprocess.Popen(argv, cwd=str(ctx.workspace), stdin=subprocess.DEVNULL, stdout=out,
                                stderr=subprocess.STDOUT, env=_shell_env(PYTHONUNBUFFERED="1"), **extra)
    _background[proc.pid] = proc
    for _ in range(16):  # bis zu 4 s: erste Ausgabe abwarten oder ein sofortiges Scheitern erkennen
        await asyncio.sleep(0.25)
        if proc.poll() is not None:
            break
    tail = log.read_bytes()[-4000:].decode("utf-8", "replace").replace("\r\n", "\n").strip()
    code = proc.poll()
    if code is None:
        stop = f"taskkill /T /F /PID {proc.pid}" if IS_WINDOWS else f"kill -- -{proc.pid}"
        status = f"[Läuft im Hintergrund · PID {proc.pid} · Log: {log} · Beenden: {stop}]"
    else:
        _background.pop(proc.pid, None)
        status = f"[Sofort beendet · Exit-Code {code} · Log: {log}]"
    return {"ok": code in (None, 0), "content": f"{tail}\n{status}" if tail else status,
            "display": {"background": True, "pid": proc.pid, "exit_code": code, "log": str(log)}}


def stop_background() -> None:
    """Hintergrundprozesse sollen Coder nicht überleben – sonst bleiben Ports belegt."""
    for pid, proc in list(_background.items()):
        if proc.poll() is None:
            _kill_tree(pid)
    _background.clear()


atexit.register(stop_background)


def _kill_tree(pid: int) -> None:
    try:
        if IS_WINDOWS:
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(pid)], capture_output=True,
                           creationflags=subprocess.CREATE_NO_WINDOW)
        else:
            os.killpg(os.getpgid(pid), signal.SIGKILL)
    except (OSError, ProcessLookupError):
        pass


async def _t_memory_search(ctx, query):
    from . import recall
    hits = await recall.search(str(query), ctx.workspace, ctx.runtime)
    lines = [f"- [[{h['title']}]] ({'global' if h['vault'] == 'global' else 'Projekt'}"
             f"{''.join(' #' + t for t in h['tags'])}): {h['snippet']}" for h in hits]
    return {"content": "\n".join(lines) or "Keine passenden Notizen.", "display": {"count": len(hits)}}


async def _t_memory_read(ctx, title):
    from . import memory
    try:
        note = await asyncio.to_thread(memory.read, str(title), ctx.workspace)
    except KeyError:
        raise ToolError(f"Keine Notiz „{title}“. Mit memory_search nach ähnlichen Titeln suchen.")
    back = ", ".join(f"[[{b['title']}]]" for b in note["backlinks"]) or "keine"
    return {"content": f"# {note['title']}\n{note['content']}\n\n[Verlinkt von: {back}]",
            "display": {"note": note["title"], "vault": note["vault"], "lines": len(note["content"].splitlines())}}


async def _t_memory_write(ctx, title, content, scope="project", append=False):
    from . import memory
    vault = "global" if str(scope).lower() == "global" else "project"
    try:
        saved = await asyncio.to_thread(memory.write, str(title), str(content), ctx.workspace, vault, _flag(append))
    except ValueError as e:
        raise ToolError(str(e))
    diff, add, rem = _changes(saved["old"], saved["new"], f"{saved['title']}.md")
    verb = "angelegt" if saved["created"] else "ergänzt" if _flag(append) else "aktualisiert"
    return {"content": f"Notiz [[{saved['title']}]] {verb} ({'global' if vault == 'global' else 'Projekt'}).",
            "display": {"diff": diff, "added": add, "removed": rem, "created": saved["created"],
                        "note": saved["title"], "vault": vault}}


async def _t_todo_write(ctx, todos):
    clean = []
    for t in todos or []:
        if isinstance(t, dict) and t.get("content"):
            status = t.get("status") if t.get("status") in ("pending", "in_progress", "completed") else "pending"
            clean.append({"content": str(t["content"]), "status": status})
    ctx.todos[:] = clean
    mark = {"pending": "[ ]", "in_progress": "[~]", "completed": "[x]"}
    text = "\n".join(f"{mark[t['status']]} {t['content']}" for t in clean) or "(leer)"
    return {"content": "Aufgabenliste aktualisiert:\n" + text, "display": {"todos": clean}}
