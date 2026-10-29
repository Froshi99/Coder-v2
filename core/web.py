"""Internetzugang für den Agenten: Websuche ohne API-Schlüssel, Webseiten als lesbarer Text und Recherche in einem
Schritt – mehrere Suchanfragen, die besten Seiten lesen, die passendsten Abschnitte mit Quellen zurückgeben."""

import asyncio
import base64
import codecs
import math
import re
import time
from html.parser import HTMLParser
from urllib.parse import parse_qs, urljoin, urlparse

import httpx

HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"),
    "Accept-Language": "de-DE,de;q=0.9,en;q=0.8",
}
MAX_BYTES = 5 * 1024 * 1024
# DuckDuckGo zuerst; bremst es (HTTP 202) oder findet nichts, springt Bing ein.
ENGINES = (("duckduckgo", "https://html.duckduckgo.com/html/"), ("duckduckgo", "https://lite.duckduckgo.com/lite/"),
           ("bing", "https://www.bing.com/search"))
SKIP_DOMAINS = ("youtube.com", "youtu.be", "facebook.com", "instagram.com", "tiktok.com", "pinterest.", "x.com",
                "twitter.com", "linkedin.com")
PAGE_TTL = 900
EMBED_POOL = 40  # so viele Abschnitte einer Recherche bewertet das Embedding-Modell höchstens
_pages: dict[str, tuple[float, dict]] = {}

VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}
SKIP = {"script", "style", "noscript", "template", "svg", "canvas", "iframe", "select", "nav", "footer", "dialog"}
# Unsichtbares und Navigation erkennt man oft nur an Attributen – geprüft nur bei Tags, die zuverlässig geschlossen werden.
CONTAINERS = {"div", "section", "aside", "header", "ul", "ol", "span", "form", "details", "table"}
HIDDEN_ROLES = {"navigation", "banner", "contentinfo", "search", "dialog", "menu", "tooltip"}
HEADINGS = {"h1", "h2", "h3", "h4", "h5", "h6"}
BLOCK = {"p", "div", "section", "article", "main", "header", "aside", "ul", "ol", "table", "blockquote",
         "figure", "figcaption", "dl", "dt", "dd", "details", "summary", "form", "fieldset"}


class WebError(Exception):
    pass


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(headers=HEADERS, follow_redirects=True, timeout=httpx.Timeout(20.0, connect=10.0))


def _squash(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[:limit].rsplit(" ", 1)[0] + " …"


# --------------------------------------------------------------------------- Suche

class _Results(HTMLParser):
    """Treffer der HTML- und Lite-Seite von DuckDuckGo: erst der Titel-Link, dann der Kurztext."""

    def __init__(self):
        super().__init__()
        self.items: list[dict] = []
        self._field: str | None = None
        self._depth = 0

    def handle_starttag(self, tag, attrs):
        if self._field:
            if tag not in VOID:
                self._depth += 1
            return
        a = dict(attrs)
        cls = a.get("class") or ""
        if tag == "a" and ("result__a" in cls or "result-link" in cls):
            self.items.append({"title": "", "url": _unwrap(a.get("href") or ""), "snippet": ""})
            self._field = "title"
        elif self.items and ("result__snippet" in cls or "result-snippet" in cls):
            self._field = "snippet"

    def handle_endtag(self, tag):
        if not self._field:
            return
        if self._depth:
            self._depth -= 1
        else:
            self._field = None

    def handle_data(self, data):
        if self._field:
            self.items[-1][self._field] += data


class _BingResults(HTMLParser):
    """Treffer von Bing: <li class="b_algo"> mit Titel-Link in <h2> und Kurztext im ersten <p>."""

    def __init__(self):
        super().__init__()
        self.items: list[dict] = []
        self._li = 0
        self._h2 = False
        self._field: str | None = None
        self._field_tag = ""
        self._field_depth = 0

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "li":
            if self._li:
                self._li += 1
            elif "b_algo" in (a.get("class") or "").split():
                self._li = 1
                self.items.append({"title": "", "url": "", "snippet": ""})
            return
        if not self._li:
            return
        if self._field:
            if tag == self._field_tag:
                self._field_depth += 1
            return
        item = self.items[-1]
        if tag == "h2":
            self._h2 = True
        elif tag == "a" and self._h2 and not item["url"]:
            item["url"] = _bing_unwrap(a.get("href") or "")
            self._field, self._field_tag, self._field_depth = "title", "a", 1
        elif tag == "p" and not item["snippet"]:
            self._field, self._field_tag, self._field_depth = "snippet", "p", 1

    def handle_endtag(self, tag):
        if not self._li:
            return
        if self._field:
            if tag == self._field_tag:
                self._field_depth -= 1
                if not self._field_depth:
                    self._field = None
            return
        if tag == "h2":
            self._h2 = False
        elif tag == "li":
            self._li -= 1

    def handle_data(self, data):
        if self._field:
            self.items[-1][self._field] += data


def _unwrap(href: str) -> str:
    """DuckDuckGo verlinkt über //duckduckgo.com/l/?uddg=<Ziel>."""
    if href.startswith("//"):
        href = "https:" + href
    target = parse_qs(urlparse(href).query).get("uddg")
    return target[0] if target else href


def _bing_unwrap(href: str) -> str:
    """Bing verlinkt über bing.com/ck/a?…&u=a1<Ziel als Base64>."""
    if "bing.com/ck/a" not in href:
        return href
    target = (parse_qs(urlparse(href).query).get("u") or [""])[0]
    if target.startswith("a1"):
        raw = target[2:]
        try:
            return base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4)).decode("utf-8")
        except (ValueError, UnicodeDecodeError):
            pass
    return href


