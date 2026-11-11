"""Ekipe callera i skriveni popisi novčanika (10.11., Jure: zastavica group_discovery, G12; start u sjeni).

Two kinds of groups, measured from our own databases first; nothing here buys, sells or changes live scoring:

1) Caller groups. kol.db calls (X + Telegram, last `days`), the FIRST call of every account per token. For every
   pair of accounts: shared tokens called within 120 s and within 10 min, against the random expectation
       expected_w = n_a * n_b / U * f_w
   (n_a, n_b: tokens each account called, U: tokens anybody called, f_w: share of ALL same-token caller pairs that
   came within w seconds of each other), lift_w = shared_w / expected_w. A link is a pair with >= min_shared shared
   tokens and lift >= min_lift in either window; a group is a connected component of links (kol/together.components).
   Per group, over its events (2+ members called the token within 10 min): who calls first, market cap at the first
   member call, the result 1 h / 4 h / 24 h after it (kol.db r1h, r24h; 4 h from minute.db candles when kept), rug
   share, and the delay of the public calls (anybody outside the group) behind the first. Grade: quality (11.11.:
   >= 8 events measured at 1 h, 4 h and 24 h, r4h_med > 0, r24h_med > -30 %, EV after cost > 0 at 1 h and 4 h),
   exit_liquidity (the first public call falls in its first hour), bad, or insufficient_data; every grade is shown
   with n_measured, and saved groups are graded again by today's rule when read (grade_of). Also the link density of
   each group (a component chained through pairs is split by kol/preshill.py before it is called a shill network).
   For scoring (shadow only, league/flags.shadow): calls of one group within 10 min are ONE signal (dedupe), and an
   exit_liquidity group weighs -1 (weighted).

2) Wallet groups ("hidden paid lists"). Wallets that bought a token under max_mcap in its first 30 min: early.db
   early_buyers (smart_discovery) and our own Helius cache group_buys (getTransactionsForAddress on the mint, oldest
   first, wallets/rpc.fetch at 10 credits per 100 tx, at most night_credits a pass). A trade is attributed to the
   OWNER whose balance of the mint changed and who signed the transaction, never to the fee payer as such: relayed /
   gasless swaps (Jupiter Ultra, some terminals) are paid by a relayer for many different traders, and a relayer is
   never a member and never links anybody (10.11. Hope research: two relayers "bought" for 153 and 104 wallets).
   A link is a wallet pair that bought >= w_min_shared of the same tokens within slot_gap slots (ts_gap s when a slot
   is unknown). Removed first: dev-funded buys (the dev's own, paid by the dev, or funded by the dev), pairs of one
   owner (same non-hub funder, or a non-relayer fee payer that paid for the other), and bots (> bot_tx_min tx in one
   minute, buy and sell of one mint in one slot, or a bot/mev/sniper label in wallets.db). Groups of >= w_min_size.
   Hidden list signal: >= hidden_min wallets of one QUALITY wallet group buy the same token within 10 min with no
   public call -> group_signals source hidden_group (also in get_market_signals, flag on).

3) Traces without a call: unique buyers in 5 min >= trace_jump x the 5-min rate of the 30 min before, market cap
   under trace_max_mcap, no public call: group_traces, measured later (result, and how late the callers came).

Passes: `python3 -m kol.groupdisc night` (01-06 Zagreb under ops.heavy --night, at most once in 20 h: caller groups,
Helius for early buyers, wallet groups, measurement) and `python3 -m kol.groupdisc incr` every 15 min (our databases
only by default). Own tables (prefix group_) in early.db (EARLY_DB, next to the other databases). With the flag off
every pass ends at once and the MCP tools answer empty: nothing is read, written or paid.

Paper only through the owner's tap and only when paper_refusal() says nothing: the flag 7+ days in shadow and EV > 0
on >= gate_n measured cases (hidden_group signals and first calls of quality caller groups; EV = +tp when +20 % came
before -30 % within 4 h, -30 % when the stop came first, else the 4 h result, minus cost). trade/settings.set_flag
asks it (PAPER_GATES), so it is enforced in code and never automatic. Tokens under $30k are analysed, never bought.
"""
import hashlib
import json
import os
import sqlite3
import statistics
import sys
import time
from collections import Counter, defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FLAG = "group_discovery"
WSOL = "So11111111111111111111111111111111111111112"
PUMP_SUPPLY = 1e9

DEFAULT = {
    # 1) caller groups
    "days": 30, "win_fast_s": 120, "win_s": 600, "min_shared": 3, "min_lift": 5.0, "min_events": 3, "cost": 0.02,
    "r_cap": 3.0, "exit_drop": -0.15, "max_rug": 0.34,
    # 11.11. (Jure): "quality" only on >= q_min_measured measured events at 1 h, 4 h and 24 h, the medians at 4 h above
    # 0 and at 24 h above q_min_r24h, and EV > 0 at 1 h and at 4 h (LiLiStormX was "quality" with r24h -88 % on 6)
    "q_min_measured": 8, "q_min_r24h": -0.3,
    # 2) wallet groups
    "early_s": 1800, "max_mcap": 100_000, "slot_gap": 5, "ts_gap": 2, "w_min_shared": 3, "w_min_size": 4,
    "w_max_size": 40, "bot_tx_min": 50, "relayer_min": 5, "hub_min": 20, "hidden_min": 3, "hidden_window_s": 600,
    # 3) traces
    "trace_jump": 4.0, "trace_min_buyers": 6, "trace_max_mcap": 50_000, "trace_min_age_s": 2100,
    # 5) cost and measurement
    "night_credits": 3000, "pages": 3, "fetch_days": 3, "incr_credits": 0, "incr_day_credits": 500,
    "gt_night": 30, "gt_incr": 0, "night_gap_h": 20, "tp": 0.20, "sl": -0.30, "gate_n": 30, "gate_days": 7,
    "keep_days": 45,
}
GRADES = ("exit_liquidity", "bad", "insufficient_data", "quality")   # worst to best for us: min_quality order
GRADE_HR = {"quality": "kvalitetna", "exit_liquidity": "izlazna likvidnost", "bad": "loša",
            "insufficient_data": "premalo podataka"}
WEIGHT = {"quality": 1.0, "insufficient_data": 1.0, "bad": 0.5, "exit_liquidity": -1.0}
SOURCES = ("hidden_group", "caller_group_first")
BOT_LABELS = {"bot", "mev", "sniper"}
LABEL_SHAPE = {"group_label": {"group_id": "c1a2b3c4d", "label": "kratko ime", "note": "zašto"}}

SCHEMA = """
CREATE TABLE IF NOT EXISTS early_buyers (mint TEXT, wallet TEXT, first_buy_ts INTEGER, sol_in REAL, sold_ts INTEGER,
    sol_out REAL, slot INTEGER, rank INTEGER, PRIMARY KEY (mint, wallet));
CREATE TABLE IF NOT EXISTS group_list (id TEXT PRIMARY KEY, kind TEXT, members TEXT, size INTEGER, grade TEXT,
    metrics TEXT, updated INTEGER);
CREATE TABLE IF NOT EXISTS group_member (member TEXT, kind TEXT, gid TEXT, PRIMARY KEY (member, kind));
CREATE TABLE IF NOT EXISTS group_buys (mint TEXT, wallet TEXT, sig TEXT, ts INTEGER, slot INTEGER, side TEXT,
    sol REAL, tokens REAL, payer TEXT, mcap_usd REAL, PRIMARY KEY (sig, wallet, mint));
CREATE INDEX IF NOT EXISTS group_buys_mint ON group_buys (mint, ts);
CREATE INDEX IF NOT EXISTS group_buys_wallet ON group_buys (wallet, ts);
CREATE TABLE IF NOT EXISTS group_fetched (mint TEXT PRIMARY KEY, ts INTEGER, credits INTEGER, n_tx INTEGER,
    first_ts INTEGER, dev TEXT, complete INTEGER);
CREATE TABLE IF NOT EXISTS group_activity (ts INTEGER, kind TEXT, gid TEXT, token TEXT, who TEXT, mcap_usd REAL,
    public_called INTEGER, PRIMARY KEY (gid, token, who, kind));
CREATE INDEX IF NOT EXISTS group_activity_ts ON group_activity (ts);
CREATE TABLE IF NOT EXISTS group_signals (id INTEGER PRIMARY KEY AUTOINCREMENT, ts INTEGER, source TEXT, gid TEXT,
    token TEXT, who TEXT, mcap_usd REAL, detail TEXT, r1h REAL, r4h REAL, r24h REAL, hit1h INTEGER, hit4h INTEGER,
    ev REAL, first_public_ts INTEGER, measured_ts INTEGER, UNIQUE (source, gid, token));
CREATE INDEX IF NOT EXISTS group_signals_ts ON group_signals (ts);
CREATE TABLE IF NOT EXISTS group_traces (token TEXT, ts INTEGER, buyers5 INTEGER, buyers30 INTEGER, mcap_usd REAL,
    group_wallets INTEGER, r1h REAL, r4h REAL, hit1h INTEGER, hit4h INTEGER, ev REAL, first_public_ts INTEGER,
    measured_ts INTEGER, PRIMARY KEY (token, ts));
CREATE TABLE IF NOT EXISTS group_runs (ts INTEGER, kind TEXT, credits INTEGER, gt INTEGER, detail TEXT);
CREATE TABLE IF NOT EXISTS group_kv (key TEXT PRIMARY KEY, value TEXT);
"""


def config(cfg=None):
    return {**DEFAULT, **((cfg or {}).get(FLAG) or {})}


def db_path():
    """early.db: EARLY_DB, else next to the other databases (start.sh links it to the persistent disk)."""
    return os.environ.get("EARLY_DB") or os.path.join(ROOT, "early.db")


def connect(path=None):
    con = sqlite3.connect(path or db_path(), timeout=60)
    con.executescript(SCHEMA)
    return con


def _ro(path):
    if not path or not os.path.exists(path) or not os.path.getsize(path):
        return None
    try:
        return sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=10)
    except sqlite3.Error:
        return None


def _q(con, sql, args=()):
    if con is None:
        return []
    try:
        return con.execute(sql, args).fetchall()
    except sqlite3.Error:
        return []


def paths(**over):
    """Every database this module reads, by the same rule the owning modules use (tests pass their own)."""
    from kol import store as kstore
    from wallets import store as wstore
    out = {"kol_db": kstore.DB, "hype_db": os.environ.get("HYPE_DB") or os.path.join(ROOT, "hype.db"),
           "tg_db": os.environ.get("TG_DB") or os.path.join(ROOT, "tg.db"), "wallet_db": wstore.DB,
           "rug_db": os.environ.get("RUG_DB") or os.path.join(ROOT, "rug.db"), "early_db": db_path()}
    try:
        from kol import minute
        out["minute_db"] = minute.db_path()
    except Exception:  # noqa: BLE001
        out["minute_db"] = None
    try:
        from league import store as lstore
        out["league_db"] = lstore.DB
    except Exception:  # noqa: BLE001
        out["league_db"] = None
    out.update({k: v for k, v in over.items() if v is not None})
    return out


