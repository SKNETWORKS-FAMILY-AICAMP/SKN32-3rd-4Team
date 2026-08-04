"""확정 원장 — **확인 안 된 약관으로 판정하지 않는다**를 구조로 지킨다.

★왜 원장을 따로 두나

    매니페스트는 「우리가 무엇을 받았나」(수집 기록)이고 크롤러가 다시 쓴다.
    확정은 「이게 무엇인지 사람이 정했다」(결정)다. 같은 파일에 두면
    수집을 다시 돌리는 순간 사람의 결정이 덮인다.

★이 파일이 지키는 것

    1. 원장이 없으면 판정 가능 약관이 **0건**이다 (fail-closed)
    2. 원장은 **판단만** 덮는다 — 상품명·판매일까지 덮으면 두 번째 매니페스트가 된다
    3. 짧은 sha 는 **거부**한다 — 앞자리만 맞는 다른 문서를 확정할 수 있다
    4. 확정 범위를 **숨기지 않는다** — 10건을 전량으로 읽게 두지 않는다
"""

from __future__ import annotations

import json

import pytest

from app.adapters import manifest_policy_resolver as mpr
from app.core.errors import InfraError

_SHA = "a" * 64
_ROW = {
    "insurer": "테스트화재",
    "product_name": "테스트 실손의료비보험",
    "sha256": _SHA,
    "sale_start": "20220101",
    "date_confidence": "exact",
    "generation": 4,
    "generation_confidence": "exact",
    "product_line": "standard",
}


@pytest.fixture
def _manifest(tmp_path, monkeypatch):
    """매니페스트 한 줄짜리 가짜 폴더."""
    d = tmp_path / "manifests"
    d.mkdir()
    (d / "test.jsonl").write_text(json.dumps(_ROW, ensure_ascii=False) + "\n", encoding="utf-8")
    monkeypatch.setattr(mpr, "_MANIFESTS", d)
    return d


@pytest.fixture
def _ledger(tmp_path, monkeypatch):
    def _set(rows: list[dict] | None):
        p = tmp_path / "confirmed.jsonl"
        if rows is not None:
            p.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows),
                         encoding="utf-8")
        monkeypatch.setattr(mpr, "_LEDGER", p)
        return p

    return _set


def test_원장이_없으면_판정_가능_약관이_0건이다(_manifest, _ledger):
    """★**fail-closed 가 기본이다.** 아무것도 안 하면 아무것도 판정하지 않는다.

    매니페스트에 완벽히 갖춰진 행이 있어도 확정 없이는 못 쓴다 —
    받아왔다는 이유로 무엇인지 안다고 하지 않는다.
    """
    _ledger(None)
    assert mpr.load_versions() == []


def test_원장에_있으면_판정에_쓴다(_manifest, _ledger):
    """★막기만 하고 통과를 못 하면 그것도 고장이다."""
    _ledger([{"sha256": _SHA, "identification": "confirmed", "generation_review": "partial"}])
    vs = mpr.load_versions()
    assert len(vs) == 1
    assert vs[0].insurer == "테스트화재"
    assert vs[0].identification == "confirmed"


def test_원장은_판단만_덮고_사실은_안_덮는다(_manifest, _ledger):
    """★원장이 상품명·판매일까지 이기면 **두 번째 매니페스트**가 된다.

    둘이 어긋났을 때 어느 쪽이 맞는지 아무도 모르게 된다.
    원장은 「이게 무엇인지 정했다」는 판단만 담는다.
    """
    _ledger([{
        "sha256": _SHA, "identification": "confirmed", "generation_review": "partial",
        #: 원장이 사실을 다르게 적어 두어도 무시돼야 한다.
        "product_name": "★원장이_바꾼_이름", "sale_start": "19990101", "insurer": "★원장보험",
    }])
    v = mpr.load_versions()[0]
    assert v.product_name == "테스트 실손의료비보험"
    assert v.sale_start == "20220101"
    assert v.insurer == "테스트화재"


def test_세대검토가_안_된_확정은_통과하지_않는다(_manifest, _ledger):
    """`identification` 만 채우고 `generation_review` 를 비우면 여전히 못 쓴다.

    세대가 틀리면 **다른 세대 약관을 근거로 든다** — 2019년 가입자에게
    4세대 자기부담률을 적용하는 식이다.
    """
    _ledger([{"sha256": _SHA, "identification": "confirmed"}])
    assert mpr.load_versions() == []


def test_짧은_sha_는_거부한다(_manifest, _ledger):
    """★앞자리만 맞는 **다른 문서**를 확정할 수 있다.

    같은 사고가 색인 적재에서 이미 있었다 — 20자 sha 가 들어가
    조회가 통째로 실패했다(2026-08-03). 조용히 넘기지 않는다.
    """
    _ledger([{"sha256": _SHA[:12], "identification": "confirmed", "generation_review": "partial"}])
    with pytest.raises(InfraError) as e:
        mpr.load_versions()
    assert "64자" in str(e.value)


