"""Phase 10 — `/api/rag/qa`의 `backend` 선택(faiss/hybrid/graph).

Phase 4/5b에서 만든 build_hybrid_answer_question/build_graph_answer_question이 REST에
연결된 적이 없었다(테스트에서만 직접 호출) — Phase 10 시연을 위해 실제로 연결했다.
여기서는 라우팅 자체(어떤 빌더가 불렸는가)만 결정론으로 검증한다(PG 불필요).
"""

from __future__ import annotations

from app.application.answer_question import AnswerResult


def test_default_backend_is_faiss(client, monkeypatch):
    import app.routers.rag as rag_router

    called = {}

    def fake_build(top_k=None):
        called["which"] = "faiss"
        return lambda q: AnswerResult(answer="a", sources=[])

    monkeypatch.setattr(rag_router, "build_answer_question", fake_build)
    r = client.post("/api/rag/qa", json={"question": "q"})
    assert r.status_code == 200
    assert called["which"] == "faiss"


def test_backend_hybrid_routes_to_hybrid_builder(client, monkeypatch):
    import app.routers.rag as rag_router

    called = {}

    def fake_build(top_k=None):
        called["which"] = "hybrid"
        return lambda q: AnswerResult(answer="a", sources=[])

    monkeypatch.setattr(rag_router, "build_hybrid_answer_question", fake_build)
    r = client.post("/api/rag/qa", json={"question": "q", "backend": "hybrid"})
    assert r.status_code == 200
    assert called["which"] == "hybrid"


def test_backend_graph_routes_to_graph_builder(client, monkeypatch):
    import app.routers.rag as rag_router

    called = {}

    def fake_build(top_k=None):
        called["which"] = "graph"
        return lambda q: AnswerResult(answer="a", sources=[])

    monkeypatch.setattr(rag_router, "build_graph_answer_question", fake_build)
    r = client.post("/api/rag/qa", json={"question": "q", "backend": "graph"})
    assert r.status_code == 200
    assert called["which"] == "graph"


def test_hybrid_rerank_can_be_enabled_from_settings(client, monkeypatch):
    from types import SimpleNamespace

    import app.core.config as config
    import app.routers.rag as rag_router

    called = {}

    def fake_build(top_k=None, rerank=False):
        called["rerank"] = rerank
        return lambda q: AnswerResult(answer="a", sources=[])

    monkeypatch.setattr(rag_router, "build_hybrid_answer_question", fake_build)
    monkeypatch.setattr(
        config,
        "get_settings",
        lambda: SimpleNamespace(RAG_RERANK_ENABLED=True),
    )
    response = client.post(
        "/api/rag/qa", json={"question": "q", "backend": "hybrid"}
    )
    assert response.status_code == 200
    assert called["rerank"] is True


def test_unknown_backend_is_rejected_not_defaulted(client):
    """알 수 없는 backend를 조용히 faiss로 대체하지 않고 422로 거부한다(무폴백)."""
    r = client.post("/api/rag/qa", json={"question": "q", "backend": "nope"})
    assert r.status_code == 422
