"""Eigene Slash-Befehle („Prompts“): Markdown-Dateien, deren Text als Aufgabe gesendet wird – wie bei Claude Code.

    ---
    description: Prüft die angegebenen Dateien auf Fehler
    argument-hint: [Dateien]
    tab: code
    ---
    Prüfe $ARGUMENTS gründlich auf Fehler …

Gesucht wird in ~/.claude/commands, ~/.coder/commands und im Workspace unter .claude/commands und
.coder/commands. Unterordner ergeben Namensräume: frontend/test.md wird zu /frontend:test.

`tab` sagt, wo ein Prompt angeboten wird: code (Tab Code und Terminal), chat (Tab Chat) oder beide. Fehlt es, gilt
code – Befehle aus Claude Code sind fürs Projekt gedacht. Anlegen, ändern und löschen geht auch in der Oberfläche
(save/delete); Claude Code liest dieselben Dateien, das zusätzliche `tab` stört dort nicht.
"""

import re
from pathlib import Path

from .agents import CLAUDE_HOME, clip, parse_frontmatter, squash
from .config import HOME

NAME_RX = re.compile(r"^[\w-]+(:[\w-]+)*$")
RESERVED = {"new", "clear", "compact", "models", "model", "settings", "agents", "workspace", "memory"}
# Namen, die Oberfläche oder Terminal selbst belegen – ein neuer Prompt mit diesem Namen wäre nie erreichbar.
APP_NAMES = RESERVED | {
    "undo", "loop", "prompt", "prompts", "print", "help", "resume", "retry", "diff", "todo", "todos", "image", "paste",
    "open", "mode", "effort", "theme", "controller", "think", "status", "diktat", "buddy", "exit", "quit", "commands",
    "style", "stil", "instructions", "anweisungen", "schleife", "drucken", "bericht", "aufwand", "modus", "thema",
    "farben", "themes", "kontrolle", "bild", "denken", "sprechen", "diktieren", "voice", "mikro", "nochmal", "q",
    "userprompt", "antwortstil"}
# Wie Prompts beim Anlegen heißen dürfen: schlicht, damit sie sich tippen lassen.
SAVE_NAME_RX = re.compile(r"^[a-z0-9][a-z0-9_-]{0,39}$")
SCOPES = ("global", "project")
TABS = ("code", "talk", "all")
TAB_WORDS = {"code": "code", "projekt": "code", "chat": "talk", "talk": "talk", "reden": "talk", "all": "all",
             "beide": "all", "both": "all", "alle": "all", "überall": "all"}
MAX_TEMPLATE = 20000

