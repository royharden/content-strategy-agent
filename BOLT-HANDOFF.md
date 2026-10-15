# Bolt handoff — local backend, frontend scaffold

Development is paused. The stack is Python 3.12, Pydantic/FastAPI and local SQLite,
with Node 24, React, TypeScript and Vite scaffolding. Both lockfiles are committed.
Browser output is `dist/`; a complete browser workflow is outstanding.

The host API supports retained metrics, actual shared screening/accounting in authored mock
mode, checked review, separate recommendation/draft approvals, revision invalidation and audited
Markdown/CSV receipts across restart. Live model calls and quality remain unvalidated. The HTTP
factory is written, but its application routes have not run. A separate constant-route ASGI
check does not establish application HTTP acceptance.

SQLite migrations and append-only review/source/proof storage are real local code. The call
ledger uses a separate database. There is no provisioned cloud database, authentication
service, edge function, hosted Python backend or publishing/scheduling integration.

The MVP portability decision preserves the Python core and local approval authority. Full
Bolt-hosted operation needs separately authorized authenticated Python hosting or a separately
validated JavaScript/Deno port. Static frontend inspection does not provision persistence or
model access. Public hosting and multi-user authentication are outstanding decisions.

Setup/build entry points are `uv sync --locked`, `npm ci`, `npm run typecheck` and
`npm run build`. These describe source tooling rather than completed frontend acceptance.
React type dependency setup is unfinished. Local serving needs an explicit loopback origin
and a registered listening resource. No server launcher or listener is currently provided.

Preserve server-controlled actor/namespace/policy and assessment boundaries. Browser bodies
must use checked preview; exact human approvals precede export. Provider secrets belong on
the server. Browser request models accept no actor, judgment or proof fields.

Inspection prompt: inspect the components and scaffold, preserve the documented local/cloud
boundary, and show unfinished browser behavior honestly. Any backend port must preserve input,
grounding, approval, receipt and target conformance. Provisioning, hosting, provider access and
publication require separate readiness and authorization.

See [development status](DEVELOPMENT-STATUS.md), [limitations](docs/LIMITATIONS.md) and
[third-party provenance](THIRD_PARTY.md).
