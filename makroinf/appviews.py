"""The interpretation and the library in the app (15.11. navečer, the owner: "... reći 55 % influencera na primjer je
bullish, 45 % bearish, što znači da je neizvjesno ... Ali isto tako i prikazati iz čega su izvučeni ti podaci i
tablice, da budu uredne, strukturirane"; "sve to treba spremati u library"), for every logged-in user, in the
"Makro" tab of Influenceri (/kol) and its sub-view Biblioteka (/kol-makro/biblioteka):

  overview_html()   the tab's top: the market mood of the last 24 h and 7 days (unweighted and weighted by accuracy,
                    the verdict rule printed), the topics of the day, the stance changes, the mood per asset and the
                    last 14 days; every statement with its "Iz čega je izvučeno" (the counts, the accounts, the posts)
  library_page(qs)  every stored post with its classification, filtered by account, asset, side, horizon, date, words
Fresh (members): no 7-day delay here. Never in these views: keys, env names, internal services, costs, model names,
wallet or token addresses. Layout: the app's CSS variables, the segmented style of the tabs, tables that fold into
rows on a 390-px phone.
"""
import time
from urllib.parse import quote, urlencode

from makroinf import library, mood, rules, store, teme

D = 86400
SIDE_HR = {"bik": "Bikovski", "medvjed": "Medvjeđi", "neutralno": "Neutralno"}
SIDE_TONE = {"bik": "good", "medvjed": "bad", "neutralno": ""}
ASSET_HR = {"BTC": "BTC", "ETH": "ETH", "SOL": "SOL", "alts": "Altcoini", "memes": "Meme coini",
            "total": "Kripto tržište"}
DIR_HR = {"up": "gore", "down": "dolje", "bottom_in": "dno je tu", "top_in": "vrh je tu", "range": "raspon"}
HZ_HR = {"7": "7 d", "30": "30 d", "oba": "bez roka", "dugo": "> 60 d"}
WIN_HR = {"24h": "Zadnja 24 h", "7d": "Zadnjih 7 dana"}
LIB = "/kol-makro/biblioteka"

