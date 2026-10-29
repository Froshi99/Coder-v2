"""Markdown fürs Terminal – Stück für Stück, so wie das Modell schreibt.

Wörter erscheinen, sobald sie vollständig sind, und brechen am Fensterrand mit hängendem Einzug um. Fett, Code und
Links sind schon beim ersten Zeichnen richtig – nichts wird hinterher überschrieben, deshalb gibt es auch keine
kaputten Zeilen, wenn eine Antwort breiter als das Fenster ist. Was erst als Ganzes Sinn ergibt – Überschriften,
Tabellen, Codeblöcke –, wartet bis zum Zeilen- bzw. Blockende.

Dazu CallFilter: Werkzeugaufrufe, die ein Modell als Text schreibt (<function=…>, <tool_call>, JSON), gehören nicht
ins Terminal. Er hält sie zurück, bis feststeht, ob es wirklich Aufrufe waren.
"""

import re

from . import term as T

FENCE_RX = re.compile(r"^\s*(`{3,}|~{3,})\s*([\w+#.-]*)")
HEADING_RX = re.compile(r"^\s{0,3}(#{1,6})\s+(.*?)(?:\s+#+)?\s*$")
BULLET_RX = re.compile(r"^(\s*)([-*+•])\s+")
TASK_RX = re.compile(r"^\[([ xX])\]\s+")
NUMBER_RX = re.compile(r"^(\s*)(\d{1,3})([.)])\s+")
QUOTE_RX = re.compile(r"^(\s{0,3})>\s?")
HR_RX = re.compile(r"^\s{0,3}([-*_])(?:\s*\1){2,}\s*$")
MARKS_ONLY_RX = re.compile(r"^\s{0,3}([-*_=`~])\1*\s*$")
TABLE_SEP_RX = re.compile(r"^\s*\|?\s*:?-{2,}:?\s*(?:\|\s*:?-{2,}:?\s*)*\|?\s*$")
LINK_RX = re.compile(r"\[([^\[\]\n]+)\]\(([^()\s]+)\)")
WIKI_RX = re.compile(r"\[\[([^\[\]|\n]+)(?:\|([^\[\]\n]+))?\]\]")
WORD_RX = re.compile(r"[^ \t]+")

# Syntaxfarben für Codeblöcke – nur, wenn Pygments da ist. Bedeutungen statt Farbnummern: das Thema entscheidet.
PYGMENTS_COLORS = (
    ("Comment", "c-comment"), ("Literal.String", "c-string"), ("Literal.Number", "c-number"),
    ("Keyword", "c-keyword"), ("Name.Builtin", "c-builtin"), ("Name.Function", "c-function"),
    ("Name.Class", "c-function"), ("Name.Decorator", "c-function"), ("Name.Tag", "c-tag"),
    ("Name.Attribute", "c-attr"), ("Operator.Word", "c-keyword"), ("Generic.Inserted", "ok"),
    ("Generic.Deleted", "error"), ("Generic.Heading", "c-heading"), ("Generic.Subheading", "c-sub"),
)
DIFF_COLORS = {"+": "ok", "-": "error", "@": "code"}


def _pygments(lang: str):
    """Ein Lexer für die Sprache – oder None, wenn Pygments fehlt oder die Sprache unbekannt ist."""
    if not lang or lang in ("text", "plain", "txt", "output", "console"):
        return None
    try:
        from pygments.lexers import get_lexer_by_name
        from pygments.util import ClassNotFound
    except ImportError:
        return None
    try:
        return get_lexer_by_name(lang, stripnl=False, ensurenl=False)
    except ClassNotFound:
        return None


def fit_columns(natural: list[int], room: int, floor: int = 6) -> list[int]:
    """Spaltenbreiten für eine Tabelle: erst die breiteste Spalte schmaler machen, keine unter floor."""
    widths = list(natural)
    while sum(widths) > room:
        i = max(range(len(widths)), key=lambda k: widths[k])
        if widths[i] <= floor:
            break
        widths[i] -= 1
    return widths


