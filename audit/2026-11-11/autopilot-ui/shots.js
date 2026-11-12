// Snimke Autopilota (/pravi-trade) na 375, 768 i 1440 px (deviceScaleFactor 2) i provjera vodoravnog skrola.
//   NODE_PATH=/opt/node22/lib/node_modules node audit/2026-11-11/autopilot-ui/shots.js \
//     --base http://127.0.0.1:8791 --cookie 'cb_s=...' --out audit/2026-11-11/autopilot-ui --prefix poslije
// Lokalni seed podaci (audit/2026-11-10/seed_app.py + audit/2026-11-11/autopilot-ui/seed_extra.py), NE produkcija.
const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');

const arg = (k, d) => { const i = process.argv.indexOf('--' + k); return i > 0 ? process.argv[i + 1] : d; };
const BASE = arg('base', 'http://127.0.0.1:8791');
const COOKIE = arg('cookie', '');
const OUT = arg('out', '.');
const PREFIX = arg('prefix', 'poslije');
const PATH = arg('path', '/pravi-trade');
const OPEN = arg('open', '');   // e.g. "#apx-ostalo": a <details> to open before the shot (lazy part)
const OPEN_SHEET = arg('sheet', '1') === '1';
const FIRST = arg('first', '1') === '1';   // also the -prvi-ekran shot (viewport only)
// --widths 375,1440: only these (11.11.: the "prikaz" shots are 375 and 1440)
const WIDTHS = [[375, 812], [768, 1024], [1440, 900]].filter(([w]) => !arg('widths', '') || arg('widths', '').split(',').includes(String(w)));

(async () => {
  const browser = await chromium.launch({ executablePath: '/opt/pw-browsers/chromium', args: ['--no-sandbox'] });
  const report = [];
  for (const [w, h] of WIDTHS) {
    const ctx = await browser.newContext({ viewport: { width: w, height: h }, deviceScaleFactor: 2,
      isMobile: w < 800, hasTouch: w < 800 });
    if (COOKIE) {
      const i = COOKIE.indexOf('=');
      await ctx.addCookies([{ name: COOKIE.slice(0, i), value: COOKIE.slice(i + 1), url: BASE }]);
    }
    const page = await ctx.newPage();
    const errors = [];
    page.on('pageerror', e => errors.push(String(e)));
    page.on('console', m => { if (m.type() === 'error') errors.push(m.text()); });
    await page.goto(BASE + PATH, { waitUntil: 'load' });
    await page.waitForTimeout(2500);   // chart, first live tick
    // scroll down step by step so the parts that load on scroll get their data, then back to the top
    await page.evaluate(async () => {
      for (let y = 0; y < document.scrollingElement.scrollHeight; y += 400) {
        window.scrollTo(0, y); await new Promise(r => setTimeout(r, 150));
      }
      window.scrollTo(0, 0);
    });
    if (OPEN) {
      await page.evaluate(sel => { const d = document.querySelector(sel); if (d) { d.open = true; d.dispatchEvent(new Event('toggle')); } }, OPEN);
    }
    await page.waitForTimeout(2000);
    const m = await page.evaluate(() => ({ scrollWidth: document.scrollingElement.scrollWidth, innerWidth: window.innerWidth,
      height: document.scrollingElement.scrollHeight }));
    const name = `${PREFIX}-${w}.png`;
    if (FIRST) await page.screenshot({ path: path.join(OUT, `${PREFIX}-${w}-prvi-ekran.png`), fullPage: false });
    if (w < 1024 && OPEN_SHEET) {   // the order panel as the phone's bottom sheet (viewport only)
      const b = await page.$('[data-sheet=buy]');
      if (b) { await b.click(); await page.waitForTimeout(400); await page.screenshot({ path: path.join(OUT, `${PREFIX}-${w}-nalog.png`) }); }
      await page.evaluate(() => { const r = document.getElementById('apx'); if (r) r.classList.remove('sheet'); document.body.style.overflow = ''; });
    }
    // a full-page capture lays fixed elements over the first screen: the sticky bars and the closed sheet are hidden
    // for it (they are in the -prvi-ekran / -nalog shots)
    await page.addStyleTag({ content: '.bbar,.apx-mbar,.totop{display:none!important}' +
      (w < 1024 ? '.apx-side{display:none!important}' : '') });
    await page.screenshot({ path: path.join(OUT, name), fullPage: true });
    report.push({ width: w, file: name, ...m, noHorizontalScroll: m.scrollWidth <= m.innerWidth, errors });
    await ctx.close();
  }
  await browser.close();
  fs.writeFileSync(path.join(OUT, `${PREFIX}-shots.json`), JSON.stringify(report, null, 1));
  for (const r of report) {
    console.log(`${r.file}: ${r.width}px scrollWidth=${r.scrollWidth} inner=${r.innerWidth} ` +
      `${r.noHorizontalScroll ? 'bez vodoravnog skrola' : 'IMA VODORAVNI SKROL'} visina=${r.height} greske=${r.errors.length}`);
    for (const e of r.errors) console.log('   ' + e.slice(0, 200));
  }
})();
