"""Bilder erzeugen – mit dem Bilddienst, der auf diesem Rechner ohnehin dafür da ist.

Ollama malt nicht. Coder spricht deshalb mit einer lokalen Stable-Diffusion-Oberfläche:

* **ComfyUI** (Standard-Port 8188) – Coder baut den Graphen selbst, es braucht keinen vorbereiteten Workflow
* **Automatic1111**, **Forge**, **reForge**, **SD.Next** (Port 7860 oder 7801) – über deren `/sdapi/v1`

Gefunden wird der Dienst von allein: Die üblichen Adressen werden geprüft, das Ergebnis eine Minute lang gemerkt.
Läuft keiner, gibt es das Werkzeug `generate_image` gar nicht erst – so verspricht der Agent nichts, was er nicht kann.
"""

import asyncio
import base64
import binascii
import contextlib
import json
import os
import random
import re
import struct
import time
from pathlib import Path
from typing import Awaitable, Callable

import httpx

# Wo lokale Bilddienste üblicherweise horchen. Eine eigene Adresse aus den Einstellungen wird zuerst geprüft.
CANDIDATES = ("http://127.0.0.1:7860", "http://127.0.0.1:8188", "http://127.0.0.1:7801", "http://127.0.0.1:8189")
PROBE_TIMEOUT = 2.0
GENERATE_TIMEOUT = 600.0
DETECT_TTL = 60.0  # so lange gilt ein Fund, bevor erneut gesucht wird
# Ohne Fund wird seltener gesucht – sonst pingt Coder bei jedem Auftrag Adressen an, an denen nie etwas horcht.
# Die Einstellungen suchen auf Knopfdruck sofort neu (force), ein frisch gestarteter Dienst ist also gleich da.
MISS_TTL = 120.0

MAX_SIDE = 2048
MIN_SIDE = 128
MAX_STEPS = 150
DEFAULT_STEPS = 25
DEFAULT_CFG = 6.5
# Was ein Modell ohne weitere Angabe malen soll: SDXL, Flux und SD3 sind auf 1024 trainiert, SD 1.5 auf 512.
BIG_MODEL_RX = re.compile(r"(xl|flux|sd3|sd35|qwen|chroma|illustrious|pony|hidream|playground)", re.I)
# Destillierte Modelle führen keine Guidance aus: mit CFG 6.5 verbrennen sie das Bild, Euler passt besser als DPM++.
DISTILLED_RX = re.compile(r"(flux|schnell|sd3|sd35|chroma|hidream|turbo|lightning|hyper|lcm)", re.I)
NEGATIVE_DEFAULT = "lowres, blurry, jpeg artifacts, watermark, text, signature, deformed, extra fingers"

_cache: tuple[float, str, dict | None] = (0.0, "", None)
_lock = asyncio.Lock()
_pending: set = set()  # hält losgeschickte Abbruch-Anfragen fest, bis sie durch sind


class ImageError(RuntimeError):
    pass


# --------------------------------------------------------------------------- Dienst finden


def _clean_url(raw) -> str:
    url = str(raw or "").strip().rstrip("/")
    if url and "://" not in url:
        url = "http://" + url
    return url


async def _probe(client: httpx.AsyncClient, url: str) -> dict | None:
    """Was horcht dort – A1111-Familie, ComfyUI oder nichts?"""
    try:
        r = await client.get(f"{url}/sdapi/v1/sd-models")
        if r.status_code == 200:
            data = r.json()
            if isinstance(data, list):
                names = [str(m.get("model_name") or m.get("title") or "") for m in data if isinstance(m, dict)]
                return {"kind": "a1111", "url": url, "models": [n for n in names if n],
                        "label": "Stable Diffusion WebUI"}
    except (httpx.HTTPError, ValueError):
        pass
    try:
        r = await client.get(f"{url}/system_stats")
        if r.status_code == 200 and isinstance(r.json(), dict):
            return {"kind": "comfyui", "url": url, "models": await _comfy_checkpoints(client, url), "label": "ComfyUI"}
    except (httpx.HTTPError, ValueError):
        pass
    return None


async def _comfy_checkpoints(client: httpx.AsyncClient, url: str) -> list[str]:
    try:
        r = await client.get(f"{url}/object_info/CheckpointLoaderSimple")
        info = r.json() if r.status_code == 200 else {}
        names = info["CheckpointLoaderSimple"]["input"]["required"]["ckpt_name"][0]
        return [str(n) for n in names][:200]
    except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError):
        return []


