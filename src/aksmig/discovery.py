from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from ruamel.yaml import YAML

from .models import Finding, Severity

_yaml = YAML(typ="safe")

OCP_MARKERS = {
    "route.openshift.io": "OpenShift Route API",
    "apps.openshift.io": "OpenShift DeploymentConfig API",
    "image.openshift.io": "OpenShift ImageStream API",
    "build.openshift.io": "OpenShift BuildConfig API",
    "security.openshift.io": "OpenShift SecurityContextConstraints",
    "HelmDeploy@0": "Azure DevOps OCP-era Helm task",
    "kubernetesServiceEndpoint": "OCP service connection",
    "autoscaling/v1": "Deprecated HPA API",
    ".ocp.internal.spark.co.nz": "OpenShift cluster DNS",
    "ocp-billing-invserv1": "OpenShift build agent pool",
    "openshift.io/host.generated": "OpenShift-generated route host",
}


class Inventory:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.files: dict[str, dict[str, Any]] = {}
        self.findings: list[Finding] = []

    @property
    def helm_templates(self) -> list[str]:
        return [p for p in self.files if "/templates/" in p and p.endswith((".yaml", ".yml"))]

    @property
    def values_files(self) -> list[str]:
        return [
            p for p in self.files
            if re.search(r"helm/[a-z0-9_]*values\.ya?ml$", p) or p.endswith("/values.yaml")
        ]

    @property
    def pipeline_files(self) -> list[str]:
        return [p for p in self.files if p.startswith("pipeline/") or "pipeline" in Path(p).name]

    @property
    def dockerfiles(self) -> list[str]:
        return [p for p in self.files if Path(p).name.lower().startswith("dockerfile")]

    def text(self, rel: str) -> str:
        return self.files[rel]["text"]

    def docs(self, rel: str) -> list[dict[str, Any]]:
        return self.files[rel].get("docs", [])

    def to_dict(self) -> dict[str, Any]:
        return {
            "root": str(self.root),
            "fileCount": len(self.files),
            "files": {
                p: {
                    "ocpScore": m["ocp_score"],
                    "markers": m["markers"],
                    "kind": m.get("kind"),
                    "apiVersion": m.get("api_version"),
                }
                for p, m in sorted(self.files.items())
            },
        }


def _parse_yaml_docs(text: str) -> list[dict[str, Any]]:
    """Best-effort parse. Helm templating makes most files invalid YAML; that's expected."""
    stripped = re.sub(r"\{\{-?.*?-?\}\}", "PLACEHOLDER", text, flags=re.S)
    out: list[dict[str, Any]] = []
    try:
        for doc in _yaml.load_all(stripped):
            if isinstance(doc, dict):
                out.append(doc)
    except Exception:
        pass
    return out


def discover(root: Path) -> Inventory:
    inv = Inventory(root)
    skip = {".git", "node_modules", "dist", "test", "tests", ".venv", "__pycache__"}

    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(root).as_posix()
        if any(part in skip for part in path.relative_to(root).parts[:-1]):
            continue
        if path.suffix.lower() not in {".yaml", ".yml", ".tpl", ""} and not path.name.lower().startswith("dockerfile"):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue

        markers = [desc for marker, desc in OCP_MARKERS.items() if marker in text]
        docs = _parse_yaml_docs(text) if path.suffix.lower() in {".yaml", ".yml"} else []
        first = docs[0] if docs else {}

        inv.files[rel] = {
            "text": text,
            "docs": docs,
            "markers": markers,
            "ocp_score": len(markers),
            "kind": first.get("kind"),
            "api_version": first.get("apiVersion"),
        }

        for marker, desc in OCP_MARKERS.items():
            if marker in text:
                line = next(
                    (i for i, ln in enumerate(text.splitlines(), 1) if marker in ln), None
                )
                inv.findings.append(
                    Finding(
                        rule_id="D0",
                        title=f"OpenShift coupling: {desc}",
                        severity=Severity.INFO,
                        path=rel,
                        line=line,
                        detail=f"Found marker {marker!r}",
                        remediation="Handled by the transform stage.",
                    )
                )

    return inv