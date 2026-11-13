// Snimke zaslona lokalne aplikacije (stanje "sada") za prijedlog dizajna, 10.11.2026.
//   node audit/2026-11-10/shots.js [--base http://127.0.0.1:8790] [--out <dir>] [--only kljuc1,kljuc2] [--prefix sada]
// Za svaki zaslon: <prefix>-<kljuc>-phone.png (cijela stranica, 390x844 @2x), -phone-fold.png (samo prvi ekran),
// -desktop.png (cijela stranica, 1280x800 @2x) i redak u <prefix>-metrics.json (brojanje onoga što se VIDI).
const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');

const arg = (k, d) => { const i = process.argv.indexOf('--' + k); return i > 0 ? process.argv[i + 1] : d; };
const BASE = arg('base', 'http://127.0.0.1:8790');
const OUT = arg('out', '/tmp/claude-0/-home-user/4912361d-d525-5b3e-b714-652a838e02b7/scratchpad/shots/ui');
const ONLY = (arg('only', '') || '').split(',').filter(Boolean);
const PREFIX = arg('prefix', 'sada');
const USER = arg('user', 'Jure'), PASS = arg('pass', 'demo');
const SEED = JSON.parse(fs.readFileSync(path.join(__dirname, 'local', 'seed.json'), 'utf8'));

// key, path, login needed, optional action after load (phone only unless both:true)
const SCREENS = [
  { key: 'pregled', path: '/pregled', title: 'Pregled (početna nakon prijave)' },
  { key: 'tokeni', path: '/tokens', title: 'Tokeni: prijedlozi' },
  { key: 'token', path: '/token/' + SEED.token, title: 'Jedan token' },
  { key: 'influenceri', path: '/kol', title: 'Influenceri (kako se otvori)' },
  { key: 'influenceri-ljestvica', path: '/kol', title: 'Influenceri: otvorena ljestvica "Najbolji influenceri"', open: 'Najbolji influenceri' },
  { key: 'influencer', path: '/kol/' + SEED.kol, title: 'Jedan influencer' },
  { key: 'novcanici', path: '/wallets', title: 'Novčanici' },
  { key: 'natjecanje', path: '/natjecanje', title: 'Natjecanje' },
  { key: 'copy', path: '/copy-trading', title: 'Copy trading' },
  { key: 'autopilot', path: '/pravi-trade', title: 'Autopilot (pravi novac)' },
  { key: 'izbornik', path: '/pregled', title: 'Izbornik "Više" (ladica)', menu: true },
  { key: 'mapa', path: '/mapa', title: 'Sve stranice' },
  { key: 'postavke', path: '/postavke', title: 'Postavke' },
  // drugi krug (10.11.): jedan novčanik (Vfdn…At74 iz seed_app.py, isti kao u prijedlogu na Pregledu)
  { key: 'novcanik', path: '/wallet/VfdnxFG33CM2rVeYegb6ooV5xEPLuhKYGhBPa5aWAt74', title: 'Jedan novčanik' },
  { key: 'naslovna', path: '/hr', title: 'Javna naslovna stranica', anon: true },
  { key: 'prijava', path: '/prijava', title: 'Prijava', anon: true },
];

