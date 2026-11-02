"""The "KOL-ovi" page: influencers on X, their calls with links, what the price and volume did after each call,
group calls, KOL pairs that call together, wallets that sell into calls, and which call features correlate
with a pump. /kol/<handle> lists one KOL's calls. All read-only from kol.db (written by run_kol.py)."""
import json
import time
import os
from urllib.parse import quote

from kol import score as kscore, store
from ui.html import ago, badge, breakdown, esc, filt, num, signed, table, tdesc, tip, tlink, ts, usd, wlink

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
    return b + (" " + badge("ticker") if match == "ticker" else "")


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
        name = klink(k["handle"]) + (
            f' <span class="b warn" title="{esc(s.get("trial_why", ""))}">na probi</span>{TRIAL_TIP}'
            if s.get("trial") else "") + (
            f' <span class="b bad" title="{esc(s.get("rug_why", ""))}">puno rugova</span>{RUG_TIP}'
            if s.get("rugger") else "") + (' <span class="b good" title="Njegov novčanik je kupio tokene koje je zvao">'
                                           'kupio</span>' if s.get("bought") else "")
        out.append([name, num(k["followers"]), (f"<b>{k['score']:.0f}</b>{rng}", k["score"], "n"),
                    m(lift(k["power_rel"])), num(s.get("measured")), m(share(s.get("hit_rate"))),
                    m(pct(s.get("med_max24"))), m(pct(s.get("med_r1h"))), m(lift(s.get("med_lift"))),
                    m(share(s.get("rug_rate"))), m(share(s.get("prepump_rate"))), m(share(s.get("first_rate"))),
                    num(s.get("brags")), num(s.get("med_views")),
                    ("–", -1, "n") if eng is None else (f"{eng * 100:.2g}%" if eng < 0.1 else f"{eng * 100:.0f}%", eng, "n"),
                    _zone(s), ago(last.get(k["handle"]))])
    html = table(["X račun", ("Pratitelji", "n"), ("Moć poziva", "n"), ("Moć/pratitelj", "n"), ("Poziva", "n"),
                  ("Pogodak", "n"), ("Medijan max 24 h", "n"), ("Medijan 1 h", "n"), ("Medijan volumen ×", "n"),
                  ("Rugovi", "n"), ("Kasni pozivi", "n"), ("Prvi", "n"), ("Hvalisanja", "n"), ("Medijan pregleda", "n"), ("Engagement", "n"),
                  "Zona", "Zadnji poziv"],
                 out, tid=tid, empty="Još nema KOL-ova s izmjerenim pozivom u ovoj skupini (mjerenje kreće 1 h nakon "
                                     "poziva).")
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
    import sqlite3
    from kol import live
    try:  # tables appear with the first run_kol.py round after the deploy
        mon = dict(con.execute("SELECT handle, last_run FROM monitor"))
        rows = con.execute("SELECT handle, score, since, reason FROM watch ORDER BY score DESC").fetchall()
    except sqlite3.OperationalError:
        mon, rows = {}, []
    on = live.hook_url() is not None
    out = []
    for h, sc, since, why in rows:
        st = (badge("uživo", "good") if h in mon else badge("čeka pokretanje", "warn")) if on else badge("isključeno", "bad")
        out.append([klink(h), (f"<b>{sc:.0f}</b>", sc, "n"), (esc(why), "", "wrap"), ago(since), st, ago(mon.get(h))])
    return table(["X račun", ("Moć poziva", "n"), ("Razlog", "wrap"), "Na listi od", "Praćenje", "Zadnja sinkronizacija"],
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
                  "Dev prodaje"], out, tid="groups", empty="Još nema grupnih poziva.")


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
                    (", ".join(tlink(t, syms.get(t)) for t in toks[:8]), "", "wrap")])
    return table(["KOL A", "KOL B", ("Puta zajedno", "n"), ("Slučajno očekivano", "n"), ("Puta više od slučaja", "n"),
                  "Test slučajnosti", ("Zajednički tokeni", "wrap")], out, tid="kpairs",
                 empty="Još nema KOL-ova koji su zajedno zvali isti token.")


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
                    (sure, n - rev, ""), (", ".join(tlink(t, syms.get(t)) for t in toks[:8]), "", "wrap")])
    return table(["Mali KOL", ("Pratitelji malog", "n"), ("Veliki KOL", ""), ("Pratitelji velikog", "n"),
                  ("Mali prvi", "n"), ("Veliki prvi", "n"), ("Medijan kašnjenja", "n"), "Ocjena veze",
                  ("Tokeni", "wrap")], out, tid="kcopy",
                 empty="Još nema velikih računa koji su na 2+ tokena zvali nakon manjeg.")


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


