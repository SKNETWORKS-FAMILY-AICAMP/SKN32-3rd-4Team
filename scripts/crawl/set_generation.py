"""실손의료보험 **세대**를 판매개시일로 판정해 매니페스트에 넣는다.

★경계는 코드에 박지 않는다 — `config/generation_profiles.json` 을 읽는다

    처음에 이 스크립트를 만들 때 설정 파일이 있는 줄 모르고 경계를 코드에 박았다.
    그래서 **틀렸다**(코덱스가 잡아냈다).

      · 5세대(2026-05-06~)를 아예 몰라서 139건을 4세대로 판정했다
      · 노후실손·유병력자실손을 일반 실손과 **같은 축**으로 판정했다.
        설정에는 `applies_to: ["standard"]` 로 **별도 라인**임이 명시돼 있다.

    같은 사실을 두 곳에 두면 반드시 갈라진다. 설정이 단일 출처다.

★상품 라인이 먼저다 — 세대는 일반 실손에만 있다

    노후실손(2014-08~)·유병력자실손(2018-04-02~)은 **별개 상품**이지
    일반 실손의 세대가 아니다. 여행 실손은 세대 구분 대상이 아니다.
    이들에게 "3세대"라고 붙이면 자기부담금을 잘못 안내하게 된다.

★`review_status` 를 존중한다

    설정에 이렇게 적혀 있다.

        "출처는 2차 자료(보도자료·보험사 뉴스룸)다. 금융위/협회 원문으로 재확인이 필요하다."
        "review_status 가 'unreviewed' 인 동안에는 어떤 문서도 CONFIRMED 로 확정할 수 없다."

    그래서 `unreviewed` 면 판정 결과에 `generation_review="unreviewed"` 를 박아
    **자동 판정에서 그대로 믿지 않도록** 표시한다.

★신뢰도

    exact     날짜를 일자까지 안다
    month     월까지만 안다(상품코드에서 유도). 경계달이 아니면 세대는 갈린다
    ambiguous 월까지만 아는데 **경계달에 걸린다** — 세대가 흔들릴 수 있다
    unknown   날짜를 모른다. 판정하지 않는다

실행:
    python -m scripts.crawl.set_generation --dry-run
    python -m scripts.crawl.set_generation
"""

from __future__ import annotations

import argparse
import collections
import json
from pathlib import Path

from app.core.errors import InfraError

_ROOT = Path(__file__).resolve().parents[2]
_MANIFESTS = _ROOT / "data" / "raw" / "manifests"
_PROFILES = _ROOT / "config" / "generation_profiles.json"


def _load_profiles() -> dict:
    if not _PROFILES.exists():
        raise InfraError(
            f"세대 설정이 없습니다: {_PROFILES}\n"
            "경계를 코드에 박지 않는다 — 설정이 단일 출처다."
        )
    return json.loads(_PROFILES.read_text(encoding="utf-8"))


def _ymd(s: str | None) -> str:
    """`2021-07-01` → `20210701`. None 이면 열린 구간."""
    return s.replace("-", "") if s else ""


def product_line(name: str, profiles: dict) -> str:
    """상품 라인(standard / senior / simplified_issue / travel)."""
    types = profiles["product_types"]
    #: ★일반 실손보다 **특수 라인을 먼저** 본다.
    #:   `노후실손의료비보험` 은 `실손의료비` 도 포함하므로 순서가 중요하다.
    for key in ("travel", "senior", "simplified_issue"):
        spec = types.get(key, {})
        if any(mk in name for mk in spec.get("name_markers", [])):
            return key
    spec = types.get("standard", {})
    if any(mk in name for mk in spec.get("name_markers", [])):
        if any(x in name for x in spec.get("exclude_markers", [])):
            return "unknown"
        return "standard"
    return "unknown"


