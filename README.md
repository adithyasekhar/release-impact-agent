# release-impact-agent

**Workday Release Impact Agent** — scan your integration inventory, match it against Workday release notes, and get a prioritized, evidence-backed impact report *before* the release window hits your tenant.

Twice a year (R1/R2), every Workday customer plays the same game: read hundreds of What's New items and guess which ones will break which integrations. This agent turns that into a 30-second scan.

```
┌─────────────────┐   ┌──────────────────┐   ┌──────────────────────┐
│ Studio assembly │   │  Release notes    │   │  Impact report        │
│ XML + EIB       │──▶│  (What's New CSV) │──▶│  md + html + Slack    │
│ exports         │   │                   │   │  🔴 critical → ⚪ info │
└─────────────────┘   └──────────────────┘   └──────────────────────┘
   inventory scan        deterministic match      optional Claude
                         (auditable evidence)     severity refinement
```

> **Unofficial** — not affiliated with, endorsed by, or supported by Workday, Inc. Runs entirely on files you already have (Studio workspace, tenant exports). No tenant credentials required.

## What it does

1. **Scans** a Workday Studio workspace (and/or EIB definition exports) and builds a dependency inventory per integration: WWS SOAP services **and pinned versions**, operations called, RaaS reports consumed, Workday REST endpoints, and external endpoints.
2. **Loads** a release-notes export — a What's New report CSV from your tenant, or JSON. Free text is mined for service names, versions, and operations; item types (retirement / deprecation / breaking change / change / new feature) are inferred when not provided.
3. **Matches deterministically.** Every finding carries explicit evidence ("pinned to Human_Resources v34.0, at or below affected v34.0"). No LLM is involved in matching — the report is auditable.
4. **Classifies.** Rule-based severity out of the box. With `ANTHROPIC_API_KEY` set, Claude reviews each finding to refine severity and write a concrete remediation + regression-test step.
5. **Reports.** Markdown report, self-contained HTML dashboard (severity tiles + filterable table), optional Slack digest, and a CI exit code (`--fail-on-critical`) so you can gate deployments.

## Quick start

```bash
pip install release-impact-agent            # or: pip install -e . from a clone

# one shot: scan + analyze + report
release-impact run ~/StudioWorkspace \
  --notes whats-new-2026R2.csv \
  --release-label 2026R2 \
  --outdir reports/
```

Try it immediately with the bundled sample data:

```bash
git clone https://github.com/adithyasekhar/release-impact-agent.git
cd release-impact-agent
pip install -e .
release-impact run tests/fixtures/studio_workspace \
  --notes examples/release-notes-2026R2-sample.csv \
  --release-label 2026R2 --no-claude
open reports/impact-report.html
```

Sample output (from the fixtures above):

```
🔴 Critical: 2   🟠 High: 2   🟡 Medium: 1   🟢 Low: 0   ⚪ Info: 0

🔴 INT001_Worker_Sync   ← Retirement of WWS versions v34.0 and earlier
   evidence: pinned to Human_Resources v34.0, at or below affected v34.0
🔴 EIB_New_Hire_Load    ← Retirement of WWS versions v34.0 and earlier
   evidence: pinned to Staffing v33.0, at or below affected v34.0
🟠 INT002_Comp_Report   ← Deprecation of Submit_Compensation_Change
   evidence: calls operation Submit_Compensation_Change
🟠 INT002_Comp_Report   ← Custom report field rename impacts RaaS
   evidence: consumes RaaS report INT002_Comp_Extract
```

## Step by step (instead of `run`)

```bash
release-impact scan ~/StudioWorkspace -o inventory.json
release-impact analyze --inventory inventory.json --notes whats-new.csv -o findings.json
release-impact report --inventory inventory.json --findings findings.json --outdir reports/
```

## Claude refinement (optional)

```bash
export ANTHROPIC_API_KEY=sk-ant-...
pip install "release-impact-agent[claude]"
release-impact run ~/StudioWorkspace --notes whats-new.csv
```

Claude never creates or removes matches — it only refines severity and writes remediation/test guidance on top of the deterministic findings. Without a key, a rule-based fallback fills in generic remediation so the agent is fully usable offline.

## MCP server mode

Drive the agent conversationally from Claude Desktop or Claude Code:

```bash
pip install "release-impact-agent[mcp]"
claude mcp add release-impact -- release-impact mcp
```

Then: *"Scan my Studio workspace at ~/StudioWorkspace, analyze it against ~/Downloads/whats-new-2026R2.csv, and tell me what to fix first."*

Tools exposed: `scan_inventory`, `analyze_impact`, `generate_report`, `get_artifact_details`.

Pairs well with [Workday-studio-mcp](https://github.com/krishnagutta/Workday-studio-mcp) (fix the flagged assemblies) and [workday-community-mcp](https://github.com/krishnagutta/workday-community-mcp) (pull the release documentation behind each finding).

## Run it on a schedule (GitHub Actions)

`.github/workflows/release-impact.yml` runs the agent weekly during a release-preview window against release notes committed to the repo, publishes the report as a build artifact, and posts a Slack digest. Configure secrets:

| Secret | Purpose |
|---|---|
| `ANTHROPIC_API_KEY` | optional — Claude severity refinement |
| `SLACK_WEBHOOK_URL` | optional — digest to your channel |

## Getting release notes out of your tenant

The agent reads a CSV export. Two easy sources:

* **What's New report** — in your tenant, run *What's New in Workday*, filter to the target release, export to Excel/CSV. Column names are matched loosely; extra columns are ignored.
* **Hand-built sheet** — minimum useful columns: `Title`, `Description`. Add `Type`, `Functional Area`, `Release`, `Setup Required` for better classification. See [`examples/release-notes-2026R2-sample.csv`](examples/release-notes-2026R2-sample.csv).

> The sample release notes bundled here are **synthetic** — realistic in shape, invented in content. Use your tenant's real What's New export for real analysis.

## How matching works (and its limits)

| Signal | Example evidence |
|---|---|
| Service match | "uses WWS service Human_Resources v34.0" |
| Version ceiling | "pinned to Staffing v33.0, at or below affected v34.0" |
| Operation match | "calls operation Submit_Compensation_Change" |
| RaaS report match | "consumes RaaS report INT002_Comp_Extract" |
| REST path match | "calls REST endpoint v1/example_tenant/workers" |

Static analysis can't see everything: endpoints passed as launch parameters, versions resolved at runtime, or logic inside deployed-only integrations. Artifacts with unresolvable dependencies are flagged with notes rather than silently skipped. Treat the report as a prioritized starting list, not a guarantee of completeness.

## Repo structure

```
release_impact/
├── cli.py                  # scan / analyze / report / run / mcp
├── mcp_server.py           # FastMCP server (4 tools)
├── inventory/              # studio_scanner, eib_scanner, models
├── release_notes/          # loader (CSV/JSON), models, text mining
├── analysis/               # matcher (deterministic), classifier (Claude, optional)
├── report/                 # markdown_report, html_report
└── notify/                 # slack digest
tests/                      # pytest suite + realistic fixtures
examples/                   # synthetic 2026R2 release-notes sample
```

## Development

```bash
pip install -e ".[dev]"
pytest
ruff check .
```

## Roadmap

- [ ] Workday REST JSON change detection (schema diffing between API versions)
- [ ] Orchestrate/flows inventory scanner
- [ ] `workday-community-mcp` integration: auto-attach Community doc links to findings
- [ ] Cloud Connect / packaged-integration awareness
- [ ] HTML report: per-artifact drill-down page

## License

MIT — see [LICENSE](LICENSE).
