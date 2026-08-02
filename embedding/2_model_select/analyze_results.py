"""결과 CSV들을 모아 hit@5 / hit@1 / MRR 종합"""
import csv
import glob
from collections import defaultdict

stats = defaultdict(lambda: {"n": 0, "hit5": 0, "hit1": 0, "rr": 0.0})

for path in glob.glob(r"out\results_*.csv"):
    with open(path, encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            key = row["model"]
            s = stats[key]
            s["n"] += 1
            s["hit5"] += int(row["hit@5"])
            r = row["first_hit_rank"]
            if r != "-":
                r = int(r)
                s["rr"] += 1.0 / r
                if r == 1:
                    s["hit1"] += 1

print(f"{'모델':<18}{'문항':>5}{'hit@5':>9}{'hit@1':>9}{'MRR':>7}")
for m, s in sorted(stats.items(), key=lambda x: -x[1]["rr"] / max(x[1]["n"], 1)):
    n = s["n"]
    print(f"{m:<18}{n:>5}{s['hit5'] / n:>8.0%}{s['hit1'] / n:>8.0%}"
          f"{s['rr'] / n:>7.3f}")