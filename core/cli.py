"""Terminal-Modus: derselbe Agent wie in der App – mit Companion, Befehlen und Live-Anzeige.

Terminal verbindet die Ereignisse des Agenten mit der Ausgabe und die Eingabe mit den Befehlen:
- Antworten laufen durch termmd: Wort für Wort, sauber umbrochen, Tabellen und Code gesetzt. Werkzeugaufrufe, die
  ein Modell als Text schreibt, erscheinen gar nicht erst.
- Eingaben kommen aus lineedit: Tab vervollständigt, ↑/↓ blättert im Verlauf, Umschalt+Enter macht eine neue Zeile.
- Während der Agent arbeitet, zeigt die Statuszeile, was passiert – und was du schon tippst. Enter reiht die
  Nachricht ein, der Agent liest sie vor seinem nächsten Schritt. Esc oder Strg+C stoppen ihn.
- Freigaben brauchen eine Taste: j, i oder n. Rückfragen des Agenten beantwortet eine Auswahlliste.
- Umschalt+Tab wechselt den Modus reihum: Normal, Auto-Edit, Planen, Chat.
"""

import asyncio
import io
import os
import random
import re
import signal
import sys
import textwrap
import time
import uuid
from pathlib import Path

from . import __version__
from . import agents as agents_mod
from . import commands as commands_mod
from . import memory as memory_mod
from . import checkpoints, imagegen, lineedit, optimizer, power, preprompt, recall, report, sessions, vision
from . import effort as effort_mod
from . import personal as personal_mod
from . import loop as loop_mod
from . import term as T
from . import termmd
from .agent import Agent, AgentError
from . import speech as speech_mod
from .companion import WIDTH, Companion
from .config import CLI_THEMES, HOME, PERMISSION_MODES, blocked_workspace, normalize_path
from .ollama import OllamaError
from .runtime import Runtime

ANSI_RX = T.ANSI_RX
IMAGE_RX = re.compile(r'"([^"\n]+\.(?:png|jpe?g|gif|webp|bmp))"|\'([^\'\n]+\.(?:png|jpe?g|gif|webp|bmp))\''
                      r'|((?:[A-Za-z]:)?[^\s"\']+\.(?:png|jpe?g|gif|webp|bmp))(?=\s|$)', re.I)
HISTORY = HOME / "cli_history"

VERB = {"read_file": "Lesen", "list_dir": "Ordner", "glob": "Dateien suchen", "grep": "Durchsuchen",
        "view_image": "Bild ansehen", "web_search": "Websuche", "web_fetch": "Webseite", "web_research": "Recherche",
        "memory_search": "Gedächtnis durchsuchen", "memory_read": "Notiz lesen", "memory_write": "Notiz speichern",
        "edit_file": "Bearbeiten", "write_file": "Schreiben", "run_command": "Ausführen", "agent": "Delegieren",
        "generate_image": "Bild malen", "ask_user": "Rückfrage"}
APPROVAL = {"edit_file": "Datei bearbeiten?", "write_file": "Datei schreiben?", "run_command": "Befehl ausführen?",
            "web_fetch": "Webseite öffnen?", "web_research": "Im Internet recherchieren?",
            "generate_image": "Bild erzeugen und speichern?"}
MODE_LABEL = {"chat": "Chat", "ask": "Normal", "auto-edit": "Auto-Edit", "plan": "Planen", "yolo": "Autonom"}
MODE_HINT = {"chat": "reden, fragen, erklären – ändert nichts, führt nichts aus",
             "ask": "liest frei, fragt vor Änderungen und Befehlen",
             "auto-edit": "Dateien im Workspace frei, Befehle mit Freigabe",
             "plan": "nur lesen und einen Plan vorlegen – danach umsetzen",
             "yolo": "alles ohne Rückfrage – nur, wo das unkritisch ist"}
MODE_STYLE = {"chat": "code", "auto-edit": "warn", "plan": "accent", "yolo": "error"}
# So tippt man die Modi: deutsch, englisch, kurz.
MODE_ALIASES = {"normal": "ask", "fragen": "ask", "standard": "ask", "default": "ask", "reden": "chat",
                "gespräch": "chat", "auto": "auto-edit", "autoedit": "auto-edit", "edit": "auto-edit",
                "planen": "plan", "autonom": "yolo", "bypass": "yolo"}
# Umschalt+Tab: reihum wie in Claude Code. Autonom bleibt draußen – dahin kommt man nie aus Versehen.
MODE_CYCLE = ("ask", "auto-edit", "plan", "chat")
PLAN_GO = "Setze den Plan jetzt Schritt für Schritt um und prüfe am Ende, ob alles läuft."
REASON_LABEL = {"end": "prüft das Ergebnis", "interval": "schaut nach dem Rechten", "stuck": "hilft aus der Sackgasse"}
VAULT_LABEL = {"project": "Projekt", "global": "Global", "library": "Bibliothek"}
HELP = [
    ("Chat", [("/new", "neuer Chat"), ("/resume [nr|wort]", "frühere Chats fortsetzen – auch per Wort im Titel"),
              ("/retry", "letzten Auftrag noch einmal"), ("/compact", "Verlauf verdichten")]),
    ("Änderungen", [("/diff", "was der letzte Auftrag geändert hat"), ("/undo", "Dateiänderungen zurücknehmen"),
                    ("/todo", "Aufgabenliste des Agenten")]),
    ("Arbeit", [("/loop [5m|3x] auftrag", "denselben Auftrag wiederholen – /loop stop beendet"),
                ("/prompt text", "den Auftrag schärfen lassen, bevor er losgeht"),
                ("/print [datei]", "Bericht zum Ausdrucken – für eine Abgabe oder den Prüfer"),
                ("/commands", "fertige Aufgaben: /review, /test, /fix …"),
                ("/agents", "Spezialisten – mit @name ansprechen")]),
    ("Gedächtnis", [("/memory", "alle Notizen im Überblick"), ("/memory titel", "eine Notiz lesen"),
                    ("/memory suche", "nach Bedeutung und Stichworten suchen")]),
    ("Bilder", [("/image pfad", "Bild an die nächste Nachricht hängen"), ("/paste", "Bild aus der Zwischenablage"),
                ("/imagine beschreibung", "ein Bild erzeugen lassen"), ("/open [pfad]", "Datei oder Ordner öffnen")]),
    ("Einstellungen", [("/model [name|nr]", "Modelle anzeigen oder wechseln"),
                       ("/mode [modus]", "chat · normal · auto-edit · planen · autonom – Umschalt+Tab wechselt"),
                       ("/effort [stufe]", "Aufwand: niedrig · mittel · hoch · max"),
                       ("/anweisungen [text]", "eigene Anweisungen: wer du bist, wie Coder arbeiten soll"),
                       ("/stil [name]", "Antwortstil: normal · knapp · ausführlich · erklärend · förmlich"),
                       ("/theme [name]", "Farben: dunkel · hell · farbenblind · schlicht"),
                       ("/workspace [pfad]", "Ordner anzeigen oder wechseln"),
                       ("/controller [an|aus|modell]", "Kontrolle durch ein zweites Modell"),
                       ("/think [an|aus]", "Gedanken des Modells mitlesen"), ("/status", "Modell, GPU, Kontext, Token")]),
    ("Sonst", [("/diktat", "sprechen statt tippen – der Text landet in der Eingabe"),
               ("/buddy [streicheln|name X|aus|an]", "dein Axolotl"), ("/help", "diese Übersicht"),
               ("/exit", "beenden")]),
]
ALIASES = {"?": "help", "clear": "new", "models": "model", "kontrolle": "controller", "bild": "image",
           "rückgängig": "undo", "drucken": "print", "bericht": "print", "schleife": "loop", "todos": "todo",
           "öffne": "open", "nochmal": "retry", "denken": "think", "gedächtnis": "memory", "quit": "exit", "q": "exit",
           "aufwand": "effort", "modus": "mode", "thema": "theme", "farben": "theme", "themes": "theme",
           "sprechen": "diktat", "diktieren": "diktat", "voice": "diktat", "mikro": "diktat",
           "anweisungen": "instructions", "userprompt": "instructions", "persönlich": "instructions",
           "stil": "style", "antwortstil": "style"}
MARKS_RX = re.compile(r"\b(test|tests|pytest|jest|vitest|unittest)\b")
DOCK_LINES = 3  # so viele Zeilen der laufenden Eingabe bleiben während der Arbeit sichtbar
DOCK_MIN_ROWS = 14  # darunter ist das Fenster zu flach für den Rahmen – dann nur die Statuszeile


def open_path(path) -> bool:
    """Datei oder Ordner mit dem Standardprogramm des Systems öffnen."""
    import subprocess
    target = str(path)
    try:
        if os.name == "nt":
            os.startfile(target)  # noqa: S606 – der Nutzer hat es selbst verlangt
        elif sys.platform == "darwin":
            subprocess.Popen(["open", target])
        else:
            subprocess.Popen(["xdg-open", target])
        return True
    except (OSError, AttributeError, ValueError):
        return False


def width(text: str) -> int:
    return T.width(text)


def clip(text: str, limit: int) -> str:
    return T.clip(text, limit)


def duration(seconds: float) -> str:
    seconds = int(round(seconds))
    return f"{seconds} s" if seconds < 60 else f"{seconds // 60} min {seconds % 60:02d} s"


def ago(ts: float) -> str:
    minutes = int((time.time() - (ts or 0)) / 60)
    if minutes < 1:
        return "gerade eben"
    if minutes < 60:
        return f"vor {minutes} min"
    if minutes < 48 * 60:
        return f"vor {minutes // 60} h"
    return time.strftime("%d.%m.%Y", time.localtime(ts))


def number(n: int) -> str:
    return f"{n:,}".replace(",", ".")


def diff_rows(diff: str, st: "T.Styles", limit: int, room: int) -> list[str]:
    """Ein Unified Diff als Zeilen mit Zeilennummern: − rot, + grün, Kontext gedimmt."""
    rows, old, new, hidden = [], 0, 0, 0
    for line in (diff or "").splitlines():
        if line.startswith(("---", "+++")):
            continue
        hunk = re.match(r"@@ -(\d+)(?:,\d+)? \+(\d+)", line)
        if hunk:
            if rows and len(rows) < limit:
                rows.append(st("     ⋮", "dim"))
            old, new = int(hunk.group(1)), int(hunk.group(2))
            continue
        sign, body = line[:1], line[1:]
        if sign == "+":
            num, style, new = new, "ok", new + 1
        elif sign == "-":
            num, style, old = old, "error", old + 1
        else:
            num, style, old, new, sign = new, "dim", old + 1, new + 1, " "
        if len(rows) >= limit:
            hidden += 1
            continue
        text = T.cut(body, max(10, room - 8))
        rows.append(st(f"{num:>4} ", "dim") + st(f"{'−' if sign == '-' else sign} {text}", style))
    if hidden:
        rows.append(st(f"     … {hidden} weitere Zeilen", "dim"))
    return rows


