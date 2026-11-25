"""Kopija dokazanih novčanika: what WE would have earned copying them (16.11.2026, vlasnik: "Objasni mi kako ovdje
postoji profitabilni wallet, a mi nemamo profitabilnu strategiju").

The ranking (wallets/rang.py) and the proven-twice list (wallets/dokazani.py) measure a wallet's OWN trades at its OWN
prices. This module replays the copier: the same wallets, picked on the older part of the data only, and on the newer
part every one of their buys taken `delay` seconds later at the price the databases hold for that moment, sold `delay`
after their sale (or at our stop / time limit), minus the real round-trip cost of a 0.1 SOL stake. Local databases
only: no network call, no paid call, no write outside wallets.db copy_rank_kv.

Data
  wallets.db   wallets (scored_at: the scored universe, labels) and wallet_trades (every stored swap of every scored
               wallet: ts, mint, tokens, sol, kind). The available days = the UTC days with a stored trade inside the
               last MAX_DAYS; the first TRAIN_FRAC (60 %) are the selection part, the rest the measured part.
  prices       per token, two kinds that are never mixed inside one trade (a return is a ratio inside one series):
               "sol"  prints of real swaps, SOL per token, to the second: wallets.db wallet_trades of EVERY scored
                      wallet (|sol| / |tokens|), hype.db live_trades (PumpPortal), insajderi.db i2_trades, early.db
                      precall_trades / group_buys, and hype.db token_pulse price_native (pool snapshots)
               "usd"  minute.db call_candles (1-min candles: the open at the minute's start, the close at its end),
                      range.db / momentum.db / kol.db snaps, hype.db token_pulse / hype_snapshots, midcap.db snap and
                      15-min candles
               A price is the FIRST point at or after the moment, at most ENTRY_GAP_S (entry) / EXIT_GAP_S (exit) later
               (several prints in one second: their mean). No point = the buy is counted as "bez cijene" and dropped,
               never guessed. The SOL prints are tried first, the USD series only when they cannot price the trade.
  liquidity    the stored pool snapshot nearest the entry within 30 min; else, for a pump.fun mint, the
               constant-product estimate of wallets/rang.pool_liq_usd from our entry price; else unknown
  cost         trade/cost.round_trip(0.1 SOL in USD, that liquidity) = 2 x fee a side + 2 x price impact, never under
               RT_FLOOR (3 %, the measured round trip)

Selection at the split (nothing after it is read): for every scored wallet its trades BEFORE the split only
  app         "dokazan dvaput" (wallets/dokazani.RULE applied with now = the split) and "kopirljiv" (dokazani.copyable
              on stats recomputed from those trades, and wallets/rang's median entry liquidity >= 15k)
  top         the first TOP_N by the ranking's score among its proven (10+ closed), copyable wallets in profit
  jednom      the first half of "dokazan dvaput" only (no second confirmation) and "kopirljiv"
  likvidnost  the wallets of `app`, but only their buys in a pool of known liquidity >= LIQ_STRICT (15k, the real
              account's hard floor)
A rule copies at most MAX_WALLETS (50) wallets, the best score at the split first (what the webhook can follow).

The copier (pre-declared; GRID = 4 rules x 3 delays x 3 exits = 36 combinations, all reported)
  signal      the first buy of a position (the wallet held none of the token); its later buys of the same position
              are not copied; buys under MIN_SOL are dust
  entry       the price at buy + delay (30 / 60 / 180 s)
  exit        on: the price at his first sale + delay | on_stop: that, or our stop at -20 % (filled at the print that
              crossed it) | on_stop_24h: that, or 24 h after our entry
  account     one position a token at a time, at most MAX_OPEN open; a buy that meets either is "not copied"; so is
              a buy in a pool known to be under the liquidity floor or of a token known to be under 30k $ market cap
              (the owner's rule for every automatic buy)
PRIMARY (declared before any result) = app, 60 s, on_stop: the demo's rule.

Next to the grid: "strict" = PRIMARY over the wallets the tool had scored BEFORE the split only (a wallet found later
may have been found because of a buy inside the measured part); "own" = the picked wallets' own result on the measured
part; "gap" = their return against ours on the same trades, split into one-entry-one-exit, entry delay, exit, cost.

Result: wallets.db copy_rank_kv "kopija" (JSON; latest()); summary() = the morning report's and /strategije's view;
one log line "novčanici kopija: ...". run() is bounded by BUDGET_S and MAX_BUYS (a cut pass is a pseudo-random sample
of the tokens and says "djelomično") and never raises.
"""
import bisect
import json
import math
import os
import random
import sqlite3
import statistics
import time
import zlib

PREFIX = "novčanici kopija: "
KV = "kopija"
D, H = 86400, 3600
SIZE_SOL = 0.1
RT_FLOOR = float(os.environ.get("KOPIJA_RT_FLOOR", "0.03"))
MAX_DAYS = 60
MIN_DAYS = 6                 # fewer days with trades than this: no split, no result
TRAIN_FRAC = 0.6
MIN_N = 30
B = 1000
BUDGET_S = int(os.environ.get("KOPIJA_BUDGET_S", "300"))
DELAYS = (30, 60, 180)
EXITS = ("on", "on_stop", "on_stop_24h")
RULES = ("app", "top", "jednom", "likvidnost")
PRIMARY = ("app", 60, "on_stop")
TOP_N = 20
MAX_WALLETS = 50             # a rule copies at most this many, the best score at the split first: the Helius webhook
#                              gives the proven wallets half of its 100 addresses (kol/chainwatch.wanted)
MAX_BUYS = int(os.environ.get("KOPIJA_MAX_BUYS", "12000"))   # positions simulated in one pass (memory); more = partial
STOP = 0.20
HOLD_S = 24 * H
MAX_OPEN = 10
ENTRY_GAP_S = 120
EXIT_GAP_S = 600
LIQ_FLOOR = 5_000            # the demo accounts' floor: a pool known to be thinner is not copied
LIQ_STRICT = 15_000          # trade/cost.LIQ_HARD_MIN: the real account's hard floor
LIQ_TOL_S = 30 * 60
MIN_MC = 30_000              # the owner's rule: nothing under 30k $ market cap is bought automatically
MIN_SOL = 0.02               # wallets/rang.MIN_SOL: a smaller buy is dust, not a signal
MIN_PRINT_SOL = 0.01         # a swap smaller than this is no price (rounding)
CLOSED_FRAC = 0.98           # wallets/pnl.CLOSED_FRAC
# 25.11. (vlasnik, jutarnji izvještaj: „Prvih 20 po ocjeni: prosjek +48693144406 %, zbroj +88864988541 SOL"): a copied
# trade whose PRICE cannot be real is dropped and counted ("sumnjiva_cijena"), never clipped and never kept. The rules
# judge the quality of the price, not the size of the result (a real +800 % passes):
#   - the entry or exit print is <= 0 / not a number
#   - the entry or exit print sits more than SPIKE_X times away from the median of the SPIKE_K prints before it AND of
#     the SPIKE_K after it (an isolated print; a real jump agrees with one side); at the edge of a series, with one side
#     only, SPIKE_X ** 2
#   - the market cap at entry or exit (price x supply) above MC_MAX: no memecoin was ever worth that, so the price is in
#     another unit or of another pool (e.g. GeckoTerminal candles of a pool whose base token is SOL: SOL's price)
#   - our entry more than SLIP_X times away from his own fill `delay` seconds earlier (two prints of one token that
#     cannot both be right)
# and the exit is capped by the pool: no more can come out than the pool's whole SOL side (half its USD liquidity), so
# a trade's gross return is at most liquidity / 2 / stake - 1 (row "ograniceno", counted).
SPIKE_X = 10.0
SPIKE_K = 3
MC_MAX = 1e11
SLIP_X = 50.0
DIAG_N = 5                   # the log's diagnostic line: the most extreme trades of each table row
EXIT_HR = {"on": "njegov izlaz", "on_stop": "njegov izlaz ili stop −20 %",
           "on_stop_24h": "njegov izlaz, stop −20 % ili 24 h"}
RULE_HR = {"app": "Dokazan dvaput i kopirljiv (kao u aplikaciji)",
           "top": f"Prvih {TOP_N} po ocjeni",
           "jednom": "Dokazan jednom i kopirljiv",
           "likvidnost": "Kao u aplikaciji, samo poolovi od 15k $ naviše"}
SRC_HR = ("trgovine (na sekundu)", "svijeće od 1 min", "snimke poola (1–20 min)", "svijeće od 15 min")
S_TRADE, S_M1, S_SNAP, S_M15 = 0, 1, 2, 3
MC_B = ((1e6, "ispod 1M"), (5e6, "1–5M"), (float("inf"), "5M i više"))
LIQ_B = ((15e3, "ispod 15k"), (50e3, "15–50k"), (float("inf"), "50k i više"))
HOLD_B = ((30, "do 30 min"), (240, "30 min – 4 h"), (float("inf"), "dulje od 4 h"))
CONFIG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")
# wallets/config.json "kopija": the paid refresh of the proven wallets' trades is OFF until the owner says so
CFG_DEFAULT = {"osvjezi": False, "kredita_dan": 2000, "najvise_novcanika": 150, "svakih_h": 6}
BIASES = (
    "preživjeli: u bazi su novčanici koje je alat pronašao i ocijenio jer su već bili dobri; oni koji su prestali "
    "trgovati ili su izbačeni nisu ovdje, pa je i njihov vlastiti rezultat ljepši od prosjeka",
    "pogled unaprijed: odabir vidi samo tradeove prije reza, ali oznake novčanika (bot, rugger …) su današnje, a udio "
    "starih otvorenih gubitnika na dan reza nije se mogao provjeriti (nema tadašnjih cijena), pa je „kopirljiv” ovdje "
    "malo blaži nego u aplikaciji",
    "povijest novčanika prije njegove prve ocjene je uzorak (zadnjih do 300 transakcija, najviše 30 dana), pa odabir na "
    "starijem dijelu vidi manje tradeova nego što ih je stvarno bilo",
    "jedan tržišni režim: mjereni dio je nekoliko tjedana jednog tržišta; drugo tržište može dati drugi rezultat",
    "zrnatost cijene: cijena je prvi zabilježeni ispis nakon trenutka (do 2 min za ulaz, do 10 min za izlaz), a ne "
    "ponuda u toj sekundi; rijetko trgovani tokeni nemaju ispis i ispadaju kao „bez cijene”, pa je izmjereni dio "
    "pomaknut prema življim tokenima",
    "stop se vidi tek na zabilježenom ispisu: između dva ispisa cijena je mogla pasti i vratiti se, a jedan ispis na "
    "krivoj cijeni može lažno okinuti stop; u svijećama se dno unutar minute ne vidi",
    "pozicije koje novčanik nije prodao do kraja podataka vrednuju se zadnjom poznatom cijenom (token je možda mrtav)",
    "nije simulirano: neuspjele transakcije, dnevni stropovi, rug i druge zaštite pri ulazu, njegova dokupljivanja, je "
    "li token u trenutku kupnje već bio bondan (kupnje na pump.fun krivulji pravi kopirač ne bi uzeo)",
)


