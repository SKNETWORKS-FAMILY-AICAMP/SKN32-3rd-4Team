"""Composition root — 어댑터를 유스케이스에 조립·주입한다(Interface가 유스케이스만 보게).

Phase 1: RAG 질문 유스케이스를 FAISS 검색 + 레지스트리 모델 게이트웨이로 조립.
이후 Phase에서 pgvector/GraphRAG 어댑터로 교체 지점이 된다(설정 기반 선택은 Phase 3).
"""

from __future__ import annotations

import os

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




def build_chat_commerce(db, chat_fn=None, max_steps: int = 3):
    """상담 에이전트 + 자기검증 조립(Phase 7).

    에이전트는 읽기 전용 도구만 사용하며, 초안은 근거 정합성 검사를 거쳐 나간다
    (미지지면 차단). 검증기는 초안과 **같은 모델** — 독립 검증이 아님에 유의.
    """
    from app.adapters.react_agent_adapter import ReactAgentAdapter
    from app.application.chat_commerce import ChatCommerce
    from app.application.self_verify import SelfVerify
    from app.core.llm_clients import get_active_model

    model = LlmGateway()
    model_id = get_active_model()
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
    from app.core.llm_clients import get_active_model

    settings = get_settings()
    if support_check is None:
        support_check = SelfVerify(LlmGateway(), model_id=get_active_model())
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
        from app.adapters.reranker import (
            CrossEncoderReranker,
            LlmReranker,
            RerankedRetriever,
        )
        from app.core.config import get_settings

        settings = get_settings()
        if settings.RERANKER_PROVIDER == "cross_encoder":
            ranker = CrossEncoderReranker(
                settings.RERANKER_MODEL,
                device=settings.RERANKER_DEVICE,
                batch_size=settings.RERANKER_BATCH_SIZE,
                max_length=settings.RERANKER_MAX_LENGTH,
                dtype=settings.RERANKER_DTYPE,
                trust_remote_code=settings.RERANKER_TRUST_REMOTE_CODE,
            )
        else:
            ranker = LlmReranker(model)
        retriever = RerankedRetriever(
            retriever, ranker, over_fetch=settings.RERANKER_OVER_FETCH
        )
    return AnswerQuestion(retriever=retriever, model=model, top_k=top_k)


#: 조항을 어디서 읽을 것인가. `file`(추출 산출물) | `pg`(인덱스 A).
#:
#: ★기본은 `file` 이다. 인덱스 A 적재는 CPU 로 4~5시간 걸리는 긴 작업이라
#:   기계마다 상태가 다르다. **없는 것을 있는 척하지 않는다** —
#:   PG 를 쓰려면 `CLAUSE_STORE=pg` 로 **명시**한다.
#: ★★**부를 때 읽는다.** import 시점에 굳히면 두 가지가 깨진다 —
#:   ① 환경을 바꿔도 같은 프로세스가 옛 선택을 붙들고 있다
#:   ② 테스트가 `importlib.reload` 로 우회하다가 **뒤 테스트를 오염시킨다**(실제로 그랬다)
def _clause_store_kind() -> str:
    return os.getenv("CLAUSE_STORE", "file").strip().lower()


def build_precheck():
    """보장 사전판정에 쓸 어댑터 묶음.

    ★구체 구현을 고르는 것은 **조립 지점의 일**이다.
      라우터가 어댑터를 직접 import 하면 "어느 저장소를 쓰는가"가
      HTTP 계층에 흩어진다.

    ★조항 저장소는 두 구현이 **같은 포트**를 만족한다.
        file  data/structured/…  추출 산출물을 직접 읽는다(불변·재생성 근거)
        pg    인덱스 A            내용 한 벌 + 발생 여러 벌 (중복 65.4% 해소)
      통합 저장소를 파일로 또 만들지 않는다 — 같은 본문이 세 곳에 생기면
      어긋났을 때 무엇이 맞는지 판단할 근거가 없어진다.
    """
    from app.adapters import manifest_policy_resolver
    from app.core import release
    from app.core.errors import ConfigError

    #: ★★**어댑터를 만드는 시점에 fail-closed 검사를 한다.**
    #:
    #:   임포트 시점에 하면 테스트·CLI·부분 실행이 깨진다(코덱스).
    #:   여기서 하면 "판정을 하려는 순간"에만 검사가 걸린다.
    #:
    #:   ★산출물이 반쪽이면 판정이 **"그 약관엔 그런 조항이 없다"** 고 답한다.
    #:     그건 근거 없음이 아니라 **틀린 답**이다.
    rel = release.current()
    kind = _clause_store_kind()

    #: 배포 환경의 PG 저장소는 조항 본문을 인덱스에 보관하므로
    #: 로컬 `data/structured/*/<clause_tag>/*.clauses.json`를 포함하지 않는다.
    #: 파일 저장소에서만 산출물 존재·개수 검사를 수행한다.
    if kind == "file":
        rel.ensure_ready()

    if kind == "pg":
        from app.adapters import pg_clause_store

        #: ★승인된 임베딩 프로필이 없으면 PG 경로를 **고르지 않는다.**
        #:   벡터가 없으면 검색이 0건인데, 그걸 "근거 없음"으로 내보내면
        #:   적재를 안 한 것과 근거가 정말 없는 것을 구분할 수 없다.
        if not rel.embed_profile.is_set:
            raise ConfigError(
                f"CLAUSE_STORE=pg 인데 승인된 임베딩 프로필이 없습니다"
                f"(릴리스 {rel.release_id}).\n"
                "★모델이 확정되지 않았습니다 — "
                "`docs/reports/debugs/2026-08-03_임베딩_128토큰_절단_적재중단.md` 참조.\n"
                "지금은 `CLAUSE_STORE=file` 로 두세요."
            )
        return {"policies": manifest_policy_resolver, "clauses": pg_clause_store}

    if kind != "file":
        #: ★알 수 없는 값을 조용히 file 로 떨어뜨리지 않는다(코덱스).
        #:   오타 하나로 다른 저장소를 쓰고 있는 줄 모르게 된다.
        raise ConfigError(
            f"CLAUSE_STORE 값을 모르겠습니다: {kind!r}. `file` 또는 `pg` 여야 합니다."
        )

    from app.adapters import file_clause_store

    return {"policies": manifest_policy_resolver, "clauses": file_clause_store}


def build_cohort():
    """코호트 조회 유스케이스.

    ★어느 저장소를 볼지는 여기서 정한다. DB 적재 후엔 이 줄만 바꾼다.
    """
    from app.adapters import cohort_stats
    from app.core.usecases.cohort import CohortQuery

    return CohortQuery(cohort_stats)


def build_glossary():
    """용어 설명이 볼 구절 색인.

    ★판정용 어댑터와 **다른 것을 준다.** 용어 경로는 전역·완화 필터라
      같은 것을 나눠 쓰면 완화된 필터가 판정으로 샌다
      (`docs/handoff/11_AI_구조_지도.md` §2).
    """
    from app.adapters import file_glossary_source

    return file_glossary_source


def build_clause_search_deps() -> dict:
    """조항 의미검색이 쓸 어댑터를 묶어 준다.

    ★유스케이스(`app/core/usecases/clause_search.py`)는 어댑터를 직접 부르지 않는다
      (ARCH-002·003 — 의존 방향). 그래서 조립은 여기서 한다.
    """
    from app.adapters import pgvector_clause_index
    from app.adapters.clause_rerank import rerank_hits

    return {"index": pgvector_clause_index, "rerank_fn": rerank_hits}
