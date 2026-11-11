"""Kupci prije shill mreže (11.11., Jure; flag pre_shill, G15, default off: the owner's one-time order sets shadow).

The owner's spec: the shill network is a caller group of kol/groupdisc (get_trader_groups) graded "bad" with 20+
members; it is marked shill_network=true with the label "plaćena shill mreža". The wallets that buy its tokens in
the 6 hours BEFORE its first call, and sell into its wave of calls, are probably its owners and organisers.
Nothing here buys or sells: every mode measures in shadow (paper only past paper_refusal, the flag's own proof).

0) The chain check (before anything is labelled). groupdisc's groups are connected components of linked caller pairs
   (>= 3 shared tokens within 120 s / 10 min, lift >= 5). A component can be a CHAIN: A~B, B~C, C~D ... joins crews
   that never post together. For every caller group with >= min_size members the links between its members are
   recomputed with groupdisc's own rule (gd.lift_table over the same 30 days, restricted to the members, gd.links)
   and measured: density (share of member pairs that are linked), median degree, share of members with >= 3 links,
   the 3-core. A group at density >= dense_min (0.3) is kept whole. A sparser one is split:
     a) the 4-truss: only links that lie in >= 2 triangles of links stay (both accounts share two more partners);
        a chain link lies in no triangle and falls away, a crew that posts together keeps its triangles; the
        components of what stays are the parts;
     b) a part that is still sparse (or a truss that removed nothing) is split again with the lift threshold doubled
        (5 -> 10 -> 20 ...), up to max_depth levels;
     c) a part still under dense_min at the last level is marked chained and is NEVER a shill network.
   Accounts left in no part were tied in only through chain links. Every part is graded again by groupdisc's rule
   on its own events (gd.group_events / gd.caller_metrics, quality needs 8+ measured since 11.11.). A part graded
   "bad" (config grades) with >= min_size members and not chained is a shill network. preshill_checks keeps the
   measurement of every big group (MCP get_pre_shill_wallets "chain_checks", log line of the night pass).

1) Tokens. Every token a shill network called in the last `days` (14): T0 = the first call of any member (kol.db
   calls, kind 'call', not bad), the wave = its calls up to 24 h after T0 (wave_end = the last one + 30 min), market
   cap at T0 from the first member call that has one (under min_t0_mcap, CLAUDE.md 30k, or unknown: not analysed).

2) Buyers in [T0 - 6 h, T0] (from the token's first trade when it is younger). Our data first, merged per wallet
   and deduplicated by signature: early.db preshill_trades / precall_trades / group_buys (Helius, signer-attributed)
   and early_buyers, hype.db live_trades (PumpPortal: the trader is the signer) and chain_trades, events.db
   wallet_buy / wallet_sell (the same feed kept 30+ days; deduplicated through its uid "wallet|sig|mint"). kol.db
   insiders (kol/flows) are NOT used: before 10.11. they named the fee payer. Helius getTransactionsForAddress on
   the mint only for the part of the window no Helius cache of ours holds (precall's window before the first call,
   groupdisc's first 30 min): newest first from T0, pre_pages pages, once per mint (preshill_fetched), within the
   pass's credit cap (night_credits, 3000). A trade belongs to the SIGNER whose balance of the mint changed
   (gd.owner_trades), never to a fee payer (relayed / gasless swaps). Sells: our feeds, then for the wallets with
   >= min_tokens pre-shill tokens one page of the wallet's own history from its buy to T0 + 24 h (10 credits,
   once per wallet and token, sell_share of the cap).
   Out: dev-funded buys (the dev's own, paid by the dev, or a wallet the dev funded: group_fetched / precall /
   live_launches creator), bundles (a slot where >= bundle_min wallets bought the token: those buys), bots (> 200
   trades a day: wallets.db stats trades_per_day, a fetched page of 100 trades inside 12 h, > 200 of our recorded
   trades in one day; groupdisc's rate rules: > 50 a minute, buy and sell in one slot), relayers (fee payer for >=
   5 owners), LP (a pool never signs, so owner_trades never names one; pool addresses of kol.db tokens.pair and
   events.db pools are dropped too), CEX (label cex, and funding hubs: a funder of > hub_min wallets is an exchange
   hot wallet: it is never a buyer here and never makes two wallets "one owner"). Labels from wallets.db: the
   repo has no LP / CEX address list; wallets/store.BAD_LABELS minus insider / rugger / funder_of_rugger (those are
   what this looks for, kept and shown) excludes: bot, bundler, cex, dev, mev, sniper. The owner's own bot / sniper
   labels (kol/precall.owner_labels) too.

3) Per wallet and token: minutes before T0, entry market cap, SOL in, when it sold relative to T0 and to the peak
   (minute.db candles within 4 h, else PumpPortal prices within 24 h; kol.db max24 for the size only), PnL, sold
   into the wave (first sell between T0 and wave_end). Per wallet: n_tokens_pre_shill, median / average minutes
   before T0, hit rate (closed in profit), total PnL SOL, median hold, entry market cap, shared funders. Candidate:
   n >= 3, average 5-120 min before T0, PnL > 0. Out of sample by time like kol/precall: tokens with T0 in the older
   2/3 of the 14 days select (the same rule there), the newer 1/3 confirm (>= 2 tokens, the band, PnL > 0):
   confirmed. Same non-hub funder, or the same slot on >= cluster_slot_min tokens, joins wallets into one cluster
   (likely the network's owners).

4) Signal (shadow). Every 30 min: when >= 2 candidate / confirmed wallets, or one wallet of a cluster of 2+, buy a
   token within an hour and no public call came before that buy: preshill_signals (detection time, the buy that
   completed it, market cap) and a shadow line. Measured after 4 h from the detection time (gd.path_outcome: +20 %
   before -30 %, 1 h / 4 h, EV after cost), with the minutes until the shill network's first call and the result of
   selling into it. A shill-network call is a NEGATIVE weight in the shadow scoring (one line per token: exit
   liquidity) and in ui/kandidati (the call counts -1); for a token held through a pre_shill signal the network's
   call is the EXIT: "prodaj u callove" in shadow, exit_ts / exit_ret on the signal. Our feeds see these wallets
   only when they are followed; the incremental pass therefore reads the newest page of the best poll_wallets (8)
   wallets' own history (10 credits each, at most once in 30 min, poll_day_credits 1000 a day).

Storage: early.db (EARLY_DB), own tables prefixed preshill_: the same file as groupdisc's and precall's Helius
caches, so "never fetch a mint twice" is one SQL join, and the file the trading code never reads. kol.db / wallets.db
/ events.db are only read; the wallets table's tier / labels / scores are never written.

Passes: `python3 -m kol.preshill night` (01-06 Zagreb under ops.heavy --night, at most once in night_gap_h) and
`python3 -m kol.preshill incr` every 30 min. Flag off: both end at once, MCP answers empty, the card is not shown.
Cost: Helius credits metered by usage/meter (wallets/rpc through event_calendar/http) and in preshill_runs.
"""
import hashlib
import json
import os
import sqlite3
import statistics
import sys
import time
from collections import Counter, defaultdict

from kol import groupdisc as gd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FLAG = "pre_shill"
LABEL = "plaćena shill mreža"
STATUS_HR = {"confirmed": "potvrđen", "candidate": "kandidat", "watch": "promatra se", "excluded": "isključen"}
KEEP_LABELS = {"insider", "rugger", "funder_of_rugger"}   # BAD_LABELS that are what this looks for: shown, not dropped
WSOL = gd.WSOL
DUST_SOL = 0.001
SOLSCAN = "https://solscan.io/account/"

