"""Composition root — 어댑터를 유스케이스에 조립·주입한다(Interface가 유스케이스만 보게).

Phase 1: RAG 질문 유스케이스를 FAISS 검색 + 레지스트리 모델 게이트웨이로 조립.
이후 Phase에서 pgvector/GraphRAG 어댑터로 교체 지점이 된다(설정 기반 선택은 Phase 3).
"""

from __future__ import annotations

from app.adapters.faiss_retriever import FaissRetriever
from app.adapters.llm_gateway import LlmGateway
from app.application.answer_question import AnswerQuestion


def build_answer_question(top_k: int | None = None) -> AnswerQuestion:
    return AnswerQuestion(retriever=FaissRetriever(), model=LlmGateway(), top_k=top_k)


def build_graph_answer_question(top_k: int | None = None) -> AnswerQuestion:
    """GraphRAG: pgvector(문서 청크) + PG 그래프(정형 관계 사실)를 결합한 RAG.

    그래프 사실이 벡터 청크와 함께 근거로 들어가 관계 집계·비교 질의를 보강한다(Phase 5b).
    같은 RetrieverPort라 AnswerQuestion을 수정 없이 재사용.
    """
    from app.adapters.fusion_retriever import FusionRetriever
    from app.adapters.pg_graph_retriever import PgGraphRetriever
    from app.adapters.pgvector_retriever import PgVectorRetriever

    fusion = FusionRetriever([PgVectorRetriever(), PgGraphRetriever()])
    return AnswerQuestion(retriever=fusion, model=LlmGateway(), top_k=top_k)


def build_preview_order(db):
    """미리보기 유스케이스(읽기전용) — SqlCatalog 주입(Phase 6)."""
    from app.adapters.sql_catalog import SqlCatalog
    from app.application.commerce import PreviewOrder

    return PreviewOrder(catalog=SqlCatalog(db))


def build_place_order(db):
    """승인(주문 생성) 유스케이스 — SqlOrderRepository 주입(Phase 6, 멱등·원자)."""
    from app.adapters.sql_order_repo import SqlOrderRepository
    from app.application.commerce import PlaceOrder

    return PlaceOrder(orders=SqlOrderRepository(db))


def build_chat_commerce(db, chat_fn=None, max_steps: int = 3):
    """상담 에이전트 + 자기검증 조립(Phase 7).

    에이전트는 읽기 전용 도구만 사용하며, 초안은 근거 정합성 검사를 거쳐 나간다
    (미지지면 차단). 검증기는 초안과 **같은 모델** — 독립 검증이 아님에 유의.
    """
    from app.adapters.react_agent_adapter import ReactAgentAdapter
    from app.application.chat_commerce import ChatCommerce
    from app.application.self_verify import SelfVerify
    from app.core.model_registry import get_active_profile

    model = LlmGateway()
    model_id = get_active_profile().provider_model_id
    agent = ReactAgentAdapter(db, chat_fn=chat_fn, max_steps=max_steps)
    return ChatCommerce(agent=agent, verify=SelfVerify(model, model_id=model_id))


def build_verify_bounty_submission(retriever=None, support_check=None):
    """지식 바운티 L1 기계 검증 조립.

    재현성·중복성은 기존 리트리버를 재사용하고, 정합성은 SelfVerify를 주입한다
    (새 인프라를 만들지 않는다). 임계값은 config에서 온다 — 하드코딩 금지.

    **이 조립물은 사실성을 판정하지 않는다.** 근거성·재현성·중복성만 확인한다.
    """
    from app.application.bounty import VerifyBountySubmission
    from app.application.self_verify import SelfVerify
    from app.core.config import get_settings
    from app.core.model_registry import get_active_profile

    settings = get_settings()
    if support_check is None:
        support_check = SelfVerify(LlmGateway(), model_id=get_active_profile().provider_model_id)
    return VerifyBountySubmission(
        retriever=retriever if retriever is not None else FaissRetriever(),
        support_check=support_check,
        citation_match_threshold=settings.BOUNTY_CITATION_MATCH_THRESHOLD,
        duplicate_threshold=settings.BOUNTY_DUPLICATE_THRESHOLD,
    )


def build_hybrid_answer_question(top_k: int | None = None, rerank: bool = False) -> AnswerQuestion:
    """Hybrid RAG: dense(pgvector) + lexical(pg_trgm)을 RRF로 결합(Phase 4).

    rerank=True면 결합 결과를 LLM-as-reranker로 재정렬(RerankedRetriever). 모두 같은
    RetrieverPort라 AnswerQuestion을 수정 없이 재사용. 정렬 순서는 그대로 근거로 들어간다.
    """
    from app.adapters.hybrid_retriever import HybridRetriever
    from app.adapters.pg_lexical_retriever import PgLexicalRetriever
    from app.adapters.pgvector_retriever import PgVectorRetriever

    model = LlmGateway()
    retriever = HybridRetriever([PgVectorRetriever(), PgLexicalRetriever()])
    if rerank:
        from app.adapters.reranker import LlmReranker, RerankedRetriever

        retriever = RerankedRetriever(retriever, LlmReranker(model))
    return AnswerQuestion(retriever=retriever, model=model, top_k=top_k)
