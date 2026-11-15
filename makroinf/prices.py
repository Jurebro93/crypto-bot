"""The truth the calls are measured against (CoinGecko market_chart, cached, a few calls a day).

  BTC, ETH, SOL   daily closes (365 days) + hourly (the last 90 days: CoinGecko's automatic granularity) per coin;
                  BTC hourly also from market.db / veliki.db btc_h where we already collect it (free)
  alts            equal-weight basket of large alts (ETH, SOL, XRP, ADA, LINK, AVAX, DOGE), daily
  memes           equal-weight basket of meme coins INCLUDING ones that later collapsed (MEME_IDS); a coin CoinGecko no
                  longer serves is listed as "bez podataka" (px_meta) and the survivorship bias is stated in the report
  total           the whole market ~ BTC (Pretpostavka: BTC's dominance and correlation; CoinGecko's total market cap
                  history is not on the free API)
A basket's level: day d = level d-1 x (1 + the mean daily return of the members that have closes on d and d-1).

A point (ts, close) is known at ts (CoinGecko's 00:00 UTC point of day d is the close of d-1, known at d 00:00): every
"known at the call time" question (the volatility, the 7-day trend) reads only points with ts <= the call time.
With COINGECKO_API_KEY the paid host is used while the key's day budget allows it (event_calendar/http); otherwise
the free endpoint (cached 20 h, a pause between calls).
"""
import bisect
import math
import time

from makroinf import store

COINS = {"BTC": "bitcoin", "ETH": "ethereum", "SOL": "solana"}
ALT_IDS = ("ethereum", "solana", "ripple", "cardano", "chainlink", "avalanche-2", "dogecoin")
# meme basket: the big ones of the last year plus ones that faded / collapsed (where CoinGecko still has data)
MEME_IDS = ("dogwifcoin", "bonk", "popcat", "fartcoin", "pudgy-penguins", "book-of-meme", "cat-in-a-dogs-world",
            "official-trump", "peanut-the-squirrel", "goatseus-maximus", "moo-deng", "slerf", "myro", "jeo-boden",
            "mother-iggy", "act-i-the-ai-prophecy", "gigachad-2", "michi")
D, H = 86400, 3600
FETCH = {}   # tests: "chart" (coin_id, days) -> {"prices": [[ms, p], ...]}


def _chart(coin, days):
    if "chart" in FETCH:
        return FETCH["chart"](coin, days)
    from event_calendar import http
    params = {"vs_currency": "usd", "days": days}
    if days > 90:
        params["interval"] = "daily"
    key = http._cg_key_raw()
    if key:
        try:
            if http._cg_take():
                import os
                demo = os.environ.get("COINGECKO_DEMO") == "1"
                base = "https://api.coingecko.com/api/v3" if demo else "https://pro-api.coingecko.com/api/v3"
                hdr = {("x-cg-demo-api-key" if demo else "x-cg-pro-api-key"): key}
                return http.get_json(f"{base}/coins/{coin}/market_chart", params, ttl=20 * H, timeout=60,
                                     headers=hdr, retries=1)
        except Exception:  # noqa: BLE001 - the free endpoint below
            pass
    return http.get_json(f"https://api.coingecko.com/api/v3/coins/{coin}/market_chart", params, ttl=20 * H,
                         timeout=60, retries=1)


