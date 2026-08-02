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
import re
from functools import lru_cache
import hashlib 

# ================= 확정 설정 (변경 시 여기만 수정) =================
EMBED_MODEL = "intfloat/multilingual-e5-large"   # 2026-08-02 확정
QUERY_PREFIX = "query: "        # e5 필수 접두사 (검색)
PASSAGE_PREFIX = "passage: "    # e5 필수 접두사 (색인)
from pathlib import Path
_ROOT = Path(__file__).parent.parent       # embedding\ 의 상위 = 프로젝트 루트
DB_PATH = str(_ROOT / "chroma_full")
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
        key = (hashlib.md5(d.encode()).hexdigest()[:12], m["insurer"], m["generation"])
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

def _norm(s):
    """용어 비교용 정규화: 공백·괄호 제거"""
    return re.sub(r"[\s()\[\]「」『』]", "", s or "")


def extract_query_term(question):
    """질문에서 용어 부분 추출: '기왕증이란?' -> '기왕증'"""
    m = re.match(r"^(.+?)(이란|란|의 정의|이 뭐|가 뭐|은 무슨|는 무슨)", question.strip())
    return m.group(1).strip() if m else question.strip().rstrip("?")


def search_terms_guarded(question, k=TOP_K):
    """용어 검색 + 일치 가드: 질문 용어와 다른 정의는 차단.
    반환: (hits, guard_note) — hits가 비면 호출측은 '확인 불가' 응답."""
    q_term = _norm(extract_query_term(question))
    hits = search_terms(question, k=k)
    matched = [h for h in hits
               if q_term and (q_term in _norm(h.get("term")) or _norm(h.get("term")) in q_term)]
    if matched:
        return matched, "ok"
    found = ", ".join(sorted({h.get("term") or "?" for h in hits})[:3])
    return [], f"용어 불일치 차단 (질문: {q_term} / 검색됨: {found})"


@lru_cache(maxsize=1)
def get_insurers():
    """색인된 보험사 목록 (컬렉션 메타에서 자동 추출)"""
    coll = get_client().get_collection(COLL_MAIN)
    seen = set()
    n = coll.count()
    for offset in range(0, min(n, 50000), 10000):
        page = coll.get(limit=10000, offset=offset, include=["metadatas"])
        seen.update(m["insurer"] for m in page["metadatas"])
    return sorted(seen)


if __name__ == "__main__":
    # 자가 테스트: python rag_config.py
    print(f"모델: {EMBED_MODEL} / DB: {DB_PATH}")
    for h in search("통원 공제금액은 얼마인가요?", insurer="삼성화재", k=3):
        print(f"  [{h['insurer']}|{h['generation']}] {h['citation'][:40]} | {h['text'][:60]!r}")
    for h in search_terms("진단계약이란?", k=2):
        print(f"  [용어] {h['citation']} | {h['text'][:60]!r}")