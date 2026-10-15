# Current implementation limitations

WP02 provides local atomic CSV ingestion and deterministic analytics as Python functions.
WP03 adds generic exact-evidence validation, a bounded numeric/passage renderer and
SQLite approval/audit/two-format export functions. These are local module functions, with
focused injected-assessment and authorization tests. A finished user workflow, application
storage/API/UI and shipping end-to-end recommendation generation remain absent. Pipeline and
tagging components have focused staging controls. Published S3/S6 source, actual rules screening
and a zero-dispatch provider gateway are present; [provenance](VENDORED.md) describes the scope.
Structural schema acceptance does not authorize a citation or an action.

Runtime policy, migration, historical-receipt and host-trust boundaries are documented in
[grounding.md](../conformance/grounding.md). Actor labels are attribution, not human
authentication; screen/semantic fixtures do not establish S6 or model readiness. Detached
corpus/queue proofs do not establish acceptance by the real downstream applications.

The input contract is `csv.v2-bounded-counts`. INT1 approved an explicit MVP-first drift on
2026-10-14: raw numeric count cells may contain at most 128 ASCII digits, including leading
zeros. Longer numeric cells reject the whole upload rather than silently excluding rows.
The original plan did not bound numeric cell size. This guard was chosen before Gold or
held-out evaluation; no held-out data was opened or used to choose it.

Exact accepted integer counts can exceed Decimal precision-28/eight-place representability.
Those metrics retain exact integer sums and eligible counts, but their value is unavailable
with `arithmetic_out_of_range`. High rates are not clamped. Date-only input never supplies
an hour. Fixed-UTC calendar overflow is an explicit error. Input normalization, bin edges,
minimum samples and clock configuration are described in [input-contract.md](input-contract.md).

Supplied labels are untrusted source data. There is no calibrated model tagging or measured
prompt-screen quality here. Actual S6 rules have synthetic contract controls; typed screening
integration remains pending. Diagnostics for individual posts are insufficient-data records.
Focused synthetic hand-computed tests establish these domain behaviors only; they do not
establish real-world recommendation quality, independent app acceptance or live provider
readiness.