# ---------- small helpers ----------------------------------------------------------------------------------------------

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


def _bucket(x, edges, unknown="nepoznato"):
    if x is None:
        return unknown
    for hi, name in edges:
        if x < hi:
            return name
    return edges[-1][1]


def config(path=None):
    """CFG_DEFAULT with wallets/config.json "kopija" on top (known keys only)."""
    c = dict(CFG_DEFAULT)
    try:
        with open(path or CONFIG, encoding="utf-8") as f:
            own = json.load(f).get("kopija") or {}
        for k, v in own.items():
            if k in CFG_DEFAULT and isinstance(v, type(CFG_DEFAULT[k])):
                c[k] = v
    except (OSError, ValueError, AttributeError, TypeError):
        pass
    return c


def paths(over=None):
    """The database files read (wallets/rang._paths + the price stores); `over` replaces any of them (tests)."""
    from wallets import rang, store as wstore
    p = dict(over or {})
    base = rang._paths(p)

    def get(k, fn):
        if k not in p:
            try:
                p[k] = fn()
            except Exception:  # noqa: BLE001 - a module that does not import: that source is simply missing
                p[k] = None
    for k, v in base.items():
        p.setdefault(k, v)
    get("wallets", lambda: wstore.DB)
    get("early", lambda: os.environ.get("EARLY_DB") or os.path.join(rang.ROOT, "early.db"))
    get("insajderi", lambda: __import__("insajderi.store", fromlist=["x"]).db_path())
    get("range", lambda: __import__("rangedca.data", fromlist=["x"]).db_path())
    get("momentum", lambda: __import__("momentum.data", fromlist=["x"]).db_path())
    get("midcap", lambda: __import__("veliki.midcap", fromlist=["x"]).db_path())
    return p


# ---------- the split ---------------------------------------------------------------------------------------------------

def split_days(days, frac=TRAIN_FRAC):
    """(the first `frac` of the sorted UTC day numbers, the rest, the first second of the rest); no split (None) with
    fewer than MIN_DAYS days."""
    days = sorted(set(days))
    if len(days) < MIN_DAYS:
        return days, [], None
    k = max(1, min(len(days) - 1, int(len(days) * frac)))
    return days[:k], days[k:], days[k] * D


def trade_days(con, now, max_days=MAX_DAYS):
    """([UTC day numbers with a stored trade], the newest trade's time) inside the last max_days. One scan."""
    rows = _q(con, "SELECT ts / 86400, MAX(ts) FROM wallet_trades WHERE ts >= ? AND ts <= ? AND kind IN ('buy', 'sell') "
                   "GROUP BY 1", (int(now) - max_days * D, int(now)))
    return sorted(int(r[0]) for r in rows), max((int(r[1]) for r in rows), default=None)


# ---------- the selection (trades before the split only) ---------------------------------------------------------------

TRADE_COLS = ("sig", "ts", "mint", "tokens", "sol", "kind")


def trades_of(con, wallet, lo, hi):
    """The wallet's stored trades with lo <= ts < hi, oldest first."""
    return [dict(zip(TRADE_COLS, r)) for r in _q(
        con, "SELECT sig, ts, mint, tokens, sol, kind FROM wallet_trades WHERE wallet=? AND ts>=? AND ts<? ORDER BY ts",
        (wallet, int(lo), int(hi)))]


def dvaput_at(trades, split, rule=None):
    """wallets/dokazani.evaluate's verdict for one wallet as it stood AT the split: {"jednom", "dvaput"} or None when
    it had no closed position before the cut. Trades at or after the split are dropped here, whatever the caller
    passed (the selection never sees the measured part)."""
    from wallets import dokazani
    r = rule or dokazani.RULE
    cut = split - r["cut_days"] * D
    before = [t for t in trades if t["ts"] < cut]
    after = [t for t in trades if cut <= t["ts"] < split]
    if not before:
        return None
    rb, nb, wb = dokazani._realized(before)
    if nb == 0:
        return None
    once = nb >= r["min_closed"] and rb > 0 and wb / nb >= r["min_win"]
    ra, na, _wa = dokazani._realized(after) if after else (0.0, 0, 0)
    return {"jednom": bool(once), "dvaput": bool(once and na >= r["min_after"] and ra > 0)}


def select(con, split, p, deadline=None, top_n=TOP_N, max_wallets=MAX_WALLETS):
    """{"rules": {rule: [wallets]}, "info": {wallet: {...}}, "scored", "partial"}: who would have been picked at the
    split, by each pre-declared rule, from the trades before it only."""
    from wallets import dokazani, pnl, rang
    info, cands, n, partial = {}, {}, 0, False
    rows = _q(con, "SELECT wallet, labels FROM wallets WHERE scored_at IS NOT NULL")
    first = dict(_q(con, "SELECT wallet, MIN(ts) FROM wallet_pnl GROUP BY wallet"))   # when the tool first scored it
    for w, lab in rows:
        if deadline and time.time() > deadline:
            partial = True
            break
        try:
            labels = set(json.loads(lab or "[]"))
        except ValueError:
            labels = set()
        if labels & rang.BAD or labels & dokazani.BAD:
            continue
        tr = trades_of(con, w, split - 2 * rang.WINDOW_D * D, split)
        if not tr:
            continue
        n += 1
        d = dvaput_at(tr, split)
        items = rang.wallet_items(tr, split)
        if not (d and d["jednom"]) and len(items) < rang.MIN_N:
            continue
        s = pnl.score(pnl.positions(tr), tr, split, labels)
        info[w] = {"jednom": bool(d and d["jednom"]), "dvaput": bool(d and d["dvaput"]),
                   "dkop": dokazani.copyable(s, labels), "hold_min": s.get("median_hold_min"),
                   "rano": bool(first.get(w) and first[w] < split)}
        cands[w] = items
    sols = rang.sol_usd_days(p.get("market"))
    snap = rang.snapshot_liq({(i["mint"], int(i["t0"])) for items in cands.values() for i in items}, p)
    for w, items in cands.items():
        for i in items:
            liq = snap.get((i["mint"], int(i["t0"])))
            if not liq and rang.is_pump(i["mint"]) and i["px0"]:
                liq = rang.pool_liq_usd(i["px0"] * rang.PUMP_SUPPLY, rang.sol_at(sols, i["t0"]))
            i["liq"], i["avail"] = liq, None
        r = rang.evaluate(items, split, float(rang.LAG_DEFAULT_S["wallet"]), "zadano", rang.sol_at(sols, split))
        info[w].update(score=r["score"], proven=bool(r["proven"]), rkop=bool(r["copyable"]), n=r["n"], liq=r.get("liq"),
                       roi=r.get("roi"))
    best = lambda ws, k: sorted(sorted(ws, key=lambda w: (-info[w]["score"], w))[:k])   # noqa: E731
    app = [w for w, x in info.items() if x["dvaput"] and x["dkop"] and x.get("rkop")]
    once = [w for w, x in info.items() if x["jednom"] and x["dkop"] and x.get("rkop")]
    top = [w for w, x in info.items() if x.get("proven") and x.get("rkop") and (x.get("roi") or 0) > 0]
    rules = {"app": best(app, max_wallets), "top": best(top, top_n), "jednom": best(once, max_wallets)}
    rules["likvidnost"] = list(rules["app"])
    return {"rules": rules, "passed": {"app": len(app), "top": len(top), "jednom": len(once), "likvidnost": len(app)},
            "info": info, "scored": n, "partial": partial}


# ---------- his positions -----------------------------------------------------------------------------------------------

def episodes(trades):
    """A wallet's trades (oldest first) -> its positions [{mint, t0, px0, sol0, sell_ts, sell_px, t1, ret, adds}]:
    a position opens with a buy while the wallet holds none of the token and closes once CLOSED_FRAC of what it bought
    is sold. px0 = his fill of the first buy (SOL per token); sell_ts / sell_px = his FIRST sale (the copier's exit
    signal); ret = his realized return on the whole position (moving average cost, like wallets/pnl), None while it is
    not closed, was moved to another wallet, or a sale has no SOL amount."""
    out, cur = [], {}
    for r in trades:
        m, k = r["mint"], r["kind"]
        tok, sol = r.get("tokens") or 0.0, r.get("sol") or 0.0
        e = cur.get(m)
        if k == "buy" and tok > 0 and sol < 0:
            if e is None:
                e = cur[m] = {"mint": m, "t0": int(r["ts"]), "px0": -sol / tok, "sol0": -sol, "bought": 0.0, "held": 0.0,
                              "held_cost": 0.0, "proceeds": 0.0, "mcost": 0.0, "sell_ts": None, "sell_px": None,
                              "t1": None, "adds": -1, "odd": False}
                out.append(e)
            e["bought"] += tok
            e["held"] += tok
            e["held_cost"] += -sol
            e["adds"] += 1
        elif e is not None and k in ("sell", "transfer_out") and tok < 0:
            q = -tok
            if k == "sell" and e["sell_ts"] is None:
                e["sell_ts"], e["sell_px"] = int(r["ts"]), (sol / q if sol > 0 else None)
            mq = min(q, e["held"])
            if mq > 0:
                c = e["held_cost"] * mq / e["held"]
                e["held"] -= mq
                e["held_cost"] -= c
                if k == "sell" and sol > 0:
                    e["proceeds"] += sol * mq / q
                    e["mcost"] += c
                else:
                    e["odd"] = True   # moved out, or a sale without a SOL amount: his result is not known
            if e["held"] <= (1 - CLOSED_FRAC) * e["bought"]:
                e["t1"] = int(r["ts"])
                del cur[m]
    for e in out:
        e["ret"] = (e["proceeds"] / e["mcost"] - 1) if e["t1"] and not e["odd"] and e["mcost"] > 0 else None
    return out


