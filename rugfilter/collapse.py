"""Rug / collapse after the fact: a token that has already been rugged (its pool pulled, or a crash with the dev or
a top holder selling, or the rug filter rating it high risk) must not be offered to anyone any more, whatever the
rug filter said before.

The rug filter (rugfilter/check.py) judges a token *before* entry from its mechanics and wallets. This module
judges what *happened*: we compare the newest market cap and liquidity with the highest the bot has seen for that
token in the last `WINDOW_H` hours (hype scans and the 2-minute pulse).

11.11. (Jure: "rugan" meant only "70 %+ under the peak"; X (CccS…y1eU), labelled rugan, was later at $387k, +155 %
from the call), then 11.11. evening the owner's rule as he finally wrote it ("Prag 'SOL strana -50 %' na x*y=k poolu
hvata i čisti dump (pad cijene 75 % → SOL -50 %). Rug je izvučena likvidnost, pa mjeri višak"). In a constant-product
pool the SOL side is y = L * sqrt(p): a price move alone changes it by sqrt(p_end / p_start). So (sol_v2, judge_v2):
  expected SOL ratio = sqrt(price_end / price_start), actual SOL ratio = SOL_end / SOL_start;
  RUGGED when actual / expected <= EXCESS_RUG (0.5: half the SOL left beyond what the price explains; the quotient
    is L_end / L_start), the start being the first snapshot, or the first one after liquidity was added or the pool
    migrated (L up more than LP_ADD between two snapshots, or a different pool), OR
  the price fell PRICE_CRASH (90 %) or more and the SOL side SOL_CRASH (90 %) or more (a total collapse: XTO, FOTF,
    GTA, HERO, where the price ratio is ~0 and the quotient says nothing), OR
  it crashed (DROP, 70 %+ under the peak) AND the dev or a top holder is selling, or the rug filter rates it high
    risk (rug_evidence: rug.db's newest report VISOK RIZIK / ODBAČEN on anything but thin liquidity, "dev je
    prodao" / "dev je prebacio"; range.db's transfer holders net-selling, rangedca/holders).
Everything else that fell 70 %+ is a "dump nakon pumpe" (kind "dump"): not a block, only a P modifier x 0.7 (ui/kandidati,
proposals/build, fast/decide through trade/edge.modifiers(dump=...)). A non-CP pool (concentrated liquidity, a bonding
curve; is_cp) is judged the same way and the reason says "ne-CP pool".
Where the numbers come from (pool_drops, Track): the hype scan's token_pulse (liq_sol = DexScreener liquidity.quote,
price_native, pool, dex; hype/pulse.record), compared only within the newest pool; for older rows and tokens without a
pulse, liquidity_usd / 2 / the day's SOL price (market.db) with mcap / SOL price as the price, marked as an estimate
("sol_measured" False, "procjena iz USD"); with only peak / now numbers (judge without `pool`) the peak is the start.
Until the owner's switch rug_labels_v2_ok (rugfilter/labels) a token blocks when ANY version says rug: usd (11.11.
noon, judge_usd), pool_v1 (PR #140: L 50 %+ under its peak, judge_pool_v1) or sol_v2; "kinds" carries all three.
check() returns only the rug, so every caller that blocked on it keeps blocking; assess() returns the rug or the dump.
Nothing stored is rewritten: the check is recomputed on every look. rugfilter/archive keeps its own cleanup rule
(judge_legacy, unchanged); its stored kinds are read through the same versions (archive.kinds, rugfilter/relabel next
to the old labels).

If a collapsed token later climbs back above `RECOVER` of its peak it is shown again (the check is recomputed on
every look, nothing is stored).
"""
import bisect
import collections
import json
import math
import os
import sqlite3
import time

WINDOW_H = 24
DROP = 0.70          # market cap at least 70% below the peak seen in WINDOW_H -> collapsed (a dump; a rug with evidence)
LIQ_DROP = 0.60      # judge_legacy (rugfilter/archive's cleanup): liquidity at least 60% below its peak ...
LIQ_PRICE_DROP = 0.50  # ... together with market cap at least 50% below its peak (liquidity pulled)
LIQ_RUG = 0.50       # pool_v1 (PR #140): a rug when the pool invariant L fell this much from its peak
EXCESS_RUG = 0.50    # sol_v2 (11.11. evening): a rug when actual SOL ratio / expected (sqrt of the price ratio) <= this
PRICE_CRASH = 0.90   # sol_v2: ... or the price this much from the peak
SOL_CRASH = 0.90     # ... together with the SOL side this much
LP_ADD = 0.20        # L up more than this between two snapshots: liquidity added / a migration, the start moves there
RECOVER = 0.50       # recomputed each time; above half of the peak it is no longer collapsed
MIN_PEAK_MCAP = 5000  # below this nothing meaningful to compare
DUMP = "dump nakon pumpe"
RUG_DB = None        # rug.db (None: ui/data.RUG_DB); the offline tests pass their own
MARKET_DB = None     # market.db (daily SOL/USD for L from USD numbers); None: DATA_DIR/market.db
SOL_MINT = "So11111111111111111111111111111111111111112"
FRESH_S = 900        # the SOL-side series counts as "now" when its newest row is this close to the newest snapshot
EVIDENCE_TTL_S = 60
_EVIDENCE = {}


