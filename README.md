# Content Strategy Agent

Local components for importing historical-post CSVs, computing metrics, validating cited
content and preserving exact approvals and Markdown/CSV receipts. Application integration
is in progress. Publishing and scheduling are outside the product scope.

Implemented components include atomic bounded CSV ingestion, deterministic platform metrics,
immutable source/config identity, numeric/passage grounding checks and a SQLite approval/audit/
receipt engine. Pipeline staging uses injected generation, screening and semantic ports;
supplied/keyword/untagged tagging and a conservative LinkedIn UTF-16 target check are present.
X draft support is unavailable until its proposed parser and official conformance pass.

The CLI exposes status/version/help, `import-csv` and exact historical `report` commands.
Imports retain validated source bytes and full reports atomically in an explicitly named local
SQLite database/namespace. Reports remain historical; retention neither activates a source nor
approves content. There is no complete application API/UI workflow,
shipping end-to-end mock/replay pipeline integration. Published S3/S6 components and app rules/
offline-call/native-screen adapters are present; see [provenance and limits](docs/VENDORED.md).
Native screening prepares the exact request before caller admission and preserves mock
provenance for synthetic fixtures. Authored doubles
are not production providers, screen implementations or measured model results. The static
Vite page still identifies the unfinished workflow. Root status creates no runtime file.

```powershell
uv run --offline --no-sync python -m content_strategy --status-json
uv run --offline --no-sync pytest tests/ingest tests/metrics tests/grounded tests/pipeline tests/platforms tests/scaffold
uv run --offline --no-sync python scripts/export_schemas.py --check
uv run --offline --no-sync python conformance/export_runtime_schemas.py --check
```

For local analysis, run `python -m content_strategy import-csv --database <local.sqlite3>
--namespace <user> --file <posts.csv>`. The result supplies dataset and snapshot IDs for
`python -m content_strategy report --database <local.sqlite3> --namespace <user>
--dataset-id <id> --snapshot-id <hash>`. Paths are explicit trusted host inputs. The CLI has
no activation, approval or export command; it does not call providers.

These commands need the existing locked Python 3.12 environment. Fresh setup uses `uv sync --locked`.
Node 24/Vite commands are `npm ci`, `npm test`, `npm run typecheck`, `npm run build`; `dist/` is
the browser output. Dependency setup may require registry access. Local serving needs an actual
resource claim and an allocated loopback `CSA_WEB_PORT`; build/status checks need no listener.

The intended journey is CSV → computed metrics → validated strategy → recommendation approval →
screened draft → exact draft approval → audited Markdown/CSV download. The reusable grounding
module has detached corpus/queue consumer tests and actual local transaction/crash/CAS controls.
Those tests do not establish real downstream application integration or finished-app acceptance.

`content_strategy.api.LocalReviewService` now connects retained source selection to the actual
SQLite approval/export store. A host must supply the database, namespace, actor, authorization
and assessment callbacks. Importing a CSV retains history; activating a snapshot is explicit.
Decisions bind exact immutable item versions and event sequences. Downloads replay authorized
historical receipts. `api.security.SessionGuard` supplies pure loopback Host/Origin/cookie/CSRF
checks. No HTTP factory, listener or default passing assessment is provided by these components;
HTTP integration and browser acceptance remain pending dependency setup and resource allocation.

Metric-only planning requests contain a bounded, declared stratified selection of metric rows,
never raw post rows/text. A screen hold or unavailable required judge stops subsequent model
stages. One content repair is bounded; fewer than five survivors is explicit underfill. Supplied
tags stay unchanged; optional typed tags use an explicit exact confidence threshold and report
unassigned fields. Jev and Luna task ports have no SDK, key lookup or network default.

Independent Gold/held-out fixtures, calibrated comparisons, real provider usage/cost/latency,
API/browser/security acceptance and deployment remain pending. No benchmark or accuracy table
is invented from the focused controls. Actual evaluation must generate its own results against
sealed inputs and the candidate. See [limitations](docs/LIMITATIONS.md),
[input contract](docs/input-contract.md), [grounding contract](conformance/grounding.md),
[boundary inventory](docs/contracts/BOUNDARY-PROPOSALS.md) and [Bolt handoff](BOLT-HANDOFF.md).

The published S2 `shared/evalkit/` module now supplies the canonical comparison,
statistics, resampling and reporting types. Its original synthetic controls and tiny
S9 validator-consumer tests establish component integration; they are separate from
the independent application corpus, its provisional labels and any held-out campaign.
