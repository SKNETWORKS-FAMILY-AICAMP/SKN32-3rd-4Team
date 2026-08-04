"""Phase 5a — PG 네이티브 그래프 스키마 PoC (TEST-GRAPH-SCHEMA-001, pg 마커).

정책 그래프 seed 후, 그래프만이 잘 답하는 질의(관계 집계·재귀 순회)를 검증한다.
"""

from __future__ import annotations

import pytest


@pytest.mark.pg
def test_graph_schema_and_policy_queries():
    from app.adapters.pg_graph import (
        ensure_graph_schema,
        k_hop,
        reason_periods,
        reasons_by_payer,
        seed_policy_graph,
    )
    from app.adapters.pgvector_index import get_conn

    conn = get_conn()
    try:
        ensure_graph_schema(conn)
        res = seed_policy_graph(conn)
        assert res == {"nodes": 6, "edges": 4}

        # 집계 질의: 회사가 배송비를 부담하는 사유 = {상품불량, 오배송, 표시광고상이}
        rows = reasons_by_payer(conn, "회사")
        names = {r[0] for r in rows}
        assert names == {"상품 불량·하자", "오배송(상품 상이)", "표시·광고와 상이"}
        # provenance: 원천 문서 + locator(위치)까지 (ADR-007)
        assert all(r[1] == "환불교환정책.pdf" and r[2] is not None for r in rows)

        # 고객 부담 사유 = {단순변심}
        assert {r[0] for r in reasons_by_payer(conn, "고객")} == {"단순 변심"}

        # 비교 질의: 사유별 기한 (단순변심 7일 vs 상품불량 30일) + provenance
        periods = {name: period for name, period, _src, _loc in reason_periods(conn)}
        assert periods["단순 변심"] == "7일"
        assert periods["상품 불량·하자"] == "30일"
        assert all(loc is not None for *_x, loc in reason_periods(conn))

        # 재귀 CTE 순회(임의 깊이 지원): 단순변심 → 고객 (1-hop)
        hops = k_hop(conn, "reason:단순변심", max_depth=2)
        assert any("payer:고객" in path for _d, path in hops)
    finally:
        conn.close()
