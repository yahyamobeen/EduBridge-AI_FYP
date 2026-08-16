# HISTORY

A running changelog. **Append one line per change**, newest at the bottom:

```
- YYYY-MM-DD — <what changed> — docs updated: <files> — <handle>
```

Required by [`/CLAUDE.md`](../CLAUDE.md) §4 and [`RULES.md`](RULES.md) §A2. If you were unsure
which document a change belonged in, say so here so the next pass can place it precisely.

---

- 2026-08-15 — Phase 0: added repository governance (`CLAUDE.md` at root and per application, `Claude/RULES.md`, `Claude/DOC-SYNC-MAP.md`, this file) and the first architecture documentation for both applications — docs updated: all of `backend/Architecture/`, `frontend/Architecture/`, `supabase/README.md` — Claude
- 2026-08-16 — Phase 1: closed the ten live defects from the Epic 1 review (A1–A9, C4, D11) — administrators are no longer self-registrable at either layer (new `RegistrableRole` + migration `20260816120000`), logout clears the refresh cookie via a single shared definition in `dependencies.py`, `/2fa/enroll` honours the lockout, and `environment`/`email_provider` are `Literal` types with `openapi_url` closed and `app_base_url` required to be https in production — docs updated: `backend/Architecture/api-endpoints.md`, `architecture.md`, `architecture.html`, `database.md`, `frontend/Architecture/README.md`, `prd.md` (new FR-A2a), `tdd.md` §3.1 — Claude
- 2026-08-16 — Recorded finding **F1** in `backend/Architecture/database.md`: four row-level security policies exist in the live database and in no migration (`audit_default_admin_read`, `audit_default_insert`, `reqlog_default_admin_read`, `reqlog_default_insert`). Measured from `pg_policy`, which also corrected this repository's policy count from 73 to 77. Both default partitions have row-level security forced, so a database rebuilt from the migrations alone may refuse every audit and request-log write. Reconciling migration deferred to Phase 2 and must be written from what is live — docs updated: `backend/Architecture/database.md` — Claude
