from __future__ import annotations

import json
import os
import urllib.request

from .base import LLMProvider

# Ollama is inherently a local/private-network service - never something a
# corporate HTTP(S)_PROXY should intercept. Build one opener with proxying
# disabled so a proxy that blocks/misroutes localhost traffic (a common
# corporate-network quirk) can't make an always-reachable local model look
# unavailable.
_opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))


class OllamaProvider(LLMProvider):
    name = "ollama"

    def __init__(self, cfg: dict) -> None:
        llm = cfg.get("llm", {})
        self.model = os.environ.get("LLM_MODEL") or llm.get("model", "llama3.1")
        self.endpoint = (llm.get("endpoint")
                         or os.environ.get("LLM_ENDPOINT", "http://localhost:11434")).rstrip("/")
        self.timeout = float(os.environ.get("LLM_TIMEOUT") or llm.get("timeout_seconds", 300))
        self.temperature = float(llm.get("temperature", 0) or 0)
        seed_env = os.environ.get("LLM_SEED")
        self.seed = int(seed_env) if seed_env not in (None, "") else llm.get("seed", 0)

    def complete(self, prompt: str, *, system: str = "", max_tokens: int | None = None) -> str:
        options = {"temperature": self.temperature, "seed": self.seed}
        if max_tokens:
            options["num_predict"] = max_tokens
        payload = {"model": self.model, "prompt": prompt, "stream": False, "options": options}
        if system:
            payload["system"] = system
        req = urllib.request.Request(
            f"{self.endpoint}/api/generate",
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with _opener.open(req, timeout=self.timeout) as resp:
            return json.loads(resp.read()).get("response", "")

    @property
    def available(self) -> bool:
        try:
            req = urllib.request.Request(f"{self.endpoint}/api/tags")
            with _opener.open(req, timeout=5):
                return True
        except Exception:
            return False

    def embed(self, texts: list[str]) -> list[list[float]]:
        out = []
        for t in texts:
            req = urllib.request.Request(
                f"{self.endpoint}/api/embeddings",
                data=json.dumps({"model": self.model, "prompt": t}).encode(),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with _opener.open(req, timeout=self.timeout) as resp:
                out.append(json.loads(resp.read()).get("embedding", []))
        return out