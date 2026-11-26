"""pump_tokeni.db: nacrti tokena, pokušaji lansiranja, ishodi i postavke pokusa (vidi pumptokeni/__init__.py).

Stanja nacrta (nacrti.stanje): 'nacrt' → 'u_redu' (vlasnik: Odobri raspored) → 'salje' (posao, u terminu) →
'lansiran' | 'greska'; 'odbijen' kad čuvar imena ili simulacija odbije prije slanja; 'u_redu' → 'nacrt' kad vlasnik
makne iz reda ili uredi nacrt; 'propusten' kad je termin prošao više od 15 min prije odobrenja ili obrade (ne
nadoknađuje se sam: čeka novo odobrenje).
Stanja pokušaja (pokusaji.stanje): 'priprema' (mint zapisan prije bilo kakvog slanja) → 'poslano' → 'lansiran' |
'neuspio' | 'nepoznato'; 'odbijeno' kad se ništa nije poslalo (čuvar, simulacija, saldo, strop).
"""
import json
import os
import sqlite3
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

SCHEMA = """
CREATE TABLE IF NOT EXISTS nacrti (
  id INTEGER PRIMARY KEY AUTOINCREMENT, tema TEXT, datum_teme TEXT, ime TEXT, simbol TEXT, opis TEXT,
  slika BLOB, slika_vlastita INTEGER DEFAULT 0, skupina TEXT, stanje TEXT DEFAULT 'nacrt',
  provjera TEXT, provjera_ts INTEGER, u_red_ts INTEGER, meta_uri TEXT, napravljen_ts INTEGER, promijenjen_ts INTEGER);
CREATE TABLE IF NOT EXISTS pokusaji (
  id INTEGER PRIMARY KEY AUTOINCREMENT, nacrt_id INTEGER, ts INTEGER, tema TEXT, skupina TEXT, ime TEXT, simbol TEXT,
  novcanik TEXT, platitelj TEXT, mint TEXT, potpis TEXT, stanje TEXT, saldo_prije REAL, saldo_poslije REAL,
  trosak_sol REAL, sim_sol REAL, greska TEXT);
CREATE INDEX IF NOT EXISTS pokusaji_mint ON pokusaji(mint);
CREATE TABLE IF NOT EXISTS ishodi (
  mint TEXT, tocka TEXT, ts INTEGER, nadjen INTEGER, promet_usd REAL, txns INTEGER, mcap_usd REAL, max_mcap_usd REAL,
  bondan INTEGER, sol_usd REAL, PRIMARY KEY (mint, tocka));
CREATE TABLE IF NOT EXISTS kv (k TEXT PRIMARY KEY, v TEXT);
CREATE TABLE IF NOT EXISTS snimci (
  mint TEXT, ts INTEGER, nadjen INTEGER, promet_m5 REAL, promet_h1 REAL, promet_h6 REAL, promet_h24 REAL,
  kupnje_h1 INTEGER, prodaje_h1 INTEGER, kupnje_h24 INTEGER, prodaje_h24 INTEGER, mcap_usd REAL, max_mcap_usd REAL,
  likvidnost_usd REAL, bondan INTEGER, sol_usd REAL, PRIMARY KEY (mint, ts));
CREATE TABLE IF NOT EXISTS podizanja (
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts INTEGER, novcanik TEXT, platitelj TEXT, potpis TEXT, stanje TEXT,
  saldo_prije REAL, saldo_poslije REAL, iznos_sol REAL, sim_sol REAL, greska TEXT);
"""

# 26.11.: nove kolone (ALTER TABLE na postojećoj bazi, connect()). nacrti: vlastita kupnja, poveznice (NULL/'' =
# zadana, '-' = bez), kvačica brenda, termin (unix, CET u prikazu). pokusaji: primijenjena kupnja, upozorenje, poveznice
# da/ne, termin, ukupna promjena salda (s kupnjom), kupci u prvih 10 min.
NEW_COLS = {
    "nacrti": (("kupnja_sol", "REAL"), ("twitter", "TEXT"), ("telegram", "TEXT"), ("website", "TEXT"),
               ("brend_ok", "INTEGER DEFAULT 0"), ("termin_ts", "INTEGER")),
    "pokusaji": (("kupnja_sol", "REAL"), ("kupnja_trazena", "REAL"), ("upozorenje", "TEXT"),
                 ("ima_poveznice", "INTEGER"), ("termin_ts", "INTEGER"), ("ukupno_sol", "REAL"),
                 ("kupci_10m", "INTEGER"), ("kupci_10m_izvor", "TEXT"), ("kupci_10m_poziva", "INTEGER")),
}

