import json
from pathlib import Path

from release_impact.analysis.classifier import classify_fallback
from release_impact.analysis.matcher import match_all, unmatched_items
from release_impact.inventory.eib_scanner import scan_eib
from release_impact.inventory.studio_scanner import scan_studio
from release_impact.release_notes.loader import load_release_notes
from release_impact.report.html_report import render_html
from release_impact.report.markdown_report import render_markdown

FIXTURES = Path(__file__).parent / "fixtures" / "studio_workspace"
NOTES = Path(__file__).parent.parent / "examples" / "release-notes-2026R2-sample.csv"


def _full_inventory():
    inv = scan_studio(FIXTURES)
    eib = scan_eib(FIXTURES)
    seen = {a.path for a in inv.artifacts}
    inv.artifacts.extend(a for a in eib.artifacts if a.path not in seen)
    return inv


def test_loader_parses_and_enriches():
    items = load_release_notes(NOTES)
    assert len(items) == 7
    retirement = next(i for i in items if i.id == "WN-2026R2-001")
    assert retirement.item_type == "retirement"
    assert "Human_Resources" in retirement.affected_services
    assert "v34.0" in retirement.affected_versions


def test_version_retirement_hits_pinned_artifacts():
    inv = _full_inventory()
    items = load_release_notes(NOTES)
    findings = match_all(inv, items)
    retirement_hits = [f for f in findings if f.item_id == "WN-2026R2-001"]
    hit_names = {f.artifact_name for f in retirement_hits}
    # INT001 pinned at HR v34.0 and EIB at Staffing v33.0 must be flagged
    assert "INT001_Worker_Sync" in hit_names
    assert "EIB_New_Hire_Load" in hit_names
    # INT002 (Compensation v42.0) must NOT be hit by the v34 retirement
    assert "INT002_Comp_Report" not in hit_names
    assert all(f.severity == "critical" for f in retirement_hits)


def test_operation_and_deprecation_match():
    inv = _full_inventory()
    items = load_release_notes(NOTES)
    findings = match_all(inv, items)
    dep = [f for f in findings if f.item_id == "WN-2026R2-003"]
    assert {f.artifact_name for f in dep} == {"INT002_Comp_Report"}
    assert dep[0].severity == "high"
    assert any("Submit_Compensation_Change" in r for r in dep[0].reasons)


def test_unmatched_items_reported():
    inv = _full_inventory()
    items = load_release_notes(NOTES)
    findings = match_all(inv, items)
    leftover_ids = {i.id for i in unmatched_items(items, findings)}
    assert "WN-2026R2-007" in leftover_ids  # payroll dashboard: no integration surface


def test_reports_render():
    inv = _full_inventory()
    items = load_release_notes(NOTES)
    findings = classify_fallback(match_all(inv, items))
    md = render_markdown(inv, items, findings, "2026R2")
    html = render_html(inv, items, findings, "2026R2")
    assert "Integration Impact Report" in md
    assert "INT001_Worker_Sync" in md and "Recommended action" in md
    assert "<html" in html and "INT001_Worker_Sync" in html
    # findings must be JSON-serializable round-trip
    json.dumps([f.to_dict() for f in findings])
