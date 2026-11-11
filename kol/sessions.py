"""Trading sessions and KOL time zones.

US and Asian (mostly Chinese) market makers and buyers move memecoins at different hours. Three sessions in UTC:
asia 00-08 (China 08-16), eu 08-14 (Croatia 09-15 winter), us 14-24 (New York 09-19). For each:

- KOL time zone: from the hours a KOL posts. The quietest 6 h of the day is taken as his night (centred on 04:00
  local), which gives a UTC offset and a region. Needs zone_min_posts posts.
- token volume by session: GeckoTerminal 5-min candles that measure.py already fetches, summed per UTC hour
  (token_hours), so a token shows whether its volume is American, Asian or European.
- learning: how calls and KOL group signals did per session (hit = +hit_x within 24 h). The signal factor of a
  session is its hit rate over the overall one, shrunk towards 1 with shrink_n calls and kept in [min, max], so
  thin data never swings it. kol_group signals are multiplied by the factor of the session they start in, and the
  hit rate of signals per session is the measured accuracy of those suggestions. Recomputed every score run.
"""
import json
import statistics
import time

SESSIONS = [("asia", 0, 8), ("eu", 8, 14), ("us", 14, 24)]
NAMES = {"asia": "Azija", "eu": "Europa", "us": "SAD"}
H = 3600


