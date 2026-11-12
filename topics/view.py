"""What MCP clients, the Autopilot page, get_hourly_brief and get_trade_candidates see of the event topics.

    submit()          MCP submit_event_topic: upsert a topic by name (Grok, or the owner through run_topics.py add)
    list_topics()     MCP get_event_topics: the topics with their ids, buzz trend and how many tokens match
    tokens()          MCP get_event_tokens: the matched Solana tokens of one topic with market, rug, holders, X, range,
                      role and the price around the event, plus the topic's measured summary
    card_html()       the "Eventi" card under "Još" on the Autopilot page (owner only, closed)
    brief_part()      one short part of get_hourly_brief
    kandidati_rows()  the source "event" of ui/kandidati (main / other tokens of active topics)
Read-only except submit(). Nothing here trades: an event token is at most paper-traded by range_dca on the demo
account (flag event_tokens paper), never with real money.
"""
import json
import os
import re
import sqlite3
import statistics
import time

from topics import match, roles, store

RATE_PER_HOUR = int(os.environ.get("TOPICS_RATE_PER_HOUR", "60"))
MAX_ACTIVE = int(os.environ.get("TOPICS_MAX_ACTIVE", "8"))
NAME_MAX = 60
NOTE_MAX = 500
SPARK = "▁▂▃▄▅▆▇█"
ORDER = {"upcoming": 0, "live": 1, "done": 2}
MARKET_FRESH_S = 30 * 60
ROLE_ORDER = {"main": 0, "other": 1, "clone": 2, "rug": 3}
ISO = re.compile(r"^\d{4}-\d{2}-\d{2}")


# ---------- small helpers --------------------------------------------------------------------------------------------

def _num(x, name, lo, hi):
    if isinstance(x, bool):
        raise ValueError(f"{name} must be a number")
    try:
        v = float(x)
    except (TypeError, ValueError):
        raise ValueError(f"{name} must be a number")
    if not lo <= v <= hi:
        raise ValueError(f"{name} must be between {lo:g} and {hi:g}")
    return v


def parse_ts(x, now):
    """unix seconds / milliseconds or ISO 8601 -> unix seconds; ValueError outside 2020 .. now + 2 years."""
    if isinstance(x, str) and ISO.match(x.strip()):
        from datetime import datetime, timezone
        s = x.strip().replace("Z", "+00:00")
        try:
            d = datetime.fromisoformat(s)
        except ValueError:
            raise ValueError("event_ts must be unix seconds or ISO 8601")
        if d.tzinfo is None:
            d = d.replace(tzinfo=timezone.utc)
        v = d.timestamp()
    else:
        v = _num(x, "event_ts", 0, 1e14)
        if v > 1e11:
            v /= 1000
    if not 1_577_836_800 <= v <= now + 2 * 365 * 86400:
        raise ValueError("event_ts must be unix seconds between 2020 and two years from now")
    return int(v)


def trend(hist):
    """(arrow, sparkline) of a buzz history [[ts, score], ...]: up when the newest point is 15 % over the mean of the
    three before it, down when 13 % under, flat otherwise; '' without two points."""
    pts = [p[1] for p in hist or [] if isinstance(p, (list, tuple)) and len(p) >= 2 and p[1] is not None]
    if len(pts) < 2:
        return "", ""
    prev = pts[-4:-1]
    base = sum(prev) / len(prev)
    arrow = "↑" if pts[-1] > base * 1.15 else "↓" if pts[-1] < base * 0.87 else "→"
    last = pts[-12:]
    lo, hi = min(last), max(last)
    spark = "".join(SPARK[int((p - lo) / (hi - lo) * (len(SPARK) - 1)) if hi > lo else 3] for p in last)
    return arrow, spark


