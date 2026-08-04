# -*- coding: utf-8 -*-
"""전처리 v5 산출물 시각화 HTML 생성."""
import os, json, datetime
import pandas as pd

TAG = os.environ.get('VIZ_TAG', 's5')
import plotly.express as px
import plotly.graph_objects as go

df = pd.read_parquet(f'data/exports/{TAG}_documents.parquet')
ln = pd.read_parquet(f'data/exports/{TAG}_clause_lengths.parquet')['char_length']
kcd = pd.read_parquet('data/exports/kcd_chapter_kind.parquet')
mx = pd.read_parquet('data/exports/ref_matrix_top.parquet')
meta = json.load(open('data/exports/ref_matrix_meta.json', encoding='utf-8'))

figs = []
C = {'ok': '#3d8bfd', 'suspect': '#e8a05a', 'no_clause_heads': '#d9534f'}

# A
fA = px.scatter(df, x='pages', y='clauses', color='parse_status', color_discrete_map=C,
                hover_data=['sha12', 'insurer', 'generation', 'numbering',
                            'clauses_per_page', 'max_clause_len', 'product'],
                labels={'pages': '본문 쪽수', 'clauses': '조항 수', 'parse_status': '파싱 상태'},
                opacity=.72)
for r, nm in ((0.3, '조항/쪽 0.3'), (2.0, '조항/쪽 2.0')):
    xm = df.pages.max()
    fA.add_scatter(x=[0, xm], y=[0, r * xm], mode='lines',
                   line=dict(dash='dot', width=1, color='#999'), name=nm, hoverinfo='skip')
fA.update_layout(height=540, title='A. 문서별 쪽수 × 조항 수 — 선 아래는 조항이 너무 적은 문서')
figs.append(fA)

# D1 / D2
piv = df.pivot_table(index='insurer', columns='generation', values='sha12', aggfunc='count').fillna(0)
f = px.imshow(piv, text_auto=True, aspect='auto', color_continuous_scale='Blues', labels=dict(color='문서 수'))
f.update_layout(height=420, title='D-1. 보험사 × 세대 — 문서 수 (코퍼스 편중)')
figs.append(f)

df['bad'] = (df.parse_status != 'ok').astype(int)
piv2 = (df.pivot_table(index='insurer', columns='generation', values='bad', aggfunc='mean') * 100).round(1)
f = px.imshow(piv2, text_auto=True, aspect='auto', color_continuous_scale='Oranges', labels=dict(color='% 불량'))
f.update_layout(height=420, title='D-2. 보험사 × 세대 — parse_status ≠ ok 비율(%) (파서 편향)')
figs.append(f)

# Pareto
df['burden'] = df.ambiguous + df.unresolved + df.bad * 50
top = df.nlargest(40, 'burden')
p = top[['sha12', 'ambiguous', 'unresolved']].copy()
p['cum'] = (top.burden.cumsum() / df.burden.sum() * 100).round(1).values
f = go.Figure()
f.add_bar(x=p.sha12, y=p.ambiguous, name='모호 조항', marker_color='#e8a05a')
f.add_bar(x=p.sha12, y=p.unresolved, name='미해결 항', marker_color='#d9534f')
f.add_scatter(x=p.sha12, y=p.cum, name='누적 비중(%)', yaxis='y2', mode='lines+markers',
              line=dict(color='#0b5fa5'))
f.update_layout(barmode='stack', height=500,
                yaxis2=dict(overlaying='y', side='right', range=[0, 100], title='누적 %'),
                xaxis_tickangle=-60,
                title='Pareto. 오류 부담 상위 40문서 = 전체의 %s%% — 평평하다(소수 문서 수정으로 끝나지 않는다)' % p.cum.iloc[-1])
figs.append(f)

# B
f = px.histogram(ln[ln > 0], log_x=True, nbins=90,
                 labels={'value': '조항 길이(자, 로그)'}, color_discrete_sequence=['#3d8bfd'])
