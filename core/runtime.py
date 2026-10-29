"""Verbindet Ollama, Hardware-Erkennung und Ladeplanung zu einer Laufzeit."""

import asyncio
import contextlib
import time

from . import config as config_mod
from . import complete as complete_mod
from . import controller, imagegen, optimizer
from . import vllm as vllm_mod
from .ollama import Ollama, OllamaError

VISION_PREFERENCE = ("gemma3", "qwen2.5vl", "qwen2.5-vl", "llama3.2-vision", "gemma4", "mistral-small3", "llava",
                     "minicpm-v", "moondream")
EMBED_PREFERENCE = ("nomic-embed-text", "mxbai-embed-large", "embeddinggemma", "snowflake-arctic-embed", "bge-m3",
                    "all-minilm")
SIDE_CTX = 16384  # Kontroll- und Bildmodelle brauchen keinen riesigen Kontext – das spart VRAM und Ladezeit
# Ein Embedding-Modell belegt samt Puffer rund ein halbes Gigabyte. Ist weniger frei, rechnet es auf der CPU, statt dass
# Ollama das Chat-Modell entlädt und bei der nächsten Antwort wieder lädt.
EMBED_VRAM = 1536 * optimizer.MB
CPU_ONLY = {"num_gpu": 0}


def _short(name: str) -> str:
    return name.split("/")[-1].lower()


