"""The "KOL-ovi" page: influencers on X, their calls with links, what the price and volume did after each call,
group calls, KOL pairs that call together, wallets that sell into calls, and which call features correlate
with a pump. /kol/<handle> lists one KOL's calls. All read-only from kol.db (written by run_kol.py)."""
import json
import re
import sqlite3
import time
import os
from urllib.parse import quote

from kol import score as kscore, store
from ui import kolchart
from ui.html import ago, badge, breakdown, esc, filt, lead, num, signed, table, tdesc, tip, tlink, ts, usd, wlink

CONFIG = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "kol", "config.json")


def _cfg():
    with open(CONFIG) as f:
        return json.load(f)


def _rows(con, sql, args=()):
    cur = con.execute(sql, args)
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in cur]


def pct(x):
    return signed(None if x is None else x * 100, "{:+.0f}%")


def lift(x):
    if x is None:
        return ("–", -1, "n")
    c = "pos" if x >= 2 else "neg" if x < 1 else ""
    if x >= 50:  # measure.py caps at 50×: almost no volume in the hour before, so the ratio has no real ceiling
        return (f'<span class="{c}" title="Sat prije gotovo nije bilo trgovanja, pa omjer nema smisla računati točno">'
                f'50×+</span>', x, "n")
    return (f'<span class="{c}">{x:.1f}×</span>', x, "n")


def share(x):
    return ("–", -1, "n") if x is None else (f"{x * 100:.0f}%", x, "n")


def hook_handles(con):
    """9.11. (audit P42): the X accounts the twitterapi.io webhook delivers within seconds, lower-cased. kol/xhook.sync
    saves its rule values ("from:a OR from:b") in kv 'xhook'; that set (followed + hot list + watch + big accounts) is
    wider than the xquik monitor table the pages called "uživo". Empty before the first sync (no key / no public URL)."""
    try:
        r = con.execute("SELECT value FROM kv WHERE key = 'xhook'").fetchone()
        vals = (json.loads(r[0]) if r else {}).get("values") or []
    except (sqlite3.Error, ValueError, TypeError, AttributeError):
        return set()
    out = set()
    for v in vals:
        out.update(h.lower() for h in re.findall(r"from:(\S+)", v or ""))
    return out


def speed_badge(hook, monitor):
    """'⚡ uživo' with the channel in the tooltip (X webhook: seconds; xquik monitor: the old Apify channel), or
    'sporije' for an account we only see at scan time."""
    if hook and monitor:
        title = "X webhook (twitterapi.io) i xquik monitor: objave stižu u sekundama"
    elif hook:
        title = "X webhook (twitterapi.io): objave stižu u sekundama"
    elif monitor:
        title = "xquik monitor (Apify): stari kanal, pravila se osvježavaju svakih ~15 min"
    else:
        return badge("sporije", "warn")
    return f'<span class="b good" title="{esc(title)}">⚡ uživo</span>'


MINUTE_DAYS, MINUTE_MIN_N = 14, 3


def minute_stats(now=None, days=MINUTE_DAYS, min_n=MINUTE_MIN_N, path=None):
    """9.11. (audit P43): (handle -> kol/minute.handle_stats row, hot-list handles) for the influencer tables: hits
    before the −20 % stop measured from the minute of the call (distinct tokens), the measure the real-money follows
    should be chosen by; the hot list (kv hot_list) is what the X webhook and the 2-s Telegram reader actually follow.
    ({}, set()) until minute.db has rows (it fills for a day or two after a deploy). Pure: no state kept."""
    try:
        from kol import minute
        mcon = minute.ro(path)
        stats = {}
        if mcon is not None:
            try:
                stats = dict(minute.handle_stats(mcon, days, now or int(time.time()), min_n=min_n))
            finally:
                mcon.close()
        hot = minute.hot_list(path)
        hs = set(hot.get("x") or []) | {"tg:" + h for h in (hot.get("tg") or [])}
    except Exception:  # noqa: BLE001 - the tables work without the minute layer
        return {}, set()
    return stats, hs


MINUTE_HEAD = [("+10 % prije stopa", "n"), ("+15 % prije stopa", "n"), ("Stop prvi", "n"), ("Minutnih poziva", "n")]


def minute_cells(s):
    """Cells for MINUTE_HEAD from one handle_stats row; dashes when the account has no minute check yet."""
    if not s:
        return [("–", -1, "n mut")] * 4
    return [share(s["hit10"]), share(s["hit15"]),
            (f"{s['sl']:.0%}", round(s["sl"], 3), "n " + ("bad" if s["sl"] >= 0.3 else "")), num(s["n"])]


def hot_badge(h, hot):
    return (" " + badge("🔥 vruća lista", "good")) if h in hot else ""


def profile_url(h):
    """X profile, Telegram channel ('tg:<name>') or the wallet on Solscan ('w:<name>' has no page)."""
    if h.startswith("tg:"):
        return f"https://t.me/{quote(h[3:])}"
    if h.startswith("w:"):
        return None
    return f"https://x.com/{quote(h)}"


TRIAL_TIP = tip("", "na-probi")
RUG_TIP = tip("", "puno-rugova")


def klink(h):
    u = profile_url(h)
    name = f"✈ {h[3:]}" if h.startswith("tg:") else f"👛 {h[2:]}" if h.startswith("w:") else f"@{h}"
    return (f'<a href="/kol/{quote(h)}">{esc(name)}</a> ' + (
        f'<a href="{u}" target=_blank rel=noopener class=mut style="text-decoration:none">↗</a>' if u else ""))


def post(url):
    """Link to the original post on X or Telegram; anything else (e.g. a Solscan transaction) is not a post."""
    ok = url and ("/status/" in url or "t.me/" in url)
    return f'<a href="{esc(url)}" target=_blank rel=noopener>post ↗</a>' if ok else "–"


def txlink(url):
    ok = url and "solscan.io/tx/" in url
    return f'<a href="{esc(url)}" target=_blank rel=noopener>transakcija ↗</a>' if ok else "–"


# Wallet trades (Helius -> kol.db calls with kind buy/sell) are not posts: they get their own table.
TRADES = "kind IN ('buy', 'sell')"
POSTS = "kind NOT IN ('buy', 'sell')"


def _wallet_of(con):
    """handle in calls ('w:<name>' or the KOL's X handle) -> wallet address, from kol_ids."""
    out = {}
    try:
        from kol.collect import wallet_handles
        out = {h: w for w, h in wallet_handles(con).items()}
    except Exception:
        pass
    try:  # tracked wallets that are not in kol_ids are stored as 'w:<first 6 chars>': find them in the swap feed
        import sqlite3
        from kol.collect import HYPE_DB
        src = sqlite3.connect(f"file:{HYPE_DB}?mode=ro", uri=True, timeout=5)
        try:
            for w, in src.execute("SELECT DISTINCT wallet FROM chain_trades"):
                out.setdefault("w:" + w[:6], w)
        finally:
            src.close()
    except Exception:
        pass
    return out


def wallet_cell(h, wmap):
    """Who traded: wallet name (opens its page with all trades) + Solscan account; for a known KOL his X handle too."""
    w = wmap.get(h)
    sol = (f' <a href="https://solscan.io/account/{quote(w)}" target=_blank rel=noopener class=mut '
           f'title="Novčanik na Solscanu" style="text-decoration:none">↗</a>') if w else ""
    if h.startswith("w:"):
        return f'<a href="/kol/{quote(h)}">👛 {esc(h[2:])}</a>{sol}'
    return klink(h) + (f' <span class=mut>novčanik</span>{sol}' if w else "")


def _sol(text):
    try:
        return float((text or "").split()[1])
    except (IndexError, ValueError):
        return None


def kindb(kind, match):
    b = {"call": badge("poziv", "good"), "repost": badge("proslijeđeno"), "buy": badge("kupio", "good"),
         "sell": badge("prodao", "bad"), "brag": badge("hvalisanje", "warn"),
         "bot": badge("automatska objava", "warn"), "warn": badge("upozorenje", "bad")}.get(kind) or badge(kind or "?")
    return b + (" " + badge("ticker") if match == "ticker" else " " + badge("nejasan token") if match == "ambiguous" else "")


def _syms(con):
    return dict(con.execute("SELECT token, symbol FROM tokens"))


def _flows(con):
    return {(r[0], r[1]): r[2:] for r in con.execute(
        "SELECT tweet_id, token, insiders, insider_sol, post_sell_sol, post_buy_sol, rotation_selling FROM flows")}


def _flowcell(f):
    if not f:
        return ("–", -1, "n")
    ins, ins_sol, sell, buy, rot = f
    kind = "neg" if ins or rot else ""
    txt = f"{ins} ins. · {sell:.1f}/{buy:.1f} SOL" + (f" · {rot} rot.dev" if rot else "")
    return (f'<span class="{kind}">{esc(txt)}</span>', ins, "n")


def _groupsize(con):
    out = {}
    for token, start, end, n in con.execute("SELECT token, start_ts, end_ts, n_authors FROM groups"):
        out.setdefault(token, []).append((start, end, n))
    return out


def _gcell(gs, token, t):
    for start, end, n in gs.get(token, ()):
        if start <= t <= end:
            return (badge(f"{n} autora", "good" if n >= 3 else ""), n, "n")
    return ("–", 0, "n")


def _ticker(text):
    """$TICKER of a post that names exactly one, as the token's name until DexScreener gives us the symbol."""
    from hype.telegram import _TICKER
    found = _TICKER.findall(text or "")
    return "$" + found[0] if len({x.upper() for x in found}) == 1 else None


def calls_table(con, where="1=1", args=(), limit=300, tid="calls", show_kol=True):
    syms, fl, gs = _syms(con), _flows(con), _groupsize(con)
    rows = _rows(con, f"SELECT * FROM calls WHERE ({where}) AND {POSTS} ORDER BY ts DESC LIMIT ?", (*args, limit))
    head = ["Vrijeme"] + (["Račun", ("Pratitelji", "n")] if show_kol else []) + [
        "Token", "Vrsta poziva", "Post", ("Mcap u pozivu", "n"), ("2 h prije", "n"), ("1 h", "n"), ("6 h", "n"),
        ("24 h", "n"), ("Max 24 h", "n"), ("Volumen ×", "n"), ("Grupa", "n"), ("Prodaja u poziv", "n"), ("Tekst", "wrap")]
    out = []
    for c in rows:
        r = [ts(c["ts"])] + ([klink(c["handle"]), num(c["followers"])] if show_kol else []) + [
            tlink(c["token"], syms.get(c["token"]) or c["symbol"] or _ticker(c["text"])), kindb(c["kind"], c["match"]),
            post(c["url"]),
            usd(c["mcap0"]), pct(c["pre2h"]), pct(c["r1h"]), pct(c["r6h"]), pct(c["r24h"]), pct(c["max24"]),
            lift(c["vol_lift"]), _gcell(gs, c["token"], c["ts"]), _flowcell(fl.get((c["tweet_id"], c["token"]))),
            (f'<span class=mut>{esc((c["text"] or "")[:160])}</span>', "", "wrap")]
        out.append(r)
    return table(head, out, tid=tid, empty="Još nema poziva. Bot ih skuplja sam iz X pretraga koje ionako plaća.")


def trades_table(con, where="1=1", args=(), limit=200, tid="trades", show_who=True):
    """Buys and sells of tracked KOL wallets (Helius); the link opens the transaction on Solscan."""
    syms, wmap = _syms(con), _wallet_of(con)
    rows = _rows(con, f"SELECT * FROM calls WHERE ({where}) AND {TRADES} ORDER BY ts DESC LIMIT ?", (*args, limit))
    head = ["Vrijeme"] + (["Novčanik"] if show_who else []) + [
        "Token", "Kupio/prodao", ("Iznos SOL", "n"), ("Mcap u trenutku", "n"), ("2 h prije", "n"), ("1 h", "n"),
        ("6 h", "n"), ("24 h", "n"), ("Max 24 h", "n"), "Transakcija"]
    out = []
    for c in rows:
        sol = _sol(c["text"])
        out.append([ts(c["ts"])] + ([wallet_cell(c["handle"], wmap)] if show_who else []) + [
            tlink(c["token"], syms.get(c["token"]) or c["symbol"]), kindb(c["kind"], None),
            num(sol, "{:.2f}"), usd(c["mcap0"]), pct(c["pre2h"]), pct(c["r1h"]), pct(c["r6h"]), pct(c["r24h"]),
            pct(c["max24"]), txlink(c["url"])])
    return table(head, out, tid=tid, empty="Još nema kupnji ni prodaja praćenih novčanika.")


FEW = 5  # fewer measured calls than this: medians are shown faded


