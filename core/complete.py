"""Ergänzen in der Dateiansicht – der graue Vorschlag hinter dem Cursor.

Die Oberfläche schickt, was vor und hinter dem Cursor steht; hier entsteht daraus der Prompt. Modelle, die
„Fill in the Middle“ gelernt haben, bekommen ihn in ihrer eigenen Schreibweise – meldet Ollama für ein Modell
die Fähigkeit `insert`, baut der Server den Prompt sogar selbst. Kennt das Modell nichts davon, fragt Coder
es im Chat und putzt die Antwort: ohne Zaun, ohne Erklärung, ohne Wiederholung dessen, was schon dasteht.

Gerechnet wird nur mit einem Modell, das ohnehin im Speicher liegt – es sei denn, in den Einstellungen steht
ein eigenes Ergänzungsmodell. Sonst würde ein Tastendruck ein 70B-Modell laden, und die Oberfläche stünde.
"""

import asyncio
import re
import time

from .ollama import OllamaError

PREFIX_CHARS = 3000  # so viel vom Text vor dem Cursor geht mit
SUFFIX_CHARS = 1500  # und so viel von dem dahinter
MAX_LINES = 6        # längere Vorschläge trifft man ohnehin nicht
MAX_CHARS = 400
TIMEOUT = 25.0       # danach ist der Vorschlag nichts mehr wert
CACHE_MAX = 64
PS_MAX_AGE = 5.0     # so lange gilt die Auskunft, welche Modelle im Speicher liegen

# Wer „Fill in the Middle“ kann, sagt es nicht immer – diese Familien erkennt Coder am Namen.
# pre/suf/mid sind die Marken des Modells; spm heißt: erst das Hintere, dann das Vordere (Codestral).
FIM_FAMILIES = (
    {"names": ("qwen2.5-coder", "qwen2.5coder", "qwen3-coder", "qwen-coder", "qwen2-coder"),
     "pre": "<|fim_prefix|>", "suf": "<|fim_suffix|>", "mid": "<|fim_middle|>",
     "stop": ("<|endoftext|>", "<|fim_pad|>", "<|file_sep|>", "<|repo_name|>", "<|im_end|>")},
    {"names": ("deepseek-coder", "deepseek-v2", "deepseek-v3"),
     "pre": "<｜fim▁begin｜>", "suf": "<｜fim▁hole｜>", "mid": "<｜fim▁end｜>",
     "stop": ("<|EOT|>", "<｜end▁of▁sentence｜>")},
    {"names": ("codellama", "code-llama"),
     "pre": "<PRE> ", "suf": " <SUF>", "mid": " <MID>", "stop": ("<EOT>", "</s>", "<EOD>")},
    {"names": ("starcoder", "starcoder2", "codegemma", "stable-code", "granite-code", "codeqwen"),
     "pre": "<fim_prefix>", "suf": "<fim_suffix>", "mid": "<fim_middle>",
     "stop": ("<|endoftext|>", "<file_sep>", "<fim_pad>", "<|file_separator|>")},
    {"names": ("codestral", "mistral-code"), "order": "spm",
     "pre": "[PREFIX]", "suf": "[SUFFIX]", "mid": "", "stop": ("</s>", "[PREFIX]", "[SUFFIX]")},
)
# Zäune und Vorreden, die ein Chat-Modell gern mitschickt.
FENCE_RX = re.compile(r"^\s*```[^\n]*\n(.*?)(?:```\s*$|\Z)", re.S)
LEAD_RX = re.compile(r"^(?:hier|here|sure|natürlich|klar)\b[^\n]*:\s*\n", re.I)
CHAT_SYSTEM = (
    "You complete code. The user shows you a file with the cursor marked as {cursor}. "
    "Answer with exactly the code that belongs at the cursor and nothing else: no explanation, no markdown "
    "fence, no repetition of the code before or after the cursor. Keep the file's indentation style. "
    "If nothing is missing, answer with an empty line."
)
CURSOR = "<|cursor|>"

_cache: dict[tuple, dict] = {}
_ps: tuple[float, set[str]] = (0.0, set())


def _short(model: str) -> str:
    return str(model or "").split("/")[-1].lower()


