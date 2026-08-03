"""
목적: 보험 약관 조항을 임베딩+벡터DB로 검색하고, 근거 기반으로 답하게 하는 RAG 서비스.

[중요] 이 파일은 "Index A(보험 약관)" 전용이다 (11_AI_구조_지도.md §1, §2 기준).
  - Index A = 보험 약관 조항. 판정 근거로 인용 가능. load_all_chunks()/build_index()가
    다루는 게 이거다.
  - Index B = 외부 청구 사례(에이전트가 보내주는 보고, 통계). 판정 근거로 인용 불가 -
    참고/통계 전용이다. 이 파일에는 Index B 관련 코드가 전혀 없고, 만들어서도 안 된다.
    나중에 청구 사례 데이터를 다루게 되어도 load_all_chunks()/build_index()에 절대
    섞지 말고 완전히 별도의 함수/인덱스로 분리할 것 (판정 근거 오염 방지).
  - "용어 설명" Use Case는 별도 RAG가 아니라 Index A를 그대로 재사용한다 (용어 정의도
    결국 약관 안에 있으므로) - answer_question()을 용어 질문에 그대로 써도 된다.

이 파일은 이후 LangGraph 안에서 하나의 Tool처럼 호출될 것을 염두에 두고 만들었다.
그래서 answer_question()/answer_term_question() 각각이 명확한 입력/출력 딕셔너리
(=JSON으로 바로 변환 가능한 형태)를 주고받는 '독립적인 함수'로 동작하고,
LangChain/LangGraph에 대한 의존은 전혀 없다. 그 연결(Tool로 감싸기, Agent Workflow
연결, 두 진입점 중 어느 쪽을 호출할지 라우팅)은 AI3(LangChain/Agent 담당)가 처리할 부분.

[UseCase 2개, 진입점 2개] Index A 안에서 UseCase가 둘로 나뉜다.
  - answer_question(): "약관 판정" UseCase. 검색 -> assess(규칙 기반, 일부 구현) -> explain(verdict 설명).
  - answer_term_question(): "용어 설명" UseCase. 검색 -> explain_term(정의 설명) - assess를
    거치지 않는다. 용어 설명은 보장 여부를 판정할 필요가 없는 질문이라서다.
  둘 다 같은 데이터(Index A 청크)와 같은 검색 함수(search_relevant_chunks)를 공유하고,
  차이는 "판정까지 필요한가"뿐이다.

[중요] 판정(assess)과 설명(explain)은 분리되어 있다 (11_AI_구조_지도.md §5, §7 기준).
  - assess(): 보장 여부를 '결정'한다. LLM이 판정을 내려서는 안 되고, 조항 "종류"(면책/한도)와
    질문 낱말의 실제 등장 여부만으로 규칙을 적용한다 (05_계약_AI2_판정.md §6 기준 - 팀 저장소
    전용 타입 대신 insurance_rag의 dict 구조로 옮겨 구현함). 원 단위 자기부담금 계산과
    대기기간 판단, 세대별 차등화는 아직 안 한다 - assess() 함수 docstring 참고.
  - explain(): assess()가 이미 정한 verdict를 '바꾸지 않고', 왜 그런 verdict가 나왔는지
    약관 근거를 들어 사람이 이해하기 쉽게 설명만 한다. 여기서 LLM을 쓴다.

파이프라인:
  청크 json 로드 -> 임베딩 생성 -> FAISS 인덱스 -> 질문 임베딩 -> 유사도 검색(top-N, EVIDENCE_TOP_N개)
  -> assess(규칙 기반, 일부 구현) -> explain(LLM 호출, 후보 중 관련 있는 것만 인용) -> 답변 반환

[중요] 검색은 top-1이 아니라 top-N(EVIDENCE_TOP_N)을 반환한다. 실측으로, top-1만 보면
진짜 관련 조항(예: 면책조항 "지급하지 않는 사유")이 임베딩 유사도 순위에서 밀려도
(예: 절차 조항 "지급사유"가 더 높게 나옴) 그걸 놓치고 엉뚱한 근거를 확신 있게 내놓는
사례가 확인됐다. 그래서 후보 여러 개를 묶어(evidence bundle) LLM에게 주고, 그중
실제로 관련 있는 것만 골라 인용하게 한다 (explain()/explain_term() 참고).

특정 필드명에 강하게 의존하지 않으려고, 청크에서 '임베딩에 쓸 텍스트'를 뽑는 부분을
chunk_to_text() 함수 하나로 모아뒀다. 나중에 실제 데이터 구조(필드명 등)가 바뀌면
이 함수만 고치면 된다.

API 키(OPENAI_API_KEY)는 코드에 직접 쓰지 않고 .env 파일에서 읽어온다.
실행 전에 .env.example을 복사해서 .env로 만들고 실제 키를 넣을 것.

[알아둘 것] 지금 청크에는 '보험 세대(1~5세대)' 정보가 없다.
file_config.py에는 insurer/product_code/product_type만 있고 세대 태그가 없어서,
"가입 세대와 검색된 약관의 세대가 같은지 확인"을 데이터로 검증할 방법이 아직 없다.
지금은 generation을 호출하는 쪽에서 직접 넘겨주는 값으로만 쓰고 있고, 나중에 청크
쪽에도 세대 메타데이터를 붙일지는 AI1과 상의가 필요하다.
"""

