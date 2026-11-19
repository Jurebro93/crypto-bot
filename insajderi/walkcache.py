"""The copy walk-forwards, incremental (19.11. navečer, coordinator: "the copy walk-forward over 180 days of pumps ... is
cut at the deadline on every pass and so never produces a number. The owner is waiting for exactly that number").

The selection of walk day D depends only on the events whose window ended before D (and on the per-owner facts: the
bots, the market makers, the tokens' first trades), so a walked day is kept and only what changed is walked again:

  inputs     a fingerprint per event (its fields that classify reads and its participants), per wallet its flags (bot,
             market maker) and per token its first trade, stored per walk after every pass (i2_walk_fp)
  dirty      the earliest window end among the events whose fingerprint changed / appeared / left the horizon, among
             the events of the wallets whose flags changed and of the tokens whose first trade changed: every day after
             it is walked again; plus always the last `tail_days` (2) days (today's buys, exits still to come); a
             different config / code version (VERSION) walks everything again
  resume     a pass walks days in order from the first dirty day and stops at the deadline after a whole day; the next
             pass continues from there (i2_walk.through)
  publish    the summary (the numbers in the line) only when the walk has reached today; before that the line says
             "kopija: izračunato do <date> (<n> od <m> dana)"

Cheaper days: only owner groups seen in 2+ events can ever be selected or be in the null's pool (an owner seen in ONE
event is "jednokratni", excluded, in the pump class, and can never reach the insider's 3 events), so the walks
classify only those owners (classify's results for them are the same: every per-owner statistic reads only that
owner's own rows). The null's draw is seeded per day (null_seed + day), so a day's draw does not depend on how many
draws came before it, and a drawn owner's wallets are those seen in the events closed before D (before: all its
wallets, a small look-ahead). The selection itself is the class Fast (see there).

Tables: i2_walk (walk, through, version, days, updated), i2_walk_fp (walk, kind, key, val). Rows: i2_pp_copy (walk
"pp", with the new column assumed) and i2_copy (walk "ins"), each row with its day.
"""
import hashlib
import json
import random
from collections import defaultdict

from insajderi import copy, prijepumpe, score, store

VERSION = "w1"
D = 86400
SCHEMA = """
CREATE TABLE IF NOT EXISTS i2_walk (walk TEXT PRIMARY KEY, through INTEGER, version TEXT, days INTEGER, updated INTEGER);
CREATE TABLE IF NOT EXISTS i2_walk_fp (walk TEXT, kind TEXT, key TEXT, val TEXT, PRIMARY KEY (walk, kind, key));
"""
PP_KEYS = ("pump_min_tokens", "min_sol", "min_lead_min", "min_confirm", "sniper_secs", "sniper_share",
           "busy_events_share", "null_k", "null_seed", "warmup_days", "delay_s", "fast_delay_s", "fast_gap_s",
           "slip_fast", "slip_entry", "slip_exit", "stop", "hold_h", "price_gap_s", "pp_size_sol", "pp_size_sol_big")
INS_KEYS = ("min_tokens", "min_confirm", "min_callers", "min_lift", "min_lead_min", "sniper_secs", "sniper_share",
            "busy_events_share", "warmup_days", "delay_s", "slip_entry", "slip_exit", "stop", "hold_h", "size_usd",
            "price_gap_s", "bond_mcap")


def ensure(con):
    con.executescript(SCHEMA)
    have = {r[1] for r in con.execute("PRAGMA table_info(i2_pp_copy)")}
    if "assumed" not in have:
        con.execute("ALTER TABLE i2_pp_copy ADD COLUMN assumed INTEGER")
    con.commit()


def version(c, walk):
    keys = PP_KEYS if walk == "pp" else INS_KEYS
    return VERSION + ":" + hashlib.sha1(json.dumps([str(c.get(k)) for k in keys]).encode()).hexdigest()[:12]


