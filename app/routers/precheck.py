"""보장 사전판정 API.

★HTTP 상태 코드 규칙 — **"확인 불가"는 오류가 아니다**

    200  판정했다. `verdict=unknown` 이어도 200 이다.
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

from app.adapters import file_clause_store, manifest_policy_resolver
from app.core.errors import InfraError, ValidationErr
from app.core.usecases import precheck
from app.schemas.precheck import (
    ExternalCaseSubmission,
    PrecheckRequest,
    PrecheckResult,
)

router = APIRouter(prefix="/v1", tags=["precheck"])

#: ★유스케이스는 포트만 안다. 구체 어댑터를 고르는 것은 **여기(바깥)** 의 일이다.
#:   DB 적재가 끝나면 이 줄만 바꾸면 된다 — 유스케이스는 손대지 않는다.
_POLICIES = manifest_policy_resolver
_CLAUSES = file_clause_store

#: 약관 버전 목록은 매 요청마다 읽을 필요가 없다.
_VERSIONS = None


def _versions():
    global _VERSIONS
    if _VERSIONS is None:
        _VERSIONS = _POLICIES.load_versions()
    return _VERSIONS


@router.post("/prechecks", response_model=PrecheckResult)
def create_precheck(body: PrecheckRequest) -> PrecheckResult:
    """가입일·질병기호로 보장 여부를 미리 본다.

    ★근거 조항을 못 대면 `verdict="unknown"` 으로 답한다(HTTP 200).
      추측해서 "보장됩니다"라고 말하지 않는다.
    """
    try:
        return precheck.run(
            body, policies=_POLICIES, clauses=_CLAUSES, versions=_versions()
        )
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
    return {
        "schema_version": "v1",
        "rule_engine_version": precheck.RULE_ENGINE_VERSION,
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
        "notes": [
            "판정은 약관 원문 조항만을 근거로 한다.",
            "근거를 못 대면 verdict=unknown 으로 답한다(HTTP 200).",
            "면책 목록에 없다는 것이 보장된다는 뜻은 아니다.",
        ],
    }


@router.post("/observations", status_code=status.HTTP_202_ACCEPTED)
def submit_observation(body: ExternalCaseSubmission) -> dict:
    """외부 에이전트가 실제 청구 결과를 보고한다.

    ★이 데이터는 **판정 근거가 되지 않는다.**

        약관 조항과 같은 인덱스에 넣지 않고, 같은 등급으로 인용하지도 않는다.
        검증되지 않은 남의 보고로 "보장됩니다"라고 말하면 안 되기 때문이다.
        쓰임은 둘이다 — **승인율 통계**와 **우리 판정의 사후 검증**.

    ★지금은 받기만 하고 저장은 뒤로 미룬다(프로토타입).
      저장 스키마는 `docs/handoff/` 의 데이터 축적 설계를 따른다.
    """
    return {
        "accepted": True,
        "verification": "unverified",
        "note": (
            "접수했습니다. 이 보고는 검증 전까지 통계에 반영되지 않으며, "
            "약관 조항과 같은 근거로 쓰이지 않습니다."
        ),
        "echo": {
            "client_ref": body.client_ref,
            "insurer": body.insurer,
            "outcome": body.outcome,
            "precheck_trace_id": body.precheck_trace_id,
        },
    }
