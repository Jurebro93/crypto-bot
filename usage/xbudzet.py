"""X budžet (27.11.2026., vlasnik): every X read (twitterapi.io and the Apify X actors) under ONE budget of at most
5 $ a UTC day and 100 $ a calendar month (UTC), both hard; the month cap wins. It replaces the 5-day social window
of ops/drustveni (19.11., abolished the same day): the influencer, X and Telegram jobs run every day again, and this
budget is what stops them.

Priorities (share of the day's limit; CATS):
  1 pozivi      ~50 %  influencer calls of tokens we track (midcaps 2M+, tokens our watched wallets buy): who calls,
                       the exact time, for call power (veliki/moc), the deleted-post checks, the crews and the
                       wallet <-> influencer linking (kol/novcanici_x, insajderi/kolwallets)
  2 otkrivanje  ~30 %  new influencers (winners, trending, followings, audits; accounts that call right after our
                       watched pre-pump wallets bought) and the tracked influencers' timelines, daily
  3 ostatak     ~20 %  macro influencers (makroinf, approved again by the owner within this budget) and the general X
                       scan (scan/xmom)

Limit of the day L = min(DAY_USD, MONTH_USD - what the month spent before today): today can never take the month
past its cap. Category c may spend share_c * L plus what the categories above it left unused. "Unused" grows with the
UTC day: of a higher category's share, the part it should have used by now (share * L * elapsed fraction of the day)
and did not use rolls down, so a quiet morning of priority 1 does not let priority 3 take priority 1's whole day; at
the end of the day all of it has rolled. Nothing rolls up and nothing rolls into the next day.

A paid read asks first (room / need with the most the request can cost), then books what it cost (book). Without a
persistent place (no XBUDZET_DB, USAGE_DB or DATA_DIR: a laptop, the offline tests) nothing is counted and the
budget is open, like the other gates. The ledger: usage.db tables xb_spend (day, cat, job, usd, calls) and xb_stat
(day, key, n: calls captured, new influencers found). One line a day (run_usage dnevno, usage/daily):
  "X budžet 2026-11-27: pozivi 2,10/2,50 $ (moc 1,20, ...), ... | dan 4,02/5,00 $, mjesec 61,30/100,00 $ |
   uhvaćeno poziva 37, novih influencera 4"
"""
import math
import os
import sqlite3
import time

DAY_USD = 5.0
MONTH_USD = 100.0
SINCE = "27.11.2026."
# (key, share, what) in priority order
CATS = (("pozivi", 0.50, "pozivi influencera na naše tokene (midcapovi 2M+, tokeni naših novčanika)"),
        ("otkrivanje", 0.30, "novi influenceri i dnevni timelineovi praćenih"),
        ("ostatak", 0.20, "makro influenceri i opći X sken (ostatak)"))
KEYS = tuple(c[0] for c in CATS)
DEFAULT_CAT = "ostatak"   # a read nobody named a category for gets the leftover share
SCHEMA = """
CREATE TABLE IF NOT EXISTS xb_spend (day TEXT, cat TEXT, job TEXT, usd REAL, calls INTEGER,
  PRIMARY KEY (day, cat, job));
CREATE TABLE IF NOT EXISTS xb_stat (day TEXT, key TEXT, n INTEGER, PRIMARY KEY (day, key));
"""
# the Apify X sources (hype/apify.json daily_usd) and their category; the others (gmgn, google_trends...) are not X
APIFY_X = {"kol_monitor": "pozivi", "kol_backfill": "pozivi", "kol_search": "otkrivanje",
           "kol_timeline": "otkrivanje", "kol_stars": "otkrivanje", "x_buzz": "ostatak", "x_trends": "ostatak"}


class Cap(Exception):
    """The X budget (day, month or this category's share) has no room for this read."""


# ---------- settings ---------------------------------------------------------------------------------------------------

def _env_cap(name, hard):
    """An env value may only LOWER the owner's cap (never raise it)."""
    try:
        v = float(os.environ.get(name, hard))
        return min(hard, v) if math.isfinite(v) and v >= 0 else hard
    except (TypeError, ValueError):
        return hard


