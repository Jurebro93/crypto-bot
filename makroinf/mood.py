"""The market mood of the macro influencers (15.11. navečer, the owner: "Interpretirati, klasterizirati pa reći 55 %
influencera na primjer je bullish, 45 % bearish, što znači da je neizvjesno ... Ali isto tako i prikazati iz čega su
izvučeni ti podaci i tablice, da budu uredne, strukturirane").

The rule (MOOD_RULES, versioned; the pages print it next to every statement):
  who counts   an account with at least one measurable market call whose POST TIME is in the window before t (the last
               24 h, the last 7 days). Not counted: unclear, joke, promotion, a withdrawal, and conditional calls (a
               condition is a plan, not a view of now)
  its side     the sign of the sum of its calls in the window (+1 up / the bottom is in, -1 down / the top is in, 0 a
               range): bikovski, medvjeđi, neutralno (a tie is neutral)
  shares       unweighted (every account one vote) and weighted by accuracy: the account's shrunk hit rate
               (score.py, the average for one without measured episodes) over the average, every cluster of
               look-alike accounts (index.clusters: the same text, quoting, the same calls at the same time) capped at
               cluster_cap weight together, so a group of copies is one voice
  the verdict  on the bull / bear split (neutral reported apart): >= 65 % on one side = jasan stav, more than 55 % =
               blagi stav, 55 % or less = neizvjesno (the owner's example 55 / 45 is neizvjesno); neutral >= 50 % of
               the accounts = uglavnom neutralno; fewer than min_accounts accounts with a side = premalo podataka
Every statement carries its source ("Iz čega je izvučeno"): the counts, the accounts on each side and the posts.
Also: the same per asset (7 days), the stance changes (an account whose newest call in the last 7 days points the
other way than its call before; within 60 days, same asset) and the daily series (mood_d).
compute(t) for any t: the app shows t = now, the public pages t = now - 7 days (the existing rule: stances and the
consensus are public with a 7-day delay; the topics of the day are not stances and are public the same day).
"""
import bisect
import json
import time

from makroinf import index, rules, store

D = 86400
MOOD_RULES = {"version": "raspolozenje-v1 (15.11.2026.)", "clear": 0.65, "mild": 0.55, "neutral_majority": 0.5,
              "min_accounts": 5, "windows_h": {"24h": 24, "7d": 168}, "flip_lookback_d": 60, "posts_per_account": 5,
              "cluster_cap": index.INDEX_LOCKED["cluster_cap"]}
ASSETS = ("BTC", "ETH", "SOL", "alts", "memes", "total")
GROUP = {"BTC": "BTC", "total": "BTC", "ETH": "ETH", "SOL": "SOL", "alts": "alts", "memes": "memes"}
SIDES = ("bik", "medvjed", "neutralno")
VERDICT = {"hr": {"jasno_bik": "Jasno bikovski", "blago_bik": "Blago bikovski", "neizvjesno": "Neizvjesno",
                  "blago_medvjed": "Blago medvjeđe", "jasno_medvjed": "Jasno medvjeđe",
                  "neutralno": "Uglavnom neutralno", "premalo": "Premalo podataka"},
           "en": {"jasno_bik": "Clearly bullish", "blago_bik": "Mildly bullish", "neizvjesno": "Uncertain",
                  "blago_medvjed": "Mildly bearish", "jasno_medvjed": "Clearly bearish",
                  "neutralno": "Mostly neutral", "premalo": "Too little data"}}
TONE = {"jasno_bik": "good", "blago_bik": "good", "jasno_medvjed": "bad", "blago_medvjed": "bad"}


def verdict(bull, bear, neutral, R=MOOD_RULES):
    """The verdict key of counts (or weights) on each side."""
    side = bull + bear
    tot = side + neutral
    if side <= 0 or (tot and neutral / tot >= R["neutral_majority"]):
        return "neutralno" if tot else "premalo"
    b = bull / side
    dom = max(b, 1 - b)
    if dom >= R["clear"]:
        return "jasno_bik" if b > 0.5 else "jasno_medvjed"
    if dom > R["mild"]:
        return "blago_bik" if b > 0.5 else "blago_medvjed"
    return "neizvjesno"


def rule_text(lang="hr", R=MOOD_RULES):
    c, m, nb = round(R["clear"] * 100), round(R["mild"] * 100), "\u00a0"
    if lang == "en":
        return (f"Rule: {c}{nb}% or more on one side = a clear view, more than {m}{nb}% = a mild view, {m}{nb}% or "
                f"less = uncertain (55{nb}/{nb}45 is uncertain). Neutral is counted apart.")
    return (f"Pravilo: {c}{nb}% ili više na jednoj strani = jasan stav, više od {m}{nb}% = blagi stav, {m}{nb}% ili "
            f"manje = neizvjesno (55{nb}/{nb}45 je neizvjesno). Neutralni se broje zasebno.")