import glob
import json
import os
import re

import numpy as np
import faiss
from sentence_transformers import SentenceTransformer
from openai import OpenAI
from dotenv import load_dotenv

# 팀 저장소(app/core/domain/citation_guard.py, kcd_ranges.py)에서 그대로 복사해온 것.
# ★수정하지 않는다 - 나중에 팀 저장소로 합칠 때 이 두 파일이 원본과 다르면
# 합치는 사람이 diff를 다시 확인해야 한다. 둘 다 "프레임워크도 바깥 계층도 모르는"
# 순수 함수 모듈이라(표준 라이브러리 re/dataclasses/enum만 씀) insurance_rag의
# dict 구조에서도 어댑터만 붙이면 그대로 쓸 수 있다.
import kcd_ranges
from citation_guard import EvidenceClause
from citation_guard import verify as verify_citation_guard

# 모델명/경로/검색 개수 등 설정값은 전부 file_config.py 하나에서 가져온다.
# (하드코딩 금지 - 나중에 모델이나 경로를 바꿀 때 file_config.py만 고치면 되게 하려는 목적)
from file_config import (
    DATA_DIR,
    CHUNKS_SUFFIX,
    CHUNK_TITLE_FIELD,
    CHUNK_BODY_FIELD,
    EMBEDDING_MODEL_NAME,
    SEARCH_CANDIDATE_K,
    EVIDENCE_TOP_N,
    LLM_MODEL_NAME,
    LLM_MAX_TOKENS,
    MAX_CHUNK_CHARS_FOR_PROMPT,
    UNKNOWN_VALUE,
)

load_dotenv()  # .env 파일에 적어둔 OPENAI_API_KEY를 환경변수로 등록

# 판정 결과(verdict) 4단계. 11_AI_구조_지도.md §3 기준 - 이진(O/X) 판정이나
# 확률(%) 표현은 쓰지 않는다. 근거를 못 찾으면 "needs_expert"로 기권한다(정상 결과).
VERDICT_LABELS = {
    "likely_covered": "보장 가능",
    "needs_documents": "조건부 확인 필요",
    "unlikely": "면책 가능성",
    "needs_expert": "전문가 확인 필요",
}

# 역할/답변규칙/답변형식 - 질문이 바뀌어도 변하지 않는 고정된 지침이라
# system 프롬프트로 분리했다 (Claude API에서 권장하는 방식).
#
# [주의] 여기서 LLM에게 시키는 건 '판정'이 아니라 '설명'이다. verdict는 이미
# assess()가 정해서 넘겨주고, LLM은 그 verdict를 바꾸지 않고 왜 그런지만 설명한다.
SYSTEM_PROMPT = """너는 실손보험 약관 판정 결과를 설명하는 AI 상담 에이전트이다.

보장 여부(verdict)는 이미 규칙 기반 판정 로직이 결정해서 너에게 전달했다.
너는 그 verdict를 바꾸지 않는다 - 오직 왜 그런 verdict가 나왔는지, 제공된 약관
근거를 들어 사용자가 이해하기 쉽게 설명하는 역할만 한다.

반드시 제공된 약관 근거(context) 안에서만 설명해야 하며,
약관에 없는 내용은 추측하거나 일반적인 보험 상식으로 보완하지 않는다.

[역할]
1. 전달받은 verdict와, 그 근거가 된 약관 조항을 확인한다.
2. 사용자의 질문 맥락(보험사/가입시점/세대/질병명 등)에 맞춰 왜 이 verdict가 나왔는지 설명한다.
3. 최종 답변에는 반드시 약관 근거(조항명/번호)를 포함한다.

[여러 후보 조항이 주어짐]
검색된 약관 정보는 조항 하나가 아니라 후보 여러 개(번호 매김)로 주어진다. 그중
질문과 실제로 관련 있는 조항만 근거로 골라 인용한다 - 관련 없는 후보는 답변에서
언급하지 않는다. 후보 전부가 관련 없다고 판단되면 억지로 아무거나 인용하지 말고
그렇게 판단한 이유를 반영해 답한다.

[답변 규칙]
1. verdict를 임의로 바꾸거나 새로 판단하지 않는다 - 전달받은 verdict를 그대로 설명한다.
2. 약관 조항을 참고한 경우 반드시 조항명 또는 조항 번호를 함께 표시한다.
   예시: "약관 제5조(보험금 지급 기준)에 따르면..."
3. 절대 다음을 하지 않는다:
   - 보험 업계 일반 지식으로 추론
   - 다른 세대 보험 기준 적용
   - 다른 보험사의 약관 적용
   - 보장 가능성을 확률이나 수치(%)로 표현
4. 질병명과 질병코드가 함께 제공되는 경우: 질병명 / 질병코드 / 약관상 보장 관련 여부를 함께 설명한다.
5. 사용자가 이해하기 어려운 약관 표현은 쉬운 말로 다시 설명한다.

[답변 형식]
고객님이 가입한 {보험사} 보험 기준으로 확인해보겠습니다.

{가입 조건 및 보험 세대 설명}

질문하신 "{질병명/치료항목}"에 대한 판정 결과는 [{verdict_label}]입니다.

[약관 근거]
- {약관 조항명 또는 조항 번호}
- {관련 약관 내용 요약}

[쉽게 설명하면]
{고객이 이해하기 쉬운 설명}

※ 제공된 약관 정보 기준이며, 실제 보험금 지급 여부는 보험금 청구 심사 결과에 따라 달라질 수 있습니다.

[JSON 출력 형식 - 반드시 이 형식으로만 응답한다]
자유 텍스트가 아니라 아래 3개 키를 가진 JSON 객체 하나로만 응답한다:
{
  "cited_clauses": ["실제로 인용한 후보의 제목을 그대로, 후보 번호가 아니라 제목 문자열로"],
  "quotes": {"그 제목": "그 후보 본문에서 실제로 그대로 가져온 문장(요약/의역 금지)"},
  "reason": "위 [답변 형식]을 그대로 따른 최종 답변 문자열"
}
cited_clauses/quotes는 답변을 검증하는 데 쓰인다 - 여기 적은 제목과 인용문이 실제
후보 원문과 다르면 답변 전체가 폐기되니, 반드시 후보에 있는 제목/문장을 그대로 옮겨 적는다.
"""