class Terminal:
    def __init__(self, rt: Runtime, console: "lineedit.Console | None | bool" = None):
        self.rt = rt
        self.st = T.Styles(theme=rt.cfg.get("cli_theme"))
        self.g = T.glyphs()
        self.buddy = Companion.load()
        self.session = sessions.new(rt.cfg["workspace"], rt.cfg.get("model", ""))
        self.images: list[str] = []
        self.turn: asyncio.Future | None = None
        self.loop: "loop_mod.Loop | None" = None  # laufende Schleife
        self.last_sent: tuple[str, str | None] | None = None  # für /retry
        self.sigint_at = 0.0
        self.commands: dict[str, str] = {}
        self.labels: dict[str, str] = {}  # Werkzeugaufruf → Name in der Statuszeile
        self.context: dict = {}
        self.shown_plan: int | None = None
        self.inbox: list[dict] = []  # während der Arbeit geschrieben – der Agent liest es vor seinem nächsten Schritt
        self.prefill = ""  # steht beim nächsten Prompt schon in der Eingabe
        self.plan_offer = False  # der letzte Auftrag im Modus Planen endete mit einem Plan
        self.aloop: asyncio.AbstractEventLoop | None = None  # für Umschalt+Tab aus dem Eingabe-Thread
        # Eingabe: eigene Tasten in der Windows-Konsole, sonst input()
        self.console = (lineedit.open_console() if console is None else console) or None
        self.history = lineedit.History(HISTORY)
        self.editor = None
        self.poller = None
        if self.console:
            self.editor = lineedit.LineEditor(self.console.read, self.write, more=self.console.more_typed,
                                              pending=self.console.waiting, history=self.history, styles=self.st)
            self.poller = lineedit.Poller(self.console)
            self.editor.on_shift_tab = self.shift_tab
        # Ohne eigene Konsole: GNU readline, wo es das gibt (macOS, Linux) – unter Windows bleibt input() schlicht.
        self.readline = (not self.console and os.name != "nt" and sys.stdin.isatty()
                         and lineedit.readline_setup(self.complete, HISTORY))
        self.asking = False
        self.cache = {"stamp": 0.0, "commands": [], "agents": [], "notes": [], "models": []}
        # Anzeige
        self.status: tuple[str, str, float] | None = None
        self.shown: list[str] = []  # die Zeilen, die unten stehen – Statuszeile und Eingabe
        self.tick = 0
        self.midline = False  # der Cursor steht mitten in einer Zeile
        self.block = ""  # was zuletzt stand: prompt · text · tool · info
        self.md: termmd.MarkdownStream | None = None  # die laufende Antwort
        self.think: termmd.MarkdownStream | None = None
        self.filter: termmd.CallFilter | None = None
        self.later: list[str] = []  # Zeilen, die warten, bis die laufende Antwort fertig ist
        self.steps = 0
        self.tokens = 0
        self.gen_seconds = 0.0

    # ------------------------------------------------------------------ Ausgabe

    def write(self, text: str) -> None:
        """Alles, was ins Fenster geht, läuft hier durch."""
        if not text:
            return
        if self.shown:
            self.clear_status()
        sys.stdout.write(text)
        sys.stdout.flush()
        self.midline = not text.endswith("\n")

    def out(self, text: str = "") -> None:
        """Eine ganze Zeile – beendet vorher eine laufende Antwort und räumt die Statuszeile weg."""
        self.end_text()
        self.clear_status()
        if self.midline:
            self.write("\n")
        self.write(text + "\n")

    def hint(self, text: str, indent: int = 2) -> None:
        """Ein grauer Hinweis, am Fensterrand zwischen Wörtern umbrochen."""
        pad = " " * indent
        for line in textwrap.wrap(text, max(30, T.columns() - indent - 2)) or [""]:
            self.out(self.st(pad + line, "dim"))

    def gap(self, kind: str) -> None:
        """Luft zwischen Blöcken verschiedener Art; Werkzeugschritte stehen dicht untereinander."""
        if self.block and (self.block != kind or kind == "text"):
            self.out("")
        self.block = kind

    def clear_status(self) -> None:
        """Den Fuß wegräumen – der Cursor steht danach wieder dort, wo die Ausgabe weitergeht."""
        if not self.shown:
            return
        hoch = f"\033[{len(self.shown) - 1}A" if len(self.shown) > 1 else ""
        sys.stdout.write(f"\r{hoch}\033[J")
        sys.stdout.flush()
        self.shown = []

    def set_status(self, text: str, mood: str = "think") -> None:
        self.status = (text, mood, time.monotonic())

    def stop_status(self) -> None:
        self.status = None
        self.clear_status()

    def status_row(self, avail: int) -> str:
        """Woran der Agent gerade ist – mit Gesicht und Uhr."""
        text, mood, since = self.status
        if self.buddy.enabled:
            face = self.st(self.buddy.face(mood, self.tick // 2), "buddy")
        else:
            spin = self.g["spinner"]
            face = self.st(spin[self.tick % len(spin)], "accent")
        seconds = int(time.monotonic() - since)
        clock = f"  {seconds} s" if seconds else ""
        stop = self.st("  · Esc stoppt", "dim") if self.poller and seconds >= 2 else ""
        room = avail - 3 - T.width(face) - T.width(clock) - T.width(stop)
        return f"  {face} {T.clip(text, max(8, room))}{self.st(clock, 'dim')}{stop}"

    def input_rows(self, avail: int) -> list[str]:
        """Die Eingabe, wie sie auch im Ruhezustand aussieht – mit dem, was du gerade tippst.

        Sie bleibt während der Arbeit stehen: Man sieht, wo der Text hingeht, und schiebt einen Wunsch nach,
        ohne den Agenten zu stoppen. Enter reiht ihn ein, Esc verwirft ihn.
        """
        typed = self.poller.buf if self.poller else ""
        mark = self.st(self.g["prompt"] + " ", "bold")
        cursor = self.st("▏", "dim")
        if not typed:
            hint = "Schreib mit – Enter reiht deine Nachricht für den nächsten Schritt ein"
            return [mark + cursor + self.st(" " + T.clip(hint, max(10, avail - 6)), "dim")]
        zeilen = typed.split("\n")
        # Bei vielen Zeilen bleiben die letzten stehen – dort tippt man gerade.
        gezeigt = zeilen[-DOCK_LINES:]
        rows = []
        letzte = len(gezeigt) - 1
        for i, zeile in enumerate(gezeigt):
            vorn = mark if i == 0 and len(gezeigt) == len(zeilen) else "  "
            room = max(10, avail - 4)
            # In der Zeile, in der getippt wird, zählt das Ende: Dort steht das zuletzt geschriebene Wort.
            if T.width(zeile) > room:
                zeile = "…" + zeile[-(room - 1):] if i == letzte else T.clip(zeile, room)
            rows.append(vorn + zeile + (cursor if i == letzte else ""))
        return rows

    def dock_rows(self) -> list[str]:
        """Der Fuß: Statuszeile, darunter die gerahmte Eingabe mit der Fußzeile."""
        avail = max(20, T.columns() - 1)
        rows = [self.status_row(avail)]
        # Ohne eigene Konsole wird nichts mitgetippt, und in einem flachen Fenster fräße der Rahmen die Ausgabe –
        # dann bleibt es bei der Statuszeile allein.
        if self.poller and T.rows() >= DOCK_MIN_ROWS:
            rule = self.st("─" * avail, "dim")
            rows += [rule] + self.input_rows(avail) + [rule, self.footer_line(avail)]
        return rows

    def draw_status(self) -> None:
        """Den Fuß unten halten: alte Zeilen überschreiben, Reste darunter wegräumen."""
        rows = self.dock_rows()
        if rows == self.shown:
            return  # nichts Neues – kein Flackern
        out = []
        if self.shown:
            out.append("\r" + (f"\033[{len(self.shown) - 1}A" if len(self.shown) > 1 else ""))
        out.append("\r\n".join(f"\033[2K{row}" for row in rows))
        out.append("\033[J")  # war der Fuß vorher höher, verschwindet der Rest
        sys.stdout.write("".join(out))
        sys.stdout.flush()
        self.shown = rows

    async def animate(self) -> None:
        """Statuszeile mit Companion-Gesicht und Uhr; liest nebenbei, was du während der Arbeit tippst."""
        while True:
            await asyncio.sleep(0.08)
            self.tick += 1
            try:
                if self.poller and self.turn and not self.asking:
                    self.on_keys(self.poller.poll())
                if self.st.enabled and self.status and not self.midline and not self.asking:
                    self.draw_status()
            except Exception:  # noqa: BLE001 – die Anzeige darf den Agenten nie aufhalten
                continue

    def on_keys(self, events: list[str]) -> None:
        for event in events:
            if event.startswith("submit:"):
                text = event[7:].strip()
                self.inbox.append({"id": uuid.uuid4().hex[:8], "text": text, "display": text})
                line = (f"  {self.st(self.g['queue'], 'accent')} {self.st('wartet:', 'dim')} "
                        f"{T.clip(text, T.columns() - 14)}")
                if self.md:  # mitten in einer Antwort: erst nach dem Textblock, sonst zerreißt es Absatz oder Tabelle
                    self.later.append(line)
                else:
                    self.out(line)
            elif event == "mode":
                mode = self.next_mode()
                asyncio.ensure_future(self.rt.update_config({"permission_mode": mode}))
                line = f"  {self.st('Modus:', 'dim')} {self.mode_label(mode)} {self.st('· ' + MODE_HINT[mode], 'dim')}"
                if self.md:
                    self.later.append(line)
                else:
                    self.out(line)
            elif event in ("esc", "interrupt") and self.turn and not self.turn.done():
                if event == "interrupt":
                    self.sigint_at = time.monotonic()
                self.turn.cancel()

    def scene(self, text: str, mood: str) -> list[str]:
        """Companion mit Sprechblase."""
        art = self.buddy.art(mood)
        wrap = max(16, min(52, T.columns() - WIDTH - 10))
        lines = [part for para in text.splitlines() or [""] for part in (textwrap.wrap(para, wrap) or [""])]
        inner = max(T.width(line) for line in lines)
        box = ["╭" + "─" * (inner + 2) + "╮", *[f"│ {line}{' ' * (inner - T.width(line))} │" for line in lines],
               "╰" + "─" * (inner + 2) + "╯"]
        top = max(0, self.buddy.face_row - 1)
        rows = []
        for i in range(max(len(art), top + len(box))):
            figure = art[i] if i < len(art) else " " * WIDTH
            bubble = box[i - top] if 0 <= i - top < len(box) else ""
            joint = " "
            if i == self.buddy.face_row and bubble.startswith("│"):
                joint, bubble = "─", "┤" + bubble[1:]
            if bubble.startswith(("│", "┤")):
                rows.append(f"{self.st(figure, 'buddy')}{self.st(joint, 'dim')}{self.st(bubble[:1], 'dim')}"
                            f"{bubble[1:-1]}{self.st(bubble[-1:], 'dim')}")
            else:
                rows.append(f"{self.st(figure, 'buddy')}{joint}{self.st(bubble, 'dim')}")
        return rows

    def say(self, event: str, mood: str = "happy", extra: str = "", **values) -> None:
        if not self.buddy.enabled:
            if extra:
                self.out(f"  {extra.strip()}")
            return
        text = self.buddy.line(event, **values)
        if text:
            self.out(f"  {self.st(self.buddy.face(mood), 'buddy')} {self.st(self.buddy.name + ':', 'dim')} {text}{extra}")

    # ------------------------------------------------------------------ Antworttext

    def feed_text(self, text: str) -> None:
        if not text:
            return
        if self.md is None:
            if not text.strip():
                return
            self.stop_status()
            self.end_think()
            self.gap("text")
            self.md = termmd.MarkdownStream(self.write, styles=self.st, glyphs=self.g)
        self.md.feed(text)

    def end_think(self) -> None:
        if self.think:
            self.think.end()
            self.think = None

    def end_text(self) -> None:
        """Die laufende Antwort abschließen – vor jedem anderen Block."""
        self.end_think()
        if self.md:
            md, self.md = self.md, None
            md.end()
            self.block = "text"
        waiting, self.later = self.later, []
        for line in waiting:
            self.out(line)

    # ------------------------------------------------------------------ Ereignisse des Agenten

    async def emit(self, ev: dict) -> None:
        ev = T.clean(ev)  # was vom Modell, aus Befehlen oder dem Netz kommt, steuert das Terminal nicht
        if ev.get("parent"):
            self.sub_event(ev)
            return
        handler = getattr(self, "on_" + ev["type"], None)
        if handler:
            handler(ev)
        if ev["type"] in ("tool_result", "stats"):
            sessions.autosave(self.session)  # Fenster zu oder Absturz mitten im Auftrag: der Verlauf bleibt

    def on_profile(self, ev: dict) -> None:
        self.gap("info")
        self.out(self.st(f"  @{ev['agent']} übernimmt", "dim"))

    def on_status(self, ev: dict) -> None:
        self.set_status(ev["text"], "work")

    def on_model(self, ev: dict) -> None:
        plan = ev["plan"]
        if plan.get("load_seconds") and id(plan) != self.shown_plan:
            self.shown_plan = id(plan)
            share = (plan.get("actual") or {}).get("gpu_share", plan.get("gpu_share", 0))
            self.gap("info")
            self.out(self.st(f"  {ev['model']} geladen · {plan['num_ctx'] // 1024}K Kontext · "
                             f"{round(share * 100)} % GPU · {plan['load_seconds']} s", "dim"))

    def on_assistant_start(self, ev: dict) -> None:
        self.end_text()
        self.filter = termmd.CallFilter()
        self.set_status("denkt nach …", "think")

    def on_thinking(self, ev: dict) -> None:
        if not self.rt.cfg.get("think"):
            return
        if self.think is None:
            self.stop_status()
            self.gap("think")
            self.think = termmd.MarkdownStream(self.write, styles=self.st, glyphs=self.g, plain=True,
                                               base=("dim", "italic"))
        self.think.feed(ev["text"])

    def on_text(self, ev: dict) -> None:
        self.feed_text(self.filter.feed(ev["text"]) if self.filter else ev["text"])

    def on_assistant_text(self, ev: dict) -> None:
        """Der Agent hat Werkzeugaufrufe im Text gefunden: nur zeigen, was ohne sie übrig bleibt."""
        if self.filter:
            self.feed_text(self.filter.finish(ev["text"]))
            self.filter = None

    def on_stats(self, ev: dict) -> None:
        if self.filter:
            self.feed_text(self.filter.finish(None))
            self.filter = None
        self.end_text()
        s = ev["stats"]
        self.tokens += int(s.get("tokens") or 0)
        if s.get("tokens") and s.get("tokens_per_s"):
            self.gen_seconds += s["tokens"] / max(0.1, s["tokens_per_s"])

    def on_assistant_discard(self, ev: dict) -> None:
        if self.filter:
            self.filter = None
        self.end_text()

    def on_tool_call(self, ev: dict) -> None:
        if ev["name"] in ("todo_write", "ask_user"):  # die Rückfrage zeigt question() samt Antwort
            return
        self.end_text()
        self.stop_status()
        self.steps += 1
        self.commands[ev["id"]] = str(ev["args"].get("command") or "")
        label = f"@{ev['args'].get('agent', '?')}" if ev["name"] == "agent" else VERB.get(ev["name"], ev["name"])
        summary = ev["args"].get("task", "") if ev["name"] == "agent" else ev["summary"]
        self.gap("tool")
        room = T.columns() - T.width(label) - 5
        self.out(f"{self.st(self.g['bullet'], 'accent')} {self.st(label, 'bold')} {self.st(T.clip(summary, room), 'dim')}")
        self.labels[ev["id"]] = label
        self.set_status(f"{label} …", "work")

    def on_tool_running(self, ev: dict) -> None:
        """Nach einer Freigabe läuft der Schritt – die Statuszeile zeigt es wieder, samt Uhr."""
        self.set_status(f"{self.labels.get(ev['id'], 'Arbeitet')} …", "work")

    def on_tool_result(self, ev: dict) -> None:
        if ev["name"] == "todo_write":
            return
        if ev["name"] == "ask_user":
            d = ev["display"] or {}
            if not d.get("items") or d.get("limit"):  # nicht gefragt: Autonom, Schleife oder genug gefragt
                self.gap("info")
                self.out(self.st("  Rückfrage übersprungen – Coder entscheidet selbst.", "dim"))
            self.set_status("denkt weiter …", "think")
            return
        self.stop_status()
        info, extra = self.result_info(ev)
        self.out(f"  {self.st(self.g['result'], 'ok' if ev['ok'] else 'error')} {info}")
        for line in extra:
            self.out(f"    {line}")
        self.block = "tool"
        self.react(ev)
        self.set_status("denkt weiter …", "think")

    def on_todos(self, ev: dict) -> None:
        marks = {"pending": self.st(self.g["todo"], "dim"), "in_progress": self.st(self.g["doing"], "warn"),
                 "completed": self.st(self.g["done"], "ok")}
        for todo in ev["todos"]:
            text = T.clip(todo["content"], T.columns() - 8)
            self.out(f"    {marks[todo['status']]} {self.st(text, 'dim') if todo['status'] == 'completed' else text}")
        self.block = "tool"

    def on_controller(self, ev: dict) -> None:
        if ev["state"] == "start":
            self.gap("tool")
            self.out(f"{self.st(self.g['control'], 'magenta')} {self.st('Kontrolle', 'bold')} "
                     f"{self.st(ev['model'] + ' · ' + REASON_LABEL.get(ev['reason'], ''), 'dim')}")
            self.set_status(f"Kontrolle · {ev['model']} prüft …", "work")
            return
        self.stop_status()
        verdict, note = ev["verdict"], ev.get("note") or ""
        if verdict == "done":
            self.out(f"  {self.st(self.g['ok'], 'ok')} {note or 'Passt.'}")
            self.say("verdict_done", "happy")
        elif verdict == "continue":
            self.out(f"  {self.st(self.g['redo'], 'warn')} {note}")
            self.say("verdict_continue", "alert")
        else:
            self.out(self.st(f"  – {note or 'Kein klares Urteil.'}", "dim"))
        self.block = "tool"

    def on_recall(self, ev: dict) -> None:
        titles = [self.st(t, "bold") for t in ev["notes"]]
        self.gap("info")
        self.out(f"  {self.st(self.g['recall'], 'accent')} {self.st('Aus dem Gedächtnis:', 'dim')} "
                 + self.st(", ", "dim").join(titles))
        if random.random() < 0.3:
            self.say("recall", "think")

    def on_files(self, ev: dict) -> None:
        """Chat: genannte Dateien liest Coder gleich mit."""
        self.gap("info")
        self.out(f"  {self.st(self.g['recall'], 'accent')} {self.st('Mitgelesen:', 'dim')} "
                 + self.st(", ", "dim").join(self.st(f, "code") for f in ev["files"]))

    def on_vision(self, ev: dict) -> None:
        self.gap("info")
        self.out(self.st(f"  Bild beschrieben von {ev.get('model', '?')}", "dim"))

    def on_watchdog(self, ev: dict) -> None:
        self.gap("info")
        self.out(self.st(f"  {self.g['watchdog']} {ev['text']}", "warn"))
        self.say("watchdog", "alert")

    def on_compacted(self, ev: dict) -> None:
        self.gap("info")
        self.out(self.st("  Verlauf verdichtet.", "dim"))
        self.say("compact", "happy")

    def on_changes(self, ev: dict) -> None:
        files = ev["files"]
        names = ", ".join(f["path"] for f in files[:4]) + (f" und {len(files) - 4} weitere" if len(files) > 4 else "")
        added = sum(f.get("added") or 0 for f in files)
        removed = sum(f.get("removed") or 0 for f in files)
        self.gap("info")
        self.out(self.st(f"  {len(files)} {'Datei' if len(files) == 1 else 'Dateien'} geändert: {names} ", "dim")
                 + self.st(f"+{added}", "ok") + " " + self.st(f"−{removed}", "error")
                 + self.st(" · /undo nimmt das zurück", "dim"))

    def on_context(self, ev: dict) -> None:
        self.context = ev

    def on_queued_taken(self, ev: dict) -> None:
        """Eine Nachricht, die während der Arbeit kam – jetzt liest der Agent sie."""
        self.gap("prompt")
        self.out(f"{self.st(self.g['prompt'], 'accent', 'bold')} {ev.get('text', '')}")

    def on_plan_ready(self, ev: dict) -> None:
        self.plan_offer = True

    def on_apply_ready(self, ev: dict) -> None:
        """Chat mit Code zu gelesenen Dateien: daran erinnern, dass nichts geändert ist – und wie es geht."""
        how = "Umschalt+Tab bis „Normal“ (oder /mode normal)" if self.editor else "/mode normal"
        self.end_text()
        self.gap("info")
        self.hint(f"Im Chat ändert Coder nichts. Umsetzen: {how}, dann z. B. „setz das um“.")

    def on_memory_changed(self, ev: dict) -> None:
        self.cache["stamp"] = 0.0  # neue Notiz: beim nächsten Tab frisch laden

    def on_notice(self, ev: dict) -> None:
        self.gap("info")
        # Am Fensterrand umbrechen statt mitten im Wort abreißen – Hinweise sind oft lange Sätze.
        text = str(ev.get("text") or ev.get("message") or "")
        for line in textwrap.wrap(text, max(30, T.columns() - 4)) or [""]:
            self.out(self.st("  " + line, "warn"))

    on_error = on_notice

    def sub_event(self, ev: dict) -> None:
        t, who = ev["type"], ev.get("agent", "")
        label = "Kontrolle" if who == "kontrolle" else f"@{who}"
        if t == "tool_call" and ev["name"] != "todo_write":
            verb = VERB.get(ev["name"], ev["name"])
            self.out(self.st(f"    {self.g['sub']} {label} · {verb} {T.clip(ev['summary'], T.columns() - 30)}", "dim"))
            self.set_status(f"{label} · {verb} …", "work")
        elif t == "tool_result" and not ev["ok"] and not (ev["display"] or {}).get("denied"):
            info, _ = self.result_info(ev)
            self.out(f"      {self.st(self.g['result'], 'error')} {self.st(T.strip(info), 'dim')}")
        elif t == "status":
            self.set_status(f"{label} · {ev['text']}", "work")
        elif t == "assistant_start":
            self.set_status(f"{label} denkt nach …", "think")

    def result_info(self, ev: dict) -> tuple[str, list[str]]:
        """Kurzfassung eines Werkzeugergebnisses plus ein paar Zeilen Vorschau."""
        name, d, output = ev["name"], ev["display"] or {}, ev.get("output") or ""
        st, room = self.st, T.columns() - 8
        if d.get("denied"):
            return st("abgelehnt", "error"), []
        if name == "memory_write":
            where = VAULT_LABEL.get(d.get("vault"), d.get("vault") or "")
            state = "neu" if d.get("created") else "aktualisiert"
            return (f"{st(state, 'bold')} {st('· ' + where, 'dim')} "
                    f"{st('+' + str(d.get('added', 0)), 'ok')} {st('−' + str(d.get('removed', 0)), 'error')}"), []
        if name == "memory_read" and "lines" in d:
            return f"{d['lines']} Zeilen {st('· ' + VAULT_LABEL.get(d.get('vault'), ''), 'dim')}", []
        if d.get("diff"):
            return (f"{st('+' + str(d.get('added', 0)), 'ok')} {st('−' + str(d.get('removed', 0)), 'error')}",
                    diff_rows(d["diff"], st, 10, room))
        if name == "run_command":
            lines = [line for line in output.strip().splitlines() if not line.startswith(("[Exit-Code", "[Timeout"))]
            if d.get("background"):
                return f"läuft im Hintergrund · PID {d.get('pid')}", [st(T.clip(line, room), "dim") for line in lines[-3:]]
            if d.get("timed_out"):
                return st("Zeitüberschreitung", "error"), [st(T.clip(line, room), "dim") for line in lines[-6:]]
            if d.get("exit_code") == 0:
                return st("Exit 0", "ok") + (st(" · " + T.clip(lines[-1], room - 10), "dim") if lines else ""), []
            return st(f"Exit {d.get('exit_code')}", "error"), [st(T.clip(line, room), "dim") for line in lines[-8:]]
        if name == "web_research":
            return f"{d.get('count', 0)} Quellen", [st(f"[{s['n']}] {T.clip(s['title'], 60)} · {T.clip(s['url'], 60)}", "dim")
                                                    for s in d.get("sources", [])[:6]]
        if name == "view_image":
            return f"gesehen mit {d.get('model', '?')}", [st(T.clip(line, room), "dim")
                                                           for line in output.splitlines()[1:4] if line.strip()]
        if name == "agent":
            # Womit der Sub-Agent gearbeitet hat, steht dabei – aber nur, wenn es ein anderes Modell war.
            teile = [f"{len(d.get('steps') or [])} Schritte", f"{d.get('seconds', 0):g} s"]
            eigen = str(d.get("model") or "")
            if eigen and eigen != (self.rt.cfg.get("model") or eigen):
                teile.append(eigen)
            return st(" · ".join(teile), "dim"), []
        if name == "generate_image":
            if not d.get("path"):
                return st("nicht erzeugt", "error"), [st(T.clip(output.strip(), room), "dim")]
            return (f"{d['width']}×{d['height']} · {d.get('seconds', 0)} s",
                    [st(f"{d['path']} · Seed {d.get('seed')} · {T.clip(str(d.get('model') or '?'), 60)}", "dim")])
        if "lines" in d:
            return f"{d['lines']} Zeilen", []
        if name == "list_dir" and "count" in d:
            return f"{d['count']} Einträge", []
        if "count" in d:
            return f"{d['count']} Treffer", []
        if "chars" in d:
            return f"{number(d['chars'])} Zeichen", []
        first = (output.strip().splitlines() or [""])[0]
        return st(T.clip(first, room), "dim"), []

    def react(self, ev: dict) -> None:
        d = ev["display"] or {}
        if d.get("denied"):
            self.say("denied", "sad")
        elif ev["name"] == "run_command" and not d.get("background"):
            command = self.commands.get(ev["id"], "")
            if ev["ok"] and MARKS_RX.search(command):
                self.say("tests_ok", "proud")
            elif not ev["ok"] and random.random() < 0.4:
                self.say("run_fail", "sad", code=d.get("exit_code"))

    # ------------------------------------------------------------------ Fragen

    async def choose(self, prompt: str, options: dict[str, str], default: str) -> str:
        """Eine Antwort mit einer Taste – ohne eigene Konsole eine Zeile mit input()."""
        if self.editor:
            def pick():
                with self.console.raw():
                    return self.editor.choice(prompt, options, default)
            answer = await asyncio.to_thread(pick)
            if self.poller and self.editor.spill:  # mitten im Tippen gefragt: der Text gehört zur Nachricht
                self.poller.buf += self.editor.spill
            self.editor.spill = ""
            return answer
        while True:
            try:
                answer = (await asyncio.to_thread(input, prompt)).strip().lower()
            except EOFError:
                return options.get("esc", options.get("n", default))
            if not answer:
                return default
            if answer[:1] in options:
                return options[answer[:1]]
            keys = "/".join(k for k in options if len(k) == 1)
            self.out(self.st(f"    Bitte {keys} – oder Enter.", "dim"))

    async def menu(self, options: list[tuple[str, str]], *, keys: dict | None = None, other: str | None = None,
                   multiple: bool = False, hint: str = "") -> tuple[str, object]:
        """Eine Auswahl wie in Claude Code. Mit eigener Konsole eine Liste mit Pfeiltasten, sonst nummerierte Zeilen
        und eine Antwort per input(). Rückgabe wie LineEditor.select: choices · text · skip."""
        if self.editor:
            def pick():
                with self.console.raw():
                    return self.editor.select(options, multiple=multiple, glyphs=self.g, other=other, keys=keys,
                                              hint=hint)

            result = await asyncio.to_thread(pick)
            self.midline = False  # die Liste ist weggeräumt, der Cursor steht am Anfang ihrer ersten Zeile
            if self.poller and self.editor.spill:  # mitten im Tippen gefragt: der Text gehört zur nächsten Nachricht
                self.poller.buf += self.editor.spill
            self.editor.spill = ""
            return result
        for i, (label, desc) in enumerate(options, 1):
            self.out(f"    {self.st(str(i) + '.', 'accent')} {label}" + (self.st("  " + desc, "dim") if desc else ""))
        keys = {k.lower(): v for k, v in (keys or {}).items()}
        letters = "/".join(keys)
        parts = [("Nummern, z. B. 1,3" if multiple else "Nummer") if options else "",
                 letters, "eigene Antwort tippen" if other else "", "Enter nimmt 1" if options else "",
                 "- überspringt" if other else "- lehnt ab"]
        self.hint(" · ".join(p for p in parts if p), indent=4)
        while True:
            try:
                raw = (await asyncio.to_thread(input, "    › ")).strip()
            except EOFError:
                return "skip", None
            if raw == "-" or (not raw and not options):
                return "skip", None
            if not raw:
                return "choices", [0]
            if raw.lower() in keys:
                return "choices", [keys[raw.lower()]]
            if options and re.fullmatch(r"\d{1,2}(?:\s*[,; ]\s*\d{1,2})*", raw):
                picked = list(dict.fromkeys(int(n) - 1 for n in re.findall(r"\d+", raw)))
                if all(0 <= n < len(options) for n in picked):
                    return "choices", picked if multiple else picked[:1]
            if other:
                return "text", raw
            self.out(self.st(f"    Bitte 1–{len(options)}{' oder ' + letters if letters else ''} – oder Enter.", "dim"))

    async def ask(self, req: dict) -> str:
        """Freigabe wie in Claude Code: „› 1. Ja“ · „2. Ja, und nicht mehr fragen“ · „3. Nein“ – j/i/n gehen auch."""
        req = T.clean(req)  # sonst sähe ein Befehl mit Steuerzeichen in der Freigabe anders aus, als er ist
        self.asking = True
        try:
            self.end_text()
            self.stop_status()
            who = "Kontrolle · " if req.get("agent") == "kontrolle" else (f"@{req['agent']} · " if req.get("agent") else "")
            face = f" {self.st(self.buddy.face('alert'), 'buddy')}" if self.buddy.enabled else ""
            # Die Frage hängt direkt unter dem Schritt, um den es geht – eingerückt, ohne Leerzeile dazwischen.
            if self.block != "tool":
                self.gap("info")
            title = who + APPROVAL.get(req["name"], req["name"] + " ausführen?")
            self.out(f"  {self.st('?', 'warn', 'bold')} {self.st(title, 'bold')}{face}")
            self.out(f"    {self.st(T.clip(req['summary'], T.columns() - 6), 'code')}")
            diff = (req.get("preview") or {}).get("diff", "")
            for line in diff_rows(diff, self.st, 30, T.columns() - 8):
                self.out("    " + line)
            always = req.get("always")
            options, keys = [("Ja", "")], {"j": 0, "y": 0}
            if always:
                label = (f"Ja, und Befehle mit „{always}“ in diesem Chat nicht mehr fragen"
                         if req["name"] == "run_command" else "Ja, und das in diesem Chat nicht mehr fragen")
                options.append((label, ""))
                keys.update({"i": 1, "a": 1})
            options.append(("Nein – Coder hält an, du sagst, was anders werden soll", ""))
            keys["n"] = len(options) - 1
            kind, value = await self.menu(options, keys=keys, hint="j/i/n" if always else "j/n")
            if kind != "choices" or value[0] == len(options) - 1:
                answer = "deny"
            else:
                answer = "always" if always and value[0] == 1 else "allow"
            mark, style, said = {"allow": (self.g["ok"], "ok", "Ja"), "always": (self.g["ok"], "ok", "Ja, immer"),
                                 "deny": (self.g["fail"], "error", "Nein")}[answer]
            self.out(f"    {self.st(mark, style)} {said}")
            self.block = "tool"
            return answer
        finally:
            self.asking = False

    async def question(self, req: dict) -> dict:
        """Eine Rückfrage des Agenten: Antwort aus der Liste, eigene Antwort – oder Esc, dann entscheidet er selbst."""
        req = T.clean(req)
        self.asking = True
        try:
            self.end_text()
            self.stop_status()
            self.gap("info")
            who = f"@{req['agent']} · " if req.get("agent") else ""
            of = f"Frage {req['index']} von {req['count']} · " if int(req.get("count") or 1) > 1 else ""
            face = f" {self.st(self.buddy.face('ask'), 'buddy')}" if self.buddy.enabled else ""
            wrapped = textwrap.wrap(req["question"], max(30, T.columns() - 6 - T.width(who + of))) or [""]
            self.out(f"  {self.st('?', 'accent', 'bold')} {self.st(who + of, 'dim')}{self.st(wrapped[0], 'bold')}{face}")
            for line in wrapped[1:]:
                self.out("    " + self.st(line, "bold"))
            answer = await self.pick_answer(req.get("options") or [], bool(req.get("multiple")))
            if answer.get("skipped"):
                self.out(self.st(f"    {self.g['arrow']} übersprungen – Coder entscheidet selbst", "dim"))
            else:
                said = ", ".join(answer["choices"])
                if answer["text"]:
                    said += (" · " if said else "") + f"„{answer['text']}“"
                self.out(f"    {self.st(self.g['arrow'], 'ok')} {T.clip(said, T.columns() - 8)}")
            self.block = "info"  # der nächste Schritt bekommt wieder Luft
            self.set_status("denkt weiter …", "think")
            return answer
        finally:
            self.asking = False

    @staticmethod
    def option_hint(option: dict) -> str:
        return " · ".join(x for x in ("empfohlen" if option.get("recommended") else "",
                                        option.get("description") or "") if x)

    async def pick_answer(self, options: list, multiple: bool) -> dict:
        """Antwort aus der Liste, eine eigene (lostippen) – oder Esc: überspringen."""
        items = [(o["label"], self.option_hint(o)) for o in options]
        kind, value = await self.menu(items, other="Eigene Antwort", multiple=multiple)
        if kind == "cancel" and self.turn and not self.turn.done():
            self.turn.cancel()  # Strg+C hält den Agent an – wie überall sonst; Esc überspringt nur die Frage
        if kind == "choices":
            return {"choices": [options[i]["label"] for i in value], "text": "", "skipped": False}
        if kind == "text":
            text = await self.read_answer(str(value or "")) if self.editor else str(value or "").strip()
            return {"choices": [], "text": text, "skipped": not text}
        return {"choices": [], "text": "", "skipped": True}

    async def read_answer(self, initial: str) -> str:
        """Eine eigene Antwort in einer Zeile – landet nicht im Verlauf der Eingabe."""
        prompt = f"    {self.st('Antwort', 'bold')} {self.st(self.g['prompt'], 'accent')} "
        history, self.editor.history = self.editor.history, lineedit.History(None)
        cycle, self.editor.on_shift_tab = self.editor.on_shift_tab, None  # hier wechselt Umschalt+Tab keinen Modus

        def read():
            with self.console.raw():
                return self.editor.read(prompt, initial, None)

        try:
            return (await asyncio.to_thread(read)).strip()
        except (KeyboardInterrupt, EOFError):
            return ""
        finally:
            self.editor.history, self.editor.on_shift_tab = history, cycle

    # ------------------------------------------------------------------ Modus

    def mode_label(self, mode: str) -> str:
        return self.st(MODE_LABEL[mode], MODE_STYLE.get(mode, "bold"), "bold")

    def next_mode(self) -> str:
        mode = self.rt.cfg["permission_mode"]
        return MODE_CYCLE[(MODE_CYCLE.index(mode) + 1) % len(MODE_CYCLE)] if mode in MODE_CYCLE else "ask"

    def shift_tab(self) -> str | None:
        """Umschalt+Tab in der Eingabezeile – läuft im Thread der Eingabe, die Einstellung sichert die Event-Loop."""
        if self.aloop is None:
            return None
        mode = self.next_mode()
        try:
            asyncio.run_coroutine_threadsafe(self.rt.update_config({"permission_mode": mode}), self.aloop).result(5)
        except Exception:  # noqa: BLE001 – dann bleibt eben der alte Modus
            return None
        return self.prompt_line()  # die Fußzeile zeigt den neuen Modus beim nächsten Zeichnen

    async def offer_plan(self) -> None:
        """Nach einem Plan – wie in Claude Code: umsetzen mit Auto-Edit, einzeln freigeben oder weiter planen."""
        self.plan_offer = False
        self.out("")
        self.block = "info"
        self.out(f"  {self.st('?', 'accent', 'bold')} {self.st('Plan umsetzen?', 'bold')}")
        kind, value = await self.menu([
            ("Ja, mit Auto-Edit", "Dateien ändern ohne Rückfrage, Befehle mit Freigabe"),
            ("Ja, jede Änderung einzeln freigeben", "Modus Normal"),
            ("Nein, weiter planen", "schreib, was am Plan anders werden soll"),
        ], keys={"a": 0, "j": 1, "n": 2})
        mode = {0: "auto-edit", 1: "ask"}.get(value[0] if kind == "choices" else 2)
        if not mode:
            self.out(f"    {self.st(self.g['arrow'], 'dim')} {self.st('weiter planen', 'dim')}")
            return
        await self.rt.update_config({"permission_mode": mode})
        self.out(f"    {self.st(self.g['ok'], 'ok')} {self.mode_label(mode)} {self.st('· ' + MODE_HINT[mode], 'dim')}")
        self.block = "prompt"
        await self.send(PLAN_GO, display="Plan umsetzen")

    # ------------------------------------------------------------------ Ablauf

    async def main(self) -> int:
        T.enable_vt()
        self.aloop = asyncio.get_running_loop()
        status = await self.rt.status()
        if not status["ok"]:
            print(self.st(status["error"], "error"))
            return 1
        await self.banner(status)
        animator = asyncio.create_task(self.animate())
        loop = asyncio.get_running_loop()

        def on_sigint(_signum, _frame):
            self.sigint_at = time.monotonic()
            if self.turn and not self.turn.done():
                loop.call_soon_threadsafe(self.turn.cancel)  # Strg+C bricht nur die laufende Aufgabe ab

        previous = signal.signal(signal.SIGINT, on_sigint)
        power.keep_awake.hold(self.rt.cfg.get("keep_awake") == "open")  # „solange Coder offen ist“
        try:
            await self.repl()
        finally:
            power.keep_awake.hold(False)
            signal.signal(signal.SIGINT, previous if callable(previous) else signal.default_int_handler)
            animator.cancel()
            self.stop_status()
            self.say("bye", "happy")
            if self.readline:
                lineedit.readline_save(HISTORY)
            await self.rt.close()
        return 0

    async def banner(self, status: dict) -> None:
        """Begrüßung wie in Claude Code: ein Kasten mit Ordner, Modell und den wichtigsten Tasten."""
        cfg = self.rt.cfg
        hw = optimizer.detect_hardware()
        gpu = f"{hw['gpus'][0]['name']} · {hw['vram_total'] / 1024 ** 3:.0f} GB" if hw["gpus"] else "CPU"
        print()
        if self.buddy.enabled:
            for line in self.scene(self.buddy.line("hello"), "happy"):
                print(line)
            print(self.st(f"  {self.buddy.name} · {self.buddy.species}", "dim"))
            print()
        server = f"vLLM {status['version']}" if status.get("backend") == "vllm" else f"Ollama {status['version']}"
        details = [cfg.get("model") or "Modell automatisch", gpu, server]
        if cfg.get("controller", True):
            details.append(f"Kontrolle {await self.rt.controller_model(cfg.get('model') or '') or 'Hauptmodell'}")
        keys = " · Tab ergänzt" if self.editor or self.readline else ""
        modes = " · Umschalt+Tab Modus" if self.editor else ""
        inner = max(30, min(T.columns() - 6, 96))
        body = [(self.st(f"{self.g['star']} ", "accent") + self.st("Coder", "bold") + " " + self.st(__version__, "dim"), ""),
                ("", "")]
        body += [(self.st(line, "dim"), "") for line in textwrap.wrap(f"Ordner: {self.session['workspace']}", inner)]
        body += [(self.st(line, "dim"), "") for line in textwrap.wrap(" · ".join(details), inner)]
        body.append((f"Modus {self.mode_label(cfg['permission_mode'])}"
                     + self.st(f" · Aufwand {effort_mod.LABEL[effort_mod.level(cfg)]}", "dim"), ""))
        body.append(("", ""))
        body += [(self.st(line, "dim"), "") for line in textwrap.wrap(
            f"/help Befehle · ? Tastenkürzel · @agent Spezialist · [[Notiz]] Gedächtnis{keys}{modes} · "
            "Bild ins Fenster ziehen", inner)]
        width = min(inner, max(T.width(text) for text, _ in body))
        g, bar = self.g, self.st(self.g["bar"], "dim")
        print(self.st(g["top"][0] + g["rule"] * (width + 2) + g["corner-tr"], "dim"))
        for text, _ in body:
            print(f"{bar} {text}{' ' * (width - T.width(text))} {bar}")
        print(self.st(g["bottom"][0] + g["rule"] * (width + 2) + g["corner-br"], "dim"))
        self.block = "info"

    def prompt(self) -> str:
        """Der Prompt für input() – mit Leerzeile davor."""
        return "\n" + self.prompt_line()

    def prompt_line(self) -> str:
        """Ohne eigene Konsole steht vor dem Prompt, was sonst die Fußzeile zeigt."""
        if self.editor:
            return self.st(self.g["prompt"] + " ", "bold")
        parts = []
        mode = self.rt.cfg["permission_mode"]
        if mode != "ask":
            parts.append(self.st(MODE_LABEL[mode], MODE_STYLE.get(mode, "warn")))
        level = effort_mod.level(self.rt.cfg)
        if level != "medium":
            parts.append(self.st(f"Aufwand {effort_mod.LABEL[level].lower()}", "dim"))
        if self.images:
            parts.append(self.st(f"{len(self.images)} {'Bild' if len(self.images) == 1 else 'Bilder'}", "code"))
        if self.loop and self.loop.running:
            parts.append(self.st("Schleife", "magenta"))
        return "".join(f"{p} " for p in parts) + self.st(self.g["prompt"] + " ", "bold")

    def footer_line(self, avail: int) -> str:
        """Die Zeile unter der Eingabe – wie in Claude Code: links der Modus, rechts Aufwand, Bilder, Kontext."""
        cfg, g = self.rt.cfg, self.g
        mode = cfg["permission_mode"]
        cycle = " (Umschalt+Tab wechselt)"
        left = {
            "ask": ("", "? Tastenkürzel · / Befehle · @ Agents · Umschalt+Tab Modus"),
            "auto-edit": (f"{g['mode-auto']} Auto-Edit an", cycle),
            "plan": (f"{g['mode-plan']} Planen an", cycle),
            "chat": (f"{g['mode-chat']} Chat – ändert nichts", cycle),
            "yolo": (f"{g['mode-yolo']} Autonom – alles ohne Rückfrage", cycle),
        }[mode]
        right = []
        level = effort_mod.level(cfg)
        if level != "medium":
            right.append(f"Aufwand {effort_mod.LABEL[level].lower()}")
        if self.images:
            right.append(f"{len(self.images)} {'Bild' if len(self.images) == 1 else 'Bilder'}")
        if self.loop and self.loop.running:
            right.append("Schleife")
        used, most = self.context.get("used") or 0, self.context.get("max") or 0
        if most and used / most >= 0.5:
            right.append(f"Kontext {round(used / most * 100)} %")
        right_text = " · ".join(right)
        room = avail - 2 - (T.width(right_text) + 2 if right_text else 0)
        head, tail = left
        head = T.clip(head, max(8, room))
        # clip nimmt führende Leerzeichen weg – der Abstand kommt danach wieder davor
        tail = T.clip(tail, max(0, room - T.width(head) - 1)) if room - T.width(head) > 7 else ""
        if head and tail:
            tail = " " + tail
        shown = T.width(head) + T.width(tail)
        text = "  " + (self.st(head, MODE_STYLE.get(mode, "bold")) if head else "") + self.st(tail, "dim")
        if right_text:
            text += " " * max(2, avail - 2 - shown - T.width(right_text)) + self.st(right_text, "dim")
        return text

    async def repl(self) -> None:
        last_interrupt = 0.0
        while True:
            try:
                initial, self.prefill = self.prefill, ""
                text = await self.read_line(initial)
            except KeyboardInterrupt:  # Strg+C auf leerer Zeile (eigene Eingabe)
                if time.monotonic() - last_interrupt < 2.5:
                    return
                last_interrupt = time.monotonic()
                self.out(self.st("  Noch einmal Strg+C zum Beenden – oder /exit.", "dim"))
                continue
            except EOFError:
                if time.monotonic() - self.sigint_at < 1.5:  # Strg+C bei input() (Windows meldet es als EOF)
                    if time.monotonic() - last_interrupt < 2.5:
                        return
                    last_interrupt = time.monotonic()
                    self.out(self.st("  Noch einmal Strg+C zum Beenden – oder /exit.", "dim"))
                    continue
                return
            text = text.strip()
            if not text:
                continue
            self.block = "prompt"
            if text == "?":  # wie in Claude Code: ? zeigt die Tastenkürzel
                await self.cmd_help("")
                continue
            if text.startswith("/") and not IMAGE_RX.fullmatch(text):
                if await self.command(text) is False:
                    return
                continue
            await self.send(text)

    async def read_line(self, initial: str = "") -> str:
        """Eine Eingabe. Mit eigener Konsole: Editor mit Vervollständigung. Sonst input() – mehrzeilig, wenn eine
        Zeile auf \\ endet oder ein Codeblock offen ist."""
        self.stop_status()
        if self.editor or self.readline:
            await self.refresh_cache()
        if self.editor:
            self.out("")
            prompt = self.prompt_line()

            def read():
                with self.console.raw():
                    return self.editor.read(prompt, initial, self.complete, footer=self.footer_line)

            self.midline = False
            return await asyncio.to_thread(read)
        text = await asyncio.to_thread(input, self.prompt())
        while text.rstrip().endswith("\\") or text.count("```") % 2:
            more = await asyncio.to_thread(input, self.st("  … ", "dim"))
            text = (text.rstrip()[:-1].rstrip() + "\n" + more) if text.rstrip().endswith("\\") else text + "\n" + more
        return text

    # ------------------------------------------------------------------ Vervollständigen

    async def refresh_cache(self, force: bool = False) -> None:
        """Befehle, Agents, Notizen und Modelle für Tab – höchstens alle 20 Sekunden neu."""
        if not force and time.monotonic() - self.cache["stamp"] < 20:
            return
        ws = self.session["workspace"]
        claude = bool(self.rt.cfg.get("claude_extensions", True))
        try:
            found = commands_mod.for_tab(await asyncio.to_thread(commands_mod.load, ws, claude), "code")
            own = [(f"/{c}", text) for _group, items in HELP for cmd, text in items for c in [cmd.split()[0][1:]]]
            self.cache["commands"] = sorted({name: text for name, text in own + [
                (f"/{c['name']}", c["description"]) for c in found]}.items())
            agents = await asyncio.to_thread(agents_mod.load, ws, claude)
            self.cache["agents"] = [(f"@{a.name}", a.description) for a in agents.values()]
            notes = await asyncio.to_thread(memory_mod.load, ws)
            self.cache["notes"] = [(n.title, VAULT_LABEL.get(n.vault, n.vault)) for n in notes]
        except Exception:  # noqa: BLE001 – nur Komfort: ohne Liste geht Tab eben nicht
            pass
        try:
            self.cache["models"] = [(m, "") for m in await self.rt.installed()]
        except Exception:  # noqa: BLE001
            pass
        self.cache["stamp"] = time.monotonic()

    def complete(self, text: str, pos: int):
        """Was an der Cursorstelle passt: (Anfang des Worts, [(Wert, Beschreibung)], beim Tippen zeigen?)."""
        before = text[:pos]
        note = before.rfind("[[")
        if note >= 0 and "]]" not in before[note:] and "\n" not in before[note:]:
            query = before[note + 2:].lower()
            items = [(t + "]]", v) for t, v in self.cache["notes"] if t.lower().startswith(query)]
            items += [(t + "]]", v) for t, v in self.cache["notes"]
                      if query and query in t.lower() and not t.lower().startswith(query)]
            return note + 2, items[:40], True
        if "\n" in before:
            return None
        if before.startswith("/") and " " not in before:
            q = before.lower()
            return 0, [(n, d) for n, d in self.cache["commands"] if n.startswith(q)], True
        if before.startswith("@") and " " not in before:
            q = before.lower()
            return 0, [(n, d) for n, d in self.cache["agents"] if n.lower().startswith(q)], True
        head, space, arg = before.partition(" ")
        if not space or " " in arg and head.lower() not in ("/memory", "/gedächtnis"):
            return None
        cmd = ALIASES.get(head[1:].lower(), head[1:].lower()) if head.startswith("/") else ""
        start = len(head) + 1
        fixed = {"mode": [({"ask": "normal", "plan": "planen", "yolo": "autonom"}.get(m, m), MODE_HINT[m])
                          for m in PERMISSION_MODES],
                 "effort": [(effort_mod.LABEL[e].lower(), effort_mod.HINT[e]) for e in effort_mod.LEVELS],
                 "theme": [(t, T.THEME_HINT.get(t, "nach dem Terminal")) for t in CLI_THEMES],
                 "buddy": [("streicheln", ""), ("name ", "neuer Name"), ("aus", ""), ("an", "")],
                 "controller": [("an", ""), ("aus", ""), ("auto", "Mistral, falls installiert")],
                 "loop": [("stop", "laufende Schleife beenden"), ("3x ", "dreimal"), ("5m ", "alle 5 Minuten")],
                 "think": [("an", ""), ("aus", "")],
                 "instructions": [("code ", "nur im Terminal und im Tab Code"), ("chat ", "nur im Tab Chat"),
                                  ("+ ", "eine Zeile anhängen"), ("leeren", "Anweisungen löschen")],
                 "style": [(personal_mod.LABEL[s].lower(), personal_mod.HINT[s]) for s in personal_mod.STYLES]}
        if cmd in fixed:
            items = fixed[cmd] + (self.cache["models"] if cmd == "controller" else [])
            return start, [(v, d) for v, d in items if v.lower().startswith(arg.lower())], True
        if cmd == "model":
            return start, [(v, d) for v, d in self.cache["models"] if v.lower().startswith(arg.lower())], True
        if cmd == "memory":
            q = arg.lower()
            return start, [(t, v) for t, v in self.cache["notes"] if q and t.lower().startswith(q)], True
        if cmd in ("image", "open", "print", "workspace"):
            return self.complete_path(arg, start, dirs_only=cmd == "workspace")
        return None

    def complete_path(self, arg: str, start: int, dirs_only: bool = False):
        raw = arg.strip("\"'")
        base = Path(self.session["workspace"])
        folder, _, stem = raw.replace("\\", "/").rpartition("/")
        where = Path(folder) if folder and Path(folder).is_absolute() else base / folder
        try:
            entries = sorted(where.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))[:400]
        except OSError:
            return None
        prefix = (folder + "/") if folder else ""
        items = []
        for entry in entries:
            if entry.name.startswith(".") and not stem.startswith("."):
                continue
            if not entry.name.lower().startswith(stem.lower()):
                continue
            is_dir = entry.is_dir()
            if dirs_only and not is_dir:
                continue
            items.append((prefix + entry.name + ("/" if is_dir else ""), "Ordner" if is_dir else ""))
        return start + (len(arg) - len(raw) if arg.startswith(("\"", "'")) else 0), items[:60], False

    # ------------------------------------------------------------------ Aufträge

    def extract_images(self, text: str) -> tuple[str, list[str]]:
        """Ins Terminal gezogene Bilder kommen als Pfad an – die werden angehängt."""
        found: list[str] = []

        def take(match: re.Match) -> str:
            raw = next(g for g in match.groups() if g)
            path = Path(raw.strip())
            if not path.is_absolute():
                path = Path(self.session["workspace"]) / path
            try:
                if path.is_file() and vision.is_image(path):
                    found.append(vision.store(path.read_bytes()))
                    return f"[Bild: {path.name}]"
            except (OSError, ValueError) as e:
                self.out(self.st(f"  {path.name}: {e}", "warn"))
            return match.group(0)

        return IMAGE_RX.sub(take, text), found

    async def send(self, text: str, display: str | None = None) -> str:
        self.last_sent = (text, display)
        text, found = self.extract_images(text)
        images, self.images = self.images + found, []
        if images and not re.sub(r"\[Bild: [^\]]+\]", "", text).strip():
            text += "\nWas ist auf dem Bild zu sehen?"
        if images:
            self.say("image", "happy")
        self.plan_offer = False
        agent = Agent(self.rt, self.session, self.emit, self.ask, inbox=self.inbox, question=self.question)  # je Auftrag neu
        outcome = await self.run_turn(agent.run(text, display, images))
        # Kam erst nach dem letzten Schritt an: wird der nächste Auftrag – wie in der App.
        if outcome == "done" and self.inbox:
            item = self.inbox.pop(0)
            self.on_queued_taken({"text": item["display"]})
            return await self.send(item["text"], None if item["display"] == item["text"] else item["display"])
        if outcome == "done" and self.plan_offer and self.rt.cfg["permission_mode"] == "plan":
            await self.offer_plan()
        return outcome

    async def run_turn(self, coro) -> str:
        awake = self.rt.cfg.get("keep_awake") != "off"
        if awake:
            power.keep_awake.acquire()
        self.steps, self.tokens, self.gen_seconds = 0, 0, 0.0
        started = time.monotonic()
        outcome = "done"
        self.turn = asyncio.ensure_future(coro)
        self.set_status("denkt nach …", "think")
        try:
            await self.turn
        except asyncio.CancelledError:
            outcome = "cancel"
        except (OllamaError, AgentError) as e:
            outcome = "error"
            self.out(self.st(f"  {e}", "error"))
        except Exception as e:  # noqa: BLE001 — das Terminal soll weiterlaufen
            outcome = "error"
            self.out(self.st(f"  {e.__class__.__name__}: {e}", "error"))
        finally:
            self.turn = None
            if awake:
                power.keep_awake.release()
            self.stop_status()
            self.filter = None
            self.end_text()
            if self.session["messages"]:
                sessions.save(self.session)
            if self.poller and self.poller.buf.strip():
                self.prefill = self.poller.buf  # angefangener Text steht gleich wieder in der Eingabe
            if self.poller:
                self.poller.buf = ""
        if outcome == "cancel":
            waiting = [item["text"] for item in self.inbox]
            self.inbox.clear()
            if waiting:  # nicht verloren: zurück in die Eingabe
                self.prefill = "\n".join(waiting + ([self.prefill] if self.prefill else []))
            self.gap("info")
            # Hier sagt das Maskottchen nichts: Beim Abbruch soll klar und knapp dastehen, was passiert ist.
            self.out(self.st("  Abgebrochen.", "warn"))
        elif outcome == "error":
            self.say("error", "sad")
        elif self.steps or self.tokens:
            seconds = time.monotonic() - started
            stats = []
            if self.tokens and self.gen_seconds > 0.2:  # nur das Tempo; die Token stehen in /status
                stats.append(f"{self.tokens / self.gen_seconds:.0f} tok/s")
            extra = self.st("  " + " · ".join(stats), "dim") if stats else ""
            self.gap("info")
            if self.steps and self.buddy.enabled:
                steps = f"{self.steps} {'Schritt' if self.steps == 1 else 'Schritte'}"
                # Nach einem langen Lauf sagt es etwas anderes als nach einem kurzen.
                self.say("long" if seconds > 120 else "done", "proud" if seconds > 120 else "happy",
                         extra=extra, steps=steps, time=duration(seconds))
            elif self.steps:
                self.out(self.st(f"  {self.g['ok']} {self.steps} Schritte · {duration(seconds)}", "dim") + extra)
            elif extra:
                self.out(extra)
        return outcome

    # ------------------------------------------------------------------ Befehle

    async def command(self, text: str) -> bool | None:
        head, _, rest = text.partition(" ")
        name, rest = head[1:].lower(), rest.strip()
        name = ALIASES.get(name, name)
        if name == "exit":
            return False
        handler = getattr(self, f"cmd_{name}", None) if re.fullmatch(r"[a-z]+", name) else None
        if handler:
            await handler(rest)
            return None
        found = await asyncio.to_thread(commands_mod.load, self.session["workspace"],
                                        bool(self.rt.cfg.get("claude_extensions", True)))
        cmd = next((c for c in found if c["name"] == name), None)
        if cmd:
            await self.send(commands_mod.expand(cmd["template"], rest), display=text)
        else:
            close = [n for n, _ in self.cache["commands"] if n[1:].startswith(name[:2])][:3]
            hint = f" Meintest du {' oder '.join(close)}?" if close else ""
            self.out(self.st(f"  Unbekannter Befehl /{name}.{hint} /help zeigt alle.", "warn"))
        return None

    async def cmd_help(self, _rest: str) -> None:
        pad = min(26, max(len(c) for _g, items in HELP for c, _ in items) + 2)
        room = max(20, T.columns() - pad - 6)
        for group, items in HELP:
            self.out("")
            self.out(f"  {self.st(group, 'bold')}")
            for cmd, text in items:
                if len(cmd) >= pad:  # lange Befehle bekommen ihre eigene Zeile
                    self.out(f"    {self.st(cmd, 'accent')}")
                    self.out(f"    {' ' * pad}{self.st(T.clip(text, room), 'dim')}")
                else:
                    self.out(f"    {self.st(cmd.ljust(pad), 'accent')}{self.st(T.clip(text, room), 'dim')}")
        self.out("")
        self.hint("@agent am Anfang spricht einen Spezialisten an · [[Notiz]] holt eine Notiz dazu")
        if self.editor:
            self.hint("Tab vervollständigt · ↑↓ Verlauf · Umschalt+Enter neue Zeile · Umschalt+Tab wechselt den Modus "
                      "· Esc stoppt den Agent")
            self.hint("Während der Agent arbeitet, weitertippen: Enter reiht die Nachricht ein")
        else:
            self.hint("Zeile mit \\ am Ende geht weiter · Strg+C bricht die laufende Aufgabe ab")

    async def cmd_new(self, _rest: str) -> None:
        self.session = sessions.new(self.rt.cfg["workspace"], self.rt.cfg.get("model", ""))
        self.context = {}
        self.out(self.st("  Neuer Chat.", "dim"))

    async def cmd_resume(self, rest: str) -> None:
        items = sessions.list_all(30)
        if not items:
            self.out(self.st("  Noch keine Chats.", "dim"))
            return
        if not rest:
            cols = T.columns()
            for i, s in enumerate(items[:15], 1):
                where = Path(s["workspace"]).name or s["workspace"]
                meta = f"{ago(s['updated'])} · {where}"
                title = T.clip(s["title"] or "Ohne Titel", max(20, cols - T.width(meta) - 12))
                self.out(f"  {self.st(str(i).rjust(2), 'dim')}  {title}  {self.st(meta, 'dim')}")
            self.out(self.st("  /resume nr oder /resume wort aus dem titel setzt den Chat fort.", "dim"))
            return
        # Nummer aus der Liste, Anfang der Kennung – oder ein Stück vom Titel („/resume login“).
        word = rest.lower()
        pick = items[int(rest) - 1] if rest.isdigit() and 0 < int(rest) <= len(items) else \
            next((s for s in items if s["id"].startswith(rest)), None) or \
            next((s for s in items if word in (s["title"] or "").lower()), None)
        loaded = sessions.load(pick["id"]) if pick else None
        if not loaded:
            self.out(self.st("  Chat nicht gefunden.", "warn"))
            return
        self.session = loaded
        self.out(f"  {self.st(loaded['title'], 'bold')} {self.st('· ' + loaded['workspace'], 'dim')}")
        for m in [m for m in loaded["messages"] if m["role"] == "user" and "_text" in m][-3:]:
            self.out(self.st(f"  {self.g['prompt']} {T.clip(m['_text'], T.columns() - 8)}", "dim"))
        answer = next((m["content"] for m in reversed(loaded["messages"])
                       if m["role"] == "assistant" and (m.get("content") or "").strip()), "")
        if answer:
            lines = termmd.render(answer, width=T.columns(), styles=self.st, glyphs=self.g).splitlines()
            for line in lines[:14]:
                self.out(line)
            if len(lines) > 14:
                self.out(self.st(f"  … {len(lines) - 14} weitere Zeilen", "dim"))

    async def cmd_compact(self, _rest: str) -> None:
        await self.run_turn(Agent(self.rt, self.session, self.emit, self.ask).compact())

    async def cmd_undo(self, _rest: str) -> None:
        try:
            result = await asyncio.to_thread(checkpoints.undo, self.session)
        except ValueError as e:
            self.out(self.st(f"  {e}", "warn"))
            return
        sessions.save(self.session)
        for path in result["restored"]:
            self.out(f"  {self.st(self.g['redo'], 'ok')} {path}")
        for item in result["skipped"]:
            self.out(f"  {self.st('–', 'warn')} {item['path']} {self.st('· ' + item['reason'], 'dim')}")
        if not result["restored"] and not result["skipped"]:
            self.out(self.st("  Die Dateien waren schon im alten Zustand.", "dim"))
        elif result["restored"]:
            self.out(self.st("  Befehle im Terminal lassen sich nicht zurücknehmen – nur Dateiänderungen.", "dim"))
            self.say("undo", "happy")

    async def cmd_mode(self, rest: str) -> None:
        word = rest.strip().lower()
        mode = word if word in PERMISSION_MODES else MODE_ALIASES.get(word)
        if mode:
            await self.rt.update_config({"permission_mode": mode})
            self.out(f"  {self.st('Modus:', 'dim')} {self.mode_label(mode)} {self.st('· ' + MODE_HINT[mode], 'dim')}")
            return
        if word:
            self.out(self.st(f"  Unbekannter Modus „{rest.strip()}“.", "warn"))
        current = self.rt.cfg["permission_mode"]
        for m in PERMISSION_MODES:
            mark = self.st(self.g["prompt"], "accent") if m == current else " "
            name = MODE_LABEL[m].ljust(10)
            self.out(f"  {mark} {self.st(name, 'bold') if m == current else name}{self.st(MODE_HINT[m], 'dim')}")
        self.hint("/mode normal · /mode chat … – oder Umschalt+Tab in der Eingabe" if self.editor
                  else "/mode normal · /mode chat · /mode planen …")

    async def cmd_effort(self, rest: str) -> None:
        word = rest.strip()
        if word:
            level = effort_mod.parse(word)
            if not level:
                self.out(self.st(f"  Unbekannte Stufe „{word}“ – niedrig, mittel, hoch oder max.", "warn"))
                return
            await self.rt.update_config({"effort": level})
        current = effort_mod.level(self.rt.cfg)
        for level in effort_mod.LEVELS:
            mark = self.st(self.g["prompt"], "accent") if level == current else " "
            name = effort_mod.LABEL[level].ljust(9)
            self.out(f"  {mark} {self.st(name, 'bold') if level == current else name}{self.st(effort_mod.HINT[level], 'dim')}")
        cfg = self.rt.cfg
        self.hint(f"Schritte höchstens {effort_mod.steps(cfg)} · Kontrolle "
                  f"{'an, ' + str(effort_mod.controller_rounds(cfg)) + ' Nachbesserungen' if effort_mod.controller_on(cfg) else 'aus'}"
                  " · Denkmodus " + {"low": "aus", "medium": "nach /think", "high": "an", "max": "an"}[current])

    async def cmd_style(self, rest: str) -> None:
        word = rest.strip()
        if word:
            chosen = personal_mod.parse_style(word)
            if not chosen:
                names = ", ".join(personal_mod.LABEL[s].lower() for s in personal_mod.STYLES)
                self.out(self.st(f"  Unbekannter Stil „{word}“ – {names}.", "warn"))
                return
            await self.rt.update_config({"style": chosen})
        current = personal_mod.style(self.rt.cfg)
        for name in personal_mod.STYLES:
            mark = self.st(self.g["prompt"], "accent") if name == current else " "
            label = personal_mod.LABEL[name].ljust(13)
            self.out(f"  {mark} {self.st(label, 'bold') if name == current else label}"
                     f"{self.st(personal_mod.HINT[name], 'dim')}")
        self.hint("/stil knapp · /stil erklärend … – gilt ab dem nächsten Auftrag, hier und in der App")

    # Welches Feld /anweisungen meint: ohne Angabe das allgemeine, sonst das eines Tabs.
    INSTRUCTION_FIELDS = {"code": ("user_prompt_code", "nur im Tab Code und hier im Terminal"),
                          "chat": ("user_prompt_talk", "nur im Tab Chat"),
                          "": ("user_prompt", "überall")}
    CLEAR_WORDS = ("leeren", "löschen", "loeschen", "aus", "clear", "reset")

    async def cmd_instructions(self, rest: str) -> None:
        """Eigene Anweisungen (User-Prompt): ansehen, setzen, ergänzen, leeren – dieselben wie in der App."""
        text = rest.strip()
        head, _, tail = text.partition(" ")
        field = head.lower() if head.lower() in ("code", "chat") else ""
        if field:
            text = tail.strip()
        key, where = self.INSTRUCTION_FIELDS[field]
        cfg = self.rt.cfg
        if text:
            if text.lower() in self.CLEAR_WORDS:
                value = ""
            elif text.startswith("+"):
                value = "\n".join(p for p in (personal_mod.clean(cfg.get(key)), text[1:].strip()) if p)
            else:
                value = text
            value = personal_mod.clean(value)
            await self.rt.update_config({key: value})
            cfg = self.rt.cfg
            self.gap("info")
            self.out(self.st(f"  {self.g['ok']} ", "ok") + (f"Anweisungen {where} gesichert – gilt ab dem nächsten Auftrag."
                                                           if value else f"Anweisungen {where} gelöscht."))
        self.gap("info")
        room = max(20, T.columns() - 8)
        for name, (k, label) in (("", self.INSTRUCTION_FIELDS[""]), ("code", self.INSTRUCTION_FIELDS["code"])):
            value = personal_mod.clean(cfg.get(k))
            title = "Für alles" if not name else "Nur Code"
            self.out(f"  {self.st(title, 'bold')}  {self.st(label, 'dim')}")
            if value:
                for line in value.splitlines()[:12]:
                    self.out("    " + T.clip(line, room))
                if len(value.splitlines()) > 12:
                    self.out(self.st(f"    … {len(value.splitlines()) - 12} Zeilen mehr", "dim"))
            else:
                self.out(self.st("    (leer)", "dim"))
        style = personal_mod.style(cfg)
        self.out(f"  {self.st('Stil', 'bold')}  {personal_mod.LABEL[style]} {self.st('– ' + personal_mod.HINT[style], 'dim')}")
        self.hint("/anweisungen text setzt · /anweisungen + text hängt an · /anweisungen code … nur hier · "
                  "/anweisungen leeren · /stil – in der App unter Einstellungen → Persönlich")

    # Pegelbalken für die Statuszeile – acht Stufen, damit man das Sprechen sieht.
    LEVEL_BARS = "▁▂▃▄▅▆▇█"
    SPEAKING = 0.06  # ab hier gilt es als gesprochen
    QUIET = 0.02  # darunter ist es still
    HANG_UP = 1.3  # so lange Stille beendet die Aufnahme
    NOTHING = 9.0  # so lange gar nichts: dann war das Mikrofon wohl stumm
    LIMIT = 120.0  # Obergrenze im Terminal

    async def cmd_diktat(self, rest: str) -> None:
        """Sprechen statt tippen: aufnehmen, bis es still wird – der Text steht danach in der Eingabe."""
        if not self.rt.cfg.get("speech", True):
            self.gap("info")
            self.out(self.st("  Das Diktat ist abgeschaltet – in der App unter Einstellungen wieder an.", "warn"))
            return
        hindernis = await asyncio.to_thread(speech_mod.blocked, self.rt.cfg)
        if hindernis:
            self.gap("info")
            self.out(self.st("  " + hindernis, "warn"))
            if speech_mod.missing():
                self.hint(f"Nachrüsten mit: pip install {' '.join(speech_mod.missing())} – danach Coder neu starten.")
            elif "Erkennungsmodell" in hindernis:
                self.hint("Das Modell holst du in der App unter Einstellungen → Sprechen statt tippen.")
            return
        rec = speech_mod.Recorder()
        try:
            await asyncio.to_thread(rec.start, speech_mod.input_index(self.rt.cfg))
        except Exception as e:  # noqa: BLE001 – belegtes Mikrofon, fehlender Audiodienst
            self.gap("info")
            self.out(self.st(f"  Das Mikrofon lässt sich nicht öffnen: {e}", "error"))
            return
        self.gap("info")
        if self.midline:
            self.write("\n")  # hinter der Eingabezeile ist kein Platz – die Statuszeile braucht eine eigene
        began = time.monotonic()
        peak, quiet_since = 0.0, None
        try:
            while True:
                await asyncio.sleep(0.1)
                level, seconds = rec.level, rec.seconds
                peak = max(peak, level)
                step = min(len(self.LEVEL_BARS) - 1, int(level ** 0.5 * len(self.LEVEL_BARS)))
                bars = self.LEVEL_BARS[step] * (1 + step // 2)
                # Direkt gesetzt, damit die Uhr der Statuszeile weiterläuft, statt bei jedem Pegel neu zu starten.
                self.status = (f"Sprich – ich höre zu  {bars}", "ask", began)
                # Esc und Strg+C beenden das Diktat, ohne den Ton zu verwenden; Getipptes sammelt der Poller.
                if any(e in ("esc", "interrupt") for e in (self.poller.poll() if self.poller else [])):
                    raise KeyboardInterrupt
                if seconds >= self.LIMIT:
                    break
                if peak >= self.SPEAKING:
                    if level < self.QUIET:
                        quiet_since = quiet_since or time.monotonic()
                        if time.monotonic() - quiet_since >= self.HANG_UP:
                            break
                    else:
                        quiet_since = None
                elif seconds >= self.NOTHING:
                    break
        except (KeyboardInterrupt, asyncio.CancelledError):
            await asyncio.to_thread(rec.stop)
            self.stop_status()
            self.out(self.st("  Abgebrochen.", "warn"))
            return
        audio = await asyncio.to_thread(rec.stop)
        laenge = 0 if audio is None else len(audio) / speech_mod.SAMPLE_RATE
        if audio is None or laenge < speech_mod.MIN_SECONDS or peak < self.SPEAKING:
            self.stop_status()
            self.out(self.st("  Nichts gehört – ist das richtige Mikrofon eingestellt?", "warn"))
            self.hint("Auswahl in der App unter Einstellungen → Sprechen statt tippen.")
            return
        self.set_status("Schreibe mit …", "think")
        try:
            heard = await asyncio.to_thread(speech_mod.transcribe, audio, self.rt.cfg)
        except Exception as e:  # noqa: BLE001 – Modell weg, Speicher voll
            self.stop_status()
            self.out(self.st(f"  Erkennen ging nicht: {e}", "error"))
            return
        self.stop_status()
        text = heard["text"]
        if not text:
            self.out(self.st("  Da war nichts zu verstehen.", "warn"))
            return
        self.prefill = f"{self.prefill} {text}".strip() if self.prefill else text
        self.out(f"  {self.st(self.g['arrow'], 'ok')} {text}")
        self.hint(f"steht in der Eingabe · {laenge:.0f} s gesprochen, {heard['took']:.1f} s erkannt")

    async def cmd_theme(self, rest: str) -> None:
        word = rest.strip().lower()
        if word:
            if word not in CLI_THEMES:
                self.out(self.st(f"  Unbekanntes Thema „{rest.strip()}“. Es gibt: {', '.join(CLI_THEMES)}.", "warn"))
                return
            await self.rt.update_config({"cli_theme": word})
            self.st.set_theme(word)
        wanted = self.rt.cfg.get("cli_theme", "auto")
        for name in CLI_THEMES:
            mark = self.st(self.g["prompt"], "accent") if name == wanted else " "
            label = T.THEME_LABEL.get(name, "Automatisch").ljust(22)
            hint = T.THEME_HINT.get(name) or f"jetzt: {T.THEME_LABEL[T.theme_name('auto')]}"
            self.out(f"  {mark} {self.st(label, 'bold') if name == wanted else label}{self.st(hint, 'dim')}")
        st = self.st
        sample = (f"{st('+ hinzugefügt', 'ok')}  {st('− entfernt', 'error')}  {st('Warnung', 'warn')}  "
                  f"{st('Akzent', 'accent')}  {st('code', 'code')}  {st('gedimmt', 'dim')}")
        self.out("")
        self.out("    " + sample)

    async def cmd_model(self, rest: str) -> None:
        try:
            data = await self.rt.models()
        except OllamaError as e:
            self.out(self.st(f"  {e}", "error"))
            return
        items = data["models"]
        if not rest:
            current = self.rt.cfg.get("model") or data["recommended"]
            name_w = min(40, max((len(m["name"]) for m in items), default=10) + 1)
            for i, m in enumerate(items, 1):
                caps, plan = m["profile"]["capabilities"], m["plan"]
                tags = [t for t, ok in (("Tools", "tools" in caps), ("Bilder", "vision" in caps),
                                        ("empfohlen", m["name"] == data["recommended"])) if ok]
                where = {"gpu": "GPU", "mixed": "GPU+RAM", "cpu": "CPU", "disk": "Platte"}.get(plan.get("fit"), "")
                fit = f"{plan['num_ctx'] // 1024}K · {where} · {plan.get('tokens_per_s', 0):g} tok/s"
                mark = self.st(self.g["done"], "ok") if m["name"] == current else " "
                self.out(f"  {mark} {self.st(str(i).rjust(2), 'dim')} {m['name'][:name_w].ljust(name_w)} "
                         f"{self.st(fit.ljust(16), 'dim')} {self.st(' · '.join(tags), 'code')}")
            roles = data.get("roles") or {}
            self.out(self.st(f"  Kontrolle: {roles.get('controller') or '–'} · Bilder: {roles.get('vision') or '–'} · "
                             f"Gedächtnis: {roles.get('embed') or 'nur Stichworte'}", "dim"))
            self.out(self.st("  /model nr oder /model name wechselt.", "dim"))
            return
        name = items[int(rest) - 1]["name"] if rest.isdigit() and 0 < int(rest) <= len(items) else rest
        if name not in {m["name"] for m in items}:
            self.out(self.st(f"  {name} ist nicht installiert.", "warn"))
            return
        await self.rt.update_config({"model": name})
        self.out(self.st(f"  Modell: {name} – wird beim nächsten Auftrag geladen.", "dim"))

    async def cmd_workspace(self, rest: str) -> None:
        if not rest:
            self.out(f"  {self.session['workspace']}")
            return
        path = normalize_path(rest)
        if not path.is_dir():
            self.out(self.st(f"  Ordner nicht gefunden: {path}", "warn"))
            return
        reason = blocked_workspace(path)
        if reason:
            self.out(self.st(f"  {path} geht nicht als Workspace ({reason}).", "warn"))
            return
        await self.rt.update_config({"workspace": str(path)})
        self.session = sessions.new(str(path), self.rt.cfg.get("model", ""))
        self.cache["stamp"] = 0.0
        self.out(self.st(f"  Workspace: {path} · neuer Chat", "dim"))

    async def cmd_agents(self, _rest: str) -> None:
        found = await asyncio.to_thread(agents_mod.load, self.session["workspace"],
                                        bool(self.rt.cfg.get("claude_extensions", True)))
        pad = max((len(a.name) for a in found.values()), default=8) + 3
        for a in found.values():
            # Ein eigenes Modell steht rechts – sonst arbeitet der Agent mit dem des Hauptagenten.
            modell = self.st(f"  ({a.model})", "code") if a.model else ""
            text = T.clip(a.description, max(20, T.columns() - pad - 4 - T.width(modell)))
            self.out(f"  {self.st(('@' + a.name).ljust(pad), 'accent')}{self.st(text, 'dim')}{modell}")

    async def cmd_commands(self, _rest: str) -> None:
        found = commands_mod.for_tab(await asyncio.to_thread(commands_mod.load, self.session["workspace"],
                                                             bool(self.rt.cfg.get("claude_extensions", True))), "code")
        for c in found:
            head = f"/{c['name']}" + (f" {c['hint']}" if c["hint"] else "")
            origin = "" if c["source"] == "builtin" else self.st(f"  ({c['source']})", "dim")
            text = T.clip(c["description"], max(20, T.columns() - 40))
            self.out(f"  {self.st(head[:34].ljust(34), 'accent')} {self.st(text, 'dim')}{origin}")

    # ------------------------------------------------------------------ Gedächtnis

    async def cmd_memory(self, rest: str) -> None:
        """Überblick über alle Notizen, eine Notiz ganz – oder die Suche danach."""
        workspace = self.session["workspace"]
        notes = await asyncio.to_thread(memory_mod.load, workspace)
        arg = rest.strip()
        if arg:
            note = memory_mod.find(notes, arg.strip("[]"))
            if note:
                self.show_note(note, notes)
                return
            hits = await recall.search(arg, workspace, self.rt, limit=8)
            if not hits:
                self.out(self.st(f"  Keine Notiz zu „{arg}“.", "dim"))
                return
            cols = T.columns()
            for h in hits:
                self.out(f"  {self.st(h['title'], 'bold')} {self.st('· ' + VAULT_LABEL.get(h['vault'], h['vault']), 'dim')}")
                for line in textwrap.wrap(h["snippet"], max(30, cols - 8))[:2]:
                    self.out(self.st(f"    {line}", "dim"))
            self.hint("/memory Titel zeigt eine Notiz ganz.")
            return
        if not notes:
            self.hint("Noch keine Notizen. Coder legt sie an, sobald er etwas Dauerhaftes lernt – "
                      "oder du sagst es ihm mit /remember.")
            return
        overview = await asyncio.to_thread(memory_mod.overview, workspace)
        links = {n["id"]: len(n["links"]) + n.get("backlinks", 0) for n in overview["notes"]}
        cols = T.columns()
        for vault in ("project", "global"):
            items = sorted((n for n in notes if n.vault == vault), key=lambda n: (not n.pinned, -n.updated))
            if not items:
                continue
            where = overview["folders"].get(vault, "")
            room = cols - T.width(VAULT_LABEL[vault]) - len(str(len(items))) - 10
            if T.width(where) > room:  # lange Pfade vorn kürzen – das Ende sagt, wo es ist
                where = "…" + where[-max(10, room - 1):]
            self.out("")
            self.out(f"  {self.st(VAULT_LABEL[vault], 'bold')} {self.st(f'{len(items)} · {where}', 'dim')}")
            title_w = min(28, max(T.width(n.title) for n in items[:30]) + 1)
            for n in items[:30]:
                mark = self.st(self.g["pin"], "warn") if n.pinned else " "
                count = links.get(n.key, 0)
                meta = f"{count} {'Link' if count == 1 else 'Links'}" if count else ""
                room = cols - title_w - T.width(meta) - 12
                excerpt = T.clip(memory_mod.plain(n.body), max(10, room)) if room > 14 else ""
                title = T.clip(n.title, title_w)
                self.out(f"  {mark} {title}{' ' * (title_w - T.width(title))} {self.st(excerpt, 'dim')}"
                         + (self.st(f"  {meta}", "dim") if meta else ""))
            if len(items) > 30:
                self.out(self.st(f"    … und {len(items) - 30} weitere – /memory suche findet sie", "dim"))
        library = [n.title for n in notes if n.vault == "library"]
        if library:
            self.out("")
            self.out(f"  {self.st('Bibliothek', 'bold')} {self.st(f'{len(library)} · Leitfäden, schreibgeschützt', 'dim')}")
            for line in textwrap.wrap(", ".join(library), max(30, cols - 6)):
                self.out(self.st(f"    {line}", "dim"))
        self.out("")
        self.hint("/memory Titel liest eine Notiz · /memory suche findet nach Bedeutung · "
                  "[[Titel]] in einer Nachricht holt sie dazu")

    def show_note(self, note, notes: list) -> None:
        vault = VAULT_LABEL.get(note.vault, note.vault)
        when = "schreibgeschützt" if note.vault == "library" else f"geändert {ago(note.updated)}"
        self.out("")
        pin = f" {self.st(self.g['pin'], 'warn')}" if note.pinned else ""
        self.out(f"  {self.st(note.title, 'bold')}{pin} {self.st(f'· {vault} · {when}', 'dim')}")
        if note.tags:
            self.out(self.st("  " + " ".join(f"#{t}" for t in note.tags), "code"))
        self.out("")
        body = termmd.render(note.body or "_(leer)_", width=T.columns(), styles=self.st, glyphs=self.g, indent=2)
        for line in body.splitlines():
            self.out(line)
        back = [b.title for b in memory_mod.backlinks(notes, note)]
        if note.links or back:
            self.out("")
        if note.links:
            self.out(self.st(f"  Verweist auf: {', '.join(note.links)}", "dim"))
        if back:
            self.out(self.st(f"  Verlinkt von: {', '.join(back)}", "dim"))
        self.out(self.st(f"  {note.path}", "dim"))

    async def cmd_controller(self, rest: str) -> None:
        arg = rest.lower()
        if arg in ("an", "on", "ein"):
            await self.rt.update_config({"controller": True})
        elif arg in ("aus", "off"):
            await self.rt.update_config({"controller": False})
        elif arg in ("auto", "automatisch"):
            await self.rt.update_config({"controller_model": ""})
        elif rest:
            if rest not in await self.rt.installed(max_age=0):
                self.out(self.st(f"  {rest} ist nicht installiert.", "warn"))
                return
            await self.rt.update_config({"controller_model": rest, "controller": True})
        cfg = self.rt.cfg
        model = await self.rt.controller_model(cfg.get("model") or "") or "das Hauptmodell"
        source = "" if cfg.get("controller_model") else " (automatisch)"
        interval = cfg.get("controller_interval") or 0
        self.out(f"  Kontrolle {self.st('an' if cfg.get('controller') else 'aus', 'bold')} · {model}{self.st(source, 'dim')}")
        self.hint(f"prüft am Ende jeder Aufgabe mit Änderungen · höchstens {cfg.get('controller_rounds', 2)} "
                  f"Nachbesserungen · {'alle ' + str(interval) + ' min zwischendurch' if interval else 'nicht zwischendurch'}")

    async def cmd_think(self, rest: str) -> None:
        arg = rest.lower()
        if arg in ("an", "on", "ein"):
            await self.rt.update_config({"think": True})
        elif arg in ("aus", "off"):
            await self.rt.update_config({"think": False})
        on = bool(self.rt.cfg.get("think"))
        self.hint(f"Gedanken {'werden mitgelesen' if on else 'bleiben verborgen'} – nur bei Modellen mit "
                  f"Denkmodus. /think {'aus' if on else 'an'} schaltet um.")
        self.hint("Ob das Modell überhaupt nachdenkt, regelt der Aufwand: Niedrig nie, Mittel nach dieser "
                  "Einstellung, Hoch und Maximal immer (/effort).")

    async def cmd_image(self, rest: str) -> None:
        if not rest:
            self.hint(f"{len(self.images)} Bild(er) hängen an der nächsten Nachricht." if self.images
                      else "Kein Bild angehängt. /image pfad – oder das Bild einfach ins Terminal ziehen.")
            return
        if rest.lower() in ("weg", "löschen", "clear"):
            self.images = []
            self.out(self.st("  Anhänge entfernt.", "dim"))
            return
        path = Path(rest.strip("\"'"))
        if not path.is_absolute():
            path = Path(self.session["workspace"]) / path
        if not path.is_file() or not vision.is_image(path):
            self.out(self.st(f"  Kein Bild gefunden: {path}", "warn"))
            return
        try:
            self.images.append(vision.store(path.read_bytes()))
        except (OSError, ValueError) as e:
            self.out(self.st(f"  {e}", "warn"))
            return
        self.out(self.st(f"  {path.name} hängt an der nächsten Nachricht.", "dim"))

    # ------------------------------------------------------------------ Schleife, Schärfen, Drucken

    async def cmd_loop(self, rest: str) -> None:
        """Denselben Auftrag wiederholen – bis er sitzt, bis die Runden alle sind oder bis du stoppst."""
        arg = rest.strip()
        if arg.lower() in ("stop", "aus", "ende", "halt", "schluss"):
            if self.loop and self.loop.running:
                self.loop.stop("user")
                self.out(self.st("  Die Schleife endet nach dieser Runde.", "dim"))
            else:
                self.out(self.st("  Es läuft keine Schleife.", "dim"))
            return
        if self.loop and self.loop.running:
            self.out(self.st(f"  Es läuft schon eine Schleife: {T.clip(self.loop.display or self.loop.task, 60)} · "
                             f"{self.loop.label}", "warn"))
            self.out(self.st("  /loop stop beendet sie.", "dim"))
            return
        if not arg:
            for line in loop_mod.__doc__.strip().splitlines()[2:7]:
                self.out(self.st("  " + line.strip(), "dim"))
            return
        try:
            self.loop = loop_mod.parse(arg)
        except loop_mod.LoopError as e:
            self.out(self.st(f"  {e}", "warn"))
            return
        # /loop 3x /review: der Befehl wird ausgeschrieben, sonst liest das Modell nur „/review“
        task, shown = await asyncio.to_thread(commands_mod.resolve, self.loop.task, self.session["workspace"],
                                              bool(self.rt.cfg.get("claude_extensions", True)))
        self.loop.task, self.loop.display = task, shown or ""
        await self.run_loop()

    async def run_loop(self) -> None:
        lp = self.loop
        name = lp.display or lp.task
        wie = f"{lp.times} Runden" if lp.times else f"alle {loop_mod.human(lp.every)}, bis du stoppst"
        self.out(self.st(f"  Schleife: {T.clip(name, 60)} · {wie} · Strg+C beendet sie.", "dim"))
        while lp.running and self.loop is lp:
            mark = len(self.session["messages"])
            outcome = await self.run_turn(
                Agent(self.rt, self.session, self.emit, self.ask, inbox=self.inbox).run(
                    lp.prompt(), f"/loop {T.clip(name, 70)} · Runde {lp.round}"))
            if outcome != "done":
                lp.stop("user" if outcome == "cancel" else "error")
                break
            lp.note(self.last_answer(mark))
            if not lp.running:
                break
            if lp.every and not await self.pause(lp.every):
                lp.stop("user")
                break
        self.out(self.st(f"  Schleife beendet nach {lp.round} {'Runde' if lp.round == 1 else 'Runden'} – {lp.reason}.", "dim"))
        if lp.stopped_by == "done":
            self.say("done", "happy", steps=f"{lp.round} Runden", time="")
        self.loop = None

    def last_answer(self, since: int = 0) -> str:
        """Der letzte Text des Agenten – daran erkennt die Schleife, ob Schluss ist."""
        for m in reversed(self.session.get("messages", [])[since:]):
            if m.get("role") == "assistant" and str(m.get("content") or "").strip():
                return str(m["content"])
        return ""

    async def pause(self, seconds: float) -> bool:
        """Wartet bis zur nächsten Runde. False heißt: Strg+C – Schluss."""
        self.out(self.st(f"  Nächste Runde in {loop_mod.human(seconds)} · Strg+C beendet die Schleife.", "dim"))
        self.turn = asyncio.ensure_future(asyncio.sleep(seconds))
        self.set_status("Schleife wartet …", "sleep")
        try:
            await self.turn
            return True
        except asyncio.CancelledError:
            return False
        finally:
            self.turn = None
            self.stop_status()

    async def cmd_prompt(self, rest: str) -> None:
        """Den Auftrag vom Modell schärfen lassen und ihn sich vorher ansehen."""
        text, kind = rest.strip(), "auto"
        for prefix, want in (("bild:", "image"), ("image:", "image"), ("aufgabe:", "task"), ("task:", "task")):
            if text.lower().startswith(prefix):
                kind, text = want, text[len(prefix):].strip()
        if not text and self.last_sent:
            text = self.last_sent[0]
        if not text:
            self.hint("/prompt <auftrag> schärft ihn vor dem Senden. Mit „bild:“ davor kommt ein Bildprompt.")
            return
        self.set_status("schärft den Auftrag", "think")
        try:
            sharp = await preprompt.sharpen(self.rt, text, workspace=self.session["workspace"], kind=kind)
        except (OllamaError, ValueError) as e:
            self.stop_status()
            self.out(self.st(f"  {e}", "error"))
            return
        finally:
            self.stop_status()
        self.out("")
        self.out(self.st(f"  {'Bildprompt' if sharp['kind'] == 'image' else 'Auftrag'} · {sharp['model']}", "dim"))
        for line in textwrap.wrap(sharp["text"], max(40, min(96, T.columns() - 6))) or [""]:
            self.out("  " + self.st(line, "code"))
        if not sharp["changed"]:
            self.out(self.st("  (unverändert)", "dim"))
        answer = await self.choose(f"\n  {self.st('Senden?', 'bold')} {self.st('[J]a · [b]earbeiten · [n]ein', 'dim')} › ",
                                   {"j": "send", "y": "send", "b": "edit", "e": "edit", "n": "drop", "esc": "drop"},
                                   "send")
        if answer == "drop":
            self.out(self.st("  Verworfen.", "dim"))
            return
        if answer == "edit":
            if self.editor:
                edited = (await self.read_line(sharp["text"])).strip()
            else:
                self.out(self.st("  Ändere den Text und drücke Enter – leer lassen bricht ab.", "dim"))
                try:
                    edited = (await asyncio.to_thread(input, "  › ")).strip()
                except EOFError:
                    edited = ""
            if not edited:
                self.out(self.st("  Verworfen.", "dim"))
                return
            sharp["text"] = edited
        await self.send(sharp["text"])

    async def cmd_print(self, rest: str) -> None:
        """Bericht zum Ausdrucken – für eine Abgabe oder ein Gespräch mit dem Prüfer."""
        if not [m for m in self.session.get("messages") or [] if m.get("role") == "user"]:
            self.out(self.st("  In diesem Chat ist noch nichts passiert.", "dim"))
            return
        target = rest.strip().strip("\"'") or None
        if target and not Path(target).is_absolute():
            target = str(Path(self.session["workspace"]) / target)
        try:
            path = await asyncio.to_thread(
                report.save, self.session, target, author=str(self.rt.cfg.get("report_author") or ""))
        except OSError as e:
            self.out(self.st(f"  Bericht lässt sich nicht schreiben: {e}", "error"))
            return
        self.out(self.st(f"  Bericht: {path}", "dim"))
        self.out(self.st("  Im Browser öffnen und mit Strg+P drucken – A4, alles drin.", "dim"))
        open_path(path)

    # ------------------------------------------------------------------ Kleine Helfer im Alltag

    async def cmd_diff(self, _rest: str) -> None:
        """Was der letzte Auftrag geändert hat."""
        changes = checkpoints.latest(self.session)
        if not changes:
            self.out(self.st("  Der letzte Auftrag hat nichts geändert.", "dim"))
            return
        for f in changes.get("files") or []:
            state = "neu" if f.get("created") else "gelöscht" if f.get("deleted") else "geändert"
            counts = ("binär" if f.get("added") is None
                      else f"{self.st('+' + str(f.get('added', 0)), 'ok')} {self.st('−' + str(f.get('removed', 0)), 'error')}")
            self.out(f"  {f.get('path', '')}  {self.st(state, 'dim')}  {counts}")
        self.out(self.st("  /undo nimmt das zurück.", "dim"))

    async def cmd_todo(self, _rest: str) -> None:
        todos = self.session.get("todos") or []
        if not todos:
            self.out(self.st("  Keine Aufgabenliste – der Agent legt sie bei mehrstufiger Arbeit selbst an.", "dim"))
            return
        mark = {"pending": self.st("[ ]", "dim"), "in_progress": self.st("[~]", "warn"), "completed": self.st("[x]", "ok")}
        for t in todos:
            self.out(f"  {mark.get(t.get('status'), '[ ]')} {t.get('content', '')}")

    async def cmd_open(self, rest: str) -> None:
        """Datei oder Ordner im System öffnen – praktisch für erzeugte Bilder."""
        target = rest.strip().strip("\"'")
        path = Path(target) if target else Path(self.session["workspace"])
        if not path.is_absolute():
            path = Path(self.session["workspace"]) / path
        if not path.exists():
            self.out(self.st(f"  Nicht gefunden: {path}", "warn"))
            return
        if open_path(path):
            self.out(self.st(f"  Geöffnet: {path}", "dim"))
        else:
            self.out(self.st(f"  Öffnen ging nicht: {path}", "warn"))

    async def cmd_paste(self, _rest: str) -> None:
        """Bild aus der Zwischenablage an die nächste Nachricht hängen."""
        try:
            from PIL import ImageGrab
        except ImportError:
            self.out(self.st("  Dafür fehlt Pillow: pip install pillow", "warn"))
            return
        try:
            grabbed = await asyncio.to_thread(ImageGrab.grabclipboard)
        except Exception as e:  # noqa: BLE001 – die Zwischenablage ist auf jedem System anders kaputt
            self.out(self.st(f"  Zwischenablage nicht lesbar: {e}", "warn"))
            return
        if isinstance(grabbed, list):  # kopierte Datei statt Bilddaten
            for name in grabbed:
                await self.cmd_image(str(name))
            return
        if grabbed is None:
            self.out(self.st("  In der Zwischenablage ist kein Bild.", "dim"))
            return
        buffer = io.BytesIO()
        grabbed.convert("RGBA").save(buffer, "PNG")
        try:
            self.images.append(vision.store(buffer.getvalue()))
        except (OSError, ValueError) as e:
            self.out(self.st(f"  {e}", "warn"))
            return
        size = f"{grabbed.width}×{grabbed.height}"
        self.out(self.st(f"  Bild aus der Zwischenablage hängt an der nächsten Nachricht ({size}).", "dim"))

    async def cmd_retry(self, _rest: str) -> None:
        if not self.last_sent:
            self.out(self.st("  Noch nichts gesendet.", "dim"))
            return
        text, display = self.last_sent
        self.out(self.st(f"  Noch einmal: {T.clip(display or text, 70)}", "dim"))
        await self.send(text, display)

    async def cmd_status(self, _rest: str) -> None:
        cfg = self.rt.cfg
        hw = optimizer.detect_hardware(max_age=0)
        loaded = await self.rt.loaded()
        model = cfg.get("model") or "automatisch"
        plan = self.rt.plans.get(cfg.get("model") or "")
        rows = [("Modell", model + (f" · {plan['num_ctx'] // 1024}K Kontext" if plan else ""))]
        if plan:
            where = {"gpu": "ganz auf der GPU", "mixed": "GPU und Arbeitsspeicher", "cpu": "auf der CPU",
                     "disk": "zu groß – liest von der Platte"}.get(plan.get("fit"), "")
            rows.append(("Tempo", f"{where} · {round(plan.get('gpu_share', 0) * 100)} % GPU · geschätzt "
                                  f"{plan.get('tokens_per_s', 0):g} Token/s"))
        if hw["gpus"]:
            free = hw["vram_free"] / 1024 ** 3
            rows.append(("Grafik", f"{hw['gpus'][0]['name']} · {hw['vram_total'] / 1024 ** 3:.0f} GB, {free:.1f} GB frei"))
        rows.append(("Geladen", ", ".join(f"{m['name']} ({round(m['gpu_share'] * 100)} % GPU)" for m in loaded) or "nichts"))
        if self.rt.backend == "vllm":
            rows.append(("Server", f"vLLM unter {self.rt.server_url} – dieselben Modelldateien wie Ollama"))
        if self.context.get("max"):
            share = round(self.context["used"] / self.context["max"] * 100)
            rows.append(("Kontext", f"{number(self.context['used'])} von {number(self.context['max'])} Token ({share} %)"))
        usage = self.session.get("usage") or {}
        if usage:
            rows.append(("Token", f"Prompt {number(usage.get('prompt', 0))} · Antworten {number(usage.get('completion', 0))}"))
        awake = {"open": "solange Coder offen ist", "work": "während der Arbeit", "off": "aus"}.get(cfg.get("keep_awake"), "aus")
        rows.append(("Modus", f"{MODE_LABEL[cfg['permission_mode']]} · Aufwand {effort_mod.LABEL[effort_mod.level(cfg)]} · "
                              f"Kontrolle {'an' if effort_mod.controller_on(cfg) else 'aus'} · PC wach {awake}"))
        notes = await asyncio.to_thread(memory_mod.load, self.session["workspace"])
        counts = {v: sum(1 for n in notes if n.vault == v) for v in ("project", "global", "library")}
        embed = await self.rt.embed_model()
        memory_line = (f"{counts['project']} Projekt · {counts['global']} global · {counts['library']} Bibliothek · "
                       f"{'nach Bedeutung (' + embed + ')' if embed else 'nur Stichworte'}")
        rows.append(("Gedächtnis", memory_line if cfg.get("memory", True) else "aus"))
        backend = await imagegen.detect(cfg)
        rows.append(("Bilder", f"{backend['label']} unter {backend['url']}" if backend else "kein Bilddienst gefunden"))
        rows.append(("Workspace", self.session["workspace"]))
        for label, value in rows:
            self.out(f"  {self.st(label.ljust(11), 'dim')} {value}")

    async def cmd_buddy(self, rest: str) -> None:
        buddy, arg = self.buddy, rest.lower()
        if arg in ("aus", "off"):
            buddy.data["enabled"] = False
            buddy.save()
            self.out(self.st(f"  {buddy.name} macht Pause. /buddy an holt es zurück.", "dim"))
            return
        if arg in ("an", "on"):
            buddy.data["enabled"] = True
            buddy.save()
        elif arg.startswith("name "):
            new = rest[5:].strip()[:20]
            if new:
                buddy.data["name"] = new
                buddy.save()
                for line in self.scene(f"Ab jetzt heiße ich {new}!", "happy"):
                    self.out(line)
                return
        elif arg in ("streicheln", "pet", "kraulen"):
            buddy.pet()
            for line in self.scene(buddy.line("pet"), "love"):
                self.out(line)
            return
        for line in self.scene(f"Hi, ich bin {buddy.name}!", "happy"):
            self.out(line)
        born = time.strftime("%d.%m.%Y", time.localtime(buddy.data.get("born", time.time())))
        about = f"· Axolotl · geschlüpft am {born} · {buddy.data.get('pets', 0)}× gestreichelt"
        self.out(f"  {self.st(buddy.name, 'buddy')} {self.st(about, 'dim')}")
        self.out(self.st("  /buddy streicheln · /buddy name Pixel · /buddy aus", "dim"))


async def run() -> int:
    T.enable_vt()
    T.enable_ctrl_c()
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except (AttributeError, ValueError):
            pass
    return await Terminal(Runtime()).main()
