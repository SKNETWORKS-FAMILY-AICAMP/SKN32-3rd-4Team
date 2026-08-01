"""지식 바운티 L0 등급화 + L1 기계 검증 (프레임워크 무의존).

설계 근거: `docs/plans/2026-07-22_2100_지식바운티_검증모델_재설계.md`

**이 모듈이 하지 않는 일(가장 중요)**: 제출된 지식이 **사실인지 판정하지 않는다.**
사실성 자동 검증은 정답(ground truth)이 없는 정보시장의 오라클 문제라 원리적으로 불가능하다
(자동으로 참을 가릴 수 있다면 애초에 그 지식을 살 이유가 없다).

**이 모듈이 하는 일**: 제출물의 성질 3가지만 기계적으로 확인한다.
  1. 근거성 — 근거가 제시됐고, 그 근거가 주장을 지지하는가(SupportCheck 재사용)
  2. 재현성 — 인용한 출처를 다시 조회해 그 내용이 실제로 존재하는가
  3. 중복성 — 이미 아는 지식과 중복인가

세 검사를 모두 통과해도 **"맞다"는 뜻이 아니다.** 근거 자체가 거짓·조작·낡았으면 통과한다.
따라서 통과 상태의 이름을 `verified`가 아니라 `grounded`로 둔다(과신 유발 방지).
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Protocol, runtime_checkable

from app.application.ports import Evidence, RetrieverPort
from app.core.errors import ValidationErr

_WS = re.compile(r"\s+")


def _normalize(text: str) -> str:
    """공백 차이를 무시하기 위한 정규화(내용 자체는 바꾸지 않는다)."""
    return _WS.sub(" ", text).strip()


def _text_match_ratio(quoted: str, source_text: str) -> float:
    """인용문이 원문과 얼마나 문자 수준으로 일치하는가 [0,1].

    부분 인용이 정상이므로 **포함 관계면 1.0**으로 본다. 아니면 문자 유사도를 쓴다.
    임베딩 의미 유사도와 달리 표현을 바꿔 쓴 허위 문장은 낮은 값을 받는다.
    """
    q, s = _normalize(quoted), _normalize(source_text)
    if not q or not s:
        return 0.0
    if q in s:
        return 1.0
    return SequenceMatcher(None, q, s).ratio()


def _validate_threshold(value: float, name: str) -> float:
    """임계값은 유한한 [0,1] 실수여야 한다. NaN이면 모든 비교가 통과해버린다(무폴백)."""
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ValidationErr(f"{name} 임계값이 숫자가 아닙니다: {value!r}")
    v = float(value)
    if not math.isfinite(v) or not (0.0 <= v <= 1.0):
        raise ValidationErr(f"{name} 임계값은 [0,1] 범위의 유한한 값이어야 합니다: {value!r}")
    return v

# --- L0 등급 ---------------------------------------------------------------
#: 명시된 출처로 재현 확인이 가능한 주장 → L1 적용
GRADE_VERIFIABLE = "verifiable"
#: 사후 관측 가능한 결과가 있는 주장(반품률 등) → L1 통과 후 결과 대기(L4는 미구현)
GRADE_OUTCOME_LINKED = "outcome_linked"
#: 객관 검증 불가(취향·전망) → 사실성 기준 정산 대상에서 제외
GRADE_OPINION = "opinion"
GRADES = (GRADE_VERIFIABLE, GRADE_OUTCOME_LINKED, GRADE_OPINION)

# --- L1 결과 상태 ----------------------------------------------------------
#: L1 3검사 통과. "사실"이 아니라 "근거가 있고 지지되며 새롭다"는 뜻.
STATUS_GROUNDED = "grounded"
#: L1 미통과 → 정산 대상 아님
STATUS_REJECTED = "rejected"
#: L1은 통과했으나 사후 결과를 기다려야 함(outcome_linked)
STATUS_AWAITING_OUTCOME = "awaiting_outcome"
#: 등급상 사실성 정산 대상이 아님(opinion)
STATUS_NOT_SETTLEABLE = "not_settleable"

# 반려 사유(고정 코드 — 자유 서술로 흘리지 않는다)
REASON_NO_EVIDENCE = "no_evidence"
REASON_UNSUPPORTED = "unsupported"
#: 인용문이 우리 색인의 원문과 일치하지 않음(외부 원본의 진위와는 무관)
REASON_CITATION_MISMATCH = "citation_mismatch"
REASON_DUPLICATE = "duplicate"


@runtime_checkable
class SupportCheckerPort(Protocol):
    """근거→주장 함의 판정 포트. 구현: `app.application.self_verify.SelfVerify`."""

    def __call__(self, question: str, draft: str, evidence: list[str]):  # -> CheckedAnswer
        ...


@dataclass(frozen=True)
class Submission:
    """Provider가 제출한 답변 1건."""

    bounty_question: str
    answer: str
    evidence: list[Evidence]
    provider_id: str


@dataclass(frozen=True)
class CheckOutcome:
    """개별 검사 결과. 통과 여부와 관측용 상세를 남긴다."""

    name: str
    passed: bool
    detail: str = ""


@dataclass(frozen=True)
class L1Result:
    """L1 종합 결과.

    status가 `grounded`여도 **사실성 보증이 아니다** — 근거성·재현성·중복성만 확인했다.
    """

    status: str
    grade: str
    checks: list[CheckOutcome] = field(default_factory=list)
    reason: str = ""

    @property
    def settleable(self) -> bool:
        """정산 단계(L2 escrow)로 넘길 수 있는가."""
        return self.status == STATUS_GROUNDED


def validate_grade(grade: str) -> str:
    """등급 검증. 알 수 없는 등급을 임의 기본값으로 때우지 않는다(무폴백)."""
    if grade not in GRADES:
        raise ValidationErr(f"알 수 없는 바운티 등급입니다: {grade!r} (허용: {list(GRADES)})")
    return grade


class VerifyBountySubmission:
    """L1 기계 검증 유스케이스.

    검사 순서는 **싼 것 → 비싼 것**이다: 근거 유무(무료) → 재현성(검색) → 중복성(검색)
    → 정합성(LLM 호출). 앞에서 걸리면 뒤 단계를 돌리지 않는다.

    `retriever`는 재현성·중복성 확인에 재사용한다(새 인프라를 만들지 않는다).
    `support_check`는 SelfVerify를 그대로 주입한다(같은 모델의 자기 점검 — 독립 검증 아님).
    """

    def __init__(
        self,
        retriever: RetrieverPort,
        support_check: SupportCheckerPort,
        *,
        citation_match_threshold: float,
        duplicate_threshold: float,
        max_evidence: int = 20,
        max_evidence_chars: int = 4000,
    ) -> None:
        self._retriever = retriever
        self._support = support_check
        self._citation_threshold = _validate_threshold(citation_match_threshold, "citation_match")
        self._duplicate_threshold = _validate_threshold(duplicate_threshold, "duplicate")
        if max_evidence < 1 or max_evidence_chars < 1:
            raise ValidationErr("근거 개수·길이 상한은 1 이상이어야 합니다.")
        self._max_evidence = max_evidence
        self._max_evidence_chars = max_evidence_chars

    # --- 개별 검사 ---------------------------------------------------------
    def _check_citation_matches_corpus(self, evidence: list[Evidence]) -> CheckOutcome:
        """인용문이 **우리 색인 코퍼스의 실제 청크와 문자 수준으로 일치**하는지 대조한다.

        ★ 이 검사가 확인하는 것과 확인하지 못하는 것(Codex 지적 반영):
          - 확인한다: 인용문이 그 출처의 실제 청크 본문과 (부분문자열 또는 높은 문자 유사도로)
            일치하는가, locator를 제시했다면 그것도 일치하는가.
          - 확인하지 **못한다**: 그 원본 문서 자체가 진짜인지, 내용이 참인지.
            우리는 외부 원문을 가져오지 않는다 — 대조 대상은 **우리 색인**이다.

        이전 구현은 임베딩 유사도만 봐서, 실제 문서명 + 원문과 의미가 비슷한 **허위 문장**이
        통과할 수 있었다. 그래서 의미 유사도가 아니라 **원문 대조**로 바꿨다.
        """
        for ev in evidence:
            hits = [h for h in self._retriever.search(ev.content, source=ev.source)
                    if h.source == ev.source]
            if not hits:
                return CheckOutcome(
                    "citation_match", False, f"출처 '{ev.source}'를 색인에서 찾지 못함"
                )
            best_ratio = max(_text_match_ratio(ev.content, h.content) for h in hits)
            if best_ratio < self._citation_threshold:
                return CheckOutcome(
                    "citation_match", False,
                    f"출처 '{ev.source}'의 원문과 인용문이 불일치(문자 일치도 {best_ratio:.3f})",
                )
            # locator를 제시했다면 그것도 색인의 locator와 맞아야 한다(페이지 위조 방지).
            if ev.locator:
                if not any(h.locator == ev.locator for h in hits):
                    return CheckOutcome(
                        "citation_match", False,
                        f"출처 '{ev.source}'에 locator '{ev.locator}'가 존재하지 않음",
                    )
        return CheckOutcome("citation_match", True, f"{len(evidence)}건 원문 대조 통과")

    def _check_duplicate(self, answer: str) -> CheckOutcome:
        """이미 아는 지식과 중복인지 임베딩 유사도로 확인한다."""
        hits = self._retriever.search(answer)
        best = max((h.score for h in hits), default=0.0)
        if best >= self._duplicate_threshold:
            return CheckOutcome("novel", False, f"기존 지식과 중복(유사도 {best:.3f})")
        return CheckOutcome("novel", True, f"최대 유사도 {best:.3f}")

    def _check_supported(self, sub: Submission) -> CheckOutcome:
        """근거가 답변의 주장을 지지하는지(함의) 판정 — SelfVerify 재사용."""
        checked = self._support(
            sub.bounty_question, sub.answer, [e.content for e in sub.evidence]
        )
        chk = checked.support_check
        return CheckOutcome(
            "supported", chk.is_supported,
            f"checked_by={chk.checked_by}, model={chk.model}",
        )

    # --- 진입점 ------------------------------------------------------------
    def __call__(self, sub: Submission, grade: str) -> L1Result:
        grade = validate_grade(grade)

        if not sub.answer or not sub.answer.strip():
            # 빈 제출은 검사 대상이 아니라 잘못된 요청이다.
            raise ValidationErr("제출 답변이 비어 있습니다.")
        if not sub.provider_id or not sub.provider_id.strip():
            raise ValidationErr("provider_id가 비어 있습니다.")

        # opinion은 사실성 기준으로 정산하지 않는다 — L1을 적용하는 것 자체가 월권이다.
        if grade == GRADE_OPINION:
            return L1Result(
                STATUS_NOT_SETTLEABLE, grade,
                [CheckOutcome("grade_gate", True, "opinion 등급은 사실성 정산 대상이 아님")],
                reason="opinion_grade",
            )

        checks: list[CheckOutcome] = []

        # 1) 근거 제시 여부 — 없으면 지지될 수 없다(LLM을 부를 필요도 없음).
        if not sub.evidence:
            checks.append(CheckOutcome("has_evidence", False, "근거가 제시되지 않음"))
            return L1Result(STATUS_REJECTED, grade, checks, reason=REASON_NO_EVIDENCE)
        # 근거 개수·길이 상한 — 무제한 입력으로 검색·LLM 연산을 유발하지 못하게 한다.
        if len(sub.evidence) > self._max_evidence:
            raise ValidationErr(f"근거는 최대 {self._max_evidence}건까지 허용됩니다.")
        for ev in sub.evidence:
            if not ev.content or not ev.content.strip():
                raise ValidationErr("빈 근거가 포함돼 있습니다.")
            if not ev.source or not ev.source.strip():
                raise ValidationErr("출처가 비어 있는 근거가 있습니다.")
            if len(ev.content) > self._max_evidence_chars:
                raise ValidationErr(f"근거 1건은 최대 {self._max_evidence_chars}자까지 허용됩니다.")
        checks.append(CheckOutcome("has_evidence", True, f"{len(sub.evidence)}건"))

        # 2) 인용 대조(원문 일치) — 의미 유사도가 아니라 문자 대조
        cite = self._check_citation_matches_corpus(sub.evidence)
        checks.append(cite)
        if not cite.passed:
            return L1Result(STATUS_REJECTED, grade, checks, reason=REASON_CITATION_MISMATCH)

        # 3) 중복성
        dup = self._check_duplicate(sub.answer)
        checks.append(dup)
        if not dup.passed:
            return L1Result(STATUS_REJECTED, grade, checks, reason=REASON_DUPLICATE)

        # 4) 정합성(LLM) — 가장 비싸므로 마지막
        sup = self._check_supported(sub)
        checks.append(sup)
        if not sup.passed:
            return L1Result(STATUS_REJECTED, grade, checks, reason=REASON_UNSUPPORTED)

        status = (
            STATUS_AWAITING_OUTCOME if grade == GRADE_OUTCOME_LINKED else STATUS_GROUNDED
        )
        return L1Result(status, grade, checks)
