"""보장 사전판정 흐름 — LangGraph.

계약: `docs/handoff/06_계약_Agent.md` §1

★계약서는 이 파일을 `app/insurance/graph.py` 로 적어 두었지만 **거기 두지 않는다.**
  `ARCH-003` 이 `app/core/{domain,ports,usecases}` 밖의 도메인 패키지를 막는다.
  앞서 `app/insurance/` 가 core 를 복제하다가 정리된 자리다.
  그래프는 도메인이 아니라 **오케스트레이션**이므로 바깥 계층에 둔다 —
  같은 폴더에 `ticket_graph.py` 선례가 있다.

```
정규화 → resolve_policy → gate_document → retrieve → assess → explain
                                                       ↓
                                            verify_citations ★재시도 지점
                                              ├ 통과            → 완료
                                              ├ 조항번호 오류   → 설명문만 1회 수정
                                              ├ 근거 부족       → 표적 검색 1회
                                              └ 재시도 초과     → 기권(CITATION_UNVERIFIED)
```

★**이 그래프는 도메인 판단을 하지 않는다.**

    `verdict` 를 여기서 바꾸지 않는다. 규칙엔진이 정한 것을 **그대로 나른다.**
    노드를 잇고, 분기하고, 재시도를 통제하는 것이 전부다.
    여기서 판단을 시작하면 규칙엔진·인용검증을 우회한 답이 나간다.

★**자율 ReAct 루프를 만들지 않는다.**

    언제 끝날지 모르고 감사가 안 된다. 노드와 분기를 **미리 다 적어 둔다.**
    재시도는 **2회를 넘지 않는다** — 그때까지 안 되면 근거가 없는 것이다.

★**상태에 원문 개인정보를 담지 않는다.**

    질병기호는 민감정보다. 상태에는 **해시**로 넣고, 원문은 입력 객체 안에만 둔다.
    상태는 로그·트레이스로 새어 나갈 수 있다.

★**LangGraph 가 없어도 돈다.**

    저장소에 `langgraph` 가 고정돼 있지만, 없는 환경에서 판정이 통째로 죽으면 안 된다.
    같은 노드·같은 분기를 그대로 실행하는 순차 실행기를 함께 둔다 —
    **폴백이 아니다.** 흐름이 동일함을 `tests/test_graph.py` 가 강제한다.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any, Callable

from app.core.domain.precheck_result import PrecheckInput, PrecheckOutcome, ReasonCode, Verdict

#: ★재시도 상한. 계약 §1 — 2회를 넘지 않는다.
MAX_RETRY = 2

#: 노드 이름. 트레이스·테스트가 이 문자열을 본다.
NODES = (
    "normalize",
    "resolve_policy",
    "gate_document",
    "retrieve",
    "assess",
    "explain",
    "verify_citations",
)


def _hash_code(code: str) -> str:
    """질병기호를 상태에 담기 전에 해시한다.

    ★원문을 그대로 두면 트레이스·로그에 민감정보가 남는다.
      짧게 자르는 것은 사람이 눈으로 대조할 수 있게 하기 위함이고,
      되돌릴 수 없다는 성질은 그대로다.
    """
    return hashlib.sha256(code.strip().upper().encode("utf-8")).hexdigest()[:16]


@dataclass
class GraphState:
    """노드 사이를 오가는 상태. **원문 개인정보를 담지 않는다.**"""

    #: 질병기호 **해시**. 원문은 여기 없다.
    kcd_hashes: tuple[str, ...] = ()
    insurer: str = ""
    enrolled_on: str = ""

    policy: Any = None
    clauses: tuple = ()
    outcome: PrecheckOutcome | None = None

    #: 지나온 노드. 감사와 테스트가 본다.
    trail: list[str] = field(default_factory=list)
    #: `verify_citations` 에서 되돌아온 횟수.
    retries: int = 0
    #: 무엇 때문에 되돌아왔나. 같은 이유로 두 번 돌지 않는다.
    retry_reasons: list[str] = field(default_factory=list)
    #: 그래프가 끝났나.
    done: bool = False

    def visit(self, node: str) -> None:
        self.trail.append(node)


class PrecheckGraph:
    """판정 흐름. 노드 구현은 **주입받는다.**

    ★그래프가 어댑터를 직접 import 하지 않는다.
      그러면 흐름과 저장소가 얽혀 어느 쪽도 따로 시험할 수 없다.
    """

    def __init__(
        self,
        *,
        run_precheck: Callable[[PrecheckInput], PrecheckOutcome],
        verify: Callable[[PrecheckOutcome], tuple[bool, ReasonCode | None, str]],
        retarget: Callable[[PrecheckInput, PrecheckOutcome], PrecheckOutcome] | None = None,
    ):
        #: 규칙엔진 전체(resolve→gate→retrieve→assess)를 한 덩어리로 받는다.
        #: ★쪼개서 다시 조립하면 유스케이스와 그래프에 **같은 판단이 두 벌** 생긴다.
        self._run = run_precheck
        self._verify = verify
        self._retarget = retarget

    # ── 노드 ────────────────────────────────────────────────────────

    def normalize(self, st: GraphState, body: PrecheckInput) -> GraphState:
        st.visit("normalize")
        st.kcd_hashes = tuple(_hash_code(c) for c in body.kcd_codes)
        st.insurer = body.insurer
        st.enrolled_on = body.enrolled_on
        return st

    def run_rules(self, st: GraphState, body: PrecheckInput) -> GraphState:
        """resolve_policy → gate_document → retrieve → assess → explain.

        ★이 넷은 유스케이스가 이미 한 덩어리로 한다. 그래프가 쪼개서 다시 하면
          **같은 판단이 두 곳**에 생기고 반드시 어긋난다.
          그래서 여기서는 **부르고, 결과가 어느 단계에서 멈췄는지만 기록**한다.
        """
        for n in ("resolve_policy", "gate_document", "retrieve", "assess", "explain"):
            st.visit(n)
        st.outcome = self._run(body)
        st.policy = st.outcome.applied_policy
        st.clauses = tuple(st.outcome.citations)
        return st

    def verify_citations(self, st: GraphState, body: PrecheckInput) -> GraphState:
        """★재시도 지점. 여기서만 되돌아온다."""
        st.visit("verify_citations")
        assert st.outcome is not None

        ok, code, msg = self._verify(st.outcome)
        if ok:
            st.done = True
            return st

        reason = code.value if code else "unknown"

        #: ★같은 이유로 두 번 돌지 않는다. 돌아도 같은 결과가 나온다.
        if reason in st.retry_reasons or st.retries >= MAX_RETRY:
            st.outcome = self._abstain(st.outcome, msg)
            st.done = True
            return st

        st.retries += 1
        st.retry_reasons.append(reason)

        if self._retarget is not None:
            #: 표적 검색 1회. 여기서도 **verdict 를 바꾸지 않는다** —
            #: 근거를 더 모아 규칙엔진을 다시 부를 뿐이다.
            st.outcome = self._retarget(body, st.outcome)
            st.clauses = tuple(st.outcome.citations)
            return st

        #: 되돌아갈 수단이 없으면 그 사실을 숨기지 않고 기권한다.
        st.outcome = self._abstain(st.outcome, msg)
        st.done = True
        return st

    @staticmethod
    def _abstain(outcome: PrecheckOutcome, msg: str) -> PrecheckOutcome:
        """초안을 폐기하고 기권한다.

        ★설명문과 인용을 **비운다.** 검증에 실패한 근거를 남겨 두면
          클라이언트가 그걸 읽고 판단한다.
        """
        from dataclasses import replace

        return replace(
            outcome,
            verdict=Verdict.NEEDS_EXPERT,
            abstained=True,
            reason_code=ReasonCode.CITATION_UNVERIFIED,
            message=(
                "근거 인용을 검증하지 못해 판정하지 않았습니다. "
                f"전문가 확인이 필요합니다. ({msg})"
            ),
            citations=(),
            per_code=(),
        )

    # ── 실행 ────────────────────────────────────────────────────────

    def invoke(self, body: PrecheckInput) -> tuple[PrecheckOutcome, GraphState]:
        """순차 실행기. **LangGraph 가 없어도 같은 흐름을 돈다.**

        ★분기와 재시도가 아래 `while` 하나에 다 보인다.
          자율 루프가 아니라 **상한이 코드에 박힌 반복**이다.
        """
        st = GraphState()
        self.normalize(st, body)
        self.run_rules(st, body)

        guard = 0
        while not st.done:
            self.verify_citations(st, body)
            guard += 1
            #: ★MAX_RETRY 로 이미 막히지만, 이중으로 잠근다.
            #:   흐름 버그로 무한 반복이 되면 서비스가 멈춘다.
            if guard > MAX_RETRY + 1:
                st.outcome = self._abstain(st.outcome, "재시도 흐름이 끝나지 않았습니다")
                st.done = True

        assert st.outcome is not None
        return st.outcome, st

    def build_langgraph(self):
        """같은 노드·분기를 LangGraph `StateGraph` 로 세운다.

        ★`invoke()` 와 **흐름이 같아야 한다.** 테스트가 그것을 강제한다.
          두 실행기가 갈라지면 어느 쪽이 진짜인지 알 수 없게 된다.
        """
        from langgraph.graph import END, StateGraph

        g = StateGraph(dict)

        def _norm(s: dict) -> dict:
            st: GraphState = s["st"]
            self.normalize(st, s["body"])
            return s

        def _rules(s: dict) -> dict:
            self.run_rules(s["st"], s["body"])
            return s

        def _verify(s: dict) -> dict:
            self.verify_citations(s["st"], s["body"])
            return s

        g.add_node("normalize", _norm)
        g.add_node("rules", _rules)
        g.add_node("verify_citations", _verify)
        g.set_entry_point("normalize")
        g.add_edge("normalize", "rules")
        g.add_edge("rules", "verify_citations")
        #: ★되돌아오는 지점. 끝났으면 END, 아니면 자기 자신으로.
        g.add_conditional_edges(
            "verify_citations",
            lambda s: END if s["st"].done else "verify_citations",
            {END: END, "verify_citations": "verify_citations"},
        )
        return g.compile()


def build() -> PrecheckGraph:
    """조립. **어댑터를 고르는 것은 조립 지점의 일이다.**"""
    from app.composition import build_precheck
    from app.core.ports.precheck import ClauseRow
    from app.core.usecases import precheck as uc

    deps = build_precheck()
    versions = deps["policies"].load_versions()

    def _run(body: PrecheckInput) -> PrecheckOutcome:
        return uc.run(body, policies=deps["policies"], clauses=deps["clauses"], versions=versions)

    def _verify(outcome: PrecheckOutcome):
        """결과의 인용을 검증한다.

        ★지금은 LLM 설명이 없어 **인용 목록만** 검증한다.
          `verify_explanation` 은 설명문(`answer_text`)을 받도록 만들어져 있는데,
          규칙엔진만 도는 지금은 설명문이 없다. **없는 것을 있는 척하지 않는다** —
          빈 설명문을 넘기고, LLM 을 붙일 때 실제 설명문을 넘긴다.
        """
        if not outcome.citations:
            #: 인용이 없으면 검증할 것도 없다. 기권 여부는 규칙엔진이 이미 정했다.
            return True, None, ""
        evidence = [
            ClauseRow(
                sha256=outcome.applied_policy.sha256 if outcome.applied_policy else "",
                qualified_no=c.qualified_no,
                clause_no=c.qualified_no.split("/")[-1] if c.qualified_no else "",
                section=c.section,
                title=c.title,
                text=c.quote,
                page_from=c.page_from,
                page_to=c.page_to,
                content_hash="",
            )
            for c in outcome.citations
        ]
        return uc.verify_explanation(
            cited_clauses=[c.qualified_no for c in outcome.citations],
            evidence=evidence,
            answer_text=outcome.message or "",
        )

    return PrecheckGraph(run_precheck=_run, verify=_verify)


__all__ = ["GraphState", "PrecheckGraph", "MAX_RETRY", "NODES", "build"]
