"""Konsenzus izvora: the research (15.11.2026., vlasnik: "hitno pronađi profitabilnu strategiju kombiniranjem
profitabilnih novčanika i influencera ... imamo puno influencera i novčanika u Telegram kanalima u bazi").

Read-only on every database, no API call, no cost. Honest by construction: the answer may be "nothing proven yet".

STREAM (izlazi/data.build, kinds kol + wallet): one entry per (source, token), the source's first call / buy of it:
  x       an X influencer's call (minute.db call_path; bots, shillers and "w:" pseudo-calls out)
  tg      a Telegram channel's call (the same table, handle "tg:<channel>")
  wallet  a followed / proven / copyable wallet's first buy (wallets.db wallet_trades, hype.db chain_trades, events.db
          wallet_buy; izlazi/data.candidate_wallets: league follows, wallets/dokazani, the top of wallets/rang)
Each: the signal time (sig_ts), our measured entry delay (lag: league copy_log per source / kind, else fast.db
latency, never under 30 s), market cap and pool liquidity at the signal when known, the price path after our entry
(1-minute bars up to 24 h from minute.db / gt_candles / live_trades / snapshots, izlazi/data.assemble), the round-trip
cost of 0.1 SOL at that pool (never under 2 %), the rug flag time. The live system's hard rules are applied there
(kol/zadnjih5._rules: MC >= 30k, pool >= 15k when known, not on the pump.fun curve, not in the rug archive at the
signal).

CAVEAT (look-ahead in the wallet universe): the wallets are TODAY's followed / proven / top-ranked lists (izlazi/data
.candidate_wallets), chosen partly by how they did, also in the holdout days, so wallet results are optimistic; the
X / Telegram universe is every measured call (no such bias). gate.real_refusal therefore also asks the demo account's
own result (DEMO_N closed konsenzus trades with EV > 0) when the holdout is WALLET_SHARE_DEMO+ wallet entries.

GROUPS: correlated sources count as ONE source (the ZAPZEKE lesson): the newest corr.db snapshot's KOL clusters (with
their linked wallets) and wallet owner groups are merged (union-find); every other source is its own group. A group's
event on a token = its first member's signal on it; later members' signals on the same token are echoes.

ROLLING SCORE of a group, only from what was known BEFORE the moment it is used: the net results of its earlier events
under the scoring exit E (known once E's 45-min time stop has passed after the entry), recency-weighted (half-life
HALF_LIFE_D days) and shrunk toward the kind's own rolling mean with PRIOR_K pseudo-trades (no data: PRIOR_EMPTY, a
loss). Selection is refreshed once a day at 03:00 Zagreb (kol/zadnjih5.refresh_cut), exactly like the live selection,
which is the research run's own output (after a deploy and nightly).

CANDIDATES (a small grid on purpose, every one is a multiple test):
  S1  top-K groups by score (K 10 / 30), any kind, n >= MIN_N, score > 0
  S2  consensus: 2+ independent groups on one token within W minutes (W 30 / 120 among groups with score > 0; W 30
      among any groups, the plain confluence); the entry is the second group's own entry
  S3  cross-type: a selected wallet group AND a selected X / Telegram group within 60 minutes
  S4  Telegram only: top-K channels (K 10)
  svi every first signal per token (the baseline, never chosen)
Each with three exits (izlazi/sim, pessimistic fills: a stop at min(level, previous close) minus the stop slippage
max(measured, SLIP_STOP_MIN 8 %: the live exits' ~8 % under the level), a take profit / time stop minus 1 %):
  E  the signal exit: half at +15 % (price), the rest break-even + trailing 8 %, stop -10 %, 45 min
  B  "brzi profit": half at +12 % net of cost, break-even + trailing 10 %, stop -20 %, no time stop (24 h)
  W  wider stop: half at +20 % net, break-even + trailing 15 %, stop -30 %, 6 h
One position per token per strategy, the first entry only.

EVALUATION: the event days are split once: the earlier 75 % choose each family's parameters and exit (the best train
EV among configurations with >= MIN_TRAIN_N trades), the last 25 % (holdout) is evaluated ONCE for the chosen one.
The winners are ranked by the holdout EV shrunk toward 0 by n / (n + RANK_K), so a few lucky trades never rank first.
Per candidate: n, trades a day, EV per trade net, the 90 % interval by a day-block bootstrap (one position per token,
so a day is the block), hit rate, worst trade, max drawdown (stakes), rug share. The families' winners are ranked by
holdout EV (shrunk, rank_score); the best runs in demo. Real money needs gate.PROOF on the holdout: n >= 30, EV >= +3 %, the day-block
interval's low > 0 AND trade/edge.live_proof on the same results.

Run: `python3 run_konsenzus.py once` (start.sh, after a deploy, low priority under the heavy lock, a time budget),
`night` (01-06 Zagreb, once a day). Output: konsenzus.db, output/konsenzus.md, log lines "konsenzus: ...".
"""
import datetime as dt
import json
import os
import random
import time
from zoneinfo import ZoneInfo

