"""The RISK-OFF EXCEPTION of the midcap daily range for real money (23.11., vlasnik u chatu: "Ok, kreni da najviše dvije
pozicije mogu biti otvorene, ali ako se zatvore, otvori dvije nove. Dakle, želim puno tradeova sa uključenim 4% fijem
kojeg plaćamo za tradeove. Tako da pazite kad se zatvara da bi profit postojao.").

Owner switch trade/settings.RISKOFF_SWITCH ("pravi_novac_risk_off"), default off, "uživo" only by his confirmed tap on
the Autopilot page (set_flag tap=True; no code turns it on). Off: veliki/live behaves exactly as before (in risk_off the
real account takes no new entry). On, the real account may enter the daily-range rule (veliki/intra, kind "intra",
never the 7-day rule, never the learned rule's twin) while ALL of:
  gate     the macro regime risk_off is the ONLY market gate holding real money (never BTC's free fall)
  BTC      known, not in a free fall, state normalno / dno_se_potvrduje, change over 4 h >= -1 % (unknown = no entry)
  sector   the Solana meme sector's market cap 24 h change of veliki/makro's newest snapshot >= 0 %, the snapshot at
           most 3 h old (unknown or stale = no entry)
  account  the pause of 19.11. ended (his tap does it), no kill switch, the global automatic caps (trade/executor
           auto_hard: the day's loss), the wallet's value not under its floor (1 SOL) when a fresh snapshot knows it,
           veliki/gate.real_refusal None (pravi_novac_veliki on; his tap turns it on)
  entry    every check of a real midcap entry in veliki/live.enter unchanged (the veliki list, MC >= 15M $, liquidity
           >= $500k, the token-quality guards, the cost cap 6 %, the gate's caps: 5 open, 20 buys, day loss 0.3 SOL,
           the per-token pause and rounds), PLUS at most MAX_OPEN (2) open real midcap positions (every open real
           veliki row counts), 0.1 SOL, and the rule's target at least +min_neto (3 %) NET after the round trip's
           cost taken at least `trosak` (4 %; the measured / modelled cost when higher)
Such a position (veliki_trades.gate_info = TAG, the league source "veliki: [risk-off iznimka] ...") keeps its real
cost (rt = the floored cost) for every number: its break-even is a +min_izlaz (+1 %) NET lock (armed at +5 % net, as
the owner's rule), every VOLUNTARY profit exit (trailing, BTC / macro profit protection) closes it only at >= +1 % net
after that cost, the macro risk_off exits never close it (the regime it was bought in), and every stop (the wide -20 %
stop, BTC's tight stop, the break-even lock, BTC's free-fall cut, a rug, a liquidity collapse, a bad reason, a volume
collapse) acts exactly as before. The target closes it.

trade/config.json "pravi_novac_risk_off" may only make it STRICTER: {"trosak": >= 0.04, "min_neto": >= 0.03,
"min_izlaz": >= 0.01}. Every function here never raises: an unreadable input refuses real money.
"""
import os
import sqlite3
import time

TAG = "risk-off iznimka"
MAX_OPEN = 2
SIZE_SOL = 0.1
CONFIG_KEY = "pravi_novac_risk_off"
DEFAULTS = {"trosak": 0.04, "min_neto": 0.03, "min_izlaz": 0.01}
BTC_4H_MIN = -0.01
BTC_OK = ("normalno", "dno_se_potvrduje")
SECTOR_MIN = 0.0
SNAP_MAX_S = 3 * 3600
VOLUNTARY = frozenset({"trail", "btc_zastita", "makro_zastita", "time"})
_S = {"on": None, "why": None, "ref": {}, "held": {}}


def cfg(conf=None):
    """DEFAULTS, raised (never lowered) by trade/config.json CONFIG_KEY."""
    out = dict(DEFAULTS)
    try:
        if conf is None:
            from trade import executor
            conf = executor.load_config()
        own = (conf or {}).get(CONFIG_KEY)
        for k in DEFAULTS:
            if isinstance(own, dict) and own.get(k) is not None:
                out[k] = max(DEFAULTS[k], float(own[k]))
    except Exception:  # noqa: BLE001 - unreadable config: the defaults
        pass
    return out


def switch_on(con=None):
    try:
        from trade import settings
        return settings.flag(settings.RISKOFF_SWITCH, con) == "live"
    except Exception:  # noqa: BLE001 - unreadable = off
        return False


def is_row(r):
    """True for a REAL position opened under the exception."""
    try:
        from trade import settings
        return (r or {}).get("user") == settings.LEAGUE_USER and (r or {}).get("gate_info") == TAG
    except Exception:  # noqa: BLE001
        return False


def rt_of(rt):
    """The round trip's cost of an exception trade: the measured / modelled one, at least cfg trosak (4 %)."""
    return max(float(rt or 0.0), cfg()["trosak"])


def net_at(entry, px, rt):
    return px / entry * (1 - rt) - 1


