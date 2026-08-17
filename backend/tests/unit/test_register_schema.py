"""
`admin` is not a self-registrable role (finding A1).

THE HOLE THIS CLOSES: `RegisterRequest.role` was `UserRole`, which includes
`admin`, and `register()` wrote it straight through. Nothing downstream
objected — `validate_required_student_fields` and `validate_student_group_for_class`
both return early for a non-student, the role chain in `register()` has no
`else`, and `derive_onboarding_state` skips the guardian and subscription rules
for a non-student. So one unauthenticated request produced an `active`
administrator, and `app.is_admin()` opened six read policies to it.

These tests cover the APPLICATION layer only. The database layer — the
`app_user_insert` policy's `role <> 'admin'` clause — is asserted in
`tests/integration/test_rls.py`, because it needs a real connection to prove.
Both exist on purpose: a validator can be forgotten by a future endpoint, and a
policy cannot produce a readable error message.
"""

import pytest
from pydantic import ValidationError

from app.auth.schemas import RegisterRequest
from app.models.enums import RegistrableRole, UserRole


def _payload(role: str) -> dict:
    """A teacher-shaped body; only `role` is under test."""
    return {
        "email": "someone@example.com",
        "password": "Password123",
        "full_name": "Some One",
        "role": role,
        "turnstile_token": "test-turnstile-token",
    }


class TestRegistrableRole:
    def test_admin_is_rejected(self):
        with pytest.raises(ValidationError) as caught:
            RegisterRequest(**_payload("admin"))

        # The field, not the whole body — `_validation_error_response` turns the
        # location into the per-field detail the client renders.
        assert caught.value.errors()[0]["loc"] == ("role",)

    @pytest.mark.parametrize("role", ["student", "teacher", "parent"])
    def test_every_other_role_is_accepted(self, role):
        # Student bodies fail the SEPARATE required-fields check, which is a
        # method call rather than Pydantic validation — so constructing the
        # model is expected to succeed for all three here.
        assert RegisterRequest(**_payload(role)).role.value == role

    def test_the_two_enums_have_not_drifted(self):
        """
        `RegistrableRole` must be `UserRole` minus exactly `admin`.

        A future role added to `UserRole` alone would be silently unregistrable;
        added to both without thought, it would be silently self-registrable.
        This fails on either, which is the point — it forces the decision to be
        made rather than defaulted.
        """
        assert {member.value for member in RegistrableRole} == {
            member.value for member in UserRole
        } - {"admin"}


class TestRoleComparisonsStillWork:
    """
    `register()` branches on `payload.role == RegistrableRole.student`.

    Guards against a refactor that reverts those comparisons to `UserRole`
    members: `RegistrableRole.student == UserRole.student` happens to be True
    today, because both are `str` mixin enums and `str.__eq__` is found before
    anything on `Enum` — but that is an implementation detail of the enum
    machinery, not a contract. Depending on it is how the student branch
    silently stops firing on a Python upgrade.
    """

    def test_comparison_against_its_own_enum_is_true(self):
        assert RegisterRequest(**_payload("teacher")).role == RegistrableRole.teacher

    def test_the_value_is_what_reaches_the_insert(self):
        # `register()` passes `payload.role.value` into the INSERT, so this is
        # the string the `user_role` column actually receives.
        assert RegisterRequest(**_payload("parent")).role.value == "parent"
