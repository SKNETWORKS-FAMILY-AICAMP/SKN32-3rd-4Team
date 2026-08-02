
# -*- coding: utf-8 -*-
"""
batch_runner.py — documents.csv 기반 400건(main+coverage_rider) 일괄 전처리 러너.

기능
  · documents.csv 읽기 → 처리대상(category ∈ {main, coverage_rider}) 필터
  · 삼성화재 분권(file1/2/3)을 같은 product_code 로 묶어 1문서로 병합 처리
  · 문서별 process_document() 호출 → chunks_all.jsonl 적재
  · 문서별 품질지표 리포트(quality_report.csv)
  · 임계 미달 실패 목록(failures.csv) 별도 산출

사용법 (Windows PowerShell / PyCharm 터미널)
  python batch_runner.py --csv documents.csv --pdfdir raw\insurance_terms --out out

컬럼명은 documents.csv 스키마 변형을 흡수하도록 후보군에서 자동 매핑한다.
"""
import argparse
import csv
import json
import os
import re
import sys
import traceback
from collections import defaultdict

from doc_processor import process_document

# ── documents.csv 컬럼 자동 매핑 후보 ──────────────────────────────
COLS = {
    'doc_id':      ['doc_id', 'id', 'sha256', 'hash'],
    'insurer':     ['insurer', 'company', '보험사'],
    'generation':  ['generation', 'gen', '세대'],
    'category':    ['category', 'cat', '분류'],
    'product_code':['product_code', 'code', '상품코드'],
    'product_name':['product_name', 'name', 'doc_name', '상품명'],
    'saved_as':    ['saved_as', 'file', 'filename', 'path', 'saved_path'],
}
PROCESS_CATS = {'main', 'coverage_rider'}
# 임계값 (미달 시 실패로 분류 — 재검토 대상)
MIN_CLAUSES = 5
MIN_COVERAGE = 40.0


def _pick(row, keys):
    for k in keys:
        for rk in row:
            if rk.strip().lower() == k.lower() and row[rk].strip():
                return row[rk].strip()
    return ''


def load_documents(csv_path):
    with open(csv_path, encoding='utf-8-sig', newline='') as f:
        rows = list(csv.DictReader(f))
    docs = []
    for r in rows:
        rec = {k: _pick(r, cands) for k, cands in COLS.items()}
        rec['category'] = (rec['category'] or 'main').lower()
        docs.append(rec)
    return docs


def resolve_path(pdfdir, saved_as):
    """saved_as 가 상대/절대/파일명뿐이든 실제 경로로 해석."""
    if os.path.isabs(saved_as) and os.path.exists(saved_as):
        return saved_as
    cand = os.path.join(pdfdir, saved_as)
    if os.path.exists(cand):
        return cand
    base = os.path.basename(saved_as)
    for root, _, files in os.walk(pdfdir):
        if base in files:
            return os.path.join(root, base)
    return None


def group_samsung_split(targets):
    """삼성화재 file1/2/3 을 product_code 로 묶음. 반환: [(대표rec, [경로...])]."""
    groups = defaultdict(list)
    singles = []
    for rec, path in targets:
        is_samsung = ('삼성' in rec['insurer']) or ('samsung' in rec['insurer'].lower())
        code = rec['product_code']
        if is_samsung and code and ('_file' in os.path.basename(path).lower()
                                    or 'file1' in os.path.basename(path).lower()):
            groups[code].append((rec, path))
        else:
            singles.append((rec, [path]))
    merged = []
    for code, items in groups.items():
        items.sort(key=lambda x: x[1])          # file1,file2,file3 순
        rep = items[0][0]
        merged.append((rep, [p for _, p in items]))
    return merged + singles


