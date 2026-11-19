"""Kritičar: short public reads of the market pages (15.11., vlasnik: "kritičar može interpretirati te podatke i
napisati svoje osvrte u nekim malim boksevima koje će korisnici vidjeti ... na hrvatski, na engleski").

    python3 run_critic.py market           # when due (run_sched: twice a day)
    python3 run_critic.py market --sada    # now, even when today's two are done (the budget still holds)

What goes to OpenAI: only the aggregated numbers the public pages already show (ui/marketpub.snapshot: volumes per
group and platform, the season index, call totals). No token, wallet, caller, position or setting. What comes back:
at most one read per page (market, calls, launchpads, dex, season), Croatian and English, each at most MAX_CHARS.
Every read is checked before it is stored: no link, no @handle, no $TICKER, no address, no advice to buy or sell, no
promise; a read that fails is dropped (the page then shows only its rule-based boxes, ui/marketnotes.py).

Cost: the cheap model (openai_api.MODEL_CHEAP), ~2k tokens in and at most MAX_OUT out, at most PER_DAY calls a day
(a few cents a month), booked as kind "market" in critic_calls and held by the critic's monthly cap. Owner switch:
openai_kritika (the critic's own); MARKET_OSVRT=0 turns only this part off.
"""
import json
import os
import re
import time

from critic import openai_api, privacy, store

KEY = "market_osvrt"            # critic_kv: {"ts", "day", "model", "notes": [{"tema", "hr", "en"}]}
PER_DAY = 2
MIN_GAP_S = 6 * 3600
MAX_OUT = 1500
MAX_CHARS = 320
TEME = ("market", "calls", "launchpads", "dex", "season")

SYSTEM = """Ti si Kritičar, skeptični analitičar tržišta Solana meme coina. Pišeš kratke javne osvrte na brojke koje dobiješ.
Pravila:
- Koristi samo brojke iz poruke. Ne izmišljaj vijesti, uzroke ni cijene. Ako uzrok nije u podacima, ne nagađaj ga.
- Svaki osvrt ima 1 do 2 rečenice, najviše 300 znakova, i navodi barem jedan broj iz podataka.
- Reci što broj znači za običnog trejdera i na što treba paziti; budi trezven, bez uzbuđenja i bez žargona.
- Ne daj savjet za kupnju ili prodaju, ne obećavaj zaradu, ne spominji pojedine tokene, novčanike ni račune s društvenih mreža. Smiješ imenovati platforme iz podataka (npr. pump.fun).
- Bez linkova, bez znakova @ i $ ispred riječi, bez emojija.
- Za svaku temu napiši isti osvrt na hrvatskom (hr) i na engleskom (en). Teme bez dovoljno podataka izostavi.
Odgovaraj isključivo valjanim JSON-om po zadanoj shemi."""

TASK = """Zadatak: za svaku temu koja ima podatke napiši jedan osvrt. Teme: market (tržište danas), calls (pozivi influencera), launchpads, dex, season (indeks sezone meme coina, 0-100; 66+ vruće, do 33 hladno).
Ne ponavljaj samo broj: reci što je neobično ili na što broj upućuje u odnosu na prošli tjedan ili prosjek.
Izlaz JSON: {"osvrti":[{"tema":"market|calls|launchpads|dex|season","hr":"...","en":"..."}]}"""

SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["osvrti"],
    "properties": {"osvrti": {"type": "array", "items": {
        "type": "object", "additionalProperties": False, "required": ["tema", "hr", "en"],
        "properties": {"tema": {"type": "string", "enum": list(TEME)}, "hr": {"type": "string"},
                       "en": {"type": "string"}}}}},
}

