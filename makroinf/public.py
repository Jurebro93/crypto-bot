"""Public pages of the macro influencers (EN main + HR), rendered through ui/public._shell and cached by
ui/public.route like the other public pages:

  /macro-influencers, /macro-influencer/<handle>              English (x-default)
  /hr/makro-influenceri, /hr/makro-influencer/<handle>        Croatian

Behind the OWNER SWITCH makroinf_javno (default off; publishing is "sending out"): while it is off every route answers
404 and nothing is in the sitemap or robots.txt. Rules (as ui/apjavno.py): only aggregated statistics with their
intervals and n, the methodology, "insufficient evidence" + noindex below 10 episodes, links to the original posts
(no post text is copied; a post no longer visible is "later unavailable", without a link), neutral wording (no
accusations), the stances and the index with a PUBLIC_DELAY_S delay (members see them fresh), never keys, env names,
internal services, costs or wallets.
"""
import json
import os
import re
import time

from ui.html import esc

PUBLIC_DELAY_S = 7 * 86400
MIN_EP = 10
HANDLE = re.compile(r"[A-Za-z0-9_]{1,15}")
GONE = ("confirmed_deleted", "unavailable", "account_protected", "account_suspended")
CAT = {"en": {"ta": "Trader / TA", "makro": "Macro / on-chain", "edukacija": "YouTube / education",
              "memecoin": "Memecoin KOL", "vijesti": "News / aggregator"},
       "hr": {"ta": "Trader / TA", "makro": "Makro / on-chain", "edukacija": "YouTube / edukacija",
              "memecoin": "Memecoin KOL", "vijesti": "Vijesti / agregator"}}
DIR = {"en": {"up": "up", "down": "down", "bottom_in": "bottom is in", "top_in": "top is in", "range": "range"},
       "hr": {"up": "gore", "down": "dolje", "bottom_in": "dno je tu", "top_in": "vrh je tu", "range": "raspon"}}
RES = {"en": {"hit": "hit", "miss": "miss", "flat": "no clear move", "ceka": "pending", "neaktiviran": "condition not met",
              "bez_podataka": "no price data", "dugo": "long-term (not scored)"},
       "hr": {"hit": "pogodak", "miss": "promašaj", "flat": "bez jasnog pomaka", "ceka": "čeka", "neaktiviran":
              "uvjet nije ispunjen", "bez_podataka": "nema cijene", "dugo": "dugoročno (ne mjeri se)"}}
ASSET = {"en": {"BTC": "BTC", "ETH": "ETH", "SOL": "SOL", "alts": "altcoins", "memes": "meme coins", "total": "crypto market"},
         "hr": {"BTC": "BTC", "ETH": "ETH", "SOL": "SOL", "alts": "altcoini", "memes": "meme coini",
                "total": "kripto tržište"}}