def multi_parts(parts):
    """The rows of the owner groups seen in 2+ events (see the module text)."""
    seen = defaultdict(set)
    for r in parts:
        seen[r[2] or r[1]].add(r[0])
    return [r for r in parts if len(seen[r[2] or r[1]]) >= 2]


def days_of(events, c, now):
    start = min(e["t0"] for e in events) + int(c["warmup_days"]) * D
    d0 = start - start % D + D
    return list(range(d0, int(now) - int(now) % D + D, D))


# ---------- the inputs and what changed -------------------------------------------------------------------------------

def inputs(events, parts, bad=frozenset(), first_trade=None, mm=frozenset()):
    """{"ev": {eid: fingerprint}, "end": {eid: win_end}, "own": {wallet: flags}, "ft": {token: ts}, "tok": {eid:
    token}, "of": {wallet: [eid]}}."""
    rows = defaultdict(list)
    of = defaultdict(set)
    for r in parts:
        rows[r[0]].append(r)
        of[r[1]].add(r[0])
    ev, end, tok = {}, {}, {}
    for e in events:
        h = hashlib.sha1(json.dumps([e.get(k) for k in ("kind", "token", "t0", "win_end", "tier", "n_part", "callers")],
                                    sort_keys=True, default=str).encode())
        for r in sorted(rows.get(e["eid"], []), key=lambda x: str(x[1])):
            h.update(repr(r).encode())
        ev[e["eid"]] = h.hexdigest()[:20]
        end[e["eid"]] = int(e["win_end"])
        tok[e["eid"]] = e["token"]
    own = {}
    for w in set(bad) | set(mm):
        own[w] = ("b" if w in bad else "") + ("m" if w in mm else "")
    return {"ev": ev, "end": end, "tok": tok, "own": own, "ft": {k: int(v) for k, v in (first_trade or {}).items()},
            "of": {w: sorted(x) for w, x in of.items()}}


def _stored(con, walk):
    out = {"ev": {}, "own": {}, "ft": {}, "end": {}}
    for kind, key, val in store.q(con, "SELECT kind, key, val FROM i2_walk_fp WHERE walk = ?", (walk,)):
        if kind == "ev":
            fp, _, end = val.partition("|")
            out["ev"][key] = fp
            out["end"][key] = int(end or 0)
        elif kind in ("own", "ft"):
            out[kind][key] = val
    return out


def dirty_from(con, walk, inp):
    """The earliest window end any change touches (None: nothing changed)."""
    old = _stored(con, walk)
    ends = []
    for eid in set(old["ev"]) | set(inp["ev"]):
        if old["ev"].get(eid) != inp["ev"].get(eid):
            ends.append(inp["end"].get(eid) or old["end"].get(eid) or 0)
    for w in set(old["own"]) | set(inp["own"]):
        if (old["own"].get(w) or "") != (inp["own"].get(w) or ""):
            ends += [inp["end"][eid] for eid in inp["of"].get(w, []) if eid in inp["end"]]
    ftc = {t for t in set(old["ft"]) | set(inp["ft"]) if str(old["ft"].get(t)) != str(inp["ft"].get(t))}
    if ftc:
        ends += [inp["end"][eid] for eid, t in inp["tok"].items() if t in ftc]
    return min(ends) if ends else None


def save_inputs(con, walk, inp):
    con.execute("DELETE FROM i2_walk_fp WHERE walk = ?", (walk,))
    rows = [(walk, "ev", eid, f"{fp}|{inp['end'][eid]}") for eid, fp in inp["ev"].items()]
    rows += [(walk, "own", w, v) for w, v in inp["own"].items()]
    rows += [(walk, "ft", t, str(v)) for t, v in inp["ft"].items()]
    con.executemany("INSERT INTO i2_walk_fp VALUES (?,?,?,?)", rows)


def state(con, walk):
    r = store.q(con, "SELECT through, version, days FROM i2_walk WHERE walk = ?", (walk,))
    return {"through": r[0][0], "version": r[0][1], "days": r[0][2]} if r else {"through": None, "version": None,
                                                                              "days": None}


