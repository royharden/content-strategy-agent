# Content Strategy Agent

Local CSV analytics, metric-grounded content review, immutable approvals and audited
Markdown/CSV exports. The local terminal and Python host API provide an authored
mock review journey; the browser remains a static scaffold.

Implemented behavior includes bounded atomic import, exact metrics/source identity, actual
shared screening/accounting in mock mode, checked previews, separate recommendation/draft
approvals, edits that invalidate approvals, and durable receipts. All current model answers
are authored synthetic data. Live model execution and quality evaluation remain unfinished.
Publishing and scheduling are outside the product scope.

The CLI provides local import, historical reports and an interactive review. From the repository root, using the
existing locked Python 3.12 environment:

```powershell
$env:PYTHONPATH = (Resolve-Path src).Path
New-Item -ItemType Directory -Force .runtime | Out-Null
uv run --offline --no-sync python -c "from pathlib import Path; from content_strategy.runtime.examples import demo_csv; Path('.runtime/synthetic-example.csv').open('xb').write(demo_csv())"
$analysisImport = uv run --offline --no-sync python -m content_strategy import-csv --database .runtime/analysis.sqlite3 --namespace local --file .runtime/synthetic-example.csv | ConvertFrom-Json
uv run --offline --no-sync python -m content_strategy report --database .runtime/analysis.sqlite3 --namespace local --dataset-id $analysisImport.dataset_id --snapshot-id $analysisImport.snapshot_id
uv run --offline --no-sync python -m content_strategy review --database .runtime/review.sqlite3 --call-database .runtime/calls.sqlite3 --namespace local --file .runtime/synthetic-example.csv --output-dir exports
```

The example contains 24 explicitly synthetic posts. File creation refuses to overwrite an
existing example. Import retains history; activation and approval are separate operations.
The terminal displays metrics and checked recommendations. Type `activate`, select a
recommendation number, then explicitly type `approve` at each of the recommendation
and draft stages. Type `export` to download both committed formats into a new folder.
Any decline or EOF stops without export. All generated answers and screening judgments
in this mode are authored synthetic controls, with no live model call or quality claim.

The receipt key, dataset ID and snapshot ID printed during review support recovery after
restart or a failed file copy. Reuse the same database, call-database and namespace:

```powershell
uv run --offline --no-sync python -m content_strategy receipt --database .runtime/review.sqlite3 --call-database .runtime/calls.sqlite3 --namespace local --dataset-id <printed-dataset-id> --snapshot-id <printed-snapshot-id> --key <printed-receipt-key> --output-dir exports
```

Receipt download replays the immutable approved bytes into a fresh folder. It does not
approve changed content. `--status-json` reports local mock capabilities, not acceptance.

`api.LocalReviewService`, `api.application.PlanningHost` and `runtime.proofs.ProofStore`
provide the local workflow. The host supplies database paths, namespace, actor and authorization.
Preview rechecks exact content, evidence, policy, parent and sequence before returning a body.
Raw historical reads are trusted storage operations. Human decisions remain explicit.

The HTTP factory's owned routes now have direct socket-free ASGI normal/refusal controls,
including explicit `/api/revoke`, dependent approval invalidation and historical receipts. Browser,
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