def _leaderboard(con, minf, minc, star=None, tid="kols", count=False):
    """star None: everyone; True: only stars (100k+ followers or on the followed-stars list); False: rising stars."""
    from ui.public import is_star, star_handles
    stars = star_handles()
    rows = _rows(con, "SELECT * FROM kols WHERE score IS NOT NULL AND COALESCE(followers, 0) >= ? ORDER BY score DESC",
                 (minf,))
    if star is not None:
        rows = [k for k in rows if is_star(k, stars) == star]
    last = dict(con.execute("SELECT handle, MAX(ts) FROM calls WHERE kind = 'call' GROUP BY handle"))
    out = []
    from kol.discover import excluded
    rows.sort(key=lambda k: excluded(k["stats"]))  # proven KOLs first, "na probi" after them (stable: by score)
    ms, hot = minute_stats()   # 9.11. (audit P43): the minute measure and the hot list next to the 24-h fuse
    for k in rows:
        s = json.loads(k["stats"] or "{}")
        if s.get("measured", 0) < minc:
            continue
        few = s.get("measured", 0) < FEW

        def m(cell):  # stats from 1-4 calls are anecdotes, not medians: shown faded
            if not few:
                return cell
            return (f'<span class=mut title="Samo {s.get("measured", 0)} izmjerenih poziva: premalo za pouzdan '
                    f'medijan">{cell[0]}</span>', cell[1], cell[2])
        eng = s.get("eng_rate")
        rng = (f' <span class=mut title="80% raspon: s ovoliko poziva prava ocjena je vjerojatno između '
               f'{s["score_lo"]:.0f} i {s["score_hi"]:.0f}">({s["score_lo"]:.0f}-{s["score_hi"]:.0f})</span>'
               if s.get("score_lo") is not None else "")
        name = klink(k["handle"]) + hot_badge(k["handle"], hot) + (
            f' <span class="b warn" title="{esc(s.get("trial_why", ""))}">na probi</span>{TRIAL_TIP}'
            if s.get("trial") else "") + (
            f' <span class="b bad" title="{esc(s.get("rug_why", ""))}">puno rugova</span>{RUG_TIP}'
            if s.get("rugger") else "") + (' <span class="b good" title="Njegov novčanik je kupio tokene koje je zvao">'
                                           'kupio</span>' if s.get("bought") else "")
        out.append([name, num(k["followers"]), (f"<b>{k['score']:.0f}</b>{rng}", k["score"], "n"),
                    m(lift(k["power_rel"])), num(s.get("measured")), *minute_cells(ms.get(k["handle"])),
                    m(share(s.get("hit_rate"))),
                    m(pct(s.get("med_max24"))), m(pct(s.get("med_r1h"))), m(lift(s.get("med_lift"))),
                    m(share(s.get("rug_rate"))), m(share(s.get("prepump_rate"))), m(share(s.get("first_rate"))),
                    num(s.get("brags")), num(s.get("med_views")),
                    ("–", -1, "n") if eng is None else (f"{eng * 100:.2g}%" if eng < 0.1 else f"{eng * 100:.0f}%", eng, "n"),
                    _zone(s), ago(last.get(k["handle"]))])
    html = table(["X račun", ("Pratitelji", "n"), ("Moć poziva", "n"), ("Moć/pratitelj", "n"), ("Poziva", "n"),
                  *MINUTE_HEAD,
                  ("Pogodak 24 h (stara mjera)", "n"), ("Medijan max 24 h", "n"), ("Medijan 1 h", "n"), ("Medijan volumen ×", "n"),
                  ("Rugovi", "n"), ("Kasni pozivi", "n"), ("Prvi", "n"), ("Hvalisanja", "n"), ("Medijan pregleda", "n"), ("Engagement", "n"),
                  "Zona", "Zadnji poziv"],
                 out, tid=tid, empty="Još nema KOL-ova s izmjerenim pozivom u ovoj skupini (mjerenje kreće 1 h nakon "
                                     "poziva).", limit=100)
    return (html, len(out)) if count else html


def _star_tabs(con, minf, minc):
    """Leaderboard in two tabs: rising stars (lesser-known accounts, the ones worth finding; default) and stars."""
    from ui.public import STAR_FOLLOWERS
    from ui.html import info
    rising, n_r = _leaderboard(con, minf, minc, star=False, tid="kols", count=True)
    stars, n_s = _leaderboard(con, minf, minc, star=True, tid="kolstars", count=True)
    btn = ("padding:7px 14px;border:1px solid var(--line,#ddd);border-radius:8px;cursor:pointer;font-weight:600;"
           "margin:0 6px 10px 0;background:var(--card,#fff)")
    return (
        f'<div class=kst><button type=button data-t=rising class=on style="{btn}">⭐ Rastuće zvijezde ({n_r})'
        f'</button><button type=button data-t=stars style="{btn}">🌟 Zvijezde ({n_s})</button> '
        f'{info("Zvijezde i rastuće zvijezde", "zvijezde-i-rastuce-zvijezde")}</div>'
        '<div class=ksp data-p=rising>' + tdesc(
            "Manje poznati računi (ispod " + f"{STAR_FOLLOWERS:,}".replace(",", ".") + " pratitelja) koji rano zovu "
            "tokene koji kasnije porastu. Njih tražimo: malo ih ljudi prati, pa nakon njihovog poziva još ima mjesta "
            "za ulaz.") + rising + "</div>"
        '<div class=ksp data-p=stars hidden>' + tdesc(
            "Najpoznatiji influenceri (" + f"{STAR_FOLLOWERS:,}".replace(",", ".") + "+ pratitelja ili s naše liste: "
            "Murad, Ansem i ekipa). Njihov poziv vidi masa ljudi u istoj sekundi, a snajper botovi čekaju baš njihove "
            "objave. Na Solani, kad puno kupnji stigne odjednom, mreža prvo obradi one s većom prioritetnom naknadom "
            f"{info('prioritetna naknada', 'prioritetna-naknada')}: bot plati više i kupi prije svih, a ljudi kupe "
            f"njemu po višoj cijeni (front-running {info('front-running', 'front-running')}). Zato su pozivi zvijezda "
            "lošiji za trgovanje nego što izgleda, iako najviše pomaknu cijenu.") + stars + "</div>"
        "<script>document.querySelectorAll('.kst button').forEach(t=>t.onclick=()=>{"
        "document.querySelectorAll('.kst button').forEach(b=>{b.classList.toggle('on',b===t);"
        "b.style.background=b===t?'var(--accent,#4f46e5)':'';b.style.color=b===t?'#fff':''});"
        "document.querySelectorAll('.ksp').forEach(p=>p.hidden=p.dataset.p!==t.dataset.t)});"
        "document.querySelector('.kst button.on').click();"
        "if(location.hash==='#zvijezde')document.querySelector('.kst button[data-t=stars]').click()</script>")


def _zone(s):
    from kol import sessions
    if s.get("tz") is None:
        return ("–", "", "mut")
    return (f"{sessions.NAMES.get(s.get('region'), '?')} (UTC{s['tz']:+d})", s["tz"], "")


def _sessions(con, cfg):
    import sqlite3
    from kol import sessions
    try:
        got = {r[0]: r[1:] for r in con.execute("SELECT key, n, hits, med_max24, factor FROM sessions")}
    except sqlite3.OperationalError:
        got = {}
    cur = sessions.session_of(time.time())

    def cell(key):
        n, hits, med, _ = got.get(key, (0, 0, None, None))
        return [num(n), share(hits / n if n else None), pct(med)]
    out = []
    for s, a, b in sessions.SESSIONS:
        name = sessions.NAMES[s] + (" " + badge("sada", "good") if s == cur else "")
        f = sessions.factors(con)[s] if got else 1.0
        out.append([name, f"{a:02d}-{b:02d} UTC", *cell(f"call:{s}"), *cell(f"signal:{s}"), *cell(f"vol:{s}"),
                    (f"×{f:.2f}", f, "n")])
    return table(["Sesija", "Sati", ("Poziva", "n"), ("Pogodak", "n"), ("Medijan max 24 h", "n"), ("Signala", "n"),
                  ("Točnost signala", "n"), ("Signal max 24 h", "n"), ("Tokena s volumenom", "n"),
                  ("Pogodak (volumen)", "n"), ("Volumen max 24 h", "n"), ("Faktor signala", "n")], out, tid="sess")


def _watch(con):
    from kol import live
    try:  # tables appear with the first run_kol.py round after the deploy
        mon = dict(con.execute("SELECT handle, last_run FROM monitor"))
        rows = con.execute("SELECT handle, score, since, reason FROM watch ORDER BY score DESC").fetchall()
    except sqlite3.OperationalError:
        mon, rows = {}, []
    hook = hook_handles(con)   # 9.11. (audit P42): the webhook is the channel that actually delivers in seconds
    on = live.hook_url() is not None
    out = []
    for h, sc, since, why in rows:
        st = (badge("uživo", "good") if h in mon else badge("čeka pokretanje", "warn")) if on else badge("isključeno", "bad")
        wh = badge("webhook", "good") if h.lower() in hook else ("–", 0, "mut")
        out.append([klink(h), (f"<b>{sc:.0f}</b>", sc, "n"), (esc(why), "", "wrap"), ago(since), st, wh, ago(mon.get(h))])
    return table(["X račun", ("Moć poziva", "n"), ("Razlog", "wrap"), "Na listi od", "Praćenje (xquik)", "X webhook",
                  "Zadnja sinkronizacija"],
                 out, tid="watch", empty="Još nijedan KOL ne prolazi uvjete (dovoljno poziva, rani i česti pogoci). "
                                         "Lista se puni sama kako se skupljaju izmjereni pozivi.")


def _groups(con):
    syms = _syms(con)
    rows = _rows(con, "SELECT * FROM groups ORDER BY start_ts DESC LIMIT 200")
    out = [[ts(g["start_ts"]), tlink(g["token"], syms.get(g["token"])), num(g["n_authors"]), num(g["good_authors"]),
            ((", ".join(klink(h) for h in json.loads(g["handles"]))), "", "wrap"),
            num((g["end_ts"] - g["start_ts"]) / 60, "{:.0f} min"), pct(g["r1h"]), pct(g["max24"]), lift(g["vol_lift"]),
            num(g["insiders"]), badge("DA", "bad") if g["dev_selling"] else badge("ne", "good")] for g in rows]
    return table(["Početak", "Token", ("Autora", "n"), ("Dobrih KOL-ova", "n"), ("KOL-ovi (redom)", "wrap"),
                  ("Trajanje", "n"), ("1 h", "n"), ("Max 24 h", "n"), ("Volumen ×", "n"), ("Insajdera", "n"),
                  "Dev prodaje"], out, tid="groups", empty="Još nema grupnih poziva.", limit=60)


def tname(mint, sym=None):
    """Light token link for lists of many tokens in one cell (tlink adds ~2 KB of icons per token)."""
    label = esc(sym) if sym else f"<code>{esc(mint[:4])}…</code>"
    return f'<a href="/token/{quote(mint)}" translate=no>{label}</a>'


LEADS = {  # one visible line per section of /kol: what the table shows, in plain words
    "ljestvica": "Ocjena 0-100 govori koliko tokeni rastu nakon poziva tog influencera. Od {good} naviše je dobar, "
                 "a s malo poziva ocjena je još nesigurna.",
    "tablica": "Ocjena 0-100 govori koliko tokeni rastu nakon poziva tog influencera. Od {good} naviše je dobar, "
               "a s malo poziva ocjena je još nesigurna. Presuda iz 1 h i 24 h je na ljestvici Influenceri.",
    "zajedno": "Kako prođe token kad ga zove jedan račun, a kako kad ga zove više njih u istih 30 min.",
    "shilleri": "Računi koje si plaćao za promociju: mjerimo im pozive, ali ne ulaze u signale dok se ne dokažu.",
    "tgpovijest": "Za svaki Telegram kanal: koliko je od njegovih zadnjih 50 poziva otišlo barem 2× i 5×.",
    "pozivi": "Zadnje objave s adresom tokena i koliko je cijena narasla ili pala od trenutka objave.",
    "kupnje": "Što su novčanici influencera kupili ili prodali. Često kupe prije nego što objave.",
    "provjera": "Radi li ocjena: ocjene iz starijih poziva uspoređene s pozivima koji su došli poslije.",
    "sesije": "Kako prolaze pozivi ovisno o dobu dana (Azija, Europa, SAD). Vrijeme je u UTC, kod nas je +1 h.",
    "uzivo": "Dokazani influenceri čije nove objave čitamo u par sekundi.",
    "grupe": "Tokeni koje su zvala barem 2 različita računa unutar 30 min, i kako su prošli.",
    "parovi": "Dva računa koja često zovu iste tokene. Dokazano znači da to nije slučajnost, nego vjerojatno "
              "ista ekipa ili plaćena kampanja.",
    "kopiraju": "Veliki računi koji ponavljaju pozive manjih. Tko prati malog, ulazi prije gužve.",
    "devovi": "Novčanici koji kupe prije poziva i prodaju odmah nakon njega, tj. zarađuju na onima koji kupe na poziv.",
    "korelacije": "Koja svojstva poziva najviše predviđaju rast u 24 h. +0,3 i više je jasna veza, oko 0 nema veze.",
    "brojke": "Koliko podataka alat ima o influencerima i njihovim pozivima.",
}


def _leads(html, cfg):
    """Put the LEADS line right under each matching <h2 id=...> heading."""
    import re
    def one(m):
        text = LEADS.get(m.group(1))
        return m.group(0) + lead(text.format(good=cfg.get("good_score", 60))) if text else m.group(0)
    return re.sub(r"<h2 id=([a-z]+)>.*?</h2>", one, html)


