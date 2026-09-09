from __future__ import annotations

import csv
import re
from pathlib import Path
from typing import Any

from .models import WORKBOOK_COLUMNS, WorkbookRow

# Free-text intake format:
#
#   Namespace: billing-prod
#   Deployment: pdfgenerator
#   Route: pdfgenerator.apps.prod05.ocp.internal.spark.co.nz
#   PVC: pdfgen-data-pvc
#   Storage Type: RWX
#   Database: postgres-prod (external)
#   Risks: shared across 3 pods
#
#   Namespace: billing-dev
#   Deployment: pdfgenerator
#   ...
#
# One entry per blank-line-separated block. Keys are case-insensitive and a
# little fuzzy (aliases below); `#` starts a comment line. Unknown keys are
# not dropped - they are carried through under "extra" so nothing the user
# typed is silently lost, even if the workbook doesn't have a column for it.

_ALIASES: dict[str, str] = {
    "namespace": "namespace", "ns": "namespace", "project": "namespace",
    "deployment": "deployment", "app": "deployment", "application": "deployment",
    "service": "deployment", "workload": "deployment", "component": "deployment",
    "route": "route", "host": "route", "hostname": "route", "url": "route", "ingress": "route",
    "service type": "service_type", "servicetype": "service_type",
    "network type": "service_type", "traffic": "service_type", "exposure": "service_type",
    "pvc": "pvc", "volume": "pvc", "storage": "pvc", "persistentvolumeclaim": "pvc",
    "storage type": "storage_type", "access mode": "storage_type", "accessmode": "storage_type",
    "database": "database", "db": "database", "datastore": "database", "data store": "database",
    "secrets": "secrets", "configmaps": "secrets", "secrets/configmaps": "secrets",
    "secretsconfigmaps": "secrets", "config": "secrets",
    "owner": "owner", "team": "owner", "contact": "owner",
    "dependencies": "dependencies", "depends on": "dependencies", "dependson": "dependencies",
    "environment": "environment", "env": "environment",
    "migration status": "migration_status", "migrationstatus": "migration_status", "status": "migration_status",
    "risks": "risks", "risk": "risks", "notes": "risks", "comments": "risks", "comment": "risks",
}

_FIELDS = {
    "namespace", "deployment", "route", "service_type", "pvc", "storage_type",
    "database", "secrets", "owner", "dependencies", "environment",
    "migration_status", "risks",
}


def _normalise_key(key: str) -> str:
    return re.sub(r"\s+", " ", key.strip().lower().rstrip(":"))


def _assign(current: dict[str, Any], extra: dict[str, str], key: str, value: str) -> None:
    field = _ALIASES.get(_normalise_key(key))
    value = value.strip()
    if field:
        # Later lines for the same field append rather than clobber, in case
        # a user lists e.g. multiple secrets on separate lines.
        if current.get(field):
            current[field] = f"{current[field]}, {value}" if value else current[field]
        else:
            current[field] = value
    elif key.strip():
        extra[key.strip()] = value


def parse_intake(text: str) -> list[dict[str, Any]]:
    """Parse the plain-text intake format into a list of entry dicts.

    Each entry is a block of ``Key: Value`` lines separated by a blank line.
    Recognised keys map to canonical fields (see ``_FIELDS``); anything else
    is preserved under ``entry["extra"]``.
    """
    entries: list[dict[str, Any]] = []
    current: dict[str, Any] = {}
    extra: dict[str, str] = {}

    def flush() -> None:
        nonlocal current, extra
        if current or extra:
            if extra:
                current["extra"] = extra
            entries.append(current)
        current, extra = {}, {}

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            flush()
            continue
        if line.startswith("#"):
            continue
        if line.startswith("[") and line.endswith("]") and ":" in line:
            key, value = line[1:-1].split(":", 1)
            _assign(current, extra, key, value)
            continue
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        _assign(current, extra, key, value)
    flush()

    return [e for e in entries if any(e.get(f) for f in _FIELDS)]


