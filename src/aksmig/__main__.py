from __future__ import annotations

import difflib
import sys
from pathlib import Path

import click
from rich.console import Console
from rich.table import Table

from . import __version__
from .config import Config
from .discovery import discover
from .judge import judge
from .llm_refine import LLMCache, refine_files
from .models import Severity, WORKBOOK_COLUMNS, sort_findings
from .providers import get_provider
from .remediate import remediate
from .render import unified_diff, write
from .report import write_all
from .transform import transform
from .validate import validate
from .workbook import build_rows, parse_intake, write_workbook

console = Console()

_STYLE = {
    Severity.BLOCK: "bold red",
    Severity.HIGH: "red",
    Severity.MEDIUM: "yellow",
    Severity.LOW: "cyan",
    Severity.NEEDS_INPUT: "magenta",
    Severity.INFO: "dim",
}


@click.group()
@click.version_option(__version__)
def cli() -> None:
    """Model-independent, reference-driven OpenShift to AKS migration agent."""


@cli.command()
@click.option("--repo", required=True, help="Repository name, for reporting.")
@click.option("--env", "env_name", default=None,
              help="Target environment from env-matrix.yaml. Omit to convert every "
                   "environment defined there in a single pass.")
@click.option("--mode", type=click.Choice(["offline", "assisted", "connected"]), default="offline",
              help="Cluster connectivity for VALIDATE (dry-run/RBAC checks). "
                   "Does not gate the LLM - the LLM runs in every mode.")
@click.option("--workspace", default="/workspace", type=click.Path(exists=True))
@click.option("--out", "out_dir", default="/aks", type=click.Path())
@click.option("--config-dir", default=None)
@click.option("--fail-on-block/--no-fail-on-block", default=True)
@click.option("--freeze-output/--no-freeze-output", "freeze_output", envvar="FREEZE_OUTPUT",
              default=False, help="Replay the cached LLM response instead of calling the "
                                   "model again, for idempotent output. Flip on once you're "
                                   "happy with a run.")
@click.option("--llm-cache-dir", envvar="LLM_CACHE_DIR", default=None, type=click.Path(),
              help="Where frozen LLM responses live. Defaults to <out>/.llm_cache.")
@click.option("--llm-force-refresh/--no-llm-force-refresh", "llm_force_refresh",
              envvar="LLM_FORCE_REFRESH", default=False,
              help="Call the model even if FREEZE_OUTPUT is on and a cached response exists.")
