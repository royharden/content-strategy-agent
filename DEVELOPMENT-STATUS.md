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
- React browser workflow, strict request client, same-origin local launcher, exact metric/status
  table, checked recommendation/draft review, human edits, revocation, receipt recovery and
  read-only approved artifact views are implemented. Real registered-loopback browser checks
  cover supplied CSV through both decision stages and committed export, restart, invalid edit,
  malformed CSV and revoked-export refusal. Decisions in these checks are scripted synthetic controls.
- Durable exact proof bindings; missing/corrupt/stale proofs, changed source/policy,
  unauthorized actions and parent races refuse disclosure or export.
- Standard X weighted checks enabled after their required mapped conformance profile passed.

The API-host/runtime/pipeline/adapter development subset passed 159 distinct cases at the edit
checkpoint. Browser wire/views passed 26 pure cases. The parser gate passed 1,706 official
cases, eight boundaries and one integrity control; the post-enable target/pipeline/runtime
subset passed 1,797 cases. These scopes overlap and must not be added as independent coverage
or interpreted as application-quality measurements.

The current browser candidate's affected Python suites passed 306 cases, including the
native terminal/restart control; the frontend configuration/request suite passed nine cases.
Strict TypeScript, production build, targeted Python lint/format and offline lockfile
consistency checks pass. Registered browser evidence uses explicitly synthetic inputs and
scripted decisions; it does not establish Human or model quality. These counts overlap
earlier development checkpoints and must not be added to them.

## Worked on and incomplete

- A same-origin FastAPI factory, bounded JSON/base64 inputs, strict host-controlled fields,
  no-store/session/CSRF boundaries, checked previews and export responses are written.
  Direct socket-free ASGI controls now exercise its actual normal/refusal routes, including
  session/CSRF/Origin/Host, untrusted fields, approval/revocation and restart receipts.
- The earlier constant-handler diagnostic is superseded by the application's actual ASGI
  route controls and registered loopback browser normal/refusal/restart journeys.
- React/Vite/TypeScript production build and strict checks pass locally. All three type
  archives were audited; the retained first archive was reused and the two remaining archives
  acquired under current authority. Installed declaration files match original archive bytes;
  full MIT notices are retained. Native automated file saving was canceled; successful browser
  HTTP artifact delivery and exact read-only views do not establish an OS disk-save pass.
- Generic comparison/statistics code and provisional development fixtures are present.
  No full application evaluation or calibrated comparison has run.

## Outstanding

1. Resolve/independently qualify native browser file saving; preserve the canceled attempts.
2. Obtain independent review and remaining app-wide security/native/portable checks.
3. Complete static fixture-preview data if needed for a backend-free Bolt demonstration;
   the current static-only setup state cannot perform review or approval.
4. Complete metric-evidence pointer integration and application evaluation/reporting.
5. Validate bounded real generation/tagging/judgment integrations and honest usage/cost records.
6. Verify packaging and portability; resolve hosting/authentication before cloud provisioning.
7. Freeze a complete candidate and obtain independent finished-application review.

The CLI inventory now distinguishes authored local workflow availability from model quality.
See [README](README.md), [LESSONS](LESSONS.md) and [Bolt handoff](BOLT-HANDOFF.md).
