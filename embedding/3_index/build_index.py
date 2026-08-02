"""e5-large 2컬렉션 색인: main -> policy_e5 / terms -> terms_e5 (이어하기 지원)
사용: python build_index.py            # 두 컬렉션 순차 색인/재개
     python build_index.py --status   # 진행 상태 확인"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import argparse
import json
import time

import chromadb
from sentence_transformers import SentenceTransformer
from rag_config import EMBED_MODEL, PASSAGE_PREFIX, DB_PATH


TARGETS = [
    (r"data\main_indexready.jsonl", "policy_e5"),
    (r"data\terms_indexready.jsonl", "terms_e5"),
]
BATCH = 500
MIN_CHARS = 5


def load_chunks(path):
    with open(path, encoding="utf-8") as f:
        for line in f:
            c = json.loads(line)
            if len(c["text"].strip()) >= MIN_CHARS:
                yield c


def get_existing_ids(coll):
    existing = set()
    n = coll.count()
    offset = 0
    while offset < n:
        page = coll.get(limit=10000, offset=offset, include=[])
        existing.update(page["ids"])
        offset += 10000
    return existing


def meta_of(c):
    m = {"insurer": c["insurer"],
         "generation": c["generation"],
         "content_type": c["content_type"],
         "citation": c.get("citation") or "",
         "doc_name": (c.get("doc_name") or "")[:80]}
    if c.get("term"):
        m["term"] = c["term"]
    return m


def index_file(client, model, path, coll_name):
    coll = client.get_or_create_collection(coll_name,
                                           metadata={"hnsw:space": "cosine"})
    print(f"\n=== {coll_name} <- {path}")
    existing = get_existing_ids(coll)
    print(f"이미 색인됨: {len(existing)}")
    todo = [c for c in load_chunks(path) if c["chunk_id"] not in existing]
    total = len(todo)
    print(f"색인 대상: {total}")
    if not total:
        print("완료 상태.")
        return

    done = 0
    t0 = time.time()
    for i in range(0, total, BATCH):
        batch = todo[i:i + BATCH]
        vecs = model.encode([PASSAGE_PREFIX + c["text"] for c in batch],
                            batch_size=32, show_progress_bar=False).tolist()
        coll.add(ids=[c["chunk_id"] for c in batch],
                 embeddings=vecs,
                 documents=[c["text"] for c in batch],
                 metadatas=[meta_of(c) for c in batch])
        done += len(batch)
        el = time.time() - t0
        eta = el / done * (total - done)
        print(f"  {done}/{total} ({done/total:.1%})  경과 {el/60:.1f}분  "
              f"잔여 약 {eta/60:.0f}분", flush=True)
    print(f"{coll_name} 완료: 총 {coll.count()}청크")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--status", action="store_true")
    args = ap.parse_args()

    client = chromadb.PersistentClient(path=DB_PATH)
    if args.status:
        for _, name in TARGETS:
            try:
                print(f"{name}: {client.get_collection(name).count()}청크")
            except Exception:
                print(f"{name}: (없음)")
        return

    print("로딩 중...")
    model = SentenceTransformer(EMBED_MODEL)
    for path, name in TARGETS:
        index_file(client, model, path, name)
    print("\n전체 색인 완료.")


if __name__ == "__main__":
    main()