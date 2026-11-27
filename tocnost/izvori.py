"""What every shown score predicts and where its point-in-time record lives. Every loader opens its source database
READ-ONLY, takes the score exactly as it was stored at that moment (never recomputed with later data) and judges the
outcome only from what happened after it, inside the score's horizon. Each loader returns stat rows
{subject, ts, bucket, outcome, resolved_ts}; stat.aggregate applies the window, the horizon and the dedup.

SPECS: key -> name, buckets [(bucket, dir)], horizon_s, since (the last tuning date, below), oos (how "days the model
did not see" is guaranteed), ishod (what outcome 1 means, plain words for the tooltip; no thresholds), izvor.

Last tuning dates (since): a hand-set rule is counted only after the day its rule last changed (git history of the
file that holds it, read 27.11.: rugfilter/score.py T unchanged since 4.11., ui/confidence.py parts 9.11., ui/
kolsummary verdict thresholds 10.11., wallets/dokazani RULE 10.11., wallets/rang.py 20.11., ui/prijedlog.py 17.11.,
veliki/sjena.py profiles 18.11.). A learned score (pouzdanost's learned model, the hype weights, refit daily or every
6 h; learn_runs) is stored as the model of that moment produced it, before its outcome existed: every row is out of
sample for the model that made it (oos "pit"); the newest refit is named on the owner page. Where the file's last
change may have been cosmetic the cut is still taken (conservative: fewer days, never seen days).
"""
import calendar
import json
import os
import sqlite3
import time

from tocnost import store

H, DAY = 3600, 86400
ROOT = store.HERE


def _d(s):
    return calendar.timegm(time.strptime(s, "%Y-%m-%d"))


TP, SL = 0.15, -0.25          # same exit as the Prijedlog box (ui/prijedlog_log)
COLLAPSE = 0.30               # rug outcome: the market cap fell to 30 % of the value at the check or lower
MIN_POINTS = 3                # fewer price points in the horizon = unknown (12.11. rule "nepouzdano")
REF_MAX_AGE_S = 2 * H         # a start value older than this before the score is not its start
SNAP_MAX_AGE_S = 2 * DAY      # a night snapshot older than this does not judge a later call / buy
WALLET_H = 7 * DAY
MIN_SOL = 0.02

