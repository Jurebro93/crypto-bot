"""The shadow book: about a thousand imagined midcap trades a day, so the program can count what works
(18.11., owner: "1000 demo tradeova treba raditi dnevno da bi program mogao naučiti što prolazi, a što ne").

The rule's demo account opens 10-15 trades a day and the explorer (veliki/istrazivac) a few dozen: a group needs weeks
to reach 30 trades. A league demo trade is also heavy (a buy, a sale, exits managed row by row) and the server runs at
85-90 % CPU. A shadow trade is one row in league.db veliki_sjena and a few comparisons per quote the tick already has:
no account, no league trade, nobody can mistake it for money.

What is opened: every candidate of the demo universe, once per completed 15m bar, whatever the rule thinks of it,
in every exit PROFILE that has no open shadow in that token:

  skalp    target +3 % net, stop -4 %      kratko   +6 % / -8 %       uski   +10 % / -8 %
  pravilo  +10 % / -20 % (the live rule)   siroko   +20 % / -20 %

so the same entry is judged under five exits (a paired comparison), at the rule's stake (0.1 SOL) and the REAL
account's cost (the higher of the modelled and the measured round trip, never under replay.RT_FLOOR = 3 %). Each row stores what was known BEFORE the entry:
where the price stood in the 48 h zone (band dno / donja / sredina / vrh / ispod / iznad), whether the 15m bars had
stopped falling, whether the zone was valid and why not, BTC's regime, the macro tag, the dip reason, a holder block or
static risk, Grok's verdict from X, market cap, liquidity, the hour.

How a shadow closes: the level (target, stop) is crossed on one quote, the fill is the NEXT quote of the token (the
live exit also sells at market after it has seen the price; one spiky quote books neither a win nor a loss it could
not have traded). No exit after MAX_H (72 h): closed at the quote, reason "vrijeme". A token that stops being quoted
is closed without a result ("bez_cijene") and counted nowhere.

How it is read (table()): closed rows grouped by one feature and the profile: n, the mean net return, the hit rate
and a 90 % interval computed over TOKEN-DAYS, not trades: a thousand trades in 200 tokens on one day are not a
thousand independent facts (they fall together when the market falls). A cell is spoken of only from MIN_CLUSTERS
token-days. The hour's log line "veliki sjena: ..." and the MCP tool get_shadow_book carry it.

Nothing here decides anything: no rule, cap or real-money gate reads this table. A cell that looks good is a
candidate for the walk-forward test and the owner, not a switch. VEL_SJENA=0 turns the book off.
"""
import os
import time

SIZE_SOL = 0.1
MAX_H = 72
MAX_OPEN = int(os.environ.get("VEL_SJENA_MAX_OPEN", "2000"))
PER_DAY = int(os.environ.get("VEL_SJENA_PER_DAY", "3000"))
ROUNDS = 6                 # shadows of one token in one profile a Zagreb day
FILL_GAP_S = 5             # the fill quote is at least this much newer than the one that crossed the level
KEEP_D = 45
MIN_CLUSTERS = 20
PROFILES = {"skalp": (3.0, 0.04), "kratko": (6.0, 0.08), "uski": (10.0, 0.08), "pravilo": (10.0, 0.20),
            "siroko": (20.0, 0.20)}
BANDS = (("dno", 0.25), ("donja", 0.50), ("sredina", 0.75), ("vrh", 1.0))
FEATURES = ("band", "calm", "zone_ok", "btc", "makro", "dip", "oprez", "grok", "hour6")
SCHEMA = """CREATE TABLE IF NOT EXISTS veliki_sjena (
    id INTEGER PRIMARY KEY AUTOINCREMENT, token TEXT, symbol TEXT, opened_ts INTEGER, entry_px REAL, profil TEXT,
    tp_px REAL, stop_px REAL, rt REAL, pos REAL, band TEXT, calm INTEGER, zone_ok INTEGER, zone_why TEXT, width REAL,
    btc TEXT, makro TEXT, dip TEXT, oprez INTEGER, grok TEXT, mcap REAL, liq REAL, status TEXT, closed_ts INTEGER,
    exit_px REAL, reason TEXT, ret REAL);
CREATE INDEX IF NOT EXISTS veliki_sjena_st ON veliki_sjena (status, token);
CREATE INDEX IF NOT EXISTS veliki_sjena_cl ON veliki_sjena (closed_ts);"""
_ST = {"ready": False, "open": {}, "day": None, "n_day": 0, "clean": 0.0, "err": 0.0}


