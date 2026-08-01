"""지식 바운티 L0 등급화 + L1 기계 검증 (결정론 — LLM·검색은 Fake).

핵심 검증 관점: 이 계층이 **사실성을 판정하지 않는다**는 것과, 각 검사가 독립적으로
동작해 위조 출처·중복·미지지 제출을 걸러낸다는 것.
"""

from __future__ import annotations

import pytest

from app.application.bounty import (
    GRADE_OPINION,
    GRADE_OUTCOME_LINKED,
    GRADE_VERIFIABLE,
    REASON_DUPLICATE,
    REASON_NO_EVIDENCE,
    REASON_CITATION_MISMATCH,
    REASON_UNSUPPORTED,
    STATUS_AWAITING_OUTCOME,
    STATUS_GROUNDED,
    STATUS_NOT_SETTLEABLE,
    STATUS_REJECTED,
    Submission,
    VerifyBountySubmission,
    validate_grade,
)
from app.application.ports import Evidence
from app.application.self_verify import SUPPORTED, UNSUPPORTED, CheckedAnswer, SupportCheck
from app.core.errors import ValidationErr

_Q = "이 청소기는 원룸에서 쓸 만한가요?"
_ANS = "CleanX는 흡입력 2000Pa로 원룸 청소에 충분합니다."


def _ev(content: str = "CleanX 흡입력 2000Pa", source: str = "manual.pdf") -> Evidence:
    return Evidence(content=content, source=source, locator="p.3", score=0.9, backend="fake")


class FakeRetriever:
    """인용 대조·중복성 검사를 결정론으로 만들기 위한 Fake.

    - `corpus_text`: 그 출처에 실제로 들어 있는 원문(인용 대조의 비교 대상)
    - `corpus_locator`: 색인에 존재하는 locator
    - `duplicate_score`: 답변으로 검색했을 때 기존 지식과의 최대 유사도
    - `source_missing`: True면 그 출처가 색인에 아예 없음
    """

    def __init__(self, corpus_text: str = "CleanX 흡입력 2000Pa", duplicate_score: float = 0.1,
                 corpus_locator: str = "p.3", source_missing: bool = False) -> None:
        self.corpus_text = corpus_text
        self.duplicate_score = duplicate_score
        self.corpus_locator = corpus_locator
        self.source_missing = source_missing

    def search(self, query: str, k: int | None = None, source: str | None = None):
        if source is not None:  # 인용 대조 경로 — 색인의 **실제 원문**을 돌려준다
            if self.source_missing:
                return []
            return [Evidence(self.corpus_text, source, self.corpus_locator, 1.0, "fake")]
        return [Evidence("기존 지식", "kb.pdf", None, self.duplicate_score, "fake")]


def _support(result: str):
    """SelfVerify 자리에 꽂을 Fake — 지정한 판정을 그대로 돌려준다."""

    def _call(question: str, draft: str, evidence: list[str]) -> CheckedAnswer:
        chk = SupportCheck(result, "llm", "fake-model", "테스트")
        return CheckedAnswer(draft if result == SUPPORTED else "차단됨", chk, result != SUPPORTED)

    return _call


def _uc(corpus_text: str = "CleanX 흡입력 2000Pa", duplicate: float = 0.1,
        support: str = SUPPORTED, **kw):
    return VerifyBountySubmission(
        retriever=FakeRetriever(corpus_text, duplicate, **kw),
        support_check=_support(support),
        citation_match_threshold=0.85,
        duplicate_threshold=0.95,
    )


def _sub(evidence=None, answer: str = _ANS) -> Submission:
    return Submission(_Q, answer, evidence if evidence is not None else [_ev()], "provider-1")


# --- L0 등급 --------------------------------------------------------------
def test_unknown_grade_is_rejected_not_defaulted():
    """알 수 없는 등급을 임의 기본값으로 때우지 않는다(무폴백)."""
    for bad in ("verified", "", "VERIFIABLE", None):
        with pytest.raises(ValidationErr):
            validate_grade(bad)


