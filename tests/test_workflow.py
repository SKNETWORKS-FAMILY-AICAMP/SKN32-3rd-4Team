"""LangGraph CS 티켓 워크플로 테스트 (결정론 — mock 분류, LLM 불필요).

분기 전부 검증: 유효→긴급→escalate / 유효→일반→assign / 미분류→manual_review.
무폴백 검증: 빈 입력→ValidationErr, LLM 실패→InfraError 전파.
규칙(rules) 단위 + 불변식(모든 카테고리 매핑).
"""

from __future__ import annotations

import pytest

from app.core.errors import ConfigError, InfraError, ValidationErr
from app.prompts.classifier import CATEGORIES, UNCLASSIFIED
from app.workflow import rules
from app.workflow.ticket_graph import run_ticket


def _fixed_chat(category: str):
    """분류 LLM을 특정 카테고리 문자열로 고정하는 mock."""

    def _chat(_prompt: str) -> str:
        return category

    return _chat


# --- 규칙(rules) 단위 -------------------------------------------------------
def test_priority_urgent_categories():
    assert rules.calculate_priority("불만") == "긴급"
    assert rules.calculate_priority("환불") == "긴급"


def test_priority_normal_categories():
    for c in ["결제", "상품문의", "교환", "배송", "칭찬"]:
        assert rules.calculate_priority(c) == "일반"


def test_priority_unknown_category_raises():
    # 무폴백: 유효 카테고리가 아닌 값을 조용히 '일반'으로 떨구지 않는다
    with pytest.raises(ConfigError):
        rules.calculate_priority("존재하지않는카테고리")
    with pytest.raises(ConfigError):
        rules.calculate_priority(UNCLASSIFIED)


def test_assign_team_mapping():
    assert rules.assign_team("결제") == "결제팀"
    assert rules.assign_team("배송") == "물류팀"
    assert rules.assign_team("상품문의") == "상품팀"
    assert rules.assign_team("칭찬") == "CS팀"


def test_category_and_team_mapping_are_exactly_equal():
    # 불변식: 유효 카테고리 집합 == 팀 매핑 키 집합(누락도, 오타 여분 키도 불가)
    assert set(CATEGORIES) == set(rules.TEAM_BY_CATEGORY)


def test_assign_team_unknown_category_raises():
    # 매핑 누락은 배포된 정책 불일치 → ConfigError(503)
    with pytest.raises(ConfigError):
        rules.assign_team("존재하지않는카테고리")


# --- 그래프 분기(mock 분류) -------------------------------------------------
def test_urgent_category_routes_to_escalate():
    state = run_ticket("환불해주세요 당장!", chat_complete=_fixed_chat("불만"))
    assert state["category"] == "불만"
    assert state["priority"] == "긴급"
    assert state["team"] == "CS팀"
    assert state["action"] == "escalate"


def test_normal_category_routes_to_assign():
    state = run_ticket("언제 배송되나요?", chat_complete=_fixed_chat("배송"))
    assert state["category"] == "배송"
    assert state["priority"] == "일반"
    assert state["team"] == "물류팀"
    assert state["action"] == "assign"


def test_refund_is_urgent_and_payment_team():
    state = run_ticket("환불 요청합니다", chat_complete=_fixed_chat("환불"))
    assert state["priority"] == "긴급"
    assert state["team"] == "결제팀"
    assert state["action"] == "escalate"


def test_unclassified_routes_to_manual_review_and_stops():
    # 허용 카테고리가 아닌 출력 → 미분류 → manual_review → END
    state = run_ticket("횡설수설", chat_complete=_fixed_chat("헛소리분류불가"))
    assert state["category"] == UNCLASSIFIED
    assert state["action"] == "manual_review"
    # 무폴백: priority/team으로 계속 진행하지 않았음을 증명
    assert "priority" not in state
    assert "team" not in state


# --- 무폴백: 예외 전파 ------------------------------------------------------
def test_empty_content_raises_validation_error():
    with pytest.raises(ValidationErr):
        run_ticket("   ", chat_complete=_fixed_chat("배송"))


def test_llm_failure_propagates():
    def _boom(_prompt: str) -> str:
        raise InfraError("LLM 서버에 연결할 수 없습니다.")

    with pytest.raises(InfraError):
        run_ticket("배송 문의", chat_complete=_boom)


# --- HTTP 계약 (/api/workflow/ticket) ---------------------------------------
def test_http_ticket_success(client, monkeypatch):
    # 분류 LLM을 고정해 결정론적으로 HTTP 성공 경로 검증
    from app.prompts import classifier

    monkeypatch.setattr(classifier, "_default_chat_complete", lambda _p: "배송")
    r = client.post("/api/workflow/ticket", json={"content": "언제 배송되나요?"})
    assert r.status_code == 200
    body = r.json()
    assert body["category"] == "배송"
    assert body["priority"] == "일반"
    assert body["team"] == "물류팀"
    assert body["action"] == "assign"


def test_http_ticket_blank_content_returns_422(client):
    # 빈/공백 입력 → 폴백 없이 422 (pydantic min_length / classify_one ValidationErr)
    assert client.post("/api/workflow/ticket", json={"content": ""}).status_code == 422
    assert client.post("/api/workflow/ticket", json={"content": "   "}).status_code == 422


def test_http_ticket_llm_failure_maps_503(client, monkeypatch):
    from app.prompts import classifier

    def _boom(_p: str) -> str:
        raise InfraError("LLM 서버에 연결할 수 없습니다.")

    monkeypatch.setattr(classifier, "_default_chat_complete", _boom)
    r = client.post("/api/workflow/ticket", json={"content": "배송 문의"})
    assert r.status_code == 503
    assert r.json()["error_code"] == "infra_error"
