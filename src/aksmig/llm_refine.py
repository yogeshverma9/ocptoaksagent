from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from .discovery import Inventory, _parse_yaml_docs
from .models import Finding, Severity
from .transform import TransformResult

SYSTEM_PROMPT = """You are an OpenShift-to-AKS migration engineer.

You will be given one file from a Helm chart, Azure DevOps pipeline, or
Dockerfile. It has already been mechanically transformed by a deterministic
rule engine (rules listed below). Review it and return the final, complete
file content for Azure Kubernetes Service.

Rules:
- Preserve Helm templating syntax exactly, e.g. {{ .Values.x }} - never
  resolve, remove or rewrite it.
- Only change what is necessary to finish the AKS migration or fix a defect
  named in FINDINGS below. Do not restructure things that are already correct.
- If nothing needs to change, return the AFTER content unchanged.
- Return ONLY the final file content. No explanation, no markdown code
  fences, no commentary before or after.
"""

_FENCE_RE = re.compile(r"^```[a-zA-Z0-9_-]*\n|\n```\s*$")

# Some models echo the prompt's own "--- AFTER (...) ---" section marker and
# append a "--- CHANGES MADE ---"-style explanation afterwards, despite being
# told to return only the file content - keep just what's between the
# echoed "AFTER" marker and the next "---" marker, dropping the commentary.
_AFTER_SECTION_RE = re.compile(
    r"^-{2,}\s*AFTER\b.*?-{2,}\s*$\n(.*?)(?=\n-{2,}|\Z)",
    re.IGNORECASE | re.MULTILINE | re.DOTALL,
)


def _strip_fences(text: str) -> str:
    return _FENCE_RE.sub("", text.strip())


def _strip_commentary(text: str) -> str:
    m = _AFTER_SECTION_RE.search(text)
    return m.group(1).strip() if m else text


def _clean_response(text: str) -> str:
    return _strip_fences(_strip_commentary(text))


def _cache_key(*parts: str) -> str:
    h = hashlib.sha256()
    for p in parts:
        h.update(p.encode("utf-8"))
        h.update(b"\x00")
    return h.hexdigest()


class LLMCache:
    """On-disk, content-addressed cache of LLM responses.

    This is what makes idempotent output possible: once `freeze` is true,
    a cache hit is replayed verbatim instead of calling the model again, so
    re-running against the same inputs reproduces the same files every time
    - even though the underlying model/provider may not be perfectly
    deterministic between calls, hosts, or versions.
    """

    def __init__(self, cache_dir: Path, *, freeze: bool, force_refresh: bool) -> None:
        self.dir = cache_dir
        self.freeze = freeze
        self.force_refresh = force_refresh
        self.dir.mkdir(parents=True, exist_ok=True)

    def get(self, key: str) -> str | None:
        if self.force_refresh or not self.freeze:
            return None
        f = self.dir / f"{key}.json"
        if f.is_file():
            try:
                return json.loads(f.read_text(encoding="utf-8"))["response"]
            except Exception:
                return None
        return None

    def put(self, key: str, response: str, meta: dict[str, Any]) -> None:
        # Always record the latest response, frozen or not - freezing later
        # replays whatever was last recorded for this exact input.
        f = self.dir / f"{key}.json"
        f.write_text(json.dumps({"response": response, **meta}, indent=2), encoding="utf-8")


def _looks_valid(rel: str, before_ok: bool, candidate: str) -> bool:
    if not candidate.strip():
        return False
    if rel.endswith((".yaml", ".yml")):
        docs = _parse_yaml_docs(candidate)
        if before_ok and not docs:
            return False
    return True


def _build_prompt(rel: str, before: str, after: str, findings: list[Finding], standards: dict) -> str:
    lines = [
        f"FILE: {rel}", "",
        "--- BEFORE (original OpenShift source) ---", before or "(new file)", "",
        "--- AFTER (deterministic rule engine output) ---", after, "",
    ]
    if findings:
        lines.append("--- FINDINGS FOR THIS FILE ---")
        for f in findings:
            lines.append(f"[{f.severity.value}] {f.rule_id} {f.title}: {f.detail}")
        lines.append("")
    lines += [
        "--- RELEVANT STANDARDS ---",
        f"ingress class: {standards.get('ingress', {}).get('class')}",
        f"memory units: {standards.get('resources', {}).get('memoryUnits')}",
        f"probes required: liveness={standards.get('probes', {}).get('requireLiveness')}, "
        f"readiness={standards.get('probes', {}).get('requireReadiness')}",
    ]
    return "\n".join(lines)


