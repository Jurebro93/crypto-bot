"""Public Telegram call channels (9.11.2026, SEO plan 7.11. section 4): a hub and one page per channel.

- /telegram-channels, /telegram/<channel>            English (x-default)
- /hr/telegram-kanali, /hr/telegram/<channel>        Croatian
Same honest model as the X profiles (ui/kolstats.py): visible = history and tradable outcomes of calls older than
24 h; locked = the last 24 h and the entry rule, in the app. Channels with fewer than MIN_CLEAN clean measured calls
have a page (links keep working) but carry noindex and are not in the sitemap. The hub lists only channels with
enough data. Everything comes from kol.db (calls with handle 'tg:<channel>'), plus the channel title and member
count from tg.db when it is there. No addresses, keys or internal service names appear here.
"""
import json
import os
import re
import sqlite3
import time

from ui.html import esc

CH = re.compile(r"[A-Za-z0-9_]{3,40}")

T = {
    "en": dict(
        hub_title="Best crypto Telegram call channels, measured by what their calls did | MemeSonar",
        hub_desc="{n} crypto Telegram channels measured on every Solana token call: price higher after 1 hour, calls that "
                 "reached +15 %, median 24 h result and rugs. Updated daily.",
        hub_h1="Crypto Telegram call channels, measured",
        hub_lead="Every token call posted in these Telegram channels is measured the same way as an influencer's post on "
                 "X: what the price did 1 hour and 24 hours later and whether the token rugged. Only channels with at "
                 "least {m} clean measured calls are listed; the rest wait for data.",
        cols=("#", "Channel", "Clean calls", "Higher after 1 h", "Reached +15 %", "Median 24 h", "Rugs", "Calls / day"),
        how_h="How to read the table",
        how=("Clean calls: real call posts whose outcome was measured, excluding calls made after the price had "
             "already doubled and calls found through searches that start from winners.",
             "Higher after 1 h: share of calls where the price was above the post price one hour later, the simplest "
             "tradable outcome.",
             "Reached +15 %: share of calls whose price touched +15 % within 24 hours; median 24 h: the typical result "
             "a day later; rugs: tokens that fell 90 % or more.",
             "A channel that posts dozens of calls a day is a feed, not a signal: calls per day tells you which is "
             "which."),
        lock="Members see the calls of the last 24 hours live, which channels agree on a token right now, and our entry "
             "rule per channel.",
        cta="Request access", back="← All Telegram channels", none="No channel has enough measured calls yet.",
        p_title="{c} Telegram crypto calls: hit rate, rugs and track record | MemeSonar",
        p_desc="What did the calls in Telegram channel {c} do? {n} measured calls: higher after 1 h in {up}, {hit} "
               "reached +15 %, median 24 h result {med}, {rug} rugged. Updated daily.",
        p_desc_few="Telegram channel {c}: we measure its Solana token calls; {n} measured so far, too few for a "
                   "verdict. Updated daily.",
        calls_h="Recent calls", calls_note="Calls older than 24 hours, with their outcome. Fresh calls are for members.",
        ccols=("Date", "Token", "Market cap", "1 h", "24 h", "24h peak"),
        plock="{n} calls in the last 24 hours and our entry rule for this channel are in the app.",
        similar="Other channels", x_same="The same brand on X: @{h}",
        foot="Not financial advice. Measurements of past calls, not accusations or endorsements.",
        home="/", hub="/telegram-channels", prof="/telegram/"),
    "hr": dict(
        hub_title="Najbolji kripto Telegram call kanali, izmjereni po tome što su im pozivi napravili | MemeSonar",
        hub_desc="{n} kripto Telegram kanala izmjereno na svakom pozivu Solana tokena: cijena viša nakon sat vremena, "
                 "pozivi koji su dosegli +15 %, medijan nakon 24 h i rugovi. Osvježava se svaki dan.",
        hub_h1="Kripto Telegram call kanali, izmjereni",
        hub_lead="Svaki poziv tokena objavljen u ovim Telegram kanalima mjerimo kao i objavu influencera na X-u: što je "
                 "cijena napravila sat i 24 sata kasnije i je li token završio kao rug. Na popisu su samo kanali s "
                 "barem {m} čistih izmjerenih poziva; ostali čekaju podatke.",
        cols=("#", "Kanal", "Čistih poziva", "Viša nakon 1 h", "Doseglo +15 %", "Medijan 24 h", "Rugovi", "Poziva / dan"),
        how_h="Kako čitati tablicu",
        how=("Čisti pozivi: prave objave poziva s izmjerenim ishodom, bez poziva nakon što se cijena već udvostručila "
             "i bez poziva nađenih preko pretrage koja kreće od pobjednika.",
             "Viša nakon 1 h: udio poziva kod kojih je cijena sat kasnije bila iznad cijene u trenutku objave, "
             "najjednostavniji trgovivi ishod.",
             "Doseglo +15 %: udio poziva čija je cijena dotakla +15 % unutar 24 sata; medijan 24 h: tipičan rezultat dan "
             "kasnije; rugovi: tokeni koji su pali 90 % ili više.",
             "Kanal koji objavi desetke poziva dnevno je feed, a ne signal: broj poziva po danu kaže koji je koji."),
        lock="Članovi vide pozive iz zadnja 24 sata uživo, koji se kanali upravo slažu oko istog tokena i naše pravilo "
             "ulaza po kanalu.",
        cta="Zatraži pristup", back="← Svi Telegram kanali", none="Nijedan kanal još nema dovoljno izmjerenih poziva.",
        p_title="{c} Telegram kripto pozivi: pogodak, rugovi i rezultati | MemeSonar",
        p_desc="Što su napravili pozivi iz Telegram kanala {c}? {n} izmjerenih poziva: viša nakon 1 h u {up}, {hit} "
               "doseglo +15 %, medijan nakon 24 h {med}, {rug} rugova. Osvježava se svaki dan.",
        p_desc_few="Telegram kanal {c}: mjerimo njegove pozive Solana tokena; dosad {n} izmjerenih, premalo za presudu. "
                   "Osvježava se svaki dan.",
        calls_h="Zadnji pozivi", calls_note="Pozivi stariji od 24 sata, s ishodom. Svježi pozivi su za članove.",
        ccols=("Datum", "Token", "Tržišna vrijednost", "1 h", "24 h", "Vrh 24 h"),
        plock="{n} poziva u zadnja 24 sata i naše pravilo ulaza za ovaj kanal nalaze se u aplikaciji.",
        similar="Drugi kanali", x_same="Isti brend na X-u: @{h}",
        foot="Nije financijski savjet. Mjerenja prošlih poziva, a ne optužbe ili preporuke.",
        home="/hr", hub="/hr/telegram-kanali", prof="/hr/telegram/"),
}


