"""RAG 라우터: 검색 / 요약."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.application.answer_question import NO_ANSWER, AnswerResult
from app.composition import (
    build_answer_question,
    build_graph_answer_question,
    build_hybrid_answer_question,
)
from app.core.errors import ValidationErr
from app.db.database import get_db
from app.obs.events import record_event
from app.obs.knowledge_gaps import record_knowledge_gap
from app.rag.service import search
from app.rag.summarize import summarize_text

router = APIRouter(prefix="/api/rag", tags=["rag"])

#: backend → 유스케이스 빌더. Phase 4/5b에서 만들었지만 REST에 연결된 적이 없었다
#: (테스트에서만 직접 호출) — Phase 10 시연을 위해 이 라우터에서 실제로 선택 가능하게 연결.
_QA_BACKENDS = {
    "faiss": lambda top_k: build_answer_question(top_k=top_k),
    "hybrid": lambda top_k: build_hybrid_answer_question(top_k=top_k),  # pgvector+pg_trgm(RRF), PG 필요
    "graph": lambda top_k: build_graph_answer_question(top_k=top_k),  # pgvector+그래프 결합, PG 필요
}


class SearchRequest(BaseModel):
    query: str = Field(min_length=1)
    top_k: int = Field(default=3, ge=1, le=10)
    source: str | None = None


class SummarizeRequest(BaseModel):
    text: str = Field(min_length=1)


class QARequest(BaseModel):
    question: str = Field(min_length=1)
    top_k: int = Field(default=3, ge=1, le=10)
    backend: str = Field(default="faiss", description="faiss(기본, SQLite도 동작) / hybrid / graph(둘 다 PG 필요)")


@router.post("/search")
def rag_search(body: SearchRequest) -> dict:
    return {"results": search(body.query, k=body.top_k, source=body.source)}


def _to_response(result: AnswerResult) -> dict:
    # 변환은 rag_view 1벌만 사용한다 — MCP와 응답이 어긋나지 않도록(Phase 8 parity).
    from app.adapters.rag_view import answer_to_dict

    return answer_to_dict(result)


@router.post("/qa")
def rag_qa(body: QARequest, db: Session = Depends(get_db)) -> dict:
    """질문 → 근거 기반 답변 + 출처 인용 (환각 억제). AnswerQuestion 유스케이스 경유.

    `backend`로 검색 백엔드를 선택한다(같은 RetrieverPort라 유스케이스는 그대로).
    알 수 없는 값은 조용히 faiss로 대체하지 않고 422로 거부한다(무폴백).

    관측성(NFR-OBS-01): 처리 결과를 run_events에 trace_id와 함께 기록한다(원문 저장 금지, 요약만).
    """
    if body.backend not in _QA_BACKENDS:
        raise ValidationErr(
            f"알 수 없는 backend입니다: {body.backend!r} (허용: {sorted(_QA_BACKENDS)})"
        )
    use_case = _QA_BACKENDS[body.backend](body.top_k)
    result = use_case(body.question)
    record_event(
        db,
        kind="rag_query",
        detail={"backend": body.backend, "top_k": body.top_k, "source_count": len(result.sources)},
    )
    # 지식보강 큐(Phase 9): 근거를 못 찾아 답하지 못한 질문을 모은다 = 문서 보강 대상.
    # 유스케이스는 순수(DB 무지)라 **인터페이스 계층인 여기서** 기록한다(Clean Arch 경계).
    if result.answer == NO_ANSWER:
        record_knowledge_gap(db, body.question)
    return _to_response(result)


@router.post("/summarize")
def rag_summarize(body: SummarizeRequest) -> dict:
    return {"summary": summarize_text(body.text)}
