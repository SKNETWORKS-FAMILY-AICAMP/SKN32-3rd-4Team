"""app/adapters/audit_log.py -- MCP 요청 감사 로그(계약 §4: client·trace_id·
verdict·latency 기록).
"""

from datetime import datetime, timezone
from pathlib import Path

from app.adapters import audit_log


def test_기록한_이벤트를_같은_날짜에서_읽는다(monkeypatch, tmp_path):
    monkeypatch.setattr(audit_log, "_AUDIT_DIR", tmp_path)
    when = datetime(2026, 8, 3, 12, 0, 0, tzinfo=timezone.utc)

    audit_log.record(
        agent_client_id="demo-client",
        operation="precheck",
        trace_id="tr-1",
        verdict="unlikely",
        latency_ms=5.0,
        recorded_at=when,
    )

    events = audit_log.read_events("2026-08-03")
    assert len(events) == 1
    e = events[0]
    assert e["agent_client_id"] == "demo-client"
    assert e["operation"] == "precheck"
    assert e["trace_id"] == "tr-1"
    assert e["verdict"] == "unlikely"
    assert e["latency_ms"] == 5.0


def test_같은_날짜에_여러번_기록하면_append된다(monkeypatch, tmp_path):
    monkeypatch.setattr(audit_log, "_AUDIT_DIR", tmp_path)
    when = datetime(2026, 8, 3, 9, 0, 0, tzinfo=timezone.utc)

    for i in range(3):
        audit_log.record(
            agent_client_id=f"client-{i}",
            operation="terms_search",
            latency_ms=1.0,
            recorded_at=when,
        )

    events = audit_log.read_events("2026-08-03")
    assert [e["agent_client_id"] for e in events] == ["client-0", "client-1", "client-2"]


def test_원문_식별정보를_담지_않는다(monkeypatch, tmp_path):
    """★client_ref/질병코드 등은 기록 대상이 아니다 -- record()에 그런
    파라미터 자체가 없다(호출부가 잘못 넘길 수도 없다)."""
    monkeypatch.setattr(audit_log, "_AUDIT_DIR", tmp_path)
    audit_log.record(agent_client_id="c1", operation="observations", latency_ms=1.0)

    events = audit_log.read_events(datetime.now(timezone.utc).strftime("%Y-%m-%d"))
    assert set(events[0].keys()) == {
        "at", "agent_client_id", "operation", "trace_id", "verdict", "latency_ms",
    }


def test_기록할_날짜가_없으면_빈_목록():
    assert audit_log.read_events("1999-01-01") == []


def test_쓰기_실패해도_예외를_던지지_않는다(monkeypatch):
    """★감사 로그는 부수 효과다 -- 디스크 문제로 실제 응답을 막으면 안 된다."""

    def boom(*a, **k):
        raise OSError("디스크 문제")

    monkeypatch.setattr(Path, "mkdir", boom)
    audit_log.record(agent_client_id="c1", operation="precheck", latency_ms=1.0)


def test_직렬화_안되는_값을_넘겨도_예외를_던지지_않는다(monkeypatch, tmp_path):
    """★호출부가 실수로 str이 아닌 값(enum 등)을 넘겨 json.dumps가
    TypeError를 던져도 -- OSError만 잡던 예전 버전이면 이게 그대로 새어나가
    MCP 응답 전체를 크래시시켰을 것이다."""
    monkeypatch.setattr(audit_log, "_AUDIT_DIR", tmp_path)

    class _NotSerializable:
        pass

    audit_log.record(
        agent_client_id="c1", operation="precheck", verdict=_NotSerializable(), latency_ms=1.0,
    )
