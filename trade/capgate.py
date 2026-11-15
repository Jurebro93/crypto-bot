"""Mikrokap blokada: one gate for every AUTOMATIC entry (15.11.2026., vlasnik: "Od sada nema smisla, čak ni u demu,
tradati ove mikrokapove tražeći 10 %. Oni mogu biti moonshot samo ako vidimo ogromnu bazu na društvenim mrežama i
puno influencera koji ga zovu, onda ulazimo. Inače sada tradamo samo mid-capove: 5M-150M $ market capa.").

    allow_entry(token, mcap_usd, source, account, now, ctx) -> (ok, reason)
        (True, None)              no gate: the switch is off, the owner's manual buy (ctx manual), or MC >= MIN_MC
        (True, "moonshot: ...")   the moonshot exception (DEMO accounts only): the caller tags the entry's source
                                  (tag) and halves its stake (size_usd / size_sol); is_moon(reason) tells it apart
        (False, "MC ispod 5M (mikrokap): ...")   refused; the caller skips the entry with this reason

    check(...) does the same and returns (why_not, source, size) for the usual call site.

Rule (MIN_MC = trade/config.json "mikrokap" min_mc, default 5_000_000): an automatic entry needs MC >= MIN_MC. MC
unknown = refused (an automatic entry never buys blind). The owner's manual buy is never gated (CLAUDE.md: his manual
buy overrides with a warning); measurement / shadow pipelines do not call this (they never trade).

MOONSHOT EXCEPTION (owner 15.11.; the coordinator's rules after the OpenAI critic: demo only, LOCKED rules defined up
front, no discretionary override, its own measured strategy). An entry under MIN_MC passes ONLY when ALL hold:
  0. the account is a demo account (never LEAGUE_USER / real money: no switch turns that on), the caller allows the
     exception (ctx moonshot, default True; price-driven strategies pass False), and the flag mikrokap_moonshot is
     "paper" (its default; "off" = no exception at all; "live" is refused: trade/settings.NEVER_LIVE)
  1. MC >= FLOOR_MC ($30k, the hard floor) and bonded (ctx bonded is not False: every caller checks the curve first)
  2. pool liquidity >= MOON_MIN_LIQ ($50k; unknown = no)
  3. top-10 holders share <= MOON_TOP10_MAX (45 %, fast/checks top10_max) from the data the system already has
     (topcheck.db RugCheck summary, else rug.db's newest report; topcheck/holders.pumpfun_shape); unknown = no
  4. >= MOON_MIN_CALLERS (4) DISTINCT callers within MOON_WINDOW_H (6 h): X influencers (kol.db calls kind 'call') and
     Telegram channels (tg.db posts that are not forwards, kol.db 'tg:<channel>' calls); the newest corr.db snapshot's
     KOL clusters and wallet owner groups count ONCE (konsenzus/research.load_groups, union-find); alert bots
     (kol.db kols.bot), paid shillers (kol/shillers.json) and the shill networks of kol/preshill (early.db
     preshill_networks shill=1) do not count at all; "w:" pseudo-calls (wallet buys) are not callers
  5. X momentum high: scan/xmom x_momentum_score >= MOON_MIN_XMOM (1.0 = organic authors at twice the previous hour's
     rate) on a row at most MOON_XMOM_FRESH_MIN (90 min) old (xfeat.db x_momentum; Grok's hand-checked
     submit_x_features row of the last 2 h takes precedence, like xmom.latest)
  6. organic authors growing: that row's organic authors in the last 15 min >= MOON_MIN_ORGANIC (3) and above the
     previous hour's per-15-min rate (a score of 1 alone could be one author against none)
Only data already collected is read: no new paid call (CLAUDE.md: learn more for less). config.json may only make
these numbers STRICTER (LOCKED is the floor of each); the moonshot stake is half the strategy's own demo stake and at
most MOON_MAX_SOL (0.05 SOL). Its trades carry " · moonshot" in the source and are measured on their own (moon_stats:
n, net EV per trade after the modelled cost: 1 % a side + the pool impact of league/store).

Logging: start_line() once at a process start ("mikrokap blokada: automatski ulazi samo MC ≥ 5M $ (iznimka moonshot:
...)"); every refused / moonshot entry once per token and Zagreb day (trade.db mikrokap_log, so several processes
agree; the line is printed by the process that wrote the row); day_tick() prints the closed day's counter once
("mikrokap 15.11.: odbijeno N ulaza ispod 5M, moonshot iznimki M").

Switches (trade/settings, both shown under Prekidači): mikrokap_blokada (owner switch, "uživo" = on; switched on once by
the owner's order 15.11., ui/assistnotes.OWNER_FLAG_ORDERS; any other mode = the old behaviour, MC >= 30k only) and
mikrokap_moonshot (paper = the exception on the demo accounts, default; off = no exception).
"""
import datetime as _dt
import json
import os
import sqlite3
import time
from zoneinfo import ZoneInfo

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG = os.path.join(HERE, "config.json")
FLAG = "mikrokap_blokada"
MOON_FLAG = "mikrokap_moonshot"
MOON = "moonshot"
MOON_TAG = " · moonshot"
TZ = "Europe/Zagreb"
# the locked rules: config.json "mikrokap" may only make the moonshot numbers stricter (min_mc may move either way:
# the owner's band starts at 5M, he may change it)
LOCKED = {"min_mc": 5_000_000, "floor_mc": 30_000, "moon_min_callers": 4, "moon_window_h": 6.0, "moon_min_xmom": 1.0,
          "moon_min_organic": 3, "moon_min_liq": 50_000, "moon_top10_max": 45.0, "moon_size_share": 0.5,
          "moon_max_sol": 0.05, "moon_xmom_fresh_min": 90}
