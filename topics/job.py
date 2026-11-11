"""One pass of the event-topic job (run_topics.py once, every TOPICS_EVERY_S from start.sh; flag event_tokens).

  1. day roll-over: one spend line per source for the day that ended (CLAUDE.md: trošak po izvoru)
  2. topics whose event is more than AUTO_DONE_S past are marked done (nothing searches a forgotten topic)
  3. matching (free, string only): a topic seen for the first time (or with new keywords) against everything hype.db
     live_launches holds (new pump.fun tokens 24 h, migrations 7 days) and scan.db's candidates and DexScreener
     profiles (descriptions); then, every pass, only the rows newer than the watermark. The PumpPortal feed's own
     hook (topics/hook.py) matches new tokens in real time; this is its catch-up.
  4. search, per ACTIVE topic every SEARCH_EVERY_S (10 min): one DexScreener /latest/dex/search query (free, the
     300-a-minute endpoint), its keywords in turn, at most DEX_DAY a day; Birdeye search only with BIRDEYE_API_KEY,
     every BIRD_EVERY_S, at most BIRD_DAY a day. Every result is checked with the token-aware matcher again
     (DexScreener's search is fuzzy: "GTA6" also returns GTA5 tokens).
  5. roles (topics/roles.py) every ROLE_EVERY_S or when a token was added: market numbers from what we store, the rug
     check of get_trade_candidates, X rows we already have (no paid X call), the sniper share from stored reports;
     Helius (first page of the mint, ~100 credits) only for a token under 30 min old at 30k+ without a stored share,
     at most HELIUS_DAY credits a day.
  6. the price 24 h before event_ts, at event_ts and 24 h after for every token of a topic with an event time: from
     range.db snapshots, hype.db token_pulse and stored minute candles; GeckoTerminal (one request around the point)
     only when nothing is stored, at most GT_DAY a day, once per point.
Network calls go through the Net seam (the offline tests pass their own). Writes topics.db only.
"""
import json
import os
import sqlite3
import time

from topics import match, roles, store, view

DEX_DAY = int(os.environ.get("TOPICS_DEX_DAY", "1200"))
BIRD_DAY = int(os.environ.get("TOPICS_BIRDEYE_DAY", "100"))
GT_DAY = int(os.environ.get("TOPICS_GT_DAY", "20"))
HELIUS_DAY = int(os.environ.get("TOPICS_HELIUS_DAY", "1000"))
HELIUS_CHECK = 100            # one enhanced-transactions page
SEARCH_EVERY_S = 600
BIRD_EVERY_S = 1800
ROLE_EVERY_S = 600
AUTO_DONE_S = 7 * 86400
POINT_S = 24 * 3600
NEAR_S = 30 * 60              # a stored price this close to the point counts
MIN_MCAP = 30_000             # CLAUDE.md: under 30k is not analysed (no paid call for it)
CAPS = (("dexscreener", "dex", lambda: DEX_DAY), ("birdeye", "bird", lambda: BIRD_DAY), ("gt", "gt", lambda: GT_DAY),
        ("helius", "helius", lambda: HELIUS_DAY))


