"""Tjedna rotacija novčanika u Helius webhooku i dnevni batch transfera (27.11.2026., vlasnik: "više znanja za isti
trošak"; Helius ostaje na istom planu, 10M kredita mjesečno, a webhook novčanika je najveća stavka: ~92k događaja dnevno
za 300 novčanika, 1 kredit po isporučenom događaju).

Rotacija (rotate(), jednom tjedno, noću 01-06 Zagreb, run_kol.py noćni korak cmd_rotacija)
  Iz trenutnog skupa webhooka (kol.db kv chain_hook) izlaze novčanici koji u zadnjih window_d (14) dana nisu imali
  KORISNU kupnju, a u webhooku su barem min_age_d (7) dana (rot_seen, upisuje kol/chainwatch.sync). Korisno je bilo što
  od ovoga (useful(); izvori su naše baze, samo čitanje):
    insajderi.db i2_part        kupio prije pumpe / prodao u pumpu (bought_before / sold_into) u prozoru
    insajderi.db ik_predpoziv   kupio prije poziva influencera (called = 1)
    early.db preshill_buys      kupio prije shilla (kol/preshill)
    early.db early_buyers       rani kupac pumpanog tokena (kol/groupdisc)
    kol.db insiders             kupio prije KOL poziva (kol/insiders)
    wallets.db copy_rank        dokazan i kopirljiv u profitu (wallets/rang, ocjena >= min_copy; kopija.py ga koristi)
    potvrđena grupa / osoba     i2_pp prije_pumpe potvrđen, i2_groups potvrđen, ik_wallets potvrđen,
                                preshill_wallets confirmed, early.db group_list (novčanici) kvalitetna
  Nikad ne izlaze (protected()): vlasnikovi prikvačeni (chain.rotacija.pinned i kol.db kv rot_pinned), praćeni u ligi
  (league.db follows, svaki igrač, i vlasnik), dokazani (wallets/dokazani), povezani s osobom / influencerom (kol_ids,
  kol_wallets, ik_wallets), vrh insajdera (prvih protect_insajderi_top iz insajderi/live.webhook_wallets i
  kol/precall.webhook_wallets).
  Najviše cap_share (20 %) skupa tjedno, i nikad više nego što ima zamjena. Prvo izlaze najskuplji (najviše događaja
  u hype.db chain_trades u prozoru: svaki događaj je kredit), pa najstariji. Zamjene (candidates()), naizmjence po
  izvoru: insajderi (pp_live kandidati, bundle, i2_smart), wallets/povijest otkriće (copy_rank dokazani i kopirljivi
  koji nisu u skupu), groupdisc / preshill (kvalitetne grupe, potvrđeni i kandidati), bez loših oznaka i botova.

  NIŠTA SE NE BRIŠE: ovaj modul nema nijedan DELETE. Rotacija mijenja samo koje novčanike webhook gleda: izbačeni
  dobije stanje 'parked' (rot_state), svaka promjena je redak u rot_log (tko, kamo, zašto), svaki prolaz redak u
  rot_runs. Tradeovi, transferi, oznake i PnL ostaju. Parkiran novčanik se vraća (returns(), svaku noć) čim se u
  batch podacima pojavi korisna kupnja nakon parkiranja (npr. kupio prije pumpe): stanje 'returned', ide u webhook.
  Izvor koji se ne može pročitati (zaključana baza, kvar) zaustavlja cijeli prolaz: bolje tjedan bez rotacije nego
  izbaciti dobar novčanik zbog rupe u podacima.

Transferi (transfers_batch(), svaku noć)
  27.11.: webhook više ne traži TRANSFER (samo SWAP, kol/config.json chain.types). Transferi (izvori financiranja,
  primljeni tokeni) dohvaćaju se jednom dnevno samo za novčanike kojima trebaju (need_list(): osobe (kol_ids u skupu,
  ik_wallets), vrh insajdera, nove zamjene iz rotacije), Helius getTransactionsForAddress (wallets/rpc._rpc, stranica
  od 100 = 10 kredita, wallets/rpc.credits_for), inkrementalno od zadnjeg dohvata, najviše credits_day (15k) kredita
  dnevno (kol.db tb_days). Redci idu u hype.db chain_transfers (isti oblik kao iz webhooka), pa kol/traces.py i
  events/sources.py rade kao prije. Krediti se u usage.db broje pod skriptom "transferi novčanika".
"""
import datetime as dt
import json
import os
import sqlite3
import time

from kol import store as kstore

