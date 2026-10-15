# Development status — local authored-mock journey, 2026-10-15

Prior host-only implementation baseline: `a4990d4ef57fca4e8fa57e915e8a72ac13e85927`.
No finished-app or model-quality verdict has been made.

## Finished components

- Atomic bounded CSV ingestion, exact analytics, immutable identities and retained reports,
  with explicit CLI import/report commands.
- Exact grounding and SQLite activation, review, approval, revision and export gates.
- Actual shared offline accounting/provider and native screening integration. Concrete
  requests, screen nonces and captures exist before a single zero-dispatch admission.
- Host-API journey: source → plan → explicit recommendation approval → draft → explicit
  draft approval → audited Markdown/CSV export → restart and historical receipt replay.
- Human edits receive fresh screening/support, create a new revision and need a new approval.
  Recommendation edits invalidate dependent draft approval. Human input has no generation capture.
- The `review` terminal command reaches CSV/metrics, checked recommendations, separate human
  recommendation/draft decisions and approved-only download. `receipt` recovers committed bytes.
- Explicit approval revocation invalidates the current item and dependent approved drafts;
  old committed receipts remain available as historical artifacts. Invalid CSV is checked
  before database creation.
- Durable exact proof bindings; missing/corrupt/stale proofs, changed source/policy,
  unauthorized actions and parent races refuse disclosure or export.
- Standard X weighted checks enabled after their required mapped conformance profile passed.

The API-host/runtime/pipeline/adapter development subset passed 159 distinct cases at the edit
checkpoint. Browser wire/views passed 26 pure cases. The parser gate passed 1,706 official
cases, eight boundaries and one integrity control; the post-enable target/pipeline/runtime
subset passed 1,797 cases. These scopes overlap and must not be added as independent coverage
or interpreted as application-quality measurements.

## Worked on and incomplete

- A same-origin FastAPI factory, bounded JSON/base64 inputs, strict host-controlled fields,
  no-store/session/CSRF boundaries, checked previews and export responses are written.
  Direct socket-free ASGI controls now exercise its actual normal/refusal routes, including
  session/CSRF/Origin/Host, untrusted fields, approval/revocation and restart receipts.
- One separate constant async ASGI handler passed a socket-free single-step diagnostic.
  The application's own route journey has not started.
- React/Vite/TypeScript scaffolding exists; the page still identifies an unfinished workflow.
  React declaration dependency installation is incomplete. The retained first archive's
  corrected entry-count, integrity, identity and MIT-notice audit passed without refetching;
  the remaining archives are unacquired.
- Generic comparison/statistics code and provisional development fixtures are present.
  No full application evaluation or calibrated comparison has run.

## Outstanding

1. Complete the browser workflow around the working local terminal/host journey.
2. Exercise real loopback/browser and security behavior with registered
   resources.
3. Complete frontend dependencies, UI implementation, type checks and visual verification.
4. Complete metric-evidence pointer integration and application evaluation/reporting.
5. Validate bounded real generation/tagging/judgment integrations and honest usage/cost records.
6. Verify packaging and portability; resolve hosting/authentication before cloud provisioning.
7. Freeze a complete candidate and obtain independent finished-application review.

The CLI inventory now distinguishes authored local workflow availability from model quality.
See [README](README.md), [LESSONS](LESSONS.md) and [Bolt handoff](BOLT-HANDOFF.md).
