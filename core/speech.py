"""Sprechen statt tippen: Diktat mit Whisper – auf diesem Rechner, ohne Netz.

Aufgenommen wird hier im Programm (`sounddevice`, 16 kHz Mono – genau das, was Whisper hört), erkannt mit
`faster-whisper`. Beide sind eigene Pakete: Fehlen sie, gibt es den Knopf gar nicht erst, und die Einstellungen
zeigen, wie man sie nachrüstet. Heruntergeladen wird nichts von allein.

Das Erkennungsmodell liegt im Zwischenspeicher von Hugging Face. Geholt wird es erst, wenn du in den
Einstellungen darauf tippst – danach arbeitet es offline. Gerechnet wird standardmäßig auf der CPU: Die GPU
gehört dem Sprachmodell, und für ein paar Sekunden Sprache reicht der Prozessor allemal.

Aufgenommen wird dort, wo Coder läuft. Über das Netz bedient (mit `--host 0.0.0.0`) wäre das das falsche
Mikrofon – der Server bietet das Diktat deshalb nur dem an, der am selben Rechner sitzt.
"""

import importlib.util
import os
import re
import threading
import time
from pathlib import Path

SAMPLE_RATE = 16000  # womit Whisper rechnet – gleich so aufnehmen spart das Umrechnen
BLOCK = 1600  # 0,1 s: fein genug für den Pegelausschlag, grob genug für wenig Last
MAX_SECONDS = 300  # Notbremse, falls das Stoppen vergessen wird
MIN_SECONDS = 0.4  # kürzer ist ein Verklicken, kein Satz

# Die Whisper-Größen, die faster-whisper kennt. „mb“ ist der Platz auf der Platte – er steht in den Einstellungen,
# damit niemand aus Versehen drei Gigabyte zieht.
MODELS = (
    {"name": "tiny", "label": "Winzig", "mb": 75, "hint": "für kurze Notizen, versteht Deutsch nur ungefähr"},
    {"name": "base", "label": "Klein", "mb": 145, "hint": "schnell, für einfache Sätze"},
    {"name": "small", "label": "Mittel", "mb": 484, "hint": "guter Kompromiss – empfohlen für Deutsch"},
    {"name": "medium", "label": "Groß", "mb": 1530, "hint": "genauer, braucht spürbar länger auf der CPU"},
    {"name": "large-v3", "label": "Sehr groß", "mb": 3090, "hint": "das Beste, sinnvoll nur auf der Grafikkarte"},
)
MODEL_NAMES = tuple(m["name"] for m in MODELS)
VRAM_HEADROOM = 700 * 1024 * 1024  # so viel Luft muss neben dem Erkennungsmodell noch frei sein
PACKAGES = {"sounddevice": "sounddevice", "faster_whisper": "faster-whisper"}

# Fachwörter, die sonst als Alltagswörter ankommen („Commit“ → „Komitee“). Whisper nimmt den Satz als Vorlage.
PROMPT = {
    "de": "Wir sprechen über Programmieren: Python, JavaScript, Ollama, Coder, Commit, Repository, Branch, "
          "Funktion, Datei, Ordner, Test, Terminal, Bug, README, Workspace.",
    "en": "We are talking about programming: Python, JavaScript, Ollama, commit, repository, branch, function, "
          "file, folder, test, terminal, bug, README, workspace.",
}
# Was Whisper gern in die Stille hineinhört – kommt nur das, war da nichts.
GHOSTS = re.compile(r"^(untertitel(ung)?( des| von| im auftrag)?[^.]*\.?|vielen dank[.!]?|"
                    r"amara\.org[^.]*\.?|thanks? for watching[.!]?|copyright[^.]*\.?|\.{1,3}|musik|applaus)$", re.I)

_lock = threading.Lock()
_loaded: dict = {}  # (Modell, Gerät) → WhisperModel, einmal geladen bleibt es liegen


# ---------------------------------------------------------------------------- Was ist da?

def has(module: str) -> bool:
    try:
        return importlib.util.find_spec(module) is not None
    except (ImportError, ValueError):
        return False


def missing() -> list[str]:
    """Die Pakete, die für das Diktat fehlen – in der Schreibweise für pip."""
    return [pip for module, pip in PACKAGES.items() if not has(module)]


