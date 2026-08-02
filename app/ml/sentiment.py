"""감성 분석 (로컬 KoELECTRA, NSMC 파인튜닝).

Bert_sentiment 학습 성과 재사용. transformers pipeline을 lazy 로드·캐시하고, 라벨은
model.config.id2label에서 해석한다(하드코딩 금지). 알 수 없는 라벨/로드 실패는
ConfigError, 빈 입력은 ValidationErr.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from app.core.config import get_settings
from app.core.errors import ConfigError, ValidationErr

# id2label 라벨 → 한국어 표기
_LABEL_KO = {"negative": "부정", "positive": "긍정"}


@lru_cache(maxsize=1)
def _get_pipeline():
    from transformers import pipeline

    settings = get_settings()
    model = settings.SENTIMENT_MODEL
    if not (model and model.strip()):
        raise ConfigError("SENTIMENT_MODEL이 비어 있습니다.")
    try:
        pipe = pipeline("text-classification", model=model, device=settings.SENTIMENT_DEVICE)
    except Exception as exc:  # noqa: BLE001 - 모델 로드 실패는 명시적 실패
        raise ConfigError(f"감성 모델 로드 실패: {exc}") from exc

    labels = set(pipe.model.config.id2label.values())
    if not labels.issubset({"negative", "positive"}):
        raise ConfigError(f"예상치 못한 감성 라벨: {labels}")
    return pipe


def _resolve_label(raw_label: str, pipe) -> str:
    """pipeline이 낸 라벨을 id2label로 해석한다 (LABEL_0/1 단정 금지).

    알 수 없는 라벨/인덱스는 조용히 넘기지 않고 ConfigError로 실패한다.
    """
    id2label = pipe.model.config.id2label
    if raw_label in _LABEL_KO:  # 이미 negative/positive
        return raw_label
    if raw_label.startswith("LABEL_"):
        try:
            idx = int(raw_label.split("_")[1])
            resolved = id2label[idx]
        except (ValueError, KeyError, IndexError) as exc:
            raise ConfigError(f"감성 라벨 인덱스를 해석할 수 없습니다: {raw_label}") from exc
        if resolved not in _LABEL_KO:
            raise ConfigError(f"예상치 못한 감성 라벨: {resolved}")
        return resolved
    raise ConfigError(f"알 수 없는 감성 라벨: {raw_label}")


def analyze_sentiment(text: str) -> dict[str, Any]:
    if not text or not text.strip():
        raise ValidationErr("감성을 분석할 텍스트가 비어 있습니다.")
    pipe = _get_pipeline()
    result = pipe(text, truncation=True)[0]  # 긴 텍스트 잘림 처리
    label_en = _resolve_label(result["label"], pipe)
    return {
        "label": _LABEL_KO[label_en],
        "label_en": label_en,
        "score": round(float(result["score"]), 4),
    }