def _topic_out(t, n_tokens=None, main=None):
    arrow, spark = trend(t.get("buzz_hist"))
    return {"id": t["id"], "name": t["name"], "keywords": t["keywords"], "event_ts": t.get("event_ts"),
            "status": t["status"], "buzz_score": t.get("buzz_score"), "buzz_trend": arrow or None,
            "buzz_spark": spark or None, "buzz_history": [[int(p[0]), p[1]] for p in (t.get("buzz_hist") or [])][-12:],
            "source": t.get("source"), "created_by": t.get("created_by"), "created_ts": t.get("created_ts"),
            "updated_ts": t.get("updated_ts"), "note": t.get("note"), "n_tokens": n_tokens, "main": main}


# ---------- submit_event_topic ---------------------------------------------------------------------------------------

def submit(name, keywords=None, event_ts=None, buzz_score=None, status=None, source=None, note=None, kid="local",
           created_by="grok", now=None, path=None, trade_db=None):
    """Upsert one topic by name (its normal form); returns the stored topic and what changed. ValueError with the
    reason for the client: the flag is off (Grok only), the hourly limit, a bad field, a status moving backwards,
    more than MAX_ACTIVE active topics."""
    now = int(now or time.time())
    owner = created_by == "owner"
    if not owner and store.mode(trade_db) == "off":
        raise ValueError("event topics are switched off (flag event_tokens is off): nothing stored")
    nm = str(name or "").strip()
    key = match.norm(nm)
    if not 2 <= len(nm) <= NAME_MAX or len(key) < 2:
        raise ValueError(f"name must be 2-{NAME_MAX} characters with at least 2 letters or digits")
    kws = match.validate(keywords) if keywords is not None else None
    ets = parse_ts(event_ts, now) if event_ts not in (None, "") else None
    buzz = round(_num(buzz_score, "buzz_score", 0, 100), 2) if buzz_score not in (None, "") else None
    st = str(status).strip().lower() if status not in (None, "") else None
    if st is not None and st not in store.STATUSES:
        raise ValueError(f"status must be one of {', '.join(store.STATUSES)}")
    src = str(source or "").strip()[:40] or None
    nt = str(note or "").strip()[:NOTE_MAX] or None
    con = store.connect(path)
    try:
        n = con.execute("SELECT COUNT(*) FROM topic_log WHERE kid=? AND ts>?", (kid, now - 3600)).fetchone()[0]
        if not owner and n >= RATE_PER_HOUR:
            raise ValueError(f"rate limit: at most {RATE_PER_HOUR} topic writes an hour per key")
        cur = con.execute("SELECT * FROM event_topics WHERE name_key=?", (key,))
        cols = [c[0] for c in cur.description]
        row = cur.fetchone()
        old = store.topic_row(row, cols) if row else None
        n_active = con.execute(f"SELECT COUNT(*) FROM event_topics WHERE status IN ({','.join('?' * len(store.ACTIVE))})",
                               store.ACTIVE).fetchone()[0]
        changed = []
        if old is None:
            if kws is None:
                raise ValueError("a new topic needs keywords (e.g. [\"GTA6\", \"GTA 6\", \"Grand Theft Auto\", \"$GTA6\"])")
            st = st or "upcoming"
            if st in store.ACTIVE and n_active >= MAX_ACTIVE:
                raise ValueError(f"at most {MAX_ACTIVE} active topics (upcoming / live): mark one done first")
            hist = [[now, buzz]] if buzz is not None else []
            cur = con.execute("INSERT INTO event_topics (name, name_key, keywords, event_ts, buzz_score, buzz_hist, source, "
                              "created_by, kid, status, created_ts, updated_ts, note) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                              (nm, key, json.dumps(kws, ensure_ascii=False), ets, buzz, json.dumps(hist), src or "x",
                               "owner" if owner else "grok", kid, st, now, now, nt))
            tid = cur.lastrowid
            changed = ["created"]
        else:
            tid = old["id"]
            sets, args = [], []
            if st is not None and st != old["status"]:
                if not owner and ORDER[st] < ORDER[old["status"]]:
                    raise ValueError(f"status can only move forward (upcoming -> live -> done); it is {old['status']}")
                if st in store.ACTIVE and old["status"] not in store.ACTIVE and n_active >= MAX_ACTIVE:
                    raise ValueError(f"at most {MAX_ACTIVE} active topics (upcoming / live)")
                sets.append("status=?")
                args.append(st)
                changed.append(f"status {old['status']} -> {st}")
            if kws is not None and kws != old["keywords"]:
                sets += ["keywords=?", "backfill_ts=NULL"]   # new keywords: the stored launches are matched again
                args.append(json.dumps(kws, ensure_ascii=False))
                changed.append("keywords")
            if ets is not None and ets != old.get("event_ts"):
                sets.append("event_ts=?")
                args.append(ets)
                changed.append("event_ts")
            if buzz is not None:
                hist = list(old.get("buzz_hist") or [])
                if hist and now - int(hist[-1][0]) < 300:
                    hist[-1] = [now, buzz]          # one point per 5 minutes: a burst of updates is one point
                else:
                    hist.append([now, buzz])
                sets += ["buzz_score=?", "buzz_hist=?"]
                args += [buzz, json.dumps(hist[-store.BUZZ_KEEP:])]
                changed.append("buzz")
            if src and src != old.get("source"):
                sets.append("source=?")
                args.append(src)
            if nt:
                sets.append("note=?")
                args.append(nt)
            if sets:
                con.execute(f"UPDATE event_topics SET {', '.join(sets)}, updated_ts=? WHERE id=?", (*args, now, tid))
        store.log(con, tid, kid, ", ".join(changed) or "bez promjene", now)
        con.commit()
        t = store.topic(con, tid)
        n_tok = con.execute("SELECT COUNT(*) FROM topic_tokens WHERE topic_id=?", (tid,)).fetchone()[0]
    finally:
        con.close()
    print(f"eventi: tema #{tid} {nm}: {', '.join(changed) or 'bez promjene'} ({'vlasnik' if owner else kid})", flush=True)
    out = _topic_out(t, n_tok)
    out.update(created=changed[:1] == ["created"], changed=changed,
               message=("Stored. MemeSonar matches the keywords (token-aware: GTA6 never matches GTA or GTAV) against "
                        "new pump.fun tokens in real time and searches DexScreener every 10 min while the topic is "
                        "upcoming or live; get_event_tokens(topic_id) lists the tokens with their role "
                        "(main / clone / rug / other). Nothing is bought with real money."))
    return out