def _k(x):
    return f"${x / 1000:,.1f}k"


def is_cp(dex):
    """True: a constant-product pool (PumpSwap, Raydium AMM v4 / CPMM, Meteora DYN, FluxBeam); False: concentrated
    liquidity (Meteora DLMM / DAMM v2, Raydium CLMM, Orca whirlpool) or a bonding curve, where L is not constant;
    None: unknown (treated as CP: almost every bonded token we see is on PumpSwap). dex: "dexId" or
    "dexId/label,label" as pair_pool stores it."""
    if not dex:
        return None
    d = str(dex).lower()
    dex_id, _, labels = d.partition("/")
    labs = {x.strip() for x in labels.split(",") if x.strip()}
    if dex_id == "orca" or "dlmm" in dex_id or "clmm" in dex_id or labs & NON_CP_LABELS:
        return False
    if dex_id in CURVES:
        return False
    if dex_id in CP_DEXES or labs & {"cpmm", "amm", "dyn", "amm v4"}:
        return True
    return None


NON_CP_LABELS = {"clmm", "dlmm", "wp", "whirlpool", "dyn2", "damm v2", "dammv2", "dbc", "concentrated"}
CURVES = {"pumpfun", "launchlab", "moonshot", "boop", "believe"}
CP_DEXES = {"pumpswap", "raydium", "meteora", "fluxbeam", "pumpfun-amm"}


def _f(x):
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if v == v else None


def pair_pool(p, sol_usd=None):
    """{"liq_sol", "price_native", "pool", "dex"} of a DexScreener pair: the SOL side is liquidity.quote when the quote
    token is SOL / WSOL (price_native = priceNative, in SOL), else liquidity.usd / 2 / SOL price (price_usd / SOL price;
    None without sol_usd). dex = dexId plus its labels ("raydium/CLMM")."""
    p = p or {}
    liq = p.get("liquidity") or {}
    q = p.get("quoteToken") or {}
    sol_quote = q.get("address") == SOL_MINT or str(q.get("symbol") or "").upper() in ("SOL", "WSOL")
    if sol_quote:
        ls, px = _f(liq.get("quote")), _f(p.get("priceNative"))
    elif sol_usd and sol_usd > 0:
        usd, pu = _f(liq.get("usd")), _f(p.get("priceUsd"))
        ls = usd / 2 / sol_usd if usd else None
        px = pu / sol_usd if pu else None
    else:
        ls = px = None
    labels = [str(x) for x in (p.get("labels") or []) if x]
    dex = (p.get("dexId") or "") + ("/" + ",".join(labels) if labels else "")
    return {"liq_sol": ls if ls and ls > 0 else None, "price_native": px if px and px > 0 else None,
            "pool": p.get("pairAddress"), "dex": dex or None}


def approx_pool(peak_mcap, now_mcap, peak_liq, now_liq):
    """pool dict from peak / now numbers only (judge called without a series): the peak stands in for the start
    snapshot, the SOL side ~ the USD liquidity / 2 (SOL/USD taken as steady, an estimate), so the actual SOL ratio is
    now_liq / peak_liq, the expected one sqrt(now_mcap / peak_mcap) and their quotient L_now / L_peak."""
    out = {"ratio": None, "actual": None, "expected": None, "l_drop": None, "sol_drop": None, "sol_drop_peak": None,
           "sol_first": None, "sol_last": None, "sol_low": None, "sol_peak": None, "reset": False, "measured": False,
           "cp": None, "src": "vrhovi", "empty": False}
    if not peak_liq or now_liq is None:
        return out
    actual = now_liq / peak_liq
    out.update(actual=actual, sol_drop=1 - actual, sol_drop_peak=1 - actual)
    if now_liq <= 0:
        out.update(ratio=0.0, l_drop=1.0, empty=True)
    elif now_mcap and now_mcap > 0 and peak_mcap and peak_mcap > 0:
        exp = math.sqrt(now_mcap / peak_mcap)
        out.update(expected=exp, ratio=actual / exp, l_drop=1 - actual / exp)
    return out


