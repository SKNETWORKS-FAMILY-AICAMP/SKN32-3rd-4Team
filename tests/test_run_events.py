"""TEST-OBS-002 — run_events 기록 + trace 상관."""

from __future__ import annotations

from app.db.database import SessionLocal
from app.db.models import RunEvent
from app.obs.events import record_event
from app.obs.trace import set_trace_id


def test_record_event_persists_with_trace_id():
    set_trace_id("trace-evt-1")
    db = SessionLocal()
    try:
        ev = record_event(db, "rag_query", {"top_k": 3, "source_count": 2})
        assert ev.id is not None
        assert ev.trace_id == "trace-evt-1"
        assert ev.kind == "rag_query"
        row = db.query(RunEvent).filter(RunEvent.id == ev.id).first()
        assert row is not None and row.trace_id == "trace-evt-1"
        assert '"top_k": 3' in row.detail
    finally:
        db.close()


def test_qa_route_records_event(client, monkeypatch):
    # 유스케이스를 페이크로 대체(인덱스·모델 불필요) → 라우터의 이벤트 기록·응답 shape 검증.
    from app.application.answer_question import AnswerResult, Citation
    from app.routers import rag

    class _FakeUseCase:
        def __call__(self, question: str) -> AnswerResult:
            return AnswerResult(answer="답변", sources=[Citation("정책.pdf", "3")])

    monkeypatch.setattr(rag, "build_answer_question", lambda top_k=None: _FakeUseCase())

    db0 = SessionLocal()
    n0 = db0.query(RunEvent).filter(RunEvent.kind == "rag_query").count()
    db0.close()

    r = client.post("/api/rag/qa", json={"question": "환불 기한?", "top_k": 3})
    assert r.status_code == 200
    assert r.json()["sources"] == [{"source": "정책.pdf", "page": 3}]

    db1 = SessionLocal()
    n1 = db1.query(RunEvent).filter(RunEvent.kind == "rag_query").count()
    db1.close()
    assert n1 == n0 + 1
