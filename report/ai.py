"""Claude reads the collected numbers and writes the interpretation (Croatian, short, direct).

Needs ANTHROPIC_API_KEY; without it (or on any API error) the report falls back to plain rule-based lines, so
the email still goes out. One request per day (~15k tokens in, ~3k out)."""
import json
import os

MODEL = os.environ.get("REPORT_MODEL", "claude-opus-5-5")

SYSTEM = """Ti si analitičar memecoin trading bota (Solana, pump.fun) i svako jutro pišeš vlasniku kratak izvještaj na hrvatskom.
Vlasnik ne želi gledati 100 mjesta: ti iz brojeva izvlačiš zaključke. Piši jednostavno, direktno, bez žargona gdje nije nužan,
kratke rečenice, konkretni brojevi (postotci, n). Nikad ne izmišljaj podatke: ako nešto nije izmjereno ili je uzorak mali
(n < 10), reci to jednom riječju ("malo podataka"). Ne daj financijske savjete kao sigurnost: "mogli bi", "signal", ne "kupi".

Kontekst bota:
- Sesije trgovanja (UTC): Azija 00-08, Europa 08-14, SAD 14-24. Bot uči točnost KOL signala po sesiji (faktor 0.7-1.3).
- Razine tokena: T0 = samo mehanika ruga (mint/freeze authority, LP); klase tokena; "skok" = top 15% u klasi.
- Težine hype ocjene se same uče svaki dan po klasi, uz zaštitu (min. ishoda, max pomak 20% po pokretanju, bolje na obje polovice).
  Kad fit želi veću promjenu, sve takve težine pomaknu se za točno 20%: to je ta zaštita, ne greška u učenju.
- Izlazi (TP/SL/trailing) se uče po klasi i sesiji iz putanja cijena, s rollbackom ako live rezultati padnu.
- KOL = influencer na X-u; score 0-100 iz pogodaka (definicija u kol_hit_definition), medijana max 24 h, kasnih poziva (nakon pumpe), rugova.
  Retrospektiva: broj pregleda posta i broj autora koji zajedno zovu predviđaju pumpe, broj followera ne predviđa.
  Tokeni s KOL pozivom dođu do 2x u 52% slučajeva naspram 14% bez.
- Puls = tokeni kojima holderi i volumen rastu kroz zadnja 24 h (organska snaga).
- Retrospektiva (25k tokena): najbolji ulaz je prvi prelazak $100k MC (2x 24%, 5x 9%); ulazi na graduaciji imaju medijan -94%.

Prijedloge za poboljšanje algoritma temelji na onome što vidiš u podacima (rupe, slabi signali, mali uzorci, faktori koji nedostaju),
konkretno i izvedivo, s procjenom koristi. Najviše 5 prijedloga, najvažniji prvi."""

SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["naslov", "ukratko", "naucio", "kol_komentar", "kol_pratiti", "danas_komentar", "danas_istaknuti",
                 "puls_komentar", "prijedlozi", "upozorenja"],
    "properties": {
        "naslov": {"type": "string", "description": "jedna rečenica, glavna poruka dana"},
        "ukratko": {"type": "array", "items": {"type": "string"}, "description": "3-5 najvažnijih zaključaka"},
        "naucio": {"type": "array", "items": {"type": "string"},
                   "description": "što se promijenilo u težinama, izlazima i točnosti po sesijama, i što to znači"},
        "kol_komentar": {"type": "string"},
        "kol_pratiti": {"type": "array", "items": {
            "type": "object", "additionalProperties": False, "required": ["handle", "zasto"],
            "properties": {"handle": {"type": "string"}, "zasto": {"type": "string"}}}},
        "danas_komentar": {"type": "string", "description": "koja sesija danas nosi najviše, i zašto"},
        "danas_istaknuti": {"type": "array", "items": {
            "type": "object", "additionalProperties": False, "required": ["simbol", "zasto"],
            "properties": {"simbol": {"type": "string"}, "zasto": {"type": "string"}}}},
        "puls_komentar": {"type": "string"},
        "prijedlozi": {"type": "array", "items": {
            "type": "object", "additionalProperties": False, "required": ["naslov", "opis", "prioritet"],
            "properties": {"naslov": {"type": "string"}, "opis": {"type": "string"},
                           "prioritet": {"type": "string", "enum": ["visok", "srednji", "nizak"]}}}},
        "upozorenja": {"type": "array", "items": {"type": "string"}},
    },
}


def compact(data):
    """The collected data without the long series, so the prompt stays small."""
    d = json.loads(json.dumps(data, default=str))
    for p in d.get("pulse", []):
        hs = p.pop("holders_series", [])
        p.pop("vol_series", None)
        p["holders_hourly_sample"] = hs[::4]
    for t in d.get("today", {}).get("tokens", []):
        t["shares"] = {k: round(v, 2) for k, v in (t.get("shares") or {}).items()}
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


def fallback(data):
    """Plain lines from the numbers, used without an API key."""
    w, ex, acc, k = data["weights"], data["exits"], data["sessions"], data["kols"]
    naucio = []
    for r in w["runs"]:
        top = ", ".join(f"{t['feature']} {t['old']}→{t['new']}" for t in r["top"][:3])
        naucio.append(f"Klasa {r['klasa']}: težine {'primijenjene' if r['applied'] else 'nisu primijenjene'} "
                      f"(n={r['n']}){': ' + top if top and r['applied'] else ''}.")
    for c in ex["changed"]:
        naucio.append(f"Izlazi {c['profil']}: nova verzija v{c['v']}.")
    for s, v in acc.items():
        sig = v.get("signal") or v.get("call")
        if sig:
            naucio.append(f"{s}: točnost KOL signala {_pct(sig['hit'])} (n={sig['n']}), faktor {sig['factor']:.2f}.")
    if not naucio:
        naucio = ["Jučer nije bilo promjena težina ni izlaza (premalo novih ishoda ili zaštita nije pustila)."]
    p = data["paper"]
    ukr = [f"Demo trading: {p['closed']} zatvorenih, {p['wins']} u plusu, PnL ${p['pnl']:,.0f}."]
    if k["top"]:
        ukr.append(f"Najbolji KOL po scoreu: @{k['top'][0]['handle']} ({k['top'][0]['score']}).")
    return {"naslov": "Jutarnji izvještaj (bez AI interpretacije: dodaj ANTHROPIC_API_KEY)",
            "ukratko": ukr, "naucio": naucio, "kol_komentar": "",
            "kol_pratiti": [{"handle": x["handle"], "zasto": f"pogodak {_pct(x['hit_rate'])} na {x['measured']} poziva"}
                            for x in k["top"][:4]],
            "danas_komentar": "", "danas_istaknuti": [], "puls_komentar": "", "prijedlozi": [], "upozorenja": []}
