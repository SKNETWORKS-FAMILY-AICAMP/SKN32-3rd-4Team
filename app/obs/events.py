"""run_events 기록 헬퍼 (NFR-OBS-01, TEST-OBS-002).

Interface 계층(라우터)에서 호출한다. Application(AnswerQuestion)은 순수 유지 — 관측성 기록은
경계 밖에서 수행해 도메인이 DB/trace에 의존하지 않게 한다.
"""

from __future__ import annotations

import json

from sqlalchemy.orm import Session

from app.db.models import RunEvent
from app.obs.trace import get_trace_id


def record_event(db: Session, kind: str, detail: dict | None = None) -> RunEvent:
    """현재 trace_id로 이벤트를 append한다. detail은 요약 dict(원문·민감정보 금지)."""
    event = RunEvent(
        trace_id=get_trace_id() or "no-trace",
        kind=kind,
        detail=json.dumps(detail or {}, ensure_ascii=False),
    )
    db.add(event)
    db.commit()
    db.refresh(event)
    return event
