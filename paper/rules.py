"""Entry rules from the 1.11. review "Prijedlozi za bolji algoritam", all applied by the bot itself.

1. Hard rug gate before every demo entry (gate()): T0 must have passed (a non-pump.fun mint needs a real T0 check,
   RugCheck, free), liquidity at least $10k, no pool larger than the token (liq >= 0.8 x mcap: 11 of the
   1.11. night's -100% trades), no $1+ token with a tiny supply (tokenised stocks / wrapped coins), no token whose
   Puls volume fell under 20% of its best hour. What the gate rejects stays tracked, so the page shows how many of
   them later collapsed, and the rug share of trades before / after the gate.
2. A/B of the entry point (ab_*): A = the usual entry (mostly $2-50k MC), B = the first crossing of $100k MC with T0
   passed (retrospective: 2x in 24%, 5x in 9%). Both trade in the demo book with the same stake; once both have
   ab.min_n closed trades the better one (average AND median, on both time halves) gets the slots and the other keeps
   ab.keep_frac of its entries so the comparison never stops. Re-judged every day, so it switches back by itself.
3. KOL convergence trigger (kol3()): >= 3 different X authors on a token within 15 minutes (scanner bots excluded,
   kol.db kols.bot), its own small demo entry; accuracy is measured per session and a session where it keeps losing
   gets only keep_frac of the entries.
4. Position size per session (session_sizes()): from the last 7 days of closed demo trades per session (asia/eu/us);
   a session with profit factor under 1 gets a smaller stake (0.75 / 0.5) and under 0.7 a pause (only keep_frac of
   entries, at half size, so it is still measured). One step per day, comes back up by itself when results improve.

State: LEARNED_DIR/paper_rules.json (a few KB). Nothing here is set by hand.
"""
import json
import os
import sqlite3
import time
import zlib

from learn import weights as _w

DEFAULT = {
    "gate": {"enabled": True, "min_mcap": 20000, "min_liq": 10000, "max_liq_mcap": 0.8, "max_price_small": 1.0, "min_vol_keep": 0.2,
             "t0_checks_per_pass": 8},
    "ab": {"enabled": True, "band": 100000, "fresh_min": 15, "size_usd": 20, "max_open": 40, "max_per_day": None,
           "min_n": 30, "keep_frac": 0.25, "ret_cap": 3.0},
    "kol3": {"enabled": True, "authors": 3, "window_min": 15, "fresh_min": 10, "size_usd": 20, "max_open": 40,
             "max_per_day": None, "min_n": 15, "bad_win": 0.3, "keep_frac": 0.25},
    "sessions": {"enabled": True, "days": 7, "min_n": 30, "steps": [[1.0, 1.0], [0.85, 0.75], [0.7, 0.5]],
                 "pause_below": 0.7, "keep_frac": 0.2, "refresh_h": 24},
}
SESS_HR = {"asia": "Azija (00–08 UTC)", "eu": "Europa (08–14 UTC)", "us": "Amerika (14–24 UTC)"}


def config(cfg):
    """paper config's "rules" block over the defaults."""
    r = (cfg or {}).get("rules") or {}
    return {k: {**v, **(r.get(k) or {})} for k, v in DEFAULT.items()}


def path():
    return os.path.join(_w.LEARNED_DIR, "paper_rules.json")


def load():
    try:
        with open(path()) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save(st):
    """Written only when something changed (intake runs every minute)."""
    try:
        with open(path()) as f:
            if json.load(f) == json.loads(json.dumps(st)):
                return
    except (OSError, ValueError):
        pass
    os.makedirs(os.path.dirname(path()), exist_ok=True)
    tmp = path() + ".tmp"
    with open(tmp, "w") as f:
        json.dump(st, f, indent=1, ensure_ascii=False)
    os.replace(tmp, path())


def since(st, key, now):
    """When rule `key` started (first time it was seen running); kept for the before/after comparison."""
    s = st.setdefault("since", {})
    if key not in s:
        s[key] = int(now)
        return s[key], True
    return s[key], False


def keep(token, frac, salt=""):
    """Deterministic 'let this one through anyway' draw: the same token gets the same answer on every pass."""
    return (zlib.crc32((salt + token).encode()) % 1000) / 1000 < frac


# ---------- 1. hard rug gate ----------

def is_pump(mint):
    return (mint or "").endswith("pump")


