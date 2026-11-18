"""Vijeće: one member's review of another member's proposal (18.11., vlasnik: "Claude i OpenAI moraju biti kritični
prema njemu, doraditi ga i prihvatiti ako se slažu").

ocijeni_openai / ocijeni_claude(note, kontekst) -> {"verdict": slazem | doradi | protiv, "critique",
"refined_change" (a dict in the shape of a note's proposed_change, or None), "kako_povecava_zaradu", "model", "usd"}.
The same Croatian system prompt and JSON schema for both. kontekst = {"ocjene": the reviews so far, "stanje": the
direction brief (vijece/smjer.brief), cut to STANJE_MAX}.

OpenAI: critic/openai_api.call_json (the Responses API with Structured Outputs; test seam critic.openai_api._urlopen).
Claude: the anthropic SDK exactly as report/ai.py calls it (server-side fallback first, plain messages on a 400, the
refusal check); the test seam is _claude_call. No key or no SDK = the member is "nedostupan" (Nedostupan), never a
crash. What leaves the server goes through critic/privacy.scrub first and is not sent when leaks() still finds
something.

ocijeni(con, clan, ...) is the wrapper the pass uses: the owner switch and the key, the member's day budget
(VIJECE_OPENAI_DAY_USD / VIJECE_CLAUDE_DAY_USD, 0.60 $ each, counted before the call with the most it can cost), the
call, the spend booked in vijece_kv (usage/daily.py shows it as "vijeće").
"""
import json
import os

from critic import openai_api, privacy
from vijece import store

STANJE_MAX = 6000
EVIDENCE_MAX = 3000
OPENAI_MAX_OUT = 3000
OPENAI_EFFORT = "low"
CLAUDE_MAX_TOKENS = 8000      # the answer and the model's own reasoning at effort medium (billed as output)
CLAUDE_TIMEOUT_S = 180
CLAUDE_USD_IN, CLAUDE_USD_OUT = 4.0, 20.0     # USD per 1M tokens (input, output)

SYSTEM = """Ti si član vijeća alata MemeSonar (trading bot za Solana midcap memecoine, market cap 2M-200M $). Vijeće
čine tri člana: Grok, OpenAI i Claude. Kad jedan član nešto predloži, druga dvojica moraju biti KRITIČNA prema
prijedlogu: provjeriti ga, doraditi ga i prihvatiti samo ako ima smisla. Vlasnikov cilj je jedan: veća NETO zarada
(PnL trgovanja minus trošak rada alata: API-ji, pretplate, SOL za podatke), i što više naučiti za što manje novca.

Za prijedlog pred tobom odgovori na ova pitanja, kratko i s brojevima:
1. Koji dokazi podupiru prijedlog? Navedi brojeve iz konteksta (n, postotci, $, SOL, krediti). Ako dokaza nema ili je
   uzorak malen (n < 20), reci to izravno.
2. Što može poći po zlu: gubitak podataka koje nešto drugo koristi, pristrano mjerenje, nepovratna šteta?
3. Povećava li NETO zaradu i KAKO točno: koliko štedi ili zarađuje, na dan ili po tradeu? Ako ne povećava, reci.
4. Je li mjerljivo (koji broj će pokazati uspjeh i do kada) i može li se vratiti na staro?

Presuda:
- "slazem": samo kad prijedlog ima smisla točno ovakav kakav jest.
- "doradi": slažeš se s namjerom, ali imaš konkretno bolju verziju. Opiši je u critique. Ako se dorada može izraziti
  kao promjena postavke, upiši je u refined_change kao JSON objekt (kao tekst) istog oblika kao predložena promjena,
  npr. {"key": "runup_max", "from": 0.15, "to": 0.10}; inače refined_change neka bude null.
- "protiv": ne povećava neto zaradu, nema dokaza ili je rizik veći od koristi. Navedi razlog.

Pravila: ne izmišljaj podatke i ne ponavljaj prijedlog, nego ga kritiziraj; ne povlađuj drugom članu, ali uzmi u
obzir njegovu ocjenu ako je već dana. Pravi novac (ulog, broj pozicija, TP, SL, prekidači pravog novca, autotrade)
uključuje i mijenja samo vlasnik: takvu promjenu možeš preporučiti, vijeće je ne primjenjuje. ODLUKE VLASNIKA u
kontekstu su njegove trajne odluke: prijedlog koji im proturječi odbij ("protiv") ili ga doradi tako da ih poštuje
("doradi"), nikad ga ne prihvaćaj takvog kakav jest. Oznake [adresa],
[skriveno] i [interno] su namjerno skrivene vrijednosti (adrese novčanika, interna imena): ne upisuj ih u
refined_change i ne odbijaj prijedlog samo zato što su skrivene. Piši hrvatski, jednostavno, najviše 1200 znakova u
critique i 400 u kako_povecava_zaradu."""

