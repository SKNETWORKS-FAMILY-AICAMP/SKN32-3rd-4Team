"""
mcp_tools/policy_rag_server.py

역할:
    기능1(약관 RAG)을 MCP 도구로 노출하는 서버.
    실제 검색 로직은 rag/search_policy.py에 있고, 여기서는 MCP 프로토콜에
    맞춰 도구로 등록만 한다.

    이렇게 rag/ 와 분리해두면, 벡터DB를 나중에 다른 걸로 바꾸거나
    검색 로직을 수정해도 이 MCP 인터페이스 자체는 안 건드려도 된다.

TODO: FastMCP로 실제 서버 등록 (예시)
    from fastmcp import FastMCP
    mcp = FastMCP("policy-rag")

    @mcp.tool()
    def search_policy_clause(query: str, generation: str = None) -> list[dict]:
        ...
"""

from rag.search_policy import search_policy_clause as _search_policy_clause


def search_policy_clause(query: str, generation: str | None = None) -> list[dict]:
    """MCP 도구로 노출될 함수. 내부적으로 rag.search_policy를 그대로 호출."""
    return _search_policy_clause(query, generation=generation)