BAD = [
    (re.compile(r"https?://|www\.|\.(?:com|app|io|fun|xyz)/", re.I), "link"),
    (re.compile(r"(?<!\w)@\w{2,}"), "račun"),
    (re.compile(r"\$[A-Za-z]{2,}"), "ticker"),
    (re.compile(r"\b[1-9A-HJ-NP-Za-km-z]{32,44}\b"), "adresa"),
    (re.compile(r"\b(kupi(te)?|kupuj(te)?|prodaj(te)?|uđi(te)?|buy now|you should (buy|sell)|sell now|go long|go short|"
                r"ape in|garantiran\w*|guarantee\w*|sigurn\w+ zarad\w+|risk[- ]free|bez rizika)\b", re.I), "savjet"),
]


def enabled():
    return (os.environ.get("MARKET_OSVRT") or "1").strip() not in ("0", "false", "off", "ne")


def _r(x, n=3):
    return None if x is None else round(float(x), n)


def payload(d):
    """The public aggregates of one marketpub snapshot, small and flat. None when there is nothing to read."""
    if not d:
        return None
    D = 86400
    day, ser = d["day"], d["ser"]

    def s7(k, end):
        w = [ser[k].get(end - i * D) for i in range(7)]
        return sum(w) if all(v is not None for v in w) else None

    def grp(k):
        a, b = s7(k, day), s7(k, day - 7 * D)
        return {"zadnji_dan_usd": _r(ser[k].get(day), 0), "7d_usd": _r(a, 0),
                "promjena_7d": _r(a / b - 1) if a and b else None}

    def plats(k, n):
        return [{"ime": p["name"], "7d_usd": _r(p["v7"], 0), "promjena_7d": _r(p["v7"] / p["p7"] - 1) if p["p7"] else None}
                for p in d["plats"][k][:n]]

    out = {"dan": time.strftime("%Y-%m-%d", time.gmtime(day)),
           "market": {"launchpadi": grp("launchpad"), "solana_dex_ukupno": grp("dex"), "terminali": grp("terminal"),
                      "sol_cijena": _r(d["price"].get(day), 2),
                      "sol_promjena_7d": _r(d["price"][day] / d["price"][day - 7 * D] - 1)
                      if d["price"].get(day) and d["price"].get(day - 7 * D) else None},
           "launchpads": plats("launchpad", 5), "dex": {"dexovi": plats("dex", 8), "terminali": plats("terminal", 5)}}
    reg = d.get("regime") or []
    if reg:
        _day, score, _lb, f = reg[-1]
        out["season"] = {"indeks": score, "prije_7_dana": reg[-8][1] if len(reg) >= 8 else None,
                         "rang_launchpad_volumena_90d": _r(f.get("launchpad_pct90"), 2),
                         "rang_dex_volumena_90d": _r(f.get("dex_pct90"), 2),
                         "rang_rasta_launchpada_90d": _r(f.get("launchpad_growth_pct90"), 2)}
    c = d.get("calls")
    if c:
        y = c["x"].get(c["day"]) or {}
        out["calls"] = {"x_poziva_zadnji_dan": y.get("calls"), "x_prosjek_7d": _r(c.get("calls_avg7"), 0),
                        "x_callera_zadnji_dan": y.get("callers"), "x_callera_prosjek_7d": _r(c.get("callers_avg7"), 0),
                        "udio_prvih_poziva_plus50_u_24h_7d": _r(c.get("hit7")), "isto_30d": _r(c.get("hit30")),
                        "napomena": "plus50 je vrh unutar 24 h, ne ostvariva zarada",
                        "medijan_mcap_na_pozivu_7d": _r(c.get("mc7"), 0), "isto_mcap_30d": _r(c.get("mc30"), 0),
                        "udio_rugova_7d": _r(c.get("rug7")), "udio_rugova_30d": _r(c.get("rug30")),
                        "pogodak_po_trzistu_90d": {k: _r(v["rate"]) for k, v in (c.get("regime") or {}).items()}}
    return out


