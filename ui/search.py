"""Search box on top of every page: pages, tokens (name, ticker or address), KOL-ovi and novčanici.

Read-only, only runs when somebody types: a few small LIKE queries with a hard time limit each (a slow scan of a big
table is cut off instead of holding the page), answers cached for a minute. /api/trazi?q= gives JSON for the
drop-down under the box, /trazi?q= the full results page.
"""
import json
import os
import re
import sqlite3
import threading
import time
import unicodedata
from urllib.parse import quote

from ui import data
from ui.html import SECTIONS, esc, ext_icons

HERE = data.HERE
ADDR = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{32,44}$")
LIMIT_MS = 700          # per query; a cut-off query just returns what it found so far (usually nothing)
_CACHE, _LOCK, TTL = {}, threading.Lock(), 60


def fold(s):
    """Lower case without diacritics, so 'potrosnja' finds 'Potrošnja'."""
    return "".join(c for c in unicodedata.normalize("NFD", (s or "").lower()) if unicodedata.category(c) != "Mn")


def _rows(path, sql, args=()):
    if not path or not os.path.exists(path) or not os.path.getsize(path):
        return []
    try:
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=2)
    except sqlite3.Error:
        return []
    con.row_factory = sqlite3.Row
    end = time.monotonic() + LIMIT_MS / 1000
    con.set_progress_handler(lambda: 1 if time.monotonic() > end else 0, 20000)
    try:
        return [dict(r) for r in con.execute(sql, args)]
    except sqlite3.Error:
        return []
    finally:
        con.close()


def _db(name, env=None):
    return os.environ.get(env, os.path.join(HERE, name)) if env else os.path.join(HERE, name)


# ---------- pages ----------

def pages(q):
    f = fold(q)
    words = f.split()
    out = []
    for sec, items in SECTIONS:
        for p in items:
            hay = fold(" ".join([p["name"], p["desc"], p.get("kw", ""), sec]))
            name = fold(p["name"])
            if not all(w in hay for w in words):
                continue
            rank = 0 if name.startswith(f) else 1 if f in name else 2
            out.append((rank, {"name": p["name"], "href": p["href"], "icon": p["icon"], "desc": p["desc"], "sec": sec}))
    return [p for _, p in sorted(out, key=lambda x: x[0])][:8]


# ---------- tokens ----------

def tokens(q, limit=10):
    q = q.strip().lstrip("$")
    if not q:
        return []
    found = {}

    def add(mint, sym, name, ts=0, url=None, src=""):
        if not mint:
            return
        t = found.setdefault(mint, {"mint": mint, "sym": sym, "name": name, "ts": 0, "url": url, "src": set()})
        t["sym"] = t["sym"] or sym
        t["name"] = t["name"] or name
        t["url"] = t["url"] or url
        t["ts"] = max(t["ts"], ts or 0)
        if src:
            t["src"].add(src)

    if ADDR.match(q):
        cond, args = "token = ?", (q,)
    else:
        like = f"%{q}%"
        cond, args = "(symbol LIKE ? OR name LIKE ?)", (like, like)
    for r in _rows(data.HYPE_DB, f"SELECT token, symbol, name, url, MAX(ts) ts FROM hype_signals WHERE {cond} "
                                 "GROUP BY token ORDER BY ts DESC LIMIT 40", args):
        add(r["token"], r["symbol"], r["name"], r["ts"], r["url"], "skener")
    for r in _rows(_db("dugo.db", "DUGO_DB"), f"SELECT mint token, symbol, name FROM tokens WHERE "
                                              f"{cond.replace('token =', 'mint =')} LIMIT 20", args):
        add(r["token"], r["symbol"], r["name"], 0, None, "dugoročni")
    for r in _rows(_db("kol.db", "KOL_DB"), f"SELECT token, symbol, name, updated ts FROM tokens WHERE {cond} "
                                            "ORDER BY updated DESC LIMIT 20", args):
        add(r["token"], r["symbol"], r["name"], r["ts"], None, "KOL pozivi")
    pc = "token = ?" if ADDR.match(q) else "symbol LIKE ?"
    pa = (q,) if ADDR.match(q) else (f"%{q}%",)
    for r in _rows(data.PAPER_DB, f"SELECT token, symbol, first_ts ts, url FROM candidates WHERE {pc} "
                                  "ORDER BY first_ts DESC LIMIT 20", pa):
        add(r["token"], r["symbol"], None, r["ts"], r["url"], "demo")
    f = fold(q)

    def rank(t):
        s = fold(t["sym"])
        return (0 if s == f else 1 if s.startswith(f) else 2, -t["ts"])
    out = sorted(found.values(), key=rank)[:limit]
    for t in out:
        t["src"] = sorted(t["src"])
    return out


# ---------- KOL-ovi and novčanici ----------

def kols(q, limit=8):
    q = q.strip().lstrip("@")
    if len(q) < 2:
        return []
    like = f"%{q}%"
    rows = _rows(_db("kol.db", "KOL_DB"), "SELECT handle, name, followers FROM kols WHERE handle LIKE ? OR name LIKE ? "
                                          "ORDER BY COALESCE(followers, 0) DESC LIMIT ?", (like, like, limit))
    f = fold(q)
    rows.sort(key=lambda r: 0 if fold(re.sub(r"^(tg:|w:)", "", r["handle"])) == f else 1)
    return [{"handle": r["handle"], "name": r["name"], "followers": r["followers"],
             "label": ("✈ " + r["handle"][3:]) if r["handle"].startswith("tg:") else
                      ("👛 " + r["handle"][2:]) if r["handle"].startswith("w:") else "@" + r["handle"]} for r in rows]


