"""Scanner for EIB (Enterprise Interface Builder) definition exports.

EIB definitions exported from Workday (via "View Integration System" XML
export or implementation-suite extracts) reference a web service +
operation + version for inbound EIBs, and a custom report for outbound
EIBs. As with Studio XML, formats vary — parse tolerantly.
"""

from __future__ import annotations

import re
from pathlib import Path

from .models import Artifact, Inventory, RaaSDependency, WWSDependency
from .studio_scanner import _RAAS_URL, _WWS_OPERATION, _WWS_URL

_EIB_MARKERS = (
    "Integration_System",
    "EIB",
    "Custom_Report_Transformation",
    "Web_Service_Operation",
)

_SERVICE_FIELD = re.compile(
    r"(?:Web_Service|Web_Service_Operation_Reference|Service_Name)[^>]*>\s*([A-Za-z_]+)\s*<",
)
_VERSION_FIELD = re.compile(
    r"(?:Web_Service_Version|Version)[^>]*>\s*v?([\d]+\.[\d]+)\s*<",
)
_REPORT_FIELD = re.compile(
    r"Custom_Report(?:_Definition)?[^>]*>\s*([A-Za-z0-9_\- ]+)\s*<",
)


def looks_like_eib(text: str) -> bool:
    return any(marker in text for marker in _EIB_MARKERS)


def scan_eib_text(text: str) -> tuple[list[WWSDependency], list[RaaSDependency]]:
    wws: dict[str, WWSDependency] = {}

    # URL-style references first (most reliable)
    for m in _WWS_URL.finditer(text):
        service, version = m.group(2), m.group(3) or ""
        version = version if version.startswith("v") else (f"v{version}" if version else "")
        wws.setdefault(service, WWSDependency(service=service, version=version))

    # Field-style references
    for service in _SERVICE_FIELD.findall(text):
        wws.setdefault(service, WWSDependency(service=service, version=""))

    versions = _VERSION_FIELD.findall(text)
    if versions:
        for dep in wws.values():
            if not dep.version:
                dep.version = f"v{versions[0]}"

    ops = sorted(set(_WWS_OPERATION.findall(text)))
    for dep in wws.values():
        dep.operations = ops

    raas = [
        RaaSDependency(owner=m.group(2), report=m.group(3))
        for m in _RAAS_URL.finditer(text)
    ]
    for report in _REPORT_FIELD.findall(text):
        raas.append(RaaSDependency(owner="", report=report.strip()))
    raas = list({r.key(): r for r in raas}.values())

    return list(wws.values()), raas


def scan_eib(root: Path) -> Inventory:
    """Scan a folder tree for EIB definition XML exports."""
    inv = Inventory(root=str(root))
    for f in sorted(root.glob("**/*.xml")):
        if f.name == "assembly.xml":  # studio, not EIB
            continue
        text = f.read_text(errors="replace")
        if not looks_like_eib(text):
            continue
        wws, raas = scan_eib_text(text)
        if not wws and not raas:
            continue
        inv.artifacts.append(
            Artifact(
                name=f.stem,
                kind="eib",
                path=str(f.relative_to(root)),
                wws=wws,
                raas=raas,
            )
        )
    return inv
