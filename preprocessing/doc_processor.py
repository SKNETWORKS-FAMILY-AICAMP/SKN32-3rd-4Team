# -*- coding: utf-8 -*-
"""
doc_processor.py — 단일 약관 PDF → 조항 청크 + 품질지표.

preprocess.py 설계(추출 2모드 자동선택 / 클리닝 / 조항 청킹 / 계층 분할)를
clause_detector 의 하드닝된 헤더 검출과 결합한 실행 모듈.
배치 러너가 문서별로 호출한다.
"""
import re
import fitz  # pymupdf
from clause_detector import (
    normalize, detect_headers, looks_like_non_terms, RE_APPENDIX,
    collapse_glyph_dup, parse_clause_body,
)

# 클리닝 정규식
RE_PAGENUM = re.compile(r'^\s*[ⅠⅡⅢⅣ]?\s*[-–]?\s*\d{1,4}\s*$')  # 페이지번호 줄
RE_DOTLEAD = re.compile(r'[·.]{3,}')                              # 목차 점선
RE_PAGEREF = re.compile(r'\(?\bP\.?\s?\d{1,4}\b\)?')             # 페이지참조 P55
MAX_CHARS = 1500
OVERLAP = 100
MIN_CLAUSE_LEN = 50


# ────────────────────────────────────────────────────────────────
# 추출 (2모드 자동선택)
# ────────────────────────────────────────────────────────────────
def _pages_text(doc, sort):
    return [normalize(doc[i].get_text(sort=sort)) for i in range(len(doc))]


def _score_mode(pages):
    """조항 헤더 수 + 순차성 점수 (높을수록 좋은 추출)."""
    lines, pmap = [], []
    for pi, t in enumerate(pages):
        for ln in t.split('\n'):
            lines.append(ln); pmap.append(pi)
    heads, stats = detect_headers(lines, pmap)
    # 순차성: 인접 조 번호가 +1 로 이어지는 비율
    seq = 0
    for a, b in zip(heads, heads[1:]):
        if b.num == a.num + 1:
            seq += 1
    return stats['accepted'] + seq, heads, stats, lines, pmap


def extract_best(path):
    """스트림/좌표정렬 두 모드 중 조항 구조가 잘 살아나는 쪽 선택."""
    doc = fitz.open(path)
    pstream = _pages_text(doc, sort=False)
    psorted = _pages_text(doc, sort=True)
    doc.close()
    s_stream, *_ = _score_mode(pstream)
    s_sorted, *_ = _score_mode(psorted)
    if s_sorted > s_stream:
        mode, pages = 'sorted', psorted
    else:
        mode, pages = 'stream', pstream  # 동점/우세 시 스트림(2단 조판 안전)
    return mode, pages


# ────────────────────────────────────────────────────────────────
# 클리닝
# ────────────────────────────────────────────────────────────────
def clean_lines(pages):
    lines, pmap = [], []
    for pi, t in enumerate(pages):
        for ln in t.split('\n'):
            s = ln.rstrip()
            if not s.strip():
                continue
            if RE_PAGENUM.match(s.strip()):
                continue
            if RE_DOTLEAD.search(s):          # 목차 잔해
                continue
            s = RE_PAGEREF.sub('', s)
            lines.append(s); pmap.append(pi)
    return lines, pmap


def find_appendix_start(lines):
    """문서 후반 50%에서 부록/관계법령 경계 첫 위치."""
    half = len(lines) // 2
    for i in range(half, len(lines)):
        if RE_APPENDIX.search(lines[i]) and len(lines[i]) < 30:
            return i
    return len(lines)


# ────────────────────────────────────────────────────────────────
# 청킹
# ────────────────────────────────────────────────────────────────
_SEPS = [r'(?=[①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮])', r'\n\n', r'(?<=[.。])\s']


def _force_cut(text, max_chars, overlap):
    step = max(1, max_chars - overlap)
    return [text[i:i + max_chars] for i in range(0, len(text), step)]


def _recursive_split(text, max_chars=MAX_CHARS, overlap=OVERLAP, level=0):
    """항(①)→문단→문장→강제 절단. level 로 구분자 단계를 전진시켜 무한재귀 방지."""
    if len(text) <= max_chars:
        return [text]
    if level >= len(_SEPS):
        return _force_cut(text, max_chars, overlap)
    parts = re.split(_SEPS[level], text)
    if len(parts) <= 1:
        return _recursive_split(text, max_chars, overlap, level + 1)
    chunks, cur = [], ''
    for p in parts:
        if len(cur) + len(p) <= max_chars:
            cur += p
        else:
            if cur:
                chunks.append(cur)
            cur = (cur[-overlap:] if cur else '') + p
    if cur:
        chunks.append(cur)
    out = []
    for c in chunks:
        # 이 단계로도 안 줄면 다음 단계 구분자로 강제 전진
        out.extend([c] if len(c) <= max_chars
                   else _recursive_split(c, max_chars, overlap, level + 1))
    return out


