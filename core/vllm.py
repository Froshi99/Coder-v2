"""vLLM als zweiter Modell-Server – mit den Modellen, die Ollama ohnehin auf der Platte hat.

Ollama ist bequem, vLLM ist schnell: Es hält das Modell dauerhaft im VRAM, beantwortet mehrere Anfragen
gleichzeitig und bringt eine OpenAI-kompatible Schnittstelle mit (`/v1/chat/completions`). Coder spricht
beide Sprachen – umgestellt wird in den Einstellungen unter *Modell-Server*.

**Dieselben Dateien, kein zweiter Download.** Ollama legt jedes Modell als GGUF-Datei unter
`~/.ollama/models/blobs` ab; welche Datei zu `qwen2.5-coder:14b` gehört, steht im Manifest daneben. Coder liest
das direkt von der Platte – dafür muss Ollama nicht einmal laufen – und baut daraus den fertigen `vllm serve`
-Befehl samt Pfad, Tokenizer und Namen.

**Unter Windows läuft vLLM nicht von allein.** Es braucht Linux mit CUDA, also WSL 2 oder Docker mit
GPU-Durchgriff. Coder startet es deshalb nicht selbst: Es sucht einen laufenden Server (Port 8000, 8001) und
zeigt sonst die Schritte mit Befehlen zum Kopieren – wie beim Bilddienst. Heruntergeladen oder gestartet wird
nichts von allein.
"""

import asyncio
import json
import os
import re
import time
from pathlib import Path
from typing import AsyncIterator

import httpx

from .ollama import OllamaError, _error_text

# Wo vLLM üblicherweise horcht. Eine eigene Adresse aus den Einstellungen wird zuerst geprüft.
CANDIDATES = ("http://127.0.0.1:8000", "http://127.0.0.1:8001")
PROBE_TIMEOUT = 2.0
DETECT_TTL = 60.0  # so lange gilt ein Fund
MISS_TTL = 120.0  # ohne Fund seltener nachsehen – sonst pingt Coder ständig ins Leere
MODEL_MEDIA = "application/vnd.ollama.image.model"  # so heißt die GGUF-Schicht im Manifest
DEFAULT_CTX = 8192

# Welcher Tokenizer zu welcher Modellfamilie passt. vLLM liest ihn bei neueren Fassungen aus der GGUF selbst;
# wo das nicht klappt, hilft der Name des passenden Repositories auf Hugging Face.
TOKENIZERS = {
    "qwen2": "Qwen/Qwen2.5-7B-Instruct", "qwen3": "Qwen/Qwen3-8B", "llama": "meta-llama/Llama-3.1-8B-Instruct",
    "gemma": "google/gemma-3-4b-it", "mistral": "mistralai/Mistral-Nemo-Instruct-2407",
    "phi3": "microsoft/Phi-3.5-mini-instruct", "deepseek2": "deepseek-ai/DeepSeek-V2-Lite",
}

_found: dict = {}  # gemerkter Fund: {"at": …, "backend": … oder None}


# --------------------------------------------------------------------------- Die Modelle von Ollama

def store() -> Path:
    """Wo Ollama seine Dateien ablegt – `OLLAMA_MODELS` geht vor, sonst der Standardordner."""
    raw = os.environ.get("OLLAMA_MODELS")
    if raw:
        return Path(raw)
    return Path.home() / ".ollama" / "models"


def _blob(root: Path, digest: str) -> Path:
    return root / "blobs" / digest.replace(":", "-")


def library(root: Path | None = None) -> list[dict]:
    """Alle Modelle, die Ollama auf der Platte hat – samt GGUF-Datei, Größe und Familie.

    Gelesen werden nur die Manifeste und die kleinen Konfigurationsblobs; die Gewichte fasst niemand an.
    """
    root = root or store()
    manifests = root / "manifests"
    found: list[dict] = []
    if not manifests.is_dir():
        return found
    for path in sorted(manifests.rglob("*")):
        if not path.is_file():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        layer = next((x for x in data.get("layers") or [] if x.get("mediaType") == MODEL_MEDIA), None)
        if not layer:
            continue
        gguf = _blob(root, str(layer.get("digest") or ""))
        if not gguf.is_file():
            continue
        # …/manifests/registry.ollama.ai/library/qwen2.5-coder/14b → „qwen2.5-coder:14b“
        parts = path.relative_to(manifests).parts
        name = "/".join(parts[2:-1]) + ":" + parts[-1] if len(parts) >= 3 else path.name
        details = _details(root, data)
        found.append({"name": name, "path": str(gguf), "size": int(layer.get("size") or gguf.stat().st_size),
                      "family": details.get("family", ""), "params": details.get("parameter_size", ""),
                      "quant": details.get("quantization_level", ""), "details": details})
    return found


