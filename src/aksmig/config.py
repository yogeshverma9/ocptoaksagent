from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from ruamel.yaml import YAML

_yaml = YAML(typ="safe")


def _expand(node: Any) -> Any:
    if isinstance(node, str):
        return os.path.expandvars(node)
    if isinstance(node, dict):
        return {k: _expand(v) for k, v in node.items()}
    if isinstance(node, list):
        return [_expand(v) for v in node]
    return node


class Config:
    """Loads config from AKSMIG_CONFIG_DIR, falling back to the baked-in defaults."""

    def __init__(self, config_dir: str | None = None) -> None:
        primary = Path(config_dir or os.environ.get("AKSMIG_CONFIG_DIR", "/config"))
        fallback = Path(os.environ.get("AKSMIG_DEFAULT_CONFIG_DIR", "/app/config"))
        self._dirs = [d for d in (primary, fallback) if d.is_dir()]
        if not self._dirs:
            raise SystemExit("No config directory found. Mount one at /config.")

        self.standards = self._load("standards.yaml")
        self.env_matrix = self._load("env-matrix.yaml")
        self.models = self._load("models.yaml")
        self.rules = self._load("rules.yaml")
        self.mappings = self._load("mappings.yaml")

    def _load(self, name: str) -> dict[str, Any]:
        for d in self._dirs:
            p = d / name
            if p.is_file():
                with p.open() as fh:
                    return _expand(_yaml.load(fh) or {})
        raise SystemExit(f"Config file {name} not found in {[str(d) for d in self._dirs]}")

    def environment(self, name: str) -> dict[str, Any]:
        for env in self.env_matrix.get("environments", []):
            if env.get("name", "").lower() == name.lower():
                return env
        available = [e.get("name") for e in self.env_matrix.get("environments", [])]
        raise SystemExit(f"Unknown environment {name!r}. Available: {available}")

    def rule_severity(self, rule_id: str, default: str) -> str:
        """Look up the configured severity for a transform/remediate rule id.

        Falls back to `default` if rules.yaml has no entry for this id (e.g. a
        rule that predates rules.yaml, or a validator (V*) rule that is not
        declared there at all).
        """
        for section in ("transform", "remediate"):
            for rule in self.rules.get(section, []):
                if rule.get("id") == rule_id:
                    return rule.get("severity", default)
        return default