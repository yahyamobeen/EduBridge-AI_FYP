# Frontend Architecture

Next.js App Router client for EduBridge AI — screens, routing and a transport layer over the FastAPI backend.

> **Snapshot date: 2026-08-15.** Describes commit `eea0e74` on branch `fix-epic-1` (`git log -1 --format=%h` → `eea0e74`), plus the uncommitted Phase 0 documentation.
> Source of truth is the code. Every `file:line` below was opened and verified at this snapshot; paths are relative to `frontend/`.

---

## Measured facts

Every count here has the command that produced it beside it. Run from `frontend/`.

| Measure | Value | Command |
|---|---|---|
| Pages | **30** (4 added by classroom Phase 2, 2 by Phase 5, 1 by Phase 8) | `find app -name "page.tsx" \| wc -l` |
| Route groups | **3** | `find app -type d -name "(*)" \| wc -l` |
| Test files | **44** | `find . -path ./node_modules -prune -o -path ./.next -prune -o \( -name "*.test.ts" -o -name "*.test.tsx" \) -print \| wc -l` |
| Locales | **3** (`en`, `ur`, `ur-Latn`) | `ls messages/` |
| Leaf message keys per locale | **787**, identical across all three and in the same order | see `README.md` § *How those numbers were measured* |

*Re-measured 2026-10-05 (classroom Phase 8).*

`node_modules/` and `.next/` are excluded from every count.

---

## Stack

| Layer | Choice | Where |
|---|---|---|
| Framework | Next.js `^16.2.12` (App Router) | `package.json:19` |
| UI runtime | React `^19.2.8` | `package.json:21` |
| Language | TypeScript `^6.0.3` | `package.json:48` |
| Styling | Tailwind CSS `^3.4.19` | `package.json:47` |
| Internationalisation | next-intl `^4.13.4` | `package.json:20` |
| Tests | Vitest `^4.1.10` + Testing Library | `package.json:49`, `vitest.config.mts` |

**Two dependencies are installed and imported by zero source files**: `react-hook-form` (`package.json:23`), `zod` (`package.json:24`) and their resolver bridge `@hookform/resolvers` (`package.json:18`). Every form in this application is plain `useState`. That is a deliberate choice, not an oversight — the forms here are short and the validation is server-authoritative — but the packages are still in the dependency tree and a future contributor should know they are unused rather than assume a convention exists.

`package.json:26-30` carries an `overrides` block lifting `postcss` and `sharp` off the versions Next pins, with the reason recorded inline: `npm audit fix --force` "resolves" those advisories by installing `next@9`, which is not a fix.

---

## The route tree

Everything lives under one dynamic `[locale]` segment. `app/layout.tsx:9-11` is a bare pass-through, because `<html>` cannot live there — `lang` and `dir` both depend on the locale, which is only known inside `[locale]`. The real document shell is `app/[locale]/layout.tsx:32-60`.

```
app/
  layout.tsx                     pass-through (:9-11)
  [locale]/
    layout.tsx                   <html lang dir>, NextIntlClientProvider, SkipLink (:32-60)
    error.tsx                    locale-wide error boundary (:20-71)
    not-found.tsx                localized 404, renders its own chrome (:15-38)
    (site)/    layout.tsx        TopNav + main + Footer (:12-22)
    (auth)/    layout.tsx        bare main, no chrome (:11-17)
    (app)/     layout.tsx        AppFrame: the guard and the sidebar, mounted once (:15-21)
```

`app/[locale]/layout.tsx:17-19` pre-renders all three locales at build time via `generateStaticParams`. `:38` sends an unknown locale to `notFound()` rather than falling back to English — a student who lands on `/pk/login` is told the page is wrong instead of being handed a language they may not read. `:41` calls `setRequestLocale`, without which every page opts into dynamic rendering; that static prerendering is what the Content Security Policy section below turns on.

### The three route groups

A route group adds **no path segment**. `/login` is `/login` whether or not it sits inside `(auth)`. The split exists purely so the three surfaces can have different chrome.

#### `(site)` — the public marketing surface

`app/[locale]/(site)/layout.tsx:12-22` renders `TopNav`, `main`, `Footer`. Seven pages:

| Route | File |
|---|---|
| `/` | `(site)/page.tsx` |
| `/signup` | `(site)/signup/page.tsx` |
| `/signup/student` | `(site)/signup/student/page.tsx` |
| `/signup/parent` | `(site)/signup/parent/page.tsx` |
| `/signup/teacher` | `(site)/signup/teacher/page.tsx` |
| `/coming-soon/[slug]` | `(site)/coming-soon/[slug]/page.tsx` — 21 allow-listed slugs at `:15-41` |
| catch-all | `(site)/[...rest]/page.tsx:8-10` — calls `notFound()` so an unmatched path renders the *localized* 404 |

`/coming-soon/[slug]` is the destination for every prototype link whose product area is not built yet. `:61` rejects any slug outside the literal list with `notFound()`; `:53-55` statically generates all 21 slugs × 3 locales. It exists because `href="#"` reads as broken and deleting the links loses the prototype's navigation.

#### `(auth)` — the transactional screens

`app/[locale]/(auth)/layout.tsx:11-17` is **deliberately bare**: no top nav, no footer. The reason is recorded at `:3-10` — a half-authenticated user has nowhere legitimate to navigate to, and offering the marketing nav mid-challenge is an invitation to abandon the flow. Each screen carries its own minimal footer links instead (`components/auth/AuthFooterLinks.tsx`).

Ten pages:

| Route | File | Notes |
|---|---|---|
| `/login` | `(auth)/login/page.tsx` | |
| `/login/2fa` | `(auth)/login/2fa/page.tsx` | Reachable only from `/login`, which puts the `pending_token` in memory first (`:13-18`) |
| `/onboarding/email` | `(auth)/onboarding/email/page.tsx` | |
| `/onboarding/2fa` | `(auth)/onboarding/2fa/page.tsx` | |
| `/onboarding/guardian` | `(auth)/onboarding/guardian/page.tsx` | Class 9–10 students only; the backend never puts a Class 11–12 student in that state (`:13-18`) |
| `/onboarding/plan` | `(auth)/onboarding/plan/page.tsx` | The one step a user can reach *after* having been `active` (`:13-17`) |
| `/verify-email` | `(auth)/verify-email/page.tsx` | |
| `/forgot-password` | `(auth)/forgot-password/page.tsx` | |
| `/reset-password` | `(auth)/reset-password/page.tsx` | |
| `/guardian/confirm` | `(auth)/guardian/confirm/page.tsx` | Where the invitation email lands; authenticated as the **parent** (`:16-21`) |

#### `(app)` — the authenticated application, and the frame it keeps mounted

`app/[locale]/(app)/layout.tsx:15-21` renders `<AppFrame>` (`components/app/AppFrame.tsx:15`) inside
the `<main>`: the identity check (`SessionGuard`) and the role's sidebar (`DashboardShell`), **once**,
with every `(app)` page rendered inside them. Every one of the 11 pages in the group has a sidebar,
so none gains or loses one.

⚠️ **Until classroom Phase 6c (2026-10-05) the layout rendered a bare `<main>`, on purpose**: the
sidebar depends on the role, known only once the guard has resolved the identity, so each page wrapped
itself in its own `SessionGuard` and `DashboardShell`. The cost, reported by the owner: **every
navigation unmounted the sidebar, blanked the screen to "Loading…" and built a new one.** The frame
now resolves the identity once and stays mounted. The sidebar's subtitle is one per user — a
student's board, class and group; anyone else's role (`AppFrame.tsx:19-29`) — rather than one per
page, and the two per-page subtitle keys that fed it were removed. Each page still declares its own
roles with `RequireRole` (below). The layout itself stays a server component; `AppFrame` is the
client boundary.

Three pages, one per role that has a dashboard:

| Route | File | Component | `allow` |
|---|---|---|---|
| `/dashboard` | `(app)/dashboard/page.tsx:13-17` | `StudentDashboard` | `['student']` — `components/app/Dashboards.tsx:34` |
| `/teacher` | `(app)/teacher/page.tsx:13-17` | `TeacherDashboard` | `['teacher']` — `Dashboards.tsx:80` |
| `/parent` | `(app)/parent/page.tsx:13-17` | `ParentDashboard` | `['parent']` — `Dashboards.tsx:103` |
| `/admin` | `(app)/admin/page.tsx:13-17` | `AdminDashboard` | `['admin']` — `Dashboards.tsx:145` |

**`/admin` was built in phase 1b**, which closes defect **A6**. Administrators reach it after signing
in at an unlisted path served by `(auth)/admin-login/page.tsx` — see *The unlisted administrator
login* below.

**The classroom pages (classroom Phase 2, 2026-10-04).** Four more `(app)` pages, each a thin server
page (`setRequestLocale`, the `settings/page.tsx` pattern) rendering a client component with an
**exact** `allow` list — one route per role, so the RBAC boundary is a route boundary:

| Route | File | Component | `allow` |
|---|---|---|---|
| `/classroom` | `(app)/classroom/page.tsx` | `StudentClassrooms` — list + join form | `['student']` |
| `/classroom/[spaceId]` | `(app)/classroom/[spaceId]/page.tsx` | `StudentClassroom` | `['student']` |
| `/teacher/classroom` | `(app)/teacher/classroom/page.tsx` | `TeacherClassrooms` — list + create form | `['teacher']` |
| `/teacher/classroom/[spaceId]` | `(app)/teacher/classroom/[spaceId]/page.tsx` | `TeacherClassroom` | `['teacher']` |
| `/classroom/calendar` | `(app)/classroom/calendar/page.tsx` | `StudentCalendar` (classroom Phase 5) | `['student']` |
| `/teacher/classroom/calendar` | `(app)/teacher/classroom/calendar/page.tsx` | `TeacherCalendar` (classroom Phase 5) | `['teacher']` |
| `/parent/classroom` | `(app)/parent/classroom/page.tsx` | `ParentClassrooms` (classroom Phase 8) — read-only | `['parent']` |

