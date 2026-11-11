"""The owner's EV and proof rule, the P / size modifiers and the signal strategies' exit (11.11., the owner's
consolidated correction, rules B, D and E). One module, so every strategy and every gate reads the same numbers.

EV (the same everywhere; fractions of the stake, cost from trade/cost.py):

    EV = P x TP - (1 - P) x SL - cost

  paper              EV > 0 (to collect n)
  live / autotrade   EV >= EV_LIVE_MIN (+3 %) AND the lower bound of the 90 % confidence interval of the measured EV
                     > 0 AND n >= N_MIN (10). The measured EV is the mean of the n closed results, each net of cost;
                     its 90 % interval is mean +- t(0.95, n - 1) x sd / sqrt(n) (Student t, Cornish-Fisher).
  No win-rate rule: ">= 40 % winners" is gone (with TP +15 / SL -10 and ~2-3 % cost break-even is ~50 %, so a 40 %
  rule let losing sources through).

Modifiers (rule B: they change P and the size, they never block):
  run-up >= RUNUP_X (4x) from the first signal   P x 0.7 and size x 0.5, unless X is bursting AND buys >= 60 % of the
                                                 5 min transactions. X bursting: the posts / authors of the last 15 min
                                                 >= 2x their earlier rate. The 24 h average the owner named is not
                                                 stored; the existing measure is scan/xmom's x_momentum_score (organic
                                                 authors of the last 15 min against the 60 min before, log2) >= 1, the
                                                 stricter of the two (a token that pumps already posts more in the last
                                                 hour than its 24 h average). Unknown X or buy share: reduced.
  wash or shill-driven                           P x 0.5 (once, also when both)
  liquidity $15-25k                              the size by slippage (trade/cost.size_sol), no modifier here
Hard blocks (rule B) live where the data is: rug high / honeypot / freeze / dev dump (the rug view), liquidity under
$15k (trade/cost.liq_block), under $30k MC and the bonding curve (CLAUDE.md).

Signal exit (rule E: influencer, group, insider, the fast path and momentum): half at +15 %, trailing 8 % from the
peak, stop -10 %, everything out after 45 min. The influencer's P is measured on the same benchmark (+15 % before
-10 % within 45 min: proposals bench / kol/tpsl horizon 45).
"""
import math

EV_LIVE_MIN = 0.03
N_MIN = 10
Z90 = 1.6449
TP, SL, TRAIL, TIME_MIN, TP_SHARE = 0.15, 0.10, 0.08, 45, 0.5
RUNUP_X = 4.0
RUNUP_P, RUNUP_SIZE = 0.7, 0.5
X_BURST_SCORE = 1.0          # log2(rate of the last 15 min / rate of the hour before) >= 1: twice the rate
BUY_SHARE_MIN = 0.6
WASH_SHILL_P = 0.5
RULE_TEXT = ("EV = P x TP - (1 - P) x SL - cost; paper: EV > 0; live / autotrade: EV >= +3 %, the 90 % interval's lower "
             "bound of the measured EV > 0 and n >= 10; no win-rate rule")


def ev(p, tp, sl, cost):
    """EV per trade (fraction of the stake): p x TP - (1 - p) x SL - cost (sl > 0)."""
    return p * tp - (1 - p) * sl - cost


def break_even(tp, sl, cost):
    return (sl + cost) / (tp + sl) if tp + sl > 0 else 1.0


def t90(df):
    """The two-sided 90 % Student t quantile (Cornish-Fisher; z for df <= 0)."""
    z = Z90
    if not df or df <= 0:
        return z
    return z + (z ** 3 + z) / (4 * df) + (5 * z ** 5 + 16 * z ** 3 + 3 * z) / (96 * df * df)


