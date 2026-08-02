"""실험실 테스트 (결정론 + mock)."""

import pytest

from app.core.errors import ConfigError, ValidationErr
from app.lab import experiments as X
from app.lab.usecase import build_usecase_prompt


def test_count_tokens_positive():
    assert X.count_tokens("안녕하세요") > 0


def test_token_compare_korean_uses_more():
    r = X.token_compare("안녕하세요 반갑습니다", "Hello nice to meet you")
    assert r["ko_tokens"] > r["en_tokens"]
    assert "참고치" in r["note"]


def test_estimate_cost_registered_model():
    r = X.estimate_cost(1_000_000, 1_000_000, "gpt-4o-mini")
    assert r["estimated_usd"] == round(0.15 + 0.60, 6)


def test_estimate_cost_local_not_registered_raises():
    with pytest.raises(ConfigError):
        X.estimate_cost(100, 100, "gemma-4-e4b")


def test_diversity_unique_count_with_mock():
    same = X.diversity("q", n=3, complete=lambda p, t, m, s: "동일답변")
    assert same["unique_count"] == 1
    seq = iter(["a", "b", "c"])
    diff = X.diversity("q", n=3, complete=lambda p, t, m, s: next(seq))
    assert diff["unique_count"] == 3


def test_diversity_n_out_of_range():
    with pytest.raises(ValidationErr):
        X.diversity("q", n=99)


def test_basic_call_mock():
    out = X.basic_call("질문", complete=lambda p, t, m, s: "답변")
    assert out == "답변"


def test_role_call_requires_system():
    with pytest.raises(ValidationErr):
        X.role_call("질문", "  ", complete=lambda p, t, m, s: "x")


def test_usecase_builders():
    assert "요약" in build_usecase_prompt("summary", "내용")
    assert "번역" in build_usecase_prompt("translation", "안녕", "영어")
    assert "이메일" in build_usecase_prompt("email", "환불 안내")


def test_usecase_unknown_task_raises():
    with pytest.raises(ValidationErr):
        build_usecase_prompt("dance", "내용")
