"""What each strategy would buy right now. Read-only on kol.db, tg.db, hype.db and paper.db; no network, no cost.

Every reader returns [(token, ts, who, score)]: the token, when the signal happened, a short reason shown on the page
and a priority (higher first when a strategy's hourly cap is tight).
"""
import json
import os
import random
import sqlite3

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _path(name, env):
    return os.environ.get(env) or os.path.join(ROOT, name)


def _ro(path):
    if not os.path.exists(path) or not os.path.getsize(path):
        return None
    try:
        return sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=10)
    except sqlite3.OperationalError:
        return None


def _q(con, sql, args=()):
    if con is None:
        return []
    try:
        return con.execute(sql, args).fetchall()
    except sqlite3.OperationalError:
        return []


def _ok(tok):
    return bool(tok) and 32 <= len(tok) <= 50


class Sources:
    """One read of every source for one pass; paths can be overridden (tests)."""

    def __init__(self, kol_db=None, tg_db=None, hype_db=None, paper_db=None):
        self.kol_db = kol_db or _path("kol.db", "KOL_DB")
        self.tg_db = tg_db or _path("tg.db", "TG_DB")
        self.hype_db = hype_db or _path("hype.db", "HYPE_DB")
        self.paper_db = paper_db or _path("paper.db", "PAPER_DB")

    def read(self, now, window_s):
        since = now - window_s
        kc, tc, hc, pc = (_ro(p) for p in (self.kol_db, self.tg_db, self.hype_db, self.paper_db))
        try:
            from kol import bots as _bots
            bad = _bots.handles(kc)   # scanner bots + hacked spam accounts, paid-group sellers, self-pumping devs
            scores = dict(_q(kc, "SELECT handle, COALESCE(score, 0) FROM kols"))
            names = {w: (tw and "@" + tw) or name or w[:6]
                     for w, tw, name in _q(kc, "SELECT wallet, twitter, name FROM kol_ids")}

            wallets = [(m, int(ts), "novčanik " + names.get(w, w[:6] + "…"), 0)
                       for w, m, ts in _q(hc, "SELECT wallet, mint, ts FROM chain_trades WHERE side='buy' AND ts >= ?",
                                          (since,)) if _ok(m) and ts]

            kols = []
            for tok, ts, h in _q(kc, "SELECT token, ts, handle FROM calls WHERE kind='call' AND ts >= ?", (since,)):
                if h not in bad and not h.startswith("w:"):
                    kols.append((tok, int(ts), h, scores.get(h) or 0))
            for h, ca, ts in _q(hc, "SELECT handle, ca, ts FROM kol_mentions WHERE ts >= ? AND ca != ''", (since,)):
                if h not in bad:
                    kols.append((ca, int(ts), h, scores.get(h) or 0))
            for ch, ts, cas, fwd in _q(tc, "SELECT channel, ts, cas, fwd_from FROM posts WHERE ts >= ? AND cas != ''",
                                       (since,)):
                h = f"tg:{ch}"
                if fwd or h in bad:
                    continue
                for ca in (cas or "").split(","):
                    kols.append((ca, int(ts), h, scores.get(h) or 0))
            kols = [k for k in kols if _ok(k[0]) and k[1]]

            tool = []
            for tok, ts, cfg in _q(pc, "SELECT token, opened_ts, config FROM trades WHERE opened_ts >= ?", (since,)):
                try:
                    mode = json.loads(cfg or "{}").get("entry_mode") or "ocjena"
                except ValueError:
                    mode = "ocjena"
                if mode != "konv" and _ok(tok):   # konv = bought because of KOL convergence, that is not the tool's pick
                    tool.append((tok, int(ts), "demo bot kupio (" + mode + ")", 1))

            scored = [(t, int(ts), f"ocjena {sc:.0f}", sc or 0)
                      for t, ts, sc in _q(hc, "SELECT token, ts, score FROM hype_signals WHERE ts >= ?", (since,))
                      if _ok(t) and ts]
        finally:
            for c in (kc, tc, hc, pc):
                if c is not None:
                    c.close()
        return {"novcanici": wallets, "kol": kols, "alat": tool, "scored": scored}


def mix(src, min_score, window_s):
    """Tokens that at least two of the three groups (wallets, KOLs, the tool) flagged within window_s of each other.
    For the tool, a hype score >= the demo's min_score counts too, not only an actual demo buy."""
    first = {}   # token -> {group: earliest ts}
    groups = {"novčanici": src.get("novcanici", []), "KOL": src.get("kol", []), "alat": src.get("alat", []) +
              [s for s in src.get("scored", []) if s[3] >= min_score]}
    for g, evs in groups.items():
        for tok, ts, _who, _sc in evs:
            d = first.setdefault(tok, {})
            d[g] = min(ts, d.get(g, ts))
    out = []
    for tok, d in first.items():
        if len(d) < 2:
            continue
        ts = sorted(d.values())
        if ts[1] - ts[0] <= window_s:
            out.append((tok, ts[1], " + ".join(sorted(d)), len(d)))   # the moment the second group agreed
    return out


def random_pick(src, now, last_ts, every_s, seed=None):
    """Control group: one random token the scanner saw in the last 10 minutes, at most once every every_s."""
    if last_ts and now - last_ts < every_s:
        return []
    pool = sorted({t for t, ts, _w, _s in src.get("scored", []) if now - ts <= 600})
    if not pool:
        return []
    rnd = random.Random(seed if seed is not None else int(now))
    return [(rnd.choice(pool), int(now), "nasumičan izbor", 0)]
