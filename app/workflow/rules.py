"""티켓 라우팅 규칙 — 순수 함수(LLM 무관, 결정론).

우선순위·담당팀은 **명명된 도메인 정책 상수**로 선언한다(매직값 하드코딩 아님).
누락/모순은 폴백하지 않고 명시적 오류로 실패한다(RULE).
"""

from __future__ import annotations

from app.core.errors import ConfigError
from app.prompts.classifier import CATEGORIES

# 즉시 에스컬레이션 대상(도메인 정책). 그 외는 '일반'.
URGENT_CATEGORIES: frozenset[str] = frozenset({"불만", "환불"})

# 카테고리 → 담당팀 (유효 카테고리 7종 전부 명시, 기본팀 없음).
TEAM_BY_CATEGORY: dict[str, str] = {
    "결제": "결제팀",
    "환불": "결제팀",
    "배송": "물류팀",
    "교환": "물류팀",
    "상품문의": "상품팀",
    "칭찬": "CS팀",
    "불만": "CS팀",
}

PRIORITY_URGENT = "긴급"
PRIORITY_NORMAL = "일반"


def calculate_priority(category: str) -> str:
    """카테고리로 우선순위를 정한다. 긴급 정책 대상이면 '긴급', 아니면 '일반'.

    유효 카테고리(CATEGORIES)만 받는다. 그 외 값(미분류·오타 등)을 조용히 '일반'으로
    떨어뜨리면 폴백이므로, 명시적 오류로 실패한다(정상 경로에서는 도달 불가).
    """
    if category not in CATEGORIES:
        raise ConfigError(f"우선순위 판정 대상이 아닌 카테고리입니다: {category}")
    return PRIORITY_URGENT if category in URGENT_CATEGORIES else PRIORITY_NORMAL


def assign_team(category: str) -> str:
    """카테고리의 담당팀을 반환한다. 매핑에 없으면 폴백 대신 명시적 실패.

    매핑 누락은 사용자 입력 오류가 아니라 배포된 도메인 정책의 불일치이므로 ConfigError(503).
    """
    try:
        return TEAM_BY_CATEGORY[category]
    except KeyError as exc:
        # 유효 카테고리는 전부 매핑돼 있어야 한다(정상 경로에서는 도달 불가).
        raise ConfigError(f"담당팀 매핑에 없는 카테고리입니다: {category}") from exc


# 불변식: 분류기의 유효 카테고리 집합과 팀 매핑 키 집합이 정확히 일치해야 한다.
# (드리프트/오타 시 import 시점에 즉시 실패시켜 조용한 폴백을 막는다.)
if set(CATEGORIES) != set(TEAM_BY_CATEGORY):  # pragma: no cover - 개발 중 실수 방지용 가드
    _diff = set(CATEGORIES) ^ set(TEAM_BY_CATEGORY)
    raise ConfigError(f"카테고리↔팀 매핑 불일치: {sorted(_diff)}")
