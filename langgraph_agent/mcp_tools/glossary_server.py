"""
mcp_tools/glossary_server.py

역할:
    기능5(어려운 보험/의학 용어 설명)를 MCP 도구로 노출.
    약관에 나오는 전문용어(예: "본인부담금 상한제", "비급여")를 쉽게 설명.

구현 방향 (택1):
    (a) 자체 용어사전 DB/딕셔너리 구축해서 검색
    (b) LLM에게 직접 설명을 맡기고 이 서버는 통과만 시킴 (더 간단하지만
        일관성/정확성은 (a)가 더 보장됨)

TODO:
    - 용어사전 데이터 소스 결정 (자체 구축 vs LLM 직답)
    - (a)로 갈 경우 data/glossary.json 같은 파일 추가
"""


def search_glossary(term: str) -> dict | None:
    """
    용어 설명 조회.

    Returns:
        {"term": str, "definition": str, "related_terms": list[str]} 또는 None
    """
    # TODO: 용어사전 데이터 연동 결정 후 구현
    return None
