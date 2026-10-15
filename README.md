# Content Strategy Agent

Local CSV analytics, metric-grounded content review, immutable approvals and audited
Markdown/CSV exports. Development is paused. The Python backend has a working authored
mock journey through its host API; the browser remains a static scaffold.

Implemented behavior includes bounded atomic import, exact metrics/source identity, actual
shared screening/accounting in mock mode, checked previews, separate recommendation/draft
approvals, edits that invalidate approvals, and durable receipts. All current model answers
are authored synthetic data. Live model execution and quality evaluation remain unfinished.
Publishing and scheduling are outside the product scope.

The CLI provides local import and historical reports. From the repository root, using the
existing locked Python 3.12 environment:

```powershell
$env:PYTHONPATH = (Resolve-Path src).Path
New-Item -ItemType Directory -Force .runtime | Out-Null
uv run --offline --no-sync python -c "from pathlib import Path; from content_strategy.runtime.examples import demo_csv; Path('.runtime/synthetic-example.csv').open('xb').write(demo_csv())"
$analysisImport = uv run --offline --no-sync python -m content_strategy import-csv --database .runtime/analysis.sqlite3 --namespace local --file .runtime/synthetic-example.csv | ConvertFrom-Json
uv run --offline --no-sync python -m content_strategy report --database .runtime/analysis.sqlite3 --namespace local --dataset-id $analysisImport.dataset_id --snapshot-id $analysisImport.snapshot_id
```

The example contains 24 explicitly synthetic posts. File creation refuses to overwrite an
existing example. Import retains history; activation and approval are separate operations.
A complete interactive CLI launcher is outstanding. The legacy `--status-json` inventory
contains scaffold-era flags and needs updating before use as a readiness signal.

`api.LocalReviewService`, `api.application.PlanningHost` and `runtime.proofs.ProofStore`
provide the local workflow. The host supplies database paths, namespace, actor and authorization.
Preview rechecks exact content, evidence, policy, parent and sequence before returning a body.
Raw historical reads are trusted storage operations. Human decisions remain explicit.

The HTTP factory and strict request contracts are written; its owned routes have not run.
One separate constant ASGI handler passed a bounded socket-free interface check. Browser,
real HTTP and independent security acceptance remain pending. Standard X weighted limits use
the [licensed parser compatibility edition](conformance/vendor/twitter-text-parser/README.md).
LinkedIn uses the application's conservative 3,000 UTF-16-unit limit.

Fresh setup uses `uv sync --locked` and `npm ci`; the frontend build currently produces the
scaffold. React declaration dependency setup is incomplete. Importing these modules creates
no listener, Docker stack, model client or hosted backend.

See [development status](DEVELOPMENT-STATUS.md), [limitations](docs/LIMITATIONS.md),
[lessons](LESSONS.md), [input contract](docs/input-contract.md),
[grounding contract](conformance/grounding.md), [source provenance](docs/VENDORED.md),
[third-party notices](THIRD_PARTY.md) and [Bolt handoff](BOLT-HANDOFF.md).
