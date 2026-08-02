"""좌표로 표를 복원한다 — 테두리가 없어도, 페이지가 돌아가 있어도.

★왜 필요한가

    보장한도·자기부담금·질병분류표(KCD)가 **전부 표에 있다.**
    지금 `to_page_json.py` 는 `page.find_tables()` 기본값만 쓰는데, 그게 실패하면
    표의 글자가 조항 본문에 **평문으로** 섞여 들어간다. 글자는 있는데 행·열이 없다.
    "자기부담금 20%" 는 검색되지만 **그 20% 가 표준형 입원인지 선택형 통원인지 모른다.**
    KCD 표는 더 위험하다 — 질병명과 코드가 잘못 짝지어지면 **오판정**이 된다.
    결함 상세: `docs/reports/debugs/2026-08-02_표추출_구조파괴_결함.md`

★실측 (2026-08-02)

    | 케이스 | `find_tables()` | OpenDataLoader v2.0 | 이 모듈 |
    |---|---|---|---|
    | 흥국화재 `ff0521a99902` p109 KCD (선 있음) | **2×3 붕괴** | 27×3 | **42×3 · 단어배정 100%** |
    | DB `02aaee47b190` p53 용어정의표 (rot90·무테두리·2패널) | **0표** | **0표** | **용어 23개 · 점수 0.97/0.92** |

    ★도구를 갈아치우는 문제가 아니었다. **좌표가 답이다.**
      `find_tables()` 가 격자를 못 엮어도 **선은 `get_drawings()` 에 남아 있고**,
      선이 아예 없어도 좌측 정렬과 여백으로 열을 찾을 수 있다.

★핵심은 **순서**다

    행(baseline)부터 묶으면 안 된다. 용어정의표는 용어가 여러 줄짜리 정의 옆에
    **세로 가운데**로 놓여서, 행으로 묶으면 용어와 정의가 다른 행이 된다.
        열 경계 → 열별 **덩어리** → **y 겹침**으로 짝짓기
    코덱스 표현으로 "시각 줄 · 격자 row · 논리 레코드"는 **서로 다른 개념**이다.

★추정하지 않는다

    경계를 못 고르면 `None` 을 돌려준다. 점수(`score`)를 함께 내보내
    쓰는 쪽이 **믿을지 말지 스스로 판단**하게 한다. 보장한도·자기부담금·
    표준형/선택형·입원/통원·KCD 는 점수가 낮으면 **자동 판정을 멈춰야** 한다.

실행:
    python -m scripts.extract.table_coords <pdf> <0-based page>
"""

from __future__ import annotations

import sys
from collections import defaultdict

import fitz


def words_of(page) -> list[tuple]:
    """`(x0, y0, x1, y1, text)` — 회전을 편 좌표계로.

    ★수동 삼각함수로 돌리면 안 된다. `page.rect` 는 **회전이 반영된** 크기인데
      `get_text("words")` 좌표는 **회전 전** 공간이라 헷갈린다
      (실측 DB p53: rect 751×544 인데 단어 y 가 664 까지).
      `page.rotation_matrix` 를 쓰면 CropBox 원점이 0 이 아닌 문서도 맞는다.
    """
    m = page.rotation_matrix
    out = []
    for x0, y0, x1, y1, t, *_ in page.get_text("words"):
        r = fitz.Rect(x0, y0, x1, y1) * m
        out.append((r.x0, r.y0, r.x1, r.y1, t))
    return out


