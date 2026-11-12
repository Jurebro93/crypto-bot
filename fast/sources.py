"""Who the fast path listens to, and how good each source has been (check e).

Followed sources (refresh(): every REFRESH_S into fast.db sources, so a webhook hook answers "is this wallet ours?"
with one indexed read):
  wallet_follow  the Autopilot accounts' active wallet follows (league.db follows kind wallet; LEAGUE_USER's follow id
                 first: the evidence run_trade asks before real money)
  influencer     the Autopilot accounts' KOL follows and every member of a crew follow (X handles, tg:channels)
  insider        kol/precall confirmed pre-call wallets (early.db precall_wallets status confirmed)
  pre_shill      kol/preshill confirmed wallets (early.db preshill_wallets status confirmed)
  group          members of kol/groupdisc wallet groups graded quality (early.db group_member / group_list)
A wallet in several lists keeps the first kind in that order. Nothing here calls an API.

The record (quality): the source's closed trades: its Autopilot follow's closed demo copies (league.db trades by
follow_id, the same rows run_trade._no_proof counts) plus the fast path's own closed paper trades of that source
(league.db fast_trades), so the proof builds itself from the paper trades (Jure, point 4). Proof = run_trade.PROOF
(11.11. owner's rule D: trade/edge.live_proof on the closed results, each pnl / stake net of the calibrated cost:
n >= 10, EV >= +3 %, the 90 % interval's lower bound > 0; the old ">= 40 % winners" is gone), read from run_trade,
never a second copy of the numbers. Wallets add their
wallets.db tier, score and labels; influencers their kol.db caller statistics (only kind 'call': n of measured calls,
EV after the cost model's fee part, the Influenceri verdict; ui/kandidati.caller_records) and, 11.11. (owner's rule E),
their benchmark on the fast exit itself: +15 % before -10 % within 45 min (proposals.db bench, kol/tpsl over minute.db,
computed nightly). P's sample (hits, n) is the record with more closed outcomes of the two.
"""
import json
import os
import sqlite3
import time

from . import store

KINDS = ("wallet_follow", "insider", "pre_shill", "group", "influencer", "proven", "convergence", "tool", "x_call")
# 11.11. (Jure: every live candidate gets a fast_check): "proven" = a wallets/dokazani wallet whose buy put a token on
# the live list (ui/zivo smart buys), "convergence" = several sources on one token (kol/converge; the pseudo-source
# CONVERGENCE, enqueued by the worker's scan of kol.db converge), "tool" = a live pick of the tool itself (topcheck /
# the Pregled box) with no wallet / call / convergence behind it (fast/live.ensure). The last three come only from the
# live list and the scan, never from the hooks' followed-source list (except CONVERGENCE, refreshed below).
# 12.11.: "x_call" = an X post Grok sent with the MCP tool submit_watch_token (fast/xcall.py; the author's handle is the
# source id); checked in run_ui.py at once and never traded (fast/paper and the proposals skip the kind).
WALLET_KINDS = frozenset(KINDS[:4] + ("proven",))
KIND_HR = {"wallet_follow": "praćeni novčanik", "insider": "insajder prije poziva", "pre_shill": "kupac prije shill mreže",
           "group": "skupina novčanika", "influencer": "influencer", "proven": "dokazani novčanik",
           "convergence": "konvergencija izvora", "tool": "živi kandidat alata", "x_call": "X poziv (Grok)"}
PRIORITY = {"wallet_follow": 0, "influencer": 1, "insider": 1, "proven": 1, "convergence": 1, "pre_shill": 2, "group": 2,
            "tool": 3, "x_call": 1}
CONVERGENCE = "konvergencija"
TOOL = "alat"
REFRESH_S = 60


def proof_rule():
    """run_trade.PROOF ({"closed": 10, "ev_min": 0.03, "ci_lo_min": 0.0}); league/copy.PROOF is its tested twin when
    run_trade cannot be imported (a test of the copy module keeps the two equal)."""
    try:
        from run_trade import PROOF
    except Exception:  # noqa: BLE001 - the worker must run without the trade process module
        from league.copy import PROOF
    return PROOF