_HIGHER = ("floor_mc", "moon_min_callers", "moon_min_xmom", "moon_min_organic", "moon_min_liq")   # stricter = higher
_LOWER = ("moon_window_h", "moon_top10_max", "moon_size_share", "moon_max_sol", "moon_xmom_fresh_min")
MOON_CACHE_S = 60
GROUPS_TTL_S = 600
KEEP_DAYS = 30
SCHEMA = """CREATE TABLE IF NOT EXISTS mikrokap_log (
    day TEXT, token TEXT, kind TEXT, account TEXT, source TEXT, mcap REAL, why TEXT, ts INTEGER,
    PRIMARY KEY (day, token, kind))"""
_CFG = {"mt": None, "c": dict(LOCKED)}
_SAID = {}        # (day, token, kind) -> True: written / printed by this process
_MOON = {}        # token -> (monotonic ts, (ok, text, facts))
_GROUPS = {"ts": 0.0, "g": None}
_DAY = {"day": None}


# ---------- config and switches -------------------------------------------------------------------------------------

def cfg(path=None):
    """LOCKED + trade/config.json "mikrokap" (the moonshot numbers only stricter), cached by the file's mtime."""
    path = path or CONFIG
    try:
        mt = os.path.getmtime(path)
    except OSError:
        return dict(LOCKED)
    if _CFG["mt"] == (path, mt):
        return dict(_CFG["c"])
    c = dict(LOCKED)
    try:
        with open(path) as f:
            own = (json.load(f) or {}).get("mikrokap") or {}
    except (OSError, ValueError):
        own = {}
    for k, v in (own.items() if isinstance(own, dict) else ()):
        if k.startswith("_") or k not in LOCKED or not isinstance(v, (int, float)) or isinstance(v, bool):
            continue
        if k == "min_mc":
            c[k] = max(float(v), LOCKED["floor_mc"])
        elif k in _HIGHER:
            c[k] = max(v, LOCKED[k])
        elif k in _LOWER:
            c[k] = min(v, LOCKED[k])
    _CFG.update(mt=(path, mt), c=c)
    return dict(c)


def on(con=None):
    """True while the owner switch mikrokap_blokada is on ("live"). Never raises: unreadable = the old behaviour."""
    try:
        from trade import settings
        return settings.flag(FLAG, con) == "live"
    except Exception:  # noqa: BLE001
        return False


def moon_on(con=None):
    """True while the moonshot exception may be used on demo accounts (flag mikrokap_moonshot "paper")."""
    try:
        from trade import settings
        return settings.flag(MOON_FLAG, con) == "paper"
    except Exception:  # noqa: BLE001
        return False


def _real(account, ctx):
    if ctx.get("real") is not None:
        return bool(ctx["real"])
    try:
        from trade import settings
        return account == settings.LEAGUE_USER
    except Exception:  # noqa: BLE001
        return False


