"""Deterministic matching of release items to inventory artifacts.

This layer never calls an LLM. Every finding it produces carries an
explicit, human-checkable ``reason`` so the report is auditable. The
optional Claude classifier only *refines* severity and adds remediation
text on top of these findings — it never invents matches.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from ..inventory.models import Artifact, Inventory
from ..release_notes.models import ReleaseItem

SEVERITIES = ("critical", "high", "medium", "low", "info")

_TYPE_BASE_SEVERITY = {
    "retirement": "critical",
    "deprecation": "high",
    "breaking_change": "high",
    "change": "medium",
    "new_feature": "low",
    "info": "info",
}


@dataclass
class Finding:
    """A release item matched to one artifact, with evidence."""

    artifact_name: str
    artifact_kind: str
    artifact_path: str
    item_id: str
    item_title: str
    item_type: str
    release: str
    severity: str
    reasons: list[str] = field(default_factory=list)
    remediation: str = ""       # filled by classifier (or left empty)
    classified_by: str = "rules"  # "rules" or "claude"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _version_leq(a: str, b: str) -> bool:
    """True if version a <= b (e.g. v34.0 <= v35.0). Unknown versions -> False."""
    try:
        pa = tuple(int(x) for x in a.lstrip("v").split("."))
        pb = tuple(int(x) for x in b.lstrip("v").split("."))
        return pa <= pb
    except ValueError:
        return False


def match_item_to_artifact(item: ReleaseItem, artifact: Artifact) -> list[str]:
    """Return the list of reasons this item affects this artifact (empty = no match)."""
    reasons: list[str] = []

    artifact_services = {w.service for w in artifact.wws}
    artifact_ops = {op for w in artifact.wws for op in w.operations}
    artifact_reports = {r.report.lower() for r in artifact.raas}

    # Service-level match
    for svc in item.affected_services:
        if svc in artifact_services:
            dep = next(w for w in artifact.wws if w.service == svc)
            reasons.append(f"uses WWS service {svc} {dep.version or '(version unknown)'}")

    # Version match: a retirement/deprecation of vX affects artifacts pinned <= vX
    if item.affected_versions and item.item_type in ("retirement", "deprecation", "breaking_change"):
        ceiling = max(item.affected_versions, key=lambda v: _version_leq("v0.0", v) and v)
        for w in artifact.wws:
            if w.version and any(_version_leq(w.version, v) for v in item.affected_versions):
                if item.affected_services and w.service not in item.affected_services:
                    continue
                reasons.append(
                    f"pinned to {w.service} {w.version}, at or below affected {ceiling}"
                )

    # Operation match
    for op in item.affected_operations:
        if op in artifact_ops:
            reasons.append(f"calls operation {op}")

    # RaaS report match
    for rep in item.affected_reports:
        if rep.lower() in artifact_reports:
            reasons.append(f"consumes RaaS report {rep}")

    # REST path match
    for frag in item.affected_rest_paths:
        for r in artifact.rest:
            if frag.strip("/") in r.path:
                reasons.append(f"calls REST endpoint {r.path}")

    return sorted(set(reasons))


def base_severity(item: ReleaseItem, reasons: list[str]) -> str:
    sev = _TYPE_BASE_SEVERITY.get(item.item_type, "info")
    # A version-pinned match on a retirement is the worst case; already critical.
    # Downgrade service-only matches on "change" items slightly? Keep simple + honest.
    if item.setup_required and sev in ("low", "info"):
        sev = "medium"
    return sev


def match_all(inventory: Inventory, items: list[ReleaseItem]) -> list[Finding]:
    findings: list[Finding] = []
    for item in items:
        for artifact in inventory.artifacts:
            reasons = match_item_to_artifact(item, artifact)
            if not reasons:
                continue
            findings.append(
                Finding(
                    artifact_name=artifact.name,
                    artifact_kind=artifact.kind,
                    artifact_path=artifact.path,
                    item_id=item.id,
                    item_title=item.title,
                    item_type=item.item_type,
                    release=item.release,
                    severity=base_severity(item, reasons),
                    reasons=reasons,
                )
            )
    order = {s: i for i, s in enumerate(SEVERITIES)}
    findings.sort(key=lambda f: (order.get(f.severity, 99), f.artifact_name, f.item_id))
    return findings


def unmatched_items(items: list[ReleaseItem], findings: list[Finding]) -> list[ReleaseItem]:
    matched_ids = {f.item_id for f in findings}
    return [i for i in items if i.id not in matched_ids]
