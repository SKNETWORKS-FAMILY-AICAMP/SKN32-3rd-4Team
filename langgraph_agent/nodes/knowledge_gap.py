"""
nodes/knowledge_gap.py

역할:
    MCP 호출 실패 또는 근거 조항을 못 찾은 경우 도달하는 노드.
    절대로 LLM이 답을 지어내지 않도록, 여기서는 "확인 불가" 성격의
    고정 응답 + 에러 사유만 채우고 종료한다.

    이후 별도 관리자 대시보드(기능6)에서 이 케이스들을 모아
    사람이 검토할 수 있도록 큐에 쌓는 구조로 확장 가능.
"""

from graph.state import InsuranceState


def knowledge_gap_node(state: InsuranceState) -> InsuranceState:
    reason = state.get("error", "관련 근거를 찾지 못했습니다.")

    answer = (
        "죄송합니다, 이 질문에 대해 약관 근거를 확인하지 못했습니다. "
        f"(사유: {reason}) 정확한 확인을 위해 상담원 문의를 권장합니다."
    )

    return {**state, "final_answer": answer, "citations": []}