def lock_px(entry, rt):
    """The break-even of an exception trade: the price where the rest nets +min_izlaz (+1 %) after rt."""
    return entry * (1 + cfg()["min_izlaz"]) / (1 - min(max(rt, 0.0), 0.5))


def be_at():
    """The owner's "+5 % net -> stop to the entry" measured from lock_px: still armed at +5 % net."""
    from veliki import rule
    return (1 + (rule.OWNER_EXIT.get("be_at") or 0.05)) / (1 + cfg()["min_izlaz"]) - 1


# ---------- the mode ------------------------------------------------------------------------------------------------

def btc_refusal(btc, now):
    """Why BTC does not allow the exception now (Croatian), or None."""
    b = btc or {}
    if not b.get("known"):
        return "BTC cijena nepoznata"
    st = b.get("state")
    if b.get("crash") or st == "slobodan_pad":
        return "BTC slobodan pad"
    if st not in BTC_OK:
        return f"BTC stanje {st or '?'}"
    try:
        ch = b["crash_obj"].chg(now, 4)
    except Exception:  # noqa: BLE001
        ch = None
    if ch is None:
        return "BTC promjena 4 h nepoznata"
    if ch < BTC_4H_MIN:
        return f"BTC pada ({ch:+.1%} u 4 h, prag {BTC_4H_MIN:+.0%})"
    return None


def sector_chg(snap, now):
    """(the Solana meme sector's 24 h market cap change in %, why unknown or None)."""
    if not snap:
        return None, "makro snimka nepoznata"
    age = now - (snap.get("ts") or 0)
    if age > SNAP_MAX_S:
        return None, f"makro snimka stara {age / 3600:.1f} h"
    ch = (snap.get("sector") or {}).get("mcap_chg24")
    try:
        return (float(ch), None) if ch is not None else (None, "Solana meme sektor nepoznat")
    except (TypeError, ValueError):
        return None, "Solana meme sektor nepoznat"


def sector_refusal(snap, now):
    ch, why = sector_chg(snap, now)
    if why:
        return why
    if ch < SECTOR_MIN:
        return f"Solana meme sektor {ch:+.1f} % u 24 h"
    return None


def account_refusal(now, path=None):
    """What on the real account holds an automatic buy now (trade.db read-only), or None: the pause of 19.11., the
    kill switch, the global automatic caps (the day's loss), the wallet's value under its floor (a fresh snapshot)."""
    try:
        from trade import executor, settings
        if os.path.exists(executor.STOP_FILE):
            return "kill switch (trade/STOP)"
        db = path or settings.DB
        if not os.path.exists(db):
            return "trade.db nečitljiv"
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=5)
        try:
            if settings.pauza(con):
                return "pauza od 19.11. nije skinuta (uključuje samo vlasnik svojim prekidačem)"
            hard = executor.auto_hard(con, SIZE_SOL, now, veliki=True)
            if hard:
                return hard[0][1]
            val, src = executor.equity_value(con, now)
            fl = executor.equity_floor(executor.load_config())
            if val is not None and val < fl:
                return f"vrijednost novčanika {val:.3f} SOL ispod poda {fl:g} SOL ({src})"
        finally:
            con.close()
    except Exception as e:  # noqa: BLE001 - an unreadable account is no real money
        return f"stanje računa nečitljivo ({type(e).__name__})"
    return None


def mode_refusal(gates, btc, snap, now, path=None):
    """None when the exception holds now (the real account may enter the daily range in risk_off), else why."""
    try:
        from veliki import gate, live
        if not switch_on():
            return f"prekidač {CONFIG_KEY} isključen"
        if live.GATE_BTC in (gates or []):
            return "BTC slobodan pad"
        if list(gates or []) != [live.GATE_MAKRO]:
            return "filtar tržišta: " + ("; ".join(gates or []) or "nijedan")
        why = btc_refusal(btc, now) or sector_refusal(snap, now) or account_refusal(now, path)
        if why:
            return why
        return gate.real_refusal(now=now)
    except Exception as e:  # noqa: BLE001
        return f"iznimka nečitljiva ({type(e).__name__})"


def set_mode(on, why=None, info=None):
    """tick(): the exception active now ({"btc", "sector", "ts"}) or not (why)."""
    _S["on"] = dict(info or {}) if on else None
    _S["why"] = None if on else why


def active():
    return _S.get("on") is not None


def open_refusal(con):
    """At most MAX_OPEN open REAL midcap positions (every open real veliki row, whatever opened it)."""
    from trade import settings
    n = con.execute("SELECT COUNT(*) FROM veliki_trades WHERE user=? AND status='open'",
                    (settings.LEAGUE_USER,)).fetchone()[0]
    if n >= MAX_OPEN:
        return f"risk-off iznimka: već {n} otvorene prave midcap pozicije (najviše {MAX_OPEN})"
    return None


