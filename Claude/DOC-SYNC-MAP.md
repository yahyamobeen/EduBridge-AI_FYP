# DOC-SYNC-MAP — which docs to update when you touch the code

The lookup table referenced by [`/CLAUDE.md`](../CLAUDE.md) §4 and
[`RULES.md`](RULES.md) §A. When a change touches a code area on the left, you **must** update the
documents on the right **in the same change** and append to [`HISTORY.md`](HISTORY.md).

> Rule of thumb: the `Architecture/*` pages cite **`file:line`**. If your edit shifts lines in a
> referenced file, re-verify the citations for the symbols you moved.

## Backend

| Code area | Docs to update | What to check |
|---|---|---|
| `supabase/migrations/*` | `backend/Architecture/database.md` **and** `database.html`; `supabase/README.md` if the migration list changes | New/renamed/dropped table, column, policy, function, grant or index → update the entity-relationship diagram, the policy catalogue, the `app.*` function catalogue, and the migration count. **A dropped function loses its grant and comment — check both are re-issued.** |
| `backend/app/auth/routes.py` | `backend/Architecture/api-endpoints.md`; `architecture.*` if it adds a flow | Method, path, handler name and line; which dependency guards it; its rate-limit bucket; whether it moves a route out of the "specified but missing" list. |
| `backend/app/auth/service.py` | `backend/Architecture/architecture.md` **and** `architecture.html` | Any change to the request lifecycle, the token model, the onboarding derivation, or which `app.*` function a flow calls. |
| `backend/app/auth/dependencies.py` | `backend/Architecture/architecture.*` | The per-request check order and the number of database round trips before business logic. Both are documented explicitly. |
| `backend/app/auth/tokens.py`, `security.py` | `backend/Architecture/architecture.*` (token-kinds table) | Kind, lifetime, storage, and the single endpoint each kind is accepted by. |
| `backend/app/auth/gate.py`, `onboarding.py` | `backend/Architecture/architecture.*` | The gate decision and the onboarding state machine are both drawn as diagrams — update the diagram, not only the prose. |
| `backend/app/core/config.py` | `backend/Architecture/architecture.*`; `backend/.env.example` | A new setting needs a default, or `tests/unit/conftest.py` breaks at collection (it sets environment variables at import time). |
| `backend/app/core/errors.py` | `backend/Architecture/architecture.*`; **`tdd.md` §7.3**; `frontend/lib/api/errors.ts` | A new code must exist in all three, or the client renders "something went wrong". |
| `backend/app/core/ratelimit.py` | `backend/Architecture/architecture.*` | Bucket name, limit, window, and whether it keys on address or user. |
| `backend/app/models/*` | `backend/Architecture/database.md` | The models mirror the applied SQL — if they drift, say so rather than silently correcting one side. |
| `backend/pyproject.toml`, `requirements*.txt` | `backend/Architecture/README.md` | Dependency list; regenerate the exports together with `uv lock`. |

## Frontend

| Code area | Docs to update | What to check |
|---|---|---|
| `frontend/app/**/page.tsx`, layouts | `frontend/Architecture/architecture.md` **and** `.html` | Route group, what the layout renders, and the page count. |
| `frontend/lib/auth/navigation.ts` | `frontend/Architecture/architecture.*` | This is a Role-Based Access Control boundary, not styling. Any new item needs its role list checked. |
| `frontend/lib/auth/onboarding.ts` | `frontend/Architecture/architecture.*` | The state → route table is documented; it is the only routing input. |
| `frontend/lib/api/client.ts`, `endpoints.ts`, `types.ts` | `frontend/Architecture/architecture.*`; `backend/Architecture/api-endpoints.md` if the contract shifts | Mock-versus-live condition, refresh behaviour, retry allow-list. The types mirror `tdd.md` §3.1. |
| `frontend/lib/api/mock/*` | `frontend/Architecture/architecture.*` | The mock must mirror the real contract; a drift here is a type error rather than a runtime surprise, and that is the point. |
| `frontend/components/app/SessionGuard.tsx` | `frontend/Architecture/architecture.*` | The three checks and their order are documented, as is the fact that it fails closed. |
| `frontend/next.config.mjs` | `frontend/Architecture/architecture.*` | Content Security Policy directives, the security headers, and the `/api` rewrite — all three are documented with their reasons. |
| `frontend/messages/*.json` | — | No document to update, but all three locales must stay at the same key set. |

## Cross-cutting

| Code area | Docs to update |
|---|---|
| `render.yaml` | `backend/Architecture/README.md` deployment notes; `frontend/Architecture/README.md` |
| `.github/workflows/*` | `backend/Architecture/README.md` |
| Anything that changes a **requirement** | **`prd.md` and `tdd.md`**, in the same change, plus the architecture pages |
| A new finding or a fixed defect | The "Known gaps" section of the page that owns it |

## When in doubt

If a change is structural enough that you are unsure which document it lands in, update
`backend/Architecture/architecture.md` (the narrative) at minimum, and note the uncertainty in
[`HISTORY.md`](HISTORY.md) so the next pass can place it precisely.