# Zum Rechnen auf der Grafikkarte braucht ctranslate2 die CUDA-Bibliotheken von NVIDIA. Eine Karte allein
# genügt nicht: Fehlen cuBLAS und cuDNN, fliegt der Fehler erst mitten im Erkennen. Deshalb vorher nachsehen.
CUDA_LIBS = (("cublas64_12.dll", "cublas64_11.dll"), ("cudnn64_9.dll", "cudnn64_8.dll")) if os.name == "nt" else \
    (("libcublas.so.12", "libcublas.so.11"), ("libcudnn.so.9", "libcudnn.so.8"))
CUDA_PIP = "pip install nvidia-cublas-cu12 nvidia-cudnn-cu12"
_cuda: dict = {}  # gemerkt: geht die Grafikkarte? Das ändert sich im laufenden Programm nicht mehr


def _nvidia_dirs() -> None:
    """Die CUDA-Bibliotheken aus den nvidia-*-Paketen findet Windows nur, wenn man ihren Ordner dazusagt."""
    if os.name != "nt" or _cuda.get("paths"):
        return
    _cuda["paths"] = True
    try:
        import nvidia
        for root in nvidia.__path__:
            for sub in Path(root).glob("*/bin"):
                if sub.is_dir():
                    os.add_dll_directory(str(sub))
    except Exception:  # noqa: BLE001 – ohne die Pakete bleibt es beim Systempfad
        pass


def cuda_ready() -> bool:
    """Karte da *und* die Bibliotheken ladbar – sonst rechnet der Prozessor."""
    if "ok" in _cuda:
        return _cuda["ok"]
    _cuda["ok"] = False
    if has("ctranslate2") and not _cuda.get("broken"):
        try:
            import ctypes
            import ctranslate2
            if ctranslate2.get_cuda_device_count() > 0:
                _nvidia_dirs()
                _cuda["ok"] = all(any(_loadable(ctypes, n) for n in names) for names in CUDA_LIBS)
        except Exception:  # noqa: BLE001 – ohne CUDA-Laufzeit wirft ctranslate2 schon beim Zählen
            pass
    return _cuda["ok"]


def _loadable(ctypes, name: str) -> bool:
    try:
        (ctypes.WinDLL if os.name == "nt" else ctypes.CDLL)(name)
        return True
    except OSError:
        return False


def cuda_broken(message: str) -> None:
    """Die Grafikkarte hat mitten im Erkennen aufgegeben – ab jetzt rechnet der Prozessor."""
    _cuda.update({"ok": False, "broken": message})
    unload()


def repo_of(name: str) -> str:
    """Das Hugging-Face-Repository zur Größe – so heißen sie seit faster-whisper 1.0.

    Bewusst ohne Import von faster_whisper: Das Paket zieht ctranslate2, tokenizers und av mit und braucht
    dafür mehrere Sekunden. Zum Nachsehen, ob ein Modell schon da ist, reicht der Name.
    """
    return f"Systran/faster-whisper-{name}"


def model_path(name: str) -> str | None:
    """Wo das Modell liegt – oder None, wenn es noch geholt werden muss. Fragt nie das Netz.

    Nachgesehen wird direkt im Zwischenspeicher. Der Weg über huggingface_hub dauert je Größe über eine
    Sekunde, und die Einstellungen fragen nach allen fünf – das hielte das Diktat jedes Mal auf.
    """
    if name not in MODEL_NAMES:
        return None
    snapshots = cache_root() / ("models--" + repo_of(name).replace("/", "--")) / "snapshots"
    try:
        for snap in snapshots.iterdir():
            if (snap / "model.bin").is_file() and (snap / "config.json").is_file():
                return str(snap)
    except OSError:  # den Ordner gibt es noch nicht
        pass
    return None


def models_state() -> list[dict]:
    return [{**m, "ready": bool(model_path(m["name"]))} for m in MODELS]


