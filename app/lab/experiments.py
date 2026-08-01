"""파라미터 실험실 (PDF2).

temperature/다양성/토큰·비용 감각을 실험한다.

주의:
- count_tokens는 tiktoken cl100k_base 기준 '참고치'다. 로컬 Gemma의 실제 토크나이저와
  다르므로 정확한 과금 토큰 수가 아니다.
- 비용 추정은 config PRICE_TABLE에 등록된 모델만 가능하다. 로컬(local)은 과금이 없어
  미등록이며 estimate_cost는 ConfigError로 실패한다(폴백 없음).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from app.core.config import get_settings
from app.core.errors import ConfigError, ValidationErr

# complete_fn(prompt, temperature, max_tokens, system) -> str
CompleteFn = Callable[..., str]


def _default_complete(prompt: str, temperature: float, max_tokens: int, system: str | None = None) -> str:
    """요청별 temperature/max_tokens를 그대로 전달하는 평문 호출."""
    from openai import APIConnectionError

    from app.core.errors import InfraError
    from app.core.llm_clients import get_active_model, get_chat_client

    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    client = get_chat_client()
    try:
        resp = client.chat.completions.create(
            model=get_active_model(), messages=messages,
            temperature=temperature, max_tokens=max_tokens,
        )
    except APIConnectionError as exc:
        raise InfraError("LLM 서버에 연결할 수 없습니다.") from exc
    return resp.choices[0].message.content or ""


def count_tokens(text: str) -> int:
    """tiktoken cl100k_base 기준 토큰 수(참고치). 실제 Gemma 토큰 수와 다를 수 있다."""
    import tiktoken

    return len(tiktoken.get_encoding("cl100k_base").encode(text))


def token_compare(ko_text: str, en_text: str) -> dict[str, Any]:
    """같은 의미의 한/영 텍스트 토큰 수 비교(참고치)."""
    ko, en = count_tokens(ko_text), count_tokens(en_text)
    return {
        "ko_tokens": ko,
        "en_tokens": en,
        "ratio": round(ko / en, 3) if en else None,
        "note": "tiktoken cl100k_base 참고치 (로컬 Gemma 실제 토큰과 다를 수 있음)",
    }


def estimate_cost(prompt_tokens: int, output_tokens: int, model: str) -> dict[str, Any]:
    """PRICE_TABLE 등록 모델의 예상 비용(USD). 미등록(로컬 포함)은 ConfigError."""
    table = get_settings().PRICE_TABLE
    if model not in table:
        raise ConfigError(
            f"가격표에 없는 모델입니다: {model}. 로컬 모델은 과금이 없어 비용 추정 대상이 아닙니다."
        )
    in_price, out_price = table[model]
    cost = prompt_tokens / 1_000_000 * in_price + output_tokens / 1_000_000 * out_price
    return {"model": model, "prompt_tokens": prompt_tokens, "output_tokens": output_tokens,
            "estimated_usd": round(cost, 6)}


def basic_call(prompt: str, temperature: float = 0.7, max_tokens: int = 128,
               complete: CompleteFn | None = None) -> str:
    if not prompt.strip():
        raise ValidationErr("prompt가 비어 있습니다.")
    complete = complete or _default_complete
    return complete(prompt, temperature, max_tokens, None)


def role_call(prompt: str, system: str, temperature: float = 0.7, max_tokens: int = 128,
              complete: CompleteFn | None = None) -> str:
    if not prompt.strip() or not system.strip():
        raise ValidationErr("prompt/system이 비어 있습니다.")
    complete = complete or _default_complete
    return complete(prompt, temperature, max_tokens, system)


def diversity(prompt: str, n: int = 3, temperature: float = 1.0,
              complete: CompleteFn | None = None) -> dict[str, Any]:
    """같은 질문을 n회 반복해 고유 답변 수를 센다(temperature 효과)."""
    if not prompt.strip():
        raise ValidationErr("prompt가 비어 있습니다.")
    if not (1 <= n <= 10):
        raise ValidationErr("n은 1~10 사이여야 합니다.")
    complete = complete or _default_complete
    answers = [complete(prompt, temperature, 64, None) for _ in range(n)]
    return {"runs": n, "unique_count": len(set(answers)), "answers": answers}
