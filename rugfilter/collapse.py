"""Rug / collapse after the fact: a token that has already been rugged (its pool pulled, or a crash with the dev or
a top holder selling, or the rug filter rating it high risk) must not be offered to anyone any more, whatever the
rug filter said before.

The rug filter (rugfilter/check.py) judges a token *before* entry from its mechanics and wallets. This module
judges what *happened*: we compare the newest market cap and liquidity with the highest the bot has seen for that
token in the last `WINDOW_H` hours (hype scans and the 2-minute pulse).

11.11. (Jure: "rugan" meant only "70 %+ under the peak"; X (CccS…y1eU), labelled rugan, was later at $387k, +155 %
from the call): the owner's rule. A token is RUGGED only when
  - its liquidity fell more than LIQ_RUG (50 %) from its peak (the pool pulled), with the market cap at least half
    under its peak, OR
  - it crashed (DROP, 70 %+ under the peak) AND the dev or a top holder is selling, or the rug filter rates it high
    risk (rug_evidence: rug.db's newest report VISOK RIZIK / ODBAČEN on anything but thin liquidity, "dev je
    prodao" / "dev je prebacio"; range.db's transfer holders net-selling, rangedca/holders).
A crash without any of that is a "dump nakon pumpe" (kind "dump"): not a block, only a P modifier x 0.7 where the
old label blocked (ui/kandidati, proposals/build, fast/decide through trade/edge.modifiers(dump=...)).
check() returns only the rug, so every caller that blocked on it keeps blocking, under the new rule; assess()
returns the rug or the dump. Nothing stored is rewritten: the check is recomputed on every look. rugfilter/archive
keeps its own cleanup rule (judge_legacy, unchanged); its stored kinds are read through the new rule (archive.kinds).
Pretpostavka (not measured): in a constant-product pool an organic fall of the price to 15 % takes the USD liquidity
to ~39 % of its peak (sqrt(0.15)), so a plain -85 % dump can also show liquidity "> 50 % lower" and read as a rug.

If a collapsed token later climbs back above `RECOVER` of its peak it is shown again (the check is recomputed on
every look, nothing is stored).
"""
import json
import os
import sqlite3
import time

WINDOW_H = 24
DROP = 0.70          # market cap at least 70% below the peak seen in WINDOW_H -> collapsed (a dump; a rug with evidence)
LIQ_DROP = 0.60      # judge_legacy (rugfilter/archive's cleanup): liquidity at least 60% below its peak ...
LIQ_PRICE_DROP = 0.50  # ... together with market cap at least 50% below its peak (liquidity pulled)
LIQ_RUG = 0.50       # 11.11. owner's rule: a rug when the liquidity fell MORE than this from its peak
RECOVER = 0.50       # recomputed each time; above half of the peak it is no longer collapsed
MIN_PEAK_MCAP = 5000  # below this nothing meaningful to compare
DUMP = "dump nakon pumpe"
RUG_DB = None        # rug.db (None: ui/data.RUG_DB); the offline tests pass their own
EVIDENCE_TTL_S = 60
_EVIDENCE = {}


def _k(x):
    return f"${x / 1000:,.1f}k"


def judge(peak_mcap, now_mcap, peak_liq=None, now_liq=None, evidence=None):
    """None, or {"kind": "rug" | "dump", "drop", "liq_drop", "text"} under the owner's rule of 11.11. (module text).
    evidence: the Croatian line of the dev / a top holder selling or the rug filter's high risk (rug_evidence), which
    turns a crash into a rug. Plain Croatian text for the dashboard."""
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
    """token -> (peak_mcap, peak_liq, last_mcap, last_liq, last_ts) from hype_signals + token_pulse in hype.db."""
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
            for table in ("hype_signals", "token_pulse"):
                try:
                    rows = con.execute(f"SELECT token, ts, mcap, liquidity FROM {table} WHERE ts >= ? AND token IN ({ph})",
                                       (since, *part)).fetchall()
                except sqlite3.OperationalError:
                    continue
                for t, ts, mc, liq in rows:
                    add(out, t, ts, mc, liq)
    finally:
        con.close()
    return out


def add(acc, token, ts, mcap, liq):
    """Fold one observation into acc[token] = [peak_mcap, peak_liq, last_mcap, last_liq, last_ts]."""
    r = acc.setdefault(token, [0.0, 0.0, None, None, 0])
    if mcap:
        r[0] = max(r[0], mcap)
    if liq:
        r[1] = max(r[1], liq)
    if ts >= r[4] and mcap:
        r[2], r[3], r[4] = mcap, liq, ts
    return r


def assess(peak_row, live_mcap=None, live_liq=None, token=None, evidence=None):
    """The rug OR the dump after a pump of a peaks() row (judge's dict), preferring a live market cap / liquidity when
    given (and counting it into the peak). token: for a dump the evidence (rug_evidence) is looked up, which can make
    it a rug; evidence given: used as is."""
    if not peak_row:
        return None
    pm, pl, lm, ll, _ = peak_row
    now_m = live_mcap if live_mcap is not None else lm
    now_l = live_liq if live_liq is not None else ll
    args = (max(pm or 0, now_m or 0), now_m, max(pl or 0, now_l or 0) or None, now_l)
    j = judge(*args, evidence=evidence)
    if j and j["kind"] == "dump" and evidence is None and token:
        ev = rug_evidence(token)
        if ev:
            j = judge(*args, evidence=ev)
    return j


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