DEFAULT = {"on": True, "every_d": 7, "window_d": 14, "min_age_d": 7, "cap_share": 0.2, "protect_insajderi_top": 45,
           "pinned": [], "min_copy": 35, "per_source": 200, "night_only": True}
TDEFAULT = {"on": True, "credits_day": 15000, "max_pages": 2, "lookback_d": 14, "min_gap_h": 20, "min_sol": 0.05,
            "token_accounts": "balanceChanged", "top_insajderi": 45, "new_days": 14, "max_wallets": 400,
            "person_max": 200}
SCRIPT = "transferi novčanika"
PAGE_CREDITS = 10
HYPE_DB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "hype.db")
FORCED = ("in", "returned")

SCHEMA = """
CREATE TABLE IF NOT EXISTS rot_seen (wallet TEXT PRIMARY KEY, first_ts INTEGER, last_ts INTEGER);
CREATE TABLE IF NOT EXISTS rot_state (wallet TEXT PRIMARY KEY, state TEXT, since INTEGER, reason TEXT, src TEXT,
    run TEXT, updated INTEGER);
CREATE TABLE IF NOT EXISTS rot_log (ts INTEGER, run TEXT, wallet TEXT, action TEXT, reason TEXT, src TEXT,
    events INTEGER);
CREATE INDEX IF NOT EXISTS rot_log_wallet ON rot_log (wallet, ts);
CREATE TABLE IF NOT EXISTS rot_runs (run TEXT PRIMARY KEY, ts INTEGER, n_set INTEGER, n_judged INTEGER,
    n_useful INTEGER, n_protected INTEGER, n_idle INTEGER, n_out INTEGER, n_in INTEGER, n_return INTEGER, cap INTEGER,
    status TEXT, detail TEXT);
CREATE TABLE IF NOT EXISTS tb_fetched (wallet TEXT PRIMARY KEY, ts INTEGER, newest_ts INTEGER, credits INTEGER,
    n_tx INTEGER, n_rows INTEGER, complete INTEGER, why TEXT);
CREATE TABLE IF NOT EXISTS tb_days (day TEXT PRIMARY KEY, credits INTEGER, wallets INTEGER, rows INTEGER,
    ts INTEGER);
"""


class SourceError(Exception):
    """A source database exists but cannot be read: the rotation pass stops (never rotates on a hole in the data)."""


def ensure(con):
    con.executescript(SCHEMA)


def config(cfg=None):
    c = dict(DEFAULT, **((cfg or {}).get("rotacija") or {}))
    t = dict(TDEFAULT, **((cfg or {}).get("transferi") or {}))
    return c, t


def paths(over=None):
    """Database paths (tests pass their own)."""
    out = {"kol": kstore.DB, "hype": os.environ.get("HYPE_DB") or HYPE_DB}
    try:
        from insajderi import store as istore
        out["insajderi"] = istore.db_path()
    except Exception:  # noqa: BLE001
        out["insajderi"] = None
    try:
        from kol import groupdisc as gd
        out["early"] = gd.db_path()
    except Exception:  # noqa: BLE001
        out["early"] = None
    try:
        from wallets import store as wstore
        out["wallets"] = wstore.DB
    except Exception:  # noqa: BLE001
        out["wallets"] = None
    try:
        from league import store as lstore
        out["league"] = lstore.DB
    except Exception:  # noqa: BLE001
        out["league"] = None
    out.update(over or {})
    return out


def _ro(path):
    if not path or not os.path.exists(path):
        return None
    try:
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=30)
    except sqlite3.Error as e:
        raise SourceError(f"{os.path.basename(path)}: {e}") from e
    return con


def _q(path, sql, args=()):
    """Rows of a read-only query; [] when the file or the table does not exist (a fresh install), SourceError when
    the database is there but cannot be read (locked, corrupt)."""
    con = _ro(path)
    if con is None:
        return []
    try:
        return con.execute(sql, args).fetchall()
    except sqlite3.OperationalError as e:
        if "no such table" in str(e) or "no such column" in str(e):
            return []
        raise SourceError(f"{os.path.basename(path)}: {e}") from e
    except sqlite3.Error as e:
        raise SourceError(f"{os.path.basename(path)}: {e}") from e
    finally:
        con.close()


def _q_in(path, sql, wallets, args=()):
    """sql holds one {in} for the wallet list; run in chunks of 400."""
    ws, out = sorted(wallets), []
    for i in range(0, len(ws), 400):
        ch = ws[i:i + 400]
        out += _q(path, sql.format(**{"in": ",".join("?" * len(ch))}), (*args, *ch))
    return out


