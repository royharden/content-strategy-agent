# Bolt handoff — scaffold inventory, inspection only

Status: structural models and scaffold only. No app workflow, provisioned backend, cloud account, remote repository or publication is established.

| Inventory | Implemented now | Planned / gap |
|---|---|---|
| Frontend | Vite configuration and static unfinished-state HTML | React workflow/UI and integrated browser checks |
| Core | Python structural models/identity/generic resolver protocol, generated schemas and explicit contracts-only status | CSV analytics, actual grounded validation, approval/export and local FastAPI |
| Database | Not required by scaffold | Local SQLite for proposed single-user MVP; no hosted database or migrations yet |
| Functions/auth/storage | None | Public use needs authenticated hosting and a separately assessed storage/access model |
| Provider secrets | Reserved server-only env names, no values or calls | Actual approved owner adapters and bounded tests |
| Results | None | Offline demo/evaluation, baselines, costs and limitations |

The proposed Python backend is not a Bolt-supported JavaScript backend. A future import can build browser assets; full operation needs an authenticated external Python service or an explicitly approved port passing the same conformance. Import does not provision Python, SQLite, providers or approval persistence. See [Bolt supported technologies](https://support.bolt.new/reference/supported-technologies).

Both lockfiles are committed. Setup/build commands: `uv sync --locked`; `uv run pytest`; `uv run python scripts/export_schemas.py --check`; `npm ci`; `npm run typecheck`; `npm run build`. Build output is `dist/`. No listener is needed to build. Local serving requires the actual claimed loopback port via `CSA_WEB_PORT`.

Future inspection prompt: Inspect the structural models/scaffold and stated workflow gaps. Confirm dependency install/build and show only the unfinished static page. Model/schema construction is not evidence validation, authenticated approval or export permission. Do not provision a database, deploy functions, add secrets, publish, or claim the planned workflow exists. Replace this inspection inventory only after actual application resources and checks exist.