# ---------- get_event_topics -----------------------------------------------------------------------------------------

def list_topics(status=None, limit=50, path=None, now=None):
    now = int(now or time.time())
    try:
        lim = max(1, min(100, int(limit if limit is not None else 50)))
    except (TypeError, ValueError):
        lim = 50
    st = str(status).strip().lower() if status else None
    if st and st not in store.STATUSES + ("active",):
        return {"error": "status must be upcoming, live, done or active"}
    con = store.ro(path)
    out = []
    if con is not None:
        try:
            ts = store.topics(con, store.ACTIVE if st == "active" else st)[:lim]
            for t in ts:
                n = con.execute("SELECT COUNT(*) FROM topic_tokens WHERE topic_id=?", (t["id"],)).fetchone()[0]
                m = con.execute("SELECT token, symbol FROM topic_tokens WHERE topic_id=? AND role='main' LIMIT 1",
                                (t["id"],)).fetchone()
                out.append(_topic_out(t, n, {"token": m[0], "symbol": m[1]} if m else None))
        except sqlite3.Error:
            out = []
        finally:
            con.close()
    return {"ts": now, "flag_mode": store.mode(), "max_active": MAX_ACTIVE, "topics": out,
            "notes": ("submit_event_topic adds or updates a topic (upsert by name); get_event_tokens(topic_id) lists its "
                      "tokens. Active = upcoming or live: only those are matched and searched.")}


# ---------- get_event_tokens -----------------------------------------------------------------------------------------

def _ro_file(path):
    if not path or not os.path.exists(path) or not os.path.getsize(path):
        return None
    try:
        return sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=10)
    except sqlite3.Error:
        return None


