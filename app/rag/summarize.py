"""문서 요약 (map-reduce, PDF5/langchain_test).

긴 텍스트를 청크로 나눠 청크별 요약(map) 후 통합(reduce). 로컬 Gemma 평문 사용.
chat_complete 주입으로 결정론적 테스트 가능.
"""

from __future__ import annotations

from collections.abc import Callable

from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.core.config import get_settings

ChatComplete = Callable[[str], str]


def _default_chat_complete(prompt: str) -> str:
    from openai import APIConnectionError

    from app.core.errors import InfraError
    from app.core.llm_clients import get_active_model, get_chat_client

    client = get_chat_client()
    try:
        resp = client.chat.completions.create(
            model=get_active_model(),
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
            max_tokens=200,
        )
    except APIConnectionError as exc:
        raise InfraError("LLM 서버에 연결할 수 없습니다.") from exc
    return resp.choices[0].message.content or ""


def summarize_text(text: str, chat_complete: ChatComplete | None = None) -> str:
    chat_complete = chat_complete or _default_chat_complete
    settings = get_settings()

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=settings.CHUNK_SIZE * 3, chunk_overlap=settings.CHUNK_OVERLAP
    )
    chunks = splitter.split_text(text)

    if len(chunks) <= 1:
        return chat_complete(f"다음 내용을 한국어로 3문장 이내로 요약하라:\n\n{text}")

    # map: 청크별 요약
    partials = [chat_complete(f"다음을 한국어로 간단히 요약하라:\n\n{c}") for c in chunks]
    # reduce: 부분 요약 통합
    joined = "\n".join(f"- {p}" for p in partials)
    return chat_complete(f"다음 부분 요약들을 한국어로 3문장 이내로 통합 요약하라:\n\n{joined}")