def _tg_meta(channels):
    """{channel: (title, subs)} from tg.db when it exists (read-only), else {}."""
    from ui import public
    path = os.environ.get("TG_DB") or os.path.join(public.ROOT, "tg.db")
    if not channels or not os.path.exists(path):
        return {}
    try:
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5)
        try:
            q = ",".join("?" * len(channels))
            return {n: (t, s) for n, t, s in con.execute(f"SELECT name, title, subs FROM channels WHERE name IN ({q})",
                                                           list(channels))}
        finally:
            con.close()
    except sqlite3.Error:
        return {}


def rows(now=None):
    """Channels with enough clean calls, honest stats and tg.db title/members. [] without kol.db."""
    from ui import kolstats as KS, public
    con = public._con()
    if con is None:
        return []
    try:
        out = [r for r in KS.channel_rows(con, now) if CH.fullmatch(r["channel"]) and not public.BAD.search(r["channel"])]
    finally:
        con.close()
    meta = _tg_meta([r["channel"] for r in out])
    for r in out:
        t, s = meta.get(r["channel"], (None, None))
        r["title"] = r["title"] or t
        r["subs"] = r["subs"] or s
    return out


def urls():
    """[(path_en, path_hr, priority)] for the sitemap: the hub and every channel with enough data."""
    from ui import kolstats as KS
    out = [("/telegram-channels", "/hr/telegram-kanali", "0.8")]
    out += [(f"/telegram/{r['channel']}", f"/hr/telegram/{r['channel']}", "0.7") for r in rows() if r["n"] >= KS.MIN_CLEAN]
    return out