CSS = """
.mi-seg{display:flex;background:var(--soft);border-radius:11px;padding:3px;margin:16px 0 0;max-width:420px}
.mi-seg a{flex:1;text-align:center;font-size:14.5px;padding:6px 0;border-radius:9px;white-space:nowrap;color:var(--fg);text-decoration:none}
.mi-seg a.on{background:#fff;font-weight:600;box-shadow:0 1px 3px rgba(11,18,32,.12)}
.mi-mood{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px;margin:14px 0 0}
@media(max-width:640px){.mi-mood{grid-template-columns:1fr}}
.mi-mc{background:var(--card);border:1px solid var(--line);border-radius:16px;padding:14px 16px;min-width:0}
.mi-mc .l{font-size:13px;color:var(--mut)}.mi-mc .v{font-size:24px;font-weight:700;letter-spacing:-.02em;margin:3px 0 8px;
display:flex;align-items:center;gap:9px}.mi-mc .v i{width:11px;height:11px;border-radius:50%;background:var(--line2);flex:none}
.mi-mc .v i.good{background:var(--good)}.mi-mc .v i.bad{background:var(--bad)}
.mi-mc .w{font-size:14px;color:var(--mut);line-height:1.45;margin-top:6px}.mi-mc .w b{color:var(--fg);font-weight:600}
.mi-bar{display:flex;height:9px;border-radius:999px;overflow:hidden;background:var(--soft)}
.mi-bar span{display:block;height:100%}.mi-bar .b{background:var(--good)}.mi-bar .n{background:var(--line2)}
.mi-bar .m{background:var(--bad)}
.mi-rule{font-size:13px;color:var(--mut);margin:10px 0 0;line-height:1.45}
details.mi-src{border:1px solid var(--line);border-radius:14px;margin:10px 0 0;background:var(--card)}
details.mi-src>summary{cursor:pointer;list-style:none;padding:11px 14px;font-size:14.5px;font-weight:600;display:flex;
align-items:baseline;gap:10px}details.mi-src>summary::-webkit-details-marker{display:none}
details.mi-src>summary span{font-weight:400;color:var(--mut);font-size:13.5px;white-space:nowrap;margin-left:auto}
details.mi-src>summary:after{content:"+";color:var(--mut);font-weight:400}details.mi-src[open]>summary:after{content:"−"}
.mi-src .in{padding:0 14px 12px}
table.mi-t{width:100%;border-collapse:collapse;font-size:14px;margin:2px 0 6px}
table.mi-t th{font-weight:500;color:var(--mut);font-size:12.5px;text-align:left;padding:7px 6px;border-bottom:1px solid var(--line)}
table.mi-t td{padding:8px 6px;border-bottom:1px solid var(--line);vertical-align:top}
table.mi-t tr:last-child td{border-bottom:0}table.mi-t .n{text-align:right;white-space:nowrap;font-variant-numeric:tabular-nums}
table.mi-t td.good{color:var(--good);font-weight:600}
@media(max-width:420px){table.mi-t th,table.mi-t td{padding:7px 4px}table.mi-t{font-size:13.5px}}
table.mi-t .sm{font-size:12.5px;color:var(--mut);margin-top:2px}table.mi-t .sm a{color:var(--acc);text-decoration:none}
table.mi-t td a{color:var(--acc);text-decoration:none}table.mi-t td.bad{color:var(--bad);font-weight:600}
.mi-who{margin:8px 0 0;font-size:13.5px;line-height:1.9}.mi-who>b{display:block;font-size:13px;color:var(--mut);font-weight:500;line-height:1.4;margin-top:6px}
.mi-chip{display:inline-flex;align-items:baseline;gap:3px;margin:0 6px 0 0;white-space:nowrap}
.mi-chip a{color:var(--acc);text-decoration:none}.mi-chip a.p{font-size:11.5px;color:var(--mut);border:1px solid var(--line);
border-radius:6px;padding:0 4px;line-height:1.5}
.mi-more{font-size:13.5px;margin:8px 0 0}.mi-more a{color:var(--acc);text-decoration:none}
ol.mi-top{list-style:none;padding:0;margin:8px 0 0;counter-reset:t}
ol.mi-top>li{counter-increment:t;border-bottom:1px solid var(--line);padding:12px 0 12px 30px;position:relative}
ol.mi-top>li:before{content:counter(t);position:absolute;left:2px;top:12px;font-size:15px;color:var(--mut)}
ol.mi-top .t{font-size:16.5px;font-weight:600}ol.mi-top .s{font-size:14.5px;color:var(--fg);margin:2px 0 0;line-height:1.45}
ol.mi-top .m{font-size:13px;color:var(--mut);margin:3px 0 0}ol.mi-top details.mi-src{margin-top:8px}
.mi-up{color:var(--good);font-weight:600}.mi-dn{color:var(--bad);font-weight:600}.mi-fl{font-weight:600}
form.mi-f{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:8px;margin:14px 0 0}
@media(max-width:700px){form.mi-f{grid-template-columns:repeat(2,minmax(0,1fr))}}
form.mi-f label{display:flex;flex-direction:column;gap:3px;font-size:12.5px;color:var(--mut);min-width:0}
form.mi-f select,form.mi-f input{font:inherit;font-size:15px;color:var(--fg);background:var(--card);border:1px solid var(--line);
border-radius:10px;padding:8px 9px;min-width:0;width:100%;box-sizing:border-box}
form.mi-f .go{display:flex;align-items:flex-end;gap:8px}form.mi-f button{font:inherit;font-size:15px;font-weight:600;
background:var(--acc);color:#fff;border:0;border-radius:10px;padding:9px 14px;cursor:pointer;flex:1}
form.mi-f .go a{font-size:14px;color:var(--mut);text-decoration:none;padding:9px 4px;white-space:nowrap}
.mi-cnt{font-size:14px;color:var(--mut);margin:14px 0 4px}
table.mi-lib{width:100%;border-collapse:collapse;font-size:14.5px;table-layout:fixed}
table.mi-lib col.cd{width:96px}table.mi-lib col.ch{width:150px}table.mi-lib col.cc{width:190px}table.mi-lib col.ce{width:108px}
table.mi-lib th{font-weight:500;color:var(--mut);font-size:12.5px;text-align:left;padding:8px 8px;border-bottom:1px solid var(--line)}
table.mi-lib td{padding:10px 8px;border-bottom:1px solid var(--line);vertical-align:top}
table.mi-lib td.d{white-space:nowrap;color:var(--mut);font-size:13.5px}table.mi-lib td.h a{color:var(--fg);font-weight:600;text-decoration:none;overflow-wrap:anywhere}
table.mi-lib .tx{line-height:1.45;overflow-wrap:anywhere;display:-webkit-box;-webkit-line-clamp:5;-webkit-box-orient:vertical;overflow:hidden}
table.mi-lib .qt{color:var(--mut);font-size:13px;margin-top:4px;border-left:2px solid var(--line);padding-left:7px;overflow-wrap:anywhere}
table.mi-lib .po{font-size:13px;margin-top:4px}table.mi-lib .po a{color:var(--acc);text-decoration:none}
table.mi-lib td.e{white-space:nowrap;text-align:right;color:var(--mut);font-size:13px;font-variant-numeric:tabular-nums}
.mi-cl{display:inline-block;font-size:12.5px;border-radius:999px;padding:2px 8px;border:1px solid var(--line);background:var(--soft);
margin:0 4px 4px 0;white-space:nowrap}.mi-cl.good{background:var(--goodbg)}.mi-cl.bad{background:var(--badbg)}.mi-cl.mut{color:var(--mut)}
@media(max-width:700px){table.mi-lib,table.mi-lib tbody{display:block}table.mi-lib thead,table.mi-lib colgroup{display:none}
table.mi-lib td.d br{display:none}table.mi-lib td.e br{display:none}table.mi-lib td.e{white-space:normal}
table.mi-lib tr{display:grid;grid-template-columns:minmax(0,1fr) auto;column-gap:10px;padding:11px 0;border-bottom:1px solid var(--line)}
table.mi-lib td{display:block;border:0;padding:0}table.mi-lib td.h{grid-column:1;grid-row:1}
table.mi-lib td.d{grid-column:2;grid-row:1;text-align:right}table.mi-lib td.c{grid-column:1/3;margin-top:5px}
table.mi-lib td.x{grid-column:1/3;margin-top:2px}table.mi-lib td.e{grid-column:1/3;text-align:left;margin-top:4px}}
.mi-pg{display:flex;justify-content:space-between;margin:14px 0 0;font-size:15px}.mi-pg a{color:var(--acc);text-decoration:none}
.mi-pg span{color:var(--mut)}
"""


