"""Readiness — 기동/데이터 분리(REQ-OPS-01, TEST-OPS-READY-001).

앱 기동 시 자동으로 테이블 생성·seed·인덱스 빌드를 하지 않는다(v3.2 ADR). 대신 명시적
migration/ingest(scripts/manage.py) 후 이 readiness가 준비 상태를 보고하고, 미준비면
조용히 진행하지 않고 명시적으로 알린다(무폴백).
"""

from __future__ import annotations

from sqlalchemy import inspect

from app.core.config import get_settings
from app.db.database import engine

# migration으로 생성돼야 하는 핵심 테이블(존재로 준비 여부 판정)
#: ★보험 서비스가 **쇼핑몰 테이블 때문에 "준비 안 됨"** 이 되고 있었다.
#:   (products · orders 는 커머스 실습 테이블이다 — legacy 로 옮겼다)
#:   지금 판정은 파일을 읽으므로 필수 테이블이 없다. DB 적재 후 다시 채운다.
_REQUIRED_TABLES: tuple[str, ...] = ()


def check_readiness() -> dict[str, object]:
    """DB 테이블·RAG 인덱스 준비 상태를 보고한다(실 모델 호출 없음)."""
    settings = get_settings()
    existing = set(inspect(engine).get_table_names())
    missing_tables = [t for t in _REQUIRED_TABLES if t not in existing]
    vector_dir = settings.VECTOR_DIR
    index_ready = (vector_dir / "index.faiss").exists() and (vector_dir / "index.pkl").exists()

    db_ready = not missing_tables
    return {
        "ready": db_ready and index_ready,
        "db_tables_ready": db_ready,
        "missing_tables": missing_tables,
        "vector_index_ready": index_ready,
        "hint": None
        if (db_ready and index_ready)
        else "먼저 `python -m scripts.manage migrate && python -m scripts.manage ingest` 실행",
    }
