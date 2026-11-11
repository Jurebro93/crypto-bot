"""Rug labels again, under every label version (11.11. evening, Jure: "Retroaktivno ponovi oznake za zadnjih 7 dana i
javi koliko se tokena prebacilo iz 'rug' u 'dump'"; after PR #140 decided on the pool invariant L from its peak, the
owner's final rule: "Rug je izvučena likvidnost, pa mjeri višak: očekivani_SOL_omjer = sqrt(cijena_kraj /
cijena_početak), stvarni_SOL_omjer = SOL_kraj / SOL_početak, rug ako stvarni / očekivani <= 0,5, ILI pad cijene >= 90 %
i SOL strana >= 90 %, ILI >= 70 % uz dev/top-holder prodaju ili visok rug_risk"; "ponovno pokreni preoznačavanje za 7
dana ... 5 nasumičnih tokena iz ostatka rug→dump"). Nothing is deleted or rewritten: every label goes NEXT to the old one.
  rug_relabel      (PR #140, RULE pool_v1; kept as it was written) old_kind = usd, new_kind = pool_v1
  rug_relabel_sol  (RULE sol_v2) old_kind = usd (11.11. noon: the USD liquidity more than 50 % down), l_kind = pool_v1
                   (L 50 %+ under its peak), new_kind = sol_v2 (rugfilter/collapse.judge_v2, the rule above, from the
                   start snapshot: the first, or the first after liquidity was added / the pool migrated), strict_kind
                   (a rug if any says rug: what blocks until the owner's switch rug_labels_v2_ok, rugfilter/labels), why
                   (višak | 90/90 | dokaz), the falls, the SOL side first / lowest / last, the expected SOL ratio and
                   actual / expected, measured (the stored DexScreener SOL side) or estimated (USD liquidity / 2 / the
                   day's SOL price).
rugfilter/archive.kinds reads the archive rows of both tables.

Sources: every place a rug label was stored or shown in the DAYS window.
  archive   hype.db rug_archive rows archived in the window ("srusen" / "likvidnost"; "mehanika" stays a rug in every
            version and is only counted): the versions at the token's last point against its whole kept history (the
            archive keeps two snapshots per hour), else from the row's own peak / last numbers. note_archived() writes
            the same row for every token the hourly run archives, before its history is purged.
  collapse  tokens of hype_signals / token_pulse in the window (what ui/kandidati, league/copy, run_paper and fast
            computed live from collapse.peaks), plus the tokens of paper.db's 'skip_rug' decisions "rugan: ..." and X
            (CccS…y1eU) when it is in the data: every point (thinned to the last, highest and lowest of each 10 min)
            against the 24 h before it (collapse.Track: the start snapshot, the SOL ratios, the peaks); a token's
            label is the worst it had in the window.
retro_once() runs once per RULE (rug_relabel_runs) inside the hourly rug archive process (start.sh: 2 min after a start,
under the heavy-job lock, low priority), bounded by BUDGET_S, and prints ONE log block "rug pravilo (višak SOL-a,
sol_v2) 7 dana: ..." with 5 random tokens of what stays rug→dump.
"""
import collections
import math
import os
import random
import sqlite3
import time

from rugfilter import collapse

RULE = "sol_v2"
DAYS = 7
SLOT_S = 600
BUDGET_S = float(os.environ.get("RUG_RELABEL_BUDGET_S", "300"))
X_HEAD, X_TAIL = "CccS", "y1eU"
RANK = {None: 0, "dump": 1, "rug": 2}
SAMPLE = 5
COLS = ("token", "src", "ts", "symbol", "old_kind", "l_kind", "new_kind", "strict_kind", "why", "pad", "liq_pad", "l_pad",
        "sol_pad", "sol_peak_pad", "sol_first", "sol_low", "sol_last", "ratio", "expected", "reset", "measured", "reason",
        "rule", "relabeled_ts")