def _pairs(con):
    import sqlite3
    syms = _syms(con)
    ps = kscore.pairs(con, 2) or kscore.pairs(con, 1, 20)
    try:  # table appears with the first scoring round after the deploy
        tests = {(r[0], r[1]): r[2:] for r in con.execute("SELECT a, b, expected, lift, p, ok FROM pair_tests")}
    except sqlite3.OperationalError:
        tests = {}
    out = []
    for a, b, n, toks in ps:
        exp, lf, p, ok = tests.get((a, b), (None, None, None, None))
        st = ("–", -1, "") if ok is None else (badge("dokazano", "good"), 2, "") if ok else (
            (badge("moguća slučajnost", "warn"), 1, "") if n >= 2 else ("–", 0, ""))
        out.append([klink(a), klink(b), num(n), num(exp, "{:.1f}"), lift(lf), st,
                    (", ".join(tname(t, syms.get(t)) for t in toks[:8]), "", "wrap")])
    return table(["Prvi račun", "Drugi račun", ("Zajedničkih tokena", "n"), ("Da je slučajno", "n"),
                  ("Češće od slučaja", "n"), "Presuda", ("Koji tokeni", "wrap")], out, tid="kpairs",
                 empty="Još nema KOL-ova koji su zajedno zvali isti token.", limit=60)


def _copies(con, cfg):
    """Big accounts that keep calling tokens after a small one (kol/validate.copies)."""
    from kol import validate
    syms = _syms(con)
    foll = dict(con.execute("SELECT handle, COALESCE(followers, 0) FROM kols"))
    out = []
    for a, b, n, lag, rev, toks in validate.copies(con, cfg):
        lagtxt = f"{lag:.0f} min" if lag < 120 else f"{lag / 60:.1f} h"
        sure = badge("kopira", "good") if n >= 3 and rev * 2 <= n else badge("isti krug", "warn") if rev >= n / 2 else ""
        out.append([klink(a), num(foll.get(a)), klink(b), num(foll.get(b)), num(n), num(rev), (lagtxt, lag, "n"),
                    (sure, n - rev, ""), (", ".join(tname(t, syms.get(t)) for t in toks[:8]), "", "wrap")])
    return table(["Mali KOL", ("Pratitelji malog", "n"), ("Veliki KOL", ""), ("Pratitelji velikog", "n"),
                  ("Mali prvi", "n"), ("Veliki prvi", "n"), ("Medijan kašnjenja", "n"), "Ocjena veze",
                  ("Tokeni", "wrap")], out, tid="kcopy",
                 empty="Još nema velikih računa koji su na 2+ tokena zvali nakon manjeg.", limit=60)


def _validate(con, cfg):
    """Walk-forward check of the KOL score (kol/validate.py): verdict, the weeks, and 'said vs happened'."""
    from kol import validate
    from ui.html import info
    v = validate.load(con)
    if not v:
        return "<p class=mut>Prva provjera stiže s prvim bodovanjem nakon objave nove verzije.</p>"
    hx = f"+{cfg['hit_x']:.0%}"
    lab = {"prolazi": ("✅ Ocjena prolazi test", "good",
                       "Najbolji KOL-ovi po našoj ocjeni stvarno su pogađali češće od ostalih na pozivima koje "
                       "ocjena nije vidjela. Ocjena smije pojačavati signale."),
           "pada": ("❌ Ocjena pada test", "bad",
                    "Najbolji po ocjeni nisu bili bolji od ostalih na novim pozivima. Dok ne prođe, \"dobri KOL-ovi\" "
                    "ne pojačavaju signal; broji se samo koliko ih zove zajedno."),
           "nejasno": ("🤔 Ocjena još nije dokazana", "warn",
                       "Najbolji po ocjeni pogađaju malo češće od ostalih, ali razlika je premala da isključimo sreću. "
                       "Ocjena radi kao i prije; čekamo više poziva."),
           "malo": ("⏳ Premalo novih poziva", "warn",
                    "Još nema dovoljno izmjerenih poziva da test išta kaže. Ocjena radi kao i prije.")}[v["state"]]
    tile = (lambda x: "–" if x is None else f"{x:.0%}")
    b = [f'<p>{badge(lab[0], lab[1])} {info("Provjera točnosti", "provjera-tocnosti")}</p><p>{esc(lab[2])}</p>',
         "<div class=grid>"]
    for val, l in [(tile(v["hit_top"]), f"top 20% po ocjeni došlo do {hx} ({v['n_top']} poziva)"),
                   (tile(v["hit_rest"]), f"ostali KOL-ovi ({v['n_rest']} poziva)"),
                   (tile(v["hit_foll"]), f"top 20% po pratiteljima ({v['n_foll']} poziva)"),
                   (tile(v["hit_all"]), f"svi pozivi ({v['n_all']})")]:
        b.append(f"<div class=stat><div class=v>{val}</div><div class=l>{esc(l)}</div></div>")
    b.append("</div>")
    rows = [[ts(w["start"], "%d.%m."), num(w["kols"]),
             num(w["n_top"]), share(w["hit_top"]), num(w["n_rest"]), share(w["hit_rest"]), share(w["hit_foll"])]
            for w in v.get("weeks", [])]
    b.append(tdesc("Svaki tjedan: ocjene izračunate samo iz poziva prije tog tjedna, pa uspoređene s pozivima u tom "
                   "tjednu.") + table(["Tjedan od", ("Ocijenjenih KOL-ova", "n"), ("Poziva top 20%", "n"),
                                       ("Pogodak top 20%", "n"), ("Poziva ostali", "n"), ("Pogodak ostali", "n"),
                                       ("Pogodak po pratiteljima", "n")], rows, tid="kvweeks"))
    cal = [[f"{c['lo']:.0%}-{c['hi']:.0%}", num(c["n"]), share(c["said"]), share(c["real"])] for c in v.get("calib", [])]
    b.append(tdesc("Rekli smo / dogodilo se: kad je alat iz prošlih poziva procijenio da KOL pogađa x% puta, koliko "
                   "je njegovih sljedećih poziva stvarno pogodilo. Blizu = procjene su poštene.")
             + table(["Procjena", ("Poziva", "n"), ("Rekli smo", "n"), ("Dogodilo se", "n")], cal, tid="kvcal",
                     empty="Još nema dovoljno poziva."))
    return "".join(b)


def _wallets(con):
    syms = _syms(con)
    rows = _rows(con, "SELECT * FROM kol_wallets ORDER BY tokens DESC, sol_out DESC LIMIT 200")
    out = [[wlink(w["wallet"]), badge("rotacijski dev", "bad") if w["label"] == "rotation_dev" else badge("insajder", "warn"),
            num(w["tokens"]), num(w["sol_in"], "{:,.2f}"), num(w["sol_out"], "{:,.2f}"),
            (", ".join(tlink(t, syms.get(t)) for t in json.loads(w["token_list"] or "[]")[:8]), "", "wrap"),
            ago(w["last_seen"])] for w in rows]
    return table(["Wallet", "Oznaka", ("Tokena", "n"), ("Kupio SOL", "n"), ("Prodao u poziv SOL", "n"),
                  ("Tokeni", "wrap"), "Zadnje"], out, tid="kolw",
                 empty="Još nema walleta koji prodaju u pozive (Helius provjera ide za grupne i jake pozive).")


MEANING = {
    "Pratitelji (log)": "veći računi pomiču cijenu više?",
    "Autora u grupi": "više KOL-ova u 30 min = jači skok?",
    "Prvi autor na tokenu": "prvi koji zove vrijedi više od ponavljanja?",
    "Rast 2 h prije poziva": "pozivi nakon već velikog skoka (kasni ili plaćeni)",
    "Mcap u pozivu (log)": "manji tokeni rastu više nakon poziva?",
    "Lajkovi (log)": "angažman na postu",
    "Pregledi (log)": "koliko je ljudi vidjelo post",
    "Pronađen samo po tickeru": "post bez CA, samo $TICKER (možda drugi token)",
}


def _corr(con):
    rows = []
    for name, rho, n in kscore.correlations(con):
        kind = "" if rho is None or abs(rho) < 0.15 else ("pos" if rho > 0 else "neg")
        cell = ("–", -9, "n") if rho is None else (f'<span class="{kind}">{rho:+.2f}</span>', rho, "n")
        rows.append([esc(name), cell, num(n), (esc(MEANING.get(name, "")), "", "wrap mut")])
    return table(["Svojstvo poziva", ("Korelacija s max 24 h", "n"), ("Poziva", "n"), ("Pitanje", "wrap")], rows)


# ---------- Influenceri: mirna ljestvica (10.11., Jure: "Ostalo mi se sviđa", prijedlog 3.3 i 4.4) -----------------
# Maketa audit/2026-11-10/makete/influenceri-ljestvica.html: jedan odgovor na vrhu (hero), segment Ljestvica | Upravo
# zvali, redak = mjesto, ime, presuda i dva broja (1 h, 24 h), poredano po prvom satu; računi s manje od 5 izmjerenih
# poziva u skupini "Premalo poziva". Presuda je SAMO ui/kolsummary.verdict_stats (ista riječ na profilu, u Autopilotu i na
# Pregledu). Sve ostalo što je stranica imala (21 stupac, Zovu zajedno, shilleri, 9 sekcija za znatiželjne) je na
# /kol/analize, jedan dodir dalje. Ništa ne mijenja kako Autopilot bira račune.
BOARD_DAYS = (7, 14, 30)
BOARD_DEFAULT = 14
BOARD_SHOW, FEW_SHOW = 10, 5          # redaka prije "Prikaži još"
RUG_WARN = 0.30                       # od ovoliko rugova naviše redak to kaže narančasto (umjesto broja poziva)
RECENT_N = 20                         # "Upravo zvali": zadnjih ovoliko prvih poziva po tokenu
CURIOUS = ("provjera", "sesije", "uzivo", "grupe", "parovi", "kopiraju", "devovi", "korelacije", "brojke")
ANALIZE = (("zajedno", "Zovu zajedno", "grupe koje zovu isti token"),
           ("shilleri", "Plaćeni shilleri", "računi s tvoje liste"),
           ("tgpovijest", "Telegram calleri", "zadnjih 50 poziva"),
           ("kupnje", "Kupnje i prodaje", "što rade novčanici influencera"),
           ("tablica", "Sve brojke ljestvice", "ocjena, pogodak, vrh 24 h i ostali stupci"),
           ("znatizeljne", "Za znatiželjne", f"točnost ocjene, sesije, parovi i još {len(CURIOUS) - 3}"))
# stari linkovi /kol#<sekcija> (Pojmovnik, Pregled, Telegram stranice) vode na istu sekciju na /kol/analize
OLD_IDS = tuple(a[0] for a in ANALIZE) + CURIOUS + ("telegram",)


def _back(href, text):
    """Povratak na roditeljsku stranicu (maketa influencer.html: "‹ Influenceri")."""
    return f'<a class="kl-back" href="{esc(href)}">{esc(text)}</a>'


def _poziva(n):
    return "poziv" if n % 10 == 1 and n % 100 != 11 else "poziva"


def kname(hnd):
    """Ime računa bez emojija (pravilo 5): "@ime" za X, ime kanala za Telegram, ime novčanika za "w:"."""
    if hnd.startswith("tg:"):
        return hnd[3:]
    if hnd.startswith("w:"):
        return hnd[2:]
    return "@" + hnd


def _kname_html(hnd):
    from ui import redak as R
    if hnd.startswith("tg:"):
        return R.cat(kname(hnd), R.raw(" <span class=kl-tg>Telegram</span>"))
    return R.h(kname(hnd))


def live_handles(con, hot=None):
    """Mala slova imena računa čije objave čitamo u sekundama: pravila X webhooka (kv xhook), xquik monitor i vruća
    lista minutne provjere (X i Telegram, čita se svake 1-2 s). Za stupac "Uživo" i "Stižemo li ga"."""
    out = set(hook_handles(con))
    try:
        out |= {h.lower() for h, in con.execute("SELECT handle FROM monitor")}
    except sqlite3.Error:
        pass
    if hot is None:
        try:
            from kol import minute
            hl = minute.hot_list()
            hot = set(hl.get("x") or []) | {"tg:" + x for x in hl.get("tg") or []}
        except Exception:  # noqa: BLE001 - bez minute.db nema vruće liste
            hot = set()
    return out | {h.lower() for h in hot}


def ap_follows():
    """{ime malim slovima: 'kol' | 'ekipa'} koje Autopilot (račun pravog novca, league follows) prati; {} bez baze.
    Samo za prikaz (hero i prekidač na profilu, adm-only); tko se prati mijenja se na stranici Autopilot."""
    try:
        from league import copy, store as lstore
        from trade import settings
        lc = copy._ro(lstore.DB)
        if lc is None:
            return {}
        try:
            rows = lc.execute("SELECT kind, target FROM follows WHERE user = ? AND active = 1",
                              (settings.LEAGUE_USER,)).fetchall()
        finally:
            lc.close()
    except Exception:  # noqa: BLE001 - nema league.db ili tablice follows
        return {}
    out = {}
    for kind, target in rows:
        if kind == "kol":
            out[(target or "").lstrip("@").lower()] = "kol"
        elif kind == "ekipa":
            for m in copy.members_of(target):
                out.setdefault(m.lower(), "ekipa")
    return out


def board(kols, vs, last=None, live=()):
    """(rangirani, premalo) za jedno razdoblje. kols: [dict(handle, score, followers, stats)]; vs: verdict_stats(days).
    Računi bez ijednog poziva u razdoblju nisu na popisu. Rangirani (presuda nije "premalo") po 1 h, pa po broju
    izmjerenih poziva; premalo po broju poziva."""
    low = {k.lower(): v for k, v in vs.items()}
    last = last or {}
    ranked, few = [], []
    for k in kols:
        v = vs.get(k["handle"]) or low.get(k["handle"].lower())
        if not v or not v.get("n"):
            continue
        r = {"k": k, "v": v, "s": k.get("s") or {}, "last": last.get(k["handle"]), "live": k["handle"].lower() in live}
        (few if v["key"] == "premalo" else ranked).append(r)
    # 10.11. (pregled): the lower end of the 1-h share, as the Autopilot and Pregled rank (5 of 5 does not beat 40 of 50)
    from ui.autopilot import wilson_low
    ranked.sort(key=lambda r: (-wilson_low(r["v"]["h1"] or 0, r["v"]["n1"] or 0), -r["v"]["n1"], -(r["k"].get("score") or 0)))
    few.sort(key=lambda r: (-r["v"]["n"], -(r["k"].get("score") or 0)))
    return ranked, few


