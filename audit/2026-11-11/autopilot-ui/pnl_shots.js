// Snimke kartice "Portfelj" u prikazu "PnL po danima" s tooltipom jednog dana (pnl-dani-375.png, pnl-dani-1440.png),
// deviceScaleFactor 2, lokalni seed (seed_app.py + seed_extra.py + seed_pnl.py), NE produkcija.
//   NODE_PATH=/opt/node22/lib/node_modules node audit/2026-11-11/autopilot-ui/pnl_shots.js --base http://127.0.0.1:8791 \
//     --cookie 'cb_s=...' --out audit/2026-11-11/autopilot-ui
const { chromium } = require('playwright');
const path = require('path');

const arg = (k, d) => { const i = process.argv.indexOf('--' + k); return i > 0 ? process.argv[i + 1] : d; };
const BASE = arg('base', 'http://127.0.0.1:8791');
const COOKIE = arg('cookie', '');
const OUT = arg('out', '.');

(async () => {
  const browser = await chromium.launch({ executablePath: '/opt/pw-browsers/chromium', args: ['--no-sandbox'] });
  for (const [w, h] of [[375, 812], [1440, 900]]) {
    const mobile = w < 800;
    const ctx = await browser.newContext({ viewport: { width: w, height: h }, deviceScaleFactor: 2, isMobile: mobile, hasTouch: mobile });
    if (COOKIE) { const i = COOKIE.indexOf('='); await ctx.addCookies([{ name: COOKIE.slice(0, i), value: COOKIE.slice(i + 1), url: BASE }]); }
    const page = await ctx.newPage();
    const errors = [];
    page.on('pageerror', e => errors.push(String(e)));
    await page.goto(BASE + '/pravi-trade', { waitUntil: 'load' });
    await page.waitForTimeout(2500);
    await page.evaluate(() => { const c = document.getElementById('apx-port'); c.scrollIntoView({ block: 'start' }); window.scrollBy(0, -70); });
    await page.click('[data-pv=days]');
    await page.waitForTimeout(1500);
    // the tooltip of a day with trades: the chart takes the arrow keys (End = today, ← one day back)
    await page.focus('#apx-pchart');
    await page.keyboard.press('End');
    for (let k = 0; k < +arg('back', '3'); k++) { await page.waitForTimeout(80); await page.keyboard.press('ArrowLeft'); }
    await page.waitForTimeout(600);
    // the whole card, without the phone's fixed bars over it
    await page.addStyleTag({ content: '.bbar,.apx-mbar,.totop{display:none!important}' });
    const card = await page.evaluate(() => { const r = document.getElementById('apx-port').getBoundingClientRect();
      return { y: r.top + scrollY, h: r.height }; });
    const m = await page.evaluate(() => ({ scrollWidth: document.scrollingElement.scrollWidth, innerWidth,
      tip: [...document.querySelectorAll('#apx-pchart .apx-tip')].map(t => t.hidden ? '' : t.innerText.replace(/\n/g, ' | ')).join('') }));
    await page.screenshot({ path: path.join(OUT, `pnl-dani-${w}.png`), fullPage: true,
      clip: { x: 0, y: Math.max(0, card.y - 8), width: w, height: card.h + 16 } });
    console.log(`pnl-dani-${w}.png: scrollWidth=${m.scrollWidth} inner=${m.innerWidth} ${m.scrollWidth <= m.innerWidth ? 'bez vodoravnog skrola' : 'IMA VODORAVNI SKROL'}` +
      ` tooltip="${m.tip}" greske=${errors.length}`);
    await ctx.close();
  }
  await browser.close();
})();
