"""Bericht zum Ausdrucken: was in einem Chat beauftragt wurde, was Coder getan hat und was sich geändert hat.

Gedacht für eine Abgabe oder ein Gespräch mit einem Prüfer: eine Datei, die man aufmacht und auf A4 druckt –
schwarz auf weiß, ohne Oberfläche drumherum, mit Auftrag, Schritten, Diffs, erzeugten Bildern und einem Feld
für Anmerkungen. Die Datei enthält alles (auch die Bilder) und braucht weder Coder noch Internet.
"""

import base64
import html
import re
import time
from pathlib import Path

from . import vision
from .config import HOME

REPORTS_DIR = HOME / "reports"
MAX_DIFF_LINES = 120  # längere Diffs werden im Druck gekürzt – sonst füllt eine Datei zehn Seiten
MAX_OUTPUT = 600  # Zeichen Werkzeugausgabe je Schritt
SLUG_RX = re.compile(r"[^a-z0-9]+")
NAME_RX = re.compile(r"^[0-9a-zA-Z._-]{1,120}\.html$")  # was der Server aus dem Berichtsordner ausliefern darf
TOOL_LABEL = {
    "read_file": "Datei gelesen", "list_dir": "Ordner gelesen", "glob": "Dateien gesucht", "grep": "Code durchsucht",
    "edit_file": "Datei bearbeitet", "write_file": "Datei geschrieben", "generate_image": "Bild erzeugt",
    "run_command": "Befehl ausgeführt", "todo_write": "Aufgabenliste", "view_image": "Bild angesehen",
    "web_search": "Web durchsucht", "web_fetch": "Seite gelesen", "web_research": "Recherchiert",
    "memory_search": "Gedächtnis durchsucht", "memory_read": "Notiz gelesen", "memory_write": "Notiz gespeichert",
    "agent": "An Sub-Agent übergeben", "controller": "Kontrolle", "ask_user": "Rückfrage",
}


# --------------------------------------------------------------------------- Markdown (klein gehalten)

INLINE_CODE_RX = re.compile(r"`([^`]+)`")
BOLD_RX = re.compile(r"\*\*([^*]+)\*\*")
ITALIC_RX = re.compile(r"(?<![*\w])\*([^*\n]+)\*(?!\*)")
LINK_RX = re.compile(r"\[([^\]]+)\]\(([^)\s]+)\)")
HEAD_RX = re.compile(r"^(#{1,4})\s+(.*)$")
BULLET_RX = re.compile(r"^\s*[-*+]\s+(.*)$")
NUMBER_RX = re.compile(r"^\s*\d+[.)]\s+(.*)$")


def _inline(text: str) -> str:
    out = html.escape(text)
    out = INLINE_CODE_RX.sub(lambda m: f"<code>{m.group(1)}</code>", out)
    out = BOLD_RX.sub(lambda m: f"<strong>{m.group(1)}</strong>", out)
    out = ITALIC_RX.sub(lambda m: f"<em>{m.group(1)}</em>", out)
    return LINK_RX.sub(lambda m: f'<a href="{m.group(2)}">{m.group(1)}</a>', out)


def markdown(text: str) -> str:
    """So viel Markdown, wie in Antworten vorkommt: Überschriften, Listen, Codeblöcke, Absätze."""
    lines = str(text or "").replace("\r\n", "\n").split("\n")
    out, buffer, mode = [], [], None

    def flush():
        nonlocal buffer, mode
        if not buffer:
            mode = None
            return
        if mode == "p":
            out.append(f"<p>{'<br>'.join(_inline(b) for b in buffer)}</p>")
        elif mode in ("ul", "ol"):
            items = "".join(f"<li>{_inline(b)}</li>" for b in buffer)
            out.append(f"<{mode}>{items}</{mode}>")
        elif mode == "code":
            out.append(f"<pre class=\"code\">{html.escape(chr(10).join(buffer))}</pre>")
        buffer, mode = [], None

    fence = False
    for line in lines:
        if line.strip().startswith("```"):
            if fence:
                flush()
            else:
                flush()
                mode = "code"
            fence = not fence
            continue
        if fence:
            buffer.append(line)
            continue
        head = HEAD_RX.match(line)
        if head:
            flush()
            level = min(4, len(head.group(1)) + 2)
            out.append(f"<h{level}>{_inline(head.group(2))}</h{level}>")
            continue
        bullet = BULLET_RX.match(line)
        number = NUMBER_RX.match(line)
        if bullet or number:
            want = "ul" if bullet else "ol"
            if mode != want:
                flush()
                mode = want
            buffer.append((bullet or number).group(1))
            continue
        if not line.strip():
            flush()
            continue
        if mode not in (None, "p"):
            flush()
        mode = "p"
        buffer.append(line)
    flush()
    return "".join(out) or ""


