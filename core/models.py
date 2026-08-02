"""LLM 티어 레지스트리 — 프로젝트에서 유일하게 LLM을 생성하는 곳.
티어 배정 근거: docs/README_FEATURE234_TOOLS.md, README_LLM.md (전부 실측)
"""
from functools import lru_cache

# 티어 정의 (모델 변경 시 여기만 수정)
TIER_CONFIG = {
    # 기능1 보장 판별: 함정 방어 일관성이 결정 요인 (README_LLM 4절)
    "heavy": {"provider": "openai", "model": "gpt-4.1"},
    # 기능2·3·4 툴 변환 + 기능5 용어 설명: 멀티턴 13/14, 무료·로컬
    "light": {"provider": "ollama", "model": "qwen3:8b"},
}

TIMEOUT_S = 30      # Qwen 장고(최악 704s 실측) 방어 — 전 티어 공통


@lru_cache(maxsize=None)
def get_llm(tier: str):
    cfg = TIER_CONFIG[tier]
    if cfg["provider"] == "openai":
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(model=cfg["model"], temperature=0, timeout=TIMEOUT_S)
    if cfg["provider"] == "ollama":
        from langchain_ollama import ChatOllama
        # ChatOllama는 timeout 파라미터가 없어 호출측(agent)에서 제한
        return ChatOllama(model=cfg["model"], temperature=0)
    raise ValueError(f"unknown provider: {cfg['provider']}")