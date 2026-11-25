"""Čuvari imena (tvrdi): nacrt se ne lansira kad
  1. DexScreener pretraga (besplatno, kroz postojeći limiter dexscreener/client) nađe token istog imena ili simbola s
     likvidnošću ≥ MIN_LIQ_USD (50k $): „postoji poznat token istog imena: ne oponašamo”;
  2. ime, simbol ili opis sadrži riječ s popisa zabranjenih (BANNED + vlasnikov popis u kv 'zabranjene') ili „by <ime>”;
  3. opis (ili ime/simbol) sadrži URL ili domenu;
  4. polja nisu u granicama (ime 1-32, simbol 2-10 slova/brojki, opis 1-500 znakova).
Neuspjela pretraga DexScreenera je odbijanje („provjera nije uspjela”), nikad prolaz.
"""
import re
import time

MIN_LIQ_USD = 50_000
FRESH_S = 24 * 3600     # provjera starija od ovoga se ponavlja prije slanja (posao je ionako ponavlja)
SIMILAR = "postoji poznat token istog imena: ne oponašamo"
BANNED = ("official", "officially", "oficijalni", "službeni", "sluzbeni", "ovjeren", "ovjereni", "verified",
          "guaranteed", "guarantee", "zajamčen", "zajamcen", "airdrop", "giveaway", "presale", "100x", "1000x",
          "get rich", "profit", "returns")
_BY = re.compile(r"\bby\s+[A-Za-z@][\w.@-]*", re.I)
_URL = re.compile(r"(https?://|www\.|\bt\.me/|\b[a-z0-9-]+\.(com|io|fun|xyz|net|org|app|gg|me|co|so|ai|dev|link|"
                  r"site|info|finance|money|cash|meme|lol|wtf|tv|to|ly|sh)\b)", re.I)
_SYM = re.compile(r"^[A-Z0-9]{2,10}$")


def banned_list(extra=()):
    return [w.strip().lower() for w in list(BANNED) + list(extra or ()) if w and w.strip()]


def word_hits(text, extra=()):
    """Zabranjene riječi u tekstu (cijele riječi, bez obzira na velika slova) + „by <ime>”."""
    t = (text or "").lower()
    out = []
    for w in banned_list(extra):
        if re.search(rf"(?<![\w]){re.escape(w)}(?![\w])", t):
            out.append(w)
    m = _BY.search(text or "")
    if m:
        out.append(f"„{m.group(0)}”")
    return out


def has_url(text):
    return bool(_URL.search(text or ""))


def form_reasons(d, extra=()):
    """Razlozi odbijanja bez mreže (polja, riječi, URL)."""
    why = []
    ime, sim, opis = (d.get("ime") or "").strip(), (d.get("simbol") or "").strip(), (d.get("opis") or "").strip()
    if not 1 <= len(ime) <= 32:
        why.append("ime mora imati 1-32 znaka")
    if not _SYM.match(sim):
        why.append("simbol: 2-10 velikih slova ili brojki")
    if not 1 <= len(opis) <= 500:
        why.append("opis mora imati 1-500 znakova")
    for label, txt in (("ime", ime), ("simbol", sim), ("opis", opis)):
        hits = word_hits(txt, extra)
        if hits:
            why.append(f"{label} sadrži zabranjeno: {', '.join(hits)}")
        if has_url(txt):
            why.append(f"{label} sadrži poveznicu ili domenu (nije dopušteno)")
    if not d.get("slika"):
        why.append("nema slike")
    return why


def _f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return 0.0


def similar(name, symbol, pairs, min_liq=MIN_LIQ_USD):
    """[(simbol, ime, chain, likvidnost)] postojećih tokena istog imena ili simbola s likvidnošću ≥ min_liq (zbroj
    po tokenu preko svih parova koje je pretraga vratila)."""
    n, s = (name or "").strip().lower(), (symbol or "").strip().upper()
    by = {}
    for p in pairs or []:
        b = (p or {}).get("baseToken") or {}
        bn, bs = (b.get("name") or "").strip().lower(), (b.get("symbol") or "").strip().upper()
        if not ((n and bn == n) or (s and bs == s)):
            continue
        key = (p.get("chainId"), b.get("address"))
        e = by.setdefault(key, [b.get("symbol"), b.get("name"), p.get("chainId"), 0.0])
        e[3] += _f((p.get("liquidity") or {}).get("usd"))
    return sorted([tuple(e) for e in by.values() if e[3] >= min_liq], key=lambda e: -e[3])


def _search(q):
    from dexscreener import client   # isti put i limiter kao ostali (280/min, predmemorija 60 s)
    return client.search(q)


def check(d, extra=(), search=None, now=None):
    """{"ok", "razlozi": [...], "dex": tekst, "slicni": [...], "ts"} za jedan nacrt. search(q) -> parovi (za test)."""
    now = int(now or time.time())
    why = form_reasons(d, extra)
    search = search or _search
    found, dex = [], ""
    try:
        pairs = []
        seen = set()
        for q in (d.get("ime"), d.get("simbol")):
            q = (q or "").strip()
            if q and q.lower() not in seen:
                seen.add(q.lower())
                pairs += search(q) or []
        found = similar(d.get("ime"), d.get("simbol"), pairs)
        if found:
            why.append(SIMILAR)
            top = found[0]
            dex = f"nađen {top[0]} ({top[1]}, {top[2]}) s likvidnošću {top[3]:,.0f} $"
        else:
            dex = f"DexScreener: nema tokena istog imena ili simbola s likvidnošću ≥ {MIN_LIQ_USD:,.0f} $"
    except Exception as e:  # noqa: BLE001 - a search that failed is a refusal, never a pass
        why.append("provjera DexScreenera nije uspjela: pokušaj ponovno")
        dex = f"DexScreener nedostupan ({type(e).__name__})"
    return {"ok": not why, "razlozi": why, "dex": dex, "slicni": [list(x) for x in found[:5]], "ts": now}


def fresh_ok(res, now=None):
    return bool(res and res.get("ok") and (now or time.time()) - (res.get("ts") or 0) <= FRESH_S)
