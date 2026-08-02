"""LlmGateway — ModelGateway의 OpenAI 호환 구현.

모델 ID는 소스가 아니라 **레지스트리**(get_active_profile)에서 해석한다(REQ-LLM-REG-01).
접속 인프라(base_url/key)는 기존 `app.core.llm_clients`를 재사용한다. 무폴백: 연결/HTTP
실패는 InfraError로 전파(빈/가짜 답변 반환 금지).
"""

from __future__ import annotations

from app.core.model_registry import ModelProfile


class LlmGateway:
    """ModelGateway 구현. 프로필의 provider_model_id로 완성 요청."""

    def __init__(self, profile: ModelProfile | None = None) -> None:
        self._profile = profile

    def complete(
        self, prompt: str, *, max_tokens: int | None = None, temperature: float = 0.0
    ) -> str:
        from openai import APIConnectionError, APIError, APITimeoutError

        from app.core.errors import InfraError
        from app.core.llm_clients import get_chat_client
        from app.core.model_registry import get_active_profile

        profile = self._profile or get_active_profile()
        client = get_chat_client()
        try:
            resp = client.chat.completions.create(
                model=profile.provider_model_id,  # 레지스트리에서 해석(하드코딩 아님)
                messages=[{"role": "user", "content": prompt}],
                temperature=temperature,
                max_tokens=max_tokens or 256,
            )
        except (APIConnectionError, APITimeoutError) as exc:
            raise InfraError("LLM 서버에 연결할 수 없습니다.") from exc
        except APIError as exc:
            raise InfraError(f"LLM 호출 오류: {exc}") from exc
        return resp.choices[0].message.content or ""
