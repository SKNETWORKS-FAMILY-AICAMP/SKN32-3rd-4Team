"""PgVectorRetriever — RetrieverPort의 pgvector 구현(Phase 3).

FaissRetriever와 **동일 포트·동일 임베딩**. pgvector L2 거리(`<->`)로 top-k 검색 후 중립
`Evidence`로 매핑(정규화 score). 백엔드 전용 거리는 노출하지 않는다(ADR-005').

점수 정규화: 정규화 임베딩의 L2 거리는 [0,2]. score = 1 - d/2 (단조 감소, [0,1]).
연결 실패는 InfraError로 전파(무폴백 — FAISS로 자동 대체하지 않음).
"""

from __future__ import annotations

from app.application.ports import Evidence

_MAX_L2_DISTANCE = 2.0  # 정규화 임베딩의 L2 거리 이론 최대


def normalize_score(distance: float) -> float:
    score = 1.0 - (distance / _MAX_L2_DISTANCE)
    if score < 0.0:
        return 0.0
    if score > 1.0:
        return 1.0
    return score


def _locator(page: object) -> str | None:
    return str(page + 1) if isinstance(page, int) else None


def _row_to_evidence(source: str, page, content: str, distance: float) -> Evidence:
    return Evidence(
        content=content,
        source=source or "",
        locator=_locator(page),
        score=normalize_score(float(distance)),
        backend="pgvector",
    )


class PgVectorRetriever:
    """RetrieverPort 구현(backend='pgvector'). 연결은 호출 시 열고 닫는다(학습용 단순 구조)."""

    backend = "pgvector"

    def __init__(self, dsn: str | None = None) -> None:
        self._dsn = dsn

    def search(
        self, query: str, k: int | None = None, source: str | None = None
    ) -> list[Evidence]:
        import numpy as np

        from app.adapters.pgvector_index import get_conn
        from app.core.config import get_settings
        from app.rag.embeddings import get_embeddings

        k = k or get_settings().RAG_TOP_K
        # numpy 배열이어야 register_vector가 vector 타입으로 명시 어댑트한다(연산자 컨텍스트에서
        # 리스트는 double precision[]로 전송돼 `vector <-> ...` 연산자를 못 찾음).
        qvec = np.asarray(get_embeddings().embed_query(query), dtype=np.float32)

        where = "WHERE source = %(source)s" if source else ""
        sql = (
            f"SELECT source, page, content, embedding <-> %(q)s AS distance "
            f"FROM rag_chunks {where} "
            f"ORDER BY embedding <-> %(q)s LIMIT %(k)s"
        )
        params = {"q": qvec, "k": k}
        if source:
            params["source"] = source

        conn = get_conn(self._dsn)
        try:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                rows = cur.fetchall()
        finally:
            conn.close()
        return [_row_to_evidence(src, page, content, dist) for src, page, content, dist in rows]
