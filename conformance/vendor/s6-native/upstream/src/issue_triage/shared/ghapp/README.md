# GitHub boundary helpers

`auth.py`, `signatures.py` and lazy `__init__.py` form a standalone stdlib closure. Copying the
whole directory to a detached `ghapp` package can import auth/signature helpers without the S6 app,
Pydantic, provider SDKs or a key loader; the focused detached test exercises this. Preserve the root
MIT LICENSE with any export. No absolute workspace imports or automatic transport are used.

`verify_signature(raw_body, signature_header, secret)` accepts original bytes up to1MiB and a
supplied secret of at least16bytes. It requires the SHA256 header form and constant-time comparison
before JSON decoding. The public test vector comes from
[GitHub's webhook validation documentation](https://docs.github.com/en/webhooks/using-webhooks/validating-webhook-deliveries).

`app_jwt(issuer, *, now_seconds, signer)` constructs RS256 claims with issued-at60seconds in the past
and expiry540seconds in the future, calling the explicit signer's `sign(bytes, algorithm='RS256')`.
No default signer/private-key file reader exists. Synthetic signer tests check composition only;
real RSA signing and GitHub verification remain untested/pending. `AppJwt` hides the token in repr.
See [GitHub's JWT requirements](https://docs.github.com/en/apps/creating-github-apps/authenticating-with-a-github-app/generating-a-json-web-token-jwt-for-a-github-app).

`installation_token_request(installation_id, repository_id, *, role, registered_permissions)`
returns an immutable one-repo request descriptor; each `payload()` is a fresh map. Reader requests
Contents/Issues/Metadata read; apply requests Issues write/Metadata read. Every requested permission
must fit supplied registered capabilities. This constructs a request, not a minted credential or
account grant. HTTP/token expiry handling is not yet installed. See
[GitHub's token scope documentation](https://docs.github.com/en/apps/creating-github-apps/authenticating-with-a-github-app/generating-an-installation-access-token-for-a-github-app).

`webhook.py` is lazy and additionally requires the declared S6 `contracts` package/Pydantic2 under
the same parent package layout. It authenticates raw bytes, rejects duplicate/nonfinite JSON, matches
trusted installation/repository IDs and projects supported issues opened/edited. Null body becomes
an empty description; non-null text is preserved whole. Unsupported events/actions, pull requests
and configured app-self events remain visible ignored metadata; other bots can continue.

`Delivery` is a structurally bound trusted-process value, not a serializable authentication grant.
An external handler must always call `parse_delivery`; it must never construct Delivery from HTTP
JSON or treat a dataclass instance as proof against arbitrary same-user Python code.

The separate app-local `ingest.IntakeStore` and `store.JobStore` enforce atomic delivery/job state.
Intake coalescing is not a paid-evaluation cache or S3 reservation; it does not yet bind captured SHA,
allowed-label/policy/threshold/schema dependencies. Those later stages remain required.