_NULLABLE_TEXT = {"anyOf": [{"type": "string"}, {"type": "null"}]}
SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["verdict", "critique", "refined_change", "kako_povecava_zaradu"],
    "properties": {
        "verdict": {"type": "string", "enum": list(store.VERDIKTI)},
        "critique": {"type": "string", "description": "dokazi, rizici, mjerljivost, povratnost; kod doradi i bolja verzija"},
        "refined_change": {**_NULLABLE_TEXT, "description": "samo uz doradi: JSON objekt promjene kao tekst, inače null"},
        "kako_povecava_zaradu": {"type": "string", "description": "kako i koliko mijenja neto zaradu (PnL minus trošak rada)"},
    },
}


class Nedostupan(Exception):
    """The member cannot be asked now (no key, no SDK, the owner's switch off): the proposal waits."""


class Greska(Exception):
    """A call that was made and failed or came back unusable; .usd is what it still cost."""
    def __init__(self, msg, usd=0.0, model=None):
        super().__init__(msg)
        self.usd, self.model = float(usd or 0), model


def claude_model():
    return os.environ.get("VIJECE_CLAUDE_MODEL") or "claude-opus-5-5"


def openai_model():
    return os.environ.get("VIJECE_OPENAI_MODEL") or openai_api.MODEL_DEEP


def claude_usd(tokens_in, tokens_out):
    return (int(tokens_in or 0) * CLAUDE_USD_IN + int(tokens_out or 0) * CLAUDE_USD_OUT) / 1e6


def claude_max_usd(chars_in, max_tokens):
    """The most one Claude call can cost (3 characters a token, as critic/openai_api.max_cost counts)."""
    return (chars_in / 3.0 * CLAUDE_USD_IN + max_tokens * CLAUDE_USD_OUT) / 1e6


# ---------- what is sent ---------------------------------------------------------------------------------------------

def _j(x, cap):
    s = json.dumps(x, ensure_ascii=False, default=str)
    return s if len(s) <= cap else s[:cap] + " …(skraćeno)"


def siguran_tekst(text, con=None):
    """The text as it may leave the server (critic/privacy.scrub + the council's own two patterns), or Greska when
    something private is still in it."""
    from vijece import smjer
    wallets = privacy.owner_wallets(con)
    s = smjer.ocisti(text, wallets)
    bad = privacy.leaks(s, (), extra=wallets)
    if bad:
        raise Greska(f"nije poslano (privatnost: {', '.join(bad)})")
    return s


def korisnik_tekst(note, kontekst=None, con=None):
    """The user text of one review: the proposal, the reviews so far, the state block."""
    k = kontekst or {}
    pc = note.get("proposed_change")
    parts = [f"PRIJEDLOG #{note.get('id')} (predlagač: {store.IME[note.get('predlagac') or store.predlagac(note.get('key_id'))]})",
             f"Naslov: {note.get('title') or ''}",
             f"Obrazloženje: {note.get('interpretation') or ''}"]
    if note.get("improvement"):
        parts.append(f"Poboljšanje: {note['improvement']}")
    if note.get("evidence"):
        parts.append("Dokazi (JSON): " + _j(note["evidence"], EVIDENCE_MAX))
    parts.append("Predložena promjena postavke (JSON): " + _j(pc, 2000) if pc else
                 "Predložena promjena postavke: nema (prijedlog traži izmjenu koda ili načina rada)")
    oc = k.get("ocjene") or {}
    if oc:
        parts.append("DOSADAŠNJE OCJENE DRUGIH ČLANOVA:")
        for m, o in oc.items():
            parts.append(f"- {store.IME.get(m, m)}: {o.get('verdict')}: {store.kratko(o.get('critique'), 1500)}"
                         + (f" | dorada: {_j(o['refined_change'], 600)}" if o.get("refined_change") else ""))
    else:
        parts.append("DOSADAŠNJE OCJENE DRUGIH ČLANOVA: još nema")
    st = str(k.get("stanje") or "").strip()
    from vijece import smjer   # here, not at the top: smjer imports this module
    if smjer.ODLUKE_NASLOV not in st[:STANJE_MAX]:   # a brief stored before 18.11. (an open session) does not carry them
        parts.append(smjer.odluke_vlasnika())
    parts.append("STANJE ALATA (izmjereno):\n" + (st[:STANJE_MAX] if st else "nije dostupno"))
    return siguran_tekst("\n".join(parts), con)


