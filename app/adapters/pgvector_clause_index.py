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

import re
from dataclasses import dataclass
from typing import Callable

from app.core.errors import InfraError

#: 임베딩 차원. 모델은 레지스트리(`app/rag/embeddings.py`)가 정한다.
_EMBED_DIM = 768

#: ★쪼개는 단위를 **글자에서 토큰으로** 바꿨다.
#:
#:   처음엔 800자 고정으로 잘랐다. 두 가지가 틀렸다.
#:
#:   1. **모델 한계를 넘었다.** `ko-sroberta` 의 최대 입력은 **512토큰**인데
#:      800자 조각의 **1.4%가 512토큰을 넘어**(표본 1,500개 실측: 중앙값 363 ·
#:      90분위 446 · 최대 641) 뒷부분이 **조용히 잘린 채** 임베딩됐다.
#:      전량이면 약 1,800조각이다. 겹침이 120자뿐이라 잘린 구간이
#:      다음 조각에도 안 들어가 **아예 색인되지 않는 본문**이 생긴다.
#:   2. **문장 한가운데를 잘랐다.** 법률문은 부정어와 예외조건이 문장 끝에 온다 —
#:      "…보상합니다. 다만 … 경우에는 보상하지 않습니다" 에서 뒤를 자르면
#:      뜻이 **반대로** 남는다.
#:
#:   그래서 문단·문장 경계로 묶고 토큰 수로 센다.
#:   (코덱스 교차검증 2026-08-02)
MAX_TOKENS = 448
OVERLAP_TOKENS = 80

#: 조항 길이(고유 내용 52,899개 실측): 중앙값 **613자** · 90분위 2,905 ·
#: 99분위 14,200 · 최대 29,977. 800자 초과 21,311개.
#: ★앞서 주석에 적어 둔 "중앙값 356자"는 **등장 기준**이었다.
#:   임베딩 대상은 고유 조항이므로 분모가 다르다 — 숫자를 인용할 때 분모를 적는다.

#: 문단 → 문장 순으로 끊는다. 여기서도 안 끊기면 토큰 창으로 자른다.
_PARA = re.compile(r"\n+")
#: ★뒤돌아보기는 **길이가 고정**이어야 한다. `다\.` 같은 두 글자 패턴을 넣었다가
#:   `look-behind requires fixed-width pattern` 으로 임포트가 죽었다.
#:   한국어 종결은 어차피 마침표로 끝나므로 한 글자 종결부호만 본다.
_SENT = re.compile(r"(?<=[.。」』\)])\s+")


def _segments(text: str) -> list[str]:
    """문단 → 문장 순으로 끊는다. 조각의 **자연스러운 경계**를 만든다."""
    out: list[str] = []
    for para in _PARA.split(text):
        para = para.strip()
        if not para:
            continue
        parts = [s for s in _SENT.split(para) if s.strip()]
        out.extend(parts or [para])
    return out or ([text] if text.strip() else [])


