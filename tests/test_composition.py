"""app/composition.py::build_precheck() -- 이 브랜치가 지원 안 하는
CLAUSE_STORE 값이면 raw ImportError 대신 ConfigError로 명시적으로 실패하는지
확인한다."""

import pytest

import app.composition as composition
from app.core.errors import ConfigError


def test_기본값은_file_어댑터를_돌려준다(monkeypatch):
    monkeypatch.setattr(composition, "_CLAUSE_STORE", "file")
    deps = composition.build_precheck()
    assert deps["clauses"].__name__ == "app.adapters.file_clause_store"


def test_지원_안_하는_값이면_ConfigError(monkeypatch):
    """★예전엔 CLAUSE_STORE=pg일 때 존재하지 않는 app.adapters.pg_clause_store를
    import하려다 raw ImportError가 그대로 터졌다(이 브랜치엔 그 어댑터가 없음)."""
    monkeypatch.setattr(composition, "_CLAUSE_STORE", "pg")
    with pytest.raises(ConfigError, match="file"):
        composition.build_precheck()


def test_오타여도_ConfigError(monkeypatch):
    monkeypatch.setattr(composition, "_CLAUSE_STORE", "flie")
    with pytest.raises(ConfigError):
        composition.build_precheck()
