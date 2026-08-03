"""보장 사전판정 API.

★HTTP 상태 코드 규칙 — **"확인 불가"는 오류가 아니다**

    200  판정했다. `verdict=needs_expert` 로 기권해도 200 이다.
         근거를 못 대서 기권한 것은 **정상 결과**이지 서버 잘못이 아니다.
    422  입력이 잘못됐다(가입일 형식 등).
    503  검색·저장소 장애. 이때만 "우리 잘못"이다.

    이 구분이 무너지면 클라이언트가 기권과 장애를 못 가린다.

★외부 에이전트가 부를 것을 전제로 만든다

    · `trace_id` 를 항상 돌려준다 — 나중에 "그 판정" 을 지목할 수 있어야 한다
    · 응답에 **무엇으로 판정했는지**(약관 버전·규칙 버전·추출기)를 담는다
    · 사례 제출(`/observations`)은 **판정 근거로 쓰지 않는다.** 통계·검증용이다
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from app.core.domain.precheck_result import PrecheckInput, PrecheckOutcome
from app.core.errors import InfraError, ValidationErr
from app.core.usecases import precheck
from app.schemas.precheck import (
    AppliedPolicy,
    Citation,
    CodeAssessment,
    ExternalCaseSubmission,
    PrecheckRequest,
    PrecheckResult,
)

router = APIRouter(prefix="/v1", tags=["precheck"])

#: ★어댑터를 고르는 것은 **조립 지점(`app/composition.py`)** 의 일이다.
#:   라우터가 직접 import 하면 "어느 저장소를 쓰는가"가 HTTP 계층에 흩어진다.
_DEPS = None


def _deps():
    global _DEPS
    if _DEPS is None:
        from app.composition import build_precheck

        _DEPS = build_precheck()
    return _DEPS

#: 판정 흐름. 매 요청마다 다시 조립하지 않는다.
_GRAPH = None


def _graph():
    global _GRAPH
    if _GRAPH is None:
        from app.workflow.precheck_graph import build

        _GRAPH = build()
    return _GRAPH


#: 약관 버전 목록은 매 요청마다 읽을 필요가 없다.
_VERSIONS = None


#: ★캐시를 만들 때의 모드 설정 파일 mtime. **프로세스가 둘이기 때문에** 필요하다.
_VERSIONS_STAMP = None


def _mode_stamp() -> float:
    """판정 모드 설정의 변경 시각. 파일이 없으면 0."""
    from app.core.domain import identification_mode

    try:
        f = identification_mode._MODE_FILE
        return f.stat().st_mtime if f.exists() else 0.0
    except OSError:
        return 0.0


def _versions():
    """판정에 쓸 약관 목록(캐시).

    ★★**모드가 바뀌면 자동으로 다시 읽는다.**

        관리 서버(8081)에서 모드를 바꿔도 고객 서버(8080)는 **다른 프로세스**라
        `invalidate_versions_cache()` 가 닿지 않는다. 실측 2026-08-04:
        엄격 모드로 바꿨는데 고객 API 는 계속 `total_policy_versions=132` 를
        보고했다 — **표시와 동작이 어긋난 상태**다. 관측 스트림에서 이미
        같은 종류의 문제를 겪었고, 같은 해법(파일을 진실의 출처로)을 쓴다.
    """
    #: ★캐시는 **어댑터가 파일 지문으로** 관리한다. 라우터가 따로 캐시를 두면
    #:   판정 경로와 표시 경로가 서로 다른 목록을 보게 된다 — 실제로 그랬다.
    loader = getattr(_deps()["policies"], "load_versions_cached", None)
    return loader() if loader else _deps()["policies"].load_versions()


def invalidate_versions_cache() -> None:
    """★판정 모드가 바뀌면 **반드시** 부른다.

    모드는 어떤 문서를 판정에 쓸지 바꾼다. 캐시를 그대로 두면 화면에는
    "엄격"이라 적혀 있는데 판정은 자동승인 결과로 계속 나온다 —
    **표시와 동작이 어긋나는 것이 이 도메인에서 가장 나쁜 상태**다.
    """
    global _VERSIONS, _VERSIONS_STAMP
    _VERSIONS = None
    _VERSIONS_STAMP = None


def _confirmation_stats() -> dict:
    """확정이 **어디까지** 됐나. 분모를 함께 낸다.

    ★`total_policy_versions` 만 내보내면 그게 전량인 줄 안다.
      숫자를 인용할 때 분모가 무엇인지 함께 적는다(CLAUDE.md §1).
    """
    from app.adapters import manifest_policy_resolver as mpr

    try:
        ledger = mpr.load_ledger()
        collected = mpr.count_collected()
    except Exception:  # noqa: BLE001
        #: ★삼켜서 0 으로 보고하지 않는다. "못 셌다"와 "0건"은 다르다.
        return {"error": "확정 현황을 세지 못했습니다"}
    scopes: dict[str, int] = {}
    pending = 0
    for e in ledger.values():
        scopes[e.get("scope") or "-"] = scopes.get(e.get("scope") or "-", 0) + 1
        if "대기" in (e.get("confirmed_by") or ""):
            pending += 1
    return {
        "confirmed": len(ledger),
        "collected": collected,
        "scopes": scopes,
        "human_signoff_pending": pending,
        "ledger": "config/confirmed_documents.jsonl",
    }


def _confirmation_coverage() -> str:
    st = _confirmation_stats()
    if st.get("error") or not st.get("confirmed"):
        return ""
    total = st.get("collected") or 0
    pct = (st["confirmed"] / total * 100) if total else 0.0
    #: ★**마크다운을 쓰지 않는다.** 이 문장은 화면에 **그대로** 찍힌다 —
    #:   `insurance.js` 가 `textContent` 로 넣기 때문에 `**강조**` 가 별표째 보인다.
    #:   실측 2026-08-04: 화면에 `**10건(0.7%)**` 이 그대로 나왔다.
    msg = (f"⚠ 확정된 약관은 수집분 {total:,}건 중 {st['confirmed']}건({pct:.1f}%) 뿐입니다. "
           "여기 없는 약관은 판정하지 않고 기권합니다.")
    #: ★`demo` 만 이름으로 집어 말하다가 `machine_verified` 확대분(122건)이
    #:   **문장에서 통째로 빠졌다**(2026-08-04). 범위 이름이 늘 때마다 여기를 고쳐야 하면
    #:   반드시 빠뜨린다 — 있는 것을 **전부** 적는다.
    _LABEL = {"demo": "시연", "machine_verified": "기계대조", "-": "범위미상"}
    parts = [f"{_LABEL.get(k, k)} {v}건" for k, v in sorted(st.get("scopes", {}).items())]
    if parts:
        msg += f" 확정 범위 — {' · '.join(parts)}."
    if st.get("human_signoff_pending"):
        msg += (f" {st['human_signoff_pending']}건은 기계 대조로 확정됐고 "
                "사람의 최종 승인이 남아 있습니다.")
    return msg


#: ★도메인 ↔ HTTP 변환은 **여기(바깥)** 의 일이다.
#:
#:   유스케이스가 pydantic 모델을 직접 쓰면 **안쪽이 바깥을 참조**하게 된다.
#:   실제로 그랬고, `ARCH-002` 의 금지 목록에 `app.schemas` 가 없어 빠져나갔다.
#:   유스케이스는 `PrecheckOutcome`(순수 dataclass)을 돌려주고 여기서 옮긴다.


def _to_input(body: PrecheckRequest) -> PrecheckInput:
    return PrecheckInput(
        insurer=body.insurer,
        enrolled_on=body.enrolled_on,
        kcd_codes=tuple(body.kcd_codes),
        product_name=body.product_name,
        client_ref=body.client_ref,
    )


def _cite(c) -> Citation:
    return Citation(
        clause_id=c.clause_id,
        qualified_no=c.qualified_no,
        section=c.section,
        title=c.title,
        quote=c.quote,
        page_from=c.page_from,
        page_to=c.page_to,
        tier=c.tier,
    )


def _policy(p) -> AppliedPolicy:
    return AppliedPolicy(
        insurer=p.insurer,
        product_name=p.product_name,
        sale_start=p.sale_start,
        sale_end=p.sale_end,
        generation=p.generation,
        generation_label=p.generation_label,
        product_line=p.product_line,
        sha256=p.sha256,
        date_confidence=p.date_confidence,
        generation_confidence=p.generation_confidence,
        parse_status=p.parse_status,
    )


def _to_dto(o: PrecheckOutcome) -> PrecheckResult:
    return PrecheckResult(
        verdict=o.verdict,
        abstained=o.abstained,
        reason_code=o.reason_code,
        message=o.message,
        applied_policy=_policy(o.applied_policy) if o.applied_policy else None,
        per_code=[
            CodeAssessment(
                code=a.code,
                verdict=a.verdict,
                reason_code=a.reason_code,
                citations=[_cite(c) for c in a.citations],
                note=a.note,
            )
            for a in o.per_code
        ],
        citations=[_cite(c) for c in o.citations],
        candidates=[_policy(c) for c in o.candidates],
        rule_engine_version=o.rule_engine_version,
        extractor=o.extractor,
        trace_id=o.trace_id,
        warnings=o.warnings,
    )


@router.post("/prechecks", response_model=PrecheckResult)
def create_precheck(body: PrecheckRequest) -> PrecheckResult:
    """가입일·질병기호로 보장 여부를 미리 본다.

    ★근거 조항을 못 대면 `verdict="needs_expert"` 로 답한다(HTTP 200).
      추측해서 "보장됩니다"라고 말하지 않는다.
    """
    try:
        #: ★흐름은 **그래프가 소유한다.** 라우터가 유스케이스를 직접 부르면
        #:   같은 판단이 두 곳(라우터·그래프)에 생기고 반드시 어긋난다.
        #:   그래프는 판정을 바꾸지 않고 잇고·분기하고·재시도만 통제한다
        #:   (`docs/handoff/06_계약_Agent.md` §1).
        outcome, _state = _graph().invoke(_to_input(body))
        dto = _to_dto(outcome)
        #: ★★**확정이 부분이면 고른 판본이 진짜 최신이 아닐 수 있다.**
        #:
        #:   `resolve()` 는 「가입일 이전 판매 시작 중 **가장 늦은 것**」을 고른다.
        #:   그런데 그 '가장 늦은 것'은 **확정된 것 중에서만** 가장 늦다.
        #:   진짜 적용 판본이 아직 미확정이면 **조용히 더 오래된 판본**이 뽑히고,
        #:   응답은 그것을 100% 확정된 것과 **똑같은 확신으로** 말한다.
        #:
        #:   실측 2026-08-04 — 확정을 10건에서 132건으로 늘리자
        #:   `NH농협생명 20180101` 의 적용 판본이 **2세대에서 3세대로 바뀌었다.**
        #:   답이 바뀐 것이 아니라 **원래 3세대였는데 안 보였던 것**이다.
        #:   그때 응답의 `warnings` 는 비어 있었다 — 사용자는 알 길이 없었다.
        #:
        #:   ★그래서 판본을 골랐을 때만 붙인다. 기권했으면 이미 다른 사유를 말하고 있다.
        if dto.applied_policy is not None:
            st = _confirmation_stats()
            done, total = st.get("confirmed") or 0, st.get("collected") or 0
            if total and done < total:
                dto.warnings = [
                    *dto.warnings,
                    f"확정된 약관은 보유 {total:,}건 중 {done:,}건({done / total * 100:.1f}%)입니다. "
                    "아직 확정되지 않은 약관 중에 더 나중에 판매된 판본이 있을 수 있고, "
                    "그렇다면 여기 적힌 약관은 실제 적용 판본이 아닐 수 있습니다.",
                ]
        #: ★관측은 **응답을 만든 뒤** 붙인다. 여기서 실패해도 판정은 이미 끝나 있다.
        #:   그리고 판정 자체를 바꾸지 않는다(`agent_stream` 은 표현 계층이다).
        from app.obs import agent_stream

        agent_stream.publish(
            "agent.precheck",
            client_ref=body.client_ref or "-",
            detail={"insurer": body.insurer, "codes": list(body.kcd_codes)[:3],
                    "verdict": dto.verdict, "abstained": dto.abstained,
                    "trace_id": dto.trace_id},
        )
        return dto
    except ValidationErr as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e)
        ) from e
    except InfraError as e:
        #: ★저장소·검색 장애만 503 이다. 기권을 503 으로 내보내면 안 된다.
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(e)
        ) from e


@router.get("/support-manifest")
def support_manifest() -> dict:
    """**무엇을 지원하는지** 밝힌다.

    ★"1,367건 전부 지원"이라고 말하지 않는다. 판정에 쓸 수 있는 것만 센다.
      클라이언트가 기대를 잘못 세우면 없는 보험사를 계속 물어보게 된다.
    """
    vs = _versions()
    by_insurer: dict[str, dict] = {}
    for v in vs:
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
    from app.core.ports.precheck import REQUIRE_CONFIRMED

    #: ★확정 게이트를 껐으면 **반드시 드러낸다.**
    #:   조용히 미확정 약관으로 답하는 것이 가장 위험하다.
    notes = [
        "판정은 약관 원문 조항만을 근거로 한다.",
        "근거를 못 대면 verdict=needs_expert 로 기권한다(HTTP 200).",
        "면책 목록에 없다는 것이 보장된다는 뜻은 아니다.",
    ]
    if not REQUIRE_CONFIRMED:
        notes.insert(
            0,
            "⚠ 확정 게이트가 꺼져 있습니다(PRECHECK_ALLOW_UNCONFIRMED=1). "
            "식별이 확정되지 않은 약관도 판정에 쓰고 있습니다 — 시연용입니다.",
        )
    elif not vs:
        notes.insert(
            0,
            "⚠ 판정 가능한 약관이 0건입니다. 수집은 끝났으나 "
            "'이 파일이 무엇인가'를 사람이 확정하는 절차가 아직 남았습니다. "
            "확인 안 된 약관으로 보장 여부를 답하지 않습니다.",
        )

    #: ★★**확정 범위를 숨기지 않는다.**
    #:
    #:   0건일 때는 위 경고가 사실을 말했다. 그런데 데모용으로 10건을 확정하자
    #:   경고가 **사라지고** `total_policy_versions: 10` 만 남았다 — 읽는 사람은
    #:   전체 1,367건 중 판정 준비가 끝난 것으로 읽는다. 실제로는 **0.7%** 다.
    #:
    #:   그리고 그 10건은 `scripts.confirm.identify_documents` 의 **기계 대조**로
    #:   확정됐다. 사람의 최종 승인이 아직 남아 있다면 그것도 말해야 한다 —
    #:   감지하고 통과시키면서 신호를 안 남기면 그건 폴백이다(CLAUDE.md §0).
    coverage = _confirmation_coverage()
    if coverage:
        notes.insert(0, coverage)

    #: ★자동승인 모드면 **맨 앞에** 경고를 둔다. 뒤에 두면 안 읽힌다.
    from app.core.domain import identification_mode

    mode = identification_mode.current()
    if mode.auto_approve:
        notes.insert(0, f"⚠ {mode.as_dict()['warning']}")

    return {
        "schema_version": "v1",
        "rule_engine_version": precheck.RULE_ENGINE_VERSION,
        "require_confirmed_documents": REQUIRE_CONFIRMED,
        #: ★어느 게이트로 만든 목록인지 **항상** 함께 낸다. 숫자만 보면 오해한다.
        "identification_mode": mode.as_dict(),
        "total_policy_versions": len(vs),
        #: 판정 준비가 끝난 범위. `total_policy_versions` 만 보면 전량으로 오해한다.
        "confirmation": _confirmation_stats(),
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
    }


@router.post("/observations", status_code=status.HTTP_202_ACCEPTED)
def submit_observation(body: ExternalCaseSubmission) -> dict:
    """외부 에이전트가 실제 청구 결과를 보고한다.

    ★이 데이터는 **판정 근거가 되지 않는다.**

        약관 조항과 같은 인덱스에 넣지 않고, 같은 등급으로 인용하지도 않는다.
        검증되지 않은 남의 보고로 "보장됩니다"라고 말하면 안 되기 때문이다.
        쓰임은 둘이다 — **승인율 통계**와 **우리 판정의 사후 검증**.

    ★원본을 그대로 남기고, 정규화한 것은 append-only 로 쌓는다.

        data/external/submissions/{YYYY-MM}/{client_ref}/{ts}_{idem}.json
        data/external/events/{YYYY-MM-DD}.jsonl

      나중에 파싱 규칙이 바뀐다. 정규화한 것만 두면 "그때 뭘 받았나"를
      다시 볼 수 없다(약관 PDF 를 원본으로 두는 것과 같은 이유).

    ★`verification` 은 **클라이언트가 뭐라 보내든 `unverified`** 다.
      남이 자기 데이터를 스스로 "검증됨"이라 하면 그건 검증이 아니다.
    """
    from app.adapters import external_submission_store as store

    try:
        res = store.store(body.model_dump())
    except InfraError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(e)
        ) from e

    from app.obs import agent_stream

    #: ★`track="verified_real"` — **제출된 트랙**을 말하는 것이지
    #:   "검증됐다"는 뜻이 아니다. 아래 `verification` 이 `unverified` 인 것과 모순 아니다.
    agent_stream.publish(
        "agent.observe",
        client_ref=body.client_ref,
        track="verified_real",
        detail={"outcome": body.outcome, "codes": list(body.kcd_codes)[:3],
                "duplicate": res.duplicate},
    )
    return {
        "accepted": True,
        "stored": res.stored,
        "duplicate": res.duplicate,
        "idempotency_key": res.idempotency_key,
        "verification": "unverified",
        "note": (
            "이미 접수된 보고입니다(재시도로 판단해 새로 쌓지 않았습니다)."
            if res.duplicate
            else "접수했습니다. 이 보고는 검증 전까지 통계에 반영되지 않으며, "
            "약관 조항과 같은 근거로 쓰이지 않습니다."
        ),
        "echo": {
            "client_ref": body.client_ref,
            "insurer": body.insurer,
            "outcome": body.outcome,
            "precheck_trace_id": body.precheck_trace_id,
        },
    }
