"""인덱스 A — 약관 조항 벡터 색인 (pgvector).

★인덱스 B(외부 청구결과)와 **테이블이 다르다.** 필터로 나누지 않는다.

    나누는 기준은 "데이터가 다른가"가 아니라 **"판정 근거로 인용할 수 있는가"** 다.
    한 테이블에 두고 `WHERE` 로 거르면 두 가지가 무너진다 —

      1. 인용이 섞인다. "제9조에 따르면"과 "어떤 사용자 보고에 따르면"이 한 답에 들어간다.
      2. 순위가 오염된다. 사례 보고는 **구어체라 질문과 문장이 비슷하고**
         약관 조항은 법률체 문어다. 사후 필터로 사례를 빼도
         **필요한 조항이 이미 top-k 밖으로 밀린 뒤**라 되살릴 수 없다.

    이 테이블에는 약관 조항만 들어간다. 외부 보고는 여기 넣지 않는다.

★정체성과 발생을 나눈다 (CLAUDE.md §1)

    실측(s5 전량 1,367문서): 조항 등장 **211,131** / 고유 내용 **73,031** — 중복 **65.4%**.
    본문을 등장마다 넣으면 임베딩을 3배 계산하고 3배 저장한다.

        policy_clause_chunk       내용 한 벌 (`content_hash` 로 식별) + 임베딩
        policy_clause_occurrence  그 내용이 **어느 문서 어디에** 실렸는가

    검색은 내용에서 하고, 근거를 댈 때 발생으로 되돌린다.

★적재 대상은 **`parse_status == "ok"` 문서의 조항**이다

    추출이 의심스러운 문서(`suspect` 250 · `no_clause_heads` 9)의 조항은
    판정 근거가 될 수 없다. 넣어 두면 언젠가 필터를 빠뜨린다.
    고유 조항 73,031 중 **52,899** 가 대상이다.

★검색 필터는 **명시 인자로 받는다**

    기본값을 느슨하게 두면 용어 경로(전역)의 완화된 필터가 판정 경로로 샌다.
    판정은 약관 버전 하나로 가둬야 한다 — 2019년 가입자에게 2024년 조항이 붙으면 안 된다.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.core.errors import InfraError

#: 임베딩 차원. 모델은 레지스트리(`app/rag/embeddings.py`)가 정한다.
_EMBED_DIM = 768

#: 조항 하나를 쪼개는 크기. 조항 길이 중앙값 356자 · 90분위 1,742자 · 최대 147,390자.
#: 긴 조항(1,000자 초과 41,608개)을 통째로 넣으면 임베딩이 뭉개진다.
CHUNK_SIZE = 800
CHUNK_OVERLAP = 120


@dataclass(frozen=True)
class ClauseHit:
    """검색 결과 한 건. **어느 문서 어디인지**가 항상 붙는다."""

    content_hash: str
    chunk_ix: int
    text: str
    distance: float
    sha256: str
    insurer: str
    qualified_no: str
    section: str
    title: str
    page_from: int
    page_to: int

    @property
    def clause_id(self) -> str:
        tail = f"#{self.content_hash[:8]}" if self.content_hash else ""
        return f"{self.sha256[:12]}/{self.qualified_no}{tail}"


def ensure_schema(conn) -> None:
    """테이블·인덱스 생성(멱등)."""
    with conn.cursor() as cur:
        cur.execute("CREATE EXTENSION IF NOT EXISTS vector")
        cur.execute(
            f"""
            CREATE TABLE IF NOT EXISTS policy_clause_chunk (
                content_hash text    NOT NULL,
                chunk_ix     integer NOT NULL,
                text         text    NOT NULL,
                embedding    vector({_EMBED_DIM}) NOT NULL,
                PRIMARY KEY (content_hash, chunk_ix)
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS policy_clause_occurrence (
                content_hash text    NOT NULL,
                sha256       text    NOT NULL,
                insurer      text    NOT NULL DEFAULT '',
                qualified_no text    NOT NULL DEFAULT '',
                section      text    NOT NULL DEFAULT '',
                title        text    NOT NULL DEFAULT '',
                page_from    integer NOT NULL DEFAULT 0,
                page_to      integer NOT NULL DEFAULT 0,
                PRIMARY KEY (content_hash, sha256, qualified_no, page_from)
            )
            """
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS policy_clause_chunk_hnsw "
            "ON policy_clause_chunk USING hnsw (embedding vector_l2_ops)"
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS policy_clause_occurrence_sha "
            "ON policy_clause_occurrence (sha256)"
        )
    conn.commit()


def existing_hashes(conn) -> set[str]:
    """이미 임베딩된 내용. **다시 계산하지 않는다**(재개 가능하게)."""
    with conn.cursor() as cur:
        cur.execute("SELECT DISTINCT content_hash FROM policy_clause_chunk")
        return {r[0] for r in cur.fetchall()}


def upsert_chunks(conn, rows) -> int:
    """`(content_hash, chunk_ix, text, embedding)` 을 넣는다. 이미 있으면 건너뛴다."""
    n = 0
    with conn.cursor() as cur:
        for content_hash, chunk_ix, text, vec in rows:
            cur.execute(
                "INSERT INTO policy_clause_chunk (content_hash, chunk_ix, text, embedding) "
                "VALUES (%s, %s, %s, %s) ON CONFLICT DO NOTHING",
                (content_hash, chunk_ix, text, vec),
            )
            n += cur.rowcount
    conn.commit()
    return n


def upsert_occurrences(conn, rows) -> int:
    """조항이 **어느 문서 어디에** 실렸는지. 같은 자리는 한 번만."""
    n = 0
    with conn.cursor() as cur:
        for r in rows:
            cur.execute(
                "INSERT INTO policy_clause_occurrence "
                "(content_hash, sha256, insurer, qualified_no, section, title, page_from, page_to) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                r,
            )
            n += cur.rowcount
    conn.commit()
    return n


def search(
    conn,
    query_vec,
    *,
    sha256s: list[str] | None,
    limit: int = 8,
) -> list[ClauseHit]:
    """조항 검색.

    ★`sha256s` 는 **반드시 넘긴다.** `None` 은 "전역으로 찾겠다"는 **명시적 선택**이고,
      용어 설명 경로에서만 쓴다. 판정 경로는 약관 버전 목록을 넘겨 가둔다.
      기본값을 두지 않는 이유다 — 안 넘기면 호출이 실패해야 한다.
    """
    if sha256s is not None and not sha256s:
        #: 빈 목록은 "쓸 수 있는 약관이 없다"이다. 전역 검색으로 바꿔치지 않는다.
        return []
    where = "WHERE o.sha256 = ANY(%(shas)s)" if sha256s is not None else ""
    sql = f"""
        SELECT c.content_hash, c.chunk_ix, c.text,
               c.embedding <-> %(q)s AS distance,
               o.sha256, o.insurer, o.qualified_no, o.section, o.title,
               o.page_from, o.page_to
        FROM policy_clause_chunk c
        JOIN policy_clause_occurrence o ON o.content_hash = c.content_hash
        {where}
        ORDER BY distance
        LIMIT %(k)s
    """
    params = {"q": query_vec, "k": limit, "shas": sha256s}
    with conn.cursor() as cur:
        cur.execute(sql, params)
        return [ClauseHit(*row) for row in cur.fetchall()]


def stats(conn) -> dict:
    """적재 현황. **응답·리포트에 그대로 싣는다.**"""
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT count(*), count(DISTINCT content_hash) FROM policy_clause_chunk")
            chunks, contents = cur.fetchone()
            cur.execute(
                "SELECT count(*), count(DISTINCT sha256) FROM policy_clause_occurrence"
            )
            occ, docs = cur.fetchone()
    except Exception as exc:  # noqa: BLE001
        raise InfraError(f"인덱스 A 현황을 읽지 못했습니다: {exc}") from exc
    return {
        "chunks": chunks,
        "distinct_contents": contents,
        "occurrences": occ,
        "documents": docs,
    }


__all__ = [
    "ClauseHit",
    "CHUNK_SIZE",
    "CHUNK_OVERLAP",
    "ensure_schema",
    "existing_hashes",
    "search",
    "stats",
    "upsert_chunks",
    "upsert_occurrences",
]
