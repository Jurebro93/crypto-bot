"""From measured calls to: first-call flags, call groups, KOL call power, co-calling pairs, correlations and
the kol_group signal for the hype score.

Call power (0-100) uses only a KOL's own first call per token, and only kind "call" (brags are counted apart):
  hit      share of calls that went at least +50% within 24 h
  max24    median best move within 24 h (+200% = full points)
  r1h      median move after 1 h (+50% = full)
  vol_lift median volume in the hour after the call vs the hour before (8x = full, log scale)
  first    share of calls where he was the first author we saw on that token
  no_rug   share of calls that did not lose 90%
  prepump  share of calls made after the price had already doubled in 2 h (subtracted: late or paid)
With few calls the score is pulled towards prior_score (below good_score): weight n / (n + prior_calls), so one
lucky call is not enough to count as a good KOL.

Power per follower ("Moć/pratitelj"): the KOL's median impact (1 h move and volume lift) divided by
log10(followers), relative to the median KOL. 2.0x = moves the price twice as much as his audience size predicts.
"""
import itertools
import json
import math
import statistics
import time

H = 3600


def _clip(x):
    return max(0.0, min(1.0, x))


def _med(xs):
    xs = [x for x in xs if x is not None]
    return statistics.median(xs) if xs else None


def mark_first(con):
    """first_by_kol: the KOL's earliest call (not brag) on that token. first_overall: earliest caller on that token."""
    con.execute("""UPDATE calls SET first_by_kol = kind = 'call' AND tweet_id = (SELECT c2.tweet_id FROM calls c2
        WHERE c2.token = calls.token AND c2.handle = calls.handle AND c2.kind = 'call' ORDER BY c2.ts, c2.tweet_id LIMIT 1)""")
    con.execute("""UPDATE calls SET first_overall = kind = 'call' AND ts = (SELECT MIN(c2.ts) FROM calls c2
        WHERE c2.token = calls.token AND c2.kind = 'call')""")


def impact(c):
    """0..1 how much one call moved things in the first hour."""
    parts = []
    if c.get("r1h") is not None:
        parts.append(_clip(c["r1h"] / 1.0))
    if c.get("vol_lift"):
        parts.append(_clip(math.log2(max(c["vol_lift"], 1)) / 3))
    return sum(parts) / len(parts) if parts else None


def kol_stats(calls, cfg):
    """Stats and raw (unshrunk) score for one KOL from his first calls (dicts with the calls columns)."""
    mine = [c for c in calls if c["kind"] == "call" and c["first_by_kol"]]
    measured = [c for c in mine if c["max24"] is not None]
    brags = sum(1 for c in calls if c["kind"] == "brag")
    s = {"calls": len(mine), "measured": len(measured), "tokens": len({c["token"] for c in calls}), "brags": brags,
         "tweets": len(calls)}
    if not measured:
        return s, None
    w = cfg["weights"]
    s["hit_rate"] = sum(1 for c in measured if c["max24"] >= cfg["hit_x"]) / len(measured)
    s["med_max24"] = _med(c["max24"] for c in measured)
    s["med_r1h"] = _med(c["r1h"] for c in measured)
    s["med_lift"] = _med(c["vol_lift"] for c in measured)
    s["rug_rate"] = sum(1 for c in measured if c["rug"]) / len(measured)
    pre = [c for c in measured if c["pre2h"] is not None]
    s["prepump_rate"] = (sum(1 for c in pre if c["pre2h"] >= cfg["prepump_x"]) / len(pre)) if pre else 0.0
    s["first_rate"] = sum(1 for c in measured if c["first_overall"]) / len(measured)
    s["med_impact"] = _med(impact(c) for c in measured)
    s["med_views"] = _med(c["views"] or None for c in mine)
    eng = [((c["likes"] or 0) + 2 * (c["retweets"] or 0)) / c["followers"] for c in mine if c["followers"]]
    s["eng_rate"] = _med(eng)
    parts = {
        "hit": w["hit"] * s["hit_rate"],
        "max24": w["max24"] * _clip((s["med_max24"] or 0) / 2),
        "r1h": w["r1h"] * _clip((s["med_r1h"] or 0) / 0.5),
        "vol_lift": w["vol_lift"] * _clip(math.log2(max(s["med_lift"] or 1, 1)) / 3),
        "first": w["first"] * s["first_rate"],
        "no_rug": w["no_rug"] * (1 - s["rug_rate"]),
        "prepump": w["prepump"] * s["prepump_rate"],
    }
    s["parts"] = {k: round(v, 1) for k, v in parts.items()}
    return s, max(0.0, min(100.0, sum(parts.values())))


def _rows(con, sql, args=()):
    cur = con.execute(sql, args)
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in cur]


