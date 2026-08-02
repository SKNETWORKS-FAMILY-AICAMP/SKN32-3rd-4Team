"""임베딩 모델 비교용 평가셋 — **우리 약관에서** 만든다.

    python -m scripts.eval.build_retrieval_set

★남의 벤치마크로 고르지 않는다.

    KURE 8-subset · MTEB-Korean 9-subset · MLEB 어느 것도
    **한국어 실손보험 약관을 재지 않는다.** 위키·뉴스·일반 법률에서 이긴 모델이
    약관에서도 이긴다는 보장이 없다.

★질의를 **지어내지 않는다.**

    LLM 으로 질문을 만들면 그 LLM 의 표현 습관을 잘 맞히는 모델이 이긴다.
    평가가 모델이 아니라 **질문 생성기**를 재게 된다.
    그래서 문서에 **이미 적혀 있는 것**만 쓴다.

두 가지를 만든다.

  ① 제목 → 본문 검색
     질의 = 조항 제목("보상하지 않는 사항"), 정답 = 그 조항 본문.
     ★본문 앞의 제목 문구는 **지운다.** 안 지우면 글자만 겹쳐 봐도 맞아
       임베딩 품질을 재는 게 아니라 문자열 일치를 재게 된다.

  ② 면책 민감도 탐침
     같은 조항의 앞부분과, 거기에 「다만 … 보상하지 않습니다」를 붙인 것.
     ★두 벡터가 **같으면 모델이 뒷부분을 안 본 것**이다.
       현재 모델(`ko-sroberta`, 128토큰)이 정확히 그랬다 — 유사도 1.000000.
       면책은 늘 문장 끝에 오므로, 이걸 못 보는 모델은 우리 과제에 쓸 수 없다.

산출물: data/eval/embed_bench.json
"""

from __future__ import annotations

import json
import pathlib
import random
import re

_ROOT = pathlib.Path(__file__).resolve().parents[2]
_STRUCT = _ROOT / "data" / "structured"
_OUT = _ROOT / "data" / "eval" / "embed_bench.json"

#: 후보 조항 수. CPU 로 여러 모델을 돌려야 하므로 현실적인 크기로 자른다.
#: ★작다는 것을 숨기지 않는다 — 산출물에 그대로 적는다.
CORPUS_N = 2000
QUERY_N = 200

#: 너무 짧은 조항은 제목만 있는 껍데기일 수 있다.
MIN_CHARS = 120
#: 너무 긴 것은 모델별 최대 길이 차이가 결과를 지배한다. 별도로 봐야 한다.
MAX_CHARS = 3000

#: 본문 맨 앞의 「N. (제목)」 표기. 질의와 글자가 겹치므로 지운다.
_HEAD = re.compile(r"^\s*[\d가-힣]+[.\)]?\s*[（(]?[^)）\n]{0,40}[)）]?\s*")
#: 단서·면책이 시작하는 자리.
#:
#: ★처음엔 「다만 … 보상하지 않습니다」로 끝나는 것만 찾았는데 **0건**이었다.
#:   본문에 줄바꿈이 섞여 있어 `.` 이 안 넘어갔고(DOTALL 누락), 끝맺음도
#:   "않습니다" 말고 "제외합니다"·"한합니다" 등 여러 가지였다.
#:   실측: 코퍼스 2,000개 중 **884개**에 「다만」이 있다. 규칙이 좁았던 것이다.
#:   탐침의 목적은 "모델이 뒷부분을 보는가"이므로 끝맺음을 좁힐 이유가 없다.
_PROVISO = re.compile(r"다만[,\s]", re.DOTALL)
#: 단서 문장의 끝. 여기까지를 꼬리로 삼는다.
_SENT_END = re.compile(r"(?:니다|합니다|습니다)[.\s]")


def _strip_head(text: str, title: str) -> str:
    """본문 앞에 붙은 제목 문구를 지운다."""
    body = text
    m = _HEAD.match(body)
    if m and title and title[:6] in m.group(0):
        body = body[m.end() :]
    #: 남아 있는 제목 반복도 한 번만 지운다.
    if title and body.lstrip().startswith(title):
        body = body.lstrip()[len(title) :]
    return body.strip()