from izlazi import sim

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VERSION = 1
TZ = "Europe/Zagreb"
PREFIX = "konsenzus: "
DAYS = 30
MAX_ENTRIES = int(os.environ.get("KONSENZUS_MAX_ENTRIES", "20000"))
BUILD_BUDGET_S = int(os.environ.get("KONSENZUS_BUILD_BUDGET_S", "720"))
BUDGET_S = {"once": int(os.environ.get("KONSENZUS_BUDGET_S", "1200")), "night": 2400}
SHARE = {"kol": 0.55, "wallet": 0.45}
HOLDOUT_SHARE = 0.25
MIN_N = 5               # known results before a group can be selected
MIN_TRAIN_N = 10        # a configuration needs this many train trades to be chosen
PRIOR_K = 10.0          # pseudo-trades of the kind's mean in a group's score
PRIOR_EMPTY = -0.03     # the prior with nothing known yet (a loss: costs are real)
HALF_LIFE_D = 14.0
SLIP_STOP_MIN = 0.08    # the live exits filled ~8 % under the level (critic 15.11.); never assume better
SLIP_MKT = sim.SLIP_MKT
BOOT_B = 1000
SEED = 15
LIQ_MIN = 15_000
MIN_MCAP = 30_000
SCORE_EXIT = "E"
KINDS_HR = {"x": "X influencer", "tg": "Telegram kanal", "wallet": "novčanik", "mix": "mješovita grupa"}

# (sl %, grace, tp1 %, share, trail %, tmax min, mirror); tp_gross: tp1 is a price move (E), else net of the cost
EXITS = {
    "E": {"name": "signalni izlaz", "p": sim.Params(10, 0, 15, 0.5, 8, 45, 0), "tp_gross": True,
          "words": "pola na +15 %, ostatak BE + trailing 8 %, stop −10 %, 45 min"},
    "B": {"name": "brzi profit", "p": sim.Params(20, 0, 12, 0.5, 10, 1440, 0), "tp_gross": False,
          "words": "pola na +12 % neto, ostatak BE + trailing 10 %, stop −20 %, bez vremenskog izlaza"},
    "W": {"name": "širi stop", "p": sim.Params(30, 0, 20, 0.5, 15, 360, 0), "tp_gross": False,
          "words": "pola na +20 % neto, ostatak BE + trailing 15 %, stop −30 %, 6 h"},
}
FAMILIES = {
    "S1": {"name": "top-K izvora", "grid": ({"k": 10}, {"k": 30})},
    "S2": {"name": "konsenzus 2+ neovisna izvora", "grid": ({"w": 30, "sel": "dobri"}, {"w": 120, "sel": "dobri"},
                                                            {"w": 30, "sel": "svi"})},
    "S3": {"name": "novčanik + X/Telegram", "grid": ({"w": 60},)},
    "S4": {"name": "samo Telegram top kanali", "grid": ({"k": 10},)},
}
BASELINE = "svi"


# ---------- small helpers (pure) ----------------------------------------------------------------------------------

def day_of(ts):
    return dt.datetime.fromtimestamp(int(ts), ZoneInfo(TZ)).strftime("%Y-%m-%d")


def refresh_cut(ts):
    from kol import zadnjih5
    return zadnjih5.refresh_cut(ts)


def kind_of(src, entry_kind):
    if entry_kind == "wallet":
        return "wallet"
    return "tg" if str(src or "").lower().startswith("tg:") else "x"


def norm(src):
    s = str(src or "").strip()
    return s if not s.lower().startswith(("tg:", "@")) and len(s) >= 32 else s.lower().lstrip("@")


def _pc(x):
    return "?" if x is None else f"{x:+.1f}"


def cfg_key(fam, params, ex):
    return fam + ":" + ",".join(f"{k}{v}" for k, v in sorted(params.items())) + ":" + ex


# ---------- groups (correlated sources = one source) ----------------------------------------------------------------

