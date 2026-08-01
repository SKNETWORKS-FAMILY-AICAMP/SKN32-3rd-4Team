"""감성 분석 테스트 (실 KoELECTRA, @ml — CI 제외).

실행: pytest -m ml tests/test_sentiment.py
"""

import pytest

from app.core.errors import ValidationErr
from app.ml.sentiment import analyze_sentiment

pytestmark = pytest.mark.ml


def test_positive_sentiment():
    r = analyze_sentiment("이 제품 정말 좋아요. 배송도 빠르고 만족스러워요!")
    assert r["label"] == "긍정"
    assert 0.0 <= r["score"] <= 1.0


def test_negative_sentiment():
    r = analyze_sentiment("최악이에요. 고장난 상품이 왔고 환불도 안 돼요.")
    assert r["label"] == "부정"


def test_empty_raises():
    with pytest.raises(ValidationErr):
        analyze_sentiment("  ")
