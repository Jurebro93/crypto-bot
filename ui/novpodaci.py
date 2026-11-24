"""Read-only data of the wallet pages (19.11., vlasnik: "the admin must have a dashboard with more data about the
wallets than an ordinary user ... the ordinary user should only be informed: follow this wallet because of this and
this"): insajderi.db (Insajderi 2.0 + "kupuje prije pumpe", insajderi/prijepumpe.py), wallets.db (the scored wallets'
history), holderi.db (large holders of the midcaps), league.db (the demo trades that follow wallets), trade.db (the
real-money pause).

Rules: every connection is read-only (file:...?mode=ro), nothing here writes, nothing reaches the network, a missing
database / table / column is "nothing yet" (never an exception into a page). The other agent's modules (insajderi/
store, prijepumpe) are only READ (their constants, db_path, helius_cap); the queries are here.

Neutral wording everywhere: "kupuje prije pumpe" is a statistic about a group of wallets, never a statement about who
they are.
"""
import json
import os
import sqlite3
import statistics
import time

D = 86400
# the demo sources that follow wallets: league.db trades.source starts with one of these (wallets/kopija_demo.SRC,
# insajderi/live.SRC). A new demo source ("kupuje prije pumpe", bundles) is ONE more entry here.
# insajderi/pp_live.SRC: "prije pumpe kandidat" before "prije pumpe" (the longer prefix names a row's kind first)
DEMO_SOURCES = ("prije pumpe kandidat", "prije pumpe", "bundle", "kopija dokazanih", "insajderi2")
DEMO_LABEL = {"prije pumpe kandidat": "kandidat", "prije pumpe": "prije pumpe", "bundle": "bundle",
              "kopija dokazanih": "kopija dokazanih", "insajderi2": "insajderi2"}
EXCLUDED = ("relayer", "bot", "snajper", "kupuje_sve", "market_maker", "jednokratni", "bez_placanja")
EXCL_HR = {"relayer": "relayer", "bot": "bot", "snajper": "snajper", "kupuje_sve": "kupuje sve",
           "market_maker": "market maker", "jednokratni": "jednokratni", "bez_placanja": "bez plaćanja"}
SHOWN_CLS = ("prije_pumpe", "kandidat")


# ---------- connections ----------------------------------------------------------------------------------------------

def ro(path):
    """A read-only connection, or None (no file, empty file, unreadable)."""
    try:
        if not path or not os.path.exists(path) or not os.path.getsize(path):
            return None
        return sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5)
    except (sqlite3.Error, OSError):
        return None


def q(con, sql, args=()):
    if con is None:
        return []
    try:
        return con.execute(sql, args).fetchall()
    except sqlite3.Error:
        return []