def _details(root: Path, manifest: dict) -> dict:
    """Familie, Größe und Quantisierung – dieselben Angaben, die auch Ollama über /api/show meldet."""
    try:
        raw = json.loads(_blob(root, manifest["config"]["digest"]).read_text(encoding="utf-8"))
    except (OSError, ValueError, KeyError):
        return {}
    return {"format": raw.get("model_format", "gguf"), "family": raw.get("model_family", ""),
            "families": raw.get("model_families") or [], "parameter_size": raw.get("model_type", ""),
            "quantization_level": raw.get("file_type", "")}


def find_model(name: str, root: Path | None = None) -> dict | None:
    """Ein Modell aus Ollamas Bestand – „qwen3:8b“ oder auch nur „qwen3“."""
    models = library(root)
    want = name.strip().lower()
    return next((m for m in models if m["name"].lower() == want), None) \
        or next((m for m in models if m["name"].split(":")[0].lower() == want), None)


# --------------------------------------------------------------------------- Einrichten

def wsl_path(path: str | Path) -> str:
    """C:\\Users\\… wird in WSL zu /mnt/c/Users/… – damit der Befehl zum Kopieren stimmt."""
    text = str(path).replace("\\", "/")
    if re.match(r"^[A-Za-z]:/", text):
        return f"/mnt/{text[0].lower()}{text[2:]}"
    return text


def tokenizer_for(model: dict) -> str:
    family = str(model.get("family") or "").lower()
    return next((repo for key, repo in TOKENIZERS.items() if family.startswith(key)), "")


def serve_command(model: dict, kind: str = "wsl", ctx: int = DEFAULT_CTX) -> str:
    """Der fertige Befehl, der vLLM mit genau diesem Ollama-Modell startet.

    Ohne `--tokenizer`: Neuere vLLM-Fassungen lesen ihn aus der GGUF-Datei selbst. Wo das nicht klappt, steht
    der passende Name in der Anleitung daneben – geraten wird er hier nicht in den Befehl hinein.
    """
    name = model["name"]
    link = re.sub(r"[^\w.-]", "-", name) + ".gguf"
    if kind == "docker":
        ordner = str(Path(model["path"]).parent)
        datei = Path(model["path"]).name
        return (f'docker run --gpus all -p 8000:8000 -v "{ordner}":/gguf vllm/vllm-openai:latest '
                f'--model /gguf/{datei} --served-model-name {name} --max-model-len {ctx}')
    # WSL: erst eine Verknüpfung mit der Endung .gguf, dann starten – vLLM erkennt das Format am Namen.
    return (f'mkdir -p ~/gguf && ln -sf "{wsl_path(model["path"])}" ~/gguf/{link} && '
            f'vllm serve ~/gguf/{link} --served-model-name {name} --max-model-len {ctx}')


def setup(cfg: dict) -> dict:
    """Was zu tun ist, damit vLLM läuft – mit den Modellen, die schon da sind."""
    models = library()
    wanted = str(cfg.get("model") or "")
    pick = find_model(wanted) if wanted else None
    pick = pick or (max(models, key=lambda m: m["size"]) if models else None)
    steps = [{
        "titel": "Linux mit CUDA bereitstellen",
        "text": "vLLM läuft nicht unter Windows. Mit **WSL 2** geht es auf demselben Rechner – der "
                "NVIDIA-Treiber von Windows reicht, in Linux wird keiner gebraucht.",
        "command": "wsl --install -d Ubuntu",
    }, {
        "titel": "vLLM installieren",
        "text": "In der Linux-Konsole. Das lädt PyTorch mit CUDA – das dauert und braucht Platz.",
        "command": "pip install vllm",
    }]
    if pick:
        tokenizer = tokenizer_for(pick)
        steps.append({
            "titel": f"Server mit „{pick['name']}“ starten",
            "text": f"Die Datei liegt schon hier – {pick['size'] / 1024 ** 3:.1f} GB, nichts wird noch einmal "
                    f"geladen. Verlangt vLLM einen Tokenizer, hängst du "
                    + (f"`--tokenizer {tokenizer}` an." if tokenizer else "`--tokenizer <HF-Repo>` an."),
            "command": serve_command(pick),
        })
        steps.append({
            "titel": "Lieber mit Docker?",
            "text": "Dann braucht es kein WSL-Python – nur Docker Desktop mit GPU-Durchgriff.",
            "command": serve_command(pick, "docker"),
        })
    else:
        steps.append({"titel": "Erst ein Modell holen",
                      "text": "Coder findet unter Ollamas Modellen keine GGUF-Datei. Lade eines mit "
                              "`ollama pull qwen2.5-coder:14b` – vLLM nutzt dann dieselbe Datei.", "command": ""})
    return {"hint": "Kein vLLM erreichbar." if models else "Kein vLLM erreichbar, keine Ollama-Modelle gefunden.",
            "steps": steps, "models": [{k: m[k] for k in ("name", "path", "size", "params", "quant")}
                                       for m in models[:20]], "picked": pick["name"] if pick else ""}