T = {
    "en": dict(
        hub="/macro-influencers", prof="/macro-influencer/", other="/hr/makro-influenceri",
        title="Crypto macro influencers: who calls BTC right? | MemeSonar",
        desc="{n} well-known crypto accounts on X, their calls on BTC, ETH, SOL, altcoins and meme coins measured "
             "against what the market did, with rules fixed in advance. Hit rate with intervals, baselines, n.",
        h1="Crypto macro influencer scorecard",
        lead="We measure the market calls of {n} well-known crypto accounts on X against what BTC, ETH, SOL, altcoins "
             "and meme coins did next. The rules were fixed before looking at any result.",
        cols=("#", "Account", "Type", "Episodes", "Hit rate (95 % interval)", "vs best baseline",
              "Follow return vs always-bull", "Later unavailable", "Stance on BTC 7 days ago"),
        few="insufficient evidence", none="No measured calls yet.",
        idx_h="Consensus of the most accurate accounts", idx="Consensus on BTC 7 days ago: {v} ({n} accounts with a "
        "view; −1 all bearish … +1 all bullish).", idx_none="Not enough history yet: the consensus is published with a "
        "7-day delay once it exists.",
        how_h="How we measure",
        how=("A call is a post stating where a market goes (up, down, the bottom or the top is in, a range), on BTC, ETH, "
             "SOL, altcoins, meme coins or the whole market. Posts are classified automatically; a stratified sample is "
             "audited.",
             "Horizons are fixed in advance: 7 and 30 days. A call that states its horizon is tested on the matching one; "
             "a call without one is tested on both, each with half weight, and both results are shown.",
             "A hit means the price moved in the called direction by more than half of its usual move over that horizon "
             "(volatility of the 30 days before the call). Conditional calls (\"if BTC loses 60k\") count only once the "
             "condition is met.",
             "Repeating the same call is one prediction (an episode), not ten.",
             "Every account is compared with simple baselines on the same dates: always bullish, a coin flip and "
             "following the last 7 days' trend. A hit rate means little unless it beats them.",
             "Three separate scores, never multiplied: predictive (hit rate with a 95 % interval), economic (the return "
             "of following the calls against always-bullish) and integrity (posts that later became unavailable, "
             "promotions).",
             "Fewer than {m} measured episodes = insufficient evidence: no rank and no verdict.",
             "\"Later unavailable\" means we can no longer see a post we stored (deleted, or the account became private "
             "or suspended). It is reported, not judged.",
             "Known limits: the accounts are the ones well known today, and history only shows posts that still existed "
             "when we first read them."),
        lock="Members see every account's current stance and the consensus live, without the 7-day delay.",
        cta="Request access", back="← All macro influencers", memecoin="Memecoin calls of @{h} →",
        p_title="@{h}: crypto market calls measured, hit rate {hit} | MemeSonar",
        p_title_few="@{h}: crypto market calls measured | MemeSonar",
        p_desc="How did @{h}'s calls on BTC and the crypto market play out? {n} measured episodes, hit rate {hit} "
               "(95 % interval {lo}–{hi}) against simple baselines on the same dates.",
        p_desc_few="We measure @{h}'s calls on BTC and the crypto market; {n} measured episodes so far, too few for a "
                   "verdict.",
        cards=("Predictive", "Economic", "Integrity"),
        pred="Hit rate {hit} ({lo}–{hi}, n {n}); best baseline {b}", econ="Follow return vs always-bull {d} per call "
        "({lo}–{hi}, n {n})", integ="Later unavailable {g} of {m} calls; promotions {p}",
        hz_h="By horizon", hz_cols=("Group", "Measured", "Hit rate", "95 % interval"),
        hz_names={"s_rokom_7d": "Stated horizon, 7 days", "s_rokom_30d": "Stated horizon, 30 days",
                  "bez_roka_7d": "No horizon, tested at 7 days", "bez_roka_30d": "No horizon, tested at 30 days"},
        ep_h="Calls (older than 7 days)", ep_cols=("Date", "Market", "Call", "Horizon", "Result", "Post"),
        post="post", gone="later unavailable", stance="Stance on BTC 7 days ago: {s}.", no_stance="no current view",
        foot_note="Not financial advice. These are measurements of past public posts, not accusations or endorsements."),
    "hr": dict(
        hub="/hr/makro-influenceri", prof="/hr/makro-influencer/", other="/macro-influencers",
        title="Kripto makro influenceri: tko pogađa BTC? | MemeSonar",
        desc="{n} poznatih kripto računa na X-u, njihove izjave o BTC-u, ETH-u, SOL-u, altcoinima i meme coinima "
             "izmjerene prema tome što je tržište napravilo, pravilima zadanima unaprijed. Pogodak s intervalima, n.",
        h1="Ocjene kripto makro influencera",
        lead="Izjave {n} poznatih kripto računa na X-u o tržištu mjerimo prema tome što su BTC, ETH, SOL, altcoini i "
             "meme coini zatim napravili. Pravila su zadana prije nego što smo vidjeli ijedan rezultat.",
        cols=("#", "Račun", "Vrsta", "Epizode", "Pogodak (95 % interval)", "prema najboljoj osnovi",
              "Povrat praćenja prema uvijek-bik", "Naknadno nedostupno", "Stav o BTC-u prije 7 dana"),
        few="nedovoljno dokaza", none="Još nema izmjerenih izjava.",
        idx_h="Konsenzus najtočnijih računa", idx="Konsenzus o BTC-u prije 7 dana: {v} ({n} računa sa stavom; −1 svi "
        "medvjeđi … +1 svi bikovski).", idx_none="Još nema dovoljno povijesti: konsenzus se objavljuje s odgodom od 7 "
        "dana kad postoji.",
        how_h="Kako mjerimo",
        how=("Izjava je objava koja kaže kamo ide tržište (gore, dolje, dno ili vrh je tu, raspon), o BTC-u, ETH-u, SOL-u, "
             "altcoinima, meme coinima ili cijelom tržištu. Objave se razvrstavaju automatski; stratificirani uzorak se "
             "provjerava.",
             "Horizonti su zadani unaprijed: 7 i 30 dana. Izjava s rokom mjeri se na odgovarajućem; izjava bez roka na "
             "oba, svaki s pola težine, i oba rezultata su prikazana.",
             "Pogodak znači da se cijena pomaknula u najavljenom smjeru više od pola svog uobičajenog pomaka u tom "
             "horizontu (volatilnost 30 dana prije izjave). Uvjetne izjave („ako BTC izgubi 60k”) broje se tek kad se "
             "uvjet ostvari.",
             "Ponavljanje iste izjave je jedno predviđanje (epizoda), ne deset.",
             "Svaki račun uspoređujemo s jednostavnim osnovama na istim datumima: uvijek bikovski, bacanje novčića i "
             "praćenje trenda zadnjih 7 dana. Pogodak malo znači ako ih ne nadmašuje.",
             "Tri odvojene ocjene, nikad pomnožene: prediktivna (pogodak s 95 % intervalom), ekonomska (povrat praćenja "
             "izjava prema uvijek-bik) i integritet (objave koje su naknadno postale nedostupne, promocije).",
             "Manje od {m} izmjerenih epizoda = nedovoljno dokaza: bez ranga i bez presude.",
             "„Naknadno nedostupno” znači da objavu koju smo spremili više ne vidimo (obrisana ili je račun postao "
             "privatan ili suspendiran). Navodimo to, ne prosuđujemo.",
             "Poznata ograničenja: računi su oni poznati danas, a povijest pokazuje samo objave koje su postojale kad smo "
             "ih prvi put pročitali."),
        lock="Članovi vide trenutni stav svakog računa i konsenzus uživo, bez odgode od 7 dana.",
        cta="Zatraži pristup", back="← Svi makro influenceri", memecoin="Memecoin pozivi od @{h} →",
        p_title="@{h}: izmjerene izjave o kripto tržištu, pogodak {hit} | MemeSonar",
        p_title_few="@{h}: izmjerene izjave o kripto tržištu | MemeSonar",
        p_desc="Kako su prošle izjave @{h} o BTC-u i kripto tržištu? {n} izmjerenih epizoda, pogodak {hit} (95 % "
               "interval {lo}–{hi}) prema jednostavnim osnovama na istim datumima.",
        p_desc_few="Mjerimo izjave @{h} o BTC-u i kripto tržištu; dosad {n} izmjerenih epizoda, premalo za presudu.",
        cards=("Prediktivno", "Ekonomski", "Integritet"),
        pred="Pogodak {hit} ({lo}–{hi}, n {n}); najbolja osnova {b}", econ="Povrat praćenja prema uvijek-bik {d} po "
        "izjavi ({lo}–{hi}, n {n})", integ="Naknadno nedostupno {g} od {m} izjava; promocija {p}",
        hz_h="Po horizontu", hz_cols=("Skupina", "Izmjereno", "Pogodak", "95 % interval"),
        hz_names={"s_rokom_7d": "S rokom, 7 dana", "s_rokom_30d": "S rokom, 30 dana",
                  "bez_roka_7d": "Bez roka, mjereno na 7 dana", "bez_roka_30d": "Bez roka, mjereno na 30 dana"},
        ep_h="Izjave (starije od 7 dana)", ep_cols=("Datum", "Tržište", "Izjava", "Horizont", "Ishod", "Objava"),
        post="objava", gone="naknadno nedostupno", stance="Stav o BTC-u prije 7 dana: {s}.", no_stance="bez stava",
        foot_note="Nije financijski savjet. Ovo su mjerenja prošlih javnih objava, a ne optužbe ili preporuke."),
}