def _d24_share(v):
    return v["plus24"] / v["n24"] if v.get("n24") else None


def board_row(r, rank=None, now=None):
    """Jedan redak ljestvice (Html): mjesto, ime, presuda i broj poziva (ili narančasto "rug 32 %"), desno 1 h i 24 h;
    na računalu još Poziva, Ocjena, Rugovi, Uživo, Zadnji poziv. data-* za poredak bez novog upita."""
    from urllib.parse import quote
    from ui import redak as R
    from ui.kolsummary import VERDICT_MIN_N
    k, v, s = r["k"], r["v"], r["s"]
    n, few = v["n"], v["key"] == "premalo"
    rug = s.get("rug_rate")
    rugw = rug is not None and rug >= RUG_WARN
    rugtxt = R.raw(f'<span class=warn>rug {esc(R.pct(rug, sign=False, frac=True))}</span>') if rugw else None
    if few:
        why = rugtxt or (f"{n} {_poziva(n)} · premalo" if n < VERDICT_MIN_N else f"{n} {_poziva(n)} · izmjereno {v['n1']}")
    else:
        why = R.cat(R.dot(v["dot"], v["word"]), " · ", rugtxt or f"{n} {_poziva(n)}")
    d24 = _d24_share(v)
    c1 = R.pct(v["h1"], sign=False, frac=True) if v["h1"] is not None else "–"
    c2 = R.pct(d24, sign=False, frac=True) if d24 is not None else "–"
    m1 = " mut" if few or v["h1"] is None else ""
    m2 = " mut" if few or (v.get("n24") or 0) < VERDICT_MIN_N else ""
    sc = k.get("score")
    data = (f' data-h1="{-1 if v["h1"] is None else round(v["h1"], 4)}" data-d24="{-1 if d24 is None else round(d24, 4)}"'
            f' data-sc="{-1 if sc is None else round(sc, 1)}" data-n="{n}"')
    t24 = (f"{v['plus24']} od {v['n24']} u plusu dan kasnije" if v.get("n24") else "cijena dan kasnije još nije poznata")
    title = f"1 h: {v['hits1']} od {v['n1']} do +10 % prije stopa · 24 h: {t24}"
    return R.Html(
        f'<a class="kl-kr" href="/kol/{quote(k["handle"])}" title="{esc(title)}"{data}>'
        f'<span class=rk>{"" if rank is None else rank}</span><span class=tk>{_kname_html(k["handle"])}</span>'
        f'<span class=why>{R.h(why)}</span><span class="c1{m1}">{c1}</span><span class="c2{m2}">{c2}</span>'
        f'<span class="x n">{n}</span><span class="x sc">{"–" if sc is None else f"{sc:.0f}"}</span>'
        f'<span class="x rug{" warn" if rugw else ""}">{R.pct(rug, sign=False, frac=True) if rug is not None else "–"}</span>'
        f'<span class="x lv">{"uživo" if r["live"] else "–"}</span>'
        f'<span class="x last">{R.ago(r["last"], now) if r["last"] else "–"}</span><span class=chev></span></a>')


def _set(ranked, few, g, d, on, n_group, now):
    """Popis jednog izbora (skupina računa × razdoblje); vidljiv je samo izabrani (JS ispod, bez novog upita)."""
    out = [f'<div class=kl-set data-g={g} data-d={d}{"" if on else " hidden"}>']
    if not ranked and not few:
        who = "nijedan od velikih računa" if g == "stars" else "nijedan manje poznati račun"
        more = ' <a href="#" data-d30>Pogledaj 30 dana</a>' if d < 30 else ""
        out.append(f'<div class=kl-empty><b>Nitko nije zvao</b><p>U zadnjih {d} dana {who} ({n_group}) nema izmjeren '
                   f'poziv iznad 30k $.</p>{more}</div></div>')
        return "".join(out)
    if ranked:
        out.append('<div class="kl-list kl-top">' + "".join(board_row(r, i, now) for i, r in enumerate(ranked, 1))
                   + "</div>")
        if len(ranked) > BOARD_SHOW:
            out.append(f"<button type=button class=kl-more>Prikaži još {len(ranked) - BOARD_SHOW}</button>")
    else:
        out.append(f"<p class=ms-hint>U zadnjih {d} dana još nitko nema 5 poziva izmjerenih od minute poziva.</p>")
    if few:
        out.append("<div class=kl-sec><b>Premalo poziva</b> · ispod 5, ne rangiraju se</div>"
                   '<div class="kl-list kl-few">' + "".join(board_row(r, None, now) for r in few) + "</div>")
        if len(few) > FEW_SHOW:
            out.append(f"<button type=button class=kl-more>Prikaži svih {len(few)}</button>")
    return "".join(out) + "</div>"


def _recent_html(con, vs, now):
    """"Upravo zvali": zadnji prvi pozivi po tokenu (calls_ts), tko je zvao s točkom njegove presude, promjena od
    poziva (zadnja izmjerena: 24 h, 6 h ili 1 h) i mcap kod poziva."""
    from urllib.parse import quote
    from ui import redak as R
    from kol.minute import MIN_MCAP
    low = {k.lower(): v for k, v in vs.items()}
    try:
        rows = con.execute("SELECT c.token, c.handle, c.ts, c.mcap0, c.r1h, c.r6h, c.r24h, COALESCE(t.symbol, c.symbol), "
                           "c.text FROM calls c LEFT JOIN tokens t ON t.token = c.token WHERE c.kind = 'call' "
                           "AND c.first_by_kol = 1 ORDER BY c.ts DESC LIMIT ?", (RECENT_N,)).fetchall()
    except sqlite3.Error:
        rows = []
    items = []
    for tok, hnd, t, mc, r1, r6, r24, sym, text in rows:
        v = low.get(hnd.lower()) or {}
        ch, lab = next(((x, l) for x, l in ((r24, "24 h"), (r6, "6 h"), (r1, "1 h")) if x is not None), (None, None))
        small = mc is not None and mc < MIN_MCAP
        if ch is not None:     # promjena od poziva (zadnja izmjerena), ispod koliko je bilo i mcap kod poziva
            val, vt, sub = R.pct(ch, frac=True), R.tone(ch), (f"{lab} · {R.usd(mc)}" if mc else lab)
        else:                  # svjež poziv: mcap kod poziva, prvi sat još traje (bez cijene uživo u kol.db)
            val, vt, sub = (R.usd(mc) if mc else "–"), None, "1 h još traje"
        items.append(R.row(sym or _ticker(text) or tok[:6], R.cat(R.dot(v.get("dot", "")), kname(hnd), " · ", R.ago(t, now)),
                           val, "ispod 30k $" if small else sub, href=f"/token/{quote(tok)}", value_tone=vt,
                           sub_tone="warn" if small else "mut"))
    return (R.rows(items, empty="Još nema poziva. Bot ih skuplja sam iz X pretraga i Telegram kanala.")
            + R.raw('<p class=ms-hint><a class=ms-acc href="/kol/analize#pozivi">Svi pozivi s objavom i brojkama</a></p>'))


def _hero(ranked14, follows):
    """Jedan odgovor ekrana: račun s najboljim prvim satom (presuda drži se ili samo brzo) i do dva koji se drže i dan
    kasnije. Bez izmjerenih poziva: iskreno "još nema presude"."""
    from urllib.parse import quote
    from ui import redak as R
    from ui.kolsummary import verdict_counts
    if not ranked14:
        return R.hero("Još nema presude", "Minutna provjera još nije izmjerila 5 poziva nijednog računa u zadnjih "
                      f"{BOARD_DEFAULT} dana; dotad su svi u skupini Premalo poziva.", label="Najbolji za brzi ulaz i izlaz")
    best = next((r for r in ranked14 if r["v"]["key"] in ("samo_brzo", "drzi_se")), None)
    if best is None:
        return R.hero("Nitko se ne isplati", f"U zadnjih {BOARD_DEFAULT} dana nijedan račun ne dođe do +10 % prije stopa "
                      "−20 % u barem pola poziva.", label="Najbolji za brzi ulaz i izlaz")
    v, hnd = best["v"], best["k"]["handle"]
    fol = R.raw("<span class=adm-only> · Autopilot ga prati</span>") if hnd.lower() in follows else None
    facts = R.cat(R.dot(v["dot"], v["word"]), f" · {v['n']} {_poziva(v['n'])}", fol)
    hold = [r for r in ranked14 if r["v"]["key"] == "drzi_se" and r is not best][:2]
    foot = (R.raw("<span>Drže se i 24 h: " + " · ".join(f"<b>{esc(kname(r['k']['handle']))}</b>" for r in hold) + "</span>")
            if hold else None)
    label = "Najbolji za brzi ulaz i izlaz" if v["key"] == "samo_brzo" else "Najbolji u prvom satu, drži se i dan kasnije"
    return R.hero(kname(hnd), verdict_counts(v), label=label, facts=facts, href=f"/kol/{quote(hnd)}", foot=foot)


def page(qs):
    """/kol: Influenceri. Hero, segment Ljestvica | Upravo zvali, ljestvica po 1 h (7/14/30 dana, manje poznati ili
    veliki računi; sve se bira na stranici bez novog upita), Analize. Gradi se u djetetu i čuva kao snimka (run_ui
    HEAVY/SNAPSHOT_ONLY): verdict_stats tri puta (jedno čitanje kol.db po razdoblju), kols, zadnji poziv iz 30 dana."""
    from ui import kolsummary, redak as R
    from ui.public import is_star, star_handles
    con = store.ro()
    top = R.top("Influenceri")   # bez ikone povećala: tražilica je u zaglavlju svake stranice
    if con is None:
        return "Influenceri", f'<div class="ms-page ms-wide kl"><style>{KL_CSS}</style>{top}<p class=ms-hint>Još nema podataka.</p></div>'
    now = time.time()
    try:
        kols = []
        for k in _rows(con, "SELECT handle, name, followers, score, stats FROM kols WHERE score IS NOT NULL"):
            k["s"] = json.loads(k["stats"] or "{}")
            kols.append(k)
        last = {}
        try:   # range read on calls_ts (a GROUP BY here walks the whole calls_handle index and looks up every row)
            for hnd, t in con.execute("SELECT handle, ts FROM calls WHERE ts >= ? AND kind NOT IN ('buy', 'sell')",
                                      (int(now) - max(BOARD_DAYS) * 86400,)):
                if t > last.get(hnd, 0):
                    last[hnd] = t
        except sqlite3.Error:
            pass
        live = live_handles(con)
        stars = star_handles()
        star_of = {k["handle"]: is_star(k, stars) for k in kols}
        vss = {d: kolsummary.verdict_stats(d) for d in BOARD_DAYS}
        recent = _recent_html(con, vss[BOARD_DEFAULT], now)
        n_all = con.execute("SELECT COUNT(*) FROM kols").fetchone()[0]
    finally:
        con.close()
    follows = ap_follows()
    groups = {"rising": [k for k in kols if not star_of[k["handle"]]], "stars": [k for k in kols if star_of[k["handle"]]]}
    sets = []
    for g, ks in groups.items():
        for d in BOARD_DAYS:
            ranked, few = board(ks, vss[d], last, live)
            sets.append(_set(ranked, few, g, d, g == "rising" and d == BOARD_DEFAULT, len(ks), now))
    ranked14, _ = board(kols, vss[BOARD_DEFAULT], last, live)
    # izbor je pravi <select> (na mobitelu otvara sustavni popis), nevidljiv preko teksta izabranog: tako je širok koliko
    # izabrani natpis, a ne najduži, i izgleda kao poveznica iz makete
    sel = lambda name, opts, cur: (
        f'<label class=kl-sel><span>{esc(next(t for v, t, _ in opts if v == cur))}</span>'
        f'<select id={name} aria-label="{esc(opts[0][2])}">' + "".join(
            f'<option value="{v}"{" selected" if v == cur else ""}>{esc(t)}</option>' for v, t, _ in opts) + "</select></label>")
    ctl = ('<div class=kl-ctl>'
           + sel("kl-g", [("rising", f"Manje poznati računi · {len(groups['rising'])}", "Računi"),
                          ("stars", f"Veliki računi · {len(groups['stars'])}", "")], "rising")
           + sel("kl-d", [(str(d), f"{d} dana", "Razdoblje") for d in BOARD_DAYS], str(BOARD_DEFAULT)) + "</div>")
    th = ('<div class=kl-th><span class=so>'
          + sel("kl-so", [("h1", "Poredano po prvom satu", "Poredak"), ("d24", "Poredano po 24 h", ""),
                          ("sc", "Poredano po ocjeni", ""), ("n", "Poredano po broju poziva", "")], "h1")
          + '</span><span>1 h</span><span>24 h</span><span class=d>Poziva</span><span class=d>Ocjena</span>'
            '<span class=d>Rugovi</span><span class=d>Uživo</span><span class=d>Zadnji poziv</span><span></span></div>')
    built = kolchart._local(now)
    hint = R.hint(f"1 h: koliko poziva dođe do +10 % prije stopa −20 %, od minute poziva (po tome bira Autopilot). "
                  f"24 h: koliko ih je u plusu dan kasnije. Ocjena 0–100 ostaje na profilu i u stupcima na računalu. "
                  f"Ljestvica od {built:%H:%M}.")
    analize = R.rows([R.row(t, s, value=str(len(CURIOUS)) if sid == "znatizeljne" else None, value_tone="mut",
                            href=f"/kol/analize#{sid}") for sid, t, s in ANALIZE])
    body = (f'<div class="ms-page ms-wide kl"><style>{KL_CSS}</style>{top}'
            f'<p class=ms-sub>{esc(R.num(n_all))} računa · svaki poziv mjeren nakon 1 h i 24 h</p>'
            + _hero(ranked14, follows)
            + R.seg([("#ljestvica", "Ljestvica"), ("#pozivi", "Upravo zvali")], "#ljestvica")
            + f'<div class=kl-pane data-pane=ljestvica id=ljestvica>{ctl}{th}{"".join(sets)}{hint}</div>'
            + f'<div class=kl-pane data-pane=pozivi id=pozivi hidden>{recent}</div>'
            + R.section("Analize", sid="analize") + analize + "</div>" + KL_JS.replace("__OLD__", json.dumps(list(OLD_IDS))))
    return "Influenceri", _calm(body)


