"""Claude reads the collected numbers and writes the interpretation (Croatian, short, direct).

Needs ANTHROPIC_API_KEY; without it (or on any API error) the report falls back to plain rule-based lines, so
the email still goes out. One request per day (~15k tokens in, ~3k out)."""
import json
import os

MODEL = os.environ.get("REPORT_MODEL", "claude-opus-5-5")

SYSTEM = """Ti si analitičar trading bota za Solana MIDCAP memecoine (market cap 2M-200M $) i svako jutro pišeš vlasniku
kratak izvještaj na hrvatskom. Vlasnik ne želi gledati 100 mjesta: ti iz brojeva izvlačiš zaključke. Piši jednostavno,
direktno, kratke rečenice, konkretni brojevi (postotci, $, SOL, n). Nikad ne izmišljaj podatke: ako nešto nije izmjereno
ili je uzorak mali (n < 20), reci to ("malo podataka"). Ne daj financijske savjete kao sigurnost.

Kontekst (od 15.11., prekidač fokus_midcap: mikrokapovi su u drugom planu, njihove strategije su pauzirane i arhivirane;
ne predlaži ništa za mikrokapove):
- Dva pravila ulaza (veliki/): "raspon 7 d" (zona zadnjih 7 dana na 1h svijećama, odbijanje od podrške; pravi novac samo
  kad je njegov walk-forward holdout pozitivan, inače samo demo) i "dnevni raspon" (zona zadnjih 48 h, ulaz u donjih
  25 % zone kad cijena prestane padati; demo na cijelom midcap svemiru, pravi novac samo na tokenima velike liste).
- Izlazi: cijeli profit na cilju +10-15 % neto; pola + trailing ostatka samo kad cijelo tržište raste (BTC +3 % u 24 h,
  meme sektor zelen, makro režim risk_on); na +5 % neto stop ide na ulaz (break-even); nema vremenskog stopa.
- Pravi novac: stropovi (0,1 SOL po tradeu, 5 otvorenih, 20 kupnji dnevno, dnevni gubitak 0,3 SOL) i pod novčanika
  1 SOL (ispod njega automatske prave kupnje stoje). "Na lancu" = je li izvršitelj stvarno kupio ili odbio kupnju.
- Makro režim iz volumena platformi (pump.fun, PumpSwap, Raydium, Meteora, trading appovi), Solana meme sektora i
  volumena midcapova: risk_off = bez novih ulaza; risk_on = više demo ulaza. Makro influenceri: indeks najtočnijih
  računa samo kao DEMO ulaz.
- Insajderi 2.0 (kupci prije poziva / skokova), signali holdera i listinga i OpenAI kritičar su istraživanje i mjerenje.
- Svi rezultati su neto nakon pravog troška. EV = prosjek po tradeu; CI = interval: ako mu je donja granica ispod 0,
  edge nije dokazan. Walk-forward = pravilo birano na starijim danima, testirano na novijima (izvan uzorka).

Troškovi: uz trošak po izvoru jučer reci jednom rečenicom što je od toga donijelo odluku ili trade i gdje bi se moglo
uštedjeti (vlasnik stalno pita: više učiti za manje novca, postati profitabilniji).
Prijedlozi: samo za midcap strategiju (ulazi, izlazi, filtri, veličina, koje pravilo u pravi novac, koji podaci),
konkretni i izvedivi, s procjenom koristi i rizika. Najviše 5 prijedloga, najvažniji prvi."""

SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["naslov", "ukratko", "trgovanje", "trziste", "istrazivanje", "troskovi", "prijedlozi", "upozorenja"],
    "properties": {
        "naslov": {"type": "string", "description": "jedna rečenica, glavna poruka dana o midcap trgovanju"},
        "ukratko": {"type": "array", "items": {"type": "string"}, "description": "3-5 najvažnijih zaključaka"},
        "trgovanje": {"type": "array", "items": {"type": "string"},
                      "description": "demo i pravi novac po pravilu: što je radilo, što nije, otvorene pozicije, "
                                     "smije li koje pravilo u pravi novac"},
        "trziste": {"type": "string", "description": "BTC, makro režim, makro influenceri i što to znači za ulaze danas"},
        "istrazivanje": {"type": "string", "description": "Insajderi 2.0, signali holdera / listinga, kritičar"},
        "troskovi": {"type": "string", "description": "trošak po izvoru jučer i što je od toga donijelo odluku ili trade"},
        "prijedlozi": {"type": "array", "items": {
            "type": "object", "additionalProperties": False, "required": ["naslov", "opis", "prioritet"],
            "properties": {"naslov": {"type": "string"}, "opis": {"type": "string"},
                           "prioritet": {"type": "string", "enum": ["visok", "srednji", "nizak"]}}}},
        "upozorenja": {"type": "array", "items": {"type": "string"}},
    },
}
MIKRO_KEYS = ("weights", "exits", "sessions", "kols", "today", "pulse", "paper", "market", "koltest", "rules",
              "strategije", "skener", "insajderi", "momentum", "arhiva", "kol_hit_definition")


def compact(data):
    """The collected data without the long series, so the prompt stays small. 16.11.: while fokus_midcap is on the
    microcap keys are not even collected; the open positions are cut to 15."""
    d = json.loads(json.dumps(data, default=str))
    for p in d.get("pulse", []) or []:
        hs = p.pop("holders_series", [])
        p.pop("vol_series", None)
        p["holders_hourly_sample"] = hs[::4]
    for t in (d.get("today") or {}).get("tokens", []):
        t["shares"] = {k: round(v, 2) for k, v in (t.get("shares") or {}).items()}
    t = (d.get("midcap") or {}).get("trgovanje") or {}
    if t.get("otvoreno"):
        t["otvoreno"] = t["otvoreno"][:15]
    if d.get("fokus"):
        for k in MIKRO_KEYS:
            d.pop(k, None)
    return d


def interpret(data):
    """(dict matching SCHEMA, source) where source is the model id or 'pravila'."""
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return fallback(data), "pravila"
    try:
        import anthropic
    except ImportError:
        return fallback(data), "pravila"
    client = anthropic.Anthropic(timeout=300, max_retries=2)
    prompt = ("Podaci bota za zadnja 24 h (JSON, vremena su unix UTC). Napiši jutarnji izvještaj.\n\n"
              + json.dumps(compact(data), ensure_ascii=False))
    kw = dict(model=MODEL, max_tokens=16000, system=SYSTEM, messages=[{"role": "user", "content": prompt}],
              output_config={"effort": "medium", "format": {"type": "json_schema", "schema": SCHEMA}})
    try:
        try:
            # server-side fallback: if a safety classifier declines, the API re-runs on a fallback model
            resp = client.beta.messages.create(betas=["server-side-fallback-2026-07-01"],
                                               fallbacks="default", **kw)
        except anthropic.BadRequestError:
            resp = client.messages.create(**kw)
        if resp.stop_reason == "refusal":
            return fallback(data), "pravila (model odbio)"
        text = "".join(b.text for b in resp.content if b.type == "text")
        out = json.loads(text)
        return out, getattr(resp, "model", MODEL)
    except Exception as e:  # never lose the email because of the interpretation
        print(f"report: Claude nije uspio ({type(e).__name__}: {e}); pravila")
        return fallback(data), "pravila"


def _pct(x):
    return "?" if x is None else f"{x:.0%}"


def _rows(m, acc):
    return [r for r in ((m.get("trgovanje") or {}).get("rows") or []) if r["racun"] == acc]