def migrate(repo, env_name, mode, workspace, out_dir, config_dir, fail_on_block,
            freeze_output, llm_cache_dir, llm_force_refresh):
    """Discover, transform, remediate, refine (LLM), validate and judge a repository."""
    cfg = Config(config_dir)
    if env_name:
        envs = [cfg.environment(env_name)]
    else:
        envs = list(cfg.env_matrix.get("environments", []))
        if not envs:
            raise SystemExit("No environments defined in config/env-matrix.yaml.")
    # The "primary" environment - used only for defaults/fallbacks (agent
    # pool, DNS tier) on files that aren't tied to one specific environment.
    # T6/T8 (transform.py) resolve the *correct* environment per file for
    # anything that is environment-specific, regardless of which one this is.
    env = envs[0]
    env_label = env["name"] if len(envs) == 1 else (
        f"{len(envs)} environments ({', '.join(e['name'] for e in envs)})")
    out = Path(out_dir)
    root = Path(workspace)

    provider = get_provider(cfg.models)
    if not provider.available:
        raise SystemExit(
            f"LLM provider {provider.name!r} is not available, but the LLM is mandatory "
            f"for every run (see config/models.yaml). For the default 'ollama' provider, "
            f"make sure the Ollama daemon is running and reachable at "
            f"{getattr(provider, 'endpoint', '?')} with the model pulled."
        )
    cache_dir = Path(llm_cache_dir) if llm_cache_dir else out / ".llm_cache"
    cache = LLMCache(cache_dir, freeze=freeze_output, force_refresh=llm_force_refresh)

    console.rule(f"[bold]{repo} -> AKS ({env_label})  mode={mode}  "
                 f"llm={provider.name}  freeze={freeze_output}")

    console.print("[bold]1/7[/] Discover")
    inv = discover(root)
    console.print(f"      {len(inv.files)} file(s); "
                  f"{sum(1 for m in inv.files.values() if m['ocp_score'])} with OpenShift coupling")

    console.print("[bold]2/7[/] Transform")
    res = transform(inv, cfg, env)
    console.print(f"      {sum(1 for f in res.findings if f.auto_fixed)} transform(s) applied, "
                  f"{len(res.deleted)} file(s) removed")

    console.print("[bold]3/7[/] Remediate")
    rem = remediate(inv, res, cfg, env, envs=envs)
    console.print(f"      {len(rem)} latent defect(s) detected")

    console.print("[bold]4/7[/] Refine (LLM)")
    def _progress(rel: str, replayed: bool) -> None:
        console.print(f"      {'replaying (frozen)' if replayed else 'generating'}: {rel}")
    llm_findings = refine_files(inv, res, rem, cfg, provider, cache=cache, on_file=_progress)
    replayed = sum(1 for f in llm_findings if f.rule_id == "L2")
    generated = sum(1 for f in llm_findings if f.rule_id == "L1")
    reverted = sum(1 for f in llm_findings if f.rule_id == "L3")
    failed = sum(1 for f in llm_findings if f.rule_id == "L4")
    console.print(f"      {generated} file(s) refined fresh, {replayed} replayed from frozen "
                  f"cache, {reverted} reverted (failed validation), {failed} failed (LLM call error)")

    console.print("[bold]5/7[/] Render")
    rendered = write(res, out)
    diff = unified_diff(inv, res)

    console.print("[bold]6/7[/] Validate")
    val = validate(rendered, cfg, envs, mode)
    console.print(f"      {len(val)} validator finding(s)")

    console.print("[bold]7/7[/] Judge")
    findings = inv.findings + res.findings + rem + llm_findings + val
    verdict = judge(findings, cfg)

    write_all(out, repo=repo, envs=envs, mode=mode,
              inventory=inv.to_dict(), findings=findings,
              verdict=verdict, diff=diff)

    table = Table(title="Findings requiring action", show_lines=False)
    table.add_column("Sev", width=6)
    table.add_column("Rule", width=5)
    table.add_column("File", overflow="fold")
    table.add_column("Issue", overflow="fold")
    for f in sort_findings(findings):
        if f.severity is Severity.INFO:
            continue
        table.add_row(f"[{_STYLE[f.severity]}]{f.severity.value}[/]",
                      f.rule_id, f.path, f.title)
    console.print(table)

    colour = {"BLOCK": "bold red", "NEEDS_REVIEW": "yellow", "AUTO_APPROVE": "green"}[verdict.decision]
    console.rule(f"[{colour}]VERDICT: {verdict.decision}")
    console.print(verdict.rationale)
    console.print(f"\nArtefacts written to [bold]{out}[/]: "
                  "validation.md, findings.json, diff.patch, rendered/")

    if fail_on_block and verdict.decision == "BLOCK":
        sys.exit(2)


@cli.command()
@click.option("--candidate", required=True, type=click.Path(exists=True))
@click.option("--reference", required=True, type=click.Path(exists=True))
@click.option("--out", "out_dir", default="/aks", type=click.Path())
def golden(candidate, reference, out_dir):
    """Score agent output against the human-verified AKS migration."""
    cand, ref = Path(candidate), Path(reference)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    def collect(root: Path) -> dict[str, list[str]]:
        return {
            p.relative_to(root).as_posix(): p.read_text(encoding="utf-8").splitlines()
            for p in sorted(root.rglob("*"))
            if p.is_file() and p.suffix in {".yaml", ".yml"} and not p.name.startswith(".")
        }

    c, r = collect(cand), collect(ref)
    table = Table(title="Golden diff: agent output vs human AKS branch")
    table.add_column("File", overflow="fold")
    table.add_column("Match", justify="right")
    table.add_column("Status")

    total = 0.0
    for rel in sorted(set(c) | set(r)):
        if rel not in r:
            table.add_row(rel, "-", "[cyan]agent extra (expected: remediation)[/]")
            continue
        if rel not in c:
            table.add_row(rel, "0%", "[red]MISSING from agent output[/]")
            total += 0
            continue
        ratio = difflib.SequenceMatcher(None, c[rel], r[rel]).ratio()
        total += ratio
        style = "green" if ratio >= 0.9 else "yellow" if ratio >= 0.7 else "red"
        table.add_row(rel, f"{ratio:.0%}", f"[{style}]{'match' if ratio >= 0.9 else 'differs'}[/]")

    score = total / max(len(r), 1)
    console.print(table)
    console.rule(f"[bold]Golden score: {score:.1%} (Phase 1 target: >= 90%)")
    (out / "golden.json").write_text(
        f'{{"score": {score:.4f}, "target": 0.90, "pass": {str(score >= 0.9).lower()}}}\n',
        encoding="utf-8")
    if score < 0.90:
        sys.exit(3)


