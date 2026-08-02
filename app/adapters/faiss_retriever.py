"""FaissRetriever — RetrieverPort의 FAISS 구현(기존 rag.service 재사용).

기존 `app.rag.service.search`(거리 오름차순 + RAG_MAX_DISTANCE 필터)를 호출하고,
결과를 중립 `Evidence`로 매핑한다. 백엔드 전용 '거리'는 포트 밖으로 노출하지 않고
정규화 점수 [0,1]로 변환한다(ADR-005').

점수 정규화: 임베딩 정규화 + FAISS L2제곱거리는 [0,4] 범위. score = 1 - distance/4
(단조 감소, 0거리→1, 최대거리→0). 기존 거리임계 필터는 service.search가 이미 적용하므로
무관 결과는 애초에 들어오지 않는다(의미 일치 유지).
"""

from __future__ import annotations

from app.application.ports import Evidence
from app.rag import service

# 정규화 임베딩의 L2 제곱거리 이론 최대(= ||a-b||^2, a·b∈[-1,1] → [0,4]).
_MAX_L2_SQ_DISTANCE = 4.0


def _normalize_score(distance: float) -> float:
    score = 1.0 - (distance / _MAX_L2_SQ_DISTANCE)
    # 방어적 클램프(부동소수·경계)
    if score < 0.0:
        return 0.0
    if score > 1.0:
        return 1.0
    return score


def _locator(page: object) -> str | None:
    """검색 결과 page(PDF 0-based int, TXT None) → 사용자용 1-based 문자열."""
    if isinstance(page, int):
        return str(page + 1)
    return None


class FaissRetriever:
    """RetrieverPort 구현(backend='faiss')."""

    backend = "faiss"

    def search(
        self, query: str, k: int | None = None, source: str | None = None
    ) -> list[Evidence]:
        rows = service.search(query, k=k, source=source)
        return [
            Evidence(
                content=r["text"],
                source=r.get("source", ""),
                locator=_locator(r.get("page")),
                score=_normalize_score(float(r["distance"])),
                backend=self.backend,
            )
            for r in rows
        ]
