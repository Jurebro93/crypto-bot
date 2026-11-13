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
  // 11.11. (Jure: "mali info button na svim stupcima"): the info buttons of the numbers written here, the words of the tables
  // (ui/apterm.COL_HELP); .tip is the site's own tooltip (ui/html.JS: hover, tap, keyboard focus)
  const HELP = F.help || {};
  const tipI = (k, label) => {
    const t = HELP[k];
    if (!t) return '';
    const e = s => String(s).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
    return `<span class="tip apx-i" tabindex=0 role=button aria-label="Što znači: ${e(label || k)}" data-tip="${e(t)}">i</span>`;
  };
  const S = { m: F.m || '', tf: '5m', unit: 'mc', side: 'buy', live: {}, tsig: null, fit: true };
  // 13.11. (Jure: "Svaki put kada osvježim stranicu autopilota na mobitelu, ona me centrira dolje na graf"): the address
  // a form sends back (#pozicije and #poz-12 after a sale or an SL/TP edit, #kupi-odmah after a buy, #grok-auto) stayed
  // in the URL, so every reload scrolled to it again: to the positions right under the chart. It is used once, right
  // after the form (S.hash), and taken out of the URL; a reload opens at the top, where Grok's positions are.
  const NAV = (() => {
    try { const n = performance.getEntriesByType('navigation')[0]; if (n) return n.type; } catch (e) { /* old browser */ }
    try { return performance.navigation.type === 1 ? 'reload' : ''; } catch (e) { return ''; }
  })();
  S.hash = NAV === 'reload' ? '' : decodeURIComponent(location.hash.slice(1));
  const dropHash = () => {
    if (location.hash) try { history.replaceState(history.state, '', location.pathname + location.search); } catch (e) { /* file:// */ }
  };
  dropHash();
  if (NAV === 'reload') {
    try { history.scrollRestoration = 'manual'; } catch (e) { /* not supported */ }
    let touched = false;   // the owner's own scroll after the reload wins over the jump to the top below
    for (const ev of ['touchstart', 'wheel', 'keydown', 'pointerdown']) addEventListener(ev, () => { touched = true; }, { once: true, passive: true });
    const top = () => { if (!touched && scrollY) scrollTo(0, 0); };
    top(); addEventListener('load', () => { top(); setTimeout(top, 300); });
  }
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
      el.textContent = (el.dataset.short && innerWidth < 480 ? 'prije ' : 'ažurirano prije ') + w;   // one row on a phone
      el.classList.toggle('old', a > (+el.dataset.stale || 60));   // data-stale: a source with its own cadence
    }
  }
  setInterval(age, 1000);

  // ---- parts that load when they come into view (or when their tab / accordion opens) ----
  const shown = el => !el.closest('[hidden]') && !el.closest('details:not([open])');
  const inView = el => { const r = el.getBoundingClientRect(); return r.bottom > -300 && r.top < innerHeight + 300; };
  // 11.11. (Jure: "kartice se ne otvaraju iz prvoga, kao da je lag"): a part used to load only 300 px before it came
  // into view, so scrolling down to "Postavke i dijagnostika" made "Što kupiti" and "Koga pratimo" above it grow by
  // hundreds of px in the moment of the tap, and the tap landed on something else. Now they load well ahead
  // (1200 px, and all of them once the page is idle after the first paint), and a closed box with lazy content is
  // fetched when it comes near the screen or a finger / the mouse is on its title, so it opens with its content.
  const io = 'IntersectionObserver' in window ? new IntersectionObserver(es => {
    for (const e of es) if (e.isIntersecting) { io.unobserve(e.target); startLazy(e.target); }
  }, { rootMargin: '1200px' }) : null;
  const prefetchBox = d => { if (d && !d._pf) { d._pf = 1; for (const c of $$('[data-x-src]', d)) startLazy(c); } };
  const ioBox = 'IntersectionObserver' in window ? new IntersectionObserver(es => {
    for (const e of es) if (e.isIntersecting) { ioBox.unobserve(e.target); prefetchBox(e.target.parentElement); }
  }, { rootMargin: '800px' }) : null;
  function warmBoxes() {   // closed <details> with a lazy part: near the screen, or a finger / pointer on the summary
    for (const d of $$('details')) {
      const s = d.querySelector(':scope>summary');
      if (!s || s._warm || !d.querySelector('[data-x-src]')) continue;
      s._warm = 1;
      const pf = () => prefetchBox(d);
      s.addEventListener('pointerenter', pf, { passive: true });
      s.addEventListener('touchstart', pf, { passive: true });
      s.addEventListener('focus', pf);
      if (ioBox) ioBox.observe(s);
    }
  }
  // what the user opened stays open when a block is rebuilt from the server (Uredi SL-TP, a <details>)
  function keepOpen(el, swap) {
    const ed = $$('.apx-edit:not([hidden])', el).map(x => x.id), dd = $$('details', el).map(d => [d.id, d.open]);
    swap();
    for (const id of ed) { const x = id && document.getElementById(id); if (x) x.hidden = false; }
    const now = $$('details', el);
    dd.forEach(([id, o], i) => { const d = id ? document.getElementById(id) : now[i]; if (d && d.open !== o) d.open = o; });
  }
  function watch(el) { if (!el || el._w) return; el._w = 1; if (io) io.observe(el); else startLazy(el); }
  // 11.11. (Jure: "prikazuj samo ono što ima zaključak ili nešto radi"): data-hide-empty = a card that exists only
  // while it has something. An empty answer hides it (or its [data-hide-wrap]) and it keeps being asked, hidden, so it
  // shows itself the moment it fills. No skeleton stays longer than 5 s: such a card is hidden, an always-shown one
  // (data-slow) says in one line that it is still coming.
  const hides = el => el.dataset.hideEmpty !== undefined;
  const wrapOf = el => el.closest('[data-hide-wrap]') || el;
  const isEmpty = h => !h.trim() || /^<p class=mut>u[čc]itavam…<\/p>$/i.test(h.trim());
  function startLazy(el) {
    if (!el || el._on) return;
    el._on = 1;
    loadBox(el);
    setTimeout(() => {
      if (el._filled || !$('.apx-skel', el)) return;
      if (hides(el)) wrapOf(el).hidden = true;
      else if (el.dataset.slow) { const p = document.createElement('p'); p.className = 'apx-one'; p.textContent = el.dataset.slow; el.replaceChildren(p); }
    }, 5000);
    const ev = +el.dataset.xEvery;
    if (ev) setInterval(() => { if (document.visibilityState === 'visible' && (hides(el) || (shown(el) && inView(el)))) loadBox(el); }, ev * 1000);
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
      if (hides(el)) {
        const empty = isEmpty(h);
        wrapOf(el).hidden = empty;
        if (empty) { el.replaceChildren(); el._filled = 0; return; }
      }
      const first = !el._filled || url;
      if (!first && window.apPatch) {
        // refused (a finger on it, a field in focus): again in a moment, not a whole interval later
        if (window.apPatch(el, h) === false) setTimeout(() => loadBox(el), 3000);
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
      // 11.11. (Jure: "Koga pratimo / Tokeni: ažurirano prije 38 min"): the badge says why it is old, and the part
      // is asked again in 10 s instead of a whole interval later
      el.classList.add('stale');
      const a = $('.apx-age', el);
      if (a) { a.classList.add('old'); a.title = 'Osvježavanje nije uspjelo (mreža ili poslužitelj); pokušavam ponovno.'; }
      if (!el._retry) el._retry = setTimeout(() => { el._retry = 0; loadBox(el); }, 10000);
    } finally { el._busy = 0; }
  }
  // back to the tab / the phone unlocked: every part already on the page is asked at once (the timers of a hidden tab
  // are frozen; a card showed "ažurirano prije 38 min" until its next minute came round)
  function wake() {
    if (document.visibilityState !== 'visible') return;
    for (const el of $$('[data-x-src]')) if (el._on && (hides(el) || (shown(el) && inView(el)))) loadBox(el);
  }
  document.addEventListener('visibilitychange', wake);
  addEventListener('pageshow', e => { if (e.persisted) wake(); });
  function after(el) {
    for (const c of $$('[data-x-src]', el)) if (shown(c)) watch(c); else if (hides(c)) startLazy(c);
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
  // 11.11.: "Uredi praćenja" (#pratim, #prati-<id> after a follow form) is under "Postavke" now
  const OSTALO = /^(limiti|cilj|stop|trigger|mcp|grok|pozivnice|postavljanje|exit-planovi|pregled|jos|zastita|sazetak|ev-|zastavice|fl-|pravila|fast|preporuke|zatvorene|pratim|prati-)/;
  function scrollHash() {
    const h = S.hash;   // 13.11.: the one-shot address of this navigation (never the URL's: it is dropped)
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
    else if (/^(pf-|pr-[wit]$)/.test(h)) startLazy($('#pratimo'));
    else if (/^(eventi|preshill|ps-)/.test(h)) { startLazy($('#apx-eventi')); startLazy($('#apx-preshill')); }
    else if (/^(prijedlozi|pr-)/.test(h)) startLazy($('#kupiti'));
    else if (OSTALO.test(h) || h) { const o = $('#apx-ostalo'); if (o) { o.open = true; for (const c of $$('[data-x-src]', o)) startLazy(c); } }
  }

  // ---- colours from the site's tokens (ui/html.py :root + ap.css), so the charts are in the brand's palette ----
  const T = {};
  function tokens() {
    let cs = null;
    try { cs = getComputedStyle(document.documentElement); } catch (e) { /* very old browser */ }
    const g = (n, d) => ((cs && cs.getPropertyValue(n)) || '').trim() || d;
    Object.assign(T, { fg: g('--fg', '#0b1220'), mut: g('--mut', '#5b6474'), line: g('--line', '#e8ebf2'), line2: g('--line2', '#cfd5e1'),
      acc: g('--acc', '#4f46e5'), cyan: g('--ap-cyan', '#0891b2'), up: g('--good', '#16a34a'), dn: g('--bad', '#dc2626'),
      warn: g('--warn', '#d97706'), font: (document.body && getComputedStyle(document.body).fontFamily) || 'Inter, system-ui, sans-serif' });
    // lines: my entry in the accent, DCA / limit orders in the logo's cyan, SL red, TP green; zones the same, translucent
    Object.assign(LINE, { entry: T.acc, dca: T.cyan, limit: T.cyan, sl: T.dn, tp: T.up });
    Object.assign(BAND, { bottom: rgba(T.acc, 0.08), dca: rgba(T.cyan, 0.11), top: rgba(T.warn, 0.09) });
    return T;
  }
  function rgba(c, a) {
    const m = /^#([0-9a-f]{3}|[0-9a-f]{6})$/i.exec(c || '');
    if (!m) return `rgba(79,70,229,${a})`;
    let h = m[1];
    if (h.length === 3) h = h.split('').map(x => x + x).join('');
    const n = parseInt(h, 16);
    return `rgba(${(n >> 16) & 255},${(n >> 8) & 255},${n & 255},${a})`;
  }
  const esc = s => String(s == null ? '' : s).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  const fUsd = (x, sign = false) => {
    if (x == null || !isFinite(x)) return '–';
    const a = Math.abs(x), s = x < 0 && a >= 0.005 ? MI : sign && a >= 0.005 ? '+' : '';
    return s + (a >= 1e6 ? fNum(a / 1e6, 2) + ' M $' : a >= 1e4 ? fNum(a / 1e3, 1) + 'k $' : fNum(a, 2) + ' $');
  };
  const tkey = t => (t && typeof t === 'object') ? `${t.year}-${String(t.month).padStart(2, '0')}-${String(t.day).padStart(2, '0')}` : String(t);

  // ---- the tooltip beside the cursor / finger, shared by both charts: mirrors at the chart's edges, a tap pins it,
  //      the arrow keys move it point by point (Shift: 10), Home / End, Escape hides it ----
  function placeTip(tip, box, x, y) {
    tip.hidden = false;
    const W = box.clientWidth, H = box.clientHeight, w = tip.offsetWidth, h = tip.offsetHeight, gap = 14;
    let left = x + gap, top = y + gap;
    if (left + w > W - 4) left = x - gap - w;
    if (left < 4) left = Math.max(4, Math.min(W - w - 4, x - w / 2));
    if (top + h > H - 4) top = y - gap - h;
    if (top < 4) top = Math.max(4, Math.min(H - h - 4, 4));
    tip.style.transform = `translate(${Math.round(left)}px,${Math.round(top)}px)`;
  }
  function interact(o) {   // o: box, chart, series(), n(), index(time), time(i), value(i), html(i), say(i)
    const tip = document.createElement('div');
    tip.className = 'apx-tip'; tip.hidden = true;
    o.box.appendChild(tip);
    let sr = o.box.nextElementSibling;
    if (!sr || !sr.classList.contains('apx-sr')) { sr = document.createElement('p'); sr.className = 'apx-sr'; sr.setAttribute('aria-live', 'polite'); o.box.after(sr); }
    const st = { k: -1, pin: false };
    const show = (i, x, y) => { tip.innerHTML = o.html(i); placeTip(tip, o.box, x, y); };
    const hide = () => { tip.hidden = true; };
    const at = (p, tap) => {
      const i = p && p.point && p.time != null ? o.index(p.time) : null;
      if (i == null) { if (!st.pin) hide(); return; }
      if (tap) st.pin = true;
      st.k = i; show(i, p.point.x, p.point.y);
    };
    o.chart.subscribeCrosshairMove(p => at(p, false));
    o.chart.subscribeClick(p => {   // a tap on a phone: the tooltip and the crosshair stay on that point
      at(p, true);
      const i = p && p.time != null ? o.index(p.time) : null;
      if (i != null) { try { o.chart.setCrosshairPosition(o.value(i), o.time(i), o.series()); } catch (e) { /* older library */ } }
    });
    const on = (ev, fn) => { o.box.addEventListener(ev, fn); offs.push(() => o.box.removeEventListener(ev, fn)); };
    const offs = [];
    on('pointermove', e => { if (e.pointerType === 'mouse') st.pin = false; });
    on('mouseleave', () => { if (!st.pin) hide(); });
    const go = i => {
      const ts = o.chart.timeScale(), r = ts.getVisibleLogicalRange();
      if (r && (i < r.from + 0.5 || i > r.to - 0.5)) { const w = r.to - r.from; ts.setVisibleLogicalRange({ from: i - w / 2, to: i + w / 2 }); }
      requestAnimationFrame(() => {
        const x = ts.timeToCoordinate(o.time(i)), y = o.series().priceToCoordinate(o.value(i));
        if (x == null || y == null) return;
        st.pin = true; st.k = i;
        try { o.chart.setCrosshairPosition(o.value(i), o.time(i), o.series()); } catch (e) { /* older library */ }
        show(i, x, y);
        sr.textContent = o.say(i);
      });
    };
    on('keydown', e => {
      const n = o.n();
      if (!n) return;
      let i = st.k < 0 ? n - 1 : st.k;
      if (e.key === 'ArrowLeft') i -= e.shiftKey ? 10 : (st.k < 0 ? 0 : 1);
      else if (e.key === 'ArrowRight') i += e.shiftKey ? 10 : (st.k < 0 ? 0 : 1);
      else if (e.key === 'Home') i = 0;
      else if (e.key === 'End') i = n - 1;
      else if (e.key === 'Escape') { st.pin = false; st.k = -1; hide(); try { o.chart.clearCrosshairPosition(); } catch (x) { /* older */ } return; }
      else return;
      e.preventDefault();
      go(Math.max(0, Math.min(n - 1, i)));
    });
    on('blur', () => { if (st.pin) { st.pin = false; hide(); try { o.chart.clearCrosshairPosition(); } catch (x) { /* older */ } } });
    return { hide, reset: () => { st.k = -1; st.pin = false; hide(); }, destroy: () => { for (const f of offs) f(); tip.remove(); } };
  }

  // ---- the chart (TradingView Lightweight Charts, self-hosted, loaded after the first paint) ----
  let lib = null, chart = null, series = null, bands = null, plines = [], lastBar = null, cUnit = null, cBusy = false;
  let cData = [], cVol = [], cIdx = new Map(), cLv = {}, cTip = null;
  const LINE = {}, BAND = {};
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
        const H = sc.mediaSize ? sc.mediaSize.height : sc.bitmapSize.height / r;
        c.font = `600 ${Math.round(11 * r)}px ${T.font || 'system-ui,sans-serif'}`;
        for (const b of this.b) {
          const y1 = s.priceToCoordinate(b.hi), y2 = s.priceToCoordinate(b.lo);
          if (y1 == null || y2 == null) continue;
          const t = Math.min(y1, y2), bt = Math.max(y1, y2);
          c.fillStyle = BAND[b.kind] || BAND.bottom;
          c.fillRect(0, Math.round(t * r), w, Math.max(1, Math.round((bt - t) * r)));
          // the name inside the band's visible part, top left. 11.11.: never under the TradingView logo, which the
          // library puts 10 px from the pane's bottom-left corner (35 x 19 px): a label that low starts right of it
          const vt = Math.max(0, t), vb = Math.min(H, bt);
          if (!b.label || vb - vt < 6) continue;
          const y = Math.min(vt + 13, vb - 2), x = y > H - 42 ? 54 : 8;
          c.fillStyle = T.mut || '#5b6474';
          c.fillText(b.label, Math.round(x * hr), Math.round(y * r));
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
      tokens();
      const hm = d => d.toLocaleTimeString('hr-HR', { hour: '2-digit', minute: '2-digit' });
      chart = LW.createChart(box, {
        autoSize: true,
        layout: { background: { type: 'solid', color: 'transparent' }, textColor: T.mut, fontSize: 12, fontFamily: T.font, attributionLogo: true },
        grid: { vertLines: { color: T.line }, horzLines: { color: T.line } },
        rightPriceScale: { borderColor: T.line },
        timeScale: { borderColor: T.line, timeVisible: true, secondsVisible: false,
          tickMarkFormatter: (t, k) => { const d = new Date(t * 1000); return k < 3 ? d.toLocaleDateString('hr-HR', { day: '2-digit', month: '2-digit' }) : hm(d); } },
        crosshair: { mode: 0, vertLine: { color: rgba(T.mut, 0.45), labelBackgroundColor: T.fg }, horzLine: { color: rgba(T.mut, 0.45), labelBackgroundColor: T.fg } },
        localization: { locale: 'hr-HR', timeFormatter: t => new Date(t * 1000).toLocaleString('hr-HR', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' }) },
      });
      series = chart.addCandlestickSeries({ upColor: T.up, downColor: T.dn, borderVisible: false, wickUpColor: T.up, wickDownColor: T.dn, priceLineColor: T.mut });
      bands = new Bands();
      series.attachPrimitive(bands);
      cTip = interact({ box, chart, series: () => series, n: () => cData.length, index: t => cIdx.get(tkey(t)),
        time: i => cData[i].time, value: i => cData[i].close, html: candleTip, say: candleSay });
    }
    await loadCandles();
  }
  // the candle's tooltip: time, open / high / low / close (MC or price, as the switch), the candle's change, its
  // volume when we have one, and how far its close is from my average entry, my SL and my TP
  function candleTip(i) {
    const b = cData[i];
    if (!b) return '';
    const f = cUnit === 'mc' ? fMc : fPx, ch = b.open ? (b.close / b.open - 1) * 100 : null;
    const row = (k, v, cls) => `<div class=r><span>${k}</span><span${cls ? ' class=' + cls : ''}>${v}</span></div>`;
    const when = new Date(b.time * 1000).toLocaleString('hr-HR', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' });
    let h = `<b>${esc(when)} · svijeća ${esc(S.tf)}${cUnit === 'mc' ? ' · MC' : ' · cijena'}</b><div class=g>` +
      row('Otvaranje', f(b.open)) + row('Najviše', f(b.high)) + row('Najniže', f(b.low)) + row('Zatvaranje', f(b.close)) +
      '</div>' + row('Promjena', fPct(ch, 2), tone(ch));
    const v = cVol[i];
    if (v != null) h += row('Volumen', v > 0 ? fMc(v) : '$0');
    let ex = '';
    if (cLv.entry) { const p = (b.close / cLv.entry - 1) * 100; ex += row('Od mog ulaza', fPct(p), tone(p)); }
    if (cLv.sl) ex += row('Do SL-a', fPct((cLv.sl / b.close - 1) * 100), 'dn');
    if (cLv.tp) ex += row('Do TP-a', fPct((cLv.tp / b.close - 1) * 100), 'up');
    return h + (ex ? '<hr>' + ex : '');
  }
  function candleSay(i) {
    const b = cData[i];
    if (!b) return '';
    const f = cUnit === 'mc' ? fMc : fPx;
    return `${new Date(b.time * 1000).toLocaleString('hr-HR', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' })}: ` +
      `otvaranje ${f(b.open)}, najviše ${f(b.high)}, najniže ${f(b.low)}, zatvaranje ${f(b.close)}, ${fPct(b.open ? (b.close / b.open - 1) * 100 : null, 2)}`;
  }
  let cAgain = false;
  async function loadCandles() {
    if (!series || !S.m) return;
    // 11.11. (Jure: "klik na ime tokena otvori gore njegov graf"): a token picked while candles were loading used to
    // be skipped (the chart kept the old token's candles until the next refresh), and a late answer for the old
    // token could land after the new one's: now the newest pick is loaded right after, and an old answer is dropped
    if (cBusy) { cAgain = true; return; }
    cBusy = true;
    const ageEl = $('#apx-chart-age'), want = [S.m, S.tf, S.unit];
    try {
      const r = await fetch(`/pravi-trade/api/candles?m=${encodeURIComponent(want[0])}&tf=${want[1]}&u=${want[2]}`, { cache: 'no-store', credentials: 'same-origin' });
      if (!r.ok) throw new Error(String(r.status));
      const c = await r.json();
      if (want.join() !== [S.m, S.tf, S.unit].join()) { cAgain = true; return; }
      cUnit = c.unit;
      for (const b of $$('[data-unit]')) b.classList.toggle('on', b.dataset.unit === c.unit);
      series.applyOptions({ priceFormat: { type: 'custom', minMove: c.unit === 'mc' ? 1 : 1e-12, formatter: c.unit === 'mc' ? fMc : fPx } });
      const data = c.candles || [];
      series.setData(data);
      cData = data.slice(); cVol = (c.vol || []).slice(); cIdx = new Map(data.map((b, i) => [String(b.time), i]));
      cLv = {};   // my lines for the tooltip: the first of each kind (live positions come first)
      for (const l of c.lines || []) if (['entry', 'sl', 'tp'].includes(l.kind) && cLv[l.kind] == null) cLv[l.kind] = l.value;
      if (cTip) cTip.reset();
      lastBar = data.length ? { ...data[data.length - 1] } : null;
      for (const l of plines) series.removePriceLine(l);
      plines = (c.lines || []).map(l => series.createPriceLine({ price: l.value, color: LINE[l.kind] || T.mut, lineWidth: l.kind === 'entry' ? 2 : 1, lineStyle: l.kind === 'entry' ? 0 : 2, axisLabelVisible: true, title: l.label }));
      bands.set(c.zones ? c.zones.bands : []);
      const zi = $('#apx-zinfo');
      if (zi) {
        const z = c.zones;
        zi.textContent = z ? `Zone raspona (rangedca, ${z.status || ''}) izračunate ${new Date(z.computed_ts * 1000).toLocaleTimeString('hr-HR', { hour: '2-digit', minute: '2-digit' })}`
          : (data.length ? '' : 'Za ovaj token još nemamo svijeće: snimke se skupljaju dok ga bot prati.');
      }
      zoneSelects(c.zones_mc);
      if (S.fit) { chart.timeScale().fitContent(); S.fit = false; }
      if (ageEl) { ageEl.dataset.ts = c.data_ts || 0; if (!c.data_ts) { ageEl.textContent = 'nema svijeća'; ageEl.classList.add('old'); } }
      age();
    } catch (e) {
      if (ageEl) { ageEl.textContent = 'graf: nema podataka'; ageEl.classList.add('old'); }
    } finally {
      cBusy = false;
      if (cAgain) { cAgain = false; loadCandles(); }
    }
  }
  function liveBar(lv) {   // the last candle follows the tick between two candle reads
    if (!series || !lastBar) return;
    const v = cUnit === 'mc' ? lv.mcap : lv.price;
    if (!v) return;
    const step = STEP[S.tf] || 300, t = Math.floor(Date.now() / 1000 / step) * step;
    if (t === lastBar.time) { lastBar.high = Math.max(lastBar.high, v); lastBar.low = Math.min(lastBar.low, v); lastBar.close = v; }
    else if (t > lastBar.time) lastBar = { time: t, open: lastBar.close, high: Math.max(lastBar.close, v), low: Math.min(lastBar.close, v), close: v };
    else return;
    try { series.update({ ...lastBar }); } catch (e) { return; /* out of order */ }
    const n = cData.length;   // the tooltip reads the same candle the chart shows
    if (n && cData[n - 1].time === lastBar.time) cData[n - 1] = { ...lastBar };
    else { cData.push({ ...lastBar }); cVol.push(null); cIdx.set(String(lastBar.time), cData.length - 1); }
  }
  function zoneSelects(z) {   // DCA levels: a rangedca zone fills the level as a market cap
    const opts = ['<option value="">zona…</option>'];
    for (const b of (z && z.bands) || []) {
      if (b.kind === 'bottom') { opts.push(`<option value="$${Math.round(b.hi)}">vrh dna ${fMc(b.hi)}</option>`, `<option value="$${Math.round(b.lo)}">dno ${fMc(b.lo)}</option>`); }
      if (b.kind === 'dca') opts.push(`<option value="$${Math.round(b.lo)}">DCA zona ${fMc(b.lo)}</option>`);
    }
    for (const s of $$('[data-zone]')) { const v = s.value; s.innerHTML = opts.join(''); s.value = v; s.disabled = opts.length < 2; }
  }

  // ---- "Portfelj" (the card under the token's chart): the numbers (ukupno, slobodno, u pozicijama, danas, ukupni PnL)
  //      and one chart: "Vrijednost" = the wallet's value over time (live) or the running sum of the demo account's
  //      closed trades (paper), "PnL po danima" = bars of each day's closed trades (green profit, red loss) and the
  //      line of their running sum. Uživo / Paper, SOL / $, 7 / 30 / 90 days. GET /pravi-trade/api/portfelj and
  //      /pravi-trade/api/pnl-days, fetched after the first paint and every minute while the card is on screen ----
  const PN = { m: 'live', u: 'sol', d: 30, v: 'val', kind: '', chart: null, s1: null, s2: null, j: null, p: null,
    idx: new Map(), busy: false, tip: null, LW: null };
  try {
    PN.m = localStorage.getItem('apx.pm') === 'paper' ? 'paper' : 'live';
    PN.u = localStorage.getItem('apx.pu') === 'usd' ? 'usd' : 'sol';
    PN.d = [7, 30, 90].includes(+localStorage.getItem('apx.pd')) ? +localStorage.getItem('apx.pd') : 30;
    PN.v = localStorage.getItem('apx.pv') === 'days' ? 'days' : 'val';
  } catch (e) { /* private mode */ }
  function pnlSave() {
    try { localStorage.setItem('apx.pm', PN.m); localStorage.setItem('apx.pu', PN.u); localStorage.setItem('apx.pd', PN.d); localStorage.setItem('apx.pv', PN.v); } catch (e) { /* no storage */ }
  }
  function pnlMark() {
    for (const b of $$('[data-pm]')) b.classList.toggle('on', b.dataset.pm === PN.m);
    for (const b of $$('[data-pu]')) b.classList.toggle('on', b.dataset.pu === PN.u);
    for (const b of $$('[data-pd]')) b.classList.toggle('on', +b.dataset.pd === PN.d);
    for (const b of $$('[data-pv]')) b.classList.toggle('on', b.dataset.pv === PN.v);
  }
  const pv = r => PN.u === 'usd' ? r.pnl_usd : r.pnl_sol;
  const pcum = r => PN.u === 'usd' ? r.cum_usd : r.cum_sol;
  const pfmt = (x, sign = true) => PN.u === 'usd' ? fUsd(x, sign) : fSol(x, 3, sign);
  const getJ = async u => { const r = await fetch(u, { cache: 'no-store', credentials: 'same-origin' }); if (!r.ok) throw new Error(String(r.status)); return r.json(); };
  async function pnlLoad() {
    const box = $('#apx-pchart');
    if (!box || PN.busy || !URLS.lwc) return;
    PN.busy = true;
    pnlMark();
    try {
      const q = `m=${PN.m}&d=${PN.d}`;
      const [LW, p, j] = await Promise.all([loadLib(), getJ('/pravi-trade/api/portfelj?' + q),
        PN.v === 'days' ? getJ('/pravi-trade/api/pnl-days?' + q) : Promise.resolve(null)]);
      PN.LW = LW; PN.p = p; if (j) PN.j = j;
      kpiDraw(); pnlDraw();
    } catch (e) {
      pnlChart('');
      box.innerHTML = '<p class=apx-empty>Portfelj se nije učitao. Pokušat ću ponovno za minutu.</p>';
    } finally { PN.busy = false; }
  }
  // the numbers above the chart: the same words as the server's first HTML (ui/apterm._kpi_cells)
  function kpiDraw() {
    const el = $('#apx-kpi'), p = PN.p;
    if (!el || !p) return;
    const k = p.kpi || {}, s = (x, d = 3, sg = false) => x == null ? '–' : fSol(x, d, sg), u = (x, sg = false) => x == null ? '' : fUsd(x, sg);
    const cells = [];
    if (p.mode === 'live') {
      cells.push(['Ukupno', s(k.value_sol), k.value_usd != null ? '≈ ' + u(k.value_usd) : '', '']);
      cells.push(['Slobodno', s(k.free_sol), 'SOL u walletu', '']);
      cells.push(['U pozicijama', s(k.pos_sol), `${k.pos_n || 0} otvorenih`, '']);
    } else {
      cells.push(['U pozicijama', s(k.pos_sol), `${k.pos_n || 0} otvorenih · ${u(k.pos_usd)}`, '']);
      cells.push(['Otvoreno (nerealizirano)', u(k.unreal_usd, true) || '–', 'po živoj cijeni', tone(k.unreal_usd)]);
    }
    cells.push(['Danas', s(k.today_sol, 4, true), (u(k.today_usd, true) + ' · zatvoreno danas').replace(/^ · /, ''), tone(k.today_sol != null ? k.today_sol : k.today_usd)]);
    if (p.mode === 'paper' && (k.n_closed || 0) < 10) cells.push(['Ukupni PnL', s(k.total_sol, 3, true), `u procjeni: ${k.n_closed || 0} zatvorenih (n < 10)`, '']);
    else cells.push(['Ukupni PnL', s(k.total_sol, 3, true), k.total_pct != null ? fPct(k.total_pct) : u(k.total_usd, true), tone(k.total_sol != null ? k.total_sol : k.total_usd)]);
    el.innerHTML = cells.map(([l, v, sm, t]) => `<div><span>${esc(l)}${tipI(l)}</span><b class="${t}">${v}</b><small>${esc(sm)}</small></div>`).join('');
    const a = $('#apx-port-age');
    if (a) { a.dataset.ts = k.at || p.ts || 0; age(); }
  }
  // one chart in the box at a time: made anew when the view changes (its series differ)
  function pnlChart(kind) {
    if (PN.kind === kind && PN.chart) return;
    if (PN.tip) { PN.tip.destroy(); PN.tip = null; }
    if (PN.chart) { PN.chart.remove(); PN.chart = null; }
    PN.kind = kind;
    const box = $('#apx-pchart');
    if (!kind || !box) return;
    box.innerHTML = '';
    tokens();
    const days = kind === 'days', hm = d => d.toLocaleTimeString('hr-HR', { hour: '2-digit', minute: '2-digit' });
    const dd = s => { const [, m, d] = s.split('-'); return `${d}.${m}.`; };
    PN.chart = PN.LW.createChart(box, {
      autoSize: true,
      // the TradingView logo is off here: the attribution is the text line under the chart (as under the candles)
      layout: { background: { type: 'solid', color: 'transparent' }, textColor: T.mut, fontSize: 12, fontFamily: T.font, attributionLogo: false },
      grid: { vertLines: { visible: false }, horzLines: { color: T.line } },
      rightPriceScale: { borderColor: T.line, scaleMargins: { top: 0.12, bottom: 0.08 } },
      timeScale: days ? { borderColor: T.line, fixLeftEdge: true, fixRightEdge: true, lockVisibleTimeRangeOnResize: true, tickMarkFormatter: tm => dd(tkey(tm)) }
        : { borderColor: T.line, fixLeftEdge: true, fixRightEdge: true, timeVisible: true, secondsVisible: false,
          tickMarkFormatter: (t, k) => { const d = new Date(t * 1000); return k < 3 ? d.toLocaleDateString('hr-HR', { day: '2-digit', month: '2-digit' }) : hm(d); } },
      crosshair: { mode: 0, vertLine: { color: rgba(T.mut, 0.45), labelBackgroundColor: T.fg }, horzLine: { color: rgba(T.mut, 0.45), labelBackgroundColor: T.fg } },
      handleScroll: false, handleScale: false,   // a fixed span: the page scrolls under a finger, a tap shows the point
      localization: { locale: 'hr-HR', timeFormatter: days ? (tm => { const [y, m, d] = tkey(tm).split('-'); return `${d}.${m}.${y}.`; })
        : (t => new Date(t * 1000).toLocaleString('hr-HR', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' })) },
    });
    if (days) {
      PN.s1 = PN.chart.addHistogramSeries({ base: 0, priceLineVisible: false, lastValueVisible: false });
      PN.s2 = PN.chart.addLineSeries({ color: T.acc, lineWidth: 2, priceLineVisible: false, lastValueVisible: false, crosshairMarkerRadius: 4 });
      PN.tip = interact({ box, chart: PN.chart, series: () => PN.s2, n: () => (PN.j ? PN.j.rows.length : 0),
        index: tm => PN.idx.get(tkey(tm)), time: i => PN.j.rows[i].day, value: i => pcum(PN.j.rows[i]) || 0, html: pnlTip, say: pnlSay });
    } else {
      PN.s1 = PN.chart.addAreaSeries({ lineColor: T.acc, lineWidth: 2, topColor: rgba(T.acc, 0.16), bottomColor: rgba(T.acc, 0.01),
        priceLineVisible: false, lastValueVisible: true, crosshairMarkerRadius: 4 });
      PN.s2 = null;
      PN.tip = interact({ box, chart: PN.chart, series: () => PN.s1, n: () => valRows().length,
        index: tm => PN.idx.get(tkey(tm)), time: i => valRows()[i].t, value: i => valOf(valRows()[i]) || 0, html: valTip, say: valSay });
    }
  }
  const valRows = () => ((PN.p && PN.p.series) || []).filter(r => valOf(r) != null);
  const valOf = r => PN.u === 'usd' ? r.u : r.v;
  function pnlDraw() {
    if (!PN.LW) return;
    pnlMark();
    if (PN.v === 'days') daysDraw(); else valDraw();
  }
  function pnlEmpty(msg) {
    pnlChart('');
    const box = $('#apx-pchart');
    if (box) box.innerHTML = `<p class=apx-empty>${esc(msg)}</p>`;
  }
  function valDraw() {
    const p = PN.p, sum = $('#apx-psum'), note = $('#apx-pnote');
    if (!p) return;
    let rows = valRows();
    if (!rows.length && (p.series || []).length) { PN.u = PN.u === 'usd' ? 'sol' : 'usd'; pnlMark(); rows = valRows(); }   // no rate
    const live = p.mode === 'live';
    if (note) note.textContent = p.note || '';
    if (sum) {
      const a = rows[0], z = rows[rows.length - 1], ch = a && z ? valOf(z) - valOf(a) : null;
      sum.innerHTML = rows.length > 1 ? `<span><b class=${tone(ch)}>${pfmt(ch)}</b>${live ? 'promjena vrijednosti' : 'zatvoreno'} u ${p.days} d${tipI('promjena')}</span>` : '';
    }
    if (rows.length < 2) {
      pnlEmpty(live ? 'Još nema dovoljno snimki vrijednosti walleta za graf (jedna svakih 5 min).' : `Demo račun nema zatvorenih tradeova u zadnjih ${p.days} dana.`);
      return;
    }
    pnlChart('val');
    const usd = PN.u === 'usd';
    PN.s1.applyOptions({ priceFormat: { type: 'custom', minMove: usd ? 0.01 : 0.0001, formatter: x => usd ? fUsd(x) : fNum(x, Math.abs(x) >= 10 ? 1 : 3) } });
    PN.idx = new Map(rows.map((r, i) => [String(r.t), i]));
    PN.s1.setData(rows.map(r => ({ time: r.t, value: valOf(r) })));
    // deposits and withdrawals on the live line (a marker, not a profit)
    try {
      PN.s1.setMarkers(live ? rows.filter(r => r.flow).map(r => ({ time: r.t, position: 'belowBar', color: T.acc, shape: r.flow > 0 ? 'arrowUp' : 'arrowDown',
        text: r.t === rows[0].t ? '' : r.flow > 0 ? 'uplata' : 'isplata' })) : []);   // the first point's word would be cut at the edge
    } catch (e) { /* older library */ }
    PN.tip.reset();
    PN.chart.timeScale().fitContent();
  }
  // a point of the value line: time, the value in SOL and $, PnL against the money put in, change since the span's
  // first point; paper: the running sum and the trade that closed there
  function valTip(i) {
    const rows = valRows(), r = rows[i], p = PN.p;
    if (!r) return '';
    const row = (k, v, cls) => `<div class=r><span>${k}</span><span${cls ? ' class=' + cls : ''}>${v}</span></div>`;
    const when = new Date(r.t * 1000).toLocaleString('hr-HR', { weekday: 'short', day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' });
    const ch = valOf(r) - valOf(rows[0]);
    let h = `<b>${esc(when)}</b>`;
    if (p.mode === 'live') {
      h += row('Vrijednost', fSol(r.v, 3)) + (r.u != null ? row('u $', fUsd(r.u)) : '') +
        row('PnL prema uplatama', fSol(r.pnl, 3, true), tone(r.pnl)) + (r.flow ? row(r.flow > 0 ? 'Uplata' : 'Isplata', fSol(Math.abs(r.flow), 3)) : '');
    } else {
      h += row('Zbroj zatvorenih', pfmt(valOf(r)), tone(valOf(r))) + row('Zatvoren', `${esc(r.sym)} ${fPct(r.pct)}`, tone(r.pct)) +
        row('PnL tradea', fUsd(r.pnl, true), tone(r.pnl));
    }
    return h + '<hr>' + row(`Od ${new Date(rows[0].t * 1000).toLocaleDateString('hr-HR', { day: '2-digit', month: '2-digit' })}`, pfmt(ch), tone(ch));
  }
  function valSay(i) {
    const r = valRows()[i];
    return r ? `${new Date(r.t * 1000).toLocaleString('hr-HR')}: ${pfmt(valOf(r), false)}` : '';
  }
  function daysDraw() {
    const j = PN.j, sum = $('#apx-psum'), note = $('#apx-pnote');
    if (!j) { pnlLoad(); return; }
    const t = j.total || {};
    let noRate = false;
    if (t.n && (PN.u === 'usd' ? t.pnl_usd : t.pnl_sol) == null) { PN.u = PN.u === 'usd' ? 'sol' : 'usd'; noRate = true; pnlMark(); }   // no SOL rate
    const tot = PN.u === 'usd' ? t.pnl_usd : t.pnl_sol, who = j.mode === 'live' ? 'uživo' : 'paper';
    if (sum) {
      sum.innerHTML = t.n ? `<span><b class=${tone(tot)}>${pfmt(tot)}</b>${j.days} d ${who}</span>` +
        // fewer than 10 closed trades: a win rate is no conclusion yet (11.11., Jure)
        `<span><b>${t.n}</b>zatvorenih${tipI('zatvorenih')}</span><span><b>${t.n < 10 ? 'u procjeni' : t.win_rate == null ? '–' : fNum(t.win_rate, 0) + NB + '%'}</b>win rate${t.n < 10 ? ' (n &lt; 10)' : ''}${tipI('win rate')}</span>` +
        `<span><b>${t.days_plus}/${t.days_minus}</b>dana u plusu / minusu${tipI('dana u plusu / minusu')}</span>` +
        (j.fees_known && t.fees_sol != null ? `<span><b>${fSol(t.fees_sol, 4)}</b>naknade${tipI('naknade')}</span>` : '') +
        (noRate ? '<span>tečaj SOL-a nije poznat: prikaz u drugoj jedinici</span>' : '') : '';
    }
    if (note) note.textContent = j.note || '';
    if (!t.n) { pnlEmpty(`Nema zatvorenih tradeova (${who}) u zadnjih ${j.days} dana.`); return; }
    pnlChart('days');
    const usd = PN.u === 'usd';
    const pf = { type: 'custom', minMove: usd ? 0.01 : 0.0001, formatter: x => usd ? fUsd(x) : fNum(x, Math.abs(x) >= 10 ? 1 : 3) };
    PN.s1.applyOptions({ priceFormat: pf });
    PN.s2.applyOptions({ priceFormat: pf, color: T.acc });
    PN.idx = new Map(j.rows.map((r, i) => [r.day, i]));
    PN.s1.setData(j.rows.map(r => {
      const v = pv(r);
      return r.n && v != null ? { time: r.day, value: v, color: v > 0 ? T.up : v < 0 ? T.dn : T.mut } : { time: r.day };
    }));
    PN.s2.setData(j.rows.map(r => ({ time: r.day, value: pcum(r) || 0 })));
    PN.tip.reset();
    PN.chart.timeScale().fitContent();
  }
  function pnlDay(r) {
    const [y, m, d] = r.day.split('-');
    return new Date(+y, +m - 1, +d).toLocaleDateString('hr-HR', { weekday: 'short', day: '2-digit', month: '2-digit', year: 'numeric' });
  }
  // the day's tooltip: date, PnL in SOL and $, closed trades, win rate, best and worst trade, fees (when known)
  function pnlTip(i) {
    const r = PN.j && PN.j.rows[i];
    if (!r) return '';
    const row = (k, v, cls) => `<div class=r><span>${k}</span><span${cls ? ' class=' + cls : ''}>${v}</span></div>`;
    let h = `<b>${esc(pnlDay(r))}</b>`;
    if (!r.n) h += '<div class=w>Taj dan nije zatvoren nijedan trade.</div>';
    else {
      h += '<div class=g>' + row('PnL', fSol(r.pnl_sol, 4, true), tone(r.pnl_sol)) + row('PnL u $', fUsd(r.pnl_usd, true), tone(r.pnl_usd)) +
        row('Zatvoreno', String(r.n)) + row('Win rate', `${fNum(r.win_rate, 0)}${NB}% (${r.wins}/${r.n})`) + '</div>';
      if (r.best) h += row('Najbolji', `${esc(r.best.sym)} ${fPct(r.best.pct)}`, tone(r.best.pct));
      if (r.worst && r.n > 1) h += row('Najgori', `${esc(r.worst.sym)} ${fPct(r.worst.pct)}`, tone(r.worst.pct));
      if (PN.j.fees_known) h += row('Naknade', fSol(r.fees_sol, 4) + (r.fees_usd != null ? ' · ' + fUsd(r.fees_usd) : ''));
      else h += '<div class=w>Naknada i klizanje su već u PnL-u (simulacija).</div>';
    }
    const c = pcum(r);
    h += '<hr>' + row(`Zbroj od ${esc(PN.j.rows[0].day.split('-').reverse().slice(0, 2).join('.'))}.`, pfmt(c), tone(c));
    if (r.n && r.rate_now) h += '<div class=w>$ ↔ SOL po današnjem tečaju (taj dan bez snimke walleta).</div>';
    return h;
  }
  function pnlSay(i) {
    const r = PN.j && PN.j.rows[i];
    if (!r) return '';
    return r.n ? `${pnlDay(r)}: ${fSol(r.pnl_sol, 4, true)}, ${fUsd(r.pnl_usd, true)}, ${r.n} zatvorenih, win rate ${fNum(r.win_rate, 0)} %`
      : `${pnlDay(r)}: bez zatvorenih tradeova`;
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
  function posRow(p, lv) {   // the position's row and, when it is the selected token, the panel's "Tvoja pozicija"
    if (!lv || !lv.mcap) return;
    for (const row of $$(`[data-key="${CSS.escape(p.key)}"]`)) {
      const mcEl = $('[data-f="mc"]', row), pnEl = $('[data-f="pnl"]', row);
      if (mcEl) mcEl.textContent = fMc(lv.mcap);
      if (!p.avg_mc || !pnEl) continue;
      const pp = (lv.mcap / p.avg_mc - 1) * 100;
      let ps = 0;
      for (const [sin, held, lmc, sback] of p.lots || []) ps += sin * held * (lv.mcap / (lmc || p.avg_mc)) + sback - sin;
      pnEl.innerHTML = `${fPct(pp)}<small>${fSol(ps, 4, true)}</small>`;
      pnEl.className = `n apx-pnl ${tone(pp)}`;
    }
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
    // 11.11.: built anew on the server: a position opened a moment ago used to miss the 3-s cached view, and the
    // table showed it only at the next 30-s refresh
    if (t.sig && S.tsig && t.sig !== S.tsig) refreshFirst(true);
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

  async function getFirst(m, html, sym, fresh) {
    const r = await fetch(`/pravi-trade/api/first?m=${encodeURIComponent(m || '')}${html ? '&html=1' : ''}${sym ? '&s=' + encodeURIComponent(sym) : ''}${fresh ? '&fresh=1' : ''}`, { cache: 'no-store', credentials: 'same-origin' });
    if (!r.ok) throw new Error(String(r.status));
    return r.json();
  }
  // 11.11. (Jure: "Uredi SL-TP ... teško je fokusirati text box, kao da je laggy, ima bugove"): the tables were rebuilt
  // every 30 s (and on every changed tick) whenever the focus was not inside them, so an open editor lost what was
  // typed, and a press that landed during the swap went nowhere (Safari gives a pressed button no focus). A part with
  // an open editor, the focus, or a finger / the mouse pressed on it in the last 1.5 s is left as it is now; it is
  // rebuilt when the editor closes, or a moment after the press.
  const pressed = el => { for (let p = el; p; p = p.parentElement) if (Date.now() - (p._down || 0) < 1500) return true; return false; };
  const busy = el => el.contains(document.activeElement) || !!$('.apx-edit:not([hidden])', el) || pressed(el);
  root.addEventListener('pointerdown', e => { const p = e.target.closest('.apx-pane,.apx-side'); if (p) p._down = Date.now(); }, true);
  function swapPart(sel, html, force) {   // replace one element of the panel from the server's HTML (by id / selector)
    const cur = $(sel); if (!cur || !html) return;
    const t = document.createElement('template'); t.innerHTML = html;
    const nxt = t.content.querySelector(sel);
    if (nxt && (force || !busy(cur))) cur.replaceWith(nxt);
  }
  let refreshing = false;
  async function refreshFirst(fresh) {
    if (refreshing) { S.again = fresh ? 2 : (S.again || 1); return; }   // asked during a refresh: once more right after it
    refreshing = true;
    try {
      const j = await getFirst(S.m, true, '', fresh);
      j.urls = URLS; F = j;
      const pos = $('#pozicije'), ord = $('#nalozi');
      if (pos && !busy(pos)) { keepOpen(pos, () => { pos.innerHTML = j.html.pos; }); S.stale = 0; }
      else if (pos) {
        S.stale = 1;
        if (pressed(pos) && !S.retry) S.retry = setTimeout(() => { S.retry = 0; refreshFirst(); }, 1600);
      }
      // only the orders' table: the exit plans' kill switch under it (server-rendered, not in html.ord) stays
      if (ord && !busy(ord)) keepOpen(ord, () => { const t = $('.apx-tbl', ord); if (t) t.outerHTML = j.html.ord; else ord.insertAdjacentHTML('afterbegin', j.html.ord); });
      const np = $('#apx-npos'), no = $('#apx-nord');
      if (np) np.textContent = (j.positions || []).length;
      if (no) no.textContent = (j.orders || []).length;
      swapPart('#apx-sell', j.html.side); swapPart('.apx-dca', j.html.side); swapPart('.apx-wal', j.html.side);
      swapPart('#apx-mypos', j.html.side);
      if (S.flash && !S.stale) {   // a saved SL/TP: its row and card light up once with the new levels
        const c = $('#apx-mypos'), mine = c && $('input[name=id]', c);
        for (const el of [document.getElementById('poz-' + S.flash), mine && mine.value === S.flash ? c : null]) {
          if (el) { el.classList.remove('apx-saved'); void el.offsetWidth; el.classList.add('apx-saved'); }
        }
        S.flash = 0;
      }
      for (const p of F.positions || []) posRow(p, S.live[p.token]);
      label();
      if (series) loadCandles();
    } catch (e) { /* the next tick tries again */ } finally {
      refreshing = false;
      if (S.again) { const fr = S.again === 2; S.again = 0; setTimeout(() => refreshFirst(fr), 50); }
    }
  }
  setInterval(() => { if (document.visibilityState === 'visible') refreshFirst(); }, 30000);

  async function selectToken(m, sym) {
    if (!m || m === S.m) return;
    const f = form(), sol = f && f.elements.sol.value, foc = f && f.contains(document.activeElement) ? document.activeElement.name : '';
    S.m = m; S.fit = true;
    lastBar = null;   // the tick must not draw the new token's MC onto the old token's last candle
    try { history.replaceState(null, '', '?m=' + encodeURIComponent(m)); } catch (e) { /* file:// */ }
    const box = $('#apx-chart'); if (box) box.dataset.m = m;
    try {
      const j = await getFirst(m, true, sym || tokSym(m));
      if (S.m !== m) return;   // another token was picked meanwhile: its answer is the one shown
      j.urls = URLS; F = j;
      swapPart('#apx-hdr', j.html.hdr, true);
      const side = $('.apx-side');
      if (side && j.html.side) {
        const t = document.createElement('template'); t.innerHTML = j.html.side;
        const nxt = t.content.querySelector('.apx-side');
        if (nxt) side.replaceWith(nxt);
      }
      const f2 = form(); if (f2 && sol) f2.elements.sol.value = sol;
      if (f2 && foc && f2.elements[foc]) f2.elements[foc].focus({ preventScroll: true });   // typing / pasting goes on
      setSide(S.side);
    } catch (e) { /* the header stays as it was */ }
    if (chart) loadCandles(); else chartInit();
    startLive();
    hints(); costEst(); label(); tokCheck(true);
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
  // ---- the Token field: which token is that address (11.11., Jure: "da nisam krivo pastao adresu") ----
  // GET /pravi-trade/api/token (the server's DexScreener cache) 300 ms after typing or pasting. The Kupi button names
  // the token of the ADDRESS IN THE FIELD (it used to name the token picked before, whatever was pasted: real money)
  // and stays off until that name is known; a valid address of another token is picked, as a tap on its name
  const shortM = a => a && a.length > 9 ? a.slice(0, 4) + '…' + a.slice(-4) : (a || '');
  const tokSym = m => (S.tok && S.tok.found && S.tok.mint === m && S.tok.sym) || '';
  const fAge = s => s == null ? '–' : s < 3600 ? Math.max(1, Math.floor(s / 60)) + ' min' : s < 86400 ? Math.floor(s / 3600) + ' h' : Math.floor(s / 86400) + ' d';
  function tokState(f) {
    const v = ((f && f.elements.token && f.elements.token.value) || '').trim();
    if (!v) return { st: 'empty' };
    const t = S.tok;
    if (t && (t.q === v || t.mint === v)) return { st: t.found ? 'ok' : t.found === false ? 'bad' : 'down', sym: t.sym, t };
    const p = (F.positions || []).find(x => x.token === v), h = F.header;
    if (p && p.sym) return { st: 'ok', sym: p.sym };   // an open position's token: its name is ours already
    if (h && h.mint === v && h.sym && h.sym !== shortM(v)) return { st: 'ok', sym: h.sym };
    return { st: 'wait' };
  }
  const chartSym = () => { const h = F.header; return (h && h.mint === S.m && h.sym) || shortM(S.m); };
  const fieldMint = (f, s) => {   // the mint the buy goes to: the field's address (a link: what the server resolved it to)
    if (s.st !== 'ok') return '';
    const v = f.elements.token.value.trim();
    return (s.t && s.t.mint) || (/^[1-9A-HJ-NP-Za-km-z]{32,44}$/.test(v) ? v : '');
  };
  // the buy form's onsubmit (Kupi and Enter): only a named token; another token than the chart's after its own confirm
  // (then confirm_mismatch=1, the server refuses a difference without it); the general confirm names the field's token
  window.apBuyOk = f => {
    const s = tokState(f), mint = fieldMint(f, s), cm = f.elements.confirm_mismatch, ch = f.elements.chart_mint;
    label();
    if (!mint) return false;
    if (ch) ch.value = S.m || '';
    if (cm) cm.value = '';
    const sol = (f.elements.sol.value || '').trim().replace('.', ',');
    if (S.m && mint !== S.m) {
      if (!confirm(`PAŽNJA: adresa u polju je ${s.sym} (${shortM(mint)}), a graf prikazuje ${chartSym()} (${shortM(S.m)}).\n\n` +
        `Kupnja ide na token iz polja: ${s.sym} (${shortM(mint)}). Kupiti baš njega?`)) return false;
      if (cm) cm.value = '1';
    }
    return confirm(`Kupiti ${sol} SOL ${s.sym} (${shortM(mint)}) pravim novcem (ako je Autopilot uključen)?`);
  };
  function tokShow(f, s) {
    const el = f && $('[data-tokline]', f);
    if (!el) return;
    const t = s.t;
    el.className = 'apx-tokline' + (s.st === 'bad' || s.st === 'down' ? ' dn' : s.st === 'wait' ? ' wait' : '');
    if (s.st === 'empty') el.textContent = '';
    else if (s.st === 'wait') el.textContent = 'Provjeravam adresu…';
    else if (s.st === 'bad') el.textContent = 'Token nije pronađen — provjeri adresu.';
    else if (s.st === 'down') el.textContent = 'DexScreener se trenutno ne javlja: adresa nije provjerena. Pokušavam ponovno…';
    else el.innerHTML = `Kupuješ: <b translate=no>${esc(s.sym)}</b>` + (t ? `${t.name ? ' (' + esc(t.name) + ')' : ''} · MC ${fMc(t.mcap)} · ` +
      `likvidnost ${fMc(t.liq)} · starost ${fAge(t.age_s)}` : '');
  }
  let tokT = 0;
  function tokCheck(now) {
    clearTimeout(tokT);
    const f = form(), v = ((f && f.elements.token.value) || '').trim();
    label();   // at once: the button says what is known, "provjeravam adresu…" until then
    // a known answer is kept; "not found" is asked again after 20 s (a token listed a moment ago)
    if (!v || (S.tok && (S.tok.q === v || S.tok.mint === v) && (S.tok.found || (S.tok.found === false && Date.now() - S.tok.at < 20000)))) return;
    tokT = setTimeout(async () => {
      let t;
      try {
        const r = await fetch('/pravi-trade/api/token?q=' + encodeURIComponent(v), { cache: 'no-store', credentials: 'same-origin' });
        if (!r.ok) throw new Error(String(r.status));
        t = await r.json();
      } catch (e) { t = { q: v, found: null }; }
      const f2 = form(), cur = ((f2 && f2.elements.token.value) || '').trim();
      if (cur !== v && cur !== t.mint) return;   // typed on meanwhile: the newer check answers
      S.tok = t; t.at = Date.now();
      if (t.found && t.mint && cur !== t.mint) f2.elements.token.value = t.mint;   // a link: the mint it is, in sight
      const named = !!(t.found && t.sym);   // DexScreener's symbol; without one the name we already show, else the address
      if (t.found && !t.sym) t.sym = (F.header && F.header.mint === t.mint && F.header.sym) || shortM(t.mint);
      if (t.found && t.mint && t.mint !== S.m) { selectToken(t.mint, t.sym); return; }   // chart, header, panel: that token
      const hs = $('#apx-hdr [data-f=sym]');
      if (named && F.header && F.header.mint === t.mint && F.header.sym !== t.sym) { F.header.sym = t.sym; if (hs) hs.textContent = t.sym; }
      if (t.found == null) tokT = setTimeout(() => { if (S.tok === t) S.tok = null; tokCheck(true); }, 5000);
      label();
    }, now ? 0 : 300);
  }
  function label() {
    const f = form(), b = f && $('[data-go="buy"]', f);
    if (b) {
      const sol = (f.elements.sol.value || '').trim(), s = tokState(f);
      const who = { ok: s.sym, empty: '', wait: '(provjeravam adresu…)', bad: '(provjeri adresu)', down: '(adresa nije provjerena)' }[s.st];
      b.textContent = `Kupi ${sol ? sol.replace('.', ',') + ' SOL ' : ''}${who}`.trim();
      b.disabled = s.st !== 'ok';
      tokShow(f, s);
      const mm = $('[data-mismatch]', f), mint = fieldMint(f, s), on = !!(mint && S.m && mint !== S.m);
      if (mm) { mm.hidden = !on; if (on) mm.textContent = `Adresa u polju je ${s.sym} (${shortM(mint)}), a graf prikazuje ${chartSym()} (${shortM(S.m)}). Kupnja ide na adresu iz polja, uz potvrdu.`; }
    }
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
    chips(f);
  }
  // the quick TP / SL chips show what is in the field (filled from "Što kupiti", typed or tapped): "15%" = +15 %
  const nLvl = v => { let s = String(v || '').trim().toLowerCase().replace(/\s/g, '').replace(/[−–]/g, '-').replace(',', '.').replace(/^\+/, ''); if (/^-?[0-9.]+$/.test(s)) s += '%'; return s; };
  function chips(f) {
    if (!f || !f.elements.tp) return;
    const tp = nLvl(f.elements.tp.value), sl = nLvl(f.elements.sl.value);
    for (const c of $$('[data-tp],[data-etp]', f)) c.classList.toggle('on', !!tp && nLvl(c.dataset.tp || c.dataset.etp) === tp);
    for (const c of $$('[data-sl],[data-esl]', f)) c.classList.toggle('on', !!sl && nLvl(c.dataset.sl || c.dataset.esl) === sl);
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
  // "Kupi" in "Što kupiti" (a proposal: ui/apterm.proposal_fill, a live pick: live_fill) / "U panel": only fills the
  // form, never posts it. 11.11. (Jure: "neka prepopulira sve stavke ... da ja mogu gore opet samo kliknuti Kupi"):
  // token, stake, TP, SL, trailing, exit "moj TP/SL", the matching chips lit, and the panel's Kupi focused
  async function fillFrom(d, plain) {
    if (d.token && d.token !== S.m) await selectToken(d.token, d.sym);
    const f = form(); if (!f) return;
    setSide('buy');
    f.elements.token.value = d.token || '';
    if (d.sol) { f.elements.sol.value = d.sol; for (const c of $$('[data-sol]', f)) c.classList.toggle('on', c.dataset.sol === d.sol); }
    let note = $('#ap-pk-note');
    if (!plain) {
      if (f.elements.at) f.elements.at.value = '';
      f.elements.tp.value = d.tp || ''; f.elements.sl.value = d.sl || '';
      if (f.elements.exit) f.elements.exit.value = d.exit || 'tpsl';
      let h = f.elements.prijedlog;   // a proposal's id: its exit plan goes with the buy (pravitrade._post_proposal_buy)
      if (d.id) { if (!h) { h = document.createElement('input'); h.type = 'hidden'; h.name = 'prijedlog'; f.appendChild(h); } h.value = d.id; }
      else if (h) h.remove();
      // 11.11. (owner: "Plan izlaza uz kupnju: DA"): trailing and time stop are the buy's own fields now (the plan
      // the server sets with the buy: pravitrade._buy_plan), filled from the proposal / the fast path's exit
      const num = v => (v === null || v === undefined || v === '') ? '' : String(+(+v).toFixed(2));
      const pc = num(d.trail), tm = num(d.time);
      const tr = $('[data-trail]', f), tt = $('[data-time]', f);
      if (tr) tr.value = pc;
      if (tt) tt.value = tm;
      if (pc || tm) { const det = (tr || tt).closest('details'); if (det) det.open = true; }
      if (!note) { note = document.createElement('p'); note.id = 'ap-pk-note'; note.className = 'apx-note'; f.insertBefore(note, $('[data-cost]', f)); }
      note.textContent = `${d.id ? 'Prijedlog' : 'Alat (živo)'} ${d.sym}: ulog ${String(d.sol).replace('.', ',')} SOL, TP ${d.tp || '–'}, ` +
        `SL ${d.sl || 'zadani'}${pc ? ', trailing ' + pc.replace('.', ',') + NB + '%' : ''}${tm ? ', time stop ' + tm + NB + 'min' : ''}. ` +
        `${d.plan ? d.plan + ' ' : ''}Provjeri i dodirni Kupi.`;
    } else {
      if (f.elements.prijedlog) f.elements.prijedlog.remove();
      if (note) note.remove();
    }
    hints(); costEst(); label(); tokCheck(true);
    const go = $('[data-go="buy"]', f);
    if (matchMedia('(max-width:1023px)').matches) openSheet('buy');
    else if (go) go.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    if (go) go.focus({ preventScroll: true });   // ready: one tap on Kupi (it still asks to confirm)
  }
  function openSheet(side) { if (side) setSide(side); root.classList.add('sheet'); document.body.style.overflow = 'hidden'; }
  function closeSheet() { root.classList.remove('sheet'); document.body.style.overflow = ''; }
  document.addEventListener('keydown', e => { if (e.key === 'Escape' && root.classList.contains('sheet')) closeSheet(); });

  // ---- Uredi SL-TP (ui/apterm.sltp_html): in the position's row, in the panel's "Tvoja pozicija", and "Uredi" in
  //      Otvoreni nalozi opens the row's. 11.11. (Jure: "nemam nigdje button spremi ... nego samo Kupi 0,15"): it used to
  //      open in place under the row, often below the screen's edge, so nothing seemed to happen and the TP / SL typed
  //      went into the Kupi panel. Now it opens in sight with its TP focused, and "Spremi SL/TP" answers in place ----
  function eHints(f) {   // "≈ MC $442k" / "≈ +30 % od ulaza" under the editor's fields, from the position's average entry
    const base = +f.dataset.base || null;
    for (const k of ['tp', 'sl']) {
      const el = $(`[data-ehint="${k}"]`, f), v = (f.elements[k].value || '').trim();
      if (!el) continue;
      const txt = v || (k === 'sl' ? (F.panel || {}).sl_default || '' : ''), lv = parseLvl(txt, base, k);
      el.textContent = !lv ? '' : (v ? '' : 'zadano · ') + (txt.includes('%') || !/[$kmb]/i.test(txt) ? '≈ MC ' + fMc(lv.mc) : '≈ ' + fPct(lv.pct, 0) + ' od ulaza');
    }
    chips(f);
  }
  function openEdit(t) {
    const pane = t.closest('.apx-pane');
    if (pane && pane.hidden) showTab(pane.id);
    const inSide = !!t.closest('.apx-side');
    if (inSide && matchMedia('(max-width:1023px)').matches) openSheet();   // the panel is the phone's sheet
    t.hidden = false;
    for (const b of $$(`[data-edit="${t.id}"]`)) b.setAttribute('aria-expanded', 'true');
    const f = $('form[data-sltp]', t), m = f && $('.apx-sltp-msg', f);
    if (m) { m.textContent = ''; m.className = 'apx-sltp-msg'; }
    if (f) eHints(f);
    t.scrollIntoView({ behavior: 'smooth', block: inSide ? 'nearest' : 'center' });
    if (f) { f.elements.tp.focus({ preventScroll: true }); f.elements.tp.select(); }
  }
  function closeEdit(t, keep) {
    if (!t) return;
    if (t.contains(document.activeElement)) document.activeElement.blur();
    t.hidden = true;
    for (const b of $$(`[data-edit="${t.id}"]`)) b.setAttribute('aria-expanded', 'false');
    const f = $('form[data-sltp]', t), m = f && $('.apx-sltp-msg', f);
    if (f && !keep) { f.reset(); if (m) { m.textContent = ''; m.className = 'apx-sltp-msg'; } }
    if (S.stale) refreshFirst();   // what the open editor held back
  }
  function toast(txt, bad) {   // the same note as the server's answer to a form (.ap-toast, ui/pravitrade.CSS)
    for (const o of $$('.ap-toast')) o.remove();
    const t = document.createElement('div');
    t.className = 'ap-toast ' + (bad ? 'bad' : 'ok'); t.setAttribute('role', bad ? 'alert' : 'status');
    t.textContent = txt; t.addEventListener('click', () => t.remove());
    root.appendChild(t);
    setTimeout(() => t.remove(), 7000);
  }
  async function saveExit(f) {   // POST /pravi-trade/exit with the form's own fields (and _csrf), the answer in place
    if (f._busy) return;
    const msg = $('.apx-sltp-msg', f), btn = $('[data-save]', f), ed = f.closest('.apx-edit');
    const say = (txt, cls) => { msg.textContent = txt; msg.className = 'apx-sltp-msg ' + (cls || ''); };
    f._busy = 1; btn.disabled = true; btn.textContent = 'Spremam…'; say('');
    try {
      const r = await fetch(f.action, { method: 'POST', body: new URLSearchParams(new FormData(f)), credentials: 'same-origin',
        headers: { 'X-Apx-Fetch': '1' } });
      if (!r.ok) throw new Error('poslužitelj ' + r.status);
      // run_ui answers {"to": the address a form would go to}; an older server redirects, the address says the same
      const to = (r.headers.get('content-type') || '').includes('json') ? ((await r.json()).to || '') : r.redirected ? r.url : '';
      const q = new URL(to || '/', location.href).searchParams, err = q.get('err'), ok = q.get('ok');
      if (err || !ok) { say('Nije spremljeno: ' + (err || 'poslužitelj nije potvrdio.'), 'dn'); return; }
      say('✓ Spremljeno. ' + ok, 'up');
      toast(ok);
      for (const k of ['tp', 'sl']) f.elements[k].defaultValue = f.elements[k].value;
      for (const p of $$('.apx-pane,.apx-side')) p._down = 0;   // the press on Spremi must not hold the tables back
      S.flash = f.elements.id.value; S.stale = 1;
      setTimeout(() => closeEdit(ed, true), 1200);
    } catch (x) {
      say(`Nije spremljeno (${x.message || 'mreža'}). Upisano je ostalo; pokušaj ponovno.`, 'dn');
    } finally { f._busy = 0; btn.disabled = false; btn.textContent = 'Spremi SL/TP'; }
  }
  // ---- 11.11. (owner: "Može izaći upozorenje, box na kojem piše upozorenje, ali ako se složim, ručno uvijek nadjačava
  //      sve ostalo"): Kupi (and Kupi na MC) and the DCA rows post in place; a buy over the owner's limits answers
  //      {"warn": [...]} (ui/pravitrade.fetch_answer): the box below lists every reason with its numbers, "Kupi
  //      svejedno" sends the same form with override=1 after a confirm, "Odustani" closes it. The box never goes away
  //      on its own (Jure: "poruke odmah nestanu"). Under $30k MC it asks for the reason first. ----
  function goTo(to) {   // the page the answer names (its ?ok= / ?err= toast), like an ordinary form would
    const u = new URL(to || '/pravi-trade', location.href);
    if (u.pathname + u.search === location.pathname + location.search) location.reload(); else location.assign(u.href);
  }
  async function postForm(action, body) {
    const r = await fetch(action, { method: 'POST', body, credentials: 'same-origin', headers: { 'X-Apx-Fetch': '1' } });
    if (!r.ok) throw new Error('poslužitelj ' + r.status);
    return (r.headers.get('content-type') || '').includes('json') ? r.json() : { to: r.redirected ? r.url : '' };
  }
  function warnClose() { for (const o of $$('.ap-warnbox')) o.remove(); }
  function warnBox(action, body, j) {
    warnClose();
    const box = document.createElement('div');
    box.className = 'ap-warnbox'; box.id = 'ap-warn'; box.setAttribute('role', 'alertdialog');
    box.setAttribute('aria-labelledby', 'ap-warn-h'); box.setAttribute('aria-describedby', 'ap-warn-l');
    const min = +j.reason_min || 10, prev = body.get('reason') || '';
    box.innerHTML = `<p class=ap-warnbox-h id=ap-warn-h>${esc(j.title || 'Upozorenje: ova kupnja prelazi tvoje limite')}</p>` +
      (j.what ? `<p class=ap-warnbox-what>${esc(j.what)}</p>` : '') +
      `<ul id=ap-warn-l>${(j.warn || []).map(w => `<li>${esc(w)}</li>`).join('')}</ul>` +
      '<p class=ap-warnbox-note>Ako potvrdiš, tvoja ručna kupnja nadjačava ove limite samo za ovu kupnju. Kill switch, ' +
      'stanje walleta i rug i dalje vrijede.</p>' +
      (j.need_reason ? `<label class=ap-warnbox-r>${esc(j.reason_label || 'Razlog kupnje ispod 30k MC')} <small>(obavezno, ` +
        `najmanje ${min} znakova)</small><textarea name=reason required minlength=${min} maxlength=300 rows=2 autocomplete=off ` +
        `placeholder="npr. poznati caller, svjež volumen, likvidnost drži">${esc(prev)}</textarea></label>` : '') +
      (j.note ? `<p class=ap-warnbox-err>${esc(j.note)}</p>` : '') + '<p class=ap-warnbox-err data-werr hidden></p>' +
      '<div class=ap-warnbox-go><button type=button class=ap-warnbox-yes>Kupi svejedno</button>' +
      '<button type=button class=ap-warnbox-no>Odustani</button></div>';
    const yes = $('.ap-warnbox-yes', box), why = $('textarea', box), err = $('[data-werr]', box);
    const ready = () => { yes.disabled = !!why && why.value.trim().length < min; };
    if (why) { why.addEventListener('input', ready); ready(); }
    $('.ap-warnbox-no', box).addEventListener('click', warnClose);
    yes.addEventListener('click', async () => {
      if (yes.disabled || box._busy) return;
      if (!confirm('Kupiti svejedno, iznad svojih limita?\n\n' + (j.warn || []).join('\n'))) return;
      body.set('override', '1');
      if (why) body.set('reason', why.value.trim()); else body.delete('reason');
      box._busy = 1; yes.disabled = true; yes.textContent = 'Šaljem…'; err.hidden = true;
      try {
        const a = await postForm(action, body);
        if (a.warn && a.warn.length) { warnBox(action, body, a); return; }   // e.g. the reason is still missing
        goTo(a.to);
      } catch (x) {
        err.textContent = `Nije poslano (${x.message || 'mreža'}). Pokušaj ponovno.`; err.hidden = false;
        box._busy = 0; yes.textContent = 'Kupi svejedno'; ready(); if (!why) yes.disabled = false;
      }
    });
    root.appendChild(box);
    (why || yes).focus({ preventScroll: true });
  }
  async function sendOrder(f) {   // Kupi / Kupi na MC / a DCA row: in place; a warning opens the box, else the page
    if (f._busy) return;
    const btn = $('button:not([type=button])', f), txt = btn && btn.textContent;
    f._busy = 1; if (btn) { btn.disabled = true; btn.textContent = 'Šaljem…'; }
    const body = new URLSearchParams(new FormData(f));
    body.delete('override'); body.delete('reason');
    try {
      const j = await postForm(f.action, body);
      if (j.warn && j.warn.length) { warnBox(f.action, body, j); return; }
      goTo(j.to);
    } catch (x) {
      toast(`Nije poslano (${x.message || 'mreža'}). Pokušaj ponovno.`, true);
    } finally { f._busy = 0; if (btn) { btn.disabled = false; btn.textContent = txt; } }
  }
  root.addEventListener('submit', e => {
    if (e.target.id === 'apx-buy' && !fieldMint(e.target, tokState(e.target))) { e.preventDefault(); label(); return; }   // never an unnamed token
    if (!e.defaultPrevented && window.fetch && (e.target.id === 'apx-buy' || e.target.matches('form.apx-dcar'))) {
      e.preventDefault(); sendOrder(e.target); return;   // the confirm (apBuyOk) ran in the form's own onsubmit
    }
    const f = e.target.closest('form[data-sltp]');
    if (!f || !window.fetch) return;   // no fetch: the ordinary form, back to #poz-<id>
    e.preventDefault();
    saveExit(f);
  });

  // 13.11. (Jure: "Kako da odaberem token da bi se prikazao graf kad gdje god kliknem otvori mi novi pop-up i onda ako
  // kliknem na token odvede me na DexScreener ... trebao bi se učitavati ovaj graf"): on this page a tap on a token (a row
  // or a name that opened the token pop-up, a link to /token/<mint>, a "Prikaži na grafu" button, also inside an open
  // pop-up) loads it into the chart, the header and the panel above. Capture phase, so the pop-up's own handler never
  // sees it. What keeps the pop-up: anything marked data-popkeep ("provjera"), the small ↗ links to other sites, and
  // a click with a modifier key (new tab).
  const MINT_RE = /^[1-9A-HJ-NP-Za-km-z]{32,44}$/;
  const tokOf = el => {
    if (el.dataset.sel) return el.dataset.sel;
    if (el.dataset.pop) { try { return new URL(el.dataset.pop, location.href).searchParams.get('m') || ''; } catch (x) { return ''; } }
    const h = el.getAttribute('href') || '';
    return h.startsWith('/token/') ? decodeURIComponent(h.slice(7).split(/[?#/]/)[0]) : '';
  };
  document.addEventListener('click', e => {
    if (e.button || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
    const el = e.target.closest('[data-pop^="/pravi-trade/token?"], a[href^="/token/"], [data-sel]');
    if (!el || el.closest('[data-popkeep]')) return;
    // a button, link or field INSIDE a token row (Kupi, Uredi, ↗, a tab) keeps doing its own job
    const inner = e.target.closest('a,button,input,select,textarea,label,summary');
    if (inner && inner !== el && el.contains(inner)) return;
    const m = tokOf(el);
    if (!MINT_RE.test(m)) return;
    e.preventDefault(); e.stopImmediatePropagation();
    const d = document.getElementById('ap-pop'); if (d && d.open) d.close();
    const name = el.dataset.sym || ((el.querySelector('b') || el).textContent || '').trim().split(/\s+/)[0].slice(0, 24);
    selectToken(m, name);
    const hd = $('#apx-hdr'); if (hd && hd.getBoundingClientRect().top < 0) hd.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }, true);

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
    if ((b = g('[data-etp],[data-esl]'))) {   // the editor's chips only fill its field; "Spremi SL/TP" saves
      const f = b.closest('form'), k = b.dataset.etp ? 'tp' : 'sl';
      if (f) { f.elements[k].value = b.dataset.etp || b.dataset.esl; eHints(f); }
      return;
    }
    if ((b = g('[data-pk]'))) {
      e.preventDefault(); e.stopPropagation();
      // the Kupi under a proposal's "detalji" (proposals/view) fills what its row's own Kupi does (apterm.proposal_fill)
      const row = b.closest('.apx-krow'), main = row && $(':scope > .apx-act [data-pk]', row);
      try { fillFrom(JSON.parse((main || b).dataset.pk)); } catch (x) { /* bad data */ }
      return;
    }
    if ((b = g('[data-fill]'))) { e.preventDefault(); try { fillFrom(JSON.parse(b.dataset.fill), true); } catch (x) { /* bad data */ } return; }
    if ((b = g('[data-sel]'))) {
      e.preventDefault();
      selectToken(b.dataset.sel, b.textContent.trim());
      const hd = $('#apx-hdr'); if (hd && hd.getBoundingClientRect().top < 0) hd.scrollIntoView({ behavior: 'smooth', block: 'start' });
      return;
    }
    if ((b = g('[data-edit]'))) {
      const t = document.getElementById(b.dataset.edit);
      if (!t) {   // a position with no editor here (no demo pair, a sale under way): at least its row
        const r = b.dataset.goto && document.getElementById(b.dataset.goto);
        if (r) { showTab('pozicije'); r.scrollIntoView({ behavior: 'smooth', block: 'center' }); }
        return;
      }
      // the row's button opens and closes it; "Uredi" in Otvoreni nalozi and the panel's link only open it
      if (t.hidden || b.dataset.goto || b.classList.contains('apx-lnk')) openEdit(t); else closeEdit(t);
      return;
    }
    if ((b = g('[data-edit-close]'))) { closeEdit(b.closest('.apx-edit')); return; }
    if ((b = g('[data-page]'))) { const box = $('#apx-hist'); if (box) loadBox(box, b.dataset.page); return; }
    if ((b = g('[data-pm]'))) { PN.m = b.dataset.pm; pnlSave(); pnlLoad(); return; }
    if ((b = g('[data-pd]'))) { PN.d = +b.dataset.pd; pnlSave(); pnlLoad(); return; }
    if ((b = g('[data-pu]'))) { PN.u = b.dataset.pu; pnlSave(); pnlDraw(); return; }
    if ((b = g('[data-pv]'))) { PN.v = b.dataset.pv; pnlSave(); pnlLoad(); return; }
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
      if (e.target.name === 'token') tokCheck();
    }
    const ef = e.target.closest('form[data-sltp]');
    if (ef) eHints(ef);
    if (e.target.name === 'frac') label();
  });
  root.addEventListener('change', e => {
    if (e.target.matches('[data-zone]')) { const r = e.target.closest('form'); if (r && e.target.value) r.elements.lvl.value = e.target.value; }
    if (e.target.name === 'token' && form() && form().contains(e.target)) tokCheck(true);   // picks it once it is found
    if (e.target.name === 'frac') label();
  });
  const ost = $('#apx-ostalo');
  if (ost) ost.addEventListener('toggle', () => { if (ost.open) for (const c of $$('[data-x-src]', ost)) startLazy(c); });

  // ---- start: lazy parts, the remembered tab, the panel's numbers; the chart and the stream after the first paint ----
  // what is on the first screen now; the rest after the token's chart (go, below), so they do not race it
  for (const el of $$('[data-x-src]')) if (shown(el) && inView(el)) watch(el);
  try { const t = sessionStorage.getItem('apx.tab'); if (t && t !== 'pozicije' && !S.hash) showTab(t); } catch (e) { /* no storage */ }
  for (const b of $$('[data-tf]')) b.classList.toggle('on', b.dataset.tf === S.tf);
  for (const b of $$('[data-unit]')) b.classList.toggle('on', b.dataset.unit === S.unit);
  setSide('buy'); hints(); costEst(); age(); tokCheck(true);
  scrollHash();
  window.addEventListener('hashchange', () => {   // a link to an anchor on the page: used once as well
    S.hash = decodeURIComponent(location.hash.slice(1)); S.hashDone = null; S.hashTried = null; scrollHash(); dropHash();
  });
  const later = fn => ('requestIdleCallback' in window) ? requestIdleCallback(fn, { timeout: 1500 }) : setTimeout(fn, 300);
  const go = () => {
    setTimeout(startLive, 400);
    // one at a time on a slow phone line: the token's chart first, then the "Portfelj" chart (its numbers came with
    // the page), then the parts under the tables (loaded before the finger gets there: no jump under a tap)
    later(async () => {
      try { await chartInit(); } catch (e) { /* the chart says so in its box */ }
      pnlLoad();
      setTimeout(() => later(() => { for (const el of $$('[data-x-src]')) if (shown(el) || hides(el)) { watch(el); startLazy(el); } warmBoxes(); }), 300);
    });
    setInterval(() => { const c = $('#apx-port'); if (document.visibilityState === 'visible' && c && inView(c)) pnlLoad(); }, 60000);
  };
  warmBoxes();
  if (document.readyState === 'complete') go(); else addEventListener('load', go);
})();
