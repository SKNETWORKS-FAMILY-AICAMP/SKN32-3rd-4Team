"""TEST-RAG-EVAL-001 — 실 FAISS 검색 품질 평가(ml 마커: 임베딩 로드 필요, CI 제외).

검색 품질 지표는 **Hit@3**다. abstention은 이 corpus에서 거리임계로 분리 불가함을
평가가 밝혔다(unanswerable 0.96~1.34 ↔ answerable 0.45~1.14 겹침) → abstention은
**생성 계층(LLM이 약한 근거를 보고 NO_ANSWER)** 의 책임이며 별도 llm 테스트로 검증한다.
이 격차가 Hybrid/Rerank(Phase 4)·GraphRAG(Phase 5)의 동기다.
"""

from __future__ import annotations

import pathlib

import pytest

from app.eval.rag_eval import evaluate, load_dataset

_DATA = pathlib.Path(__file__).resolve().parents[1] / "data" / "eval" / "rag_v1.jsonl"


@pytest.mark.ml
def test_rag_v1_retrieval_hit_at_3():
    from app.adapters.faiss_retriever import FaissRetriever
    from app.rag.build_index import build_index, index_is_current

    if not index_is_current():
        build_index()

    items = load_dataset(_DATA)
    report = evaluate(items, FaissRetriever(), k=3)

    # 검색 품질: answerable+paraphrase(22개)의 expected_source가 top-3에 (기준 0.85)
    assert report.hit_rate >= 0.85, (
        f"Hit@3={report.hit_rate:.2f} ({report.hits}/{report.retrievable_total})"
    )
    # 참고(비-assert): 검색 단계 abstention은 이 corpus에서 분리 불가 → 생성 계층 책임.
    # report.abstention_rate 는 정보용으로만 계산된다.


@pytest.mark.llm
def test_rag_v1_generation_abstains_on_unanswerable():
    """생성 계층 abstention — 실 LLM이 unanswerable에 NO_ANSWER를 내는지(로컬 모델 서버 필요).

    5개 중 최소 4개(0.8) 이상 abstention을 기준으로 한다(생성 계층이 안전망).
    """
    from app.adapters.faiss_retriever import FaissRetriever
    from app.adapters.llm_gateway import LlmGateway
    from app.application.answer_question import AnswerQuestion
    from app.rag.build_index import build_index, index_is_current

    if not index_is_current():
        build_index()

    uc = AnswerQuestion(FaissRetriever(), LlmGateway(), top_k=3)
    items = load_dataset(_DATA)
    from app.eval.rag_eval import is_abstention

    unanswerable = [i for i in items if i.kind == "unanswerable"]
    abstained = sum(1 for i in unanswerable if is_abstention(uc(i.question).answer))
    rate = abstained / len(unanswerable)
    assert rate >= 0.8, f"generation abstention={rate:.2f} ({abstained}/{len(unanswerable)})"