def _match_mapping(value: str, table: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not value:
        return None
    v = value.lower()
    for row in table:
        if any(token in v for token in row.get("match", [])):
            return row
    return None


def build_rows(entries: list[dict[str, Any]], cfg) -> list[WorkbookRow]:
    """Turn parsed intake entries into workbook rows, applying config/mappings.yaml."""
    storage_table = cfg.mappings.get("storage", [])
    network_table = cfg.mappings.get("network", [])
    rows: list[WorkbookRow] = []

    for e in entries:
        row = WorkbookRow(
            namespace=e.get("namespace", ""),
            deployment=e.get("deployment", ""),
            route=e.get("route", ""),
            service_type=e.get("service_type", ""),
            pvc=e.get("pvc", ""),
            storage_type=e.get("storage_type", ""),
            database=e.get("database", ""),
            secrets=e.get("secrets", ""),
            owner=e.get("owner", ""),
            dependencies=e.get("dependencies", ""),
        )

        aks_parts: list[str] = []
        risks: list[str] = []

        storage_match = _match_mapping(row.storage_type, storage_table)
        if row.storage_type and storage_match:
            aks_parts.append(f"{storage_match['azureService']} ({storage_match['requirement']})")
        elif row.storage_type and not storage_match:
            risks.append(
                f"Unrecognised storage type '{row.storage_type}' - map manually "
                "against the storage table in config/mappings.yaml."
            )
        elif row.pvc and not row.storage_type:
            risks.append(
                "PVC declared without an access mode/storage type - cannot determine "
                "Azure Disk vs Azure Files vs Azure NetApp Files vs Blob."
            )

        network_matches: list[dict[str, Any]] = []
        if row.route:
            m = _match_mapping("route", network_table)
            if m:
                network_matches.append(m)
            risks.append(
                "Confirm ingress class, TLS certificate and any residual "
                "*.ocp.internal hostnames per config/standards.yaml."
            )
        if row.service_type:
            m = _match_mapping(row.service_type, network_table)
            if m and m not in network_matches:
                network_matches.append(m)
            elif not m:
                risks.append(
                    f"Unrecognised service type '{row.service_type}' - map manually "
                    "against the network table in config/mappings.yaml."
                )
        for m in network_matches:
            label = f"{m['azureService']} ({m['requirement']})"
            if label not in aks_parts:
                aks_parts.append(label)

        if aks_parts:
            row.aks_equivalent = "; ".join(aks_parts)
        elif row.pvc or row.route or row.service_type:
            row.aks_equivalent = "NEEDS_INPUT"

        if row.secrets:
            risks.append(
                "Secrets/ConfigMaps present - migrate via the Azure Key Vault CSI "
                "provider, not literals in values files (config/standards.yaml secrets.backend)."
            )
        if row.database:
            risks.append(
                "Confirm database migration/cutover approach (backup+restore, DMS, "
                "dual-write) and update connection strings/secrets after cutover."
            )

        explicit_status = e.get("migration_status", "").strip()
        unresolved = any(
            r.startswith("Unrecognised") or r.startswith("PVC declared") for r in risks
        )
        if explicit_status:
            row.migration_status = explicit_status.upper().replace(" ", "_")
        elif not row.namespace or not row.deployment:
            row.migration_status = "NEEDS_INPUT"
        elif unresolved:
            row.migration_status = "NEEDS_INPUT"
        else:
            row.migration_status = "NOT_YET_MIGRATED"

        user_risk_note = e.get("risks", "").strip()
        all_risks = ([user_risk_note] if user_risk_note else []) + risks
        row.risks = " | ".join(all_risks) if all_risks else "None noted"

        rows.append(row)

    return rows


def write_workbook(out: Path, rows: list[WorkbookRow]) -> tuple[Path, Path]:
    out.mkdir(parents=True, exist_ok=True)
    md_path = out / "migration_workbook.md"
    csv_path = out / "migration_workbook.csv"

    lines = [
        "# Migration Workbook", "",
        "| " + " | ".join(WORKBOOK_COLUMNS) + " |",
        "|" + "---|" * len(WORKBOOK_COLUMNS),
    ]
    for r in rows:
        cells = [c.replace("|", "\\|") if c else "-" for c in r.as_row()]
        lines.append("| " + " | ".join(cells) + " |")
    if not rows:
        lines.append("| " + " | ".join(["-"] * len(WORKBOOK_COLUMNS)) + " |")
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    with csv_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(WORKBOOK_COLUMNS)
        for r in rows:
            writer.writerow(r.as_row())

    return md_path, csv_path