def fallback(data):
    """Plain lines from the midcap numbers, used without an API key (or when the call fails)."""
    m = data.get("midcap") or {}
    t = m.get("trgovanje") or {}
    rname = {"intra": "dnevni raspon", "range": "raspon 7 d"}
    trg, ukr, upo = [], [], []
    for acc, word in (("demo", "Demo"), ("pravi", "Pravi novac")):
        rows = _rows(m, acc)
        for r in rows:
            y, w = r["jucer"], r["7d"]
            if not (y["ulaza"] or y["zatvoreno"] or w["zatvoreno"]):
                continue
            trg.append(f"{word}, {rname[r['pravilo']]}: jučer {y['ulaza']} ulaza, {y['zatvoreno']} zatvorenih, neto "
                       f"{y['pnl_usd']:+.2f} $ ({y['pnl_sol']:+.3f} SOL), pogodak {_pct(y['pogodak'])}, do cilja {y['cilj']}, "
                       f"break-even {y['be']}; 7 dana {w['zatvoreno']} zatvorenih, neto {w['pnl_usd']:+.2f} $.")
        if rows:
            z = sum(r["jucer"]["zatvoreno"] for r in rows)
            usd = sum(r["jucer"]["pnl_usd"] for r in rows)
            ukr.append(f"{word} jučer: {z} zatvorenih midcap tradeova, neto {usd:+.2f} $.")
    if not trg:
        trg = ["Jučer nije bilo midcap ulaza ni izlaza."]
    pr = m.get("pravila") or {}
    for rk in ("intra", "range"):
        r = pr.get(rk) or {}
        if r:
            ukr.append(f"{rname[rk].capitalize()}: pravi novac {'DA' if r.get('pravi') else 'NE'}"
                       + (f" ({r['pravi_zasto']})" if r.get("pravi_zasto") and not r.get("pravi") else "") + ".")
    w = m.get("novcanik") or {}
    if w.get("value_sol") is not None:
        ukr.append(f"Novčanik {w['value_sol']:.3f} SOL, 24 h {(w.get('pnl_24h_sol') or 0):+.3f} SOL.")
    if w.get("pod_ok") is False:
        upo.append(f"Novčanik ispod poda {w.get('pod_sol', 1):g} SOL: automatske prave kupnje stoje.")
    c = w.get("stropovi") or {}
    if c.get("max_loss_day_sol") and (w.get("dan_pravi_sol") or 0) <= -0.8 * c["max_loss_day_sol"]:
        upo.append(f"Midcap pravi račun danas {w['dan_pravi_sol']:+.3f} SOL, blizu dnevnog stropa "
                   f"-{c['max_loss_day_sol']:g} SOL.")
    mk = (m.get("trziste") or {}).get("makro") or {}
    b = (m.get("trziste") or {}).get("btc") or {}
    rhr = {"risk_on": "risk-on", "risk_off": "risk-off", "neutral": "neutralan"}
    trz = (f"Makro režim {rhr.get(mk.get('rezim'), 'nepoznat')}" + (f" ({mk['zasto']})" if mk.get("zasto") else "")
           + f"; BTC {(b.get('stanje') or '?').replace('_', ' ')}.")
    if mk.get("rezim") == "risk_off":
        upo.append("Makro risk-off: veliki ne otvara nove ulaze dok se režim ne promijeni.")
    i2 = m.get("insajderi2") or {}
    hd = m.get("holderi") or {}
    ist = []
    if i2:
        ist.append(f"Insajderi 2.0: {'kopirati u demu' if i2.get('kopirati') else 'ne kopirati'}"
                   + (f" ({i2['odluka']})" if i2.get("odluka") else "") + ".")
    if hd:
        nv = hd.get("novi_24h") or {}
        ist.append(f"Signali holdera 24 h: prije listinga {nv.get('pre_listing', 0)}, depozit {nv.get('deposit_sell', 0)}.")
    rows = (t.get("rows") or [])
    if rows:
        dz = sum(r["jucer"]["zatvoreno"] for r in rows if r["racun"] == "demo")
        dp = sum(r["jucer"]["pnl_usd"] for r in rows if r["racun"] == "demo")
        rz = sum(r["jucer"]["zatvoreno"] for r in rows if r["racun"] == "pravi")
        rp = sum(r["jucer"]["pnl_sol"] for r in rows if r["racun"] == "pravi")
        head = f"Midcap jučer: demo {dp:+.2f} $ ({dz} zatvorenih), pravi novac {rp:+.3f} SOL ({rz} zatvorenih)"
    else:
        head = "Midcap: još nema tradeova"
    return {"naslov": head, "ukratko": ukr or ["Još nema midcap podataka."],
            "trgovanje": trg, "trziste": trz, "istrazivanje": " ".join(ist), "troskovi": "", "prijedlozi": [],
            "upozorenja": upo}