# ---------- prices ------------------------------------------------------------------------------------------------------

# (database, SQL -> (ts, price in SOL per token) of one token inside [lo, hi], source class)
SOL_SQL = (
    ("hype", "SELECT ts, price_sol FROM live_trades WHERE mint=? AND ts BETWEEN ? AND ? AND price_sol > 0 AND sol >= "
             f"{MIN_PRINT_SOL}", S_TRADE),
    ("insajderi", "SELECT ts, sol / tokens FROM i2_trades WHERE mint=? AND ts BETWEEN ? AND ? AND tokens > 0 AND sol >= "
                  f"{MIN_PRINT_SOL}", S_TRADE),
    ("early", "SELECT ts, sol / tokens FROM precall_trades WHERE mint=? AND ts BETWEEN ? AND ? AND tokens > 0 AND sol >= "
              f"{MIN_PRINT_SOL}", S_TRADE),
    ("early", "SELECT ts, sol / tokens FROM group_buys WHERE mint=? AND ts BETWEEN ? AND ? AND tokens > 0 AND sol >= "
              f"{MIN_PRINT_SOL}", S_TRADE),
    ("hype", "SELECT ts, price_native FROM token_pulse WHERE token=? AND ts BETWEEN ? AND ? AND price_native > 0", S_SNAP),
)
# (database, SQL -> (ts, price in USD, pool liquidity USD, market cap USD), source class)
USD_SQL = (
    ("range", "SELECT ts, price, liq, mcap FROM snaps WHERE token=? AND ts BETWEEN ? AND ? AND price > 0", S_SNAP),
    ("momentum", "SELECT ts, price, liq, mcap FROM snaps WHERE token=? AND ts BETWEEN ? AND ? AND price > 0", S_SNAP),
    ("kol", "SELECT ts, price, liq, mcap FROM snaps WHERE token=? AND ts BETWEEN ? AND ? AND price > 0", S_SNAP),
    ("hype", "SELECT ts, price, liquidity, mcap FROM token_pulse WHERE token=? AND ts BETWEEN ? AND ? AND price > 0",
     S_SNAP),
    ("hype", "SELECT ts, price, liquidity, mcap FROM hype_snapshots WHERE token=? AND ts BETWEEN ? AND ? AND price > 0",
     S_SNAP),
)


class Series:
    """One token's points of one kind, oldest first: parallel lists ts / px / src. Several points in one second are
    one point at their mean price (neither the cheapest entry nor the dearest exit of that second is picked)."""
    __slots__ = ("ts", "px", "src")

    def __init__(self, pts=()):
        by = {}
        for t, px, src in pts:
            if px and px > 0:
                a = by.setdefault(int(t), [0.0, 0, src])
                a[0] += float(px)
                a[1] += 1
                a[2] = min(a[2], src)
        self.ts = sorted(by)
        self.px = [by[t][0] / by[t][1] for t in self.ts]
        self.src = [by[t][2] for t in self.ts]

    def first_from(self, t, gap):
        """Index of the first point at or after t, at most gap seconds later; None when there is none."""
        i = bisect.bisect_left(self.ts, int(t))
        return i if i < len(self.ts) and self.ts[i] - t <= gap else None


class Prices:
    """Every stored price of the tokens asked for, one token at a time (the 512 MB server). prints: the SOL prints of
    wallets.db wallet_trades, read once for all the tokens (load_prints); the other stores are read per token."""

    def __init__(self, p, lo, hi):
        self.p, self.lo, self.hi = p, int(lo), int(hi)
        self.prints = {}
        self._con = {}

    def con(self, key):
        if key not in self._con:
            self._con[key] = _ro(self.p.get(key))
        return self._con[key]

    def close(self):
        for c in self._con.values():
            if c is not None:
                c.close()
        self._con = {}

    def load_prints(self, con, mints, deadline=None):
        """wallets.db wallet_trades -> {mint: [(ts, SOL per token)]} for `mints`, every scored wallet's swaps (one
        streaming scan, filtered here). False when the time budget cut it."""
        want = set(mints)
        try:
            cur = con.execute("SELECT mint, ts, tokens, sol FROM wallet_trades WHERE ts >= ? AND ts <= ? AND kind IN "
                              "('buy', 'sell')", (self.lo, self.hi))
            for k, (m, ts, tok, sol) in enumerate(cur):
                if k % 50000 == 0 and deadline and time.time() > deadline:
                    return False
                if m in want and tok and sol and abs(sol) >= MIN_PRINT_SOL:
                    self.prints.setdefault(m, []).append((int(ts), abs(sol) / abs(tok), S_TRADE))
        except sqlite3.Error:
            pass
        return True

    def token(self, mint):
        """{"sol": Series, "usd": Series, "liq": [(ts, USD)], "supply": tokens or None} of one token."""
        sol = list(self.prints.pop(mint, ()))
        for key, sql, cls in SOL_SQL:
            sol += [(ts, px, cls) for ts, px in _q(self.con(key), sql, (mint, self.lo, self.hi))]
        usd, liq, supply = [], [], None
        for key, sql, cls in USD_SQL:
            for ts, px, lq, mc in _q(self.con(key), sql, (mint, self.lo, self.hi)):
                usd.append((ts, px, cls))
                if lq and lq > 0:
                    liq.append((int(ts), float(lq)))
                if supply is None and mc and mc > 0:
                    supply = mc / px
        for row in _q(self.con("minute"), "SELECT data FROM call_candles WHERE token=?", (mint,)):
            try:
                from kol import minute
                for c in minute._unpack(row[0]):
                    if self.lo <= c[0] <= self.hi:
                        usd += [(c[0], c[1], S_M1), (c[0] + 59, c[4], S_M1)]
            except Exception:  # noqa: BLE001 - an unreadable blob is a missing source
                pass
        mc = self.con("midcap")
        tid = _q(mc, "SELECT id, mcap FROM tokens WHERE mint=?", (mint,))
        if tid:
            for ts, px, lq, cap in _q(mc, "SELECT ts, px, liq, mc FROM snap WHERE id=? AND ts BETWEEN ? AND ? AND px > 0",
                                      (tid[0][0], self.lo, self.hi)):
                usd.append((ts, px, S_SNAP))
                if lq and lq > 0:
                    liq.append((int(ts), float(lq)))
                if supply is None and cap and cap > 0:
                    supply = cap / px
            for ts, o, c in _q(mc, "SELECT ts, o, c FROM c15 WHERE token=? AND ts BETWEEN ? AND ?",
                               (mint, self.lo, self.hi)):
                usd += [(ts, o, S_M15), (ts + 899, c, S_M15)]
        if supply is None:
            r = _q(self.con("kol"), "SELECT supply FROM tokens WHERE token=? AND supply > 0", (mint,))
            supply = float(r[0][0]) if r else None
        liq.sort()
        return {"sol": Series(sol), "usd": Series(usd), "liq": liq, "supply": supply}


def liq_near(points, ts, tol=LIQ_TOL_S):
    """The stored pool liquidity nearest ts within tol seconds, else None. points: sorted [(ts, USD)]."""
    if not points:
        return None
    i = bisect.bisect_left(points, (int(ts), -1.0))
    best = min((points[j] for j in (i - 1, i) if 0 <= j < len(points)), key=lambda x: abs(x[0] - ts), default=None)
    return best[1] if best and abs(best[0] - ts) <= tol else None


# ---------- one copied trade ----------------------------------------------------------------------------------------------

def simulate(ep, delay, rule, ser, hi):
    """The copier's trade of one position `ep` on one price series, before cost: None when the series has no price for
    our entry; else {"ts", "e_px", "src", "out_ts", "x_px" (None = the exit has no price), "why", "open", "stale"}.
    why: "prodao" (his first sale + delay), "stop" (the first print at or under entry x (1 - STOP)), "vrijeme" (24 h),
    "otvoreno" (not sold by the end of the data `hi`: marked at the last print)."""
    et = ep["t0"] + delay
    i = ser.first_from(et, ENTRY_GAP_S)
    if i is None:
        return None
    ts, px = ser.ts, ser.px
    e_px = px[i]
    out = {"ts": et, "e_px": e_px, "src": ser.src[i], "lag": ts[i] - ep["t0"], "open": False, "stale": False, "x_px": None,
           "_i": i, "_j": None}
    sell_t = ep["sell_ts"] + delay if ep.get("sell_ts") else None
    limit = et + HOLD_S if rule == "on_stop_24h" else None
    plan = min((x for x in (sell_t, limit) if x is not None), default=None)
    horizon = min(plan, hi) if plan is not None else hi
    if rule != "on":
        stop_px = e_px * (1 - STOP)
        for j in range(i + 1, len(ts)):
            if ts[j] > horizon:
                break
            if px[j] <= stop_px:
                out.update(out_ts=ts[j], x_px=px[j], why="stop", _j=j)
                return out
    if plan is None or plan > hi:
        j = bisect.bisect_right(ts, hi) - 1
        out.update(out_ts=hi, why="otvoreno", open=True, x_px=px[j] if j > i else None, _j=j if j > i else None)
        return out
    why = "prodao" if plan == sell_t else "vrijeme"
    out.update(out_ts=plan, why=why)
    j = ser.first_from(plan, EXIT_GAP_S)
    if j is not None and j > i:
        out.update(x_px=px[j], _j=j)
    elif why == "vrijeme":   # nobody traded around the limit: the last print we saw while holding
        j = bisect.bisect_right(ts, plan) - 1
        if j > i:
            out.update(x_px=px[j], stale=True, _j=j)
    return out


