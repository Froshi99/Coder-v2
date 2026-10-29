"""Terminal-Grundlagen: Farben, Zeichen und Breiten – einmal richtig, für alle Teile des Terminalmodus.

Zwei Zeichensätze: Moderne Terminals (Windows Terminal, VS Code, macOS, Linux) zeichnen Symbole wie ⠋ ⎿ ✦ ◆. Die alte
Windows-Konsole mit Consolas kann das nicht und zeigt Kästchen – dort nimmt Coder Zeichen, die Consolas hat.
Mit CODER_GLYPHS=unicode oder CODER_GLYPHS=basic lässt sich das erzwingen, NO_COLOR schaltet Farben ab.
"""

import os
import re
import shutil
import sys
import unicodedata

ANSI_RX = re.compile(r"\033\[[0-9;?]*[A-Za-z]|\033\][^\007\033]*(?:\007|\033\\)")


def strip(text: str) -> str:
    return ANSI_RX.sub("", str(text))


# Fremder Text – Antworten des Modells, Ausgaben von Befehlen, Webseiten – darf das Terminal nicht steuern: kein
# Bildschirm löschen, kein Cursor, der einen angezeigten Befehl in der Freigabe überschreibt, keine Zwischenablage.
FOREIGN_RX = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)?|[\x00-\x08\x0b-\x1f\x7f-\x9f]")


def safe(text: str) -> str:
    """Steuerzeichen aus fremdem Text entfernen – Zeilenumbrüche und Tabs bleiben, ein Wagenrücklauf wird Umbruch."""
    text = str(text)
    if not FOREIGN_RX.search(text):
        return text
    return FOREIGN_RX.sub("", text.replace("\r\n", "\n").replace("\r", "\n"))


def clean(value):
    """safe() für alles, was in einem Ereignis steckt: Texte, Listen, verschachtelte Angaben."""
    if isinstance(value, str):
        return safe(value)
    if isinstance(value, dict):
        return {key: clean(item) for key, item in value.items()}
    if isinstance(value, list):
        return [clean(item) for item in value]
    return value


def char_width(ch: str) -> int:
    if unicodedata.combining(ch) or ch in "​‌‍️":
        return 0
    return 2 if unicodedata.east_asian_width(ch) in "WF" else 1


def width(text: str) -> int:
    """Sichtbare Breite in Terminalspalten – ohne Farbcodes, breite Zeichen doppelt."""
    return sum(char_width(ch) for ch in strip(text))


def take(text: str, room: int) -> str:
    """So viel vom Anfang, wie in room Spalten passt (ohne Farbcodes im Text)."""
    used = 0
    for i, ch in enumerate(text):
        w = char_width(ch)
        if used + w > room:
            return text[:i]
        used += w
    return text


def clip(text, limit: int) -> str:
    """Eine Zeile, höchstens limit Spalten, mit … am Ende, wenn gekürzt."""
    text = " ".join(str(text or "").split())
    if width(text) <= limit:
        return text
    return take(text, max(1, limit - 1)).rstrip() + "…"


def cut(text: str, limit: int) -> str:
    """Wie clip, aber Leerzeichen bleiben stehen – für Code, bei dem der Einzug zählt."""
    text = str(text).replace("\t", "    ")
    if width(text) <= limit:
        return text
    return take(text, max(1, limit - 1)) + "…"


def columns(default: int = 100) -> int:
    try:
        cols = shutil.get_terminal_size((default, 30)).columns
    except (OSError, ValueError):
        cols = default
    return max(30, min(cols, 400))


def rows(default: int = 30) -> int:
    """Wie viele Zeilen das Fenster hoch ist – in einem flachen Fenster bleibt weniger stehen."""
    try:
        return max(5, min(shutil.get_terminal_size((100, default)).lines, 200))
    except (OSError, ValueError):
        return default


# ---------------------------------------------------------------------------- Fähigkeiten des Fensters

def color_enabled(stream=None) -> bool:
    if os.environ.get("NO_COLOR"):
        return False
    if os.environ.get("FORCE_COLOR"):
        return True
    try:
        return bool((stream or sys.stdout).isatty())
    except (AttributeError, ValueError):
        return False


def _console_window_class() -> str:
    """Fensterklasse der Konsole: „PseudoConsoleWindow“ heißt Windows Terminal, VS Code & Co."""
    try:
        import ctypes
        hwnd = ctypes.windll.kernel32.GetConsoleWindow()
        if not hwnd:
            return ""
        buf = ctypes.create_unicode_buffer(64)
        ctypes.windll.user32.GetClassNameW(hwnd, buf, 64)
        return buf.value
    except (OSError, AttributeError):
        return ""


