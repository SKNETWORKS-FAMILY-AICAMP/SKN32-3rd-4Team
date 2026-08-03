"""
tests/test_mcp_caller.py

역할:
    nodes/mcp_caller.py의 오케스트레이션 로직(무폴백 판단, 부분 실패 처리,
    intent 실행 순서, claim_stats 목업 데이터 무시)을 실제 도구 호출 없이 검증한다.
    실제 mcp_tools.* 함수는 monkeypatch로 대체한다.
"""

import nodes.mcp_caller as mcp_caller


def _base_state(**overrides):
    state = {
        "user_query": "테스트 질문",
        "intent": [],
        "matched_clauses": [],
        "similar_cases": [],
        "glossary_terms": [],
        "citations": [],
        "needs_fallback": False,
    }
    state.update(overrides)
    return state


def test_no_result_triggers_fallback(monkeypatch):
    monkeypatch.setattr(mcp_caller, "search_policy_clause", lambda *a, **k: [])
    state = _base_state(intent=["policy_rag"])

    result = mcp_caller.mcp_caller_node(state)

    assert result["needs_fallback"] is True
    assert result["matched_clauses"] == []


def test_successful_result_does_not_fallback(monkeypatch):
    fake_clauses = [{"article_no": "제1조", "content": "..."}]
    monkeypatch.setattr(mcp_caller, "search_policy_clause", lambda *a, **k: fake_clauses)
    state = _base_state(intent=["policy_rag"])

    result = mcp_caller.mcp_caller_node(state)

    assert result["needs_fallback"] is False
    assert result["matched_clauses"] == fake_clauses


def test_one_intent_failing_does_not_block_others(monkeypatch):
    def boom(*a, **k):
        raise ValueError("bad input")

    fake_clauses = [{"article_no": "제1조", "content": "..."}]
    monkeypatch.setattr(mcp_caller, "lookup_disease_code", boom)
    monkeypatch.setattr(mcp_caller, "search_policy_clause", lambda *a, **k: fake_clauses)
    state = _base_state(intent=["disease_lookup", "policy_rag"])

    result = mcp_caller.mcp_caller_node(state)

    assert result["needs_fallback"] is False
    assert result["matched_clauses"] == fake_clauses
    assert "disease_lookup" in result["error"]


def test_mock_claim_stats_does_not_count_as_real_result(monkeypatch):
    monkeypatch.setattr(
        mcp_caller,
        "get_approval_stats",
        lambda *a, **k: {"approved": 0, "total": 0, "rejected": 0, "_mock": True},
    )
    state = _base_state(intent=["claim_stats"])

    result = mcp_caller.mcp_caller_node(state)

    assert result["needs_fallback"] is True


def test_ambiguous_disease_candidates_not_collapsed(monkeypatch):
    candidates = [{"code": "F32", "name": "우울 에피소드"}, {"code": "F33", "name": "재발성 우울장애"}]
    monkeypatch.setattr(mcp_caller, "lookup_disease_code", lambda *a, **k: candidates)
    state = _base_state(intent=["disease_lookup"], disease_name="우울증")

    result = mcp_caller.mcp_caller_node(state)

    assert result["needs_fallback"] is False
    assert result.get("disease_code") is None
    assert result["disease_candidates"] == candidates


def test_disease_name_enriches_policy_rag_query(monkeypatch):
    """disease_lookup이 먼저 이름을 찾아주면 policy_rag 검색어에 반영돼야 한다."""
    monkeypatch.setattr(
        mcp_caller, "lookup_disease_code", lambda *a, **k: [{"code": "F32", "name": "우울 에피소드"}]
    )

    captured_queries = []

    def fake_search(query, **kwargs):
        captured_queries.append(query)
        return [{"article_no": "제1조", "content": "..."}]

    monkeypatch.setattr(mcp_caller, "search_policy_clause", fake_search)
    state = _base_state(intent=["disease_lookup", "policy_rag"], user_query="이거 보장되나요?")

    result = mcp_caller.mcp_caller_node(state)

    assert result["disease_name"] == "우울 에피소드"
    assert "우울 에피소드" in captured_queries[0]


def test_policy_rag_empty_falls_back_even_if_disease_lookup_succeeds(monkeypatch):
    """"우울증 보장되나요?" 같은 질문 -- disease_lookup은 성공, policy_rag는 0건인 경우
    policy_rag가 보장판단의 유일한 근거라서, 다른 intent 성공만으로 통과되면 안 된다."""
    monkeypatch.setattr(
        mcp_caller, "lookup_disease_code", lambda *a, **k: [{"code": "F32", "name": "우울 에피소드"}]
    )
    monkeypatch.setattr(mcp_caller, "search_policy_clause", lambda *a, **k: [])
    state = _base_state(intent=["disease_lookup", "policy_rag"], user_query="우울증 보장되나요?")

    result = mcp_caller.mcp_caller_node(state)

    assert result["needs_fallback"] is True
    assert result["matched_clauses"] == []


def test_timeout_is_retried_then_succeeds(monkeypatch):
    calls = {"count": 0}

    def flaky(*a, **k):
        calls["count"] += 1
        if calls["count"] == 1:
            raise TimeoutError("simulated transient timeout")
        return [{"article_no": "제1조", "content": "..."}]

    monkeypatch.setattr(mcp_caller, "search_policy_clause", flaky)
    state = _base_state(intent=["policy_rag"])

    result = mcp_caller.mcp_caller_node(state)

    assert calls["count"] == 2
    assert result["needs_fallback"] is False