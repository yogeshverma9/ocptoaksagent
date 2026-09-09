from __future__ import annotations

from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any


class Severity(str, Enum):
    BLOCK = "BLOCK"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    INFO = "INFO"
    NEEDS_INPUT = "NEEDS_INPUT"


_ORDER = {
    Severity.BLOCK: 0,
    Severity.HIGH: 1,
    Severity.MEDIUM: 2,
    Severity.LOW: 3,
    Severity.NEEDS_INPUT: 4,
    Severity.INFO: 5,
}


@dataclass
class Finding:
    rule_id: str
    title: str
    severity: Severity
    path: str
    detail: str
    remediation: str = ""
    line: int | None = None
    auto_fixed: bool = False

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["severity"] = self.severity.value
        return d


@dataclass
class Verdict:
    decision: str
    rationale: str
    counts: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def sort_findings(findings: list[Finding]) -> list[Finding]:
    return sorted(findings, key=lambda f: (_ORDER[f.severity], f.rule_id, f.path))


WORKBOOK_COLUMNS = [
    "Namespace",
    "Deployment",
    "Route",
    "Service Type",
    "PVC",
    "Storage Type",
    "Database",
    "Secrets/ConfigMaps",
    "AKS Equivalent",
    "Owner",
    "Dependencies",
    "Migration Status",
    "Risks",
]


@dataclass
class WorkbookRow:
    namespace: str = ""
    deployment: str = ""
    route: str = ""
    service_type: str = ""
    pvc: str = ""
    storage_type: str = ""
    database: str = ""
    secrets: str = ""
    aks_equivalent: str = ""
    owner: str = ""
    dependencies: str = ""
    migration_status: str = ""
    risks: str = ""

    def as_row(self) -> list[str]:
        return [
            self.namespace, self.deployment, self.route, self.service_type,
            self.pvc, self.storage_type, self.database, self.secrets,
            self.aks_equivalent, self.owner, self.dependencies,
            self.migration_status, self.risks,
        ]