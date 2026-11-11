"""11.11. (Jure, preporuka 8 iz analize troška): one cost line per source a day, and the same numbers as JSON.

At 23:59 UTC (00:59 CET in winter: the minute before every daily counter of the bot resets at UTC midnight) run_sched
runs `run_usage.py dnevno`: collect() reads what the bot already counts, line() makes one log line of it and save()
keeps it in usage.db daily_cost (one JSON row per UTC day) for the weekly report (week(): the 7-day sums, shown in
events/evreport's "trošak po izvoru (7 dana)"). Read-only on every other database; no network.

Sources (all counted by the bot itself; nothing here is a provider's invoice):
  CoinGecko    the day file of event_calendar/http (key calls and free calls per job, HTTP 429 per UTC hour)
  twitterapi   kol.db kv twapi:<day> (all of it) and its parts: twtl (timeline), twdisc (discovery), twtrend
               (trending), scan.db xusd (the scanner), kol.db flash_day (deleted-post checks, ~$0.15 per 1000)
  Apify        hype.db apify_runs per source, and the account's own reading (usage.db account) a day apart
  PumpPortal   hype.db live_state trades_day (trades received today), 0.01 SOL per 10,000 trades
  Helius       usage.db usage per script (the bot's own count) and the account reading (Helius Admin API, taken every
               15 min by run_usage tick); without a reading: "stanje računa: /usage ručno"
  AI oznake    usage.db anthropic per method ($) and ai.db batches (posts sent)
"""
import json
import os
import sqlite3
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PP_SOL_PER_10K = 0.01
FLASH_USD = 0.00015   # twitterapi.io: $0.15 per 1000 posts returned (kol/deleted.py)
SCHEMA = "CREATE TABLE IF NOT EXISTS daily_cost (day TEXT PRIMARY KEY, ts INTEGER, data TEXT)"


def _paths():
    from kol import store as kstore
    from live import store as lstore
    from scan import store as sstore
    from usage import meter
    return {"kol": kstore.DB, "scan": sstore.db_path(), "hype": lstore.HYPE_DB, "usage": meter.DB,
            "ai": os.path.join(ROOT, "ai.db")}


def _ro(path):
    if not path or not os.path.exists(path):
        return None
    try:
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=10)
        con.execute("PRAGMA busy_timeout = 10000")
        return con
    except sqlite3.Error:
        return None


def _one(con, sql, args=(), default=None):
    if con is None:
        return default
    try:
        r = con.execute(sql, args).fetchone()
        return r[0] if r and r[0] is not None else default
    except sqlite3.Error:
        return default


def _all(con, sql, args=()):
    if con is None:
        return []
    try:
        return con.execute(sql, args).fetchall()
    except sqlite3.Error:
        return []


def _f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return 0.0


def _day(now):
    return time.strftime("%Y-%m-%d", time.gmtime(now))


def coingecko(now):
    try:
        from event_calendar import http
        st = http.cg_status(now)
    except Exception:  # noqa: BLE001
        return {}
    return {"kljuc": st["n"], "strop": st["cap"], "po_poslu": st["jobs"], "besplatno": st["free"],
            "besplatno_ukupno": sum(st["free"].values()), "e429": st["e429"], "e429_ukupno": sum(st["e429"].values()),
            "kljuc_postavljen": st["key"]}


def twitterapi(now, paths):
    day = _day(now)
    kcon, scon = _ro(paths["kol"]), _ro(paths["scan"])
    try:
        kv = lambda key: _f(_one(kcon, "SELECT value FROM kv WHERE key = ?", (key,)))  # noqa: E731
        total = kv(f"twapi:{day}")
        flash = 0.0
        try:
            fd = json.loads(_one(kcon, "SELECT value FROM kv WHERE key = 'flash_day'", (), "{}") or "{}")
            if fd.get("day") == day:
                flash = round(_f(fd.get("n")) * FLASH_USD, 4)
        except ValueError:
            pass
        parts = {"timeline": kv(f"twtl:{day}"), "skener": _f(_one(scon, "SELECT value FROM kv WHERE key = ?", (f"xusd:{day}",))),
                 "discover": kv(f"twdisc:{day}"), "trending": kv(f"twtrend:{day}"), "obrisane": flash}
        parts = {k: round(v, 4) for k, v in parts.items()}
        parts["ostalo"] = round(max(0.0, total - sum(parts.values())), 4)
        return {"usd": round(total, 4), "dijelovi": parts}
    finally:
        for c in (kcon, scon):
            if c is not None:
                c.close()


