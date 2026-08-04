"""health 라우터 테스트 (LLM 호출 없이 readiness 확인)."""

from fastapi.testclient import TestClient

from app.main import app


def test_health_ok():
    client = TestClient(app)
    resp = client.get("/api/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert "provider" in body
    assert set(body["readiness"].keys()) == {"local", "openai", "gemini", "db", "vector"}
    assert body["configured"] == body["readiness"]
    assert body["llm_live_check"] == "/api/health/llm"


def test_llm_health_uses_live_probe(monkeypatch):
    from app.adapters import llm_probe

    expected = {
        "provider": "local",
        "model": "configured-model",
        "configured": True,
        "ready": True,
        "latency_ms": 1.2,
        "error": None,
    }
    monkeypatch.setattr(llm_probe, "probe_llm", lambda: expected)
    resp = TestClient(app).get("/api/health/llm")
    assert resp.status_code == 200
    assert resp.json() == expected