def isolated(px, k, x=SPIKE_X, w=SPIKE_K):
    """None, or why print k of a series cannot be a real price: not a positive number, or more than x times away from
    the median of the w prints before it AND of the w after it (x ** 2 when only one side exists)."""
    p = px[k]
    if not (isinstance(p, (int, float)) and math.isfinite(p) and p > 0):
        return "cijena ≤ 0 ili nepoznata"
    sides = [statistics.median(s) for s in (px[max(0, k - w):k], px[k + 1:k + 1 + w]) if s]
    if not sides:
        return None
    far = min(max(p / m, m / p) for m in sides)
    return f"ispis ×{far:.3g} od susjednih" if far > (x if len(sides) == 2 else x * x) else None


def price_flag(t, ser, ep, supply, sol_usd):
    """None, or why the copied trade `t` (simulate's dict) has a price that cannot be real (see SPIKE_X above)."""
    for k, what in ((t.get("_i"), "ulaz"), (t.get("_j"), "izlaz")):
        if k is not None:
            why = isolated(ser.px, k)
            if why:
                return f"{what}: {why}"
    to_usd = (sol_usd or 0) if t["kind"] == "sol" else 1.0
    if supply and to_usd:
        for px, what in ((t["e_px"], "ulaz"), (t.get("x_px"), "izlaz")):
            if px is not None and px * supply * to_usd > MC_MAX:
                return f"{what}: tržišna vrijednost {px * supply * to_usd:.3g} $ (druga jedinica ili drugi pool)"
    his = ep.get("px0")
    if his and his > 0:
        mine = t["e_px"] if t["kind"] == "sol" else (t["e_px"] / sol_usd if sol_usd else None)
        if mine and max(mine / his, his / mine) > SLIP_X:
            return f"ulaz: ×{max(mine / his, his / mine):.3g} od njegove cijene"
    return None


FIELDS = ("wallet", "token", "t0", "ts", "out_ts", "e_px", "x_px", "why", "open", "stale", "kind", "src", "liq", "mc",
          "cost", "his", "gross", "ret", "mirror", "at_his", "slip", "lag", "xsrc", "sumnja", "cap", "ret0", "xliq")


class Trade:
    """One copied trade, slim (tens of thousands are held at once on the 512 MB server); read like a dict."""
    __slots__ = FIELDS

    def __init__(self, d):
        for k in FIELDS:
            setattr(self, k, d.get(k))

    def __getitem__(self, k):
        try:
            return getattr(self, k)
        except AttributeError:
            raise KeyError(k) from None

    def get(self, k, default=None):
        return getattr(self, k, default)


def copy_trade(wallet, ep, delay, rule, tok, sol_usd, fee=None, size=SIZE_SOL, floor=RT_FLOOR, hi=None):
    """One buy as the copier would have traded it, or None when no stored price is near our entry. The SOL prints
    first, the USD series only when the prints cannot price the trade. "ret" None = the exit has no price."""
    from trade import cost
    from wallets import rang
    best = None
    for kind in ("sol", "usd"):
        s = simulate(ep, delay, rule, tok[kind], hi)
        if s is None:
            continue
        s["kind"] = kind
        if best is None or (best["x_px"] is None and s["x_px"] is not None):
            best = s
        if s["x_px"] is not None:
            break
    if best is None:
        return None
    t = best
    liq = liq_near(tok["liq"], t["ts"])
    supply = tok["supply"] or (rang.PUMP_SUPPLY if rang.is_pump(ep["mint"]) else None)
    if t["kind"] == "sol":
        if liq is None and rang.is_pump(ep["mint"]):
            liq = rang.pool_liq_usd(t["e_px"] * rang.PUMP_SUPPLY, sol_usd)
        mc = t["e_px"] * supply * sol_usd if supply else None
    else:
        if liq is None and rang.is_pump(ep["mint"]) and sol_usd:
            liq = rang.pool_liq_usd(t["e_px"] * rang.PUMP_SUPPLY / sol_usd, sol_usd)
        mc = t["e_px"] * supply if supply else None
    rt = max(floor, cost.round_trip(size * sol_usd, liq, fee))
    ser = tok[t["kind"]]
    t.update(wallet=wallet, token=ep["mint"], t0=ep["t0"], liq=liq, mc=mc, cost=rt, his=ep.get("ret"), gross=None,
             ret=None, mirror=None, at_his=None, slip=None, ret0=None, cap=False, xliq=None,
             xsrc=ser.src[t["_j"]] if t.get("_j") is not None else None,
             sumnja=price_flag(t, ser, ep, supply, sol_usd))
    if t["x_px"] is not None and not t["sumnja"]:
        t["gross"] = t["x_px"] / t["e_px"] - 1
        t["ret"] = t["ret0"] = t["gross"] - rt
        # the pool caps the exit: never more out than its whole SOL side (half the USD liquidity)
        xl = liq_near(tok["liq"], t["out_ts"])
        if xl is None and rang.is_pump(ep["mint"]) and sol_usd:
            xl = rang.pool_liq_usd((t["x_px"] if t["kind"] == "sol" else t["x_px"] / sol_usd) * rang.PUMP_SUPPLY,
                                   sol_usd)
        xl = xl or liq
        t["xliq"] = xl
        if xl and sol_usd and size:
            top = xl / 2 / (size * sol_usd) - 1
            if t["gross"] > top:
                t["gross"], t["ret"], t["cap"] = top, top - rt, True
    elif t["x_px"] is not None:   # a price that cannot be real: kept for the diagnosis, out of every number
        if t["e_px"] and t["e_px"] > 0 and math.isfinite(t["x_px"] / t["e_px"]):
            t["gross"] = t["x_px"] / t["e_px"] - 1
            t["ret0"] = t["gross"] - rt   # what the copier counted before 25.11. (demo_exit's legacy pick only)
    if t["kind"] == "sol" and ep.get("px0"):
        t["slip"] = t["e_px"] / ep["px0"] - 1
        if ep.get("sell_px"):
            t["mirror"] = ep["sell_px"] / ep["px0"] - 1
            t["at_his"] = ep["sell_px"] / t["e_px"] - 1
    return Trade(t)


def portfolio(cands, floor=LIQ_FLOOR, need_liq=False, max_open=MAX_OPEN, min_mc=MIN_MC, bad=None, legacy=False):
    """The account's constraints over the candidates of one combination [(position, trade or None)], oldest entry
    first: no token known to be under min_mc, no pool known to be under floor (need_liq: nor an unknown one), one
    position a token, at most max_open open. -> (the copied trades with a result, {reason: count}). A trade whose
    price cannot be real (Trade.sumnja: its result, market cap and pool are all unknown) is counted "sumnjiva_cijena"
    first and is in no number; `bad` (a list) receives those trades (the diagnosis).
    legacy: the rule before 25.11. (no price check, no cap; the result in "ret0"),
    only for the demo exit the demo copies use (demo_exit_legacy)."""
    why = {"kupnji": 0, "kopirano": 0, "bez_cijene_ulaza": 0, "bez_cijene_izlaza": 0, "ispod_30k": 0, "likvidnost": 0,
           "vec_drzimo": 0, "strop": 0, "sumnjiva_cijena": 0}
    held, out = [], []
    for ep, t in sorted(cands, key=lambda c: c[0]["t0"]):
        why["kupnji"] += 1
        if t is None:
            why["bez_cijene_ulaza"] += 1
            continue
        held = [h for h in held if h[0] > t["ts"]]
        if t.get("sumnja") and not legacy:
            # its price cannot be real, so neither its result nor its market cap / pool is known: dropped, counted
            why["sumnjiva_cijena"] += 1
            if bad is not None:
                bad.append(t)
        elif t.get("mc") is not None and t.get("mc") < min_mc:
            why["ispod_30k"] += 1
        elif (t["liq"] is not None and t["liq"] < floor) or (need_liq and t["liq"] is None):
            why["likvidnost"] += 1
        elif any(h[1] == t["token"] for h in held):
            why["vec_drzimo"] += 1
        elif len(held) >= max_open:
            why["strop"] += 1
        else:
            held.append((t["out_ts"], t["token"]))
            if t["ret0" if legacy else "ret"] is None:
                why["bez_cijene_izlaza"] += 1   # we would have been in; what it returned is not known
            else:
                why["kopirano"] += 1
                out.append(t)
    return out, why


# ---------- the numbers ----------------------------------------------------------------------------------------------