# ---------- words ---------------------------------------------------------------------------------------------------

def money(x):
    """5_000_000 -> "5M", 1_234_567 -> "1,2M", 850_000 -> "850k", 30_000 -> "30k"."""
    x = float(x or 0)
    if x >= 1e6:
        s = f"{x / 1e6:.1f}".rstrip("0").rstrip(".")
        return s.replace(".", ",") + "M"
    if x >= 1e3:
        return f"{x / 1e3:.0f}k"
    return f"{x:.0f}"


def rule_text(c=None):
    """The rule in one line (the start log line, the page)."""
    c = c or cfg()
    return (f"automatski ulazi samo MC ≥ {money(c['min_mc'])} $ (iznimka moonshot, samo demo: MC ≥ "
            f"{money(c['floor_mc'])} bondan, likvidnost ≥ {money(c['moon_min_liq'])} $, top10 holdera ≤ "
            f"{c['moon_top10_max']:g} %, {c['moon_min_callers']}+ neovisnih influencera / TG kanala u "
            f"{c['moon_window_h']:g} h (klasteri i grupe vlasnika jednom, botovi i shill mreže ne broje), X momentum ≥ "
            f"{c['moon_min_xmom']:g} i {c['moon_min_organic']}+ organskih autora u rastu; pola uloga, najviše "
            f"{c['moon_max_sol']:g} SOL)").replace(".", ",")


def start_line(log=print):
    """The one line at a process start."""
    st = "uključena" if on() else "ISKLJUČENA (stari način: samo MC ≥ 30k)"
    text = f"mikrokap blokada: {rule_text()}" if on() else f"mikrokap blokada {st}"
    if on() and not moon_on():
        text += "; moonshot iznimka isključena (mikrokap_moonshot)"
    if log:
        log(text, flush=True) if log is print else log(text)
    return text


def is_moon(reason):
    return bool(reason) and str(reason).startswith(MOON)


def tag(source, reason, n=200):
    """The entry's source with the moonshot tag (measured on its own); unchanged for a normal entry."""
    s = str(source or "")
    if not is_moon(reason) or MOON_TAG in s:
        return s
    return s[:max(0, n - len(MOON_TAG))] + MOON_TAG


def size_usd(usd, reason, sol=None, c=None):
    """A moonshot's stake in USD: half the strategy's own, at most moon_max_sol SOL (when the SOL price is known)."""
    if not is_moon(reason):
        return usd
    c = c or cfg()
    out = float(usd or 0) * c["moon_size_share"]
    if sol:
        out = min(out, c["moon_max_sol"] * float(sol))
    return out


def size_sol(amount, reason, c=None):
    """A moonshot's stake in SOL: half the strategy's own, at most moon_max_sol."""
    if not is_moon(reason):
        return amount
    c = c or cfg()
    return min(float(amount or 0) * c["moon_size_share"], c["moon_max_sol"])


# ---------- the log (trade.db mikrokap_log) -------------------------------------------------------------------------

def day_of(now):
    return _dt.datetime.fromtimestamp(int(now), ZoneInfo(TZ)).strftime("%Y-%m-%d")


def _db():
    from trade import settings
    return settings.DB


def _record(now, token, kind, account, source, mcap, why, symbol=None, log=print):
    """Once per token, kind (odbijen / moonshot) and Zagreb day: the row, then one log line. Never raises."""
    day = day_of(now)
    k = (day, token, kind)
    if k in _SAID:
        return False
    _SAID[k] = True
    if len(_SAID) > 20000:
        for kk in [kk for kk in _SAID if kk[0] != day]:
            _SAID.pop(kk, None)
    fresh = True
    try:
        con = sqlite3.connect(_db(), timeout=10)
        try:
            con.execute(SCHEMA)
            cur = con.execute("INSERT OR IGNORE INTO mikrokap_log VALUES (?,?,?,?,?,?,?,?)",
                              (day, token, kind, account, str(source or "")[:200], mcap, str(why or "")[:300], int(now)))
            con.commit()
            fresh = cur.rowcount == 1
        finally:
            con.close()
    except sqlite3.Error:
        pass   # the line is still printed once by this process
    if fresh and log:
        sym = symbol or (token or "")[:6]
        if kind == MOON:
            text = f"mikrokap: MOONSHOT iznimka {sym} ({str(source or '')[:60]}, {account}): {why}"
        else:
            text = f"mikrokap: odbijen ulaz {sym} ({str(source or '')[:60]}, {account}): {why}"
        log(text, flush=True) if log is print else log(text)
    return fresh


