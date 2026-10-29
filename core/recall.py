"""Erinnern: findet passende Notizen nach Bedeutung und Stichworten.

Die Bedeutung kommt aus einem Embedding-Modell in Ollama (z. B. nomic-embed-text). Notizen werden in Abschnitte
geteilt; deren Vektoren liegen zwischengespeichert unter ~/.coder/cache, berechnet wird nur Neues. Ohne
Embedding-Modell bleibt die Stichwortsuche – nichts geht kaputt.
"""

import asyncio
import base64
import contextlib
import hashlib
import json
import math
import re
import struct
import time
from pathlib import Path

from . import memory
from .agents import clip
from .config import HOME

CACHE_DIR = HOME / "cache"
CHUNK = 900
MAX_CHUNKS = 4000
MAX_CACHED = 30000
BATCH = 48
# So viele noch unbekannte Abschnitte berechnet eine Suche sofort, der Rest folgt im Hintergrund. Rechnet das
# Embedding-Modell auf der CPU, würde ein großer neuer Tresor die erste Nachricht sonst minutenlang aufhalten.
SYNC_CHUNKS = 64
STOPWORDS = set("""
der die das und oder aber nicht mit von für auf ist sind war wie was wer wo wann warum ein eine einen einem einer
den dem des im in am an zu zum zur es er sie wir ihr ich du bei aus nach vor über unter auch noch nur schon dann
doch mal kann soll muss wird werden hat haben mich mir dich dir sich uns euch dass diese dieser dieses bitte
the and or but not with from for on is are was were how what who where when why a an of in at to it he she we
you they this that these those be been has have do does did can could should would will please
""".split())

_indexes: dict[str, "Index"] = {}


def terms(text: str) -> list[str]:
    words = re.findall(r"\w[\w.+#-]*", (text or "").lower())
    return list(dict.fromkeys(w.strip(".-") for w in words if len(w) > 2 and w not in STOPWORDS))


def chunks(note: memory.Note) -> list[str]:
    """Abschnitte an Überschriften und Leerzeilen, jeder mit dem Notiztitel davor."""
    parts, current = [], ""
    for block in re.split(r"\n(?=#{1,6}\s)|\n\s*\n", note.body):
        block = block.strip()
        if not block:
            continue
        while len(block) > CHUNK:  # sehr lange Absätze teilen
            cut = block.rfind(" ", 0, CHUNK)
            cut = cut if cut > CHUNK // 2 else CHUNK
            parts.append(block[:cut])
            block = block[cut:].strip()
        if current and len(current) + len(block) > CHUNK:
            parts.append(current)
            current = block
        else:
            current = f"{current}\n\n{block}".strip()
    if current:
        parts.append(current)
    return [f"{note.title}\n{p}" for p in parts] or [note.title]


class Index:
    def __init__(self, model: str):
        self.model = model
        safe = re.sub(r"[^\w.-]+", "_", model)
        self.path = CACHE_DIR / f"embeddings-{safe}.json"
        self.vectors: dict[str, str] = {}
        self.dirty = False
        try:
            self.vectors = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass

    @staticmethod
    def key(text: str) -> str:
        return hashlib.sha1(text.encode("utf-8")).hexdigest()

    def get(self, text: str) -> list[float] | None:
        raw = self.vectors.get(self.key(text))
        if raw is None:
            return None
        data = base64.b64decode(raw)
        return list(struct.unpack(f"{len(data) // 4}f", data))

    def put(self, text: str, vector: list[float]) -> None:
        self.vectors[self.key(text)] = base64.b64encode(struct.pack(f"{len(vector)}f", *vector)).decode("ascii")
        self.dirty = True

    def save(self) -> None:
        if not self.dirty:
            return
        if len(self.vectors) > MAX_CACHED:  # älteste zuerst raus (dict behält die Einfügereihenfolge)
            self.vectors = dict(list(self.vectors.items())[-MAX_CACHED:])
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.vectors), encoding="utf-8")
        tmp.replace(self.path)
        self.dirty = False


