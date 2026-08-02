"""PgLexicalRetriever — pg_trgm 키워드 검색 RetrieverPort(Phase 4, hybrid의 sparse 측).

한국어 형태소분석기 없이 `word_similarity(query, content)`로 랭킹(임계 없이 top-k). dense(pgvector)와
동일 포트라 HybridRetriever가 RRF로 결합한다. 연결 실패는 전파(무폴백).
"""

from __future__ import annotations

from app.application.ports import Evidence


def _locator(page: object) -> str | None:
    return str(page + 1) if isinstance(page, int) else None


class PgLexicalRetriever:
    """RetrieverPort 구현(backend='pg_lexical'). word_similarity 랭킹."""

    backend = "pg_lexical"

    def __init__(self, dsn: str | None = None) -> None:
        self._dsn = dsn

    def search(
        self, query: str, k: int | None = None, source: str | None = None
    ) -> list[Evidence]:
        from app.adapters.pgvector_index import get_conn
        from app.core.config import get_settings

        k = k or get_settings().RAG_TOP_K
        where = "WHERE source = %(source)s" if source else ""
        sql = (
            "SELECT source, page, content, word_similarity(%(q)s, content) AS sim "
            f"FROM rag_chunks {where} "
            "ORDER BY word_similarity(%(q)s, content) DESC LIMIT %(k)s"
        )
        params = {"q": query, "k": k}
        if source:
            params["source"] = source

        conn = get_conn(self._dsn)
        try:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                rows = cur.fetchall()
        finally:
            conn.close()
        return [
            Evidence(
                content=content,
                source=src or "",
                locator=_locator(page),
                score=float(sim),  # word_similarity ∈ [0,1]
                backend=self.backend,
            )
            for src, page, content, sim in rows
        ]
