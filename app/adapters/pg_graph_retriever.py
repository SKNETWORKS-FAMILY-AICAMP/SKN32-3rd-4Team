"""PgGraphRetriever — 그래프 사실을 Evidence로 반환하는 RetrieverPort 구현(Phase 5b).

그래프 검색도 `Evidence`를 내므로 **별도 포트 없이 RetrieverPort로 구현**한다(그래서 FusionRetriever로
pgvector와 결합하면 기존 AnswerQuestion을 그대로 재사용). 그래프는 관계를 **정형 사실 문장**으로
언어화해 제공한다(집계·비교에 강함). 원천 문서+locator provenance 유지(ADR-007). 연결 실패는 전파(무폴백).
"""

from __future__ import annotations

from app.application.ports import Evidence

# 질문 topic 라우팅 키워드
_PAYER_KW = ("배송비", "부담", "누가", "비용")
_PERIOD_KW = ("기한", "기간", "며칠", "언제", "이내", "일 안")


def _fact_evidence(content: str, source: str, locator: str | None) -> Evidence:
    # 그래프 사실은 정형·정확 → score 1.0. backend 명시.
    return Evidence(content=content, source=source, locator=locator, score=1.0, backend="pg_graph")


class PgGraphRetriever:
    """RetrieverPort 구현(backend='pg_graph'). 정책 그래프를 정형 사실 Evidence로 언어화."""

    backend = "pg_graph"

    def __init__(self, dsn: str | None = None) -> None:
        self._dsn = dsn

    def _payer_facts(self, conn) -> list[Evidence]:
        from app.adapters.pg_graph import reasons_by_payer

        out: list[Evidence] = []
        for payer in ("회사", "고객"):
            for name, source, locator in reasons_by_payer(conn, payer):
                out.append(
                    _fact_evidence(f"{name} 반품의 배송비는 {payer}가 부담한다.", source, locator)
                )
        return out

    def _period_facts(self, conn) -> list[Evidence]:
        from app.adapters.pg_graph import reason_periods

        out: list[Evidence] = []
        for name, period, source, locator in reason_periods(conn):
            if period:
                out.append(
                    _fact_evidence(f"{name} 반품의 청약철회 기한은 {period}이다.", source, locator)
                )
        return out

    def search(
        self, query: str, k: int | None = None, source: str | None = None
    ) -> list[Evidence]:
        from app.adapters.pgvector_index import get_conn  # 동일 PG 연결 재사용

        q = query or ""
        want_payer = any(kw in q for kw in _PAYER_KW)
        want_period = any(kw in q for kw in _PERIOD_KW)

        conn = get_conn(self._dsn)
        try:
            facts: list[Evidence] = []
            if want_payer:
                facts += self._payer_facts(conn)
            if want_period:
                facts += self._period_facts(conn)
            if not facts:
                # 어느 topic도 특정되지 않으면 전체 정형 사실을 문맥으로 제공(오류 폴백 아님).
                facts = self._payer_facts(conn) + self._period_facts(conn)
        finally:
            conn.close()

        # RetrieverPort 계약: source 메타필터 준수(주어지면 해당 원천만).
        # 빈 문자열은 '필터 없음'으로 취급 — FaissRetriever/service.search의 truthy 관례와 일치.
        if source:
            facts = [e for e in facts if e.source == source]
        return facts[:k] if (k and k > 0) else facts