def latest_market(tokens, now):
    """{token: {price, mcap, liq, vol_h1, vol_h6, ts, src, pool, dex}} from what we already store: range.db snaps
    (the range watchlist) and hype.db token_pulse, the newer of the two within MARKET_FRESH_S."""
    out = {}
    if not tokens:
        return out
    toks = list(tokens)
    q = ",".join("?" * len(toks))
    try:
        from rangedca import data as rdata
        rc = rdata.ro()
        if rc is not None:
            try:
                for tok, ts, px, mc, liq, v1, v6 in rc.execute(
                        f"SELECT token, MAX(ts), price, mcap, liq, vol_h1, vol_h6 FROM snaps WHERE token IN ({q}) AND ts >= ? "
                        f"GROUP BY token", (*toks, int(now - MARKET_FRESH_S))):
                    out[tok] = {"price": px, "mcap": mc, "liq": liq, "vol_h1": v1, "vol_h6": v6, "ts": ts,
                                "src": "range.db snimka (DexScreener)"}
                for tok, pool, dex in rc.execute(f"SELECT token, pool, dex FROM pools WHERE token IN ({q})", toks):
                    out.setdefault(tok, {}).update(pool=pool, dex=dex)
            finally:
                rc.close()
        hc = _ro_file(rdata.hype_path())
        if hc is not None:
            try:
                for tok, ts, px, mc, liq, v1, hold in hc.execute(
                        f"SELECT token, MAX(ts), price, mcap, liquidity, vol_h1, holders FROM token_pulse WHERE token IN ({q}) "
                        f"AND ts >= ? GROUP BY token", (*toks, int(now - MARKET_FRESH_S))):
                    cur = out.get(tok) or {}
                    if (cur.get("ts") or 0) < ts:
                        out[tok] = {**cur, "price": px, "mcap": mc, "liq": liq, "vol_h1": v1, "ts": ts,
                                    "src": "hype.db token_pulse (DexScreener)"}
                    if hold:
                        out.setdefault(tok, {})["holders"] = hold
            except sqlite3.Error:
                pass
            finally:
                hc.close()
    except Exception:  # noqa: BLE001 - numbers we cannot read are unknown, never an error
        pass
    return out


def sniper_shares(tokens):
    """{token: (sniper %, source)}: the pump.fun board's snipers + bundlers holding now (hype.db hype_details), else
    the rug filter's sniper + bundle share of the first slots (rug.db). Free: both are already stored."""
    out = {}
    toks = list(tokens)
    if not toks:
        return out
    q = ",".join("?" * len(toks))
    try:
        from rangedca import data as rdata
        rc = _ro_file(os.environ.get("RUG_DB") or os.path.join(store.ROOT, "rug.db"))
        if rc is not None:
            try:
                for m, sn, b in rc.execute(f"SELECT mint, sniper_pct, bundle_pct FROM rug_reports WHERE mint IN ({q}) "
                                           f"ORDER BY checked_at", toks):
                    if sn is not None or b is not None:
                        out[m] = (round((sn or 0) + (b or 0), 2), "rug.db (snajperi + bundle u prvim slotovima)")
            except sqlite3.Error:
                pass
            finally:
                rc.close()
        hc = _ro_file(rdata.hype_path())
        if hc is not None:
            try:
                for tok, extra in hc.execute(f"SELECT token, extra FROM hype_details WHERE token IN ({q}) ORDER BY ts", toks):
                    try:
                        pf = (json.loads(extra or "{}") or {}).get("pumpfun") or {}
                    except ValueError:
                        continue
                    s, b = pf.get("snipersOwnedPercent"), pf.get("bundlerOwnedPercent")
                    if s is not None or b is not None:
                        out[tok] = (round(float(s or 0) + float(b or 0), 2), "pump.fun ploča (snajperi + bundleri drže)")
            except (sqlite3.Error, TypeError, ValueError):
                pass
            finally:
                hc.close()
    except Exception:  # noqa: BLE001
        pass
    return out


