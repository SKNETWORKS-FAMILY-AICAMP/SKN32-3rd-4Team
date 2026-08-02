"""외부 에이전트 보고 저장.

★지금까지 202 만 돌려주고 **아무것도 안 쌓았다.**
  데모에서 보고를 보내면 영영 사라지는 상태였다.
"""

import json

from fastapi.testclient import TestClient

from app.adapters import external_submission_store as store
from app.main import create_app

_BODY = {
    "client_ref": "agent-test",
    "insurer": "DB손해보험",
    "enrolled_on": "20200301",
    "kcd_codes": ["F32"],
    "outcome": "denied",
    "outcome_reason": "면책 조항",
    "idempotency_key": "test-key-001",
}


def test_원본을_그대로_남긴다(monkeypatch, tmp_path):
    monkeypatch.setattr(store, "_ROOT", tmp_path)
    monkeypatch.setattr(store, "_SUBMISSIONS", tmp_path / "submissions")
    monkeypatch.setattr(store, "_EVENTS", tmp_path / "events")

    r = store.store(dict(_BODY))
    assert r.stored
    raw = list((tmp_path / "submissions").rglob("*.json"))
    assert len(raw) == 1
    saved = json.loads(raw[0].read_text(encoding="utf-8"))
    #: ★원본은 손대지 않는다 — 나중에 파싱 규칙이 바뀐다.
    assert saved["payload"] == _BODY


def test_정규화_이벤트를_append_한다(monkeypatch, tmp_path):
    monkeypatch.setattr(store, "_ROOT", tmp_path)
    monkeypatch.setattr(store, "_SUBMISSIONS", tmp_path / "submissions")
    monkeypatch.setattr(store, "_EVENTS", tmp_path / "events")

    store.store(dict(_BODY))
    store.store({**_BODY, "idempotency_key": "test-key-002"})
    lines = [
        line
        for p in (tmp_path / "events").glob("*.jsonl")
        for line in p.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert len(lines) == 2


def test_같은_멱등키는_다시_쌓지_않는다(monkeypatch, tmp_path):
    """★에이전트는 재시도한다. 재시도가 통계를 부풀리면 안 된다."""
    monkeypatch.setattr(store, "_ROOT", tmp_path)
    monkeypatch.setattr(store, "_SUBMISSIONS", tmp_path / "submissions")
    monkeypatch.setattr(store, "_EVENTS", tmp_path / "events")

    first = store.store(dict(_BODY))
    second = store.store(dict(_BODY))
    assert first.stored
    assert not second.stored
    assert second.duplicate
    assert len(list((tmp_path / "submissions").rglob("*.json"))) == 1


def test_클라이언트가_검증됨이라_해도_무시한다(monkeypatch, tmp_path):
    """★남이 자기 데이터를 스스로 '검증됨'이라 하면 그건 검증이 아니다."""
    monkeypatch.setattr(store, "_ROOT", tmp_path)
    monkeypatch.setattr(store, "_SUBMISSIONS", tmp_path / "submissions")
    monkeypatch.setattr(store, "_EVENTS", tmp_path / "events")

    store.store({**_BODY, "verification": "confirmed"})
    line = next(
        line
        for p in (tmp_path / "events").glob("*.jsonl")
        for line in p.read_text(encoding="utf-8").splitlines()
        if line.strip()
    )
    assert json.loads(line)["verification"] == "unverified"


def test_경로_조작을_막는다(monkeypatch, tmp_path):
    monkeypatch.setattr(store, "_ROOT", tmp_path)
    monkeypatch.setattr(store, "_SUBMISSIONS", tmp_path / "submissions")
    monkeypatch.setattr(store, "_EVENTS", tmp_path / "events")

    store.store({**_BODY, "client_ref": "../../etc/passwd"})
    #: 상위로 새어 나가지 않는다.
    assert not (tmp_path.parent / "etc").exists()
    assert list((tmp_path / "submissions").rglob("*.json"))


def test_API_가_저장_결과를_알려준다(monkeypatch, tmp_path):
    monkeypatch.setattr(store, "_ROOT", tmp_path)
    monkeypatch.setattr(store, "_SUBMISSIONS", tmp_path / "submissions")
    monkeypatch.setattr(store, "_EVENTS", tmp_path / "events")

    c = TestClient(create_app())
    r = c.post("/v1/observations", json=_BODY)
    assert r.status_code == 202
    j = r.json()
    assert j["stored"] is True
    assert j["verification"] == "unverified"

    again = c.post("/v1/observations", json=_BODY).json()
    assert again["duplicate"] is True
