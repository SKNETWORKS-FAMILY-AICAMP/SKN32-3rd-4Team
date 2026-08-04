"""signup SECRET_KEY preflight 회귀 테스트 (Codex 지적).

SECRET_KEY가 없으면 signup은 503으로 실패하고 유저를 생성하지 않아야 한다.
"""

import uuid

from app.core.config import Settings
from app.core.errors import ConfigError


def test_require_secret_key_raises_without_key():
    s = Settings(_env_file=None, SECRET_KEY=None)
    try:
        s.require_secret_key()
        assert False, "ConfigError 기대"
    except ConfigError:
        pass


def test_signup_preflight_no_user_created(monkeypatch):
    """SECRET_KEY 미설정 시 signup preflight가 유저 생성 전에 실패한다."""
    from app.db.database import SessionLocal
    from app.db.models import User
    from app.routers import auth as auth_router

    # get_settings를 secret 없는 설정으로 대체
    no_secret = Settings(_env_file=None, SECRET_KEY=None)
    monkeypatch.setattr(auth_router, "get_settings", lambda: no_secret)

    username = f"nosecret_{uuid.uuid4().hex[:8]}"
    db = SessionLocal()
    try:
        before = db.query(User).filter(User.username == username).count()
        raised = False
        try:
            #: ★`app.schemas.commerce` 는 레거시 격리 때 사라졌다.
            #:   `SignupRequest` 는 커머스가 아니라 인증 스키마라 `app.schemas.auth` 로 갔는데
            #:   이 테스트만 옛 경로를 붙들고 있어 격리 이후 계속 실패하고 있었다.
            from app.schemas.auth import SignupRequest

            auth_router.signup(SignupRequest(username=username, password="pass1234"), db=db)
        except ConfigError:
            raised = True
        assert raised
        after = db.query(User).filter(User.username == username).count()
        assert before == after == 0
    finally:
        db.close()