def on():
    return os.environ.get("VEL_SJENA", "1") != "0"


def reset():
    _ST.update(ready=False, open={}, day=None, n_day=0, clean=0.0, err=0.0)


def _load(con, now):
    """The open shadows into memory, once per process (a deploy loses nothing: they are rows)."""
    if _ST["ready"]:
        return
    con.executescript(SCHEMA)
    _ST["open"] = {}
    for rid, tok, prof, entry, tp, stop, rt, ts in con.execute(
            "SELECT id, token, profil, entry_px, tp_px, stop_px, rt, opened_ts FROM veliki_sjena WHERE status='open'"):
        _ST["open"].setdefault(tok, {})[prof] = {"id": rid, "entry": entry, "tp": tp, "stop": stop, "rt": rt, "ts": ts,
                                                 "pend": None}
    _ST["ready"] = True


def _day(now):
    from veliki import live
    return live._day_start(now)


def band_of(px, z):
    """(band, position in the zone 0..1 or outside) of a price; (None, None) without a zone's edges."""
    lo, hi = (z or {}).get("lo"), (z or {}).get("hi")
    if not lo or not hi or hi <= lo or not px:
        return None, None
    pos = (px - lo) / (hi - lo)
    if pos < 0:
        return "ispod", pos
    for name, top in BANDS:
        if pos <= top:
            return name, pos
    return "iznad", pos


def why_class(why):
    """The zone's refusal as one short word (the full sentence carries numbers that would split the groups)."""
    w = (why or "").lower()
    for key, word in (("preuzak", "uzak"), ("preširok", "sirok"), ("trend", "trend"), ("klizi", "klizi"),
                      ("premalo", "premalo"), ("nema cijene", "bez_cijene")):
        if key in w:
            return word
    return "drugo" if w else None


def levels(px, prof, rt):
    """(target price, stop price) of an entry at px under one exit profile at the round trip rt: the target is NET of
    the cost, the stop a plain share under the entry. The book and everything that trades its profiles (veliki/ucenik)
    take their levels here."""
    from veliki import rule
    tp, stop = PROFILES[prof]
    return rule.tp_price(px, tp, rt, None, {"exit_slip": 0.0}), px * (1 - stop)


def known(tok, q, now, z, b15, prow=None, btc=None, cfg=None, sol=None, size_sol=SIZE_SOL):
    """What the book knows about a candidate BEFORE its entry: the fields of a book row that veliki/nauceno.facts reads
    (band, calm, zone_ok, zone_why, width, btc, makro, dip, oprez, grok) plus the price, the place in the zone, the
    liquidity, the market cap, the name and the cost (rt: the real round trip at size_sol, never under
    replay.RT_FLOOR). None when it is no candidate: no zone edges, no liquidity, a round trip of 50 % or more.
    ONE code path for the row the book stores and for a live prediction (18.11.), so both speak about the same thing."""
    px, liq, url, mcap = (list(q[:4]) + [None] * 4)[:4]
    band, pos = band_of(px, z)
    if band is None or not liq or liq <= 0:
        return None
    from veliki import intra, live, replay, rule
    sol = sol or live._sol()
    c = rule.cost_at(size_sol, liq, sol, rule.fee_side_of(url=url), rule.tx_sol()[0])
    # 18.11.: the real account's cost, never under the measured 3 % (replay.RT_FLOOR): a plus at an imagined cost
    # teaches nothing
    rt = max(c["rt"], rule.demo_rt(size_sol * sol, liq), replay.RT_FLOOR)
    if rt >= 0.5:
        return None
    prow = prow or {}
    g = prow.get("grok") or {}
    grok = None
    if g.get("verdict") and now - float(g.get("ts") or 0) <= 6 * 3600:
        grok = str(g["verdict"]).strip().lower()[:12]
    return {"px": px, "liq": liq, "url": url, "mcap": mcap, "rt": rt, "pos": round(pos, 4), "band": band,
            "symbol": (q[4] if len(q) > 4 else None) or live._sym(tok, q),
            "calm": 1 if intra.calm(b15 or [], cfg)[0] else 0, "zone_ok": 1 if (z or {}).get("ok") else 0,
            "zone_why": why_class((z or {}).get("why")), "width": (z or {}).get("width"),
            "btc": (btc or {}).get("state"), "makro": live._ST.get("makro_tag"),
            "dip": ((prow.get("dip") or {}).get("kind") or None),
            "oprez": 1 if (prow.get("block") or prow.get("risk")) else 0, "grok": grok}