def chunk_clause(text: str, count_tokens: Callable[[str], int]) -> list[str]:
    """조항 하나를 **토큰 예산 안에서** 조각낸다.

    ★한 조각도 `MAX_TOKENS` 를 넘지 않는다. 넘으면 모델이 조용히 잘라 버린다.
    ★문장 경계로 묶는다. 법률문은 예외가 문장 끝에 오므로
      한가운데를 자르면 뜻이 반대로 남는다.
    ★그래도 한 문장이 예산을 넘으면 **그 문장만** 토큰 창으로 자른다.
      이때도 잘렸다는 사실이 감춰지지 않게 겹쳐 둔다.
    """
    if not text.strip():
        return []
    if count_tokens(text) <= MAX_TOKENS:
        return [text]

    #: 예산을 넘는 한 문장은 미리 쪼개 둔다. 이분 탐색으로 글자 경계를 찾는다.
    flat: list[str] = []
    for seg in _segments(text):
        if count_tokens(seg) <= MAX_TOKENS:
            flat.append(seg)
            continue
        i = 0
        while i < len(seg):
            lo, hi = 1, len(seg) - i
            while lo < hi:
                mid = (lo + hi + 1) // 2
                if count_tokens(seg[i : i + mid]) <= MAX_TOKENS:
                    lo = mid
                else:
                    hi = mid - 1
            flat.append(seg[i : i + lo])
            i += lo

    chunks: list[str] = []
    cur: list[str] = []
    cur_tokens = 0
    for seg in flat:
        n = count_tokens(seg)
        if cur and cur_tokens + n > MAX_TOKENS:
            chunks.append(" ".join(cur))
            #: ★뒤에서부터 `OVERLAP_TOKENS` 만큼을 다음 조각 앞에 남긴다.
            back: list[str] = []
            back_tokens = 0
            for s in reversed(cur):
                t = count_tokens(s)
                if back_tokens + t > OVERLAP_TOKENS:
                    break
                back.insert(0, s)
                back_tokens += t
            cur, cur_tokens = back, back_tokens
        cur.append(seg)
        cur_tokens += n
    if cur:
        chunks.append(" ".join(cur))
    return chunks


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
    #: ★★**부모 문서 회수(parent-document retrieval).**
    #:
    #:   검색은 **조각**으로 하고(정밀도), LLM 에는 **조 전체**를 준다(문맥).
    #:   법률문은 예외가 뒤에 온다 —
    #:     "…보상합니다. 다만 … 경우에는 보상하지 않습니다"
    #:   조각만 주면 앞 절만 남아 **뜻이 반대가 된다.**
    #:
    #:   실측 근거 둘:
    #:     · KCD 코드 스캔이 조각 밖 코드를 **못 본다**(`precheck.scan_clause`)
    #:     · 인용 검증이 조 안의 문장을 "근거에 없다"고 **버린다**(`citation_guard`)
    #:
    #:   본문 한 벌은 `policy_clause_content` 에 이미 있다. 조인 한 번이면 된다 —
    #:   **데이터를 다 갖춰 두고 안 쓰고 있었다.**
    full_text: str = ""

    @property
    def citable_text(self) -> str:
        """인용·판정에 쓸 본문. **조 전체**를 준다.

        ★`full_text` 가 비면 조각으로 떨어진다. 조용히 그러지 않도록
          비는 경우는 `policy_clause_content` 에 본문이 없을 때뿐이고,
          그건 적재가 반쪽이라는 뜻이라 `drop_incomplete` 가 지운다.
        """
        return self.full_text or self.text

    @property
    def clause_id(self) -> str:
        tail = f"#{self.content_hash[:8]}" if self.content_hash else ""
        return f"{self.sha256[:12]}/{self.qualified_no}{tail}"


#: ★★현재 세대. **조항 JSON 스키마 버전과 맞춘다.**
#:
#:   검색은 이 세대의 발생행만 본다. 옛 세대는 지우지 않고 남겨 두되
#:   **사용자 경로에는 안 보인다.** 지우면 6시간짜리 임베딩을 버리고,
#:   그냥 두면 오염된 옛 근거가 계속 올라온다 — 가르는 것이 답이다.
CURRENT_GENERATION = "s6"

#: ★★**어느 모델로 만든 벡터인가.** 모델이 바뀌면 벡터 공간이 통째로 다르다 —
#:   섞이면 거리 비교가 무의미해지고, 그런데도 **아무 오류도 안 난다.**
#:
#:   실측 사고(2026-08-03): 지금 설정된 모델은 `max_seq_length = 128` 이다.
#:   우리 조각은 448토큰 예산이라 **표본 6,000조각 중 89.1%가 잘렸고
#:   전체 토큰의 59.8%가 버려졌다.** 면책은 문장 끝에 오므로
#:   ("…보상합니다. 다만 … 보상하지 않습니다") 우리가 절대 놓치면 안 되는
#:   부분이 구조적으로 사라진다.
#:
#:   ★모델을 아직 **고르지 않았다.**
#:     `docs/reports/2026-08-02_1800_임베딩모델_후보_20선_코덱스합의.md` 결론:
#:     "200~500개 실손보험 질의로 재보기 전에는 아무것도 확정하지 않는다."
#:
#:   ★모델 ID 를 **여기 적지 않는다.** 레지스트리(설정)가 정한다 —
#:     하드코딩하면 설정을 바꿔도 태그가 안 따라와 벡터 공간이 조용히 섞인다.
#:     (`tests/test_model_registry.py::test_llm_reg_002` 가 이걸 막는다)
LEGACY_EMBED_MODEL = "legacy-truncated-128"


