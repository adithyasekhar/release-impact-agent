"""Markdown impact report generator."""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone

from ..analysis.matcher import SEVERITIES, Finding
from ..inventory.models import Inventory
from ..release_notes.models import ReleaseItem

_SEV_LABEL = {
    "critical": "🔴 Critical",
    "high": "🟠 High",
    "medium": "🟡 Medium",
    "low": "🟢 Low",
    "info": "⚪ Info",
}


def render_markdown(
    inventory: Inventory,
    items: list[ReleaseItem],
    findings: list[Finding],
    release_label: str = "",
) -> str:
    counts = Counter(f.severity for f in findings)
    artifacts_hit = len({f.artifact_name for f in findings})
    if not release_label:
        release_label = items[0].release if items and items[0].release else "Workday Release"

    out: list[str] = []
    out.append(f"# {release_label} — Integration Impact Report")
    out.append("")
    today = datetime.now(tz=timezone.utc).date().isoformat()
    out.append(f"*Generated {today} by release-impact-agent*")
    out.append("")
    out.append("## Summary")
    out.append("")
    out.append("| Scanned artifacts | Release items | Affected artifacts | Findings |")
    out.append("|---|---|---|---|")
    out.append(f"| {len(inventory.artifacts)} | {len(items)} | {artifacts_hit} | {len(findings)} |")
    out.append("")
    out.append(" · ".join(f"{_SEV_LABEL[s]}: **{counts.get(s, 0)}**" for s in SEVERITIES))
    out.append("")

    if not findings:
        out.append("No release items matched the scanned inventory. Review the unmatched "
                   "items below for tenant-level (non-integration) impact.")
        out.append("")

    for sev in SEVERITIES:
        sev_findings = [f for f in findings if f.severity == sev]
        if not sev_findings:
            continue
        out.append(f"## {_SEV_LABEL[sev]} ({len(sev_findings)})")
        out.append("")
        for f in sev_findings:
            out.append(f"### `{f.artifact_name}` ← {f.item_title}")
            out.append("")
            out.append(f"- **Artifact**: `{f.artifact_path}` ({f.artifact_kind})")
            release_suffix = f" ({f.release})" if f.release else ""
            out.append(f"- **Release item**: {f.item_id} — "
                       f"{f.item_type.replace('_', ' ')}{release_suffix}")
            out.append("- **Evidence**: " + "; ".join(f.reasons))
            if f.remediation:
                out.append(f"- **Recommended action**: {f.remediation}")
            out.append(f"- **Classified by**: {f.classified_by}")
            out.append("")

    matched_ids = {f.item_id for f in findings}
    unmatched = [i for i in items if i.id not in matched_ids]
    if unmatched:
        out.append(f"## Not matched to any artifact ({len(unmatched)})")
        out.append("")
        out.append("These items didn't match scanned integrations; they may still need "
                   "functional or tenant-configuration review.")
        out.append("")
        for i in unmatched:
            out.append(f"- **{i.id}** {i.title} *({i.item_type.replace('_', ' ')})*")
        out.append("")

    return "\n".join(out).rstrip() + "\n"
