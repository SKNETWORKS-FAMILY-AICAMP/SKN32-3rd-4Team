/* 올바른 보험비서 — 사람 화면.
 *
 * ★이 화면은 **판정하지 않는다.** 서버가 돌려준 것을 그대로 그린다.
 *   화면에서 조건을 하나라도 해석하면 규칙엔진과 두 벌이 되고 반드시 어긋난다.
 *
 * ★기권을 실패처럼 그리지 않는다.
 *   `verdict="needs_expert"` 는 정상 결과이고 HTTP 200 이다.
 *   빨간 오류 화면으로 그리면 사용자가 "고장났다"로 읽는다.
 *
 * ★경고를 접지 않는다. `warnings[]` 는 항상 펼쳐서 보인다.
 */
'use strict';

const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? '').replace(/[&<>"]/g, (c) =>
  ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));

//: 서버 enum → 사람 말. ★네 단계를 셋으로 줄이지 않는다.
const VERDICT_KO = {
  likely_covered: ['보장 가능', 'ok'],
  needs_documents: ['조건부 확인 필요', 'warn'],
  unlikely: ['면책 가능성', 'danger'],
  needs_expert: ['전문가 확인 필요', 'warn'],
};

async function api(path, opts) {
  const res = await fetch(path, opts);
  let body = null;
  try { body = await res.json(); } catch { /* 본문 없음 */ }
  return { status: res.status, body };
}

/* ── 컷① 지원범위 ─────────────────────────────────────────────── */

async function loadScope() {
  const { status, body } = await api('/v1/support-manifest');
  const el = $('scopeBody');
  if (status !== 200 || !body) {
    //: ★못 불러온 것을 "지원 안 함"으로 그리지 않는다. 다른 사실이다.
    el.innerHTML = `<div class="banner danger">지원 범위를 불러오지 못했습니다 (HTTP ${status}).
      화면 문제이지 보장 여부와는 무관합니다.</div>`;
    return;
  }

  const insurers = Object.keys(body.insurers || {});
  $('insurers').innerHTML = insurers.map((n) => `<option value="${esc(n)}">`).join('');

  //: ★판정 가능 약관이 0건이면 그것을 **첫 화면에** 쓴다.
  const total = body.total_policy_versions || 0;
  const notes = (body.notes || []).map((n) => {
    const warn = n.startsWith('⚠');
    return `<div class="banner ${warn ? 'warn' : ''}" ${warn ? '' : 'style="background:transparent;border:0;padding:2px 0"'}>${esc(n)}</div>`;
  }).join('');

  el.innerHTML = `
    <div class="${total === 0 ? 'banner danger' : ''}">
      <strong>판정 가능 약관 ${total.toLocaleString()}건</strong>
      · 보험사 ${insurers.length}곳
      ${total === 0 ? '<br>수집은 끝났지만 사람이 문서를 확정하는 절차가 남아 지금은 판정할 수 없습니다.' : ''}
    </div>
    ${insurers.map((n) => `<span class="chip">${esc(n)} ${body.insurers[n].versions}</span>`).join('')}
    <div style="margin-top:10px">${notes}</div>
    <div class="small muted" style="margin-top:8px">
      규칙엔진 ${esc(body.rule_engine_version || '')} ·
      확정 문서만 사용: ${body.require_confirmed_documents ? '예' : '<strong>아니오(시연 모드)</strong>'}
    </div>`;
}

/* ── 컷②~⑦ 판정 ──────────────────────────────────────────────── */

function renderCitations(cites) {
  if (!cites || !cites.length) return '';
  return `<h2 style="margin-top:18px">근거 조항</h2>` + cites.map((c) => `
    <div class="cite">
      <div><strong>${esc(c.title || c.qualified_no)}</strong></div>
      <div class="quote">${esc(c.quote || '')}</div>
      <div class="loc">${esc(c.clause_id)} · ${esc(c.section || '')} p${c.page_from}${c.page_to && c.page_to !== c.page_from ? '–' + c.page_to : ''}</div>
    </div>`).join('');
}