def ev_stats(returns):
    """{"n", "ev", "sd", "lo90", "hi90"} of closed results (fractions, net of cost); EV None without any."""
    xs = [float(x) for x in returns or () if x is not None]
    n = len(xs)
    if not n:
        return {"n": 0, "ev": None, "sd": None, "lo90": None, "hi90": None}
    m = sum(xs) / n
    if n < 2:
        return {"n": n, "ev": m, "sd": None, "lo90": None, "hi90": None}
    sd = math.sqrt(sum((x - m) ** 2 for x in xs) / (n - 1))
    h = t90(n - 1) * sd / math.sqrt(n)
    return {"n": n, "ev": m, "sd": sd, "lo90": m - h, "hi90": m + h}


def live_proof(returns, n_min=N_MIN, ev_min=EV_LIVE_MIN):
    """(ok, why not in Croatian or None, ev_stats) of the live / autotrade proof on closed results."""
    s = ev_stats(returns)
    if s["n"] < n_min:
        return False, f"zatvorenih {s['n']} od potrebnih {n_min}", s
    if s["ev"] < ev_min - 1e-12:
        return False, f"EV {s['ev'] * 100:+.1f} % po tradeu, treba barem {ev_min * 100:+.0f} %", s
    if s["lo90"] is None or s["lo90"] <= 0:
        lo = s["lo90"] if s["lo90"] is not None else s["ev"]
        return False, f"donja granica 90 % intervala EV-a {lo * 100:+.1f} % nije iznad nule", s
    return True, None, s


def proof_text(s):
    """One line of an ev_stats for the pages."""
    if not s or not s.get("n"):
        return "nema zatvorenih"
    lo = f", 90 % od {s['lo90'] * 100:+.1f} %" if s.get("lo90") is not None else ""
    return f"n={s['n']}, EV {s['ev'] * 100:+.1f} %{lo}".replace(".", ",")


def x_bursting(x_score):
    v = None
    try:
        v = float(x_score) if x_score is not None else None
    except (TypeError, ValueError):
        v = None
    return v is not None and v >= X_BURST_SCORE


def modifiers(runup_x=None, x_score=None, buy_share_5m=None, wash=False, shill=False):
    """{"p_mult", "size_mult", "tags": [{"key", "text"}]} of rule B's modifiers (see the module text)."""
    p, size, tags = 1.0, 1.0, []
    try:
        ru = float(runup_x) if runup_x is not None else None
    except (TypeError, ValueError):
        ru = None
    if ru is not None and ru >= RUNUP_X:
        try:
            bs = float(buy_share_5m) if buy_share_5m is not None else None
        except (TypeError, ValueError):
            bs = None
        if x_bursting(x_score) and bs is not None and bs >= BUY_SHARE_MIN:
            tags.append({"key": "runup", "text": f"već {ru:.1f}× od prvog signala, ali X raste i kupnje {bs:.0%}: "
                                                 "bez umanjenja"})
        else:
            p *= RUNUP_P
            size *= RUNUP_SIZE
            tags.append({"key": "runup", "text": f"već {ru:.1f}× od prvog signala: P × {RUNUP_P:g}, ulog × "
                                                 f"{RUNUP_SIZE:g}"})
    if wash or shill:
        p *= WASH_SHILL_P
        what = " i ".join(w for w, on in (("lažni volumen", wash), ("vođeno shillanjem", shill)) if on)
        tags.append({"key": "wash" if wash else "shill", "text": f"{what}: P × {WASH_SHILL_P:g}"})
    return {"p_mult": p, "size_mult": size, "tags": tags}


def ev_p_mult(e, m, cost, sl=SL):
    """The EV after P x m, for an EV measured without a P (a mean result net of `cost` on the signal exit): the
    implied P = (e + cost + sl) / (tp + sl), so EV' = m x e - (1 - m) x (cost + sl) (TP cancels)."""
    if e is None or m >= 1:
        return e
    return m * e - (1 - m) * (cost + sl)


def signal_exit_levels():
    """The signal strategies' exit (rule E) in proposals/strategies' level format."""
    return {"tp": [{"pct": TP * 100, "share": TP_SHARE}], "sl": {"pct": -SL * 100},
            "trail": {"activate_pct": TP * 100, "trail_pct": TRAIL * 100},
            "time": {"after_min": TIME_MIN, "if_pnl_below_pct": 1000}}
