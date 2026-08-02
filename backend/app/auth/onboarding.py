"""
The `onboarding_state` derivation (tdd.md §3.1).

DELIBERATELY FREE OF DATABASE AND SETTINGS IMPORTS. This is the single field the
frontend routes on, and every rule in it is a product decision — so it should be
assertable without a connection string, an engine, or a live Supabase project.
Keeping it here rather than in `service.py` is what makes `tests/unit` genuinely
runnable anywhere, including on a fork with no secrets.

It mirrors `frontend/lib/auth/onboarding.ts` on the other side of the contract.
"""

# Statuses that count as paid-or-trialing access (prd.md §2.6).
ACTIVE_SUBSCRIPTION_STATUSES = frozenset({"trialing", "active"})


def derive_onboarding_state(
    *,
    email_verified: bool,
    two_factor_active: bool,
    is_student: bool,
    guardian_required: bool,
    guardian_status: str | None,
    subscription_status: str | None,
) -> str:
    """
    The precedence table, evaluated in order. Clients route on this single field
    and must not reconstruct it from the underlying booleans — that is how the
    four tracks drift apart.

    Rule 4 is NOT MONOTONIC: it can fire after a user has already been `active`,
    when a trial lapses. It is the only backward transition in the system, and a
    consumer that evaluates once and caches `active` will strand that user on a
    page they no longer have rights to.

    Rule 4 also FAILS CLOSED — no subscription row means no access, never "still
    trialing", because a failed insert at registration must not silently grant
    indefinite free use (prd.md MON-2).
    """
    if not email_verified:
        return "email_verification_pending"
    if not two_factor_active:
        return "two_factor_enrollment_pending"
    if guardian_required and guardian_status != "verified":
        return "guardian_link_pending"
    if is_student and (
        subscription_status is None or subscription_status not in ACTIVE_SUBSCRIPTION_STATUSES
    ):
        return "plan_selection_pending"
    return "active"
