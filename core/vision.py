"""Bilderkennung: Bilder aus dem Chat oder dem Workspace für Modelle mit Vision vorbereiten.

Angehängte Bilder liegen unter ~/.coder/images, benannt nach ihrem Inhalt – so bleiben Chats klein und dasselbe Bild
wird nur einmal gespeichert. Ollama bekommt immer PNG oder JPEG, auf eine sinnvolle Größe verkleinert.
"""

import base64
import binascii
import hashlib
import io
import re
from pathlib import Path

from .config import HOME

IMAGES_DIR = HOME / "images"
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}
MAX_BYTES = 15 * 1024 * 1024
MAX_SIDE = 1568  # mehr Details erkennen die üblichen Vision-Modelle ohnehin nicht
ID_RX = re.compile(r"^[0-9a-f]{16}\.(png|jpg|gif|webp|bmp)$")

DESCRIBE_PROMPT = """Describe this image for a coding assistant that cannot see it.
- Transcribe all visible text exactly: code, error messages, log lines, labels, numbers.
- For screenshots of apps or websites: layout, components, colors, states and anything that looks broken.
- For diagrams: the elements and how they are connected.
Be precise and complete, no speculation. The user's request, for context:
{request}"""

_encoded: dict[str, str] = {}


def sniff(data: bytes) -> str | None:
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if data[:3] == b"\xff\xd8\xff":
        return "jpg"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    if data[:2] == b"BM":
        return "bmp"
    return None


def store(data: bytes) -> str:
    ext = sniff(data)
    if not ext:
        raise ValueError("Kein unterstütztes Bildformat – PNG, JPEG, GIF, WebP oder BMP.")
    if len(data) > MAX_BYTES:
        raise ValueError("Das Bild ist zu groß (höchstens 15 MB).")
    name = f"{hashlib.sha256(data).hexdigest()[:16]}.{ext}"
    IMAGES_DIR.mkdir(parents=True, exist_ok=True)
    path = IMAGES_DIR / name
    if not path.exists():
        path.write_bytes(data)
    return name


def store_base64(text: str) -> str:
    text = str(text or "").strip()
    if text.startswith("data:"):
        text = text.split(",", 1)[-1]  # data:image/png;base64,…
    try:
        data = base64.b64decode(text, validate=True)
    except (binascii.Error, ValueError) as e:
        raise ValueError("Das Bild kam beschädigt an.") from e
    return store(data)


def path_of(image_id: str) -> Path | None:
    if not isinstance(image_id, str) or not ID_RX.match(image_id):
        return None
    path = IMAGES_DIR / image_id
    return path if path.is_file() else None


def is_image(path: Path) -> bool:
    return path.suffix.lower() in IMAGE_EXT


def encode(path: Path) -> str:
    """Base64 für Ollama: PNG/JPEG, lange Seite höchstens MAX_SIDE Pixel."""
    key = f"{path}:{path.stat().st_mtime_ns}"
    if key in _encoded:
        return _encoded[key]
    data = path.read_bytes()
    if len(data) > MAX_BYTES:
        raise ValueError(f"{path.name} ist zu groß (höchstens 15 MB).")
    kind = sniff(data)
    if not kind:
        raise ValueError(f"{path.name} ist kein unterstütztes Bild.")
    try:
        from PIL import Image
        with Image.open(io.BytesIO(data)) as img:
            needs_resize = max(img.size) > MAX_SIDE
            if needs_resize or kind not in ("png", "jpg"):
                img.load()
                if needs_resize:
                    img.thumbnail((MAX_SIDE, MAX_SIDE))
                out = io.BytesIO()
                if img.mode in ("RGBA", "LA", "P"):
                    img.convert("RGBA").save(out, "PNG", optimize=True)
                else:
                    img.convert("RGB").save(out, "JPEG", quality=90)
                data = out.getvalue()
    except ImportError:
        if kind not in ("png", "jpg"):
            raise ValueError(f"{path.name}: {kind.upper()} geht nur mit Pillow (pip install pillow).")
    except OSError as e:
        raise ValueError(f"{path.name} lässt sich nicht öffnen: {e}") from e
    encoded = base64.b64encode(data).decode("ascii")
    if len(_encoded) > 32:
        _encoded.clear()
    _encoded[key] = encoded
    return encoded
