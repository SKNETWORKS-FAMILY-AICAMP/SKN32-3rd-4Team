"""
tests/test_mcp_tools.py

역할:
    각 mcp_tools/* 도구가 입력에 맞는 형식의 출력을 내는지 검증.
    아직 실제 데이터 연동 전(TODO 상태)이라 지금은 "함수가 죽지 않고
    올바른 타입을 반환하는지"만 확인하는 수준.

    실제 데이터 연동 후에는 케이스별(정상/빈 결과/잘못된 입력) 검증으로 보강.
"""

from mcp_tools.policy_rag_server import search_policy_clause
from mcp_tools.disease_code_server import lookup_disease_code
from mcp_tools.claim_stats_server import get_approval_stats


def test_disease_code_lookup_returns_list():
    result = lookup_disease_code("우울증")
    assert isinstance(result, list)


def test_approval_stats_returns_dict_with_expected_keys():
    result = get_approval_stats()
    assert "approved" in result
    assert "total" in result
    assert "rejected" in result


# NOTE: search_policy_clause는 실제 벡터DB가 구축된 이후에만 테스트 가능.
# 벡터DB 없는 환경(CI 등)에서는 아래 테스트를 skip 처리하거나 목업으로 대체할 것.
# def test_search_policy_clause_returns_list():
#     result = search_policy_clause("입원 보장", generation="3세대")
#     assert isinstance(result, list)
