"""FastAPI 진입점 — 고객/운영 분리 지원.

앱 조립: trace 미들웨어 + 예외 핸들러 + 라우터 + 정적 UI. 기동 시 자동 DB/인덱스 설정은
하지 않는다(REQ-OPS-01) — 명시적 `scripts.manage`로 준비하고 `/api/health/ready`로 확인한다.

**고객 웹 ↔ 운영 도구 분리(실제 프로덕션 패턴 축소판)**: 실무에선 고객 사이트와 관리자
대시보드를 별도 서비스/포트/서브도메인으로 나누고, 관리자 쪽은 VPN·사내망 뒤에 둔다. 여기서는
세 가지 앱을 제공한다:
  - `app`          : 전체(모든 라우터) — 테스트·개발 편의용 기본.
  - `customer_app` : **관리자 + 운영/내부 API 라우터(rag/nlp/lab/mcp/workflow) 미포함** + 운영
                     페이지 정적 차단 → 공개 포트(8080)용. 이 포트에서 `/api/admin/*`·`/api/rag/*`
                     등은 **물리적으로 404**(라우터가 없음).
  - `admin_app`    : 전체(관리자 대시보드 + 운영 도구) → 내부 포트(8081)용.
운영 스크립트: `run_customer_server.py`(customer 8080), `run_admin_server.py`(admin 8081).
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

from app.core.config import get_settings
from app.core.errors import register_exception_handlers
from app.obs.trace import TraceMiddleware
from app.routers import (
    admin,
    auth,
    bounty,
    cohort,
    face,
    health,
    lab,
    precheck,
    rag,
    voice,
    workflow,
)

#: ★커머스 라우터(products/orders/payments)와 이름만 A2A 인 `a2a` 라우터는
#:   저장소 루트 `legacy/v3_commerce/` 로 옮겼다.
#:   코드는 보존하되 **API 표면에서 뺀다** — 보험 API 문서에 `/api/products` 가
#:   섞이면 쓰는 사람이 혼란스럽다. 되살리려면 여기서 다시 import 하면 된다.

_STATIC_DIR = Path(__file__).resolve().parent / "static"

# 고객 포트에서 서빙하지 않을 운영/개발 정적 페이지·스크립트(고객 웹 노출 금지).
_OPS_STATIC = {
    "admin.html", "admin.js", "facebench.html", "facebench.js",
    "mcp.html", "mcp.js", "rag.html", "rag.js", "orders.html", "orders.js",
}


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # 기동 시 자동 create_all/seed/index를 하지 않는다(REQ-OPS-01, Phase 2).
    # 데이터 준비는 명시적 명령으로: `python -m scripts.manage migrate|seed|ingest`.
    # 준비 상태는 GET /api/health/ready 로 확인(미준비 시 명시적으로 알림, 무폴백).
    yield


def create_app(role: str = "full") -> FastAPI:
    """role: full(전체) | customer(관리자 제외·운영페이지 차단) | admin(전체·관리자 랜딩)."""
    settings = get_settings()
    suffix = {"customer": " (고객)", "admin": " (운영)", "full": ""}.get(role, "")
    app = FastAPI(
        #: 커머스 실습에서 보험 판정으로 도메인이 바뀌었다.
        title=f"{settings.BRAND_NAME} 보험 보장 판정 에이전트{suffix}",
        version="0.3.0",
        lifespan=lifespan,
    )
    app.add_middleware(TraceMiddleware)
    register_exception_handlers(app)

    # 고객 웹이 실제로 호출하는 공개 라우터(shop/video/mypage/AI상담 = 상품·주문·결제·에이전트·
    # 음성·얼굴). 이 집합만 고객 포트(8080)에 노출한다.
    app.include_router(health.router)
    app.include_router(auth.router)
    #: 보험 보장 사전판정 — 이 프로젝트의 본체다.
    app.include_router(precheck.router)
    app.include_router(cohort.router)
    app.include_router(voice.router)
    app.include_router(face.router)

    # 운영/내부 API 라우터: 분석·프로토콜·개발 도구(rag/nlp/lab/mcp/workflow)와 관리자(admin).
    # 고객 앱에는 **싣지 않는다** → 고객 포트에서 이들 경로는 물리적으로 404(무인증 노출·DoS 표면
    # 축소). 어떤 고객 페이지도 이 엔드포인트들을 호출하지 않는다(rag/mcp는 운영 페이지 전용).
    if role != "customer":
        app.include_router(rag.router)
        app.include_router(lab.router)
        app.include_router(bounty.router)
        app.include_router(workflow.router)
        app.include_router(admin.router)

    # 고객 앱은 운영/개발 정적 페이지를 차단(정적 마운트보다 먼저 매칭됨).
    if role == "customer":
        @app.get("/static/{filename}", include_in_schema=False)
        def _block_ops_static(filename: str):
            if filename in _OPS_STATIC:
                return PlainTextResponse("운영 도구는 관리자 포트에서 접근하세요.", status_code=404)
            target = _STATIC_DIR / filename
            if not target.is_file():
                return PlainTextResponse("Not Found", status_code=404)
            return FileResponse(str(target))

    app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")

    #: ★없는 파일을 반환하고 있었다.
    #:   `shop.html` · `index.html` 은 커머스 화면이라 `legacy/` 로 옮겼는데
    #:   여기 이름이 그대로 남아 500 이 났다. 보험 화면은 아직 없다.
    #:   **없는 것을 있는 척하지 않는다** — 무엇이 없는지 말하고 API 로 안내한다.
    landing = {"admin": "admin.html"}.get(role, "")

    @app.get("/", include_in_schema=False)
    def index():
        target = _STATIC_DIR / landing if landing else None
        if target and target.is_file():
            return FileResponse(str(target))
        return PlainTextResponse(
            "올바른 보험비서 — 보장 사전판정 API\n"
            "\n"
            "  POST /v1/prechecks         보장 사전판정\n"
            "  GET  /v1/support-manifest  무엇을 지원하는지\n"
            "  GET  /docs                 API 문서\n"
            "\n"
            "웹 화면은 아직 없습니다.\n",
            status_code=200,
        )

    return app


app = create_app("full")            # 테스트·개발 편의(전체)
customer_app = create_app("customer")  # 공개 포트(8080) — 관리자 API·운영 페이지 없음
admin_app = create_app("admin")     # 내부 포트(8081) — 전체
