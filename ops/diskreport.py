"""Disk report (11.11., Jure: "NIŠTA ne briši bez moje potvrde"): it MEASURES, it never deletes or rewrites anything.

    python3 -m ops.diskreport           the report now: one log block "disk izvještaj: ..." (Render log)
    python3 -m ops.diskreport --auto    start.sh, after every hourly upkeep: only when due (below), else ends at once
    python3 -m ops.diskreport --json    the whole report as JSON on stdout

When (--auto): at the first hourly pass after a deploy (marker = RENDER_GIT_COMMIT in the state file) and once a day
from 06:30 Zagreb; never inside the heavy-job night window (ops/heavy.NIGHT, 01-06 Zagreb). start.sh runs it at low
priority (nice) as its own process, so the CPU guard may pause it (ops/cpuguard "disk"); the hourly upkeep itself is
protected there, because it holds the write locks of trade.db and league.db.

What it measures:
  disk        used / free / total of the data disk (DATA_DIR), and per directory under DATA_DIR plus the repo's
              output/, research/, logs/ and the HTTP cache (event_calendar/http CACHE_DIR) when they live elsewhere
  databases   per *.db: file size, WAL size, free pages (freelist: handed back by VACUUM) and the unused bytes inside
              pages (dbstat); per table: rows, bytes with its indexes (dbstat; without dbstat a sampled estimate), the
              time column (ts, created_ts, opened_ts, ... detected, seconds / milliseconds / ISO text), rows of the
              last 24 h / 7 d, the oldest row, growth per day (rows of 24 h x bytes per row) and the bytes older
              than 7 / 14 / 30 days
  candidates  per table with a time column that nothing learns from: "rows older than N days" with the MB it would
              free (N never below what its readers need, MIN_DAYS), VACUUM per file, cache folders. Tables the bot
              learns or measures from (outcomes, scores, labels, proofs, money) are KEEP with the reason and are never
              proposed (KEEP below, grounded in who reads them; the readers are found by a grep of the code at run time)
  runway      free MB / growth per day: the net growth from the state file's earlier runs (>= 20 h back) when there
              is one, else the rows' inflow (an upper bound: retention frees pages the inflow does not count)
  alarm       used > ALARM_USED (80 %) or runway < ALARM_RUNWAY_D (3 days): get_hourly_brief health (brief_part)

Read-only by construction: every database is opened with mode=ro and a short busy timeout, every query runs under a
time guard (progress handler) and the whole report under BUDGET_S; a locked or slow table is skipped and named. The
one file it writes is its own state DATA_DIR/.diskreport.json (yesterday's numbers, the deploy marker, the brief's
summary). (A read-only connection to a WAL database that nobody has open leaves an empty -wal/-shm pair behind, as
SQLite does; in production the writers keep those files open anyway.)
"""
import datetime as dt
import json
import os
import re
import shutil
import sqlite3
import sys
import time

from ops import disk

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATE = ".diskreport.json"
BUDGET_S = float(os.environ.get("DISKREPORT_BUDGET_S", "240"))
QUERY_S = float(os.environ.get("DISKREPORT_QUERY_S", "20"))
BUSY_MS = 2000
DAILY_AT = (6, 30)          # Zagreb
TZ = "Europe/Zagreb"
ALARM_USED = 0.80
ALARM_RUNWAY_D = 3.0
TOP = 15
TOP_CAND = 12
DAYS = (7, 14, 30)
SMALL_ROWS = 50_000         # below this a plain COUNT ... WHERE is cheap even without an index
NET_MIN_H = 20              # the net growth needs an earlier run at least this far back
D = 86400
TIME_COLS = ("ts", "created_ts", "opened_ts", "checked_at", "checked_ts", "fetched_ts", "seen_ts", "archived_ts",
             "first_ts", "created_at", "time", "hour", "day", "first_seen", "updated", "updated_ts", "last_ts",
             "last_seen")

