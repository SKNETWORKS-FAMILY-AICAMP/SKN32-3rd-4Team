"""인덱싱 (사전 1회) — PDF4 핵심: 인덱싱과 서비스 분리.

data/docs/*.txt → 청킹 → FAISS 인덱스 → save_local. 요청마다 재인덱싱하는
안티패턴을 피하기 위해 서비스(service.py)와 분리한다.
"""

from __future__ import annotations

from pathlib import Path

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.core.config import get_settings
from app.core.errors import InfraError
from app.rag.embeddings import get_embeddings


def _load_docs(docs_dir: Path) -> list[Document]:
    """docs 폴더의 TXT + PDF를 Document 목록으로 로드한다.

    - TXT: 전체를 하나의 Document(page 메타데이터 없음)
    - PDF: PyPDFLoader로 페이지별 Document(page 메타데이터 유지). 파싱 실패는
      TXT로 조용히 대체하지 않고 파일명을 포함한 InfraError로 명시 실패한다.
    """
    if not docs_dir.exists():
        raise InfraError(f"문서 폴더가 없습니다: {docs_dir}")
    docs: list[Document] = []

    for path in sorted(docs_dir.glob("*.txt")):
        text = path.read_text(encoding="utf-8").strip()
        if text:
            docs.append(Document(page_content=text, metadata={"source": path.name}))

    for path in sorted(docs_dir.glob("*.pdf")):
        try:
            from langchain_community.document_loaders import PyPDFLoader

            pages = PyPDFLoader(str(path)).load()
        except Exception as exc:  # noqa: BLE001 - 파싱 실패를 숨기지 않고 전파
            raise InfraError(f"PDF 로딩 실패: {path.name} ({exc})") from exc
        for page in pages:
            content = (page.page_content or "").strip()
            if not content:
                continue
            # source는 파일명으로 통일, page 메타데이터(0-based)는 보존
            metadata = {"source": path.name}
            if isinstance(page.metadata.get("page"), int):
                metadata["page"] = page.metadata["page"]
            docs.append(Document(page_content=content, metadata=metadata))

    if not docs:
        raise InfraError(f"인덱싱할 문서(txt/pdf)가 없습니다: {docs_dir}")
    return docs


# 하위호환 별칭 (기존 호출부 보존)
_load_txt_docs = _load_docs


def _docs_fingerprint(docs_dir: Path) -> str:
    """docs 폴더의 txt/pdf 목록·크기로 지문을 만든다(문서 추가/변경 감지용)."""
    if not docs_dir.exists():
        return ""
    parts = [
        f"{p.name}:{p.stat().st_size}"
        for p in sorted(docs_dir.glob("*.txt")) + sorted(docs_dir.glob("*.pdf"))
    ]
    return "|".join(parts)


def build_index(docs_dir: Path | None = None, out_dir: Path | None = None) -> dict:
    """txt/pdf 문서를 청킹·임베딩해 FAISS 인덱스를 out_dir에 저장한다."""
    from langchain_community.vectorstores import FAISS

    settings = get_settings()
    docs_dir = docs_dir or settings.DOCS_DIR
    out_dir = out_dir or settings.VECTOR_DIR

    docs = _load_txt_docs(docs_dir)
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=settings.CHUNK_SIZE, chunk_overlap=settings.CHUNK_OVERLAP
    )
    chunks = splitter.split_documents(docs)

    store = FAISS.from_documents(chunks, get_embeddings())
    out_dir.mkdir(parents=True, exist_ok=True)
    store.save_local(str(out_dir))
    # 임베딩 모델명 + 문서 지문 기록(모델 변경 또는 문서 추가/변경 시 재빌드 판단용)
    (out_dir / ".embedding_model").write_text(settings.ST_EMBEDDING_MODEL, encoding="utf-8")
    (out_dir / ".docs_manifest").write_text(_docs_fingerprint(docs_dir), encoding="utf-8")
    return {"docs": len(docs), "chunks": len(chunks), "out_dir": str(out_dir)}


def index_is_current(out_dir: Path | None = None, docs_dir: Path | None = None) -> bool:
    """인덱스가 현재 임베딩 모델·문서 목록과 일치하고 완전한지 확인한다."""
    settings = get_settings()
    out_dir = out_dir or settings.VECTOR_DIR
    docs_dir = docs_dir or settings.DOCS_DIR
    if not ((out_dir / "index.faiss").exists() and (out_dir / "index.pkl").exists()):
        return False
    model_marker = out_dir / ".embedding_model"
    if not (model_marker.exists() and model_marker.read_text(encoding="utf-8").strip() == settings.ST_EMBEDDING_MODEL):
        return False
    docs_marker = out_dir / ".docs_manifest"
    if not docs_marker.exists():
        return False  # 지문 없으면 stale 취급(재빌드)
    return docs_marker.read_text(encoding="utf-8") == _docs_fingerprint(docs_dir)


if __name__ == "__main__":
    print(build_index())