def score_kols(con, cfg, now=None):
    now = now or int(time.time())
    by = {}
    for c in _rows(con, "SELECT * FROM calls"):
        by.setdefault(c["handle"], []).append(c)
    stats = {h: kol_stats(cs, cfg) for h, cs in by.items()}
    prior = cfg["prior_score"]
    foll = dict(con.execute("SELECT handle, COALESCE(followers, 0) FROM kols"))
    ratios = {}
    for h, (s, raw) in stats.items():
        if s.get("med_impact") is not None:
            ratios[h] = s["med_impact"] / math.log10(max(foll.get(h) or 0, 100))
    base_ratio = statistics.median([r for h, r in ratios.items() if stats[h][0]["measured"] >= 2] or
                                   list(ratios.values()) or [0]) or None
    for h, (s, raw) in stats.items():
        score = None
        if raw is not None:
            k = s["measured"] / (s["measured"] + cfg["prior_calls"])
            score = round(k * raw + (1 - k) * prior, 1)
            s["raw"], s["prior"], s["confidence"] = round(raw, 1), round(prior, 1), round(k, 2)
        rel = round(ratios[h] / base_ratio, 2) if h in ratios and base_ratio else None
        con.execute("UPDATE kols SET score=?, power_rel=?, stats=?, updated=? WHERE handle=?",
                    (score, rel, json.dumps(s), now, h))
    return len(stats)


def find_groups(calls, secs):
    """calls: [(token, ts, handle)] sorted by token, ts. Yields (token, start, end, [handles in order])."""
    for token, it in itertools.groupby(calls, key=lambda c: c[0]):
        cur = None
        for _, ts, h in it:
            if cur and ts - cur[0] <= secs:
                cur[1] = ts
                if h not in cur[2]:
                    cur[2].append(h)
            else:
                if cur and len(cur[2]) >= 2:
                    yield token, cur[0], cur[1], cur[2]
                cur = [ts, ts, [h]]
        if cur and len(cur[2]) >= 2:
            yield token, cur[0], cur[1], cur[2]


