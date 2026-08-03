"""외부 에이전트 보고 저장 (어댑터).

★지금까지 **받아놓고 버렸다.**

    `/v1/observations` 가 202 만 돌려주고 아무것도 안 쌓았다.
    `data/external/` 폴더 자체가 없었다.
    데모에서 에이전트가 보고를 보내면 **영영 사라진다.**

★설계는 `docs/handoff/03_에이전트_데이터_축적_설계.md` 를 따른다

    1. **받은 것은 손대지 않고 남긴다**

        data/external/submissions/{YYYY-MM}/{client_ref}/{ts}_{idem}.json

       나중에 파싱 규칙이 바뀐다. 정규화한 것만 두면 "그때 뭘 받았나"를
       다시 볼 수 없다. 약관 PDF 를 원본으로 두는 것과 같은 이유다.

    2. **정규화한 것은 append-only 이벤트 로그로**

        data/external/events/{YYYY-MM-DD}.jsonl

       수정·삭제하지 않는다 — 통계가 조용히 바뀌면 안 된다.
       정정이 필요하면 정정 이벤트를 **뒤에 붙인다.**

★`verification="unverified"` 로 고정한다

    클라이언트가 `verification="confirmed"` 를 보내도 **무시한다.**
    남이 자기 데이터를 스스로 "검증됨"이라 선언하면 그건 검증이 아니다.
    승급은 우리 쪽 검수·규칙엔진·발행처 확인으로만 한다.

★멱등키

    같은 `idempotency_key` 가 다시 오면 **새로 쓰지 않고** 기존 것을 알린다.
    에이전트는 재시도한다 — 재시도가 통계를 부풀리면 안 된다.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

from app.core.errors import InfraError

_ROOT = Path(__file__).resolve().parents[2]
_BASE = _ROOT / "data" / "external"
_SUBMISSIONS = _BASE / "submissions"
_EVENTS = _BASE / "events"

#: ★클라이언트가 무엇을 보내든 이 값으로 고정한다.
_FIXED_VERIFICATION = "unverified"


@dataclass(frozen=True)
class StoreResult:
    """저장 결과."""

    stored: bool
    idempotency_key: str
    #: 이미 있던 것이면 True — 재시도다.
    duplicate: bool = False
    raw_path: str = ""


def _safe(s: str, *, limit: int = 40) -> str:
    """경로에 쓸 수 있게 다듬는다. 경로 조작을 막는다."""
    out = "".join(ch for ch in (s or "") if ch.isalnum() or ch in "-_")
    return (out or "unknown")[:limit]


def _idem_key(payload: dict, client_ref: str) -> str:
    """멱등키. 클라이언트가 안 주면 내용으로 만든다."""
    given = (payload.get("idempotency_key") or "").strip()
    if given:
        return _safe(given, limit=64)
    raw = json.dumps(
        {"c": client_ref, "p": payload}, ensure_ascii=False, sort_keys=True
    )
    return hashlib.sha256(raw.encode()).hexdigest()[:24]


def store(payload: dict, *, received_at: datetime | None = None) -> StoreResult:
    """보고 하나를 저장한다.

    Args:
        payload: 클라이언트가 보낸 그대로. **손대지 않는다.**
        received_at: 시각(테스트용 주입).

    Returns:
        `StoreResult`. `duplicate=True` 면 이미 받은 것이다.
    """
    now = received_at or datetime.now(timezone.utc)
    client = _safe(str(payload.get("client_ref") or "unknown"))
    key = _idem_key(payload, client)

    month = now.strftime("%Y-%m")
    day = now.strftime("%Y-%m-%d")
    ts = now.strftime("%Y%m%dT%H%M%SZ")

    raw_dir = _SUBMISSIONS / month / client
    raw_path = raw_dir / f"{ts}_{key}.json"

    #: ★멱등 — 같은 키가 이미 있으면 새로 쓰지 않는다.
    existing = list(raw_dir.glob(f"*_{key}.json")) if raw_dir.exists() else []
    if existing:
        return StoreResult(
            stored=False,
            idempotency_key=key,
            duplicate=True,
            raw_path=str(existing[0].relative_to(_ROOT)),
        )

    try:
        raw_dir.mkdir(parents=True, exist_ok=True)
        #: ① 원본 그대로. 정규화는 따로 한다.
        raw_path.write_text(
            json.dumps(
                {
                    "received_at": now.isoformat(timespec="seconds"),
                    "client_ref": client,
                    "idempotency_key": key,
                    #: ★손대지 않은 원본.
                    "payload": payload,
                },
                ensure_ascii=False,
                indent=1,
            ),
            encoding="utf-8",
        )

        #: ② 정규화 이벤트 — append-only.
        _EVENTS.mkdir(parents=True, exist_ok=True)
        event = {
            "event": "claim_outcome",
            "at": now.isoformat(timespec="seconds"),
            "idempotency_key": key,
            "client_ref": client,
            "insurer": payload.get("insurer", ""),
            "enrolled_on": payload.get("enrolled_on", ""),
            "kcd_codes": payload.get("kcd_codes", []),
            "outcome": payload.get("outcome", ""),
            "outcome_reason": payload.get("outcome_reason", ""),
            "precheck_trace_id": payload.get("precheck_trace_id"),
            #: ★클라이언트가 뭐라 보내든 미검증이다.
            "verification": _FIXED_VERIFICATION,
        }
        with (_EVENTS / f"{day}.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")
    except OSError as e:
        raise InfraError(f"보고를 저장하지 못했습니다: {e}") from e

    return StoreResult(
        stored=True, idempotency_key=key, raw_path=str(raw_path.relative_to(_ROOT))
    )


def count_events() -> int:
    """쌓인 이벤트 수. 운영 화면·테스트에서 쓴다."""
    if not _EVENTS.exists():
        return 0
    return sum(
        1
        for p in _EVENTS.glob("*.jsonl")
        for line in p.read_text(encoding="utf-8").splitlines()
        if line.strip()
    )


__all__ = ["StoreResult", "count_events", "store"]
