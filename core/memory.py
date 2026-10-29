"""Gedächtnis: verknüpfte Markdown-Notizen wie in Obsidian – für dich und für den Agenten.

Jede Notiz ist eine .md-Datei, der Dateiname ist ihr Titel. [[Links]] verbinden Notizen, #tags und das Frontmatter
(tags, aliases, pinned) ordnen sie. Es gibt drei Tresore: „project“ unter <workspace>/.coder/memory, „global“ unter
~/.coder/memory und die schreibgeschützte „library“, die mit Coder kommt (Design- und Arbeitsleitfäden). Die Ordner
lassen sich direkt als Vault in Obsidian öffnen.
"""

import os
import re
from dataclasses import dataclass
from pathlib import Path

from .agents import clip, parse_frontmatter, squash
from .config import APP_DIR, HOME

VAULTS = ("project", "global", "library")
LIBRARY_DIR = APP_DIR / "library"
READ_ONLY = {"library"}
LINK_RX = re.compile(r"\[\[([^\[\]|#\n]+)(#[^\[\]|\n]*)?(?:\|([^\[\]\n]*))?\]\]")
TAG_RX = re.compile(r"(?<![\w/&#])#([^\W\d_][\w/-]*)")
CODE_RX = re.compile(r"```.*?```|`[^`\n]*`", re.S)
FRONTMATTER_BLOCK_RX = re.compile(r"\A\ufeff?---[ \t]*\r?\n.*?\r?\n---[ \t]*(?:\r?\n|\Z)", re.S)
UNSAFE_RX = re.compile(r'[\\/:*?"<>|\x00-\x1f]+')
MAX_NOTES = 2000


@dataclass
class Note:
    title: str
    vault: str
    path: Path
    meta: dict
    body: str
    updated: float

    @property
    def key(self) -> str:
        return f"{self.vault}:{self.title}"

    @property
    def links(self) -> list[str]:
        seen, unique = set(), []
        for match in LINK_RX.finditer(CODE_RX.sub(" ", self.body)):
            target = match.group(1).strip()
            if target.lower() not in seen:  # eindeutig, in der Reihenfolge des ersten Auftretens
                seen.add(target.lower())
                unique.append(target)
        return unique

    @property
    def tags(self) -> list[str]:
        raw = self.meta.get("tags") or []
        if isinstance(raw, str):
            raw = re.split(r"[,\s]+", raw.strip("[]"))
        tags = [str(t).strip().strip("\"'").lstrip("#") for t in raw]
        tags += TAG_RX.findall(CODE_RX.sub(" ", self.body))
        return list(dict.fromkeys(t.lower() for t in tags if t))

    @property
    def aliases(self) -> list[str]:
        raw = self.meta.get("aliases") or self.meta.get("alias") or []
        if isinstance(raw, str):
            raw = raw.strip("[]").split(",")
        return [str(a).strip().strip("\"'") for a in raw if str(a).strip()]

    @property
    def pinned(self) -> bool:
        return str(self.meta.get("pinned", "")).lower() in ("true", "yes", "ja", "1") or "pinned" in self.tags

    def summary(self) -> dict:
        return {"id": self.key, "title": self.title, "vault": self.vault, "tags": self.tags, "links": self.links,
                "pinned": self.pinned, "updated": self.updated, "excerpt": clip(plain(self.body), 160)}


def plain(text: str) -> str:
    """Markdown als Fließtext für Vorschauen: Links zeigen ihren Text, Codeblöcke und Formatzeichen fallen weg."""
    text = re.sub(r"```.*?```", " ", text, flags=re.S)
    text = re.sub(r"`([^`\n]*)`", r"\1", text)  # Inline-Code bleibt lesbar: „mit pytest -q“ statt „mit .“
    text = re.sub(r"(?m)^(\s*[-*+]\s+)\[[ xX]\]\s*", r"\1", text)  # Aufgabenlisten ohne „[ ]“
    text = LINK_RX.sub(lambda m: (m.group(3) or m.group(1)).strip(), text)
    text = re.sub(r"^\s{0,3}#{1,6}\s+", "", text, flags=re.M)
    return squash(re.sub(r"[*_>]+|^\s*[-+]\s+", " ", text, flags=re.M))


# --------------------------------------------------------------------------- Tresore und Notizen

def vault_dir(vault: str, workspace: str | Path | None) -> Path:
    if vault == "global":
        return HOME / "memory"
    if vault == "library":
        return LIBRARY_DIR
    if vault == "project" and workspace:
        return Path(workspace) / ".coder" / "memory"
    raise ValueError("Tresor muss „project“, „global“ oder „library“ sein.")


def writable(vault: str) -> None:
    if vault in READ_ONLY:
        raise ValueError("Die Bibliothek ist schreibgeschützt. Lege eine eigene Notiz an und verlinke die Seite.")


def safe_title(title) -> str:
    cleaned = squash(UNSAFE_RX.sub(" ", str(title or ""))).strip(". ")
    if not cleaned:
        raise ValueError("Die Notiz braucht einen Titel.")
    return cleaned[:120]


