"""임베딩 모델을 **하나씩** 재고, 다 재면 지운다.

    python -m scripts.eval.bench_embedders --model BAAI/bge-m3
    python -m scripts.eval.bench_embedders --model ... --purge      # 측정 후 캐시 삭제
    python -m scripts.eval.bench_embedders --list                   # 후보 목록
    python -m scripts.eval.bench_embedders --report                 # 지금까지 결과 표

★한 번에 하나만 받는다. 후보 10개를 다 받으면 수십 GB 다.
  `--purge` 를 주면 측정 직후 HuggingFace 캐시에서 지운다.

★측정하는 것

    recall@1/5/10 · MRR@10       조항 제목 → 본문 검색
    proviso_delta                면책 민감도. **1 - cos(앞부분, 앞부분+단서)**
                                 ★0 이면 모델이 뒷부분을 **전혀 안 본 것**이다.
                                   현재 모델(ko-sroberta 128토큰)이 정확히 0 이었다.
                                   면책은 늘 문장 끝에 오므로 이게 0 인 모델은 쓸 수 없다.
    truncated_ratio              코퍼스 중 모델 최대 길이를 넘어 잘린 비율
    max_seq_length               ★모델이 **실제로** 쓰는 값. 모델카드 숫자가 아니다.
    sec_per_1k                   처리량

★모델카드를 믿지 않고 실제 값을 찍는다.
  `ko-sroberta` 는 "512토큰"으로 알려져 있었지만 실제 설정은 **128** 이었다.

결과는 `data/eval/embed_bench_results/{모델}.json` 에 쌓인다(누적).
"""

from __future__ import annotations

import argparse
import json
import pathlib
import shutil
import time

_ROOT = pathlib.Path(__file__).resolve().parents[2]
_SET = _ROOT / "data" / "eval" / "embed_bench.json"
_OUT = _ROOT / "data" / "eval" / "embed_bench_results"

#: 후보. 순서는 우선순위가 아니라 **작은 것부터**다 — 디스크가 적을 때 먼저 끝난다.
CANDIDATES = [
    # (모델 ID, 대략 크기GB, 질의 접두, 문서 접두, 비고)
    ("ibm-granite/granite-embedding-311m-multilingual-r2", 1.3, "", "", "768d 유지"),
    ("Snowflake/snowflake-arctic-embed-l-v2.0", 2.3, "query: ", "", ""),
    ("dragonkue/snowflake-arctic-embed-l-v2.0-ko", 2.3, "query: ", "", "한국어 추가학습"),
    ("nlpai-lab/KURE-v1", 2.3, "", "", "한국어 추가학습"),
    ("dragonkue/BGE-m3-ko", 2.3, "", "", "한국어 추가학습"),
    ("BAAI/bge-m3", 2.3, "", "", ""),
    ("intfloat/multilingual-e5-large", 2.2, "query: ", "passage: ", "모델팀 선정 후보"),
    ("nlpai-lab/KoE5", 2.2, "query: ", "passage: ", ""),
    ("Qwen/Qwen3-Embedding-0.6B", 2.4, "", "", "instruction 지원"),
    ("jinaai/jina-embeddings-v5-text-small", 2.7, "", "", "★CC BY-NC 상업불가"),
    ("nvidia/Nemotron-3-Embed-1B-BF16", 4.0, "", "", "2026-07 신규"),
    ("google/embeddinggemma-300m", 1.2, "task: search result | query: ", "title: none | text: ", "게이트"),
    ("Qwen/Qwen3-Embedding-4B", 8.0, "", "", "★8GB 빠듯"),
    ("Qwen/Qwen3-Embedding-8B", 16.0, "", "", "★8GB 불가 — GPU 여유 있을 때만"),
    ("jhgan/ko-sroberta-multitask", 0.5, "", "", "★현재 모델. 회귀 기준선"),
]


def _slug(model_id: str) -> str:
    return model_id.replace("/", "__")


def _load_set() -> dict:
    if not _SET.exists():
        raise SystemExit(
            "평가셋이 없습니다. 먼저 만드세요: python -m scripts.eval.build_retrieval_set"
        )
    return json.loads(_SET.read_text(encoding="utf-8"))


def _purge(model_id: str) -> str:
    """HuggingFace 캐시에서 이 모델을 지운다."""
    from huggingface_hub import constants

    d = pathlib.Path(constants.HF_HUB_CACHE) / f"models--{model_id.replace('/', '--')}"
    if not d.exists():
        return "캐시 없음"
    size = sum(f.stat().st_size for f in d.rglob("*") if f.is_file())
    shutil.rmtree(d, ignore_errors=True)
    return f"{size/1e9:.1f}GB 삭제"