# Fertige Befehle für häufige Aufgaben. Viele übergeben direkt an einen passenden Agent (@name am Anfang).
BUILTIN = [
    ("init", "CODER.md für dieses Projekt anlegen: Aufbau, Befehle, Konventionen", "",
     "Analysiere dieses Projekt und lege im Workspace eine CODER.md an: Zweck in zwei Sätzen, wichtigste Ordner und "
     "Dateien, Befehle für Installation, Start, Tests und Build, Code-Konventionen und Stolperfallen. Lies zuerst README, "
     "Paket-Manifeste und Einstiegspunkte. Höchstens 80 Zeilen. Gibt es schon eine CODER.md, AGENTS.md oder CLAUDE.md, "
     "aktualisiere sie, statt eine neue anzulegen. $ARGUMENTS"),
    ("review", "Aktuelle Änderungen auf Fehler prüfen lassen", "[Dateien]",
     "@bug-checker Prüfe die aktuellen Änderungen mit git status, git diff und git diff --staged. Ohne Git prüfe die "
     "zuletzt geänderten Dateien. Nenne echte Fehler, Randfälle und Sicherheitsprobleme mit Datei:Zeile. $ARGUMENTS"),
    ("test", "Tests finden, ausführen und Fehlschläge erklären", "[Bereich]",
     "@test-runner Finde heraus, wie dieses Projekt getestet wird, führe die Tests aus und erkläre jeden Fehlschlag. $ARGUMENTS"),
    ("write-tests", "Tests schreiben und zum Laufen bringen", "<Datei oder Bereich>",
     "@test-writer Schreibe sinnvolle Tests für: $ARGUMENTS"),
    ("fix", "Einen Fehler beheben und die Korrektur prüfen", "<Fehlermeldung>",
     "@fix-it Behebe diesen Fehler und prüfe die Korrektur:\n$ARGUMENTS"),
    ("explain", "Code oder Zusammenhänge verständlich erklären", "<Datei oder Thema>",
     "@explorer Erkläre verständlich und mit Datei:Zeile, wie das funktioniert: $ARGUMENTS"),
    ("plan", "Umsetzungsplan erstellen, ohne etwas zu ändern", "<Aufgabe>",
     "@planer Erstelle einen konkreten Umsetzungsplan für: $ARGUMENTS"),
    ("refactor", "Code aufräumen, ohne das Verhalten zu ändern", "<Datei oder Bereich>",
     "@refactorer Räume diesen Code auf, ohne das Verhalten zu ändern, und prüfe danach mit den Tests: $ARGUMENTS"),
    ("security", "Projekt auf Sicherheitslücken prüfen", "[Bereich]",
     "@security-check Prüfe dieses Projekt auf Sicherheitsprobleme. $ARGUMENTS"),
    ("perf", "Performance-Engpässe finden", "[Bereich]",
     "@perf-check Finde die wichtigsten Performance-Engpässe. $ARGUMENTS"),
    ("design", "Oberfläche verbessern: Layout, Typografie, Zustände", "<Ansicht oder Datei>",
     "@ui-designer Verbessere das Design von: $ARGUMENTS"),
    ("docs", "README und Doku an den Code anpassen", "[Datei]",
     "@doku-writer Bringe die Dokumentation auf den Stand des Codes. $ARGUMENTS"),
    ("commit", "Commit-Nachricht zu den aktuellen Änderungen vorschlagen", "",
     "@commit-writer Schlage eine Commit-Nachricht für die aktuellen Änderungen vor. $ARGUMENTS"),
    ("research", "Im Internet recherchieren, mit Quellen", "<Frage>",
     "@recherche $ARGUMENTS"),
    ("imagine", "Ein Bild erzeugen und im Workspace ablegen", "<Beschreibung>",
     "Erzeuge mit generate_image genau ein Bild: $ARGUMENTS\nSchreibe den Prompt auf Englisch und konkret – Motiv, "
     "Stil, Farben, Hintergrund, Licht. Wähle einen passenden Pfad im Workspace und nenne danach kurz, was entstanden "
     "ist und wo es liegt. Fehlt das Werkzeug, sage nur, dass kein Bilddienst läuft."),
    ("remember", "Etwas dauerhaft im Gedächtnis ablegen", "<was Coder sich merken soll>",
     "Lege das dauerhaft im Gedächtnis ab (memory_write): passender Titel, verwandte Notizen mit [[Titel]] verknüpfen, "
     "danach kurz bestätigen, was gespeichert wurde:\n$ARGUMENTS"),
    # Für beide Tabs – und die ersten, die sich im Tab Chat lohnen. Das fünfte Feld ist der Tab (fehlt: code).
    ("tldr", "Zusammenfassen: das Wichtigste in wenigen Punkten", "<Text oder Link>",
     "Fasse das Wichtigste knapp zusammen: höchstens fünf Punkte, danach ein Satz Fazit. Ist es ein Link, lies die "
     "Seite zuerst.\n\n$ARGUMENTS", "all"),
    ("translate", "Übersetzen – ins Englische oder in die genannte Sprache", "<Text>",
     "Übersetze den folgenden Text. Nennt der Anfang eine Sprache (etwa „ins Französische:“), übersetze in diese, "
     "sonst ins Englische – ist der Text schon Englisch, ins Deutsche. Antworte nur mit der Übersetzung.\n\n"
     "$ARGUMENTS", "all"),
    ("mail", "Nachricht oder E-Mail formulieren", "<worum es geht>",
     "Formuliere daraus eine gut lesbare Nachricht: bei E-Mails mit Betreff, freundlicher und klarer Ton, kurze "
     "Absätze, am Ende der konkrete nächste Schritt. Frag nur nach, wenn Empfänger oder Anlass wirklich fehlen."
     "\n\n$ARGUMENTS", "talk"),
    ("compare", "Optionen vergleichen – als Tabelle, mit Empfehlung", "<Optionen>",
     "Vergleiche diese Optionen in einer Markdown-Tabelle nach den Kriterien, auf die es hier ankommt (etwa Preis, "
     "Qualität, Vor- und Nachteile). Prüfe aktuelle Fakten im Netz und nenne die Quellen. Schließe mit einer klaren "
     "Empfehlung und für wen sie passt.\n\n$ARGUMENTS", "talk"),
]


