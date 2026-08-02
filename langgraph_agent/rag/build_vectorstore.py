"""
rag/build_vectorstore.py

역할:
    rag/chunking.py로 청킹한 약관 조문들을 임베딩해서 Chroma 벡터DB로 저장한다.
    최초 1회 또는 약관 원문이 추가/수정될 때마다 실행.

실행:
    python -m rag.build_vectorstore

주의:
    sentence-transformers(torch 포함)가 필요해서 용량이 크다.
    로컬 개발환경이 아니라 RunPod처럼 디스크 여유 있는 곳에서 실행 권장.
"""

from pathlib import Path
from langchain_community.vectorstores import Chroma
from langchain_huggingface import HuggingFaceEmbeddings

from rag.chunking import chunk_all_policy_docs
from config import POLICY_DOCS_DIR, VECTORSTORE_DIR, EMBEDDING_MODEL_NAME


def build_vectorstore():
    documents = chunk_all_policy_docs(Path(POLICY_DOCS_DIR))
    print(f"총 {len(documents)}개 청크, 임베딩 시작...")

    embeddings = HuggingFaceEmbeddings(
        model_name=EMBEDDING_MODEL_NAME,
        encode_kwargs={"normalize_embeddings": True},
    )

    vectorstore = Chroma.from_documents(
        documents=documents,
        embedding=embeddings,
        persist_directory=VECTORSTORE_DIR,
    )

    print(f"벡터DB 저장 완료: {VECTORSTORE_DIR}")
    return vectorstore


if __name__ == "__main__":
    build_vectorstore()
