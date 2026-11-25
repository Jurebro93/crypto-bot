"""Knjiga ishoda naših tokena: DexScreener (besplatno, kroz limiter dexscreener/client) na +1 h, +12 h, +24 h i +7 d
od lansiranja: promet, broj transakcija, mcap, najviša viđena vrijednost (donja granica vrha: trenutni mcap i oni
izvedeni iz priceChange m5/h1/h6), bondan da/ne (par izvan krivulje pump.fun).

Procjena naknade kreatoru: promet × CREATOR_RATE (0,30 % „prema objavi, NEPROVJERENO”) / cijena SOL-a. Promet: dok je
token mlađi od 24 h, DexScreenerov volume.h24 je cijeli promet od lansiranja, pa je osnova točka +24 h (ili zadnja
ranija koja postoji); točka +7 d dodaje svoj volume.h24 (zadnji dan) kao DONJU granicu prometa dana 2-7.
Neto = procjena naknade − izmjereni trošak lansiranja (saldo prije − poslije).

CSV (za istraživanje): po tokenu, bez ikakvih adresa kupaca (alat ih ni ne dohvaća).
"""
import csv
import io
import math
import statistics
import time

from pumptokeni import store

CHECKS = (("1h", 3600), ("12h", 12 * 3600), ("24h", 24 * 3600), ("7d", 7 * 86400))
CREATOR_RATE = 0.003
RATE_NOTE = "stopa naknade 0,30 % prometa prema objavi pump.fun, NEPROVJERENO"
WSOL = "So11111111111111111111111111111111111111112"
BATCH = 30


def _num(x):
    try:
        v = float(x)
        return v if math.isfinite(v) else None
    except (TypeError, ValueError):
        return None


def aggregate(pairs, mints):
    """{mint: dict(nadjen, promet_usd, txns, mcap_usd, max_mcap_usd, bondan)}, sol_usd (medijan iz parova u SOL-u)."""
    by = {m: [] for m in mints}
    rates = []
    for p in pairs or []:
        m = ((p or {}).get("baseToken") or {}).get("address")
        if m in by:
            by[m].append(p)
        q = ((p or {}).get("quoteToken") or {}).get("address")
        pu, pn = _num((p or {}).get("priceUsd")), _num((p or {}).get("priceNative"))
        if q == WSOL and pu and pn:
            rates.append(pu / pn)
    out = {}
    for m, ps in by.items():
        if not ps:
            out[m] = {"nadjen": 0, "promet_usd": None, "txns": None, "mcap_usd": None, "max_mcap_usd": None, "bondan": None}
            continue
        vols = [v for v in (_num((p.get("volume") or {}).get("h24")) for p in ps) if v is not None]
        tx = sum(int(_num(((p.get("txns") or {}).get("h24") or {}).get(s)) or 0) for p in ps for s in ("buys", "sells"))
        mcaps, peaks = [], []
        for p in ps:
            mc = _num(p.get("marketCap")) or _num(p.get("fdv"))
            if not mc:
                continue
            mcaps.append(mc)
            peaks.append(mc)
            for w in ("m5", "h1", "h6"):
                pc = _num((p.get("priceChange") or {}).get(w))
                if pc is not None and pc > -99.9:
                    peaks.append(mc / (1 + pc / 100))
        out[m] = {"nadjen": 1, "promet_usd": sum(vols) if vols else None, "txns": tx,
                  "mcap_usd": max(mcaps) if mcaps else None, "max_mcap_usd": max(peaks) if peaks else None,
                  "bondan": int(any((p.get("dexId") or "") != "pumpfun" for p in ps))}
    return out, (statistics.median(rates) if rates else None)


def _fetch(mints):
    from dexscreener import client
    return client._get(f"/tokens/v1/solana/{','.join(mints)}", fast=True) or []


def _fallback_sol_usd():
    try:
        from trade import equity
        return (equity.rates() or {}).get("sol_usd")
    except Exception:  # noqa: BLE001
        return None


def launched(con):
    """[{mint, ts, ...pokušaj}] uspješno lansiranih (stanje 'lansiran')."""
    return [dict(r) for r in con.execute("SELECT * FROM pokusaji WHERE stanje='lansiran' AND mint IS NOT NULL ORDER BY ts")]


def due(con, now):
    """[(mint, oznaka)] kontrolnih točaka koje su dospjele, a nisu zapisane."""
    have = {(r[0], r[1]) for r in con.execute("SELECT mint, tocka FROM ishodi")}
    out = []
    for a in launched(con):
        for lab, off in CHECKS:
            if now >= a["ts"] + off and (a["mint"], lab) not in have:
                out.append((a["mint"], lab))
    return out


def check_pass(con, now=None, fetch=None, log=print):
    """Zapiše dospjele točke (DexScreener u serijama od 30). Broj zapisanih."""
    now = int(now or time.time())
    todo = due(con, now)
    if not todo:
        return 0
    fetch = fetch or _fetch
    mints = sorted({m for m, _ in todo})
    agg, rate = {}, None
    for i in range(0, len(mints), BATCH):
        part = mints[i:i + BATCH]
        try:
            a, r = aggregate(fetch(part), part)
        except Exception as e:  # noqa: BLE001 - next pass tries again
            log(f"pump tokeni: ishod nije dohvaćen ({type(e).__name__})")
            return 0
        agg.update(a)
        rate = rate or r
    rate = rate or _fallback_sol_usd()
    for m, lab in todo:
        x = agg.get(m) or {}
        con.execute("INSERT OR IGNORE INTO ishodi VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (m, lab, now, x.get("nadjen", 0), x.get("promet_usd"), x.get("txns"), x.get("mcap_usd"),
                     x.get("max_mcap_usd"), x.get("bondan"), rate))
    con.commit()
    return len(todo)