async def detect(cfg: dict | None = None, *, force: bool = False) -> dict | None:
    """Der gefundene Bilddienst – oder None. Das Ergebnis wird kurz gemerkt, damit nichts unnötig gepingt wird."""
    global _cache
    cfg = cfg or {}
    if str(cfg.get("image_backend") or "auto") == "off":
        return None
    configured = _clean_url(cfg.get("image_url"))
    async with _lock:
        at, key, found = _cache
        ttl = DETECT_TTL if found else MISS_TTL
        if not force and key == configured and time.monotonic() - at < ttl:
            return found
        urls = [configured] if configured else list(CANDIDATES)
        result = None
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(PROBE_TIMEOUT)) as client:
                # Alle Adressen gleichzeitig anklopfen; die Reihenfolge entscheidet, nicht wer zuerst antwortet.
                found = await asyncio.gather(*(_probe(client, url) for url in urls), return_exceptions=True)
                result = next((f for f in found if isinstance(f, dict)), None)
        except (httpx.InvalidURL, httpx.UnsupportedProtocol, ValueError, TypeError):
            result = None  # eine unbrauchbare Adresse aus den Einstellungen soll nichts umwerfen
        _cache = (time.monotonic(), configured, result)
        return result


def forget() -> None:
    """Nach einer Änderung an den Einstellungen neu suchen."""
    global _cache
    _cache = (0.0, "", None)


SETTINGS_HINT = " Die Adresse steht in den Einstellungen unter „Bilder erzeugen“."


def hint(cfg: dict | None = None) -> str:
    """Was der Nutzer tun kann, wenn kein Dienst läuft. Ohne Verweis auf die Einstellungen – dort steht er schon."""
    configured = _clean_url((cfg or {}).get("image_url"))
    where = configured or "http://127.0.0.1:7860 (Automatic1111, Forge, SD.Next) oder http://127.0.0.1:8188 (ComfyUI)"
    return (f"Kein lokaler Bilddienst erreichbar unter {where}. Starte ComfyUI oder eine Stable-Diffusion-WebUI – "
            "die WebUI braucht dafür den Schalter --api.")


# --------------------------------------------------------------------------- Einrichten

# Woran ein bereits entpackter Dienst auf der Platte zu erkennen ist.
SPUREN = (
    ("comfyui", "ComfyUI", ("main.py", "comfy"), "python main.py"),
    ("comfyui", "ComfyUI (portable)", ("ComfyUI", "python_embeded"),
     r"run_nvidia_gpu.bat"),
    ("a1111", "Stable Diffusion WebUI", ("webui-user.bat", "modules"), "webui-user.bat"),
    ("a1111", "Stable Diffusion WebUI", ("webui.sh", "modules"), "./webui.sh --api"),
)
# Wo Leute solche Ordner ablegen. Nur eine Ebene tief – ein Plattenscan wäre unverschämt.
SUCHORTE = ("~", "~/Desktop", "~/Downloads", "~/Documents", "C:/", "D:/", "D:/KI", "D:/AI", "E:/")
NAMEN = ("comfyui", "stable-diffusion-webui", "sd-webui", "forge", "sdnext", "automatic")


def _passt(ordner: Path) -> tuple[str, str, str] | None:
    try:
        vorhanden = {p.name.lower() for p in list(ordner.iterdir())[:400]}
    except OSError:
        return None
    for kind, label, marker, start in SPUREN:
        if all(m.lower() in vorhanden for m in marker):
            return kind, label, start
    return None


def find_install() -> dict | None:
    """Ein Dienst, der schon auf der Platte liegt, aber nicht läuft – oder None.

    Das ist der häufigste Fall: installiert, nur gerade nicht gestartet. Dann muss niemand etwas herunterladen.
    """
    gesehen: set = set()
    for ort in SUCHORTE:
        wurzel = Path(os.path.expanduser(ort))
        try:
            if not wurzel.is_dir():
                continue
            kandidaten = [wurzel] + [p for p in list(wurzel.iterdir())[:300] if p.is_dir()
                                     and any(n in p.name.lower() for n in NAMEN)]
        except OSError:
            continue
        for ordner in kandidaten:
            key = str(ordner).lower()
            if key in gesehen:
                continue
            gesehen.add(key)
            if not any(n in ordner.name.lower() for n in NAMEN):
                continue
            treffer = _passt(ordner)
            if treffer:
                kind, label, start = treffer
                return {"kind": kind, "label": label, "path": str(ordner), "start": start}
    return None