def wallets(q, limit=8):
    q = q.strip()
    out, seen = [], set()
    if len(q) >= 3:  # tracked KOL wallets by their name
        for r in _rows(_db("kol.db", "KOL_DB"), "SELECT wallet, label FROM kol_wallets WHERE label LIKE ? OR wallet LIKE ? "
                                                "LIMIT ?", (f"%{q}%", f"{q}%", limit)):
            seen.add(r["wallet"])
            out.append({"wallet": r["wallet"], "label": r["label"]})
    if len(q) >= 4 and re.fullmatch(r"[1-9A-HJ-NP-Za-km-z]+", q):  # registry by the start of the address
        for r in _rows(data.WALLET_DB, "SELECT wallet FROM wallets WHERE wallet >= ? AND wallet < ? LIMIT ?",
                       (q, q + "￿", limit)):
            if r["wallet"] not in seen:
                seen.add(r["wallet"])
                out.append({"wallet": r["wallet"], "label": None})
    return out[:limit]


def search(q):
    q = (q or "").strip()[:80]
    if not q:
        return {"q": q, "pages": [], "tokens": [], "kols": [], "wallets": [], "addr": False}
    key = q.lower()
    now = time.time()
    with _LOCK:
        hit = _CACHE.get(key)
        if hit and now - hit[0] < TTL:
            return hit[1]
    res = {"q": q, "pages": pages(q), "addr": bool(ADDR.match(q))}
    res["tokens"] = tokens(q) if len(q) >= 2 else []
    res["kols"] = kols(q)
    res["wallets"] = wallets(q)
    with _LOCK:
        if len(_CACHE) > 300:
            _CACHE.clear()
        _CACHE[key] = (now, res)
    return res


def api(q):
    return json.dumps(search(q), ensure_ascii=False)


def _ago(ts):
    if not ts:
        return ""
    d = time.time() - ts
    return f"prije {d / 60:.0f} min" if d < 3600 else f"prije {d / 3600:.0f} h" if d < 86400 else f"prije {d / 86400:.0f} d"


def page(qs):
    q = (qs.get("q") or "").strip()
    form = (f'<form action=/trazi class="sform card"><input name=q value="{esc(q)}" placeholder="Token, adresa, KOL, '
            'novčanik ili stranica…" autofocus><button type=submit>Traži</button></form>')
    if not q:
        return "Traži", ("<h1>Traži</h1>" + form + "<p class=mut>Upiši ime ili ticker tokena (npr. Fartcoin), adresu tokena "
                         "ili novčanika, ime KOL-a ili ime stranice (npr. natjecanje).</p>")
    r = search(q)
    b = ["<h1>Traži</h1>", form]
    n = 0
    if r["pages"]:
        n += len(r["pages"])
        b.append("<h2>Stranice</h2><div class=mapgrid>" + "".join(
            f'<a class=mapcard href="{p["href"]}"><span class=mi>{p["icon"]}</span><b>{esc(p["name"])}</b>'
            f'<span class=mut>{esc(p["desc"])}</span></a>' for p in r["pages"]) + "</div>")
    if r["tokens"]:
        n += len(r["tokens"])
        rows = "".join(
            f'<li><a href="/token/{quote(t["mint"])}"><b>{esc(t["sym"] or t["mint"][:6])}</b></a> '
            f'<span class=mut>{esc(t["name"] or "")}</span> {ext_icons(t["mint"], t["url"])}'
            f'<div class=mut style="font-size:12px"><code>{esc(t["mint"])}</code> · viđen u: {esc(", ".join(t["src"]))}'
            f'{" · " + _ago(t["ts"]) if t["ts"] else ""}</div></li>' for t in r["tokens"])
        b.append(f"<h2>Tokeni</h2><ul class=sres>{rows}</ul>")
    if r["kols"]:
        n += len(r["kols"])
        rows = "".join(f'<li><a href="/kol/{quote(k["handle"])}"><b>{esc(k["label"])}</b></a> <span class=mut>'
                       f'{esc(k["name"] or "")}{" · " + format(k["followers"], ",") + " pratitelja" if k["followers"] else ""}'
                       f'</span></li>' for k in r["kols"])
        b.append(f"<h2>KOL-ovi i kanali</h2><ul class=sres>{rows}</ul>")
    if r["wallets"]:
        n += len(r["wallets"])
        rows = "".join(f'<li><a href="/wallet/{quote(w["wallet"])}"><code>{esc(w["wallet"])}</code></a>'
                       f'{" <span class=mut>" + esc(w["label"]) + "</span>" if w["label"] else ""}</li>'
                       for w in r["wallets"])
        b.append(f"<h2>Novčanici</h2><ul class=sres>{rows}</ul>")
    if r["addr"]:
        b.append(f'<div class=card>Ovo izgleda kao adresa na Solani. Otvori je kao '
                 f'<a href="/token/{quote(q)}">token</a> ili kao <a href="/wallet/{quote(q)}">novčanik</a>.</div>')
    elif not n:
        b.append("<p class=mut>Ništa nije pronađeno. Probaj kraći dio imena, ticker bez $ ili cijelu adresu.</p>")
    return "Traži", "".join(b)