# Tables the bot learns or measures from: KEEP, never proposed. Grounded in a grep of their readers (11.11.).
KEEP = {
    "hype.db": {
        "hype_snapshots": "ishodi cijena za učenje (learn/outcomes, hype/evaluate, learn/shadow, run_paper); mrtve "
                          "tokene već čisti ops/prune (mrtvi_tokeni)",
        "token_tier": "klase i razine tokena (learn/outcomes, learn/shadow, exits/paths, paper/rules, league/auto)",
        "tier_events": "događaji razina za sjenu i pravila (learn/shadow, paper/rules)",
        "rug_archive": "oznake rugova: učenje (learn/rugprofile) i blok (rugfilter/archive)",
        "rug_recovered": "tokeni vraćeni iz arhive rugova (rugfilter/archive)",
        "rug_relabel": "oznake rug / dump po pravilu poola (rugfilter/relabel)",
        "rug_watch": "potvrda kolapsa prije arhive (rugfilter/archive)",
        "smart_wallets": "ocjene pametnih walleta (hype/sources, wallets/store)",
        "dokazani": "dokazani novčanici, prvi izvor Autopilota (wallets/dokazani)",
        "learn_runs": "povijest učenja i vraćanja (learn/store, report/collect)",
        "token_status": "stanje para: povratak iz arhive rugova, mrtvi tokeni (rugfilter/archive, ops/prune)",
        "graduates": "bondani tokeni, izvor skenera i range liste (scan/market, rangedca/market)",
    },
    "kol.db": {
        "calls": "pozivi s izmjerenim ishodom: ocjene callera (kol/score i 70+ čitača); čisti ih samo ops/prune "
                 "(w_pozivi, neaktivni_x)",
        "kols": "ocjene callera (kol/score, kol/converge, ui)",
        "snaps": "cijene nakon poziva = ishod za ocjene (kol/snap, kol/score, proposals/outcomes)",
        "flows": "Helius tokovi oko jakih poziva (kol/flows, kol/score)",
        "insiders": "insajderi poziva (kol/insiders, corr/analyze)",
        "groups": "KOL skupine i njihova mjerenja (kol/score, kol/together)",
        "pair_tests": "testovi parova callera (kol/validate, kol/together)",
        "sessions": "sesije callera (kol/sessions, report)", "token_hours": "sati tokena (kol/sessions, report)",
        "kol_wallets": "novčanici callera (kol/flows, ui)", "kol_ids": "identiteti callera (14 čitača)",
        "follows": "praćeni računi: kopiranje (league/copy, fast/sources)",
    },
    "wallets.db": {
        "wallet_trades": "povijest za ocjene i dokaze novčanika (wallets/score, dokazani, rang, learn/masovno); "
                         "gubitnike već čisti ops/prune (gubitnici)",
        "wallets": "ocjene novčanika (28 čitača: copy, fast, rang)",
        "wallet_pnl": "PnL novčanika (run_wallets, ui)",
    },
    "paper.db": {
        "trades": "rezultati demo trgovanja (exits/fit, learn, paper/review)",
        "candidates": "odluke demo petlje s ishodom: učenje i pregled (learn/shadow, paper/review, exits/paths, paper/arms)",
        "reviews": "dnevni pregled demoa (run_paper, ui)", "trigger_points": "okidači za sjenu (learn/shadow)",
        "manual_exits": "ručni izlazi (run_paper)",
    },
    "shadow.db": {"points": "sjena: što bi bilo da je ušao (learn/shadow, learn/masovno)"},
    "ai.db": {"posts_ai": "plaćene AI oznake objava (learn/postai): brisanje = platiti ponovno",
              "post_tokens": "tokeni iz AI oznaka (learn/postai)", "batches": "AI serije (learn/postai)",
              "detektiv_runs": "AI detektiv (learn/detektiv)", "hipoteze": "AI hipoteze (learn/detektiv)",
              "ideje": "AI ideje (learn/detektiv)"},
    "events.db": {"call_outcomes": "ishodi poziva (events/outcomes, evreport, wallets/rang)",
                  "scores": "ocjene callera, kanala i novčanika (events/outcomes, brief)",
                  "early_wallets": "rani kupci s ishodom (events/outcomes, brief)",
                  "ev_report": "EV izvještaj (events/evreport)", "grok_predictions": "Grokove prognoze i ishod "
                  "(events/predictions, proposals/calib)"},
    "minute.db": {"call_candles": "minutne svijeće poziva: ishodi i backtestovi (kol/minute, rangedca/backtest, "
                                  "wallets/rang)",
                  "call_path": "put cijene nakon poziva (kol/pit, kol/tpsl, events/remeasure)",
                  "call_lv": "razine poziva (kol/pit, kol/tpsl)"},
    "tg.db": {"channels": "ocjene Telegram kanala (kol/collect, kol/minute, tg)"},
    "early.db": {"early_buyers": "rani kupci za ekipe i insajdere (kol/groupdisc, precall, preshill)"},
    "dugo.db": {"candles": "dnevne svijeće za tjedno učenje (dugo/learn)"},
    "xfeat.db": {"x_features": "plaćeni X podaci (ui/xfeat, scan/xmom, kandidati)"},
}
WHOLE_KEEP = {"league.db": "natjecanje, demo i kopiranje: novac i rezultati", "trade.db": "pravi novac: nalozi, pozicije",
              "usage.db": "troškovi plaćenih izvora (tjedni izvještaj troška po izvoru)",
              "market.db": "tržište i SOL cijena (režim, makro)", "nastoken.db": "naš token", "koltest.db": "KOL test pozicije",
              "strat.db": "strategije: pozicije i equity", "proposals.db": "prijedlozi i njihov ishod",
              "momentum.db": "momentum signali i kalibracija", "fast.db": "brzi put: odluke i ishodi"}
# Name parts that mean an outcome, a score, a label, a proof or money: KEEP when a table is not listed above.
KEEP_NAME = re.compile(r"(outcome|score|label|proof|dokaz|archive|trades|position|equity|order|review|calib|predict|"
                       r"learn|weight|rank|profile|stats|pnl|bench|report|candles|shadow|points|tier|recover|relabel|"
                       r"account|setting|member|usage|cost|credit|_runs$|^runs$|rules|plans|kv$|meta$|metas$)")
# Raw tables: what reads them and the shortest age a cleanup may start at (their readers need what is younger).
RAW = {
    ("hype.db", "hype_signals"): (7, "sirovi redovi skena; PRVI red po tokenu su ulazne značajke za učenje "
                                     "(learn/masovno, learn/confmodel) i ostaje; ostalo se satno sažima (ops/dbs.slim_signals)"),
    ("hype.db", "hype_details"): (7, "detalji skena; prvi i zadnji red po tokenu čitaju learn/confmodel i arhiva rugova"),
    ("hype.db", "chain_trades"): (14, "swapovi praćenih walleta; strategije čitaju zadnje sate, masovno zadnji dan; "
                                      "pravilo već postoji: ops/prune chain (14 d, DATA_PRUNE=on)"),
    ("hype.db", "chain_transfers"): (14, "transferi walleta (kol/traces); pravilo ops/prune chain (14 d)"),
    ("hype.db", "live_trades"): (7, "PumpPortal kupnje/prodaje (fast/checks, grupe, insajderi: zadnji sati/dani)"),
    ("hype.db", "live_launches"): (14, "nova lansiranja (insajderi, shill mreža, learn/masovno)"),
    ("hype.db", "apify_cache"): (1, "sirovi Apify JSON; ops/dbs ga već briše nakon APIFY_KEEP_DAYS"),
    ("hype.db", "token_pulse"): (7, "puls tokena svake 2 min; hype/pulse ga sam čisti nakon 7 d"),
    ("hype.db", "kol_mentions"): (7, "spominjanja na X (converge, copy: zadnji sat)"),
    ("hype.db", "tg_mentions"): (14, "Telegram spominjanja (corr/analyze, evidence)"),
    ("tg.db", "posts"): (14, "Telegram objave; pozivi su već u kol.db (kol/collect); learn/postai, converge: zadnji dani"),
    ("paper.db", "ticks"): (14, "cijene demo pozicija; netradeane već čisti ops/prune (4 d), tradeane koristi exits/fit"),
    ("wallets.db", "wallet_sightings"): (14, "viđenja walleta: red za ocjenjivanje (run_wallets harvest, corr/analyze)"),
    ("events.db", "events"): (30, "jedinstveni log događaja; events/store ima svoju retenciju (cijene 30 d, ostalo 90 d, "
                                  "budžet 600 MB)"),
    ("kol.db", "seen_cache"): (7, "cache viđenih objava (kol/collect)"),
    ("kol.db", "searches"): (14, "povijest X pretraga (kol/collect, discover, trending)"),
}
MIN_DAYS_DEFAULT = 14
LEARN_READERS = re.compile(r"^(learn/|exits/fit|exits/paths|kol/score|wallets/score|wallets/dokazani|wallets/rang|"
                           r"events/outcomes|events/remeasure|paper/review|hype/evaluate|dugo/learn|momentum/evgate|"
                           r"proposals/calib|proposals/outcomes|fast/outcomes|corr/analyze)")