def consider(con, tok, q, now, z, b15, prow=None, btc=None, cfg=None, sol=None):
    """Called once per token per completed 15m bar (live.intra_entries): open a shadow in every profile that has none
    in this token. How many were opened. Never raises."""
    if not on():
        return 0
    try:
        _load(con, now)
        px, liq = (list(q[:2]) + [None] * 2)[:2]
        if band_of(px, z)[0] is None or not liq or liq <= 0:
            return 0
        day = _day(now)
        if _ST["day"] != day:
            _ST["day"] = day
            _ST["n_day"] = con.execute("SELECT COUNT(*) FROM veliki_sjena WHERE opened_ts>=?", (day,)).fetchone()[0]
        held = _ST["open"].setdefault(tok, {})
        free = [p for p in PROFILES if p not in held]
        n_open = sum(len(v) for v in _ST["open"].values())
        if not free or _ST["n_day"] >= PER_DAY or n_open >= MAX_OPEN:
            return 0
        k = known(tok, q, now, z, b15, prow, btc, cfg, sol)
        if k is None:
            return 0
        rt = k["rt"]
        done = dict(con.execute("SELECT profil, COUNT(*) FROM veliki_sjena WHERE token=? AND opened_ts>=? GROUP BY profil",
                                (tok, day)).fetchall())
        n = 0
        for prof in free:
            if done.get(prof, 0) >= ROUNDS:
                continue
            tp_px, stop_px = levels(px, prof, rt)
            cur = con.execute(
                "INSERT INTO veliki_sjena (token, symbol, opened_ts, entry_px, profil, tp_px, stop_px, rt, pos, band, calm, "
                "zone_ok, zone_why, width, btc, makro, dip, oprez, grok, mcap, liq, status) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,"
                "?,?,?,?,?,?,?,?,?,'open')",
                (tok, k["symbol"], int(now), px, prof, tp_px, stop_px, rt, k["pos"], k["band"], k["calm"], k["zone_ok"],
                 k["zone_why"], k["width"], k["btc"], k["makro"], k["dip"], k["oprez"], k["grok"], k["mcap"], liq))
            held[prof] = {"id": cur.lastrowid, "entry": px, "tp": tp_px, "stop": stop_px, "rt": rt, "ts": int(now),
                          "pend": None}
            n += 1
        _ST["n_day"] += n
        return n
    except Exception as e:  # noqa: BLE001 - the book never costs the rule's pass
        _said(f"veliki sjena: ulaz nije zapisan ({type(e).__name__}: {str(e)[:100]})", now)
        return 0


def _said(text, now):
    if now - _ST["err"] > 3600:
        _ST["err"] = now
        print(text, flush=True)


def _close(con, tok, prof, row, px, reason, now):
    from veliki import rule
    ret = rule.net_ret(row["entry"], px, row["rt"]) if px else None
    con.execute("UPDATE veliki_sjena SET status='closed', closed_ts=?, exit_px=?, reason=?, ret=? WHERE id=? AND "
                "status='open'", (int(now), px, reason, ret, row["id"]))
    _ST["open"].get(tok, {}).pop(prof, None)


def mark(con, quotes, now):
    """Every quote of this pass against the open shadows of its token: a crossed level arms the exit, the next quote
    fills it. How many closed. Never raises."""
    if not on():
        return 0
    try:
        _load(con, now)
        n = 0
        for tok, q in (quotes or {}).items():
            rows = _ST["open"].get(tok)
            if not rows or not q or not q[0]:
                continue
            px = q[0]
            for prof, r in list(rows.items()):
                if r["pend"]:
                    if now - r["pend"][1] >= FILL_GAP_S:
                        _close(con, tok, prof, r, px, r["pend"][0], now)
                        n += 1
                    continue
                if px <= r["stop"]:
                    r["pend"] = ("stop", now)
                elif px >= r["tp"]:
                    r["pend"] = ("tp", now)
                elif now - r["ts"] >= MAX_H * 3600:
                    _close(con, tok, prof, r, px, "vrijeme", now)
                    n += 1
        if now - _ST["clean"] >= 6 * 3600:
            _ST["clean"] = now
            cleanup(con, now)
        return n
    except Exception as e:  # noqa: BLE001
        _said(f"veliki sjena: izlazi nisu obrađeni ({type(e).__name__}: {str(e)[:100]})", now)
        return 0