# --------------------------------------------------------------------------- Suchen

def forget() -> None:
    _found.clear()


async def detect(cfg: dict, force: bool = False) -> dict | None:
    """Läuft irgendwo ein vLLM? Gibt Adresse und bediente Modelle zurück – oder None."""
    ttl = DETECT_TTL if _found.get("backend") else MISS_TTL
    if not force and _found and time.monotonic() - _found.get("at", 0) < ttl:
        return _found.get("backend")
    own = str(cfg.get("vllm_url") or "").strip().rstrip("/")
    urls = [own] if own else list(CANDIDATES)
    found = None
    for url in urls:
        info = await probe(url)
        if info:
            found = info
            break
    _found.update({"at": time.monotonic(), "backend": found})
    return found


async def probe(url: str) -> dict | None:
    """Antwortet dort ein OpenAI-kompatibler Server?"""
    try:
        async with httpx.AsyncClient(timeout=PROBE_TIMEOUT) as client:
            r = await client.get(f"{url.rstrip('/')}/v1/models")
            if r.status_code >= 400:
                return None
            data = r.json()
            models = [m for m in data.get("data") or [] if m.get("id")]
            version = ""
            try:
                v = await client.get(f"{url.rstrip('/')}/version")
                version = (v.json() or {}).get("version", "") if v.status_code < 400 else ""
            except (httpx.HTTPError, ValueError):
                pass
        return {"url": url.rstrip("/"), "version": version,
                "models": [{"id": m["id"], "max_model_len": m.get("max_model_len")} for m in models]}
    except (httpx.HTTPError, ValueError, KeyError):
        return None


# --------------------------------------------------------------------------- Der Client