# "용어 설명" UseCase 전용 프롬프트. SYSTEM_PROMPT(판정 설명용)와 다른 이유:
# 용어 설명은 verdict가 없다 - 보장 여부를 판정하는 질문이 아니라서 assess()를
# 아예 거치지 않는다. 그래서 "verdict를 그대로 전달받아 설명"하는 지침 대신,
# "약관 안의 정의를 찾아서 쉬운 말로 설명"하는 지침만 있으면 된다.
TERM_SYSTEM_PROMPT = """너는 보험 약관 용어를 설명하는 AI 상담 도우미이다.

사용자가 물어본 용어나 표현에 대해, 제공된 약관 근거(context) 안에서 정의를
찾아 쉬운 말로 설명한다. 보장 여부를 판정하지 않는다 - 이 기능은 용어 설명 전용이다.

검색된 약관 정보는 조항 하나가 아니라 후보 여러 개(번호 매김)로 주어진다. 그중
실제로 용어 정의가 담긴 후보만 골라 설명하고, 관련 없는 후보는 언급하지 않는다.

반드시 제공된 약관 근거 안에서만 설명해야 하며, 근거에 없는 내용은 추측하거나
일반적인 보험 상식으로 보완하지 않는다. 근거를 찾지 못하면
"제공된 약관 정보에서는 확인되지 않습니다"라고 답한다.

[답변 형식]
[용어 설명]
{쉬운 말로 풀어쓴 정의}

[약관 근거]
- {약관 조항명 또는 조항 번호}
- {관련 약관 내용 요약}

[JSON 출력 형식 - 반드시 이 형식으로만 응답한다]
자유 텍스트가 아니라 아래 3개 키를 가진 JSON 객체 하나로만 응답한다:
{
  "cited_clauses": ["실제로 인용한 후보의 제목을 그대로, 후보 번호가 아니라 제목 문자열로"],
  "quotes": {"그 제목": "그 후보 본문에서 실제로 그대로 가져온 문장(요약/의역 금지)"},
  "reason": "위 [답변 형식]을 그대로 따른 최종 답변 문자열"
}
cited_clauses/quotes는 답변을 검증하는 데 쓰인다 - 여기 적은 제목과 인용문이 실제
후보 원문과 다르면 답변 전체가 폐기되니, 반드시 후보에 있는 제목/문장을 그대로 옮겨 적는다.
"""

_embedding_model = None  # 한 번만 불러와서 재사용 (매번 다시 로드하면 느림)
_llm_client = None  # 한 번만 만들어서 재사용


def get_embedding_model() -> SentenceTransformer:
    """file_config.EMBEDDING_MODEL_NAME으로 임베딩 모델을 불러온다.

    [주의] 이 모델은 AI1의 실제 모델 선정 결과가 나올 때까지 쓰는 임시값이다.
    나중에 모델이 바뀌어도 이 함수의 호출부(build_index, search_relevant_chunks)는
    안 고쳐도 되고, file_config.py의 EMBEDDING_MODEL_NAME 값만 바꾸면 된다.
    """
    global _embedding_model
    if _embedding_model is None:
        _embedding_model = SentenceTransformer(EMBEDDING_MODEL_NAME)
    return _embedding_model


def get_llm_client() -> OpenAI:
    """OpenAI 클라이언트를 만든다.

    OpenAI()는 API 키가 없으면 '만드는 순간' 바로 에러를 던진다
    (Claude와 다른 점 - Claude는 실제 호출 시점에야 에러가 남).
    그래서 이 함수를 파일 맨 위가 아니라 ask_llm() 안에서, answer_question()의
    try/except로 감싸질 수 있는 시점에 호출해야 에러가 깔끔하게 처리된다.
    """
    global _llm_client
    if _llm_client is None:
        _llm_client = OpenAI()
    return _llm_client