LEVEL3 = [("visoka", 1), ("srednja", 0), ("niska", -1)]
TPSL = "u idućem danu token je narastao prije nego što je jako pao"
SPECS = {
    "pouzdanost": {"name": "Pouzdanost", "buckets": LEVEL3, "horizon_s": DAY, "since": _d("2026-11-09"), "oos": "pit",
                   "ishod": TPSL, "kratko": "narasli prije pada",
                   "izvor": "stranica tokena (prikaz) i kartica Prijedlog (prijedlog_log.conf)"},
    "sansa": {"name": "Šansa za skok", "buckets": LEVEL3, "horizon_s": DAY, "since": _d("2026-11-09"), "oos": "pit",
              "ishod": TPSL, "kratko": "narasli prije pada", "izvor": "stranica tokena (prikaz)"},
    "hype": {"name": "Hype ocjena", "buckets": [("50 i više", 1), ("ispod 50", -1)], "horizon_s": DAY,
             "since": _d("2026-11-04"), "oos": "pit", "ishod": TPSL, "kratko": "narasli prije pada",
             "izvor": "hype.db hype_signals (ocjena s težinama tog trenutka), prvi signal tokena u danu"},
    "kartica": {"name": "Kartica Kupi / Nemoj kupiti", "buckets": [("kupi", 1), ("nemoj", -1)], "horizon_s": DAY,
                "since": _d("2026-11-17"), "oos": "rule", "ishod": TPSL, "kratko": "narasli prije pada",
                "izvor": "hype.db prijedlog_log (kupi) i prikaz (nemoj, od 27.11.)"},
    "rug": {"name": "Provjera ruga", "buckets": [("PROLAZI", -1), ("OPREZ", 0), ("VISOK RIZIK", 1), ("ODBAČEN", 1)],
            "horizon_s": DAY, "since": _d("2026-11-04"), "oos": "rule",
            "ishod": "u idućem danu token je rugan ili je izgubio većinu vrijednosti", "kratko": "rugani ili srušeni",
            "izvor": "rug.db rug_reports (presuda u trenutku provjere)"},
    "topcheck": {"name": "Obavezna provjera ruga", "buckets": [("prolazi", -1), ("oprez", 0), ("pao", 1)],
                 "horizon_s": DAY, "since": _d("2026-11-27"), "oos": "rule",
                 "ishod": "u idućem danu token je rugan ili je izgubio većinu vrijednosti", "kratko": "rugani ili srušeni",
                 "izvor": "prikaz na stranici tokena (od 27.11.; topcheck.db čuva samo zadnju provjeru)"},
    "kol": {"name": "Presuda za influencera", "buckets": [("drzi_se", 1), ("samo_brzo", -1), ("ne_isplati_se", -1),
                                                          ("premalo", 0)],
            "horizon_s": DAY, "since": _d("2026-11-10"), "oos": "rule",
            "ishod": "njegov sljedeći poziv bio je dan kasnije u plusu", "kratko": "poziva u plusu dan kasnije",
            "izvor": "noćna snimka presude (14 dana; od 27.11.) i kol.db calls.r24h poziva poslije snimke"},
    "dokazani": {"name": "Novčanik: vrijedi kopirati", "buckets": [("dokazan", 1), ("nije dokazan", 0)],
                 "horizon_s": WALLET_H, "since": _d("2026-11-10"), "oos": "rule",
                 "ishod": "u tjedan dana od kupnje novčanik je iz tog tokena izvukao više nego što je uložio",
                 "kratko": "kupnji u plusu", "izvor": "wallets.db dokazani (svaki krug) i wallet_trades poslije kruga"},
    "rang": {"name": "Rang za kopiranje", "buckets": [("60 i više", 1), ("40 do 59", 0), ("ispod 40", -1)],
             "horizon_s": WALLET_H, "since": _d("2026-11-20"), "oos": "rule",
             "ishod": "u tjedan dana od kupnje novčanik je iz tog tokena izvukao više nego što je uložio",
             "kratko": "kupnji u plusu", "izvor": "noćna snimka copy_rank (od 27.11.) i wallet_trades poslije snimke"},
    "midcap_grok": {"name": "Grok o midcapu", "buckets": [("kupi", 1), ("preskoči", -1), ("bez mišljenja", 0)],
                    "horizon_s": 72 * H, "since": _d("2026-11-18"), "oos": "rule",
                    "ishod": "zamišljeni ulaz po pravilu završio je u plusu nakon troška", "kratko": "ulaza u plusu",
                    "izvor": "league.db veliki_sjena (profil pravilo), prvi ulaz tokena u danu"},
    "midcap_zona": {"name": "Mjesto u zoni (midcap)", "buckets": [(b, 0) for b in ("ispod", "dno", "donja", "sredina",
                                                                                     "vrh", "iznad")],
                    "horizon_s": 72 * H, "since": _d("2026-11-18"), "oos": "rule",
                    "ishod": "zamišljeni ulaz po pravilu završio je u plusu nakon troška", "kratko": "ulaza u plusu",
                    "izvor": "league.db veliki_sjena (profil pravilo), prvi ulaz tokena u danu"},
}
ORDER = list(SPECS)


def paths(over=None):
    from kol import store as kstore
    p = {"hype": os.path.join(ROOT, "hype.db"), "rug": os.environ.get("RUG_DB", os.path.join(ROOT, "rug.db")),
         "kol": kstore.DB, "wallets": os.environ.get("WALLET_DB", os.path.join(ROOT, "wallets.db")),
         "league": os.environ.get("LEAGUE_DB", os.path.join(ROOT, "league.db")), "tocnost": store.DB}
    p.update(over or {})
    return p


def ro(path):
    if not path or not os.path.exists(path) or not os.path.getsize(path):
        return None
    try:
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=10)
        con.execute("SELECT 1")
        return con
    except sqlite3.Error:
        return None


