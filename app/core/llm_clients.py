"""LLM 호출 — 타임아웃·정리 안전장치 포함.

★이 모듈은 실제 LLM(OpenAI)을 부르는 유일한 자리다. `explain()`이 이
함수를 통해서만 LLM을 부르게 해서, 타임아웃/정리 로직을 한 곳에서만
관리한다.

★왜 executor로 감싸나 — 예전 mcp_caller.py 버그의 재발 방지

    langgraph_agent/nodes/mcp_caller.py에서 겪었던 문제가 그대로 재발할 수
    있는 자리다: 외부 API(OpenAI) 호출이 멈추거나 느려지면, 파이썬은
    스레드를 강제 종료할 방법이 없어서 그 스레드가 계속 남는다. 공유
    스레드풀을 쓰면 반복된 타임아웃이 풀을 통째로 고갈시켜 이후 모든
    요청이 멈춘다(재현·수정 기록은 p0_compliance_check.txt 참고).

    그래서 호출마다 독립된 1-worker executor를 쓴다 -- 스레드 하나가
    영영 안 멈춰도 "그 호출 전용"으로 격리돼 있어서 다른 호출을 안 막는다.

★도구 자신의 예외와 wrapper의 데드라인 초과를 구분한다

    `future.done()`으로 가른다 -- 데드라인을 넘겨서 `result()`가 포기한
    경우 백그라운드 스레드는 아직 실행 중이라 `future.done()`이 False다.
    호출이 빠르게 자기 예외를 던져서 끝난 경우엔 future가 이미 완료
    상태(done()=True)이므로, 그건 우리 데드라인 문제가 아니라 호출 자체의
    오류이니 원래 예외를 그대로(원인 보존) 다시 던진다.
"""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError

from app.core.errors import InfraError

#: 환경변수로 조정 가능. LLM 호출은 도구 호출보다 오래 걸릴 수 있어 기본을 넉넉히 둔다.
LLM_TIMEOUT_SECONDS = float(os.getenv("LLM_TIMEOUT_SECONDS", "20"))
LLM_MODEL_NAME = os.getenv("LLM_MODEL_NAME", "gpt-4o-mini")


def call_with_timeout(func, *args, **kwargs):
    """호출마다 새 1-worker executor를 쓴다(공유 풀을 쓰지 않는다).
    자세한 이유는 모듈 docstring 참고."""
    executor = ThreadPoolExecutor(max_workers=1)
    future = executor.submit(func, *args, **kwargs)
    try:
        return future.result(timeout=LLM_TIMEOUT_SECONDS)
    except FutureTimeoutError as e:
        if future.done():
            #: 도구 자신이 던진 예외다(3.11+에서는 concurrent.futures.TimeoutError가
            #: builtins.TimeoutError와 같은 클래스라 여기로 들어올 수 있다).
            #: 우리 데드라인 문제가 아니므로 원인 그대로 다시 던진다.
            raise
        raise TimeoutError(
            f"LLM 호출 타임아웃 ({LLM_TIMEOUT_SECONDS}초 초과)"
        ) from e
    finally:
        executor.shutdown(wait=False, cancel_futures=True)


class LlmClient:
    """OpenAI 호출 어댑터.

    ★`explain()`은 이 클래스만 알고 `openai` SDK를 직접 import하지 않는다
      -- provider를 바꿔도 `explain()`은 안 바뀐다.
    """

    def __init__(self, *, model: str | None = None, api_key: str | None = None):
        self._model = model or LLM_MODEL_NAME
        self._api_key = api_key or os.getenv("OPENAI_API_KEY")
        self._client = None

    def _get_client(self):
        if self._client is None:
            if not self._api_key:
                raise InfraError("OPENAI_API_KEY가 설정되지 않았습니다.")
            from openai import OpenAI

            self._client = OpenAI(api_key=self._api_key)
        return self._client

    def complete(self, prompt: str) -> str:
        """프롬프트 하나를 보내고 텍스트 응답을 받는다.

        타임아웃·executor 정리는 `call_with_timeout`이 보장한다 -- 이
        메서드 자체는 그 안전장치를 우회할 방법이 없다.
        """

        def _do_call() -> str:
            client = self._get_client()
            resp = client.chat.completions.create(
                model=self._model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0,
            )
            return resp.choices[0].message.content or ""

        return call_with_timeout(_do_call)