def median_h(words) -> float:
    """글자 높이 중앙값. ★임계를 여기서 유도한다 — 문서마다 손으로 주지 않는다."""
    hs = sorted(w[3] - w[1] for w in words)
    return hs[len(hs) // 2] if hs else 10.0


def detect_clip(words):
    """본문 영역만 남긴다.

    ★머리말·쪽번호가 **하나만** 있어도 열 추정이 무너진다 —
      그 한 줄이 좌우를 이어 버려 빈 구간이 사라진다(코덱스 지적).
    """
    if not words:
        return None
    h = median_h(words)
    rows = defaultdict(list)
    for w in words:
        rows[round(w[1] / h)].append(w)
    keys = sorted(rows)
    while len(keys) > 2 and len(rows[keys[0]]) <= 3:
        keys.pop(0)
    while len(keys) > 2 and len(rows[keys[-1]]) <= 3:
        keys.pop()
    keep = [w for k in keys for w in rows[k]]
    if not keep:
        return None
    return (min(w[0] for w in keep), min(w[1] for w in keep),
            max(w[2] for w in keep), max(w[3] for w in keep))


def panels(words) -> list[float]:
    """다단(좌우 패널) 분리 — **가장 적게 걸치는** 세로 띠.

    ★"완전히 빈 띠"를 요구하면 못 찾는다. 실측(DB p53) x 히스토그램에서
      360~460 구간이 단어 5~15개로 파여 있는데 **0 은 아니다.**
      두 패널에 걸친 넓은 셀이 있기 때문이다.
    """
    xs = [w[0] for w in words] + [w[2] for w in words]
    lo, hi = min(xs), max(xs)
    step = max(2.0, (hi - lo) / 200)
    best, best_cross = None, None
    x = lo + (hi - lo) * 0.25
    while x < lo + (hi - lo) * 0.75:
        cross = sum(1 for w in words if w[0] < x < w[2])
        if best_cross is None or cross < best_cross:
            best, best_cross = x, cross
        x += step
    if best is None:
        return []
    left = sum(1 for w in words if w[2] <= best) / len(words)
    if best_cross / len(words) < 0.02 and 0.2 < left < 0.8:
        return [best]
    return []


def line_cols(page, clip, min_frac: float = 0.3) -> list[float]:
    """★세로선에서 열 경계를 얻는다 — 있으면 이게 정답이다.

    `find_tables()` 는 선을 **격자로 엮지 못하면** 표를 통째로 놓치지만
    (흥국화재 KCD 22행 → 2×3), **선 자체는 `get_drawings()` 에 그대로 있다.**
    실측: 경계 `66.13 | 86.49 | 165.44 | 445.88` 가 여기서 나오고,
    그걸 쓰면 격자 조립 없이 42×3 이 복원된다.
    """
    if not clip:
        return []
    x0, y0, x1, y1 = clip
    need = (y1 - y0) * min_frac
    m = page.rotation_matrix
    xs = []
    for d in page.get_drawings():
        for it in d["items"]:
            if it[0] != "l":
                continue
            p, q = fitz.Point(it[1]) * m, fitz.Point(it[2]) * m
            if abs(p.x - q.x) > 1.0 or abs(p.y - q.y) < need:
                continue
            xs.append((p.x + q.x) / 2)
    xs = sorted(x for x in xs if x0 - 2 <= x <= x1 + 2)
    out = []
    for x in xs:
        if out and x - out[-1] < 3:
            continue
        out.append(x)
    #: 양끝은 표 테두리라 열 경계가 아니다.
    return out[1:-1] if len(out) >= 3 else []


def drop_vertical_runs(words, h, min_len: int = 3) -> tuple[list, list]:
    """★세로로 세운 글자(사이드바 탭)를 걷어낸다. `(남길 것, 걷어낸 것)`.

    약관은 쪽 옆에 `보`/`통`/`약`/`관` 을 **한 글자씩 세로로** 찍는다.
    회전을 편 좌표계에서는 그게 정의 열 안으로 들어가 본문을 오염시킨다
    (실측 DB `02aaee47b190` p53: 정의 열에 `보 통 약 관` 이 섞였다).

    시그니처: **한 글자 단어가 같은 x 에 3개 이상, y 가 글자높이 간격으로 규칙적.**
        `보`(720.5, 42.6) `통`(720.5, 54.4) `약`(720.5, 66.1) `관`(720.5, 78.0)

    ★걷어낸 것도 **돌려준다.** 조용히 버리지 않는다(RULE §3).
    """
    #: ★★숫자는 제외한다. 표의 **행 번호**(`5` `6` `7`…)가 세로로 쌓여 있어
    #:   그대로 걸면 번호가 사라진다. 실제로 흥국 KCD 표에서 번호 5~9 가 지워져
    #:   `고혈압` 이 결핵·담석증까지 흡수하는 **KCD 오짝**이 났다.
    #: ★그리고 **본문 영역 안쪽은 건드리지 않는다.** 사이드바는 쪽 가장자리에 있다.
    xs_all = [w[0] for w in words] + [w[2] for w in words]
    lo, hi = min(xs_all), max(xs_all)
    edge = (hi - lo) * 0.08
    by_x = defaultdict(list)
    for w in words:
        if len(w[4]) != 1 or w[4].isdigit():
            continue
        if lo + edge < w[0] < hi - edge:      # 가장자리가 아니면 사이드바가 아니다
            continue
        by_x[round(w[0])].append(w)
    drop = set()
    for xs in by_x.values():
        if len(xs) < min_len:
            continue
        xs.sort(key=lambda w: w[1])
        run = [xs[0]]
        for a, b in zip(xs, xs[1:]):
            #: 세로로 잇달아 있는가 — 간격이 글자높이의 2배 이내
            if b[1] - a[1] < h * 2.0:
                run.append(b)
            else:
                if len(run) >= min_len:
                    drop |= {id(z) for z in run}
                run = [b]
        if len(run) >= min_len:
            drop |= {id(z) for z in run}
    keep = [w for w in words if id(w) not in drop]
    return keep, [w for w in words if id(w) in drop]


def logical_records(cells, anchor_col: int = 0):
    """★rowspan 복원 — **y 겹침**으로. 행 순서로 묶으면 틀린다.

    ★처음엔 "번호 행부터 다음 번호 행까지"로 묶었다가 **KCD 오짝을 만들었다**:
        1 심장질환   -> I20~I25, I26~I28  I30~I52, I97  **I60~I69**  ← 뇌혈관질환 것
        2 뇌혈관질환 -> G45, G46, Q28  **E10~E14**                    ← 당뇨병 것
        4 고혈압     -> 결핵·담석증·요로결석증까지 흡수(rowspan 8)
      번호·질병명이 **세로 가운데**에 놓여 코드 줄이 한 칸 위에서 시작하기 때문이다.
      질병명↔코드 오짝은 **이 서비스에서 가장 위험한 실패**다(CLAUDE.md 0장).

    그래서 anchor 셀의 **y 범위와 겹치는 셀만** 가져온다. 용어정의표와 같은 원리.
    ★anchor 가 없는 구간은 **묶지 않고 남긴다**(`no=None`). 추정하지 않는다.

    cells: `[{col, y0, y1, text}]`
    """
    anchors = sorted((c for c in cells
                      if c["col"] == anchor_col and c["text"].strip()
                      and c["text"].strip().isascii() and c["text"].strip().isdigit()),
                     key=lambda c: c["y0"])
    if len(anchors) < 3:
        return []
    recs = []
    for i, a in enumerate(anchors):
        #: ★경계는 **이웃 anchor 의 중간**. anchor 자신의 높이만 쓰면 코드 줄을 놓친다.
        top = (anchors[i - 1]["y1"] + a["y0"]) / 2 if i else a["y0"] - (a["y1"] - a["y0"])
        bot = (a["y1"] + anchors[i + 1]["y0"]) / 2 if i + 1 < len(anchors) else a["y1"] + (a["y1"] - a["y0"])
        by_col = defaultdict(list)
        for c in cells:
            if c["col"] == anchor_col or not c["text"].strip():
                continue
            cy = (c["y0"] + c["y1"]) / 2
            if top <= cy < bot:
                by_col[c["col"]].append(c)
        rec = {"no": int(a["text"].strip()), "y0": top, "y1": bot, "cols": {}}
        for col, cs in by_col.items():
            rec["cols"][col] = " ".join(c["text"] for c in sorted(cs, key=lambda c: c["y0"]))
        recs.append(rec)
    return recs


def rows_of(words, tol):
    """y 대역으로 행 묶기. ★대역을 **고정**한다 — 팽창시키면 연쇄 병합된다."""
    rows = []
    for w in sorted(words, key=lambda x: (x[1], x[0])):
        cy = (w[1] + w[3]) / 2
        hit = next((r for r in rows if r["c"] - tol <= cy <= r["c"] + tol), None)
        if hit:
            hit["ws"].append(w)
        else:
            rows.append({"c": cy, "ws": [w]})
    return rows


def join_words(ws, tol) -> str:
    """셀 안의 단어를 **읽는 순서**로 잇는다.

    ★x 로만 정렬하면 여러 줄짜리 정의가 뒤섞인다 —
      실제로 `계약을계약 체결하기 위하여…` 가 나왔다.
      **줄(y)로 먼저 묶고 줄 안에서 x** 로 정렬해야 한다(코덱스 지적).
    ★붙임: x 간격이 1pt 미만이면 줄바꿈으로 갈린 한 낱말이다
      (`계약자에 게` · `의료기 관` 이 그렇게 생겼다).
    """
    parts = []
    for r in sorted(rows_of(ws, tol), key=lambda r: r["c"]):
        line, prev = [], None
        for w in sorted(r["ws"], key=lambda x: x[0]):
            if prev is not None and w[0] - prev < 1.0:
                line[-1] += w[4]
            else:
                line.append(w[4])
            prev = w[2]
        parts.append(" ".join(line))
    return " ".join(parts)


def blocks_of(words, gap):
    """y 로 이어지는 **덩어리**. ★행이 아니다.

    용어정의표는 용어가 여러 줄짜리 정의 옆에 **세로 가운데**로 놓인다.
    행(baseline)으로 묶으면 용어와 정의가 다른 행이 되어 짝을 못 짓는다.
    """
    out = []
    for w in sorted(words, key=lambda x: x[1]):
        if out and w[1] - max(z[3] for z in out[-1]) < gap:
            out[-1].append(w)
        else:
            out.append([w])
    return out


def pair_two_col(words, h, bound, tol):
    """경계 하나로 2열 표를 짝짓고 **점수**를 낸다."""
    left = [w for w in words if w[2] <= bound]
    right = [w for w in words if w[0] >= bound]
    if len(left) < 3 or len(right) < 3:
        return None
    lb, rb = blocks_of(left, h * 0.8), blocks_of(right, h * 0.8)
    if len(lb) < 3:
        return None
    pairs, matched = [], 0
    for t in lb:
        ty0, ty1 = min(w[1] for w in t), max(w[3] for w in t)
        m = [b for b in rb
             if not (max(w[3] for w in b) < ty0 - 2 or min(w[1] for w in b) > ty1 + 2)]
        if m:
            matched += 1
        pairs.append((join_words(t, tol), join_words([w for b in m for w in b], tol)))
    #: ★검증 — 왼쪽 덩어리가 오른쪽과 **1:1 로 붙는 비율.**
    #:   단어 커버리지만 보면 안 된다. **전부 한 셀에 넣어도 커버리지는 100%** 다.
    return {"bound": bound, "pairs": pairs, "score": matched / len(lb),
            "n_left": len(lb), "n_right": len(rb)}


def find_two_col(words, h, tol, min_score: float = 0.6):
    """★경계를 **검증 점수로 고른다.** 후보를 다 만들어 보고 제일 잘 붙는 것을 쓴다."""
    xs = sorted(set(round(w[2]) for w in words))
    if not xs:
        return None
    lo, hi = xs[0], xs[-1]
    best = None
    x = lo + (hi - lo) * 0.05
    while x < lo + (hi - lo) * 0.6:
        #: ★가로지르는 단어를 **금지하지 않는다.** 제목 한 줄이 전폭이면 후보가 다 죽는다.
        #:   대신 벌점으로 주고 점수로 고른다.
        cross = sum(1 for w in words if w[0] < x < w[2])
        r = pair_two_col(words, h, x, tol)
        if r:
            r["score"] -= cross / len(words)
            if best is None or (r["score"], r["n_left"]) > (best["score"], best["n_left"]):
                best = r
        x += h * 0.5
    return best if best and best["score"] >= min_score else None


def build_grid(words, bounds, tol):
    """경계를 받아 격자를 만든다. 열 배정은 **겹침 폭이 최대인 열**로."""
    ncol = len(bounds) + 1
    edges = [-1e9] + list(bounds) + [1e9]
    grid, assigned, flat = [], 0, []
    for r in sorted(rows_of(words, tol), key=lambda r: r["c"]):
        cells = defaultdict(list)
        for w in r["ws"]:
            best, bi = -1.0, 0
            for i in range(ncol):
                ov = min(w[2], edges[i + 1]) - max(w[0], edges[i])
                if ov > best:
                    best, bi = ov, i
            cells[bi].append(w)
            assigned += 1
        row = []
        for i in range(ncol):
            ws2 = cells.get(i, [])
            row.append(join_words(ws2, tol))
            if ws2:
                flat.append({"col": i, "text": row[-1],
                             "y0": min(w[1] for w in ws2), "y1": max(w[3] for w in ws2)})
        grid.append(row)
    #: ★첫 열이 `1…22` 처럼 단조 증가하면 표일 가능성이 높다(약한 신호).
    firsts = [r[0].strip() for r in grid if r[0].strip()]
    nums = [int(x) for x in firsts if x.isascii() and x.isdigit()]
    return {"cols": ncol, "rows": len(grid), "grid": grid, "cells": flat,
            "word_coverage": round(assigned / len(words), 3) if words else 0.0,
            "first_col_monotonic": len(nums) >= 3 and all(a < b for a, b in zip(nums, nums[1:]))}


def extract(page) -> list[dict]:
    """페이지에서 표 후보를 만든다. 못 만들면 빈 목록."""
    ws = words_of(page)
    if not ws:
        return []
    clip = detect_clip(ws)
    if clip:
        ws = [w for w in ws if clip[0] - 1 <= w[0] and w[2] <= clip[2] + 1
              and clip[1] - 1 <= w[1] and w[3] <= clip[3] + 1]
    if len(ws) < 5:
        return []
    h = median_h(ws)
    #: ★세로 사이드바를 먼저 걷어낸다. 안 하면 정의 열이 오염된다.
    ws, dropped = drop_vertical_runs(ws, h)
    if len(ws) < 5:
        return []
    tol = h * 0.3
    lines = line_cols(page, clip)
    out = []
    edges = [-1e9] + panels(ws) + [1e9]
    for i in range(len(edges) - 1):
        #: ★패널마다 **자기 y 축**으로. 전역 y 로 맞추면 왼쪽 14행·오른쪽 10행이 깨진다.
        sub = [w for w in ws if edges[i] <= w[0] < edges[i + 1]]
        if len(sub) < 5:
            continue
        mine = [x for x in lines if edges[i] < x < edges[i + 1]]
        if mine:
            r = build_grid(sub, mine, tol)
            r.update(method="선", panel=i + 1,
                     dropped_vertical=len(dropped),
                     records=logical_records(r.pop("cells")))
            out.append(r)
            continue
        two = find_two_col(sub, h, tol)
        if two:
            out.append({"method": "2열짝짓기", "panel": i + 1, "cols": 2,
                        "rows": len(two["pairs"]), "grid": [list(p) for p in two["pairs"]],
                        "score": round(two["score"], 3), "word_coverage": None,
                        "first_col_monotonic": False,
                        "dropped_vertical": len(dropped)})
    return out


def main() -> None:
    src, pno = sys.argv[1], int(sys.argv[2])
    doc = fitz.open(src)
    page = doc[pno]
    print(f"rotation={page.rotation} · find_tables()={len(page.find_tables().tables)}표")
    for t in extract(page):
        head = {k: v for k, v in t.items() if k != "grid"}
        print(f"\n-- {head}")
        for row in t["grid"][:12]:
            print("   ", [c[:30] for c in row])


if __name__ == "__main__":
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    main()