def page(qs):
    con = store.ro()
    b = ["<h1>Influenceri</h1>"]
    if con is None:
        return "Influenceri", "".join(b) + "<p class=mut>Još nema podataka.</p>"
    try:
        cfg = _cfg()
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
        b.append("<h2 id=ljestvica>Najbolji</h2>")
        b.append(f'<form class=flt>{filt("kols", "Traži KOL-a…")}<details class=more><summary>Više filtara</summary>'
                 f'Min. pratitelja <input name=minf value="{minf}" size=7> Min. poziva '
                 f'<input name=minc value="{minc}" size=3><button>Primijeni</button></details></form>')
        b.append(tdesc(f"Moć poziva 0-100 iz KOL-ovih prvih poziva na token: pogodak (+{cfg['hit_x']:.0%} u 24 h), "
                       "medijan rasta, volumen nakon poziva, je li prvi, rugovi; kasni pozivi (cijena već 2× prije poziva) "
                       f"oduzimaju. S malo poziva ocjena je bliže {cfg['prior_score']} (nesigurno). Dobar KOL za signal: "
                       f"{cfg['good_score']}+. Klik na ime otvara sve njegove pozive.") + _star_tabs(con, minf, minc))

        b.append(f"<h2 id=pozivi>Upravo zvali</h2>{filt('calls', 'Filtriraj pozive…')}" + tdesc(
            "Svaki post s CA tokena. Postoci su promjena cijene od trenutka posta; Volumen × = volumen sat nakon "
            "posta naspram sata prije. Prodaja u poziv: insajderi (kupili sat prije, prodali 30 min poslije) i SOL "
            "prodano/kupljeno u 30 min nakon posta.") + calls_table(con))
        b.append("<h2 id=kupnje>Kupnje i prodaje</h2>" + tdesc(
            "Kupnje i prodaje novčanika KOL-ova koje pratimo (Helius javlja svaku). To nisu postovi: link otvara "
            "transakciju na Solscanu. KOL obično kupi prije nego što objavi, pa je ovo najraniji trag.")
                 + trades_table(con, limit=200, tid="ktrades"))
        b.append("<h2 id=analiza>Analiza</h2><details><summary>Točnost, sesije, grupe, parovi, devovi i brojke</summary>")
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
            "pred sretnicima s par poziva. Lista se sama mijenja nakon svakog bodovanja.") + _watch(con))
        b.append("<h2 id=grupe>Grupni pozivi</h2>" + tdesc(
            f"Dva ili više različitih autora zovu isti token unutar {cfg['group_secs'] // 60} min. Brojke su od prvog poziva "
            "u grupi. Dva dobra KOL-a bez prodaje devova = signal kol_group u hype ocjeni.") + _groups(con))
        b.append("<h2 id=parovi>KOL-ovi koji zovu zajedno</h2>" + tdesc(
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
        b.append("<h3>Brojke</h3>" + "".join(grid) + "</details>")
    finally:
        con.close()
    return "Influenceri", "".join(b)


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
    con = store.ro()
    if con is None:
        return None
    try:
        k = (_rows(con, "SELECT * FROM kols WHERE handle = ?", (handle,)) or [None])[0]
        if not k and handle.startswith("w:"):
            return _wallet_page(con, handle)
        if not k:
            return "KOL", f"<h1>@{esc(handle)}</h1><p>Nema poziva od ovog računa.</p>"
        s = json.loads(k["stats"] or "{}")
        cfg = _cfg()
        b = [f'<p><a href="/kol">← KOL-ovi</a></p><h1>{esc("✈ " + handle[3:] if handle.startswith("tg:") else "@" + handle)} <span class=mut>{esc(k["name"] or "")}</span></h1>'
             + (f'<p><a href="{profile_url(handle)}" target=_blank rel=noopener>'
                f'{"Kanal na Telegramu" if handle.startswith("tg:") else "Profil na X-u"} ↗</a></p>' if profile_url(handle) else "")
             + '<div class=grid>']
        sc = k["score"] if k["score"] is not None else s.get("bot_score")
        rel = k["power_rel"] if k["power_rel"] is not None else s.get("bot_rel")
        for v, l in [(f"{sc:.0f}" if sc is not None else "–", "moć objava (bot)" if k.get("bot") else "moć poziva"),
                     (f"{rel:.2f}×" if rel is not None else "–", "moć po pratitelju"),
                     (f"{k['followers'] or 0:,}", "pratitelja"), (s.get("measured", 0), "izmjerenih poziva"),
                     (f"{s['hit_rate']:.0%}" if "hit_rate" in s else "–", "pogodak"), (s.get("brags", 0), "hvalisanja")]:
            b.append(f"<div class=stat><div class=v>{esc(v)}</div><div class=l>{l}</div></div>")
        b.append("</div>")
        if k.get("bot"):
            b.append('<p><span class="b warn">nije KOL</span> <b>Bot, spam, promo ili dev račun.</b> Razlog: '
                     f'{esc(k.get("bot_why") or "")}. Njegove objave se ne broje kao pozivi: ne ulaze u '
                     'grupe KOL-ova, ljestvicu, praćenje uživo, copy trading, konvergenciju, demo ulaze ni statistiku '
                     'X objava. Ne otvaraj linkove iz njegovih objava. Brojke niže samo pokazuju što su njegove objave '
                     'napravile s cijenom.</p>')
        if s.get("trial") and not k.get("bot"):
            b.append(f'<p><span class="b warn">na probi</span>{tip("", "na-probi")} Još ga ne pratimo uživo, ne '
                     f'ulazi u copy trading ni kao „dobar KOL“ u grupni signal: {esc(s.get("trial_why") or "")}.</p>')
        if s.get("rugger") and not k.get("bot"):
            b.append(f'<p><span class="b bad">puno rugova</span>{RUG_TIP} {esc(s.get("rug_why") or "")}. Ostaje na '
                     'listi, ali njegove objave čitamo rjeđe (svaka 3 dana). Pazi kod kupnje njegovih poziva.</p>')
        if s.get("bought"):
            b.append(f'<p><span class="b good">kupio</span> Njegov novčanik je kupio {s["bought"]} od tokena koje je '
                     'zvao: stavlja novac iza objave.</p>')
        b.append(_audit_line(con, handle))
        if s.get("parts"):
            w, p = cfg["weights"], s["parts"]
            expl = {"hit": f"{s['hit_rate']:.0%} poziva s barem +{cfg['hit_x']:.0%} u 24 h",
                    "max24": f"medijan najvećeg rasta u 24 h {s['med_max24']:+.0%} (+200% = puni bodovi)",
                    "r1h": f"medijan nakon 1 h {(s.get('med_r1h') or 0):+.0%} (+50% = puni)",
                    "vol_lift": f"medijan volumena sat poslije / sat prije {(s.get('med_lift') or 0):.1f}× (8× = puni)",
                    "first": f"{s['first_rate']:.0%} poziva u kojima je prvi autor",
                    "no_rug": f"{s['rug_rate']:.0%} poziva palo 90%+",
                    "prepump": f"{s['prepump_rate']:.0%} poziva nakon što je cijena već udvostručena u 2 h"}
            names = {"hit": "Pogodak", "max24": "Rast 24 h", "r1h": "Rast 1 h", "vol_lift": "Volumen", "first": "Prvi",
                     "no_rug": "Bez ruga", "prepump": "Kasni pozivi"}
            b.append("<h2>Kako je dobio ocjenu</h2>" + tdesc(
                f"Izmjereni dio daje {s.get('raw', 0):.1f}; s {s.get('measured', 0)} poziva vjerujemo mu "
                f"{s.get('confidence', 0):.0%}, ostatak je početnih {s.get('prior', cfg['prior_score'])} bodova.")
                     + breakdown([(names[x], p[x], abs(w[x]), expl[x]) for x in w], "Izmjereno"))
        b.append(_charts(con, handle))
        b.append(_influence(con, handle, cfg))
        b.append("<h2>Svi pozivi</h2>" + tdesc("Svaki njegov post s CA tokena, najnoviji prvi. Postoci su od trenutka posta. Cijena i volumen: iz "
                 "5-min svijeća (GeckoTerminal) kad su dostupne, inače iz snimki DexScreenera svakih 20 min (tada je "
                 "Max 24 h približan). Stupci 1 h / 6 h / 24 h se pune kad to vrijeme prođe.")
                 + calls_table(con, "handle = ?", (handle,), 500, "kcalls", show_kol=False))
        if con.execute(f"SELECT 1 FROM calls WHERE handle = ? AND {TRADES} LIMIT 1", (handle,)).fetchone():
            b.append("<h2>Kupnje i prodaje s njegovog novčanika</h2>" + tdesc(
                "Što je njegov novčanik kupio i prodao, najnovije prvo. Link otvara transakciju na Solscanu.")
                     + trades_table(con, "handle = ?", (handle,), 500, "ktrades", show_who=False))
    finally:
        con.close()
    return f"@{handle}", "".join(b)


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
