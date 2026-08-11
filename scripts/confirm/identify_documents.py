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

        ① ★**전체 상품명이 문서에 한 덩어리로** 나오는가 (강한 식별자)
        ② 문서가 스스로 밝힌 판매일이 `sale_start` 보다 **앞서지 않는가**
           (뒤면 개정이다 — 상품 판매개시와 판본 효력일은 **다른 것**이다)
        ③ 세대는 **값이 있을 때만** 규칙과 맞는지 본다 (NULL 은 정상 · 핸드오프 계약)
        ④ ★같은 문서에서 **다른 본약관**도 확인되면 자동 확정하지 않는다 (`ambiguous`)

    `parse_status` 는 **식별 조건이 아니다.** 「이 파일이 무엇인가」와
    「조항을 근거로 댈 수 있는가」는 다른 층이라 `extraction_blocked` 로 표시만 한다.

★이 도구가 실제로 잡은 것들 (2026-08-04)

    · 메리츠화재 `sale_start=20260501` vs 표지 「판매개시 2026. 7. 13」
      → 처음엔 탈락시켰는데 **틀렸다.** 상품 판매개시와 판본 효력일은 다른 필드다.
    · 반대로 내가 만든 **없는 규칙** 셋이 대량 오탈락을 냈다 —
      `date_confidence` 라벨 부재(+677) · 세대 NULL(+301) · `parse_status`(+36).
      ★**계약보다 엄격한 규칙을 임의로 만드는 것**이 이 작업의 주된 실패 모드였다.
    · 반대로 **너무 무른 기준**도 있었다 — 토큰 커버리지만 보다가
      확정 1,115건 중 **798건(71.6%)이 다른 상품명과도 일치**하고 있었다.
      강한 식별자로 바꾸니 850건이 됐다(제거 337). **줄어든 것이 맞는 방향이다.**

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

#: 문서 앞 몇 쪽까지 훑을 것인가.
#:
#: ★★**15 였다가 전체로 바꿨다(2026-08-04).** 표지가 「감사의 글」·「가이드 북」인
#:   회사가 있어 3 → 15 로 올렸는데 그래도 모자랐다 — 삼성생명은 **17쪽**에
#:   「삼성생명 인터넷실손의료비보장보험4.0(기본형,갱신형,무배당)」 이라고 정확히 밝힌다.
#:   실측: 상품명 탈락 206건 중 **117건이 40쪽 안에** 전체 이름을 갖고 있었다.
#:   즉 그 117건은 문서 문제가 아니라 **내가 만든 인위적 실패**였다(코덱스 지적).
#:
#: ★`None` 이면 전문을 본다. 범위를 넓히는 대신 **아래 강한 식별자**로 정밀도를 지킨다.
_SCAN_PAGES: int | None = None

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


def _gen_for(yyyymmdd: str) -> int | None:
    for gen, a, b in _generation_ranges():
        if (a is None or yyyymmdd >= a) and (b is None or yyyymmdd <= b):
            return gen
    return None


def _gen_splits_month(ss: str) -> bool:
    """그 달 **안에서** 세대가 갈리는가 — 갈리면 월 정밀도 날짜로는 못 가린다.

    ★5세대 경계가 `2026-05-06` 이다. 경계가 달 가운데 있으면 「1일」로 채운 값이
      경계 앞뒤 어느 쪽에도 놓일 수 있다. 그 값으로 모순을 선언할 수 없다.

    ☠**말일을 `31` 로 고정하면 안 된다.** 처음 그렇게 썼더니 2009-09 가 갈린다고
      나왔다 — 1세대 경계는 `2009-09-30` 이라 9월은 갈리지 않는데, 있지도 않은
      `20090931` 이 문자열 비교로 경계를 넘었다. **없는 날짜를 채워 결론을 만든 것**이
      이 함수가 막으려던 바로 그 잘못이다.
    """
    import calendar

    y, m = int(ss[:4]), int(ss[4:6])
    last = calendar.monthrange(y, m)[1]
    return _gen_for(f"{y:04d}{m:02d}01") != _gen_for(f"{y:04d}{m:02d}{last:02d}")