def inputs() -> list[dict]:
    """Die Mikrofone dieses Rechners. Ohne sounddevice oder ohne Gerät: eine leere Liste."""
    if not has("sounddevice"):
        return []
    try:
        import sounddevice as sd
        try:
            default_in = int(sd.default.device[0])
        except (TypeError, ValueError, IndexError):
            default_in = -1
        found, seen = [], set()
        for index, dev in enumerate(sd.query_devices()):
            name = str(dev.get("name") or f"Gerät {index}").strip()
            # PortAudio zählt dasselbe Mikrofon einmal je Audio-Schnittstelle (MME, DirectSound, WASAPI …).
            # In der Auswahl steht es nur einmal – die erste Fassung ist die, die Windows selbst nimmt.
            if dev.get("max_input_channels", 0) > 0 and name.lower() not in seen:
                seen.add(name.lower())
                found.append({"index": index, "name": name, "default": index == default_in})
        return found
    except Exception:  # noqa: BLE001 – ohne Audiodienst wirft PortAudio beim Abfragen
        return []


def input_index(cfg: dict):
    """Der Index des eingestellten Mikrofons – None heißt: das, was das System ohnehin nimmt."""
    want = str(cfg.get("speech_input") or "").strip().lower()
    if not want:
        return None
    return next((m["index"] for m in inputs() if m["name"].lower() == want), None)


def model_name(cfg: dict) -> str:
    name = str(cfg.get("speech_model") or "small")
    return name if name in MODEL_NAMES else "small"


def gpu_room_for(name: str) -> bool:
    """Passt das Erkennungsmodell gerade auf die Grafikkarte, ohne dem Sprachmodell wehzutun?"""
    if not cuda_ready():
        return False
    from .optimizer import detect_hardware
    need = next(m["mb"] for m in MODELS if m["name"] == name) * 1024 * 1024
    return detect_hardware().get("vram_free", 0) >= need + VRAM_HEADROOM


def device_name(cfg: dict) -> str:
    """Wo gerechnet wird. „Automatisch“ nimmt die Grafikkarte nur, wenn dort im Moment Platz ist –
    ein großes Sprachmodell im VRAM hat Vorrang, das Diktat wandert dann auf die CPU."""
    want = str(cfg.get("speech_device") or "auto")
    if want == "cuda":
        return "cuda" if cuda_ready() else "cpu"
    if want == "auto":
        return "cuda" if gpu_room_for(model_name(cfg)) else "cpu"
    return "cpu"


def blocked(cfg: dict) -> str:
    """Was dem Diktat gerade im Weg steht – leer heißt: los geht's.

    Bewusst ohne die Frage nach der Grafikkarte: Die kostet beim ersten Mal ein paar Sekunden, und bis der
    Ton erkannt wird, ist sie längst beantwortet. Aufnehmen soll sofort losgehen.
    """
    fehlt = missing()
    if fehlt:
        return "Es fehlt: " + " und ".join(fehlt)
    if not inputs():
        return "Kein Mikrofon gefunden."
    if not model_path(model_name(cfg)):
        return "Das Erkennungsmodell ist noch nicht geladen."
    return ""


def status(cfg: dict) -> dict:
    """Alles, was die Einstellungen über das Diktat wissen müssen – und woran es gerade hakt."""
    fehlt = missing()
    name = model_name(cfg)
    mics = inputs()
    ready = not fehlt and bool(mics) and bool(model_path(name))
    if fehlt:
        note = "Es fehlt: " + " und ".join(fehlt)
    elif not mics:
        note = "Kein Mikrofon gefunden."
    elif not model_path(name):
        note = "Das Erkennungsmodell ist noch nicht geladen."
    else:
        dev = "der Grafikkarte" if device_name(cfg) == "cuda" else "dem Prozessor"
        note = f"Bereit – {dict((m['name'], m['label']) for m in MODELS)[name]} auf {dev}."
    # Eine Karte ohne CUDA-Bibliotheken: Coder rechnet still auf der CPU weiter, sagt aber, was helfen würde.
    gpu_hint = ""
    if str(cfg.get("speech_device")) == "cuda" and not cuda_ready():
        gpu_hint = ("Für die Grafikkarte fehlen die CUDA-Bibliotheken – solange rechnet der Prozessor."
                    if not _cuda.get("broken") else "Die Grafikkarte hat abgelehnt – es rechnet der Prozessor.")
    return {"ok": ready, "missing": fehlt, "note": note, "model": name, "device": device_name(cfg),
            "cuda": cuda_ready(), "gpu_hint": gpu_hint, "gpu_install": CUDA_PIP if gpu_hint else "",
            "language": str(cfg.get("speech_language") or "de"),
            "models": models_state(), "inputs": mics,
            "install": "pip install " + " ".join(fehlt) if fehlt else ""}


