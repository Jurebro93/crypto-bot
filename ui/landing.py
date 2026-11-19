"""Public front page for visitors who are not logged in ("/" and /dobrodosli), plus access requests.

- page_html(): sales page in plain Croatian: invite only, live numbers from the databases, real screenshots of the app
  (ui/static/landing/*.jpg, player names replaced), "Zatraži pristup" form and the login button.
- Live numbers are counted in a background thread (start(), every STATS_EVERY_S) with cheap queries only
  (MAX(rowid) for the big tables), so a visitor never waits for a database and the bot's writers are never slowed.
- Access requests: league.db table access_requests (the dashboard process is league.db's only writer). /zahtjevi lists
  them for players who may invite (ui/register.can_invite); "Pozovi" makes a single-use invite link
  (league/members.single) for that person, ready to copy or send on WhatsApp / e-mail.
- Site log (10.11.): the block "MemeSonar je live N dana" with the last days of what the nightly 02:00 refresh found
  new (ui/sitelog.py), each item an internal link. The rows are read in the same background count as the numbers,
  never per request. start() also starts the watch that drops in-memory copies of public data once the night's
  refresh has happened (refreshed()).
"""
import os
import re
import sqlite3
import threading
import time
from urllib.parse import quote

from ui.html import ago, esc, logo
from ui import favicon as _fav  # noqa: E402

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATIC = os.path.join(HERE, "ui", "static", "landing")
STATS_EVERY_S = int(os.environ.get("LANDING_STATS_EVERY_S", "1800"))
MAX_PENDING = 500            # a bot filling the form cannot fill the disk
PER_IP_HOUR = 5
# site log: days read from public.db per count / days with news shown. 10.11.: 3, not 4: one day is ~210 px on a phone
# and four filled a whole screen between the numbers and the features
LOG_READ, LOG_SHOW = 8, 3
LOG_LINKS_MAX = 2            # blog posts named per line; the rest is "i još N", a link to the blog

SCHEMA = """
CREATE TABLE IF NOT EXISTS access_requests (
    id INTEGER PRIMARY KEY AUTOINCREMENT, ts INTEGER, name TEXT, contact TEXT, experience TEXT, interest TEXT,
    source TEXT, ip TEXT, status TEXT DEFAULT 'novi', handled_by TEXT, handled_ts INTEGER, invite TEXT);
"""

_STATS = {"ts": 0, "v": {}}
_LOCK = threading.Lock()
_IPS = {}   # ip -> [ts, ...] of recent requests (in memory: enough against a form-filling bot)


# ---------- live numbers ------------------------------------------------------------------------------------------

def _db(name):
    return os.path.join(HERE, name)


def _one(path, sql, args=()):
    """First column of the first row, or None (missing file/table, locked, anything)."""
    if not os.path.exists(path) or not os.path.getsize(path):
        return None
    try:
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5)
    except sqlite3.Error:
        return None
    try:
        r = con.execute(sql, args).fetchone()
        return r[0] if r else None
    except sqlite3.Error:
        return None
    finally:
        con.close()


def compute():
    """Every number on the page, from the live databases. Missing ones are simply left out."""
    v = {}
    hype, wal, kol, tg, dugo, paper = (_db(n) for n in ("hype.db", "wallets.db", "kol.db", "tg.db", "dugo.db", "paper.db"))
    v["tokens"] = (_one(hype, "SELECT COUNT(*) FROM token_tier") or 0) + (_one(hype, "SELECT COUNT(*) FROM rug_archive") or 0)
    v["rugs"] = _one(hype, "SELECT COUNT(*) FROM rug_archive")
    v["scans"] = _one(hype, "SELECT MAX(rowid) FROM hype_signals")
    v["wallets"] = _one(wal, "SELECT COUNT(*) FROM wallets")
    v["wallet_trades"] = _one(wal, "SELECT MAX(rowid) FROM wallet_trades")
    v["kols"] = _one(kol, "SELECT COUNT(*) FROM kols WHERE handle NOT LIKE 'tg:%' AND handle NOT LIKE 'w:%'")  # X only
    v["calls"] = _one(kol, "SELECT COUNT(*) FROM calls WHERE kind='call'")
    v["kol_wallets"] = _one(kol, "SELECT COUNT(*) FROM kol_wallets")
    v["snaps"] = _one(kol, "SELECT MAX(rowid) FROM snaps")
    v["channels"] = _one(tg, "SELECT COUNT(*) FROM channels WHERE status IN ('active','quiet','slow')")
    v["dugo"] = _one(dugo, "SELECT COUNT(*) FROM tokens")
    v["demo_trades"] = _one(paper, "SELECT COUNT(*) FROM trades")
    # what happens after an influencer call: share of measured calls whose token at least doubled in 24 h
    if os.path.exists(kol) and os.path.getsize(kol):
        try:
            con = sqlite3.connect(f"file:{kol}?mode=ro", uri=True, timeout=5)
            try:
                r = con.execute("SELECT COUNT(*), SUM(max24 >= 1.0), SUM(max24 >= 0.5) FROM calls "
                                "WHERE kind='call' AND max24 IS NOT NULL").fetchone()
                if r and r[0]:
                    v["measured"], v["call_2x"], v["call_50"] = r[0], (r[1] or 0) / r[0], (r[2] or 0) / r[0]
            finally:
                con.close()
        except sqlite3.Error:
            pass
    try:
        from ourtoken import advisor
        lift = advisor.cocall_lift()
        if lift:
            v["group_rate"], v["solo_rate"], v["group_n"], v["solo_n"] = (lift["group_rate"], lift["solo_rate"],
                                                                           lift["group_n"], lift["solo_n"])
    except Exception:  # noqa: BLE001
        pass
    try:
        from league import store
        v["players"] = len(store.users())
    except Exception:  # noqa: BLE001
        pass
    try:   # 20.11. (vlasnik 19.11.: novi fokus): the wallet search's public aggregates, read with the other numbers
        v["nov"] = wallet_numbers()
    except Exception as e:  # noqa: BLE001
        print(f"naslovnica: brojke novčanika nisu pročitane: {type(e).__name__}: {e}", flush=True)
    try:   # 10.11.: the site log rows (a few rows by primary key) are kept with the numbers, so a visit reads no database
        from ui import sitelog
        v["log"] = sitelog.recent(LOG_READ)
    except Exception as e:  # noqa: BLE001
        print(f"naslovnica: dnevnik weba nije pročitan: {type(e).__name__}: {e}", flush=True)
    return {k: x for k, x in v.items() if x}


def wallet_numbers(now=None):
    """Public-safe aggregates of the wallet search (no address, no name of a wallet, no cost): {"rises" (token rises
    reviewed), "found" (wallets or groups that bought before and sold into 3+ rises), "confirmed", "examples" (up to 3
    of the best confirmed: members, tokens, tokens worth 15 M $+), "meas" (the per-entry measurement of those groups:
    n, mean, lo, hi, token-days, verdict word), "tokens" (tracked midcap pages: slug, symbol, mcap)}."""
    from ui import novjasno as J
    from ui import novpodaci as NP
    out = {"rises": None, "found": None, "confirmed": None, "examples": [], "meas": None, "tokens": []}
    con = NP.ins_con()
    if con is not None:
        try:
            _s, pp = NP.summary(con)
            if pp:
                out["rises"] = int(pp.get("covered15") or 0) + int(pp.get("covered2") or 0)
            n, c, _k = J._counts(con)
            if pp or n:
                out["found"], out["confirmed"] = n, c
            for g in NP.confirmed_groups(con, 3):
                out["examples"].append({"k": len(g["members"]) or 1, "n": int(g.get("n_tokens") or 0),
                                        "b": int(g.get("n_pumps15") or 0)})
        finally:
            con.close()
    st, _first = J.mjera_stats(now=now)
    if st is not None and st.get("signals"):
        from league import mjera
        out["meas"] = {"n": int(st.get("measured") or 0), "mean": st.get("mean01"), "lo": st.get("lo"),
                       "hi": st.get("hi"), "td": int(st.get("token_days") or 0), "verdict": mjera.verdict(st)}
    try:
        from tokenstranice import store as TS
        tc = TS.ro()
        if tc is not None:
            try:
                out["tokens"] = [{"slug": sl, "symbol": sy, "mcap": mc} for sl, sy, mc in tc.execute(
                    "SELECT slug, symbol, mcap FROM pages WHERE active=1 AND enough=1 AND slug IS NOT NULL AND "
                    "COALESCE(mcap, 0) >= 2e6 ORDER BY (mcap >= 15e6 AND mcap <= 200e6) DESC, vol24 DESC LIMIT 8")]
            finally:
                tc.close()
    except Exception:  # noqa: BLE001 - the section says the list is filling up
        pass
    return out


def _refresh():
    try:
        val = compute()
    except Exception:  # noqa: BLE001
        val = None
    with _LOCK:
        if val:
            _STATS["v"] = val
        _STATS["ts"] = time.time()
        _STATS["busy"] = False


def stats():
    """Latest numbers (possibly empty right after a restart); starts a recount in the background when stale."""
    with _LOCK:
        stale = time.time() - _STATS["ts"] > STATS_EVERY_S and not _STATS.get("busy")
        if stale:
            _STATS["busy"] = True
        v, ts = dict(_STATS["v"]), _STATS["ts"]
    if stale:
        threading.Thread(target=_refresh, daemon=True, name="landing-stats").start()
    return v, ts


def refreshed():
    """The night's refresh has happened (ui/sitelog marker moved; run_web.py daily in the scheduler's process): every
    in-memory copy of public data is dropped, the numbers and the site log are counted again and the main public
    tables are built once, so the first visitor of the morning waits for nothing. Runs in the watch thread."""
    from ui import public
    public.drop_caches()
    with _LOCK:
        _STATS["busy"] = True
    _refresh()
    public.warm()


def start():
    """Count once soon after boot (the boot itself is busy) and keep the numbers fresh."""
    def loop():
        time.sleep(int(os.environ.get("LANDING_STATS_DELAY_S", "45")))
        while True:
            with _LOCK:
                _STATS["busy"] = True
            _refresh()
            time.sleep(STATS_EVERY_S)
    threading.Thread(target=loop, daemon=True, name="landing-stats-loop").start()
    try:   # 10.11.: one cheap look at the refresh marker a minute, in its own thread (ui/sitelog.watch)
        from ui import sitelog
        sitelog.watch(refreshed)
    except Exception as e:  # noqa: BLE001 - without the watch the pages still refresh on their own cache times
        print(f"naslovnica: praćenje noćnog osvježavanja nije pokrenuto: {type(e).__name__}: {e}", flush=True)


# ---------- formatting ---------------------------------------------------------------------------------------------

def _n(x):
    """12,345 -> '12.345' (Croatian grouping); big numbers rounded: 1,234,567 -> '1,2 mil.'."""
    if x is None:
        return "–"
    x = float(x)
    if x >= 1_000_000:
        return f"{x / 1_000_000:.1f}".replace(".", ",") + " mil."
    return f"{x:,.0f}".replace(",", ".")


def _pct(x):
    return f"{x * 100:.0f}%"


# ---------- page ---------------------------------------------------------------------------------------------------

