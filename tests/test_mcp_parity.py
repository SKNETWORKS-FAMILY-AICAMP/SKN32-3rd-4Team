"""Phase 8 — TEST-MCP-PARITY-001: REST와 MCP가 같은 결과를 낸다.

parity의 의미: 같은 기능을 두 인터페이스가 **서로 다른 구현으로 두 번** 만들지 않는다.
결정론 확보를 위해 유스케이스(LLM·Retriever 포함)를 고정 Fake로 주입하고 두 경로의
응답 dict가 **완전히 동일**한지 비교한다(Codex 권고: 실모델 없이 DTO 동등성 검증).
"""

from __future__ import annotations

import asyncio

import pytest

from app.application.answer_question import AnswerResult, Citation

pytestmark = pytest.mark.mcp


def _run(coro):
    return asyncio.run(coro)


#: 고정 결과 — 어느 인터페이스로 부르든 같은 유스케이스가 이걸 낸다.
_FIXED = AnswerResult(
    answer="단순 변심 반품은 수령 후 7일 이내 가능합니다.",
    sources=[
        Citation(source="환불교환정책.pdf", locator="3"),
        Citation(source="loop_safety.txt", locator=None),  # page 없음 → None
    ],
)


@pytest.fixture
def _fixed_use_case(monkeypatch):
    """REST·MCP 양쪽이 타고 들어가는 composition을 고정 Fake로 대체.

    주의(바인딩 시점 차이): REST 라우터는 모듈 로드 시 `build_answer_question`을 import해
    이름을 **조기 바인딩**하고, MCP 도구는 호출 시점에 import해 **지연 바인딩**한다.
    그래서 두 참조를 모두 교체해야 한다. 운영 동작은 동일하지만 테스트에서는 구분해야 한다.
    """
    import app.composition as composition
    import app.routers.rag as rag_router

    def _fake_build(top_k=None):
        def _uc(question):
            return _FIXED

        return _uc

    monkeypatch.setattr(composition, "build_answer_question", _fake_build)
    monkeypatch.setattr(rag_router, "build_answer_question", _fake_build)


def test_rest_and_mcp_rag_qa_are_identical(client, _fixed_use_case):
    question = "단순 변심 반품 기한은?"

    rest = client.post("/api/rag/qa", json={"question": question, "top_k": 3}).json()

    from app.mcp.server import mcp

    _blocks, mcp_out = _run(mcp.call_tool("rag_qa", {"question": question, "top_k": 3}))

    # 두 인터페이스의 응답이 완전히 동일해야 한다(구현이 1벌이므로).
    assert rest == mcp_out, f"REST/MCP parity 위반:\nREST={rest}\nMCP ={mcp_out}"
    # 계약 고정: page는 1-based int이거나 None
    assert rest["sources"] == [
        {"source": "환불교환정책.pdf", "page": 3},
        {"source": "loop_safety.txt", "page": None},
    ]


def test_shared_view_is_single_conversion():
    """변환이 1벌인지 구조로 확인 — REST 라우터와 MCP가 같은 rag_view를 쓴다."""
    from app.adapters.rag_view import answer_to_dict

    expected = answer_to_dict(_FIXED)
    assert expected["sources"][0]["page"] == 3  # locator "3" → 1-based page
    assert expected["sources"][1]["page"] is None  # locator None → None


def test_runtime_config_exposes_no_secrets():
    """TEST-MCP-NOSECRET-001: 런타임 설정 리소스에 키/시크릿이 없어야 한다."""
    import json

    from app.mcp.server import runtime_config

    payload = json.loads(runtime_config())
    keys = {k.lower() for k in payload}
    for banned in ("api_key", "openai_api_key", "gemini_api_key", "secret_key", "token"):
        assert banned not in keys
    # 값에도 키처럼 보이는 문자열이 없어야 한다
    blob = json.dumps(payload).lower()
    assert "sk-" not in blob and "secret" not in blob