def on():
    """True while the owner switch makroinf_javno is on ("live"). Never raises: unreadable = off."""
    try:
        from trade import settings
        return settings.flag(settings.MAKROINF_JAVNO) == "live"
    except Exception:  # noqa: BLE001
        return False


def _pct(x, lang):
    if x is None:
        return "–"
    s = f"{x * 100:.0f} %"
    return s


def _pp(x, lang):
    if x is None:
        return "–"
    s = f"{x * 100:+.1f} pp"
    return s.replace(".", ",") if lang == "hr" else s


def _data():
    from makroinf import report
    return report.data()


def _rows(d):
    from makroinf import report
    return [r for r in report.rank_rows(d) if HANDLE.fullmatch(r["handle"] or "")]


def _stance_7d(d, h, lang):
    st = (((d.get("stavovi") or {}).get("prije_7d") or {}).get("BTC") or {}).get(h)
    return DIR[lang].get(st["dir"]) if st else T[lang]["no_stance"]


def _index_7d(lang):
    from makroinf import store
    con = store.ro()
    if con is None:
        return None
    try:
        day = (int(time.time()) - PUBLIC_DELAY_S) // 86400 * 86400
        r = store.q(con, "SELECT value, coverage FROM index_d WHERE asset = 'BTC' AND mode = 'prospektivno' AND "
                         "kind = 'top' AND day <= ? ORDER BY day DESC LIMIT 1", (day,))
    finally:
        con.close()
    if not r or r[0][0] is None:
        return None
    v = f"{r[0][0]:+.2f}"
    return (v.replace(".", ",") if lang == "hr" else v), r[0][1]


