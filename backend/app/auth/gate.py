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
    Whether the gate applies at all. Classes 9-10 only (prd.md §4.3); everyone
    else — teachers, parents, admins, and 11-12 students — is never required to
    link a guardian, regardless of guardian status.
    """
    return is_student and class_level in (9, 10)


def is_guardian_gate_pending(
    *, is_student: bool, class_level: int | None, guardian_status: str | None
) -> bool:
    """
    The gate itself. Fails CLOSED: anything that is not a verified link —
    `null`, `pending`, `revoked` — holds the gate. Only `verified` opens it.
    Non-students and 11-12 students are never gated.
    """
    if not is_student:
        return False
    if class_level not in (9, 10):
        return False
    return guardian_status != "verified"