class VLLM:
    """Spricht mit vLLM und antwortet in derselben Form wie der Ollama-Client.

    So merkt der Rest von Coder nichts vom Wechsel: Der Agent bekommt dieselben Stücke („message“,
    „done“, Zähler) – nur kommen sie hier aus `/v1/chat/completions` im OpenAI-Format.
    """

    def __init__(self, base_url: str = "http://127.0.0.1:8000"):
        self.base_url = (base_url or CANDIDATES[0]).rstrip("/")
        self._client = httpx.AsyncClient(base_url=self.base_url, timeout=httpx.Timeout(None, connect=5.0))
        self._models: tuple[float, list[dict]] = (0.0, [])

    async def close(self) -> None:
        await self._client.aclose()

    async def _json(self, method: str, path: str, **kw) -> dict:
        try:
            r = await self._client.request(method, path, **kw)
        except httpx.HTTPError as e:
            raise OllamaError(f"vLLM nicht erreichbar unter {self.base_url} ({e.__class__.__name__})") from e
        if r.status_code >= 400:
            raise OllamaError(_error_text(r.text, r.status_code))
        try:
            return r.json()
        except ValueError as e:
            raise OllamaError(f"vLLM antwortet nicht in JSON: {r.text[:200]}") from e

    # ------------------------------------------------------------------ Auskunft

    async def version(self) -> str:
        try:
            return (await self._json("GET", "/version")).get("version", "vLLM")
        except OllamaError:
            await self._served()  # /version gibt es nicht überall – dann zählt, dass Modelle antworten
            return "vLLM"

    async def _served(self, max_age: float = 10.0) -> list[dict]:
        stamp, models = self._models
        if not models or time.monotonic() - stamp > max_age:
            data = await self._json("GET", "/v1/models")
            models = [m for m in data.get("data") or [] if m.get("id")]
            self._models = (time.monotonic(), models)
        return models

    async def tags(self) -> list[dict]:
        """Die bedienten Modelle – ergänzt um das, was Ollamas Dateien über sie wissen."""
        served = await self._served()
        known = {m["name"]: m for m in await asyncio.to_thread(library)}
        out = []
        for m in served:
            info = known.get(m["id"]) or {}
            out.append({"name": m["id"], "size": info.get("size", 0), "details": info.get("details", {}),
                        "max_model_len": m.get("max_model_len")})
        return out

    async def show(self, model: str) -> dict:
        """Dasselbe Bild wie bei Ollama: Fähigkeiten, Eckdaten, Kontextlänge."""
        tag = next((t for t in await self.tags() if t["name"] == model), None)
        ctx = (tag or {}).get("max_model_len") or DEFAULT_CTX
        family = ((tag or {}).get("details") or {}).get("family") or "llama"
        return {"capabilities": ["completion", "tools"], "details": (tag or {}).get("details", {}),
                "model_info": {"general.architecture": family, f"{family}.context_length": ctx}}

    async def ps(self) -> list[dict]:
        """vLLM hält sein Modell dauerhaft im Speicher – es ist also immer „geladen“."""
        out = []
        for tag in await self.tags():
            out.append({"name": tag["name"], "size": tag.get("size", 0), "size_vram": tag.get("size", 0),
                        "context_length": tag.get("max_model_len"), "expires_at": None})
        return out

    async def load(self, model: str, options: dict, keep_alive: str) -> dict:
        """Geladen wird beim Start des Servers – hier ist nichts zu tun."""
        await self._served()
        return {"done": True}

    async def unload(self, model: str) -> None:
        return None  # das entscheidet der vLLM-Server, nicht Coder

    async def generate(self, model: str, prompt: str, *, suffix: str = "", raw: bool = False,
                       options: dict | None = None, stop=None, keep_alive: str | None = None) -> str:
        """Eine Antwort am Stück über `/v1/completions` – der Prompt geht so durch, wie er ankommt."""
        opts = dict(options or {})
        payload: dict = {"model": model, "prompt": prompt, "stream": False,
                         "max_tokens": int(opts.get("num_predict") or 128),
                         "temperature": float(opts.get("temperature", 0.1))}
        if opts.get("top_p") is not None:
            payload["top_p"] = opts["top_p"]
        if suffix:
            payload["suffix"] = suffix
        if stop:
            payload["stop"] = list(stop)[:4]  # vLLM nimmt höchstens vier
        choices = (await self._json("POST", "/v1/completions", json=payload)).get("choices") or []
        return str((choices[0] or {}).get("text") or "") if choices else ""

    async def embed(self, model: str, inputs: list[str], keep_alive: str = "10m",
                    options: dict | None = None) -> list[list[float]]:
        data = await self._json("POST", "/v1/embeddings", json={"model": model, "input": inputs})
        return [d.get("embedding", []) for d in data.get("data") or []]

    # ------------------------------------------------------------------ Reden

    async def chat_stream(self, model: str, messages: list[dict], *, tools: list[dict] | None = None,
                          options: dict | None = None, keep_alive: str | None = None,
                          think: bool | None = None) -> AsyncIterator[dict]:
        payload: dict = {"model": model, "messages": to_openai(messages), "stream": True,
                         "stream_options": {"include_usage": True}}
        if tools:
            payload["tools"] = tools  # dasselbe Schema wie bei Ollama: {"type": "function", "function": {…}}
        for key, ziel in (("temperature", "temperature"), ("top_p", "top_p"), ("num_predict", "max_tokens"),
                          ("seed", "seed")):
            if options and options.get(key) is not None:
                payload[ziel] = options[key]
        if think is not None:
            payload["chat_template_kwargs"] = {"enable_thinking": bool(think)}
        calls: dict[int, dict] = {}
        usage: dict = {}
        try:
            async with self._client.stream("POST", "/v1/chat/completions", json=payload) as r:
                if r.status_code >= 400:
                    body = (await r.aread()).decode("utf-8", "replace")
                    raise OllamaError(_error_text(body, r.status_code))
                async for line in r.aiter_lines():
                    line = line.strip()
                    if not line.startswith("data:"):
                        continue
                    rest = line[5:].strip()
                    if rest == "[DONE]":
                        break
                    try:
                        chunk = json.loads(rest)
                    except ValueError:
                        continue
                    if chunk.get("error"):
                        raise OllamaError(str(chunk["error"]))
                    if chunk.get("usage"):
                        usage = chunk["usage"]
                    for stück in _pieces(chunk, calls):
                        yield stück
        except httpx.HTTPError as e:
            raise OllamaError(f"Verbindung zu vLLM unterbrochen ({e.__class__.__name__})") from e
        message: dict = {"role": "assistant", "content": ""}
        fertig = _finish_calls(calls)
        if fertig:
            message["tool_calls"] = fertig
        yield {"message": message, "done": True, "done_reason": "stop",
               "prompt_eval_count": usage.get("prompt_tokens", 0), "eval_count": usage.get("completion_tokens", 0)}