class Groups:
    """Union-find of correlated sources. join(members): these source ids belong together."""

    def __init__(self):
        self.parent = {}
        self._multi = None

    def find(self, a):
        p = self.parent.setdefault(a, a)
        while p != self.parent.setdefault(p, p):
            self.parent[p] = self.parent[self.parent[p]]
            p = self.parent[p]
        self.parent[a] = p
        return p

    def join(self, members):
        ms = [norm(m) for m in members if m]
        for m in ms[1:]:
            a, b = self.find(ms[0]), self.find(m)
            if a != b:
                self.parent[max(a, b)] = min(a, b)
        self._multi = None

    def table(self):
        """{source: group id} of every source in a group of 2+ (singletons are their own group)."""
        if self._multi is None:
            roots = {}
            for k in list(self.parent):
                roots.setdefault(self.find(k), []).append(k)
            self._multi = {m: "g:" + r for r, ms in roots.items() if len(ms) > 1 for m in ms}
        return self._multi

    def of(self, src):
        s = norm(src)
        return self.table().get(s, s)


def load_groups(path=None):
    """(Groups, info) from the newest corr.db snapshot: KOL clusters (+ their linked wallets) and wallet owner groups
    (+ their linked handles). No snapshot: every source alone (info says so)."""
    g = Groups()
    try:
        from corr import store as cstore
        ts, snap, _ai = cstore.latest(path)
    except Exception:  # noqa: BLE001 - corr not readable: singletons
        ts, snap = None, None
    if not snap:
        return g, {"snapshot_ts": None, "clusters": 0, "owner_groups": 0, "note": "nema corr.db snimke: svaki izvor sam"}
    nc = no = 0
    for cl in snap.get("clusters") or []:
        ms = list(cl.get("members") or []) + list(cl.get("wallets") or [])
        if len(ms) > 1:
            g.join(ms)
            nc += 1
    for gr in snap.get("groups") or []:
        ms = list(gr.get("wallets") or []) + list(gr.get("handles") or [])
        if len(ms) > 1:
            g.join(ms)
            no += 1
    return g, {"snapshot_ts": ts, "clusters": nc, "owner_groups": no}


# ---------- exits (pure) --------------------------------------------------------------------------------------------

def exit_result(e, ex, slip_stop):
    """Net result (fraction of the stake) of one entry under exit `ex` (EXITS key)."""
    spec = EXITS[ex]
    p = spec["p"]
    cost = e["cost"]
    if spec["tp_gross"]:   # a price move: izlazi/sim's TP1 is net of the cost, so take the cost back off
        p = p._replace(tp1=max(0.5, p.tp1 - cost * 100))
    return sim.evaluate(sim.unpack(e["arrs"]), p, cost, sell_s=None, rug_s=e.get("rug_s"), slip_stop=slip_stop,
                        slip_mkt=SLIP_MKT)


KNOWN_MIN_S = 70 * 60   # kol/minute measures a call once it is 70 min old: nothing is "known" sooner


def known_at(e, ex=SCORE_EXIT):
    """When the result of entry e under exit ex was known at the latest: its time stop after our entry, never sooner
    than KNOWN_MIN_S (the minute data of a call exists only then)."""
    return int(e["ts"]) + max(KNOWN_MIN_S, int(EXITS[ex]["p"].tmax * 60))


# ---------- events and the rolling score (pure) ----------------------------------------------------------------------

def make_events(entries, groups, slip_stop):
    """[event] in time order: per (group, token) the first signal only (an echo of the same group is not a second
    source). event: {i, src, kind, group, tok, sig_ts, ts (our entry = path start), day, r (E result), known, rug,
    mcap, liq, lag, entry}."""
    first = {}
    for e in sorted(entries, key=lambda e: (e.get("sig_ts") or e["ts"], e["src"])):
        k = kind_of(e["src"], e["kind"])
        grp = groups.of(e["src"]) if groups is not None else norm(e["src"])
        key = (grp, e["tok"])
        if key in first:
            continue
        first[key] = {"src": norm(e["src"]), "kind": k, "group": grp, "tok": e["tok"],
                      "sig_ts": int(e.get("sig_ts") or e["ts"]), "ts": int(e["ts"]), "day": day_of(e["ts"]),
                      "rug": e.get("rug_s") is not None, "mcap": e.get("mcap"), "liq": e.get("liq"),
                      "lag": e.get("lag"), "entry": e, "cut": refresh_cut(e["ts"])}
    evs = sorted(first.values(), key=lambda x: (x["sig_ts"], x["src"]))
    for i, ev in enumerate(evs):
        ev["i"] = i
        ev["r"] = exit_result(ev["entry"], SCORE_EXIT, slip_stop)
        ev["known"] = known_at(ev["entry"])
    return evs


