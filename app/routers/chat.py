"""용어 챗봇 API.

★응답에 `verdict` 가 **없다.** 보장 여부는 `POST /v1/prechecks` 로만 답한다.
  보장 질문이 오면 `next_action="precheck_form"` 으로 **넘긴다.**

★HTTP 상태 규칙은 다른 API 와 같다
    200  답했다. "약관에서 못 찾았다"도 200 이다 — 정상 결과다
    422  입력이 잘못됐다
    503  색인이 없다. 이때만 "우리 잘못"이다
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from app.core.errors import InfraError, ValidationErr
from app.core.usecases import chat

router = APIRouter(prefix="/v1", tags=["chat"])


class ChatRequest(BaseModel):
    message: str = Field(description="사용자가 보낸 한 마디", max_length=500)
    insurer: str | None = Field(default=None, description="보험사로 좁힌다(선택)")


def _source():
    from app.composition import build_glossary

    return build_glossary()


@router.post("/chat")
def chat_turn(body: ChatRequest) -> dict:
    """용어 질문에 **약관 원문 인용으로** 답한다.

    ★보장 질문에는 답하지 않는다. 판정 양식으로 안내한다.
    """
    try:
        turn = chat.reply(body.message, source=_source(), insurer=body.insurer)
    except ValidationErr as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e)
        ) from e
    except InfraError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(e)
        ) from e

    ex = turn.explanation
    return {
        "schema_version": "v1",
        "intent": turn.intent,
        "message": turn.message,
        "next_action": turn.next_action,
        "term": turn.term,
        "found": bool(ex and ex.found),
        #: 인용은 가공하지 않은 원문이다.
        "quotes": [
            {
                "quote": q.quote,
                "kind": q.kind,
                "insurer": q.insurer,
                "title": q.title,
                "locator": q.locator,
            }
            for q in (ex.quotes if ex else ())
        ],
        "total_passages": ex.total_passages if ex else 0,
        "insurers": list(ex.insurers) if ex else [],
        "warnings": list(turn.warnings),
    }
