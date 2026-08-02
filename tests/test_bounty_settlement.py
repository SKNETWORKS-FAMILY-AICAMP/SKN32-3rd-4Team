"""바운티 L2 — escrow · 이의제기 · 제한적 slash (결정론).

핵심 검증 관점: (1) 허용된 상태 전이만 통과 (2) 이의제기 기간 내 정산 거부
(3) **몰수는 객관적 위반에만** — "부정확 의심"으로는 몰수 불가 (4) 원장 불변식.
"""

from __future__ import annotations

import pytest

from app.application.bounty_settlement import (
    DISPUTE_WINDOW,
    ESCROWED,
    OPEN,
    REJECTED,
    SETTLED,
    SLASH_DUPLICATE,
    SLASH_FORGED_CITATION,
    SLASHED,
    SUBMITTED,
    UNDER_REVIEW,
    Bounty,
    PointLedger,
    can_settle,
    open_bounty,
    settle,
    transition,
    validate_slash_reason,
)
from app.core.errors import ConflictErr, ValidationErr


def _b(status: str = OPEN, provider: str | None = "prov", dispute_days: int = 7) -> Bounty:
    return Bounty("B1", "req", provider, reward=100, stake=20, status=status,
                  dispute_days=dispute_days)


def _ledger(**balances: int) -> PointLedger:
    led = PointLedger()
    for i, (acct, amt) in enumerate(balances.items()):
        led.credit(acct, amt, key=f"seed:{acct}:{i}")
    return led


# --- 생성 계약 -------------------------------------------------------------
def test_open_bounty_requires_positive_reward_stake_and_window():
    with pytest.raises(ValidationErr):
        open_bounty("B1", "req", 0, 10, 7)          # reward 0
    with pytest.raises(ValidationErr):
        open_bounty("B1", "req", 100, -1, 7)        # stake 음수
    with pytest.raises(ValidationErr):
        open_bounty("B1", "req", 100, 10, 0)        # 이의제기 기간 0일
    with pytest.raises(ValidationErr):
        open_bounty("  ", "req", 100, 10, 7)        # 빈 id
    b = open_bounty("B1", "req", 100, 10, 7)
    assert b.status == OPEN and b.provider_id is None


# --- 상태 머신 -------------------------------------------------------------
def test_only_allowed_transitions_pass():
    b = transition(_b(OPEN), SUBMITTED)
    b = transition(b, ESCROWED)
    b = transition(b, DISPUTE_WINDOW)
    assert transition(b, SETTLED).status == SETTLED


@pytest.mark.parametrize(
    "frm,to",
    [
        (OPEN, ESCROWED),        # L1 건너뛰고 바로 escrow 금지
        (OPEN, SETTLED),         # 검증 없이 정산 금지
        (SUBMITTED, SETTLED),    # 이의제기 기간 건너뛰기 금지
        (ESCROWED, SETTLED),     # dispute_window 없이 정산 금지
        (SETTLED, DISPUTE_WINDOW),  # 종료 상태에서 되돌리기 금지
        (REJECTED, ESCROWED),
        (SLASHED, SETTLED),
    ],
)
def test_disallowed_transitions_are_conflicts(frm, to):
    with pytest.raises(ConflictErr):
        transition(_b(frm), to)


def test_unknown_state_is_validation_error():
    with pytest.raises(ValidationErr):
        transition(_b(OPEN), "approved")  # 존재하지 않는 상태


# --- 이의제기 기간 ---------------------------------------------------------
def test_cannot_settle_inside_dispute_window():
    b = _b(DISPUTE_WINDOW, dispute_days=7)
    led = _ledger(req=100)
    led.hold("B1", "req", 100, key="hold:B1")
    assert can_settle(b, 6) is False
    with pytest.raises(ConflictErr):
        settle(b, led, 6)
    # 기간 내 정산 시도가 실패했으므로 포인트는 그대로 묶여 있어야 한다
    assert led.escrowed("B1") == 100 and led.balance("prov") == 0


def test_settle_after_window_pays_provider_once():
    b = _b(DISPUTE_WINDOW, dispute_days=7)
    led = _ledger(req=100)
    led.hold("B1", "req", 100, key="hold:B1")
    done = settle(b, led, 7)
    assert done.status == SETTLED
    assert led.balance("prov") == 100 and led.escrowed("B1") == 0
    # 같은 바운티를 두 번 정산하면 멱등 가드로 막힌다
    with pytest.raises(ConflictErr):
        settle(_b(DISPUTE_WINDOW), led, 7)


def test_settle_requires_provider():
    with pytest.raises(ValidationErr):
        settle(_b(DISPUTE_WINDOW, provider=None), _ledger(req=100), 7)


def test_negative_elapsed_days_rejected():
    with pytest.raises(ValidationErr):
        can_settle(_b(DISPUTE_WINDOW), -1)


