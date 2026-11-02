"""Navigation of the public site: one menu, grouped by topic, used everywhere.

Top bar (desktop dropdowns), ☰ phone menu, footer columns and the landing page "Explore" block all come from MENU, so
every public page is reachable from every other page (internal links for SEO) and a new section is added in one place.

Other modules can add items without touching this file: a module listed in PLUGINS may define
`nav_items(lang) -> [(group_key, href, label, description)]` (e.g. blog categories).
"""
import importlib

from ui.html import esc

# group key -> (label, hub href, one-line description)
GROUPS = {
    "en": {"coins": ("Meme coins", "/solana-meme-coins", "Live data on the top 100 Solana meme coins"),
           "kols": ("Influencers", "/influencers", "Every crypto influencer call measured"),
           "tools": ("Tools", "/best-crypto-tools", "Crypto tools compared, with prices"),
           "learn": ("Learn", "/blog", "Guides, tax, exchanges and a glossary")},
    "hr": {"coins": ("Meme coini", "/hr/solana-meme-coini", "Podaci uživo o top 100 Solana meme coina"),
           "kols": ("Influenceri", "/hr/influenceri", "Svaki poziv kripto influencera izmjeren"),
           "tools": ("Alati", "/hr/najbolji-kripto-alati", "Usporedba kripto alata s cijenama"),
           "learn": ("Uči", "/hr/blog", "Vodiči, porezi, burze i rječnik")},
}

ITEMS = {
    "en": [
        ("coins", "/solana-meme-coins", "Top 100 Solana meme coins", "Ranked by market cap, with charts"),
        ("coins", "/solana-meme-coins/gainers", "Top gainers today", "Biggest 24 h price gains"),
        ("coins", "/solana-meme-coins/trending", "Trending today", "Most traders in 24 h"),
        ("coins", "/solana-meme-coins/new", "New coins", "Youngest coins in the top 100"),
        ("coins", "/how-to-buy", "How to buy", "Step-by-step for every coin"),
        ("coins", "/rug-check", "Rug checks", "Safety score for every coin"),
        ("kols", "/influencers", "Influencer ranking", "Hit rate, rugs and late calls"),
        ("kols", "/glossary/call-power", "How we score calls", "What call power means"),
        ("kols", "/glossary/kol", "What is a KOL?", "Crypto influencers explained"),
        ("tools", "/best-crypto-tools", "All crypto tools", "The full comparison"),
        ("learn", "/blog", "Blog", "All articles"),
        ("learn", "/glossary", "Crypto glossary", "Terms explained in plain words"),
    ],
    "hr": [
        ("coins", "/hr/solana-meme-coini", "Top 100 Solana meme coina", "Po market capu, s grafovima"),
        ("coins", "/hr/solana-meme-coini/rastuci", "Najveći rast danas", "Najveći skok cijene u 24 h"),
        ("coins", "/hr/solana-meme-coini/popularni", "Popularni danas", "Najviše tradera u 24 h"),
        ("coins", "/hr/solana-meme-coini/novi", "Novi coini", "Najmlađi coini u top 100"),
        ("coins", "/hr/kako-kupiti", "Kako kupiti", "Korak po korak za svaki coin"),
        ("coins", "/hr/provjera", "Provjera ruga", "Sigurnosna ocjena za svaki coin"),
        ("kols", "/hr/influenceri", "Ljestvica influencera", "Pogodak, rugovi i kasni pozivi"),
        ("kols", "/hr/rjecnik/moc-poziva", "Kako ocjenjujemo pozive", "Što znači moć poziva"),
        ("kols", "/hr/rjecnik/kol", "Što je KOL?", "Kripto influenceri objašnjeni"),
        ("tools", "/hr/najbolji-kripto-alati", "Svi kripto alati", "Cijela usporedba"),
        ("learn", "/hr/blog", "Blog", "Svi članci"),
        ("learn", "/hr/rjecnik", "Kripto rječnik", "Pojmovi objašnjeni jednostavno"),
    ],
}

PLUGINS = ("ui.blog", "ui.coinseo", "ui.botguides", "ui.marketpub")


def _tools_items(lang):
    try:
        from ui import toolsdata as T
    except Exception:  # noqa: BLE001
        return []
    base = "/best-crypto-tools/" if lang == "en" else "/hr/najbolji-kripto-alati/"
    return [("tools", base + c[f"{lang}_slug"], c[lang]["short"], "") for c in T.CATS]


