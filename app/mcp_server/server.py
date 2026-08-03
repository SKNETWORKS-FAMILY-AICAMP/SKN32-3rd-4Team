"""MCP 서버 조립 — 도구 3개 + 리소스 2개 등록 (06_계약_Agent.md §2).

실행:
    python -m app.mcp_server.server

★인증을 FastMCP 내장 OAuth 흐름에 태우지 않는다.

    FastMCP(`mcp[cli]`)의 `token_verifier`/`AuthSettings`는 `issuer_url`·
    `resource_server_url`이 **필수**다 -- OAuth 인가서버가 있다는 걸 전제한다.
    우리는 그런 서버가 없다. `agent_client`는 사전 발급한 API 키 하나를
    해시로 대조하는 단순한 모델이라(계약 §4), 안 맞는 틀에 억지로 끼우면
    설정만 복잡해지고 실제로는 아무것도 검증 안 하는 상태가 되기 쉽다.

    대신 각 도구가 **`api_key`를 인자로 받는다.** 호출부(`app/mcp_server/tools.py`)
    로 넘기기 전에 여기서 `agent_client.authenticate()`로 확인한다. 인증 실패는
    `AppError`(401/403/429)를 그대로 던지고, MCP 클라이언트는 도구 호출 에러로
    받는다 -- 조용히 통과시키지 않는다.
"""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from app.auth import agent_client as ac
from app.mcp_server import resources as res
from app.mcp_server import tools

mcp = FastMCP("insurance-precheck-agent")


def _authed(api_key: str) -> ac.AgentClient:
    return ac.authenticate(f"Bearer {api_key}")


@mcp.tool()
def insurance_precheck(
    api_key: str,
    insurer: str,
    enrolled_on: str,
    kcd_codes: list[str],
    product_name: str | None = None,
    client_ref: str | None = None,
) -> dict:
    """가입일·질병기호로 보장 여부를 미리 본다. scope: `precheck:read`."""
    client = _authed(api_key)
    return tools.insurance_precheck(
        client,
        insurer=insurer,
        enrolled_on=enrolled_on,
        kcd_codes=kcd_codes,
        product_name=product_name,
        client_ref=client_ref,
    )


@mcp.tool()
def policy_clause_search(
    api_key: str,
    insurer: str,
    enrolled_on: str,
    query: str,
    product_name: str | None = None,
    limit: int = 8,
    client_ref: str | None = None,
) -> dict:
    """약관 조항을 찾는다(확정된 버전 안에서만). scope: `terms:read`."""
    client = _authed(api_key)
    return tools.policy_clause_search(
        client,
        insurer=insurer,
        enrolled_on=enrolled_on,
        query=query,
        product_name=product_name,
        limit=limit,
        client_ref=client_ref,
    )


@mcp.tool()
def submit_case_observation(
    api_key: str,
    client_ref: str,
    insurer: str,
    enrolled_on: str,
    kcd_codes: list[str],
    outcome: str,
    idempotency_key: str,
    outcome_reason: str = "",
    precheck_trace_id: str | None = None,
) -> dict:
    """실제 청구 결과를 보고한다(판정 근거로 쓰이지 않음). scope: `observations:write`."""
    client = _authed(api_key)
    return tools.submit_case_observation(
        client,
        client_ref=client_ref,
        insurer=insurer,
        enrolled_on=enrolled_on,
        kcd_codes=kcd_codes,
        outcome=outcome,
        idempotency_key=idempotency_key,
        outcome_reason=outcome_reason,
        precheck_trace_id=precheck_trace_id,
    )


@mcp.resource("insurance://support-manifest")
def support_manifest() -> dict:
    """무엇을 지원하는지 -- 인증 없이도 볼 수 있다(공개 정보)."""
    return res.support_manifest()


@mcp.resource("insurance://schemas/precheck-v1")
def precheck_schema_v1() -> dict:
    """`PrecheckResult` 응답 스키마."""
    return res.precheck_schema_v1()


if __name__ == "__main__":
    mcp.run()
