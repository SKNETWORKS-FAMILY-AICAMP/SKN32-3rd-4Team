"""
mcp_tools/disease_code_server.py

역할:
    기능4(질병명 <-> KCD 질병코드 매칭)를 MCP 도구로 노출.
    예: "우울증" 입력 -> "F32" 등 관련 코드 반환

데이터 출처:
    공공데이터포털(data.go.kr) "건강보험심사평가원_상병마스터" API 활용 예정.
    https://www.data.go.kr/data/15067467/fileData.do

TODO:
    - data.go.kr Open API 키 발급 후 실제 연동
    - 질병명 -> 코드는 완전 일치가 아니라 유사 검색이 필요할 수 있음
      (예: "우울증"이 F32, F33 등 여러 코드에 걸칠 수 있음)
"""


def lookup_disease_code(disease_name: str) -> list[dict]:
    """
    질병명으로 관련 KCD 코드를 조회.

    Returns:
        [{"code": "F32", "name": "우울 에피소드"}, ...]
        일치하는 코드가 없으면 빈 리스트.
    """
    # TODO: data.go.kr 상병마스터 API 연동
    return []


def lookup_disease_name(disease_code: str) -> str | None:
    """질병코드로 질병명 역조회. 존재하지 않는 코드면 None."""
    # TODO: 실제 API 연동
    return None
