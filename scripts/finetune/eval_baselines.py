"""저렴한 기준선 평가 (Phase 16) — SLM 없이 나오는 성능선을 먼저 확보한다.

계획서 §5의 4종 비교 중 **①TF-IDF+선형**과 그 변형을 여기서 측정한다.
Codex 지적: "이 기준선을 못 이기면 SLM을 쓸 이유가 없다."

평가 방식(계획서 §3.3):
- 고정된 반복 stratified 5-fold(`data/finetune/cs_splits.json`)를 그대로 사용한다.
- fold마다 학습→예측하고, seed·fold 전체의 Macro-F1 **평균 ± 95% 신뢰구간**을 보고한다.
- 단일 숫자만 보고하지 않는다. 60건 규모에선 분산이 결론의 일부다.

무폴백: 분할 파일이 없으면 즉시 실패한다(먼저 prepare_splits를 돌리라는 뜻).

실행: python -m scripts.finetune.eval_baselines
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
from sklearn.dummy import DummyClassifier
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import f1_score
from sklearn.naive_bayes import ComplementNB
from sklearn.pipeline import Pipeline
from sklearn.svm import LinearSVC

_ROOT = Path(__file__).resolve().parents[2]
_SPLITS = _ROOT / "data" / "finetune" / "cs_splits.json"


def _char_tfidf() -> TfidfVectorizer:
    """한국어 짧은 문장이라 형태소 분석 없이 **문자 n-gram**을 쓴다(교착어에 견고)."""
    return TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 4), min_df=1, sublinear_tf=True)


def build_models() -> dict[str, Pipeline]:
    return {
        "다수클래스(하한선)": Pipeline([("clf", DummyClassifier(strategy="most_frequent"))]),
        "TF-IDF(char)+LogReg": Pipeline(
            [("vec", _char_tfidf()), ("clf", LogisticRegression(max_iter=2000, class_weight="balanced"))]
        ),
        "TF-IDF(char)+LinearSVC": Pipeline(
            [("vec", _char_tfidf()), ("clf", LinearSVC(class_weight="balanced"))]
        ),
        "TF-IDF(char)+ComplementNB": Pipeline([("vec", _char_tfidf()), ("clf", ComplementNB())]),
    }


def _mean_ci(values: list[float]) -> tuple[float, float]:
    """평균과 95% 신뢰구간 반폭(정규근사). 표본이 작으므로 폭이 넓게 나오는 게 정상."""
    arr = np.asarray(values, dtype=float)
    mean = float(arr.mean())
    if arr.size < 2:
        return mean, 0.0
    sem = float(arr.std(ddof=1) / math.sqrt(arr.size))
    return mean, 1.96 * sem


def evaluate() -> dict[str, dict]:
    if not _SPLITS.is_file():
        raise FileNotFoundError(f"분할 파일이 없습니다: {_SPLITS}\n먼저 prepare_splits를 실행하세요.")

    payload = json.loads(_SPLITS.read_text(encoding="utf-8"))
    rows = payload["rows"]
    texts = np.array([r["content"] for r in rows])
    labels = np.array([r["label"] for r in rows])

    results: dict[str, dict] = {}
    for name, model in build_models().items():
        macro_f1: list[float] = []
        acc: list[float] = []
        # per-fold 예측을 모아 seed별 paired 비교가 가능하도록 라운드 키를 남긴다.
        per_round: dict[str, float] = {}
        for seed, folds in payload["folds_by_seed"].items():
            for k, fold in enumerate(folds):
                tr, te = fold["train"], fold["test"]
                model.fit(texts[tr], labels[tr])
                pred = model.predict(texts[te])
                f1 = f1_score(labels[te], pred, average="macro", zero_division=0)
                macro_f1.append(float(f1))
                acc.append(float((pred == labels[te]).mean()))
                per_round[f"seed{seed}_fold{k}"] = float(f1)
        m, ci = _mean_ci(macro_f1)
        a, aci = _mean_ci(acc)
        results[name] = {
            "macro_f1_mean": m, "macro_f1_ci95": ci,
            "acc_mean": a, "acc_ci95": aci,
            "rounds": len(macro_f1), "per_round": per_round,
        }
    return results


def main() -> None:
    results = evaluate()
    out = _ROOT / "data" / "finetune" / "baseline_results.json"
    out.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = ["", "=== 저렴한 기준선 (원본 60건, 반복 stratified 5-fold) ===", ""]
    lines.append(f"{'모델':<28} {'Macro-F1 (평균±95%CI)':<26} {'Accuracy':<20} 라운드")
    lines.append("-" * 86)
    for name, r in sorted(results.items(), key=lambda kv: -kv[1]["macro_f1_mean"]):
        lines.append(
            f"{name:<28} {r['macro_f1_mean']:.3f} ± {r['macro_f1_ci95']:.3f}"
            f"{'':<10} {r['acc_mean']:.3f} ± {r['acc_ci95']:.3f}    {r['rounds']}"
        )
    lines += [
        "",
        "해석 주의: 60건 규모라 신뢰구간이 넓다. 구간이 겹치면 '더 낫다'고 말할 수 없다.",
        f"저장: {out.relative_to(_ROOT)}",
    ]
    text = "\n".join(lines)
    (_ROOT / "data" / "finetune" / "baseline_summary.txt").write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