# 첫 줄(헤더 라인)에서 조 헤더 라벨 접두를 떼어 본문 서두만 남김
RE_STRIP_JO = re.compile(r'^제\s*\d{1,3}\s*조\s*[\(（【\[][^)）】\]]*[\)）】\]]?\s*')
RE_STRIP_NUM = re.compile(r'^\d{1,3}(?:-\d{1,2})?\.\s*[\(（][^)）]*[\)）]?\s*')


def _split_by_ho(text, items):
    """항이 1500자 초과 시 호(1. / 가. / 1)) 경계로 분할, 각 조각의 대표 호 라벨 반환."""
    from clause_detector import match_ho
    pieces, labels = [], []
    cur, cur_lbl = [], None
    for ln in text.split('\n'):
        s = ln.strip()
        m = match_ho(s)
        if m and cur:
            pieces.append('\n'.join(cur)); labels.append(cur_lbl)
            cur, cur_lbl = [s], m[0]
        else:
            if m and not cur:
                cur_lbl = m[0]
            cur.append(s)
    if cur:
        pieces.append('\n'.join(cur)); labels.append(cur_lbl)
    return pieces, labels


MIN_TAIL = 40   # 이어짐 꼬리가 이보다 짧으면 앞 조각에 합쳐 에코 청크 방지


def _pieces_for_unit(u):
    """한 항(unit)을 (조각텍스트, 호라벨) 리스트로 분해 + 미세 꼬리 병합."""
    if len(u['text']) > MAX_CHARS:
        subs, sublabels = _split_by_ho(u['text'], u['items'])
    else:
        subs, sublabels = [u['text']], [None]
    flat = []
    for piece, ho_lbl in zip(subs, sublabels):
        for small in _recursive_split(piece):
            flat.append([small, ho_lbl])
    # 미세 꼬리 병합: 짧은 조각을 직전 조각에 흡수(첫 조각이면 다음에 흡수)
    merged = []
    for txt, lbl in flat:
        if merged and len(txt.strip()) < MIN_TAIL:
            merged[-1][0] += '\n' + txt
        else:
            merged.append([txt, lbl])
    if len(merged) >= 2 and len(merged[0][0].strip()) < MIN_TAIL:
        merged[1][0] = merged[0][0] + '\n' + merged[1][0]
        merged.pop(0)
    return merged


def build_chunks(lines, pmap, headers, appendix_at, meta):
    """헤더 경계로 조 슬라이스 → 항(①) 단위 청킹 + 조/항/호 메타 부여.

    반환: (chunks, cov) — cov: 정직한 커버리지 계산용 dict
      · captured_core : 조 본문으로 파싱돼 담긴 원문 글자수(분할/겹침 비반영)
      · body_region   : 첫 조 이후 영역 글자수
      · front_lines   : 첫 조 이전(서문/목차) 라인 수
    """
    chunks = []
    gid = 0                      # 문서 내 전역 청크 순번 → chunk_id 유일성 보장
    captured_core = 0
    n_para_units = 0             # 실제 항 총개수(특약별 중복 유지, 분할 비반영)
    n_ho_total = 0              # 실제 호 총개수
    idx_of, hi = {}, 0
    for i, ln in enumerate(lines):
        if hi < len(headers) and headers[hi].raw == ln.strip():
            idx_of[hi] = i; hi += 1
    bounds = [(k, idx_of[k]) for k in range(len(headers)) if k in idx_of]
    first_start = bounds[0][1] if bounds else len(lines)
    body_region = sum(len(lines[i]) for i in range(first_start, len(lines))) or 1

    for bi, (k, start) in enumerate(bounds):
        end = bounds[bi + 1][1] if bi + 1 < len(bounds) else len(lines)
        h = headers[k]
        section = '부록(관계법령)' if start >= appendix_at else '본문'
        # 헤더 라인에서 라벨 접두 제거 → 본문 서두
        first = lines[start].strip()
        first = (RE_STRIP_NUM.sub('', first) if h.kind == 'num'
                 else RE_STRIP_JO.sub('', first))
        body_lines = ([first] if first else []) + [l.strip() for l in lines[start + 1:end]]

        units = parse_clause_body(body_lines)
        if not units:
            continue

        for u in units:
            # 줄바꿈 문자 제외하고 순수 글자수만 — 분모(body_region)와 단위 일치
            captured_core += len(u['text'].replace('\n', ''))
            if u['paragraph_no']:
                n_para_units += 1
            n_ho_total += len(u['items'])
            pno = u['paragraph_no']
            base_cite = h.label + (f" 제{pno}항" if pno else '')
            pieces = _pieces_for_unit(u)
            for si, (small, ho_lbl) in enumerate(pieces):
                    is_cont = (si > 0)
                    cite = base_cite + (f" 제{ho_lbl}호" if ho_lbl else '')
                    hdr = h.label if not is_cont else f"[{cite} - 이어짐]"
                    gid += 1
                    chunks.append(dict(
                        insurer=meta['insurer'], generation=meta['generation'],
                        doc_name=meta['doc_name'],
                        article_no=h.num, article_sub=h.sub, article_title=h.title,
                        paragraph_no=pno,
                        item_no=ho_lbl,
                        item_list=';'.join(u['items']) if u['items'] else '',
                        citation=cite,
                        section=section, part=meta.get('part', ''),
                        content_type='clause', header=hdr, page=pmap[start],
                        chunk_id=f"{meta['doc_id']}#{gid:05d}::{h.label}"
                                 + (f"항{pno}" if pno else ''),
                        text=(f"{h.label}" + (f" 제{pno}항" if pno else '') + "\n" + small
                              if is_cont else small),
                    ))
    cov = dict(captured_core=captured_core, body_region=body_region,
               front_lines=first_start, total_lines=len(lines),
               n_para_units=n_para_units, n_ho_total=n_ho_total)
    return chunks, cov


