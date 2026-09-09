from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

from .models import Finding, Severity


def _has(tool: str) -> bool:
    return shutil.which(tool) is not None


def _run(cmd: list[str], cwd: Path | None = None) -> tuple[int, str]:
    try:
        p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=180)
        return p.returncode, (p.stdout + p.stderr)
    except Exception as exc:  # noqa: BLE001
        return 127, str(exc)


def validate(rendered: Path, cfg, envs: list[dict], mode: str) -> list[Finding]:
    """`envs` is every environment being converted this run (one entry for a
    single-environment `--env` invocation). V1/V2/V3/V5 render/lint the chart
    once per environment - each environment's values file can render
    differently, so a defect specific to one environment must not be masked
    by another happening to be fine.
    """
    findings: list[Finding] = []
    std = cfg.standards
    chart = rendered / "helm"

    # ---- V1/V2/V3/V5: per environment
    if _has("helm") and (chart / "Chart.yaml").is_file():
        for env in envs:
            env_name = env["name"]
            manifests = rendered / f".manifests.{env_name}.yaml"
            values = chart / env["valuesFile"]
            values_arg = str(values) if values.is_file() else None

            args = ["helm", "lint", "--strict", str(chart)]
            if values_arg:
                args += ["--values", values_arg]
            rc, output = _run(args)
            if rc != 0:
                findings.append(Finding(
                    "V1", f"helm lint --strict failed ({env_name})", Severity.BLOCK, "helm/",
                    output.strip()[:1500],
                    remediation="Fix chart errors before deploying."))

            # ---- V2 helm template
            rc, output = _run([
                "helm", "template", "release", str(chart),
                "--values", values_arg or str(chart / "values.yaml"),
                "--set", "image.tag=validation",
            ])
            if rc != 0:
                findings.append(Finding(
                    "V2", f"helm template failed to render ({env_name})", Severity.BLOCK, "helm/",
                    output.strip()[:1500],
                    remediation="Chart cannot render; deployment would fail."))
                continue
            manifests.write_text(output, encoding="utf-8")

            # ---- V3 kubeconform
            if _has("kubeconform"):
                rc, kout = _run([
                    "kubeconform", "-strict", "-summary",
                    "-ignore-missing-schemas", "-output", "json", str(manifests),
                ])
                if rc != 0:
                    findings.append(Finding(
                        "V3", f"Kubernetes schema validation failed ({env_name})", Severity.BLOCK,
                        "helm/", kout.strip()[:1500],
                        remediation="Correct the manifest against the Kubernetes API schema."))

            # ---- V5 conftest / OPA
            policy_dir = Path(os.environ.get("AKSMIG_POLICY_DIR", "/app/policy"))
            if _has("conftest") and policy_dir.is_dir():
                rc, cout = _run([
                    "conftest", "test", "--policy", str(policy_dir),
                    "--output", "json", str(manifests),
                ])
                try:
                    for result in json.loads(cout or "[]"):
                        for f in result.get("failures", []):
                            findings.append(Finding(
                                "V5", f"Policy violation ({env_name})", Severity.BLOCK, "helm/",
                                f.get("msg", ""), remediation="Bring the manifest into policy compliance."))
                        for w in result.get("warnings", []):
                            findings.append(Finding(
                                "V5", f"Policy warning ({env_name})", Severity.MEDIUM, "helm/",
                                w.get("msg", "")))
                except json.JSONDecodeError:
                    pass

    # ---- V4 trivy config scan
    if _has("trivy"):
        rc, tout = _run([
            "trivy", "config", "--quiet", "--severity", "HIGH,CRITICAL",
            "--format", "json", str(rendered),
        ])
        try:
            for result in json.loads(tout or "{}").get("Results", []) or []:
                for mis in result.get("Misconfigurations", []) or []:
                    findings.append(Finding(
                        "V4", f"Security: {mis.get('Title', 'misconfiguration')}",
                        Severity.HIGH if mis.get("Severity") == "HIGH" else Severity.BLOCK,
                        result.get("Target", "."), mis.get("Description", "")[:600],
                        remediation=mis.get("Resolution", "")[:400]))
        except json.JSONDecodeError:
            pass

    # ---- V6 residual OCP scan (the defect the human migration left behind)
    if std["dns"].get("scanEnvVarsForResidualOcp"):
        for path in sorted(rendered.rglob("*.y*ml")):
            try:
                text = path.read_text(encoding="utf-8")
            except OSError:
                continue
            for m in re.finditer(r"\S*\.ocp\.internal\.spark\.co\.nz\S*", text):
                line = text[: m.start()].count("\n") + 1
                findings.append(Finding(
                    "V6", "Residual OpenShift hostname after migration",
                    Severity.BLOCK, path.relative_to(rendered).as_posix(),
                    f"{m.group(0)} still targets the OCP cluster.", line=line,
                    remediation="Remap to the AKS equivalent, or confirm the dependency is staying on OCP."))

    # ---- V7 forbidden API versions
    for path in sorted(rendered.rglob("*.y*ml")):
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        for bad in std.get("forbiddenApiVersions", []):
            if bad in text:
                findings.append(Finding(
                    "V7", f"Forbidden apiVersion {bad}", Severity.BLOCK,
                    path.relative_to(rendered).as_posix(),
                    f"{bad} is not permitted on AKS.",
                    remediation="Migrate to the supported API version."))

    # ---- V8 pipeline hygiene
    for path in sorted(rendered.rglob("*.y*ml")):
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        rel = path.relative_to(rendered).as_posix()
        for bad in std["pipeline"].get("forbiddenTasks", []):
            if bad in text:
                findings.append(Finding(
                    "V8", f"Forbidden pipeline task {bad}", Severity.BLOCK, rel,
                    f"{bad} cannot authenticate to AKS.",
                    remediation="Use AzureCLI@2 with az aks get-credentials + kubelogin."))
        if "stages" in rel or "pipeline" in rel:
            commented = len(re.findall(r"^\s*#\s*-\s*stage:", text, re.M))
            if commented:
                findings.append(Finding(
                    "V8", f"{commented} deployment stage(s) commented out",
                    Severity.HIGH, rel,
                    "Environments are silently excluded from the CD pipeline.",
                    remediation="Re-enable the stages, or remove them and record why."))

    if mode == "offline":
        findings.append(Finding(
            "V9", "Server-side validation skipped (offline mode)",
            Severity.INFO, ".",
            "helm --dry-run=server and kubectl auth can-i require cluster access.",
            remediation="Re-run with --mode connected once credentials are available."))

    return findings