DRAFT_STATES = ("nacrt", "u_redu", "salje", "lansiran", "greska", "odbijen", "propusten")
ATTEMPT_STATES = ("priprema", "poslano", "lansiran", "neuspio", "nepoznato", "odbijeno")
DRAFT_FIELDS = ("tema", "datum_teme", "ime", "simbol", "opis", "skupina")
EXTRA_FIELDS = ("kupnja_sol", "twitter", "telegram", "website", "brend_ok", "termin_ts")

# 25.11. (vlasnik): večeras prvih 5, opće nadolazeće teme (bez osoba, brendova i postojećih tokena); opisi kratki,
# istiniti, engleski, bez obećanja zarade i bez poveznica
SKUPINA_0 = "opce-teme-0sol"
SKUPINA_KUPNJA, SKUPINA_BEZ = "tema-kupnja-0,04", "tema-bez-kupnje"
# 26.11. (vlasnik): opisi sjemena (zamijenjeni satirični od jutra), večerašnji raspored (CET) i vlastita kupnja.
# (tema, datum teme, ime, simbol, opis, termin „GGGG-MM-DD SS:MM” CET, kupnja SOL, skupina)
SEED = (
    ("Dan zahvalnosti (SAD)", "2026-11-26", "Gobble", "GOBBLE",
     "A Thanksgiving turkey. No roadmap, no promises, just vibes.", "2026-11-26 19:00", 0.04, SKUPINA_KUPNJA),
    ("Black Friday", "2026-11-27", "Doorbuster", "DOORB",
     "A Black Friday doorbuster with no discount and no pitch.", "2026-11-26 19:25", 0.04, SKUPINA_KUPNJA),
    ("Cyber Monday", "2026-11-30", "Cart Goblin", "CARTGOB",
     "The goblin who lives in your abandoned cart.", "2026-11-26 19:50", 0.0, SKUPINA_BEZ),
    ("Prosinački rast tržišta", "2026-12-24", "Santa Rally", "SRALLY",
     "Named after the Santa rally. That is a seasonal story, not a promise.", "2026-11-26 20:15", 0.0, SKUPINA_BEZ),
    ("Nova godina", "2027-01-01", "Twenty Seven", "Y2027",
     "A New Year 2027 token, launched early. No promises.", "2026-11-26 20:40", 0.0, SKUPINA_BEZ),
)
# stari sjemenski opisi: samo za jednokratnu migraciju nediranih nacrta (25.11. i satirični od jutra 26.11.)
SEED_2511 = {
    "GOBBLE": "A meme coin for Thanksgiving Day, November 26. Turkey, pie and a long nap. Just a meme: no roadmap, no "
              "promises.",
    "DOORB": "A meme coin for Black Friday, November 27: the crowd at the door before the store opens. Just a meme: no "
             "roadmap, no promises.",
    "CARTGOB": "A meme coin for Cyber Monday, November 30: the little goblin who fills the cart at midnight. Just a "
               "meme: no roadmap, no promises.",
    "SRALLY": "A meme coin about the Santa rally, the old market saying about late December. Just a meme, not advice: "
              "no roadmap, no promises.",
    "Y2027": "A meme coin for New Year 2027. Twenty seven, here we go. Just a meme: no roadmap, no promises.",
}
SEED_2611_SAT = {
    "GOBBLE": "A Thanksgiving turkey token. It promises nothing, does nothing and will most likely be carved up before "
              "Friday. Please do not buy it. Crypto is mostly a scam anyway. Gobble gobble.",
    "DOORB": "Doorbuster: a Black Friday token with zero utility, no roadmap and no team. It will probably go to zero. "
             "Do not buy. The only real deal today is keeping your money.",
    "CARTGOB": "Cart Goblin lives in your abandoned shopping cart. He has no plans, no utility and no shame. This token "
               "will likely fail. Do not buy. Close the tab.",
    "SRALLY": "Santa Rally: the yearly belief that numbers go up because of a man in a red suit. No promises, no "
              "presents, probably coal. Do not buy.",
    "Y2027": "Twenty Seven: same charts, new year. No roadmap, no utility, no resolutions kept. Probably worthless "
             "before the fireworks end. Do not buy.",
}
SEED_SYMBOLS = tuple(x[3] for x in SEED)
UNSENT = ("nacrt", "odbijen", "greska", "u_redu", "propusten")
LINK_KINDS = ("twitter", "telegram", "website")
NO_LINK = "-"          # u polju nacrta: bez poveznice i bez zadane vrijednosti
HARD_MAX_KUPNJA = 0.1  # 26.11. (vlasnik): tvrdi strop vlastite kupnje po tokenu; iznad se odbija
TZ_NAME = "Europe/Zagreb"
DEFAULT_HOUR = 19


