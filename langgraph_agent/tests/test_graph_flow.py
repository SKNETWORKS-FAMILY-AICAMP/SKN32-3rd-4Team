"""
tests/test_graph_flow.py

역할:
    graph/builder.py(5개 기능 라우터, 프로토타입)를 실제로 돌려서 시나리오별로
    검증한다.
    - 정상 케이스: 질문 -> 근거조항 포함된 답변까지 나오는지
    - 실패 케이스: MCP 호출이 아무 근거도 못 찾았을 때 knowledge_gap으로 잘 빠지는지 (무폴백 원칙)

    ★main.py는 더 이상 이 그래프를 부르지 않는다(계약 기준 graph/precheck_graph.py를
    부름) -- 그래서 여기서는 main.run()이 아니라 graph.builder.build_graph()를
    직접 돌린다. graph/precheck_graph.py 자체 테스트는 tests/test_precheck_graph.py.

    LLM(ChatOpenAI)과 실제 벡터DB는 monkeypatch로 대체한다 -- OPENAI_API_KEY나
    구축된 chroma_db가 없는 환경(팀원 로컬, CI)에서도 그래프 배선 자체가
    맞는지는 확인할 수 있어야 하기 때문이다.
"""

import graph.router as router_module
import nodes.judge_coverage as judge_module
import nodes.mcp_caller as mcp_caller_module
from graph.builder import build_graph


class _FakeLLM:
    def __init__(self, content):
        self._content = content

    def invoke(self, _prompt):
        return type("Response", (), {"content": self._content})()


def _run(user_query: str) -> dict:
    app = build_graph()
    initial_state = {
        "user_query": user_query,
        "matched_clauses": [],
        "similar_cases": [],
        "glossary_terms": [],
        "citations": [],
        "references": [],
        "needs_fallback": False,
    }
    return app.invoke(initial_state)


def test_graph_runs_and_includes_citations_on_success(monkeypatch):
    monkeypatch.setattr(router_module, "_get_llm", lambda: _FakeLLM('["policy_rag"]'))
    monkeypatch.setattr(judge_module, "_get_llm", lambda: _FakeLLM("보장됩니다. (제1조)"))
    monkeypatch.setattr(
        mcp_caller_module,
        "search_policy_clause",
        lambda *a, **k: [
            {"article_no": "제1조", "article_title": "보장", "content": "...", "generation": "3세대"}
        ],
    )

    result = _run("우울증(F32) 입원비 보장되나요?")

    assert "final_answer" in result
    assert result["needs_fallback"] is False
    assert result["citations"]


def test_graph_falls_back_when_nothing_found(monkeypatch):
    """무폴백 원칙: 근거를 하나도 못 찾으면 knowledge_gap으로 빠지고, LLM이 답을 지어내면 안 된다."""
    monkeypatch.setattr(router_module, "_get_llm", lambda: _FakeLLM('["policy_rag"]'))
    monkeypatch.setattr(mcp_caller_module, "search_policy_clause", lambda *a, **k: [])

    result = _run("이상한 질문입니다")

    assert result["needs_fallback"] is True
    assert result["citations"] == []
    assert "확인하지 못했습니다" in result["final_answer"]


# TODO: mcp_tools/* 실제 데이터(공공데이터 API, 청구DB, 용어사전) 연동 후
# 실제 OPENAI_API_KEY + 실제 벡터DB를 쓰는 별도의 통합 테스트 추가 (마킹해서 opt-in으로).
