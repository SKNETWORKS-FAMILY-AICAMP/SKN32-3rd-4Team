"""
목적: 청구사례(Index B) 기반 "유사사례 조회" 서비스.

[중요] 이 파일은 Index B(청구사례) 전용이다. Index A(보험 약관, main_rag_service.py)와
절대 같은 인덱스/함수에 섞지 않는다 (11_AI_구조_지도.md §1, §2 기준).
그래서 이 파일은 main_rag_service.py의 load_all_chunks()/build_index()를 재사용하지 않고
똑같은 패턴(임베딩 -> FAISS -> 검색 -> LLM 설명)을 완전히 별도로 다시 구성한다.

Index A(main_rag_service.py)와 근본적으로 다른 점:
  - 여기서 나가는 건 '판정(verdict)'이 아니라 '통계'다. assess()를 쓰지 않는다.
  - 유사사례는 조건이 완전히 같다고 볼 수 없으므로, 하나의 확률(예: "승인율 82%")로
    뭉쳐서 보여주지 않는다. 대신 "건수 + 95% 신뢰구간 + 표본 부족 여부"를 함께 낸다
    (11_AI_구조_지도.md §3 - 점추정 금지, 표본 30건 미만이면 비율 자체를 숨김).
  - 숫자 -> 문장 변환은 LLM이 아니라 결정론 코드(build_headline)가 한다.
    LLM은 그 문장의 숫자를 바꾸지 않고 자연스럽게 다듬어 전달하는 역할만 한다
    (11_AI_구조_지도.md §4 - "LLM은 봉투를 만들고, 편지는 코드가 쓴다").

데이터: claim_rag_data/claim_samples.json (가상 샘플 50건).
실제 서비스에서는 사용자가 남기는 데이터로 계속 축적될 예정이라, 지금은 개발/
테스트 단계에서만 쓰는 자리채움 데이터다 (실제 청구 데이터는 개인정보라 확보 불가).

API 키(OPENAI_API_KEY)는 main_rag_service.py와 마찬가지로 .env에서 읽는다.
"""

import json
import math
import os

import numpy as np
import faiss
from sentence_transformers import SentenceTransformer
from openai import OpenAI
from dotenv import load_dotenv

# 임베딩/LLM 모델명은 main_rag_service.py와 같은 설정(file_config.py)을 재사용한다 -
# "어떤 모델을 쓸지"는 인프라 선택이라 Index A/B가 굳이 다를 필요가 없어서다.
# 반대로 데이터 경로/필드명/검색 로직은 완전히 분리해서 이 파일 안에만 둔다.
from file_config import EMBEDDING_MODEL_NAME, LLM_MODEL_NAME, LLM_MAX_TOKENS

load_dotenv()

# main_rag_service.py의 main_rag_data/ 폴더와 안 섞이도록 별도 하위 폴더(claim_rag_data/)를 쓴다.
# (물리적 분리는 "insurance_rag 바깥"이 아니라 "다른 서브폴더/다른 파일" 수준이면 충분하다)
CLAIM_DATA_PATH = os.path.join("claim_rag_data", "claim_samples.json")

CLAIM_SEARCH_CANDIDATE_K = 30  # 유사사례는 여러 건을 모아 통계를 내야 하므로 후보를 넉넉히 뽑는다
MIN_SAMPLE_SIZE = 30  # 이보다 적으면 비율/신뢰구간을 숨기고 건수만 보여준다
CONFIDENCE_Z = 1.96  # 95% 신뢰구간에 쓰는 z값

CLAIM_SYSTEM_PROMPT = """너는 보험 청구 유사사례를 안내하는 AI 도우미이다.

너에게는 이미 계산이 끝난 통계 문장(headline)이 주어진다. 그 문장에 있는 숫자나
표현을 바꾸지 않고 그대로 포함시켜서, 사용자 질문 맥락에 맞게 자연스럽게 안내하는
역할만 한다. 스스로 승인율을 계산하거나 새로운 확률을 만들어내지 않는다.

절대 하지 않을 것:
- headline에 없는 숫자를 새로 만들어내기
- "~일 것 같다", "~할 가능성이 높다" 같은 개인 예측성 표현
- 확률을 신뢰구간 없이 하나의 숫자로 단정하기 (예: "약 80%")

[답변 형식]
[유사사례 조회 결과]
{headline 문장을 그대로 포함}

[참고사항]
- 이 결과는 조건이 유사한 과거 사례의 통계이며, 실제 심사 결과는 개별 건마다 다를 수 있습니다.
- 본인의 청구 건에 대한 확정적인 예측이 아닙니다.
"""

_embedding_model = None  # 한 번만 불러와서 재사용
_llm_client = None  # 한 번만 만들어서 재사용


def get_embedding_model() -> SentenceTransformer:
    global _embedding_model
    if _embedding_model is None:
        _embedding_model = SentenceTransformer(EMBEDDING_MODEL_NAME)
    return _embedding_model


