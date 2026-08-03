"""외부 에이전트가 사전판정 API를 어떻게 쓰는지 보여주는 데모 클라이언트
(06_계약_Agent.md §5).

    1. GET  /v1/support-manifest      무엇을 지원하는지 확인
    2. POST /v1/prechecks             판정 요청
    3. 결과의 trace_id 를 든다
    4. POST /v1/observations          나중에 실제 결과 보고

실행:
    python -m scripts.demo.agent_client --insurer 삼성화재 --enrolled-on 20200301 --kcd F32

★A2A와 별개다(계약 §3, §5) -- 이건 REST를 그대로 부르는 평범한 HTTP 클라이언트다.
  "에이전트가 도구로 쓴다"를 MCP로도 보여주려면 이 파일과 나란히 MCP 클라이언트
  버전을 추가할 수 있다(계약이 언급만 하고 필수로 못박진 않음).

★인증: 지금 REST `/v1/prechecks` 라우터는 아직 `agent_client` 인증을 안 걸고
  있다(app/mcp_server 쪽 도구만 걸려 있음) -- 그래서 이 스크립트는 지금은
  Authorization 헤더 없이 호출한다. REST에도 인증이 붙으면 `--api-key`만
  추가하면 된다.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys

import httpx


def _print_step(n: int, label: str) -> None:
    print(f"\n[{n}] {label}", file=sys.stderr)


def check_support(client: httpx.Client) -> dict:
    _print_step(1, "GET /v1/support-manifest -- 무엇을 지원하는지 확인")
    resp = client.get("/v1/support-manifest")
    resp.raise_for_status()
    manifest = resp.json()
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    if not manifest.get("total_policy_versions"):
        print(
            "⚠ 판정 가능한 약관이 0건입니다. 이 상태에서 판정을 요청하면 "
            "대부분 기권(needs_expert)으로 돌아옵니다 -- 그게 정상입니다.",
            file=sys.stderr,
        )
    return manifest


def request_precheck(
    client: httpx.Client,
    *,
    insurer: str,
    enrolled_on: str,
    kcd_codes: list[str],
    product_name: str | None = None,
    client_ref: str | None = None,
) -> dict:
    _print_step(2, "POST /v1/prechecks -- 판정 요청")
    body = {
        "insurer": insurer,
        "enrolled_on": enrolled_on,
        "kcd_codes": kcd_codes,
        "product_name": product_name,
        "client_ref": client_ref,
    }
    resp = client.post("/v1/prechecks", json=body)
    resp.raise_for_status()
    result = resp.json()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return result


def _default_idempotency_key(client_ref: str, precheck_result: dict, outcome: str) -> str:
    """호출부가 안 주면 내용으로 만든다 -- 같은 보고를 재시도해도 같은 키가
    나와야 서버가 중복으로 알아본다(`external_submission_store.py`와 같은 원칙)."""
    raw = f"{client_ref}:{precheck_result.get('trace_id', '')}:{outcome}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def submit_observation(
    client: httpx.Client,
    *,
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

    ★`Idempotency-Key`는 필수다(계약 §4) -- 헤더로 보낸다.
    """
    _print_step(4, "POST /v1/observations -- 나중에 실제 결과 보고")
    key = idempotency_key or _default_idempotency_key(client_ref, precheck_result, outcome)
    body = {
        "client_ref": client_ref,
        "insurer": insurer,
        "enrolled_on": enrolled_on,
        "kcd_codes": kcd_codes,
        "outcome": outcome,
        "outcome_reason": outcome_reason,
        #: ★우리 판정과 대조할 수 있게 trace_id를 같이 보낸다.
        "precheck_trace_id": precheck_result.get("trace_id"),
    }
    resp = client.post("/v1/observations", json=body, headers={"Idempotency-Key": key})
    resp.raise_for_status()
    result = resp.json()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return result


def run(
    *,
    base_url: str,
    insurer: str,
    enrolled_on: str,
    kcd_codes: list[str],
    product_name: str | None,
    client_ref: str,
    outcome: str | None,
    idempotency_key: str | None = None,
) -> dict:
    """4단계를 순서대로 실행한다. 마지막 결과(들)를 dict로 돌려준다(테스트용)."""
    with httpx.Client(base_url=base_url, timeout=10.0) as client:
        manifest = check_support(client)

        precheck_result = request_precheck(
            client,
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
            observation_result = submit_observation(
                client,
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


def main() -> None:
    p = argparse.ArgumentParser(description="사전판정 API 데모 클라이언트")
    p.add_argument("--base-url", default="http://127.0.0.1:8000")
    p.add_argument("--insurer", required=True)
    p.add_argument("--enrolled-on", required=True, help="YYYYMMDD")
    p.add_argument(
        "--kcd", dest="kcd_codes", action="append", required=True,
        help="질병기호. 여러 개 지정 가능 (--kcd F32 --kcd S72.0)",
    )
    p.add_argument("--product-name", default=None)
    p.add_argument("--client-ref", default="demo-agent-client")
    p.add_argument(
        "--outcome", default=None,
        help="주면 4단계(사례 보고)까지 실행. 예: paid/denied/partial/pending",
    )
    p.add_argument(
        "--idempotency-key", default=None,
        help="4단계 보고의 Idempotency-Key(계약 §4 필수). 안 주면 자동 생성.",
    )
    args = p.parse_args()

    run(
        base_url=args.base_url,
        insurer=args.insurer,
        enrolled_on=args.enrolled_on,
        kcd_codes=args.kcd_codes,
        product_name=args.product_name,
        client_ref=args.client_ref,
        outcome=args.outcome,
        idempotency_key=args.idempotency_key,
    )


if __name__ == "__main__":
    main()
