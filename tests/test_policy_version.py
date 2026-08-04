"""가입일 → 적용 약관 확정. ★현행 약관 폴백이 없어야 한다."""

import pytest

from app.core.errors import ValidationErr
from app.adapters.manifest_policy_resolver import resolve
from app.core.ports.precheck import NotResolved, PolicyVersionRow as PolicyVersion


def _v(start, end="", name="실손의료비보험", gen=3, ins="삼성화재"):
    return PolicyVersion(
        insurer=ins, product_name=name, sale_start=start, sale_end=end,
        generation=gen, generation_label=f"{gen}세대", product_line="standard",
        sha256="x" * 64, date_confidence="exact", generation_confidence="exact",
    )


_POOL = [
    _v("20150101", "20161231", gen=2),
    _v("20170401", "20210630", gen=3),
    _v("20210701", "20260505", gen=4),
]


def test_가입일에_해당하는_약관을_고른다():
    r = resolve(insurer="삼성화재", enrolled_on="20190501", versions=_POOL)
    assert isinstance(r, PolicyVersion)
    assert r.generation == 3
    assert r.sale_start == "20170401"


def test_경계일_당일은_새_약관이다():
    r = resolve(insurer="삼성화재", enrolled_on="20210701", versions=_POOL)
    assert r.generation == 4


def test_보유_기간_밖이면_현행약관으로_때우지_않는다():
    #: ★가장 중요한 테스트 — 2010년 가입자에게 최신 약관을 주면 안 된다.
    r = resolve(insurer="삼성화재", enrolled_on="20100101", versions=_POOL)
    assert isinstance(r, NotResolved)
    assert r.reason_code == "no_version_at_date"


def test_보유하지_않은_보험사면_확인_불가다():
    r = resolve(insurer="없는보험", enrolled_on="20190501", versions=_POOL)
    assert isinstance(r, NotResolved)
    assert r.reason_code == "insurer_not_supported"


def test_확정_0건이면_미보유가_아니라_확정대기다():
    """★"없다"와 "아직 확정 안 됐다"를 구분한다.

    확정 게이트가 켜져 있고 확정이 0건이면 `pool` 이 통째로 빈다.
    그때 "약관을 보유하고 있지 않습니다"라고 답하면 **사실을 잘못 전한다** —
    DB손보 약관만 236건 갖고 있다. 수집이 아니라 **식별**이 안 끝난 것이다.

    사용자가 할 일도 다르다. 확정 대기면 기다리면 되고, 미보유면 다른 곳을 찾아야 한다.
    """
    r = resolve(insurer="DB손해보험", enrolled_on="20200301", versions=[])
    assert isinstance(r, NotResolved)
    assert r.reason_code == "documents_not_confirmed"
    #: ★문구가 "보유하고 있지 않다"로 읽히면 안 된다.
    assert "보유하고 있지 않은 것이 아니라" in r.message


def test_모르는_reason_code는_조용히_None이_되지_않는다():
    """★조용한 스킵 금지 (CLAUDE.md §3).

    전에는 `_REASON_MAP.get()` 이라 표에 없는 코드가 **소리 없이 `None`** 이 됐다.
    에이전트는 `reason_code` 로 분기하므로 그러면 왜 기권했는지 알 수 없어진다.
    """
    from app.core.errors import ValidationErr
    from app.core.usecases.precheck import _reason
    from app.core.domain.precheck_result import ReasonCode

    assert _reason(None) is None
    assert _reason("documents_not_confirmed") is ReasonCode.DOCUMENTS_NOT_CONFIRMED
    with pytest.raises(ValidationErr):
        _reason("아직_없는_코드")


def test_같은_시점_상품이_여럿이면_되묻는다():
    pool = _POOL + [_v("20170401", "20210630", name="노후실손의료비보험", gen=3)]
    r = resolve(insurer="삼성화재", enrolled_on="20190501", versions=pool)
    assert isinstance(r, NotResolved)
    assert r.reason_code == "ambiguous_product"
    assert len(r.candidates) == 2


