# Dependency and source provenance

No prior-art code, cookbook code or cross-app implementation is copied. Dependency versions come from the official PyPI/npm registries; actual distributions, transitive notices and installed behavior still need lock/install receipts. Lockfiles are generated from those registries, never invented.

The root status command uses the standard library; the structural `grounded` models use pinned Pydantic. Hatchling, pytest and ruff are build/development dependencies. React, React DOM, TypeScript, Vite and Node typings are locked frontend tooling; no React workflow exists yet. Both lockfiles are checked locally. The GitHub CI definition includes the commit-pinned upstream setup-uv action; its remote execution remains unobserved.

No `VENDORED.md` exists because no verified shared source commit has been copied. Future vendoring must name actual owner source/commit/file hashes/licence and execute consumer contracts. A proposed interface or scaffold commit is not a provider/ledger implementation pin. X text-parser and official conformance/licence inputs remain unselected implementation gates.

## twitter-text-parser and official conformance

The vendored `content_strategy.vendor.twitter_text` is the MIT-licensed 3.0.0 PyPI wheel, edition `3.0.0+stdlib.resources.1`: three import-prefix relocations and two resource-loader compatibility lines. Algorithms, configuration and emoji data are unchanged. Full MIT is included in `src/content_strategy/vendor/LICENSE.twitter-text-parser`; exact original/derived member hashes and the five-line patch are in `conformance/vendor/twitter-text-parser/`. The original installed distribution remains separate.

The separate official Twitter conformance vectors are pinned to upstream commit `65e7e00da383fb77f5ab7fe3c0dc26b724e14035` and retain their Apache-2.0 LICENSE/README in `conformance/vendor/twitter-text-official/`. The Python port MIT licence is not the official Twitter Apache licence. Required mapped v3/URL/TLD groups and synthetic boundary controls must pass before enabling X support.