def _members(path, sql):
    out = set()
    for (m,) in _q(path, sql):
        try:
            ms = json.loads(m or "[]")
        except ValueError:
            continue
        out.update(x for x in ms if isinstance(x, str))
    return out


# ---------- what is useful ----------------------------------------------------------------------------------------------

def useful(p, wallets, since, min_copy=35):
    """{wallet: reason} of `wallets` with a useful buy since `since` (or a standing confirmation). Raises SourceError."""
    ws = set(wallets)
    out = {}

    def mark(rows, why):
        for r in rows:
            w = r[0]
            if w in ws and w not in out:
                out[w] = why
    if not ws:
        return out
    mark(_q_in(p.get("insajderi"), "SELECT wallet FROM i2_part WHERE buy_ts >= ? AND (bought_before = 1 OR sold_into = 1) "
               "AND wallet IN ({in})", ws, (int(since),)), "kupio prije pumpe (insajderi)")
    mark(_q_in(p.get("insajderi"), "SELECT wallet FROM ik_predpoziv WHERE buy_ts >= ? AND called = 1 AND wallet IN ({in})",
               ws, (int(since),)), "kupio prije poziva influencera")
    mark(_q_in(p.get("early"), "SELECT wallet FROM preshill_buys WHERE buy_ts >= ? AND wallet IN ({in})", ws, (int(since),)),
         "kupio prije shilla (preshill)")
    mark(_q_in(p.get("early"), "SELECT wallet FROM early_buyers WHERE first_buy_ts >= ? AND wallet IN ({in})", ws,
               (int(since),)), "rani kupac pumpe (groupdisc)")
    mark(_q_in(p.get("kol"), "SELECT wallet FROM insiders WHERE bought_ts >= ? AND bought_ts < call_ts AND wallet IN ({in})",
               ws, (int(since),)), "kupio prije KOL poziva")
    mark([(w,) for w in copyable(p, min_copy)], "kopirljiv u profitu (rang)")
    mark([(w,) for w in confirmed(p)], "u potvrđenoj grupi / osobi")
    return out


def copyable(p, min_copy=35):
    rows = _q(p.get("wallets"), "SELECT target, score FROM copy_rank WHERE kind = 'wallet' AND proven = 1 AND copyable = 1 "
              "AND score >= ? ORDER BY score DESC", (float(min_copy),))
    return [w for w, _s in rows]


def confirmed(p):
    out = _members(p.get("insajderi"), "SELECT members FROM i2_pp WHERE cls = 'prije_pumpe' AND confirmed_ts IS NOT NULL")
    out |= _members(p.get("insajderi"), "SELECT members FROM i2_groups WHERE confirmed_ts IS NOT NULL")
    out |= _members(p.get("insajderi"), "SELECT members FROM ik_wallets WHERE cls = 'potvrđen'")
    out |= {w for (w,) in _q(p.get("early"), "SELECT wallet FROM preshill_wallets WHERE status = 'confirmed'")}
    out |= _members(p.get("early"), "SELECT members FROM group_list WHERE kind = 'wallet' AND grade = 'quality'")
    return out


# ---------- who is never rotated out ------------------------------------------------------------------------------------

def pinned(con, c):
    out = set(c.get("pinned") or [])
    try:
        row = con.execute("SELECT value FROM kv WHERE key = 'rot_pinned'").fetchone()
        if row:
            out |= set(json.loads(row[0] or "[]"))
    except (sqlite3.Error, ValueError):
        pass
    return out


def insajderi_top(n, live_fn=None, precall_fn=None):
    """The insider ranks the webhook gives first (confirmed pump groups, bundles), the first n, and the pre-call set."""
    out = []
    try:
        if live_fn is None:
            from insajderi import live as _i2
            live_fn = _i2.webhook_wallets
        out += list(live_fn(10_000))[:int(n)]
    except Exception:  # noqa: BLE001 - [] off / no db
        pass
    try:
        if precall_fn is None:
            from kol import precall as _pre
            precall_fn = _pre.webhook_wallets
        out += list(precall_fn())
    except Exception:  # noqa: BLE001
        pass
    return out