# ────────────────────────────────────────────────────────────────
# 문서 처리 진입점
# ────────────────────────────────────────────────────────────────
def _page_clause_map(headers, appendix_at, lines):
    """페이지 → 그 페이지에 걸린 조항(직전 헤더). 표를 조에 연결하는 데 사용."""
    if not headers:
        return {}
    # (page, header) 를 페이지 오름차순으로
    hs = sorted(((h.page, h) for h in headers), key=lambda x: x[0])
    max_pg = max(h.page for h in headers)
    pm, hi, cur = {}, 0, None
    for pg in range(0, max_pg + 1):
        while hi < len(hs) and hs[hi][0] <= pg:
            cur = hs[hi][1]; hi += 1
        if cur:
            pm[pg] = dict(article_no=cur.num, article_title=cur.title,
                          section='본문')
    return pm


def process_document(path, meta, with_tables=False):
    """
    반환: (chunks, quality)
      quality: dict — 배치 품질 리포트 한 행
    """
    mode, pages = extract_best(path)
    full_head_text = '\n'.join(pages[:3])

    lines, pmap = clean_lines(pages)
    headers, stats = detect_headers(lines, pmap)
    # 비약관은 '방법서 시그널 + 조항 거의 없음' 을 동시 만족할 때만(유의사항 서문 오탐 방지)
    non_terms = looks_like_non_terms(full_head_text) and len(headers) < 5
    appendix_at = find_appendix_start(lines)
    chunks, cov = build_chunks(lines, pmap, headers, appendix_at, meta)

    # 겹침-글리프 아티팩트 정제
    glyph_dup = 0
    for c in chunks:
        c['text'], h1 = collapse_glyph_dup(c['text'])
        c['article_title'], _ = collapse_glyph_dup(c['article_title'])
        glyph_dup += h1

    # 표 청크(선택) — 같은 페이지의 조항에 연결해 본문 청크와 병합
    n_tables = 0
    if with_tables:
        from table_extract import extract_table_chunks
        pcmap = _page_clause_map(headers, appendix_at, lines)
        tchunks, n_tables = extract_table_chunks(path, pcmap, meta,
                                                 gid_start=len(chunks))
        chunks.extend(tchunks)

    # 정직한 커버리지: 첫 조 이후 본문영역 중 실제 조 본문으로 담긴 원문 비율.
    # 분자·분모 모두 줄바꿈 제외 순수 글자수 — 정상이면 100을 넘을 수 없음.
    # (혹시 100 초과가 나오면 중복 산입 버그이므로 가리지 말고 그대로 노출)
    coverage = round(100 * cov['captured_core'] / cov['body_region'], 1)
    front_pct = round(100 * cov['front_lines'] / (cov['total_lines'] or 1), 1)
    wrapped = sum(1 for h in headers if h.title_wrapped)
    n_para = cov['n_para_units']          # 실제 항 총개수(특약 반복 유지)
    n_item = cov['n_ho_total']            # 실제 호 총개수
    para_chunks = sum(1 for c in chunks if c['paragraph_no'])

    quality = dict(
        doc_id=meta['doc_id'], doc_name=meta['doc_name'],
        insurer=meta['insurer'], generation=meta['generation'],
        category=meta.get('part', ''),
        pages=len(pages), extract_mode=mode, style=stats['style'],
        n_clauses=len(headers), n_chunks=len(chunks),
        n_tables=n_tables,
        n_paragraphs=n_para, n_items=n_item, para_chunks=para_chunks,
        coverage_pct=coverage, front_matter_pct=front_pct, wrapped_titles=wrapped,
        glyph_dup_fixed=glyph_dup,
        rejected_outliers=stats['rejected_outlier'],
        appendix_split=(appendix_at < len(lines)),
        non_terms_doc=non_terms,
    )
    return chunks, quality