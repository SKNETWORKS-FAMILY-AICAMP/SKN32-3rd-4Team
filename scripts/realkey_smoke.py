"""실키 스모크 테스트 (최종, 토큰 최소).

로컬 Gemma는 tool-calling을 못하므로, 에이전트가 실제 도구를 호출하는지(steps 채워짐)는
OpenAI/Gemini 실키로만 검증된다. 이 스크립트는 **토큰을 최소로** 쓰도록 짧은 질문 1~2개만
호출한다.

사용법:
  1) .env에 SECRET_KEY + (OPENAI_API_KEY 또는 GOOGLE_API_KEY) 설정
  2) LLM_PROVIDER=openai (또는 gemini)로 실행:
       LLM_PROVIDER=openai python scripts/realkey_smoke.py
  3) 비용: 짧은 질문 2개(수동 ReAct 1 + LangChain 1)만 호출. gpt-4o-mini 기준 수십원 이하.

주의(RULE): 이 스크립트는 키를 출력하거나 저장하지 않는다.
"""

from __future__ import annotations

import os

from app.core.config import get_settings
from app.db.database import SessionLocal


def main() -> None:
    get_settings.cache_clear()
    settings = get_settings()
    provider = settings.LLM_PROVIDER
    print(f"[smoke] provider={provider}")
    if provider == "local":
        print("경고: LLM_PROVIDER=local이면 tool-calling을 검증할 수 없습니다. openai/gemini로 실행하세요.")
        return
    if provider == "openai" and not settings.has_openai_key():
        print("OPENAI_API_KEY가 없습니다. .env에 설정하세요.")
        return
    if provider == "gemini" and not settings.has_google_key():
        print("GOOGLE_API_KEY가 없습니다. .env에 설정하세요.")
        return

    db = SessionLocal()
    try:
        q = "P0001 상품의 가격을 알려줘"

        # 1) 수동 ReAct는 get_chat_client(OpenAI 호환)만 지원 → openai에서만 검증.
        #    (Gemini는 google-genai라 수동 경로 미지원, LangChain 경로에서 검증)
        if provider == "openai":
            from app.agent.react import run_react_agent

            res = run_react_agent(q, db, max_steps=3)
            print(f"[manual] stopped_by={res.stopped_by} steps={len(res.steps)}")
            if res.steps:
                print(f"[manual] tool: {res.steps[0].action} -> ok={res.steps[0].observation.get('ok')}")
            assert res.steps, "실키인데 도구 호출(steps)이 비어 있음 — tool-calling 확인 필요"
        else:
            print("[manual] gemini는 수동 ReAct 경로 미지원 → LangChain 경로로만 검증")

        # 2) LangChain 자동 에이전트 (openai/gemini 모두 지원)
        from app.agent.lc_agent import run_langchain_agent

        res2 = run_langchain_agent(q, db, recursion_limit=6)
        print(f"[langchain] stopped_by={res2.stopped_by} steps={len(res2.steps)}")
        assert res2.steps, "LangChain 에이전트가 도구를 호출하지 않음 — tool-calling 확인 필요"

        print("REALKEY_SMOKE_OK")
    finally:
        db.close()


if __name__ == "__main__":
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    main()
