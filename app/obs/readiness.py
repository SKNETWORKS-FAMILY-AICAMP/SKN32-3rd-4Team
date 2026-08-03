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
    out: dict[str, object] = {
        "ready": db_ready and index_ready,
        "db_tables_ready": db_ready,
        "missing_tables": missing_tables,
        "vector_index_ready": index_ready,
        "hint": None
        if (db_ready and index_ready)
        else "먼저 `python -m scripts.manage migrate && python -m scripts.manage ingest` 실행",
    }
    clause = _clause_index_state()
    out["clause_index"] = clause
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
    return out


def _clause_index_state() -> dict[str, object]:
    """인덱스 A 가 **승인 릴리스와 맞나.**

    ★왜 여기서도 보나 — 검색 경로가 막아 주기는 하지만, 그건 **요청이 와야**
      드러난다. 실측 2026-08-03 에 승인 세대 's5' 로 적재된 행이 0건인 채
      한참 있었는데 아무도 몰랐다. 준비 상태는 **묻기 전에** 말해야 한다.

    ★PG 가 없거나 못 붙어도 여기서 죽지 않는다 — 이 함수는 **보고**다.
      다만 "확인 못 함"과 "준비됨"을 **구분해서** 적는다. 섞으면 폴백이다.
    """
    try:
        from app.adapters import pgvector_clause_index as ix
        from app.adapters.pgvector_index import get_conn

        with get_conn() as conn:
            st = ix.index_state(conn)
    except Exception as exc:  # noqa: BLE001
        return {"checked": False, "reason": f"{type(exc).__name__}: {exc}"[:200]}
    st["checked"] = True
    if not st["ready"]:
        st["hint"] = ("승인 릴리스와 색인이 어긋납니다. "
                      "`python -m scripts.index.build_clause_index` 로 다시 적재하세요.")
    return st