class Net:
    """The network seams."""

    def dex_search(self, q):
        from dexscreener import client
        return client.search(q)

    def bird_search(self, q):
        """[{address, name, symbol, mcap, liq, vol_h24, created_ts}] from Birdeye search; None without the key."""
        key = os.environ.get("BIRDEYE_API_KEY")
        if not key:
            return None
        import urllib.parse
        import urllib.request
        from event_calendar import http
        url = ("https://public-api.birdeye.so/defi/v3/search?" + urllib.parse.urlencode(
            {"chain": "solana", "keyword": q, "target": "token", "sort_by": "volume_24h_usd", "sort_type": "desc",
             "offset": 0, "limit": 20}))
        req = urllib.request.Request(url, headers={"X-API-KEY": key, "x-chain": "solana", "Accept": "application/json",
                                                   "User-Agent": http.USER_AGENT})
        d = http._fetch(req, 20, retries=1)
        out = []
        for it in ((d or {}).get("data") or {}).get("items") or []:
            for t in (it or {}).get("result") or []:
                if isinstance(t, dict) and t.get("address"):
                    out.append({"address": t["address"], "name": t.get("name"), "symbol": t.get("symbol"),
                                "mcap": t.get("market_cap"), "liq": t.get("liquidity"),
                                "vol_h24": t.get("volume_24h_usd"), "created_ts": _ts(t.get("creation_time"))})
        return out

    def gt_minutes(self, pool, start, end):
        from kol import minute
        return minute.minutes(pool, start, end)

    def helius_snipers(self, mint):
        """Snipers + bundle share of the supply from the mint's first 100 transactions (one Helius page)."""
        from rugfilter import analysis as A, helius
        early = helius.address_txs(mint, 100, "asc")
        pools = A.curve_accounts(A.find_creation(early, mint), mint)
        L = A.launch(early, mint, 1e9, pools)
        if not L:
            return None
        return round((L.get("sniper_pct") or 0) + (L.get("bundle_pct") or 0), 2)


def _ts(x):
    if x in (None, ""):
        return None
    try:
        v = float(x)
        return int(v / 1000 if v > 1e11 else v)
    except (TypeError, ValueError):
        pass
    try:
        from datetime import datetime
        return int(datetime.fromisoformat(str(x).replace("Z", "+00:00")).timestamp())
    except ValueError:
        return None


def _meter(service, method, n=1, amount=0.0):
    try:
        from usage import meter
        meter.record(service, method, amount, calls=n)
    except Exception:  # noqa: BLE001
        pass


def left(con, key, cap, now):
    return max(0, cap - store.day_used(con, key, now))


def spend_line(con, now, log):
    """At the first pass of a new UTC day: one line with every source's use of the day that ended."""
    today = store._day(now)
    last = store.kv_get(con, "spend_day")
    if last == today:
        return None
    store.kv_put(con, "spend_day", today)
    if not last:
        return None
    parts = []
    for name, key, cap in CAPS:
        d = store.kv_get(con, f"day:{key}") or {}
        parts.append(f"{name} {int(d.get(last, 0))}/{cap()}" + (" kredita" if key == "helius" else ""))
    line = f"eventi trošak ({last}): " + ", ".join(parts)
    log(line)
    return line


def auto_done(con, now, log):
    n = 0
    for t in store.topics(con, store.ACTIVE):
        if t.get("event_ts") and now - t["event_ts"] > AUTO_DONE_S:
            con.execute("UPDATE event_topics SET status='done', updated_ts=? WHERE id=?", (now, t["id"]))
            store.log(con, t["id"], "auto", f"done: {AUTO_DONE_S // 86400} dana nakon događaja", now)
            log(f"eventi: tema #{t['id']} {t['name']} završena ({AUTO_DONE_S // 86400} dana nakon događaja)")
            n += 1
    return n


# ---------- matching from what we store (free) ------------------------------------------------------------------------

def _ro_file(path):
    if not path or not os.path.exists(path) or not os.path.getsize(path):
        return None
    try:
        return sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=10)
    except sqlite3.Error:
        return None


def _hype_path():
    from rangedca import data as rdata
    return rdata.hype_path()


def _scan_path():
    from scan import store as sstore
    return sstore.db_path()


