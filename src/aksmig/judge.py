from __future__ import annotations

from collections import Counter

from .models import Finding, Severity, Verdict


def judge(findings: list[Finding], cfg) -> Verdict:
    counts = Counter(f.severity for f in findings)
    thresholds = cfg.rules.get("judge", {}).get("thresholds", {})
    needs_input_blocks = cfg.rules.get("judge", {}).get("needsInputIsBlocking", False)

    blocks = counts[Severity.BLOCK]
    highs = counts[Severity.HIGH] + counts[Severity.MEDIUM]
    inputs = counts[Severity.NEEDS_INPUT]

    if blocks >= thresholds.get("block", 1):
        decision = "BLOCK"
        rationale = (
            f"{blocks} blocking finding(s) must be resolved before this workload can be "
            f"deployed to AKS. No pull request will be opened for deployment. "
            f"The most severe items are structural defects the OpenShift platform "
            f"tolerated but AKS will reject."
        )
    elif needs_input_blocks and inputs:
        decision = "BLOCK"
        rationale = f"{inputs} required input(s) are unresolved (TBC in the environment matrix)."
    elif highs >= thresholds.get("review", 1) or inputs:
        decision = "NEEDS_REVIEW"
        rationale = (
            f"No blocking defects, but {highs} finding(s) require human judgement "
            f"and {inputs} configuration value(s) are still TBC. A pull request will be "
            f"opened for review; it will not auto-merge."
        )
    else:
        decision = "AUTO_APPROVE"
        rationale = (
            "All deterministic transforms applied and every validator passed. "
            "Artefacts are ready for pull request."
        )

    return Verdict(
        decision=decision,
        rationale=rationale,
        counts={s.value: counts[s] for s in Severity if counts[s]},
    )