f.add_vline(x=30000, line_dash='dash', line_color='#d9534f', annotation_text='suspect 임계 30,000자')
q = ln.quantile([.5, .95, .99]).astype(int)
for v, c in ((q[.5], '중앙'), (q[.95], 'p95'), (q[.99], 'p99')):
    f.add_vline(x=v, line_dash='dot', line_color='#888', annotation_text='%s %s' % (c, format(v, ',')))
f.update_layout(height=450, showlegend=False,
                title='B. 조항 길이 분포 (n=%s) — 30,000자 초과 %s건 (%.2f%%)'
                      % (format(len(ln), ','), format(int((ln > 30000).sum()), ','), (ln > 30000).mean() * 100))
figs.append(f)

# E
kp = kcd.pivot_table(index='chapter', columns='kind', values='n', aggfunc='sum').fillna(0)
kp = kp.reindex(columns=[c for c in ['exclude', 'exception', 'mention'] if c in kp.columns])
kp = kp.loc[kp.sum(1).sort_values().index]
f = px.imshow(kp, text_auto='.0f', aspect='auto', color_continuous_scale='Reds', labels=dict(color='언급 수'))
f.update_layout(height=620,
                title='E. 약관이 직접 쓴 KCD 범위 — 질병 장(章) × 성격 (총 %s건)' % format(int(kcd.n.sum()), ','))
figs.append(f)

# F
f = px.scatter(mx, x='target_no', y='section', size='refs', color='dup',
               color_continuous_scale='Turbo', size_max=26,
               labels={'target_no': '참조된 조 번호', 'section': '참조를 한 부(部)',
                       'dup': '문서 내 같은 번호 개수', 'refs': '참조 횟수'},
               hover_data=['refs', 'dup'])
f.update_layout(height=560,
                title='F. 준용 모호 최다 문서 <b>%s</b>(%s) — 참조 %s건 중 %s건(%.0f%%)이 모호'
                      '<br><sub>색 = 그 조 번호를 가진 조항이 문서 안에 몇 개인가. '
                      '1이면 특정 가능, 2 이상이면 특정 불가, 0이면 문서 밖</sub>'
                      % (meta['sha12'], meta['insurer'], format(meta['tot'], ','),
                         format(meta['amb'], ','), meta['amb'] / meta['tot'] * 100))
figs.append(f)

parts = [fg.to_html(full_html=False,
                    include_plotlyjs='inline' if i == 0 else False,
                    config={'displaylogo': False}) for i, fg in enumerate(figs)]

built = datetime.datetime.now().strftime('%Y-%m-%d %H:%M')
STYLE = """<style>body{margin:0;padding:1.5rem 1.2rem 4rem;font:15px/1.7 -apple-system,"Segoe UI","Malgun Gothic",sans-serif;background:#fff;color:#1a1a1a}
main{max-width:1180px;margin:0 auto} h1{font-size:1.6rem;margin:0 0 .3rem}
h2{font-size:1.2rem;margin:2.5rem 0 .6rem;border-bottom:2px solid #e2e2e2;padding-bottom:.3rem}
.sub{color:#666;margin:0 0 1.2rem} table{border-collapse:collapse;width:100%;font-size:.9rem;margin:.6rem 0}
th,td{border:1px solid #e2e2e2;padding:.45rem .6rem;text-align:left} th{background:#fafafa}
td.n,th.n{text-align:right;font-variant-numeric:tabular-nums}
.box{border:1px solid #e2e2e2;border-left:4px solid #0b5fa5;background:#fafafa;padding:.7rem 1rem;margin:1rem 0;font-size:.92rem;border-radius:0 6px 6px 0}
.box.w{border-left-color:#a54b0b} .box b{display:block;margin-bottom:.25rem}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:.6rem;margin:1rem 0}
.stat{border:1px solid #e2e2e2;border-radius:6px;padding:.6rem .8rem;background:#fafafa}
.stat .v{font-size:1.4rem;font-weight:600} .stat .l{color:#666;font-size:.78rem}
code{background:#f0f0f0;padding:.1rem .3rem;border-radius:3px;font:12.5px ui-monospace,Consolas,monospace}</style>"""

