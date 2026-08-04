"""헬스 체크 라우터.

/api/health 는 LLM/네트워크 실호출 없이 '설정·키·경로 존재 여부'만 boolean으로
보고한다 (Codex 합의).
"""

from __future__ import annotations

from fastapi import APIRouter

from app.core.config import get_settings
from app.core.llm_clients import get_active_model

router = APIRouter(prefix="/api", tags=["system"])


@router.get("/health")
def health() -> dict:
    settings = get_settings()
    configured = settings.readiness()
    return {
        "status": "ok",
        "provider": settings.LLM_PROVIDER,
        "model": get_active_model(settings),
        # 하위 호환 키. 값은 실제 연결이 아니라 설정 여부다.
        "readiness": configured,
        "configured": configured,
        "llm_live_check": "/api/health/llm",
    }


@router.get("/health/llm")
def llm_health() -> dict:
    """선택된 provider의 모델 조회 API를 실제로 검사한다(답변 토큰 생성 없음)."""
    from app.adapters.llm_probe import probe_llm

    return probe_llm()


@router.get("/health/ready")
def ready() -> dict:
    """데이터 준비 상태(DB 테이블·RAG 인덱스). 미준비면 명시적으로 알린다(REQ-OPS-01)."""
    from app.obs.readiness import check_readiness

    return check_readiness()
