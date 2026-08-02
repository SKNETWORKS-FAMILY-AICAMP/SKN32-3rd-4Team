"""Phase 3 — pgvector 어댑터. 결정론 단위(연결 불필요) + pg 마커(실 PG 필요)."""

from __future__ import annotations

import pathlib

import pytest

from app.adapters.pgvector_retriever import _row_to_evidence, normalize_score

_DATA = pathlib.Path(__file__).resolve().parents[1] / "data" / "eval" / "rag_v1.jsonl"


# --- 결정론(연결 불필요) ---------------------------------------------------
def test_normalize_score_l2():
    assert normalize_score(0.0) == 1.0  # 완전 일치
    assert normalize_score(2.0) == 0.0  # 최대 거리
    assert normalize_score(1.0) == 0.5
    assert normalize_score(3.0) == 0.0  # 클램프
    assert normalize_score(-0.1) == 1.0  # 클램프


def test_row_to_evidence_maps_and_normalizes():
    ev = _row_to_evidence("policy.pdf", 2, "내용", 0.4)
    assert ev.source == "policy.pdf"
    assert ev.locator == "3"  # 0-based page 2 → 1-based "3"
    assert ev.backend == "pgvector"
    assert 0.0 <= ev.score <= 1.0
    assert _row_to_evidence("t.txt", None, "x", 0.5).locator is None


# --- pg 마커(실 PostgreSQL+pgvector, ingest 완료 필요) ---------------------
@pytest.mark.pg
def test_get_conn_failure_is_infra_error():
    from app.adapters.pgvector_index import get_conn
    from app.core.errors import InfraError

    with pytest.raises(InfraError):
        get_conn("host=127.0.0.1 port=9 user=x dbname=nope connect_timeout=2")


#: ★이 테스트는 **커머스 실습 코퍼스**(`data/docs/`)가 pgvector 에 적재돼 있어야 한다.
#:   보험 프로젝트에서는 그걸 적재하지 않는다 — 레거시 데이터 의존성이 생긴다.
#:   PG 가 떠 있으면 `pg` 마커만으로는 안 걸러져 **영구히 빨간 테스트**가 된다.
#:   영구 실패는 앞서 51건을 숨겼던 그 함정이므로 `legacy_data` 도 붙인다.
#:   되살리려면: python -m scripts.pg setup   (커머스 문서를 적재한다)
@pytest.mark.pg
@pytest.mark.legacy_data
def test_pgvector_parity_with_faiss():
    from app.adapters.faiss_retriever import FaissRetriever
    from app.adapters.pgvector_retriever import PgVectorRetriever
    from app.rag.build_index import build_index, index_is_current

    if not index_is_current():
        build_index()
    q = "단순 변심 반품 기한은?"
    faiss = FaissRetriever().search(q, k=3)
    pg = PgVectorRetriever().search(q, k=3)
    assert faiss and pg  # 둘 다 근거 반환(같은 포트)
    assert all(0.0 <= e.score <= 1.0 for e in pg)
    assert pg[0].backend == "pgvector"
    assert faiss[0].source == pg[0].source  # 상위 출처 일치(동일 임베딩)


#: ★이 테스트는 **커머스 실습 코퍼스**(`data/docs/`)가 pgvector 에 적재돼 있어야 한다.
#:   보험 프로젝트에서는 그걸 적재하지 않는다 — 레거시 데이터 의존성이 생긴다.
#:   PG 가 떠 있으면 `pg` 마커만으로는 안 걸러져 **영구히 빨간 테스트**가 된다.
#:   영구 실패는 앞서 51건을 숨겼던 그 함정이므로 `legacy_data` 도 붙인다.
#:   되살리려면: python -m scripts.pg setup   (커머스 문서를 적재한다)
@pytest.mark.pg
@pytest.mark.legacy_data
def test_pgvector_hit_at_3_matches_faiss():
    from app.adapters.faiss_retriever import FaissRetriever
    from app.adapters.pgvector_retriever import PgVectorRetriever
    from app.eval.rag_eval import evaluate, load_dataset
    from app.rag.build_index import build_index, index_is_current

    if not index_is_current():
        build_index()
    items = load_dataset(_DATA)
    pg = evaluate(items, PgVectorRetriever(), k=3)
    faiss = evaluate(items, FaissRetriever(), k=3)
    assert pg.hit_rate >= 0.85, f"pgvector Hit@3={pg.hit_rate:.2f}"
    assert pg.hit_rate == faiss.hit_rate  # 동일 임베딩 → 랭킹 동등