def _account(ucon, service, now):
    """(used now, limit, reading ts, used a day before or None) from usage.db account readings."""
    last = _all(ucon, "SELECT ts, used, lim FROM account WHERE service = ? AND ts <= ? ORDER BY ts DESC LIMIT 1",
                (service, int(now)))
    if not last:
        return None
    ts, used, lim = last[0]
    prev = _all(ucon, "SELECT used FROM account WHERE service = ? AND ts <= ? ORDER BY ts DESC LIMIT 1",
                (service, int(ts) - 86400 + 1800))
    return {"used": used, "lim": lim, "ts": ts, "dan": (round(used - prev[0][0], 4) if prev and used >= prev[0][0] else None)}


def apify(now, paths):
    day0 = int(now) // 86400 * 86400
    hcon, ucon = _ro(paths["hype"]), _ro(paths["usage"])
    try:
        rows = _all(hcon, "SELECT source, SUM(cost_usd) FROM apify_runs WHERE ts >= ? GROUP BY source", (day0,))
        by = {s: round(_f(v), 4) for s, v in rows if s}
        return {"usd_bot": round(sum(by.values()), 4), "po_izvoru": by, "racun": _account(ucon, "apify", now)}
    finally:
        for c in (hcon, ucon):
            if c is not None:
                c.close()


def pumpportal(now, paths):
    hcon = _ro(paths["hype"])
    try:
        try:
            st = json.loads(_one(hcon, "SELECT value FROM live_state WHERE key = 'trades_day'", (), "{}") or "{}")
        except ValueError:
            st = {}
        n = int(st.get("base") or 0) if st.get("day") == _day(now) else 0
        return {"tradeova": n, "sol": round(n / 10000 * PP_SOL_PER_10K, 4)}
    finally:
        if hcon is not None:
            hcon.close()


def helius(now, paths):
    day0 = int(now) // 86400 * 86400
    ucon = _ro(paths["usage"])
    try:
        rows = _all(ucon, "SELECT script, SUM(amount) FROM usage WHERE service = 'helius' AND hour >= ? GROUP BY script",
                    (day0,))
        by = {s: int(_f(v)) for s, v in rows if s}
        return {"krediti_bot": sum(by.values()), "po_poslu": by, "racun": _account(ucon, "helius", now)}
    finally:
        if ucon is not None:
            ucon.close()


def ai(now, paths):
    day0 = int(now) // 86400 * 86400
    ucon, acon = _ro(paths["usage"]), _ro(paths["ai"])
    try:
        rows = _all(ucon, "SELECT method, SUM(amount) FROM usage WHERE service = 'anthropic' AND hour >= ? GROUP BY method",
                    (day0,))
        by = {m: round(_f(v), 4) for m, v in rows if m}
        posts = int(_f(_one(acon, "SELECT COALESCE(SUM(n), 0) FROM batches WHERE created >= ?", (day0,), 0)))
        return {"usd": round(sum(by.values()), 4), "po_poslu": by, "objava": posts}
    finally:
        for c in (ucon, acon):
            if c is not None:
                c.close()


def collect(now=None, paths=None):
    """Today's (UTC) numbers per source as a dict (JSON-safe)."""
    now = int(now or time.time())
    paths = paths or _paths()
    out = {"day": _day(now), "ts": now}
    for name, fn in (("coingecko", lambda: coingecko(now)), ("twitterapi", lambda: twitterapi(now, paths)),
                     ("apify", lambda: apify(now, paths)), ("pumpportal", lambda: pumpportal(now, paths)),
                     ("helius", lambda: helius(now, paths)), ("ai", lambda: ai(now, paths))):
        try:
            out[name] = fn()
        except Exception as e:  # noqa: BLE001 - one source costs only its part of the line
            out[name] = {"greska": f"{type(e).__name__}: {e}"[:120]}
    return out


