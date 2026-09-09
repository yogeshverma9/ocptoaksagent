from __future__ import annotations

import difflib
from pathlib import Path

from .discovery import Inventory
from .transform import TransformResult

# Report artefacts written by report.py/__main__.py alongside the converted
# chart - write()'s cleanup of stale output from a previous run must never
# touch these.
_RESERVED = {
    "inventory.json", "findings.json", "verdict.json", "diff.patch",
    "validation.md", ".llm_cache",
}


def _shared_top_dir(paths: list[str]) -> str:
    """The single top-level directory every file lives under, if there is one -
    stripped so a single-chart repo lands flat in `out_dir` instead of nested
    one level deeper under its own name."""
    tops = set()
    for p in paths:
        if "/" not in p:
            return ""  # a bare top-level file already exists - nothing safe to strip
        tops.add(p.split("/", 1)[0])
    return tops.pop() if len(tops) == 1 else ""


def write(res: TransformResult, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    for p in sorted(out_dir.iterdir()):
        if p.name in _RESERVED:
            continue
        if p.is_dir():
            for f in sorted(p.rglob("*"), reverse=True):
                f.unlink() if f.is_file() else f.rmdir()
            p.rmdir()
        else:
            p.unlink()

    prefix = _shared_top_dir(list(res.files))
    strip = len(prefix) + 1 if prefix else 0
    for rel, text in res.files.items():
        dest = out_dir / rel[strip:]
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(text, encoding="utf-8")
    return out_dir


def unified_diff(inv: Inventory, res: TransformResult) -> str:
    chunks: list[str] = []
    for rel in sorted(set(inv.files) | set(res.files)):
        before = inv.files.get(rel, {}).get("text", "").splitlines(keepends=True)
        after = res.files.get(rel, "").splitlines(keepends=True)
        if before == after:
            continue
        chunks.extend(difflib.unified_diff(
            before, after,
            fromfile=f"a/{rel}" if before else "/dev/null",
            tofile=f"b/{rel}" if after else "/dev/null",
        ))
    return "".join(chunks)