def has_proof(rets):
    """(proven?, why not) under run_trade.PROOF: trade/edge.live_proof on the closed results (fractions of the stake,
    net of cost): n >= 10, EV >= +3 %, the 90 % interval's lower bound > 0. No win-rate rule."""
    from trade import edge
    P = proof_rule()
    ok, why, _s = edge.live_proof(rets, n_min=P["closed"], ev_min=P["ev_min"])
    return ok, why


def _ro(path):
    if not path or not os.path.exists(path) or not os.path.getsize(path):
        return None
    try:
        return sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5)
    except sqlite3.Error:
        return None


def _q(con, sql, args=()):
    if con is None:
        return []
    try:
        return con.execute(sql, args).fetchall()
    except sqlite3.Error:
        return []


def _short(w):
    return f"{w[:4]}…{w[-4:]}" if w and len(w) > 12 else (w or "")


def collect(league_db=None, early_db=None):
    """{source id: {"kind", "label", "follow_id"}} of every followed source (see the module text)."""
    from league import copy as lcopy, store as lstore
    from trade import settings as ts
    out = {}

    def put(sid, kind, label, fid=None):
        if not sid:
            return
        for k in dict.fromkeys((sid, sid.lower() if kind == "influencer" else sid)):
            out.setdefault(k, {"kind": kind, "label": label or _short(sid), "follow_id": fid})
    lc = _ro(league_db or lstore.DB)
    try:
        for fid, _user, kind, target, label in _q(lc, "SELECT id, user, kind, target, label FROM follows WHERE active=1 "
                                                      "AND user IN (?,?) ORDER BY (user != ?), id",
                                                  (ts.LEAGUE_USER, ts.PAPER_USER, ts.LEAGUE_USER)):
            if kind == "wallet":
                put(target, "wallet_follow", label, fid)
            elif kind == "kol":
                put(target.lstrip("@"), "influencer", label or target, fid)
            elif kind == "ekipa":
                for m in lcopy.members_of(target):
                    if not m.startswith("w:"):
                        put(m, "influencer", m, fid)
    finally:
        if lc is not None:
            lc.close()
    try:
        from kol import groupdisc
        ep = early_db or groupdisc.db_path()
    except Exception:  # noqa: BLE001
        groupdisc, ep = None, early_db
    ec = _ro(ep)
    try:
        for (w,) in _q(ec, "SELECT wallet FROM precall_wallets WHERE status = 'confirmed'"):
            put(w, "insider", f"insajder {_short(w)}")
        for (w,) in _q(ec, "SELECT wallet FROM preshill_wallets WHERE status = 'confirmed'"):
            put(w, "pre_shill", f"prije shill mreže {_short(w)}")
        if ec is not None and groupdisc is not None:
            try:
                member_of, grades, _owner = groupdisc.load_groups(ec, "wallet")
            except Exception:  # noqa: BLE001 - groupdisc changes in parallel: no group sources this time
                member_of, grades = {}, {}
            for w, g in member_of.items():
                if grades.get(g) == "quality":
                    put(w, "group", f"skupina {str(g)[:8]}")
    finally:
        if ec is not None:
            ec.close()
    put(CONVERGENCE, "convergence", "konvergencija izvora")   # 11.11.: the kol.db converge rows (worker scan)
    return out


def refresh(con, now=None, got=None):
    """fast.db sources := collect() (one transaction). Returns how many."""
    now = int(now or time.time())
    got = collect() if got is None else got
    con.execute("DELETE FROM sources")
    con.executemany("INSERT OR REPLACE INTO sources VALUES (?,?,?,?,?)",
                    [(k, v["kind"], v.get("label"), v.get("follow_id"), now) for k, v in got.items()])
    store.kv_put(con, "sources_ts", now)
    con.commit()
    return len(got)


