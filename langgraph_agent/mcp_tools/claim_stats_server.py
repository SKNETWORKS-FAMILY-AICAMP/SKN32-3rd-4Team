"""
mcp_tools/claim_stats_server.py

역할:
    기능2(청구승인율 통계), 기능3(유사 케이스 조회)을 MCP 도구로 노출.

의존성 (중요):
    이 도구는 과거 청구 데이터 DB가 필요하고, 특히 기능3은 연령대 등으로
    전처리된 카테고리 필드가 있어야 검색이 가능하다.
    이 전처리 작업은 데이터팀(다른 팀원) 담당 -- 스키마 확정 전까지는
    아래 함수들은 목업(mock) 데이터로 개발/테스트한다.

TODO:
    - 실제 청구 데이터 DB 연결 (스키마 확정 후)
    - 데이터팀에게 전처리된 카테고리 필드명 확인
"""


def get_approval_stats(insurer: str | None = None, disease_code: str | None = None) -> dict:
    """
    청구 승인율 통계 조회.

    Returns:
        {"approved": int, "total": int, "rejected": int}
    """
    # TODO: 실제 DB 쿼리로 교체
    return {"approved": 0, "total": 0, "rejected": 0, "_mock": True}


def search_similar_cases(
    disease_code: str | None = None,
    age_group: str | None = None,
    insurer: str | None = None,
    top_k: int = 5,
) -> list[dict]:
    """
    전처리된 카테고리(연령대 등) 기준으로 유사 청구 케이스 조회.

    Returns:
        [{"insurer": str, "disease_code": str, "age_group": str,
          "result": "approved"|"rejected", "note": str}, ...]
    """
    # TODO: 실제 DB 쿼리로 교체, 데이터팀 스키마 확정 후 연결
    return []
