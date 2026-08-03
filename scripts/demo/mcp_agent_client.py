"""외부 에이전트가 MCP **도구**로 사전판정 서비스를 쓰는 걸 보여주는 데모
클라이언트 (06_계약_Agent.md §5).

REST 버전(`scripts/demo/agent_client.py`)과 같은 4단계를, REST 호출 대신
MCP 리소스/도구 호출로 그대로 보여준다 -- "에이전트가 도구로 쓴다"는 계약의
표현을 실제로 실행 가능한 코드로 남긴다.

    1. read_resource(insurance://support-manifest)   무엇을 지원하는지 확인
    2. call_tool(insurance_precheck)                  판정 요청
    3. 결과의 trace_id 를 든다
    4. call_tool(submit_case_observation)              나중에 실제 결과 보고

실행 (실제 MCP 서버를 subprocess로 띄워 stdio로 붙는다):
    python -m scripts.demo.mcp_agent_client --api-key <키> \\
        --insurer 삼성화재 --enrolled-on 20200301 --kcd F32

★REST 데모와 마찬가지로 각 단계 함수는 이미 연결된 `ClientSession`을 받는다
  -- 테스트가 실제 subprocess 대신 `mcp.shared.memory`의 인메모리 세션을
  끼워 넣을 수 있게 하기 위해서다(REST 데모가 `httpx.MockTransport`를 쓰는
  것과 같은 이유).
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


def _print_step(n: int, label: str) -> None:
    print(f"\n[{n}] {label}", file=sys.stderr)


def _unwrap_tool_result(result) -> dict:
    """`CallToolResult` -> JSON dict.

    ★`structuredContent`가 있으면 그걸 쓰고, 없으면 `content`의 텍스트를
      JSON으로 파싱한다 -- 우리 도구는 반환 타입을 `dict`로만 선언해서
      지금 SDK 버전에서는 구조화 출력이 안 채워지고 텍스트로 온다(실측
      확인함). 도구 타입 힌트가 더 정교해지면 구조화 쪽으로 자연히 넘어간다.
    """
    if result.isError:
        text = result.content[0].text if result.content else "알 수 없는 오류"
        raise RuntimeError(f"MCP 도구 호출 실패: {text}")
    structured = getattr(result, "structuredContent", None)
    if structured is not None:
        return structured
    for item in result.content:
        if getattr(item, "type", None) == "text":
            return json.loads(item.text)
    raise ValueError("도구 응답에서 JSON 페이로드를 찾지 못했습니다.")


def _unwrap_resource_result(result) -> dict:
    for item in result.contents:
        text = getattr(item, "text", None)
        if text is not None:
            return json.loads(text)
    raise ValueError("리소스 응답에서 JSON 페이로드를 찾지 못했습니다.")


def _default_idempotency_key(client_ref: str, precheck_result: dict, outcome: str) -> str:
    """REST 데모와 같은 규칙 -- 같은 보고를 재시도해도 같은 키가 나와야
    서버가 중복으로 알아본다."""
    raw = f"{client_ref}:{precheck_result.get('trace_id', '')}:{outcome}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


async def check_support(session: ClientSession) -> dict:
    _print_step(1, "insurance://support-manifest -- 무엇을 지원하는지 확인")
    result = await session.read_resource("insurance://support-manifest")
    manifest = _unwrap_resource_result(result)
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    if not manifest.get("total_policy_versions"):
        print(
            "⚠ 판정 가능한 약관이 0건입니다. 이 상태에서 판정을 요청하면 "
            "대부분 기권(needs_expert)으로 돌아옵니다 -- 그게 정상입니다.",
            file=sys.stderr,
        )
    return manifest


async def request_precheck(
    session: ClientSession,
    *,
    api_key: str,
    insurer: str,
    enrolled_on: str,
    kcd_codes: list[str],
    product_name: str | None = None,
    client_ref: str | None = None,
) -> dict:
    _print_step(2, "insurance_precheck 도구 호출 -- 판정 요청")
    result = await session.call_tool(
        "insurance_precheck",
        {
            "api_key": api_key,
            "insurer": insurer,
            "enrolled_on": enrolled_on,
            "kcd_codes": kcd_codes,
            "product_name": product_name,
            "client_ref": client_ref,
        },
    )
    outcome = _unwrap_tool_result(result)
    print(json.dumps(outcome, ensure_ascii=False, indent=2))
    return outcome


async def submit_observation(
    session: ClientSession,
    *,
    api_key: str,
    precheck_result: dict,
    client_ref: str,
    insurer: str,
    enrolled_on: str,
    kcd_codes: list[str],
    outcome: str,
    outcome_reason: str = "",
    idempotency_key: str | None = None,
) -> dict:
    """★이 보고는 판정 근거가 되지 않는다 -- 통계·사후검증 전용(계약 §5).
    ★`idempotency_key`는 필수다(계약 §4) -- 안 주면 자동 생성한다.
    """
    _print_step(4, "submit_case_observation 도구 호출 -- 나중에 실제 결과 보고")
    key = idempotency_key or _default_idempotency_key(client_ref, precheck_result, outcome)
    result = await session.call_tool(
        "submit_case_observation",
        {
            "api_key": api_key,
            "client_ref": client_ref,
            "insurer": insurer,
            "enrolled_on": enrolled_on,
            "kcd_codes": kcd_codes,
            "outcome": outcome,
            "outcome_reason": outcome_reason,
            "idempotency_key": key,
            "precheck_trace_id": precheck_result.get("trace_id"),
        },
    )
    observation = _unwrap_tool_result(result)
    print(json.dumps(observation, ensure_ascii=False, indent=2))
    return observation


async def run_with_session(
    session: ClientSession,
    *,
    api_key: str,
    insurer: str,
    enrolled_on: str,
    kcd_codes: list[str],
    product_name: str | None,
    client_ref: str,
    outcome: str | None,
    idempotency_key: str | None = None,
) -> dict:
    """세션이 이미 연결된 상태에서 4단계를 순서대로 돈다(테스트용 진입점)."""
    await session.initialize()

    manifest = await check_support(session)

    precheck_result = await request_precheck(
        session,
        api_key=api_key,
        insurer=insurer,
        enrolled_on=enrolled_on,
        kcd_codes=kcd_codes,
        product_name=product_name,
        client_ref=client_ref,
    )

    _print_step(3, "결과의 trace_id를 든다")
    trace_id = precheck_result.get("trace_id")
    print(f"trace_id = {trace_id!r}", file=sys.stderr)

    observation_result = None
    if outcome:
        observation_result = await submit_observation(
            session,
            api_key=api_key,
            precheck_result=precheck_result,
            client_ref=client_ref,
            insurer=insurer,
            enrolled_on=enrolled_on,
            kcd_codes=kcd_codes,
            outcome=outcome,
            idempotency_key=idempotency_key,
        )
    else:
        print(
            "\n(--outcome을 안 줘서 4단계(사례 보고)는 생략합니다. "
            "예: --outcome paid)",
            file=sys.stderr,
        )

    return {
        "manifest": manifest,
        "precheck_result": precheck_result,
        "observation_result": observation_result,
    }


async def run(
    *,
    api_key: str,
    insurer: str,
    enrolled_on: str,
    kcd_codes: list[str],
    product_name: str | None,
    client_ref: str,
    outcome: str | None,
    idempotency_key: str | None = None,
) -> dict:
    """실제 MCP 서버를 subprocess로 띄워 stdio로 붙은 뒤 4단계를 돈다."""
    params = StdioServerParameters(command=sys.executable, args=["-m", "app.mcp_server.server"])
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            return await run_with_session(
                session,
                api_key=api_key,
                insurer=insurer,
                enrolled_on=enrolled_on,
                kcd_codes=kcd_codes,
                product_name=product_name,
                client_ref=client_ref,
                outcome=outcome,
                idempotency_key=idempotency_key,
            )


def main() -> None:
    p = argparse.ArgumentParser(description="MCP 도구로 사전판정 API를 쓰는 데모 클라이언트")
    p.add_argument("--api-key", required=True)
    p.add_argument("--insurer", required=True)
    p.add_argument("--enrolled-on", required=True, help="YYYYMMDD")
    p.add_argument(
        "--kcd", dest="kcd_codes", action="append", required=True,
        help="질병기호. 여러 개 지정 가능 (--kcd F32 --kcd S72.0)",
    )
    p.add_argument("--product-name", default=None)
    p.add_argument("--client-ref", default="demo-mcp-client")
    p.add_argument(
        "--outcome", default=None,
        help="주면 4단계(사례 보고)까지 실행. 예: paid/denied/partial/pending",
    )
    p.add_argument(
        "--idempotency-key", default=None,
        help="4단계 보고의 Idempotency-Key(계약 §4 필수). 안 주면 자동 생성.",
    )
    args = p.parse_args()

    asyncio.run(
        run(
            api_key=args.api_key,
            insurer=args.insurer,
            enrolled_on=args.enrolled_on,
            kcd_codes=args.kcd_codes,
            product_name=args.product_name,
            client_ref=args.client_ref,
            outcome=args.outcome,
            idempotency_key=args.idempotency_key,
        )
    )


if __name__ == "__main__":
    main()
