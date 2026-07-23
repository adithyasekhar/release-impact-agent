"""Load Workday release notes from CSV or JSON exports.

Workday publishes release content through the What's New report in the
tenant and through Community release notes. Neither has a public API, so
the agent takes an export:

* CSV — a What's New report export (or a hand-built sheet). Column names
  are matched case-insensitively and loosely ("Functional Area" ==
  "functional_area").
* JSON — a list of ReleaseItem dicts (the agent's native format, also
  what you get from ``release-impact notes --normalize``).

Free-text fields are mined for service names, versions, and operations so
that even a bare title/description export still matches inventory.
"""

from __future__ import annotations

import csv
import json
import re
from pathlib import Path

from .models import ITEM_TYPES, ReleaseItem

# Known WWS service names appear in release text as e.g. "Human_Resources"
# or "Human Resources Web Service".
_SERVICE_IN_TEXT = re.compile(
    r"\b([A-Z][A-Za-z]+(?:_[A-Z][A-Za-z]+)+)\s*(?:Web Service|web service|WWS)?\b"
)
_VERSION_IN_TEXT = re.compile(r"\bv(\d+\.\d+)\b")
_OPERATION_IN_TEXT = re.compile(
    r"\b((?:Get|Put|Submit|Import|Cancel|Rescind|Approve|Deny|Add|Update|Maintain|"
    r"Assign|Change|End|Manage|Remove|Reassign|Terminate|Correct)_[A-Z][A-Za-z0-9_]+)\b"
)

# WWS services whose names are a single word, invisible to the underscore
# regex above. Curated from the public WWS directory.
_SINGLE_WORD_SERVICES = (
    "Staffing", "Recruiting", "Payroll", "Compensation", "Benefits", "Absence",
    "Learning", "Talent", "Integrations", "Notification", "Settlement",
    "Cash_Management", "Identity", "Provisioning",
)
_SINGLE_WORD_RE = re.compile(r"\b(" + "|".join(_SINGLE_WORD_SERVICES) + r")\b")

# "... report INT002_Comp_Extract ..." / "custom report Comp_Extract"
_REPORT_IN_TEXT = re.compile(r"\breport\s+([A-Z][A-Za-z0-9_]{3,})")

_TYPE_KEYWORDS = [
    ("retirement", ("retire", "retirement", "removed", "no longer available", "end of life")),
    ("deprecation", ("deprecat", "will be removed", "planned removal", "sunset")),
    ("breaking_change", ("breaking", "must update", "action required", "required by")),
    ("change", ("changed", "change to", "now returns", "updated behavior", "renamed")),
    ("new_feature", ("new ", "introduces", "now available", "added")),
]

_COLUMN_ALIASES = {
    "id": ("id", "item id", "whats new id", "reference id", "item"),
    "title": ("title", "name", "item title", "feature"),
    "description": ("description", "details", "summary", "whats new description"),
    "item_type": ("type", "item type", "category type", "change type"),
    "functional_area": ("functional area", "area", "product area", "category"),
    "release": ("release", "release name", "delivered in"),
    "setup_required": ("setup required", "requires setup", "automatically available"),
    "url": ("url", "link", "community link"),
}


def _norm_header(h: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", h.strip().lower())


def _map_columns(headers: list[str]) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for field_name, aliases in _COLUMN_ALIASES.items():
        for h in headers:
            if _norm_header(h) in aliases:
                mapping[field_name] = h
                break
    return mapping


def infer_item_type(text: str) -> str:
    low = text.lower()
    for item_type, keywords in _TYPE_KEYWORDS:
        if any(k in low for k in keywords):
            return item_type
    return "info"


def enrich_from_text(item: ReleaseItem) -> ReleaseItem:
    """Mine title+description for services/versions/operations."""
    text = f"{item.title}\n{item.description}"
    if not item.affected_services:
        multi = {s for s in _SERVICE_IN_TEXT.findall(text) if not _OPERATION_IN_TEXT.match(s)}
        single = set(_SINGLE_WORD_RE.findall(text))
        item.affected_services = sorted(multi | single)
    if not item.affected_versions:
        item.affected_versions = sorted({f"v{v}" for v in _VERSION_IN_TEXT.findall(text)})
    if not item.affected_operations:
        item.affected_operations = sorted(set(_OPERATION_IN_TEXT.findall(text)))
    if not item.affected_reports:
        item.affected_reports = sorted(set(_REPORT_IN_TEXT.findall(text)))
    if item.item_type not in ITEM_TYPES or item.item_type == "info":
        inferred = infer_item_type(text)
        if inferred != "info":
            item.item_type = inferred
    return item


def load_csv(path: Path) -> list[ReleaseItem]:
    with path.open(newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        headers = reader.fieldnames or []
        colmap = _map_columns(list(headers))
        items: list[ReleaseItem] = []
        for i, row in enumerate(reader, start=1):
            def get(field_name: str, default: str = "", row: dict = row) -> str:
                col = colmap.get(field_name)
                return (row.get(col) or default).strip() if col else default

            raw_type = get("item_type").lower().replace(" ", "_")
            item = ReleaseItem(
                id=get("id") or f"item-{i}",
                title=get("title"),
                description=get("description"),
                item_type=raw_type if raw_type in ITEM_TYPES else "info",
                functional_area=get("functional_area"),
                release=get("release"),
                setup_required=get("setup_required").lower() in ("yes", "true", "y", "1"),
                url=get("url"),
            )
            items.append(enrich_from_text(item))
    return items


def load_json(path: Path) -> list[ReleaseItem]:
    data = json.loads(path.read_text())
    if isinstance(data, dict):
        data = data.get("items", [])
    return [enrich_from_text(ReleaseItem.from_dict(d)) for d in data]


def load_release_notes(path: Path) -> list[ReleaseItem]:
    if path.suffix.lower() == ".csv":
        return load_csv(path)
    if path.suffix.lower() == ".json":
        return load_json(path)
    raise ValueError(f"Unsupported release notes format: {path.suffix} (use .csv or .json)")