def run(model_id: str, *, q_prefix: str, d_prefix: str, batch: int, device: str) -> dict:
    import numpy as np
    import torch
    from sentence_transformers import SentenceTransformer

    data = _load_set()
    corpus = data["corpus"]
    queries = data["queries"]
    probes = data["proviso_probes"]

    t0 = time.time()
    kw = {"trust_remote_code": True}
    if device:
        kw["device"] = device
    model = SentenceTransformer(model_id, **kw)
    load_s = time.time() - t0

    #: ★모델카드가 아니라 **실제 설정값**을 찍는다.
    max_len = int(getattr(model, "max_seq_length", 0) or 0)
    dim = int(model.get_sentence_embedding_dimension())
    dev = str(model.device)

    tok = model.tokenizer
    body_tokens = [len(tok.encode(c["body"])) for c in corpus]
    truncated = sum(1 for n in body_tokens if max_len and n > max_len)

    def enc(texts: list[str]) -> "np.ndarray":
        return model.encode(
            texts, batch_size=batch, normalize_embeddings=True,
            convert_to_numpy=True, show_progress_bar=False,
        )

    t1 = time.time()
    doc_vecs = enc([d_prefix + c["body"] for c in corpus])
    enc_s = time.time() - t1
    q_vecs = enc([q_prefix + q["query"] for q in queries])

    ids = [c["id"] for c in corpus]
    pos = {cid: i for i, cid in enumerate(ids)}
    sims = q_vecs @ doc_vecs.T
    order = np.argsort(-sims, axis=1)

    r1 = r5 = r10 = 0
    mrr = 0.0
    for i, q in enumerate(queries):
        gold = pos.get(q["gold_id"])
        if gold is None:
            continue
        rank = int(np.where(order[i] == gold)[0][0]) + 1
        r1 += rank <= 1
        r5 += rank <= 5
        r10 += rank <= 10
        if rank <= 10:
            mrr += 1.0 / rank
    n = len(queries)

    #: ★면책 민감도. 0 이면 모델이 뒷부분을 안 본 것이다.
    h = enc([p["head"] for p in probes])
    w = enc([p["with_proviso"] for p in probes])
    deltas = 1.0 - np.sum(h * w, axis=1)
    blind = int(np.sum(deltas < 1e-6))

    res = {
        "model": model_id,
        "device": dev,
        "cuda": torch.cuda.is_available(),
        "gpu": torch.cuda.get_device_name(0) if torch.cuda.is_available() else "",
        "dim": dim,
        "max_seq_length": max_len,
        "load_sec": round(load_s, 1),
        "corpus": len(corpus),
        "queries": n,
        "truncated_ratio": round(truncated / len(corpus), 4),
        "body_tokens_p50": int(np.median(body_tokens)),
        "body_tokens_p90": int(np.percentile(body_tokens, 90)),
        "recall@1": round(r1 / n, 4),
        "recall@5": round(r5 / n, 4),
        "recall@10": round(r10 / n, 4),
        "mrr@10": round(mrr / n, 4),
        "proviso_delta_mean": round(float(np.mean(deltas)), 6),
        "proviso_delta_min": round(float(np.min(deltas)), 6),
        "proviso_blind_count": blind,
        "proviso_probes": len(probes),
        "sec_per_1k": round(enc_s / len(corpus) * 1000, 1),
        "q_prefix": q_prefix,
        "d_prefix": d_prefix,
    }
    _OUT.mkdir(parents=True, exist_ok=True)
    (_OUT / f"{_slug(model_id)}.json").write_text(
        json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return res


def report() -> None:
    rows = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(_OUT.glob("*.json"))]
    if not rows:
        print("아직 결과가 없습니다.")
        return
    rows.sort(key=lambda r: -r.get("mrr@10", 0))
    head = f"{'모델':52} {'차원':>5} {'최대':>5} {'R@1':>6} {'R@10':>6} {'MRR':>6} {'면책Δ':>8} {'잘림':>6} {'ms/건':>7}"
    print(head)
    print("-" * len(head))
    for r in rows:
        flag = " ★면책못봄" if r.get("proviso_blind_count", 0) > 0 else ""
        print(
            f"{r['model']:52} {r['dim']:>5} {r['max_seq_length']:>5} "
            f"{r['recall@1']:>6.3f} {r['recall@10']:>6.3f} {r['mrr@10']:>6.3f} "
            f"{r['proviso_delta_mean']:>8.5f} {r['truncated_ratio']:>6.1%} "
            f"{r['sec_per_1k']:>7.1f}{flag}"
        )
    print()
    print("면책Δ = 1 - cos(앞부분, 앞부분+단서). ★0 이면 모델이 뒷부분을 안 본 것이다.")
    print("잘림 = 코퍼스 중 모델 최대 길이를 넘은 비율.")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="임베딩 모델 벤치")
    ap.add_argument("--model")
    ap.add_argument("--batch", type=int, default=16)
    ap.add_argument("--device", default="")
    ap.add_argument("--purge", action="store_true", help="측정 후 캐시 삭제")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--report", action="store_true")
    a = ap.parse_args(argv)

    if a.list:
        print(f"{'모델':52} {'GB':>5}  비고")
        for m, gb, *_rest in CANDIDATES:
            print(f"{m:52} {gb:>5.1f}  {_rest[2]}")
        return 0
    if a.report:
        report()
        return 0
    if not a.model:
        ap.error("--model 이 필요합니다 (--list 로 후보 확인)")

    known = {c[0]: c for c in CANDIDATES}
    _, _, qp, dp, note = known.get(a.model, (a.model, 0, "", "", ""))
    print(f"[{a.model}] {note}", flush=True)

    res = run(a.model, q_prefix=qp, d_prefix=dp, batch=a.batch, device=a.device)
    print(json.dumps(res, ensure_ascii=False, indent=2))
    if res["proviso_blind_count"]:
        print(
            f"\n★경고: 면책 탐침 {res['proviso_blind_count']}/{res['proviso_probes']} 건에서 "
            "앞부분과 완전히 같은 벡터가 나왔습니다 — 모델이 뒷부분을 보지 않습니다."
        )
    if a.purge:
        print("[정리]", _purge(a.model))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
