"""지식 바운티 L2 — escrow · 이의제기 · 제한적 slash (프레임워크 무의존).

설계: `docs/plans/2026-07-22_2100_지식바운티_검증모델_재설계.md` §4 L2

**L2가 다루는 것**: 포인트를 즉시 지급하지 않고 묶어두고(escrow), 이의제기 기간을 준 뒤
정산하며, 몰수(slash)는 **객관적 위반에만** 적용한다.

**L2가 하지 않는 것(가장 중요)**: 진실 판정. "틀린 것 같다"는 이유로는 몰수하지 않는다.
그렇게 하면 L1이 확인할 수 없는 사실성을 판정하는 권위를 주장하게 된다. 몰수 사유는
아래 `SLASHABLE`에 열거된 **객관적으로 확인 가능한 위반**으로 한정된다.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from app.core.errors import ConflictErr, ValidationErr

# --- 상태 ------------------------------------------------------------------
OPEN = "open"                      # 바운티 공개(보상 확정, stake 예치)
SUBMITTED = "submitted"            # 제출 접수(L1 검증 대기)
REJECTED = "rejected"              # L1 미통과
ESCROWED = "escrowed"              # L1 통과 → 포인트 묶임
DISPUTE_WINDOW = "dispute_window"  # 이의제기 기간
UNDER_REVIEW = "under_review"      # 이의 제기됨 → 검토(L3)
SETTLED = "settled"                # 정산 완료
SLASHED = "slashed"                # 객관적 위반 확인 → stake 몰수

#: 허용된 상태 전이. 여기 없는 전이는 조용히 통과시키지 않고 즉시 거부한다(무폴백).
_TRANSITIONS: dict[str, frozenset[str]] = {
    OPEN: frozenset({SUBMITTED}),
    SUBMITTED: frozenset({ESCROWED, REJECTED}),
    ESCROWED: frozenset({DISPUTE_WINDOW}),
    DISPUTE_WINDOW: frozenset({SETTLED, UNDER_REVIEW}),
    UNDER_REVIEW: frozenset({SETTLED, SLASHED, REJECTED}),
    REJECTED: frozenset(),
    SETTLED: frozenset(),
    SLASHED: frozenset(),
}

# --- 몰수 가능한 객관적 위반 (이것만 허용) --------------------------------
#: 인용문이 색인 원문과 불일치(위조 인용)
SLASH_FORGED_CITATION = "forged_citation"
#: 출처를 색인에서 찾을 수 없음(존재하지 않는 문서 인용)
SLASH_UNKNOWN_SOURCE = "unknown_source"
#: 이미 있는 지식의 명백한 중복 제출
SLASH_DUPLICATE = "duplicate"
SLASHABLE = frozenset({SLASH_FORGED_CITATION, SLASH_UNKNOWN_SOURCE, SLASH_DUPLICATE})


@dataclass(frozen=True)
class Bounty:
    """정산 관점의 바운티 상태(불변 — 전이는 새 객체를 만든다)."""

    bounty_id: str
    requester_id: str
    provider_id: str | None
    reward: int
    stake: int
    status: str
    dispute_days: int


def _require_positive(value: int, name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValidationErr(f"{name}은 정수여야 합니다: {value!r}")
    if value <= 0:
        raise ValidationErr(f"{name}은 0보다 커야 합니다: {value}")
    return value


def open_bounty(
    bounty_id: str, requester_id: str, reward: int, stake: int, dispute_days: int
) -> Bounty:
    """바운티를 공개한다. 보상·stake·이의제기 기간은 이 시점에 확정된다."""
    if not bounty_id.strip() or not requester_id.strip():
        raise ValidationErr("bounty_id와 requester_id는 비어 있을 수 없습니다.")
    _require_positive(reward, "reward")
    _require_positive(stake, "stake")
    if not isinstance(dispute_days, int) or dispute_days < 1:
        raise ValidationErr(f"이의제기 기간은 1일 이상이어야 합니다: {dispute_days!r}")
    return Bounty(bounty_id, requester_id, None, reward, stake, OPEN, dispute_days)


def transition(bounty: Bounty, to: str) -> Bounty:
    """상태 전이. 허용 표에 없으면 ConflictErr(409) — 임의로 진행하지 않는다."""
    if to not in _TRANSITIONS:
        raise ValidationErr(f"알 수 없는 상태입니다: {to!r}")
    allowed = _TRANSITIONS[bounty.status]
    if to not in allowed:
        raise ConflictErr(
            f"허용되지 않은 상태 전이입니다: {bounty.status} → {to} (허용: {sorted(allowed)})"
        )
    return replace(bounty, status=to)


def validate_slash_reason(reason: str) -> str:
    """몰수 사유 검증 — 객관적 위반만 허용한다.

    "부정확 의심", "품질 낮음" 같은 주관·진실 판정 사유는 거부한다. 이것이 L2가 사실성
    판정 권위를 주장하지 않게 막는 핵심 장치다.
    """
    if reason not in SLASHABLE:
        raise ValidationErr(
            f"몰수는 객관적 위반에만 허용됩니다: {reason!r} (허용: {sorted(SLASHABLE)})"
        )
    return reason


class PointLedger:
    """비현금 내부 포인트 원장.

    불변식: 잔액은 음수가 될 수 없고, 같은 멱등키의 기록은 두 번 반영되지 않는다.
    escrow에 묶인 포인트는 잔액에서 빠져 있어 이중 사용이 불가능하다.
    """

    def __init__(self, balances: dict[str, int] | None = None) -> None:
        self._balances: dict[str, int] = dict(balances or {})
        self._escrow: dict[str, int] = {}
        self._applied: set[str] = set()

    # --- 조회 ---
    def balance(self, account: str) -> int:
        return self._balances.get(account, 0)

    def escrowed(self, bounty_id: str) -> int:
        return self._escrow.get(bounty_id, 0)

    def _guard_idempotent(self, key: str) -> None:
        if key in self._applied:
            raise ConflictErr(f"이미 반영된 원장 기록입니다(멱등키 중복): {key}")
        self._applied.add(key)

    # --- 기록 ---
    def credit(self, account: str, amount: int, *, key: str) -> None:
        """포인트 적립(테스트·초기 지급용)."""
        _require_positive(amount, "amount")
        self._guard_idempotent(key)
        self._balances[account] = self.balance(account) + amount

    def hold(self, bounty_id: str, payer: str, amount: int, *, key: str) -> None:
        """escrow 예치 — payer 잔액에서 빼서 바운티에 묶는다."""
        _require_positive(amount, "amount")
        if self.balance(payer) < amount:
            # 잔액 부족을 조용히 부분 예치로 때우지 않는다(무폴백).
            raise ValidationErr(
                f"잔액이 부족합니다: {payer} 보유 {self.balance(payer)} < 필요 {amount}"
            )
        self._guard_idempotent(key)
        self._balances[payer] = self.balance(payer) - amount
        self._escrow[bounty_id] = self.escrowed(bounty_id) + amount

    def release(self, bounty_id: str, payee: str, *, key: str) -> int:
        """escrow 해제 — 묶인 전액을 payee에게 지급한다.

        멱등 가드를 **금액 검사보다 먼저** 둔다. 중복 정산 시도는 "escrow가 없다"(422)가
        아니라 "이미 반영됨"(409)으로 보고돼야 원인이 분명하다.
        """
        self._guard_idempotent(key)
        amount = self.escrowed(bounty_id)
        if amount <= 0:
            raise ValidationErr(f"해제할 escrow가 없습니다: {bounty_id}")
        self._escrow[bounty_id] = 0
        self._balances[payee] = self.balance(payee) + amount
        return amount

    def refund(self, bounty_id: str, payer: str, *, key: str) -> int:
        """escrow 반환 — 묶인 전액을 원 지불자에게 돌려준다(반려 시)."""
        return self.release(bounty_id, payer, key=key)

    def burn(self, account: str, amount: int, *, reason: str, key: str) -> None:
        """stake 몰수 — 객관적 위반에만. 사유는 SLASHABLE로 제한된다."""
        validate_slash_reason(reason)
        _require_positive(amount, "amount")
        if self.balance(account) < amount:
            raise ValidationErr(
                f"몰수할 stake가 부족합니다: {account} 보유 {self.balance(account)} < {amount}"
            )
        self._guard_idempotent(key)
        self._balances[account] = self.balance(account) - amount


def can_settle(bounty: Bounty, days_elapsed: int) -> bool:
    """이의제기 기간이 지났는지. 기간 내 정산은 허용하지 않는다."""
    if not isinstance(days_elapsed, int) or days_elapsed < 0:
        raise ValidationErr(f"경과 일수가 올바르지 않습니다: {days_elapsed!r}")
    return bounty.status == DISPUTE_WINDOW and days_elapsed >= bounty.dispute_days


def reject(bounty: Bounty, ledger: PointLedger) -> Bounty:
    """부적격 제출을 기각한다 — escrow는 **요청자에게 환불**하고 stake는 몰수하지 않는다.

    "부정행위는 아니지만 채택할 수 없음"이 이 경로다. 몰수는 `slash`만 한다.
    escrow가 아직 없는 단계(submitted)에서의 기각도 허용한다(환불할 것이 없으면 건너뛴다).
    """
    moved = transition(bounty, REJECTED)
    if ledger.escrowed(bounty.bounty_id) > 0:
        ledger.refund(bounty.bounty_id, bounty.requester_id, key=f"refund:{bounty.bounty_id}")
    return moved


def slash(bounty: Bounty, ledger: PointLedger, reason: str) -> Bounty:
    """객관적 위반이 확인된 경우 stake를 몰수하고 escrow는 요청자에게 환불한다.

    `reason`은 `SLASHABLE`에 열거된 값만 허용된다 — 진실 판정을 몰수 근거로 삼지 않는다.
    """
    validate_slash_reason(reason)
    if bounty.provider_id is None:
        raise ValidationErr("provider가 없는 바운티는 몰수할 수 없습니다.")
    moved = transition(bounty, SLASHED)
    ledger.burn(
        bounty.provider_id, bounty.stake, reason=reason, key=f"slash:{bounty.bounty_id}"
    )
    if ledger.escrowed(bounty.bounty_id) > 0:
        ledger.refund(bounty.bounty_id, bounty.requester_id, key=f"refund:{bounty.bounty_id}")
    return moved


def settle(bounty: Bounty, ledger: PointLedger, days_elapsed: int) -> Bounty:
    """이의제기 기간 경과 후 escrow를 provider에게 지급하고 정산 완료로 전이한다."""
    if bounty.provider_id is None:
        raise ValidationErr("provider가 지정되지 않은 바운티는 정산할 수 없습니다.")
    if not can_settle(bounty, days_elapsed):
        raise ConflictErr(
            f"아직 정산할 수 없습니다(상태={bounty.status}, 경과 {days_elapsed}/{bounty.dispute_days}일)"
        )
    ledger.release(bounty.bounty_id, bounty.provider_id, key=f"settle:{bounty.bounty_id}")
    return transition(bounty, SETTLED)