def generation_of(sale_start: str, line: str, profiles: dict) -> dict | None:
    """해당 라인·날짜의 세대 항목. 없으면 None."""
    for g in profiles["generations"]:
        if line not in g.get("applies_to", []):
            continue
        lo = _ymd(g.get("effective_from"))
        hi = _ymd(g.get("effective_to"))
        if lo and sale_start < lo:
            continue
        if hi and sale_start > hi:
            continue
        return g
    return None


def _boundary_months(profiles: dict) -> set[str]:
    """경계가 걸린 달 — 월까지만 아는 날짜로는 세대가 흔들린다."""
    out: set[str] = set()
    for g in profiles["generations"]:
        for k in ("effective_from", "effective_to"):
            v = _ymd(g.get(k))
            if v:
                out.add(v[:6])
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    profiles = _load_profiles()
    review = profiles.get("review_status", "unreviewed")
    boundary = _boundary_months(profiles)
    print(f"설정 {_PROFILES.name} (작성 {profiles.get('compiled_at')}, 검수 {review})")
    print(f"  세대 구간: {[(g['generation'], g.get('effective_from'), g.get('effective_to')) for g in profiles['generations']]}")
    if review != "reviewed":
        print("  ★검수 전이다 — 판정 결과에 generation_review 를 남긴다(그대로 믿지 않는다).")

    dist = collections.Counter()
    lines = collections.Counter()
    conf = collections.Counter()
    for m in sorted(_MANIFESTS.glob("*.jsonl")):
        rows = [
            json.loads(line)
            for line in m.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        for r in rows:
            #: ★격리된 문서(사업방법서·여행실손·비의료실손)는 판정 대상이 아니다.
            #:   세지도 않는다 — 세면 분모가 부풀어 통계가 거짓말을 한다.
            if (r.get("excluded_reason") or "").strip():
                continue
            name = r.get("product_name") or r.get("original_name") or ""
            line = product_line(name, profiles)
            r["product_line"] = line
            lines[line] += 1

            #: 이전 판정을 지우고 다시 넣는다(잘못 박힌 값이 남지 않게).
            for k in ("generation", "generation_label", "generation_note"):
                r.pop(k, None)

            start = (r.get("sale_start") or "").strip()
            if not start or len(start) < 8 or start == "00000000":
                r["generation_confidence"] = "unknown"
                dist["날짜모름"] += 1
                continue
            if line != "standard":
                #: ★특수 라인은 일반 실손의 세대 축이 아니다.
                r["generation_confidence"] = "not_applicable"
                dist[f"{line}(세대축 아님)"] += 1
                continue

            g = generation_of(start, line, profiles)
            if g is None:
                r["generation_confidence"] = "unknown"
                dist["구간없음"] += 1
                continue

            r["generation"] = g["generation"]
            r["generation_label"] = g["label"]
            date_conf = r.get("date_confidence", "exact")
            if date_conf == "month" and start[:6] in boundary:
                gc = "ambiguous"
            elif date_conf == "month":
                gc = "month"
            else:
                gc = "exact"
            r["generation_confidence"] = gc
            r["generation_review"] = review
            dist[f"{g['generation']}세대"] += 1
            conf[gc] += 1

        if not args.dry_run:
            tmp = m.with_suffix(".jsonl.tmp")
            tmp.write_text(
                "".join(json.dumps(x, ensure_ascii=False) + "\n" for x in rows),
                encoding="utf-8",
            )
            tmp.replace(m)

    print("\n상품 라인(행 기준):")
    for k, v in lines.most_common():
        print(f"  {k:<20}{v:>5}")
    print("\n판정 결과:")
    for k in sorted(dist):
        print(f"  {k:<22}{dist[k]:>5}")
    print(f"\n세대 판정 신뢰도: {dict(conf)}")
    if args.dry_run:
        print("(dry-run: 아무것도 쓰지 않았습니다.)")


if __name__ == "__main__":
    import sys

    sys.path.insert(0, str(_ROOT))
    main()
