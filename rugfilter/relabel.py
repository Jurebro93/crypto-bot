"""Rug labels again, under the pool rule (11.11. evening, Jure: "Retroaktivno ponovi oznake za zadnjih 7 dana i javi
koliko se tokena prebacilo iz 'rug' u 'dump'"). Nothing is deleted or rewritten: every label goes NEXT to the old one,
into hype.db rug_relabel (token, src):
  old_kind  the 11.11. noon rule (USD liquidity more than 50 % down = rug; collapse.judge_usd, archive.kind_usd)
  new_kind  the pool rule (rugfilter/collapse.judge: the pool invariant L fell 50 %+, or 70 %+ down with evidence)
  sol_kind  the owner's literal words (the SOL side -50 %, collapse.literal_kind), for the comparison
  with the falls behind them (pad, liq_pad, l_pad, sol_pad) and the reason. rugfilter/archive.kinds reads new_kind for
  archived tokens.

Sources: every place a rug label was stored or shown in the DAYS window.
  archive   hype.db rug_archive rows archived in the window ("srusen" / "likvidnost"; "mehanika" stays a rug and is
            only counted): old = archive.kind_usd of the stored row; new = the pool rule at the token's last point
            against its whole kept history (the archive keeps two snapshots per hour), else on the row's own peak /
            last numbers (collapse.approx_pool). note_archived() writes the same row for every token the hourly run
            archives from now on, before its history is purged.
  collapse  tokens of hype_signals / token_pulse in the window (what ui/kandidati, league/copy, run_paper and fast
            computed live from collapse.peaks), plus the tokens of paper.db's 'skip_rug' decisions "rugan: ..." and X
            (CccS…y1eU) when it is in the data: every point (thinned to the last, highest and lowest of each 10 min)
            against the 24 h peaks before it; a token's label is the worst it had in the window.
retro_once() runs once (rug_relabel_runs row RULE) inside the hourly rug archive process (start.sh: 2 min after a
start, under the heavy-job lock, low priority), bounded by BUDGET_S, and prints ONE log block "rug pravilo (pool
invariant) 7 dana: ...". Pretpostavke it states: L from the USD numbers with the day's SOL price where no SOL side was
stored (before 11.11. evening none was), a pool of unknown kind counted as CP (PumpSwap), the evidence (dev, holders,
rug filter) as it is today.
"""
import collections
import math
import os
import sqlite3
import time

from rugfilter import collapse

RULE = "pool_v1"
DAYS = 7
SLOT_S = 600
BUDGET_S = float(os.environ.get("RUG_RELABEL_BUDGET_S", "300"))
X_HEAD, X_TAIL = "CccS", "y1eU"
RANK = {None: 0, "dump": 1, "rug": 2}
COLS = ("token", "src", "ts", "symbol", "old_kind", "new_kind", "sol_kind", "pad", "liq_pad", "l_pad", "sol_pad", "cp",
        "reason", "rule", "relabeled_ts")
SCHEMA = """
CREATE TABLE IF NOT EXISTS rug_relabel (
    token TEXT, src TEXT, ts INTEGER, symbol TEXT, old_kind TEXT, new_kind TEXT, sol_kind TEXT, pad REAL,
    liq_pad REAL, l_pad REAL, sol_pad REAL, cp INTEGER, reason TEXT, rule TEXT, relabeled_ts INTEGER,
    PRIMARY KEY (token, src));
CREATE TABLE IF NOT EXISTS rug_relabel_runs (rule TEXT PRIMARY KEY, ts INTEGER, summary TEXT);
"""


def short(m):
    return f"{m[:4]}…{m[-4:]}" if m and len(m) > 10 else (m or "?")


# ---------- one token's points -----------------------------------------------------------------------------------
def points(con, token, since=None, until=None):
    """[(ts, mcap, liq)] by ts from hype_signals, token_pulse and hype_snapshots (each read by its (token, ts) key);
    points without a market cap are left out."""
    since = int(since or 0)
    until = int(until or 2 ** 40)
    out = []
    for table in ("hype_signals", "token_pulse", "hype_snapshots"):
        try:
            out += con.execute(f"SELECT ts, mcap, liquidity FROM {table} WHERE token=? AND ts BETWEEN ? AND ?",
                               (token, since, until)).fetchall()
        except sqlite3.OperationalError:
            continue
    return sorted((int(t), float(m), float(lq or 0)) for t, m, lq in out if t and m and m > 0)