def current_embed_model() -> str:
    """지금 설정된 임베딩 모델 이름. 벡터 행에 그대로 박는다."""
    from app.core.config import get_settings

    return get_settings().ST_EMBEDDING_MODEL


def ensure_schema(conn) -> None:
    """테이블·인덱스 생성(멱등)."""
    with conn.cursor() as cur:
        cur.execute("CREATE EXTENSION IF NOT EXISTS vector")
        cur.execute(
            f"""
            CREATE TABLE IF NOT EXISTS policy_clause_chunk (
                content_hash text    NOT NULL,
                chunk_ix     integer NOT NULL,
                --: ★이 조항이 **몇 조각으로 나뉘었는지**. 재개 판정에 쓴다.
                n_chunks     integer NOT NULL DEFAULT 0,
                text         text    NOT NULL,
                embedding    vector({_EMBED_DIM}) NOT NULL,
                PRIMARY KEY (content_hash, chunk_ix)
            )
            """
        )
        #: ★본문을 **한 벌** 둔다(코덱스 제안: content / chunk / occurrence 3계층).
        #:   조각을 이어 붙여 본문을 복원하려 했는데, 겹침이 토큰 기준이라
        #:   **글자 수로 자를 수 없다.** 복원을 추측으로 하느니 원본을 둔다.
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS policy_clause_content (
                content_hash text    PRIMARY KEY,
                text         text    NOT NULL,
                n_chunks     integer NOT NULL
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
        #: 앞서 만든 테이블에는 이 열이 없다. 붙인다(멱등).
        cur.execute(
            "ALTER TABLE policy_clause_chunk "
            "ADD COLUMN IF NOT EXISTS n_chunks integer NOT NULL DEFAULT 0"
        )
        #: ★★**세대(generation)를 행에 박는다.**
        #:
        #:   조항 스키마가 오르면 `content_hash` 가 바뀐다(s6 에서 부록을 본문에서 뺐다).
        #:   구·신 해시가 한 테이블에 같이 남으면 **오염된 옛 근거가 계속 검색된다**(코덱스).
        #:   그렇다고 지우면 6시간짜리 임베딩을 버린다.
        #:   그래서 **지우지 않고 갈라 놓는다** — 검색은 현재 세대만 본다.
        #:
        #:   ★기존 행의 기본값을 `s5-mixed` 로 둔다. `s5` 라고 하지 않는다 —
        #:     실제로 s5 적재 중간에 s6 발생행이 섞여 들어간 적이 있어
        #:     그 안이 순수한 s5 라고 **말할 수 없다.** 모르면 모른다고 적는다(§0).
        cur.execute(
            "ALTER TABLE policy_clause_occurrence "
            "ADD COLUMN IF NOT EXISTS index_generation text NOT NULL DEFAULT 's5-mixed'"
        )
        #: ★조항인가 부록인가. 판정이 인용 문구를 다르게 써야 한다 —
        #:   부록을 `제27조(준용규정)` 이라 부르면 출처가 틀린다.
        cur.execute(
            "ALTER TABLE policy_clause_occurrence "
            "ADD COLUMN IF NOT EXISTS source_kind text NOT NULL DEFAULT 'clause'"
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS policy_clause_occurrence_gen "
            "ON policy_clause_occurrence (index_generation)"
        )
        #: ★벡터를 만든 모델. 세대와 **같은 이유**로 행에 박는다 —
        #:   모델이 다르면 벡터 공간이 다르고, 섞여도 오류가 안 난다.
        #:   기존 행은 128토큰에서 잘린 벡터다. 그 사실을 이름에 적어 둔다.
        cur.execute(
            "ALTER TABLE policy_clause_chunk ADD COLUMN IF NOT EXISTS "
            f"embed_model text NOT NULL DEFAULT '{LEGACY_EMBED_MODEL}'"
        )
        #: ★PK 에 넣는다. 안 넣으면 `ON CONFLICT DO NOTHING` 때문에
        #:   새 모델 벡터가 **버려지고** 옛 벡터가 자리를 지킨다(발생행에서 겪은 그 함정).
        cur.execute(
            """
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.key_column_usage
                    WHERE table_name = 'policy_clause_chunk'
                      AND constraint_name = 'policy_clause_chunk_pkey'
                      AND column_name = 'embed_model'
                ) THEN
                    ALTER TABLE policy_clause_chunk
                        DROP CONSTRAINT IF EXISTS policy_clause_chunk_pkey;
                    ALTER TABLE policy_clause_chunk
                        ADD PRIMARY KEY (content_hash, chunk_ix, embed_model);
                END IF;
            END $$;
            """
        )
        #: ★★**세대를 기본키에 넣는다.** 이걸 빠뜨리면 조용히 새는 곳이 생긴다 —
        #:   `upsert_occurrences` 는 `ON CONFLICT DO NOTHING` 이라,
        #:   `(hash, sha, no, page)` 가 같은 옛 세대 행이 이미 있으면
        #:   **새 세대 행이 버려지고** 그 자리는 계속 `s5-mixed` 로 남는다.
        #:   검색은 현재 세대만 보므로 그 조항은 **영원히 안 나온다.**
        #:   적재 로그에는 "이미 있음"으로 찍혀 정상처럼 보인다. 최악의 실패다.
        cur.execute(
            """
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.key_column_usage
                    WHERE table_name = 'policy_clause_occurrence'
                      AND constraint_name = 'policy_clause_occurrence_pkey'
                      AND column_name = 'index_generation'
                ) THEN
                    ALTER TABLE policy_clause_occurrence
                        DROP CONSTRAINT IF EXISTS policy_clause_occurrence_pkey;
                    ALTER TABLE policy_clause_occurrence
                        ADD PRIMARY KEY (content_hash, sha256, qualified_no,
                                         page_from, index_generation);
                END IF;
            END $$;
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


def existing_hashes(conn, *, model: str | None = None) -> set[str]:
    """**온전히** 들어간 내용만. 다시 계산하지 않는다(재개 가능하게).

    ★조각 하나만 들어가도 "완료"로 보던 버그가 있었다.
      배치 중간에 죽으면 그 조항의 나머지 조각이 **영구히 누락되고**,
      다음 실행은 이미 있다고 건너뛴다. 아무도 모른다.

      실측(2026-08-02, 중단 지점): 내용 12,507개 중 **2개**의 끝 조각이
      800자로 꽉 찬 채 완료로 표시돼 있었다 — 뒤가 더 있었다는 뜻이다.
      5시간짜리 작업을 여러 번 끊으면 쌓이고, **감지되지 않는다.**

    이제 `n_chunks` 를 기록하고 **개수가 맞는 것만** 완료로 본다.
    """
    model = model or current_embed_model()
    with conn.cursor() as cur:
        #: ★**모델별로** 센다. 모델을 바꾸면 옛 모델 벡터가 있어도
        #:   "이미 있음"이 되어선 안 된다 — 새 모델로는 아직 안 만든 것이다.
        cur.execute(
            "SELECT ct.content_hash FROM policy_clause_content ct "
            "JOIN policy_clause_chunk ck ON ck.content_hash = ct.content_hash "
            "WHERE ck.embed_model = %s "
            "GROUP BY ct.content_hash, ct.n_chunks "
            "HAVING count(*) = ct.n_chunks",
            (model,),
        )
        return {r[0] for r in cur.fetchall()}


def drop_incomplete(conn) -> int:
    """미완성으로 남은 조각을 지운다. **다시 넣기 위해서다.**

    ★남겨 두면 검색에 반쪽짜리 본문이 근거로 올라온다.

    ★**저장소 전체를 훑는 정리 작업이다.** 적재 스크립트 시작 지점에서만 부른다.
      테스트에서 부르면 남의 적재 결과까지 날린다 —
      실제로 테스트가 조각 43,064개를 지웠다(2026-08-02).
    """
    done = existing_hashes(conn)
    with conn.cursor() as cur:
        #: ★**현재 모델 안에서만** 반쪽을 찾는다. 모델 전체를 섞어 보면
        #:   옛 모델 벡터를 "미완성"으로 오인해 통째로 지운다.
        cur.execute("SELECT DISTINCT content_hash FROM policy_clause_chunk "
                    "WHERE embed_model = %s", (current_embed_model(),))
        have = {r[0] for r in cur.fetchall()}
        bad = sorted(have - done)
        if bad:
            cur.execute("DELETE FROM policy_clause_chunk "
                        "WHERE content_hash = ANY(%s) AND embed_model = %s",
                        (bad, current_embed_model()))
        n = len(bad)
        #: 본문만 있고 조각이 없는 것도 지운다(반대 방향의 반쪽).
        cur.execute(
            "DELETE FROM policy_clause_content ct WHERE NOT EXISTS ("
            "  SELECT 1 FROM policy_clause_chunk ck WHERE ck.content_hash = ct.content_hash)"
        )
    conn.commit()
    return n


def upsert_content(conn, rows) -> int:
    """`(content_hash, text, n_chunks)` — 조항 본문 한 벌."""
    n = 0
    with conn.cursor() as cur:
        for content_hash, text, n_chunks in rows:
            cur.execute(
                "INSERT INTO policy_clause_content (content_hash, text, n_chunks) "
                "VALUES (%s, %s, %s) ON CONFLICT (content_hash) DO UPDATE "
                "SET text = EXCLUDED.text, n_chunks = EXCLUDED.n_chunks",
                (content_hash, text, n_chunks),
            )
            n += cur.rowcount
    return n


def upsert_chunks(conn, rows, *, model: str | None = None) -> int:
    """`(content_hash, chunk_ix, n_chunks, text, embedding)` 을 넣는다.

    ★한 조항의 조각은 **전부 한 트랜잭션**에 들어와야 한다.
      호출자가 조항 단위로 묶어서 넘긴다 — 중간에 죽어도 반쪽이 남지 않는다.
    """
    model = model or current_embed_model()
    n = 0
    with conn.cursor() as cur:
        for content_hash, chunk_ix, n_chunks, text, vec in rows:
            cur.execute(
                "INSERT INTO policy_clause_chunk "
                "(content_hash, chunk_ix, n_chunks, text, embedding, embed_model) "
                "VALUES (%s, %s, %s, %s, %s, %s) ON CONFLICT DO NOTHING",
                (content_hash, chunk_ix, n_chunks, text, vec, model),
            )
            n += cur.rowcount
    conn.commit()
    return n


def upsert_occurrences(conn, rows, *, generation: str = CURRENT_GENERATION) -> int:
    """조항이 **어느 문서 어디에** 실렸는지. 같은 자리는 한 번만.

    ★`rows` 는 `(hash, sha, insurer, qualified_no, section, title, page_from, page_to)`
      또는 뒤에 `source_kind` 를 하나 더 붙인 9튜플.
    """
    n = 0
    with conn.cursor() as cur:
        for r in rows:
            kind = r[8] if len(r) > 8 else "clause"
            cur.execute(
                "INSERT INTO policy_clause_occurrence "
                "(content_hash, sha256, insurer, qualified_no, section, title, "
                " page_from, page_to, index_generation, source_kind) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                (*r[:8], generation, kind),
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
    #: ★조각을 **먼저** 고르고, 그다음에 발생을 붙인다.
    #:
    #:   앞서는 발생을 조인한 뒤 `LIMIT` 을 걸었다. 한 조항이 최대 **170개 문서**에
    #:   실리므로 **같은 조항 하나가 결과를 다 채운다** — `LIMIT 8` 이 서로 다른
    #:   조항 8개가 아니라 같은 조항의 발생 8개가 된다. (코덱스 지적 2026-08-02)
    #:
    #:   그래서 조각을 유사도 순으로 먼저 뽑고(약관 필터는 `EXISTS` 로 걸어
    #:   범위 밖 조항이 자리를 차지하지 못하게 한다), 내용마다 대표 발생 하나를 붙인다.
    filt = (
        "AND EXISTS (SELECT 1 FROM policy_clause_occurrence o2 "
        "WHERE o2.content_hash = c.content_hash AND o2.sha256 = ANY(%(shas)s) "
        "AND o2.index_generation = %(gen)s)"
        if sha256s is not None
        #: ★약관을 안 가둬도 **세대는 가둔다.** 옛 세대 조각이 올라오면
        #:   부록을 삼킨 조항이 근거로 붙는다.
        else "AND EXISTS (SELECT 1 FROM policy_clause_occurrence o2 "
             "WHERE o2.content_hash = c.content_hash AND o2.index_generation = %(gen)s)"
    )
    sql = f"""
        WITH best AS (
            SELECT DISTINCT ON (c.content_hash)
                   c.content_hash, c.chunk_ix, c.text,
                   c.embedding <-> %(q)s AS distance
            FROM policy_clause_chunk c
            --: ★현재 모델의 벡터만 본다. 벡터 공간이 다르면 거리가 뜻을 잃는다.
            WHERE c.embed_model = %(model)s {filt}
            ORDER BY c.content_hash, distance
        )
        SELECT b.content_hash, b.chunk_ix, b.text, b.distance,
               o.sha256, o.insurer, o.qualified_no, o.section, o.title,
               o.page_from, o.page_to,
               --: ★부모 문서 회수. 조각으로 찾고 **조 전체**를 돌려준다.
               --:   `LEFT JOIN` 이다 — 본문이 없어도 결과를 **버리지 않는다.**
               --:   그 경우 `citable_text` 가 조각으로 떨어지고, 그건
               --:   적재가 반쪽이라는 신호다(`drop_incomplete` 가 처리).
               COALESCE(ct.text, '') AS full_text
        FROM best b
        LEFT JOIN policy_clause_content ct ON ct.content_hash = b.content_hash
        JOIN LATERAL (
            SELECT * FROM policy_clause_occurrence o
            WHERE o.content_hash = b.content_hash
              AND o.index_generation = %(gen)s
              {"AND o.sha256 = ANY(%(shas)s)" if sha256s is not None else ""}
            ORDER BY o.sha256, o.page_from
            LIMIT 1
        ) o ON TRUE
        ORDER BY b.distance
        LIMIT %(k)s
    """
    #: ★파이썬 리스트를 그냥 넘기면 `double precision[]` 로 가서
    #:   `operator does not exist: vector <-> double precision[]` 로 죽는다.
    #:   `register_vector()` 가 알아보는 것은 **numpy 배열**이다.
    import numpy as np

    q = np.asarray(query_vec, dtype=np.float32)
    params = {"q": q, "k": limit, "shas": sha256s,
              "gen": CURRENT_GENERATION, "model": current_embed_model()}
    with conn.cursor() as cur:
        cur.execute(sql, params)
        return [ClauseHit(*row) for row in cur.fetchall()]


def stats(conn) -> dict:
    """적재 현황. **응답·리포트에 그대로 싣는다.**"""
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT count(*), count(DISTINCT content_hash) FROM policy_clause_chunk")
            chunks, contents = cur.fetchone()
            cur.execute("SELECT embed_model, count(*), count(DISTINCT content_hash) "
                        "FROM policy_clause_chunk GROUP BY 1 ORDER BY 1")
            by_model = {m: {"chunks": c, "contents": d} for m, c, d in cur.fetchall()}
            cur.execute("SELECT count(*) FROM policy_clause_content")
            (bodies,) = cur.fetchone()
            cur.execute(
                "SELECT count(*), count(DISTINCT sha256) FROM policy_clause_occurrence"
            )
            occ, docs = cur.fetchone()
            #: ★세대·종류별로 **쪼개서** 보여준다. 합계만 보면 옛 세대가 섞인 걸 못 본다.
            cur.execute(
                "SELECT index_generation, source_kind, count(*), count(DISTINCT sha256) "
                "FROM policy_clause_occurrence GROUP BY 1,2 ORDER BY 1,2"
            )
            by_gen = {f"{g}/{k}": {"occurrences": n, "documents": d}
                      for g, k, n, d in cur.fetchall()}
    except Exception as exc:  # noqa: BLE001
        raise InfraError(f"인덱스 A 현황을 읽지 못했습니다: {exc}") from exc
    return {
        "chunks": chunks,
        "distinct_contents": contents,
        "bodies": bodies,
        "occurrences": occ,
        "documents": docs,
        #: ★검색이 실제로 보는 세대. 합계와 나란히 놓아야 오염이 눈에 띈다.
        "current_generation": CURRENT_GENERATION,
        "current_embed_model": current_embed_model(),
        "by_embed_model": by_model,
        "by_generation": by_gen,
    }


__all__ = [
    "ClauseHit",
    "CHUNK_SIZE",
    "CHUNK_OVERLAP",
    "ensure_schema",
    "chunk_clause",
    "drop_incomplete",
    "existing_hashes",
    "search",
    "stats",
    "upsert_chunks",
    "upsert_content",
    "upsert_occurrences",
]
