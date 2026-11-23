"""Public Telegram channels (9.11.2026; 19.11.2026: informational only).

- /telegram-channels, /telegram/<channel>            English (x-default)
- /hr/telegram-kanali, /hr/telegram/<channel>        Croatian

19.11. (vlasnik: "Makni Telegram KOL-ove iz izračuna. Ali zadrži popis kanala, osvježen jednom tjedno, samo za broj
pratitelja"): the pages no longer rank channels by what their calls did. The URLs stay (search engines know them); the
hub is the channel list with followers and their change, counted once a week from each channel's public page
(tg/pratitelji.py), with one honest sentence that call performance is no longer measured since 19 Nov 2026. A channel
page is a short card (followers, its public link) and is noindex; only the hub is in the sitemap, its lastmod the day
of the last weekly count. No addresses, keys or internal service names appear here.
"""
import datetime as dt
import json
import os
import re

from ui.html import esc

CH = re.compile(r"[A-Za-z0-9_]{3,40}")
SINCE = {"en": "19 Nov 2026", "hr": "19. 11. 2026."}

T = {
    "en": dict(
        hub_title="Crypto Telegram channels: follower counts, updated weekly | MemeSonar",
        hub_desc="{n} crypto Telegram channels with their follower counts and the change over 7 and 30 days, counted "
                 "once a week. Call performance is no longer measured.",
        hub_h1="Crypto Telegram channels",
        hub_lead="A plain list of crypto Telegram channels and how many followers each has, counted once a week from "
                 "the channel's public page. Since {since} we no longer measure what the calls in these channels did, "
                 "so this page does not rank or recommend any channel.",
        cols=("#", "Channel", "Followers", "7 days", "30 days", "Counted"),
        hub_top="The {k} channels with the most followers, of {n} counted in total.",
        none="The list is empty right now.", back="← All Telegram channels",
        p_title="{c} Telegram channel: followers | MemeSonar",
        p_desc="Telegram channel {c}: {n} followers, counted once a week. Call performance is no longer measured.",
        p_lead="Followers: {n}. Counted once a week from the channel's public page. Since {since} we no longer measure "
               "the calls of Telegram channels.",
        p_date="Last count: {d}.", list_link="The full list of channels (informational)",
        open_tg="Open the channel on Telegram", x_same="The same brand on X: @{h}",
        foot="Not financial advice. A list of public channels, not an endorsement.",
        home="/", hub="/telegram-channels", prof="/telegram/"),
    "hr": dict(
        hub_title="Kripto Telegram kanali: broj pratitelja, tjedno | MemeSonar",
        hub_desc="{n} kripto Telegram kanala s brojem pratitelja i promjenom u 7 i 30 dana, brojano jednom tjedno. "
                 "Uspješnost poziva više ne mjerimo.",
        hub_h1="Kripto Telegram kanali",
        hub_lead="Običan popis kripto Telegram kanala i broja pratitelja svakog od njih, brojano jednom tjedno s javne "
                 "stranice kanala. Od {since} više ne mjerimo što su napravili pozivi iz ovih kanala, pa ova stranica "
                 "ne rangira i ne preporučuje nijedan kanal.",
        cols=("#", "Kanal", "Pratitelja", "7 dana", "30 dana", "Brojano"),
        hub_top="{k} kanala s najviše pratitelja, od ukupno {n} brojanih.",
        none="Popis je trenutno prazan.", back="← Svi Telegram kanali",
        p_title="{c} Telegram kanal: pratitelji | MemeSonar",
        p_desc="Telegram kanal {c}: {n} pratitelja, brojano jednom tjedno. Uspješnost poziva više ne mjerimo.",
        p_lead="Pratitelja: {n}. Brojano jednom tjedno s javne stranice kanala. Od {since} više ne mjerimo pozive "
               "Telegram kanala.",
        p_date="Zadnje brojanje: {d}.", list_link="Cijeli popis kanala (informativno)",
        open_tg="Otvori kanal na Telegramu", x_same="Isti brend na X-u: @{h}",
        foot="Nije financijski savjet. Popis javnih kanala, a ne preporuka.",
        home="/hr", hub="/hr/telegram-kanali", prof="/hr/telegram/"),
}


def _path():
    from ui import public
    return os.environ.get("TG_DB") or os.path.join(public.ROOT, "tg.db")


ROWS_TTL_S = 600   # 23.11.: the list changes once a week; one copy per process, read by one thread (ui/javniteret)


def _rows():
    from ui import public
    try:
        from tg import pratitelji
        rs = pratitelji.pregled(_path())
    except Exception:  # noqa: BLE001 - no tg.db: an empty list
        return []
    return [r for r in rs if CH.fullmatch(r["kanal"] or "") and not public.BAD.search(r["kanal"])]