def family(model: str) -> dict | None:
    """Die FIM-Schreibweise des Modells – oder None, wenn Coder sie nicht kennt."""
    name = _short(model)
    for fam in FIM_FAMILIES:
        if any(n in name for n in fam["names"]):
            return fam
    return None


def fim_prompt(fam: dict, prefix: str, suffix: str) -> str:
    """Vorher, nachher und die Marke, ab der das Modell schreibt."""
    if fam.get("order") == "spm":
        return f"{fam['suf']}{suffix}{fam['pre']}{prefix}"
    return f"{fam['pre']}{prefix}{fam['suf']}{suffix}{fam['mid']}"


def cut_prefix(text: str, limit: int = PREFIX_CHARS) -> str:
    """Das Ende des Textes vor dem Cursor – abgeschnitten an einem Zeilenanfang."""
    if len(text) <= limit:
        return text
    rest = text[-limit:]
    nl = rest.find("\n")
    return rest[nl + 1:] if 0 <= nl < 200 else rest


def cut_suffix(text: str, limit: int = SUFFIX_CHARS) -> str:
    """Der Anfang des Textes hinter dem Cursor – abgeschnitten an einem Zeilenende."""
    if len(text) <= limit:
        return text
    rest = text[:limit]
    nl = rest.rfind("\n")
    return rest[:nl + 1] if nl > limit - 200 else rest


def _strip_stops(text: str, stops) -> str:
    for mark in stops:
        cut = text.find(mark)
        if cut >= 0:
            text = text[:cut]
    return text


def _unfence(text: str) -> str:
    """Ein Chat-Modell schickt gern einen Codeblock – der Zaun gehört nicht in die Datei."""
    hit = FENCE_RX.match(text)
    if hit:
        return hit.group(1)
    return LEAD_RX.sub("", text)


def _drop_overlap(text: str, suffix: str) -> str:
    """Was gleich hinter dem Cursor schon steht, muss der Vorschlag nicht noch einmal bringen.

    Sonst stehen die schließende Klammer oder das `return` am Ende doppelt da.
    """
    tail = suffix.lstrip("\n")
    first = tail.split("\n", 1)[0].strip()
    lines = text.split("\n")
    while len(lines) > 1 and first and lines[-1].strip() == first:
        lines.pop()
    text = "\n".join(lines)
    # Auch zeichenweise: „)“ oder „);“ am Ende, das im Suffix direkt folgt. Nur ganze Wörter – sonst fiele bei
    # „items“ vor „self.x“ das s weg, weil das nächste Wort zufällig damit anfängt.
    rest = suffix.lstrip()
    for size in range(min(len(text), 24), 0, -1):
        part = text[-size:]
        if not (part.strip() and rest.startswith(part)):
            continue
        starts_clean = not _word(part[0]) or size == len(text) or not _word(text[-size - 1])
        ends_clean = not _word(part[-1]) or len(rest) == size or not _word(rest[size])
        if starts_clean and ends_clean:
            return text[:-size]
    return text


def _word(ch: str) -> bool:
    return ch.isalnum() or ch == "_"


def trim(text: str, suffix: str = "", multiline: bool = True, stops=()) -> str:
    """Aus der Antwort des Modells wird der Vorschlag: ohne Marken, ohne Zaun, in Maßen."""
    text = _strip_stops(_unfence(_strip_stops(text, stops)), stops)
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace(CURSOR, "")
    if not multiline:
        text = text.split("\n", 1)[0]
    lines = text.split("\n")[:MAX_LINES]
    while lines and not lines[-1].strip():
        lines.pop()
    text = "\n".join(lines)[:MAX_CHARS]
    text = _drop_overlap(text, suffix)
    # Nur Leerzeichen sind kein Vorschlag; ein führender Umbruch schon (neue Zeile darunter).
    return "" if not text.strip() else text


async def in_memory(rt, model: str) -> bool:
    """Liegt das Modell gerade im Speicher? Die Antwort gilt ein paar Sekunden – es wird oft gefragt."""
    global _ps
    stamp, names = _ps
    if time.monotonic() - stamp > PS_MAX_AGE:
        try:
            names = {m["name"] for m in await rt.loaded()}
        except OllamaError:
            names = set()
        _ps = (time.monotonic(), names)
    return model in names


