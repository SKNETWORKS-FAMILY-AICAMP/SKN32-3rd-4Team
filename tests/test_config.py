"""config 단위 테스트 (LLM 호출 없음)."""

from app.core.config import Settings


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
