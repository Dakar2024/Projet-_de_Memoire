from itertools import product

import pytest

from features.auth.status import (
    LOGIN_STATUSES,
    AccountStatus,
    InvalidTransitionError,
    TransitionPlan,
    plan_transition,
)

S = AccountStatus

# The diagram of MODELISATION_BACKEND.md § 4.1, written out independently of the implementation:
# (from, to) -> (audit action, performed by an admin).
EXPECTED: dict[tuple[AccountStatus, AccountStatus], tuple[str, bool]] = {
    (S.PENDING_EMAIL, S.ONBOARDING):   ("user.verify_email", False),
    (S.ONBOARDING, S.PENDING_REVIEW):  ("user.submit_profile", False),
    (S.ONBOARDING, S.ACTIVE):          ("user.auto_approve", False),
    (S.PENDING_REVIEW, S.ACTIVE):      ("user.approve", True),
    (S.PENDING_REVIEW, S.REJECTED):    ("user.reject", True),
    (S.ACTIVE, S.SUSPENDED):           ("user.suspend", True),
    (S.SUSPENDED, S.ACTIVE):           ("user.reactivate", True),
}


@pytest.mark.parametrize(("current", "target", "by_admin"), list(product(S, S, (False, True))))
def test_every_transition_pair(current: AccountStatus, target: AccountStatus, by_admin: bool):
    expected = EXPECTED.get((current, target))
    if expected is None or expected[1] != by_admin:
        with pytest.raises(InvalidTransitionError):
            plan_transition(current, target, by_admin=by_admin)
        return
    assert plan_transition(current, target, by_admin=by_admin) == TransitionPlan(
        from_status=current, to_status=target, action=expected[0]
    )


def test_status_values_match_the_frontend_contract():
    assert {s.value for s in S} == {
        "pending_email", "onboarding", "pending_review", "active", "rejected", "suspended",
    }


def test_only_active_and_onboarding_accounts_can_sign_in():
    assert frozenset({S.ACTIVE, S.ONBOARDING}) == LOGIN_STATUSES


def test_invalid_transition_is_a_conflict():
    with pytest.raises(InvalidTransitionError) as info:
        plan_transition(S.REJECTED, S.ACTIVE, by_admin=True)
    assert info.value.status == 409
    assert info.value.code == "invalid_transition"
