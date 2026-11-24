"""P, its 90 % interval, the EV and the lag of one live candidate (11.11., Jure: "za svakog živog kandidata odmah
fast_check i procjena EV-a, nikad 'nije izmjeren'"). Pure functions, plus priors_read() for the worker's 10-min read.

The source's sample (sample()): the first of these with n >= N_SRC (10, trade/edge.N_MIN), else the one with the most
outcomes (then P leans on the prior and is labelled PRIOR_LABEL "procjena, n izvora < 10"):
  wallets       fast.db outcomes of THIS source (+15 % before -10 % within 45 min from our decision: the fast exit
                itself), wallets/rang.py copy rank (closed tokens, wins = closed in profit), the Autopilot record
                (closed demo copies of its follow + fast paper trades)
  influencer    proposals.db bench (+15 % before -10 % within 45 min after the call, kind 'call' only), fast.db
                outcomes of this handle, the rang row of the handle (calls), the Autopilot record
  convergence,  fast.db outcomes of the pseudo-source, the fast paper trades of it
  tool
The strategy prior (priors()): per source kind the first pooled rate with n >= BASE_MIN_N (20):
  wallet kinds  fast.db outcomes of the kind, of every wallet kind, rang: every closed token of the PROVEN wallets
                ("sve kupnje dokazanih novčanika"; wins = closed in profit, not the +15/-10 benchmark: Pretpostavka,
                optimistic, used only until fast.db has 20 outcomes), the demo copies of wallet follows (league.db, ret > 0)
  influencer    fast.db outcomes of influencers, proposals.db bench pooled over every caller (+15/-10/45: the same
                benchmark), rang: every call of the proven influencers
  convergence   fast.db outcomes of convergence, of every kind
  tool          fast.db outcomes of the tool's own live picks, of every kind
  else          no edge: (SL + the cost model's fee part) / (TP + SL) = 48 %: an unmeasured kind never looks good
P (shrink, decide.K = 10 pseudo-trades of the prior): P0 = (hits + K x prior) / (n + K), then x the P modifiers (trade/edge
rule B: run-up P x 0.7, wash P x 0.5).
CI: Wilson 90 % (two-sided, z = 1.645) on the shrunk sample (hits + K x prior of n + K), x the same modifiers: a source
with n = 0 carries only the prior's K = 10 pseudo-trades, so its interval is wide on purpose (+-15-25 points of P).
EV = P x TP - (1 - P) x SL - cost (TP +15 %, SL -10 %, cost trade/cost.round_trip of the stake in the pool), and the
interval of P maps straight onto EV (EV is linear in P): EV_lo = EV(P_lo), EV_hi = EV(P_hi).
Lag: price now vs the source's entry (a wallet's own swap price, the call's price p0, else the market cap at the
signal); below it "jeftinije od njega" unless his sale is seen after the buy ("izlazi"); above it "skuplje od njega".
"""
import math

from trade import cost as tcost, edge

TP, SL = edge.TP, edge.SL
K = 10
BASE_MIN_N = 20
N_SRC = edge.N_MIN
Z90 = 1.6449
NO_EDGE = round((SL + tcost.FEE_ROUND_TRIP) / (TP + SL), 4)
PRIOR_LABEL = "procjena, n izvora < 10"
WALLET_KINDS = ("wallet_follow", "insider", "pre_shill", "group", "proven")
LABEL = {"BUY_PAPER": "KUPI (paper)", "BUY_LIVE": "KUPI (live-eligible)", "SKIP": "PRESKOČI",
         "CHECK_FAILED": "provjera nije uspjela"}
STRATEGY = {"wallet": "kupnje praćenih novčanika", "influencer": "pozivi influencera",
            "convergence": "konvergencija izvora", "tool": "živi kandidati alata", "none": "bez prednosti",
            "x_call": "X pozivi koje šalje Grok"}


def group_of(kind):
    """12.11.: an X call Grok sends (x_call) is an influencer's call: the author's caller bench / record is its sample,
    its prior the x_call outcomes first, then the influencers' chain (priors)."""
    if kind in WALLET_KINDS:
        return "wallet"
    if kind == "x_call":
        return "influencer"
    return kind if kind in ("influencer", "convergence", "tool") else "tool"