# ---------- small helpers ----------------------------------------------------------------------------------------
class OutOfTime(Exception):
    pass


class Guard:
    """Time guard: every query aborts after QUERY_S (progress handler), the report stops after BUDGET_S."""

    def __init__(self, budget_s=None, query_s=None):
        self.t0 = time.monotonic()
        self.budget = BUDGET_S if budget_s is None else budget_s
        self.query_s = QUERY_S if query_s is None else query_s
        self.deadline = None
        self.skipped = []

    def left(self):
        return self.budget - (time.monotonic() - self.t0)

    def check(self):
        if self.left() <= 0:
            raise OutOfTime()

    def attach(self, con):
        con.set_progress_handler(lambda: 1 if self.deadline and time.monotonic() > self.deadline else 0, 20000)

    def q(self, con, sql, args=(), limit_s=None):
        """fetchall() under the per-query limit; OutOfTime when the report's budget is gone."""
        self.check()
        self.deadline = time.monotonic() + min(limit_s or self.query_s, max(0.5, self.left()))
        try:
            return con.execute(sql, args).fetchall()
        finally:
            self.deadline = None


def _ro(path, guard):
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=BUSY_MS / 1000)
    con.execute(f"PRAGMA busy_timeout={BUSY_MS}")
    guard.attach(con)
    return con


def _size(p):
    try:
        return os.path.getsize(p)
    except OSError:
        return 0


def tree_size(path):
    """Bytes under a folder (files only, symlinks not followed)."""
    total = 0
    for root, _dirs, names in os.walk(path):
        for n in names:
            try:
                total += os.lstat(os.path.join(root, n)).st_size
            except OSError:
                pass
    return total


def _q(name):
    return '"' + name.replace('"', '""') + '"'


def _zagreb(ts):
    from zoneinfo import ZoneInfo
    return dt.datetime.fromtimestamp(ts, ZoneInfo(TZ))


def _mb(b):
    return (b or 0) / 1e6


def _fmt_mb(b):
    mb = _mb(b)
    return f"{mb:.0f}" if mb >= 10 else f"{mb:.1f}"


def _fmt_rows(n):
    if n is None:
        return "?"
    return f"{n / 1e6:.1f} M" if n >= 1e6 else f"{n / 1e3:.0f} k" if n >= 1e4 else str(n)


# ---------- who reads a table (grep of the code at run time) -----------------------------------------------------
_READERS = {}


def readers(root=None):
    """{table: sorted modules that read it (FROM / JOIN)} from the repo's .py files (tests and audits left out)."""
    root = root or ROOT
    if root in _READERS:
        return _READERS[root]
    out = {}
    pat = re.compile(r"(?:FROM|JOIN)\s+([a-z_][a-z_0-9]*)")
    for dp, dirs, names in os.walk(root):
        rel = os.path.relpath(dp, root)
        if rel.split(os.sep)[0] in ("tests", "audit", ".git", ".claude", "node_modules") or "__pycache__" in rel:
            dirs[:] = []
            continue
        for n in names:
            if not n.endswith(".py"):
                continue
            p = os.path.join(dp, n)
            try:
                with open(p, encoding="utf-8", errors="ignore") as f:
                    s = f.read()
            except OSError:
                continue
            mod = os.path.relpath(p, root)[:-3].replace(os.sep, "/")
            for t in set(pat.findall(s)):
                out.setdefault(t, set()).add(mod)
    _READERS[root] = {t: sorted(v) for t, v in out.items()}
    return _READERS[root]


def classify(db, table, rd=None):
    """("keep", why) or ("raw", note, min_days) for one table."""
    if db in WHOLE_KEEP:
        return "keep", WHOLE_KEEP[db]
    why = (KEEP.get(db) or {}).get(table)
    if why:
        return "keep", why
    raw = RAW.get((db, table))
    if raw:
        return "raw", raw[1], raw[0]
    if table.startswith("sqlite_"):
        return "keep", "interna tablica SQLite-a"
    mods = (rd or {}).get(table, [])
    learn = [m for m in mods if LEARN_READERS.match(m)]
    if learn:
        return "keep", "čitaju je učenje / mjerenje: " + ", ".join(learn[:4])
    if KEEP_NAME.search(table):
        return "keep", "po imenu ishod / ocjena / novac / stanje" + (f" (čitači: {', '.join(mods[:3])})" if mods else "")
    return "raw", "čitači: " + (", ".join(mods[:4]) if mods else "nitko u kodu (FROM/JOIN)"), MIN_DAYS_DEFAULT


