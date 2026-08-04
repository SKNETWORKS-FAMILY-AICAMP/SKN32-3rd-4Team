"""예외 taxonomy 및 FastAPI 예외 핸들러 등록.

RULE.md 3.2(폴백 금지)와 통합 계획서 §6을 구현한다. 오류를 삼켜 그럴듯한 가짜
결과로 대체하지 않고, 정의된 HTTP 상태 + 구조화된 본문 {ok, error_code, message}로
명확히 실패시킨다.

이 모듈은 **모듈 레벨에서 프레임워크를 import하지 않는다**(Application 계층이 예외
타입만 안전히 import할 수 있게 — Clean Architecture 경계). FastAPI 의존은
register_exception_handlers 내부에서 지연 import한다.
"""

from __future__ import annotations

from typing import Any


class AppError(Exception):
    """애플리케이션 공통 예외 베이스."""

    http_status: int = 500
    error_code: str = "app_error"

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class ConfigError(AppError):
    """설정/키 부재 등 서비스 의존성 미준비 (폴백 대신 명시적 실패)."""

    http_status = 503
    error_code = "config_error"


class InfraError(AppError):
    """DB/외부 인프라 연결 실패."""

    http_status = 503
    error_code = "infra_error"


class LLMOutputError(AppError):
    """LLM 출력이 스키마 검증을 통과하지 못함 (재시도 후 최종 실패)."""

    http_status = 502
    error_code = "llm_output_error"


class ValidationErr(AppError):
    """사용자 입력 검증 실패."""

    http_status = 422
    error_code = "validation_error"


class AuthErr(AppError):
    """인증 실패 (토큰 없음/무효/만료)."""

    http_status = 401
    error_code = "auth_error"


class ForbiddenErr(AppError):
    """권한 없음 (타인 리소스 접근 등)."""

    http_status = 403
    error_code = "forbidden"


class NotFoundErr(AppError):
    """리소스 없음."""

    http_status = 404
    error_code = "not_found"


class ConflictErr(AppError):
    """리소스 충돌 (같은 멱등키·다른 payload 등)."""

    http_status = 409
    error_code = "conflict"


def register_exception_handlers(app: Any) -> None:
    """AppError 계열을 정의된 HTTP 상태 + 구조화 본문으로 매핑한다.

    FastAPI는 Interface 계층 관심사이므로 여기서 지연 import한다(모듈 레벨 순수 유지).
    """
    from fastapi import Request
    from fastapi.responses import JSONResponse

    @app.exception_handler(AppError)
    async def _handle_app_error(_request: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.http_status,
            content={"ok": False, "error_code": exc.error_code, "message": exc.message},
        )
