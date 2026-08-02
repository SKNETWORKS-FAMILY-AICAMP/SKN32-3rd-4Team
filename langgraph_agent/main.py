"""
main.py

역할:
    graph/builder.py로 조립한 그래프를 실행하는 진입점.
    터미널에서 직접 질문을 넣어보며 그래프 흐름을 테스트할 때 사용.

실행:
    python main.py
"""

from graph.builder import build_graph
from graph.state import InsuranceState


def run(user_query: str) -> InsuranceState:
    app = build_graph()
    initial_state: InsuranceState = {
        "user_query": user_query,
        "matched_clauses": [],
        "similar_cases": [],
        "glossary_terms": [],
        "citations": [],
        "needs_fallback": False,
    }
    return app.invoke(initial_state)


if __name__ == "__main__":
    query = input("질문을 입력하세요: ")
    result = run(query)
    print("\n=== 결과 ===")
    print(result.get("final_answer"))
    print("\n근거:", result.get("citations"))