def lookup(con, ids):
    """{id: {"kind", "label", "follow_id"}} of the given ids that are followed sources (fast.db sources)."""
    ids = [i for i in dict.fromkeys(ids or ()) if i]
    out = {}
    for i in range(0, len(ids), 500):
        part = ids[i:i + 500]
        q = ",".join("?" * len(part))
        for sid, kind, label, fid in _q(con, f"SELECT id, kind, label, follow_id FROM sources WHERE id IN ({q})", part):
            out[sid] = {"kind": kind, "label": label, "follow_id": fid}
    return out


# ---------- the record (check e) -------------------------------------------------------------------------------------

def _follow_ids(lc, sid, kind):
    """LEAGUE_USER's active-or-not follows of this target (wallet / handle / a crew containing it)."""
    from trade import settings as ts
    if kind in WALLET_KINDS:
        return [f for (f,) in _q(lc, "SELECT id FROM follows WHERE user=? AND kind='wallet' AND target=?",
                                 (ts.LEAGUE_USER, sid))]
    out = [f for (f,) in _q(lc, "SELECT id FROM follows WHERE user=? AND kind='kol' AND lower(target)=lower(?)",
                            (ts.LEAGUE_USER, sid))]
    for f, target in _q(lc, "SELECT id, target FROM follows WHERE user=? AND kind='ekipa'", (ts.LEAGUE_USER,)):
        if sid.lower() in {m.lower() for m in (target or "").split(",")}:
            out.append(f)
    return out


def _rets(rows):
    """[(pnl_usd, stake_usd)] -> closed results as fractions of the stake, net of the calibrated cost (the demo books
    league/store.FEE a side: trade/cost.demo_adjust)."""
    from trade import cost
    adj = cost.demo_adjust()
    return [float(p) / float(s) + adj for p, s in rows if p is not None and s]


def record(sid, kind, now=None, league_db=None):
    """{"closed", "wins", "pnl_usd", "rets", "follow_closed", "fast_closed"} of the source (see the module text)."""
    from league import store as lstore
    lc = _ro(league_db or lstore.DB)
    try:
        fids = _follow_ids(lc, sid, kind)
        fr = []
        if fids:
            q = ",".join("?" * len(fids))
            fr = _q(lc, f"SELECT pnl_usd, size_usd FROM trades WHERE follow_id IN ({q}) AND status='closed'", fids)
        pr = _q(lc, "SELECT pnl_usd, size_usd FROM fast_trades WHERE source_id=? AND status='closed'", (sid,))
    finally:
        if lc is not None:
            lc.close()
    rows = list(fr) + list(pr)
    return {"closed": len(rows), "wins": sum(1 for p, _s in rows if (p or 0) > 0),
            "pnl_usd": round(sum(p or 0 for p, _s in rows), 2), "rets": _rets(rows), "follow_closed": len(fr),
            "fast_closed": len(pr), "follow_ids": fids}


def wallet_info(w, wallet_db=None):
    """{"tier", "score", "labels", "win_rate", "trades_per_day"} from wallets.db, {} when unknown."""
    try:
        from wallets import store as wstore
        path = wallet_db or wstore.DB
    except Exception:  # noqa: BLE001
        return {}
    wc = _ro(path)
    try:
        r = _q(wc, "SELECT tier, score, labels, stats FROM wallets WHERE wallet=?", (w,))
    finally:
        if wc is not None:
            wc.close()
    if not r:
        return {}
    tier, score, labels, stats = r[0]
    try:
        st = json.loads(stats or "{}") or {}
    except ValueError:
        st = {}
    try:
        lab = json.loads(labels or "[]") or []
    except ValueError:
        lab = []
    return {"tier": tier, "score": score, "labels": lab, "win_rate": st.get("win_rate"),
            "trades_per_day": st.get("trades_per_day")}