def build_groups(con, cfg):
    scores = dict(con.execute("SELECT handle, score FROM kols"))
    calls = con.execute("SELECT token, ts, handle FROM calls WHERE kind = 'call' ORDER BY token, ts").fetchall()
    con.execute("DELETE FROM groups")
    n = 0
    for token, start, end, hs in find_groups(calls, cfg["group_secs"]):
        first = con.execute("SELECT mcap0, r1h, max24, vol_lift FROM calls WHERE token = ? AND ts = ? LIMIT 1",
                            (token, start)).fetchone() or (None,) * 4
        fl = con.execute("SELECT COALESCE(SUM(insiders), 0), COALESCE(SUM(rotation_selling), 0) FROM flows "
                         "WHERE token = ? AND ts BETWEEN ? AND ?", (token, start, end)).fetchone()
        good = sum(1 for h in hs if (scores.get(h) or 0) >= cfg["good_score"])
        con.execute("INSERT INTO groups VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (token, start, end, len(hs), json.dumps(hs), hs[0], good, *first, fl[0], int(fl[1] > 0 or fl[0] >= 2)))
        n += 1
    return n


def pairs(con, min_together=2, limit=30):
    """KOL pairs that often call the same token within the group window: [(a, b, times, tokens)]."""
    cnt = {}
    for token, hs in con.execute("SELECT token, handles FROM groups"):
        for a, b in itertools.combinations(sorted(set(json.loads(hs))), 2):
            cnt.setdefault((a, b), set()).add(token)
    out = sorted(((a, b, len(t), sorted(t)) for (a, b), t in cnt.items() if len(t) >= min_together),
                 key=lambda x: -x[2])
    return out[:limit]


def build_signals(con, cfg, now=None):
    """kol_group feature per token from groups in the last signal_hours: 2 good KOLs = 1.0, each other author +0.1
    (at most 0.5: a swarm of unknown accounts is often one paid campaign), dev selling = 0. Then times the learned
    factor of the session the group started in (kol/sessions.py)."""
    from kol import sessions
    now = now or int(time.time())
    fac = sessions.factors(con)
    con.execute("DELETE FROM signals")
    rows = con.execute("SELECT token, start_ts, n_authors, handles, good_authors, dev_selling FROM groups "
                       "WHERE start_ts >= ? ORDER BY start_ts", (now - cfg["signal_hours"] * H,)).fetchall()
    for token, start, n, hs, good, dev in rows:  # newest group per token wins
        feat = 0.0 if dev else min(1.0, (good / 2 + 0.1 * min(n - good, 5)) * fac[sessions.session_of(start)])
        con.execute("INSERT OR REPLACE INTO signals VALUES (?,?,?,?,?,?,?)", (token, start, good, n, hs, dev, round(feat, 2)))
    return len(rows)


def _rank(xs):
    order = sorted(range(len(xs)), key=lambda i: xs[i])
    r = [0.0] * len(xs)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and xs[order[j + 1]] == xs[order[i]]:
            j += 1
        for k in range(i, j + 1):
            r[order[k]] = (i + j) / 2
        i = j + 1
    return r


def spearman(xs, ys):
    if len(xs) < 5:
        return None
    rx, ry = _rank(xs), _rank(ys)
    mx, my = statistics.mean(rx), statistics.mean(ry)
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    den = math.sqrt(sum((a - mx) ** 2 for a in rx) * sum((b - my) ** 2 for b in ry))
    return round(num / den, 2) if den else None


FEATURES = [
    ("Pratitelji (log)", lambda c, g: math.log10(max(c["followers"] or 0, 1))),
    ("Autora u grupi", lambda c, g: g.get((c["token"], c["ts"]), 1)),
    ("Prvi autor na tokenu", lambda c, g: c["first_overall"] or 0),
    ("Rast 2 h prije poziva", lambda c, g: c["pre2h"]),
    ("Mcap u pozivu (log)", lambda c, g: math.log10(c["mcap0"]) if c["mcap0"] else None),
    ("Lajkovi (log)", lambda c, g: math.log10(1 + (c["likes"] or 0))),
    ("Pregledi (log)", lambda c, g: math.log10(1 + (c["views"] or 0)) if c["views"] else None),
    ("Pronađen samo po tickeru", lambda c, g: 1 if c["match"] == "ticker" else 0),
]


def correlations(con):
    """Spearman correlation of each call feature with the best move within 24 h, over measured first calls."""
    calls = _rows(con, "SELECT * FROM calls WHERE kind = 'call' AND first_by_kol = 1 AND max24 IS NOT NULL")
    by_token = {}
    for token, start, end, n in con.execute("SELECT token, start_ts, end_ts, n_authors FROM groups"):
        by_token.setdefault(token, []).append((start, end, n))
    gsize = {(c["token"], c["ts"]): n for c in calls for start, end, n in by_token.get(c["token"], ())
             if start <= c["ts"] <= end}
    out = []
    for name, fn in FEATURES:
        xs, ys = [], []
        for c in calls:
            x = fn(c, gsize)
            if x is not None:
                xs.append(x)
                ys.append(c["max24"])
        out.append((name, spearman(xs, ys), len(xs)))
    return out


def reclassify(con, bots=()):
    """Apply the current call/brag/warn rule and the bot flag to every stored post, so a better rule also fixes old
    rows (posts of automated accounts become kind 'bot'; an account no longer flagged gets its calls back)."""
    from kol.collect import kind_of
    bots = set(bots)
    rows = con.execute("SELECT DISTINCT tweet_id, handle, text, kind FROM calls "
                       "WHERE kind IN ('call', 'brag', 'warn', 'bot')").fetchall()
    for tid, h, text, kind in rows:
        k = "bot" if h in bots else kind_of(text)
        if k != kind:
            con.execute("UPDATE calls SET kind = ? WHERE tweet_id = ?", (k, tid))


def build_watch(con, cfg, now=None):
    """Live watchlist: the best KOLs by call power with enough measured calls, who call early (few calls after
    the price already doubled) and hit often. Size is watch.size (each costs ~$0.11/day to follow live)."""
    now = now or int(time.time())
    w = cfg["watch"]
    old = dict(con.execute("SELECT handle, since FROM watch"))
    picked = []
    for h, sc, st in con.execute("SELECT handle, score, stats FROM kols WHERE score >= ? AND handle NOT LIKE 'tg:%' "
                                 "AND handle NOT LIKE 'w:%' ORDER BY score DESC",
                                 (cfg["good_score"],)):
        s = json.loads(st or "{}")
        if (s.get("measured", 0) >= w["min_calls"] and s.get("prepump_rate", 1) <= w["max_prepump"]
                and s.get("hit_rate", 0) >= w["min_hit"]):
            why = (f"{s['measured']} poziva, pogodak {s['hit_rate']:.0%}, medijan max 24 h {s['med_max24']:+.0%}, "
                   f"kasnih {s['prepump_rate']:.0%}")
            picked.append((h, sc, old.get(h, now), why))
        if len(picked) >= w["size"]:
            break
    con.execute("DELETE FROM watch")
    con.executemany("INSERT INTO watch VALUES (?,?,?,?)", picked)
    return [p[0] for p in picked]


def drop_fake_tokens(con):
    """Calls on "tokens" that were the tail of an EVM address (0x...): see collect.cas_in. Returns rows deleted."""
    from kol.collect import _HEX
    fake = [t for (t,) in con.execute("SELECT DISTINCT token FROM calls WHERE token LIKE 'x%' OR token LIKE 'X%'")
            if _HEX.fullmatch(t)]
    n = 0
    for t in fake:
        n += con.execute("DELETE FROM calls WHERE token = ?", (t,)).rowcount
        for table in ("tokens", "groups", "signals", "converge", "token_hours"):
            con.execute(f"DELETE FROM {table} WHERE token = ?", (t,))
    return n


def run(con, cfg, now=None):
    from kol import bots, measure
    drop_fake_tokens(con)
    reclassify(con, bots.detect(con, cfg))
    measure.revalidate(con, cfg)
    mark_first(con)
    n = score_kols(con, cfg, now)
    from kol import sessions
    sessions.zones(con, cfg)
    sessions.learn(con, cfg, now)
    build_watch(con, cfg, now)
    g = build_groups(con, cfg)
    s = build_signals(con, cfg, now)
    con.commit()
    return n, g, s
