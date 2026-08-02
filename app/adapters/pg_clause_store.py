"""조항 조회 — **통합 저장소(PG)** 를 보는 어댑터. `ClauseSourcePort` 구현.

★통합 저장소를 **새로 만들지 않는다.** 인덱스 A 가 그것이다.

    조항 본문이 문서마다 중복 저장돼 있다(등장 211,131 / 고유 73,031 = 중복 65.4%).
    이걸 풀려고 파일 기반 통합 저장소를 하나 더 만들려 했는데, 그러면
    **같은 본문이 세 곳**(추출 산출물 · 파일 통합본 · PG)에 생긴다.
    어긋났을 때 무엇이 맞는지 판단할 근거가 없어진다
    (약관 보관형식 결정에서 표 CSV 를 폐기한 것과 같은 논리).

    그래서 층을 이렇게 나눈다.

        data/structured/…   **산출물**. 추출기가 만든 그대로. 불변. 재생성의 근거
        PG (인덱스 A)        **질의 계층**. 내용 한 벌 + 발생 여러 벌

    `file_clause_store` 는 산출물을 직접 읽고, 이 어댑터는 PG 를 읽는다.
    **둘은 같은 포트를 만족하므로 조립 지점에서 바꿔 끼운다.**

★검색은 **trigram**이다. 임베딩이 아니다.

    `ClauseSourcePort.search(sha256, query)` 는 낱말 질의를 받는다.
    여기서 임베딩을 계산하려면 요청마다 모델을 물어야 한다(최초 로드 수십 초).
    의미 검색이 필요하면 `pgvector_clause_index.search()` 를 벡터로 직접 부른다.
    **어느 쪽을 쓰는지 호출자가 알고 고르게 한다** — 조용히 바꿔치지 않는다.

★약관 버전으로 **가둔다.**

    `sha256` 을 반드시 받는다. 전역 검색을 하면 2019년 가입자에게
    2024년 조항이 근거로 붙는다.
"""

from __future__ import annotations

from typing import Sequence

from app.core.errors import InfraError
from app.core.ports.precheck import ClauseRow

#: trigram 유사도 하한. 낮추면 무관한 조항이 근거로 붙는다.
#:
#: ★`similarity()` 를 쓰면 안 된다 — 문자열 **전체**끼리 비교하므로
#:   10자 질의와 800자 조각은 아무리 잘 맞아도 값이 0.02 수준이다.
#:   실제로 "보상하지 않는 손해" 로 찾았더니 **0건**이 나왔다.
#:   `word_similarity(질의, 본문)` 은 질의가 본문의 **어느 부분과** 맞는지를 잰다.
_MIN_SIMILARITY = 0.45


def _conn():
    from app.adapters.pgvector_index import get_conn

    return get_conn()


def ensure_search_index(conn) -> None:
    """조항 본문 trigram 인덱스(멱등)."""
    with conn.cursor() as cur:
        cur.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
        cur.execute(
            "CREATE INDEX IF NOT EXISTS policy_clause_chunk_text_trgm "
            "ON policy_clause_chunk USING gin (text gin_trgm_ops)"
        )
    conn.commit()


def _rows_to_clauses(rows) -> list[ClauseRow]:
    out: list[ClauseRow] = []
    for content_hash, text, sha, qno, section, title, pfrom, pto in rows:
        out.append(
            ClauseRow(
                sha256=sha,
                qualified_no=qno,
                #: `clause_no` 는 `qualified_no` 의 꼬리다. 산출물이 따로 주지 않으므로 파생한다.
                clause_no=qno.split("/")[-1] if qno else "",
                section=section,
                title=title,
                text=text,
                page_from=pfrom,
                page_to=pto,
                content_hash=content_hash,
                #: ★적재 대상이 `parse_status == "ok"` 문서뿐이므로 여기 있는 것은 쓸 수 있다.
                #:   그 필터는 적재 스크립트가 건다 — 이 어댑터가 다시 판단하지 않는다.
                usable=True,
            )
        )
    return out


