"""The macro regime of the memecoin market from the platforms' volumes (15.11., vlasnik: "Makro tržište je jako bitno:
prati kretanje volumena najpoznatijih platformi i trendove"). Free sources only, nothing paid:

  platforms  DefiLlama DEX volumes on Solana. First market.db `snap` (run_market.py already reads the overview every
             hour, free): read, not fetched again; only when market.db is missing or older than STALE_S (3 h) one direct
             call of api.llama.fi/overview/dexs/solana (no history, cached 30 min). Per platform the 24 h volume
             against its 7-day daily average, chg = vol24 / (vol7d / 7) - 1: pump.fun, PumpSwap, Raydium (AMM / CPMM /
             CLMM / LaunchLab), Meteora (DLMM / DAMM / DBC), Orca, the trading apps (Axiom, GMGN, Photon, BullX,
             Trojan ...: DefiLlama "Trading App" / "Telegram Bot"), Solana DEX in total. The meme platforms (MEME:
             pump.fun, PumpSwap, Raydium, Meteora, the trading apps; not Orca and the prop AMMs, mostly SOL / stables)
             are summed into one chg (volume weighted)
  sector     CoinGecko's category "solana-meme-coins" (public API, one call an hour, cached): its market cap, 24 h
             volume and 24 h market cap change
  midcaps    our own collector (midcap.db, veliki/midcap.py): the members' 24 h volume now against each one's average
             over the last 7 days (summed: volume weighted), the trending count
  BTC        rule.Crash.regime (slobodan_pad / dno_se_potvrduje / normalno) and BTC's 24 h change
Regime (regime(), pure; thresholds CFG):
  risk_off   BTC in a free fall, or the meme platforms <= -25 % against their 7-day average (with the midcaps <= -20 %
             when known), or the midcaps <= -35 %, or the sector's market cap <= -12 % in 24 h
  risk_on    the meme platforms >= +10 % and the midcaps >= +5 % (when known), BTC not falling (24 h > -2 %, not a free
             fall), the sector's market cap not down more than 5 % in 24 h
  neutral    the rest (and unknown: no platform numbers)
Uses (veliki/live): risk_off -> no new entries, no DCA, the reasoned exits; risk_on -> the DCA is allowed and the demo's
caps x RISK_ON_BONUS (the real caps never move). Every hour (veliki/midcap.run_pass) the line "makro platforme:
pump.fun 24 h $…, Δ7d …; …; režim …" and one row in midcap.db makro_h (the history for the backtest). For the past
(walk.py) the same rule on market.db's DAILY volumes: day d from the days before d only (daily_regimes).
"""
import json
import os
import sqlite3
import time

PREFIX = "makro platforme: "
D, H = 86400, 3600
STALE_S = 3 * 3600
OVERVIEW = "https://api.llama.fi/overview/dexs/solana"
CG_CATS = "https://api.coingecko.com/api/v3/coins/categories"
SECTOR = "solana-meme-coins"
CFG = {"off_plat": -0.25, "off_plat_mid": -0.20, "off_mid": -0.35, "off_sector": -12.0, "on_plat": 0.10,
       "on_mid": 0.05, "on_btc24": -0.02, "on_sector": -5.0}
RISK_ON_BONUS = 1.5
ORDER = ("pump.fun", "PumpSwap", "Raydium", "Meteora", "Orca", "trading appovi", "Solana DEX")
MEME = ("pump.fun", "PumpSwap", "Raydium", "Meteora", "trading appovi")
SCHEMA = "CREATE TABLE IF NOT EXISTS makro_h (ts INTEGER PRIMARY KEY, regime TEXT, data TEXT);"
FETCH = {}    # tests: "overview" () -> DefiLlama JSON, "sector" () -> CoinGecko categories list
_C = {"ts": 0.0, "v": None}


