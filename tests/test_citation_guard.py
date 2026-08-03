"""인용 검증 — 지어낸 조항·틀린 인용문·우회를 거르는지.

★v1 은 87% 문서에서 무력했다. 그 결함들이 다시 생기지 않게 못박는다.
"""

from app.core.domain.citation_guard import (
    EvidenceClause,
    Resolution,
    make_handles,
    verify,
)

#: 실제 약관 구조를 본뜬 근거.
_EV = [
    EvidenceClause(
        qualified_no="보통약관/제9조",
        text="회사는 보험금을 지급할 때 자기부담금을 공제합니다.",
    ),
    EvidenceClause(
        qualified_no="특별약관/제3조",
        text="정신질환은 보상하지 않습니다.",
    ),
]

#: ★한 문서에서 `1.` 이 여러 부에 있는 실제 상황(실측: 최대 96개).
_EV_COLLIDING = [
    EvidenceClause(qualified_no="보통약관/1.", text="보장종목은 상해와 질병입니다."),
    EvidenceClause(qualified_no="특별약관/1.", text="이 특별약관의 보장종목은 다릅니다."),
    EvidenceClause(
        qualified_no="이륜자동차 운전중상해 부담보 특별약관/1.",
        text="특별약관의 체결 및 효력에 관한 사항입니다.",
    ),
]


# ── 기본 ──────────────────────────────────────────────────────────────
def test_전체_경로로_인용하면_통과한다():
    r = verify(cited_clauses=["보통약관/제9조"], evidence=_EV)
    assert r.ok
    assert r.checks[0].resolution is Resolution.EXACT


def test_근거에_없는_조항을_인용하면_폐기한다():
    r = verify(cited_clauses=["보통약관/제15조"], evidence=_EV)
    assert not r.ok
    assert r.reason_code == "citation_not_in_evidence"


def test_번호만_와도_후보가_하나면_해소한다():
    r = verify(cited_clauses=["제9조"], evidence=_EV)
    assert r.ok
    assert r.checks[0].resolution is Resolution.RESOLVED


def test_공백_표기_차이를_흡수한다():
    r = verify(cited_clauses=["보통약관/제 9 조"], evidence=_EV)
    assert r.ok


# ── ★v1 의 핵심 결함 ──────────────────────────────────────────────────
def test_같은_번호가_여러_부에_있으면_기권한다():
    """★v1 은 부 이름을 떼서 `보통약관/1.` `특별약관/1.` 을 같은 것으로 봤다.

    그래서 LLM 이 **어느 특약의 1조를 인용하든** 통과했다(87% 문서에서).
    이제는 특정할 수 없다고 말한다 — 통과시키지도, 무작정 폐기하지도 않는다.
    """
    r = verify(cited_clauses=["1."], evidence=_EV_COLLIDING)
    assert not r.ok
    assert r.reason_code == "ambiguous_citation"
    assert len(r.checks[0].candidates) == 3


def test_부를_명시하면_충돌_상황에서도_통과한다():
    r = verify(cited_clauses=["특별약관/1."], evidence=_EV_COLLIDING)
    assert r.ok
    assert r.checks[0].matched.text.startswith("이 특별약관의")


def test_손잡이로_인용하면_충돌이_없다():
    """★근거마다 `E001` 을 주면 이름·번호를 정확히 쓸 필요가 없다."""
    ev = make_handles(_EV_COLLIDING)
    r = verify(cited_clauses=["E002"], evidence=ev)
    assert r.ok
    assert r.checks[0].resolution is Resolution.EXACT
    assert r.checks[0].matched.qualified_no == "특별약관/1."


def test_없는_손잡이는_폐기한다():
    ev = make_handles(_EV_COLLIDING)
    r = verify(cited_clauses=["E099"], evidence=ev)
    assert not r.ok
    assert r.reason_code == "citation_not_in_evidence"


def test_부를_썼는데_틀리면_번호로_강등하지_않는다():
    """`없는특약/제9조` 는 제9조가 근거에 있어도 통과하면 안 된다."""
    r = verify(cited_clauses=["없는특약/제9조"], evidence=_EV)
    assert not r.ok
    assert r.reason_code == "citation_not_in_evidence"