def test_opinion_grade_is_excluded_from_factual_settlement():
    """opinion은 사실성 정산 대상이 아니다 — L1을 적용하는 것 자체가 월권."""
    r = _uc()(_sub(), GRADE_OPINION)
    assert r.status == STATUS_NOT_SETTLEABLE
    assert r.settleable is False


def test_outcome_linked_waits_for_outcome_even_when_l1_passes():
    r = _uc()(_sub(), GRADE_OUTCOME_LINKED)
    assert r.status == STATUS_AWAITING_OUTCOME
    assert r.settleable is False  # 아직 정산 불가


# --- L1 개별 검사 ---------------------------------------------------------
def test_submission_without_evidence_is_rejected_without_calling_llm():
    """근거가 없으면 지지될 수 없다 — LLM을 호출하지 않고 즉시 반려."""

    def _boom(*a, **k):  # 호출되면 실패
        raise AssertionError("근거 없는 제출에 LLM을 호출하면 안 된다")

    uc = VerifyBountySubmission(
        retriever=FakeRetriever(), support_check=_boom,
        citation_match_threshold=0.85, duplicate_threshold=0.95,
    )
    r = uc(_sub(evidence=[]), GRADE_VERIFIABLE)
    assert r.status == STATUS_REJECTED and r.reason == REASON_NO_EVIDENCE


def test_unknown_source_is_rejected():
    """색인에 없는 출처를 인용하면 반려한다."""
    r = _uc(source_missing=True)(_sub(), GRADE_VERIFIABLE)
    assert r.status == STATUS_REJECTED and r.reason == REASON_CITATION_MISMATCH


def test_plausible_but_fabricated_quote_is_rejected():
    """★핵심(Codex 지적): 실제 문서명 + 원문과 '의미만 비슷한' 허위 인용문은 통과하면 안 된다.

    이전 구현은 임베딩 유사도만 봐서 이런 위조가 통과했다. 지금은 문자 대조라 걸린다.
    """
    fake_quote = "CleanX는 흡입력이 매우 뛰어나 어떤 바닥에서도 완벽하게 청소합니다"
    r = _uc(corpus_text="CleanX 흡입력 2000Pa")(
        _sub(evidence=[_ev(content=fake_quote)]), GRADE_VERIFIABLE
    )
    assert r.status == STATUS_REJECTED and r.reason == REASON_CITATION_MISMATCH


def test_exact_and_partial_quote_pass():
    """원문 그대로 또는 부분 인용은 통과한다(정상 인용을 막지 않는다)."""
    corpus = "본 제품 CleanX 흡입력 2000Pa 이며 원룸에 적합하다"
    assert _uc(corpus_text=corpus)(_sub(evidence=[_ev(content=corpus)]), GRADE_VERIFIABLE).status == STATUS_GROUNDED
    assert _uc(corpus_text=corpus)(_sub(evidence=[_ev(content="CleanX 흡입력 2000Pa")]), GRADE_VERIFIABLE).status == STATUS_GROUNDED


def test_forged_locator_is_rejected():
    """본문이 맞아도 존재하지 않는 페이지를 인용하면 반려(페이지 위조 방지)."""
    ev = Evidence("CleanX 흡입력 2000Pa", "manual.pdf", "p.99", 0.9, "fake")
    r = _uc(corpus_locator="p.3")(_sub(evidence=[ev]), GRADE_VERIFIABLE)
    assert r.status == STATUS_REJECTED and r.reason == REASON_CITATION_MISMATCH


def test_invalid_thresholds_are_rejected():
    """NaN·범위 밖 임계값은 즉시 실패한다 — NaN이면 모든 비교가 통과해버린다(Codex 지적)."""
    for bad in (float("nan"), float("inf"), -0.1, 1.5, "0.5", None):
        with pytest.raises(ValidationErr):
            VerifyBountySubmission(
                retriever=FakeRetriever(), support_check=_support(SUPPORTED),
                citation_match_threshold=bad, duplicate_threshold=0.95,
            )


