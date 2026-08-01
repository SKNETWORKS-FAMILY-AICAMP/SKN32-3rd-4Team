"""테스트 공통 픽스처.

임시 SQLite DB + 테스트용 SECRET_KEY를 앱 import 전에 환경변수로 설정해 실 DB를
건드리지 않고 격리한다.
"""

from __future__ import annotations

import os
import tempfile
import uuid

# --- 앱 import 이전에 환경 설정 (엔진이 이 값으로 바인딩됨) ---
_TMP_DB = os.path.join(tempfile.gettempdir(), f"mall_test_{uuid.uuid4().hex}.db")
os.environ["DATABASE_URL"] = f"sqlite:///{_TMP_DB}"
os.environ["SECRET_KEY"] = "test-secret-key-do-not-use-in-prod"
os.environ["LLM_PROVIDER"] = "local"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.core.config import get_settings  # noqa: E402

get_settings.cache_clear()

from app.db.database import Base, engine  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def _prepare_db():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    #: ★커머스 상품을 시딩하지 않는다.
    #:   시딩 CSV 는 `legacy/` 로 옮겼고, **현행 코드가 레거시를 참조하면
    #:   레거시를 지울 수 없게 된다.** 지금 남은 테스트는 상품이 필요 없다.
    #:   보험 픽스처가 필요해지면 `tests/fixtures/` 에 따로 만든다.
    yield
    try:
        os.remove(_TMP_DB)
    except OSError:
        pass


@pytest.fixture
def client() -> TestClient:
    # lifespan을 다시 돌리지 않도록 이미 준비된 앱에 TestClient만 붙인다
    return TestClient(app)


@pytest.fixture
def unique_user():
    def _make():
        return f"user_{uuid.uuid4().hex[:8]}", "pass1234"

    return _make


def auth_header(client: TestClient, username: str, password: str) -> dict:
    client.post("/auth/signup", json={"username": username, "password": password})
    resp = client.post("/auth/login", data={"username": username, "password": password})
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