def _pct(a, b):
    return round((b / a - 1) * 100, 2) if a and b else None


def measure_summary(rows):
    """{n, run_up_pct_median (24 h before -> at the event), after_pct_median (at -> 24 h after), exit_at_event_better
    (share of tokens where selling at the event beat holding 24 h more)} of measured rows."""
    up = [_pct(r.get("before_px"), r.get("at_px")) for r in rows]
    up = [x for x in up if x is not None]
    aft = [_pct(r.get("at_px"), r.get("after_px")) for r in rows]
    aft = [x for x in aft if x is not None]
    return {"n_before_at": len(up), "run_up_pct_median": round(statistics.median(up), 2) if up else None,
            "n_at_after": len(aft), "after_pct_median": round(statistics.median(aft), 2) if aft else None,
            "exit_at_event_better": round(sum(1 for x in aft if x < 0) / len(aft), 3) if aft else None,
            "how": "price 24 h before event_ts, at event_ts and 24 h after, from stored snapshots (GeckoTerminal only "
                   "within a small daily cap); buy-the-rumor = before -> at, exit-before-event = at -> after < 0"}


def _measures(con, tid):
    cur = con.execute("SELECT * FROM topic_measure WHERE topic_id=?", (int(tid),))
    cols = [c[0] for c in cur.description]
    return {r[1]: dict(zip(cols, r)) for r in cur.fetchall()}


def tokens(topic_id, path=None, now=None, rug=None, x=None, ranges=None):
    """get_event_tokens. rug / x / ranges: the tests pass stand-ins for the rug check, X rows and range rows."""
    now = int(now or time.time())
    try:
        tid = int(topic_id)
    except (TypeError, ValueError):
        return {"error": "topic_id must be an integer (get_event_topics lists them)"}
    con = store.ro(path)
    if con is None:
        return {"error": f"no topic {tid} (no topics yet)"}
    try:
        t = store.topic(con, tid)
        if t is None:
            return {"error": f"no topic {tid} (get_event_topics lists them)"}
        rows = store.tokens_of(con, tid)
        meas = _measures(con, tid)
    finally:
        con.close()
    toks = [r["token"] for r in rows]
    mk = latest_market(toks, now)
    sn = sniper_shares(toks)
    xs = x if x is not None else _x(toks, now)
    rg = ranges if ranges is not None else _ranges(toks)
    rugs = rug if rug is not None else _rugs(rows, mk)
    out = []
    for r in rows:
        tok, m0 = r["token"], r.get("metrics") or {}
        m = mk.get(tok) or {}
        live = bool(m.get("ts"))
        num = (lambda k, k0=None: m.get(k) if live and m.get(k) is not None else m0.get(k0 or k))
        age = (now - r["created_ts"]) / 60 if r.get("created_ts") else None
        xr = xs.get(tok)
        mz = meas.get(tok) or {}
        rv = rugs.get(tok) or {}
        out.append({
            "token": tok, "symbol": r.get("symbol"), "name": r.get("name"), "role": r.get("role") or "other",
            "role_why": r.get("role_why"),
            "match": {"field": r.get("match_field"), "keyword": r.get("match_kw"), "via": r.get("via"),
                      "first_seen_ts": r.get("first_seen")},
            "age_min": round(age, 1) if age is not None else None,
            "market": {"price_usd": num("price"), "market_cap_usd": num("mcap"), "liquidity_usd": num("liq"),
                       "volume_1h_usd": num("vol_h1"), "volume_24h_usd": m0.get("vol_h24"),
                       "bonded": m0.get("bonded"), "dex": m.get("dex") or m0.get("dex"),
                       "ts": m.get("ts") if live else r.get("metrics_ts"),
                       "source": m.get("src") if live else (f"{r.get('via')} (u trenutku pretrage)" if m0 else None)},
            "holders": m.get("holders") or m0.get("holders"),
            "snipers_pct": (sn.get(tok) or (m0.get("sniper_pct"), m0.get("sniper_src")))[0],
            "snipers_source": (sn.get(tok) or (m0.get("sniper_pct"), m0.get("sniper_src")))[1],
            "rug": {k: rv.get(k) for k in ("level", "hard", "risk", "warn", "rug_filter", "topcheck")} if rv else None,
            "x": ({**{k: xr.get(k) for k in ("source", "ts", "x_momentum_score", "x_early", "posts60", "authors15",
                                             "bot_share")}, "organic": roles.organic(xr, now)} if xr else None),
            "range": rg.get(tok),
            "measure": {k: mz.get(k) for k in ("event_ts", "before_ts", "before_px", "before_src", "at_ts", "at_px",
                                               "at_src", "after_ts", "after_px", "after_src", "note")} if mz else None,
            "change_before_to_event_pct": _pct(mz.get("before_px"), mz.get("at_px")) if mz else None,
            "change_event_to_after_pct": _pct(mz.get("at_px"), mz.get("after_px")) if mz else None})
    out.sort(key=lambda d: (ROLE_ORDER.get(d["role"], 9), -((d["market"] or {}).get("liquidity_usd") or 0)))
    return {"ts": now, "flag_mode": store.mode(), "topic": _topic_out(t, len(out)), "tokens": out,
            "by_role": {k: sum(1 for d in out if d["role"] == k) for k in ROLE_ORDER},
            "measure_summary": measure_summary(list(meas.values())),
            "rules": {"clone": f"younger than {roles.CLONE_AGE_S // 60} min and snipers / bundlers hold more than "
                               f"{roles.CLONE_SNIPER_PCT:g} %",
                      "rug": "the rug check says hard or risk (as get_trade_candidates)",
                      "main": ("the most liquid token with organic X (>= 3 unique authors in 15 min or >= 10 posts in 60 "
                               "min, or a known caller / large account, bot share < 50 %); without any X row the oldest "
                               "bonded token with >= $20k liquidity"),
                      "matching": "token-aware: GTA6 matches 'GTA 6', 'gta-6', '$GTA6', never 'GTA', 'GTA5' or 'GTAV'",
                      "money": "never real money: at most paper on the demo account through range_dca (flag event_tokens "
                               "paper)"}}