def _pct(x):
    return f"{x:.0%}" if x is not None else "?"


def _sol(x):
    return "?" if x is None else (f"{x:,.1f}" if x < 1000 else f"{x:,.0f}")


def _nonc(pool):
    return f"ne-CP pool {pool.get('dex')}" if pool.get("dex") else "ne-CP pool"


def judge_v2(drop, pool, evidence=None):
    """(kind, why) under the owner's rule of 11.11. evening (sol_v2): why "višak" = more SOL left the pool than the
    price explains: actual SOL ratio (SOL_end / SOL_start) / expected (sqrt(price_end / price_start)) <= EXCESS_RUG,
    i.e. L_end / L_start <= 0.5, the start being the first snapshot or the first after an LP add / a migration;
    "90/90" = the price PRICE_CRASH and the SOL side SOL_CRASH or more down; "dokaz" = 70 %+ down with the dev / a top
    holder selling or a high rug risk; else a 70 %+ fall is ("dump", None) and anything less (None, None). An empty
    pool (liquidity 0) counts only with a real fall."""
    ratio, sd, sdp = pool.get("ratio"), pool.get("sol_drop"), pool.get("sol_drop_peak")
    if ratio is not None and ratio <= EXCESS_RUG and (not pool.get("empty") or drop >= 1 - RECOVER):
        return "rug", "višak"
    if drop >= PRICE_CRASH and max(sd or 0, sdp or 0) >= SOL_CRASH:
        return "rug", "90/90"
    if drop >= DROP:
        return ("rug", "dokaz") if evidence else ("dump", None)
    return None, None


def judge_pool_v1(drop, pool, evidence=None):
    """The 11.11. afternoon rule (PR #140, pool_v1): the pool invariant L 50 %+ down from its PEAK (CP; no price
    condition), for a non-CP pool the SOL side from its peak with the price half down; kept for the stricter label
    until the owner's switch (rugfilter/labels) and for the relabel's comparison. "rug" | "dump" | None."""
    l_drop, sdp, cp = pool.get("l_drop"), pool.get("sol_drop_peak"), pool.get("cp")
    if cp is False:
        pulled = sdp is not None and sdp >= LIQ_RUG and drop >= 1 - RECOVER
    else:
        pulled = l_drop is not None and l_drop >= LIQ_RUG and (not pool.get("empty") or drop >= 1 - RECOVER)
    if pulled:
        return "rug"
    if drop >= DROP:
        return "rug" if evidence else "dump"
    return None


def sol_line(pool):
    """"SOL strana -61 % (85.0 → 32.9 SOL), očekivano 0,39 po cijeni, stvarni / očekivani 1,00" (Croatian)."""
    a, e, r = pool.get("actual"), pool.get("expected"), pool.get("ratio")
    if a is None:
        return "SOL strana nepoznata"
    if pool.get("src") == "vrhovi":   # only peak / now USD numbers: no SOL amounts to show
        head = f"SOL strana {a - 1:+.0%} (procjena iz USD likvidnosti, vrh → sada)"
    else:
        head = (f"SOL strana {a - 1:+.0%} ({_sol(pool.get('sol_first'))} → {_sol(pool.get('sol_last'))} SOL"
                + ("" if pool.get("measured") else ", procjena iz USD") + ")")
    tail = (f", očekivano {e:.2f} po cijeni, stvarni / očekivani {r:.2f}".replace(".", ",")
            if e is not None and r is not None else "")
    if pool.get("reset"):
        tail += ", od snimke nakon dodavanja likvidnosti / migracije"
    if pool.get("cp") is False:
        tail += f", {_nonc(pool)}"
    return head + tail


