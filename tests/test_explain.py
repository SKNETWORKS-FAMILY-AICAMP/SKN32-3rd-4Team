"""app/core/usecases/precheck.py::explain() -- 규칙엔진 결과에 LLM 설명을
붙이되 verdict는 바꾸지 않는지 확인한다."""

from app.core.domain.insurance import Verdict
from app.core.domain.precheck_result import (
    CitationRef,
    CodeVerdict,
    PrecheckOutcome,
    ReasonCode,
)
from app.core.usecases.precheck import explain, parse_explain_output


class _FakeLlm:
    def __init__(self, response: str):
        self._response = response
        self.prompts: list[str] = []

    def complete(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return self._response


def _outcome_with_citation(**overrides):
    base = dict(
        verdict=Verdict.UNLIKELY,
        abstained=False,
        reason_code=ReasonCode.EXCLUDED_BY_CLAUSE,
        per_code=[
            CodeVerdict(code="F32", verdict=Verdict.UNLIKELY, reason_code=ReasonCode.EXCLUDED_BY_CLAUSE)
        ],
        citations=[
            CitationRef(clause_id="doc1#4", qualified_no="제4조", quote="정신질환은 보상하지 않습니다.")
        ],
    )
    base.update(overrides)
    return PrecheckOutcome(**base)


def test_기권한_결과는_LLM을_안_부른다():
    outcome = _outcome_with_citation(abstained=True, verdict=Verdict.NEEDS_EXPERT, citations=[])
    llm = _FakeLlm("아무 응답")
    result = explain(outcome, llm=llm)
    assert result is outcome
    assert llm.prompts == []


def test_근거가_없으면_LLM을_안_부른다():
    outcome = _outcome_with_citation(citations=[])
    llm = _FakeLlm("아무 응답")
    result = explain(outcome, llm=llm)
    assert result is outcome
    assert llm.prompts == []


def test_정상_케이스는_LLM을_불러서_message와_cited_handles를_채운다():
    outcome = _outcome_with_citation()
    llm = _FakeLlm("답변: 제4조에 따라 면책입니다 [E001]\n인용: E001")
    result = explain(outcome, llm=llm)

    assert result.message == "제4조에 따라 면책입니다 [E001]"
    assert result.cited_handles == ("E001",)
    #: ★verdict는 바뀌지 않는다 -- LLM이 판정을 재해석하면 안 된다.
    assert result.verdict is Verdict.UNLIKELY
    assert result.reason_code is ReasonCode.EXCLUDED_BY_CLAUSE
    assert len(llm.prompts) == 1
    assert "E001" in llm.prompts[0]
    assert "제4조" in llm.prompts[0]


def test_프롬프트에_이미_확정된_판정결과가_들어간다():
    """★LLM에게 판정을 맡기지 않는다는 걸 프롬프트 자체로 강제한다."""
    outcome = _outcome_with_citation()
    llm = _FakeLlm("답변: 설명 [E001]\n인용: E001")
    explain(outcome, llm=llm)

    assert "이미 확정됨" in llm.prompts[0]
    assert "F32: unlikely" in llm.prompts[0]


def test_인용_줄이_없으면_손잡이가_빈다():
    outcome = _outcome_with_citation()
    llm = _FakeLlm("그냥 설명만 있는 문장, 인용 표시 없음")
    result = explain(outcome, llm=llm)
    assert result.cited_handles == ()


class _BoomingLlm:
    def complete(self, prompt: str) -> str:
        raise TimeoutError("LLM 호출 타임아웃 (20.0초 초과)")


def test_LLM_호출이_실패해도_규칙엔진_판정은_살아있다():
    """★LLM 가용성이 판정 자체를 막으면 안 된다 -- verdict는 이미 확정돼 있다."""
    outcome = _outcome_with_citation()
    result = explain(outcome, llm=_BoomingLlm())
    assert result is outcome
    assert result.verdict is Verdict.UNLIKELY
    assert result.message == ""
    assert result.cited_handles == ()


# ── parse_explain_output ─────────────────────────────────────────────────


def test_parse_explain_output_기본_분리():
    message, cited = parse_explain_output("답변: 제9조에 따르면 면책됩니다 [E001]\n인용: E001")
    assert "제9조" in message
    assert "인용:" not in message
    assert cited == ("E001",)


def test_parse_explain_output_복수_손잡이():
    _, cited = parse_explain_output("답변: 여러 조항에 근거합니다\n인용: E001, E002")
    assert cited == ("E001", "E002")


def test_parse_explain_output_인용_줄_없으면_빈_튜플():
    message, cited = parse_explain_output("그냥 설명만 있는 문장")
    assert cited == ()
    assert message == "그냥 설명만 있는 문장"