def _clean(items: list[dict]) -> list[dict]:
    results, seen = [], set()
    for item in items:
        link = item["url"]
        host = urlparse(link).netloc.lower()
        if not link.startswith("http") or host.endswith(("duckduckgo.com", "bing.com")) or link in seen:
            continue  # Werbung und interne Links
        seen.add(link)
        results.append({"title": _squash(item["title"]) or link, "url": link, "snippet": _squash(item["snippet"])})
    return results


async def search(query: str, max_results: int = 8) -> list[dict]:
    query = query.strip()
    if not query:
        raise WebError("Leere Suchanfrage.")
    problems, answered = [], False
    async with _client() as client:
        for engine, url in ENGINES:
            try:
                r = await client.get(url, params={"q": query})
            except httpx.HTTPError as e:
                problems.append(f"{engine}: {e.__class__.__name__}")
                continue
            if r.status_code != 200:  # 202 heißt bei DuckDuckGo: bremst gerade
                problems.append(f"{engine}: HTTP {r.status_code}")
                continue
            answered = True
            parser = _BingResults() if engine == "bing" else _Results()
            parser.feed(r.text)
            results = _clean(parser.items)
            if results:
                return results[:max_results]
    if answered:
        return []
    raise WebError(f"Websuche nicht erreichbar ({', '.join(problems)}). "
                   "Internetverbindung prüfen oder web_fetch mit einer bekannten Adresse nutzen.")


# --------------------------------------------------------------------------- Seiten

async def fetch(url: str) -> dict:
    url = url.strip()
    if "://" not in url:
        url = "https://" + url
    if urlparse(url).scheme.lower() not in ("http", "https"):
        raise WebError("Nur http- und https-Adressen werden unterstützt.")
    hit = _pages.get(url)
    if hit and time.monotonic() - hit[0] < PAGE_TTL:
        return hit[1]
    try:
        async with _client() as client, client.stream("GET", url) as r:
            raw = bytearray()
            async for chunk in r.aiter_bytes():
                raw += chunk
                if len(raw) > MAX_BYTES:
                    break
            final, status = str(r.url), r.status_code
            ctype, charset = r.headers.get("content-type", ""), r.charset_encoding
    except (httpx.HTTPError, httpx.InvalidURL) as e:
        raise WebError(f"Seite nicht erreichbar ({e.__class__.__name__}: {e})") from e

    if status >= 400:
        raise WebError(f"HTTP {status} von {final}")
    ctype = ctype.split(";")[0].strip().lower()
    text = bytes(raw).decode(_encoding(charset, raw), errors="replace")
    if "html" in ctype or (not ctype and text.lstrip()[:1] == "<"):
        page = _Page(final)
        page.feed(text)
        page.close()
        result = {"url": final, "status": status, "title": _squash(page.title), "text": page.text()}
    elif ctype.startswith("text/") or ctype.endswith(("json", "xml", "javascript", "yaml", "toml")):
        result = {"url": final, "status": status, "title": "", "text": text.strip()}
    else:
        raise WebError(f"{final} liefert {ctype or 'unbekannte Daten'} statt Text.")
    if len(_pages) >= 64:
        _pages.pop(next(iter(_pages)))
    _pages[url] = (time.monotonic(), result)
    return result


def _encoding(declared: str | None, raw: bytes) -> str:
    meta = re.search(rb"<meta[^>]+charset=[\"']?([\w-]+)", raw[:4096], re.I)
    for name in (declared, meta.group(1).decode("ascii") if meta else None):
        if name:
            try:
                return codecs.lookup(name).name
            except LookupError:
                pass
    return "utf-8"