def _has(con, table):
    return con is not None and con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                                           (table,)).fetchone() is not None


# ---------- buckets ------------------------------------------------------------------------------------------------

def level(v):
    """The confidence levels (ui/confidence.LEVELS) for pouzdanost and šansa."""
    from ui.confidence import level as _lvl
    return _lvl(v)[0] if v is not None else None


def hype_bucket(v):
    return None if v is None else "50 i više" if v >= 50 else "ispod 50"


def rang_bucket(v):
    return None if v is None else "60 i više" if v >= 60 else "40 do 59" if v >= 40 else "ispod 40"


# ---------- price paths (hype.db) ----------------------------------------------------------------------------------

def series(hcon, token, t0, t1):
    """[(ts, mcap)] of hype_snapshots and token_pulse with t0 <= ts <= t1 (a price-only row is skipped)."""
    out = []
    for tbl in ("hype_snapshots", "token_pulse"):
        if not _has(hcon, tbl):
            continue
        out += [(t, m) for t, m in hcon.execute(f"SELECT ts, mcap FROM {tbl} WHERE token=? AND ts>=? AND ts<=? "
                                                "AND mcap > 0", (token, int(t0), int(t1)))]
    return sorted(out)


def ref_at(hcon, token, ts):
    """The newest market cap at or before ts (at most REF_MAX_AGE_S old), else None: never a later one."""
    s = series(hcon, token, ts - REF_MAX_AGE_S, ts)
    return s[-1][1] if s else None


def tpsl(hcon, token, ts, ref, horizon=DAY, tp=TP, sl=SL):
    """1 when +tp came before sl in (ts, ts + horizon], 0 otherwise; None with too few points or no start."""
    ref = ref or ref_at(hcon, token, ts)
    if not ref:
        return None
    vals = [m / ref - 1 for t, m in series(hcon, token, ts + 1, ts + horizon)]
    if len(vals) < MIN_POINTS:
        return None
    tp_at = next((i for i, r in enumerate(vals) if r >= tp), None)
    sl_at = next((i for i, r in enumerate(vals) if r <= sl), None)
    return int(tp_at is not None and (sl_at is None or tp_at < sl_at))


def collapsed(hcon, token, ts, ref, horizon=DAY):
    """1 when the token was archived as rugged, or fell to COLLAPSE of ref, in (ts, ts + horizon]; 0 when the path
    is known and neither happened; None without a path."""
    if _has(hcon, "rug_archive"):
        r = hcon.execute("SELECT archived_ts FROM rug_archive WHERE token=?", (token,)).fetchone()
        if r and r[0] and ts < r[0] <= ts + horizon:
            return 1
    ref = ref or ref_at(hcon, token, ts)
    if not ref:
        return None
    vals = [m for _, m in series(hcon, token, ts + 1, ts + horizon)]
    if len(vals) < MIN_POINTS:
        return None
    return int(min(vals) <= COLLAPSE * ref)


def _row(subject, ts, bucket, outcome, horizon):
    return {"subject": subject, "ts": int(ts), "bucket": bucket, "outcome": outcome, "resolved_ts": int(ts + horizon)}