SCHEMA = """
CREATE TABLE IF NOT EXISTS rug_relabel (
    token TEXT, src TEXT, ts INTEGER, symbol TEXT, old_kind TEXT, new_kind TEXT, sol_kind TEXT, pad REAL,
    liq_pad REAL, l_pad REAL, sol_pad REAL, cp INTEGER, reason TEXT, rule TEXT, relabeled_ts INTEGER,
    PRIMARY KEY (token, src));
CREATE TABLE IF NOT EXISTS rug_relabel_sol (
    token TEXT, src TEXT, ts INTEGER, symbol TEXT, old_kind TEXT, l_kind TEXT, new_kind TEXT, strict_kind TEXT,
    why TEXT, pad REAL, liq_pad REAL, l_pad REAL, sol_pad REAL, sol_peak_pad REAL, sol_first REAL, sol_low REAL,
    sol_last REAL, ratio REAL, expected REAL, reset INTEGER, measured INTEGER, reason TEXT, rule TEXT,
    relabeled_ts INTEGER, PRIMARY KEY (token, src));
CREATE TABLE IF NOT EXISTS rug_relabel_runs (rule TEXT PRIMARY KEY, ts INTEGER, summary TEXT);
"""


def short(m):
    return f"{m[:4]}…{m[-4:]}" if m and len(m) > 10 else (m or "?")


# ---------- one token's points -----------------------------------------------------------------------------------
def points(con, token, since=None, until=None):
    """[(ts, mcap, liq_usd, liq_sol, price_native, pool)] by ts from hype_signals, token_pulse (with its SOL side when
    the columns are there) and hype_snapshots, each read by its (token, ts) key; points without a market cap are left
    out."""
    since = int(since or 0)
    until = int(until or 2 ** 40)
    out = []
    for table, cols in (("hype_signals", "ts, mcap, liquidity, NULL, NULL, NULL"),
                        ("token_pulse", "ts, mcap, liquidity, liq_sol, price_native, pool"),
                        ("token_pulse", "ts, mcap, liquidity, NULL, NULL, NULL"),
                        ("hype_snapshots", "ts, mcap, liquidity, NULL, NULL, NULL")):
        if table == "token_pulse" and any(p[6] == "token_pulse" for p in out[-1:]) and cols.endswith("NULL, NULL"):
            continue
        try:
            rows = con.execute(f"SELECT {cols} FROM {table} WHERE token=? AND ts BETWEEN ? AND ?",
                               (token, since, until)).fetchall()
        except sqlite3.OperationalError:
            continue
        out += [r + (table,) for r in rows]
        if table == "token_pulse" and "liq_sol" in cols:
            out.append((None,) * 6 + ("token_pulse",))   # marker: the extended read worked
    pts = sorted((int(t), float(m), float(lq or 0), ls, pn, pool) for t, m, lq, ls, pn, pool, _tb in out
                 if t and m and m > 0)
    return pts


