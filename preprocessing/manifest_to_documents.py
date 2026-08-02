# -*- coding: utf-8 -*-
"""
manifest_to_documents.py — 팀원 보강 매니페스트(보험사별 *.jsonl) → documents_manifest.csv

파일명 추론(build_documents.py)을 대체하는 정본 생성기.
  · 세대: 검수된 generation_label 사용 ('2세대 (표준화)' → '2세대').
    generation 없음/ambiguous 도 절대 누락하지 않음 → generation='unknown'
    (5세대일 수 있음 — 팀 지침)
  · sale_end '99991231' 은 센티널(현행 판매중) — 값 그대로 보존
  · category:
      excluded_reason 비의료실손/여행실손 → 'excluded' (RAG 코퍼스 제외, 행은 보존)
      doc_type 사업방법서(또는 excluded_reason 사업방법서) → 'aux'
      doc_type 약관 → '특약' 포함 시 'coverage_rider', 아니면 'main'
  · sha256 중복은 첫 레코드만(중복 카운트 기록)

사용:
  python manifest_to_documents.py --manifestdir raw\\manifests --out documents_manifest.csv
  (manifestdir 안의 *.jsonl 전부 읽음 — merged/migrated 구본은 넣지 말 것)
"""
import argparse
import csv
import glob
import json
import os
import re
from collections import Counter

COLUMNS = ['sha256_12', 'file', 'insurer', 'product_code', 'product_name',
           'sale_start', 'sale_end', 'generation', 'category', 'doc_type',
           'product_line', 'generation_confidence', 'excluded_reason',
           'dup_count', 'all_product_codes']

INSURER_NORM = {'samsunglife': '삼성생명'}


def gen_of(rec):
    lbl = (rec.get('generation_label') or '').strip()
    if lbl:
        m = re.match(r'(\d)\s*세대', lbl)
        if m:
            return f"{m.group(1)}세대"
    g = rec.get('generation')
    if isinstance(g, int) or (isinstance(g, str) and g.isdigit()):
        return f"{g}세대"
    return 'unknown'          # ambiguous/null 포함 — 누락 금지(5세대 가능)


def cat_of(rec):
    excl = (rec.get('excluded_reason') or '').strip()
    if excl in ('비의료실손', '여행실손'):
        return 'excluded'
    dt = (rec.get('doc_type') or '').strip()
    if dt == '사업방법서' or excl == '사업방법서':
        return 'aux'
    name = (rec.get('product_name') or '') + (rec.get('saved_as') or '')
    if dt == '약관' or rec.get('filename_kind_hint') == 'policy_terms':
        return 'coverage_rider' if '특약' in name.replace(' ', '') else 'main'
    return 'aux'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--manifestdir', required=True)
    ap.add_argument('--out', default='documents_manifest.csv')
    args = ap.parse_args()

    files = sorted(glob.glob(os.path.join(args.manifestdir, '*.jsonl')))
    if not files:
        raise SystemExit(f'매니페스트 없음: {args.manifestdir}')
    print('매니페스트 파일:', len(files))

    seen = {}
    dup = 0
    order = []
    for fp in files:
        with open(fp, encoding='utf-8') as f:
            for ln in f:
                ln = ln.strip()
                if not ln:
                    continue
                try:
                    rec = json.loads(ln)
                except Exception:
                    continue
                sha = rec.get('sha256') or ''
                if not sha:
                    continue
                if sha in seen:
                    dup += 1
                    # 보강 정보가 더 많은 레코드로 갱신(세대 라벨 있는 쪽 우선)
                    if rec.get('generation_label') and not seen[sha].get('generation_label'):
                        seen[sha] = rec
                    continue
                seen[sha] = rec
                order.append(sha)

    rows = []
    stats = Counter()
    by_ins = {}
    for sha in order:
        rec = seen[sha]
        ins = (rec.get('insurer') or '?').strip()
        ins = INSURER_NORM.get(ins, ins)
        saved = (rec.get('saved_as') or '').replace('\\', '/')
        rel = saved.split('insurance_terms/', 1)[-1] if 'insurance_terms/' in saved \
            else os.path.basename(saved)
        cat = cat_of(rec)
        gen = gen_of(rec)
        rows.append({
            'sha256_12': sha[:12], 'file': rel, 'insurer': ins,
            'product_code': (rec.get('product_code') or sha[:12]),
            'product_name': (rec.get('product_name') or os.path.basename(rel))[:100],
            'sale_start': rec.get('sale_start') or '',
            'sale_end': rec.get('sale_end') or '',
            'generation': gen, 'category': cat,
            'doc_type': rec.get('doc_type') or '',
            'product_line': rec.get('product_line') or '',
            'generation_confidence': rec.get('generation_confidence') or '',
            'excluded_reason': rec.get('excluded_reason') or '',
            'dup_count': 1, 'all_product_codes': '',
        })
        stats[cat] += 1
        st = by_ins.setdefault(ins, Counter())
        st[cat] += 1
        if gen == 'unknown' and cat in ('main', 'coverage_rider'):
            st['gen_unknown'] += 1

    with open(args.out, 'w', encoding='utf-8-sig', newline='') as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS, restval='')
        w.writeheader()
        for r in rows:
            w.writerow(r)

    print(f'\n총 {len(rows)}행 저장 → {args.out}  (sha 중복 제외 {dup})')
    print('카테고리 합계:', dict(stats))
    print(f"\n{'보험사':14s} {'main':>5} {'rider':>6} {'aux':>4} {'excluded':>8} {'gen?':>5}")
    for ins, st in sorted(by_ins.items(), key=lambda x: -sum(v for k, v in x[1].items() if k != 'gen_unknown')):
        print(f"{ins:14s} {st.get('main',0):>5} {st.get('coverage_rider',0):>6} "
              f"{st.get('aux',0):>4} {st.get('excluded',0):>8} {st.get('gen_unknown',0):>5}")


if __name__ == '__main__':
    main()