"""
graph/router.py

역할:
    사용자 질문을 받아서 5가지 기능 중 어떤 게 필요한지 분류한다.
    (policy_rag / claim_stats / similar_case / disease_lookup / glossary)

    하나의 질문이 여러 기능을 동시에 필요로 할 수 있다.
    예: "우울증(F32) 보장되나요?" -> disease_lookup + policy_rag 둘 다 필요

    분류 결과는 state["intent"]에 리스트로 채워지고,
    graph/builder.py의 conditional edge가 이 값을 보고 다음 노드를 결정한다.

주의:
    여기서는 "무엇이 필요한지"만 판단하고, 실제 도구 호출은 하지 않는다.
    도구 호출은 nodes/mcp_caller.py의 역할.
"""

import json

from langchain_openai import ChatOpenAI

from graph.state import InsuranceState, Intent
from graph.extractors import extract_age_group, extract_generation
from config import LLM_MODEL_NAME

VALID_INTENTS = {
    "policy_rag",
    "claim_stats",
    "similar_case",
    "disease_lookup",
    "glossary",
}

INTENT_CLASSIFICATION_PROMPT = """\
사용자 질문을 보고 아래 5개 카테고리 중 해당하는 것을 모두 골라주세요.
여러 개 해당할 수 있습니다. 다른 설명 없이 JSON 리스트로만 답하세요.
(예: ["policy_rag", "disease_lookup"])

- policy_rag: 약관 조항, 보장 내용, 면책 사항에 대한 질문
- claim_stats: 과거 청구 승인율, 지급 통계에 대한 질문
- similar_case: 비슷한 케이스(다른 사람 사례)를 찾는 질문
- disease_lookup: 질병명을 질병코드로 바꾸거나 코드로 질병을 찾는 질문
- glossary: 보험/의학 용어의 뜻을 묻는 질문

질문: {query}
"""

_llm = None


def _get_llm() -> ChatOpenAI:
    global _llm
    if _llm is None:
        _llm = ChatOpenAI(model=LLM_MODEL_NAME, temperature=0)
    return _llm


def classify_intent(user_query: str) -> list[Intent]:
    """
    사용자 질문을 LLM으로 분류해서 intent 리스트를 반환.

    LLM 응답 파싱에 실패하거나 유효한 intent가 하나도 없으면 빈 리스트를
    반환한다 -- policy_rag(보장판정, 가장 위험한 경로)로 임의 확정하지 않는다.
    intent가 비어있으면 mcp_caller가 아무 도구도 안 부르고 자연스럽게
    needs_fallback=True로 knowledge_gap에 보내므로, 여기서 안전한 값을
    억지로 고를 필요가 없다.
    """
    prompt = INTENT_CLASSIFICATION_PROMPT.format(query=user_query)
    response = _get_llm().invoke(prompt)

    try:
        parsed = json.loads(response.content)
        # json.loads("null")은 예외가 아니라 None을 반환한다 -- 리스트가
        # 아니면(None/dict/숫자 등) 여기서 걸러야 아래 반복문에서 안 터진다.
        if not isinstance(parsed, list):
            parsed = []
    except (json.JSONDecodeError, TypeError):
        parsed = []

    return [i for i in parsed if i in VALID_INTENTS]


def router_node(state: InsuranceState) -> InsuranceState:
    """
    LangGraph 노드로 등록될 함수. classify_intent로 의도를 분류하고,
    질문 텍스트에서 연령대/가입년도(세대)도 같이 뽑아 state에 채운다.

    이미 state에 값이 있으면(예: 이전 턴에 확인받은 값) 덮어쓰지 않는다.
    """
    intents = classify_intent(state["user_query"])
    updated_state = {**state, "intent": intents}

    if not updated_state.get("user_age_group"):
        age_group = extract_age_group(state["user_query"])
        if age_group:
            updated_state["user_age_group"] = age_group

    if not updated_state.get("generation"):
        generation = extract_generation(state["user_query"])
        if generation:
            updated_state["generation"] = generation

    return updated_state
