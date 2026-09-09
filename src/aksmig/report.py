from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from .models import Finding, Severity, Verdict, sort_findings

_ICON = {
    Severity.BLOCK: "BLOCK",
    Severity.HIGH: "HIGH",
    Severity.MEDIUM: "MED",
    Severity.LOW: "LOW",
    Severity.NEEDS_INPUT: "INPUT",
    Severity.INFO: "info",
}


def write_all(out: Path, *, repo: str, envs: list[dict], mode: str,
              inventory: dict, findings: list[Finding], verdict: Verdict,
              diff: str) -> None:
    out.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).isoformat(timespec="seconds")

    (out / "inventory.json").write_text(json.dumps(inventory, indent=2), encoding="utf-8")
    (out / "findings.json").write_text(
        json.dumps([f.to_dict() for f in sort_findings(findings)], indent=2), encoding="utf-8")
    (out / "verdict.json").write_text(json.dumps(verdict.to_dict(), indent=2), encoding="utf-8")
    (out / "diff.patch").write_text(diff, encoding="utf-8")

    actionable = [f for f in sort_findings(findings) if f.severity != Severity.INFO]
    applied = [f for f in findings if f.auto_fixed]

    lines = [
        f"# OCP to AKS Migration Report",
        "",
        f"- **Repository:** `{repo}`",
        f"- **Mode:** `{mode}`",
        f"- **Generated:** {ts}",
        "",
        "## Environment(s) converted",
        "",
        "| Name | Tier | AKS Cluster | Namespace |",
        "|---|---|---|---|",
    ]
    lines += [
        f"| `{e['name']}` | `{e.get('tier')}` | `{e.get('aksTargetClusterName')}` | `{e.get('kubernetesNamespace')}` |"
        for e in envs
    ]
    lines += [
        "",
        f"## Verdict: {verdict.decision}",
        "",
        verdict.rationale,
        "",
        "| Severity | Count |",
        "|---|---|",
    ]
    for sev, count in verdict.counts.items():
        lines.append(f"| {sev} | {count} |")

    lines += ["", "## Transforms applied", "",
              "| Rule | File | Change |", "|---|---|---|"]
    for f in applied:
        lines.append(f"| `{f.rule_id}` | `{f.path}` | {f.title} |")
    if not applied:
        lines.append("| - | - | none |")

    lines += ["", "## Findings requiring action", ""]
    if not actionable:
        lines.append("None.")
    for f in actionable:
        loc = f"`{f.path}`" + (f" line {f.line}" if f.line else "")
        lines += [
            f"### [{_ICON[f.severity]}] `{f.rule_id}` — {f.title}",
            "",
            f"**Location:** {loc}",
            "",
            f.detail,
            "",
        ]
        if f.remediation:
            lines += [f"**Remediation:** {f.remediation}", ""]

    lines += [
        "## Artefacts",
        "",
        "| File | Contents |",
        "|---|---|",
        "| `inventory.json` | Discovered files with OpenShift coupling scores |",
        "| `findings.json` | Machine-readable findings |",
        "| `verdict.json` | Judge decision and counts |",
        "| `diff.patch` | Unified diff, source to migrated |",
        "| `rendered/` | Migrated artefacts ready for pull request |",
        "",
    ]
    (out / "validation.md").write_text("\n".join(lines), encoding="utf-8")