"""MCP 도구 3개의 실제 로직 (06_계약_Agent.md §2).

★MCP는 어댑터, REST가 정본 — **같은 유스케이스를 부른다.**

    이 파일은 `app/routers/precheck.py`(REST, 정본)가 부르는 것과 같은
    그래프·어댑터를 그대로 부른다. 로직을 두 벌 만들면 REST와 MCP 응답이
    갈라진다(Phase 8 parity 원칙과 같은 이유).

★이 모듈은 FastMCP를 모른다.

    도구 등록(`@mcp.tool()`)은 `server.py`가 한다. 여기는 순수 함수라
    FastMCP 없이도 이 파일만으로 단위 테스트할 수 있다.

★인증은 호출부(server.py)가 이미 확인한 `AgentClient`를 받는다.

    각 함수 안에서 `require_scope`로 scope를, `rate_limiter.check`로
    레이트리밋을 강제한다 — 도구 함수를 직접 호출해도(테스트 등) 안전장치가
    빠지지 않는다.
"""

from __future__ import annotations

import hashlib
import time

from app.adapters import audit_log
from app.auth.agent_client import AgentClient, rate_limiter, require_scope
from app.core.domain.precheck_result import (
    AppliedPolicyInfo,
    CitationRef,
    CodeVerdict,
    PrecheckInput,
    PrecheckOutcome,
)
from app.core.errors import ValidationErr
from app.core.ports.precheck import ClauseRow, NotResolved, PolicyVersionRow

_graph_cache = None
_deps_cache = None


def _graph():
    """★요청마다 다시 조립하지 않는다 -- REST 라우터와 같은 캐시 패턴."""
    global _graph_cache
    if _graph_cache is None:
        from app.workflow.precheck_graph import build

        _graph_cache = build()
    return _graph_cache


def _deps():
    global _deps_cache
    if _deps_cache is None:
        from app.composition import build_precheck

        _deps_cache = build_precheck()
    return _deps_cache


def _subject_hash(client_ref: str | None) -> str:
    """레이트리밋 버킷 키용. ★client_ref 원문 대신 해시를 쓴다 -- 감사 로그
    원칙(06_계약_Agent.md §4: "원문 대신 해시")과 같다."""
    if not client_ref:
        return "anonymous"
    return hashlib.sha256(client_ref.strip().encode("utf-8")).hexdigest()[:16]


def _policy_to_dict(p: AppliedPolicyInfo | PolicyVersionRow) -> dict:
    return {
        "insurer": p.insurer,
        "product_name": p.product_name,
        "sale_start": p.sale_start,
        "sale_end": p.sale_end,
        "generation": p.generation,
        "generation_label": p.generation_label,
        "product_line": p.product_line,
        "sha256": p.sha256,
        "date_confidence": p.date_confidence,
        "generation_confidence": p.generation_confidence,
        #: PolicyVersionRow에는 parse_status가 없어서(문서 단위 개념이라
        #: 조항 조회 후에나 안다) 없으면 빈 문자열.
        "parse_status": getattr(p, "parse_status", ""),
    }


def _citation_to_dict(c: CitationRef) -> dict:
    return {
        "clause_id": c.clause_id,
        "qualified_no": c.qualified_no,
        "section": c.section,
        "title": c.title,
        "quote": c.quote,
        "page_from": c.page_from,
        "page_to": c.page_to,
        "tier": c.tier.value,
    }


def _code_verdict_to_dict(v: CodeVerdict) -> dict:
    return {
        "code": v.code,
        "verdict": v.verdict.value,
        "reason_code": v.reason_code.value if v.reason_code else None,
        "citations": [_citation_to_dict(c) for c in v.citations],
        "note": v.note,
    }


def outcome_to_dict(o: PrecheckOutcome) -> dict:
    """`PrecheckOutcome` -> MCP 응답용 순수 dict.

    ★REST 라우터의 `_to_dto`와 같은 필드를 낸다 -- pydantic이 아니라 dict인
    것만 다르다. 필드가 갈리면 REST/MCP parity가 깨진다.
    """
    return {
        "verdict": o.verdict.value,
        "abstained": o.abstained,
        "reason_code": o.reason_code.value if o.reason_code else None,
        "message": o.message,
        "applied_policy": _policy_to_dict(o.applied_policy) if o.applied_policy else None,
        "per_code": [_code_verdict_to_dict(v) for v in o.per_code],
        "citations": [_citation_to_dict(c) for c in o.citations],
        "candidates": [_policy_to_dict(c) for c in o.candidates],
        "rule_engine_version": o.rule_engine_version,
        "extractor": o.extractor,
        "trace_id": o.trace_id,
        "warnings": list(o.warnings),
    }


