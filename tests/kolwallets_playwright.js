// tests/test_kolwallets_offline.Browser: the owner's page "Insajderski novčanici" (ui/kolinsajderi.py, the real HTML from
// a local server) at 390 px. Nothing may be wider than the screen, closed or with every row opened (long addresses,
// links and transaction lists are what would push it). No network: every other host is refused.
//   node tests/kolwallets_playwright.js <url> <out dir>
const { chromium } = require('playwright');
const path = require('path');

const [URL_, OUT] = process.argv.slice(2);

async function measure(page) {
  return page.evaluate(() => {
    const vw = document.documentElement.clientWidth;
    const wide = [];
    for (const el of document.querySelectorAll('main *')) {
      const r = el.getBoundingClientRect();
      if (r.width > 0 && (r.right > vw + 1 || r.left < -1)) {
        wide.push((el.tagName + '.' + (el.className || '')).slice(0, 60) + ' ' + Math.round(r.left) + '..' + Math.round(r.right));
      }
    }
    return { vw, scroll: document.documentElement.scrollWidth, wide: wide.slice(0, 8),
             rows: document.querySelectorAll('.ki details').length,
             text: document.querySelector('.ki') ? document.querySelector('.ki').innerText.length : 0 };
  });
}

(async () => {
  const errors = [];
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 2 });
  const base = new URL(URL_).origin;
  await page.route('**/*', r => (r.request().url().startsWith(base) ? r.continue() : r.abort()));
  page.on('pageerror', e => errors.push(String(e).slice(0, 200)));
  await page.goto(URL_, { waitUntil: 'domcontentloaded' });
  const closed = await measure(page);
  await page.screenshot({ path: path.join(OUT, 'kolwallets-390-zatvoreno.png'), fullPage: true });
  await page.evaluate(() => document.querySelectorAll('.ki details').forEach(d => { d.open = true; }));
  const open = await measure(page);
  await page.screenshot({ path: path.join(OUT, 'kolwallets-390-otvoreno.png'), fullPage: true });
  await browser.close();
  console.log(JSON.stringify({ errors, closed, open }));
})().catch(e => { console.error(e); process.exit(1); });