def _x(toks, now):
    try:
        from scan import xmom
        return xmom.latest(toks, since=now - roles.X_FRESH_S, now=now)
    except Exception:  # noqa: BLE001
        return {}


def _ranges(toks):
    try:
        from rangedca import data as rdata, view as rview
        out = {}
        for tok, r in rdata.read_ranges(tokens=toks).items():
            o = rview.one(tok, r)
            out[tok] = {k: o.get(k) for k in ("status", "range_score", "position_in_range_pct", "entry_ready", "source",
                                              "sources", "computed_ts")}
            out[tok]["zones_market_cap_usd"] = ((o.get("zones") or {}).get("market_cap_usd"))
        return out
    except Exception:  # noqa: BLE001
        return {}


def _rugs(rows, mk):
    """{token: ui/kandidati.rug_view} (the rug check of get_trade_candidates and the scanner)."""
    try:
        from rugfilter import archive
        from scan import filters
        from ui import kandidati
        from league import copy as lcopy
        S = kandidati.Sources()
        tables = filters.rug_tables()
        arch = archive.blocked()
        mine = None
        if lcopy._CONC_CACHE is None:   # the two tables once for every token (as kandidati.build), not per token
            mine = lcopy._CONC_CACHE = {"tc": tables[0], "rug": tables[1]}
        try:
            out = {}
            for r in rows:
                m = mk.get(r["token"]) or r.get("metrics") or {}
                out[r["token"]] = kandidati.rug_view(r["token"], m.get("mcap"), m.get("liq"), S, tables, arch)
            return out
        finally:
            if mine is not None and lcopy._CONC_CACHE is mine:
                lcopy._CONC_CACHE = None
    except Exception:  # noqa: BLE001
        return {}


