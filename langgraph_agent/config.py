"""
config.py

역할:
    프로젝트 전역에서 쓰이는 경로/모델명 등 설정값을 모아두는 곳.
    코드 안에 경로나 모델명을 하드코딩하지 않고 여기서 한 번에 관리.

    환경(로컬 / RunPod)에 따라 경로가 다를 수 있으므로, 필요하면
    환경변수로 오버라이드 가능하게 구성.
"""

import os
from dotenv import load_dotenv

load_dotenv()  # .env에 OPENAI_API_KEY 등을 넣어두면 여기서 자동 로드

# --- 데이터 경로 ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
POLICY_DOCS_DIR = os.environ.get(
    "POLICY_DOCS_DIR", os.path.join(BASE_DIR, "data", "policy_docs")
)
VECTORSTORE_DIR = os.environ.get(
    "VECTORSTORE_DIR", os.path.join(BASE_DIR, "data", "chroma_db")
)

# --- 임베딩 모델 ---
# BAAI/bge-m3: 다국어(한국어 포함) 검색 벤치마크에서 ko-sroberta-multitask보다
# 성능이 크게 앞서는 모델. 단, 기존 jhgan/ko-sroberta-multitask로 만든
# chroma_db가 있다면 벡터 차원이 달라지므로 반드시 재구축(build_vectorstore) 필요.
EMBEDDING_MODEL_NAME = os.environ.get(
    "EMBEDDING_MODEL_NAME", "BAAI/bge-m3"
)

# --- LLM 설정 ---
LLM_MODEL_NAME = os.environ.get("LLM_MODEL_NAME", "gpt-4o")

# --- MCP 호출 타임아웃 (초) ---
MCP_TIMEOUT_SECONDS = int(os.environ.get("MCP_TIMEOUT_SECONDS", "10"))
