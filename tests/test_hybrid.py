"""Phase 4 — Hybrid(RRF) + Reranker 결정론 단위(연결 불필요)."""

from __future__ import annotations

import pytest

from app.adapters.hybrid_retriever import HybridRetriever
from app.adapters.reranker import CrossEncoderReranker, LlmReranker, RerankedRetriever
from app.application.ports import Evidence
from app.core.errors import LLMOutputError


class _Fake:
    def __init__(self, evs: list[Evidence]):
        self._e = evs

    def search(self, query, k=None, source=None):
        return list(self._e)[:k] if (k and k > 0) else list(self._e)


def _ev(c: str, score: float, backend: str) -> Evidence:
    return Evidence(c, "s", None, score, backend)


def test_rrf_combines_dense_and_lexical_rankings():
    # dense: A,B,C / lexical: C,A,B → RRF: A(1,2) > C(3,1) > B(2,3)
    dense = _Fake([_ev("A", 0.9, "pgvector"), _ev("B", 0.8, "pgvector"), _ev("C", 0.7, "pgvector")])
    lex = _Fake([_ev("C", 0.9, "pg_lexical"), _ev("A", 0.8, "pg_lexical"), _ev("B", 0.5, "pg_lexical")])
    res = HybridRetriever([dense, lex], rrf_k=60, over_fetch=10).search("q", k=3)
    contents = [e.content for e in res]
    assert contents[0] == "A"
    assert contents[1] == "C"  # C가 B보다 위(lexical 1위 기여)
    assert set(contents) == {"A", "B", "C"}
    assert all(e.backend == "hybrid" for e in res)
    assert res[0].score == 1.0  # 정규화 최상위


def test_hybrid_requires_at_least_one_retriever():
    with pytest.raises(ValueError):
        HybridRetriever([])


def test_hybrid_rejects_nonpositive_rrf_k():
    with pytest.raises(ValueError):
        HybridRetriever([_Fake([])], rrf_k=0)


def test_hybrid_propagates_error():
    class _Boom:
        def search(self, query, k=None, source=None):
            raise RuntimeError("down")

    with pytest.raises(RuntimeError):
        HybridRetriever([_Boom()]).search("q")


# --- Reranker ---
def test_reranked_retriever_reorders_by_reranker():
    base = _Fake([_ev("low", 0.9, "b"), _ev("high", 0.5, "b")])  # base 순서: low, high

    class _FakeReranker:
        def rerank(self, query, evidence, top_n=None):
            ordered = sorted(evidence, key=lambda e: {"high": 9, "low": 1}[e.content], reverse=True)
            return ordered[:top_n] if top_n else ordered

    res = RerankedRetriever(base, _FakeReranker(), over_fetch=10).search("q", k=1)
    assert res[0].content == "high"  # reranker가 승격


def test_cross_encoder_reranker_orders_and_preserves_evidence():
    class _Model:
        def predict(self, pairs, **kwargs):
            assert pairs == [("q", "low"), ("q", "high")]
            assert kwargs["batch_size"] == 2
            return [0.1, 0.9]

    evs = [_ev("low", 0.8, "dense"), _ev("high", 0.2, "lexical")]
    ranker = CrossEncoderReranker(
        "test/model", model=_Model(), batch_size=2, dtype="auto"
    )
    out = ranker.rerank("q", evs, top_n=1)
    assert out[0].content == "high"
    assert out[0].backend == "lexical"
    assert out[0].score == pytest.approx(0.9)


def test_cross_encoder_reranker_rejects_constant_scores():
    class _Model:
        def predict(self, pairs, **kwargs):
            return [0.5] * len(pairs)

    ranker = CrossEncoderReranker("test/model", model=_Model(), dtype="auto")
    with pytest.raises(RuntimeError, match="constant scores"):
        ranker.rerank("q", [_ev("a", 0.1, "dense"), _ev("b", 0.2, "dense")])


def test_llm_reranker_scores_and_orders():
    class _M:
        def complete(self, prompt, *, max_tokens=None, temperature=0.0):
            return "9" if "관련문서" in prompt else "1"

    evs = [_ev("무관", 0.9, "b"), _ev("관련문서", 0.5, "b")]
    out = LlmReranker(_M()).rerank("q", evs, top_n=2)
    assert out[0].content == "관련문서"
    # 점수가 순위와 일치(계약): 9/10=0.9 > 1/10=0.1, 내림차순 정렬
    assert out[0].score == 0.9 and out[1].score == 0.1


def test_llm_reranker_no_number_raises():
    class _M:
        def complete(self, prompt, *, max_tokens=None, temperature=0.0):
            return "매우 관련 높음"  # 숫자 없음

    with pytest.raises(LLMOutputError):
        LlmReranker(_M()).rerank("q", [_ev("x", 0.5, "b")])


def test_llm_reranker_out_of_range_raises():
    class _M:
        def complete(self, prompt, *, max_tokens=None, temperature=0.0):
            return "50"  # 0-10 범위 밖

    with pytest.raises(LLMOutputError):
        LlmReranker(_M()).rerank("q", [_ev("x", 0.5, "b")])


def test_llm_reranker_rejects_ambiguous_reply():
    class _M:
        def complete(self, prompt, *, max_tokens=None, temperature=0.0):
            return "8 and 20"  # 첫 숫자만 몰래 취하면 안 됨

    with pytest.raises(LLMOutputError):
        LlmReranker(_M()).rerank("q", [_ev("x", 0.5, "b")])


def test_llm_reranker_accepts_suffix_forms():
    class _M:
        def complete(self, prompt, *, max_tokens=None, temperature=0.0):
            return "7점"  # 접미 "점" 허용

    out = LlmReranker(_M()).rerank("q", [_ev("x", 0.5, "b")])
    assert out[0].score == 0.7


def test_rrf_dedups_within_single_retriever():
    # 한 retriever가 같은 content를 두 번 반환해도 표는 1회만
    dup = _Fake([_ev("A", 0.9, "b"), _ev("A", 0.8, "b"), _ev("B", 0.7, "b")])
    single = _Fake([_ev("A", 0.9, "b"), _ev("B", 0.7, "b")])
    r_dup = HybridRetriever([dup]).search("q", k=2)
    r_single = HybridRetriever([single]).search("q", k=2)
    # 중복이 순위를 부풀리지 않음 → 두 결과의 content 순서 동일
    assert [e.content for e in r_dup] == [e.content for e in r_single]


def test_reranked_retriever_over_fetches_at_least_k():
    seen_k = {}

    class _RecBase:
        def search(self, query, k=None, source=None):
            seen_k["k"] = k
            return [_ev(str(i), 1.0, "b") for i in range(k or 0)]

    class _Passthrough:
        def rerank(self, query, evidence, top_n=None):
            return evidence[:top_n] if top_n else evidence

    RerankedRetriever(_RecBase(), _Passthrough(), over_fetch=5).search("q", k=20)
    assert seen_k["k"] == 20  # k>over_fetch면 k만큼 조회(누락 방지)
