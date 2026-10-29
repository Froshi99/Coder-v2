"""Die Eingabezeile des Terminalmodus – mit Vervollständigung, Verlauf und mehrzeiligem Text.

Unter Windows liest Coder die Tasten selbst (ReadConsoleInputW), statt die Zeile der Konsole zu überlassen:
- Tab vervollständigt /Befehle, @Agents, [[Notizen]] und Pfade; beim Tippen zeigt eine Liste darunter, was passt
- ↑/↓ blättern im Verlauf (gemerkt unter ~/.coder/cli_history), Strg+←/→ springen wortweise
- Umschalt+Enter macht eine neue Zeile; eingefügter Text mit Zeilenumbrüchen bleibt eine Nachricht
- Esc leert die Zeile, Strg+C auf leerer Zeile beendet (zweimal), Strg+L räumt den Bildschirm auf
Während der Agent arbeitet, liest Poller dieselben Tasten ohne zu warten – so lässt sich weiterschreiben.

Anderswo (macOS, Linux, umgeleitete Eingabe) übernimmt input(), mit readline-Vervollständigung, wenn es da ist.
"""

import json
import os
import sys
import time
from pathlib import Path
from typing import Callable

from . import term as T

Completer = Callable[[str, int], "tuple[int, list[tuple[str, str]]] | None"]

# ---------------------------------------------------------------------------- Windows-Konsole

if os.name == "nt":
    import ctypes
    from ctypes import wintypes

    class _KEY_EVENT(ctypes.Structure):
        _fields_ = [("bKeyDown", wintypes.BOOL), ("wRepeatCount", wintypes.WORD),
                    ("wVirtualKeyCode", wintypes.WORD), ("wVirtualScanCode", wintypes.WORD),
                    ("uChar", wintypes.WCHAR), ("dwControlKeyState", wintypes.DWORD)]

    class _EVENT(ctypes.Union):
        _fields_ = [("KeyEvent", _KEY_EVENT), ("_raw", ctypes.c_byte * 16)]

    class _INPUT_RECORD(ctypes.Structure):
        _fields_ = [("EventType", wintypes.WORD), ("Event", _EVENT)]

KEY_EVENT = 0x0001
PROCESSED_INPUT, LINE_INPUT, ECHO_INPUT, VT_INPUT = 0x0001, 0x0002, 0x0004, 0x0200
SHIFT, LEFT_CTRL, RIGHT_CTRL, LEFT_ALT, RIGHT_ALT = 0x0010, 0x0008, 0x0004, 0x0002, 0x0001
VK_NAMES = {0x0D: "enter", 0x09: "tab", 0x08: "backspace", 0x1B: "esc", 0x25: "left", 0x27: "right", 0x26: "up",
            0x28: "down", 0x24: "home", 0x23: "end", 0x2E: "delete", 0x21: "pageup", 0x22: "pagedown"}
CTRL_CHARS = {"\x03": "ctrl-c", "\x04": "ctrl-d", "\x01": "home", "\x05": "end", "\x15": "ctrl-u", "\x0b": "ctrl-k",
              "\x17": "ctrl-w", "\x0c": "ctrl-l", "\x10": "up", "\x0e": "down", "\x1a": "ctrl-z"}