# --- 몰수(slash)는 객관적 위반에만 ★핵심 -----------------------------------
def test_slash_only_for_objective_violations():
    for ok in (SLASH_FORGED_CITATION, SLASH_DUPLICATE, "unknown_source"):
        assert validate_slash_reason(ok) == ok


@pytest.mark.parametrize(
    "subjective",
    ["inaccurate", "부정확 의심", "low_quality", "wrong", "buyer_unsatisfied", "false"],
)
def test_slash_rejected_for_truth_judgements(subjective):
    """'틀린 것 같다'로는 몰수할 수 없다 — L2가 사실성 판정 권위를 주장하지 않게 막는 장치."""
    with pytest.raises(ValidationErr):
        validate_slash_reason(subjective)


def test_burn_enforces_slash_reason_and_balance():
    led = _ledger(prov=20)
    with pytest.raises(ValidationErr):  # 주관적 사유로는 몰수 불가
        led.burn("prov", 20, reason="inaccurate", key="burn:1")
    assert led.balance("prov") == 20   # 실패했으므로 잔액 불변
    with pytest.raises(ValidationErr):  # stake 부족
        led.burn("prov", 999, reason=SLASH_FORGED_CITATION, key="burn:2")
    led.burn("prov", 20, reason=SLASH_FORGED_CITATION, key="burn:3")
    assert led.balance("prov") == 0


# --- 원장 불변식 -----------------------------------------------------------
def test_hold_rejects_insufficient_balance_without_partial_hold():
    led = _ledger(req=50)
    with pytest.raises(ValidationErr):
        led.hold("B1", "req", 100, key="hold:B1")
    # 부분 예치로 때우지 않는다 — 잔액과 escrow 모두 불변
    assert led.balance("req") == 50 and led.escrowed("B1") == 0


def test_ledger_is_idempotent_by_key():
    led = _ledger(req=200)
    led.hold("B1", "req", 100, key="hold:B1")
    with pytest.raises(ConflictErr):
        led.hold("B1", "req", 100, key="hold:B1")  # 같은 키 재사용
    assert led.escrowed("B1") == 100 and led.balance("req") == 100


def test_escrowed_points_are_not_double_spendable():
    """escrow에 묶인 포인트는 잔액에서 빠져 다시 쓸 수 없다."""
    led = _ledger(req=100)
    led.hold("B1", "req", 100, key="hold:B1")
    assert led.balance("req") == 0
    with pytest.raises(ValidationErr):
        led.hold("B2", "req", 100, key="hold:B2")


def test_refund_returns_escrow_to_requester_on_rejection():
    led = _ledger(req=100)
    led.hold("B1", "req", 100, key="hold:B1")
    assert led.refund("B1", "req", key="refund:B1") == 100
    assert led.balance("req") == 100 and led.escrowed("B1") == 0


def test_release_without_escrow_fails():
    with pytest.raises(ValidationErr):
        _ledger().release("B1", "prov", key="x")


def test_reject_refunds_escrow_and_does_not_burn_stake():
    """기각은 '부정행위 아님' 경로 — 요청자에게 환불하고 stake는 건드리지 않는다."""
    from app.application.bounty_settlement import reject

    led = _ledger(req=100, prov=20)
    led.hold("B1", "req", 100, key="hold:B1")
    out = reject(_b(UNDER_REVIEW), led)
    assert out.status == REJECTED
    assert led.balance("req") == 100      # 환불됨
    assert led.balance("prov") == 20      # stake 보존
    assert led.escrowed("B1") == 0


def test_slash_burns_stake_and_refunds_requester():
    """객관 위반 확인 시 stake 몰수 + escrow 환불."""
    from app.application.bounty_settlement import slash

    led = _ledger(req=100, prov=20)
    led.hold("B1", "req", 100, key="hold:B1")
    out = slash(_b(UNDER_REVIEW), led, SLASH_FORGED_CITATION)
    assert out.status == SLASHED
    assert led.balance("prov") == 0       # stake 몰수
    assert led.balance("req") == 100      # 환불


def test_slash_rejects_subjective_reason_before_touching_ledger():
    """주관적 사유면 원장을 건드리기 전에 실패해야 한다."""
    from app.application.bounty_settlement import slash

    led = _ledger(req=100, prov=20)
    led.hold("B1", "req", 100, key="hold:B1")
    with pytest.raises(ValidationErr):
        slash(_b(UNDER_REVIEW), led, "inaccurate")
    assert led.balance("prov") == 20 and led.escrowed("B1") == 100  # 불변


def test_under_review_can_reject_or_slash_or_settle():
    """이의 검토 결과는 세 갈래 모두 가능해야 한다(L3 판단 결과 반영)."""
    for to in (SETTLED, SLASHED, REJECTED):
        assert transition(_b(UNDER_REVIEW), to).status == to