ROBOTS = ("/telegram-channels", "/telegram/", "/hr/telegram-kanali", "/hr/telegram/")


def hub(lang):
    from ui import kolstats as KS, public
    t = T[lang]
    rs = rows()
    pct = KS.pct
    trs = []
    for i, r in enumerate(rs, 1):
        name = esc(r["channel"]) + (f" <span class=mut>{esc(r['title'])}</span>" if r.get("title") and not public.BAD.search(r["title"]) else "")
        per_day = f"{r['per_day']:.1f}" if r.get("per_day") is not None else "–"
        trs.append(f"<tr><td class=mut>{i}</td><td><a href=\"{t['prof']}{r['channel']}\">{name}</a></td><td class=n>{r['n']}</td>"
                   f"<td class=n>{pct(r['up1h'])}</td><td class=n>{pct(r['hit15'])}</td>"
                   f"<td class='n {public._cls(r['med24'])}'>{pct(r['med24'], True)}</td><td class=n>{pct(r['rug'])}</td>"
                   f"<td class=n>{per_day}</td></tr>")
    head = "".join(f"<th{' class=n' if j >= 2 else ''}>{c}</th>" for j, c in enumerate(t["cols"]))
    table = (f"<div class=tw><table><thead><tr>{head}</tr></thead><tbody>{''.join(trs)}</tbody></table></div>" if trs
             else f"<p class=mut>{t['none']}</p>")
    how = "".join(f"<li>{x}</li>" for x in t["how"])
    lock = f"<div class=lock><p>{t['lock']}</p><a class='btn sm' href={t['home']}#pristup>{t['cta']}</a></div>"
    jsonld = ('<script type="application/ld+json">' + json.dumps({
        "@context": "https://schema.org", "@type": "ItemList", "name": t["hub_h1"],
        "itemListElement": [{"@type": "ListItem", "position": i, "name": r["channel"],
                             "url": f"{os.environ.get('RENDER_EXTERNAL_URL', '').rstrip('/')}{t['prof']}{r['channel']}"}
                            for i, r in enumerate(rs[:50], 1)]}) + "</script>")
    body = (f"<section class=ph1><h1>{t['hub_h1']}</h1><p class=lead>{t['hub_lead'].format(m=KS.MIN_CLEAN)}</p></section>"
            f"{table}{lock}<h2 class=s>{t['how_h']}</h2><ul class=how>{how}</ul>")
    return public._shell(lang, t["hub_title"], t["hub_desc"].format(n=len(rs)), "/telegram-channels", "/hr/telegram-kanali",
                         body, jsonld=jsonld)