def main() -> int:
    files = sorted(_STRUCT.glob("*/s5_*/*.clauses.json"))
    if not files:
        print("s5 산출물이 없습니다.")
        return 2

    rng = random.Random(20260802)
    rng.shuffle(files)

    pool: list[dict] = []
    seen_hash: set[str] = set()
    n_doc = 0
    for p in files:
        if len(pool) >= CORPUS_N * 2:
            break
        d = json.loads(p.read_text(encoding="utf-8"))
        if (d.get("parse_status") or "") != "ok":
            continue
        n_doc += 1
        src = d.get("source") or {}
        for c in d.get("clauses") or []:
            h = c.get("content_hash") or ""
            title = (c.get("title") or "").strip()
            text = c.get("text") or ""
            #: ★중복 65.4% 이므로 같은 내용을 여러 번 넣으면 정답이 모호해진다.
            if not h or h in seen_hash or not title:
                continue
            body = _strip_head(text, title)
            if not (MIN_CHARS <= len(body) <= MAX_CHARS):
                continue
            seen_hash.add(h)
            pool.append(
                {
                    "id": h[:16],
                    "title": title,
                    "body": body,
                    "insurer": src.get("insurer") or "",
                    "sha12": (src.get("sha256") or "")[:12],
                    "qualified_no": c.get("qualified_no") or "",
                    "statute": bool(c.get("statute")),
                }
            )

    rng.shuffle(pool)
    corpus = pool[:CORPUS_N]

    #: ★질의로 쓸 제목은 **corpus 안에서 유일해야** 한다.
    #:   같은 제목이 둘이면 어느 쪽이 정답인지 정할 수 없다.
    by_title: dict[str, list[dict]] = {}
    for c in corpus:
        by_title.setdefault(c["title"], []).append(c)
    unique = [v[0] for v in by_title.values() if len(v) == 1]
    rng.shuffle(unique)
    queries = [{"query": c["title"], "gold_id": c["id"]} for c in unique[:QUERY_N]]

    #: 면책 민감도 탐침 — 본문에 「다만 … 보상하지 않습니다」가 있는 조항에서 만든다.
    probes: list[dict] = []
    for c in corpus:
        body = c["body"]
        #: ★앞 200자 안에 있으면 탐침이 안 된다 — 어떤 모델이든 다 본다.
        #:   뒤쪽에 있는 것만 골라야 "뒤를 보는가"를 잴 수 있다.
        m = None
        for cand in _PROVISO.finditer(body):
            if cand.start() >= 200:
                m = cand
                break
        if m is None:
            continue
        end = _SENT_END.search(body, m.end())
        tail = body[m.start() : (end.end() if end else min(len(body), m.start() + 200))]
        tail = " ".join(tail.split())
        if len(tail) < 30:
            continue
        head = body[: m.start()].strip()
        probes.append({"id": c["id"], "head": head, "with_proviso": head + " " + tail})
        if len(probes) >= 60:
            break

    out = {
        "built_at": "2026-08-02",
        "built_from": "s5",
        "source_documents": n_doc,
        "corpus_size": len(corpus),
        "query_count": len(queries),
        "proviso_probe_count": len(probes),
        "note": (
            "질의는 문서에 이미 적힌 조항 제목이다. 지어내지 않았다. "
            "본문에서 제목 문구를 지워 문자열 일치로 맞히지 못하게 했다. "
            "★표본이 작다(코퍼스 2,000 · 질의 200). 순위 차이가 작으면 "
            "우열을 단정하지 않는다."
        ),
        "corpus": corpus,
        "queries": queries,
        "proviso_probes": probes,
    }
    _OUT.parent.mkdir(parents=True, exist_ok=True)
    _OUT.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")

    print(
        f"코퍼스 {len(corpus):,} · 질의 {len(queries)} · 면책탐침 {len(probes)} "
        f"(문서 {n_doc:,}개에서)"
    )
    print(f"→ {_OUT.relative_to(_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
