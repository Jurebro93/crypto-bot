"""5.11. (Nicholas): "big influencers who engage on other influencers' calls do it to widen the post's reach, which
means they were already in before the call: that is the insider signal". For every fresh call of a reaching
account we read who replied, retweeted and quoted it (twitterapi.io, one page each, ~$0.01 per call), link the
engagers to wallets we know (kol_ids twitter -> wallet) and check whether that wallet bought the token BEFORE the
call (hype.db chain_trades / live_trades). kol.db engagers. From it: per token the hype feature `ekipa` (big
engagers within 30 min / 3) and `ekipa_insajder` (an engager's wallet bought before the call), the demo strategy
"Ekipa", and on the KOL page who amplifies whom.
"""
import json
import sqlite3
import time

DEFAULT = {"lookback_h": 2, "min_age_min": 20, "per_run": 12, "daily_usd": 0.8, "caller_min_followers": 10000,
           "big_followers": 20000, "window_min": 30, "before_h": 24}
SCHEMA = """CREATE TABLE IF NOT EXISTS engagers (
    tweet_id TEXT, token TEXT, caller TEXT, call_ts INTEGER, engager TEXT, kind TEXT, followers INTEGER, ts INTEGER,
    delay_s INTEGER, wallet TEXT, bought_before INTEGER DEFAULT 0, PRIMARY KEY (tweet_id, engager, kind));
CREATE INDEX IF NOT EXISTS engagers_token ON engagers (token, call_ts);
CREATE INDEX IF NOT EXISTS engagers_caller ON engagers (caller, call_ts)"""
REPLIES, RETWEETERS, QUOTES = ("https://api.twitterapi.io/twitter/tweet/replies", "https://api.twitterapi.io/twitter/tweet/retweeters",
                               "https://api.twitterapi.io/twitter/tweet/quotes")


def config(cfg):
    return {**DEFAULT, **((cfg or {}).get("crew") or {})}


def ensure(con):
    con.executescript(SCHEMA)


def due_calls(con, cfg, now=None):
    """[(tweet_id, token, handle, ts)] fresh X calls of reaching accounts not yet read."""
    c = config(cfg)
    now = now or int(time.time())
    done = {t[5:] for (t,) in con.execute("SELECT target FROM searches WHERE target LIKE 'crew:%'")}
    rows = con.execute("""SELECT c.tweet_id, c.token, c.handle, c.ts FROM calls c LEFT JOIN kols k ON k.handle = c.handle
        WHERE c.kind = 'call' AND c.tweet_id GLOB '[0-9]*' AND c.ts >= ? AND c.ts <= ? AND COALESCE(k.bot, 0) = 0
          AND (COALESCE(k.followers, c.followers, 0) >= ? OR COALESCE(k.score, 0) >= ?)
        ORDER BY c.ts DESC""", (now - c["lookback_h"] * 3600, now - c["min_age_min"] * 60, c["caller_min_followers"],
                                (cfg or {}).get("good_score", 60))).fetchall()
    out, seen = [], set()
    for tid, tok, h, ts in rows:
        if tid in done or tid in seen:
            continue
        seen.add(tid)
        out.append((tid, tok, h, ts))
        if len(out) >= c["per_run"]:
            break
    return out


def fetch_engagers(tweet_id, get, call_ts):
    """[(engager, kind, followers, ts)] from one page of replies, retweeters and quotes."""
    from kol import collect
    out = []
    for url, kind, key in ((REPLIES, "reply", "tweets"), (QUOTES, "quote", "tweets"), (RETWEETERS, "retweet", "users")):
        try:
            d = get(url, {"tweetId": tweet_id, "cursor": ""}) or {}
        except Exception:  # noqa: BLE001
            continue
        for it in d.get(key) or []:
            a = it.get("author") or it if key == "tweets" else it
            h = a.get("userName") or a.get("screen_name")
            if not h:
                continue
            ts = collect.tweet_ts(it.get("createdAt")) if key == "tweets" else None
            out.append((h, kind, int(a.get("followers") or 0), ts))
    return out


def _wallets_by_handle(con):
    out = {}
    try:
        for w, tw in con.execute("SELECT wallet, twitter FROM kol_ids WHERE twitter IS NOT NULL AND twitter != ''"):
            out.setdefault(tw.lower().lstrip("@"), w)
    except sqlite3.OperationalError:
        pass
    return out


def bought_before(hype_db, wallet, token, call_ts, before_h=24):
    """Did `wallet` buy `token` in the before_h hours before the call? (chain_trades or live_trades)"""
    try:
        h = sqlite3.connect(f"file:{hype_db}?mode=ro", uri=True, timeout=5)
    except sqlite3.Error:
        return False
    try:
        for table in ("chain_trades", "live_trades"):
            col = "mint"
            try:
                r = h.execute(f"SELECT 1 FROM {table} WHERE wallet=? AND {col}=? AND side='buy' AND ts<? AND ts>=? LIMIT 1",
                              (wallet, token, int(call_ts), int(call_ts) - before_h * 3600)).fetchone()
                if r:
                    return True
            except sqlite3.OperationalError:
                continue
        return False
    finally:
        h.close()


