"""RAG 응답 표현(view) — REST와 MCP가 **같은 변환 1벌**을 쓰도록 모은다(Phase 8).

parity의 핵심: 유스케이스 결과(AnswerResult)를 외부 응답 dict로 바꾸는 코드가 두 벌이면
인터페이스별로 조용히 어긋난다. 변환을 여기 한 곳에 두고 REST 라우터·MCP 도구가 공유한다.
응답 shape는 기존 계약({answer, sources:[{source, page}]})을 그대로 보존한다.
"""

from __future__ import annotations

from typing import TypedDict

from app.application.answer_question import AnswerResult


class SourceDict(TypedDict):
    """출처 1건의 외부 계약."""

    source: str
    page: int | None


class AnswerDict(TypedDict):
    """RAG 답변 응답의 외부 계약(REST·MCP 공통).

    `dict[str, Any]`로 두면 이후 필드 변경이 정적으로 잡히지 않아 두 인터페이스가 조용히
    어긋날 수 있다(Codex 지적) → TypedDict로 필드를 고정한다.
    """

    answer: str
    sources: list[SourceDict]


def locator_to_page(locator: str | None) -> int | None:
    """Citation.locator(문자열) → 외부 응답의 page(int|None). 숫자가 아니면 None."""
    return int(locator) if locator and locator.isdigit() else None


def answer_to_dict(result: AnswerResult) -> AnswerDict:
    """AnswerResult → {answer, sources:[{source, page}]} (REST·MCP 공통 계약)."""
    return {
        "answer": result.answer,
        "sources": [
            {"source": c.source, "page": locator_to_page(c.locator)} for c in result.sources
        ],
    }