def menu(lang):
    """[(key, label, hub, desc, [(href, label, desc)])] in display order."""
    lang = "en" if lang == "en" else "hr"
    items = list(ITEMS[lang]) + _tools_items(lang)
    for mod in PLUGINS:
        try:
            fn = getattr(importlib.import_module(mod), "nav_items", None)
            if fn:
                items += [tuple(x) for x in fn(lang)]
        except Exception:  # noqa: BLE001  (a broken plugin must not take the menu down)
            pass
    seen, out = set(), []
    for key, (label, hub, desc) in GROUPS[lang].items():
        rows = []
        for k, h, n, d in items:
            if k == key and h not in seen:
                seen.add(h)
                rows.append((h, n, d))
        out.append((key, label, hub, desc, rows))
    return out


def nav(lang):
    """Desktop top bar: each group is a link to its hub with a dropdown (CSS only, works on hover and keyboard focus)."""
    out = []
    for _k, label, hub, _d, rows in menu(lang):
        dd = "".join(f"<a href={h}><b>{esc(n)}</b>" + (f"<span>{esc(d)}</span>" if d else "") + "</a>"
                     for h, n, d in rows)
        out.append(f"<div class='dd hm'><a class=lnk href={hub} aria-haspopup=true aria-expanded=false>{esc(label)} <i>▾</i></a>"
                   f"<div class=ddm>{dd}</div></div>")
    return "".join(out) + DD_JS


# Touch screens have no hover: the first tap on a group opens its dropdown, a second tap opens the hub page.
# A tap/click outside or Esc closes it. On a mouse the dropdown opens on hover and stays ~0.3 s after the
# pointer leaves (CSS above), so moving down to an item never closes it.
DD_JS = ("<script>(function(){if(window.__dd)return;window.__dd=1;var T=matchMedia('(hover:none)');"
         "function shut(k){document.querySelectorAll('.dd.open').forEach(function(d){if(d!==k){d.classList.remove('open');"
         "d.firstChild.setAttribute('aria-expanded','false')}})}"
         "document.addEventListener('click',function(e){var a=e.target.closest&&e.target.closest('.dd>.lnk');"
         "if(a){var d=a.parentNode;if(T.matches&&!d.classList.contains('open')){e.preventDefault();shut(d);"
         "d.classList.add('open');a.setAttribute('aria-expanded','true');return}}"
         "if(!(e.target.closest&&e.target.closest('.dd')))shut()});"
         "document.addEventListener('keydown',function(e){if(e.key==='Escape'){shut();"
         "if(document.activeElement&&document.activeElement.closest&&document.activeElement.closest('.dd'))document.activeElement.blur()}})"
         "})()</script>")


def mobile(lang):
    """Phones: ☰ opens all groups (a <details> element, no JS)."""
    home, req = ("/", "Request access") if lang == "en" else ("/hr", "Zatraži pristup")
    groups = "".join(f"<p class=mg>{esc(label)}</p>" + "".join(f"<a href={h}>{esc(n)}</a>" for h, n, _d in rows)
                     for _k, label, _hub, _d, rows in menu(lang))
    return (f"<details class=mnav><summary aria-label=Menu>☰</summary><div>{groups}"
            f"<a class='btn p sm' href={home}#pristup>{req}</a></div></details>")


def footer(lang):
    cols = "".join(f"<div><b><a href={hub}>{esc(label)}</a></b>" + "".join(f"<a href={h}>{esc(n)}</a>" for h, n, _d in rows)
                   + "</div>" for _k, label, hub, _d, rows in menu(lang))
    return f"<div class=fcols>{cols}</div>"


def explore(lang):
    """Landing page: one card per group with its links."""
    out = []
    for _k, label, hub, desc, rows in menu(lang):
        links = "".join(f"<a href={h}>{esc(n)} →</a>" for h, n, _d in rows[:8])
        out.append(f"<div class=exc><a class=exh href={hub}><b>{esc(label)}</b><span>{esc(desc)}</span></a>"
                   f"<div class=exl>{links}</div></div>")
    return f"<div class=exg>{''.join(out)}</div>"