def gate(token, price, liq, mcap, t0, features=None, cfg=None):
    """Reason (plain Croatian) to refuse this entry, or None. t0: 'prolaz' / 'pad' / 'nije' / None (no row)."""
    g = config(cfg)["gate"]
    if not g["enabled"]:
        return None
    if mcap and mcap < g.get("min_mcap", 0):  # Nicholas 4.11.: ~$5k fresh listings are mostly rug pulls
        return f"market cap ${mcap:,.0f} ispod ${g['min_mcap']:,.0f} (premali, rizik ruga)".replace(",", ".")
    if (liq or 0) < g["min_liq"]:
        return f"likvidnost ${liq or 0:,.0f} ispod ${g['min_liq']:,.0f}".replace(",", ".")
    if mcap and liq and liq >= g["max_liq_mcap"] * mcap:
        return f"likvidnost (${liq:,.0f}) veća od {g['max_liq_mcap']:.0%} vrijednosti tokena: lažni pool".replace(",", ".")
    if (price or 0) >= g["max_price_small"] and not is_pump(token):
        return "cijena iznad 1 $ uz mali supply (tokenizirana dionica ili wrapped token)"
    if t0 == "pad":
        return "T0: mehanika ruga (mint/freeze ili otključan LP)"
    if t0 != "prolaz" and not (t0 is None and is_pump(token)):
        return "T0 nije provjeren" + ("" if is_pump(token) else " (token izvan pump.funa)")
    sv = (features or {}).get("snaga_volumen")
    if sv is not None and sv < g["min_vol_keep"]:
        return f"volumen pao na {sv:.0%} najboljeg sata (Puls traži barem {g['min_vol_keep']:.0%})"
    return None


def high_risk_size(verdict, size, explore_size):
    """A rug report 'VISOK RIZIK' never gets the bigger core stake (1.11.: INKKY $50 at high risk, -97%)."""
    return min(size, explore_size) if verdict == "VISOK RIZIK" else size


def rug_share(con, start):
    """Rug share of closed demo trades before / after `start`: [{label, n, rugs, share}]; rug = liquidity gone or
    -90% or worse. Hand sales excluded."""
    out = []
    for label, op, a in (("prije filtra", "<", start), ("nakon filtra", ">=", start)):
        n = r = 0
        for ret, er, state in con.execute(f"SELECT ret, exit_reason, state FROM trades WHERE status='closed' "
                                          f"AND opened_ts {op} ? AND opened_ts >= ?", (a, start - 7 * 86400)):
            if '"rucno"' in (state or ""):
                continue
            n += 1
            r += er == "rug" or (ret or 0) <= -0.9
        out.append({"label": label, "n": n, "rugs": r, "share": r / n if n else None})
    return out


def gate_shadow(con, start, now=None):
    """Tokens the gate refused since `start` and what they did afterwards (paper.db ticks): {n, collapsed, share}.
    collapsed = price fell 70%+ below the first tick or liquidity vanished, i.e. the gate saved the stake."""
    n = col = 0
    for tok, p0 in con.execute("SELECT token, price FROM candidates WHERE decision='skip_gate' AND first_ts>=? "
                               "AND price>0", (start,)):
        lo = con.execute("SELECT MIN(price), MIN(liquidity) FROM ticks WHERE token=?", (tok,)).fetchone()
        n += 1
        if lo and lo[0] is not None and (lo[0] <= 0.3 * p0 or (lo[1] or 0) <= 0):
            col += 1
    return {"n": n, "collapsed": col, "share": col / n if n else None}


# ---------- 2. A/B of the entry point ----------

def ab_events(hype_db, band, fresh_min, now):
    """[(token, ts, mcap, price, score)] of first crossings of `band` in the last fresh_min minutes, newest first."""
    point = "B%d" % int(band)
    try:
        con = sqlite3.connect(f"file:{hype_db}?mode=ro", uri=True, timeout=10)
    except sqlite3.OperationalError:
        return []
    try:
        return con.execute("SELECT token, ts, mcap, price, score FROM tier_events WHERE point=? AND ts>=? "
                           "ORDER BY ts DESC", (point, int(now - fresh_min * 60))).fetchall()
    except sqlite3.OperationalError:
        return []
    finally:
        con.close()


def _closed(con, where, args=()):
    rows = []
    for ts, ret, state in con.execute("SELECT opened_ts, ret, state FROM trades WHERE status='closed' AND " + where,
                                      args):
        if '"rucno"' not in (state or ""):
            rows.append((ts, ret or 0))
    return sorted(rows)