def tab_of(value, default: str = "code") -> str:
    """„chat“, „beide“, „talk“ … → talk, all oder code."""
    return TAB_WORDS.get(str(value or "").strip().lower(), default)


def folder_for(scope: str, workspace: str | Path | None) -> Path:
    if scope == "global":
        return HOME / "commands"
    if scope == "project" and workspace:
        return Path(workspace) / ".coder" / "commands"
    raise ValueError("Speicherort muss „global“ oder „project“ sein.")


def load(workspace: str | Path | None = None, include_claude: bool = True) -> list[dict]:
    ws = Path(workspace) if workspace else None
    sources = [("claude", CLAUDE_HOME / "commands", include_claude), ("global", HOME / "commands", True)]
    if ws:
        sources += [("claude-project", ws / ".claude" / "commands", include_claude),
                    ("project", ws / ".coder" / "commands", True)]
    # Eigene Befehle gleichen Namens ersetzen die eingebauten
    found: dict[str, dict] = {}
    for name, description, hint, template, *tab in BUILTIN:
        found[name] = {"name": name, "description": description, "hint": hint, "template": template,
                       "source": "builtin", "tab": tab[0] if tab else "code", "editable": False}
    seen: set[Path] = set()
    for source, folder, enabled in sources:
        try:
            if not enabled or not folder.is_dir() or folder.resolve() in seen:
                continue
            seen.add(folder.resolve())
            files = sorted(folder.rglob("*.md"))[:300]
        except OSError:
            continue
        for path in files:
            name = ":".join(path.relative_to(folder).with_suffix("").parts).lower()
            if not NAME_RX.match(name) or name in RESERVED:
                continue
            try:
                meta, body = parse_frontmatter(path.read_text("utf-8", errors="replace"))
            except OSError:
                continue
            body = body.strip()
            if not body:
                continue
            found[name] = {
                "name": name,
                "description": squash(str(meta.get("description") or "")) or clip(squash(body.splitlines()[0]), 90),
                "hint": squash(str(meta.get("argument-hint") or "")),
                "template": body[:MAX_TEMPLATE],
                "source": source,
                "tab": tab_of(meta.get("tab")),
                # Ändern lassen sich nur Coders eigene Ordner, ohne Namensraum – den Rest übernimmt man als Kopie.
                "editable": source in SCOPES and bool(SAVE_NAME_RX.match(name)),
            }
    return sorted(found.values(), key=lambda c: c["name"])


def for_tab(found: list[dict], tab: str) -> list[dict]:
    """Was ein Tab anbietet: seine eigenen und die für beide."""
    want = "talk" if tab == "talk" else "code"
    return [c for c in found if c.get("tab", "code") in (want, "all")]