def protected(con, p, c, live_fn=None, precall_fn=None):
    """{wallet: why} of wallets the rotation never takes out. Raises SourceError."""
    out = {}

    def add(ws, why):
        for w in ws:
            out.setdefault(w, why)
    add(pinned(con, c), "vlasnik prikvačio")
    add([w for (w,) in _q(p.get("league"), "SELECT DISTINCT target FROM follows WHERE kind = 'wallet' AND active = 1")],
        "praćen u ligi")
    try:
        from wallets import dokazani as _dok
        add(_dok.current(p.get("wallets")), "dokazan")
    except ImportError:
        pass
    add([w for (w,) in _q(p.get("wallets"), "SELECT wallet FROM dokazani WHERE passed = 1")], "dokazan")
    add([w for (w,) in _q(p.get("kol"), "SELECT wallet FROM kol_ids")], "osoba (KOL ljestvica)")
    add([w for (w,) in _q(p.get("kol"), "SELECT wallet FROM kol_wallets")], "osoba (KOL novčanik)")
    add(_members(p.get("insajderi"), "SELECT members FROM ik_wallets"), "osoba / influencer")
    add(insajderi_top(c["protect_insajderi_top"], live_fn, precall_fn), "vrh insajdera")
    return out


# ---------- replacements ------------------------------------------------------------------------------------------------

def candidates(p, c, exclude, live_fn=None):
    """[(wallet, src)] best first, one source after another in turn (insajderi, povijest, groupdisc), without the
    excluded, bad labels and bots. Raises SourceError."""
    per = int(c["per_source"])
    ins = []
    try:
        if live_fn is None:
            from insajderi import live as _i2
            live_fn = _i2.webhook_wallets
        ins += list(live_fn(10_000))
    except Exception:  # noqa: BLE001
        pass
    ins += [w for (w,) in _q(p.get("insajderi"), "SELECT wallet FROM i2_smart ORDER BY score DESC LIMIT ?", (per * 2,))]
    pov = copyable(p, c["min_copy"])
    grp = [w for (w,) in _q(p.get("early"), "SELECT wallet FROM preshill_wallets WHERE status IN ('confirmed', 'candidate') "
                                           "ORDER BY (status = 'confirmed') DESC, score DESC LIMIT ?", (per * 2,))]
    grp += sorted(_members(p.get("early"), "SELECT members FROM group_list WHERE kind = 'wallet' AND grade = 'quality'"))
    lists = [("insajderi", ins), ("povijest", pov), ("groupdisc", grp)]
    allw = {w for _s, ws in lists for w in ws} - set(exclude)
    bad = _bad(p, allw)
    try:
        from kol import chainwatch
        bad |= chainwatch.too_busy(allw, p.get("wallets"))
    except Exception:  # noqa: BLE001
        pass
    seen, out, idx = set(exclude) | bad, [], [0] * len(lists)
    per_src = {s: 0 for s, _ws in lists}
    while True:
        moved = False
        for i, (src, ws) in enumerate(lists):
            while idx[i] < len(ws) and per_src[src] < per:
                w = ws[idx[i]]
                idx[i] += 1
                if w and w not in seen:
                    seen.add(w)
                    out.append((w, src))
                    per_src[src] += 1
                    moved = True
                    break
        if not moved:
            return out


def _bad(p, wallets):
    try:
        from wallets import store as wstore
        bad_labels = wstore.BAD_LABELS
    except ImportError:
        bad_labels = {"bot", "rugger", "bundler", "dev", "cex", "mev", "sniper"}
    out = set()
    for w, lab in _q_in(p.get("wallets"), "SELECT wallet, labels FROM wallets WHERE wallet IN ({in})", wallets):
        try:
            if set(json.loads(lab or "[]")) & set(bad_labels):
                out.add(w)
        except ValueError:
            pass
    return out


# ---------- the webhook's view ------------------------------------------------------------------------------------------

def webhook_view(con):
    """(parked set, forced list) for kol/chainwatch.wanted: parked wallets stay out of the share groups, the rotation's
    replacements (in / returned) go in before them. Never raises (an old kol.db: empty)."""
    try:
        parked = {w for (w,) in con.execute("SELECT wallet FROM rot_state WHERE state = 'parked'")}
        forced = [w for (w,) in con.execute("SELECT wallet FROM rot_state WHERE state IN ('in', 'returned') "
                                            "ORDER BY since, wallet")]
    except sqlite3.Error:
        return set(), []
    return parked, forced


def note_seen(con, wallets, now):
    """kol/chainwatch.sync: when each wallet entered the webhook (first_ts kept) and was last in it."""
    try:
        ensure(con)
        con.executemany("INSERT INTO rot_seen VALUES (?, ?, ?) ON CONFLICT (wallet) DO UPDATE SET last_ts = excluded.last_ts",
                        [(w, int(now), int(now)) for w in wallets])
    except sqlite3.Error:
        pass


def current_set(con):
    try:
        row = con.execute("SELECT value FROM kv WHERE key = 'chain_hook'").fetchone()
        return list(json.loads(row[0]).get("wallets") or []) if row else []
    except (sqlite3.Error, ValueError, AttributeError):
        return []


