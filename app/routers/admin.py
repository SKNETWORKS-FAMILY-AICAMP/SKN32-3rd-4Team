"""관리자 라우터 (Phase 9) — **전부 ADMIN 전용**.

fail-closed 설계: 권한 검사를 엔드포인트마다 붙이면 새 엔드포인트에서 빠뜨리기 쉽다.
그래서 `APIRouter(dependencies=[Depends(require_admin)])`로 **라우터 단위**로 강제하고,
`/api/admin/*` 전 라우트가 이 의존성을 갖는지 가드레일 테스트로 고정한다.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.auth.roles import require_admin
from app.db.database import get_db
from app.db.models import KnowledgeGap, Order, RunEvent

# 라우터 전역 fail-closed — 여기 추가되는 모든 엔드포인트가 자동으로 ADMIN 전용이 된다.
router = APIRouter(
    prefix="/api/admin", tags=["admin"], dependencies=[Depends(require_admin)]
)


@router.get("/orders")
def admin_list_orders(
    db: Session = Depends(get_db), limit: int = Query(default=50, ge=1, le=200)
) -> list[dict]:
    """전체 주문 요약(최신순). 최소권한 관점에서 요약 필드만 노출한다."""
    rows = db.query(Order).order_by(Order.id.desc()).limit(limit).all()
    return [
        {
            "order_no": o.order_no,
            "user_id": o.user_id,
            "status": o.status,
            "total_amount": o.total_amount,
            "item_count": len(o.items),
        }
        for o in rows
    ]


@router.get("/events")
def admin_list_events(
    db: Session = Depends(get_db),
    trace_id: str | None = None,
    kind: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
) -> list[dict]:
    """관측 이벤트(run_events) 조회 — trace 상관 추적용.

    detail은 "요약만, 원문·PII 금지" 관례(RunEvent 독스트링)지만 자유 문자열이라 그 관례가
    깨질 수 있다. knowledge-gaps와 같은 이유로, 마스킹이 실제로 값을 바꾸면(=관례 위반 증거)
    응답은 안전하게 가리되 조용히 덮지 않고 감사기록을 남긴다(RULE.md 무폴백).
    """
    q = db.query(RunEvent)
    if trace_id:
        q = q.filter(RunEvent.trace_id == trace_id)
    if kind:
        q = q.filter(RunEvent.kind == kind)
    rows = q.order_by(RunEvent.id.desc()).limit(limit).all()

    from app.obs.events import record_event
    from app.obs.pii import mask_pii

    out = []
    for e in rows:
        masked = mask_pii(e.detail)
        if masked != e.detail:
            # detail 요약-only 불변식 위반 탐지 — 조용히 고치고 넘어가지 않고 신호를 남긴다.
            record_event(db, "run_event_unmasked_detected", {"event_id": e.id})
        out.append({"id": e.id, "trace_id": e.trace_id, "kind": e.kind, "detail": masked})
    return out


#: /index가 노출할 필드 화이트리스트. check_readiness()를 그대로 흘리면 내부 경로·구성이
#: 과다 노출될 수 있다(Codex 지적) → 명시한 것만 내보낸다.
_INDEX_FIELDS = ("ready", "db_tables_ready", "vector_index_ready", "missing_tables")


@router.get("/index")
def admin_index_status() -> dict:
    """RAG 인덱스·DB 준비 상태(읽기 전용, 허용 필드만)."""
    from app.obs.readiness import check_readiness

    status = check_readiness()
    return {k: status[k] for k in _INDEX_FIELDS if k in status}


@router.get("/report")
def admin_report(db: Session = Depends(get_db)) -> Response:
    """현재 대시보드 데이터(준비상태·주문·이벤트·지식갭)를 요약한 PDF 보고서.

    서버에도 `docs/generated_reports/`에 스냅샷을 저장하고, 같은 PDF를 다운로드로 반환한다.
    라우터 전역 require_admin으로 보호됨.
    """
    from datetime import datetime

    from app.services.admin_report import build_admin_report_pdf, save_admin_report

    now = datetime.now()
    save_admin_report(db)  # 서버 보관용 스냅샷
    pdf = build_admin_report_pdf(db, generated_at=now)
    filename = f"admin_report_{now.strftime('%Y%m%d_%H%M%S')}.pdf"
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/knowledge-gaps")
def admin_list_knowledge_gaps(
    db: Session = Depends(get_db),
    resolved: bool | None = None,
    limit: int = Query(default=50, ge=1, le=200),
) -> list[dict]:
    """지식보강 큐 — 근거 없어 답하지 못한 질문(PII 마스킹 후 저장된 형태).

    출력 시 다시 mask_pii를 거는 것은 "혹시 몰라서 조용히 덮는" 폴백이 되면 안 된다
    (RULE.md 무폴백 — 이상 상태를 발견하면 침묵하지 말 것). 그래서 마스킹 전/후 값이
    다르면 **저장 시 마스킹이 뚫렸다는 뜻**이므로, 응답은 안전하게 가리되(PII 미유출)
    그 사실을 run_events에 감사기록으로 남겨 조용히 덮지 않는다.
    """
    from app.obs.events import record_event
    from app.obs.pii import mask_pii

    q = db.query(KnowledgeGap)
    if resolved is not None:
        q = q.filter(KnowledgeGap.resolved == resolved)
    rows = q.order_by(KnowledgeGap.id.desc()).limit(limit).all()

    out = []
    for g in rows:
        masked = mask_pii(g.question)
        if masked != g.question:
            # 쓰기 경로 불변식 위반 탐지 — 조용히 고치고 넘어가지 않고 신호를 남긴다.
            record_event(db, "kgap_unmasked_detected", {"gap_id": g.id})
        out.append(
            {"id": g.id, "question": masked, "trace_id": g.trace_id, "resolved": g.resolved}
        )
    return out