def rows(now=None):
    """[{kanal, naslov, pratitelji, d7, d30, ts}] of the list (tg/pratitelji.pregled), safe names only.
    23.11. (hitno): a shared copy (ROWS_TTL_S, or until tg.db changes): 12 crawler requests at once each read the
    whole list before and took 15 s together on the fixture (100-330 s in production) instead of 0.01 s each.
    The rows are shared: do not change them."""
    from ui import javniteret
    p = _path()
    return javniteret.shared(("tg_rows", p), ROWS_TTL_S, _rows, version=javniteret.file_version(p))


def one(channel):
    """The list row of one channel ({kanal, naslov, pratitelji, ts}) or None, read with bounded queries (one channel
    row, its newest weekly count): what the channel page shows, without reading the whole list (23.11.)."""
    from tg import pratitelji, store
    con = store.ro(_path())
    if con is None:
        return None
    try:
        try:
            q = (f"SELECT name, title, subs, checked_ts FROM channels WHERE name = ? AND {pratitelji.LIST_SQL}")
            r = con.execute(q, (channel,)).fetchone() or con.execute(
                q.replace("name = ?", "name = ? COLLATE NOCASE") + " ORDER BY name LIMIT 1", (channel,)).fetchone()
        except Exception:  # noqa: BLE001 - an old or empty file
            return None
        if r is None:
            return None
        name, title, subs, checked = r
        try:
            last = con.execute("SELECT ts, pratitelji FROM tg_pratitelji WHERE kanal = ? ORDER BY ts DESC LIMIT 1",
                               (name,)).fetchone()
        except Exception:  # noqa: BLE001 - the table comes with the first weekly pass
            last = None
    finally:
        con.close()
    ts, n = (int(last[0]), int(last[1])) if last else (checked, subs)
    return {"kanal": name, "naslov": title, "pratitelji": n, "ts": ts}


def _day(ts):
    return dt.datetime.fromtimestamp(int(ts), dt.timezone.utc).strftime("%Y-%m-%d") if ts else None


def urls():
    """[(path_en, path_hr, priority, lastmod)] for the sitemap: the hub only (19.11.: channel pages are noindex)."""
    try:
        from tg import pratitelji
        last = (pratitelji.zadnji(_path()) or {}).get("ts")
    except Exception:  # noqa: BLE001
        last = None
    return [("/telegram-channels", "/hr/telegram-kanali", "0.6", _day(last))]


ROBOTS = ("/telegram-channels", "/telegram/", "/hr/telegram-kanali", "/hr/telegram/")


def _n(x, lang):
    if x is None:
        return "–"
    s = f"{x:,.0f}"
    return s.replace(",", ".") if lang == "hr" else s


def _d(x, lang):
    if x is None:
        return "–"
    s = f"{x:+,.0f}"
    return s.replace(",", ".") if lang == "hr" else s


HUB_MAX = int(os.environ.get("TG_HUB_MAX") or 1000)


