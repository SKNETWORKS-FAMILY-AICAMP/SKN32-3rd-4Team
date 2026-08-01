"""명시적 운영 명령(REQ-OPS-01) — 기동 시 자동설정을 대체.

사용:
    python -m scripts.manage migrate   # 테이블 생성(멱등)
    python -m scripts.manage seed      # 상품 시딩(멱등)
    python -m scripts.manage ingest    # RAG 인덱스 빌드(없거나 stale일 때)
    python -m scripts.manage ready      # readiness 상태 출력

무폴백: 각 명령은 성공/실패를 명확히 보고하며, 실패를 삼키지 않는다.
"""

from __future__ import annotations

import argparse
import json
import sys


def _add_missing_columns(engine) -> list[str]:
    """기존 테이블에 빠진 컬럼을 멱등하게 추가한다.

    `create_all`은 **없는 테이블만** 만들고 기존 테이블에 컬럼을 추가하지 않는다. 그래서
    Phase 9의 `users.role`처럼 나중에 생긴 컬럼은 기존 DB에 반영되지 않아 조용히 깨진다.
    Alembic 없이 가는 대신 여기서 명시적으로 추가하고, 아래에서 **사후 검증**한다.
    """
    from sqlalchemy import inspect, text

    added: list[str] = []
    inspector = inspect(engine)
    if "users" not in inspector.get_table_names():
        return added  # create_all이 새로 만들었으면 스키마가 이미 최신
    columns = {c["name"] for c in inspector.get_columns("users")}
    if "role" not in columns:
        with engine.begin() as conn:
            # 기존 사용자는 전부 USER. 관리자 자동 승격은 하지 않는다.
            conn.execute(
                text("ALTER TABLE users ADD COLUMN role VARCHAR(20) DEFAULT 'USER'")
            )
            conn.execute(text("UPDATE users SET role = 'USER' WHERE role IS NULL"))
        added.append("users.role")
    return added


def _verify_schema(engine) -> None:
    """마이그레이션 사후 검증 — 기대 컬럼이 실제로 있는지 확인하고, 없으면 명시적 실패."""
    from sqlalchemy import inspect

    from app.core.errors import InfraError

    inspector = inspect(engine)
    columns = {c["name"] for c in inspector.get_columns("users")}
    if "role" not in columns:
        raise InfraError("마이그레이션 후에도 users.role 컬럼이 없습니다(스키마 검증 실패).")


def cmd_migrate() -> None:
    from app.db.database import Base, engine

    # 모든 모델이 Base에 등록되도록 import
    import app.db.models  # noqa: F401

    Base.metadata.create_all(bind=engine)
    added = _add_missing_columns(engine)
    _verify_schema(engine)
    if added:
        print(f"[migrate] 컬럼 추가: {', '.join(added)}")
    print("[migrate] 테이블 생성·스키마 검증 완료(멱등).")


def cmd_seed() -> None:
    from app.db.database import SessionLocal
    from app.db.seed import seed_products

    db = SessionLocal()
    try:
        result = seed_products(db)
    finally:
        db.close()
    print(f"[seed] 완료: {result}")


def cmd_ingest() -> None:
    from app.rag.build_index import build_index, index_is_current

    if index_is_current():
        print("[ingest] 인덱스가 최신 상태 — 건너뜀.")
        return
    build_index()
    print("[ingest] RAG 인덱스 빌드 완료.")


def cmd_ready() -> None:
    from app.obs.readiness import check_readiness

    status = check_readiness()
    print(json.dumps(status, ensure_ascii=False, indent=2))
    if not status["ready"]:
        sys.exit(1)  # 미준비는 비정상 종료(무폴백)


def set_role(username: str, role: str) -> str:
    """사용자 역할을 명시적으로 변경한다(멱등). 감사 이벤트를 남긴다.

    부트스트랩은 이 CLI **하나뿐**이다 — 환경변수·가입 시 자동 승격 같은 암묵 경로를 두면
    권한 상승 사고가 난다. 마지막 ADMIN 강등은 거부해 잠금(lockout)을 막는다.
    """
    from app.auth.roles import ROLE_ADMIN, validate_role
    from app.core.errors import NotFoundErr, ValidationErr
    from app.db.database import SessionLocal
    from app.db.models import User
    from app.obs.events import record_event

    validate_role(role)
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.username == username).first()
        if user is None:
            raise NotFoundErr(f"사용자를 찾을 수 없습니다: {username}")
        before = user.role
        if before == role:
            return f"변경 없음(이미 {role}): {username}"
        if before == ROLE_ADMIN and role != ROLE_ADMIN:
            remaining = (
                db.query(User).filter(User.role == ROLE_ADMIN, User.id != user.id).count()
            )
            if remaining == 0:
                raise ValidationErr("마지막 관리자는 강등할 수 없습니다(잠금 방지).")
        user.role = role
        db.commit()
        # 감사 기록: 누가/무엇을 바꿨는지 남긴다(원문·비밀 없음).
        record_event(db, "role_change", {"username": username, "from": before, "to": role})
        return f"역할 변경: {username} {before} → {role}"
    finally:
        db.close()


def cmd_promote(username: str) -> None:
    from app.auth.roles import ROLE_ADMIN

    print(f"[promote] {set_role(username, ROLE_ADMIN)}")


def cmd_demote(username: str) -> None:
    from app.auth.roles import ROLE_USER

    print(f"[demote] {set_role(username, ROLE_USER)}")


def purge_gaps(days: int) -> int:
    """보존기간이 지난 지식보강 큐 항목을 파기한다. 삭제 건수를 반환."""
    from datetime import datetime, timedelta

    from app.db.database import SessionLocal
    from app.db.models import KnowledgeGap

    cutoff = datetime.utcnow() - timedelta(days=days)
    db = SessionLocal()
    try:
        deleted = (
            db.query(KnowledgeGap)
            .filter(KnowledgeGap.created_at < cutoff)
            .delete(synchronize_session=False)
        )
        db.commit()
        return deleted
    finally:
        db.close()


def cmd_purge_gaps(days: int) -> None:
    print(f"[purge-gaps] {purge_gaps(days)}건 파기(보존 {days}일).")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="운영 관리 명령")
    parser.add_argument(
        "command",
        choices=["migrate", "seed", "ingest", "ready", "promote", "demote", "purge-gaps"],
    )
    parser.add_argument("target", nargs="?", help="promote/demote의 username")
    parser.add_argument("--days", type=int, default=90, help="purge-gaps 보존기간(일)")
    args = parser.parse_args(argv)

    if args.command in ("promote", "demote"):
        if not args.target:
            parser.error(f"{args.command}에는 username이 필요합니다.")
        (cmd_promote if args.command == "promote" else cmd_demote)(args.target)
        return
    if args.command == "purge-gaps":
        cmd_purge_gaps(args.days)
        return
    {"migrate": cmd_migrate, "seed": cmd_seed, "ingest": cmd_ingest, "ready": cmd_ready}[
        args.command
    ]()


if __name__ == "__main__":
    main()