def process_group(rep, paths, with_tables=False):
    """분권 그룹을 1문서로 처리(페이지 이어붙이기 방식)."""
    meta = dict(
        doc_id=rep['doc_id'] or rep['product_code'] or os.path.basename(paths[0]),
        doc_name=rep['product_name'] or os.path.basename(paths[0]),
        insurer=rep['insurer'] or 'unknown',
        generation=rep['generation'] or 'unknown',
        part=rep['category'],
    )
    if len(paths) == 1:
        return process_document(paths[0], meta, with_tables=with_tables)
    # 분권: 각 파일 처리 후 청크·지표 합산
    all_chunks, qs = [], []
    for p in paths:
        c, q = process_document(p, meta, with_tables=with_tables)
        all_chunks.extend(c); qs.append(q)
    # 파일마다 순번이 1부터 다시 매겨져 chunk_id가 충돌 → 병합 후 전체 재부여
    for i, ch in enumerate(all_chunks, 1):
        tail = ch['chunk_id'].split('::', 1)
        ch['chunk_id'] = f"{meta['doc_id']}#{i:05d}::" + (tail[1] if len(tail) > 1 else '')
    q = qs[0].copy()
    q['pages'] = sum(x['pages'] for x in qs)
    q['n_clauses'] = sum(x['n_clauses'] for x in qs)
    q['n_chunks'] = sum(x['n_chunks'] for x in qs)
    q['n_tables'] = sum(x.get('n_tables', 0) for x in qs)
    # 분권 병합: 단순 평균 대신 분량(페이지) 가중 평균 — 큰 권의 커버리지가 대표성 가짐
    tot_pg = sum(x['pages'] for x in qs) or 1
    q['coverage_pct'] = round(sum(x['coverage_pct'] * x['pages'] for x in qs) / tot_pg, 1)
    q['extract_mode'] = '+'.join(sorted(set(x['extract_mode'] for x in qs)))
    q['split_files'] = len(paths)
    return all_chunks, q


def is_failure(q):
    reasons = []
    if q.get('non_terms_doc'):
        reasons.append('비약관문서(사업방법서 등)')
    # 특약(coverage_rider)은 조항 수가 적은 게 정상 → 임계를 낮춤
    min_cl = 1 if q.get('category') == 'coverage_rider' else MIN_CLAUSES
    if q['n_clauses'] < min_cl:
        reasons.append(f"조항부족({q['n_clauses']}<{min_cl})")
    if q['coverage_pct'] < MIN_COVERAGE:
        reasons.append(f"커버리지미달({q['coverage_pct']}%<{MIN_COVERAGE}%)")
    return reasons


# 수동 다운로드 파일명 → 보험사 추론 키워드
INSURER_KEYS = [
    ('한화생명', ['한화생명', 'hanwhalife']),
    ('한화손해보험', ['한화손보', '한화손해', 'hanwhain']),
    ('메리츠화재', ['메리츠', 'meritz']),
    ('KB손해보험', ['kb손보', 'kb손해', 'kbinsure', 'kb_', 'kb손']),
    ('현대해상', ['현대해상', '현대', 'hyundai']),
    ('흥국화재', ['흥국화재', 'heungkukfire']),
    ('흥국생명', ['흥국생명', 'heungkuklife']),
    ('롯데손해보험', ['롯데', 'lotte']),
    ('삼성생명', ['삼성생명', 'samsunglife']),
    ('삼성화재', ['삼성화재', 'samsungfire']),
    ('DB손해보험', ['db손보', 'db손해', 'dbins', '동부화재']),
    ('NH농협생명', ['nh농협생명', 'nh생명', 'nhlife']),
    ('NH농협손해보험', ['nh손보', 'nh농협손해', 'nhfire']),
    ('동양생명', ['동양생명', 'tongyang']),
    ('교보생명', ['교보', 'kyobo']),
    ('신한라이프', ['신한', 'shinhan']),
]


def infer_meta_from_name(fname):
    """수동 파일명에서 보험사·세대 추론(크롤 데이터와 동일 방향의 메타)."""
    low = fname.lower()
    insurer = 'unknown'
    for name, keys in INSURER_KEYS:
        if any(k.lower() in low for k in keys):
            insurer = name; break
    m = re.search(r'([1-5])\s*세대', fname)
    generation = m.group(1) if m else 'unknown'
    return insurer, generation


