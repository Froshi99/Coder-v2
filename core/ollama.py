"""Schlanker async Client für die Ollama-REST-API."""

import json
from typing import AsyncIterator

import httpx


class OllamaError(RuntimeError):
    pass


class Ollama:
    def __init__(self, base_url: str = "http://localhost:11434"):
        self.base_url = base_url.rstrip("/")
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=httpx.Timeout(None, connect=5.0),
        )
        self._show_cache: dict[str, dict] = {}

    async def close(self) -> None:
        await self._client.aclose()

    async def _json(self, method: str, path: str, **kw) -> dict:
        try:
            r = await self._client.request(method, path, **kw)
        except httpx.HTTPError as e:
            raise OllamaError(f"Ollama nicht erreichbar unter {self.base_url} ({e.__class__.__name__})") from e
        if r.status_code >= 400:
            raise OllamaError(_error_text(r.text, r.status_code))
        return r.json()

    async def version(self) -> str:
        return (await self._json("GET", "/api/version")).get("version", "?")

    async def tags(self) -> list[dict]:
        return (await self._json("GET", "/api/tags")).get("models", [])

    async def ps(self) -> list[dict]:
        return (await self._json("GET", "/api/ps")).get("models", [])

    async def show(self, model: str) -> dict:
        if model not in self._show_cache:
            data = await self._json("POST", "/api/show", json={"model": model})
            # Tokenizer-Listen sind riesig und für uns nutzlos.
            info = data.get("model_info") or {}
            data["model_info"] = {k: v for k, v in info.items() if not k.startswith("tokenizer.")}
            data.pop("tensors", None)
            data.pop("modelfile", None)
            data.pop("license", None)
            self._show_cache[model] = data
        return self._show_cache[model]

    async def load(self, model: str, options: dict, keep_alive: str) -> dict:
        """Lädt das Modell mit exakt den Optionen, die später auch der Chat nutzt.

        Abweichende num_ctx-Werte zwischen Laden und Chat würden einen erneuten
        Ladevorgang erzwingen — deshalb kommt beides aus derselben Quelle.
        """
        return await self._json(
            "POST",
            "/api/generate",
            json={"model": model, "prompt": "", "keep_alive": keep_alive, "options": options, "stream": False},
        )

    async def unload(self, model: str) -> None:
        await self._json("POST", "/api/generate", json={"model": model, "keep_alive": 0, "stream": False})

    async def generate(self, model: str, prompt: str, *, suffix: str = "", raw: bool = False,
                       options: dict | None = None, stop=None, keep_alive: str | None = None) -> str:
        """Eine Antwort am Stück – für das Ergänzen in der Dateiansicht.

        suffix: Ollama baut den FIM-Prompt selbst (Modelle mit der Fähigkeit `insert`).
        raw: der Prompt geht ohne Vorlage durch – so, wie das Modell seine Marken erwartet.
        """
        payload: dict = {"model": model, "prompt": prompt, "stream": False}
        if suffix:
            payload["suffix"] = suffix
        if raw:
            payload["raw"] = True
        opts = dict(options or {})
        if stop:
            opts["stop"] = list(stop)
        if opts:
            payload["options"] = opts
        if keep_alive:
            payload["keep_alive"] = keep_alive
        return str((await self._json("POST", "/api/generate", json=payload)).get("response") or "")

    async def chat_stream(
        self,
        model: str,
        messages: list[dict],
        *,
        tools: list[dict] | None = None,
        options: dict | None = None,
        keep_alive: str | None = None,
        think: bool | None = None,
    ) -> AsyncIterator[dict]:
        payload: dict = {"model": model, "messages": messages, "stream": True}
        if tools:
            payload["tools"] = tools
        if options:
            payload["options"] = options
        if keep_alive:
            payload["keep_alive"] = keep_alive
        if think is not None:
            payload["think"] = think
        try:
            async with self._client.stream("POST", "/api/chat", json=payload) as r:
                if r.status_code >= 400:
                    body = (await r.aread()).decode("utf-8", "replace")
                    raise OllamaError(_error_text(body, r.status_code))
                async for line in r.aiter_lines():
                    if not line.strip():
                        continue
                    chunk = json.loads(line)
                    if "error" in chunk:
                        raise OllamaError(chunk["error"])
                    yield chunk
        except httpx.HTTPError as e:
            raise OllamaError(f"Verbindung zu Ollama unterbrochen ({e.__class__.__name__})") from e

    async def embed(self, model: str, inputs: list[str], keep_alive: str = "10m",
                    options: dict | None = None) -> list[list[float]]:
        payload: dict = {"model": model, "input": inputs, "keep_alive": keep_alive, "truncate": True}
        if options:
            payload["options"] = options
        data = await self._json("POST", "/api/embed", json=payload)
        return data.get("embeddings") or []


def _error_text(body: str, status: int) -> str:
    try:
        return json.loads(body).get("error") or f"HTTP {status}"
    except ValueError:
        return body.strip() or f"HTTP {status}"