# --------------------------------------------------------------------------- Bausteine


def _diff_html(diff: str) -> str:
    rows = []
    lines = str(diff or "").split("\n")
    cut = len(lines) - MAX_DIFF_LINES
    for line in lines[:MAX_DIFF_LINES]:
        kind = ("head" if line.startswith(("+++", "---")) else "hunk" if line.startswith("@@")
                else "add" if line.startswith("+") else "del" if line.startswith("-") else "")
        rows.append(f'<div class="dl {kind}">{html.escape(line) or "&nbsp;"}</div>')
    if cut > 0:
        rows.append(f'<div class="dl hunk">… {cut} weitere Zeilen</div>')
    return f'<div class="diff">{"".join(rows)}</div>'


def _image_tag(image_id: str, alt: str = "") -> str:
    """Bilder wandern als data:-URI in die Datei – gedruckt wird sonst nichts."""
    path = vision.path_of(image_id)
    if not path:
        return ""
    try:
        data = path.read_bytes()
    except OSError:
        return ""
    kind = vision.sniff(data) or "png"
    mime = "image/jpeg" if kind == "jpg" else f"image/{kind}"
    encoded = base64.b64encode(data).decode("ascii")
    return f'<img class="shot" src="data:{mime};base64,{encoded}" alt="{html.escape(alt)}">'


def _step_html(message: dict) -> str:
    name = message.get("_name") or ""
    display = message.get("_display") or {}
    label = TOOL_LABEL.get(name, name)
    ok = message.get("_ok", True)
    summary = html.escape(str(message.get("_summary") or ""))
    mark = "" if ok else '<span class="fail">fehlgeschlagen</span>'
    body = ""
    if display.get("diff"):
        body = _diff_html(display["diff"])
    elif name == "generate_image" and display.get("image_id"):
        body = _image_tag(display["image_id"], display.get("path", ""))
    elif name == "ask_user" and display.get("items"):
        body = _questions_html(display["items"])
    elif name == "run_command":
        text = str(message.get("content") or "").strip()
        if text:
            body = f'<pre class="out">{html.escape(text[:MAX_OUTPUT])}</pre>'
    # Hat ein Sub-Agent mit einem eigenen Modell gearbeitet, gehört das in den Bericht – sonst fehlt im
    # Nachhinein die Erklärung, warum ein Schritt anders ausfiel als der Rest.
    womit = f'<span class="step-model">{html.escape(str(display.get("model")))}</span>' if name == "agent" and display.get("model") else ""
    return (f'<li class="step"><div class="step-head"><span class="step-what">{html.escape(label)}</span>'
            f'<code class="step-target">{summary}</code>{womit}{mark}</div>{body}</li>')


def _questions_html(items: list) -> str:
    """Rückfragen des Agenten mit der Antwort – im Bericht sieht man, was der Nutzer entschieden hat."""
    rows = []
    for item in items:
        answer = item.get("answer") or {}
        if answer.get("skipped") or not answer:
            said = '<span class="skip">übersprungen – der Agent hat selbst entschieden</span>'
        else:
            said = html.escape(", ".join(answer.get("choices") or []))
            if answer.get("text"):
                said += (" · " if said else "") + f"„{html.escape(answer['text'])}“"
        offered = " · ".join(html.escape(o.get("label", "")) for o in item.get("options") or [])
        rows.append(f'<div class="qa"><div class="q">{html.escape(item.get("question", ""))}</div>'
                    + (f'<div class="offered">Angeboten: {offered}</div>' if offered else "")
                    + f'<div class="a">Antwort: {said}</div></div>')
    return "".join(rows)