# ── ★코덱스가 찾은 우회 경로 ─────────────────────────────────────────
def test_인용이_아예_없으면_폐기한다():
    """★v1 은 `ok = not unknown` 이라 빈 인용도 통과했다."""
    r = verify(cited_clauses=[], evidence=_EV, answer_text="보장됩니다.")
    assert not r.ok
    assert r.reason_code == "no_citation"


def test_본문에서만_말하고_선언하지_않으면_폐기한다():
    """★v1 은 경고로만 뒀다. 그러면 선언을 비우고 본문에만 써서 우회할 수 있다."""
    r = verify(
        cited_clauses=["보통약관/제9조"],
        evidence=_EV,
        answer_text="제9조와 제77조에 따라 보장됩니다.",
    )
    assert not r.ok
    assert r.reason_code == "undeclared_citation"
    assert "제77조" in r.undeclared_mentions


def test_인용한_조항_자신은_선언_누락이_아니다():
    r = verify(
        cited_clauses=["보통약관/제9조"],
        evidence=_EV,
        answer_text="제9조에 따라 자기부담금을 공제합니다.",
    )
    assert r.ok


def test_인용문이_원문에_없으면_폐기한다():
    """★v1 은 경고로만 뒀다."""
    r = verify(
        cited_clauses=["보통약관/제9조"],
        evidence=_EV,
        quotes={"보통약관/제9조": "회사는 전액을 지급합니다"},
    )
    assert not r.ok
    assert r.reason_code == "quote_not_in_source"


def test_빈_인용문은_통과가_아니라_실패다():
    """★`quote=""` 로 대조를 통째로 건너뛸 수 있으면 안 된다."""
    r = verify(
        cited_clauses=["보통약관/제9조"],
        evidence=_EV,
        quotes={"보통약관/제9조": ""},
    )
    assert not r.ok
    assert r.reason_code == "quote_not_in_source"


def test_인용문이_원문에_있으면_통과한다():
    r = verify(
        cited_clauses=["보통약관/제9조"],
        evidence=_EV,
        quotes={"보통약관/제9조": "자기부담금을 공제합니다"},
    )
    assert r.ok


def test_같은_조항의_인용문_여러_개를_모두_본다():
    """★v1 은 dict 라 마지막 것만 남았다."""
    r = verify(
        cited_clauses=["보통약관/제9조"],
        evidence=_EV,
        quotes={"보통약관/제9조": ["자기부담금을 공제합니다", "전액 지급합니다"]},
    )
    assert not r.ok  # 두 번째가 원문에 없다
    assert r.reason_code == "quote_not_in_source"


def test_조항_표기가_아니면_invalid_다():
    """★v1 은 `search` 라 `"아무말 제9조 아무말"` 이 통과했다."""
    r = verify(cited_clauses=["우울증은 보장됩니다"], evidence=_EV)
    assert not r.ok
    assert r.reason_code == "invalid_citation"


def test_조와_호를_구분한다():
    """★`제1조` 와 `1.` 은 문법 층이 다르다. v1 은 같은 키로 만들었다."""
    ev = [EvidenceClause(qualified_no="보통약관/제1조", text="목적")]
    r = verify(cited_clauses=["1."], evidence=ev)
    assert not r.ok  # `1.` 로는 `제1조` 에 닿지 않는다


def test_조항의_가지번호를_구분한다():
    ev = [
        EvidenceClause(qualified_no="보통약관/제9조", text="본조"),
        EvidenceClause(qualified_no="보통약관/제9조의2", text="가지조"),
    ]
    r = verify(cited_clauses=["제9조의2"], evidence=ev)
    assert r.ok
    assert r.checks[0].matched.text == "가지조"


# ── P0-3: by_path(전체경로) 충돌 ──────────────────────────────────────
# ★번호(by_no) 충돌은 위에서 이미 검증됐지만, 전체경로 색인(by_path)은
#   v2에서도 dict로 남아있어서 같은 qualified_no를 가진 서로 다른 근거가
#   들어오면 나중 것이 앞 것을 조용히 덮고 exact로 통과했다(실측 s6:
#   1,367문서 중 1,198문서(87.6%)가 같은 qualified_no를 둘 이상 가짐).


