"""Persistente Einstellungen unter ~/.coder/config.json."""

import json
import os
import re
from pathlib import Path

from . import personal
from .power import mode as awake_mode

HOME = Path(os.environ.get("CODER_HOME", Path.home() / ".coder"))
CONFIG_PATH = HOME / "config.json"
SESSIONS_DIR = HOME / "sessions"
APP_DIR = Path(__file__).resolve().parent.parent

# chat: nur reden und nachschlagen · ask (Normal): fragt vor Änderungen · auto-edit · plan · yolo (Autonom)
PERMISSION_MODES = ("chat", "ask", "auto-edit", "plan", "yolo")
EFFORTS = ("low", "medium", "high", "max")
# Farbthemen der Oberfläche – „standard“ lässt jedem Design seine eigenen Farben.
PALETTES = ("standard", "nord", "solarized", "gruvbox", "github", "catppuccin", "tokyo", "rosepine", "oled",
            "kontrast", "farbenblind")
CLI_THEMES = ("auto", "dunkel", "hell", "farbenblind", "farbenblind-hell", "schlicht")
# Modell-Server: Ollama oder ein OpenAI-kompatibler vLLM-Server mit denselben Modellen.
BACKENDS = ("ollama", "vllm")
# Diktat: Whisper-Größen (core/speech.py hat die Details), Rechenwerk und Sprache.
SPEECH_MODELS = ("tiny", "base", "small", "medium", "large-v3")
SPEECH_DEVICES = ("auto", "cpu", "cuda")
SPEECH_LANGUAGES = ("de", "en", "auto")


def normalize_path(raw: str | Path) -> Path:
    """Nimmt Pfade so, wie man sie einfügt: in Anführungszeichen („Als Pfad kopieren“), mit ~ oder %VARIABLEN%.

    Relative Angaben gelten ab dem Benutzerordner – das Arbeitsverzeichnis von Coder ist dafür kein sinnvoller Anker.
    """
    text = os.path.expandvars(os.path.expanduser(str(raw).strip().strip("\"'").strip()))
    if re.fullmatch(r"[A-Za-z]:", text):
        text += "\\"  # „D:“ meint das Laufwerk, nicht dessen letztes Arbeitsverzeichnis
    path = Path(text)
    if not path.is_absolute():
        path = Path.home() / path
    return path.resolve()


def blocked_workspace(path: str | Path) -> str | None:
    """Warum ein Ordner kein Workspace sein darf – oder None.

    Systemordner könnte der Agent beschädigen, und auf einer ganzen Laufwerkswurzel dauert jede Suche ewig.
    """
    try:
        p = Path(path).resolve()
    except (OSError, ValueError):
        return "ungültiger Pfad"
    system_root = Path(os.environ.get("SystemRoot", "C:/Windows")).resolve()
    if p == system_root or system_root in p.parents:
        return "Systemordner von Windows"
    if p == Path(p.anchor):
        return "ganze Laufwerkswurzel"
    return None


def _default_workspace() -> str:
    # Per Doppelklick gestartet ist das Arbeitsverzeichnis oft Coder selbst oder system32 – dann der Benutzerordner.
    try:
        cwd = Path.cwd().resolve()
    except OSError:
        return str(Path.home())
    return str(Path.home() if cwd == APP_DIR or blocked_workspace(cwd) else cwd)