head = ('<meta charset="utf-8"><title>전처리 v5 산출물 시각화</title>' + STYLE +
        '<main><h1>전처리 v5 산출물 시각화</h1>'
        '<p class="sub">생성 %s · 스키마 <code>s5</code> · 추출기 <code>pymupdf/1.28.0</code> · 문서 %s · 조항 %s</p>'
        '<div class="grid">'
        '<div class="stat"><div class="v">%s</div><div class="l">parse ok</div></div>'
        '<div class="stat"><div class="v">%s</div><div class="l">suspect</div></div>'
        '<div class="stat"><div class="v">%s</div><div class="l">인용 모호 조항</div></div>'
        '<div class="stat"><div class="v">%s</div><div class="l">번호 못읽은 항</div></div>'
        '<div class="stat"><div class="v">%s</div><div class="l">법령 원문 조항</div></div>'
        '<div class="stat"><div class="v">%s</div><div class="l">KCD 범위 언급</div></div>'
        '</div>'
        '<div class="box w"><b>★수치 스냅샷 주의</b>'
        '<b>2026-08-02 15:50~15:52 재생성 s5</b> 기준이다. <code>CLAUDE.md</code>·일부 리포트에는 '
        '이전 값(<code>ok 1,108 / suspect 250</code>)이 남아 있다. 시점이 다른 숫자를 섞지 말 것.</div>'
        '<div class="box"><b>무엇을 넣고 무엇을 뺐나</b>'
        '코덱스와 순위를 합의해 <b>보면 뭔가를 고치게 되는 것</b>만 넣었다. '
        '<b>2D 임베딩 투영(t-SNE·PCA)은 일부러 뺐다</b> — 왜곡이 크고 중복 조항 65%%에 그림이 지배돼 '
        '검색 실패 원인을 설명하지 못한다. 대신 k-NN 이웃 혼합률·Recall@k 실패 슬라이스를 봐야 한다.</div>'
        % (built, format(len(df), ','), format(len(ln), ','),
           format(int((df.parse_status == 'ok').sum()), ','),
           format(int((df.parse_status == 'suspect').sum()), ','),
           format(int(df.ambiguous.sum()), ','), format(int(df.unresolved.sum()), ','),
           format(int(df.statute.sum()), ','), format(int(kcd.n.sum()), ',')))


# ★스키마 태그를 완성된 문자열에서 바꾼다. 포맷 문자열을 건드리면 % 이스케이프가 깨진다.
if TAG != 's5':
    head = (head
            .replace('전처리 v5 산출물', f'전처리 {TAG} 산출물')
            .replace('<code>s5</code>', f'<code>{TAG}</code>')
            .replace('<b>2026-08-02 15:50~15:52 재생성 s5</b> 기준이다. '
                     '<code>CLAUDE.md</code>·일부 리포트에는 '
                     '이전 값(<code>ok 1,108 / suspect 250</code>)이 남아 있다. '
                     '시점이 다른 숫자를 섞지 말 것.',
                     f'<b>{TAG} 재추출 완료본</b> 기준이다({built}). '
                     f'<code>CLAUDE.md</code>·기존 리포트·이전 판 시각화에는 '
                     f'<b>s5 기준 수치</b>가 남아 있다. 시점이 다른 숫자를 섞지 말 것.'))

