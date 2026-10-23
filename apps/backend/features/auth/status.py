"""Account lifecycle (MODELISATION_BACKEND.md § 4.1).

Pure on purpose: `plan_transition` decides, `AuthService.transition` applies the plan and writes the
audit entry in the same transaction. Nothing else may change `User.status`.
"""

from dataclasses import dataclass
from enum import StrEnum

from core.exceptions import AlreadyExistsError


class AccountStatus(StrEnum):
    PENDING_EMAIL  = "pending_email"
    ONBOARDING     = "onboarding"
    PENDING_REVIEW = "pending_review"
    ACTIVE         = "active"
    REJECTED       = "rejected"
    SUSPENDED      = "suspended"


# Statuses that may hold a session: `onboarding` signs in only to complete its profile,
# every route except /auth/me, /auth/logout and /me/onboarding requires `active`.
LOGIN_STATUSES = frozenset({AccountStatus.ACTIVE, AccountStatus.ONBOARDING})


@dataclass(frozen=True)
class _Rule:
    action:   str
    by_admin: bool


_S = AccountStatus

_RULES: dict[tuple[AccountStatus, AccountStatus], _Rule] = {
    (_S.PENDING_EMAIL, _S.ONBOARDING):  _Rule("user.verify_email", by_admin=False),
    (_S.ONBOARDING, _S.PENDING_REVIEW): _Rule("user.submit_profile", by_admin=False),
    (_S.ONBOARDING, _S.ACTIVE):         _Rule("user.auto_approve", by_admin=False),
    (_S.PENDING_REVIEW, _S.ACTIVE):     _Rule("user.approve", by_admin=True),
    (_S.PENDING_REVIEW, _S.REJECTED):   _Rule("user.reject", by_admin=True),
    (_S.ACTIVE, _S.SUSPENDED):          _Rule("user.suspend", by_admin=True),
    (_S.SUSPENDED, _S.ACTIVE):          _Rule("user.reactivate", by_admin=True),
}


class InvalidTransitionError(AlreadyExistsError):
    code = "invalid_transition"

    def __init__(self, current: AccountStatus, target: AccountStatus) -> None:
        super().__init__(f"Transition impossible : {current} → {target}")


@dataclass(frozen=True)
class TransitionPlan:
    from_status: AccountStatus
    to_status:   AccountStatus
    action:      str


def plan_transition(current: AccountStatus, target: AccountStatus, *, by_admin: bool) -> TransitionPlan:
    """Validate a status change. Admin transitions cannot be self-served, and the other way round."""
    rule = _RULES.get((current, target))
    if rule is None or rule.by_admin != by_admin:
        raise InvalidTransitionError(current, target)
    return TransitionPlan(from_status=current, to_status=target, action=rule.action)