def hub(lang):
    """HTML of the hub, or None while the switch is off / before any data."""
    if not on():
        return None
    d = _data()
    if not d or not d.get("scores"):
        return None
    from ui import public as P
    t = T[lang]
    rows = _rows(d)
    trs = []
    k = 0
    for r in rows:
        few = r["presuda"] == "nedovoljno dokaza"
        if not few:
            k += 1
        g = r["integritet"]
        e = r["ekonomski"]
        trs.append(f"<tr><td class=mut>{'–' if few else k}</td><td><a href=\"{t['prof']}{r['handle']}\">"
                   f"@{esc(r['handle'])}</a></td><td>{esc(CAT[lang].get(r['category'], ''))}</td>"
                   f"<td class=n>{r['n_epizoda']}</td>"
                   + (f"<td colspan=3 class=mut>{t['few']}</td>" if few else
                      f"<td class=n><b>{_pct(r['pogodak'], lang)}</b> <span class=mut>({_pct(r['wilson95'][0], lang)}–"
                      f"{_pct(r['wilson95'][1], lang)})</span></td><td class=n>{_pp(r['razlika'], lang)}</td>"
                      f"<td class=n>{_pp(e.get('razlika'), lang)}</td>")
                   + f"<td class=n>{g.get('naknadno_nedostupno', 0)} / {g.get('makro_izjava', 0)}</td>"
                   f"<td>{esc(_stance_7d(d, r['handle'], lang))}</td></tr>")
    head = "".join(f"<th{' class=n' if 2 < j < 8 else ''}>{h}</th>" for j, h in enumerate(t["cols"]))
    table = (f"<div class=tw><table class=coins><thead><tr>{head}</tr></thead><tbody>{''.join(trs)}</tbody></table>"
             f"</div>") if trs else f"<p class=mut>{t['none']}</p>"
    ix = _index_7d(lang)
    idx = (t["idx"].format(v=ix[0], n=ix[1]) if ix else t["idx_none"])
    how = "".join(f"<li>{esc(x.format(m=MIN_EP))}</li>" for x in t["how"])
    n = len(rows)
    body = (f"<section class=ph1><div class=eyebrow>MemeSonar</div><h1>{t['h1']}</h1><p class=lead>"
            f"{esc(t['lead'].format(n=n))}</p></section>{table}<h2 class=s>{t['idx_h']}</h2><p>{esc(idx)}</p>"
            f"<h2 class=s>{t['how_h']}</h2><ul class=how>{how}</ul>"
            f"<div class=lock><p>{t['lock']}</p><a class='btn sm' href={P.L[lang]['home']}#pristup>{t['cta']}</a></div>"
            f"<p class=mut style='font-size:13px'>{t['foot_note']}</p>")
    return P._shell(lang, t["title"], t["desc"].format(n=n), "/macro-influencers", "/hr/makro-influenceri", body)


