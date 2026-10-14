# Current implementation limitations

WP02 provides local atomic CSV ingestion and deterministic analytics as Python functions.
It is not a finished user workflow. Storage, provider integration, automated tagging,
recommendation generation, citation validation, approval, audit and export effects remain
unimplemented. Structural schema acceptance does not authorize a citation or an action.

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

Supplied labels are untrusted source data. There is no calibrated model tagging or tested
prompt screening here. Diagnostics for individual posts are insufficient-data records.
Focused synthetic hand-computed tests establish these domain behaviors only; they do not
establish real-world recommendation quality, independent app acceptance or live provider
readiness.
