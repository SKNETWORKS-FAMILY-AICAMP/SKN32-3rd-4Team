"""임베딩 평가셋 — s6 릴리스(dataset/clauses.jsonl + occurrences.jsonl)에서 만든다.

    python -m scripts.eval.build_retrieval_set_s6

★기존 build_retrieval_set.py 는 s5 문서별 파일을 읽었다. s6 는 구조가 다르다 —
  내용 dedup 후 clauses.jsonl(임베딩 대상)·occurrences.jsonl(근거)로 분리돼 있고,
  제목·보험사·페이지는 occurrences 에만 있다. content_hash 로 둘을 조인한다.

★v1(s5) 동결 보호 — 산출물을 별도 파일로 낸다: data/eval/embed_bench_s6.json.
  (embed_bench.json 은 건드리지 않는다. 결과 폴더 분리는 bench_embedders 쪽에서.)

기본 정책(바꾸려면 상수만 고치면 된다):
  · has_eligible=true 만          (manifest 권고 — '안전 대상')
  · source_kind=clause 만         (부록 annex 는 조가 아니라 제목 의미가 흐려짐)
  · 코퍼스 제목 문구는 제거        (제목→본문 질의가 문자열 일치로 새는 것 방지)
    ★이건 '평가용' 본문이다. '최종 임베딩'은 원문 text 를 그대로 넣는다(별도).
"""
from __future__ import annotations

import json
import pathlib
import random
import re
from collections import Counter

_ROOT = pathlib.Path(__file__).resolve().parents[2]          # = bench/
_DATASET = _ROOT.parent / "data" / "dataset"                 # 레포 루트의 data/dataset/
_CLAUSES = _DATASET / "clauses.jsonl"
_OCCUR = _DATASET / "occurrences.jsonl"
_OUT = _ROOT / "data" / "eval" / "embed_bench_s6.json"       # ★v1 과 분리

CORPUS_N = 3000      # 옛 2000 → s6 는 12개사·1,367문서라 조금 키운다
QUERY_N = 300        # 제목 유일성 때문에 실제로는 더 적게 나온다
MIN_CHARS = 120
MAX_CHARS = 3000

_HEAD = re.compile(r"^\s*[\d가-힣]+[.\)]?\s*[（(]?[^)）\n]{0,40}[)）]?\s*")
_PROVISO = re.compile(r"(?:다만|단,|그러나|이 경우|또한)[,\s]", re.DOTALL)
_NEGATION = re.compile(r"않습니다|않는|않으며|제외|아닙니다|불가|지급하지|보상하지|해당하지")
_SENT_END = re.compile(r"(?:니다|합니다|습니다)[.\s]")


def _strip_head(text: str, title: str) -> str:
    body = text
    m = _HEAD.match(body)
    if m and title and title[:6] in m.group(0):
        body = body[m.end():]
    if title and body.lstrip().startswith(title):
        body = body.lstrip()[len(title):]
    return body.strip()