const METRICS = () => {
  // vidljivo = ima površinu i nije u sklopljenom <details> (Chromium to skriva s content-visibility, pa treba checkVisibility)
  const vis = el => { const r = el.getBoundingClientRect();
    return r.width > 0 && r.height > 0 && (!el.checkVisibility || el.checkVisibility({ checkOpacity: true, checkVisibilityCSS: true })); };
  const root = document.querySelector('main') || document.body, fold = innerHeight;
  const all = [...root.querySelectorAll('*')].filter(vis);
  const own = el => [...el.childNodes].filter(n => n.nodeType === 3).map(n => n.textContent).join('').trim();
  const fsz = {}, col = {}, bgs = {};
  for (const el of all) { const t = own(el); const cs = getComputedStyle(el);
    if (t) { fsz[cs.fontSize] = (fsz[cs.fontSize] || 0) + t.length; col[cs.color] = (col[cs.color] || 0) + t.length; }
    const b = cs.backgroundColor; if (b && b !== 'rgba(0, 0, 0, 0)' && b !== 'rgb(255, 255, 255)') bgs[b] = (bgs[b] || 0) + 1; }
  const top = el => el.getBoundingClientRect().top + scrollY;
  const n = sel => all.filter(e => e.matches(sel));
  const text = root.innerText || '';
  const emoji = text.match(/\p{Extended_Pictographic}/gu) || [];
  const foldText = all.filter(e => own(e) && top(e) < fold).map(own).join(' ');
  const boxes = n('.card,.stat,.tw,main>details,.intro,.cand,a.mapcard,.quick a,ul.core-list,.gl-term,.verdict,section,article');
  const tables = n('table'), wraps = n('.tw');
  const paras = all.filter(e => e.matches('p,li,div,span,td,summary,small') && own(e).length > 160);
  return {
    height: document.documentElement.scrollHeight, screens: +(document.documentElement.scrollHeight / fold).toFixed(1),
    hscroll: document.documentElement.scrollWidth > innerWidth + 2,
    h1: n('h1').length, h2: n('h2').length, h3: n('h3').length,
    boxes: boxes.length, boxesFold: boxes.filter(e => top(e) < fold).length,
    headingsFold: n('h1,h2,h3').filter(e => top(e) < fold).length,
    detailsClosed: n('details:not([open])').length, detailsOpen: n('details[open]').length,
    tables: tables.length, tablesOverflow: wraps.filter(w => w.scrollWidth > w.clientWidth + 4).length
      + tables.filter(t => !t.closest('.tw') && t.scrollWidth > innerWidth).length,
    maxCols: Math.max(0, ...tables.map(t => (t.rows[0] ? t.rows[0].cells.length : 0))),
    buttons: n('button,input[type=submit],a.btn,.btn').length, inputs: n('input:not([type=hidden]),select,textarea').length,
    links: n('a[href]').length, badges: n('.b,.chip,.gl-chip,.pill,.tag').length, tips: n('.tip').length,
    emoji: emoji.length, emojiKinds: new Set(emoji).size, emojiFold: (foldText.match(/\p{Extended_Pictographic}/gu) || []).length,
    words: text.split(/\s+/).filter(Boolean).length, wordsFold: foldText.split(/\s+/).filter(Boolean).length,
    longParas: paras.length,
    fontSizes: Object.keys(fsz).length, fontSizesTop: Object.entries(fsz).sort((a, b) => b[1] - a[1]).slice(0, 8).map(x => x[0]).join(' '),
    textColors: Object.keys(col).length, textColorsTop: Object.entries(col).sort((a, b) => b[1] - a[1]).slice(0, 8).map(x => x[0]).join(' | '),
    bgColors: Object.keys(bgs).length,
  };
};

async function open(page, s) {
  for (let i = 0; i < 30; i++) {                       // teške stranice se prvi put grade u pozadini (503 koji se sam osvježava)
    const r = await page.goto(BASE + s.path, { waitUntil: 'domcontentloaded', timeout: 120000 });
    if (r && r.status() !== 503) return r.status();
    await page.waitForTimeout(3000);
  }
  return 503;
}