def scores_at(evs, cut, half_life_d=HALF_LIFE_D, k=PRIOR_K):
    """{group: (score, n, kind)} from the results known by `cut` only (no look-ahead): recency-weighted mean of the
    group's E results shrunk toward its kind's mean of everything known by then."""
    per, kind_sum, kind_n = {}, {}, {}
    tau = half_life_d * 86400
    for ev in evs:
        if ev["known"] > cut or ev["ts"] >= cut:
            continue
        w = 0.5 ** ((cut - ev["ts"]) / tau)
        a = per.setdefault(ev["group"], [0.0, 0.0, 0, ev["kind"]])
        a[0] += w * ev["r"]
        a[1] += w
        a[2] += 1
        if a[3] != ev["kind"]:
            a[3] = "mix"
        kind_sum[ev["kind"]] = kind_sum.get(ev["kind"], 0.0) + ev["r"]
        kind_n[ev["kind"]] = kind_n.get(ev["kind"], 0) + 1
    out = {}
    for g, (swr, sw, n, kd) in per.items():
        if kd == "mix":
            pr = sum(kind_sum.values()) / max(1, sum(kind_n.values()))
        else:
            pr = kind_sum[kd] / kind_n[kd] if kind_n.get(kd) else PRIOR_EMPTY
        out[g] = ((swr + k * pr) / (sw + k), n, kd)
    return out


def selection(sc, fam, params):
    """The set of groups the family selects from scores {group: (score, n, kind)}."""
    good = [(s, g) for g, (s, n, kd) in sc.items() if n >= MIN_N and s > 0]
    if fam == "S1":
        return {g for _s, g in sorted(good, reverse=True)[:params["k"]]}
    if fam == "S4":
        return {g for _s, g in sorted(((s, g) for s, g in good if sc[g][2] == "tg"), reverse=True)[:params["k"]]}
    if fam == "S2" and params.get("sel") == "svi":
        return None   # any group
    return {g for _s, g in good}


def pick(evs, fam, params, sel_of):
    """[(event, why)] the strategy enters, in time order, the first entry per token only. sel_of(event) -> the set of
    groups selected at that event's refresh (None = any group)."""
    out, taken = [], set()
    if fam in ("S1", "S4"):
        for ev in evs:
            if ev["tok"] in taken:
                continue
            sel = sel_of(ev)
            if sel and ev["group"] in sel and (fam != "S4" or ev["kind"] == "tg"):
                taken.add(ev["tok"])
                out.append((ev, ev["group"]))
        return out
    w = params["w"] * 60
    seen = {}   # token -> [(sig_ts, group, kind)] of selected signals so far
    for ev in evs:
        if ev["tok"] in taken:
            continue
        sel = sel_of(ev)
        if sel is not None and ev["group"] not in sel:
            continue
        prev = [p for p in seen.get(ev["tok"], ()) if ev["sig_ts"] - p[0] <= w and p[1] != ev["group"]]
        if fam == "S3":
            mine = "wallet" if ev["kind"] == "wallet" else "kol"
            prev = [p for p in prev if ("wallet" if p[2] == "wallet" else "kol") != mine]
        if prev:
            taken.add(ev["tok"])
            out.append((ev, prev[0][1] + " + " + ev["group"]))
        seen.setdefault(ev["tok"], []).append((ev["sig_ts"], ev["group"], ev["kind"]))
    return out


# ---------- numbers (pure) ------------------------------------------------------------------------------------------

def block_ci(trades, b=BOOT_B, seed=SEED, alpha=0.10):
    """(lo, hi) of the mean net result by a day-block bootstrap (days resampled with replacement)."""
    by = {}
    for t in trades:
        by.setdefault(t["day"], []).append(t["net"])
    days = list(by.values())
    if not days:
        return None, None
    if len(days) == 1 and len(days[0]) == 1:
        return days[0][0], days[0][0]
    rnd = random.Random(seed)
    sums = [(sum(xs), len(xs)) for xs in days]
    k = len(sums)
    ms = []
    for _ in range(b):
        s = n = 0
        for _d in range(k):
            a, c = sums[rnd.randrange(k)]
            s += a
            n += c
        ms.append(s / n if n else 0.0)
    ms.sort()
    return ms[int(alpha / 2 * (b - 1))], ms[int((1 - alpha / 2) * (b - 1))]


