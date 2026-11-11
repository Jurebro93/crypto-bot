"""Missed tokens -> range watching (11.11., Jure: "propušteni tokeni u range praćenje"; flag range_missed G27).

Every token a skip journal labels "propušteno" (skipped, then >= +MIN_PCT (20 %) within 60 min of the skip) goes onto
the range watchlist (rangedca/market.py, table mkt) as source "missed" for TTL_S (72 h): watched, never bought because
of the skip. Read-only from the stores that measure a skip (one query each every EVERY_S, free):
  preskoceni   minute.db skip_path (kol/preskoceni: the Autopilot's buy-side skips and technical failures, the
               "Preskočeno" journal, measured with 1-minute candles for 60 min from the decision): hi60 >= 0.20
  brzi_put     fast.db signals (fast/outcomes): decision SKIP and missed = 1 (max within 60 min >= +20 %)
  prijedlozi   proposals.db (proposals/outcomes): a proposal that expired or was rejected (isteklo / odbijeno) whose
               1 h after-outcome reached max_gain_pct >= 20
Only skips of the last TTL_S are read. A token enters once per label: a row whose skip is not newer than the label
already stored (mkt.missed_ts) changes nothing; a newer skip labelled again renews the 72 h.

The skip's price is never used. On the list a missed token passes market.check like the others, with the owner's
rule B numbers (bonded, MC >= 30k, liquidity >= $15k, volume 1 h >= $10k; a watched one keeps the market list's softer
keep thresholds) and the hard blocks of hard_block() (rug under the 11.11. rule, the rug archive's rugs, honeypot /
mint / freeze / RugCheck "rugged", the rug filter's high risk, the dev or the transfer holders selling). Its range and
entry come only from rangedca/detect (the range computed every 5 min, computed_ts) and rangedca/rules, like every
range. After TTL_S the token falls back to source "market" and stays only while the market filter keeps it (or
another source does).

Money: paper on the demo account while range_missed is paper (rangedca/trade.allowed); the real account only while
range_missed is live AND rangedca/gate.missed_refusal() is None (>= 20 closed demo rounds of source missed passing the
trade/edge live proof). The round keeps its source in range_rounds.levels ("src"), so the EV report and
get_range_candidates show missed vs the other sources apart.
"""
import json
import os
import sqlite3
import time

FLAG = "range_missed"
SRC = "missed"
VIA = "propusteno"
TTL_S = 72 * 3600
MIN_PCT = 20.0
EVERY_S = int(os.environ.get("RANGE_MISSED_EVERY_S", "300"))
HARD_WAIT_S = 6 * 3600        # a hard-blocked missed token is looked at again after this (inside its 72 h)
HOLDERS_FRESH_S = 86400       # rangedca/holders' "transfer holders sold" counts this long
COLS = (("missed_until", "INTEGER"), ("missed_ts", "INTEGER"), ("missed_pct", "REAL"), ("missed_via", "TEXT"))
STORES = ("preskoceni", "brzi_put", "prijedlozi")


def ensure(con):
    """mkt's missed columns (idempotent ALTER on a range.db made before 11.11.)."""
    have = {r[1] for r in con.execute("PRAGMA table_info(mkt)")}
    for name, typ in COLS:
        if name not in have:
            con.execute(f"ALTER TABLE mkt ADD COLUMN {name} {typ}")


def mode():
    try:
        from league import flags
        return flags.mode(FLAG)
    except Exception:  # noqa: BLE001 - unreadable flag: off
        return "off"


def _ro(path):
    if not path or not os.path.exists(path) or not os.path.getsize(path):
        return None
    try:
        return sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=10)
    except sqlite3.Error:
        return None


def _paths(minute_db=None, fast_db=None, proposals_db=None):
    out = {"preskoceni": minute_db, "brzi_put": fast_db, "prijedlozi": proposals_db}
    try:
        if out["preskoceni"] is None:
            from kol import minute
            out["preskoceni"] = minute.db_path()
    except Exception:  # noqa: BLE001
        pass
    try:
        if out["brzi_put"] is None:
            from fast import store as fstore
            out["brzi_put"] = fstore.db_path()
    except Exception:  # noqa: BLE001
        pass
    try:
        if out["prijedlozi"] is None:
            from proposals import store as pstore
            out["prijedlozi"] = pstore.db_path()
    except Exception:  # noqa: BLE001
        pass
    return out


