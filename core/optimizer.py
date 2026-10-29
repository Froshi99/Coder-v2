"""Hardware-Erkennung und Ladeplanung für Ollama-Modelle.

Berechnet aus freiem VRAM, Dateigröße und Architektur (Layer, KV-Heads,
Head-Dimension) den größten Kontext, der ohne CPU-Offload in die GPU passt.
Nach dem Laden wird die Schätzung mit /api/ps gegen die Realität geprüft.

Große Modelle (30B bis 120B und mehr) passen nie ganz in den VRAM. Deshalb zählt der Plan auch den freien
Arbeitsspeicher mit und ordnet jedes Modell in eine von drei Lagen ein: ganz auf der GPU, geteilt zwischen GPU und
RAM – oder so groß, dass Ollama ständig von der Platte nachlesen muss. Dazu kommt eine grobe Tempo-Schätzung aus
den *aktiven* Parametern: Ein Mixture-of-Experts-Modell wie gpt-oss:120b rechnet je Token nur mit rund 5 der
117 Milliarden Parameter und läuft deshalb auch geteilt noch brauchbar, während ein dichtes 70B-Modell zäh wird.
"""

import ctypes
import os
import platform
import re
import shutil
import subprocess
import time

GB = 1024 ** 3
MB = 1024 ** 2

CTX_STEPS = [4096, 8192, 12288, 16384, 24576, 32768, 49152, 65536, 98304, 131072]
MIN_AGENT_CTX = 8192  # System-Prompt + Tool-Schemas + etwas Verlauf
KV_FACTOR = {"f16": 1.0, "q8_0": 0.5, "q4_0": 0.25}

# Speicherbandbreite in Byte/s – daraus wird das Tempo geschätzt. Je Token liest die Rechnung alle aktiven
# Gewichte einmal; wo sie liegen, entscheidet, wie lange das dauert. Grobe Mittelwerte, kein Messwert.
BW_GPU = 300e9        # typische Mittelklasse-GPU (RTX 3060: 360 GB/s, 4060: 270, 4090: 1000)
BW_GPU_UNIFIED = 150e9  # Apple Silicon
BW_RAM = 45e9         # Dual-Channel DDR4/DDR5
BW_DISK = 2.5e9       # NVMe-SSD, von der Ollama Gewichte nachliest (mmap)
TOKEN_OVERHEAD = 0.015  # Sekunden je Token für alles außer Gewichte lesen
DENSE_SHARE = 0.1     # Anteil der Gewichte, der bei MoE immer aktiv ist, wenn wir ihn nicht ausrechnen können
RAM_USABLE = 0.85     # so viel vom freien RAM darf Ollama wirklich belegen
SLOW_TPS = 2.0        # darunter fühlt sich ein Agent kaum noch benutzbar an

_hw_cache: tuple[float, dict] | None = None


# --------------------------------------------------------------------------- Hardware

def detect_hardware(max_age: float = 5.0) -> dict:
    global _hw_cache
    if _hw_cache and time.monotonic() - _hw_cache[0] < max_age:
        return _hw_cache[1]
    hw = {
        "os": platform.system(),
        "cpu": _cpu_name(),
        "cores": _physical_cores(),
        "ram_total": _ram_total(),
        "ram_free": _ram_free(),
        "gpus": _nvidia_gpus(),
        "unified_memory": False,
    }
    if not hw["ram_free"]:
        hw["ram_free"] = int(hw["ram_total"] * 0.6)  # ohne Messung vorsichtig schätzen
    if not hw["gpus"] and hw["os"] == "Darwin" and platform.machine() == "arm64":
        # Apple Silicon: Metal darf standardmäßig ca. 2/3 bis 3/4 des RAMs nutzen.
        total = hw["ram_total"]
        hw["gpus"] = [{"name": "Apple Silicon GPU", "total": int(total * 0.70), "free": int(total * 0.65)}]
        hw["unified_memory"] = True
    hw["vram_total"] = sum(g["total"] for g in hw["gpus"])
    hw["vram_free"] = sum(g["free"] for g in hw["gpus"])
    _hw_cache = (time.monotonic(), hw)
    return hw