# ---------------------------------------------------------------------------- Aufnehmen

class Recorder:
    """Nimmt vom Mikrofon auf, bis gestoppt wird – und sagt nebenbei, wie laut es gerade ist.

    Die Blöcke sammelt der Audio-Thread von PortAudio; gelesen wird aus dem Server-Thread. Deshalb hängt
    alles an einem Schloss und der Pegel ist eine einfache Zahl, die der Audio-Thread nur überschreibt.
    """

    def __init__(self) -> None:
        self.stream = None
        self.blocks: list = []
        self.level = 0.0
        self.started = 0.0
        self.error = ""
        self._lock = threading.Lock()

    @property
    def active(self) -> bool:
        return self.stream is not None

    @property
    def seconds(self) -> float:
        with self._lock:
            frames = sum(len(b) for b in self.blocks)
        return frames / SAMPLE_RATE

    def _callback(self, indata, _frames, _time, state) -> None:
        if state:  # Überlauf heißt: ein Stück fehlt. Das ist ärgerlich, aber kein Grund abzubrechen.
            pass
        block = indata[:, 0].copy()
        with self._lock:
            self.blocks.append(block)
        peak = float(abs(block).max()) if len(block) else 0.0
        self.level = peak if peak > self.level else self.level * 0.6 + peak * 0.4  # schnell hoch, langsam runter

    def start(self, device=None) -> None:
        import numpy  # noqa: F401 – sounddevice braucht es; fehlt es, fliegt der ImportError hier
        import sounddevice as sd
        if self.active:
            return
        with self._lock:
            self.blocks = []
        self.level, self.error, self.started = 0.0, "", time.monotonic()
        self.stream = sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype="float32", blocksize=BLOCK,
                                     device=device, callback=self._callback)
        self.stream.start()

    def stop(self):
        """Beendet die Aufnahme und gibt den Ton zurück – oder None, wenn nichts aufgenommen wurde."""
        import numpy as np
        stream, self.stream = self.stream, None
        if stream is not None:
            try:
                stream.stop()
                stream.close()
            except Exception as e:  # noqa: BLE001 – ein abgezogenes Mikrofon soll nur die Aufnahme kosten
                self.error = str(e)
        with self._lock:
            blocks, self.blocks = self.blocks, []
        self.level = 0.0
        return np.concatenate(blocks) if blocks else None

    def cancel(self) -> None:
        self.stop()


# ---------------------------------------------------------------------------- Erkennen

def load(name: str, device: str):
    """Das Modell in den Speicher – einmal je Größe und Gerät, danach liegt es bereit."""
    from faster_whisper import WhisperModel
    key = (name, device)
    with _lock:
        model = _loaded.get(key)
        if model is None:
            # int8 auf der CPU ist mehrfach schneller und hört sich für Diktatlängen nicht schlechter an.
            model = WhisperModel(name, device=device, compute_type="float16" if device == "cuda" else "int8",
                                 local_files_only=True)
            _loaded[key] = model
    return model


def unload() -> None:
    with _lock:
        _loaded.clear()


def clean(text: str) -> str:
    """Whisper hört in Stille gern Untertitel-Abspänne. Bleibt nur so etwas übrig, war da nichts."""
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    parts = [p for p in re.split(r"(?<=[.!?]) ", text) if p.strip()]
    keep = [p for p in parts if not GHOSTS.match(p.strip().strip("♪ "))]
    return " ".join(keep).strip() if keep else ""