class Calls:
    """The calls sorted by post time, for fast windows."""

    def __init__(self, calls):
        self.calls = sorted((c for c in calls if c.get("ts") is not None), key=lambda c: (c["ts"], str(c["id"])))
        self.ts = [c["ts"] for c in self.calls]

    def window(self, t0, t1):
        return self.calls[bisect.bisect_left(self.ts, t0):bisect.bisect_left(self.ts, t1)]


def countable(c):
    return not (rules.skip_reason(c) or c.get("withdraws") or c.get("conditional"))


def sides(calls, assets=None, per=MOOD_RULES["posts_per_account"]):
    """{handle: {"s": +1/0/-1, "n": calls, "ids": [newest post ids], "ts": newest}} of the countable calls."""
    out = {}
    for c in calls:
        if not countable(c) or (assets and c["asset"] not in assets):
            continue
        x = out.setdefault(c["handle"], {"sum": 0, "n": 0, "ids": [], "ts": 0})
        x["sum"] += rules.SIGN.get(c["direction"], 0)
        x["n"] += 1
        x["ts"] = max(x["ts"], c["ts"])
        if str(c["id"]) not in x["ids"]:
            x["ids"].append(str(c["id"]))
    for x in out.values():
        x["s"] = (x["sum"] > 0) - (x["sum"] < 0)
        x["ids"] = x["ids"][::-1][:per]   # newest first
        del x["sum"]
    return out


def weights(st, acc, cl, R=MOOD_RULES):
    """{handle: weight}: accuracy over the average, each cluster capped at cluster_cap together."""
    known = [a for a in acc.values() if a is not None]
    avg = (sum(known) / len(known)) if known else 0.5
    raw = {h: (acc.get(h) if acc.get(h) is not None else avg) / (avg or 0.5) for h in st}
    tot = {}
    for h, w in raw.items():
        k = cl.get(h, h)
        tot[k] = tot.get(k, 0.0) + w
    return {h: w * min(1.0, R["cluster_cap"] / tot[cl.get(h, h)]) if tot[cl.get(h, h)] > 0 else 0.0
            for h, w in raw.items()}


def block(st, acc, cl, R=MOOD_RULES):
    """One statement: counts, shares (unweighted / weighted), verdicts, and its source (accounts and posts per side)."""
    n = {k: 0 for k in SIDES}
    wsum = {k: 0.0 for k in SIDES}
    srcs = {k: [] for k in SIDES}
    w = weights(st, acc, cl, R)
    for h, x in st.items():
        k = "bik" if x["s"] > 0 else "medvjed" if x["s"] < 0 else "neutralno"
        n[k] += 1
        wsum[k] += w.get(h, 0.0)
        srcs[k].append({"h": h, "n": x["n"], "ids": x["ids"], "w": round(w.get(h, 0.0), 3), "ts": x["ts"]})
    tot, wt = sum(n.values()), sum(wsum.values())
    side, wside = n["bik"] + n["medvjed"], wsum["bik"] + wsum["medvjed"]
    for k in SIDES:
        srcs[k].sort(key=lambda r: (-r["w"], -r["n"], r["h"].lower()))
    return {"n": tot, "broj": n, "udio": {k: (n[k] / tot if tot else None) for k in SIDES},
            "udio_pond": {k: (wsum[k] / wt if wt else None) for k in SIDES},
            "strane": {"bik": n["bik"] / side if side else None, "medvjed": n["medvjed"] / side if side else None},
            "strane_pond": {"bik": wsum["bik"] / wside if wside else None,
                            "medvjed": wsum["medvjed"] / wside if wside else None},
            "presuda": "premalo" if n["bik"] + n["medvjed"] < R["min_accounts"] else verdict(n["bik"], n["medvjed"],
                                                                                              n["neutralno"], R),
            "presuda_pond": "premalo" if n["bik"] + n["medvjed"] < R["min_accounts"] else verdict(
                wsum["bik"], wsum["medvjed"], wsum["neutralno"], R),
            "objava": sum(r["n"] for k in SIDES for r in srcs[k]), "racuni": srcs}


def flips(cs, t, R=MOOD_RULES, limit=30):
    """Accounts whose newest call in the last 7 days points the other way than their call before (same asset group,
    the earlier one within flip_lookback_d)."""
    win = cs.window(t - 7 * D, t)
    before = cs.window(t - (7 + R["flip_lookback_d"]) * D, t - 7 * D)
    last_before = {}
    for c in before:
        if countable(c) and rules.SIGN.get(c["direction"], 0):
            last_before[(c["handle"], GROUP[c["asset"]])] = c
    newest = {}
    for c in win:
        if countable(c) and rules.SIGN.get(c["direction"], 0):
            newest[(c["handle"], GROUP[c["asset"]])] = c
    out = []
    for key, c in newest.items():
        p = last_before.get(key)
        if p and rules.SIGN[p["direction"]] != rules.SIGN[c["direction"]]:
            out.append({"h": key[0], "asset": key[1], "prije": p["direction"], "prije_ts": p["ts"],
                        "prije_id": str(p["id"]), "sada": c["direction"], "sada_ts": c["ts"], "sada_id": str(c["id"])})
    out.sort(key=lambda x: -x["sada_ts"])
    return out[:limit]