def refresh(con, now=None, log=print, sleep=time.sleep):
    """Daily closes of every coin, hourly of BTC / ETH / SOL. Returns {"ok", "failed": [ids]}."""
    now = int(now or time.time())
    ids = list(dict.fromkeys(list(COINS.values()) + list(ALT_IDS) + list(MEME_IDS)))
    ok, failed = 0, []
    jobs = [(i, 365, "d") for i in ids] + [(i, 90, "h") for i in COINS.values()]
    for coin, days, res in jobs:
        try:
            d = _chart(coin, days) or {}
            pts = [(int(t / 1000), float(p)) for t, p in d.get("prices") or [] if p]
        except Exception as e:  # noqa: BLE001 - a missing coin is documented, not fatal
            pts = []
            log(store.PREFIX + f"cijene {coin}: {type(e).__name__}: {str(e)[:80]}")
        if not pts:
            failed.append(coin)
            con.execute("INSERT OR REPLACE INTO px_meta VALUES (?,?,?,?)", (coin, now, 0, "bez podataka"))
        else:
            if res == "d":   # CoinGecko's daily points sit at 00:00 UTC; the last one is "now": keep day starts only
                pts = [(t // D * D, p) for t, p in pts if t % D < 2 * H] + [pts[-1]]
            con.executemany("INSERT OR REPLACE INTO px VALUES (?,?,?,?)", [(coin, res, t, p) for t, p in pts])
            con.execute("INSERT OR REPLACE INTO px_meta VALUES (?,?,?,?)", (f"{coin}:{res}", now, len(pts), "ok"))
            ok += 1
        con.commit()
        if "chart" not in FETCH:
            sleep(2.5)   # the free API's per-minute limit
    store.kv(con, "prices_ts", str(now))
    con.commit()
    return {"ok": ok, "failed": failed}


class Series:
    """Points (ts, close) of one asset, oldest first; .known(t) / .first_at(t) / .window(t0, t1) / .vol(t)."""

    def __init__(self, pts):
        pts = sorted({int(t): float(p) for t, p in pts if p and p > 0}.items())
        self.ts = [t for t, _p in pts]
        self.px = [p for _t, p in pts]

    def __bool__(self):
        return bool(self.ts)

    def known(self, t):
        """(ts, close) of the newest point at or before t, else None."""
        i = bisect.bisect_right(self.ts, t) - 1
        return (self.ts[i], self.px[i]) if i >= 0 else None

    def first_at(self, t, within=None):
        """(ts, close) of the first point at or after t (within seconds), else None."""
        i = bisect.bisect_left(self.ts, t)
        if i >= len(self.ts) or (within is not None and self.ts[i] - t > within):
            return None
        return self.ts[i], self.px[i]

    def window(self, t0, t1):
        """[(ts, close)] with t0 < ts <= t1."""
        i, j = bisect.bisect_right(self.ts, t0), bisect.bisect_right(self.ts, t1)
        return list(zip(self.ts[i:j], self.px[i:j]))

    def end(self):
        return self.ts[-1] if self.ts else 0


class Truth:
    """daily + hourly series per asset (BTC / ETH / SOL / alts / memes / total)."""

    def __init__(self, daily, hourly=None):
        self.d = {a: s for a, s in (daily or {}).items()}
        self.h = {a: s for a, s in (hourly or {}).items()}

    def has(self, asset):
        return bool(self.d.get(asset))

    def daily(self, asset):
        return self.d.get(asset) or Series([])

    def fine(self, asset, t0, t1):
        """Hourly when it covers [t0, t1], else daily: the series to walk the window on."""
        h = self.h.get(asset)
        if h and h.ts and h.ts[0] <= t0 + H and h.end() >= t0:
            return h
        return self.daily(asset)

    def vol(self, asset, t, days=30, min_pts=20):
        """Std of the daily log returns of the `days` daily closes KNOWN at t (ts <= t); None with < min_pts."""
        s = self.daily(asset)
        i = bisect.bisect_right(s.ts, t)
        px = s.px[max(0, i - days - 1):i]
        rets = [math.log(b / a) for a, b in zip(px, px[1:]) if a > 0 and b > 0]
        if len(rets) < min_pts:
            return None
        m = sum(rets) / len(rets)
        return math.sqrt(sum((r - m) ** 2 for r in rets) / (len(rets) - 1))

    def trend(self, asset, t, days=7):
        """Return of the last `days` days known at t (for the trend-follow baseline), None without data."""
        s = self.daily(asset)
        a, b = s.known(t - days * D), s.known(t)
        if not a or not b or b[0] - a[0] < (days - 1) * D:
            return None
        return b[1] / a[1] - 1


def basket(series_list):
    """Equal-weight level series (start 100) from daily Series of the members."""
    days = sorted({t for s in series_list for t in s.ts})
    maps = [dict(zip(s.ts, s.px)) for s in series_list]
    lvl, out, prev = 100.0, [], None
    for d in days:
        if prev is not None:
            rs = [m[d] / m[prev] - 1 for m in maps if d in m and prev in m and m[prev] > 0]
            if rs:
                lvl *= 1 + sum(rs) / len(rs)
        out.append((d, lvl))
        prev = d
    return Series(out)


def load(con=None, path=None):
    """Truth from makroinf.db px (+ BTC hourly from market.db / veliki.db)."""
    own = con is None
    con = con or store.ro(path)
    rows = store.q(con, "SELECT asset, res, ts, close FROM px")
    if own and con is not None:
        con.close()
    raw = {}
    for a, res, t, p in rows:
        raw.setdefault((a, res), []).append((t, p))
    daily = {k: Series(raw.get((cid, "d"), [])) for k, cid in COINS.items()}
    hourly = {k: Series(raw.get((cid, "h"), [])) for k, cid in COINS.items()}
    try:
        from veliki import store as vstore
        extra = vstore.btc_hourly()
        if extra:
            hourly["BTC"] = Series(list(zip(hourly["BTC"].ts, hourly["BTC"].px)) + list(extra))
    except Exception:  # noqa: BLE001 - our own hourly only
        pass
    daily["alts"] = basket([Series(raw.get((i, "d"), [])) for i in ALT_IDS if raw.get((i, "d"))])
    daily["memes"] = basket([Series(raw.get((i, "d"), [])) for i in MEME_IDS if raw.get((i, "d"))])
    daily["total"] = daily["BTC"]
    hourly["total"] = hourly["BTC"]
    return Truth(daily, hourly)


def coverage(con):
    """{"ok": [...], "bez_podataka": [...]} of the meme basket (the survivorship statement)."""
    ok = {a.split(":")[0] for (a,) in store.q(con, "SELECT asset FROM px_meta WHERE status = 'ok'")}
    return {"ok": [m for m in MEME_IDS if m in ok], "bez_podataka": [m for m in MEME_IDS if m not in ok]}
