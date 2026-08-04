"""LangGraph 워크플로 라우터 — CS 티켓 처리.

POST /api/workflow/ticket : 문의 내용 → 최종 상태(category/priority/team/action).
빈 입력/LLM 실패는 폴백 없이 오류로 전파(그래프 노드가 ValidationErr/InfraError 발생).
"""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.workflow.ticket_graph import run_ticket

router = APIRouter(prefix="/api/workflow", tags=["workflow"])


class TicketRequest(BaseModel):
    content: str = Field(min_length=1, description="CS 문의 내용")


@router.post("/ticket")
def handle_ticket(body: TicketRequest) -> dict:
    """문의를 워크플로에 태워 분류→우선순위→배정/에스컬레이션/수동검토 결과를 반환한다."""
    return dict(run_ticket(body.content))