def platform_of(slug, grp=None):
    s = (slug or "").lower()
    if s == "pump.fun":
        return "pump.fun"
    if s == "pumpswap":
        return "PumpSwap"
    if s.startswith("raydium") or s == "launchlab":
        return "Raydium"
    if s.startswith("meteora"):
        return "Meteora"
    if s.startswith("orca"):
        return "Orca"
    if grp == "terminal":
        return "trading appovi"
    return None


def platforms(rows):
    """{name: {"v24", "v7", "chg"}} from rows [(slug, grp, vol24, vol7d)] (grp "dex" / "launchpad" / "terminal";
    the group total "all:dex" is Solana DEX), plus "meme": the MEME platforms summed."""
    agg = {}
    dex_sum = [0.0, 0.0]
    have_all = None
    for slug, grp, v24, v7 in rows:
        if v24 is None or v7 is None:
            continue
        if slug == "all:dex":
            have_all = (float(v24), float(v7))
            continue
        if (slug or "").startswith("all:"):
            continue
        if grp == "dex":
            dex_sum[0] += v24
            dex_sum[1] += v7
        name = platform_of(slug, grp)
        if name:
            a = agg.setdefault(name, [0.0, 0.0])
            a[0] += float(v24)
            a[1] += float(v7)
    a = have_all or (dex_sum if dex_sum[1] else None)
    if a:
        agg["Solana DEX"] = list(a)
    out = {k: {"v24": v[0], "v7": v[1], "chg": (v[0] / (v[1] / 7) - 1) if v[1] > 0 else None} for k, v in agg.items()}
    m24 = sum(out[k]["v24"] for k in MEME if k in out)
    m7 = sum(out[k]["v7"] for k in MEME if k in out)
    if m7 > 0:
        out["meme"] = {"v24": m24, "v7": m7, "chg": m24 / (m7 / 7) - 1}
    return out


def _market_rows(now, path=None):
    """[(slug, grp, vol24, vol7d)] of market.db's newest hourly snapshot, None when missing or older than STALE_S."""
    try:
        from market import store as mstore
        con = mstore.ro(path)
    except Exception:  # noqa: BLE001
        con = None
    if con is None:
        return None, None
    try:
        ts = con.execute("SELECT MAX(ts) FROM snap").fetchone()[0]
        if not ts or now - ts > STALE_S:
            return None, ts
        rows = con.execute("SELECT s.slug, p.grp, s.vol24h, s.vol7d FROM snap s LEFT JOIN platforms p ON p.slug = "
                           "s.slug WHERE s.ts=?", (ts,)).fetchall()
        return rows, ts
    except sqlite3.Error:
        return None, None
    finally:
        con.close()


def _overview_rows():
    """The same rows from one direct DefiLlama call (no history)."""
    if "overview" in FETCH:
        ov = FETCH["overview"]()
    else:
        from event_calendar import http
        ov = http.get_json(OVERVIEW, {"excludeTotalDataChart": "true", "excludeTotalDataChartBreakdown": "true"},
                           ttl=1800, timeout=60)
    from market import sources
    rows = []
    for p in (ov or {}).get("protocols") or []:
        g = sources.GROUPS.get(p.get("category"))
        if g and p.get("slug") and p.get("total24h") is not None:
            rows.append((p["slug"], g, float(p.get("total24h") or 0), float(p.get("total7d") or 0)))
    return rows


def sector():
    """{"mcap", "vol24", "mcap_chg24"} of CoinGecko's Solana meme category, None when unreachable."""
    try:
        if "sector" in FETCH:
            cats = FETCH["sector"]()
        else:
            from event_calendar import http
            cats = http.get_json(CG_CATS, None, ttl=3300, timeout=60, retries=1)
        for x in cats or []:
            if x.get("id") == SECTOR:
                return {"mcap": x.get("market_cap"), "vol24": x.get("volume_24h"),
                        "mcap_chg24": x.get("market_cap_change_24h")}
    except Exception:  # noqa: BLE001 - the sector is one vote of several
        return None
    return None


