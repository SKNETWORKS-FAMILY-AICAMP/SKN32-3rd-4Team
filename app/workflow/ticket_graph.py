"""CS 티켓 처리 LangGraph StateGraph.

그래프(조건분기):
    START → classify → ┬ (유효 카테고리) → priority → ┬ (긴급) → escalate → END
                       │                               └ (일반) → assign   → END
                       └ (미분류)          → manual_review → END

무폴백(계획 Codex 합의 #3):
- 빈 입력 → ValidationErr(전파), LLM 연결 실패 → InfraError(전파). (classify_one이 이미 그렇게 처리)
- LLM 출력이 허용 카테고리 아님 → '미분류' → manual_review → END.
  priority로 계속 진행하지 않는다(그게 또 다른 폴백).

linear 그래프는 만들지 않는다(엔드포인트 미사용 + 미분류를 무시하고 진행 → 무폴백 위반, YAGNI).
"""

from __future__ import annotations

from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from app.core.errors import ConfigError
from app.prompts.classifier import UNCLASSIFIED, ChatComplete, classify_one
from app.workflow.rules import (
    PRIORITY_NORMAL,
    PRIORITY_URGENT,
    assign_team,
    calculate_priority,
)


class TicketState(TypedDict, total=False):
    content: str
    category: str
    priority: str
    team: str
    action: str


def build_ticket_graph(chat_complete: ChatComplete | None = None):
    """CS 티켓 워크플로 그래프를 컴파일해 반환한다.

    chat_complete: 분류 LLM 주입(테스트/로컬 결정론). 미지정 시 설정된 provider 사용.
    """

    def classify_node(state: TicketState) -> TicketState:
        # 빈 입력/LLM 실패는 classify_one이 ValidationErr/InfraError로 전파(삼키지 않음).
        return {"category": classify_one(state["content"], chat_complete)}

    def route_after_classify(state: TicketState) -> str:
        return "manual_review" if state["category"] == UNCLASSIFIED else "priority"

    def priority_node(state: TicketState) -> TicketState:
        return {"priority": calculate_priority(state["category"])}

    def route_after_priority(state: TicketState) -> str:
        # 규칙 상수 재사용(리터럴 중복 금지). 예상 밖 값은 조용한 폴백 대신 명시적 실패.
        priority = state["priority"]
        if priority == PRIORITY_URGENT:
            return "escalate"
        if priority == PRIORITY_NORMAL:
            return "assign"
        raise ConfigError(f"예상 밖 우선순위입니다: {priority}")

    def assign_node(state: TicketState) -> TicketState:
        return {"team": assign_team(state["category"]), "action": "assign"}

    def escalate_node(state: TicketState) -> TicketState:
        return {"team": assign_team(state["category"]), "action": "escalate"}

    def manual_review_node(state: TicketState) -> TicketState:
        # 미분류는 정상 수동검토 상태(오류 아님). 담당팀/우선순위는 배정하지 않는다.
        return {"action": "manual_review"}

    graph = StateGraph(TicketState)
    graph.add_node("classify", classify_node)
    graph.add_node("priority", priority_node)
    graph.add_node("assign", assign_node)
    graph.add_node("escalate", escalate_node)
    graph.add_node("manual_review", manual_review_node)

    graph.add_edge(START, "classify")
    graph.add_conditional_edges(
        "classify",
        route_after_classify,
        {"priority": "priority", "manual_review": "manual_review"},
    )
    graph.add_conditional_edges(
        "priority",
        route_after_priority,
        {"escalate": "escalate", "assign": "assign"},
    )
    graph.add_edge("assign", END)
    graph.add_edge("escalate", END)
    graph.add_edge("manual_review", END)
    return graph.compile()


def run_ticket(content: str, chat_complete: ChatComplete | None = None) -> TicketState:
    """티켓 내용을 워크플로에 태워 최종 상태를 반환한다."""
    graph = build_ticket_graph(chat_complete)
    return graph.invoke({"content": content})