def _one_per_day(rows):
    """First row per (subject, bucket-free UTC day): the loaders compute an outcome only once per token and day."""
    seen, out = set(), []
    for r in sorted(rows, key=lambda r: r[1]):
        k = (r[0], int(r[1] // DAY))
        if k not in seen:
            seen.add(k)
            out.append(r)
    return out


# ---------- loaders ------------------------------------------------------------------------------------------------

def shown_tpsl(P, score, since, now, extra=()):
    """prikaz rows of a page-logged score (pouzdanost, šansa, kartica 'nemoj') judged by tpsl; extra: more
    (subject, ts, bucket, ref) rows from another point-in-time log."""
    tcon, hcon = store.ro(P["tocnost"]), ro(P["hype"])
    try:
        base = [(r["subject"], r["ts"], r["bucket"], r["ref"]) for r in (store.shown(tcon, score, since, now) if tcon else [])]
        out = []
        for subj, ts, b, ref in _one_per_day(base + list(extra)):
            if ts + DAY > now:
                continue
            out.append(_row(subj, ts, b, tpsl(hcon, subj, ts, ref) if hcon else None, DAY))
        return out
    finally:
        for c in (tcon, hcon):
            if c is not None:
                c.close()


def prijedlog_rows(P, since, now):
    """hype.db prijedlog_log: (token, ts, razina, mcap0, conf) as the box showed them."""
    hcon = ro(P["hype"])
    if not _has(hcon, "prijedlog_log"):
        if hcon is not None:
            hcon.close()
        return []
    try:
        return hcon.execute("SELECT token, ts, razina, mcap0, conf FROM prijedlog_log WHERE ts>=? AND ts<=?",
                            (int(since), int(now))).fetchall()
    finally:
        hcon.close()


def load_pouzdanost(P, since, now):
    extra = [(t, ts, level(conf), m0) for t, ts, _, m0, conf in prijedlog_rows(P, since, now) if conf is not None]
    return shown_tpsl(P, "pouzdanost", since, now, extra)


def load_sansa(P, since, now):
    return shown_tpsl(P, "sansa", since, now)


def load_kartica(P, since, now):
    extra = [(t, ts, "kupi", m0) for t, ts, _, m0, _ in prijedlog_rows(P, since, now)]
    return shown_tpsl(P, "kartica", since, now, extra)


def load_hype(P, since, now):
    """The first hype signal of each token in each UTC day, with the score it had then (weights of that moment)."""
    hcon = ro(P["hype"])
    if not _has(hcon, "hype_signals"):
        if hcon is not None:
            hcon.close()
        return []
    try:
        firsts = hcon.execute("SELECT token, MIN(ts) FROM hype_signals WHERE ts>=? AND ts<=? GROUP BY token, ts / 86400",
                              (int(since), int(now - DAY))).fetchall()
        out = []
        for tok, ts in firsts:
            sc, mc = hcon.execute("SELECT score, mcap FROM hype_signals WHERE token=? AND ts=?", (tok, ts)).fetchone()
            out.append(_row(tok, ts, hype_bucket(sc), tpsl(hcon, tok, ts, mc), DAY))
        return out
    finally:
        hcon.close()


def load_rug(P, since, now):
    rcon, hcon = ro(P["rug"]), ro(P["hype"])
    try:
        if not _has(rcon, "rug_reports") or hcon is None:
            return []
        rows = rcon.execute("SELECT mint, checked_at, verdict, data FROM rug_reports WHERE checked_at>=? AND "
                            "checked_at<=? ORDER BY checked_at", (int(since), int(now - DAY))).fetchall()
        out = []
        for mint, ts, verdict, data in _one_per_day(rows):
            try:
                mk = (json.loads(data or "{}").get("market") or {})
            except (ValueError, TypeError):
                mk = {}
            out.append(_row(mint, ts, verdict, collapsed(hcon, mint, ts, mk.get("mcap")), DAY))
        return out
    finally:
        for c in (rcon, hcon):
            if c is not None:
                c.close()


def load_topcheck(P, since, now):
    tcon, hcon = store.ro(P["tocnost"]), ro(P["hype"])
    try:
        if tcon is None or hcon is None:
            return []
        rows = [(r["subject"], r["ts"], r["bucket"], r["ref"]) for r in store.shown(tcon, "topcheck", since, now - DAY)]
        return [_row(s, ts, b, collapsed(hcon, s, ts, ref), DAY) for s, ts, b, ref in _one_per_day(rows)]
    finally:
        for c in (tcon, hcon):
            if c is not None:
                c.close()


def _snap_at(snaps, subject, ts):
    """The newest night snapshot of subject strictly before ts and at most SNAP_MAX_AGE_S old: (bucket) or None."""
    best = None
    for st, b in snaps.get(subject, ()):
        if st < ts and ts - st <= SNAP_MAX_AGE_S:
            best = b
        elif st >= ts:
            break
    return best


def _snaps(tcon, score, since, now):
    out = {}
    for r in store.shown(tcon, score, since - SNAP_MAX_AGE_S, now):
        out.setdefault(r["subject"], []).append((r["ts"], r["bucket"]))
    return out


def load_kol(P, since, now):
    """Each account's first call per token after a night snapshot of its verdict; outcome r24h > 0 (known one day
    after the call)."""
    tcon, kcon = store.ro(P["tocnost"]), ro(P["kol"])
    try:
        if tcon is None or not _has(kcon, "calls"):
            return []
        snaps = _snaps(tcon, "kol", since, now)
        if not snaps:
            return []
        cols = {r[1] for r in kcon.execute("PRAGMA table_info(calls)")}
        bad = " AND bad IS NULL" if "bad" in cols else ""
        rows = kcon.execute("SELECT handle, token, ts, r24h, mcap0 FROM calls WHERE ts>=? AND ts<=? AND kind NOT IN "
                            f"('buy','sell'){bad} ORDER BY ts", (int(since), int(now - DAY))).fetchall()
        seen, out = set(), []
        for h, tok, ts, r24, mc in rows:
            if (h, tok) in seen:
                continue
            seen.add((h, tok))
            if mc is not None and mc < 30000:
                continue
            b = _snap_at(snaps, (h or "").lower(), ts)
            if b is None:
                continue
            out.append({"subject": f"{h}:{tok}", "ts": int(ts), "bucket": b,
                        "outcome": None if r24 is None else int(r24 > 0), "resolved_ts": int(ts + DAY)})
        return out
    finally:
        for c in (tcon, kcon):
            if c is not None:
                c.close()


def wallet_entries(wcon, wallets, since, now, horizon=WALLET_H):
    """{wallet: [(mint, t, outcome)]}: the wallet's FIRST buy of a mint at t (since <= t <= now - horizon), outcome
    1 when the SOL of all his trades of that mint in [t, t + horizon] sums above zero (took out more than he put in),
    0 otherwise; a first buy under MIN_SOL is skipped. Only trades up to t + horizon are read for it."""
    out = {}
    ws = list(wallets)
    for i in range(0, len(ws), 400):
        chunk = ws[i:i + 400]
        q = ",".join("?" * len(chunk))
        rows = wcon.execute(f"SELECT wallet, mint, ts, sol, kind FROM wallet_trades WHERE wallet IN ({q}) AND ts<=? "
                            "ORDER BY wallet, mint, ts", (*chunk, int(now))).fetchall()
        cur, first, acc = None, None, None
        def flush():
            if cur and first is not None and since <= first[0] <= now - horizon and -first[1] >= MIN_SOL:
                out.setdefault(cur[0], []).append((cur[1], first[0], int(acc > 0)))
        for w, m, ts, sol, kind in rows:
            if (w, m) != cur:
                flush()
                cur, first, acc = (w, m), None, 0.0
            if first is None:
                if kind != "buy":
                    cur = (w, m)   # a sale before any buy we know: no first buy in the history
                    first = (-1, 0)
                    continue
                first = (ts, sol or 0)
            if first[0] >= 0 and ts <= first[0] + horizon:
                acc += sol or 0
        flush()
    return out


def load_dokazani(P, since, now):
    """A wallet's first buy of a token after a dokazani run (at most SNAP_MAX_AGE_S after it): the run's verdict
    (passed = dokazan) against what that wallet then made on that token in a week."""
    wcon = ro(P["wallets"])
    try:
        if not _has(wcon, "dokazani") or not _has(wcon, "wallet_trades"):
            return []
        runs = {}
        for w, a, p in wcon.execute("SELECT wallet, as_of, passed FROM dokazani WHERE as_of>=? ORDER BY as_of",
                                    (int(since - SNAP_MAX_AGE_S),)):
            runs.setdefault(w, []).append((a, "dokazan" if p else "nije dokazan"))
        ent = wallet_entries(wcon, runs, since, now)
        out = []
        for w, items in ent.items():
            for m, t, o in items:
                b = _snap_at(runs, w, t)
                if b:
                    out.append({"subject": f"{w}:{m}", "ts": t, "bucket": b, "outcome": o, "resolved_ts": t + WALLET_H})
        return out
    finally:
        if wcon is not None:
            wcon.close()


def load_rang(P, since, now):
    tcon, wcon = store.ro(P["tocnost"]), ro(P["wallets"])
    try:
        if tcon is None or not _has(wcon, "wallet_trades"):
            return []
        snaps = _snaps(tcon, "rang", since, now)
        if not snaps:
            return []
        ent = wallet_entries(wcon, snaps, since, now)
        out = []
        for w, items in ent.items():
            for m, t, o in items:
                b = _snap_at(snaps, w, t)
                if b:
                    out.append({"subject": f"{w}:{m}", "ts": t, "bucket": b, "outcome": o, "resolved_ts": t + WALLET_H})
        return out
    finally:
        for c in (tcon, wcon):
            if c is not None:
                c.close()


GROK_HR = {"kupi": "kupi", "preskoči": "preskoči", "preskoci": "preskoči"}


def _sjena(P, since, now, col):
    lcon = ro(P["league"])
    try:
        if not _has(lcon, "veliki_sjena"):
            return []
        rows = lcon.execute(f"SELECT token, opened_ts, {col}, ret, closed_ts FROM veliki_sjena WHERE profil='pravilo' "
                            "AND opened_ts>=? AND opened_ts<=? ORDER BY opened_ts", (int(since), int(now - 72 * H))).fetchall()
        out = []
        for tok, ts, v, ret, cl in _one_per_day(rows):
            known = ret is not None and cl is not None and cl <= now
            out.append({"subject": tok, "ts": int(ts), "bucket": v, "outcome": int(ret > 0) if known else None,
                        "resolved_ts": int(cl if known else ts + 72 * H)})
        return out
    finally:
        if lcon is not None:
            lcon.close()


def load_midcap_grok(P, since, now):
    rows = _sjena(P, since, now, "grok")
    for r in rows:
        r["bucket"] = GROK_HR.get((r["bucket"] or "").strip().lower(), "bez mišljenja")
    return rows


def load_midcap_zona(P, since, now):
    return _sjena(P, since, now, "band")


LOADERS = {"pouzdanost": load_pouzdanost, "sansa": load_sansa, "hype": load_hype, "kartica": load_kartica,
           "rug": load_rug, "topcheck": load_topcheck, "kol": load_kol, "dokazani": load_dokazani, "rang": load_rang,
           "midcap_grok": load_midcap_grok, "midcap_zona": load_midcap_zona}


# ---------- night snapshots of scores without a history of their own ---------------------------------------------

def snapshot_kol(now, path=None, stats=None):
    """The influencer verdict (ui/kolsummary.verdict_stats(14), the one the board and profile show) per account."""
    if stats is None:
        from ui import kolsummary
        stats = kolsummary.verdict_stats(14)
    items = [(h.lower(), v.get("key"), v.get("h1"), None) for h, v in (stats or {}).items() if v.get("key")]
    return store.log_shown("kol", items, now, path, src="noc")


def snapshot_rang(now, P, path=None):
    wcon = ro(P["wallets"])
    try:
        if not _has(wcon, "copy_rank"):
            return 0
        items = [(t, rang_bucket(s), s, None) for t, s in
                 wcon.execute("SELECT target, score FROM copy_rank WHERE kind='wallet' AND score IS NOT NULL")]
    finally:
        if wcon is not None:
            wcon.close()
    return store.log_shown("rang", items, now, path, src="noc")


def learned_refits(P):
    """{name: newest applied refit ts} from hype.db learn_runs (hype weights per class, the confidence model), for
    the owner page: which learned scores changed when. {} without the table."""
    hcon = ro(P["hype"])
    try:
        if not _has(hcon, "learn_runs"):
            return {}
        return {k: t for k, t in hcon.execute("SELECT klasa, MAX(ts) FROM learn_runs WHERE applied=1 GROUP BY klasa")}
    finally:
        if hcon is not None:
            hcon.close()