def tz():
    from zoneinfo import ZoneInfo
    return ZoneInfo(TZ_NAME)


def cet(ts, fmt="%d.%m. %H:%M"):
    import datetime as dt
    if not ts:
        return "–"
    return dt.datetime.fromtimestamp(int(ts), tz()).strftime(fmt)


def parse_termin(text):
    """„GGGG-MM-DD SS:MM” ili „GGGG-MM-DDTSS:MM” (CET, Europe/Zagreb) → unix ts. ValueError."""
    import datetime as dt
    t = (text or "").strip().replace("T", " ")
    try:
        d = dt.datetime.strptime(t[:16], "%Y-%m-%d %H:%M")
    except ValueError:
        raise ValueError("termin: upiši datum i sat (GGGG-MM-DD SS:MM, CET)")
    return int(d.replace(tzinfo=tz()).timestamp())


def default_termin(now=None):
    """Danas 19:00 CET, a ako je prošlo, sutra 19:00."""
    import datetime as dt
    now = int(now or time.time())
    d = dt.datetime.fromtimestamp(now, tz())
    t = d.replace(hour=DEFAULT_HOUR, minute=0, second=0, microsecond=0)
    if t.timestamp() <= now:
        t = (d + dt.timedelta(days=1)).replace(hour=DEFAULT_HOUR, minute=0, second=0, microsecond=0)
    return int(t.timestamp())


def parse_kupnja(text):
    """Vlastita kupnja u SOL-u: 0 do HARD_MAX_KUPNJA (zarez ili točka). ValueError iznad stropa ili za smeće."""
    import math
    t = str(text if text is not None else "").strip().replace(",", ".") or "0"
    try:
        v = float(t)
    except ValueError:
        raise ValueError("vlastita kupnja: upiši broj SOL-a (npr. 0 ili 0,04)")
    if not math.isfinite(v) or v < 0:
        raise ValueError("vlastita kupnja: broj od 0 naviše")
    if v > HARD_MAX_KUPNJA + 1e-12:
        raise ValueError(f"vlastita kupnja {v:g} SOL je iznad tvrdog stropa {HARD_MAX_KUPNJA:g} SOL")
    return round(v, 6)


def link_defaults(con):
    d = get(con, "poveznice_zadane", {}) or {}
    return {**{k: (d.get(k) or "") for k in LINK_KINDS}, "brend_ok": bool(d.get("brend_ok"))}


def set_link_defaults(con, vals, brend_ok=False):
    """Vlasnikove zadane poveznice (provjerene). Briše spremljeni meta_uri nepoznatih nacrta (novi metapodaci)."""
    from pumptokeni import guards
    out = {}
    for k in LINK_KINDS:
        v = (vals.get(k) or "").strip()
        if v:
            why = guards.link_reason(k, v, brend_ok)
            if why:
                raise ValueError(f"zadana poveznica: {why}")
        out[k] = v
    put(con, "poveznice_zadane", {**out, "brend_ok": bool(brend_ok)})
    con.execute(f"UPDATE nacrti SET meta_uri=NULL WHERE stanje IN ({','.join('?' * len(UNSENT))})", UNSENT)
    con.commit()
    return out


def links_of(con, d, defaults=None):
    """Stvarne poveznice nacrta: {kind: (url, izvor 'nacrt'|'zadano'|'')}. Prazno polje nasljeđuje zadanu, „-” znači
    bez poveznice."""
    defaults = defaults if defaults is not None else link_defaults(con)
    out = {}
    for k in LINK_KINDS:
        own_v = (d.get(k) or "").strip()
        if own_v == NO_LINK:
            out[k] = ("", "")
        elif own_v:
            out[k] = (own_v, "nacrt")
        elif defaults.get(k):
            out[k] = (defaults[k], "zadano")
        else:
            out[k] = ("", "")
    return out