function renderResult(status, b) {
  const out = $('result');

  if (status === 422) {
    out.innerHTML = `<div class="card"><div class="banner warn">입력을 확인해 주세요 —
      ${esc(b?.detail || '형식이 올바르지 않습니다.')}</div></div>`;
    return;
  }
  if (status === 503) {
    //: ★이때만 "우리 잘못"이다. 기권과 섞으면 안 된다.
    out.innerHTML = `<div class="card"><div class="banner danger">
      일시적으로 조회할 수 없습니다 — ${esc(b?.detail || '')}<br>
      <span class="small">보장 여부를 판단한 것이 아닙니다. 잠시 후 다시 시도해 주세요.</span></div></div>`;
    return;
  }
  if (status !== 200 || !b) {
    out.innerHTML = `<div class="card"><div class="banner danger">예상하지 못한 응답입니다 (HTTP ${status}).</div></div>`;
    return;
  }

  const [label, tone] = VERDICT_KO[b.verdict] || [b.verdict, 'warn'];
  const p = b.applied_policy;

  out.innerHTML = `
    <section class="card">
      <div class="verdict">${esc(label)}</div>
      <div class="banner ${tone}">${esc(b.message || '')}</div>

      ${b.abstained ? `<p class="small muted">
        ★근거 조항을 대지 못해 판정하지 않았습니다. <strong>오류가 아닙니다</strong> —
        추측으로 "보장됩니다"라고 말하지 않기 위한 정상 동작입니다.</p>` : ''}

      ${(b.warnings || []).length ? `<div class="banner warn">
        ${b.warnings.map((w) => `<div>⚠ ${esc(w)}</div>`).join('')}</div>` : ''}

      ${p ? `<h2 style="margin-top:16px">어느 약관으로 봤나</h2>
      <dl class="kv">
        <dt>보험사</dt><dd>${esc(p.insurer)}</dd>
        <dt>상품</dt><dd>${esc(p.product_name)}</dd>
        <dt>판매기간</dt><dd>${esc(p.sale_start)} ~ ${esc(p.sale_end || '')}</dd>
        <dt>세대</dt><dd>${esc(p.generation_label || p.generation || '미확정')}</dd>
        <dt>날짜 신뢰도</dt><dd>${esc(p.date_confidence)}</dd>
        <dt>추출 상태</dt><dd>${esc(p.parse_status)}</dd>
      </dl>` : ''}

      ${(b.candidates || []).length ? `<h2 style="margin-top:16px">후보 약관</h2>
        <div class="small muted">어느 것인지 특정하지 못했습니다.
          ★<strong>고르지 않으면 판정하지 않습니다</strong> — 아무거나 골라 답하면
          다른 약관의 조항을 근거로 대게 됩니다.</div>
        <div style="margin-top:8px">
        ${b.candidates.map((c, i) => `<button class="chip-btn cand" data-i="${i}"
            data-name="${esc(c.product_name)}">${esc(c.product_name)} ·
            ${esc(c.sale_start)}${c.generation_label ? ' · ' + esc(c.generation_label) : ''}</button>`).join('')}
        </div>` : ''}

      ${(b.per_code || []).length ? `<h2 style="margin-top:16px">질병기호별</h2>
        ${b.per_code.map((a) => {
          const [l] = VERDICT_KO[a.verdict] || [a.verdict];
          return `<div class="cite"><strong>${esc(a.code)}</strong> — ${esc(l)}
            <div class="small muted">${esc(a.note || a.reason_code || '')}</div></div>`;
        }).join('')}` : ''}

      ${renderCitations(b.citations)}

      <div class="small muted" style="margin-top:16px">
        규칙엔진 ${esc(b.rule_engine_version || '')} · 추출 ${esc(b.extractor || '')} ·
        추적 ${esc(b.trace_id || '')}
      </div>
    </section>`;
}

/* ── 컷③ 되묻기 ──────────────────────────────────────────────────
 * ★후보를 고르면 **그 상품명을 실어 다시 판정한다.**
 *   화면이 후보 중 하나를 임의로 고르지 않는다 — 고르는 것은 사용자다.
 *   임의로 고르면 다른 약관의 조항을 근거로 대게 된다.
 */