def run(con, cfg, hype_db, get=None, now=None, log=print):
    """One round within the daily budget. Returns (calls read, engagers stored, insiders found)."""
    from kol import collect, twapi
    if not twapi.key() and get is None:
        return 0, 0, 0
    ensure(con)
    c = config(cfg)
    now = now or int(time.time())
    day = time.strftime("%Y-%m-%d", time.gmtime(now))
    row = con.execute("SELECT value FROM kv WHERE key = ?", (f"twcrew:{day}",)).fetchone()
    spent = float(row[0]) if row else 0.0
    get = get or (lambda url, params: twapi._get_url(url, params))
    wallets = _wallets_by_handle(con)
    n_calls = n_eng = n_ins = 0
    for tid, tok, caller, call_ts in due_calls(con, cfg, now):
        if spent >= c["daily_usd"]:
            break
        eng = fetch_engagers(tid, get, call_ts)
        spent += 3 * 0.00015 + len(eng) * 0.00015
        for h, kind, foll, ts in eng:
            if h.lower() == (caller or "").lower():
                continue
            w = wallets.get(h.lower())
            before = bool(w and bought_before(hype_db, w, tok, call_ts, c["before_h"]))
            delay = (ts - call_ts) if ts else None
            n_eng += con.execute("INSERT OR IGNORE INTO engagers VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                                 (tid, tok, caller, int(call_ts), h, kind, foll, ts, delay, w, int(before))).rowcount
            n_ins += int(before)
        collect._searched(con, f"crew:{tid}", "crew", now)
        n_calls += 1
    con.execute("INSERT INTO kv VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value", (f"twcrew:{day}", str(spent)))
    con.commit()
    if n_calls:
        log(f"ekipa: {n_calls} poziva pročitano, {n_eng} reakcija, {n_ins} ušlo prije poziva (danas ${spent:.2f})")
    return n_calls, n_eng, n_ins


def token_crew(kol_db, mints, since, cfg=None):
    """{mint: {big: n, insider: n}} for the scan: big engagers within window_min of a call, and pre-call buyers."""
    c = config(cfg)
    try:
        con = sqlite3.connect(f"file:{kol_db}?mode=ro", uri=True, timeout=5)
    except sqlite3.Error:
        return {}
    out = {}
    try:
        q = ",".join("?" * len(mints)) if mints else "''"
        for tok, foll, delay, before in con.execute(
                f"SELECT token, followers, delay_s, bought_before FROM engagers WHERE call_ts >= ? AND token IN ({q})", [int(since), *mints]):
            d = out.setdefault(tok, {"big": 0, "insider": 0})
            if (foll or 0) >= c["big_followers"] and (delay is None or 0 <= delay <= c["window_min"] * 60):
                d["big"] += 1
            d["insider"] += int(before or 0)
    except sqlite3.OperationalError:
        return {}
    finally:
        con.close()
    return out


def signals(kol_db, since, cfg=None):
    """[(token, ts, who, score)] tokens whose call got 2+ big engagers and 1+ pre-call buyer: the 'Ekipa' strategy."""
    c = config(cfg)
    try:
        con = sqlite3.connect(f"file:{kol_db}?mode=ro", uri=True, timeout=5)
    except sqlite3.Error:
        return []
    out = []
    try:
        for tok, ts, caller, big, ins in con.execute(
                """SELECT token, MIN(call_ts), caller, SUM(CASE WHEN followers >= ? AND (delay_s IS NULL OR delay_s BETWEEN 0 AND ?) THEN 1 ELSE 0 END),
                          SUM(bought_before) FROM engagers WHERE call_ts >= ? GROUP BY token""",
                (c["big_followers"], c["window_min"] * 60, int(since))):
            if big >= 2 and ins >= 1:
                out.append((tok, int(ts), f"ekipa: {big} velika računa reagirala, {ins} ušlo prije poziva ({caller})", float(big + ins)))
    except sqlite3.OperationalError:
        return []
    finally:
        con.close()
    return out


def html(con, handle):
    """KOL page: who amplifies this account's calls (and bought before), and whose calls it amplifies."""
    from ui.html import esc
    ensure(con)
    amp = con.execute("SELECT engager, COUNT(*), SUM(bought_before), MAX(followers) FROM engagers WHERE LOWER(caller)=LOWER(?) "
                      "GROUP BY LOWER(engager) ORDER BY COUNT(*) DESC, MAX(followers) DESC LIMIT 10", (handle,)).fetchall()
    mine = con.execute("SELECT caller, COUNT(*), SUM(bought_before) FROM engagers WHERE LOWER(engager)=LOWER(?) "
                       "GROUP BY LOWER(caller) ORDER BY COUNT(*) DESC LIMIT 10", (handle,)).fetchall()
    if not amp and not mine:
        return ""
    li = lambda rows, fmt: "".join(fmt(r) for r in rows)
    return ("<h2>Ekipa</h2><p class=mut>Tko pojačava njegove pozive (odgovori, retweetovi, citati u prvih 30 min) i je li taj "
            "novčanik kupio prije poziva; i čije pozive on pojačava. Reakcija velikog računa prije poziva = insajder.</p>"
            + ("<p><b>Pojačavaju ga:</b></p><ul class=r>" + li(amp, lambda r: f"<li><a href='/kol/{esc(r[0])}'>@{esc(r[0])}</a>: {r[1]}× "
               + (f"<b class=neg>{r[2]}× kupio prije poziva</b>" if r[2] else "") + f" <small class=mut>{(r[3] or 0):,} pratitelja</small></li>") + "</ul>" if amp else "")
            + ("<p><b>On pojačava:</b></p><ul class=r>" + li(mine, lambda r: f"<li><a href='/kol/{esc(r[0])}'>@{esc(r[0])}</a>: {r[1]}×"
               + (f", <b class=neg>{r[2]}× ušao prije poziva</b>" if r[2] else "") + "</li>") + "</ul>" if mine else ""))
