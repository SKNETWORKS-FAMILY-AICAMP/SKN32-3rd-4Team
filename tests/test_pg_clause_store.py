"""통합 조항 저장소(PG) — 파일 어댑터와 **같은 포트**를 만족하는가.

★두 구현이 갈라지면 조립 지점에서 바꿔 끼울 수 없다.
  포트 준수는 PG 없이도 확인할 수 있으므로 여기서 먼저 막는다.
"""

from __future__ import annotations

import pytest

from app.adapters import pg_clause_store
from app.core.ports.precheck import ClauseSourcePort


def test_파일_어댑터와_같은_포트를_만족한다():
    from app.adapters import file_clause_store

    assert isinstance(pg_clause_store, ClauseSourcePort)
    assert isinstance(file_clause_store, ClauseSourcePort)


def test_빈_질의는_검색하지_않는다():
    #: ★conn 을 열기 전에 걸러야 한다. PG 가 없어도 터지지 않아야 한다.
    assert pg_clause_store.search("a" * 64, "   ") == []


def test_조립_지점이_기본으로_파일을_고른다(monkeypatch):
    """★기본이 PG 면, 적재 안 된 기계에서 판정이 통째로 죽는다.

    인덱스 A 적재는 CPU 로 4~5시간이라 기계마다 상태가 다르다.
    쓰려면 `CLAUSE_STORE=pg` 로 명시하게 한다.
    """
    import importlib

    import app.composition as comp

    monkeypatch.delenv("CLAUSE_STORE", raising=False)
    importlib.reload(comp)
    assert comp.build_precheck()["clauses"].__name__.endswith("file_clause_store")

    monkeypatch.setenv("CLAUSE_STORE", "pg")
    importlib.reload(comp)
    assert comp.build_precheck()["clauses"].__name__.endswith("pg_clause_store")

    monkeypatch.delenv("CLAUSE_STORE", raising=False)
    importlib.reload(comp)


# ---------------------------------------------------------------- PG 필요


def _conn_or_skip():
    from app.adapters.pgvector_index import get_conn

    try:
        return get_conn()
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"PG 없음 — 건너뜀: {str(exc)[:80]}")


@pytest.mark.pg
def test_없는_약관은_조용히_빈_결과를_주지_않는다():
    """★없는 것을 `[]` 로 돌려주면 "조항이 없는 약관"으로 읽힌다.

    실제로는 **적재가 안 된 것**이다. 둘을 섞으면 판정이 근거 없이 기권한다.
    """
    from app.core.errors import InfraError

    _conn_or_skip().close()
    with pytest.raises(InfraError):
        pg_clause_store.load_clauses("f" * 64)


@pytest.mark.pg
def test_적재된_약관을_읽고_찾는다():
    from app.adapters import pgvector_clause_index as ix

    conn = _conn_or_skip()
    ix.ensure_schema(conn)
    pg_clause_store.ensure_search_index(conn)

    sha = "e" * 64
    h = "통합저장소테스트해시"
    vec = [0.0] * 768
    vec[3] = 1.0
    body = "회사는 피보험자가 상해로 인하여 의료기관에 입원하여 치료를 받은 경우 보상합니다."
    ix.upsert_content(conn, [(h, body, 1)])
    ix.upsert_chunks(conn, [(h, 0, 1, body, vec)])
    ix.upsert_occurrences(conn, [(h, sha, "테스트보험", "보통약관/3.", "보통약관", "보상내용", 7, 7)])
    conn.commit()

    rows = pg_clause_store.load_clauses(sha)
    assert len(rows) == 1
    assert rows[0].text == body
    #: 인용 식별자 규칙이 파일 어댑터와 같아야 한다.
    assert rows[0].clause_id.startswith("eeeeeeeeeeee/보통약관/3.#")

    st = pg_clause_store.stats(sha)
    assert st["clauses"] == 1 and st["distinct_contents"] == 1

    hits = pg_clause_store.search(sha, "상해로 인하여 의료기관에 입원")
    assert hits and hits[0].content_hash == h
    #: ★다른 약관으로는 안 나온다.
    assert pg_clause_store.search("d" * 64, "상해로 인하여 의료기관에 입원") == []

    with conn.cursor() as cur:
        cur.execute("DELETE FROM policy_clause_chunk WHERE content_hash = %s", (h,))
        cur.execute("DELETE FROM policy_clause_content WHERE content_hash = %s", (h,))
        cur.execute("DELETE FROM policy_clause_occurrence WHERE content_hash = %s", (h,))
    conn.commit()
    conn.close()


@pytest.mark.pg
def test_짧은_질의가_긴_조각에서_찾아진다():
    """★`similarity()` 로는 **0건**이 나왔다.

    `similarity()` 는 문자열 **전체**끼리 비교하므로 10자 질의와 800자 조각은
    아무리 잘 맞아도 0.02 수준이다. 실측 —

        "보상하지 않는 손해"  similarity 0.066 · word_similarity 0.727
        "보험금의 지급사유"   similarity 0.106 · word_similarity 1.000

    `word_similarity(질의, 본문)` 은 질의가 본문의 **어느 부분과** 맞는지를 잰다.
    검색이 조용히 0건을 돌려주면 판정은 근거 없이 기권한다 — 고장이 안 보인다.
    """
    conn = _conn_or_skip()
    with conn.cursor() as cur:
        cur.execute("""SELECT o.sha256 FROM policy_clause_occurrence o
                       JOIN policy_clause_chunk c ON c.content_hash = o.content_hash
                       GROUP BY 1 ORDER BY count(*) DESC LIMIT 1""")
        row = cur.fetchone()
    conn.close()
    if not row:
        pytest.skip("인덱스 A 가 비어 있음 — build_clause_index 미실행")
    sha = row[0]
    hits = pg_clause_store.search(sha, "보험금의 지급사유", limit=5)
    assert hits, "짧은 질의가 0건입니다 — similarity/word_similarity 를 확인하세요"


@pytest.mark.pg
def test_현황이_조회_결과와_어긋나지_않는다():
    """★"조항 444개" 라고 세어 놓고 `load_clauses()` 가 0개를 돌려준 적이 있다.

    발생 행은 전 문서에 먼저 쌓고 본문은 `citation_eligible` 로 걸러 넣었기
    때문이다. 실측(2026-08-02): 발생 156,946 중 **91.4%가 본문 없음**.
    현황이 조회 결과와 어긋나면 판정이 근거 없이 기권한다.
    """
    conn = _conn_or_skip()
    with conn.cursor() as cur:
        cur.execute("""SELECT o.sha256 FROM policy_clause_occurrence o
                       JOIN policy_clause_chunk c ON c.content_hash = o.content_hash
                       GROUP BY 1 ORDER BY count(*) DESC LIMIT 1""")
        row = cur.fetchone()
    conn.close()
    if not row:
        pytest.skip("인덱스 A 가 비어 있음")
    sha = row[0]
    st = pg_clause_store.stats(sha)
    rows = pg_clause_store.load_clauses(sha)
    assert st["clauses"] == len(rows), (
        f"stats 는 {st['clauses']}개라는데 실제로는 {len(rows)}개가 나옵니다"
    )
    assert "missing_bodies" in st, "본문 없는 기록 수를 숨기면 안 됩니다"
