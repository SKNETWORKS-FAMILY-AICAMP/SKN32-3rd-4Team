"""프로젝트 공식 설정 + 검색 모듈 (임베딩 단계 확정본)
- 확정 임베딩 모델: multilingual-e5-large (6모델 x 80문항 비교 1위)
- 다른 코드에서는 이 모듈만 import해서 사용할 것. 모델명·경로·접두사를
  각자 코드에 하드코딩하지 말 것.

사용 예:
    from rag_config import search, search_terms
    hits = search("통원 공제금액은?", insurer="삼성화재", generation="4세대")
    for h in hits:
        print(h["citation"], h["text"][:80])
"""
from functools import lru_cache

# ================= 확정 설정 (변경 시 여기만 수정) =================
EMBED_MODEL = "intfloat/multilingual-e5-large"   # 2026-08-02 확정
QUERY_PREFIX = "query: "        # e5 필수 접두사 (검색)
PASSAGE_PREFIX = "passage: "    # e5 필수 접두사 (색인)
DB_PATH = "chroma_full"
COLL_MAIN = "policy_e5"         # 본문+표 청크
COLL_TERMS = "terms_e5"         # 용어 정의 청크
TOP_K = 5
MAX_TOKENS = 512                # e5 입력 한도 (색인 전 분할 기준)
# ==================================================================


@lru_cache(maxsize=1)
def get_embedder():
    """임베딩 모델 (최초 1회만 로드)"""
    from sentence_transformers import SentenceTransformer
    return SentenceTransformer(EMBED_MODEL)


@lru_cache(maxsize=1)
def get_client():
    import chromadb
    return chromadb.PersistentClient(path=DB_PATH)


def _build_where(insurer=None, generation=None, **extra):
    conds = []
    if insurer:
        conds.append({"insurer": insurer})
    if generation:
        conds.append({"generation": generation})
    for k, v in extra.items():
        if v is not None:
            conds.append({k: v})
    if not conds:
        return None
    if len(conds) == 1:
        return conds[0]
    return {"$and": conds}          # Chroma 다중 조건 문법


def _query(coll_name, question, where, k):
    coll = get_client().get_collection(coll_name)
    qvec = get_embedder().encode([QUERY_PREFIX + question]).tolist()
    kw = {"query_embeddings": qvec, "n_results": k * 2}  # 중복 접기 여유분
    if where:
        kw["where"] = where
    res = coll.query(**kw)
    hits, seen = [], set()
    for m, d in zip(res["metadatas"][0], res["documents"][0]):
        raw = (m.get("term") or d[:50]).replace(" ", "")
        key = (raw[:15], m["insurer"], m["generation"])
        if key in seen:              # 동일 (내용, 보험사, 세대) 중복 접기
            continue
        seen.add(key)
        hits.append({"insurer": m["insurer"], "generation": m["generation"],
                     "content_type": m.get("content_type", ""),
                     "citation": m.get("citation") or f"용어: {m.get('term', '')}",
                     "term": m.get("term"), "text": d})
        if len(hits) >= k:
            break
    return hits


def search(question, insurer=None, generation=None, k=TOP_K):
    """본문 검색 (보장 내용·조항·표). 메타필터는 인자로."""
    return _query(COLL_MAIN, question, _build_where(insurer, generation), k)


def search_terms(question, k=TOP_K):
    """용어 정의 검색 ("~란?", "~의 정의" 류 질문용)"""
    return _query(COLL_TERMS, question, None, k)


if __name__ == "__main__":
    # 자가 테스트: python rag_config.py
    print(f"모델: {EMBED_MODEL} / DB: {DB_PATH}")
    for h in search("통원 공제금액은 얼마인가요?", insurer="삼성화재", k=3):
        print(f"  [{h['insurer']}|{h['generation']}] {h['citation'][:40]} | {h['text'][:60]!r}")
    for h in search_terms("진단계약이란?", k=2):
        print(f"  [용어] {h['citation']} | {h['text'][:60]!r}")