# Kurzanleitungen – Befehle zum Kopieren, keine Werbung. Coder lädt nichts von allein herunter.
ANLEITUNG = [
    {
        "titel": "ComfyUI – die einfache Art (Windows, NVIDIA)",
        "text": "Portable Fassung herunterladen, entpacken, `run_nvidia_gpu.bat` doppelklicken. Danach läuft es "
                "auf Port 8188 und Coder findet es von allein. Ein Modell gehört nach "
                "`ComfyUI/models/checkpoints` – ohne Checkpoint kann es nichts malen.",
        "url": "https://github.com/comfyanonymous/ComfyUI/releases",
    },
    {
        "titel": "ComfyUI aus dem Quelltext",
        "text": "Braucht Python und Git. PyTorch passend zur Grafikkarte installieren (die Zeile unten gilt für "
                "NVIDIA mit CUDA 12).",
        "command": "\n".join((
            "git clone https://github.com/comfyanonymous/ComfyUI",
            "cd ComfyUI",
            "pip install torch torchvision --index-url https://download.pytorch.org/whl/cu121",
            "pip install -r requirements.txt",
            "python main.py",
        )),
    },
    {
        "titel": "Stable Diffusion WebUI oder Forge",
        "text": "Wenn du die WebUI schon hast: Coder spricht sie über ihre API an. Dafür muss sie mit `--api` "
                "starten – die Zeile kommt in `webui-user.bat` hinter `set COMMANDLINE_ARGS=`.",
        "command": "set COMMANDLINE_ARGS=--api",
    },
    {
        "titel": "Modelle",
        "text": "Ein Checkpoint reicht zum Anfangen. Für 12 GB Grafikspeicher passen SDXL-Modelle gut; SD-1.5-"
                "Modelle sind kleiner und schneller. Die Datei gehört bei ComfyUI nach `models/checkpoints`, "
                "bei der WebUI nach `models/Stable-diffusion`.",
        "url": "https://civitai.com/models",
    },
]


def setup(cfg: dict | None = None) -> dict:
    """Alles, was die Einstellungen zum Einrichten brauchen: gefunden, gefunden-aber-aus, und die Anleitung."""
    return {"installed": find_install(), "steps": ANLEITUNG, "hint": hint(cfg)}


# --------------------------------------------------------------------------- Maße und Modell


def default_size(model: str | None) -> int:
    return 1024 if BIG_MODEL_RX.search(str(model or "")) else 512


def _round64(value) -> int:
    return max(MIN_SIDE, min(MAX_SIDE, int(round(float(value) / 64.0)) * 64))


def pick_model(backend: dict, wanted: str | None) -> str | None:
    """Das Modell, das gemeint ist: genau, sonst als Teilstück des Namens, sonst das erste installierte."""
    models = [m for m in backend.get("models") or [] if m]
    wanted = str(wanted or "").strip()
    if wanted:
        for name in models:
            if name.lower() == wanted.lower():
                return name
        for name in models:
            if wanted.lower() in name.lower():
                return name
        if not models:
            return wanted  # der Dienst verrät seine Modelle nicht – dann eben ungeprüft weiterreichen
        raise ImageError(f"Kein Bildmodell mit „{wanted}“ im Namen. Vorhanden: {', '.join(models[:12])}")
    return models[0] if models else None


def plan(backend: dict, opts: dict) -> dict:
    """Aus den Wünschen des Modells vollständige, gültige Werte machen."""
    model = pick_model(backend, opts.get("model"))
    side = default_size(model)
    width = _round64(opts.get("width") or side)
    height = _round64(opts.get("height") or opts.get("width") or side)
    distilled = bool(DISTILLED_RX.search(str(model or "")))
    steps = max(1, min(MAX_STEPS, int(opts.get("steps") or DEFAULT_STEPS)))
    seed = opts.get("seed")
    seed = random.randint(0, 2**31 - 1) if seed in (None, "", -1) else int(seed) & 0x7FFFFFFF
    strength = opts.get("strength")
    strength = 0.65 if strength in (None, "") else max(0.05, min(1.0, float(strength)))
    return {
        "model": model,
        "prompt": str(opts.get("prompt") or "").strip(),
        "negative": str(opts.get("negative") if opts.get("negative") is not None else NEGATIVE_DEFAULT).strip(),
        "width": width, "height": height, "steps": steps, "seed": seed,
        "cfg_scale": float(opts.get("cfg_scale") or (1.0 if distilled else DEFAULT_CFG)),
        "strength": strength, "distilled": distilled,
    }


