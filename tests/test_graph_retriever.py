"""Phase 5b — PgGraphRetriever + 그래프/벡터 결합 (pg 마커, 실 PG)."""

from __future__ import annotations

import pytest


def _seed_graph():
    from app.adapters.pg_graph import ensure_graph_schema, seed_policy_graph
    from app.adapters.pgvector_index import get_conn

    conn = get_conn()
    ensure_graph_schema(conn)
    seed_policy_graph(conn)
    conn.close()


@pytest.mark.pg
def test_graph_retriever_surfaces_aggregation_facts():
    _seed_graph()
    from app.adapters.pg_graph_retriever import PgGraphRetriever

    evs = PgGraphRetriever().search("회사가 반품 배송비를 부담하는 사유는?")
    texts = " ".join(e.content for e in evs)
    # 회사 부담 3사유가 정형 사실로 완전히 포함(그래프의 집계 완전성)
    assert "상품 불량" in texts and "오배송" in texts and "표시" in texts
    # provenance(원천문서+locator) + backend + 정형 사실 score
    assert all(e.backend == "pg_graph" and e.source == "환불교환정책.pdf" for e in evs)
    assert all(e.locator is not None and e.score == 1.0 for e in evs)


@pytest.mark.pg
def test_graph_retriever_period_routing():
    _seed_graph()
    from app.adapters.pg_graph_retriever import PgGraphRetriever

    evs = PgGraphRetriever().search("단순변심 반품 기한은 며칠이야?")
    texts = " ".join(e.content for e in evs)
    assert "기한" in texts and ("7일" in texts or "30일" in texts)


@pytest.mark.pg
def test_fusion_combines_graph_and_pgvector():
    _seed_graph()
    from app.adapters.fusion_retriever import FusionRetriever
    from app.adapters.pg_graph_retriever import PgGraphRetriever
    from app.adapters.pgvector_retriever import PgVectorRetriever

    fusion = FusionRetriever([PgVectorRetriever(), PgGraphRetriever()])
    evs = fusion.search("회사가 반품 배송비를 부담하는 사유는?", k=3)
    backends = {e.backend for e in evs}
    assert "pg_graph" in backends  # 그래프 정형 사실이 결합됨
    assert evs[0].score == 1.0  # 정형 사실이 상위(벡터 청크보다 위)