SHOTS = {   # file -> alt text (HR files; the English page uses the same names with an "en-" prefix)
    # 20.11. (vlasnik 19.11.: "promijeniti fokus"): screens of what the tool does now, made from the local fixture
    # (scripts/seed_novcanici.py + audit/2026-11-10/seed_app.py), never from production data
    "novcanici.jpg": "Novčanici koje vrijedi pratiti: svaka skupina jednom rečenicom",
    "mjerenje.jpg": "Mjerenje praćenja novčanika: svaka kupnja u postocima, nakon troška",
    "token-midcap.jpg": "Stranica praćenog tokena: cijena, market cap, likvidnost i graf",
    "tokeni.jpg": "Tokeni",
    "mob-novcanici.jpg": "Novčanici koje vrijedi pratiti na mobitelu",
    "mob-mjerenje.jpg": "Mjerenje praćenja novčanika na mobitelu",
}
SHOTS_EN = {"en-novcanici.jpg": "Wallets worth following: every group in one sentence",
            "en-mjerenje.jpg": "Wallet following measured: every buy in percent, after costs",
            "en-token-midcap.jpg": "A tracked token's page: price, market cap, liquidity and chart",
            "en-tokeni.jpg": "Tokens", "en-mob-novcanici.jpg": "Wallets worth following on a phone",
            "en-mob-mjerenje.jpg": "Wallet following measured, on a phone"}
SHOTS.update(SHOTS_EN)

CSS = """
:root{--bg:#fff;--soft:#f6f7fb;--fg:#0b1220;--mut:#5b6474;--line:#e8ebf2;--acc:#4f46e5;--acc2:#0fb5a0;--good:#16a34a}
*{box-sizing:border-box}html{scroll-behavior:smooth}
body{margin:0;background:var(--bg);color:var(--fg);font:17px/1.6 Inter,system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;
-webkit-font-smoothing:antialiased}
a{color:inherit;text-decoration:none}img{max-width:100%;display:block}
.w{max-width:1080px;margin:0 auto;padding:0 20px}
nav.top{position:sticky;top:0;z-index:100;background:rgba(255,255,255,.85);backdrop-filter:blur(12px);border-bottom:1px solid transparent}
nav.top.s{border-bottom-color:var(--line)}
nav.top .w{display:flex;align-items:center;gap:18px;height:64px}
.brand{display:flex;align-items:center;gap:9px;font-weight:750;font-size:18px;letter-spacing:-.02em}.sp{flex:1}
.lnk{color:var(--mut);font-size:15px;font-weight:500}.lnk:hover{color:var(--fg)}
.btn{display:inline-flex;align-items:center;justify-content:center;border-radius:999px;padding:14px 26px;font-weight:650;font-size:16px;
border:1px solid transparent;cursor:pointer;font-family:inherit;transition:transform .15s,box-shadow .15s,background .15s}
.btn:active{transform:scale(.98)}
.btn.p{background:var(--fg);color:#fff}.btn.p:hover{background:#1f2937;box-shadow:0 10px 30px -10px rgba(11,18,32,.5)}
.btn.g{background:#fff;border-color:var(--line);color:var(--fg)}.btn.g:hover{border-color:#cfd5e1}
.btn.sm{padding:9px 18px;font-size:14px}
.hero{text-align:center;padding:84px 0 24px}
.pill{display:inline-flex;align-items:center;gap:8px;background:var(--soft);border:1px solid var(--line);border-radius:999px;padding:6px 14px;
font-size:14px;color:var(--mut);font-weight:500}
.dot{width:7px;height:7px;border-radius:50%;background:var(--good)}
h1{font-size:clamp(38px,7vw,68px);line-height:1.04;letter-spacing:-.04em;margin:22px auto 18px;font-weight:800;max-width:820px}
.g{background:linear-gradient(90deg,var(--acc),var(--acc2));-webkit-background-clip:text;background-clip:text;color:transparent}
.sub{font-size:clamp(17px,2.2vw,20px);color:var(--mut);max-width:600px;margin:0 auto 32px}
.ctas{display:flex;gap:10px;justify-content:center;flex-wrap:wrap}
.small{color:var(--mut);font-size:14px;margin-top:16px}
.phones{display:flex;justify-content:center;align-items:flex-end;gap:22px;margin:64px auto 0;padding:0 0 10px}
.ph{width:250px;flex:none;border-radius:34px;background:#0b1220;padding:8px;box-shadow:0 40px 80px -30px rgba(11,18,32,.35)}
.ph img{border-radius:27px;width:100%;aspect-ratio:390/844;object-fit:cover;object-position:top;background:#eef2f7;color:#64748b;font-size:13px}
.ph.side{width:215px;opacity:.95}@media(min-width:761px){.ph.main{order:2}.ph.side+.ph.side{order:3}}
@media(max-width:760px){.phones{justify-content:flex-start;overflow-x:auto;scroll-snap-type:x mandatory;padding:0 20px 20px;margin:48px -20px 0;
gap:14px;scrollbar-width:none}.phones::-webkit-scrollbar{display:none}.ph,.ph.side{width:72vw;scroll-snap-align:center}}
.hero{position:relative;overflow:hidden}.hero>.w{position:relative;z-index:1}
.hbg{position:absolute;inset:0;z-index:0;pointer-events:none;background-size:cover;background-position:top center;opacity:.2;
filter:blur(2px) saturate(1.1);transform:scale(1.04);-webkit-mask-image:linear-gradient(#000 0,#000 45%,transparent 92%);
mask-image:linear-gradient(#000 0,#000 45%,transparent 92%)}
.hbg:after{content:"";position:absolute;inset:0;background:radial-gradient(ellipse at 50% 38%,rgba(255,255,255,.96) 0,rgba(255,255,255,.78) 42%,rgba(255,255,255,.35) 100%)}
.dcta{margin:34px auto 0;max-width:980px}.dcta>p{margin:0 0 12px;color:var(--mut);font-size:15px;font-weight:600}
.dcta>div{display:grid;grid-template-columns:repeat(4,1fr);gap:12px}
.dcta a{display:block;text-align:left;background:rgba(255,255,255,.92);border:1px solid var(--line);border-radius:18px;padding:16px 16px 14px;
transition:transform .15s,box-shadow .15s,border-color .15s;backdrop-filter:blur(6px)}
.dcta a:hover{transform:translateY(-3px);border-color:#c7cbf5;box-shadow:0 18px 40px -22px rgba(79,70,229,.55)}
.dcta a b{display:block;font-size:22px;letter-spacing:-.02em;font-weight:780;line-height:1.15;font-variant-numeric:tabular-nums}
.dcta a span{display:block;color:var(--mut);font-size:13px;margin:2px 0 10px;min-height:34px;line-height:1.3}
.dcta a em{font-style:normal;font-weight:680;font-size:14.5px;color:var(--acc)}
@media(max-width:860px){.dcta>div{grid-template-columns:1fr 1fr}}@media(max-width:420px){.dcta a b{font-size:19px}.dcta a{padding:13px}}
.show{max-width:940px;margin:56px auto 0;text-align:left}
.show .fr{border-radius:16px;background:#0b1220;padding:10px 10px 12px;box-shadow:0 50px 100px -40px rgba(11,18,32,.45)}
.show .bar{display:flex;align-items:center;gap:6px;padding:2px 6px 10px}.show .bar i{width:10px;height:10px;border-radius:50%;background:#334155}
.show .bar span{margin-left:10px;color:#94a3b8;font-size:12.5px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.show .vp{position:relative;aspect-ratio:16/9;border-radius:9px;overflow:hidden;background:#eef2f7}
.show .vp img{position:absolute;inset:0;width:100%;height:100%;object-fit:cover;object-position:50% 0;opacity:0;transition:opacity .7s}
.show .vp img.on{opacity:1;z-index:1;animation:pan var(--dur,6s) ease-in-out forwards}.show .vp img.was{opacity:1}
@keyframes pan{0%,12%{object-position:50% 0}88%,100%{object-position:50% 100%}}
.show .pg{height:3px;background:#1e293b;border-radius:2px;margin:10px 4px 0;overflow:hidden}
.show .pg i{display:block;height:100%;width:0;background:linear-gradient(90deg,#818cf8,#2dd4bf)}
.show .pg i.run{animation:pgr var(--dur,6s) linear forwards}@keyframes pgr{to{width:100%}}
.show.paused .vp img.on,.show.paused .pg i{animation-play-state:paused}
.show .tabs{display:flex;gap:8px;justify-content:center;flex-wrap:wrap;margin:16px 0 0}
.show .tabs button{font:inherit;font-size:14px;font-weight:600;border:1px solid var(--line);background:#fff;color:var(--mut);
border-radius:999px;padding:7px 14px;cursor:pointer}.show .tabs button.on{background:var(--fg);color:#fff;border-color:var(--fg)}
.show .cap{text-align:center;color:var(--mut);font-size:14px;margin:10px 0 0;min-height:22px}
@media(max-width:600px){.show .vp{aspect-ratio:4/3}.show .tabs{flex-wrap:nowrap;overflow-x:auto;justify-content:flex-start;scrollbar-width:none;padding-bottom:4px}
.show .tabs button{flex:none}}
@media(prefers-reduced-motion:reduce){.show .vp img.on,.show .pg i.run{animation:none}}
section{padding:88px 0}.soft{background:var(--soft)}
.eyebrow{color:var(--acc);font-weight:650;font-size:14px;margin-bottom:10px}
h2{font-size:clamp(28px,4.5vw,44px);letter-spacing:-.035em;line-height:1.1;margin:0 0 14px;font-weight:780}
.lead{color:var(--mut);font-size:18px;max-width:600px;margin:0 0 40px}
.center{text-align:center}.center .lead{margin-left:auto;margin-right:auto}
.nums{display:grid;grid-template-columns:repeat(var(--n,4),1fr);gap:0;border-top:1px solid var(--line);border-bottom:1px solid var(--line)}
.num{padding:30px 18px;text-align:center}.num+.num{border-left:1px solid var(--line)}
.num b{display:block;font-size:clamp(28px,4vw,40px);letter-spacing:-.03em;font-weight:780;font-variant-numeric:tabular-nums}
.num span{color:var(--mut);font-size:14px}
@media(max-width:760px){.num{padding:22px 4px}.num b{font-size:24px}.num span{font-size:12px;line-height:1.3;display:block}}
.live{display:flex;justify-content:center;align-items:center;gap:8px;color:var(--mut);font-size:13px;margin-top:14px}
.pulse{position:relative;width:8px;height:8px;border-radius:50%;background:#22c55e;flex:none;display:inline-block}
.pulse:after{content:"";position:absolute;inset:0;border-radius:50%;background:#22c55e;animation:pl 2s cubic-bezier(.2,.6,.4,1) infinite}
@keyframes pl{0%{transform:scale(1);opacity:.55}80%,100%{transform:scale(3);opacity:0}}
@media(prefers-reduced-motion:reduce){.pulse:after{animation:none}}
.hl .lv{display:flex;flex-wrap:wrap;align-items:center;gap:10px;font-size:13px;color:#aab3c5;margin-top:18px}
.lvhead{display:flex;justify-content:center;margin-bottom:16px}
.lvb{display:inline-flex;align-items:center;gap:8px;background:#ecfdf5;color:#15803d;border:1px solid #bbf7d0;border-radius:999px;
padding:5px 12px 5px 11px;font-size:12px;font-weight:750;letter-spacing:.08em;text-transform:uppercase;line-height:1}
.lvb.dk{background:rgba(34,197,94,.14);color:#86efac;border-color:rgba(34,197,94,.35)}
.feats{display:grid;grid-template-columns:repeat(4,1fr);gap:18px}@media(max-width:1000px){.feats{grid-template-columns:1fr 1fr}}
@media(max-width:600px){.feats{grid-template-columns:1fr;gap:10px}.f{display:grid;grid-template-columns:46px 1fr;gap:4px 16px;padding:18px;border-radius:18px}.f .i{grid-row:span 2}.f h3{margin:2px 0 0;font-size:17px}.f p{font-size:15px}}
.tr{display:grid;grid-template-columns:280px 1fr;gap:64px;align-items:center;max-width:860px;margin:0 auto 72px}
.tr:nth-child(even){grid-template-columns:1fr 280px}.tr:nth-child(even) .tph{order:2}.tr:last-child{margin-bottom:0}
.tph{width:280px}.tt h3{font-size:clamp(26px,3.6vw,36px);letter-spacing:-.03em;line-height:1.12;margin:0 0 12px}
.tt p{color:var(--mut);margin:0 0 18px;font-size:17px}.tt ul,.free ul{list-style:none;padding:0;margin:0;display:grid;gap:10px}
.tt li,.free li{position:relative;padding-left:30px;font-size:15.5px}.tt li:before,.free li:before{content:"✓";position:absolute;left:0;top:1px;width:20px;
height:20px;border-radius:50%;background:#ecfdf5;color:var(--good);font-size:12px;font-weight:800;display:flex;align-items:center;justify-content:center}
@media(max-width:760px){.tr,.tr:nth-child(even){grid-template-columns:1fr;gap:26px;margin-bottom:64px}.tr:nth-child(even) .tph{order:0}
.tph{width:min(270px,74vw);margin:0 auto}.tt{text-align:left}}
.free{display:grid;grid-template-columns:1fr auto;gap:48px;align-items:center;background:#fff;border:1px solid var(--line);border-radius:28px;
padding:48px;max-width:900px;margin:0 auto;box-shadow:0 30px 60px -45px rgba(11,18,32,.3)}
.free p{color:var(--mut);margin:0 0 20px;font-size:17px}.free ul{margin-bottom:28px}
.fbig{text-align:center;padding:0 12px}.fbig b{display:block;font-size:clamp(72px,12vw,128px);font-weight:820;letter-spacing:-.05em;line-height:1;
background:linear-gradient(90deg,var(--acc),var(--acc2));-webkit-background-clip:text;background-clip:text;color:transparent}
.fbig span{color:var(--mut);font-size:14px}
@media(max-width:760px){.free{grid-template-columns:1fr;padding:30px 22px;gap:12px;border-radius:24px}.fbig{order:-1;text-align:left;padding:0}
.free .btn{width:100%}}
.f{background:#fff;border:1px solid var(--line);border-radius:22px;padding:26px}
.f .i{width:46px;height:46px;border-radius:14px;background:var(--soft);display:flex;align-items:center;justify-content:center;font-size:22px}
.f h3{font-size:19px;letter-spacing:-.02em;margin:18px 0 6px}.f p{margin:0;color:var(--mut);font-size:15.5px}
.hl{display:grid;grid-template-columns:auto 1fr;gap:40px;align-items:center;background:var(--fg);color:#fff;border-radius:28px;padding:48px}
.hl .big{font-size:clamp(64px,11vw,120px);font-weight:820;letter-spacing:-.05em;line-height:1}
.hl .big .g{background:linear-gradient(90deg,#a5b4fc,#5eead4);-webkit-background-clip:text;background-clip:text}
.hl h3{font-size:clamp(22px,3vw,30px);letter-spacing:-.025em;margin:0 0 10px;line-height:1.2}.hl p{margin:0;color:#aab3c5}
.bars{margin-top:22px;display:grid;gap:10px;max-width:420px}.bar{display:grid;grid-template-columns:1fr 54px;gap:12px;align-items:center;font-size:14px;color:#cbd2df}
.bar i{display:block;height:8px;border-radius:8px;background:#26314a;overflow:hidden}.bar i em{display:block;height:100%;border-radius:8px}
.bar b{color:#fff;text-align:right}
@media(max-width:760px){.hl{grid-template-columns:1fr;gap:18px;padding:32px 24px;border-radius:24px}}
.gal{display:flex;gap:18px;overflow-x:auto;scroll-snap-type:x mandatory;padding:4px 20px 20px;margin:0 -20px;scrollbar-width:thin}
.gal figure{margin:0;flex:none;width:min(820px,86vw);scroll-snap-align:center}
.gal img{border-radius:18px;border:1px solid var(--line);box-shadow:0 20px 50px -25px rgba(11,18,32,.25);cursor:zoom-in;background:#fff}
.gal figcaption{color:var(--mut);font-size:14px;margin-top:10px;font-weight:500}
.req{max-width:520px;margin:0 auto}
form.rq{background:#fff;border:1px solid var(--line);border-radius:24px;padding:28px;text-align:left;box-shadow:0 30px 60px -40px rgba(11,18,32,.25)}
form.rq label{display:block;font-weight:600;font-size:14px;margin:0 0 16px}
form.rq input,form.rq select{width:100%;margin-top:6px;background:var(--soft);color:var(--fg);border:1px solid var(--line);border-radius:14px;
padding:14px 16px;font:inherit;font-size:16px;-webkit-appearance:none;appearance:none}
form.rq input:focus,form.rq select:focus{outline:none;border-color:var(--acc);background:#fff;box-shadow:0 0 0 4px rgba(79,70,229,.12)}
form.rq .btn{width:100%;margin-top:6px}form.rq .hp{position:absolute;left:-9999px;width:1px;height:1px;overflow:hidden}
.fine{color:var(--mut);font-size:13px;margin:14px 0 0;text-align:center}
.ok{background:#ecfdf5;border:1px solid #a7f3d0;color:#065f46;border-radius:16px;padding:16px;margin-bottom:16px}
.err{background:#fef2f2;border:1px solid #fecaca;color:#991b1b;border-radius:16px;padding:14px;margin-bottom:16px}
.faq{max-width:680px;margin:0 auto}details{border-bottom:1px solid var(--line);padding:20px 0}
summary{cursor:pointer;font-weight:620;list-style:none;display:flex;justify-content:space-between;gap:16px}
summary::-webkit-details-marker{display:none}summary:after{content:"+";color:var(--mut);font-size:22px;line-height:1}
details[open] summary:after{content:"–"}details p{color:var(--mut);margin:10px 0 0}
footer{padding:36px 0 48px;color:var(--mut);font-size:13px;text-align:center;border-top:1px solid var(--line)}
dialog#lb{border:0;padding:0;background:transparent;max-width:96vw;max-height:94vh}dialog#lb::backdrop{background:rgba(11,18,32,.8)}
dialog#lb img{max-width:96vw;max-height:94vh;border-radius:12px}
.lg{max-width:720px;margin:0 auto}.lg h2{font-size:clamp(26px,3.6vw,36px)}.lg .lead{font-size:16.5px;margin-bottom:26px}
.lg .lead a,.lgt a{color:var(--acc);font-weight:550}
.lgl{list-style:none;margin:0;padding:0;border-top:1px solid var(--line);text-align:left}
.lgr{display:grid;grid-template-columns:64px 1fr;gap:16px;padding:16px 2px;border-bottom:1px solid var(--line)}
.lgr time{color:var(--mut);font-size:14px;font-weight:600;font-variant-numeric:tabular-nums;padding-top:1px;white-space:nowrap}
.lgn{margin:0;display:flex;flex-wrap:wrap;gap:4px 20px;font-size:15px;line-height:1.5}.lgn a{color:var(--fg);white-space:nowrap}
.lgn a:hover,.lgt a:hover{text-decoration:underline;text-underline-offset:3px}
.lgn a b{color:var(--good);font-weight:700;font-variant-numeric:tabular-nums;margin-left:3px}
.lgt{margin:6px 0 0;font-size:14.5px;line-height:1.55;color:var(--mut)}.lgt:first-child{margin-top:0}
@media(max-width:600px){.lgr{grid-template-columns:1fr;gap:6px;padding:14px 0}.lgr time{padding-top:0;font-size:13px}}
.lgt a.lgm{color:var(--mut);font-weight:500;text-decoration:underline;text-underline-offset:3px;white-space:nowrap}
.apst{margin-top:14px}.apst+.hero{padding-top:56px}@media(max-width:760px){.apst+.hero{padding-top:36px}}
.steps{list-style:none;padding:0;margin:8px auto 0;display:grid;grid-template-columns:repeat(3,1fr);gap:18px;max-width:1000px}
.steps li{background:#fff;border:1px solid var(--line);border-radius:22px;padding:24px}
.steps li b{display:inline-flex;width:34px;height:34px;border-radius:50%;background:var(--fg);color:#fff;align-items:center;
justify-content:center;font-size:16px}.steps h3{font-size:19px;letter-spacing:-.02em;margin:14px 0 6px;line-height:1.25}
.steps p{margin:0;color:var(--mut);font-size:15.5px}
@media(max-width:860px){.steps{grid-template-columns:1fr;gap:12px}}
.wx{list-style:none;padding:0;margin:0 0 6px;display:grid;gap:10px;max-width:760px}
.wx li{background:#fff;border:1px solid var(--line);border-radius:16px;padding:14px 18px;font-size:16px;line-height:1.45}
.tk{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;max-width:900px}
.tk a{display:block;border:1px solid var(--line);border-radius:14px;padding:12px 14px;background:#fff}
.tk a:hover{border-color:#c7cbf5}.tk b{display:block;font-size:17px}.tk span{color:var(--mut);font-size:13.5px}
@media(max-width:760px){.tk{grid-template-columns:1fr 1fr}}
.lk{color:var(--acc);font-weight:650}
.apb{max-width:760px;margin:0 auto;border:1px solid var(--line);border-radius:20px;padding:22px 24px;background:#fff}
.apb>div[role]{margin:0}
.mcta{position:fixed;left:14px;right:14px;bottom:14px;z-index:30;display:none;transition:opacity .2s,transform .2s}
.mcta.h{opacity:0;transform:translateY(20px);pointer-events:none}
@media(max-width:760px){.gsec{display:none}body{font-size:16px}.hero{padding:56px 0 8px}section{padding:64px 0}.hm{display:none}.mcta{display:flex}
.mcta .btn{flex:1;box-shadow:0 12px 30px -10px rgba(11,18,32,.5)}footer{padding-bottom:100px}nav.top .btn.p{display:none}}
"""

