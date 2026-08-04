"""**이 파일이 무엇인가**를 확정한다 — 수집과 식별은 별개다.

★왜 필요한가

    `usable_for_judgment` 는 `identification == "confirmed"` 를 요구한다.
    지금 매니페스트 2,121행이 **전부 `unidentified`** 라 판정 가능 약관이 0건이고,
    `POST /v1/prechecks` 가 전량 `documents_not_confirmed` 로 기권한다.

    이건 고장이 아니라 **설계**다 — 확인 안 된 약관으로 "보장됩니다"라고 하면
    2019년 가입자에게 2024년 조항이 근거로 붙는다. 그래서 사람이 확정한다.

★무엇을 근거로 확정하나 — **문서 자신에게 물어본다**

    매니페스트는 *수집기가 사이트에서 읽은 것*이다. 그게 맞는지는
    **약관 본문**과 대조해야 안다. 네 가지를 본다.

        ① 상품명 토큰이 문서 앞부분에 실제로 나오는가
        ② 문서가 스스로 밝힌 판매일이 매니페스트와 **월 단위로** 맞는가
        ③ 세대가 `config/generation_profiles.json` 의 시행 구간과 맞는가
        ④ 조항 산출물의 `parse_status` 가 `ok` 인가

    ★실제로 걸러냈다(2026-08-04) — 메리츠화재 한 건은 매니페스트가
      `20260501` 인데 **약관 표지에 "판매개시 2026. 7. 13"** 이라 적혀 있었다.
      2개월 넘게 어긋난다. 확정했다면 다른 판본으로 판정할 뻔했다.

★확정은 **매니페스트에 쓰지 않는다.** 별도 원장에 쌓는다.

    매니페스트는 「우리가 무엇을 받았나」(수집 기록)이고,
    확정은 「이게 무엇인지 사람이 정했다」(결정)이다. 섞으면
    **크롤러를 다시 돌리는 순간 사람의 결정이 덮인다.**
    원장은 `config/confirmed_documents.jsonl` 이고 저장소에 커밋된다.

쓰는 법:
    python -m scripts.confirm.identify_documents --report
    python -m scripts.confirm.identify_documents --report --limit 40
    python -m scripts.confirm.identify_documents --apply --confirmed-by "홍길동" --scope demo
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys
import unicodedata

_ROOT = pathlib.Path(__file__).resolve().parents[2]
_MANIFESTS = _ROOT / "data" / "raw" / "manifests"
_LEDGER = _ROOT / "config" / "confirmed_documents.jsonl"

#: 상품명 토큰이 몇 %나 문서에 나와야 「이름이 맞다」고 볼 것인가.
#: ★1.0 이다. 0.8 로 두면 `[1종단체전환용]` 같은 **종별 표기 하나**가 빠져도
#:   통과하는데, 종이 다르면 자기부담금이 다른 **다른 상품**이다.
_NAME_MATCH_MIN = 1.0

#: 문서 앞 몇 쪽까지 훑을 것인가. 표지가 「감사의 글」·「가이드 북」인 회사가 있어
#: 3쪽으로는 모자랐다(실측: 삼성생명·NH농협손보).
_SCAN_PAGES = 15

#: 파일명에서 온 날짜 접두어(`2016-01-01_무배당…`). 상품명이 아니라 **수집기가 붙인 것**이라
#: 문서 본문에 있을 리 없다. 이름 대조에서 뺀다 — 안 빼면 흥국화재가 통째로 탈락한다.
_FILENAME_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

_DATE_PATTERNS = (
    (re.compile(r"판매개시[:\s]*(\d{4})[.\-년](\d{1,2})"), "판매개시"),
    (re.compile(r"판매[월일][:\s]*(\d{4})[.\-년](\d{1,2})"), "판매월"),
    (re.compile(r"(\d{4})년(\d{1,2})월\d{0,2}일?시행"), "시행"),
)

#: `config/generation_profiles.json` 의 시행 구간. 코드에 박지 않고 읽어 온다.
def _generation_ranges() -> list[tuple[int, str | None, str | None]]:
    prof = json.loads((_ROOT / "config" / "generation_profiles.json").read_text(encoding="utf-8"))
    out = []
    for g in prof["generations"]:
        def _d(v):
            return v.replace("-", "") if v else None
        out.append((g["generation"], _d(g.get("effective_from")), _d(g.get("effective_to"))))
    return out


#: ★**같은 말인데 표기가 다른 것**만 여기 둔다. 게이트를 무르게 하려는 목록이 아니다.
#:
#:   `무배당` 과 `(무)` 는 한국 보험 표기의 같은 낱말이다(배당 없음). 상품명에는
#:   `무배당 메리츠 …` 로, 약관 표지에는 `(무) 메리츠 …` 로 적힌다.
#:
#:   ★크기 때문이 아니라 **맞기 때문에** 넣는다. 실측 2026-08-04 —
#:   `무배당` 누락 78건 중 문서에 `(무)` 가 실제로 있는 것은 **메리츠화재 9건뿐**이다.
#:   삼성생명 64건은 `무배당` 도 `(무)` 도 없다 — 그건 표기 차이가 아니라
#:   **문서가 상품명을 안 밝힌 것**이라 여전히 막혀야 한다.
#:
#:   ★여기에 `기본형`·`갱신형` 같은 **상품 옵션 표기를 넣지 말 것.**
#:   그건 같은 말이 아니라 **다른 상품**을 가리킬 수 있다(자기부담금이 다르다).
_NAME_ALIASES: dict[str, tuple[str, ...]] = {
    "무배당": ("무",),
    "無배당": ("무", "무배당"),
}


def _norm(s: str) -> str:
    return re.sub(r"[^0-9A-Za-z가-힣]", "", unicodedata.normalize("NFKC", s or "")).lower()


def _token_in(tok: str, flat: str) -> bool:
    """토큰이 문서에 있나. **별칭까지 본다.**"""
    if _norm(tok) in flat:
        return True
    return any(_norm(a) in flat for a in _NAME_ALIASES.get(tok.strip(), ()))


def load_manifest_rows() -> list[dict]:
    rows, seen = [], set()
    for m in sorted(_MANIFESTS.glob("*.jsonl")):
        for line in m.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            r = json.loads(line)
            sha = r.get("sha256", "")
            if not sha or sha in seen:
                continue
            seen.add(sha)
            rows.append(r)
    return rows


def _artifact_text(sha12: str, page_tag: str) -> tuple[str, int]:
    """페이지 산출물 앞부분 본문. 없으면 `("", 0)`."""
    hits = list((_ROOT / "data" / "extracted").glob(f"*/{page_tag}/{sha12}.json"))
    if not hits:
        return "", 0
    d = json.loads(hits[0].read_text(encoding="utf-8"))
    pages = d.get("pages") or []
    return "\n".join((p.get("text") or "") for p in pages[:_SCAN_PAGES]), len(pages)


def _parse_status(sha12: str, clause_tag: str) -> str | None:
    hits = list((_ROOT / "data" / "structured").glob(f"*/{clause_tag}/{sha12}.clauses.json"))
    if not hits:
        return None
    return json.loads(hits[0].read_text(encoding="utf-8")).get("parse_status")


def verify(row: dict, *, page_tag: str, clause_tag: str) -> dict:
    """한 문서의 식별 근거를 모은다. **판정하지 않고 근거를 낸다.**

    ★`ok` 가 아닌 이유를 반드시 담는다. 조용히 빼면 「검토했다」가 거짓이 된다.
    """
    sha = row.get("sha256", "")
    sha12 = sha[:12]
    out: dict = {"sha256": sha, "insurer": row.get("insurer", ""),
                 "product_name": row.get("product_name", ""),
                 "sale_start": row.get("sale_start", ""),
                 "generation": row.get("generation"),
                 "reasons": []}

    if (row.get("excluded_reason") or "").strip():
        out["reasons"].append(f"판정 제외 문서: {row['excluded_reason']}")
    if (row.get("date_confidence") or "") not in ("exact", "month"):
        #: ★키가 없는 것도 여기 걸린다. 「모른다」는 「정확하다」가 아니다.
        out["reasons"].append(f"판매시점 신뢰도가 없다: {row.get('date_confidence')!r}")
    ss = row.get("sale_start") or ""
    if not ss or ss == "00000000":
        out["reasons"].append("sale_start 가 비었거나 자리표시자다")

    ps = _parse_status(sha12, clause_tag)
    out["parse_status"] = ps
    if ps != "ok":
        out["reasons"].append(f"조항 산출물 parse_status={ps!r}")

    text, n_pages = _artifact_text(sha12, page_tag)
    out["pages"] = n_pages
    if not text:
        out["reasons"].append(f"페이지 산출물이 없다({page_tag})")
        out["ok"] = False
        return out

    #: ── ① 이름 대조 ──
    flat = _norm(text)
    raw_toks = re.split(r"[\s()\[\],_/]+", unicodedata.normalize("NFKC", out["product_name"]))
    toks = [t for t in raw_toks if len(_norm(t)) >= 2 and not _FILENAME_DATE.match(t)]
    hit = [t for t in toks if _token_in(t, flat)]
    miss = [t for t in toks if not _token_in(t, flat)]
    out["name_match"] = f"{len(hit)}/{len(toks)}"
    out["name_missing"] = miss
    ratio = (len(hit) / len(toks)) if toks else 0.0
    if not toks:
        out["reasons"].append("상품명에서 대조할 토큰을 못 만들었다")
    elif ratio < _NAME_MATCH_MIN:
        out["reasons"].append(f"상품명이 문서에서 확인되지 않는다({out['name_match']}): {miss[:4]}")

    #: ── ② 문서가 스스로 밝힌 판매일 ──
    squeezed = text.replace(" ", "")
    found = sorted({(lab, f"{m.group(1)}{int(m.group(2)):02d}")
                    for pat, lab in _DATE_PATTERNS for m in pat.finditer(squeezed)})
    out["doc_dates"] = [f"{lab}:{ym}" for lab, ym in found]
    if found:
        #: ★★**두 날짜는 같은 것이 아니다.** 처음엔 다르면 탈락시켰는데 틀렸다.
        #:
        #:     `sale_start`   **상품**이 팔리기 시작한 때
        #:     표지 판매개시   **이 판본 문서**가 효력을 가진 때
        #:
        #:   실측 2026-08-04 — 메리츠화재는 `sale_start=20260501`(상품명 "2605" 에서
        #:   추론)인데 표지에 「판매개시 2026. 7. 13 · 판매버전 3.0」 이라 적혀 있다.
        #:   **모순이 아니라 개정이다.** 같은 것으로 보고 9건을 통째로 떨어뜨렸다.
        #:
        #:   ★그렇다고 표지 날짜를 `sale_start` 로 삼아도 안 된다 —
        #:   그러면 2026년 6월 가입자가 「해당 시점 약관 없음」 이 된다. 약관은 있는데.
        #:
        #:   그래서 **뒤면 통과, 앞서면 막는다.** 문서가 상품보다 먼저 존재할 수는 없다.
        earliest = min(ym for _, ym in found)
        if any(ym == ss[:6] for _, ym in found):
            pass  # 월까지 같다 — 가장 강한 일치
        elif earliest >= ss[:6]:
            #: 개정판. 근거 등급을 낮춰 남긴다 — **통과시키되 같은 급으로 치지 않는다.**
            out["doc_dates"] = [*out["doc_dates"], f"개정추정(sale_start {ss[:6]} 이후)"]
        else:
            out["reasons"].append(
                f"문서가 밝힌 판매시점 {earliest} 이 상품 판매개시 {ss[:6]} 보다 **앞선다** "
                f"— 문서가 상품보다 먼저 있을 수는 없다(전체 {[y for _, y in found]})")
    else:
        #: ★근거가 **없는 것**과 **어긋나는 것**은 다르다. 없다고 탈락시키지 않되 적어 둔다.
        out["doc_dates"] = []

    #: ── ③ 세대 ──
    g = row.get("generation")
    exp = None
    for gen, a, b in _generation_ranges():
        if (a is None or ss >= a) and (b is None or ss <= b):
            exp = gen
            break
    out["generation_expected"] = exp
    #: ★★**세대가 비었다고 탈락시키지 않는다.** 처음엔 그렇게 했는데 **계약 위반**이었다.
    #:
    #:   `docs/handoff/02_ERD_및_스키마.md` 가 못박아 둔 것 —
    #:     「`generation` 을 NULL 허용으로 두는 것이 이 표에서 가장 중요하다.
    #:      모르는 세대를 숫자로 채우면 그 오류가 판정까지 간다.
    #:      판정에서 참조할 수 있는 것은 `date_confidence <> 'unknown'` 인 버전뿐이다.」
    #:
    #:   즉 게이트는 **판매시점**이지 세대가 아니다. `usable_for_judgment` 도
    #:   세대를 요구하지 않는다(`app/core/ports/precheck.py`). 이 도구만 더 엄격했다.
    #:
    #:   실측 2026-08-04 — 그 규칙 하나로 **363건**이 떨어졌다. 그중 287건은
    #:   `generation_confidence="not_applicable"` 이다. 세대 축이 **적용되지 않는**
    #:   상품이라 비어 있는 게 정상인데 결함으로 셌다.
    #:
    #:   ★**값이 있는데 규칙과 다른 것**은 여전히 막는다. 그건 모름이 아니라 모순이다.
    if g is not None and exp is not None and g != exp:
        out["reasons"].append(f"세대가 규칙과 다르다: 매니페스트 {g} · 규칙 {exp}")

    out["ok"] = not out["reasons"]
    #: ★문서 안에서 판매일을 못 찾았으면 근거가 한 단 약하다. **등급으로 남긴다.**
    out["evidence"] = "name+date" if (out["ok"] and out["doc_dates"]) else (
        "name_only" if out["ok"] else "-")
    return out


def _release() -> tuple[str, str]:
    sys.path.insert(0, str(_ROOT))
    from app.core import release

    r = release.current()
    return r.page_tag, r.clause_tag


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--report", action="store_true", help="근거만 낸다(쓰지 않음)")
    ap.add_argument("--apply", action="store_true", help="통과한 것을 원장에 쓴다")
    ap.add_argument("--confirmed-by", default="", help="★누가 확정했나. `--apply` 에 필수")
    ap.add_argument("--scope", default="demo", help="확정 범위 표시(demo/full)")
    ap.add_argument("--limit", type=int, default=0, help="후보 상한(0=전량)")
    ap.add_argument("--insurer", default="", help="보험사로 좁힌다")
    ap.add_argument("--spread", action="store_true",
                    help="★통과분에서 **보험사×세대마다 1건**만 남긴다(데모용 — 전 경로를 훑기 위함). "
                         "근거가 강한 것(name+date)을 먼저 고른다")
    a = ap.parse_args(argv)

    if a.apply and not a.confirmed_by.strip():
        raise SystemExit("★`--confirmed-by` 가 필요합니다. 누가 확정했는지 안 남기면 확정이 아닙니다.")
    if not (a.report or a.apply):
        raise SystemExit("★`--report` 또는 `--apply` 중 하나를 고르세요.")

    page_tag, clause_tag = _release()
    rows = load_manifest_rows()
    if a.insurer:
        rows = [r for r in rows if r.get("insurer") == a.insurer]

    results, skipped = [], 0
    for r in rows:
        #: ★싸게 거를 수 있는 것을 먼저 걸러 산출물 읽기를 아낀다.
        #:   단 **센다** — 조용히 빼면 분모가 줄어 통과율이 좋아 보인다(CLAUDE.md §3).
        if (r.get("excluded_reason") or "").strip() or \
           (r.get("date_confidence") or "") not in ("exact", "month"):
            skipped += 1
            continue
        results.append(verify(r, page_tag=page_tag, clause_tag=clause_tag))
        if a.limit and len(results) >= a.limit:
            break

    ok = [x for x in results if x["ok"]]
    print(f"매니페스트 {len(rows):,} · 사전탈락 {skipped:,}(제외사유·판매시점 미상) · "
          f"검사 {len(results):,} · 통과 {len(ok):,}", flush=True)

    if a.spread:
        #: ★근거 강한 것 먼저, 그 다음 판매시점이 이른 것. **결정적으로** 고른다 —
        #:   같은 명령을 두 번 돌려 다른 문서가 확정되면 재현이 안 된다.
        best: dict[tuple, dict] = {}
        for x in sorted(ok, key=lambda x: (x["evidence"] != "name+date",
                                           x["sale_start"], x["sha256"])):
            best.setdefault((x["insurer"], x["generation"]), x)
        dropped = len(ok) - len(best)
        ok = sorted(best.values(), key=lambda x: (x["insurer"], x["generation"] or 0))
        #: ★얼마나 뺐는지 **말한다.** 조용히 줄이면 "이만큼 확정했다"가 실제보다 커 보인다.
        print(f"--spread: 보험사×세대 {len(ok)}건만 남김(통과분에서 {dropped:,}건 보류)")
    by_ev: dict[str, int] = {}
    for x in ok:
        by_ev[x["evidence"]] = by_ev.get(x["evidence"], 0) + 1
    print(f"근거 등급: {by_ev}  (name+date = 문서가 판매시점까지 밝힘)")

    if a.report:
        #: ★★`--spread` 를 켜면 **머리말은 10건인데 본문은 132건**을 찍고 있었다(2026-08-04).
        #:   보고서가 자기 요약과 어긋나면 읽는 사람이 어느 쪽을 믿을지 모른다.
        #:   좁혔으면 좁힌 것을 보여준다. 탈락분은 좁히기 전에만 의미가 있다.
        shown = ok if a.spread else results
        print()
        for x in shown:
            mark = "OK " if x["ok"] else "NG "
            print(f"{mark}{x['insurer']:<10} {x['sha256'][:12]} {x['generation']}세대 "
                  f"{x['sale_start']} 이름{x.get('name_match','-')} "
                  f"{x.get('evidence','-')} {x.get('doc_dates') or ''}")
            for why in x["reasons"]:
                print(f"      · {why}")
            print(f"      {x['product_name'][:70]}")

    if a.apply:
        from datetime import date

        _LEDGER.parent.mkdir(parents=True, exist_ok=True)
        existing = {}
        if _LEDGER.exists():
            for line in _LEDGER.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    e = json.loads(line)
                    existing[e["sha256"]] = e
        added = 0
        for x in ok:
            if x["sha256"] in existing:
                continue
            existing[x["sha256"]] = {
                "sha256": x["sha256"],
                "insurer": x["insurer"],
                "product_name": x["product_name"],
                "identification": "confirmed",
                #: ★`reviewed` 가 아니라 `partial` 이다 —
                #:   `generation_profiles.json` 자신이 `review_status: "partial"` 이라고 적고 있다.
                #:   규칙셋이 부분 검토인데 그걸 근거로 한 판정을 완전 검토라 할 수 없다.
                "generation_review": "partial",
                "confirmed_at": date.today().isoformat(),
                "confirmed_by": a.confirmed_by.strip(),
                "scope": a.scope,
                "evidence": x["evidence"],
                "basis": {
                    "name_match": x.get("name_match"),
                    "doc_dates": x.get("doc_dates"),
                    "generation_expected": x.get("generation_expected"),
                    "parse_status": x.get("parse_status"),
                    "page_tag": page_tag,
                    "clause_tag": clause_tag,
                },
            }
            added += 1
        with _LEDGER.open("w", encoding="utf-8") as f:
            for sha in sorted(existing):
                f.write(json.dumps(existing[sha], ensure_ascii=False) + "\n")
        print(f"\n원장 기록 {added:,}건 추가 · 총 {len(existing):,}건 → {_LEDGER}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
