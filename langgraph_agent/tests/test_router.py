"""
tests/test_router.py

역할:
    graph/router.py의 classify_intent 파싱 안전성을 검증한다.
    (json.loads("null") -> None 크래시, 위험한 기본값 없음)
"""

import graph.router as router_module


class _FakeLLM:
    def __init__(self, content):
        self._content = content

    def invoke(self, _prompt):
        return type("Response", (), {"content": self._content})()


def test_classify_intent_handles_json_null_without_crashing(monkeypatch):
    """LLM이 "null"이라고만 답해도(파싱하면 None) 죽으면 안 된다."""
    monkeypatch.setattr(router_module, "_get_llm", lambda: _FakeLLM("null"))

    intents = router_module.classify_intent("아무 질문")

    assert intents == []


def test_classify_intent_handles_non_list_json_without_crashing(monkeypatch):
    """LLM이 리스트가 아닌 JSON(dict, 숫자 등)을 줘도 죽으면 안 된다."""
    monkeypatch.setattr(router_module, "_get_llm", lambda: _FakeLLM('{"policy_rag": true}'))

    intents = router_module.classify_intent("아무 질문")

    assert intents == []


def test_classify_intent_no_default_fallback_on_parse_failure(monkeypatch):
    """분류 실패 시 policy_rag(가장 위험한 경로)로 임의 확정하지 않는다."""
    monkeypatch.setattr(router_module, "_get_llm", lambda: _FakeLLM("이건 JSON이 아님"))

    intents = router_module.classify_intent("아무 질문")

    assert intents == []
    assert "policy_rag" not in intents


def test_classify_intent_returns_valid_intents(monkeypatch):
    monkeypatch.setattr(
        router_module, "_get_llm", lambda: _FakeLLM('["policy_rag", "disease_lookup", "invalid_value"]')
    )

    intents = router_module.classify_intent("우울증 보장되나요")

    assert intents == ["policy_rag", "disease_lookup"]
