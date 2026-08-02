"""CS 문의 분류 + 정확도 측정 + 혼동쌍 분석 (오분류 개선 루프, PDF5).

측정→분석→처방(후보 산출)까지 결정론으로 구현한다. 프롬프트 자동 재작성/반복
튜닝은 YAGNI로 두지 않는다 (Codex 합의).
"""

from __future__ import annotations

import csv
from collections import Counter
from collections.abc import Callable
from pathlib import Path
from typing import Any

from app.core.config import get_settings
from app.core.errors import InfraError, ValidationErr
from app.prompts.templates import CATEGORIES, build_classify_prompt

UNCLASSIFIED = "미분류"  # CATEGORIES에 포함하지 않는 오답 sentinel

# chat_complete(prompt) -> str
ChatComplete = Callable[[str], str]


def _default_chat_complete(prompt: str) -> str:
    """로컬/실제 LLM 평문 completion. 연결 실패는 InfraError."""
    from openai import APIConnectionError

    from app.core.llm_clients import get_active_model, get_chat_client

    client = get_chat_client()
    try:
        resp = client.chat.completions.create(
            model=get_active_model(),
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
            max_tokens=16,
        )
    except APIConnectionError as exc:
        raise InfraError("LLM 서버에 연결할 수 없습니다.") from exc
    return resp.choices[0].message.content or ""


def normalize_category(output: str) -> str:
    """모델 출력에서 카테고리를 정규화한다. 정확히 1개면 반환, 0/2개 이상은 미분류."""
    found = [c for c in CATEGORIES if c in output]
    if len(found) == 1:
        return found[0]
    return UNCLASSIFIED


def classify_one(text: str, chat_complete: ChatComplete | None = None) -> str:
    if not text or not text.strip():
        raise ValidationErr("분류할 텍스트가 비어 있습니다.")
    chat_complete = chat_complete or _default_chat_complete
    output = chat_complete(build_classify_prompt(text))
    return normalize_category(output)


def measure_accuracy(preds: list[str], labels: list[str]) -> dict[str, Any]:
    if len(preds) != len(labels):
        raise ValidationErr("preds와 labels 길이가 다릅니다.")
    wrong = [(i, lab, pred) for i, (pred, lab) in enumerate(zip(preds, labels)) if pred != lab]
    total = len(labels)
    correct = total - len(wrong)
    return {
        "total": total,
        "correct": correct,
        "accuracy": round(correct / total, 4) if total else 0.0,
        "wrong": wrong,
    }


def confusion_pairs(preds: list[str], labels: list[str]) -> dict[tuple[str, str], int]:
    """오분류된 (정답, 예측) 쌍을 집계한다 (혼동쌍)."""
    if len(preds) != len(labels):
        raise ValidationErr("preds와 labels 길이가 다릅니다.")
    counter: Counter[tuple[str, str]] = Counter()
    for pred, lab in zip(preds, labels):
        if pred != lab:
            counter[(lab, pred)] += 1
    return dict(counter)


def suggest_fewshot_candidates(preds: list[str], labels: list[str], top_n: int = 3) -> list[dict]:
    """가장 많이 혼동된 경계 쌍을 few-shot 보강 후보로 제안한다 (처방, 자동 재작성 아님)."""
    pairs = confusion_pairs(preds, labels)
    ranked = sorted(pairs.items(), key=lambda kv: kv[1], reverse=True)[:top_n]
    return [
        {"true_label": lab, "predicted": pred, "count": n, "hint": f"'{lab}' vs '{pred}' 경계 예시 보강"}
        for (lab, pred), n in ranked
    ]


def improvement_report(
    texts: list[str],
    labels: list[str],
    base_fewshot: list[tuple[str, str]],
    augmented_fewshot: list[tuple[str, str]],
    chat_complete: ChatComplete | None = None,
) -> dict[str, Any]:
    """오분류 개선 루프 마무리: few-shot 보강 전/후 정확도를 비교한다.

    측정(base) → 분석(confusion_pairs) → 처방(augmented few-shot) → 재측정 순환을
    하나의 리포트로 닫는다.
    """
    def _run(fewshot: list[tuple[str, str]]) -> list[str]:
        return [
            normalize_category((chat_complete or _default_chat_complete)(build_classify_prompt(t, fewshot)))
            for t in texts
        ]

    before_preds = _run(base_fewshot)
    before = measure_accuracy(before_preds, labels)
    pairs = confusion_pairs(before_preds, labels)

    after_preds = _run(augmented_fewshot)
    after = measure_accuracy(after_preds, labels)

    return {
        "before_accuracy": before["accuracy"],
        "after_accuracy": after["accuracy"],
        "delta": round(after["accuracy"] - before["accuracy"], 4),
        "confusion_pairs_before": {f"{k[0]}->{k[1]}": v for k, v in pairs.items()},
    }


def load_cs_dataset(path: Path | None = None) -> tuple[list[str], list[str]]:
    """cs_inquiries.csv에서 (content, category_hint) 로드. 라벨 컬럼=category_hint."""
    path = path or (get_settings().DATA_DIR / "cs_inquiries.csv")
    if not path.exists():
        raise InfraError(f"CS 데이터가 없습니다: {path}")
    texts, labels = [], []
    with path.open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            texts.append(row["content"])
            labels.append(row["category_hint"])
    return texts, labels


def classify_dataset(
    texts: list[str], chat_complete: ChatComplete | None = None
) -> list[str]:
    return [classify_one(t, chat_complete) for t in texts]
