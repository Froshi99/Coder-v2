"""Prepromter: aus einem hingeworfenen Satz einen brauchbaren Auftrag machen – bevor der Agent loslegt.

Kleine Modelle arbeiten deutlich besser, wenn die Aufgabe genau dasteht: was, wo, woran man erkennt, dass es
fertig ist. Der Prepromter schreibt genau das – aus dem, was du getippt hast, und dem, was im Workspace liegt.
Bei Bildaufträgen kommt statt einer Aufgabe ein englischer Bildprompt heraus, so wie ihn Stable Diffusion mag.

Du siehst das Ergebnis immer, bevor es losgeht: in der Oberfläche steht es in der Eingabe, im Terminal fragt
Coder nach. Geschärft wird nur auf Wunsch – von allein ändert Coder nie, was du geschrieben hast.
"""

import re

MAX_INPUT = 4000
MAX_OUTPUT = 1200

TASK_SYSTEM = """You turn a developer's short, casual request into a precise task description for a coding agent.

Rules:
- Keep the user's intent and language. Never invent requirements, file names, libraries or numbers they did not mention.
- Say what should change, where to look, and how to tell it worked (tests, a command, a visible result).
- Mention the obvious constraints of the project when they are in the context below.
- If something is genuinely ambiguous, name the assumption in one short sentence instead of asking.
- 2 to 6 sentences, or a short bullet list. No preamble, no headings, no quotes, no markdown fences.
Answer with the task description and nothing else."""

IMAGE_SYSTEM = """You turn a short request into one prompt for a Stable Diffusion image model.

Rules:
- Always answer in English, even when the request is in another language.
- One dense line: subject, style, composition, colours, lighting, background, level of detail.
- Keep exactly what the user asked for; add only what makes the image concrete, never new subjects.
- For icons, logos and UI assets: flat, centred, plain or transparent background, no text, no letters.
- No camera brands, no artist names, no "masterpiece" filler, no negative prompt, no quotes.
Answer with the prompt and nothing else."""

# Woran ein Bildauftrag zu erkennen ist – auf Deutsch und Englisch.
IMAGE_RX = re.compile(
    r"\b(bild|bilder|bildchen|grafik|illustration|icon|icons|logo|favicon|textur|texture|hintergrundbild|wallpaper|"
    r"poster|banner|artwork|sprite|avatar|thumbnail|og-image|mockup-bild|"
    r"image|picture|render|drawing|painting)\b"
    r"|\b(mal|male|malst|zeichne|zeichnest|skizziere)\s+(mir\s+)?(ein|eine|einen|das|den|die)\b"
    r"|\b(draw|paint|generate|create)\s+(me\s+)?(an?|some)\s+\w*\s*(image|picture|icon|logo|banner)\b", re.I)
# Zeilen, die Modelle gern voranstellen, obwohl sie nicht sollen.
LEAD_RX = re.compile(r"^\s*(hier ist|here('s| is)|sure|gerne|klar|prompt|aufgabe|task|antwort)\b[^\n]{0,40}?:\s*", re.I)
FENCE_RX = re.compile(r"^```[a-z]*\s*\n(.*?)\n?```\s*$", re.S)


def looks_like_image(text: str) -> bool:
    return bool(IMAGE_RX.search(str(text or "")))


def clean(text: str) -> str:
    """Was das Modell drumherum schreibt, gehört nicht in die Eingabe."""
    out = str(text or "").strip()
    fence = FENCE_RX.match(out)
    if fence:
        out = fence.group(1).strip()
    out = LEAD_RX.sub("", out).strip()
    if len(out) > 1 and out[0] in "\"'„«" and out[-1] in "\"'“»":
        out = out[1:-1].strip()
    return out[:MAX_OUTPUT]


def context(workspace) -> str:
    """Ein paar Zeilen über das Projekt – mehr braucht es zum Schärfen nicht."""
    from pathlib import Path

    from . import tools as T
    root = Path(workspace) if workspace else None
    if not root or not root.is_dir():
        return ""
    try:
        names = sorted(p.name + ("" if p.is_file() else "/") for p in list(root.iterdir())[:200]
                       if not (p.name in T.IGNORE_DIRS or (p.name.startswith(".") and p.name not in T.HIDDEN_KEEP)))
    except OSError:
        return ""
    lines = [f"Project folder: {root}", "Top level: " + (", ".join(names[:40]) or "(empty)")]
    for name in ("CODER.md", "AGENTS.md", "CLAUDE.md", "README.md"):
        path = root / name
        if path.is_file():
            try:
                lines.append(f"From {name}:\n{path.read_text('utf-8', errors='replace')[:1200]}")
            except OSError:
                pass
            break
    return "\n".join(lines)


async def sharpen(runtime, text: str, *, workspace=None, kind: str = "auto", model: str | None = None) -> dict:
    """Schärft den Text. Gibt {"text", "kind", "model", "changed"} zurück – bei Zweifeln den Text von vorher."""
    raw = str(text or "").strip()
    if not raw:
        raise ValueError("Ohne Text gibt es nichts zu schärfen.")
    if kind == "auto":
        kind = "image" if looks_like_image(raw) else "task"
    name = model or runtime.cfg.get("model") or ""
    if not name:
        name = await runtime.recommended_model() or ""
    if not name:
        raise ValueError("Kein Modell installiert – ohne Modell lässt sich nichts schärfen.")

    system = IMAGE_SYSTEM if kind == "image" else TASK_SYSTEM
    user = raw[:MAX_INPUT]
    if kind == "task":
        about = context(workspace)
        if about:
            user = f"{user}\n\n[Context about the project – use only what fits]\n{about}"
    messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    # Denkmodus aus, wo es ihn gibt – geschärft wird in einem Zug, nicht nachgedacht.
    think = False if "thinking" in await runtime.model_caps(name) else None
    out = []
    async for chunk in runtime.client.chat_stream(
            name, messages, options={**runtime.chat_options(name), "temperature": 0.4},
            keep_alive=runtime.cfg.get("keep_alive"), think=think):
        out.append((chunk.get("message") or {}).get("content") or "")
    sharpened = clean("".join(out))
    if not sharpened or sharpened.lower() == raw.lower():
        return {"text": raw, "kind": kind, "model": name, "changed": False}
    return {"text": sharpened, "kind": kind, "model": name, "changed": True}
