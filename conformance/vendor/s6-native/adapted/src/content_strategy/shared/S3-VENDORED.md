# Canonical S3 offline Provider/Ledger

Source project: llm-router-eval, commit c7a03a8a5aa91a3881782621d8a5f09c6b82520d,
tree e0aa5796fa163fcbcb5ade87e6a33ed2e645c2e3. The complete fourteen-file shared
closure was copied unchanged from committed Git blobs under the MIT license retained in
`LICENSE.S3`. These modules belong together: providers, callledger and their shared root.
The screen adapter is separate S6 code; it does not modify or duplicate canonical accounting.

`docs/vendor/s3/SOURCE.001.json` pins original source/license/schema bytes and explicit relocated
test mappings. Tests preserve original assertions and synthetic assets; only public import
namespace is adapted from llm_router_eval to issue_triage. Owner-namespace denial guards remain
unchanged. Supplemental offline schema/price scripts use the same import mapping. No prices
were fetched; the supplied snapshot remains synthetic. Test scripts are not runtime entrypoints.

The source supports mock/strict_replay and injected simulation with a marked test transport.
S6's native screen factory supports only mock fresh bindings and strict_replay captured bindings,
using real zero-attempt Ledger allocations. No SDK, HTTP client, real secret/token authority,
live billing, genuine model capture or quality evidence follows from this copy.
