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