def _esc(x):
    from ui.html import esc
    return esc(str(x if x is not None else ""))


def _pct(x):
    return "–" if x is None else f"{round(x * 100)} %"


def _date(ts, fmt="%d.%m.%Y."):
    return time.strftime(fmt, time.gmtime(ts)) if ts else "–"


def _day(ts):
    return time.strftime("%Y-%m-%d", time.gmtime(ts)) if ts else ""


def _post(h, i):
    return f"https://x.com/{quote(h)}/status/{quote(str(i))}"


def subnav(cur):
    """Pregled | Biblioteka inside the Makro tab (its own class: the /kol tab script only drives .ms-seg)."""
    items = (("/kol#makro", "Pregled"), (LIB, "Biblioteka"))
    out = "".join(f'<a href="{href}"' + (' class="on" aria-current="page"' if href == cur else "") + f">{lab}</a>"
                  for href, lab in items)
    return f'<nav class="mi-seg" aria-label="Makro">{out}</nav>'


def _dir_html(d):
    sg = rules.SIGN.get(d, 0)
    cls, arrow = ("mi-up", "↑") if sg > 0 else ("mi-dn", "↓") if sg < 0 else ("mi-fl", "↔")
    return f"<span class={cls}>{arrow} {_esc(DIR_HR.get(d, d))}</span>"