def counts(now=None, day=None, path=None):
    """{"day", "refused": tokens refused that Zagreb day, "moon": moonshot exceptions} from trade.db."""
    day = day or day_of(now or time.time())
    out = {"day": day, "refused": 0, "moon": 0}
    p = path or _db()
    if not os.path.exists(p):
        return out
    try:
        con = sqlite3.connect(f"file:{p}?mode=ro", uri=True, timeout=5)
        try:
            for kind, n in con.execute("SELECT kind, COUNT(*) FROM mikrokap_log WHERE day=? GROUP BY kind", (day,)):
                out["moon" if kind == MOON else "refused"] += n
        finally:
            con.close()
    except sqlite3.Error:
        pass
    return out


def day_line(now=None, day=None, path=None):
    c = counts(now, day, path)
    d = _dt.date.fromisoformat(c["day"])
    return (f"mikrokap {d.day}.{d.month}.: odbijeno {c['refused']} ulaza ispod {money(cfg()['min_mc'])}, "
            f"moonshot iznimki {c['moon']}")


def day_tick(now=None, log=print):
    """At the first call of a new Zagreb day: the closed day's counter line (and old rows pruned). The first call of a
    process only remembers the day. Returns the line or None."""
    now = now or time.time()
    day = day_of(now)
    prev = _DAY["day"]
    _DAY["day"] = day
    if prev is None or prev == day:
        return None
    text = day_line(day=prev)
    if log:
        log(text, flush=True) if log is print else log(text)
    try:
        con = sqlite3.connect(_db(), timeout=10)
        try:
            con.execute(SCHEMA)
            cut = day_of(now - KEEP_DAYS * 86400)
            con.execute("DELETE FROM mikrokap_log WHERE day < ?", (cut,))
            con.commit()
        finally:
            con.close()
    except sqlite3.Error:
        pass
    return text


# ---------- moonshot data (read-only, no paid call) -----------------------------------------------------------------

def _ro(path):
    if not path or not os.path.exists(path) or not os.path.getsize(path):
        return None
    try:
        return sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5)
    except sqlite3.Error:
        return None


def _q(con, sql, args=()):
    if con is None:
        return []
    try:
        return con.execute(sql, args).fetchall()
    except sqlite3.Error:
        return []


def _norm(h):
    from konsenzus.research import norm
    return norm(h)


def paths(over=None):
    from league import copy as lcopy
    p = dict(lcopy._paths())
    try:
        from kol import groupdisc as gd
        p["early"] = gd.db_path()
    except Exception:  # noqa: BLE001
        p["early"] = None
    try:
        from ui import xfeat
        p["xfeat"] = xfeat.db_path()
    except Exception:  # noqa: BLE001
        p["xfeat"] = None
    try:
        from topcheck import store as tstore, holders
        p["topcheck"], p["rug"] = tstore.DB, holders.RUG_DB
    except Exception:  # noqa: BLE001
        p["topcheck"] = p["rug"] = None
    p.update(over or {})
    return p


def groups():
    """konsenzus/research.load_groups' union-find of the newest corr.db snapshot (KOL clusters + owner groups),
    cached GROUPS_TTL_S; None when unreadable (every caller then counts alone)."""
    if _GROUPS["g"] is not None and time.monotonic() - _GROUPS["ts"] < GROUPS_TTL_S:
        return _GROUPS["g"]
    try:
        from konsenzus import research
        g, _info = research.load_groups()
    except Exception:  # noqa: BLE001
        g = None
    _GROUPS.update(ts=time.monotonic(), g=g)
    return g


_EXCL = {"ts": 0.0, "key": None, "v": None}


def excluded(p):
    """Lower-case handles that never count as a moonshot caller: alert bots, paid shillers, shill networks (cached
    GROUPS_TTL_S per set of paths)."""
    key = (p.get("kol"), p.get("early"))
    if _EXCL["key"] == key and _EXCL["v"] is not None and time.monotonic() - _EXCL["ts"] < GROUPS_TTL_S:
        return _EXCL["v"]
    out = _excluded(p)
    _EXCL.update(ts=time.monotonic(), key=key, v=out)
    return out


