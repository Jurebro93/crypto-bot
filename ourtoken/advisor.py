"""Advice for our own token, built from what the bot already measured (kol.db) and from the live token's numbers.

- best_hours(): when X crypto posts get the most views and the best follow-through (calls table, by UTC hour)
- cocall_lift(): how much more often a token doubles when 3+ influencers call it within 15 minutes
- influencers(): who to partner with: real reach, calls that work, few rugs and late calls, no bots
- plan(): the marketing plan by phase, every step free or with its price
- live_advice(): what to do next from a launched token's price, liquidity, volume, buyers/sellers and holders
Everything is cached (1 h) and read-only.
"""
import datetime as dt
import os
import sqlite3
import time

_CACHE = {}
CACHE_S = 3600
try:
    from zoneinfo import ZoneInfo
    ZG = ZoneInfo("Europe/Zagreb")
except Exception:  # noqa: BLE001
    ZG = dt.timezone(dt.timedelta(hours=1))


def _cached(name, fn):
    hit = _CACHE.get(name)
    if hit and time.time() - hit[0] < CACHE_S:
        return hit[1]
    try:
        val = fn()
    except Exception:  # noqa: BLE001
        val = None
    _CACHE[name] = (time.time(), val)
    return val


def _kol_con():
    from league import copy
    return copy._ro(copy._paths()["kol"])


def _zg_hour(h_utc):
    d = dt.datetime.now(dt.timezone.utc).replace(hour=h_utc, minute=0, second=0, microsecond=0)
    return d.astimezone(ZG).hour


