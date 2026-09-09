from __future__ import annotations

from .base import LLMProvider, NullProvider


def get_provider(models_cfg: dict) -> LLMProvider:
    name = str(models_cfg.get("llm", {}).get("provider", "null")).lower()
    if name in {"null", "none", ""}:
        return NullProvider()
    try:
        if name in {"azure_openai", "openai"}:
            from .openai_provider import OpenAIProvider
            return OpenAIProvider(models_cfg)
        if name == "anthropic":
            from .anthropic_provider import AnthropicProvider
            return AnthropicProvider(models_cfg)
        if name == "ollama":
            from .ollama_provider import OllamaProvider
            return OllamaProvider(models_cfg)
    except ImportError as exc:
        raise SystemExit(
            f"Provider {name!r} requires extra dependencies: {exc}. "
            "Use provider: \"null\" for offline mode."
        ) from exc
    raise SystemExit(f"Unknown LLM provider {name!r}")