def insurance_precheck(
    client: AgentClient,
    *,
    insurer: str,
    enrolled_on: str,
    kcd_codes: list[str],
    product_name: str | None = None,
    client_ref: str | None = None,
) -> dict:
    """대응 REST: `POST /v1/prechecks`. scope: `precheck:read`.

    ★근거를 못 대면 `verdict="needs_expert"`로 답한다 -- 이건 오류가 아니라
      정상 결과다(계약 §1). 예외를 던지지 않는다.
    """
    require_scope(client, "precheck:read")
    rate_limiter.check(client, subject_hash=_subject_hash(client_ref), operation="precheck")

    started = time.perf_counter()
    body = PrecheckInput(
        insurer=insurer,
        enrolled_on=enrolled_on,
        kcd_codes=tuple(kcd_codes),
        product_name=product_name,
        client_ref=client_ref,
    )
    #: ★흐름은 그래프가 소유한다 -- REST 라우터와 똑같이, 이 함수가 유스케이스를
    #:   직접 부르지 않는다(같은 판단이 두 곳에 생기는 것을 막는다).
    outcome, _state = _graph().invoke(body)
    audit_log.record(
        agent_client_id=client.agent_client_id,
        operation="precheck",
        trace_id=outcome.trace_id,
        verdict=outcome.verdict.value,
        latency_ms=(time.perf_counter() - started) * 1000,
    )
    return outcome_to_dict(outcome)


def policy_clause_search(
    client: AgentClient,
    *,
    insurer: str,
    enrolled_on: str,
    query: str,
    product_name: str | None = None,
    limit: int = 8,
    client_ref: str | None = None,
) -> dict:
    """대응 REST: `POST /v1/terms/search`. scope: `terms:read`.

    ★약관 원문 전체를 리소스로 공개하지 않는다(계약 §2) -- 검색 결과로
      조항 단위만 돌려준다. 검색 범위도 확정된 약관 버전 하나로 가둔다
      (`file_clause_store.py`와 같은 이유 -- 안 그러면 다른 세대 조항이 섞인다).
    """
    require_scope(client, "terms:read")
    rate_limiter.check(client, subject_hash=_subject_hash(client_ref), operation="terms_search")

    if not query or not query.strip():
        raise ValidationErr("검색어가 비어 있습니다.")

    started = time.perf_counter()
    deps = _deps()
    versions = deps["policies"].load_versions()
    resolved = deps["policies"].resolve(
        insurer=insurer, enrolled_on=enrolled_on, product_name=product_name, versions=versions
    )
    if isinstance(resolved, NotResolved):
        audit_log.record(
            agent_client_id=client.agent_client_id,
            operation="terms_search",
            verdict="not_resolved",
            latency_ms=(time.perf_counter() - started) * 1000,
        )
        return {
            "resolved": False,
            "reason_code": resolved.reason_code,
            "message": resolved.message,
            "candidates": [_policy_to_dict(c) for c in resolved.candidates],
            "results": [],
        }

    hits: list[ClauseRow] = deps["clauses"].search(resolved.sha256, query, limit=limit)
    audit_log.record(
        agent_client_id=client.agent_client_id,
        operation="terms_search",
        verdict="resolved",
        latency_ms=(time.perf_counter() - started) * 1000,
    )
    return {
        "resolved": True,
        "applied_policy": _policy_to_dict(resolved),
        "results": [
            {
                "clause_id": c.clause_id,
                "qualified_no": c.qualified_no,
                "clause_no": c.clause_no,
                "section": c.section,
                "title": c.title,
                "text": c.text,
                "page_from": c.page_from,
                "page_to": c.page_to,
            }
            for c in hits
        ],
    }


def submit_case_observation(
    client: AgentClient,
    *,
    client_ref: str,
    insurer: str,
    enrolled_on: str,
    kcd_codes: list[str],
    outcome: str,
    idempotency_key: str,
    outcome_reason: str = "",
    precheck_trace_id: str | None = None,
) -> dict:
    """대응 REST: `POST /v1/observations`. scope: `observations:write`.

    ★이 데이터는 판정 근거가 되지 않는다 -- 통계·사후검증 전용(계약 §5).
    ★`Idempotency-Key`는 필수다(계약 §4) -- 없으면 422.
    ★`verification`은 항상 `"unverified"`로 고정 -- 클라이언트가 뭐라
      주장해도 우리가 검증한 게 아니다.
    """
    require_scope(client, "observations:write")
    rate_limiter.check(
        client, subject_hash=_subject_hash(client_ref), operation="observations"
    )

    if not idempotency_key or not idempotency_key.strip():
        raise ValidationErr("Idempotency-Key가 필요합니다.")

    from app.adapters import external_submission_store as store

    started = time.perf_counter()
    payload = {
        "client_ref": client_ref,
        "insurer": insurer,
        "enrolled_on": enrolled_on,
        "kcd_codes": list(kcd_codes),
        "outcome": outcome,
        "outcome_reason": outcome_reason,
        "precheck_trace_id": precheck_trace_id,
        "idempotency_key": idempotency_key,
    }
    res = store.store(payload)
    audit_log.record(
        agent_client_id=client.agent_client_id,
        operation="observations",
        trace_id=precheck_trace_id or "",
        verdict="duplicate" if res.duplicate else "stored",
        latency_ms=(time.perf_counter() - started) * 1000,
    )
    return {
        "accepted": True,
        "stored": res.stored,
        "duplicate": res.duplicate,
        "idempotency_key": res.idempotency_key,
        "verification": "unverified",
    }