def _fmt_usd(x):
    if not x:
        return "–"
    for d, u in ((1e9, "B"), (1e6, "M"), (1e3, "k")):
        if x >= d:
            return f"${x / d:.1f}{u}"
    return f"${x:.0f}"


def coin_board(lang):
    """Landing page: interactive live board (tabs Top / Gainers / Trending / New) of the top Solana meme coins.
    Every row is a real link to the coin page, all tabs are in the HTML (crawlable), a few lines of JS switch them."""
    try:
        from ui import coins as K
        from ui import coinseo as CS
        rows = K.top()
    except Exception:  # noqa: BLE001
        return ""
    if len(rows) < 8:
        return ""
    en = lang == "en"
    prof = "/coin/" if en else "/hr/coin/"
    tabs = [("top", "Top 100" if en else "Top 100", rows, "/solana-meme-coins" if en else "/hr/solana-meme-coini")]
    for kind, name in (("gainers", "Gainers" if en else "Rast"), ("trending", "Trending" if en else "Popularni"),
                       ("new", "New" if en else "Novi")):
        try:
            tabs.append((kind, name, CS._pick(kind, list(rows)), CS.LISTS[kind][lang]))
        except Exception:  # noqa: BLE001
            pass
    head, panes = [], []
    for i, (kind, name, lst, more) in enumerate(tabs):
        lst = lst[:8]
        if not lst:
            continue
        top = max(abs(x.get("chg24h") or 0) for x in lst) or 1
        trs = []
        for x in lst:
            c = x.get("chg24h") or 0
            w = max(3, min(100, abs(c) / top * 100))
            icon = (f"<img src=\"{esc(x['icon'])}\" alt='' width=22 height=22 loading=lazy referrerpolicy=no-referrer "
                    "onerror=\"this.style.visibility='hidden'\">" if str(x.get("icon") or "").startswith("https://") else "<i></i>")
            trs.append(f"<a class=br href={prof}{x['slug']}>{icon}<b>{esc(x['symbol'] or '')}</b>"
                       f"<span class=bm>{_fmt_usd(x.get('mcap'))}</span>"
                       f"<span class=bb><em class={'up' if c >= 0 else 'dn'} style='width:{w:.0f}%'></em></span>"
                       f"<span class='bc {'up' if c >= 0 else 'dn'}'>{c:+.1f}%</span></a>")
        head.append(f"<button type=button data-t={kind} class='{'on' if i == 0 else ''}'>{name}</button>")
        panes.append(f"<div class=bp data-p={kind}{'' if i == 0 else ' hidden'}>{''.join(trs)}"
                     f"<a class=bmore href={more}>{'See the full list' if en else 'Cijela lista'} →</a></div>")
    js = ("document.querySelectorAll('.board').forEach(b=>b.querySelectorAll('button[data-t]').forEach(t=>t.onclick=()=>{"
          "b.querySelectorAll('button[data-t]').forEach(x=>x.classList.toggle('on',x===t));"
          "b.querySelectorAll('.bp').forEach(p=>p.hidden=p.dataset.p!==t.dataset.t)}))")
    title = "Solana meme coins right now" if en else "Solana meme coini upravo sada"
    note = "24 h change · updated every 3 hours" if en else "Promjena u 24 h · osvježava se svaka 3 sata"
    return (f"<div class=board><div class=bt><b>{title}</b><span>{note}</span></div><div class=btabs>{''.join(head)}</div>"
            f"{''.join(panes)}</div><script>{js}</script>")


