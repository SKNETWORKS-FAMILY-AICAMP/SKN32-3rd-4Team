"""
nodes/result_parser.py

역할:
    mcp_caller_node가 채워놓은 원본 결과(matched_clauses, approval_stats 등)를
    다듬어서 citations(판정 근거)/references(참고자료) 필드를 채운다.

    약관 조항(matched_clauses)만 citations에 들어간다 -- 03_에이전트_데이터_
    축적_설계.md §1의 EvidenceTier 원칙(약관 원문만 판정 근거, 나머지는 참고)에
    따른 것. 유사사례/청구통계/용어는 references로 분리해서, 약관 근거가 0건인데
    참고자료만 있어서 "근거 있음"으로 잘못 보이는 걸 막는다.
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

    references: list[str] = []

    for case in state.get("similar_cases", []):
        references.append(
            f"유사청구사례({case.get('disease_code')}/{case.get('age_group')}): "
            f"{case.get('result')}"
        )

    stats = state.get("approval_stats")
    if stats and not stats.get("_mock"):
        references.append(
            f"청구승인통계: {stats.get('approved')}/{stats.get('total')}건 승인"
        )

    for term in state.get("glossary_terms", []):
        references.append(f"용어사전: {term.get('term')}")

    return {**state, "citations": citations, "references": references}