def transcribe(audio, cfg: dict) -> dict:
    """Ton zu Text. Läuft in einem eigenen Thread – das Modell rechnet Sekunden."""
    name = model_name(cfg)
    language = str(cfg.get("speech_language") or "de")
    began = time.monotonic()

    def run(device: str) -> tuple[str, object]:
        model = load(name, device)
        segments, info = model.transcribe(
            audio, language=None if language == "auto" else language, beam_size=1, vad_filter=True,
            condition_on_previous_text=False, initial_prompt=PROMPT.get(language if language != "auto" else "de"),
            temperature=0.0)
        return clean(" ".join(s.text for s in segments)), info  # erst hier rechnet Whisper wirklich

    device = device_name(cfg)
    try:
        text, info = run(device)
    except RuntimeError as e:
        # Eine Karte ohne cuBLAS/cuDNN meldet sich erst hier. Dann eben auf dem Prozessor – und künftig gleich.
        if device != "cuda":
            raise
        cuda_broken(str(e))
        device = "cpu"
        text, info = run(device)
    if device == "cuda":
        # Der VRAM gehört dem Sprachmodell: Nach dem Diktat geben wir ihn gleich wieder her. Das nächste Mal
        # liegt das Modell noch im Dateicache des Systems und ist in ungefähr einer Sekunde wieder da.
        unload()
    return {"text": text, "model": name, "device": device, "language": getattr(info, "language", language),
            "seconds": len(audio) / SAMPLE_RATE, "took": round(time.monotonic() - began, 2)}


# ---------------------------------------------------------------------------- Modell holen

def _file_bytes(f: Path) -> int:
    """Wie groß die Datei gerade ist. Bei halbfertigen Downloads steht das in der Ordnerliste zu selten –
    ein kurzer Blick ans Dateiende sagt die Wahrheit, sonst hinge der Fortschritt minutenlang fest."""
    try:
        if f.suffix == ".incomplete":
            with open(f, "rb") as fh:
                return fh.seek(0, 2)
        return f.stat().st_size
    except OSError:
        return 0


def _cache_bytes(root: Path) -> int:
    try:
        return sum(_file_bytes(f) for f in root.rglob("*") if f.is_file())
    except OSError:
        return 0


def cache_root() -> Path:
    raw = os.environ.get("HF_HUB_CACHE") or os.environ.get("HUGGINGFACE_HUB_CACHE")
    if raw:
        return Path(raw)
    home = os.environ.get("HF_HOME")
    return (Path(home) / "hub") if home else (Path.home() / ".cache" / "huggingface" / "hub")


# Dieselben Dateien, die auch faster-whisper holt – mehr liegt im Repository nicht, was wir brauchen.
ALLOW = ["config.json", "preprocessor_config.json", "model.bin", "tokenizer.json", "vocabulary.*"]


def download(name: str, on_progress=None) -> str:
    """Holt ein Modell – nur auf ausdrücklichen Wunsch.

    Den Fortschritt liefert der Fortschrittsbalken von Hugging Face selbst: faster-whisper schaltet ihn ab,
    deshalb rufen wir den Download hier direkt auf und schieben einen eigenen Balken unter. Geht daran etwas
    schief, lädt am Ende der gewohnte Weg – dann eben ohne Prozente.
    """
    from faster_whisper.utils import _MODELS, download_model
    if name not in MODEL_NAMES:
        raise ValueError(f"Unbekannte Größe: {name}")
    if on_progress is None:
        return download_model(name)
    guess = next(m["mb"] for m in MODELS if m["name"] == name) * 1024 * 1024
    seen = {"done": 0, "total": 0}
    try:
        import huggingface_hub
        from huggingface_hub.utils import tqdm as hf_tqdm

        class Bar(hf_tqdm):
            """Hugging Face zählt die Bytes in einem Balken, die Dateien in einem zweiten – uns interessieren
            die Bytes. Die Einheit merken wir uns aus den Argumenten: Ein abgeschalteter Balken hat keine."""

            def __init__(self, *a, **kw):
                self.bytes_bar = kw.get("unit") == "B"
                super().__init__(*a, **kw)

            def update(self, n=1):
                if self.bytes_bar:
                    seen["done"] += n or 0
                    seen["total"] = max(seen["total"], getattr(self, "total", 0) or 0)
                    # Solange Hugging Face die Größe nicht nennt, rechnen wir mit der bekannten aus MODELS.
                    on_progress(seen["done"], max(seen["total"] or guess, seen["done"]))
                try:
                    return super().update(n)
                except AttributeError:  # ein abgeschalteter Balken hat nichts zum Zeichnen
                    return None

        path = huggingface_hub.snapshot_download(_MODELS[name], allow_patterns=ALLOW, tqdm_class=Bar)
    except Exception:  # noqa: BLE001 – andere Version, anderer Weg: lieber ohne Prozente als gar nicht
        path = download_model(name)
    total = seen["total"] or guess
    on_progress(total, total)
    return path