JS = """
const nav=document.querySelector('nav.top'),cta=document.querySelector('.mcta'),form=document.getElementById('pristup');
const tick=()=>{nav.classList.toggle('s',scrollY>8);const r=form.getBoundingClientRect();
 cta.classList.toggle('h',scrollY<300||(r.top<innerHeight&&r.bottom>0))};addEventListener('scroll',tick,{passive:true});tick();
(()=>{const s=document.querySelector('.show');if(!s)return;const im=[...s.querySelectorAll('.vp img')],tb=[...s.querySelectorAll('.tabs button')],
 pg=s.querySelector('.pg i'),cap=s.querySelector('.cap'),url=s.querySelector('.bar span'),D=6000;let i=0,t=0,left=D,st=0;s.style.setProperty('--dur',D+'ms');
 // 15.11. (vlasnik: "slike se ne učitavaju"): every screen is loaded once the page has loaded (idle time, not with
 // Save-Data), the first one with high priority; a tapped tab loads its screen at once and the old one stays under it
 // until the new is ready (never an empty frame); a screen that failed (a deploy, a dropped connection) is asked again
 const ld=(e,hi)=>{if(hi)e.fetchPriority='high';if(e.dataset.src){e.src=e.dataset.src;delete e.dataset.src}},
  ok=e=>e.complete&&e.naturalWidth>0,idle=f=>'requestIdleCallback'in window?requestIdleCallback(f,{timeout:2500}):setTimeout(f,1200);
 im.forEach(e=>{let n=0;e.addEventListener('error',()=>{if(n++<3)setTimeout(()=>{e.src=e.getAttribute('src').split('?')[0]+'?r='+n},1500*n)})});
 const go=n=>{const p=i;i=(n+im.length)%im.length;const e=im[i];ld(e,1);const w=p!==i&&!ok(e);
  im.forEach((x,k)=>{x.classList.toggle('on',k===i);x.classList.toggle('was',w&&k===p)});
  if(w)e.addEventListener('load',()=>im.forEach(x=>x.classList.remove('was')),{once:true});
  ld(im[(i+1)%im.length]);
  tb.forEach((e,k)=>{e.classList.toggle('on',k===i);e.setAttribute('aria-selected',k===i)});cap.textContent=tb[i].dataset.cap;url.textContent=tb[i].dataset.url;
  pg.classList.remove('run');void pg.offsetWidth;pg.classList.add('run');left=D;arm()};
 const arm=()=>{clearTimeout(t);st=Date.now();if(!s.classList.contains('paused'))t=setTimeout(()=>go(i+1),left)};
 const pause=p=>{if(p===s.classList.contains('paused'))return;if(p){left=Math.max(400,left-(Date.now()-st));clearTimeout(t)}s.classList.toggle('paused',p);if(!p)arm()};
 tb.forEach((e,k)=>{e.onclick=()=>go(k);e.addEventListener('pointerdown',()=>ld(im[k],1),{passive:true})});s.querySelector('.vp').onclick=()=>go(i+1);
 const pre=()=>{if(!(navigator.connection||{}).saveData)im.forEach(e=>ld(e))};
 if(document.readyState==='complete')idle(pre);else addEventListener('load',()=>idle(pre),{once:true});
 s.addEventListener('mouseenter',()=>pause(true));s.addEventListener('mouseleave',()=>pause(false));
 document.addEventListener('visibilitychange',()=>pause(document.hidden));
 if(matchMedia('(prefers-reduced-motion:reduce)').matches){s.classList.add('paused');go(0);clearTimeout(t)}else go(0)})();
"""