def _put(out, tok, ts, pct, via):
    if not tok or not ts:
        return
    d = out.setdefault(tok, {"ts": 0, "pct": None, "via": set()})
    d["ts"] = max(d["ts"], int(ts))
    if pct is not None:
        d["pct"] = max(d["pct"] if d["pct"] is not None else -1e9, float(pct))
    d["via"].add(via)


def labelled(now, minute_db=None, fast_db=None, proposals_db=None):
    """{token: {"ts": the newest labelled skip, "pct": the best max gain within 60 min (%), "via": {store}}} of the
    skips of the last TTL_S labelled propušteno (>= +MIN_PCT % within 60 min). Read-only; a missing store adds
    nothing."""
    now = int(now)
    since = now - TTL_S
    p = _paths(minute_db, fast_db, proposals_db)
    out = {}
    c = _ro(p["preskoceni"])
    if c is not None:
        try:
            for tok, ts, hi in c.execute("SELECT token, ts, hi60 FROM skip_path WHERE ts >= ? AND hi60 >= ? AND "
                                         "entry IS NOT NULL AND bad IS NULL", (since, MIN_PCT / 100)):
                _put(out, tok, ts, hi * 100, "preskoceni")
        except sqlite3.Error:
            pass
        finally:
            c.close()
    c = _ro(p["brzi_put"])
    if c is not None:
        try:
            for tok, ts, mx in c.execute("SELECT token, decided_ts, max60 FROM signals WHERE decision='SKIP' AND missed=1 "
                                         "AND decided_ts >= ? AND max60 >= ?", (since, MIN_PCT)):
                _put(out, tok, ts, mx, "brzi_put")
        except sqlite3.Error:
            pass
        finally:
            c.close()
    c = _ro(p["prijedlozi"])
    if c is not None:
        try:
            for tok, ts, after in c.execute("SELECT token, created_ts, after FROM proposals WHERE status IN ('isteklo', "
                                            "'odbijeno') AND created_ts >= ? AND after IS NOT NULL", (since,)):
                try:
                    g = ((json.loads(after) or {}).get("1h") or {}).get("max_gain_pct")
                except (ValueError, AttributeError):
                    g = None
                if g is not None and float(g) >= MIN_PCT:
                    _put(out, tok, ts, float(g), "prijedlozi")
        except sqlite3.Error:
            pass
        finally:
            c.close()
    return out


def from_missed(con, now, log=print, force=False, **paths):
    """The labelled tokens into the universe (src missed, due at once, missed_until = now + TTL_S), every EVERY_S.
    Returns how many got a new label."""
    from . import data, market
    now = int(now)
    if not force and now - (data.kv_get(con, "mkt_missed_ts") or 0) < EVERY_S:
        return 0
    data.kv_put(con, "mkt_missed_ts", now)
    got = labelled(now, **paths)
    n, by = 0, {}
    for tok, d in got.items():
        r = con.execute("SELECT missed_ts FROM mkt WHERE token=?", (tok,)).fetchone()
        if r and r[0] and r[0] >= d["ts"]:
            continue   # this label is known: once per label, its 72 h are not renewed by reading it again
        market.add(con, tok, VIA, now, src=SRC)
        con.execute("UPDATE mkt SET missed_until=?, missed_ts=?, missed_pct=?, missed_via=? WHERE token=?",
                    (now + TTL_S, d["ts"], round(d["pct"], 1) if d["pct"] is not None else None,
                     ",".join(sorted(d["via"])), tok))
        n += 1
        for v in d["via"]:
            by[v] = by.get(v, 0) + 1
    if n:
        con.commit()
        log(f"range propušteni: +{n} tokena na listu kao izvor missed na {TTL_S // 3600} h ("
            + ", ".join(f"{k} {v}" for k, v in sorted(by.items())) + "); raspon i ulaz samo iz rangedca/detect")
    return n


def fallback_sql():
    """SQL of the source a token falls back to when its event or missed label ends (one ? = now)."""
    return "CASE WHEN COALESCE(missed_until, 0) > ? THEN 'missed' ELSE 'market' END"