def cleanup(con, now):
    """Shadows of a token nobody quotes any more are closed without a result; old closed rows go."""
    old = int(now) - (MAX_H + 24) * 3600
    for rid, tok, prof in con.execute("SELECT id, token, profil FROM veliki_sjena WHERE status='open' AND opened_ts<?",
                                      (old,)).fetchall():
        con.execute("UPDATE veliki_sjena SET status='closed', closed_ts=?, reason='bez_cijene' WHERE id=?", (int(now), rid))
        _ST["open"].get(tok, {}).pop(prof, None)
    con.execute("DELETE FROM veliki_sjena WHERE status='closed' AND closed_ts<?", (int(now) - KEEP_D * 86400,))


def _group(row, by):
    if by == "hour6":
        h = time.gmtime(row["opened_ts"]).tm_hour
        return f"{h // 6 * 6:02d}-{h // 6 * 6 + 6:02d} UTC"
    v = row[by]
    if by in ("calm", "zone_ok", "oprez"):
        return {"calm": ("još pada", "smirilo se"), "zone_ok": ("zona nevaljana", "zona valjana"),
                "oprez": ("bez opreza", "oprez")}[by][1 if v else 0]
    return str(v) if v not in (None, "") else "nepoznato"


def table(con, now, days=7, by="band", profil=None):
    """[{"group", "profil", "n", "clusters", "ev", "hit", "lo", "hi"}] of the closed shadows of the last `days`
    (ev / lo / hi: net return as fractions; lo / hi the 90 % interval over token-days, None under 2 clusters),
    the most trades first."""
    if by not in FEATURES:
        raise ValueError(f"nepoznata značajka {by}; postoje: {', '.join(FEATURES)}")
    con.executescript(SCHEMA)
    cols = ("token", "opened_ts", "profil", "ret", "band", "calm", "zone_ok", "btc", "makro", "dip", "oprez", "grok")
    cells = {}
    for r in con.execute(f"SELECT {', '.join(cols)} FROM veliki_sjena WHERE status='closed' AND ret IS NOT NULL AND "
                         "closed_ts>=?" + (" AND profil=?" if profil else ""),
                         (int(now) - days * 86400, *((profil,) if profil else ()))):
        row = dict(zip(cols, r))
        c = cells.setdefault((_group(row, by), row["profil"]), {"rets": [], "cl": {}})
        c["rets"].append(row["ret"])
        c["cl"].setdefault((row["token"], row["opened_ts"] // 86400), []).append(row["ret"])
    out = []
    for (grp, prof), c in cells.items():
        n = len(c["rets"])
        means = [sum(v) / len(v) for v in c["cl"].values()]
        k = len(means)
        ev = sum(c["rets"]) / n
        lo = hi = None
        if k >= 2:
            m = sum(means) / k
            sd = (sum((x - m) ** 2 for x in means) / (k - 1)) ** 0.5
            lo, hi = m - 1.645 * sd / k ** 0.5, m + 1.645 * sd / k ** 0.5
        out.append({"group": grp, "profil": prof, "n": n, "clusters": k, "ev": ev,
                    "hit": sum(1 for x in c["rets"] if x > 0) / n, "lo": lo, "hi": hi})
    return sorted(out, key=lambda x: -x["n"])


def counts(con, now):
    con.executescript(SCHEMA)
    d0 = _day(now)
    opened = con.execute("SELECT COUNT(*) FROM veliki_sjena WHERE opened_ts>=?", (d0,)).fetchone()[0]
    closed = con.execute("SELECT COUNT(*) FROM veliki_sjena WHERE status='closed' AND ret IS NOT NULL AND closed_ts>=?",
                         (d0,)).fetchone()[0]
    n_open = con.execute("SELECT COUNT(*) FROM veliki_sjena WHERE status='open'").fetchone()[0]
    toks = con.execute("SELECT COUNT(DISTINCT token) FROM veliki_sjena WHERE opened_ts>=?", (d0,)).fetchone()[0]
    return {"opened": opened, "closed": closed, "open": n_open, "tokens": toks}


GATED_SQL = "(COALESCE(makro, '') LIKE 'risk_off%' OR COALESCE(btc, '') = 'slobodan_pad')"


def gated_today(con, now):
    """23.11.: today's shadows opened while a market gate held real money (the macro tag risk_off or BTC's free fall
    at the entry: the row's own facts). Real money would not have entered them; nauceno's proof leaves them out."""
    con.executescript(SCHEMA)
    return con.execute(f"SELECT COUNT(*) FROM veliki_sjena WHERE opened_ts>=? AND {GATED_SQL}",
                       (_day(now),)).fetchone()[0]


def _cell(c):
    return (f"{c['group']} × {c['profil']}: n={c['n']} ({c['clusters']} token-dana), prosjek {c['ev']:+.1%}, pogodak "
            f"{c['hit']:.0%}, raspon 90 % [{c['lo']:+.1%}; {c['hi']:+.1%}]")


def line(con, now, days=7):
    """The hour's line: today's counts and, per place in the zone and exit profile, the best and the worst cell that
    has enough token-days."""
    if not on():
        return "veliki sjena: isključena (VEL_SJENA=0)"
    n = counts(con, now)
    g = gated_today(con, now)
    head = (f"veliki sjena (zamišljeni tradeovi, 5 izlaza po ulazu): danas otvoreno {n['opened']} u {n['tokens']} tokena"
            + (f" (od toga {g} u filtru tržišta: risk-off / BTC slobodan pad, pravi novac bi stajao)" if g else "")
            + f", zatvoreno {n['closed']}, sada otvorenih {n['open']}")
    cells = [c for c in table(con, now, days) if c["clusters"] >= MIN_CLUSTERS and c["lo"] is not None]
    if not cells:
        return head + f"; ocjena po mjestu u zoni i izlazu: premalo podataka (treba {MIN_CLUSTERS} token-dana po ćeliji)"
    best = max(cells, key=lambda c: c["lo"])
    worst = min(cells, key=lambda c: c["hi"])
    pos = sum(1 for c in cells if c["lo"] > 0)
    return (head + f"; zadnjih {days} d, {len(cells)} ćelija s dovoljno podataka, s donjom granicom iznad nule: {pos}; "
            f"najbolja {_cell(best)}; najgora {_cell(worst)}")


def mcp(args=None):
    """get_shadow_book: the counts and the table by one feature (see table())."""
    from league import store as lstore
    args = args or {}
    now = time.time()
    by = str(args.get("by") or "band")
    days = max(1, min(int(args.get("days") or 7), KEEP_D))
    con = lstore.connect()
    demo = None
    try:
        rows = table(con, now, days, by, args.get("profile") or None)
        n = counts(con, now)
        try:   # 18.11.: the demo account that tests the learner's rule forward (veliki/ucenik)
            from veliki import ucenik
            demo = ucenik.summary(con, now)
        except Exception:  # noqa: BLE001 - the book's table never fails for it
            demo = None
    except ValueError as e:
        return {"error": str(e)}
    finally:
        con.close()
    for r in rows:
        for k in ("ev", "hit", "lo", "hi"):
            r[k] = None if r[k] is None else round(r[k], 4)
        r["enough"] = r["clusters"] >= MIN_CLUSTERS
    try:
        from veliki import nauceno
        learned = nauceno.summary()
    except Exception:  # noqa: BLE001
        learned = None
    if demo is not None:
        learned = {**(learned or {}), "demo": demo}
    return {"today": n, "days": days, "by": by, "features": list(FEATURES), "learned": learned,
            "profiles": {k: {"target_net_pct": v[0], "stop_pct": v[1] * 100} for k, v in PROFILES.items()},
            "rows": rows[:int(args.get("limit") or 60)],
            "read_me": ("Imagined trades only: no account, no money. ev / lo / hi are net returns after the real round "
                        "trip; lo / hi is a 90 % interval over token-days. A cell is evidence only when enough is true "
                        f"({MIN_CLUSTERS} token-days) AND it survives a later out-of-sample check; with ~45 cells a few "
                        "look good by chance.")}
