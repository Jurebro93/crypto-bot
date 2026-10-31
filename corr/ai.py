"""Claude reads the correlation snapshot and explains it in plain Croatian: which groups look organised, how they
work together, what to follow, which signals really go with pumps.

Needs ANTHROPIC_API_KEY (the same key as the morning e-mail report). Without it, or on any API error, the page
shows rule-based lines instead. One request per changed snapshot, at most every ai_every_h hours
(~12-20k tokens in, ~3k out; about $0.10-0.15 per run on the default model)."""
import json
import os

MODEL = os.environ.get("CORR_MODEL", "claude-opus-5-5")
PRICE = {"claude-opus-5-5": (4.0, 20.0), "claude-sonnet-5-5": (2.0, 10.0), "claude-haiku-5-5": (0.10, 0.50)}

SYSTEM = """Ti si analitičar on-chain i društvenih podataka za memecoin trading bota (Solana, pump.fun). Vlasnik želi
naći organizirane grupe: više X/Telegram računa iste ekipe, više walleta istog vlasnika, insidere koji kupe prije
poziva i prodaju u poziv. Cilj je ući prije gomile kad se signali poklope i izaći na +30-50%.

Dobivaš JSON s već izračunatim korelacijama:
- clusters: X računi (i Telegram kanali "tg:ime") koji zovu iste tokene unutar 30 min. overlap = udio poziva
  manjeg računa koji su zajednički, cohesion = prosječni overlap u grupi, spread_min = medijan minuta od prvog do
  zadnjeg člana, leader = tko najčešće zove prvi, hit_together / hit_solo = udio tokena koji su se udvostručili
  (2x u 24 h) kad grupa zove zajedno / kad član zove sam, late_share = udio zajedničkih poziva nakon što je token
  već pumpao. score 0-100 = koliko izgleda organizirano.
- pairs: najjači parovi računa (lift = koliko puta češće od slučajnosti).
- links: wallet koji kupi token prije poziva određenog računa (lead_min = koliko minuta prije), na više tokena;
  sold_into = na koliko tokena je prodao nakon poziva; strength 0-1; labels = oznake walleta (sniper, bot,
  insider...). Snajper koji kupuje sve nove tokene nije nužno povezan s računom.
- groups: walleti koji izgledaju kao jedan vlasnik (zajednički izvor novca, isti rug klaster, kupnje u istoj
  sekundi na više tokena); handles = računi s kojima su njihovi walleti povezani.
- factors: za tokene s KOL pozivom, udio 2x sa i bez signala (lift).
- active: tokeni koje poznata grupa dira u zadnjih nekoliko sati.

Pravila: piši hrvatski, kratko, jednostavno, bez programerskog žargona i bez naziva datoteka. Nikad ne izmišljaj:
koristi samo brojeve iz JSON-a, i kad je uzorak mali (n < 10) reci "malo podataka". Razlikuj dokaz od sumnje
(povjerenje: visoko / srednje / nisko). Ne obećavaj zaradu; govori o signalima. Za svaku grupu reci kako bi je
bot mogao iskoristiti (npr. "ulaz kad drugi član grupe pozove u 10 min nakon vođe", "izbjegavaj: kasni pozivi,
prodaju u poziv"). Grupe označi s pratiti=true samo ako praćenje ima smisla za ulaze ili kao upozorenje.
Za id grupe koristi točno id iz podataka."""

SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["naslov", "zakljucci", "grupe", "signali", "sada", "upozorenja", "sto_jos"],
    "properties": {
        "naslov": {"type": "string", "description": "jedna rečenica, najvažnije otkriće"},
        "zakljucci": {"type": "array", "items": {"type": "string"}, "description": "3-6 glavnih zaključaka"},
        "grupe": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "required": ["id", "ime", "tumacenje", "povjerenje", "pratiti", "kako_iskoristiti"],
            "properties": {
                "id": {"type": "string"}, "ime": {"type": "string", "description": "kratko ime grupe"},
                "tumacenje": {"type": "string", "description": "što grupa radi i kako se koordinira, s brojevima"},
                "povjerenje": {"type": "string", "enum": ["visoko", "srednje", "nisko"]},
                "pratiti": {"type": "boolean"},
                "kako_iskoristiti": {"type": "string"}}}},
        "signali": {"type": "array", "items": {
            "type": "object", "additionalProperties": False, "required": ["signal", "tumacenje"],
            "properties": {"signal": {"type": "string"}, "tumacenje": {"type": "string"}}}},
        "sada": {"type": "array", "items": {
            "type": "object", "additionalProperties": False, "required": ["token", "zasto"],
            "properties": {"token": {"type": "string"}, "zasto": {"type": "string"}}}},
        "upozorenja": {"type": "array", "items": {"type": "string"}},
        "sto_jos": {"type": "array", "items": {"type": "string"},
                    "description": "koji podaci bi najviše pomogli naći još veza (najviše 4)"},
    },
}


