"""Data models for Workday release notes / What's New items."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

# Item types, roughly ordered by how much attention they demand.
ITEM_TYPES = (
    "retirement",        # feature/version being removed
    "deprecation",       # announced future removal
    "breaking_change",   # behavior change that can break consumers
    "change",            # behavior change, usually compatible
    "new_feature",       # net-new, opt-in
    "info",              # everything else
)


@dataclass
class ReleaseItem:
    """One item from a Workday release (What's New report row, release note)."""

    id: str
    title: str
    description: str = ""
    item_type: str = "info"            # one of ITEM_TYPES
    functional_area: str = ""          # e.g. "HCM", "Integrations", "Recruiting"
    release: str = ""                  # e.g. "2026R2"
    affected_services: list[str] = field(default_factory=list)   # e.g. ["Human_Resources"]
    affected_versions: list[str] = field(default_factory=list)   # e.g. ["v34.0", "v35.0"]
    affected_operations: list[str] = field(default_factory=list) # e.g. ["Get_Workers"]
    affected_reports: list[str] = field(default_factory=list)    # RaaS report names
    affected_rest_paths: list[str] = field(default_factory=list) # REST path fragments
    setup_required: bool = False
    url: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> ReleaseItem:
        known = {f for f in cls.__dataclass_fields__}  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in d.items() if k in known})
