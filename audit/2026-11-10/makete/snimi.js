// Snimke maketa ("novo") i usporedbe sada/novo za prijedlog dizajna, 10.11.2026.
//   python3 audit/2026-11-10/makete/sastavi.py && node audit/2026-11-10/makete/snimi.js [--only pregled,tokeni] [--out <dir>]
// Za svaku maketu: novo-<k>-phone.png (cijela stranica, 390x844 @2x), novo-<k>-phone-fold.png (prvi ekran),
// novo-<k>-desktop.png (cijela stranica, 1280x800 @2x), redak u novo-metrics.json (ista mjerenja kao shots.js),
// za stranice detalja (drugi krug) još novo-<k>-phone-cijela.png (cijela stranica mobitela)
// i usporedba-<k>.png: prvi ekran mobitela, lijevo sada (sada-<k>-phone-fold.png), desno novo.
const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');

const arg = (k, d) => { const i = process.argv.indexOf('--' + k); return i > 0 ? process.argv[i + 1] : d; };
const OUT = arg('out', '/tmp/claude-0/-home-user/4912361d-d525-5b3e-b714-652a838e02b7/scratchpad/shots/ui');
const ONLY = (arg('only', '') || '').split(',').filter(Boolean);
const SCREENS = [
  { key: 'pregled', title: 'Pregled', sada: 'sada-pregled-phone-fold.png', m: 'pregled' },
  { key: 'tokeni', title: 'Tokeni (prijedlozi)', sada: 'sada-tokeni-phone-fold.png', m: 'tokeni' },
  { key: 'influenceri', title: 'Influenceri (ljestvica)', sada: 'sada-influenceri-phone-fold.png', m: 'influenceri-ljestvica' },
  { key: 'autopilot', title: 'Autopilot', sada: 'sada-autopilot-phone-fold.png', m: 'autopilot' },
  { key: 'izbornik', title: 'Navigacija i izbornik Više', sada: 'sada-izbornik-phone.png', m: 'izbornik' },
  // drugi krug (10.11.): "sada" snimljen na kodu f4dc160 (s trakom "Autopilot je live"), detail = i -phone-cijela.png
  { key: 'naslovna', title: 'Naslovna (memesonar.app/hr)', sada: 'sada-naslovna-phone-fold.png', m: 'naslovna', round: 2 },
  { key: 'tokeni-popis', title: 'Tokeni: cijeli popis', sada: 'sada-tokeni-phone-fold.png', m: 'tokeni', round: 2 },
  { key: 'token', title: 'Jedan token', sada: 'sada-token-phone-fold.png', m: 'token', round: 2, detail: true },
  { key: 'influenceri-ljestvica', title: 'Influenceri: cijela ljestvica', sada: 'sada-influenceri-ljestvica-phone-fold.png', m: 'influenceri-ljestvica', round: 2 },
  { key: 'influencer', title: 'Jedan influencer', sada: 'sada-influencer-phone-fold.png', m: 'influencer', round: 2, detail: true },
  { key: 'novcanici', title: 'Novčanici', sada: 'sada-novcanici-phone-fold.png', m: 'novcanici', round: 2 },
  { key: 'novcanik', title: 'Jedan novčanik', sada: 'sada-novcanik-phone-fold.png', m: 'novcanik', round: 2, detail: true },
].filter(s => !ONLY.length || ONLY.includes(s.key));

// isto brojanje kao audit/2026-11-10/shots.js (METRICS), da su brojke sada/novo usporedive
const METRICS = () => {
  const vis = el => { const r = el.getBoundingClientRect();
    return r.width > 0 && r.height > 0 && (!el.checkVisibility || el.checkVisibility({ checkOpacity: true, checkVisibilityCSS: true })); };
  const root = document.querySelector('main') || document.body, fold = innerHeight;
  const all = [...root.querySelectorAll('*')].filter(vis);
  const own = el => [...el.childNodes].filter(n => n.nodeType === 3).map(n => n.textContent).join('').trim();
  const fsz = {}, col = {};
  for (const el of all) { const t = own(el); const cs = getComputedStyle(el);
    if (t) { fsz[cs.fontSize] = (fsz[cs.fontSize] || 0) + t.length; col[cs.color] = (col[cs.color] || 0) + t.length; } }
  const top = el => el.getBoundingClientRect().top + scrollY;
  const text = root.innerText || '';
  const emoji = text.match(/\p{Extended_Pictographic}/gu) || [];
  const foldText = all.filter(e => own(e) && top(e) < fold).map(own).join(' ');
  const navLinks = [...document.querySelectorAll('.grp a, .grp .row')].filter(vis).length;
  return {
    height: document.documentElement.scrollHeight, screens: +(document.documentElement.scrollHeight / fold).toFixed(1),
    hscroll: document.documentElement.scrollWidth > innerWidth + 2,
    words: text.split(/\s+/).filter(Boolean).length, wordsFold: foldText.split(/\s+/).filter(Boolean).length,
    emoji: emoji.length, fontSizes: Object.keys(fsz).length,
    fontSizesTop: Object.entries(fsz).sort((a, b) => b[1] - a[1]).map(x => x[0]).join(' '),
    textColors: Object.keys(col).length, buttons: [...root.querySelectorAll('button,.btn')].filter(vis).length,
    tips: [...root.querySelectorAll('.tip')].filter(vis).length, badges: [...root.querySelectorAll('.b,.chip,.pill,.tag')].filter(vis).length,
    menuLinks: navLinks,
  };
};