def stats(trades, span_days):
    """The candidate's numbers on these trades (fractions; *_pct percent)."""
    n = len(trades)
    if not n:
        return {"n": 0, "per_day": 0.0}
    nets = [t["net"] for t in sorted(trades, key=lambda t: t["ts"])]
    lo, hi = block_ci(trades)
    m = sum(nets) / n
    return {"n": n, "per_day": round(n / max(1.0, span_days), 2), "ev_pct": round(m * 100, 2),
            "ci_lo_pct": round(lo * 100, 2) if lo is not None else None,
            "ci_hi_pct": round(hi * 100, 2) if hi is not None else None,
            "hit": round(sum(1 for x in nets if x > 0) / n, 3), "worst_pct": round(min(nets) * 100, 1),
            "best_pct": round(max(nets) * 100, 1), "max_dd": round(sim.max_dd(nets), 2),
            "rug_share": round(sum(1 for t in trades if t.get("rug")) / n, 3),
            "wallet_share": round(sum(1 for t in trades if t.get("kind") == "wallet") / n, 3),
            "cost_pct": round(sum(t["cost"] for t in trades) / n * 100, 2), "days": len({t["day"] for t in trades})}


RANK_K = 10   # the holdout EV is shrunk toward 0 with this many pseudo-trades for the ranking (3 lucky trades never win)


def rank_score(h):
    """The ranking key of a holdout: EV x n / (n + RANK_K) (percent); -inf without trades."""
    n = (h or {}).get("n") or 0
    if not n or h.get("ev_pct") is None:
        return -1e9
    return h["ev_pct"] * n / (n + RANK_K)


def split_days(evs, share=HOLDOUT_SHARE):
    """(train days, holdout days): the event days in order, the last `share` of them held out."""
    days = sorted({ev["day"] for ev in evs})
    if len(days) < 2:
        return days, []
    k = max(1, int(round(len(days) * share)))
    return days[:-k], days[-k:]


def walk(evs, slip_stop, log=print, deadline=None):
    """Every candidate on the events: {"configs": [...], "chosen": {fam: ...}, "ranking": [...], "days": ...}. The
    holdout of a configuration is computed only for each family's chosen one (the rest stay unopened)."""
    train_days, hold_days = split_days(evs)
    hold = set(hold_days)
    cuts = {}
    for ev in evs:
        cuts.setdefault(ev["cut"], None)
    sc_by_cut = {c: scores_at(evs, c) for c in sorted(cuts)}
    sel_cache = {}

    def sel_for(fam, params):
        key = (fam, tuple(sorted(params.items())))
        if key not in sel_cache:
            sel_cache[key] = {c: selection(sc, fam, params) for c, sc in sc_by_cut.items()}
        tab = sel_cache[key]
        return lambda ev: tab[ev["cut"]]

    res_cache = {}

    def result(ev, ex):
        k = (ev["i"], ex)
        if k not in res_cache:
            res_cache[k] = ev["r"] if ex == SCORE_EXIT else exit_result(ev["entry"], ex, slip_stop)
        return res_cache[k]

    def trades_of(picks, ex, part):
        out = []
        for ev, why in picks:
            if (ev["day"] in hold) != (part == "holdout"):
                continue
            out.append({"ts": ev["ts"], "day": ev["day"], "net": result(ev, ex), "cost": ev["entry"]["cost"],
                        "rug": ev["rug"], "tok": ev["tok"], "why": why, "kind": ev["kind"]})
        return out

    configs = []
    fams = list(FAMILIES.items()) + [(BASELINE, {"name": "svi signali (osnova)", "grid": ({},)})]
    for fam, spec in fams:
        for params in spec["grid"]:
            if deadline and time.monotonic() > deadline:
                log(PREFIX + "vremenski budžet istekao usred mreže kandidata")
                break
            if fam == BASELINE:
                taken, picks = set(), []
                for ev in evs:
                    if ev["tok"] not in taken:
                        taken.add(ev["tok"])
                        picks.append((ev, ev["group"]))
            else:
                picks = pick(evs, fam, params, sel_for(fam, params))
            for ex in EXITS:
                tr = trades_of(picks, ex, "train")
                configs.append({"key": cfg_key(fam, params, ex), "family": fam, "params": dict(params), "exit": ex,
                                "train": stats(tr, len(train_days)), "_picks": picks})
    chosen = {}
    for fam in FAMILIES:
        cs = [c for c in configs if c["family"] == fam]
        ok = [c for c in cs if c["train"]["n"] >= MIN_TRAIN_N]
        if ok:
            c = max(ok, key=lambda c: (c["train"]["ev_pct"], c["train"]["n"]))
            why = f"najbolji EV na treningu među {len(ok)} konfiguracija s {MIN_TRAIN_N}+ tradeova"
        elif cs:
            c = max(cs, key=lambda c: (c["train"]["n"], c["train"].get("ev_pct") or -1e9))
            why = f"nijedna konfiguracija nema {MIN_TRAIN_N}+ tradeova na treningu: uzeta ona s najviše"
        else:
            continue
        c["holdout"] = stats(trades_of(c["_picks"], c["exit"], "holdout"), len(hold_days))
        c["holdout_rets"] = [t["net"] for t in trades_of(c["_picks"], c["exit"], "holdout")]
        c["chosen_why"] = why
        chosen[fam] = c
    for c in configs:   # the baseline's holdout too: what "everything" did in the same days (a reference, never chosen)
        if c["family"] == BASELINE:
            c["holdout"] = stats(trades_of(c["_picks"], c["exit"], "holdout"), len(hold_days))
    ranking = sorted(chosen.values(), key=lambda c: (c["holdout"]["n"] > 0, rank_score(c["holdout"])), reverse=True)
    for c in configs:
        c.pop("_picks", None)
    return {"configs": configs, "chosen": chosen, "ranking": [c["key"] for c in ranking],
            "days": {"train": train_days, "holdout": hold_days}, "cuts": len(sc_by_cut),
            "scores_now": None}