def mode(trade_db=None):
    """The flag's mode; "off" when trade settings cannot be read (the safe side)."""
    try:
        from trade import settings
        return settings.flag(FLAG, path=trade_db)
    except Exception:  # noqa: BLE001
        return "off"


def gid_of(kind, members):
    return kind[0] + hashlib.sha1(",".join(sorted(members)).encode()).hexdigest()[:9]


def _med(xs):
    xs = [x for x in xs if x is not None]
    return statistics.median(xs) if xs else None


def _mean(xs):
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else None


def _r(x, nd=4):
    return None if x is None else round(float(x), nd)


# ===================================================================================================================
# 1) caller groups
# ===================================================================================================================
BITS = 20          # one pair's count per window, packed into one int (< 1M tokens per window)
ID_SPAN = 1 << 24  # pair key = id_a * ID_SPAN + id_b: ints, not tuples of strings (~5x less memory on the server)


def lift_table(by_token, wins=(120, 600), cand=None, min_n=1):
    """by_token: iterable of [(ts, handle)], the first call of each account on one token. -> (pairs, n_of, U, f):
    pairs {(a, b): {"n": [shared within each window], "exp": [...], "lift": [...]}} (a < b) for pairs with at least
    min_n shared tokens in some window, n_of {handle: tokens}, U tokens, f [share of all same-token caller pairs within
    each window]. cand: only these accounts get a pair row (an account with fewer than min_shared tokens can never
    link). 10.11.: 124k calls / 200k pairs took 126 MB as a dict of string tuples; packed ints take a fraction."""
    n_of, near, cnt, ids = Counter(), [0] * len(wins), {}, {}
    u = total = 0
    wmax = max(wins)
    for calls in by_token:
        calls = sorted(calls)
        k = len(calls)
        if not k:
            continue
        u += 1
        total += k * (k - 1) // 2
        for _, h in calls:
            n_of[h] += 1
        for i in range(k):
            ti, hi = calls[i]
            for j in range(i + 1, k):
                tj, hj = calls[j]
                dt = tj - ti
                if dt > wmax:
                    break
                inc = 0
                for x, w in enumerate(wins):
                    if dt <= w:
                        near[x] += 1
                        inc += 1 << (BITS * x)
                if cand is not None and (hi not in cand or hj not in cand):
                    continue
                a = ids.setdefault(hi, len(ids))
                b = ids.setdefault(hj, len(ids))
                key = a * ID_SPAN + b if a < b else b * ID_SPAN + a
                cnt[key] = cnt.get(key, 0) + inc
    f = [n / total if total else 0.0 for n in near]
    name = {i: h for h, i in ids.items()}
    del ids
    mask = (1 << BITS) - 1
    out = {}
    for key, v in cnt.items():
        c = [(v >> (BITS * x)) & mask for x in range(len(wins))]
        if max(c) < min_n:
            continue
        a, b = sorted((name[key // ID_SPAN], name[key % ID_SPAN]))
        base = n_of[a] * n_of[b] / u if u else 0.0
        exp = [base * fx for fx in f]
        out[(a, b)] = {"n": c, "exp": [round(e, 4) for e in exp],
                       "lift": [round(n / e, 2) if e > 0 else None for n, e in zip(c, exp)]}
    return out, n_of, u, f


def links(table, min_shared=3, min_lift=5.0):
    """Pairs with min_shared+ shared tokens and lift >= min_lift in at least one window."""
    return [ab for ab, s in table.items()
            if any(n >= min_shared and (lf or 0) >= min_lift for n, lf in zip(s["n"], s["lift"]))]


def components(pairs):
    from kol import together
    return together.components(pairs)


def group_events(calls, members, win=600):
    """calls: [dict(ts, handle, mcap0, r1h, r4h, r24h, rug)] first call per account on ONE token, sorted by ts.
    -> the group's event on it or None: 2+ members within `win` of the first member call."""
    mem = [c for c in calls if c["handle"] in members]
    if len(mem) < 2 or mem[1]["ts"] - mem[0]["ts"] > win:
        return None
    first = mem[0]
    order = [c["handle"] for c in mem if c["ts"] - first["ts"] <= win]
    pub_after = [c for c in calls if c["handle"] not in members and c["ts"] > first["ts"]
                 and c["ts"] - first["ts"] <= 86400]
    pub_before = any(c["handle"] not in members and c["ts"] < first["ts"] for c in calls)
    p = pub_after[0] if pub_after else None
    return {"ts": first["ts"], "first": first["handle"], "order": order, "mcap0": first.get("mcap0"),
            "r1h": first.get("r1h"), "r4h": first.get("r4h"), "r24h": first.get("r24h"),
            "rug": bool(first.get("rug")) or (first.get("r24h") is not None and first["r24h"] <= -0.9),
            "pub_delay_s": (p["ts"] - first["ts"]) if p else None, "pub_r1h": p.get("r1h") if p else None,
            "group_first": not pub_before}


def caller_metrics(events, c):
    """Aggregate of a group's events (group_events) -> metrics dict with the grade."""
    n = len(events)
    firsts = Counter(e["first"] for e in events)
    rank = defaultdict(list)
    for e in events:
        for i, h in enumerate(e["order"]):
            rank[h].append(i)
    r1 = [min(e["r1h"], c["r_cap"]) for e in events if e["r1h"] is not None]
    r4 = [min(e["r4h"], c["r_cap"]) for e in events if e.get("r4h") is not None]
    n24 = sum(1 for e in events if e.get("r24h") is not None)
    pub = [e["pub_r1h"] for e in events if e["pub_r1h"] is not None]
    m = {"events": n, "first_counts": dict(firsts.most_common()),
         "typical_order": sorted(rank, key=lambda h: (statistics.mean(rank[h]), -firsts.get(h, 0))),
         "mcap_first_med": _r(_med(e["mcap0"] for e in events), 0),
         "r1h_med": _r(_med(e["r1h"] for e in events)), "r4h_med": _r(_med(e["r4h"] for e in events)),
         "r24h_med": _r(_med(e["r24h"] for e in events)),
         "ev_1h": _r(sum(r1) / len(r1) - c["cost"]) if r1 else None, "n_measured": len(r1),
         "ev_4h": _r(sum(r4) / len(r4) - c["cost"]) if r4 else None, "n_measured_4h": len(r4), "n_measured_24h": n24,
         "rug_share": _r(sum(e["rug"] for e in events) / n, 3) if n else None,
         "public_delay_min_med": _r((_med(e["pub_delay_s"] for e in events) or 0) / 60, 1)
         if any(e["pub_delay_s"] is not None for e in events) else None,
         "public_r1h_med": _r(_med(pub)), "n_public": len(pub),
         "group_first_share": _r(sum(e["group_first"] for e in events) / n, 3) if n else None}
    m["grade"] = caller_grade(m, c)
    return m


def caller_grade(m, c):
    """exit_liquidity | bad | insufficient_data | quality. 11.11. (Jure): quality needs q_min_measured (8) measured
    events at 1 h, 4 h and 24 h, r4h_med > 0, r24h_med > q_min_r24h (-30 %) and EV > 0 at 1 h AND at 4 h. One bad
    number on min_events (3) measured events is enough for "bad" (a -88 % median at 24 h on 6 events is no quality
    group); good numbers on fewer than 8 stay insufficient_data. Metrics saved before 11.11. have no 4 h EV: they can
    be bad, never quality, until the next night pass measures them again."""
    if m["events"] < c["min_events"] or m["ev_1h"] is None or m["n_measured"] < c["min_events"]:
        return "insufficient_data"
    if m["n_public"] >= c["min_events"] and m["public_r1h_med"] is not None and m["public_r1h_med"] <= c["exit_drop"]:
        return "exit_liquidity"
    r4, r24, ev4 = m.get("r4h_med"), m.get("r24h_med"), m.get("ev_4h")
    if (m["ev_1h"] <= 0 or (m["rug_share"] or 0) >= c["max_rug"] or (r4 is not None and r4 <= 0)
            or (r24 is not None and r24 <= c["q_min_r24h"]) or (ev4 is not None and ev4 <= 0)):
        return "bad"
    q = c["q_min_measured"]
    if (m["n_measured"] < q or (m.get("n_measured_4h") or 0) < q or (m.get("n_measured_24h") or 0) < q
            or r4 is None or r24 is None or ev4 is None):
        return "insufficient_data"
    return "quality"


def n_measured_of(kind, met):
    """The number of measured cases behind a grade: caller groups their events with a 1 h result, wallet groups their
    closed positions."""
    met = met if isinstance(met, dict) else {}
    return met.get("n_measured") if kind == "caller" else met.get("n_closed")


def grade_of(kind, grade, met, c=None):
    """The grade by today's rule: caller groups are graded again from their saved metrics (a group saved under an
    older rule must not stay "quality" until the next night pass); anything unreadable keeps its saved grade."""
    if kind != "caller":
        return grade
    if isinstance(met, str):
        try:
            met = json.loads(met or "{}")
        except ValueError:
            return grade
    if not isinstance(met, dict) or "ev_1h" not in met or "events" not in met:
        return grade
    try:
        return caller_grade(met, c or config())
    except (KeyError, TypeError):
        return grade


def grade_text(grade, n):
    """'kvalitetna (n=9)': the grade in Croatian with the measured cases behind it."""
    return f"{GRADE_HR.get(grade, grade or '?')} (n={n if n is not None else 0})"


def link_density(members, n_links, deg, k=3):
    """{"n_links", "density" (share of member pairs that are linked), "deg_med", "deg_ge3_share" (members with >= k
    links)} of one group."""
    n = len(members)
    ds = sorted(deg.get(h, 0) for h in members)
    return {"n_links": n_links, "density": _r(2 * n_links / (n * (n - 1)), 4) if n > 1 else None,
            "deg_med": _med(ds), "deg_ge3_share": _r(sum(1 for d in ds if d >= k) / n, 3) if n else None}


def dedupe(calls, member_of, window=600):
    """calls [(ts, handle)] of ONE token -> signals [{"ts", "handles", "gid"}]: the calls of one caller group within
    `window` of that group's first call are one signal; every other account is its own signal (an account repeating
    itself counts once)."""
    out, open_, seen = [], {}, set()
    for ts, h in sorted(calls):
        g = member_of.get(h)
        if g:
            s = open_.get(g)
            if s and ts - s["ts"] <= window:
                if h not in s["handles"]:
                    s["handles"].append(h)
                continue
            s = {"ts": ts, "handles": [h], "gid": g}
            open_[g] = s
            out.append(s)
        elif h not in seen:
            seen.add(h)
            out.append({"ts": ts, "handles": [h], "gid": None})
    return out


def weighted(signals, grades):
    """Sum of the signals' weights: an exit_liquidity group counts -1, a bad one 0.5, the rest 1."""
    return round(sum(WEIGHT.get(grades.get(s["gid"]), 1.0) if s["gid"] else 1.0 for s in signals), 2)


def _first_calls_stream(kcon, since, bots, extra=False):
    """Yields (token, [dict]) of first calls per account, oldest first, token by token (one token in memory)."""
    cols = "token, handle, ts, mcap0, r1h, r24h, COALESCE(rug, 0)"
    cur = kcon.execute(f"SELECT {cols} FROM calls WHERE kind = 'call' AND ts >= ? AND bad IS NULL "
                       "ORDER BY token, ts", (int(since),))
    tok, seen, rows = None, set(), []
    for t, h, ts, mc, r1, r24, rug in cur:
        if t != tok:
            if rows:
                yield tok, rows
            tok, seen, rows = t, set(), []
        if h in seen or h in bots:
            continue
        seen.add(h)
        rows.append({"handle": h, "ts": int(ts), "mcap0": mc, "r1h": r1, "r24h": r24, "rug": rug} if extra
                    else (int(ts), h))
    if rows:
        yield tok, rows


def _r4h(mcon, token, ts):
    """The 4 h result after a call from minute.db call_candles (kept 240 min after every call), or None."""
    if mcon is None:
        return None
    try:
        from kol import minute
        cs = minute.candles_for(mcon, token, ts - 60, ts + 4 * 3600)
    except Exception:  # noqa: BLE001
        return None
    o = path_outcome(cs, ts, {"tp": 9e9, "sl": -9e9, "cost": 0.0})
    return o["r4h"] if o else None


def build_caller_groups(kcon, c, now, mcon=None):
    """Caller groups of the last c["days"] -> [(gid, members in typical order, metrics)] (not saved here)."""
    try:
        return _build_caller_groups(kcon, c, now, mcon)
    except sqlite3.OperationalError as e:   # an old kol.db without a column: no groups this night, the pass goes on
        print(f"grupe: ekipe callera nisu izračunate ({e})", flush=True)
        return []


def _build_caller_groups(kcon, c, now, mcon=None):
    from kol import bots as kbots
    since = now - c["days"] * 86400
    bots = kbots.handles(kcon)
    cand = {h for h, n in _q(kcon, "SELECT handle, COUNT(DISTINCT token) FROM calls WHERE kind = 'call' AND ts >= ? "
                                   "AND bad IS NULL GROUP BY handle", (since,)) if n >= c["min_shared"]} - bots
    wins = (c["win_fast_s"], c["win_s"])
    table, n_of, u, f = lift_table((rows for _t, rows in _first_calls_stream(kcon, since, bots)), wins, cand,
                                   min_n=c["min_shared"])
    lk = links(table, c["min_shared"], c["min_lift"])
    groups = [g for g in components(lk) if len(g) >= 2]
    if not groups:
        return []
    member_of = {h: i for i, g in enumerate(groups) for h in g}
    n_links, deg = Counter(), Counter()
    for a, b in lk:
        n_links[member_of[a]] += 1
        deg[a] += 1
        deg[b] += 1
    del lk
    in_group = defaultdict(list)
    for (a, b), s in table.items():
        if a in member_of and member_of[a] == member_of.get(b):
            in_group[member_of[a]].append({"a": a, "b": b, "shared_120s": s["n"][0], "shared_10min": s["n"][1],
                                           "lift_120s": s["lift"][0], "lift_10min": s["lift"][1]})
    del table
    events = defaultdict(list)
    for tok, rows in _first_calls_stream(kcon, since, bots, extra=True):
        here = {member_of[r["handle"]] for r in rows if r["handle"] in member_of}
        for i in here:
            e = group_events(rows, groups[i], c["win_s"])
            if e:
                if mcon is not None:
                    e["r4h"] = _r4h(mcon, tok, e["ts"])
                e["token"] = tok
                events[i].append(e)
    out = []
    for i, g in enumerate(groups):
        m = caller_metrics(events[i], c)
        m["pairs"] = sorted(in_group[i], key=lambda x: -x["shared_10min"])[:30]
        m["tokens"] = [e["token"] for e in sorted(events[i], key=lambda e: -e["ts"])][:20]
        m["base_rate"] = {"tokens": u, "f_120s": _r(f[0], 5), "f_10min": _r(f[1], 5)}
        # 11.11.: how tightly the members are linked: a component linked through chains (A~B, B~C ...) is not one
        # crew; kol/preshill.py splits such a component before it calls any part of it a shill network
        m.update(link_density(g, n_links[i], deg))
        out.append((gid_of("caller", g), sorted(g, key=lambda h: m["typical_order"].index(h)
                                                if h in m["typical_order"] else 99), m))
    return out


# ===================================================================================================================
# 2) wallet groups
# ===================================================================================================================
def owner_trades(tx, mint):
    """One raw getTransactionsForAddress tx -> ([(owner, side, tokens, sol)], payer, signers): every SIGNER whose
    balance of `mint` changed, with its own SOL change (lamports + WSOL); sol is spent (buy) or received (sell).
    The fee payer is NOT the trader when it is not among them (relayed / gasless swap); a pool or bonding curve never
    signs, so it never shows up as a trader."""
    meta = tx.get("meta") or {}
    msg = (tx.get("transaction") or {}).get("message") or {}
    raw = msg.get("accountKeys") or []
    keys = [k.get("pubkey") if isinstance(k, dict) else k for k in raw]
    payer = keys[0] if keys else None
    if meta.get("err") or not keys:
        return [], payer, set()
    signers = {k.get("pubkey") for k in raw if isinstance(k, dict) and k.get("signer")} or {payer}
    tok, wsol = {}, {}
    for sign, side in ((-1, "preTokenBalances"), (1, "postTokenBalances")):
        for b in meta.get(side) or []:
            o, m = b.get("owner"), b.get("mint")
            if not o or m not in (mint, WSOL):
                continue
            ui = b.get("uiTokenAmount") or {}
            try:
                amt = int(ui.get("amount") or 0) / 10 ** int(ui.get("decimals") or 0)
            except (TypeError, ValueError):
                continue
            d = tok if m == mint else wsol
            d[o] = d.get(o, 0.0) + sign * amt
    pre, post = meta.get("preBalances") or [], meta.get("postBalances") or []
    out = []
    for o, d in tok.items():
        if abs(d) < 1e-9 or o not in signers:
            continue
        sol = wsol.get(o, 0.0)
        if o in keys:
            i = keys.index(o)
            if i < len(pre) and i < len(post):
                sol += (post[i] - pre[i]) / 1e9
        out.append((o, "buy" if d > 0 else "sell", abs(d), round(-sol if d > 0 else sol, 9)))
    return out, payer, signers


def relayers(paid, min_owners=5):
    """paid: iterable of (payer, owner) where a fee payer paid for a trade that was not its own -> payers that did it
    for min_owners+ different owners: relayers, never a member, never a link, never "the same owner"."""
    by = defaultdict(set)
    for p, o in paid:
        if p and o and p != o:
            by[p].add(o)
    return {p for p, os_ in by.items() if len(os_) >= min_owners}


def bots(trades, max_per_min=50, labels=None):
    """trades: (wallet, mint, ts, slot, side) -> wallets that look automated: more than max_per_min trades in one
    minute, a buy and a sell of one mint in the same slot (sandwich / MEV), or a bot/mev/sniper label (wallets.db)."""
    per_min, slot_sides = Counter(), defaultdict(set)
    for w, m, ts, slot, side in trades:
        per_min[(w, int(ts or 0) // 60)] += 1
        if slot is not None:
            slot_sides[(w, m, slot)].add(side)
    out = {w for (w, _), n in per_min.items() if n > max_per_min}
    out |= {w for (w, _m, _s), sides in slot_sides.items() if {"buy", "sell"} <= sides}
    out |= {w for w, labs in (labels or {}).items() if set(labs) & BOT_LABELS}
    return out


def bots_sql(con, hcon, since, c):
    """The two rate rules of bots() counted inside SQLite (early.db group_buys and hype.db live_trades, read-only;
    hcon is closed here), so the night pass never holds every trade in Python."""
    out = {w for (w,) in _q(con, "SELECT DISTINCT wallet FROM group_buys WHERE ts >= ? GROUP BY wallet, ts / 60 "
                                 "HAVING COUNT(*) > ?", (since, c["bot_tx_min"]))}
    out |= {w for (w,) in _q(con, "SELECT DISTINCT wallet FROM group_buys WHERE ts >= ? AND slot IS NOT NULL "
                                  "GROUP BY wallet, mint, slot HAVING COUNT(DISTINCT side) > 1", (since,))}
    if hcon is not None:
        out |= {w for (w,) in _q(hcon, "SELECT DISTINCT wallet FROM live_trades GROUP BY wallet, ts / 60 "
                                       "HAVING COUNT(*) > ?", (c["bot_tx_min"],))}
        hcon.close()
    return out


def owner_ids(funders, hubs=frozenset(), skip=frozenset()):
    """funders: {wallet: set(funder)} -> {wallet: owner id}: wallets that share a funder (not a hub, not a relayer:
    `skip`), or one funded the other, are one owner. Wallets without such a tie are their own owner."""
    from kol import together
    pairs = []
    for w, fs in funders.items():
        for f in fs:
            if f and f not in hubs and f not in skip and f != w:
                pairs.append((w, f))
    out = {}
    for comp in together.components(pairs):
        oid = min(comp)
        for w in comp:
            out[w] = oid
    return out


def wallet_links(buys, c, skip=frozenset(), owner=None, removed=frozenset()):
    """buys: iterable of (mint, wallet, ts, slot), the FIRST buy of a wallet on a mint in its first 30 min, any
    order within a mint but grouped by mint. -> {(a, b): tokens} for pairs that bought within slot_gap slots (ts_gap
    seconds when a slot is unknown) of each other. skip: bots and relayers; owner: {wallet: owner id}: one owner's
    wallets (a same-funder bundle) are ONE buyer under its owner id, never a link between themselves; removed:
    {(mint, wallet)} dev-funded buys. The nodes of the answer are owner ids (a wallet without a tie is its own)."""
    owner = owner or {}
    cnt, ids = {}, {}

    def flush(rows):
        rows.sort(key=lambda r: r[1])
        for i in range(len(rows)):
            wi, ti, si = rows[i]
            for j in range(i + 1, len(rows)):
                wj, tj, sj = rows[j]
                if tj - ti > c["ts_gap"] + 2:
                    break
                near = abs(sj - si) <= c["slot_gap"] if si is not None and sj is not None else tj - ti <= c["ts_gap"]
                if near and wi != wj:
                    key = wi * ID_SPAN + wj if wi < wj else wj * ID_SPAN + wi
                    cnt[key] = cnt.get(key, 0) + 1

    cur, rows, seen = None, [], set()
    for mint, w, ts, slot in buys:
        if mint != cur:
            flush(rows)
            cur, rows, seen = mint, [], set()
        if w in skip or (mint, w) in removed:
            continue
        node = ids.setdefault(owner.get(w, w), len(ids))
        if node in seen:
            continue
        seen.add(node)
        rows.append((node, int(ts or 0), slot))
    flush(rows)
    name = {i: x for x, i in ids.items()}
    out = {}
    for key, n in cnt.items():
        if n >= c["w_min_shared"]:
            a, b = sorted((name[key // ID_SPAN], name[key % ID_SPAN]))
            out[(a, b)] = n
    return out


def wallet_groups(link_counts, c):
    """Components of wallet links with w_min_size..w_max_size members (bigger ones are sniper networks)."""
    return [g for g in components(list(link_counts)) if c["w_min_size"] <= len(g) <= c["w_max_size"]]


def wallet_metrics(members, buys, sells, first_call, pub_r1h, realized, c):
    """buys [(mint, wallet, ts, sol_in, mcap_usd)] of the members; sells {(mint, wallet): (ts, sol_out)};
    first_call {mint: ts of its first public call}; pub_r1h {mint: 1 h result of that call}; realized {wallet:
    realized SOL from wallets.db}. -> metrics with the grade."""
    by_mint = defaultdict(list)
    for m, w, ts, sol, mc in buys:
        if w in members:
            by_mint[m].append((ts, w, sol, mc))
    toks = {m: sorted(rs) for m, rs in by_mint.items() if len({w for _, w, _, _ in rs}) >= 2}
    pnl = {w: {"sol_in": 0.0, "sol_out": 0.0, "closed": 0} for w in members}
    rois, before, exit_sells = [], [], 0
    for m, rs in toks.items():
        for ts, w, sol, _mc in rs:
            s = sells.get((m, w))
            if s and sol:
                pnl[w]["sol_in"] += sol
                pnl[w]["sol_out"] += s[1] or 0.0
                pnl[w]["closed"] += 1
                rois.append((s[1] or 0.0) / sol - 1)
                if m in first_call and 0 <= s[0] - first_call[m] <= 7200:
                    exit_sells += 1
        if m in first_call and first_call[m] > rs[0][0]:
            before.append((first_call[m] - rs[0][0]) / 60)
    pub = [pub_r1h[m] for m in toks if pub_r1h.get(m) is not None]
    met = {"tokens": len(toks), "token_list": sorted(toks, key=lambda m: -toks[m][0][0])[:20],
           "entry_mcap_med": _r(_med(mc for rs in toks.values() for *_x, mc in rs), 0),
           "pnl_per_wallet": {w: {"sol_in": _r(p["sol_in"]), "sol_out": _r(p["sol_out"]),
                                  "pnl_sol": _r(p["sol_out"] - p["sol_in"]), "closed": p["closed"],
                                  "realized_total_sol": _r(realized.get(w))} for w, p in sorted(pnl.items())},
           "roi_med": _r(_med(rois)), "n_closed": len(rois),
           "entry_before_first_call_min_avg": _r(_mean(before), 1), "n_called": len(before),
           "public_r1h_med": _r(_med(pub)), "n_public": len(pub), "sells_into_calls": exit_sells}
    met["grade"] = wallet_grade(met, c)
    return met


def wallet_grade(m, c):
    if m["tokens"] < c["w_min_shared"]:
        return "insufficient_data"
    if m["n_public"] >= c["min_events"] and (m["public_r1h_med"] or 0) <= c["exit_drop"] and m["sells_into_calls"]:
        return "exit_liquidity"
    if m["n_closed"] < c["min_events"]:
        return "insufficient_data"
    return "quality" if (m["roi_med"] or 0) > 0 else "bad"


def hidden_signals(buys, member_of, grades, called, c, owner_of=None):
    """buys: [(mint, wallet, ts, mcap_usd)] recent buys -> [{"token", "gid", "wallets", "ts", "mcap_usd"}]: at least
    hidden_min members (distinct owners: owner_of {wallet: owner id}) of ONE quality wallet group bought the token
    within hidden_window_s, and nobody called it (called: tokens with a public call). ts = the buy that completed it."""
    owner_of = owner_of or {}
    by = defaultdict(list)
    for m, w, ts, mc in buys:
        g = member_of.get(w)
        if g and grades.get(g) == "quality" and m not in called:
            by[(m, g)].append((int(ts), w, mc))
    out = []
    for (m, g), rs in by.items():
        first = {}
        for ts, w, mc in sorted(rs):
            first.setdefault(owner_of.get(w, w), (ts, w, mc))
        seq = sorted(first.values())
        for i in range(len(seq) - c["hidden_min"] + 1):
            win = seq[i:i + c["hidden_min"]]
            t0 = win[0][0]
            if win[-1][0] - t0 <= c["hidden_window_s"]:
                out.append({"token": m, "gid": g, "ts": win[-1][0],
                            "wallets": [w for t, w, _mc in seq if t0 <= t <= t0 + c["hidden_window_s"]],
                            "mcap_usd": next((x[2] for x in reversed(win) if x[2]), None)})
                break
    return out


def traces(buys, now, c, called=frozenset(), mcap_of=None, first_seen=None):
    """buys: [(mint, wallet, ts)] of the last 35 min -> [{"token", "buyers5", "buyers30", "mcap_usd"}]: unique
    buyers in the last 5 min >= trace_jump x the 5-min rate of the 30 min before (at least trace_min_buyers), market
    cap known and under trace_max_mcap, the token older than trace_min_age_s (a fresh launch is no trace), no call."""
    mcap_of, first_seen = mcap_of or {}, first_seen or {}
    b5, b30 = defaultdict(set), defaultdict(set)
    for m, w, ts in buys:
        if now - 300 <= ts <= now:
            b5[m].add(w)
        elif now - 2100 <= ts < now - 300:
            b30[m].add(w)
    out = []
    for m, ws in b5.items():
        if m in called or len(ws) < c["trace_min_buyers"]:
            continue
        mc = mcap_of.get(m)
        if mc is None or mc >= c["trace_max_mcap"]:
            continue
        if now - first_seen.get(m, now) < c["trace_min_age_s"]:
            continue
        if len(ws) >= c["trace_jump"] * max(len(b30[m]) / 6, 1):
            out.append({"token": m, "buyers5": len(ws), "buyers30": len(b30[m]), "mcap_usd": mc})
    return out


# ===================================================================================================================
# measurement and the paper gate
# ===================================================================================================================
def trade_candles(rows):
    """[(ts, price)] trades -> 1-minute candles [(t, o, h, l, c, v)] (v = trades), oldest first."""
    by = {}
    for ts, px in sorted(rows):
        if not px or px <= 0:
            continue
        t = int(ts) - int(ts) % 60
        cd = by.get(t)
        by[t] = [t, px, px, px, px, 1] if cd is None else [t, cd[1], max(cd[2], px), min(cd[3], px), px, cd[5] + 1]
    return [tuple(v) for _, v in sorted(by.items())]


def path_outcome(candles, ts, c):
    """From 1-minute candles: entry = close of the signal's minute (else the open of the first candle within 5 min),
    then within 4 h the first minute +tp was touched (a wick counts up to 3x the body) and the first minute the low
    reached sl. -> {"r1h", "r4h", "hit1h", "hit4h", "ev"} or None without an entry. ev: +tp when the target came first,
    sl when the stop came first, else the 4 h result; minus cost."""
    m0 = int(ts) - int(ts) % 60
    cs = sorted(candles)
    cur = next((x for x in cs if x[0] == m0), None)
    if cur:
        entry = cur[4]
    else:
        nxt = next((x for x in cs if m0 < x[0] <= m0 + 300), None)
        if not nxt:
            return None
        entry = nxt[1]
    if not entry or entry <= 0:
        return None
    tp_k = sl_k = None
    last = {60: None, 240: None}
    for t, o, h, lo, cl, *_ in cs:
        if t <= m0 or t > m0 + 240 * 60:
            continue
        k = (t - m0) // 60
        capped = min(h, max(o, cl) * 3)
        if tp_k is None and capped >= entry * (1 + c["tp"]):
            tp_k = k
        if sl_k is None and lo <= entry * (1 + c["sl"]):
            sl_k = k
        for hz in last:
            if k <= hz:
                last[hz] = cl
    r1 = last[60] / entry - 1 if last[60] else None
    r4 = last[240] / entry - 1 if last[240] else None

    def hit(hz):
        return int(tp_k is not None and tp_k <= hz and (sl_k is None or tp_k < sl_k))
    if hit(240):
        ev = c["tp"]
    elif sl_k is not None and (tp_k is None or sl_k <= tp_k):
        ev = c["sl"]
    else:
        ev = r4 if r4 is not None else r1
    return {"r1h": _r(r1), "r4h": _r(r4), "hit1h": hit(60), "hit4h": hit(240),
            "ev": None if ev is None else _r(ev - c.get("cost", 0.0))}


def gate(cases, c):
    """cases: [ev] of measured shadow cases -> None when the move to paper is earned, else the reason (Croatian)."""
    xs = [x for x in cases if x is not None]
    if len(xs) < c["gate_n"]:
        return f"izmjereno tek {len(xs)} od {c['gate_n']} slučajeva (skriveni popisi i prvi pozivi kvalitetnih ekipa)"
    ev = sum(xs) / len(xs)
    if ev <= 0:
        return f"EV {ev:+.1%} na {len(xs)} slučajeva nije iznad nule"
    return None


def paper_refusal(con, now=None, path=None, cfg=None):
    """trade/settings.PAPER_GATES: None when group_discovery may go to paper, else why not. con: trade.db."""
    from trade import settings
    c = config(cfg)
    now = int(now or time.time())
    st = settings.flag_state(con)[FLAG]
    if st["mode"] != "shadow" or not st["since"]:
        return f"prvo najmanje {c['gate_days']} dana u sjeni"
    days = (now - st["since"]) / 86400
    if days < c["gate_days"]:
        return f"u sjeni tek {days:.1f} od {c['gate_days']} dana"
    ec = _ro(path or db_path())
    rows = _q(ec, "SELECT ev FROM group_signals WHERE ev IS NOT NULL AND source IN (?, ?) AND ts >= ?",
              (*SOURCES, st["since"]))
    if ec is not None:
        ec.close()
    return gate([r[0] for r in rows], c)


# ===================================================================================================================
# I/O: Helius early buyers, the passes
# ===================================================================================================================
def _sol_usd():
    try:
        from trade import equity
        return (equity.rates() or {}).get("sol_usd") or 150.0
    except Exception:  # noqa: BLE001
        return 150.0


def fetch_candidates(con, kcon, c, now, extra=()):
    """Mints worth one Helius read of their first 30 min: tokens called in the last fetch_days with the first call
    under max_mcap (most callers first), plus `extra` (trace tokens). Not fetched before by us, and not already in
    early_buyers (smart_discovery's cache)."""
    done = {m for (m,) in _q(con, "SELECT mint FROM group_fetched")}
    done |= {m for m, n in _q(con, "SELECT mint, COUNT(*) FROM early_buyers GROUP BY mint") if n >= 20}
    rows = _q(kcon, """SELECT token, COUNT(DISTINCT handle), MIN(ts) FROM calls WHERE kind = 'call' AND ts >= ?
                       GROUP BY token HAVING MIN(COALESCE(mcap0, 0)) < ? ORDER BY 2 DESC, 3 DESC""",
              (now - c["fetch_days"] * 86400, c["max_mcap"]))
    out = [m for m in extra if m not in done]
    out += [t for t, _n, _ts in rows if t not in done and t not in out]
    return out


def fetch_early(con, mints, c, budget, fetch=None, sol_usd=150.0, log=print, supply=None):
    """Read the first transactions of each mint (oldest first, c["pages"] pages) while the credits allow. Stores
    group_buys (owner-attributed), early_buyers (first buy per wallet, INSERT OR IGNORE: never over smart_discovery's
    rows) and group_fetched. -> (mints read, credits spent)."""
    if fetch is None:
        from wallets import rpc
        fetch = rpc.fetch
    spent = [0]

    def on_credits(n):
        spent[0] += n

    supply = supply or {}
    n = 0
    for mint in mints:
        if spent[0] + c["pages"] * 10 > budget:
            break
        before = spent[0]
        try:
            txs, complete = fetch(mint, max_pages=c["pages"], oldest_first=True, on_credits=on_credits)
        except Exception as e:  # noqa: BLE001 - one mint fails, the pass goes on
            log(f"  grupe: {mint[:6]}… Helius {type(e).__name__}: {str(e)[:80]}")
            continue
        rows, first_ts, dev = [], None, None
        for i, tx in enumerate(sorted(txs, key=lambda t: (t.get("slot") or 0, t.get("blockTime") or 0))):
            ts = tx.get("blockTime") or 0
            first_ts = first_ts or ts
            if first_ts and ts - first_ts > c["early_s"]:
                break
            trades, payer, _sig = owner_trades(tx, mint)
            if i == 0:
                dev = next((o for o, side, *_ in trades if side == "buy"), None) or payer
            sig = ((tx.get("transaction") or {}).get("signatures") or ["?"])[0]
            for o, side, amount, sol in trades:
                mc = (sol / amount) * (supply.get(mint) or PUMP_SUPPLY) * sol_usd if side == "buy" and amount and sol > 0 else None
                rows.append((mint, o, sig, ts, tx.get("slot"), side, sol, amount, payer, _r(mc, 0)))
        con.executemany("INSERT OR IGNORE INTO group_buys VALUES (?,?,?,?,?,?,?,?,?,?)", rows)
        firsts = {}
        for r in rows:
            if r[5] == "buy" and r[1] not in firsts:
                firsts[r[1]] = r
        con.executemany("INSERT OR IGNORE INTO early_buyers (mint, wallet, first_buy_ts, sol_in, slot, rank) "
                        "VALUES (?,?,?,?,?,?)", [(mint, w, r[3], r[6], r[4], k + 1)
                                                for k, (w, r) in enumerate(firsts.items())])
        con.execute("INSERT OR REPLACE INTO group_fetched VALUES (?,?,?,?,?,?,?)",
                    (mint, int(time.time()), spent[0] - before, len(txs), first_ts, dev, int(bool(complete))))
        con.commit()
        n += 1
    return n, spent[0]


def _labels(wallet_db, wallets):
    out = {}
    wc = _ro(wallet_db)
    if wc is None:
        return out
    try:
        ws = list(wallets)
        for i in range(0, len(ws), 500):
            ch = ws[i:i + 500]
            for w, labs in _q(wc, f"SELECT wallet, labels FROM wallets WHERE wallet IN ({','.join('?' * len(ch))})", ch):
                try:
                    out[w] = json.loads(labs or "[]")
                except ValueError:
                    pass
    finally:
        wc.close()
    return out


def _funders(p, mints, wallets):
    """{wallet: set(funder)} for `wallets` from data we already have (no API): wallets.db sightings ("funder" in
    extra) and the rug reports of `mints` (rug.db, newest report per mint, read one at a time)."""
    out = defaultdict(set)
    wc = _ro(p.get("wallet_db"))
    if wc is not None:
        try:
            for w, extra in wc.execute("SELECT wallet, extra FROM wallet_sightings WHERE extra LIKE '%funde%'"):
                if w not in wallets:
                    continue
                try:
                    x = json.loads(extra)
                except ValueError:
                    continue
                if x.get("funder"):
                    out[w].add(x["funder"])
        except sqlite3.Error:
            pass
        finally:
            wc.close()
    rc = _ro(p.get("rug_db"))
    if rc is not None:
        try:
            ms, seen = list(mints), set()
            for i in range(0, len(ms), 400):
                ch = ms[i:i + 400]
                for m, data in rc.execute(f"SELECT mint, data FROM rug_reports WHERE data IS NOT NULL AND mint IN "
                                          f"({','.join('?' * len(ch))}) ORDER BY checked_at DESC", ch):
                    if m in seen:
                        continue
                    seen.add(m)
                    try:
                        d = json.loads(data)
                    except ValueError:
                        continue
                    for x in d.get("wallets") or []:
                        if isinstance(x, dict) and x.get("wallet") in wallets and x.get("funder"):
                            out[x["wallet"]].add(x["funder"])
        except sqlite3.Error:
            pass
        finally:
            rc.close()
    return out


def _realized(wallet_db, wallets):
    out = {}
    wc = _ro(wallet_db)
    if wc is None:
        return out
    try:
        ws = list(wallets)
        for i in range(0, len(ws), 500):
            ch = ws[i:i + 500]
            for w, st in _q(wc, f"SELECT wallet, stats FROM wallets WHERE wallet IN ({','.join('?' * len(ch))})", ch):
                try:
                    v = (json.loads(st or "{}") or {}).get("realized_sol")
                except ValueError:
                    v = None
                if v is not None:
                    out[w] = v
    finally:
        wc.close()
    return out


def _calls_of(kcon, mints):
    """{mint: (first call ts, its r1h)} from kol.db."""
    out = {}
    ms = list(mints)
    for i in range(0, len(ms), 500):
        ch = ms[i:i + 500]
        for t, ts, r1 in _q(kcon, f"SELECT token, ts, r1h FROM calls WHERE kind = 'call' AND token IN "
                                  f"({','.join('?' * len(ch))}) ORDER BY ts DESC", ch):
            out[t] = (ts, r1)   # newest first: the last write is the earliest call
    return out


def build_wallet_groups(con, kcon, p, c, now):
    """Wallet groups from early.db (early_buyers + group_buys of the last `days`) -> ([(gid, members, metrics)],
    relayers). Heavy parts run in SQLite (a temp table) and only wallets with w_min_shared+ tokens reach Python."""
    since = now - c["days"] * 86400
    con.executescript("""DROP TABLE IF EXISTS temp.gb;
        CREATE TEMP TABLE gb (mint TEXT, wallet TEXT, ts INTEGER, slot INTEGER, sol REAL, mcap REAL, payer TEXT);""")
    con.execute("""INSERT INTO temp.gb SELECT b.mint, b.wallet, MIN(b.ts), MIN(b.slot), MAX(b.sol), MIN(b.mcap_usd),
                   MIN(b.payer) FROM group_buys b JOIN group_fetched f ON f.mint = b.mint
                   WHERE b.side = 'buy' AND b.ts >= ? AND b.ts <= f.first_ts + ? AND COALESCE(b.mcap_usd, 0) < ?
                   GROUP BY b.mint, b.wallet""", (since, c["early_s"], c["max_mcap"]))
    con.execute("""INSERT INTO temp.gb SELECT e.mint, e.wallet, e.first_buy_ts, e.slot, e.sol_in, NULL, NULL
                   FROM early_buyers e JOIN (SELECT mint, MIN(first_buy_ts) t0 FROM early_buyers GROUP BY mint) z
                   ON z.mint = e.mint WHERE e.first_buy_ts >= ? AND e.first_buy_ts <= z.t0 + ?
                   AND NOT EXISTS (SELECT 1 FROM temp.gb g WHERE g.mint = e.mint AND g.wallet = e.wallet)""",
                (since, c["early_s"]))
    paid = _q(con, "SELECT DISTINCT payer, wallet FROM group_buys WHERE payer IS NOT NULL AND payer != wallet")
    relay = relayers(paid, c["relayer_min"])
    cand = {w for w, n in _q(con, "SELECT wallet, COUNT(DISTINCT mint) FROM temp.gb GROUP BY wallet")
            if n >= c["w_min_shared"]} - relay
    if not cand:
        con.execute("DROP TABLE IF EXISTS temp.gb")
        return [], relay
    skip = bots_sql(con, _ro(p.get("hype_db")), since, c) & cand
    skip |= bots([], labels=_labels(p.get("wallet_db"), cand)) | relay
    mints = {m for (m,) in _q(con, "SELECT DISTINCT mint FROM temp.gb WHERE wallet IN (SELECT wallet FROM temp.gb "
                                   "GROUP BY wallet HAVING COUNT(DISTINCT mint) >= ?)", (c["w_min_shared"],))}
    funders = _funders(p, mints, cand)
    for pay, w in paid:   # a fee payer that is not a relayer and paid for another wallet's buy funded it (a bundle)
        if w in cand and pay not in relay:
            funders[w].add(pay)
    fan = Counter(f for fs in funders.values() for f in fs)
    hubs = {f for f, n in fan.items() if n > c["hub_min"]}
    owner = owner_ids(funders, hubs, relay)
    # dev-funded: the dev's own buy, a buy the dev paid for, or a wallet the dev funded (tokens of that dev only)
    removed = set(_q(con, "SELECT g.mint, g.wallet FROM temp.gb g JOIN group_fetched f ON f.mint = g.mint "
                          "WHERE f.dev IS NOT NULL AND (g.wallet = f.dev OR g.payer = f.dev)"))
    by_dev = defaultdict(set)
    for m, d in _q(con, "SELECT mint, dev FROM group_fetched WHERE dev IS NOT NULL"):
        by_dev[d].add(m)
    for w, fs in funders.items():
        for f in fs & set(by_dev):
            removed |= {(m, w) for m in by_dev[f]}
    rows = (r for r in con.execute("SELECT mint, wallet, ts, slot FROM temp.gb ORDER BY mint, ts") if r[1] in cand)
    lk = wallet_links(rows, c, skip, owner, removed)
    out = []
    for g in wallet_groups(lk, c):
        wallets = sorted(w for w in cand if owner.get(w, w) in g and w not in skip)
        q = ",".join("?" * len(wallets))
        buys = _q(con, f"SELECT mint, wallet, ts, sol, mcap FROM temp.gb WHERE wallet IN ({q})", wallets)
        buys = [b for b in buys if (b[0], b[1]) not in removed]
        sells = {}
        for m, w, ts, sol in _q(con, f"SELECT mint, wallet, MIN(ts), SUM(sol) FROM group_buys WHERE side = 'sell' "
                                     f"AND wallet IN ({q}) GROUP BY mint, wallet", wallets):
            sells[(m, w)] = (ts, sol)
        for m, w, ts, sol in _q(con, f"SELECT mint, wallet, sold_ts, sol_out FROM early_buyers WHERE sold_ts IS NOT "
                                     f"NULL AND wallet IN ({q})", wallets):
            sells.setdefault((m, w), (ts, sol))
        calls = _calls_of(kcon, {b[0] for b in buys})
        met = wallet_metrics(set(wallets), buys, sells, {k: v[0] for k, v in calls.items()},
                             {k: v[1] for k, v in calls.items()}, _realized(p.get("wallet_db"), wallets), c)
        met["owners"] = len(g)
        met["owner_of"] = {w: owner[w] for w in wallets if owner.get(w, w) != w}
        met["links"] = sorted(([a, b, n] for (a, b), n in lk.items() if a in g and b in g), key=lambda x: -x[2])[:30]
        out.append((gid_of("wallet", g), wallets, met))
    con.execute("DROP TABLE IF EXISTS temp.gb")
    return out, relay


def save_groups(con, kind, groups, now):
    """Replace the groups of one kind (group_list, group_member)."""
    con.execute("DELETE FROM group_list WHERE kind = ?", (kind,))
    con.execute("DELETE FROM group_member WHERE kind = ?", (kind,))
    for gid, members, m in groups:
        con.execute("INSERT OR REPLACE INTO group_list VALUES (?,?,?,?,?,?,?)",
                    (gid, kind, json.dumps(members), len(members), m["grade"], json.dumps(m, ensure_ascii=False), now))
        con.executemany("INSERT OR REPLACE INTO group_member VALUES (?,?,?)", [(x, kind, gid) for x in members])
    con.commit()


def load_groups(con, kind):
    """({member: gid}, {gid: grade}, {wallet: owner id} of one owner's wallets inside wallet groups)."""
    member_of = dict(_q(con, "SELECT member, gid FROM group_member WHERE kind = ?", (kind,)))
    grades, owner_of = {}, {}
    for gid, grade, met in _q(con, "SELECT id, grade, metrics FROM group_list WHERE kind = ?", (kind,)):
        try:
            m = json.loads(met or "{}") or {}
        except ValueError:
            m = {}
        grades[gid] = grade_of(kind, grade, m)   # 11.11.: today's rule, not the one of the night it was saved
        owner_of.update(m.get("owner_of") or {})
    return member_of, grades, owner_of


def _public_first(p, tokens, before=None):
    """{token: first public call ts} (kol.db calls, the live X webhook kol_mentions, Telegram posts)."""
    out = {}
    toks = list(tokens)
    if not toks:
        return out
    q = ",".join("?" * len(toks))
    kc = _ro(p.get("kol_db"))
    for t, ts in _q(kc, f"SELECT token, MIN(ts) FROM calls WHERE kind = 'call' AND token IN ({q}) GROUP BY token", toks):
        out[t] = ts
    if kc is not None:
        kc.close()
    hc = _ro(p.get("hype_db"))
    for t, ts in _q(hc, f"SELECT ca, MIN(ts) FROM kol_mentions WHERE ca IN ({q}) GROUP BY ca", toks):
        out[t] = min(ts, out.get(t, ts))
    if hc is not None:
        hc.close()
    tc = _ro(p.get("tg_db"))
    if tc is not None:
        for t in toks:
            r = _q(tc, "SELECT MIN(ts) FROM posts WHERE cas LIKE ?", (f"%{t}%",))
            if r and r[0][0]:
                out[t] = min(r[0][0], out.get(t, r[0][0]))
        tc.close()
    if before is not None:
        out = {t: ts for t, ts in out.items() if ts <= before}
    return out


def _candles(p, token, ts, gt_left, now):
    """1-minute candles from ts to ts + 4 h: minute.db call_candles, else live trades (hype.db), else one free
    GeckoTerminal read when gt_left[0] > 0 (the token's pool from kol.db). [] when nothing is known."""
    end = ts + 4 * 3600
    mc = _ro(p.get("minute_db"))
    if mc is not None:
        try:
            from kol import minute
            cs = minute.candles_for(mc, token, ts - 60, end)
        except Exception:  # noqa: BLE001
            cs = []
        mc.close()
        if cs and cs[-1][0] >= ts + 3600:
            return cs
    hc = _ro(p.get("hype_db"))
    rows = _q(hc, "SELECT ts, price_sol FROM live_trades WHERE mint = ? AND ts BETWEEN ? AND ?", (token, ts - 60, end))
    if hc is not None:
        hc.close()
    if len(rows) >= 5:
        return trade_candles(rows)
    if gt_left[0] <= 0:
        return []
    kc = _ro(p.get("kol_db"))
    pool = (_q(kc, "SELECT pair FROM tokens WHERE token = ?", (token,)) or [(None,)])[0][0]
    if kc is not None:
        kc.close()
    if not pool:
        return []
    gt_left[0] -= 1
    try:
        from kol import minute
        if minute.cooling():
            return []
        return minute.minutes(pool, ts - 60, min(end, now)) or []
    except Exception:  # noqa: BLE001
        return []


def measure_due(con, p, c, now, gt_cap=0):
    """Signals and traces at least 4 h old without a result: path_outcome from the candles we can get, and when
    the first public call came. -> (measured, GeckoTerminal reads)."""
    gt_left, n = [gt_cap], 0
    due = _q(con, "SELECT id, token, ts FROM group_signals WHERE measured_ts IS NULL AND ts <= ? AND ts >= ? "
                  "ORDER BY ts DESC LIMIT 200", (now - 4 * 3600, now - 3 * 86400))
    pub = _public_first(p, {t for _, t, _ in due})
    for sid, tok, ts in due:
        o = path_outcome(_candles(p, tok, ts, gt_left, now), ts, c) or {}
        fp = pub.get(tok)
        con.execute("UPDATE group_signals SET r1h=?, r4h=?, hit1h=?, hit4h=?, ev=?, first_public_ts=?, measured_ts=? "
                    "WHERE id=?", (o.get("r1h"), o.get("r4h"), o.get("hit1h"), o.get("hit4h"), o.get("ev"),
                                   fp if fp and fp >= ts - 60 else None, now, sid))
        n += 1
    due = _q(con, "SELECT token, ts FROM group_traces WHERE measured_ts IS NULL AND ts <= ? AND ts >= ? LIMIT 200",
             (now - 4 * 3600, now - 3 * 86400))
    pub = _public_first(p, {t for t, _ in due})
    for tok, ts in due:
        o = path_outcome(_candles(p, tok, ts, gt_left, now), ts, c) or {}
        fp = pub.get(tok)
        con.execute("UPDATE group_traces SET r1h=?, r4h=?, hit1h=?, hit4h=?, ev=?, first_public_ts=?, measured_ts=? "
                    "WHERE token=? AND ts=?", (o.get("r1h"), o.get("r4h"), o.get("hit1h"), o.get("hit4h"),
                                               o.get("ev"), fp if fp and fp >= ts else None, now, tok, ts))
        n += 1
    con.commit()
    return n, gt_cap - gt_left[0]


def _shadow(p, rows, now):
    """rows [(token, old, new, detail)] -> league.db shadow_decisions under this flag (league/flags.shadow)."""
    if not rows or not p.get("league_db"):
        return 0
    from league import flags as lflags
    try:
        lc = sqlite3.connect(p["league_db"], timeout=30)
    except sqlite3.Error:
        return 0
    try:
        n = sum(bool(lflags.shadow(lc, FLAG, None, t, o, nw, d, now)) for t, o, nw, d in rows)
        lc.commit()
    finally:
        lc.close()
    return n


def _kv(con, key, value=None):
    if value is None:
        r = _q(con, "SELECT value FROM group_kv WHERE key = ?", (key,))
        return r[0][0] if r else None
    con.execute("INSERT OR REPLACE INTO group_kv VALUES (?, ?)", (key, str(value)))


def night(cfg=None, now=None, credits=None, log=print, fetch=None, sol_usd=None, force=False, **over):
    """The full pass (01-06 Zagreb under ops.heavy --night). None when the flag is off or a pass ran < night_gap_h ago."""
    m = mode(over.pop("trade_db", None))
    if m == "off":
        log("grupe: zastavica group_discovery je isključena, noćni prolaz ne radi ništa")
        return None
    c = config(cfg)
    now = int(now or time.time())
    p = paths(**over)
    con = connect(p["early_db"])
    try:
        last = int(_kv(con, "last_night") or 0)
        if not force and now - last < c["night_gap_h"] * 3600:
            log(f"grupe: noćni prolaz je već bio prije {(now - last) / 3600:.1f} h, preskačem")
            return None
        kc = _ro(p["kol_db"])
        mc = _ro(p.get("minute_db"))
        try:
            callers = build_caller_groups(kc, c, now, mc) if kc is not None else []
            save_groups(con, "caller", callers, now)
            budget = c["night_credits"] if credits is None else int(credits)
            extra = [t for (t,) in _q(con, "SELECT token FROM group_traces WHERE ts >= ?", (now - 86400,))]
            mints = fetch_candidates(con, kc, c, now, extra)
            todo = mints[:budget // max(10, c["pages"] * 10) + 1]
            supply = {}
            for i in range(0, len(todo), 500):
                ch = todo[i:i + 500]
                supply.update(_q(kc, f"SELECT token, supply FROM tokens WHERE supply > 0 AND token IN "
                                     f"({','.join('?' * len(ch))})", ch))
            n_read, spent = fetch_early(con, mints, c, budget, fetch, sol_usd or _sol_usd(), log, supply)
            wallets, relay = build_wallet_groups(con, kc, p, c, now) if kc is not None else ([], set())
            save_groups(con, "wallet", wallets, now)
        finally:
            for x in (kc, mc):
                if x is not None:
                    x.close()
        measured, gt = measure_due(con, p, c, now, c["gt_night"])
        keep = now - c["keep_days"] * 86400
        con.execute("DELETE FROM group_buys WHERE ts < ?", (keep,))
        con.execute("DELETE FROM group_activity WHERE ts < ?", (keep,))
        con.execute("DELETE FROM group_runs WHERE ts < ?", (keep,))
        _kv(con, "last_night", now)
        g = Counter(x[2]["grade"] for x in callers)
        gw = Counter(x[2]["grade"] for x in wallets)
        # 11.11.: every grade with the measured cases behind it (n), e.g. "kvalitetna (n=9)"
        qn = [x[2].get("n_measured") or 0 for x in callers if x[2]["grade"] == "quality"]
        detail = {"caller_groups": len(callers), "caller_grades": dict(g), "wallet_groups": len(wallets),
                  "wallet_grades": dict(gw), "mints_read": n_read, "mints_waiting": max(0, len(mints) - n_read),
                  "relayers": len(relay), "measured": measured,
                  "caller_graded": [{"group_id": gid, "size": len(mem), "grade": met["grade"],
                                     "n_measured": met.get("n_measured")} for gid, mem, met in callers][:50]}
        con.execute("INSERT INTO group_runs VALUES (?,?,?,?,?)", (now, "night", spent, gt, json.dumps(detail)))
        con.commit()
        log(f"grupe (noć, {m}): {len(callers)} ekipa callera ({g.get('quality', 0)} kvalitetnih"
            + (f", n izmjerenih {', '.join(map(str, sorted(qn, reverse=True)[:8]))}" if qn else "") + ", "
            f"{g.get('exit_liquidity', 0)} izlazna likvidnost, {g.get('bad', 0)} loših), {len(wallets)} grupa novčanika "
            f"({gw.get('quality', 0)} kvalitetnih); Helius {n_read} tokena za {spent} kredita (strop {budget}), "
            f"{len(relay)} relayera izbačeno; izmjereno {measured} signala/tragova, GeckoTerminal {gt}")
        return detail
    finally:
        con.close()


def incremental(cfg=None, now=None, log=print, sol_usd=None, fetch=None, credits=None, **over):
    """The 15-minute pass: fresh calls and buys of group members, the shadow scoring lines, hidden list signals,
    traces, and the results of what became 4 h old. Our databases only unless credits > 0. None when off."""
    m = mode(over.pop("trade_db", None))
    if m == "off":
        return None
    c = config(cfg)
    now = int(now or time.time())
    p = paths(**over)
    window = 900 + c["win_s"]
    con = connect(p["early_db"])
    try:
        c_of, c_grade, _o = load_groups(con, "caller")
        w_of, w_grade, w_owner = load_groups(con, "wallet")
        sol = sol_usd or _sol_usd()
        shadow_rows, n_act = [], 0
        # --- calls of caller-group members (X, Telegram), the dedupe and the weight, first calls of quality groups
        from kol import converge
        ev, _s, _f = converge.events(now, window, kol_db=p["kol_db"], tg_db=p["tg_db"], hype_db=p["hype_db"])
        by_tok = defaultdict(list)
        for tok, ts, plat, who, kind in ev:
            if plat in ("x", "tg") and kind == "call":
                by_tok[tok].append((int(ts), who))
        kc = _ro(p["kol_db"])
        mcap0 = {}
        if kc is not None and by_tok:
            toks = list(by_tok)
            mcap0 = {t: mc for t, mc in _q(kc, f"SELECT token, MAX(mcap0) FROM calls WHERE token IN "
                                               f"({','.join('?' * len(toks))}) GROUP BY token", toks)}
        pub_before = _public_first(p, by_tok, before=now - window) if by_tok else {}
        for tok, calls in by_tok.items():
            if not any(h in c_of for _, h in calls):
                continue
            sig = dedupe(calls, c_of, c["win_s"])
            for s in sig:
                if not s["gid"]:
                    continue
                for h in s["handles"]:
                    n_act += con.execute("INSERT OR IGNORE INTO group_activity VALUES (?,?,?,?,?,?,?)",
                                         (s["ts"], "call", s["gid"], tok, h, mcap0.get(tok), 1)).rowcount
                first_overall = min(calls)[0] == s["ts"] and tok not in pub_before
                if c_grade.get(s["gid"]) == "quality" and first_overall:
                    con.execute("INSERT OR IGNORE INTO group_signals (ts, source, gid, token, who, mcap_usd, detail) "
                                "VALUES (?,?,?,?,?,?,?)", (s["ts"], "caller_group_first", s["gid"], tok, s["handles"][0],
                                                           mcap0.get(tok), json.dumps({"handles": s["handles"]})))
            n_raw = len({h for _, h in calls})
            w = weighted(sig, c_grade)
            key = f"ded:{tok}:{len(sig)}:{w}"
            if (n_raw != len(sig) or w != len(sig)) and not _kv(con, key):
                _kv(con, key, now)
                exitg = sorted({s["gid"] for s in sig if c_grade.get(s["gid"]) == "exit_liquidity"})
                shadow_rows.append((tok, f"{n_raw} računa zove", f"{len(sig)} neovisnih signala, težina {w:+.1f}",
                                    {"groups": sorted({s["gid"] for s in sig if s["gid"]}), "exit_groups": exitg}))
        if kc is not None:
            kc.close()
        # --- buys of wallet-group members: live trades, followed-wallet webhook, early buyers, our Helius cache
        buys = []
        if w_of:
            hc = _ro(p["hype_db"])
            buys += [(mi, w, ts, (mcs or 0) * sol or None) for mi, w, ts, mcs in
                     _q(hc, "SELECT mint, wallet, ts, mcap_sol FROM live_trades WHERE side = 'buy' AND ts >= ?",
                        (now - window,)) if w in w_of]
            buys += [(mi, w, ts, None) for w, mi, ts in
                     _q(hc, "SELECT wallet, mint, ts FROM chain_trades WHERE side = 'buy' AND ts >= ?",
                        (now - window,)) if w in w_of]
            if hc is not None:
                hc.close()
            buys += [(mi, w, ts, None) for mi, w, ts in
                     _q(con, "SELECT mint, wallet, first_buy_ts FROM early_buyers WHERE first_buy_ts >= ?",
                        (now - window,)) if w in w_of]
            buys += [(mi, w, ts, mc) for mi, w, ts, mc in
                     _q(con, "SELECT mint, wallet, ts, mcap_usd FROM group_buys WHERE side = 'buy' AND ts >= ?",
                        (now - window,)) if w in w_of]
        called = set(_public_first(p, {b[0] for b in buys}, before=now)) if buys else set()
        for mi, w, ts, mc in buys:
            n_act += con.execute("INSERT OR IGNORE INTO group_activity VALUES (?,?,?,?,?,?,?)",
                                 (int(ts), "buy", w_of[w], mi, w, _r(mc, 0), int(mi in called))).rowcount
        hidden = hidden_signals(buys, w_of, w_grade, called, c, w_owner)
        for h in hidden:
            if con.execute("INSERT OR IGNORE INTO group_signals (ts, source, gid, token, who, mcap_usd, detail) VALUES "
                           "(?,?,?,?,?,?,?)", (h["ts"], "hidden_group", h["gid"], h["token"], ",".join(h["wallets"]),
                                               _r(h["mcap_usd"], 0), json.dumps({"wallets": h["wallets"]}))).rowcount:
                shadow_rows.append((h["token"], "nema signala",
                                    f"skriveni popis: {len(h['wallets'])} novčanika grupe {h['gid']} bez poziva",
                                    {"gid": h["gid"], "wallets": h["wallets"], "mcap_usd": h["mcap_usd"],
                                     "under_30k": bool(h["mcap_usd"] and h["mcap_usd"] < 30000)}))
        # --- traces without a call (live trades + early buyers we have)
        hc = _ro(p["hype_db"])
        lt = _q(hc, "SELECT mint, wallet, ts, mcap_sol FROM live_trades WHERE side = 'buy' AND ts >= ?", (now - 2100,))
        first_seen = dict(_q(hc, "SELECT mint, MIN(ts) FROM live_trades WHERE mint IN (SELECT DISTINCT mint FROM "
                                 "live_trades WHERE side = 'buy' AND ts >= ?) GROUP BY mint", (now - 2100,))) if lt else {}
        # 10.11.: only the launches of the traded mints (every new pump.fun token is captured now, 20-40k a day)
        launches = dict(_q(hc, "SELECT mint, ts FROM live_launches WHERE ts >= ? AND mint IN (SELECT DISTINCT mint FROM "
                               "live_trades WHERE side = 'buy' AND ts >= ?)", (now - 7 * 86400, now - 2100))) if lt else {}
        if hc is not None:
            hc.close()
        eb = _q(con, "SELECT mint, wallet, first_buy_ts FROM early_buyers WHERE first_buy_ts >= ?", (now - 2100,))
        mcap_of = {}
        for mi, _w, ts, mcs in sorted(lt, key=lambda r: r[2]):
            if mcs:
                mcap_of[mi] = mcs * sol
        for mi, ts in launches.items():
            first_seen[mi] = min(ts, first_seen.get(mi, ts))
        tb = [(mi, w, ts) for mi, w, ts, _m in lt] + eb
        cand = traces(tb, now, c, set(), mcap_of, first_seen)
        called_t = set(_public_first(p, {t["token"] for t in cand}, before=now)) if cand else set()
        n_tr = 0
        for t in cand:
            if t["token"] in called_t or _q(con, "SELECT 1 FROM group_traces WHERE token = ? AND ts >= ?",
                                            (t["token"], now - 6 * 3600)):
                continue
            gw = len({w for mi, w, ts in tb if mi == t["token"] and ts >= now - 300 and w in w_of})
            con.execute("INSERT OR IGNORE INTO group_traces (token, ts, buyers5, buyers30, mcap_usd, group_wallets) "
                        "VALUES (?,?,?,?,?,?)", (t["token"], now, t["buyers5"], t["buyers30"], _r(t["mcap_usd"], 0), gw))
            n_tr += 1
        spent = 0
        budget = c["incr_credits"] if credits is None else int(credits)
        if budget > 0 and n_tr:
            day = time.strftime("%Y-%m-%d", time.gmtime(now))
            used = int(_kv(con, f"incr_credits:{day}") or 0)
            budget = min(budget, c["incr_day_credits"] - used)
            if budget > 0:
                tm = [t["token"] for t in cand if t["token"] not in called_t]
                tm = [t for t in tm if not _q(con, "SELECT 1 FROM group_fetched WHERE mint = ?", (t,))]
                _n, spent = fetch_early(con, tm, c, budget, fetch, sol, log)
                _kv(con, f"incr_credits:{day}", used + spent)
        measured, gt = measure_due(con, p, c, now, c["gt_incr"])
        con.commit()
        n_sh = _shadow(p, shadow_rows, now)
        con.execute("INSERT INTO group_runs VALUES (?,?,?,?,?)",
                    (now, "incr", spent, gt, json.dumps({"activity": n_act, "hidden": len(hidden), "traces": n_tr,
                                                         "shadow": n_sh, "measured": measured})))
        con.execute("DELETE FROM group_kv WHERE key LIKE 'ded:%' AND CAST(value AS INTEGER) < ?", (now - 86400,))
        con.commit()
        if n_act or hidden or n_tr or n_sh or measured:
            log(f"grupe (15 min, {m}): {n_act} novih poziva/kupnji članova grupa, {len(hidden)} skrivenih popisa, "
                f"{n_tr} tragova bez poziva, {n_sh} zapisa u sjeni, izmjereno {measured}"
                + (f", Helius {spent} kredita" if spent else ""))
        return {"activity": n_act, "hidden": len(hidden), "traces": n_tr, "shadow": n_sh, "measured": measured,
                "credits": spent}
    finally:
        con.close()


# ===================================================================================================================
# MCP (ui/mcpapi.py): read-only
# ===================================================================================================================
def _labels_from_notes(trade_db=None):
    """{gid: {"label", "status", "note_id"}} from submit_suggestion notes with proposed_change {"group_label": {...}}:
    the owner's accepted / applied ones as the label, waiting ones as proposals. Read-only on trade.db."""
    from trade import settings
    tc = _ro(trade_db or settings.DB)
    out = defaultdict(list)
    for nid, pc, status in _q(tc, "SELECT id, proposed_change, status FROM assistant_notes WHERE kind = 'suggestion' "
                                  "AND proposed_change LIKE '%group_label%' AND status != 'odbijeno' ORDER BY id DESC"):
        try:
            gl = (json.loads(pc) or {}).get("group_label") or {}
        except ValueError:
            continue
        if isinstance(gl, dict) and gl.get("group_id"):
            out[str(gl["group_id"])].append({"label": str(gl.get("label") or "")[:80], "note": str(gl.get("note") or "")[:300],
                                             "status": status, "note_id": nid})
    if tc is not None:
        tc.close()
    return out


def _page(limit, offset, default=100):
    try:
        limit = max(1, min(500, int(limit or default)))
    except (TypeError, ValueError):
        limit = default
    try:
        offset = max(0, int(offset or 0))
    except (TypeError, ValueError):
        offset = 0
    return limit, offset


def trader_groups(kind="caller", min_quality=None, limit=None, offset=None, path=None, trade_db=None):
    """get_trader_groups: the groups of one kind with members, metrics and grade (best grade first)."""
    kind = kind if kind in ("caller", "wallet") else "caller"
    m = mode(trade_db)
    base = {"flag": FLAG, "flag_mode": m, "kind": kind, "grade_order": list(GRADES), "grades_hr": GRADE_HR,
            "label_shape": LABEL_SHAPE}
    if m == "off":
        return {**base, "groups": [], "total": 0, "note": "zastavica group_discovery je isključena"}
    if min_quality is not None and min_quality not in GRADES:
        return {"error": f"min_quality must be one of {', '.join(GRADES)}"}
    floor = GRADES.index(min_quality) if min_quality else 0
    limit, offset = _page(limit, offset)
    ec = _ro(path or db_path())
    rows = _q(ec, "SELECT id, members, size, grade, metrics, updated FROM group_list WHERE kind = ?", (kind,))
    if ec is not None:
        ec.close()
    c = config()
    rows = [(gid, mem, sz, grade_of(kind, gr, met, c), met, upd) for gid, mem, sz, gr, met, upd in rows]
    rows = [r for r in rows if r[3] in GRADES and GRADES.index(r[3]) >= floor]

    def size(r):
        met = json.loads(r[4] or "{}")
        return met.get("events") or met.get("tokens") or 0
    rows.sort(key=lambda r: (-GRADES.index(r[3]), -size(r)))
    labels = _labels_from_notes(trade_db)
    shill = _shill_marks(path, trade_db) if kind == "caller" else {}
    out = []
    for gid, members, size, grade, metrics, upd in rows[offset:offset + limit]:
        ls = labels.get(gid) or []
        acc = next((x for x in ls if x["status"] in ("prihvaćeno", "primijenjeno")), None)
        met = json.loads(metrics)
        n = n_measured_of(kind, met)
        row = {"group_id": gid, "kind": kind, "members": json.loads(members), "size": size, "grade": grade,
               "grade_hr": GRADE_HR.get(grade), "n_measured": n, "grade_text": grade_text(grade, n),
               "weight_in_shadow_scoring": WEIGHT.get(grade), "metrics": met, "label": acc["label"] if acc else None,
               "proposed_labels": [x for x in ls if x["status"] == "novo"][:5], "updated_ts": upd}
        if gid in shill:   # 11.11. (kol/preshill.py, flag pre_shill): the paid shill network(s) inside this group
            row.update(shill[gid])
        out.append(row)
    nxt = offset + limit if offset + limit < len(rows) else None
    return {**base, "groups": out, "total": len(rows), "next_offset": nxt}


def _shill_marks(path=None, trade_db=None):
    """{group_id: {"shill_network", "label", "shill_parts", "chain_check"}} from kol/preshill.py ({} while its flag
    is off or nothing was measured)."""
    try:
        from kol import preshill
        return preshill.group_marks(path, trade_db)
    except Exception:  # noqa: BLE001 - the groups answer without the marks
        return {}


def group_activity(since_ts=None, limit=None, offset=None, path=None, trade_db=None, now=None):
    """get_group_activity: fresh calls and buys of group members since since_ts (default 24 h), newest first, and
    the group signals (hidden_group, caller_group_first) of that time with their measured result."""
    m = mode(trade_db)
    now = int(now or time.time())
    if m == "off":
        return {"flag": FLAG, "flag_mode": m, "activity": [], "signals": [], "total": 0,
                "note": "zastavica group_discovery je isključena"}
    try:
        since = int(since_ts) if since_ts is not None else now - 86400
    except (TypeError, ValueError):
        return {"error": "since_ts must be unix seconds"}
    limit, offset = _page(limit, offset)
    ec = _ro(path or db_path())
    c = config()
    grade = {}
    for g, k, gr, met in _q(ec, "SELECT id, kind, grade, metrics FROM group_list"):
        try:
            met = json.loads(met or "{}") or {}
        except ValueError:
            met = {}
        grade[g] = (k, grade_of(k, gr, met, c), n_measured_of(k, met))
    rows = _q(ec, "SELECT ts, kind, gid, token, who, mcap_usd, public_called FROM group_activity WHERE ts >= ? "
                  "ORDER BY ts DESC LIMIT ? OFFSET ?", (since, limit + 1, offset))
    total = (_q(ec, "SELECT COUNT(*) FROM group_activity WHERE ts >= ?", (since,)) or [(0,)])[0][0]
    sig = _q(ec, "SELECT ts, source, gid, token, who, mcap_usd, r1h, r4h, hit1h, hit4h, ev, first_public_ts "
                 "FROM group_signals WHERE ts >= ? ORDER BY ts DESC LIMIT 200", (since,))
    if ec is not None:
        ec.close()
    none = (None, None, None)
    act = [{"ts": ts, "kind": k, "group_id": g, "group_kind": grade.get(g, none)[0], "grade": grade.get(g, none)[1],
            "n_measured": grade.get(g, none)[2], "token": t, "who": w, "mcap_usd": mc,
            "under_30k": bool(mc and mc < 30000), "public_called": bool(pc)} for ts, k, g, t, w, mc, pc in rows[:limit]]
    sigs = [{"ts": ts, "source": s, "group_id": g, "grade": grade.get(g, none)[1], "n_measured": grade.get(g, none)[2],
             "token": t, "who": w.split(",") if s == "hidden_group" else w,
             "mcap_usd": mc, "under_30k": bool(mc and mc < 30000), "r1h": r1, "r4h": r4, "hit20_before_stop30_1h": h1,
             "hit20_before_stop30_4h": h4, "ev_after_cost": e,
             "public_call_delay_min": round((fp - ts) / 60, 1) if fp else None}
            for ts, s, g, t, w, mc, r1, r4, h1, h4, e, fp in sig]
    return {"flag": FLAG, "flag_mode": m, "since_ts": since, "activity": act, "total": total,
            "next_offset": offset + limit if len(rows) > limit else None, "signals": sigs}


def mcp_signals(now=None, path=None, trade_db=None, live=None, max_age_s=3600):
    """Entries for get_market_signals with source hidden_group (last hour), [] when the flag is off. live: {token:
    market row} for tests; None = DexScreener through ui/prijedlog.live_market."""
    if mode(trade_db) == "off":
        return []
    now = int(now or time.time())
    ec = _ro(path or db_path())
    rows = _q(ec, "SELECT ts, gid, token, who, mcap_usd FROM group_signals WHERE source = 'hidden_group' AND ts >= ? "
                  "ORDER BY ts DESC LIMIT 20", (now - max_age_s,))
    if ec is not None:
        ec.close()
    if not rows:
        return []
    if live is None:
        try:
            from ui import prijedlog
            live = prijedlog.live_market([r[2] for r in rows]) or {}
        except Exception:  # noqa: BLE001
            live = {}
    out = []
    for ts, gid, tok, who, mc in rows:
        lv = live.get(tok)
        mcap = (lv or {}).get("mcap") or mc
        row = None
        if lv:
            from ui import mcpapi
            row = mcpapi._market_row(lv)
        out.append({"token": tok, "symbol": None, "source": "hidden_group", "callers": [], "n_callers": 0,
                    "first_call_ts": None, "last_call_ts": None, "signal_ts": int(ts),
                    "group": {"group_id": gid, "kind": "wallet", "wallets": (who or "").split(",")},
                    "market": row, "under_30k": bool(mcap and mcap < 30000),
                    "note": "skriveni popis: 3+ novčanika iste kvalitetne grupe kupilo bez javnog poziva (sjena, ne kupuje se)"})
    return out


def mcp_tool(name, a):
    """The two read-only MCP tools (ui/mcpapi._tool)."""
    a = a if isinstance(a, dict) else {}
    if name == "get_trader_groups":
        return trader_groups(a.get("kind") or "caller", a.get("min_quality"), a.get("limit"), a.get("offset"))
    return group_activity(a.get("since_ts"), a.get("limit"), a.get("offset"))


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(description="Ekipe callera i skriveni popisi novčanika (zastavica group_discovery)")
    ap.add_argument("cmd", choices=("night", "incr", "status"))
    ap.add_argument("--credits", type=int, default=None, help="Helius krediti za ovaj prolaz (strop)")
    ap.add_argument("--force", action="store_true", help="noćni prolaz i ako je bio prije manje od 20 h")
    a = ap.parse_args(argv)
    if a.cmd == "night":
        night(credits=a.credits, force=a.force)
    elif a.cmd == "incr":
        incremental(credits=a.credits)
    else:
        ec = _ro(db_path())
        for ts, kind, cr, gt, d in _q(ec, "SELECT ts, kind, credits, gt, detail FROM group_runs ORDER BY ts DESC LIMIT 10"):
            print(time.strftime("%d.%m. %H:%M", time.gmtime(ts)), kind, f"Helius {cr}", f"GT {gt}", d)
        print(f"zastavica {FLAG}: {mode()}; {paper_refusal_text()}")
    return 0


def paper_refusal_text():
    try:
        from trade import settings
        con = settings.connect()
        try:
            why = paper_refusal(con)
        finally:
            con.close()
        return "smije u paper" if why is None else f"paper još ne: {why}"
    except Exception as e:  # noqa: BLE001
        return f"paper provjera nije uspjela ({type(e).__name__})"


if __name__ == "__main__":
    sys.exit(main())