def profile(channel, lang):
    """One channel page, or None (unknown channel, bad name, no kol.db)."""
    from ui import kolstats as KS, public
    if not CH.fullmatch(channel or "") or public.BAD.search(channel):
        return None
    t = T[lang]
    h = f"tg:{channel}"
    con = public._con()
    if con is None:
        return None
    cut = int(time.time()) - KS.PUBLIC_DELAY_S
    try:
        try:
            k = con.execute("SELECT name, followers, score, stats FROM kols WHERE handle = ?", (h,)).fetchone()
            n_any = con.execute("SELECT COUNT(*) FROM calls WHERE handle = ? AND kind = 'call'", (h,)).fetchone()[0]
        except sqlite3.OperationalError:
            k, n_any = None, 0
        if not k and not n_any:
            return None
        calls = KS.clean_calls(con, h)[:25]
        try:
            fresh = con.execute("SELECT COUNT(DISTINCT token) FROM calls WHERE handle=? AND kind='call' AND ts >= ?",
                                (h, cut)).fetchone()[0]
        except sqlite3.OperationalError:
            fresh = 0
        try:
            brand = con.execute("SELECT twitter FROM kol_ids WHERE LOWER(telegram) = LOWER(?) AND twitter IS NOT NULL LIMIT 1",
                                (channel,)).fetchone()
        except sqlite3.OperationalError:
            brand = None
    finally:
        con.close()
    meta = _tg_meta([channel]).get(channel, (None, None))
    me = {"name": (k[0] if k else None) or meta[0], "followers": (k[1] if k else None) or meta[1]}
    hb = public.honest_block(h, lang, me, kind="tg")
    pct = KS.pct
    crow = []
    for c in calls:
        d = time.strftime("%Y-%m-%d", time.gmtime(c["ts"]))
        crow.append(f"<tr><td class=mut>{d}</td><td><b>{esc(public._sym(c['symbol'], c['token']))}</b></td>"
                    f"<td class=n>{public._usd(c['mcap0'])}</td>"
                    + "".join(f"<td class='n {public._cls(c[key])}'>{pct(c[key], True)}</td>" for key in ("r1h", "r24h", "max24"))
                    + "</tr>")
    ch = "".join(f"<th{' class=n' if j >= 2 else ''}>{x}</th>" for j, x in enumerate(t["ccols"]))
    calls_html = (f"<div class=tw><table><thead><tr>{ch}</tr></thead><tbody>{''.join(crow)}</tbody></table></div>"
                  if crow else "")
    lock = f"<div class=lock><p>{t['plock'].format(n=fresh)}</p><a class='btn sm' href={t['home']}#pristup>{t['cta']}</a></div>"
    others = [r for r in rows() if r["channel"] != channel][:8]
    sim = "".join(f"<a href=\"{t['prof']}{r['channel']}\">{esc(r['channel'])} · {pct(r['up1h'])}</a>" for r in others)
    xs = (f"<p><a href=\"{'/influencer/' if lang == 'en' else '/hr/influencer/'}{esc(brand[0])}\">{t['x_same'].format(h=esc(brand[0]))}</a></p>"
          if brand and brand[0] and public.HANDLE.fullmatch(brand[0]) else "")
    s = hb["stats"]
    title = t["p_title"].format(c=channel)
    desc = (t["p_desc"].format(c=channel, n=s["n"], up=pct(s["up1h"]), hit=pct(s["hit15"]), med=pct(s["med24"], True),
                               rug=pct(s["rug"])) if s["enough"] else t["p_desc_few"].format(c=channel, n=s["n"]))
    base = os.environ.get("RENDER_EXTERNAL_URL", "").rstrip("/")
    jsonld = ('<script type="application/ld+json">' + json.dumps({
        "@context": "https://schema.org", "@type": "ProfilePage",
        "mainEntity": {"@type": "Organization", "name": me["name"] or channel, "alternateName": channel,
                       "sameAs": [f"https://t.me/{channel}"]},
        "url": f"{base}{t['prof']}{channel}"}) + "</script>" + hb["jsonld"])
    title_h1 = esc(channel) + ((" <span class=mut style=font-weight:500>" + esc(me["name"]) + "</span>")
                              if me["name"] and not public.BAD.search(me["name"]) else "")
    body = (f"<section class=ph1><div class=crumb><a href={t['hub']}>{t['back']}</a></div><h1>{title_h1}</h1>"
            f"<p class=mut>{hb['who']}</p><p class=lead>{hb['verdict']}</p></section>{hb['html']}{lock}{xs}"
            + (f"<h2 class=s>{t['calls_h']}</h2><p class=mut>{t['calls_note']}</p>{calls_html}" if calls_html else "")
            + (f"<h2 class=s>{t['similar']}</h2><div class=chips>{sim}</div>" if sim else ""))
    return public._shell(lang, title, desc, f"/telegram/{channel}", f"/hr/telegram/{channel}", body, jsonld=jsonld,
                         noindex=not s["enough"])
