"""HybridRetriever — dense(pgvector) + lexical(pg_trgm) 랭킹을 RRF로 결합(Phase 4).

RRF(Reciprocal Rank Fusion): 각 리스트에서의 순위 rank에 대해 score += 1/(rrf_k + rank).
문서 identity = content. 결합 후 RRF 내림차순 top-k. 정규화 score(최댓값=1)로 Evidence 반환.
같은 RetrieverPort라 AnswerQuestion·Reranker와 조합 가능. 하위 리트리버 오류는 전파(무폴백).
"""

from __future__ import annotations

from app.application.ports import Evidence, RetrieverPort


class HybridRetriever:
    """RetrieverPort 구현(backend='hybrid'). RRF 결합."""

    backend = "hybrid"

    def __init__(
        self, retrievers: list[RetrieverPort], rrf_k: int = 60, over_fetch: int = 10
    ) -> None:
        if not retrievers:
            raise ValueError("HybridRetriever에는 최소 1개의 retriever가 필요합니다.")
        if rrf_k <= 0:
            # rrf_k<=0이면 1/(rrf_k+rank)에서 0 나눗셈·음수 가중으로 정규화 계약이 깨진다.
            raise ValueError(f"rrf_k는 양수여야 합니다: {rrf_k}")
        self._retrievers = retrievers
        self._rrf_k = rrf_k
        self._over_fetch = over_fetch

    def search(
        self, query: str, k: int | None = None, source: str | None = None
    ) -> list[Evidence]:
        rrf: dict[str, float] = {}
        rep: dict[str, Evidence] = {}  # content → 대표 Evidence(첫 등장)
        # 요청 k가 over_fetch보다 크면 융합 후보를 누락하지 않도록 넉넉히 조회.
        fetch = max(self._over_fetch, k) if (k and k > 0) else self._over_fetch
        for retriever in self._retrievers:
            ranked = retriever.search(query, k=fetch, source=source)
            seen_here: set[str] = set()  # 한 retriever가 같은 content로 중복 투표하지 않도록
            for rank, ev in enumerate(ranked, start=1):
                if ev.content in seen_here:
                    continue
                seen_here.add(ev.content)
                rrf[ev.content] = rrf.get(ev.content, 0.0) + 1.0 / (self._rrf_k + rank)
                rep.setdefault(ev.content, ev)

        if not rrf:
            return []
        top = sorted(rrf.items(), key=lambda kv: kv[1], reverse=True)
        max_rrf = top[0][1]
        limit = k if (k and k > 0) else len(top)
        out: list[Evidence] = []
        for content, score in top[:limit]:
            base = rep[content]
            # RRF를 [0,1]로 정규화(최상위=1)해 Evidence.score 계약 유지. backend='hybrid'.
            out.append(
                Evidence(
                    content=base.content,
                    source=base.source,
                    locator=base.locator,
                    score=score / max_rrf if max_rrf else 0.0,
                    backend=self.backend,
                )
            )
        return out