def midcaps(con, now):
    """{"v24", "avg7", "chg", "n", "trending"} of the collector's members (midcap.db con): the newest pass's 24 h
    volume against each member's average over the last 7 days (members with >= 24 h of snapshots)."""
    try:
        last = con.execute("SELECT MAX(ts) FROM snap WHERE ts >= ?", (now - 3 * H,)).fetchone()[0]
        if not last:
            return None
        now_v = dict(con.execute("SELECT id, v24 FROM snap WHERE ts=?", (last,)).fetchall())
        avg = {i: (a, t0) for i, a, t0 in con.execute(
            "SELECT id, AVG(v24), MIN(ts) FROM snap WHERE ts >= ? AND v24 > 0 GROUP BY id", (now - 7 * D,))}
        v24 = a7 = 0.0
        n = 0
        for i, v in now_v.items():
            a = avg.get(i)
            if not v or not a or not a[0] or last - a[1] < 24 * H:
                continue
            v24 += v
            a7 += a[0]
            n += 1
        tr = con.execute("SELECT COUNT(*) FROM tokens WHERE member=1 AND trend IS NOT NULL").fetchone()[0]
        mem = con.execute("SELECT COUNT(*) FROM tokens WHERE member=1").fetchone()[0]
        return {"v24": v24, "avg7": a7, "chg": (v24 / a7 - 1) if a7 > 0 and n >= 5 else None, "n": n,
                "trending": tr, "members": mem, "v24_all": float(sum(v for v in now_v.values() if v))}
    except sqlite3.Error:
        return None


def regime(plat_chg, mid_chg=None, btc_state=None, btc24=None, sector_chg=None, cfg=None):
    """(risk_on / neutral / risk_off, why in Croatian) - see the module text."""
    c = {**CFG, **(cfg or {})}
    if btc_state == "slobodan_pad":
        return "risk_off", "BTC slobodan pad"
    if plat_chg is not None and plat_chg <= c["off_plat"] and (mid_chg is None or mid_chg <= c["off_plat_mid"]):
        return "risk_off", f"volumen meme platformi {plat_chg:+.0%} prema prosjeku 7 d" + (
            f", midcapovi {mid_chg:+.0%}" if mid_chg is not None else "")
    if mid_chg is not None and mid_chg <= c["off_mid"]:
        return "risk_off", f"volumen midcapova {mid_chg:+.0%} prema prosjeku 7 d"
    if sector_chg is not None and sector_chg <= c["off_sector"]:
        return "risk_off", f"Solana meme sektor {sector_chg:+.1f} % u 24 h"
    if plat_chg is None:
        return "neutral", "volumen platformi nepoznat"
    btc_ok = btc24 is None or btc24 > c["on_btc24"]
    sec_ok = sector_chg is None or sector_chg > c["on_sector"]
    if plat_chg >= c["on_plat"] and (mid_chg is None or mid_chg >= c["on_mid"]) and btc_ok and sec_ok:
        return "risk_on", f"volumen meme platformi {plat_chg:+.0%}" + (
            f", midcapovi {mid_chg:+.0%}" if mid_chg is not None else "") + ", BTC ne pada"
    return "neutral", f"volumen meme platformi {plat_chg:+.0%}" + (
        f", midcapovi {mid_chg:+.0%}" if mid_chg is not None else "")


def _m(x):
    if x is None:
        return "?"
    return f"${x / 1e9:.2f}B" if x >= 1e9 else f"${x / 1e6:.1f}M" if x >= 1e6 else f"${x / 1e3:.0f}k"


def _p(x):
    return "?" if x is None else f"{x:+.0%}"