# ---------- one database -----------------------------------------------------------------------------------------
def _unit(v):
    """'s' | 'ms' | 'iso' | None from one value of a time column."""
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        if v > 1e14:
            return None
        if v > 1e11:
            return "ms"
        if v > 1e8:
            return "s"
        return None
    if isinstance(v, str) and re.match(r"^\d{4}-\d{2}-\d{2}", v):
        return "iso"
    return None


def _cut(unit, ts):
    if unit == "ms":
        return int(ts * 1000)
    if unit == "iso":
        return dt.datetime.fromtimestamp(ts, dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
    return int(ts)


def _to_ts(unit, v):
    try:
        if unit == "ms":
            return int(v) // 1000
        if unit == "s":
            return int(v)
        if unit == "iso":
            d = dt.datetime.fromisoformat(str(v)[:19].replace(" ", "T"))
            return int(d.replace(tzinfo=dt.timezone.utc).timestamp())
    except (TypeError, ValueError):
        return None
    return None


def _indexed(con, guard, table, col):
    """True when an index starts with col (a range COUNT is then cheap)."""
    for r in guard.q(con, f"PRAGMA index_list({_q(table)})"):
        info = guard.q(con, f"PRAGMA index_info({_q(r[1])})")
        if info and sorted(info)[0][2] == col:
            return True
    return False


def _time_col(con, guard, table, cols):
    """(column, unit) of the first column of TIME_COLS whose newest row holds a time value, else (None, None)."""
    for c in TIME_COLS:
        if c not in cols:
            continue
        try:
            r = guard.q(con, f"SELECT {_q(c)} FROM {_q(table)} WHERE {_q(c)} IS NOT NULL ORDER BY rowid DESC LIMIT 1")
        except sqlite3.OperationalError:   # WITHOUT ROWID table
            try:
                r = guard.q(con, f"SELECT MAX({_q(c)}) FROM {_q(table)}")
            except sqlite3.OperationalError:
                r = []
        u = _unit(r[0][0]) if r and r[0] else None
        if u:
            return c, u
    return None, None


def _comparable(v, c):
    return v is not None and (isinstance(v, str) == isinstance(c, str))


def _monotonic(con, guard, table, col, lo, hi, probes=16):
    """True when col grows with rowid on PROBES evenly spaced rows (an append log), so a binary search on rowid
    finds the row where a time cut falls. wallets.db wallet_trades, for one, is filled back in time per wallet."""
    vals = []
    for i in range(probes + 1):
        r = guard.q(con, f"SELECT {_q(col)} FROM {_q(table)} WHERE rowid >= ? ORDER BY rowid LIMIT 1",
                    (lo + (hi - lo) * i // probes,))
        if r and r[0][0] is not None:
            vals.append(r[0][0])
    if len(vals) < 3 or len({type(v) for v in vals}) > 1:
        return False
    return sum(1 for a, b in zip(vals, vals[1:]) if b < a) <= 1


def _bisect_newer(con, guard, table, col, cuts):
    """{cut: share of rows with col >= cut} for a table without an index on col whose col grows with rowid: binary
    search on rowid, rows scaled by the density of the rowid range. None when rowid is not usable that way."""
    try:
        lo0, hi0 = guard.q(con, f"SELECT MIN(rowid), MAX(rowid) FROM {_q(table)}")[0]
    except sqlite3.OperationalError:
        return None
    if lo0 is None:
        return {c: 0.0 for c in cuts}
    if not _monotonic(con, guard, table, col, lo0, hi0):
        return None
    span = hi0 - lo0 + 1
    out = {}
    for c in cuts:
        lo, hi = lo0, hi0 + 1
        while lo < hi:
            mid = (lo + hi) // 2
            r = guard.q(con, f"SELECT {_q(col)} FROM {_q(table)} WHERE rowid >= ? ORDER BY rowid LIMIT 1", (mid,))
            v = r[0][0] if r else None
            if not _comparable(v, c) or v < c:
                lo = mid + 1
            else:
                hi = mid
        out[c] = (hi0 - lo + 1) / span
    return out


def _scan_newer(con, guard, table, col, cuts):
    """({cut: rows with col >= cut}, oldest) in ONE pass over the table (under the per-query time guard)."""
    sums = ", ".join(f"SUM({_q(col)} >= ?)" for _ in cuts)
    r = guard.q(con, f"SELECT {sums}, MIN({_q(col)}) FROM {_q(table)} WHERE {_q(col)} IS NOT NULL", tuple(cuts))[0]
    return {c: int(r[i] or 0) for i, c in enumerate(cuts)}, r[-1]


def table_report(con, guard, table, nbytes, now, sampled=False, db=""):
    """{rows, bytes, ts_col, unit, n24, n7, oldest_ts, newer: {days: rows}, growth_b_day, old_b: {days: bytes},
    est (counts estimated), note} of one table; a table that runs out of time keeps what it got."""
    t = {"table": table, "rows": None, "bytes": nbytes, "ts_col": None, "unit": None, "n24": None, "n7": None,
         "oldest_ts": None, "growth_b_day": None, "old_b": {}, "est": False, "note": None}
    try:
        cols = [r[1] for r in guard.q(con, f"PRAGMA table_info({_q(table)})")]
        try:
            t["rows"] = guard.q(con, f"SELECT COUNT(*) FROM {_q(table)}")[0][0]
        except sqlite3.OperationalError as e:
            if "interrupted" not in str(e):
                raise
            mm = guard.q(con, f"SELECT MIN(rowid), MAX(rowid) FROM {_q(table)}")[0]
            t["rows"], t["est"] = (mm[1] - mm[0] + 1) if mm[0] is not None else 0, True
            t["note"] = "redovi procijenjeni (COUNT prespor)"
        if sampled and t["rows"]:
            r = guard.q(con, f"SELECT * FROM {_q(table)} ORDER BY rowid DESC LIMIT 200")
            per = sum(sum(len(v) if isinstance(v, (str, bytes)) else 8 for v in row) + 4 for row in r) / max(1, len(r))
            t["bytes"], t["est"] = int(per * t["rows"] * 1.25), True
        col, unit = _time_col(con, guard, table, cols)
        if not col or not t["rows"]:
            return t
        t["ts_col"], t["unit"] = col, unit
        cuts = {d: _cut(unit, now - d * D) for d in (1,) + DAYS}
        if t["rows"] > SMALL_ROWS and _indexed(con, guard, table, col):
            newer = {d: guard.q(con, f"SELECT COUNT(*) FROM {_q(table)} WHERE {_q(col)} >= ?", (c,))[0][0]
                     for d, c in cuts.items()}
            oldest = guard.q(con, f"SELECT MIN({_q(col)}) FROM {_q(table)}")[0][0]
        else:
            share = _bisect_newer(con, guard, table, col, list(cuts.values())) if t["rows"] > SMALL_ROWS else None
            if share is not None:
                newer = {d: int(round(share[c] * t["rows"])) for d, c in cuts.items()}
                r = guard.q(con, f"SELECT {_q(col)} FROM {_q(table)} WHERE {_q(col)} IS NOT NULL ORDER BY rowid LIMIT 1")
                oldest = r[0][0] if r else None
                t["est"] = True
            else:   # small, or not an append log: one pass counts every cut at once
                by_cut, oldest = _scan_newer(con, guard, table, col, list(cuts.values()))
                newer = {d: by_cut[c] for d, c in cuts.items()}
        t["n24"], t["n7"] = newer[1], newer[7]
        t["oldest_ts"] = _to_ts(unit, oldest)
        per = (t["bytes"] or 0) / t["rows"] if t["rows"] else 0
        t["growth_b_day"] = int(newer[1] * per)
        t["old_b"] = {d: int(max(0, t["rows"] - newer[d]) * per) for d in DAYS}
    except OutOfTime:
        raise
    except sqlite3.OperationalError as e:
        t["note"] = ("preskočeno: zaključano" if "locked" in str(e) or "busy" in str(e) else
                     "preskočeno: predugo" if "interrupted" in str(e) else f"preskočeno: {e}")[:120]
        guard.skipped.append(f"{db}.{table}" if db else table)
    return t


def db_report(path, guard, now, rd=None):
    """{name, file_b, wal_b, page_size, free_b, unused_b, tables: [...], note} of one database (read-only)."""
    name = os.path.basename(path)
    out = {"name": name, "file_b": _size(path), "wal_b": _size(path + "-wal"), "page_size": None, "free_b": None,
           "unused_b": None, "tables": [], "note": None}
    if out["file_b"] == 0:
        return out
    try:
        con = _ro(path, guard)
    except sqlite3.Error as e:
        out["note"] = f"nije otvorena: {e}"
        return out
    try:
        ps = guard.q(con, "PRAGMA page_size")[0][0]
        out["page_size"] = ps
        out["free_b"] = guard.q(con, "PRAGMA freelist_count")[0][0] * ps
        tables = [r[0] for r in guard.q(con, "SELECT name FROM sqlite_master WHERE type='table'")]
        owner = dict(guard.q(con, "SELECT name, tbl_name FROM sqlite_master WHERE type IN ('table', 'index')"))
        sizes, sampled = {}, False
        try:
            try:
                rows = guard.q(con, "SELECT name, pgsize, unused FROM dbstat WHERE aggregate=TRUE", limit_s=max(60, QUERY_S))
            except sqlite3.OperationalError as e:
                if "aggregate" not in str(e) and "no such column" not in str(e):
                    raise   # no dbstat at all, or too slow: the sampled estimate below
                rows = guard.q(con, "SELECT name, SUM(pgsize), SUM(unused) FROM dbstat GROUP BY name",
                               limit_s=max(60, QUERY_S))
            unused = 0
            for n, pg, un in rows:
                tb = owner.get(n, n)
                sizes[tb] = sizes.get(tb, 0) + (pg or 0)
                unused += un or 0
            out["unused_b"] = unused
        except sqlite3.OperationalError as e:   # no dbstat in this build (or too slow): sampled row sizes
            sampled = True
            out["note"] = "bez dbstat: veličine tablica procijenjene iz uzorka redova" if "no such table" in str(e) \
                else "dbstat predug: veličine tablica procijenjene iz uzorka redova"
        for tb in tables:
            if tb.startswith("sqlite_"):
                continue
            t = table_report(con, guard, tb, sizes.get(tb, 0), now, sampled=sampled, db=name)
            k = classify(name, tb, rd)
            t["keep"] = k[1] if k[0] == "keep" else None
            t["raw_note"] = k[1] if k[0] == "raw" else None
            t["min_days"] = k[2] if k[0] == "raw" else None
            out["tables"].append(t)
    except OutOfTime:
        out["note"] = "vrijeme izvještaja isteklo"
        guard.skipped.append(name)
    except sqlite3.Error as e:
        out["note"] = (f"preskočena: {e}")[:120]
        guard.skipped.append(name)
    finally:
        con.close()
    return out


# ---------- the whole report -------------------------------------------------------------------------------------
def disk_usage(data_dir):
    try:
        u = shutil.disk_usage(data_dir)
        return {"total_b": u.total, "used_b": u.used, "free_b": u.free}
    except OSError:
        return {"total_b": None, "used_b": None, "free_b": None}


def dirs(data_dir, extra=None):
    """[{path, b, data_disk}] of each folder directly under DATA_DIR, the files at its top level, and the extra folders
    (repo output/, research/, logs/, the HTTP cache) that are not inside DATA_DIR already."""
    out = []
    real = os.path.realpath(data_dir)
    try:
        dev = os.stat(real).st_dev
    except OSError:
        dev = None
    top = 0
    try:
        entries = list(os.scandir(real))
    except OSError:
        entries = []
    for e in entries:
        try:
            if e.is_dir(follow_symlinks=False):
                out.append({"path": e.name + "/", "b": tree_size(e.path), "data_disk": True})
            elif e.is_file(follow_symlinks=False) and not re.search(r"\.db(-wal|-shm)?$", e.name):
                top += e.stat(follow_symlinks=False).st_size
        except OSError:
            continue
    if top:
        out.append({"path": "(ostale datoteke)", "b": top, "data_disk": True})
    if extra is None:
        try:
            from event_calendar import http
            cache = http.CACHE_DIR
        except Exception:  # noqa: BLE001
            cache = None
        extra = [os.path.join(ROOT, "output"), os.path.join(ROOT, "research"), os.path.join(ROOT, "logs"), cache]
    seen = set()
    for p in extra:
        if not p or not os.path.isdir(p):
            continue
        rp = os.path.realpath(p)
        if rp == real or rp.startswith(real + os.sep) or rp in seen:
            continue   # already counted under DATA_DIR (start.sh symlinks output/ there)
        seen.add(rp)
        try:
            same = dev is not None and os.stat(rp).st_dev == dev
        except OSError:
            same = False
        out.append({"path": os.path.relpath(rp, ROOT) if rp.startswith(ROOT) else rp, "b": tree_size(rp), "data_disk": same})
    return sorted(out, key=lambda d: -d["b"])


def build(data_dir=None, now=None, extra_dirs=None, budget_s=None, query_s=None, state=None, root=None):
    """The whole report as a dict (read-only; the caller saves the state)."""
    data_dir = data_dir or disk.DATA_DIR
    now = now or time.time()
    guard = Guard(budget_s, query_s)
    rd = readers(root)
    rep = {"ts": int(now), "data_dir": data_dir, **disk_usage(data_dir), "dirs": dirs(data_dir, extra_dirs),
           "dbs": [], "skipped": guard.skipped}
    paths = sorted(p for p in (os.path.join(data_dir, n) for n in os.listdir(data_dir)) if p.endswith(".db")
                   and os.path.isfile(p)) if os.path.isdir(data_dir) else []
    paths.sort(key=lambda p: -_size(p))   # the big files first: the budget is spent where the space is
    for p in paths:
        if guard.left() <= 0:
            guard.skipped.append(os.path.basename(p))
            rep["dbs"].append({"name": os.path.basename(p), "file_b": _size(p), "wal_b": _size(p + "-wal"),
                               "tables": [], "note": "vrijeme izvještaja isteklo"})
            continue
        rep["dbs"].append(db_report(p, guard, now, rd))
    rep["took_s"] = round(time.monotonic() - guard.t0, 1)
    rep["growth"] = growth(rep, state, now)
    rep["candidates"] = candidates(rep)
    rep["alarm"] = alarm(rep)
    return rep


def growth(rep, state=None, now=None):
    """{inflow_mb_day, net_mb_day, net_from_ts, used_mb_day, runway_days}: inflow = sum of rows/day x bytes/row; net =
    used bytes vs the newest earlier run at least NET_MIN_H back (state hist); runway on net (> 0) else inflow."""
    now = now or rep.get("ts") or time.time()
    inflow = sum((t.get("growth_b_day") or 0) for d in rep.get("dbs", []) for t in d.get("tables", [])) / 1e6
    net, net_ts = None, None
    hist = (state or {}).get("hist") or []
    old = [h for h in hist if h.get("used_b") and now - h.get("ts", now) >= NET_MIN_H * 3600]
    if old and rep.get("used_b"):
        h = max(old, key=lambda x: x["ts"])
        net = (rep["used_b"] - h["used_b"]) / 1e6 / ((now - h["ts"]) / D)
        net_ts = h["ts"]
    use = net if net is not None else inflow
    free = _mb(rep.get("free_b")) if rep.get("free_b") is not None else None
    runway = round(free / use, 1) if free is not None and use and use > 0 else None
    return {"inflow_mb_day": round(inflow, 1), "net_mb_day": None if net is None else round(net, 1),
            "net_from_ts": net_ts, "used_mb_day": round(use, 1), "runway_days": runway,
            "basis": "neto od ranijeg mjerenja" if net is not None else "priljev redova (gornja granica)"}


def alarm(rep):
    """[Croatian lines] when the disk is over ALARM_USED or the runway under ALARM_RUNWAY_D days; [] otherwise."""
    out = []
    tot, used = rep.get("total_b"), rep.get("used_b")
    if tot and used is not None and used / tot > ALARM_USED:
        out.append(f"disk {used / tot:.0%} pun (prag {ALARM_USED:.0%})")
    rw = (rep.get("growth") or {}).get("runway_days")
    if rw is not None and rw < ALARM_RUNWAY_D:
        out.append(f"disk pun za ~{rw:.1f} dana (prag {ALARM_RUNWAY_D:.0f})")
    return out


def candidates(rep):
    """[{what, db, table, days, b, alt: {days: b}, note}] biggest first: old rows of raw tables (from their min_days),
    VACUUM per file, cache folders. KEEP tables never appear."""
    out = []
    for d in rep.get("dbs", []):
        for t in d.get("tables", []):
            if t.get("keep") or not t.get("old_b"):
                continue
            ok = {n: b for n, b in t["old_b"].items() if n >= (t.get("min_days") or MIN_DAYS_DEFAULT) and b >= 1e6}
            if not ok:
                continue
            n = min(ok)
            out.append({"what": "redovi", "db": d["name"], "table": t["table"], "days": n, "b": ok[n],
                        "alt": {k: v for k, v in t["old_b"].items() if k != n}, "est": t.get("est"),
                        "note": t.get("raw_note")})
        vac = (d.get("free_b") or 0) + (d.get("unused_b") or 0)
        if vac >= 5e6:
            out.append({"what": "vacuum", "db": d["name"], "b": vac, "note": "slobodne stranice + neiskorišteno u "
                        "stranicama; ops/dbs.compact ga već radi dnevno kad je >= 35 % mrtvo i ima mjesta"})
        if (d.get("wal_b") or 0) >= 50e6:
            out.append({"what": "wal", "db": d["name"], "b": d["wal_b"], "note": "WAL; satni checkpoint (ops/dbs) ga reže"})
    for x in rep.get("dirs", []):
        if x["b"] >= 5e6 and any(k in x["path"] for k in ("cache", "pagecache")):
            out.append({"what": "cache", "path": x["path"], "b": x["b"], "note": "cache se sam obnavlja (event_calendar/"
                        "http.prune satno; stranice se ponovno grade)"})
    return sorted(out, key=lambda c: -c["b"])


# ---------- the log block ----------------------------------------------------------------------------------------
def _short(text, n=70):
    text = (text or "").split(";")[0]
    return text if len(text) <= n else text[:n - 1] + "…"


def _day(ts):
    return _zagreb(ts).strftime("%d.%m.") if ts else "?"


def lines(rep):
    """The compact block for the Render log (every line starts with 'disk izvještaj')."""
    P = "disk izvještaj"
    g = rep.get("growth") or {}
    tot, used, free = rep.get("total_b"), rep.get("used_b"), rep.get("free_b")
    pct = f" ({used / tot:.0%})" if tot and used is not None else ""
    rw = g.get("runway_days")
    net = g.get("net_mb_day") is not None
    head = (f"{P} (samo mjerenje, ništa nije obrisano): disk {_mb(used) / 1e3:.2f} od {_mb(tot) / 1e3:.2f} GB{pct}, "
            f"slobodno {_mb(free) / 1e3:.2f} GB; rast ~{g.get('used_mb_day', 0):.0f} MB/dan ("
            + (f"neto od {_day(g['net_from_ts'])}; priljev redova {g.get('inflow_mb_day', 0):.0f} MB/dan" if net
               else "priljev redova, gornja granica: retencija oslobađa stranice") + ")"
            + (f" -> pun za ~{rw:.0f} dana" if rw is not None else " -> ne raste") + f"; {rep.get('took_s', 0):.0f} s")
    out = [head]
    if rep.get("alarm"):
        out.append(f"{P} | ALARM: " + "; ".join(rep["alarm"]))
    out.append(f"{P} | mape: " + (", ".join(f"{x['path']} {_fmt_mb(x['b'])} MB" + ("" if x["data_disk"] else " (nije podatkovni disk)")
                                             for x in rep.get("dirs", [])[:8]) or "-"))
    dbs = sorted(rep.get("dbs", []), key=lambda d: -(d.get("file_b") or 0))
    out.append(f"{P} | baze (MB; WAL, slobodne stranice, VACUUM ~): " + ", ".join(
        f"{d['name']} {_fmt_mb(d['file_b'])} ({_fmt_mb(d.get('wal_b'))}, {_fmt_mb(d.get('free_b'))}, "
        f"{_fmt_mb((d.get('free_b') or 0) + (d.get('unused_b') or 0))})" for d in dbs[:10] if d.get("file_b")))
    tabs = sorted(((d["name"], t) for d in rep.get("dbs", []) for t in d.get("tables", [])), key=lambda x: -(x[1]["bytes"] or 0))
    out.append(f"{P} | top {TOP} tablica: MB, redova, +MB/dan, 24 h / 7 d redova, najstariji, starije od 7/14/30 d MB:")
    for i, (db, t) in enumerate(tabs[:TOP], 1):
        ob = t.get("old_b") or {}
        age = (f"+{_fmt_mb(t['growth_b_day'])}/dan, {_fmt_rows(t['n24'])} / {_fmt_rows(t['n7'])}, od {_day(t['oldest_ts'])}, "
               f">7/14/30 d {'/'.join(_fmt_mb(ob.get(n)) for n in DAYS)}") if t.get("ts_col") else \
            ("prazna" if t.get("rows") == 0 else "bez vremenskog stupca")
        tag = f"KEEP: {_short(t['keep'])}" if t.get("keep") else f"sirovo: {_short(t.get('raw_note'))}"
        out.append(f"{P} | {i:2d}. {db} {t['table']} {_fmt_mb(t['bytes'])} MB, {_fmt_rows(t['rows'])}"
                   + (" ~" if t.get("est") else "") + f", {age} [{tag}]" + (f" ({t['note']})" if t.get("note") else ""))
    cands = rep.get("candidates", [])
    out.append(f"{P} | kandidati za čišćenje (procjena; NIŠTA nije obrisano, svaki traži potvrdu):")
    for i, c in enumerate(cands[:TOP_CAND], 1):
        if c["what"] == "redovi":
            alt = ", ".join(f"{k} d: {_fmt_mb(v)}" for k, v in sorted(c["alt"].items()))
            out.append(f"{P} | {i:2d}. {c['db']} {c['table']}: redovi stariji od {c['days']} d ~{_fmt_mb(c['b'])} MB"
                       + (f" ({alt})" if alt else "") + f"; {c['note']}")
        elif c["what"] == "cache":
            out.append(f"{P} | {i:2d}. mapa {c['path']}: ~{_fmt_mb(c['b'])} MB; {c['note']}")
        else:
            out.append(f"{P} | {i:2d}. {c['what'].upper()} {c['db']}: ~{_fmt_mb(c['b'])} MB; {c['note']}")
    if not cands:
        out.append(f"{P} | (nema kandidata iznad 1 MB)")
    total = sum(c["b"] for c in cands if c["what"] in ("redovi", "vacuum"))
    keep = sum(1 for d in rep.get("dbs", []) for t in d.get("tables", []) if t.get("keep"))
    out.append(f"{P} | ukupno moguće (redovi + VACUUM, uz najmanji siguran N): ~{_fmt_mb(total)} MB; KEEP tablica "
               f"(ne predlažu se): {keep}" + (f"; preskočeno: {', '.join(rep['skipped'][:6])}" if rep.get("skipped") else ""))
    return out


# ---------- state, when to run, the brief -------------------------------------------------------------------------
def state_path(data_dir=None):
    return os.path.join(data_dir or disk.DATA_DIR, STATE)


def load_state(data_dir=None):
    try:
        with open(state_path(data_dir)) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_state(rep, prev, data_dir=None, commit=None, reason=None):
    """The one file this module writes: summary, top candidates, per-table bytes, the used-disk history (14 runs)."""
    hist = [h for h in (prev.get("hist") or []) if h.get("ts")][-13:] + [{"ts": rep["ts"], "used_b": rep.get("used_b")}]
    st = {"ts": rep["ts"], "commit": commit if commit is not None else (prev.get("commit") or ""),
          "daily": prev.get("daily"), "reason": reason, "total_b": rep.get("total_b"), "used_b": rep.get("used_b"),
          "free_b": rep.get("free_b"), "growth": rep.get("growth"), "alarm": rep.get("alarm"),
          "candidates": [{k: v for k, v in c.items() if k != "alt"} for c in rep.get("candidates", [])[:5]],
          "tables": {f"{d['name']}.{t['table']}": [t.get("bytes"), t.get("rows")] for d in rep.get("dbs", [])
                     for t in d.get("tables", []) if (t.get("bytes") or 0) >= 1e6},
          "hist": hist}
    z = _zagreb(rep["ts"])
    if reason in ("dnevno", "deploy") and (z.hour, z.minute) >= DAILY_AT:   # a deploy run after 06:30 is today's too
        st["daily"] = z.date().isoformat()
    p = state_path(data_dir)
    tmp = p + ".tmp"
    with open(tmp, "w") as f:
        json.dump(st, f)
    os.replace(tmp, p)
    return st


def in_night(now=None):
    """True inside the heavy-job night window (01-06 Zagreb by default): the report waits."""
    from ops import heavy
    win = heavy.night_hours()
    if win is None:
        return False
    h = _zagreb(now or time.time()).hour
    a, b = win
    return a <= h < b if a < b else (h >= a or h < b)


def due(state, now=None, commit=None):
    """'deploy' | 'dnevno' | None: the first run after a deploy (commit marker), else once a day from 06:30 Zagreb;
    never inside the night window."""
    now = now or time.time()
    if in_night(now):
        return None
    commit = os.environ.get("RENDER_GIT_COMMIT", "") if commit is None else commit
    if not state or state.get("commit", "") != commit:
        return "deploy"
    z = _zagreb(now)
    if (z.hour, z.minute) >= DAILY_AT and state.get("daily") != z.date().isoformat():
        return "dnevno"
    return None


def run(data_dir=None, now=None, log=print, reason=None, commit=None, **kw):
    """Build, log the block, save the state. Returns the report."""
    data_dir = data_dir or disk.DATA_DIR
    prev = load_state(data_dir)
    rep = build(data_dir, now, state=prev, **kw)
    for ln in lines(rep):
        log(ln)
    try:
        save_state(rep, prev, data_dir, commit if commit is not None else os.environ.get("RENDER_GIT_COMMIT", ""), reason)
    except OSError as e:
        log(f"disk izvještaj: stanje nije spremljeno ({e})")
    return rep


def maybe_run(data_dir=None, now=None, log=print, **kw):
    """--auto: run when due() says so (and say why in the first line), else nothing. Returns the report or None."""
    data_dir = data_dir or disk.DATA_DIR
    why = due(load_state(data_dir), now)
    if not why:
        return None
    log(f"disk izvještaj: pokrećem ({'prvi start nakon deploya' if why == 'deploy' else 'dnevno od 06:30'})")
    return run(data_dir, now, log, reason=why, **kw)


def brief_part(now=None, data_dir=None):
    """get_hourly_brief health.disk: live used / free, the last report's growth and runway (recomputed on today's free
    space), its top candidates, and the alarm lines (also as alerts)."""
    data_dir = data_dir or disk.DATA_DIR
    now = now or time.time()
    st = load_state(data_dir)
    u = disk_usage(data_dir)
    g = st.get("growth") or {}
    per_day = g.get("used_mb_day")
    runway = round(_mb(u["free_b"]) / per_day, 1) if u["free_b"] is not None and per_day and per_day > 0 else None
    rep = {**u, "growth": {"runway_days": runway}}
    al = alarm(rep)
    out = {"used_pct": round(u["used_b"] / u["total_b"] * 100, 1) if u["total_b"] else None,
           "used_gb": round(_mb(u["used_b"]) / 1e3, 2) if u["used_b"] is not None else None,
           "free_gb": round(_mb(u["free_b"]) / 1e3, 2) if u["free_b"] is not None else None,
           "growth_mb_day": per_day, "growth_basis": g.get("basis"), "runway_days": runway,
           "report_ts": st.get("ts"), "top_candidates": [
               {"what": c.get("what"), "db": c.get("db"), "table": c.get("table"), "path": c.get("path"),
                "days": c.get("days"), "mb": round(_mb(c.get("b")), 1)} for c in (st.get("candidates") or [])[:3]],
           "alarm": bool(al), "alerts": [{"key": "disk", "service": "disk", "level": "bad", "type": "disk",
                                          "title": "Disk: " + "; ".join(al),
                                          "detail": "ops/diskreport: kandidati za čišćenje u Render logu "
                                                    "('disk izvještaj'); ništa se ne briše bez potvrde"}] if al else []}
    if not st:
        out["note"] = "izvještaj diska još nije radio (prvi nakon deploya, pa dnevno u 06:30)"
    return out


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    try:
        if os.nice(0) < 10:
            os.nice(10 - os.nice(0))
    except OSError:
        pass
    if "--json" in argv:
        rep = build(state=load_state())
        print(json.dumps(rep, default=str, ensure_ascii=False))
        return 0
    if "--auto" in argv:
        maybe_run(log=lambda s: print(s, flush=True))
        return 0
    run(log=lambda s: print(s, flush=True), reason="ručno")
    return 0


if __name__ == "__main__":
    sys.exit(main())