def _first_seen(con, p, wallets):
    """{wallet: first ts in the webhook}: rot_seen, or for a wallet seen before rot_seen existed its oldest
    hype.db chain_trades row (the webhook is the only writer of that table)."""
    have = dict(con.execute("SELECT wallet, first_ts FROM rot_seen"))
    out = {w: have[w] for w in wallets if w in have}
    for w, ts in _q_in(p.get("hype"), "SELECT wallet, MIN(ts) FROM chain_trades WHERE wallet IN ({in}) GROUP BY wallet",
                       wallets):
        if ts and (w not in out or ts < out[w]):
            out[w] = int(ts)
    return out


def _events(p, wallets, since):
    return {w: n for w, n in _q_in(p.get("hype"), "SELECT wallet, COUNT(*) FROM chain_trades WHERE ts >= ? AND wallet IN ({in}) "
                                                  "GROUP BY wallet", wallets, (int(since),))}


def _set_state(con, w, state, now, reason, src, run):
    con.execute("""INSERT INTO rot_state VALUES (?,?,?,?,?,?,?) ON CONFLICT (wallet) DO UPDATE SET state = excluded.state,
                   since = excluded.since, reason = excluded.reason, src = excluded.src, run = excluded.run,
                   updated = excluded.updated""", (w, state, int(now), reason, src, run, int(now)))


def _log(con, now, run, w, action, reason, src, events=None):
    con.execute("INSERT INTO rot_log VALUES (?,?,?,?,?,?,?)", (int(now), run, w, action, reason, src, events))


def returns(con, cfg=None, now=None, p=None, log=print):
    """Parked wallets with a useful buy after they were parked go back (state 'returned'). -> how many."""
    ensure(con)
    c, _t = config(cfg)
    now = int(now or time.time())
    p = p or paths()
    rows = con.execute("SELECT wallet, since FROM rot_state WHERE state = 'parked'").fetchall()
    if not rows:
        return 0
    oldest = min(s for _w, s in rows)
    got = useful(p, [w for w, _s in rows], oldest, c["min_copy"])
    run = f"r{now}"
    n = 0
    for w, since in rows:
        why = got.get(w)
        if not why:
            continue
        if why.startswith(("kopirljiv", "u potvrđenoj")) or _later(p, w, since):
            _set_state(con, w, "returned", now, why, "povratak", run)
            _log(con, now, run, w, "return", why, "povratak")
            n += 1
    con.commit()
    if n:
        log(f"rotacija: {n} parkiranih novčanika vraćeno u webhook (korisna kupnja nakon parkiranja)")
    return n


def _later(p, w, since):
    """The useful buy really came after the wallet was parked (useful() was asked from the oldest parking)."""
    return bool(useful(p, [w], since).get(w))


def night_ok(now=None):
    try:
        from ops import heavy
        return heavy.night_now(dt.datetime.fromtimestamp(now, dt.timezone.utc) if now else None)
    except Exception:  # noqa: BLE001
        return True