def _episodes(h):
    from makroinf import rules, store
    con = store.ro()
    if con is None:
        return [], {}
    cut = int(time.time()) - PUBLIC_DELAY_S
    try:
        rows = store.q(con, """SELECT eid, asset, direction, hz, MAX(t_call), GROUP_CONCAT(horizon || ':' || res),
            first_id FROM outcomes WHERE lower(handle) = lower(?) AND rules_v = ? AND t_call < ? GROUP BY eid
            ORDER BY MAX(t_call) DESC LIMIT 40""", (h, rules.RULES_VERSION, cut))
        gone = {i: s for i, s in store.q(con, "SELECT id, state FROM deletions WHERE lower(handle) = lower(?) AND state "
                                              "IS NOT NULL", (h,))}
    finally:
        con.close()
    return rows, gone


def _memecoin_page(h):
    try:
        from ui import public as P
        return any(r["handle"].lower() == h.lower() for r in P.influencers())
    except Exception:  # noqa: BLE001
        return False


def profile(handle, lang):
    """HTML of one account page, or None (switch off, unknown handle)."""
    if not on() or not HANDLE.fullmatch(handle or ""):
        return None
    d = _data()
    if not d:
        return None
    me = next((r for r in _rows(d) if r["handle"].lower() == handle.lower()), None)
    if not me:
        return None
    from ui import public as P
    t = T[lang]
    h = me["handle"]
    few = me["presuda"] == "nedovoljno dokaza"
    lo, hi = me["wilson95"]
    e, g = me["ekonomski"], me["integritet"]
    cards = (f"<div class=card><span>{t['cards'][0]}</span><p>{esc(t['pred'].format(hit=_pct(me['pogodak'], lang), lo=_pct(lo, lang), hi=_pct(hi, lang), n=me['n_epizoda'], b=_pct(me['najbolja_bazna'], lang)))}</p></div>"
             f"<div class=card><span>{t['cards'][1]}</span><p>{esc(t['econ'].format(d=_pp(e.get('razlika'), lang), lo=_pp((e.get('razlika95') or [None, None])[0], lang), hi=_pp((e.get('razlika95') or [None, None])[1], lang), n=e.get('n', 0)))}</p></div>"
             f"<div class=card><span>{t['cards'][2]}</span><p>{esc(t['integ'].format(g=g.get('naknadno_nedostupno', 0), m=g.get('makro_izjava', 0), p=g.get('promocije', 0)))}</p></div>")
    hz = me.get("po_horizontu") or {}
    def ci(k):
        lo_, hi_ = ((hz.get(k) or {}).get("wilson95") or [None, None])[:2]
        return "–" if lo_ is None else f"{_pct(lo_, lang)}–{_pct(hi_, lang)}"
    hz_rows = "".join(f"<tr><td>{esc(t['hz_names'][k])}</td><td class=n>{(hz.get(k) or {}).get('n', 0)}</td>"
                      f"<td class=n>{_pct((hz.get(k) or {}).get('pogodak'), lang)}</td><td class=n>{ci(k)}</td></tr>"
                      for k in t["hz_names"])
    hz_head = "".join(f"<th{' class=n' if j else ''}>{x}</th>" for j, x in enumerate(t["hz_cols"]))
    eps, gone = _episodes(h)
    ep_rows = []
    for _eid, asset, dr, hzb, ts, res, fid in eps:
        parts = []
        for x in (res or "").split(","):
            if ":" in x:
                hh, rr = x.split(":", 1)
                parts.append(f"{hh} d: {RES[lang].get(rr, rr)}" if hh.isdigit() else RES[lang].get(rr, rr))
        hz_txt = {"7": "7 d", "30": "30 d", "oba": "7 + 30 d", "dugo": "> 60 d"}.get(hzb, hzb)
        post = (f"<span class=mut>{t['gone']}</span>" if gone.get(str(fid)) in GONE else
                f"<a href=\"https://x.com/{h}/status/{esc(str(fid))}\" target=_blank rel=\"nofollow noopener\">"
                f"{t['post']} ↗</a>")
        ep_rows.append(f"<tr><td class=mut>{time.strftime('%Y-%m-%d', time.gmtime(ts))}</td>"
                       f"<td>{esc(ASSET[lang].get(asset, asset))}</td><td>{esc(DIR[lang].get(dr, dr))}</td>"
                       f"<td>{esc(hz_txt)}</td><td>{esc('; '.join(parts))}</td><td>{post}</td></tr>")
    ep_head = "".join(f"<th>{x}</th>" for x in t["ep_cols"])
    ep_html = (f"<div class=tw><table><thead><tr>{ep_head}</tr></thead><tbody>{''.join(ep_rows)}</tbody></table></div>"
               if ep_rows else f"<p class=mut>{t['none']}</p>")
    a = (d.get("accounts") or {}).get(h) or {}
    name = a.get("name") if a.get("name") and a.get("name") != h else ""
    mc = (f"<p><a href=\"{P.L[lang]['prof']}{h}\">{esc(t['memecoin'].format(h=h))}</a></p>" if _memecoin_page(h) else "")
    stance = t["stance"].format(s=_stance_7d(d, h, lang))
    body = (f"<section class=ph1><div class=crumb><a href={t['hub']}>{t['back']}</a></div><h1>@{esc(h)}"
            + (f" <span class=mut style=font-weight:500>{esc(name)}</span>" if name else "") + "</h1>"
            f"<p class=mut>{esc(CAT[lang].get(me['category'], ''))} · x.com/{esc(h)}</p>"
            + (f"<p class=lead>{t['few']}</p>" if few else "") + f"<p>{esc(stance)}</p></section>"
            f"<div class=charts>{cards}</div><h2 class=s>{t['hz_h']}</h2><div class=tw><table><thead><tr>{hz_head}"
            f"</tr></thead><tbody>{hz_rows}</tbody></table></div><h2 class=s>{t['ep_h']}</h2>{ep_html}{mc}"
            f"<div class=lock><p>{t['lock']}</p><a class='btn sm' href={P.L[lang]['home']}#pristup>{t['cta']}</a></div>"
            f"<p class=mut style='font-size:13px'>{t['foot_note']}</p>")
    if few:
        title, desc = t["p_title_few"].format(h=h), t["p_desc_few"].format(h=h, n=me["n_epizoda"])
    else:
        title = t["p_title"].format(h=h, hit=_pct(me["pogodak"], lang))
        desc = t["p_desc"].format(h=h, n=me["n_epizoda"], hit=_pct(me["pogodak"], lang), lo=_pct(lo, lang),
                                  hi=_pct(hi, lang))
    return P._shell(lang, title, desc, f"/macro-influencer/{h}", f"/hr/makro-influencer/{h}", body, noindex=few)


def match(path):
    """fn() -> HTML or None for a macro-influencer path, else None (not ours)."""
    if path in ("/macro-influencers", "/hr/makro-influenceri"):
        lang = "en" if path == "/macro-influencers" else "hr"
        return lambda: hub(lang)
    m = re.fullmatch(r"(/hr)?/(macro|makro)-influencer/([^/]+)", path)
    if m and ((m.group(1) is None) == (m.group(2) == "macro")):
        lang, h = ("hr" if m.group(1) else "en"), m.group(3)
        return lambda: profile(h, lang)
    return None


def urls():
    """Sitemap entries (en, hr, priority): only while the switch is on; profiles only with >= MIN_EP episodes."""
    if not on():
        return []
    d = _data()
    if not d or not d.get("scores"):
        return []
    out = [("/macro-influencers", "/hr/makro-influenceri", "0.7")]
    out += [(f"/macro-influencer/{r['handle']}", f"/hr/makro-influencer/{r['handle']}", "0.5") for r in _rows(d)
            if r["presuda"] != "nedovoljno dokaza"]
    return out


def robots_lines():
    if not on():
        return ""
    return "Allow: /macro-influencer\nAllow: /hr/makro-influenc\n"
