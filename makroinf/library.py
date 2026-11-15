"""The library of the macro influencers' posts (15.11. navečer, the owner: "sve to treba spremati u library"): every
stored post (text, link, time, likes / reposts / replies / views, our classification) searchable for every logged-in
user in the app (/kol-makro/biblioteka, makroinf/web.py). Never on the public pages (they copy no post text).

Filters (GET parameters, all optional, combined with AND):
  racun     one account (handle)
  imovina   BTC | ETH | SOL | alts | memes | total (a post with a call on that asset)
  stav      bik (up, the bottom is in) | medvjed (down, the top is in) | neutralno (a range)
  horizont  7 (<= 14 days stated) | 30 (15-60) | dugo (> 60) | bez (no horizon stated)
  od, do    YYYY-MM-DD (UTC), the post date
  q         words in the text (all of them, any case)
  vrsta     izjave (default: posts with a market call) | sve (every stored post, also the ones without a call)
  str       the page (PER_PAGE rows, newest first)
A filter on the call (imovina, stav, horizont) always means posts with such a call.
"""
import calendar
import re
import time

from makroinf import classify, store

PER_PAGE = 50
STAV = {"bik": ("up", "bottom_in"), "medvjed": ("down", "top_in"), "neutralno": ("range",)}
HORIZONT = {"7": "c.horizon_days IS NOT NULL AND c.horizon_days <= 14",
            "30": "c.horizon_days > 14 AND c.horizon_days <= 60", "dugo": "c.horizon_days > 60",
            "bez": "c.horizon_days IS NULL"}
DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
HANDLE = re.compile(r"[A-Za-z0-9_]{1,15}")
KEYS = ("racun", "imovina", "stav", "horizont", "od", "do", "q", "vrsta", "str")


def _day_ts(s, end=False):
    if not s or not DATE.fullmatch(s):
        return None
    try:
        t = calendar.timegm(time.strptime(s, "%Y-%m-%d"))
    except ValueError:
        return None
    return t + 86400 if end else t


def clean(qs):
    """The valid filters of a query string dict ({key: str or [str]}); anything else is dropped."""
    f = {}
    for k in KEYS:
        v = qs.get(k)
        if isinstance(v, (list, tuple)):
            v = v[0] if v else None
        v = str(v or "").strip()
        if not v:
            continue
        if k == "racun" and HANDLE.fullmatch(v.lstrip("@")):
            f[k] = v.lstrip("@")
        elif k == "imovina" and v in classify.ASSETS:
            f[k] = v
        elif k == "stav" and v in STAV:
            f[k] = v
        elif k == "horizont" and v in HORIZONT:
            f[k] = v
        elif k in ("od", "do") and DATE.fullmatch(v):
            f[k] = v
        elif k == "q":
            f[k] = v[:80]
        elif k == "vrsta" and v in ("izjave", "sve"):
            f[k] = v
        elif k == "str" and v.isdigit():
            f[k] = max(1, min(10_000, int(v)))
    return f


def _where(f):
    w = ["a.status IN ('aktivan', 'neaktivan')"]
    args = []
    if f.get("racun"):
        w.append("lower(t.handle) = lower(?)")
        args.append(f["racun"])
    t0, t1 = _day_ts(f.get("od")), _day_ts(f.get("do"), end=True)
    if t0:
        w.append("t.ts >= ?")
        args.append(t0)
    if t1:
        w.append("t.ts < ?")
        args.append(t1)
    for word in (f.get("q") or "").split()[:6]:
        w.append("t.text LIKE ?")
        args.append(f"%{word}%")
    cw, cargs = [], []
    if f.get("imovina"):
        cw.append("c.asset = ?")
        cargs.append(f["imovina"])
    if f.get("stav"):
        ds = STAV[f["stav"]]
        cw.append(f"c.direction IN ({','.join('?' * len(ds))})")
        cargs += list(ds)
    if f.get("horizont"):
        cw.append(HORIZONT[f["horizont"]])
    if cw or f.get("vrsta", "izjave") == "izjave":
        w.append("EXISTS (SELECT 1 FROM calls c WHERE c.id = t.id" + "".join(f" AND {x}" for x in cw) + ")")
        args += cargs
    return " AND ".join(w), args


def query(con, f, per=PER_PAGE):
    """{"rows": [{id, handle, ts, text, quoted_text, quoted_handle, url, likes, retweets, replies, views, macro,
    calls: [{asset, direction, horizon_days, conditional, confidence}]}], "total", "page", "pages"}."""
    where, args = _where(f)
    total = (store.q(con, f"SELECT COUNT(*) FROM tweets t JOIN accounts a ON a.handle = t.handle WHERE {where}",
                     tuple(args)) or [[0]])[0][0]
    page = int(f.get("str") or 1)
    pages = max(1, -(-total // per))
    page = min(page, pages)
    keys = ("id", "handle", "ts", "text", "quoted_text", "quoted_handle", "url", "likes", "retweets", "replies", "views",
            "macro", "cls_v")
    rows = [dict(zip(keys, r)) for r in store.q(
        con, f"""SELECT t.id, t.handle, t.ts, t.text, t.quoted_text, t.quoted_handle, t.url, t.likes, t.retweets,
        t.replies, t.views, t.macro, t.cls_v FROM tweets t JOIN accounts a ON a.handle = t.handle WHERE {where}
        ORDER BY t.ts DESC, t.id DESC LIMIT ? OFFSET ?""", (*args, per, (page - 1) * per))]
    ids = [r["id"] for r in rows]
    calls = {}
    if ids:
        for i, a, d, hz, cond, conf in store.q(con, f"SELECT id, asset, direction, horizon_days, conditional, "
                                                    f"confidence FROM calls WHERE id IN ({','.join('?' * len(ids))})",
                                               tuple(ids)):
            calls.setdefault(i, []).append({"asset": a, "direction": d, "horizon_days": hz, "conditional": cond,
                                            "confidence": conf})
    for r in rows:
        r["calls"] = calls.get(r["id"], [])
    return {"rows": rows, "total": total, "page": page, "pages": pages}


def accounts(con):
    """[(handle, posts, calls)] for the account filter, most calls first."""
    return store.q(con, """SELECT t.handle, COUNT(*), SUM(CASE WHEN t.macro = 1 THEN 1 ELSE 0 END) n FROM tweets t
        JOIN accounts a ON a.handle = t.handle WHERE a.status IN ('aktivan', 'neaktivan') GROUP BY t.handle
        ORDER BY n DESC, t.handle""")


def totals(con):
    """{"posts", "calls", "accounts", "first", "last"} of the whole library."""
    r = store.q(con, """SELECT COUNT(*), COUNT(DISTINCT t.handle), MIN(t.ts), MAX(t.ts) FROM tweets t JOIN accounts a ON
        a.handle = t.handle WHERE a.status IN ('aktivan', 'neaktivan')""")
    c = store.q(con, """SELECT COUNT(DISTINCT c.id) FROM calls c JOIN accounts a ON a.handle = c.handle WHERE
        a.status IN ('aktivan', 'neaktivan')""")
    n, h, t0, t1 = r[0] if r else (0, 0, None, None)
    return {"posts": n or 0, "accounts": h or 0, "first": t0, "last": t1, "calls": (c[0][0] if c else 0) or 0}
