"""
main.py

역할:
    graph/precheck_graph.py(계약 06_계약_Agent.md 기준 사전판정 그래프)를
    실행하는 진입점.

    옛 5개 기능 라우터(graph/builder.py)는 프로토타입으로 레포에 남아있지만,
    인용검증·해시·기권구조가 없어서 이 진입점은 더 이상 그쪽을 부르지 않는다.

실행:
    python main.py
"""

from graph.precheck_domain import PrecheckInput, PrecheckOutcome
from graph.precheck_graph import build


def run(
    query: str,
    kcd_codes: tuple[str, ...] = (),
    insurer: str = "",
    enrolled_on: str = "",
) -> PrecheckOutcome:
    graph = build()
    body = PrecheckInput(query=query, kcd_codes=kcd_codes, insurer=insurer, enrolled_on=enrolled_on)
    outcome, _ = graph.invoke(body)
    return outcome


if __name__ == "__main__":
    query = input("질문을 입력하세요: ")
    enrolled_on = input("가입일시(YYYY-MM-DD, 모르면 엔터): ").strip()
    codes_raw = input("질병코드(콤마로 구분, 없으면 엔터): ").strip()
    kcd_codes = tuple(c.strip() for c in codes_raw.split(",") if c.strip())

    result = run(query, kcd_codes=kcd_codes, enrolled_on=enrolled_on)

    print("\n=== 결과 ===")
    print(f"verdict: {result.verdict.value}")
    if result.abstained:
        print(f"기권 (사유: {result.reason_code.value if result.reason_code else '알 수 없음'})")
    print(result.message)
    print("\n근거:")
    for c in result.citations:
        print(f"- {c.article_no}({c.article_title})")
    if result.candidates:
        print("\n후보:")
        for cand in result.candidates:
            print(f"- {cand.product_name} ({cand.product_line}, {cand.generation})")
