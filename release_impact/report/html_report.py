"""Self-contained HTML dashboard generator (no external assets)."""

from __future__ import annotations

import html
from collections import Counter
from datetime import datetime, timezone

from ..analysis.matcher import SEVERITIES, Finding
from ..inventory.models import Inventory
from ..release_notes.models import ReleaseItem

_SEV_COLOR = {
    "critical": "#b3261e",
    "high": "#c2410c",
    "medium": "#a16207",
    "low": "#15803d",
    "info": "#64748b",
}

_CSS = """
:root { color-scheme: light dark; }
* { box-sizing: border-box; }
body { font-family: -apple-system, 'Segoe UI', Roboto, sans-serif; margin: 0;
  background: #f6f7f9; color: #1c1e21; }
@media (prefers-color-scheme: dark) {
  body { background: #131417; color: #e8e9ec; }
  .card, tr { background: #1d1f24 !important; }
  th { background: #24262c !important; }
}
.wrap { max-width: 1080px; margin: 0 auto; padding: 32px 20px 64px; }
h1 { font-size: 1.5rem; margin: 0 0 4px; }
.sub { color: #6b7280; margin-bottom: 24px; font-size: .9rem; }
.tiles { display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
  gap: 12px; margin-bottom: 28px; }
.card { background: #fff; border-radius: 10px; padding: 14px 16px;
  box-shadow: 0 1px 2px rgba(0,0,0,.06); }
.card .n { font-size: 1.6rem; font-weight: 700; }
.card .l { font-size: .78rem; color: #6b7280; text-transform: uppercase;
  letter-spacing: .04em; }
table { width: 100%; border-collapse: separate; border-spacing: 0 6px; }
th { text-align: left; font-size: .75rem; text-transform: uppercase;
  letter-spacing: .05em; color: #6b7280; padding: 8px 12px; background: #eef0f3;
  position: sticky; top: 0; }
tr { background: #fff; }
td { padding: 10px 12px; vertical-align: top; font-size: .88rem;
  border-top: 1px solid rgba(0,0,0,.04); }
td:first-child, th:first-child { border-radius: 8px 0 0 8px; }
td:last-child, th:last-child { border-radius: 0 8px 8px 0; }
.badge { display: inline-block; padding: 2px 10px; border-radius: 999px;
  color: #fff; font-size: .72rem; font-weight: 600; text-transform: uppercase; }
.mono { font-family: ui-monospace, Menlo, monospace; font-size: .82rem; }
.reason { color: #6b7280; font-size: .8rem; }
.controls { margin-bottom: 14px; }
.controls button { border: 1px solid #d1d5db; background: transparent; color: inherit;
  padding: 5px 12px; border-radius: 999px; margin-right: 6px; cursor: pointer;
  font-size: .8rem; }
.controls button.active { border-color: currentColor; font-weight: 600; }
"""

_JS = """
function filterSev(sev, btn) {
  document.querySelectorAll('.controls button').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  document.querySelectorAll('tbody tr').forEach(tr => {
    tr.style.display = (sev === 'all' || tr.dataset.sev === sev) ? '' : 'none';
  });
}
"""


def render_html(
    inventory: Inventory,
    items: list[ReleaseItem],
    findings: list[Finding],
    release_label: str = "",
) -> str:
    if not release_label:
        release_label = items[0].release if items and items[0].release else "Workday Release"
    counts = Counter(f.severity for f in findings)
    artifacts_hit = len({f.artifact_name for f in findings})
    e = html.escape

    tiles = [
        ("Artifacts scanned", len(inventory.artifacts), "#334155"),
        ("Release items", len(items), "#334155"),
        ("Affected artifacts", artifacts_hit, "#334155"),
    ] + [(s.capitalize(), counts.get(s, 0), _SEV_COLOR[s]) for s in SEVERITIES]

    tile_html = "".join(
        f'<div class="card"><div class="n" style="color:{c}">{n}</div>'
        f'<div class="l">{e(label)}</div></div>'
        for label, n, c in tiles
    )

    rows = []
    for f in findings:
        rows.append(
            f'<tr data-sev="{f.severity}">'
            f'<td><span class="badge" style="background:{_SEV_COLOR[f.severity]}">'
            f'{f.severity}</span></td>'
            f'<td><span class="mono">{e(f.artifact_name)}</span><br>'
            f'<span class="reason">{e(f.artifact_kind)} · {e(f.artifact_path)}</span></td>'
            f'<td>{e(f.item_title)}<br><span class="reason">{e(f.item_id)} · '
            f'{e(f.item_type.replace("_", " "))}</span></td>'
            f'<td><span class="reason">{e("; ".join(f.reasons))}</span></td>'
            f'<td>{e(f.remediation)}</td></tr>'
        )

    buttons = '<button class="active" onclick="filterSev(\'all\', this)">All</button>' + "".join(
        f'<button onclick="filterSev(\'{s}\', this)">{s.capitalize()} '
        f'({counts.get(s, 0)})</button>'
        for s in SEVERITIES
        if counts.get(s, 0)
    )

    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{e(release_label)} — Integration Impact</title>
<style>{_CSS}</style></head>
<body><div class="wrap">
<h1>{e(release_label)} — Integration Impact Report</h1>
<div class="sub">Generated {datetime.now(tz=timezone.utc).date().isoformat()} · release-impact-agent</div>
<div class="tiles">{tile_html}</div>
<div class="controls">{buttons}</div>
<table><thead><tr><th>Severity</th><th>Artifact</th><th>Release item</th>
<th>Evidence</th><th>Recommended action</th></tr></thead>
<tbody>{''.join(rows) or '<tr><td colspan="5">No findings 🎉</td></tr>'}</tbody></table>
</div><script>{_JS}</script></body></html>
"""
