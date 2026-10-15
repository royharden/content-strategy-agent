# CSV input contract: csv.v2-bounded-counts

The local parser accepts an in-memory UTF-8 CSV, including a BOM and CRLF. It returns a
validated immutable dataset only after every record passes. One invalid record rejects the
whole upload. Error records contain the record number, column and safe code, without source
cell values. CSV record numbers count logical records, including records with quoted newlines.

Required headers are `post_id,date,platform,text,impressions,likes,comments,shares`; optional
headers are `topic,format`. Duplicate, missing and unknown headers reject the upload. Blank
physical records are ignored. The maximum upload is 10 MiB, with 1–5,000 data records. Text
must fit 4,000 Unicode code points both before and after NFC normalization. Text is preserved
as data: formula spellings, links and embedded instructions have no executable effects.

IDs are unique after NFC, case preserving, nonempty, at most 256 code points, with no edge
whitespace or ASCII controls. Platforms are trimmed, case folded and NFC normalized, with
1–64 code points and no ASCII controls. Supplied topic/format labels are trimmed and NFC
normalized, at most 128 code points; blanks become missing labels. Unknown platform names
are allowed and use the default length bins.

Counts contain only ASCII digits, with no sign, whitespace, decimal point or exponent.
**MVP-first successor approved by INT1 on 2026-10-14:** each raw count cell is limited to
128 digits, including leading zeros. A 129-digit count rejects the entire upload with
`numeric_limit` before integer conversion. This replaces the initial plan's uncapped numeric
cell size. Accepted counts remain exact integers; no floating point or clipping is used.
Programmatic PostRow construction enforces the same numeric value bound.

Dates use `YYYY-MM-DD`. Timestamps use ISO `T` with an explicit `Z` or numeric offset;
naive timestamps reject. Posted-local time is the default analysis clock. Fixed UTC is an
explicit alternative and is included in snapshot configuration identity. A date-only row
contributes to weekday and trend analysis but never to an hour bucket. UTC conversion
outside the supported calendar raises an explicit analysis error.

Rates use the sum of likes, comments and shares divided by the sum of impressions across
positive-impression posts. Zero-impression rows remain recorded as excluded, with exact
eligible IDs and integer numerators/denominators in the domain report. A rate requires at
least five eligible posts to receive `ok`. Rates above 1 remain valid. Decimal arithmetic
uses precision 28, ROUND_HALF_EVEN and eight fractional places, independent of ambient
precision/rounding. An arithmetic representation failure retains eligible counts and exact
integers, with `unavailable/arithmetic_out_of_range`; zero eligible impressions has a
separate reason. Low-sample numeric values remain `insufficient_data`.

Topic, format, weekday, hour and NFC text-length rates are separate families per platform.
Missing topic/format labels appear as `untagged`, with missing/supplied provenance retained.
Missing-time and eligible-hour counts are explicit. X length bins are 0–69, 70–139,
140–209, 210+; LinkedIn and unknown-platform bins are 0–139, 140–499, 500–1499, 1500+.
Empty length bins are unavailable. Top/bottom-five exact-rate diagnostics use ID tie breaks;
each remains a one-post insufficient-data diagnostic.

Four-week trends anchor at each platform's latest analysis date D, with inclusive recent
[D−27,D] and prior [D−55,D−28] windows. Each window requires five eligible posts. The
reported value is recent minus prior rate in percentage points; zero prior engagement is
valid. Window bounds, contributors and exact sums remain in the report.

Original byte SHA-256 is distinct from the unchanged WP01 NFC-normalized, ID-sorted dataset
fingerprint. Snapshot identity includes config, supplied/missing label provenance and
compute version. Reordering equivalent rows or changing the original byte envelope does
not change normalized identity. This contract adds local computation and no storage,
provider, citation authorization, approval or export authority.

Optional derived tagging uses `compute_metrics(..., tag_provenance=...)` and explicit
`metrics.v2-tagged` computation identity. The provenance tuple must contain exactly topic
and format for every known source ID, with no duplicates or omissions. Supplied source
labels must retain their value and supplied provenance. Assigned labels must already be
canonical; abstention stays `untagged`. Derived grouping uses those assignments while the
dataset fingerprint remains the original source fingerprint. Provenance/model/threshold/
taxonomy changes bind a new snapshot. `compute_tagged_metrics` also checks the TagRun's
original source fingerprint before reuse. The default `metrics.v1` path is unchanged.
