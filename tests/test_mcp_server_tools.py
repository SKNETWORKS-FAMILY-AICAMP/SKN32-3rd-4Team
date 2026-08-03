"""app/mcp_server/tools.py -- 인증·scope·레이트리밋 배선 + REST와 같은 유스케이스를
부르는지 검증한다. FastMCP는 안 쓴다(순수 함수라 직접 호출 가능)."""

import pytest

from app.auth.agent_client import AgentClient, RateLimitErr, rate_limiter
from app.core.domain.insurance import Verdict
from app.core.domain.precheck_result import (
    AppliedPolicyInfo,
    CitationRef,
    CodeVerdict,
    EvidenceTier,
    PrecheckOutcome,
    ReasonCode,
)
from app.core.errors import ForbiddenErr, ValidationErr
from app.core.ports.precheck import ClauseRow, NotResolved, PolicyVersionRow
from app.mcp_server import tools


def _client(scopes=("precheck:read", "terms:read", "observations:write")):
    return AgentClient(
        agent_client_id="agent-1", name="테스트", api_key_hash="x",
        scopes=tuple(scopes), rate_limit_rpm=1000,
    )


@pytest.fixture(autouse=True)
def _reset_rate_limiter():
    rate_limiter._hits.clear()
    yield
    rate_limiter._hits.clear()


@pytest.fixture(autouse=True)
def _audit_calls(monkeypatch):
    """★실제 감사 로그 파일을 안 건드린다 -- record()를 수집용 페이크로 교체."""
    calls: list[dict] = []
    monkeypatch.setattr(tools.audit_log, "record", lambda **kw: calls.append(kw))
    return calls


# ── insurance_precheck ──────────────────────────────────────────────────


class _FakeGraph:
    def __init__(self, outcome):
        self._outcome = outcome
        self.calls = []

    def invoke(self, body):
        self.calls.append(body)
        return self._outcome, None


def test_insurance_precheck_scope_없으면_403(monkeypatch):
    client = _client(scopes=("terms:read",))  # precheck:read 없음
    with pytest.raises(ForbiddenErr):
        tools.insurance_precheck(
            client, insurer="삼성화재", enrolled_on="20200101", kcd_codes=["F32"]
        )


def test_insurance_precheck_그래프를_호출하고_dict로_변환한다(monkeypatch, _audit_calls):
    outcome = PrecheckOutcome(
        verdict=Verdict.NEEDS_DOCUMENTS,
        abstained=False,
        message="",
        applied_policy=AppliedPolicyInfo(
            insurer="삼성화재", product_name="실손의료비보험", sale_start="20170401",
        ),
        per_code=[
            CodeVerdict(
                code="F32",
                verdict=Verdict.NEEDS_DOCUMENTS,
                reason_code=ReasonCode.EXCEPTION_APPLIES,
                citations=(
                    CitationRef(
                        clause_id="c1", qualified_no="제4조", quote="본문",
                        tier=EvidenceTier.POLICY_CLAUSE,
                    ),
                ),
            )
        ],
        trace_id="abc123",
    )
    fake_graph = _FakeGraph(outcome)
    monkeypatch.setattr(tools, "_graph", lambda: fake_graph)

    result = tools.insurance_precheck(
        _client(), insurer="삼성화재", enrolled_on="20200101", kcd_codes=["F32"],
    )

    assert result["verdict"] == "needs_documents"
    assert result["trace_id"] == "abc123"
    assert result["per_code"][0]["citations"][0]["qualified_no"] == "제4조"
    assert len(fake_graph.calls) == 1
    assert fake_graph.calls[0].insurer == "삼성화재"

    assert len(_audit_calls) == 1
    assert _audit_calls[0]["agent_client_id"] == "agent-1"
    assert _audit_calls[0]["operation"] == "precheck"
    assert _audit_calls[0]["verdict"] == "needs_documents"
    assert _audit_calls[0]["trace_id"] == "abc123"


def test_insurance_precheck_레이트리밋_초과하면_RateLimitErr(monkeypatch):
    outcome = PrecheckOutcome(verdict=Verdict.NEEDS_EXPERT, abstained=True, trace_id="t")
    monkeypatch.setattr(tools, "_graph", lambda: _FakeGraph(outcome))
    client = AgentClient(
        agent_client_id="agent-1", name="x", api_key_hash="x",
        scopes=("precheck:read",), rate_limit_rpm=1,
    )
    tools.insurance_precheck(client, insurer="a", enrolled_on="20200101", kcd_codes=["F32"])
    with pytest.raises(RateLimitErr):
        tools.insurance_precheck(client, insurer="a", enrolled_on="20200101", kcd_codes=["F32"])


