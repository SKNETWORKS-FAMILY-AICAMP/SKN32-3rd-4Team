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