def expire(con, now, on=True, log=print):
    """Missed tokens past their 72 h (every one of them while the flag is off) fall back to source market: the market
    filter keeps them or they leave the list. Returns how many."""
    n = con.execute("UPDATE mkt SET src='market' WHERE src='missed' AND (? = 0 OR COALESCE(missed_until, 0) <= ?)",
                    (int(bool(on)), int(now))).rowcount
    if n and on:
        log(f"range propušteni: {n} tokena nakon {TTL_S // 3600} h natrag na izvor market (ostaju samo uz tržišni filter)")
    return n


# ---------- the owner's hard blocks ---------------------------------------------------------------------------------
def _topcheck_fail(tok):
    try:
        from topcheck import store as tstore
        c = _ro(tstore.DB)
    except Exception:  # noqa: BLE001
        c = None
    if c is None:
        return None
    try:
        r = c.execute("SELECT safety_json FROM top_check WHERE token=?", (tok,)).fetchone()
    except sqlite3.Error:
        r = None
    finally:
        c.close()
    try:
        checks = ((json.loads(r[0]) if r and r[0] else {}) or {}).get("checks") or {}
    except ValueError:
        checks = {}
    for k in ("honeypot", "freeze", "mint", "rugcheck"):
        st = checks.get(k)
        if isinstance(st, (list, tuple)) and len(st) >= 2 and st[0] == "fail":
            return str(st[1])
    return None


def _holders_selling(con, tok, now):
    """rangedca/holders' last reading: the transfer holders net-selling > 2 % of supply (open range tokens only)."""
    try:
        from . import data
        st = data.kv_get(con, f"hold:{tok}") or {}
    except Exception:  # noqa: BLE001
        return None
    if st.get("why") and now - (st.get("checked") or 0) <= HOLDERS_FRESH_S:
        return f"top holderi prodaju: {st['why']}"
    return None


def hard_block(con, tok, s, now=None):
    """The owner's hard block of a missed token (Croatian reason) or None: rug (rugfilter/collapse under the 11.11.
    rule, through league/copy._rugged), the rug archive's rugs, honeypot / freeze / mint / RugCheck "rugged"
    (topcheck.db, rug.db mechanics), the rug filter's high risk (VISOK RIZIK / ODBAČEN), the dev selling (rug filter)
    or the transfer holders selling (rangedca/holders). Liquidity, MC and volume are market.check's. Unknown data is
    no block (as ui/kandidati's "unknown")."""
    now = int(now or time.time())
    mcap, liq = (s or {}).get("mcap"), (s or {}).get("liq")
    try:
        from league import copy as lcopy
        col = lcopy._rugged(tok, mcap, liq)
    except Exception:  # noqa: BLE001
        col = None
    if col:
        return f"rug: {col.get('text') or 'kolaps'}"
    try:
        from rugfilter import archive
        if archive.kind_one(tok) == "rug":
            return "rug: token je u arhivi rugova"
    except Exception:  # noqa: BLE001
        pass
    tf = _topcheck_fail(tok)
    if tf:
        return f"rug mehanika: {tf}"
    try:
        from rugfilter import collapse
        ev = collapse.rug_signals(tok)
    except Exception:  # noqa: BLE001
        ev = {}
    for k in ("mechanics", "risk", "dev"):
        if ev.get(k):
            return ev[k]
    return _holders_selling(con, tok, now)


def info(con, now):
    """{"watched", "listed", "until_max"} of the missed tokens (for get_range_candidates)."""
    try:
        w = con.execute("SELECT COUNT(*) FROM mkt WHERE watched=1 AND src='missed'").fetchone()[0]
        n = con.execute("SELECT COUNT(*) FROM mkt WHERE COALESCE(missed_until, 0) > ?", (int(now),)).fetchone()[0]
        b = con.execute("SELECT COUNT(*) FROM mkt WHERE src='missed' AND watched=0 AND why IS NOT NULL").fetchone()[0]
    except sqlite3.Error:
        return {"watched": 0, "listed": 0, "waiting_or_blocked": 0}
    return {"watched": w, "listed": n, "waiting_or_blocked": b}