def judge(peak_mcap, now_mcap, peak_liq=None, now_liq=None, evidence=None, pool=None, strict=None):
    """None, or {"kind", "kinds": {"usd", "pool_v1", "sol_v2"}, "rule", "why", "drop", "liq_drop", "ratio", "actual",
    "expected", "l_drop", "sol_drop", "sol_drop_peak", "sol_first", "sol_last", "sol_low", "sol_measured", "reset", "cp",
    "dex", "basis", "sol_rule", "text"}. kind is what blocks: until the owner's switch rug_labels_v2_ok
    (rugfilter/labels) the STRICTER of the three versions (a rug if any says rug), then sol_v2 alone. pool:
    pool_drops() of the token's series; without it the start is the peak and the SOL side the USD liquidity / 2
    (approx_pool, an estimate). evidence: the Croatian line of the dev / a top holder selling or the rug filter's high
    risk (rug_evidence). Plain Croatian text for the dashboard."""
    if not peak_mcap or peak_mcap < MIN_PEAK_MCAP or now_mcap is None or now_mcap < 0:
        return None
    from rugfilter import labels
    drop = 1 - now_mcap / peak_mcap
    liq_drop = (1 - (now_liq or 0) / peak_liq) if peak_liq and now_liq is not None else None
    pool = pool or approx_pool(peak_mcap, now_mcap, peak_liq, now_liq)
    v2, why = judge_v2(drop, pool, evidence)
    kinds = {"usd": (judge_usd(peak_mcap, now_mcap, peak_liq, now_liq, evidence) or {}).get("kind"),
             "pool_v1": judge_pool_v1(drop, pool, evidence), "sol_v2": v2}
    strict = labels.strict() if strict is None else strict
    kind = labels.effective(kinds, strict)
    if kind is None:
        return None

    def r3(k):
        return None if pool.get(k) is None else round(pool[k], 3)
    out = {"kind": kind, "kinds": kinds, "rule": "stroža" if strict else "sol_v2", "why": why, "drop": round(drop, 3),
           "liq_drop": None if liq_drop is None else round(liq_drop, 3), "ratio": r3("ratio"), "actual": r3("actual"),
           "expected": r3("expected"), "l_drop": r3("l_drop"), "sol_drop": r3("sol_drop"),
           "sol_drop_peak": r3("sol_drop_peak"), "sol_first": pool.get("sol_first"), "sol_last": pool.get("sol_last"),
           "sol_low": pool.get("sol_low"), "sol_measured": bool(pool.get("measured")), "reset": bool(pool.get("reset")),
           "cp": pool.get("cp"), "dex": pool.get("dex"), "basis": pool.get("src"), "sol_rule": v2,
           # 11.11. hotfix (#141): "old" when only an older version (usd / pool_v1) makes it a rug
           "strict": "old" if kind == "rug" and v2 != "rug" else None}
    span = f"({_k(peak_mcap)} → {_k(now_mcap)})"
    sl = sol_line(pool)
    if kind == "rug":
        if v2 == "rug" and why == "višak":
            text = f"izvučena likvidnost: {sl}; pad {drop:.0%} od vrha {span}"
        elif v2 == "rug" and why == "90/90":
            text = (f"srušio se {drop:.0%} od vrha {span} i SOL strana "
                    f"{_pct(max(pool.get('sol_drop') or 0, pool.get('sol_drop_peak') or 0))} manja (90/90); {sl}")
        elif v2 == "rug":
            text = f"srušio se {drop:.0%} od vrha {span}; {evidence}"
        else:   # only an older version says rug: the stricter label holds until the owner confirms the relabel
            old = [v for v in ("usd", "pool_v1") if kinds.get(v) == "rug"]
            text = (f"stroža oznaka do potvrde novih ({', '.join(old)}): pad {drop:.0%} od vrha {span}, likvidnost "
                    f"{_pct(liq_drop)} manja, {sl}; po novom pravilu {v2 or 'ništa'}")
        return {**out, "text": text}
    return {**out, "text": f"{DUMP}: pao {drop:.0%} od vrha {span}, {sl}, bez prodaje deva i visokog rug rizika"}


def judge_usd(peak_mcap, now_mcap, peak_liq=None, now_liq=None, evidence=None):
    """The rule of 11.11. noon (USD liquidity more than 50 % down = rug): the OLD label (usd). Until the owner's switch
    rug_labels_v2_ok it is one of the three versions of the stricter label (judge) and the label statistics use
    (rugfilter/labels.for_stats); rugfilter/relabel compares with it."""
    if not peak_mcap or peak_mcap < MIN_PEAK_MCAP or now_mcap is None or now_mcap < 0:
        return None
    drop = 1 - now_mcap / peak_mcap
    liq_drop = (1 - (now_liq or 0) / peak_liq) if peak_liq and now_liq is not None else None
    if drop < 1 - RECOVER:
        return None
    pulled = liq_drop is not None and liq_drop > LIQ_RUG
    if not pulled and drop < DROP:
        return None
    out = {"drop": round(drop, 3), "liq_drop": None if liq_drop is None else round(liq_drop, 3)}
    fell = f"srušio se {drop:.0%} od vrha ({_k(peak_mcap)} → {_k(now_mcap)})"
    if pulled:
        text = (f"{fell}, likvidnost {liq_drop:.0%} manja" if drop >= DROP
                else f"izvučena likvidnost ({liq_drop:.0%} manje) i pad {drop:.0%} od vrha")
        return {"kind": "rug", **out, "text": text}
    if evidence:
        return {"kind": "rug", **out, "text": f"{fell}; {evidence}"}
    if liq_drop is None:
        liq = "likvidnost nepoznata"
    elif liq_drop > 0:
        liq = f"likvidnost {liq_drop:.0%} manja"
    else:
        liq = "likvidnost drži"
    return {"kind": "dump", **out, "text": f"{DUMP}: pao {drop:.0%} od vrha ({_k(peak_mcap)} → {_k(now_mcap)}), {liq}, "
                                         "bez prodaje deva i visokog rug rizika"}


