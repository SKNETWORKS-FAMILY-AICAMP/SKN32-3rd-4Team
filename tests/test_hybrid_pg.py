"""Phase 4 — pg 마커: pg_trgm lexical + Hybrid(RRF) 실측(실 PostgreSQL, ingest 완료 필요).

pgvector 테스트와 동일하게 rag_chunks가 ingest된 상태를 전제한다. ensure_schema는 pg_trgm
확장·GIN 인덱스를 idempotent하게 보장한다.
"""

from __future__ import annotations

import pathlib

import pytest

_DATA = pathlib.Path(__file__).resolve().parents[1] / "data" / "eval" / "rag_v1.jsonl"


def _ensure_trgm() -> None:
    from app.adapters.pgvector_index import ensure_schema, get_conn

    conn = get_conn()
    try:
        ensure_schema(conn)  # pg_trgm 확장 + GIN 트라이그램 인덱스 보장(idempotent)
    finally:
        conn.close()


#: ★이 테스트는 **커머스 실습 코퍼스**(`data/docs/`)가 pgvector 에 적재돼 있어야 한다.
#:   보험 프로젝트에서는 그걸 적재하지 않는다 — 레거시 데이터 의존성이 생긴다.
#:   PG 가 떠 있으면 `pg` 마커만으로는 안 걸러져 **영구히 빨간 테스트**가 된다.
#:   영구 실패는 앞서 51건을 숨겼던 그 함정이므로 `legacy_data` 도 붙인다.
#:   되살리려면: python -m scripts.pg setup   (커머스 문서를 적재한다)
@pytest.mark.pg
@pytest.mark.legacy_data
def test_pg_lexical_ranks_by_word_similarity():
    from app.adapters.pg_lexical_retriever import PgLexicalRetriever

    _ensure_trgm()
    # 개발 참고 문서(tool_design_rules 등)는 RAG 코퍼스에서 분리했으므로(dev_docs) 정책
    # 문서를 대상으로 검증한다.
    evs = PgLexicalRetriever().search("반품 배송비 부담", k=3)
    assert evs, "lexical 결과가 비어있음(ingest 필요)"
    assert evs[0].source == "환불교환정책.pdf"  # 키워드 최적 출처
    assert all(0.0 <= e.score <= 1.0 for e in evs)
    assert evs[0].backend == "pg_lexical"


#: ★이 테스트는 **커머스 실습 코퍼스**(`data/docs/`)가 pgvector 에 적재돼 있어야 한다.
#:   보험 프로젝트에서는 그걸 적재하지 않는다 — 레거시 데이터 의존성이 생긴다.
#:   PG 가 떠 있으면 `pg` 마커만으로는 안 걸러져 **영구히 빨간 테스트**가 된다.
#:   영구 실패는 앞서 51건을 숨겼던 그 함정이므로 `legacy_data` 도 붙인다.
#:   되살리려면: python -m scripts.pg setup   (커머스 문서를 적재한다)
@pytest.mark.pg
@pytest.mark.legacy_data
def test_pg_lexical_source_filter():
    from app.adapters.pg_lexical_retriever import PgLexicalRetriever

    _ensure_trgm()
    evs = PgLexicalRetriever().search("반품", k=3, source="환불교환정책.pdf")
    assert evs and all(e.source == "환불교환정책.pdf" for e in evs)


#: ★이 테스트는 **커머스 실습 코퍼스**(`data/docs/`)가 pgvector 에 적재돼 있어야 한다.
#:   보험 프로젝트에서는 그걸 적재하지 않는다 — 레거시 데이터 의존성이 생긴다.
#:   PG 가 떠 있으면 `pg` 마커만으로는 안 걸러져 **영구히 빨간 테스트**가 된다.
#:   영구 실패는 앞서 51건을 숨겼던 그 함정이므로 `legacy_data` 도 붙인다.
#:   되살리려면: python -m scripts.pg setup   (커머스 문서를 적재한다)
@pytest.mark.pg
@pytest.mark.legacy_data
def test_hybrid_hit_at_3_on_rag_v1():
    from app.adapters.hybrid_retriever import HybridRetriever
    from app.adapters.pg_lexical_retriever import PgLexicalRetriever
    from app.adapters.pgvector_retriever import PgVectorRetriever
    from app.eval.rag_eval import evaluate, load_dataset

    _ensure_trgm()
    hybrid = HybridRetriever([PgVectorRetriever(), PgLexicalRetriever()])
    rep = evaluate(load_dataset(_DATA), hybrid, k=3)
    assert rep.hit_rate >= 0.85, f"hybrid Hit@3={rep.hit_rate:.2f}"
