"""
graph/precheck_graph.py

역할:
    보장 사전판정 흐름 -- LangGraph. 계약: 06_계약_Agent.md §1, docs/storyboard.html.

    retrieve/assess/explain은 이 레포에 있는 것(rag/search_policy, LLM)으로
    채운 자리표시 구현이다. 실제 규칙엔진·검색 함수가 준비되면 build() 내부만
    교체하면 된다 -- 그래프 구조 자체는 안 건드려도 된다.

흐름:
    normalize → resolve_policy → gate_document → retrieve → assess → explain
                                                              ↓
                                                   verify_citations ★재시도 지점
                                                     ├ 통과          → 완료
                                                     ├ 실패(기본)     → 같은 근거로 설명만 1회 재작성
                                                     │                 (retarget 주입 시엔 표적 검색 1회로 대체 가능)
                                                     └ 재시도 초과    → 기권(CITATION_UNVERIFIED)

    기본 재시도가 "설명만 재작성"인 이유: retrieve에서 이미 세대(generation)
    필터를 통과한 근거만 st.clauses에 담겨 있다. 실패의 대부분은 근거가
    부족해서가 아니라 explain()이 인용 표기(손잡이)를 놓친 것이므로, 여기서
    근거를 다시 검색하면 세대가 다른 조항이 섞여 들어올 위험만 생긴다.
    retarget을 주입하면(build()는 기본적으로 안 함) 그쪽 함수가 세대 제약을
    책임지는 조건 하에 표적 검색 경로를 대신 쓸 수 있다.

    resolve_policy가 1:N으로 확정 못 하면(candidates 있음) 즉시 기권하고
    ambiguous_product_line + candidates[]를 반환한다 (재시도 대상 아님 --
    사용자/에이전트가 후보 중 하나를 골라 다시 요청해야 하는 경우이기 때문).

지켜야 할 경계 (06_계약_Agent.md §1):
    - 자율 ReAct 루프 없음 (노드/분기 다 미리 적어둠)
    - 재시도 2회 초과 금지
    - verdict를 그래프가 재해석하지 않음 (assess가 정한 것을 explain이 문장화만 함)
    - 상태에 원문 개인정보(질병기호) 저장 안 함 -- 해시로 다룸
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from graph.precheck_domain import (
    Citation,
    PerCodeVerdict,
    PolicyResolution,
    PrecheckInput,
    PrecheckOutcome,
    ProductCandidate,
    ReasonCode,
    Verdict,
)
from graph.extractors import resolve_generation_from_date
from graph.privacy import hash_code
from graph import citation_guard

#: 재시도 상한. 계약 §1 -- 2회를 넘지 않는다.
MAX_RETRY = 2

NODES = (
    "normalize",
    "resolve_policy",
    "gate_document",
    "retrieve",
    "assess",
    "explain",
    "verify_citations",
)

#: 여러 kcd_codes의 개별 verdict를 하나의 대표 verdict로 합칠 때의 우선순위.
#: 가장 주의가 필요한 것이 앞선다 -- 하나라도 확인 불가면 전체를 확인 불가로 보여준다.
_VERDICT_PRIORITY = (Verdict.NEEDS_EXPERT, Verdict.UNLIKELY, Verdict.NEEDS_DOCUMENTS, Verdict.LIKELY_COVERED)


def _aggregate_verdict(per_code: tuple[PerCodeVerdict, ...]) -> Verdict:
    if not per_code:
        return Verdict.NEEDS_EXPERT
    present = {pc.verdict for pc in per_code}
    for verdict in _VERDICT_PRIORITY:
        if verdict in present:
            return verdict
    return Verdict.NEEDS_EXPERT


def citations_to_evidence(clauses: tuple[Citation, ...]) -> list[citation_guard.EvidenceClause]:
    """Citation을 citation_guard.EvidenceClause로 변환. qualified_no가 없으면 article_no로 대체."""
    return [
        citation_guard.EvidenceClause(
            qualified_no=c.qualified_no or c.article_no,
            text=c.quote,
            clause_id=c.clause_id,
        )
        for c in clauses
    ]


def parse_explain_output(raw: str) -> tuple[str, tuple[str, ...]]:
    """
    LLM의 "답변: .../인용: E001, E002" 두 줄 출력을 (메시지, 인용 손잡이들)로 분리한다.
    "인용:" 줄이 없으면 인용 없음으로 처리 -- 형식을 안 지켰다고 봐준 게 아니라
    citation_guard.verify()가 no_citations로 잡아서 재시도/기권하게 만든다.
    """
    message = raw
    cited: tuple[str, ...] = ()
    lines = raw.splitlines()
    body_lines: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("인용:") or stripped.lower().startswith("citations:"):
            handles_part = stripped.split(":", 1)[1]
            cited = tuple(h.strip() for h in handles_part.split(",") if h.strip())
        elif stripped.startswith("답변:"):
            body_lines.append(stripped.split(":", 1)[1].strip())
        else:
            body_lines.append(line)
    message = "\n".join(l for l in body_lines if l.strip()) or raw
    return message, cited


def verify_citations_in_message(
    message: str, cited_handles: tuple[str, ...], clauses: tuple[Citation, ...]
) -> tuple[bool, ReasonCode | None, str]:
    """
    citation_guard.verify()로 인용을 검증한다. explain()이 손잡이(E001 등)로
    선언한 cited_handles가 실제 clauses(검색 근거) 안에 있는지, 본문에서 선언
    없이 조항을 언급하진 않았는지 확인한다.

    quotes는 안 넘긴다 -- explain() 프롬프트가 LLM한테 "실제 인용한 문장"을
    따로 뽑아내라고 요구하지 않아서, 넘길 진짜 인용문이 없다. 조항 원문을
    quotes로 자기 자신과 비교하면 항상 통과하는 눈속임이 된다(실측 확인됨).
    quote 일치까지 검증하려면 explain()이 LLM한테 인용문 자체를 뽑아내게
    프롬프트를 확장해야 한다.
    """
    if not clauses:
        return True, None, ""
    evidence = citation_guard.make_handles(citations_to_evidence(clauses))
    result = citation_guard.verify(
        cited_clauses=list(cited_handles),
        evidence=evidence,
        answer_text=message,
    )
    if result.ok:
        return True, None, ""
    return False, ReasonCode.CITATION_UNVERIFIED, result.reason


@dataclass
class GraphState:
    """노드 사이를 오가는 상태. 원문 개인정보를 담지 않는다."""

    kcd_hashes: tuple[str, ...] = ()
    insurer: str = ""
    enrolled_on: str = ""

    generation: str | None = None
    clauses: tuple = ()
    per_code: tuple[PerCodeVerdict, ...] = ()
    outcome: PrecheckOutcome | None = None

    trail: list[str] = field(default_factory=list)
    retries: int = 0
    retry_reasons: list[str] = field(default_factory=list)
    done: bool = False

    def visit(self, node: str) -> None:
        self.trail.append(node)


class PrecheckGraph:
    """
    판정 흐름. 노드 구현은 주입받는다 -- 그래프가 어댑터를 직접 import하지
    않아야 흐름과 저장소가 얽히지 않고 각각 따로 테스트할 수 있다.
    """

    def __init__(
        self,
        *,
        resolve_policy: Callable[[PrecheckInput], PolicyResolution],
        gate_document: Callable[[str | None], bool],
        retrieve: Callable[[PrecheckInput, str | None], tuple[Citation, ...]],
        assess: Callable[[PrecheckInput, tuple[Citation, ...]], tuple[PerCodeVerdict, ...]],
        explain: Callable[
            [PrecheckInput, tuple[PerCodeVerdict, ...], tuple[Citation, ...]],
            tuple[str, tuple[str, ...]],
        ],
        verify: Callable[
            [str, tuple[str, ...], tuple[Citation, ...]], tuple[bool, ReasonCode | None, str]
        ],
        retarget: Callable[[PrecheckInput, tuple[Citation, ...]], tuple[Citation, ...]] | None = None,
    ):
        self._resolve_policy = resolve_policy
        self._gate_document = gate_document
        self._retrieve = retrieve
        self._assess = assess
        self._explain = explain
        self._verify = verify
        self._retarget = retarget

    # ── 노드 ────────────────────────────────────────────────────────

    def normalize(self, st: GraphState, body: PrecheckInput) -> GraphState:
        st.visit("normalize")
        st.kcd_hashes = tuple(hash_code(c) for c in body.kcd_codes)
        st.insurer = body.insurer
        st.enrolled_on = body.enrolled_on
        return st

    # 아래 5개는 계약(06_계약_Agent.md §1) 다이어그램이 각각 독립된 단계·분기
    # 지점으로 그리는 것들이다. 예전엔 run_rules() 하나에 다 뭉쳐서, LangGraph
    # 실행기(build_langgraph)를 봐도 어느 세부단계에서 실패했는지 그래프
    # 구조만으로는 안 보였다 -- 이제 각 단계가 자기 노드를 갖고, st.trail에도
    # 실제로 거친 단계만 남는다(예: retrieve 실패하면 assess/explain은 trail에
    # 안 남음).

    def resolve_policy_step(self, st: GraphState, body: PrecheckInput) -> GraphState:
        if st.done:
            return st
        st.visit("resolve_policy")
        resolution = self._resolve_policy(body)
        if resolution.generation is None:
            # candidates가 있으면 reason_code를 뭘로 설정했든(깜빡 안 했어도)
            # 무조건 AMBIGUOUS_PRODUCT_LINE으로 본다 -- 후보 존재 자체가 그 상황을 의미함.
            reason = ReasonCode.AMBIGUOUS_PRODUCT_LINE if resolution.candidates else (
                resolution.reason_code or ReasonCode.NOT_RESOLVED
            )
            msg = (
                "여러 상품 후보 중 하나를 확정하지 못했습니다."
                if resolution.candidates
                else "가입일시로 적용 약관(세대)을 확정하지 못했습니다."
            )
            st.outcome = self._abstain_with(reason, msg, candidates=resolution.candidates)
            st.done = True
        else:
            st.generation = resolution.generation
        return st

    def gate_document_step(self, st: GraphState, body: PrecheckInput) -> GraphState:
        if st.done:
            return st
        st.visit("gate_document")
        if not self._gate_document(st.generation):
            st.outcome = self._abstain_with(
                ReasonCode.DOCUMENT_NOT_RELIABLE, "약관 문서 상태를 신뢰할 수 없습니다."
            )
            st.done = True
        return st

    def retrieve_step(self, st: GraphState, body: PrecheckInput) -> GraphState:
        if st.done:
            return st
        st.visit("retrieve")
        st.clauses = self._retrieve(body, st.generation)
        if not st.clauses:
            st.outcome = self._abstain_with(ReasonCode.NO_EVIDENCE, "관련 약관 근거를 찾지 못했습니다.")
            st.done = True
        return st

    def assess_step(self, st: GraphState, body: PrecheckInput) -> GraphState:
        if st.done:
            return st
        st.visit("assess")
        st.per_code = self._assess(body, st.clauses)
        return st

    def explain_step(self, st: GraphState, body: PrecheckInput) -> GraphState:
        if st.done:
            return st
        st.visit("explain")
        message, cited_handles = self._explain(body, st.per_code, st.clauses)
        st.outcome = PrecheckOutcome(
            verdict=_aggregate_verdict(st.per_code),
            citations=st.clauses,
            per_code=st.per_code,
            message=message,
            cited_handles=cited_handles,
            applied_generation=st.generation,
        )
        return st

    def verify_citations(self, st: GraphState, body: PrecheckInput) -> GraphState:
        """★재시도 지점. 여기서만 되돌아온다."""
        st.visit("verify_citations")
        assert st.outcome is not None

        ok, code, msg = self._verify(st.outcome.message, st.outcome.cited_handles, st.outcome.citations)
        if ok:
            st.done = True
            return st

        reason = code.value if code else "unknown"

        # 같은 이유로 두 번 돌지 않는다 -- 돌아도 같은 결과가 나온다.
        if reason in st.retry_reasons or st.retries >= MAX_RETRY:
            st.outcome = self._abstain_with(ReasonCode.CITATION_UNVERIFIED, msg)
            st.done = True
            return st

        st.retries += 1
        st.retry_reasons.append(reason)

        if self._retarget is not None:
            # 표적 검색 1회. 여기서도 verdict는 안 바꾸고 근거만 다시 모은다.
            # retarget을 주입하는 쪽이 세대 등 제약을 지키는 검색 함수를 책임진다.
            new_clauses = self._retarget(body, st.outcome.citations)
            if new_clauses:
                st.clauses = new_clauses
                self.assess_step(st, body)
                self.explain_step(st, body)
                return st

        # retarget이 없거나(build()의 기본 경로) 새 근거를 못 찾았으면, 세대
        # 필터를 통과한 st.clauses는 그대로 두고 설명만 다시 쓰게 한다.
        # 인용검증 실패는 대부분 근거 부족이 아니라 explain()이 인용 표기를
        # 놓친 것이라, 여기서 조항을 다시 검색하면 세대가 다른 조항이 섞여
        # 들어올 위험만 생긴다.
        self.explain_step(st, body)
        return st

    @staticmethod
    def _abstain_with(
        reason_code: ReasonCode, msg: str, candidates: tuple[ProductCandidate, ...] = ()
    ) -> PrecheckOutcome:
        """초안을 폐기하고 기권한다. 설명문·인용을 비운다 (검증 안 된 근거를 남기지 않음)."""
        return PrecheckOutcome(
            verdict=Verdict.NEEDS_EXPERT,
            abstained=True,
            reason_code=reason_code,
            candidates=candidates,
            message=f"확인하지 못했습니다. 전문가 확인이 필요합니다. ({msg})",
            citations=(),
        )

    # ── 실행 ────────────────────────────────────────────────────────

    def invoke(self, body: PrecheckInput) -> tuple[PrecheckOutcome, GraphState]:
        """순차 실행기. LangGraph가 없어도 같은 흐름을 돈다."""
        st = GraphState()
        self.normalize(st, body)
        self.resolve_policy_step(st, body)
        self.gate_document_step(st, body)
        self.retrieve_step(st, body)
        self.assess_step(st, body)
        self.explain_step(st, body)

        guard = 0
        while not st.done:
            self.verify_citations(st, body)
            guard += 1
            if guard > MAX_RETRY + 1:
                st.outcome = self._abstain_with(ReasonCode.CITATION_UNVERIFIED, "재시도 흐름이 끝나지 않았습니다")
                st.done = True

        assert st.outcome is not None
        return st.outcome, st

    def build_langgraph(self):
        """
        계약 다이어그램과 같은 모양으로 노드를 세운다 -- 5단계(resolve_policy·
        gate_document·retrieve·assess·explain)를 각각 별도 노드로 두고, 각
        노드 뒤에서 st.done이면 바로 END로, 아니면 다음 단계로 가는 조건부
        엣지를 건다. invoke()와 실행 흐름(어느 단계에서 멈추는지)이 같아야
        하고, 그건 tests/test_precheck_graph.py가 두 실행기 결과를 대조해서
        강제한다.
        """
        from langgraph.graph import END, StateGraph

        g = StateGraph(dict)

        def _wrap(step):
            def node(s: dict) -> dict:
                step(s["st"], s["body"])
                return s

            return node

        def _next_or_end(next_node: str):
            def route(s: dict) -> str:
                return END if s["st"].done else next_node

            return route

        g.add_node("normalize", _wrap(self.normalize))
        g.add_node("resolve_policy", _wrap(self.resolve_policy_step))
        g.add_node("gate_document", _wrap(self.gate_document_step))
        g.add_node("retrieve", _wrap(self.retrieve_step))
        g.add_node("assess", _wrap(self.assess_step))
        g.add_node("explain", _wrap(self.explain_step))
        g.add_node("verify_citations", _wrap(self.verify_citations))

        g.set_entry_point("normalize")
        g.add_edge("normalize", "resolve_policy")
        g.add_conditional_edges(
            "resolve_policy", _next_or_end("gate_document"), {"gate_document": "gate_document", END: END}
        )
        g.add_conditional_edges(
            "gate_document", _next_or_end("retrieve"), {"retrieve": "retrieve", END: END}
        )
        g.add_conditional_edges("retrieve", _next_or_end("assess"), {"assess": "assess", END: END})
        # assess/explain은 그 자체로 기권 분기가 없다(근거는 retrieve에서 이미 확인됨).
        g.add_edge("assess", "explain")
        g.add_edge("explain", "verify_citations")
        g.add_conditional_edges(
            "verify_citations",
            lambda s: END if s["st"].done else "verify_citations",
            {END: END, "verify_citations": "verify_citations"},
        )
        return g.compile()


def build() -> PrecheckGraph:
    """
    조립. 지금은 AI1/AI2 실제 함수가 이 레포에 없어서, 있는 것(rag/search_policy,
    LLM)으로 자리표시 구현을 채운다. 실제 함수가 합쳐지면 이 함수 내부만 바꾸면 됨.
    """
    from config import LLM_MODEL_NAME
    from mcp_tools.policy_rag_server import search_policy_clause

    def _resolve_policy(body: PrecheckInput) -> PolicyResolution:
        if not body.enrolled_on:
            return PolicyResolution(reason_code=ReasonCode.NOT_RESOLVED)
        generation = resolve_generation_from_date(body.enrolled_on)
        if generation is None:
            return PolicyResolution(reason_code=ReasonCode.NOT_RESOLVED)
        # TODO: 보험사(insurer)별 상품군이 여러 개인 경우(1:N) candidates를
        # 채워 ReasonCode.AMBIGUOUS_PRODUCT_LINE으로 반환해야 함. 지금은
        # 상품 마스터 데이터가 없어 세대만으로 단일 확정한다.
        return PolicyResolution(generation=generation)

    def _gate_document(generation: str | None) -> bool:
        # TODO: 실제 parse_status 필드 연동 전까지는 항상 신뢰 가능한 것으로 둠
        return True

    def _retrieve(body: PrecheckInput, generation: str | None) -> tuple[Citation, ...]:
        results = search_policy_clause(body.query, generation=generation)
        return tuple(
            Citation(
                article_no=r.get("article_no") or "",
                article_title=r.get("article_title") or "",
                quote=r.get("content") or "",
                generation=r.get("generation"),
                source_file=r.get("source_file"),
            )
            for r in results
        )

    def _assess(body: PrecheckInput, clauses: tuple[Citation, ...]) -> tuple[PerCodeVerdict, ...]:
        # TODO: 진짜 규칙엔진(AI2 assess())으로 교체. 지금은 "근거를 찾았다"는
        # 사실만으로 코드마다 NEEDS_DOCUMENTS(조건부 확인 필요)로 잠정 처리 --
        # 이진판정 금지 원칙을 지키기 위해 LIKELY_COVERED/UNLIKELY를 함부로 안 씀.
        codes = body.kcd_codes or ("",)
        verdict = Verdict.NEEDS_DOCUMENTS if clauses else Verdict.NEEDS_EXPERT
        return tuple(PerCodeVerdict(code=c, verdict=verdict) for c in codes)

    _llm = None

    def _get_llm():
        nonlocal _llm
        if _llm is None:
            from langchain_openai import ChatOpenAI

            _llm = ChatOpenAI(model=LLM_MODEL_NAME, temperature=0)
        return _llm

    def _explain(
        body: PrecheckInput, per_code: tuple[PerCodeVerdict, ...], clauses: tuple[Citation, ...]
    ) -> tuple[str, tuple[str, ...]]:
        # 조항마다 요청 단위 손잡이(E001 등)를 붙여서, LLM이 조항번호를 정확히
        # 못 써도(부 이름 누락 등) 손잡이로만 인용하면 확실하게 대조할 수 있게 한다.
        evidence = citation_guard.make_handles(citations_to_evidence(clauses))
        evidence_text = "\n".join(f"{e.handle}: {e.qualified_no} - {e.text}" for e in evidence)
        verdicts_text = "\n".join(f"- {pc.code}: {pc.verdict.value}" for pc in per_code)
        prompt = (
            "아래 [근거]는 각각 손잡이(E001 등)가 붙어 있습니다. "
            "인용할 때는 반드시 그 손잡이를 [E001]처럼 표기하세요. 조항에 없는 내용은 추측하지 마세요.\n"
            f"판정결과(이미 확정됨, 바꾸지 마세요):\n{verdicts_text}\n\n"
            f"질문: {body.query}\n\n[근거]\n{evidence_text}\n\n"
            "다음 두 줄 형식으로만 답하세요 (다른 말 붙이지 마세요):\n"
            "답변: <설명 문장, 인용은 [E001]처럼 표기>\n"
            "인용: <사용한 손잡이를 콤마로, 예: E001, E002>"
        )
        raw = _get_llm().invoke(prompt).content
        return parse_explain_output(raw)

    def _verify(
        message: str, cited_handles: tuple[str, ...], clauses: tuple[Citation, ...]
    ) -> tuple[bool, ReasonCode | None, str]:
        return verify_citations_in_message(message, cited_handles, clauses)

    return PrecheckGraph(
        resolve_policy=_resolve_policy,
        gate_document=_gate_document,
        retrieve=_retrieve,
        assess=_assess,
        explain=_explain,
        verify=_verify,
    )


__all__ = [
    "GraphState",
    "PrecheckGraph",
    "MAX_RETRY",
    "NODES",
    "build",
    "verify_citations_in_message",
    "citations_to_evidence",
    "parse_explain_output",
]
