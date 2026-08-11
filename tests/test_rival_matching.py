"""경쟁 상품명 대조 — **자기 그림자를 증거로 세지 않는다.**

★이 파일이 지키는 명제

    1. 상대 이름이 **내 이름 안에** 들어 있으면 증거가 아니다(정보량 0).
    2. ☠거꾸로 내 이름이 상대 이름에 삼켜지면 **자동 확정을 막는다.**
       — 빼는 것이 아니라 막는 것이다. 빼면 오히려 통과한다.
    3. 독립적으로 확인된 다른 본약관은 여전히 모호로 남는다.
    4. 특약은 상대로 세지 않는다.

★★왜 이 시험이 있나 (2026-08-11 전수 재측정)

    `_norm()` 이 괄호·점을 지우므로 상품명이 이렇게 겹친다 —

        나  : 무배당 흥국화재 다이렉트 실손의료보험(25.07)  →  …실손의료보험2507
        상대: 무배당 흥국화재 다이렉트 실손의료보험        →  …실손의료보험

    내 이름이 문서에 있으면 상대 키는 **반드시** 걸린다. 그런데 그걸
    「다른 상품도 실려 있다」는 증거로 셌다. 모호 240건 중 **161건(67.1%)**
    이 이 경우였다 — 기준의 문제가 아니라 **결함**이다.

    ☠반대 방향은 실측 0건이지만 남긴다. **없다는 것을 재고 나서** 하는 말이라야 한다.
"""

from __future__ import annotations

import pytest

from scripts.confirm.identify_documents import _gen_splits_month, _norm, _rivals


def _row(name: str, sha: str = "aa"):
    return {"product_name": name, "sha256": sha}


def _doc(*names: str) -> str:
    return _norm(" ".join(names))


# ── ① 자기 그림자 ────────────────────────────────────────────────────────
def test_상대_이름이_내_이름_안에_있으면_증거가_아니다():
    me = _row("무배당 흥국화재 다이렉트 실손의료보험(25.07)", "aa")
    short = _row("무배당 흥국화재 다이렉트 실손의료보험", "bb")
    #: ★문서에는 **내 이름만** 적혀 있다. 상대 키는 그 안에 들어 있어 저절로 걸린다.
    rivals, shadowed = _rivals(me, _doc(me["product_name"]), [short])
    assert rivals == [], "내 이름 안에 든 짧은 이름은 다른 상품의 증거가 될 수 없다"
    assert shadowed == []


def test_괄호_판본만_다른_짧은_이름도_같다():
    me = _row("무배당 흥국화재 실손의료보험(개인재개용_25.07)", "aa")
    short = _row("무배당 흥국화재 실손의료보험(개인재개용)", "bb")
    rivals, _ = _rivals(me, _doc(me["product_name"]), [short])
    assert rivals == []


# ── ② ☠삼켜짐 — 빼는 것이 아니라 막는 것 ──────────────────────────────────
def test_내_이름이_더_긴_이름에_삼켜지면_막는다():
    me = _row("무배당 흥국화재 다이렉트 실손의료보험", "aa")
    longer = _row("무배당 흥국화재 다이렉트 실손의료보험(25.07)", "bb")
    #: ★문서에 적힌 것은 **긴 이름뿐**이다. 내 이름은 그 부분문자열로 걸렸을 뿐이다.
    rivals, shadowed = _rivals(me, _doc(longer["product_name"]), [longer])
    assert shadowed == [longer["product_name"]], "삼켜진 사실을 신호로 남겨야 한다"
    #: ☠★이걸 `rivals` 에서 빼기만 하면 **오히려 통과한다.** 별도 신호라야 막힌다.
    assert rivals == []


# ── ③ 진짜 경쟁은 여전히 모호 ────────────────────────────────────────────
def test_독립적인_다른_본약관은_여전히_모호다():
    me = _row("무배당 프로미라이프 실손의료비보험(계약전환용)2101", "aa")
    other = _row("무배당 프로미라이프 실손의료비보험2101", "bb")
    #: 어느 쪽도 다른 쪽의 부분문자열이 아니다 — 둘 다 문서에 실제로 적혀 있다.
    rivals, shadowed = _rivals(me, _doc(me["product_name"], other["product_name"]), [other])
    assert rivals == [other["product_name"]]
    assert shadowed == []


def test_문서에_없는_상대는_세지_않는다():
    me = _row("무배당 A화재 실손의료보험2101", "aa")
    other = _row("무배당 A화재 실손의료보험1704", "bb")
    rivals, shadowed = _rivals(me, _doc(me["product_name"]), [other])
    assert rivals == [] and shadowed == []


# ── ④ 특약 ──────────────────────────────────────────────────────────────
def test_특약은_경쟁_상대로_세지_않는다():
    me = _row("무배당 A화재 실손의료보험2101", "aa")
    rider = _row("실손의료비보장 안정화 할인 특별약관", "bb")
    rivals, _ = _rivals(me, _doc(me["product_name"], rider["product_name"]), [rider])
    assert rivals == []


def test_자기_자신은_상대가_아니다():
    me = _row("무배당 A화재 실손의료보험2101", "aa")
    same = _row("무배당 A화재 실손의료보험2101", "aa")
    rivals, shadowed = _rivals(me, _doc(me["product_name"]), [same])
    assert rivals == [] and shadowed == []


# ── ⑤ 월 정밀도 날짜로 세대 모순을 선언하지 않는다 ────────────────────────
#
# ★★실손 세대 경계 중 **월 가운데** 있는 것은 5세대(`2026-05-06`) 하나뿐이다.
#   상품명 코드 `2605` 에서 뽑은 판매일은 일(日)을 모르므로 `20260501` 로 채워지는데,
#   그 채운 값이 경계 앞에 떨어져 「규칙은 4세대」가 된다. **채운 값이 결론을 만든다.**
#   실측 2026-08-11 — 이 한 가지로 NH농협 3건이 원장에서 빠졌다.
@pytest.mark.parametrize(("ym", "splits"), [
    ("20260501", True),    # ★5세대 경계 2026-05-06 이 달 가운데 있다
    ("20260401", False),
    ("20260601", False),
    ("20210701", False),   # 4세대 경계는 1일이라 달을 가르지 않는다
    ("20170401", False),
    ("20091001", False),
    #: ☠말일을 `31` 로 고정하면 여기가 True 로 나온다 — 9월엔 31일이 없다.
    ("20090901", False),
])
def test_그_달_안에서_세대가_갈리는지(ym, splits):
    assert _gen_splits_month(ym) is splits
