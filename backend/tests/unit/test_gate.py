"""
The guardian gate decision (prd.md §4.3, RBAC-002).

Pure functions, no database — the point of gate.py. The same decision drives
`me()`, `GET /api/auth/guardian/status`, and the `require_guardian_verified`
dependency, so this matrix is what guarantees they cannot drift.
"""

import pytest

from app.auth.gate import guardian_required, is_guardian_gate_pending


class TestGuardianRequired:
    def test_class_9_and_10_students_require_a_guardian(self):
        assert guardian_required(is_student=True, class_level=9) is True
        assert guardian_required(is_student=True, class_level=10) is True

    @pytest.mark.parametrize("class_level", [11, 12, None])
    def test_class_11_12_and_missing_level_never_require(self, class_level):
        assert guardian_required(is_student=True, class_level=class_level) is False

    @pytest.mark.parametrize("class_level", [9, 10, 11, 12, None])
    def test_non_students_never_require(self, class_level):
        assert guardian_required(is_student=False, class_level=class_level) is False


class TestIsGuardianGatePending:
    def test_class_9_student_without_verified_guardian_is_gated(self):
        assert is_guardian_gate_pending(
            is_student=True, class_level=9, guardian_status=None
        ) is True

    @pytest.mark.parametrize("status", [None, "pending", "revoked"])
    def test_anything_other_than_verified_holds_the_gate(self, status):
        assert is_guardian_gate_pending(
            is_student=True, class_level=9, guardian_status=status
        ) is True

    def test_verified_opens_the_gate(self):
        assert is_guardian_gate_pending(
            is_student=True, class_level=9, guardian_status="verified"
        ) is False

    @pytest.mark.parametrize("class_level", [11, 12, None])
    @pytest.mark.parametrize("status", [None, "pending", "revoked"])
    def test_class_11_12_and_missing_level_never_gated(self, class_level, status):
        # Even a fully unverified 11-12 student is never held behind the gate.
        assert is_guardian_gate_pending(
            is_student=True, class_level=class_level, guardian_status=status
        ) is False

    @pytest.mark.parametrize("class_level", [9, 10, 11, 12, None])
    @pytest.mark.parametrize("status", [None, "pending", "revoked"])
    def test_non_students_never_gated(self, class_level, status):
        assert is_guardian_gate_pending(
            is_student=False, class_level=class_level, guardian_status=status
        ) is False