def line(snap):
    """The hour's log line."""
    pl = snap.get("platforms") or {}
    parts = [f"{k} 24 h {_m(pl[k]['v24'])}, Δ7d {_p(pl[k]['chg'])}" for k in ORDER if k in pl]
    if "meme" in pl:
        parts.append(f"meme platforme ukupno Δ7d {_p(pl['meme']['chg'])}")
    sc = snap.get("sector") or {}
    if sc:
        parts.append(f"Solana meme sektor MC {_m(sc.get('mcap'))} ({(sc.get('mcap_chg24') or 0):+.1f} % 24 h), volumen "
                     f"{_m(sc.get('vol24'))}")
    md = snap.get("midcaps") or {}
    if md:
        parts.append(f"midcap volumen {_m(md.get('v24_all'))} ({md.get('members')} tokena, {md.get('trending')} "
                     f"trending), Δ7d {_p(md.get('chg'))}")
    parts.append(f"BTC {snap.get('btc_state') or '?'}" + (f" ({snap['btc24']:+.1%} 24 h)"
                                                          if snap.get("btc24") is not None else ""))
    return PREFIX + "; ".join(parts) + f"; režim {snap.get('regime')} ({snap.get('why')}) [izvor {snap.get('src')}]"


def _btc(now):
    try:
        from veliki import rule, store
        h = store.btc_hourly()
        cr = rule.crash_of(h)
        st = cr.regime(now)[0]
        ch = cr.chg(now, 24)
        return st, ch
    except Exception:  # noqa: BLE001
        return None, None


def snapshot(con, now=None, market_path=None):
    """The macro snapshot now (con: midcap.db or None): platforms (market.db, else DefiLlama directly), the sector, the
    midcaps, BTC, the regime."""
    now = int(now or time.time())
    rows, mts = _market_rows(now, market_path)
    src = "market.db"
    if rows is None:
        try:
            rows, src = _overview_rows(), "DefiLlama izravno"
        except Exception as e:  # noqa: BLE001
            rows, src = [], f"nedostupno ({type(e).__name__})"
    pl = platforms(rows or [])
    sc = sector()
    md = midcaps(con, now) if con is not None else None
    st, b24 = _btc(now)
    reg, why = regime((pl.get("meme") or {}).get("chg"), (md or {}).get("chg"), st, b24,
                      (sc or {}).get("mcap_chg24"))
    return {"ts": now, "platforms": pl, "sector": sc, "midcaps": md, "btc_state": st, "btc24": b24, "regime": reg,
            "why": why, "src": src, "market_ts": mts}


