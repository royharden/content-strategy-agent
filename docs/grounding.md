# Grounded drafting and explicit approval

Code computes immutable evidence rows. A citation resolves an exact generation, metric ID,
scope, canonical value and unit; only adequately sampled `ok` rows are citable. Text uses
typed citation placeholders so the renderer inserts verified values. Structural validity
does not establish semantic support or human approval.

The portable `content_strategy/shared/grounded/` package contains models, validation,
identity functions and the SQLite review authority. Copy the whole directory, including
`migrations/`, into a consumer and inject its evidence resolver, authorization and exact
screen/semantic assessment callbacks. No owner-app or workspace imports are required.
The [runtime contract](../conformance/grounding.md) documents interfaces and bounded vectors.

Save immutable content with revision and sequence checks. Approve the recommendation
before drafting, then approve the exact draft before exporting. Edits, evidence/policy
changes and explicit approval revocation invalidate affected approvals. Revoking a
recommendation also invalidates its dependent approved drafts. Callers cannot turn an
earlier preview into a lasting capability; persistence and export recheck current state.

SQLite commits both rendered Markdown/CSV payloads, digests, approval references and events
before returning export bytes. Idempotency binds the exact request. Historical receipt
replay recovers already committed bytes across restart, including after revocation, and
never approves changed content. Module migrations protect append-only history.

The local terminal and direct ASGI tests exercise this workflow with authored synthetic
generation/screen/support answers. They establish development behavior, not live-model
quality or verified human identity. Actor labels are attribution; the local host and
database remain trusted. Publishing and scheduling are outside the application.
