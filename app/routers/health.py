"""헬스 체크 라우터.

/api/health 는 LLM/네트워크 실호출 없이 '설정·키·경로 존재 여부'만 boolean으로
보고한다 (Codex 합의).
"""

from __future__ import annotations

from fastapi import APIRouter

from app.core.config import get_settings

router = APIRouter(prefix="/api", tags=["system"])


@router.get("/health")
def health() -> dict:
    settings = get_settings()
    return {
        "status": "ok",
        "provider": settings.LLM_PROVIDER,
        "readiness": settings.readiness(),
    }


@router.get("/health/ready")
def ready() -> dict:
    """데이터 준비 상태(DB 테이블·RAG 인덱스). 미준비면 명시적으로 알린다(REQ-OPS-01)."""
    from app.obs.readiness import check_readiness

    return check_readiness()