The two list pages prerender in all three locales; the two `[spaceId]` pages have no
`generateStaticParams` and render on demand, because the id is per user and the data is fetched in
the browser (the access token lives only in client memory). The client refuses a non-UUID id without
making a request. Since classroom Phase 5 they also read `?assignment=<id>` from `searchParams` (on
the server, so no `useSearchParams` and no Suspense boundary) and open Classwork on that assignment —
the calendar's links; a non-UUID value is ignored. The two `calendar` pages are a static segment, so
they win over the sibling `[spaceId]`, and prerender like the list pages; there is no new navigation
entry — each list page links to its calendar. Components live in `components/classroom/`:

- **`ClassroomView.tsx`** — one classroom for both roles. ⚠️ **Owner controls (join code, rename,
  archive, remove) render from the server's `viewer_role === 'owner' && can_manage`, never from the
  session role.** A teacher whose subject scope was revoked is still `owner` but gets no controls and
  is told why. Not the security boundary — the database is — but `prd.md` §4.2 forbids rendering a
  control the caller cannot use. Since classroom Phase 3 its sections are tabs — **Stream** (the
  default), **Classwork** (Phase 4), **Chat** (Phase 7) and **People** — built on `components/ui/Tabs.tsx` (below); later phases add theirs to the
  `TABS` constant. On People the owner can also **mute** a student in the chat (and unmute them);
  the "Muted in chat" label comes from the server's `muted`, which only the owner receives.
- **`StreamTab.tsx`** (classroom Phase 3) — announcements, newest first. **Nothing here filters
  scheduled posts**: a member never receives one, because the database withholds it
  (`announcement_member_read`), so the owner alone sees the "Scheduled for" badge. Bodies render as
  plain text in `whitespace-pre-wrap` — never HTML, never auto-linked. The composer and the edit form
  offer *post now* or *schedule* (a `datetime-local` whose `min` is now); a published post can be
  edited but not rescheduled, matching the API. "Load older" follows `next_cursor` and **merges by
  id**, because a post published between two requests can appear on both pages. Posting is offered
  only for the owner of a non-archived classroom (`canPost`); errors branch on `ApiError.code` and
  `details.fields`, never on `message`.
- **`ClassworkTab.tsx`** (classroom Phase 4) — assignments, newest first, with "Load older"
  merging by id as the stream does. Opening one replaces the list **in place** with
  `AssignmentView.tsx`, and "Back" returns to the list kept in step with any change made inside — no
  new route, so the RBAC boundary stays the two existing classroom pages. Nothing filters: a member
  never receives a scheduled assignment, and each member's status is **derived by the server**
  (`StatusChip`, in `AssignmentParts.tsx`, only names and colours it).
- **`AssignmentForm.tsx`** — create and edit. Points are validated as a whole number 1–1000
  **before** sending; the due date and schedule go out as ISO instants with an offset
  (`lib/datetime.ts`); the chapter picker reads `/reference/subjects/{id}/chapters` and is replaced by
  a note when the subject has none. An edit sends only what changed, with `null` to clear an
  optional field — the API's contract. **Creating can carry files** (Phase 6b): they are checked and
  held, then uploaded one by one once the assignment exists — an upload needs its id, and one
  multi-file request is the multipart body the server refuses. A file that fails does not undo the
  assignment: `onSaved` names it, and `ClassworkTab` opens the new assignment with those names, where
  "Add a file" is the retry.
- **`SubmissionPanel.tsx`** — the student's own work, in three states read from the server's answer
  (editing, turned in, returned). Unsaved edits are saved **before** turning in, not lost behind it.
  A refusal gets its own message, chosen by `details.reason` (`graded`, `turned_in`). Since Phase 6b
  only the written answer is a draft: files and links are saved the moment they are added, through
  `WorkAttachments`, and the old single link field is gone.
- **`GradingTable.tsx`** — every active member, with "Review" opening their work inline. A draft is
  never shown (the server returns nothing until it is turned in). A grade above the points is
  refused before sending; "Save and return" sends `return_to_student: true`, and the row updates in
  place from the response. In an archived classroom the work is still readable and grading is
  hidden, matching the database, which refuses it.
- **`ChatTab.tsx`** (classroom Phase 7) — the class chat. It **says it is class-public** above the
  messages ("Everyone in this class can read what is written here"). Names come from the roster
  (`getPeople`), the one place the database releases them; an author the roster no longer lists
  refreshes it **once** and is then a "former member". ⚠️ **The Teacher badge comes from
  `people.owner.user_id`, never from a name**, so a student who calls themselves "Sir Ahmed" gets
  none. Bodies are plain text (`whitespace-pre-wrap`). Enter sends and Shift+Enter starts a new
  line — never while an input method is composing, which matters for Urdu. A student who cannot
  post sees why instead of the box: archived, muted, or locked; a post refused before the next poll
  noticed (`details.reason`) shows the same reason, and a `RATE_LIMITED` one how long to wait; a
  failed send keeps the draft. The owner gets a per-message Delete behind `ConfirmInline` — the
  message stays on their screen, marked deleted, because the server keeps it for them — and a
  Lock / Unlock chat button (`PATCH /spaces/{id}` with `chat_locked`), and can still post while
  locked.
- **`useChatPoll.ts`** (classroom Phase 7) — the poll behind it. A `setTimeout` **chain**, never
  `setInterval`, every 5 s (`POLL_MS`), so two polls never overlap on a slow connection; nothing
  while the tab is hidden, and an immediate catch-up when it is shown again. The cursor is the
  server's `server_time` — the database clock, never this device's. Messages are a `Map` by id, so
  the overlap window's repeats merge away; `deleted_ids` removes a member's copy and marks the
  teacher's; `reset` replaces everything with the newest page. A 429 waits as long as `retry_after`
  says; a 403 (removed, gated) stops polling and says the chat is unavailable; anything else keeps
  what is on screen and tries again.
- **`JoinClassForm.tsx`** — branches on `details.reason` (`invalid_code`, `class_mismatch` with the
  class named, `classroom_full`) and on `GATE_PENDING` / `RATE_LIMITED`; never on `message`.
- **`CreateClassForm.tsx`** — board → class → subject from `/reference/enums` and
  `/reference/subjects`; changing board or class discards the chosen subject.
- **`ConfirmInline.tsx`** — the second step before remove, leave, archive and turning joining off.
  Inline rather than a `<dialog>`: jsdom implements no `showModal`, so a dialog could not be tested.
- **`styles.ts`** — the card and button class strings `Settings.tsx` uses, shared by the classroom
  components.

Two shared pieces arrived with the stream:

- **`components/ui/Tabs.tsx`** — a WAI-ARIA tablist with automatic activation: one tab in the Tab
  order, arrows move, Home/End jump. ⚠️ **The arrow keys follow the screen, not the source order**:
  under `dir="rtl"` the first tab is drawn on the right, so ArrowRight moves towards the *start* of
  the list. Direction is read from the element's computed style rather than the locale, so the
  component is correct wherever it is mounted. Callers give each panel `id={tabPanelId(key)}`,
  `role="tabpanel"` and `aria-labelledby={tabId(key)}`.
- **`lib/datetime.ts`** — the only bridge between `<input type="datetime-local">` (wall-clock time,
  no offset) and the API (ISO instants **with** an offset; the backend refuses a naive one).
  ECMAScript parses an offset-less date-time as local time, so the conversion the backend will not
  guess is made in the browser, where the user's zone is actually known.

The calendar (classroom Phase 5):

- **`components/classroom/Calendar.tsx`** — `StudentCalendar` / `TeacherCalendar` (exact `allow`),
  `CalendarView` (month navigation and loading) and `CalendarMonth` (the grid). It decides nothing
  about visibility: `GET /calendar` returns only what the caller could already see. Loading is
  derived from the month the data belongs to rather than set inside the effect, so changing month
  never calls `setState` synchronously in an effect. **One DOM, two layouts**: seven columns from
  `md` up; below that, only the days that have entries, as a list. Each day carries its full date in
  `sr-only` text, so a screen reader never hears a bare number. Entries link back into the
  classroom — an assignment to `?assignment=` (Classwork), an announcement to the classroom itself.
- **`lib/calendar.ts`** — `monthGrid` (6 × 7 local days, weeks from Monday), `gridRange` (the
  instants at the grid's edges — always within the API's 62 days), `dayKey`, `addMonths`. All local:
  the grid is the user's wall calendar, never UTC's. `lib/calendar.test.ts` asserts with local
  getters, so it holds in any time zone.

Files (classroom Phases 6 and 6b):

- **`components/classroom/Files.tsx`** — `FileSection`, a teacher's attachments on a stream post
  (`StreamTab.tsx`) and on an assignment (`AssignmentView.tsx`), with add and remove for the owner;
  and `FileItem` (`:58`), one file's row — download, **View**, remove — which `WorkAttachments`
  shares. Add and remove appear only when the caller passes `upload` / `remove`. **The server is the check** — it reads the type from the bytes
  and enforces every limit; the client refuses only what is certain to fail (a wrong extension, an
  empty file, over 5 MB) so nobody waits on a doomed upload. A refusal is explained by
  `details.reason` through `REASON_KEY` (`Files.tsx:25`), never by `message`; removing asks first
  (`ConfirmInline`). **View** (Phase 6b) appears only for a PDF or an image (`lib/files.ts`,
  `isViewable`): it asks for a five-minute link and opens it in a new tab. Office files are
  download-only (owner decision 2026-10-05).
