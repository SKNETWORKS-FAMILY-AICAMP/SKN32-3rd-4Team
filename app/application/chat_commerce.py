"""ChatCommerce — 상담 에이전트 닫힌 루프 + 자기검증 조립(Phase 7, 프레임워크 무의존).

에이전트 턴(도구 사용: RAG·상품·미리보기) → 관찰에서 근거 수집 → 자기검증(SelfVerify) →
최종 응답. 에이전트는 **읽기 전용 도구만** 쓰며 주문 생성은 사용자의 명시 승인 경로로만 성립한다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from app.application.self_verify import SelfVerify, SupportCheck
from app.core.errors import ValidationErr


@dataclass(frozen=True)
class AgentTurn:
    """에이전트 한 턴의 결과. evidence는 도구 관찰에서 뽑은 근거 문장들."""

    draft: str
    evidence: list[str]
    steps: list[dict[str, Any]] = field(default_factory=list)
    stopped_by: str = ""


@runtime_checkable
class AgentPort(Protocol):
    """상담 에이전트 포트. 구현: ReactAgentAdapter, FakeAgent(테스트)."""

    def run(self, question: str) -> AgentTurn: ...


@dataclass(frozen=True)
class ChatResult:
    answer: str
    support_check: SupportCheck
    draft_blocked: bool
    steps: list[dict[str, Any]]
    stopped_by: str


class ChatCommerce:
    """에이전트 응답을 근거 정합성 검사까지 거쳐 내보낸다."""

    def __init__(self, agent: AgentPort, verify: SelfVerify) -> None:
        self._agent = agent
        self._verify = verify

    def __call__(self, question: str) -> ChatResult:
        if not question or not question.strip():
            raise ValidationErr("질문이 비어 있습니다.")
        turn = self._agent.run(question)
        checked = self._verify(question, turn.draft, turn.evidence)
        return ChatResult(
            answer=checked.answer,
            support_check=checked.support_check,
            draft_blocked=checked.draft_blocked,
            steps=turn.steps,
            stopped_by=turn.stopped_by,
        )
