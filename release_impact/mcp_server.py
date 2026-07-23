"""MCP server mode — drive the agent from Claude Desktop or Claude Code.

Requires the optional dependency:  pip install "release-impact-agent[mcp]"
Register with:  claude mcp add release-impact -- release-impact mcp
"""

from __future__ import annotations

import json
from pathlib import Path

try:
    from mcp.server.fastmcp import FastMCP
except ImportError as exc:  # pragma: no cover
    raise SystemExit(
        "MCP mode needs the 'mcp' package: pip install 'release-impact-agent[mcp]'"
    ) from exc

from .analysis.classifier import classify_fallback, classify_with_claude
from .analysis.matcher import match_all
from .inventory.eib_scanner import scan_eib
from .inventory.models import Inventory
from .inventory.studio_scanner import scan_studio
from .release_notes.loader import load_release_notes
from .report.html_report import render_html
from .report.markdown_report import render_markdown

mcp = FastMCP(
    "release-impact",
    instructions=(
        "Workday Release Impact Agent. Typical flow: scan_inventory on the "
        "user's Studio workspace, then analyze_impact with a release-notes "
        "file, then generate_report. Findings are deterministic and carry "
        "evidence; treat severities as advisory."
    ),
)

_state: dict = {"inventory": None, "items": None, "findings": None}


@mcp.tool()
def scan_inventory(workspace_path: str) -> str:
    """Scan a Workday Studio workspace / folder of integration exports.

    Returns a JSON summary of discovered artifacts and their Workday
    dependencies (WWS services+versions, operations, RaaS reports, REST).
    """
    root = Path(workspace_path).expanduser()
    if not root.is_dir():
        return json.dumps({"error": f"Not a directory: {root}"})
    inv = scan_studio(root)
    eib = scan_eib(root)
    seen = {a.path for a in inv.artifacts}
    inv.artifacts.extend(a for a in eib.artifacts if a.path not in seen)
    _state["inventory"] = inv
    return json.dumps(inv.to_dict(), indent=2)


@mcp.tool()
def analyze_impact(release_notes_path: str, use_claude: bool = False) -> str:
    """Match a release-notes export (.csv/.json) against the scanned inventory.

    Run scan_inventory first. Set use_claude=true to refine severities and
    remediation with the Anthropic API (needs ANTHROPIC_API_KEY).
    """
    inv: Inventory | None = _state.get("inventory")
    if inv is None:
        return json.dumps({"error": "Run scan_inventory first."})
    path = Path(release_notes_path).expanduser()
    if not path.is_file():
        return json.dumps({"error": f"Not a file: {path}"})
    items = load_release_notes(path)
    findings = match_all(inv, items)
    if use_claude:
        findings = classify_with_claude(findings, {i.id: i.to_dict() for i in items})
    else:
        findings = classify_fallback(findings)
    _state["items"], _state["findings"] = items, findings
    return json.dumps({
        "summary": {
            "artifacts": len(inv.artifacts),
            "release_items": len(items),
            "findings": len(findings),
        },
        "findings": [f.to_dict() for f in findings],
    }, indent=2)


@mcp.tool()
def generate_report(output_dir: str, release_label: str = "") -> str:
    """Write impact-report.md and impact-report.html to output_dir.

    Run scan_inventory and analyze_impact first.
    """
    if _state.get("findings") is None:
        return json.dumps({"error": "Run scan_inventory and analyze_impact first."})
    outdir = Path(output_dir).expanduser()
    outdir.mkdir(parents=True, exist_ok=True)
    inv, items, findings = _state["inventory"], _state["items"], _state["findings"]
    (outdir / "impact-report.md").write_text(
        render_markdown(inv, items, findings, release_label))
    (outdir / "impact-report.html").write_text(
        render_html(inv, items, findings, release_label))
    return json.dumps({"written": [str(outdir / "impact-report.md"),
                                   str(outdir / "impact-report.html")]})


@mcp.tool()
def get_artifact_details(artifact_name: str) -> str:
    """Full dependency detail for one scanned artifact, plus its findings."""
    inv: Inventory | None = _state.get("inventory")
    if inv is None:
        return json.dumps({"error": "Run scan_inventory first."})
    artifact = next((a for a in inv.artifacts if a.name == artifact_name), None)
    if artifact is None:
        names = [a.name for a in inv.artifacts]
        return json.dumps({"error": f"Unknown artifact. Scanned: {names}"})
    findings = [
        f.to_dict() for f in (_state.get("findings") or [])
        if f.artifact_name == artifact_name
    ]
    return json.dumps({"artifact": artifact.to_dict(), "findings": findings}, indent=2)


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
