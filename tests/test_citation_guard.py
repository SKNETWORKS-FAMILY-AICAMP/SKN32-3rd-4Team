"""인용 검증 — 지어낸 조항을 거르는지."""

from app.core.domain.citation_guard import EvidenceClause, verify

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


def test_근거에_있는_조항만_인용하면_통과한다():
    r = verify(cited_clauses=["보통약관/제9조"], evidence=_EV)
    assert r.ok
    assert not r.unknown_citations


def test_근거에_없는_조항을_인용하면_폐기한다():
    #: ★핵심 — LLM 이 '제15조' 를 지어냈다. 근거에 없다.
    r = verify(cited_clauses=["보통약관/제15조"], evidence=_EV)
    assert not r.ok
    assert "보통약관/제15조" in r.unknown_citations


def test_부_이름이_달라도_번호가_맞으면_통과한다():
    #: LLM 이 부 이름까지 정확히 쓰길 기대하지 않는다. 번호가 근거에 있으면 된다.
    r = verify(cited_clauses=["제9조"], evidence=_EV)
    assert r.ok


def test_공백_표기_차이를_흡수한다():
    r = verify(cited_clauses=["보통약관/제 9 조"], evidence=_EV)
    assert r.ok


def test_본문에서만_말하고_선언하지_않으면_경고한다():
    r = verify(
        cited_clauses=["보통약관/제9조"],
        evidence=_EV,
        answer_text="제9조와 제3조에 따라 보장됩니다.",
    )
    assert r.ok                      # 폐기 사유는 아니다
    assert "제3조" in r.undeclared_mentions


def test_인용문이_원문에_없으면_경고한다():
    r = verify(
        cited_clauses=["보통약관/제9조"],
        evidence=_EV,
        quotes={"보통약관/제9조": "회사는 전액을 지급합니다"},   # 원문에 없는 문장
    )
    assert "보통약관/제9조" in r.quote_mismatches


def test_인용문이_원문에_있으면_통과한다():
    r = verify(
        cited_clauses=["보통약관/제9조"],
        evidence=_EV,
        quotes={"보통약관/제9조": "자기부담금을 공제합니다"},
    )
    assert not r.quote_mismatches