def session_of(ts):
    h = int(ts // H) % 24
    return next(s for s, a, b in SESSIONS if a <= h < b)


def region_of(offset):
    if offset is None:
        return None
    if -10 <= offset <= -3:
        return "us"
    if -2 <= offset <= 4:
        return "eu"
    if 5 <= offset <= 10:
        return "asia"
    return None


def zone(timestamps, min_posts=12, night=6):
    """(utc_offset, region, posts) from posting times; offset None with too few posts or no clear night."""
    hours = [0] * 24
    for t in timestamps:
        hours[int(t // H) % 24] += 1
    n = sum(hours)
    if n < min_posts:
        return None, None, n
    best = min(range(24), key=lambda s: sum(hours[(s + i) % 24] for i in range(night)))
    quiet = sum(hours[(best + i) % 24] for i in range(night))
    if quiet > n * night / 24 * 0.5:  # night not clearly quieter than average: bot or many authors
        return None, None, n
    centre = (best + night / 2) % 24  # UTC hour of his 04:00 local
    off = int(round(4 - centre))
    off = (off + 12) % 24 - 12  # -12..11
    return off, region_of(off), n


def zones(con, cfg):
    """Write zone into each KOL's stats (score_kols rewrites stats, so this runs after it)."""
    z = cfg.get("sessions", {})
    times = {}
    for h, ts in con.execute("SELECT handle, ts FROM calls GROUP BY tweet_id"):
        times.setdefault(h, []).append(ts)
    n = 0
    for h, st in con.execute("SELECT handle, stats FROM kols").fetchall():
        off, reg, posts = zone(times.get(h, []), z.get("zone_min_posts", 12))
        s = json.loads(st or "{}")
        s.update(tz=off, region=reg, posts=posts)
        con.execute("UPDATE kols SET stats = ? WHERE handle = ?", (json.dumps(s), h))
        n += reg is not None
    return n


def hours_from_candles(candles):
    """{utc_hour: volume_usd} from 5-min candles [(ts, o, h, l, c, v)]."""
    out = {}
    for c in candles:
        hr = int(c[0] // H) % 24
        out[hr] = out.get(hr, 0.0) + c[5]
    return out


def save_hours(con, token, candles, now=None):
    hrs = hours_from_candles(candles)
    if not hrs:
        return
    con.execute("DELETE FROM token_hours WHERE token = ?", (token,))
    con.executemany("INSERT INTO token_hours VALUES (?,?,?,?)",
                    [(token, h, v, now or int(time.time())) for h, v in hrs.items()])


def shares(hours):
    """{session: share of volume} from {utc_hour: volume}."""
    tot = sum(hours.values())
    if not tot:
        return {}
    return {s: sum(v for h, v in hours.items() if a <= h < b) / tot for s, a, b in SESSIONS}


def token_shares(con, token):
    return shares(dict(con.execute("SELECT hour, volume FROM token_hours WHERE token = ?", (token,))))


def dominant(sh, min_share=0.45):
    if not sh:
        return None
    s = max(sh, key=sh.get)
    return s if sh[s] >= min_share else "mix"


def _factor(hits, n, base, cfg):
    z = cfg.get("sessions", {})
    k = z.get("shrink_n", 30)
    if not base:
        return 1.0
    f = ((hits + k * base) / (n + k)) / base
    return round(max(z.get("factor_min", 0.7), min(z.get("factor_max", 1.3), f)), 3)


def learn(con, cfg, now=None):
    """Recompute the sessions table. Keys: call:<s> (first calls posted in s), signal:<s> (group calls with a good
    KOL and no dev selling that started in s: the accuracy of the kol_group suggestion), vol:<s> (calls on tokens
    whose volume is mostly in s), match:yes/no (KOL posting in his own daytime session or not)."""
    now = now or int(time.time())
    hx = cfg["hit_x"]
    calls = con.execute("SELECT c.ts, c.max24, c.token, k.stats FROM calls c LEFT JOIN kols k ON k.handle = c.handle "
                        "WHERE c.kind = 'call' AND c.first_by_kol = 1 AND c.max24 IS NOT NULL").fetchall()
    dom = {}
    for t, h, v in con.execute("SELECT token, hour, volume FROM token_hours"):
        dom.setdefault(t, {})[h] = v
    dom = {t: dominant(shares(hs)) for t, hs in dom.items()}
    rows = {}

    def add(key, mx):
        rows.setdefault(key, []).append(mx)

    for ts, mx, tok, st in calls:
        s = session_of(ts)
        add(f"call:{s}", mx)
        if dom.get(tok) in NAMES:
            add(f"vol:{dom[tok]}", mx)
        reg = json.loads(st or "{}").get("region")
        if reg:
            add("match:yes" if reg == s else "match:no", mx)
    for ts, mx in con.execute("SELECT start_ts, max24 FROM groups WHERE good_authors >= 1 AND dev_selling = 0 "
                              "AND max24 IS NOT NULL"):
        add(f"signal:{session_of(ts)}", mx)
    base = {}
    for kind in ("call", "signal", "vol", "match"):
        xs = [m for k, v in rows.items() if k.startswith(kind + ":") for m in v]
        base[kind] = sum(1 for m in xs if m >= hx) / len(xs) if xs else None
    con.execute("DELETE FROM sessions")
    for key, xs in rows.items():
        hits = sum(1 for m in xs if m >= hx)
        con.execute("INSERT INTO sessions VALUES (?,?,?,?,?,?)",
                    (key, len(xs), hits, statistics.median(xs), _factor(hits, len(xs), base[key.split(':')[0]], cfg),
                     now))
    return len(rows)


def factors(con):
    """{session: signal factor}, from the KOL group signal accuracy, else from all calls, else 1."""
    f = {s: 1.0 for s, _, _ in SESSIONS}
    got = dict(con.execute("SELECT key, factor FROM sessions"))
    for s in f:
        f[s] = got.get(f"signal:{s}", got.get(f"call:{s}", 1.0))
    live = live_pf()
    for s, pf in live.items():
        if s in f and pf is not None and pf < 1.0:
            # 11.11. (jutarnji izvještaj): Asia had a live demo profit factor of 0.12 while its KOL call factor (peak
            # +hit_x in 24 h after the call) still favoured it. What the demo really earned in a session now caps
            # the factor: PF under 1 multiplies it by max(0.5, PF), so a losing session can never look better
            # than an even one.
            f[s] = round(max(0.35, min(f[s], 1.0) * max(0.5, pf)), 3)
    return f


def live_pf(min_n=30):
    """{session: profit factor} of closed demo trades from paper/rules.session_sizes (last 7 days, refreshed every
    few hours), only sessions with at least min_n trades. {} when the demo has not measured yet."""
    try:
        from paper import rules
        by = ((rules.load().get("sessions") or {}).get("by")) or {}
    except Exception:  # noqa: BLE001 - KOL scoring must not depend on the demo
        return {}
    return {s: v.get("pf") for s, v in by.items() if (v.get("n") or 0) >= min_n}


def backfill_due(con, limit):
    """Measured tokens without hourly volume yet (calls from before token_hours existed), most called first."""
    return [r[0] for r in con.execute("""
        SELECT c.token FROM calls c JOIN tokens t ON t.token = c.token
        WHERE t.pair IS NOT NULL AND c.p0 IS NOT NULL AND c.token NOT IN (SELECT DISTINCT token FROM token_hours)
        GROUP BY c.token ORDER BY COUNT(*) DESC LIMIT ?""", (limit,))]


def backfill(con, cfg, fetch, now=None, budget_s=None):
    """Hourly volume for up to sessions.hours_backfill tokens per run (free GeckoTerminal, shared throttle), within
    budget_s seconds (sessions.backfill_budget_s, default 60): 9.11. it held the KOL round for 10+ minutes."""
    now = now or int(time.time())
    budget = budget_s if budget_s is not None else cfg.get("sessions", {}).get("backfill_budget_s", 60)
    stop_at = time.monotonic() + budget
    n = 0
    for tok in backfill_due(con, cfg.get("sessions", {}).get("hours_backfill", 15)):
        if n and time.monotonic() > stop_at:
            break
        pair, = con.execute("SELECT pair FROM tokens WHERE token = ?", (tok,)).fetchone()
        lo, hi = con.execute("SELECT MIN(ts), MAX(ts) FROM calls WHERE token = ?", (tok,)).fetchone()
        try:
            candles = fetch(pair, lo - 2 * H, min(now, hi + 24 * H))
        except Exception:
            candles = []
        if candles:
            save_hours(con, tok, candles, now)
        else:  # nothing to learn from: mark so it is not retried every run
            con.execute("INSERT OR REPLACE INTO token_hours VALUES (?,?,?,?)", (tok, -1, 0.0, now))
        n += 1
    con.commit()
    return n


def now_info(con=None, now=None):
    """What the entry and exit logic can use: current session, its learned factor and accuracy."""
    now = now or int(time.time())
    s = session_of(now)
    out = {"session": s, "factor": 1.0, "signal_hit_rate": None, "signal_n": 0}
    if con is not None:
        try:
            out["factor"] = factors(con)[s]
            r = con.execute("SELECT n, hits FROM sessions WHERE key = ?", (f"signal:{s}",)).fetchone()
            if r and r[0]:
                out["signal_n"], out["signal_hit_rate"] = r[0], r[1] / r[0]
        except Exception:
            pass
    return out
