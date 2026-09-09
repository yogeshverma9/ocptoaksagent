from __future__ import annotations

import json
import os
import urllib.request

from .base import LLMProvider


class AnthropicProvider(LLMProvider):
    name = "anthropic"

    def __init__(self, cfg: dict) -> None:
        llm = cfg.get("llm", {})
        self.model = llm.get("model", "claude-sonnet-4")
        self.endpoint = (llm.get("endpoint") or "https://api.anthropic.com/v1").rstrip("/")
        self.api_key = llm.get("api_key") or os.environ.get("LLM_API_KEY", "")
        self.max_tokens = llm.get("max_tokens", 4096)
        self.timeout = llm.get("timeout_seconds", 120)
        if not self.api_key:
            raise SystemExit("LLM_API_KEY must be set for the anthropic provider.")

    def complete(self, prompt: str, *, system: str = "", max_tokens: int | None = None) -> str:
        payload = {
            "model": self.model,
            "max_tokens": max_tokens or self.max_tokens,
            "messages": [{"role": "user", "content": prompt}],
        }
        if system:
            payload["system"] = system
        req = urllib.request.Request(
            f"{self.endpoint}/messages",
            data=json.dumps(payload).encode(),
            headers={
                "content-type": "application/json",
                "x-api-key": self.api_key,
                "anthropic-version": "2023-06-01",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            data = json.loads(resp.read())
        return "".join(b.get("text", "") for b in data.get("content", []))

    def embed(self, texts: list[str]) -> list[list[float]]:
        raise NotImplementedError("Configure a separate embeddings provider.")