def label(decision):
    """The owner's words for a stored decision: BUY_PAPER -> "KUPI (paper)", BUY_LIVE -> "KUPI (live-eligible)" (only a
    label: real money still only through run_trade's proof and the owner's tap), SKIP -> "PRESKOČI"."""
    return LABEL.get(decision, decision or "")


def wilson(k, n, z=Z90):
    """(low, high) of the two-sided Wilson interval of k successes in n (k may be fractional: the shrunk sample)."""
    if not n or n <= 0:
        return 0.0, 1.0
    p = max(0.0, min(1.0, k / n))
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return max(0.0, c - h), min(1.0, c + h)


# ---------- the prior ----------------------------------------------------------------------------------------------------

def _hn(x):
    if not x:
        return 0, 0
    if isinstance(x, dict):
        return int(x.get("hits") or x.get("wins") or 0), int(x.get("n") or 0)
    h, n = x
    return int(h or 0), int(n or 0)


def _sum(*xs):
    h = n = 0
    for x in xs:
        a, b = _hn(x)
        h, n = h + a, n + b
    return h, n


def no_edge():
    return {"p": NO_EDGE, "hits": 0, "n": 0, "strategy": STRATEGY["none"],
            "src": f"prior bez prednosti ((SL + 2 %) / (TP + SL) = {NO_EDGE:.0%})"}


def priors(rates=None, pooled=None, kinds=None):
    """{kind: {"p", "hits", "n", "strategy", "src"}} (see the module text). rates: fast.db {kind: (hits, n)}
    (outcomes.base_rates); pooled: {"bench": (hits, n), "rang_wallet": (wins, n), "rang_kol": (wins, n),
    "demo_wallet": (wins, n)}."""
    rates, pooled = rates or {}, pooled or {}
    all_ = _sum(*rates.values())
    wallets = _sum(*(rates.get(k) for k in WALLET_KINDS))
    out = {}
    for kind in kinds or (WALLET_KINDS + ("influencer", "convergence", "tool", "x_call")):
        g = group_of(kind)
        if g == "wallet":
            chain = [(rates.get(kind), f"fast.db ishodi ({kind})", STRATEGY["wallet"]),
                     (wallets, "fast.db ishodi svih praćenih novčanika", STRATEGY["wallet"]),
                     (pooled.get("rang_wallet"), "rang: svi zatvoreni tokeni dokazanih novčanika (dobitni / svi)",
                      "kupnje dokazanih novčanika"),
                     (pooled.get("demo_wallet"), "demo kopije praćenih novčanika (dobitne / zatvorene)",
                      "demo kopije novčanika")]
        elif g == "influencer":
            chain = ([(rates.get("x_call"), "fast.db ishodi (x_call)", STRATEGY["x_call"])] if kind == "x_call" else [])
            chain += [(rates.get("influencer"), "fast.db ishodi (influencer)", STRATEGY["influencer"]),
                     (pooled.get("bench"), "proposals bench: svi pozivi callera, +15 % prije −10 % u 45 min",
                      STRATEGY["influencer"]),
                     (pooled.get("rang_kol"), "rang: svi pozivi dokazanih influencera (dobitni / svi)",
                      "pozivi dokazanih influencera")]
        else:
            chain = [(rates.get(kind), f"fast.db ishodi ({kind})", STRATEGY[g]),
                     (all_, "fast.db ishodi svih izvora", "svi izvori")]
        got = None
        for x, src, strat in chain:
            h, n = _hn(x)
            if n >= BASE_MIN_N:
                got = {"p": round(min(h, n) / n, 4), "hits": min(h, n), "n": n, "strategy": strat,
                       "src": f"{src}: {min(h, n)}/{n}"}
                break
        out[kind] = got or no_edge()
    return out


def prior_for(kind, pri=None, rates=None):
    """The prior of one kind: from priors() when given, else from fast.db rates alone (decide.base_for's rule)."""
    if pri and pri.get(kind):
        return pri[kind]
    if kind == "x_call" and pri and pri.get("influencer") and not (rates or {}).get("x_call"):
        return pri["influencer"]   # 12.11.: priors stored before the kind existed: the influencers' prior
    return priors(rates, None, (kind,))[kind]