def _summ(rows, cap):
    if not rows:
        return {"n": 0}
    rs = sorted(min(r, cap) for _, r in rows)
    return {"n": len(rs), "mean": round(sum(rs) / len(rs), 4), "median": round(rs[len(rs) // 2], 4),
            "win": round(sum(r > 0 for r in rs) / len(rs), 3)}


def ab_judge(con, st, cfg, now):
    """Compare A (usual explore/core entries) and B ($100k crossing) on trades opened since the test started.
    Sets st['ab'] = {since, A, B, winner, text}. The winner needs min_n closed trades on both sides and a better
    average and median, on both time halves of the trades."""
    a = config(cfg)["ab"]
    start, _ = since(st, "ab", now)
    A = _closed(con, "opened_ts>=? AND (config LIKE '%\"entry_mode\": \"explore\"%' OR "
                     "config LIKE '%\"entry_mode\": \"core\"%')", (start,))
    B = _closed(con, "opened_ts>=? AND config LIKE '%\"entry_mode\": \"mc100k\"%'", (start,))
    sa, sb = _summ(A, a["ret_cap"]), _summ(B, a["ret_cap"])
    prev = (st.get("ab") or {}).get("winner")
    winner, text = prev, None
    if sa["n"] >= a["min_n"] and sb["n"] >= a["min_n"]:
        def better(x, y):
            return x["mean"] > y["mean"] and x["median"] > y["median"]
        halves = []
        for lo, hi in ((0, 0.5), (0.5, 1.0)):
            ha = _summ(A[int(len(A) * lo):int(len(A) * hi)], a["ret_cap"])
            hb = _summ(B[int(len(B) * lo):int(len(B) * hi)], a["ret_cap"])
            halves.append((ha, hb))
        if better(sb, sa) and all(hb.get("n") and ha.get("n") and hb["mean"] > ha["mean"] for ha, hb in halves):
            winner = "B"
        elif better(sa, sb) and all(hb.get("n") and ha.get("n") and ha["mean"] > hb["mean"] for ha, hb in halves):
            winner = "A"
        else:
            winner = None
        if winner != prev:
            text = ("Ulaz na prvom prelasku 100k $ je bolji: dobiva većinu demo ulaza." if winner == "B" else
                    "Uobičajeni ulaz je bolji od čekanja 100k $: dobiva većinu demo ulaza." if winner == "A" else
                    "Razlika između dva ulaza više nije jasna: oba opet dobivaju jednako ulaza.")
            st.setdefault("history", []).append({"ts": int(now), "kind": "ab", "text": text})
    st["ab"] = {"since": start, "A": sa, "B": sb, "winner": winner, "ts": int(now)}
    return st["ab"]


def ab_allow(st, mode, token, cfg):
    """Does the losing side of the A/B still get this entry? The winner takes all, the loser keep_frac."""
    w = (st.get("ab") or {}).get("winner")
    if not w or (w == "B" and mode == "mc100k") or (w == "A" and mode != "mc100k"):
        return True
    return keep(token, config(cfg)["ab"]["keep_frac"], "ab")


# ---------- 3. >= 3 KOL authors within 15 minutes ----------

def kol3(kol_db, now, cfg=None, tokens=None):
    """{token: {n, handles, first_ts, last_ts}}: tokens where at least `authors` different X authors called within
    window_min minutes and the newest of them is at most fresh_min old. Scanner/alert bots (kols.bot = 1, the KOL
    thread's fix for 'blossomscanner + bitecong on every token') do not count."""
    k = config(cfg)["kol3"]
    if not kol_db or not os.path.exists(kol_db) or not os.path.getsize(kol_db):
        return {}
    con = sqlite3.connect(f"file:{kol_db}?mode=ro", uri=True, timeout=10)
    try:
        bots = set()
        try:
            bots = {h for (h,) in con.execute("SELECT handle FROM kols WHERE COALESCE(bot, 0) = 1")}
        except sqlite3.OperationalError:
            pass
        since_ts = int(now - (k["window_min"] + k["fresh_min"]) * 60)
        try:  # calls.bad = call at under $3k MC, no outcome (KOL thread, 1.11.)
            rows = con.execute("SELECT token, handle, ts FROM calls WHERE kind='call' AND COALESCE(bad, 0)=0 AND ts>=? "
                               "ORDER BY token, ts", (since_ts,)).fetchall()
        except sqlite3.OperationalError:
            rows = con.execute("SELECT token, handle, ts FROM calls WHERE kind='call' AND ts>=? ORDER BY token, ts",
                               (since_ts,)).fetchall()
    except sqlite3.OperationalError:
        return {}
    finally:
        con.close()
    by = {}
    for tok, h, ts in rows:
        if h and h.lower() not in {b.lower() for b in bots} and (tokens is None or tok in tokens):
            by.setdefault(tok, []).append((ts, h.lower()))
    out = {}
    win = k["window_min"] * 60
    for tok, evs in by.items():
        if now - evs[-1][0] > k["fresh_min"] * 60:
            continue
        best = None
        for i, (t0, _) in enumerate(evs):
            hs = {h for t, h in evs[i:] if t - t0 <= win}
            if len(hs) >= k["authors"] and (best is None or len(hs) > best["n"]):
                last = max(t for t, h in evs[i:] if t - t0 <= win)
                best = {"n": len(hs), "handles": sorted(hs), "first_ts": t0, "last_ts": last}
        if best:
            out[tok] = best
    return out


def by_session(con, mode, days, now):
    """{session: {n, win, mean}} of closed trades of entry_mode `mode` in the last `days` days."""
    from exits.paths import session_of
    out = {}
    for ts, ret in _closed(con, "opened_ts>=? AND config LIKE ?", (int(now - days * 86400),
                                                                     f'%"entry_mode": "{mode}"%')):
        s = out.setdefault(session_of(ts), {"n": 0, "w": 0, "sum": 0.0})
        s["n"] += 1
        s["w"] += ret > 0
        s["sum"] += ret
    return {k: {"n": v["n"], "win": round(v["w"] / v["n"], 3), "mean": round(v["sum"] / v["n"], 4)}
            for k, v in out.items()}


def kol3_allow(con, token, now, cfg):
    """A session where the trigger keeps losing (min_n trades, win share under bad_win) gets keep_frac of entries."""
    from exits.paths import session_of
    k = config(cfg)["kol3"]
    s = by_session(con, "kol3", 14, now).get(session_of(now))
    if not s or s["n"] < k["min_n"] or s["win"] >= k["bad_win"]:
        return True
    return keep(token, k["keep_frac"], "kol3")


# ---------- 4. position size per session ----------

def _factor(pf, sc):
    if pf is None:
        return 1.0
    if pf < sc["pause_below"]:
        return 0.0
    for lo, f in sc["steps"]:
        if pf >= lo:
            return f
    return sc["steps"][-1][1]


def session_sizes(con, st, cfg, now, force=False):
    """{session: {n, win, pf, factor}} learned from the last `days` days of closed demo trades (by return, so a
    smaller stake does not change the measurement). Refreshed every refresh_h hours; the factor moves at most one
    step per refresh (1 -> 0.75 -> 0.5 -> pauza and back)."""
    from exits.paths import session_of
    sc = config(cfg)["sessions"]
    cur = st.get("sessions") or {}
    if not force and cur and now - cur.get("ts", 0) < sc["refresh_h"] * 3600:
        return cur
    agg = {}
    for ts, ret in _closed(con, "opened_ts>=?", (int(now - sc["days"] * 86400),)):
        a = agg.setdefault(session_of(ts), {"n": 0, "w": 0, "g": 0.0, "l": 0.0})
        a["n"] += 1
        a["w"] += ret > 0
        a["g"] += max(ret, 0)
        a["l"] += max(-ret, 0)
    ladder = [f for _, f in sc["steps"]] + [0.0]
    out = {"ts": int(now), "by": {}}
    for s in ("asia", "eu", "us"):
        a = agg.get(s) or {"n": 0, "w": 0, "g": 0.0, "l": 0.0}
        pf = round(a["g"] / a["l"], 2) if a["l"] > 0 else None
        target = _factor(pf, sc) if a["n"] >= sc["min_n"] else 1.0
        prev = ((cur.get("by") or {}).get(s) or {}).get("factor", 1.0)
        i, j = ladder.index(prev) if prev in ladder else 0, ladder.index(target) if target in ladder else 0
        f = ladder[i + (1 if j > i else -1 if j < i else 0)]
        out["by"][s] = {"n": a["n"], "win": round(a["w"] / a["n"], 3) if a["n"] else None, "pf": pf, "factor": f}
        if f != prev:
            st.setdefault("history", []).append({"ts": int(now), "kind": "sesija", "text": (
                f"{SESS_HR[s]}: " + ("pauza novih ulaza (samo mali dio za mjerenje)" if f == 0 else
                                     f"ulog {f:.0%} od uobičajenog") + f" (faktor dobiti {pf}, {a['n']} tradeova)")})
    st["sessions"] = out
    st["history"] = (st.get("history") or [])[-60:]
    return out


def size_for(st, token, size, now, cfg):
    """(stake, note) for a new entry in the current session; (0, note) = paused and not one of the kept ones."""
    from exits.paths import session_of
    sc = config(cfg)["sessions"]
    if not sc["enabled"]:
        return size, None
    s = session_of(now)
    f = (((st.get("sessions") or {}).get("by") or {}).get(s) or {}).get("factor", 1.0)
    if f >= 1.0:
        return size, None
    if f <= 0:
        if keep(token, sc["keep_frac"], "sess"):
            return round(size * 0.5, 2), f"{SESS_HR[s]} na pauzi, mali ulaz za mjerenje"
        return 0, f"{SESS_HR[s]} na pauzi (gubi zadnjih {sc['days']} dana)"
    return round(size * f, 2), f"{SESS_HR[s]}: ulog {f:.0%}"
