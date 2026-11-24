// LCP i "graf nacrtan" pod emuliranim 4G-om (CDP: 150 ms RTT, 1,6 Mbit/s dolje, 750 kbit/s gore, CPU 4x sporiji),
// mobitel 412x823, prazan cache; lokalni seed podaci (NE produkcija).
//   NODE_PATH=/opt/node22/lib/node_modules node audit/2026-11-11/autopilot-ui/lcp4g.js --base http://127.0.0.1:8791 \
//     --cookie 'cb_s=...' --runs 3
// "graf nacrtan" = trenutak kad #apx-chart-age dobije vrijeme zadnje svijeće (ap.js loadCandles), samo nova stranica.
const { chromium } = require('playwright');

const arg = (k, d) => { const i = process.argv.indexOf('--' + k); return i > 0 ? process.argv[i + 1] : d; };
const BASE = arg('base', 'http://127.0.0.1:8791');
const COOKIE = arg('cookie', '');
const RUNS = +arg('runs', '3');

const INIT = () => {
  window.__m = { lcp: 0, chart: 0 };
  new PerformanceObserver(l => { for (const e of l.getEntries()) window.__m.lcp = e.startTime; })
    .observe({ type: 'largest-contentful-paint', buffered: true });
  const t = () => {
    const a = document.getElementById('apx-chart-age');
    if (a && +a.dataset.ts > 0 && !window.__m.chart) window.__m.chart = performance.now();
    if (!window.__m.chart) requestAnimationFrame(t);
  };
  requestAnimationFrame(t);
};

(async () => {
  const b = await chromium.launch({ executablePath: '/opt/pw-browsers/chromium', args: ['--no-sandbox'] });
  const out = [];
  for (let i = 0; i < RUNS; i++) {
    const ctx = await b.newContext({ viewport: { width: 412, height: 823 }, deviceScaleFactor: 1.75, isMobile: true, hasTouch: true });
    if (COOKIE) { const k = COOKIE.indexOf('='); await ctx.addCookies([{ name: COOKIE.slice(0, k), value: COOKIE.slice(k + 1), url: BASE }]); }
    const p = await ctx.newPage();
    await p.addInitScript(INIT);
    const cdp = await ctx.newCDPSession(p);
    await cdp.send('Network.enable');
    await cdp.send('Network.setCacheDisabled', { cacheDisabled: true });
    await cdp.send('Network.emulateNetworkConditions', { offline: false, latency: 150, downloadThroughput: 1.6 * 1024 * 1024 / 8,
      uploadThroughput: 750 * 1024 / 8 });
    await cdp.send('Emulation.setCPUThrottlingRate', { rate: 4 });
    const t0 = Date.now();
    await p.goto(BASE + '/pravi-trade', { waitUntil: 'load', timeout: 60000 });
    const load = Date.now() - t0;
    await p.waitForTimeout(6000);
    await p.mouse.click(5, 300);   // LCP stops at the first input
    const m = await p.evaluate(() => window.__m);
    out.push({ run: i + 1, load_ms: load, lcp_ms: Math.round(m.lcp), chart_ms: Math.round(m.chart) || null });
    await ctx.close();
  }
  await b.close();
  for (const r of out) console.log(JSON.stringify(r));
  const med = k => { const v = out.map(r => r[k]).filter(x => x != null).sort((a, c) => a - c); return v.length ? v[Math.floor(v.length / 2)] : null; };
  console.log(JSON.stringify({ median: { load_ms: med('load_ms'), lcp_ms: med('lcp_ms'), chart_ms: med('chart_ms') } }));
})();