def _prefix(model: str, kind: str) -> str:
    if model.split("/")[-1].startswith("nomic-embed"):  # nomic erwartet Aufgabenpräfixe
        return "search_query: " if kind == "query" else "search_document: "
    return ""


async def embedder(rt):
    """Liefert async embed(texts, kind, budget) oder None, wenn kein Embedding-Modell installiert ist.

    kind: "document" (Notizen, zwischengespeichert), "passage" (Webseiten, nicht gespeichert) oder "query".
    budget: höchstens so viele unbekannte Notiz-Abschnitte sofort berechnen. Die übrigen liefern None und werden im
    Hintergrund nachgeholt.
    """
    if rt is None or not hasattr(rt, "embed_model"):
        return None
    model = await rt.embed_model()
    if not model:
        return None
    index = _indexes.setdefault(model, Index(model))
    placement = getattr(rt, "embed_options", None)

    async def compute(texts: list[str], prefix: str) -> list[list[float]]:
        # Ist die GPU voll, rechnet das Embedding-Modell auf der CPU – statt das Chat-Modell zu verdrängen.
        options = await placement(model) if placement else None
        extra = {"options": options} if options else {}
        vectors: list[list[float]] = []
        for start in range(0, len(texts), BATCH):
            batch = texts[start:start + BATCH]
            found = await rt.client.embed(model, [prefix + t for t in batch], **extra)
            if len(found) != len(batch):
                raise RuntimeError("Embedding-Modell lieferte unvollständige Vektoren")
            vectors += found
        return vectors

    async def embed(texts: list[str], kind: str = "document", budget: int | None = None) -> list[list[float] | None]:
        prefix = _prefix(model, kind)
        cache = kind == "document"
        out: list[list[float] | None] = [index.get(prefix + t) if cache else None for t in texts]
        missing = [i for i, v in enumerate(out) if v is None]
        later: list[int] = []
        if cache and budget is not None and len(missing) > budget:
            missing, later = missing[:budget], missing[budget:]
        if missing:
            for i, vector in zip(missing, await compute([texts[i] for i in missing], prefix)):
                out[i] = vector
                if cache:
                    index.put(prefix + texts[i], vector)
        if cache and index.dirty:
            await asyncio.to_thread(index.save)
        if later:
            _index_later(model, [texts[i] for i in later], embed)
        return out

    return embed


_pending: dict[str, asyncio.Task] = {}


def _index_later(model: str, texts: list[str], embed) -> None:
    """Berechnet die übrigen Notiz-Abschnitte im Hintergrund – höchstens eine solche Aufgabe je Modell."""
    task = _pending.get(model)
    if task and not task.done():
        return

    async def run():
        with contextlib.suppress(Exception):  # nur Vorarbeit: was scheitert, holt die nächste Suche nach
            for start in range(0, len(texts), BATCH):
                await embed(texts[start:start + BATCH], "document")

    _pending[model] = asyncio.create_task(run())


def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    return dot / norm if norm else 0.0


def keyword_score(words: list[str], note: memory.Note, chunk: str) -> float:
    if not words:
        return 0.0
    title, tags, text = note.title.lower(), " ".join(note.tags), chunk.lower()
    total = 0.0
    for w in words:
        if w in title:
            total += 1.0
        elif w in tags:
            total += 0.8
        elif w in text:
            total += min(0.6 + 0.1 * (text.count(w) - 1), 0.9)
    return total / len(words)