def _who(rows, limit=60, per=3):
    """Account chips (to the account's page) with their posts (numbered links to the originals)."""
    out = []
    for r in rows[:limit]:
        posts = "".join(f"<a class=p href='{_post(r['h'], i)}' target=_blank rel='noopener nofollow' "
                        f"title='objava'>{k}</a>" for k, i in enumerate(r.get("ids", [])[:per], 1))
        out.append(f"<span class=mi-chip><a href='/kol-makro/{quote(r['h'])}'>@{_esc(r['h'])}</a>{posts}</span>")
    more = f" <span class=mut>i još {len(rows) - limit}</span>" if len(rows) > limit else ""
    return "".join(out) + more


def _bar(b):
    u = b.get("udio") or {}
    return ("<div class=mi-bar role=img aria-label='udjeli'>"
            + "".join(f"<span class={c} style='width:{round((u.get(k) or 0) * 100, 1)}%'></span>"
                      for k, c in (("bik", "b"), ("neutralno", "n"), ("medvjed", "m"))) + "</div>")


def _split(st):
    return f"{_pct(st.get('bik'))} bik · {_pct(st.get('medvjed'))} medvjed" if st and st.get("bik") is not None else "–"


def source_table(b, lib_q=None):
    """The "Iz čega je izvučeno" table of one statement: per side the accounts, the share, the weighted share, then
    the accounts with their posts and a link to all of them in the library."""
    trs = []
    for k in mood.SIDES:
        trs.append(f"<tr><td class='{SIDE_TONE[k]}'>{SIDE_HR[k]}</td><td class=n>{b['broj'][k]}</td>"
                   f"<td class=n>{_pct(b['udio'][k])}</td><td class=n>{_pct(b['udio_pond'][k])}</td></tr>")
    table = ("<table class='mi-t nocols'><thead><tr><th>Strana</th><th class=n>Računa</th><th class=n>Udio</th>"
             "<th class=n>Ponderirano</th></tr></thead><tbody>" + "".join(trs) + "</tbody></table>")
    who = "".join(f"<div class=mi-who><b>{SIDE_HR[k]} · {len(b['racuni'][k])}</b>{_who(b['racuni'][k])}</div>"
                  for k in mood.SIDES if b["racuni"][k])
    more = (f"<p class=mi-more><a href='{LIB}?{urlencode(lib_q)}'>Sve te objave u biblioteci →</a></p>"
            if lib_q else "")
    return table + who + more


def _mood_card(key, b, active):
    word = mood.VERDICT["hr"][b["presuda"]]
    tone = mood.TONE.get(b["presuda"], "")
    side = b["broj"]["bik"] + b["broj"]["medvjed"]
    w = mood.VERDICT["hr"][b["presuda_pond"]].lower()
    return (f"<div class=mi-mc><div class=l>{WIN_HR[key]} · {b['n']} računa sa stavom (od {active} koji su objavljivali)"
            f"</div><div class=v><i class='{tone}'></i>{_esc(word)}</div>{_bar(b)}"
            f"<div class=w><b>{_split(b['strane'])}</b> · {b['broj']['neutralno']} neutralnih · {b['objava']} izjava"
            f"</div><div class=w>Ponderirano točnošću: <b>{_esc(w)}</b> ({_split(b['strane_pond'])})</div>"
            + ("" if side else "") + "</div>")


