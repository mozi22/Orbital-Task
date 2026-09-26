# Critical Paths

Deterministic rule for labeling a PR `critical` or `non-critical`. This is **informational for the human reviewer, never a merge gate** — no agent blocks or enforces a merge based on this label.

## Rule

A PR is labeled **`critical`** if it touches any file under a path listed below. Otherwise it is labeled **`non-critical`**.

| Path | Why it's critical |
| --- | --- |
| `backend/src/takehome/db/**` | ORM models and DB session/engine setup — mistakes here corrupt or lose data. |
| `alembic/versions/**` | Schema migrations — irreversible against a live database if wrong. |
| `backend/src/takehome/config.py` | Secrets, DB connection strings, upload limits. |
| `docker-compose.yml` | Shared infra/service wiring for the whole project. |
| `backend/src/takehome/services/document.py` | File upload/storage/validation — handles user-supplied files and disk I/O. |
| `backend/src/takehome/web/routers/**` | Public API surface — a change here changes the contract every client depends on. |
| Any file matching `*auth*`, `*security*`, `*permission*` (case-insensitive) | Access control, wherever it's added. |

Everything else (UI components, prompt copy that doesn't change the request/response contract, tests, docs) is **`non-critical`**.

## Maintenance

Add a row here whenever a new module is introduced that would cause data loss, a security regression, or a breaking API/infra change if it shipped with a bug. Keep it a flat, path-based table — no judgment calls at label time.
