"""pgvector 스키마·적재 (Phase 3 학습 트랙).

FAISS와 **동일한 청킹·임베딩**(공정 비교)으로 corpus를 pgvector에 적재한다. 임베딩
모델은 app.rag.embeddings(레지스트리 기반)에서 받는다 — 여기서 모델ID를 명명하지 않음.
차원은 768(정규화). 연결/DB 실패는 삼키지 않고 전파(무폴백).

접속 정보는 config.PGVECTOR_DSN(모델ID 아님). userspace PG 기동은 scripts/pg.py 참조.
"""

from __future__ import annotations

from pathlib import Path

from app.core.config import get_settings

_EMBED_DIM = 768  # 임베딩 차원(모델은 레지스트리 기반 embeddings에서 결정)


def get_conn(dsn: str | None = None):
    """psycopg 연결 + pgvector 타입 등록. 연결 실패는 InfraError로 전파."""
    import psycopg
    from pgvector.psycopg import register_vector

    from app.core.errors import InfraError

    dsn = dsn or get_settings().PGVECTOR_DSN
    try:
        conn = psycopg.connect(dsn)
    except psycopg.OperationalError as exc:
        raise InfraError(
            f"pgvector(PostgreSQL)에 연결할 수 없습니다: {dsn}. 먼저 PG를 기동하세요(scripts/pg.py)."
        ) from exc
    register_vector(conn)
    return conn


def ensure_schema(conn) -> None:
    """확장·테이블·인덱스를 생성한다(멱등). HNSW 인덱스로 근사 최근접 검색 학습."""
    with conn.cursor() as cur:
        cur.execute("CREATE EXTENSION IF NOT EXISTS vector")
        cur.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")  # Phase 4: 키워드(trigram) 검색
        cur.execute(
            f"""
            CREATE TABLE IF NOT EXISTS rag_chunks (
                id       bigserial PRIMARY KEY,
                source   text NOT NULL,
                page     integer,
                content  text NOT NULL,
                embedding vector({_EMBED_DIM}) NOT NULL
            )
            """
        )
        # HNSW(L2) 인덱스 — pgvector 근사검색. 소규모라도 학습·정합 목적.
        cur.execute(
            "CREATE INDEX IF NOT EXISTS rag_chunks_embedding_hnsw "
            "ON rag_chunks USING hnsw (embedding vector_l2_ops)"
        )
        # GIN trigram 인덱스 — pg_trgm 키워드 검색(word_similarity) 가속.
        cur.execute(
            "CREATE INDEX IF NOT EXISTS rag_chunks_content_trgm "
            "ON rag_chunks USING gin (content gin_trgm_ops)"
        )
    conn.commit()


def ingest_corpus(conn, docs_dir: Path | None = None) -> dict:
    """FAISS와 동일한 로딩·청킹·임베딩으로 corpus를 rag_chunks에 재적재한다(TRUNCATE 후 삽입)."""
    from langchain_text_splitters import RecursiveCharacterTextSplitter

    from app.rag.build_index import _load_docs
    from app.rag.embeddings import get_embeddings

    settings = get_settings()
    docs_dir = docs_dir or settings.DOCS_DIR
    docs = _load_docs(docs_dir)
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=settings.CHUNK_SIZE, chunk_overlap=settings.CHUNK_OVERLAP
    )
    chunks = splitter.split_documents(docs)
    embeddings = get_embeddings().embed_documents([c.page_content for c in chunks])

    with conn.cursor() as cur:
        cur.execute("TRUNCATE rag_chunks RESTART IDENTITY")
        for chunk, vec in zip(chunks, embeddings):
            cur.execute(
                "INSERT INTO rag_chunks (source, page, content, embedding) VALUES (%s, %s, %s, %s)",
                (
                    chunk.metadata.get("source", ""),
                    chunk.metadata.get("page"),
                    chunk.page_content,
                    vec,
                ),
            )
    conn.commit()
    return {"chunks": len(chunks)}
