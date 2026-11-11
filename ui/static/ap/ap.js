/* Autopilot terminal (ui/apterm.py), 11.11.: the chart, the live tick (SSE with a 5-s poll fallback), the parts that
   load when they come into view, the order panel (fills fields only: every form posts to the route it always had),
   the tabs and the phone's bottom sheet. Served from /pravi-trade/static/ap.js?v=<hash>, cached for a year. */
(() => {
  'use strict';
  const root = document.getElementById('apx');
  if (!root) return;
  const $ = (s, r) => (r || document).querySelector(s);
  const $$ = (s, r) => [...(r || document).querySelectorAll(s)];
  let F = {};
  try { F = JSON.parse($('#apx-first').textContent); } catch (e) { F = {}; }
  const URLS = F.urls || {};
  const S = { m: F.m || '', tf: '5m', unit: 'mc', side: 'buy', live: {}, tsig: null, fit: true };
  try { S.tf = localStorage.getItem('apx.tf') || '5m'; S.unit = localStorage.getItem('apx.unit') || 'mc'; } catch (e) { /* private mode */ }
  if (!['1m', '5m', '15m', '1h'].includes(S.tf)) S.tf = '5m';
  const STEP = { '1m': 60, '5m': 300, '15m': 900, '1h': 3600 };

  // ---- numbers, the same words as the server (ui/apterm.mc = pravitrade._usd_short, ui/redak.pct / sol) ----
  const NB = ' ', MI = '−';
  const fMc = x => (x == null || !isFinite(x) || x <= 0) ? '–' : x >= 1e6 ? '$' + (x / 1e6).toFixed(2) + 'M' : x >= 1e3 ? '$' + (x / 1e3).toFixed(1) + 'k' : '$' + x.toFixed(0);
  const fNum = (x, d) => (x == null || !isFinite(x)) ? '–' : (x < 0 && +Math.abs(x).toFixed(d) ? MI : '') + Math.abs(x).toFixed(d).replace('.', ',');
  const fPct = (x, d = 1, sign = true) => {
    if (x == null || !isFinite(x)) return '–';
    const r = Math.abs(x).toFixed(d);
    if (+r === 0) return r.replace('.', ',') + NB + '%';
    return (x < 0 ? MI : sign ? '+' : '') + r.replace('.', ',') + NB + '%';
  };
  const fSol = (x, d = 3, sign = false) => {
    if (x == null || !isFinite(x)) return '–';
    const r = Math.abs(x).toFixed(d);
    return (+r === 0 ? '' : x < 0 ? MI : sign ? '+' : '') + r.replace('.', ',') + NB + 'SOL';
  };
  const fPx = x => { if (!x) return '0'; const a = Math.abs(x); if (a >= 1) return x.toFixed(4); const d = Math.min(12, Math.max(2, -Math.floor(Math.log10(a)) + 3)); return x.toFixed(d); };
  const tone = x => x > 0 ? 'up' : x < 0 ? 'dn' : '';

  // ---- "ažurirano prije X s": the same rule as ui/apterm.freshness (older than 60 s = yellow) ----
  function age() {
    const now = Date.now() / 1000;
    for (const el of $$('.apx-age[data-ts]')) {
      const ts = +el.dataset.ts;
      if (!ts) continue;
      const a = Math.max(0, Math.floor(now - ts));
      const w = a < 60 ? a + ' s' : a < 3600 ? Math.floor(a / 60) + ' min' : Math.floor(a / 3600) + ' h';
      el.textContent = 'ažurirano prije ' + w;
      el.classList.toggle('old', a > 60);
    }
  }
  setInterval(age, 1000);

  // ---- parts that load when they come into view (or when their tab / accordion opens) ----
  const shown = el => !el.closest('[hidden]') && !el.closest('details:not([open])');
  const inView = el => { const r = el.getBoundingClientRect(); return r.bottom > -300 && r.top < innerHeight + 300; };
  const io = 'IntersectionObserver' in window ? new IntersectionObserver(es => {
    for (const e of es) if (e.isIntersecting) { io.unobserve(e.target); startLazy(e.target); }
  }, { rootMargin: '300px' }) : null;
  function watch(el) { if (!el || el._w) return; el._w = 1; if (io) io.observe(el); else startLazy(el); }
  function startLazy(el) {
    if (!el || el._on) return;
    el._on = 1;
    loadBox(el);
    const ev = +el.dataset.xEvery;
    if (ev) setInterval(() => { if (document.visibilityState === 'visible' && shown(el) && inView(el)) loadBox(el); }, ev * 1000);
  }
  function runScripts(el) {   // scripts of a part that arrived as HTML (e.g. the wallet value chart) run once
    for (const old of $$('script', el)) {
      if (old.type && old.type !== 'text/javascript' && old.type !== 'module') continue;
      const s = document.createElement('script');
      s.textContent = old.textContent;
      old.replaceWith(s);
    }
  }
  async function loadBox(el, url) {
    if (el._busy) return;
    el._busy = 1;
    try {
      const r = await fetch(url || el.dataset.xSrc, { cache: 'no-store', credentials: 'same-origin' });
      if (!r.ok) throw new Error(String(r.status));
      const h = await r.text();
      const first = !el._filled || url;
      if (!first && window.apPatch) {
        window.apPatch(el, h);
      } else {
        el.innerHTML = h || (el.dataset.empty ? '<p class=apx-empty></p>' : '');
        if (!h && el.dataset.empty) el.firstChild.textContent = el.dataset.empty;
        if (window.apSeen) window.apSeen(el);
        runScripts(el);
        el._filled = 1;
      }
      el.classList.remove('stale');
      after(el);
    } catch (e) {
      el.classList.add('stale');
      const a = $('.apx-age', el);
      if (a) a.classList.add('old');
    } finally { el._busy = 0; }
  }
  function after(el) {
    for (const c of $$('[data-x-src]', el)) if (shown(c)) watch(c);
    if (window.apOpen) window.apOpen(el);
    if (window.apTick) window.apTick();
    if (window.apcInit) window.apcInit();
    age();
    scrollHash();
  }

  // ---- tabs (Pozicije, Otvoreni nalozi, Povijest, Dnevnik) and the sub-tabs of "Koga pratimo" ----
  const PANES = ['pozicije', 'nalozi', 'povijest', 'dnevnik'];
  function showTab(id) {
    if (!PANES.includes(id)) return;
    for (const b of $$('.apx-tabs [data-tab]')) { b.classList.toggle('on', b.dataset.tab === id); b.setAttribute('aria-selected', b.dataset.tab === id); }
    for (const p of PANES) { const el = document.getElementById(p); if (el) el.hidden = p !== id; }
    const pane = document.getElementById(id);
    if (pane) { if (pane.dataset.xSrc) startLazy(pane); for (const c of $$('[data-x-src]', pane)) startLazy(c); }
    try { sessionStorage.setItem('apx.tab', id); } catch (e) { /* no storage */ }
  }
  function showSub(btn) {
    const card = btn.closest('section') || root;
    for (const b of $$('[data-sub]', card)) b.classList.toggle('on', b === btn);
    for (const p of $$('.apx-subp', card)) p.hidden = p.id !== btn.dataset.sub;
  }

  // ---- an address (#limiti after saving the limits, #poz-12 after a sale) that lives in a part not loaded yet ----
  const OSTALO = /^(limiti|cilj|stop|trigger|mcp|grok|pozivnice|postavljanje|exit-planovi|pregled|jos|zastita|sazetak|ev-|zastavice|fl-|pravila|fast|preshill|eventi|preporuke|vrijednost|zatvorene)/;
  function scrollHash() {
    const h = decodeURIComponent(location.hash.slice(1));
    if (!h || S.hashDone === h) return;
    const t = document.getElementById(h);
    if (t) {
      S.hashDone = h;
      for (let p = t; p && p !== document.body; p = p.parentElement) {
        if (p.tagName === 'DETAILS') p.open = true;
        if (p.classList && p.classList.contains('apx-pane') && p.hidden) showTab(p.id);
        if (p.classList && p.classList.contains('apx-subp') && p.hidden) { const b = $(`[data-sub="${p.id}"]`); if (b) showSub(b); }
      }
      setTimeout(() => t.scrollIntoView({ block: 'start' }), 80);
      return;
    }
    if (S.hashTried === h) return;
    S.hashTried = h;
    if (/^(poz-|pozicije)/.test(h)) showTab('pozicije');
    else if (/^nalozi/.test(h)) showTab('nalozi');
    else if (/^(povijest)/.test(h)) showTab('povijest');
    else if (/^(dnevnik)/.test(h)) showTab('dnevnik');
    else if (/^(pratim|prati-|pr-[wit]$)/.test(h)) startLazy($('#pratimo'));
    else if (/^(prijedlozi|pr-)/.test(h)) startLazy($('#kupiti'));
    else if (OSTALO.test(h) || h) { const o = $('#apx-ostalo'); if (o) { o.open = true; for (const c of $$('[data-x-src]', o)) startLazy(c); } }
  }

  // ---- the chart (TradingView Lightweight Charts, self-hosted, loaded after the first paint) ----
  let lib = null, chart = null, series = null, bands = null, plines = [], lastBar = null, cUnit = null, cBusy = false;
  const LINE = { entry: '#6d8cff', dca: '#b48cff', limit: '#b48cff', sl: '#ea3943', tp: '#16c784' };
  const BAND = { bottom: 'rgba(109,140,255,.13)', dca: 'rgba(180,140,255,.13)', top: 'rgba(240,185,11,.10)' };
  function loadLib() {
    if (lib) return lib;
    lib = new Promise((ok, no) => {
      const s = document.createElement('script');
      s.src = URLS.lwc; s.async = true;
      s.onload = () => ok(window.LightweightCharts); s.onerror = no;
      document.head.appendChild(s);
    });
    return lib;
  }
  class Bands {   // translucent rangedca zones behind the candles (a series primitive)
    constructor() {
      this.b = []; this.s = null; this.req = null;
      const self = this;
      this.view = { zOrder: () => 'bottom', renderer: () => ({ draw() {}, drawBackground(t) { self.paint(t); } }) };
    }
    attached(p) { this.s = p.series; this.req = p.requestUpdate; }
    detached() { this.s = null; }
    set(b) { this.b = b || []; if (this.req) this.req(); }
    updateAllViews() {}
    paneViews() { return [this.view]; }
    paint(target) {
      const s = this.s;
      if (!s || !this.b.length) return;
      target.useBitmapCoordinateSpace(sc => {
        const c = sc.context, w = sc.bitmapSize.width, r = sc.verticalPixelRatio, hr = sc.horizontalPixelRatio;
        for (const b of this.b) {
          const y1 = s.priceToCoordinate(b.hi), y2 = s.priceToCoordinate(b.lo);
          if (y1 == null || y2 == null) continue;
          const top = Math.round(Math.min(y1, y2) * r), h = Math.max(1, Math.round(Math.abs(y2 - y1) * r));
          c.fillStyle = BAND[b.kind] || 'rgba(109,140,255,.12)';
          c.fillRect(0, top, w, h);
          c.fillStyle = 'rgba(231,234,240,.55)';
          c.font = `${Math.round(10 * r)}px system-ui,sans-serif`;
          c.fillText(b.label || '', Math.round(6 * hr), top + Math.round(12 * r));
        }
      });
    }
  }
  async function chartInit() {
    const box = $('#apx-chart');
    if (!box || !S.m || !URLS.lwc) return;
    let LW;
    try { LW = await loadLib(); } catch (e) { box.innerHTML = '<p class=apx-empty>Graf se nije učitao (mreža).</p>'; return; }
    if (!chart) {
      box.innerHTML = '';
      const hm = d => d.toLocaleTimeString('hr-HR', { hour: '2-digit', minute: '2-digit' });
      chart = LW.createChart(box, {
        autoSize: true,
        layout: { background: { type: 'solid', color: 'transparent' }, textColor: '#8a93a6', fontSize: 11, attributionLogo: true },
        grid: { vertLines: { color: '#151b26' }, horzLines: { color: '#151b26' } },
        rightPriceScale: { borderColor: '#1d2431' },
        timeScale: { borderColor: '#1d2431', timeVisible: true, secondsVisible: false,
          tickMarkFormatter: (t, k) => { const d = new Date(t * 1000); return k < 3 ? d.toLocaleDateString('hr-HR', { day: '2-digit', month: '2-digit' }) : hm(d); } },
        crosshair: { mode: 0 },
        localization: { locale: 'hr-HR', timeFormatter: t => new Date(t * 1000).toLocaleString('hr-HR', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' }) },
      });
      series = chart.addCandlestickSeries({ upColor: '#16c784', downColor: '#ea3943', borderVisible: false, wickUpColor: '#16c784', wickDownColor: '#ea3943', priceLineColor: '#8a93a6' });
      bands = new Bands();
      series.attachPrimitive(bands);
    }
    await loadCandles();
  }
  async function loadCandles() {
    if (!series || !S.m || cBusy) return;
    cBusy = true;
    const ageEl = $('#apx-chart-age');
    try {
      const r = await fetch(`/pravi-trade/api/candles?m=${encodeURIComponent(S.m)}&tf=${S.tf}&u=${S.unit}`, { cache: 'no-store', credentials: 'same-origin' });
      if (!r.ok) throw new Error(String(r.status));
      const c = await r.json();
      cUnit = c.unit;
      for (const b of $$('[data-unit]')) b.classList.toggle('on', b.dataset.unit === c.unit);
      series.applyOptions({ priceFormat: { type: 'custom', minMove: c.unit === 'mc' ? 1 : 1e-12, formatter: c.unit === 'mc' ? fMc : fPx } });
      const data = c.candles || [];
      series.setData(data);
      lastBar = data.length ? { ...data[data.length - 1] } : null;
      for (const l of plines) series.removePriceLine(l);
      plines = (c.lines || []).map(l => series.createPriceLine({ price: l.value, color: LINE[l.kind] || '#8a93a6', lineWidth: l.kind === 'entry' ? 2 : 1, lineStyle: l.kind === 'entry' ? 0 : 2, axisLabelVisible: true, title: l.label }));
      bands.set(c.zones ? c.zones.bands : []);
      const zi = $('#apx-zinfo');
      if (zi) {
        const z = c.zones;
        zi.textContent = z ? `Zone raspona (rangedca, ${z.status || ''}) izračunate ${new Date(z.computed_ts * 1000).toLocaleTimeString('hr-HR', { hour: '2-digit', minute: '2-digit' })}` +
          (data.length ? '' : '') : (data.length ? '' : 'Za ovaj token još nemamo svijeće: snimke se skupljaju dok ga bot prati.');
      }
      zoneSelects(c.zones_mc);
      if (S.fit) { chart.timeScale().fitContent(); S.fit = false; }
      if (ageEl) { ageEl.dataset.ts = c.data_ts || 0; if (!c.data_ts) { ageEl.textContent = 'nema svijeća'; ageEl.classList.add('old'); } }
      age();
    } catch (e) {
      if (ageEl) { ageEl.textContent = 'graf: nema podataka'; ageEl.classList.add('old'); }
    } finally { cBusy = false; }
  }
  function liveBar(lv) {   // the last candle follows the tick between two candle reads
    if (!series || !lastBar) return;
    const v = cUnit === 'mc' ? lv.mcap : lv.price;
    if (!v) return;
    const step = STEP[S.tf] || 300, t = Math.floor(Date.now() / 1000 / step) * step;
    if (t === lastBar.time) { lastBar.high = Math.max(lastBar.high, v); lastBar.low = Math.min(lastBar.low, v); lastBar.close = v; }
    else if (t > lastBar.time) lastBar = { time: t, open: lastBar.close, high: Math.max(lastBar.close, v), low: Math.min(lastBar.close, v), close: v };
    else return;
    try { series.update({ ...lastBar }); } catch (e) { /* out of order */ }
  }
  function zoneSelects(z) {   // DCA levels: a rangedca zone fills the level as a market cap
    const opts = ['<option value="">zona…</option>'];
    for (const b of (z && z.bands) || []) {
      if (b.kind === 'bottom') { opts.push(`<option value="$${Math.round(b.hi)}">vrh dna ${fMc(b.hi)}</option>`, `<option value="$${Math.round(b.lo)}">dno ${fMc(b.lo)}</option>`); }
      if (b.kind === 'dca') opts.push(`<option value="$${Math.round(b.lo)}">DCA zona ${fMc(b.lo)}</option>`);
    }
    for (const s of $$('[data-zone]')) { const v = s.value; s.innerHTML = opts.join(''); s.value = v; s.disabled = opts.length < 2; }
  }

  // ---- the live tick: header, positions' MC / PnL, the last candle; a changed set of positions reloads the tables ----
  function setHeader(lv, ts) {
    const h = $('#apx-hdr');
    if (!h || h.dataset.mint !== S.m) return;
    const set = (k, txt, t) => { const el = $(`[data-f="${k}"]`, h); if (!el) return; el.textContent = txt; if (t !== undefined) el.className = t; };
    set('mcap', fMc(lv.mcap));
    set('ch_m5', fPct(lv.ch_m5), tone(lv.ch_m5)); set('ch_h1', fPct(lv.ch_h1), tone(lv.ch_h1)); set('ch_h24', fPct(lv.ch_h24), tone(lv.ch_h24));
    set('liq', fMc(lv.liq)); set('vol_h1', fMc(lv.vol_h1));
    if (lv.buys_m5 != null && lv.sells_m5) set('bs', `${lv.buys_m5}/${lv.sells_m5} (${fNum(lv.buys_m5 / lv.sells_m5, 2)})`);
    const a = $('.apx-age', h);
    if (a && ts) a.dataset.ts = ts;
  }
  function posRow(p, lv) {
    const row = document.querySelector(`.apx-pos[data-key="${CSS.escape(p.key)}"]`);
    if (!row || !lv || !lv.mcap) return;
    const mcEl = $('[data-f="mc"]', row), pnEl = $('[data-f="pnl"]', row);
    if (mcEl) mcEl.textContent = fMc(lv.mcap);
    if (!p.avg_mc || !pnEl) return;
    const pp = (lv.mcap / p.avg_mc - 1) * 100;
    let ps = 0;
    for (const [sin, held, lmc, sback] of p.lots || []) ps += sin * held * (lv.mcap / (lmc || p.avg_mc)) + sback - sin;
    pnEl.innerHTML = `${fPct(pp)}<small>${fSol(ps, 4, true)}</small>`;
    pnEl.className = `n apx-pnl ${tone(pp)}`;
  }
  function onTick(t) {
    if (!t) return;
    if (t.tok) Object.assign(S.live, t.tok);
    const lv = t.tok && t.tok[S.m];
    if (lv) {
      setHeader(lv, t.data_ts); liveBar(lv);
      const ca = $('#apx-chart-age');   // the last candle follows the tick: the chart is as fresh as the tick
      if (ca && lastBar && t.data_ts && +t.data_ts > +(ca.dataset.ts || 0)) ca.dataset.ts = t.data_ts;
    }
    for (const p of F.positions || []) posRow(p, S.live[p.token]);
    if (t.data_ts) for (const el of $$('.apx-live-age')) el.dataset.ts = t.data_ts;
    hints(); costEst();
    if (t.sig && S.tsig && t.sig !== S.tsig) refreshFirst();
    S.tsig = t.sig || S.tsig;
    age();
  }
  let es = null, poll = null, retryT = null;
  function stopLive() {
    if (es) { es.close(); es = null; }
    if (poll) { clearInterval(poll); poll = null; }
    if (retryT) { clearTimeout(retryT); retryT = null; }
  }
  function startPoll() {
    if (poll) return;
    const f = async () => {
      if (document.visibilityState !== 'visible') return;
      try { const r = await fetch('/pravi-trade/api/tick?m=' + encodeURIComponent(S.m || ''), { cache: 'no-store', credentials: 'same-origin' }); if (r.ok) onTick(await r.json()); } catch (e) { /* next time */ }
    };
    f();
    poll = setInterval(f, (URLS.poll_s || 5) * 1000);
  }
  function startLive() {
    stopLive();
    if (document.visibilityState !== 'visible') return;
    if (!window.EventSource) { startPoll(); return; }
    try { es = new EventSource('/pravi-trade/api/stream?m=' + encodeURIComponent(S.m || '')); } catch (e) { startPoll(); return; }
    es.addEventListener('tick', ev => { try { onTick(JSON.parse(ev.data)); } catch (e) { /* bad frame */ } });
    es.addEventListener('bye', () => { stopLive(); setTimeout(startLive, 300); });
    es.onerror = () => { stopLive(); startPoll(); retryT = setTimeout(startLive, 60000); };
  }
  document.addEventListener('visibilitychange', () => { if (document.visibilityState === 'visible') { startLive(); refreshFirst(); } else stopLive(); });

  async function getFirst(m, html, sym) {
    const r = await fetch(`/pravi-trade/api/first?m=${encodeURIComponent(m || '')}${html ? '&html=1' : ''}${sym ? '&s=' + encodeURIComponent(sym) : ''}`, { cache: 'no-store', credentials: 'same-origin' });
    if (!r.ok) throw new Error(String(r.status));
    return r.json();
  }
  function swapPart(sel, html) {   // replace one element of the panel from the server's HTML (by id / selector)
    const cur = $(sel); if (!cur || !html) return;
    const t = document.createElement('template'); t.innerHTML = html;
    const nxt = t.content.querySelector(sel);
    if (nxt && !cur.contains(document.activeElement)) cur.replaceWith(nxt);
  }
  let refreshing = false;
  async function refreshFirst() {
    if (refreshing) return;
    refreshing = true;
    try {
      const j = await getFirst(S.m, true);
      j.urls = URLS; F = j;
      const pos = $('#pozicije'), ord = $('#nalozi');
      if (pos && !pos.contains(document.activeElement)) pos.innerHTML = j.html.pos;
      if (ord && !ord.contains(document.activeElement)) ord.innerHTML = j.html.ord;
      const np = $('#apx-npos'), no = $('#apx-nord');
      if (np) np.textContent = (j.positions || []).length;
      if (no) no.textContent = (j.orders || []).length;
      swapPart('#apx-sell', j.html.side); swapPart('.apx-dca', j.html.side); swapPart('.apx-wal', j.html.side);
      for (const p of F.positions || []) posRow(p, S.live[p.token]);
      label();
      if (series) loadCandles();
    } catch (e) { /* the next tick tries again */ } finally { refreshing = false; }
  }
  setInterval(() => { if (document.visibilityState === 'visible') refreshFirst(); }, 30000);

  async function selectToken(m, sym) {
    if (!m || m === S.m) return;
    const f = form(), sol = f && f.elements.sol.value;
    S.m = m; S.fit = true;
    try { history.replaceState(null, '', '?m=' + encodeURIComponent(m)); } catch (e) { /* file:// */ }
    const box = $('#apx-chart'); if (box) box.dataset.m = m;
    try {
      const j = await getFirst(m, true, sym);
      j.urls = URLS; F = j;
      swapPart('#apx-hdr', j.html.hdr);
      const side = $('.apx-side');
      if (side && j.html.side) {
        const t = document.createElement('template'); t.innerHTML = j.html.side;
        const nxt = t.content.querySelector('.apx-side');
        if (nxt) side.replaceWith(nxt);
      }
      const f2 = form(); if (f2 && sol) f2.elements.sol.value = sol;
      setSide(S.side);
    } catch (e) { /* the header stays as it was */ }
    if (chart) loadCandles(); else chartInit();
    startLive();
    hints(); costEst(); label();
  }

  // ---- the order panel ----
  const form = () => $('#apx-buy');
  function setSide(side) {
    S.side = side === 'sell' ? 'sell' : 'buy';
    for (const b of $$('.apx-seg [data-side]')) { const on = b.dataset.side === S.side; b.classList.toggle('on', on); b.setAttribute('aria-selected', on); }
    const fb = $('#apx-buy'), fs = $('#apx-sell'), dca = $('.apx-dca');
    if (fb) fb.hidden = S.side !== 'buy';
    if (fs) fs.hidden = S.side !== 'sell';
    if (dca) dca.hidden = S.side !== 'buy';
    label();
  }
  const symNow = () => { const h = F.header; return (h && h.mint === S.m && h.sym) || (S.m ? S.m.slice(0, 4) + '…' : ''); };
  function label() {
    const f = form(), b = f && $('[data-go="buy"]', f);
    if (b) { const sol = (f.elements.sol.value || '').trim(); b.textContent = `Kupi ${sol ? sol.replace('.', ',') + ' SOL ' : ''}${symNow()}`.trim(); }
    const fs = $('#apx-sell'), bs = fs && $('[data-go="sell"]', fs);
    if (bs) { const fr = $('input[name=frac]:checked', fs); bs.textContent = `Prodaj ${fr ? Math.round(+fr.value * 100) + ' %' : ''} ${symNow()}`.trim(); }
  }
  function parseLvl(txt, base, kind) {   // the reading of league/auto.parse_level and ui/pravitrade._dca_level
    const s = (txt || '').trim().toLowerCase().replace(/\s/g, '').replace(',', '.');
    if (!s) return null;
    let m = s.match(/^\$?([0-9.]+)([kmb])?(mc|mcap)?$/);
    if (m && (kind === 'at' ? !s.endsWith('%') : (s[0] === '$' || m[2] || m[3]))) {
      let v = +m[1] * ({ k: 1e3, m: 1e6, b: 1e9 }[m[2]] || 1);
      if (kind === 'at' && !m[2] && v < 1000) v *= 1e3;
      return { mc: v, pct: base ? (v / base - 1) * 100 : null };
    }
    m = s.match(/^([+-]?[0-9.]+)%?$/);
    if (m && base) { let p = +m[1]; if ((kind === 'sl' || kind === 'at') && p > 0) p = -p; return { pct: p, mc: base * (1 + p / 100) }; }
    return null;
  }
  const mcNow = () => (S.live[S.m] && S.live[S.m].mcap) || (F.header && F.header.mint === S.m && F.header.mcap) || null;
  function hints() {
    const f = form(); if (!f) return;
    const now = mcNow();
    const at = parseLvl(f.elements.at && f.elements.at.value, now, 'at');
    const base = (at && at.mc) || now;
    const put = (k, txt) => { const el = $(`[data-hint="${k}"]`, f); if (el) el.textContent = txt; };
    const tp = parseLvl(f.elements.tp.value, base, 'tp');
    put('tp', tp ? (f.elements.tp.value.includes('%') || !/[$kmb]/i.test(f.elements.tp.value) ? '≈ MC ' + fMc(tp.mc) : '≈ ' + fPct(tp.pct, 0)) : (base ? '' : 'MC još nije poznat'));
    const slTxt = f.elements.sl.value || ((F.panel || {}).sl_default || '');
    const sl = parseLvl(slTxt, base, 'sl');
    put('sl', sl ? ((f.elements.sl.value ? '' : 'zadano · ') + (slTxt.includes('%') || !/[$kmb]/i.test(slTxt) ? '≈ MC ' + fMc(sl.mc) : '≈ ' + fPct(sl.pct, 0))) : '');
  }
  function costEst() {
    const f = form(), el = f && $('[data-cost]', f);
    if (!el) return;
    const P = F.panel || {};
    const sol = parseFloat((f.elements.sol.value || '').replace(',', '.'));
    const usd = sol * (P.sol_usd || 0);
    const liq = (S.live[S.m] && S.live[S.m].liq) || (F.header && F.header.mint === S.m && F.header.liq) || 0;
    if (!sol || !usd || !liq) { el.textContent = 'Procjena troška: treba iznos, tečaj SOL-a i likvidnost tokena.'; el.classList.remove('warn'); return; }
    // trade/cost.py (ui/apterm.cost_pct): round trip = 2 x fee_side + 2 x impact, impact = usd / (liq/2 + usd)
    const imp = usd / (liq / 2 + usd), sm = P.slip_max || 0.02;
    const fee = 2 * (P.fee_side || 0) * 100, slip = 2 * imp * 100, cost = fee + slip;
    const over = P.max_cost_pct && cost > P.max_cost_pct;
    const maxSol = P.sol_usd ? sm / (1 - sm) * liq / 2 / P.sol_usd : null;   // the largest stake with buy slippage <= 2 %
    el.textContent = `Procjena troška ≈ ${fNum(cost, 2)} % (naknade ${fNum(fee, 1)} % + klizanje ${fNum(slip, 2)} %) · ulog ≈ ${fNum(usd, 0)} $` +
      (imp > sm ? ` · klizanje kupnje ${fNum(imp * 100, 1)} % je iznad ${fNum(sm * 100, 0)} %` : '') +
      (maxSol ? ` · najviše ≈ ${fNum(maxSol, 2)} SOL uz ≤ ${fNum(sm * 100, 0)} %` : '') +
      (over ? ` · iznad limita troška ${fNum(P.max_cost_pct, 0)} %: swap bi bio odbijen` : '');
    el.classList.toggle('warn', imp > sm || !!over);
  }
  async function fillFrom(d, plain) {   // "Kupi" on a proposal / "U panel": only fills the form, never posts it
    if (d.token && d.token !== S.m) await selectToken(d.token, d.sym);
    const f = form(); if (!f) return;
    setSide('buy');
    f.elements.token.value = d.token || '';
    if (d.sol) f.elements.sol.value = d.sol;
    let note = $('#ap-pk-note');
    if (!plain) {
      if (f.elements.at) f.elements.at.value = '';
      f.elements.tp.value = d.tp || ''; f.elements.sl.value = d.sl || '';
      if (f.elements.exit) f.elements.exit.value = 'tpsl';
      let h = f.elements.prijedlog;
      if (!h) { h = document.createElement('input'); h.type = 'hidden'; h.name = 'prijedlog'; f.appendChild(h); }
      h.value = d.id;
      const tr = $('[data-trail]', f);
      if (tr) {
        tr.value = d.trail ? String(d.trail).replace('.', ',') + ' % (iz plana prijedloga)' : '';
        if (d.trail) { const det = tr.closest('details'); if (det) det.open = true; }
      }
      if (!note) { note = document.createElement('p'); note.id = 'ap-pk-note'; note.className = 'apx-note'; f.insertBefore(note, $('[data-cost]', f)); }
      note.textContent = `Prijedlog ${d.sym}: ulog ${d.sol} SOL, TP ${d.tp || '–'}, SL ${d.sl || 'zadani'}. Provjeri i dodirni Kupi.`;
    } else {
      if (f.elements.prijedlog) f.elements.prijedlog.remove();
      if (note) note.remove();
    }
    hints(); costEst(); label();
    if (matchMedia('(max-width:1023px)').matches) openSheet('buy');
    else { const go = $('[data-go="buy"]'); if (go) go.scrollIntoView({ behavior: 'smooth', block: 'nearest' }); }
  }
  function openSheet(side) { if (side) setSide(side); root.classList.add('sheet'); document.body.style.overflow = 'hidden'; }
  function closeSheet() { root.classList.remove('sheet'); document.body.style.overflow = ''; }
  document.addEventListener('keydown', e => { if (e.key === 'Escape' && root.classList.contains('sheet')) closeSheet(); });

  root.addEventListener('click', e => {
    const g = s => e.target.closest(s);
    let b;
    if ((b = g('[data-tab]'))) { showTab(b.dataset.tab); return; }
    if ((b = g('[data-sub]'))) { showSub(b); return; }
    if ((b = g('.apx-seg [data-side]'))) { setSide(b.dataset.side); return; }
    if ((b = g('[data-sol]'))) {
      const f = form(); if (!f) return;
      for (const c of $$('[data-sol]', f)) c.classList.toggle('on', c === b);
      if (b.dataset.sol) f.elements.sol.value = b.dataset.sol; else { f.elements.sol.focus(); f.elements.sol.select(); }
      costEst(); label(); return;
    }
    if ((b = g('[data-tp]'))) { const f = form(); if (f) { f.elements.tp.value = b.dataset.tp; hints(); } return; }
    if ((b = g('[data-sl]'))) { const f = form(); if (f) { f.elements.sl.value = b.dataset.sl; hints(); } return; }
    if ((b = g('[data-pk]'))) { e.preventDefault(); e.stopPropagation(); try { fillFrom(JSON.parse(b.dataset.pk)); } catch (x) { /* bad data */ } return; }
    if ((b = g('[data-fill]'))) { e.preventDefault(); try { fillFrom(JSON.parse(b.dataset.fill), true); } catch (x) { /* bad data */ } return; }
    if ((b = g('[data-sel]'))) {
      e.preventDefault();
      selectToken(b.dataset.sel, b.textContent.trim());
      const hd = $('#apx-hdr'); if (hd && hd.getBoundingClientRect().top < 0) hd.scrollIntoView({ behavior: 'smooth', block: 'start' });
      return;
    }
    if ((b = g('[data-edit]'))) {
      const t = document.getElementById(b.dataset.edit);
      if (!t) return;
      if (b.dataset.goto) { showTab('pozicije'); t.hidden = false; t.scrollIntoView({ behavior: 'smooth', block: 'center' }); }
      else t.hidden = !t.hidden;
      return;
    }
    if ((b = g('[data-page]'))) { const box = $('#povijest'); if (box) loadBox(box, b.dataset.page); return; }
    if ((b = g('[data-tf]'))) {
      S.tf = b.dataset.tf; S.fit = true;
      for (const x of $$('[data-tf]')) x.classList.toggle('on', x === b);
      try { localStorage.setItem('apx.tf', S.tf); } catch (x) { /* no storage */ }
      if (chart) loadCandles(); else chartInit();
      return;
    }
    if ((b = g('[data-unit]'))) {
      S.unit = b.dataset.unit; S.fit = true;
      try { localStorage.setItem('apx.unit', S.unit); } catch (x) { /* no storage */ }
      if (chart) loadCandles(); else chartInit();
      return;
    }
    if ((b = g('[data-sheet]'))) { openSheet(b.dataset.sheet); return; }
    if (g('[data-sheet-close]')) { closeSheet(); }
  });
  root.addEventListener('input', e => {
    const f = form();
    if (f && f.contains(e.target)) {
      if (e.target.name === 'sol') for (const c of $$('[data-sol]', f)) c.classList.toggle('on', c.dataset.sol === e.target.value);
      hints(); costEst(); label();
    }
    if (e.target.name === 'frac') label();
  });
  root.addEventListener('change', e => {
    if (e.target.matches('[data-zone]')) { const r = e.target.closest('form'); if (r && e.target.value) r.elements.lvl.value = e.target.value; }
    if (e.target.name === 'token' && form() && form().contains(e.target)) {
      const v = e.target.value.trim();
      if (/^[1-9A-HJ-NP-Za-km-z]{32,44}$/.test(v)) selectToken(v);
    }
    if (e.target.name === 'frac') label();
  });
  const ost = $('#apx-ostalo');
  if (ost) ost.addEventListener('toggle', () => { if (ost.open) for (const c of $$('[data-x-src]', ost)) startLazy(c); });

  // ---- start: lazy parts, the remembered tab, the panel's numbers; the chart and the stream after the first paint ----
  for (const el of $$('[data-x-src]')) if (shown(el)) watch(el);
  try { const t = sessionStorage.getItem('apx.tab'); if (t && t !== 'pozicije' && !location.hash) showTab(t); } catch (e) { /* no storage */ }
  for (const b of $$('[data-tf]')) b.classList.toggle('on', b.dataset.tf === S.tf);
  for (const b of $$('[data-unit]')) b.classList.toggle('on', b.dataset.unit === S.unit);
  setSide('buy'); hints(); costEst(); age();
  scrollHash();
  window.addEventListener('hashchange', () => { S.hashDone = null; S.hashTried = null; scrollHash(); });
  const later = fn => ('requestIdleCallback' in window) ? requestIdleCallback(fn, { timeout: 1500 }) : setTimeout(fn, 300);
  const go = () => { later(chartInit); setTimeout(startLive, 400); };
  if (document.readyState === 'complete') go(); else addEventListener('load', go);
})();
