"""scripts/demo/mcp_agent_client.py -- 4단계 흐름(계약 06_계약_Agent.md §5)을
실제 MCP 서버(FastMCP)에 `mcp.shared.memory`의 인메모리 세션으로 붙여
검증한다. subprocess/실데이터 없이 REST 데모 테스트와 같은 걸 확인한다.
"""

import asyncio
import hashlib
import json

import pytest
from mcp.shared.memory import create_connected_server_and_client_session

import app.auth.agent_client as ac
import app.mcp_server.resources as res
import app.mcp_server.tools as tools
from app.core.domain.insurance import Verdict
from app.core.domain.precheck_result import PrecheckOutcome
from app.mcp_server.server import mcp
from scripts.demo import mcp_agent_client as demo

_RAW_KEY = "test-raw-key-123"


@pytest.fixture(autouse=True)
def _fake_registry(monkeypatch, tmp_path):
    """실제 config/agent_clients.json 없이도 인증이 통과하게 임시 레지스트리로 교체."""
    registry = {
        "clients": [
            {
                "agent_client_id": "demo-1",
                "name": "테스트",
                "api_key_hash": ac.hash_api_key(_RAW_KEY),
                "scopes": ["precheck:read", "terms:read", "observations:write"],
                "rate_limit_rpm": 1000,
                "status": "active",
            }
        ]
    }
    path = tmp_path / "agent_clients.json"
    path.write_text(json.dumps(registry), encoding="utf-8")
    monkeypatch.setattr(ac, "_REGISTRY", path)
    ac.rate_limiter._hits.clear()
    yield
    ac.rate_limiter._hits.clear()


@pytest.fixture(autouse=True)
def _fake_support_manifest(monkeypatch):
    """실데이터(data/raw/manifests)가 이 브랜치엔 없어서 support_manifest()를 페이크로 교체."""
    monkeypatch.setattr(
        res, "support_manifest", lambda: {"total_policy_versions": 1, "insurers": {}}
    )


class _FakeGraph:
    def __init__(self, outcome):
        self._outcome = outcome

    def invoke(self, body):
        return self._outcome, None


def _outcome(trace_id: str = "trace-abc123") -> PrecheckOutcome:
    return PrecheckOutcome(verdict=Verdict.NEEDS_DOCUMENTS, abstained=False, trace_id=trace_id)


def _run_async(coro):
    return asyncio.run(coro)


async def _with_session(coro_factory):
    async with create_connected_server_and_client_session(mcp) as session:
        return await coro_factory(session)


def test_outcome_없으면_3단계까지만_호출한다(monkeypatch):
    monkeypatch.setattr(tools, "_graph", lambda: _FakeGraph(_outcome()))

    async def go(session):
        return await demo.run_with_session(
            session,
            api_key=_RAW_KEY,
            insurer="삼성화재",
            enrolled_on="20200301",
            kcd_codes=["F32"],
            product_name=None,
            client_ref="demo-mcp-client",
            outcome=None,
        )

    result = _run_async(_with_session(go))

    assert result["precheck_result"]["trace_id"] == "trace-abc123"
    assert result["observation_result"] is None


def test_outcome_있으면_4단계까지_호출하고_trace_id를_같이_보낸다(monkeypatch):
    monkeypatch.setattr(tools, "_graph", lambda: _FakeGraph(_outcome()))

    calls: list[dict] = []

    def fake_store(payload, **kwargs):
        calls.append(payload)

        class _R:
            stored = True
            duplicate = False
            idempotency_key = payload["idempotency_key"]

        return _R()

    monkeypatch.setattr("app.adapters.external_submission_store.store", fake_store)

    async def go(session):
        return await demo.run_with_session(
            session,
            api_key=_RAW_KEY,
            insurer="삼성화재",
            enrolled_on="20200301",
            kcd_codes=["F32"],
            product_name=None,
            client_ref="demo-mcp-client",
            outcome="paid",
        )

    result = _run_async(_with_session(go))

    assert result["observation_result"]["verification"] == "unverified"
    assert calls[0]["precheck_trace_id"] == "trace-abc123"
    assert calls[0]["outcome"] == "paid"
    #: ★계약 §4: Idempotency-Key는 필수다 -- 안 줬으니 자동 생성됐어야 한다.
    assert calls[0]["idempotency_key"]


def test_idempotency_key를_직접_주면_그대로_쓴다(monkeypatch):
    monkeypatch.setattr(tools, "_graph", lambda: _FakeGraph(_outcome()))

    calls: list[dict] = []

    def fake_store(payload, **kwargs):
        calls.append(payload)

        class _R:
            stored = True
            duplicate = False
            idempotency_key = payload["idempotency_key"]

        return _R()

    monkeypatch.setattr("app.adapters.external_submission_store.store", fake_store)

    async def go(session):
        return await demo.run_with_session(
            session,
            api_key=_RAW_KEY,
            insurer="삼성화재",
            enrolled_on="20200301",
            kcd_codes=["F32"],
            product_name=None,
            client_ref="demo-mcp-client",
            outcome="paid",
            idempotency_key="my-fixed-key",
        )

    _run_async(_with_session(go))
    assert calls[0]["idempotency_key"] == "my-fixed-key"


def _find_runtime_error(exc: BaseException) -> RuntimeError | None:
    """★anyio 태스크그룹이 예외를 ExceptionGroup으로 감싸므로 재귀적으로 찾는다."""
    if isinstance(exc, RuntimeError):
        return exc
    if isinstance(exc, BaseExceptionGroup):
        for sub in exc.exceptions:
            found = _find_runtime_error(sub)
            if found is not None:
                return found
    return None


def test_잘못된_api_key면_예외를_던진다(monkeypatch):
    monkeypatch.setattr(tools, "_graph", lambda: _FakeGraph(_outcome()))

    async def go(session):
        return await demo.run_with_session(
            session,
            api_key="wrong-key",
            insurer="삼성화재",
            enrolled_on="20200301",
            kcd_codes=["F32"],
            product_name=None,
            client_ref="demo-mcp-client",
            outcome=None,
        )

    with pytest.raises(BaseException) as exc_info:
        _run_async(_with_session(go))

    #: ★ClientSession/TaskGroup 종료 과정에서 ExceptionGroup으로 감싸질 수
    #:   있다 -- 안에서 우리가 던진 RuntimeError를 찾아서 검증한다.
    found = _find_runtime_error(exc_info.value)
    assert found is not None, f"RuntimeError를 못 찾음: {exc_info.value!r}"
    assert "MCP 도구 호출 실패" in str(found)
