# Bolt handoff — local authored-mock browser and terminal

The stack is Python 3.12, Pydantic/FastAPI and local SQLite,
with Node 24, React, TypeScript and Vite. Both lockfiles are committed.
Browser output is `dist/`; the local browser workflow is implemented and exercised on loopback.

The host API supports retained metrics, actual shared screening/accounting in authored mock
mode, checked review, separate recommendation/draft approvals, revision invalidation and audited
Markdown/CSV receipts across restart. Live model calls and quality remain unvalidated. The HTTP
factory's actual normal/refusal routes have direct socket-free ASGI coverage. The terminal
`review` command provides explicit separate decisions and approved-only local downloads;
`receipt` recovers committed bytes after restart. Registered real HTTP/browser checks cover
normal/refusal/restart behavior; independent browser-candidate review remains pending. Direct
same-origin receipt attachments and read-only artifact views use stored approved bytes. Automated
OS file saves were canceled in the test environment and remain unverified.

SQLite migrations and append-only review/source/proof storage are real local code. The call
ledger uses a separate database. There is no provisioned cloud database, authentication
service, edge function, hosted Python backend or publishing/scheduling integration.

The MVP portability decision preserves the Python core and local approval authority. Full
Bolt-hosted operation needs separately authorized authenticated Python hosting or a separately
validated JavaScript/Deno port. Static frontend inspection does not provision persistence or
model access. Public hosting and multi-user authentication are outstanding decisions.

Setup/build entry points are `uv sync --locked`, `npm ci`, `npm run typecheck` and
`npm run build`. These describe source tooling rather than completed frontend acceptance.
React type dependencies are installed and match the audited archives, including full MIT notices;
the retained first archive was reused. Local serving uses `python -m content_strategy serve`
with explicit database/call-database, namespace, built-assets and assigned port arguments. The
launcher binds loopback only. Agents register/check the actual listening resource first and
close owned resources after verification. Importing the module starts nothing.

Preserve server-controlled actor/namespace/policy and assessment boundaries. Browser bodies
must use checked preview; exact human approvals precede export. Provider secrets belong on
the server. Browser request models accept no actor, judgment or proof fields.

Inspection prompt: inspect the implemented local browser and terminal, preserve the documented local/cloud
boundary, and show the static-host setup state honestly. Backend-free static fixture data is
not yet supplied. Any backend port must preserve input,
grounding, approval, receipt and target conformance. Provisioning, hosting, provider access and
publication require separate readiness and authorization.

Database target for this edition: local SQLite only; no cloud database is required for the
terminal workflow. No remote migrations, functions, buckets or provider secrets are needed
for authored mock execution. Approval revocation appends invalidation events through the
existing migration edition; it never rewrites historical receipt bytes.

See [development status](DEVELOPMENT-STATUS.md), [limitations](docs/LIMITATIONS.md) and
[third-party provenance](THIRD_PARTY.md).