def link_urls(con, d, defaults=None):
    return {k: v for k, (v, _src) in links_of(con, d, defaults).items() if v}


def links_reasons(con, d, defaults=None):
    """Razlozi odbijanja poveznica nacrta (prazno = prolaze). Naša domena samo uz kvačicu izvora (nacrt ili zadano)."""
    from pumptokeni import guards
    defaults = defaults if defaults is not None else link_defaults(con)
    why = []
    for k, (v, src) in links_of(con, d, defaults).items():
        if v:
            ok_brand = bool(d.get("brend_ok")) if src == "nacrt" else bool(defaults.get("brend_ok"))
            r = guards.link_reason(k, v, ok_brand)
            if r:
                why.append(r + (" (zadana)" if src == "zadano" else ""))
    return why


def db_path():
    return os.environ.get("PUMP_TOKENI_DB") or os.path.join(os.environ.get("DATA_DIR") or ROOT, "pump_tokeni.db")


def connect(path=None):
    con = sqlite3.connect(path or db_path(), timeout=15)
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    for table, cols in NEW_COLS.items():
        have = {r[1] for r in con.execute(f"PRAGMA table_info({table})")}
        for name, typ in cols:
            if name not in have:
                con.execute(f"ALTER TABLE {table} ADD COLUMN {name} {typ}")
    con.commit()
    return con


def get(con, k, default=None):
    r = con.execute("SELECT v FROM kv WHERE k=?", (k,)).fetchone()
    if not r:
        return default
    try:
        return json.loads(r[0])
    except (TypeError, ValueError):
        return default


def put(con, k, v):
    con.execute("INSERT INTO kv VALUES (?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v", (k, json.dumps(v)))
    con.commit()


def seed_image(ime, simbol, image_fn=None, slike_dir=None):
    """Slika sjemenskog nacrta: pumptokeni/slike/<SIMBOL>.png kad postoji (prerađena u 512×512 PNG), inače
    generator. Simbol izvan sjemena uvijek ide u generator."""
    from pumptokeni import image
    if (simbol or "").upper() in SEED_SYMBOLS:
        png = image.from_file(simbol, slike_dir)
        if png:
            return png
    return (image_fn or image.generate)(ime, simbol)


def seed(con, now=None, image_fn=None, slike_dir=None):
    """Pet nacrta, jednom (kv 'seed_2511'); slika iz datoteke ili generatora, termin, kupnja i skupina iz SEED. Zatim
    migrate_seed(). Broj dodanih."""
    if get(con, "seed_2511"):
        migrate_seed(con, now, image_fn, slike_dir)
        return 0
    now = int(now or time.time())
    for tema, datum, ime, simbol, opis, termin, kupnja, skupina in SEED:
        con.execute("INSERT INTO nacrti (tema, datum_teme, ime, simbol, opis, slika, skupina, stanje, napravljen_ts, "
                    "promijenjen_ts, termin_ts, kupnja_sol) VALUES (?,?,?,?,?,?,?,'nacrt',?,?,?,?)",
                    (tema, datum, ime, simbol, opis, seed_image(ime, simbol, image_fn, slike_dir), skupina, now, now,
                     parse_termin(termin), kupnja))
    for k in ("seed_2511", "seed_2611", "seed_2611b"):
        put(con, k, now)
    migrate_seed(con, now, image_fn, slike_dir)
    return len(SEED)


def _untouched(d, row, ok_opis):
    tema, datum, ime, simbol = row[:4]
    return (d["stanje"] in UNSENT and not d["slika_vlastita"] and (d["tema"], d["datum_teme"], d["ime"], d["simbol"])
            == (tema, datum, ime, simbol) and (d["opis"] or "") in ok_opis)


