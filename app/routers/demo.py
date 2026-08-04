"""합성(데모) 트랙 제출 — `/v1/demo/observations`.

★★**실제 제출(`/v1/observations`)과 파일을 나눈 것이 의도다.**

    계획서 §5-1 은 합성/실제를 다섯 층에서 나누라고 했다. 그 중 **수집** 층이 여기다.
    한 핸들러에 `?synthetic=true` 같은 스위치를 두지 않는다 —
    스위치는 빠뜨릴 수 있고, 빠뜨리면 합성이 실제 통계로 샌다.

        실제  `/v1/observations`      → `external_submission_store` → `data/external/…`
        합성  `/v1/demo/observations` → `demo_submission_store`     → `data/demo/…`

    이 모듈은 실제 저장소를 **import 하지 않는다.**

★여기 들어온 것도 `unverified` 다

    합성이라고 해서 바로 통계가 되지 않는다. 그게 이 데모의 요점이다 —
    **검수 단계를 거쳐야 숫자가 움직인다**(`/api/admin/demo/verifications`).
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from app.core.errors import InfraError, ValidationErr

router = APIRouter(prefix="/v1/demo", tags=["demo"])


class DemoObservation(BaseModel):
    """합성 에이전트가 보고하는 사례. 실제 사례와 **스키마가 같아도 저장소가 다르다.**"""

    client_ref: str = Field(min_length=1, description="보고한 (가상) 에이전트 식별자")
    insurer: str = ""
    enrolled_on: str = ""
    kcd_codes: list[str] = Field(default_factory=list)
    product_id: str = ""
    age_band: str | None = None
    outcome: str = Field(description="paid / denied / partial / pending")
    outcome_reason: str = ""
    precheck_trace_id: str | None = None
    idempotency_key: str | None = None


@router.post("/observations", status_code=status.HTTP_202_ACCEPTED)
def submit_demo_observation(body: DemoObservation) -> dict:
    """합성 사례를 접수한다. **아직 집계에 들어가지 않는다.**"""
    from app.adapters import demo_submission_store as demo
    from app.obs import agent_stream

    try:
        res = demo.store(body.model_dump())
    except ValidationErr as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e)
        ) from e
    except InfraError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(e)
        ) from e

    agent_stream.publish(
        "agent.observe",
        client_ref=body.client_ref,
        track="synthetic",
        detail={"outcome": body.outcome, "codes": body.kcd_codes[:3],
                "duplicate": res.duplicate},
    )
    return {
        "accepted": True,
        "data_source": "synthetic",
        "stored": res.stored,
        "duplicate": res.duplicate,
        "submission_id": res.submission_id,
        "verification": "unverified",
        "note": (
            "이미 접수된 보고입니다(재시도로 판단해 새로 쌓지 않았습니다)."
            if res.duplicate
            else "접수했습니다. **합성 데이터**이며, 검수로 승격되기 전까지 "
                 "통계에 반영되지 않습니다."
        ),
    }
