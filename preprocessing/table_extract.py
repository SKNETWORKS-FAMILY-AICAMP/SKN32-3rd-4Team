# -*- coding: utf-8 -*-
"""
table_extract.py — pdfplumber로 표를 뽑아 '표 청크'로 만들고, 같은 페이지의
조항에 연결한다. 본문 청크와 동일한 메타 스키마라서 chunks_all.jsonl에 그대로
합쳐진다(content_type='table').

pdfplumber 기본 추출은 1열 레이아웃 조각 등 가짜 표가 많아, 아래 필터로 실표만
남긴다. 기존 extract_tables.py에 튜닝한 옵션이 있으면 TABLE_SETTINGS만 교체.
"""
import re

try:
    import pdfplumber
except Exception:  # pdfplumber 없으면 표 없이 진행
    pdfplumber = None

from clause_detector import normalize, collapse_glyph_dup

MAX_CHARS = 1500
# 실표 판정 임계
MIN_ROWS = 2
MIN_COLS = 2
MIN_FILLED = 4          # 채워진 셀 최소 수
MIN_DENSITY = 0.30      # 채워진 셀 비율
MIN_TEXTLEN = 30        # 표 전체 텍스트 최소 길이

# 선(ruling) 기반 기본 추출만 사용 — 빠르고 노이즈 적음.
# 선 없는 표까지 잡으려면 text-strategy를 추가할 수 있으나 대량 처리에선 매우 느림.
TABLE_SETTINGS = [{}]


def _clean_cell(c):
    if not c:
        return ''
    s = normalize(str(c)).replace('\n', ' ')
    s, _ = collapse_glyph_dup(s)
    return re.sub(r'\s+', ' ', s).strip()


def _is_real_table(rows):
    if len(rows) < MIN_ROWS:
        return False
    ncols = max((len(r) for r in rows), default=0)
    if ncols < MIN_COLS:
        return False
    cells = [c for r in rows for c in r]
    filled = sum(1 for c in cells if c)
    if filled < MIN_FILLED:
        return False
    if cells and filled / len(cells) < MIN_DENSITY:
        return False
    if sum(len(c) for c in cells) < MIN_TEXTLEN:
        return False
    return True


def _to_markdown(rows):
    ncols = max(len(r) for r in rows)
    norm = [[*(r + [''] * (ncols - len(r)))] for r in rows]
    head = norm[0]
    md = ['| ' + ' | '.join(head) + ' |',
          '| ' + ' | '.join(['---'] * ncols) + ' |']
    for r in norm[1:]:
        md.append('| ' + ' | '.join(r) + ' |')
    return '\n'.join(md), head


def _split_rows(rows):
    """표가 크면 헤더행을 유지하며 행 단위로 분할."""
    md, head = _to_markdown(rows)
    if len(md) <= MAX_CHARS:
        return [rows]
    out, cur = [], [rows[0]]
    for r in rows[1:]:
        cur.append(r)
        test, _ = _to_markdown(cur)
        if len(test) > MAX_CHARS and len(cur) > 2:
            out.append(cur); cur = [rows[0]]      # 헤더행 반복
    if len(cur) > 1:
        out.append(cur)
    return out


def extract_table_chunks(path, page_clause, meta, gid_start=0):
    """
    path        : PDF 경로
    page_clause : {page_idx: dict(article_no, article_title, section)} — 표를 조항에 연결
    meta        : insurer/generation/doc_name/doc_id/part
    반환        : (table_chunks, n_tables)
    """
    if pdfplumber is None:
        return [], 0
    chunks = []
    gid = gid_start
    n_tab = 0
    try:
        pdf = pdfplumber.open(path)
    except Exception:
        return [], 0
    for pi, page in enumerate(pdf.pages):
        # 격자 선이 거의 없는 페이지는 선기반 표가 없으므로 건너뜀(대폭 가속)
        try:
            h_edges = sum(1 for e in page.edges if e.get('orientation') == 'h')
            v_edges = sum(1 for e in page.edges if e.get('orientation') == 'v')
            if h_edges < 3 or v_edges < 2:
                continue
        except Exception:
            pass
        found = []
        for st in TABLE_SETTINGS:
            try:
                tbls = page.extract_tables(st) if st else page.extract_tables()
            except Exception:
                tbls = []
            if tbls:
                found = tbls
                break
        for t in found:
            rows = [[_clean_cell(c) for c in r] for r in t]
            rows = [r for r in rows if any(r)]           # 완전 빈 행 제거
            if not _is_real_table(rows):
                continue
            ctx = page_clause.get(pi, {})
            art = ctx.get('article_no')
            art_title = ctx.get('article_title', '')
            section = ctx.get('section', '본문')
            cite_base = (f"제{art}조({art_title})" if art else f"p{pi+1}") + " [표]"
            for si, sub in enumerate(_split_rows(rows)):
                md, head = _to_markdown(sub)
                if len(md) > MAX_CHARS:
                    md = md[:MAX_CHARS]
                n_tab += 1
                gid += 1
                cont = ' (이어짐)' if si > 0 else ''
                chunks.append(dict(
                    insurer=meta['insurer'], generation=meta['generation'],
                    doc_name=meta['doc_name'],
                    article_no=art, article_sub=None, article_title=art_title,
                    paragraph_no=None, item_no=None, item_list='',
                    citation=cite_base + cont,
                    section=section, part=meta.get('part', ''),
                    content_type='table',
                    header=f"[표] {head[:3]}",
                    page=pi,
                    chunk_id=f"{meta['doc_id']}#T{gid:05d}::표p{pi+1}",
                    text=(cite_base + '\n' + md),
                ))
    pdf.close()
    return chunks, n_tab