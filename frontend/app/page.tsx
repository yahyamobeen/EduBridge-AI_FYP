/**
 * Placeholder root. The real landing page is Phase 4; this exists so the app
 * builds and runs at the end of Phase 1, and so the token wiring is visible.
 */
export default function Page() {
  return (
    <main className="mx-auto max-w-container-max px-margin-mobile py-16 md:px-margin-desktop">
      <p className="text-label-caps uppercase text-on-surface-variant">Scaffold</p>
      <h1 className="mt-2 font-headline text-headline-lg-mobile md:text-headline-lg">
        EduBridge AI
      </h1>
      <p className="mt-4 max-w-prose text-body-md text-on-surface-variant">
        Frontend scaffold is up. Design tokens, linting and the test harness are wired;
        internationalisation and routing land in the next phase.
      </p>

      {/* Renders the role palettes from DESIGN.md so a token regression is
          visible rather than silent. */}
      <ul className="mt-8 flex flex-wrap gap-3" aria-label="Role palette check">
        <li className="rounded bg-student-blue px-3 py-2 text-body-sm text-on-surface">
          Student
        </li>
        <li className="rounded bg-teacher-indigo px-3 py-2 text-body-sm text-white">Teacher</li>
        <li className="rounded bg-surface-container-high px-3 py-2 text-body-sm text-on-surface">
          Parent
        </li>
      </ul>
    </main>
  )
}