@cli.command()
@click.option("--intake", required=True, type=click.Path(exists=True),
              help="Plain-text file describing namespaces/deployments to migrate.")
@click.option("--out", "out_dir", default="/aks", type=click.Path())
@click.option("--config-dir", default=None)
def workbook(intake, out_dir, config_dir):
    """Build the migration workbook from a plain-text intake file.

    Fill in what you know (namespace, deployment, route, PVC, storage type,
    database, ...) in a simple text file - see migration-intake.example.txt -
    and this extracts it, maps storage/network requirements to their Azure
    equivalent via config/mappings.yaml, and writes migration_workbook.md/.csv.
    """
    cfg = Config(config_dir)
    # utf-8-sig tolerates (and strips) a BOM, which Notepad adds by default -
    # without this the first "Key:" in the file silently fails to match.
    text = Path(intake).read_text(encoding="utf-8-sig")
    entries = parse_intake(text)
    if not entries:
        console.print("[yellow]No entries found in the intake file. "
                       "See migration-intake.example.txt for the expected format.[/]")

    rows = build_rows(entries, cfg)
    md_path, csv_path = write_workbook(Path(out_dir), rows)

    table = Table(title="Migration workbook")
    for col in WORKBOOK_COLUMNS:
        table.add_column(col, overflow="fold")
    for r in rows:
        table.add_row(*[c or "-" for c in r.as_row()])
    console.print(table)
    console.print(f"\nWritten: [bold]{md_path}[/] and [bold]{csv_path}[/]")

    needs_input = sum(1 for r in rows if r.migration_status == "NEEDS_INPUT")
    if needs_input:
        console.print(f"[magenta]{needs_input} row(s) need more information "
                       "before they can be migrated.[/]")


@cli.command()
def selftest() -> None:
    """Verify configuration loads and required tools are present."""
    ok = True
    cfg = Config()
    console.print(f"[green]OK[/] standards.yaml  ingress class = {cfg.standards['ingress']['class']}")
    console.print(f"[green]OK[/] env-matrix.yaml  {len(cfg.env_matrix['environments'])} environments")
    console.print(f"[green]OK[/] rules.yaml       "
                  f"{len(cfg.rules['transform'])} transform, {len(cfg.rules['remediate'])} remediate")
    console.print(f"[green]OK[/] models.yaml      provider = {cfg.models['llm']['provider']}")
    console.print(f"[green]OK[/] mappings.yaml    "
                  f"{len(cfg.mappings.get('storage', []))} storage, "
                  f"{len(cfg.mappings.get('network', []))} network mapping(s)")

    provider = get_provider(cfg.models)
    if provider.available:
        console.print(f"[green]OK[/] llm provider     {provider.name} "
                      f"(model={getattr(provider, 'model', '?')}) reachable")
    else:
        console.print(f"[red]MISSING[/] llm provider  {provider.name} not reachable - "
                      f"the LLM is mandatory for `migrate`. For Ollama: start the daemon "
                      f"and `ollama pull <model>`.")
        ok = False

    import shutil
    for tool in ("helm", "kubeconform", "conftest", "trivy"):
        if shutil.which(tool):
            console.print(f"[green]OK[/] {tool}")
        else:
            console.print(f"[yellow]MISSING[/] {tool} (validators will degrade gracefully)")
            ok = False
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    cli()