# ---------- the Autopilot card, the hourly brief, get_trade_candidates ------------------------------------------------

def _when(ts):
    if not ts:
        return "bez datuma"
    return time.strftime("%d.%m. %H:%M UTC", time.gmtime(ts))


def _usd(x):
    if not x:
        return "–"
    x = float(x)
    return f"{x / 1e6:.1f}M $".replace(".", ",") if x >= 1e6 else f"{x / 1e3:.0f}k $" if x >= 1e3 else f"{x:.0f} $"


ROLE_HR = {"main": "glavni", "clone": "klon", "rug": "rug", "other": "ostali"}


def card_html(sec, item, esc, path=None, trade_db=None, now=None, limit=12):
    """"Eventi" for the Autopilot page, under "Još", closed (ui/pravitrade passes its _sec / _item / esc). '' while
    the flag is off. Per topic: the event time, the buzz trend (arrow + sparkline text) and its tokens with market cap
    and role (glavni / klon / rug / ostali)."""
    if store.mode(trade_db) == "off":
        return ""
    now = int(now or time.time())
    con = store.ro(path)
    ts, toks = [], {}
    if con is not None:
        try:
            ts = [t for t in store.topics(con) if t["status"] in store.ACTIVE
                  or (t.get("updated_ts") or 0) >= now - 3 * 86400][:limit]
            toks = {t["id"]: store.tokens_of(con, t["id"]) for t in ts}
        except sqlite3.Error:
            ts, toks = [], {}
        finally:
            con.close()
    mk = latest_market({r["token"] for rs in toks.values() for r in rs}, now) if ts else {}
    items = []
    for t in ts:
        arrow, spark = trend(t.get("buzz_hist"))
        rows = sorted(toks.get(t["id"]) or [], key=lambda r: ROLE_ORDER.get(r.get("role") or "other", 9))
        lines = []
        for r in rows[:15]:
            mc = (mk.get(r["token"]) or {}).get("mcap") or (r.get("metrics") or {}).get("mcap")
            lines.append(f'<li><b>{esc(ROLE_HR.get(r.get("role") or "other", "ostali"))}</b> '
                         f'{esc(r.get("symbol") or r["token"][:6])} <code>{esc(r["token"][:6])}…</code> · MC {_usd(mc)}'
                         + (f' <span class=mut>({esc(r["role_why"])})</span>' if r.get("role_why") else "") + '</li>')
        body = (f'<p class=mut>{esc(", ".join(t["keywords"][:8]))} · {esc(t["status"])} · buzz '
                f'{t.get("buzz_score") if t.get("buzz_score") is not None else "–"} {esc(arrow)} {esc(spark)}</p>'
                + (f'<ul>{"".join(lines)}</ul>' if lines else '<p class=mut>Još nema tokena koji odgovaraju.</p>'))
        items.append(item(t["name"], f'{_when(t.get("event_ts"))} · {len(rows)} tokena', body,
                          value=(f'{arrow}' if arrow else None), iid=f'ev-{t["id"]}'))
    body = ("".join(items) if items else '<p class=mut>Još nema tema. Grok ih šalje alatom submit_event_topic.</p>') + \
        ('<p class=mut>Tokeni događaja se samo mjere (cijena 24 h prije, u trenutku i 24 h nakon); najviše paper na '
         'demo računu preko range_dca, nikad pravi novac.</p>')
    n_act = sum(1 for t in ts if t["status"] in store.ACTIVE)
    return sec("Eventi", f"{n_act} aktivnih tema", body, sid="eventi")


