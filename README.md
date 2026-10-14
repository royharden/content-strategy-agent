# Content Strategy Agent

Planned: import historical-post CSV data, compute metrics in code, review cited recommendations and approve exact drafts before export. No publishing or scheduling.

**Current state: package/configuration scaffold only.** CSV ingestion, analytics, model adapters, review UI, persistent approval and exports are not implemented. The static page identifies this unfinished state; it is not the fixture demo.

## Keyless scaffold check

Python 3.12 and Node 24 are the intended runtimes. The package has no import-time dependency or credential requirement:

```powershell
$env:PYTHONPATH = 'src'
python -m content_strategy --status-json
python -m unittest discover -s tests/scaffold -v
npm test
```

Use a Python 3.12 interpreter for `python` above. From an existing installed runtime, no network, API key, database or listener is needed. These commands test scaffold behavior only. Once lockfiles are produced and checked, `uv sync --locked`, `uv run pytest`, `npm ci`, `npm run typecheck` and `npm run build` validate the configured toolchains. They do not establish application acceptance.

The eventual workflow is CSV → computed metrics → validated strategy → recommendation approval → screened draft → draft approval → audited Markdown/CSV export. The reusable Python `grounded` module is planned for other evidence/approval consumers. See [boundary proposals](docs/contracts/BOUNDARY-PROPOSALS.md).

## Evidence and limits

| Evidence | Current status |
|---|---|
| Scaffold import/status and detached-copy checks | Run separately; no workflow result inferred |
| Deterministic metric/citation/approval evaluation | Not implemented, not measured |
| Tagged/untagged or model comparison | Not measured |
| Provider usage, cost and latency | No calls; not measured |
| Application/browser/security acceptance | Not performed |
| Deployment or public release | Not performed |

No results table or fixture accuracy is invented. Future `scripts/demo.py` and `scripts/eval.py` must work offline and generate their own result tables; scaffold checks are not substitutes. Coding agents prepare the code; later checks and independent review must be reported against actual candidates.

Local serving requires an actual resource claim and `CSA_WEB_PORT`; commands fail without explicit in-band port configuration. The configuration does not allocate a port. Do not put server credentials in frontend variables. [BOLT-HANDOFF.md](BOLT-HANDOFF.md) describes the deployment boundary and unfinished inventory.