(async () => {
  fs.mkdirSync(OUT, { recursive: true });
  const browser = await chromium.launch();
  const metricsFile = path.join(OUT, PREFIX + '-metrics.json');
  const metrics = fs.existsSync(metricsFile) ? JSON.parse(fs.readFileSync(metricsFile, 'utf8')) : {};
  const devices = [
    { name: 'phone', opts: { viewport: { width: 390, height: 844 }, deviceScaleFactor: 2, isMobile: true, hasTouch: true,
        userAgent: 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1' } },
    { name: 'desktop', opts: { viewport: { width: 1280, height: 800 }, deviceScaleFactor: 2 } },
  ];
  for (const d of devices) {
    for (const anon of [false, true]) {
      const list = SCREENS.filter(s => !!s.anon === anon && (!ONLY.length || ONLY.includes(s.key)));
      if (!list.length) continue;
      const ctx = await browser.newContext({ ...d.opts, locale: 'hr-HR', timezoneId: 'Europe/Zagreb' });
      const page = await ctx.newPage();
      if (!anon) {
        await page.goto(BASE + '/prijava', { waitUntil: 'domcontentloaded' });
        await page.fill('#name', USER); await page.fill('#pw', PASS);
        await Promise.all([page.waitForNavigation({ waitUntil: 'domcontentloaded' }), page.click('button.go')]);
      }
      for (const s of list) {
        const t0 = Date.now();
        const status = await open(page, s);
        await page.waitForTimeout(s.wait || 1800);       // dijelovi koji se dohvaćaju svake sekunde (Autopilot) nikad ne "miruju"
        if (!s.menu) {                                   // prođi stranicu do dna da se učitaju slike s loading=lazy, pa natrag na vrh
          await page.evaluate(async () => { const h = document.documentElement.scrollHeight;
            for (let y = 0; y < h; y += 700) { scrollTo(0, y); await new Promise(r => setTimeout(r, 40)); } scrollTo(0, 0); });
          await page.waitForTimeout(400);
        }
        if (s.menu && d.name === 'phone') { await page.click('.bbar button[data-nav]'); await page.waitForTimeout(500); }
        if (s.open) {                                    // sekcija koja je na stranici sklopljena: otvori je dodirom kao korisnik
          const sum = page.locator('main summary', { hasText: s.open }).first();
          if (await sum.count()) { await sum.scrollIntoViewIfNeeded(); await sum.click(); await page.waitForTimeout(1200); await page.evaluate(() => scrollTo(0, 0)); await page.waitForTimeout(200); }
        }
        const f = (suffix) => path.join(OUT, `${PREFIX}-${s.key}-${d.name}${suffix}.png`);
        if (d.name === 'phone') await page.screenshot({ path: f('-fold') });
        if (s.menu) {                                    // izbornik: koliko stavki i grupa vidi administrator
          metrics[s.key] = metrics[s.key] || {};
          metrics[s.key][d.name] = { status, path: s.path, ...(await page.evaluate(() => {
            const a = document.querySelector('aside.side'); const v = e => !e.checkVisibility || e.checkVisibility();
            return { menuLinks: [...a.querySelectorAll('a')].filter(v).length, menuGroups: [...a.querySelectorAll('h4')].filter(v).length,
              menuHeight: a.scrollHeight, menuScreens: +(a.scrollHeight / innerHeight).toFixed(1),
              bottomBar: [...document.querySelectorAll('.bbar a,.bbar button')].filter(v).length }; })) };
          if (d.name === 'phone') {                      // drugi dio ladice (pomaknuto do dna)
            await page.evaluate(() => { const a = document.querySelector('aside.side'); a.scrollTop = a.scrollHeight; });
            await page.waitForTimeout(300); await page.screenshot({ path: f('-dno') });
            await page.evaluate(() => { document.querySelector('aside.side').scrollTop = 0; }); await page.waitForTimeout(200);
          }
        } else if (!(s.menu && d.name === 'phone')) {
          metrics[s.key] = metrics[s.key] || {}; metrics[s.key][d.name] = { status, path: s.path, ...(await page.evaluate(METRICS)) };
        }
        // donja traka je position:fixed; na snimci cijele stranice ostala bi usred slike, pa je za tu snimku stavljamo na dno
        if (d.name === 'phone' && !s.menu) await page.addStyleTag({ content: '.bbar{position:static!important}' });
        await page.screenshot({ path: f(''), fullPage: !(s.menu && d.name === 'phone') });
        console.log(`${d.name} ${s.key} ${status} ${Date.now() - t0} ms`);
      }
      await ctx.close();
    }
  }
  fs.writeFileSync(metricsFile, JSON.stringify(metrics, null, 1));
  await browser.close();
})().catch(e => { console.error(e); process.exit(1); });