DEFAULTS = {
    # Womit Coder redet: "ollama" oder "vllm" (OpenAI-kompatibel, nutzt dieselben GGUF-Dateien – core/vllm.py).
    "backend": "ollama",
    "ollama_url": "http://localhost:11434",
    "vllm_url": "",  # leer: 127.0.0.1 auf Port 8000, dann 8001
    "model": "",
    "workspace": _default_workspace(),
    "permission_mode": "ask",
    # Wie lange das Modell nach der letzten Anfrage im VRAM bleibt.
    "keep_alive": "30m",
    # 0 = automatisch aus VRAM und Modellarchitektur berechnen.
    "num_ctx": 0,
    # Obergrenze für die Auto-Berechnung: größerer Kontext = langsameres Prompt-Processing.
    "max_auto_ctx": 32768,
    # KV-Cache-Typ, mit dem der Ollama-Server läuft (OLLAMA_KV_CACHE_TYPE). Nur für die Schätzung.
    "kv_cache_type": "auto",
    "temperature": None,
    "think": False,
    # Aufwand: wie gründlich der Agent arbeitet – Denkmodus, Schrittlimit, Kontrolle, Arbeitsweise (core/effort.py).
    "effort": "medium",
    "max_steps": 50,
    "max_tool_output": 16000,
    "command_timeout": 120,
    "unload_others": True,
    # Coder darf Teilaufgaben an Sub-Agents abgeben.
    "subagents": True,
    # Agents und Slash-Befehle aus Claude Code (~/.claude) mit anbieten.
    "claude_extensions": True,
    # Gedächtnis: verknüpfte Notizen, die der Agent über Chats hinweg liest und schreibt.
    "memory": True,
    # Passende Notizen automatisch zur Nachricht holen und erledigte Aufgaben in der Notiz „Verlauf“ festhalten.
    "auto_recall": True,
    "journal": True,
    # Kontrolle: ein zweites Modell prüft und testet das Ergebnis und schickt den Agent weiter, bis es passt.
    "controller": True,
    "controller_model": "",  # leer: automatisch – Mistral, falls installiert, sonst das Hauptmodell
    "controller_rounds": 2,
    "controller_interval": 10,  # Minuten zwischen Prüfungen bei langen Aufgaben; 0 = nur am Ende
    # Watchdog: kommt so viele Sekunden nichts vom Modell und die GPU ruht, wird es neu geladen. 0 = aus.
    "watchdog": 180,
    # Bilderkennung für Modelle ohne eigene Vision. Leer: automatisch.
    "vision_model": "",
    # Bilder erzeugen mit einem lokalen Dienst (ComfyUI, Automatic1111, Forge, SD.Next): "auto" sucht ihn selbst,
    # "off" schaltet das Werkzeug ab. image_url ist eine eigene Adresse, image_model der Checkpoint.
    "image_backend": "auto",
    "image_url": "",
    "image_model": "",
    "image_size": 0,  # 0 = passend zum Modell (512 bei SD 1.5, 1024 bei SDXL und Flux)
    "image_steps": 25,
    # Kein Standby: "open" solange Coder offen ist, "work" während der Agent arbeitet, "off" nie.
    "keep_awake": "open",
    # Aussehen: "ruhig" (weiche Flächen), "terminal" (Monospace, dicht) oder "papier" (Serife, zum Lesen).
    "design": "ruhig",
    # Hell oder dunkel: "auto" folgt dem System, sonst "light" oder "dark".
    "theme": "auto",
    # Farbthema der Oberfläche (PALETTES) – gilt in jedem Design.
    "palette": "standard",
    # Farben im Terminalmodus: "auto" nimmt dunkel, außer das Terminal meldet einen hellen Grund (COLORFGBG).
    "cli_theme": "auto",
    # Name im Kopf des Berichts zum Ausdrucken. Leer: eine Linie zum Ausfüllen.
    "report_author": "",
    # Prepromter: den Auftrag vor dem Senden schärfen lassen. Du siehst das Ergebnis immer vorher.
    "preprompt": True,
    # Ergänzen in der Dateiansicht: der graue Vorschlag hinter dem Cursor (core/complete.py).
    # Ohne eigenes Modell ergänzt das Hauptmodell – aber nur, wenn es ohnehin im Speicher liegt.
    "complete": True,
    "complete_model": "",
    # Cowork: mehrere Aufträge gleichzeitig im Workspace (core/cowork.py). So viele laufen parallel.
    "cowork_parallel": 2,
    # Diktat: sprechen statt tippen (core/speech.py). Das Erkennungsmodell wird nur auf Knopfdruck geholt.
    "speech": True,
    "speech_model": "small",
    "speech_device": "auto",  # Grafikkarte nur, wenn dort gerade Platz ist - sonst Prozessor
    "speech_language": "de",
    "speech_input": "",  # leer: das Mikrofon, das Windows ohnehin nimmt
    # Chat-Tab: reden und recherchieren ohne Projekt. Leer: das Hauptmodell.
    "talk_model": "",
    # Eigene Anweisungen (User-Prompt, core/personal.py): gilt überall, dazu je ein Feld nur für Code und nur für Chat.
    "user_prompt": "",
    "user_prompt_code": "",
    "user_prompt_talk": "",
    # Antwortstil: normal, knapp, ausfuehrlich, lernen, formell. Normal ändert nichts am Prompt.
    "style": "normal",
    # Freigabe für andere (core/users.py): die Adresse, unter der Coder von außen erreichbar ist – etwa die
    # weitergeleitete Adresse aus VS Code. Nur für die Einladungslinks; leer: die zuletzt gesehene Tunnel-Adresse.
    "public_url": "",
}


def _choices(cfg: dict) -> dict:
    """Werte mit fester Auswahl: Unbekanntes – etwa von einer älteren Oberfläche – fällt auf den Standard zurück."""
    for key, allowed in (("permission_mode", PERMISSION_MODES), ("effort", EFFORTS), ("palette", PALETTES),
                         ("backend", BACKENDS), ("style", personal.STYLES),
                         ("cli_theme", CLI_THEMES), ("speech_model", SPEECH_MODELS),
                         ("speech_device", SPEECH_DEVICES), ("speech_language", SPEECH_LANGUAGES)):
        if cfg.get(key) not in allowed:
            cfg[key] = DEFAULTS[key]
    # Wie viele Cowork-Aufträge gleichzeitig laufen: mehr als vier bringt auf einer Grafikkarte nichts.
    try:
        cfg["cowork_parallel"] = max(1, min(4, int(cfg.get("cowork_parallel", 2))))
    except (TypeError, ValueError):
        cfg["cowork_parallel"] = DEFAULTS["cowork_parallel"]
    for key in personal.KEYS:
        cfg[key] = personal.clean(cfg.get(key))
    return cfg


def load() -> dict:
    cfg = dict(DEFAULTS)
    try:
        cfg.update(json.loads(CONFIG_PATH.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        pass
    _choices(cfg)
    cfg["keep_awake"] = awake_mode(cfg.get("keep_awake"))  # früher an/aus – „an“ heißt jetzt: solange Coder offen ist
    workspace = str(cfg.get("workspace") or "")
    if not workspace or blocked_workspace(workspace) or not Path(workspace).is_dir():
        cfg["workspace"] = str(Path.home())
    return cfg


def save(cfg: dict) -> None:
    HOME.mkdir(parents=True, exist_ok=True)
    clean = {k: cfg[k] for k in DEFAULTS if k in cfg}
    tmp = CONFIG_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(clean, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(CONFIG_PATH)


def update(changes: dict) -> dict:
    cfg = load()
    for key, value in changes.items():
        if key in DEFAULTS:
            cfg[key] = value
    _choices(cfg)
    save(cfg)
    return cfg