def _refined(x):
    """A reviewer's refined change as a dict, or None (not given, or not one JSON object)."""
    if isinstance(x, str):
        x = x.strip()
        if not x or x.lower() in ("null", "none"):
            return None
        try:
            x = json.loads(x)
        except ValueError:
            return None
    return x if isinstance(x, dict) and x else None


def validiraj(d):
    """{"verdict", "critique", "refined_change", "kako_povecava_zaradu"} of an answer; ValueError when unusable."""
    if not isinstance(d, dict):
        raise ValueError("odgovor nije objekt")
    v = str(d.get("verdict") or "").strip().lower()
    if v not in store.VERDIKTI:
        raise ValueError("nepoznata presuda")
    crit = str(d.get("critique") or "").strip()
    if not crit:
        raise ValueError("nema kritike")
    return {"verdict": v, "critique": crit[:3000],
            "refined_change": _refined(d.get("refined_change")) if v == "doradi" else None,
            "kako_povecava_zaradu": str(d.get("kako_povecava_zaradu") or "").strip()[:1000]}


# ---------- OpenAI ---------------------------------------------------------------------------------------------------

def openai_json(model, system, text, schema, name, max_out):
    """One OpenAI Structured Outputs call -> {"data", "model", "usd"}; Nedostupan without a key, Greska on failure."""
    if not openai_api.has_key():
        raise Nedostupan("nema ključa")
    try:
        res = openai_api.call_json(model, system, text, schema, name, max_out, OPENAI_EFFORT)
    except openai_api.ApiError as e:
        usd = openai_api.cost(e.model or model, e.usage) if e.usage else 0.0
        raise Greska(str(e), usd, e.model or model) from None
    return {"data": res["data"], "model": res["model"], "usd": res["cost_usd"]}


def ocijeni_openai(note, kontekst=None, model=None, con=None):
    text = korisnik_tekst(note, kontekst, con)
    res = openai_json(model or openai_model(), SYSTEM, text, SCHEMA, "vijece_ocjena", OPENAI_MAX_OUT)
    return _gotovo(res)


def _gotovo(res):
    try:
        out = validiraj(res["data"])
    except ValueError as e:
        raise Greska(f"neispravan odgovor: {e}", res.get("usd"), res.get("model")) from None
    out.update(model=res.get("model"), usd=float(res.get("usd") or 0))
    return out


# ---------- Claude ---------------------------------------------------------------------------------------------------

def _claude_call(system, text, schema, max_tokens):
    """One Claude call -> {"data", "model", "usd"} (the test seam: tests replace this function, nothing reaches the
    network then). The same pattern as report/ai.interpret: JSON by schema, effort medium, the server-side fallback
    first and the plain call on a 400; no thinking, temperature or forced tool_choice (this model answers 400)."""
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise Nedostupan("nema ključa")
    try:
        import anthropic
    except ImportError:
        raise Nedostupan("nema anthropic SDK-a") from None
    client = anthropic.Anthropic(timeout=CLAUDE_TIMEOUT_S, max_retries=2)
    model = claude_model()
    kw = dict(model=model, max_tokens=int(max_tokens), system=system, messages=[{"role": "user", "content": text}],
              output_config={"effort": "medium", "format": {"type": "json_schema", "schema": schema}})
    try:
        try:
            # server-side fallback: if a safety classifier declines, the API re-runs on a fallback model
            resp = client.beta.messages.create(betas=["server-side-fallback-2026-07-01"], fallbacks="default", **kw)
        except anthropic.BadRequestError:
            resp = client.messages.create(**kw)
    except Exception as e:  # noqa: BLE001 - the SDK's errors: the proposal waits, the pass goes on
        raise Greska(f"{type(e).__name__}: {str(e)[:160]}", 0.0, model) from None
    u = getattr(resp, "usage", None)
    usd = claude_usd(getattr(u, "input_tokens", 0), getattr(u, "output_tokens", 0))
    used = getattr(resp, "model", None) or model
    if resp.stop_reason == "refusal":
        raise Greska("model odbio", usd, used)
    try:
        data = json.loads("".join(b.text for b in resp.content if b.type == "text"))
    except ValueError:
        raise Greska("odgovor nije valjan JSON", usd, used) from None
    return {"data": data, "model": used, "usd": usd}


