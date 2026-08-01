"""DB 엔진·세션·Base 정의."""

from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, declarative_base, sessionmaker

from app.core.config import get_settings

_settings = get_settings()

# SQLite + FastAPI(멀티스레드) 조합을 위해 check_same_thread=False
engine = create_engine(
    _settings.DATABASE_URL,
    connect_args={"check_same_thread": False} if _settings.DATABASE_URL.startswith("sqlite") else {},
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)

Base = declarative_base()


def get_db() -> Iterator[Session]:
    """요청 스코프 DB 세션 의존성."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
