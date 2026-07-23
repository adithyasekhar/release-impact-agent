"""Data models for the integration inventory."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class WWSDependency:
    """A dependency on a Workday Web Service (SOAP)."""

    service: str          # e.g. "Human_Resources"
    version: str          # e.g. "v43.0" ("" if unknown)
    operations: list[str] = field(default_factory=list)  # e.g. ["Get_Workers"]

    def key(self) -> str:
        return f"{self.service}:{self.version or '?'}"


@dataclass
class RaaSDependency:
    """A dependency on a Report-as-a-Service custom report."""

    owner: str
    report: str
    output_format: str = ""   # e.g. "csv", "xml" if detectable

    def key(self) -> str:
        return f"{self.owner}/{self.report}"


@dataclass
class RestDependency:
    """A dependency on a Workday REST API endpoint (ccx/api/...)."""

    path: str          # normalized path, tenant stripped
    version: str = ""  # e.g. "v1" if present in path


@dataclass
class Artifact:
    """One integration artifact discovered in the workspace.

    kind is one of: "studio_assembly", "eib", "unknown_xml".
    """

    name: str
    kind: str
    path: str
    wws: list[WWSDependency] = field(default_factory=list)
    raas: list[RaaSDependency] = field(default_factory=list)
    rest: list[RestDependency] = field(default_factory=list)
    external_endpoints: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Inventory:
    """The full scanned inventory."""

    root: str
    artifacts: list[Artifact] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"root": self.root, "artifacts": [a.to_dict() for a in self.artifacts]}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Inventory:
        inv = cls(root=data.get("root", ""))
        for a in data.get("artifacts", []):
            inv.artifacts.append(
                Artifact(
                    name=a["name"],
                    kind=a["kind"],
                    path=a["path"],
                    wws=[WWSDependency(**w) for w in a.get("wws", [])],
                    raas=[RaaSDependency(**r) for r in a.get("raas", [])],
                    rest=[RestDependency(**r) for r in a.get("rest", [])],
                    external_endpoints=list(a.get("external_endpoints", [])),
                    notes=list(a.get("notes", [])),
                )
            )
        return inv
