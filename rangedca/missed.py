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

12.11. (Jure, točka 4: "Missed-movers mjerenje: kad token ima manje od 3 točke cijene u prozoru, označi rezultat kao
'nepouzdano' i ne računaj ga u statistiku propuštenih"): every measurement of what a skipped / missed token did
afterwards counts the price points of its own window, and with fewer than MIN_POINTS (3) the result is UNRELIABLE
("nepouzdano"): shown as that word instead of its number, never labelled propušteno here (so never on the range list
as source missed, never in its rounds, the missed vs ostali report or the missed live gate), never in a count, hit
rate or EV of the missed, and every such statistic says how many it left out (note()). The counts: kol/preskoceni
skip_path.n_pts (1-minute candles of the 60 min), fast/outcomes out.n_points (fast.db px points of the 60 min),
proposals/outcomes after["1h"].n_points (the merged minutes of the hour), proposals/report (the minutes after a zone
entry, the momentum snapshots of a riser), learn/outcomes (the token's snapshots), learn/shadow points.n_pts (the
24 h path: ui/learnpage's missed winners, learn/detektiv), paper/review (the ticks of the tracking window). A row
measured before 12.11. without a count is unknown (reliable() None) and counted as before.
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
# 12.11. (Jure, točka 4): a missed result measured on fewer than MIN_POINTS prices in its window is "nepouzdano"
MIN_POINTS = 3
UNRELIABLE = "nepouzdano"
WHY = f"manje od {MIN_POINTS} točke cijene"
UNREL_KV = "mkt_missed_unrel"   # range.db kv: the tokens whose every label of the last TTL_S was nepouzdano
UNREL_KEEP = 500


def reliable(n_points):
    """12.11.: True = >= MIN_POINTS price points in the measured window; False = fewer (the result is nepouzdano, in
    no statistic of the missed); None = no count stored (a row measured before 12.11.: counted as before)."""
    if n_points is None or isinstance(n_points, bool):
        return None
    try:
        return int(n_points) >= MIN_POINTS
    except (TypeError, ValueError):
        return None


def unreliable(n_points):
    """12.11.: the count is known and below MIN_POINTS."""
    return reliable(n_points) is False


def points_hr(n):
    """'0 točaka' / '1 točka' / '2 točke' / '5 točaka' (cijene): the Croatian plural of a point count."""
    n = int(n or 0)
    if n % 10 == 1 and n % 100 != 11:
        return f"{n} točka"
    if n % 10 in (2, 3, 4) and n % 100 not in (12, 13, 14):
        return f"{n} točke"
    return f"{n} točaka"


def note(n):
    """12.11.: how many results a statistic of the missed left out, e.g. 'nepouzdano: 2 (manje od 3 točke cijene)'."""
    return f"{UNRELIABLE}: {int(n or 0)} ({WHY})"


def detail(n, window="60 min"):
    """12.11.: one nepouzdano result in words, e.g. 'samo 2 točke cijene u 60 min (treba 3)'."""
    n = int(n or 0)
    head = "nijedna točka" if n == 0 else f"samo {points_hr(n)}"
    return f"{head} cijene u {window} (treba {MIN_POINTS})"


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


def _put_unrel(unrel, tok, ts, n, via):
    if not tok or not ts:
        return
    d = unrel.setdefault(tok, {"ts": 0, "n_points": None, "via": set()})
    d["ts"] = max(d["ts"], int(ts))
    d["n_points"] = max(d["n_points"] if d["n_points"] is not None else -1, int(n))
    d["via"].add(via)


def _n_points(js):
    """n_points of a fast.db outcome JSON (out); None when not there."""
    try:
        d = json.loads(js) if js else {}
        return d.get("n_points") if isinstance(d, dict) else None
    except (ValueError, TypeError):
        return None


def labelled(now, minute_db=None, fast_db=None, proposals_db=None, excluded=None):
    """{token: {"ts": the newest labelled skip, "pct": the best max gain within 60 min (%), "via": {store}}} of the
    skips of the last TTL_S labelled propušteno (>= +MIN_PCT % within 60 min). Read-only; a missing store adds
    nothing. 12.11. (Jure, točka 4): a skip measured on fewer than MIN_POINTS prices in its 60 min is nepouzdano, not
    propušteno: no label (a fast.db row whose window is still open waits for its points). excluded: a dict filled with
    {token: {"ts", "n_points", "via"}} of the tokens whose every rise of the last TTL_S was nepouzdano (the count the
    list and the missed statistics leave out)."""
    now = int(now)
    since = now - TTL_S
    p = _paths(minute_db, fast_db, proposals_db)
    out, unrel = {}, {}
    c = _ro(p["preskoceni"])
    if c is not None:
        try:
            # 12.11.: n_pts (kol/preskoceni, the 1-minute candles of the 60 min); NULL before 12.11. = counted as before
            n_col = "n_pts" if "n_pts" in {r[1] for r in c.execute("PRAGMA table_info(skip_path)")} else "NULL"
            for tok, ts, hi, n in c.execute(f"SELECT token, ts, hi60, {n_col} FROM skip_path WHERE ts >= ? AND "
                                            "hi60 >= ? AND entry IS NOT NULL AND bad IS NULL", (since, MIN_PCT / 100)):
                if unreliable(n):
                    _put_unrel(unrel, tok, ts, n, "preskoceni")
                    continue
                _put(out, tok, ts, hi * 100, "preskoceni")
        except sqlite3.Error:
            pass
        finally:
            c.close()
    c = _ro(p["brzi_put"])
    if c is not None:
        try:
            # 12.11.: fast/outcomes stores missed NULL for a thin window; a row measured before keeps missed = 1, so the
            # count (out.n_points, the fast.db px points of the 60 min) decides for both
            for tok, ts, mx, mi, done, js in c.execute(
                    "SELECT token, decided_ts, max60, missed, out_done, out FROM signals WHERE decision='SKIP' AND "
                    "decided_ts >= ? AND max60 >= ? AND (missed = 1 OR out_done = 1)", (since, MIN_PCT)):
                n = _n_points(js)
                if unreliable(n):
                    if done:
                        _put_unrel(unrel, tok, ts, n, "brzi_put")
                    continue   # an open window: its next points decide
                if mi == 1:
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
                    h1 = (json.loads(after) or {}).get("1h") or {}
                    g = h1.get("max_gain_pct")
                except (ValueError, AttributeError):
                    h1, g = {}, None
                if g is not None and float(g) >= MIN_PCT:
                    if unreliable(h1.get("n_points")):   # 12.11.: the merged minutes of the hour (proposals/outcomes)
                        _put_unrel(unrel, tok, ts, h1["n_points"], "prijedlozi")
                        continue
                    _put(out, tok, ts, float(g), "prijedlozi")
        except sqlite3.Error:
            pass
        finally:
            c.close()
    if excluded is not None:
        excluded.update({t: d for t, d in unrel.items() if t not in out})
    return out


def from_missed(con, now, log=print, force=False, **paths):
    """The labelled tokens into the universe (src missed, due at once, missed_until = now + TTL_S), every EVERY_S.
    Returns how many got a new label."""
    from . import data, market
    now = int(now)
    if not force and now - (data.kv_get(con, "mkt_missed_ts") or 0) < EVERY_S:
        return 0
    data.kv_put(con, "mkt_missed_ts", now)
    unrel = {}
    got = labelled(now, excluded=unrel, **paths)
    _note_unreliable(con, unrel, now, log)
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


def _note_unreliable(con, unrel, now, log=print):
    """12.11.: the tokens left out as nepouzdano into range.db kv (UNREL_KV: missed_meta, the EV report); a log line
    only for the ones not left out at the previous read."""
    from . import data
    prev = set((data.kv_get(con, UNREL_KV) or {}).get("tokens") or [])
    toks = sorted(unrel, key=lambda t: -unrel[t]["ts"])[:UNREL_KEEP]
    data.kv_put(con, UNREL_KV, {"ts": int(now), "n": len(unrel), "tokens": toks})
    new = [t for t in toks if t not in prev]
    if new:
        who = "taj token nije" if len(new) == 1 else "ti tokeni nisu"
        log(f"range propušteni: {note(len(new))} u 60 min nakon preskoka, {who} na listi ni u statistici "
            f"propuštenih (u zadnja {TTL_S // 3600} h ukupno {len(unrel)})")


def unreliable_info(con):
    """12.11.: {"n", "ts", "tokens"} of the last read's nepouzdano tokens (range.db kv); zeros without one."""
    try:
        from . import data
        u = data.kv_get(con, UNREL_KV) or {}
    except sqlite3.Error:
        u = {}
    return {"n": int(u.get("n") or 0), "ts": u.get("ts"), "tokens": list(u.get("tokens") or [])}


def unreliable_now():
    """unreliable_info() on a read-only range.db connection (the EV report); zeros without range.db."""
    try:
        from . import data
        con = data.ro()
    except Exception:  # noqa: BLE001
        con = None
    if con is None:
        return {"n": 0, "ts": None, "tokens": []}
    try:
        return unreliable_info(con)
    finally:
        con.close()


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
    """{"watched", "listed", "waiting_or_blocked", "unreliable", "unreliable_why"} of the missed tokens (for
    get_range_candidates). 12.11.: unreliable = the tokens of the last TTL_S whose every rise was measured on fewer
    than MIN_POINTS prices (nepouzdano: not on the list, in no statistic of the missed)."""
    u = unreliable_info(con)
    why = f"{WHY} u 60 min nakon preskoka: nije propušteno, nije na listi ni u statistici propuštenih"
    try:
        w = con.execute("SELECT COUNT(*) FROM mkt WHERE watched=1 AND src='missed'").fetchone()[0]
        n = con.execute("SELECT COUNT(*) FROM mkt WHERE COALESCE(missed_until, 0) > ?", (int(now),)).fetchone()[0]
        b = con.execute("SELECT COUNT(*) FROM mkt WHERE src='missed' AND watched=0 AND why IS NOT NULL").fetchone()[0]
    except sqlite3.Error:
        return {"watched": 0, "listed": 0, "waiting_or_blocked": 0, "unreliable": u["n"], "unreliable_why": why}
    return {"watched": w, "listed": n, "waiting_or_blocked": b, "unreliable": u["n"], "unreliable_why": why}