def mood_html(m):
    """The two mood cards, the rule and the sources (24 h, 7 d)."""
    from ui import redak as R
    if not m or not m.get("okviri"):
        return str(R.hint("Raspoloženje se računa nakon prvog izračuna ocjena."))
    t = m.get("t") or time.time()
    out = [str(R.section("Raspoloženje makro influencera", sid="makro-raspolozenje"))]
    b24 = m["okviri"].get("24h")
    out.append(f"<p class=mi-rule style='font-size:15px;color:var(--fg);margin-top:6px'>{_esc(mood.line(b24))}</p>")
    out.append("<div class=mi-mood>" + "".join(_mood_card(k, m["okviri"][k], (m.get("aktivnih") or {}).get(k, 0))
                                               for k in ("24h", "7d") if k in m["okviri"]) + "</div>")
    out.append(f"<p class=mi-rule>{_esc(mood.rule_text('hr'))} Ponderirano: točniji računi (pogodak skupljen prema "
               "prosjeku) vrijede više, a skupina sličnih računa (isti tekst, citiranje, iste izjave u isto vrijeme) "
               "zajedno najviše kao jedan i pol. Uvjetne, nejasne, šaljive i promotivne izjave se ne broje.</p>")
    for k in ("24h", "7d"):
        b = m["okviri"].get(k)
        if not b or not b["n"]:
            continue
        hrs = mood.MOOD_RULES["windows_h"][k]
        q = {"od": _day(t - hrs * 3600), "do": _day(t)}
        out.append(f"<details class=mi-src><summary>Iz čega je izvučeno · {WIN_HR[k].lower()}<span>{b['n']} računa, "
                   f"{b['objava']} izjava</span></summary><div class=in>{source_table(b, q)}</div></details>")
    return "".join(out)


def topics_html(tp, public_links=False):
    from ui import redak as R
    out = [str(R.section("Teme dana", sid="makro-teme"))]
    if not tp or not tp.get("topics"):
        out.append(str(R.hint("Teme se slažu iz makro objava zadnja 24 sata, četiri puta dnevno; još ih nema.")))
        return "".join(out)
    out.append(str(R.hint(f"Iz {tp.get('n_objava', 0)} makro objava {tp.get('n_racuna', 0)} računa u 24 h do "
                          f"{_date(tp.get('do'), '%d.%m. %H:%M')} UTC. Strana teme je naše razvrstavanje njezinih objava.")))
    items = []
    for x in tp["topics"]:
        word = mood.VERDICT["hr"].get(x.get("presuda"), "")
        b = x.get("broj") or {}
        acc = {}
        for i, h in x.get("posts") or []:
            acc.setdefault(h, []).append(i)
        rows = [{"h": h, "ids": ids} for h, ids in sorted(acc.items(), key=lambda kv: -len(kv[1]))]
        src = (f"<table class='mi-t nocols'><tbody><tr><td>Objava</td><td class=n>{x['n_posts']}</td></tr><tr><td>Računa</td>"
               f"<td class=n>{x['n_accounts']}</td></tr><tr><td class=good>Bikovskih računa</td><td class=n>"
               f"{b.get('bik', 0)}</td></tr><tr><td class=bad>Medvjeđih računa</td><td class=n>{b.get('medvjed', 0)}"
               f"</td></tr><tr><td>Neutralnih</td><td class=n>{b.get('neutralno', 0)}</td></tr></tbody></table>"
               f"<div class=mi-who>{_who(rows)}</div>")
        items.append(f"<li><div class=t>{_esc(x['title_hr'])}</div><div class=s>{_esc(x['summary_hr'])}</div>"
                     f"<div class=m>{x['n_accounts']} računa · {x['n_posts']} objava"
                     + (f" · {_esc(word.lower())}" if word and x.get("presuda") != "premalo" else "") + "</div>"
                     f"<details class=mi-src><summary>Iz čega je izvučeno<span>{x['n_posts']} objava</span></summary>"
                     f"<div class=in>{src}</div></details></li>")
    out.append("<ol class=mi-top>" + "".join(items) + "</ol>")
    return "".join(out)