DEFAULT = {
    # 0) the network
    "min_size": 20, "grades": ["bad"], "dense_min": 0.3, "truss_k": 4, "core_k": 3, "lift_step": 2.0, "max_depth": 4,
    # 1) tokens
    "days": 14, "pre_window_s": 6 * 3600, "min_t0_mcap": 30_000, "wave_tail_s": 1800, "post_s": 86400,
    # 2) buyers
    "min_sol": 0.05, "bundle_min": 3, "bot_tpd": 200, "bot_tx_min": 50, "relayer_min": 5, "hub_min": 20,
    # 3) wallets
    "min_tokens": 3, "min_before_min": 5.0, "max_before_min": 120.0, "min_confirm": 2, "cluster_slot_min": 2,
    # Helius: metered (usage/meter) and capped per pass / per day
    "night_credits": 3000, "sell_share": 0.34, "pre_pages": 3, "night_gap_h": 20,
    "poll_wallets": 8, "poll_gap_s": 1800, "poll_day_credits": 1000, "poll_back_s": 7200,
    # 4) signal and measurement
    "signal_min_wallets": 2, "signal_window_s": 3600, "exit_window_s": 86400, "tp": 0.20, "sl": -0.30, "cost": 0.02,
    "gt_night": 20, "gate_n": 30, "gate_days": 7, "keep_days": 45,
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS preshill_checks (parent TEXT PRIMARY KEY, size INTEGER, grade TEXT, diag TEXT, parts TEXT,
    periphery INTEGER, updated INTEGER);
CREATE TABLE IF NOT EXISTS preshill_networks (id TEXT PRIMARY KEY, parent TEXT, members TEXT, size INTEGER, grade TEXT,
    shill INTEGER, chained INTEGER, how TEXT, metrics TEXT, updated INTEGER);
CREATE TABLE IF NOT EXISTS preshill_tokens (token TEXT PRIMARY KEY, net TEXT, t0 INTEGER, first_handle TEXT,
    n_calls INTEGER, n_callers INTEGER, calls TEXT, wave_end INTEGER, mcap_t0 REAL, first_public_ts INTEGER,
    window_start INTEGER, dev TEXT, peak_ts INTEGER, peak_mcap REAL, peak_x REAL, buyers INTEGER, built_ts INTEGER);
CREATE INDEX IF NOT EXISTS preshill_tokens_t0 ON preshill_tokens (t0);
CREATE TABLE IF NOT EXISTS preshill_trades (mint TEXT, wallet TEXT, sig TEXT, ts INTEGER, slot INTEGER, side TEXT,
    sol REAL, tokens REAL, payer TEXT, src TEXT, PRIMARY KEY (sig, wallet, mint));
CREATE INDEX IF NOT EXISTS preshill_trades_mint ON preshill_trades (mint, ts);
CREATE INDEX IF NOT EXISTS preshill_trades_wallet ON preshill_trades (wallet, ts);
CREATE TABLE IF NOT EXISTS preshill_fetched (key TEXT PRIMARY KEY, kind TEXT, ts INTEGER, credits INTEGER,
    n_tx INTEGER, since_ts INTEGER, until_ts INTEGER, oldest_ts INTEGER, newest_ts INTEGER, complete INTEGER);
CREATE TABLE IF NOT EXISTS preshill_buys (token TEXT, wallet TEXT, buy_ts INTEGER, slot INTEGER, sol_in REAL,
    mcap_usd REAL, sold_ts INTEGER, sol_out REAL, payer TEXT, bundle INTEGER, src TEXT, PRIMARY KEY (token, wallet));
CREATE INDEX IF NOT EXISTS preshill_buys_wallet ON preshill_buys (wallet);
CREATE TABLE IF NOT EXISTS preshill_wallets (wallet TEXT PRIMARY KEY, status TEXT, why TEXT, cluster TEXT, score REAL,
    n_tokens INTEGER, med_min REAL, avg_min REAL, entry_mcap_med REAL, pnl_sol REAL, hit_rate REAL, med_hold_min REAL,
    sold_into_wave REAL, n_sel INTEGER, n_conf INTEGER, last_ts INTEGER, stats TEXT, first_seen INTEGER,
    status_ts INTEGER, updated INTEGER);
CREATE TABLE IF NOT EXISTS preshill_signals (id INTEGER PRIMARY KEY AUTOINCREMENT, ts INTEGER, buy_ts INTEGER,
    token TEXT UNIQUE, wallets TEXT, clusters TEXT, n_wallets INTEGER, mcap_usd REAL, detail TEXT, r1h REAL, r4h REAL,
    hit1h INTEGER, hit4h INTEGER, ev REAL, shill_ts INTEGER, first_public_ts INTEGER, exit_ts INTEGER, exit_ret REAL,
    measured_ts INTEGER);
CREATE INDEX IF NOT EXISTS preshill_signals_ts ON preshill_signals (ts);
CREATE TABLE IF NOT EXISTS preshill_runs (ts INTEGER, kind TEXT, credits INTEGER, detail TEXT);
CREATE TABLE IF NOT EXISTS preshill_kv (key TEXT PRIMARY KEY, value TEXT);
"""

_ro, _q, _med, _mean, _r = gd._ro, gd._q, gd._med, gd._mean, gd._r


# ===================================================================================================================
# basics
# ===================================================================================================================
def config(cfg=None):
    """DEFAULT with kol/config.json "pre_shill" on top (or the given cfg's section)."""
    if cfg is None:
        try:
            with open(os.path.join(ROOT, "kol", "config.json"), encoding="utf-8") as f:
                cfg = json.load(f)
        except (OSError, ValueError):
            cfg = {}
    c = {**DEFAULT, **((cfg or {}).get(FLAG) or {})}
    c["min_t0_mcap"] = max(10_000, float(c["min_t0_mcap"]))   # owner: never analysed under 10k (CLAUDE.md: 30k)
    c["min_size"] = max(2, int(c["min_size"]))
    return c


def paths(**over):
    """gd.paths plus trade.db and events.db (tests pass their own)."""
    p = gd.paths(**{k: v for k, v in over.items() if k not in ("trade_db", "events_db")})
    try:
        from trade import settings
        p["trade_db"] = settings.DB
    except Exception:  # noqa: BLE001
        p["trade_db"] = None
    try:
        from events import store as estore
        p["events_db"] = estore.db_path()
    except Exception:  # noqa: BLE001
        p["events_db"] = None
    for k in ("trade_db", "events_db"):
        if over.get(k):
            p[k] = over[k]
    return p


def connect(path=None):
    con = sqlite3.connect(path or gd.db_path(), timeout=60)
    con.executescript(SCHEMA)
    return con


def mode(trade_db=None):
    """The flag's mode; "off" when trade settings cannot be read (the safe side)."""
    try:
        from trade import settings
        return settings.flag(FLAG, path=trade_db)
    except Exception:  # noqa: BLE001
        return "off"


def kv(con, key, value=None):
    if value is None:
        r = _q(con, "SELECT value FROM preshill_kv WHERE key = ?", (key,))
        return r[0][0] if r else None
    con.execute("INSERT OR REPLACE INTO preshill_kv VALUES (?, ?)", (key, str(value)))


def _day(now):
    return time.strftime("%Y-%m-%d", time.gmtime(now))


def _chunks(xs, n=400):
    xs = list(xs)
    for i in range(0, len(xs), n):
        yield xs[i:i + n]


def _in(xs):
    return ",".join("?" * len(xs))


def _uid(sig, mint):
    """events.db's uid of a wallet trade (events/store.uid("wallet|sig|mint")): one trade seen in two feeds is one."""
    return int.from_bytes(hashlib.blake2b(f"wallet|{sig}|{mint}".encode(), digest_size=8).digest(), "big") >> 1


def _sol_usd():
    return gd._sol_usd()


# ===================================================================================================================
# 0) the chain check and the shill networks
# ===================================================================================================================
def _adj(edges):
    adj = defaultdict(set)
    for a, b in edges:
        if a != b:
            adj[a].add(b)
            adj[b].add(a)
    return adj


def kcore(edges, k):
    """Members of the k-core: what is left after members with fewer than k links are removed again and again."""
    adj = _adj(edges)
    deg = {x: len(n) for x, n in adj.items()}
    alive = set(adj)
    todo = [x for x in alive if deg[x] < k]
    while todo:
        x = todo.pop()
        if x not in alive:
            continue
        alive.discard(x)
        for y in adj[x]:
            if y in alive:
                deg[y] -= 1
                if deg[y] < k:
                    todo.append(y)
    return alive


def truss(edges, k):
    """Links of the k-truss: every link that stays lies in >= k - 2 triangles of links that stay. A chain link
    (A~B where A and B share no partner) lies in no triangle and goes; a crew posting together keeps its triangles."""
    adj = _adj(edges)
    es = {tuple(sorted(e)) for e in edges if e[0] != e[1]}
    sup = {e: len(adj[e[0]] & adj[e[1]]) for e in es}
    need = k - 2
    todo = [e for e, s in sup.items() if s < need]
    gone = set()
    while todo:
        e = todo.pop()
        if e in gone:
            continue
        gone.add(e)
        a, b = e
        adj[a].discard(b)
        adj[b].discard(a)
        for w in adj[a] & adj[b]:   # the triangles (a, b, w) are gone: their other two links lose one each
            for f in (tuple(sorted((a, w))), tuple(sorted((b, w)))):
                if f not in gone:
                    sup[f] -= 1
                    if sup[f] < need:
                        todo.append(f)
    return sorted(es - gone)


def density(members, edges, k=3):
    """groupdisc's link density of `members` over `edges` plus the size of the k-core."""
    ms = set(members)
    es = [e for e in edges if e[0] in ms and e[1] in ms]
    deg = Counter()
    for a, b in es:
        deg[a] += 1
        deg[b] += 1
    d = gd.link_density(ms, len(es), deg, k)
    d["core"] = len(kcore(es, k))
    return d


def refine(members, table, gc, c):
    """Split a caller group that is a chain of links into the parts whose accounts actually post together (see the
    module text, 0). table: gd.lift_table rows of (at least) the members' pairs. -> [{"members": sorted list, "how",
    "diag", "chained"}]; members in no part were tied in only through chain links."""
    cache = {}

    def links_at(lift):
        if lift not in cache:
            cache[lift] = gd.links(table, gc["min_shared"], lift)
        return cache[lift]

    def edges_in(ms, lift):
        return [e for e in links_at(lift) if e[0] in ms and e[1] in ms]

    parts = []

    def part(ms, how, d, chained):
        parts.append({"members": sorted(ms), "how": how, "diag": d, "chained": chained})

    def go(ms, lift, depth, how):
        es = edges_in(ms, lift)
        d = density(ms, es, c["core_k"])
        if len(ms) < 3 or (d["density"] or 0) >= c["dense_min"]:
            return part(ms, how, d, False)
        if depth >= c["max_depth"]:
            return part(ms, how, d, True)
        comps = [g for g in gd.components(truss(es, c["truss_k"])) if len(g) >= 2]
        step = f"{c['truss_k']}-truss"
        if not comps or (len(comps) == 1 and len(comps[0]) == len(ms)):
            up = round(lift * c["lift_step"], 2)
            comps = [g for g in gd.components(edges_in(ms, up)) if len(g) >= 2]
            step, lift = f"lift >= {up:g}", up
            if not comps:
                return part(ms, how, d, True)
        for g in comps:
            go(set(g), lift, depth + 1, f"{how} -> {step}")

    go(set(members), float(gc["min_lift"]), 0, "komponenta")
    return parts


def grade_parts(kcon, parts, gc, now, mcon=None):
    """Events, metrics and grade of every part by groupdisc's own rule, over the same days (parts are disjoint)."""
    from kol import bots as kbots
    if not parts:
        return parts
    since = now - gc["days"] * 86400
    member_of = {h: i for i, pt in enumerate(parts) for h in pt["members"]}
    sets = [set(pt["members"]) for pt in parts]
    events = defaultdict(list)
    try:
        for tok, rows in gd._first_calls_stream(kcon, since, kbots.handles(kcon), extra=True):
            for i in {member_of[r["handle"]] for r in rows if r["handle"] in member_of}:
                e = gd.group_events(rows, sets[i], gc["win_s"])
                if e:
                    e["r4h"] = gd._r4h(mcon, tok, e["ts"]) if mcon is not None else None
                    e["token"] = tok
                    events[i].append(e)
    except sqlite3.Error:
        pass
    for i, pt in enumerate(parts):
        m = gd.caller_metrics(events[i], gc)
        pt["grade"] = m["grade"]
        pt["metrics"] = {k: m.get(k) for k in ("events", "n_measured", "n_measured_4h", "n_measured_24h", "ev_1h",
                                                "ev_4h", "r1h_med", "r4h_med", "r24h_med", "rug_share",
                                                "public_r1h_med", "public_delay_min_med", "mcap_first_med")}
        pt["metrics"]["typical_order"] = m["typical_order"][:30]
    return parts


def build_networks(con, p, c, now, log=print):
    """The chain check of every caller group with >= min_size members and the shill networks among their parts
    (preshill_checks, preshill_networks rewritten). Returns a summary."""
    gc = gd.config()
    ec_rows = _q(con, "SELECT id, members, size, grade, metrics FROM group_list WHERE kind = 'caller' AND size >= ?",
                 (c["min_size"],))
    big = []
    for gid, mem, size, grade, met in ec_rows:
        try:
            big.append((gid, json.loads(mem or "[]"), gd.grade_of("caller", grade, met, gc)))
        except ValueError:
            continue
    con.execute("DELETE FROM preshill_checks")
    con.execute("DELETE FROM preshill_networks")
    out = {"groups_checked": len(big), "parts": 0, "shill_networks": 0, "chained": 0}
    if not big:
        con.commit()
        return out
    kc = _ro(p["kol_db"])
    mc = _ro(p.get("minute_db"))
    try:
        if kc is None:
            return out
        from kol import bots as kbots
        cand = set().union(*(set(m) for _g, m, _gr in big))
        since = now - gc["days"] * 86400
        table, _n, _u, _f = gd.lift_table((rows for _t, rows in gd._first_calls_stream(kc, since, kbots.handles(kc))),
                                          (gc["win_fast_s"], gc["win_s"]), cand, min_n=gc["min_shared"])
        for gid, members, grade in big:
            whole = density(members, gd.links(table, gc["min_shared"], gc["min_lift"]), c["core_k"])
            parts = grade_parts(kc, refine(members, table, gc, c), gc, now, mc)
            covered = sum(len(pt["members"]) for pt in parts)
            summary = []
            for pt in parts:
                nid = gd.gid_of("network", pt["members"])
                shill = int(pt["grade"] in c["grades"] and len(pt["members"]) >= c["min_size"] and not pt["chained"])
                con.execute("INSERT OR REPLACE INTO preshill_networks VALUES (?,?,?,?,?,?,?,?,?,?)",
                            (nid, gid, json.dumps(pt["members"]), len(pt["members"]), pt["grade"], shill,
                             int(pt["chained"]), pt["how"], json.dumps({**pt["metrics"], **pt["diag"]}), now))
                summary.append({"network_id": nid, "size": len(pt["members"]), "grade": pt["grade"],
                                "n_measured": pt["metrics"].get("n_measured"), "density": pt["diag"]["density"],
                                "chained": pt["chained"], "shill": bool(shill), "how": pt["how"]})
                out["parts"] += 1
                out["shill_networks"] += shill
                out["chained"] += int(pt["chained"])
            summary.sort(key=lambda x: -x["size"])
            con.execute("INSERT OR REPLACE INTO preshill_checks VALUES (?,?,?,?,?,?,?)",
                        (gid, len(members), grade, json.dumps(whole), json.dumps(summary[:40]),
                         len(members) - covered, now))
            big_parts = [s for s in summary if s["size"] >= 2]
            log(f"shill mreža: grupa {gid} ({len(members)} računa, {gd.GRADE_HR.get(grade, grade)}): gustoća veza "
                f"{(whole['density'] or 0):.3f}, medijan veza {whole['deg_med']}, 3-jezgra {whole['core']}; "
                + ("cijela je jedna ekipa" if len(parts) == 1 and not parts[0]["chained"] and covered == len(members)
                   else f"lanac: {len(big_parts)} dijelova (najveći {', '.join(str(s['size']) for s in big_parts[:5])}), "
                        f"{len(members) - covered} računa samo preko lanca")
                + f"; shill mreža: {sum(s['shill'] for s in summary)}")
        con.commit()
    finally:
        for x in (kc, mc):
            if x is not None:
                x.close()
    return out


def networks(con):
    """{network id: set(members)} of the shill networks."""
    out = {}
    for nid, mem in _q(con, "SELECT id, members FROM preshill_networks WHERE shill = 1"):
        try:
            out[nid] = set(json.loads(mem or "[]"))
        except ValueError:
            pass
    return out


def shill_members(path=None, trade_db=None):
    """{handle: network id} of every shill network ({} while the flag is off or nothing was measured)."""
    if mode(trade_db) == "off":
        return {}
    ec = _ro(path or gd.db_path())
    try:
        return {h: nid for nid, ms in networks(ec).items() for h in ms} if ec is not None else {}
    finally:
        if ec is not None:
            ec.close()


def group_marks(path=None, trade_db=None):
    """For groupdisc.trader_groups: {caller group id: {"shill_network", "shill_label", "shill_parts", "chain_check"}}.
    shill_network is true only when the WHOLE group is one network (dense, not a chain); otherwise the parts that are
    shill networks are listed. {} while the flag is off."""
    if mode(trade_db) == "off":
        return {}
    ec = _ro(path or gd.db_path())
    if ec is None:
        return {}
    try:
        checks = {g: (sz, json.loads(d or "{}"), per) for g, sz, d, per in
                  _q(ec, "SELECT parent, size, diag, periphery FROM preshill_checks")}
        parts = defaultdict(list)
        for nid, parent, mem, size, grade, shill, chained in _q(
                ec, "SELECT id, parent, members, size, grade, shill, chained FROM preshill_networks"):
            parts[parent].append({"network_id": nid, "size": size, "grade": grade, "shill": bool(shill),
                                  "chained": bool(chained), "members": json.loads(mem or "[]")[:30]})
    finally:
        ec.close()
    out = {}
    for gid, (size, d, per) in checks.items():
        ps = sorted(parts.get(gid, []), key=lambda x: -x["size"])
        whole = len(ps) == 1 and ps[0]["size"] == size and ps[0]["shill"]
        out[gid] = {"shill_network": whole, "shill_label": LABEL if whole else None,
                    "shill_parts": [{**x, "label": LABEL} for x in ps if x["shill"]],
                    "chain_check": {"density": d.get("density"), "links": d.get("n_links"), "deg_med": d.get("deg_med"),
                                    "deg_ge3_share": d.get("deg_ge3_share"), "core3": d.get("core"),
                                    "parts": len(ps), "only_through_chain": per,
                                    "verdict": "gusta ekipa" if len(ps) == 1 and ps[0]["size"] == size
                                    and not ps[0]["chained"] else "lanac, podijeljena"}}
    return out


# ===================================================================================================================
# 1) tokens of the shill networks
# ===================================================================================================================
def collect_tokens(con, p, c, now):
    """preshill_tokens for every token a shill network called in the last `days` (see the module text, 1)."""
    nets = networks(con)
    member_of = {h: nid for nid, ms in nets.items() for h in ms}
    if not member_of:
        return 0
    kc = _ro(p["kol_db"])
    if kc is None:
        return 0
    since = now - int(c["days"]) * 86400
    calls = defaultdict(list)
    try:
        for ch in _chunks(sorted(member_of)):
            for tok, h, ts, mc0 in _q(kc, f"SELECT token, handle, ts, mcap0 FROM calls WHERE kind = 'call' AND ts >= ? "
                                          f"AND bad IS NULL AND handle IN ({_in(ch)})", (since, *ch)):
                if tok and len(tok) >= 32:
                    calls[tok].append((int(ts), h, mc0))
        toks = list(calls)
        created, pub = {}, {}
        for ch in _chunks(toks):
            created.update(dict(_q(kc, f"SELECT token, created_ts FROM tokens WHERE created_ts > 0 AND token IN ({_in(ch)})",
                                   ch)))
            # the first call by anybody (X and Telegram are both in kol.db calls; indexed, unlike tg.db's LIKE)
            pub.update(dict(_q(kc, f"SELECT token, MIN(ts) FROM calls WHERE kind = 'call' AND token IN ({_in(ch)}) "
                                   f"GROUP BY token", ch)))
    finally:
        kc.close()
    dev = {}
    for ch in _chunks(toks):
        q = _in(ch)
        for m, ft, d in _q(con, f"SELECT mint, first_ts, dev FROM group_fetched WHERE mint IN ({q})", ch):
            if ft:
                created[m] = min(x for x in (created.get(m), ft) if x)
            if d:
                dev.setdefault(m, d)
        for m, ft in _q(con, f"SELECT mint, MIN(first_buy_ts) FROM early_buyers WHERE mint IN ({q}) GROUP BY mint", ch):
            if ft:
                created[m] = min(x for x in (created.get(m), ft) if x)
        for m, ft, d in _q(con, f"SELECT token, first_trade_ts, dev FROM precall_tokens WHERE token IN ({q})", ch):
            if ft:
                created[m] = min(x for x in (created.get(m), ft) if x)
            if d:
                dev.setdefault(m, d)
    hc = _ro(p["hype_db"])
    for ch in _chunks(toks):
        for m, ts, cr in _q(hc, f"SELECT mint, ts, creator FROM live_launches WHERE pool != 'migration' AND mint IN "
                                f"({_in(ch)})", ch):
            created[m] = min(x for x in (created.get(m), ts) if x)
            if cr:
                dev.setdefault(m, cr)
    if hc is not None:
        hc.close()
    n = 0
    for tok, cs in calls.items():
        cs.sort()
        t0, first_h = cs[0][0], cs[0][1]
        mc0 = next((m for _t, _h, m in cs if m), None)
        if mc0 is None or mc0 < c["min_t0_mcap"]:
            continue
        wave = [x for x in cs if x[0] <= t0 + 86400]
        nid = member_of.get(first_h)
        ws = max(int(t0 - c["pre_window_s"]), int(created.get(tok) or 0))
        con.execute("""INSERT INTO preshill_tokens (token, net, t0, first_handle, n_calls, n_callers, calls, wave_end,
            mcap_t0, first_public_ts, window_start, dev) VALUES (?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(token) DO UPDATE SET
            net = excluded.net, t0 = excluded.t0, first_handle = excluded.first_handle, n_calls = excluded.n_calls,
            n_callers = excluded.n_callers, calls = excluded.calls, wave_end = excluded.wave_end,
            mcap_t0 = excluded.mcap_t0, first_public_ts = excluded.first_public_ts,
            window_start = excluded.window_start, dev = COALESCE(excluded.dev, dev),
            built_ts = CASE WHEN excluded.t0 != t0 THEN NULL ELSE built_ts END""",
                    (tok, nid, t0, first_h, len(cs), len({h for _t, h, _m in cs}),
                     json.dumps([[h, t] for t, h, _m in wave[:30]]), wave[-1][0] + int(c["wave_tail_s"]), mc0,
                     pub.get(tok), ws, dev.get(tok)))
        n += 1
    con.commit()
    return n


# ===================================================================================================================
# 2) Helius for the missing windows, the wallets' own sells
# ===================================================================================================================
def fetch_candidates(con, c, now):
    """[(token, since, until)] of tokens never fetched by us whose pre-shill window no Helius cache of ours holds:
    precall's window before the first call covers the tail up to T0 (only its read part when it stopped early),
    groupdisc's first 30 min the start. A window fully covered is returned with since >= until (marked, no credits).
    Most network callers first, newest first."""
    rows = _q(con, """SELECT t.token, t.window_start, t.t0 FROM preshill_tokens t LEFT JOIN preshill_fetched f
        ON f.key = t.token WHERE f.key IS NULL AND t.t0 >= ? AND t.t0 <= ? ORDER BY t.n_callers DESC, t.t0 DESC""",
              (now - int(c["days"]) * 86400, now - 600))
    out = []
    for ch in _chunks(rows):
        toks = [r[0] for r in ch]
        pf = {m: (s, u, o, cp) for m, s, u, o, cp in _q(con, f"SELECT mint, since_ts, until_ts, oldest_ts, complete FROM "
                                                         f"precall_fetched WHERE mint IN ({_in(toks)})", toks)}
        gf = dict(_q(con, f"SELECT mint, first_ts FROM group_fetched WHERE mint IN ({_in(toks)})", toks))
        for tok, ws, t0 in ch:
            since, until = int(ws or t0 - c["pre_window_s"]), int(t0)
            if gf.get(tok):
                since = max(since, int(gf[tok]) + 1800)
            if tok in pf:
                s, u, o, cp = pf[tok]
                lo = (s if cp else (o or u)) or u
                if u and u >= until - 60 and lo:
                    until = min(until, int(lo))
                elif u and lo and lo <= since:
                    since = max(since, int(u))
            out.append((tok, since, until))
    return out


def _parse(txs, mint, wallet=None, src="helius"):
    """Rows for preshill_trades from raw txs (signer-attributed: gd.owner_trades); only `wallet`'s when given."""
    rows = []
    for tx in txs:
        trades, payer, _s = gd.owner_trades(tx, mint)
        sig = ((tx.get("transaction") or {}).get("signatures") or ["?"])[0]
        for o, side, amount, sol in trades:
            if (wallet is None or o == wallet) and abs(sol) >= DUST_SOL:
                rows.append((mint, o, sig, tx.get("blockTime") or 0, tx.get("slot"), side, abs(sol), amount, payer, src))
    return rows


def _mints_of(tx, wallet):
    """Mints (not WSOL) whose balance of `wallet` changed in one tx."""
    meta = tx.get("meta") or {}
    out = set()
    for side in ("preTokenBalances", "postTokenBalances"):
        for b in meta.get(side) or []:
            if b.get("owner") == wallet and b.get("mint") and b.get("mint") != WSOL:
                out.add(b["mint"])
    return out


def _fetched(con, key, kind, now, credits, txs, since, until, complete):
    ts = [t.get("blockTime") for t in txs if t.get("blockTime")]
    con.execute("INSERT OR REPLACE INTO preshill_fetched VALUES (?,?,?,?,?,?,?,?,?,?)",
                (key, kind, now, credits, len(txs), since, until, min(ts) if ts else None, max(ts) if ts else None,
                 int(bool(complete))))


def _meter():
    spent = [0]

    def on_credits(n):
        spent[0] += n
    return spent, on_credits


def fetch_windows(con, c, now, budget, fetch=None, log=print):
    """Helius for the pre-shill windows nobody of us read, within `budget` credits. -> (mints read, credits spent)."""
    if budget <= 0:
        return 0, 0
    if fetch is None:
        from wallets import rpc
        fetch = rpc.fetch
    per = int(c["pre_pages"]) * 10
    spent, on_credits = _meter()
    n = 0
    for tok, since, until in fetch_candidates(con, c, now):
        if since >= until:   # our caches already hold the whole window
            _fetched(con, tok, "mint", now, 0, [], since, until, True)
            continue
        if spent[0] + per > budget:
            break
        before = spent[0]
        try:
            txs, complete = fetch(tok, since_ts=since, until_ts=until, max_pages=int(c["pre_pages"]), oldest_first=False,
                                  on_credits=on_credits)
        except Exception as e:  # noqa: BLE001 - one mint fails, the pass goes on (and it is tried again next night)
            log(f"shill mreža: {tok[:6]}… Helius {type(e).__name__}: {str(e)[:80]}")
            continue
        con.executemany("INSERT OR IGNORE INTO preshill_trades VALUES (?,?,?,?,?,?,?,?,?,?)", _parse(txs, tok))
        _fetched(con, tok, "mint", now, spent[0] - before, txs, since, until, complete)
        con.execute("UPDATE preshill_tokens SET built_ts = NULL WHERE token = ?", (tok,))
        con.commit()
        n += 1
    con.commit()
    return n, spent[0]


def fetch_sells(con, c, now, budget, skip=frozenset(), fetch=None, log=print):
    """One page of a wallet's own history from its pre-shill buy to T0 + 24 h, for the wallets with >= min_tokens
    pre-shill tokens whose sell we do not know (once per wallet and token). -> (pairs read, credits spent)."""
    if budget <= 0:
        return 0, 0
    if fetch is None:
        from wallets import rpc
        fetch = rpc.fetch
    rows = _q(con, """SELECT b.wallet, b.token, b.buy_ts, t.t0, w.n FROM preshill_buys b
        JOIN preshill_tokens t ON t.token = b.token
        JOIN (SELECT wallet, COUNT(*) n FROM preshill_buys WHERE bundle = 0 GROUP BY wallet HAVING COUNT(*) >= ?) w
          ON w.wallet = b.wallet
        LEFT JOIN preshill_fetched f ON f.key = b.wallet || '|' || b.token
        WHERE b.sold_ts IS NULL AND b.bundle = 0 AND f.key IS NULL AND t.t0 <= ? AND t.t0 >= ?
        ORDER BY w.n DESC, b.wallet, t.t0 DESC""", (int(c["min_tokens"]), now - 3600, now - int(c["days"]) * 86400))
    spent, on_credits = _meter()
    n = 0
    for w, tok, bts, t0, _n in rows:
        if w in skip:
            continue
        if spent[0] + 10 > budget:
            break
        before = spent[0]
        until = min(int(t0) + int(c["post_s"]), now)
        try:
            txs, complete = fetch(w, since_ts=int(bts) - 1, until_ts=until, max_pages=1, oldest_first=True,
                                  on_credits=on_credits)
        except Exception as e:  # noqa: BLE001
            log(f"shill mreža: novčanik {w[:6]}… Helius {type(e).__name__}: {str(e)[:80]}")
            continue
        rows_w = []
        for tx in txs:   # the page also shows what else the wallet traded: a page full in < 12 h is a bot
            for m in _mints_of(tx, w):
                rows_w += _parse([tx], m, w, "sell")
        con.executemany("INSERT OR IGNORE INTO preshill_trades VALUES (?,?,?,?,?,?,?,?,?,?)", rows_w)
        _fetched(con, f"{w}|{tok}", "sell", now, spent[0] - before, txs, int(bts) - 1, until, complete)
        con.execute("UPDATE preshill_tokens SET built_ts = NULL WHERE token = ?", (tok,))
        n += 1
    con.commit()
    return n, spent[0]


# ===================================================================================================================
# 2) buyers from every free source
# ===================================================================================================================
SRC_RANK = {"helius": 0, "sell": 0, "poll": 0, "precall": 1, "grupe": 1, "pumpportal": 2, "webhook": 3, "events": 4,
            "rani": 5}


def _sources(con, p, toks, sol_usd):
    """{token: [(wallet, ts, side, sol, tokens, slot, payer, mcap_usd, src, key)]} from every source we have; key is
    events.db's uid of the trade (None when unknown), so one trade seen in two feeds counts once."""
    by = defaultdict(list)
    for ch in _chunks(toks):
        q = _in(ch)
        for m, w, sig, ts, slot, side, sol, amt, payer, src in _q(
                con, f"SELECT mint, wallet, sig, ts, slot, side, sol, tokens, payer, src FROM preshill_trades WHERE "
                     f"mint IN ({q})", ch):
            by[m].append((w, ts, side, sol, amt, slot, payer, None, src or "helius", _uid(sig, m)))
        for m, w, sig, ts, slot, side, sol, amt, payer in _q(
                con, f"SELECT mint, wallet, sig, ts, slot, side, sol, tokens, payer FROM precall_trades WHERE "
                     f"mint IN ({q})", ch):
            by[m].append((w, ts, side, sol, amt, slot, payer, None, "precall", _uid(sig, m)))
        for m, w, sig, ts, slot, side, sol, amt, payer, mc in _q(
                con, f"SELECT mint, wallet, sig, ts, slot, side, sol, tokens, payer, mcap_usd FROM group_buys WHERE "
                     f"mint IN ({q})", ch):
            by[m].append((w, ts, side, sol, amt, slot, payer, mc, "grupe", _uid(sig, m)))
        for m, w, ts, sin, slot, sts, sout in _q(
                con, f"SELECT mint, wallet, first_buy_ts, sol_in, slot, sold_ts, sol_out FROM early_buyers WHERE "
                     f"mint IN ({q})", ch):
            by[m].append((w, ts, "buy", sin, None, slot, None, None, "rani", None))
            if sts:
                by[m].append((w, sts, "sell", sout, None, None, None, None, "rani", None))
    hc = _ro(p["hype_db"])
    if hc is not None:
        for ch in _chunks(toks):
            q = _in(ch)
            for m, w, sig, ts, side, sol, amt, mcs in _q(
                    hc, f"SELECT mint, wallet, sig, ts, side, sol, tokens, mcap_sol FROM live_trades WHERE mint IN ({q})",
                    ch):
                by[m].append((w, ts, side, sol, amt, None, None, (mcs * sol_usd) if mcs else None, "pumpportal",
                              _uid(sig, m)))
            for m, w, sig, ts, side, sol in _q(hc, f"SELECT mint, wallet, sig, ts, side, sol FROM chain_trades WHERE "
                                                   f"mint IN ({q})", ch):
                by[m].append((w, ts, side, sol, None, None, None, None, "webhook", _uid(sig, m)))
        hc.close()
    evc = _ro(p.get("events_db"))
    if evc is not None:
        for ch in _chunks(toks):
            for m, w, ts, typ, sol, slot, mc, u in _q(
                    evc, f"SELECT mint, actor, ts, type, sol_amount, slot, mcap_usd, uid FROM events WHERE type IN "
                         f"('wallet_buy', 'wallet_sell') AND mint IN ({_in(ch)})", ch):
                by[m].append((w, int(ts // 1000) if ts and ts > 1e12 else ts, "buy" if typ == "wallet_buy" else "sell",
                              sol, None, slot, None, mc, "events", u))
        evc.close()
    return by


def merge(rows):
    """Rows of one token -> {wallet: [rows]}: one row per trade (events.db uid / signature), the richest source kept;
    rows without a key (early_buyers) only for a side the wallet has no other row of."""
    by_w = defaultdict(list)
    for r in rows:
        if r[0] and r[1] is not None and r[2] in ("buy", "sell"):
            by_w[r[0]].append(r)
    out = {}
    for w, rs in by_w.items():
        keep = []
        for side in ("buy", "sell"):
            srs = sorted((r for r in rs if r[2] == side), key=lambda r: (SRC_RANK.get(r[8], 9), r[1]))
            seen, keyed = set(), []
            for r in srs:
                if r[9] is not None and r[9] not in seen:
                    seen.add(r[9])
                    keyed.append(r)
            keep += keyed or [r for r in srs if r[9] is None]
        out[w] = sorted(keep, key=lambda r: r[1])
    return out


def token_buyers(rows, t, c, sol_usd=150.0, supply=None):
    """rows: one token's rows (_sources); t: {"t0", "window_start"} -> {wallet: {"buy_ts", "slot", "sol_in",
    "mcap_usd", "sold_ts", "sol_out", "payer", "bundle", "src"}} for the wallets that bought in [window_start, t0).
    bundle: the first buy fell in a slot where >= bundle_min wallets bought the token. Dust (known SOL under min_sol)
    is left out. Sells up to t0 + post_s; sol_out is scaled down when the wallet sold more tokens than it bought in
    the window (later buys)."""
    ws, t0 = int(t.get("window_start") or 0), int(t["t0"])
    per = merge(rows)
    slot_ws = defaultdict(set)
    for w, rs in per.items():
        for r in rs:
            if r[2] == "buy" and ws <= r[1] < t0 and r[5] is not None:
                slot_ws[r[5]].add(w)
    bundled = {s for s, x in slot_ws.items() if len(x) >= int(c["bundle_min"])}
    out = {}
    for w, rs in per.items():
        buys = [r for r in rs if r[2] == "buy" and ws <= r[1] < t0]
        if not buys:
            continue
        known = [abs(r[3]) for r in buys if r[3] is not None]
        sol_in = round(sum(known), 6) if known else None
        if sol_in is not None and sol_in < c["min_sol"]:
            continue
        first = buys[0]
        mcap = next((r[7] for r in buys if r[7]), None)
        if mcap is None:
            r = next((r for r in buys if r[3] and r[4]), None)
            if r and (supply or gd.PUMP_SUPPLY):
                mcap = abs(r[3]) / r[4] * (supply or gd.PUMP_SUPPLY) * sol_usd
        sells = [r for r in rs if r[2] == "sell" and first[1] < r[1] <= t0 + int(c["post_s"])]
        sold_ts = sells[0][1] if sells else None
        sk = [abs(r[3]) for r in sells if r[3] is not None]
        sol_out = round(sum(sk), 6) if sk else None
        tin = sum(r[4] for r in buys if r[4])
        tout = sum(abs(r[4]) for r in sells if r[4])
        if sol_out is not None and tin and tout > tin * 1.05:
            sol_out = round(sol_out * tin / tout, 6)
        out[w] = {"buy_ts": int(first[1]), "slot": first[5], "sol_in": sol_in, "mcap_usd": _r(mcap, 0),
                  "sold_ts": int(sold_ts) if sold_ts else None, "sol_out": sol_out,
                  "payer": next((r[6] for r in buys if r[6]), None),
                  "bundle": int(any(r[5] in bundled for r in buys if r[5] is not None)),
                  "src": ",".join(sorted({r[8] for r in buys + sells}))}
    return out


def build_buys(con, p, c, now, tokens=None, sol_usd=None):
    """preshill_buys of `tokens` (default: every token of the last `days` not built since its data changed) from the
    free sources. Returns the number of tokens built."""
    sol_usd = sol_usd or _sol_usd()
    if tokens is None:
        rows = _q(con, "SELECT token, t0, window_start FROM preshill_tokens WHERE t0 >= ? AND (built_ts IS NULL OR "
                       "t0 >= ?)", (now - int(c["days"]) * 86400, now - 2 * 86400))
    else:
        rows = []
        for ch in _chunks(tokens):
            rows += _q(con, f"SELECT token, t0, window_start FROM preshill_tokens WHERE token IN ({_in(ch)})", ch)
    supply = {}
    kc = _ro(p["kol_db"])
    for ch in _chunks([r[0] for r in rows]):
        supply.update(dict(_q(kc, f"SELECT token, supply FROM tokens WHERE supply > 0 AND token IN ({_in(ch)})", ch)))
    if kc is not None:
        kc.close()
    n = 0
    for ch in _chunks(rows, 100):
        src = _sources(con, p, [r[0] for r in ch], sol_usd)
        for tok, t0, ws in ch:
            got = token_buyers(src.get(tok) or [], {"t0": t0, "window_start": ws}, c, sol_usd, supply.get(tok))
            con.execute("DELETE FROM preshill_buys WHERE token = ?", (tok,))
            con.executemany("INSERT INTO preshill_buys VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                            [(tok, w, b["buy_ts"], b["slot"], b["sol_in"], b["mcap_usd"], b["sold_ts"], b["sol_out"],
                              b["payer"], b["bundle"], b["src"]) for w, b in got.items()])
            con.execute("UPDATE preshill_tokens SET buyers = ?, built_ts = ? WHERE token = ?", (len(got), now, tok))
            n += 1
        con.commit()
    return n


def peaks(con, p, c, now):
    """peak_ts / peak_mcap / peak_x of the tokens without one: the highest minute within 4 h after T0 (minute.db,
    a wick counts up to 3x the body), else the highest PumpPortal price within 24 h, else kol.db max24 (no time)."""
    rows = _q(con, "SELECT token, t0, mcap_t0 FROM preshill_tokens WHERE peak_x IS NULL AND t0 <= ? AND t0 >= ?",
              (now - 4 * 3600, now - int(c["days"]) * 86400))
    if not rows:
        return 0
    mc, hc, kc = _ro(p.get("minute_db")), _ro(p["hype_db"]), _ro(p["kol_db"])
    n = 0
    try:
        for tok, t0, m0 in rows:
            pk = None
            if mc is not None:
                try:
                    from kol import minute
                    cs = minute.candles_for(mc, tok, t0 - 60, t0 + 4 * 3600)
                except Exception:  # noqa: BLE001
                    cs = []
                base = next((x[4] for x in cs if x[0] == t0 - t0 % 60), None) or (cs[0][1] if cs else None)
                if cs and base:
                    top = max(cs, key=lambda x: min(x[2], max(x[1], x[4]) * 3))
                    pk = (top[0], min(top[2], max(top[1], top[4]) * 3) / base)
            if pk is None and hc is not None:
                px = _q(hc, "SELECT ts, price_sol FROM live_trades WHERE mint = ? AND ts BETWEEN ? AND ? AND price_sol > 0 "
                            "ORDER BY ts", (tok, t0 - 600, t0 + int(c["post_s"])))
                before = [x for x in px if x[0] <= t0]
                after = [x for x in px if x[0] >= t0]
                base = (before[-1][1] if before else after[0][1]) if px else None
                if after and base:
                    top = max(after, key=lambda x: x[1])
                    pk = (top[0], top[1] / base)
            if pk is None and kc is not None:
                r = _q(kc, "SELECT max24 FROM calls WHERE token = ? AND kind = 'call' AND max24 IS NOT NULL ORDER BY "
                           "ABS(ts - ?) LIMIT 1", (tok, t0))
                if r:
                    pk = (None, 1 + r[0][0])
            if pk is None:
                continue
            x = max(1.0, pk[1])
            con.execute("UPDATE preshill_tokens SET peak_ts = ?, peak_x = ?, peak_mcap = ? WHERE token = ?",
                        (pk[0], round(x, 3), _r(m0 * x, 0) if m0 else None, tok))
            n += 1
    finally:
        for x in (mc, hc, kc):
            if x is not None:
                x.close()
    con.commit()
    return n


# ===================================================================================================================
# 3) the wallets
# ===================================================================================================================
def exclude_labels():
    """wallets/store.BAD_LABELS without the labels this module looks for (insider, rugger, funder_of_rugger)."""
    try:
        from wallets import store as wstore
        return set(wstore.BAD_LABELS) - KEEP_LABELS
    except Exception:  # noqa: BLE001
        return {"bot", "bundler", "cex", "dev", "mev", "sniper"}


def _labels(p, wallets):
    return gd._labels(p.get("wallet_db"), wallets)


def _busy(p, wallets, tpd):
    """Wallets with more than `tpd` trades a day in our own scoring (wallets.db stats trades_per_day)."""
    out = set()
    wc = _ro(p.get("wallet_db"))
    if wc is None:
        return out
    try:
        for ch in _chunks(wallets, 500):
            for w, st in _q(wc, f"SELECT wallet, stats FROM wallets WHERE wallet IN ({_in(ch)})", ch):
                try:
                    if (json.loads(st or "{}") or {}).get("trades_per_day", 0) > tpd:
                        out.add(w)
                except (ValueError, TypeError, AttributeError):
                    pass
    finally:
        wc.close()
    return out


def bots(con, p, c, since, cand):
    """Bots among `cand` (see the module text, 2): > bot_tpd trades a day, groupdisc's rate rules, a fetched page of
    100 trades inside 12 h."""
    tpd = int(c["bot_tpd"])
    out = _busy(p, cand, tpd)
    for table in ("preshill_trades", "precall_trades", "group_buys"):
        out |= {w for (w,) in _q(con, f"SELECT DISTINCT wallet FROM {table} WHERE ts >= ? GROUP BY wallet, ts / 86400 "
                                      f"HAVING COUNT(*) > ?", (since, tpd))}
        out |= {w for (w,) in _q(con, f"SELECT DISTINCT wallet FROM {table} WHERE ts >= ? GROUP BY wallet, ts / 60 "
                                      f"HAVING COUNT(*) > ?", (since, int(c["bot_tx_min"])))}
        out |= {w for (w,) in _q(con, f"SELECT DISTINCT wallet FROM {table} WHERE ts >= ? AND slot IS NOT NULL GROUP BY "
                                      f"wallet, mint, slot HAVING COUNT(DISTINCT side) > 1", (since,))}
    hc = _ro(p["hype_db"])
    if hc is not None:
        out |= {w for (w,) in _q(hc, "SELECT DISTINCT wallet FROM live_trades GROUP BY wallet, ts / 86400 HAVING "
                                     "COUNT(*) > ?", (tpd,))}
        out |= {w for (w,) in _q(hc, "SELECT DISTINCT wallet FROM live_trades GROUP BY wallet, ts / 60 HAVING "
                                     "COUNT(*) > ?", (int(c["bot_tx_min"]),))}
        hc.close()
    for key, n_tx, lo, hi in _q(con, "SELECT key, n_tx, oldest_ts, newest_ts FROM preshill_fetched WHERE kind IN "
                                     "('sell', 'poll') AND n_tx >= 100"):
        if lo and hi and hi - lo < 86400 * 100 / tpd:
            out.add(key.split("|")[0])
    return out & set(cand)


def _pools(p, toks):
    """Pool addresses of `toks` (kol.db tokens.pair, events.db pools): an LP is never a buyer."""
    out = set()
    kc = _ro(p["kol_db"])
    for ch in _chunks(toks):
        out |= {x for (x,) in _q(kc, f"SELECT pair FROM tokens WHERE pair IS NOT NULL AND token IN ({_in(ch)})", ch)}
    if kc is not None:
        kc.close()
    evc = _ro(p.get("events_db"))
    for ch in _chunks(toks):
        out |= {x for (x,) in _q(evc, f"SELECT pool FROM pools WHERE pool IS NOT NULL AND token IN ({_in(ch)})", ch)}
    if evc is not None:
        evc.close()
    return out


def wallet_stats(obs, cut, c):
    """obs: one dict per pre-shill token of a wallet {"token", "t0", "buy_ts", "sol_in", "mcap_usd", "sold_ts",
    "sol_out", "wave_end", "peak_ts"} (dev, bundle already out). cut: T0 before it select, after it confirm.
    -> stats with status confirmed | candidate | watch | None."""
    if not obs:
        return None
    for o in obs:
        o["min_before"] = (o["t0"] - o["buy_ts"]) / 60
        o["sel"] = o["t0"] < cut
        o["closed"] = bool(o.get("sold_ts")) and o.get("sol_in") is not None and o.get("sol_out") is not None
        o["pnl"] = (o["sol_out"] - o["sol_in"]) if o["closed"] else None
        o["hold_min"] = (o["sold_ts"] - o["buy_ts"]) / 60 if o.get("sold_ts") else None
        o["into_wave"] = int(bool(o.get("sold_ts")) and o["t0"] <= o["sold_ts"] <= (o.get("wave_end") or o["t0"]))

    def part(xs):
        closed = [o["pnl"] for o in xs if o["pnl"] is not None]
        return {"n": len(xs), "avg_min": _mean(o["min_before"] for o in xs), "med_min": _med(o["min_before"] for o in xs),
                "pnl": sum(closed) if closed else None, "n_closed": len(closed),
                "hit": sum(1 for x in closed if x > 0) / len(closed) if closed else None}

    def ok(d, n_min):
        return (d["n"] >= n_min and d["avg_min"] is not None and c["min_before_min"] <= d["avg_min"] <= c["max_before_min"]
                and (d["pnl"] or 0) > 0)

    full = part(obs)
    sel = part([o for o in obs if o["sel"]])
    conf = part([o for o in obs if not o["sel"]])
    full_ok, sel_ok, conf_ok = ok(full, c["min_tokens"]), ok(sel, c["min_tokens"]), ok(conf, c["min_confirm"])
    status = ("confirmed" if sel_ok and conf_ok else "candidate" if full_ok else "watch" if full["n"] >= 2 else None)
    sold = [o for o in obs if o.get("sold_ts")]
    score = (full["n"] + 2 * (full["hit"] or 0) + max(-5.0, min(10.0, full["pnl"] or 0)) / 2
             + (3 if status == "confirmed" else 0))
    return {"status": status, "score": round(score, 2), "n_tokens": full["n"], "med_min": _r(full["med_min"], 1),
            "avg_min": _r(full["avg_min"], 1), "entry_mcap_med": _r(_med(o.get("mcap_usd") for o in obs), 0),
            "pnl_sol": _r(full["pnl"]), "hit_rate": _r(full["hit"], 3), "n_closed": full["n_closed"],
            "med_hold_min": _r(_med(o["hold_min"] for o in obs), 1),
            "sold_into_wave": _r(sum(o["into_wave"] for o in sold) / len(sold), 3) if sold else None,
            "n_sel": sel["n"], "n_conf": conf["n"], "pnl_sel": _r(sel["pnl"]), "pnl_conf": _r(conf["pnl"]),
            "avg_min_sel": _r(sel["avg_min"], 1), "avg_min_conf": _r(conf["avg_min"], 1),
            "last_ts": max(o["buy_ts"] for o in obs), "tokens": [o["token"] for o in sorted(obs, key=lambda o: -o["t0"])][:20]}


def clusters(wallets, owner, slot_pairs, c):
    """{wallet: cluster id}: wallets with the same owner id (shared non-hub funder, gd.owner_ids) or that bought
    the same token in the same slot on >= cluster_slot_min tokens are one cluster (id = its smallest address);
    a wallet alone is its own."""
    from kol import together
    ws = set(wallets)
    pairs = [(a, b) for (a, b), n in slot_pairs.items() if n >= c["cluster_slot_min"] and a in ws and b in ws]
    by_owner = defaultdict(list)
    for w in ws:
        by_owner[owner.get(w, w)].append(w)
    for grp in by_owner.values():
        pairs += [(grp[0], x) for x in grp[1:]]
    out = {w: w for w in ws}
    for comp in together.components(pairs):
        cid = min(comp)
        for w in comp:
            if w in ws:
                out[w] = cid
    return out


def owner_labels(trade_db=None):
    try:
        from kol import precall
        return precall.owner_labels(trade_db)
    except Exception:  # noqa: BLE001
        return {}


def analyze(con, p, c, now):
    """The wallet analysis over the network tokens of the last `days`: preshill_wallets rewritten. -> summary."""
    since = now - int(c["days"]) * 86400
    cut = now - int(c["days"]) * 86400 // 3
    toks = {t: {"t0": t0, "dev": dv, "wave_end": we, "peak_ts": pk}
            for t, t0, dv, we, pk in _q(con, "SELECT token, t0, dev, wave_end, peak_ts FROM preshill_tokens WHERE t0 >= ?",
                                        (since,))}
    rows = defaultdict(list)
    for tok, w, bts, slot, sin, mc, sts, sout, payer, bundle in _q(
            con, "SELECT token, wallet, buy_ts, slot, sol_in, mcap_usd, sold_ts, sol_out, payer, bundle FROM preshill_buys"):
        if tok in toks:
            rows[w].append((tok, bts, slot, sin, mc, sts, sout, payer, bundle))
    cand = {w for w, rs in rows.items() if sum(1 for r in rs if not r[8]) >= 2}
    paid = _q(con, "SELECT DISTINCT payer, wallet FROM preshill_trades WHERE payer IS NOT NULL AND payer != wallet")
    paid += _q(con, "SELECT DISTINCT payer, wallet FROM precall_trades WHERE payer IS NOT NULL AND payer != wallet")
    paid += _q(con, "SELECT DISTINCT payer, wallet FROM group_buys WHERE payer IS NOT NULL AND payer != wallet")
    paid += [(r[7], w) for w, rs in rows.items() for r in rs if r[7] and r[7] != w]
    relay = gd.relayers(paid, c["relayer_min"])
    cand -= relay
    why = {}
    for w in bots(con, p, c, since, cand) if cand else set():
        why[w] = "bot (više od 200 tradeova dnevno ili brzina bota)"
    bad = exclude_labels()
    for w, labs in _labels(p, cand).items():
        hit = sorted(set(labs) & bad)
        if hit and w not in why:
            why[w] = f"oznaka {', '.join(hit)}"
    for w, lab in owner_labels(p.get("trade_db")).items():
        if w in cand and (lab or {}).get("label") in ("bot", "sniper") and w not in why:
            why[w] = f"vlasnik ga je označio: {lab['label']}"
    for w in _pools(p, toks) & cand:
        why.setdefault(w, "adresa poola (LP)")
    funders = gd._funders(p, toks, cand) if cand else defaultdict(set)
    for pay, w in paid:
        if w in cand and pay not in relay:
            funders[w].add(pay)
    fan = Counter(f for fs in funders.values() for f in fs)
    hubs = {f for f, n in fan.items() if n > c["hub_min"]}
    for w in cand & hubs:
        why.setdefault(w, "burza ili čvorište financiranja (CEX)")
    owner = gd.owner_ids(funders, hubs, relay)
    old = {w: (s, fs, st) for w, s, fs, st in _q(con, "SELECT wallet, status, first_seen, status_ts FROM preshill_wallets")}
    res, slot_of = {}, defaultdict(list)
    n_dev = 0
    for w in sorted(cand):
        obs = []
        for tok, bts, slot, sin, mc, sts, sout, payer, bundle in rows[w]:
            d = toks[tok]
            dv = d["dev"]
            if dv and (w == dv or payer == dv or dv in funders.get(w, ())):
                n_dev += 1
                continue
            if bundle:
                continue
            if slot is not None:
                slot_of[(tok, slot)].append(w)
            obs.append({"token": tok, "t0": d["t0"], "buy_ts": bts, "sol_in": sin, "mcap_usd": mc, "sold_ts": sts,
                        "sol_out": sout, "wave_end": d["wave_end"], "peak_ts": d["peak_ts"]})
        st = wallet_stats(obs, cut, c)
        if not st or not st["status"]:
            continue
        if w in why:
            st.update(status="excluded", why=why[w])
        res[w] = st
    slot_pairs = Counter()
    for ws in slot_of.values():
        ws = sorted(set(ws))
        for i in range(len(ws)):
            for j in range(i + 1, len(ws)):
                slot_pairs[(ws[i], ws[j])] += 1
    kept = [w for w, s in res.items() if s["status"] != "excluded"]
    cl = clusters(kept, owner, slot_pairs, c)
    size = Counter(cl.values())
    con.execute("DELETE FROM preshill_wallets")
    for w, s in res.items():
        o = old.get(w)
        first = o[1] if o else now
        sts = o[2] if o and o[0] == s["status"] else now
        cid = cl.get(w)
        s["cluster_size"] = size.get(cid, 0) if cid else 0
        s["funders"] = sorted(f for f in funders.get(w, ()) if f not in hubs and f not in relay and fan[f] >= 2)[:5]
        stats = {k: v for k, v in s.items() if k not in ("status", "why", "score")}
        con.execute("INSERT INTO preshill_wallets VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (w, s["status"], s.get("why"), cid, s["score"], s["n_tokens"], s["med_min"], s["avg_min"],
                     s["entry_mcap_med"], s["pnl_sol"], s["hit_rate"], s["med_hold_min"], s["sold_into_wave"],
                     s["n_sel"], s["n_conf"], s["last_ts"], json.dumps(stats, separators=(",", ":")), first, sts, now))
    con.commit()
    stc = Counter(s["status"] for s in res.values())
    return {"tokens": len(toks), "wallets": len(res), "confirmed": stc.get("confirmed", 0),
            "candidates": stc.get("candidate", 0), "watch": stc.get("watch", 0), "excluded": stc.get("excluded", 0),
            "clusters": sum(1 for n in size.values() if n >= 2), "relayers": len(relay), "dev_buys": n_dev,
            "skip": sorted(set(why) | relay | (cand - set(res)))}   # no sells to read for these


