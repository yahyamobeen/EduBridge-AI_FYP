"""
The `onboarding_state` precedence table (tdd.md §3.1).

Pure function, no database — which is the point. This is the single field the
frontend routes on, and every one of its rules is a product decision that can be
asserted directly rather than reconstructed through five inserts.
"""

import pytest

from app.auth.onboarding import derive_onboarding_state

# A fully onboarded student, to be spoiled one rule at a time.
ACTIVE_STUDENT = {
    "email_verified": True,
    "two_factor_active": True,
    "is_student": True,
    "guardian_required": False,
    "guardian_status": None,
    "subscription_status": "active",
}


def state(**overrides) -> str:
    return derive_onboarding_state(**{**ACTIVE_STUDENT, **overrides})


def test_baseline_is_active():
    assert state() == "active"


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        ({"email_verified": False}, "email_verification_pending"),
        ({"two_factor_active": False}, "two_factor_enrollment_pending"),
        (
            {"guardian_required": True, "guardian_status": "pending"},
            "guardian_link_pending",
        ),
        ({"subscription_status": "expired"}, "plan_selection_pending"),
    ],
)
def test_each_rule_fires(overrides, expected):
    assert state(**overrides) == expected


def test_precedence_is_ordered_not_arbitrary():
    """Every rule unsatisfied at once still reports the FIRST one."""
    assert (
        state(
            email_verified=False,
            two_factor_active=False,
            guardian_required=True,
            guardian_status=None,
            subscription_status=None,
        )
        == "email_verification_pending"
    )


class TestSubscriptionFailsClosed:
    """
    prd.md MON-2. A missing subscription row means NO access — never an implied
    trial. A failed insert at registration must not hand out indefinite free use.
    """

    def test_no_row_is_not_access(self):
        assert state(subscription_status=None) == "plan_selection_pending"

    @pytest.mark.parametrize("status", ["past_due", "canceled", "expired"])
    def test_lapsed_statuses_are_not_access(self, status):
        assert state(subscription_status=status) == "plan_selection_pending"

    @pytest.mark.parametrize("status", ["trialing", "active"])
    def test_only_trialing_and_active_grant_access(self, status):
        assert state(subscription_status=status) == "active"


class TestNonMonotonic:
    """
    The only backward transition in the system: rule 4 can fire AFTER a user has
    been active. A consumer that evaluates once and caches `active` strands the
    user on a page they no longer have rights to (tdd.md §3.1).
    """

    def test_a_lapsed_trial_returns_an_active_student_to_plan_selection(self):
        assert state(subscription_status="trialing") == "active"
        assert state(subscription_status="expired") == "plan_selection_pending"


class TestSubscriptionIsStudentsOnly:
    """
    prd.md §2.6: students are the subscriber of record. A teacher or parent
    without a subscription row is fully active — gating them would lock out the
    people a student's account depends on.
    """

    @pytest.mark.parametrize("status", [None, "expired"])
    def test_non_students_are_unaffected_by_subscription(self, status):
        assert state(is_student=False, subscription_status=status) == "active"


class TestGuardianGate:
    def test_only_applies_when_required(self):
        # Class 11-12 students never have it required, so no code path can put
        # them behind the gate.
        assert state(guardian_required=False, guardian_status=None) == "active"

    @pytest.mark.parametrize("status", [None, "pending", "revoked"])
    def test_anything_other_than_verified_holds_the_gate(self, status):
        assert state(guardian_required=True, guardian_status=status) == "guardian_link_pending"

    def test_verified_opens_it(self):
        assert state(guardian_required=True, guardian_status="verified") == "active"
