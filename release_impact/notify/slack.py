"""Optional Slack digest, following integration-monitor's notifier pattern.

Uses a plain incoming-webhook URL (SLACK_WEBHOOK_URL) — no SDK dependency.
"""

from __future__ import annotations

import json
import os
import urllib.request
from collections import Counter

from ..analysis.matcher import SEVERITIES, Finding

_EMOJI = {"critical": "🔴", "high": "🟠", "medium": "🟡", "low": "🟢", "info": "⚪"}


def build_digest(findings: list[Finding], release_label: str, report_url: str = "") -> dict:
    counts = Counter(f.severity for f in findings)
    header = f"*{release_label} — Integration Impact*"
    summary = "  ".join(
        f"{_EMOJI[s]} {s.capitalize()}: *{counts.get(s, 0)}*" for s in SEVERITIES
    )
    top = [f for f in findings if f.severity in ("critical", "high")][:10]
    lines = [
        f"{_EMOJI[f.severity]} `{f.artifact_name}` — {f.item_title}"
        for f in top
    ]
    text_blocks = [header, summary]
    if lines:
        text_blocks.append("*Top findings:*\n" + "\n".join(lines))
    if report_url:
        text_blocks.append(f"<{report_url}|Full report>")
    return {"text": "\n\n".join(text_blocks)}


def send_digest(findings: list[Finding], release_label: str, report_url: str = "") -> bool:
    url = os.environ.get("SLACK_WEBHOOK_URL")
    if not url:
        return False
    payload = json.dumps(build_digest(findings, release_label, report_url)).encode()
    req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        return resp.status == 200
