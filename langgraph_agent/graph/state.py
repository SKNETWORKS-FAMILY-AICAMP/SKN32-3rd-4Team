"""
graph/state.py

역할:
    LangGraph 전체 흐름에서 공유되는 State(작업 서류철) 스키마를 정의한다.
    모든 노드는 이 State를 입력받고, 자기 작업 결과를 채워서 다음 노드로 넘긴다.

    5가지 기능(약관RAG / 청구승인율 / 유사케이스 / 질병코드매칭 / 용어설명)이
    공통으로 쓸 수 있도록 필드를 넉넉히 잡아두되, intent에 따라 실제로
    쓰이는 필드만 채워지고 나머지는 None으로 남는다.

사용 예:
    from graph.state import InsuranceState

    def some_node(state: InsuranceState) -> InsuranceState:
        return {**state, "disease_name": "급성기관지염"}
"""

from typing import TypedDict, Optional, Literal

Intent = Literal[
    "policy_rag",       # 기능1: 약관 조항 검색
    "claim_stats",       # 기능2: 청구승인율 통계
    "similar_case",       # 기능3: 유사 케이스 조회
    "disease_lookup",     # 기능4: 질병명 -> 질병코드 매칭
    "glossary",           # 기능5: 용어 설명
]


class InsuranceState(TypedDict, total=False):
    # --- 공통 입력 ---
    user_query: str                      # 사용자 원 질문
    intent: list[Intent]                 # Router가 분류한 의도 (복수 가능)

    # --- 기능4: 질병코드 매칭 ---
    disease_code: Optional[str]          # 예: "F32" (후보가 정확히 1개일 때만 확정)
    disease_code_hash: Optional[str]     # disease_code의 해시 -- 로그/트레이스는 이걸 참조
    disease_name: Optional[str]          # 예: "우울증"
    disease_candidates: list[dict]       # 후보가 여러 개일 때 (예: "우울증" -> F32/F33 등)
                                          # 임의로 하나 골라서 disease_code에 넣지 않는다 --
                                          # 잘못된 코드로 보장여부를 판단하면 오답으로 이어짐

    # --- 기능1: 약관 RAG ---
    generation: Optional[str]            # 세대 필터 (예: "3세대")
    matched_clauses: list[dict]          # 검색된 조항 리스트

    # --- 기능2, 3: 청구통계 / 유사케이스 ---
    user_age_group: Optional[str]        # 전처리된 연령대 카테고리
    approval_stats: Optional[dict]       # {"approved": 33, "total": 40, "rejected": 7}
    similar_cases: list[dict]

    # --- 기능5: 용어설명 ---
    glossary_terms: list[dict]

    # --- 공통 출력 ---
    final_answer: Optional[str]
    # citations는 "판정 근거"로만 쓴다 -- 약관 조항(matched_clauses)만 여기 들어간다.
    # 03_에이전트_데이터_축적_설계.md §1의 EvidenceTier 원칙: 약관 원문(POLICY_CLAUSE)만
    # 판정 근거이고, 외부사례/통계/용어는 참고(EXTERNAL_REPORT·STATISTICS)일 뿐이다.
    # 이 둘을 citations 하나에 섞으면, 약관 조항이 0건이어도 참고자료가 있으면
    # "근거 있음"처럼 보이는 사고가 생긴다 -- references로 분리해서 막는다.
    citations: list[str]                 # 판정 근거 (약관 조항만, 무폴백 판단에 씀)
    references: list[str]                # 참고자료 (유사사례/통계/용어 -- 판정 근거 아님)

    # --- 에러/폴백 처리 ---
    error: Optional[str]
    needs_fallback: bool