class MarkdownStream:
    """Schreibt Markdown als formatierten Terminaltext, während es hereinkommt: feed() so oft wie nötig, end() am Schluss.

    write: nimmt fertigen Text (mit Farbcodes und Zeilenumbrüchen) entgegen.
    width: liefert die aktuelle Fensterbreite. indent: Einzug der ganzen Antwort.
    plain: nur umbrechen, kein Markdown – für Gedanken und Rohtext. base: Grundstil, z. B. ("dim",).
    """

    def __init__(self, write, *, styles: "T.Styles | None" = None, glyphs: dict | None = None, width=None,
                 indent: int = 2, plain: bool = False, base: tuple = ()):
        self.write = write
        self.st = styles or T.Styles()
        self.g = glyphs or T.glyphs()
        self.width = width or T.columns
        self.indent = " " * indent
        self.plain = plain
        self.base = tuple(base)
        self.buf = ""
        self.mode = "start"  # start · inline
        self.col = 0
        self.cont = ""  # Einzug für umbrochene Folgezeilen, fertig gestylt
        self.cont_w = 0
        self.fresh = True  # direkt nach dem Einzug: kein Leerzeichen davor
        self.space = False  # vor dem nächsten Wort steht ein Leerzeichen
        self.bold = self.italic = self.code = self.strike = False
        self.line_style: tuple = ()
        self.table: list[str] = []
        self.fence: tuple | None = None  # (Zeichen, Länge, Sprache)
        self.lexer = None
        self.pending_blank = False
        self.lines = 0

    # ------------------------------------------------------------------ öffentlich

    def feed(self, text: str) -> None:
        if not text:
            return
        self.buf += T.safe(text.replace("\r\n", "\n").replace("\r", "\n"))  # fremder Text steuert kein Terminal
        self._pump(final=False)

    def end(self) -> None:
        """Alles ausgeben, was noch wartet, und offene Blöcke schließen."""
        self._pump(final=True)
        if self.mode == "inline":
            self._end_line()
        if self.table:
            self._flush_table()
        if self.fence:
            self._close_fence()
        self.pending_blank = False

    @property
    def open_line(self) -> bool:
        """Steht der Cursor gerade mitten in einer Zeile?"""
        return self.mode == "inline" and self.col > 0

    # ------------------------------------------------------------------ Ausgabe

    def _out(self, text: str) -> None:
        if text:
            self.write(text)

    def _avail(self) -> int:
        return max(24, self.width() - 1)  # letzte Spalte frei: manche Konsolen brechen dort sofort um

    def _newline(self) -> None:
        self._out("\n")
        self.col = 0
        self.lines += 1

    def _gap(self) -> None:
        """Eine aufgeschobene Leerzeile – erst schreiben, wenn wirklich noch etwas kommt."""
        if self.pending_blank and self.lines:
            self._newline()
        self.pending_blank = False

    def _begin(self, first: str, cont: str) -> None:
        self._gap()
        self._out(first)
        self.col = T.width(first)
        self.cont, self.cont_w = cont, T.width(cont)
        self.fresh, self.space = True, False

    def _wrap(self) -> None:
        self._newline()
        self._out(self.cont)
        self.col, self.fresh = self.cont_w, True

    def _codes(self, extra: tuple = ()) -> str:
        if not self.st.enabled:
            return ""
        names = [*self.base, *self.line_style, *extra]
        if self.bold:
            names.append("bold")
        if self.italic:
            names.append("italic")
        if self.strike:
            names.append("strike")
        if self.code:
            names.append("code")
        return self.st.codes(*names)

    def _word(self, segments: list) -> None:
        """Ein Wort aus gestylten Stücken – bricht vorher um, wenn es nicht mehr in die Zeile passt."""
        w = sum(T.width(t) for t, _ in segments)
        if not w:
            return  # nur Auszeichnung wie „**“: das Leerzeichen davor bleibt vorgemerkt
        avail = self._avail()
        gap = 1 if self.space and not self.fresh else 0
        if self.col + gap + w > avail and not self.fresh:
            self._wrap()
            gap = 0
        if gap:
            self._out(" ")
            self.col += 1
        for text, code in segments:
            while text:
                room = avail - self.col
                if room <= 0:
                    self._wrap()
                    room = avail - self.col
                piece = T.take(text, room) or text[0]
                self._out(self.st.raw(code, piece) if code else piece)
                self.col += T.width(piece)
                text = text[len(piece):]
        self.fresh = self.space = False

    # ------------------------------------------------------------------ Auszeichnung im Text

    @staticmethod
    def _edge(word: str, i: int, size: int, closing: bool) -> bool:
        """Steht ein Marker am Wortrand? Mitten im Wort (snake_case, 2*3) ist er nur ein Zeichen."""
        if closing:
            return i > 0 and not word[i - 1].isspace() and (i + size == len(word) or not word[i + size].isalnum())
        return ((i == 0 or not word[i - 1].isalnum()) and i + size < len(word)
                and not word[i + size].isspace() and word[i + size] not in "*_")

    def _inline(self, word: str, extra: tuple = ()) -> list:
        """Ein Wort in gestylte Stücke zerlegen: **fett**, *kursiv*, `Code`, ~~durch~~. Der Zustand wirkt über
        Wortgrenzen hinweg – `npm run dev` ist ein Codeabschnitt aus drei Wörtern."""
        if self.plain:
            return [(word, self._codes(extra))]
        segments, buf, i, n = [], "", 0, len(word)

        def flush():
            nonlocal buf
            if buf:
                segments.append((buf, self._codes(extra)))
                buf = ""

        while i < n:
            c = word[i]
            if self.code:
                if c == "`":
                    flush()
                    self.code = False
                else:
                    buf += c
                i += 1
                continue
            if c == "\\" and i + 1 < n and word[i + 1] in "\\`*_[]#~|<>":
                buf += word[i + 1]
                i += 2
                continue
            if c == "`":
                flush()
                self.code = True
                i += 1
                continue
            two = word[i:i + 2]
            if two == "**" or (two == "__" and self._edge(word, i, 2, self.bold)):
                flush()
                self.bold = not self.bold
                i += 2
                continue
            if two == "~~":
                flush()
                self.strike = not self.strike
                i += 2
                continue
            if c in "*_" and self._edge(word, i, 1, self.italic):
                flush()
                self.italic = not self.italic
                i += 1
                continue
            buf += c
            i += 1
        flush()
        return segments

    def _phrase(self, text: str, extra: tuple) -> None:
        for i, w in enumerate(text.split()):
            if i:
                self.space = True
            self._word(self._inline(w, extra))

    def _link(self, text: str, complete: bool) -> str:
        """[[Notiz]] oder [Text](Adresse) am Anfang von text? done · wait (kommt vielleicht noch) · literal."""
        if text.startswith("[["):
            m = WIKI_RX.match(text)
            if m:
                self.buf = self.buf[m.end():]
                self._phrase(m.group(2) or m.group(1), ("link",))
                return "done"
            return "wait" if not complete and "]]" not in text and len(text) < 160 else "literal"
        m = LINK_RX.match(text)
        if m:
            label, url = m.group(1), m.group(2)
            self.buf = self.buf[m.end():]
            self._phrase(label, ("link",))
            if url.rstrip("/") != label.strip().rstrip("/") and not url.startswith("#"):
                self.space = True
                self._word([(f"({url})", self.st.codes("dim") if self.st.enabled else "")])
            return "done"
        if complete or len(text) >= 300:
            return "literal"
        close = text.find("]")
        if close < 0 or close == len(text) - 1:
            return "wait"
        if text[close + 1] == "(" and ")" not in text[close:]:
            return "wait"
        return "literal"

    # ------------------------------------------------------------------ Zeilen

    def _pump(self, final: bool) -> None:
        while True:
            if self.mode == "inline":
                if not self._pump_inline(final):
                    return
                continue
            if not self.buf:
                return
            nl = self.buf.find("\n")
            line = self.buf if nl < 0 else self.buf[:nl]
            complete = nl >= 0 or final
            rest = self.buf[nl + 1:] if nl >= 0 else ""
            if self.fence:
                if not complete:
                    return
                self.buf = rest
                self._fence_line(line)
                continue
            kind = self._classify(line, complete)
            if kind is None:
                return
            if kind == "hold":
                if not complete:
                    return
                self.buf = rest
                self._whole_line(line)
                continue
            self._start_inline()

    def _classify(self, line: str, complete: bool) -> str | None:
        """hold: erst die ganze Zeile ansehen · inline: Wort für Wort · None: noch zu früh, um es zu sagen."""
        s = line.strip()
        if not s:
            return "hold" if complete else None
        if self.plain:
            return "inline"
        if not complete and len(s) < 6:
            return None  # „- “, „1. “, „``“ oder „--“ sind noch nicht eindeutig
        if s.startswith(("```", "~~~", "|")) or HEADING_RX.match(line if complete else line + " x"):
            return "hold"
        if HR_RX.match(line) or (not complete and MARKS_ONLY_RX.match(line)):
            return "hold"
        return "inline"

    def _start_inline(self) -> None:
        if self.table:
            self._flush_table()
        text, pad = self.buf, self.indent
        first, consumed = pad, 0
        if not self.plain:
            m = BULLET_RX.match(text)
            n = NUMBER_RX.match(text)
            q = QUOTE_RX.match(text)
            if m:
                level = min(len(m.group(1).expandtabs(4)) // 2, 4)
                task = TASK_RX.match(text[m.end():])
                if task:
                    mark = (self.st(self.g["checked"], "ok") if task.group(1) in "xX"
                            else self.st(self.g["box"], "dim"))
                    consumed = m.end() + task.end()
                else:
                    mark, consumed = self.st(self.g["item"], "dim"), m.end()
                first = f"{pad}{'  ' * level}{mark} "
            elif n:
                level = min(len(n.group(1).expandtabs(4)) // 3, 4)
                first = f"{pad}{'   ' * level}{self.st(n.group(2) + '.', 'dim')} "
                consumed = n.end()
            elif q:
                first = f"{pad}{self.st(self.g['quote'], 'dim')} "
                consumed = q.end()
                self.buf = text[consumed:]
                self._begin(first, first)
                self.mode = "inline"
                return
            else:
                consumed = len(text) - len(text.lstrip(" \t"))
        self.buf = text[consumed:]
        self._begin(first, " " * T.width(first))
        self.mode = "inline"

    def _pump_inline(self, final: bool) -> bool:
        """Wörter der laufenden Zeile ausgeben. True: die Zeile ist fertig."""
        while True:
            nl = self.buf.find("\n")
            part = self.buf if nl < 0 else self.buf[:nl]
            complete = nl >= 0 or final
            if not part:
                if nl >= 0:
                    self.buf = self.buf[1:]
                    self._end_line()
                    return True
                return False
            lead = len(part) - len(part.lstrip(" \t"))
            if lead:
                self.space = True
                self.buf = self.buf[lead:]
                continue
            literal = False
            if part[0] == "[" and not self.code and not self.plain:
                found = self._link(part, complete)
                if found == "wait":
                    return False
                if found == "done":
                    continue
                literal = True
            m = WORD_RX.match(part)
            if m.end() == len(part) and not complete:
                return False  # das Wort geht vielleicht noch weiter
            word = m.group(0)
            if not literal and not self.code and not self.plain:
                cut = word.find("[", 1)
                if cut > 0:
                    word = word[:cut]  # „siehe[[Notiz]]“: der Link beginnt mitten im Wort
            self.buf = self.buf[len(word):]
            self._word(self._inline(word))

    def _end_line(self) -> None:
        self._newline()
        self.bold = self.italic = self.code = self.strike = False
        self.line_style = ()
        self.mode = "start"

    def _whole_line(self, line: str) -> None:
        s = line.strip()
        if not s:
            if self.table:
                self._flush_table()
            self.pending_blank = True
            return
        if s.startswith("|"):
            self.table.append(line)
            return
        if self.table:
            self._flush_table()
        fence = FENCE_RX.match(line)
        if fence:
            self._open_fence(fence.group(1), fence.group(2))
            return
        heading = HEADING_RX.match(line)
        if heading:
            level, text = len(heading.group(1)), heading.group(2)
            if self.lines:
                self.pending_blank = True  # Luft über jeder Überschrift
            self.line_style = ("bold", "under") if level == 1 else ("bold",)
            self.buf = text + "\n" + self.buf
            self._begin(self.indent, self.indent)
            self.mode = "inline"
            return
        if HR_RX.match(line):
            self._gap()
            n = max(8, min(self._avail() - len(self.indent), 60))
            self._out(self.indent + self.st(self.g["rule"] * n, "dim"))
            self._newline()
            return
        # doch ein gewöhnlicher Absatz, etwa „--- und dann“
        self.buf = line.lstrip() + "\n" + self.buf
        self._begin(self.indent, self.indent)
        self.mode = "inline"

    # ------------------------------------------------------------------ Codeblöcke

    def _open_fence(self, marker: str, lang: str) -> None:
        self._gap()
        self.fence = (marker[0], len(marker), lang.lower())
        self.lexer = _pygments(lang.lower()) if self.st.enabled and lang.lower() != "diff" else None
        label = f" {lang}" if lang else ""
        self._out(self.indent + self.st(self.g["top"] + label, "dim"))
        self._newline()

    def _close_fence(self) -> None:
        self._out(self.indent + self.st(self.g["bottom"], "dim"))
        self._newline()
        self.fence = self.lexer = None

    def _code_segments(self, text: str) -> list:
        lang = self.fence[2] if self.fence else ""
        if not self.st.enabled:
            return [(text, "")]
        if lang == "diff" or (not lang and text[:1] in "+-" and not text.startswith(("+++", "---"))):
            if lang == "diff" or text[:1] in "+-":
                return [(text, self.st.codes(DIFF_COLORS.get(text[:1], "")))]
        if self.lexer is None:
            return [(text, self.st.codes("code"))]
        segments = []
        for token, value in self.lexer.get_tokens(text):
            name = str(token).replace("Token.", "")
            style = next((c for key, c in PYGMENTS_COLORS if name == key or name.startswith(key + ".")), "")
            code = self.st.codes(style) if style else ""
            value = value.replace("\n", "")
            if value:
                segments.append((value, code))
        return segments or [(text, "")]

    def _fence_line(self, line: str) -> None:
        mark, size, _lang = self.fence
        s = line.strip()
        if s and set(s) == {mark} and len(s) >= size:
            self._close_fence()
            return
        gutter = self.indent + self.st(self.g["bar"], "dim") + " "
        start = T.width(gutter)
        avail = self._avail()
        self._out(gutter)
        col = start
        for text, code in self._code_segments(line.expandtabs(4).rstrip()):
            while text:
                room = avail - col
                if room <= 0:
                    self._newline()
                    self._out(gutter)
                    col, room = start, avail - start
                piece = T.take(text, room) or text[0]
                self._out(self.st.raw(code, piece) if code else piece)
                col += T.width(piece)
                text = text[len(piece):]
        self._newline()

    # ------------------------------------------------------------------ Tabellen

    @staticmethod
    def _cells(row: str) -> list[str]:
        row = row.strip()
        row = row[1:] if row.startswith("|") else row
        row = row[:-1] if row.endswith("|") and not row.endswith("\\|") else row
        cells, cur, code = [], "", False
        for i, ch in enumerate(row):
            if ch == "`":
                code = not code
            if ch == "|" and not code and (i == 0 or row[i - 1] != "\\"):
                cells.append(cur.strip())
                cur = ""
            else:
                cur += ch
        cells.append(cur.strip())
        return [c.replace("\\|", "|") for c in cells]

    @staticmethod
    def _aligns(sep: str) -> list[str]:
        out = []
        for cell in MarkdownStream._cells(sep):
            c = cell.strip()
            out.append("center" if c.startswith(":") and c.endswith(":") else "right" if c.endswith(":") else "left")
        return out

    def _cell_words(self, text: str, extra: tuple = ()) -> list:
        text = WIKI_RX.sub(lambda m: m.group(2) or m.group(1), text)
        text = LINK_RX.sub(lambda m: m.group(1), text)
        saved = (self.bold, self.italic, self.code, self.strike, self.line_style)
        self.bold = self.italic = self.code = self.strike = False
        self.line_style = ()
        words = [w for w in (self._inline(word, extra) for word in text.split()) if w]
        self.bold, self.italic, self.code, self.strike, self.line_style = saved
        return words

    @staticmethod
    def _wrap_words(words: list, width: int) -> list:
        """Wörter (Listen gestylter Stücke) auf Zeilen mit höchstens width Spalten verteilen."""
        lines, line, col = [], [], 0
        for word in words:
            w = sum(T.width(t) for t, _ in word)
            if line and col + 1 + w > width:
                lines.append(line)
                line, col = [], 0
            if line:
                line.append((" ", ""))
                col += 1
            for text, code in word:
                while text:
                    room = width - col
                    if room <= 0:
                        lines.append(line)
                        line, col, room = [], 0, width
                    piece = T.take(text, room) or text[0]
                    line.append((piece, code))
                    col += T.width(piece)
                    text = text[len(piece):]
        if line or not lines:
            lines.append(line)
        return lines

    def _flush_table(self) -> None:
        rows, self.table = self.table, []
        if len(rows) < 2 or not TABLE_SEP_RX.match(rows[1]):
            for row in rows:  # keine echte Tabelle: als Absatz
                self.buf = row.strip() + "\n" + self.buf
                self._begin(self.indent, self.indent)
                self.mode = "inline"
                self._pump_inline(final=False)
            return
        header = self._cells(rows[0])
        body = [self._cells(r) for r in rows[2:]]
        ncol = max(len(r) for r in [header, *body])
        header += [""] * (ncol - len(header))
        body = [r + [""] * (ncol - len(r)) for r in body]
        aligns = (self._aligns(rows[1]) + ["left"] * ncol)[:ncol]
        head_words = [self._cell_words(c, ("bold",)) for c in header]
        body_words = [[self._cell_words(c) for c in r] for r in body]

        def natural(words):
            return sum(sum(T.width(t) for t, _ in w) for w in words) + max(0, len(words) - 1)

        widths = [max([natural(head_words[i])] + [natural(r[i]) for r in body_words] + [1]) for i in range(ncol)]
        room = self._avail() - len(self.indent) - 3 * (ncol - 1)
        widths = fit_columns(widths, max(room, ncol * 4))
        self._gap()
        self._table_row(head_words, widths, aligns)
        sep = self.st(self.g["rule"] + self.g["cross"] + self.g["rule"], "dim")
        self._out(self.indent + sep.join(self.st(self.g["rule"] * w, "dim") for w in widths))
        self._newline()
        for r in body_words:
            self._table_row(r, widths, aligns)

    def _table_row(self, cells: list, widths: list, aligns: list) -> None:
        wrapped = [self._wrap_words(words, widths[i]) for i, words in enumerate(cells)]
        bar = self.st(f" {self.g['bar']} ", "dim")
        for li in range(max(len(w) for w in wrapped)):
            parts = []
            for ci, lines in enumerate(wrapped):
                segments = lines[li] if li < len(lines) else []
                text = "".join(self.st.raw(code, t) if code else t for t, code in segments)
                pad = widths[ci] - sum(T.width(t) for t, _ in segments)
                last = ci == len(wrapped) - 1
                if aligns[ci] == "right":
                    parts.append(" " * pad + text)
                elif aligns[ci] == "center":
                    parts.append(" " * (pad // 2) + text + ("" if last else " " * (pad - pad // 2)))
                else:
                    parts.append(text + ("" if last else " " * pad))
            self._out(self.indent + bar.join(parts))
            self._newline()


def render(text: str, *, width: int = 100, styles: "T.Styles | None" = None, glyphs: dict | None = None,
           indent: int = 2, plain: bool = False, base: tuple = ()) -> str:
    """Markdown auf einmal – für fertige Texte wie Notizen oder frühere Antworten."""
    out: list[str] = []
    stream = MarkdownStream(out.append, styles=styles, glyphs=glyphs, width=lambda: width, indent=indent,
                            plain=plain, base=base)
    stream.feed(text)
    stream.end()
    return "".join(out)


# ---------------------------------------------------------------------------- Werkzeugaufrufe als Text

class CallFilter:
    """Hält Text zurück, der wie ein Werkzeugaufruf aussieht, bis der Modellzug vorbei ist.

    feed() gibt zurück, was schon gezeigt werden darf. finish(cleaned) am Ende des Zugs gibt den Rest: Hat der Agent
    Aufrufe im Text gefunden, kommt nur, was ohne sie übrig bleibt (cleaned) – sonst der zurückgehaltene Text.
    Verdächtig sind <function=…>, <tool_call> und Zeilen, die außerhalb eines Codeblocks mit { oder einem
    ```json-Block voller Aufrufe beginnen. Ein gewöhnlicher Codeblock läuft nach seiner ersten Zeile normal weiter.
    """

    MARKERS = ("<tool_call", "<function=", "<function_call", "[TOOL_CALLS]")
    CALL_FENCE_RX = re.compile(r"^\s*```[ \t]*(?:json|tool_call|tool|javascript|js)?[ \t]*$", re.I)
    OPEN_RX = re.compile(r"\[?\s*\{\s*")
    KEY_RX = re.compile(r'"([^"\\\n]*)(")?')
    CALL_KEYS = {"name", "function", "tool", "tool_name", "type", "id", "arguments"}

    @classmethod
    def call_start(cls, text: str) -> bool | None:
        """Beginnt text wie ein Aufruf in JSON – {"name": …} oder [{"name": …}]? None: noch zu früh zu sagen.

        Entschieden wird erst am ersten Schlüssel: Qwen schreibt Aufrufe gern über mehrere Zeilen, und die erste
        besteht dann nur aus „{“ oder „[“.
        """
        s = text.lstrip()
        if not s:
            return None
        if s[0] == "[":
            inner = s[1:].lstrip()
            if not inner:
                return None
            if inner[0] != "{":
                return False
        elif s[0] != "{":
            return False
        rest = s[cls.OPEN_RX.match(s).end():]
        if not rest:
            return None
        if rest[0] != '"':
            return False
        key = cls.KEY_RX.match(rest)
        if not key.group(2):
            return None if len(key.group(1)) < 16 else False
        return key.group(1) in cls.CALL_KEYS

    def __init__(self):
        self.shown = ""  # schon herausgegeben
        self.held = ""  # zurückgehalten, ab der verdächtigen Stelle
        self.holding = False  # sicher ein Aufruf: bis zum Ende des Zugs zurückhalten
        self.fenced = False  # der gezeigte Text steht gerade in einem Codeblock

    def _show(self, text: str, out: list) -> None:
        if not text:
            return
        out.append(text)
        self.shown += text
        for line in text.split("\n"):
            if line.lstrip().startswith("```"):
                self.fenced = not self.fenced

    def _line_start(self, buf: str, pos: int) -> bool:
        if pos:
            return buf[pos - 1] == "\n"
        return not self.shown[self.shown.rfind("\n") + 1:].strip()  # davor nur Einzug derselben Zeile

    def _next(self, buf: str, pos: int) -> tuple[int, str]:
        """Die nächste verdächtige Stelle ab pos: (Index, Art) oder (-1, "")."""
        best, kind = -1, ""
        for marker in self.MARKERS:
            i = buf.find(marker, pos)
            if i >= 0 and (best < 0 or i < best):
                best, kind = i, "marker"
        fenced, i = self.fenced, pos
        while i < len(buf) and (best < 0 or i < best):
            end = buf.find("\n", i)
            line = buf[i:] if end < 0 else buf[i:end]
            if self._line_start(buf, i):
                stripped = line.lstrip()
                if stripped.startswith("```"):
                    if not fenced:
                        return i, "fence"
                    fenced = False
                elif not fenced:
                    if stripped.startswith(("{", "[{")):
                        return i, "json"
                    if end < 0 and stripped in ("`", "``", "["):
                        return i, "partial"  # angefangene Zeile: ``` oder [{ kommt vielleicht noch
            if end < 0:
                break
            i = end + 1
        return best, kind

    def _judge(self, buf: str, i: int, kind: str) -> tuple:
        """(True, _) Aufruf · (False, Ende) kein Aufruf, bis Ende freigeben · (None, _) noch offen."""
        text = buf[i:]
        if kind == "marker":
            return True, None
        if kind == "partial":
            return None, None
        nl = text.find("\n")
        if kind == "json":
            verdict = self.call_start(text)
            if verdict is None:
                return None, None
            return (True, None) if verdict else (False, i + (nl + 1 if nl >= 0 else len(text)))
        # kind == "fence": erst die Sprache, dann der Anfang des Inhalts
        if nl < 0:
            return (False, len(buf)) if len(text) > 40 else (None, None)
        if not self.CALL_FENCE_RX.match(text[:nl]):
            return False, i + nl + 1
        verdict = self.call_start(text[nl + 1:])
        if verdict is None:
            return None, None
        return (True, None) if verdict else (False, i + nl + 1)

    def feed(self, text: str) -> str:
        if self.holding:
            self.held += text
            return ""
        buf, self.held, out, pos = self.held + text, "", [], 0
        while pos < len(buf):
            i, kind = self._next(buf, pos)
            if i < 0:
                # Ein angefangener Marker am Ende („<func“) entscheidet sich erst mit dem nächsten Stück.
                keep = next((k for m in self.MARKERS for k in range(len(m) - 1, 0, -1)
                             if buf.endswith(m[:k]) and len(buf) - k >= pos), 0)
                self._show(buf[pos:len(buf) - keep], out)
                self.held = buf[len(buf) - keep:]
                break
            self._show(buf[pos:i], out)
            verdict, end = self._judge(buf, i, kind)
            if verdict is None or verdict:
                self.held, self.holding = buf[i:], bool(verdict)
                break
            self._show(buf[i:end], out)
            pos = end
        return "".join(out)

    def finish(self, cleaned: str | None = None) -> str:
        """Ende des Modellzugs. cleaned: der Text ohne Aufrufe, wenn der Agent welche gefunden hat."""
        held, self.held, self.holding = self.held, "", False
        out: list[str] = []
        if cleaned is None:
            self._show(held, out)
            return "".join(out)
        shown, clean = self.shown.strip(), cleaned.strip()
        if shown and not clean.startswith(shown):
            return ""  # passt nicht zusammen – lieber nichts doppelt zeigen
        self._show(clean[len(shown):], out)
        return "".join(out)
