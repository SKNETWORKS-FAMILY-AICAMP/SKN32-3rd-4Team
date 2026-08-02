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
                                                     ├ 인용 오류      → 설명문만 1회 수정
                                                     ├ 근거 부족      → 표적 검색 1회
                                                     └ 재시도 초과    → 기권(CITATION_UNVERIFIED)

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

import hashlib
import re
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


def _hash_code(code: str) -> str:
    """질병기호를 상태에 담기 전에 해시한다. 원문은 입력 객체 안에만 둔다."""
    return hashlib.sha256(code.strip().upper().encode("utf-8")).hexdigest()[:16]


_ARTICLE_PATTERN = re.compile(r"제\d+조(?:의\d+)?")


def verify_citations_in_message(
    message: str, clauses: tuple[Citation, ...]
) -> tuple[bool, ReasonCode | None, str]:
    """
    설명문(message)에서 인용된 조항번호가 전부 clauses(실제 검색 근거) 안에
    있는지 확인한다. clauses에 없는 조항번호를 인용했으면(할루시네이션) 실패.
    """
    if not clauses:
        return True, None, ""
    valid_article_nos = {c.article_no for c in clauses if c.article_no}
    cited = set(_ARTICLE_PATTERN.findall(message))
    if not cited:
        return False, ReasonCode.CITATION_UNVERIFIED, "설명문이 조항을 인용하지 않았습니다"
    hallucinated = cited - valid_article_nos
    if hallucinated:
        return (
            False,
            ReasonCode.CITATION_UNVERIFIED,
            f"검색되지 않은 조항을 인용했습니다: {', '.join(sorted(hallucinated))}",
        )
    return True, None, ""


@dataclass
class GraphState:
    """노드 사이를 오가는 상태. 원문 개인정보를 담지 않는다."""

    kcd_hashes: tuple[str, ...] = ()
    insurer: str = ""
    enrolled_on: str = ""

    generation: str | None = None
    clauses: tuple = ()
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
        explain: Callable[[PrecheckInput, tuple[PerCodeVerdict, ...], tuple[Citation, ...]], str],
        verify: Callable[[str, tuple[Citation, ...]], tuple[bool, ReasonCode | None, str]],
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
        st.kcd_hashes = tuple(_hash_code(c) for c in body.kcd_codes)
        st.insurer = body.insurer
        st.enrolled_on = body.enrolled_on
        return st

    def run_rules(self, st: GraphState, body: PrecheckInput) -> GraphState:
        """resolve_policy → gate_document → retrieve → assess → explain."""
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
            return st
        st.generation = resolution.generation

        st.visit("gate_document")
        if not self._gate_document(st.generation):
            st.outcome = self._abstain_with(
                ReasonCode.DOCUMENT_NOT_RELIABLE, "약관 문서 상태를 신뢰할 수 없습니다."
            )
            st.done = True
            return st

        st.visit("retrieve")
        st.clauses = self._retrieve(body, st.generation)
        if not st.clauses:
            st.outcome = self._abstain_with(ReasonCode.NO_EVIDENCE, "관련 약관 근거를 찾지 못했습니다.")
            st.done = True
            return st

        st.visit("assess")
        per_code = self._assess(body, st.clauses)

        st.visit("explain")
        message = self._explain(body, per_code, st.clauses)

        st.outcome = PrecheckOutcome(
            verdict=_aggregate_verdict(per_code),
            citations=st.clauses,
            per_code=per_code,
            message=message,
            applied_generation=st.generation,
        )
        return st

    def verify_citations(self, st: GraphState, body: PrecheckInput) -> GraphState:
        """★재시도 지점. 여기서만 되돌아온다."""
        st.visit("verify_citations")
        assert st.outcome is not None

        ok, code, msg = self._verify(st.outcome.message, st.outcome.citations)
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
            new_clauses = self._retarget(body, st.outcome.citations)
            if new_clauses:
                st.clauses = new_clauses
                per_code = self._assess(body, st.clauses)
                message = self._explain(body, per_code, st.clauses)
                st.outcome = PrecheckOutcome(
                    verdict=_aggregate_verdict(per_code),
                    citations=st.clauses,
                    per_code=per_code,
                    message=message,
                    applied_generation=st.generation,
                )
            return st

        st.outcome = self._abstain_with(ReasonCode.CITATION_UNVERIFIED, msg)
        st.done = True
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
        self.run_rules(st, body)

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
        """같은 노드·분기를 LangGraph StateGraph로 세운다. invoke()와 흐름이 같아야 한다."""
        from langgraph.graph import END, StateGraph

        g = StateGraph(dict)

        def _norm(s: dict) -> dict:
            self.normalize(s["st"], s["body"])
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
    ) -> str:
        clauses_text = "\n".join(f"- {c.article_no}: {c.quote}" for c in clauses)
        verdicts_text = "\n".join(f"- {pc.code}: {pc.verdict.value}" for pc in per_code)
        prompt = (
            "아래 약관 조항만 근거로, 사용자 질문에 답하는 설명 문장을 쓰세요.\n"
            "조항 번호를 반드시 인용하고, 조항에 없는 내용은 추측하지 마세요.\n"
            f"판정결과(이미 확정됨, 바꾸지 마세요):\n{verdicts_text}\n\n"
            f"질문: {body.query}\n\n관련 조항:\n{clauses_text}\n"
        )
        return _get_llm().invoke(prompt).content

    def _verify(message: str, clauses: tuple[Citation, ...]) -> tuple[bool, ReasonCode | None, str]:
        return verify_citations_in_message(message, clauses)

    return PrecheckGraph(
        resolve_policy=_resolve_policy,
        gate_document=_gate_document,
        retrieve=_retrieve,
        assess=_assess,
        explain=_explain,
        verify=_verify,
    )


__all__ = ["GraphState", "PrecheckGraph", "MAX_RETRY", "NODES", "build", "verify_citations_in_message"]