def boot_ci(trs, b=B, seed=7, q=0.05):
    """The (q, 1 - q) interval of EV % a trade by the cluster bootstrap over (token, UTC day of the entry): the trades
    of one token on one day move together, so they are resampled together (veliki/walk.boot_ci)."""
    g = {}
    for x in trs:
        s = g.setdefault((x["token"], x["ts"] // D), [0.0, 0])
        s[0] += x["ret"]
        s[1] += 1
    groups = list(g.values())
    if len(groups) < 3:
        return None
    rnd = random.Random(seed)
    out = []
    for _ in range(b):
        sr = sn = 0
        for _k in range(len(groups)):
            s = groups[rnd.randrange(len(groups))]
            sr += s[0]
            sn += s[1]
        out.append(sr / sn * 100 if sn else 0.0)
    out.sort()
    return [round(out[int(q * b)], 2), round(out[int((1 - q) * b) - 1], 2)]


def max_dd(trs, size=SIZE_SOL):
    eq = peak = dd = 0.0
    for x in sorted(trs, key=lambda x: x["out_ts"]):
        eq += x["ret"] * size
        peak = max(peak, eq)
        dd = min(dd, eq - peak)
    return round(dd, 4)


def _without_best(trs, key):
    """EV % of the trades without the group (a token / a wallet) that earned the most; None when nothing is left."""
    sums = {}
    for x in trs:
        sums[x[key]] = sums.get(x[key], 0.0) + x["ret"]
    if not sums:
        return None
    best = max(sums, key=sums.get)
    rest = [x["ret"] for x in trs if x[key] != best]
    return round(sum(rest) / len(rest) * 100, 2) if rest else None


def brief(trs, min_n=MIN_N, size=SIZE_SOL, full=True):
    """n, EV % a trade (after delay and cost), the 90 % interval, hit rate, median hold, sum in SOL, max drawdown, the
    result without the best token / wallet, and the pessimistic EV (every exit valued at a last known price counted as
    a total loss). Under min_n trades only {"n", "malo": True}: "premalo podataka", never a finding."""
    n = len(trs)
    if n < min_n:
        return {"n": n, "malo": True}
    rets = [x["ret"] for x in trs]
    s = {"n": n, "ev_pct": round(sum(rets) / n * 100, 2), "ci90": boot_ci(trs),
         "hit": round(sum(1 for r in rets if r > 0) / n, 3), "sum_sol": round(sum(rets) * size, 4),
         "med_pct": round(statistics.median(rets) * 100, 2)}
    if full:
        soft = sum(1 for x in trs if x["open"] or x["stale"])
        pess = [(-1.0 if (x["open"] or x["stale"]) else x["ret"]) for x in trs]
        s.update(hold_med_min=round(statistics.median((x["out_ts"] - x["ts"]) / 60 for x in trs), 1),
                 max_dd_sol=max_dd(trs, size), bez_tokena_pct=_without_best(trs, "token"),
                 bez_novcanika_pct=_without_best(trs, "wallet"),
                 zadnja_cijena=soft, ev_pes_pct=round(sum(pess) / n * 100, 2),
                 izlazi={k: sum(1 for x in trs if x["why"] == k) for k in ("prodao", "stop", "vrijeme", "otvoreno")})
    return s


def gap(trs, min_n=MIN_N):
    """The wallet's own return against ours on the SAME trades, in plain percentage points that add up:
    njegov (his realized return on the position) -> jedan_ulaz_izlaz (one buy at his first fill, all sold at his first
    sale) -> nas_ulaz (our entry `delay` later, his sale price) -> nas_izlaz (our exit, before cost) -> nase (after
    cost). Only trades priced by SOL prints whose position he closed (every one of the five numbers is known)."""
    xs = [x for x in trs if x["kind"] == "sol" and x["his"] is not None and x["mirror"] is not None]
    n = len(xs)
    if n < min_n:
        return {"n": n, "malo": True}
    m = lambda k: sum(x[k] for x in xs) / n * 100   # noqa: E731
    his, mir, at_his, gross, net = m("his"), m("mirror"), m("at_his"), m("gross"), m("ret")
    return {"n": n, "njegov_pct": round(his, 2), "jedan_ulaz_izlaz_pct": round(mir, 2), "nas_ulaz_pct": round(at_his, 2),
            "nas_izlaz_pct": round(gross, 2), "nase_pct": round(net, 2),
            "skaliranje_pp": round(mir - his, 2), "ulaz_pp": round(at_his - mir, 2), "izlaz_pp": round(gross - at_his, 2),
            "trosak_pp": round(net - gross, 2), "razlika_pp": round(net - his, 2),
            "ulaz_med_pct": round(statistics.median(x["slip"] for x in xs) * 100, 2),
            "njegov_med_pct": round(statistics.median(x["his"] for x in xs) * 100, 2),
            "nase_med_pct": round(statistics.median(x["ret"] for x in xs) * 100, 2)}


def own_result(eps):
    """The picked wallets' OWN result on the measured part (their fills, no delay, no cost of ours): did they stay
    profitable after the split?"""
    done = [e["ret"] for e in eps if e.get("ret") is not None]
    out = {"kupnji": len(eps), "zatvoreno": len(done)}
    if done:
        out.update(prosjek_pct=round(sum(done) / len(done) * 100, 2), medijan_pct=round(statistics.median(done) * 100, 2),
                   pogodak=round(sum(1 for r in done if r > 0) / len(done), 3))
    return out


def groups(trs, hold_of, min_n=MIN_N):
    """The primary combination's trades by market cap, pool liquidity and the wallet's usual hold time."""
    out = {}
    for name, key in (("mc", lambda x: _bucket(x["mc"], MC_B)), ("likvidnost", lambda x: _bucket(x["liq"], LIQ_B)),
                      ("drzanje", lambda x: _bucket(hold_of.get(x["wallet"]), HOLD_B))):
        per = {}
        for x in trs:
            per.setdefault(key(x), []).append(x)
        order = [b[1] for b in {"mc": MC_B, "likvidnost": LIQ_B, "drzanje": HOLD_B}[name]] + ["nepoznato"]
        out[name] = [{"naziv": k, **brief(per[k], min_n, full=False)} for k in order if k in per]
    return out


# ---------- the diagnosis (25.11.) ----------------------------------------------------------------------------------------

SRC_SHORT = ("trgovina", "svijeća 1 min", "snimka poola", "svijeća 15 min")


def table_combos():
    """The combinations of the report's small table (summary rows), in its order (the strict row apart)."""
    out = [PRIMARY]
    out += [(PRIMARY[0], d, PRIMARY[2]) for d in DELAYS if d != PRIMARY[1]]
    out += [(PRIMARY[0], PRIMARY[1], x) for x in EXITS if x != PRIMARY[2]]
    out += [(r, PRIMARY[1], PRIMARY[2]) for r in RULES if r != PRIMARY[0]]
    return out


def _ratio(t):
    try:
        return abs(math.log(t["x_px"] / t["e_px"]))
    except (TypeError, ValueError, ZeroDivisionError, OverflowError):
        return float("inf")


def extremes(trs, k=DIAG_N):
    """The k trades with the largest move between our entry and exit price (either way), dropped ones included."""
    return sorted((t for t in trs if t["x_px"] is not None), key=_ratio, reverse=True)[:k]


def symbols(p, mints):
    """{mint: symbol} from the token tables we keep (midcap, veliki, kol); a mint without one is shown shortened.
    Read-only, at most a few dozen mints (the diagnosis only)."""
    out, mints = {}, [m for m in mints if m][:200]
    if not mints:
        return out
    marks = ",".join("?" * len(mints))
    for key, sql in (("midcap", f"SELECT mint, symbol FROM tokens WHERE mint IN ({marks})"),
                     ("veliki", f"SELECT mint, symbol FROM tokens WHERE mint IN ({marks})"),
                     ("kol", f"SELECT token, symbol FROM tokens WHERE token IN ({marks})")):
        con = _ro((p or {}).get(key))
        try:
            for m, sym in _q(con, sql, mints):
                if sym and m not in out:
                    out[m] = str(sym)[:16]
        finally:
            if con is not None:
                con.close()
    return out


def _trade_txt(t, sym):
    unit = "SOL" if t["kind"] == "sol" else "$"
    src = SRC_SHORT[t["src"]] if t["src"] is not None else "?"
    xsrc = SRC_SHORT[t["xsrc"]] if t.get("xsrc") is not None else "?"
    liq = f", likv. {t['liq']:,.0f} $" if t.get("liq") else ", likv. nepoznata"
    tail = (f" IZBAČEN ({t['sumnja']})" if t.get("sumnja") else
            f" {t['gross'] * 100:+.0f} % (ograničeno likvidnošću)" if t.get("cap") else
            f" {t['gross'] * 100:+.0f} %" if t.get("gross") is not None else "")
    return (f"{sym.get(t['token']) or (t['token'] or '?')[:6] + '…'} ulaz {t['e_px']:.4g} {unit} ({src}), izlaz "
            f"{t['x_px']:.4g} {unit} ({xsrc}){liq}{tail}")


def diag_line(diag, sym):
    """One log line: per table row the number of trades dropped for their price and its most extreme trades (token
    symbol, entry and exit price, the price source of each, the pool liquidity; never a wallet address)."""
    parts = []
    for combo, dropped, trs in diag:
        body = "; ".join(_trade_txt(t, sym) for t in trs) or "bez tradeova"
        parts.append(f"[{combo}: izbačeno {dropped} zbog sumnjive cijene; najekstremniji: {body}]")
    return "novčanici kopija dijagnostika: " + " ".join(parts)


# ---------- the run --------------------------------------------------------------------------------------------------

def _combo(rule, delay, ex):
    return f"{rule}/{delay}/{ex}"


def compute(con, now, p=None, budget_s=BUDGET_S, fee=None, size=SIZE_SOL, floor=RT_FLOOR, max_days=MAX_DAYS):
    """The whole measurement over wallets.db `con` (see the module text). Bounded by budget_s: a cut pass says
    "partial" and reports what it had."""
    from wallets import rang
    t_start = time.time()
    deadline = t_start + budget_s if budget_s else None
    p = paths(p)
    days, newest = trade_days(con, now, max_days)
    train, hold, split = split_days(days)
    res = {"ts": int(now), "day": time.strftime("%Y-%m-%d", time.gmtime(now + 3600)), "days": len(days),
           "train_days": len(train), "hold_days": len(hold), "split_ts": split, "to_ts": newest, "size_sol": size,
           "floor_pct": round(floor * 100, 2), "max_open": MAX_OPEN, "grid_n": len(RULES) * len(DELAYS) * len(EXITS),
           "primary": _combo(*PRIMARY), "biases": list(BIASES), "partial": False}
    if split is None:
        res["verdict"] = (f"Premalo podataka: u bazi je {len(days)} dana s tradeovima novčanika, a za podjelu na stariji i "
                          f"noviji dio treba ih barem {MIN_DAYS}.")
        res["secs"] = round(time.time() - t_start, 1)
        return res
    hi = min(int(now), (newest or int(now)) + HOLD_S)
    sel = select(con, split, p, deadline)
    res["partial"] = sel["partial"]
    res["scored"] = sel["scored"]
    res["odabir"] = {r: len(ws) for r, ws in sel["rules"].items()}
    res["prolazi"] = sel["passed"]
    chosen = sorted({w for ws in sel["rules"].values() for w in ws})
    hold_of = {w: sel["info"][w].get("hold_min") for w in chosen}
    eps_w, by_mint = {}, {}
    for w in chosen:
        tr = trades_of(con, w, split - 2 * rang.WINDOW_D * D, int(now) + 1)
        eps = [e for e in episodes(tr) if e["t0"] >= split and e["sol0"] >= MIN_SOL]
        eps_w[w] = eps
        for e in eps:
            by_mint.setdefault(e["mint"], []).append((w, e))
    res["own"] = {r: own_result([e for w in ws for e in eps_w.get(w, [])]) for r, ws in sel["rules"].items()}
    sols = rang.sol_usd_days(p.get("market"))
    pr = Prices(p, split - 60, hi)
    cands = {(d, x): [] for d in DELAYS for x in EXITS}
    try:
        if not pr.load_prints(con, by_mint, deadline):
            res["partial"] = True
        done = buys = 0
        # a cut pass (time or MAX_BUYS) must stay a fair sample: the tokens in a fixed pseudo-random order
        for mint in sorted(by_mint, key=lambda m: zlib.crc32(m.encode())):
            lst = by_mint[mint]
            if (deadline and time.time() > deadline) or buys + len(lst) > MAX_BUYS:
                res["partial"] = True
                break
            buys += len(lst)
            tok = pr.token(mint)
            for w, e in lst:
                for d in DELAYS:
                    su = rang.sol_at(sols, e["t0"] + d)
                    for x in EXITS:
                        cands[(d, x)].append((w, e, copy_trade(w, e, d, x, tok, su, fee, size, floor, hi)))
            done += 1
        res["tokens"], res["tokens_all"] = done, len(by_mint)
    finally:
        pr.close()
    rows, per, legacy, diag = [], {}, [], []
    shown = set(table_combos())
    for r in RULES:
        ws = set(sel["rules"][r])
        strict = r == "likvidnost"
        for d in DELAYS:
            for x in EXITS:
                mine = [(e, t) for w, e, t in cands[(d, x)] if w in ws]
                bad = []
                trs, why = portfolio(mine, LIQ_STRICT if strict else LIQ_FLOOR, strict, bad=bad)
                per[_combo(r, d, x)] = trs
                st = brief(trs)
                rows.append({"rule": r, "delay": d, "exit": x, **st, "kupnji": why["kupnji"],
                             "nekopirano": round(1 - why["kopirano"] / why["kupnji"], 3) if why["kupnji"] else None,
                             "razlozi": why, "ograniceno": sum(1 for t in trs if t["cap"])})
                if (r, d, x) in shown:
                    diag.append((_combo(r, d, x), why["sumnjiva_cijena"], extremes(trs + bad)))
                if (r, d) == PRIMARY[:2]:   # the demo exit as picked before 25.11. (see demo_exit_legacy)
                    old, _w = portfolio(mine, LIQ_FLOOR, False, legacy=True)
                    legacy.append({"rule": r, "delay": d, "exit": x, "n": len(old), "malo": len(old) < MIN_N,
                                   "ev_pct": round(sum(t["ret0"] for t in old) / len(old) * 100, 2) if old else None})
    res["grid"] = rows
    prim = per[_combo(*PRIMARY)]
    early = {w for w in sel["rules"][PRIMARY[0]] if sel["info"][w].get("rano")}
    bad = []
    strict, why_s = portfolio([(e, t) for w, e, t in cands[PRIMARY[1:]] if w in early], bad=bad)
    res["strict"] = {"wallets": len(early), **brief(strict), "razlozi": why_s,
                     "ograniceno": sum(1 for t in strict if t["cap"])}
    diag.append(("strict", why_s["sumnjiva_cijena"], extremes(strict + bad)))
    res["dijagnostika"] = diag_line(diag, symbols(p, {t["token"] for _c, _n, ts in diag for t in ts}))
    res["gap"] = gap(prim)
    res["gap_delay"] = {str(d): gap(per[_combo(PRIMARY[0], d, PRIMARY[2])]) for d in DELAYS}
    res["groups"] = groups(prim, hold_of)
    res["sources"] = {SRC_HR[k]: sum(1 for t in prim if t["src"] == k) for k in range(len(SRC_HR))
                      if any(t["src"] == k for t in prim)}
    res["cost_med_pct"] = round(statistics.median(t["cost"] for t in prim) * 100, 2) if prim else None
    res["lag_med_s"] = statistics.median(t["lag"] for t in prim) if prim else None   # his buy -> the print we priced at
    # 25.11.: the demo copies (wallets/kopija_demo.exit_rule) read "demo_exit". Vlasnik 25.11. ("Demo izlaz čisti"):
    # it is the pick on the CLEAN rows (after the price check); "demo_exit_staro" is the pick the way it was made
    # before the check (legacy rows), kept so the report can say when the two differ. Demo only: real money never
    # reads this.
    res["demo_exit"] = demo_exit(rows)
    res["prije_provjere"] = legacy   # the primary rule and delay as counted before the price check (the diagnosis)
    res["demo_exit_cisti"] = res["demo_exit"]
    res["demo_exit_staro"] = demo_exit(legacy)
    res["verdict"] = verdict(res)
    res["secs"] = round(time.time() - t_start, 1)
    return res


def _hr(v, d=1):
    """A signed number the Croatian way (+3,4)."""
    return f"{v:+.{d}f}".replace(".", ",")


def row_of(res, rule, delay, ex):
    return next((r for r in (res or {}).get("grid") or [] if (r["rule"], r["delay"], r["exit"]) == (rule, delay, ex)), None)


def demo_exit(rows):
    """The exit the demo copies use: of the three pre-declared exits, the best EV at the primary rule and delay among
    those with MIN_N+ trades; the primary exit before any such result. A pick among three on the measured part, so
    the demo's own prospective copies are its test."""
    ok = [r for r in rows if (r["rule"], r["delay"]) == PRIMARY[:2] and not r.get("malo")]
    return max(ok, key=lambda r: r["ev_pct"])["exit"] if ok else PRIMARY[2]


def _sumnja(r, res=None):
    """report/razumno.sumnja of one grid row: None, or why its numbers cannot be real (25.11.)."""
    from report import razumno
    return razumno.sumnja(r, (res or {}).get("size_sol") or SIZE_SOL) if r else None


def _dropped(r):
    return ((r or {}).get("razlozi") or {}).get("sumnjiva_cijena") or 0


def verdict(res):
    """One sentence for a non-programmer. 25.11.: never on a row whose numbers cannot be real."""
    r = row_of(res, *PRIMARY) or {}
    own = (res.get("own") or {}).get(PRIMARY[0]) or {}
    if own.get("prosjek_pct") is not None and _sumnja({"ev_pct": own.get("prosjek_pct"),
                                                       "med_pct": own.get("medijan_pct")}):
        own = {}
    bad = _sumnja(r, res) if not r.get("malo") else None
    if bad:
        return (f"Glavni red ima sumnjive podatke ({bad}), pa presude nema: red je izostavljen dok se izvor cijene ne "
                "popravi.")
    picked = (res.get("odabir") or {}).get(PRIMARY[0]) or 0
    if not picked:
        return (f"Na starijem dijelu podataka ({res.get('train_days')} dana) nijedan novčanik ne prolazi „dokazan dvaput i "
                "kopirljiv”, pa se kopiranje nema na čemu izmjeriti.")
    if r.get("malo") or not r.get("n"):
        return (f"Premalo podataka: {picked} novčanika odabranih na starijem dijelu u novijih {res.get('hold_days')} dana "
                f"dalo je samo {r.get('n') or 0} kopija s poznatom cijenom (treba {MIN_N}); od {r.get('kupnji') or 0} "
                "njihovih kupnji ostale nemaju zabilježenu cijenu u trenutku našeg ulaza ili izlaza.")
    ci = r.get("ci90") or [None, None]
    his = (f" Isti novčanici na svojim cijenama, sve njihove pozicije zatvorene u tom razdoblju: prosjek "
           f"{_hr(own['prosjek_pct'])} %." if own.get("prosjek_pct") is not None else "")
    num = f"{_hr(r['ev_pct'])} % po tradeu nakon kašnjenja od 60 s i troška (n = {r['n']}"
    if ci[0] is not None:
        num += f", interval 90 %: {_hr(ci[0])} do {_hr(ci[1])} %"
    num += ")"
    if _dropped(r):
        num += f"; izbačeno {_dropped(r)} tradeova zbog sumnjive cijene"
    if ci[0] is not None and ci[0] > 0:
        return f"Kopiranje dokazanih novčanika bilo bi u plusu: {num}.{his}"
    if r["ev_pct"] > 0:
        return ("Kopiranje dokazanih novčanika je u blagom plusu, ali plus nije dokazan (interval ide ispod nule): "
                f"{num}.{his}")
    return f"Kopiranje dokazanih novčanika ne bi zaradilo: {num}.{his}"


# ---------- what is stale, and what refreshing would cost ---------------------------------------------------------------

def freshness(con, now, newest=None):
    """How old the data this measurement (and the live "dokazan dvaput" list) lives on is, whether the jobs that
    refresh it are switched off by the midcap focus, and what switching the refresh on would cost in Helius credits
    (measured from wallets.db helius_credits, the scorer's own counter)."""
    now = int(now)
    out = {"fokus": False}
    try:
        from ops import fokus
        out["fokus"] = bool(fokus.on())
        out["ugaseno"] = [k for k in ("wallets_harvest", "wallets_score") if k in fokus._OFF_KEYS]
    except Exception:  # noqa: BLE001
        out["ugaseno"] = []
    r = _q(con, "SELECT MAX(scored_at), COUNT(*) FROM wallets WHERE scored_at IS NOT NULL")
    out["zadnja_ocjena_ts"], out["ocijenjeno"] = (r[0][0], r[0][1]) if r else (None, 0)
    if newest is None:   # (the measurement passes the newest trade it already found: no second scan)
        r = _q(con, "SELECT MAX(ts) FROM wallet_trades")
        newest = r[0][0] if r else None
    out["zadnji_trade_ts"] = newest
    r = _q(con, "SELECT MAX(as_of) FROM dokazani")
    out["dokazani_ts"] = r[0][0] if r else None
    r = _q(con, "SELECT COUNT(*) FROM dokazani WHERE passed = 1 AND as_of = (SELECT MAX(as_of) FROM dokazani)")
    out["dokazanih"] = r[0][0] if r else 0
    day = {}
    for d, c, k in _q(con, "SELECT ts / 86400, SUM(credits), COUNT(*) FROM helius_credits WHERE ts >= ? AND method IN "
                           "('wallet_history', 'early_buyers') GROUP BY 1", (now - 30 * D,)):
        day[int(d)] = (c or 0, k or 0)
    last7 = [day[d] for d in sorted(day)[-7:]]
    out["kredita_dan_prije"] = round(sum(c for c, _k in last7) / len(last7)) if last7 else None
    r = _q(con, "SELECT SUM(credits), COUNT(*) FROM helius_credits WHERE ts >= ? AND method = 'wallet_history'",
           (now - 30 * D,))
    per = (r[0][0] / r[0][1]) if r and r[0][1] else 10.0   # one page of 100 transactions = 10 credits
    c = config()
    n = min(int(c["najvise_novcanika"]), max(out["dokazanih"] or 0, 0) + TOP_N)
    out.update(osvjezi=bool(c["osvjezi"]), strop_kredita_dan=int(c["kredita_dan"]), kredita_po_provjeri=round(per, 1),
               novcanika_za_osvjezavanje=n, svakih_h=c["svakih_h"],
               procjena_kredita_dan=int(min(c["kredita_dan"], n * per * 24 / max(1, c["svakih_h"]))))
    return out


def freshness_lines(f, now):
    """What is stale and what the refresh would cost, in plain Croatian."""
    if not f:
        return []
    age = lambda ts: None if not ts else (now - ts) / 3600   # noqa: E731
    out = []
    a, s = age(f.get("zadnji_trade_ts")), age(f.get("zadnja_ocjena_ts"))
    if f.get("fokus") and f.get("ugaseno"):
        out.append("Zbog prekidača „fokus midcap” od 15.11. ne rade skupljanje i ocjenjivanje novčanika (Helius), pa se "
                   "povijest tradeova novčanika više ne puni"
                   + (f": zadnji spremljeni trade je star {a:.0f} h, zadnja ocjena {s:.0f} h." if a is not None and
                      s is not None else "."))
        out.append("Posljedica: popis „dokazan dvaput” traži zatvorene pozicije u zadnjih 5 dana, pa se bez novih tradeova "
                   f"sam isprazni oko 5 dana nakon gašenja (sada {f.get('dokazanih') or 0} novčanika); rang gleda 30 dana i "
                   "polako stari; demo kopije i ovaj test ostaju bez novih podataka.")
    elif a is not None:
        out.append(f"Podaci su svježi: zadnji spremljeni trade prije {a:.0f} h, zadnja ocjena prije {s or 0:.0f} h.")
    was = f.get("kredita_dan_prije")
    out.append(f"Prijedlog (isključeno dok vlasnik ne odobri; wallets/config.json „kopija” osvjezi): osvježavati samo "
               f"dokazane i najbolje rangirane novčanike ({f.get('novcanika_za_osvjezavanje')}), svakih "
               f"{f.get('svakih_h')} h: oko "
               f"{f.get('procjena_kredita_dan')} Helius kredita dnevno (strop {f.get('strop_kredita_dan')}; izmjereno "
               f"{str(f.get('kredita_po_provjeri')).replace('.', ',')} kredita po provjeri)"
               + (f"; cijelo skupljanje i ocjenjivanje prije gašenja trošilo je oko {was} kredita dnevno." if was else "."))
    if f.get("osvjezi"):
        out.append("Osvježavanje dokazanih novčanika je UKLJUČENO u konfiguraciji.")
    return out


# ---------- the run, the stored result ----------------------------------------------------------------------------------

def latest(path=None):
    """The stored result (wallets.db copy_rank_kv "kopija") or None."""
    from wallets import store as wstore
    con = _ro(path or wstore.DB)
    if con is None:
        return None
    try:
        r = con.execute("SELECT v FROM copy_rank_kv WHERE k = ?", (KV,)).fetchone()
        return json.loads(r[0]) if r and r[0] else None
    except (sqlite3.Error, ValueError):
        return None
    finally:
        con.close()


def line(res):
    """The one log line with the headline numbers."""
    r = row_of(res, *PRIMARY) or {}
    g = res.get("gap") or {}
    head = (PREFIX + f"{(res.get('odabir') or {}).get(PRIMARY[0], 0)} novčanika „dokazan dvaput i kopirljiv” odabrano na "
            f"prvih {res.get('train_days')} dana, mjereno na zadnjih {res.get('hold_days')}"
            + (" (djelomično: vremenski budžet)" if res.get("partial") else ""))
    if res.get("split_ts") is None:
        return PREFIX + (res.get("verdict") or "premalo podataka")
    if r.get("malo") or not r.get("n"):
        body = f"; kopija s cijenom n={r.get('n') or 0} od {r.get('kupnji') or 0} kupnji (premalo podataka)"
    else:
        ci = r.get("ci90") or ["—", "—"]
        body = (f"; kašnjenje 60 s, njegov izlaz ili stop −20 %: n={r['n']}, EV {r['ev_pct']:+.2f} % po tradeu, interval "
                f"90 % [{ci[0]}; {ci[1]}], pogodak {r['hit']:.0%}, zbroj {r['sum_sol']:+.3f} SOL, nekopirano "
                f"{(r.get('nekopirano') or 0):.0%} kupnji, izbačeno {_dropped(r)} zbog sumnjive cijene"
                + (f" (SUMNJIVI PODACI: {_sumnja(r, res)})" if _sumnja(r, res) else ""))
    if g and not g.get("malo"):
        body += (f"; njegov rezultat na istim tradeovima {g['njegov_pct']:+.1f} %, naš {g['nase_pct']:+.1f} %: ulaz "
                 f"{g['ulaz_pp']:+.1f}, izlaz {g['izlaz_pp']:+.1f}, trošak {g['trosak_pp']:+.1f}, jedan ulaz i izlaz "
                 f"{g['skaliranje_pp']:+.1f} postotnih bodova")
    good = sum(1 for x in res.get("grid") or [] if not x.get("malo") and not _sumnja(x, res)
               and (x.get("ci90") or [0])[0] > 0)
    return (head + body + f"; isprobano {res.get('grid_n')} kombinacija, s donjom granicom iznad nule: {good}"
            f" ({res.get('secs')} s)")


def run(now=None, log=print, path=None, p=None, budget_s=None, fee=None, save=True):
    """One pass: compute() over wallets.db, the result into copy_rank_kv "kopija", one log line. Local databases only,
    bounded by budget_s. Never raises: {} and a log line when it cannot run."""
    from wallets import rang, store as wstore
    now = int(now or time.time())
    try:
        path = path or wstore.DB
        con = _ro(path)
        if con is None:
            log(PREFIX + "nema podataka (wallets.db još ne postoji)")
            return {}
        try:
            res = compute(con, now, dict(p or {}, wallets=path), BUDGET_S if budget_s is None else budget_s, fee)
            res["svjezina"] = freshness(con, now, res.get("to_ts"))
        finally:
            con.close()
        kept = ""
        if save and not res.get("grid") and (latest(path) or {}).get("grid"):
            kept = "; zadnji spremljeni rezultat ostaje"   # a pass without a result never erases one
        elif save:
            wcon = wstore.connect(path)
            try:
                rang.ensure(wcon)
                wcon.execute("INSERT OR REPLACE INTO copy_rank_kv VALUES (?, ?)", (KV, dumps(res)))
                wcon.commit()
            finally:
                wcon.close()
        if res.get("dijagnostika"):
            log(res["dijagnostika"])
        log(line(res) + kept)
        return res
    except Exception as e:  # noqa: BLE001 - a measurement: it never takes its caller down
        try:
            log(PREFIX + f"nije uspio ({type(e).__name__}: {e})")
        except Exception:  # noqa: BLE001
            pass
        return {}


# ---------- the report's view ---------------------------------------------------------------------------------------------

def _row(name, m, size=SIZE_SOL):
    """One table row. 25.11.: "izbaceno" (trades dropped for a price that cannot be real), "ograniceno" (exits capped
    by the pool), "medijan_pct"; "sumnja" (report/razumno) when the row's numbers still cannot be real: the renderers
    then print "sumnjivi podaci, red izostavljen" instead of them (also for a result stored before this check)."""
    m = m or {}
    why = m.get("razlozi") or {}
    if m.get("malo") or not m.get("n"):
        return {"naziv": name, "n": m.get("n", 0), "malo": True, "izbaceno": why.get("sumnjiva_cijena")}
    out = {"naziv": name, "n": m["n"], "ev_pct": m.get("ev_pct"), "medijan_pct": m.get("med_pct"), "ci": m.get("ci90"),
           "pogodak": m.get("hit"), "zbroj_sol": m.get("sum_sol"), "max_pad_sol": m.get("max_dd_sol"),
           "nekopirano": m.get("nekopirano"), "izbaceno": why.get("sumnjiva_cijena"),
           "ograniceno": m.get("ograniceno")}
    from report import razumno
    bad = razumno.sumnja(out, size)
    if bad:
        out["sumnja"] = bad
    return out


def gap_lines(g):
    """The decomposition in sentences; [] while there are too few trades."""
    if not g or g.get("malo"):
        return []
    f = _hr
    return [f"Na istih {g['n']} tradeova novčanici su na svojim cijenama zaradili {f(g['njegov_pct'])} % po poziciji, "
            f"a mi bismo {f(g['nase_pct'])} %: razlika {f(g['razlika_pp'])} postotnih bodova.",
            f"Jedan ulaz i jedan izlaz umjesto njegovih dokupa i prodaja u dijelovima: {f(g['skaliranje_pp'])}.",
            f"Kašnjenje ulaza (kupujemo nakon njega, tipično {f(g['ulaz_med_pct'])} % skuplje): {f(g['ulaz_pp'])}.",
            f"Kašnjenje izlaza i naš stop: {f(g['izlaz_pp'])}.",
            f"Trošak kupnje i prodaje (naknade i utjecaj na cijenu): {f(g['trosak_pp'])}.",
            f"Tipičan trade (medijan): njegov {f(g['njegov_med_pct'])} %, naš {f(g['nase_med_pct'])} %."]


def summary(res, now=None):
    """What the morning report and /strategije show (plain Croatian): the verdict, the small table, the decomposition,
    the notes, what is stale, the known biases; None without a result."""
    if not res or not res.get("ts"):
        return None
    now = int(now or time.time())
    size = res.get("size_sol") or SIZE_SOL
    rows = []
    if res.get("grid"):
        for c in table_combos():
            name = ("Glavno pravilo: dokazan dvaput i kopirljiv, 60 s, njegov izlaz ili stop −20 %" if c == PRIMARY else
                    f"Isto, kašnjenje {c[1]} s" if c[1] != PRIMARY[1] else
                    f"Isto, izlaz: {EXIT_HR[c[2]]}" if c[2] != PRIMARY[2] else RULE_HR[c[0]])
            rows.append(_row(name, row_of(res, *c), size))
        st = res.get("strict") or {}
        rows.append(_row(f"Glavno pravilo, samo novčanici koje je alat ocijenio prije reza ({st.get('wallets') or 0})", st,
                         size))
    grid = [x for x in res.get("grid") or [] if not x.get("malo")]
    broken = [x for x in grid if _sumnja(x, res)]
    grid = [x for x in grid if not _sumnja(x, res)]
    good = sum(1 for x in grid if (x.get("ci90") or [0])[0] > 0)
    prim = row_of(res, *PRIMARY) or {}
    why = prim.get("razlozi") or {}
    notes = []
    if res.get("grid"):
        notes.append(f"Isprobano {res.get('grid_n')} unaprijed zadanih kombinacija (4 odabira novčanika × 3 kašnjenja × 3 "
                     f"izlaza); dovoljno tradeova ima {len(grid)}, donju granicu intervala iznad nule {good}. Uz interval "
                     f"od 90 % otprilike svaka dvadeseta ({len(grid) / 20:.0f}) može ispasti dobra pukim slučajem.")
        od = res.get("odabir") or {}
        pa = res.get("prolazi") or {}
        notes.append(f"Odabrano na starijem dijelu ({res.get('train_days')} dana), od {res.get('scored')} ocijenjenih "
                     f"novčanika: dokazan dvaput i kopirljiv {od.get('app', 0)}, prvih po ocjeni {od.get('top', 0)}, "
                     f"dokazan jednom {od.get('jednom', 0)}. Mjereno samo na novijem dijelu ({res.get('hold_days')} dana)."
                     + (f" Pravilo „dokazan jednom” prolazi {pa.get('jednom')} novčanika; kopira se najviše {MAX_WALLETS} "
                        "najbolje ocijenjenih, koliko ih stane na praćenje u stvarnom vremenu."
                        if (pa.get("jednom") or 0) > MAX_WALLETS or (pa.get("app") or 0) > MAX_WALLETS else ""))
    if broken:
        notes.append(f"{len(broken)} od {len(broken) + len(grid)} kombinacija s dovoljno tradeova ima nemoguće brojke "
                     "(prosjek, interval ili zbroj izvan onoga što ulog može dati): u tablicama piše „sumnjivi podaci, red "
                     "izostavljen” i ne broje se ni u presudi ni u broju dobrih kombinacija.")
    if why.get("kupnji"):
        notes.append(f"Od {why['kupnji']} njihovih kupnji u mjerenom dijelu kopirano je {why['kopirano']}; bez cijene u "
                     f"trenutku našeg ulaza {why['bez_cijene_ulaza']}, bez cijene izlaza {why['bez_cijene_izlaza']}, "
                     + (f"izbačeno zbog sumnjive cijene {why['sumnjiva_cijena']}, " if "sumnjiva_cijena" in why else "")
                     + f"token ispod 30k $ {why.get('ispod_30k', 0)}, "
                     f"likvidnost ispod praga {why['likvidnost']}, token već držimo {why['vec_drzimo']}, strop od "
                     f"{res.get('max_open')} otvorenih {why['strop']}."
                     + (f" Kod {prim['ograniceno']} kopiranih izlaz je ograničen likvidnošću poola (više od cijele SOL "
                        "strane poola ne može se izvući)." if prim.get("ograniceno") else ""))
    if "sumnjiva_cijena" in why:
        notes.append("Sumnjiva cijena (izbačeno i brojeno, ne rezano): ulazni ili izlazni ispis ≤ 0, ispis više od "
                     f"{SPIKE_X:.0f}× daleko od susjednih ispisa s obje strane, tržišna vrijednost iznad "
                     f"{MC_MAX / 1e9:.0f} mlrd $ (druga jedinica ili drugi pool) ili naš ulaz više od {SLIP_X:.0f}× od "
                     "njegove cijene. Velik dobitak sam po sebi nije razlog za izbacivanje. Prosjek je prosjek čistih "
                     "tradeova; medijan je u dnevniku i na /strategije.")
    if res.get("demo_exit_staro") and res.get("demo_exit_staro") != res.get("demo_exit"):
        notes.append(f"Demo kopije koriste izlaz „{EXIT_HR.get(res.get('demo_exit'), '?')}”, izabran na očišćenim "
                     "podacima (vlasnik 25.11.); prije provjere cijena bio bi izabran "
                     f"„{EXIT_HR.get(res['demo_exit_staro'], '?')}”.")
    own = (res.get("own") or {}).get(PRIMARY[0]) or {}
    if own.get("prosjek_pct") is not None and _sumnja({"ev_pct": own["prosjek_pct"], "med_pct": own.get("medijan_pct")}):
        notes.append("Vlastiti rezultat odabranih novčanika ima nemoguće brojke (sumnjivi podaci), pa nije prikazan.")
        own = {}
    if own.get("prosjek_pct") is not None:
        notes.append(f"Odabrani novčanici na vlastitim cijenama u mjerenom dijelu: {own['zatvoreno']} zatvorenih pozicija "
                     f"od {own['kupnji']} kupnji, prosjek {_hr(own['prosjek_pct'])} %, medijan {_hr(own['medijan_pct'])} %, "
                     f"u plusu {own['pogodak']:.0%}.")
    if prim.get("zadnja_cijena") and not _sumnja(prim, res) and not _sumnja({"ev_pct": prim.get("ev_pes_pct")}):
        notes.append(f"{prim['zadnja_cijena']} od {prim['n']} tradeova vrednovano je zadnjom poznatom cijenom (nije prodao "
                     f"do kraja podataka ili nitko nije trgovao oko izlaza); kad bi svi bili potpuni gubitak, prosjek bi "
                     f"bio {_hr(prim['ev_pes_pct'])} %.")
    if res.get("sources"):
        notes.append("Izvor cijene našeg ulaza: " + ", ".join(f"{k} {v}" for k, v in res["sources"].items())
                     + f". Cijena našeg ulaza je tipično ispis {res.get('lag_med_s'):.0f} s nakon njegove kupnje (zadano "
                       f"kašnjenje {PRIMARY[1]} s, pa prvi zabilježeni ispis). Trošak kruga tipično "
                       f"{str(res.get('cost_med_pct')).replace('.', ',')} % (nikad ispod "
                       f"{str(res.get('floor_pct')).replace('.', ',')} %).")
    st = res.get("strict") or {}
    if res.get("grid") and (res.get("odabir") or {}).get(PRIMARY[0]):
        notes.append(f"Od {res['odabir'][PRIMARY[0]]} odabranih novčanika alat je {st.get('wallets') or 0} prvi put "
                     "ocijenio prije reza; ostale je pronašao kasnije (možda baš zato što su u mjerenom dijelu dobro "
                     "kupili), pa glavni red može biti ljepši od stvarnog. Zadnji red tablice mjeri samo one poznate prije "
                     "reza.")
    if res.get("partial"):
        notes.append(f"Djelomičan prolaz (ograničenje vremena ili memorije): obrađeno {res.get('tokens')} od "
                     f"{res.get('tokens_all')} tokena, nasumičnim redom, pa je i dio pošten uzorak.")
    gr = []
    for key, name in (("mc", "Tržišna vrijednost"), ("likvidnost", "Likvidnost poola"), ("drzanje", "Koliko novčanik drži")):
        for g in (res.get("groups") or {}).get(key) or []:
            gr.append(_row(f"{name}: {g['naziv']}", g, size))
    short = {"app": "dokazan dvaput", "top": f"prvih {TOP_N}", "jednom": "dokazan jednom", "likvidnost": "pool 15k+"}
    full = [_row(f"{short[x['rule']]} · {x['delay']} s · {EXIT_HR[x['exit']]}", x, size) for x in res.get("grid") or []]
    # 25.11.: the verdict is recomputed from the rows (also for a result stored before the price check), so it never
    # rests on a row whose numbers cannot be real
    return {"ts": res["ts"], "presuda": verdict(res) if res.get("grid") else res.get("verdict"), "redovi": rows, "skupine": gr, "mreza": full,
            "razlika": gap_lines(res.get("gap")), "napomene": notes,
            "svjezina": freshness_lines(res.get("svjezina"), now), "pristranosti": res.get("biases") or [],
            "dana": res.get("days"), "dana_izvan": res.get("hold_days"), "ulog_sol": res.get("size_sol"),
            "demo_izlaz": EXIT_HR.get(res.get("demo_exit") or PRIMARY[2])}


def dumps(d):
    return json.dumps(d, ensure_ascii=False, default=str)