KL_JS = """<script>(()=>{const qa=s=>[...document.querySelectorAll(s)],q=s=>document.querySelector(s);
const hs=decodeURIComponent(location.hash.slice(1));if(__OLD__.includes(hs)){location.replace('/kol/analize#'+hs);return}
const pane=p=>{qa('.kl-pane').forEach(e=>e.hidden=e.dataset.pane!==p);qa('.kl .ms-seg a').forEach(a=>a.classList.toggle('on',a.getAttribute('href')==='#'+p))};
qa('.kl .ms-seg a').forEach(a=>a.onclick=e=>{e.preventDefault();const p=a.getAttribute('href').slice(1);pane(p);history.replaceState(null,'','#'+p)});
const g=q('#kl-g'),d=q('#kl-d'),so=q('#kl-so');if(!g)return;
const show=()=>qa('.kl-set').forEach(e=>e.hidden=!(e.dataset.g===g.value&&e.dataset.d===d.value));
qa('.kl-sel select').forEach(x=>x.addEventListener('change',()=>{x.previousElementSibling.textContent=x.selectedOptions[0].text}));
g.addEventListener('change',show);d.addEventListener('change',show);qa('[data-d30]').forEach(a=>a.onclick=e=>{e.preventDefault();d.value='30';d.dispatchEvent(new Event('change'))});
so.addEventListener('change',()=>{const k=so.value;qa('.kl-top').forEach(l=>{const rs=[...l.children];rs.sort((a,b)=>(+b.dataset[k])-(+a.dataset[k]));
rs.forEach((r,i)=>{l.appendChild(r);const n=r.querySelector('.rk');if(n)n.textContent=i+1})})});
qa('.kl-more').forEach(b=>b.onclick=()=>{b.previousElementSibling.classList.add('open');b.remove()});
if(hs==='pozivi')pane('pozivi');if(hs==='zvijezde'){g.value='stars';g.dispatchEvent(new Event('change'))}})()</script>"""

# Vrijednosti iz maketa influenceri-ljestvica.html i influencer.html (prefiks kl-, uz ui/html.MS_CSS i ui/kolchart.CSS).
# Stupci za računalo idu po širini stranice (container query), ne prozora: s bočnim izbornikom (1001 px+) sadržaj je
# uži od 900 px, pa bi prozor od 1050 px stisnuo ime na 20 px.
KL_CSS = """
.kl{container-type:inline-size}
.kl-tg{font-size:13px;font-weight:400;color:var(--mut);margin-left:4px}
.kl-ctl{display:flex;justify-content:space-between;gap:12px;font-size:15px;margin:16px 0 0}
.kl-sel{position:relative;display:inline-flex;align-items:center;color:var(--acc);font-weight:500;font-size:15px}
.kl-sel select{position:absolute;inset:0;width:100%;height:100%;opacity:0;cursor:pointer;font:inherit;border:0;margin:0}
.kl-sel::after{content:"";display:inline-block;width:6px;height:6px;border-right:1.5px solid var(--acc);border-bottom:1.5px solid var(--acc);transform:rotate(45deg);margin:0 2px 3px 7px;pointer-events:none}
.kl-sel:focus-within{outline:2px solid color-mix(in srgb,var(--acc) 35%,transparent);outline-offset:2px;border-radius:4px}
.kl-kr,.kl-th{display:grid;grid-template-columns:24px minmax(0,1fr) 50px 50px 12px;column-gap:10px;align-items:center}
.kl-kr{grid-template-areas:"rk tk c1 c2 chev" "rk why c1 c2 chev";padding:11px 0;border-bottom:1px solid var(--line);min-height:64px;color:var(--fg);text-decoration:none}
a.kl-kr:hover .tk{color:var(--acc)}
.kl-kr .rk{grid-area:rk;font-size:15px;color:var(--mut)}
.kl-kr .tk{grid-area:tk;font-size:17px;font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.kl-kr .why{grid-area:why;font-size:15px;color:var(--mut);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.kl-kr .why .warn,.kl-kr .rug.warn{color:var(--warn)}
.kl-kr .c1,.kl-kr .c2{text-align:right;font-size:17px;font-weight:600;white-space:nowrap}
.kl-kr .c1{grid-area:c1}.kl-kr .c2{grid-area:c2}
.kl-kr .c1.mut,.kl-kr .c2.mut{font-weight:400;color:var(--mut)}
.kl-kr .chev{grid-area:chev;width:8px;height:8px;border-right:2px solid var(--line2);border-top:2px solid var(--line2);transform:rotate(45deg)}
.kl-kr .x{display:none}
.kl-th{font-size:13px;color:var(--mut);padding:16px 0 8px;border-bottom:1px solid var(--line)}
.kl-th span{text-align:right}.kl-th .so{grid-column:1/3;text-align:left}.kl-th .d{display:none}
.kl-sec{font-size:15px;font-weight:600;color:var(--mut);margin:26px 0 0;padding:0 0 6px;border-bottom:1px solid var(--line)}
.kl-sec b{color:var(--fg)}
.kl-top:not(.open)>.kl-kr:nth-child(n+11),.kl-few:not(.open)>.kl-kr:nth-child(n+6){display:none}
.kl-more{display:block;width:100%;text-align:center;font:inherit;font-size:15px;color:var(--acc);padding:16px 0 0;border:0;background:none;cursor:pointer}
.kl-empty{text-align:center;padding:24px 6px 16px}.kl-empty b{display:block;font-size:17px;font-weight:600}
.kl-empty p{font-size:15px;color:var(--mut);margin:6px 0 12px;line-height:1.4}.kl-empty a{font-size:15px;color:var(--acc);font-weight:500}
.kl .ms-v.mut{font-weight:400;color:var(--mut)}
.kl a.ms-acc,.kl .ms-hint a{color:var(--acc);text-decoration:none}
.kl-back{display:inline-flex;align-items:center;gap:7px;color:var(--acc);font-size:17px;padding:8px 0 0;text-decoration:none}
.kl-back::before{content:"";width:9px;height:9px;border-left:2px solid var(--acc);border-bottom:2px solid var(--acc);transform:rotate(45deg);margin-left:3px}
.kl-dh{padding:12px 0 0}.kl-dh .ms-h1{overflow-wrap:anywhere}
.kl-dh .s{font-size:15px;color:var(--mut);margin-top:4px}.kl-dh .s a{color:var(--acc);text-decoration:none}
.kl-key{margin-top:6px}.kl-key .ms-row{min-height:62px}.kl-key .ms-e{max-width:60%}
.kl-key .ms-v{font-size:22px;font-weight:700;letter-spacing:-.02em}.kl-key .ms-e .ms-s{white-space:nowrap}
.kl-sw{display:flex;align-items:center;justify-content:space-between;gap:12px;padding:12px 0;border-top:1px solid var(--line);margin:8px 0 0;color:var(--fg);text-decoration:none}
.kl-sw .t{font-size:17px;font-weight:600}.kl-sw .s{font-size:15px;color:var(--mut)}
.kl-swi{flex:none;width:51px;height:31px;border-radius:999px;background:var(--line2);position:relative}
.kl-swi::after{content:"";position:absolute;top:2px;left:2px;width:27px;height:27px;border-radius:50%;background:#fff;box-shadow:0 2px 4px rgba(0,0,0,.2)}
.kl-swi.on{background:var(--good)}.kl-swi.on::after{left:auto;right:2px}
.kl-warn{font-size:15px;color:var(--warn);margin:10px 0 0;line-height:1.4}
.kl-old h2{font-size:22px;font-weight:700;letter-spacing:-.025em;margin:40px 0 8px}
@container (min-width:820px){
 .kl-kr,.kl-th{grid-template-columns:28px minmax(0,1fr) 70px 70px 70px 64px 70px 64px 104px 14px;column-gap:14px}
 .kl-kr{grid-template-areas:"rk tk c1 c2 n sc rug lv last chev" "rk why c1 c2 n sc rug lv last chev"}
 .kl-kr .x{display:block;text-align:right;font-size:15px;grid-row:1/3}
 .kl-kr .n{grid-area:n}.kl-kr .sc{grid-area:sc}.kl-kr .rug{grid-area:rug}.kl-kr .lv{grid-area:lv;color:var(--mut)}.kl-kr .last{grid-area:last;color:var(--mut)}
 .kl-th .d{display:block}
}
@container (min-width:760px){
 .kl-g2{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);column-gap:44px;align-items:start}
 .kl-g2>div>.ms-h2:first-child{margin-top:28px}
}
"""


def _foll(n):
    """Pratitelji kratko: "850", "4,0 tis.", "34 tis.", "1,2 mil."."""
    from ui import redak as R
    if not n:
        return None
    if n < 1000:
        return R.num(n)
    if n < 1e6:
        return f"{R.num(n / 1000, 0 if n >= 10000 else 1)} tis."
    return f"{R.num(n / 1e6, 1)} mil."


def _ap_row(handle):
    """Redak "Autopilot ga prati" s prekidačem (samo administrator: adm-only). Stanje iz league follows; mijenja se na
    stranici Autopilot (prekidač vodi tamo), jer je to pravi novac i ide kroz postojeću potvrdu."""
    kind = ap_follows().get(handle.lower())
    if kind == "kol":
        t, s = "Autopilot ga prati", "kupuje na njegove pozive, izlaz po pravilima Autopilota"
    elif kind == "ekipa":
        t, s = "Autopilot ga prati", "kao dio ekipe, izlaz po pravilima Autopilota"
    else:
        t, s = "Autopilot ga ne prati", "praćenje se uključuje na stranici Autopilot"
    on = " on" if kind else ""
    # div nosi adm-only: za administratora ui/html vraća "display:revert", što bi <a> pretvorilo u inline
    return (f'<div class=adm-only><a class=kl-sw href="/pravi-trade#influenceri"><div><div class=t>{t}</div>'
            f'<div class=s>{s}</div></div><span class="kl-swi{on}" role=switch aria-checked="{"true" if kind else "false"}">'
            '</span></a></div>')


def _first_hour(mrow, call, now):
    """(vrijednost, ton, sporedno) ishoda prvog sata jednog poziva za "Zadnji pozivi"."""
    from ui import redak as R
    from kol.minute import MIN_MCAP, clean_hit
    t, mc, r1, r24 = call["ts"], call["mcap0"], call["r1h"], call["r24h"]
    day = (f"24 h {R.pct(r24, frac=True)}", R.tone(r24)) if r24 is not None else (
        ("24 h još traje" if now - t < 86400 else "24 h –"), None)
    if mc is not None and mc < MIN_MCAP:
        return "ne broji se", "mut", ("ispod 30k $", None)
    if mrow:
        if clean_hit(mrow, 10):
            return f"+10 % u {mrow['t10']} min", "pos", day
        if mrow["sl_min"] is not None:
            return "stop −20 %", "neg", day
        return f"{R.pct(mrow['r60'] or 0, frac=True)} u 1 h", R.tone(mrow["r60"]) or "mut", day
    if now - t < 70 * 60:
        return "1 h još traje", "mut", day
    if r1 is not None:
        return f"{R.pct(r1, frac=True)} u 1 h", R.tone(r1) or "mut", day
    return "nije izmjereno", "mut", day


def _last_calls(con, handle, now, n=5):
    """Zadnjih n poziva (kind call/bot) s ishodom prvog sata iz minute.db (po ključu) i rezultatom nakon 24 h."""
    from urllib.parse import quote
    from ui import redak as R
    from kol import minute
    rows = _rows(con, "SELECT c.tweet_id, c.token, c.ts, c.mcap0, c.r1h, c.r24h, c.text, COALESCE(t.symbol, c.symbol) sym "
                      "FROM calls c LEFT JOIN tokens t ON t.token = c.token WHERE c.handle = ? AND c.kind IN ('call', 'bot') "
                      "ORDER BY c.ts DESC LIMIT ?", (handle, n))
    mrows = {}
    mcon = minute.ro()
    if mcon is not None and rows:
        try:
            for c in rows:
                got = minute._rows(mcon, "tweet_id = ? AND token = ?", (c["tweet_id"], c["token"]))
                if got:
                    mrows[(c["tweet_id"], c["token"])] = got[0]
        except sqlite3.Error:
            pass
        finally:
            mcon.close()
    items = []
    for c in rows:
        val, vt, (sub, st) = _first_hour(mrows.get((c["tweet_id"], c["token"])), c, now)
        mc = f" · na {R.usd(c['mcap0'])}" if c["mcap0"] else ""
        items.append(R.row(c["sym"] or _ticker(c["text"]) or c["token"][:6], f"{kolchart.when(c['ts'], now)}{mc}",
                           val, sub, href=f"/token/{quote(c['token'])}", value_tone=vt, sub_tone=st or "mut"))
    return R.rows(items, empty="Još nema njegovih poziva s adresom tokena.")