def rotate(con, cfg=None, now=None, p=None, log=print, force=False, live_fn=None, precall_fn=None):
    """The weekly pass. -> summary dict (status ok / nije_na_redu / izvan_noci / prazno / greska_izvora / iskljuceno)."""
    ensure(con)
    c, _t = config(cfg)
    now = int(now or time.time())
    p = p or paths()
    if not c.get("on") and not force:
        return {"status": "iskljuceno"}
    last = con.execute("SELECT MAX(ts) FROM rot_runs WHERE status = 'ok'").fetchone()[0]
    if not force and last and now - last < c["every_d"] * 86400 - 3600:
        return {"status": "nije_na_redu", "zadnja": last}
    if not force and c.get("night_only") and not night_ok(now):
        return {"status": "izvan_noci"}
    run = f"w{now}"
    cur = current_set(con)
    if not cur:
        return {"status": "prazno"}
    try:
        n_ret = returns(con, cfg, now, p, log=log)
        prot = protected(con, p, c, live_fn, precall_fn)
        first = _first_seen(con, p, cur)
        judged = [w for w in cur if w not in prot and first.get(w, now) <= now - c["min_age_d"] * 86400]
        since = now - c["window_d"] * 86400
        good = useful(p, judged, since, c["min_copy"])
        idle = [w for w in judged if w not in good]
        ev = _events(p, idle, since)
        idle.sort(key=lambda w: (-ev.get(w, 0), first.get(w, now), w))
        st = dict(con.execute("SELECT wallet, state FROM rot_state"))
        exclude = set(cur) | {w for w, s in st.items() if s in ("parked",) + FORCED} | set(prot)
        cands = candidates(p, c, exclude, live_fn)
    except SourceError as e:
        con.execute("INSERT OR REPLACE INTO rot_runs VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (run, now, len(cur), None, None, None, None, 0, 0, 0, None, "greska_izvora", str(e)[:300]))
        con.commit()
        log(f"rotacija: izvor nečitljiv ({e}), ovaj tjedan bez rotacije")
        return {"status": "greska_izvora", "greska": str(e)}
    cap = int(len(cur) * float(c["cap_share"]))
    n_out = min(len(idle), cap, len(cands) + n_ret)
    outs = idle[:n_out]
    ins = cands[:max(0, n_out - n_ret)]
    for w in outs:
        why = f"bez korisne kupnje {c['window_d']} d ({ev.get(w, 0)} događaja)"
        _set_state(con, w, "parked", now, why, "rotacija", run)
        _log(con, now, run, w, "out", why, "rotacija", ev.get(w, 0))
    for w, src in ins:
        _set_state(con, w, "in", now, f"zamjena iz {src}", src, run)
        _log(con, now, run, w, "in", f"zamjena iz {src}", src)
    detail = {"izvori_zamjena": {s: sum(1 for _w, x in ins if x == s) for s in ("insajderi", "povijest", "groupdisc")},
              "dogadaja_izbacenih_14d": sum(ev.get(w, 0) for w in outs)}
    con.execute("INSERT OR REPLACE INTO rot_runs VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (run, now, len(cur), len(judged), len(good), len(prot), len(idle), len(outs), len(ins), n_ret, cap, "ok",
                 json.dumps(detail, ensure_ascii=False)))
    con.commit()
    out = {"status": "ok", "run": run, "skup": len(cur), "ocijenjeno": len(judged), "korisni": len(good),
           "zasticeni": len(prot), "bez_koristi": len(idle), "van": len(outs), "unutra": len(ins), "povratak": n_ret,
           "strop": cap, **detail}
    log(f"rotacija: skup {len(cur)}, zaštićeno {len(prot)}, ocijenjeno {len(judged)}, korisnih {len(good)}, "
        f"bez koristi {len(idle)}; van {len(outs)} (strop {cap}), unutra {len(ins)} + {n_ret} povrataka")
    return out


# ---------- the daily transfer batch -------------------------------------------------------------------------------------

def need_list(con, p, t, now, live_fn=None):
    """[(wallet, why)] that need their transfers, best first: persons (KOL wallets in the webhook, influencer
    clusters), the top insiders, the rotation's new replacements. Wallets fetched within min_gap_h are left out."""
    cur = set(current_set(con))
    out, seen = [], set()

    def add(ws, why, limit=None):
        k = 0
        for w in ws:
            if limit is not None and k >= limit:
                break
            if w and w not in seen:
                seen.add(w)
                out.append((w, why))
                k += 1
    try:
        kids = [w for (w,) in con.execute("SELECT wallet FROM kol_ids")]
    except sqlite3.Error:
        kids = []
    add([w for w in kids if w in cur], "osoba (KOL)")
    try:
        add(sorted(_members(p.get("insajderi"), "SELECT members FROM ik_wallets ORDER BY score DESC")), "osoba (grupiranje)",
            int(t["person_max"]))
    except SourceError:
        pass
    add(insajderi_top(t["top_insajderi"], live_fn, precall_fn=lambda: []), "vrh insajdera")
    try:
        add([w for (w,) in con.execute("SELECT wallet FROM rot_state WHERE state IN ('in', 'returned') AND since >= ? "
                                       "ORDER BY since DESC", (int(now) - int(t["new_days"]) * 86400,))], "nova zamjena")
    except sqlite3.Error:
        pass
    fresh = {w for (w,) in con.execute("SELECT wallet FROM tb_fetched WHERE ts >= ?", (int(now) - int(t["min_gap_h"]) * 3600,))}
    return [(w, why) for w, why in out if w not in fresh][:int(t["max_wallets"])]


def _day(now):
    return time.strftime("%Y-%m-%d", time.gmtime(int(now)))


def spent_today(con, now):
    row = con.execute("SELECT credits FROM tb_days WHERE day = ?", (_day(now),)).fetchone()
    return int(row[0]) if row else 0