function bindCandidates() {
  document.querySelectorAll('.cand').forEach((b) =>
    b.addEventListener('click', () => runPrecheck(b.dataset.name)));
}

async function runPrecheck(productName) {
  const codes = $('codes').value.split(',').map((s) => s.trim()).filter(Boolean);
  $('status').textContent = '판정 중…';
  $('go').disabled = true;

  const { status, body } = await api('/v1/prechecks', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      insurer: $('insurer').value.trim(),
      enrolled_on: $('enrolled').value.trim(),
      kcd_codes: codes,
      //: ★사용자가 후보를 고른 경우에만 실린다. 화면이 지어내지 않는다.
      ...(productName ? { product_name: productName } : {}),
    }),
  });

  $('status').textContent = '';
  $('go').disabled = !$('consent').checked;
  renderResult(status, body);
  bindCandidates();
  if (codes.length) loadCohorts(codes[0]);
}

/* ── 컷⑧ 코호트 — ★실제와 합성을 각각 제 구역에만 그린다 ────────── */

async function loadCohort(path, elId, isDemo) {
  const el = $(elId);
  const { status, body } = await api(path);
  if (status !== 200 || !body) {
    el.innerHTML += `<div class="banner danger small">조회하지 못했습니다 (HTTP ${status}).</div>`;
    return;
  }
  el.innerHTML = `
    <h2>${isDemo ? 'DEMO · 합성 데이터' : '실제 검증 데이터'}</h2>
    <div class="banner ${isDemo ? 'warn' : (body.n ? 'ok' : '')}"
         ${!isDemo && !body.n ? 'style="background:transparent;border:1px solid var(--line)"' : ''}>
      ${esc(body.headline || '')}
    </div>
    <dl class="kv">
      <dt>사례 수</dt><dd>${body.n}</dd>
      <dt>지급</dt><dd>${body.approved_n}</dd>
      <dt>부지급</dt><dd>${body.denied_n}</dd>
      <dt>최소 표본</dt><dd>${body.min_sample} ${body.min_sample_met ? '충족' : '미달'}</dd>
    </dl>
    ${body.approval_rate != null ? `<p class="small">관측 비율 ${(body.approval_rate * 100).toFixed(1)}%
      <strong>(95% 구간 ${(body.approval_ci[0] * 100).toFixed(0)}~${(body.approval_ci[1] * 100).toFixed(0)}%)</strong></p>`
      : `<p class="small muted">표본이 적어 비율을 계산하지 않았습니다.</p>`}
    ${(body.warnings || []).map((w) => `<div class="small muted">⚠ ${esc(w)}</div>`).join('')}
    <div class="small muted" style="margin-top:8px">data_source: <code>${esc(body.data_source)}</code></div>`;
}

function loadCohorts(code) {
  const q = `?code=${encodeURIComponent(code)}`;
  //: ★엔드포인트가 다르다. 한 응답을 나눠 그리지 않는다.
  loadCohort('/v1/cohorts' + q, 'cohortReal', false);
  loadCohort('/v1/demo/cohorts' + q, 'cohortDemo', true);
}

/* ── 용어 챗봇 ────────────────────────────────────────────────── */

/* ★대화창이 판정하지 않는다.
 *   서버가 `intent="precheck"` 를 주면 **답을 만들지 않고** 판정 양식으로 올려보낸다.
 *   화면에서 "아마 보장될 거예요" 같은 말을 한 마디라도 만들면
 *   약관버전 확정·인용검증·4단 판정을 통째로 우회한 답이 된다.
 */

function bubble(cls, html) {
  const d = document.createElement('div');
  d.className = 'msg ' + cls;
  d.innerHTML = html;
  const log = $('chatLog');
  log.appendChild(d);
  log.scrollTop = log.scrollHeight;
  return d;
}

