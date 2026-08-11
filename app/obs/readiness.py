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
_SQLITE_AUTH_TABLES = ("users", "face_credentials")
_SQLITE_OPS_TABLES = ("run_events", "knowledge_gaps")


def _required_sqlite_tables(settings) -> tuple[str, ...]:
    """Return tables required by the active SQLite-backed application paths."""
    required = (
        set(_REQUIRED_TABLES)
        if getattr(settings, "SQLITE_LEGACY_ENABLED", True)
        else set()
    )
    if getattr(settings, "AUTH_PERSISTENCE", "sqlite") == "sqlite":
        required.update(_SQLITE_AUTH_TABLES)
    if getattr(settings, "OPS_PERSISTENCE", "sqlite") == "sqlite":
        required.update(_SQLITE_OPS_TABLES)
    return tuple(sorted(required))


def check_readiness() -> dict[str, object]:
    """DB 테이블·RAG 인덱스 준비 상태를 보고한다(실 모델 호출 없음)."""
    settings = get_settings()
    sqlite_enabled = getattr(settings, "SQLITE_LEGACY_ENABLED", True)
    required_sqlite_tables = _required_sqlite_tables(settings)
    if sqlite_enabled:
        existing = set(inspect(engine).get_table_names())
    else:
        existing = set()
    missing_tables = [t for t in required_sqlite_tables if t not in existing]
    sqlite_configuration_error = not sqlite_enabled and bool(required_sqlite_tables)
    vector_dir = settings.VECTOR_DIR
    index_ready = (vector_dir / "index.faiss").exists() and (vector_dir / "index.pkl").exists()

    db_ready = not missing_tables
    if sqlite_configuration_error:
        readiness_hint = (
            "SQLite 저장 경로가 선택되어 있습니다. SQLite를 사용하려면 "
            "`SQLITE_LEGACY_ENABLED=true`로 설정하세요."
        )
    elif db_ready and index_ready:
        readiness_hint = None
    else:
        readiness_hint = "먼저 `python -m scripts.manage migrate && python -m scripts.manage ingest` 실행"
    out: dict[str, object] = {
        "ready": db_ready and index_ready,
        "db_tables_ready": db_ready,
        "missing_tables": missing_tables,
        "vector_index_ready": index_ready,
        "hint": readiness_hint,
    }
    clause = _clause_index_state()
    out["clause_index"] = clause
    from app.core.candidate_fact_registry import check_candidate_fact_sources

    candidates = check_candidate_fact_sources()
    out["candidate_fact_sources"] = candidates
    if not candidates.get("ready"):
        out["ready"] = False
        out["hint"] = "candidate fact 산출물 무결성 검증에 실패했습니다."
    #: ★**지금 쓰는 저장소가 요구하는 것만** 준비 조건에 넣는다.
    #:
    #:   `CLAUSE_STORE=file` 이면 인덱스 A 가 비어도 판정은 돈다 —
    #:   그때 `ready:false` 로 만들면 늘 미준비라 아무도 안 본다.
    #:   반대로 `pg` 인데 색인이 어긋나면 **검색이 전부 실패**하므로
    #:   `ready:true` 라고 말하면 거짓이다.
    #:   실측 2026-08-03: 하위는 false 인데 상위가 true 였다.
    from app.composition import _clause_store_kind

    if _clause_store_kind() == "pg" and not clause.get("ready"):
        out["ready"] = False
        out["hint"] = clause.get("hint") or "인덱스 A 가 준비되지 않았습니다."
    from app.adapters.demo_submission_store import backend_name as demo_backend

    if demo_backend() == "postgres":
        from app.adapters.pg_demo_submission_store import readiness as demo_readiness

        demo = demo_readiness()
    else:
        demo = {"backend": "file", "ready": True}
    out["demo_store"] = demo
    if not demo.get("ready"):
        out["ready"] = False
        out["hint"] = (
            "합성 PostgreSQL 저장소가 준비되지 않았습니다. "
            "insurance_demo DB에 demo migration을 적용하세요."
        )
    return out


def _clause_index_state() -> dict[str, object]:
    """인덱스 A 가 **승인 릴리스와 맞나.**

    ★왜 여기서도 보나 — 검색 경로가 막아 주기는 하지만, 그건 **요청이 와야**
      드러난다. 실측 2026-08-03 에 승인 세대 's5' 로 적재된 행이 0건인 채
      한참 있었는데 아무도 몰랐다. 준비 상태는 **묻기 전에** 말해야 한다.

    ★PG 가 없거나 못 붙어도 여기서 죽지 않는다 — 이 함수는 **보고**다.
      다만 "확인 못 함"과 "준비됨"을 **구분해서** 적는다. 섞으면 폴백이다.
    """
    #: ★★**절대 매달리지 않는다.** 준비 상태는 **보고**이지 작업이 아니다.
    #:
    #:   실측 2026-08-03 — 이 함수가 연 연결이 `idle in transaction` 으로
    #:   **3시간 9분** 남아 `policy_clause_chunk` 에 읽기 락을 쥐고 있었다.
    #:   그 뒤로 병행 트랙의 `ALTER TABLE ... ADD COLUMN` 이 막히고,
    #:   그 뒤로 다시 이 함수의 조회 **12개**가 줄줄이 밀렸다.
    #:   그 상태로 테스트를 돌리니 **64% 에서 15분 넘게 멈췄다.**
    #:
    #:   세 가지가 겹쳤다 —
    #:     ① 읽고 나서 트랜잭션을 **안 닫았다**(SELECT 도 트랜잭션을 연다)
    #:     ② 시간 제한이 **없었다** — 락을 만나면 영원히 기다린다
    #:     ③ `pg` 마커가 없는 테스트 경로에서 **PG 를 요구했다**
    try:
        from app.adapters import pgvector_clause_index as ix
        from app.adapters.pgvector_index import get_conn

        conn = get_conn()
        try:
            #: ★락을 만나면 **기다리지 않고 실패한다.** 보고하려다 남을 막으면 안 된다.
            with conn.cursor() as cur:
                cur.execute("SET LOCAL lock_timeout = '2s'")
                cur.execute("SET LOCAL statement_timeout = '5s'")
            st = ix.index_state(conn)
        finally:
            #: ★**읽기만 했어도 닫는다.** 이걸 안 해서 3시간짜리 락이 생겼다.
            try:
                conn.rollback()
            finally:
                conn.close()
    except Exception as exc:  # noqa: BLE001
        #: ★"확인 못 함"과 "준비됨"을 **구분해서** 적는다. 섞으면 그게 폴백이다.
        return {"checked": False, "reason": f"{type(exc).__name__}: {exc}"[:200]}
    st["checked"] = True
    if not st["ready"]:
        st["hint"] = ("승인 릴리스와 색인이 어긋납니다. "
                      "`python -m scripts.index.build_clause_index` 로 다시 적재하세요.")
    return st
