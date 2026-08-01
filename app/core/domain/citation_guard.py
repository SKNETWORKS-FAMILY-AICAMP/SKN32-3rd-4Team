"""인용 검증 — LLM 이 댄 조항이 **근거에 실제로 있는지** 대조한다.

★왜 필요한가 — 프롬프트는 방어선이 아니다

    지금 코드는 근거가 0건이면 LLM 을 부르지 않는다(`AnswerQuestion`).
    그런데 근거가 **하나라도** 있으면 LLM 이 호출되고, 그 다음은 프롬프트에 맡겨진다.

    위험은 여기서 생긴다. 조항에 "우울증"이 없는데 LLM 이
    "정신과 질환이니 비슷하게 보장될 겁니다" 처럼 **그럴듯하게 지어내는 것**이다.
    프롬프트에 "추측하지 말라"고 적어도, 지키는지는 모델에 달렸다.

    ★이건 코드로 강제할 수 있다.

        LLM 출력에서 인용한 조항 번호를 뽑는다
          → 넘겨준 근거에 그 조항이 실재하는지 대조한다
          → 없으면 그 답을 버린다

    프롬프트를 무시하는 모델이라도 이 검사는 통과하지 못한다.

★더 나쁜 상황을 막는다

    지금은 답변에 **검색 결과가 그대로 출처로 붙는다.**
    LLM 이 지어낸 답에도 근거가 달려 나가서 **오히려 더 그럴듯해 보인다.**
    실제로 인용한 것과 붙은 출처가 다른 것이다.

★무엇을 검사하나

    1. 인용한 조항이 **허용 목록(넘겨준 근거)** 에 있는가
    2. 본문에서 `제N조` 를 말했는데 `cited_clauses` 에 없는가 (선언 누락)
    3. 인용문이 조항 원문의 **실제 일부인가** (지어낸 문장 방지)

    1번을 어기면 **폐기**한다. 2·3번은 경고로 남긴다 —
    본문의 `제N조` 는 조항 안의 상호참조일 수 있어 폐기 사유로 삼으면 과하다.

이 모듈은 **프레임워크도 바깥 계층도 모른다**(클린아키텍처 2단계 안쪽).
검증에 필요한 것은 인자로 받는다 — 저장소를 직접 읽지 않는다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

#: 본문에서 조항을 말한 흔적. `제9조`, `제 9 조의 2`, `보통약관 제9조`.
_MENTION = re.compile(r"제\s*(\d{1,3})\s*조(?:\s*의\s*(\d{1,2}))?")
#: 조항 식별자 정규화용.
_NUM = re.compile(r"제\s*(\d{1,3})\s*조(?:\s*의\s*(\d{1,2}))?")


def _norm_quote(s: str) -> str:
    """인용문 대조용 정규화. 줄바꿈·공백 차이로 어긋나지 않게 한다."""
    return re.sub(r"\s+", "", s or "")


def _clause_key(qualified_no: str) -> str:
    """`보통약관/제 9 조` → `제9조`. 부 이름은 떼고 번호만 본다.

    ★왜 번호만 보나 — LLM 이 부 이름까지 정확히 쓰길 기대할 수 없다.
      부까지 맞추길 요구하면 **정답인데 폐기**하는 일이 생긴다.
      대신 번호가 허용 목록에 없으면 그건 확실한 오류다.
    """
    tail = qualified_no.rsplit("/", 1)[-1]
    m = _NUM.search(tail)
    if not m:
        return re.sub(r"\s+", "", tail)
    return f"제{m.group(1)}조" + (f"의{m.group(2)}" if m.group(2) else "")


@dataclass(frozen=True)
class EvidenceClause:
    """판정에 넘긴 근거 조항 하나."""

    qualified_no: str
    text: str
    clause_id: str = ""


@dataclass
class GuardResult:
    """검증 결과."""

    ok: bool
    #: 허용 목록에 없는 조항을 인용했다 — **폐기 사유**.
    unknown_citations: list[str] = field(default_factory=list)
    #: 본문에서 말했는데 `cited_clauses` 에 선언하지 않았다 — 경고.
    undeclared_mentions: list[str] = field(default_factory=list)
    #: 인용문이 원문에 없다 — 경고.
    quote_mismatches: list[str] = field(default_factory=list)

    @property
    def reason(self) -> str:
        if self.ok:
            return ""
        return "근거에 없는 조항을 인용했습니다: " + ", ".join(self.unknown_citations)


def verify(
    *,
    cited_clauses: list[str],
    evidence: list[EvidenceClause],
    answer_text: str = "",
    quotes: dict[str, str] | None = None,
) -> GuardResult:
    """인용을 검증한다.

    Args:
        cited_clauses: LLM 이 인용했다고 선언한 조항들(`"보통약관/제9조"` 꼴).
        evidence: 실제로 넘겨준 근거 조항들.
        answer_text: 답변 본문(선언 누락 확인용).
        quotes: `{조항: 인용문}` — 있으면 원문 포함 여부를 확인한다.

    Returns:
        `GuardResult`. `ok=False` 면 **그 답을 쓰면 안 된다.**
    """
    allowed = {_clause_key(e.qualified_no) for e in evidence}
    by_key = {_clause_key(e.qualified_no): e for e in evidence}

    unknown = [c for c in cited_clauses if _clause_key(c) not in allowed]

    #: 본문에서 조항을 말했는데 선언하지 않은 것.
    declared = {_clause_key(c) for c in cited_clauses}
    mentioned = {
        f"제{m.group(1)}조" + (f"의{m.group(2)}" if m.group(2) else "")
        for m in _MENTION.finditer(answer_text or "")
    }
    undeclared = sorted(mentioned - declared)

    #: 인용문이 원문에 실제로 있는지.
    mismatched: list[str] = []
    for key, quote in (quotes or {}).items():
        src = by_key.get(_clause_key(key))
        if src is None:
            continue  # 허용 목록에 없는 건 위에서 이미 잡힌다
        if _norm_quote(quote) and _norm_quote(quote) not in _norm_quote(src.text):
            mismatched.append(key)

    return GuardResult(
        ok=not unknown,
        unknown_citations=unknown,
        undeclared_mentions=undeclared,
        quote_mismatches=mismatched,
    )
