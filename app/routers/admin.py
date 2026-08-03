"""관리자 라우터 (Phase 9) — **전부 ADMIN 전용**.

fail-closed 설계: 권한 검사를 엔드포인트마다 붙이면 새 엔드포인트에서 빠뜨리기 쉽다.
그래서 `APIRouter(dependencies=[Depends(require_admin)])`로 **라우터 단위**로 강제하고,
`/api/admin/*` 전 라우트가 이 의존성을 갖는지 가드레일 테스트로 고정한다.
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, Query, status
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth.roles import require_admin
from app.db.database import get_db
from app.db.models import KnowledgeGap, RunEvent

# 라우터 전역 fail-closed — 여기 추가되는 모든 엔드포인트가 자동으로 ADMIN 전용이 된다.
router = APIRouter(
    prefix="/api/admin", tags=["admin"], dependencies=[Depends(require_admin)]
)

#: ★`/orders` 는 제거했다(2026-08-04). 커머스 잔재이고 v4.0 §2-3 폐기 대상이다.
#:   화면에서만 숨기면 죽은 엔드포인트가 남아 다음 사람이 또 판단해야 한다.
#:   보관본은 `legacy/v3_commerce.zip`.


class DemoVerifyRequest(BaseModel):
    """합성 제출 승격 요청.

    ★`verification_method` 를 클라이언트가 고르지 못하게 한다 —
      이 경로로 들어온 것은 정의상 `admin_review` 다. 고르게 하면
      화면에서 `simulated` 를 눌러 놓고 "관리자가 검수했다"고 말할 수 있다.
    """

    submission_id: str = Field(min_length=1)


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


#: SSE 꼬리읽기 주기. 화면 체감(≤0.5초)과 파일 stat 비용 사이의 절충.
_STREAM_POLL_S = 0.4


# ── 에이전트 관측 ─────────────────────────────────────────────────────────
#
# ★"접속 중"이라고 말하지 않는다. HTTP 는 연결을 유지하지 않으므로 우리가 아는 것은
#   **마지막 요청이 언제였나** 뿐이다. 화면에도 `idle_s` 로 표시한다.


@router.get("/agents")
def admin_agents() -> dict:
    """붙어 있는 에이전트 요약 + 최근 상호작용.

    ★출처를 밝힌다 — 이 목록은 **인메모리 링버퍼**라 재시작하면 사라진다.
      "기록이 없다"가 "그런 일이 없었다"는 뜻이 아니다(감사는 `run_events`).
    """
    from app.obs import agent_stream

    return {
        "agents": agent_stream.agents(),
        "recent": agent_stream.recent(limit=50),
        "volatile": True,
        "note": "관측용 append-only 파일입니다(고객·운영 두 프로세스가 공유). "
                "감사 기록은 run_events 입니다 — 여기 없다고 그런 일이 없었던 것은 아닙니다.",
    }


@router.get("/agents/stream")
async def admin_agents_stream() -> StreamingResponse:
    """에이전트 상호작용 SSE. 대시보드 타임라인이 이걸 구독한다.

    ★**파일 꼬리읽기**다. 고객 서버(8080)와 운영 서버(8081)는 다른 프로세스라
      인메모리 큐로는 고객 쪽 트래픽이 대시보드에 안 보인다(실측으로 잡았다).
    """
    from app.obs import agent_stream

    async def gen():
        #: 붙자마자 최근 것을 한 번 밀어준다(빈 화면으로 시작하지 않게).
        yield agent_stream.sse({"kind": "_snapshot", "items": agent_stream.recent(30)})
        offset = agent_stream.current_offset()
        idle = 0.0
        while True:
            await asyncio.sleep(_STREAM_POLL_S)
            offset, events = agent_stream.read_from(offset)
            if events:
                idle = 0.0
                for ev in events:
                    yield agent_stream.sse(ev)
                continue
            idle += _STREAM_POLL_S
            if idle >= 15:
                idle = 0.0
                #: ★주석 프레임으로 연결을 살려 둔다. 프록시가 유휴 연결을 끊는다.
                yield ": keep-alive\n\n"

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ── 합성(데모) 트랙 검수 ──────────────────────────────────────────────────
#
# ★★경로에 `demo` 가 들어가는 것이 **의도**다. 실제 트랙에는 이 API 가 없다.
#   실제 사례의 승격은 증빙 검수 절차가 정해진 뒤에 별도로 만든다 —
#   지금 만들면 "관리자가 눌렀다"가 "검증됐다"로 둔갑한다.


@router.get("/demo/queue")
def admin_demo_queue(limit: int = Query(default=50, ge=1, le=200)) -> dict:
    """합성 트랙 검수 대기 목록. **승격되지 않은 것만** 나온다."""
    from app.adapters import demo_submission_store as demo

    return {
        "data_source": "synthetic",
        "counts": demo.counts(),
        "pending": demo.pending(limit=limit),
    }


@router.post("/demo/verifications", status_code=status.HTTP_201_CREATED)
def admin_demo_verify(body: DemoVerifyRequest, user=Depends(require_admin)) -> dict:
    """합성 제출 하나를 승격한다 → 이 순간 합성 코호트 `n` 이 +1 된다.

    ★승격 방법을 응답에 그대로 실어 보낸다(`verification_method`).
      이 숫자가 어떻게 생겼는지 나중에 설명할 수 있어야 한다.
    """
    from app.adapters import demo_submission_store as demo
    from app.obs import agent_stream

    event = demo.promote(
        body.submission_id, method=demo.METHOD_ADMIN, actor=getattr(user, "username", "admin")
    )
    agent_stream.publish(
        "admin.verify",
        client_ref=str(event.get("client_ref") or "-"),
        track="synthetic",
        detail={"submission_id": event["submission_id"], "outcome": event.get("outcome"),
                "method": event["verification_method"]},
    )
    return {"promoted": True, "event": event, "counts": demo.counts()}


# ── 판정 모드(문서 확정 게이트) ───────────────────────────────────────────
#
# ★이 스위치는 **어떤 약관으로 판정할지**를 바꾼다. 시뮬레이션 제어와 성격이 완전히 다르다 —
#   저쪽은 합성 데이터를 만들 뿐이지만, 이쪽은 **고객이 받는 답**을 바꾼다.
#   그래서 바꾼 사람·시각을 파일에 남기고, 감사 로그와 관측 스트림에 모두 알린다.


class PrecheckModeRequest(BaseModel):
    """`true` 면 기계 대조까지만 끝난 문서도 판정에 쓴다(시연)."""

    auto_approve: bool


@router.get("/precheck-mode")
def admin_precheck_mode() -> dict:
    from app.core.domain import identification_mode
    from app.routers import precheck as precheck_router

    state = identification_mode.current().as_dict()
    #: ★모드만 보여주면 "켜면 몇 건이 되는지"를 모른다. 판단에 필요한 수를 함께 낸다.
    state["stats"] = precheck_router._confirmation_stats()
    state["usable_now"] = len(precheck_router._versions())
    return state


@router.put("/precheck-mode")
def admin_set_precheck_mode(
    body: PrecheckModeRequest, db: Session = Depends(get_db), user=Depends(require_admin)
) -> dict:
    """판정 모드를 바꾼다. **캐시를 반드시 비운다.**

    ★표시와 동작이 어긋나는 것을 막는 자리다 — 화면에는 "엄격"이라 적혀 있는데
      판정은 캐시된 자동승인 목록으로 계속 나가면 그게 최악이다.
    """
    from app.core.domain import identification_mode
    from app.obs import agent_stream
    from app.obs.events import record_event
    from app.routers import precheck as precheck_router

    actor = getattr(user, "username", "admin")
    mode = (identification_mode.MACHINE_MATCH if body.auto_approve
            else identification_mode.HUMAN_SIGNOFF)
    state = identification_mode.set_mode(mode, actor=actor)
    precheck_router.invalidate_versions_cache()

    #: 감사 기록(DB)과 관측 스트림(화면) 양쪽에 남긴다 — 성격이 다른 두 독자다.
    record_event(db, "precheck_mode_changed", {"mode": state.mode, "by": actor})
    agent_stream.publish("mode.change", client_ref=actor,
                         detail={"mode": state.mode, "auto_approve": state.auto_approve})

    out = state.as_dict()
    out["usable_now"] = len(precheck_router._versions())
    return out


# ── 실제 트랙 증빙 검수 ───────────────────────────────────────────────────
#
# ★★**이름을 `verified` 라고 하지 않는다.**
#
#   부트캠프 범위에서 발행처 API 확인은 불가능하다. 관리자가 할 수 있는 것은
#   **교차검증**뿐이고, 그것을 `verified` 라 부르면 "보험사가 그렇게 결정했음이
#   확인됐다"는 뜻이 되어 버린다. 실제로 확인된 것은 "관리자가 보고 납득했다"이다.
#   그래서 등급 이름을 `admin_attested` 로 둔다 — 계획서 §3 이 지적한
#   "정합성 검증을 사실성 검증으로 부르지 않는다"와 같은 계열이다.


class RealVerifyRequest(BaseModel):
    submission_id: str = Field(min_length=1)
    #: ★관리자가 무엇을 근거로 납득했는지. 비워 둘 수 없다 —
    #:   근거 없는 승격은 나중에 설명할 수 없다.
    basis: str = Field(min_length=5)


@router.get("/verifications/queue")
def admin_real_queue(limit: int = Query(default=50, ge=1, le=200)) -> dict:
    """실제 트랙 검수 대기 목록."""
    from app.adapters import external_submission_store as store

    return {
        "data_source": "verified_real",
        "counts": store.counts(),
        "pending": store.pending(limit=limit),
        "note": "관리자 교차검증으로만 승격됩니다(admin_attested). 발행처 확인이 아닙니다.",
    }


@router.post("/verifications", status_code=status.HTTP_201_CREATED)
def admin_real_verify(body: RealVerifyRequest, user=Depends(require_admin)) -> dict:
    """실제 제보 하나를 **관리자 교차검증**으로 승격한다.

    ★승격해도 등급은 `admin_attested` 다. 코호트 응답은 이 등급의 건수를
      따로 세어 보여준다 — "n=5" 를 "5건 발행처 확인됨"으로 읽지 않게.
    """
    from app.adapters import external_submission_store as store
    from app.obs import agent_stream

    event = store.attest(
        body.submission_id, basis=body.basis, actor=getattr(user, "username", "admin")
    )
    agent_stream.publish(
        "admin.attest", client_ref=str(event.get("client_ref") or "-"),
        track="verified_real",
        detail={"submission_id": event["submission_id"], "outcome": event.get("outcome"),
                "method": event["verification_method"]},
    )
    return {"attested": True, "event": event, "counts": store.counts()}


# ── 시뮬레이션 제어 ───────────────────────────────────────────────────────
#
# ★경로에 `demo` 가 들어간다. 이 제어가 만들 수 있는 것은 **합성 데이터뿐**이다.
#   실제 트랙을 만들거나 지우는 버튼은 없다 — 있으면 언젠가 눌린다.


class SimulationStartRequest(BaseModel):
    """시뮬레이션 파라미터. 상한은 어댑터가 검증한다(화면·CLI 가 같은 규칙을 쓰도록)."""

    agents: int = Field(default=12, ge=1)
    cases: int = Field(default=3, ge=1)
    #: 비우면 8종 무작위. 좁히면 한 코호트에 표본이 몰려 최소표본 게이트를 넘는 장면을 만든다.
    codes: list[str] = Field(default_factory=list)
    delay_ms: int = Field(default=150, ge=0, le=5000)
    auto_verify: bool = False
    #: ★고정 시드. 발표 때마다 숫자가 달라지면 "그때 그 화면"을 다시 못 만든다.
    seed: int = 20260804
    #: 비우면 설정값(`CUSTOMER_BASE_URL`). 가상 에이전트는 **실제 HTTP 로** 붙는다.
    base: str = ""


@router.get("/demo/simulation")
def admin_simulation_status() -> dict:
    from app.adapters import demo_simulator

    return demo_simulator.status()


@router.post("/demo/simulation")
def admin_simulation_start(body: SimulationStartRequest) -> dict:
    """시작. 이미 실행 중이면 409 — 조용히 덮어쓰지 않는다."""
    from app.adapters import demo_simulator
    from app.core.config import get_settings
    from app.obs import agent_stream

    base = body.base.strip() or get_settings().CUSTOMER_BASE_URL
    state = demo_simulator.start(
        base=base, agents=body.agents, cases=body.cases, codes=body.codes,
        delay_ms=body.delay_ms, auto_verify=body.auto_verify, seed=body.seed,
    )
    agent_stream.publish(
        "sim.start", client_ref="simulator", track="synthetic",
        detail={"agents": body.agents, "cases": body.cases,
                "auto_verify": body.auto_verify, "base": base},
    )
    return state


@router.delete("/demo/simulation")
def admin_simulation_stop() -> dict:
    """정지 **요청**. 루프가 다음 건에서 스스로 멈춘다(강제 종료 없음)."""
    from app.adapters import demo_simulator
    from app.obs import agent_stream

    state = demo_simulator.stop()
    agent_stream.publish("sim.stop", client_ref="simulator", track="synthetic",
                         detail={"requested": True})
    return state


@router.post("/demo/reset")
def admin_demo_reset(user=Depends(require_admin)) -> dict:
    """합성 트랙을 비운다.

    ★★**실제 트랙은 이 API 가 지울 수 없다.** 어댑터가 합성 경로만 알고 있다.
    """
    from app.adapters import demo_simulator
    from app.obs import agent_stream

    result = demo_simulator.reset()
    agent_stream.publish(
        "demo.reset", client_ref=getattr(user, "username", "admin"),
        track="synthetic", detail={"removed": result["removed"]},
    )
    return result


@router.get("/cohort-summary")
def admin_cohort_summary(code: str = Query(default="S72.0")) -> dict:
    """두 트랙을 **나란히** 보여준다 — 화면에서 섞이지 않게 라벨을 붙여서.

    ★두 값을 합치지 않는다. 합계 필드를 만들지 않는다.
    """
    from app.core.domain.insurance import DataSource, KcdCode
    from app.composition import build_cohort

    q = build_cohort()
    kc = KcdCode(version_label="", code=code.strip().upper(), name_ko="")
    out = {}
    for src in (DataSource.VERIFIED_REAL, DataSource.SYNTHETIC):
        ans = q.run(kcd_code=kc, product_id="", age_band=None, data_source=src)
        out[src.value] = {
            "n": ans.stats.n,
            "approved_n": ans.stats.approved_n,
            "denied_n": ans.stats.denied_n,
            "min_sample": ans.stats.min_sample,
            "min_sample_met": ans.stats.n >= ans.stats.min_sample,
            "approval_rate": ans.approval_rate,
            "approval_ci": list(ans.approval_ci) if ans.approval_ci else None,
            "headline": ans.headline,
        }
    return {"code": kc.code, "tracks": out}
