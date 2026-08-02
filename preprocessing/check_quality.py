# -*- coding: utf-8 -*-
"""본문(clause)·표(table) 청크 품질 감사 — 용어 감사와 동일한 취지의 전수 검사.

검사 항목
  [공통] 빈/초미세 텍스트, 인코딩 깨짐(한글비율), chunk_id 중복, 과대 청크
  [본문] 조항 메타 누락, 항 번호 이상치, 목차 점선 잔재, 요약서 등 필러 혼입,
         겹침-글리프(단어 3연속 반복) 잔재
  [표]   데이터 없는 빈 표, 숫자 쓰레기 표, 조항 미연결 비율, 문서 내 중복 표

사용: python check_quality.py            # out/chunks_main.jsonl 검사
      python check_quality.py <경로>     # 다른 파일 검사
"""
import json
import re
import sys
from collections import Counter, defaultdict

PATH = sys.argv[1] if len(sys.argv) > 1 else 'out/chunks_main.jsonl'

RE_HANGUL = re.compile(r'[가-힣]')
RE_LETTER = re.compile(r'[가-힣A-Za-z]')
RE_DOTLEAD = re.compile(r'[·.]{4,}')
RE_TRIPLE = re.compile(r'(\S{2,8})\s+\1\s+\1')          # 같은 단어 3연속
FILLERS = ('약관 요약서', '쉽게 이해하는', '민원 예시', '문답식 상품해설',
           'QR코드', '가이드북')

ids = Counter()
stat = Counter()
ex = defaultdict(list)          # 항목별 예시
tables_per_doc = defaultdict(Counter)   # 문서 내 중복 표 검출용
n_clause = n_table = 0

def add(kind, c, note=''):
    stat[kind] += 1
    if len(ex[kind]) < 3:
        ex[kind].append(f"{c['doc_name'][:20]} | {c['citation'][:36]} | {note or c['text'][:46]}".replace('\n', ' '))

with open(PATH, encoding='utf-8') as f:
    for line in f:
        c = json.loads(line)
        t = c['text']
        ids[c['chunk_id']] += 1
        letters = len(RE_LETTER.findall(t))
        hangul = len(RE_HANGUL.findall(t))

        # ── 공통 ──
        if not t.strip():
            add('공통: 빈 텍스트', c); continue
        if len(t.strip()) < 20:
            add('공통: 초미세(<20자)', c)
        if letters >= 20 and hangul / letters < 0.3:
            add('공통: 인코딩 의심(한글<30%)', c, t[:46])
        if len(t) > 2200:
            add('공통: 과대(>2200자)', c, f"{len(t)}자")

        if c['content_type'] == 'clause':
            n_clause += 1
            if not c.get('article_no'):
                add('본문: 조 번호 누락', c)
            p = c.get('paragraph_no')
            if p and (p < 1 or p > 30):
                add('본문: 항 번호 이상치', c, f"항={p}")
            if RE_DOTLEAD.search(t):
                add('본문: 목차 점선 잔재', c)
            for m in FILLERS:
                if m in t:
                    add('본문: 필러 혼입 의심', c, m); break
            if RE_TRIPLE.search(t):
                add('본문: 글리프 반복 잔재', c)

        elif c['content_type'] == 'table':
            n_table += 1
            data_rows = [l for l in t.split('\n')
                         if l.startswith('|') and '---' not in l]
            if len(data_rows) <= 1:
                add('표: 데이터 행 없음', c)
            cells = [x.strip() for l in data_rows for x in l.split('|')[1:-1]]
            filled = [x for x in cells if x]
            if cells and len(filled) / len(cells) < 0.25:
                add('표: 빈 셀 과다(<25%)', c)
            if letters >= 10 and hangul / max(letters, 1) < 0.3:
                pass  # 공통 인코딩 항목에서 이미 집계
            if not c.get('article_no'):
                stat['표: 조항 미연결(참고)'] += 1
            # 문서 내 동일 표 반복(내용 해시)
            doc = c['chunk_id'].split('#')[0]
            body_key = hash('\n'.join(data_rows))
            tables_per_doc[doc][body_key] += 1

n_total = n_clause + n_table
dup_ids = sum(1 for v in ids.values() if v > 1)
dup_tables = sum(v - 1 for cnt in tables_per_doc.values() for v in cnt.values() if v > 1)

print(f"검사 대상: {PATH}")
print(f"총 {n_total:,}청크 (본문 {n_clause:,} / 표 {n_table:,})\n")
print(f"chunk_id 중복: {dup_ids}")
print(f"문서 내 동일 표 반복: {dup_tables}개 (참고 — 특약별 반복일 수 있음)")
print()
if not any(k for k in stat if not k.endswith('(참고)')):
    print("발견된 결함 없음")
for kind in sorted(stat):
    print(f"[{stat[kind]:>5}] {kind}")
    for e in ex.get(kind, []):
        print(f"        {e}")