def fetch_page(wallet, since_ts, token, t):
    """One getTransactionsForAddress page (newest first) -> (txs, next token, credits paid; 0 when from the cache)."""
    from wallets import rpc
    flt = {"status": "succeeded", "blockTime": {"gt": int(since_ts)}}
    if t.get("token_accounts"):
        flt["tokenAccounts"] = t["token_accounts"]
    opts = {"transactionDetails": "full", "encoding": "jsonParsed", "maxSupportedTransactionVersion": 1,
            "limit": rpc.PAGE, "sortOrder": "desc", "filters": flt}
    if token:
        opts["paginationToken"] = token
    res, cached = rpc._rpc("getTransactionsForAddress", [wallet, opts])
    data = (res or {}).get("data") or []
    return data, (res or {}).get("paginationToken"), 0 if cached else rpc.credits_for(len(data))


def tx_rows(txs, wallet, min_sol=0.05):
    """Raw jsonParsed transactions -> chain_transfers rows (sig, src, dst, mint, amount, ts) touching `wallet`:
    token transfers (insajderi/kolwallets.token_moves) and plain SOL transfers ('SOL', kolwallets.sol_moves)."""
    from insajderi import kolwallets as kw
    out = []
    for tx in txs or []:
        try:
            for sig, ts, s, d, amt, m in kw.token_moves(tx, None):
                if wallet in (s, d):
                    out.append((sig, s, d, m, float(amt), int(ts)))
            for sig, ts, s, d, sol in kw.sol_moves(tx, min_sol):
                if wallet in (s, d):
                    out.append((sig, s, d, "SOL", float(sol), int(ts)))
        except (KeyError, TypeError, ValueError, IndexError):
            continue
    return out


def transfers_batch(con, cfg=None, now=None, p=None, fetch=None, log=print, live_fn=None):
    """The day's transfer fetch within credits_day. -> {wallets, credits, rows, left}."""
    ensure(con)
    _c, t = config(cfg)
    now = int(now or time.time())
    p = p or paths()
    if not t.get("on"):
        return {"status": "iskljuceno"}
    fetch = fetch or fetch_page
    left = int(t["credits_day"]) - spent_today(con, now)
    todo = need_list(con, p, t, now, live_fn)
    worst = int(t["max_pages"]) * PAGE_CREDITS
    rows_all, credits, n = [], 0, 0
    try:
        from usage import meter
        ctx = meter.as_script(SCRIPT)
    except Exception:  # noqa: BLE001
        ctx = None
    if ctx:
        ctx.__enter__()
    try:
        for w, why in todo:
            if left - credits < worst:
                break
            row = con.execute("SELECT newest_ts FROM tb_fetched WHERE wallet = ?", (w,)).fetchone()
            since = max(int(row[0] or 0) if row else 0, now - int(t["lookback_d"]) * 86400)
            txs, token, paid, complete = [], None, 0, 1
            try:
                for _page in range(int(t["max_pages"])):
                    data, token, cr = fetch(w, since, token, t)
                    paid += cr
                    txs += data
                    if not token or not data:
                        break
                else:
                    complete = 0
            except Exception as e:  # noqa: BLE001 - one wallet's failure is that wallet's
                log(f"transferi: {w[:6]}: {type(e).__name__}: {e}")
                credits += paid
                continue
            credits += paid
            rows = tx_rows(txs, w, float(t["min_sol"]))
            rows_all += rows
            newest = max([int(x.get("blockTime") or 0) for x in txs] + [since])
            con.execute("INSERT OR REPLACE INTO tb_fetched VALUES (?,?,?,?,?,?,?,?)",
                        (w, now, newest, paid, len(txs), len(rows), complete, why))
            n += 1
    finally:
        if ctx:
            ctx.__exit__(None, None, None)
    if rows_all:
        from kol import chainwatch
        h = sqlite3.connect(p.get("hype") or HYPE_DB, timeout=60)
        try:
            chainwatch._create(h)
            h.executemany("INSERT OR IGNORE INTO chain_transfers VALUES (?,?,?,?,?,?)", rows_all)
            h.commit()
        finally:
            h.close()
    con.execute("""INSERT INTO tb_days VALUES (?,?,?,?,?) ON CONFLICT (day) DO UPDATE SET credits = credits + excluded.credits,
                   wallets = wallets + excluded.wallets, rows = rows + excluded.rows, ts = excluded.ts""",
                (_day(now), credits, n, len(rows_all), now))
    con.commit()
    out = {"status": "ok", "novcanika": n, "krediti": credits, "redaka": len(rows_all), "na_redu": len(todo),
           "ostalo": max(0, left - credits), "strop": int(t["credits_day"])}
    log(f"transferi: {n}/{len(todo)} novčanika, {credits} kredita (strop {t['credits_day']}/dan), {len(rows_all)} transfera")
    return out