def load_clauses(sha256: str, *, usable_only: bool = True) -> list[ClauseRow]:
    """한 약관 문서의 조항 전부.

    ★조각을 **이어 붙이지 않는다.** 본문 한 벌을 그대로 읽는다.

        처음엔 조각을 이어 붙여 복원하려 했는데, 겹침이 **토큰 기준**이라
        글자 수로 잘라 낼 수 없다. 복원을 추측으로 하면 근거 인용문이
        미세하게 틀리고, 그건 인용 검증이 잡아내지 못한다.
        `policy_clause_content` 에 원본을 한 벌 둔다(중복 없음).
    """
    try:
        with _conn() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT o.content_hash, ct.text,
                       o.sha256, o.qualified_no, o.section, o.title, o.page_from, o.page_to
                FROM policy_clause_occurrence o
                JOIN policy_clause_content ct ON ct.content_hash = o.content_hash
                WHERE o.sha256 = %s
                ORDER BY o.page_from, o.qualified_no
                """,
                (sha256,),
            )
            fetched = cur.fetchall()
    except Exception as exc:  # noqa: BLE001
        raise InfraError(f"조항을 읽지 못했습니다(sha={sha256[:12]}): {exc}") from exc

    if not fetched:
        #: ★"적재 안 됨"과 "인용 불가라 일부러 뺐음"은 **다른 사실**이다.
        #:   섞어 말하면 팀이 적재를 다시 돌리는 헛수고를 한다.
        raise InfraError(
            f"이 약관의 조항 본문이 색인에 없습니다: {sha256[:12]}. "
            "인용 불가(citation_eligible=false)로 제외됐거나 아직 적재 전입니다. "
            "GET /v1/support-manifest 로 대상 여부를 확인하세요."
        )
    return _rows_to_clauses(fetched)


def stats(sha256: str) -> dict:
    """이 문서가 인덱스에 얼마나 들어와 있나."""
    try:
        with _conn() as conn, conn.cursor() as cur:
            #: ★**실제로 조회되는 것**을 센다.
            #:
            #:   처음엔 `policy_clause_occurrence` 만 셌더니 어떤 약관이
            #:   "조항 444개" 라고 나오는데 `load_clauses()` 는 0개를 돌려줬다.
            #:   발생 행은 전 문서에 대해 먼저 쌓았고, 본문 임베딩은 그 뒤에
            #:   `citation_eligible` 로 걸러 **161문서만** 넣었기 때문이다.
            #:   실측(2026-08-02): 발생 156,946 중 **91.4%가 본문 없음**.
            #:
            #:   현황이 조회 결과와 어긋나면 그게 더 나쁘다 —
            #:   "있다"고 세어 놓고 못 꺼내면 판정이 근거 없이 기권한다.
            cur.execute(
                """
                SELECT count(*) FILTER (WHERE c.h IS NOT NULL),
                       count(DISTINCT c.h),
                       count(*)
                FROM policy_clause_occurrence o
                LEFT JOIN LATERAL (
                    SELECT k.content_hash AS h FROM policy_clause_chunk k
                    WHERE k.content_hash = o.content_hash LIMIT 1
                ) c ON true
                WHERE o.sha256 = %s
                """,
                (sha256,),
            )
            usable, uniq, recorded = cur.fetchone()
    except Exception as exc:  # noqa: BLE001
        raise InfraError(f"조항 현황을 읽지 못했습니다: {exc}") from exc
    if not recorded:
        raise InfraError(f"이 약관의 조항 기록이 없습니다: {sha256[:12]}")
    return {
        #: 조회 가능한 조항 수. `load_clauses()` 와 **같은 기준**이다.
        "clauses": usable,
        "distinct_contents": uniq,
        #: ★기록은 있으나 본문이 없는 것. 숨기지 않는다.
        "recorded_occurrences": recorded,
        "missing_bodies": recorded - usable,
        "parse_status": "ok",
        "source": "pg/index_a",
    }


def search(sha256: str, query: str, *, limit: int = 8) -> Sequence[ClauseRow]:
    """약관 **하나 안에서** 낱말로 찾는다(trigram).

    ★유사도 하한을 둔다. 없으면 아무거나 상위에 올라와 근거로 붙는다.
    """
    q = (query or "").strip()
    if not q:
        return []
    try:
        with _conn() as conn, conn.cursor() as cur:
            cur.execute(
                """
                WITH ranked AS (
                    SELECT DISTINCT ON (o.content_hash, o.qualified_no, o.page_from)
                           o.content_hash, ct.text, o.sha256, o.qualified_no,
                           o.section, o.title, o.page_from, o.page_to,
                           word_similarity(%(q)s, c.text) AS sim
                    FROM policy_clause_chunk c
                    JOIN policy_clause_occurrence o ON o.content_hash = c.content_hash
                    JOIN policy_clause_content ct ON ct.content_hash = c.content_hash
                    WHERE o.sha256 = %(sha)s AND word_similarity(%(q)s, c.text) >= %(min)s
                    ORDER BY o.content_hash, o.qualified_no, o.page_from, sim DESC
                )
                --: ★정렬을 **바깥에서** 다시 한다.
                --:   `DISTINCT ON` 은 그룹 키 순서로 정렬해야 하므로,
                --:   그 상태로 LIMIT 을 걸면 유사도 상위가 아니라
                --:   **해시 순서 앞쪽**이 나온다. (코덱스 지적 2026-08-02)
                SELECT * FROM ranked ORDER BY sim DESC LIMIT %(k)s
                """,
                {"q": q, "sha": sha256, "min": _MIN_SIMILARITY, "k": limit},
            )
            fetched = cur.fetchall()
    except Exception as exc:  # noqa: BLE001
        raise InfraError(f"조항 검색에 실패했습니다: {exc}") from exc
    return _rows_to_clauses([r[:8] for r in fetched])


__all__ = ["ensure_search_index", "load_clauses", "search", "stats"]
