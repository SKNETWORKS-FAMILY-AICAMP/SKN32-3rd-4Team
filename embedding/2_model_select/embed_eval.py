"""임베딩 모델 비교: 샘플 색인 -> 질문 검색 -> hit@k 채점"""
import argparse
import csv
import json
import time
from pathlib import Path

import chromadb

TOP_K = 5


def load_bge_m3():
    from sentence_transformers import SentenceTransformer
    m = SentenceTransformer("BAAI/bge-m3")
    return lambda texts: m.encode(texts, batch_size=32,
                                  show_progress_bar=True).tolist()


def load_ko_sroberta():
    from sentence_transformers import SentenceTransformer
    m = SentenceTransformer("jhgan/ko-sroberta-multitask")
    return lambda texts: m.encode(texts, batch_size=64,
                                  show_progress_bar=True).tolist()


def load_openai_small():
    from openai import OpenAI
    client = OpenAI()  # OPENAI_API_KEY 환경변수 사용

    def embed(texts):
        out = []
        for i in range(0, len(texts), 100):
            resp = client.embeddings.create(model="text-embedding-3-small",
                                            input=texts[i:i + 100])
            out.extend(d.embedding for d in resp.data)
        return out
    return embed


def load_kure():
    from sentence_transformers import SentenceTransformer
    m = SentenceTransformer("nlpai-lab/KURE-v1")
    return lambda texts: m.encode(texts, batch_size=32,
                                  show_progress_bar=True).tolist()


def load_e5_large():
    from sentence_transformers import SentenceTransformer
    m = SentenceTransformer("intfloat/multilingual-e5-large")

    def embed(texts):
        # e5는 접두사 필요: 문서=passage, 질문=query
        # 단건(질문)과 다건(문서) 구분
        if len(texts) == 1:
            texts = ["query: " + texts[0]]
        else:
            texts = ["passage: " + t for t in texts]
        return m.encode(texts, batch_size=32, show_progress_bar=True).tolist()
    return embed


def load_qwen3_06b():
    from sentence_transformers import SentenceTransformer
    m = SentenceTransformer("Qwen/Qwen3-Embedding-0.6B")
    return lambda texts: m.encode(texts, batch_size=32,
                                  show_progress_bar=True).tolist()


MODELS = {
    "bge-m3": load_bge_m3,
    "ko-sroberta": load_ko_sroberta,
    "openai-3-small": load_openai_small,
    "kure-v1": load_kure,
    "e5-large": load_e5_large,
    "qwen3-embed-0.6b": load_qwen3_06b,
}

def match(meta, text, expect):
    for k, v in expect.items():
        if k == "text_contains":
            if v not in text:
                return False
        elif k == "citation_contains":
            if v not in (meta.get("citation") or ""):
                return False
        elif meta.get(k) != v:
            return False
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", default=r"out\eval_sample.jsonl")
    ap.add_argument("--questions", default="eval_questions.json")
    ap.add_argument("--models", default="ko-sroberta",
                    help="쉼표 구분: bge-m3,ko-sroberta,openai-3-small")
    ap.add_argument("--db", default="chroma_eval")
    args = ap.parse_args()

    chunks = []
    with open(args.sample, encoding="utf-8") as f:
        for line in f:
            chunks.append(json.loads(line))
    print(f"샘플 {len(chunks)}청크 로드")
    print(f"generation 고유값: {sorted({c['generation'] for c in chunks})}")
    print(f"insurer 고유값: {sorted({c['insurer'] for c in chunks})}")

    questions = json.loads(Path(args.questions).read_text(encoding="utf-8"))
    client = chromadb.PersistentClient(path=args.db)
    rows = []

    for name in [m.strip() for m in args.models.split(",")]:
        print(f"\n{'=' * 55}\n[모델] {name}")
        embed = MODELS[name]()
        coll_name = "eval_" + name.replace(".", "_").replace("-", "_")
        try:
            client.delete_collection(coll_name)
        except Exception:
            pass
        coll = client.create_collection(coll_name, metadata={"hnsw:space": "cosine"})

        t0 = time.time()
        vecs = embed([c["text"] for c in chunks])
        embed_s = time.time() - t0
        for i in range(0, len(chunks), 1000):
            batch = chunks[i:i + 1000]
            coll.add(
                ids=[f"{c['chunk_id']}::{i + j}" for j, c in enumerate(batch)],
                embeddings=vecs[i:i + 1000],
                documents=[c["text"] for c in batch],
                metadatas=[{"insurer": c["insurer"], "generation": c["generation"],
                            "content_type": c["content_type"],
                            "citation": c.get("citation") or ""} for c in batch],
            )
        print(f"  색인 완료: {len(chunks)}개, 임베딩 {embed_s:.1f}초")

        for q in questions:
            t0 = time.time()
            qvec = embed([q["query"]])[0]
            kw = {"query_embeddings": [qvec], "n_results": TOP_K}
            if q["where"]:
                w = q["where"]
                if len(w) > 1:  # 조건 2개 이상이면 Chroma $and 문법 필요
                    w = {"$and": [{k: v} for k, v in w.items()]}
                kw["where"] = w
            res = coll.query(**kw)
            q_ms = (time.time() - t0) * 1000

            metas = res["metadatas"][0]
            docs = res["documents"][0]
            rank = 0
            for r, (m, d) in enumerate(zip(metas, docs), start=1):
                if match(m, d, q["expect"]):
                    rank = r
                    break
            top1 = (metas[0].get("citation") or "")[:40] if metas else "-"
            rows.append({"model": name, "qid": q["id"], "type": q["type"],
                         "hit@5": int(rank > 0), "first_hit_rank": rank or "-",
                         "query_ms": round(q_ms), "top1_citation": top1})
            mark = "O" if rank else "X"
            print(f"  [{mark}] {q['id']} {q['type']:<8} rank={rank or '-'} top1={top1}")

    out = f"out\\results_{args.models.replace(',', '_')}.csv"
    with open(out, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    print(f"\n{'=' * 55}\n모델별 hit@5")
    for name in sorted({r["model"] for r in rows}):
        sub = [r for r in rows if r["model"] == name]
        h = sum(r["hit@5"] for r in sub)
        print(f"  {name:<16} {h}/{len(sub)}")
    print(f"결과 저장: {out}")


if __name__ == "__main__":
    main()