class _Page(HTMLParser):
    """HTML als knapper Markdown-Text.

    Skripte, Unsichtbares und Navigation fallen weg. Der erste <article> (etwa ein README) oder der Hauptbereich
    hat Vorrang vor der ganzen Seite.
    """

    def __init__(self, base: str):
        super().__init__()
        self.base = base
        self.title = ""
        self._in_title = False
        self._pre = 0
        self._links: list[str | None] = []
        self._skip_tag: str | None = None  # übersprungenes Element; Tiefe zählt gleichnamige Tags darin
        self._skip_depth = 0
        self._all: list[str] = []
        self._article = {"parts": [], "tag": None, "depth": 0, "done": False}
        self._main = {"parts": [], "tag": None, "depth": 0, "done": False}

    def _emit(self, s: str) -> None:
        self._all.append(s)
        for region in (self._article, self._main):
            if region["depth"]:
                region["parts"].append(s)

    def handle_starttag(self, tag, attrs):
        if self._skip_tag:
            if tag == self._skip_tag:
                self._skip_depth += 1
            return
        a = dict(attrs)
        if tag in SKIP or (tag in CONTAINERS and ("hidden" in a or a.get("aria-hidden") == "true"
                                                  or a.get("role") in HIDDEN_ROLES)):
            self._skip_tag, self._skip_depth = tag, 1
            return
        if tag == "title":
            self._in_title = not self.title
            return
        for region, starts in ((self._article, tag == "article"),
                               (self._main, tag == "main" or a.get("role") == "main")):
            if region["depth"]:
                if tag == region["tag"]:
                    region["depth"] += 1
            elif starts and not region["done"]:
                region["tag"], region["depth"] = tag, 1
        if tag in HEADINGS:
            self._emit("\n\n" + "#" * int(tag[1]) + " ")
        elif tag == "li":
            self._emit("\n- ")
        elif tag == "pre":
            self._pre += 1
            self._emit("\n\n```\n")
        elif tag == "code" and not self._pre:
            self._emit("`")
        elif tag in ("br", "tr"):
            self._emit("\n")
        elif tag in ("td", "th"):
            self._emit(" | ")
        elif tag == "a":
            href = (a.get("href") or "").strip()
            link = urljoin(self.base, href) if href and not href.startswith(("#", "javascript:")) else None
            self._links.append(link)
            if link:
                self._emit("[")
        elif tag in BLOCK:
            self._emit("\n\n")

    def handle_endtag(self, tag):
        if self._skip_tag:
            if tag == self._skip_tag:
                self._skip_depth -= 1
                if not self._skip_depth:
                    self._skip_tag = None
            return
        if tag == "title":
            self._in_title = False
            return
        if tag == "pre" and self._pre:
            self._pre -= 1
            self._emit("\n```\n\n")
        elif tag == "code" and not self._pre:
            self._emit("`")
        elif tag == "a" and self._links:
            link = self._links.pop()
            if link:
                self._emit(f"]({link})")
        elif tag in HEADINGS or tag in BLOCK:
            self._emit("\n\n")
        for region in (self._article, self._main):
            if region["depth"] and tag == region["tag"]:
                region["depth"] -= 1
                region["done"] = not region["depth"]

    def handle_data(self, data):
        if self._in_title:
            self.title += data
        elif not self._skip_tag:
            self._emit(data if self._pre else re.sub(r"\s+", " ", data))

    def text(self) -> str:
        for region in (self._article, self._main):
            text = _tidy("".join(region["parts"]))
            if len(text) >= 400:
                return text
        return _tidy("".join(self._all))


def _tidy(text: str) -> str:
    text = re.sub(r"\[\s*\]\([^)]*\)", "", text)  # Links ohne Text: Icons, Bilder
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n (?=\S)", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


# --------------------------------------------------------------------------- Recherche

def passages(text: str, size: int = 800) -> list[str]:
    """Teilt eine Seite in Abschnitte von etwa size Zeichen, an Absätzen und Satzenden."""
    out, current = [], ""
    for block in re.split(r"\n\s*\n", text):
        block = block.strip()
        if not block:
            continue
        pieces = []
        while len(block) > size * 1.5:
            cut = block.rfind(". ", 0, size)
            cut = cut + 1 if cut > size // 3 else size
            pieces.append(block[:cut].strip())
            block = block[cut:].strip()
        pieces.append(block)
        for piece in pieces:
            if current and len(current) + len(piece) > size:
                out.append(current)
                current = piece
            else:
                current = f"{current}\n\n{piece}".strip()
    if current:
        out.append(current)
    return [p for p in out if len(p) >= 60]


