"""s6 최종 임베딩 v2 — PG 적재용 **조각(청크) 단위** 벡터를 만든다.

    python embed_s6_chunks.py          # /workspace 에서

산출:
  s6_chunks_arctic-ko.jsonl        (content_hash · seq · n_chunks · text)
  s6_chunks_arctic-ko_vectors.npz  (vectors fp16 · content_hash · seq — jsonl 과 행 일치)
  s6_chunks_arctic-ko.meta.json

★청킹 규칙: 팀 프로필 chunk_budget=448 토큰 · overlap=80 (stride 368).
  토크나이저는 임베딩 모델 자신의 것. 조각 텍스트는 토큰을 되붙인 게 아니라
  offset 으로 **원문에서 그대로 잘라** 인용 시 원문과 어긋나지 않는다.
★대상: has_eligible=true. 접두어: 문서 없음(질의만 "query: " — 검색 시점).
"""
import json, time
import numpy as np
import torch
from sentence_transformers import SentenceTransformer

MODEL = "dragonkue/snowflake-arctic-embed-l-v2.0-ko"
BUDGET, OVERLAP = 448, 80
STRIDE = BUDGET - OVERLAP
SRC = "/workspace/clauses.jsonl"
OUT = "/workspace/s6_chunks_arctic-ko"

model = SentenceTransformer(MODEL, device="cuda",
                            model_kwargs={"torch_dtype": torch.float16})
tok = model.tokenizer

rows = []                     # (hash, seq, n_chunks, chunk_text)
n_clauses = 0
with open(SRC, encoding="utf-8") as f:
    for line in f:
        c = json.loads(line)
        if not c.get("has_eligible"):
            continue
        n_clauses += 1
        h = c["content_hash"]
        text = (c.get("text") or "").strip()
        offs = tok(text, add_special_tokens=False,
                   return_offsets_mapping=True)["offset_mapping"]
        if len(offs) <= BUDGET:
            chunks = [text]
        else:
            chunks, i = [], 0
            while i < len(offs):
                j = min(i + BUDGET, len(offs))
                chunks.append(text[offs[i][0]: offs[j - 1][1]])
                if j == len(offs):
                    break
                i += STRIDE
        for k, ch in enumerate(chunks):
            rows.append((h, k, len(chunks), ch))

print(f"적격 조항 {n_clauses:,} → 조각 {len(rows):,} (평균 {len(rows)/n_clauses:.2f})")

t0 = time.time()
vecs = model.encode([r[3] for r in rows], batch_size=32,
                    normalize_embeddings=True, convert_to_numpy=True,
                    show_progress_bar=True)
print(f"인코딩 {time.time()-t0:.0f}초 · shape={vecs.shape}")

np.savez_compressed(
    OUT + "_vectors.npz",
    vectors=vecs.astype(np.float16),
    content_hash=np.array([r[0] for r in rows]),
    seq=np.array([r[1] for r in rows], dtype=np.int32),
    n_chunks=np.array([r[2] for r in rows], dtype=np.int32),
)
with open(OUT + ".jsonl", "w", encoding="utf-8") as f:
    for h, k, n, ch in rows:
        f.write(json.dumps({"content_hash": h, "seq": k,
                            "n_chunks": n, "text": ch},
                           ensure_ascii=False) + "\n")

meta = {
    "model": MODEL, "dtype": "float16", "dim": int(vecs.shape[1]),
    "normalized": True, "doc_prefix": "", "query_prefix": "query: ",
    "chunk_budget": BUDGET, "overlap": OVERLAP,
    "tokenizer": "모델 자체 토크나이저 · offset 기반 원문 슬라이스",
    "clauses": n_clauses, "chunks": len(rows),
    "source": "s6 shadow-s6_pymupdf-1.28.0 · clauses.jsonl has_eligible=true",
    "gpu": torch.cuda.get_device_name(0), "built_at": "2026-08-03",
}
with open(OUT + ".meta.json", "w", encoding="utf-8") as f:
    json.dump(meta, f, ensure_ascii=False, indent=2)
print("저장 완료:", OUT + "_vectors.npz / .jsonl / .meta.json")