def has_table(con, name):
    return bool(q(con, "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)))


def ins_path():
    try:
        from insajderi import store
        return store.db_path()
    except Exception:  # noqa: BLE001
        return None


def ins_con():
    return ro(ins_path())


def _json(s, default=None):
    try:
        v = json.loads(s) if isinstance(s, (str, bytes)) else s
        return default if v is None else v
    except (ValueError, TypeError):
        return default


# ---------- the status strip -----------------------------------------------------------------------------------------

def summary(con):
    """The last pass's summary (i2_kv summary) and its "prije_pumpe" block; ({}, {}) before the first pass."""
    rows = q(con, "SELECT value FROM i2_kv WHERE key='summary'")
    s = _json(rows[0][0], {}) if rows else {}
    s = s if isinstance(s, dict) else {}
    pp = s.get("prije_pumpe") if isinstance(s.get("prije_pumpe"), dict) else {}
    return s, pp


def last_run(con):
    """{"ts", "kind", "credits", "detail"} of the newest i2_runs row, or None."""
    rows = q(con, "SELECT ts, kind, credits, detail FROM i2_runs ORDER BY ts DESC LIMIT 1")
    if not rows:
        return None
    ts, kind, cr, det = rows[0]
    det = _json(det, {})
    return {"ts": ts, "kind": kind, "credits": cr, "detail": det if isinstance(det, dict) else {}}


def helius(con, now=None):
    """(spent today, day cap, how the cap was set) or (spent, None, None) when the cap cannot be read."""
    now = int(now or time.time())
    spent = None
    rows = q(con, "SELECT value FROM i2_kv WHERE key=?", (f"helius:{time.strftime('%Y-%m-%d', time.gmtime(now))}",))
    if rows:
        try:
            spent = int(float(rows[0][0]))
        except (TypeError, ValueError):
            spent = None
    try:
        from insajderi import store
        try:
            from usage import meter
            udb = meter.DB
        except Exception:  # noqa: BLE001
            udb = None
        cap, how = store.helius_cap(store.config(), now, udb)
        return spent, cap, how
    except Exception:  # noqa: BLE001
        return spent, None, None


def pause_on():
    """The real-money pause (trade/settings.pauza through ui/pauza's cached read-only helper)."""
    try:
        from ui import pauza
        return pauza.on()
    except Exception:  # noqa: BLE001
        return False


def social():
    try:
        from ops import drustveni
        return drustveni.state(create=False)
    except Exception:  # noqa: BLE001
        return None


# ---------- groups "kupuje prije pumpe" ------------------------------------------------------------------------------

GKEYS = ("owner", "members", "n_members", "cls", "why", "n_pumps15", "n_pumps2", "n_tokens", "med_lead_min",
         "pnl_sol", "confirmed_ts", "last_seen")


def _group(row):
    g = dict(zip(GKEYS, row))
    m = _json(g.get("members"), [])
    g["members"] = [str(x) for x in m] if isinstance(m, list) else []
    return g


def group_count(con, conf_only=False, tier=None):
    where, args = _where(conf_only, tier)
    r = q(con, f"SELECT COUNT(*) FROM i2_pp WHERE {where}", args)
    return r[0][0] if r else 0


def _where(conf_only, tier):
    w = [f"cls IN ({','.join('?' * len(SHOWN_CLS))})"]
    args = list(SHOWN_CLS)
    if conf_only:
        w.append("confirmed_ts IS NOT NULL")
    if tier == "15":
        w.append("COALESCE(n_pumps15, 0) > 0")
    elif tier == "2":
        w.append("COALESCE(n_pumps2, 0) > 0")
    return " AND ".join(w), args


def groups(con, conf_only=False, tier=None, limit=50, offset=0):
    """Owner groups (confirmed first, then pumps >= 15M, then tokens), paginated."""
    where, args = _where(conf_only, tier)
    rows = q(con, f"SELECT {', '.join(GKEYS)} FROM i2_pp WHERE {where} ORDER BY (confirmed_ts IS NULL), "
                  "COALESCE(n_pumps15, 0) DESC, COALESCE(n_tokens, 0) DESC, owner LIMIT ? OFFSET ?",
             (*args, int(limit), int(offset)))
    return [_group(r) for r in rows]


def confirmed_groups(con, limit=10):
    rows = q(con, f"SELECT {', '.join(GKEYS)} FROM i2_pp WHERE cls='prije_pumpe' AND confirmed_ts IS NOT NULL "
                  "ORDER BY COALESCE(n_pumps15, 0) DESC, COALESCE(n_tokens, 0) DESC, owner LIMIT ?", (int(limit),))
    return [_group(r) for r in rows]


def pumps_of(con, owners):
    """{owner: [pump rows]} of the given owners: every pump event they bought early in, newest first."""
    owners = [o for o in owners if o]
    if not owners:
        return {}
    out = {o: [] for o in owners}
    sql = (f"SELECT p.owner, p.wallet, e.token, e.symbol, e.t0, e.tier, e.peak_mc, p.buy_ts, p.lead_s, p.sol_in, "
           f"p.sol_out, p.sold_into FROM i2_part p JOIN i2_events e ON e.eid = p.eid WHERE p.owner IN "
           f"({','.join('?' * len(owners))}) AND p.bought_before = 1 AND e.tier IS NOT NULL ORDER BY e.t0 DESC")
    rows = q(con, sql, owners)
    if not rows:   # an older insajderi.db without tier / peak_mc
        rows = q(con, sql.replace("e.tier, e.peak_mc", "NULL, NULL").replace(" AND e.tier IS NOT NULL", ""), owners)
    keys = ("owner", "wallet", "token", "symbol", "t0", "tier", "peak_mc", "buy_ts", "lead_s", "sol_in", "sol_out",
            "sold_into")
    for r in rows:
        d = dict(zip(keys, r))
        out.setdefault(d["owner"], []).append(d)
    return out


def links(con, members):
    """What ties a group's wallets, from what is stored: a fee payer paying for two or more of them, the same block.
    [] when nothing is stored (the funder / corr ties are used by the owner grouping but not kept per wallet)."""
    members = [m for m in members if m]
    if len(members) < 2:
        return []
    ph = ",".join("?" * len(members))
    out = []
    for payer, n in q(con, f"SELECT payer, COUNT(DISTINCT wallet) FROM i2_trades WHERE wallet IN ({ph}) AND payer IS NOT "
                           f"NULL AND payer != wallet GROUP BY payer HAVING COUNT(DISTINCT wallet) >= 2 "
                           f"ORDER BY 2 DESC LIMIT 3", members):
        out.append(("platitelj", payer, n))
    r = q(con, f"SELECT COUNT(*) FROM (SELECT slot FROM i2_trades WHERE wallet IN ({ph}) AND slot IS NOT NULL AND "
               f"side='buy' GROUP BY mint, slot HAVING COUNT(DISTINCT wallet) >= 2)", members)
    if r and r[0][0]:
        out.append(("blok", None, r[0][0]))
    return out


def bundles(con, limit=30):
    keys = ("bid", "kind", "members", "n_members", "n_pumps", "n_pumps15", "share_med", "sold_into", "tokens",
            "last_seen")
    rows = q(con, f"SELECT {', '.join(keys)} FROM i2_bundle ORDER BY COALESCE(n_pumps15, 0) DESC, "
                  "COALESCE(n_pumps, 0) DESC LIMIT ?", (int(limit),))
    out = []
    for r in rows:
        d = dict(zip(keys, r))
        d["members"] = [str(x) for x in (_json(d["members"], []) or []) if x]
        d["tokens"] = [str(x) for x in (_json(d["tokens"], []) or []) if x]
        out.append(d)
    return out


def bundle_count(con):
    r = q(con, "SELECT COUNT(*) FROM i2_bundle")
    return r[0][0] if r else 0


def exclusions(con, pp, limit=40):
    """{cls: {"n", "rows"}} of every excluded class: counts from the last pass's classes (those include the one-time
    wallets, which are not stored), rows (owner, why, members) from i2_pp."""
    cls = (pp or {}).get("classes") if isinstance((pp or {}).get("classes"), dict) else {}
    out = {}
    for c in EXCLUDED:
        rows = q(con, "SELECT owner, why, members, n_members FROM i2_pp WHERE cls=? ORDER BY owner LIMIT ?", (c, int(limit)))
        stored = q(con, "SELECT COUNT(*) FROM i2_pp WHERE cls=?", (c,))
        n = cls.get(c)
        if n is None:
            n = stored[0][0] if stored else 0
        out[c] = {"n": int(n or 0), "rows": [{"owner": o, "why": w, "members": _json(m, []) or [], "n_members": k}
                                            for o, w, m, k in rows]}
    return out


def demo_tokens(con, tokens):
    """{mint: symbol} from i2_events (bundles list mints only)."""
    tokens = [t for t in tokens if t]
    if not tokens:
        return {}
    return {t: s for t, s in q(con, f"SELECT token, MAX(symbol) FROM i2_events WHERE token IN "
                                    f"({','.join('?' * len(tokens))}) GROUP BY token", tokens) if s}


# ---------- the copy test --------------------------------------------------------------------------------------------

def copy_table(pp):
    """[(variant label, bucket, stats dict)] of the stored copy test (summary), in a fixed order; [] before one."""
    cp = (pp or {}).get("copy") if isinstance((pp or {}).get("copy"), dict) else {}
    out = []
    for v, lab in (("60s", "60 s"), ("brzo", "brzo 2 s (Pretpostavka klizanja 1 %)"), ("null", "nasumični novčanici")):
        block = cp.get(v) if isinstance(cp.get(v), dict) else {}
        for b in ("svi", "15M+", "5M-15M", "1M-5M", "<1M"):
            s = block.get(b) if isinstance(block.get(b), dict) else None
            if s is not None:
                out.append((lab, b, s))
    return out


def verdict(pp):
    """One plain line from the stored numbers (never hard-coded): proven / not yet / too little data."""
    cp = (pp or {}).get("copy") if isinstance((pp or {}).get("copy"), dict) else {}
    a = ((cp.get("60s") or {}).get("svi") or {}) if isinstance(cp.get("60s"), dict) else {}
    need = int((pp or {}).get("min_n") or 20)
    n = int(a.get("n") or 0)
    if not cp:
        return "Test kopiranja još nije pokrenut: prvi rezultat nakon noćnog prolaza."
    if n < need:
        return f"Premalo podataka: n={n} od potrebnih {need} kopija (60 s, svi)."
    lo, hi, ev = a.get("lo_pct"), a.get("hi_pct"), a.get("ev_pct")
    from ui import redak as rd
    if lo is None or hi is None:
        return f"Još nije dokazano: prosjek {rd.num(ev, 1, sign=True)} % bez intervala (premalo tokena)." if ev is not None else \
            "Još nije dokazano: nema intervala."
    from ui import redak as rd
    f = (lambda x: rd.num(x, 1, sign=True))
    ci = f"[{f(lo)}; {f(hi)}]"
    if lo > 0:
        return f"Kopiranje 60 s je u plusu: {f(ev)} %, 95 % interval {ci} iznad nule (n={n})."
    if hi < 0:
        return f"Kopiranje 60 s je u minusu: {f(ev)} %, 95 % interval {ci} ispod nule (n={n})."
    return f"Još nije dokazano: interval dira nulu ({f(ev)} %, {ci}, n={n})."


# ---------- wallets.db: the history of the wallets ---------------------------------------------------------------------

def wallet_db():
    try:
        from wallets import store as wstore
        return wstore.DB
    except Exception:  # noqa: BLE001
        return None


def wallet_history(wallets, path=None, extra_top=50):
    """[{wallet, closed, win_rate, realized, first_ts, last_ts, days, proven, copyable, rank, score, scored}] for the
    given wallets (group members) and the best extra_top scored wallets; "scored" False = history not computed yet."""
    con = ro(path or wallet_db())
    if con is None:
        return [], False
    try:
        ws = list(dict.fromkeys(w for w in wallets if w))
        top = [w for (w,) in q(con, "SELECT wallet FROM wallets WHERE stats IS NOT NULL ORDER BY COALESCE(copy_score, "
                                    "score, 0) DESC LIMIT ?", (int(extra_top),))]
        ws += [w for w in top if w not in ws]
        if not ws:
            return [], True
        rows = {}
        for i in range(0, len(ws), 500):
            part = ws[i:i + 500]
            ph = ",".join("?" * len(part))
            for w, stats, hist_from, last_tx, first_seen in q(con, f"SELECT wallet, stats, history_from, last_tx_ts, "
                                                                   f"first_seen FROM wallets WHERE wallet IN ({ph})", part):
                rows[w] = (stats, hist_from, last_tx, first_seen)
            for w, lo, hi in q(con, f"SELECT wallet, MIN(ts), MAX(ts) FROM wallet_trades WHERE wallet IN ({ph}) "
                                    "GROUP BY wallet", part):
                st, hf, lt, fs = rows.get(w, (None, None, None, None))
                rows[w] = (st, hf, lt, fs, lo, hi)
        proven = set()
        if has_table(con, "dokazani"):
            last = q(con, "SELECT MAX(as_of) FROM dokazani")
            if last and last[0][0]:
                proven = {w for (w,) in q(con, "SELECT wallet FROM dokazani WHERE as_of=? AND passed=1", (last[0][0],))}
    finally:
        con.close()
    rank = {}
    try:
        from wallets import rang
        for i, r in enumerate(rang.ranked("wallet", path or wallet_db()), 1):
            rank[r["target"]] = (i, r.get("copyable"), r.get("score"))
    except Exception:  # noqa: BLE001
        rank = {}
    out = []
    for w in ws:
        v = rows.get(w)
        st = _json(v[0], {}) if v else {}
        st = st if isinstance(st, dict) else {}
        first = v[4] if v and len(v) > 4 and v[4] else None
        last = v[5] if v and len(v) > 5 and v[5] else (v[2] if v else None)
        rk = rank.get(w)
        out.append({"wallet": w, "scored": bool(st), "closed": st.get("closed"), "win_rate": st.get("win_rate"),
                    "realized": st.get("closed_pnl_sol", st.get("realized_sol")), "first_ts": first, "last_ts": last,
                    "days": round((last - first) / D, 1) if first and last and last >= first else None,
                    "proven": w in proven, "copyable": rk[1] if rk else None, "rank": rk[0] if rk else None,
                    "score": rk[2] if rk else None})
    return out, True


def povijest_status(path=None, now=None):
    """wallets/povijest.status() (the history queue, scored / waiting per source, credits, the last pass); None when
    the module or the database cannot be read."""
    path = path or wallet_db()
    con = ro(path)
    have = con is not None and has_table(con, "povijest_queue")
    if con is not None:
        con.close()
    if not have:   # no database / an older one: the queue does not exist yet (not "0 waiting")
        return None
    try:
        from wallets import povijest
        return povijest.status(path, now)
    except Exception:  # noqa: BLE001
        return None


def hist_of(con, owners):
    """{owner: i2_pp_hist row} of the given groups (the members' own scored history, report only)."""
    owners = [o for o in owners if o]
    if not owners or not has_table(con, "i2_pp_hist"):
        return {}
    keys = ("owner", "n_members", "n_scored", "realized_sol", "profitable_share", "pump_pnl_sol", "agrees")
    return {r[0]: dict(zip(keys, r)) for r in q(con, f"SELECT {', '.join(keys)} FROM i2_pp_hist WHERE owner IN "
                                                       f"({','.join('?' * len(owners))})", owners)}


def stages(con):
    """The last night / deploy pass's stage seconds and whether it was cut (i2_kv stage_s), or None."""
    rows = q(con, "SELECT value FROM i2_kv WHERE key='stage_s'")
    v = _json(rows[0][0], {}) if rows else None
    return v if isinstance(v, dict) and v else None


# ---------- holderi.db: large holders with a long history --------------------------------------------------------------

def holders(limit=40, path=None, now=None):
    """(rows, info) of wallets.db veliki_holderi (wallets/povijest.holders: >= 50k $ of a midcap held >= 30 days, no
    exchange / pool / team), 15-200M first then by value, each with the wallet's own scored history when it has one;
    info False when the table does not exist yet."""
    now = int(now or time.time())
    con = ro(path or wallet_db())
    if con is None or not has_table(con, "veliki_holderi"):
        if con is not None:
            con.close()
        return [], False
    try:
        keys = ("wallet", "mint", "symbol", "tier", "mcap", "value_usd", "pct", "first_ts", "held_days")
        rows = [dict(zip(keys, r)) for r in q(con, f"SELECT {', '.join(keys)} FROM veliki_holderi ORDER BY "
                                                   "(tier = '15-200M') DESC, value_usd DESC LIMIT ?", (int(limit),))]
        n = q(con, "SELECT COUNT(*), COUNT(DISTINCT wallet) FROM veliki_holderi")
        ws = sorted({r["wallet"] for r in rows})
        st = {}
        if ws:
            for w, s_ in q(con, f"SELECT wallet, stats FROM wallets WHERE stats IS NOT NULL AND wallet IN "
                                f"({','.join('?' * len(ws))})", ws):
                d = _json(s_, {})
                st[w] = d if isinstance(d, dict) else {}
    finally:
        con.close()
    for r in rows:
        h = st.get(r["wallet"])
        r["scored"] = bool(h)
        r["closed"] = (h or {}).get("closed")
        r["win_rate"] = (h or {}).get("win_rate")
        r["realized"] = (h or {}).get("closed_pnl_sol", (h or {}).get("realized_sol")) if h else None
        if r.get("held_days") is None and r.get("first_ts"):
            r["held_days"] = round((now - r["first_ts"]) / D, 1)
    return rows, {"n": (n[0][0] if n else 0), "wallets": (n[0][1] if n else 0)}


# ---------- the demo trades that follow wallets (league.db) --------------------------------------------------------------

def league_db():
    try:
        from league import store as lstore
        return lstore.DB
    except Exception:  # noqa: BLE001
        return None


def demo_users():
    """The demo accounts that follow wallets: trade/settings.PAPER_USER (kopija dokazanih, insajderi2 until they move)
    and insajderi/pp_live.USER (prije pumpe, kandidati, bundle; the others' new entries)."""
    users = []
    try:
        from trade import settings
        users.append(settings.PAPER_USER)
    except Exception:  # noqa: BLE001
        users.append("autopilot-paper")
    try:
        from insajderi import pp_live
        users.append(pp_live.USER)
    except Exception:  # noqa: BLE001
        users.append("autopilot-novcanici")
    return tuple(dict.fromkeys(users))


def _bucket(mcap):
    try:
        from insajderi import pp_live
        return pp_live.bucket(mcap)
    except Exception:  # noqa: BLE001
        return "?"


def demo_trades(prefixes=DEMO_SOURCES, limit_closed=20, days=14, path=None, now=None):
    """(open rows, recent closed rows) of the wallet-following demo trades: every demo account in demo_users(), chosen
    by the source prefix (not by the account), each with its kind, MC bucket at entry and the followed group / wallet
    when the strategy's own table names it."""
    now = int(now or time.time())
    users = demo_users()
    con = ro(path or league_db())
    if con is None:
        return [], []
    try:
        like = " OR ".join("source LIKE ?" for _ in prefixes)
        args = [p.replace("%", "") + "%" for p in prefixes]
        keys = ("id", "user", "token", "symbol", "opened_ts", "closed_ts", "status", "size_usd", "entry_px", "exit_px",
                "ret", "pnl_usd", "source")
        rows = q(con, f"SELECT {', '.join(keys)} FROM trades WHERE user IN ({','.join('?' * len(users))}) AND ({like}) "
                      "AND (status='open' OR closed_ts >= ?) ORDER BY COALESCE(closed_ts, opened_ts) DESC LIMIT 400",
                 (*users, *args, now - int(days) * D))
        trades = [dict(zip(keys, r)) for r in rows]
        ids = [t["id"] for t in trades]
        follow, mc = {}, {}
        if ids:
            ph = ",".join("?" * len(ids))
            if has_table(con, "pp_trades"):
                for tid, k, gid, w, b, emc in q(con, f"SELECT trade_id, kind, gid, wallet, mc_bucket, entry_mcap FROM "
                                                     f"pp_trades WHERE trade_id IN ({ph})", ids):
                    follow[tid] = ("bundle", gid, w) if k == "bundle" else ("group", gid, w)
                    mc[tid] = b or _bucket(emc)
            if has_table(con, "kopija_trades"):
                for tid, w, emc in q(con, f"SELECT trade_id, wallet, entry_mcap FROM kopija_trades WHERE trade_id IN "
                                          f"({ph})", ids):
                    follow[tid] = ("wallet", w)
                    mc[tid] = _bucket(emc)
            if has_table(con, "insajderi2_trades"):
                for tid, o, w, emc in q(con, f"SELECT trade_id, owner, wallet, entry_mcap FROM insajderi2_trades WHERE "
                                             f"trade_id IN ({ph})", ids):
                    follow[tid] = ("group", o, w)
                    mc[tid] = _bucket(emc)
    finally:
        con.close()
    for t in trades:
        t["follow"] = follow.get(t["id"])
        t["mc_bucket"] = mc.get(t["id"]) or "?"
        t["kind"] = next((p for p in prefixes if str(t["source"] or "").startswith(p)), "")
    opened = [t for t in trades if t["status"] == "open"]
    closed = [t for t in trades if t["status"] != "open"][:int(limit_closed)]
    return opened, closed


def demo_summary(prefixes=DEMO_SOURCES, days=14, path=None, now=None):
    """{"open", "closed", "from", "to", "stats"}: stats = insajderi/pp_live.day_stats (per source and MC bucket, the
    mean NET of the real round trip, never under 3 %: the data agent's daily line), the date range of the trades."""
    now = int(now or time.time())
    opened, closed = demo_trades(prefixes, 400, days, path, now)
    con = ro(path or league_db())
    st = {}
    try:
        if con is not None:
            from insajderi import pp_live
            st = pp_live.day_stats(con, now)
    except Exception:  # noqa: BLE001 - a missing table / module: no summary numbers
        st = {}
    finally:
        if con is not None:
            con.close()
    ts = [x for t in opened + closed for x in (t.get("opened_ts"), t.get("closed_ts")) if x]
    return {"open": len(opened), "closed": len(closed), "from": min(ts) if ts else None, "to": max(ts) if ts else None,
            "stats": st}


def group_of(con, owner):
    rows = q(con, f"SELECT {', '.join(GKEYS)} FROM i2_pp WHERE owner=?", (owner,))
    return _group(rows[0]) if rows else None


def i2_group_why(con, owner):
    """The Insajderi 2.0 group's own reason (i2_groups.why), when stored."""
    rows = q(con, "SELECT why, n_hits FROM i2_groups WHERE owner=?", (owner,))
    return rows[0] if rows else None


# ---------- Birdeye (insajderi/birdeye.py: a second source, report only) -----------------------------------------------

def birdeye(con, pp=None, now=None, limit=40):
    """{"key": the key is set in this process, "table": the tables exist, "calls", "cu", "cap" (this month),
    "tokens" (pump tokens read), "check": the summary block prije_pumpe.birdeye (groups_checked, groups_seen_in_top,
    share, tag_agree, tag_disagree) or {}, "cand": [{"owner", "n_tokens", "n15", "realized", "tags", "last_ts"}],
    "smart": [{"owner", "smart_n"}]}. Read-only; nothing is called."""
    now = int(now or time.time())
    out = {"key": bool(os.environ.get("BIRDEYE_API_KEY") or os.environ.get("BIRDEYE_PROXY_KEY") == "1"),
           "table": has_table(con, "be_tok"), "calls": 0, "cu": 0, "cap": None, "tokens": 0, "check": {}, "cand": [],
           "smart": []}
    try:
        from insajderi import birdeye as be, store
        out["cap"] = int(be.config(store.config()).get("cu_month"))
    except Exception:  # noqa: BLE001
        out["cap"] = None
    month = time.strftime("%Y-%m", time.gmtime(now))
    r = q(con, "SELECT calls, cu FROM be_usage WHERE month = ?", (month,))
    if r:
        out["calls"], out["cu"] = int(r[0][0] or 0), int(r[0][1] or 0)
    r = q(con, "SELECT COUNT(*) FROM be_tok")
    out["tokens"] = int(r[0][0] or 0) if r else 0
    b = (pp or {}).get("birdeye")
    out["check"] = b if isinstance(b, dict) else {}
    for o, n, n15, s, tg, last in q(con, "SELECT owner, n_tokens, n15, sum_realized_usd, tags, last_ts FROM be_cand "
                                         "WHERE n_tokens >= 3 ORDER BY n15 DESC, sum_realized_usd DESC LIMIT ?",
                                    (int(limit),)):
        out["cand"].append({"owner": o, "n_tokens": n, "n15": n15, "realized": s, "tags": _json(tg, []) or [],
                            "last_ts": last})
    out["smart"] = [{"owner": o, "smart_n": n} for o, n in q(con, "SELECT owner, smart_n FROM be_cand WHERE smart_n >= 2 "
                                                                  "ORDER BY smart_n DESC LIMIT ?", (int(limit),))]
    return out