# ---------- the live selection (as of now) ---------------------------------------------------------------------------

def live_selection(evs, fam, params, groups, now, top_sources=400):
    """What the live entries use until the next run: {"groups": {group: {score, n, kind}}, "members": {source:
    group}} of the family's selection with the results known now; for an any-group family, the group table of every
    source seen (members) and no group list."""
    sc = scores_at(evs, now + 1)
    sel = selection(sc, fam, params)
    members = {}
    for ev in evs:
        if sel is None or ev["group"] in sel:
            members[ev["src"]] = ev["group"]
    if groups is not None:
        for s, g in groups.table().items():
            if sel is None or g in sel:
                members.setdefault(s, g)
    if sel is None and len(members) > 20000:
        members = dict(list(members.items())[-20000:])
    gsel = {} if sel is None else {g: {"score_pct": round(sc[g][0] * 100, 2), "n": sc[g][1], "kind": sc[g][2]}
                                   for g in sel}
    top = sorted(gsel.items(), key=lambda kv: -kv[1]["score_pct"])[:top_sources]
    return {"groups": dict(top) if sel is not None else None, "members": members, "any": sel is None}


# ---------- the run ---------------------------------------------------------------------------------------------------

def slip_of(meta):
    s = ((meta or {}).get("costs") or {}).get("slip_stop_pct")
    return max(SLIP_STOP_MIN, (s or 0) / 100)


def research(entries, meta=None, groups=None, ginfo=None, now=None, log=print, deadline=None):
    """The whole analysis on prepared entries (izlazi/data.build shape). Returns (data, best)."""
    from konsenzus import gate
    now = int(now or time.time())
    slip = slip_of(meta)
    evs = make_events(entries, groups, slip)
    w = walk(evs, slip, log, deadline)
    best = None
    for key in w["ranking"]:
        c = next(x for x in w["chosen"].values() if x["key"] == key)
        best = c
        break
    data = {"version": VERSION, "ts": now, "slip_stop_pct": round(slip * 100, 1), "events": len(evs),
            "events_by_kind": {}, "groups": ginfo or {}, "days": w["days"], "cuts": w["cuts"],
            "configs": w["configs"], "ranking": w["ranking"],
            "chosen": {f: {k: v for k, v in c.items() if k != "holdout_rets"} for f, c in w["chosen"].items()},
            "assumptions": {"exits": {k: v["words"] for k, v in EXITS.items()}, "min_n": MIN_N, "prior_k": PRIOR_K,
                            "half_life_d": HALF_LIFE_D, "holdout_share": HOLDOUT_SHARE, "min_train_n": MIN_TRAIN_N,
                            "slip_mkt_pct": SLIP_MKT * 100, "proof": gate.PROOF},
            "meta": {k: v for k, v in (meta or {}).items() if k not in ("wallet_own",)}}
    for ev in evs:
        data["events_by_kind"][ev["kind"]] = data["events_by_kind"].get(ev["kind"], 0) + 1
    out_best = None
    if best is not None:
        ok, why = gate.holdout_proof(best["holdout_rets"], best["holdout"])
        sel = live_selection(evs, best["family"], best["params"], groups, now)
        out_best = {"key": best["key"], "family": best["family"], "family_name": FAMILIES[best["family"]]["name"],
                    "params": best["params"], "exit": best["exit"], "exit_words": EXITS[best["exit"]]["words"],
                    "exit_params": sim.as_dict(EXITS[best["exit"]]["p"]), "tp_gross": EXITS[best["exit"]]["tp_gross"],
                    "train": best["train"], "holdout": best["holdout"], "proof_ok": bool(ok), "proof_why": why,
                    "chosen_why": best.get("chosen_why"), "ts": now, "selection": sel,
                    "n_sources": len(sel["members"]), "n_groups": (len(sel["groups"]) if sel["groups"] is not None
                                                                   else None)}
        data["best"] = {k: v for k, v in out_best.items() if k != "selection"}
    return data, out_best