def _norm(s: str) -> str:
    return re.sub(r"[^0-9A-Za-z가-힣]", "", unicodedata.normalize("NFKC", s or "")).lower()


#: 수집기가 파일명에서 붙인 날짜 접두어. 상품명이 아니다.
_NAME_DATE_PREFIX = re.compile(r"^\d{4}-\d{2}-\d{2}_")


def full_name_key(product_name: str) -> str:
    """상품명 **전체**를 기호·공백 없이 한 덩어리로. 제목이 줄바꿈으로 갈려도 이어 붙는다."""
    return _norm(_NAME_DATE_PREFIX.sub("", product_name or ""))


def _rivals(row: dict, flat_doc: str, siblings: list[dict]) -> tuple[list[str], list[str]]:
    """이 문서 안에서 **같은 보험사의 다른 상품명**도 통째로 확인되는가.

    반환: `(독립적으로 확인된 본약관, 내 이름을 삼키는 더 긴 상품명)`

    ★★**토큰 커버리지는 유일성을 보장하지 않는다**(코덱스 지적 · 2026-08-04 실측으로 확인).

        약관집 PDF 하나에 본약관·특약·비교표가 같이 실린다. 그래서 상품명 토큰이
        전부 나온다고 그 문서가 **그 상품**이라는 뜻이 아니다.

        확정 원장 1,115건을 재측정한 결과 —
          토큰 부분문자열 대조   다른 상품명도 일치 **798건(71.6%)**
          낱말 경계 대조         504건(60.1%)
          ★전체 이름 연속 대조   297건(31.4%)  ← 지금 쓰는 것

    ★★그런데 그 「경쟁」의 3분의 2는 **경쟁이 아니었다**(2026-08-11 전수 재측정).

        모호 240건의 실제 성격 —
          ★상대명이 **내 이름 안에** 있음     161 (67.1%)  ← 매처가 자기 그림자를 밟았다
          내가 특약 · 상대는 내 적용대상        23 ( 9.6%)
          상대명이 「적용대상」 문맥에 있음      24 (10.0%)
          ☠내 이름이 상대 이름의 부분            0 ( 0.0%)
          진짜 모호                           32 (13.3%)

        실제 —
          나  : 무배당 흥국화재 다이렉트 실손의료보험(25.07)  →  …실손의료보험2507
          상대: 무배당 흥국화재 다이렉트 실손의료보험        →  …실손의료보험

        `_norm()` 이 괄호·점을 지우므로 **상대 키가 내 키의 접두사**가 된다.
        그러면 `k in flat_doc` 은 내 이름이 문서에 있다는 사실만으로 **반드시 참**이다.
        정보량이 0인 것을 증거로 센 것이다 — 이건 기준의 문제가 아니라 **결함**이다.

    ★★방향이 반대면 정반대로 위험하다.

          나  : …실손의료보험          (짧다)
          상대: …실손의료보험(25.07)   (내 이름을 **포함**한다)

        이때는 `me in flat` 이 상대 이름 때문에 참이 된다 — **내 이름이 확인된 게 아니다.**
        문서는 상대 것일 수 있으므로 **자동 확정을 막아야 한다.**

        ☠실측 0건이다. 그래도 남긴다 — 없다는 것을 **재고 나서** 하는 말이라야 하고,
          매니페스트에 상품명이 하나 추가되면 언제든 생길 수 있다.

    ★남은 것은 **조용히 통과시키지 않는다.** 독립적으로 확인된 본약관 상대가 있으면
      자동 확정하지 않는다(`ambiguous`). 특약만 상대인 경우는 정상이다 —
      `resolve()` 가 본약관을 우선하므로 섞이지 않는다.
    """
    from app.core.domain.policy_naming import looks_like_rider

    me = full_name_key(row.get("product_name", ""))
    out: list[str] = []
    shadowed: list[str] = []
    for o in siblings:
        if o.get("sha256") == row.get("sha256"):
            continue
        k = full_name_key(o.get("product_name", ""))
        if not k or k == me or k not in flat_doc:
            continue
        if k in me:
            #: ★내 이름 안에 든 짧은 이름. 내 이름이 확인된 순간 **반드시** 걸린다.
            #:   증거가 아니므로 세지 않는다. 이건 완화가 아니라 잘못된 증거 제거다.
            continue
        if me in k:
            #: ☠거꾸로다. 내 이름이 이 긴 이름 때문에 걸렸을 수 있다 — **막는다.**
            #:   ★`continue` 로 빼면 안 된다. 그러면 오히려 통과한다(코덱스 초안의 결함).
            shadowed.append(o.get("product_name") or "")
            continue
        if not looks_like_rider(o.get("product_name") or ""):
            out.append(o.get("product_name") or "")
    return out, shadowed


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
    keep = pages if _SCAN_PAGES is None else pages[:_SCAN_PAGES]
    return "\n".join((p.get("text") or "") for p in keep), len(pages)


