from pathlib import Path

from release_impact.inventory.studio_scanner import scan_studio

FIXTURES = Path(__file__).parent / "fixtures" / "studio_workspace"


def test_finds_both_projects():
    inv = scan_studio(FIXTURES)
    names = {a.name for a in inv.artifacts}
    assert {"INT001_Worker_Sync", "INT002_Comp_Report"} <= names


def test_extracts_wws_service_and_version():
    inv = scan_studio(FIXTURES)
    int001 = next(a for a in inv.artifacts if a.name == "INT001_Worker_Sync")
    hr = next(w for w in int001.wws if w.service == "Human_Resources")
    assert hr.version == "v34.0"
    assert "Get_Workers" in hr.operations


def test_extracts_raas_and_rest():
    inv = scan_studio(FIXTURES)
    int002 = next(a for a in inv.artifacts if a.name == "INT002_Comp_Report")
    assert any(r.report.startswith("INT002_Comp_Extract") for r in int002.raas)
    assert any("workers" in r.path for r in int002.rest)
    comp = next(w for w in int002.wws if w.service == "Compensation")
    assert comp.version == "v42.0"
    assert "Submit_Compensation_Change" in comp.operations


def test_external_endpoints_exclude_workday():
    inv = scan_studio(FIXTURES)
    int001 = next(a for a in inv.artifacts if a.name == "INT001_Worker_Sync")
    assert "api.examplevendor.com" in int001.external_endpoints
    assert not any("workday.com" in e for e in int001.external_endpoints)
