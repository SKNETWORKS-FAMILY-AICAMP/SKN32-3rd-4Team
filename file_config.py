"""
목적: 프로젝트 전체가 공유하는 설정값을 한 곳에 모아둔다 - 경로, 파일명 규칙,
     임베딩/LLM 모델명, 검색 개수 같은 값들. 나중에 모델을 바꾸거나 경로 규칙을
     바꿀 일이 생기면 이 파일 하나만 고치면 되게 하는 게 목적이다.

     pdf_to_text.py, text_to_chunks.py, main_rag_service.py 모두 이 파일의 값을 가져다 쓴다.
     (API 키처럼 비밀로 관리해야 하는 값은 여기 두지 않고 .env에서 읽는다 - main_rag_service.py 참고)
"""

import os

# ── 경로 / 파일명 규칙 ──────────────────────────────────────────
DATA_DIR = "main_rag_data"
FILTERED_SUFFIX = "_filtered.txt"   # pdf_to_text.py 결과물 파일명 접미사
CHUNKS_SUFFIX = "_chunks.json"      # text_to_chunks.py 결과물 파일명 접미사

# ── 처리할 PDF 파일 목록 ────────────────────────────────────────
# 파일이 늘어나면(다른 상품, 다른 보험사) 이 리스트에 항목만 추가하면 된다.
# source_file은 DATA_DIR 폴더 안 파일명 그대로 적는다.
FILES = [
    {
        "insurer": "현대해상",
        "product_code": "Hi2607",
        "product_type": "일반",
        "source_file": "무배당현대해상실손의료비보장보험(갱신형)(Hi2607).pdf",
    },
    {
        "insurer": "현대해상",
        "product_code": "Hi2607",
        "product_type": "노후",
        "source_file": "(무)현대해상노후실손의료비보장보험(갱신형)(Hi2607).pdf",
    },
    {
        "insurer": "현대해상",
        "product_code": "Hi2607",
        "product_type": "유병력자",
        "source_file": "무배당현대해상유병력자실손의료비보장보험(갱신형)(Hi2607).pdf",
    },
]

# ── 임베딩 / 검색 설정 (main_rag_service.py에서 사용) ─────────────────
# [주의] EMBEDDING_MODEL_NAME은 확정된 모델이 아니라, RAG 서비스(assess/explain) 로직을
# 먼저 만들고 테스트하기 위해 AI2가 임시로 골라서 설치해둔 값이다.
# 실제 임베딩 모델은 AI1(데이터/검색 담당)이 별도로 모델 비교·선정 중이며,
# 그 결과에 따라 이 값과 build_index()/search_relevant_chunks()의 벡터 저장 방식
# 자체가 통째로 바뀔 수 있다. AI1과 다른 팀원은 이 값을 "확정 스펙"으로 참고하지 말 것 -
# 우리가 정말로 맞춰야 하는 건 아래 청크 json 형식(README "네이밍 계약" 참고)뿐이다.
EMBEDDING_MODEL_NAME = "jhgan/ko-sroberta-multitask"  # TODO: AI1 모델 선정 결과로 교체 예정

# 보험사로 필터링하려면, 벡터 유사도 1등만 보면 안 되고 후보를 여러 개 뽑아서
# 그중 보험사가 일치하는 걸 걸러야 한다. 그래서 이 값은 "최종 반환 개수"가
# 아니라 "필터링 전에 미리 뽑아둘 후보 개수"다 (search_relevant_chunks 참고).
SEARCH_CANDIDATE_K = 20

# search_relevant_chunks()가 filters를 통과한 후보 중 실제로 반환할 개수(evidence 묶음 크기).
# [주의] top-1만 반환하면, 진짜 관련 조항(예: "지급하지 않는 사유")이 임베딩 유사도에서
# 밀려도(예: "지급사유" 같은 절차 조항이 더 높게 나옴) 그걸 놓치고 잘못된 근거를 확신 있게
# 내놓게 된다(실측 사례: "공황장애 보상되나요?" 질문에서 진짜 관련 조항이 5위 밖으로 밀림).
# 그래서 후보를 여러 개 묶어서 LLM에게 주고, 그중 실제로 관련 있는 것만 골라 인용하게 한다.
EVIDENCE_TOP_N = 3

# ── LLM 설정 (main_rag_service.py의 explain()에서 사용) ───────────────
LLM_MODEL_NAME = "gpt-4o-mini"  # 비용/성능 때문에 모델을 바꾸고 싶으면 이 값만 수정
LLM_MAX_TOKENS = 1024  # 응답(출력) 쪽 토큰 상한

# 프롬프트에 넣을 조항 본문 하나의 최대 글자수(입력 토큰 비용 통제용).
# [주의] 검색(임베딩)에는 영향 없다 - build_index()/search_relevant_chunks()는 항상
# 전체 본문으로 유사도를 계산한다. 이 값은 오직 LLM에게 보내는 프롬프트(explain/
# explain_term)에서만 적용된다 - EVIDENCE_TOP_N개(최대 3개) 조항의 본문 전체를
# 그대로 다 넣으면 조항 하나가 길 때(1,500자 이상인 경우가 실제로 있었음) 질문
# 하나당 입력 토큰이 꽤 커질 수 있어서다.
MAX_CHUNK_CHARS_FOR_PROMPT = 800

# ── 청크 데이터 필드명 (다양한 전처리 결과를 수용하기 위한 설정) ──
# main_rag_service.py의 chunk_to_text()가 청크에서 "임베딩할 텍스트"를 뽑을 때
# 이 필드명들을 쓴다. AI1의 전처리 결과물에서 필드명이 다르게 나오면
# (예: title -> clause_title) 코드를 고치지 않고 이 값만 바꾸면 된다.
CHUNK_TITLE_FIELD = "title"
CHUNK_BODY_FIELD = "body"

# ── 기본값 ──────────────────────────────────────────────────────
UNKNOWN_VALUE = "확인 불가"  # request에 보험사/가입일/세대 값이 없을 때 대신 쓰는 문구


def get_file_paths(file_info: dict) -> tuple[str, str, str]:
    """file_info 하나를 보고, 이 파일의 pdf/filtered_text/chunks 경로 3개를 만들어 돌려준다.

    os.path.join을 써서 윈도우/맥/리눅스 어디서 돌려도 경로가 깨지지 않게 한다.
    """
    base_name = file_info["source_file"].replace(".pdf", "")

    pdf_path = os.path.join(DATA_DIR, file_info["source_file"])
    filtered_path = os.path.join(DATA_DIR, f"{base_name}{FILTERED_SUFFIX}")
    chunks_path = os.path.join(DATA_DIR, f"{base_name}{CHUNKS_SUFFIX}")

    return pdf_path, filtered_path, chunks_path