def priors_read(con, now, league_db=None, bench_path=None, wallet_db=None):
    """The pooled rates for priors() (each read guarded: a missing database is no data, never an error)."""
    from . import outcomes
    out = {}
    try:
        rates = outcomes.base_rates(con, now)
    except Exception:  # noqa: BLE001
        rates = {}
    try:
        from proposals import store as pstore
        pc = pstore.ro(bench_path)
        if pc is not None:
            try:
                r = pc.execute("SELECT COALESCE(SUM(hits), 0), COALESCE(SUM(n), 0) FROM bench").fetchone()
                out["bench"] = (int(r[0] or 0), int(r[1] or 0))
            finally:
                pc.close()
    except Exception:  # noqa: BLE001
        pass
    try:
        from wallets import rang
        for kind, key in (("wallet", "rang_wallet"), ("kol", "rang_kol")):
            rows = rang.ranked(kind, wallet_db, proven=True)
            out[key] = (sum(int(r.get("wins") or 0) for r in rows), sum(int(r.get("n") or 0) for r in rows))
    except Exception:  # noqa: BLE001
        pass
    try:
        import sqlite3
        from league import store as lstore
        lc = sqlite3.connect(f"file:{league_db or lstore.DB}?mode=ro", uri=True, timeout=5)
        try:
            r = lc.execute("SELECT COALESCE(SUM(t.ret > 0), 0), COUNT(*) FROM trades t JOIN follows f ON f.id = "
                           "t.follow_id WHERE f.kind = 'wallet' AND t.status = 'closed' AND t.ret IS NOT NULL AND "
                           "t.closed_ts >= ?", (int(now) - 30 * 86400,)).fetchone()
            out["demo_wallet"] = (int(r[0] or 0), int(r[1] or 0))
        finally:
            lc.close()
    except Exception:  # noqa: BLE001
        pass
    return priors(rates, out), rates, out


# ---------- the source's sample and the estimate ----------------------------------------------------------------------

def sample(kind, q, src_rate=None):
    """{"hits", "n", "from"} of the source (see the module text). q: fast/sources.quality (its "rang", "bench" and the
    record's hits / n); src_rate: (hits, n) of this source's measured fast.db outcomes."""
    q = q or {}
    rec = (int(q.get("hits") or 0), int(q.get("n") or 0))
    rec_from = q.get("sample") or "zapis praćenja + fast paper"
    rg = q.get("rang") or {}
    rg = (int(rg.get("wins") or 0), int(rg.get("n") or 0)) if rg else None
    bench = q.get("bench") or {}
    bench = (int(bench.get("hits") or 0), int(bench.get("n") or 0)) if bench else None
    own = ("fast.db ishodi izvora (+15 % prije −10 % u 45 min)", src_rate)
    g = group_of(kind)
    if g == "wallet":
        cands = [own, ("rang za kopiranje (dobitni zatvoreni tokeni)", rg), (rec_from, rec)]
    elif g == "influencer":
        cands = [("brzi izlaz callera (+15 % prije −10 % u 45 min, proposals bench)", bench), own,
                 ("rang za kopiranje (pozivi)", rg), (rec_from, rec)]
    else:
        cands = [own, (rec_from, rec)]
    cands = [(f, _hn(x)) for f, x in cands if x]
    for f, (h, n) in cands:
        if n >= N_SRC:
            return {"hits": min(h, n), "n": n, "from": f}
    if not cands:
        return {"hits": 0, "n": 0, "from": "nema zapisa izvora"}
    f, (h, n) = max(cands, key=lambda c: c[1][1])   # max keeps the first of equal n
    return {"hits": min(h, n), "n": n, "from": f}