def start_day(con, walk, c, days, inp, tail_days=2):
    """The first day to walk this pass (index into days) and why."""
    st = state(con, walk)
    if st["version"] != version(c, walk) or st["through"] is None:
        return 0, "od početka"
    first = min(days.index(st["through"]) + 1 if st["through"] in days else 0, len(days))
    dirty = dirty_from(con, walk, inp)
    if dirty is not None:
        k = next((i for i, d in enumerate(days) if d > dirty), len(days))
        first = min(first, k)
    first = min(first, max(0, len(days) - int(tail_days)))   # today and yesterday: buys / exits still arriving
    return first, "nastavak"


# ---------- the pump walk (prijepumpe) --------------------------------------------------------------------------------

def _pp_select(c, events, mparts, d, bad, ft, mm, owner_members, early_owners):
    st = prijepumpe.classify(mparts, events, d, c, bad, ft, mm)
    sel = prijepumpe.confirmed(st)
    pool = set()
    for eid in prijepumpe.pump_events(events, d):
        pool |= early_owners.get(eid, set())
    keep = {o for o, s in st.items() if s["cls"] in ("prije_pumpe", "kandidat", "promatra")}
    pool = sorted((pool & keep) - set(sel))
    k = min(len(pool), max(len(sel), int(c["null_k"])))
    rng = random.Random(int(c["null_seed"]) * 1_000_003 + int(d) // D)
    closed = {e["eid"] for e in events if e["win_end"] < d}
    null = {o: sorted({w for eid, w in owner_members[o] if eid in closed}) for o in rng.sample(pool, k)} if k else {}
    return sel, null


def _ins_select(c, events, mparts, d, bad, ft):
    return score.confirmed(score.classify(mparts, events, d, c, bad, ft))


# ---------- the fast selection (exact: per-owner classification reads only that owner's rows + day globals) ----------

def _rows_of_owners(parts, owners):
    return [r for r in parts if (r[2] or r[1]) in owners]


class Fast:
    """The day-by-day selection without classifying every owner every day (19.11. navečer (2)): the result for an owner
    depends only on its own rows and on the day's globals (the closed events, the pump count n_cov, the 2/3 cut), so
      - the SELECTED groups can only come from owners that qualify on the final data (their pump tokens / hits only
        grow day by day): only those few owners are classified each day (prijepumpe / score.classify on their rows);
      - the null's pool needs the class of every early buyer: kept per owner and recomputed only for the owners whose
        events closed that day, plus the owners whose "kupuje sve" (n_early / n_cov) may have flipped.
    Results are identical to classifying everyone every day (tests/test_kopija_hod_offline.py)."""

    def __init__(self, c, events, mparts, bad, ft, mm, last_day, walk="pp"):
        self.c, self.events, self.bad, self.ft, self.mm = c, events, bad, ft, mm
        self.walk = walk
        self.by_owner = defaultdict(list)
        for r in mparts:
            self.by_owner[r[2] or r[1]].append(r)
        fin = last_day + D
        self.s_pp, self.s_ins = [], []
        if walk == "pp":
            st_pp = prijepumpe.classify(mparts, events, fin, c, bad, ft, mm)
            need = int(c["pump_min_tokens"])
            self.s_pp = [r for o in sorted(o for o, s in st_pp.items() if s["n_tokens"] >= need)
                         for r in self.by_owner[o]]
        else:
            st_ins = score.classify(mparts, events, fin, c, bad, ft)
            self.s_ins = [r for o in sorted(o for o, s in st_ins.items() if s["n_hits"] >= int(c["min_tokens"]))
                          for r in self.by_owner[o]]
        self.ends = sorted((int(e["win_end"]), e["eid"]) for e in events)
        self.owners_of = defaultdict(set)
        self.early_of = defaultdict(set)
        self.wallets_of = defaultdict(list)
        for r in mparts:
            self.owners_of[r[0]].add(r[2] or r[1])
            self.wallets_of[r[0]].append((r[1], r[2] or r[1]))
            if r[8]:
                self.early_of[r[0]].add(r[2] or r[1])
        self.tier = {e["eid"]: e.get("tier") for e in events}
        self.npart = {e["eid"]: e.get("n_part") for e in events}
        self.i = 0
        self.mem = defaultdict(set)   # owner -> wallets in the events closed so far (the null's members)
        self.cls, self.n_early = {}, {}
        self.keep, self.pool_all = set(), set()
        self.n_cov = 0
        self.any_cov = False

    def _recheck(self, owners, d):
        rows = [r for o in owners for r in self.by_owner.get(o, ())]
        st = prijepumpe.classify(rows, self.events, d, self.c, self.bad, self.ft, self.mm) if rows else {}
        for o in owners:
            s = st.get(o)
            if s is None:
                self.cls.pop(o, None)
                self.n_early.pop(o, None)
                self.keep.discard(o)
                continue
            self.cls[o], self.n_early[o] = s["cls"], s["n_early"]
            if s["cls"] in ("prije_pumpe", "kandidat", "promatra"):
                self.keep.add(o)
            else:
                self.keep.discard(o)

    def advance(self, d):
        """Close the events whose window ended before d; -> (selected pump groups, sorted null pool candidates
        before removing the selected, selected insiders)."""
        touched = set()
        first = self.i == 0
        while self.i < len(self.ends) and self.ends[self.i][0] < d:
            eid = self.ends[self.i][1]
            touched |= self.owners_of.get(eid, set())
            for w, o in self.wallets_of.get(eid, ()):
                self.mem[o].add(w)
            if self.tier.get(eid):
                self.pool_all |= self.early_of.get(eid, set())
            if self.npart.get(eid):
                self.any_cov = True
                if self.tier.get(eid):
                    self.n_cov += 1
            self.i += 1
        if self.walk == "pp":   # the null's pool: the classes of the early buyers
            if not self.any_cov or first:   # the "or every event" fallback of classify, and the first day: everyone
                touched = set(self.by_owner)
            share = float(self.c["busy_events_share"])
            busy = {o for o, n in self.n_early.items() if self.n_cov >= 10 and n >= share * self.n_cov}
            busy |= {o for o, k in self.cls.items() if k == "kupuje_sve"}
            if touched or busy:
                self._recheck(touched | busy, d)
        sel = prijepumpe.confirmed(prijepumpe.classify(self.s_pp, self.events, d, self.c, self.bad, self.ft, self.mm)) \
            if self.s_pp else {}
        ins = score.confirmed(score.classify(self.s_ins, self.events, d, self.c, self.bad, self.ft)) if self.s_ins else {}
        return sel, self.pool_all & self.keep, ins


def run(con, p, c, events, parts, now, bad=frozenset(), first_trade=None, mm=frozenset(), stop=None, prices=None,
        trades_fn=None, walks=("pp", "ins"), timer=None, fast=True):
    """One pass of both walks (the pump walk first). -> {walk: {"done", "through", "n", "m", "from", "summary"}}.
    trades_fn(members) -> trades (default copy.wallet_trades, read ONCE for both walks); timer(name, fn) times."""
    ensure(con)
    out = {}
    if not events:
        return {w: {"done": True, "through": None, "n": 0, "m": 0, "summary": None} for w in walks}
    timer = timer or (lambda _n, fn: fn())
    days = days_of(events, c, now)
    mparts = multi_parts(parts)
    owner_members = defaultdict(set)
    early_owners = defaultdict(set)
    for eid, w, o, _b, _si, _ns, _so, _fs, bb, _sd, _l in mparts:
        owner_members[o or w].add((eid, w))   # the null's members: the owner's wallets in events closed before D
        if bb:
            early_owners[eid].add(o or w)
    plan = {}
    for walk in walks:
        inp = inputs(events, parts, bad, first_trade, mm if walk == "pp" else frozenset())
        k0, why = start_day(con, walk, c, days, inp)
        plan[walk] = {"inp": inp, "k0": k0, "sel": {}, "null": {}, "why": why}

    # phase 1: the selections, day by day, the pump walk first
    fs = {}

    def sel_phase(walk):
        pl = plan[walk]
        todo = days[pl["k0"]:]
        if fast and todo:
            f = fs.get(walk) or Fast(c, events, mparts, bad, first_trade, mm, days[-1], walk)
            fs[walk] = f
        for d in todo:
            if stop is not None and stop():
                break
            if not fast:
                if walk == "pp":
                    pl["sel"][d], pl["null"][d] = _pp_select(c, events, mparts, d, bad, first_trade, mm,
                                                             owner_members, early_owners)
                else:
                    pl["sel"][d] = _ins_select(c, events, mparts, d, bad, first_trade)
                continue
            sel, pool, ins = f.advance(d)
            if walk == "pp":
                pool = sorted(pool - set(sel))
                k = min(len(pool), max(len(sel), int(c["null_k"])))
                rng = random.Random(int(c["null_seed"]) * 1_000_003 + int(d) // D)
                pl["sel"][d] = sel
                pl["null"][d] = {o: sorted(f.mem[o]) for o in rng.sample(pool, k)} if k else {}
            else:
                pl["sel"][d] = ins
    for walk in walks:
        timer(walk, lambda w=walk: sel_phase(w))
    members = set()
    for pl in plan.values():
        for x in list(pl["sel"].values()) + list(pl["null"].values()):
            for ms in x.values():
                members |= set(ms)
    trades = (trades_fn or (lambda ms: copy.wallet_trades(con, p, ms)))(members) if members else []
    by_w = defaultdict(list)
    for r in trades:
        by_w[r[0]].append(r)
    pr = prices or copy.Prices(con, p, c)
    for walk in walks:
        pl = plan[walk]
        out[walk] = timer(walk, lambda w=walk, pl=pl: _rows_phase(con, p, c, w, pl, days, by_w, pr, now))
        if out[walk].get("walked"):   # the inputs are stored only with the days they produced
            save_inputs(con, walk, pl["inp"])
        con.commit()
    return out


def _rows_phase(con, p, c, walk, pl, days, by_w, pr, now):
    """The rows of the days whose selection this pass computed (stored), the walk's state, the summary when it
    reached today. The selection is the costly part (stopped at the deadline); the rows of its days always follow."""
    table = "i2_pp_copy" if walk == "pp" else "i2_copy"
    walked = [d for d in days[pl["k0"]:] if d in pl["sel"]]
    first = days[pl["k0"]] if pl["k0"] < len(days) else None
    if first is not None and walked:
        con.execute(f"DELETE FROM {table} WHERE day >= ?", (store.day(first),))
    con.execute(f"DELETE FROM {table} WHERE day < ?", (store.day(days[0]),))
    variants = ("60s", "brzo", "null") if walk == "pp" else ("ins",)
    taken = {v: set() for v in variants}
    if walk == "pp":
        for v, t in store.q(con, "SELECT variant, token FROM i2_pp_copy"):
            taken.setdefault(v, set()).add(t)
    else:
        taken["ins"] = {t for (t,) in store.q(con, "SELECT token FROM i2_copy")}
    ca = copy.calls_after(p, {r[1] for rs in by_w.values() for r in rs}) if walk == "ins" else {}
    rt = copy.cost_rt(c)
    through = state(con, walk)["through"] if pl["k0"] > 0 else None
    for d in walked:
        rows = []
        for v in variants:
            chosen = pl["null"].get(d) or {} if v == "null" else pl["sel"].get(d) or {}
            for owner, ms in chosen.items():
                own = sorted((r for m in ms for r in by_w.get(m, [])), key=lambda r: r[2])
                before = {r[1] for r in own if r[2] < d}
                for r in own:
                    if not d <= r[2] < d + D or r[3] != "buy" or r[1] in before or r[1] in taken[v] or r[2] > now:
                        continue
                    taken[v].add(r[1])
                    if walk == "pp":
                        row = prijepumpe._copy_row(r, own, owner, pr, c, d, fast=(v == "brzo"))
                        rows.append((v, row["owner"], row["token"], row["buy_ts"], row.get("entry_ts"), row.get("mcap"),
                                     row.get("bucket"), row.get("ret"), row.get("ret_big"), row.get("exit"),
                                     row.get("miss"), row["day"], int(bool(row.get("assumed")))))
                    else:
                        sells = [s for s in own if s[1] == r[1] and s[3] == "sell" and s[2] > r[2]]
                        sim = copy.simulate(r, sells, pr, c, rt)
                        nxt = [t for t in ca.get(r[1], []) if t > r[2]]
                        cas = (nxt[0] - r[2]) if nxt else None
                        if sim:
                            rows.append((owner, r[1], r[2], sim["entry_ts"], sim["mcap"], copy.bucket_of(sim["mcap"]),
                                         int(sim["bonded"]), round(sim["ret"], 4), sim["exit"], cas, store.day(d)))
                        else:
                            rows.append((owner, r[1], r[2], None, None, "?", None, None, "bez cijene", cas,
                                         store.day(d)))
        if walk == "pp":
            con.executemany("INSERT OR REPLACE INTO i2_pp_copy (variant, owner, token, buy_ts, entry_ts, mcap, bucket, "
                            "ret, ret_big, exit, miss, day, assumed) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)
        else:
            con.executemany("INSERT OR REPLACE INTO i2_copy VALUES (?,?,?,?,?,?,?,?,?,?,?)", rows)
        through = d
    if through is not None:
        con.execute("INSERT OR REPLACE INTO i2_walk VALUES (?,?,?,?,?)",
                    (walk, int(through), version(c, walk), len(days), int(now)))
    con.commit()
    n = (days.index(through) + 1) if through in days else 0
    done = bool(days) and through == days[-1]
    return {"done": done, "through": through, "n": n, "m": len(days), "from": first, "why": pl["why"],
            "walked": len(walked),
            "summary": summary(con, c, walk) if done else None}


def rows_of(con, walk):
    if walk == "pp":
        keys = ("variant", "owner", "token", "buy_ts", "entry_ts", "mcap", "bucket", "ret", "ret_big", "exit", "miss",
                "day", "assumed")
        out = {"60s": [], "brzo": [], "null": []}
        for r in store.q(con, f"SELECT {', '.join(keys)} FROM i2_pp_copy ORDER BY day, buy_ts, token"):
            d = dict(zip(keys, r))
            d["assumed"] = bool(d.get("assumed"))
            out.setdefault(d["variant"], []).append(d)
        return out
    keys = ("owner", "token", "buy_ts", "entry_ts", "mcap", "bucket", "bonded", "ret", "exit", "call_after_s", "day")
    return [dict(zip(keys, r)) for r in store.q(con, f"SELECT {', '.join(keys)} FROM i2_copy ORDER BY day, buy_ts, "
                                                     "token")]


def summary(con, c, walk):
    if walk == "pp":
        return prijepumpe.summarize(rows_of(con, "pp"), c)
    return copy.summarize(rows_of(con, "ins"))


def progress(res):
    """'kopija: izračunato do <date> (<n> od <m> dana)' of a walk that has not reached today, else None."""
    if not res or res.get("done"):
        return None
    th = res.get("through")
    date = (store.day(th)[8:10] + "." + store.day(th)[5:7] + ".") if th else "—"
    return f"kopija: izračunato do {date} ({res.get('n', 0)} od {res.get('m', 0)} dana)"