def _img(name, eager=False):
    return (f'<img src="/static/landing/{name}" alt="{esc(SHOTS.get(name, ""))}" '
            f'{"" if eager else "loading=lazy "}decoding=async>')


T = {
    "hr": dict(
        title="MemeSonar · novčanici koji kupuju prije skoka Solana tokena",
        desc="Tražimo novčanike koji kupuju prije skoka Solana tokena i mjerimo isplati li se pratiti ih, nakon "
             "stvarnog troška. Besplatno, pristup na zahtjev.",
        pill="Za sada besplatno · pristup na zahtjev", h1a="Novčanici koji kupuju", h1b="prije skoka.",
        sub="Tražimo novčanike koji kupuju prije nego što token skoči i mjerimo isplati li se pratiti ih.",
        req="Zatraži pristup", login="Prijava", app="Otvori aplikaciju", ex_eye="Istraži besplatno",
        ex_h="Javni podaci MemeSonara",
        how_eye="Kako radi", how_h="Tri koraka, svaki dan.",
        steps=[("Pratimo tokene od 2 do 200 milijuna dolara",
                "Gledamo Solana tokene vrijedne od 2 do 200 milijuna dolara, najviše one od 15 milijuna naviše, i "
                "bilježimo svaki nagli rast."),
               ("Tražimo tko je kupio prije rasta",
                "Za svaki rast gledamo tko je kupio prije njega i prodao dok je rastao. Zadržavamo samo novčanike koji "
                "su to napravili opet i opet; botove, market makere i novčanike koji se pojave samo jednom izbacujemo."),
               ("Mjerimo i objavljujemo",
                "Svaku novu kupnju tih novčanika mjerimo u postocima, nakon stvarnog troška, i objavljujemo što "
                "nađemo, i kad je rezultat negativan.")],
        live_eye="Uživo", live_h="Što smo dosad našli.", live_wait="Prvi rezultati se upravo računaju.",
        live_upd="Brojke se osvježavaju iz baze svakih 30 minuta.",
        n_rises="rasta tokena pregledano", n_found="novčanika ili skupina pronađeno",
        n_conf="potvrđeno na novijim podacima", n_meas="isplati li se pratiti ih",
        meas_early="prerano za reći", meas_none="—",
        meas_n="izmjereno {n} kupnji",
        wal_eye="Novčanici koje vrijedi pratiti", wal_h="Ovako izgleda jedan nalaz.",
        wal_p="Primjeri iz popisa, bez adresa. Popis s adresama je u aplikaciji.",
        wal_wait="Prvi nalazi stižu nakon noćne obrade.",
        wal_one="Kupio je prije rasta {n} tokena i prodao dok su rasli",
        wal_grp="Skupina od {k} povezanih novčanika kupila je prije rasta {n} tokena i prodala dok su rasli",
        wal_big=" ({b} od njih vrijedilo je 15 milijuna dolara ili više)",
        wal_conf="; potvrđeno na novijim podacima.", wal_unc="; još se potvrđuje na novijim podacima.",
        disclaimer="To je statistika iz javnih podataka s lanca, a ne financijski savjet.",
        tok_eye="Tokeni", tok_h="Tokeni koje pratimo.",
        tok_p="Svaki praćeni token od 2 milijuna dolara naviše ima svoju javnu stranicu: cijena, likvidnost, vlasnici "
              "i tko ga je zvao.", tok_all="Svi meme coini", tok_wait="Popis tokena se puni.",
        mak_eye="Influenceri", mak_h="Makro influenceri.",
        mak_p="Računi koji pišu o smjeru cijelog tržišta, svaka izjava izmjerena po tome što je tržište napravilo "
              "poslije.", mak_btn="Otvori makro influencere",
        ap_eye="Autopilot", ap_h="Autopilot", ap_on="Rezultati Autopilota su javni.", ap_btn="Pogledaj Autopilot",
        rq_eye="Pristup na zahtjev", rq_h="Zatraži pristup.",
        rq_p="Besplatno je. Pristup otvaramo postupno: ostavi ime i e-mail i javimo ti se s osobnim linkom.",
        free_eye="Cijena", free_h="Za sada besplatno.", free_big="0 €", free_sub="za sada",
        free_p="Alat je u ranoj fazi i za sada ga ne naplaćujemo. Pristup dobiješ na zahtjev: ostavi ime i e-mail i "
               "pošaljemo ti osobni link za registraciju.",
        free_li=["Bez kartice i plaćanja", "Nikad ne tražimo seed frazu ni privatni ključ", "Radi na mobitelu i računalu"],
        f_name="Ime", f_ph_name="Marko", f_contact="E-mail (javljamo ti se njime)", f_ph_contact="marko@mail.com",
        f_exp="Koliko tradaš?", f_opts=("Odaberi", "Tek počinjem", "Povremeno", "Aktivno", "Svaki dan"),
        f_fine="Bez novca, kartice i seed fraze. Kontakt koristimo samo za pozivnicu.",
        f_ok="<b>Zahtjev je poslan.</b> Javit ćemo ti se s osobnim linkom za registraciju.",
        faq_h="Pitanja", faq=[
            ("Što znači „kupuje prije skoka”?", "Da je novčanik ili skupina novčanika više puta kupila token prije "
             "naglog rasta i prodala dok je rastao. To je statistika iz javnih podataka s lanca, a ne optužba i ne "
             "tvrdnja o tome tko su."),
            ("Je li ovo financijski savjet?", "Nije. Alat mjeri i pokazuje podatke. Memecoini su vrlo rizični i odluka je "
             "uvijek tvoja."),
            ("Koliko košta?", "Za sada ništa. Alat je besplatan dok je u ranoj fazi."),
            ("Kako dobijem pristup?", "Ispuni kratki obrazac na ovoj stranici (ime i e-mail). Kad ti otvorimo mjesto, "
             "dobiješ osobni link za registraciju."),
            ("Radi li na mobitelu?", "Da. Otvoriš link, prijaviš se jednom i alat te pamti 60 dana.")],
        log_eye="Dnevnik", log_h="MemeSonar je live {n}.", log_h0="MemeSonar je live od danas.",
        log_p="Svake noći u 02:00 osvježimo <a href=/hr/solana-meme-coini>meme coine</a>, "
              "<a href=/hr/influenceri>influencere</a> i brojke na <a href=/hr/blog>blogu</a>. Ovdje piše što je novo.",
        log_wait="Prvi zapis stiže nakon sljedećeg noćnog osvježavanja.",
        log_k=dict(kols="Influenceri", calls="Izmjereni pozivi", channels="Telegram kanali", wallets="Novčanici",
                   trades="Tradeovi novčanika", coins="Meme coini", tokens="Provjereni tokeni"),
        log_blogs="Blogovi s novim podacima", log_posts="Novi članci", log_more="i još {n}",
        foot="Nije financijski savjet. Kripto nosi visok rizik."),
    "en": dict(
        title="MemeSonar · wallets that buy before Solana tokens jump",
        desc="We look for the wallets that buy before a Solana token jumps and measure whether following them pays, "
             "after real costs. Free for now, access on request.",
        pill="Free for now · access on request", h1a="Wallets that buy", h1b="before the jump.",
        sub="We look for the wallets that buy before a token jumps, and measure whether following them pays.",
        req="Request access", login="Log in", app="Open the app", ex_eye="Explore for free", ex_h="Public MemeSonar data",
        how_eye="How it works", how_h="Three steps, every day.",
        steps=[("We watch tokens worth 2 to 200 million dollars",
                "We watch Solana tokens worth 2 to 200 million dollars, most closely those from 15 million up, and note "
                "every sharp rise."),
               ("We find who bought before the rise",
                "For each rise we look at who bought before it and sold into it. We keep only wallets that did so again "
                "and again; bots, market makers and one-off wallets are left out."),
               ("We measure and publish",
                "Every new buy of those wallets is measured in percent after real costs, and we publish what we find, "
                "also when it is negative.")],
        live_eye="Live", live_h="What we have found so far.", live_wait="The first results are being computed.",
        live_upd="These numbers refresh from the database every 30 minutes.",
        n_rises="token rises reviewed", n_found="wallets or groups found",
        n_conf="confirmed on newer data", n_meas="does following them pay",
        meas_early="too early to say", meas_none="—",
        meas_n="{n} buys measured",
        wal_eye="Wallets worth following", wal_h="What one finding looks like.",
        wal_p="Examples from the list, without addresses. The list with addresses is in the app.",
        wal_wait="The first findings arrive after the nightly run.",
        wal_one="Bought before the rise of {n} tokens and sold into it",
        wal_grp="A group of {k} linked wallets bought before the rise of {n} tokens and sold into it",
        wal_big=" ({b} of them worth 15 million dollars or more)",
        wal_conf="; confirmed on newer data.", wal_unc="; still being confirmed on newer data.",
        disclaimer="These are statistics from public on-chain data, not financial advice.",
        tok_eye="Tokens", tok_h="The tokens we track.",
        tok_p="Every tracked token from 2 million dollars up has its own public page: price, liquidity, holders and "
              "who called it.", tok_all="All meme coins", tok_wait="The token list is filling up.",
        mak_eye="Influencers", mak_h="Macro influencers.",
        mak_p="Accounts that write about the direction of the whole market, each statement measured against what the "
              "market did afterwards.", mak_btn="Open macro influencers",
        ap_eye="Autopilot", ap_h="Autopilot", ap_on="Autopilot's results are public.", ap_btn="See Autopilot",
        rq_eye="Access on request", rq_h="Request access.",
        rq_p="It's free. We open access gradually: leave your name and e-mail and we'll send you a personal link.",
        free_eye="Price", free_h="Free for now.", free_big="$0", free_sub="for now",
        free_p="The tool is at an early stage and we don't charge for it for now. Access is on request: leave your name "
               "and e-mail and we'll send you a personal sign-up link.",
        free_li=["No card, no payment", "We never ask for a seed phrase or private key", "Works on phone and desktop"],
        f_name="Name", f_ph_name="Alex", f_contact="E-mail (we reply there)", f_ph_contact="alex@mail.com",
        f_exp="How often do you trade?", f_opts=("Choose", "Just starting", "Now and then", "Actively", "Every day"),
        f_fine="No money, no card, no seed phrase. We use your contact only to send the invite.",
        f_ok="<b>Request sent.</b> We'll get back to you with a personal sign-up link.",
        faq_h="Questions", faq=[
            ("What does “buys before a jump” mean?", "That a wallet or a group of wallets bought a token before a sharp "
             "rise and sold while it was rising, again and again. It is a statistic from public on-chain data, not an "
             "accusation and not a statement about who they are."),
            ("Is this financial advice?", "No. The tool measures and shows data. Memecoins are very risky and the "
             "decision is always yours."),
            ("How much does it cost?", "Nothing for now. The tool is free while it is at an early stage."),
            ("How do I get access?", "Fill in the short form on this page (name and e-mail). When we open a spot for "
             "you, you get a personal sign-up link."),
            ("Does it work on my phone?", "Yes. Open the link, log in once and the app remembers you for 60 days.")],
        log_eye="Site log", log_h="MemeSonar has been live for {n}.", log_h0="MemeSonar went live today.",
        log_p="Every night at 02:00 (Zagreb time) we refresh the <a href=/solana-meme-coins>meme coins</a>, the "
              "<a href=/influencers>influencers</a> and the numbers on the <a href=/blog>blog</a>. This is what was new.",
        log_wait="The first entry appears after the next nightly refresh.",
        log_k=dict(kols="Influencers", calls="Calls measured", channels="Telegram channels", wallets="Wallets",
                   trades="Wallet trades", coins="Meme coins", tokens="Tokens checked"),
        log_blogs="Blog posts with new data", log_posts="New posts", log_more="and {n} more",
        foot="Not financial advice. Crypto carries a high risk."),
}