def profile(con, k, handle, now=None):
    """/kol/<ime> (10.11., Jure, prijedlog 4.5, maketa influencer.html): presuda za 14 dana i četiri broja koja je nose
    (nakon 60 min, nakon 24 h, 10 $ u svaki poziv, stižemo li ga), prekidač Autopilota (administrator), graf i dva reda
    kvadratića, zadnjih 5 poziva, "Više o njemu". Sve stare brojke su na /kol/<ime>/vise i /kol/<ime>/pozivi."""
    from urllib.parse import quote
    from ui import kolsummary as KS, redak as R
    now = now or time.time()
    s = json.loads(k["stats"] or "{}")
    v = KS.kol_verdict(handle)
    sr = kolchart.series(handle, 14, now)
    sc = k["score"] if k["score"] is not None else s.get("bot_score")
    q = quote(handle)
    # zaglavlje: ime, tko je, pratitelji, profil
    u = profile_url(handle)
    who = [k["name"]] if k.get("name") and k["name"].lower() not in (handle.lower(), kname(handle).lower()) else []
    if not handle.startswith("tg:") and _foll(k.get("followers")):
        who.append(f"{_foll(k['followers'])} pratitelja")
    link = (f' · <a href="{esc(u)}" target=_blank rel=noopener>{"kanal na Telegramu" if handle.startswith("tg:") else "profil na X-u"}</a>'
            if u else "")
    head = (_back("/kol", "Influenceri") + f'<div class=kl-dh><h1 class=ms-h1>{esc(kname(handle))}</h1>'
            f'<div class=s>{esc(" · ".join(who))}{link if who else link[3:]}</div></div>')
    warn = ""
    if k.get("bot"):
        warn = ('<p class=kl-warn>Bot, spam, promo ili dev račun: njegove objave se ne broje kao pozivi. Ne otvaraj linkove '
                'iz njegovih objava.</p>')
    # presuda i četiri broja
    rug = s.get("rug_rate")
    rugw = R.raw(f' · <span class=warn>rug {esc(R.pct(rug, sign=False, frac=True))}</span>') if (rug or 0) >= RUG_WARN else None
    facts = R.cat(f"{v['word']} · {v['n']} {_poziva(v['n'])}", f" · ocjena {sc:.0f}" if sc is not None else None, rugw)
    title = ("Još bez presude" if v["word"] == "premalo podataka" else KS.VERDICT_TITLE[v["key"]])
    panel = R.verdict(title, KS.verdict_counts(v), label=f"Presuda za zadnjih {sr['days']} dana", facts=facts, kind=v["dot"])
    n1, n24 = v["n1"], v["n24"]
    fast, hold = sr["fast_usd"], sr["hold_usd"]
    money = R.raw(" · ".join(f'<span class={kolchart._tone(x) or "mut"}>{esc(kolchart.money(x))}</span>' for x in (fast, hold)))
    con_live = handle.lower() in live_handles(con)
    med = sr["med_t10"]
    key = R.rows([
        R.row("Nakon 60 min", "do +10 % prije stopa −20 %", R.share(v["hits1"], n1) if n1 else "–",
              R.pct(v["h1"], sign=False, frac=True) if v["h1"] is not None else "još nije izmjereno", sub_tone="mut"),
        R.row("Nakon 24 h", "u plusu dan kasnije", R.share(v["plus24"], n24) if n24 else "–",
              f"{n24 - v['plus24']} u minusu" if n24 else "još se ne zna", sub_tone="neg" if n24 > v["plus24"] else "mut"),
        R.row("10 $ u svaki poziv", "brzi izlaz · drži 24 h", money, "prije naknada", sub_tone="mut"),
        R.row("Stižemo li ga", "pratimo ga uživo, 1–2 s" if con_live else "vidimo ga tek pri pretrazi, sporije",
              "Da" if con_live else "Sporije",
              (f"+10 % za {R.num(med, 0)} min" if med else "+10 % u prvoj minuti") if med is not None else "–", sub_tone="mut"),
    ], cls="kl-key")
    left = f"<div>{panel}{key}{_ap_row(handle)}</div>"
    ch = kolchart.chart(sr)
    right = ("<div>" + R.section("10 $ u svaki poziv")
             + (ch or R.hint(f"Još nema izmjerenih poziva u zadnjih {sr['days']} dana."))
             + (R.section("Svaki poziv, redom") + kolchart.strips(sr) if (sr["h1"] or sr["d24"]) else "") + "</div>")
    n_posts = con.execute(f"SELECT COUNT(*) FROM calls WHERE handle = ? AND {POSTS}", (handle,)).fetchone()[0]
    recent = (R.section("Zadnji pozivi", f"Svih {n_posts}" if n_posts else None, f"/kol/{q}/pozivi")
              + _last_calls(con, handle, now))
    lifts = [x for x, in con.execute("SELECT vol_lift FROM calls WHERE handle = ? AND kind IN ('call', 'bot') AND "
                                     "first_by_kol = 1 AND p0 IS NOT NULL AND bad IS NULL AND vol_lift IS NOT NULL", (handle,))]
    has_tr = con.execute(f"SELECT 1 FROM calls WHERE handle = ? AND {TRADES} LIMIT 1", (handle,)).fetchone()
    more = [R.row(f"Kako je dobio ocjenu {sc:.0f}" if sc is not None else "Kako je dobio ocjenu",
                  "bodovi za pogodak, rast, volumen, rugove i kasne pozive", href=f"/kol/{q}/vise#ocjena"),
            R.row("Koliko ga tržište sluša",
                  (f"volumen se udvostruči nakon {R.pct(sum(1 for x in lifts if x >= 2) / len(lifts), sign=False, frac=True)} objava"
                   if lifts else "volumen i cijena sat nakon objave"), href=f"/kol/{q}/vise#trziste"),
            R.row("Zove zajedno s", "tko pojačava njegove pozive i čije pozive on pojačava", href=f"/kol/{q}/vise#ekipa")]
    if has_tr:
        more.append(R.row("Njegov novčanik", "kupnje i prodaje oko njegovih poziva", href=f"/kol/{q}/vise#novcanik"))
    foot = ('<p class=ms-hint>Nakon 60 min: od zatvaranja minute poziva, cilj +10 % prije stopa −20 %, iz 1-min svijeća. '
            'Nakon 24 h: cijena dan poslije objave. Brzi izlaz: prodaja na +10 %, na stopu ili nakon 60 min. Pozivi na tokene '
            'ispod 30k $ se ne broje. <a class=ms-acc href="/pojmovnik">Pojmovnik</a></p>')
    body = (f'<div class="ms-page ms-wide kl"><style>{KL_CSS}{kolchart.CSS}</style>{head}{warn}'
            f'<div class=kl-g2>{left}{right}</div>{recent}' + R.section("Više o njemu") + R.rows(more) + foot + "</div>")
    return kname(handle), _calm(body)


def _calm(html):
    """Naslovi sekcija mirnih stranica bez reda čipova (ui/secnav ga gradi od 3+ <h2>; makete ga nemaju)."""
    return html.replace('<h2 class="ms-h2"', '<h2 class="ms-h2 nosec"')


def _sub_shell(handle, title, inner):
    from urllib.parse import quote
    return (f'<div class="ms-page ms-wide kl kl-old"><style>{KL_CSS}</style>{_back("/kol/" + quote(handle), kname(handle))}'
            f'<div class=kl-dh><h1 class=ms-h1>{esc(title)}</h1></div>{inner}</div>')


def calls_page(con, handle):
    """/kol/<ime>/pozivi: današnja tablica svih objava s adresom (500), stari grafovi za cijelo razdoblje."""
    n = con.execute(f"SELECT COUNT(*) FROM calls WHERE handle = ? AND {POSTS}", (handle,)).fetchone()[0]
    inner = (f"<p class=ms-sub>{n} objava s adresom tokena, najnovije prve. Postoci su od trenutka objave; stupci 1 h, "
             "6 h i 24 h se pune kad to vrijeme prođe.</p>"
             + calls_table(con, "handle = ?", (handle,), 500, "kcalls", show_kol=False) + _charts(con, handle))
    return f"Pozivi {kname(handle)}", _sub_shell(handle, f"Pozivi {kname(handle)}", inner)


def more_page(con, k, handle, cfg):
    """/kol/<ime>/vise: "Više o njemu" (kako je dobio ocjenu, koliko ga tržište sluša, ekipa, novčanik): sve brojke i
    oznake koje je profil imao prije 10.11., sadržaj isti."""
    from ui import redak as R
    s = json.loads(k["stats"] or "{}")
    b = ["<h2 id=ocjena>Kako je dobio ocjenu</h2>"]
    sc = k["score"] if k["score"] is not None else s.get("bot_score")
    rel = k["power_rel"] if k["power_rel"] is not None else s.get("bot_rel")
    b.append(R.rows([
        R.row("Ocjena" if not k.get("bot") else "Moć objava (bot)", "0–100, koliko tokeni rastu nakon poziva",
              f"{sc:.0f}" if sc is not None else "–"),
        R.row("Moć po pratitelju", "ocjena naspram veličine računa", f"{R.num(rel, 2)}×" if rel is not None else "–"),
        R.row("Pratitelja", None, R.num(k["followers"] or 0)),
        R.row("Izmjerenih poziva", "prvi poziv po tokenu, cijena izmjerena", R.num(s.get("measured", 0))),
        R.row("Pogodak (stara mjera)", f"vrh +{cfg['hit_x']:.0%} u 24 h; ulazi u bodove",
              R.pct(s["hit_rate"], sign=False, frac=True) if "hit_rate" in s else "–"),
        R.row("Hvalisanja", "objave nakon skoka", R.num(s.get("brags", 0))),
    ]))
    if k.get("bot"):
        b.append('<p class=kl-warn>Bot, spam, promo ili dev račun. Razlog: ' + esc(k.get("bot_why") or "") + '. Njegove '
                 'objave se ne broje kao pozivi: ne ulaze u grupe KOL-ova, ljestvicu, praćenje uživo, copy trading, '
                 'konvergenciju, demo ulaze ni statistiku X objava.</p>')
    if s.get("trial") and not k.get("bot"):
        b.append(f'<p class=kl-warn>Na probi: još ga ne pratimo uživo, ne ulazi u copy trading ni kao "dobar KOL" u '
                 f'grupni signal. {esc(s.get("trial_why") or "")}</p>')
    if s.get("rugger") and not k.get("bot"):
        b.append(f'<p class=kl-warn>Puno rugova: {esc(s.get("rug_why") or "")}. Ostaje na listi, ali njegove objave čitamo '
                 'rjeđe (svaka 3 dana).</p>')
    if s.get("bought"):
        b.append(f'<p class=ms-hint>Njegov novčanik je kupio {s["bought"]} od tokena koje je zvao: stavlja novac iza '
                 'objave.</p>')
    b.append(_audit_line(con, handle))
    if s.get("parts"):
        w, p = cfg["weights"], s["parts"]
        expl = {"hit": f"{s['hit_rate']:.0%} poziva s barem +{cfg['hit_x']:.0%} u 24 h",
                "max24": f"medijan najvećeg rasta u 24 h {s['med_max24']:+.0%} (+200% = puni bodovi)",
                "r1h": f"medijan nakon 1 h {(s.get('med_r1h') or 0):+.0%} (+50% = puni)",
                "vol_lift": f"medijan volumena sat poslije / sat prije {(s.get('med_lift') or 0):.1f}× (8× = puni)",
                "first": f"{s['first_rate']:.0%} poziva u kojima je prvi autor",
                "no_rug": f"{s['rug_rate']:.0%} poziva palo 90%+",
                "prepump": f"{s['prepump_rate']:.0%} poziva nakon što je cijena već udvostručena u 2 h",
                "deletes": (f"obrisao {s.get('deleted', 0)} objava, od toga {s.get('deleted_losers', 0)} gubitnika; "
                            "obrisani pozivi i dalje se broje, a brisanje gubitnika oduzima bodove")}
        names = {"hit": "Pogodak", "max24": "Rast 24 h", "r1h": "Rast 1 h", "vol_lift": "Volumen", "first": "Prvi",
                 "no_rug": "Bez ruga", "prepump": "Kasni pozivi", "deletes": "Briše gubitnike"}
        b.append("<p class=ms-hint>" + esc(
            (f"Doseg: {s['doseg'].get('followers', 0):,} pratitelja, prate ga {s['doseg'].get('followed_by', 0)} naših "
             f"dokazanih KOL-ova, pa početnih {s['doseg'].get('prior', cfg['prior_score'])} bodova. " if s.get("doseg") else "")
            + f"Izmjereni dio daje {s.get('raw', 0):.1f}; s {s.get('measured', 0)} poziva vjerujemo mu "
            f"{s.get('confidence', 0):.0%}, ostatak je početnih {s.get('prior', cfg['prior_score'])} bodova.") + "</p>"
                 + breakdown([(names[x], p.get(x, 0), abs(w[x]), expl[x]) for x in w if x in names], "Izmjereno"))
    inf = _influence(con, handle, cfg)
    b.append(inf.replace("<h2>Koliko ga tržište sluša</h2>", "<h2 id=trziste>Koliko ga tržište sluša</h2>", 1) if inf
             else "<h2 id=trziste>Koliko ga tržište sluša</h2><p class=ms-hint>Još nema izmjerenih objava.</p>")
    crew = ""
    try:   # 5.11.: transfers around the account (kol/traces.py) and the crew (kol/crew.py)
        from kol import crew as _cr, traces as _tr
        crew = _tr.html(con, handle) + _cr.html(con, handle)
    except Exception:  # noqa: BLE001
        pass
    b.append("<h2 id=ekipa>Zove zajedno s</h2>" + (crew or "<p class=ms-hint>Još nema podataka tko pojačava njegove "
                                                          "pozive.</p>"))
    if con.execute(f"SELECT 1 FROM calls WHERE handle = ? AND {TRADES} LIMIT 1", (handle,)).fetchone():
        b.append("<h2 id=novcanik>Njegov novčanik</h2><p class=ms-hint>Što je njegov novčanik kupio i prodao, najnovije "
                 "prvo. Link otvara transakciju na Solscanu.</p>"
                 + trades_table(con, "handle = ?", (handle,), 500, "ktrades", show_who=False))
    return f"Više o {kname(handle)}", _sub_shell(handle, f"Više o {kname(handle)}", "".join(b))