def _changes_html(changes: dict) -> str:
    rows = []
    for f in changes.get("files") or []:
        state = "neu" if f.get("created") else "gelöscht" if f.get("deleted") else "geändert"
        counts = ("" if f.get("added") is None
                  else f'<td class="num">+{f.get("added", 0)}</td><td class="num">−{f.get("removed", 0)}</td>')
        counts = counts or '<td class="num" colspan="2">binär</td>'
        rows.append(f'<tr><td><code>{html.escape(f.get("path", ""))}</code></td>'
                    f'<td class="state">{state}</td>{counts}</tr>')
    if not rows:
        return ""
    undone = ' <span class="fail">(zurückgenommen)</span>' if changes.get("undone") else ""
    return (f'<div class="changes"><h4>Geänderte Dateien{undone}</h4>'
            f'<table>{"".join(rows)}</table></div>')


def _turns(session: dict) -> list[dict]:
    """Den Verlauf in Aufträge zerlegen: eine Nachricht des Nutzers und alles, was daraufhin passiert ist."""
    turns: list[dict] = []
    for m in session.get("messages") or []:
        role = m.get("role")
        # _summary heißt bei Werkzeugen „Ziel des Schritts“ und nur bei Chat-Nachrichten „Verdichtung“.
        if m.get("_quiet") or (role in ("user", "assistant") and m.get("_summary") is True):
            continue
        if role == "user" and not m.get("_hidden"):
            turns.append({"task": m, "steps": [], "answers": [], "changes": None})
            continue
        if not turns:
            continue
        if role == "tool":
            turns[-1]["steps"].append(m)
        elif role == "assistant" and str(m.get("content") or "").strip():
            turns[-1]["answers"].append(m)
        elif role == "event" and m.get("_changes"):
            turns[-1]["changes"] = m["_changes"]
    return turns


# --------------------------------------------------------------------------- Bericht


def build(session: dict, *, author: str = "", subject: str = "", steps: bool = True, diffs: bool = True) -> str:
    """Der ganze Bericht als eine HTML-Datei."""
    turns = _turns(session)
    title = str(session.get("title") or "Coder-Bericht").strip() or "Coder-Bericht"
    started = session.get("created") or session.get("updated") or time.time()
    parts = []
    for n, turn in enumerate(turns, 1):
        task = turn["task"]
        shown = str(task.get("_text") or task.get("content") or "")
        when = time.strftime("%d.%m.%Y, %H:%M", time.localtime(task.get("_ts") or started))
        images = "".join(_image_tag(i, "Angehängtes Bild") for i in task.get("_images") or [])
        step_list = ""
        if steps and turn["steps"]:
            items = "".join(_step_html(s) for s in turn["steps"] if not (s.get("_display") or {}).get("denied"))
            step_list = (f'<h4>Schritte <span class="count">{len(turn["steps"])}</span></h4>'
                         f'<ol class="steps">{items}</ol>') if items else ""
        # Was das Modell zwischendurch sagt, steht vor den Schritten; die letzte Antwort ist das Ergebnis.
        said = turn["answers"]
        lead = "".join(f'<div class="answer lead">{markdown(a.get("content"))}</div>' for a in said[:-1])
        result = (f'<h4>Ergebnis</h4><div class="answer">{markdown(said[-1].get("content"))}</div>') if said else ""
        changes = _changes_html(turn["changes"]) if turn["changes"] else ""
        parts.append(f"""<section class="turn">
  <h3><span class="n">{n}</span> Auftrag <span class="when">{when}</span></h3>
  <blockquote class="task">{markdown(shown)}{images}</blockquote>
  {lead}
  {step_list}
  {result}
  {changes}
</section>""")

    changed = sorted({f.get("path", "") for t in turns if t["changes"]
                      for f in (t["changes"].get("files") or [])})
    facts = [
        ("Projekt", str(session.get("workspace") or "–")),
        ("Modell", str(session.get("model") or "–")),
        ("Aufträge", str(len(turns))),
        ("Schritte", str(sum(len(t["steps"]) for t in turns))),
        ("Geänderte Dateien", str(len(changed)) if changed else "keine"),
        ("Erstellt", time.strftime("%d.%m.%Y, %H:%M", time.localtime(started))),
        ("Gedruckt", time.strftime("%d.%m.%Y")),
    ]
    if subject:
        facts.insert(0, ("Thema", subject))
    facts.insert(0, ("Bearbeitet von", author or ""))
    blank = '<span class="blank"></span>'  # ohne Namen bleibt eine Linie zum Ausfüllen
    facts_html = "".join(f'<div class="fact"><dt>{html.escape(k)}</dt>'
                         f'<dd>{html.escape(v) if v else blank}</dd></div>' for k, v in facts)
    if not diffs:
        parts = [re.sub(r'<div class="diff">.*?</div>\s*</li>', "</li>", p, flags=re.S) for p in parts]

    return TEMPLATE.format(title=html.escape(title), facts=facts_html, turns="".join(parts) or
                           '<p class="empty">Dieser Chat enthält noch keine Aufträge.</p>')


