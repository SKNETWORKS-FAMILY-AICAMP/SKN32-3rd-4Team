"""scripts/demo/agent_client.py -- 4단계 흐름(계약 06_계약_Agent.md §5)을
httpx.MockTransport로 실제 서버 없이 검증한다."""

import httpx

from scripts.demo import agent_client as demo

#: ★monkeypatch 전에 진짜 클래스를 한 번만 잡아둔다 -- 한 테스트에서
#:   _patched_client()를 두 번 부르면(예: idempotency_key 기본값/지정값 비교),
#:   두 번째 호출이 `httpx.Client`를 다시 읽을 경우 이미 첫 번째 패치로 바뀐
#:   가짜를 "진짜"로 착각해서 감싸버린다(그러면 두 번째 계측이 첫 번째
#:   calls 리스트로 새어 들어간다).
_REAL_HTTPX_CLIENT = httpx.Client


def _transport(calls: list):
    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, request.url.path, request.content, dict(request.headers)))
        if request.url.path == "/v1/support-manifest":
            return httpx.Response(200, json={"total_policy_versions": 1, "insurers": {}})
        if request.url.path == "/v1/prechecks":
            return httpx.Response(
                200,
                json={
                    "verdict": "needs_documents",
                    "abstained": False,
                    "trace_id": "trace-abc123",
                },
            )
        if request.url.path == "/v1/observations":
            return httpx.Response(
                202,
                json={"accepted": True, "stored": True, "verification": "unverified"},
            )
        return httpx.Response(404)

    return httpx.MockTransport(handler)


def _patched_client(monkeypatch, calls):
    """`httpx.Client(base_url=..., timeout=...)` 생성을 가로채 MockTransport를 끼운다."""

    def fake_client(*args, **kwargs):
        kwargs["transport"] = _transport(calls)
        return _REAL_HTTPX_CLIENT(*args, **kwargs)

    monkeypatch.setattr(demo.httpx, "Client", fake_client)


def test_outcome_없으면_3단계까지만_호출한다(monkeypatch):
    calls: list = []
    _patched_client(monkeypatch, calls)

    result = demo.run(
        base_url="http://test",
        insurer="삼성화재",
        enrolled_on="20200301",
        kcd_codes=["F32"],
        product_name=None,
        client_ref="demo-agent-client",
        outcome=None,
    )

    paths = [c[1] for c in calls]
    assert paths == ["/v1/support-manifest", "/v1/prechecks"]
    assert result["precheck_result"]["trace_id"] == "trace-abc123"
    assert result["observation_result"] is None


def test_outcome_있으면_4단계까지_호출하고_trace_id를_같이_보낸다(monkeypatch):
    calls: list = []
    _patched_client(monkeypatch, calls)

    result = demo.run(
        base_url="http://test",
        insurer="삼성화재",
        enrolled_on="20200301",
        kcd_codes=["F32"],
        product_name=None,
        client_ref="demo-agent-client",
        outcome="paid",
    )

    paths = [c[1] for c in calls]
    assert paths == ["/v1/support-manifest", "/v1/prechecks", "/v1/observations"]

    import json

    obs_body = json.loads(calls[2][2])
    assert obs_body["precheck_trace_id"] == "trace-abc123"
    assert obs_body["outcome"] == "paid"
    assert result["observation_result"]["verification"] == "unverified"

    #: ★계약 §4: 쓰기 요청엔 Idempotency-Key가 필수다.
    obs_headers = calls[2][3]
    assert obs_headers.get("idempotency-key")


def test_idempotency_key_안_주면_자동_생성하고_주면_그대로_쓴다(monkeypatch):
    calls: list = []
    _patched_client(monkeypatch, calls)

    demo.run(
        base_url="http://test",
        insurer="삼성화재",
        enrolled_on="20200301",
        kcd_codes=["F32"],
        product_name=None,
        client_ref="demo-agent-client",
        outcome="paid",
    )
    auto_key = calls[2][3]["idempotency-key"]
    assert auto_key  # 비어있지 않음

    calls2: list = []
    _patched_client(monkeypatch, calls2)
    demo.run(
        base_url="http://test",
        insurer="삼성화재",
        enrolled_on="20200301",
        kcd_codes=["F32"],
        product_name=None,
        client_ref="demo-agent-client",
        outcome="paid",
        idempotency_key="my-fixed-key",
    )
    assert calls2[2][3]["idempotency-key"] == "my-fixed-key"


def test_kcd_여러개_지정하면_그대로_전달된다(monkeypatch):
    calls: list = []
    _patched_client(monkeypatch, calls)

    demo.run(
        base_url="http://test",
        insurer="삼성화재",
        enrolled_on="20200301",
        kcd_codes=["F32", "S72.0"],
        product_name="실손의료비보험",
        client_ref="demo-agent-client",
        outcome=None,
    )

    import json

    precheck_body = json.loads(calls[1][2])
    assert precheck_body["kcd_codes"] == ["F32", "S72.0"]
    assert precheck_body["product_name"] == "실손의료비보험"
