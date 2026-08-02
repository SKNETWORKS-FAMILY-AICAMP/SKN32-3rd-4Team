"""
mcp_tools/mcp_server.py

역할:
    policy_rag_server / disease_code_server / claim_stats_server / glossary_server의
    함수들을 실제 MCP 서버 하나로 등록해서 띄우는 진입점.

    각 파일의 함수는 그대로 두고(이 파일에서 import만 함), 여기서만
    mcp.tool()로 등록한다 -- nodes/mcp_caller.py는 지금처럼 함수를 직접
    호출하는 방식을 그대로 쓰고, 이 서버는 "MCP Inspector 같은 도구로
    수동 테스트하고 싶을 때"용으로 별도로 띄운다.

실행:
    python -m mcp_tools.mcp_server

Swagger 같은 테스트 UI로 확인하려면 (Node.js 필요):
    npx @modelcontextprotocol/inspector python -m mcp_tools.mcp_server
    -> 브라우저가 열리고 도구 목록/입력폼/실행결과를 눈으로 확인 가능
"""

from fastmcp import FastMCP

from mcp_tools.policy_rag_server import search_policy_clause
from mcp_tools.disease_code_server import lookup_disease_code, lookup_disease_name
from mcp_tools.claim_stats_server import get_approval_stats, search_similar_cases
from mcp_tools.glossary_server import search_glossary

mcp = FastMCP("insurance-assistant-tools")

mcp.tool(search_policy_clause)
mcp.tool(lookup_disease_code)
mcp.tool(lookup_disease_name)
mcp.tool(get_approval_stats)
mcp.tool(search_similar_cases)
mcp.tool(search_glossary)

if __name__ == "__main__":
    mcp.run()