# ── policy_clause_search ─────────────────────────────────────────────────


class _FakePolicies:
    def __init__(self, resolved):
        self._resolved = resolved

    def load_versions(self):
        return []

    def resolve(self, **kwargs):
        return self._resolved


class _FakeClauses:
    def __init__(self, rows):
        self._rows = rows
        self.calls = []

    def search(self, sha256, query, *, limit=8):
        self.calls.append((sha256, query, limit))
        return self._rows[:limit]


def test_policy_clause_search_scope_없으면_403():
    client = _client(scopes=("precheck:read",))
    with pytest.raises(ForbiddenErr):
        tools.policy_clause_search(
            client, insurer="삼성화재", enrolled_on="20200101", query="자기부담금"
        )


def test_policy_clause_search_검색어_비면_ValidationErr():
    with pytest.raises(ValidationErr):
        tools.policy_clause_search(
            _client(), insurer="삼성화재", enrolled_on="20200101", query="   "
        )


def test_policy_clause_search_약관_확정_못하면_resolved_false(monkeypatch, _audit_calls):
    not_resolved = NotResolved(reason_code="no_version_at_date", message="확인 불가")
    monkeypatch.setattr(
        tools, "_deps", lambda: {"policies": _FakePolicies(not_resolved), "clauses": _FakeClauses([])}
    )
    result = tools.policy_clause_search(
        _client(), insurer="삼성화재", enrolled_on="99990101", query="자기부담금"
    )
    assert result["resolved"] is False
    assert result["reason_code"] == "no_version_at_date"
    assert result["results"] == []
    assert _audit_calls[0]["operation"] == "terms_search"
    assert _audit_calls[0]["verdict"] == "not_resolved"


def test_policy_clause_search_확정되면_조항_목록을_돌려준다(monkeypatch, _audit_calls):
    version = PolicyVersionRow(
        insurer="삼성화재", product_name="실손의료비보험", sale_start="20170401",
        sale_end="20210630", generation=3, generation_label="3세대",
        product_line="standard", sha256="a" * 64,
        date_confidence="exact", generation_confidence="exact",
    )
    rows = [
        ClauseRow(
            sha256="a" * 64, qualified_no="제9조", clause_no="9", section="본문",
            title="자기부담금", text="자기부담금은...", page_from=3, page_to=3,
            content_hash="h1",
        )
    ]
    fake_clauses = _FakeClauses(rows)
    monkeypatch.setattr(
        tools, "_deps", lambda: {"policies": _FakePolicies(version), "clauses": fake_clauses}
    )
    result = tools.policy_clause_search(
        _client(), insurer="삼성화재", enrolled_on="20200101", query="자기부담금"
    )
    assert result["resolved"] is True
    assert result["applied_policy"]["sha256"] == "a" * 64
    assert result["results"][0]["qualified_no"] == "제9조"
    assert fake_clauses.calls == [("a" * 64, "자기부담금", 8)]
    assert _audit_calls[0]["operation"] == "terms_search"
    assert _audit_calls[0]["verdict"] == "resolved"


# ── submit_case_observation ──────────────────────────────────────────────


def test_submit_case_observation_scope_없으면_403():
    client = _client(scopes=("precheck:read",))
    with pytest.raises(ForbiddenErr):
        tools.submit_case_observation(
            client, client_ref="c1", insurer="a", enrolled_on="20200101",
            kcd_codes=["F32"], outcome="approved", idempotency_key="k1",
        )


def test_submit_case_observation_idempotency_key_없으면_ValidationErr():
    with pytest.raises(ValidationErr):
        tools.submit_case_observation(
            _client(), client_ref="c1", insurer="a", enrolled_on="20200101",
            kcd_codes=["F32"], outcome="approved", idempotency_key="",
        )


def test_submit_case_observation_verification은_항상_unverified(monkeypatch, _audit_calls):
    calls = []

    class _FakeResult:
        stored = True
        duplicate = False
        idempotency_key = "k1"

    def fake_store(payload, **kwargs):
        calls.append(payload)
        return _FakeResult()

    monkeypatch.setattr("app.adapters.external_submission_store.store", fake_store)

    result = tools.submit_case_observation(
        _client(), client_ref="c1", insurer="삼성화재", enrolled_on="20200101",
        kcd_codes=["F32"], outcome="approved", idempotency_key="k1",
        precheck_trace_id="tr-9",
    )
    assert result["verification"] == "unverified"
    assert result["accepted"] is True
    assert calls[0]["client_ref"] == "c1"
    assert _audit_calls[0]["operation"] == "observations"
    assert _audit_calls[0]["verdict"] == "stored"
    assert _audit_calls[0]["trace_id"] == "tr-9"
