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
- 2026-08-16 — Closed finding **F1** with `20260816130000_reconcile_default_partition_policies.sql`,
which codifies the four partition policies that existed live and in no migration. Dry-run first and
proved byte-identical to the live definitions, so it is a no-op against production; its value is that
a database rebuilt from the migrations alone now gets them. It copies `WITH CHECK (true)` including
its weakness on purpose — that is finding B15, and Phase 2 tightens parent and partition together —
docs updated: `backend/Architecture/database.md` — Claude
- 2026-08-16 — Phase 1b: deleted the frontend mock layer entirely (841 lines and
`NEXT_PUBLIC_API_MODE`, closing C4 structurally rather than by configuration), and built the
administrator surface (closing A6). Administrators no longer use the public identity surface at
either end: `POST /auth/register` already refused the role, and `POST /auth/login` now refuses them
too, with `POST /auth/admin/login` refusing everyone else — **both with a 401 byte-identical to a
wrong password**, so neither endpoint can be used to enumerate administrators.
`app.lookup_user_for_login` gained a `role` column (`20260816140000`, re-issuing the REVOKE, GRANT
and COMMENT the DROP removed). `proxy.ts` now rewrites a server-only unlisted path to the
administrator login and 404s the ordinary one, with `proxy.test.ts` guarding all three branches.
Added `/admin` with five FR-K1 placeholder cards, four navigation entries, two coming-soon slugs and
27 message keys per locale (398 → 426) — docs updated: `prd.md` (FR-A2a extended), `tdd.md` §3.1,
`backend/Architecture/api-endpoints.md`, `database.md`, `frontend/Architecture/architecture.md`,
`architecture.html`, `README.md`, `frontend/CLAUDE.md`, root `CLAUDE.md`, `Claude/DOC-SYNC-MAP.md`,
`render.yaml`, `.env.example` — Claude
- 2026-08-16 — Recorded finding **D18** and fixed its unambiguous half: `TwoFactorChallenge.tsx` referenced `auth.twoFactor.resend`, `resending` and `resent`, none of which existed in any locale, so the only control that obtains an email one-time code rendered as the literal string `auth.twoFactor.resend`. Keys added to all three locales (426 → 429) and the screen gained the `onError` translation sweep that the house pattern uses and this component never had. The underlying defect — `login` does not send the code at all, so an `email_otp` account is told a code was sent that never was — is deferred to Phase 5, where it sits beside D1 — docs updated: `frontend/Architecture/architecture.md`, `architecture.html`, `README.md`, `frontend/CLAUDE.md` — Claude