const hr = (x, d = 1) => String(Number(x).toFixed(d)).replace('.', ',');
function caption(m, key) {
  if (!m) return '';
  if (key === 'izbornik') return m.menuLinks != null && m.menuGroups != null
    ? `${m.menuLinks} poveznica u ${m.menuGroups} skupina · ladica ${hr(m.menuScreens)} ekrana · hamburger i Više otvaraju isto`
    : `${m.menuLinks} redaka u 4 skupine + Sustav · ${hr(m.screens)} ekrana`;
  const extra = m.tips ? ` · ${m.tips} ⓘ` : '';
  return `${hr(m.screens)} ekrana · ${m.words} riječi · ${m.emoji} emojija · ${m.fontSizes} veličina slova${extra}`;
}

(async () => {
  fs.mkdirSync(OUT, { recursive: true });
  const browser = await chromium.launch();
  const mFile = path.join(OUT, 'novo-metrics.json');
  const metrics = fs.existsSync(mFile) ? JSON.parse(fs.readFileSync(mFile, 'utf8')) : {};
  const sada = JSON.parse(fs.readFileSync(path.join(OUT, 'sada-metrics.json'), 'utf8'));
  const phone = { viewport: { width: 390, height: 844 }, deviceScaleFactor: 2, isMobile: true, hasTouch: true,
    userAgent: 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1' };
  const desk = { viewport: { width: 1280, height: 800 }, deviceScaleFactor: 2 };
  for (const [name, opts] of [['phone', phone], ['desktop', desk]]) {
    const ctx = await browser.newContext({ ...opts, locale: 'hr-HR', timezoneId: 'Europe/Zagreb' });
    const page = await ctx.newPage();
    for (const s of SCREENS) {
      await page.goto('file://' + path.join(__dirname, s.key + '.html'), { waitUntil: 'load' });
      await page.waitForTimeout(150);
      metrics[s.key] = metrics[s.key] || {};
      metrics[s.key][name] = await page.evaluate(METRICS);
      if (name === 'phone') await page.screenshot({ path: path.join(OUT, `novo-${s.key}-phone-fold.png`) });
      // donja traka je position:fixed; na snimci cijele stranice ide na dno (kao u shots.js za sada-*)
      if (name === 'phone' && !s.fixed) await page.addStyleTag({ content: '.tabs{position:static!important}main{padding-bottom:28px!important}' });
      await page.screenshot({ path: path.join(OUT, `novo-${s.key}-${name}.png`), fullPage: true });
      if (name === 'phone' && s.detail) fs.copyFileSync(path.join(OUT, `novo-${s.key}-phone.png`), path.join(OUT, `novo-${s.key}-phone-cijela.png`));
      console.log(name, s.key, JSON.stringify(metrics[s.key][name]));
    }
    await ctx.close();
  }
  fs.writeFileSync(mFile, JSON.stringify(metrics, null, 1));

  // usporedbe: prvi ekran mobitela, sada lijevo, novo desno
  const ctx = await browser.newContext({ viewport: { width: 880, height: 1000 }, deviceScaleFactor: 2 });
  const page = await ctx.newPage();
  for (const s of SCREENS) {
    const ms = (sada[s.m] || {}).phone, mn = (metrics[s.key] || {}).phone;
    const img = f => 'file://' + path.join(OUT, f);
    const html = `<!doctype html><html lang="hr"><meta charset="utf-8"><style>
      body{margin:0;background:#f6f7fb;font:15px/1.4 -apple-system,system-ui,Inter,sans-serif;color:#0b1220}
      .w{padding:22px 24px 26px}h1{font-size:22px;margin:0 0 16px;letter-spacing:-.02em}
      .g{display:grid;grid-template-columns:390px 390px;gap:28px}
      .c b{display:block;font-size:17px;margin:0 0 8px}.c img{display:block;width:390px;height:844px;object-fit:cover;object-position:top;
        border-radius:22px;border:1px solid #cfd5e1;background:#fff}.c p{margin:10px 2px 0;color:#5b6474;font-size:14px}</style>
      <div class="w"><h1>${s.title}: sada i novo (prvi ekran na mobitelu)</h1><div class="g">
      <div class="c"><b>Sada</b><img src="${img(s.sada)}"><p>${caption(ms, s.key)}</p></div>
      <div class="c"><b>Novo</b><img src="${img('novo-' + s.key + '-phone-fold.png')}"><p>${caption(mn, s.key)}</p></div>
      </div></div>`;
    const tmp = path.join(OUT, `.usporedba-${s.key}.html`);
    fs.writeFileSync(tmp, html);
    await page.goto('file://' + tmp, { waitUntil: 'load' });
    await page.waitForTimeout(100);
    await page.screenshot({ path: path.join(OUT, `usporedba-${s.key}.png`), fullPage: true });
    fs.unlinkSync(tmp);
    console.log('usporedba', s.key);
  }
  await browser.close();
})().catch(e => { console.error(e); process.exit(1); });