- **`components/classroom/WorkAttachments.tsx`** (Phase 6b) — a student's files **and links** in one
  list, in the order added, used in `SubmissionPanel.tsx` (editable only while the work is a draft)
  and `GradingTable.tsx` (the teacher's read-only review). One **"+ Add"** menu offers File (the
  hidden picker) or Link (an inline https field), like Google Classroom. It is a WAI-ARIA menu
  button: ArrowDown opens it on the first item, arrows/Home/End move, Escape closes it and returns
  focus, Tab or a click elsewhere closes it. A link renders as an anchor only if it is `https://`,
  with `rel="noopener noreferrer"`, and a non-https link is refused before it is sent; a refusal is
  `details.fields.url` or `details.reason` (`too_many_links`, `graded`, `turned_in`).
- **`lib/files.ts`** (Phase 6b) — the client-side checks the three file pickers share:
  `earlyRefusal` (extension, 5 MB, empty) and `isViewable`.
- **`lib/download.ts`** — `saveBlob`: a download is always **saved, never opened** inside the
  application (`prd.md` CL-8). The `BackupCodes.tsx` technique — a temporary object URL on a
  temporary link, revoked on the next tick — in one place for the classroom. `openInNewTab`
  (`:27`, Phase 6b) opens the tab **synchronously inside the click** — a pop-up blocker allows that
  and not a window opened after an await — cuts `opener`, then points the tab at the fetched link;
  if the link cannot be had, it closes the blank tab.

The parent's overview (classroom Phase 8):