def judge_legacy(peak_mcap, now_mcap, peak_liq=None, now_liq=None):
    """The rule before 11.11. (70 %+ under the peak, or 60 %+ less liquidity with a 50 %+ fall), kept ONLY for
    rugfilter/archive's hourly cleanup, so what it deletes from hype.db does not change with the label."""
    if not peak_mcap or peak_mcap < MIN_PEAK_MCAP or now_mcap is None or now_mcap < 0:
        return None
    drop = 1 - now_mcap / peak_mcap
    liq_drop = (1 - (now_liq or 0) / peak_liq) if peak_liq and now_liq is not None else None
    if drop < 1 - RECOVER:
        return None
    if drop >= DROP:
        text = f"srušio se {drop:.0%} od vrha (${peak_mcap / 1000:,.1f}k → ${now_mcap / 1000:,.1f}k)"
    elif liq_drop is not None and liq_drop >= LIQ_DROP and drop >= LIQ_PRICE_DROP:
        text = f"izvučena likvidnost ({liq_drop:.0%} manje) i pad {drop:.0%} od vrha"
    else:
        return None
    if liq_drop is not None and liq_drop >= LIQ_DROP and drop >= DROP:
        text += f", likvidnost {liq_drop:.0%} manja"
    return {"drop": round(drop, 3), "liq_drop": None if liq_drop is None else round(liq_drop, 3), "text": text}


def peaks(db_path, tokens, hours=WINDOW_H, now=None):
    """token -> [peak_mcap, peak_liq, last_mcap, last_liq, last_ts, series] from hype_signals + token_pulse in hype.db
    (series: the pool state pool_drops() reads; token_pulse's SOL side when those columns are there)."""
    tokens = list(tokens)
    if not tokens or not os.path.exists(db_path):
        return {}
    since = int((now or time.time()) - hours * 3600)
    out = {}
    try:
        con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=10)
    except sqlite3.Error:
        return {}
    try:
        for i in range(0, len(tokens), 400):
            part = tokens[i:i + 400]
            ph = ",".join("?" * len(part))
            for table, extras in (("hype_signals", ("",)), ("token_pulse", (", liq_sol, price_native, pool, dex", ""))):
                for extra in extras:   # an older token_pulse without the SOL columns: the plain read
                    try:
                        rows = con.execute(f"SELECT token, ts, mcap, liquidity{extra} FROM {table} WHERE ts >= ? "
                                           f"AND token IN ({ph})", (since, *part)).fetchall()
                    except sqlite3.OperationalError:
                        continue
                    for row in rows:
                        add(out, *row)
                    break
    finally:
        con.close()
    return out


_SOL_DAYS = {"ts": 0.0, "cfg": object(), "days": {}, "keys": [], "memo": {}}


def _load_sol_days():
    path = MARKET_DB
    if path is None:
        try:
            from ops import disk
            path = os.path.join(disk.DATA_DIR, "market.db")
        except Exception:  # noqa: BLE001
            path = ""
    days = {}
    if path and os.path.exists(path) and os.path.getsize(path) > 0:
        try:
            con = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5)
            try:
                days = {int(d): float(u) for d, u in con.execute("SELECT day, usd FROM price WHERE usd > 0")}
            finally:
                con.close()
        except sqlite3.Error:
            days = {}
    _SOL_DAYS.update(ts=time.time(), cfg=MARKET_DB, days=days, keys=sorted(days), memo={})


def sol_usd_at(ts):
    """SOL/USD of ts's UTC day from market.db price (the nearest known day either way); 1.0 without market.db, which
    is fine for L's ratios as long as every point of a token uses the same source. Read once an hour, memo per day
    (peaks() calls it for every row)."""
    if _SOL_DAYS["cfg"] is not MARKET_DB or time.time() - _SOL_DAYS["ts"] > 3600:
        _load_sol_days()
    day = int(ts) // 86400
    v = _SOL_DAYS["memo"].get(day)
    if v is None:
        days = _SOL_DAYS["days"]
        d = day * 86400
        if not days:
            v = 1.0
        elif d in days:
            v = days[d]
        else:
            keys = _SOL_DAYS["keys"]
            i = bisect.bisect_left(keys, d)
            near = [keys[j] for j in (i - 1, i) if 0 <= j < len(keys)]
            v = days[min(near, key=lambda k: abs(k - d))]
        _SOL_DAYS["memo"][day] = v
    return v


