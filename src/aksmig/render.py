from __future__ import annotations

import difflib
from pathlib import Path

from .discovery import Inventory
from .transform import TransformResult


def write(res: TransformResult, out_dir: Path) -> Path:
    target = out_dir / "rendered"
    if target.exists():
        for p in sorted(target.rglob("*"), reverse=True):
            p.unlink() if p.is_file() else p.rmdir()
    for rel, text in res.files.items():
        dest = target / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(text, encoding="utf-8")
    return target


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