def _top(limit):
    """([{kanal, naslov, pratitelji, d7, d30, ts}] of the `limit` channels with the most followers, the number of
    channels on the list) with the numbers and order of tg/pratitelji.pregled, read with bounded queries (23.11.,
    SEO: the hub listed all 137,809 channels, 29.8 MB of HTML, 10 s, every row a link to a noindex page)."""
    from tg import pratitelji, store
    from ui import public
    con = store.ro(_path())
    if con is None:
        return [], 0
    try:
        try:
            total = con.execute(f"SELECT COUNT(*) FROM channels WHERE {pratitelji.LIST_SQL}").fetchone()[0]
        except Exception:  # noqa: BLE001 - an old or empty file
            return [], 0
        has_rows = bool(con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='tg_pratitelji'").fetchone())
        newest = ("LEFT JOIN (SELECT kanal, pratitelji AS n, MAX(ts) AS t FROM tg_pratitelji GROUP BY kanal) p "
                  "ON p.kanal = c.name") if has_rows else "LEFT JOIN (SELECT NULL AS kanal, NULL AS n, NULL AS t) p ON 0"
        out, off = [], 0
        while len(out) < limit:
            got = con.execute(f"""SELECT c.name, c.title, CASE WHEN p.t IS NULL THEN c.subs ELSE p.n END,
                CASE WHEN p.t IS NULL THEN c.checked_ts ELSE p.t END FROM channels c {newest}
                WHERE c.{pratitelji.LIST_SQL}
                ORDER BY -COALESCE(CASE WHEN p.t IS NULL THEN c.subs ELSE p.n END, 0), c.name LIMIT ? OFFSET ?""",
                              (limit, off)).fetchall()
            if not got:
                break
            off += len(got)
            out += [{"kanal": n, "naslov": t, "pratitelji": k, "ts": ts} for n, t, k, ts in got
                    if CH.fullmatch(n or "") and not public.BAD.search(n)]
        out = out[:limit]
        series = {}
        if has_rows:
            names = [r["kanal"] for r in out]
            for i in range(0, len(names), 500):
                part = names[i:i + 500]
                for k, ts, n in con.execute(f"SELECT kanal, ts, pratitelji FROM tg_pratitelji WHERE kanal IN "
                                            f"({','.join('?' * len(part))}) ORDER BY kanal, ts", part):
                    series.setdefault(k, []).append((int(ts), int(n)))
    finally:
        con.close()
    for r in out:
        sr = series.get(r["kanal"]) or []
        if sr:
            ts, n = sr[-1]
            p7, p30 = pratitelji._at(sr, ts - 7 * 86400 + 3600), pratitelji._at(sr, ts - 30 * 86400 + 3600)
            r.update(pratitelji=n, ts=ts, d7=n - p7 if p7 is not None else None, d30=n - p30 if p30 is not None else None)
        else:
            r.update(d7=None, d30=None)
    return out, total


def top(limit=None):
    """_top(HUB_MAX) as one shared copy per process (until tg.db changes, at most ROWS_TTL_S). Shared: do not change."""
    from ui import javniteret
    p, lim = _path(), int(limit or HUB_MAX)
    return javniteret.shared(("tg_top", p, lim), ROWS_TTL_S, lambda: _top(lim), version=javniteret.file_version(p))


def hub(lang):
    from ui import public
    t = T[lang]
    rs, total = top()
    trs = []
    for i, r in enumerate(rs, 1):
        name = esc(r["kanal"]) + (f" <span class=mut>{esc(r['naslov'])}</span>"
                                  if r.get("naslov") and not public.BAD.search(r["naslov"]) else "")
        trs.append(f"<tr><td class=mut>{i}</td><td><a href=\"{t['prof']}{esc(r['kanal'])}\">{name}</a></td>"
                   f"<td class=n>{_n(r['pratitelji'], lang)}</td><td class=n>{_d(r['d7'], lang)}</td>"
                   f"<td class=n>{_d(r['d30'], lang)}</td><td class=mut>{esc(_day(r['ts']) or '–')}</td></tr>")
    head = "".join(f"<th{' class=n' if 2 <= j <= 4 else ''}>{c}</th>" for j, c in enumerate(t["cols"]))
    table = (f"<div class=tw><table><thead><tr>{head}</tr></thead><tbody>{''.join(trs)}</tbody></table></div>" if trs
             else f"<p class=mut>{t['none']}</p>")
    jsonld = ('<script type="application/ld+json">' + json.dumps({
        "@context": "https://schema.org", "@type": "ItemList", "name": t["hub_h1"],
        "itemListElement": [{"@type": "ListItem", "position": i, "name": r["kanal"],
                             "url": f"https://t.me/{r['kanal']}"} for i, r in enumerate(rs[:50], 1)]}) + "</script>")
    count = t["hub_top"].format(k=_n(len(rs), lang), n=_n(total, lang))
    body = (f"<section class=ph1><h1>{t['hub_h1']}</h1><p class=lead>{t['hub_lead'].format(since=SINCE[lang])}</p>"
            f"<p class=mut>{count}</p></section>{table}<p class=mut style='margin-top:22px;font-size:13px'>{t['foot']}</p>")
    return public._shell(lang, t["hub_title"], t["hub_desc"].format(n=_n(total, lang)),
                         "/telegram-channels", "/hr/telegram-kanali", body, jsonld=jsonld)


def profile(channel, lang):
    """One channel's card, or None (not on the list, bad name)."""
    from ui import public
    if not CH.fullmatch(channel or "") or public.BAD.search(channel):
        return None
    t = T[lang]
    r = one(channel)   # 23.11.: one channel's rows, not the whole list per request
    if r is None or not CH.fullmatch(r["kanal"] or "") or public.BAD.search(r["kanal"]):
        return None
    ch = r["kanal"]
    title_h1 = esc(ch) + ((" <span class=mut style=font-weight:500>" + esc(r["naslov"]) + "</span>")
                          if r.get("naslov") and not public.BAD.search(r["naslov"]) else "")
    n = _n(r["pratitelji"], lang)
    body = (f"<section class=ph1><div class=crumb><a href={t['hub']}>{t['back']}</a></div><h1>{title_h1}</h1>"
            f"<p class=lead>{t['p_lead'].format(n=n, since=SINCE[lang])}</p>"
            + (f"<p class=mut>{t['p_date'].format(d=esc(_day(r['ts'])))}</p>" if _day(r.get("ts")) else "")
            + f"</section><p><a href={t['hub']}>{t['list_link']}</a> · "
            f"<a href=\"https://t.me/{esc(ch)}\" target=_blank rel=\"noopener nofollow\">{t['open_tg']}</a></p>"
            f"<p class=mut style='margin-top:22px;font-size:13px'>{t['foot']}</p>")
    return public._shell(lang, t["p_title"].format(c=ch), t["p_desc"].format(c=ch, n=n), f"/telegram/{ch}",
                         f"/hr/telegram/{ch}", body, noindex=True)
