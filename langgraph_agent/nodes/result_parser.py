"""
nodes/result_parser.py

역할:
    mcp_caller_node가 채워놓은 원본 결과(matched_clauses, approval_stats 등)를
    다듬어서 citations(근거 출처) 필드를 채운다.

    citations는 "무폴백 + 출처인용" 원칙의 핵심 필드 -- 여기서 안 채우면
    최종 응답에 근거를 못 붙이게 되므로 반드시 채워야 한다.
"""

from graph.state import InsuranceState


def result_parser_node(state: InsuranceState) -> InsuranceState:
    if state.get("needs_fallback"):
        # 이미 실패 표시된 상태면 파싱할 게 없으므로 그대로 통과
        return state

    citations: list[str] = []

    for clause in state.get("matched_clauses", []):
        citations.append(
            f"{clause.get('generation')} {clause.get('article_no')}"
            f"({clause.get('article_title')})"
        )

    for case in state.get("similar_cases", []):
        citations.append(
            f"유사청구사례({case.get('disease_code')}/{case.get('age_group')}): "
            f"{case.get('result')}"
        )

    stats = state.get("approval_stats")
    if stats and not stats.get("_mock"):
        citations.append(
            f"청구승인통계: {stats.get('approved')}/{stats.get('total')}건 승인"
        )

    for term in state.get("glossary_terms", []):
        citations.append(f"용어사전: {term.get('term')}")

    return {**state, "citations": citations}
