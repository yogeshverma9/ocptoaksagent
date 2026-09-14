from __future__ import annotations

import os

from .base import LLMProvider, NullProvider


def get_provider(models_cfg: dict) -> LLMProvider:
    # LLM_PROVIDER lets you flip vendor from migration.env (untracked) without
    # editing config/models.yaml (tracked). Value is any of: ollama, openai,
    # azure_openai, anthropic, null/none.
    env_override = os.environ.get("LLM_PROVIDER", "").strip().lower()
    name = env_override or str(models_cfg.get("llm", {}).get("provider", "null")).lower()
    if name in {"null", "none", ""}:
        return NullProvider()
    try:
        if name in {"azure_openai", "openai"}:
            from .openai_provider import OpenAIProvider
            return OpenAIProvider(models_cfg, flavor=name)
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