def lines(data):
    """The compact log lines: one per family winner, then the decision."""
    out = []
    for key in data.get("ranking") or []:
        c = next((x for x in data["chosen"].values() if x["key"] == key), None)
        if not c:
            continue
        h = c.get("holdout") or {}
        t = c.get("train") or {}
        if h.get("n"):
            out.append(f"{PREFIX}{key} holdout n={h['n']}, EV {_pc(h.get('ev_pct'))} %, CI [{_pc(h.get('ci_lo_pct'))}; "
                       f"{_pc(h.get('ci_hi_pct'))}], trades/dan {h.get('per_day', 0):.1f} (trening n={t.get('n')}, EV "
                       f"{_pc(t.get('ev_pct'))} %)")
        else:
            out.append(f"{PREFIX}{key} holdout n=0 (trening n={t.get('n')}, EV {_pc(t.get('ev_pct'))} %)")
    for c in data.get("configs") or []:
        if c["family"] == BASELINE and c["exit"] == SCORE_EXIT:
            h = c.get("holdout") or {}
            if h.get("n"):
                out.append(f"{PREFIX}osnova (svi signali, izlaz E) holdout n={h['n']}, EV {_pc(h.get('ev_pct'))} %, CI "
                           f"[{_pc(h.get('ci_lo_pct'))}; {_pc(h.get('ci_hi_pct'))}]")
    b = data.get("best")
    if b:
        out.append(f"{PREFIX}najbolji kandidat {b['key']} ({b['family_name']}, izlaz {b['exit']}); pravi novac: "
                   + ("dokaz PROŠAO (još treba prekidač pravi_novac_izvori)" if b["proof_ok"] else
                      f"NE ({b['proof_why']}); demo radi"))
    else:
        out.append(f"{PREFIX}nema kandidata (premalo podataka)")
    return out