def compact(snap):
    """What the model needs, without long address lists (short wallet ids are enough to talk about them)."""
    d = json.loads(json.dumps(snap, default=str))
    for cl in d.get("clusters", []):
        cl["wallets"] = [w[:6] for w in cl.get("wallets", [])][:8]
        for e in cl.get("examples", []):
            e["token"] = e["token"][:6]
    for ln in d.get("links", []):
        ln["wallet"] = ln["wallet"][:6]
        ln.pop("token_list", None)
    for g in d.get("groups", []):
        g["wallets"] = [w[:6] for w in g["wallets"]][:8]
        g.pop("token_list", None)
    for a in d.get("active", []):
        a["token"] = (a.get("symbol") or a["token"][:6])
    d["links"] = d.get("links", [])[:40]
    d.pop("secs", None)
    return d


def interpret(snap):
    """(dict matching SCHEMA, model or 'pravila', cost in $)."""
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return fallback(snap), "pravila", 0.0
    try:
        import anthropic
    except ImportError:
        return fallback(snap), "pravila", 0.0
    client = anthropic.Anthropic(timeout=300, max_retries=2)
    prompt = ("Korelacije iz podataka bota (JSON, vremena su unix UTC). Protumači ih.\n\n"
              + json.dumps(compact(snap), ensure_ascii=False))
    kw = dict(model=MODEL, max_tokens=16000, system=SYSTEM, messages=[{"role": "user", "content": prompt}],
              output_config={"effort": "medium", "format": {"type": "json_schema", "schema": SCHEMA}})
    try:
        try:
            # if a safety classifier declines, the API re-runs the request on a fallback model
            resp = client.beta.messages.create(betas=["server-side-fallback-2026-07-01"], fallbacks="default", **kw)
        except anthropic.BadRequestError:
            resp = client.messages.create(**kw)
        if resp.stop_reason == "refusal":
            return fallback(snap), "pravila (model odbio)", 0.0
        text = "".join(b.text for b in resp.content if b.type == "text")
        out = json.loads(text)
        pin, pout = PRICE.get(MODEL, (4.0, 20.0))
        cost = (resp.usage.input_tokens * pin + resp.usage.output_tokens * pout) / 1e6
        return out, getattr(resp, "model", MODEL), round(cost, 4)
    except Exception as e:  # never break the page because of the interpretation
        print(f"korelacije: Claude nije uspio ({type(e).__name__}: {e}); pravila")
        return fallback(snap), "pravila", 0.0


def _p(x):
    return "?" if x is None else f"{x:.0%}"


def fallback(snap):
    """Plain lines straight from the numbers, used without an API key."""
    grupe, zak = [], []
    for cl in snap.get("clusters", [])[:8]:
        better = cl["hit_together"] is not None and cl["hit_solo"] is not None and cl["hit_together"] > cl["hit_solo"]
        grupe.append({
            "id": cl["id"], "ime": f"Grupa oko @{cl['leader']}" if cl["leader"] else "KOL grupa",
            "tumacenje": (f"{cl['size']} računa zove iste tokene ({cl['tokens']} puta), medijan {cl['spread_min']} min "
                          f"od prvog do zadnjeg. Zajedno 2x: {_p(cl['hit_together'])}, sami: {_p(cl['hit_solo'])}. "
                          f"Kasnih poziva {_p(cl['late_share'])}."),
            "povjerenje": "srednje" if cl["tokens"] >= 10 else "nisko", "pratiti": cl["score"] >= 60,
            "kako_iskoristiti": ("Kad vođa pozove, pratiti ulaze li ostali u idućih 30 min." if better else
                                 "Više kao upozorenje: zajednički pozivi nisu bolji od pojedinačnih.")})
    for g in snap.get("groups", [])[:6]:
        grupe.append({"id": g["id"], "ime": f"Walleti {g['wallets'][0][:4]}…",
                      "tumacenje": f"{g['size']} walleta, veze: " + ", ".join(f"{k} {v}" for k, v in g["reasons"].items())
                      + (f"; povezani s @{', @'.join(g['handles'][:3])}" if g["handles"] else ""),
                      "povjerenje": "nisko", "pratiti": g["score"] >= 60,
                      "kako_iskoristiti": "Pratiti kupuju li novi token prije poziva."})
    f = snap.get("factors", {})
    for x in f.get("factors", [])[:3]:
        zak.append(f"{x['factor']}: 2x u {_p(x['hit_yes'])} slučajeva (n={x['n_yes']}) naspram {_p(x['hit_no'])} bez.")
    return {"naslov": "Korelacije (bez AI tumačenja: AI ključ još nije postavljen)", "zakljucci": zak, "grupe": grupe,
            "signali": [], "sada": [{"token": a.get("symbol") or a["token"][:6],
                                     "zasto": ", ".join(f"{w['n']} iz grupe {w['id']}" for w in a["who"])}
                                    for a in snap.get("active", [])[:5]],
            "upozorenja": [], "sto_jos": []}
