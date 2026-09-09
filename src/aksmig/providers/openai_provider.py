from __future__ import annotations

import json
import os
import urllib.request

from .base import LLMProvider


class OpenAIProvider(LLMProvider):
    """Azure OpenAI and OpenAI-compatible endpoints. Stdlib only, no SDK."""

    name = "openai"

    def __init__(self, cfg: dict) -> None:
        llm = cfg.get("llm", {})
        self.model = llm.get("model", "gpt-4o")
        self.endpoint = (llm.get("endpoint") or os.environ.get("LLM_ENDPOINT", "")).rstrip("/")
        self.api_key = llm.get("api_key") or os.environ.get("LLM_API_KEY", "")
        self.temperature = llm.get("temperature", 0)
        self.max_tokens = llm.get("max_tokens", 4096)
        self.timeout = llm.get("timeout_seconds", 120) 
        if not self.endpoint or not self.api_key:
            raise SystemExit("LLM_ENDPOINT and LLM_API_KEY must be set for this provider.")

    def _post(self, path: str, payload: dict) -> dict:
        req = urllib.request.Request(
            f"{self.endpoint}{path}",
            data=json.dumps(payload).encode(),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
                "api-key": self.api_key,
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            return json.loads(resp.read())

    def complete(self, prompt: str, *, system: str = "", max_tokens: int | None = None) -> str:
        messages = ([{"role": "system", "content": system}] if system else []) + \
                   [{"role": "user", "content": prompt}]
        data = self._post("/chat/completions", {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
            "max_tokens": max_tokens or self.max_tokens,
        })
        return data["choices"][0]["message"]["content"]

    def embed(self, texts: list[str]) -> list[list[float]]:
        data = self._post("/embeddings", {"model": self.model, "input": texts})
        return [d["embedding"] for d in data["data"]]