def rang_info(sid, kind):
    """{"n", "wins", "win", "win_lo", "proven", "copyable", "score"} of the source in wallets/rang.py (the copy rank,
    PR #129: a wallet's closed tokens, an influencer's calls of kind 'call'), {} when not ranked or unreadable."""
    try:
        from wallets import rang
        r = rang.get("wallet" if kind in WALLET_KINDS else "kol", sid)
    except Exception:  # noqa: BLE001 - no wallets.db / table yet: unknown
        return {}
    if not r:
        return {}
    return {k: r.get(k) for k in ("n", "wins", "win", "win_lo", "proven", "copyable", "score")}


def caller_info(handle, now):
    """kol.db caller statistics of one account (ui/kandidati.caller_records: only kind 'call'), {} when unknown."""
    try:
        from ui import kandidati
        return kandidati.caller_records([handle], now).get(handle) or {}
    except Exception:  # noqa: BLE001 - no kol.db / minute.db: unknown
        return {}


def caller_bench(handle):
    """{"n", "hits"} of the caller's +15 / -10 / 45 min benchmark (proposals.db bench), {} when unknown."""
    try:
        from proposals import build
        b = build.Sources().bench([handle]) or {}
    except Exception:  # noqa: BLE001 - no proposals.db yet: unknown
        return {}
    return b.get(handle) or b.get(str(handle).lower()) or {}


def quality(sig, now=None, league_db=None):
    """Check e's numbers for one signal: the record, proof, tier / caller statistics and P's sample (hits, n)."""
    now = int(now or time.time())
    sid, kind = sig["source_id"], sig.get("kind")
    if kind == "x_call" and str(sid).startswith("x:"):   # 12.11.: an x_call's source id is "x:<handle>"
        sid = sid[2:]
    from trade import edge
    rec = record(sid, kind, now, league_db)
    ok, why = has_proof(rec["rets"])
    st = edge.ev_stats(rec["rets"])
    q = {"kind": kind, "kind_hr": KIND_HR.get(kind, kind), "id": sig["source_id"], "label": sig.get("source_label"),
         "closed": rec["closed"], "wins": rec["wins"], "pnl_usd": rec["pnl_usd"],
         "ev_pct": round(st["ev"] * 100, 2) if st["ev"] is not None else None,
         "ev_lo90_pct": round(st["lo90"] * 100, 2) if st["lo90"] is not None else None,
         "win_rate": round(rec["wins"] / rec["closed"], 3) if rec["closed"] else None,
         "follow_closed": rec["follow_closed"], "fast_closed": rec["fast_closed"], "proof": ok, "proof_why": why,
         "hits": rec["wins"], "n": rec["closed"], "sample": "zapis praćenja + fast paper"}
    if kind in ("convergence", "tool"):   # 11.11.: pseudo-sources, their record is the fast paper trades of the kind
        return q
    rg = rang_info(sid, kind)
    if rg:   # 11.11. (PR #129): the copy rank's closed tokens / calls, one of P's samples (fast/estimate.sample)
        q["rang"] = rg
    if kind in WALLET_KINDS:
        wi = wallet_info(sid)
        q.update(tier=wi.get("tier"), score=wi.get("score"), labels=wi.get("labels") or [],
                 wallet_win_rate=wi.get("win_rate"))
    else:
        ci = caller_info(sid, now)
        n_min, hit10 = int(ci.get("minute_n") or 0), ci.get("hit10")
        q.update(tier=ci.get("verdict_hr"), calls_n=ci.get("ev_n"), calls_ev_pct=(round(ci["ev_mean"] * 100, 2)
                                                                                  if ci.get("ev_mean") is not None else None),
                 hit_rate=hit10, minute_n=n_min)
        bn = caller_bench(sid)
        if bn:
            q["bench"] = {"n": int(bn.get("n") or 0), "hits": int(bn.get("hits") or 0)}
        if int(bn.get("n") or 0) > q["n"]:   # the caller's measured calls on the fast exit are the bigger sample for P
            q.update(hits=int(bn.get("hits") or 0), n=int(bn["n"]),
                     sample="brzi izlaz callera (+15 % prije −10 % u 45 min, proposals bench)")
    return q