- **`components/classroom/ParentClassrooms.tsx`** — `/parent/classroom`, `allow={['parent']}`. One
  call, `GET /parent/classrooms`, rendered as each child, then each classroom (subject and teacher,
  an "Archived" label where it applies), then its assignments: deadline, the server-derived status
  (`StatusChip`, shared with Classwork) and a grade **only as the server sends it**, which is once
  returned. ⚠️ **Nothing to click**: no link into a classroom, no tab, no button — a classroom's own
  pages carry the stream, the chat and classmates' names, none of which a parent may see — and a
  test asserts there is no link, button or tab on the page. It says, above everything, what it
  never shows. A linked child in no classroom, and a parent with no linked child, each get a sentence
  saying so. The sidebar marks it current by the longest-prefix rule (`/parent/classroom` beats the
  dashboard's `/parent`).

The dashboards are shells. `Dashboards.tsx:9-22` records why: no dashboard data endpoint exists in the contract, so the panels name what will live there and say plainly that it is not available yet, rather than rendering the mockups' invented 78% exam readiness. `PlaceholderCard` (`components/app/DashboardShell.tsx:188`) renders the "not yet available" pill. What *is* real on these pages is the navigation and the role boundary — and, **since classroom Phase 6c, the classroom card**: `ClassroomsCard` (`components/app/ClassroomsCard.tsx:24`) replaced the student's "My classes" and the teacher's "My classrooms" placeholders, which kept saying "Not available yet" for a feature built in Phase 2. It lists up to three active classrooms from `GET /api/spaces` (the teacher's with member counts), says what to do when there are none — join with a code, or create the first — and, if the request fails, still offers the way in; it never shows the pill. The teacher's "Class roster" placeholder is unchanged, pending the owner's decision (its body promises "who has not joined yet", which the API cannot know; each classroom's People tab is the roster).

---

## `SessionGuard` and `RequireRole` — the gate on every authenticated route

`components/app/SessionGuard.tsx`. Since classroom Phase 6c the gate is in two parts: `SessionGuard`
(`:43`) lives in the `(app)` layout through `AppFrame` and answers *who is this, and is their journey
complete?*; `RequireRole` (`:132`) lives in each page and answers *may this role see this page?*.

### Shape

Both are **render-prop** components, not wrappers and not hooks:

```ts
// components/app/SessionGuard.tsx:43, :132
export function SessionGuard({ children }: { children: (me: MeResponse) => ReactNode })
export function RequireRole({ allow, children }: { allow: Role[]; children: (me: MeResponse) => ReactNode })
```

`children` is a *function* of the resolved identity. That shape is load-bearing: the page body cannot be
constructed at all until `me` exists, so there is no branch on which a component can render with an
undefined user. `SessionGuard` shares `me` through a context (`useMe`, `:121`); `RequireRole` reads it
from there, so a page's role check makes no second request. Call sites: `Dashboards.tsx:29`, `:70`,
`:98`, `:140`, and the Settings, classroom and calendar pages.

### The three checks, in order

1. **No session → `/login`.** `SessionGuard`, `:77-81`: any failure to establish identity is treated as
   "not signed in". The client has already attempted a refresh by this point.
2. **Onboarding incomplete → the step that completes it.** `SessionGuard`, `:72-75`: if
   `identity.onboarding_state !== 'active'`, `router.replace(routeForOnboardingState(…))`.
3. **Wrong role → that role's own dashboard.** `RequireRole`, `:145-150`: a parent who opens
   `/dashboard` is sent to `/parent`, not to an error page, and sees "Redirecting…" meanwhile — never
   the page.

**The identity is re-read on every navigation** — the effect is keyed on the path (`:50-99`) — because
onboarding is not monotonic (below). What changed in Phase 6c is only what is on screen meanwhile: the
page and the sidebar stay while the re-check runs (stale while revalidating), and a redirect follows
if the state went backwards. Tests: `SessionGuard.test.tsx:62-90` (the three checks and the happy path),
`:98-132` (the lapsed trial, the re-read on navigation, and the page staying on screen meanwhile).

### It fails closed on first entry

`:101-115`: while there is no identity yet, `SessionGuard` renders a `role="status"` region and **no
page content** — `checked ? t('redirecting') : t('loading')`. There is no `me ?? fallbackUser` and no
optimistic path. This is now the **only** blank screen: a full load or a refresh. `SessionGuard.test.tsx:134-140`
asserts that a permanently pending first check produces no page content.

### It is **not** a security control

Stated in the file's own header at `:25-27`, and repeated here because it is the single most misreadable thing in this application:

> None of this is a security control. The gate is enforced at the API and RLS layers, so calling the endpoint directly is still refused; this only stops the UI showing a user a page they cannot use.

`SessionGuard` runs in the browser. Its inputs come from a `fetch` the user controls, its decisions are `router.replace` calls the user can skip, and its entire bundle is readable. It prevents a *confusing* screen, not an *unauthorized* read. Everything that actually protects data is in `backend/Architecture/architecture.md` (the application layer) and `backend/Architecture/database.md` (the Row-Level Security layer). **Register section B records that the database layer does not currently hold**, which makes it more important, not less, that nobody counts this file as a second line of defence.

### The StrictMode note

`:43-56` records a real bug and its fix. The obvious implementation — a `started` ref to make the effect idempotent — **deadlocked in development**. `reactStrictMode: true` (`next.config.mjs:136`) makes React mount, unmount and remount every component. The unmount set `cancelled`, discarding the in-flight response; the remount found `started.current` still `true` (refs survive the double-invoke) and returned early. The first request's result was thrown away, the second was never made, and neither `setMe` nor `setChecked` ever ran. Every dashboard sat on "Loading…" forever with a healthy 200 in the network tab — and only in development, so nothing in continuous integration could see it.

The fix is the empty dependency array plus a plain `let cancelled` closure variable (`:57`, `:83-85`), which is re-created per mount and therefore does not survive the double-invoke. `:86-97` explains why the array is empty rather than `[router]`: `router` is a fresh object each render, so keying on it would re-run the identity check continuously.

**The same pattern is reproduced, unfixed, in `VerifyEmail`.** See defect **D5**.

---

## Onboarding routing

`lib/auth/onboarding.ts` is the **one place** onboarding routing is decided.

### `onboarding_state` is the only input

`:3-11`:

> Routing is driven by `onboarding_state` from the identity endpoint and nothing else — never from `class_level`, never from a combination of booleans.

That is why a Class 11–12 student has **no code path** that can render the parental gate: the backend never sets the state for them, so the frontend has nothing to render it from. There is no `if (classLevel <= 10 && !guardianVerified)` anywhere in this application, and there must never be one — a client-side re-derivation of a server-side gate is a second source of truth that will drift.

`onboarding_state` is a five-value union on the client (`lib/api/types.ts:12-17`) and is derived server-side per request, never stored.

### State → route

`lib/auth/onboarding.ts:24-29` and `:13-18`:

| `onboarding_state` | Route | Source |
|---|---|---|
| `email_verification_pending` | `/onboarding/email` | `onboarding.ts:25` |
| `two_factor_enrollment_pending` | `/onboarding/2fa` | `onboarding.ts:26` |
| `guardian_link_pending` | `/onboarding/guardian` | `onboarding.ts:27` |
| `plan_selection_pending` | `/onboarding/plan` | `onboarding.ts:28` |
| `active` | `dashboardFor(role)` | `onboarding.ts:32` |

And `dashboardFor` (`:13-22`):

| Role | Dashboard |
|---|---|
| `student` | `/dashboard` |
| `teacher` | `/teacher` |
| `parent` | `/parent` |
| `admin` | `/admin` |

Three functions read that table:

- `routeForOnboardingState(state, role)` (`:31-33`) — for a caller that has both. `SessionGuard.tsx:73`.
- `pendingOnboardingRoute(state)` (`:43-45`) — returns `null` for `active`. Exists so a caller that has a state but **no role** — the two-factor challenge, whose response carries `onboarding_state` and nothing else (`lib/api/types.ts:119-124`) — can route without inventing one. `TwoFactorChallenge.tsx:175`, `TwoFactorEnrollment.tsx:136`, `VerifyEmail.tsx:61`.
- `isOnboardingComplete(state)` (`:54-56`) — a named predicate for `state === 'active'`.

### It is **not monotonic**

This is the rule that makes the guard different from the obvious implementation, recorded at `onboarding.ts:47-53` and again at `SessionGuard.tsx:21-29`:

> A student reaches `active`, uses the app for fourteen days, and then the trial lapses and the server puts them back into `plan_selection_pending`.

Onboarding is a **state**, not a **checklist**. A user moves *backwards* through it. Any consumer that caches `active` — a context set once on login, a `hasOnboarded` boolean in local storage, a guard written as "check once, then trust" — strands that user on a page they no longer have rights to, with every API call returning 403 `SUBSCRIPTION_REQUIRED` and no route out.

The defence is that the state is re-read on **every navigation** and never remembered across one (until classroom Phase 6c, on every mount — each page had its own guard). `SessionGuard.test.tsx:106-117` asserts exactly this: it renders the guard with an `active` student, flips the mock to `plan_selection_pending`, moves to another path, and asserts both the redirect and that `getMe` was called twice; `:119-132` asserts the page is the same node, not a "Loading…", while the re-check is in flight.

The transport client carries the same rule at a lower level: a 403 `SUBSCRIPTION_REQUIRED` on any request redirects to `/onboarding/plan` (`lib/api/client.ts:186-190`), so a trial that lapses *mid-session* is caught without waiting for a remount.

---

## `navigation.ts` is a Role-Based Access Control boundary

`lib/auth/navigation.ts`. Its header says so in the first sentence (`:3-31`):

> THIS FILE IS AN RBAC BOUNDARY, not a styling concern.

`NAV_BY_ROLE` (`:50-115`) is a `Record<Role, NavItem[]>`. `DashboardShell` builds every sidebar from it (`components/app/DashboardShell.tsx:41`, rendered at `:69-85`) and from nothing else. That single-source construction is the mechanism: an item cannot leak across roles by copy-paste, because there is no per-role markup to paste into.

Three decisions it encodes, each of which a shared component tree makes easy to get wrong:

**(a) The parent surface is read-only.** `:76-86` — dashboard, my child, classrooms (the read-only overview, classroom Phase 8), progress, how to help, settings, help. No tutor, no session replay, no planner write. The supplied mockups shipped **one student sidebar pasted into all three dashboards**, which handed parents a "Play Session" button that replays a child's AI tutor conversation. `GET /api/tutor/sessions/{id}` is student-owner-only and the requirements forbid a parent reading chat content — so that control was not a dead link, it was a privacy violation with a button on it.

**(b) The teacher surface has no tutor entry.** `:64-75`. The requirements once granted teachers tutor access "for own testing" while `POST /api/tutor/ask` has always been scoped to gate-verified students. The technical design document won.

**(c) The student surface must expose My Classes.** `:60`. Students are guaranteed the right to see who can view them and to leave any space at any time. No mockup had an entry for it, and a right with no route to it is not a right.

**Classroom Phase 2 (2026-10-04)** moved the four things the comment at `navigation.ts:40-45` says
move together: student `myClasses` → `/classroom`, teacher `mySpaces` → `/teacher/classroom`
(relabelled "My Classrooms"); the teacher's `roster` and `announcements` entries were **removed**,
not repointed — both now live inside a classroom; `my-classes`, `spaces`, `roster` and
`announcements` left the coming-soon `SLUGS`; and the route-prefix regex in `navigation.test.ts`
gained `classroom` — **after** it had failed naming `myClasses`, the order its own comment demands.
`Dashboards.tsx` card links were repointed in the same change (`/coming-soon/my-classes` would have
become a silent 404).

`lib/auth/navigation.test.ts` is described in its own header (`:8-18`) as *the highest-value regression test in the frontend*. `:19-42` asserts the parent navigation contains no href and no key matching `/tutor/`, `/session|replay|play/`, `/planner/`, `/practice/`, `/quiz/`, `/subject|curriculum/` or — since classroom Phase 8 — `/chat/`, and that it does reach the read-only `/parent/classroom`. `:44-54` asserts the teacher surface has no tutor entry. `:56-62` asserts the student surface has My Classes. `:80-94` asserts every key has a translated label in all three locales.

`ROLE_ACCENT` (`:118-123`) sits in the same file and *is* styling — one Tailwind text-colour class per role. It is the exception that proves the rule: it is here because it is keyed by `Role`, and keeping every role-keyed record together is what makes an incomplete role obvious.

---

## The API (Application Programming Interface) client

`lib/api/client.ts` is the single entry point for every call. `lib/api/endpoints.ts` wraps it in typed functions so no screen hand-writes a path or a shape. `lib/api/types.ts` is transcribed from the contract, so a response shape that drifts from it is a type error rather than an integration surprise.

### Live data always — the mock layer was deleted

`lib/api/client.ts` used to select a hand-rolled in-memory backend from `NEXT_PUBLIC_API_MODE`.
**Phase 1b deleted it entirely** — 841 lines across `lib/api/mock/{index,db,db.test}.ts`, plus the
branch, plus the flag from `.env.example`, `vitest.config.mts`, `render.yaml` and the CI workflow.

**The settings screen (Phase 7, FR-A8).** `app/[locale]/(app)/settings` is the client for all three account-management endpoints. Built from the Stitch prototype, which governs structure and copy while the API contract governs which fields exist. Four conflicts were decided by the owner: **board and class are read-only** (Phase 2 made both unwritable — finding B4 — and the prototype board list is wrong regardless, offering FBISE/Punjab/Sindh/Cambridge against an enum of PCTB and STBB, so labels come from `GET /reference/enums`); **Student ID is dropped** (no such field exists anywhere); **one language control sets both** the stored preference and the interface locale; **Appearance is dropped** (the application has zero `dark:` classes).

⚠️ **The language control does two unrelated things, and missing the second is the easy mistake.** The stored preference is an API write that governs outgoing email; the interface locale is a URL segment, so it is a route change. The write happens FIRST — navigating first would leave the user reading a page in a language the server does not think they chose. The value sets differ (`ur-Latn` on the web is `roman_ur` in the API) and are mapped through `toApiLanguage`. **This contradicted `prd.md` FR-A8, whose Edge clause said the two must be presented as distinct settings; the requirement was amended in the same change rather than the screen.**

⚠️ **Building the route moves four things together**, two of which are tests that exist to stop it moving alone: the nav href, the coming-soon `SLUGS` list, `navigation.test.ts`'s route-prefix regex, and its prerender-pairing test. The regex failure was observed naming `settings` before it was widened.

**A11 — the navigation handoff is deleted (Phase 5).** `setNavigationHandler` and
`handleOnboardingRedirect` let the client route a user to an onboarding step on a 403 without
importing the router. ⚠️ **The only caller of `setNavigationHandler` in the repository was
`client.test.ts`**, so `navigate` was permanently `null` and the redirect returned on its first
line every time. Four tests passed while describing behaviour the application did not have, which is
the more dangerous kind of green. `SessionGuard` re-evaluates `onboarding_state` on every navigation and
is what actually moves a gated or lapsed user; the suite went 289 -> 285.

What it was, recorded so nobody rebuilds it: an in-memory router serving 18 endpoints from eight
seeded accounts that all shared one password, plus magic strings — `verify-<user-id>` **minted a
session from a URL with no password**, `123456` passed any two-factor challenge, and `BKUP0000` was a
working backup code. It was the **default** whenever `NODE_ENV` was not `production`, and the
`'mock'` flag was tested *before* `NODE_ENV` — so setting it explicitly shipped those credentials out
of a production build. That is what defect **C4** was, and deleting the layer converts the guarantee
from a configuration invariant into a structural one: there is no mock to select.

#### The configuration hole it was hiding, now named instead of hidden

```ts
// lib/api/client.ts
const BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? ''
const SERVER_ORIGIN = process.env.BACKEND_INTERNAL_URL?.trim().replace(/\/+$/, '') ?? ''

function resolve(path: string): string {
  const onServer = typeof window === 'undefined'
  if (BASE_URL) {
    if (!onServer || isAbsolute(BASE_URL)) return `${BASE_URL}${path}`
    if (SERVER_ORIGIN) return `${SERVER_ORIGIN}${BASE_URL}${path}` // + validity check
    throw new Error('Cannot resolve a relative API base on the server: BACKEND_INTERNAL_URL…')
  }
  if (onServer) throw new Error('NEXT_PUBLIC_API_BASE_URL is not set…')
  return path
}
```

The mock default existed *because* an unset base URL produces a relative path Node cannot parse on
the server. **The empty string is still load-bearing in the browser**: relative `/api/...` goes
through the `next.config.mjs` rewrite, and that rewrite is what keeps the refresh cookie same-site.
Pointing `NEXT_PUBLIC_API_BASE_URL` at the backend's public address re-breaks it silently, in
production only.

> ⚠️ **A base that is SET but RELATIVE was the same hole, and the guard above did not cover it.**
> The check asked "is it set?", not "can Node use it?" — so production, where the value is `/api`
> **by design**, went straight past it. `app/[locale]/(site)/signup/student/page.tsx` is the only
> **server** component that calls the API (it fetches board and class options so the academic step
> has them on first paint), and there `fetch('/api/reference/enums')` threw
> `TypeError: Failed to parse URL`. The page catches its own enum load and degrades, so the real
> error surfaced **nowhere** — no log line, no console entry, no network request.
>
> It could not reproduce locally: development sets an **absolute** `http://localhost:8000/api`, so
> the failing branch never ran. In production the symptom was that **student** signup showed "Could
> not load the class and subject options" while **teacher and parent** signup worked perfectly —
> because neither of those fetches on the server. That asymmetry is the diagnostic.
>
> A relative base is now resolved against `BACKEND_INTERNAL_URL` **on the server only**; the browser
> path is untouched, and `resolveBaseUrl.test.ts` asserts that explicitly, because prefixing the
> browser's URL would reintroduce the cross-site cookie bug this rewrite exists to prevent.
>
> ⚠️ The origin is validated with `new URL()` **plus a hostname check**, not a `startsWith('https://')`
> test. `https://https://host` passes both a prefix test and the WHATWG parser — it yields hostname
> `"https"` rather than an error. That exact value was live on Render and 500'd every API call,
> because `next.config.mjs` validates the rewrite destination with the naive prefix test.

What this costs, stated plainly: a developer with a clean checkout and no backend running no longer
gets a working application. Pages that load data fail, and signup fails first, because
`(site)/signup/student/page.tsx` fetches reference data during server rendering.

### Proactive refresh at 80% of token lifetime

`apiFetch` refreshes **ahead of use** rather than waiting to be told (`:152-159`):

```ts
if (init.bearer === undefined && getAccessToken() !== null) {
  if (isExpired() || shouldRefreshAhead(lastLifetimeSeconds)) {
    await refreshOnce()
  }
}
```

`shouldRefreshAhead` (`lib/auth/tokenStore.ts:45-50`) reconstructs the issue time from the stored absolute expiry and the original `expires_in`, then compares elapsed time against `REFRESH_AT_FRACTION` — `0.8` (`tokenStore.ts:18`). `lastLifetimeSeconds` is remembered at `client.ts:28` and set by `rememberSession` at `:30-33`, because the store keeps only the absolute expiry.

The point is stated at `client.ts:153-154`: a long form must not be interrupted by a redirect the user did not cause. Waiting for a 401 means the interruption lands mid-typing.

### Single-flight refresh, and why rotation makes it necessary

```ts
// lib/api/client.ts:76-81
export function refreshOnce(): Promise<boolean> {
  refreshInFlight ??= performRefresh().finally(() => {
    refreshInFlight = null
  })
  return refreshInFlight
}
```

The module-level `refreshInFlight` (`:69`) means N concurrent 401s trigger **one** refresh, not N. Every caller awaits the same promise.

The reason is refresh-token **rotation**: each successful refresh invalidates the token it consumed and issues a new one. Without single-flight, a dashboard firing several requests at once sends a burst of refreshes; the first consumes the cookie, and every other one presents a token the server has already retired. On a backend that treats a retired token as theft, that burst is indistinguishable from an attack — it signs the user out mid-session and writes a false reuse-detection audit row. `client.test.ts:76-94` fires three concurrent requests that each 401 and asserts exactly one `/auth/refresh` call.

`performRefresh` (`:83-94`) deliberately bypasses `apiFetch` and calls `rawRequest` directly (`:85-87`): a refresh that itself 401s must not recurse back into the retry path. On failure it calls `endSession()` and returns `false`.

**A caveat worth recording:** this guard is per browser tab. Two tabs of the same application hold two independent module states and can still race a rotating refresh (register **D2**).

### The retry allow-list

Not every 401 is worth retrying. `lib/api/errors.ts:90-102`:

```ts
const REFRESHABLE_401_CODES = new Set<string>(['UNAUTHENTICATED', 'UNKNOWN'])

export function isRefreshableAuthError(error: ApiError): boolean {
  return error.status === 401 && REFRESHABLE_401_CODES.has(error.code)
}
```

An **allow-list**, not a status check. `TWO_FACTOR_INVALID` and `PENDING_TOKEN_EXPIRED` are also 401s, but they mean the submitted code was wrong or its challenge died. Refreshing and retrying those would resubmit a bad code and burn one of the user's lockout attempts. `UNKNOWN` is included because `toApiError` (`:79-88`) assigns it when a proxy, gateway or crash returns HTML or an empty body — a transport failure that a fresh token may well fix.

The retry itself is at `client.ts:168-170`, guarded three ways: not a challenge credential (`init.bearer === undefined`), not opted out (`!init.noRetry`), and on the allow-list. It runs **once** — `rawRequest` is called directly, not `apiFetch`, so there is no loop. `client.test.ts:96-105` asserts the original path is hit exactly twice and then gives up.

`noRetry` is documented at `client.ts:105-113` and used at **four** call sites: `login`,
`adminLogin`, `changePassword` and `twoFactorConfirm`.

⚠️ **The `init.bearer === undefined` guard beside it protects nothing, and this was corrected in
Phase 5.** No wrapper in `endpoints.ts` passes `bearer` — every 2FA credential travels in the body
by design (tdd.md §3.1) — so that condition is always true. `noRetry` is the only thing that opts a
route out of refresh-and-retry.

⚠️ **`twoFactorConfirm` was added for finding D9, but NOT for the reason the register gave.** The
register said a wrong CODE triggers a retry and burns a lockout attempt. Measured: a wrong code is
`401 TWO_FACTOR_INVALID`, and `REFRESHABLE_401_CODES` is `{UNAUTHENTICATED, UNKNOWN}` — so the one
path that increments `failed_attempts` was never retried. The retryable case is
`401 UNAUTHENTICATED` ("enrolment not found or already active"), and retrying it refreshes a session
that does not exist yet, because enrolment precedes any refresh cookie. One wasted round trip, not a
burned attempt. On `/auth/login` a 401 means the password was wrong, so refreshing would fire a guaranteed-to-fail request on every typo.

⚠️ **`changePassword` is the subtle one, added in Phase 3.** `POST /auth/password/change` returns `401 UNAUTHENTICATED` for a wrong *current* password — the contract forbids a bespoke code — and `UNAUTHENTICATED` is necessarily on `REFRESHABLE_401_CODES`, because it normally means an expired token. It is therefore the **only** route where both meanings of that 401 are live at once. The `init.bearer === undefined` guard does **not** shield it: unlike `/2fa/confirm`, its credential travels in the body, not as `bearer`. Without `noRetry` every mistyped password would silently fire a token refresh and replay the request.

### File transfer — raw bodies and blobs (classroom Phase 6)

Two options on `ApiRequestInit` (`client.ts:195`), used only by the file wrappers in
`endpoints.ts:518-583`:

- **`rawBody`** (`:203`) sends a `Blob` — a `File` — **as-is**: no JSON encoding and no JSON
  `Content-Type`; the caller sets the type (`:226-242`). Uploads are never multipart, because the
  backend counts the raw body against `Content-Length`. The file name travels in an
  `X-Upload-Filename` header, URL-encoded. A `Blob` can be sent twice, so refresh-and-retry
  stays safe; a one-shot stream could not be.
- **`responseType: 'blob'`** (`:208`) returns a **successful** body as a `Blob` (`:246`). An
  error is still parsed as the JSON envelope, so a refused download is an ordinary `ApiError`. The
  download goes through `fetch` with the access token in the header — never a URL carrying a
  credential — and `saveBlob` (`lib/download.ts`) hands it to the browser as a saved file.

`client.test.ts` pins all four behaviours: the raw body sent untouched with no JSON type, a blob
returned on success, a JSON error still thrown as `ApiError`, and a refresh-and-retry that resends
the same file.

### Transport-level onboarding redirects

`GATE_PENDING` and `SUBSCRIPTION_REQUIRED` are both 403s that mean "authenticated, but an onboarding precondition is unmet". Neither is an error to show; both are a signal to move the user. `client.ts:182-198`:

| Error code | Redirect target |
|---|---|
| `GATE_PENDING` | `/onboarding/guardian` |
| `SUBSCRIPTION_REQUIRED` | `/onboarding/plan` |
| any other 403 | none — left to the screen to render |

`:193-195` suppresses the redirect when `currentPath()` already ends with the target, because the gate page itself calls guardian endpoints and would otherwise loop.

The client must not import the router — that would make it untestable outside React and couple the transport to the framework — so a handler is **registered** instead (`:40-56`):

```ts
export function setNavigationHandler(fn: NavigateFn, pathReader: () => string): void
```

> **Verified, and worth knowing: `setNavigationHandler` is called from no application code.** The only call sites are `lib/api/client.test.ts:138`, `:148`, `:159` and `:169`. A repository-wide search outside `node_modules` and `.next` finds no provider that registers it. `navigate` is therefore `null` at runtime, and `handleOnboardingRedirect` returns at its first line (`:183`) on every real request. The mechanism is built and tested but not wired; the redirects it describes do not currently fire in the running application. `SessionGuard` still catches the same conditions on the next mount, so the user is not stranded — the loss is that a mid-session lapse is not caught until a navigation.

---

## Credential storage

Three kinds of credential, three storage rules, all of them narrower than the obvious choice.

| Credential | Where it lives | Survives a reload? |
|---|---|---|
| Access token | Module variable, `lib/auth/tokenStore.ts:14` | **No** |
| Refresh token | `httpOnly` cookie set by the server | **Yes**, but JavaScript can never read it |
| `pending_token` (two-factor challenge) | Module variable, `lib/auth/challenge.ts:34` | **No** |
| `enrollment_token` (two-factor enrolment) | Module variable, `lib/auth/challenge.ts:35` | **No** |
| Unverified email address | Module variable, `lib/auth/challenge.ts:43` | **No** |

### The access token

`lib/auth/tokenStore.ts:1-12`:

> The access token lives in a module-level variable and nowhere else. Never localStorage, sessionStorage, a readable cookie, or a URL: any of those survive the tab and are readable by injected script.

`accessToken` and `expiresAtMs` are two `let` bindings at `:14-15`. There is no persistence layer under them. The repository contains no `localStorage`, no `sessionStorage` and no `document.cookie` anywhere in application code — that was verified in the Epic 1 sweep and recorded in the register's *verified correct* list.

The refresh token is an `httpOnly` cookie the server sets. JavaScript cannot read it at all, which is the property that makes it safe to persist when the access token is not.

The consequence is stated at `tokenStore.ts:9-11`: **a full page reload loses the access token**, and the application recovers by calling `/auth/refresh` with the cookie. That is the intended trade-off, not a bug — and it is why `rawRequest` sends `credentials: 'include'` (`client.ts:230`) on every call.

`startSession` (`endpoints.ts:291-293`) is the one place a token enters the application, so no screen has to remember that `expires_in` drives proactive refresh.

### The challenge tokens, and the deliberate reload consequence

`lib/auth/challenge.ts:3-17`:

> `pending_token` and `enrollment_token` are bearer credentials: presenting one completes an authentication step. So they follow exactly the same storage rule as the access token — a module variable and nowhere else.

And the consequence, spelled out as design rather than defect:

> a hard reload on `/login/2fa` loses the challenge, and the screen sends the user back to `/login` to sign in again. A token that survived a reload would also survive the user walking away from a shared device.

Shared devices are the operative case here. This is a product used on family phones and school computers; a challenge credential that outlives the tab outlives the user's attention. `/login/2fa` records the same thing from the page side (`(auth)/login/2fa/page.tsx:13-18`): opening it directly renders nothing and returns to sign-in, because the token cannot be recovered from a URL or from storage **by design**.

`unverifiedEmail` (`:37-43`) is kept for a subtler reason: `status: 'email_verification_required'` returns a **masked** address, and a masked address cannot be submitted to `/auth/email/resend`. The unmasked address the user typed is the only usable value.

`clearAllChallenges()` (`:77-82`) is called once a session exists, so a spent challenge cannot be replayed — `TwoFactorChallenge.tsx:173`, immediately after `startSession` at `:172`. The order is deliberate (`:169-171`): the session is stored before the spent challenge is dropped, so a failure between the two cannot leave the user holding neither credential.

Challenge credentials travel as `init.bearer` (`client.ts:103-104`, `:127`), which is what excludes them from proactive refresh (`:155`) and from refresh-and-retry (`:168`). Refreshing cannot help a challenge token, and retrying would waste an attempt. `client.test.ts:126-132` asserts a `bearer` request never triggers a refresh.

---

## Internationalisation

### Three locales

`i18n/routing.ts:16-37` defines `['en', 'ur', 'ur-Latn']` with `en` as default. Messages live in `messages/en.json`, `messages/ur.json`, `messages/ur-Latn.json` — **787 leaf keys each, identical across all three**, and in the same order (re-measured 2026-10-05) — phase 1 added `downloadFailed` (A7); phase 1b added 27 administrator keys and the 3 two-factor resend keys that were referenced by live code and existed nowhere (D18); classroom Phases 2–7 added the `classroom` namespace and the dashboard card's keys (562, then 590, 682, 696, 719, 734, 739, 770 and 787).

`localeDetection: false` (`:36`). Left on, next-intl negotiates from `Accept-Language` and a `NEXT_LOCALE` cookie, so a browser configured for Urdu — entirely normal in this audience — would be redirected to `/ur` before the visitor had chosen anything. Turning detection off makes `/` resolve to `/en` for everyone and makes language an explicit choice. The trade-off, accepted deliberately at `:31-34`: this also disables the cookie, so a returning visitor who previously chose Urdu lands on `/` in English again. They stay in Urdu while navigating, because every link carries the locale prefix.

`i18n/navigation.ts:9` exports locale-aware `Link`, `redirect`, `usePathname`, `useRouter` and `getPathname`. **Always import from there**, never from `next/link` or `next/navigation`, or the locale prefix is dropped and the user silently falls back to English mid-journey (`:4-8`). `proxy.ts:4` mounts the next-intl middleware; `:6-9` excludes `/api`, Next internals and any path with a file extension.

`components/layout/LanguageSwitcher.tsx:18-51` is a segmented control of **real links**, not a JavaScript dropdown — so switching works without JavaScript, costs one tap rather than two, and survives a slow connection. `:20` calls the locale-aware `usePathname`, which returns the path *without* the prefix, and `:31` feeds it straight back as the `href`, so the same page is preserved across a switch. `:36` sets `lang="ur"` on the Urdu option so the endonym renders in the Naskh face even inside an English page.

### Right-to-left for Urdu only

`i18n/routing.ts:64-80`:

```ts
const RTL_LOCALES = new Set<string>(['ur'])
export function isRtl(locale: string): boolean { return RTL_LOCALES.has(locale) }
export function dirFor(locale: string): 'rtl' | 'ltr' { return isRtl(locale) ? 'rtl' : 'ltr' }
```

**Roman Urdu is Urdu written in Latin script, so it reads left-to-right.** Mirroring it would be a defect, not a feature. This is the single place that decision is encoded; nothing else may test the locale string to work out direction. `app/[locale]/layout.tsx:51` is the only consumer that matters — `<html lang={locale} dir={dirFor(locale)}>`.

`app/fonts.ts:36-38` reads the same predicate: the Urdu Naskh face is loaded with `preload: false` (`:30`) and applied only for right-to-left locales, so an English or Roman-Urdu visitor never downloads a large Arabic-script font they cannot read.

### The logical-property lint rule

`lib/i18n-rules.test.ts` is a **test that behaves like a lint rule**. Its header (`:5-16`):

> A single `ml-2` looks fine in English and silently breaks the Urdu layout, which nobody notices until someone reads the page in Urdu. The prototypes are entirely physical (`pl-10`, `left-0`, `text-left`), so this catches a class copied straight across.

It walks `app/` and `components/` (`:18`, `:24-32`), skipping test files, and fails any non-test `.ts`/`.tsx` file whose `className` lines match:

```
// lib/i18n-rules.test.ts:21-22
/(?:^|[\s"'`:[])(?:-)?(?:ml|mr|pl|pr|left|right|border-l|border-r|rounded-l|rounded-r)(?:-[a-z0-9./[\]%-]+)?(?=[\s"'`\]]|$)|text-(?:left|right)/
```

`:43-45` restricts the check to lines containing `className` or `class=`, so prose in a comment may still say "left". `:39` runs it as one test case per file, so a failure names the offending file and line rather than a single opaque assertion. `:35-37` guards against the walker silently finding nothing.

The permitted replacements are the logical properties: `ms`/`me`, `ps`/`pe`, `start`/`end`, `text-start`/`text-end`, `border-s`/`border-e`. A new screen is correct in Urdu by construction rather than by review. Real usage: `DashboardShell.tsx:92` (`text-start`), `:105` (`border-e`), `:118` (`end-4`).

Where mirroring is genuinely wrong, it is opted out explicitly. `BackupCodes.tsx:63-67` marks the code grid `force-ltr` because backup codes are Latin-alphanumeric strings that must not reorder inside an Urdu page. `error.tsx:64` does the same for the digest.

### Web locale → API enum

The two vocabularies are **deliberately different** (`i18n/routing.ts:3-15`):

| Web locale | API / database `language_code` |
|---|---|
| `en` | `en` |
| `ur` | `ur` |
| `ur-Latn` | **`roman_ur`** |

The database enum and the API contract use `roman_ur`. That is a fine internal identifier but **not a valid BCP-47 language tag**: `Intl.NumberFormat('roman_ur')` throws `RangeError`, and `<html lang="roman_ur">` is invalid, so a screen reader cannot tell what language the page is in. The web layer therefore uses `ur-Latn` — the correct tag for Urdu in Latin script — and maps at the API boundary.

Both directions live in one file: `LOCALE_TO_API` (`:44-48`) and `API_TO_LOCALE` (`:50-54`), exposed as `toApiLanguage` (`:56-58`) and `fromApiLanguage` (`:60-62`). `lib/api/types.ts:23-24` re-declares `ApiLanguage` with a comment pointing back here.

`LOCALE_LABELS` (`:83-87`) names each language in its own script — `English`, `اردو`, `Roman Urdu` — never translated.

---

## The Content Security Policy deviation

`next.config.mjs:59-97` sets four security headers on every path (`:147-149`). One directive deviates from the obvious hardening, deliberately:

```
// next.config.mjs:81
script-src 'self' 'unsafe-inline' https://challenges.cloudflare.com   [+ 'unsafe-eval' in dev]
```

### Why `'unsafe-inline'` stays

`next.config.mjs:3-30` records it in full. Summarised:

- The App Router **streams its React payload through inline `<script>` elements**. Under a bare `script-src 'self'` every one of them is blocked, React never hydrates, and the entire site ships as dead HTML — no form accepts input, no button responds.
- **It fails silently.** Every asset returns 200 and the console stays empty. That is why it survived five phases unnoticed.
- **Verified both ways on a clean production build.** The tightened value was applied, built and opened; the application was inert. The current value was applied, built and opened; it works.

The correct fix is a **per-request nonce**, and it cannot be used here. A nonce must differ per response, so the page must be rendered per request — but these routes are prerendered per locale at build time (`app/[locale]/layout.tsx:17-19`, `:41`). Forcing them dynamic would trade the static prerendering the accessibility and performance requirements depend on — a fast first paint on a mid-tier Android over Slow 3G — for a directive that stops a subset of cross-site scripting payloads. Revisit if the auth routes ever become dynamic for another reason.

`'unsafe-eval'` is **development only** (`:66-72`): React uses `eval()` in development to reconstruct call stacks across the server/client boundary, and without it the error overlay reports the policy violation instead of the actual bug. React never uses `eval()` in a production build, so shipping the directive would weaken `script-src` for a feature that is not there. The `isDev` switch reads `NODE_ENV` (`:31`), which `next build` sets.

### What still holds

The directives that matter most for an authentication surface are all intact:

| Directive | Value | What it buys |
|---|---|---|
| `default-src` | `'self'` | everything not named below |
| `style-src` | `'self' 'unsafe-inline'` | Tailwind's runtime styles |
| `font-src` | `'self'` | self-hosted via `next/font`; no `fonts.googleapis.com` |
| `img-src` | `'self' data:` | the `data:` URI is the server-supplied two-factor QR code |
| `connect-src` | `'self'` + Turnstile + the API origin + `ws:`/`wss:` in dev | confines API calls |
| `frame-src` | `https://challenges.cloudflare.com` | what **we** may frame — the Turnstile widget |
| `frame-ancestors` | `'none'` | blocks clickjacking of the login and two-factor screens |
| `base-uri` | `'self'` | stops a `<base>` tag rewriting every relative URL |
| `form-action` | `'self'` | stops a form being pointed at another origin |

Plus `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff` and `Referrer-Policy: strict-origin-when-cross-origin` (`:60-62`), and `poweredByHeader: false` (`next.config.mjs:137`).

`connect-src` is computed rather than hard-coded (`:33-57`). `'self'` alone is wrong the moment the backend is a separate origin, which it is in development — the app is served from `:3000` and calls `:8000`, so **every** fetch is blocked before it leaves the browser, and the symptom is a login screen that appears to do nothing. `apiOrigin` is derived from the same `NEXT_PUBLIC_API_BASE_URL` the client reads, so the two cannot disagree, and `:50-53` emits nothing unless the value parses to a real `http(s)` origin — an opaque origin would put a literal `null` into the directive, which allows nothing and reads like a bug.

Cloudflare Turnstile needs three directives, not one (`:73-80`): `script-src` for the challenge script, `frame-src` for the Cloudflare-served iframe, and `connect-src` because the widget's orchestration code fetches from that origin. No other third-party origin is allowed anywhere in the policy.

---

## The `/api` rewrite

`next.config.mjs:138-146` proxies `/api/:path*` to `${BACKEND_INTERNAL_URL}/api/:path*`. It looks like a convenience. It is the thing that keeps sessions alive in production.

### Why it exists

`next.config.mjs:99-124` records the reasoning:

The refresh token is an `httpOnly` cookie set `SameSite=Lax`. **Lax cookies are not sent on cross-*site* requests, and a platform subdomain is its own site.** `*.onrender.com` and `*.vercel.app` are both on the **Public Suffix List**, which means the browser treats `edubridge-web.onrender.com` and `edubridge-api.onrender.com` as two different sites, not two hosts of one site. Deployed as sibling subdomains, the frontend and backend are cross-site to the browser.

The failure mode that produces is the nastiest kind: **login succeeds**, the dashboard loads, and then `/api/auth/refresh` silently stops receiving the cookie. The user is signed out the moment the access token expires — roughly fifteen minutes in — **in production only**. Nothing in development reproduces it, because `localhost:3000` and `localhost:8000` are the same site.

Rewriting `/api/*` through the Next server makes the API **same-origin**. The Lax cookie keeps working with no backend change, `connect-src 'self'` already covers the calls, and there is no credentialed Cross-Origin Resource Sharing to configure. The cookie's `path=/api/auth/refresh` is unchanged by the rewrite, so it still matches.

### The trap

**Pointing `NEXT_PUBLIC_API_BASE_URL` at the backend's public address silently breaks refresh in production, and only in production.**

`lib/api/client.ts:25` reads that variable as the fetch prefix. Set it to `/api` and every call goes through the same-origin rewrite. Set it to `https://edubridge-api.onrender.com/api` — which looks more correct, is what the deployment dashboard invites, and works perfectly in every manual test that finishes inside one token lifetime — and every call is cross-site. Login still works. The dashboard still loads. Fifteen minutes later the user is signed out, and the reproduction requires waiting.

There are two variables and they are not interchangeable:

| Variable | Read by | Exposed to browser | Should be |
|---|---|---|---|
| `NEXT_PUBLIC_API_BASE_URL` | `lib/api/client.ts:25`, `next.config.mjs:46` | **Yes** | `/api` in any deployed environment |
| `BACKEND_INTERNAL_URL` | `next.config.mjs:132` | No | the backend's address, server-side only |

`:125-131` records a second failure this already caused: the value is pasted into a hosting dashboard by hand and a stray tab or newline rides along more often than not. Untrimmed, Next rejects the rewrite at **build** time with "`destination` does not start with `/`, `http://`, or `https://`" — accurate, but it reads like the URL is wrong when the URL is fine and the whitespace is invisible. Hence `.trim()` at `:132`.

Left unset, `:139` emits no rewrite at all.

Locally the rewrite exists in a dev build too, and is harmless either way: with the template's default `NEXT_PUBLIC_API_BASE_URL=http://localhost:8000/api` the client calls `:8000` directly and never uses it, and both origins are `localhost` — same site — so Lax is satisfied regardless. Point the base URL at `/api` locally and the rewrite carries the calls instead, matching production.

---

## Testing

41 test files, run with `npm test` (Vitest). `npm run build` includes the TypeScript check.

The classroom tests that wait on `SessionGuard` (`ClassroomView.test.tsx`, `Classrooms.test.tsx`)
give their **first** wait an explicit 5 s timeout (`LOADED`): Testing Library's 1 s default measured
machine load inside the full suite rather than the code — the same class of false failure
`vitest.config.mts` records raising `testTimeout` for. The ones that render dates
(`ClassroomView.test.tsx`, `StreamTab.test.tsx`) pass `timeZone="Asia/Karachi"` as
`PlanSelection.test.tsx` does, because **the app configures no global next-intl time zone**
(pre-existing; dates render in the browser's zone, which is correct for client-only rendering, but a
server-rendered date would mismatch). `StreamTab.test.tsx` also renders in `ur` and `ur-Latn` with an
`onError` that fails on any missing key, and `components/ui/Tabs.test.tsx` pins the reversed arrows
under `dir="rtl"`. The Phase 4 files (`ClassworkTab.test.tsx`, `SubmissionPanel.test.tsx`,
`GradingTable.test.tsx`) use the same `LOADED` first wait and fixed time zone, and each ends with the
`ur` / `ur-Latn` `onError` sweep.

The suite is not uniform — three files do something other than test a component:

| File | What it is |
|---|---|
| `lib/i18n-rules.test.ts` | A lint rule: fails on any physical Tailwind class in `app/` or `components/` |
| `lib/auth/navigation.test.ts` | The Role-Based Access Control regression net described above |
| `tailwind.config.test.ts` | Asserts the design tokens in the configuration match the design document |

The rest cover the transport client (`lib/api/client.test.ts`), the error envelope (`lib/api/errors.test.ts`), the middleware that routes every page (`proxy.test.ts`), the token and challenge stores (`lib/auth/tokenStore.test.ts`, `lib/auth/challenge.test.ts`), onboarding routing (`lib/auth/onboarding.test.ts`), locale routing (`i18n/routing.test.ts`), the guard (`components/app/SessionGuard.test.tsx`) and eight auth, signup, landing and layout components.

---

## Known defects

Recorded here rather than hidden until fixed, per the Phase 0 honesty rules. Numbering follows the 35-finding register in the Phase 0 plan.

### A6 — FIXED, phase 1b (2026-08-16)

`lib/auth/onboarding.ts:17` mapped `admin` to `/admin` and `lib/auth/navigation.ts` gave the admin
sidebar one entry pointing there, but `app/[locale]/(app)/` contained only `dashboard/`, `teacher/`
and `parent/`. Three call sites could send an administrator to that route — what is now `SessionGuard.tsx:73`
(`routeForOnboardingState(state, 'admin')` when the state is `active`), what is now
`SessionGuard.tsx:146` in `RequireRole` (`dashboardFor('admin')` on a role mismatch) and `TwoFactorChallenge.tsx:183` after a completed
challenge — and the result was a loop: the guard redirected, the route 404'd through the `(site)`
catch-all, and the guard's own fallback rendered "Redirecting…" for ever.

**`app/[locale]/(app)/admin/page.tsx` and `AdminDashboard` now exist.** The page is a shell, exactly
like the other three: no `/api/admin/*` endpoint is implemented, so its five cards name the five
FR-K1 duties — provisioning, curriculum currency, security posture, quotas, daily endpoint access
logs — and say plainly that each is not available yet.

**Why the test could not have caught it, and what changed.** `lib/auth/navigation.test.ts` had two
tests covering the nav table and neither covered the admin row: the *sends each role to its own
dashboard first* test omitted `admin` altogether, while *routes every non-dashboard item somewhere
that exists* allow-listed `admin` inside its regex alternation. The test written to catch this class
of regression had the regression written into it. Phase 1 added the missing first-item assertion.
Phase 1b added a third test that resolves every `coming-soon` href against the page's own
`generateStaticParams`, because a prefix regex accepts `/coming-soon/anything` and two of the four
new admin entries needed slugs that did not exist yet.

### The unlisted administrator login

Administrators do **not** sign in at `/login`. `POST /api/auth/login` refuses them, and
`POST /api/auth/admin/login` refuses everyone else — both with a 401 whose body is identical to a
wrong password, so neither endpoint can be used to work out which addresses are administrators
(prd.md FR-A2a).

`proxy.ts` is what makes the page unlisted. It was four lines wrapping next-intl; it now composes
three handlers, in order:

1. `pathname === '/' + process.env.ADMIN_LOGIN_PATH` → **rewrite** to `/en/admin-login`. A rewrite,
   not a redirect, so the address bar keeps the unlisted path and no locale prefix appears in it.
2. any path whose last segment is `admin-login` → **404**, so the ordinary route is not a second,
   listed door.
3. everything else → the existing next-intl middleware, untouched.

`ADMIN_LOGIN_PATH` carries **no `NEXT_PUBLIC_` prefix**, deliberately: that prefix would inline the
value into the browser bundle and publish it to every visitor. Measured on a production build, the
server chunk keeps the literal `process.env.ADMIN_LOGIN_PATH` read rather than folding it to a
constant, and the value appears **nowhere** under `.next/` — so it is read at runtime and never
enters a build artefact, client or server. Unset, the guard is `'' !== ''` and no rewrite happens:
the administrator login is simply unreachable, which is the correct failure.

> ⚠️ **The unlisted path is not an access control.** It keeps the entrance off the public site and
> nothing more. The endpoint's role check is the lock, and it holds whether or not the path is known.
> `proxy.test.ts` covers all three branches, including that ordinary locale routing is unchanged —
> that is the assertion worth having, because a middleware that stops calling next-intl takes down
> all 21 pages at once.

The page lives in the `(auth)` group rather than `(site)` because that group renders no top nav and
no footer: an operations door must not carry the marketing chrome. `AdminLoginForm` is a separate
component from `LoginForm` so the choice of endpoint is fixed at the route rather than behind a
prop a refactor could thread in from a URL; the challenge handoffs, the error mapping and the
captcha reset are imported, not copied. It deliberately offers no "create an account" link
(administrators are provisioned by SQL) and no "forgot password" link (that flow is public and
address-keyed, so linking it would confirm the address reaches a real reset e-mail).

### A7 — the backup-code download can silently produce no file

`components/auth/BackupCodes.tsx:41-51`:

```ts
const url = URL.createObjectURL(blob)
const link = document.createElement('a')
link.href = url
link.download = 'edubridge-backup-codes.txt'
link.click()                 // :49
URL.revokeObjectURL(url)     // :50 — synchronous, immediately after
```

Two problems in four lines. The anchor is **never appended to the document**, which several browsers require before a synthetic click on a download link does anything. And `URL.revokeObjectURL` is called **synchronously** on the next statement, which can invalidate the blob URL before the browser has started reading it.

The stakes are set by the component's own header (`:7-20`): the ten backup codes are shown **exactly once**. A user who clicks Download, sees nothing happen, and continues past the acknowledgement checkbox has lost their only recovery credential. The copy path (`:32-39`) reports its own failure through the `copied === 'failed'` banner at `:95-99`; the download path reports nothing, because a `click()` that does nothing throws nothing.

### A8 — sign-out no-ops on a network failure

`components/app/DashboardShell.tsx:45-48`:

```ts
async function signOut() {
  await logout()
  router.replace('/login')
}
```

No `try`/`catch`. `logout()` (`lib/api/endpoints.ts:295-304`) uses `try`/`finally`, not `try`/`catch` — the local session is dropped in the `finally` at `:302`, but the error still propagates. So on a network failure or a 500: `endSession()` runs, the access token is cleared, `await logout()` rejects, and `router.replace('/login')` at `:47` **never executes**.

The user is left looking at a dashboard that appears signed in, with no token behind it. Every subsequent request 401s. It looks like the sign-out button is broken, and it is — on the shared devices this product is used on, "sign out appeared to do nothing" is the worst possible failure for that button.

### C4 — CLOSED PERMANENTLY (phase 1b)

`.env.example` documented `NEXT_PUBLIC_API_MODE=mock` as the default, three lines below an
instruction to `cp .env.example .env.local`. Phase 1 flipped the value to `live`; **phase 1b then
deleted the entire mock layer along with the flag**, which is why this is closed rather than fixed.

The hazard was never the default on its own. It was that `API_MODE === 'mock'` was checked **before**
`NODE_ENV`, so the value copied forward into a deployment's environment would ship the in-memory
mock — seeded accounts and all — as the production backend, with nothing in the build warning,
because an explicitly set flag was exactly the condition the client treated as intentional.

`NEXT_PUBLIC_API_BASE_URL` is required in its place. See *Live data always* above.

### D18 — `login` never sends the email code (found 2026-08-16, deferred to Phase 5)

`_issue_and_send_email_otp` (`service.py:593`) has exactly two callers —
`two_factor_enroll` (`:823`) and `two_factor_resend` (`:1136`). **Neither `login` nor
`admin_login` is one of them.** So an account enrolled in `email_otp` reaches this screen with no
code sent, while `methodEmailBody` tells it *"Use the 6-digit code sent to {email}"*.

Measured against a running backend: `POST /auth/admin/login` returned `two_factor_required` with
`method: "email_otp"` and the mail log stayed empty until `/auth/2fa/resend` was called explicitly.

**Fixed in phase 1b, partially.** The control that sends the code called `t('resend')`,
`t('resending')` and `t('resent')`, and **none of the three existed in any locale** — the button
rendered the literal string `auth.twoFactor.resend`. The keys are now present in all three, and
`TwoFactorChallenge.test.tsx` gained the `onError` sweep that would have caught it. Two things had
to be true for it to survive: next-intl reports a missing key through `onError` rather than
throwing, so the render "succeeds"; and the control only appears while `type === 'email_otp'`, a
branch no test reached.

**Still open:** the auto-send itself. It is deferred rather than fixed here because it makes
`login` dispatch mail, which is the same path as **D1** (emails dispatched before the transaction
commits) and needs a decision on whether it shares `two_factor_resend`'s per-account limit of 3 per
5 minutes. Until it lands, `methodEmailBody` is inaccurate for a fresh challenge — recorded here
rather than reworded, so the copy and the code are fixed together.

⚠️ **This is the administrator's normal path, not an edge case.** A seeded administrator must use
`email_otp`: `totp` requires `totp_secret_encrypted`, AES ciphertext under the application key,
which cannot be produced in SQL.

### D5 — `VerifyEmail` reproduces the StrictMode deadlock `SessionGuard` documents fixing

`components/auth/VerifyEmail.tsx:41-73` uses precisely the pattern `SessionGuard.tsx:51-64` records as having deadlocked:

```ts
const attempted = useRef(false)                              // :41

useEffect(() => {
  if (token === null || attempted.current) return            // :44
  attempted.current = true                                   // :45

  let cancelled = false                                      // :47
  void (async () => {
    const result = await verifyEmail({ token })
    if (cancelled) return                                    // :51
    ...
  })()

  return () => { cancelled = true }                          // :70-72
}, [token])
```

A ref guard that survives React's development double-invoke, combined with a `cancelled` flag that discards the first response. React mounts, unmounts and remounts (`next.config.mjs:136`); the unmount sets `cancelled`, so the in-flight verification's result is thrown away at `:51`; the remount finds `attempted.current === true` and returns at `:44`, so no second request is made. `setState` is never called again and the screen stays on the `verifying` spinner (`:93-114`) permanently.

Development only, exactly like the original — which is what makes it costly. The `:29-31` comment explains the ref as a guard against a mail client prefetching the link and the human then clicking it. That is a real concern, but the token is single-use server-side, so the guard is defending against a duplicate request the server already rejects, at the price of a development-only deadlock.

### D6 — an unvalidated `onboarding_state` reaches `router.replace(undefined)`

`onboarding_state` is typed as a five-value union (`lib/api/types.ts:12-17`), but it arrives from the network and nothing validates it against that union at the boundary. Both lookup tables are plain `Record`s, so an unrecognised value returns `undefined`:

- `lib/auth/onboarding.ts:32` — `ONBOARDING_ROUTES[state]` → `undefined` → `SessionGuard.tsx:73` calls `router.replace(undefined)`
- `lib/auth/onboarding.ts:44` — `pendingOnboardingRoute` returns `undefined`, and the guard at `TwoFactorChallenge.tsx:176` is `if (next !== null)`. `undefined !== null` is **true**, so `:177` calls `router.replace(undefined)`.

Two of the three `pendingOnboardingRoute` call sites are accidentally safe — `VerifyEmail.tsx:61` and `TwoFactorEnrollment.tsx:136` both use `?? '/dashboard'`, and nullish coalescing catches `undefined` as well as `null`. `TwoFactorChallenge.tsx:176` uses an explicit `!== null` and is not.

The trigger is a backend that adds a sixth onboarding state, or renames one. Today the two sides agree; the register also notes that `onboarding_state` is a `Literal` on `MeResponse` and a plain string on four other backend responses (register **D13**), which is the drift channel.

### The sidebar marked the first item as the current page, everywhere — FIXED, classroom Phase 6c (2026-10-05)

`DashboardShell.tsx` set `aria-current="page"` and the highlight on `index === 0` rather than on
the route being shown, so "Dashboard" was announced and drawn as current on every page — Settings
and the classroom pages included; the owner reported it from a classroom. Recorded on 2026-10-04 and
fixed on its own, as recorded then: `currentItem` (`DashboardShell.tsx:19`) picks the item whose href is
the **longest prefix** of `usePathname()`, so `/teacher/classroom/<id>` is My classrooms and not the
Dashboard at `/teacher`, and a path no item owns marks nothing. `DashboardShell.test.tsx` pins five
paths, the teacher's prefix case and the no-match case. Because the shell no longer remounts on a
navigation, the phone menu's "open" is derived from the page it was opened on, so following a link
closes it — also pinned.

### D17 — `error.tsx` logs the error object it refuses to render

`app/[locale]/error.tsx:16-18` states the security rule:

> The error is deliberately NOT shown. A stack or a message from a failed request can carry an email address, a token fragment or an internal path, and this page is reachable by anyone.

Then `:29-31`:

```ts
useEffect(() => {
  console.error(error)
}, [error])
```

The whole error object — message, stack and any attached properties — goes to the browser console. The console is not a private channel: it is readable by any extension with page access, captured by client-side error-reporting integrations, and visible to anyone who opens developer tools, including on a shared device. The page correctly renders only `error.digest` (`:63-67`), which is exactly the opaque, safe identifier that ought to be the *only* thing that leaves.

---

## Where the rest of the system is documented

This application makes no authorization decisions and holds no data. For anything below the transport layer:

- **[`../../backend/Architecture/architecture.md`](../../backend/Architecture/architecture.md)** — the layered request path, the two-layer authorization model and its current failure, the token kinds, the onboarding state machine as the server computes it, and the guardian gate.
- **[`../../backend/Architecture/database.md`](../../backend/Architecture/database.md)** — tables by domain, the complete Row-Level Security policy catalogue, the `app.*` privileged functions, and the invariants. **There is no database page in this folder**; this is it.
- **[`../../backend/Architecture/api-endpoints.md`](../../backend/Architecture/api-endpoints.md)** — implemented routes with `file:line`, and the specified-but-missing ones.