def markdown(data):
    """output/konsenzus.md: the run in words, Croatian."""
    if not data:
        return "# Konsenzus izvora\n\nJoš nema izračuna.\n"
    ts = dt.datetime.fromtimestamp(data["ts"], ZoneInfo(TZ)).strftime("%d.%m.%Y. %H:%M")
    d = data.get("days") or {}
    L = [f"# Konsenzus izvora ({ts})", "",
         f"Događaja (prvi signal grupe po tokenu): {data.get('events')} · po vrsti: "
         + ", ".join(f"{KINDS_HR.get(k, k)} {v}" for k, v in (data.get("events_by_kind") or {}).items()),
         f"Dani: trening {len(d.get('train') or [])} ({(d.get('train') or ['?'])[0]} – {(d.get('train') or ['?'])[-1]}),"
         f" holdout {len(d.get('holdout') or [])} ({', '.join(d.get('holdout') or []) or '—'})",
         f"Grupe (korelirani izvori = jedan): {json.dumps(data.get('groups') or {}, ensure_ascii=False)}",
         f"Klizanje stopa {data.get('slip_stop_pct')} % (najmanje {SLIP_STOP_MIN * 100:.0f} %), tržišni izlaz "
         f"{SLIP_MKT * 100:.0f} %, trošak round tripa po poolu (najmanje 2 %).", "",
         "## Izabrani po obitelji (rangirano po holdoutu)", "",
         "| kandidat | trening n | trening EV | holdout n | holdout EV | CI90 | trades/dan | pogodak | najgori | max pad | rug |",
         "|---|---|---|---|---|---|---|---|---|---|---|"]
    for key in data.get("ranking") or []:
        c = next((x for x in data["chosen"].values() if x["key"] == key), None)
        if not c:
            continue
        t, h = c.get("train") or {}, c.get("holdout") or {}

        def p(x):
            return "—" if x is None else f"{x:+.1f} %"
        L.append(f"| {key} | {t.get('n', 0)} | {p(t.get('ev_pct'))} | {h.get('n', 0)} | {p(h.get('ev_pct'))} | "
                 f"[{p(h.get('ci_lo_pct'))}; {p(h.get('ci_hi_pct'))}] | {h.get('per_day', 0)} | "
                 f"{h.get('hit', '—')} | {p(h.get('worst_pct'))} | {h.get('max_dd', '—')} | {h.get('rug_share', '—')} |")
    b = data.get("best")
    L += ["", "## Odluka", ""]
    if b:
        L.append(f"Najbolji kandidat: **{b['key']}** ({b['family_name']}), izlaz {b['exit']}: {b['exit_words']}.")
        L.append("Pravi novac: " + ("dokaz na holdoutu PROŠAO; i dalje treba vlasnikov prekidač pravi_novac_izvori."
                                    if b["proof_ok"] else f"ne — {b['proof_why']}. Demo trguje ovaj kandidat."))
        L.append(f"Izvora u živoj selekciji: {b.get('n_sources')}, grupa: {b.get('n_groups')}.")
    else:
        L.append("Nema kandidata: premalo podataka.")
    L += ["", "## Sve konfiguracije (trening; holdout samo za izabrane i osnovu)", "",
          "| konfiguracija | n | EV | CI90 | trades/dan | holdout n | holdout EV |", "|---|---|---|---|---|---|---|"]
    for c in data.get("configs") or []:
        t, h = c.get("train") or {}, c.get("holdout") or {}
        L.append(f"| {c['key']} | {t.get('n', 0)} | {t.get('ev_pct', '—')} | [{t.get('ci_lo_pct', '—')}; "
                 f"{t.get('ci_hi_pct', '—')}] | {t.get('per_day', 0)} | {h.get('n', '—') if h else '—'} | "
                 f"{h.get('ev_pct', '—') if h else '—'} |")
    L += ["", "Pretpostavke: " + json.dumps(data.get("assumptions") or {}, ensure_ascii=False, default=str), ""]
    return "\n".join(L)


def write_md(data, path=None):
    out = path or os.path.join(ROOT, "output", "konsenzus.md")
    try:
        os.makedirs(os.path.dirname(out), exist_ok=True)
        with open(out, "w") as f:
            f.write(markdown(data))
    except OSError:
        pass


def run(now=None, p=None, log=print, mode="once", path=None, entries=None, meta=None, groups=None, ginfo=None):
    """The whole run: stream -> groups -> walk-forward -> konsenzus.db + output/konsenzus.md + log lines."""
    from konsenzus import store
    now = int(now or time.time())
    t0 = time.monotonic()
    deadline = t0 + BUDGET_S.get(mode, BUDGET_S["once"])
    cov = None
    if entries is None:
        from izlazi import data as idata
        log(PREFIX + f"čitam signale (X, Telegram, novčanici) zadnjih {DAYS} dana, budžet {BUILD_BUDGET_S} s")
        entries, cov, meta = idata.build(p, now, log=lambda s: log(PREFIX + s), budget_s=BUILD_BUDGET_S,
                                         max_entries=MAX_ENTRIES, days=DAYS, kinds=("kol", "wallet"), share=SHARE)
    if groups is None:
        groups, ginfo = load_groups()
    log(PREFIX + f"{len(entries)} ulaza s putanjom, grupe: {json.dumps(ginfo or {}, ensure_ascii=False)}")
    data, best = research(entries, meta, groups, ginfo, now, log, deadline)
    data["coverage"] = cov or {}
    data["s"] = round(time.monotonic() - t0, 1)
    data["mode"] = mode
    if not entries:
        log(PREFIX + "nema ulaza s putanjom: prethodni izbor ostaje")
        best = None
    con = store.connect(path)
    try:
        store.save(con, data, best, now)
        store.kv_put(con, "last_day", day_of(now))
        con.commit()
    finally:
        con.close()
    write_md(data)
    for s in lines(data):
        log(s)
    log(PREFIX + f"gotovo za {data['s']:.0f} s")
    return data