class Track:
    """The pool numbers of one token's series, point by point in time order (sol = SOL side, px = price in SOL or a
    proxy proportional to it; L = sol / sqrt(px)): the START snapshot is the first one, or the first after an LP add /
    a migration (L AND the SOL side both up more than LP_ADD between two snapshots: liquidity came in; a crash where
    the price falls faster than the SOL side raises L without any SOL coming in, and must not move the start); from it
    to the newest: the actual SOL ratio, the expected
    one sqrt(px_end / px_start), their quotient (= L_end / L_start), the SOL side's lowest and peak; and L's peak over
    the window for pool_v1. window_s: points older than that before the newest drop out (None: all stay)."""

    def __init__(self, window_s=None):
        self.window_s = window_s
        self.win = collections.deque()      # (ts, sol, px, L, measured)
        self.start = None
        self.prev_L = self.prev_sol = None
        self.reset = False
        self.mx_sol, self.mx_L, self.mn_sol = collections.deque(), collections.deque(), collections.deque()
        self.last = None

    @staticmethod
    def _push(q, ts, v, low=False):
        while q and ((q[-1][1] >= v) if low else (q[-1][1] <= v)):
            q.pop()
        q.append((ts, v))

    @staticmethod
    def _expire(q, ts_min):
        while q and q[0][0] < ts_min:
            q.popleft()

    def push(self, ts, sol, px, measured=False):
        L = sol / math.sqrt(px) if px and px > 0 and sol > 0 else 0.0
        pt = (ts, sol, px, L, measured)
        self.win.append(pt)
        if self.start is None or (self.prev_L and L > self.prev_L * (1 + LP_ADD)
                                  and sol > self.prev_sol * (1 + LP_ADD)):
            if self.start is not None:
                self.reset = True
            self.start = pt
            self.mx_sol.clear()
            self.mn_sol.clear()
        if L > 0:
            self.prev_L, self.prev_sol = L, sol
        if self.window_s is not None:
            lo = ts - self.window_s
            while self.win and self.win[0][0] < lo:
                self.win.popleft()
            if self.start[0] < lo:          # the start fell out of the window: the oldest point in it
                self.start = self.win[0]
            self._expire(self.mx_L, lo)
        self._expire(self.mx_sol, self.start[0])
        self._expire(self.mn_sol, self.start[0])
        self._push(self.mx_sol, ts, sol)
        self._push(self.mn_sol, ts, sol, low=True)
        self._push(self.mx_L, ts, L)
        self.last = pt

    def state(self):
        """The pool dict judge_v2 / judge_pool_v1 read (None before the first point)."""
        if self.last is None:
            return None
        f, z = self.start, self.last
        fS, fp, fL = f[1], f[2], f[3]
        lS, lp, lL = z[1], z[2], z[3]
        pS = self.mx_sol[0][1] if self.mx_sol else lS
        pL = self.mx_L[0][1] if self.mx_L else lL
        actual = lS / fS if fS else None
        expected = math.sqrt(lp / fp) if fp and fp > 0 and lp and lp > 0 else (0.0 if fp and fp > 0 else None)
        ratio = lL / fL if fL and lL else (0.0 if fL and lS <= 0 else None)
        return {"ratio": ratio, "actual": actual, "expected": expected, "sol_first": fS, "sol_last": lS,
                "sol_low": self.mn_sol[0][1] if self.mn_sol else lS, "sol_peak": pS,
                "sol_drop": 1 - actual if actual is not None else None, "sol_drop_peak": 1 - lS / pS if pS else None,
                "l_drop": 1 - lL / pL if pL else None, "measured": bool(f[4] and z[4]), "reset": self.reset,
                "start_ts": f[0], "empty": lS <= 0}


def _series():
    return {"u": [], "z": 0, "s": {}}


def _fold(st, ts, mcap, liq, liq_sol=None, price_native=None, pool=None, dex=None):
    """One snapshot into the pool state (points, sorted when read: the rows come from two tables): u = the SOL side
    estimated from USD (liquidity / 2 / SOL/USD) with the price proxy mcap / SOL/USD; z = the newest ts with liquidity
    0; s = per pool the measured SOL side (DexScreener liquidity.quote) with the price in SOL."""
    if mcap and mcap > 0 and liq is not None:
        if liq > 0:
            sol = sol_usd_at(ts)
            st["u"].append((ts, liq / 2 / sol, mcap / sol))
        else:
            st["z"] = max(st["z"], ts)
    if liq_sol and liq_sol > 0 and price_native and price_native > 0:
        st["s"].setdefault(pool or "?", []).append((ts, liq_sol, price_native, dex))