def _analize_head():
    return (f'<div class=kl><style>{KL_CSS}</style>{_back("/kol", "Influenceri")}<div class=kl-dh>'
            '<h1 class=ms-h1>Analize influencera</h1></div><p class=ms-sub>Sve što je bilo ispod ljestvice, sklopljeno: '
            'otvori dodirom.</p></div>')


def analize_page(qs):
    """/kol/analize: everything the old /kol page had below the leaderboard, unchanged and still folded (10.11., Jure,
    prijedlog 3.3: "10 sekcija za znatiželjne -> jedna podstranica"), plus the old 21-column table as "Sve brojke
    ljestvice". Heavy (together.build, pairs, correlations): run_ui builds it in a child and keeps a snapshot, like /kol."""
    con = store.ro()
    b = [_analize_head()]
    if con is None:
        return "Analize influencera", "".join(b) + "<p class=mut>Još nema podataka.</p>"
    try:
        cfg = _cfg()
        b = []
        st = con.execute("""SELECT (SELECT COUNT(*) FROM kols), (SELECT COUNT(*) FROM calls WHERE kind='call'),
            (SELECT COUNT(*) FROM calls WHERE kind='brag'), (SELECT COUNT(*) FROM calls WHERE p0 IS NOT NULL),
            (SELECT COUNT(*) FROM groups), (SELECT COUNT(*) FROM kol_wallets WHERE label='rotation_dev'),
            (SELECT COUNT(*) FROM flows), (SELECT MAX(measured_ts) FROM calls)""").fetchone()
        grid = ["<div class=grid>"]
        for v, l in [(st[0], "KOL-ova (autora)"), (st[1], "poziva"), (st[2], "hvalisanja (nakon skoka)"),
                     (st[3], "izmjereno cijenom"), (st[4], "grupnih poziva"), (st[5], "rotacijskih devova"),
                     (st[6], "Helius provjera tokova"), (ago(st[7])[0], "zadnje mjerenje")]:
            grid.append(f"<div class=stat><div class=v>{esc(v)}</div><div class=l>{l}</div></div>")
        grid.append("</div>")

        minf, minc = int(qs.get("minf") or 0), int(qs.get("minc") or 1)
        from ui import kolsummary, learnprogress
        from kol import shillers, together
        tog = together.build(con, shillers.handles())
        for name, fn in (("ukratko", lambda: kolsummary.top_html(con, cfg, tog)),):
            try:
                b.append(fn())
            except Exception as e:  # noqa: BLE001
                print(f"influenceri: {name}: {type(e).__name__}: {e}")
        head = "".join(b)
        b = []
        b.append("<h2 id=tablica>Sve brojke ljestvice</h2>")
        try:
            b.append(kolsummary.leaders_html(con, cfg))
        except Exception as e:  # noqa: BLE001
            print(f"influenceri: najbolji: {type(e).__name__}: {e}")
        b.append(f'<form class=flt>{filt("kols", "Traži KOL-a…")}<details class=more><summary>Više filtara</summary>'
                 f'Min. pratitelja <input name=minf value="{minf}" size=7> Min. poziva '
                 f'<input name=minc value="{minc}" size=3><button>Primijeni</button></details></form>')
        b.append(tdesc(f"Moć poziva 0-100 iz KOL-ovih prvih poziva na token: pogodak (+{cfg['hit_x']:.0%} u 24 h), "
                       "medijan rasta, volumen nakon poziva, je li prvi, rugovi; kasni pozivi (cijena već 2× prije poziva) "
                       f"oduzimaju. S malo poziva ocjena je bliže {cfg['prior_score']} (nesigurno). Dobar KOL za signal: "
                       f"{cfg['good_score']}+. Klik na ime otvara sve njegove pozive. <b>+10 % / +15 % prije stopa</b> = "
                       f"minutna provjera ({MINUTE_DAYS} dana, od minute objave, stop −20 %, barem {MINUTE_MIN_N} poziva; "
                       "stranica <a href=/ekipe>Ekipe</a>): to je mjera za pravi novac, a pogodak +50 % u 24 h je stara mjera. "
                       "<b>🔥 vruća lista</b> = račune s te liste X webhook i Telegram čitač prate u sekundama.")
                 + _star_tabs(con, minf, minc))

        for name, fn in (("zajedno", lambda: kolsummary.together_html(con, cfg, tog)),
                         ("shilleri", lambda: kolsummary.shill_html(con, cfg)),
                         ("tg povijest", kolsummary.tg_history_html)):
            try:
                b.append(fn())
            except Exception as e:  # noqa: BLE001
                print(f"influenceri: {name}: {type(e).__name__}: {e}")
        b.append(f"<h2 id=pozivi>Svi pozivi s objavom</h2>{filt('calls', 'Filtriraj pozive…')}" + tdesc(
            "Svaki post s CA tokena. Postoci su promjena cijene od trenutka posta; Volumen × = volumen sat nakon "
            "posta naspram sata prije. Prodaja u poziv: insajderi (kupili sat prije, prodali 30 min poslije) i SOL "
            "prodano/kupljeno u 30 min nakon posta.") + calls_table(con, limit=60))
        b.append("<h2 id=kupnje>Kupnje i prodaje</h2>" + tdesc(
            "Kupnje i prodaje novčanika KOL-ova koje pratimo (Helius javlja svaku). To nisu postovi: link otvara "
            "transakciju na Solscanu. KOL obično kupi prije nego što objavi, pa je ovo najraniji trag.")
                 + trades_table(con, limit=100, tid="ktrades"))
        main = "".join(b)
        b = []
        z = cfg.get("sessions", {})
        b.append("<h2 id=provjera>Provjera točnosti ocjene</h2>" + tdesc(
            "Alat svaki krug sam provjerava predviđa li njegova ocjena budućnost: ocjene iz starijih poziva uspoređuje "
            "s novim pozivima koje nije vidio, i s glupim pravilom \"najviše pratitelja\".") + _validate(con, cfg))
        b.append("<h2 id=sesije>Sesije trgovanja i vremenske zone</h2>" + tdesc(
            "Američki i azijski (kineski) market makeri pokreću memecoine u različito doba dana. Sesije u UTC: Azija "
            "00-08 (Kina 08-16), Europa 08-14, SAD 14-24 (New York 09-19); kod nas je UTC+1. Za svaku sesiju: kako su "
            "prošli prvi pozivi KOL-ova objavljeni u njoj, koliko su točni bili KOL grupni signali koji su u njoj "
            "krenuli i kako su prošli tokeni kojima je volumen najviše u toj sesiji (iz 5-min svijeća). Faktor "
            f"signala = pogodak sesije naspram prosjeka, prigušen s {z.get('shrink_n', 30)} poziva i ograničen na "
            f"×{z.get('factor_min', 0.7)}-×{z.get('factor_max', 1.3)}; njime se množi KOL signal. Uči se samo nakon "
            "svakog bodovanja.") + _sessions(con, cfg))
        w = cfg["watch"]
        b.append("<h2 id=uzivo>Prati uživo</h2>" + tdesc(
            f"Najboljih {w['size']} KOL-ova: moć poziva {cfg['good_score']}+, barem {w['min_calls']} izmjerenih poziva, "
            f"pogodak {w['min_hit']:.0%}+ i najviše {w['max_prepump']:.0%} kasnih poziva. Njihove nove postove dobivamo "
            "za nekoliko sekundi (xquik monitor, oko $0.11 po računu dnevno), pa hype sken unutar 2 min vidi token kao "
            "kandidata sa signalom kol_x. Redoslijed ide po donjoj granici raspona ocjene, pa dokazani KOL-ovi imaju prednost "
            "pred sretnicima s par poziva. Lista se sama mijenja nakon svakog bodovanja. <b>X webhook</b> = račun je u "
            "pravilima twitterapi.io webhooka (praćeni pravim novcem, vruća lista, ova lista, veliki računi): to je kanal "
            "koji objave stvarno dostavlja u sekundama, širi od xquik liste.") + _watch(con))
        b.append("<h2 id=grupe>Svi grupni pozivi</h2>" + tdesc(
            f"Dva ili više različitih autora zovu isti token unutar {cfg['group_secs'] // 60} min. Brojke su od prvog poziva "
            "u grupi. Dva dobra KOL-a bez prodaje devova = signal kol_group u hype ocjeni.") + _groups(con))
        b.append("<h2 id=parovi>Parovi koji zovu zajedno (test slučajnosti)</h2>" + tdesc(
            "Parovi računa koji su više puta zvali isti token u istom prozoru. Test slučajnosti uspoređuje to s "
            "koliko bi zajedničkih tokena dala sama slučajnost (koliko tokena svaki zove i koliko se tokena tada "
            "uopće zvalo). Dokazano = 3+ tokena, 3× češće od slučaja i manje od 1% šanse da je slučajno: vjerojatno "
            "ista ekipa ili plaćena kampanja.") + _pairs(con))
        b.append("<h2 id=kopiraju>Tko koga kopira</h2>" + tdesc(
            "Veliki računi (5× više pratitelja i barem 20.000) koji zovu token nakon što ga je manji račun već zvao, "
            "unutar 48 h, na 2+ tokena. Takav mali KOL je izvor: tko njega prati, ulazi prije gomile koju dovede "
            "veliki. Veliki prvi = koliko je puta bilo obrnuto; ako je to podjednako, nije kopiranje nego isti krug "
            "ljudi.") + _copies(con, cfg))
        b.append("<h2 id=devovi>Walleti koji prodaju u pozive</h2>" + tdesc(
            f"Kupili sat prije poziva i prodali do {cfg['flow_post_secs'] // 60} min nakon njega. Na "
            f"{cfg['rotation_min_tokens']}+ tokena = rotacijski dev: seli s tokena na token i prodaje u pozive. "
            "Rotacijski devovi ulaze u registar walleta s oznakom insider (nikad na copy listu).") + _wallets(con))
        b.append("<h2 id=korelacije>Što predviđa skok nakon poziva</h2>" + tdesc(
            "Korelacija svakog svojstva poziva s najvećim rastom u 24 h, preko svih izmjerenih prvih poziva. "
            "+0.3 i više = jasna veza, oko 0 = nema veze, minus = obrnuto. Mijenja se kako se skupljaju podaci.")
                 + _corr(con))
        b.append("<h2 id=brojke>Brojke</h2>" + "".join(grid))
        # 10.11. (Jure, prijedlog 3.3 i 5.1): "Prijedlog za danas" (prijedlog.box) lives only on Pregled; the long
        # intro still folds under "pročitaj više"; "za znatiželjne" keeps its id for the row on /kol (Analize)
        head = ("<details class=more><summary>Pročitaj više: kako mjerimo influencere</summary>" + head + "</details>"
                      if head else "")
        body = (head + learnprogress.fold(_leads(main, cfg))
                + "<p class=uc-more id=znatizeljne>Detalji za znatiželjne (otvori dodirom):</p>"
                + learnprogress.fold(_leads("".join(b), cfg)))
    finally:
        con.close()
    return "Analize influencera", _analize_head() + body