def thin(pts, slot=SLOT_S):
    """The last, the highest and the lowest point of every slot, in time order (a 2-minute pulse over 7 days is
    5,000 points; the labels are about 50-85 % moves)."""
    by = collections.OrderedDict()
    for p in pts:
        by.setdefault(p[0] // slot, []).append(p)
    out = []
    for grp in by.values():
        keep = {grp[-1], max(grp, key=lambda p: p[1]), min(grp, key=lambda p: p[1])}
        out += sorted(keep)
    return out


class _Max:
    """Sliding-window maximum (monotonic deque)."""

    def __init__(self):
        self.q = collections.deque()

    def push(self, ts, v):
        while self.q and self.q[-1][1] <= v:
            self.q.pop()
        self.q.append((ts, v))

    def expire(self, ts_min):
        while self.q and self.q[0][0] < ts_min:
            self.q.popleft()

    def top(self):
        return self.q[0][1] if self.q else 0.0


def judge_point(pm, m, pl, liq, plu, lu, pls, ls, evidence, cp=None):
    """(old, new, sol, detail) at one point: old = the 11.11. noon rule, new = the pool rule, sol = the literal rule."""
    if not pm or pm < collapse.MIN_PEAK_MCAP:
        return None, None, None, None
    drop = 1 - m / pm
    l_drop = 1 - lu / plu if plu and lu else (1.0 if plu and liq <= 0 else None)
    sol_drop = 1 - ls / pls if pls else None
    o = collapse.judge_usd(pm, m, pl or None, liq, evidence)
    n = collapse.judge(pm, m, pl or None, liq, evidence,
                       pool={"l_drop": l_drop, "sol_drop": sol_drop, "cp": cp, "src": "usd", "empty": liq <= 0})
    s = collapse.literal_kind(drop, sol_drop, evidence)
    det = {"pad": drop, "liq_pad": (1 - liq / pl) if pl else None, "l_pad": l_drop, "sol_pad": sol_drop,
           "reason": (n or o or {}).get("text")}
    return (o or {}).get("kind"), (n or {}).get("kind"), s, det


def evaluate(pts, token=None, window_s=collapse.WINDOW_H * 3600, since=None, evidence_fn=None):
    """{"old", "new", "sol", "ts", detail...}: the worst label of each rule over the points from `since` on, every point
    against the peaks of the window_s before it (None: the whole history). evidence_fn(token) is asked once, only when
    a point fell DROP or more (it turns a dump into a rug under every rule)."""
    pts = thin(pts)
    mx = [_Max() for _ in range(4)]   # mcap, liq, L (USD-based), SOL side
    best = {"old": None, "new": None, "sol": None, "ts": None}
    worst_pad = -1.0
    ev, asked = None, False
    for ts, m, liq in pts:
        sol = collapse.sol_usd_at(ts)
        lu = liq / math.sqrt(m * sol) if liq > 0 else 0.0
        ls = liq / 2 / sol if liq > 0 else 0.0
        for q, v in zip(mx, (m, liq, lu, ls)):
            q.push(ts, v)
            if window_s is not None:
                q.expire(ts - window_s)
        if since is not None and ts < since:
            continue
        pm, pl, plu, pls = (q.top() for q in mx)
        if pm < collapse.MIN_PEAK_MCAP:
            continue
        drop = 1 - m / pm
        if drop < 1 - collapse.RECOVER and not (plu and lu and lu / plu <= 1 - collapse.LIQ_RUG) \
                and not (pls and ls / pls <= 1 - collapse.LIQ_RUG) and not (pl and liq / pl < 1 - collapse.LIQ_RUG):
            continue   # no rule can label this point: skip the judging
        if drop >= collapse.DROP and not asked and evidence_fn and token:
            asked, ev = True, evidence_fn(token)
        o, n, s, det = judge_point(pm, m, pl, liq, plu, lu, pls, ls, ev)
        if o is None and n is None and s is None:
            continue
        for k, v in (("old", o), ("new", n), ("sol", s)):
            if RANK[v] > RANK[best[k]]:
                best[k] = v
        if det["pad"] > worst_pad:
            worst_pad = det["pad"]
            best.update(det, ts=ts)
    return best


# ---------- the archive rows -------------------------------------------------------------------------------------
def archive_row_labels(con, row, now=None):
    """{"old", "new", "sol", ...} of one rug_archive row (dict) on the token's kept history, whole-history peaks."""
    from rugfilter import archive
    old = archive.kind_usd(row["kind"], row.get("peak_liq"), row.get("last_liq"))
    if (row.get("last_mcap") or 0) <= 0 and (row.get("last_liq") or 0) <= 0:   # the pair vanished: still a rug
        return {"old": old, "new": "rug", "sol": "rug", "pad": 1.0, "liq_pad": 1.0, "l_pad": 1.0, "sol_pad": 1.0,
                "reason": row.get("reason") or "par nestao s DEX-a", "ts": row.get("archived_ts")}
    pts = points(con, row["token"])
    out = None
    if len([p for p in pts if p[2] > 0]) >= 2:
        last = pts[-1][0]
        out = evaluate(pts, row["token"], window_s=None, since=last, evidence_fn=collapse.rug_evidence)
        if out["new"] is None and out["old"] is None and out["sol"] is None:
            out = None   # the kept history does not show the fall the archive saw: its own numbers below
    if out is None:
        pm, lm, pl, ll = row.get("peak_mcap"), row.get("last_mcap"), row.get("peak_liq"), row.get("last_liq")
        j = collapse.judge(pm, lm, pl, ll) if pm and lm is not None else None
        drop = 1 - lm / pm if pm and lm is not None else None
        pool = collapse.approx_pool(pm, lm, pl, ll) if pm else {}
        out = {"new": archive.kind_of(row["kind"], pl, ll, pm, lm), "sol": collapse.literal_kind(drop, pool.get("sol_drop")),
               "pad": drop, "liq_pad": (1 - (ll or 0) / pl) if pl and ll is not None else None,
               "l_pad": pool.get("l_drop"), "sol_pad": pool.get("sol_drop"),
               "reason": (j or {}).get("text") or row.get("reason"), "ts": row.get("archived_ts")}
    if row["kind"] != "srusen" and out.get("new") is None:
        out["new"] = "dump"   # an archived token is never unlabelled: at worst a dump (P x 0.7, no block)
    out["old"] = old
    return out


def note_archived(con, cands, now=None, log=None):
    """The hourly archive run: one rug_relabel row (src 'archive') per collapse it archives now, from its history
    before the purge. cands: archive.candidates() tuples. Returns rows written."""
    now = int(now or time.time())
    con.executescript(SCHEMA)
    n = 0
    for t, kind, reason, st in cands:
        if kind not in ("srusen", "likvidnost"):
            continue
        row = {"token": t, "kind": kind, "reason": reason, "archived_ts": now, **{k: st.get(k) for k in
               ("symbol", "peak_mcap", "last_mcap", "peak_liq", "last_liq")}}
        lab = archive_row_labels(con, row, now)
        write(con, t, "archive", lab, st.get("symbol"), now)
        n += 1
    con.commit()
    return n


def write(con, token, src, lab, symbol, now):
    con.execute(f"INSERT OR REPLACE INTO rug_relabel ({', '.join(COLS)}) VALUES ({','.join('?' * len(COLS))})",
                (token, src, lab.get("ts"), symbol, lab.get("old"), lab.get("new"), lab.get("sol"),
                 _r(lab.get("pad")), _r(lab.get("liq_pad")), _r(lab.get("l_pad")), _r(lab.get("sol_pad")), None,
                 (lab.get("reason") or "")[:300], RULE, int(now)))


def _r(x):
    return None if x is None else round(float(x), 4)


# ---------- the retroactive pass ---------------------------------------------------------------------------------
def _prefilter(con, since, budget_end):
    """{token} whose 7 days (plus the day before) hold a 50 %+ fall of the market cap, the liquidity or the USD-based L
    (order ignored: a superset), from one pass over hype_signals (its ts index) and token_pulse."""
    acc = {}
    for table in ("hype_signals", "token_pulse"):
        try:
            cur = con.execute(f"SELECT token, mcap, liquidity FROM {table} WHERE ts >= ?", (int(since),))
        except sqlite3.OperationalError:
            continue
        i = 0
        for t, m, liq in cur:
            i += 1
            if i % 50000 == 0 and time.monotonic() > budget_end:
                break
            if not m or m <= 0:
                continue
            liq = liq or 0
            lu = liq / math.sqrt(m) if liq > 0 else 0.0
            a = acc.get(t)
            if a is None:
                acc[t] = [m, m, liq, liq, lu, lu]
            else:
                if m > a[0]:
                    a[0] = m
                if m < a[1]:
                    a[1] = m
                if liq > a[2]:
                    a[2] = liq
                if liq < a[3]:
                    a[3] = liq
                if lu > a[4]:
                    a[4] = lu
                if lu < a[5]:
                    a[5] = lu
    return {t for t, a in acc.items() if a[0] >= collapse.MIN_PEAK_MCAP and (
        a[1] <= a[0] * (1 - collapse.RECOVER) or a[3] <= a[2] * (1 - collapse.LIQ_RUG)
        or a[5] <= a[4] * (1 - collapse.LIQ_RUG))}


def _paper_rugan(paper_db, since):
    """{token} of paper.db's 'skip_rug' decisions labelled "rugan: ..." (the demo's stored rug labels) of tokens first
    seen at most a week before `since`."""
    if not paper_db or not os.path.exists(paper_db):
        return set()
    try:
        con = sqlite3.connect(f"file:{paper_db}?mode=ro", uri=True, timeout=10)
    except sqlite3.Error:
        return set()
    try:
        # one row per token with its newest decision (paper/store); first_ts bounds it to tokens of about the window
        return {t for (t,) in con.execute("SELECT token FROM candidates WHERE decision='skip_rug' AND "
                                          "reason LIKE 'rugan:%' AND first_ts >= ?", (int(since) - 7 * 86400,))}
    except sqlite3.Error:
        return set()
    finally:
        con.close()


def find_x(con):
    """The full mint of X (CccS…y1eU) from what hype.db holds, else None."""
    for sql in ("SELECT token FROM token_tier WHERE token LIKE ? LIMIT 1",
                "SELECT token FROM rug_archive WHERE token LIKE ? LIMIT 1",
                "SELECT token FROM token_status WHERE token LIKE ? LIMIT 1",
                "SELECT token FROM hype_snapshots WHERE token LIKE ? LIMIT 1"):
        try:
            r = con.execute(sql, (f"{X_HEAD}%{X_TAIL}",)).fetchone()
        except sqlite3.OperationalError:
            continue
        if r and r[0].startswith(X_HEAD) and r[0].endswith(X_TAIL):
            return r[0]
    return None


def _symbols(con, tokens):
    out = {}
    toks = list(tokens)
    for i in range(0, len(toks), 400):
        part = toks[i:i + 400]
        q = ",".join("?" * len(part))
        for table in ("token_tier", "rug_archive"):
            try:
                for t, s in con.execute(f"SELECT token, symbol FROM {table} WHERE token IN ({q})", part):
                    if s and t not in out:
                        out[t] = s
            except sqlite3.OperationalError:
                continue
    return out


def retro(path, now=None, days=DAYS, paper_db=None, budget_s=None, log=print, evidence_fn=None):
    """The labels of the last `days` days again (module text); writes rug_relabel rows (never deletes) and returns
    the summary dict (the log block is lines(summary))."""
    now = int(now or time.time())
    t0 = time.monotonic()
    budget_end = t0 + (BUDGET_S if budget_s is None else budget_s)
    since = now - days * 86400
    evidence_fn = evidence_fn or collapse.rug_evidence
    con = sqlite3.connect(path, timeout=60)
    con.execute("PRAGMA busy_timeout=60000")
    con.executescript(SCHEMA)
    res = {}          # token -> (src, labels)
    partial = False
    mech = 0
    try:
        # 1. the archive
        try:
            con.row_factory = sqlite3.Row
            rows = [dict(r) for r in con.execute("SELECT * FROM rug_archive WHERE archived_ts >= ?", (since,))]
        except sqlite3.OperationalError:
            rows = []
        finally:
            con.row_factory = None
        archived = set()
        try:
            archived = {t for (t,) in con.execute("SELECT token FROM rug_archive")}
        except sqlite3.OperationalError:
            pass
        for r in rows:
            if r["kind"] == "mehanika":
                mech += 1
                continue
            if time.monotonic() > budget_end:
                partial = True
                break
            res[r["token"]] = ("archive", archive_row_labels(con, r, now), r.get("symbol"))
        # 2. what collapse computed live: hype_signals / token_pulse, the demo's "rugan" decisions, X
        x = find_x(con)
        paper = _paper_rugan(paper_db, since)
        cands = (_prefilter(con, since - collapse.WINDOW_H * 3600, budget_end) | paper | ({x} if x else set())) - archived
        for t in sorted(cands):
            if time.monotonic() > budget_end:
                partial = True
                break
            pts = points(con, t, since - collapse.WINDOW_H * 3600, now)
            lab = evaluate(pts, t, since=since, evidence_fn=evidence_fn)
            if lab["old"] is None and lab["new"] is None and lab["sol"] is None and t != x:
                continue
            res[t] = ("collapse", lab, None)
        syms = _symbols(con, [t for t, v in res.items() if not v[2]])
        for t, (src, lab, sym) in res.items():
            write(con, t, src, lab, sym or syms.get(t), now)
        summary = summarize(res, syms, paper, mech, x, partial, round(time.monotonic() - t0, 1), days)
        con.execute("INSERT OR REPLACE INTO rug_relabel_runs VALUES (?,?,?)",
                    (RULE, now, str({k: v for k, v in summary.items() if not isinstance(v, list)})[:2000]))
        con.commit()
    finally:
        con.close()
    return summary


def summarize(res, syms, paper, mech, x, partial, took, days=DAYS):
    c = collections.Counter()
    moved = {"rug_dump": [], "dump_rug": []}
    for t, (src, lab, sym) in res.items():
        o, n, s = lab.get("old"), lab.get("new"), lab.get("sol")
        if o is None and n is None and s is None:
            continue
        c["n"] += 1
        c[f"src_{src}"] += 1
        c[f"{o}->{n}"] += 1
        c[f"sol_{s}"] += 1
        if s == "rug" and n == "dump":
            c["sol_rug_pool_dump"] += 1
        item = {"token": t, "symbol": sym or syms.get(t), "pad": lab.get("pad"), "l_pad": lab.get("l_pad"),
                "sol_pad": lab.get("sol_pad"), "src": src, "old": o, "new": n, "sol": s}
        if o == "rug" and n == "dump":
            moved["rug_dump"].append(item)
        elif o == "dump" and n == "rug":
            moved["dump_rug"].append(item)
    for k in moved:
        moved[k].sort(key=lambda i: -(i["pad"] or 0))
    paper_now_dump = sum(1 for t in paper if t in res and res[t][1].get("new") == "dump")
    xl = None
    if x:
        lab = res.get(x, (None, {}, None))[1]
        xl = {"token": x, "old": lab.get("old"), "new": lab.get("new"), "sol": lab.get("sol"), "pad": lab.get("pad"),
              "l_pad": lab.get("l_pad"), "sol_pad": lab.get("sol_pad"), "in_data": x in res}
    return {"n": c["n"], "rug_dump": c["rug->dump"], "dump_rug": c["dump->rug"], "rug_rug": c["rug->rug"],
            "rug_none": c["rug->None"], "none_rug": c["None->rug"], "dump_dump": c["dump->dump"],
            "dump_none": c["dump->None"], "none_dump": c["None->dump"], "sol_rug": c["sol_rug"],
            "sol_dump": c["sol_dump"], "sol_rug_pool_dump": c["sol_rug_pool_dump"], "src_archive": c["src_archive"],
            "src_collapse": c["src_collapse"], "mehanika": mech, "paper": len(paper), "paper_now_dump": paper_now_dump,
            "x": xl, "partial": partial, "took_s": took, "days": days,
            "list_rug_dump": moved["rug_dump"], "list_dump_rug": moved["dump_rug"]}


def _p(x):
    if x is None:
        return "?"
    v = -x * 100
    return "0 %" if abs(v) < 0.5 else f"{v:+.0f} %"


def _item(i):
    sym = f"{i['symbol']} " if i.get("symbol") else ""
    return (f"{sym}{short(i['token'])} pad {(i['pad'] or 0) * 100:.0f} %, L {_p(i['l_pad'])}, SOL strana "
            f"{_p(i['sol_pad'])}")


def lines(s, top=12):
    """The ONE log block (every line starts with 'rug pravilo')."""
    P = "rug pravilo"
    out = [f"{P} (pool invariant) {s['days']} dana: {s['n']} tokena, rug→dump {s['rug_dump']}, dump→rug {s['dump_rug']}, "
           f"ostaje rug {s['rug_rug']} (rug→ništa {s['rug_none']}, ništa→rug {s['none_rug']}, ostaje dump "
           f"{s['dump_dump']}); po SOL strani bi bilo: rug {s['sol_rug']}, dump {s['sol_dump']} (od pool dumpova "
           f"{s['sol_rug_pool_dump']} bi po SOL strani bili rug)" + (" [DJELOMIČNO: isteklo vrijeme]" if s["partial"] else "")]
    out.append(f"{P} | izvori: arhiva rugova {s['src_archive']} (+ mehanika {s['mehanika']}, ostaje rug), kolaps ulazi "
               f"{s['src_collapse']}, demo odluke 'rugan' {s['paper']} tokena (od toga sada dump {s['paper_now_dump']}); "
               f"{s['took_s']:.0f} s")
    x = s.get("x")
    if x and x["in_data"]:
        out.append(f"{P} | X {short(x['token'])}: staro {x['old'] or 'ništa'} → novo {x['new'] or 'ništa'} (po SOL strani "
                   f"{x['sol'] or 'ništa'}); pad {(x['pad'] or 0) * 100:.0f} %, L {_p(x['l_pad'])}, SOL strana {_p(x['sol_pad'])}")
    elif x:
        out.append(f"{P} | X {short(x['token'])}: u bazi, ali bez pada od 50 %+ u {s['days']} dana (nijedno pravilo ga ne označava)")
    else:
        out.append(f"{P} | X {X_HEAD}…{X_TAIL}: nije pronađen u hype.db (token_tier, rug_archive, token_status, hype_snapshots)")
    if s["list_rug_dump"]:
        out.append(f"{P} | rug→dump ({min(top, len(s['list_rug_dump']))} od {len(s['list_rug_dump'])}): "
                   + "; ".join(_item(i) for i in s["list_rug_dump"][:top]))
    if s["list_dump_rug"]:
        out.append(f"{P} | dump→rug ({min(top, len(s['list_dump_rug']))} od {len(s['list_dump_rug'])}): "
                   + "; ".join(_item(i) for i in s["list_dump_rug"][:top]))
    out.append(f"{P} | pretpostavke: L iz USD likvidnosti i mcapa uz dnevnu SOL cijenu (market.db), jer SOL strana prije "
               "11.11. navečer nije spremana; pool nepoznate vrste = CP (PumpSwap); dokazi (dev, holderi, rug filter) "
               "današnji. Ništa nije obrisano: nove oznake su u hype.db rug_relabel uz stare.")
    return out


def retro_once(path, now=None, log=print, paper_db=None, **kw):
    """retro() once per RULE (the rug_relabel_runs row is the marker); the log block. Returns the summary or None."""
    if not path or not os.path.exists(path) or os.path.getsize(path) == 0:
        return None
    try:
        con = sqlite3.connect(path, timeout=60)
        try:
            con.executescript(SCHEMA)
            done = con.execute("SELECT ts FROM rug_relabel_runs WHERE rule=?", (RULE,)).fetchone()
        finally:
            con.close()
    except sqlite3.Error as e:
        log(f"rug pravilo: provjera oznake nije uspjela ({e})")
        return None
    if done:
        return None
    if paper_db is None:
        paper_db = os.path.join(os.path.dirname(path), "paper.db")
    s = retro(path, now, paper_db=paper_db, log=log, **kw)
    for ln in lines(s):
        log(ln)
    return s
