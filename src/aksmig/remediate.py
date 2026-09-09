from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from ruamel.yaml import YAML

from .discovery import Inventory
from .models import Finding, Severity
from .transform import TransformResult

_yaml = YAML(typ="safe")

_MEM = re.compile(r"^(\d+)(Mi|Gi|M|G|Ki|K)?$")


def _to_bytes(v: str) -> int | None:
    m = _MEM.match(str(v).strip().strip('"'))
    if not m:
        return None
    n = int(m.group(1))
    unit = m.group(2) or ""
    mult = {"": 1, "K": 10**3, "M": 10**6, "G": 10**9,
            "Ki": 2**10, "Mi": 2**20, "Gi": 2**30}
    return n * mult.get(unit, 1)


def _load_values(text: str) -> dict[str, Any]:
    try:
        return _yaml.load(text) or {}
    except Exception:
        return {}


def remediate(
    inv: Inventory, res: TransformResult, cfg, env: dict[str, Any],
    envs: list[dict[str, Any]] | None = None,
) -> list[Finding]:
    """`env` is the primary/passed-in environment (used for defaults elsewhere
    in the pipeline). `envs`, if given, is the full list being converted this
    run - the NEEDS_INPUT scan below checks every one of them, so converting
    several environments in one pass surfaces every environment's unresolved
    TBC values, not just the primary one's.
    """
    std = cfg.standards
    out: list[Finding] = []

    def sev(rule_id: str, default: Severity) -> Severity:
        """Resolve a finding's severity from config/rules.yaml, falling back to `default`
        if the rule isn't declared there. Keeps rules.yaml authoritative for M1-M9."""
        return Severity(cfg.rule_severity(rule_id, default.value))

    values_files = {
        rel: _load_values(res.files[rel])
        for rel in res.files
        if re.search(r"values\.ya?ml$", rel) and "/templates/" not in rel
    }

    # ---- M1 undefined .Values references
    referenced: dict[str, set[str]] = {}
    for rel, text in res.files.items():
        if "/templates/" not in rel:
            continue
        for m in re.finditer(r"\.Values\.([A-Za-z0-9_.]+)", text):
            referenced.setdefault(m.group(1).rstrip("."), set()).add(rel)

    def defined(path: str, tree: dict) -> bool:
        node: Any = tree
        for part in path.split("."):
            if isinstance(node, list):
                return any(isinstance(i, dict) and part in i for i in node)
            if not isinstance(node, dict) or part not in node:
                return False
            node = node[part]
        return True

    for key, where in sorted(referenced.items()):
        if key.split(".")[0] in {"image"} and key.endswith(".tag"):
            continue  # injected via --set at deploy time
        missing = [rel for rel, tree in values_files.items() if not defined(key, tree)]
        if missing and len(missing) == len(values_files):
            out.append(Finding(
                "M1", f"Template references undefined value .Values.{key}",
                sev("M1", Severity.BLOCK), sorted(where)[0],
                f"No values file defines {key!r}; it renders empty. "
                f"Checked: {sorted(Path(m).name for m in missing)}",
                remediation=f"Define {key} in every values file, or correct the template key name."))

    # ---- M2 environment parity (checks nested keys, not just top-level)
    def _flatten_keys(tree: Any, prefix: str = "") -> set[str]:
        keys: set[str] = set()
        if isinstance(tree, dict):
            for k, v in tree.items():
                path = f"{prefix}.{k}" if prefix else str(k)
                keys.add(path)
                keys |= _flatten_keys(v, path)
        return keys

    if std.get("helm", {}).get("requireEnvParity") and len(values_files) > 1:
        keysets = {rel: _flatten_keys(tree) for rel, tree in values_files.items()}
        universe: set[str] = set().union(*keysets.values())
        for key in sorted(universe):
            absent = sorted(Path(r).name for r, ks in keysets.items() if key not in ks)
            if absent and len(absent) < len(keysets):
                present = sorted(Path(r).name for r, ks in keysets.items() if key in ks)
                out.append(Finding(
                    "M2", f"Values key {key!r} is not declared in every environment",
                    sev("M2", Severity.BLOCK), "helm/",
                    f"Present in {present}; missing from {absent}. "
                    f"Templates ranging over {key!r} silently render nothing.",
                    remediation=f"Declare {key} in all environments, or gate the template explicitly."))

    # ---- M3 secrets committed to values files
    if std["secrets"].get("forbidLiteralsInValuesFiles"):
        patterns = [re.compile(p) for p in std["secrets"]["forbiddenKeyPatterns"]]
        allowed = {str(a).lower() for a in std["secrets"].get("allowedPlaceholders", [])}
        for rel, tree in values_files.items():
            for item in tree.get("envVars", []) or []:
                if not isinstance(item, dict):
                    continue
                name, value = str(item.get("name", "")), str(item.get("value", ""))
                if not any(p.match(name) for p in patterns):
                    continue
                if value.lower() in allowed or "<" in value or not value:
                    continue
                out.append(Finding(
                    "M3", f"Literal credential committed for {name}",
                    sev("M3", Severity.BLOCK), rel,
                    f"{name} has a hard-coded value in version control "
                    f"(masked: {value[:4]}...{value[-2:]}).",
                    remediation=f"Move to {std['secrets']['backend']} and reference via secretRef."))

    # ---- M4 / M5 / M7 container-level checks
    for rel, text in res.files.items():
        if "/templates/" not in rel or "kind: Deployment" not in text:
            continue
        blocks = re.split(r"^---\s*$", text, flags=re.M)
        for block in blocks:
            if "kind: Deployment" not in block:
                continue
            cname = re.search(r"-\s*name:\s*([\w.-]+)", block)
            container = cname.group(1) if cname else "container"

            lim = re.search(r"limits:\s*\n(?:\s+cpu:.*\n)?\s+memory:\s*\"?([\w]+)\"?", block)
            req = re.search(r"requests:\s*\n(?:\s+cpu:.*\n)?\s+memory:\s*\"?([\w]+)\"?", block)

            if lim and req:
                lu = _MEM.match(lim.group(1))
                ru = _MEM.match(req.group(1))
                if lu and ru and (lu.group(2) or "") != (ru.group(2) or ""):
                    if {lu.group(2), ru.group(2)} & {"M", "G"}:
                        out.append(Finding(
                            "M4", f"Mixed memory units on container {container!r}",
                            sev("M4", Severity.HIGH), rel,
                            f"limits={lim.group(1)} vs requests={req.group(1)} "
                            "(decimal vs binary in the same container).",
                            remediation="Use Mi/Gi consistently.", auto_fixed=True))

                lb, rb = _to_bytes(lim.group(1)), _to_bytes(req.group(1))
                maxratio = std["resources"].get("maxBurstRatio", 4)
                if lb and rb and rb > 0 and lb / rb > maxratio:
                    out.append(Finding(
                        "M5", f"Burst ratio {lb / rb:.0f}x exceeds limit on {container!r}",
                        sev("M5", Severity.HIGH), rel,
                        f"limit={lim.group(1)} request={req.group(1)}; standard allows {maxratio}x. "
                        "AKS node pools may be unable to satisfy the limit.",
                        remediation="Raise the request, lower the limit, or confirm node pool SKU."))

            if std["probes"].get("requireReadiness") and "readinessProbe" not in block:
                out.append(Finding(
                    "M7", f"Container {container!r} has no readinessProbe",
                    sev("M7", Severity.HIGH), rel,
                    "helm upgrade --atomic judges rollout success by readiness. "
                    "Without a probe, --atomic reports success on a broken deploy.",
                    remediation="Add readinessProbe and livenessProbe on the container port."))
            if std["probes"].get("requireLiveness") and "livenessProbe" not in block:
                out.append(Finding(
                    "M7", f"Container {container!r} has no livenessProbe",
                    sev("M7", Severity.HIGH), rel, "No livenessProbe defined.",
                    remediation="Add a livenessProbe."))

    # ---- M6 HPA coverage
    if std["autoscaling"].get("requirePerDeployment"):
        deployments: set[str] = set()
        scaled: set[str] = set()
        for rel, text in res.files.items():
            if "/templates/" not in rel:
                continue
            if "kind: Deployment" in text:
                for m in re.finditer(r"\{\{\s*\.Values\.(\w+)\.name\s*\}\}", text):
                    deployments.add(m.group(1))
            if "HorizontalPodAutoscaler" in text:
                for m in re.finditer(r"\{\{\s*\.Values\.(\w+)\.name\s*\}\}", text):
                    scaled.add(m.group(1))
        for d in sorted(deployments - scaled):
            out.append(Finding(
                "M6", f"Deployment {d!r} has no HorizontalPodAutoscaler",
                sev("M6", Severity.MEDIUM), "helm/templates/pod_scaler.yaml",
                f"{d} will not scale under load.",
                remediation="Add an HPA per Deployment, or record an explicit exemption."))

    # ---- M8 Dockerfile hardening
    for rel in inv.dockerfiles:
        text = inv.text(rel)
        if re.search(r"^\s*USER\s+root", text, re.M):
            out.append(Finding(
                "M8", "Container runs as root",
                sev("M8", Severity.BLOCK), rel,
                f"USER root is set. AKS Pod Security Admission "
                f"({std['security']['podSecurityAdmission']}) will reject this pod.",
                remediation="Run as a non-root UID and set securityContext.runAsNonRoot: true."))
        if std["security"].get("forbidWorldWritableChmod") and re.search(r"chmod\s+(-R\s+)?777", text):
            out.append(Finding(
                "M8", "World-writable permissions set in image",
                sev("M8", Severity.BLOCK), rel,
                "chmod 777 grants write to all users.",
                remediation="Use targeted ownership (chown) with 0755."))

    # ---- M9 registry + pull secret
    legacy = std["registry"]["legacy"]
    target = std["registry"]["target"]
    for rel, tree in values_files.items():
        repo = str((tree.get("image") or {}).get("repository", ""))
        if legacy in repo:
            # NEEDS_INPUT overrides the configured M9 severity when we don't even know
            # the destination registry yet - there's nothing actionable to block on.
            m9_sev = Severity.NEEDS_INPUT if target.startswith("TBC") else sev("M9", Severity.HIGH)
            out.append(Finding(
                "M9", "Image pulled from on-premises registry",
                m9_sev, rel,
                f"repository={repo} is not reachable by policy from AKS.",
                remediation=(f"Confirm target ACR name (currently {target}) "
                             "and add imagePullSecrets or AcrPull via workload identity.")))
    if std["registry"].get("requireImagePullSecret"):
        if not any("imagePullSecrets" in t for t in res.files.values()):
            out.append(Finding(
                "M9", "No imagePullSecrets defined in any template",
                sev("M9", Severity.HIGH), "helm/templates/deployment.yaml",
                "Pods cannot authenticate to a private registry.",
                remediation="Add imagePullSecrets, or grant AcrPull to the kubelet identity."))

    # ---- NEEDS_INPUT from the environment matrix
    for target_env in (envs if envs is not None else [env]):
        for key, value in target_env.items():
            if str(value).strip().upper() == "TBC":
                out.append(Finding(
                    "N0", f"Environment {target_env['name']} is missing {key}",
                    Severity.NEEDS_INPUT, "config/env-matrix.yaml",
                    f"{key} is TBC; the agent will not guess this value.",
                    remediation=f"Supply {key} for environment {target_env['name']}."))

    return out