def clean(notes):
    """The reads that may go public: [{"tema", "hr", "en"}], one per page, each checked. Returns (kept, dropped why)."""
    kept, dropped, seen = [], [], set()
    for n in notes or []:
        tema = n.get("tema")
        hr, en = (n.get("hr") or "").strip(), (n.get("en") or "").strip()
        why = None
        if tema not in TEME or tema in seen:
            why = "tema"
        elif not (20 <= len(hr) <= MAX_CHARS and 20 <= len(en) <= MAX_CHARS):
            why = "duljina"
        elif not (re.search(r"\d", hr) and re.search(r"\d", en)):
            why = "bez broja"
        else:
            why = next((lab for rx, lab in BAD if rx.search(hr) or rx.search(en)), None)
            if not why and (privacy.leaks(hr) or privacy.leaks(en)):
                why = "privatnost"
        if why:
            dropped.append(f"{tema}: {why}")
            continue
        seen.add(tema)
        kept.append({"tema": tema, "hr": hr, "en": en})
    return kept, dropped


def due(tcon, now):
    last = store.kv_get(tcon, KEY) or {}
    if now - (last.get("ts") or 0) < MIN_GAP_S:
        return False
    n = tcon.execute("SELECT COUNT(*) FROM critic_calls WHERE kind='market' AND ts>=?", (store.day_start(now),)).fetchone()[0]
    return n < PER_DAY


def run(now=None, log=print, tcon=None, call=None, snapshot=None, force=False):
    """One pass. Returns a small dict of what happened."""
    from critic import trades as ctrades
    now = int(now or time.time())
    own = tcon is None
    if own:
        from trade import executor, settings
        tcon = executor.connect(settings.DB)
    try:
        store.ensure(tcon)
        if not enabled() or not ctrades.enabled(tcon):
            return {"skip": "isključen"}
        if not openai_api.has_key():
            return {"skip": "nema ključa"}
        if not force and not due(tcon, now):
            return {"skip": "nije vrijeme"}
        if snapshot is None:
            from ui import marketpub
            snapshot = marketpub.build(now)
        data = payload(snapshot)
        if not data:
            return {"skip": "nema podataka"}
        text = TASK + "\n\nPodaci (JSON):\n" + json.dumps(data, ensure_ascii=False, separators=(",", ":"), default=str)
        text = privacy.scrub(text)
        bad = privacy.leaks(text)
        if bad:
            log(f"kritičar: osvrt na tržište nije poslan (privatnost: {', '.join(bad)})", flush=True)
            return {"skip": "privatnost"}
        model = openai_api.MODEL_CHEAP
        est = openai_api.max_cost(model, len(text) + len(SYSTEM), MAX_OUT)
        why = store.refusal(tcon, "market", est, now, log)
        if why:
            return {"skip": "budžet"}
        fn = call or openai_api.call_json
        try:
            res = fn(model, SYSTEM, text, SCHEMA, "kriticar_trziste", MAX_OUT, "low")
        except openai_api.ApiError as e:
            c = openai_api.cost(e.model or model, e.usage) if e.usage else 0.0
            store.book(tcon, "market", e.model or model, e.usage, c, False, str(e), text, now=now)
            log(f"kritičar: osvrt na tržište nije uspio ({e})", flush=True)
            return {"skip": "greška API-ja", "greska": str(e)}
        notes, dropped = clean((res.get("data") or {}).get("osvrti"))
        store.book(tcon, "market", res["model"], res["usage"], res["cost_usd"], bool(notes),
                   None if notes else "nijedan osvrt nije prošao provjeru", text, n=len(notes), now=now)
        if notes:
            store.kv_put(tcon, KEY, {"ts": now, "day": snapshot["day"], "model": res["model"], "notes": notes})
        log(f"kritičar: osvrt na tržište, {len(notes)} spremljeno"
            + (f", odbačeno {len(dropped)} ({'; '.join(dropped)})" if dropped else "")
            + f", trošak {res['cost_usd']:.4f} $ ({res['model']})", flush=True)
        return {"osvrta": len(notes), "odbaceno": dropped, "cost_usd": res["cost_usd"]}
    finally:
        if own:
            tcon.close()