def _nvidia_gpus() -> list[dict]:
    exe = shutil.which("nvidia-smi")
    if not exe:
        return []
    try:
        out = subprocess.run(
            [exe, "--query-gpu=name,memory.total,memory.free", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    gpus = []
    for line in out.strip().splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) == 3 and parts[1].isdigit():
            gpus.append({"name": parts[0], "total": int(parts[1]) * MB, "free": int(parts[2]) * MB})
    return gpus


def gpu_utilization() -> int | None:
    """Auslastung der GPU in Prozent (höchster Wert aller Karten) – None ohne nvidia-smi."""
    exe = shutil.which("nvidia-smi")
    if not exe:
        return None
    try:
        out = subprocess.run([exe, "--query-gpu=utilization.gpu", "--format=csv,noheader,nounits"],
                             capture_output=True, text=True, timeout=5,
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout
        values = [int(v) for v in re.findall(r"\d+", out)]
        return max(values) if values else None
    except (OSError, subprocess.SubprocessError):
        return None


def _ram_free() -> int:
    """Wirklich freier Arbeitsspeicher – was Ollama für ausgelagerte Schichten nutzen kann."""
    system = platform.system()
    try:
        if system == "Windows":
            class MEMSTAT2(ctypes.Structure):
                _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                            ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                            ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                            ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                            ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
            stat = MEMSTAT2()
            stat.dwLength = ctypes.sizeof(MEMSTAT2)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat))
            return int(stat.ullAvailPhys)
        if system == "Darwin":
            out = subprocess.run(["vm_stat"], capture_output=True, text=True).stdout
            size = int(re.search(r"page size of (\d+)", out).group(1))
            pages = sum(int(m) for m in re.findall(r"Pages (?:free|inactive|speculative):\s+(\d+)", out))
            return pages * size
        with open("/proc/meminfo") as f:
            text = f.read()
        hit = re.search(r"MemAvailable:\s+(\d+)", text) or re.search(r"MemFree:\s+(\d+)", text)
        return int(hit.group(1)) * 1024 if hit else 0
    except Exception:
        return 0


def _ram_total() -> int:
    system = platform.system()
    try:
        if system == "Windows":
            class MEMSTAT(ctypes.Structure):
                _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                            ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                            ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                            ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                            ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
            stat = MEMSTAT()
            stat.dwLength = ctypes.sizeof(MEMSTAT)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat))
            return int(stat.ullTotalPhys)
        if system == "Darwin":
            return int(subprocess.run(["sysctl", "-n", "hw.memsize"], capture_output=True, text=True).stdout)
        with open("/proc/meminfo") as f:
            return int(re.search(r"MemTotal:\s+(\d+)", f.read()).group(1)) * 1024
    except Exception:
        return 0


