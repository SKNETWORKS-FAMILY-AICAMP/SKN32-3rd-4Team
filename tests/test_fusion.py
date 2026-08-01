"""Phase 5b — FusionRetriever 결정론 단위(그래프+벡터 결합 로직, 연결 불필요)."""

from __future__ import annotations

import pytest

from app.adapters.fusion_retriever import FusionRetriever
from app.application.ports import Evidence


class _Fake:
    def __init__(self, evs: list[Evidence]):
        self._e = evs

    def search(self, query, k=None, source=None):
        return list(self._e)


def test_fusion_merges_dedupes_and_sorts_by_score():
    graph = _Fake([
        Evidence("정형 사실1", "pdf", "1", 1.0, "pg_graph"),
        Evidence("중복", "pdf", "1", 0.9, "pg_graph"),
    ])
    vec = _Fake([
        Evidence("청크1", "pdf", "2", 0.7, "pgvector"),
        Evidence("중복", "pdf", "2", 0.5, "pgvector"),  # content 중복
    ])
    res = FusionRetriever([graph, vec]).search("q", k=3)
    contents = [e.content for e in res]
    assert contents[0] == "정형 사실1"  # 최고 score 상위
    assert contents.count("중복") == 1  # 중복 제거
    assert "청크1" in contents  # 두 소스 모두 포함(결합)


def test_fusion_requires_at_least_one_retriever():
    with pytest.raises(ValueError):
        FusionRetriever([])


def test_fusion_propagates_subretriever_error():
    class _Boom:
        def search(self, query, k=None, source=None):
            raise RuntimeError("retriever down")

    with pytest.raises(RuntimeError):
        FusionRetriever([_Boom()]).search("q")  # 무폴백: 한쪽 실패를 삼키지 않음


def test_graph_answer_question_composes():
    # 조립이 유스케이스를 만드는지(연결 없이 구성만).
    from app.application.answer_question import AnswerQuestion
    from app.composition import build_graph_answer_question

    uc = build_graph_answer_question(top_k=3)
    assert isinstance(uc, AnswerQuestion)