def scan_stored(con, m, now, since, hype_db=None, scan_db=None):
    """Match stored tokens newer than `since` (per source) against matcher m. Returns (new matches, newest ts per
    source). Streams the rows (no table is loaded whole)."""
    new, wm = 0, dict(since)
    hc = _ro_file(hype_db or _hype_path())
    if hc is not None:
        try:
            for mint, ts, name, sym, pool in hc.execute("SELECT mint, ts, name, symbol, pool FROM live_launches WHERE ts > ? "
                                                        "ORDER BY ts", (int(since.get("launch", 0)),)):
                mig = pool == "migration"
                for tid, (field, kw) in m.match(sym, name).items():
                    new += store.add_match(con, tid, mint, now, field, kw,
                                           "pumpportal_migration" if mig else "pumpportal_create", sym, name,
                                           None if mig else ts)
                wm["launch"] = max(wm.get("launch", 0), ts or 0)
        except sqlite3.Error:
            pass
        finally:
            hc.close()
    sc = _ro_file(scan_db or _scan_path())
    if sc is not None:
        try:
            for tok, ts, sym, name in sc.execute("SELECT token, checked_ts, symbol, name FROM cand WHERE checked_ts > ? "
                                                 "ORDER BY checked_ts", (int(since.get("cand", 0)),)):
                for tid, (field, kw) in m.match(sym, name).items():
                    new += store.add_match(con, tid, tok, now, field, kw, "skener", sym, name)
                wm["cand"] = max(wm.get("cand", 0), ts or 0)
            for tok, ts, desc, sym, name in sc.execute(
                    "SELECT p.token, p.ts, p.description, c.symbol, c.name FROM profiles p LEFT JOIN cand c ON "
                    "c.token = p.token WHERE p.ts > ? ORDER BY p.ts", (int(since.get("profile", 0)),)):
                for tid, (field, kw) in m.match(sym, name, desc).items():
                    new += store.add_match(con, tid, tok, now, field, kw, "dexscreener_profil", sym, name)
                wm["profile"] = max(wm.get("profile", 0), ts or 0)
        except sqlite3.Error:
            pass
        finally:
            sc.close()
    return new, wm


def match_stored(con, act, now, log, hype_db=None, scan_db=None):
    """New topics (backfill_ts NULL) against everything stored, then every active topic against the newer rows."""
    new = 0
    fresh = [t for t in act if not t.get("backfill_ts")]
    if fresh:
        m = match.Matcher({t["id"]: t["keywords"] for t in fresh})
        n, _ = scan_stored(con, m, now, {}, hype_db, scan_db)
        for t in fresh:
            con.execute("UPDATE event_topics SET backfill_ts=? WHERE id=?", (now, t["id"]))
        if n:
            log(f"eventi: {n} spremljenih tokena odgovara novim temama ({', '.join(t['name'] for t in fresh)})")
        new += n
    wm = store.kv_get(con, "wm") or {}
    if not wm:   # first pass ever: start from now (the backfill above covered what was stored)
        wm = {"launch": now, "cand": now, "profile": now}
    n, wm2 = scan_stored(con, match.Matcher({t["id"]: t["keywords"] for t in act}), now, wm, hype_db, scan_db)
    store.kv_put(con, "wm", wm2)
    return new + n


# ---------- search (budgeted) -------------------------------------------------------------------------------------------

def queries(t):
    """The topic's search strings: its keywords without "$", one per normal form, in the order given."""
    out, seen = [], set()
    for k in t["keywords"]:
        n = match.norm(k)
        if n not in seen:
            seen.add(n)
            out.append(k.replace("$", "").strip())
    return out or [t["name"]]


def pair_metrics(pairs):
    """{token: (symbol, name, created_ts, metrics)} of DexScreener pairs (Solana only), the deepest pair's numbers."""
    by = {}
    for p in pairs or []:
        if not isinstance(p, dict) or p.get("chainId") != "solana":
            continue
        b = p.get("baseToken") or {}
        tok = b.get("address")
        if not tok:
            continue
        by.setdefault(tok, []).append(p)
    out = {}
    for tok, ps in by.items():
        liq = lambda p: ((p.get("liquidity") or {}).get("usd") or 0)  # noqa: E731
        best = max(ps, key=liq)
        vol, ch = best.get("volume") or {}, best.get("priceChange") or {}
        created = [int(p["pairCreatedAt"] / 1000) for p in ps if p.get("pairCreatedAt")]
        b = best.get("baseToken") or {}
        m = {"price": float(best.get("priceUsd") or 0) or None, "mcap": best.get("marketCap") or best.get("fdv"),
             "liq": liq(best), "vol_h1": vol.get("h1"), "vol_h24": vol.get("h24"), "ch_h1": ch.get("h1"),
             "pool": best.get("pairAddress"), "dex": best.get("dexId"),
             "bonded": any(liq(p) > 0 and p.get("dexId") != "pumpfun" for p in ps)}
        out[tok] = (b.get("symbol"), b.get("name"), min(created) if created else None, m)
    return out


