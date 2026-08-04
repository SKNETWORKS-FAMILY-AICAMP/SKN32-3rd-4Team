"""등록 에이전트 REST가 기존 보험 유스케이스를 호출하는 얇은 façade."""

from __future__ import annotations

from app.schemas.agent import AgentObservationRequest, AgentPrecheckRequest, AgentTermRequest
from app.schemas.precheck import PrecheckRequest, PrecheckResult


class AgentFacade:
    """내부 HTTP 자기호출 없이 기존 application 흐름을 재사용한다."""

    def support_manifest(self) -> dict:
        from app.routers.precheck import support_manifest

        return support_manifest()

    def precheck(self, body: AgentPrecheckRequest, *, client_id: str) -> PrecheckResult:
        from app.routers.precheck import create_precheck_for_registered_agent

        return create_precheck_for_registered_agent(
            PrecheckRequest(
                **body.model_dump(),
                client_ref=client_id,
            )
        )

    def explain_term(self, body: AgentTermRequest) -> dict:
        from app.routers.chat import ChatRequest, chat_turn_for_registered_agent

        return chat_turn_for_registered_agent(ChatRequest(**body.model_dump()))

    def cohort(self, *, code: str, product_id: str, age_band: str | None) -> dict:
        from app.routers.cohort import cohorts

        # 합성 선택지는 노출하지 않는다. 등록 에이전트는 실제 검증 트랙만 조회한다.
        return cohorts(
            code=code,
            product_id=product_id,
            age_band=age_band,
        )

    def submit_observation(
        self,
        body: AgentObservationRequest,
        *,
        client_id: str,
        idempotency_key: str,
    ):
        from app.adapters import external_submission_store as store
        from app.obs import agent_stream

        payload = {
            **body.model_dump(),
            "client_ref": client_id,
            "idempotency_key": idempotency_key,
            # 클라이언트가 검증 상태를 보낼 필드 자체가 없다. 저장도 항상 unverified다.
            "verification": "unverified",
        }
        result = store.store(
            payload,
            channel="registered_agent",
            authenticated_client_id=client_id,
        )
        agent_stream.publish(
            "agent.observe",
            client_ref=client_id,
            track="verified_real",
            detail={
                "outcome": body.outcome,
                "code_count": len(body.kcd_codes),
                "duplicate": result.duplicate,
            },
        )
        return result


def get_agent_facade() -> AgentFacade:
    """DI 교체점."""

    return AgentFacade()


__all__ = ["AgentFacade", "get_agent_facade"]