def load_all_chunks(data_dir: str = DATA_DIR) -> list[dict]:
    """data 폴더 안의 모든 청크 json 파일을 찾아서 하나의 리스트로 합친다.

    파일 하나만 보게 하드코딩하지 않고 폴더 전체를 훑기 때문에,
    나중에 다른 보험사 청크 파일이 추가돼도 코드를 안 고쳐도 된다.
    확장자 패턴(CHUNKS_SUFFIX)도 file_config.py에서 가져온 값이라,
    text_to_chunks.py의 저장 규칙이 바뀌어도 여기가 자동으로 맞춰진다.
    """
    chunks = []
    for path in glob.glob(os.path.join(data_dir, f"*{CHUNKS_SUFFIX}")):
        with open(path, "r", encoding="utf-8") as f:
            chunks.extend(json.load(f))
    return chunks


def chunk_to_text(chunk: dict) -> str:
    """청크에서 임베딩/프롬프트에 쓸 텍스트를 뽑는다.

    필드명을 'title'/'body'로 직접 하드코딩하지 않고 file_config.py의
    CHUNK_TITLE_FIELD/CHUNK_BODY_FIELD를 쓴다. 나중에 다른 전처리 결과물이
    다른 필드명을 쓰더라도, 이 함수를 고칠 필요 없이 file_config.py 값만
    바꾸면 되게 하려는 목적이다.
    """
    return f"{chunk.get(CHUNK_TITLE_FIELD, '')}\n{chunk.get(CHUNK_BODY_FIELD, '')}"


def build_index(chunks: list[dict]) -> faiss.IndexFlatIP:
    """모든 청크를 임베딩해서 FAISS 벡터 인덱스를 만든다."""
    model = get_embedding_model()
    texts = [chunk_to_text(c) for c in chunks]
    embeddings = model.encode(texts, normalize_embeddings=True)  # 정규화 -> 내적이 코사인 유사도와 같아짐

    dimension = embeddings.shape[1]
    index = faiss.IndexFlatIP(dimension)
    index.add(np.array(embeddings, dtype="float32"))
    return index


def search_relevant_chunks(question: str, chunks: list[dict], index: faiss.IndexFlatIP, filters: dict | None = None) -> list[dict]:
    """질문을 임베딩해서, 조건(filters)에 맞는 청크를 유사도 순으로 최대 EVIDENCE_TOP_N개 찾는다.

    [왜 1개가 아니라 여러 개인가] 예전에는 가장 유사한 청크 1개만 반환했는데,
    임베딩 유사도 1등이 항상 진짜 정답은 아니었다 - 실측으로 "공황장애 보상되나요?"
    질문에서 진짜 관련 조항("지급하지 않는 사유", 면책조항)이 절차 조항("지급사유")
    보다 순위가 밀려 top-1에서 놓쳤다. 그래서 후보를 여러 개(EVIDENCE_TOP_N) 묶어서
    돌려주고, 그중 실제로 관련 있는 걸 LLM이 골라 인용하게 한다(explain 참고).

    [메타데이터 기반 필터링] filters는 {필드명: 값} 형태의 딕셔너리다.
    예: {"insurer": "현대해상"}, 나중에는 {"insurer": "현대해상", "generation": "5세대"}처럼
    필드를 추가할 수 있다. 벡터 유사도 상위 SEARCH_CANDIDATE_K개 후보 중에서
    filters의 모든 항목이 일치하는 것만 유사도 순으로 최대 EVIDENCE_TOP_N개 돌려준다.

    이 함수는 특정 필드(예: insurer)를 안다고 가정하지 않는다 - 어떤 필드로 거를지는
    호출하는 쪽(answer_question)이 filters에 담아서 넘겨준다. 그래서 나중에
    새로운 메타데이터 필드(세대 등)가 청크에 추가돼도 이 함수는 안 고쳐도 된다.

    [알아둘 것] '세대(generation)' 필터링은 아직 못 한다 - 청크 데이터에 세대
    필드 자체가 없기 때문이다 (file_config.py, README 알려진 한계 참고). filters에
    청크에 없는 필드를 넣으면 전부 안 맞는 걸로 처리돼 아무것도 못 찾게 되니,
    generation처럼 아직 없는 필드는 filters에 넣지 말 것 (answer_question 참고).
    """
    if len(chunks) == 0:
        return []

    filters = filters or {}

    model = get_embedding_model()
    question_embedding = model.encode([question], normalize_embeddings=True)

    # SEARCH_CANDIDATE_K: 필터링 여유를 두기 위해 EVIDENCE_TOP_N보다 넉넉히 뽑는다.
    _, indices = index.search(np.array(question_embedding, dtype="float32"), SEARCH_CANDIDATE_K)

    matched = []
    for idx in indices[0]:
        if idx < 0:  # 청크 수가 SEARCH_CANDIDATE_K보다 적어서 채워진 빈 자리
            continue

        chunk = chunks[idx]
        # filters의 모든 (필드, 값) 쌍이 청크와 일치해야 통과 (AND 조건)
        if any(chunk.get(field) != value for field, value in filters.items()):
            continue  # 필터 조건 중 하나라도 안 맞으면 후보에서 제외

        matched.append(chunk)
        if len(matched) >= EVIDENCE_TOP_N:
            break

    return matched  # 조건을 만족하는 것 중 유사도가 높은 순으로 최대 EVIDENCE_TOP_N개


