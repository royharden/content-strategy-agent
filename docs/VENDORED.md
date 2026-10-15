# Published component provenance

The [machine-readable map](../conformance/vendor/manifest.json) pins original repository
paths, exact Git blobs and SHA-256 hashes. Production modules retain their original bytes;
only the containing package path changes. Both source notices are MIT, copyright 2026 Roy
Harden, preserved in `conformance/vendor/s3/upstream/LICENSE` and
`conformance/vendor/s6/upstream/LICENSE`.

| Component | Source repository | Exact commit | Local package |
| --- | --- | --- | --- |
| S3 ledger and offline provider | llm-router-eval | c7a03a8a5aa91a3881782621d8a5f09c6b82520d | content_strategy.shared.callledger and providers |
| S6 screen | github-issue-triage | 419eaf97f605637a9aece2f43c25b04ccb3dabdf | content_strategy.shared.screen |

S3's fourteen-file closure and S6's six-file closure are copied together. Granted contracts,
schemas, synthetic fixtures, tests and three S3 supplemental utilities/assets are retained
under `conformance/vendor/<component>/upstream`. The separate `adapted` directories change
test imports and file locations to exercise this repository. Original tests are preserved;
the manifest records both byte views. Test adaptations use explicit UTF-8.

Run moved tests with `python -m pytest --import-mode=importlib
conformance/vendor/s3/adapted/tests conformance/vendor/s6/adapted/tests`. They are synthetic
contract controls, separate from independent quality evaluation. Package defaults still
run the app's own `tests/` suite. The app gateway's tests use the published synthetic helper
with real SQLite ledger admission, hit/miss and invalid-binding checks.

The app rules adapter projects actual S6 full-input results without converting them into
typed results or human approval. The offline provider gateway accepts actual owner binding
objects, requires an explicit zero outbound limit, and invokes S3's allocation validation
and `run`. S3 rechecks after lookup atomically. The gateway creates no allocation, evidence,
capture, transport or fallback. A synthetic fixture hit remains mock. A strict replay miss
may carry the backend origin `replay`, with no usable output or source observation.

Typed screening integration is pending a published preparation/execution API that permits
exact request evidence before admission. The retained S6 version explicitly holds captured
typed requests as unavailable. Live SDK access, calibrated thresholds, real token/billing
proof, deployment and finished-app acceptance are unestablished.