def day_cap():
    return _env_cap("X_DAY_USD", DAY_USD)


def month_cap():
    return _env_cap("X_MONTH_USD", MONTH_USD)


def path():
    """The ledger (usage.db on the persistent disk) or None (no persistent place: open, nothing counted)."""
    for k in ("XBUDZET_DB", "USAGE_DB"):
        if os.environ.get(k):
            return os.environ[k]
    d = os.environ.get("DATA_DIR")
    return os.path.join(d, "usage.db") if d else None


def cat_of(cat):
    return cat if cat in KEYS else DEFAULT_CAT


def _day(now):
    return time.strftime("%Y-%m-%d", time.gmtime(float(now)))


def _frac(now):
    """Elapsed fraction of the UTC day (0..1)."""
    return (float(now) % 86400) / 86400.0


def connect(p=None):
    p = p or path()
    con = sqlite3.connect(p, timeout=30)
    con.executescript(SCHEMA)
    return con


# ---------- the arithmetic (pure, tested on its own) ------------------------------------------------------------------

def limit_of(month_before, dcap=None, mcap=None):
    """L: the day's limit with the month cap winning."""
    dcap = day_cap() if dcap is None else dcap
    mcap = month_cap() if mcap is None else mcap
    return max(0.0, min(dcap, mcap - month_before))


def allowance(spent, L, frac):
    """{cat: {"base", "carry", "avail", "spent", "left"}} for the day's limit L, today's spend per category and the
    elapsed fraction of the day. carry = what the categories above left unused so far (see the module text)."""
    out, carry, total = {}, 0.0, sum(max(0.0, float(spent.get(k, 0.0))) for k in KEYS)
    for k, share, _w in CATS:
        s = max(0.0, float(spent.get(k, 0.0)))
        base = share * L
        avail = base + carry
        left = max(0.0, min(avail - s, L - total))
        out[k] = {"base": round(base, 6), "carry": round(carry, 6), "avail": round(avail, 6), "spent": round(s, 6),
                  "left": round(left, 6)}
        released = base * max(0.0, min(1.0, frac)) + carry
        carry = max(0.0, released - s)
    return out


# ---------- the ledger -------------------------------------------------------------------------------------------------

def _spent(con, day_):
    return {c: float(u) for c, u in con.execute("SELECT cat, COALESCE(SUM(usd), 0) FROM xb_spend WHERE day = ? "
                                                "GROUP BY cat", (day_,))}


def _month_before(con, day_):
    r = con.execute("SELECT COALESCE(SUM(usd), 0) FROM xb_spend WHERE day LIKE ? AND day < ?",
                    (day_[:7] + "-%", day_)).fetchone()
    return float(r[0] or 0)


def state(now=None, con=None):
    """{"day", "persist", "L", "day_cap", "month_cap", "month_before", "month", "today", "cats": allowance(...),
    "jobs": {cat: {job: usd}}, "stat": {key: n}}. Without a ledger: persist False, everything open."""
    now = float(now if now is not None else time.time())
    d = _day(now)
    out = {"day": d, "persist": False, "day_cap": day_cap(), "month_cap": month_cap(), "month_before": 0.0,
           "jobs": {}, "stat": {}}
    own = con is None
    if own:
        p = path()
        if not p:
            out.update(L=out["day_cap"], month=0.0, today=0.0, cats=allowance({}, out["day_cap"], _frac(now)))
            return out
        con = connect(p)
    try:
        spent = _spent(con, d)
        mb = _month_before(con, d)
        L = limit_of(mb, out["day_cap"], out["month_cap"])
        for c, j, u in con.execute("SELECT cat, job, usd FROM xb_spend WHERE day = ?", (d,)):
            out["jobs"].setdefault(c, {})[j] = round(float(u or 0), 4)
        out["stat"] = {k: int(n or 0) for k, n in con.execute("SELECT key, n FROM xb_stat WHERE day = ?", (d,))}
        today = sum(spent.values())
        out.update(persist=True, L=L, month_before=round(mb, 4), today=round(today, 4), month=round(mb + today, 4),
                   cats=allowance(spent, L, _frac(now)))
        return out
    finally:
        if own:
            con.close()


