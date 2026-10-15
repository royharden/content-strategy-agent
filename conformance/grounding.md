# Grounded runtime v1

This portable package uses only Pydantic and the Python standard library. Import runtime
policy/validation records from `grounded.validation`, and `AuditStore`, `ExportRequest`,
`Bundle` and `GateError` from `grounded.audit` after copying the complete package, including
`migrations/001.sql`. No owner-app, platform, test, provider or workspace imports are required.
WP01's 13 structural records and identity semantics remain unchanged. The owner-specific
snapshot resolver lives outside the export at `content_strategy.metrics.grounding`.

The trusted host injects current-access evidence resolution, authorization and assessment.
A numeric citation requires the exact current generation/key/scope/value/unit and `ok`
status with the policy's minimum sample (default five). Exact corpus excerpts instead use
PassageCitation/PassageEvidence; quotes, keys, access and status must match exactly.
Semantic supports/contradicts/says-nothing/unknown and screen pass/hold/not-run assessments
bind content, complete resolved evidence, policy hash and screen edition. This module does
not authenticate humans, run a model, implement S6 screening or establish semantic truth.
Actor labels record attribution. Host authorization is required for save/decision/export
and receipt reads. An untrusted API must never control the injected host callbacks.

Text uses `{{cite:evidence-id}}` placeholders; code renders verified exact values/quotes.
Free historical numbers reject. The named grammar detects Unicode numeric characters
before and after NFKC, digits/decimals/exponents/ranges/multipliers containing digits,
percent/per-mille signs, and these case-folded whole words: zero through nineteen,
twenty/thirty/forty/fifty/sixty/seventy/eighty/ninety, hundred/thousand/million/billion/
trillion, dozen/half/quarter/double/triple/twice/thrice/twofold/threefold/tenfold,
percent/percentage/multiplier. This finite grammar is not universal natural-language
verification. Semantic review handles unsupported phrasings. Explicit editorial literals
use whole-line `{{edit:name}}` tokens and fixed labels for count/cadence/horizon, bounded
to 1–90 integer units. They cannot be inserted into a free performance sentence.

Seal exact Content before saving. New edits increment revisions; content hashes bind the
whole item, citations, editorial choices and passage quotes. Activate the current evidence
generation/policy through the trusted host. All writes use BEGIN IMMEDIATE and sequence
CAS. Recommendation approval is required before saving a dependent draft; exact draft
approval and current parent approval are required before export. Edits invalidate old
approvals and dependent drafts; evidence/policy/screen-edition changes append context and
invalidation events. Old revisions cannot become current through receipt replay.

`read_content(id, revision, actor_label=...)` is an authorized exact historical read,
with no approval claim. `require_approved(...)` additionally checks the current version,
generation, policy, screen and semantic assessment inside BEGIN IMMEDIATE. Its immutable
Content return is not a lasting approval token. Callers recheck after generation; saving
a dependent draft and exporting still perform their own current-parent checks.

SQLite is authoritative. Module-owned migration 001 creates namespaced immutable versions,
events and receipts. Hash/actual DDL checks detect edition/schema changes. INSERT replacement,
UPDATE and DELETE guards prevent rewriting rows. The database file, host callbacks and code
are trusted; a database administrator able to replace files or disable code is outside this
boundary. These controls do not create cryptographic human attestation.
Namespaces contain 1–64 ASCII letters/digits/underscore/hyphen. A policy limits a bundle
to 100 items by default (configurable up to 1,000); rendered body expansion stops at 2 MiB,
and incremental two-format rendering refuses before accumulating an oversized bundle.

Export binds the full request, actor, exact item versions, generation, policy, sequence and
idempotency key. Within one transaction it rechecks authority, renders formula-safe CSV and
HTML/Markdown-escaped Markdown, rejects combined bytes above 2 MiB, stores exact bytes,
hashes and approval references, and appends export events. Bytes return only after COMMIT.
Same key/request replays identical historical bytes; changed requests conflict. Replay checks
stored hashes and approval/version references and remains a historical read, never current
approval. There is no arbitrary file-path download API. Failed/pre-commit crashes expose
no receipt; post-commit crashes replay both committed formats.
The full original request is stored with the immutable receipt. `read_receipt(key, actor_label=...)`
supports authorized historical download after restart without requiring the client to retain
the original CAS sequence. Keys are SQL parameters, never filesystem paths.

The JSON vectors describe validator/state/export cases executed by focused tests. Separate
tests exercise actual process exits, two SQLite connections, tamper, stale approvals and
detached renamed M3 corpus/M8 queue consumers with valid and invalid controls. These are
portable consumer proofs, not integration acceptance by the real M3/M8 applications.
# Additive current review and historical metadata APIs

`AuditStore.require_context` authorizes `read_context` with no content argument, checks
current generation/policy and optional exact event sequence in the existing transaction,
and returns an observation, never a lease. `history` first authorizes the empty inventory
and then every exact version with `read_history`; it returns metadata only, with no partial
list on denial and no raw or rendered body. Callbacks must explicitly support `None` for
these context/inventory checks. Item labels and historical state are not capabilities.

`review` authorizes the exact item and reuses `_checked` for latest/current source,
structural grounding and exact screen/semantic binding, plus current parent approval for
a draft. It returns checked disclosure only after those gates; it appends no event and
cannot approve or export. The service checks sequence/context again before disclosure.
An authorized historical `read_content` remains a trusted storage operation and must not
be exposed as an unscreened browser-body route. Original DTO schemas and migration bytes
remain unchanged by these additive APIs.

`revoke(id, revision, actor_label=..., expected_sequence=...)` requires current context,
the latest exact version, the `revoke` host permission and an approved/exported state.
One transaction appends `invalidate` with reason `approval_revoked` and invalidates current
approved/exported drafts bound to that recommendation revision. New exports then refuse;
reauthorization requires fresh explicit decisions. Existing committed receipts remain
authorized historical downloads. Rejection remains a separate draft-state decision.
Revocation adds no migration or structural DTO change.