async function sendChat(text) {
  const msg = (text ?? $('chatIn').value).trim();
  if (!msg) return;
  $('chatIn').value = '';
  bubble('me', esc(msg));
  const thinking = bubble('bot muted', '약관에서 찾는 중…');

  const { status, body } = await api('/v1/chat', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message: msg }),
  });
  thinking.remove();

  if (status === 503) {
    bubble('bot', `<span style="color:var(--danger)">용어 색인을 사용할 수 없습니다 — ${esc(body?.detail || '')}</span>`);
    return;
  }
  if (status !== 200 || !body) {
    bubble('bot', `<span style="color:var(--danger)">응답을 받지 못했습니다 (HTTP ${status}).</span>`);
    return;
  }

  let html = esc(body.message).replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');

  if (body.found && body.quotes.length) {
    html += `<div class="small muted" style="margin-top:8px">정의 구절 ${body.total_passages}개 · 보험사 ${body.insurers.length}곳</div>`;
    html += body.quotes.map((q) => `
      <div class="cite">
        <div class="small muted">${esc(q.insurer)} · ${esc(q.title)}${q.kind === 'appendix' ? ' (붙임 정의표)' : ''}</div>
        <div class="quote">${esc(q.quote)}</div>
        <div class="loc">${esc(q.locator)}</div>
      </div>`).join('');
  }

  //: ★경고를 접지 않는다. 특히 "보장 여부는 판정하지 않습니다".
  if (body.warnings.length) {
    html += body.warnings.map((w) => `<div class="small muted" style="margin-top:6px">⚠ ${esc(w)}</div>`).join('');
  }
  bubble('bot', html);

  //: ★보장 질문이면 판정 양식으로 **올려보낸다.** 여기서 답하지 않는다.
  if (body.next_action === 'precheck_form') {
    document.getElementById('insurer').scrollIntoView({ behavior: 'smooth', block: 'center' });
    document.getElementById('insurer').focus();
  }
}

/* ── 컷⑨ 증빙 제출 ────────────────────────────────────────────── */

/* ★제출 결과를 "반영되었습니다"로 그리지 않는다.
 *   서버는 `verification="unverified"` 로 고정해 저장하고, 검증 전까지
 *   통계에 넣지 않는다. 화면이 그보다 강하게 말하면 거짓말이 된다.
 */
async function submitObservation() {
  const out = $('obOut');
  const insurer = $('obInsurer').value.trim();
  if (!insurer) {
    out.innerHTML = '<div class="banner warn small">보험사를 적어 주세요.</div>';
    return;
  }
  $('obGo').disabled = true;
  const { status, body } = await api('/v1/observations', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      client_ref: 'web-ui',
      insurer,
      enrolled_on: $('enrolled').value.trim(),
      kcd_codes: $('obCodes').value.split(',').map((s) => s.trim()).filter(Boolean),
      outcome: $('obOutcome').value,
      outcome_reason: $('obReason').value.trim(),
    }),
  });
  $('obGo').disabled = false;

  if (status === 503) {
    out.innerHTML = `<div class="banner danger small">저장하지 못했습니다 — ${esc(body?.detail || '')}</div>`;
    return;
  }
  if (status !== 202 || !body) {
    out.innerHTML = `<div class="banner danger small">제출하지 못했습니다 (HTTP ${status}).</div>`;
    return;
  }
  out.innerHTML = `
    <div class="banner ok small">${esc(body.note || '')}</div>
    <div class="small muted">
      검증 상태 <code>${esc(body.verification)}</code>
      ${body.duplicate ? ' · 이미 접수된 보고입니다(중복으로 쌓지 않았습니다)' : ''}
    </div>`;
}

/* ── 시작 ─────────────────────────────────────────────────────── */

$('consent').addEventListener('change', (e) => { $('go').disabled = !e.target.checked; });
$('go').addEventListener('click', runPrecheck);
$('obGo').addEventListener('click', submitObservation);
$('chatGo').addEventListener('click', () => sendChat());
$('chatIn').addEventListener('keydown', (e) => { if (e.key === 'Enter') sendChat(); });
document.querySelectorAll('.chip-btn').forEach((b) =>
  b.addEventListener('click', () => sendChat(b.dataset.q)));
loadScope();