def search(con, act, now, net, log):
    """The least recently searched topic first (the oldest on a tie), so a tight day cap still rotates them."""
    new = 0
    for t in sorted(act, key=lambda t: (t.get("last_search_ts") or 0, t["id"])):
        m = match.Matcher({t["id"]: t["keywords"]})
        if now - (t.get("last_search_ts") or 0) >= SEARCH_EVERY_S and left(con, "dex", DEX_DAY, now) > 0:
            qs = queries(t)
            q = qs[(t.get("search_i") or 0) % len(qs)]
            store.day_add(con, "dex", 1, now)
            _meter("dexscreener", "eventi pretraga")
            con.execute("UPDATE event_topics SET last_search_ts=?, search_i=COALESCE(search_i, 0)+1 WHERE id=?",
                        (now, t["id"]))
            try:
                pairs = net.dex_search(q)
            except Exception as e:  # noqa: BLE001 - one failed search is the next pass's
                log(f"eventi: DexScreener pretraga '{q}': {type(e).__name__}")
                pairs = []
            for tok, (sym, name, created, met) in pair_metrics(pairs).items():
                hit = m.match(sym, name).get(t["id"])
                if hit:
                    new += store.add_match(con, t["id"], tok, now, hit[0], hit[1], "dexscreener_search", sym, name,
                                           created, met)
        if (now - (t.get("last_bird_ts") or 0) >= BIRD_EVERY_S and os.environ.get("BIRDEYE_API_KEY")
                and left(con, "bird", BIRD_DAY, now) > 0):
            qs = queries(t)
            q = qs[(t.get("search_i") or 0) % len(qs)]
            store.day_add(con, "bird", 1, now)
            _meter("birdeye", "eventi pretraga")
            con.execute("UPDATE event_topics SET last_bird_ts=? WHERE id=?", (now, t["id"]))
            try:
                res = net.bird_search(q) or []
            except Exception as e:  # noqa: BLE001
                log(f"eventi: Birdeye pretraga '{q}': {type(e).__name__}")
                res = []
            for r in res:
                hit = m.match(r.get("symbol"), r.get("name")).get(t["id"])
                if hit:
                    met = {k: r.get(k) for k in ("mcap", "liq", "vol_h24")}
                    new += store.add_match(con, t["id"], r["address"], now, hit[0], hit[1], "birdeye_search",
                                           r.get("symbol"), r.get("name"), r.get("created_ts"), met)
    return new


# ---------- roles --------------------------------------------------------------------------------------------------------

def roles_pass(con, act, now, net, log, rug=None, x=None):
    """Recompute the role of every token of the active topics. rug / x: stand-ins (tests)."""
    n = 0
    for t in act:
        rows = store.tokens_of(con, t["id"])
        if not rows:
            continue
        toks = [r["token"] for r in rows]
        mk = view.latest_market(toks, now)
        sn = view.sniper_shares(toks)
        rugs = rug if rug is not None else view._rugs(rows, mk)
        xs = x if x is not None else view._x(toks, now)
        inp = []
        for r in rows:
            m0 = r.get("metrics") or {}
            m = {**m0, **{k: v for k, v in (mk.get(r["token"]) or {}).items() if v is not None}}
            share = (sn.get(r["token"]) or (m0.get("sniper_pct"), None))[0]
            age = now - r["created_ts"] if r.get("created_ts") else None
            if (share is None and age is not None and age < roles.CLONE_AGE_S and (m.get("mcap") or 0) >= MIN_MCAP
                    and left(con, "helius", HELIUS_DAY, now) >= HELIUS_CHECK and os.environ.get("HELIUS_API_KEY")):
                store.day_add(con, "helius", HELIUS_CHECK, now)
                try:
                    share = net.helius_snipers(r["token"])
                except Exception as e:  # noqa: BLE001
                    log(f"eventi: Helius snajperi {r['token'][:6]}: {type(e).__name__}")
                    share = None
                if share is not None:
                    m0 = {**m0, "sniper_pct": share, "sniper_src": "Helius prva stranica (snajperi + bundle)"}
                    con.execute("UPDATE topic_tokens SET metrics=? WHERE topic_id=? AND token=?",
                                (json.dumps(m0, separators=(",", ":")), t["id"], r["token"]))
            inp.append({"token": r["token"], "created_ts": r.get("created_ts"), "sniper_pct": share,
                        "rug_level": (rugs.get(r["token"]) or {}).get("level"), "liq": m.get("liq"),
                        "mcap": m.get("mcap"), "bonded": m.get("bonded", bool(m.get("liq"))), "x": xs.get(r["token"])})
        for tok, (role, why) in roles.classify(inp, now).items():
            cur = con.execute("UPDATE topic_tokens SET role=?, role_why=? WHERE topic_id=? AND token=? AND "
                              "(COALESCE(role, '') != ? OR COALESCE(role_why, '') != COALESCE(?, ''))",
                              (role, why, t["id"], tok, role, why))
            n += cur.rowcount
    store.kv_put(con, "last_roles", now)
    return n