def _influence(con, handle, cfg):
    """'Koliko ga tržište sluša': what happened in the hour after his posts, from the measured first posts per token."""
    import statistics
    rows = _rows(con, """SELECT token, ts, r1h, max24, vol_before, vol_after, vol_lift, views, followers, likes, retweets
        FROM calls WHERE handle = ? AND kind IN ('call', 'bot') AND first_by_kol = 1 AND p0 IS NOT NULL AND bad IS NULL""",
                 (handle,))
    if not rows:
        return ""

    def med(xs):
        xs = [x for x in xs if x is not None]
        return statistics.median(xs) if xs else None
    lifts = [r["vol_lift"] for r in rows if r["vol_lift"] is not None]
    r1 = [r["r1h"] for r in rows if r["r1h"] is not None]
    extra = med((r["vol_after"] or 0) - (r["vol_before"] or 0) for r in rows if r["vol_after"] is not None)
    after = con.execute("""SELECT COUNT(DISTINCT c.tweet_id) FROM calls c WHERE c.handle = ? AND c.kind IN ('call', 'bot')
        AND c.first_by_kol = 1 AND EXISTS (SELECT 1 FROM calls o WHERE o.token = c.token AND o.handle != c.handle
        AND o.kind IN ('call', 'bot') AND o.ts > c.ts AND o.ts <= c.ts + ?)""", (handle, cfg["group_secs"])).fetchone()[0]
    total = con.execute("SELECT COUNT(DISTINCT tweet_id) FROM calls WHERE handle = ? AND kind IN ('call', 'bot') "
                        "AND first_by_kol = 1", (handle,)).fetchone()[0]
    views = med(r["views"] or None for r in rows)
    foll = med(r["followers"] or None for r in rows)
    eng = med(((r["likes"] or 0) + 2 * (r["retweets"] or 0)) / r["followers"] for r in rows if r["followers"])

    def p(n, d):
        return f"{n / d:.0%} ({n} od {d})" if d else "–"
    out = [
        ["Volumen se barem udvostručio", p(sum(1 for x in lifts if x >= 2), len(lifts)),
         "U koliko njegovih objava je trgovanje u satu poslije bilo barem 2× veće nego u satu prije. Ovo je "
         "najizravniji znak da ljudi reagiraju na objavu."],
        ["Medijan volumena poslije / prije", lift(med(lifts))[0] if lifts else "–",
         "Tipičan omjer trgovanja sat poslije i sat prije objave (50×+ = prije gotovo nije bilo trgovanja)."],
        ["Tipičan dodatni volumen u satu poslije", usd(extra)[0] if extra is not None else "–",
         "Koliko je dolara trgovanja više nego u satu prije (medijan po objavi)."],
        ["Cijena viša nakon 1 h", p(sum(1 for x in r1 if x > 0), len(r1)),
         "Udio objava nakon kojih je cijena sat kasnije bila viša."
         + (f" Medijan promjene: {med(r1) * 100:+.0f}%." if r1 else "")],
        ["Drugi računi zvali isti token poslije njega", p(after, total),
         f"U koliko njegovih objava je unutar {cfg['group_secs'] // 60} min isti token objavio još netko (KOL ili bot)."],
        ["Pratitelja", num(foll)[0] if foll else "–", "Broj pratitelja u trenutku objave."],
        ["Medijan pregleda objave", num(views)[0] if views else "–", "Koliko ljudi tipično vidi njegovu objavu (X)."],
        ["Engagement", "–" if eng is None else f"{eng * 100:.2g}%",
         "(Lajkovi + 2 × reposti) / pratitelji, medijan. Ispod 0,1% = slabo; 1%+ = jako vjerna publika."],
    ]
    return ("<h2>Koliko ga tržište sluša</h2>" + tdesc(
        f"Iz {len(rows)} izmjerenih objava (prva objava po tokenu; cijena i volumen iz 5-min svijeća GeckoTerminala "
        "ili snimki DexScreenera svakih 20 min). "
        "Ne znamo tko je točno kupio, pa reakciju pratitelja mjerimo onim što se vidi na grafu: volumen i cijena u "
        "satu nakon objave naspram sata prije.")
            + table(["Mjera", ("Vrijednost", "n"), ("Što znači", "wrap")],
                    [[esc(a), b, (f'<span class=mut>{esc(c)}</span>', "", "wrap")] for a, b, c in out]))


def _charts(con, handle):
    """How his calls did over time: one bar per call (24 h result) and the running result of $10 on every call."""
    from ui import charts
    syms = _syms(con)
    rows = _rows(con, f"SELECT ts, token, symbol, text, r24h, max24 FROM calls WHERE handle = ? AND {POSTS} "
                      "AND r24h IS NOT NULL ORDER BY ts", (handle,))
    if len(rows) < 2:
        return ""
    rows = rows[-300:]
    name = lambda c: "$" + str(syms.get(c["token"]) or c["symbol"] or _ticker(c["text"]) or c["token"][:6]).strip()
    run, pts = 0.0, []
    for c in rows:
        run += 10 * max(-1.0, c["r24h"])
        pts.append((c["ts"], run))
    ups = sum(1 for c in rows if c["r24h"] > 0)
    return ("<h2>Kako su mu prolazili pozivi kroz vrijeme</h2>" + tdesc(
        f"{len(rows)} izmjerenih poziva, {ups} u plusu nakon 24 h. Gornji graf: jedan stupac po pozivu, koliko je "
        "token bio gore (plavo) ili dolje (crveno) 24 sata nakon posta. Donji graf: da si na svaki njegov poziv uložio "
        "$10 i prodao nakon 24 h, ovoliko bi bio u plusu ili minusu (bez naknada). Pređi prstom ili mišem preko grafa "
        "za točan broj.")
            + charts.bars([(c["ts"], name(c), c["r24h"]) for c in rows], "Rezultat svakog poziva nakon 24 h",
                          "plavo = token je narastao, crveno = pao", fmt="pct")
            + charts.line([{"name": "Zbroj", "pts": [(rows[0]["ts"] - 1, 0.0)] + pts}],
                          "Da si uložio $10 u svaki njegov poziv", "prodano nakon 24 h, zbroj kroz vrijeme",
                          fmt="usd+", base=0, base_label="nula"))


def _audit_line(con, handle):
    """Latest weekly AI profile check (kol/discover.py audit) of this account, or ''."""
    try:
        r = con.execute("SELECT ts, verdict, why, bio, created FROM audits WHERE handle = ?", (handle,)).fetchone()
    except Exception:  # noqa: BLE001 - no audits table yet
        return ""
    if not r:
        return ""
    from kol.discover import VERDICTS
    ok = r[1] in ("kol", "trader")
    return (f'<p><span class="b {"good" if ok else "warn"}">AI provjera</span>{tip("", "ai-provjera-racuna")} '
            f'{esc(VERDICTS.get(r[1], r[1]))}{(": " + esc(r[2])) if r[2] else ""} '
            f'<span class=mut>({ago(r[0])[0]}; profil: {esc((r[3] or "")[:160])})</span></p>')


def kol_page(handle, qs):
    """/kol/<ime> (profil), /kol/<ime>/pozivi (sve objave) i /kol/<ime>/vise (više o njemu). 10.11. (Jure, prijedlog
    4.5): profil počinje presudom i četirima brojevima; stare brojke su jedan dodir dalje na podstranicama. Kanal samo
    iz povijesti Telegrama (tg:) i novčanik bez X računa (w:) imaju svoje stranice kao i prije."""
    handle, _, sub = handle.partition("/")
    if sub not in ("", "pozivi", "vise"):
        return None
    con = store.ro()
    if con is None:
        return None
    try:
        k = (_rows(con, "SELECT * FROM kols WHERE handle = ?", (handle,)) or [None])[0]
        if not k and handle.startswith("w:"):
            return _wallet_page(con, handle)
        if not k and handle.startswith("tg:"):
            hist = _tg_history_page(con, handle)
            if hist:
                return hist
        if not k:
            return "KOL", (f'<div class="ms-page kl"><style>{KL_CSS}</style>{_back("/kol", "Influenceri")}'
                           f'<div class=kl-dh><h1 class=ms-h1>{esc(kname(handle))}</h1></div>'
                           "<p class=ms-hint>Nema poziva od ovog računa.</p></div>")
        if sub == "pozivi":
            return calls_page(con, handle)
        if sub == "vise":
            return more_page(con, k, handle, _cfg())
        return profile(con, k, handle)
    finally:
        con.close()


def _tg_history_page(con, handle):
    """/kol/tg:<chan> for a channel that is only in kol/tg_history.json (Nicholas's Call Analyser + SpyDefi exports,
    95 channels): the 6-month summary instead of "Nema poziva" (4.11.: the Influenceri table linked here and the page
    was empty, because those exports carry per-channel totals, not the calls themselves). Live calls the bot has
    collected for the channel since are listed under it."""
    from ui.izvori import _tg_history
    r = _tg_history().get(handle[3:].lower())
    if not r:
        return None
    chan = handle[3:]
    n, n50 = r.get("calls") or 0, r.get("n50") or r.get("calls") or 0
    h2 = r["hit2_50"] if r.get("hit2_50") is not None else r.get("hit2")
    h5 = r["hit5_50"] if r.get("hit5_50") is not None else r.get("hit5")
    pct = lambda x: f"{x:.0%}" if x is not None else "–"
    cards = [("Poziva u 6 mj.", f"{n:,}".replace(",", "."), ""),
             (f"Barem 2× (zadnjih {n50})", pct(h2), "cijena bar 2× nakon poziva"),
             (f"Barem 5× (zadnjih {n50})", pct(h5), ""),
             ("Najviše", f"{r['max_x']:.0f}×" if r.get("max_x") else "–", ""),
             ("Mcap u pozivu (medijan)", usd(r["med_mcap"])[0] if r.get("med_mcap") else "–", ""),
             ("Zadnji poziv", ago(r["last"])[0] if r.get("last") else "–", "aktivan" if r.get("active") else "utihnuo")]
    b = [f'<p><a href="/kol#telegram">← KOL-ovi</a></p><h1>✈ {esc(chan)} <span class=mut>Telegram kanal</span></h1>'
         f'<p><a href="{profile_url(handle)}" target=_blank rel=noopener>Kanal na Telegramu ↗</a></p>',
         tdesc("Brojke su iz izvoza Call Analysera i SpyDefija za zadnjih 6 mjeseci (sažetak po kanalu, bez pojedinačnih "
               "poziva, pa nema ocjene ni grafova kao kod računa koje bot sam mjeri). Pozive koje bot od tada sam skupi "
               "vidiš dolje."),
         "<div class=grid>" + "".join(f"<div class=card><div class=l>{esc(l)}</div><div class=n>{v}</div>"
                                      + (f"<div class=mut>{esc(o)}</div>" if o else "") + "</div>" for l, v, o in cards)
         + "</div>"]
    live = con.execute("SELECT COUNT(*) FROM calls WHERE LOWER(handle) = LOWER(?) AND kind = 'call'", (handle,)).fetchone()[0]
    if live:
        b.append("<h2>Pozivi koje je bot sam skupio</h2>"
                 + calls_table(con, "LOWER(handle) = LOWER(?)", (handle,), 500, "kcalls", show_kol=False))
    else:
        b.append("<p class=mut>Bot još nije skupio nijedan poziv ovog kanala uživo (prati se kroz Telegram izvore čim ga "
                 "otkrivanje doda).</p>")
    return f"✈ {chan}", "".join(b)


def _wallet_page(con, handle):
    """/kol/w:<name>: a tracked KOL wallet without a known X account: its buys and sells."""
    w = _wallet_of(con).get(handle)
    link = (f'<p><code>{esc(w)}</code> · <a href="https://solscan.io/account/{quote(w)}" target=_blank '
            f'rel=noopener>Novčanik na Solscanu ↗</a> · <a href="https://gmgn.ai/sol/address/{quote(w)}" '
            f'target=_blank rel=noopener>GMGN ↗</a></p>') if w else ""
    return (f"Novčanik {handle[2:]}",
            f'<p><a href="/kol#kupnje">← KOL-ovi</a></p><h1>👛 {esc(handle[2:])} <span class=mut>KOL novčanik</span></h1>'
            + link + "<h2>Kupnje i prodaje</h2>" + tdesc(
                "Novčanik s KOL liste (KOLscan / Solana Tracker) za koji ne znamo X račun. Link u zadnjem stupcu "
                "otvara transakciju na Solscanu.") + trades_table(con, "handle = ?", (handle,), 500, "ktrades", show_who=False))


def token_section(mint):
    """'Tko ga je zvao na X-u' block for the token page; '' when kol.db has nothing on it."""
    con = store.ro()
    if con is None:
        return ""
    try:
        has_posts = con.execute(f"SELECT 1 FROM calls WHERE token = ? AND {POSTS} LIMIT 1", (mint,)).fetchone()
        has_trades = con.execute(f"SELECT 1 FROM calls WHERE token = ? AND {TRADES} LIMIT 1", (mint,)).fetchone()
        if not has_posts and not has_trades:
            return ""
        from kol import sessions
        sh = sessions.token_shares(con, mint)
        vol = ""
        if sh:
            vol = "<p>Volumen po sesijama: " + " · ".join(
                f"{sessions.NAMES[s]} <b>{sh[s]:.0%}</b>" for s, _, _ in sessions.SESSIONS) + "</p>"
        out = ""
        if has_posts:
            out += ("<h2 id=kol>Tko ga je zvao na X-u i Telegramu</h2>" + tdesc(
                "KOL postovi s ovim CA, najnoviji prvi, i što je cijena napravila nakon svakog. Link „post“ otvara "
                "sam post. Više na stranici KOL-ovi. Volumen po sesijama: udio trgovanja u satima Azije (00-08 UTC), "
                "Europe (08-14) i SAD-a (14-24).") + vol + calls_table(con, "token = ?", (mint,), 100, "tcalls"))
        if has_trades:
            out += ("<h2 id=kol-novcanici>Koji su ga KOL novčanici kupili ili prodali</h2>" + tdesc(
                "Kupnje i prodaje novčanika KOL-ova koje pratimo, najnovije prve. To nisu postovi: link otvara "
                "transakciju na Solscanu.") + ("" if has_posts else vol)
                    + trades_table(con, "token = ?", (mint,), 100, "ttrades"))
        return out
    except Exception:
        return ""
    finally:
        con.close()
