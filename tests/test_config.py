"""config 단위 테스트 (LLM 호출 없음)."""

import pytest

from app.core.config import Settings, validate_agent_bind
from app.core.errors import ConfigError


def test_default_provider_is_local():
    s = Settings(_env_file=None)
    assert s.LLM_PROVIDER == "local"


def test_readiness_keys():
    s = Settings(_env_file=None)
    r = s.readiness()
    assert set(r.keys()) == {"local", "openai", "gemini", "db", "vector"}
    assert all(isinstance(v, bool) for v in r.values())


def test_local_ready_without_keys():
    s = Settings(_env_file=None)
    assert s.readiness()["local"] is True
    assert s.readiness()["openai"] is False
    assert s.readiness()["gemini"] is False


def test_database_url_default_sqlite(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    s = Settings(_env_file=None)
    assert s.DATABASE_URL.startswith("sqlite")
    assert s.DATABASE_URL.endswith("/data/db/insurance.sqlite3")
    assert s.DB_DIR == s.DATA_DIR / "db"


def test_openai_key_detection():
    s = Settings(_env_file=None, OPENAI_API_KEY="sk-test")
    assert s.has_openai_key() is True
    assert s.readiness()["openai"] is True


def test_agent_bind_default_is_loopback_and_customer_url_is_independent():
    settings = Settings(_env_file=None, CUSTOMER_BASE_URL="http://example.invalid:9999")
    assert validate_agent_bind(settings) == ("127.0.0.1", 8082)


@pytest.mark.parametrize("host", ["0.0.0.0", "::", "192.0.2.10", "agent.example.test"])
def test_agent_remote_bind_requires_explicit_opt_in(host):
    settings = Settings(
        _env_file=None,
        AGENT_BIND_HOST=host,
        ALLOW_REMOTE_AGENT_BIND=False,
    )
    with pytest.raises(ConfigError):
        validate_agent_bind(settings)


def test_agent_remote_bind_can_be_explicitly_enabled():
    settings = Settings(
        _env_file=None,
        AGENT_BIND_HOST="0.0.0.0",
        ALLOW_REMOTE_AGENT_BIND=True,
    )
    assert validate_agent_bind(settings) == ("0.0.0.0", 8082)