def test_상품명을_주면_좁혀진다():
    pool = _POOL + [_v("20170401", "20210630", name="노후실손의료비보험", gen=3)]
    r = resolve(insurer="삼성화재", enrolled_on="20190501",
                product_name="노후실손", versions=pool)
    assert isinstance(r, PolicyVersion)
    assert "노후" in r.product_name


def test_판매시점을_모르는_약관은_후보에서_빠진다():
    v = PolicyVersion(
        insurer="삼성화재", product_name="x", sale_start="", sale_end="",
        generation=None, generation_label="", product_line="standard",
        sha256="y" * 64, date_confidence="unknown", generation_confidence="unknown",
    )
    assert not v.usable_for_judgment


def test_가입일_형식이_틀리면_거부한다():
    with pytest.raises(ValidationErr):
        resolve(insurer="삼성화재", enrolled_on="2019-05-01", versions=_POOL)


def test_상품_라인이_갈리면_반드시_되묻는다():
    """★일반 실손과 노후실손은 자기부담금 체계가 다르다. 골라 주면 안 된다."""
    pool = [
        _v("20220101", name="무배당 삼성화재 실손의료비보험"),
        PolicyVersion(
            insurer="삼성화재", product_name="무배당 삼성화재 노후실손의료비보험",
            sale_start="20220301", sale_end="", generation=None,
            generation_label="", product_line="senior", sha256="z" * 64,
            date_confidence="exact", generation_confidence="not_applicable",
        ),
    ]
    pool[0] = PolicyVersion(**{**pool[0].__dict__, "product_line": "standard"})
    r = resolve(insurer="삼성화재", enrolled_on="20220501", versions=pool)
    assert isinstance(r, NotResolved)
    assert r.reason_code == "ambiguous_product_line"
    assert {c.product_line for c in r.candidates} == {"standard", "senior"}


def test_자리표시자_날짜는_후보에서_빠진다():
    v = _v("00000000")
    assert not v.usable_for_judgment


def test_특약은_본약관과_경쟁하지_않는다():
    assert _v("20220101", name="실손의료비보장 안정화 할인 특별약관").is_rider
    assert not _v("20220101", name="무배당 삼성화재 실손의료비보험").is_rider


def test_판매시점_신뢰도가_없으면_정확하다고_하지_않는다():
    """★**fail-open 이었다.** `r.get("date_confidence", "exact")` 였다.

    실측 2026-08-04 — 매니페스트 2,121행 중 **1,702행에 이 키가 없다.**
    그 전부가 "판매시점을 정확히 안다"로 둔갑해 있었다. 판매시점을 모르면
    **어느 판본이 적용되는지도 모른다** — 2019년 가입자에게 다른 세대 약관을
    근거로 댈 수 있다.

    `identification` 게이트가 먼저 0건을 만들어 드러나지 않았을 뿐이다.
    확정 절차가 붙는 순간(6-5a) 조용히 새는 문이 된다.
    """
    from app.adapters.manifest_policy_resolver import _row_to_version

    #: 키 자체가 없는 경우 — 실제 매니페스트 1,702행의 모양이다.
    v = _row_to_version({"insurer": "삼성화재", "sha256": "a" * 64,
                         "sale_start": "20220101", "generation_review": "reviewed",
                         "identification": "confirmed"})
    assert v.date_confidence == "unknown"
    assert v.usable_for_judgment is False, "판매시점을 모르는데 판정에 쓰고 있습니다"

    #: 값이 비어 있는 경우도 같다. `""` 는 "안다"가 아니다.
    v2 = _row_to_version({"insurer": "삼성화재", "sha256": "a" * 64,
                          "sale_start": "20220101", "date_confidence": "",
                          "generation_review": "reviewed", "identification": "confirmed"})
    assert v2.date_confidence == "unknown"
    assert v2.usable_for_judgment is False

    #: ★막기만 하고 통과를 못 하면 그것도 고장이다.
    v3 = _row_to_version({"insurer": "삼성화재", "sha256": "a" * 64,
                          "sale_start": "20220101", "date_confidence": "exact",
                          "generation_review": "reviewed", "identification": "confirmed"})
    assert v3.usable_for_judgment is True