# 조항 "제목"만으로 종류를 구분한다 (05_계약_AI2_판정.md §6 기준 - 이 문서의 팀 저장소
# 전용 타입(EvidenceBundleV1 등)을 그대로 쓸 수는 없어서, insurance_rag의 dict 기반
# 구조에 맞게 같은 취지를 옮겨 적용했다).
#
# [의도적으로 안 하는 것] 원 단위 자기부담금 계산(계약서 §6-1)은 여기서 하지 않는다.
# 실제 조항의 <표1> 같은 표가 PDF 추출 과정에서 컬럼이 뒤섞여 나온다
# (main_rag_data/*_filtered.txt로 직접 확인함 - 예: "일반" 제5조 본문에 입원/통원
# 항목과 금액이 서로 다른 줄에 잘못 붙어 나옴). 이 상태에서 숫자를 정규식으로
# 뽑아 계산하면, 코드가 "확실한 근거로 계산했다"는 인상을 주면서 실제로는 틀린
# 금액을 낼 위험이 있다 - 05_계약_AI2_판정.md §2 "기권을 부끄러워하기 금지" 원칙상
# 계산을 지어내느니 "조건부 확인 필요"로 넘기는 쪽을 택했다.
_EXCLUSION_TITLE_HINTS = ["지급하지 않는 사유"]
_LIMIT_TITLE_HINTS = ["보험가입금액 한도", "지급에 관한 세부규정"]


def _clause_kind(chunk: dict) -> str:
    """조항 제목으로 종류를 구분한다: "exclusion"(면책) / "limit"(한도·자기부담금) / "other"."""
    title = chunk.get(CHUNK_TITLE_FIELD, "")
    if any(hint in title for hint in _EXCLUSION_TITLE_HINTS):
        return "exclusion"
    if any(hint in title for hint in _LIMIT_TITLE_HINTS):
        return "limit"
    return "other"


def _mentions_question_terms(question: str, chunk: dict) -> bool:
    """질문에 쓰인 낱말이 조항 본문에 문자 그대로 등장하는지 본다.

    "정신질환이니까 비슷하게 판단한다" 같은 근거를 넘어선 추론을 하지 않기 위해
    (05_계약_AI2_판정.md §2), 의미 유사도가 아니라 문자열 등장 여부만 본다.

    [주의] 짧은 낱말 하나만 우연히 겹치는 걸로는 "관련 있다"고 안 본다 - 실측으로
    "완전히 무관한 이야기입니다"라는, 조항과 전혀 상관없는 질문에서 "무관한"이라는
    낱말이 그 조항 본문에 우연히 등장해 잘못 "관련 있음"으로 판단된 적이 있다.
    그래서 (a) 4글자 이상 낱말이 하나라도 겹치거나 (b) 2글자 이상 낱말이 2개 이상
    겹쳐야만 "실제로 이 조항 얘기"로 본다 - 우연한 짧은 낱말 하나의 일치보다는
    차라리 놓치고 기권(needs_expert)하는 쪽이 안전하다(§2 "기권을 부끄러워하기 금지").
    """
    body = chunk.get(CHUNK_BODY_FIELD, "")
    terms = [t for t in re.split(r"\s+", question.strip()) if len(t) >= 2]
    matched = [t for t in terms if t in body]
    return len(matched) >= 2 or any(len(t) >= 4 for t in matched)


def kcd_verdict(kcd_codes: list[str], chunks: list[dict]) -> str | None:
    """kcd_ranges.py(팀 저장소 원본, 그대로 복사해옴)로 KCD 코드 기준 면책 여부를 본다.

    약관은 면책을 질병명이 아니라 KCD 코드 범위("F04~F99" 등)로 적는 경우가 많다는
    게 팀 실측 결과다 - 그래서 코드가 있을 때는 이 경로가 title 키워드 매칭보다
    훨씬 정확하다. 진료비 내역서에는 KCD 코드가 이미 적혀 있으므로, 실제 서비스라면
    이 경로가 기본이 된다(05_계약_AI2_판정.md 골든세트 예시도 kcd_codes를 입력으로 받음).

    반환값: "unlikely"(면책 코드로 확인됨) | "needs_documents"(면책의 예외 조항 걸림 -
    조건부 확인 필요) | None(코드 기준으로는 못 정함 - 호출부가 기존 규칙으로 계속 판단).
    """
    statuses = []
    for chunk in chunks:
        mentions = kcd_ranges.scan_clause(chunk.get(CHUNK_BODY_FIELD, ""))
        for code in kcd_codes:
            statuses.append(kcd_ranges.judge(code, mentions)["status"])

    if "excluded" in statuses:
        return "unlikely"
    if "exception" in statuses:
        return "needs_documents"
    return None


