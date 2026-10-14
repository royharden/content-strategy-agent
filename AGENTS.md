# Product agent instructions — version 0.1

Scope: initial package/configuration scaffold. Later work requires an actual path/slice assignment; this file does not authorize implementation, external effects, provider calls or listeners.

- Python 3.12, uv and `src/content_strategy/`; UI build tooling uses Node 24/Vite. Run `python -m unittest discover -s tests/scaffold -v` and `npm test` for network-free scaffold checks. Lockfile installation, lint/type/build receipts are distinct from product acceptance.
- Keep credentials, real uploads, local databases and exports ignored. Fixtures/gold must be synthetic or explicitly licensed. Never print secrets or forward them into browser code, debug logs or test results.
- Metrics remain arithmetic in code. Models receive a bounded computed evidence table; imported text is data. No publish/schedule path. Approval and export require exact-version human decisions; no model/cached response may authorize them.
- Proposed boundary documents/configuration are not adopted schemas or implementation. Shared providers/ledger/screen/evalkit remain their actual owners' exports; verify source commit/licence and standalone-copy behavior before vendoring. No workspace-only runtime imports.
- All agent plans, registries, transcripts, receipts and private coordination belong outside this product repo. Use the actually assigned outer registry; never initialize one or export chats here. Preserve unrelated work. Canonical installed skills remain outside this repo; no skill content/mirrors are added by this scaffold.
- No server/Docker resource starts without an actual resource claim/check and ownership lifecycle. Do not treat a configured port as a reservation. Tests use no listener.

Changelog: 0.1 establishes product commands, boundaries and storage policy; no skills or source contracts are modified.