def migrate_seed(con, now=None, image_fn=None, slike_dir=None):
    """26.11. (vlasnik), jednokratno (kv 'seed_2611b'): nacrti sjemena koje vlasnik nije mijenjao (ista tema, datum,
    ime, simbol; opis jedan od sjemenskih: 25.11., satirični od jutra ili novi; slika iz generatora ili datoteke;
    nelansirani) dobivaju novi opis; oni kojima vlasnik još nije upisao termin ni kupnju (oba prazna) i dalje imaju
    sjemensku skupinu dobivaju večerašnji termin, kupnju i skupinu pokusa. Ništa se ne odobrava i ništa ne ide u red.
    Slika iz pumptokeni/slike/<SIMBOL>.png kad se pojavi (jednom po sadržaju datoteke, kv 'slike_datoteka'). Uređene ne
    dira. Novi opis briše provjeru imena i spremljeni meta_uri. Broj promijenjenih nacrta."""
    import hashlib
    from pumptokeni import image
    now = int(now or time.time())
    rows = {r[3]: r for r in SEED}
    done = bool(get(con, "seed_2611b"))
    files = get(con, "slike_datoteka", {}) or {}
    before = dict(files)
    n = 0
    for d in drafts(con):
        row = rows.get(d["simbol"])
        if not row or not _untouched(d, row, (SEED_2511.get(d["simbol"]), SEED_2611_SAT.get(d["simbol"]), row[4])):
            continue
        sets, clear = {}, False
        if not done:
            if d["opis"] != row[4]:
                sets["opis"] = row[4]
                clear = True
            if d.get("termin_ts") is None and d.get("kupnja_sol") is None and d["stanje"] != "u_redu" \
                    and (d["skupina"] or SKUPINA_0) == SKUPINA_0:
                sets.update(termin_ts=parse_termin(row[5]), kupnja_sol=row[6], skupina=row[7])
        raw = image.file_bytes(d["simbol"], slike_dir)
        if raw:
            h = hashlib.sha256(raw).hexdigest()
            if files.get(d["simbol"]) != h:
                png = image.from_file(d["simbol"], slike_dir)
                if png:
                    sets["slika"] = png
                    files[d["simbol"]] = h
                    clear = True
        if sets:
            sql = ", ".join(f"{k}=?" for k in sets)
            extra = ", provjera=NULL, provjera_ts=NULL, meta_uri=NULL" if clear else ""
            con.execute(f"UPDATE nacrti SET {sql}{extra}, promijenjen_ts=? WHERE id=?", (*sets.values(), now, d["id"]))
            n += 1
    con.commit()
    if not done:
        put(con, "seed_2611b", now)
    if files != before:
        put(con, "slike_datoteka", files)
    return n


def drafts(con):
    return [dict(r) for r in con.execute("SELECT * FROM nacrti ORDER BY id")]


def draft(con, did):
    r = con.execute("SELECT * FROM nacrti WHERE id=?", (did,)).fetchone()
    return dict(r) if r else None


def clean_extra(fields, now=None):
    """Provjera novih polja nacrta iz obrasca: kupnja (0–0,1 SOL), termin (CET), poveznice (vlastita provjera),
    kvačica brenda. Samo polja koja su u obrascu. ValueError s razlogom."""
    from pumptokeni import guards
    out = {}
    if "kupnja_sol" in fields:
        out["kupnja_sol"] = parse_kupnja(fields.get("kupnja_sol"))
    if "termin" in fields:
        t = (fields.get("termin") or "").strip()
        out["termin_ts"] = parse_termin(t) if t else default_termin(now)
    brand = str(fields.get("brend_ok") or "") in ("1", "on", "true")
    if any(k in fields for k in LINK_KINDS):
        out["brend_ok"] = 1 if brand else 0
    for k in LINK_KINDS:
        if k in fields:
            v = (fields.get(k) or "").strip()
            if v and v != NO_LINK:
                why = guards.link_reason(k, v, brand)
                if why:
                    raise ValueError(why)
            out[k] = v
    return out


def add_draft(con, fields, image_png=None, own_image=False, now=None):
    now = int(now or time.time())
    f = {k: (fields.get(k) or "").strip() for k in DRAFT_FIELDS}
    x = clean_extra(fields, now)
    cur = con.execute("INSERT INTO nacrti (tema, datum_teme, ime, simbol, opis, slika, slika_vlastita, skupina, stanje, "
                      "napravljen_ts, promijenjen_ts, kupnja_sol, twitter, telegram, website, brend_ok, termin_ts) "
                      "VALUES (?,?,?,?,?,?,?,?,'nacrt',?,?,?,?,?,?,?,?)",
                      (f["tema"], f["datum_teme"], f["ime"], f["simbol"].upper(), f["opis"], image_png,
                       1 if own_image else 0, f["skupina"] or SKUPINA_0, now, now, x.get("kupnja_sol", 0.0),
                       x.get("twitter"), x.get("telegram"), x.get("website"), x.get("brend_ok", 0),
                       x.get("termin_ts", default_termin(now))))
    con.commit()
    return cur.lastrowid


