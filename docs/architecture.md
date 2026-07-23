# Architecture

## Design principles

1. **Deterministic core, LLM garnish.** Matching between release items and
   artifacts is pure rules with explicit evidence strings. Claude (optional)
   only refines severity and writes remediation text — it can never invent or
   remove a match. This keeps the report auditable, reproducible, and usable
   offline.
2. **Files in, files out.** The agent needs no tenant credentials. Inputs are
   things practitioners already have on disk: a Studio workspace, EIB exports,
   a What's New CSV. Outputs are JSON (machine), Markdown (humans in git),
   HTML (humans in a browser), Slack (humans in a hurry).
3. **Tolerant parsing.** Studio and EIB XML in the wild is messy and version-
   dependent. Scanners combine loose regex passes with structural markers,
   and record `notes` on artifacts whenever something couldn't be resolved
   statically instead of silently dropping it.

## Pipeline

```
            ┌────────────────────────────────────────────┐
            │ inventory/                                 │
 workspace ─┤  studio_scanner  ──┐                       │
            │  eib_scanner     ──┴─▶ Inventory (JSON)    │
            └────────────────────────────┬───────────────┘
                                         │
 whats-new.csv ─▶ release_notes/loader ──┤   (text mining: services,
                                         │    versions, ops, reports)
                                         ▼
            ┌────────────────────────────────────────────┐
            │ analysis/matcher — deterministic joins:    │
            │  service · version-ceiling · operation ·   │
            │  RaaS report · REST path                   │
            │        └─▶ Finding(evidence[], severity)   │
            │ analysis/classifier — optional Claude pass │
            └────────────────────────────┬───────────────┘
                                         ▼
              report/markdown · report/html · notify/slack
```

## Severity model

| item_type | base severity |
|---|---|
| retirement | critical |
| deprecation / breaking_change | high |
| change | medium |
| new_feature | low |
| info | info |

`setup_required` bumps low/info to medium. The Claude pass may adjust one
step in either direction when evidence warrants (e.g. a "change" item that
renames a field an artifact demonstrably maps).

## Entry points

* **CLI** (`release_impact/cli.py`) — `scan`, `analyze`, `report`, `run`, `mcp`.
* **MCP server** (`release_impact/mcp_server.py`) — FastMCP, stdio transport,
  4 tools with an in-process state dict (scan → analyze → report).
* **GitHub Actions** — `release-impact.yml` cron + `--fail-on-critical` exit
  code for CI gating.

## Extending

* New artifact source → add a scanner in `inventory/` returning `Artifact`s;
  merge it in `cli._scan` and `mcp_server.scan_inventory`.
* New release-notes source → add a loader returning `ReleaseItem`s.
* New match signal → add a block to `matcher.match_item_to_artifact` that
  appends an evidence string; everything downstream picks it up for free.