def refresh(con, now=None, log=print, market_path=None):
    """The hour's snapshot into midcap.db makro_h (con, the collector's own connection) and the log line."""
    now = int(now or time.time())
    con.executescript(SCHEMA)
    s = snapshot(con, now, market_path)
    con.execute("INSERT OR REPLACE INTO makro_h (ts, regime, data) VALUES (?,?,?)",
                (now // H * H, s["regime"], json.dumps(s, ensure_ascii=False)))
    con.execute("DELETE FROM makro_h WHERE ts < ?", (now - 120 * D,))
    con.commit()
    _C.update(ts=0.0)
    log(line(s))
    return s


def current(now=None, path=None, max_age_s=3 * H):
    """The newest stored snapshot (midcap.db makro_h, read-only, cached 5 min) no older than max_age_s, else None
    (unknown: veliki/live treats it as neutral and says so)."""
    now = now or time.time()
    if path is None and _C["v"] is not None and time.monotonic() - _C["ts"] < 300:
        v = _C["v"]
    else:
        v = None
        try:
            from veliki import midcap
            con = midcap.ro(path)
            if con is not None:
                try:
                    r = con.execute("SELECT ts, data FROM makro_h ORDER BY ts DESC LIMIT 1").fetchone()
                    v = json.loads(r[1]) if r else None
                except (sqlite3.Error, ValueError, TypeError):
                    v = None
                finally:
                    con.close()
        except Exception:  # noqa: BLE001
            v = None
        if path is None:
            _C.update(ts=time.monotonic(), v=v or {})
    if not v or now - (v.get("ts") or 0) > max_age_s:
        return None
    return v


def regime_now(now=None):
    """risk_on / neutral / risk_off / None (unknown)."""
    v = current(now)
    return v.get("regime") if v else None


# ---------- the past (walk.py) ------------------------------------------------------------------------------------------

def daily_regimes(series=None, crash=None, market_path=None, cfg=None):
    """{UTC day: regime} for the backtest: day d from the complete days before d only (market.db daily per platform:
    the MEME platforms' volume of day d-1 against the mean of d-7..d-1; the midcaps: the sum of the daily volume of
    the backtest's tokens (series' c1d) the same way; BTC's state at d 00:00 UTC). {} without market.db."""
    try:
        from market import store as mstore
        con = mstore.ro(market_path)
    except Exception:  # noqa: BLE001
        con = None
    if con is None:
        return {}
    try:
        grp = dict(con.execute("SELECT slug, grp FROM platforms").fetchall())
        vol = {}
        for day, slug, v in con.execute("SELECT day, slug, volume FROM daily WHERE slug NOT LIKE 'all:%' AND "
                                        "slug NOT LIKE 'meta:%'"):
            if platform_of(slug, grp.get(slug)) in MEME:
                vol[int(day) // D * D] = vol.get(int(day) // D * D, 0.0) + (v or 0.0)
    except sqlite3.Error:
        return {}
    finally:
        con.close()
    mid = {}
    for s in (series or {}).values():
        for c in s.get("daily") or []:
            k = int(c[0]) // D * D
            mid[k] = mid.get(k, 0.0) + (c[5] if len(c) > 5 and c[5] else 0.0)

    def chg(ser, d):
        w = [ser.get(d - k * D) for k in range(1, 8)]
        if any(x is None for x in w) or not sum(w):
            return None
        return w[0] / (sum(w) / 7) - 1

    out = {}
    days = sorted(vol)
    for d in [x + D for x in days]:
        st = crash.regime(d)[0] if crash is not None else None
        b24 = crash.chg(d, 24) if crash is not None else None
        out[d // D] = regime(chg(vol, d), chg(mid, d) if mid else None, st, b24, None, cfg)[0]
    return out


# ---------- makroinf (15.11.): the macro influencers' index, an optional DEMO input -----------------------------------
# (vlasnik: "Slažem se s prijedlogom koraka za plan makroinfluencera s dopunama kritičara": the index feeds the midcap
# strategy only as a DEMO input until it proves incremental EV). Behind the flag makroinf_indeks (NEVER_LIVE):
#   off      nothing (regime() and every real-account path never read it)
#   shadow   demo_index() says "would block" (the caller logs it), nothing changes
#   paper    the DEMO account takes no new entry while makroinf's input is "aktivan" and the prospective index of the most
#            accurate accounts is <= -thr (makroinf/index.demo_check)
_MI = {"ts": 0.0, "v": (False, None, "off")}


def demo_index(now=None, max_age_s=300):
    """(would_block, why, flag mode) of makroinf's index for the DEMO account; cached 5 min; never raises."""
    if time.monotonic() - _MI["ts"] < max_age_s and _MI["ts"]:
        return _MI["v"]
    try:
        from trade import settings
        mode = settings.flag(settings.MAKROINF)
    except Exception:  # noqa: BLE001 - unreadable: off (the old behaviour)
        mode = "off"
    v = (False, None, mode)
    if mode != "off":
        try:
            from makroinf import index as mindex
            blocks, why, _val = mindex.demo_check(now or time.time())
            v = (bool(blocks), why, mode)
        except Exception as e:  # noqa: BLE001
            v = (False, f"makroinf nečitljiv ({type(e).__name__})", mode)
    _MI.update(ts=time.monotonic(), v=v)
    return v


def demo_regime(now=None):
    """(regime, why) for the DEMO account's new entries: regime_now(), turned risk_off by makroinf's index only when
    the flag makroinf_indeks is paper and the index blocks. The real account uses regime_now() alone."""
    base = regime_now(now)
    blocks, why, mode = demo_index(now)
    if blocks and mode == "paper":
        return "risk_off", why
    return base, None
