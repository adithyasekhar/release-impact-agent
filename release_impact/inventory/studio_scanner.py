"""Scanner for Workday Studio assembly projects.

Extracts Workday-facing dependencies from Studio assembly XML without
requiring Studio itself: WWS SOAP services + versions + operations,
RaaS report references, Workday REST endpoints, and external endpoints.

The parsing is deliberately tolerant — Studio XML in the wild varies by
Studio version and by how integrations were hand-edited, so we combine
XML parsing with targeted regex passes over the raw text.
"""

from __future__ import annotations

import re
from pathlib import Path

from .models import Artifact, Inventory, RaaSDependency, RestDependency, WWSDependency

# https://<host>/ccx/service/<tenant>/<Service_Name>/<version>
_WWS_URL = re.compile(
    r"ccx/service/(?!customreport2)([A-Za-z0-9_\-]+)/([A-Za-z_]+)(?:/(v?[\d.]+))?",
)

# https://<host>/ccx/service/customreport2/<tenant>/<owner>/<report>
_RAAS_URL = re.compile(
    r"ccx/service/customreport2/([A-Za-z0-9_\-]+)/([A-Za-z0-9_\-%.@]+)/([A-Za-z0-9_\-%.]+)"
)

# https://<host>/ccx/api/<...path>
_REST_URL = re.compile(r"ccx/api/([A-Za-z0-9_\-/.{}]+)")

# WWS operation names: Get_Workers, Submit_Hire, Put_Applicant, Import_..., etc.
_WWS_OPERATION = re.compile(
    r"\b((?:Get|Put|Submit|Import|Cancel|Rescind|Approve|Deny|Add|Update|Maintain|"
    r"Assign|Change|End|Manage|Remove|Reassign|Terminate|Correct)_[A-Z][A-Za-z0-9_]+)\b"
)

# Non-Workday endpoints referenced by the assembly (outbound HTTP, SFTP, SMTP)
_EXTERNAL_URL = re.compile(r"\b(?:https?|sftp|ftps)://([A-Za-z0-9.\-]+)[^\s\"'<>]*")

_WORKDAY_HOSTS = ("workday.com", "workdaysuv.com", "myworkday.com")

# Version declared separately from the URL (common in hand-parameterized assemblies)
_VERSION_PROP = re.compile(
    r"(?:web[\s_-]?service[\s_-]?version|wws[\s_-]?version)[\"'>=\s:]*v?([\d]+\.[\d]+)",
    re.IGNORECASE,
)

STUDIO_FILENAMES = ("assembly.xml", ".assembly")


def looks_like_studio_project(path: Path) -> bool:
    """A directory is a Studio project if it contains an assembly file."""
    return any((path / n).exists() for n in ("assembly.xml",)) or any(
        path.glob("*.assembly")
    )


def _find_assembly_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for pattern in ("**/assembly.xml", "**/*.assembly"):
        files.extend(p for p in root.glob(pattern) if p.is_file())
    # Also pick up sibling XSLT/diagram files? No — the assembly is the dependency surface.
    return sorted(set(files))


def scan_assembly_text(text: str) -> tuple[
    list[WWSDependency], list[RaaSDependency], list[RestDependency], list[str], list[str]
]:
    """Extract dependencies from raw assembly XML text."""
    notes: list[str] = []

    # --- WWS SOAP services ---
    services: dict[str, WWSDependency] = {}
    for m in _WWS_URL.finditer(text):
        _tenant, service, version = m.group(1), m.group(2), m.group(3) or ""
        version = version if version.startswith("v") else (f"v{version}" if version else "")
        dep = services.setdefault(service, WWSDependency(service=service, version=version))
        if version and not dep.version:
            dep.version = version

    # Versions declared away from the URL
    loose_versions = _VERSION_PROP.findall(text)
    if loose_versions:
        for dep in services.values():
            if not dep.version:
                dep.version = f"v{loose_versions[0]}"
                notes.append(
                    f"Version for {dep.service} inferred from a version property "
                    f"(v{loose_versions[0]}) — verify in the assembly."
                )

    # Operations (attach to every service; Studio XML rarely scopes them cleanly)
    operations = sorted(set(_WWS_OPERATION.findall(text)))
    for dep in services.values():
        dep.operations = operations
    if operations and not services:
        # Operations present but no service URL (endpoint may be a launch parameter)
        services["_unresolved"] = WWSDependency(
            service="_unresolved", version="", operations=operations
        )
        notes.append(
            "WWS operations found but no service URL — endpoint is likely a "
            "launch parameter. Service name could not be resolved statically."
        )

    # --- RaaS ---
    raas = [
        RaaSDependency(owner=m.group(2), report=m.group(3))
        for m in _RAAS_URL.finditer(text)
    ]
    raas = list({r.key(): r for r in raas}.values())

    # --- REST ---
    rest: dict[str, RestDependency] = {}
    for m in _REST_URL.finditer(text):
        path = m.group(1).rstrip("/")
        vm = re.match(r"(v\d+)/", path)
        rest.setdefault(path, RestDependency(path=path, version=vm.group(1) if vm else ""))

    # --- External endpoints ---
    external = sorted(
        {
            m.group(1)
            for m in _EXTERNAL_URL.finditer(text)
            if not any(h in m.group(1) for h in _WORKDAY_HOSTS)
            and m.group(1) not in ("localhost",)
            and "." in m.group(1)
        }
    )

    return list(services.values()), raas, list(rest.values()), external, notes


def scan_studio(root: Path) -> Inventory:
    """Scan a Studio workspace (or any folder tree) for assembly files."""
    inv = Inventory(root=str(root))
    for f in _find_assembly_files(root):
        text = f.read_text(errors="replace")
        wws, raas, rest, external, notes = scan_assembly_text(text)
        # Project name = folder containing the assembly (or file stem for *.assembly)
        name = f.parent.name if f.name == "assembly.xml" else f.stem
        inv.artifacts.append(
            Artifact(
                name=name,
                kind="studio_assembly",
                path=str(f.relative_to(root)),
                wws=wws,
                raas=raas,
                rest=rest,
                external_endpoints=external,
                notes=notes,
            )
        )
    return inv
