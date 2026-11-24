"""The explorer: a second DEMO account that buys what the intraday rule refuses, each trade tagged with why
(18.11., owner: "obavezno treba biti što više demo tradeova"; "analitičar Grok bot ... informacije s Twittera,
postovi, hajp").

The rule's demo account opens 10-15 trades a day because its filters refuse most candidates; its caps (30 open, 100 a
day) are never the limit. Loosening the rule would change what the real account buys, so the refused candidates go to
a SEPARATE demo account (USER) instead. A demo trade costs nothing but a DexScreener quote we already fetch, and each
variant answers whether one filter earns its keep:

  sire   the price is in the zone's bottom half (the rule: the bottom 25 %), the bars have stopped falling
  pada   the price is in the rule's bottom 25 %, but the 15m bars are still making lower lows / a lower close
  grok   Grok's fresh X read of the token (veliki/prioritet "grok": verdict kupi, confidence >= GROK_CONF, at most
         GROK_H old) while the rule says no and the price is in the zone's bottom three quarters: his analyst edge
         measured on trades, the only X signal we have while twitterapi has no credit

Everything else is the rule's own: the zone must be valid (never a zone too narrow / too wide / trending / sliding),
never under the zone, never a token with a bad dip reason, a holder block or a static risk
(live.intra_entries skips those before it asks here), live.enter's guards, costs and the "exit would sell at once"
check, the same stop, target and exits (live.manage sells every open row, whoever owns it), 0.1 SOL.

Kept apart from everything that decides money: its own league account, its own caps (live.caps by user), its own
cooldown and rounds; the rule's cooldown ignores its exits (live.intra_entries), gate.demo_proof reads PAPER_USER
only, the hourly "veliki demo" line and the morning report leave it out (report/midcap.vrows). Its result is one line
an hour, "veliki istraživač: ...", per variant next to the rule's own demo trades of the same days.
VEL_ISTRAZIVAC=0 switches it off.

23.11. (vlasnik: "Demo tradanje nikad ne treba prestati ... Ne vrijede ista pravila za demo"): the market gates (the
macro regime risk_off, BTC's free fall) no longer stop it; such an entry stores the gate (veliki_trades.gate, set by
live.enter) and its result is reported apart ("u filtru tržišta"), never in the per-variant numbers that are compared
with the rule.
"""
import os
import time

USER = "autopilot-istrazivac"
SIRE = 0.50
GROK_TOP = 0.75
GROK_CONF = 0.6
GROK_H = 6
DAYS = 7
VARIANTS = {"sire": "donja polovica zone (pravilo traži donjih 25 %)",
            "pada": "u zoni pravila, ali svijeće još padaju",
            "grok": "Grok na X-u kaže kupi, pravilo ne bi ušlo"}


def on():
    return os.environ.get("VEL_ISTRAZIVAC", "1") != "0"


def grok_buy(g, now):
    """True when Grok's stored opinion of the token is a fresh, confident "kupi"."""
    g = g or {}
    try:
        return (str(g.get("verdict") or "").strip().lower() == "kupi" and float(g.get("confidence") or 0) >= GROK_CONF
                and now - float(g.get("ts") or 0) <= GROK_H * 3600)
    except (TypeError, ValueError):
        return False


def variant(px, z, b15, cfg, btc_state=None, grok=None, now=None):
    """The tag of a candidate the rule refused, or None (the rule itself would enter, or nobody should)."""
    from veliki import intra
    c = intra.cfg_of(cfg)
    if btc_state == "slobodan_pad" or not z or not z.get("ok") or not px or px < z["lo"] * (1 - c["below"]):
        return None
    span = z["hi"] - z["lo"]
    in_rule = px <= z["lo"] + c["bottom"] * span
    calm, _why = intra.calm(b15, c)
    if in_rule and calm:
        return None
    if grok_buy(grok, now or time.time()) and px <= z["lo"] + GROK_TOP * span:
        return "grok"
    if in_rule:
        return "pada"
    if calm and px <= z["lo"] + SIRE * span:
        return "sire"
    return None