def _physical_cores() -> int:
    try:
        import psutil  # optional
        return psutil.cpu_count(logical=False) or os.cpu_count() or 1
    except ImportError:
        return max(1, (os.cpu_count() or 2) // 2)


def _cpu_name() -> str:
    name = platform.processor()
    if platform.system() == "Windows":
        try:
            import winreg
            key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\CentralProcessor\0")
            name = winreg.QueryValueEx(key, "ProcessorNameString")[0]
        except OSError:
            pass
    return re.sub(r"\s+", " ", name or platform.machine()).strip()


def server_env() -> dict:
    """Ollama-Umgebungsvariablen (Prozess + unter Windows die Benutzer-Variablen)."""
    keys = ["OLLAMA_FLASH_ATTENTION", "OLLAMA_KV_CACHE_TYPE", "OLLAMA_NUM_PARALLEL", "OLLAMA_MAX_LOADED_MODELS"]
    env = {k: os.environ.get(k) for k in keys}
    if platform.system() == "Windows":
        try:
            import winreg
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment")
            for k in keys:
                if not env[k]:
                    try:
                        env[k] = winreg.QueryValueEx(key, k)[0]
                    except OSError:
                        pass
        except OSError:
            pass
    return env


# --------------------------------------------------------------------------- Modellprofil

def model_profile(show: dict, size: int) -> dict:
    info = show.get("model_info") or {}
    arch = info.get("general.architecture", "")

    def g(key, default=None):
        return info.get(f"{arch}.{key}", default)

    def scalar(v, default=0):
        if isinstance(v, list):
            vals = [x for x in v if isinstance(x, (int, float))]
            return max(vals) if vals else default
        return v if isinstance(v, (int, float)) else default

    layers = scalar(g("block_count"), 0)
    n_embd = scalar(g("embedding_length"), 0)
    n_head = scalar(g("attention.head_count"), 0)
    n_head_kv = scalar(g("attention.head_count_kv"), n_head) or n_head
    key_len = scalar(g("attention.key_length"), 0) or (n_embd // n_head if n_head else 128)
    val_len = scalar(g("attention.value_length"), 0) or key_len
    ctx_max = scalar(g("context_length"), 0) or _ctx_from_details(show) or 8192

    kv_layers = max(1, layers - scalar(g("attention.shared_kv_layers"), 0))
    per_token = 2 * kv_layers * n_head_kv * (key_len + val_len)  # f16: 2 Bytes je Element
    sliding = scalar(g("attention.sliding_window"), 0)

    experts = int(scalar(g("expert_count"), 0))
    experts_used = int(scalar(g("expert_used_count"), 0))
    params = int(scalar(info.get("general.parameter_count"), 0)) or _params_from_details(show)
    active = _active_params(params, layers, n_embd, n_head, n_head_kv, key_len, val_len,
                            experts, experts_used, int(scalar(g("expert_feed_forward_length"), 0)))

    return {
        "arch": arch,
        "param_size": show.get("details", {}).get("parameter_size", ""),
        "quant": show.get("details", {}).get("quantization_level", ""),
        "size": size,
        "layers": layers,
        "ctx_max": int(ctx_max),
        "kv_per_token_f16": int(per_token),
        "sliding_window": int(sliding),
        "capabilities": show.get("capabilities") or [],
        "moe": bool(experts),
        "experts": experts,
        "experts_used": experts_used,
        "params": int(params),
        "active_params": int(active),
        # Wie viel der Gewichte je Token wirklich gelesen wird – bei MoE ein Bruchteil.
        "active_ratio": round(active / params, 4) if params and active else 1.0,
        "active_bytes": int(size * (active / params)) if params and active else int(size),
    }


def _params_from_details(show: dict) -> int:
    """„117B“ oder „14.8B“ aus den Modelldetails in eine Zahl."""
    text = str(show.get("details", {}).get("parameter_size") or "")
    hit = re.fullmatch(r"\s*([\d.]+)\s*([BMK])\s*", text, re.I)
    if not hit:
        return 0
    factor = {"k": 1e3, "m": 1e6, "b": 1e9}[hit.group(2).lower()]
    return int(float(hit.group(1)) * factor)


def _active_params(params: int, layers: int, n_embd: int, n_head: int, n_head_kv: int, key_len: int, val_len: int,
                   experts: int, experts_used: int, expert_ffn: int) -> int:
    """Parameter, die ein Token wirklich anfasst. Dichte Modelle: alle. MoE: Aufmerksamkeit plus die paar Experten.

    Bei gpt-oss:120b kommen so rund 5 der 117 Milliarden heraus – genau der Grund, warum das Modell trotz seiner
    Größe noch flüssig antwortet, solange die Gewichte im Speicher liegen.
    """
    if not experts or not experts_used or not params:
        return params
    if layers and n_embd and expert_ffn:
        attention = n_embd * (n_head * key_len + 2 * n_head_kv * key_len + n_head * val_len)
        moe = experts_used * 3 * n_embd * expert_ffn  # Gate, Up, Down je Experte
        active = layers * (attention + moe)
        embeddings = max(0, params - layers * (attention + experts * 3 * n_embd * expert_ffn))
        return int(min(params, active + max(0, embeddings)))
    return int(params * (DENSE_SHARE + (1 - DENSE_SHARE) * experts_used / experts))


def _ctx_from_details(show: dict) -> int:
    m = re.search(r"num_ctx\s+(\d+)", show.get("parameters") or "")
    return int(m.group(1)) if m else 0


def kv_bytes(profile: dict, ctx: int, kv_type: str) -> int:
    per_tok = profile["kv_per_token_f16"] * KV_FACTOR.get(kv_type, 1.0)
    sw = profile["sliding_window"]
    if sw and ctx > sw:
        # Sliding-Window-Modelle (z. B. Gemma): nur ca. jede 6. Schicht hält den vollen Kontext.
        return int(per_tok * (ctx / 6 + sw * 5 / 6))
    return int(per_tok * ctx)


def speed(profile: dict, shares: dict, unified: bool = False) -> float:
    """Grobe Schätzung in Token/s: je Token werden alle aktiven Gewichte einmal gelesen.

    shares: Anteile der Gewichte in {"gpu", "ram", "disk"}. Die Zahl ist eine Hausnummer (Faktor 2 daneben ist
    möglich) – sie soll nur die Größenordnung zeigen: flott, zäh oder unbenutzbar.
    """
    active = max(profile.get("active_bytes") or profile["size"], 1)
    gpu_bw = BW_GPU_UNIFIED if unified else BW_GPU
    seconds = TOKEN_OVERHEAD + active * (shares.get("gpu", 0) / gpu_bw + shares.get("ram", 0) / BW_RAM
                                         + shares.get("disk", 0) / BW_DISK)
    return round(1 / seconds, 1) if seconds > 0 else 0.0


def graph_overhead(profile: dict, ctx: int) -> int:
    # Compute-Buffer wächst mit Kontext und Modellbreite; empirisch 0.4–1.2 GB.
    return int(400 * MB + ctx * 12_000 + profile["size"] * 0.02)


# --------------------------------------------------------------------------- Ladeplan

def _gb(value: float) -> str:
    return f"{value / GB:.1f} GB".replace(".", ",")


def plan(profile: dict, hw: dict, cfg: dict, loaded_vram: int = 0) -> dict:
    """Kontext und Speicherverteilung für dieses Modell – GPU zuerst, dann RAM, notfalls von der Platte."""
    env = server_env()
    kv_type = cfg.get("kv_cache_type") or "auto"
    if kv_type == "auto":
        kv_type = (env.get("OLLAMA_KV_CACHE_TYPE") or "f16").lower()
        if env.get("OLLAMA_FLASH_ATTENTION") not in ("1", "true", "True"):
            kv_type = "f16"  # Quantisierter KV-Cache wirkt nur mit Flash Attention

    # Speicher, den dieses Modell bereits belegt, gilt als verfügbar.
    vram_budget = max(0, hw["vram_free"] + loaded_vram - 350 * MB) if hw["gpus"] else 0
    ram_budget = max(0, int(hw.get("ram_free", 0) * RAM_USABLE))
    weights = profile["size"]
    ctx_cap = min(profile["ctx_max"], int(cfg.get("max_auto_ctx") or 32768))
    notes: list[str] = []

    def need_for(ctx: int) -> int:
        return weights + kv_bytes(profile, ctx, kv_type) + graph_overhead(profile, ctx)

    if cfg.get("num_ctx"):
        ctx = min(int(cfg["num_ctx"]), profile["ctx_max"])
        source = "manuell"
    else:
        source = "auto"
        fitting = [c for c in CTX_STEPS if MIN_AGENT_CTX <= c <= ctx_cap and need_for(c) <= vram_budget]
        if fitting:
            ctx = fitting[-1]
        else:
            # Passt nicht ganz auf die GPU: so viel Kontext, wie GPU und RAM zusammen sicher tragen. MoE-Modelle
            # dürfen mehr, weil sie mit Teil-Offload ohnehin flott bleiben; dichte Modelle bleiben knapp, damit
            # möglichst viele Schichten auf der GPU landen.
            head = min(ctx_cap, 32768 if profile["moe"] else 16384)
            roomy = [c for c in CTX_STEPS if MIN_AGENT_CTX <= c <= head and need_for(c) <= vram_budget + ram_budget]
            ctx = roomy[-1] if roomy else min(MIN_AGENT_CTX, profile["ctx_max"])

    need = need_for(ctx)
    unified = bool(hw.get("unified_memory"))
    if unified and hw["vram_total"]:
        gpu_share = min(1.0, vram_budget / need) if need else 1.0
    elif hw["gpus"] and need:
        gpu_share = min(1.0, vram_budget / need)
    else:
        gpu_share = 0.0
    rest = need * (1 - gpu_share)
    ram_share = (min(rest, ram_budget) / need) if need else 0.0
    disk_share = max(0.0, 1 - gpu_share - ram_share)
    shares = {"gpu": round(gpu_share, 3), "ram": round(ram_share, 3), "disk": round(disk_share, 3)}
    tokens_per_s = speed(profile, shares, unified=unified)

    if gpu_share >= 0.999:
        fit = "gpu"
    elif disk_share > 0.01:
        fit = "disk"
    else:
        fit = "cpu" if not hw["gpus"] else "mixed"
    heavy = weights > vram_budget  # Neuladen kostet Minuten – Hilfsmodelle sollen es nicht verdrängen

    active = profile.get("active_bytes") or weights
    moe_note = ""
    if profile["moe"] and active < weights * 0.5:
        moe_note = f" Von {_gb(weights)} sind je Token nur rund {_gb(active)} aktiv (Mixture-of-Experts)"
        moe_note += (", deshalb bleibt es benutzbar." if tokens_per_s >= SLOW_TPS else
                     " – die wechselnden Experten liegen aber über die ganze Datei verteilt, das rettet es hier nicht.")
    if fit == "cpu":
        notes.append(f"Keine GPU erkannt – das Modell rechnet auf der CPU, erwartbar {tokens_per_s} Token/s.{moe_note}")
    elif fit == "disk":
        have = vram_budget + ram_budget
        # Was wäre, wenn der Speicher reichte? Das beantwortet die Frage „lohnt sich mehr RAM?“ direkt.
        enough = speed(profile, {"gpu": gpu_share, "ram": 1 - gpu_share}, unified=unified)
        notes.append(f"Zu groß für diesen Rechner: {_gb(need)} nötig, frei sind {_gb(have)} "
                     f"({_gb(vram_budget)} VRAM + {_gb(ram_budget)} RAM). Ollama liest den Rest laufend von der "
                     f"Platte – erwartbar nur {tokens_per_s} Token/s. Mit rund {_gb(need - have)} mehr "
                     f"Arbeitsspeicher wären es etwa {enough} Token/s; eine kleinere Quantisierung tut es "
                     f"auch.{moe_note}")
    elif fit == "mixed":
        pct = round(gpu_share * 100)
        notes.append(f"Geteilt: ca. {pct}% auf der GPU, der Rest im Arbeitsspeicher – erwartbar "
                     f"{tokens_per_s} Token/s.{moe_note}")
    if heavy and fit != "gpu":
        notes.append("Das Modell passt nicht in den VRAM – Nachladen dauert entsprechend. Coder lässt es deshalb "
                     "geladen, wenn zwischendurch ein Hilfsmodell gebraucht wird; ist es sehr langsam, übernimmt es "
                     "die Kontrolle gleich selbst.")
    if env.get("OLLAMA_FLASH_ATTENTION") not in ("1", "true", "True"):
        notes.append("OLLAMA_FLASH_ATTENTION=1 senkt den Speicherbedarf bei langem Kontext.")
    if kv_type == "f16" and hw["gpus"]:
        notes.append("OLLAMA_KV_CACHE_TYPE=q8_0 halbiert den KV-Cache – fast doppelter Kontext bei gleichem VRAM.")
    if env.get("OLLAMA_NUM_PARALLEL") not in ("1",):
        notes.append("OLLAMA_NUM_PARALLEL=1 verhindert, dass der Kontextspeicher mehrfach reserviert wird.")
    if "tools" not in profile["capabilities"]:
        notes.append("Kein natives Tool-Calling – Coder nutzt ein Text-Protokoll, das weniger zuverlässig ist.")

    options = {"num_ctx": int(ctx)}
    if gpu_share < 1.0 and hw["cores"]:
        options["num_thread"] = int(hw["cores"])

    return {
        "options": options,
        "num_ctx": int(ctx),
        "ctx_source": source,
        "kv_type": kv_type,
        "estimate_bytes": int(need),
        "available_bytes": int(vram_budget + ram_budget),
        "vram_budget": int(vram_budget),
        "ram_budget": int(ram_budget),
        "gpu_share": round(gpu_share, 3),
        "shares": shares,
        "tokens_per_s": tokens_per_s,
        "fit": fit,
        "heavy": bool(heavy),
        "slow": bool(tokens_per_s < SLOW_TPS),
        "fits": gpu_share >= 1.0,
        "notes": notes,
    }


# --------------------------------------------------------------------------- Empfehlung

def score(profile: dict, pl: dict, name: str) -> float:
    """Wie gut taugt das Modell hier als Agent? Klugheit zählt, aber nur, wenn man auf die Antwort nicht wartet."""
    caps = profile["capabilities"]
    if "completion" not in caps and caps:
        return -1  # Embedding-Modelle
    s = 0.0
    s += 40 if "tools" in caps else 0
    s += 25 if re.search(r"coder|code|devstral|codestral", name, re.I) else 0
    # Tempo statt Speicherort: Ein Mixture-of-Experts mit Teil-Offload ist oft schneller als ein dichtes Modell,
    # das gerade so ganz in den VRAM passt. Ab etwa 20 Token/s gibt es die volle Punktzahl.
    tps = pl.get("tokens_per_s") or 0
    s += 30 * min(1.0, tps / 20)
    s += min(20.0, profile["size"] / GB * 1.6)  # größer = meist klüger
    s += 5 if pl["num_ctx"] >= 16384 else 0
    s -= 15 if profile["size"] < 1.5 * GB else 0  # Winzlinge scheitern an Agent-Aufgaben
    if pl.get("fit") == "disk":
        s -= 45  # ständiges Nachlesen von der Platte macht jeden Agenten unbrauchbar
    if tps and tps < SLOW_TPS:
        s -= 25
    return round(s, 1)