def _n(x):
    return f"{int(x or 0):,}".replace(",", ".")


def _usd(x):
    return f"{_f(x):.2f}".replace(".", ",")


def _top(d, k=6, fmt=_n):
    items = sorted(((a, b) for a, b in (d or {}).items() if b), key=lambda kv: -_f(kv[1]))[:k]
    return ", ".join(f"{a} {fmt(b)}" for a, b in items) or "-"


def line(d):
    """One log line of collect()'s dict."""
    cg, tw, ap, pp, he, ai_ = (d.get(k) or {} for k in ("coingecko", "twitterapi", "apify", "pumpportal", "helius", "ai"))
    parts = []
    if cg:
        hours = ", ".join(f"{h}h {n}" for h, n in sorted((cg.get("e429") or {}).items())) or "-"
        parts.append(f"CoinGecko ključem {_n(cg.get('kljuc'))}/{_n(cg.get('strop'))} ({_top(cg.get('po_poslu'))}), "
                     f"besplatno {_n(cg.get('besplatno_ukupno'))} ({_top(cg.get('besplatno'))}), "
                     f"429 ukupno {_n(cg.get('e429_ukupno'))} (po satu UTC: {hours})")
    if tw:
        p = tw.get("dijelovi") or {}
        parts.append(f"X twitterapi ${_usd(tw.get('usd'))} (" + ", ".join(f"{k} {_usd(v)}" for k, v in p.items()) + ")")
    if ap:
        acc = ap.get("racun")
        parts.append(f"Apify ${_usd(ap.get('usd_bot'))} po botu ({_top(ap.get('po_izvoru'), fmt=_usd)})"
                     + (f", račun +${_usd(acc['dan'])} u 24 h" if acc and acc.get("dan") is not None else ""))
    if pp:
        parts.append(f"PumpPortal {_n(pp.get('tradeova'))} tradeova ≈ {pp.get('sol', 0):.3f} SOL")
    if he:
        acc = he.get("racun")
        state = (f"stanje računa {_f(acc['used']) / 1e6:.2f}M/{_f(acc['lim']) / 1e6:.0f}M"
                 + (f" (+{_f(acc['dan']) / 1e3:.0f}k u 24 h)" if acc.get("dan") is not None else "")
                 + time.strftime(", očitano %H:%M UTC", time.gmtime(acc["ts"]))) if acc else "stanje računa: /usage ručno"
        parts.append(f"Helius bot {_n(he.get('krediti_bot'))} kr. ({_top(he.get('po_poslu'))}), {state}")
    if ai_:
        parts.append(f"AI oznake {_n(ai_.get('objava'))} objava, ${_usd(ai_.get('usd'))} ({_top(ai_.get('po_poslu'), fmt=_usd)})")
    errs = [f"{k}: {v['greska']}" for k, v in d.items() if isinstance(v, dict) and v.get("greska")]
    return f"trošak po izvoru {d.get('day')} (UTC dan): " + " | ".join(parts) + (f" | greške: {'; '.join(errs)}" if errs else "")


def connect(path=None):
    from usage import meter
    con = sqlite3.connect(path or meter.DB, timeout=30)
    con.execute(SCHEMA)
    return con


def save(d, path=None):
    con = connect(path)
    try:
        con.execute("INSERT OR REPLACE INTO daily_cost VALUES (?,?,?)", (d["day"], d["ts"], json.dumps(d, ensure_ascii=False)))
        con.commit()
    finally:
        con.close()


def days(n=7, now=None, path=None):
    """The last n saved days (newest first) as dicts."""
    now = int(now or time.time())
    con = _ro(path or _paths()["usage"])
    if con is None:
        return []
    try:
        first = _day(now - (n - 1) * 86400)
        rows = _all(con, "SELECT data FROM daily_cost WHERE day >= ? ORDER BY day DESC", (first,))
    finally:
        con.close()
    out = []
    for (data,) in rows:
        try:
            out.append(json.loads(data))
        except ValueError:
            pass
    return out


