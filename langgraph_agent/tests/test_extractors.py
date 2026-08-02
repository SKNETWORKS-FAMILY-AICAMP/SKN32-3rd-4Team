"""
tests/test_extractors.py

역할:
    graph/extractors.py의 연령대/세대 추출 로직을 검증한다.
    특히 "경계 연도는 확정하지 않고 None을 반환한다"는 안전장치가
    실제로 지켜지는지가 핵심이다 (틀린 세대로 확정하면 오답으로 이어짐).
"""

from graph.extractors import extract_age_group, extract_generation, generation_type_to_label


def test_extract_age_group_from_native_form():
    assert extract_age_group("저 30대인데 우울증이 있어요") == "30대"


def test_extract_age_group_from_age_number():
    assert extract_age_group("35살인데 보장되나요") == "30대"
    assert extract_age_group("42세 남성입니다") == "40대"


def test_extract_age_group_filters_false_positives():
    # "3대 질환", "2대 보험사" 같은 표현은 나이가 아니므로 걸러야 한다
    assert extract_age_group("암은 3대 질환 중 하나죠") is None
    assert extract_age_group("2대 보험사 상품 비교") is None


def test_extract_age_group_no_match():
    assert extract_age_group("우울증 보장되나요") is None


def test_extract_generation_clear_years():
    assert extract_generation("2020년에 가입했어요") == "3세대"
    assert extract_generation("2022년 가입") == "4세대"
    assert extract_generation("05년도에 가입했어요") == "1세대"  # 2005년 -> 1세대
    assert extract_generation("2012년에 가입") == "2세대"


def test_extract_generation_boundary_years_are_ambiguous():
    # 월 정보 없이는 세대를 확정할 수 없어야 한다 (임의로 찍으면 안 됨)
    assert extract_generation("2009년에 가입") is None
    assert extract_generation("2017년에 가입") is None
    assert extract_generation("2021년에 가입") is None
    assert extract_generation("2026년에 가입") is None


def test_extract_generation_no_match():
    assert extract_generation("우울증 보장되나요") is None


def test_generation_type_to_label():
    assert generation_type_to_label(1) == "1세대"
    assert generation_type_to_label(3) == "3세대"
    assert generation_type_to_label(None) is None
    assert generation_type_to_label(9) is None  # 정의 안 된 값