def book(con):
    """[{pokušaj + točke + procjena}] po lansiranom tokenu, i {skupina: zbroj}."""
    pts = {}
    for r in con.execute("SELECT * FROM ishodi"):
        pts.setdefault(r["mint"], {})[r["tocka"]] = dict(r)
    rows, groups = [], {}
    for a in launched(con):
        p = pts.get(a["mint"], {})
        base = next((p[k] for k in ("24h", "12h", "1h") if k in p and p[k]["promet_usd"] is not None), None)
        vol = base["promet_usd"] if base else None
        late = p.get("7d", {}).get("promet_usd")
        vol_total = (vol or 0) + (late or 0) if (vol is not None or late is not None) else None
        rate = next((x["sol_usd"] for x in p.values() if x.get("sol_usd")), None)
        fee_sol = vol_total * CREATOR_RATE / rate if (vol_total is not None and rate) else None
        cost = a.get("trosak_sol")
        net = (fee_sol or 0) - cost if (cost is not None and fee_sol is not None) else None
        peak = max([x["max_mcap_usd"] for x in p.values() if x.get("max_mcap_usd")] or [None]) \
            if any(x.get("max_mcap_usd") for x in p.values()) else None
        bond = 1 if any(x.get("bondan") for x in p.values()) else (0 if p else None)
        row = {**a, "tocke": p, "promet_usd": vol_total, "max_mcap_usd": peak, "bondan": bond, "naknada_sol": fee_sol,
               "neto_sol": net}
        rows.append(row)
        g = groups.setdefault(a.get("skupina") or "-", {"n": 0, "trosak_sol": 0.0, "naknada_sol": 0.0, "neto_sol": 0.0,
                                                        "bondano": 0, "s_ishodom": 0})
        g["n"] += 1
        g["trosak_sol"] += cost or 0.0
        if fee_sol is not None:
            g["naknada_sol"] += fee_sol
            g["s_ishodom"] += 1
        g["neto_sol"] = g["naknada_sol"] - g["trosak_sol"]
        g["bondano"] += 1 if bond else 0
    return rows, groups


CSV_COLS = ("nacrt_id", "skupina", "tema", "ime", "simbol", "mint", "lansirano_utc", "novcanik", "trosak_sol",
            "promet_1h_usd", "promet_12h_usd", "promet_24h_usd", "promet_7d_zadnji_dan_usd", "txns_24h", "max_mcap_usd",
            "bondan", "naknada_procjena_sol", "neto_sol", "napomena")


def csv_text(con):
    """CSV knjige ishoda. Bez adresa kupaca i bez adrese novčanika (samo vrsta novčanika); mint je naš token."""
    rows, _ = book(con)
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(CSV_COLS)
    for r in rows:
        p = r["tocke"]
        w.writerow([r["nacrt_id"], r["skupina"], r["tema"], r["ime"], r["simbol"], r["mint"],
                    time.strftime("%Y-%m-%d %H:%M", time.gmtime(r["ts"])), r["novcanik"], _c(r.get("trosak_sol")),
                    *(_c(p.get(k, {}).get("promet_usd")) for k in ("1h", "12h", "24h", "7d")),
                    p.get("24h", {}).get("txns", ""), _c(r["max_mcap_usd"]),
                    "" if r["bondan"] is None else ("da" if r["bondan"] else "ne"), _c(r["naknada_sol"]),
                    _c(r["neto_sol"]), RATE_NOTE])
    return out.getvalue()


def _c(x):
    return "" if x is None else (f"{x:.6f}" if isinstance(x, float) else str(x))


def line(con, now=None):
    """Red u logu: „pump tokeni: ...”."""
    now = int(now or time.time())
    from pumptokeni import launch
    rows, groups = book(con)
    n_q = len(launch.queue(con))
    today = launch.sent_today(con, now)
    cost = sum(g["trosak_sol"] for g in groups.values())
    fee = sum(g["naknada_sol"] for g in groups.values())
    bond = sum(g["bondano"] for g in groups.values())
    fails = con.execute("SELECT COUNT(*) FROM pokusaji WHERE stanje IN ('neuspio','odbijeno')").fetchone()[0]
    return (f"pump tokeni: lansirano {len(rows)} (danas poslano {today}), u redu {n_q}, odbijenih/neuspjelih {fails}, "
            f"bondano {bond}; trošak {cost:.4f} SOL, procjena naknade {fee:.4f} SOL (neprovjereno), neto "
            f"{fee - cost:+.4f} SOL")


def daily_line(con, now=None, log=print):
    """Jednom dnevno (UTC dan) red u logu; True kad je napisan. Bez ijednog pokušaja: ništa."""
    now = int(now or time.time())
    day = time.strftime("%Y-%m-%d", time.gmtime(now))
    if store.get(con, "zadnji_red") == day:
        return False
    if not con.execute("SELECT 1 FROM pokusaji LIMIT 1").fetchone():
        return False
    log(line(con, now))
    store.put(con, "zadnji_red", day)
    return True
