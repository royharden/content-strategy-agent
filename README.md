# Content Strategy Agent

Local CSV analytics, metric-grounded content review, immutable approvals and audited
Markdown/CSV exports. The local browser, terminal and Python host API provide an authored
mock review journey with explicit decisions and durable receipts.

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

The HTTP factory has direct ASGI and actual registered-loopback/browser normal/refusal checks,
including explicit `/api/revoke`, dependent approval invalidation and historical receipts. The
browser shows exact committed Markdown/CSV, supports direct receipt attachments and restores
receipt lookup after restart. Native automated file saves were canceled in the local test
environment and remain unverified; browser HTTP bytes and read-only artifact views were checked
against SQLite. Independent review of the browser candidate remains pending. Standard X weighted limits use
the [licensed parser compatibility edition](conformance/vendor/twitter-text-parser/README.md).
LinkedIn uses the application's conservative 3,000 UTF-16-unit limit.

Fresh setup uses `uv sync --locked`, `npm ci --ignore-scripts`, `npm run typecheck` and
`npm run build`, with Python 3.12 and Node 24. The three React declaration dependencies are
pinned, installed and byte-checked against audited registry archives; full MIT notices are
retained in [frontend dependency provenance](conformance/vendor/frontend-types/manifest.json).
A fresh portable installation remains a separate check. Importing modules starts no listener.

After obtaining a local listening port, serve the built browser and API on the same origin:

```powershell
uv run --offline --no-sync python -m content_strategy serve --database .runtime/review.sqlite3 --call-database .runtime/calls.sqlite3 --namespace local --assets dist --port <assigned-local-port>
```

Agents claim/check that port before starting. The launcher binds loopback only, uses one
ephemeral session/CSRF boundary and prints its URL. Import a CSV or try the explicitly
synthetic example; use the snapshot, create a demo strategy, inspect/approve a recommendation,
draft, then inspect/approve that draft separately. Export commits both formats together.
Edits and revocation require fresh decisions. A static-only host displays a setup state and
cannot approve/export; it does not provision Python or SQLite.

See [development status](DEVELOPMENT-STATUS.md), [limitations](docs/LIMITATIONS.md),
[lessons](LESSONS.md), [input contract](docs/input-contract.md),
[grounding contract](conformance/grounding.md), [source provenance](docs/VENDORED.md),
[third-party notices](THIRD_PARTY.md) and [Bolt handoff](BOLT-HANDOFF.md).