def brief_part(now=None, path=None):
    """get_hourly_brief: the active topics, each with its buzz trend, token count, main token and measured summary."""
    now = int(now or time.time())
    m = store.mode()
    if m == "off":
        return {"flag_mode": "off", "topics": []}
    con = store.ro(path)
    out = []
    if con is not None:
        try:
            for t in store.topics(con, store.ACTIVE)[:10]:
                n = con.execute("SELECT COUNT(*) FROM topic_tokens WHERE topic_id=?", (t["id"],)).fetchone()[0]
                mn = con.execute("SELECT token, symbol FROM topic_tokens WHERE topic_id=? AND role='main' LIMIT 1",
                                 (t["id"],)).fetchone()
                arrow, _ = trend(t.get("buzz_hist"))
                out.append({"id": t["id"], "name": t["name"], "status": t["status"], "event_ts": t.get("event_ts"),
                            "buzz_score": t.get("buzz_score"), "buzz_trend": arrow or None, "n_tokens": n,
                            "main": {"token": mn[0], "symbol": mn[1]} if mn else None,
                            "measure": measure_summary(list(_measures(con, t["id"]).values()))})
        except sqlite3.Error:
            pass
        finally:
            con.close()
    return {"flag_mode": m, "topics": out, "tool": "get_event_tokens(topic_id) for the tokens"}


def proposal_rows(now=None, days=7, path=None):
    """The canonical token of every upcoming / live event in the next `days` days (for the "Prijedlozi" list):
    [{"token", "symbol", "topic", "topic_id", "event_ts", "role", "mcap", "liq"}] of tokens with role main whose topic
    has an event_ts between now and now + days, soonest first; market cap and liquidity from what we store (range.db
    snapshots, hype.db token_pulse, else the numbers seen when the token was found). Read-only; [] without topics.db.
    It does not read the flag: with event_tokens off the job assigns no roles, so there is no main token to list."""
    now = int(now or time.time())
    try:
        horizon = now + float(days) * 86400
    except (TypeError, ValueError):
        horizon = now + 7 * 86400
    con = store.ro(path)
    if con is None:
        return []
    rows = []
    try:
        q = ",".join("?" * len(store.ACTIVE))
        rows = con.execute(
            f"SELECT tt.token, tt.symbol, t.name, t.id, t.event_ts, tt.role, tt.metrics FROM topic_tokens tt JOIN "
            f"event_topics t ON t.id = tt.topic_id WHERE t.status IN ({q}) AND tt.role = 'main' AND t.event_ts IS NOT NULL "
            f"AND t.event_ts >= ? AND t.event_ts <= ? ORDER BY t.event_ts, t.id", (*store.ACTIVE, now, int(horizon))).fetchall()
    except sqlite3.Error:
        rows = []
    finally:
        con.close()
    mk = latest_market({r[0] for r in rows}, now) if rows else {}
    out = []
    for tok, sym, topic, tid, ets, role, met in rows:
        try:
            m0 = json.loads(met or "{}") or {}
        except ValueError:
            m0 = {}
        m = mk.get(tok) or {}
        out.append({"token": tok, "symbol": sym, "topic": topic, "topic_id": tid, "event_ts": ets, "role": role,
                    "mcap": m.get("mcap") if m.get("mcap") is not None else m0.get("mcap"),
                    "liq": m.get("liq") if m.get("liq") is not None else m0.get("liq")})
    return out


def kandidati_rows(now=None, path=None):
    """[{"token", "symbol", "topic_id", "topic", "role", "event_ts", "buzz_score", "buzz_trend", "first_seen"}]: the
    main and other tokens of the active topics ([] while the flag is off)."""
    if store.mode() == "off":
        return []
    con = store.ro(path)
    if con is None:
        return []
    out = []
    try:
        for t in store.topics(con, store.ACTIVE):
            arrow, _ = trend(t.get("buzz_hist"))
            for r in store.tokens_of(con, t["id"]):
                if (r.get("role") or "other") in ("main", "other"):
                    out.append({"token": r["token"], "symbol": r.get("symbol"), "topic_id": t["id"], "topic": t["name"],
                                "role": r.get("role") or "other", "event_ts": t.get("event_ts"),
                                "buzz_score": t.get("buzz_score"), "buzz_trend": arrow or None,
                                "first_seen": r.get("first_seen")})
    except sqlite3.Error:
        return []
    finally:
        con.close()
    return out