def _read(path: Path, vault: str) -> Note | None:
    try:
        raw = path.read_text("utf-8", errors="replace")
        updated = path.stat().st_mtime
    except OSError:
        return None
    meta, body = parse_frontmatter(raw)
    return Note(title=path.stem, vault=vault, path=path, meta=meta, body=body.strip("\r\n"), updated=updated)


def _folders(workspace) -> list[tuple[str, Path]]:
    found = []
    for vault in VAULTS:
        try:
            found.append((vault, vault_dir(vault, workspace)))
        except ValueError:
            continue
    paths = {vault: folder.resolve() for vault, folder in found}
    if "project" in paths and paths["project"] == paths.get("global"):
        found = [(v, f) for v, f in found if v != "project"]  # Workspace = Benutzerordner: derselbe Ordner
    return found


def load(workspace) -> list[Note]:
    """Alle Notizen, Projekt vor global – so gewinnt bei gleichem Titel die Projektnotiz."""
    notes: list[Note] = []
    for vault, folder in _folders(workspace):
        if not folder.is_dir():
            continue
        for root, dirs, files in os.walk(folder):
            dirs[:] = sorted(d for d in dirs if not d.startswith("."))  # .obsidian, .trash
            for name in sorted(files):
                if name.lower().endswith(".md") and len(notes) < MAX_NOTES:
                    note = _read(Path(root) / name, vault)
                    if note:
                        notes.append(note)
    return notes


def _lookup(notes: list[Note]) -> dict[str, Note]:
    table: dict[str, Note] = {}
    for note in reversed(notes):  # rückwärts, damit Projektnotizen am Ende gewinnen
        for name in (note.title, *note.aliases):
            table[name.lower()] = note
    return table


def find(notes: list[Note], title: str, vault: str | None = None) -> Note | None:
    wanted = squash(str(title)).lower()
    for note in notes:
        if (vault is None or note.vault == vault) and (
                note.title.lower() == wanted or wanted in (a.lower() for a in note.aliases)):
            return note
    return None


def backlinks(notes: list[Note], target: Note) -> list[Note]:
    names = {target.title.lower(), *(a.lower() for a in target.aliases)}
    return [n for n in notes if n is not target and any(link.lower() in names for link in n.links)]


# --------------------------------------------------------------------------- Lesen

def overview(workspace) -> dict:
    notes = load(workspace)
    table = _lookup(notes)
    incoming: dict[str, int] = {}
    nodes = [{"id": n.key, "title": n.title, "vault": n.vault, "pinned": n.pinned} for n in notes]
    links, missing = [], {}
    for note in notes:
        for target in note.links:
            hit = table.get(target.lower())
            if hit is note:
                continue
            key = hit.key if hit else f"missing:{target.lower()}"
            if not hit and key not in missing:
                missing[key] = {"id": key, "title": target, "vault": "missing", "pinned": False}
            links.append({"source": note.key, "target": key})
            incoming[key] = incoming.get(key, 0) + 1
    tags: dict[str, int] = {}
    for note in notes:
        for tag in note.tags:
            tags[tag] = tags.get(tag, 0) + 1
    summaries = [{**n.summary(), "backlinks": incoming.get(n.key, 0)} for n in notes]
    summaries.sort(key=lambda s: (not s["pinned"], -s["updated"]))
    return {"notes": summaries, "graph": {"nodes": nodes + list(missing.values()), "links": links},
            "tags": dict(sorted(tags.items(), key=lambda t: -t[1])),
            "folders": {vault: str(folder) for vault, folder in _folders(workspace)}}


def read(title: str, workspace, vault: str | None = None) -> dict:
    notes = load(workspace)
    note = find(notes, title, vault)
    if note is None:
        raise KeyError(title)
    table = _lookup(notes)
    return {**note.summary(), "content": note.body, "path": str(note.path),
            "backlinks": [b.summary() for b in backlinks(notes, note)],
            "resolved": {link: (table[link.lower()].key if link.lower() in table else None) for link in note.links}}


def search(query: str, workspace, limit: int = 8) -> list[dict]:
    words = [w for w in re.findall(r"\w+", query.lower()) if len(w) > 1]
    if not words:
        return []
    ranked = []
    for note in load(workspace):
        title, body, tags = note.title.lower(), note.body.lower(), " ".join(note.tags)
        score = sum(6 * (w in title) + 4 * (w in tags) + min(body.count(w), 5) for w in words)
        if score:
            pos = min((body.find(w) for w in words if w in body), default=0)
            ranked.append((score, note.updated, {**note.summary(), "snippet": clip(plain(note.body[max(0, pos - 80):pos + 240]), 220)}))
    ranked.sort(key=lambda r: (r[0], r[1]), reverse=True)
    return [r[2] for r in ranked[:limit]]