def get_llm_client() -> OpenAI:
    """OpenAI 클라이언트를 만든다. main_rag_service.py와 같은 이유로 지연 생성한다
    (API 키가 없으면 만드는 순간 에러가 나서, try/except로 감쌀 수 있는 시점에 만들어야 함)."""
    global _llm_client
    if _llm_client is None:
        _llm_client = OpenAI()
    return _llm_client


def load_claim_cases(path: str = CLAIM_DATA_PATH) -> list[dict]:
    """청구사례 json을 읽어온다.

    main_rag_service.py의 load_all_chunks()와 다르게 파일 하나만 읽는다 - 청구사례는
    조항처럼 보험사/상품별로 여러 파일로 안 쪼개져 있고, 계속 누적되는 단일
    로그 형태이기 때문이다.
    """
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def case_to_text(case: dict) -> str:
    """청구사례 한 건에서 임베딩할 텍스트를 만든다.

    보험사/세대/질병명/입원유형을 문장으로 엮어서, "이런 상황의 청구"를
    의미 기반으로 검색할 수 있게 한다.
    """
    return (
        f"{case.get('insurer', '')} {case.get('generation', '')} "
        f"{case.get('disease_name', '')}({case.get('disease_code', '')}) "
        f"{case.get('admission_type', '')} 청구"
    )


def build_index(cases: list[dict]) -> faiss.IndexFlatIP:
    """모든 청구사례를 임베딩해서 FAISS 벡터 인덱스를 만든다."""
    model = get_embedding_model()
    texts = [case_to_text(c) for c in cases]
    embeddings = model.encode(texts, normalize_embeddings=True)

    dimension = embeddings.shape[1]
    index = faiss.IndexFlatIP(dimension)
    index.add(np.array(embeddings, dtype="float32"))
    return index


def search_similar_cases(
    question: str, cases: list[dict], index: faiss.IndexFlatIP, filters: dict | None = None
) -> list[dict]:
    """질문과 비슷한 상황의 청구사례를 '여러 건' 찾는다.

    main_rag_service.py의 search_relevant_chunks()도 여러 건(EVIDENCE_TOP_N개)을 찾지만
    그건 "LLM에게 줄 근거 후보"가 목적이고, 여기는 통계를 내야 하므로 후보(CLAIM_SEARCH_CANDIDATE_K개,
    보통 더 많은 수) 전부를 돌려준다는 점이 다르다.
    filters 방식은 main_rag_service.py와 동일하게 {필드명: 값} 딕셔너리다.
    """
    if len(cases) == 0:
        return []

    filters = filters or {}
    model = get_embedding_model()
    question_embedding = model.encode([question], normalize_embeddings=True)

    top_k = min(CLAIM_SEARCH_CANDIDATE_K, len(cases))
    _, indices = index.search(np.array(question_embedding, dtype="float32"), top_k)

    matched = []
    for idx in indices[0]:
        if idx < 0:
            continue
        case = cases[idx]
        if any(case.get(field) != value for field, value in filters.items()):
            continue
        matched.append(case)

    return matched


def wilson_confidence_interval(successes: int, total: int, z: float = CONFIDENCE_Z) -> tuple[float, float]:
    """Wilson score interval로 95% 신뢰구간을 계산한다.

    단순 정규근사(p ± z*sqrt(p(1-p)/n))보다 표본이 작을 때 더 안정적이라
    이 방식을 썼다 - 유사사례 건수가 많지 않을 수 있어서다.
    """
    if total == 0:
        return (0.0, 0.0)

    p = successes / total
    denom = 1 + z ** 2 / total
    center = p + z ** 2 / (2 * total)
    margin = z * math.sqrt((p * (1 - p) + z ** 2 / (4 * total)) / total)

    lower = (center - margin) / denom
    upper = (center + margin) / denom
    return (max(0.0, lower), min(1.0, upper))


def aggregate_cohort(cases: list[dict]) -> dict:
    """유사사례 목록을 승인/부분승인/거절 건수 + 신뢰구간으로 집계한다.

    [중요] 이 함수는 결정론 코드다 - LLM이 아니다. "부분승인이라도 일부는
    지급됐다"는 관점에서 승인+부분승인을 '지급됨'으로 합쳐 지급 비율을 계산한다.

    표본이 MIN_SAMPLE_SIZE보다 적으면 비율/신뢰구간 자체를 계산하지 않는다
    (11_AI_구조_지도.md §3 - "표본 30건 미만이면 비율 자체를 숨긴다").
    """
    total = len(cases)
    approved = sum(1 for c in cases if c.get("result") == "승인")
    partially_approved = sum(1 for c in cases if c.get("result") == "부분승인")
    denied = sum(1 for c in cases if c.get("result") == "거절")

    sufficient_sample = total >= MIN_SAMPLE_SIZE

    stats = {
        "total": total,
        "approved": approved,
        "partially_approved": partially_approved,
        "denied": denied,
        "sufficient_sample": sufficient_sample,
        "payment_rate_ci": None,  # (하한%, 상한%) - 표본 부족 시 None
    }

    if sufficient_sample:
        paid_count = approved + partially_approved
        lower, upper = wilson_confidence_interval(paid_count, total)
        stats["payment_rate_ci"] = (round(lower * 100, 1), round(upper * 100, 1))

    return stats