def flips_html(m, limit=12):
    from ui import redak as R
    fl = (m or {}).get("promjene") or []
    out = [str(R.section(f"Promjene stava · {len(fl)}", sid="makro-promjene"))]
    if not fl:
        out.append(str(R.hint("U zadnjih 7 dana nitko nije okrenuo stav (prema svojoj izjavi unutar 60 dana prije).")))
        return "".join(out)
    out.append(str(R.hint("Najnovija izjava u zadnjih 7 dana u suprotnom smjeru od prethodne o istoj imovini.")))
    def side(d, ts, i, h):
        return (f"{_dir_html(d)}<div class=sm><a href='{_post(h, i)}' target=_blank rel='noopener nofollow'>"
                f"{_date(ts, '%d.%m.')} ↗</a></div>")
    trs = "".join(f"<tr><td><a href='/kol-makro/{quote(f['h'])}'>@{_esc(f['h'])}</a><div class=sm>"
                  f"{_esc(ASSET_HR.get(f['asset'], f['asset']))}</div></td>"
                  f"<td>{side(f['prije'], f['prije_ts'], f['prije_id'], f['h'])}</td>"
                  f"<td>{side(f['sada'], f['sada_ts'], f['sada_id'], f['h'])}</td></tr>" for f in fl[:limit])
    out.append("<table class='mi-t nocols'><thead><tr><th>Račun · imovina</th><th>Prije</th><th>Sada</th></tr></thead>"
               f"<tbody>{trs}</tbody></table>")
    if len(fl) > limit:
        out.append(f"<p class=mi-more>i još {len(fl) - limit} promjena</p>")
    return "".join(out)


def assets_html(m):
    from ui import redak as R
    pa = (m or {}).get("po_imovini") or {}
    if not pa:
        return ""
    t = (m or {}).get("t") or time.time()
    trs = []
    for a in mood.ASSETS:
        b = pa.get(a)
        if not b or not b["n"]:
            continue
        q = urlencode({"imovina": a, "od": _day(t - 7 * D), "do": _day(t)})
        word = mood.VERDICT["hr"][b["presuda"]]
        tone = mood.TONE.get(b["presuda"], "")
        trs.append(f"<tr><td><a href='{LIB}?{q}'>{_esc(ASSET_HR[a])}</a></td><td class=n>{b['n']}</td>"
                   f"<td class=n>{_pct((b['strane'] or {}).get('bik'))}</td>"
                   f"<td class=n>{_pct((b['strane'] or {}).get('medvjed'))}</td><td class='{tone}'>{_esc(word)}</td></tr>")
    if not trs:
        return ""
    return (str(R.section("Po imovini · 7 dana", sid="makro-imovina"))
            + "<table class='mi-t nocols'><thead><tr><th>Imovina</th><th class=n>Računa</th><th class=n>Bik</th>"
              "<th class=n>Medvjed</th><th>Zaključak</th></tr></thead><tbody>" + "".join(trs) + "</tbody></table>"
            + str(R.hint("Bik i medvjed: udio među računima s jasnom stranom. Naziv imovine vodi na njezine izjave u "
                         "biblioteci.")))


