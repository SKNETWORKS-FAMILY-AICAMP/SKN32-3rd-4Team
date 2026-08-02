"""
graph/builder.py

역할:
    router, nodes, mcp_tools에 흩어진 함수들을 실제로 연결해서
    하나의 실행 가능한 StateGraph로 조립하는 곳.

    이 파일만 보면 전체 흐름이 한눈에 보이도록 유지하는 게 목표.
    개별 노드의 상세 로직은 여기 넣지 않고 nodes/, mcp_tools/에서 import만 한다.

흐름:
    START -> router -> mcp_caller -> result_parser -> (분기)
        분기 성공 -> judge_coverage -> END
        분기 실패 -> knowledge_gap -> END
"""

from langgraph.graph import StateGraph, START, END

from graph.state import InsuranceState
from graph.router import router_node
from nodes.mcp_caller import mcp_caller_node
from nodes.result_parser import result_parser_node
from nodes.judge_coverage import judge_coverage_node
from nodes.knowledge_gap import knowledge_gap_node


def route_after_mcp(state: InsuranceState) -> str:
    """MCP 호출 결과를 보고 다음 노드를 결정 (무폴백 원칙 적용 지점)."""
    if state.get("needs_fallback"):
        return "knowledge_gap"
    return "judge_coverage"


def build_graph():
    graph = StateGraph(InsuranceState)

    graph.add_node("router", router_node)
    graph.add_node("mcp_caller", mcp_caller_node)
    graph.add_node("result_parser", result_parser_node)
    graph.add_node("judge_coverage", judge_coverage_node)
    graph.add_node("knowledge_gap", knowledge_gap_node)

    graph.add_edge(START, "router")
    graph.add_edge("router", "mcp_caller")
    graph.add_edge("mcp_caller", "result_parser")
    graph.add_conditional_edges(
        "result_parser",
        route_after_mcp,
        {
            "judge_coverage": "judge_coverage",
            "knowledge_gap": "knowledge_gap",
        },
    )
    graph.add_edge("judge_coverage", END)
    graph.add_edge("knowledge_gap", END)

    return graph.compile()
