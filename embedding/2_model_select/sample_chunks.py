"""평가용 샘플 추출: 층화 샘플 + 질문 키워드 앵커 청크 강제 포함"""
import argparse
import json
import random
from collections import defaultdict
from pathlib import Path

ANCHOR_KEYWORDS = ["공제금액", "보상하지 않는", "통원", "입원의료비", "한도", "자기부담"]
ANCHOR_PER_KEYWORD = 40


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", default=r"data\chunks_clean.jsonl")
    ap.add_argument("--output", default=r"out\eval_sample.jsonl")
    ap.add_argument("--per-stratum", type=int, default=150,
                    help="(보험사 x content_type) 층별 샘플 수")
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    Path("out").mkdir(exist_ok=True)
    random.seed(args.seed)
    strata = defaultdict(list)
    anchors = defaultdict(list)
    offsets = []

    with open(args.input, encoding="utf-8") as f:
        pos = f.tell()
        line = f.readline()
        while line:
            offsets.append(pos)
            c = json.loads(line)
            i = len(offsets) - 1
            strata[(c["insurer"], c["content_type"])].append(i)
            for kw in ANCHOR_KEYWORDS:
                if kw in c["text"]:
                    anchors[kw].append(i)
            pos = f.tell()
            line = f.readline()

    picked = set()
    for key, idxs in strata.items():
        picked.update(random.sample(idxs, min(args.per_stratum, len(idxs))))
    for kw, idxs in anchors.items():
        picked.update(random.sample(idxs, min(ANCHOR_PER_KEYWORD, len(idxs))))

    picked = sorted(picked)
    with open(args.input, encoding="utf-8") as f, \
         open(args.output, "w", encoding="utf-8") as out:
        for i in picked:
            f.seek(offsets[i])
            out.write(f.readline())

    print(f"샘플 {len(picked)}개 저장 -> {args.output}")
    print("앵커 키워드별 포함: "
          + ", ".join(f"{k}:{min(ANCHOR_PER_KEYWORD, len(v))}" for k, v in anchors.items()))


if __name__ == "__main__":
    main()