# ---------- site log: "MemeSonar je live N dana" -------------------------------------------------------------------

# what each counted thing links to: a public page (English, Croatian) or a blog post by its English slug
LOG_LINKS = {
    "kols": ("/influencers", "/hr/influenceri"), "calls": "how-to-check-a-kol-track-record",
    "channels": ("/telegram-channels", "/hr/telegram-kanali"), "wallets": "what-is-wallet-tracking",
    "trades": "what-is-copy-trading", "coins": ("/solana-meme-coins", "/hr/solana-meme-coini"),
    "tokens": ("/rug-check", "/hr/provjera"),
}
_MON_EN = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def _days_words(n, lang):
    """9 -> '9 dana', 21 -> '21 dan' (Croatian: 1, 21, 31... take the singular, 11 does not); English '1 day'."""
    if lang == "en":
        return f"{n} day" if n == 1 else f"{n} days"
    return f"{n} dan" if n % 10 == 1 and n % 100 != 11 else f"{n} dana"


def _log_date(day, lang):
    """'2026-11-10' -> '10. 11.' / '10 Nov'."""
    try:
        _y, m, d = (int(x) for x in day.split("-"))
        return f"{d} {_MON_EN[m - 1]}" if lang == "en" else f"{d}. {m}."
    except (ValueError, IndexError):
        return esc(day)


def _short_title(h1):
    """A post's headline cut to what fits a line of the log: 'What is wallet tracking? How to ...' -> 'What is wallet
    tracking?', 'Best ... in 2026: ranked by ...' -> 'Best ... in 2026', a closing '(and why ...)' dropped."""
    title = re.sub(r"\s*\([^()]*\)\s*$", "", h1).strip()
    if "?" in title and title.index("?") >= 14:
        title = title[:title.index("?") + 1]
    elif ":" in title:
        head, tail = (x.strip() for x in title.split(":", 1))
        # "KOL in crypto: how to check ..." keeps the how-to, a longer head ("Best ... in 2026") is the title
        title = head if len(head) >= 15 or not tail else tail[0].upper() + tail[1:]
    if len(title) > 56 and title.find(" (") >= 14:   # "Što je praćenje novčanika (wallet tracking) i zašto ..."
        title = title[:title.find(" (")]
    if len(title) > 72:
        title = title[:70].rsplit(" ", 1)[0] + "…"
    return title


def _post_link(en_slug, lang):
    """(href, short title) of a blog post in that language, or None when the post is not there."""
    from ui import blog
    v = blog.get_en(en_slug, lang)
    return (f"{blog.L[lang]['base']}/{v['slug']}", _short_title(v["h1"])) if v else None


def _log_href(key, lang):
    to = LOG_LINKS.get(key)
    if isinstance(to, tuple):
        return to[0 if lang == "en" else 1]
    link = _post_link(to, lang) if to else None
    return link[0] if link else None


def _log_posts(label, slugs, lang, t, turn=0):
    """'Novi članci: <a>…</a>, <a>…</a> i još 9' ('' when no slug resolves to a post; the tail links to the blog).
    turn: which posts are named when there are more than LOG_LINKS_MAX (the same blocks change most nights; the names
    should not repeat)."""
    links = [x for x in (_post_link(sl, lang) for sl in slugs) if x]
    if not links:
        return ""
    if len(links) > LOG_LINKS_MAX:
        k = turn % len(links)
        links = links[k:] + links[:k]
    out = ", ".join(f"<a href={h}>{esc(tt)}</a>" for h, tt in links[:LOG_LINKS_MAX])
    if len(links) > LOG_LINKS_MAX:
        from ui import blog
        out += f" <a class=lgm href={blog.L[lang]['base']}>{t['log_more'].format(n=len(links) - LOG_LINKS_MAX)}</a>"
    return f"<p class=lgt>{label}: {out}</p>"


def _log_row(e, lang, t, num):
    """One day of the log as <li>, '' when that day has nothing to show."""
    nums = ""
    for k, lab in t["log_k"].items():
        n, href = (e.get("added") or {}).get(k), _log_href(k, lang)
        if n and n > 0 and href:
            nums += f"<a href={href}>{lab}<b>+{num(n)}</b></a>"
    try:
        turn = int(e["day"].replace("-", "")) * LOG_LINKS_MAX   # a different set of names every day
    except (ValueError, AttributeError):
        turn = 0
    body = ((f"<p class=lgn>{nums}</p>" if nums else "")
            + _log_posts(t["log_posts"], e.get("posts") or [], lang, t)
            + _log_posts(t["log_blogs"], e.get("blogs") or [], lang, t, turn))
    if not body:
        return ""
    return f"<li class=lgr><time datetime={esc(e['day'])}>{_log_date(e['day'], lang)}</time><div>{body}</div></li>"


def log_html(rows, lang="hr", days=None):
    """The block "MemeSonar je live N dana": heading, one line on the nightly refresh and the last LOG_SHOW days that
    have something new. Without rows (the job has not run yet) the heading and the line stay, with a note."""
    lang = "en" if lang == "en" else "hr"
    t = T[lang]
    num = _n_en if lang == "en" else _n
    if days is None:
        from ui import sitelog
        days = sitelog.live_days()
    items = []
    for e in rows or []:
        try:
            li = _log_row(e, lang, t, num)
        except Exception as ex:  # noqa: BLE001 - one odd row must not take the block (or the page) down
            print(f"naslovnica: redak dnevnika {e.get('day') if isinstance(e, dict) else '?'} preskočen: {ex}", flush=True)
            li = ""
        if li:
            items.append(li)
        if len(items) >= LOG_SHOW:
            break
    head = t["log_h"].format(n=_days_words(days, lang)) if days > 0 else t["log_h0"]
    lst = f"<ol class=lgl>{''.join(items)}</ol>" if items else f"<p class=small>{t['log_wait']}</p>"
    return (f"<section id=dnevnik style='padding:24px 0 72px'><div class='w center'><div class=lg>"
            f"<div class=eyebrow>{t['log_eye']}</div><h2>{head}</h2><p class=lead>{t['log_p']}</p>{lst}</div></div></section>")


_STRIP_ERR = [0.0]


def ap_block(lang):
    """20.11. (vlasnik 19.11.: "Autopilot stavi u drugi plan dok rekonstruiramo app"): one short block low on the page.
    While paused: the public pause notice of ui/pauza (the single source of that wording) and its demo sentence; else
    one plain line with a link to the public results. Never raises."""
    t = T["en" if lang == "en" else "hr"]
    href = "/autopilot" if lang == "en" else "/hr/autopilot"
    try:
        from ui import pauza
        if pauza.on():
            body = pauza.notice_html(lang, notr=True) + pauza.demo_html(lang, notr=True).replace("margin:-12px 0 18px",
                                                                                             "margin:8px 0 0")
        else:
            body = f"<p class=lead style='margin:0'>{t['ap_on']}</p>"
    except Exception as e:  # noqa: BLE001
        if time.time() - _STRIP_ERR[0] > 3600:
            _STRIP_ERR[0] = time.time()
            print(f"naslovnica: blok Autopilota nije prikazan: {type(e).__name__}: {e}", flush=True)
        return ""
    return (f"<section id=autopilot style='padding:40px 0'><div class=w><div class=apb><div class=eyebrow>{t['ap_eye']}"
            f"</div>{body}<p style='margin:14px 0 0'><a class=lk href={href}>{t['ap_btn']} →</a></p></div></div></section>")


SHOW = [   # the hero's "mini video": (file, tab, caption, address shown in the frame); real screens of the app (fixture)
    ("novcanici.jpg", "Novčanici", "Novčanici koji kupuju prije skoka, svaka skupina jednom rečenicom.",
     "app.memesonar.app/wallets"),
    ("mjerenje.jpg", "Mjerenje", "Svaka nova kupnja tih novčanika izmjerena u postocima, nakon troška.",
     "app.memesonar.app"),
    ("token-midcap.jpg", "Stranica tokena", "Svaki praćeni token od 2 milijuna dolara naviše ima svoju stranicu.",
     "memesonar.app/hr/coin"),
    # 20.11.: the Tokeni page is being rebuilt in another branch; this slot is re-shot after the merge
    ("tokeni.jpg", "Tokeni", "Tokeni koje pratimo, na jednom popisu.", "app.memesonar.app/tokens"),
]
SHOW_EN = [
    ("en-novcanici.jpg", "Wallets", "Wallets that buy before a jump, every group in one sentence.",
     "app.memesonar.app/wallets"),
    ("en-mjerenje.jpg", "Measured", "Every new buy of those wallets measured in percent, after costs.",
     "app.memesonar.app"),
    ("en-token-midcap.jpg", "Token page", "Every tracked token from 2 million dollars up has its own page.",
     "memesonar.app/coin"),
    ("en-tokeni.jpg", "Tokens", "The tokens we track, on one list.", "app.memesonar.app/tokens"),
]


def showcase(lang):
    """The hero's interactive "mini video": the app's real screenshots in a browser frame, each panned top to bottom,
    changing every 6 s; tabs jump to a screen, hover pauses, a click on the picture goes on. The first picture comes
    with the page (high priority); 15.11.: the rest are loaded right after the page has loaded (idle time, low priority),
    no longer only when their turn came, so a tab shows its screen at once. Without JavaScript the first screenshot stands."""
    en = lang == "en"
    shots = SHOW_EN if en else SHOW
    imgs = "".join(
        f'<img {"src" if k == 0 else "data-src"}="/static/landing/{f}" alt="{esc(SHOTS.get(f, tab))}" decoding=async'
        f'{" class=on fetchpriority=high" if k == 0 else " fetchpriority=low"}>' for k, (f, tab, _c, _u) in enumerate(shots))
    tabs = "".join(f'<button type=button role=tab aria-selected={"true" if k == 0 else "false"}{" class=on" if k == 0 else ""} '
                   f'data-cap="{esc(c)}" data-url="{esc(u)}">{esc(tab)}</button>' for k, (_f, tab, c, u) in enumerate(shots))
    label = "MemeSonar screens" if en else "Ekrani MemeSonara"
    return (f'<div class=show aria-label="{label}"><div class=fr><div class=bar><i></i><i></i><i></i><span>{esc(shots[0][3])}</span></div>'
            f'<div class=vp>{imgs}</div><div class=pg><i></i></div></div>'
            f'<div class=tabs role=tablist>{tabs}</div><p class=cap>{esc(shots[0][2])}</p></div>')