def save(data: dict, workspace: str | Path | None) -> dict:
    """Einen Prompt anlegen oder ändern. Gibt ihn so zurück, wie load() ihn liefert."""
    name = str(data.get("name") or "").strip().lstrip("/").lower()
    if not SAVE_NAME_RX.match(name):
        raise ValueError("Name: Kleinbuchstaben, Ziffern, - und _, höchstens 40 Zeichen – so, wie man ihn nach / tippt.")
    if name in APP_NAMES:
        raise ValueError(f"/{name} gehört schon zu Coder selbst – nimm einen anderen Namen.")
    template = str(data.get("template") or "").replace("\r\n", "\n").strip()
    if not template:
        raise ValueError("Der Prompt braucht einen Text.")
    if len(template) > MAX_TEMPLATE:
        raise ValueError(f"Höchstens {MAX_TEMPLATE} Zeichen.")
    description = squash(str(data.get("description") or ""))[:200] \
        or clip(squash(re.sub(r"\$(ARGUMENTS|\d)", "…", template.splitlines()[0])), 90)
    hint = squash(str(data.get("hint") or ""))[:80]
    tab = tab_of(data.get("tab"), "all")
    scope = str(data.get("scope") or "global")
    folder = folder_for(scope, workspace)
    path = folder / f"{name}.md"
    original = str(data.get("original") or "").strip().lower()
    original_scope = str(data.get("original_scope") or scope)
    # Neu angelegt, umbenannt oder verschoben: nie still einen anderen eigenen Prompt überschreiben.
    if (not original or (original, original_scope) != (name, scope)) and path.exists():
        raise ValueError(f"Es gibt schon einen eigenen Prompt /{name} – nimm einen anderen Namen.")
    folder.mkdir(parents=True, exist_ok=True)
    head = ["---", f"description: {description}"]
    if hint:
        head.append(f"argument-hint: {hint}")
    head += [f"tab: {'chat' if tab == 'talk' else 'beide' if tab == 'all' else 'code'}", "---", ""]
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(head) + template + "\n")
    if original and (original, original_scope) != (name, scope) and SAVE_NAME_RX.match(original) \
            and original_scope in SCOPES:
        (folder_for(original_scope, workspace) / f"{original}.md").unlink(missing_ok=True)  # umbenannt oder verschoben
    return {"name": name, "description": description, "hint": hint, "template": template, "source": scope,
            "tab": tab, "editable": True}


def delete(scope: str, name: str, workspace: str | Path | None) -> None:
    if not SAVE_NAME_RX.match(str(name or "")):
        raise ValueError("Ungültiger Name.")
    path = folder_for(scope, workspace) / f"{name}.md"
    if not path.is_file():
        raise ValueError(f"Einen eigenen Prompt /{name} gibt es dort nicht.")
    path.unlink()


def resolve(text: str, workspace: str | Path | None = None, include_claude: bool = True) -> tuple[str, str | None]:
    """„/review src“ → (ausgeschriebener Auftrag, „/review src“). Kein bekannter Befehl: (text, None).

    Für Stellen, an denen ein Befehl als Auftrag weitergereicht wird – etwa /loop 3x /review.
    """
    stripped = str(text or "").strip()
    if not stripped.startswith("/"):
        return stripped, None
    head, _, rest = stripped.partition(" ")
    cmd = next((c for c in load(workspace, include_claude) if c["name"] == head[1:].lower()), None)
    return (expand(cmd["template"], rest.strip()), stripped) if cmd else (stripped, None)


def expand(template: str, args: str) -> str:
    """$ARGUMENTS wird zum ganzen Rest, $1, $2 … zu einzelnen Wörtern; ohne Platzhalter kommt der Rest ans Ende."""
    words = args.split()
    text = template.replace("$ARGUMENTS", args)
    text = re.sub(r"\$(\d)", lambda m: words[int(m.group(1)) - 1] if 0 < int(m.group(1)) <= len(words) else "", text)
    if args and not re.search(r"\$ARGUMENTS|\$\d", template):
        text += f"\n\n{args}"
    return text.strip()
