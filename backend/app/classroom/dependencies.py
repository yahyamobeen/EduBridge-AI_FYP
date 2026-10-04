"""
Who may call a classroom route.

Every dependency here wraps `authenticated` (through `require_role` or
`require_guardian_verified`), so the user is bound and the identity check has
already run UNDER Row-Level Security before any of these decides anything.
Membership of a SPECIFIC classroom is not decided here: that is per-space, and
the service asks the database (`app.owns_space`, `app.is_enrolled_in`).
"""

from typing import Annotated

from fastapi import Depends

from app.auth.dependencies import AuthContext, require_guardian_verified, require_role
from app.core.errors import forbidden_scope
from app.models.enums import UserRole

_PARTICIPANTS = frozenset({UserRole.teacher.value, UserRole.student.value})


def participant(ctx: Annotated[AuthContext, Depends(require_guardian_verified)]) -> AuthContext:
    """
    A teacher, or a student who passes the Class 9–10 guardian gate.

    The gate dependency lets every non-student through, so the role check that
    follows is what keeps parents and administrators out — the classroom routes
    are not theirs (parents get their own read-only overview in a later phase).
    """
    if ctx.role not in _PARTICIPANTS:
        raise forbidden_scope()
    return ctx


def gated_student(ctx: Annotated[AuthContext, Depends(require_guardian_verified)]) -> AuthContext:
    if ctx.role != UserRole.student.value:
        raise forbidden_scope()
    return ctx


Participant = Annotated[AuthContext, Depends(participant)]
GatedStudent = Annotated[AuthContext, Depends(gated_student)]
Teacher = Annotated[AuthContext, Depends(require_role(UserRole.teacher.value))]
# Leaving is a consent right (prd.md §4.2): a student whose guardian link was
# later revoked must still be able to leave, so this is role-gated and NOT
# guardian-gated.
AnyStudent = Annotated[AuthContext, Depends(require_role(UserRole.student.value))]