def forget() -> None:
    """Zwischenspeicher leeren – nach einem Modell- oder Serverwechsel."""
    global _ps
    _cache.clear()
    _ps = (0.0, set())


def _options(rt, model: str, multiline: bool) -> dict:
    """Dieselben Optionen wie beim Chat – ein anderes num_ctx würde Ollama zum Neuladen zwingen."""
    opts = dict(rt.plans.get(model, {}).get("options", {}))
    opts["temperature"] = 0.1
    opts["top_p"] = 0.9
    opts["num_predict"] = 160 if multiline else 64
    return opts


def chat_messages(prefix: str, suffix: str, path: str) -> list[dict]:
    """Der Notausgang für Modelle ohne FIM: die Datei mit einer Marke an der Cursorstelle."""
    where = f"File: {path}\n\n" if path else ""
    return [
        {"role": "system", "content": CHAT_SYSTEM.format(cursor=CURSOR)},
        {"role": "user", "content": f"{where}{prefix}{CURSOR}{suffix}"},
    ]


async def _chat(rt, model: str, prefix: str, suffix: str, path: str, options: dict) -> str:
    out = []
    async for chunk in rt.client.chat_stream(model, chat_messages(prefix, suffix, path),
                                             options=options, keep_alive=rt.cfg["keep_alive"]):
        out.append(str((chunk.get("message") or {}).get("content") or ""))
        if chunk.get("done"):
            break
    return "".join(out)


async def _ask(rt, model: str, prefix: str, suffix: str, path: str, multiline: bool) -> tuple[str, str, tuple]:
    """Fragt das Modell und gibt (Rohtext, Weg, Stoppmarken) zurück."""
    options = _options(rt, model, multiline)
    try:
        caps = await rt.model_caps(model)
    except OllamaError:
        caps = []
    fam = family(model)
    if "insert" in caps and rt.backend == "ollama":
        raw = await rt.client.generate(model, prefix, suffix=suffix, options=options,
                                       keep_alive=rt.cfg["keep_alive"])
        return raw, "insert", ()
    if fam:
        stops = fam["stop"]
        raw = await rt.client.generate(model, fim_prompt(fam, prefix, suffix), raw=True, options=options,
                                       stop=stops, keep_alive=rt.cfg["keep_alive"])
        return raw, "fim", stops
    return await _chat(rt, model, prefix, suffix, path, options), "chat", (CURSOR,)


async def complete(rt, *, prefix: str, suffix: str = "", path: str = "", multiline: bool = True) -> dict:
    """Der Vorschlag für die Stelle zwischen prefix und suffix.

    Antwortet immer mit demselben Bild: `text` ist der Vorschlag (leer heißt: keiner), `reason` sagt warum.
    """
    if not rt.cfg.get("complete", True):
        return {"text": "", "reason": "off"}
    own = str(rt.cfg.get("complete_model") or "").strip()
    model = own or str(rt.cfg.get("model") or "")
    if not model:
        return {"text": "", "reason": "no_model"}
    prefix, suffix = cut_prefix(prefix), cut_suffix(suffix)
    if not prefix.strip() and not suffix.strip():
        return {"text": "", "reason": "empty"}
    # Ohne eigenes Ergänzungsmodell wird nichts geladen: Ein großes Hauptmodell stünde sonst minutenlang.
    if not own and not await in_memory(rt, model):
        return {"text": "", "reason": "not_loaded", "model": model}

    key = (model, prefix[-500:], suffix[:200], multiline)
    hit = _cache.get(key)
    if hit is not None:
        return {**hit, "cached": True}

    t0 = time.perf_counter()
    try:
        raw, how, stops = await asyncio.wait_for(_ask(rt, model, prefix, suffix, path, multiline), TIMEOUT)
    except asyncio.TimeoutError:
        return {"text": "", "reason": "timeout", "model": model}
    except OllamaError as e:
        return {"text": "", "reason": "error", "message": str(e), "model": model}
    result = {"text": trim(raw, suffix, multiline, stops), "reason": "ok", "model": model, "how": how,
              "ms": int((time.perf_counter() - t0) * 1000)}
    if len(_cache) >= CACHE_MAX:
        _cache.clear()
    _cache[key] = result
    return result