def shortlist(parts: list[dict], size: int = EMBED_POOL, per_source: int = 3) -> list[dict]:
    """Welche Abschnitte zusätzlich nach Bedeutung bewertet werden: die besten jeder Quelle, dann die stärksten
    Stichworttreffer. Rechnet das Embedding-Modell auf der CPU, würden 400 Abschnitte die Recherche lange aufhalten."""
    ranked = sorted(parts, key=lambda p: -p["lex"])
    if len(ranked) <= size:
        return ranked
    pool, counts = [], {}
    for p in ranked:
        if counts.get(p["n"], 0) < per_source:
            pool.append(p)
            counts[p["n"]] = counts.get(p["n"], 0) + 1
    taken = {id(p) for p in pool}
    return pool + [p for p in ranked if id(p) not in taken][:max(0, size - len(pool))]


async def research(question: str, queries=(), max_pages: int = 5, embed=None) -> dict:
    """Mehrere Suchanfragen parallel, die besten Seiten lesen und die passendsten Abschnitte auswählen.

    embed: optionale async Funktion (texts, kind) -> Vektoren; damit zählt die Bedeutung, nicht nur Stichworte.
    """
    from .recall import cosine, terms

    question = question.strip()
    if not question:
        raise WebError("Die Frage fehlt.")
    wanted = list(dict.fromkeys(q.strip() for q in [question, *queries] if q and q.strip()))[:4]
    found = await asyncio.gather(*(search(q, 8) for q in wanted), return_exceptions=True)
    if all(isinstance(f, Exception) for f in found):
        raise found[0] if isinstance(found[0], WebError) else WebError(str(found[0]))

    ranking: dict[str, dict] = {}
    for results in found:
        if isinstance(results, Exception):
            continue
        for rank, r in enumerate(results):
            if any(d in urlparse(r["url"]).netloc.lower() for d in SKIP_DOMAINS):
                continue
            entry = ranking.setdefault(r["url"], {**r, "score": 0.0})
            entry["score"] += 1 / (rank + 2)  # oft und weit oben gefunden = wahrscheinlich relevant
    candidates = sorted(ranking.values(), key=lambda r: -r["score"])[:max_pages]
    pages = await asyncio.gather(*(asyncio.wait_for(fetch(c["url"]), 15) for c in candidates), return_exceptions=True)

    sources, failed, parts = [], [], []
    for cand, page in zip(candidates, pages):
        if isinstance(page, BaseException) or not page.get("text"):
            failed.append(cand["url"])
            continue
        n = len(sources) + 1
        sources.append({"n": n, "title": page.get("title") or cand["title"], "url": page["url"]})
        parts += [{"n": n, "i": i, "text": p} for i, p in enumerate(passages(page["text"])[:80])]
    if not parts:  # keine Seite lesbar: wenigstens die Kurztexte der Suche
        sources = [{"n": i, "title": c["title"], "url": c["url"]} for i, c in enumerate(candidates, 1)]
        excerpts = [{"n": i, "text": c["snippet"]} for i, c in enumerate(candidates, 1) if c["snippet"]]
        return {"question": question, "queries": wanted, "sources": sources, "failed": failed, "excerpts": excerpts}

    words = terms(" ".join(wanted))
    for p in parts:
        low = p["text"].lower()
        p["lex"] = sum(1 + math.log(low.count(w)) for w in words if w in low) / max(1, len(words))
    top_lex = max(p["lex"] for p in parts) or 1.0
    semantic: dict[int, float] | None = None
    if embed:
        pool = shortlist(parts)
        try:
            vectors = await embed([p["text"] for p in pool], "passage")
            (q,) = await embed([question], "query")
            semantic = {id(p): cosine(q, v) for p, v in zip(pool, vectors)}
        except Exception:  # noqa: BLE001 — dann eben nur Stichworte
            semantic = None
    for p in parts:
        lex = p["lex"] / top_lex
        if semantic is None:
            p["score"] = lex
        else:  # nicht nach Bedeutung bewertete Abschnitte lagen schon nach Stichworten weit hinten
            p["score"] = 0.6 * semantic[id(p)] + 0.4 * lex if id(p) in semantic else 0.4 * lex

    chosen, per_source = [], {}
    for p in sorted(parts, key=lambda p: -p["score"]):
        if p["score"] <= 0 or len(chosen) >= 12:
            break
        if per_source.get(p["n"], 0) < 3:
            chosen.append(p)
            per_source[p["n"]] = per_source.get(p["n"], 0) + 1
    chosen.sort(key=lambda p: (p["n"], p["i"]))
    return {"question": question, "queries": wanted, "sources": sources, "failed": failed,
            "excerpts": [{"n": p["n"], "text": _clip(p["text"], 900)} for p in chosen]}