def left(cat, now=None, con=None):
    """USD this category may still spend today (inf without a ledger)."""
    try:
        st = state(now, con)
    except sqlite3.Error:
        return float("inf")
    if not st["persist"]:
        return float("inf")
    return st["cats"][cat_of(cat)]["left"]


def room(cat, usd, now=None, con=None):
    """True: a read that costs at most `usd` fits the day, the month and this category's share."""
    return left(cat, now, con) + 1e-12 >= float(usd)


def need(cat, usd, now=None, con=None):
    """room() or raise Cap (the callers that cannot simply stop a loop)."""
    if not room(cat, usd, now, con):
        raise Cap(f"X budžet: {cat_of(cat)} nema mjesta za {usd:.4f} $ (dan {day_cap():g} $, mjesec {month_cap():g} $)")


def book(cat, usd, now=None, job="", calls=1, con=None):
    """What a read cost. Never raises (losing a count must not break the job)."""
    try:
        if usd <= 0 and calls <= 0:
            return
        own = con is None
        if own:
            p = path()
            if not p:
                return
            con = connect(p)
        try:
            con.execute("INSERT INTO xb_spend VALUES (?,?,?,?,?) ON CONFLICT (day, cat, job) DO UPDATE SET "
                        "usd = usd + excluded.usd, calls = calls + excluded.calls",
                        (_day(now if now is not None else time.time()), cat_of(cat), str(job or "-"), float(usd),
                         int(calls)))
            con.commit()
        finally:
            if own:
                con.close()
    except Exception:  # noqa: BLE001
        pass


def note(key, n=1, now=None, con=None):
    """A count of the day (key "pozivi": calls captured, "novi_influenceri": new accounts found). Never raises."""
    try:
        if not n:
            return
        own = con is None
        if own:
            p = path()
            if not p:
                return
            con = connect(p)
        try:
            con.execute("INSERT INTO xb_stat VALUES (?,?,?) ON CONFLICT (day, key) DO UPDATE SET n = n + excluded.n",
                        (_day(now if now is not None else time.time()), str(key), int(n)))
            con.commit()
        finally:
            if own:
                con.close()
    except Exception:  # noqa: BLE001
        pass


# ---------- the line ---------------------------------------------------------------------------------------------------

def _usd(x):
    return f"{float(x or 0):.2f}".replace(".", ",")


def line(now=None, st=None):
    """The one line a day (usage/daily logs it with the cost line)."""
    try:
        st = st or state(now)
    except sqlite3.Error as e:
        return f"X budžet: nečitljiv ({e})"
    if not st["persist"]:
        return (f"X budžet {st['day']}: nema trajnog stanja (ne broji se); strop {_usd(st['day_cap'])} $ dnevno, "
                f"{_usd(st['month_cap'])} $ mjesečno")
    parts = []
    for k, _s, _w in CATS:
        a = st["cats"][k]
        jobs = st["jobs"].get(k) or {}
        js = ", ".join(f"{j} {_usd(u)}" for j, u in sorted(jobs.items(), key=lambda kv: -kv[1]) if u)
        parts.append(f"{k} {_usd(a['spent'])}/{_usd(a['avail'])} $" + (f" ({js})" if js else ""))
    full = []
    if st["today"] + 1e-9 >= st["L"]:
        full.append("dnevni strop dosegnut" if st["L"] >= st["day_cap"] - 1e-9 else "mjesečni strop dosegnut")
    s = st["stat"]
    return (f"X budžet {st['day']}: " + ", ".join(parts)
            + f" | dan {_usd(st['today'])}/{_usd(st['L'])} $ (strop {_usd(st['day_cap'])}), mjesec "
              f"{_usd(st['month'])}/{_usd(st['month_cap'])} $"
            + f" | uhvaćeno poziva {int(s.get('pozivi', 0))}, novih influencera {int(s.get('novi_influenceri', 0))}"
            + (f" | {'; '.join(full)}" if full else ""))


def main(argv=None):
    print(line(), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