def assess(question: str, chunks: list[dict], request: dict) -> str:
    """규칙 기반 판정 함수 (05_계약_AI2_판정.md §6 기준, 팀 저장소 타입 대신 insurance_rag의
    dict 구조로 구현. kcd_ranges 판단만은 팀 저장소 원본 코드를 그대로 씀 - kcd_verdict 참고).

    chunks는 search_relevant_chunks()가 찾은 후보 여러 개(evidence bundle)다.

    지금 실제로 하는 판단:
      0. request에 kcd_codes(예: ["F32"])가 있으면 kcd_verdict()로 먼저 본다 -
         KCD 코드 범위 기반 판단이 아래 1)보다 정확하다.
      1. (kcd_codes가 없거나 0에서 못 정했으면) 면책조항("보험금을 지급하지 않는
         사유")이 근거에 있고, 질문의 낱말이 그 조항 본문에 실제로 등장하면
         -> "unlikely"(면책 가능성).
      2. 한도/자기부담금 관련 조항("보험가입금액 한도", "지급에 관한 세부규정")이
         근거에 있으면 -> "needs_documents"(조건부 확인 필요 - 05_계약_AI2_판정.md
         §6-2 "한도·대기기간 → needs_documents 구체화"에 해당).
      3. 셋 다 아니면 -> "needs_expert"(안전한 기본값, 근거 부족).

    [의도적으로 안 하는 것]
      - "likely_covered"는 아예 내지 않는다. 면책 목록에 없다고 보장된다는 뜻이
        아니라서(계약서 §2 첫 항목 "not_mentioned를 likely_covered로 올리기 금지"),
        긍정 판정에는 훨씬 강한 근거(명확한 '보상하는 사항' 조항)가 필요한데
        지금은 그런 조항을 구조적으로 구분할 방법이 없다.
      - 원 단위 자기부담금 계산, 대기기간 판단: 위 모듈 docstring/README 참고.
      - '세대'(1~5세대)별 차등화: 청크에 세대 필드가 없어 여전히 못 한다
        (request.get("generation")은 받아도 검증할 데이터가 없음).

    반환값은 VERDICT_LABELS의 키 중 하나:
      "needs_documents" | "unlikely" | "needs_expert"  (지금은 "likely_covered" 미사용)
    """
    kcd_codes = request.get("kcd_codes") or []
    if kcd_codes:
        verdict = kcd_verdict(kcd_codes, chunks)
        if verdict is not None:
            return verdict

    exclusion_hit = any(
        _clause_kind(c) == "exclusion" and _mentions_question_terms(question, c)
        for c in chunks
    )
    if exclusion_hit:
        return "unlikely"

    if any(_clause_kind(c) == "limit" for c in chunks):
        return "needs_documents"

    return "needs_expert"


def build_evidence_context(chunks: list[dict]) -> str:
    """검색된 후보 조항 여러 개를 번호를 매겨 하나의 컨텍스트 문자열로 합친다.

    explain()/explain_term()이 LLM에게 "이 중 실제로 관련 있는 것만 인용하라"고
    시킬 수 있으려면, 후보들을 구분 가능한 형태로 나열해서 줘야 한다.

    [비용 통제] 조항 본문이 MAX_CHUNK_CHARS_FOR_PROMPT(글자수)보다 길면 잘라서
    보낸다 - 검색(임베딩)은 전체 본문으로 하니 영향 없고, 여기(LLM 입력)만 자른다.
    citation_guard.verify()는 원본 전체 본문과 대조하므로, 잘린 뒷부분에서 나올 법한
    문장은 애초에 LLM이 보지도 못해 인용할 수 없다 - 검증 결과가 어긋나지 않는다.
    """
    parts = []
    for i, chunk in enumerate(chunks, start=1):
        text = chunk_to_text(chunk)
        if len(text) > MAX_CHUNK_CHARS_FOR_PROMPT:
            text = text[:MAX_CHUNK_CHARS_FOR_PROMPT] + " …(이하 생략)"
        parts.append(f"[후보 {i}]\n{text}")
    return "\n\n".join(parts)


def build_user_message(question: str, insurer: str, join_date: str, generation: str, verdict_label: str, chunks: list[dict]) -> str:
    """질문마다 바뀌는 정보(질문, 가입 정보, verdict, 검색된 약관 후보들)를 담은 메시지를 만든다."""
    context = build_evidence_context(chunks)

    return f"""보험 정보:
- 보험사: {insurer}
- 가입일: {join_date}
- 보험 세대: {generation}

판정 결과 (이미 결정됨, 바꾸지 말 것):
{verdict_label}

검색된 약관 정보:
{context}

사용자 질문:
Q: {question}
"""


def _call_llm_json(system_prompt: str, user_message: str) -> dict:
    """explain()/explain_term() 공용 LLM 호출부 - JSON 응답을 강제한다.

    자유 텍스트가 아니라 `response_format={"type": "json_object"}`로 구조화된
    JSON(cited_clauses/quotes/reason)을 받는다 - citation_guard.verify()가 인용을
    코드로 대조하려면 이 구조가 있어야 한다 (05_계약_AI2_판정.md §4 "LLM 출력
    형식 강제"에 해당, cited_clauses/quotes는 citation_guard.verify()의 실제
    파라미터 이름과 맞췄다).
    """
    client = get_llm_client()
    response = client.chat.completions.create(
        model=LLM_MODEL_NAME,  # file_config.py 설정값 (하드코딩 금지 - 모델 교체는 그 파일만 고치면 됨)
        max_tokens=LLM_MAX_TOKENS,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ],
    )
    return json.loads(response.choices[0].message.content)


def _to_evidence_clauses(chunks: list[dict]) -> list[EvidenceClause]:
    """insurance_rag 청크(dict)를 citation_guard.EvidenceClause로 바꾼다.

    ★이 파일에서 가장 얇아야 하는 부분 - 나중에 팀 저장소의 진짜 근거 타입
    (ClauseRow 등)으로 교체될 때, citation_guard 호출부는 그대로 두고 이
    어댑터 함수만 바꾸면 된다.
    """
    return [
        EvidenceClause(qualified_no=c.get(CHUNK_TITLE_FIELD, ""), text=c.get(CHUNK_BODY_FIELD, ""))
        for c in chunks
    ]


