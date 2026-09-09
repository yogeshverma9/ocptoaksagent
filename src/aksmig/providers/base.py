from __future__ import annotations

from abc import ABC, abstractmethod


class LLMProvider(ABC):
    """The only surface the migration engine may call.

    Swapping vendor or model must never require a change outside providers/.
    """

    name: str = "base"

    @abstractmethod
    def complete(self, prompt: str, *, system: str = "", max_tokens: int | None = None) -> str: ...

    @abstractmethod
    def embed(self, texts: list[str]) -> list[list[float]]: ...

    @property
    def available(self) -> bool:
        return True


class NullProvider(LLMProvider):
    """Deterministic no-op. Offline mode. No network, no credentials."""

    name = "null"

    def complete(self, prompt: str, *, system: str = "", max_tokens: int | None = None) -> str:
        return ""

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [[] for _ in texts]

    @property
    def available(self) -> bool:
        return False