def best_hours(con=None, days=30, now=None):
    """Best 3-hour window to post: {start_utc, start_zg, views, hit, n, rows: [(h, n, views, hit)]} or None."""
    own = con is None
    con = con or _kol_con()
    if con is None:
        return None
    since = int((now or time.time()) - days * 86400)
    try:
        raw = con.execute("SELECT (ts/3600)%24, views, max24 >= 0.5 FROM calls "
                          "WHERE kind='call' AND max24 IS NOT NULL AND ts >= ?", (since,)).fetchall()
    except sqlite3.OperationalError:
        raw = []
    finally:
        if own:
            con.close()
    per = {}
    for h, v, hit in raw:
        per.setdefault(int(h), []).append((v or 0, hit or 0))
    by = {}
    for h, xs in per.items():   # median views: a few viral posts must not pick the hour
        vs = sorted(v for v, _ in xs)
        by[h] = (len(xs), vs[len(vs) // 2], sum(x for _, x in xs) / len(xs))
    if sum(r[0] for r in by.values()) < 100:
        return None
    mean_v = sum(r[0] * r[1] for r in by.values()) / sum(r[0] for r in by.values())
    best = None
    for s in range(24):
        if not 9 <= _zg_hour(s) <= 21:   # we launch and post ourselves: only hours when the players are awake
            continue
        hs = [by.get((s + i) % 24) for i in range(3)]
        if any(h is None or h[0] < 40 for h in hs):
            continue
        n = sum(h[0] for h in hs)
        v = sum(h[0] * h[1] for h in hs) / n
        hit = sum(h[0] * h[2] for h in hs) / n
        score = (v / mean_v) * hit
        if best is None or score > best[0]:
            best = (score, s, v, hit, n)
    if not best:
        return None
    return {"start_utc": best[1], "start_zg": _zg_hour(best[1]), "views": best[2], "hit": best[3], "n": best[4],
            "mean_views": mean_v, "rows": sorted((h, *r) for h, r in by.items())}


def cocall_lift(con=None, window_s=900, min_kols=3):
    """{group_n, group_rate, solo_n, solo_rate}: share of tokens reaching 2x in 24 h when min_kols+ distinct callers
    posted within window_s of the first call, versus fewer."""
    own = con is None
    con = con or _kol_con()
    if con is None:
        return None
    try:
        rows = con.execute("SELECT token, handle, ts, max24 FROM calls WHERE kind='call' AND max24 IS NOT NULL "
                           "ORDER BY token, ts").fetchall()
    except sqlite3.OperationalError:
        rows = []
    finally:
        if own:
            con.close()
    toks = {}
    for t, h, ts, m in rows:
        toks.setdefault(t, []).append((ts, h, m))
    g = [0, 0]
    s = [0, 0]
    for calls in toks.values():
        t0, first_max = calls[0][0], calls[0][2]
        kols = {h for ts, h, _ in calls if ts - t0 <= window_s}
        bucket = g if len(kols) >= min_kols else s
        bucket[0] += 1
        bucket[1] += 1 if (first_max or 0) >= 1.0 else 0
    if g[0] < 5 or s[0] < 20:
        return None
    return {"group_n": g[0], "group_rate": g[1] / g[0], "solo_n": s[0], "solo_rate": s[1] / s[0]}


def post_price(followers):
    """Very rough price of one paid post on crypto X, USD (small accounts ~$5-10 per 1k followers)."""
    f = followers or 0
    return max(50.0, min(5000.0, round(f / 1000 * 7 / 10) * 10))


def influencers(rows=None, n=12):
    """Partners ranked by fit: reach x calls that work x honesty. Each row gets 'fit', 'why', 'price', 'deal'."""
    if rows is None:
        from ui import copytrade
        rows = copytrade.kol_rows()
    out = []
    for r in rows:
        s = r.get("s") or {}
        fol = r.get("followers") or 0
        if fol < 1000 or (s.get("measured") or 0) < 3 or r["handle"].startswith(("w:", "tg:")):
            continue
        hit, rug, late = s.get("hit_rate") or 0, s.get("rug_rate") or 0, s.get("prepump_rate") or 0
        reach = min(1.0, (fol / 50_000) ** 0.5)
        fit = 100 * (0.40 * reach + 0.35 * hit + 0.15 * (1 - rug) + 0.10 * (1 - late)) * (r.get("score") or 50) / 60
        why = []
        if hit >= 0.5:
            why.append(f"{hit:.0%} njegovih poziva naraste +50% u 24 h")
        if fol >= 20_000:
            why.append(f"velik doseg ({fol:,.0f} pratitelja)")
        if rug <= 0.1:
            why.append("rijetko zove rugove")
        if late >= 0.4:
            why.append("često zove kasno, nakon pumpe (oprez)")
        if rug > 0.25:
            why.append("zove dosta rugova (oprez)")
        price = post_price(fol)
        pct = 0.5 if fol < 10_000 else 1.0 if fol < 50_000 else 1.5
        out.append(dict(r, fit=min(100.0, fit), why=why, price=price,
                        deal=f"{pct:g}% supplyja kroz 4 tjedna (25% tjedno, samo ako objavi) ili ~${price:,.0f} po objavi"))
    return sorted(out, key=lambda r: r["fit"], reverse=True)[:n]


def plan(p, hours=None, lift=None, partners=None):
    """Marketing plan by phase: [(phase, [(step, cost_text, free?)])]."""
    hrs = hours or {}
    when = (f"{hrs['start_zg']:02d}:00-{(hrs['start_zg'] + 3) % 24:02d}:00 po našem vremenu"
            if hrs else "u američkoj sesiji (15-23 h po našem vremenu)")
    wave = (f"tokeni koje 3+ influencera zove unutar 15 min dupliraju se u {lift['group_rate']:.0%} slučajeva, "
            f"inače u {lift['solo_rate']:.0%}" if lift else "više influencera u istih 15 minuta daje puno jači efekt")
    names = ", ".join("@" + r["handle"] for r in (partners or [])[:5])
    sym = p.get("symbol") or "TOKEN"
    pump = p.get("launch") == "pumpfun"
    mkt = float(p.get("mkt_usd") or 0)
    return [
        ("1. Prije lansiranja (3-7 dana)", [
            (f"Otvoriti X račun ${sym} i Telegram grupu; ime, slika i opis isti svugdje", "besplatno", True),
            ("Jednostavna web stranica (Netlify ili Carrd) s adresom tokena, raspodjelom supplyja i linkovima",
             "besplatno, domena ~$15/god", True),
            ("Napraviti 20-30 memeova i 3 kratka videa unaprijed (AI generator slika)", "besplatno", True),
            (f"Dogovoriti 3-5 influencera ({names or 'vidi tablicu ispod'}) za objavu u istih 15 minuta",
             "dio supplyja ili po objavi, vidi tablicu", False),
        ]),
        ("2. Dan lansiranja", [
            (f"Lansirati {when}: tada objave na X-u imaju najviše pregleda i najbolji ishod (iz naših podataka)",
             "besplatno", True),
            ("Odmah javno objaviti: mint i freeze isključeni" + ("" if pump else ", LP tokeni spaljeni")
             + ", adresa trezora i tima. Naš anti-rug filter to traži, i ostali botovi isto", "besplatno", True),
            (f"Val objava: svi dogovoreni influenceri u istih 15 minuta ({wave})", "dogovor", False),
            ("Svi igrači: retweet, odgovori, objava u svojim grupama (raid) prvih sat vremena", "besplatno", True),
            ("DexScreener Boost tek kad krene volumen, ne odmah", "$99", False),
        ]),
        ("3. Prvi tjedan", [
            ("Svaki dan 2-3 memea, jedan Space na X-u, odgovarati svima u grupi", "besplatno", True),
            (("Cilj: napuniti pump.fun krivulju (~$70k) da token prijeđe na PumpSwap" if pump else
              "Cilj: dnevni volumen barem 10% tržišne vrijednosti"), "", True),
            ("DexScreener profil (logo, linkovi) čim ima stalan volumen", "$299", False),
            ("Prijava na Jupiter popis tokena i CoinGecko (traži 7+ dana trgovanja)", "besplatno", True),
            ("Natječaj za holdere: najbolji meme tjedna dobiva tokene iz trezora tima", "iz supplyja", True),
        ]),
        ("4. Dalje", [
            ("Tjedno pogledati ovu stranicu: alat iz brojki tokena predlaže sljedeći korak", "besplatno", True),
            ("Influencerima isplaćivati dio supplyja tek kad objave (25% tjedno), nikad sve unaprijed", "", True),
            (f"Ukupni marketinški budžet iz forme: ${mkt:,.0f}. Prvo besplatno, plaćeno tek kad ima volumena",
             "", True),
        ]),
    ]


def live_stats(mint):
    """Live numbers of a launched token: price, mcap, liq, vol24, buys24, sells24, top10 (% of supply), url."""
    out = {}
    try:
        from dexscreener import client
        pairs = client.tokens("solana", [mint]) or []
    except Exception:  # noqa: BLE001
        pairs = []
    if pairs:
        p = max(pairs, key=lambda x: (x.get("liquidity") or {}).get("usd") or 0)
        tx = (p.get("txns") or {}).get("h24") or {}
        out = {"price": float(p.get("priceUsd") or 0), "mcap": p.get("marketCap") or p.get("fdv"),
               "liq": (p.get("liquidity") or {}).get("usd"), "vol24": (p.get("volume") or {}).get("h24"),
               "buys24": tx.get("buys"), "sells24": tx.get("sells"), "url": p.get("url"),
               "chg24": (p.get("priceChange") or {}).get("h24"), "dex": p.get("dexId")}
    if os.environ.get("HELIUS_API_KEY"):
        try:
            from wallets import rpc
            big, _ = rpc._rpc("getTokenLargestAccounts", [mint], ttl=900)
            sup, _ = rpc._rpc("getTokenSupply", [mint], ttl=900)
            total = float((sup.get("value") or {}).get("uiAmount") or 0)
            amounts = sorted((float(a.get("uiAmount") or 0) for a in big.get("value") or []), reverse=True)
            if total:
                out["top10"] = 100 * sum(amounts[1:11]) / total   # largest account is usually the pool: left out
        except Exception:  # noqa: BLE001
            pass
    return out


def live_advice(s, hist=()):
    """Plain advice from a launched token's numbers: [(level, text)], level good/warn/bad."""
    if not s or not s.get("price"):
        return [("warn", "DexScreener još ne vidi trgovanje ovim tokenom. Ako je tek lansiran, pričekaj par minuta.")]
    out = []
    mcap, liq, vol = s.get("mcap") or 0, s.get("liq") or 0, s.get("vol24") or 0
    buys, sells = s.get("buys24") or 0, s.get("sells24") or 0
    if mcap and liq / mcap < 0.05 and s.get("dex") != "pumpfun":
        out.append(("bad", f"Likvidnost je samo {liq / mcap:.0%} tržišne vrijednosti: veće prodaje ruše cijenu. "
                           "Dodati likvidnost iz trezora ili ne gurati marketing dok se to ne popravi."))
    if mcap and vol / mcap < 0.1:
        out.append(("warn", "Volumen je nizak (ispod 10% vrijednosti dnevno): vrijeme za novi val objava "
                            "(3+ influencera u istih 15 min) ili natječaj za holdere."))
    elif mcap and vol / mcap > 1:
        out.append(("good", "Volumen je jak: sad ima smisla plaćeni boost i DexScreener profil, ljudi traže token."))
    if buys + sells >= 50:
        if sells > buys * 1.3:
            out.append(("warn", f"Više prodaja nego kupnji ({sells} prema {buys}): netko izlazi. Provjeriti tko "
                                "(top holderi) i odgovoriti u grupi prije panike."))
        elif buys > sells * 1.3:
            out.append(("good", f"Više kupnji nego prodaja ({buys} prema {sells}): pravo vrijeme za objave."))
    if s.get("top10") is not None:
        if s["top10"] > 35:
            out.append(("bad", f"Top 10 novčanika drži {s['top10']:.0f}% supplyja: botovi i kupci to vide kao rizik "
                               "od ruga. Raspodijeliti (natječaji, influenceri) i javno objasniti čije su adrese."))
        elif s["top10"] < 20:
            out.append(("good", f"Top 10 novčanika drži samo {s['top10']:.0f}%: zdrava raspodjela."))
    if len(hist) >= 2 and hist[-1].get("mcap") and hist[0].get("mcap"):
        ch = hist[0]["mcap"] / hist[-1]["mcap"] - 1
        out.append(("good" if ch >= 0 else "warn", f"Od prve snimke vrijednost {'narasla' if ch >= 0 else 'pala'} "
                                                    f"{abs(ch):.0%}."))
    if not out:
        out.append(("good", "Brojke su uredne. Nastaviti s dnevnim objavama i pratiti ovu stranicu."))
    return out
