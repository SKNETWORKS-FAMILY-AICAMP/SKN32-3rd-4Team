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
