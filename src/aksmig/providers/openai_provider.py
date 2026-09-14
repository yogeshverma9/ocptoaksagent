from __future__ import annotations

import json
import os
import urllib.request

from .base import LLMProvider


class OpenAIProvider(LLMProvider):
    """OpenAI and Azure OpenAI. Stdlib only, no SDK.

    Azure OpenAI's URL/auth shape differs from OpenAI's:
    - URL: `{endpoint}/openai/deployments/{deployment}/chat/completions?api-version=...`
      vs OpenAI's `{endpoint}/chat/completions`.
    - Auth: `api-key: <key>` header vs `Authorization: Bearer <key>`.
    - `model` is a *deployment name*, not a model id.
    Toggle with `provider: azure_openai` (or `LLM_PROVIDER=azure_openai`).
    """

    def __init__(self, cfg: dict, *, flavor: str = "openai") -> None:
        llm = cfg.get("llm", {})
        self.flavor = flavor
        self.name = flavor
        self.model = os.environ.get("LLM_MODEL") or llm.get("model", "gpt-4o")
        self.endpoint = (llm.get("endpoint") or os.environ.get("LLM_ENDPOINT", "")).rstrip("/")
        self.api_key = os.environ.get("LLM_API_KEY") or llm.get("api_key", "")
        self.api_version = (os.environ.get("LLM_API_VERSION")
                            or llm.get("api_version", "2024-06-01"))
        self.temperature = llm.get("temperature", 0)
        self.max_tokens = llm.get("max_tokens", 4096)
        self.timeout = float(os.environ.get("LLM_TIMEOUT") or llm.get("timeout_seconds", 120))
        if not self.endpoint or not self.api_key:
            raise SystemExit(
                f"LLM_ENDPOINT and LLM_API_KEY must be set for provider {flavor!r}."
            )

    def _url(self, path: str) -> str:
        # Azure requires the deployment segment and api-version query string;
        # OpenAI-compatible endpoints take the path as-is.
        if self.flavor == "azure_openai":
            return (f"{self.endpoint}/openai/deployments/{self.model}"
                    f"{path}?api-version={self.api_version}")
        return f"{self.endpoint}{path}"

    def _headers(self) -> dict:
        if self.flavor == "azure_openai":
            return {"Content-Type": "application/json", "api-key": self.api_key}
        return {"Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}"}

    def _post(self, path: str, payload: dict) -> dict:
        req = urllib.request.Request(
            self._url(path),
            data=json.dumps(payload).encode(),
            headers=self._headers(),
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            return json.loads(resp.read())

    def complete(self, prompt: str, *, system: str = "", max_tokens: int | None = None) -> str:
        messages = ([{"role": "system", "content": system}] if system else []) + \
                   [{"role": "user", "content": prompt}]
        # Azure OpenAI ignores `model` in the body (the deployment in the URL wins),
        # but including it is harmless and keeps the payload identical for both.
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