TEMPLATE = """<!DOCTYPE html>
<html lang="de">
<head>
<meta charset="utf-8">
<title>{title}</title>
<style>
  @page {{ size: A4; margin: 18mm 15mm 16mm; }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0 auto; padding: 24px 20px 64px; max-width: 800px;
    font: 11pt/1.55 -apple-system, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    color: #15181d; background: #fff; -webkit-print-color-adjust: exact; print-color-adjust: exact;
  }}
  code, pre, .diff {{ font-family: "Cascadia Mono", Consolas, "SF Mono", Menlo, monospace; font-size: 9.5pt; }}
  h1 {{ margin: 0 0 4px; font-size: 20pt; letter-spacing: -0.02em; }}
  .sub {{ margin: 0 0 20px; color: #5b6472; font-size: 10pt; }}
  .facts {{ display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 0 28px;
            margin: 0 0 28px; padding: 14px 0; border-top: 1.5px solid #15181d; border-bottom: 1px solid #c9ced6; }}
  .step-model {{ margin-left: 8px; font-family: ui-monospace, Consolas, monospace; font-size: 10.5px; color: #555; }}
  .fact {{ display: flex; justify-content: space-between; gap: 12px; padding: 3px 0;
           border-bottom: 1px dotted #dfe3e9; }}
  .fact dt {{ color: #5b6472; }}
  .fact dd {{ margin: 0; text-align: right; overflow-wrap: anywhere; }}
  .blank {{ display: inline-block; width: 38mm; border-bottom: 1px solid #9aa2ae; }}
  .turn {{ margin: 0 0 26px; padding-top: 4px; break-inside: auto; }}
  .turn h3 {{ display: flex; align-items: baseline; gap: 10px; margin: 0 0 10px;
              font-size: 12pt; border-bottom: 1px solid #c9ced6; padding-bottom: 6px; break-after: avoid; }}
  .turn h3 .n {{ display: inline-block; min-width: 22px; height: 22px; line-height: 22px; text-align: center;
                 background: #15181d; color: #fff; border-radius: 4px; font-size: 9.5pt; }}
  .when {{ margin-left: auto; font-weight: 400; color: #5b6472; font-size: 9.5pt; }}
  blockquote.task {{ margin: 0 0 14px; padding: 10px 14px; background: #f4f6f8;
                     border-left: 3px solid #15181d; border-radius: 0 4px 4px 0; break-inside: avoid; }}
  blockquote.task p {{ margin: 0 0 6px; }} blockquote.task p:last-child {{ margin: 0; }}
  h4 {{ margin: 16px 0 8px; font-size: 10pt; color: #5b6472; text-transform: uppercase;
        letter-spacing: 0.06em; break-after: avoid; }}
  h4 .count {{ color: #9aa2ae; }}
  ol.steps {{ margin: 0; padding: 0; list-style: none; counter-reset: step; }}
  li.step {{ margin: 0 0 8px; padding: 0 0 0 22px; position: relative; break-inside: avoid; }}
  li.step::before {{ counter-increment: step; content: counter(step); position: absolute; left: 0; top: 1px;
                     color: #9aa2ae; font-size: 9pt; }}
  .step-head {{ display: flex; align-items: baseline; gap: 8px; flex-wrap: wrap; }}
  .step-what {{ font-weight: 600; }}
  .step-target {{ color: #40485a; overflow-wrap: anywhere; }}
  .fail {{ color: #b3261e; font-size: 9.5pt; }}
  .qa {{ margin: 6px 0 0; padding: 8px 10px; border: 1px solid #dfe3e9; border-radius: 4px; break-inside: avoid; }}
  .qa .q {{ font-weight: 600; }} .qa .offered {{ color: #5b6472; font-size: 9.5pt; margin-top: 2px; }}
  .qa .a {{ margin-top: 4px; }} .qa .skip {{ color: #5b6472; font-style: italic; }}
  pre.out, pre.code {{ margin: 6px 0 0; padding: 8px 10px; background: #f4f6f8; border: 1px solid #dfe3e9;
                       border-radius: 4px; white-space: pre-wrap; overflow-wrap: anywhere; break-inside: avoid; }}
  .diff {{ margin: 6px 0 0; border: 1px solid #dfe3e9; border-radius: 4px; overflow: hidden; }}
  .dl {{ padding: 0 8px; white-space: pre-wrap; overflow-wrap: anywhere; }}
  .dl.add {{ background: #eaf5ec; }} .dl.del {{ background: #fbecea; }}
  .dl.hunk, .dl.head {{ background: #f4f6f8; color: #5b6472; }}
  .answer {{ margin: 10px 0 0; }}
  .answer.lead {{ margin: 0 0 12px; color: #40485a; }}
  .answer p {{ margin: 0 0 8px; }}
  .answer ul, .answer ol {{ margin: 0 0 8px; padding-left: 20px; }}
  .answer code {{ background: #f4f6f8; padding: 1px 4px; border-radius: 3px; }}
  .changes {{ margin-top: 14px; break-inside: avoid; }}
  .changes table {{ width: 100%; border-collapse: collapse; }}
  .changes td {{ padding: 4px 6px; border-bottom: 1px solid #eceff3; vertical-align: top; }}
  .changes .state {{ color: #5b6472; width: 92px; }}
  .changes .num {{ width: 52px; text-align: right; color: #5b6472; font-variant-numeric: tabular-nums; }}
  img.shot {{ display: block; max-width: 100%; max-height: 90mm; margin: 8px 0 0;
              border: 1px solid #dfe3e9; border-radius: 4px; }}
  .empty {{ color: #5b6472; }}
  .sign {{ margin-top: 34px; padding-top: 14px; border-top: 1.5px solid #15181d; break-inside: avoid; }}
  .sign h4 {{ margin-top: 0; }}
  .lines {{ height: 26mm; background: repeating-linear-gradient(to bottom, transparent 0 8.5mm,
            #c9ced6 8.5mm 8.5mm, transparent 8.5mm 9mm); }}
  .signatures {{ display: flex; gap: 32px; margin-top: 14px; }}
  .signatures div {{ flex: 1; border-top: 1px solid #15181d; padding-top: 5px; color: #5b6472; font-size: 9.5pt; }}
  footer {{ margin-top: 22px; color: #9aa2ae; font-size: 9pt; }}
  @media print {{ body {{ padding: 0; max-width: none; }} a {{ color: inherit; text-decoration: none; }} }}
</style>
</head>
<body>
<h1>{title}</h1>
<p class="sub">Arbeitsbericht · erstellt mit Coder, einem lokalen Coding-Agenten</p>
<dl class="facts">{facts}</dl>
{turns}
<section class="sign">
  <h4>Anmerkungen</h4>
  <div class="lines"></div>
  <div class="signatures"><div>Datum</div><div>Unterschrift Bearbeiter</div><div>Unterschrift Prüfer</div></div>
</section>
<footer>Erzeugt mit Coder · alle Angaben stammen aus dem Chatverlauf</footer>
</body>
</html>
"""


def filename(session: dict) -> str:
    slug = SLUG_RX.sub("-", str(session.get("title") or "bericht").lower()).strip("-")[:48] or "bericht"
    return f"{time.strftime('%Y-%m-%d')}-{slug}.html"


def save(session: dict, path: str | Path | None = None, **kw) -> Path:
    """Schreibt den Bericht und gibt den Pfad zurück. Ohne Angabe landet er unter ~/.coder/reports."""
    target = Path(path) if path else REPORTS_DIR / filename(session)
    if target.is_dir():
        target = target / filename(session)
    if target.suffix.lower() not in (".html", ".htm"):
        target = target.with_name(target.name + ".html")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(build(session, **kw), encoding="utf-8")
    return target