# ---------- the price around the event ------------------------------------------------------------------------------------

def stored_price(token, ts, near=NEAR_S):
    """(price, mcap, source) nearest to ts within `near` from range.db snaps, hype.db token_pulse, range.db gt_candles
    and minute.db call_candles; None when nothing stored is that close."""
    best = None
    try:
        from rangedca import data as rdata
        rc = rdata.ro()
        if rc is not None:
            try:
                r = rc.execute("SELECT ts, price, mcap FROM snaps WHERE token=? AND ts BETWEEN ? AND ? AND price > 0 "
                               "ORDER BY ABS(ts - ?) LIMIT 1", (token, int(ts - near), int(ts + near), int(ts))).fetchone()
                if r:
                    best = (abs(r[0] - ts), r[1], r[2], "range.db snimka")
                c = [x for x in rdata.gt_rows(rc, token, ts - near, ts + near)]
                if c:
                    k = min(c, key=lambda x: abs(x[0] - ts))
                    if best is None or abs(k[0] - ts) < best[0]:
                        best = (abs(k[0] - ts), k[4], None, "GeckoTerminal minuta (range.db)")
            finally:
                rc.close()
        hc = _ro_file(rdata.hype_path())
        if hc is not None:
            try:
                r = hc.execute("SELECT ts, price, mcap FROM token_pulse WHERE token=? AND ts BETWEEN ? AND ? AND price > 0 "
                               "ORDER BY ABS(ts - ?) LIMIT 1", (token, int(ts - near), int(ts + near), int(ts))).fetchone()
                if r and (best is None or abs(r[0] - ts) < best[0]):
                    best = (abs(r[0] - ts), r[1], r[2], "hype.db token_pulse")
            except sqlite3.Error:
                pass
            finally:
                hc.close()
        c = rdata.call_candles(token, ts - near, ts + near)
        if c:
            k = min(c, key=lambda x: abs(x[0] - ts))
            if best is None or abs(k[0] - ts) < best[0]:
                best = (abs(k[0] - ts), k[4], None, "GeckoTerminal minuta (minute.db)")
    except Exception:  # noqa: BLE001
        return None
    return best[1:] if best else None


POINTS = (("before", -POINT_S), ("at", 0), ("after", POINT_S))


