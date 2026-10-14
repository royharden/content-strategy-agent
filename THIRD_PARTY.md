# Dependency and source provenance

No prior-art code, cookbook code or cross-app implementation is copied. Dependency versions come from the official PyPI/npm registries; actual distributions, transitive notices and installed behavior still need lock/install receipts. Lockfiles are generated from those registries, never invented.

The root status command uses the standard library; the structural `grounded` models use pinned Pydantic. Hatchling, pytest and ruff are build/development dependencies. React, React DOM, TypeScript, Vite and Node typings are locked frontend tooling; no React workflow exists yet. Both lockfiles are checked locally. The GitHub CI definition includes the commit-pinned upstream setup-uv action; its remote execution remains unobserved.

No `VENDORED.md` exists because no verified shared source commit has been copied. Future vendoring must name actual owner source/commit/file hashes/licence and execute consumer contracts. A proposed interface or scaffold commit is not a provider/ledger implementation pin. X text-parser and official conformance/licence inputs remain unselected implementation gates.