def main() -> int:
    if not _CLAUSES.exists():
        print(f"clauses.jsonl 없음: {_CLAUSES}")
        return 2

    rng = random.Random(20260803)

    # ① 적격 clause 풀 (content_hash → text). dedup 은 이미 돼 있다.
    pool: list[tuple[str, str]] = []
    with _CLAUSES.open(encoding="utf-8") as f:
        for line in f:
            c = json.loads(line)
            if not c.get("has_eligible"):
                continue
            if (c.get("source_kind") or "") != "clause":     # 부록 제외
                continue
            cl = c.get("char_length") or len(c.get("text") or "")
            if not (MIN_CHARS <= cl <= MAX_CHARS + 200):     # 제목 여유
                continue
            pool.append((c["content_hash"], c.get("text") or ""))

    rng.shuffle(pool)
    take = pool[: CORPUS_N * 2]                              # 제목 조인·본문 필터 후 줄어드니 오버샘플
    want = {h for h, _ in take}

    # ② occurrences 조인 — 대표 제목·보험사·sha256 (적격 등장만).
    titles: dict[str, Counter] = {}
    insurers: dict[str, Counter] = {}
    meta: dict[str, dict] = {}
    with _OCCUR.open(encoding="utf-8") as f:
        for line in f:
            o = json.loads(line)
            h = o.get("content_hash")
            if h not in want or not o.get("eligible"):
                continue
            t = (o.get("title") or "").strip()
            if t:
                titles.setdefault(h, Counter())[t] += 1
            ins = (o.get("insurer") or "").strip()
            if ins:
                insurers.setdefault(h, Counter())[ins] += 1
            meta.setdefault(h, {"sha256": o.get("sha256") or ""})

    # ③ 코퍼스 조립 — 대표 제목으로 앞머리 제거.
    corpus: list[dict] = []
    for h, text in take:
        tc = titles.get(h)
        if not tc:                                          # 적격 등장에 제목 없으면 제외
            continue
        title = tc.most_common(1)[0][0]
        body = _strip_head(text, title)
        if not (MIN_CHARS <= len(body) <= MAX_CHARS):
            continue
        ins = insurers.get(h)
        corpus.append({
            "id": h[:16],
            "title": title,
            "body": body,
            "insurer": ins.most_common(1)[0][0] if ins else "",
            "sha12": (meta.get(h, {}).get("sha256") or "")[:12],
        })
        if len(corpus) >= CORPUS_N:
            break

    # ④ 제목→본문 질의 — corpus 안에서 제목이 유일한 것만. 정답은 본문 동일 조항 전부.
    by_title: dict[str, list[dict]] = {}
    for c in corpus:
        by_title.setdefault(c["title"], []).append(c)
    unique = [v[0] for v in by_title.values() if len(v) == 1]
    rng.shuffle(unique)
    by_body: dict[str, list[str]] = {}
    for c in corpus:
        by_body.setdefault(c["body"], []).append(c["id"])
    queries = [
        {"query": c["title"], "gold_id": c["id"],
         "gold_ids": sorted(by_body.get(c["body"], [c["id"]]))}
        for c in unique[:QUERY_N]
    ]

    # ⑤ 뒷부분 민감도 탐침 — 「다만…」이 200자 이후에 있는 조항.
    probes: list[dict] = []
    for c in corpus:
        body = c["body"]
        m = None
        for cand in _PROVISO.finditer(body):
            if cand.start() >= 200:
                m = cand
                break
        if m is None:
            continue
        end = _SENT_END.search(body, m.end())
        tail = body[m.start(): (end.end() if end else min(len(body), m.start() + 200))]
        tail = " ".join(tail.split())
        if len(tail) < 30:
            continue
        head = body[: m.start()].strip()
        probes.append({"id": c["id"], "head": head, "with_proviso": head + " " + tail})
        if len(probes) >= 60:
            break

    # ⑥ 뒷부분 검색 질의 — 단서 문장 원문(표지 제거). 진짜 면책은 is_exclusion 표시.
    proviso_queries = []
    for pr in probes:
        tail = pr["with_proviso"][len(pr["head"]):].strip()
        q = re.sub(r"^(?:다만|단,|그러나|이 경우|또한)[,\s]*", "", tail).strip()
        if len(q) < 25:
            continue
        golds = sorted({c["id"] for c in corpus if q in c["body"]}) or [pr["id"]]
        proviso_queries.append({
            "query": q, "gold_id": pr["id"], "gold_ids": golds,
            "is_exclusion": bool(_NEGATION.search(q)),
        })

    out = {
        "built_at": "2026-08-03",
        "built_from": "s6 (shadow-s6_pymupdf-1.28.0)",
        "corpus_size": len(corpus),
        "query_count": len(queries),
        "proviso_probe_count": len(probes),
        "proviso_query_count": len(proviso_queries),
        "exclusion_query_count": sum(1 for q in proviso_queries if q["is_exclusion"]),
        "note": (
            "s6 clauses.jsonl(dedup, has_eligible, clause) + occurrences 조인. "
            "질의는 약관 원문 제목·문장이다(지어내지 않음). 본문 제목 문구 제거. "
            "정답은 gold_ids(복수). ★표본이 여전히 작다 — 순위 미세차는 단정 금지."
        ),
        "corpus": corpus,
        "queries": queries,
        "proviso_probes": probes,
        "proviso_queries": proviso_queries,
    }
    _OUT.parent.mkdir(parents=True, exist_ok=True)
    _OUT.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")

    dist = Counter(c["insurer"] for c in corpus)
    print(f"코퍼스 {len(corpus):,} · 제목질의 {len(queries)} · "
          f"뒷부분질의 {len(proviso_queries)}"
          f"(진짜 면책 {sum(1 for q in proviso_queries if q['is_exclusion'])}) · "
          f"탐침 {len(probes)}")
    print("보험사 분포(대표 등장 기준):")
    for ins, n in dist.most_common():
        print(f"  {ins or '(미상)':16} {n:>4}  ({n/len(corpus):.0%})")
    print(f"→ {_OUT.relative_to(_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())