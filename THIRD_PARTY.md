# Dependency and source provenance

No prior-art code, cookbook code or cross-app implementation is copied. Dependency versions come from the official PyPI/npm registries; actual distributions, transitive notices and installed behavior still need lock/install receipts. Lockfiles are generated from those registries, never invented.

The Python package scaffold itself uses only the standard library. Declared Pydantic is reserved for later approved boundary implementation. Hatchling, pytest and ruff are build/development dependencies. React, React DOM, TypeScript, Vite and Node typings are declared frontend tooling; no React workflow exists yet.

No `VENDORED.md` exists because no verified shared source commit has been copied. Future vendoring must name actual owner source/commit/file hashes/licence and execute consumer contracts. A proposed interface or scaffold commit is not a provider/ledger implementation pin. X text-parser and official conformance/licence inputs remain unselected implementation gates.