class Console:
    """Tasten direkt aus der Windows-Konsole – mit Umschalt, Strg und dem Zeichen, das die Taste ergibt."""

    def __init__(self):
        self.k = ctypes.windll.kernel32
        self.handle = self.k.GetStdHandle(-10)  # STD_INPUT_HANDLE
        mode = wintypes.DWORD()
        if not self.k.GetConsoleMode(self.handle, ctypes.byref(mode)):
            raise OSError("Die Eingabe ist keine Konsole.")
        self.normal = mode.value
        self.high = ""  # erste Hälfte eines Ersatzpaars (Emoji)

    def raw(self) -> "_RawMode":
        """Strg+C kommt als Taste an, nichts wird von der Konsole selbst angezeigt."""
        return _RawMode(self)

    def set_mode(self, mode: int) -> None:
        self.k.SetConsoleMode(self.handle, mode)

    def pending(self) -> int:
        count = wintypes.DWORD()
        return count.value if self.k.GetNumberOfConsoleInputEvents(self.handle, ctypes.byref(count)) else 0

    def more_typed(self) -> bool:
        """Liegt schon weiterer Text im Puffer? Dann war das Enter Teil eines eingefügten Textes."""
        records = (_INPUT_RECORD * 32)()
        count = wintypes.DWORD()
        if not self.k.PeekConsoleInputW(self.handle, records, 32, ctypes.byref(count)):
            return False
        for rec in records[:count.value]:
            if rec.EventType == KEY_EVENT and rec.Event.KeyEvent.bKeyDown:
                ev = rec.Event.KeyEvent
                if (ev.uChar and ev.uChar >= " ") or ev.wVirtualKeyCode in (0x0D, 0x09):
                    return True
        return False

    def waiting(self) -> bool:
        """Liegen weitere Tastendrücke im Puffer? Loslassen und bloße Umschalt-/Strg-Tasten zählen nicht."""
        records = (_INPUT_RECORD * 64)()
        count = wintypes.DWORD()
        if not self.k.PeekConsoleInputW(self.handle, records, 64, ctypes.byref(count)):
            return False
        for rec in records[:count.value]:
            if rec.EventType == KEY_EVENT and rec.Event.KeyEvent.bKeyDown:
                ev = rec.Event.KeyEvent
                if ev.uChar or ev.wVirtualKeyCode in VK_NAMES:
                    return True
        return False

    def flush(self) -> None:
        self.k.FlushConsoleInputBuffer(self.handle)
        self.high = ""

    def read(self, block: bool = True) -> list[str]:
        """Die nächsten Tasten. block=False: nur, was schon da ist – kehrt sofort zurück."""
        keys: list[str] = []
        while not keys:
            if not block and not self.pending():
                return keys
            rec = _INPUT_RECORD()
            count = wintypes.DWORD()
            if not self.k.ReadConsoleInputW(self.handle, ctypes.byref(rec), 1, ctypes.byref(count)):
                raise EOFError
            keys = self.decode(rec)
            if not block:
                break
        return keys

    def decode(self, rec) -> list[str]:
        if rec.EventType != KEY_EVENT:
            return []
        ev = rec.Event.KeyEvent
        ch, vk, state = ev.uChar, ev.wVirtualKeyCode, ev.dwControlKeyState
        if not ev.bKeyDown:
            # Alt+Ziffernblock liefert sein Zeichen erst beim Loslassen von Alt
            return [ch] if vk == 0x12 and ch and ch >= " " else []
        repeat = max(1, ev.wRepeatCount)
        ctrl, alt, shift = bool(state & (LEFT_CTRL | RIGHT_CTRL)), bool(state & (LEFT_ALT | RIGHT_ALT)), bool(state & SHIFT)
        name = VK_NAMES.get(vk)
        if name:
            if name == "enter":
                name = "shift-enter" if shift else "ctrl-enter" if ctrl else "enter"
            elif name == "tab":
                name = "shift-tab" if shift else "tab"
            elif name == "backspace":
                name = "ctrl-backspace" if ctrl else "backspace"
            elif ctrl and name in ("left", "right", "delete", "home", "end"):
                name = "ctrl-" + name
            return [name] * repeat
        if not ch:
            return []
        if "\ud800" <= ch <= "\udbff":
            self.high = ch
            return []
        if "\udc00" <= ch <= "\udfff" and self.high:
            ch, self.high = (self.high + ch).encode("utf-16", "surrogatepass").decode("utf-16"), ""
        if ch >= " " and (alt or not ctrl):  # AltGr ist Strg+Alt: das Zeichen zählt (@, €, {, …)
            return [ch] * repeat
        key = CTRL_CHARS.get(ch)
        return [key] * repeat if key else []


class _RawMode:
    def __init__(self, console: Console):
        self.c = console

    def __enter__(self):
        mode = self.c.normal & ~(PROCESSED_INPUT | LINE_INPUT | ECHO_INPUT | VT_INPUT)
        self.c.set_mode(mode)
        return self.c

    def __exit__(self, *exc):
        self.c.set_mode(self.c.normal)
        return False


def open_console() -> "Console | None":
    """Die Konsole, wenn Ein- und Ausgabe wirklich eine sind – sonst None (dann gilt input())."""
    if os.name != "nt" or os.environ.get("CODER_PLAIN_INPUT"):
        return None
    try:
        if not (sys.stdin.isatty() and sys.stdout.isatty()):
            return None
        return Console()
    except (OSError, AttributeError, ValueError):
        return None


# ---------------------------------------------------------------------------- Verlauf