class Runtime:
    def __init__(self, cfg: dict | None = None):
        self.cfg = cfg or config_mod.load()
        self.client = self._open()
        self.plans: dict[str, dict] = {}
        self._lock = asyncio.Lock()
        self._installed: tuple[float, list[str]] = (0.0, [])
        self._preload: asyncio.Task | None = None
        self.warned_slow: set[str] = set()  # „läuft großteils auf der CPU“ sagt Coder je Modell nur einmal
        self.busy_agents = 0  # wie viele Aufträge gerade laufen – solange ergänzt Coder nicht nebenher

    def _open(self):
        """Der Client zum eingestellten Modell-Server. Beide sprechen dieselbe Sprache nach außen."""
        if self.cfg.get("backend") == "vllm":
            return vllm_mod.VLLM(self.cfg.get("vllm_url") or vllm_mod.CANDIDATES[0])
        return Ollama(self.cfg["ollama_url"])

    @property
    def backend(self) -> str:
        return "vllm" if self.cfg.get("backend") == "vllm" else "ollama"

    @property
    def server_url(self) -> str:
        return getattr(self.client, "base_url", self.cfg["ollama_url"])

    async def close(self) -> None:
        await self.client.close()

    async def update_config(self, changes: dict) -> dict:
        vorher = (self.cfg["ollama_url"], self.cfg.get("backend"), self.cfg.get("vllm_url"))
        self.cfg = config_mod.update(changes)
        if (self.cfg["ollama_url"], self.cfg.get("backend"), self.cfg.get("vllm_url")) != vorher:
            await self.client.close()
            self.client = self._open()
            self._installed = (0.0, [])
            self.plans.clear()  # ein anderer Server lädt anders – der alte Plan gilt nicht mehr
            vllm_mod.forget()
            complete_mod.forget()  # ein anderer Server ergänzt anders
            await self.match_model()
        if {"num_ctx", "max_auto_ctx", "kv_cache_type"} & changes.keys():
            self.plans.clear()  # nächster Chat lädt mit neuem Plan
        if {"model", "complete_model", "complete"} & changes.keys():
            complete_mod.forget()  # alte Vorschläge passen nicht zu einem neuen Modell
        if any(key.startswith("image_") for key in changes):
            imagegen.forget()  # Adresse oder Schalter geändert: den Bilddienst neu suchen
        return self.cfg

    async def match_model(self) -> None:
        """Nach einem Serverwechsel auf ein Modell umstellen, das der neue Server auch bedient.

        vLLM bedient genau das, womit es gestartet wurde. Bliebe der alte Name stehen, scheiterte jede Anfrage
        mit „model not found“ – dann lieber gleich das nehmen, was da ist.
        """
        want = str(self.cfg.get("model") or "")
        try:
            names = [t["name"] for t in await self.client.tags()]
        except OllamaError:
            return  # Server gerade nicht erreichbar: Der Name bleibt, bis es wieder geht
        if names and want not in names:
            self.cfg = config_mod.update({"model": names[0]})

    # ------------------------------------------------------------------ Status

    async def status(self) -> dict:
        try:
            version = await self.client.version()
            return {"ok": True, "version": version, "url": self.server_url, "backend": self.backend}
        except OllamaError as e:
            return {"ok": False, "error": str(e), "url": self.server_url, "backend": self.backend}

    async def loaded(self) -> list[dict]:
        try:
            models = await self.client.ps()
        except OllamaError:
            return []
        return [{
            "name": m["name"],
            "size": m.get("size", 0),
            "size_vram": m.get("size_vram", 0),
            "gpu_share": round(m.get("size_vram", 0) / m["size"], 3) if m.get("size") else 0,
            "context_length": m.get("context_length"),
            "expires_at": m.get("expires_at"),
        } for m in models]

    async def models(self) -> dict:
        tags = await self.client.tags()
        self._installed = (time.monotonic(), [t["name"] for t in tags])
        shows = await asyncio.gather(*(self.client.show(t["name"]) for t in tags), return_exceptions=True)
        loaded = {m["name"]: m for m in await self.loaded()}
        hw = await asyncio.to_thread(optimizer.detect_hardware)  # nvidia-smi soll die Event-Loop nicht anhalten
        all_loaded_vram = sum(m["size_vram"] for m in loaded.values())
        items = []
        for tag, show in zip(tags, shows):
            if isinstance(show, Exception):
                continue
            profile = optimizer.model_profile(show, tag.get("size", 0))
            if profile["capabilities"] and "completion" not in profile["capabilities"]:
                continue  # Embedding-Modelle können nicht chatten
            lm = loaded.get(tag["name"])
            # Beim Laden werden andere Modelle entladen – deren VRAM zählt als verfügbar.
            reclaim = all_loaded_vram if self.cfg.get("unload_others", True) else (lm["size_vram"] if lm else 0)
            pl = optimizer.plan(profile, hw, self.cfg, loaded_vram=reclaim)
            items.append({
                "name": tag["name"],
                "profile": profile,
                "plan": pl,
                "score": optimizer.score(profile, pl, tag["name"]),
                "loaded": lm,
            })
        items.sort(key=lambda m: m["score"], reverse=True)
        recommended = items[0]["name"] if items else None
        main = self.cfg.get("model") or recommended
        roles = {"controller": await self.controller_model(main) if main else None,
                 "vision": await self.vision_model(main), "embed": await self.embed_model()}
        return {"models": items, "recommended": recommended, "hardware": hw, "env": optimizer.server_env(),
                "roles": roles}

    async def recommended_model(self) -> str | None:
        return (await self.models())["recommended"]

    # ------------------------------------------------------------------ Rollen: Kontrolle, Bilder, Embeddings

    async def installed(self, max_age: float = 15.0) -> list[str]:
        stamp, names = self._installed
        if not names or time.monotonic() - stamp > max_age:
            names = [t["name"] for t in await self.client.tags()]
            self._installed = (time.monotonic(), names)
        return names

    async def model_caps(self, model: str) -> list[str]:
        if model in self.plans:
            return self.capabilities(model)
        try:
            return list((await self.client.show(model)).get("capabilities") or [])
        except OllamaError:
            return []

    async def _first(self, prefer: tuple[str, ...], need: str, names: list[str]) -> str | None:
        for prefix in prefer:
            for name in names:
                if _short(name).startswith(prefix) and need in await self.model_caps(name):
                    return name
        return None

    def heavy(self, model: str) -> bool:
        """Passt das Modell nicht in den VRAM? Dann kostet jedes Nachladen viel Zeit – 120B-Modelle Minuten."""
        return bool(self.plans.get(model, {}).get("heavy"))

    def very_heavy(self, model: str) -> bool:
        """So groß oder langsam, dass sich ein zweites Modell nicht mehr lohnt – dann prüft es sich selbst."""
        pl = self.plans.get(model) or {}
        return bool(pl.get("fit") == "disk" or pl.get("slow") or (pl.get("load_seconds") or 0) > 60)

    async def controller_model(self, main: str) -> str:
        """Wer kontrolliert: das eingestellte Modell, sonst Mistral, sonst das Hauptmodell selbst.

        Bei einem großen Hauptmodell prüft es sich selbst: Ein zweites Modell würde es aus dem Speicher drängen,
        und das Zurückladen dauert bei 120B länger als die Prüfung.
        """
        try:
            names = await self.installed()
        except OllamaError:
            return main
        wanted = str(self.cfg.get("controller_model") or "")
        if wanted and wanted in names:
            return wanted
        if self.very_heavy(main):
            return main  # ein zweites Modell zu laden dauert hier länger als die Prüfung selbst
        return await self._first(controller.PREFERENCE, "completion", names) or main

    async def vision_model(self, main: str | None = None) -> str | None:
        """Wer Bilder ansieht: das Hauptmodell, wenn es das kann – sonst das eingestellte oder ein passendes Modell."""
        if main and "vision" in await self.model_caps(main):
            return main
        try:
            names = await self.installed()
        except OllamaError:
            return None
        wanted = str(self.cfg.get("vision_model") or "")
        if wanted and wanted in names and "vision" in await self.model_caps(wanted):
            return wanted
        in_memory = [m["name"] for m in await self.loaded()]
        found = (await self._first(VISION_PREFERENCE, "vision", in_memory)  # schon geladen: kein Modellwechsel
                 or await self._first(VISION_PREFERENCE, "vision", names))
        if found:
            return found
        for name in names:
            if "vision" in await self.model_caps(name):
                return name
        return None

    async def embed_model(self) -> str | None:
        try:
            names = await self.installed(max_age=60)
        except OllamaError:
            return None
        for prefix in EMBED_PREFERENCE:
            for name in names:
                if _short(name).startswith(prefix):
                    return name
        return None

    async def embed_options(self, model: str) -> dict | None:
        """Wo das Embedding-Modell rechnet: auf der GPU nur, wenn dort Platz ist – sonst auf der CPU.

        Ist es schon geladen, bleibt es, wo es ist; andere Optionen würden Ollama zum Neuladen zwingen.
        """
        current = next((m for m in await self.loaded() if m["name"] == model), None)
        if current is not None:
            return None if current.get("size_vram") else CPU_ONLY
        hw = await asyncio.to_thread(optimizer.detect_hardware)
        if not hw["gpus"] or hw.get("unified_memory") or hw["vram_free"] >= EMBED_VRAM:
            return None
        return CPU_ONLY

    # ------------------------------------------------------------------ Laden

    async def ensure_loaded(self, model: str, force: bool = False, side: bool = False) -> dict:
        """Lädt das Modell GPU-optimiert und misst anschließend die echte Verteilung.

        side: Hilfsmodell (Kontrolle, Bilder) – kleinerer Kontext. Ist das Modell schon als Hauptmodell geladen,
        wird es einfach mitbenutzt.
        """
        async with self._lock:
            loaded = {m["name"]: m for m in await self.loaded()}
            cached = self.plans.get(model)
            if not force and cached and model in loaded and (side or not cached.get("side")):
                return cached

            show = await self.client.show(model)
            tag = next((t for t in await self.client.tags() if t["name"] == model), None)
            if tag is None:
                raise OllamaError(f"Modell '{model}' ist nicht installiert (ollama pull {model}).")
            profile = optimizer.model_profile(show, tag.get("size", 0))

            if self.cfg.get("unload_others", True):
                # Ein großes Hauptmodell bleibt liegen, wenn nur ein Hilfsmodell dazukommt – sonst lädt es minutenlang nach.
                others = [name for name in loaded if name != model and not (side and self.heavy(name))]
                for name in others:
                    # Aufräumen ist Kür: Lässt sich ein Modell nicht entladen, darf das Laden trotzdem nicht scheitern.
                    with contextlib.suppress(OllamaError):
                        await self.client.unload(name)
                if others:
                    await asyncio.sleep(0.8)  # Treiber gibt VRAM verzögert frei

            cfg = dict(self.cfg)
            if side:
                explicit = int(cfg.get("num_ctx") or 0)
                cfg["num_ctx"] = min(explicit, SIDE_CTX) if explicit else 0
                cfg["max_auto_ctx"] = min(int(cfg.get("max_auto_ctx") or SIDE_CTX), SIDE_CTX)
            hw = await asyncio.to_thread(optimizer.detect_hardware, 0)
            current = loaded.get(model)
            pl = optimizer.plan(profile, hw, cfg, loaded_vram=current["size_vram"] if current else 0)

            t0 = time.perf_counter()
            await self.client.load(model, pl["options"], self.cfg["keep_alive"])
            pl["load_seconds"] = round(time.perf_counter() - t0, 2)

            actual = next((m for m in await self.loaded() if m["name"] == model), None)
            pl["actual"] = actual
            if actual and actual["size"]:  # gemessen schlägt geschätzt: Tempo mit der echten Verteilung
                share = actual["size_vram"] / actual["size"]
                rest = 1 - share
                ram_part = min(rest, max(0.0, pl["ram_budget"] / actual["size"])) if actual["size"] else 0
                pl["shares"] = {"gpu": round(share, 3), "ram": round(ram_part, 3),
                                "disk": round(max(0.0, rest - ram_part), 3)}
                pl["tokens_per_s"] = optimizer.speed(profile, pl["shares"], unified=hw.get("unified_memory", False))
                pl["slow"] = pl["tokens_per_s"] < optimizer.SLOW_TPS
            if actual and actual["gpu_share"] < 0.999 and pl["fits"]:
                pl["notes"].insert(0, f"Gemessen: {round(actual['gpu_share'] * 100)}% auf der GPU – "
                                      "Kontext in den Einstellungen verkleinern für volle GPU-Geschwindigkeit.")
            pl["profile"] = profile
            pl["side"] = side
            self.plans[model] = pl
            return pl

    def preload(self, model: str) -> None:
        """Legt das Hauptmodell im Hintergrund wieder in den VRAM, nachdem ein Hilfsmodell es verdrängt hat."""
        if self._preload and not self._preload.done():
            return

        async def run():
            try:
                await self.ensure_loaded(model)
            except Exception:  # noqa: BLE001 — beim nächsten Chat wird ohnehin geladen
                pass

        self._preload = asyncio.create_task(run())

    def chat_options(self, model: str) -> dict:
        opts = dict(self.plans.get(model, {}).get("options", {}))
        if self.cfg.get("temperature") is not None:
            opts["temperature"] = float(self.cfg["temperature"])
        return opts

    def num_ctx(self, model: str) -> int:
        return self.plans.get(model, {}).get("num_ctx", 8192)

    def capabilities(self, model: str) -> list[str]:
        return self.plans.get(model, {}).get("profile", {}).get("capabilities", [])