def target_refusal(entry, tp, rt):
    """The rule's target must net at least min_neto (+3 %) after the floored cost."""
    c = cfg()
    net = net_at(entry, tp, rt)
    if net < c["min_neto"]:
        return (f"risk-off iznimka: cilj {tp / entry - 1:+.1%} daje {net:+.1%} neto uz trošak {rt:.1%} "
                f"(treba barem {c['min_neto']:+.0%})")
    return None


def exit_ok(r, pos, price, reason, now=None):
    """False when a VOLUNTARY profit exit of an exception position would close it under +min_izlaz net after its
    cost (the position is then held to its target or its stop); every other exit True."""
    if reason not in VOLUNTARY or not is_row(r):
        return True
    from veliki import rule
    got = rule.blend_ret(pos, price, r.get("rt") or rt_of(0.0), {"exit_slip": 0.0}, r.get("lots") or 1)
    if got >= cfg()["min_izlaz"]:
        return True
    k = (r.get("id"), reason)
    t = now or time.time()
    if t - _S["held"].get(k, 0) > 3600:
        _S["held"][k] = t
        refused(f"izlaz {reason} zadržan ispod +1 % neto")
    return False


# ---------- reporting -------------------------------------------------------------------------------------------------

def refused(why):
    import re
    k = re.sub(r"[-+−]?\d[\d.,]*", "N", (why or "?").split(" (")[0])[:80]
    _S["ref"][k] = _S["ref"].get(k, 0) + 1


def stats(con, since=0, sol=None):
    """{n, ev, sol, open} of the exception's real rows (closed since `since`)."""
    from trade import settings
    try:
        rows = con.execute("SELECT ret, pnl_usd FROM veliki_trades WHERE user=? AND gate_info=? AND status='closed' "
                           "AND ret IS NOT NULL AND closed_ts>=?", (settings.LEAGUE_USER, TAG, int(since))).fetchall()
        n_open = con.execute("SELECT COUNT(*) FROM veliki_trades WHERE user=? AND gate_info=? AND status='open'",
                             (settings.LEAGUE_USER, TAG)).fetchone()[0]
    except Exception:  # noqa: BLE001 - an old database: nothing
        return {"n": 0, "ev": None, "sol": 0.0, "open": 0}
    px = sol or 150.0
    rets = [x[0] for x in rows]
    return {"n": len(rets), "ev": (sum(rets) / len(rets)) if rets else None,
            "sol": sum((x[1] or 0.0) for x in rows) / px, "open": n_open}


def stats_text(s):
    ev = f"{s['ev']:+.1%}" if s.get("ev") is not None else "—"
    return f"n={s['n']}, prosjek {ev} neto, zbroj {s['sol']:+.3f} SOL, otvoreno {s['open']}"


def _since_text(con=None):
    try:
        import datetime as dt
        from zoneinfo import ZoneInfo
        from trade import settings
        own = con is None
        c = con or sqlite3.connect(f"file:{settings.DB}?mode=ro", uri=True, timeout=5)
        try:
            st = settings.flag_state(c)[settings.RISKOFF_SWITCH]
        finally:
            if own:
                c.close()
        if not st["since"]:
            return "?"
        return dt.datetime.fromtimestamp(st["since"], ZoneInfo("Europe/Zagreb")).strftime("%d.%m. %H:%M")
    except Exception:  # noqa: BLE001
        return "?"


def line(lcon, now=None, tcon=None):
    """The hour's line (None while the switch is off and nothing was refused): the mode, BTC, the sector, the open
    count and the refusals of the hour (counted per reason; reset)."""
    ref = _S["ref"]
    _S["ref"] = {}
    on = _S.get("on")
    if on is None and not switch_on(tcon) and not ref:
        return None
    try:
        from trade import settings
        n_open = lcon.execute("SELECT COUNT(*) FROM veliki_trades WHERE user=? AND status='open'",
                              (settings.LEAGUE_USER,)).fetchone()[0]
    except Exception:  # noqa: BLE001
        n_open = 0
    if on is not None:
        sc = on.get("sector")
        head = (f"veliki risk-off iznimka: UKLJUČENA (vlasnik {_since_text(tcon)}): pravi novac smije do {MAX_OPEN} "
                f"pozicije po {SIZE_SOL:g} SOL; BTC {on.get('btc') or '?'}, meme sektor "
                f"{('%+.1f %%' % sc) if sc is not None else '?'} 24 h; otvoreno {n_open} od {MAX_OPEN}")
    elif switch_on(tcon):
        head = f"veliki risk-off iznimka: prekidač uključen, sada ne kupuje ({_S.get('why') or 'izvan risk-offa'})"
    else:
        head = "veliki risk-off iznimka: isključena"
    if ref:
        head += "; odbijeno zadnji sat: " + "; ".join(f"{k} {v}" for k, v in sorted(ref.items(), key=lambda kv: -kv[1]))
    return head