def add(acc, token, ts, mcap, liq, liq_sol=None, price_native=None, pool=None, dex=None):
    """Fold one observation into acc[token] = [peak_mcap, peak_liq, last_mcap, last_liq, last_ts, series]."""
    r = acc.setdefault(token, [0.0, 0.0, None, None, 0, _series()])
    if len(r) < 6:
        r.append(_series())
    if mcap:
        r[0] = max(r[0], mcap)
    if liq:
        r[1] = max(r[1], liq)
    if ts >= r[4] and mcap:
        r[2], r[3], r[4] = mcap, liq, ts
    _fold(r[5], ts, mcap, liq, liq_sol, price_native, pool, dex)
    return r


def pool_drops(peak_row, live_mcap=None, live_liq=None, now=None):
    """The pool dict (Track.state plus "cp", "dex", "src", "measured") of a peaks() row, None for a row without a
    series: the measured SOL side of the newest pool in token_pulse when that series is as fresh as the newest snapshot
    (FRESH_S; only that pool is compared), else the SOL side estimated from the USD liquidity and the day's SOL price,
    with the live market cap / liquidity folded in as the newest point."""
    if not peak_row or len(peak_row) < 6 or not isinstance(peak_row[5], dict):
        return None
    st = peak_row[5]
    u = list(st["u"])
    z = st["z"]
    now = int(now or time.time())
    if live_mcap and live_mcap > 0 and live_liq is not None:
        if live_liq > 0:
            sol = sol_usd_at(now)
            u.append((now, live_liq / 2 / sol, live_mcap / sol))
        else:
            z = max(z, now)
    newest = max(st["s"].items(), key=lambda kv: max(p[0] for p in kv[1])) if st["s"] else None
    n_ts = max(p[0] for p in newest[1]) if newest else 0
    dex = max(newest[1])[3] if newest else None
    u_ts = max((p[0] for p in u), default=0)
    out = {"cp": is_cp(dex), "dex": dex, "src": None, "measured": False}
    if newest and n_ts >= u_ts - FRESH_S:
        tr = Track()
        for ts, s, px, _d in sorted(newest[1]):
            tr.push(ts, s, px, True)
        out["src"] = "sol"
    elif u:
        tr = Track()
        for ts, s, px in sorted(u):
            tr.push(ts, s, px, False)
        out["src"] = "usd"
    else:
        tr = None
    state = tr.state() if tr else None
    if z > max(u_ts, n_ts):   # the newest snapshot shows an empty pool
        state = dict(state or {"sol_first": None, "measured": False, "reset": False, "sol_peak": None})
        state.update(ratio=0.0, actual=0.0, expected=None, sol_last=0.0, sol_low=0.0, sol_drop=1.0, sol_drop_peak=1.0,
                     l_drop=1.0, empty=True)
        out["src"] = "likvidnost 0"
    if state is None:
        return {**out, "ratio": None, "actual": None, "expected": None, "sol_drop": None, "sol_drop_peak": None,
                "l_drop": None, "empty": False, "reset": False}
    measured = state.pop("measured", False)
    return {**state, **out, "measured": measured}


def assess(peak_row, live_mcap=None, live_liq=None, token=None, evidence=None, strict=None):
    """What BLOCKS (11.11. hotfix #141, Jure: "stara ILI nova = rug -> blokiran"): the rug OR the dump after a pump of a
    peaks() row (judge's dict; kind = the stricter of the versions until the owner's switch rug_labels_v2_ok, "kinds"
    has each), preferring a live market cap / liquidity when given (and counting it into the peak and the pool
    series). token: for a dump the evidence (rug_evidence) is looked up, which can make it a rug; evidence given: used
    as is."""
    if not peak_row:
        return None
    pm, pl, lm, ll = peak_row[:4]
    now_m = live_mcap if live_mcap is not None else lm
    now_l = live_liq if live_liq is not None else ll
    args = (max(pm or 0, now_m or 0), now_m, max(pl or 0, now_l or 0) or None, now_l)
    pool = pool_drops(peak_row, live_mcap, live_liq)
    j = judge(*args, evidence=evidence, pool=pool, strict=strict)
    if j and j["kind"] == "dump" and evidence is None and token:
        ev = rug_evidence(token)
        if ev:
            j = judge(*args, evidence=ev, pool=pool, strict=strict)
    return j


def assess_pool(peak_row, live_mcap=None, live_liq=None, token=None, evidence=None):
    """The new rule alone (sol_v2: the SOL that left beyond what the price explains, 90 / 90, evidence), whatever the
    owner's switch: for the relabel and the comparison, never for a block until he confirms it."""
    return assess(peak_row, live_mcap, live_liq, token, evidence, strict=False)