def estimate(smp, prior, p_mult=1.0, cost=None, tp=TP, sl=SL, k=K):
    """{"p", "p_lo", "p_hi", "p0" (before the modifiers), "hits", "n", "from", "origin" ("source" | "prior: ..."),
    "label" (PRIOR_LABEL under N_SRC, else None), "prior", "ev", "ev_lo", "ev_hi"} (fractions; EV None while the cost
    is unknown)."""
    h, n = int(smp.get("hits") or 0), int(smp.get("n") or 0)
    base = float(prior.get("p") if prior.get("p") is not None else NO_EDGE)
    eh, en = min(h, n) + k * base, n + k
    p0 = eh / en
    lo, hi = wilson(eh, en)
    m = float(p_mult if p_mult is not None else 1.0)
    p, plo, phi = p0 * m, lo * m, hi * m
    out = {"p": round(p, 4), "p_lo": round(plo, 4), "p_hi": round(phi, 4), "p0": round(p0, 4), "p_mult": m,
           "hits": min(h, n), "n": n, "from": smp.get("from"),
           "origin": "source" if n >= N_SRC else f"prior: {prior.get('strategy') or STRATEGY['none']}",
           "label": None if n >= N_SRC else PRIOR_LABEL,
           "prior": {kk: prior.get(kk) for kk in ("p", "hits", "n", "strategy", "src")},
           "ev": None, "ev_lo": None, "ev_hi": None}
    if cost is not None:
        out.update(ev=edge.ev(p, tp, sl, cost), ev_lo=edge.ev(plo, tp, sl, cost), ev_hi=edge.ev(phi, tp, sl, cost))
    return out


def stored(est):
    """The estimate as fast.db keeps it (percent, rounded)."""
    if not est:
        return None

    def pc(x):
        return round(x * 100, 2) if x is not None else None
    return {"p": est["p"], "p_lo": est["p_lo"], "p_hi": est["p_hi"], "p0": est.get("p0"), "p_mult": est.get("p_mult"),
            "hits": est["hits"], "n": est["n"], "from": est.get("from"), "origin": est["origin"], "label": est["label"],
            "prior": est.get("prior"), "ev_pct": pc(est.get("ev")), "ev_lo_pct": pc(est.get("ev_lo")),
            "ev_hi_pct": pc(est.get("ev_hi"))}


# ---------- lag ---------------------------------------------------------------------------------------------------------

def ref_word(kind):
    g = group_of(kind)
    return "njega" if g == "wallet" else "poziva" if g == "influencer" else "signala"


def lag(chase, sold, kind):
    """{"pct", "txt"}: how far the price moved from the source's entry, in plain words (see the module text)."""
    pct = round(chase * 100, 1) if chase is not None else None
    if sold:
        return {"pct": pct, "txt": "izlazi", "sold": True}
    if chase is None:
        return {"pct": None, "txt": f"ulaz {'izvora' if group_of(kind) == 'wallet' else ref_word(kind)} nepoznat",
                "sold": False}
    w = ref_word(kind)
    if chase < -0.01:
        txt = f"jeftinije od {w}"
    elif chase > 0.01:
        txt = f"skuplje od {w}"
    else:
        txt = "isto kao " + {"njega": "on", "poziva": "poziv", "signala": "signal"}[w]
    return {"pct": pct, "txt": txt, "sold": False}


# ---------- text ----------------------------------------------------------------------------------------------------------

def pct(x, nd=1):
    """Percent points -> "+2,1 %" (a real minus sign)."""
    if x is None:
        return "–"
    s = f"{x:+.{nd}f}".replace(".", ",").replace("-", "−")
    return f"{s} %"


def ev_text(e):
    """"EV +2,1 % (90 %: −1,0 do +5,2 %)" of a stored estimate."""
    if not e or e.get("ev_pct") is None:
        return "EV –"
    ci = (f" (90 %: {pct(e.get('ev_lo_pct')).replace(' %', '')} do {pct(e.get('ev_hi_pct'))})"
          if e.get("ev_lo_pct") is not None else "")
    return f"EV {pct(e['ev_pct'])}{ci}"


def p_text(e):
    """"P 58 % (n=3, prior: kupnje praćenih novčanika; procjena, n izvora < 10)" / "P 62 % (n=12, izvor)"."""
    if not e or e.get("p") is None:
        return "P –"
    tail = f"n={int(e.get('n') or 0)}, " + ("izvor" if e.get("origin") == "source" else str(e.get("origin")))
    lab = e.get("n_label") if "n_label" in e else e.get("label")   # a fast/live verdict keeps the decision in "label"
    if lab:
        tail += f"; {lab}"
    return f"P {e['p'] * 100:.0f} % ({tail})"


def lag_text(lg):
    if not lg:
        return ""
    if lg.get("pct") is None:
        return lg.get("txt") or ""
    return f"{pct(lg['pct'])} od ulaza: {lg.get('txt')}"