def try_enter(con, out, held, tok, q, now, sol, z, b15, icfg, btc, pr=None, prioritet=None):
    """Called by live.intra_entries for a candidate its signal refused. Enters the explorer's account when a variant
    applies; the trade's id or None. Never raises (an explorer's error must not cost the rule's pass)."""
    if not on() or (USER, tok) in held:
        return None
    try:
        from veliki import intra, live
        st = (btc or {}).get("state")   # 23.11.: BTC's free fall is a market gate (real money only): not asked
        tag = variant(q[0], z, b15, icfg, None if st == "slobodan_pad" else st,
                      ((pr or {}).get(tok) or {}).get("grok"), now)
        if not tag:
            return None
        last = con.execute("SELECT MAX(closed_ts) FROM veliki_trades WHERE token=? AND user=?", (tok, USER)).fetchone()[0]
        if last and now - last < intra.COOLDOWN_S:
            return None
        n_r = con.execute("SELECT COUNT(*) FROM veliki_trades WHERE user=? AND token=? AND opened_ts>=?",
                          (USER, tok, live._day_start(now))).fetchone()[0]
        if n_r >= intra.MAX_ROUNDS:
            return None
        text, _no, vid = live.enter(con, USER, tok, q, now, sol, z, icfg, live._regime(now), btc, None,
                                    meta=prioritet.meta(tok, pr) if prioritet else None, kind="intra")
        if not vid:
            return None
        con.execute("UPDATE veliki_trades SET varijanta=? WHERE id=?", (tag, vid))
        con.commit()
        held.add((USER, tok))
        if text:
            out.append(text.replace("veliki demo ulaz", f"veliki istraživač ulaz [{tag}]", 1))
        return vid
    except Exception as e:  # noqa: BLE001
        try:
            con.rollback()
        except Exception:  # noqa: BLE001
            pass
        out.append(f"veliki istraživač: ulaz nije uspio ({type(e).__name__}: {str(e)[:120]})")
        return None


def _stat(rows):
    rets = [r[0] for r in rows if r[0] is not None]
    if not rets:
        return {"n": 0, "ev": None, "hit": None, "usd": 0.0}
    return {"n": len(rets), "ev": sum(rets) / len(rets), "hit": sum(1 for x in rets if x > 0) / len(rets),
            "usd": sum(r[1] or 0.0 for r in rows)}


def stats(con, now, days=DAYS):
    """{"open", "today", "by": {variant: {n, ev, hit, usd}}, "rule": the rule's demo intraday trades of the same days}
    (closed trades, real cost)."""
    from trade import settings
    from veliki import live
    t0 = int(now) - days * 86400
    by = {}
    try:   # 23.11.: entries made while a market gate held real money are reported apart (live.PROOF_ROWS)
        con.execute("SELECT gate FROM veliki_trades LIMIT 0")
        pr = live.PROOF_ROWS
    except Exception:  # noqa: BLE001 - an old database: no gated rows
        pr = ""
    for v in VARIANTS:
        by[v] = _stat(con.execute("SELECT ret, pnl_usd FROM veliki_trades WHERE user=? AND varijanta=? AND "
                                  f"status='closed' AND closed_ts>=?{pr}", (USER, v, t0)).fetchall())
    rule = _stat(con.execute("SELECT ret, pnl_usd FROM veliki_trades WHERE user=? AND kind='intra' AND status='closed' "
                             f"AND closed_ts>=?{pr}", (settings.PAPER_USER, t0)).fetchall())
    gated = live.gated_stats(con, USER, t0) if pr else {"n": 0, "ev": None, "usd": 0.0, "open": 0}
    n_open = con.execute("SELECT COUNT(*) FROM veliki_trades WHERE user=? AND status='open'", (USER,)).fetchone()[0]
    n_day = con.execute("SELECT COUNT(*) FROM veliki_trades WHERE user=? AND opened_ts>=?",
                        (USER, live._day_start(now))).fetchone()[0]
    return {"open": n_open, "today": n_day, "by": by, "rule": rule, "days": days, "u_filtru": gated}


def _txt(s):
    if not s["n"]:
        return "još nema zatvorenih"
    return f"n={s['n']}, prosjek {s['ev']:+.1%}, pogodak {s['hit']:.0%}, zbroj {s['usd']:+.2f} $"


def line(con, now):
    """The hour's line: what the explorer opened and how each variant did against the rule's own demo trades."""
    if not on():
        return "veliki istraživač: isključen (VEL_ISTRAZIVAC=0)"
    from veliki import live
    s = stats(con, now)
    parts = "; ".join(f"{v} ({VARIANTS[v]}): {_txt(s['by'][v])}" for v in VARIANTS)
    return (f"veliki istraživač (demo, odbijeni kandidati): danas otvoreno {s['today']}, sada otvorenih {s['open']}; "
            f"zadnjih {s['days']} d po varijanti: {parts}; pravilo (demo, dnevni raspon) u istom razdoblju: "
            f"{_txt(s['rule'])}"
            + (f"; u filtru tržišta (pravi novac bi stajao, izvan usporedbe): {live.gated_text(s['u_filtru'])}"
               if s["u_filtru"]["n"] or s["u_filtru"]["open"] else ""))
