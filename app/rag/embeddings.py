"""임베딩 제공자 (로컬 sentence-transformers).

RULE §7: 해시 임베딩 폴백 없음. 로컬 ST 모델(ko-sroberta)은 실제 임베딩 모델이며
외부 토큰을 쓰지 않는다. 모델명은 config에서 온다(하드코딩 금지).
"""

from __future__ import annotations

from functools import lru_cache

from app.core.config import get_settings
from app.core.errors import ConfigError


@lru_cache
def get_embeddings():
    """현재 EMBEDDING_PROVIDER에 맞는 LangChain Embeddings 객체를 반환한다."""
    settings = get_settings()
    if settings.EMBEDDING_PROVIDER == "local_st":
        from langchain_huggingface import HuggingFaceEmbeddings

        model = settings.ST_EMBEDDING_MODEL
        if not (model and model.strip()):
            raise ConfigError("ST_EMBEDDING_MODEL이 비어 있습니다.")
        # 정규화하면 L2 거리가 [0,2]로 유계 → 거리 임계값(RAG_MAX_DISTANCE)이 의미를 가짐
        return HuggingFaceEmbeddings(
            model_name=model, encode_kwargs={"normalize_embeddings": True}
        )
    raise ConfigError(f"지원하지 않는 EMBEDDING_PROVIDER: {settings.EMBEDDING_PROVIDER}")
