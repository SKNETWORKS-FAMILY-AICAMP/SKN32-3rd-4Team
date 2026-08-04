"""TEST-OPS-READY-001 — 기동/데이터 분리 readiness (REQ-OPS-01)."""

from __future__ import annotations

from app.obs import readiness


def test_readiness_reports_expected_fields():
    s = readiness.check_readiness()
    for key in ("ready", "db_tables_ready", "missing_tables", "vector_index_ready", "hint"):
        assert key in s


def test_readiness_not_ready_when_index_missing(monkeypatch, tmp_path):
    # 인덱스 없는 빈 디렉터리를 가리키면 vector_index_ready=False → ready=False, hint 제공(무폴백: 명시적)
    fake_settings = type("S", (), {"VECTOR_DIR": tmp_path})()
    monkeypatch.setattr(readiness, "get_settings", lambda: fake_settings)
    s = readiness.check_readiness()
    assert s["vector_index_ready"] is False
    assert s["ready"] is False
    assert s["hint"]  # 준비 방법 안내


def test_readiness_endpoint(client):
    r = client.get("/api/health/ready")
    assert r.status_code == 200
    assert "ready" in r.json()
