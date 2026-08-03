"""MCP 리소스 2개 (06_계약_Agent.md §2).

    insurance://support-manifest      무엇을 지원하는지
    insurance://schemas/precheck-v1   응답 스키마

★약관 원문 전체는 여기 안 올린다 -- 저작물이다(계약 §2).

이 모듈도 FastMCP를 모른다 -- 등록은 `server.py`가 한다.
"""

from __future__ import annotations


def support_manifest() -> dict:
    """**무엇을 지원하는지** 밝힌다. REST `GET /v1/support-manifest`와 같은 로직.

    ★"전부 지원"이라고 말하지 않는다 -- 판정에 쓸 수 있는 것만 센다.
      클라이언트가 기대를 잘못 세우면 없는 보험사를 계속 물어보게 된다.
    """
    from app.composition import build_precheck
    from app.core.ports.precheck import REQUIRE_CONFIRMED
    from app.core.usecases import precheck

    versions = build_precheck()["policies"].load_versions()

    by_insurer: dict[str, dict] = {}
    for v in versions:
        d = by_insurer.setdefault(
            v.insurer,
            {"versions": 0, "generations": set(), "lines": set(), "earliest": "", "latest": ""},
        )
        d["versions"] += 1
        if v.generation:
            d["generations"].add(v.generation)
        if v.product_line:
            d["lines"].add(v.product_line)
        if not d["earliest"] or v.sale_start < d["earliest"]:
            d["earliest"] = v.sale_start
        if v.sale_start > d["latest"]:
            d["latest"] = v.sale_start

    notes = [
        "판정은 약관 원문 조항만을 근거로 한다.",
        "근거를 못 대면 verdict=needs_expert 로 기권한다(HTTP 200).",
        "면책 목록에 없다는 것이 보장된다는 뜻은 아니다.",
    ]
    if not REQUIRE_CONFIRMED:
        notes.insert(
            0,
            "⚠ 확정 게이트가 꺼져 있습니다(PRECHECK_ALLOW_UNCONFIRMED=1). "
            "식별이 확정되지 않은 약관도 판정에 쓰고 있습니다 -- 시연용입니다.",
        )
    elif not versions:
        notes.insert(
            0,
            "⚠ 판정 가능한 약관이 0건입니다. 확인 안 된 약관으로 "
            "보장 여부를 답하지 않습니다.",
        )

    return {
        "schema_version": "v1",
        "rule_engine_version": precheck.RULE_ENGINE_VERSION,
        "require_confirmed_documents": REQUIRE_CONFIRMED,
        "total_policy_versions": len(versions),
        "insurers": {
            k: {
                "versions": d["versions"],
                "generations": sorted(d["generations"]),
                "product_lines": sorted(d["lines"]),
                "sale_start_range": [d["earliest"], d["latest"]],
            }
            for k, d in sorted(by_insurer.items())
        },
        "notes": notes,
        "tools": ["insurance_precheck", "policy_clause_search", "submit_case_observation"],
    }


#: ★손으로 관리한다 -- `app/core/domain/precheck_result.py`의 필드가 바뀌면
#:   `app/mcp_server/tools.py::outcome_to_dict`와 이 스키마 둘 다 고쳐야 한다.
#:   자동 생성(예: dataclass -> JSON Schema)은 나중에 붙일 수 있지만,
#:   지금은 필드 수가 적어 손으로 맞추는 편이 더 명확하다.
PRECHECK_RESULT_SCHEMA_V1: dict = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": "PrecheckResult",
    "type": "object",
    "required": ["verdict", "abstained", "message", "trace_id"],
    "properties": {
        "verdict": {
            "type": "string",
            "enum": ["likely_covered", "unlikely", "needs_documents", "needs_expert"],
        },
        "abstained": {"type": "boolean"},
        "reason_code": {"type": ["string", "null"]},
        "message": {"type": "string"},
        "applied_policy": {"type": ["object", "null"]},
        "per_code": {"type": "array"},
        "citations": {"type": "array"},
        "candidates": {"type": "array"},
        "rule_engine_version": {"type": "string"},
        "extractor": {"type": "string"},
        "trace_id": {"type": "string"},
        "warnings": {"type": "array", "items": {"type": "string"}},
    },
}


def precheck_schema_v1() -> dict:
    return PRECHECK_RESULT_SCHEMA_V1