def data_ctas(lang, v):
    """Four buttons to the free public data (15.11.; 20.11.: the call and leaderboard buttons gave way to the midcap
    focus: the market, the macro influencers, the meme coins, the hours), each with its newest number when known."""
    en = lang == "en"
    idx = peak = None
    try:
        from ui import marketpub as M
        d = M.snapshot()
        if d:
            if d.get("regime"):
                sc = d["regime"][-1][1]
                idx = f"{sc:.0f}/100 · {M.label(sc, lang)}"
            h = d.get("hours")
            if h and h.get("vol"):
                b = max(range(24), key=lambda i: h["vol"][i])
                peak = f"{b:02d}:00 UTC"
    except Exception as e:  # noqa: BLE001 - the buttons stand without numbers
        print(f"naslovnica: podaci za gumbe nedostupni: {type(e).__name__}: {e}", flush=True)
    if en:
        head = "Free public data, no account:"
        items = [("/solana-market", idx or "Market today", "Meme coin season index: is the market hot or cold?", "Market today"),
                 ("/macro-influencers", "Macro", "Statements about the whole market, measured against what it did", "Macro influencers"),
                 ("/solana-meme-coins", "Top 100", "Solana meme coins by market cap, with a rug check", "Meme coins"),
                 ("/best-time-to-trade-crypto", peak or "By the hour", "the hour meme coin volume peaks" if peak else "When meme coins trade", "Best time to trade")]
    else:
        head = "Besplatni javni podaci, bez računa:"
        items = [("/hr/solana-trziste", idx or "Tržište danas", "Indeks sezone meme coina: je li tržište vruće ili hladno?", "Tržište danas"),
                 ("/hr/makro-influenceri", "Makro", "Izjave o cijelom tržištu, izmjerene po tome što je napravilo", "Makro influenceri"),
                 ("/hr/solana-meme-coini", "Top 100", "Solana meme coini po market capu, s provjerom ruga", "Meme coini"),
                 ("/hr/najbolje-vrijeme-za-trgovanje-kriptom", peak or "Po satu", "sat u kojem je volumen meme coina najveći" if peak else "Kad se meme coini trguju", "Najbolje vrijeme")]
    cards = "".join(f"<a href={h}><b>{esc(b)}</b><span>{esc(sub)}</span><em>{esc(lab)} →</em></a>" for h, b, sub, lab in items)
    return f"<div class=dcta><p>{head}</p><div>{cards}</div></div>"


def _pct1(x, en):
    s = f"{x * 100:+.1f} %"
    return s if en else s.replace(".", ",")


def live_html(lang, nv, age=""):
    """The live numbers of the wallet search (server-rendered, fixed slots: no layout shift when they change)."""
    en = lang == "en"
    t = T["en" if en else "hr"]
    num = _n_en if en else _n
    nv = nv or {}
    dash = t["meas_none"]

    def val(x):
        return num(x) if isinstance(x, (int, float)) and x is not None else dash
    m = nv.get("meas")
    if m and m.get("n"):
        if str(m.get("verdict") or "").startswith("premalo"):
            mv, ms = t["meas_early"], t["meas_n"].format(n=num(m["n"]))
        else:
            rng = (f" ({_pct1(m['lo'], en)} … {_pct1(m['hi'], en)})" if m.get("lo") is not None and m.get("hi") is not None
                   else "")
            mv = _pct1(m.get("mean") or 0, en)
            ms = (("per buy after costs" if en else "po kupnji nakon troška") + rng)
    elif m:
        mv, ms = t["meas_early"], t["meas_n"].format(n="0")
    else:
        mv, ms = dash, t["n_meas"]
    tiles = [(val(nv.get("rises")), t["n_rises"]), (val(nv.get("found")), t["n_found"]),
             (val(nv.get("confirmed")), t["n_conf"]), (mv, ms if m else t["n_meas"])]
    empty = nv.get("rises") is None and nv.get("found") is None
    foot = t["live_wait"] if empty else (t["live_upd"] + (f" · {age}" if age else ""))
    return (f"<section id=brojke style='padding:56px 0 24px'><div class=w><div class=center><div class=eyebrow>{t['live_eye']}"
            f"</div><h2>{t['live_h']}</h2></div><div class=nums style='--n:4'>"
            + "".join(f"<div class=num><b>{esc(x)}</b><span>{esc(lab)}</span></div>" for x, lab in tiles)
            + f"</div><div class=live><span class=pulse></span>{esc(foot)}</div></div></section>")


def wallets_html(lang, nv, app_href, app_label):
    """Two or three example sentences of the kind the app's card shows, WITHOUT addresses, and the way into the app."""
    en = lang == "en"
    t = T["en" if en else "hr"]
    num = _n_en if en else _n
    rows = []
    for e in (nv or {}).get("examples") or []:
        head = (t["wal_one"].format(n=num(e["n"])) if e["k"] <= 1 else
                t["wal_grp"].format(k=num(e["k"]), n=num(e["n"])))
        big = t["wal_big"].format(b=num(e["b"])) if e.get("b") and e["n"] > 1 else ""
        rows.append(f"<li>{esc(head + big + t['wal_conf'])}</li>")
    lst = f"<ul class=wx>{''.join(rows)}</ul>" if rows else f"<p class=small>{t['wal_wait']}</p>"
    return (f"<section id=novcanici class=soft><div class=w><div class=eyebrow>{t['wal_eye']}</div><h2>{t['wal_h']}</h2>"
            f"<p class=lead>{t['wal_p']}</p>{lst}<p class=fine style='text-align:left'>{t['disclaimer']}</p>"
            f"<div class=ctas style='justify-content:flex-start;margin-top:22px'><a class='btn p' href=#pristup>{t['req']}</a>"
            f"<a class='btn g' href={app_href}>{app_label}</a></div></div></section>")


def tokens_html(lang, nv):
    en = lang == "en"
    t = T["en" if en else "hr"]
    pre = "/coin/" if en else "/hr/coin/"
    toks = (nv or {}).get("tokens") or []
    links = "".join(f"<a href={pre}{quote(x['slug'])}><b translate=no>{esc(x['symbol'] or x['slug'])}</b>"
                    f"<span>{esc(_usd_short(x.get('mcap')))}</span></a>" for x in toks)
    allh = "/solana-meme-coins" if en else "/hr/solana-meme-coini"
    body = f"<div class=tk>{links}</div>" if links else f"<p class=small>{t['tok_wait']}</p>"
    return (f"<section id=tokeni style='padding-top:64px'><div class=w><div class=eyebrow>{t['tok_eye']}</div>"
            f"<h2>{t['tok_h']}</h2><p class=lead>{t['tok_p']}</p>{body}"
            f"<p style='margin:18px 0 0'><a class=lk href={allh}>{t['tok_all']} →</a></p></div></section>")


def _usd_short(x):
    try:
        v = float(x)
    except (TypeError, ValueError):
        return ""
    return f"{v / 1e6:.0f} M $" if v >= 1e7 else f"{v / 1e6:.1f} M $"


def macro_html(lang):
    """One secondary section linking to the public macro pages (only while they are published)."""
    t = T["en" if lang == "en" else "hr"]
    try:
        from makroinf import public as MP
        if not MP.nav_items(lang):
            return ""
    except Exception:  # noqa: BLE001
        return ""
    href = "/macro-influencers" if lang == "en" else "/hr/makro-influenceri"
    return (f"<section id=makro style='padding-top:24px'><div class=w><div class=eyebrow>{t['mak_eye']}</div>"
            f"<h2>{t['mak_h']}</h2><p class=lead>{t['mak_p']}</p><a class='btn g' href={href}>{t['mak_btn']} →</a>"
            f"</div></section>")