def explain(question: str, verdict: str, chunks: list[dict], insurer: str, join_date: str, generation: str) -> tuple[str, str | None]:
    """이미 정해진 verdict를, 약관 근거를 들어 사람이 이해하기 쉽게 설명한다 (LLM 호출).

    verdict를 '결정'하지 않는다 - assess()가 결정한 걸 그대로 받아서 설명만 한다.
    chunks는 후보 여러 개(evidence bundle) - SYSTEM_PROMPT가 그중 관련 있는 것만
    골라 인용하도록 지시한다.

    인용 검증은 팀 저장소 원본 `citation_guard.verify()`를 그대로 쓴다(직접 만든
    간이 버전 대신 - v1의 실측 버그들까지 고친 v2라 훨씬 정교함).

    반환값: (answer, warning). 검증 실패하면 answer=""이고 warning에 이유가 담긴다 -
    이때도 verdict 자체는 안 바뀐다(assess()가 이미 정했고, 설명 생성 실패가 그
    판정까지 무효로 만들 이유는 없다는 판단 - answer_question() 참고).
    """
    verdict_label = VERDICT_LABELS[verdict]
    user_message = build_user_message(question, insurer, join_date, generation, verdict_label, chunks)
    llm_output = _call_llm_json(SYSTEM_PROMPT, user_message)
    reason_text = llm_output.get("reason", "")
    result = verify_citation_guard(
        cited_clauses=llm_output.get("cited_clauses") or [],
        evidence=_to_evidence_clauses(chunks),
        answer_text=reason_text,
        quotes=llm_output.get("quotes") or {},
    )
    if not result.ok:
        return "", f"설명 생성 결과가 인용 검증에 실패해 폐기함: {result.reason}"
    return reason_text, None


def build_term_user_message(question: str, chunks: list[dict]) -> str:
    """용어 설명용 메시지를 만든다. verdict가 없으니 build_user_message보다 훨씬 단순하다."""
    context = build_evidence_context(chunks)

    return f"""검색된 약관 정보:
{context}

사용자 질문:
Q: {question}
"""


def explain_term(question: str, chunks: list[dict]) -> tuple[str, str | None]:
    """약관 안의 정의를 찾아 용어를 쉬운 말로 설명한다 (LLM 호출).

    assess()를 거치지 않는다 - 용어 설명은 판정이 필요 없는 질문이라서다.
    chunks는 후보 여러 개(evidence bundle) - TERM_SYSTEM_PROMPT가 그중 정의가
    담긴 것만 골라 설명하도록 지시한다.

    반환값: (answer, warning) - explain()과 동일하게, 팀 저장소 원본
    `citation_guard.verify()`로 검증하고 실패 시 answer=""이고 warning에 이유가 담긴다.
    """
    user_message = build_term_user_message(question, chunks)
    llm_output = _call_llm_json(TERM_SYSTEM_PROMPT, user_message)
    reason_text = llm_output.get("reason", "")
    result = verify_citation_guard(
        cited_clauses=llm_output.get("cited_clauses") or [],
        evidence=_to_evidence_clauses(chunks),
        answer_text=reason_text,
        quotes=llm_output.get("quotes") or {},
    )
    if not result.ok:
        return "", f"설명 생성 결과가 인용 검증에 실패해 폐기함: {result.reason}"
    return reason_text, None


def summarize_chunk(chunk: dict) -> dict:
    """청크에서 응답에 포함할 요약 정보만 뽑는다 (answer_question/answer_term_question 공용)."""
    return {
        "chunk_id": chunk.get("chunk_id"),
        "title": chunk.get(CHUNK_TITLE_FIELD),
        "insurer": chunk.get("insurer"),
        "product_type": chunk.get("product_type"),
    }


def answer_term_question(request: dict, chunks: list[dict], index: faiss.IndexFlatIP) -> dict:
    """"용어 설명" UseCase의 진입 함수. answer_question()과 데이터/검색은 같지만
    assess()를 거치지 않고 바로 explain_term()으로 간다.

    request (입력, dict): {"question": str, "insurer": str(선택)}
    반환값 (출력, dict): answer_question()과 같은 모양이되, verdict/verdict_label은
    항상 None이다 (용어 설명에는 판정 개념이 없으므로).
    """
    question = request["question"]

    filters = {}
    if request.get("insurer"):
        filters["insurer"] = request["insurer"]

    try:
        matched = search_relevant_chunks(question, chunks, index, filters=filters)
    except Exception as e:
        return {
            "verdict": None, "verdict_label": None, "abstained": False,
            "answer": "", "matched_chunks": [], "warnings": [],
            "error": f"검색 중 오류가 발생했습니다: {e}",
        }

    if not matched:
        return {
            "verdict": None, "verdict_label": None, "abstained": True,
            "answer": "제공된 약관 정보에서는 확인되지 않습니다.", "matched_chunks": [], "warnings": [],
            "error": None,
        }

    try:
        answer, warning = explain_term(question, matched)
    except Exception as e:
        return {
            "verdict": None, "verdict_label": None, "abstained": False,
            "answer": "", "matched_chunks": [summarize_chunk(c) for c in matched], "warnings": [],
            "error": f"LLM 호출 중 오류가 발생했습니다: {e}",
        }

    return {
        "verdict": None, "verdict_label": None, "abstained": False,
        "answer": answer, "matched_chunks": [summarize_chunk(c) for c in matched],
        "warnings": [warning] if warning else [],
        "error": None,
    }


