"""RAG 서비스 (로드 1회) — PDF4: 서버 기동 시 인덱스를 한 번만 로드.

similarity_search_with_score의 점수는 '거리'(작을수록 유사, 코사인과 반대)이므로
반환 필드명을 distance로 둔다.
"""

from __future__ import annotations

from typing import Any

from app.core.config import get_settings
from app.core.errors import InfraError
from app.rag.embeddings import get_embeddings

_store = None  # 모듈레벨 캐시 (로드 1회)


def reset_store() -> None:
    """테스트 격리용: 캐시된 인덱스를 비운다."""
    global _store
    _store = None


def get_store():
    """VECTOR_DIR의 FAISS 인덱스를 1회 로드해 캐시한다. 없으면 명확한 오류."""
    global _store
    if _store is not None:
        return _store
    from langchain_community.vectorstores import FAISS

    out_dir = get_settings().VECTOR_DIR
    if not ((out_dir / "index.faiss").exists() and (out_dir / "index.pkl").exists()):
        raise InfraError(
            f"FAISS 인덱스가 없습니다: {out_dir}. 먼저 build_index를 실행하세요."
        )
    # allow_dangerous_deserialization: 자체 생성한 VECTOR_DIR만 로드한다는 전제 (신뢰 소스)
    _store = FAISS.load_local(
        str(out_dir), get_embeddings(), allow_dangerous_deserialization=True
    )
    return _store


def search(query: str, k: int | None = None, source: str | None = None) -> list[dict[str, Any]]:
    """질문과 유사한 청크를 거리 오름차순으로 반환한다. source 메타필터 지원.

    거리가 RAG_MAX_DISTANCE를 초과하는(무관한) 결과는 제외한다(방어).
    """
    settings = get_settings()
    k = k or settings.RAG_TOP_K
    store = get_store()
    filter_arg = {"source": source} if source else None
    pairs = store.similarity_search_with_score(query, k=k, filter=filter_arg)
    return [
        {
            "text": doc.page_content,
            "source": doc.metadata.get("source", ""),
            "page": doc.metadata.get("page"),  # PDF는 0-based, TXT는 None
            "distance": float(score),  # 거리: 작을수록 유사
        }
        for doc, score in pairs
        if float(score) <= settings.RAG_MAX_DISTANCE
    ]


def add_documents(texts: list[str], sources: list[str]) -> dict:
    """인덱스에 문서를 증분 추가하고 저장한다 (PDF4 증분 업데이트).

    build_index와 동일하게 청킹 후 추가한다(긴 문서 검색 품질 유지).
    """
    if len(texts) != len(sources):
        raise InfraError("texts와 sources 길이가 다릅니다.")
    from langchain_core.documents import Document
    from langchain_text_splitters import RecursiveCharacterTextSplitter

    settings = get_settings()
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=settings.CHUNK_SIZE, chunk_overlap=settings.CHUNK_OVERLAP
    )
    raw = [Document(page_content=t, metadata={"source": s}) for t, s in zip(texts, sources)]
    chunks = splitter.split_documents(raw)

    store = get_store()
    store.add_documents(chunks)
    store.save_local(str(settings.VECTOR_DIR))
    return {"added": len(chunks)}
