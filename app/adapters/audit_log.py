"""MCP 요청 감사 로그 (어댑터).

계약(06_계약_Agent.md §4):
    감사 — 요청마다 client, trace_id, verdict, latency 기록. 원문 대신 해시.

★REST(정본)와 별개 진입점이다

    MCP는 REST 라우터를 거치지 않는다 -- REST 쪽에 감사 미들웨어가 있어도
    MCP로 들어온 요청은 그걸 안 통과한다. 그래서 `app/mcp_server/tools.py`가
    이 모듈을 직접 불러 기록한다.

★client_ref/질병코드 등 원문은 담지 않는다

    여기 기록하는 건 "누가·언제·무슨 작업을·얼마나 걸려서" 뿐이다.
    `agent_client_id`는 등록된 호출 주체 식별자이지 고객(data subject) 정보가
    아니라 그대로 남긴다 -- 해시가 필요한 건 client_ref 같은 고객측 식별자다
    (그건 `tools.py::_subject_hash()`가 이미 해시해서 넘긴다).

★append-only, 실패해도 요청을 막지 않는다

    감사 로그 쓰기 실패(디스크 등)가 실제 판정 응답을 막으면 안 된다 --
    `external_submission_store.py`(보고 저장, 요청의 본 목적)와 달리 이건
    부수 효과라 best-effort로 남긴다.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_AUDIT_DIR = _ROOT / "data" / "audit"


def record(
    *,
    agent_client_id: str,
    operation: str,
    trace_id: str = "",
    verdict: str = "",
    latency_ms: float = 0.0,
    recorded_at: datetime | None = None,
) -> None:
    """요청 하나를 감사 로그에 남긴다.

    Args:
        agent_client_id: 인증된 호출 클라이언트의 등록 ID.
        operation: `"precheck"` / `"terms_search"` / `"observations"`.
        trace_id: 있으면 판정 결과의 trace_id.
        verdict: 있으면 판정 결과(문자열). 검색/보고처럼 verdict 개념이
            없는 작업은 상태 문자열(`"resolved"`, `"stored"` 등)을 대신 쓴다.
        latency_ms: 호출 소요시간(밀리초).
        recorded_at: 시각(테스트용 주입).
    """
    now = recorded_at or datetime.now(timezone.utc)
    day = now.strftime("%Y-%m-%d")
    event = {
        "at": now.isoformat(timespec="milliseconds"),
        "agent_client_id": agent_client_id,
        "operation": operation,
        "trace_id": trace_id,
        "verdict": verdict,
        "latency_ms": round(latency_ms, 2),
    }
    try:
        _AUDIT_DIR.mkdir(parents=True, exist_ok=True)
        with (_AUDIT_DIR / f"{day}.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")
    except Exception:
        #: ★감사 로그는 부수 효과다 -- 쓰기 실패(디스크 등)든, 호출부가 실수로
        #:   직렬화 안 되는 값(enum 등)을 넘긴 경우든, 실제 응답을 막지 않는다.
        pass


def read_events(day: str) -> list[dict]:
    """`day`(YYYY-MM-DD)의 감사 이벤트 전부. 테스트·운영 조회용."""
    path = _AUDIT_DIR / f"{day}.jsonl"
    if not path.exists():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


__all__ = ["record", "read_events"]
