# Bolt handoff — local components, inspection only

The Python core has local ingestion/analytics, exact grounding and SQLite approval/audit/receipt
functions. App pipeline/tagging ports are staged. Published S3/S6 components, a real rules-screen
adapter and a zero-dispatch provider gateway are present; typed workflow integration is pending.
The root CLI supports explicit local CSV import and historical report retrieval as well as
inventory. Local retention creates no active-context or approval authority. The Vite browser
output is an unfinished static page;
React workflow, application API integration and browser acceptance remain pending.

The module-owned SQLite migration is real local code, not a provisioned cloud database. Its
transaction tests cover exact two-format bytes, approvals, restart, CAS and crash timing.
No account, hosted backend, remote repository, Bolt import or publication is established.

Python is not a Bolt JavaScript backend. Bolt can inspect/build browser assets; a full workflow
needs separately authorized authenticated Python hosting or an approved port that passes the
same conformance. See [supported technologies](https://support.bolt.new/reference/supported-technologies).
Import alone does not provision Python, SQLite, providers or approval persistence.

Both lockfiles are committed. Setup/build commands: `uv sync --locked`; `uv run pytest`;
`uv run python scripts/export_schemas.py --check`;
`uv run python conformance/export_runtime_schemas.py --check`; `npm ci`; `npm run typecheck`;
`npm run build`. Browser output is `dist/`. Local serving requires an actual resource claim and
allocated loopback `CSA_WEB_PORT`. No serving resource is created by these source files.

Server-only secret names are reserved; there are no provider calls or secret values in this
artifact. See [source provenance](docs/VENDORED.md). Typed S3/S6 workflow integration,
X parser/official target checks, independent
fixtures/evaluation, the application journey and independent finished-app review remain pending.

Inspection prompt: inspect the local components and explicit gaps, verify locked build/schema
commands, and show the unfinished static page honestly. Keep Python approval/storage authority
on the server. Do not create a cloud database, deploy functions, add secrets or publish from
this handoff; provisioning and hosting require their own concrete authorization/readiness.

Canonical S2 evaluation components are vendored with exact source/license/test provenance.
They provide generic statistics/comparison boundaries; no application corpus or model
quality result follows from their synthetic conformance controls.

The local review service joins retained metric snapshots to the actual SQLite approval/export
store with required host callbacks and explicit activation/version/sequence checks. Pure
loopback session checks are available. Neither component starts a listener or supplies a
passing model assessment. Framework integration and browser acceptance remain pending;
keep these host-controlled authority boundaries when adapting the interface.