def claude_json(system, text, schema, max_tokens):
    """_claude_call behind the key check (so a stubbed seam still needs the key, as the real call does)."""
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise Nedostupan("nema ključa")
    return _claude_call(system, text, schema, max_tokens)


def ocijeni_claude(note, kontekst=None, con=None):
    text = korisnik_tekst(note, kontekst, con)
    return _gotovo(claude_json(SYSTEM, text, SCHEMA, CLAUDE_MAX_TOKENS))


# ---------- availability, budget, the booked call --------------------------------------------------------------------

def nedostupan(con, clan):
    """Why the member cannot be asked at all (Croatian), or None. OpenAI also follows the owner switch of the OpenAI
    critic (openai_kritika): switched off there, it is not asked here either."""
    if clan == "openai":
        if not openai_api.has_key():
            return "nema ključa"
        try:
            from critic import trades as ctrades
            if not ctrades.enabled(con):
                return "prekidač OpenAI kritičara je isključen"
        except Exception:  # noqa: BLE001 - the switch cannot be read: the key decides
            pass
        return None
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return "nema ključa"
    return None


def model_u_budzetu(con, clan, chars, max_out, now=None):
    """(model, None) for the member's next call when its most fits the day budget, else (None, why). OpenAI falls
    back to the cheap model (critic/openai_api.MODEL_CHEAP) when the strong one does not fit, as critic/store.pick."""
    t = store.trosak(con, now)[clan]
    cap = store.strop(clan)
    if clan == "openai":
        order = [openai_model()]
        if openai_api.MODEL_CHEAP and openai_api.MODEL_CHEAP not in order:
            order.append(openai_api.MODEL_CHEAP)
        for m in order:
            if t + openai_api.max_cost(m, chars, max_out) <= cap:
                return m, None
    elif t + claude_max_usd(chars, max_out) <= cap:
        return claude_model(), None
    return None, f"dnevni budžet {cap:.2f} $ potrošen ({t:.3f} $)".replace(".", ",")


def pitaj(con, clan, system, text, schema, name, max_out, now=None):
    """One booked call of a member: {"data", "model", "usd"}. Nedostupan (no key, switch, budget: nothing was spent)
    or Greska (the call failed; what it cost is booked)."""
    why = nedostupan(con, clan)
    if why:
        raise Nedostupan(why)
    model, why = model_u_budzetu(con, clan, len(text) + len(system), max_out, now)
    if model is None:
        raise Nedostupan(why)
    try:
        res = (openai_json(model, system, text, schema, name, max_out) if clan == "openai"
               else claude_json(system, text, schema, max_out))
    except Greska as e:
        store.dodaj_trosak(con, clan, e.usd, now)
        raise
    store.dodaj_trosak(con, clan, res.get("usd"), now)
    return res


def ocijeni(con, clan, note, kontekst=None, now=None):
    """The member's review of a note, booked: the dict of ocijeni_openai / ocijeni_claude. Nedostupan: the member
    cannot review now (the note waits); Greska: this call failed."""
    text = korisnik_tekst(note, kontekst, con)
    max_out = OPENAI_MAX_OUT if clan == "openai" else CLAUDE_MAX_TOKENS
    return _gotovo(pitaj(con, clan, SYSTEM, text, SCHEMA, "vijece_ocjena", max_out, now))
