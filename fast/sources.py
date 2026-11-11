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
(closed >= 10, PnL > 0, >= 40 % winners), read from run_trade, never a second copy of the numbers. Wallets add their
wallets.db tier, score and labels; influencers their kol.db caller statistics (only kind 'call': n of measured calls,
EV after the 2 % cost, the minute check's hit rate +10 % before -20 % within 60 min, the Influenceri verdict;
ui/kandidati.caller_records). P's sample (hits, n) is the record with more closed outcomes of the two.
"""
import json
import os
import sqlite3
import time

from . import store

KINDS = ("wallet_follow", "insider", "pre_shill", "group", "influencer")
WALLET_KINDS = frozenset(KINDS[:4])
KIND_HR = {"wallet_follow": "praćeni novčanik", "insider": "insajder prije poziva", "pre_shill": "kupac prije shill mreže",
           "group": "skupina novčanika", "influencer": "influencer"}
PRIORITY = {"wallet_follow": 0, "influencer": 1, "insider": 1, "pre_shill": 2, "group": 2}
REFRESH_S = 60


def proof_rule():
    """run_trade.PROOF ({"closed": 10, "win_rate": 0.4}); league/copy.PROOF is its tested twin when run_trade cannot
    be imported (a test of the copy module keeps the two equal)."""
    try:
        from run_trade import PROOF
    except Exception:  # noqa: BLE001 - the worker must run without the trade process module
        from league.copy import PROOF
    return PROOF


def has_proof(closed, wins, pnl):
    """(proven?, why not) under run_trade.PROOF: closed >= 10, PnL > 0, winners >= 40 %."""
    P = proof_rule()
    closed, wins, pnl = int(closed or 0), int(wins or 0), float(pnl or 0)
    if closed < P["closed"]:
        return False, f"zatvorenih {closed} od potrebnih {P['closed']}"
    if pnl <= 0:
        return False, f"PnL {pnl:+.0f} $ nije iznad nule"
    if wins / closed < P["win_rate"]:
        return False, f"dobitnih {wins / closed:.0%}, treba {P['win_rate']:.0%}+"
    return True, None


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


def record(sid, kind, now=None, league_db=None):
    """{"closed", "wins", "pnl_usd", "follow_closed", "fast_closed"} of the source (see the module text)."""
    from league import store as lstore
    lc = _ro(league_db or lstore.DB)
    try:
        fids = _follow_ids(lc, sid, kind)
        fc = fw = 0
        fp = 0.0
        if fids:
            q = ",".join("?" * len(fids))
            r = _q(lc, f"SELECT COUNT(*), COALESCE(SUM(pnl_usd > 0), 0), COALESCE(SUM(pnl_usd), 0) FROM trades WHERE "
                       f"follow_id IN ({q}) AND status='closed'", fids)
            if r:
                fc, fw, fp = int(r[0][0]), int(r[0][1]), float(r[0][2])
        r = _q(lc, "SELECT COUNT(*), COALESCE(SUM(pnl_usd > 0), 0), COALESCE(SUM(pnl_usd), 0) FROM fast_trades WHERE "
                   "source_id=? AND status='closed'", (sid,))
        pc, pw, pp = (int(r[0][0]), int(r[0][1]), float(r[0][2])) if r else (0, 0, 0.0)
    finally:
        if lc is not None:
            lc.close()
    return {"closed": fc + pc, "wins": fw + pw, "pnl_usd": round(fp + pp, 2), "follow_closed": fc, "fast_closed": pc,
            "follow_ids": fids}


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


def caller_info(handle, now):
    """kol.db caller statistics of one account (ui/kandidati.caller_records: only kind 'call'), {} when unknown."""
    try:
        from ui import kandidati
        return kandidati.caller_records([handle], now).get(handle) or {}
    except Exception:  # noqa: BLE001 - no kol.db / minute.db: unknown
        return {}


def quality(sig, now=None, league_db=None):
    """Check e's numbers for one signal: the record, proof, tier / caller statistics and P's sample (hits, n)."""
    now = int(now or time.time())
    sid, kind = sig["source_id"], sig.get("kind")
    rec = record(sid, kind, now, league_db)
    ok, why = has_proof(rec["closed"], rec["wins"], rec["pnl_usd"])
    q = {"kind": kind, "kind_hr": KIND_HR.get(kind, kind), "id": sid, "label": sig.get("source_label"),
         "closed": rec["closed"], "wins": rec["wins"], "pnl_usd": rec["pnl_usd"],
         "win_rate": round(rec["wins"] / rec["closed"], 3) if rec["closed"] else None,
         "follow_closed": rec["follow_closed"], "fast_closed": rec["fast_closed"], "proof": ok, "proof_why": why,
         "hits": rec["wins"], "n": rec["closed"], "sample": "zapis praćenja + fast paper"}
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
        if n_min > q["n"] and hit10 is not None:   # the caller's measured calls are the bigger sample for P
            q.update(hits=int(round(hit10 * n_min)), n=n_min,
                     sample="minutna provjera poziva (+10 % prije −20 % u 60 min)")
    return q
