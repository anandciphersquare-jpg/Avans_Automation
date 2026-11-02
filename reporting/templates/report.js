/* ==========================================================================
   Execution report - client
   Plain ES2018, no dependencies, works from file:// and as a CI artifact.
   All data comes from the <script id="report-data"> JSON block.
   ========================================================================== */
(() => {
  'use strict';

  // captured before anything renders, so "Export HTML" saves the pristine page
  const ORIGINAL_HTML = '<!doctype html>\n' + document.documentElement.outerHTML;
  const DATA = JSON.parse(document.getElementById('report-data').textContent);
  const { meta, summary, trend, tests } = DATA;

  const STATUSES = ['PASS', 'FAIL', 'BLOCKED', 'SKIPPED'];
  const LABEL = { PASS: 'Passed', FAIL: 'Failed', BLOCKED: 'Blocked', SKIPPED: 'Skipped' };
  const SEVERITY = { FAIL: 0, BLOCKED: 1, SKIPPED: 2, PASS: 3 };
  const COLOR = { PASS: 'var(--pass)', FAIL: 'var(--fail)', BLOCKED: 'var(--blocked)', SKIPPED: 'var(--skipped)' };
  const PAGE_SIZE = 300;
  // screenshots / videos are embedded (a.src = data: URI); anything else links next to the page
  const asset = (a) => a.src || a.href || a.path;
  const NO_QA = { verdict: '', summary: '', failed_at: '', expected: '', actual: '', cause: '', action: '' };

  // ------------------------------------------------------------------ helpers
  const $ = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));
  const esc = (v) => String(v == null ? '' : v)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  const icon = (name, cls = 'ic') => `<svg class="${cls}" aria-hidden="true"><use href="#i-${name}"/></svg>`;
  const pill = (s) => `<span class="pill ${s}">${icon(s)}${LABEL[s] || s}</span>`;
  const pct = (n, d) => (d ? Math.round((1000 * n) / d) / 10 : 0);
  const plural = (n, word) => `${n} ${word}${n === 1 ? '' : 's'}`;

  function fmtDur(sec) {
    if (sec == null || isNaN(sec)) return '–';
    if (sec < 1) return `${Math.round(sec * 1000)} ms`;
    if (sec < 60) return `${sec.toFixed(sec < 10 ? 2 : 1)} s`;
    const m = Math.floor(sec / 60), s = Math.round(sec % 60);
    if (m < 60) return `${m}m ${String(s).padStart(2, '0')}s`;
    return `${Math.floor(m / 60)}h ${String(m % 60).padStart(2, '0')}m`;
  }
  function fmtDateTime(iso) {
    if (!iso) return '–';
    const d = new Date(iso);
    if (isNaN(d)) return iso;
    return d.toLocaleString(undefined, { year: 'numeric', month: 'short', day: '2-digit',
      hour: '2-digit', minute: '2-digit', second: '2-digit' });
  }
  const fmtTime = (iso) => (iso ? String(iso).slice(11, 23) : '–');
  const shortDate = (iso) => {
    const d = new Date(iso);
    return isNaN(d) ? '' : d.toLocaleString(undefined, { month: 'short', day: '2-digit', hour: '2-digit', minute: '2-digit' });
  };
  const trunc = (s, n) => (s.length > n ? s.slice(0, n - 1) + '…' : s);

  function download(name, content, type) {
    const blob = new Blob([content], { type });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = name;
    document.body.appendChild(a);
    a.click();
    setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 0);
  }
  async function copyText(text, btn) {
    try { await navigator.clipboard.writeText(text); }
    catch (e) {
      const ta = document.createElement('textarea');
      ta.value = text; document.body.appendChild(ta); ta.select();
      try { document.execCommand('copy'); } catch (_) { /* ignore */ }
      ta.remove();
    }
    if (btn) { const old = btn.textContent; btn.textContent = 'Copied'; setTimeout(() => { btn.textContent = old; }, 1200); }
  }

  // search index
  tests.forEach((t, i) => {
    t._idx = i;
    t.qa = t.qa || NO_QA;
    t._search = [t.test_id, t.name, t.module, t.feature, t.test_types.join(' '), t.nodeid,
      t.failure_reason, t.failure_category, t.skip_reason, t.expected, t.status, t.trend,
      t.qa.summary, t.qa.verdict]
      .join(' ').toLowerCase();
    t._shots = (t.attachments || []).filter((a) => a.kind === 'screenshot');
  });

  // ------------------------------------------------------------------ theme
  const root = document.documentElement;
  const media = window.matchMedia ? window.matchMedia('(prefers-color-scheme: dark)') : null;
  const isDark = () => root.dataset.theme ? root.dataset.theme === 'dark' : !!(media && media.matches);
  function syncThemeIcon() {
    $('#themeBtn').innerHTML = icon(isDark() ? 'sun' : 'moon');
  }
  function initTheme() {
    try { const saved = localStorage.getItem('exec-report-theme'); if (saved) root.dataset.theme = saved; } catch (e) { /* storage blocked */ }
    syncThemeIcon();
    $('#themeBtn').addEventListener('click', () => {
      root.dataset.theme = isDark() ? 'light' : 'dark';
      try { localStorage.setItem('exec-report-theme', root.dataset.theme); } catch (e) { /* ignore */ }
      syncThemeIcon();
    });
    if (media && media.addEventListener) media.addEventListener('change', syncThemeIcon);
  }

  // ------------------------------------------------------------------ tooltip
  const tip = $('#tooltip');
  function showTip(html, evt) {
    tip.innerHTML = html;
    tip.hidden = false;
    const pad = 14, r = tip.getBoundingClientRect();
    let x = evt.clientX + pad, y = evt.clientY + pad;
    if (x + r.width > window.innerWidth - 8) x = evt.clientX - r.width - pad;
    if (y + r.height > window.innerHeight - 8) y = evt.clientY - r.height - pad;
    tip.style.left = Math.max(8, x) + 'px';
    tip.style.top = Math.max(8, y) + 'px';
  }
  const hideTip = () => { tip.hidden = true; };
  function bindTips(container) {
    container.addEventListener('mousemove', (e) => {
      const el = e.target.closest('[data-tip]');
      if (el) showTip(el.getAttribute('data-tip'), e); else hideTip();
    });
    container.addEventListener('mouseleave', hideTip);
  }
  const tipRow = (color, label, value) =>
    `<div class="t-row"><i style="background:${color}"></i>${esc(label)} <b>${esc(value)}</b></div>`;

  // ------------------------------------------------------------------ header / KPIs / meta
  function renderHeader() {
    $('#title').textContent = meta.title;
    $('#subtitle').textContent = [meta.environment, `${meta.browser} ${meta.browser_version || ''}`.trim(),
      `Build ${meta.build_version}`, fmtDateTime(meta.started)].join('  ·  ');
    document.title = `${meta.title} – ${meta.run_id}`;
    $('#navTests').textContent = summary.total;
    $('#navFailures').textContent = summary.failed + summary.blocked;
    $('#navRetries').textContent = summary.retried;
  }

  function renderKpis() {
    const tile = (label, value, sub, extra = '', attrs = '') =>
      `<div class="card kpi${attrs ? ' clickable' : ''}" ${attrs}><div class="label">${label}</div>` +
      `<div class="value">${value}</div>${extra}<div class="sub">${sub}</div></div>`;
    const statusTile = (s, n) => tile(`${icon(s)}<span>${LABEL[s]}</span>`, n,
      `${pct(n, summary.total)}% of total`, '', `data-status="${s}" role="button" tabindex="0" title="Show ${LABEL[s].toLowerCase()} tests"`);
    const modules = Object.keys(summary.modules);
    $('#kpis').innerHTML = [
      tile('Total tests', summary.total, `${summary.executed} executed`),
      statusTile('PASS', summary.passed),
      statusTile('FAIL', summary.failed),
      statusTile('BLOCKED', summary.blocked),
      statusTile('SKIPPED', summary.skipped),
      tile('Pass rate', `${summary.pass_pct}%`, 'of executed tests',
        `<div class="meter" role="img" aria-label="${summary.pass_pct}% passed"><i style="width:${summary.pass_pct}%"></i></div>`),
      tile('Duration', fmtDur(meta.duration_s), `${fmtDur(summary.test_time_s)} total test time`),
      tile('Modules', modules.length, esc(modules.join(', ')) || '–'),
    ].join('');
    $$('#kpis [data-status]').forEach((el) => {
      const go = () => filterToStatus(el.dataset.status);
      el.addEventListener('click', go);
      el.addEventListener('keydown', (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); go(); } });
    });
  }

  function renderMeta() {
    const ci = meta.ci || {};
    const items = [
      ['Browser', `${meta.browser} ${meta.browser_version || ''}${meta.headless ? ' (headless)' : ''}`],
      ['Environment', `${meta.environment}`],
      ['Base URL', `<a href="${esc(meta.base_url)}" target="_blank" rel="noopener">${esc(meta.base_url)}</a>`, true],
      ['Build / release', meta.build_version],
      ['Executed by', meta.executed_by],
      ['Started', fmtDateTime(meta.started)],
      ['Finished', fmtDateTime(meta.finished)],
      ['Run ID', meta.run_id],
      ['CI', ci.url ? `<a href="${esc(ci.url)}" target="_blank" rel="noopener">${esc(ci.name)} ${esc(ci.build || '')}</a>` : esc(ci.name || 'Local'), true],
      ['Host', `${meta.host} · ${meta.os}`],
      ['Stack', `Python ${meta.python} · pytest ${meta.pytest} · Playwright ${meta.playwright}`],
      ['Parallel workers', meta.workers || 'off'],
      ['Retried / flaky', `${summary.retried} / ${summary.flaky}`],
      ['Command', `<code>${esc(meta.command)}</code>`, true],
    ];
    $('#meta').innerHTML = items.map(([k, v, raw]) =>
      `<div><dt>${esc(k)}</dt><dd>${raw ? v : esc(v)}</dd></div>`).join('');
  }

  // ------------------------------------------------------------------ charts (inline SVG)
  function chartStatus() {
    const el = $('#chartStatus');
    const counts = STATUSES.map((s) => ({ s, n: summary[{ PASS: 'passed', FAIL: 'failed', BLOCKED: 'blocked', SKIPPED: 'skipped' }[s]] }));
    const total = summary.total;
    if (!total) { el.innerHTML = '<div class="empty">No tests in this run</div>'; return; }
    const size = 170, cx = 85, cy = 85, r = 66, w = 24, C = 2 * Math.PI * r;
    const nonZero = counts.filter((c) => c.n > 0).length;
    const gap = nonZero > 1 ? 2 : 0;  // 2px surface gap between slices
    let offset = 0;
    const arcs = counts.map(({ s, n }) => {
      if (!n) return '';
      const len = (n / total) * C;
      const dash = Math.max(len - gap, 0.5);
      const t = `<div class="t-title">${LABEL[s]}</div>${tipRow(COLOR[s], 'Tests', `${n} (${pct(n, total)}%)`)}`;
      const arc = `<circle class="mark click" data-status="${s}" data-tip="${esc(t)}" cx="${cx}" cy="${cy}" r="${r}" fill="none"
        style="stroke:${COLOR[s]}" stroke-width="${w}" stroke-dasharray="${dash} ${C - dash}"
        stroke-dashoffset="${-offset}" transform="rotate(-90 ${cx} ${cy})"/>`;
      offset += len;
      return arc;
    }).join('');
    const svg = `<svg viewBox="0 0 ${size} ${size}" role="img" aria-label="Result distribution: ${counts.map((c) => `${c.n} ${LABEL[c.s].toLowerCase()}`).join(', ')}">
      <circle cx="${cx}" cy="${cy}" r="${r}" fill="none" style="stroke:var(--grid)" stroke-width="${w}"/>
      ${arcs}
      <text x="${cx}" y="${cy - 2}" text-anchor="middle" class="val" style="font-size:26px">${summary.pass_pct}%</text>
      <text x="${cx}" y="${cy + 18}" text-anchor="middle" class="tick">pass rate</text>
    </svg>`;
    const legend = `<div class="legend">${counts.map(({ s, n }) =>
      `<span>${icon(s)}<i style="background:${COLOR[s]}"></i>${LABEL[s]} <b>${n}</b> <span class="muted">${pct(n, total)}%</span></span>`).join('')}</div>`;
    el.innerHTML = `<div class="donut-wrap">${svg}${legend}</div>`;
    $$('[data-status]', el).forEach((a) => a.addEventListener('click', () => filterToStatus(a.dataset.status)));
    bindTips(el);
  }

  function chartModules() {
    const el = $('#chartModules');
    const mods = Object.entries(summary.modules);
    if (!mods.length) { el.innerHTML = '<div class="empty">No modules</div>'; return; }
    const W = 680, labelW = 150, totalW = 44, rowH = 28, barH = 14, top = 6, axisH = 22;
    const plotW = W - labelW - totalW;
    const max = Math.max(...mods.map(([, m]) => m.total), 1);
    const step = niceStep(max, 4);
    const ticks = [];
    for (let v = 0; ; v += step) { ticks.push(v); if (v >= max) break; } // last tick covers the longest bar
    const xMax = ticks[ticks.length - 1] || 1;
    const x = (v) => labelW + (v / xMax) * plotW;
    const H = top + mods.length * rowH + axisH;
    let g = ticks.map((v) => `<line class="gridline" x1="${x(v)}" x2="${x(v)}" y1="${top}" y2="${H - axisH}"/>
      <text class="tick" x="${x(v)}" y="${H - 6}" text-anchor="middle">${v}</text>`).join('');
    g += `<line class="baseline" x1="${labelW}" x2="${labelW}" y1="${top}" y2="${H - axisH}"/>`;
    mods.forEach(([name, m], i) => {
      const y = top + i * rowH + (rowH - barH) / 2;
      const keys = { PASS: 'passed', FAIL: 'failed', BLOCKED: 'blocked', SKIPPED: 'skipped' };
      const t = `<div class="t-title">${esc(name)}</div>` +
        STATUSES.map((s) => tipRow(COLOR[s], LABEL[s], m[keys[s]])).join('') +
        `<div class="t-row">Pass rate <b>${pct(m.passed, m.passed + m.failed + m.blocked)}%</b> · ${fmtDur(m.duration_s)}</div>`;
      const barEnd = x(m.total), bw = barEnd - labelW;
      const clip = `mclip${i}`;
      // square at the baseline, 4px rounded at the data end
      const rr = Math.min(4, bw / 2);
      g += `<clipPath id="${clip}"><path d="M${labelW} ${y}h${Math.max(bw - rr, 0)}a${rr} ${rr} 0 0 1 ${rr} ${rr}v${barH - 2 * rr}a${rr} ${rr} 0 0 1 ${-rr} ${rr}h${-Math.max(bw - rr, 0)}z"/></clipPath><g clip-path="url(#${clip})">`;
      let acc = 0;
      const segs = STATUSES.filter((s) => m[keys[s]] > 0);
      segs.forEach((s, j) => {
        const n = m[keys[s]];
        const x0 = x(acc), x1 = x(acc + n);
        const wSeg = Math.max(x1 - x0 - (j < segs.length - 1 ? 2 : 0), 0.5);
        g += `<rect class="mark" x="${x0}" y="${y}" width="${wSeg}" height="${barH}" style="fill:${COLOR[s]}"/>`;
        acc += n;
      });
      g += '</g>';
      g += `<text class="val" x="${barEnd + 6}" y="${y + barH - 3}">${m.total}</text>`;
      g += `<text class="click" data-module="${esc(name)}" x="${labelW - 10}" y="${y + barH - 3}" text-anchor="end"><title>${esc(name)}</title>${esc(trunc(name, 20))}</text>`;
      g += `<rect class="hit" data-module="${esc(name)}" data-tip="${esc(t)}" x="${labelW}" y="${top + i * rowH}" width="${plotW + totalW}" height="${rowH}"/>`;
    });
    el.innerHTML = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Results by module">${g}</svg>` +
      `<div class="legend">${STATUSES.map((s) => `<span><i style="background:${COLOR[s]}"></i>${LABEL[s]}</span>`).join('')}</div>`;
    $$('[data-module]', el).forEach((a) => a.addEventListener('click', () => filterToModule(a.dataset.module)));
    bindTips(el);
  }

  function chartCategories() {
    const el = $('#chartCategories');
    const cats = Object.entries(summary.verdicts || summary.failure_categories || {});
    if (!cats.length) {
      el.innerHTML = `<div class="empty">${icon('PASS')} No failed or blocked tests in this run</div>`;
      return;
    }
    const W = 400, labelW = 178, valW = 34, rowH = 30, barH = 14;
    const plotW = W - labelW - valW;
    const max = Math.max(...cats.map(([, n]) => n), 1);
    const total = cats.reduce((a, [, n]) => a + n, 0);
    const H = cats.length * rowH + 6;
    let g = `<line class="baseline" x1="${labelW}" x2="${labelW}" y1="0" y2="${H}"/>`;
    cats.forEach(([name, n], i) => {
      const y = i * rowH + (rowH - barH) / 2;
      const bw = Math.max((n / max) * plotW, 2), rr = Math.min(4, bw / 2);
      const t = `<div class="t-title">${esc(name)}</div>${tipRow('var(--accent)', 'Tests', `${n} (${pct(n, total)}%)`)}`;
      g += `<path class="mark" style="fill:var(--accent)" d="M${labelW} ${y}h${bw - rr}a${rr} ${rr} 0 0 1 ${rr} ${rr}v${barH - 2 * rr}a${rr} ${rr} 0 0 1 ${-rr} ${rr}h${-(bw - rr)}z"/>`;
      g += `<text class="val" x="${labelW + bw + 6}" y="${y + barH - 3}">${n}</text>`;
      g += `<text x="${labelW - 8}" y="${y + barH - 3}" text-anchor="end"><title>${esc(name)}</title>${esc(trunc(name, 27))}</text>`;
      g += `<rect class="hit" data-q="${esc(name)}" data-tip="${esc(t)}" x="0" y="${i * rowH}" width="${W}" height="${rowH}"/>`;
    });
    el.innerHTML = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Issue types">${g}</svg>`;
    $$('[data-q]', el).forEach((a) => a.addEventListener('click', () => {
      state.q = a.dataset.q.toLowerCase(); $('#search').value = a.dataset.q;
      state.statuses = new Set(['FAIL', 'BLOCKED']); syncChips(); renderList(); jump('#tests');
    }));
    bindTips(el);
  }

  function chartTrend() {
    const el = $('#chartTrend');
    const pts = (trend || []).filter((p) => p && p.pass_pct != null);
    $('#trendHint').textContent = pts.length > 1 ? `Last ${pts.length} runs · pass rate of executed tests` : 'Builds up from the next run';
    if (!pts.length) { el.innerHTML = '<div class="empty">No history yet</div>'; return; }
    const W = 680, H = 230, L = 40, R = 46, T = 14, B = 30;
    const pw = W - L - R, ph = H - T - B;
    const x = (i) => L + (pts.length === 1 ? pw / 2 : (i / (pts.length - 1)) * pw);
    const y = (v) => T + ph - (v / 100) * ph;
    let g = [0, 25, 50, 75, 100].map((v) => `<line class="${v === 0 ? 'baseline' : 'gridline'}" x1="${L}" x2="${L + pw}" y1="${y(v)}" y2="${y(v)}"/>
      <text class="tick" x="${L - 8}" y="${y(v) + 4}" text-anchor="end">${v}%</text>`).join('');
    const labelEvery = Math.max(1, Math.ceil(pts.length / 6));
    pts.forEach((p, i) => {
      if (i % labelEvery === 0 || i === pts.length - 1) {
        g += `<text class="tick" x="${x(i)}" y="${H - 8}" text-anchor="middle">${esc(shortDate(p.started))}</text>`;
      }
    });
    if (pts.length > 1) {
      const d = pts.map((p, i) => `${i ? 'L' : 'M'}${x(i).toFixed(1)} ${y(p.pass_pct).toFixed(1)}`).join('');
      g += `<path d="${d}L${x(pts.length - 1)} ${y(0)}L${x(0)} ${y(0)}Z" style="fill:var(--accent-soft)" stroke="none"/>`;
      g += `<path d="${d}" fill="none" style="stroke:var(--accent)" stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/>`;
    }
    pts.forEach((p, i) => {
      const last = i === pts.length - 1;
      g += `<circle cx="${x(i)}" cy="${y(p.pass_pct)}" r="${last ? 5 : 4}" style="fill:var(--accent);stroke:var(--surface)" stroke-width="2"/>`;
    });
    const lp = pts[pts.length - 1];
    g += `<text class="val" x="${x(pts.length - 1) + 9}" y="${y(lp.pass_pct) + 4}">${lp.pass_pct}%</text>`;
    g += `<line id="trendCross" class="baseline" x1="0" x2="0" y1="${T}" y2="${T + ph}" visibility="hidden"/>`;
    g += `<rect id="trendHit" class="hit" x="${L}" y="${T}" width="${pw}" height="${ph}" style="cursor:crosshair"/>`;
    el.innerHTML = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Pass rate across the last ${pts.length} runs, now ${lp.pass_pct}%">${g}</svg>`;

    const svg = $('svg', el), cross = $('#trendCross', el), hit = $('#trendHit', el);
    hit.addEventListener('mousemove', (e) => {
      const r = svg.getBoundingClientRect();
      const sx = ((e.clientX - r.left) / r.width) * W;
      let i = pts.length === 1 ? 0 : Math.round(((sx - L) / pw) * (pts.length - 1));
      i = Math.max(0, Math.min(pts.length - 1, i));
      const p = pts[i];
      cross.setAttribute('x1', x(i)); cross.setAttribute('x2', x(i)); cross.setAttribute('visibility', 'visible');
      showTip(`<div class="t-title">${esc(fmtDateTime(p.started))}${i === pts.length - 1 ? ' · this run' : ''}</div>` +
        `<div class="t-row">${esc(p.run_id)}</div>` +
        tipRow('var(--accent)', 'Pass rate', `${p.pass_pct}%`) +
        tipRow(COLOR.PASS, 'Passed', p.passed) + tipRow(COLOR.FAIL, 'Failed', p.failed) +
        tipRow(COLOR.BLOCKED, 'Blocked', p.blocked) + tipRow(COLOR.SKIPPED, 'Skipped', p.skipped) +
        `<div class="t-row">Total <b>${p.total}</b> · ${fmtDur(p.duration_s)}</div>`, e);
    });
    hit.addEventListener('mouseleave', () => { cross.setAttribute('visibility', 'hidden'); hideTip(); });
  }

  function niceStep(max, target) {
    const raw = max / target, mag = Math.pow(10, Math.floor(Math.log10(raw || 1)));
    const n = raw / mag;
    return Math.max(1, (n <= 1 ? 1 : n <= 2 ? 2 : n <= 5 ? 5 : 10) * mag);
  }

  // ------------------------------------------------------------------ failure summary
  function trendTag(t) {
    if (!t.trend) return '';
    const cls = { 'new failure': 'bad', 'still failing': 'warn', fixed: 'good', 'new test': 'accent' }[t.trend] || '';
    return `<span class="tag ${cls}">${esc(t.trend)}</span>`;
  }
  const thumb = (t) => (t._shots.length
    ? `<img class="thumb" loading="lazy" src="${esc(asset(t._shots[0]))}" alt="Failure screenshot of ${esc(t.test_id)}" data-gallery="${t._idx}" data-i="0">`
    : '<span class="muted">–</span>');

  function renderFailures() {
    const failed = tests.filter((t) => t.status === 'FAIL' || t.status === 'BLOCKED'
      || t.qa.verdict === 'Pending development');
    const box = $('#failureSummary');
    const modules = new Set(failed.map((t) => t.module));
    $('#failureCaption').textContent = failed.length
      ? `${plural(failed.length, 'test')} failed, blocked or pending across ${plural(modules.size, 'module')}` : '';
    if (!failed.length) {
      box.innerHTML = `<div class="card empty">${icon('PASS')} No failed or blocked tests in this run.</div>`;
      return;
    }
    // grouped by what a tester does next: defect, review, fix script, fix environment
    const ORDER = ['Application defect', 'Needs review', 'Test script issue', 'Environment / configuration',
      'Pending development'];
    const HINT = {
      'Application defect': 'The application did not meet the requirement. Reproduce and raise a defect.',
      'Needs review': 'Could be the application or the test expectation. Check the screenshot and decide.',
      'Test script issue': 'Automation needs fixing. Not a product defect.',
      'Environment / configuration': 'Setup, data or environment problem. Not a product defect.',
      'Pending development': 'Feature not finished by the developers. Known gap, re-test after hand-over.',
    };
    const groups = {};
    failed.forEach((t) => { const k = t.qa.verdict || 'Needs review'; (groups[k] = groups[k] || []).push(t); });
    const rank = (k) => (ORDER.indexOf(k) < 0 ? 99 : ORDER.indexOf(k));
    box.innerHTML = Object.entries(groups).sort((a, b) => rank(a[0]) - rank(b[0])).map(([verdict, list]) => `
      <div class="group-title">${esc(verdict)} <span class="tag">${list.length}</span><span class="muted group-hint">${esc(HINT[verdict] || '')}</span></div>
      <div class="card table-wrap"><table class="grid fixed">
        <thead><tr><th style="width:110px">Status</th><th style="width:120px">ID</th><th style="width:20%">Test case</th>
        <th>What went wrong</th><th style="width:24%">Next action</th><th style="width:96px">Screenshot</th></tr></thead>
        <tbody>${list.map((t) => `
          <tr class="fs-row" data-open="${t._idx}" tabindex="0">
            <td>${pill(t.status)}</td>
            <td class="mono">${esc(t.test_id)}</td>
            <td>${esc(t.name)}<div class="muted">${esc(t.module)} · ${esc(t.feature)}</div></td>
            <td><div class="reason qa">${esc(t.qa.summary || t.failure_reason)}</div>${t.qa.failed_at ? `<div class="muted">Stopped at ${esc(t.qa.failed_at)}</div>` : ''}</td>
            <td>${esc(t.qa.action)}</td>
            <td>${thumb(t)}</td>
          </tr>`).join('')}</tbody></table></div>`).join('');
  }

  // ------------------------------------------------------------------ retry analysis
  function renderRetries() {
    const box = $('#retryAnalysis');
    const retried = tests.filter((t) => t.attempts > 1);
    const flaky = retried.filter((t) => t.flaky);
    const stillBad = retried.filter((t) => t.status === 'FAIL' || t.status === 'BLOCKED');
    const extra = retried.reduce((a, t) => a + t.attempts - 1, 0);
    // unstable across runs: status flipped at least twice over recent history + this run
    const unstable = tests.map((t) => {
      const seq = (t.history || []).concat([t.status]).filter((s) => s !== 'SKIPPED');
      let flips = 0;
      for (let i = 1; i < seq.length; i++) if ((seq[i] === 'PASS') !== (seq[i - 1] === 'PASS')) flips++;
      return { t, flips, seq };
    }).filter((x) => x.flips >= 2).sort((a, b) => b.flips - a.flips);

    $('#retryCaption').textContent = retried.length ? `${plural(retried.length, 'test')} needed more than one attempt` : '';
    const kpis = `<div class="mini-kpis">
      <div class="card"><span class="muted">Retried tests</span><b>${retried.length}</b></div>
      <div class="card"><span class="muted">Passed on retry (flaky)</span><b>${flaky.length}</b></div>
      <div class="card"><span class="muted">Failed after all retries</span><b>${stillBad.length}</b></div>
      <div class="card"><span class="muted">Extra attempts</span><b>${extra}</b></div>
      <div class="card"><span class="muted">Unstable across runs</span><b>${unstable.length}</b></div>
    </div>`;
    const seqTags = (list) => `<span class="seq">${list.map((s, i) => `<span class="pill ${s}" title="Attempt ${i + 1}">${icon(s)}${i + 1}</span>`).join('')}</span>`;
    const retryTable = retried.length ? `<div class="card table-wrap"><table class="grid">
      <thead><tr><th>ID</th><th>Test case</th><th>Module</th><th>Attempts</th><th>Outcome per attempt</th><th>Final</th><th>Verdict</th></tr></thead>
      <tbody>${retried.map((t) => `<tr class="fs-row" data-open="${t._idx}" tabindex="0">
        <td class="mono">${esc(t.test_id)}</td><td>${esc(t.name)}</td><td>${esc(t.module)}</td>
        <td class="num">${t.attempts}</td><td>${seqTags(t.attempt_outcomes)}</td><td>${pill(t.status)}</td>
        <td>${t.flaky ? '<span class="tag warn">Flaky – passed on retry</span>' : '<span class="tag bad">Consistent failure</span>'}</td>
      </tr>`).join('')}</tbody></table></div>`
      : `<div class="card empty">No test needed a retry in this run. Run with <code>--reruns 2</code> (pytest-rerunfailures) to retry failures automatically and separate flaky tests from real defects.</div>`;
    const unstableTable = unstable.length ? `<div class="group-title">Unstable across recent runs <span class="tag">${unstable.length}</span></div>
      <div class="card table-wrap"><table class="grid">
      <thead><tr><th>ID</th><th>Test case</th><th>Module</th><th>Recent results (oldest → this run)</th><th>Status flips</th></tr></thead>
      <tbody>${unstable.slice(0, 50).map(({ t, flips }) => `<tr class="fs-row" data-open="${t._idx}" tabindex="0">
        <td class="mono">${esc(t.test_id)}</td><td>${esc(t.name)}</td><td>${esc(t.module)}</td>
        <td>${histDots(t)}</td><td class="num">${flips}</td></tr>`).join('')}</tbody></table></div>` : '';
    box.innerHTML = kpis + retryTable + unstableTable;
  }

  function histDots(t) {
    const seq = (t.history || []);
    return `<span class="hist">${seq.map((s) => `<i class="bg-${s}" title="${LABEL[s] || s}"></i>`).join('')}` +
      `<i class="bg-${t.status} cur" title="This run: ${LABEL[t.status]}"></i></span>`;
  }

  // ------------------------------------------------------------------ filters / list
  const state = { q: '', statuses: new Set(), module: '', type: '', sort: 'default', group: true, retriedOnly: false, limit: PAGE_SIZE };

  function initToolbar() {
    const counts = {};
    tests.forEach((t) => { counts[t.status] = (counts[t.status] || 0) + 1; });
    $('#statusChips').innerHTML = STATUSES.map((s) =>
      `<button class="chip ${s}" data-status="${s}" aria-pressed="false">${icon(s)}${LABEL[s]} <span class="n">${counts[s] || 0}</span></button>`).join('');
    $$('#statusChips .chip').forEach((c) => c.addEventListener('click', () => {
      const s = c.dataset.status;
      state.statuses.has(s) ? state.statuses.delete(s) : state.statuses.add(s);
      syncChips(); resetLimit(); renderList();
    }));
    const modules = [...new Set(tests.map((t) => t.module))].sort();
    $('#moduleFilter').insertAdjacentHTML('beforeend', modules.map((m) => `<option>${esc(m)}</option>`).join(''));
    const types = [...new Set(tests.flatMap((t) => t.test_types))].sort();
    $('#typeFilter').insertAdjacentHTML('beforeend', types.map((m) => `<option>${esc(m)}</option>`).join(''));

    let timer;
    $('#search').addEventListener('input', (e) => {
      clearTimeout(timer);
      timer = setTimeout(() => { state.q = e.target.value.trim().toLowerCase(); resetLimit(); renderList(); }, 150);
    });
    $('#moduleFilter').addEventListener('change', (e) => { state.module = e.target.value; resetLimit(); renderList(); });
    $('#typeFilter').addEventListener('change', (e) => { state.type = e.target.value; resetLimit(); renderList(); });
    $('#sortBy').addEventListener('change', (e) => { state.sort = e.target.value; renderList(); });
    $('#groupToggle').addEventListener('change', (e) => { state.group = e.target.checked; renderList(); });
    $('#retriedOnly').addEventListener('change', (e) => { state.retriedOnly = e.target.checked; resetLimit(); renderList(); });
    $('#expandAll').addEventListener('click', () => setAllOpen(true));
    $('#collapseAll').addEventListener('click', () => setAllOpen(false));
    $('#resetFilters').addEventListener('click', () => { resetFilters(); renderList(); });
  }

  function resetLimit() { state.limit = PAGE_SIZE; }
  function resetFilters() {
    Object.assign(state, { q: '', statuses: new Set(), module: '', type: '', retriedOnly: false, limit: PAGE_SIZE });
    $('#search').value = ''; $('#moduleFilter').value = ''; $('#typeFilter').value = ''; $('#retriedOnly').checked = false;
    syncChips();
  }
  function syncChips() {
    $$('#statusChips .chip').forEach((c) => c.setAttribute('aria-pressed', state.statuses.has(c.dataset.status) ? 'true' : 'false'));
  }
  function filterToStatus(s) {
    resetFilters(); state.statuses = new Set([s]); syncChips(); renderList(); jump('#tests');
  }
  function filterToModule(m) {
    resetFilters(); state.module = m; $('#moduleFilter').value = m; renderList(); jump('#tests');
  }
  const jump = (sel) => { const el = $(sel); if (el) el.scrollIntoView({ behavior: 'smooth', block: 'start' }); };

  function matches(t) {
    if (state.statuses.size && !state.statuses.has(t.status)) return false;
    if (state.module && t.module !== state.module) return false;
    if (state.type && !t.test_types.includes(state.type)) return false;
    if (state.retriedOnly && t.attempts < 2) return false;
    if (state.q) return state.q.split(/\s+/).every((term) => t._search.includes(term));
    return true;
  }
  const SORTERS = {
    default: (a, b) => a._idx - b._idx,
    status: (a, b) => SEVERITY[a.status] - SEVERITY[b.status] || a._idx - b._idx,
    duration: (a, b) => b.duration_s - a.duration_s,
    name: (a, b) => a.name.localeCompare(b.name),
    id: (a, b) => a.test_id.localeCompare(b.test_id, undefined, { numeric: true }),
    start: (a, b) => String(a.start).localeCompare(String(b.start)),
  };
  function filtered() { return tests.filter(matches).sort(SORTERS[state.sort] || SORTERS.default); }

  function testRow(t, showModule) {
    const shots = t._shots.length ? `<span class="tag" title="${plural(t._shots.length, 'screenshot')}">${icon('camera')}${t._shots.length}</span>` : '';
    const retry = t.attempts > 1 ? `<span class="tag ${t.flaky ? 'warn' : ''}" title="${t.attempts} attempts">${icon('retry')}${t.attempts}${t.flaky ? ' flaky' : ''}</span>` : '';
    const sub = (t.status === 'FAIL' || t.status === 'BLOCKED') && (t.qa.summary || t.failure_reason)
      ? `<span class="err">${esc(trunc(t.qa.summary || t.failure_reason, 180))}</span>`
      : esc([t.feature, showModule ? t.module : ''].filter(Boolean).join(' · '));
    return `<details class="test" data-idx="${t._idx}" id="t${t._idx}">
      <summary>
        ${pill(t.status)}
        <span class="tid${t.test_id_auto ? ' auto' : ''}" title="${t.test_id_auto ? 'Auto-generated ID (add one to the docstring or @pytest.mark.meta)' : esc(t.test_id)}">${esc(t.test_id)}</span>
        <span class="tname"><div class="n" title="${esc(t.name)}">${esc(t.name)}</div><div class="f">${sub}</div></span>
        <span class="tbadges"><span class="tag accent">${esc(t.test_type)}</span>${shots}${retry}${trendTag(t)}</span>
        <span class="tdur">${fmtDur(t.duration_s)}</span>
        ${icon('chev', 'ic chev')}
      </summary>
      <div class="detail"></div>
    </details>`;
  }

  function moduleStats(list) {
    const c = { PASS: 0, FAIL: 0, BLOCKED: 0, SKIPPED: 0 };
    list.forEach((t) => { c[t.status]++; });
    const total = list.length || 1;
    const bar = `<span class="stackbar" role="img" aria-label="${STATUSES.map((s) => `${c[s]} ${LABEL[s].toLowerCase()}`).join(', ')}">${STATUSES.filter((s) => c[s])
      .map((s) => `<i style="width:${(100 * c[s]) / total}%;background:${COLOR[s]}"></i>`).join('')}</span>`;
    return STATUSES.filter((s) => c[s]).map((s) => `<span class="dotstat" title="${LABEL[s]}">${icon(s)}${c[s]}</span>`).join('') + bar;
  }

  function renderList() {
    const list = filtered();
    const box = $('#testList');
    $('#resultCount').textContent = `Showing ${list.length} of ${tests.length}`;
    if (!list.length) {
      box.innerHTML = '<div class="card empty">No test matches these filters. <button class="btn ghost" id="emptyReset">Reset filters</button></div>';
      $('#emptyReset').addEventListener('click', () => { resetFilters(); renderList(); });
      return;
    }
    const visible = list.slice(0, state.limit);
    let html = '';
    if (state.group) {
      const groups = new Map();
      list.forEach((t) => { if (!groups.has(t.module)) groups.set(t.module, []); groups.get(t.module).push(t); });
      const shown = new Set(visible.map((t) => t._idx));
      [...groups.keys()].sort().forEach((m) => {
        const all = groups.get(m), rows = all.filter((t) => shown.has(t._idx));
        if (!rows.length) return;
        html += `<details class="module-group card" open>
          <summary>${icon('chev', 'ic chev')}<span class="module-name">${esc(m)}</span>
          <span class="muted">${plural(all.length, 'test')}</span><span class="module-stats">${moduleStats(all)}</span></summary>
          <div>${rows.map((t) => testRow(t, false)).join('')}</div></details>`;
      });
    } else {
      html = `<div class="card flat">${visible.map((t) => testRow(t, true)).join('')}</div>`;
    }
    if (list.length > visible.length) {
      html += `<div class="more"><button class="btn" id="showMore">Show ${Math.min(PAGE_SIZE, list.length - visible.length)} more (${list.length - visible.length} hidden)</button></div>`;
    }
    box.innerHTML = html;
    const more = $('#showMore');
    if (more) more.addEventListener('click', () => { state.limit += PAGE_SIZE; renderList(); });
  }

  function setAllOpen(open) {
    $$('#testList details.module-group').forEach((d) => { d.open = true; });
    $$('#testList details.test').forEach((d) => { d.open = open; if (open) ensureDetail(d); });
  }

  // lazy detail rendering
  document.addEventListener('toggle', (e) => {
    const d = e.target;
    if (d.classList && d.classList.contains('test') && d.open) ensureDetail(d);
  }, true);

  function ensureDetail(d) {
    const box = $('.detail', d);
    if (box.dataset.ready) return;
    box.innerHTML = renderDetail(tests[+d.dataset.idx]);
    box.dataset.ready = '1';
  }

  // ------------------------------------------------------------------ test detail
  function renderDetail(t) {
    const tabs = [
      ['overview', 'Overview', null],
      ['steps', 'Steps', t.steps.length],
      ['evidence', 'Evidence', t.attachments.length],
      ['api', 'API calls', t.api_logs.length],
      ['console', 'Console', t.console_errors.length],
      ['network', 'Network', t.network_failures.length],
      ['logs', 'Logs', null],
    ];
    const head = `<div class="tabs" role="tablist">${tabs.map(([k, label, n], i) =>
      `<button role="tab" data-tab="${k}" aria-selected="${i === 0}">${label}${n != null ? ` <span class="count">${n}</span>` : ''}</button>`).join('')}</div>`;
    const panels = {
      overview: panelOverview(t), steps: panelSteps(t), evidence: panelEvidence(t), api: panelApi(t),
      console: panelConsole(t), network: panelNetwork(t), logs: panelLogs(t),
    };
    return head + tabs.map(([k, label], i) =>
      `<div class="panel${i === 0 ? ' active' : ''}" data-panel="${k}" role="tabpanel"><div class="panel-title">${label}</div>${panels[k]}</div>`).join('');
  }

  const listOr = (items, empty) => (items.length ? `<ul>${items.map((x) => `<li>${esc(x)}</li>`).join('')}</ul>` : `<span class="muted">${empty}</span>`);
  const val = (v) => (v !== null && typeof v === 'object' ? `<code>${esc(JSON.stringify(v))}</code>` : esc(v === '' ? '""' : v));

  function panelOverview(t) {
    let out = '';
    if (t.status !== 'PASS') {
      const q = t.qa;
      const row = (label, value) => (value ? `<dt>${label}</dt><dd>${esc(value)}</dd>` : '');
      const skipped = t.status === 'SKIPPED';
      out += `<div class="failbox ${t.status === 'FAIL' ? '' : 'blocked'}"${skipped ? ' style="background:var(--skipped-soft);border-color:var(--border-strong)"' : ''}>
        <div class="head">${pill(t.status)} ${q.verdict ? `<span class="tag verdict">${esc(q.verdict)}</span>` : ''}</div>
        <div class="msg qa">${esc(q.summary || t.failure_reason || t.skip_reason)}</div>
        <dl class="kv qa-kv">
          ${row('Stopped at', q.failed_at)}
          ${row('Expected', q.expected)}
          ${row('Actual', q.actual)}
          ${row('Probable cause', q.cause)}
          ${row('Next action', q.action)}
        </dl></div>`;
      if (t.failure_reason || t.stack_trace) {
        out += `<details class="block tech"><summary><h4>Technical details (for developers)</h4></summary>
          <div class="note">${t.failure_category ? `<span class="tag">${esc(t.failure_category)}</span> ` : ''}${t.error_type ? `<code>${esc(t.error_type)}</code> ` : ''}${esc(t.failure_reason)}</div>
          ${t.stack_trace ? `<div class="code-actions"><button class="btn ghost" data-copy="stack">Copy</button></div>
          <pre class="code" data-stack>${esc(t.stack_trace)}</pre>` : ''}</details>`;
      }
    }
    const passLike = t.status === 'PASS';
    const data = Object.entries(t.test_data || {});
    out += `<div class="cols"><div>
      ${passLike ? `<div class="block"><h4>Expected vs actual</h4><div class="ea">
        <div><h5>Expected result</h5>${esc(t.expected || '–')}</div>
        <div class="good"><h5>Actual result</h5>${esc(t.actual || '–')}</div>
      </div></div>` : ''}
      <div class="block"><h4>Preconditions</h4>${listOr(t.preconditions, 'None recorded')}</div>
      <div class="block"><h4>Test data</h4>${data.length
        ? `<dl class="kv">${data.map(([k, v]) => `<dt>${esc(k)}</dt><dd class="mono">${val(v)}</dd>`).join('')}</dl>`
        : '<span class="muted">No parameters or recorded data</span>'}</div>
    </div><div>
      <div class="block"><h4>Execution</h4><dl class="kv">
        <dt>Status</dt><dd>${pill(t.status)}</dd>
        <dt>Test ID</dt><dd class="mono">${esc(t.test_id)}${t.test_id_auto ? ' <span class="muted">(auto)</span>' : ''}</dd>
        <dt>Type</dt><dd>${t.test_types.map((x) => `<span class="tag accent">${esc(x)}</span>`).join(' ')}</dd>
        <dt>Module</dt><dd>${esc(t.module)}</dd>
        <dt>Feature</dt><dd>${esc(t.feature)}</dd>
        <dt>Start</dt><dd>${esc(fmtDateTime(t.start))}</dd>
        <dt>End</dt><dd>${esc(fmtDateTime(t.end))}</dd>
        <dt>Duration</dt><dd>${fmtDur(t.duration_s)}</dd>
        <dt>Attempts</dt><dd>${t.attempts}${t.attempts > 1 ? ' · ' + t.attempt_outcomes.map((s) => LABEL[s]).join(' → ') : ''}${t.flaky ? ' <span class="tag warn">flaky</span>' : ''}</dd>
        <dt>Browser</dt><dd>${esc(`${t.browser || meta.browser} ${t.browser_version || ''}`)}</dd>
        <dt>Environment</dt><dd>${esc(meta.environment)}</dd>
        <dt>Build</dt><dd>${esc(meta.build_version)}</dd>
        <dt>Executed by</dt><dd>${esc(meta.executed_by)}</dd>
        <dt>Worker</dt><dd>${esc(t.worker)}</dd>
        <dt>History</dt><dd>${histDots(t)} ${trendTag(t)}</dd>
        <dt>Location</dt><dd class="mono">${esc(t.file)}:${t.line}</dd>
        <dt>Node ID</dt><dd class="mono">${esc(t.nodeid)}</dd>
        <dt>Markers</dt><dd>${t.markers.map((m) => `<span class="tag">${esc(m)}</span>`).join(' ') || '–'}</dd>
      </dl></div>
    </div></div>`;
    return out;
  }

  const STEP_ICON = { passed: 'PASS', failed: 'FAIL', skipped: 'SKIPPED' };
  function panelSteps(t) {
    if (!t.steps.length) return '<div class="empty">No steps recorded.</div>';
    const auto = t.steps[0].source === 'auto';
    const items = t.steps.map((s) => {
      const cls = s.status.replace(' ', '-');
      const ic = STEP_ICON[s.status] ? icon(STEP_ICON[s.status], `ic st ${cls}`)
        : `<svg class="ic st ${cls}" viewBox="0 0 16 16" aria-hidden="true"><circle cx="8" cy="8" r="4" fill="none" stroke="currentColor" stroke-width="1.6"/></svg>`;
      const metaTxt = s.source === 'auto' ? (s.line ? `line ${s.line}` : '') : fmtDur(s.duration_ms / 1000);
      return `<li class="s-${cls}" style="${s.depth ? `padding-left:${s.depth * 18}px` : ''}">${ic}
        <span class="txt${s.source === 'auto' && !s.code ? ' code' : ''}" title="${esc(s.status)}">${esc(s.title)}${s.code ? `<code class="step-code">${esc(s.code)}</code>` : ''}</span><span class="meta">${esc(s.status)} · ${esc(metaTxt)}</span>
        ${s.error ? `<span class="err">${esc(s.error.split('\nassert ')[0])}</span>` : ''}</li>`;
    }).join('');
    return `<ol class="steps">${items}</ol>` + (auto
      ? '<div class="note">Steps are read from the test script (shown in plain words, with the code underneath). The step that failed is marked; later steps did not run.</div>' : '');
  }

  function panelEvidence(t) {
    const shots = t._shots, vids = t.attachments.filter((a) => a.kind === 'video'),
      traces = t.attachments.filter((a) => a.kind === 'trace'), files = t.attachments.filter((a) => a.kind === 'file');
    if (!t.attachments.length) {
      return '<div class="empty">No attachments. Screenshots are taken automatically on failure; videos and traces are kept for failed tests (see REPORT_VIDEO / REPORT_TRACE).</div>';
    }
    let out = '';
    if (shots.length) {
      out += `<div class="block"><h4>Screenshots</h4><div class="shots">${shots.map((a, i) => `
        <figure class="shot"><img loading="lazy" src="${esc(asset(a))}" alt="${esc(a.title)}" data-gallery="${t._idx}" data-i="${i}">
        <figcaption>${esc(a.title)} · attempt ${a.attempt}</figcaption></figure>`).join('')}</div></div>`;
    }
    if (vids.length) {
      out += `<div class="block"><h4>Video</h4>${vids.map((a) => `<div style="margin-bottom:8px"><video controls preload="metadata" src="${esc(asset(a))}"></video>
        <div class="note">Recording of attempt ${a.attempt}${a.src ? ' (embedded in this page)' : ` · <a href="${esc(a.href || a.path)}" download>${esc(a.path)}</a>`}</div></div>`).join('')}</div>`;
    }
    if (traces.length) {
      out += `<div class="block"><h4>Playwright trace</h4>${traces.map((a) => `<div style="margin-bottom:8px">
        <a class="btn" href="${esc(asset(a))}" download>${icon('download')} ${esc(a.path.split('/').pop())}</a>
        <div class="note">Open with <code>playwright show-trace runs/${esc(meta.run_id)}/${esc(a.path)}</code> (run inside <code>reports/</code>), or drop the file on trace.playwright.dev.</div></div>`).join('')}</div>`;
    }
    if (files.length) {
      out += `<div class="block"><h4>Files</h4><ul>${files.map((a) => `<li><a href="${esc(asset(a))}" target="_blank" rel="noopener">${esc(a.title)}</a></li>`).join('')}</ul></div>`;
    }
    return out;
  }

  function statusCode(code, ok) {
    if (code == null) return '<span class="muted">–</span>';
    return `<span class="status-code ${ok ? 'ok' : 'bad'}">${icon(ok ? 'PASS' : 'FAIL')}${esc(code)}</span>`;
  }
  const headersBlock = (h) => (h && Object.keys(h).length ? Object.entries(h).map(([k, v]) => `${k}: ${v}`).join('\n') : '');
  function panelApi(t) {
    if (!t.api_logs.length) return '<div class="empty">No API calls captured. ApiClient calls and browser XHR/fetch traffic are logged automatically.</div>';
    const rows = t.api_logs.map((a, i) => {
      if (a.source === 'note') return `<tr><td colspan="6" class="muted">${esc(a.url)}</td></tr>`;
      const req = [headersBlock(a.request_headers), a.request_body ? '\n' + a.request_body : ''].join('').trim();
      const res = [headersBlock(a.response_headers), a.response_body ? '\n' + a.response_body : ''].join('').trim();
      return `<tr class="api-row" data-api="${i}" tabindex="0">
          <td class="num">${i + 1}</td><td><span class="tag">${esc(a.source)}</span></td><td class="method">${esc(a.method)}</td>
          <td>${statusCode(a.status, a.ok)}</td><td class="url">${esc(a.url)}</td><td class="num">${a.duration_ms != null ? a.duration_ms + ' ms' : '–'}</td></tr>
        <tr class="api-detail" data-api-detail="${i}" hidden><td colspan="6"><div class="ea">
          <div><h5>Request</h5><pre class="code wrap">${esc(req || '(no headers / body captured)')}</pre></div>
          <div><h5>Response</h5><pre class="code wrap">${esc(res || (a.source === 'browser' ? '(browser traffic: body not captured)' : '(empty)'))}</pre></div>
        </div></td></tr>`;
    }).join('');
    return `<div class="table-wrap"><table class="grid"><thead><tr><th>#</th><th>Source</th><th>Method</th><th>Status</th><th>URL</th><th>Time</th></tr></thead><tbody>${rows}</tbody></table></div>
      <div class="note">Click a row for headers and bodies. Passwords, tokens, OTPs and cookies are redacted.</div>`;
  }

  function panelConsole(t) {
    if (!t.console_errors.length) return '<div class="empty">No console errors or warnings captured.</div>';
    return `<div class="table-wrap"><table class="grid"><thead><tr><th>Time</th><th>Type</th><th>Message</th><th>Location</th></tr></thead><tbody>${
      t.console_errors.map((c) => `<tr><td class="mono">${esc(fmtTime(c.time))}</td>
        <td><span class="tag ${c.type === 'warning' ? 'warn' : 'bad'}">${esc(c.type)}</span></td>
        <td><pre class="code wrap" style="max-height:160px">${esc(c.text)}</pre></td><td class="url">${esc(c.location)}</td></tr>`).join('')
    }</tbody></table></div>`;
  }

  function panelNetwork(t) {
    if (!t.network_failures.length) return '<div class="empty">No failed requests or HTTP error responses captured.</div>';
    return `<div class="table-wrap"><table class="grid"><thead><tr><th>Time</th><th>Kind</th><th>Method</th><th>Status</th><th>URL</th><th>Type</th><th>Error</th></tr></thead><tbody>${
      t.network_failures.map((n) => `<tr><td class="mono">${esc(fmtTime(n.time))}</td><td>${esc(n.kind)}</td>
        <td class="method">${esc(n.method)}</td><td>${statusCode(n.status, false)}</td><td class="url">${esc(n.url)}</td>
        <td>${esc(n.resource_type)}</td><td>${esc(n.error)}</td></tr>`).join('')
    }</tbody></table></div>`;
  }

  function panelLogs(t) {
    if (!t.captured_log) return '<div class="empty">No stdout / stderr / logging output captured.</div>';
    return `<div class="code-actions"><button class="btn ghost" data-copy="log">Copy</button></div><pre class="code" data-log>${esc(t.captured_log)}</pre>`;
  }

  // delegated clicks inside the test list / summaries
  document.addEventListener('click', (e) => {
    const tab = e.target.closest('.tabs button');
    if (tab) {
      const detail = tab.closest('.detail');
      $$('.tabs button', detail).forEach((b) => b.setAttribute('aria-selected', b === tab ? 'true' : 'false'));
      $$('.panel', detail).forEach((p) => p.classList.toggle('active', p.dataset.panel === tab.dataset.tab));
      return;
    }
    const img = e.target.closest('[data-gallery]');
    if (img) { e.preventDefault(); e.stopPropagation(); openModal(+img.dataset.gallery, +img.dataset.i); return; }
    const copy = e.target.closest('[data-copy]');
    if (copy) {
      const pre = $(`[data-${copy.dataset.copy}]`, copy.closest('.panel'));
      if (pre) copyText(pre.textContent, copy);
      return;
    }
    const api = e.target.closest('.api-row');
    if (api) {
      const row = $(`[data-api-detail="${api.dataset.api}"]`, api.closest('tbody'));
      if (row) row.hidden = !row.hidden;
      return;
    }
    const open = e.target.closest('[data-open]');
    if (open) openTest(+open.dataset.open);
  });
  document.addEventListener('keydown', (e) => {
    if (e.key !== 'Enter') return;
    const row = e.target.closest && e.target.closest('[data-open], .api-row');
    if (row) row.click();
  });

  function openTest(idx) {
    let el = document.getElementById('t' + idx);
    if (!el) {
      resetFilters();
      const pos = filtered().findIndex((t) => t._idx === idx);
      state.limit = Math.max(PAGE_SIZE, Math.ceil((pos + 1) / PAGE_SIZE) * PAGE_SIZE);
      renderList();
      el = document.getElementById('t' + idx);
    }
    if (!el) return;
    const group = el.closest('details.module-group');
    if (group) group.open = true;
    el.open = true;
    ensureDetail(el);
    el.scrollIntoView({ behavior: 'smooth', block: 'start' });
    el.classList.remove('flash'); void el.offsetWidth; el.classList.add('flash');
  }

  // ------------------------------------------------------------------ screenshot modal
  const modal = $('#modal');
  let gallery = [], gi = 0, lastFocus = null;
  function openModal(testIdx, i) {
    const t = tests[testIdx];
    gallery = t._shots.map((a) => ({ src: asset(a), title: `${t.test_id} · ${t.name} — ${a.title} (attempt ${a.attempt})` }));
    if (!gallery.length) return;
    lastFocus = document.activeElement;
    modal.hidden = false;
    document.body.style.overflow = 'hidden';
    showShot(i || 0);
    $('#modalClose').focus();
  }
  function showShot(i) {
    gi = (i + gallery.length) % gallery.length;
    const g = gallery[gi];
    $('#modalImg').src = g.src;
    $('#modalImg').alt = g.title;
    $('#modalOpen').href = g.src;
    $('#modalCaption').textContent = `${g.title}${gallery.length > 1 ? `  ·  ${gi + 1} / ${gallery.length}` : ''}`;
    $('#modalPrev').hidden = $('#modalNext').hidden = gallery.length < 2;
  }
  function closeModal() {
    modal.hidden = true;
    document.body.style.overflow = '';
    if (lastFocus) lastFocus.focus();
  }
  modal.addEventListener('click', (e) => { if (e.target.closest('[data-close]')) closeModal(); });
  $('#modalPrev').addEventListener('click', () => showShot(gi - 1));
  $('#modalNext').addEventListener('click', () => showShot(gi + 1));
  document.addEventListener('keydown', (e) => {
    if (modal.hidden) return;
    if (e.key === 'Escape') closeModal();
    else if (e.key === 'ArrowLeft') showShot(gi - 1);
    else if (e.key === 'ArrowRight') showShot(gi + 1);
  });

  // ------------------------------------------------------------------ export
  const CSV_FIELDS = [
    ['Test Case ID', (t) => t.test_id], ['Test Case Name', (t) => t.name], ['Module', (t) => t.module],
    ['Feature', (t) => t.feature], ['Type', (t) => t.test_types.join(', ')],
    ['Preconditions', (t) => t.preconditions.join(' | ')], ['Test Data', (t) => (Object.keys(t.test_data).length ? JSON.stringify(t.test_data) : '')],
    ['Steps', (t) => t.steps.map((s, i) => `${i + 1}. [${s.status}] ${s.title}`).join('\n')],
    ['Expected Result', (t) => t.expected], ['Actual Result', (t) => t.actual], ['Status', (t) => t.status],
    ['QA Summary', (t) => (t.status === 'PASS' ? '' : t.qa.summary)], ['Issue Type', (t) => (t.status === 'PASS' ? '' : t.qa.verdict)],
    ['Failed At', (t) => t.qa.failed_at], ['Probable Cause', (t) => t.qa.cause], ['Suggested Action', (t) => t.qa.action],
    ['Technical Error', (t) => t.failure_reason || t.skip_reason], ['Failure Category', (t) => t.failure_category],
    ['Screenshots', (t) => t._shots.map((a) => a.path).join('; ')],
    ['Video', (t) => t.attachments.filter((a) => a.kind === 'video').map((a) => a.path).join('; ')],
    ['Start', (t) => t.start], ['End', (t) => t.end], ['Duration (s)', (t) => t.duration_s],
    ['Browser', (t) => `${t.browser} ${t.browser_version}`.trim()], ['Environment', () => meta.environment],
    ['Executed By', () => meta.executed_by], ['Build Version', () => meta.build_version],
    ['API Calls', (t) => t.api_logs.length], ['Console Errors', (t) => t.console_errors.length],
    ['Network Failures', (t) => t.network_failures.length], ['Attempts', (t) => t.attempts], ['Node ID', (t) => t.nodeid],
  ];
  const csvCell = (v) => { const s = String(v == null ? '' : v); return /[",\n\r]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s; };

  function exportAs(kind) {
    const base = `test-report_${meta.run_id}`;
    if (kind === 'json') {
      const clean = { ...DATA, tests: tests.map(({ _idx, _search, _shots, ...rest }) =>
        ({ ...rest, attachments: rest.attachments.map(({ src, ...a }) => a) })) };
      download(`${base}.json`, JSON.stringify(clean, null, 2), 'application/json');
    } else if (kind === 'csv') {
      const rows = [CSV_FIELDS.map(([h]) => h)].concat(filtered().map((t) => CSV_FIELDS.map(([, f]) => f(t))));
      download(`${base}.csv`, '﻿' + rows.map((r) => r.map(csvCell).join(',')).join('\r\n'), 'text/csv');
    } else if (kind === 'html') {
      download(`${base}.html`, ORIGINAL_HTML, 'text/html');
    } else if (kind === 'pdf') {
      printPdf();
    }
  }

  function printPdf() {
    const list = filtered();
    if (list.length > state.limit) { state.limit = list.length; renderList(); }
    if (list.length > 400 && !window.confirm(`The PDF will include ${list.length} tests with full details. This can take a while. Continue?`)) return;
    const opened = [];
    $$('#testList details.module-group').forEach((d) => { if (!d.open) { d.open = true; opened.push(d); } });
    $$('#testList details.test').forEach((d) => { if (!d.open) { d.open = true; ensureDetail(d); opened.push(d); } });
    const restore = () => { opened.forEach((d) => { d.open = false; }); window.removeEventListener('afterprint', restore); };
    window.addEventListener('afterprint', restore);
    setTimeout(() => window.print(), 50);
  }

  function initExport() {
    const btn = $('#exportBtn'), list = $('#exportMenu .menu-list');
    const close = () => { list.hidden = true; btn.setAttribute('aria-expanded', 'false'); };
    btn.addEventListener('click', (e) => {
      e.stopPropagation();
      list.hidden = !list.hidden;
      btn.setAttribute('aria-expanded', String(!list.hidden));
      if (!list.hidden) $('button', list).focus();
    });
    $$('button', list).forEach((b) => b.addEventListener('click', () => { close(); exportAs(b.dataset.export); }));
    document.addEventListener('click', (e) => { if (!e.target.closest('#exportMenu')) close(); });
    document.addEventListener('keydown', (e) => { if (e.key === 'Escape') close(); });
  }

  // ------------------------------------------------------------------ boot
  function renderFooter() {
    // reports/runs/<id>/html/ vs the reports/latest/html/ copy
    const index = /\/latest\/html\/[^/]*$/.test(location.pathname.replace(/\\/g, '/')) ? '../../index.html' : '../../../index.html';
    $('#footer').innerHTML = `Generated ${esc(fmtDateTime(meta.finished))} · run folder <code>reports/runs/${esc(meta.run_id)}</code> ·
      data: <a href="../json/results.json">results.json</a> · <a href="../csv/results.csv">results.csv</a> ·
      <a href="../logs/execution.log">execution.log</a> · <a href="${index}">all runs</a>`;
  }

  initTheme();
  renderHeader();
  renderKpis();
  renderMeta();
  chartStatus();
  chartModules();
  chartCategories();
  chartTrend();
  renderFailures();
  renderRetries();
  initToolbar();
  initExport();
  renderList();
  renderFooter();

  // deep link: report.html#fail opens with failures selected
  if (location.hash === '#fail') filterToStatus('FAIL');
})();