def active_accounts(con, t0, t1):
    r = store.q(con, "SELECT COUNT(DISTINCT t.handle) FROM tweets t JOIN accounts a ON a.handle = t.handle WHERE "
                     "a.status IN ('aktivan', 'neaktivan') AND t.ts >= ? AND t.ts < ?", (int(t0), int(t1)))
    return int(r[0][0]) if r else 0


def accuracy(con):
    """{handle: shrunk hit rate} of the last scoring (None without decided outcomes)."""
    out = {}
    for h, data in store.q(con, "SELECT handle, data FROM scores"):
        try:
            p = (json.loads(data) or {}).get("prediktivno") or {}
        except ValueError:
            continue
        out[h] = p.get("skupljeno") if p.get("n_tezinski") else None
    return out


def compute(con, t, calls=None, acc=None, cl=None, R=MOOD_RULES):
    """The mood as of t: {"t", "okviri": {"24h", "7d"}, "po_imovini": {asset: block (7 d)}, "promjene", "aktivnih"}."""
    cs = calls if isinstance(calls, Calls) else Calls(calls if calls is not None else index.load_calls(con))
    acc = acc if acc is not None else accuracy(con)
    cl = cl if cl is not None else (store.kv_json(con, "klasteri", {}) or {})
    out = {"t": int(t), "rules_v": R["version"], "okviri": {}, "po_imovini": {}, "aktivnih": {}}
    for key, hrs in R["windows_h"].items():
        win = cs.window(t - hrs * 3600, t)
        out["okviri"][key] = block(sides(win), acc, cl, R)
        out["aktivnih"][key] = active_accounts(con, t - hrs * 3600, t)
    win7 = cs.window(t - 7 * D, t)
    for a in ASSETS:
        out["po_imovini"][a] = block(sides(win7, {a}), acc, cl, R)
    out["promjene"] = flips(cs, t, R)
    return out


def series(cs, acc, cl, t_end, days=14, R=MOOD_RULES):
    """[(day, block 24 h)] at each UTC day's end for the last `days` days (oldest first), compact (no sources)."""
    out = []
    end = int(t_end) // D * D
    for k in range(days - 1, -1, -1):
        t = end - k * D
        b = block(sides(cs.window(t - D, t)), acc, cl, R)
        out.append((t, {x: b[x] for x in ("n", "broj", "udio", "strane", "strane_pond", "presuda", "presuda_pond")}))
    return out


def refresh(con, now=None, calls=None):
    """After a scoring: kv raspolozenje (t = now, the app), raspolozenje_javno (t = now - 7 days, the public pages),
    the day's row in mood_d and the 14-day series of both. Returns the fresh mood."""
    now = int(now or time.time())
    cs = Calls(calls if calls is not None else index.load_calls(con))
    acc = accuracy(con)
    cl = store.kv_json(con, "klasteri", {}) or {}
    fresh = compute(con, now, cs, acc, cl)
    fresh["ts"] = now
    fresh["niz"] = series(cs, acc, cl, now)
    late = compute(con, now - 7 * D, cs, acc, cl)
    late["ts"] = now
    late["niz"] = series(cs, acc, cl, now - 7 * D)
    store.kv(con, "raspolozenje", fresh)
    store.kv(con, "raspolozenje_javno", late)
    day = now // D * D
    for win, b in fresh["okviri"].items():
        con.execute("INSERT OR REPLACE INTO mood_d VALUES (?,?,?,?)", (day, win, now, json.dumps(
            {k: b[k] for k in ("n", "broj", "udio", "strane", "strane_pond", "presuda", "presuda_pond")},
            ensure_ascii=False)))
    return fresh


def load(con=None, public=False):
    """The stored mood (fresh for the app, the 7-day-old one for the public pages) or None."""
    own = con is None
    con = con or store.ro()
    if con is None:
        return None
    try:
        return store.kv_json(con, "raspolozenje_javno" if public else "raspolozenje")
    finally:
        if own:
            con.close()


def line(m, lang="hr"):
    """One plain sentence of a block: "Od 120 računa sa stavom 55 % je bikovsko, 45 % medvjeđe (8 neutralnih):
    neizvjesno." """
    if not m or not m.get("n"):
        return "Još nema računa sa stavom u ovom razdoblju." if lang == "hr" else "No account stated a view in this period."
    b = m["broj"]
    side = b["bik"] + b["medvjed"]
    pb = round(100 * b["bik"] / side) if side else 0
    pm = 100 - pb if side else 0
    word = VERDICT[lang][m["presuda"]].lower()
    if lang == "en":
        return (f"Of {side} accounts with a side, {pb}\u00a0% are bullish and {pm}\u00a0% bearish "
                f"({b['neutralno']} neutral): {word}.")
    return (f"Od {side} računa s jasnom stranom {pb}\u00a0% je bikovsko, {pm}\u00a0% medvjeđe "
            f"({b['neutralno']} neutralnih): {word}.")