def refine_files(
    inv: Inventory,
    res: TransformResult,
    extra_findings: list[Finding],
    cfg,
    provider,
    *,
    cache: LLMCache,
    on_file=None,
) -> list[Finding]:
    """LLM pass over every file the deterministic engine touched.

    Runs unconditionally - the LLM is mandatory - but `cache` decides whether
    a fresh call is made or a frozen response is replayed for idempotency.
    Mutates res.files in place; returns findings describing what happened.
    `on_file(rel, replayed)`, if given, is called before each model call so
    the caller can show live progress on what can be a slow step.

    A per-file failure (timeout, unreachable endpoint, invalid output) never
    aborts the run: that file's deterministic output is kept, a finding
    (`L3`/`L4`) records what happened, and the loop moves on to the next file.
    """
    findings: list[Finding] = []
    all_findings = res.findings + extra_findings

    changed = {
        rel for rel, text in res.files.items()
        if inv.files.get(rel, {}).get("text") != text
    }
    flagged = {f.path for f in all_findings if f.path in res.files}
    targets = sorted(changed | flagged)

    for rel in targets:
        before = inv.files.get(rel, {}).get("text", "")
        after = res.files[rel]
        file_findings = [f for f in all_findings if f.path == rel]

        prompt = _build_prompt(rel, before, after, file_findings, cfg.standards)
        key = _cache_key(provider.name, getattr(provider, "model", ""), SYSTEM_PROMPT, prompt)

        # Cap generation to a small multiple of the input size, not the
        # global (much larger) max_tokens - a file-rewrite should never need
        # to run away to that budget, and doing so is the single biggest
        # cause of a slow refine pass on smaller/local models.
        token_budget = min(4000, max(600, len(after) // 2))

        cached = cache.get(key)
        if on_file:
            on_file(rel, cached is not None)
        if cached is not None:
            candidate = _clean_response(cached)
            replayed = True
        else:
            try:
                raw = provider.complete(prompt, system=SYSTEM_PROMPT, max_tokens=token_budget)
            except Exception as exc:
                # A single slow/unreachable/erroring call must never take down
                # the whole run - fall back to the deterministic output for
                # this file only, exactly like a failed validation check.
                findings.append(Finding(
                    rule_id="L4", title="LLM call failed, kept deterministic output",
                    severity=Severity.MEDIUM, path=rel,
                    detail=f"The model call for this file raised {type(exc).__name__}: {exc}. "
                           "The deterministic transform/remediate output was kept unchanged.",
                    remediation="Common causes: the model is too slow for LLM_TIMEOUT on this "
                                 "hardware (raise LLM_TIMEOUT, or use a smaller LLM_MODEL), or "
                                 "the provider endpoint is unreachable (check LLM_ENDPOINT).",
                ))
                continue
            candidate = _clean_response(raw)
            cache.put(key, candidate, {"path": rel, "model": getattr(provider, "model", "")})
            replayed = False

        before_ok = bool(_parse_yaml_docs(after)) if rel.endswith((".yaml", ".yml")) else True
        if not _looks_valid(rel, before_ok, candidate):
            findings.append(Finding(
                rule_id="L3", title="LLM refinement rejected, reverted to deterministic output",
                severity=Severity.MEDIUM, path=rel,
                detail="The model's response for this file failed a basic sanity/YAML check "
                       "and was discarded; the deterministic transform/remediate output was kept.",
                remediation="Optionally re-run with LLM_FORCE_REFRESH=true, or inspect "
                             "the cached prompt/response under LLM_CACHE_DIR.",
            ))
            continue

        res.files[rel] = candidate
        if replayed:
            findings.append(Finding(
                rule_id="L2", title="LLM refinement replayed from frozen cache",
                severity=Severity.INFO, path=rel,
                detail="FREEZE_OUTPUT is on and a cached response existed for this exact "
                       "input - it was replayed verbatim for idempotent output.",
                auto_fixed=True,
            ))
        else:
            findings.append(Finding(
                rule_id="L1", title="LLM reviewed and updated this file",
                severity=Severity.INFO, path=rel,
                detail="Generated fresh by the model this run. Set FREEZE_OUTPUT=true in "
                       "migration.env once you're happy with the result to lock it in.",
                auto_fixed=True,
            ))

    return findings