def week(now=None, path=None, n=7):
    """7-day sums per source (the weekly report): {days, coingecko_kljuc, coingecko_besplatno, e429, x_usd, x_dijelovi,
    apify_usd_bot, apify_racun_usd, pumpportal_tradeova, pumpportal_sol, helius_bot, helius_racun, ai_usd, ai_objava}."""
    rows = days(n, now, path)
    s = {"dana": len(rows), "od": rows[-1]["day"] if rows else None, "do": rows[0]["day"] if rows else None,
         "coingecko_kljuc": 0, "coingecko_besplatno": 0, "e429": 0, "x_usd": 0.0, "x_dijelovi": {}, "apify_usd_bot": 0.0,
         "apify_racun_usd": 0.0, "pumpportal_tradeova": 0, "pumpportal_sol": 0.0, "helius_bot": 0, "helius_racun": 0.0,
         "ai_usd": 0.0, "ai_objava": 0}
    for d in rows:
        cg, tw, ap, pp, he, ai_ = (d.get(k) or {} for k in ("coingecko", "twitterapi", "apify", "pumpportal", "helius", "ai"))
        s["coingecko_kljuc"] += int(cg.get("kljuc") or 0)
        s["coingecko_besplatno"] += int(cg.get("besplatno_ukupno") or 0)
        s["e429"] += int(cg.get("e429_ukupno") or 0)
        s["x_usd"] += _f(tw.get("usd"))
        for k, v in (tw.get("dijelovi") or {}).items():
            s["x_dijelovi"][k] = round(s["x_dijelovi"].get(k, 0.0) + _f(v), 4)
        s["apify_usd_bot"] += _f(ap.get("usd_bot"))
        s["apify_racun_usd"] += _f(((ap.get("racun") or {}).get("dan")))
        s["pumpportal_tradeova"] += int(pp.get("tradeova") or 0)
        s["pumpportal_sol"] += _f(pp.get("sol"))
        s["helius_bot"] += int(he.get("krediti_bot") or 0)
        s["helius_racun"] += _f(((he.get("racun") or {}).get("dan")))
        s["ai_usd"] += _f(ai_.get("usd"))
        s["ai_objava"] += int(ai_.get("objava") or 0)
    for k in ("x_usd", "apify_usd_bot", "apify_racun_usd", "pumpportal_sol", "ai_usd"):
        s[k] = round(s[k], 4)
    return s


def week_md(s):
    """Markdown lines of week() for the EV report ("trošak po izvoru (7 dana)")."""
    if not s.get("dana"):
        return ["## Trošak po izvoru (7 dana)", "", "- još nema spremljenih dana (usage.db daily_cost, prvi u 23:59 UTC)"]
    parts = ", ".join(f"{k} {_usd(v)}" for k, v in (s.get("x_dijelovi") or {}).items())
    return ["## Trošak po izvoru (7 dana)", "", f"Dana: {s['dana']} ({s['od']} do {s['do']}), brojevi bota (nije račun dobavljača).", "",
            f"- CoinGecko: ključem {_n(s['coingecko_kljuc'])} poziva, besplatno {_n(s['coingecko_besplatno'])}, "
            f"HTTP 429 {_n(s['e429'])}",
            f"- X (twitterapi.io): ${_usd(s['x_usd'])} ({parts or '-'})",
            f"- Apify: ${_usd(s['apify_usd_bot'])} po botu, račun ${_usd(s['apify_racun_usd'])}",
            f"- PumpPortal: {_n(s['pumpportal_tradeova'])} tradeova ≈ {s['pumpportal_sol']:.3f} SOL",
            f"- Helius: {_n(s['helius_bot'])} kredita po botu, račun +{s['helius_racun'] / 1e6:.2f}M",
            f"- AI oznake: {_n(s['ai_objava'])} objava, ${_usd(s['ai_usd'])}"]


def run(now=None, log=print, paths=None, path=None):
    """Collect, save and log today's line (run_usage.py dnevno). Returns the dict."""
    d = collect(now, paths)
    try:
        save(d, path)
    except sqlite3.Error as e:
        log(f"trošak po izvoru: nije spremljeno u usage.db ({e})")
    log(line(d), flush=True)
    return d
