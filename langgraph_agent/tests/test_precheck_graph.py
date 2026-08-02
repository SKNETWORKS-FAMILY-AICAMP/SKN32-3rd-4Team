"""
tests/test_precheck_graph.py

역할:
    graph/precheck_graph.py의 PrecheckGraph 오케스트레이션(정상 흐름, 각
    abstain 사유코드, 1:N 되묻기, per_code 판정, verify_citations 재시도/기권)을
    검증한다.
"""

from graph.precheck_domain import (
    Citation,
    PerCodeVerdict,
    PolicyResolution,
    PrecheckInput,
    ProductCandidate,
    ReasonCode,
    Verdict,
)
from graph.precheck_graph import MAX_RETRY, PrecheckGraph, verify_citations_in_message


def _clause(article_no="제9조", quote="..."):
    return Citation(article_no=article_no, article_title="면책조항", quote=quote)


def _per_code(verdict=Verdict.NEEDS_DOCUMENTS, codes=("F32",)):
    return tuple(PerCodeVerdict(code=c, verdict=verdict) for c in codes)


def _make_graph(**overrides):
    defaults = dict(
        resolve_policy=lambda body: PolicyResolution(generation="3세대"),
        gate_document=lambda generation: True,
        retrieve=lambda body, generation: (_clause(),),
        assess=lambda body, clauses: _per_code(),
        explain=lambda body, per_code, clauses: f"{clauses[0].article_no}에 따르면...",
        verify=lambda message, clauses: (True, None, ""),
    )
    defaults.update(overrides)
    return PrecheckGraph(**defaults)


def _body(**overrides):
    defaults = dict(query="보장되나요?", kcd_codes=("F32",), insurer="테스트생명", enrolled_on="2020-01-01")
    defaults.update(overrides)
    return PrecheckInput(**defaults)


def test_success_path():
    graph = _make_graph()
    outcome, state = graph.invoke(_body())

    assert outcome.abstained is False
    assert outcome.verdict == Verdict.NEEDS_DOCUMENTS
    assert outcome.per_code == _per_code()
    assert "제9조" in outcome.message
    assert state.kcd_hashes and state.kcd_hashes[0] != "F32"  # 원문 그대로 저장 안 함


def test_resolve_policy_failure_abstains_not_resolved():
    graph = _make_graph(resolve_policy=lambda body: PolicyResolution(reason_code=ReasonCode.NOT_RESOLVED))
    outcome, _ = graph.invoke(_body())

    assert outcome.abstained is True
    assert outcome.reason_code == ReasonCode.NOT_RESOLVED


def test_resolve_policy_ambiguous_returns_candidates():
    candidates = (
        ProductCandidate(product_name="일반실손", product_line="general", generation="3세대"),
        ProductCandidate(product_name="노후실손", product_line="senior", generation="3세대"),
    )
    graph = _make_graph(
        resolve_policy=lambda body: PolicyResolution(
            candidates=candidates, reason_code=ReasonCode.AMBIGUOUS_PRODUCT_LINE
        )
    )
    outcome, _ = graph.invoke(_body())

    assert outcome.abstained is True
    assert outcome.reason_code == ReasonCode.AMBIGUOUS_PRODUCT_LINE
    assert outcome.candidates == candidates


def test_resolve_policy_candidates_forces_ambiguous_reason_even_if_unset():
    """reason_code를 안 채워도 candidates가 있으면 AMBIGUOUS_PRODUCT_LINE으로 봐야 한다."""
    candidates = (ProductCandidate(product_name="일반실손", product_line="general", generation="3세대"),)
    graph = _make_graph(resolve_policy=lambda body: PolicyResolution(candidates=candidates))
    outcome, _ = graph.invoke(_body())

    assert outcome.reason_code == ReasonCode.AMBIGUOUS_PRODUCT_LINE
    assert outcome.candidates == candidates


def test_gate_document_failure_abstains_document_not_reliable():
    graph = _make_graph(gate_document=lambda generation: False)
    outcome, _ = graph.invoke(_body())

    assert outcome.abstained is True
    assert outcome.reason_code == ReasonCode.DOCUMENT_NOT_RELIABLE


def test_no_evidence_abstains():
    graph = _make_graph(retrieve=lambda body, generation: ())
    outcome, _ = graph.invoke(_body())

    assert outcome.abstained is True
    assert outcome.reason_code == ReasonCode.NO_EVIDENCE


def test_multiple_kcd_codes_get_individual_verdicts():
    per_code = (
        PerCodeVerdict(code="F32", verdict=Verdict.NEEDS_DOCUMENTS),
        PerCodeVerdict(code="S72", verdict=Verdict.NEEDS_EXPERT),
    )
    graph = _make_graph(assess=lambda body, clauses: per_code)
    outcome, _ = graph.invoke(_body(kcd_codes=("F32", "S72")))

    assert outcome.per_code == per_code
    # 하나라도 NEEDS_EXPERT면 대표 verdict도 NEEDS_EXPERT (가장 주의 필요한 것 우선)
    assert outcome.verdict == Verdict.NEEDS_EXPERT


def test_citation_retry_then_success_via_retarget():
    calls = {"verify": 0}

    def verify(message, clauses):
        calls["verify"] += 1
        if calls["verify"] == 1:
            return False, ReasonCode.CITATION_UNVERIFIED, "인용 오류"
        return True, None, ""

    graph = _make_graph(
        verify=verify,
        retarget=lambda body, clauses: (_clause(article_no="제10조"),),
    )
    outcome, state = graph.invoke(_body())

    assert outcome.abstained is False
    assert state.retries == 1


def test_citation_retry_exhausted_abstains():
    graph = _make_graph(
        verify=lambda message, clauses: (False, ReasonCode.CITATION_UNVERIFIED, "계속 오류"),
        retarget=lambda body, clauses: (_clause(),),
    )
    outcome, state = graph.invoke(_body())

    assert outcome.abstained is True
    assert outcome.reason_code == ReasonCode.CITATION_UNVERIFIED
    assert state.retries <= MAX_RETRY


def test_same_reason_does_not_retry_twice():
    """같은 사유로 두 번 돌지 않는다 -- retarget이 매번 같은 근거를 주는 상황."""
    graph = _make_graph(
        verify=lambda message, clauses: (False, ReasonCode.CITATION_UNVERIFIED, "동일 오류"),
        retarget=lambda body, clauses: clauses,  # 근거가 안 바뀜
    )
    outcome, state = graph.invoke(_body())

    assert outcome.abstained is True
    assert state.retries <= 1  # 같은 사유 반복이라 1번 만에 기권해야 함


def test_verify_citations_catches_hallucinated_article():
    """실제 검색된 건 제9조뿐인데 설명문이 제15조도 인용하면 실패해야 한다."""
    clauses = (_clause(article_no="제9조"),)
    ok, code, _ = verify_citations_in_message("제9조에 따르면... 그리고 제15조도 관련 있습니다", clauses)

    assert ok is False
    assert code == ReasonCode.CITATION_UNVERIFIED


def test_verify_citations_passes_when_all_cited_are_valid():
    clauses = (_clause(article_no="제9조"),)
    ok, code, _ = verify_citations_in_message("제9조에 따르면 면책 대상입니다.", clauses)

    assert ok is True
    assert code is None


def test_verify_citations_fails_when_no_citation_present():
    clauses = (_clause(article_no="제9조"),)
    ok, code, _ = verify_citations_in_message("보장되지 않는 것으로 보입니다.", clauses)

    assert ok is False
    assert code == ReasonCode.CITATION_UNVERIFIED
