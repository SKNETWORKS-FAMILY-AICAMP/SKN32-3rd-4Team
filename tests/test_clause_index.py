"""인덱스 A — 약관 조항 벡터 색인.

★PG 없이 도는 것만 여기 둔다. 실제 적재·검색은 PG 가 떠 있을 때만 돈다.
  PG 를 요구하는 테스트를 무조건 통과시키지 않고 **건너뛴다고 말한다.**
"""

from __future__ import annotations

import pytest

from app.adapters import pgvector_clause_index as ix
from scripts.index.build_clause_index import _chunks


def test_짧은_조항은_쪼개지_않는다():
    assert _chunks("가" * 100, 800, 120) == ["가" * 100]


def test_긴_조항은_겹쳐서_쪼갠다():
    body = "".join(chr(0xAC00 + i % 100) for i in range(2000))
    parts = _chunks(body, 800, 120)
    assert len(parts) > 1
    #: ★겹치게 쪼갠다. 경계에서 문장이 잘려 뜻이 사라지지 않게.
    assert parts[0][-120:] == parts[1][:120]
    #: 원문이 빠짐없이 들어 있다.
    assert body.startswith(parts[0]) and body.endswith(parts[-1])


def test_빈_약관목록은_전역검색으로_바뀌지_않는다():
    #: ★"쓸 수 있는 약관이 없다"를 "전부에서 찾자"로 바꾸면
    #:   2019년 가입자에게 2024년 조항이 근거로 붙는다.
    #:   conn 을 건드리기 전에 걸러야 하므로 None 을 넘겨도 터지지 않아야 한다.
    assert ix.search(None, [0.0] * 8, sha256s=[], limit=5) == []


def test_필터를_기본값으로_두지_않는다():
    #: ★`sha256s` 는 키워드 필수다. 안 넘기면 호출이 실패해야 한다 —
    #:   기본값이 있으면 판정 경로가 조용히 전역 검색을 한다.
    with pytest.raises(TypeError):
        ix.search(None, [0.0] * 8)  # type: ignore[call-arg]


def test_검색결과는_어느_문서_어디인지를_들고_다닌다():
    hit = ix.ClauseHit(
        content_hash="deadbeefcafebabe",
        chunk_ix=0,
        text="…",
        distance=0.1,
        sha256="a" * 64,
        insurer="가보험",
        qualified_no="보통약관/9.",
        section="보통약관",
        title="보상하지 않는 사항",
        page_from=12,
        page_to=13,
    )
    #: 인용 식별자는 판정 경로(`ClauseRow.clause_id`)와 같은 규칙이다.
    assert hit.clause_id == "aaaaaaaaaaaa/보통약관/9.#deadbeef"


# ---------------------------------------------------------------- PG 필요


def _conn_or_skip():
    from app.adapters.pgvector_index import get_conn

    try:
        return get_conn()
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"PG 없음 — 건너뜀: {str(exc)[:80]}")


@pytest.mark.pg
def test_스키마와_적재와_검색이_이어진다():
    conn = _conn_or_skip()
    ix.ensure_schema(conn)

    h = "테스트해시_" + "0" * 10
    vec = [0.0] * 768
    vec[0] = 1.0
    ix.upsert_chunks(conn, [(h, 0, "상해라 함은 급격하고 우연한 외래의 사고를 말합니다.", vec)])
    ix.upsert_occurrences(
        conn, [(h, "t" * 64, "테스트보험", "보통약관/2.", "보통약관", "용어의 정의", 3, 3)]
    )

    #: ★같은 것을 두 번 넣어도 늘지 않는다(재개 가능해야 하므로).
    again = ix.upsert_chunks(conn, [(h, 0, "무시됨", vec)])
    assert again == 0

    hits = ix.search(conn, vec, sha256s=["t" * 64], limit=3)
    assert hits and hits[0].content_hash == h
    assert hits[0].insurer == "테스트보험"

    #: ★다른 약관으로 가두면 안 나온다.
    assert ix.search(conn, vec, sha256s=["z" * 64], limit=3) == []

    with conn.cursor() as cur:
        cur.execute("DELETE FROM policy_clause_chunk WHERE content_hash = %s", (h,))
        cur.execute("DELETE FROM policy_clause_occurrence WHERE content_hash = %s", (h,))
    conn.commit()
    conn.close()