dbtab = """<h2>G. 전처리 → DB 적재 정합성</h2>
<div class="box w"><b>분모가 다른 것을 한 퍼널로 합치지 않는다</b>
조항(수록)·고유 내용·청크는 서로 다른 단위다. 하나로 이으면 "몇 % 적재됨"이 잘못 계산된다.</div>
<table><tr><th>단위</th><th class="n">전처리 산출</th><th class="n">DB 적재</th><th class="n">차이</th><th>비고</th></tr>
<tr><td>조항(수록) <code>policy_clause_occurrence</code></td><td class="n">211,131</td><td class="n">156,946</td><td class="n">-54,185</td><td>약관 177,436 + 법령 33,257 + fallback 438</td></tr>
<tr><td>고유 내용 <code>policy_clause_content</code></td><td class="n">63,963</td><td class="n">2,221</td><td class="n">-61,742</td><td>약관 조항 기준 고유 <code>content_hash</code></td></tr>
<tr><td>청크 <code>policy_clause_chunk</code></td><td class="n">(미산출)</td><td class="n">6,208</td><td class="n">—</td><td>권고안 추산 154,874 (항 경계 정렬 900자)</td></tr>
<tr><td><code>rag_chunks</code></td><td class="n">—</td><td class="n">0</td><td class="n">—</td><td>비어 있음</td></tr></table>
<div class="box"><b>읽는 법</b>
적재가 <b>중간 상태</b>다. 수록은 74% 들어갔는데 고유 내용은 3.5%뿐이다.
정상 순서라면 내용이 먼저 차야 한다 — 적재 스크립트의 순서·중단 지점을 확인해야 한다.
측정 시각 기준이며 다른 세션이 적재 중이면 값이 바뀐다.</div>"""

tail = dbtab + """<div class="box"><b>원자료를 직접 보려면</b>
집계는 이 문서로, 행 단위 탐색은 <b>Parquet + Tad</b>(MIT · DuckDB 기반)로 나눴다.
수십만 행을 단일 HTML에 넣으면 파일 크기와 브라우저 메모리가 문제가 된다.
<code>data/exports/s5_clauses.parquet</code> (211,131행 · 83MB) ·
<code>s5_documents.parquet</code> · <code>s5_clause_lengths.parquet</code></div></main>"""

#: ★꼬리말·DB표도 스키마를 따라가야 한다. 예전엔 여기만 `s5` 로 굳어 있어
#:   s6 페이지가 **s5 parquet 을 가리키고** 조항 수도 s5 값(211,131)을 보여줬다.
if TAG != 's5':
    tail = (tail
            .replace('data/exports/s5_clauses.parquet',
                     'data/exports/%s_clauses.parquet' % TAG)
            .replace('<code>s5_documents.parquet</code>',
                     '<code>%s_documents.parquet</code>' % TAG)
            .replace('<code>s5_clause_lengths.parquet</code>',
                     '<code>%s_clause_lengths.parquet</code>' % TAG)
            .replace('(211,131행 · 83MB)', '(%s행)' % format(len(ln), ','))
            .replace('<td class="n">211,131</td>',
                     '<td class="n">%s</td>' % format(len(ln), ','))
            .replace('측정 시각 기준이며 다른 세션이 적재 중이면 값이 바뀐다.',
                     '★<b>왼쪽(전처리 산출)은 %s 실측, 오른쪽(DB 적재)은 s5 시절 적재 결과</b>다. '
                     '서로 다른 판을 나란히 둔 것이므로 차이 열을 "누락"으로 읽으면 안 된다. '
                     '적재를 다시 돌린 뒤 같은 판으로 재측정해야 한다.' % TAG))

#: ★H 절(Tad 행 단위 캡처)은 GUI 로만 만들 수 있어 재생성에서 살아남지 못했다.
#:   자산 파일로 떼어 두고 여기서 이어 붙인다 — 없으면 없다고 적는다(조용히 빠지지 않게).
_tad = os.path.join('docs', 'handoff', '_viz_tad_section.html')
if os.path.exists(_tad):
    tail = tail.replace('</main>', open(_tad, encoding='utf-8').read() + '</main>')
else:
    tail = tail.replace('</main>',
        '<h2>H. 행 단위 캡처</h2><div class="box w">'
        '<b>캡처 자산이 없다</b> — <code>docs/handoff/_viz_tad_section.html</code> 이 없어 '
        '이 절을 싣지 못했다. 빠진 것을 조용히 넘기지 않으려고 이 문단을 남긴다.</div></main>')

out = 'docs/handoff/preprocess_viz.html'
open(out, 'w', encoding='utf-8').write(head + '\n'.join(parts) + tail)
print('작성 완료: %s  %d KB · 그림 %d장 + DB표' % (out, os.path.getsize(out) // 1024, len(figs)))
