# Structural boundary contracts and remaining proposals

The local product separates app analytics from portable grounding policy and future model transport. WP02 implements bounded ingestion/analytics. WP03 adds exact metric/passage validation, bounded rendering and SQLite approval/audit/export functions under `shared/grounded/`, using trusted injected authorization and screen/semantic assessments. The unchanged 13 structural models remain in `schemas/grounded-v1.json`; seven runtime additions and executed vectors live in `conformance/`. No finished application workflow or provider implementation is present.

| Boundary | Proposed responsibility | Still required |
|---|---|---|
| CSV → metrics | Code computes platform-stratified rates, eligible counts and immutable snapshots | Local import/arithmetic and hand-computed oracle tests implemented; independent fixed gold/evaluation still required |
| Metrics → recommendations | Screened brief and computed metrics only; no raw post rows | Exact adopted provider interface, bounded generation and payload tests |
| Citation → evidence | Exact current metric/passage checks, finite claim grammar and vectors implemented | Application integration and genuine screen/semantic provider acceptance |
| Draft → approval | Exact content, parent recommendation and evidence version bind approval | Local state/migration/CAS/race/restart checks implemented; application authorization and end-user journey still required |
| Approval → export | One SQLite transaction stores approved Markdown+CSV bytes, receipt and events | Local two-format receipts and crash/idempotency/authorization checks implemented; application download flow still required |
| Shared modules | S3 owns providers/callledger; S6 screen; S2 evalkit and optional rulings | Actual owner adoption, verified commits/licences and moved-copy tests |

## Identity edition

Dataset identity `dataset-identity.v1` hashes named source rows sorted by their explicitly supplied ID field, using NFC strings, sorted object keys and canonical UTF-8 JSON. Duplicate IDs/keys after normalization fail. Float/datetime/SDK values are rejected; bounded exact Decimals serialize as plain strings with no exponent, rounding or negative zero. IDs retain case. Semantic category slugs use NFKC/casefold and ASCII runs; all colliding NFC keys get six-hex suffixes, and any remaining collision fails explicitly.

`SnapshotIdentity` hashes its exact versioned structural document: dataset fingerprint, sorted source/field tag provenance, immutable canonical `config_json` text and computation version. Config is a JSON object encoded as a canonical string; decimal config literals must be strings, not JSON floats. Creation timestamps belong to `MetricSnapshot` metadata and never enter this identity. Fields are immutable tuples/records/strings. No mutable configuration dictionary is retained. Changed source/config/tags/computation changes identity; equivalent row/key/Unicode order does not.

`EvidenceResolver[T]` is a protocol over generation/evidence-ID/scope and has no concrete IO implementation or social-platform enum. A corpus-passage or approval-queue consumer may provide its own evidence type. The added runtime validator enforces exact numeric or passage evidence and policy checks through a trusted current-access resolver. The app metric adapter is isolated outside the portable export. Approval/export record construction and schema checks cannot prove human identity, approved state, actual artifact hashes or permission. Call public validation on untrusted input; Pydantic's deliberately unvalidated `model_construct`/`model_copy(update=...)` are trusted-code escape hatches, not validation boundaries.

Module-owned SQLite audit/receipt DDL and exporter are implemented; provider/call ledgers and application storage remain absent. See [grounding.md](../../conformance/grounding.md) for host-trust, historical-receipt and finite-grammar limits. Foreign provider contract proposals are not vendored source. `config/metric-policy.proposal.json` is proposed analytic configuration, unused at runtime. Product state must never be authorized by a model result, cached response or UI button alone.
