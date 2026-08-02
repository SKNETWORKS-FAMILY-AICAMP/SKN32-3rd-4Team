"""판정 흐름(LangGraph) — 계약 §1 의 경계가 지켜지는가.

★이 테스트가 지키는 것은 **흐름의 경계**다.
  "그래프가 판정을 바꾸지 않는다" · "재시도는 2회를 넘지 않는다" ·
  "상태에 질병기호 원문이 없다" · "두 실행기의 흐름이 같다".
"""

from __future__ import annotations

import pytest

from app.core.domain.precheck_result import (
    PrecheckInput,
    PrecheckOutcome,
    ReasonCode,
    Verdict,
)
from app.workflow.precheck_graph import MAX_RETRY, GraphState, PrecheckGraph


def _body(codes=("F32",)) -> PrecheckInput:
    return PrecheckInput(insurer="가보험", enrolled_on="20200101", kcd_codes=tuple(codes))


def _outcome(verdict=Verdict.LIKELY_COVERED, **kw) -> PrecheckOutcome:
    return PrecheckOutcome(
        verdict=verdict,
        abstained=kw.pop("abstained", False),
        message=kw.pop("message", "보장 조항 근거가 있습니다."),
        **kw,
    )


def _graph(*, verify, retarget=None, run=None) -> PrecheckGraph:
    return PrecheckGraph(
        run_precheck=run or (lambda b: _outcome()),
        verify=verify,
        retarget=retarget,
    )


def test_통과하면_판정을_그대로_나른다():
    g = _graph(verify=lambda o: (True, None, ""))
    out, st = g.invoke(_body())
    #: ★그래프가 verdict 를 바꾸지 않는다. 규칙엔진이 정한 것 그대로다.
    assert out.verdict is Verdict.LIKELY_COVERED
    assert out.abstained is False
    assert st.done and st.retries == 0


def test_상태에_질병기호_원문이_없다():
    """★질병기호는 민감정보다. 상태는 로그·트레이스로 새어 나갈 수 있다."""
    g = _graph(verify=lambda o: (True, None, ""))
    _, st = g.invoke(_body(codes=("F32", "S82")))
    dumped = repr(st)
    assert "F32" not in dumped and "S82" not in dumped
    assert len(st.kcd_hashes) == 2
    assert all(len(h) == 16 for h in st.kcd_hashes)


def test_검증_실패하고_되돌아갈_수단이_없으면_기권한다():
    g = _graph(verify=lambda o: (False, ReasonCode.CITATION_UNVERIFIED, "인용 불일치"))
    out, st = g.invoke(_body())
    assert out.verdict is Verdict.NEEDS_EXPERT
    assert out.abstained is True
    assert out.reason_code is ReasonCode.CITATION_UNVERIFIED
    #: ★검증에 실패한 근거를 남기지 않는다. 남기면 클라이언트가 그걸 읽고 판단한다.
    assert out.citations == () and out.per_code == ()


def test_재시도는_2회를_넘지_않는다():
    """★계약 §1. 그때까지 안 되면 근거가 없는 것이다."""
    calls = {"n": 0}

    def verify(o):
        calls["n"] += 1
        #: 매번 **다른** 이유로 실패시켜 "같은 이유 차단"에 걸리지 않게 한다.
        code = (
            ReasonCode.CITATION_UNVERIFIED
            if calls["n"] % 2
            else ReasonCode.AMBIGUOUS_CITATION
        )
        return False, code, f"실패 {calls['n']}"

    g = _graph(verify=verify, retarget=lambda b, o: o)
    out, st = g.invoke(_body())
    assert st.retries <= MAX_RETRY
    assert out.abstained is True
    assert out.reason_code is ReasonCode.CITATION_UNVERIFIED


def test_같은_이유로는_다시_돌지_않는다():
    """돌아도 같은 결과가 나온다. 시간만 쓴다."""
    g = _graph(
        verify=lambda o: (False, ReasonCode.CITATION_UNVERIFIED, "같은 이유"),
        retarget=lambda b, o: o,
    )
    out, st = g.invoke(_body())
    assert st.retries == 1
    assert st.retry_reasons == ["citation_unverified"]
    assert out.abstained is True


def test_표적검색으로_근거를_보강하면_통과한다():
    state = {"tries": 0}

    def verify(o):
        state["tries"] += 1
        return (True, None, "") if state["tries"] > 1 else (
            False, ReasonCode.NO_EVIDENCE, "근거 부족"
        )

    def retarget(b, o):
        #: ★여기서도 verdict 를 바꾸지 않는다. 근거만 더 모은다.
        return o

    g = _graph(verify=verify, retarget=retarget)
    out, st = g.invoke(_body())
    assert out.verdict is Verdict.LIKELY_COVERED
    assert out.abstained is False
    assert st.retries == 1


def test_규칙엔진이_기권했으면_그대로_둔다():
    """★그래프가 기권을 뒤집지 않는다."""
    abstained = _outcome(
        verdict=Verdict.NEEDS_EXPERT,
        abstained=True,
        reason_code=ReasonCode.NO_VERSION_AT_DATE,
        message="해당 시점의 약관을 찾지 못했습니다.",
    )
    g = _graph(run=lambda b: abstained, verify=lambda o: (True, None, ""))
    out, _ = g.invoke(_body())
    assert out.verdict is Verdict.NEEDS_EXPERT
    assert out.reason_code is ReasonCode.NO_VERSION_AT_DATE


def test_흐름이_계약_순서를_따른다():
    g = _graph(verify=lambda o: (True, None, ""))
    _, st = g.invoke(_body())
    assert st.trail == [
        "normalize",
        "resolve_policy",
        "gate_document",
        "retrieve",
        "assess",
        "explain",
        "verify_citations",
    ]


def test_무한반복이_구조로_막힌다():
    """★흐름 버그로 끝나지 않으면 서비스가 멈춘다. 이중으로 잠근다."""

    class _NeverDone(PrecheckGraph):
        def verify_citations(self, st: GraphState, body):  # noqa: D102
            st.visit("verify_citations")
            return st  # done 을 영원히 세우지 않는다

    g = _NeverDone(
        run_precheck=lambda b: _outcome(),
        verify=lambda o: (False, ReasonCode.CITATION_UNVERIFIED, ""),
    )
    out, st = g.invoke(_body())
    assert st.done is True
    assert out.abstained is True


# ---------------------------------------------------------------- LangGraph


def test_두_실행기의_흐름이_같다():
    """★`invoke()` 와 LangGraph 가 갈라지면 어느 쪽이 진짜인지 알 수 없다."""
    pytest.importorskip("langgraph")

    g = _graph(verify=lambda o: (True, None, ""))
    body = _body()

    _, seq = g.invoke(body)

    st = GraphState()
    compiled = g.build_langgraph()
    compiled.invoke({"st": st, "body": body})

    assert st.trail == seq.trail
    assert st.done == seq.done
    assert st.retries == seq.retries


def test_langgraph도_재시도_상한을_지킨다():
    pytest.importorskip("langgraph")

    calls = {"n": 0}

    def verify(o):
        calls["n"] += 1
        code = (
            ReasonCode.CITATION_UNVERIFIED
            if calls["n"] % 2
            else ReasonCode.AMBIGUOUS_CITATION
        )
        return False, code, "실패"

    g = _graph(verify=verify, retarget=lambda b, o: o)
    st = GraphState()
    g.build_langgraph().invoke({"st": st, "body": _body()})
    assert st.retries <= MAX_RETRY
    assert st.done is True