def _excluded(p):
    out = set()
    kc = _ro(p.get("kol"))
    for (h,) in _q(kc, "SELECT handle FROM kols WHERE bot = 1"):
        if h:
            out.add(_norm(h))
    if kc is not None:
        kc.close()
    try:
        from kol import shillers
        out |= {_norm(h) for h in shillers.handles()}
    except Exception:  # noqa: BLE001
        pass
    ec = _ro(p.get("early"))
    for (mem,) in _q(ec, "SELECT members FROM preshill_networks WHERE shill = 1"):
        try:
            out |= {_norm(h) for h in json.loads(mem or "[]") if isinstance(h, str)}
        except ValueError:
            pass
    if ec is not None:
        ec.close()
    return out


def callers(token, now, window_s, p):
    """[(ts, source)] of every X / Telegram call of the token in the window (first per source), newest data only."""
    since = int(now - window_s)
    first = {}
    kc = _ro(p.get("kol"))
    for h, ts in _q(kc, "SELECT handle, ts FROM calls WHERE token=? AND kind='call' AND ts >= ? AND ts <= ?",
                    (token, since, int(now))):
        if h and not str(h).startswith("w:") and ts:
            s = _norm(h)
            first[s] = min(first.get(s, ts), ts)
    if kc is not None:
        kc.close()
    tc = _ro(p.get("tg"))
    for ch, ts, fwd in _q(tc, "SELECT channel, ts, fwd_from FROM posts WHERE ts >= ? AND ts <= ? AND cas LIKE ?",
                          (since, int(now), f"%{token}%")):
        if ch and ts and not fwd:
            s = _norm("tg:" + str(ch))
            first[s] = min(first.get(s, ts), ts)
    if tc is not None:
        tc.close()
    return sorted((ts, s) for s, ts in first.items())


def distinct(calls, bad, grp=None):
    """(independent group ids, sources left out as bots / shillers) of the callers: a group counts once (pure)."""
    seen, gone = {}, []
    for ts, s in calls:
        if s in bad:
            gone.append(s)
            continue
        g = grp.of(s) if grp is not None else s
        seen.setdefault(g, s)
    return list(seen.values()), gone


def xmom_row(token, now, p, fresh_s):
    """{score, organic15, organic_prev60, source, ts} of the token's newest X momentum (Grok's row of the last 2 h
    first, then the scanner's x_momentum row at most fresh_s old); None when none."""
    try:
        from scan import xmom
        g = xmom.grok_row(token, now, p.get("xfeat"))
    except Exception:  # noqa: BLE001
        g = None
    if g and g.get("x_momentum_score") is not None and g.get("authors15") is not None:
        a15 = int(g["authors15"])
        # Grok's hand-checked authors (known callers named apart): the previous rate from the score itself
        prev = max(0.0, ((a15 + 1) / (2 ** float(g["x_momentum_score"])) - 1) * 4)
        return {"score": float(g["x_momentum_score"]), "organic15": a15, "organic_prev60": round(prev, 2),
                "source": "grok", "ts": g.get("ts")}
    xc = _ro(p.get("xfeat"))
    rows = _q(xc, "SELECT ts, score, organic15, organic_prev60 FROM x_momentum WHERE token=? AND ts >= ? "
                  "ORDER BY ts DESC LIMIT 1", (token, int(now - fresh_s)))
    if xc is not None:
        xc.close()
    if not rows or rows[0][1] is None:
        return None
    ts, sc, o15, oprev = rows[0]
    return {"score": float(sc), "organic15": int(o15 or 0), "organic_prev60": int(oprev or 0), "source": "scan",
            "ts": ts}


def top10(token, p):
    """The top-10 holders share in percent (topcheck RugCheck summary, else rug.db), None when unknown."""
    rc = {}
    tc = _ro(p.get("topcheck"))
    r = _q(tc, "SELECT rc_json FROM top_check WHERE token=?", (token,))
    if tc is not None:
        tc.close()
    if r and r[0][0]:
        try:
            rc = json.loads(r[0][0]) or {}
        except ValueError:
            rc = {}
    try:
        from topcheck import holders
        rug = holders._rug_rows([token], p.get("rug"))
        d = holders.pumpfun_shape([token], tc={token: {"rc": rc}} if rc else {}, rug=rug).get(token) or {}
        v = d.get("top10HoldersPercent")
        return float(v) if v is not None else None
    except Exception:  # noqa: BLE001
        return None