OUT_EXT = (".png", ".jpg", ".jpeg", ".webp", ".ico")
ICO_SIZES = [(256, 256), (128, 128), (64, 64), (32, 32), (16, 16)]


def convert(png: bytes, suffix: str) -> tuple[bytes, str]:
    """Das erzeugte PNG ins gewünschte Format bringen. Ohne Pillow bleibt es ein PNG – dann heißt auch die Datei so."""
    want = str(suffix or "").lower()
    if want not in OUT_EXT or want == ".png":
        return png, ".png"
    try:
        import io
        from PIL import Image
        with Image.open(io.BytesIO(png)) as img:
            out = io.BytesIO()
            if want == ".webp":
                img.save(out, "WEBP", quality=92, method=4)
            elif want == ".ico":
                img.convert("RGBA").save(out, "ICO", sizes=[s for s in ICO_SIZES if s[0] <= min(img.size)] or None)
            else:
                img.convert("RGB").save(out, "JPEG", quality=92, optimize=True)
            return out.getvalue(), want
    except (ImportError, OSError, ValueError):
        return png, ".png"


# --------------------------------------------------------------------------- Erzeugen


async def generate(backend: dict, opts: dict, init_png: bytes | None = None,
                   on_status: Callable[[str], Awaitable[None]] | None = None) -> dict:
    """Erzeugt ein Bild und gibt {"png", "model", "seed", "width", "height", "steps", "seconds"} zurück."""
    settings = plan(backend, opts)
    if not settings["prompt"]:
        raise ImageError("Ohne Beschreibung kann ich kein Bild malen.")
    started = time.monotonic()
    timeout = httpx.Timeout(GENERATE_TIMEOUT, connect=5.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        try:
            if backend["kind"] == "comfyui":
                png, model = await _comfy_generate(client, backend["url"], settings, init_png, on_status)
            else:
                png, model = await _a1111_generate(client, backend["url"], settings, init_png, on_status)
        except asyncio.CancelledError:
            # Stopp im Chat: der Dienst soll die GPU nicht weiter beschäftigen. Losschicken, nicht darauf warten.
            task = asyncio.ensure_future(interrupt(backend))
            _pending.add(task)
            task.add_done_callback(_pending.discard)
            raise
    if not png:
        raise ImageError("Der Bilddienst hat kein Bild zurückgegeben.")
    real = png_size(png)
    if real:  # manche Oberflächen skalieren nach (Hires-Fix) – gemeldet wird, was wirklich herauskam
        settings["width"], settings["height"] = real
    return {**settings, "png": png, "model": model or settings["model"] or "?",
            "seconds": round(time.monotonic() - started, 1), "backend": backend["kind"]}


def png_size(data: bytes) -> tuple[int, int] | None:
    """Breite und Höhe aus dem PNG-Kopf."""
    if len(data) >= 24 and data[:8] == b"\x89PNG\r\n\x1a\n" and data[12:16] == b"IHDR":
        width, height = struct.unpack(">II", data[16:24])
        return (width, height) if 0 < width <= 65535 and 0 < height <= 65535 else None
    return None


async def interrupt(backend: dict) -> None:
    """Dem Bilddienst sagen, dass er aufhören darf."""
    path = "/interrupt" if backend.get("kind") == "comfyui" else "/sdapi/v1/interrupt"
    with contextlib.suppress(httpx.HTTPError, ValueError, TypeError):
        async with httpx.AsyncClient(timeout=httpx.Timeout(5.0)) as client:
            await client.post(f"{backend['url']}{path}")


def _decode(b64: str) -> bytes:
    text = str(b64 or "")
    if text.startswith("data:"):
        text = text.split(",", 1)[-1]
    try:
        return base64.b64decode(text, validate=True)
    except (binascii.Error, ValueError) as e:
        raise ImageError("Das Bild kam beschädigt an.") from e


# ---------------------------------------------------------------- Automatic1111 / Forge / SD.Next


async def _a1111_generate(client, url, s, init_png, on_status):
    payload = {
        "prompt": s["prompt"], "negative_prompt": s["negative"],
        "width": s["width"], "height": s["height"], "steps": s["steps"],
        "cfg_scale": s["cfg_scale"], "seed": s["seed"], "batch_size": 1, "n_iter": 1,
        "save_images": False, "send_images": True,
    }
    if s["model"]:
        payload["override_settings"] = {"sd_model_checkpoint": s["model"]}
        payload["override_settings_restore_afterwards"] = True
    endpoint = "txt2img"
    if init_png:
        endpoint = "img2img"
        payload["init_images"] = [base64.b64encode(init_png).decode("ascii")]
        payload["denoising_strength"] = s["strength"]
        payload["resize_mode"] = 1
    if on_status:
        await on_status(f"{s['width']}×{s['height']}, {s['steps']} Schritte …")
    watch = asyncio.create_task(_a1111_progress(client, url, on_status)) if on_status else None
    try:
        r = await client.post(f"{url}/sdapi/v1/{endpoint}", json=payload)
    finally:
        if watch:
            watch.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await watch  # erst zu Ende, dann darf der Client zumachen
    if r.status_code >= 400:
        raise ImageError(_http_error(r))
    data = r.json()
    images = data.get("images") or []
    if not images:
        raise ImageError("Der Bilddienst hat kein Bild zurückgegeben.")
    used = s["model"]
    try:
        info = json.loads(data.get("info") or "{}")
        s["seed"] = int(info.get("seed", s["seed"]))
        used = info.get("sd_model_name") or used
    except (ValueError, TypeError):
        pass
    return _decode(images[0]), used


async def _a1111_progress(client, url, on_status):
    """Der Fortschritt der WebUI, solange sie rechnet – nur fürs Auge."""
    try:
        while True:
            await asyncio.sleep(2.0)
            r = await client.get(f"{url}/sdapi/v1/progress", params={"skip_current_image": "true"},
                                 timeout=httpx.Timeout(5.0))
            if r.status_code != 200:
                continue
            data = r.json()
            done = float(data.get("progress") or 0)
            if done > 0:
                left = data.get("eta_relative") or 0
                rest = f", noch etwa {int(left)} s" if left and left > 1 else ""
                await on_status(f"{int(done * 100)} %{rest}")
    except (asyncio.CancelledError, httpx.HTTPError, ValueError, TypeError, RuntimeError):
        return  # der Fortschritt ist nur fürs Auge – er darf den Auftrag nie zu Fall bringen


# ---------------------------------------------------------------- ComfyUI


def _comfy_graph(s: dict, init_name: str | None) -> dict:
    """Ein vollständiger txt2img- bzw. img2img-Graph – Coder baut ihn selbst, damit kein Workflow nötig ist."""
    graph = {
        "1": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": s["model"]}},
        "2": {"class_type": "CLIPTextEncode", "inputs": {"text": s["prompt"], "clip": ["1", 1]}},
        "3": {"class_type": "CLIPTextEncode", "inputs": {"text": s["negative"], "clip": ["1", 1]}},
        "5": {"class_type": "KSampler", "inputs": {
            "seed": s["seed"], "steps": s["steps"], "cfg": s["cfg_scale"],
            "sampler_name": "euler" if s.get("distilled") else "dpmpp_2m",
            "scheduler": "simple" if s.get("distilled") else "karras", "denoise": 1.0,
            "model": ["1", 0], "positive": ["2", 0], "negative": ["3", 0], "latent_image": ["4", 0]}},
        "6": {"class_type": "VAEDecode", "inputs": {"samples": ["5", 0], "vae": ["1", 2]}},
        "7": {"class_type": "SaveImage", "inputs": {"filename_prefix": "coder", "images": ["6", 0]}},
    }
    if init_name:
        graph["4"] = {"class_type": "VAEEncode", "inputs": {"pixels": ["8", 0], "vae": ["1", 2]}}
        graph["8"] = {"class_type": "LoadImage", "inputs": {"image": init_name}}
        graph["5"]["inputs"]["denoise"] = s["strength"]
    else:
        graph["4"] = {"class_type": "EmptyLatentImage",
                      "inputs": {"width": s["width"], "height": s["height"], "batch_size": 1}}
    return graph


async def _comfy_generate(client, url, s, init_png, on_status):
    if not s["model"]:
        raise ImageError("ComfyUI meldet kein Checkpoint-Modell. Lege eines unter models/checkpoints ab.")
    init_name = await _comfy_upload(client, url, init_png) if init_png else None
    client_id = f"coder-{random.randint(0, 2**31 - 1):x}"
    if on_status:
        await on_status(f"{s['width']}×{s['height']}, {s['steps']} Schritte …")
    r = await client.post(f"{url}/prompt", json={"prompt": _comfy_graph(s, init_name), "client_id": client_id})
    if r.status_code >= 400:
        raise ImageError(_comfy_error(r))
    prompt_id = (r.json() or {}).get("prompt_id")
    if not prompt_id:
        raise ImageError("ComfyUI hat den Auftrag nicht angenommen.")
    entry = await _comfy_wait(client, url, prompt_id, on_status)
    for node in (entry.get("outputs") or {}).values():
        for image in node.get("images") or []:
            if image.get("type") == "temp":
                continue
            got = await client.get(f"{url}/view", params={"filename": image.get("filename", ""),
                                                          "subfolder": image.get("subfolder", ""),
                                                          "type": image.get("type", "output")})
            if got.status_code == 200 and got.content:
                return got.content, s["model"]
    raise ImageError("ComfyUI hat den Auftrag beendet, aber kein Bild gespeichert.")


async def _comfy_upload(client, url, png: bytes) -> str:
    name = f"coder-{random.randint(0, 2**31 - 1):x}.png"
    files = {"image": (name, png, "image/png")}
    r = await client.post(f"{url}/upload/image", files=files, data={"overwrite": "true", "type": "input"})
    if r.status_code >= 400:
        raise ImageError(f"ComfyUI nimmt das Vorlagenbild nicht an ({_http_error(r)}).")
    data = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
    folder = data.get("subfolder") or ""
    return f"{folder}/{data.get('name', name)}" if folder else str(data.get("name", name))


async def _comfy_wait(client, url, prompt_id, on_status) -> dict:
    """Wartet auf das Ergebnis und meldet unterwegs, wie weit es ist."""
    deadline = time.monotonic() + GENERATE_TIMEOUT
    told = 0.0
    while time.monotonic() < deadline:
        r = await client.get(f"{url}/history/{prompt_id}", timeout=httpx.Timeout(15.0))
        entry = (r.json() or {}).get(prompt_id) if r.status_code == 200 else None
        if entry:
            if entry.get("outputs"):
                return entry
            status = entry.get("status") or {}
            if status.get("status_str") == "error":
                raise ImageError(_comfy_status_error(status))
        if on_status and time.monotonic() - told > 5.0:
            told = time.monotonic()
            await on_status(await _comfy_progress(client, url, prompt_id))
        await asyncio.sleep(1.0)
    raise ImageError(f"ComfyUI ist nach {int(GENERATE_TIMEOUT)} s noch nicht fertig.")


async def _comfy_progress(client, url, prompt_id) -> str:
    try:
        r = await client.get(f"{url}/queue", timeout=httpx.Timeout(5.0))
        data = r.json() if r.status_code == 200 else {}
        running = [q for q in data.get("queue_running") or [] if len(q) > 1 and q[1] == prompt_id]
        waiting = len(data.get("queue_pending") or [])
        if not running and waiting:
            return f"in der Warteschlange von ComfyUI ({waiting} davor)"
    except (httpx.HTTPError, ValueError, TypeError, IndexError):
        pass
    return "ComfyUI rechnet …"


def _comfy_status_error(status: dict) -> str:
    for entry in reversed(status.get("messages") or []):
        if isinstance(entry, (list, tuple)) and len(entry) > 1 and isinstance(entry[1], dict):
            detail = entry[1].get("exception_message") or entry[1].get("exception_type")
            if detail:
                return f"ComfyUI meldet: {detail}"
    return "ComfyUI hat den Auftrag abgebrochen."


def _comfy_error(r) -> str:
    try:
        data = r.json()
    except ValueError:
        return _http_error(r)
    parts = []
    for node, err in (data.get("node_errors") or {}).items():
        for detail in err.get("errors") or []:
            where = err.get("class_type", node)
            parts.append(f"{where}: {detail.get('message', '')} {detail.get('details', '')}".strip())
    if data.get("error"):
        head = data["error"]
        parts.insert(0, head.get("message", "") if isinstance(head, dict) else str(head))
    text = "; ".join(p for p in parts if p)
    return f"ComfyUI: {text[:500]}" if text else _http_error(r)


def _http_error(r) -> str:
    body = (r.text or "").strip()
    try:
        data = json.loads(body)
        body = str(data.get("detail") or data.get("error") or body)
    except ValueError:
        pass
    return f"HTTP {r.status_code}: {body[:300]}" if body else f"HTTP {r.status_code}"
