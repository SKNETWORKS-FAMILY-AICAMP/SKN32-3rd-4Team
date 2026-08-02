"""임베딩 모델 비교 v2: 12종 로더 + chunk_id 일치 채점
사용: python embed_eval.py --models e5-large,qwen3-embed-4b --questions eval_questions_v5.json"""
import argparse
import csv
import json
import time
from pathlib import Path

import chromadb

TOP_K = 5


# ---------------- 로더 헬퍼 ----------------
def st_loader(model_name, query_style=None, batch=32, trust=False):
    """sentence-transformers 공통 로더.
    query_style: None | "prompt"(내장 query 프롬프트) | "prefix:<str>"(질문 접두사)
    문서는 항상 plain (e5만 별도 passage 접두사 처리)"""
    def load():
        from sentence_transformers import SentenceTransformer
        kw = {"trust_remote_code": True} if trust else {}
        m = SentenceTransformer(model_name, **kw)

        def embed(texts):
            is_query = len(texts) == 1
            if is_query and query_style == "prompt":
                try:
                    return m.encode(texts, prompt_name="query",
                                    show_progress_bar=False).tolist()
                except Exception:
                    pass
            if is_query and query_style and query_style.startswith("prefix:"):
                texts = [query_style[7:] + texts[0]]
            return m.encode(texts, batch_size=batch,
                            show_progress_bar=not is_query).tolist()
        return embed
    return load


def load_e5():
    from sentence_transformers import SentenceTransformer
    m = SentenceTransformer("intfloat/multilingual-e5-large")

    def embed(texts):
        if len(texts) == 1:
            texts = ["query: " + texts[0]]
        else:
            texts = ["passage: " + t for t in texts]
        return m.encode(texts, batch_size=32,
                        show_progress_bar=len(texts) > 1).tolist()
    return embed


def load_jina_v5():
    from sentence_transformers import SentenceTransformer
    m = SentenceTransformer("jinaai/jina-embeddings-v5-text-small",
                            trust_remote_code=True)

    def embed(texts):
        is_query = len(texts) == 1
        kw = {"task": "retrieval", "batch_size": 32,
              "show_progress_bar": not is_query}
        if is_query:
            kw["prompt_name"] = "query"     # 문서는 기본 prompt('document') 사용
        try:
            return m.encode(texts, **kw).tolist()
        except TypeError:                    # 인자 미지원 버전 대비
            return m.encode(texts, batch_size=32,
                            show_progress_bar=not is_query).tolist()
    return embed


def load_openai_small():
    from openai import OpenAI
    client = OpenAI()

    def embed(texts):
        out = []
        for i in range(0, len(texts), 100):
            r = client.embeddings.create(model="text-embedding-3-small",
                                         input=texts[i:i + 100])
            out.extend(d.embedding for d in r.data)
        return out
    return embed


MODELS = {
    # 기존 6종
    "e5-large": load_e5,
    "bge-m3": st_loader("BAAI/bge-m3"),
    "kure-v1": st_loader("nlpai-lab/KURE-v1"),
    "ko-sroberta": st_loader("jhgan/ko-sroberta-multitask", batch=64),
    "qwen3-embed-0.6b": st_loader("Qwen/Qwen3-Embedding-0.6B", query_style="prompt"),
    "openai-3-small": load_openai_small,
    # 신규 6종 (SOTA 10선 반영)
    "qwen3-embed-4b": st_loader("Qwen/Qwen3-Embedding-4B", query_style="prompt", batch=8),
    "nemotron-1b": st_loader("nvidia/Nemotron-3-Embed-1B-BF16", trust=True, batch=16),
    "jina-v5-small": load_jina_v5,
    "granite-311m": st_loader("ibm-granite/granite-embedding-311m-multilingual-r2", batch=64),
    "arctic-l-v2": st_loader("Snowflake/snowflake-arctic-embed-l-v2.0", query_style="prompt"),
    "arctic-ko": st_loader("dragonkue/snowflake-arctic-embed-l-v2.0-ko", query_style="prompt"),
}


# ---------------- 채점 ----------------
def base_id(indexed_id):
    """색인 시 붙인 위치 접미사(::숫자) 제거 -> 원본 chunk_id"""
    head, sep, tail = indexed_id.rpartition("::")
    return head if sep and tail.isdigit() else indexed_id


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", default=r"out\eval_sample.jsonl")
    ap.add_argument("--questions", default="eval_questions_v5.json")
    ap.add_argument("--models", default="e5-large")
    ap.add_argument("--db", default="chroma_eval")
    args = ap.parse_args()

    chunks = [json.loads(l) for l in open(args.sample, encoding="utf-8")]
    print(f"샘플 {len(chunks)}청크 로드")
    questions = json.loads(Path(args.questions).read_text(encoding="utf-8"))
    n_ids = sum("answer_ids" in q for q in questions)
    print(f"문항 {len(questions)}개 (chunk_id 채점: {n_ids}개)")

    client = chromadb.PersistentClient(path=args.db)
    rows = []

    for name in [m.strip() for m in args.models.split(",")]:
        print(f"\n{'=' * 55}\n[모델] {name}")
        try:
            embed = MODELS[name]()
        except Exception as e:
            print(f"  로드 실패: {e}")
            continue
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
            b = chunks[i:i + 1000]
            coll.add(ids=[f"{c['chunk_id']}::{i + j}" for j, c in enumerate(b)],
                     embeddings=vecs[i:i + 1000],
                     documents=[c["text"] for c in b],
                     metadatas=[{"insurer": c["insurer"],
                                 "generation": c["generation"],
                                 "content_type": c["content_type"],
                                 "citation": c.get("citation") or ""} for c in b])
        print(f"  색인 {len(chunks)}개, 임베딩 {embed_s:.1f}초")

        for q in questions:
            t0 = time.time()
            qvec = embed([q["query"]])[0]
            kw = {"query_embeddings": [qvec], "n_results": TOP_K}
            if q.get("where"):
                w = q["where"]
                if len(w) > 1:
                    w = {"$and": [{k: v} for k, v in w.items()]}
                kw["where"] = w
            res = coll.query(**kw)
            q_ms = (time.time() - t0) * 1000

            answers = set(q["answer_ids"])
            rank = 0
            for r, rid in enumerate(res["ids"][0], start=1):
                if base_id(rid) in answers:
                    rank = r
                    break
            rows.append({"model": name, "qid": q["id"], "type": q["type"],
                         "hit@5": int(rank > 0), "first_hit_rank": rank or "-",
                         "query_ms": round(q_ms)})
        h = sum(r["hit@5"] for r in rows if r["model"] == name)
        print(f"  hit@5: {h}/{len(questions)}")

    out_dir = Path("out"); out_dir.mkdir(exist_ok=True)
    out = out_dir / "results_v2.csv"
    exists = out.exists()
    with open(out, "a", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        if not exists:
            w.writeheader()
        w.writerows(rows)
    print(f"\n결과 누적 저장: {out} (analyze_results.py로 집계)")


if __name__ == "__main__":
    main()