def measure_pass(con, now, net, log, price_fn=None):
    """Fill the three points of every token of every topic with an event time whose point has passed."""
    price_fn = price_fn or stored_price
    n = 0
    for t in store.topics(con):
        ev = t.get("event_ts")
        if not ev or now < ev - POINT_S or now > ev + POINT_S + 3 * 86400:
            continue
        have = {r[0]: r for r in con.execute("SELECT token, before_px, at_px, after_px, note FROM topic_measure "
                                             "WHERE topic_id=?", (t["id"],))}
        for r in store.tokens_of(con, t["id"]):
            tok = r["token"]
            h = have.get(tok)
            if h is None:
                con.execute("INSERT OR IGNORE INTO topic_measure (topic_id, token, event_ts, updated_ts) VALUES (?,?,?,?)",
                            (t["id"], tok, ev, now))
                h = (tok, None, None, None, "")
            tried = set((h[4] or "").split(",")) - {""}
            m0 = r.get("metrics") or {}
            supply = (m0["mcap"] / m0["price"]) if m0.get("mcap") and m0.get("price") else None
            for i, (name, off) in enumerate(POINTS):
                at = ev + off
                if h[1 + i] is not None or now < at:
                    continue
                if r.get("created_ts") and r["created_ts"] > at + NEAR_S:
                    if f"nije:{name}" not in tried:
                        tried.add(f"nije:{name}")
                    continue
                got = price_fn(tok, at)
                if got is None and f"gt:{name}" not in tried and left(con, "gt", GT_DAY, now) > 0:
                    pool = m0.get("pool") or _pool(tok)
                    if pool:
                        tried.add(f"gt:{name}")
                        store.day_add(con, "gt", 1, now)
                        _meter("coingecko", "eventi mjerenje")
                        try:
                            cs = net.gt_minutes(pool, at - NEAR_S, at + NEAR_S) or []
                        except Exception as e:  # noqa: BLE001
                            log(f"eventi: GeckoTerminal {tok[:6]}: {type(e).__name__}")
                            cs = []
                        if cs:
                            k = min(cs, key=lambda c: abs(c[0] - at))
                            got = (k[4], None, "GeckoTerminal minuta (eventi)")
                if got is None:
                    continue
                px, mc, src = got
                if mc is None and supply and px:
                    mc = px * supply
                con.execute(f"UPDATE topic_measure SET {name}_ts=?, {name}_px=?, {name}_mc=?, {name}_src=?, updated_ts=? "
                            f"WHERE topic_id=? AND token=?", (at, px, mc, src, now, t["id"], tok))
                n += 1
            con.execute("UPDATE topic_measure SET note=? WHERE topic_id=? AND token=?",
                        (",".join(sorted(tried)) or None, t["id"], tok))
    return n


def _pool(token):
    try:
        from rangedca import data as rdata
        rc = rdata.ro()
        if rc is None:
            return None
        try:
            r = rc.execute("SELECT pool FROM pools WHERE token=?", (token,)).fetchone()
            return r[0] if r else None
        finally:
            rc.close()
    except Exception:  # noqa: BLE001
        return None


# ---------- the pass ------------------------------------------------------------------------------------------------------

def once(now=None, log=print, net=None, path=None, hype_db=None, scan_db=None, rug=None, x=None, price_fn=None):
    """One pass. Returns a short text ("off" while the flag is off: nothing is read or fetched)."""
    if store.mode() == "off":
        return "off"
    now = int(now or time.time())
    net = net or Net()
    con = store.connect(path)
    try:
        spend_line(con, now, log)
        auto_done(con, now, log)
        act = store.topics(con, store.ACTIVE)
        new = match_stored(con, act, now, log, hype_db, scan_db) if act else 0
        new += search(con, act, now, net, log) if act else 0
        con.commit()
        changed = 0
        if act and (new or now - (store.kv_get(con, "last_roles") or 0) >= ROLE_EVERY_S):
            changed = roles_pass(con, act, now, net, log, rug, x)
            con.commit()
        measured = measure_pass(con, now, net, log, price_fn)
        con.execute("DELETE FROM topic_log WHERE ts < ?", (now - 30 * 86400,))
        con.commit()
        text = (f"eventi: {len(act)} aktivnih tema, novih tokena {new}, promijenjenih uloga {changed}, izmjerenih "
                f"točaka {measured}; danas DexScreener {store.day_used(con, 'dex', now)}/{DEX_DAY}, Birdeye "
                f"{store.day_used(con, 'bird', now)}/{BIRD_DAY}, GeckoTerminal {store.day_used(con, 'gt', now)}/{GT_DAY}, "
                f"Helius {store.day_used(con, 'helius', now)}/{HELIUS_DAY} kredita")
        if new or changed or measured:
            log(text)
        return text
    finally:
        con.close()
