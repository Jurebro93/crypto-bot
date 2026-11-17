// tests/test_apaudit_offline.Browser: the Autopilot page (the real ap.js / ap.css from a local server) at 390 px and
// at a foldable's 860 px. 16.11. (owner: "Kliknem na ovu otvorenu poziciju GTA V6 da mi otvori gore graf. On mi otvori
// graf nekog tokena koji se zove Umbra"): a tap on a position's ROW (not only on its small name) must load exactly
// that position's token above: the header, the DexScreener link, the chart, the Token field and Kupi, the sale form.
//   taps    every row is tapped on its line, right of the name; the top is read after each tap
//   race    a refresh for the token picked before answers AFTER another row was tapped: its parts are dropped
//   down    the pick's own answer never comes: the header names the new token, the old sale form is gone
// No network: the server answers from its own databases; every other host is refused.
//   node tests/apaudit_playwright.js <base url> <out dir>
const { chromium } = require('playwright');
const path = require('path');

const [BASE, OUT] = process.argv.slice(2);
const errors = [];

const top = page => page.evaluate(() => {
  const q = s => document.querySelector(s), h = q('#apx-hdr'), a = h && h.querySelector('a[href*="dexscreener.com"]');
  const tok = q('#apx-buy input[name=token]'), ids = q('#apx-sell input[name=id]');
  return { hdr: h ? (h.querySelector('[data-f=sym]') || {}).textContent : null, mint: h ? h.dataset.mint : null,
    dex: a ? a.getAttribute('href').split('/').pop() : null, chart: (q('#apx-chart') || { dataset: {} }).dataset.m,
    token: tok ? tok.value : null, buy: (q('#apx-buy [data-go=buy]') || {}).textContent || '',
    sell: (q('#apx-sell [data-go=sell]') || {}).textContent || '', sellIds: ids ? ids.value : null,
    sel: [...document.querySelectorAll('#pozicije details.is-sel')].map(d => d.dataset.tok),
    m: new URLSearchParams(location.search).get('m') };
});

const wide = page => page.evaluate(() => {
  const w = document.documentElement.clientWidth, out = [];
  for (const el of document.querySelectorAll('#apx *')) {
    if (el.closest('[hidden]')) continue;
    const r = el.getBoundingClientRect();
    if (!r.width || !r.height || (r.right <= w + 1 && r.left >= -1)) continue;
    let p = el.parentElement, clipped = false;
    while (p && p !== document.body) { if (/(auto|scroll|hidden)/.test(getComputedStyle(p).overflowX)) { clipped = true; break; } p = p.parentElement; }
    if (!clipped) out.push(`${el.tagName.toLowerCase()}.${String(el.className).split(' ')[0]}`);
  }
  return { scroll: document.scrollingElement.scrollWidth, vw: w, wide: out.slice(0, 6) };
});

async function tapRow(page, tok, w) {
  const sum = page.locator(`#pozicije details[data-tok="${tok}"] > summary`);
  await sum.scrollIntoViewIfNeeded();
  const bb = await sum.boundingBox();
  // the row's line, away from the name button (left) and the chevron (right)
  await page.touchscreen.tap(bb.x + Math.min(bb.width - 40, Math.max(bb.width * 0.7, 220)), bb.y + bb.height - 12);
}

async function run(browser, w, h) {
  const ctx = await browser.newContext({ viewport: { width: w, height: h }, deviceScaleFactor: 2, isMobile: true, hasTouch: true });
  await ctx.route('**/*', route => (route.request().url().startsWith(BASE) ? route.continue() : route.abort()));
  const page = await ctx.newPage();
  page.on('pageerror', e => errors.push(`${w}: ${e}`));
  await page.goto(BASE + '/pravi-trade', { waitUntil: 'load' });
  await page.waitForFunction(() => document.querySelector('#pozicije details.apx-pos') && document.querySelector('#apx-buy [data-go=buy]'));
  await page.waitForTimeout(1200);
  const rows = await page.evaluate(() => [...document.querySelectorAll('#pozicije details.apx-pos')].map(d => {
    const b = d.querySelector('summary [data-sel]'), r = d.querySelector('summary').getBoundingClientRect();
    return { tok: d.dataset.tok, sel: b.dataset.sel, name: b.textContent, addr: b.classList.contains('apx-addr'), rowH: Math.round(r.height) };
  }));
  const out = { rows, start: await top(page), taps: [], overflow: await wide(page) };
  for (const r of rows.slice().reverse()) {   // from the last row up: never the one the page opened on first
    await tapRow(page, r.tok, w);
    await page.waitForFunction(m => (document.querySelector('#apx-hdr') || { dataset: {} }).dataset.mint === m, r.tok, { timeout: 5000 }).catch(() => {});
    await page.waitForTimeout(500);
    out.taps.push({ row: r.tok, open: await page.evaluate(m => document.querySelector(`#pozicije details[data-tok="${m}"]`).open, r.tok), top: await top(page) });
  }
  await page.locator('#pozicije').scrollIntoViewIfNeeded();
  await page.screenshot({ path: path.join(OUT, `apaudit-${w}-pozicije.png`) });
  out.overflowOpen = await wide(page);
  // "Prikaži graf ↑" of an opened row: its token above, the header in view
  const first = rows[0].tok, second = rows[1].tok;
  await page.locator(`#pozicije details[data-tok="${second}"] .apx-tograf`).tap();
  await page.waitForFunction(m => document.querySelector('#apx-hdr').dataset.mint === m, second, { timeout: 5000 }).catch(() => {});
  await page.waitForTimeout(700);
  out.tograf = { top: await top(page), hdrTop: await page.evaluate(() => Math.round(document.querySelector('#apx-hdr').getBoundingClientRect().top)) };
  await page.screenshot({ path: path.join(OUT, `apaudit-${w}-graf.png`) });
  // race: the refresh for `second` is held for 1.5 s, the row of `first` is tapped meanwhile
  let held = 0;
  const pat = u => u.pathname.endsWith('/api/first') && u.searchParams.get('m') === second && u.searchParams.get('html') === '1' && !u.searchParams.has('s');
  await page.route(pat, async route => { held++; await new Promise(z => setTimeout(z, 1500)); await route.continue(); });
  await page.evaluate(() => document.dispatchEvent(new Event('visibilitychange')));   // the page's own refresh
  await page.waitForTimeout(200);
  await tapRow(page, first, w);
  await page.waitForTimeout(2600);
  out.race = { held, top: await top(page) };
  await page.unroute(pat);
  // down: the pick of `second` gets no answer
  const dead = u => u.pathname.endsWith('/api/first') && u.searchParams.get('m') === second;
  await page.route(dead, route => route.abort());
  await tapRow(page, second, w);
  await page.waitForTimeout(900);
  out.down = await top(page);
  await page.unroute(dead);
  await ctx.close();
  return out;
}

(async () => {
  const browser = await chromium.launch();
  const rep = { errors };
  try {
    rep[390] = await run(browser, 390, 844);
    rep[860] = await run(browser, 860, 1000);
  } finally {
    await browser.close();
  }
  console.log(JSON.stringify(rep));
})().catch(e => { console.error(e); process.exit(1); });
