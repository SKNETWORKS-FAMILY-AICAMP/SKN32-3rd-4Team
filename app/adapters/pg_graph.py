"""PostgreSQL 네이티브 지식그래프 (Phase 5a 설계 검증 / 5b 토대).

노드/엣지 테이블 + 재귀 CTE로 그래프를 표현·순회한다(확장 불필요, pgvector와 동일 DB).
정책 그래프는 환불교환정책.pdf에서 도출 — provenance 실재(ADR-007). 연결 실패는 InfraError 전파.
"""

from __future__ import annotations

# 정책 그래프 인스턴스(환불교환정책.pdf 도출). (node_key, type, name, props, locator)
_POLICY_NODES = [
    ("reason:단순변심", "reason", "단순 변심", {"period": "7일"}, "1"),
    ("reason:상품불량", "reason", "상품 불량·하자", {"period": "30일"}, "1"),
    ("reason:오배송", "reason", "오배송(상품 상이)", {"period": "30일"}, "1"),
    ("reason:표시광고상이", "reason", "표시·광고와 상이", {"period": "3개월/30일"}, "1"),
    ("payer:고객", "payer", "고객", {}, "1"),
    ("payer:회사", "payer", "회사", {}, "1"),
]
# (src_key, dst_key, rel)
_POLICY_EDGES = [
    ("reason:단순변심", "payer:고객", "배송비부담"),
    ("reason:상품불량", "payer:회사", "배송비부담"),
    ("reason:오배송", "payer:회사", "배송비부담"),
    ("reason:표시광고상이", "payer:회사", "배송비부담"),
]
_POLICY_SOURCE = "환불교환정책.pdf"


def ensure_graph_schema(conn) -> None:
    """그래프 노드/엣지 테이블 생성(멱등)."""
    with conn.cursor() as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS graph_nodes (
                id bigserial PRIMARY KEY,
                node_key text UNIQUE NOT NULL,
                node_type text NOT NULL,
                name text NOT NULL,
                props jsonb DEFAULT '{}',
                source text,
                locator text,
                synthetic boolean DEFAULT false
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS graph_edges (
                id bigserial PRIMARY KEY,
                src_key text NOT NULL,
                dst_key text NOT NULL,
                rel text NOT NULL,
                props jsonb DEFAULT '{}',
                source text
            )
            """
        )
    conn.commit()


def seed_policy_graph(conn) -> dict:
    """정책 그래프를 재적재한다(TRUNCATE 후 삽입). provenance=환불교환정책.pdf."""
    import json

    with conn.cursor() as cur:
        cur.execute("TRUNCATE graph_nodes, graph_edges RESTART IDENTITY")
        for key, ntype, name, props, loc in _POLICY_NODES:
            cur.execute(
                "INSERT INTO graph_nodes (node_key, node_type, name, props, source, locator) "
                "VALUES (%s,%s,%s,%s,%s,%s)",
                (key, ntype, name, json.dumps(props, ensure_ascii=False), _POLICY_SOURCE, loc),
            )
        for src, dst, rel in _POLICY_EDGES:
            cur.execute(
                "INSERT INTO graph_edges (src_key, dst_key, rel, source) VALUES (%s,%s,%s,%s)",
                (src, dst, rel, _POLICY_SOURCE),
            )
    conn.commit()
    return {"nodes": len(_POLICY_NODES), "edges": len(_POLICY_EDGES)}


def reasons_by_payer(conn, payer_name: str) -> list[tuple[str, str, str | None]]:
    """집계 질의(벡터 RAG가 약한 관계 집계): 특정 주체가 배송비를 부담하는 사유 목록.

    반환: (사유명, 원천문서, locator) — provenance는 **원천 문서 + 위치(locator)**까지(ADR-007).
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT r.name, r.source, r.locator
            FROM graph_edges e
            JOIN graph_nodes r ON r.node_key = e.src_key
            JOIN graph_nodes p ON p.node_key = e.dst_key
            WHERE e.rel = '배송비부담' AND p.name = %s
            ORDER BY r.name
            """,
            (payer_name,),
        )
        return cur.fetchall()


def reason_periods(conn) -> list[tuple[str, str, str, str | None]]:
    """비교 질의: 각 반품 사유의 청약철회 기한(props.period)을 provenance와 함께 반환.

    반환: (사유명, 기한, 원천문서, locator). 예: "단순 변심" vs "상품 불량·하자" 기한 비교.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT name, props->>'period' AS period, source, locator
            FROM graph_nodes
            WHERE node_type = 'reason'
            ORDER BY name
            """
        )
        return cur.fetchall()


def k_hop(conn, start_key: str, max_depth: int = 2) -> list[tuple[int, str]]:
    """재귀 CTE k-hop 순회(임의 깊이). 반환: (depth, path 문자열)."""
    with conn.cursor() as cur:
        cur.execute(
            """
            WITH RECURSIVE walk(node, path, depth) AS (
                SELECT %(start)s, ARRAY[%(start)s], 0
                UNION ALL
                SELECT e.dst_key, w.path || e.dst_key, w.depth + 1
                FROM walk w JOIN graph_edges e ON e.src_key = w.node
                WHERE w.depth < %(d)s AND NOT e.dst_key = ANY(w.path)
            )
            SELECT depth, array_to_string(path, ' -> ') FROM walk WHERE depth > 0 ORDER BY depth
            """,
            {"start": start_key, "d": max_depth},
        )
        return cur.fetchall()