def thin(pts, slot=SLOT_S):
    """The last, the highest and the lowest point of every slot, in time order (a 2-minute pulse over 7 days is
    5,000 points; the labels are about 50-90 % moves)."""
    by = collections.OrderedDict()
    for p in pts:
        by.setdefault(p[0] // slot, []).append(p)
    out = []
    for grp in by.values():
        keep = {grp[-1], max(grp, key=lambda p: p[1]), min(grp, key=lambda p: p[1])}
        out += sorted(keep, key=lambda p: (p[0], p[1]))
    return out


class _Win:
    """Sliding-window maximum or minimum (monotonic deque) of (ts, value, extra)."""

    def __init__(self, low=False):
        self.q = collections.deque()
        self.low = low

    def push(self, ts, v, extra=None):
        while self.q and ((self.q[-1][1] >= v) if self.low else (self.q[-1][1] <= v)):
            self.q.pop()
        self.q.append((ts, v, extra))

    def expire(self, ts_min):
        while self.q and self.q[0][0] < ts_min:
            self.q.popleft()

    def top(self):
        return self.q[0] if self.q else (None, 0.0, None)


def judge_point(pm, m, pl, liq, pool, evidence):
    """{"usd", "pool_v1", "sol_v2", "why"} at one point (None for a peak too small to judge)."""
    if not pm or pm < collapse.MIN_PEAK_MCAP:
        return None
    drop = 1 - m / pm
    v2, why = collapse.judge_v2(drop, pool, evidence)
    return {"usd": (collapse.judge_usd(pm, m, pl or None, liq, evidence) or {}).get("kind"),
            "pool_v1": collapse.judge_pool_v1(drop, pool, evidence), "sol_v2": v2, "why": why}


def evaluate(pts, token=None, window_s=collapse.WINDOW_H * 3600, since=None, evidence_fn=None):
    """{"usd", "pool_v1", "sol_v2", "whys": {why of every sol_v2 rug point}, "ts", detail of the deepest labelled
    point}: the worst label of each version over the points from `since` on, every point against the window_s before
    it (None: the whole history): collapse.Track's start snapshot (the first, or the first after an LP add / a
    migration), its SOL ratios and the peaks. The SOL side of a point is the stored DexScreener one (token_pulse, only
    the newest pool's) or the USD liquidity / 2 / the day's SOL price; the price is mcap / the day's SOL price for
    every point (one scale). evidence_fn(token) is asked once, only when a point fell DROP or more."""
    pts = thin(pts)
    pools = [(p[0], p[5]) for p in pts if p[3] and p[4] and p[5]]
    pool = max(pools)[1] if pools else None
    tr = collapse.Track(window_s)
    mx_m, mx_liq = _Win(), _Win()
    best = {"usd": None, "pool_v1": None, "sol_v2": None, "whys": set(), "ts": None}
    worst_pad = -1.0
    ev, asked = None, False
    for ts, m, liq, ls, pn, addr in pts:
        s_usd = collapse.sol_usd_at(ts)
        meas = bool(ls and pn and addr == pool)
        tr.push(ts, ls if meas else (liq / 2 / s_usd if liq > 0 else 0.0), m / s_usd, meas)
        mx_m.push(ts, m)
        mx_liq.push(ts, liq)
        if window_s is not None:
            mx_m.expire(ts - window_s)
            mx_liq.expire(ts - window_s)
        if since is not None and ts < since:
            continue
        pm, pl = mx_m.top()[1], mx_liq.top()[1]
        if pm < collapse.MIN_PEAK_MCAP:
            continue
        pool_d = tr.state()
        drop = 1 - m / pm
        ratio = pool_d.get("ratio")
        if drop < 1 - collapse.RECOVER and (ratio is None or ratio > collapse.EXCESS_RUG) \
                and (pool_d.get("l_drop") or 0) < collapse.LIQ_RUG and not (pl and liq / pl < 1 - collapse.LIQ_RUG):
            continue   # no version can label this point: skip the judging
        if drop >= collapse.DROP and not asked and evidence_fn and token:
            asked, ev = True, evidence_fn(token)
        k = judge_point(pm, m, pl, liq, pool_d, ev)
        if not k or (k["usd"] is None and k["pool_v1"] is None and k["sol_v2"] is None):
            continue
        for v in ("usd", "pool_v1", "sol_v2"):
            if RANK[k[v]] > RANK[best[v]]:
                best[v] = k[v]
        if k["sol_v2"] == "rug":
            best["whys"].add(k["why"])
        if drop > worst_pad:
            worst_pad = drop
            best.update(ts=ts, pad=drop, liq_pad=(1 - liq / pl) if pl else None, l_pad=pool_d.get("l_drop"),
                        sol_pad=pool_d.get("sol_drop"), sol_peak_pad=pool_d.get("sol_drop_peak"),
                        sol_first=pool_d.get("sol_first"), sol_low=pool_d.get("sol_low"),
                        sol_last=pool_d.get("sol_last"), ratio=ratio, actual=pool_d.get("actual"),
                        expected=pool_d.get("expected"), reset=pool_d.get("reset"), measured=pool_d.get("measured"),
                        why=k["why"])
    return best


# ---------- the archive rows -------------------------------------------------------------------------------------
def archive_row_labels(con, row, now=None, evidence_fn=None):
    """The versions of one rug_archive row (dict) on the token's kept history (whole-history first snapshot and
    peaks, judged at its last point), else from the row's own numbers."""
    from rugfilter import archive
    evidence_fn = evidence_fn or collapse.rug_evidence
    usd = archive.kind_usd(row["kind"], row.get("peak_liq"), row.get("last_liq"))
    if (row.get("last_mcap") or 0) <= 0 and (row.get("last_liq") or 0) <= 0:   # the pair vanished: a rug everywhere
        return {"usd": usd, "pool_v1": "rug", "sol_v2": "rug", "whys": {"sol"}, "why": "sol", "pad": 1.0,
                "liq_pad": 1.0, "l_pad": 1.0, "sol_pad": 1.0, "sol_peak_pad": 1.0, "measured": False,
                "reason": row.get("reason") or "par nestao s DEX-a", "ts": row.get("archived_ts")}
    pts = points(con, row["token"])
    out = None
    if len([p for p in pts if p[2] > 0]) >= 2:
        out = evaluate(pts, row["token"], window_s=None, since=pts[-1][0], evidence_fn=evidence_fn)
        if out["usd"] is None and out["pool_v1"] is None and out["sol_v2"] is None:
            out = None   # the kept history does not show the fall the archive saw: its own numbers below
    if out is None:
        pm, lm, pl, ll = row.get("peak_mcap"), row.get("last_mcap"), row.get("peak_liq"), row.get("last_liq")
        ks = archive.kinds_of(row["kind"], pl, ll, pm, lm)
        j = collapse.judge(pm, lm, pl, ll, strict=False) if pm and lm is not None else None
        out = {**ks, "whys": {(j or {}).get("why")} - {None}, "why": (j or {}).get("why"),
               "pad": (j or {}).get("drop"), "liq_pad": (j or {}).get("liq_drop"), "l_pad": (j or {}).get("l_drop"),
               "sol_pad": (j or {}).get("sol_drop"), "sol_peak_pad": (j or {}).get("sol_drop_peak"),
               "sol_first": (j or {}).get("sol_first"), "sol_low": (j or {}).get("sol_low"),
               "sol_last": (j or {}).get("sol_last"), "ratio": (j or {}).get("ratio"),
               "actual": (j or {}).get("actual"), "expected": (j or {}).get("expected"), "measured": False,
               "reason": (j or {}).get("text") or row.get("reason"), "ts": row.get("archived_ts")}
    for v in ("pool_v1", "sol_v2"):
        if out.get(v) is None:
            out[v] = "dump"   # an archived token is never unlabelled: at worst a dump (P x 0.7, no block)
    out["usd"] = usd
    return out


def note_archived(con, cands, now=None, log=None):
    """The hourly archive run: one rug_relabel_sol row (src 'archive') per collapse it archives now, from its history
    before the purge. cands: archive.candidates() tuples. Returns rows written."""
    now = int(now or time.time())
    con.executescript(SCHEMA)
    n = 0
    for t, kind, reason, st in cands:
        if kind not in ("srusen", "likvidnost"):
            continue
        row = {"token": t, "kind": kind, "reason": reason, "archived_ts": now, **{k: st.get(k) for k in
               ("symbol", "peak_mcap", "last_mcap", "peak_liq", "last_liq")}}
        write(con, t, "archive", archive_row_labels(con, row, now), st.get("symbol"), now)
        n += 1
    con.commit()
    return n


def _r(x):
    return None if x is None else round(float(x), 4)


def write(con, token, src, lab, symbol, now):
    from rugfilter import labels
    strict_kind = labels.worst(lab.get("usd"), lab.get("pool_v1"), lab.get("sol_v2"))
    reason = lab.get("reason") or (f"pad {(lab.get('pad') or 0):.0%}, SOL strana {(lab.get('sol_pad') or 0):.0%}, "
                                   f"L {(lab.get('l_pad') or 0):.0%}")
    con.execute(f"INSERT OR REPLACE INTO rug_relabel_sol ({', '.join(COLS)}) VALUES ({','.join('?' * len(COLS))})",
                (token, src, lab.get("ts"), symbol, lab.get("usd"), lab.get("pool_v1"), lab.get("sol_v2"), strict_kind,
                 ",".join(sorted(lab.get("whys") or ())) or lab.get("why"), _r(lab.get("pad")), _r(lab.get("liq_pad")),
                 _r(lab.get("l_pad")), _r(lab.get("sol_pad")), _r(lab.get("sol_peak_pad")), _r(lab.get("sol_first")),
                 _r(lab.get("sol_low")), _r(lab.get("sol_last")), _r(lab.get("ratio")), _r(lab.get("expected")),
                 int(bool(lab.get("reset"))), int(bool(lab.get("measured"))), reason[:300], RULE, int(now)))


# ---------- the retroactive pass ---------------------------------------------------------------------------------
def _prefilter(con, since, budget_end):
    """{token} whose window (plus the day before) holds a 50 %+ fall of the market cap or the liquidity (order
    ignored: a superset of what any version can label), from one pass over hype_signals (its ts index) and
    token_pulse."""
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
                a[0], a[1], a[2], a[3], a[4], a[5] = (max(a[0], m), min(a[1], m), max(a[2], liq), min(a[3], liq),
                                                      max(a[4], lu), min(a[5], lu))
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


def retro(path, now=None, days=DAYS, paper_db=None, budget_s=None, log=print, evidence_fn=None, seed=None):
    """The labels of the last `days` days again (module text); writes rug_relabel_sol rows (never deletes) and returns
    the summary dict (the log block is lines(summary))."""
    now = int(now or time.time())
    t0 = time.monotonic()
    budget_end = t0 + (BUDGET_S if budget_s is None else budget_s)
    since = now - days * 86400
    evidence_fn = evidence_fn or collapse.rug_evidence
    con = sqlite3.connect(path, timeout=60)
    con.execute("PRAGMA busy_timeout=60000")
    con.executescript(SCHEMA)
    res = {}          # token -> (src, labels, symbol)
    partial = False
    mech = 0
    try:
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
            res[r["token"]] = ("archive", archive_row_labels(con, r, now, evidence_fn), r.get("symbol"))
        x = find_x(con)
        paper = _paper_rugan(paper_db, since)
        cands = (_prefilter(con, since - collapse.WINDOW_H * 3600, budget_end) | paper | ({x} if x else set())) - archived
        for t in sorted(cands):
            if time.monotonic() > budget_end:
                partial = True
                break
            lab = evaluate(points(con, t, since - collapse.WINDOW_H * 3600, now), t, since=since,
                           evidence_fn=evidence_fn)
            if lab["usd"] is None and lab["pool_v1"] is None and lab["sol_v2"] is None and t != x:
                continue
            res[t] = ("collapse", lab, None)
        syms = _symbols(con, [t for t, v in res.items() if not v[2]])
        for t, (src, lab, sym) in res.items():
            write(con, t, src, lab, sym or syms.get(t), now)
        summary = summarize(res, syms, paper, mech, x, partial, round(time.monotonic() - t0, 1), days,
                            random.Random(now if seed is None else seed))
        con.execute("INSERT OR REPLACE INTO rug_relabel_runs VALUES (?,?,?)",
                    (RULE, now, str({k: v for k, v in summary.items() if not isinstance(v, (list, dict))})[:2000]))
        con.commit()
    finally:
        con.close()
    return summary


def _item(t, lab, sym):
    return {"token": t, "symbol": sym, **{k: lab.get(k) for k in ("usd", "pool_v1", "sol_v2", "pad", "l_pad", "sol_pad",
                                                                  "sol_peak_pad", "sol_first", "sol_low", "sol_last",
                                                                  "ratio", "actual", "expected", "reset", "measured")}}


def summarize(res, syms, paper, mech, x, partial, took, days=DAYS, rnd=None):
    c = collections.Counter()
    rug_dump, dump_rug, v1_rug_dump = [], [], 0
    for t, (src, lab, sym) in res.items():
        o, l1, n = lab.get("usd"), lab.get("pool_v1"), lab.get("sol_v2")
        if o is None and l1 is None and n is None:
            continue
        sym = sym or syms.get(t)
        c["n"] += 1
        c[f"src_{src}"] += 1
        c[f"{o}->{n}"] += 1
        v1_rug_dump += o == "rug" and l1 == "dump"
        if "rug" in (o, l1, n):
            c["strict_rug"] += 1
        if (lab.get("sol_pad") or 0) >= 0.5:
            c["literal_sol"] += 1   # the dropped literal threshold "SOL side -50 %" (a plain 75 % dump crosses it)
            c["literal_sol_dump"] += n == "dump"
        if o == "rug" and n == "dump":
            rug_dump.append(_item(t, lab, sym))
        elif o == "dump" and n == "rug":
            dump_rug.append(_item(t, lab, sym))
    rug_dump.sort(key=lambda i: -(i["pad"] or 0))
    rnd = rnd or random.Random()
    sample = rnd.sample(rug_dump, min(SAMPLE, len(rug_dump)))
    paper_now_dump = sum(1 for t in paper if t in res and res[t][1].get("sol_v2") == "dump")
    xl = None
    if x:
        lab = res.get(x, (None, {}, None))[1]
        xl = {**_item(x, lab, syms.get(x)), "in_data": x in res}
    return {"n": c["n"], "rug_dump": c["rug->dump"], "dump_rug": c["dump->rug"], "rug_rug": c["rug->rug"],
            "rug_none": c["rug->None"], "none_rug": c["None->rug"], "dump_dump": c["dump->dump"],
            "dump_none": c["dump->None"], "none_dump": c["None->dump"], "v1_rug_dump": v1_rug_dump,
            "literal_sol": c["literal_sol"], "literal_sol_dump": c["literal_sol_dump"], "strict_rug": c["strict_rug"],
            "src_archive": c["src_archive"],
            "src_collapse": c["src_collapse"], "mehanika": mech, "paper": len(paper), "paper_now_dump": paper_now_dump,
            "x": xl, "partial": partial, "took_s": took, "days": days, "list_rug_dump": rug_dump,
            "list_dump_rug": dump_rug, "sample": sample}


def _p(x):
    if x is None:
        return "?"
    v = -x * 100
    return "0 %" if abs(v) < 0.5 else f"{v:+.0f} %"


def _sol(x):
    return "?" if x is None else (f"{x:.1f}" if x < 1000 else f"{x:.0f}").replace(".", ",")


def _ratio(x):
    return "?" if x is None else f"{x:.2f}".replace(".", ",")


def why_dump(i):
    """Why sol_v2 says dump, in Croatian."""
    bits = []
    if i.get("ratio") is not None:
        bits.append(f"stvarni / očekivani SOL omjer {_ratio(i['ratio'])} (> 0,5: SOL je otišao koliko objašnjava pad "
                    "cijene, ne više)")
    else:
        bits.append("omjer nepoznat")
    sd = max(i.get("sol_pad") or 0, i.get("sol_peak_pad") or 0)
    bits.append(f"cijena {(i['pad'] or 0) * 100:.0f} % i SOL strana {sd * 100:.0f} % (nije 90/90)")
    return ", ".join(bits) + ", bez dokaza (dev / top holderi / rug rizik)"


def _sample_line(i):
    sym = f"{i['symbol']} " if i.get("symbol") else ""
    px = None if i.get("expected") is None else 1 - i["expected"] ** 2
    return (f"{sym}{short(i['token'])}: cijena od vrha {_p(i['pad'])}, od prve snimke {_p(px)}, SOL strana "
            f"{_sol(i['sol_first'])} → {_sol(i['sol_last'])} "
            f"SOL ({_p(i['sol_pad'])}; najniža {_sol(i['sol_low'])}), očekivano po cijeni {_ratio(i.get('expected'))}, "
            f"stvarni / očekivani {_ratio(i.get('ratio'))}, L od vrha {_p(i['l_pad'])}, "
            f"{'izmjereno (DexScreener SOL strana)' if i.get('measured') else 'procjena iz USD likvidnosti'}"
            f"{', start nakon dodavanja likvidnosti / migracije' if i.get('reset') else ''}; dump jer: {why_dump(i)}")


def _x_line(x, days):
    if not x:
        return f"X {X_HEAD}…{X_TAIL}: nije pronađen u hype.db (token_tier, rug_archive, token_status, hype_snapshots)"
    if not x["in_data"]:
        return f"X {short(x['token'])}: u bazi, ali bez pada od 50 %+ u {days} dana (nijedna verzija ga ne označava)"
    return (f"X {short(x['token'])}: staro (usd) {x['usd'] or 'ništa'}, L (pool_v1) {x['pool_v1'] or 'ništa'}, novo "
            f"(sol_v2) {x['sol_v2'] or 'ništa'}; cijena {_p(x['pad'])}, SOL strana {_sol(x['sol_first'])} → "
            f"{_sol(x['sol_last'])} ({_p(x['sol_pad'])}), stvarni / očekivani {_ratio(x.get('ratio'))}")


def lines(s):
    """The ONE log block (every line starts with 'rug pravilo')."""
    P = "rug pravilo"
    out = [f"{P} (višak SOL-a, sol_v2) {s['days']} dana: {s['n']} tokena, rug→dump {s['rug_dump']}, dump→rug "
           f"{s['dump_rug']}, ostaje rug {s['rug_rug']} (rug→ništa {s['rug_none']}, ništa→rug {s['none_rug']}, ostaje "
           f"dump {s['dump_dump']}); po L pravilu (pool_v1, PR #140) bilo bi rug→dump {s['v1_rug_dump']}"
           + (" [DJELOMIČNO: isteklo vrijeme]" if s["partial"] else "")]
    out.append(f"{P} | pravilo: rug ako stvarni / očekivani SOL omjer <= 0,5 (očekivani = √(cijena kraj / početak)), ili "
               "cijena i SOL strana 90 %+, ili 70 %+ uz dokaz; početak = prva snimka ili prva nakon dodavanja likvidnosti / "
               f"migracije. Po odbačenom pragu 'SOL strana −50 %' bilo bi rug {s['literal_sol']} (od toga po novom pravilu "
               f"dump {s['literal_sol_dump']}: čisti pad cijene 75 %+ na CP poolu, √0,25 = 0,5)")
    out.append(f"{P} | blokiranje do potvrde (zastavica rug_labels_v2_ok isključena): stroža oznaka, rug ako ijedna "
               f"verzija kaže rug: {s['strict_rug']} od {s['n']}; statistike i dalje po starim oznakama")
    out.append(f"{P} | izvori: arhiva rugova {s['src_archive']} (+ mehanika {s['mehanika']}, ostaje rug), kolaps ulazi "
               f"{s['src_collapse']}, demo odluke 'rugan' {s['paper']} tokena (od toga sada dump {s['paper_now_dump']}); "
               f"{s['took_s']:.0f} s")
    out.append(f"{P} | {_x_line(s.get('x'), s['days'])}")
    if s["sample"]:
        out.append(f"{P} | {len(s['sample'])} nasumičnih od {s['rug_dump']} koji ostaju rug→dump:")
        out += [f"{P} |   {_sample_line(i)}" for i in s["sample"]]
    if s["list_dump_rug"]:
        out.append(f"{P} | dump→rug ({min(8, len(s['list_dump_rug']))} od {len(s['list_dump_rug'])}): "
                   + "; ".join(f"{i['symbol'] + ' ' if i.get('symbol') else ''}{short(i['token'])} cijena {_p(i['pad'])}"
                               f", SOL strana {_p(i['sol_pad'])}" for i in s["list_dump_rug"][:8]))
    out.append(f"{P} | pretpostavke: SOL strana iz DexScreenera (token_pulse) samo gdje je spremljena (od 11.11. "
               "popodne), inače USD likvidnost / 2 / dnevna SOL cijena (market.db); dokazi (dev, holderi, rug filter) "
               "današnji. Ništa nije obrisano: oznake su u hype.db rug_relabel_sol uz stare.")
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