def unicode_symbols() -> bool:
    """Zeichnet das Fenster Symbole wie ⠋ und ⎿ – oder ist es die alte Konsole mit Consolas?"""
    wanted = os.environ.get("CODER_GLYPHS", "").lower()
    if wanted in ("unicode", "modern"):
        return True
    if wanted in ("basic", "ascii", "legacy"):
        return False
    if os.name != "nt":
        return True
    env = os.environ
    if env.get("WT_SESSION") or env.get("TERM_PROGRAM") or env.get("TERM") or env.get("ConEmuANSI") == "ON":
        return True
    # Auch per Doppelklick in Windows Terminal gestartet fehlt WT_SESSION – die Fensterklasse verrät es trotzdem.
    return _console_window_class() == "PseudoConsoleWindow"


def enable_vt() -> None:
    """ANSI-Farben und Cursorbefehle in der Windows-Konsole einschalten."""
    if os.name != "nt":
        return
    try:
        import ctypes
        from ctypes import wintypes
        kernel32 = ctypes.windll.kernel32
        for handle_id in (-11, -12):  # STD_OUTPUT_HANDLE, STD_ERROR_HANDLE
            handle = kernel32.GetStdHandle(handle_id)
            mode = wintypes.DWORD()
            if kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
                kernel32.SetConsoleMode(handle, mode.value | 0x0004 | 0x0001)  # VIRTUAL_TERMINAL, PROCESSED_OUTPUT
    except (OSError, AttributeError):
        os.system("")  # der alte Weg: schaltet die Verarbeitung ebenfalls ein


def enable_ctrl_c() -> None:
    """Strg+C wieder zulassen. Windows vererbt „Strg+C ignorieren“ vom startenden Prozess – aus manchen IDEs,
    Diensten oder Hintergrundstarts käme es sonst nie an, und nichts ließe sich abbrechen."""
    if os.name != "nt":
        return
    try:
        import ctypes
        ctypes.windll.kernel32.SetConsoleCtrlHandler(None, False)
    except (OSError, AttributeError):
        pass


# ---------------------------------------------------------------------------- Zeichen

UNICODE = {
    "bullet": "●", "result": "⎿", "recall": "✦", "control": "◆", "ok": "✓", "fail": "✗", "redo": "↻",
    "watchdog": "⟳", "sub": "↳", "todo": "○", "doing": "◐", "done": "●", "quote": "▎", "item": "•",
    "rule": "─", "bar": "│", "top": "╭─", "bottom": "╰─", "cross": "┼", "ellipsis": "…", "arrow": "→",
    "prompt": "›", "queue": "↳", "box": "☐", "checked": "☑", "pin": "★", "spinner": "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏",
    "star": "✻", "corner-tr": "╮", "corner-br": "╯", "mode-auto": "⏵⏵", "mode-plan": "⏸", "mode-chat": "◇",
    "mode-yolo": "!!",
}
# Nur Zeichen, die Consolas – die Schrift der alten Windows-Konsole – wirklich hat.
BASIC = {
    **UNICODE,
    "result": "└", "recall": "◊", "control": "♦", "ok": "√", "fail": "×", "redo": "»", "watchdog": "»",
    "sub": "└", "doing": "►", "quote": "│", "queue": "»", "box": "[ ]", "checked": "[x]", "pin": "*",
    "spinner": "·∙•●•∙", "star": "*", "mode-auto": "»", "mode-plan": "■", "mode-chat": "○",
}


def glyphs() -> dict:
    return dict(UNICODE if unicode_symbols() else BASIC)


# ---------------------------------------------------------------------------- Farben

THEME_LABEL = {"dunkel": "Dunkel", "hell": "Hell", "farbenblind": "Farbenblind (dunkel)",
               "farbenblind-hell": "Farbenblind (hell)", "schlicht": "Schlicht"}
