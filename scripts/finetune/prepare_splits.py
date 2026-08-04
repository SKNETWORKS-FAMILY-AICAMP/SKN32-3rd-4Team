"""CS 분류 학습/평가용 분할 고정 (Phase 16).

계획서 §3.3에 따라 **단일 holdout을 쓰지 않는다.** 원본 60건만으로
`반복 stratified 5-fold CV`를 구성하고 그 분할을 파일로 고정한다.

핵심 설계:
- **lineage_id**: 각 원본 문의에 계보 ID를 부여한다. 이후 증강문은 원본의 lineage_id를
  물려받아, 같은 계보가 서로 다른 fold로 흩어지는 누수를 막는다(group 분할의 근거).
- **다중 seed**: fold 구성이 운에 좌우되므로 여러 seed로 반복해 분산을 볼 수 있게 한다.
- 분할은 파일로 고정한다 — 실행할 때마다 달라지면 baseline 비교가 성립하지 않는다.

무폴백: 입력 CSV가 없거나 라벨이 CATEGORIES에 없으면 조용히 건너뛰지 않고 즉시 실패한다.

실행: python -m scripts.finetune.prepare_splits
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

from sklearn.model_selection import StratifiedKFold

_ROOT = Path(__file__).resolve().parents[2]
_SRC = _ROOT / "data" / "cs_inquiries.csv"
_OUT = _ROOT / "data" / "finetune" / "cs_splits.json"

N_SPLITS = 5
SEEDS = (0, 1, 2, 3, 4)


def load_rows() -> tuple[list[dict[str, str]], dict]:
    """원본 CS 문의를 읽어 lineage_id를 부여하고 **중복 문장을 제거**한다.

    ★ 중복 제거가 필수인 이유(실측으로 발견): 원본 60건 중 동일 본문이 15건 있었다.
    중복을 그대로 두면 같은 문장이 train과 test 양쪽에 들어가 점수가 부풀려진다
    (실제로 TF-IDF Macro-F1이 0.992로 나왔다 — 누수된 수치였다).
    중복 문장은 학습에 새 정보를 주지 않으므로 하나만 남긴다.

    라벨 검증 실패·본문 공백·**같은 문장에 서로 다른 라벨**은 조용히 넘기지 않고 즉시 오류.
    """
    from app.prompts.templates import CATEGORIES

    if not _SRC.is_file():
        raise FileNotFoundError(f"원본 데이터가 없습니다: {_SRC}")

    seen: dict[str, dict[str, str]] = {}
    raw_count = 0
    with _SRC.open(encoding="utf-8") as f:
        for i, r in enumerate(csv.DictReader(f)):
            label = (r.get("category_hint") or "").strip()
            content = (r.get("content") or "").strip()
            if label not in CATEGORIES:
                raise ValueError(f"{i+2}행: 알 수 없는 라벨 '{label}' (허용: {CATEGORIES})")
            if not content:
                raise ValueError(f"{i+2}행: 본문이 비어 있습니다")
            raw_count += 1

            prev = seen.get(content)
            if prev is not None:
                if prev["label"] != label:
                    # 같은 문장에 다른 라벨 = 라벨 노이즈. 임의로 하나를 고르지 않는다(무폴백).
                    raise ValueError(
                        f"{i+2}행: 동일 본문에 상충 라벨('{prev['label']}' vs '{label}'): {content[:30]}"
                    )
                continue  # 동일 본문·동일 라벨 → 중복이므로 버린다

            seen[content] = {
                # 원본(중복 제거 후) 1건 = 계보 1개. 증강문은 이 값을 그대로 물려받는다.
                "lineage_id": r.get("inquiry_id") or f"L{i:04d}",
                "content": content,
                "label": label,
                "origin": "original",
            }

    rows = list(seen.values())
    stats = {"raw": raw_count, "unique": len(rows), "dropped_duplicates": raw_count - len(rows)}
    return rows, stats


def build_splits(rows: list[dict[str, str]]) -> dict:
    """seed별 stratified 5-fold 인덱스를 만든다(원본만 대상)."""
    labels = [r["label"] for r in rows]
    folds_by_seed: dict[str, list[dict[str, list[int]]]] = {}
    for seed in SEEDS:
        skf = StratifiedKFold(n_splits=N_SPLITS, shuffle=True, random_state=seed)
        folds = [
            {"train": train_idx.tolist(), "test": test_idx.tolist()}
            for train_idx, test_idx in skf.split(range(len(rows)), labels)
        ]
        folds_by_seed[str(seed)] = folds
    return folds_by_seed


def main() -> None:
    rows, stats = load_rows()
    folds_by_seed = build_splits(rows)

    _OUT.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "note": "중복 제거된 원본 전용 반복 stratified 5-fold. 증강문은 lineage_id로 train fold에만 합류시킬 것.",
        "n_splits": N_SPLITS,
        "seeds": list(SEEDS),
        "dedup": stats,
        "rows": rows,
        "folds_by_seed": folds_by_seed,
    }
    _OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    from collections import Counter

    dist = Counter(r["label"] for r in rows)
    lines = [
        f"원본 {stats['raw']}건 → 중복 {stats['dropped_duplicates']}건 제거 → **{stats['unique']}건** 사용",
        f"→ {_OUT.relative_to(_ROOT)}",
        f"seed {len(SEEDS)}개 × {N_SPLITS}-fold = {len(SEEDS) * N_SPLITS} 평가 라운드",
        "클래스 분포: " + ", ".join(f"{k} {v}" for k, v in dist.most_common()),
        f"최소 클래스 {min(dist.values())}건 → fold당 약 {min(dist.values()) / N_SPLITS:.1f}건(경고: 극소)",
    ]
    print("\n".join(lines))


if __name__ == "__main__":
    import sys

    sys.path.insert(0, str(_ROOT))
    main()
