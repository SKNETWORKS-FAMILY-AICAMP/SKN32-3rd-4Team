"""
rag/search_policy.py

역할:
    build_vectorstore.py로 구축한 벡터DB에서 세대 필터링 + 유사도 검색을 수행.
    이 함수가 mcp_tools/policy_rag_server.py에서 MCP 도구로 그대로 래핑된다.

무폴백 원칙:
    검색 결과가 없으면 빈 리스트를 반환한다. 호출한 쪽(nodes/mcp_caller.py)에서
    빈 결과를 받으면 needs_fallback=True로 표시해서 knowledge_gap 노드로 보내야 한다.
    여기서 임의로 답을 만들어내지 않는다.
"""

from langchain_community.vectorstores import Chroma
from langchain_huggingface import HuggingFaceEmbeddings

from config import VECTORSTORE_DIR, EMBEDDING_MODEL_NAME

_embeddings = None
_vectorstore = None


def _get_vectorstore():
    global _embeddings, _vectorstore
    if _vectorstore is None:
        _embeddings = HuggingFaceEmbeddings(
            model_name=EMBEDDING_MODEL_NAME,
            encode_kwargs={"normalize_embeddings": True},
        )
        _vectorstore = Chroma(
            persist_directory=VECTORSTORE_DIR,
            embedding_function=_embeddings,
        )
    return _vectorstore


def search_policy_clause(
    query: str,
    generation: str | None = None,
    top_k: int = 5,
) -> list[dict]:
    """
    Args:
        query: 검색 질의 (예: "우울증 입원 보장 여부")
        generation: 세대 필터 (예: "3세대"). None이면 전체 세대 검색.
        top_k: 반환할 최대 청크 수

    Returns:
        [{"article_no", "article_title", "content", "generation",
          "source_file", "score"}, ...] 형식의 리스트. 결과 없으면 빈 리스트.
    """
    vectorstore = _get_vectorstore()
    filter_dict = {"generation": generation} if generation else None

    results = vectorstore.similarity_search_with_score(
        query, k=top_k, filter=filter_dict
    )

    return [
        {
            "article_no": doc.metadata.get("article_no"),
            "article_title": doc.metadata.get("article_title"),
            "content": doc.page_content,
            "generation": doc.metadata.get("generation"),
            "source_file": doc.metadata.get("source_file"),
            "score": round(float(score), 4),
        }
        for doc, score in results
    ]