def _pieces(chunk: dict, calls: dict) -> list[dict]:
    """Ein Stück aus dem Strom in die Form bringen, die der Agent von Ollama kennt."""
    out = []
    for choice in chunk.get("choices") or []:
        delta = choice.get("delta") or {}
        denken = delta.get("reasoning_content") or delta.get("reasoning")
        if denken:
            out.append({"message": {"role": "assistant", "content": "", "thinking": denken}, "done": False})
        if delta.get("content"):
            out.append({"message": {"role": "assistant", "content": delta["content"]}, "done": False})
        for call in delta.get("tool_calls") or []:
            index = int(call.get("index") or 0)
            eintrag = calls.setdefault(index, {"id": "", "name": "", "args": ""})
            if call.get("id"):
                eintrag["id"] = call["id"]
            fn = call.get("function") or {}
            if fn.get("name"):
                eintrag["name"] = fn["name"]
            if fn.get("arguments"):
                eintrag["args"] += fn["arguments"]
    return out


def _finish_calls(calls: dict) -> list[dict]:
    """Aus den Bruchstücken des Stroms werden Aufrufe, wie Ollama sie schickt."""
    fertig = []
    for index in sorted(calls):
        eintrag = calls[index]
        if not eintrag["name"]:
            continue
        try:
            args = json.loads(eintrag["args"] or "{}")
        except ValueError:
            args = {"_raw": eintrag["args"]}
        fertig.append({"function": {"name": eintrag["name"], "arguments": args if isinstance(args, dict) else {}}})
    return fertig


def to_openai(messages: list[dict]) -> list[dict]:
    """Ollamas Nachrichten ins OpenAI-Format – inklusive der Kennungen, die dort zu jedem Aufruf gehören.

    Ollama kommt ohne sie aus: Werkzeugergebnisse folgen einfach in der Reihenfolge der Aufrufe. Hier werden
    sie deshalb durchnummeriert und den Ergebnissen der Reihe nach wieder zugeordnet.
    """
    out: list[dict] = []
    offen: list[str] = []
    zähler = 0
    for m in messages:
        role = m.get("role")
        if role == "tool":
            out.append({"role": "tool", "tool_call_id": offen.pop(0) if offen else f"call_{zähler}",
                        "content": str(m.get("content") or "")})
            continue
        neu: dict = {"role": role or "user", "content": _content(m)}
        if m.get("tool_calls"):
            neu["tool_calls"] = []
            for call in m["tool_calls"]:
                fn = call.get("function") or {}
                zähler += 1
                kennung = call.get("id") or f"call_{zähler}"
                offen.append(kennung)
                args = fn.get("arguments")
                neu["tool_calls"].append({"id": kennung, "type": "function", "function": {
                    "name": fn.get("name", ""),
                    "arguments": args if isinstance(args, str) else json.dumps(args or {}, ensure_ascii=False)}})
            if not neu["content"]:
                neu["content"] = None  # ein Aufruf ohne Text: OpenAI mag dort lieber nichts als ""
        out.append(neu)
    return out


def _content(m: dict):
    """Text – und Bilder, wenn welche dabei sind (Ollama hängt sie als base64 an die Nachricht)."""
    text = str(m.get("content") or "")
    images = [i for i in (m.get("images") or []) if isinstance(i, str)]
    if not images:
        return text
    teile: list[dict] = [{"type": "text", "text": text}] if text else []
    for bild in images:
        url = bild if bild.startswith("data:") else f"data:image/png;base64,{bild}"
        teile.append({"type": "image_url", "image_url": {"url": url}})
    return teile