THEME_HINT = {
    "dunkel": "für dunklen Grund – Windows Terminal, VS Code, cmd",
    "hell": "für hellen Grund – kräftigere, dunklere Farben",
    "farbenblind": "Blau statt Grün, Orange statt Rot – dunkler Grund",
    "farbenblind-hell": "Blau statt Grün, Rot bleibt dunkel – heller Grund",
    "schlicht": "keine Farben, nur fett und gedimmt",
}
# Was sich je Thema ändert. Alles Übrige kommt aus Styles.CODES (dunkel).
# Hell nutzt die 256-Farben-Palette: deren Werte stehen fest, die 16 Grundfarben legt jedes Terminal anders aus.
THEMES = {
    "dunkel": {},
    "hell": {
        "dim": "38;5;243", "red": "38;5;160", "green": "38;5;28", "yellow": "38;5;130", "blue": "38;5;25",
        "cyan": "38;5;24", "magenta": "38;5;90", "accent": "38;5;25", "code": "38;5;24", "link": "38;5;25;4",
        "error": "38;5;160", "warn": "38;5;130", "ok": "38;5;28", "buddy": "38;5;90",
        "c-string": "38;5;28", "c-number": "38;5;24", "c-keyword": "38;5;25", "c-builtin": "38;5;24",
        "c-function": "38;5;130", "c-tag": "38;5;25", "c-attr": "38;5;130", "c-sub": "38;5;24",
    },
    "farbenblind": {"ok": "94", "green": "94", "error": "38;5;208", "red": "38;5;208", "c-string": "38;5;75"},
    "farbenblind-hell": {
        "dim": "38;5;243", "red": "38;5;160", "green": "38;5;25", "yellow": "38;5;130", "blue": "38;5;25",
        "cyan": "38;5;24", "magenta": "38;5;90", "accent": "38;5;25", "code": "38;5;24", "link": "38;5;25;4",
        "error": "38;5;160", "warn": "38;5;130", "ok": "38;5;25", "buddy": "38;5;90",
        "c-string": "38;5;24", "c-number": "38;5;90", "c-keyword": "38;5;25", "c-builtin": "38;5;24",
        "c-function": "38;5;130", "c-tag": "38;5;25", "c-attr": "38;5;130", "c-sub": "38;5;24",
    },
    "schlicht": {name: "" for name in ("red", "green", "yellow", "blue", "cyan", "magenta", "code", "ok", "buddy",
                                       "c-string", "c-number", "c-builtin", "c-function", "c-tag", "c-attr",
                                       "c-sub")}
    | {"accent": "1", "error": "1", "warn": "1", "link": "4", "c-keyword": "1"},
}


def theme_name(wanted: str | None = None) -> str:
    """Welches Thema gilt: das gewählte – oder bei „auto“ hell, wenn das Terminal hellen Grund meldet (COLORFGBG)."""
    wanted = str(wanted or "auto").lower()
    if wanted == "auto":
        wanted = os.environ.get("CODER_THEME", "auto").lower()
    if wanted in THEMES:
        return wanted
    parts = os.environ.get("COLORFGBG", "").split(";")
    try:
        bg = int(parts[-1])
    except ValueError:
        return "dunkel"
    return "hell" if bg == 7 or 9 <= bg <= 15 else "dunkel"


class Styles:
    """ANSI-Stile, die sich abschalten lassen. Farben sind so gewählt, dass sie auf dunklem Grund (Campbell,
    das Schema von Windows Terminal) mindestens 4,5:1 erreichen – das dunkle Blau und Violett der Konsole nicht.
    Themen (THEMES) tauschen einzelne Farben: hell, farbenblind, schlicht. Aufrufer nennen Bedeutungen („ok“,
    „error“, „c-keyword“), nie Farbnummern – so greift ein Thema überall."""

    CODES = {
        "bold": "1", "dim": "2", "italic": "3", "under": "4", "strike": "9",
        "red": "91", "green": "32", "yellow": "33", "blue": "94", "cyan": "36", "magenta": "95",
        "accent": "94", "code": "36", "link": "94;4", "error": "91", "warn": "33", "ok": "32", "buddy": "95",
        # Syntaxfarben in Codeblöcken
        "c-comment": "2", "c-string": "32", "c-number": "36", "c-keyword": "94", "c-builtin": "36",
        "c-function": "33", "c-tag": "94", "c-attr": "33", "c-heading": "1", "c-sub": "36",
    }

    def __init__(self, enabled: bool | None = None, theme: str | None = None):
        self.enabled = color_enabled() if enabled is None else enabled
        self.theme = "dunkel"
        self.map = dict(self.CODES)
        self.set_theme(theme)

    def set_theme(self, theme: str | None) -> str:
        self.theme = theme_name(theme)
        self.map = {**self.CODES, **THEMES[self.theme]}
        return self.theme

    def codes(self, *names: str) -> str:
        return ";".join(code for code in (self.map.get(n, n) for n in names if n) if code)

    def __call__(self, text, *names: str) -> str:
        text = str(text)
        if not self.enabled or not names or not text:
            return text
        code = self.codes(*names)
        return f"\033[{code}m{text}\033[0m" if code else text

    def raw(self, code: str, text) -> str:
        """Mit fertigem SGR-Code, z. B. aus einer Liste von Stilen."""
        text = str(text)
        return f"\033[{code}m{text}\033[0m" if self.enabled and code and text else text