def context(workspace, budget: int = 4000) -> str:
    """Für den System-Prompt: angeheftete Notizen im Wortlaut, von allen anderen nur die Titel."""
    notes = load(workspace)
    if not notes:
        return "The vault is still empty."
    parts, used = [], 0
    for note in (n for n in notes if n.pinned):
        block = clip(f"## {note.title}\n{note.body.strip()}", max(0, budget - used))
        if not block:
            break
        parts.append(block)
        used += len(block)
    others = [n.title for n in notes if not n.pinned and n.vault != "library"]
    library = [n.title for n in notes if n.vault == "library"]
    text = ("Pinned notes:\n" + "\n\n".join(parts) + "\n") if parts else ""
    if others:
        text += f"Other notes ({len(others)}): {clip(', '.join(others), 1500)}\n"
    if library:
        text += f"Library – read-only guides, open with memory_read: {clip(', '.join(library), 700)}"
    return text.strip() or "The vault is still empty."


def references(text: str, workspace, budget: int = 6000) -> str:
    """Inhalt der Notizen, die jemand mit [[Titel]] in einer Nachricht erwähnt."""
    wanted = list(dict.fromkeys(m.group(1).strip() for m in LINK_RX.finditer(text or "")))
    if not wanted:
        return ""
    notes, blocks, used = load(workspace), [], 0
    for title in wanted:
        note = find(notes, title)
        if note and used < budget:
            blocks.append(clip(f"## {note.title}\n{note.body.strip()}", budget - used))
            used += len(blocks[-1])
    return "\n\n".join(blocks)


# --------------------------------------------------------------------------- Schreiben

def write(title: str, content: str, workspace, vault: str = "project", append: bool = False) -> dict:
    writable(vault)
    title = safe_title(title)
    folder = vault_dir(vault, workspace)
    existing = find(load(workspace), title, vault)
    content = str(content or "").strip()
    head, old_body = "", ""
    if existing:
        old_body = existing.body
        block = FRONTMATTER_BLOCK_RX.match(existing.path.read_text("utf-8", errors="replace"))
        head = block.group(0) if block else ""
    own = FRONTMATTER_BLOCK_RX.match(content)
    if own:  # der neue Text bringt eigenes Frontmatter mit
        head, content = own.group(0), content[own.end():].strip()
    body = f"{old_body.rstrip()}\n\n{content}".strip() if append and old_body else content
    path = existing.path if existing else folder / f"{title}.md"
    folder.mkdir(parents=True, exist_ok=True)
    path.write_text(f"{head}{body}\n", encoding="utf-8")
    return {"title": existing.title if existing else title, "vault": vault, "path": str(path),
            "created": existing is None, "old": old_body, "new": body}


def set_pinned(title: str, workspace, vault: str, pinned: bool) -> None:
    writable(vault)
    note = find(load(workspace), title, vault)
    if note is None:
        raise KeyError(title)
    raw = note.path.read_text("utf-8", errors="replace")
    block = FRONTMATTER_BLOCK_RX.match(raw)
    head, rest = (block.group(0), raw[block.end():]) if block else ("---\n---\n", raw)
    head = re.sub(r"(?m)^pinned\s*:.*(?:\r?\n)?", "", head)
    if pinned:
        head = head.replace("---", "---\npinned: true", 1)
    elif re.fullmatch(r"\ufeff?---[ \t]*\r?\n---[ \t]*(?:\r?\n)?", head):
        head = ""  # leeres Frontmatter nicht stehen lassen
    note.path.write_text(head + rest, encoding="utf-8")


def rename(title: str, new_title: str, workspace, vault: str, new_vault: str | None = None) -> str:
    """Benennt um oder verschiebt in den anderen Tresor – und passt alle [[Links]] darauf an, wie Obsidian."""
    writable(vault)
    writable(new_vault or vault)
    notes = load(workspace)
    note = find(notes, title, vault)
    if note is None:
        raise KeyError(title)
    new_title = safe_title(new_title)
    target = vault_dir(new_vault or vault, workspace) / f"{new_title}.md"
    if target.exists() and target.resolve() != note.path.resolve():
        raise ValueError(f"Es gibt schon eine Notiz „{new_title}“.")
    target.parent.mkdir(parents=True, exist_ok=True)
    note.path.replace(target)
    if new_title.lower() != note.title.lower():
        pattern = re.compile(r"\[\[" + re.escape(note.title) + r"(?=[\]|#])", re.I)
        for other in load(workspace):
            raw = other.path.read_text("utf-8", errors="replace")
            changed = pattern.sub(lambda _m: "[[" + new_title, raw)
            if changed != raw:
                other.path.write_text(changed, encoding="utf-8")
    return new_title


def save(data: dict, workspace) -> dict:
    """Speichern aus der Oberfläche: anlegen, ändern, umbenennen, verschieben, anheften – in einem Schritt."""
    vault = str(data.get("vault") or "project")
    title = safe_title(data.get("title"))
    original = data.get("original_title")
    original_vault = str(data.get("original_vault") or vault)
    if original and (safe_title(original).lower() != title.lower() or original_vault != vault):
        title = rename(original, title, workspace, original_vault, vault)
    write(title, data.get("content", ""), workspace, vault)
    if "pinned" in data:
        set_pinned(title, workspace, vault, bool(data["pinned"]))
    return read(title, workspace, vault)


def delete(title: str, workspace, vault: str) -> None:
    writable(vault)
    note = find(load(workspace), title, vault)
    if note:
        note.path.unlink(missing_ok=True)
