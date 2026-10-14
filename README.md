# Content Strategy Agent

Planned: import historical-post CSV data, compute metrics in code, review cited recommendations and approve exact drafts before export. No publishing or scheduling.

**Current state: structural contracts only.** Reusable `grounded` models, canonical identity and generated structural schemas are implemented. CSV ingestion, analytics, citation resolution/validation, model adapters, review UI, persistent approval and exports are not implemented. The static page identifies the unfinished workflow; it is not the fixture demo. Constructing an approval/receipt record does not authenticate a human or authorize an export.

## Keyless scaffold check

Python 3.12 and Node 24 are the runtimes. The root status command needs no credentials or third-party imports; the structural models require the locked Pydantic dependency:

```powershell
$env:PYTHONPATH = 'src'
python -m content_strategy --status-json
python -m unittest discover -s tests/scaffold -v
npm test
```

Use a Python 3.12 interpreter for `python` above. Those scaffold commands need no network, API key, database or listener. Both lockfiles are committed. `uv sync --locked`, `uv run pytest`, `uv run python scripts/export_schemas.py --check`, `npm ci`, `npm run typecheck` and `npm run build` validate the configured toolchains. Installation can require registry access on a fresh machine. Structural checks do not establish application acceptance.

The eventual workflow is CSV → computed metrics → validated strategy → recommendation approval → screened draft → draft approval → audited Markdown/CSV export. The reusable Python `grounded` structural models and generic resolver protocol have detached synthetic M3/M8-style consumer tests; no actual downstream app integration is claimed. See [boundary contracts and remaining proposals](docs/contracts/BOUNDARY-PROPOSALS.md).

## Evidence and limits

| Evidence | Current status |
|---|---|
| Scaffold import/status and detached-copy checks | Run separately; no workflow result inferred |
| Structural model/identity/generated-schema checks | Local tests; no grounding or approval authorization inferred |
| npm lock/install/typecheck/static build | Local scaffold checks; no application UI inferred |
| Deterministic metric/citation/approval evaluation | Not implemented, not measured |
| Tagged/untagged or model comparison | Not measured |
| Provider usage, cost and latency | No calls; not measured |
| Application/browser/security acceptance | Not performed |
| Deployment or public release | Not performed |

No results table or fixture accuracy is invented. Future `scripts/demo.py` and `scripts/eval.py` must work offline and generate their own result tables; scaffold checks are not substitutes. Coding agents prepare the code; later checks and independent review must be reported against actual candidates.

Local serving requires an actual resource claim and `CSA_WEB_PORT`; commands fail without explicit in-band port configuration. The configuration does not allocate a port. Do not put server credentials in frontend variables. [BOLT-HANDOFF.md](BOLT-HANDOFF.md) describes the deployment boundary and unfinished inventory.