def check(peak_row, live_mcap=None, live_liq=None, token=None, evidence=None):
    """The RUG of a peaks() row under the owner's rule (judge kind "rug"), or None: no collapse, or only a dump after
    a pump (assess() returns that one). Every caller that blocks on it blocks only a rug."""
    j = assess(peak_row, live_mcap, live_liq, token, evidence)
    return j if j and j["kind"] == "rug" else None


# ---------- the evidence that turns a crash into a rug -----------------------------------------------------------
def _rug_db():
    if RUG_DB:
        return RUG_DB
    try:
        from ui import data
        return data.RUG_DB
    except Exception:  # noqa: BLE001
        return os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "rug.db")


def rug_report(token, path=None):
    """(verdict, score, data dict) of the newest rug.db report of the token, or None (read-only, one row)."""
    p = path or _rug_db()
    if not token or not p or not os.path.exists(p):
        return None
    try:
        con = sqlite3.connect(f"file:{p}?mode=ro", uri=True, timeout=10)
    except sqlite3.Error:
        return None
    try:
        r = con.execute("SELECT verdict, score, data FROM rug_reports WHERE mint=? ORDER BY checked_at DESC LIMIT 1",
                        (token,)).fetchone()
    except sqlite3.Error:
        r = None
    finally:
        con.close()
    if not r:
        return None
    try:
        d = json.loads(r[2]) if isinstance(r[2], str) and r[2] else (r[2] or {})
    except ValueError:
        d = {}
    return r[0], r[1], d if isinstance(d, dict) else {}


MECHANICS = ("mint authority", "freeze authority", "RugCheck ga je označio kao rugan")
DEV_SELLS = ("dev je prodao", "dev je prebacio")


def rug_signals(token, path=None):
    """{"mechanics", "risk", "dev"}: Croatian lines from the rug filter's newest report (each None when not there):
    mechanics = mint / freeze authority or RugCheck "rugged" (hard fails); risk = VISOK RIZIK, or ODBAČEN on anything
    but "likvidnost samo" (rug_risk high); dev = the dev sold or moved his tokens."""
    out = {"mechanics": None, "risk": None, "dev": None}
    rep = rug_report(token, path)
    if not rep:
        return out
    v, sc, d = rep
    hard = [str(h) for h in d.get("hard_fails") or [] if h]
    flags = [str(f) for f in d.get("flags") or [] if f]
    mech = [h for h in hard if h.startswith(MECHANICS)]
    if mech:
        out["mechanics"] = f"rug mehanika: {mech[0]}"
    real_hard = [h for h in hard if not h.startswith("likvidnost samo")]
    if v == "VISOK RIZIK":
        out["risk"] = "rug filter: visok rizik" + (f", ocjena {float(sc):.0f}/100" if sc is not None else "")
    elif v == "ODBAČEN" and real_hard:
        out["risk"] = f"rug filter: odbačen ({real_hard[0]})"
    dev = [x for x in hard + flags if any(w in x for w in DEV_SELLS)]
    if dev:
        out["dev"] = f"dev prodaje ({dev[0]})"
    return out


def _holders_selling(token):
    """rangedca/holders' newest reading (range.db kv hold:<token>, only tokens with an open range round): the holders
    that got the token by transfer net-sold > 2 % of supply in 15 min, within the last day."""
    try:
        from rangedca import data as rdata
        con = rdata.ro()
    except Exception:  # noqa: BLE001
        return None
    if con is None:
        return None
    try:
        st = rdata.kv_get(con, f"hold:{token}") or {}
    except sqlite3.Error:
        st = {}
    finally:
        con.close()
    if st.get("why") and time.time() - (st.get("checked") or 0) <= 86400:
        return f"top holderi prodaju ({st['why']})"
    return None


def rug_evidence(token, now=None):
    """The line that makes a crash a rug (the dev / a top holder selling, or the rug filter's high risk), or None.
    Cached EVIDENCE_TTL_S per token; any read error is no evidence."""
    now = now or time.time()
    hit = _EVIDENCE.get(token)
    if hit and now - hit[0] < EVIDENCE_TTL_S:
        return hit[1]
    try:
        sg = rug_signals(token)
        ev = sg["dev"] or sg["risk"] or _holders_selling(token)
    except Exception:  # noqa: BLE001 - evidence is a reading, never the reason a loop stops
        ev = None
    if len(_EVIDENCE) > 500:
        _EVIDENCE.clear()
    _EVIDENCE[token] = (now, ev)
    return ev