def _parse_status(sha12: str, clause_tag: str) -> str | None:
    hits = list((_ROOT / "data" / "structured").glob(f"*/{clause_tag}/{sha12}.clauses.json"))
    if not hits:
        return None
    return json.loads(hits[0].read_text(encoding="utf-8")).get("parse_status")


def verify(row: dict, *, page_tag: str, clause_tag: str,
           siblings: list[dict] | None = None) -> dict:
    """한 문서의 식별 근거를 모은다. **판정하지 않고 근거를 낸다.**

    ★`ok` 가 아닌 이유를 반드시 담는다. 조용히 빼면 「검토했다」가 거짓이 된다.

    Args:
        siblings: 같은 보험사의 다른 매니페스트 행. 주면 **경쟁 상품명 검사**를 한다.
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

    #: ★★**`parse_status` 를 식별 실패로 세지 않는다**(2026-08-04 · 코덱스 지적).
    #:
    #:   「이 파일이 무엇인가」(식별)와 「조항을 근거로 댈 수 있는가」(인용 가능성)는
    #:   **다른 층**이다. ERD 도 확정 문서와 추출 승인을 나눠 두었고,
    #:   런타임은 판본을 고른 **뒤에** `parse_status` 를 다시 본다
    #:   (`app/core/usecases/precheck.py`). 여기서 또 막으면 층을 섞는 것이다.
    #:
    #:   실측 — `suspect` 52건 중 **51건이 인용 가능 조항 10개 이상**이다.
    #:   식별은 되는데 식별 단계에서 떨어뜨리고 있었다(36건이 이 이유만으로 막혔다).
    #:
    #: ★★그런데 **그냥 통과시키면 안 된다.** `eligibility.check()` 가
    #:   `parse_status != "ok"` 인 문서의 조항을 **전부** 거절한다. 그래서 확정하면
    #:   판본은 잡히고 인용은 0건이 되어 `no_evidence`(「질병기호로 적힌 조항을
    #:   찾지 못했습니다」)로 답한다 — **실제 이유는 구조화 품질인데 다른 사유를 말한다.**
    #:   그래서 원장에 `extraction_blocked` 로 **표시**해 두고, 판정 쪽이
    #:   그 사유를 쓸 수 있게 남긴다.
    ps = _parse_status(sha12, clause_tag)
    out["parse_status"] = ps
    out["extraction_blocked"] = ps != "ok"

    text, n_pages = _artifact_text(sha12, page_tag)
    out["pages"] = n_pages
    if not text:
        out["reasons"].append(f"페이지 산출물이 없다({page_tag})")
        out["ok"] = False
        return out

    #: ── ① 이름 대조 — **강한 식별자 하나**를 요구한다 ──
    #:
    #: ★★토큰이 문서 여기저기 흩어져 다 나오는 것으로는 **부족하다.**
    #:   전체 상품명이 **한 덩어리로** 있어야 한다. 근거는 `_rivals()` 주석의 실측 표.
    flat = _norm(text)
    me = full_name_key(out["product_name"])
    raw_toks = re.split(r"[\s()\[\],_/]+", unicodedata.normalize("NFKC", out["product_name"]))
    toks = [t for t in raw_toks if len(_norm(t)) >= 2 and not _FILENAME_DATE.match(t)]
    miss = [t for t in toks if not _token_in(t, flat)]
    out["name_match"] = f"{len(toks) - len(miss)}/{len(toks)}"
    out["name_missing"] = miss
    if not me:
        out["reasons"].append("상품명이 비어 있어 대조할 수 없다")
    elif me not in flat:
        detail = f", 빠진 토큰 {miss[:3]}" if miss else " — 토큰은 다 있으나 흩어져 있다"
        out["reasons"].append(
            f"전체 상품명이 문서에 한 덩어리로 나오지 않는다(토큰 {out['name_match']}{detail})")

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
    #:
    #: ★★단, **모순이라고 말하려면 규칙 쪽이 확정적이어야 한다.**
    #:
    #:   실측 2026-08-11 — 3건이 이 규칙으로 떨어졌다.
    #:     (무)헤아림다이렉트실손의료비보험(전환계약용)2605  매니페스트 5 · 규칙 4
    #:
    #:   판매일은 `20260501` 인데 `date_confidence="month"` 다. 출처는 **상품명 코드**
    #:   (`2605` = 2026년 5월)라 **일(日)을 모른다.** 5세대 경계는 `2026-05-06` 으로
    #:   **그 달 가운데**에 있다. 즉 모르는 일자를 1일로 채운 뒤 그 값으로
    #:   「규칙은 4세대」라고 선언한 것이다 — 채운 값이 결론을 만들었다.
    #:
    #:   ★그래서 **그 달 안에서 세대가 갈리면 날짜는 아무것도 말해 주지 않는다.**
    #:     모순이 아니라 **판정 불가**다. 판정 불가를 모순으로 부르면 안 된다.
    if g is not None and exp is not None and g != exp:
        if (row.get("date_confidence") or "") == "month" and _gen_splits_month(ss):
            #: 날짜로는 가릴 수 없다. 막지 않되 **적어 둔다** — 조용히 넘기지 않는다.
            out["generation_expected"] = f"{exp}?(월 안에서 갈림)"
        else:
            out["reasons"].append(f"세대가 규칙과 다르다: 매니페스트 {g} · 규칙 {exp}")

    #: ── ④ 경쟁 상품명 — **유일하게 식별되는가** ──
    #:
    #: ★이름이 맞는 것과 **그 이름만 맞는 것**은 다르다. 약관집에 본약관과 특약이
    #:   같이 실리므로, 같은 보험사의 다른 **본약관**까지 통째로 나오면 자동 확정하지 않는다.
    #:   (특약만 상대인 경우는 정상 — `resolve()` 가 본약관을 우선한다.)
    out["rivals"], out["shadowed_by"] = (
        _rivals(row, flat, siblings or []) if (me and me in flat) else ([], []))
    if out["shadowed_by"]:
        #: ☠이름 대조 자체가 성립하지 않는다. 확정률보다 **먼저** 막는다.
        out["reasons"].append(
            f"내 상품명이 더 긴 상품명 {len(out['shadowed_by'])}건에 삼켜져 있다 — "
            f"이 문서가 그쪽 것일 수 있다: {out['shadowed_by'][:2]}")
    if out["rivals"]:
        out["reasons"].append(
            f"같은 문서에서 다른 본약관 {len(out['rivals'])}건도 확인된다 — 사람이 골라야 한다"
            f": {out['rivals'][:2]}")

    out["ok"] = not out["reasons"]
    #: ★근거 등급. 문서 안에서 판매일까지 확인되면 한 단 강하다.
    if not out["ok"]:
        #: ☠「삼켜짐」은 모호와 다르다 — 모호는 둘 중 고르는 것이고 이건 대조가 안 된 것이다.
        out["evidence"] = ("shadowed" if out["shadowed_by"]
                           else "ambiguous" if out["rivals"] else "-")
    elif out["extraction_blocked"]:
        #: 식별은 됐지만 **인용은 못 한다.** 판정 쪽이 이 사실을 말할 수 있어야 한다.
        out["evidence"] = "extraction_blocked"
    else:
        out["evidence"] = "name+date" if out["doc_dates"] else "name_only"
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
    ap.add_argument("--rebuild", action="store_true",
                    help="★원장을 **다시 심사**한다. 기준이 바뀌면 기존 항목도 다시 봐야 한다 — "
                         "덧붙이기만 하면 통과율이 「기준 완화 이력의 합」이 된다. "
                         "사람이 승인한 항목은 지우지 않고 보고만 한다")
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

    #: 경쟁 상품명 검사용 — 같은 보험사 행을 미리 묶는다.
    import collections as _c
    by_insurer = _c.defaultdict(list)
    for _r in rows:
        by_insurer[_r.get('insurer', '')].append(_r)

    results, skipped = [], 0
    for r in rows:
        #: ★싸게 거를 수 있는 것을 먼저 걸러 산출물 읽기를 아낀다.
        #:   단 **센다** — 조용히 빼면 분모가 줄어 통과율이 좋아 보인다(CLAUDE.md §3).
        if (r.get("excluded_reason") or "").strip() or \
           (r.get("date_confidence") or "") not in ("exact", "month"):
            skipped += 1
            continue
        results.append(verify(r, page_tag=page_tag, clause_tag=clause_tag,
                              siblings=by_insurer.get(r.get('insurer', ''), [])))
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
        dropped = 0
        if a.rebuild:
            #: ★★기준이 바뀌면 **옛 기준으로 들어온 것을 반드시 다시 심사한다.**
            #:   덧붙이기만 하면 통과율이 「기준을 느슨하게 했던 이력의 합」이 된다.
            #:   실측 2026-08-04 — 강한 식별자를 넣기 전 1,115건이 들어와 있었는데
            #:   새 기준으로는 850건만 통과한다. 265건은 **빼야 한다.**
            keep = {x["sha256"] for x in ok}
            for sha, e in list(existing.items()):
                if sha in keep:
                    continue
                if "대기" not in (e.get("confirmed_by") or ""):
                    #: ★사람이 승인한 것은 **지우지 않는다.** 기계 기준이 사람 결정을 덮으면 안 된다.
                    print(f"  ★사람 승인 항목이 새 기준에서 탈락 — 남겨 둡니다: "
                          f"{sha[:12]} {(e.get('product_name') or '')[:34]}")
                    continue
                del existing[sha]
                dropped += 1
        added = refreshed = 0
        for x in ok:
            prev = existing.get(x["sha256"])
            if prev is not None:
                #: ★★**살아남았다고 그냥 두면 옛 기준의 근거가 남는다.**
                #:   `--rebuild` 가 탈락만 지우고 통과분을 갱신하지 않아,
                #:   새로 생긴 `extraction_blocked` 필드가 기존 행에 안 붙었다
                #:   (회귀 시험이 잡았다 · 2026-08-04). 기준이 바뀌면 **근거도 다시 쓴다.**
                #:   ★사람이 승인한 것은 손대지 않는다.
                if not a.rebuild or "대기" not in (prev.get("confirmed_by") or ""):
                    continue
                refreshed += 1
            else:
                added += 1
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
                #: ★인용 가능성은 식별과 **다른 층**이다. 확정했다고 근거를 댈 수 있는 건 아니다.
                "extraction_blocked": x.get("extraction_blocked", False),
                "basis": {
                    "name_match": x.get("name_match"),
                    "doc_dates": x.get("doc_dates"),
                    "generation_expected": x.get("generation_expected"),
                    "parse_status": x.get("parse_status"),
                    "page_tag": page_tag,
                    "clause_tag": clause_tag,
                },
            }
        with _LEDGER.open("w", encoding="utf-8") as f:
            for sha in sorted(existing):
                f.write(json.dumps(existing[sha], ensure_ascii=False) + "\n")
        print(f"\n원장 추가 {added:,} · 제거 {dropped:,} · 총 {len(existing):,}건 → {_LEDGER}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