def social(token, now, c=None, p=None, grp=None, bad=None):
    """The moonshot's data part (cached MOON_CACHE_S per token): (ok, text, facts)."""
    c = c or cfg()
    hit = _MOON.get(token)
    if p is None and hit and time.monotonic() - hit[0] < MOON_CACHE_S:
        return hit[1]
    pp = p or paths()
    facts = {}
    res = None
    xm = xmom_row(token, now, pp, c["moon_xmom_fresh_min"] * 60)
    facts["xmom"] = xm
    if xm is None:
        res = (False, "nema svježeg X momentuma (scan/xmom)", facts)
    elif xm["score"] < c["moon_min_xmom"]:
        res = (False, f"X momentum {xm['score']:.2f} < {c['moon_min_xmom']:g}".replace(".", ","), facts)
    elif xm["organic15"] < c["moon_min_organic"] or xm["organic15"] <= xm["organic_prev60"] / 4:
        res = (False, f"organskih autora {xm['organic15']} u 15 min (treba {c['moon_min_organic']}+ i rast)", facts)
    if res is None:
        calls = callers(token, now, c["moon_window_h"] * 3600, pp)
        ind, gone = distinct(calls, excluded(pp) if bad is None else bad, groups() if grp is None else grp)
        facts.update(callers=ind, left_out=gone)
        if len(ind) < c["moon_min_callers"]:
            res = (False, f"{len(ind)} neovisnih callera u {c['moon_window_h']:g} h (treba {c['moon_min_callers']}+)"
                   + (f", {len(gone)} botova / shillera ne broji" if gone else ""), facts)
    if res is None:
        t10 = top10(token, pp)
        facts["top10"] = t10
        if t10 is None:
            res = (False, "top10 holdera nepoznat", facts)
        elif t10 > c["moon_top10_max"]:
            res = (False, f"top10 holdera {t10:.0f} % > {c['moon_top10_max']:g} %", facts)
    if res is None:
        res = (True, (f"{len(facts['callers'])} neovisnih callera u {c['moon_window_h']:g} h, X momentum "
                      f"{xm['score']:.2f}, {xm['organic15']} organskih autora u 15 min, top10 {facts['top10']:.0f} %"
                      ).replace(".", ","), facts)
    if p is None:
        _MOON[token] = (time.monotonic(), res)
        if len(_MOON) > 5000:
            for k in [k for k, v in _MOON.items() if time.monotonic() - v[0] > MOON_CACHE_S]:
                _MOON.pop(k, None)
    return res


def moonshot(token, mcap, account, now, ctx=None, c=None):
    """(ok, text): the moonshot exception for this entry (module text). Pure on ctx "social" (tests / a caller that
    has the facts); else reads the data (social)."""
    ctx = ctx or {}
    c = c or cfg()
    if _real(account, ctx):
        return False, "pravi račun: moonshot iznimka samo u demu"
    if ctx.get("moonshot") is False:
        return False, "strategija bez moonshot iznimke"
    if not moon_on(ctx.get("con")):
        return False, "moonshot iznimka isključena (mikrokap_moonshot)"
    if mcap is None or mcap < c["floor_mc"]:
        return False, f"MC ispod {money(c['floor_mc'])}"
    if ctx.get("bonded") is False:
        return False, "nije bondan"
    liq = ctx.get("liq")
    if liq is None or liq < c["moon_min_liq"]:
        return False, f"likvidnost ${liq or 0:,.0f} < ${c['moon_min_liq']:,.0f}"
    if "social" in ctx:
        s = ctx["social"]
        return bool(s[0]), s[1]
    ok, text, _facts = social(token, now, c, ctx.get("paths"), ctx.get("groups"), ctx.get("excluded"))
    return ok, text


# ---------- the gate ------------------------------------------------------------------------------------------------

