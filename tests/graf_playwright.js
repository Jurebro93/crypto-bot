// tests/test_graf_povijest_offline.Browser: the Autopilot chart (ui/static/ap/ap.js, the real page from a local server)
// at 390 px. 14.11. (owner: "Graf ne prikazuje dobro": YoungBull on 1h, one candle in the middle and a fragment cut at
// the left edge). The candles come from page.route (no server data, no network: every other host is refused):
//   dvije  1h with 2 candles: both whole
//   rast   1h: 1 candle while the history is fetched (fill "dohvacam"), the re-read 4 s later has 3 (two new on the
//          left, the read that used to leave one cut): all 3 whole
//   mlad   1h with 2 candles and young.pick 5m: the chart shows 5m for this token, the saved TF stays 1h
// "Whole" is read from the chart's own canvas: the columns that hold a candle colour (--good / --bad) form one run
// per candle; every run inside the pane, none narrower than the others (a cut candle is).
//   node tests/graf_playwright.js <base url> <mint> <out dir> <hour ts>
const { chromium } = require('playwright');
const path = require('path');

const [BASE, MINT, OUT, H0s] = process.argv.slice(2);
const H0 = +H0s;
const errors = [];

function bar(t, o, c) { return { time: t, open: o, high: Math.max(o, c) * 1.01, low: Math.min(o, c) * 0.99, close: c }; }
function answer(candles, extra) {
  return Object.assign({ mint: MINT, unit: 'mc', ts: H0 + 3660, data_ts: H0 + 3600, candles, vol: candles.map(() => 1000),
    supply: 1e9, lines: [{ kind: 'entry', value: 92300, label: 'Ulaz' }], zones: null, zones_mc: null,
    first_ts: candles.length ? candles[0].time : null, born: null, fill: null, young: null }, extra || {});
}
const TWO = [bar(H0 - 3600, 75000, 71000), bar(H0, 80200, 92300)];

async function measure(page) {
  return page.evaluate(() => {
    const box = document.getElementById('apx-chart');
    const cs = getComputedStyle(document.documentElement);
    const rgb = v => {
      const s = (v || '').trim();
      let m = /^#([0-9a-f]{6})$/i.exec(s);
      if (m) { const n = parseInt(m[1], 16); return [(n >> 16) & 255, (n >> 8) & 255, n & 255]; }
      m = /^#([0-9a-f]{3})$/i.exec(s);
      if (m) return m[1].split('').map(x => parseInt(x + x, 16));
      m = /rgba?\(([^)]+)\)/.exec(s);
      return m ? m[1].split(',').slice(0, 3).map(x => +x) : null;
    };
    const cols = [rgb(cs.getPropertyValue('--good')) || [22, 163, 74], rgb(cs.getPropertyValue('--bad')) || [220, 38, 38]];
    const canv = [...box.querySelectorAll('canvas')];
    const area = c => c.getBoundingClientRect().width * c.getBoundingClientRect().height;
    const pane = canv.reduce((a, c) => (area(c) > area(a) ? c : a), canv[0]);
    const pr = pane.getBoundingClientRect();
    const layers = canv.filter(c => { const r = c.getBoundingClientRect(); return Math.abs(r.left - pr.left) < 1 && Math.abs(r.width - pr.width) < 1 && Math.abs(r.height - pr.height) < 1; });
    const W = pane.width, H = pane.height, k = W / pr.width, hit = new Array(W).fill(false);
    for (const c of layers) {
      const d = c.getContext('2d').getImageData(0, 0, W, H).data;
      for (let x = 0; x < W; x++) {
        if (hit[x]) continue;
        for (let y = 0; y < H; y++) {
          const i = (y * W + x) * 4;
          if (d[i + 3] < 200) continue;
          if (cols.some(q => Math.abs(d[i] - q[0]) + Math.abs(d[i + 1] - q[1]) + Math.abs(d[i + 2] - q[2]) < 40)) { hit[x] = true; break; }
        }
      }
    }
    const runs = [];
    for (let x = 0; x < W; x++) {
      if (!hit[x]) continue;
      if (runs.length && runs[runs.length - 1][1] === x - 1) runs[runs.length - 1][1] = x; else runs.push([x, x]);
    }
    const w = runs.map(r => (r[1] - r[0] + 1) / k);
    const whole = runs.length > 0 && runs[0][0] > 1 && runs[runs.length - 1][1] < W - 2 && Math.max(...w) - Math.min(...w) <= 2;
    const on = document.querySelector('[data-tf].on');
    let saved = null;
    try { saved = localStorage.getItem('apx.tf'); } catch (e) { /* none */ }
    return { runs: runs.length, widths: w.map(x => Math.round(x * 10) / 10), first: runs.length ? Math.round(runs[0][0] / k) : null,
      last: runs.length ? Math.round(runs[runs.length - 1][1] / k) : null, pane: Math.round(pr.width), whole,
      on: on ? on.dataset.tf : null, saved, note: (document.getElementById('apx-cnote') || {}).textContent || '' };
  });
}