def night(con, cfg=None, now=None, log=print):
    """The night step (run_kol.py cmd_rotacija): returns, the weekly rotation when due, the day's transfer batch."""
    out = {}
    p = paths()
    for k, fn in (("povratak", lambda: returns(con, cfg, now, p, log)), ("rotacija", lambda: rotate(con, cfg, now, p, log)),
                  ("transferi", lambda: transfers_batch(con, cfg, now, p, log=log))):
        try:
            out[k] = fn()
        except SourceError as e:
            out[k] = {"status": "greska_izvora", "greska": str(e)}
            log(f"rotacija {k}: izvor nečitljiv: {e}")
    return out


# ---------- the report line and the estimate ------------------------------------------------------------------------------

def webhook_estimate(usage_db, n_wallets, budget_day=92_000, batch_day=15_000, now=None, days=3):
    """Webhook events a day per wallet over the last `days` full UTC days (usage.db) and how many wallets the day
    budget holds next to the transfer batch. None without data. (Pretpostavka: new wallets as active as the average.)"""
    if not usage_db or not os.path.exists(usage_db) or not n_wallets:
        return None
    now = int(now or time.time())
    d0 = now // 86400 * 86400
    try:
        from usage import meter
        name = meter.WEBHOOK_SCRIPT
    except Exception:  # noqa: BLE001
        name = "webhook novčanika"
    rows = _q(usage_db, "SELECT hour / 86400, SUM(calls) FROM usage WHERE service = 'helius' AND script = ? AND "
                        "method = 'webhook događaji' AND hour >= ? AND hour < ? GROUP BY 1", (name, d0 - days * 86400, d0))
    vals = [v for _d, v in rows if v]
    if not vals:
        return None
    per_day = sum(vals) / len(vals)
    per_w = per_day / n_wallets
    fits = int((budget_day - batch_day) / per_w) if per_w > 0 else None
    return {"dogadaja_dan": round(per_day), "po_novcaniku": round(per_w, 1), "stane": fits, "dana": len(vals)}


def report(kol_db=None, usage_db=None, now=None, cfg=None):
    """Dict for the daily cost line: the last rotation, parked / replaced now, today's transfer batch, the estimate."""
    con = _ro(kol_db or kstore.DB)
    if con is None:
        return {}
    now = int(now or time.time())
    try:
        try:
            last = con.execute("SELECT run, ts, n_set, n_out, n_in, n_return, cap, status FROM rot_runs ORDER BY ts DESC "
                               "LIMIT 1").fetchone()
            states = dict(con.execute("SELECT state, COUNT(*) FROM rot_state GROUP BY state").fetchall())
            day = con.execute("SELECT credits, wallets, rows FROM tb_days WHERE day = ?", (_day(now),)).fetchone()
        except sqlite3.Error:
            return {}
        n_set = len(current_set(con))
    finally:
        con.close()
    _c, t = config(cfg)
    out = {"parkirano": states.get("parked", 0), "zamjena": states.get("in", 0), "vraceno": states.get("returned", 0),
           "skup": n_set, "transferi_krediti": (day or (0,))[0], "transferi_novcanika": (day or (0, 0))[1],
           "transferi_redaka": (day or (0, 0, 0))[2]}
    if last:
        out["zadnja"] = {"ts": last[1], "skup": last[2], "van": last[3], "unutra": last[4], "povratak": last[5],
                         "strop": last[6], "status": last[7]}
    est = webhook_estimate(usage_db, n_set, batch_day=int(t["credits_day"]), now=now)
    if est:
        out["procjena"] = est
    return out


def report_line(r):
    if not r:
        return ""
    z = r.get("zadnja") or {}
    s = (f"rotacija novčanika: skup {r.get('skup', 0)}, parkirano {r.get('parkirano', 0)}, zamjena {r.get('zamjena', 0)}, "
         f"vraćeno {r.get('vraceno', 0)}")
    if z:
        s += (time.strftime(" (zadnja %d.%m.", time.gmtime(z["ts"])) + f" {z.get('status')}: van {z.get('van') or 0}, "
              f"unutra {z.get('unutra') or 0}, povratak {z.get('povratak') or 0}, strop {z.get('strop') or 0})")
    s += f"; transferi batch {r.get('transferi_krediti', 0)} kr. za {r.get('transferi_novcanika', 0)} novčanika"
    e = r.get("procjena")
    if e:
        s += (f"; webhook {e['dogadaja_dan']:,} dog./dan = {e['po_novcaniku']} po novčaniku, u 92k/dan stane ~{e['stane']} "
              f"novčanika (procjena, {e['dana']} d)").replace(",", ".")
    return s
