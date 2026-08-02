# -*- coding: utf-8 -*-
"""(v2) 용어정의표 청크 → 용어 1개당 1청크(content_type='term')로 분해.

v2 변경점 (임베딩팀 품질 보고 반영):
  1. term_key(공백 제거 정규화) 추가 — 줄바꿈 잔재 공백("동등하 다고")이 있어도
     동일 용어로 취급·매칭 가능. term(표시용)은 연속 공백만 1칸으로 정리.
  2. 숫자 쓰레기 행 제거 — 표 추출 노이즈(숫자 4개 이상 또는 숫자비율 20%↑).
  3. 문서 내 중복 제거 — 같은 (용어, 정의) 쌍이 특약마다 반복되는 것 1회만 유지.
  4. 잘린 용어 표식 — '및/또는' 등으로 끝나는 용어는 term_quality='truncated' 표시
     (페이지 경계에서 용어 칸이 잘린 케이스, 정의는 유효하므로 유지).
  ※ '입원의 정의 중 ...' 류 긴 용어는 원본 표에 실재하는 정식 용어명임을 원본
     PDF로 확인 — 직전 용어에 병합하지 않고 독립 용어로 유지한다.
"""
import json
import re

RE_DIGITS = re.compile(r'\d')
RE_WS = re.compile(r'\s+')


def parse_header(line):
    h = line.replace('용용어어', '용어').replace('정정의의', '정의')
    return ('용어' in h) and ('정의' in h)


def clean_display(s):
    """연속 공백 1칸으로. (한글 어중 공백은 원형 보존 — term_key로 매칭 해결)"""
    return RE_WS.sub(' ', s).strip()


def term_key(s):
    """공백·따옴표 제거 정규화 키 — 줄바꿈 잔재와 무관하게 동일 용어 식별."""
    return re.sub(r"[\s'‘’“”\"']", '', s)


def is_junk(term):
    """표 추출 노이즈 행: 숫자 조각이 섞인 용어."""
    digits = len(RE_DIGITS.findall(term))
    if digits >= 4:
        return True
    core = term_key(term)
    return bool(core) and digits / max(len(core), 1) > 0.2


def is_truncated(term):
    return term.rstrip("'’").endswith(('및', '또는', '과', '와'))


def rows_of(text):
    """마크다운 표 행 → [용어, 정의] 목록 (머리행·구분행 제외, 이어짐 행 병합)"""
    out = []
    for line in text.split('\n'):
        if not line.startswith('|'):
            continue
        cells = [x.strip() for x in line.split('|')][1:-1]
        if len(cells) < 2 or set(cells[0]) <= {'-', ' '}:
            continue
        if parse_header(line):
            continue
        term, definition = cells[0], ' '.join(c for c in cells[1:] if c)
        if not term and out:              # 용어 칸 비면 앞 용어의 이어진 정의
            out[-1][1] += ' ' + definition
        elif term:
            out.append([term, definition])
    return out


total = kept = made = removed = junk = dup = trunc = 0
seen = {}   # doc -> set of (term_key, def_key)
seq = {}
with open('out/chunks_clean.jsonl', encoding='utf-8') as fin, \
     open('out/chunks_final.jsonl', 'w', encoding='utf-8') as fout:
    for line in fin:
        c = json.loads(line)
        total += 1
        is_terms = c['content_type'] == 'table' and any(
            parse_header(l) for l in c['text'].split('\n') if l.startswith('|'))
        if not is_terms:
            fout.write(line); kept += 1
            continue
        removed += 1
        doc = c['chunk_id'].split('#')[0]
        seen.setdefault(doc, set())
        for term_raw, def_raw in rows_of(c['text']):
            term = clean_display(term_raw)
            definition = clean_display(def_raw)
            if not definition:
                continue
            if is_junk(term):
                junk += 1
                continue
            key = (term_key(term), term_key(definition)[:60])
            if key in seen[doc]:          # 문서 내 반복(특약별 중복) 제거
                dup += 1
                continue
            seen[doc].add(key)
            quality = 'truncated' if is_truncated(term) else 'ok'
            if quality == 'truncated':
                trunc += 1
            seq[doc] = seq.get(doc, 0) + 1
            t = dict(c)
            t['content_type'] = 'term'
            t['article_no'] = None
            t['article_title'] = '용어의 정의'
            t['paragraph_no'] = None; t['item_no'] = None; t['item_list'] = ''
            t['term'] = term
            t['term_key'] = term_key(term)
            t['term_quality'] = quality
            t['citation'] = f'용어의 정의 - {term}'
            t['chunk_id'] = f'{doc}#G{seq[doc]:04d}::용어::{term_key(term)[:20]}'
            t['text'] = f'[용어] {term}: {definition}'
            fout.write(json.dumps(t, ensure_ascii=False) + '\n')
            made += 1

print(f'입력 {total} → 유지 {kept} + 용어청크 {made} (표덩어리 {removed}개 분해)')
print(f'  정리: 문서내중복 {dup} 제거, 숫자노이즈 {junk} 제거, 잘림표식 {trunc}')
print(f'최종: out/chunks_final.jsonl = {kept + made}청크')