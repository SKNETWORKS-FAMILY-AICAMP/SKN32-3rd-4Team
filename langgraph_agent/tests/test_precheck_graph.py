"""
tests/test_precheck_graph.py

역할:
    graph/precheck_graph.py의 PrecheckGraph 오케스트레이션(정상 흐름, 각
    abstain 사유코드, 1:N 되묻기, per_code 판정, citation_guard 기반 인용검증
    재시도/기권)을 검증한다.
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
from graph.precheck_graph import (
    MAX_RETRY,
    PrecheckGraph,
    parse_explain_output,
    verify_citations_in_message,
)


def _clause(article_no="제9조", quote="면책 조항 원문"):
    return Citation(article_no=article_no, article_title="면책조항", quote=quote)


def _per_code(verdict=Verdict.NEEDS_DOCUMENTS, codes=("F32",)):
    return tuple(PerCodeVerdict(code=c, verdict=verdict) for c in codes)


def _make_graph(**overrides):
    defaults = dict(
        resolve_policy=lambda body: PolicyResolution(generation="3세대"),
        gate_document=lambda generation: True,
        retrieve=lambda body, generation: (_clause(),),
        assess=lambda body, clauses: _per_code(),
        # 첫 번째(유일한) 근거는 항상 E001 손잡이를 받는다(citation_guard.make_handles 순서 보장).
        explain=lambda body, per_code, clauses: (f"{clauses[0].article_no}에 따르면...", ("E001",)),
        verify=lambda message, cited_handles, clauses: (True, None, ""),
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

    def verify(message, cited_handles, clauses):
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
        verify=lambda message, cited_handles, clauses: (False, ReasonCode.CITATION_UNVERIFIED, "계속 오류"),
        retarget=lambda body, clauses: (_clause(),),
    )
    outcome, state = graph.invoke(_body())

    assert outcome.abstained is True
    assert outcome.reason_code == ReasonCode.CITATION_UNVERIFIED
    assert state.retries <= MAX_RETRY


def test_same_reason_does_not_retry_twice():
    """같은 사유로 두 번 돌지 않는다 -- retarget이 매번 같은 근거를 주는 상황."""
    graph = _make_graph(
        verify=lambda message, cited_handles, clauses: (False, ReasonCode.CITATION_UNVERIFIED, "동일 오류"),
        retarget=lambda body, clauses: clauses,  # 근거가 안 바뀜
    )
    outcome, state = graph.invoke(_body())

    assert outcome.abstained is True
    assert state.retries <= 1  # 같은 사유 반복이라 1번 만에 기권해야 함


def test_citation_retry_without_retarget_reexplains_with_same_clauses():
    """retarget 없이(build()의 기본 경로) 검증 실패 시, 조항을 다시 검색하지
    않고 같은(세대 필터 통과한) clauses로 explain()만 다시 부른다."""
    seen_clauses = []
    calls = {"verify": 0}

    def explain(body, per_code, clauses):
        seen_clauses.append(clauses)
        return (f"{clauses[0].article_no}에 따르면...", ("E001",))

    def verify(message, cited_handles, clauses):
        calls["verify"] += 1
        if calls["verify"] == 1:
            return False, ReasonCode.CITATION_UNVERIFIED, "인용 표기 누락"
        return True, None, ""

    graph = _make_graph(explain=explain, verify=verify)
    outcome, state = graph.invoke(_body())

    assert outcome.abstained is False
    assert state.retries == 1
    # explain이 두 번 불렸고(최초 + 재시도), 두 번 다 같은 근거(제9조)로 불렸다.
    assert len(seen_clauses) == 2
    assert seen_clauses[0][0].article_no == seen_clauses[1][0].article_no == "제9조"


def test_citation_retry_without_retarget_exhausted_abstains():
    graph = _make_graph(
        verify=lambda message, cited_handles, clauses: (False, ReasonCode.CITATION_UNVERIFIED, "계속 오류"),
    )
    outcome, state = graph.invoke(_body())

    assert outcome.abstained is True
    assert outcome.reason_code == ReasonCode.CITATION_UNVERIFIED
    assert state.retries <= MAX_RETRY


# ── citation_guard 기반 인용검증 (verify_citations_in_message) ──────────────


def test_verify_citations_catches_hallucinated_handle():
    """진짜 근거는 E001 하나뿐인데 존재하지 않는 E999도 같이 인용하면 실패해야 한다."""
    clauses = (_clause(article_no="제9조"),)
    ok, code, reason = verify_citations_in_message(
        "제9조에 따르면 면책됩니다 [E001][E999]", ("E001", "E999"), clauses
    )

    assert ok is False
    assert code == ReasonCode.CITATION_UNVERIFIED
    assert "E999" in reason


def test_verify_citations_passes_when_all_cited_are_valid():
    clauses = (_clause(article_no="제9조", quote="면책 조항 원문"),)
    ok, code, _ = verify_citations_in_message("면책 조항 원문에 따르면 대상입니다 [E001]", ("E001",), clauses)

    assert ok is True
    assert code is None


def test_verify_citations_fails_when_no_citation_present():
    clauses = (_clause(article_no="제9조"),)
    ok, code, _ = verify_citations_in_message("보장되지 않는 것으로 보입니다.", (), clauses)

    assert ok is False
    assert code == ReasonCode.CITATION_UNVERIFIED


def test_verify_citations_fails_on_undeclared_mention():
    """본문에 "제9조"를 언급했지만 인용(cited_handles)으로 선언하지 않으면 실패해야 한다
    (citation_guard의 undeclared_mentions 체크 -- 인용검증 우회 방지)."""
    clauses = (_clause(article_no="제9조", quote="면책 조항 원문"),)
    ok, code, _ = verify_citations_in_message(
        "제9조에 따르면 면책됩니다 [E001]", (), clauses  # 인용 선언은 비어있음
    )

    assert ok is False
    assert code == ReasonCode.CITATION_UNVERIFIED


def test_verify_citations_does_not_check_quote_content_yet():
    """알려진 한계: quotes를 검증기에 안 넘기므로, 손잡이만 맞으면 답변 내용이
    조항과 무관해도 통과한다 -- explain()이 LLM한테서 실제 인용문을 따로 뽑아
    quotes로 넘기기 전까지는 이 검사가 없다는 걸 명시하는 회귀 방지 테스트."""
    clauses = (_clause(article_no="제9조", quote="완전히 다른 원문 내용"),)
    ok, _, _ = verify_citations_in_message("전혀 관련 없는 답변입니다 [E001]", ("E001",), clauses)

    assert ok is True  # 지금은 통과함 -- quote 내용 대조는 아직 미구현


def test_verify_citations_no_clauses_always_passes():
    """근거가 아예 없는 상황(abstain 경로)에서는 검증할 것도 없다."""
    ok, code, _ = verify_citations_in_message("아무 텍스트", (), ())

    assert ok is True
    assert code is None


# ── explain 출력 파싱 ────────────────────────────────────────────────────


def test_parse_explain_output_splits_message_and_citations():
    raw = "답변: 제9조에 따르면 면책됩니다 [E001]\n인용: E001"
    message, cited = parse_explain_output(raw)

    assert "제9조" in message
    assert "인용:" not in message
    assert cited == ("E001",)


def test_parse_explain_output_multiple_handles():
    raw = "답변: 여러 조항에 근거합니다\n인용: E001, E002"
    _, cited = parse_explain_output(raw)

    assert cited == ("E001", "E002")


def test_parse_explain_output_no_citation_line_means_no_citations():
    message, cited = parse_explain_output("그냥 설명만 있는 문장")

    assert cited == ()