// the sticky "Kupi / Prodaj" bar and the bottom navigation lie over the chart in an element shot: hidden for it
async function shot(page, file) {
  await page.addStyleTag({ content: '.bbar,.apx-mbar,.totop{display:none!important}' });
  await page.locator('#apx-chartbox').screenshot({ path: path.join(OUT, file) });
}

async function scenario(browser, name, reply) {
  const ctx = await browser.newContext({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 2, isMobile: true, hasTouch: true });
  await ctx.addInitScript(() => { try { localStorage.setItem('apx.tf', '1h'); } catch (e) { /* none */ } });
  const page = await ctx.newPage();
  page.on('pageerror', e => errors.push(`${name}: ${e}`));
  page.on('console', m => { if (m.type() === 'error' && !/Failed to load resource/.test(m.text())) errors.push(`${name}: ${m.text()}`); });
  const tfs = [];
  await page.route('**/*', route => {
    const u = new URL(route.request().url());
    if (u.hostname !== '127.0.0.1') return route.abort();
    if (u.pathname === '/pravi-trade/api/candles') {
      const tf = u.searchParams.get('tf');
      tfs.push(tf);
      return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(reply(tf, tfs.length)) });
    }
    return route.continue();
  });
  await page.goto(`${BASE}/pravi-trade?m=${MINT}`, { waitUntil: 'load' });
  await page.waitForFunction(() => document.querySelectorAll('#apx-chart canvas').length > 0, null, { timeout: 20000 });
  await page.waitForTimeout(1500);
  const early = await measure(page);
  return { ctx, page, tfs, early };
}

(async () => {
  const browser = await chromium.launch({ args: ['--no-sandbox'] });
  const rep = { errors };
  // 1) two candles on 1h
  {
    const s = await scenario(browser, 'dvije', () => answer(TWO));
    rep.dvije = { ...s.early, tfs: s.tfs };
    await s.page.screenshot({ path: path.join(OUT, 'graf-1h-dvije-390-ekran.png') });
    await shot(s.page, 'graf-1h-dvije-390.png');
    await s.ctx.close();
  }
  // 2) the history arrives on the re-read: two more candles on the left
  {
    const s = await scenario(browser, 'rast', (tf, n) => n === 1
      ? answer([bar(H0, 80200, 92300)], { fill: { state: 'dohvacam', kind: 'm1', why: 'pocetak', note: 'Dohvaćam povijest (GeckoTerminal)…' } })
      : answer([bar(H0 - 7200, 61000, 74000), ...TWO]));
    await s.page.waitForTimeout(5500);
    rep.rast = { ...(await measure(s.page)), tfs: s.tfs, note_first: s.early.note, runs_first: s.early.runs, whole_first: s.early.whole };
    await shot(s.page, 'graf-1h-rast-390.png');
    await s.ctx.close();
  }
  // 3) a young token: 5m for itself only
  {
    const five = Array.from({ length: 13 }, (_, i) => bar(H0 + i * 300, 80200 + i * 900, 81000 + i * 950));
    const young = { first_ts: H0, bars: 2, tf: '1h', more: ['1m', '5m'], counts: { '1m': 61, '5m': 13, '15m': 5 }, pick: '5m',
      why: 'Token je mlad (prvi podaci 16:00)', bars_txt: 'na 1h su 2 svijeće',
      note: 'Token je mlad (prvi podaci 16:00): na 1h su 2 svijeće — 1m/5m pokazuju više' };
    const s = await scenario(browser, 'mlad', tf => (tf === '1h' ? answer(TWO, { young }) : answer(five)));
    rep.mlad = { ...(await measure(s.page)), tfs: s.tfs };
    await shot(s.page, 'graf-mlad-5m-390.png');
    await s.ctx.close();
  }
  await browser.close();
  console.log(JSON.stringify(rep));
})().catch(e => { console.error(e); process.exit(1); });
