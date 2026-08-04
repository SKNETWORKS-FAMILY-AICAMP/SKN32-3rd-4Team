"""FusionRetriever — 여러 RetrieverPort를 결합(그래프 + 벡터)해 하나의 RetrieverPort로 제공.

같은 포트라 AnswerQuestion을 수정 없이 재사용한다(Phase 5b). 각 리트리버의 Evidence를 모아
정규화 score 내림차순으로 정렬하고 content 중복을 제거한다. 무폴백: 하위 리트리버 오류는 전파한다
(한쪽 실패를 조용히 무시하지 않음 — 결합의 정직성).
"""

from __future__ import annotations

from app.application.ports import Evidence, RetrieverPort


class FusionRetriever:
    """N개의 RetrieverPort를 결합. backend='fusion'."""

    backend = "fusion"

    def __init__(self, retrievers: list[RetrieverPort]) -> None:
        if not retrievers:
            raise ValueError("FusionRetriever에는 최소 1개의 retriever가 필요합니다.")
        self._retrievers = retrievers

    def search(
        self, query: str, k: int | None = None, source: str | None = None
    ) -> list[Evidence]:
        merged: list[Evidence] = []
        for retriever in self._retrievers:
            merged.extend(retriever.search(query, k=k, source=source))

        # content 중복 제거(첫 등장 우선), score 내림차순 정렬(정형 그래프 사실이 상위로).
        seen: set[str] = set()
        deduped: list[Evidence] = []
        for ev in sorted(merged, key=lambda e: e.score, reverse=True):
            if ev.content in seen:
                continue
            seen.add(ev.content)
            deduped.append(ev)
        # k가 양수일 때만 cap(그래프+벡터라 여유 있게 k*2). k<=0이면 제한 없음.
        return deduped[: k * 2] if (k and k > 0) else deduped