def build_headline(stats: dict) -> str:
    """통계를 문장으로 바꾼다.

    [중요] LLM이 아니라 여기(결정론 코드)에서 문장을 만든다. 이유:
    LLM에게 숫자 서술을 맡기면 "지급 비율이 68~91%다" 같은 정확한 표현이
    "대체로 지급되는 편이다"처럼 뭉개질 위험이 있고, 그렇게 뭉개져도 LLM이
    스스로 알려주지 않는다 (11_AI_구조_지도.md §4). 그래서 문장 자체를
    코드가 고정 생성하고, LLM(explain_cohort)은 이 문장을 그대로 옮겨적기만 한다.
    """
    if stats["total"] == 0:
        return "유사한 과거 청구 사례를 찾지 못했습니다."

    line = f"검증된 과거 사례 {stats['total']}건 중 {stats['approved']}건 승인"
    if stats["partially_approved"]:
        line += f" · {stats['partially_approved']}건 부분승인"
    if stats["denied"]:
        line += f" · {stats['denied']}건 거절"

    if stats["sufficient_sample"]:
        low, high = stats["payment_rate_ci"]
        line += f" (이 사례들의 지급 비율은 {low}%~{high}% 범위로 추정됩니다 · 95% 신뢰구간)"
    else:
        line += f" (표본이 {MIN_SAMPLE_SIZE}건 미만이라 비율은 제공하지 않습니다)"

    line += " · 본인의 결과를 예측하지 않습니다."
    return line


def explain_cohort(question: str, headline: str) -> str:
    """집계된 통계 문장(headline)을 사용자에게 자연스럽게 안내한다 (LLM 호출).

    LLM은 숫자를 바꾸지 않고, headline을 그대로 포함해 문장만 자연스럽게 다듬는다.
    """
    user_message = f"""사용자 질문:
Q: {question}

통계 결과 (이 문장의 숫자를 바꾸지 말고 그대로 포함할 것):
{headline}
"""

    client = get_llm_client()
    response = client.chat.completions.create(
        model=LLM_MODEL_NAME,
        max_tokens=LLM_MAX_TOKENS,
        messages=[
            {"role": "system", "content": CLAIM_SYSTEM_PROMPT},
            {"role": "user", "content": user_message},
        ],
    )
    return response.choices[0].message.content


def answer_claim_question(request: dict, cases: list[dict], index: faiss.IndexFlatIP) -> dict:
    """청구사례 RAG Tool의 진입 함수. LangGraph Node에서는 이 함수 하나만 부르면 된다.

    흐름: 유사사례 검색 -> 통계 집계(결정론 코드) -> 통계 문장 생성(결정론 코드)
         -> LLM이 그 문장을 자연스럽게 안내.

    request (입력, dict): {"question": str, "insurer": str(선택)}

    반환값 (출력, dict):
      {
        "stats": dict | None,        # aggregate_cohort() 결과 (건수/신뢰구간)
        "headline": str | None,      # 결정론 코드가 만든 통계 문장 (LLM이 다듬기 전 원본)
        "answer": str,               # LLM이 다듬은 최종 안내문
        "matched_case_count": int,
        "error": str | None,         # 검색/LLM 호출 실패 같은 '진짜' 기술적 오류만 여기 담김
      }
    """
    question = request["question"]

    filters = {}
    if request.get("insurer"):
        filters["insurer"] = request["insurer"]

    try:
        matched_cases = search_similar_cases(question, cases, index, filters=filters)
    except Exception as e:
        return {
            "stats": None, "headline": None, "answer": "",
            "matched_case_count": 0,
            "error": f"검색 중 오류가 발생했습니다: {e}",
        }

    stats = aggregate_cohort(matched_cases)
    headline = build_headline(stats)

    try:
        answer = explain_cohort(question, headline)
    except Exception as e:
        return {
            "stats": stats, "headline": headline, "answer": "",
            "matched_case_count": len(matched_cases),
            "error": f"LLM 호출 중 오류가 발생했습니다: {e}",
        }

    return {
        "stats": stats, "headline": headline, "answer": answer,
        "matched_case_count": len(matched_cases),
        "error": None,
    }


def _run_interactive() -> None:
    """터미널에서 질문을 직접 입력해가며 테스트하기 위한 REPL.

    실제 서비스에서 질문은 사용자 입력으로 들어오므로, 코드에 질문을
    고정해두지 않고 매번 input()으로 받아 그 값 그대로 RAG를 태운다.
    """
    cases = load_claim_cases()
    print(f"불러온 청구사례 수: {len(cases)}")
    index = build_index(cases)

    insurer = input("보험사 필터 (없으면 Enter): ").strip() or None
    print("\n질문을 입력하세요. 종료하려면 'exit'.")
    while True:
        question = input("\n질문> ").strip()
        if question.lower() in ("exit", "quit", "종료"):
            break
        if not question:
            continue
        request = {"question": question}
        if insurer:
            request["insurer"] = insurer
        result = answer_claim_question(request, cases, index)
        print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    _run_interactive()
