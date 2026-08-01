"""감성 라벨 해석 로직 테스트 (모델 로드 없이, CI 포함)."""

import pytest

from app.core.errors import ConfigError
from app.ml.sentiment import _resolve_label


class _FakeCfg:
    def __init__(self, id2label):
        self.id2label = id2label


class _FakeModel:
    def __init__(self, id2label):
        self.config = _FakeCfg(id2label)


class _FakePipe:
    def __init__(self, id2label):
        self.model = _FakeModel(id2label)


def test_resolve_direct_label():
    pipe = _FakePipe({0: "negative", 1: "positive"})
    assert _resolve_label("positive", pipe) == "positive"


def test_resolve_label_index():
    pipe = _FakePipe({0: "negative", 1: "positive"})
    assert _resolve_label("LABEL_1", pipe) == "positive"
    assert _resolve_label("LABEL_0", pipe) == "negative"


def test_resolve_unknown_index_raises():
    pipe = _FakePipe({0: "negative", 1: "positive"})
    with pytest.raises(ConfigError):
        _resolve_label("LABEL_5", pipe)


def test_resolve_unexpected_label_raises():
    pipe = _FakePipe({0: "neutral"})
    with pytest.raises(ConfigError):
        _resolve_label("LABEL_0", pipe)


def test_resolve_garbage_raises():
    pipe = _FakePipe({0: "negative", 1: "positive"})
    with pytest.raises(ConfigError):
        _resolve_label("웃김", pipe)
