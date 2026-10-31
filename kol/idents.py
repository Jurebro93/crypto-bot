"""KOL wallets with a public identity (X handle, Telegram link), so the bot sees a KOL buy before the post.

- KOLscan leaderboard (free, public page, its embedded initLeaderboard JSON): ~50 best KOLs of the day; read once
  a day, so the list grows over time.
- Solana Tracker KOL leaderboard (paid, SOLANATRACKER_API_KEY, from EUR 50/mo): every tracked KOL with PnL.
- FOMO app top traders (Apify actor, ~$0.0015 per trader, weekly): the people FOMO users copy-trade.
All go to kol.db kol_ids; kol/chainwatch.py follows the best of them on chain.
"""
import json
import os
import re
import time
import urllib.parse
import urllib.request

from event_calendar.http import USER_AGENT

KOLSCAN = "https://kolscan.io/leaderboard"
ST_URL = "https://data.solanatracker.io/v2/pnl/leaderboard/kols/period"
FOMO = "muhammetakkurtt/fomo-top-traders-scraper"
_HANDLE = re.compile(r"(?:x|twitter)\.com/([A-Za-z0-9_]{1,15})", re.I)


def _get(url, headers=None, timeout=30):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


def handle_of(url):
    m = _HANDLE.search(url or "")
    return m.group(1) if m else (url.lstrip("@") if url and re.fullmatch(r"@?[A-Za-z0-9_]{1,15}", url) else None)


_FLIGHT = re.compile(r'self\.__next_f\.push\(\[1,("(?:[^"\\]|\\.)*")\]\)')


def _flight(page):
    """The Next.js payload is split over many <script> pushes; join the decoded strings."""
    parts = []
    for lit in _FLIGHT.findall(page):
        try:
            parts.append(json.loads(lit))
        except ValueError:
            pass
    return "".join(parts)


def parse_kolscan(page):
    """[{wallet, name, twitter, telegram, pnl, wins, losses, rank}] from the leaderboard page's initLeaderboard."""
    s = _flight(page) or page.replace('\\"', '"')
    i = s.find('"initLeaderboard":[')
    if i < 0:
        return []
    j, depth, k = s.index("[", i), 0, None
    for k in range(j, len(s)):
        depth += {"[": 1, "]": -1}.get(s[k], 0)
        if depth == 0:
            break
    try:
        rows = json.loads(s[j:k + 1])
    except ValueError:
        return []
    out = []
    for rank, r in enumerate(rows, 1):
        if r.get("wallet_address"):
            out.append({"wallet": r["wallet_address"], "name": r.get("name"), "twitter": handle_of(r.get("twitter")),
                        "telegram": r.get("telegram"), "pnl": r.get("profit"), "wins": r.get("wins"),
                        "losses": r.get("losses"), "rank": rank})
    return out


def kolscan():
    return parse_kolscan(_get(KOLSCAN))


def solanatracker(period="7d", limit=100):
    key = os.environ.get("SOLANATRACKER_API_KEY")
    if not key:
        return []
    q = urllib.parse.urlencode({"period": period, "limit": limit, "sort": "realized"})
    body = json.loads(_get(f"{ST_URL}?{q}", {"x-api-key": key}))
    out = []
    for rank, t in enumerate(body.get("traders") or [], 1):
        idt = t.get("identity") or {}
        out.append({"wallet": t.get("wallet"), "name": idt.get("name"), "twitter": handle_of(idt.get("twitter")),
                    "telegram": idt.get("telegram"), "pnl": ((t.get("period") or {}).get("realized")),
                    "wins": None, "losses": None, "rank": rank})
    return [o for o in out if o["wallet"]]


def fomo(limit=100, window="7d"):
    from hype import apify
    if not apify.enabled():
        return []
    items = apify.run("fomo", FOMO, {"window": window, "tradeType": "spot", "limit": limit}, cache_secs=6 * 86400)
    out = []
    for rank, t in enumerate(items or [], 1):
        if t.get("address"):
            out.append({"wallet": t["address"], "name": t.get("displayName") or t.get("userHandle"), "twitter": None,
                        "telegram": None, "pnl": t.get("pnl7d") or t.get("pnl30d") or t.get("totalPnL"),
                        "wins": None, "losses": None, "rank": rank})
    return out


def save(con, rows, source, now=None):
    now = now or int(time.time())
    for r in rows:
        con.execute("""INSERT INTO kol_ids VALUES (?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT (wallet) DO UPDATE SET
            name=COALESCE(excluded.name, name), twitter=COALESCE(excluded.twitter, twitter),
            telegram=COALESCE(excluded.telegram, telegram), source=CASE WHEN source='fomo' THEN excluded.source
            ELSE source END, pnl=excluded.pnl, wins=excluded.wins, losses=excluded.losses, rank=excluded.rank,
            updated=excluded.updated""",
                    (r["wallet"], r["name"], r["twitter"], r["telegram"], source, r["pnl"], r["wins"], r["losses"],
                     r["rank"], now, now))
    return len(rows)


def refresh(con, cfg, now=None, log=print):
    """Once a day per source (cfg['idents']['every_h']). Returns {source: rows}."""
    now = now or int(time.time())
    every = cfg.get("idents", {}).get("every_h", 24) * 3600
    done = {}
    for name, fn in (("kolscan", kolscan), ("solanatracker", solanatracker), ("fomo", fomo)):
        last = con.execute("SELECT last_ts FROM searches WHERE target=?", (f"ids:{name}",)).fetchone()
        if last and now - last[0] < (every * 7 if name == "fomo" else every):
            continue
        try:
            rows = fn()
        except Exception as e:
            log(f"idents {name}: {type(e).__name__}: {e}")
            continue
        done[name] = save(con, rows, name, now)
        con.execute("INSERT INTO searches VALUES (?,?,?,1) ON CONFLICT (target) DO UPDATE SET last_ts=excluded.last_ts, "
                    "n=n+1", (f"ids:{name}", "idents", now))
    con.commit()
    return done