class History:
    def __init__(self, path: Path | None, limit: int = 500):
        self.path, self.limit = path, limit
        self.items: list[str] = []
        if path:
            try:
                for line in path.read_text(encoding="utf-8").splitlines():
                    try:
                        item = json.loads(line)
                    except ValueError:
                        continue
                    if isinstance(item, str) and item.strip():
                        self.items.append(item)
            except OSError:
                pass
        self.items = self.items[-limit:]

    def add(self, text: str) -> None:
        text = text.rstrip()
        if not text.strip():
            return
        if self.items and self.items[-1] == text:
            return
        self.items.append(text)
        self.items = self.items[-self.limit:]
        if self.path:
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                self.path.write_text("".join(json.dumps(i, ensure_ascii=False) + "\n" for i in self.items),
                                     encoding="utf-8")
            except OSError:
                pass


# ---------------------------------------------------------------------------- Zeileneditor

def common_prefix(values: list[str]) -> str:
    if not values:
        return ""
    first, last = min(values), max(values)
    i = 0
    while i < len(first) and i < len(last) and first[i].lower() == last[i].lower():
        i += 1
    return first[:i]


class LineEditor:
    """Liest eine Eingabe mit Vervollständigung und Verlauf – Tasten kommen von keys(), Text geht an write().

    keys: liefert die nächste(n) Taste(n) als Namen („enter“, „up“, „a“ …). more: liegt schon weitere Eingabe
    bereit (eingefügter Text)? Beides kommt normalerweise von Console, in Tests aus einer Liste.
    """

    MENU_ROWS = 6

    def __init__(self, keys: Callable[[], list[str]], write: Callable[[str], None], *,
                 more: Callable[[], bool] = lambda: False, pending: Callable[[], bool] = lambda: False,
                 history: History | None = None, width: Callable[[], int] = T.columns,
                 styles: "T.Styles | None" = None):
        self.keys, self.write, self.more, self.pending = keys, write, more, pending
        self.spill = ""  # bei einer Auswahl getippt, aber nicht als Antwort gemeint
        self.history = history or History(None)
        self.width = width
        self.st = styles or T.Styles(True)
        self.completer: Completer | None = None
        self.buf: list[str] = []
        self.pos = 0
        self.prompt = ""
        self.cursor_row = 0  # Zeile des Cursors im gezeichneten Bereich, von oben gezählt
        self.menu: list[tuple[str, str]] = []
        self.menu_start = 0
        self.menu_index = 0
        self.menu_moved = False  # mit ↑/↓ gewählt: Tab nimmt genau das
        self.menu_auto = False  # die Liste erscheint beim Tippen (Befehle, Agents, Notizen), sonst nur auf Tab
        self.drawn_width = 0
        self.on_shift_tab: Callable[[], "str | None"] | None = None  # Umschalt+Tab ohne Liste: gibt den neuen Prompt
        self.footer: Callable[[int], str] | None = None  # Fußzeile unter der Eingabe – nur solange sie offen ist
        self.bare = False  # beim Abschluss: ohne Linien und Fußzeile zeichnen

    # ------------------------------------------------------------------ Lesen

    def read(self, prompt: str, initial: str = "", completer: Completer | None = None, *,
             footer: Callable[[int], str] | None = None) -> str:
        """Eine Eingabe. footer: gibt es sie, steht die Zeile wie in Claude Code zwischen zwei Linien, darunter
        die Fußzeile (Modus, Aufwand …). Nach Enter bleibt nur „› Text“ stehen."""
        self.prompt, self.completer = prompt, completer
        self.footer = footer
        self.buf, self.pos = list(initial), len(initial)
        self.cursor_row = 0
        self.menu = []
        browse, draft = len(self.history.items), None
        self._suggest(auto_only=True)
        self._draw()
        while True:
            for key in self.keys():
                result = self._key(key)
                if key in ("up", "down") and result == "history":
                    items = self.history.items
                    if not items:
                        continue
                    if draft is None:
                        draft = "".join(self.buf)
                    browse = max(0, browse - 1) if key == "up" else min(len(items), browse + 1)
                    text = items[browse] if browse < len(items) else draft
                    self.buf, self.pos = list(text), len(text)
                    self.menu = []
                elif result == "submit":
                    text = "".join(self.buf)
                    self._finish()
                    self.history.add(text)
                    return text
                elif result == "cancel":
                    self._finish()
                    raise KeyboardInterrupt
                elif result == "eof":
                    self._finish()
                    raise EOFError
                elif result == "edit":
                    browse, draft = len(self.history.items), None
            if self.pending():
                continue  # Eingefügtes erst ganz verarbeiten, dann einmal zeichnen
            self._draw()

    def _key(self, key: str) -> str:
        """Eine Taste anwenden. Rückgabe: submit · cancel · eof · history · edit · move."""
        text = "".join(self.buf)
        if key == "enter":
            if self.menu and self.menu_auto and self._menu_differs():
                self._accept()
                return "edit"
            before = text[:self.pos]
            if before.endswith("\\") and self.pos == len(self.buf):  # „\“ am Zeilenende: weiter in der nächsten
                self.buf[self.pos - 1:self.pos] = ["\n"]
                return "edit"
            if text.count("```") % 2 or self.more():  # offener Codeblock oder eingefügter Text
                return self._insert("\n")
            return "submit"
        if key in ("shift-enter", "ctrl-enter"):
            return self._insert("\n")
        if key == "tab":
            if self.menu:
                if len(self.menu) == 1 or self.menu_moved or not self._menu_differs():
                    self._accept()  # gewählt ist gewählt
                else:
                    self._complete_prefix() or self._move_menu(1)
            else:
                self._suggest(auto_only=False)
                if len(self.menu) == 1:
                    self._accept()
                elif self.menu:
                    self._complete_prefix()
            return "edit"
        if key == "shift-tab":
            if self.menu:
                self._move_menu(-1)
            elif self.on_shift_tab:  # wie in Claude Code: den Modus reihum wechseln
                prompt = self.on_shift_tab()
                if prompt is not None:
                    self.prompt = prompt
            return "move"
        if key in ("up", "down"):
            if self.menu:
                self._move_menu(-1 if key == "up" else 1)
                return "move"
            if "\n" in text and self._line_move(-1 if key == "up" else 1):
                return "move"
            return "history"
        if key == "esc":
            if self.menu:
                self.menu = []
                return "move"
            self.buf, self.pos = [], 0
            return "edit"
        if key == "ctrl-c":
            if self.buf:
                self.buf, self.pos, self.menu = [], 0, []
                return "edit"
            return "cancel"
        if key == "ctrl-d":
            if not self.buf:
                return "eof"
            return self._delete(1)
        if key == "ctrl-l":
            self.write("\033[2J\033[H")
            self.cursor_row = 0
            return "move"
        if key == "left":
            self.pos = max(0, self.pos - 1)
        elif key == "right":
            if self.pos == len(self.buf) and self.menu and self.menu_auto:
                self._accept()
                return "edit"
            self.pos = min(len(self.buf), self.pos + 1)
        elif key == "home":
            self.pos = text.rfind("\n", 0, self.pos) + 1
        elif key == "end":
            end = text.find("\n", self.pos)
            self.pos = len(self.buf) if end < 0 else end
        elif key == "ctrl-left":
            self.pos = self._word_left(text, self.pos)
        elif key == "ctrl-right":
            self.pos = self._word_right(text, self.pos)
        elif key == "backspace":
            return self._delete(-1)
        elif key == "delete":
            return self._delete(1)
        elif key in ("ctrl-backspace", "ctrl-w"):
            start = self._word_left(text, self.pos)
            del self.buf[start:self.pos]
            self.pos = start
            return self._changed()
        elif key == "ctrl-delete":
            end = self._word_right(text, self.pos)
            del self.buf[self.pos:end]
            return self._changed()
        elif key == "ctrl-u":
            start = text.rfind("\n", 0, self.pos) + 1
            del self.buf[start:self.pos]
            self.pos = start
            return self._changed()
        elif key == "ctrl-k":
            end = text.find("\n", self.pos)
            del self.buf[self.pos:len(self.buf) if end < 0 else end]
            return self._changed()
        elif len(key) == 1:  # ein Zeichen – Tastennamen wie „up“ sind länger
            return self._insert(key)
        return "move"

    def _insert(self, text: str) -> str:
        self.buf[self.pos:self.pos] = list(text)
        self.pos += len(text)
        return self._changed()

    def _delete(self, direction: int) -> str:
        if direction < 0 and self.pos > 0:
            del self.buf[self.pos - 1]
            self.pos -= 1
        elif direction > 0 and self.pos < len(self.buf):
            del self.buf[self.pos]
        return self._changed()

    def _changed(self) -> str:
        self._suggest(auto_only=True)
        return "edit"

    @staticmethod
    def _word_left(text: str, pos: int) -> int:
        i = pos
        while i > 0 and text[i - 1].isspace():
            i -= 1
        while i > 0 and not text[i - 1].isspace():
            i -= 1
        return i

    @staticmethod
    def _word_right(text: str, pos: int) -> int:
        i = pos
        while i < len(text) and text[i].isspace():
            i += 1
        while i < len(text) and not text[i].isspace():
            i += 1
        return i

    def _line_move(self, step: int) -> bool:
        """↑/↓ in mehrzeiligem Text: eine Zeile hoch oder runter – am Rand False (dann Verlauf)."""
        text = "".join(self.buf)
        start = text.rfind("\n", 0, self.pos) + 1
        col = self.pos - start
        if step < 0:
            if start == 0:
                return False
            prev = text.rfind("\n", 0, start - 1) + 1
            self.pos = min(prev + col, start - 1)
        else:
            end = text.find("\n", self.pos)
            if end < 0:
                return False
            nxt = text.find("\n", end + 1)
            self.pos = min(end + 1 + col, len(text) if nxt < 0 else nxt)
        return True

    # ------------------------------------------------------------------ Vervollständigen

    def _suggest(self, auto_only: bool) -> None:
        self.menu, self.menu_index = [], 0
        if not self.completer:
            return
        try:
            found = self.completer("".join(self.buf), self.pos)
        except Exception:  # noqa: BLE001 – eine kaputte Quelle darf die Eingabe nicht blockieren
            found = None
        if not found:
            return
        start, items, *rest = found
        auto = bool(rest[0]) if rest else True
        if auto_only and not auto:
            return
        token = "".join(self.buf[start:self.pos])
        if len(items) == 1 and items[0][0] == token and auto_only:
            return  # schon ganz getippt
        self.menu, self.menu_start, self.menu_auto, self.menu_moved = items, start, auto, False
        # Genau getippt gewinnt: bei „/mode“ steht die Auswahl auf /mode, nicht auf /model davor.
        self.menu_index = next((i for i, (value, _) in enumerate(items) if value.strip() == token), 0)

    def _menu_differs(self) -> bool:
        token = "".join(self.buf[self.menu_start:self.pos])
        return self.menu[self.menu_index][0] != token

    def _move_menu(self, step: int) -> None:
        if self.menu:
            self.menu_index = (self.menu_index + step) % len(self.menu)
            self.menu_moved = True

    def _complete_prefix(self) -> bool:
        token = "".join(self.buf[self.menu_start:self.pos])
        prefix = common_prefix([v for v, _ in self.menu])
        if len(prefix) > len(token) and prefix.lower().startswith(token.lower()):
            self.buf[self.menu_start:self.pos] = list(prefix)
            self.pos = self.menu_start + len(prefix)
            self._suggest(auto_only=False)
            return True
        return False

    def _accept(self) -> None:
        value = self.menu[self.menu_index][0]
        after = "".join(self.buf[self.pos:])
        tail = "" if value.endswith(("/", "\\", "]]")) or after.startswith(" ") else " "
        self.buf[self.menu_start:self.pos] = list(value + tail)
        self.pos = self.menu_start + len(value + tail)
        self.menu = []
        self._suggest(auto_only=True)  # nach „/memory “ gleich die Notizen anbieten
        if self.menu and not self.menu_auto:
            self.menu = []

    # ------------------------------------------------------------------ Zeichnen

    def _layout(self, avail: int) -> tuple[list[str], int, int]:
        """Zeilen des Eingabebereichs und die Position des Cursors (Zeile, Spalte)."""
        pw = T.width(self.prompt)
        cont = " " * max(0, pw - 2) + self.st("… ", "dim") if pw >= 2 else ""
        rows, cur, col = [], [self.prompt], pw
        crow, ccol = 0, pw
        for i, ch in enumerate(self.buf + [None]):
            if i == self.pos:
                crow, ccol = len(rows), col
            if ch is None:
                break
            if ch == "\n":
                rows.append("".join(cur))
                cur, col = [cont], T.width(cont)
                continue
            w = T.char_width(ch)
            if col + w > avail:
                rows.append("".join(cur))
                cur, col = [" " * pw], pw
                if i == self.pos:
                    crow, ccol = len(rows), col
            cur.append(ch)
            col += w
        rows.append("".join(cur))
        # Eine volle Zeile endet eine Spalte vor dem Rand – dort hat der Cursor noch Platz.
        return rows, crow, ccol

    def _menu_rows(self, avail: int) -> list[str]:
        if not self.menu:
            return []
        n = len(self.menu)
        first = min(max(0, self.menu_index - self.MENU_ROWS + 1), max(0, n - self.MENU_ROWS))
        shown = self.menu[first:first + self.MENU_ROWS]
        name_w = min(max(T.width(v) for v, _ in shown) + 2, max(12, avail // 2))
        rows = []
        for k, (value, desc) in enumerate(shown, first):
            name = T.clip(value, name_w - 2)
            line = "  " + name + " " * (name_w - T.width(name))
            room = avail - T.width(line)
            text = T.clip(desc, room) if desc and room > 8 else ""
            if k == self.menu_index:
                rows.append(self.st(line, "bold", "accent") + self.st(text, "dim"))
            else:
                rows.append(line + self.st(text, "dim"))
        if n > self.MENU_ROWS:
            rows.append(self.st(f"  {self.menu_index + 1}/{n} · Tab übernimmt · ↑↓ wählt", "dim"))
        else:
            rows.append(self.st("  Tab übernimmt · ↑↓ wählt · Esc schließt", "dim"))
        return rows

    def _frame(self, avail: int, menu: list[str]) -> tuple[list[str], list[str]]:
        """Linie über und unter der Eingabe, darunter die Fußzeile – solange keine Liste offen ist."""
        if not self.footer or self.bare:
            return [], []
        rule = self.st("─" * avail, "dim")
        below = [rule]
        if not menu:
            try:
                below.append(self.footer(avail))
            except Exception:  # noqa: BLE001 – eine kaputte Fußzeile darf die Eingabe nicht blockieren
                pass
        return [rule], below

    def _draw(self) -> None:
        width = self.width()
        avail = max(20, width - 1)
        rows, crow, ccol = self._layout(avail)
        menu = [] if self.bare else self._menu_rows(avail)
        above, below = self._frame(avail, menu)
        rows = above + rows + below
        crow += len(above)
        out = []
        if self.drawn_width and self.drawn_width != width:
            out.append("\r\n")  # Fenster wurde breiter oder schmaler: neu anfangen statt Reste zu zerschneiden
            self.cursor_row = 0
        elif self.cursor_row:
            out.append(f"\033[{self.cursor_row}A")
        out.append("\r\033[J")
        out.append("\r\n".join(rows + menu))
        up = len(rows) + len(menu) - 1 - crow
        if up:
            out.append(f"\033[{up}A")
        out.append(f"\r\033[{ccol}C" if ccol else "\r")
        self.write("".join(out))
        self.cursor_row, self.drawn_width = crow, width

    def _finish(self) -> None:
        """Eingabe fertig: Liste, Linien und Fußzeile weg, Cursor unter den Text."""
        self.menu = []
        self.bare = True
        try:
            self._draw()  # nur noch „› Text“ – darunter ist jetzt alles leer
        finally:
            self.bare = False
        rows, crow, _ = self._layout(max(20, self.width() - 1))
        down = len(rows) - 1 - crow
        self.write((f"\033[{down}B" if down else "") + "\r\n")
        self.cursor_row = 0
        self.drawn_width = 0

    # ------------------------------------------------------------------ Auswahl mit einer Taste

    def choice(self, prompt: str, options: dict[str, str], default: str, *, calm: float = 0.45) -> str:
        """Eine Taste statt einer Zeile: options bildet Buchstaben auf Ergebnisse ab, Enter nimmt default.

        Wer gerade tippt, wenn die Frage erscheint, soll sie nicht aus Versehen beantworten: Eine Antwort zählt erst
        nach einer Pause von calm Sekunden – seit die Frage steht und seit der letzten Taste. Was dazwischen getippt
        wurde, geht nicht verloren, sondern liegt danach in spill. Esc und Strg+C lehnen immer sofort ab.
        """
        self.write(prompt)
        self.spill = ""
        last = time.monotonic()
        while True:
            for key in self.keys():
                now = time.monotonic()
                settled, last = now - last >= calm, now
                pick = None
                if key in ("esc", "ctrl-c"):
                    pick = options.get("esc", options.get("n", default))
                elif not settled:
                    if len(key) == 1:
                        self.spill += key
                    elif key == "backspace":
                        self.spill = self.spill[:-1]
                    continue
                elif key == "enter":
                    pick = default
                elif len(key) == 1 and key.lower() in options:
                    pick = options[key.lower()]
                elif len(key) == 1:
                    self.spill += key  # kein Antwortbuchstabe: da tippt jemand
                if pick is not None:
                    label = next((k for k, v in options.items() if v == pick and len(k) == 1), "")
                    self.write(self.st(label.upper() if key == "enter" else key if len(key) == 1 else "Esc",
                                       "bold") + "\n")
                    return pick

    # ------------------------------------------------------------------ Auswahl aus einer Liste

    def select(self, options: list[tuple[str, str]], *, multiple: bool = False, calm: float = 0.45,
               glyphs: dict | None = None, other: str | None = "Eigene Antwort", keys: dict | None = None,
               hint: str = "") -> tuple[str, object]:
        """Eine Antwort aus einer Liste – wie in Claude Code: „› 1. Ja“, die Beschreibung darunter.

        ↑/↓ und Enter wählen, Ziffern (und Buchstaben aus keys, etwa j/n) direkt. Bei multiple schalten Ziffern und
        Leertaste um, Enter bestätigt. other ist die letzte Zeile „Eigene Antwort …“ – wer einfach lostippt, landet
        dort; ohne other gibt es keine. hint ergänzt die Tastenzeile.

        Rückgabe: ("choices", [Index, …]) · ("text", schon Getipptes) · ("skip", None) für Esc ·
        ("cancel", None) für Strg+C – der Aufrufer hält dann den Agent an.
        Wie bei choice() zählen Tasten erst nach einer Pause von calm Sekunden; was davor kam, liegt in spill.
        """
        g = glyphs or {}
        mark, box, checked = g.get("prompt", ">"), g.get("box", "[ ]"), g.get("checked", "[x]")
        rows = list(options) + ([(other + " …", "")] if other else [])
        own = len(rows) - 1 if other else -1  # Index der eigenen Antwort, -1: gibt es nicht
        keys = {k.lower(): v for k, v in (keys or {}).items()}
        index, picked = 0, set()
        self.spill = ""
        drawn = 0

        def draw(final: bool = False) -> None:
            nonlocal drawn
            out = (f"\033[{drawn}A" if drawn else "") + "\r\033[J"
            if final:
                self.write(out + "\033[?25h")
                drawn = 0
                return
            width = max(24, self.width() - 1)
            lines = []
            for i, (label, desc) in enumerate(rows):
                pointer = mark if i == index else " "
                check = (checked if i in picked else box) + " " if multiple and i != own else ""
                head = f"  {pointer} {check}{i + 1}. "
                name = T.clip(label, max(8, width - T.width(head)))
                if i == index:
                    name = self.st(name, "bold", "accent")
                elif i == own:
                    name = self.st(name, "dim")
                lines.append(self.st(head, "accent") + name if i == index else head + name)
                if desc:
                    pad = " " * T.width(head)  # unter dem Namen, nicht unter der Nummer
                    lines.append(self.st(pad + T.clip(desc, max(8, width - len(pad))), "dim"))
            count = len(rows)
            keys_text = ("Leertaste oder Ziffer schaltet · Enter bestätigt" if multiple
                         else "Enter wählt · ↑↓" + (f" · 1–{min(count, 9)}" if count > 1 else ""))
            if hint:
                keys_text += f" · {hint}"
            keys_text += f" · Esc {'überspringt' if other else 'lehnt ab'}"
            lines.append("    " + self.st(T.clip(keys_text, width - 4), "dim"))  # clip würde den Einzug schlucken
            self.write(out + "\033[?25l" + "\r\n".join(lines) + "\r\n")
            drawn = len(lines)

        def pick(i: int):
            """Ziffer oder Buchstabe: bei einer Wahl sofort fertig, bei multiple umschalten."""
            nonlocal index
            index = i
            if i == own:
                return "text", ""
            if not multiple:
                return "choices", [i]
            picked.symmetric_difference_update({i})
            return None

        draw()
        last = time.monotonic()
        armed = False  # nach der ersten bewussten Taste zählt alles – ↓ und gleich Enter muss gehen
        try:
            while True:
                for key in self.keys():
                    now = time.monotonic()
                    settled, last = armed or now - last >= calm, now
                    if key == "esc":
                        return "skip", None
                    if key == "ctrl-c":
                        return "cancel", None
                    if not settled:
                        if len(key) == 1:
                            self.spill += key
                        elif key == "backspace":
                            self.spill = self.spill[:-1]
                        continue
                    armed = True
                    done = None
                    if key in ("up", "shift-tab"):
                        index = (index - 1) % len(rows)
                    elif key in ("down", "tab"):
                        index = (index + 1) % len(rows)
                    elif key == "home":
                        index = 0
                    elif key == "end":
                        index = len(rows) - 1
                    elif key == "enter":
                        if index == own:
                            return "text", ""
                        return "choices", (sorted(picked or {index}) if multiple else [index])
                    elif key == " " and multiple and index != own:
                        picked.symmetric_difference_update({index})
                    elif len(key) == 1 and key.isdigit() and 0 < int(key) <= min(len(rows), 9):
                        done = pick(int(key) - 1)
                    elif len(key) == 1 and key.lower() in keys and 0 <= keys[key.lower()] < len(rows):
                        done = pick(keys[key.lower()])
                    elif other and len(key) == 1 and key.isprintable() and key != " ":
                        return "text", key  # lostippen heißt: eigene Antwort
                    if done:
                        return done
                draw()
        finally:
            draw(final=True)

# ---------------------------------------------------------------------------- Tippen während der Arbeit

class Poller:
    """Liest Tasten, ohne zu warten – der Agent arbeitet weiter, der Text sammelt sich in buf."""

    def __init__(self, console: Console):
        self.console = console
        self.buf = ""

    def poll(self) -> list[str]:
        """Neue Tasten verarbeiten. Rückgabe: Ereignisse – „submit:<text>“, „esc“, „interrupt“ oder „changed“."""
        events: list[str] = []
        try:
            while self.console.pending():
                for key in self.console.read(block=False):
                    if key == "enter":
                        if self.console.more_typed():
                            self.buf += "\n"
                        elif self.buf.strip():
                            events.append("submit:" + self.buf)
                            self.buf = ""
                    elif key in ("shift-enter", "ctrl-enter"):
                        self.buf += "\n"
                    elif key == "shift-tab":
                        events.append("mode")  # Modus wechseln, auch während der Agent arbeitet
                    elif key == "esc":
                        if self.buf:
                            self.buf = ""
                            events.append("changed")
                        else:
                            events.append("esc")
                    elif key == "ctrl-c":
                        # Kommt Strg+C als Taste statt als Signal (VS Code, manche Terminals), stoppt es trotzdem.
                        events.append("interrupt")
                    elif key == "backspace":
                        self.buf = self.buf[:-1]
                        events.append("changed")
                    elif key in ("ctrl-backspace", "ctrl-w"):
                        self.buf = self.buf[:LineEditor._word_left(self.buf, len(self.buf))]
                        events.append("changed")
                    elif len(key) == 1:
                        self.buf += key
                        events.append("changed")
        except (OSError, EOFError):
            pass
        return events


# ---------------------------------------------------------------------------- ohne eigene Konsole

def readline_setup(completer: Completer | None, history_path: Path | None) -> bool:
    """input() mit Vervollständigung und Verlauf, wo GNU readline da ist (macOS, Linux)."""
    try:
        import readline
    except ImportError:
        return False
    if "libedit" in (getattr(readline, "__doc__", "") or ""):
        readline.parse_and_bind("bind ^I rl_complete")
    else:
        readline.parse_and_bind("tab: complete")
    readline.set_completer_delims(" \t\n")
    if history_path:
        try:
            readline.read_history_file(str(history_path.with_suffix(".readline")))
        except OSError:
            pass
    if completer:
        state: dict = {}

        def complete(text: str, n: int):
            if n == 0:
                line = readline.get_line_buffer()
                found = completer(line, readline.get_endidx())
                state["items"] = [v for v, _ in found[1]] if found else []
            items = state.get("items") or []
            return items[n] if n < len(items) else None

        readline.set_completer(complete)
    return True


def readline_save(history_path: Path | None) -> None:
    try:
        import readline
        if history_path:
            readline.write_history_file(str(history_path.with_suffix(".readline")))
    except (ImportError, OSError):
        pass
