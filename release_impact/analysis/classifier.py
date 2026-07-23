"""Optional Claude-powered refinement of findings.

Mirrors the classifier pattern from integration-monitor: deterministic
rules produce the findings; Claude reviews each finding with full context
and (a) confirms or adjusts severity, (b) writes a concrete remediation
step, (c) drafts a test-plan line. If no ANTHROPIC_API_KEY is configured,
a rule-based fallback fills in generic remediation text so the agent is
fully usable offline.
"""

from __future__ import annotations

import json
import os

from .matcher import SEVERITIES, Finding

DEFAULT_MODEL = os.environ.get("CLAUDE_MODEL", "claude-sonnet-4-5")

_SYSTEM = """You are a Workday integration release-impact analyst.
You receive findings that were produced by deterministic matching between a
Workday release item and a customer's integration artifact. For each finding:
1. Confirm or adjust the severity (critical/high/medium/low/info). Only adjust
   when the evidence clearly warrants it; explain nothing.
2. Write ONE concrete remediation step (imperative, <= 30 words).
3. Write ONE regression-test line for the artifact (imperative, <= 25 words).
Respond with a JSON array, one object per finding, in the same order:
[{"severity": "...", "remediation": "...", "test": "..."}]"""

_FALLBACK_REMEDIATION = {
    "retirement": "Upgrade the pinned WWS version / replace the retired feature before the effective release, then regression-test the integration end to end.",
    "deprecation": "Plan an upgrade away from the deprecated version/feature this cycle; it will be removed in a future release.",
    "breaking_change": "Review the changed behavior against this artifact's request/response handling and update mappings before the release window.",
    "change": "Review the release note against this artifact's field mappings and confirm behavior in the preview tenant.",
    "new_feature": "Optional: evaluate whether this new capability simplifies or replaces part of this integration.",
    "info": "No action expected; noted for awareness.",
}


def classify_fallback(findings: list[Finding]) -> list[Finding]:
    for f in findings:
        if not f.remediation:
            f.remediation = _FALLBACK_REMEDIATION.get(f.item_type, _FALLBACK_REMEDIATION["info"])
        f.classified_by = "rules"
    return findings


def classify_with_claude(
    findings: list[Finding],
    items_by_id: dict[str, dict],
    model: str = DEFAULT_MODEL,
    batch_size: int = 20,
) -> list[Finding]:
    """Refine findings with Claude. Falls back to rules on any error."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return classify_fallback(findings)

    try:
        import anthropic
    except ImportError:
        return classify_fallback(findings)

    client = anthropic.Anthropic(api_key=api_key)

    for start in range(0, len(findings), batch_size):
        batch = findings[start : start + batch_size]
        payload = [
            {
                "artifact": f.artifact_name,
                "kind": f.artifact_kind,
                "evidence": f.reasons,
                "rule_severity": f.severity,
                "release_item": items_by_id.get(f.item_id, {"title": f.item_title}),
            }
            for f in batch
        ]
        try:
            resp = client.messages.create(
                model=model,
                max_tokens=4096,
                system=_SYSTEM,
                messages=[{"role": "user", "content": json.dumps(payload, indent=1)}],
            )
            text = resp.content[0].text.strip()
            if text.startswith("```"):
                text = text.strip("`").lstrip("json").strip()
            results = json.loads(text)
            for f, r in zip(batch, results, strict=False):
                sev = str(r.get("severity", f.severity)).lower()
                if sev in SEVERITIES:
                    f.severity = sev
                f.remediation = r.get("remediation", "") or f.remediation
                test = r.get("test", "")
                if test:
                    f.remediation = f"{f.remediation} Test: {test}"
                f.classified_by = "claude"
        except Exception:  # network, parse, refusal — degrade gracefully
            classify_fallback(batch)

    # Ensure nothing is left without remediation text
    return classify_fallback(findings) if any(not f.remediation for f in findings) else findings
