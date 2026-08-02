# -*- coding: utf-8 -*-
"""(v2) chunks_all.jsonl 정제 → chunks_clean.jsonl.

v2 변경점 (본문·표 품질 감사 반영):
  1. 초미세 조각 제거 — 조 제목 줄바꿈 꼬리("와계약의해지]", "]" 등) 20자 미만.
  2. 깨진 표 제거 — 폰트 CID 미해석 '(cid:...)' 또는 한글 비율 30% 미만인 표.
  3. (기존) 인코딩 깨진 문서(삼성 95683)·동양 사업방법서 청크를 doc_id 기준 제외.
"""
import json
import csv
import re
from collections import Counter

RE_HANGUL = re.compile(r'[가-힣]')
RE_LETTER = re.compile(r'[가-힣A-Za-z]')

# 1) 제외할 doc_id: 인코딩 깨진 95683 + 동양 사업방법서(비약관)
excl = {'95683'}
try:
    with open('out/failures.csv', encoding='utf-8-sig') as f:
        for r in csv.DictReader(f):
            if '비약관' in r['fail_reason'] and r['insurer'] == '동양생명':
                excl.add(r['doc_id'])
except FileNotFoundError:
    pass
print('제외 doc_id:', excl)


def is_garbled_table(c):
    if c['content_type'] != 'table':
        return False
    t = c['text']
    if '(cid:' in t:
        return True
    letters = len(RE_LETTER.findall(t))
    return letters >= 20 and len(RE_HANGUL.findall(t)) / letters < 0.3


kept = 0
removed = Counter()
rm_docs = Counter()
with open('out/chunks_all.jsonl', encoding='utf-8') as fin, \
     open('out/chunks_clean.jsonl', 'w', encoding='utf-8') as fout:
    for line in fin:
        c = json.loads(line)
        doc = c['chunk_id'].split('#')[0]
        if doc in excl:
            removed['제외 문서']; removed['제외 문서'] += 1
            rm_docs[c['doc_name'][:28]] += 1
            continue
        if len(c['text'].strip()) < 20:
            removed['초미세 조각(<20자)'] += 1
            continue
        if is_garbled_table(c):
            removed['깨진 표(cid/한글비율)'] += 1
            rm_docs[c['doc_name'][:28]] += 1
            continue
        fout.write(line)
        kept += 1

print(f'유지 {kept} / 제거 {sum(removed.values())}')
for k, v in removed.items():
    print(f'  {k}: {v}개')
for name, n in rm_docs.most_common(8):
    print(f'    - {name} ({n})')