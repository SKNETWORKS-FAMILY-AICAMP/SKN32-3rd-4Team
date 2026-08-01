"""역할(RBAC) 정의와 관리자 의존성 (Phase 9).

설계 핵심: **role은 JWT에 넣지 않는다.** 토큰에 박으면 권한 강등이 토큰 만료 전까지 반영되지
않아 stale privilege가 생긴다. `get_current_user`가 어차피 요청마다 DB에서 User를 읽으므로,
DB의 role을 신뢰하면 추가 비용 없이 항상 최신 권한이 적용된다.

무폴백: DB의 role이 허용값이 아니면 **USER로 간주하지 않고** 명시적으로 거부한다
(데이터 오염 시 조용히 권한을 주거나 뺏지 않는다).
"""

from __future__ import annotations

from fastapi import Depends

from app.auth.security import get_current_user
from app.core.errors import ForbiddenErr, InfraError
from app.db.models import User

ROLE_USER = "USER"
ROLE_ADMIN = "ADMIN"
ROLES = frozenset({ROLE_USER, ROLE_ADMIN})


def validate_role(role: str | None) -> str:
    """역할 문자열을 검증해 반환. 알 수 없으면 InfraError(폴백 금지)."""
    if role not in ROLES:
        raise InfraError(f"알 수 없는 역할 값입니다(데이터 오염): {role!r}")
    return role


def require_admin(user: User = Depends(get_current_user)) -> User:
    """ADMIN만 통과. 미인증은 get_current_user가 401, USER는 여기서 403.

    라우터 단위 의존성으로 걸어 **fail-closed**를 강제한다(엔드포인트마다 붙이면 누락된다).
    """
    if validate_role(user.role) != ROLE_ADMIN:
        raise ForbiddenErr("관리자 권한이 필요합니다.")
    return user
