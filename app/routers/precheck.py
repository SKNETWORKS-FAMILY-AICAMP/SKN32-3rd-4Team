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


def _versions():
    global _VERSIONS
    if _VERSIONS is None:
        _VERSIONS = _deps()["policies"].load_versions()
    return _VERSIONS


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
        return _to_dto(outcome)
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

    return {
        "schema_version": "v1",
        "rule_engine_version": precheck.RULE_ENGINE_VERSION,
        "require_confirmed_documents": REQUIRE_CONFIRMED,
        "total_policy_versions": len(vs),
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
