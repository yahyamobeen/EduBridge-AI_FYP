# RULES — EduBridge AI engineering and documentation maintenance

The full version of the summary in [`/CLAUDE.md`](../CLAUDE.md) §3. When this file and a
`CLAUDE.md` disagree, the application-level `CLAUDE.md` wins for its own area.

---

## A. Documentation maintenance

**A1.** Any change that adds, removes, renames or moves a route, model, migration, policy,
privileged function, setting or dependency **updates the matching `Architecture/` document in the
same change**. Which one is in [`DOC-SYNC-MAP.md`](DOC-SYNC-MAP.md).

**A2.** Every change appends one line to [`HISTORY.md`](HISTORY.md).

**A3.** The `Architecture/` pages cite `file:line`. If your edit shifts lines in a referenced file,
re-verify the citations for the symbols you moved. **Never knowingly leave a wrong line number.**

**A4.** The `.md` and `.html` pages are **parallel documents, not generated from each other**. The
Markdown reads anywhere; the HTML carries the Mermaid diagrams. Update both.

**A5. Every count in a document records the command that produced it**, so the next contributor can
re-run it rather than trusting a stale number.

**A6. Known defects appear in the documents.** Do not omit a finding because it is not fixed yet.
A document that describes a broken flow as working is worse than no document.

**A7.** Directories with only `.gitkeep` are described as **"scaffolded, no implementation"** —
never "empty", which was measured and found wrong once already.

---

## B. Architecture conventions

**B1. One backend router today** (`app/auth/routes.py`). New feature areas get their own router
module and are mounted in `app/main.py`.

**B2. Pre-authentication database access goes through narrow `SECURITY DEFINER` functions**, never
through the Row-Level-Security-bypassing service connection. The standing rule: *if a new endpoint
appears to need the service connection, add another narrow function rather than widening the door.*

**B3. No endpoint invents an error code.** The catalogue is `tdd.md` §7.3. If nothing fits, the
answer is `VALIDATION_ERROR` with `details.fields`, or a contract change — not a new string.

**B4. Frontend forms use plain `useState`.** `react-hook-form` and `zod` are in `package.json` and
imported by zero source files. Do not start for one screen.

**B5. Frontend markup uses logical Tailwind properties** (`ms`/`me`, `ps`/`pe`,
`text-start`/`text-end`). `lib/i18n-rules.test.ts` fails the build on physical ones, because Urdu
renders right-to-left.

---

## C. Data and migrations

**C1. Never edit an applied migration.** Add a new one. Filenames are
`YYYYMMDDHHMMSS_snake_case_subject.sql` and run in filename order.

**C2. Changing a function's `RETURNS TABLE` or adding a parameter requires `DROP` then `CREATE`**,
not `CREATE OR REPLACE`. Adding a parameter *overloads* rather than replaces, and the existing call
then matches both signatures and fails at runtime with "function name is not unique".

**C3. A `DROP FUNCTION` takes its `GRANT` and its `COMMENT` with it.** Re-issue both in the same
migration, or the next call gets "permission denied for function".

**C4. Every migration file is idempotent** (`ADD COLUMN IF NOT EXISTS`, `DROP … IF EXISTS` before
each `CREATE`). The Supabase CLI (Command-Line Interface) does not wrap a file in a transaction, so
a half-applied file must be re-runnable.

**C5. Every `SECURITY DEFINER` function carries** `SET search_path = public, pg_temp`,
`REVOKE ALL … FROM PUBLIC`, `GRANT EXECUTE … TO app_backend`, and a `COMMENT ON FUNCTION` naming
the calling endpoint first.

**C6. Claude never pushes a migration.** Produce the file, verify it with a dry run against a
shadow or branch database, and **report the actual output**. The repository owner applies it before
a merge to `main`.

**C7. The user binding is transaction-scoped.** A stray `commit()` mid-request ends the transaction
and silently discards it; every query after that returns zero rows with no error raised anywhere.
If a query returns nothing and the row is definitely there, look for a stray commit first.

---

## D. Security and secrets

**D1. `.env` content is sacred.** Never log a secret, never commit one, never edit `.env` directly.
Suggest what to add; the owner adds it.

**D2. `DATABASE_URL` connects as `app_backend`, never `postgres`.** The owner role bypasses
Row-Level Security, which leaves every policy inert while the application appears to work. The
backend refuses to start if its role reports `rolsuper` or `rolbypassrls`.

**D3. Access token in memory only.** Never `localStorage`, `sessionStorage`, a readable cookie, or
a query string. The refresh token is an httpOnly cookie.

**D4. `question_key` has no Row-Level Security policy and must never gain one.**

**D5. Chat content is owner-only.** No teacher, parent or administrator read path for
`chat_session`, `message` or `visual_aid`.

**D6. Never run `npm audit fix --force`.**

---

## E. Working style

**E1. Never self-speculate and never hallucinate.** Ground every decision in `prd.md`, `tdd.md`,
the applied SQL, existing repository code, or official library documentation — and say which.

**E2. When something is ambiguous, look for the in-house pattern first.** If it is still ambiguous,
**stop and ask**. One problem per question — never bundle several into one message.

**E3. Impact analysis on every function you touch.** Walk the full caller and callee graph and
update every site, not only the one that prompted the change.

**E4. Divide large work across subagents** and reason each aspect through.

**E5. Plans carry before-and-after snippets for backend changes** — every Python and SQL change
shows a before block and an after block, because that is where the subtle, security-critical work
lives. **Frontend changes are described in prose** against the file and symbol, with a snippet only
where the shape is genuinely unobvious. This asymmetry is deliberate; a missing frontend snippet is
not an omission.

**E6. Plans are self-reviewed before the user sees them** — adversarially, looking for gaps, wrong
assumptions, security holes and integration mismatches.

**E7. Keep the user in the loop.** Explain what you are doing and why, so they can validate the
direction before the work is done rather than after.

---

## F. The phase gate

No phase begins until the previous one is closed, **in this order**:

1. Verification passes, with the **real output reported**.
2. Tests written for the change exist and are green at every level it touches.
3. Architecture documents and `HISTORY.md` updated in the same change; `prd.md` and `tdd.md` too if
   the phase introduced anything not already in them.
4. A commit message handed over covering the **final state of the phase** — not intermediate fixes,
   not the debugging, not the discussion. **No `Co-Authored-By` line, no tool attribution.**
5. **The user commits it themselves.** Claude never commits, branches, pushes, or opens a pull
   request.
6. **The user confirms.** Only then does the next phase begin.

## G. Context-window discipline

- **Above 75%** — do not start a new phase and do not begin new planning. Finish what is in flight.
- **At 80%** — complete the work in flight, write the handoff, update the memory files, and ask the
  user to compact.

There is no precise readout of remaining context, so apply this **conservatively — err early**.
Stopping a phase short is recoverable; running out part-way through a migration is not.

**Handoff state lives outside the repository root**, at
`C:\Users\DELL\Desktop\EduBridge-AI_FYP-handoff\`, so a careless `git add -A` cannot pick it up.
Nothing committed ever references it, so its absence cannot break a checkout.