def make_manual_targets(extradir):
    """수동 PDF 폴더 → [(rec, path)]. 카테고리는 main 기본, 메타는 파일명 추론."""
    out = []
    for root, _, files in os.walk(extradir):
        for fn in sorted(files):
            if not fn.lower().endswith('.pdf'):
                continue
            path = os.path.join(root, fn)
            insurer, gen = infer_meta_from_name(fn)
            stem = os.path.splitext(fn)[0]
            out.append((dict(
                doc_id='manual_' + stem[:40], insurer=insurer, generation=gen,
                category='main', product_code='', product_name=stem,
                saved_as=fn), path))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--csv', default='', help='documents.csv 경로(크롤 데이터)')
    ap.add_argument('--pdfdir', default='', help='크롤 PDF 루트 폴더')
    ap.add_argument('--extradir', default='', help='수동 다운로드 PDF 폴더(추가 처리)')
    ap.add_argument('--out', default='out', help='출력 폴더')
    ap.add_argument('--limit', type=int, default=0, help='디버그용 처리 건수 제한')
    ap.add_argument('--tables', action='store_true',
                    help='pdfplumber 표 추출까지 포함(느림, 표 청크 병합)')
    args = ap.parse_args()
    if not args.csv and not args.extradir:
        ap.error('--csv 또는 --extradir 중 최소 하나는 필요합니다.')

    os.makedirs(args.out, exist_ok=True)
    targets = []
    missing = []
    if args.csv:
        docs = load_documents(args.csv)
        for rec in docs:
            if rec['category'] not in PROCESS_CATS:
                continue
            p = resolve_path(args.pdfdir, rec['saved_as'])
            if not p:
                missing.append(rec); continue
            targets.append((rec, p))
    n_crawl = len(targets)
    n_manual = 0
    if args.extradir:
        manual = make_manual_targets(args.extradir)
        n_manual = len(manual)
        targets.extend(manual)
    if args.limit:
        targets = targets[:args.limit]

    groups = group_samsung_split(targets)
    print(f"[i] 크롤 {n_crawl}건 + 수동 {n_manual}건 = 처리대상 {len(targets)}건 "
          f"→ 병합 후 {len(groups)}문서 (파일없음 {len(missing)}건)")

    chunk_fp = open(os.path.join(args.out, 'chunks_all.jsonl'), 'w', encoding='utf-8')
    qreport, failures, errors = [], [], []
    for i, (rep, paths) in enumerate(groups, 1):
        try:
            chunks, q = process_group(rep, paths, with_tables=args.tables)
            for c in chunks:
                chunk_fp.write(json.dumps(c, ensure_ascii=False) + '\n')
            reasons = is_failure(q)
            q['status'] = 'FAIL' if reasons else 'OK'
            q['fail_reason'] = '; '.join(reasons)
            qreport.append(q)
            if reasons:
                failures.append(q)
        except Exception as e:
            errors.append(dict(doc=os.path.basename(paths[0]), error=repr(e)))
            traceback.print_exc()
        if i % 25 == 0:
            print(f"    ...{i}/{len(groups)}")
    chunk_fp.close()

    # 리포트 저장
    _write_csv(os.path.join(args.out, 'quality_report.csv'), qreport)
    _write_csv(os.path.join(args.out, 'failures.csv'), failures)
    _write_csv(os.path.join(args.out, 'errors.csv'), errors)
    _write_csv(os.path.join(args.out, 'missing_files.csv'), missing)

    total_chunks = sum(q['n_chunks'] for q in qreport)
    print("\n=== 배치 완료 ===")
    print(f" 문서 {len(qreport)}  |  OK {len(qreport)-len(failures)}  "
          f"FAIL {len(failures)}  ERROR {len(errors)}")
    print(f" 총 청크 {total_chunks}  → {args.out}/chunks_all.jsonl")
    print(f" 품질리포트 {args.out}/quality_report.csv, 실패목록 failures.csv")


def _write_csv(path, rows):
    if not rows:
        open(path, 'w', encoding='utf-8-sig').close()
        return
    # 행마다 키가 다를 수 있으므로(예: 분권 병합 문서의 split_files) 전체 키의 합집합 사용
    keys, seen = [], set()
    for r in rows:
        for k in r:
            if k not in seen:
                seen.add(k); keys.append(k)
    with open(path, 'w', encoding='utf-8-sig', newline='') as f:
        w = csv.DictWriter(f, fieldnames=keys, restval='', extrasaction='ignore')
        w.writeheader()
        for r in rows:
            w.writerow(r)


if __name__ == '__main__':
    main()