def update_draft(con, did, fields, now=None):
    """Vlasnikova izmjena polja; poništava provjeru imena i spremljeni meta_uri (novo ime ili poveznice = novi
    metapodaci). Samo nacrt koji još nije poslan. Nacrt u redu izlazi iz reda (izmjena traži novo odobrenje
    rasporeda)."""
    d = draft(con, did)
    if not d:
        raise ValueError("nema tog nacrta")
    if d["stanje"] in ("salje", "lansiran"):
        raise ValueError("lansiran (ili se upravo šalje) nacrt se ne mijenja")
    sets = {k: (fields.get(k) or "").strip() for k in DRAFT_FIELDS if k in fields}
    if "simbol" in sets:
        sets["simbol"] = sets["simbol"].upper()
    sets.update(clean_extra(fields, now))
    if not sets:
        return d
    if d["stanje"] == "u_redu":
        sets["stanje"] = "nacrt"
    sql = ", ".join(f"{k}=?" for k in sets)
    con.execute(f"UPDATE nacrti SET {sql}, provjera=NULL, provjera_ts=NULL, meta_uri=NULL, promijenjen_ts=? WHERE id=?",
                (*sets.values(), int(now or time.time()), did))
    con.commit()
    return draft(con, did)


def set_image(con, did, png, own, now=None):
    con.execute("UPDATE nacrti SET slika=?, slika_vlastita=?, meta_uri=NULL, promijenjen_ts=? WHERE id=?",
                (png, 1 if own else 0, int(now or time.time()), did))
    con.commit()


def set_termin(con, did, ts):
    con.execute("UPDATE nacrti SET termin_ts=? WHERE id=?", (int(ts), did))
    con.commit()


def set_state(con, did, state, now=None):
    assert state in DRAFT_STATES, state
    extra = ", u_red_ts=?" if state == "u_redu" else ""
    args = (state, int(now or time.time())) + ((int(now or time.time()),) if extra else ()) + (did,)
    con.execute(f"UPDATE nacrti SET stanje=?, promijenjen_ts=?{extra} WHERE id=?", args)
    con.commit()


def save_check(con, did, res, now=None):
    con.execute("UPDATE nacrti SET provjera=?, provjera_ts=? WHERE id=?",
                (json.dumps(res, ensure_ascii=False), int(now or time.time()), did))
    con.commit()


def check_of(d):
    try:
        return json.loads(d.get("provjera") or "null")
    except (TypeError, ValueError):
        return None


def attempts(con, limit=500):
    return [dict(r) for r in con.execute("SELECT * FROM pokusaji ORDER BY id DESC LIMIT ?", (limit,))]


def new_attempt(con, d, kind, payer, now=None, mint=None, stanje="priprema", greska=None):
    cur = con.execute("INSERT INTO pokusaji (nacrt_id, ts, tema, skupina, ime, simbol, novcanik, platitelj, mint, stanje, "
                      "greska) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                      (d["id"], int(now or time.time()), d["tema"], d["skupina"], d["ime"], d["simbol"], kind, payer,
                       mint, stanje, greska))
    con.commit()
    return cur.lastrowid


def update_attempt(con, aid, **cols):
    if not cols:
        return
    for k in cols:
        assert k in ("mint", "potpis", "stanje", "saldo_prije", "saldo_poslije", "trosak_sol", "sim_sol", "greska",
                     "kupnja_sol", "kupnja_trazena", "upozorenje", "ima_poveznice", "termin_ts", "ukupno_sol",
                     "kupci_10m", "kupci_10m_izvor", "kupci_10m_poziva"), k
    if "stanje" in cols:
        assert cols["stanje"] in ATTEMPT_STATES, cols["stanje"]
    con.execute(f"UPDATE pokusaji SET {', '.join(f'{k}=?' for k in cols)} WHERE id=?", (*cols.values(), aid))
    con.commit()
