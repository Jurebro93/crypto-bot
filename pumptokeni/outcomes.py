"""Knjiga ishoda naših tokena: DexScreener (besplatno, kroz limiter dexscreener/client) na +1 h, +12 h, +24 h i +7 d
od lansiranja: promet, broj transakcija, mcap, najviša viđena vrijednost (donja granica vrha: trenutni mcap i oni
izvedeni iz priceChange m5/h1/h6), bondan da/ne (par izvan krivulje pump.fun).

Procjena naknade kreatoru: promet × CREATOR_RATE / cijena SOL-a. Stopa 0,30 % prometa na krivulji je POTVRĐENA s lanca
25.11.2026. (protokol 0,95 %, ukupno 1,25 %); nakon bondanja vrijedi druga ljestvica, pa je za bondane procjena gruba. Promet: dok je
token mlađi od 24 h, DexScreenerov volume.h24 je cijeli promet od lansiranja, pa je osnova točka +24 h (ili zadnja
ranija koja postoji); točka +7 d dodaje svoj volume.h24 (zadnji dan) kao DONJU granicu prometa dana 2-7.
Neto = procjena naknade bez vlastite kupnje − izmjereni trošak lansiranja (saldo prije − poslije − vlastita kupnja).
Vlastita kupnja (26.11.): naknada kreatora od naše kupnje (0,30 % × kupnja) nije prihod, pa se oduzima od procjene
(„naknada bez vlastite kupnje”); kupnja je vezan kapital u tokenima („u tokenima: X SOL”), ne gubitak.
Kupci u prvih 10 min (measure_buyers): različiti novčanici (bez kreatora i računa krivulje) čiji je saldo našeg tokena
porastao u transakcijama u prvih 600 s od lansiranja; getSignaturesForAddress(mint) + getTransaction kroz RPC posla,
jednom po tokenu (11+ min nakon lansiranja), tvrdi strop BUYERS_MAX_CALLS poziva po tokenu (dosegnut = „≥ N”). Ako
RPC ne odgovori: broj kupnji iz DexScreener snimka (kupnje 1 h u snimku 10–20 min nakon lansiranja), označen „kupnji”.

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
BUYERS_WINDOW_S = 600
BUYERS_AFTER_S = 660          # mjeri se tek 11 min nakon lansiranja (prozor od 10 min je zatvoren)
BUYERS_MAX_CALLS = 300        # tvrdi strop RPC poziva po tokenu
BUYERS_MAX_TRIES = 3
RATE_NOTE = "0,30 % prometa na krivulji, potvrđeno s lanca 25.11.2026.; za bondane tokene procjena je gruba"
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
            out[m] = {"nadjen": 0, "promet_usd": None, "txns": None, "mcap_usd": None, "max_mcap_usd": None,
                      "bondan": None}
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
        for w in ("m5", "h1", "h6", "h24"):   # 26.11.: nadzorna ploča (snimci)
            v = [x for x in (_num((p.get("volume") or {}).get(w)) for p in ps) if x is not None]
            out[m]["promet_" + w] = sum(v) if v else None
        for w in ("h1", "h24"):
            for s_, k in (("buys", "kupnje_"), ("sells", "prodaje_")):
                out[m][k + w] = sum(int(_num(((p.get("txns") or {}).get(w) or {}).get(s_)) or 0) for p in ps)
        liq = [x for x in (_num((p.get("liquidity") or {}).get("usd")) for p in ps) if x is not None]
        out[m]["likvidnost_usd"] = sum(liq) if liq else None
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


def own_fee_adjusted(fee_sol, buy_sol):
    """Procjena naknade bez naknade od vlastite kupnje (0,30 % × kupnja nije prihod)."""
    if fee_sol is None:
        return None
    return max(0.0, fee_sol - CREATOR_RATE * float(buy_sol or 0))


def buyers_text(a):
    """„7”, „≥ 300” ili „12 kupnji” (DexScreener), „–” bez mjerenja."""
    n, src = a.get("kupci_10m"), a.get("kupci_10m_izvor")
    if n is None:
        return "–"
    if src == "rpc_strop":
        return f"≥ {n}"
    if src == "dex_kupnji":
        return f"{n} kupnji"
    return str(n)


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
        buy = float(a.get("kupnja_sol") or 0)
        fee_sol = own_fee_adjusted(fee_sol, buy)
        cost = a.get("trosak_sol")
        net = (fee_sol or 0) - cost if (cost is not None and fee_sol is not None) else None
        peak = max([x["max_mcap_usd"] for x in p.values() if x.get("max_mcap_usd")] or [None]) \
            if any(x.get("max_mcap_usd") for x in p.values()) else None
        bond = 1 if any(x.get("bondan") for x in p.values()) else (0 if p else None)
        row = {**a, "tocke": p, "promet_usd": vol_total, "max_mcap_usd": peak, "bondan": bond, "naknada_sol": fee_sol,
               "neto_sol": net, "u_tokenima_sol": buy}
        rows.append(row)
        g = groups.setdefault(a.get("skupina") or "-", {"n": 0, "trosak_sol": 0.0, "naknada_sol": 0.0, "neto_sol": 0.0,
                                                        "bondano": 0, "s_ishodom": 0, "u_tokenima_sol": 0.0})
        g["u_tokenima_sol"] += buy
        g["n"] += 1
        g["trosak_sol"] += cost or 0.0
        if fee_sol is not None:
            g["naknada_sol"] += fee_sol
            g["s_ishodom"] += 1
        g["neto_sol"] = g["naknada_sol"] - g["trosak_sol"]
        g["bondano"] += 1 if bond else 0
    return rows, groups


# ---------- nadzorna ploča: snimci (26.11., vlasnik: „svakih 10-ak minuta, da možemo mjeriti uspješnost”) ---------

SNAP_YOUNG_S = 7 * 86400          # mlađi od 7 dana: svaki prolaz; stariji jednom dnevno
SNAP_OLD_EVERY_S = 86400
MAX_SNAPS = 7 * 144               # tvrdi strop redaka po tokenu (7 dana × 144 snimka)
SNAP_COLS = ("nadjen", "promet_m5", "promet_h1", "promet_h6", "promet_h24", "kupnje_h1", "prodaje_h1", "kupnje_h24",
             "prodaje_h24", "mcap_usd", "max_mcap_usd", "likvidnost_usd", "bondan")
RENT_EMPTY_LAMPORTS = 890_880     # najam praznog računa (0 B): ostaje u trezoru, ne može se podići


def refresh_every_s(env=None):
    """PUMP_TOKENI_OSVJEZI_MIN (zadano 10, najmanje 5, najviše 1440) u sekundama."""
    import os
    env = os.environ if env is None else env
    try:
        v = float((env.get("PUMP_TOKENI_OSVJEZI_MIN") or "").strip() or 10)
    except ValueError:
        v = 10
    return int(max(5, min(1440, v)) * 60)


def snapshot_due(con, now):
    """[mint] naših lansiranih tokena kojima je snimak dospio (mlađi od 7 dana uvijek, stariji jednom dnevno)."""
    last = {r[0]: r[1] for r in con.execute("SELECT mint, MAX(ts) FROM snimci GROUP BY mint")}
    out = []
    for a in launched(con):
        m = a["mint"]
        if now - a["ts"] < SNAP_YOUNG_S or now - (last.get(m) or 0) >= SNAP_OLD_EVERY_S:
            out.append(m)
    return sorted(set(out))


def refresh(con, now=None, fetch=None, log=print):
    """Jedan prolaz ploče: JEDAN batch zahtjev DexScreeneru (kroz limiter dexscreener/client; serija od 30 tokena,
    pokus ih ima manje) za sve naše tokene kojima je dospio snimak ili kontrolna točka; zapiše snimke (strop
    MAX_SNAPS po tokenu) i dospjele točke knjige ishoda iz istog odgovora. (snimaka, točaka)."""
    now = int(now or time.time())
    todo = due(con, now)
    mints = sorted(set(snapshot_due(con, now)) | {m for m, _ in todo})
    if not mints:
        return 0, 0
    fetch = fetch or _fetch
    agg, rate = {}, None
    for i in range(0, len(mints), BATCH):
        part = mints[i:i + BATCH]
        try:
            a, r = aggregate(fetch(part), part)
        except Exception as e:  # noqa: BLE001 - next pass tries again
            log(f"pump tokeni: ploča nije osvježena ({type(e).__name__})")
            return 0, 0
        agg.update(a)
        rate = rate or r
    rate = rate or _fallback_sol_usd()
    prev = {r[0]: r[1] for r in con.execute("SELECT mint, MAX(max_mcap_usd) FROM snimci GROUP BY mint")}
    snaps = set(snapshot_due(con, now))
    n = 0
    for m in mints:
        x = agg.get(m) or {}
        if m not in snaps:
            continue
        peak = max([v for v in (x.get("max_mcap_usd"), prev.get(m)) if v] or [None])
        vals = dict(x, max_mcap_usd=peak)
        con.execute(f"INSERT OR REPLACE INTO snimci (mint, ts, {', '.join(SNAP_COLS)}, sol_usd) VALUES "
                    f"(?,?,{','.join('?' * len(SNAP_COLS))},?)", (m, now, *(vals.get(c) for c in SNAP_COLS), rate))
        con.execute("DELETE FROM snimci WHERE mint=? AND ts NOT IN (SELECT ts FROM snimci WHERE mint=? ORDER BY ts DESC "
                    "LIMIT ?)", (m, m, MAX_SNAPS))
        n += 1
    for m, lab in todo:
        x = agg.get(m) or {}
        con.execute("INSERT OR IGNORE INTO ishodi VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (m, lab, now, x.get("nadjen", 0), x.get("promet_usd"), x.get("txns"), x.get("mcap_usd"),
                     x.get("max_mcap_usd"), x.get("bondan"), rate))
    con.commit()
    return n, len(todo)


def snapshots(con, mint, since=None):
    q = "SELECT * FROM snimci WHERE mint=?" + (" AND ts>=?" if since else "") + " ORDER BY ts"
    return [dict(r) for r in con.execute(q, (mint, since) if since else (mint,))]


def _cumulative(snaps, launch_ts, field):
    """Zbroj polja `field` (24-satni prozor DexScreenera) od lansiranja. Token mlađi od 24 h: zadnji snimak je cijeli
    zbroj. Stariji: zbroj prvog snimka nakon svake pune 24 h (dan koji teče se ne broji): donja granica. None bez
    snimka."""
    pts = [s for s in snaps if s.get(field) is not None]
    if not pts:
        return None
    last = pts[-1]
    if last["ts"] - launch_ts < 86400:
        return last[field]
    tot, k = 0.0, 1
    for s in pts:
        if s["ts"] - launch_ts >= k * 86400:
            tot += s[field]
            k = int((s["ts"] - launch_ts) // 86400) + 1
    return tot


def vault_pda(creator):
    """Trezor naknade kreatora na krivulji: PDA ["creator-vault", kreator] programa pump.fun (jedan po novčaniku
    kreatora, za sve njegove tokene). Prema javnom IDL-u pump.funa; adresa se računa lokalno, bez mreže."""
    from solders.pubkey import Pubkey
    from pumptokeni import launch
    return str(Pubkey.find_program_address([b"creator-vault", bytes(Pubkey.from_string(creator))],
                                           Pubkey.from_string(launch.PUMP_PROGRAM))[0])


def read_vaults(con, now=None, rpc=None, log=print):
    """Saldo trezora za svakog kreatora naših lansiranih tokena (getBalance, besplatan RPC), u kv 'trezori'
    {kreator: {"vault", "lamports", "za_podici_sol", "ts"}}. Ne baca."""
    now = int(now or time.time())
    creators = sorted({a["platitelj"] for a in launched(con) if a.get("platitelj")})
    if not creators:
        return {}
    if rpc is None:
        from trade import wallet
        rpc = wallet.rpc
    out = store.get(con, "trezori", {}) or {}
    for c in creators:
        try:
            v = vault_pda(c)
            lam = int(rpc("getBalance", [v, {"commitment": "confirmed"}])["value"])
            out[c] = {"vault": v, "lamports": lam, "za_podici_sol": max(0, lam - RENT_EMPTY_LAMPORTS) / 1e9, "ts": now}
        except Exception as e:  # noqa: BLE001
            log(f"pump tokeni: trezor naknade nečitljiv ({type(e).__name__})")
    store.put(con, "trezori", out)
    return out


def claimed_sol(con):
    r = con.execute("SELECT SUM(iznos_sol) FROM podizanja WHERE stanje='potvrdeno' AND iznos_sol IS NOT NULL").fetchone()
    return float(r[0] or 0.0)


def dashboard(con, now=None):
    """Podaci nadzorne ploče iz baze (bez mreže): {"tiles": {...}, "rows": [...]}."""
    now = int(now or time.time())
    rows_b, _ = book(con)
    by_book = {r["mint"]: r for r in rows_b}
    rows = []
    t = {"lansirano": 0, "promet_usd": 0.0, "promet_sol": 0.0, "kupnje": 0, "prodaje": 0, "naknada_sol": 0.0,
         "trosak_sol": 0.0, "s_prometom": 0, "bondano": 0, "u_tokenima_sol": 0.0}
    for a in launched(con):
        sn = snapshots(con, a["mint"])
        last = sn[-1] if sn else {}
        b = by_book.get(a["mint"]) or {}
        vol = _cumulative(sn, a["ts"], "promet_h24")
        if b.get("promet_usd") is not None:
            vol = max(vol or 0.0, b["promet_usd"])
        buys = _cumulative(sn, a["ts"], "kupnje_h24")
        sells = _cumulative(sn, a["ts"], "prodaje_h24")
        rate = next((s["sol_usd"] for s in reversed(sn) if s.get("sol_usd")), None) or \
            next((x["sol_usd"] for x in (b.get("tocke") or {}).values() if x.get("sol_usd")), None)
        buy = float(a.get("kupnja_sol") or 0)
        fee = own_fee_adjusted(vol * CREATOR_RATE / rate if (vol is not None and rate) else None, buy)
        cost = a.get("trosak_sol")
        peak = max([v for v in [s.get("max_mcap_usd") for s in sn] + [b.get("max_mcap_usd")] if v] or [None])
        bond = 1 if (last.get("bondan") or b.get("bondan")) else (0 if (sn or b.get("tocke")) else None)
        r = {"nacrt_id": a["nacrt_id"], "mint": a["mint"], "simbol": a["simbol"], "ime": a["ime"], "ts": a["ts"],
             "starost_s": now - a["ts"], "promet_m5": last.get("promet_m5"), "promet_h1": last.get("promet_h1"),
             "promet_h24": last.get("promet_h24"), "promet_usd": vol, "kupnje": buys, "prodaje": sells,
             "mcap_usd": last.get("mcap_usd"), "max_mcap_usd": peak, "bondan": bond, "naknada_sol": fee,
             "trosak_sol": cost, "neto_sol": (fee or 0.0) - cost if cost is not None else None, "snimci": sn,
             "zadnji_ts": last.get("ts"), "u_tokenima_sol": buy, "kupci": buyers_text(a)}
        rows.append(r)
        t["lansirano"] += 1
        t["promet_usd"] += vol or 0.0
        t["promet_sol"] += (vol or 0.0) / rate if rate else 0.0
        t["kupnje"] += buys or 0
        t["prodaje"] += sells or 0
        t["naknada_sol"] += fee or 0.0
        t["s_prometom"] += 1 if (vol or 0) > 0 or (buys or 0) + (sells or 0) > 0 else 0
        t["bondano"] += 1 if bond else 0
        t["u_tokenima_sol"] += buy
    t["trosak_sol"] = float(con.execute("SELECT COALESCE(SUM(trosak_sol), 0) FROM pokusaji WHERE trosak_sol IS NOT NULL")
                            .fetchone()[0])
    t["neto_sol"] = t["naknada_sol"] - t["trosak_sol"]
    t["osvjezeno_ts"] = con.execute("SELECT MAX(ts) FROM snimci").fetchone()[0]
    trez = store.get(con, "trezori", {}) or {}
    t["za_podici_sol"] = sum(v.get("za_podici_sol") or 0 for v in trez.values()) if trez else None
    t["trezor_ts"] = max([v.get("ts") or 0 for v in trez.values()] or [0]) or None
    t["podignuto_sol"] = claimed_sol(con)
    rows.sort(key=lambda r: -r["ts"])
    return {"tiles": t, "rows": rows}


# ---------- kupci u prvih 10 min (26.11., vlasnik) ----------------------------------------------------------------

def curve_pda(mint):
    from solders.pubkey import Pubkey
    from pumptokeni import launch
    return str(Pubkey.find_program_address([b"bonding-curve", bytes(Pubkey.from_string(mint))],
                                           Pubkey.from_string(launch.PUMP_PROGRAM))[0])


def _gained(tx, mint):
    """Vlasnici token računa našeg minta kojima je saldo porastao u transakciji (bez greške)."""
    meta = (tx or {}).get("meta") or {}
    if meta.get("err") is not None:
        return set()

    def bal(rows):
        out = {}
        for b in rows or []:
            if b.get("mint") != mint or not b.get("owner"):
                continue
            try:
                out[b["owner"]] = out.get(b["owner"], 0) + int((b.get("uiTokenAmount") or {}).get("amount") or 0)
            except (TypeError, ValueError):
                continue
        return out
    pre, post = bal(meta.get("preTokenBalances")), bal(meta.get("postTokenBalances"))
    return {o for o, v in post.items() if v > pre.get(o, 0)}


def count_buyers(rpc, mint, launch_ts, creator, max_calls=BUYERS_MAX_CALLS):
    """(broj, izvor 'rpc'|'rpc_strop', poziva). Različiti novčanici kojima je saldo našeg tokena porastao u prvih 600 s
    od lansiranja (prva transakcija minta, ili launch_ts), bez kreatora i računa krivulje. Najviše max_calls poziva."""
    calls, sigs, before = 0, [], None
    capped, at_start = False, False
    while True:
        if calls >= max_calls:
            capped = True
            break
        opts = {"limit": 1000, "commitment": "confirmed", **({"before": before} if before else {})}
        page = rpc("getSignaturesForAddress", [mint, opts]) or []
        calls += 1
        sigs += page
        if len(page) < 1000 or not page:
            at_start = True   # cijela povijest minta: najstarija je lansiranje
            break
        if (page[-1].get("blockTime") or 0) < launch_ts - 60:
            break
        before = page[-1].get("signature")
    times = [x["blockTime"] for x in sigs if x.get("blockTime")]
    t0 = min(times) if (at_start and times and abs(min(times) - launch_ts) < 3600) else launch_ts
    early = sorted((x for x in sigs if x.get("err") is None and x.get("blockTime") is not None
                    and t0 <= x["blockTime"] <= t0 + BUYERS_WINDOW_S), key=lambda x: (x["blockTime"], x["signature"]))
    skip = {creator, curve_pda(mint)}
    buyers = set()
    for x in early:
        if calls >= max_calls:
            capped = True
            break
        tx = rpc("getTransaction", [x["signature"], {"encoding": "json", "maxSupportedTransactionVersion": 0,
                                                     "commitment": "confirmed"}])
        calls += 1
        buyers |= _gained(tx, mint) - skip
    return len(buyers), ("rpc_strop" if capped else "rpc"), calls


def _dex_buys(con, a):
    """Kupnje (ne kupci) iz DexScreener snimka 10–20 min nakon lansiranja (kupnje 1 h = sve od lansiranja)."""
    for s in snapshots(con, a["mint"]):
        if BUYERS_WINDOW_S <= s["ts"] - a["ts"] <= 2 * BUYERS_WINDOW_S and s.get("kupnje_h1") is not None:
            return int(s["kupnje_h1"])
    return None


def measure_buyers(con, now=None, rpc=None, log=print, max_calls=BUYERS_MAX_CALLS):
    """Jednom po lansiranom tokenu (11+ min nakon lansiranja): kupci u prvih 10 min u pokusaji.kupci_10m. Broj
    izmjerenih. RPC posla (trade/wallet.rpc), besplatno; ne baca."""
    now = int(now or time.time())
    todo = [a for a in launched(con) if a.get("kupci_10m") is None and a.get("kupci_10m_izvor") is None
            and now - a["ts"] >= BUYERS_AFTER_S]
    if not todo:
        return 0
    if rpc is None:
        from trade import wallet
        rpc = wallet.rpc
    tries = store.get(con, "kupci_pokusaji", {}) or {}
    n = 0
    for a in todo:
        try:
            k, src, calls = count_buyers(rpc, a["mint"], a["ts"], a.get("platitelj"), max_calls)
            store.update_attempt(con, a["id"], kupci_10m=k, kupci_10m_izvor=src, kupci_10m_poziva=calls)
            log(f"pump tokeni: {a['simbol']} kupaca u prvih 10 min {'≥ ' if src == 'rpc_strop' else ''}{k} "
                f"({calls} RPC poziva)")
            n += 1
            continue
        except Exception as e:  # noqa: BLE001
            tries[a["mint"]] = tries.get(a["mint"], 0) + 1
            err = type(e).__name__
        dex = _dex_buys(con, a)
        if dex is not None or tries[a["mint"]] >= BUYERS_MAX_TRIES:
            store.update_attempt(con, a["id"], kupci_10m=dex, kupci_10m_izvor="dex_kupnji" if dex is not None else
                                 "nema", kupci_10m_poziva=0)
            log(f"pump tokeni: {a['simbol']} RPC bez podataka ({err}): "
                + (f"{dex} kupnji iz DexScreenera (kupnje, ne kupci)" if dex is not None else "kupci nisu izmjereni"))
            n += 1
    store.put(con, "kupci_pokusaji", tries)
    return n


CSV_COLS = ("nacrt_id", "skupina", "tema", "ime", "simbol", "mint", "lansirano_utc", "sat_lansiranja_cet", "novcanik",
            "vlastita_kupnja_sol", "ima_poveznice", "trosak_sol", "u_tokenima_sol", "promet_1h_usd", "promet_12h_usd",
            "promet_24h_usd", "promet_7d_zadnji_dan_usd", "txns_24h", "max_mcap_usd", "bondan", "kupaca_10min",
            "kupaca_10min_izvor", "naknada_bez_vlastite_kupnje_sol", "neto_sol", "upozorenje", "napomena")


def csv_text(con):
    """CSV knjige ishoda. Bez adresa kupaca i bez adrese novčanika (samo vrsta novčanika); mint je naš token."""
    rows, _ = book(con)
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(CSV_COLS)
    for r in rows:
        p = r["tocke"]
        w.writerow([r["nacrt_id"], r["skupina"], r["tema"], r["ime"], r["simbol"], r["mint"],
                    time.strftime("%Y-%m-%d %H:%M", time.gmtime(r["ts"])), store.cet(r["ts"], "%Y-%m-%d %H:%M"),
                    r["novcanik"], _c(float(r.get("kupnja_sol") or 0)), "da" if r.get("ima_poveznice") else "ne",
                    _c(r.get("trosak_sol")), _c(r["u_tokenima_sol"]),
                    *(_c(p.get(k, {}).get("promet_usd")) for k in ("1h", "12h", "24h", "7d")),
                    p.get("24h", {}).get("txns", ""), _c(r["max_mcap_usd"]),
                    "" if r["bondan"] is None else ("da" if r["bondan"] else "ne"),
                    "" if r.get("kupci_10m") is None else r["kupci_10m"],
                    {"rpc": "kupaca (RPC)", "rpc_strop": f"kupaca (RPC, strop {BUYERS_MAX_CALLS} poziva: najmanje)",
                     "dex_kupnji": "kupnji (DexScreener, ne kupaca)"}.get(r.get("kupci_10m_izvor") or "", ""),
                    _c(r["naknada_sol"]), _c(r["neto_sol"]), r.get("upozorenje") or "",
                    RATE_NOTE + "; naknada bez naknade od vlastite kupnje; vlastita kupnja je vezan kapital u tokenima"])
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
            f"bondano {bond}; trošak {cost:.4f} SOL, procjena naknade {fee:.4f} SOL, neto "
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