CSS = """
.dd{position:relative}.dd>.lnk i{font-style:normal;font-size:10px;opacity:.6}
nav.top{z-index:100}
.ddm{display:grid;gap:2px;visibility:hidden;opacity:0;transform:translateY(4px);position:absolute;left:-14px;top:100%;padding:10px;
background:#fff;border:1px solid var(--line);border-radius:16px;min-width:280px;max-height:calc(100vh - 80px);overflow:auto;
box-shadow:0 24px 60px -24px rgba(11,18,32,.35);z-index:100;transition:opacity .15s .3s,transform .15s .3s,visibility 0s .45s}
.dd:hover .ddm,.dd:focus-within .ddm,.dd.open .ddm{visibility:visible;opacity:1;transform:none;transition-delay:0s}
.dd:before{content:"";position:absolute;left:-14px;right:-14px;top:100%;height:14px}
.ddm a{display:block;padding:9px 12px;border-radius:10px}.ddm a:hover{background:var(--soft)}
.ddm b{display:block;font-size:14.5px;font-weight:600;color:var(--fg)}.ddm span{display:block;font-size:12.5px;color:var(--mut)}
.mnav{display:none;position:relative}.mnav summary{list-style:none;cursor:pointer;font-size:22px;line-height:1;padding:6px 4px}
.mnav summary::-webkit-details-marker{display:none}.mnav summary:after{content:none!important}
.mnav>div{position:absolute;right:0;top:44px;background:#fff;border:1px solid var(--line);border-radius:16px;padding:8px 8px 10px;
width:min(300px,86vw);max-height:75vh;overflow:auto;box-shadow:0 20px 50px -20px rgba(11,18,32,.35);display:grid;gap:0;z-index:40}
.mnav>div a{padding:9px 12px;border-radius:10px;font-weight:520;font-size:15px}.mnav>div a:hover{background:var(--soft)}
.mnav .mg{margin:10px 12px 2px;font-size:12px;font-weight:700;text-transform:uppercase;letter-spacing:.06em;color:var(--mut)}
.mnav>div a.btn{display:flex!important;margin-top:8px;color:#fff}
@media(max-width:760px){.mnav{display:block}}
.fcols{display:grid;grid-template-columns:repeat(4,1fr);gap:24px;text-align:left;margin:0 auto 28px;max-width:1040px}
.fcols div{display:grid;gap:6px;align-content:start}.fcols b a{color:var(--fg);font-size:14px}.fcols a{color:var(--mut);font-size:13.5px}
.fcols a:hover{color:var(--fg)}@media(max-width:760px){.fcols{grid-template-columns:1fr 1fr}}
.exg{margin-top:22px;display:grid;grid-template-columns:repeat(4,1fr);gap:14px}@media(max-width:960px){.exg{grid-template-columns:1fr 1fr}}
@media(max-width:560px){.exg{grid-template-columns:1fr}}
.exc{border:1px solid var(--line);border-radius:20px;padding:20px;background:#fff}
.exh{display:block;margin-bottom:10px}.exh b{display:block;font-size:18px;color:var(--fg)}.exh span{color:var(--mut);font-size:14px}
.exl{display:grid;gap:4px}.exl a{color:var(--acc);font-size:14.5px;font-weight:550}
.board{border:1px solid var(--line);border-radius:24px;background:#fff;padding:22px;box-shadow:0 30px 60px -40px rgba(11,18,32,.25);
max-width:760px;margin:0 auto}
.bt{display:flex;justify-content:space-between;align-items:baseline;gap:10px;flex-wrap:wrap}.bt b{font-size:18px}.bt span{color:var(--mut);font-size:13px}
.btabs{display:flex;gap:6px;margin:14px 0 10px;flex-wrap:wrap}.btabs button{border:1px solid var(--line);background:#fff;border-radius:999px;
padding:7px 14px;font:inherit;font-size:14px;cursor:pointer;color:var(--mut)}.btabs button.on{background:var(--fg);color:#fff;border-color:var(--fg)}
.br{display:grid;grid-template-columns:24px 90px 70px 1fr 66px;gap:10px;align-items:center;padding:9px 6px;border-radius:12px}
.br:hover{background:var(--soft)}.br img,.br i{width:22px;height:22px;border-radius:50%;background:#eef;display:block}
.br b{font-size:15px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.bm{color:var(--mut);font-size:13px;font-variant-numeric:tabular-nums}
.bb{height:8px;background:var(--soft);border-radius:8px;overflow:hidden}.bb em{display:block;height:100%;border-radius:8px}
.bb em.up{background:#22c55e}.bb em.dn{background:#ef4444}
.bc{text-align:right;font-weight:650;font-size:14px;font-variant-numeric:tabular-nums}.bc.up{color:#16a34a}.bc.dn{color:#dc2626}
.bmore{display:block;text-align:center;margin-top:8px;color:var(--acc);font-weight:600;font-size:14.5px}
@media(max-width:520px){.br{grid-template-columns:22px 1fr 60px 64px}.bb{display:none}.board{padding:16px}}
"""