def page_html(qs=None, logged_in=False, ok=False, err="", form=None, lang="hr"):
    qs = qs or {}
    form = form or {}
    from ui import public as P
    from ui import sitenav as SN
    lang = "en" if lang == "en" else "hr"
    t = T[lang]
    en = lang == "en"
    home = "/" if en else "/hr"
    v, ts = stats()
    svg, name = logo(30)
    base = os.environ.get("RENDER_EXTERNAL_URL", "").rstrip("/")
    from ui import urls
    app_href, app_label = (urls.app_link("/"), t["app"]) if logged_in else (urls.app_link("/prijava"), t["login"])
    num = _n_en if en else _n

    age = ""
    if ts and v:
        age = ago(ts)[0]
        if en:
            age = age.replace("prije ", "").replace(" min", " min ago").replace(" h", " h ago").replace(" d", " d ago")
    nv = v.get("nov") or {}
    steps = "".join(f"<li><b>{k}</b><h3>{esc(h)}</h3><p>{esc(d)}</p></li>" for k, (h, d) in enumerate(t["steps"], 1))
    free_li = "".join(f"<li>{esc(x)}</li>" for x in t["free_li"])

    msg = f"<div class=ok>{t['f_ok']}</div>" if ok else (f"<div class=err>{esc(err)}</div>" if err else "")
    fv = {k: esc(form.get(k, "")) for k in ("name", "contact")}
    exp = form.get("experience", "")
    opts = "".join(f"<option value=\"{val}\"{' selected' if exp == val else ''}>{lab}</option>"
                   for val, lab in zip(("", "pocetnik", "povremeno", "aktivno", "profi"), t["f_opts"]))
    request_form = (
        f"<form class=rq method=post action=/zatrazi-pristup id=forma>{msg}"
        f"<input type=hidden name=lang value={'en' if en else 'hr'}>"
        f"<label>{t['f_name']}<input name=name required maxlength=40 autocomplete=name value=\"{fv['name']}\" "
        f"placeholder='{t['f_ph_name']}'></label>"
        f"<label>{t['f_contact']}<input name=contact type=email required maxlength=120 autocomplete=email value=\"{fv['contact']}\" "
        f"placeholder='{t['f_ph_contact']}'></label>"
        f"<label>{t['f_exp']}<select name=experience>{opts}</select></label>"
        "<div class=hp aria-hidden=true><label>Web<input name=web tabindex=-1 autocomplete=off></label></div>"
        f"<input type=hidden name=src value=\"{esc(qs.get('src', qs.get('utm_source', ''))[:40])}\">"
        f"<button class='btn p' type=submit>{t['req']}</button><p class=fine>{t['f_fine']}</p></form>")
    faq = "".join(f"<details><summary>{q}</summary><p>{a}</p></details>" for q, a in t["faq"])
    try:   # 10.11.: "MemeSonar je live N dana" from the rows cached with the numbers (no database read here)
        site_log = log_html(v.get("log"), lang)
    except Exception as e:  # noqa: BLE001
        print(f"naslovnica: dnevnik nije prikazan: {type(e).__name__}: {e}", flush=True)
        site_log = ""

    def part(name, fn, *a):
        try:
            return fn(*a)
        except Exception as e:  # noqa: BLE001 - one block never costs the front page
            print(f"naslovnica: {name}: {type(e).__name__}: {e}", flush=True)
            return ""

    og_img, og_alt = P.og_card("/", lang)
    og_img = base + og_img
    canon = f"{base}{home}"
    switch = (f"<a class=lnk href=/hr hreflang=hr lang=hr>HR</a>" if en else
              f"<a class=lnk href=/ hreflang=en lang=en>EN</a>")
    return f"""<!doctype html><html lang={'en' if en else 'hr'}><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1,viewport-fit=cover"><title>{esc(t['title'])}</title>
<meta name=description content="{esc(t['desc'])}"><link rel=canonical href="{canon}">
<link rel=alternate hreflang=en href="{base}/"><link rel=alternate hreflang=hr href="{base}/hr">
<link rel=alternate hreflang=x-default href="{base}/">
<meta property="og:type" content="website"><meta property="og:title" content="{esc(t['title'])}">
<meta property="og:description" content="{esc(t['desc'])}">{P.og_tags(lang, esc(og_img), og_alt)}
<meta property="og:url" content="{canon}"><meta name="twitter:title" content="{esc(t['title'])}">
<meta name="twitter:description" content="{esc(t['desc'])}">
<meta name=theme-color content="#ffffff">{_fav.HEAD}
<script type="application/ld+json">{{"@context":"https://schema.org","@type":"WebApplication","name":"{esc(name)}",
"url":"{canon}","applicationCategory":"FinanceApplication","operatingSystem":"Web","description":"{esc(t['desc'])}",
"offers":{{"@type":"Offer","price":"0","priceCurrency":"USD"}}}}</script>
<style>{CSS}{P._nav_css()}</style></head><body>
<nav class=top><div class=w><a class=brand href={home}>{svg}<span>{esc(name)}</span></a><span class=sp></span>
{P.nav_links(lang)}{switch}
<a class=lnk href={app_href}>{app_label}</a><a class='btn p sm' href=#pristup>{t['req']}</a>{P.mobile_menu(lang)}</div></nav>
<header class=hero><div class=hbg style="background-image:url(/static/landing/{'en-' if en else ''}token-midcap.jpg)"></div><div class=w>
<span class=pill><span class=dot></span>{t['pill']}</span>
<h1>{t['h1a']} <span class=g>{t['h1b']}</span></h1>
<p class=sub>{t['sub']}</p>
<div class=ctas><a class='btn p' href=#pristup>{t['req']}</a><a class='btn g' href={app_href}>{app_label}</a></div>
{showcase(lang)}
</div></header>

<section id=kako style='padding-top:56px'><div class=w><div class=center><div class=eyebrow>{t['how_eye']}</div>
<h2>{t['how_h']}</h2></div><ol class=steps>{steps}</ol></div></section>
{part("brojke", live_html, lang, nv, age)}
{part("novcanici", wallets_html, lang, nv, app_href, app_label)}
{part("tokeni", tokens_html, lang, nv)}
{part("makro", macro_html, lang)}

<section style='padding-top:40px'><div class=w><div class=eyebrow>{t['ex_eye']}</div><h2>{t['ex_h']}</h2>
{part("gumbi", data_ctas, lang, v)}{P.explore(lang)}</div></section>
{site_log}
{part("autopilot", ap_block, lang)}

<section class=soft id=cijena><div class=w><div class=free><div class=fl><div class=eyebrow>{t['free_eye']}</div>
<h2>{t['free_h']}</h2><p>{t['free_p']}</p><ul>{free_li}</ul><a class='btn p' href=#pristup>{t['req']}</a></div>
<div class=fbig><b>{t['free_big']}</b><span>{t['free_sub']}</span></div></div></div></section>

<section id=pristup><div class='w center'><div class=eyebrow>{t['rq_eye']}</div><h2>{t['rq_h']}</h2>
<p class=lead>{t['rq_p']}</p><div class=req>{request_form}</div></div></section>

<section class=soft><div class=w><div class=faq><h2 class=center style='margin-bottom:24px'>{t['faq_h']}</h2>
{faq}</div></div></section>

<footer><div class=w>{P._foot_links(lang)}<p style='margin:0 0 10px'>{switch.replace("class=lnk ", "")}</p>
© {time.gmtime().tm_year} {esc(name)} · {t['foot']}</div></footer>
<div class='mcta h'><a class='btn p' href=#pristup>{t['req']}</a></div>
<script>{JS}</script>{P._ga_tag(lang)}</body></html>"""


def _n_en(x):
    if x is None:
        return "–"
    x = float(x)
    if x >= 1_000_000:
        return f"{x / 1_000_000:.1f}M"
    return f"{x:,.0f}"



# ---------- access requests ----------------------------------------------------------------------------------------

def _con():
    from league import store
    con = store.connect()
    con.executescript(SCHEMA)
    return con


ERR_EN = {
    "Upiši ime ili nadimak.": "Please enter your name.",
    "Upiši ispravan e-mail, njime ti šaljemo pozivnicu i novosti.": "Please enter a valid e-mail: we send the invite and news there.",
    "Previše zahtjeva s ove adrese. Pokušaj ponovno za sat vremena.": "Too many requests from this address. Try again in an hour.",
    "Lista čekanja je trenutno puna. Pokušaj ponovno za par dana.": "The waiting list is full right now. Try again in a few days.",
    "Zahtjev trenutno nije moguće spremiti. Pokušaj ponovno za par minuta.": "We couldn't save your request. Try again in a few minutes.",
}


def submit(form, ip=""):
    """(True, None) when stored, else (False, plain-Croatian reason). Honeypot hits pretend to succeed."""
    if (form.get("web") or "").strip():
        return True, None
    name = re.sub(r"\s+", " ", (form.get("name") or "").strip())[:40]
    contact = (form.get("contact") or "").strip()[:120]
    if len(name) < 2:
        return False, "Upiši ime ili nadimak."
    from league.profiles import EMAIL
    if not EMAIL.fullmatch(contact):   # 3.11.: an e-mail is required, so we can reach everyone about new features
        return False, "Upiši ispravan e-mail, njime ti šaljemo pozivnicu i novosti."
    now = time.time()
    hits = [t for t in _IPS.get(ip, []) if now - t < 3600]
    if len(hits) >= PER_IP_HOUR:
        return False, "Previše zahtjeva s ove adrese. Pokušaj ponovno za sat vremena."
    _IPS[ip] = hits + [now]
    try:
        con = _con()
        try:
            if (con.execute("SELECT COUNT(*) FROM access_requests WHERE status='novi'").fetchone()[0] or 0) >= MAX_PENDING:
                return False, "Lista čekanja je trenutno puna. Pokušaj ponovno za par dana."
            dup = con.execute("SELECT id FROM access_requests WHERE contact=? AND status='novi'", (contact,)).fetchone()
            if dup:
                return True, None
            con.execute("INSERT INTO access_requests (ts, name, contact, experience, interest, source, ip) "
                        "VALUES (?,?,?,?,?,?,?)",
                        (int(now), name, contact, (form.get("experience") or "")[:20],
                         (form.get("interest") or "").strip()[:600], (form.get("src") or "")[:40], ip[:64]))
            con.commit()
        finally:
            con.close()
    except sqlite3.OperationalError as e:
        print(f"zahtjev za pristup nije spremljen: {e}", flush=True)
        return False, "Zahtjev trenutno nije moguće spremiti. Pokušaj ponovno za par minuta."
    print(f"pristup: zahtjev za pristup od {name}", flush=True)
    return True, None


def pending_count():
    try:
        con = _con()
        try:
            return con.execute("SELECT COUNT(*) FROM access_requests WHERE status='novi'").fetchone()[0] or 0
        finally:
            con.close()
    except sqlite3.Error:
        return 0


EXP = {"pocetnik": "tek počinje", "povremeno": "povremeno", "aktivno": "aktivno, memecoini", "profi": "svaki dan"}
STATUS = {"novi": ("novi", "warn"), "pozvan": ("pozvan", "good"), "odbijen": ("odbijen", ""), "obrisan": ("pozivnica obrisana", ""),
          "registriran": ("registriran", "good")}


def _invite_text(row, url):
    return (f"Bok {row['name']}! Evo tvoje pozivnice za MemeSonar: {url}\n"
            "Otvori link, upiši ime i lozinku i dobiješ demo račun od $1.000.")


def _share(row, url):
    """Buttons to send the invite: WhatsApp (to the number when we have one), e-mail (to the address when we have one),
    Telegram share, and the phone's own share sheet when the browser has one."""
    text = _invite_text(row, url)
    c = (row["contact"] or "").strip()
    digits = re.sub(r"[^\d+]", "", c)
    if re.fullmatch(r"\+?\d{8,15}", digits) and "@" not in c:
        num = digits.lstrip("+")
        if num.startswith("0"):
            num = "385" + num[1:]   # Croatian number written locally
        wa = f"https://wa.me/{num}?text={quote(text)}"
    else:
        wa = f"https://wa.me/?text={quote(text)}"
    to = esc(c) if ("@" in c and "." in c.split("@")[-1] and not c.startswith("@")) else ""
    mail = f"mailto:{to}?subject={quote('Tvoja pozivnica za MemeSonar')}&body={quote(text)}"
    tg = f"https://t.me/share/url?url={quote(url)}&text={quote(text.split(': ')[0] + ':')}"
    return (f"<a class='sh' href=\"{wa}\" target=_blank rel=noopener title='Pošalji na WhatsApp'>WhatsApp</a>"
            f"<a class='sh' href=\"{mail}\" title='Pošalji e-mailom'>E-mail</a>"
            f"<a class='sh' href=\"{tg}\" target=_blank rel=noopener title='Pošalji na Telegram'>Telegram</a>"
            f"<button type=button class='sh ns' hidden data-t=\"{esc(text)}\" title='Ostale aplikacije na mobitelu' "
            "onclick=\"navigator.share({text:this.dataset.t}).catch(function(){})\">Više…</button>")


INV_CSS = """<style>
/* 3.11.: one quiet list instead of big coloured share buttons */
.invl{display:grid;gap:8px;margin:8px 0 14px}
.inv{border:1px solid var(--line,#e5e7eb);border-radius:12px;padding:10px 12px;display:grid;gap:6px;background:var(--card,#fff)}
.inv .hd{display:flex;justify-content:space-between;gap:8px;align-items:baseline;flex-wrap:wrap}
.inv .hd b{font-size:15px}.inv .mt{color:var(--mut,#6b7280);font-size:12.5px}
.inv .lk{display:flex;gap:6px}.inv .lk input{flex:1;min-width:0;font-size:13px;padding:6px 8px;border-radius:8px}
.inv .cp,.inv .del{white-space:nowrap;padding:6px 10px;border-radius:8px;font-size:13px}
.inv .ac{display:flex;gap:6px;flex-wrap:wrap;align-items:center}
.inv .sh{font-size:12.5px;padding:3px 9px;border:1px solid var(--line,#e5e7eb);border-radius:999px;color:var(--fg,#111)!important;
text-decoration:none!important;background:none;cursor:pointer;font-family:inherit;line-height:1.5}
.inv .sh[hidden]{display:none}.inv .del{margin-left:auto;background:none;border:1px solid var(--line,#e5e7eb);color:#b91c1c;cursor:pointer}
.inv.off{opacity:.7}
</style>"""


