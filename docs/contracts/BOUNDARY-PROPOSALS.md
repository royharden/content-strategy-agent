# Boundary proposals — not implemented or adopted schemas

The local product will separate CSV analytics, evidence validation, model transport and human approvals. This document is a design proposal; it exports no JSON Schema or provider implementation.

| Boundary | Proposed responsibility | Still required |
|---|---|---|
| CSV → metrics | Code computes platform-stratified rates, eligible counts and immutable snapshots | Import/arithmetic implementation, independent oracle tests and fixed gold |
| Metrics → recommendations | Screened brief and computed metrics only; no raw post rows | Exact adopted provider interface, bounded generation and payload tests |
| Citation → evidence | Snapshot/id/value/unit/scope must match; insufficient metrics cannot be cited | S9 grounded schema/validator, numeric grammar and conformance |
| Draft → approval | Exact content, parent recommendation and evidence version bind approval | Durable state machine, audit migration and race/restart tests |
| Approval → export | One SQLite transaction stores approved Markdown+CSV bytes, receipt and events | Export implementation and crash/idempotency/unauthorized tests |
| Shared modules | S3 owns providers/callledger; S6 screen; S2 evalkit and optional rulings | Actual owner adoption, verified commits/licences and moved-copy tests |

No shared schema, audit DDL, adapter, ledger or exporter is implemented in this scaffold. Provider contract proposals are not vendored source. `config/metric-policy.proposal.json` is proposed configuration, unused at runtime. Product state must never be authorized by a model result, cached response or UI button alone.