def answer_question(request: dict, chunks: list[dict], index: faiss.IndexFlatIP) -> dict:
    """RAG Tool의 진짜 입구 함수. LangGraph Node에서는 이 함수 하나만 부르면 된다.

    흐름: 검색(top-N) -> assess(규칙 기반 판정, 일부 구현) -> explain(LLM 설명).
    근거를 못 찾으면 "기권"하는 게 정상 결과다(오류가 아님) - 11_AI_구조_지도.md §3.

    request (입력, dict):
      {"question": str, "insurer": str, "join_date": str, "generation": str}

    반환값 (출력, dict):
      {
        "verdict": "likely_covered" | "needs_documents" | "unlikely" | "needs_expert" | None,
        "verdict_label": str | None,
        "abstained": bool,   # True면 근거 부족으로 판단을 보류함 (정상 결과, 오류 아님)
        "answer": str,
        "matched_chunks": list[dict],  # 검색된 후보 최대 EVIDENCE_TOP_N개 (빈 리스트면 근거 없음)
        "warnings": list[str],  # 인용 검증 실패 등 - verdict는 안 바뀌지만 참고할 경고
        "error": str | None,  # 검색/LLM 호출 실패 같은 '진짜' 기술적 오류만 여기 담김
      }
    """
    question = request["question"]

    # 메타데이터 필터 구성. 지금은 insurer만 넣는다 - generation은 청크 데이터에
    # 필드 자체가 없어서, 여기 넣으면 모든 청크가 걸러져 아무것도 못 찾게 된다.
    # 나중에 청크에 generation 필드가 생기면 여기에 한 줄만 추가하면 된다.
    filters = {}
    if request.get("insurer"):
        filters["insurer"] = request["insurer"]

    try:
        matched = search_relevant_chunks(question, chunks, index, filters=filters)
    except Exception as e:
        return {
            "verdict": None, "verdict_label": None, "abstained": False,
            "answer": "", "matched_chunks": [], "warnings": [],
            "error": f"검색 중 오류가 발생했습니다: {e}",
        }

    if not matched:
        return {
            "verdict": "needs_expert", "verdict_label": VERDICT_LABELS["needs_expert"], "abstained": True,
            "answer": "제공된 약관 정보에서는 확인되지 않습니다.", "matched_chunks": [], "warnings": [],
            "error": None,
        }

    verdict = assess(question, matched, request)
    chunk_summaries = [summarize_chunk(c) for c in matched]

    try:
        answer, warning = explain(
            question=question,
            verdict=verdict,
            chunks=matched,
            # request에 값이 없으면 UNKNOWN_VALUE(file_config.py 설정값)로 대체
            insurer=request.get("insurer", UNKNOWN_VALUE),
            join_date=request.get("join_date", UNKNOWN_VALUE),
            generation=request.get("generation", UNKNOWN_VALUE),
        )
    except Exception as e:
        return {
            "verdict": verdict, "verdict_label": VERDICT_LABELS[verdict], "abstained": False,
            "answer": "", "matched_chunks": chunk_summaries, "warnings": [],
            "error": f"LLM 호출 중 오류가 발생했습니다: {e}",
        }

    return {
        "verdict": verdict, "verdict_label": VERDICT_LABELS[verdict], "abstained": False,
        "answer": answer, "matched_chunks": chunk_summaries,
        "warnings": [warning] if warning else [],
        "error": None,
    }


def _run_interactive() -> None:
    """터미널에서 질문을 직접 입력해가며 테스트하기 위한 REPL.

    실제 서비스에서 질문은 사용자 입력으로 들어오므로, 코드에 질문을
    고정해두지 않고 매번 input()으로 받아 그 값 그대로 RAG를 태운다.
    """
    chunks = load_all_chunks()
    print(f"불러온 청크 수: {len(chunks)}")
    index = build_index(chunks)

    print("\n테스트할 UseCase를 선택하세요.")
    print("  1) 약관 판정 (answer_question)")
    print("  2) 용어 설명 (answer_term_question)")
    mode = input("선택 (1/2): ").strip()

    if mode == "2":
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
            result = answer_term_question(request, chunks, index)
            print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        insurer = input("보험사 (예: 현대해상, 없으면 Enter): ").strip() or None
        join_date = input("가입일 (예: 2025년 7월, 없으면 Enter): ").strip() or None
        generation = input("보험 세대 (예: 5세대, 없으면 Enter): ").strip() or None
        print("\n질문을 입력하세요. 종료하려면 'exit'.")
        while True:
            question = input("\n질문> ").strip()
            if question.lower() in ("exit", "quit", "종료"):
                break
            if not question:
                continue
            request = {
                "question": question,
                "insurer": insurer,
                "join_date": join_date,
                "generation": generation,
            }
            result = answer_question(request, chunks, index)
            print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    _run_interactive()