def _invites_html(con, user):
    """Pozivnice: every invite link with copy, small share links and Obriši; active first, used/deleted collapsed."""
    from league import members
    from ui.register import link
    try:
        members.connect().close()
        invs = members.all_invites(con)
        req = {r["invite"]: dict(r) for r in con.execute(
            "SELECT invite, name, contact FROM access_requests WHERE invite IS NOT NULL")}
    except sqlite3.Error:
        return ""

    def card(i):
        r = req.get(i["token"])
        url = link(i["token"])
        who = (f"Za {esc(r['name'])}" if r else "Stalni link" if i["kind"] == "stalni" else "Jednokratni link")
        if i["active"]:
            st = ("vrijedi za više ljudi" if i["kind"] == "stalni" else "čeka da se registrira")
            if i["joined"]:
                st += f" · registrirali: {esc(i['joined'])}"
        elif i["used_by"]:
            st = f"✅ iskoristio <b>{esc(i['used_by'])}</b>"
        else:
            st = "poništen" + (f" · registrirali: {esc(i['joined'])}" if i["joined"] else "")
        meta = f"{st} · napravljen {ago(i['created'])[0]}" + (f" · {esc(r['contact'])}" if r and r.get("contact") else "")
        delete = (f"<form method=post action=/zahtjevi/pozivnica/obrisi style='margin:0;margin-left:auto'>"
                  f"<input type=hidden name=k value=\"{esc(i['token'])}\"><button class=del onclick=\"return confirm("
                  "'Obrisati pozivnicu? Link prestaje raditi. Računi napravljeni s njim ostaju.')\">Obriši</button></form>")
        if not i["active"]:
            return f"<div class='inv off'><div class=hd><b>{who}</b>{delete}</div><div class=mt>{meta}</div></div>"
        row = r or {"name": "", "contact": ""}
        return (f"<div class=inv><div class=hd><b>{who}</b><span class=mt>{meta}</span></div>"
                f"<div class=lk><input readonly value=\"{esc(url)}\" data-inv=\"{esc('/registracija?k=' + quote(i['token']))}\" "
                "onclick='this.select()' aria-label='Link pozivnice'>"
                "<button type=button class=cp onclick=\"var i=this.previousElementSibling;i.select();"
                "navigator.clipboard&&navigator.clipboard.writeText(i.value);this.textContent='✅ Kopirano'\">Kopiraj</button></div>"
                f"<div class=ac><span class=mt>Pošalji:</span>{_share(row, url)}{delete}</div></div>")

    act = [i for i in invs if i["active"]]
    old = [i for i in invs if not i["active"]]
    return (INV_CSS + f"<h2 id=pozivnice style='margin:18px 0 4px'>Pozivnice ({len(act)} aktivnih)</h2>"
            "<p class=mut style='margin:0 0 6px'>Svaki link za registraciju na jednom mjestu. <b>Obriši</b> zaustavi "
            "link; računi koji su već napravljeni ostaju.</p>"
            "<div style='display:flex;gap:6px;flex-wrap:wrap'>"
            "<form method=post action=/zahtjevi/pozivnica/jednokratni style='margin:0'><button>➕ Jednokratni link"
            "</button></form><form method=post action=/zahtjevi/pozivnica/stalni style='margin:0'><button "
            "onclick=\"return confirm('Stari stalni link prestaje vrijediti. Računi koji su već napravljeni ostaju.')\">"
            "🔄 Novi stalni link</button></form></div>"
            + "<div class=invl>" + ("".join(card(i) for i in act) or "<p class=mut>Nema aktivnih pozivnica.</p>")
            + "</div>"
            + (f"<details><summary>Iskorištene i poništene ({len(old)})</summary><div class=invl>"
               + "".join(card(i) for i in old[:100]) + "</div></details>" if old else "")
            + "<script>if(navigator.share)document.querySelectorAll('.sh.ns').forEach(function(b){b.hidden=false})</script>")


def admin_page(qs, user):
    """/zahtjevi: who asked for access, with one-click single-use invites."""
    from ui import register
    title = "Pozivnice i zahtjevi"
    if not register.can_invite(user):
        return title, ("<h1>Zahtjevi za pristup</h1><div class=card>Ovu stranicu vidi samo administrator. "
                       "<a href=/prijava>Prijavi se svojim imenom</a>.</div>")
    try:
        con = _con()
        try:
            rows = [dict(r) for r in con.execute(
                "SELECT * FROM access_requests ORDER BY (status='novi') DESC, ts DESC LIMIT 300")]
            joined = {r[0]: r[1] for r in con.execute("SELECT invite, name FROM members WHERE invite IS NOT NULL")} \
                if con.execute("SELECT 1 FROM sqlite_master WHERE name='members'").fetchone() else {}
        finally:
            con.close()
    except sqlite3.Error as e:
        return title, f"<h1>Zahtjevi za pristup</h1><div class=card neg>Baza nije dostupna: {esc(e)}</div>"
    b = ["<h1>Pozivnice i zahtjevi</h1>"]
    if qs.get("ok"):
        b.append(f"<div class=card style='border-color:var(--good)'>✅ {esc(qs['ok'])}</div>")
    novi = sum(1 for r in rows if r["status"] == "novi")
    if novi:
        b.append(f"<p class=lead>Ljudi koji su na <a href=/dobrodosli target=_blank>naslovnoj stranici</a> kliknuli "
                 f"„Zatraži pristup”. <b>{novi}</b> čeka odgovor. Klikni <b>✉️ Pozovi</b> u stupcu Akcija i alat napravi "
                 "jednokratni link za tu osobu, pa ga pošalješ na WhatsApp, e-mail ili Telegram jednim klikom.</p>")
    else:
        # 2.11.: with nothing pending the old text still said "click Invite" and no such button was anywhere
        b.append("<p class=lead>Ljudi koji su na <a href=/dobrodosli target=_blank>naslovnoj stranici</a> kliknuli "
                 "„Zatraži pristup”. <b>Trenutno nitko ne čeka odgovor</b>, zato u tablici nema gumba Pozovi. Gumb se "
                 "pojavi uz svaki novi zahtjev. Želiš nekoga pozvati odmah? Upiši ga ispod i dobiješ link s gumbom za "
                 "WhatsApp.</p>")
    b.append("<form method=post action=/zahtjevi/nova class=card style='display:flex;gap:8px;flex-wrap:wrap;"
             "align-items:flex-end;margin:10px 0'><b style='flex-basis:100%'>➕ Pozovi nekoga odmah</b>"
             "<label style='flex:1;min-width:150px'>Ime<br><input name=name required maxlength=60 "
             "style='width:100%' placeholder='npr. Marko'></label>"
             "<label style='flex:1;min-width:180px'>Mobitel ili e-mail (nije obavezno)<br><input name=contact "
             "maxlength=120 style='width:100%' placeholder='npr. 091 234 5678'></label>"
             "<button>✉️ Napravi pozivnicu</button></form>")
    from ui.html import table
    out = []
    from ui.register import link
    for r in rows:
        st = r["status"]
        if r["invite"] and r["invite"] in joined:
            st = "registriran"
        lab, kind = STATUS.get(st, (st, ""))
        if r["status"] == "novi":
            act = (f"<form method=post action=/zahtjevi/{r['id']}/pozovi style='display:inline;margin:0'>"
                   "<button>✉️ Pozovi</button></form> "
                   f"<form method=post action=/zahtjevi/{r['id']}/odbij style='display:inline;margin:0'>"
                   "<button class=sm onclick=\"return confirm('Odbiti zahtjev?')\">Odbij</button></form>")
        elif r["status"] == "pozvan" and r["invite"]:
            url = link(r["invite"])
            if st == "registriran":
                act = f"<span class=mut>✅ ušao u aplikaciju kao <b>{esc(joined[r['invite']])}</b></span>"
            else:
                act = "<a href=#pozivnice>📨 Pošalji pozivnicu ↑</a>"
        else:
            act = f"<span class=mut>{esc(r['handled_by'] or '')}</span>"
        out.append([ago(r["ts"]), f"<b>{esc(r['name'])}</b>", esc(r["contact"]), esc(EXP.get(r["experience"], "–")),
                    f"<span style='white-space:normal'>{esc(r['interest'] or '')}</span>",
                    f"<span class='b {kind}'>{esc(lab)}</span>", act])
    try:
        con = _con()
        try:
            b.append(_invites_html(con, user))
        finally:
            con.close()
    except sqlite3.Error:
        pass
    b.append("<h2 style='margin:18px 0 4px'>Zahtjevi za pristup</h2>")
    b.append(table(["Kada", "Ime", "Kontakt", "Iskustvo", "Zanima ga", "Status", "Akcija"], out, tid="zahtjevi",
                   empty="Još nema zahtjeva. Pošalji link naslovne stranice ljudima koje želiš privući."))
    if not os.environ.get("RENDER_EXTERNAL_URL"):
        b.append("<script>document.querySelectorAll('input[data-inv]').forEach(function(i){"
                 "i.value=location.origin+i.dataset.inv})</script>")
    return title, "".join(b)


def admin_post(path, user, form=None):
    from league import members
    from ui import register
    if not register.can_invite(user):
        return "/zahtjevi"
    if path.startswith("/zahtjevi/pozivnica/"):
        con = _con()
        try:
            members.connect().close()
            act = path.rsplit("/", 1)[1]
            if act == "obrisi":
                tok = (form or {}).get("k", "")
                members.delete(con, tok)
                con.execute("UPDATE access_requests SET status='obrisan' WHERE invite=? AND status='pozvan'", (tok,))
                con.commit()
                msg = "Pozivnica je obrisana: link više ne radi."
            elif act == "jednokratni":
                members.single(con, user)
                msg = "Napravljen je jednokratni link, kopiraj ga ispod."
            elif act == "stalni":
                members.renew(con, user)
                msg = "Napravljen je novi stalni link, stari više ne vrijedi."
            else:
                return "/zahtjevi"
        finally:
            con.close()
        print(f"pristup: {user} pozivnica {path.rsplit('/', 1)[1]}", flush=True)
        return f"/zahtjevi?ok={quote(msg)}#pozivnice"
    if path == "/zahtjevi/nova":   # invite someone who never filled in the form
        name = (form or {}).get("name", "").strip()[:60]
        if not name:
            return "/zahtjevi"
        con = _con()
        try:
            members.connect().close()
            tok = members.single(con, user)
            now = int(time.time())
            con.execute("INSERT INTO access_requests (ts, name, contact, source, status, handled_by, handled_ts, invite) "
                        "VALUES (?,?,?,?,?,?,?,?)",
                              (now, name, (form or {}).get("contact", "").strip()[:120], "ručno", "pozvan", user, now,
                               tok))
            con.commit()
        finally:
            con.close()
        print(f"pristup: {user} ručna pozivnica za {name}", flush=True)
        return f"/zahtjevi?ok={quote(f'Pozivnica za {name} je spremna: pošalji je ispod.')}#pozivnice"
    m = re.fullmatch(r"/zahtjevi/(\d+)/(pozovi|odbij)", path)
    if not m:
        return "/zahtjevi"
    rid, act = int(m.group(1)), m.group(2)
    con = _con()
    try:
        r = con.execute("SELECT name, status FROM access_requests WHERE id=?", (rid,)).fetchone()
        if not r or r["status"] != "novi":
            return "/zahtjevi"
        if act == "pozovi":
            members.connect().close()   # invites table exists
            tok = members.single(con, user)
            con.execute("UPDATE access_requests SET status='pozvan', invite=?, handled_by=?, handled_ts=? WHERE id=?",
                        (tok, user, int(time.time()), rid))
            msg = f"Pozivnica za {r['name']} je spremna: kopiraj link ili ga pošalji gumbom ispod."
        else:
            con.execute("UPDATE access_requests SET status='odbijen', handled_by=?, handled_ts=? WHERE id=?",
                        (user, int(time.time()), rid))
            msg = f"Zahtjev od {r['name']} je odbijen."
        con.commit()
    finally:
        con.close()
    print(f"pristup: {user} zahtjev {rid} {act}", flush=True)
    return f"/zahtjevi?ok={quote(msg)}"
