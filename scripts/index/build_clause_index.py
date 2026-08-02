"""인덱스 A 적재 — 약관 조항을 pgvector 에 올린다.

    python -m scripts.index.build_clause_index            # 전량(재개 가능)
    python -m scripts.index.build_clause_index --limit 500   # 맛보기
    python -m scripts.index.build_clause_index --stats       # 현황만

★고유 내용만 임베딩한다

    실측(s5 전량): 조항 등장 **211,131** / 고유 **73,031** — 중복 65.4%.
    등장마다 임베딩하면 같은 계산을 3배 한다.
    `parse_status == "ok"` 문서의 고유 조항 **52,899** 가 대상이다.

★재개 가능하다

    이미 들어간 `content_hash` 는 건너뛴다. 27분짜리 작업이 중간에 끊겨도
    처음부터 다시 하지 않는다. 끊긴 것을 모르고 "다 됐다"고 하지 않기 위해
    **끝에 현황을 다시 세어 출력한다.**

★건너뛴 것을 **센다**

    조용한 스킵을 만들지 않는다(CLAUDE.md §3). 세지 않으면 분모가 줄어
    커버리지가 실제보다 좋아 보인다.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys
import time

_ROOT = pathlib.Path(__file__).resolve().parents[2]
_STRUCT = _ROOT / "data" / "structured"

#: 한 번에 임베딩할 조각 수. 크게 잡아도 처리량은 비슷하고 메모리만 는다.
_BATCH = 256


def _iter_docs(limit: int | None):
    files = sorted(_STRUCT.glob("*/s5_*/*.clauses.json"))
    if limit:
        files = files[:limit]
    for p in files:
        yield p, json.loads(p.read_text(encoding="utf-8"))


def _chunks(text: str, size: int, overlap: int) -> list[str]:
    if len(text) <= size:
        return [text]
    out, i = [], 0
    while i < len(text):
        out.append(text[i : i + size])
        i += size - overlap
    return out


def main(argv: list[str] | None = None) -> int:
    from app.adapters import pgvector_clause_index as ix
    from app.adapters.pgvector_index import get_conn

    ap = argparse.ArgumentParser(description="인덱스 A 적재")
    ap.add_argument("--limit", type=int, default=0, help="문서 수 제한(맛보기)")
    ap.add_argument("--stats", action="store_true", help="현황만 출력")
    args = ap.parse_args(argv)

    conn = get_conn()
    ix.ensure_schema(conn)

    if args.stats:
        print(json.dumps(ix.stats(conn), ensure_ascii=False, indent=2))
        return 0

    #: ★먼저 **문서에서 모은다.** 임베딩은 그다음이다 —
    #:   중복 제거를 하기 전에 임베딩하면 3배를 계산한다.
    texts: dict[str, str] = {}
    occurrences: list[tuple] = []
    n_docs = n_skip_doc = n_clause = n_skip_clause = 0

    for p, doc in _iter_docs(args.limit or None):
        status = doc.get("parse_status") or "unknown"
        if status != "ok":
            #: ★추출이 의심스러운 문서의 조항은 판정 근거가 될 수 없다.
            n_skip_doc += 1
            continue
        n_docs += 1
        src = doc.get("source") or {}
        sha = src.get("sha256") or ""
        insurer = src.get("insurer") or ""
        for c in doc.get("clauses") or []:
            h = c.get("content_hash") or ""
            body = c.get("text") or ""
            if not h or not body.strip():
                n_skip_clause += 1
                continue
            n_clause += 1
            texts.setdefault(h, body)
            loc = c.get("locator") or {}
            occurrences.append(
                (
                    h,
                    sha,
                    insurer,
                    c.get("qualified_no") or "",
                    c.get("section") or "",
                    c.get("title") or "",
                    int(loc.get("page_from") or c.get("page_from") or 0),
                    int(loc.get("page_to") or c.get("page_to") or 0),
                )
            )

    print(
        f"[모음] ok 문서 {n_docs:,} (건너뜀 {n_skip_doc:,}) · "
        f"조항 등장 {n_clause:,} → 고유 {len(texts):,} "
        f"(내용/해시 없음 {n_skip_clause:,})",
        flush=True,
    )

    n_occ = ix.upsert_occurrences(conn, occurrences)
    print(f"[발생] {n_occ:,}행 새로 기록 (총 {len(occurrences):,}건 시도)", flush=True)

    done = ix.existing_hashes(conn)
    todo = [(h, t) for h, t in texts.items() if h not in done]
    print(f"[임베딩] 이미 있음 {len(done):,} · 할 것 {len(todo):,}", flush=True)
    if not todo:
        print(json.dumps(ix.stats(conn), ensure_ascii=False, indent=2))
        return 0

    from app.rag.embeddings import get_embeddings

    embed = get_embeddings()

    pending: list[tuple[str, int, str]] = []
    for h, body in todo:
        for i, part in enumerate(_chunks(body, ix.CHUNK_SIZE, ix.CHUNK_OVERLAP)):
            pending.append((h, i, part))
    print(f"[임베딩] 조각 {len(pending):,}개", flush=True)

    t0 = time.time()
    written = 0
    for s in range(0, len(pending), _BATCH):
        batch = pending[s : s + _BATCH]
        vecs = embed.embed_documents([b[2] for b in batch])
        written += ix.upsert_chunks(conn, [(b[0], b[1], b[2], v) for b, v in zip(batch, vecs)])
        done_n = s + len(batch)
        el = time.time() - t0
        rate = done_n / el if el else 0
        left = (len(pending) - done_n) / rate if rate else 0
        print(
            f"  {done_n:,}/{len(pending):,} 조각 · {rate:.0f}/s · 남은 시간 {left/60:.1f}분",
            flush=True,
        )

    print(f"[완료] {written:,}조각 기록 · {(time.time()-t0)/60:.1f}분", flush=True)
    #: ★끝에 **다시 세어** 출력한다. 중간에 끊겼는지 여기서 드러난다.
    print(json.dumps(ix.stats(conn), ensure_ascii=False, indent=2))
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