def test_evidence_bounds_enforced():
    """근거 개수·길이 상한과 빈 근거를 무제한 허용하지 않는다."""
    uc = VerifyBountySubmission(
        retriever=FakeRetriever(), support_check=_support(SUPPORTED),
        citation_match_threshold=0.85, duplicate_threshold=0.95,
        max_evidence=2, max_evidence_chars=50,
    )
    with pytest.raises(ValidationErr):
        uc(_sub(evidence=[_ev()] * 3), GRADE_VERIFIABLE)
    with pytest.raises(ValidationErr):
        uc(_sub(evidence=[_ev(content="x" * 51)]), GRADE_VERIFIABLE)
    with pytest.raises(ValidationErr):
        uc(_sub(evidence=[_ev(content="   ")]), GRADE_VERIFIABLE)


def test_duplicate_knowledge_is_rejected():
    r = _uc(duplicate=0.99)(_sub(), GRADE_VERIFIABLE)
    assert r.status == STATUS_REJECTED and r.reason == REASON_DUPLICATE


def test_unsupported_answer_is_rejected():
    """근거는 재현되지만 그 근거가 주장을 지지하지 않으면 반려."""
    r = _uc(support=UNSUPPORTED)(_sub(), GRADE_VERIFIABLE)
    assert r.status == STATUS_REJECTED and r.reason == REASON_UNSUPPORTED


def test_passing_all_checks_yields_grounded_not_verified():
    """통과 상태의 이름은 'grounded'다 — 'verified'(사실 확인)가 아니다."""
    r = _uc()(_sub(), GRADE_VERIFIABLE)
    assert r.status == STATUS_GROUNDED
    assert r.settleable is True
    names = {c.name for c in r.checks}
    assert names == {"has_evidence", "citation_match", "novel", "supported"}


# --- 무폴백·계약 ----------------------------------------------------------
def test_empty_answer_or_provider_raises():
    for bad in ("", "   "):
        with pytest.raises(ValidationErr):
            _uc()(_sub(answer=bad), GRADE_VERIFIABLE)
    with pytest.raises(ValidationErr):
        _uc()(Submission(_Q, _ANS, [_ev()], ""), GRADE_VERIFIABLE)


def test_cheap_checks_run_before_expensive_llm():
    """검사 순서(싼 것 → 비싼 것): 중복이면 LLM을 부르지 않는다."""

    def _boom(*a, **k):
        raise AssertionError("중복 반려인데 LLM을 호출하면 안 된다")

    uc = VerifyBountySubmission(
        retriever=FakeRetriever(duplicate_score=0.99), support_check=_boom,
        citation_match_threshold=0.85, duplicate_threshold=0.95,
    )
    assert uc(_sub(), GRADE_VERIFIABLE).reason == REASON_DUPLICATE


def test_all_bounty_routes_require_admin(client):
    """운영 전용 계약: /grades 포함 **모든** 라우트가 관리자 의존성을 가져야 한다(Codex 지적)."""
    from app.auth.roles import require_admin
    from app.routers.bounty import router

    assert router.dependencies, "바운티 라우터에 전역 의존성이 없습니다"
    assert require_admin in [d.dependency for d in router.dependencies]
    assert client.get("/api/bounty/grades").status_code == 401
    assert client.get("/api/bounty/open").status_code == 401
    r = client.post(
        "/api/bounty/submit",
        json={"question": "q", "answer": "a", "provider_id": "p", "grade": "verifiable"},
    )
    assert r.status_code == 401


def test_bounty_is_ops_only_not_on_customer_port():
    """바운티는 운영 표면 — 고객 공개 포트에는 물리적으로 없어야(404) 한다."""
    from fastapi.testclient import TestClient

    from app.main import admin_app, customer_app

    assert TestClient(customer_app).get("/api/bounty/grades").status_code == 404
    assert TestClient(admin_app).get("/api/bounty/grades").status_code == 401  # 존재하되 인증 필요


def test_module_never_claims_factuality():
    """이 계층이 사실성 판정을 하지 않음을 정적으로 확인(설계 계약 가드레일)."""
    import pathlib

    src = (pathlib.Path(__file__).resolve().parents[1] / "app" / "application" / "bounty.py").read_text(
        encoding="utf-8"
    )
    # 통과 상태를 'verified'로 부르지 않는다(과신 유발 방지).
    assert 'STATUS_GROUNDED = "grounded"' in src
    assert '"verified"' not in src
