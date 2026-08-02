"""
nodes/judge_coverage.py

역할:
    mcp_caller/result_parser가 모아온 정보(약관 조항, 질병 정보, 청구통계,
    유사사례, 용어설명)를 근거로, LLM이 최종 응답(state["final_answer"])을
    생성하는 노드.

    citations 없이는 답을 만들지 않는다 -- 근거가 하나도 없으면 이 노드가
    아니라 knowledge_gap 노드로 이미 라우팅됐어야 정상.

주의:
    intent가 policy_rag가 아닐 수도 있다 (예: 순수 용어설명 질문). 그래서
    프롬프트에 "약관 조항"만이 아니라 mcp_caller가 채운 4가지 정보를 전부
    조건부로 넣어준다 -- 안 그러면 예를 들어 청구승인율만 찾은 질문인데
    LLM한테는 그 내용이 안 보여서 엉뚱한 답이 나갈 수 있다.
"""

from langchain_openai import ChatOpenAI

from graph.state import InsuranceState
from config import LLM_MODEL_NAME

_llm = None


def _get_llm() -> ChatOpenAI:
    global _llm
    if _llm is None:
        _llm = ChatOpenAI(model=LLM_MODEL_NAME, temperature=0)
    return _llm


JUDGE_PROMPT_TEMPLATE = """\
아래 "제공된 정보"만 근거로 사용자 질문에 답해주세요.
제공된 정보에 없는 내용은 추측하지 말고 "확인 불가"라고 답하세요.
약관 조항을 인용할 때는 반드시 조항 번호를 함께 쓰세요.

질병코드 후보가 여러 개(candidates)로 주어지면, 그중 하나를 임의로 골라
확정 짓지 말고 "어느 진단명인지 확인이 필요하다"고 답하세요.

질문: {query}
질병정보: {disease_name} ({disease_code})
질병코드 후보(미확정): {disease_candidates}

[제공된 정보]

관련 약관 조항:
{clauses}

청구승인 통계:
{stats}

유사 청구 사례:
{cases}

용어 설명:
{glossary}
"""


def _format_clauses(state: InsuranceState) -> str:
    clauses = state.get("matched_clauses", [])
    if not clauses:
        return "없음"
    return "\n".join(f"- {c.get('article_no')}: {c.get('content')}" for c in clauses)


def _format_stats(state: InsuranceState) -> str:
    stats = state.get("approval_stats")
    if not stats or stats.get("_mock"):
        return "없음"
    return f"{stats.get('approved')}/{stats.get('total')}건 승인 ({stats.get('rejected')}건 반려)"


def _format_cases(state: InsuranceState) -> str:
    cases = state.get("similar_cases", [])
    if not cases:
        return "없음"
    return "\n".join(
        f"- {c.get('disease_code')}/{c.get('age_group')}: {c.get('result')} ({c.get('note', '')})"
        for c in cases
    )


def _format_glossary(state: InsuranceState) -> str:
    terms = state.get("glossary_terms", [])
    if not terms:
        return "없음"
    return "\n".join(f"- {t.get('term')}: {t.get('definition')}" for t in terms)


def _format_candidates(state: InsuranceState) -> str:
    candidates = state.get("disease_candidates", [])
    if not candidates:
        return "없음"
    return ", ".join(f"{c.get('code')}({c.get('name')})" for c in candidates)


def judge_coverage_node(state: InsuranceState) -> InsuranceState:
    prompt = JUDGE_PROMPT_TEMPLATE.format(
        query=state.get("user_query", ""),
        disease_name=state.get("disease_name", "미상"),
        disease_code=state.get("disease_code", "미상"),
        disease_candidates=_format_candidates(state),
        clauses=_format_clauses(state),
        stats=_format_stats(state),
        cases=_format_cases(state),
        glossary=_format_glossary(state),
    )

    answer = _get_llm().invoke(prompt).content

    return {**state, "final_answer": answer}