def test_같은_전체경로에_다른_조항이_있으면_기권한다():
    ev = [
        EvidenceClause(qualified_no="제9조", text="본문 A", clause_id="doc-a#9"),
        EvidenceClause(qualified_no="제9조", text="본문 B", clause_id="doc-b#9"),
    ]
    r = verify(cited_clauses=["제9조"], evidence=ev, answer_text="제9조에 따르면...")
    assert not r.ok
    assert r.checks[0].resolution is Resolution.AMBIGUOUS


def test_같은_전체경로_충돌도_손잡이로는_정확히_해소한다():
    ev = make_handles(
        [
            EvidenceClause(qualified_no="제9조", text="본문 A", clause_id="doc-a#9"),
            EvidenceClause(qualified_no="제9조", text="본문 B", clause_id="doc-b#9"),
        ]
    )
    r = verify(
        cited_clauses=["E001"],
        evidence=ev,
        answer_text="본문 A에 따르면...",
        quotes={"E001": ["본문 A"]},
    )
    assert r.ok
    assert r.checks[0].resolution is Resolution.EXACT
    assert r.checks[0].matched.clause_id == "doc-a#9"


def test_같은_전체경로_같은_조항이_여러_청크로_쪼개진_것은_통과한다():
    """clause_id·본문이 같으면 같은 조항이 여러 청크로 쪼개진 것으로 보고
    후보 1개로 접는다 -- 진짜 다른 조항일 때만 ambiguous."""
    ev = [
        EvidenceClause(qualified_no="제9조", text="같은 본문", clause_id="doc-a#9"),
        EvidenceClause(qualified_no="제9조", text="같은 본문", clause_id="doc-a#9"),
    ]
    r = verify(cited_clauses=["제9조"], evidence=ev, answer_text="제9조에 따르면...")
    assert r.checks[0].resolution is Resolution.EXACT


# ── P0-2: 검증된 quote 안의 준용조항 ──────────────────────────────────
# ★약관은 "제3조에서 정한 사유가 발생한 경우" 처럼 다른 조항을 준용하는
#   문장이 흔하다(실측 s6: 204,098개 조항 중 90,428개(44.3%)가 자기 번호가
#   아닌 제N조를 본문에 포함). 검증된 quote 밖의 미선언 주장은 계속
#   fail-closed지만, quote 안의 준용조항까지 잡으면 정상 답변이 대량으로
#   기권된다.


def test_검증된_quote_안의_준용조항은_선언_누락이_아니다():
    ev = make_handles(
        [EvidenceClause(qualified_no="제9조", text="회사는 제3조(보험금의 지급사유)에서 정한 사유가 발생한 경우 보상합니다.")]
    )
    answer = (
        "제9조에 따라 보상됩니다 [E001]. "
        "회사는 제3조(보험금의 지급사유)에서 정한 사유가 발생한 경우 보상합니다."
    )
    r = verify(
        cited_clauses=["E001"],
        evidence=ev,
        answer_text=answer,
        quotes={"E001": ["회사는 제3조(보험금의 지급사유)에서 정한 사유가 발생한 경우 보상합니다."]},
    )
    assert r.ok
    assert r.undeclared_mentions == []


def test_quote_밖의_준용조항_주장은_여전히_선언_누락이다():
    ev = make_handles([EvidenceClause(qualified_no="제9조", text="본문")])
    answer = "제9조에 따르면 보상됩니다 [E001]. 다만 제4조에 따라 예외가 있을 수 있습니다."
    r = verify(
        cited_clauses=["E001"],
        evidence=ev,
        answer_text=answer,
        quotes={"E001": ["본문"]},
    )
    assert not r.ok
    assert "제4조" in r.undeclared_mentions


def test_quote_payload에만_있고_answer에_없으면_면제하지_않는다():
    ev = make_handles(
        [EvidenceClause(qualified_no="제9조", text="회사는 제3조에서 정한 사유가 발생한 경우 보상합니다.")]
    )
    answer = "제9조에 따라 보상됩니다 [E001]. 그리고 별개로 제3조도 관련이 있다고 생각합니다."
    r = verify(
        cited_clauses=["E001"],
        evidence=ev,
        answer_text=answer,
        quotes={"E001": ["회사는 제3조에서 정한 사유가 발생한 경우 보상합니다."]},
    )
    assert "제3조" in r.undeclared_mentions