def allow_entry(token, mcap_usd, source, account, now=None, ctx=None):
    """(ok, reason) of one automatic entry (module text). ctx: manual (the owner's own buy: never gated), liq, symbol,
    bonded, real (default: account == LEAGUE_USER), moonshot (False = this strategy takes no exception), con (trade.db
    for the switches), paths / groups / excluded (the moonshot's data), social ((ok, text): the moonshot facts given),
    log (print; None = silent)."""
    ctx = ctx or {}
    if ctx.get("manual"):
        return True, None
    if not on(ctx.get("con")):
        return True, None
    now = now or time.time()
    c = cfg()
    if mcap_usd is not None and mcap_usd >= c["min_mc"]:
        return True, None
    log = ctx.get("log", print)
    ok, text = moonshot(token, mcap_usd, account, now, ctx, c)
    if ok:
        reason = f"{MOON}: {text}"
        _record(now, token, MOON, account, source, mcap_usd, reason, ctx.get("symbol"), log)
        return True, reason
    head = f"MC ispod {money(c['min_mc'])} (mikrokap)"
    mc = f"MC ${mcap_usd:,.0f}" if mcap_usd is not None else "MC nepoznat"
    reason = f"{head}: {mc}; moonshot ne: {text}"
    _record(now, token, "odbijen", account, source, mcap_usd, reason, ctx.get("symbol"), log)
    return False, reason


def check(token, mcap_usd, source, account, size, now=None, unit="usd", sol=None, **ctx):
    """The usual call site: (why_not or None, source (tagged for a moonshot), size (halved for a moonshot)).
    unit "usd" (sol = the SOL price, caps the moonshot stake) or "sol"."""
    ok, reason = allow_entry(token, mcap_usd, source, account, now, ctx)
    if not ok:
        return reason, source, size
    if is_moon(reason):
        size = size_usd(size, reason, sol) if unit == "usd" else size_sol(size, reason)
        source = tag(source, reason)
    return None, source, size


def refusal(token, mcap_usd, source, account, now=None, **ctx):
    """Only the refusal (for a strategy that takes no moonshot exception): the reason or None."""
    ok, reason = allow_entry(token, mcap_usd, source, account, now, dict(ctx, moonshot=ctx.get("moonshot", False)))
    return None if ok else reason


# ---------- measurement ---------------------------------------------------------------------------------------------

def moon_stats(lcon=None):
    """The moonshot entries as their own strategy (league.db trades with the tag; a partial sale's rows are one entry:
    user, token, opened_ts): {"n", "open", "closed", "pnl_usd", "ev_pct": mean net return per closed entry (after
    league/store's 1 % a side + the pool impact), "hit"}."""
    own = lcon is None
    out = {"n": 0, "open": 0, "closed": 0, "pnl_usd": 0.0, "ev_pct": None, "hit": None}
    if own:
        try:
            from league import store as lstore
            lcon = _ro(lstore.DB)
        except Exception:  # noqa: BLE001
            lcon = None
    if lcon is None:
        return out
    try:
        rows = _q(lcon, "SELECT user, token, opened_ts, status, size_usd, pnl_usd FROM trades WHERE source LIKE ?",
                  (f"%{MOON_TAG}%",))
    finally:
        if own:
            lcon.close()
    ent = {}
    for user, tok, ts, st, size, pnl in rows:
        e = ent.setdefault((user, tok, ts), {"open": False, "size": 0.0, "pnl": 0.0})
        e["open"] = e["open"] or st == "open"
        if st == "closed":
            e["size"] += size or 0
            e["pnl"] += pnl or 0
    rets = []
    for e in ent.values():
        out["n"] += 1
        if e["open"]:
            out["open"] += 1
            continue
        out["closed"] += 1
        out["pnl_usd"] += e["pnl"]
        if e["size"]:
            rets.append(e["pnl"] / e["size"])
    if rets:
        out["ev_pct"] = round(100 * sum(rets) / len(rets), 2)
        out["hit"] = round(sum(1 for r in rets if r > 0) / len(rets), 3)
    out["pnl_usd"] = round(out["pnl_usd"], 2)
    return out


def summary_line(now=None):
    """One line for the page: today's counters and the moonshot strategy so far."""
    c = counts(now)
    m = moon_stats()
    ev = (f", EV {m['ev_pct']:+.1f} % neto po tradeu".replace(".", ",") if m["ev_pct"] is not None else "")
    return (f"danas odbijeno {c['refused']} ulaza ispod {money(cfg()['min_mc'])}, moonshot iznimki {c['moon']}; "
            f"moonshot demo dosad {m['n']} ulaza ({m['open']} otvorenih, {m['closed']} zatvorenih{ev})")