def series_html(m, days=7):
    from ui import redak as R
    s = (m or {}).get("niz") or []
    s = [x for x in s if (x[1] or {}).get("n")][-days:]
    if not s:
        return ""
    trs = "".join(f"<tr><td>{_date(d - 1, '%d.%m.')}</td><td class=n>{b['n']}</td><td class=n>"
                  f"{_pct((b.get('strane') or {}).get('bik'))}</td><td class=n>{_pct((b.get('strane') or {}).get('medvjed'))}"
                  f"</td><td class='{mood.TONE.get(b['presuda'], '')}'>{_esc(mood.VERDICT['hr'][b['presuda']])}</td></tr>"
                  for d, b in reversed(s))
    return (str(R.section("Zadnji dani", sid="makro-dani"))
            + "<table class='mi-t nocols'><thead><tr><th>Dan (24 h)</th><th class=n>Računa</th><th class=n>Bik</th>"
              "<th class=n>Medvjed</th><th>Zaključak</th></tr></thead><tbody>" + trs + "</tbody></table>")


def overview_html():
    """The interpretation block at the top of the Makro tab (fresh)."""
    m = mood.load()
    tp = teme.load()
    return (f"<style>{CSS}</style>{subnav('/kol#makro')}{mood_html(m)}{topics_html(tp)}{flips_html(m)}"
            f"{assets_html(m)}{series_html(m)}")


# ---------- the library ------------------------------------------------------------------------------------------------

def _opts(name, pairs, cur):
    return (f"<select name={name}>" + "".join(f"<option value='{_esc(v)}'" + (" selected" if str(v) == str(cur or "")
                                                                              else "") + f">{_esc(lab)}</option>"
                                              for v, lab in pairs) + "</select>")


def _num(x):
    if x is None:
        return "–"
    x = int(x)
    if x >= 1_000_000:
        return f"{x / 1_000_000:.1f}".replace(".", ",") + " mil."
    if x >= 10_000:
        return f"{round(x / 1000)}k"
    return f"{x:,}".replace(",", ".")


def _calls_html(r):
    if not r["calls"]:
        if r.get("cls_v") in (None,):
            return "<span class='mi-cl mut'>čeka razvrstavanje</span>"
        return "<span class='mi-cl mut'>nije izjava o tržištu</span>"
    out = []
    for c in r["calls"]:
        sg = rules.SIGN.get(c["direction"], 0)
        tone = "good" if sg > 0 else "bad" if sg < 0 else ""
        hz = HZ_HR.get(rules.bucket(c.get("horizon_days")), "")
        extra = " · uvjetno" if c.get("conditional") else ""
        extra += " · šala" if c.get("confidence") == "joke" else ""
        out.append(f"<span class='mi-cl {tone}'>{_esc(ASSET_HR.get(c['asset'], c['asset']))} "
                   f"{'↑' if sg > 0 else '↓' if sg < 0 else '↔'} {_esc(DIR_HR.get(c['direction'], c['direction']))}"
                   f" · {_esc(hz)}{extra}</span>")
    return "".join(out)