async def search(query: str, workspace, rt=None, limit: int = 8) -> list[dict]:
    notes = await asyncio.to_thread(memory.load, workspace)
    words = terms(query)
    if not notes or not query.strip():
        return []
    items = [(note, chunk) for note in notes for chunk in chunks(note)][:MAX_CHUNKS]
    semantic: list[float | None] | None = None
    try:
        embed = await embedder(rt)
        if embed:
            vectors = await embed([c for _, c in items], "document", budget=SYNC_CHUNKS)
            (q,) = await embed([query], "query")
            semantic = [cosine(q, v) if v is not None else None for v in vectors]
    except Exception:  # noqa: BLE001 — ohne Embeddings geht es mit Stichworten weiter
        semantic = None

    best: dict[str, dict] = {}
    for i, (note, chunk) in enumerate(items):
        kw = keyword_score(words, note, chunk)
        sem = semantic[i] if semantic else None  # None: (noch) ohne Vektor – dann zählen nur die Stichworte
        score = 0.7 * sem + 0.3 * kw if sem is not None else kw
        if note.key not in best or score > best[note.key]["score"]:
            best[note.key] = {"note": note, "chunk": chunk, "score": score, "semantic": sem, "keyword": kw}
    ranked = sorted(best.values(), key=lambda h: (h["score"], h["note"].updated), reverse=True)
    ranked = [h for h in ranked if h["keyword"] > 0 or (h["semantic"] or 0) >= 0.5]
    return [{**h["note"].summary(), "snippet": clip(memory.plain(h["chunk"].split("\n", 1)[-1]), 280),
             "score": round(h["score"], 3), "semantic": round(h["semantic"] or 0.0, 3),
             "indexed": h["semantic"] is not None, "keyword": round(h["keyword"], 3)}
            for h in ranked[:limit]]


async def recall(text: str, workspace, rt=None, exclude: set[str] | None = None, limit: int = 3,
                 budget: int = 2400) -> dict | None:
    """Notizen, die zur Nachricht passen – für den Agenten, bevor er loslegt."""
    if len(terms(text)) < 2 and len(text) < 40:
        return None  # „ok“, „weiter“: da gibt es nichts zu erinnern
    hits = await search(text, workspace, rt, limit=8)
    exclude = {e.lower() for e in exclude or ()}
    # Mit Vektor: passt die Bedeutung – oder die Stichworte treffen fast vollständig. Ohne Vektor: nur Stichworte.
    chosen = [h for h in hits if not h["pinned"] and h["title"].lower() not in exclude
              and ((h["semantic"] >= 0.62 or h["keyword"] >= 0.85) if h["indexed"] else h["keyword"] >= 0.6)][:limit]
    if not chosen:
        return None
    notes = {n.key: n for n in await asyncio.to_thread(memory.load, workspace)}
    blocks, used = [], 0
    for hit in chosen:
        note = notes.get(hit["id"])
        if note is None or used >= budget:
            continue
        blocks.append(clip(f"## {note.title}\n{note.body.strip()}", min(1200, budget - used)))
        used += len(blocks[-1])
    return {"titles": [h["title"] for h in chosen], "text": "\n\n".join(blocks)} if blocks else None


def journal(workspace, request: str, result: str, files: list[str]) -> None:
    """Führt die Notiz „Verlauf“: was in diesem Projekt erledigt wurde – so weiß Coder es auch im nächsten Chat."""
    title = "Verlauf"
    note = memory.find(memory.load(workspace), title, "project")
    body = note.body if note else "Was Coder in diesem Projekt erledigt hat – automatisch geführt. #verlauf"
    day = f"## {time.strftime('%Y-%m-%d')}"
    if day not in body:
        body += f"\n\n{day}"
    entry = f"- {time.strftime('%H:%M')} **{clip(memory.plain(request), 140)}**"
    if result:
        entry += f" → {clip(memory.plain(result), 240)}"
    if files:
        entry += " · " + ", ".join(f"`{Path(f).name}`" for f in files[:6])
    body = f"{body}\n{entry}"
    lines = body.splitlines()
    entries = [i for i, line in enumerate(lines) if line.startswith("- ")]
    if len(entries) > 300:  # älteste Einträge und leere Tagesüberschriften entfernen
        drop = set(entries[:len(entries) - 300])
        body = "\n".join(line for i, line in enumerate(lines) if i not in drop)
        body = re.sub(r"(?m)^## \d{4}-\d{2}-\d{2}\n(?=## |\Z)", "", body)
    memory.write(title, body, workspace, "project")
