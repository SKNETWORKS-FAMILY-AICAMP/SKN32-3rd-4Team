"""app/core/llm_clients.py -- 타임아웃·executor 정리 안전장치.

★mcp_caller.py에서 겪은 버그(스레드풀 고갈)가 LLM 호출 자리에서 재발하지
않는지 확인한다. p0_compliance_check.txt의 DoD 1·2번에 대응하는 테스트.
"""

from concurrent.futures import ThreadPoolExecutor

import pytest

from app.core import llm_clients as lc


def test_성공_호출마다_executor가_정리된다(monkeypatch):
    shutdown_calls = []
    original_shutdown = ThreadPoolExecutor.shutdown

    def spy_shutdown(self, *a, **k):
        shutdown_calls.append(1)
        return original_shutdown(self, *a, **k)

    monkeypatch.setattr(ThreadPoolExecutor, "shutdown", spy_shutdown)

    for _ in range(10):
        assert lc.call_with_timeout(lambda: "ok") == "ok"

    assert len(shutdown_calls) == 10


def test_일반_예외_50회에도_executor가_누적되지_않는다(monkeypatch):
    """★재현된 결함(mcp_caller.py의 P0-1)이 여기서 재발하지 않아야 한다."""
    shutdown_calls = []
    original_shutdown = ThreadPoolExecutor.shutdown

    def spy_shutdown(self, *a, **k):
        shutdown_calls.append(1)
        return original_shutdown(self, *a, **k)

    monkeypatch.setattr(ThreadPoolExecutor, "shutdown", spy_shutdown)

    def boom():
        raise ValueError("LLM 응답 파싱 실패 등 일반 예외")

    for _ in range(50):
        with pytest.raises(ValueError):
            lc.call_with_timeout(boom)

    assert len(shutdown_calls) == 50


def test_wrapper_데드라인_초과하면_타임아웃_메시지가_붙는다(monkeypatch):
    monkeypatch.setattr(lc, "LLM_TIMEOUT_SECONDS", 0.05)

    import time

    def slow():
        time.sleep(0.3)
        return "늦음"

    with pytest.raises(TimeoutError) as exc_info:
        lc.call_with_timeout(slow)

    assert "LLM 호출 타임아웃" in str(exc_info.value)


def test_도구_자신의_TimeoutError는_원래_메시지가_보존된다():
    """★wrapper 데드라인 메시지로 오표시되면 안 된다(원인 구분)."""

    def raises_own_timeout():
        raise TimeoutError("OpenAI API 자체 타임아웃")

    with pytest.raises(TimeoutError) as exc_info:
        lc.call_with_timeout(raises_own_timeout)

    assert "OpenAI API 자체 타임아웃" in str(exc_info.value)
    assert "LLM 호출 타임아웃" not in str(exc_info.value)


def test_LlmClient는_API_키_없으면_InfraError(monkeypatch):
    from app.core.errors import InfraError

    #: ★환경변수에 진짜 키가 있어도 이 테스트는 "키가 없는 상황"을 확인해야
    #:   하므로, 생성자에 넘긴 빈 값이 환경변수로 대체되지 않게 명시적으로
    #:   None을 넘긴다(api_key="" 는 falsy라 os.getenv로 폴백되므로 부적절).
    client = lc.LlmClient(api_key=None)
    monkeypatch.setattr(client, "_api_key", None)
    with pytest.raises(InfraError):
        client.complete("아무 프롬프트")
