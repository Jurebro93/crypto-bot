// Koliko traje otvaranje sklopljene kartice (<details>): od dodira / klika na <summary> do (1) vidljivo otvorene kartice
// i (2) vidljivog sadržaja (bez kostura i "učitavam"), te je li se otvorila iz prvog pokušaja. Lokalni seed podaci,
// NE produkcija.
//   NODE_PATH=/opt/node22/lib/node_modules node audit/2026-11-11/autopilot-ui/kartice.js --base http://127.0.0.1:8791 \
//     --cookie 'cb_s=...' --out audit/2026-11-11/autopilot-ui/kartice-poslije.json [--cpu 4] [--pages /pravi-trade,/paper]
const { chromium } = require('playwright');
const fs = require('fs');

const arg = (k, d) => { const i = process.argv.indexOf('--' + k); return i > 0 ? process.argv[i + 1] : d; };
const BASE = arg('base', 'http://127.0.0.1:8791');
const COOKIE = arg('cookie', '');
const OUT = arg('out', '');
const PAGES = arg('pages', '/pravi-trade,/pregled,/wallets').split(',');
const MAX = +arg('max', '8');
const CPU = +arg('cpu', '1');   // 4 = a slow phone (Chrome's CPU throttling)

// in the page: the probe that times one open (installed once per page)
const PROBE = () => {
  window.__k = { t0: 0 };
  addEventListener('pointerdown', () => { window.__k.t0 = performance.now(); }, true);
  window.__ev = [];
  try {
    new PerformanceObserver(l => { for (const e of l.getEntries()) if (/click|pointer|touch/.test(e.name)) window.__ev.push(e.duration); })
      .observe({ type: 'event', durationThreshold: 16, buffered: true });
  } catch (e) { /* no Event Timing */ }
};

async function measure(page, idx) {
  return page.evaluate(async i => {
    const d = window.__cand[i];
    const ready = () => {
      const kids = [...d.children].filter(c => c.tagName !== 'SUMMARY');
      const vis = d.open && kids.some(c => c.getBoundingClientRect().height > 0);
      const txt = kids.map(c => c.innerText || '').join(' ').trim();
      const loading = !!d.querySelector('.apx-skel, .skel') || /u[čc]itavam/i.test(txt);
      return { vis, content: vis && !loading && txt.length > 0 };
    };
    const t0 = window.__k.t0 || performance.now();
    let tOpen = null, tContent = null;
    const end = t0 + 5000;
    while (performance.now() < end) {
      await new Promise(r => requestAnimationFrame(r));
      const s = ready(), now = performance.now();
      if (s.vis && tOpen == null) tOpen = now - t0;
      if (s.content) { tContent = now - t0; break; }
    }
    await new Promise(r => setTimeout(r, 1200));
    return { open_ms: tOpen == null ? null : Math.round(tOpen), content_ms: tContent == null ? null : Math.round(tContent),
      still_open_1s: d.open };
  }, idx);
}

(async () => {
  const browser = await chromium.launch({ executablePath: '/opt/pw-browsers/chromium', args: ['--no-sandbox'] });
  const report = {};
  for (const [w, h, mobile] of [[1440, 900, false], [375, 812, true]]) {
    for (const path of PAGES) {
      const ctx = await browser.newContext({ viewport: { width: w, height: h }, deviceScaleFactor: 1, isMobile: mobile, hasTouch: mobile });
      if (COOKIE) { const k = COOKIE.indexOf('='); await ctx.addCookies([{ name: COOKIE.slice(0, k), value: COOKIE.slice(k + 1), url: BASE }]); }
      const page = await ctx.newPage();
      if (CPU > 1) { const cdp = await ctx.newCDPSession(page); await cdp.send('Emulation.setCPUThrottlingRate', { rate: CPU }); }
      await page.addInitScript(PROBE);
      await page.goto(BASE + path, { waitUntil: 'load' });
      await page.waitForTimeout(2500);
      // closed boxes whose summary is visible, outer first, at most MAX
      const n = await page.evaluate(max => {
        window.__cand = [...document.querySelectorAll('details:not([open])')].filter(d => {
          const s = d.querySelector(':scope>summary');
          return s && s.getBoundingClientRect().height > 0 && !d.parentElement.closest('details:not([open])') && !d.closest('dialog');
        }).slice(0, max);
        return window.__cand.length;
      }, MAX);
      const rows = [];
      for (let i = 0; i < n; i++) {
        const [name, seen] = await page.evaluate(i => {
          const d = window.__cand[i], s = d.querySelector(':scope>summary');
          s.scrollIntoView({ block: 'center' });
          // right after the scroll the summary is what a finger would hit (a closed bottom sheet's is not: skipped)
          const r = s.getBoundingClientRect(), at = document.elementFromPoint(r.left + Math.min(40, r.width / 2), r.top + r.height / 2);
          return [(d.id ? '#' + d.id + ' ' : '') + (s.innerText || '').replace(/\s+/g, ' ').trim().slice(0, 50), !!(at && s.contains(at))];
        }, i);
        if (!seen) continue;
        await page.waitForTimeout(400);
        const box = await page.evaluateHandle(i => window.__cand[i].querySelector(':scope>summary'), i);
        const bb = await box.asElement().boundingBox();
        if (!bb) continue;
        const x = bb.x + Math.min(40, bb.width / 2), y = bb.y + bb.height / 2;
        await page.evaluate(() => { window.__ev = []; });
        if (mobile) await page.touchscreen.tap(x, y); else await page.mouse.click(x, y);
        const m = await measure(page, i);
        m.max_event_ms = await page.evaluate(() => Math.round(Math.max(0, ...window.__ev)));
        rows.push({ box: name, ...m });
      }
      report[`${w} ${path}`] = rows;
      await ctx.close();
    }
  }
  await browser.close();
  if (OUT) fs.writeFileSync(OUT, JSON.stringify(report, null, 1));
  for (const [k, rows] of Object.entries(report)) {
    console.log(k);
    for (const r of rows) console.log(`  ${r.box.padEnd(52)} otvoreno ${String(r.open_ms).padStart(5)} ms  sadržaj ${String(r.content_ms).padStart(5)} ms  ` +
      `event ${String(r.max_event_ms).padStart(4)} ms  ${r.still_open_1s ? 'ostaje otvoreno' : 'ZATVORENO/NIJE SE OTVORILO'}`);
  }
})();