# ===================================================================================================================
# 4) signal, exit, measurement
# ===================================================================================================================
def pre_shill_wallets(con):
    """{wallet: (status, cluster, cluster size)} of candidate and confirmed wallets."""
    out = {}
    for w, st, cl, stats in _q(con, "SELECT wallet, status, cluster, stats FROM preshill_wallets WHERE status IN "
                                    "('candidate', 'confirmed')"):
        try:
            n = (json.loads(stats or "{}") or {}).get("cluster_size") or 1
        except ValueError:
            n = 1
        out[w] = (st, cl or w, n)
    return out


def recent_buys(con, p, wallets, since, sol_usd):
    """[(token, wallet, ts, mcap_usd)] of `wallets` since `since` from our feeds (no API)."""
    ws = sorted(wallets)
    out = []
    if not ws:
        return out
    for ch in _chunks(ws):
        q = _in(ch)
        for table, mc in (("preshill_trades", "NULL"), ("precall_trades", "NULL"), ("group_buys", "mcap_usd")):
            out += _q(con, f"SELECT mint, wallet, ts, {mc} FROM {table} WHERE side = 'buy' AND ts >= ? AND wallet IN ({q})",
                      (since, *ch))
    hc = _ro(p["hype_db"])
    if hc is not None:
        for ch in _chunks(ws):
            q = _in(ch)
            out += [(m, w, ts, mcs * sol_usd if mcs else None) for m, w, ts, mcs in
                    _q(hc, f"SELECT mint, wallet, ts, mcap_sol FROM live_trades WHERE side = 'buy' AND ts >= ? AND "
                           f"wallet IN ({q})", (since, *ch))]
            out += [(m, w, ts, None) for m, w, ts in
                    _q(hc, f"SELECT mint, wallet, ts FROM chain_trades WHERE side = 'buy' AND ts >= ? AND wallet IN ({q})",
                       (since, *ch))]
        hc.close()
    evc = _ro(p.get("events_db"))
    if evc is not None:
        for ch in _chunks(ws):
            out += [(m, w, ts // 1000, mc) for m, w, ts, mc in
                    _q(evc, f"SELECT mint, actor, ts, mcap_usd FROM events WHERE type = 'wallet_buy' AND ts >= ? AND "
                            f"actor IN ({_in(ch)})", (since * 1000, *ch))]
        evc.close()
    return [(m, w, int(ts), mc) for m, w, ts, mc in out if m and ts]


def poll(con, c, now, wallets, budget, fetch=None, log=print):
    """The newest page of the best wallets' own history (10 credits each, at most once in poll_gap_s), stored as
    trades (src poll), so a pre-shill buy is seen within one pass although no feed of ours follows them.
    -> (wallets read, credits spent)."""
    if budget <= 0 or not wallets:
        return 0, 0
    if fetch is None:
        from wallets import rpc
        fetch = rpc.fetch
    spent, on_credits = _meter()
    n = 0
    for w in wallets[:int(c["poll_wallets"])]:
        last = int(float(kv(con, f"poll:{w}") or 0))
        if now - last < c["poll_gap_s"]:
            continue
        if spent[0] + 10 > budget:
            break
        before = spent[0]
        since = max(last, now - int(c["poll_back_s"]))
        try:
            txs, complete = fetch(w, since_ts=since, until_ts=now, max_pages=1, oldest_first=False, on_credits=on_credits)
        except Exception as e:  # noqa: BLE001
            log(f"shill mreža: novčanik {w[:6]}… Helius {type(e).__name__}: {str(e)[:80]}")
            continue
        rows = []
        for tx in txs:
            for m in _mints_of(tx, w):
                rows += _parse([tx], m, w, "poll")
        con.executemany("INSERT OR IGNORE INTO preshill_trades VALUES (?,?,?,?,?,?,?,?,?,?)", rows)
        _fetched(con, w, "poll", now, spent[0] - before, txs, since, now, complete)
        kv(con, f"poll:{w}", now)
        n += 1
    con.commit()
    return n, spent[0]


def detect(buys, ws, called, c, have=frozenset()):
    """buys [(token, wallet, ts, mcap_usd)]; ws {wallet: (status, cluster, cluster size)}; called {token: first public
    call ts}. -> [{"token", "buy_ts", "wallets", "clusters", "mcap_usd"}]: >= signal_min_wallets pre-shill wallets,
    or one wallet of a cluster of 2+, bought the token within signal_window_s, and no public call came before the
    buy that completed it. have: tokens with a signal already."""
    by = defaultdict(dict)
    for m, w, ts, mc in sorted(buys, key=lambda b: b[2]):
        if w in ws and m not in have:
            by[m].setdefault(w, (ts, mc))
    out = []
    for m, first in by.items():
        seq = sorted((ts, w, mc) for w, (ts, mc) in first.items())
        for i, (ts, w, mc) in enumerate(seq):
            win = [x for x in seq[:i + 1] if ts - x[0] <= c["signal_window_s"]]
            big = any(ws[x[1]][2] >= 2 for x in win)
            if len(win) >= c["signal_min_wallets"] or big:
                if m in called and called[m] <= ts:
                    break   # a public call came first: not a pre-shill signal
                t_lo = win[0][0]   # every pre-shill wallet of that hour, also the ones that came after the trigger
                allw = [x for x in seq if t_lo <= x[0] <= t_lo + c["signal_window_s"]]
                out.append({"token": m, "buy_ts": int(ts), "wallets": [x[1] for x in allw],
                            "clusters": sorted({ws[x[1]][1] for x in allw}),
                            "mcap_usd": next((x[2] for x in reversed(allw) if x[2]), None)})
                break
    return out


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


def network_calls(p, members, since, until=None):
    """[(token, handle, ts)] calls of shill-network members since `since` (kol.db), oldest first."""
    kc = _ro(p["kol_db"])
    out = []
    if kc is None or not members:
        return out
    try:
        for ch in _chunks(sorted(members)):
            out += _q(kc, f"SELECT token, handle, ts FROM calls WHERE kind = 'call' AND ts >= ? AND ts <= ? AND "
                          f"handle IN ({_in(ch)})", (int(since), int(until or 2 ** 40), *ch))
    finally:
        kc.close()
    return sorted(out, key=lambda r: r[2])


def exits(con, p, c, now, members, since):
    """Shill-network calls since `since`: one negative-weight shadow line per token, and the EXIT of a token held
    through a pre_shill signal ("prodaj u callove"). -> shadow rows."""
    rows = []
    first = {}
    for tok, h, ts in network_calls(p, members, since, now):
        first.setdefault(tok, (int(ts), h))
    for tok, (ts, h) in first.items():
        if not kv(con, f"neg:{tok}"):
            kv(con, f"neg:{tok}", ts)
            rows.append((tok, "poziv callera (+1)", "shill mreža: težina -1, izlazna likvidnost",
                         {"handle": h, "call_ts": ts, "weight": -1}))
        sig = _q(con, "SELECT id, ts FROM preshill_signals WHERE token = ? AND exit_ts IS NULL AND ts <= ? AND ts >= ?",
                 (tok, ts, ts - int(c["exit_window_s"])))
        if sig:
            sid, sts = sig[0]
            con.execute("UPDATE preshill_signals SET exit_ts = ?, shill_ts = COALESCE(shill_ts, ?) WHERE id = ?",
                        (ts, ts, sid))
            rows.append((tok, "drži (kupci prije shill mreže)", "prodaj u callove",
                         {"signal_id": sid, "signal_ts": sts, "call_ts": ts, "handle": h,
                          "min_after_signal": round((ts - sts) / 60, 1)}))
    con.commit()
    return rows


def _price_at(cs, ts):
    m = int(ts) - int(ts) % 60
    x = next((k for k in cs if k[0] == m), None) or next((k for k in cs if m < k[0] <= m + 300), None)
    return (x[4] if x[0] == m else x[1]) if x else None


def measure_due(con, p, c, now, members, gt_cap=0):
    """Signals at least 4 h old without a result: path_outcome from the candles we can get (from the detection
    time), the shill network's first call after the signal, the first public call, and the result of selling into
    the network's call (exit_ret, after cost). -> (measured, GeckoTerminal reads)."""
    gt_left, n = [gt_cap], 0
    due = _q(con, "SELECT id, token, ts, exit_ts FROM preshill_signals WHERE measured_ts IS NULL AND ts <= ? AND ts >= ?",
             (now - 4 * 3600, now - 3 * 86400))
    if not due:
        return 0, 0
    pub = gd._public_first(p, {t for _i, t, _ts, _e in due})
    for sid, tok, ts, ex in due:
        cs = gd._candles(p, tok, ts, gt_left, now)
        o = gd.path_outcome(cs, ts, c) or {}
        calls = [r for r in network_calls(p, members, ts, ts + int(c["exit_window_s"])) if r[0] == tok]
        shill = calls[0][2] if calls else None
        ex = ex or shill
        e0, e1 = (_price_at(cs, ts), _price_at(cs, ex)) if ex else (None, None)
        er = _r(e1 / e0 - 1 - c["cost"]) if e0 and e1 else None
        fp = pub.get(tok)
        con.execute("UPDATE preshill_signals SET r1h=?, r4h=?, hit1h=?, hit4h=?, ev=?, shill_ts=COALESCE(shill_ts, ?), "
                    "first_public_ts=?, exit_ts=COALESCE(exit_ts, ?), exit_ret=?, measured_ts=? WHERE id=?",
                    (o.get("r1h"), o.get("r4h"), o.get("hit1h"), o.get("hit4h"), o.get("ev"), shill,
                     fp if fp and fp >= ts - 60 else None, ex, er, now, sid))
        n += 1
    con.commit()
    return n, gt_cap - gt_left[0]


def gate(cases, c):
    """cases: [ev] of measured signals -> None when the move to paper is earned, else the reason (Croatian)."""
    xs = [x for x in cases if x is not None]
    if len(xs) < c["gate_n"]:
        return f"izmjereno tek {len(xs)} od {c['gate_n']} signala kupaca prije shill mreže"
    ev = sum(xs) / len(xs)
    if ev <= 0:
        return f"EV {ev:+.1%} na {len(xs)} signala nije iznad nule"
    return None


def paper_refusal(con, now=None, path=None, cfg=None):
    """trade/settings.PAPER_GATES: None when pre_shill may go to paper, else why not. con: trade.db."""
    from trade import settings
    c = config(cfg)
    now = int(now or time.time())
    st = settings.flag_state(con)[FLAG]
    if st["mode"] != "shadow" or not st["since"]:
        return f"prvo najmanje {c['gate_days']} dana u sjeni"
    days = (now - st["since"]) / 86400
    if days < c["gate_days"]:
        return f"u sjeni tek {days:.1f} od {c['gate_days']} dana"
    ec = _ro(path or gd.db_path())
    rows = _q(ec, "SELECT ev FROM preshill_signals WHERE ev IS NOT NULL AND ts >= ?", (st["since"],))
    if ec is not None:
        ec.close()
    return gate([r[0] for r in rows], c)


# ===================================================================================================================
# the passes
# ===================================================================================================================
def _members(con):
    return {h for ms in networks(con).values() for h in ms}


def prune(con, c, now):
    keep = now - int(c["keep_days"]) * 86400
    con.execute("DELETE FROM preshill_buys WHERE token IN (SELECT token FROM preshill_tokens WHERE t0 < ?)", (keep,))
    con.execute("DELETE FROM preshill_tokens WHERE t0 < ?", (keep,))
    con.execute("DELETE FROM preshill_trades WHERE ts < ?", (keep,))
    con.execute("DELETE FROM preshill_runs WHERE ts < ?", (keep,))
    con.execute("DELETE FROM preshill_signals WHERE ts < ?", (keep,))
    con.execute("DELETE FROM preshill_kv WHERE key LIKE 'neg:%' AND CAST(value AS INTEGER) < ?", (keep,))
    con.execute("DELETE FROM preshill_kv WHERE key LIKE 'poll_day:%' AND key < ?", (f"poll_day:{_day(keep)}",))


def night(cfg=None, now=None, credits=None, log=print, fetch=None, sol_usd=None, force=False, **over):
    """The full pass (01-06 Zagreb under ops.heavy --night). None when the flag is off or a pass ran < night_gap_h ago."""
    p = paths(**over)
    m = mode(p.get("trade_db"))
    if m == "off":
        log("shill mreža: zastavica pre_shill je isključena, noćni prolaz ne radi ništa")
        return None
    c = config(cfg)
    now = int(now or time.time())
    con = connect(p["early_db"])
    try:
        last = int(float(kv(con, "last_night") or 0))
        if not force and now - last < c["night_gap_h"] * 3600:
            log(f"shill mreža: noćni prolaz je već bio prije {(now - last) / 3600:.1f} h, preskačem")
            return None
        sol = sol_usd or _sol_usd()
        net = build_networks(con, p, c, now, log)
        n_tok = collect_tokens(con, p, c, now)
        budget = int(c["night_credits"] if credits is None else credits)
        w_budget = int(budget * (1 - float(c["sell_share"])))
        n_read, spent = fetch_windows(con, c, now, w_budget, fetch, log)
        n_built = build_buys(con, p, c, now, sol_usd=sol)
        n_peak = peaks(con, p, c, now)
        res = analyze(con, p, c, now)
        n_sell, spent2 = fetch_sells(con, c, now, budget - spent, set(res["skip"]), fetch, log)
        if n_sell:
            build_buys(con, p, c, now, sol_usd=sol)
            res = analyze(con, p, c, now)
        measured, gt = measure_due(con, p, c, now, _members(con), c["gt_night"])
        prune(con, c, now)
        kv(con, "last_night", now)
        detail = {**net, **{k: v for k, v in res.items() if k != "skip"}, "network_tokens": n_tok,
                  "mints_read": n_read, "sells_read": n_sell, "credits": spent + spent2, "budget": budget,
                  "built": n_built, "peaks": n_peak, "measured": measured, "gt": gt}
        con.execute("INSERT INTO preshill_runs VALUES (?,?,?,?)", (now, "night", spent + spent2, json.dumps(detail)))
        con.commit()
        log(f"shill mreža (noć, {m}): {net['groups_checked']} velikih grupa provjereno, {net['shill_networks']} shill "
            f"mreža ({net['chained']} dijelova odbačeno kao lanac); {n_tok} tokena mreže, {res['confirmed']} potvrđenih "
            f"i {res['candidates']} kandidata, {res['clusters']} klastera, {res['excluded']} isključenih; Helius "
            f"{n_read} tokena + {n_sell} prodaja za {spent + spent2} kredita (strop {budget}); izmjereno {measured}")
        return detail
    finally:
        con.close()


def incremental(cfg=None, now=None, log=print, fetch=None, credits=None, sol_usd=None, **over):
    """The 30-minute pass: fresh network tokens and their buyers from our databases, the polls of the best wallets
    (capped), pre-shill signals, the network's calls as negative weight and exit, results of what became 4 h old.
    None when the flag is off (nothing read, written or paid)."""
    p = paths(**over)
    m = mode(p.get("trade_db"))
    if m == "off":
        return None
    c = config(cfg)
    now = int(now or time.time())
    con = connect(p["early_db"])
    try:
        sol = sol_usd or _sol_usd()
        members = _members(con)
        n_tok = collect_tokens(con, p, c, now) if members else 0
        fresh = [t for (t,) in _q(con, "SELECT token FROM preshill_tokens WHERE t0 >= ?", (now - 2 * 86400,))]
        n_built = build_buys(con, p, c, now, fresh, sol) if fresh else 0
        ws = pre_shill_wallets(con)
        best = [w for (w,) in _q(con, "SELECT wallet FROM preshill_wallets WHERE status IN ('candidate', 'confirmed') "
                                      "ORDER BY status = 'confirmed' DESC, score DESC")]
        day = _day(now)
        used = int(float(kv(con, f"poll_day:{day}") or 0))
        cap = int(c["poll_day_credits"] if credits is None else credits)
        n_poll, spent = poll(con, c, now, best, cap - used, fetch, log)
        kv(con, f"poll_day:{day}", used + spent)
        have = {t for (t,) in _q(con, "SELECT token FROM preshill_signals")}
        buys = recent_buys(con, p, set(ws), now - int(c["signal_window_s"]) - 1800, sol)
        maybe = {s["token"] for s in detect(buys, ws, {}, c, have)}   # public calls only of tokens that could fire
        called = gd._public_first(p, maybe, before=now) if maybe else {}
        shadow_rows, n_sig = [], 0
        for s in detect(buys, ws, called, c, have):
            if con.execute("INSERT OR IGNORE INTO preshill_signals (ts, buy_ts, token, wallets, clusters, n_wallets, "
                           "mcap_usd, detail) VALUES (?,?,?,?,?,?,?,?)",
                           (now, s["buy_ts"], s["token"], ",".join(s["wallets"]), ",".join(s["clusters"]),
                            len(s["wallets"]), _r(s["mcap_usd"], 0),
                            json.dumps({"statuses": {w: ws[w][0] for w in s["wallets"]},
                                        "lag_s": now - s["buy_ts"]}))).rowcount:
                n_sig += 1
                shadow_rows.append((s["token"], "nema signala",
                                    f"kupci prije shill mreže: {len(s['wallets'])} novčanika, čekaj val callova",
                                    {"wallets": s["wallets"], "clusters": s["clusters"], "mcap_usd": s["mcap_usd"],
                                     "under_30k": bool(s["mcap_usd"] and s["mcap_usd"] < 30000)}))
        con.commit()
        since = int(float(kv(con, "exit_since") or now - 3600))
        shadow_rows += exits(con, p, c, now, members, since)
        kv(con, "exit_since", now)
        measured, gt = measure_due(con, p, c, now, members, 0)
        n_sh = _shadow(p, shadow_rows, now)
        detail = {"tokens": n_tok, "built": n_built, "polled": n_poll, "signals": n_sig, "shadow": n_sh,
                  "measured": measured, "credits": spent}
        con.execute("INSERT INTO preshill_runs VALUES (?,?,?,?)", (now, "incr", spent, json.dumps(detail)))
        con.commit()
        if n_sig or n_sh or measured or spent:
            log(f"shill mreža (30 min, {m}): {n_sig} novih signala, {n_sh} zapisa u sjeni, izmjereno {measured}, "
                f"Helius {spent} kredita ({n_poll} novčanika)")
        return detail
    finally:
        con.close()


# ===================================================================================================================
# read side: MCP, the Autopilot card
# ===================================================================================================================
def _when(ts):
    """'11.11. 14:05' in Zagreb time ('' for None)."""
    if not ts:
        return ""
    import datetime
    try:
        from zoneinfo import ZoneInfo
        d = datetime.datetime.fromtimestamp(int(ts), ZoneInfo("Europe/Zagreb"))
    except Exception:  # noqa: BLE001 - no tz data: UTC
        d = datetime.datetime.fromtimestamp(int(ts), datetime.timezone.utc)
    return f"{d.day}.{d.month}. {d:%H:%M}"


def _num(x, dec=1, sign=False):
    if x is None:
        return "–"
    s = f"{x:+.{dec}f}" if sign else f"{x:.{dec}f}"
    return s.replace(".", ",").replace("-", "−")


def sentence(st):
    """One Croatian sentence: 'kupio 4 tokena prosječno 25 min prije mreže, prodao u val callova, +3,2 SOL'."""
    n = int(st.get("n_tokens") or 0)
    word = "token" if n % 10 == 1 and n % 100 != 11 else "tokena"
    out = f"kupio {n} {word} prosječno {_num(st.get('avg_min'), 0)} min prije mreže"
    into = st.get("sold_into_wave")
    if into is None:
        out += ", još nije prodao"
    elif into >= 0.5:
        out += ", prodao u val callova"
    else:
        out += ", prodaje izvan vala callova"
    if st.get("pnl_sol") is not None:
        out += f", {_num(st['pnl_sol'], 1, True)} SOL"
    return out


def timeline(ec, wallet, limit=10):
    """The wallet's pre-shill tokens, newest first: buy -> first shill call -> peak -> sell."""
    out = []
    for tok, bts, sin, mc, sts, sout, t0, fh, pk, pmc, we, m0 in _q(
            ec, "SELECT b.token, b.buy_ts, b.sol_in, b.mcap_usd, b.sold_ts, b.sol_out, t.t0, t.first_handle, t.peak_ts, "
                "t.peak_mcap, t.wave_end, t.mcap_t0 FROM preshill_buys b JOIN preshill_tokens t ON t.token = b.token "
                "WHERE b.wallet = ? AND b.bundle = 0 ORDER BY t.t0 DESC LIMIT ?", (wallet, int(limit))):
        out.append({"token": tok, "bought_ts": bts, "min_before_shill": round((t0 - bts) / 60, 1), "sol_in": sin,
                    "entry_mcap_usd": mc, "under_30k_at_entry": bool(mc and mc < 30000), "first_shill_call_ts": t0,
                    "first_shill_caller": fh, "mcap_at_first_call": m0, "peak_ts": pk, "peak_mcap_usd": pmc,
                    "sold_ts": sts, "sol_out": sout,
                    "sold_min_after_first_call": round((sts - t0) / 60, 1) if sts else None,
                    "sold_min_vs_peak": round((sts - pk) / 60, 1) if sts and pk else None,
                    "sold_into_wave": bool(sts and t0 <= sts <= (we or t0)),
                    "pnl_sol": _r(sout - sin) if sts and sin is not None and sout is not None else None})
    return out


def wallets_view(status=None, limit=None, offset=None, path=None, trade_db=None):
    """get_pre_shill_wallets: the shill networks (after the chain check), the chain check of every big caller group,
    and the pre-shill wallets with metrics and their tokens' timelines; empty with a note while the flag is off."""
    m = mode(trade_db)
    c = config()
    base = {"flag": FLAG, "flag_mode": m, "label": LABEL, "statuses_hr": STATUS_HR,
            "rule": {"network": f"ekipa callera ocjene {'/'.join(c['grades'])} s >= {c['min_size']} računa, nakon "
                                f"provjere lanca (gustoća veza >= {c['dense_min']}, inače {c['truss_k']}-truss i viši "
                                f"lift); dio koji ostane lanac nikad nije shill mreža",
                     "window": "6 h prije prvog poziva mreže (T0) do T0",
                     "candidate": f">= {c['min_tokens']} tokena, prosječno {c['min_before_min']:g}-"
                                  f"{c['max_before_min']:g} min prije T0, PnL > 0",
                     "confirmed": f"isto na starijih 2/3 od {c['days']} dana, novija 1/3: >= {c['min_confirm']} tokena "
                                  f"i PnL > 0",
                     "excluded": "dev i novčanici koje je dev financirao, bundleri (isti slot, 3+ novčanika), botovi "
                                 "(> 200 tradeova dnevno), relayeri, LP i CEX"}}
    if m == "off":
        return {**base, "networks": [], "chain_checks": [], "wallets": [], "total": 0,
                "note": "zastavica pre_shill je isključena"}
    want = ("candidate", "confirmed") if status in (None, "", "all") else (status,)
    if any(s not in STATUS_HR for s in want):
        return {"error": f"status must be one of {', '.join(STATUS_HR)} or all"}
    limit, offset = gd._page(limit, offset, 50)
    ec = _ro(path or gd.db_path())
    try:
        nets = [{"network_id": nid, "parent_group_id": par, "shill_network": True, "label": LABEL, "size": sz,
                 "grade": gr, "grade_text": gd.grade_text(gr, (json.loads(met or "{}") or {}).get("n_measured")),
                 "members": json.loads(mem or "[]"), "split": how, "metrics": json.loads(met or "{}")}
                for nid, par, mem, sz, gr, how, met in _q(ec, "SELECT id, parent, members, size, grade, how, metrics FROM "
                                                             "preshill_networks WHERE shill = 1 ORDER BY size DESC")]
        checks = [{"group_id": g, "size": sz, "grade": gr, "whole": json.loads(d or "{}"),
                   "parts": json.loads(pt or "[]"), "only_through_chain": per, "checked_ts": up}
                  for g, sz, gr, d, pt, per, up in _q(ec, "SELECT parent, size, grade, diag, parts, periphery, updated "
                                                          "FROM preshill_checks ORDER BY size DESC")]
        q = _in(want)
        total = (_q(ec, f"SELECT COUNT(*) FROM preshill_wallets WHERE status IN ({q})", want) or [(0,)])[0][0]
        rows = _q(ec, f"SELECT wallet, status, why, cluster, score, n_tokens, med_min, avg_min, entry_mcap_med, pnl_sol, "
                      f"hit_rate, med_hold_min, sold_into_wave, n_sel, n_conf, last_ts, stats, first_seen, status_ts, "
                      f"updated FROM preshill_wallets WHERE status IN ({q}) ORDER BY status = 'confirmed' DESC, "
                      f"score DESC, wallet LIMIT ? OFFSET ?", (*want, limit, offset))
        out = []
        for (w, st, why, cl, sc, n, mm, am, emc, pnl, hit, hold, into, ns, nc, last, stats, fs, sts, upd) in rows:
            s = json.loads(stats or "{}")
            d = {"wallet": w, "solscan": SOLSCAN + w, "status": st, "status_hr": STATUS_HR.get(st), "why": why,
                 "cluster": cl, "cluster_size": s.get("cluster_size"), "score": sc, "n_tokens_pre_shill": n,
                 "median_min_before_t0": mm, "avg_min_before_t0": am, "entry_mcap_med_usd": emc, "pnl_sol": pnl,
                 "hit_rate": hit, "median_hold_min": hold, "sold_into_wave_share": into, "select_tokens": ns,
                 "confirm_tokens": nc, "shared_funders": s.get("funders") or [], "last_activity_ts": last,
                 "first_seen_ts": fs, "status_since_ts": sts, "updated_ts": upd}
            d["sentence_hr"] = sentence({"n_tokens": n, "avg_min": am, "sold_into_wave": into, "pnl_sol": pnl})
            d["tokens"] = timeline(ec, w)
            out.append(d)
        runs = _q(ec, "SELECT kind, COUNT(*), SUM(credits) FROM preshill_runs WHERE ts >= ? GROUP BY kind",
                  (int(time.time()) - 86400,))
    finally:
        if ec is not None:
            ec.close()
    return {**base, "networks": nets, "chain_checks": checks, "wallets": out, "total": total,
            "next_offset": offset + limit if offset + limit < total else None,
            "cost_24h": {k: {"runs": n, "helius_credits": int(cr or 0)} for k, n, cr in runs}}


def signals_view(since_ts=None, limit=None, path=None, trade_db=None, now=None):
    """get_pre_shill_signals: the shadow signals since since_ts (default 7 days) with their measured result, the
    minutes until the shill network's first call and the result of selling into it."""
    m = mode(trade_db)
    now = int(now or time.time())
    if m == "off":
        return {"flag": FLAG, "flag_mode": m, "signals": [], "total": 0, "note": "zastavica pre_shill je isključena"}
    try:
        since = int(since_ts) if since_ts is not None else now - 7 * 86400
    except (TypeError, ValueError):
        return {"error": "since_ts must be unix seconds"}
    limit, _o = gd._page(limit, 0, 100)
    ec = _ro(path or gd.db_path())
    rows = _q(ec, "SELECT ts, buy_ts, token, wallets, clusters, n_wallets, mcap_usd, r1h, r4h, hit1h, hit4h, ev, shill_ts, "
                  "first_public_ts, exit_ts, exit_ret, measured_ts FROM preshill_signals WHERE ts >= ? ORDER BY ts DESC "
                  "LIMIT ?", (since, limit))
    ev = [r[0] for r in _q(ec, "SELECT ev FROM preshill_signals WHERE ev IS NOT NULL AND ts >= ?", (since,))]
    exr = [r[0] for r in _q(ec, "SELECT exit_ret FROM preshill_signals WHERE exit_ret IS NOT NULL AND ts >= ?", (since,))]
    if ec is not None:
        ec.close()
    sigs = [{"ts": ts, "bought_ts": bts, "token": t, "wallets": (w or "").split(","), "clusters": (cl or "").split(","),
             "n_wallets": nw, "mcap_usd": mc, "under_30k": bool(mc and mc < 30000), "r1h": r1, "r4h": r4,
             "hit20_before_stop30_1h": h1, "hit20_before_stop30_4h": h4, "ev_after_cost": e,
             "shill_started_min_after_signal": round((sh - ts) / 60, 1) if sh else None,
             "first_public_call_min_after_signal": round((fp - ts) / 60, 1) if fp else None,
             "exit_ts": ex, "sell_into_calls_ret_after_cost": er, "measured": bool(ms)}
            for ts, bts, t, w, cl, nw, mc, r1, r4, h1, h4, e, sh, fp, ex, er, ms in rows]
    return {"flag": FLAG, "flag_mode": m, "since_ts": since, "signals": sigs, "total": len(sigs),
            "summary": {"measured": len(ev), "ev_after_cost": _r(sum(ev) / len(ev)) if ev else None,
                        "sell_into_calls_n": len(exr), "sell_into_calls_ret": _r(sum(exr) / len(exr)) if exr else None},
            "note": "sjena: ništa se ne kupuje; ulaz = trenutak otkrića (do 30 min nakon kupnje), izlaz = prvi poziv mreže"}


def mcp_tool(name, a):
    """The two read-only MCP tools (ui/mcpapi._tool)."""
    a = a if isinstance(a, dict) else {}
    if name == "get_pre_shill_signals":
        return signals_view(a.get("since_ts"), a.get("limit"))
    return wallets_view(a.get("status"), a.get("limit"), a.get("offset"))


def kandidati_view(now=None, path=None, trade_db=None, window_s=3600, held_s=86400):
    """For ui/kandidati (empty while off): {"members": {handle: network id}, "signals": [(ts, token, wallets,
    mcap_usd)] of the last window_s, "held": {token: signal ts} of the last held_s (a pre_shill signal is open)}."""
    if mode(trade_db) == "off":
        return {"members": {}, "signals": [], "held": {}}
    now = int(now or time.time())
    ec = _ro(path or gd.db_path())
    if ec is None:
        return {"members": {}, "signals": [], "held": {}}
    try:
        members = {h: nid for nid, ms in networks(ec).items() for h in ms}
        rows = _q(ec, "SELECT ts, token, wallets, mcap_usd FROM preshill_signals WHERE ts >= ? ORDER BY ts",
                  (now - held_s,))
    finally:
        ec.close()
    return {"members": members, "signals": [(ts, t, (w or "").split(","), mc) for ts, t, w, mc in rows
                                            if ts >= now - window_s],
            "held": {t: ts for ts, t, _w, _mc in rows}}


def card_html(sec, item, esc, limit=12, path=None, trade_db=None):
    """"Kupci prije shill mreže" for the Autopilot page, under "Još", closed (ui/pravitrade passes its _sec / _item /
    esc). '' while the flag is off. A tap on a wallet opens its tokens as a timeline: buy -> first shill call -> peak
    -> sell. No chip, no h2."""
    if mode(trade_db) == "off":
        return ""
    d = wallets_view(limit=limit, path=path, trade_db=trade_db)
    if "error" in d:
        return ""
    ws, nets = d["wallets"], d["networks"]
    items = []
    for w in ws:
        lines = []
        for t in w["tokens"]:
            pk = (f' → vrh {esc(_when(t["peak_ts"]))}' if t["peak_ts"] else " → vrh –") + (
                f' (MC {_usd(t["peak_mcap_usd"])})' if t["peak_mcap_usd"] else "")
            sold = (f' → prodao {esc(_when(t["sold_ts"]))}' + (" u val callova" if t["sold_into_wave"] else "")
                    + (f', {_num(t["pnl_sol"], 2, True)} SOL' if t["pnl_sol"] is not None else "")) if t["sold_ts"] \
                else " → još drži"
            lines.append(f'<li><code>{esc(t["token"][:6])}…</code> kupio {esc(_when(t["bought_ts"]))} (MC '
                         f'{_usd(t["entry_mcap_usd"])}, {_num(t["sol_in"], 2)} SOL) → prvi shill call '
                         f'{esc(_when(t["first_shill_call_ts"]))} ({esc(t["first_shill_caller"] or "")}, '
                         f'{_num(t["min_before_shill"], 0)} min kasnije){pk}{sold}</li>')
        facts = (f'<p><a href="{SOLSCAN}{esc(w["wallet"])}" target=_blank rel=noopener>{esc(w["wallet"])}</a></p>'
                 f'<p class=mut>{esc(w["status_hr"] or "")} · klaster {esc((w["cluster"] or w["wallet"])[:6])}… '
                 f'({w["cluster_size"] or 1}) · {w["n_tokens_pre_shill"]} tokena · medijan '
                 f'{_num(w["median_min_before_t0"], 0)} min prije mreže · ulaz MC {_usd(w["entry_mcap_med_usd"])} · '
                 f'pogodak {_pct(w["hit_rate"])} · zadnja aktivnost {esc(_when(w["last_activity_ts"]))}</p>')
        items.append(item(f'{w["wallet"][:4]}…{w["wallet"][-4:]}', w["sentence_hr"],
                          facts + (f'<ol class=ap-tl>{"".join(lines)}</ol>' if lines else ""),
                          value=_num(w["pnl_sol"], 1, True) if w["pnl_sol"] is not None else None, sub="SOL",
                          iid=f'ps-{w["wallet"][:10]}'))
    if nets:
        head = (f'<p class=mut>{esc(LABEL)}: ' + ", ".join(f'{n["size"]} računa ({esc(n["grade_text"])})' for n in nets[:3])
                + ". Poziv mreže je znak za izlaz (sjena, ništa se ne kupuje).</p>")
    else:
        head = '<p class=mut>Još nema shill mreže nakon provjere lanca (ekipa ocjene loša, 20+ računa koji stvarno ' \
               'zovu zajedno).</p>'
    body = head + ("".join(items) if items else '<p class=mut>Još nema novčanika koji kupuju prije mreže '
                                               '(3+ tokena, 5-120 min prije, u plusu).</p>')
    meta = f'{d["total"]} novčanika' + (f' · {len(nets)} mreža' if nets else "")
    return sec("Kupci prije shill mreže", meta, body, sid="preshill")


def _usd(x):
    if not x:
        return "–"
    x = float(x)
    return f"{x / 1e6:.1f}M $".replace(".", ",") if x >= 1e6 else f"{x / 1e3:.0f}k $" if x >= 1e4 else \
        f"{x / 1e3:.1f}k $".replace(".", ",") if x >= 1e3 else f"{x:.0f} $"


def _pct(x):
    return "–" if x is None else f"{x * 100:.0f} %"


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(description="Kupci prije shill mreže (zastavica pre_shill)")
    ap.add_argument("cmd", choices=("night", "incr", "status"))
    ap.add_argument("--credits", type=int, default=None,
                    help="Helius krediti: noć = strop prolaza, incr = dnevni strop čitanja novčanika")
    ap.add_argument("--force", action="store_true", help="noćni prolaz i ako je bio prije manje od 20 h")
    a = ap.parse_args(argv)
    if a.cmd == "night":
        night(credits=a.credits, force=a.force)
    elif a.cmd == "incr":
        incremental(credits=a.credits)
    else:
        ec = _ro(gd.db_path())
        for g, sz, gr, d, pt, per in _q(ec, "SELECT parent, size, grade, diag, parts, periphery FROM preshill_checks"):
            print(f"grupa {g}: {sz} računa ({gr}), gustoća {json.loads(d).get('density')}, samo preko lanca {per}, "
                  f"dijelovi {[(x['size'], x['grade'], x['shill']) for x in json.loads(pt)][:8]}")
        for ts, kind, cr, d in _q(ec, "SELECT ts, kind, credits, detail FROM preshill_runs ORDER BY ts DESC LIMIT 10"):
            print(time.strftime("%d.%m. %H:%M", time.gmtime(ts)), kind, f"Helius {cr}", d)
        if ec is not None:
            ec.close()
        print(f"zastavica {FLAG}: {mode()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