def test_판매시점을_모르면_확정해도_못_쓴다(_manifest, _ledger, tmp_path, monkeypatch):
    """★★**fail-open 이었던 자리다.**

    `date_confidence` 키가 없으면 `"exact"` 로 기본값을 주고 있었다.
    실측 2026-08-04 — 매니페스트 2,121행 중 1,702행에 이 키가 없다.
    확정 게이트가 0건을 만들어 드러나지 않았을 뿐, 확정이 붙는 순간
    1,702행이 "판매시점을 정확히 안다"로 새어 나갔을 것이다.
    """
    d = tmp_path / "m2"
    d.mkdir()
    row = {k: v for k, v in _ROW.items() if k != "date_confidence"}
    (d / "t.jsonl").write_text(json.dumps(row, ensure_ascii=False) + "\n", encoding="utf-8")
    monkeypatch.setattr(mpr, "_MANIFESTS", d)
    _ledger([{"sha256": _SHA, "identification": "confirmed", "generation_review": "partial"}])
    assert mpr.load_versions() == []


def test_확정_범위를_숨기지_않는다():
    """★10건 확정을 **전량**으로 읽게 두지 않는다.

    0건일 때는 경고가 사실을 말했다. 그런데 시연용 10건을 확정하자
    경고가 사라지고 `total_policy_versions: 10` 만 남았다 —
    수집 1,367건 중 0.7% 인데 준비가 끝난 것처럼 보인다.
    """
    from fastapi.testclient import TestClient

    from app.main import app

    m = TestClient(app).get("/v1/support-manifest").json()
    conf = m.get("confirmation") or {}
    assert "confirmed" in conf and "collected" in conf, "확정 건수의 분모가 없습니다"
    if conf.get("confirmed"):
        assert conf["collected"] > 0
        #: ★★**`notes[0]` 만 보면 안 된다.** 처음엔 첫 줄만 검사했는데,
        #:   판정 모드 경고가 앞에 끼어들자 이 시험이 깨졌다(2026-08-04).
        #:   경고가 **몇 번째냐**는 계약이 아니다 — **있느냐**가 계약이다.
        #:   위치를 고정하면 안내를 하나 추가할 때마다 시험이 거짓으로 실패한다.
        head = " ".join(m["notes"])
        #: 분모와 비율이 **문장으로도** 나와야 한다 — 표를 안 보는 사람이 있다.
        assert str(conf["collected"]) in head.replace(",", ""), "확정 건수의 분모가 문장에 없습니다"
        assert "%" in head
        if conf.get("human_signoff_pending"):
            assert "사람" in head, "사람 승인이 남았다는 사실이 안 드러납니다"


def test_확정이_부분이면_판정_응답이_그_사실을_말한다():
    """★★**고른 판본이 진짜 최신이 아닐 수 있다.**

    `resolve()` 는 「가입일 이전 판매 시작 중 가장 늦은 것」을 고르는데,
    그 '가장 늦은 것'은 **확정된 것 중에서만** 가장 늦다. 진짜 적용 판본이
    미확정이면 조용히 더 오래된 판본이 뽑히고, 응답은 그것을 100% 확정된
    것과 **똑같은 확신으로** 말한다.

    실측 2026-08-04 — 확정을 10건에서 132건으로 늘리자 `NH농협생명 20180101`
    의 적용 판본이 2세대에서 3세대로 바뀌었다. 답이 바뀐 게 아니라
    **원래 3세대였는데 안 보였던 것**이다. 그때 `warnings` 는 비어 있었다.
    """
    from fastapi.testclient import TestClient

    from app.main import app

    c = TestClient(app)
    m = c.get("/v1/support-manifest").json()
    conf = m.get("confirmation") or {}
    if not conf.get("confirmed"):
        pytest.skip("확정 0건 — 판본을 고르는 경로 자체가 없다")

    ins = next(iter(m["insurers"]))
    rng = m["insurers"][ins]["sale_start_range"]
    j = c.post("/v1/prechecks",
               json={"insurer": ins, "enrolled_on": "20260801", "kcd_codes": ["F20.0"]}).json()
    if not j.get("applied_policy"):
        pytest.skip(f"{ins} {rng} 로 판본이 안 잡혔다 — 경고 경로가 아니다")

    partial = conf["confirmed"] < conf["collected"]
    joined = " ".join(j.get("warnings") or [])
    if partial:
        assert joined, "확정이 부분인데 판정 응답이 아무 말도 하지 않습니다"
        assert "적용 판본이 아닐 수 있" in joined, f"경고가 위험을 설명하지 않습니다: {joined[:120]}"
        assert str(conf["confirmed"]) in joined.replace(",", "")
    else:
        assert "적용 판본이 아닐 수 있" not in joined, "전량 확정인데 불필요한 경고가 붙습니다"


def test_확정_범위_이름이_늘어도_문장에서_빠지지_않는다():
    """★`demo` 만 이름으로 집어 말하다가 `machine_verified` 122건이 문장에서 통째로 빠졌다.

    범위 이름이 늘 때마다 문구를 고쳐야 하면 반드시 빠뜨린다.
    """
    from fastapi.testclient import TestClient

    from app.main import app

    m = TestClient(app).get("/v1/support-manifest").json()
    scopes = (m.get("confirmation") or {}).get("scopes") or {}
    if not scopes:
        pytest.skip("확정 0건")
    head = " ".join(m["notes"])
    for name, n in scopes.items():
        assert str(n) in head.replace(",", ""), f"범위 {name}({n}건)이 안내 문구에 없습니다"
