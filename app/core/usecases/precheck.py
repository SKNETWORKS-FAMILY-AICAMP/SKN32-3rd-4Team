"""보장 사전판정 파이프라인.

★단계

    1. resolve_policy   가입일 → 적용 약관 확정      못 하면 → abstain
    2. gate_document    그 문서가 판정에 쓸 만한가    아니면 → abstain
    3. retrieve         면책·보상 조항에서 코드 범위 수집
    4. assess           코드별 판정(규칙 기반)
    5. build_citations  근거 조항을 원문 위치까지 붙임

★이 모듈은 **프레임워크도 바깥 계층도 모른다**(클린아키텍처 2단계 안쪽).

    파일을 읽지 않는다. 필요한 것은 **포트로 주입받는다.**
    `policies` 는 `PolicyVersionSourcePort`, `clauses` 는 `ClauseSourcePort` 다.
    구현은 `app/adapters/` 가 한다.

★지금은 **LLM 이 없다.** 규칙만으로 판정한다.

    이유는 두 가지다.
      · 약관이 KCD 코드를 직접 쓰므로 규칙으로 답이 나온다(실측 80% 문서)
      · 규칙 판정이 먼저 서야 LLM 답을 **대조**할 수 있다
    LLM 은 설명문 생성과 애매한 사례에 붙이고, 그때 `citation_guard` 로 검증한다.

★`covered` 를 함부로 내지 않는다

    면책 목록에 없다 = 보장된다, 가 아니다. 보장은 '보상하는 사항' 조항이 정한다.
    지금 단계에서 확실히 말할 수 있는 것은 **면책 여부**뿐이므로,
    면책이 아니면 `unknown`(근거 부족)으로 둔다.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict

from app.core.errors import ValidationErr
from app.core.domain import kcd_ranges as kcd
from app.core.ports.precheck import (
    ClauseRow,
    ClauseSourcePort,
    NotResolved,
    PolicyVersionRow,
    PolicyVersionSourcePort,
)
from app.core.domain.insurance import Verdict
from app.schemas.precheck import (
    AppliedPolicy,
    Citation,
    CodeAssessment,
    EvidenceTier,
    PrecheckRequest,
    PrecheckResult,
    ReasonCode,
)

RULE_ENGINE_VERSION = "rules-2026.08.02"

#: 판정 근거로 쓸 수 있는 문서 상태. ★`suspect` 는 쓰지 않는다.
_USABLE_PARSE_STATUS = {"ok"}


def _trace_id(req: PrecheckRequest) -> str:
    """같은 요청이면 같은 값. 감사·재현에 쓴다."""
    raw = json.dumps(
        {
            "i": req.insurer,
            "d": req.enrolled_on,
            "c": sorted(req.kcd_codes),
            "p": req.product_name or "",
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def _to_applied(v: PolicyVersionRow, parse_status: str = "") -> AppliedPolicy:
    return AppliedPolicy(
        insurer=v.insurer,
        product_name=v.product_name,
        sale_start=v.sale_start,
        sale_end=v.sale_end,
        generation=v.generation,
        generation_label=v.generation_label,
        product_line=v.product_line,
        sha256=v.sha256,
        date_confidence=v.date_confidence,
        generation_confidence=v.generation_confidence,
        parse_status=parse_status,
    )


_REASON_MAP = {
    "insurer_not_supported": ReasonCode.INSURER_NOT_SUPPORTED,
    "no_version_at_date": ReasonCode.NO_VERSION_AT_DATE,
    "ambiguous_product": ReasonCode.AMBIGUOUS_PRODUCT,
    "ambiguous_product_line": ReasonCode.AMBIGUOUS_PRODUCT_LINE,
}


def run(
    req: PrecheckRequest,
    *,
    policies: PolicyVersionSourcePort,
    clauses: ClauseSourcePort,
    versions: list[PolicyVersionRow] | None = None,
) -> PrecheckResult:
    """사전판정 한 건.

    Args:
        policies: 약관 버전 출처(포트). 어댑터가 주입한다.
        clauses: 조항 출처(포트).
        versions: 미리 읽어 둔 목록(성능·테스트용).
    """
    if not req.kcd_codes:
        raise ValidationErr("질병기호가 비어 있습니다.")
    trace = _trace_id(req)
    base = {
        "rule_engine_version": RULE_ENGINE_VERSION,
        "trace_id": trace,
    }

    # ── 1) 적용 약관 확정 ────────────────────────────────────────
    pool = versions if versions is not None else policies.load_versions()
    got = policies.resolve(
        insurer=req.insurer,
        enrolled_on=req.enrolled_on,
        product_name=req.product_name,
        versions=pool,
    )
    if isinstance(got, NotResolved):
        #: ★현행 약관으로 때우지 않는다. 못 정하면 못 정했다고 답한다.
        return PrecheckResult(
            verdict=Verdict.NEEDS_EXPERT,
            abstained=True,
            reason_code=_REASON_MAP.get(got.reason_code),
            message=got.message,
            candidates=[_to_applied(c) for c in got.candidates],
            **base,
        )

    # ── 2) 그 문서를 판정에 쓸 수 있나 ────────────────────────────
    try:
        st = clauses.stats(got.sha256)
    except Exception as e:  # noqa: BLE001
        return PrecheckResult(
            verdict=Verdict.NEEDS_EXPERT,
            abstained=True,
            reason_code=ReasonCode.NO_EVIDENCE,
            message=f"조항 데이터를 찾지 못했습니다: {e}",
            applied_policy=_to_applied(got),
            **base,
        )

    applied = _to_applied(got, st["parse_status"])
    if st["parse_status"] not in _USABLE_PARSE_STATUS:
        #: ★구조화가 미심쩍은 문서로 "보장됩니다"라고 말하지 않는다.
        return PrecheckResult(
            verdict=Verdict.NEEDS_EXPERT,
            abstained=True,
            reason_code=ReasonCode.DOCUMENT_NOT_RELIABLE,
            message=(
                f"이 약관은 조항 구조화 상태가 '{st['parse_status']}' 라 "
                "근거를 정확히 대기 어렵습니다. 사람이 확인해야 합니다."
            ),
            applied_policy=applied,
            **base,
        )

    # ── 3) 코드 언급 수집 ────────────────────────────────────────
    found = clauses.load_clauses(got.sha256)
    mentions: list[tuple[kcd.CodeMention, ClauseRow]] = []
    for c in found:
        for m in kcd.scan_clause(c.text):
            mentions.append((m, c))
    if not mentions:
        return PrecheckResult(
            verdict=Verdict.NEEDS_EXPERT,
            abstained=True,
            reason_code=ReasonCode.NO_EVIDENCE,
            message="이 약관에서 질병기호로 적힌 조항을 찾지 못했습니다.",
            applied_policy=applied,
            **base,
        )

    # ── 4) 코드별 판정 ──────────────────────────────────────────
    per_code: list[CodeAssessment] = []
    all_cites: list[Citation] = []
    for code in req.kcd_codes:
        judged = kcd.judge(code, [m for m, _ in mentions])
        if judged["status"] == "invalid_code":
            per_code.append(
                CodeAssessment(
                    code=code,
                    verdict=Verdict.NEEDS_EXPERT,
                    reason_code=ReasonCode.INVALID_CODE,
                    note="질병기호 형식이 아닙니다(예: F32, S72.0).",
                )
            )
            continue

        parsed = kcd.KcdCode.parse(code)
        hit_pairs = [(m, c) for m, c in mentions if m.range.contains(parsed)]
        cites = _citations(hit_pairs, judged["status"])
        all_cites.extend(cites)

        if judged["status"] == "excluded":
            v, rc, note = Verdict.UNLIKELY, ReasonCode.EXCLUDED_BY_CLAUSE, "면책 조항에 해당합니다."
        elif judged["status"] == "exception":
            v, rc, note = (
                Verdict.NEEDS_DOCUMENTS,
                ReasonCode.EXCEPTION_APPLIES,
                "면책의 예외에 해당합니다. 요양급여 해당 여부 등 조건을 확인해야 합니다.",
            )
        else:
            #: ★면책 목록에 없다 ≠ 보장된다.
            v, rc, note = (
                Verdict.NEEDS_EXPERT,
                ReasonCode.NO_EVIDENCE,
                "면책 조항에는 없습니다. 다만 보장 여부는 '보상하는 사항' 조항이 정하므로 "
                "이 단계에서 보장된다고 단정할 수 없습니다.",
            )
        per_code.append(
            CodeAssessment(code=judged["code"], verdict=v, reason_code=rc, citations=cites, note=note)
        )

    # ── 5) 전체 결론 ────────────────────────────────────────────
    verdicts = {a.verdict for a in per_code}
    if Verdict.UNLIKELY in verdicts:
        overall, rc = Verdict.UNLIKELY, ReasonCode.EXCLUDED_BY_CLAUSE
    elif Verdict.NEEDS_DOCUMENTS in verdicts:
        overall, rc = Verdict.NEEDS_DOCUMENTS, ReasonCode.EXCEPTION_APPLIES
    else:
        overall, rc = Verdict.NEEDS_EXPERT, ReasonCode.NO_EVIDENCE

    warnings: list[str] = []
    if applied.date_confidence == "month":
        warnings.append("판매시점을 월까지만 확인했습니다. 경계 시점이면 세대가 다를 수 있습니다.")
    if applied.generation_confidence == "ambiguous":
        warnings.append("세대 판정이 경계에 걸쳐 있습니다.")

    return PrecheckResult(
        verdict=overall,
        abstained=overall == Verdict.NEEDS_EXPERT,
        reason_code=rc,
        message="",
        applied_policy=applied,
        per_code=per_code,
        citations=_dedupe(all_cites),
        extractor=st.get("extractor", ""),
        warnings=warnings,
        **base,
    )


def _citations(pairs, status: str) -> list[Citation]:
    """근거 조항 → 인용. ★성격이 불명한(`mention`) 것은 근거로 내지 않는다."""
    want = {"excluded": {"exclude"}, "exception": {"exception", "exclude"}}.get(status, set())
    out: list[Citation] = []
    for m, c in pairs:
        if m.kind not in want:
            continue
        out.append(
            Citation(
                clause_id=c.clause_id,
                qualified_no=c.qualified_no,
                section=c.section,
                title=c.title,
                quote=m.context[:300],
                page_from=c.page_from,
                page_to=c.page_to,
                tier=EvidenceTier.POLICY_CLAUSE,
            )
        )
    return out


def _dedupe(cites: list[Citation]) -> list[Citation]:
    seen: set[str] = set()
    out: list[Citation] = []
    for c in cites:
        if c.clause_id in seen:
            continue
        seen.add(c.clause_id)
        out.append(c)
    return out
