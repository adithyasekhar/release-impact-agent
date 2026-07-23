"""release-impact CLI.

Commands:
  scan     Scan a workspace for Studio/EIB artifacts -> inventory.json
  analyze  Match release notes against an inventory -> findings.json
  report   Render Markdown + HTML reports from findings
  run      scan + analyze + report (+ optional Slack digest) in one shot
  mcp      Start the MCP server (stdio) for Claude Desktop / Claude Code
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .analysis.classifier import classify_fallback, classify_with_claude
from .analysis.matcher import Finding, match_all
from .inventory.eib_scanner import scan_eib
from .inventory.models import Inventory
from .inventory.studio_scanner import scan_studio
from .release_notes.loader import load_release_notes


def _scan(root: Path) -> Inventory:
    inv = scan_studio(root)
    eib = scan_eib(root)
    seen = {a.path for a in inv.artifacts}
    inv.artifacts.extend(a for a in eib.artifacts if a.path not in seen)
    return inv


def _analyze(inv: Inventory, notes_path: Path, use_claude: bool) -> tuple[list, list[Finding]]:
    items = load_release_notes(notes_path)
    findings = match_all(inv, items)
    if use_claude:
        findings = classify_with_claude(findings, {i.id: i.to_dict() for i in items})
    else:
        findings = classify_fallback(findings)
    return items, findings


def cmd_scan(args: argparse.Namespace) -> int:
    inv = _scan(Path(args.workspace))
    out = Path(args.output)
    out.write_text(json.dumps(inv.to_dict(), indent=2))
    print(f"Scanned {len(inv.artifacts)} artifact(s) -> {out}")
    for a in inv.artifacts:
        services = ", ".join(w.key() for w in a.wws) or "-"
        print(f"  [{a.kind}] {a.name}  WWS: {services}  RaaS: {len(a.raas)}")
    return 0


def cmd_analyze(args: argparse.Namespace) -> int:
    inv = Inventory.from_dict(json.loads(Path(args.inventory).read_text()))
    items, findings = _analyze(inv, Path(args.notes), use_claude=not args.no_claude)
    out = Path(args.output)
    out.write_text(json.dumps({
        "items": [i.to_dict() for i in items],
        "findings": [f.to_dict() for f in findings],
    }, indent=2))
    print(f"{len(findings)} finding(s) from {len(items)} release item(s) -> {out}")
    return 0


def cmd_report(args: argparse.Namespace) -> int:
    from .report.html_report import render_html
    from .report.markdown_report import render_markdown

    inv = Inventory.from_dict(json.loads(Path(args.inventory).read_text()))
    data = json.loads(Path(args.findings).read_text())
    from .release_notes.models import ReleaseItem
    items = [ReleaseItem.from_dict(d) for d in data["items"]]
    findings = [Finding(**f) for f in data["findings"]]

    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    (outdir / "impact-report.md").write_text(
        render_markdown(inv, items, findings, args.release_label))
    (outdir / "impact-report.html").write_text(
        render_html(inv, items, findings, args.release_label))
    print(f"Reports written to {outdir}/impact-report.{{md,html}}")
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    from .report.html_report import render_html
    from .report.markdown_report import render_markdown

    inv = _scan(Path(args.workspace))
    items, findings = _analyze(inv, Path(args.notes), use_claude=not args.no_claude)

    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    (outdir / "inventory.json").write_text(json.dumps(inv.to_dict(), indent=2))
    (outdir / "findings.json").write_text(json.dumps({
        "items": [i.to_dict() for i in items],
        "findings": [f.to_dict() for f in findings],
    }, indent=2))
    (outdir / "impact-report.md").write_text(
        render_markdown(inv, items, findings, args.release_label))
    (outdir / "impact-report.html").write_text(
        render_html(inv, items, findings, args.release_label))

    label = args.release_label or (items[0].release if items else "Workday Release")
    print(f"{len(inv.artifacts)} artifacts, {len(items)} items, {len(findings)} findings")
    print(f"Reports in {outdir}/")

    if args.slack:
        from .notify.slack import send_digest
        if send_digest(findings, label, args.report_url):
            print("Slack digest sent.")
        else:
            print("Slack digest skipped (SLACK_WEBHOOK_URL not set).", file=sys.stderr)

    critical = sum(1 for f in findings if f.severity == "critical")
    if args.fail_on_critical and critical:
        print(f"::error::{critical} critical finding(s)", file=sys.stderr)
        return 2
    return 0


def cmd_mcp(_args: argparse.Namespace) -> int:
    from .mcp_server import main as mcp_main
    mcp_main()
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="release-impact",
                                description="Workday Release Impact Agent")
    sub = p.add_subparsers(dest="command", required=True)

    s = sub.add_parser("scan", help="Scan a workspace for integration artifacts")
    s.add_argument("workspace", help="Studio workspace / folder of integration exports")
    s.add_argument("-o", "--output", default="inventory.json")
    s.set_defaults(func=cmd_scan)

    a = sub.add_parser("analyze", help="Match release notes against an inventory")
    a.add_argument("--inventory", default="inventory.json")
    a.add_argument("--notes", required=True, help="Release notes .csv or .json")
    a.add_argument("--no-claude", action="store_true",
                   help="Skip Claude refinement (rules only)")
    a.add_argument("-o", "--output", default="findings.json")
    a.set_defaults(func=cmd_analyze)

    r = sub.add_parser("report", help="Render reports from findings")
    r.add_argument("--inventory", default="inventory.json")
    r.add_argument("--findings", default="findings.json")
    r.add_argument("--outdir", default="reports")
    r.add_argument("--release-label", default="")
    r.set_defaults(func=cmd_report)

    run = sub.add_parser("run", help="scan + analyze + report in one shot")
    run.add_argument("workspace")
    run.add_argument("--notes", required=True)
    run.add_argument("--outdir", default="reports")
    run.add_argument("--release-label", default="")
    run.add_argument("--no-claude", action="store_true")
    run.add_argument("--slack", action="store_true", help="Send Slack digest")
    run.add_argument("--report-url", default="", help="Link to include in the digest")
    run.add_argument("--fail-on-critical", action="store_true",
                     help="Exit 2 if any critical finding (for CI gates)")
    run.set_defaults(func=cmd_run)

    m = sub.add_parser("mcp", help="Start MCP server (stdio)")
    m.set_defaults(func=cmd_mcp)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