def library_html(qs, now=None):
    """The library body (filters, the count, the table, the pages)."""
    from ui import redak as R
    f = library.clean(qs or {})
    con = store.ro()
    if con is None:
        return str(R.hint("Biblioteka je prazna: još nema spremljenih objava."))
    try:
        tot = library.totals(con)
        accs = library.accounts(con)
        res = library.query(con, f)
    finally:
        con.close()
    head = (f"<p class=mi-cnt>{_num(tot['posts'])} objava · {_num(tot['calls'])} izjava o tržištu · "
            f"{tot['accounts']} računa · od {_date(tot['first'])} do {_date(tot['last'])}</p>")
    form = (f"<form class=mi-f method=get action='{LIB}'>"
            f"<label>Račun{_opts('racun', [('', 'svi')] + [(h, f'@{h} · {int(n or 0)}') for h, _a, n in accs], f.get('racun'))}</label>"
            f"<label>Imovina{_opts('imovina', [('', 'sve')] + [(a, ASSET_HR[a]) for a in ASSET_HR], f.get('imovina'))}</label>"
            f"<label>Stav{_opts('stav', [('', 'svi'), ('bik', 'bikovski'), ('medvjed', 'medvjeđi'), ('neutralno', 'raspon')], f.get('stav'))}</label>"
            f"<label>Horizont{_opts('horizont', [('', 'svi'), ('7', 'do 14 dana'), ('30', '15–60 dana'), ('dugo', 'više od 60 dana'), ('bez', 'bez roka')], f.get('horizont'))}</label>"
            f"<label>Od<input type=date name=od value='{_esc(f.get('od', ''))}'></label>"
            f"<label>Do<input type=date name=do value='{_esc(f.get('do', ''))}'></label>"
            f"<label>Riječi<input type=search name=q value='{_esc(f.get('q', ''))}' placeholder='npr. etf'></label>"
            f"<label>Vrsta{_opts('vrsta', [('izjave', 'izjave o tržištu'), ('sve', 'sve objave')], f.get('vrsta', 'izjave'))}</label>"
            f"<div class=go><button type=submit>Traži</button><a href='{LIB}'>Očisti</a></div></form>")
    n0 = (res["page"] - 1) * library.PER_PAGE
    cnt = (f"<p class=mi-cnt>{n0 + 1}–{n0 + len(res['rows'])} od {_num(res['total'])} · stranica {res['page']} / "
           f"{res['pages']}</p>" if res["rows"] else "")
    trs = []
    for r in res["rows"]:
        h = r["handle"]
        qt = (f"<div class=qt>{'@' + _esc(r['quoted_handle']) + ': ' if r.get('quoted_handle') else ''}"
              f"{_esc((r['quoted_text'] or '')[:280])}</div>" if r.get("quoted_text") else "")
        url = r.get("url") or _post(h, r["id"])
        trs.append(f"<tr><td class=d>{_date(r['ts'], '%d.%m.%Y.')}<br>{_date(r['ts'], '%H:%M')}</td>"
                   f"<td class=h><a href='/kol-makro/{quote(h)}'>@{_esc(h)}</a></td>"
                   f"<td class=c>{_calls_html(r)}</td>"
                   f"<td class=x><div class=tx>{_esc(r['text'] or '')}</div>{qt}<div class=po><a href='{_esc(url)}' "
                   f"target=_blank rel='noopener nofollow'>objava ↗</a></div></td>"
                   f"<td class=e>{_num(r.get('likes'))} sviđanja<br>{_num(r.get('retweets'))} dijeljenja<br>"
                   f"{_num(r.get('views'))} pregleda</td></tr>")
    table = ("<table class='mi-lib nocols'><colgroup><col class=cd><col class=ch><col class=cc><col><col class=ce>"
             "</colgroup><thead><tr><th>Vrijeme (UTC)</th><th>Račun</th><th>Izjava</th><th>Objava</th>"
             "<th style=text-align:right>Odjek</th></tr></thead><tbody>" + "".join(trs) + "</tbody></table>"
             if trs else str(R.hint("Nijedna objava ne odgovara filtrima.")))

    def pg(p):
        q = {k: v for k, v in f.items() if k != "str"}
        q["str"] = p
        return f"{LIB}?{urlencode(q)}"
    nav = ""
    if res["pages"] > 1:
        nav = ("<div class=mi-pg>" + (f"<a href='{pg(res['page'] - 1)}'>← Novije</a>" if res["page"] > 1 else "<span></span>")
               + (f"<a href='{pg(res['page'] + 1)}'>Starije →</a>" if res["page"] < res["pages"] else "<span></span>")
               + "</div>")
    return head + form + cnt + table + nav


def library_page(qs, now=None):
    """(title, body) of /kol-makro/biblioteka."""
    from ui import kol, redak as R
    body = (f'<div class="ms-page ms-wide kl"><style>{kol.KL_CSS}{CSS}</style>{kol._back("/kol#makro", "Makro influenceri")}'
            f'{R.top("Biblioteka objava", "Sve spremljene objave makro influencera s našim razvrstavanjem")}'
            f'{subnav(LIB)}{library_html(qs, now)}</div>')
    return "Biblioteka · makro", kol._calm(body)
