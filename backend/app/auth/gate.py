"""
The parental-consent gate decision (prd.md §4.3, RBAC-002).

DELIBERATELY FREE OF DATABASE AND SETTINGS IMPORTS — the same rule as
`onboarding.py`. `me()` and `GET /api/auth/guardian/status` both derive their
`guardian.required`/gated decision here, so the "class 11-12 are never gated"
rule cannot drift between endpoints, and the decision is assertable in
`tests/unit` without a connection string.

The gate is an APPLICATION-layer decision on purpose: "class 9-10 student whose
guardian is not verified" is not expressible as a Row Level Security policy
(RLS cannot branch on the status of a row in another table per-access). The
database backstop is that the learning data tables themselves are
student-owner-only anyway.
"""


def guardian_required(*, is_student: bool, class_level: int | None) -> bool:
    """
    Whether the gate applies at all. Classes 9-10 (prd.md §4.3); teachers,
    parents, admins and 11-12 students are never required to link a guardian,
    regardless of guardian status.

    A student whose class level is UNKNOWN is treated as required. `None` here
    means the `student_profile` row was missing or unreadable, which under Row
    Level Security is also what a forgotten binding looks like — and the whole
    point of this gate is that we do not serve a 14-year-old as though they were
    18 because a read came back empty. It stays consistent with
    `is_guardian_gate_pending` deliberately: the two must agree, or a student
    would be blocked from every learning endpoint while `onboarding_state`
    reported `active` and offered no screen on which to fix it.
    """
    if not is_student:
        return False
    return class_level is None or class_level in (9, 10)


def is_guardian_gate_pending(
    *, is_student: bool, class_level: int | None, guardian_status: str | None
) -> bool:
    """
    The gate itself. Fails CLOSED in both directions: an unknown class level
    holds the gate (see `guardian_required`), and anything that is not a
    verified link — `null`, `pending`, `revoked` — holds it too. Only a
    `verified` link on a student the gate applies to opens it.
    """
    if not guardian_required(is_student=is_student, class_level=class_level):
        return False
    return guardian_status != "verified"
