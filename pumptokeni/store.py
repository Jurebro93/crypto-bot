"""pump_tokeni.db: nacrti tokena, pokušaji lansiranja, ishodi i postavke pokusa (vidi pumptokeni/__init__.py).

Stanja nacrta (nacrti.stanje): 'nacrt' → 'u_redu' (vlasnik: Lansiraj) → 'salje' (posao) → 'lansiran' | 'greska';
'odbijen' kad čuvar imena ili simulacija odbije prije slanja; 'u_redu' → 'nacrt' kad vlasnik makne iz reda.
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
"""

DRAFT_STATES = ("nacrt", "u_redu", "salje", "lansiran", "greska", "odbijen")
ATTEMPT_STATES = ("priprema", "poslano", "lansiran", "neuspio", "nepoznato", "odbijeno")
DRAFT_FIELDS = ("tema", "datum_teme", "ime", "simbol", "opis", "skupina")

# 25.11. (vlasnik): večeras prvih 5, opće nadolazeće teme (bez osoba, brendova i postojećih tokena); opisi kratki,
# istiniti, engleski, bez obećanja zarade i bez poveznica
SKUPINA_0 = "opce-teme-0sol"
SEED = (
    ("Dan zahvalnosti (SAD)", "2026-11-26", "Gobble", "GOBBLE",
     "A meme coin for Thanksgiving Day, November 26. Turkey, pie and a long nap. Just a meme: no roadmap, no promises."),
    ("Black Friday", "2026-11-27", "Doorbuster", "DOORB",
     "A meme coin for Black Friday, November 27: the crowd at the door before the store opens. Just a meme: no roadmap, "
     "no promises."),
    ("Cyber Monday", "2026-11-30", "Cart Goblin", "CARTGOB",
     "A meme coin for Cyber Monday, November 30: the little goblin who fills the cart at midnight. Just a meme: no "
     "roadmap, no promises."),
    ("Prosinački rast tržišta", "2026-12-24", "Santa Rally", "SRALLY",
     "A meme coin about the Santa rally, the old market saying about late December. Just a meme, not advice: no "
     "roadmap, no promises."),
    ("Nova godina", "2027-01-01", "Twenty Seven", "Y2027",
     "A meme coin for New Year 2027. Twenty seven, here we go. Just a meme: no roadmap, no promises."),
)


def db_path():
    return os.environ.get("PUMP_TOKENI_DB") or os.path.join(os.environ.get("DATA_DIR") or ROOT, "pump_tokeni.db")


def connect(path=None):
    con = sqlite3.connect(path or db_path(), timeout=15)
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
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


def seed(con, now=None, image_fn=None):
    """Pet nacrta za večeras, jednom (kv 'seed_2511'); slika iz generatora. Broj dodanih."""
    if get(con, "seed_2511"):
        return 0
    if image_fn is None:
        from pumptokeni import image
        image_fn = image.generate
    now = int(now or time.time())
    for tema, datum, ime, simbol, opis in SEED:
        con.execute("INSERT INTO nacrti (tema, datum_teme, ime, simbol, opis, slika, skupina, stanje, napravljen_ts, "
                    "promijenjen_ts) VALUES (?,?,?,?,?,?,?,'nacrt',?,?)",
                    (tema, datum, ime, simbol, opis, image_fn(ime, simbol), SKUPINA_0, now, now))
    put(con, "seed_2511", now)
    return len(SEED)


def drafts(con):
    return [dict(r) for r in con.execute("SELECT * FROM nacrti ORDER BY id")]


def draft(con, did):
    r = con.execute("SELECT * FROM nacrti WHERE id=?", (did,)).fetchone()
    return dict(r) if r else None


def add_draft(con, fields, image_png=None, own_image=False, now=None):
    now = int(now or time.time())
    f = {k: (fields.get(k) or "").strip() for k in DRAFT_FIELDS}
    cur = con.execute("INSERT INTO nacrti (tema, datum_teme, ime, simbol, opis, slika, slika_vlastita, skupina, stanje, "
                      "napravljen_ts, promijenjen_ts) VALUES (?,?,?,?,?,?,?,?,'nacrt',?,?)",
                      (f["tema"], f["datum_teme"], f["ime"], f["simbol"].upper(), f["opis"], image_png,
                       1 if own_image else 0, f["skupina"] or SKUPINA_0, now, now))
    con.commit()
    return cur.lastrowid


def update_draft(con, did, fields, now=None):
    """Vlasnikova izmjena polja; poništava provjeru i spremljeni meta_uri (novo ime = novi metapodaci). Samo nacrt koji
    još nije poslan (nacrt, odbijen, greska, u_redu)."""
    d = draft(con, did)
    if not d:
        raise ValueError("nema tog nacrta")
    if d["stanje"] in ("salje", "lansiran"):
        raise ValueError("lansiran (ili se upravo šalje) nacrt se ne mijenja")
    sets = {k: (fields.get(k) or "").strip() for k in DRAFT_FIELDS if k in fields}
    if "simbol" in sets:
        sets["simbol"] = sets["simbol"].upper()
    if not sets:
        return d
    sql = ", ".join(f"{k}=?" for k in sets)
    con.execute(f"UPDATE nacrti SET {sql}, provjera=NULL, provjera_ts=NULL, meta_uri=NULL, promijenjen_ts=? WHERE id=?",
                (*sets.values(), int(now or time.time()), did))
    con.commit()
    return draft(con, did)


def set_image(con, did, png, own, now=None):
    con.execute("UPDATE nacrti SET slika=?, slika_vlastita=?, meta_uri=NULL, promijenjen_ts=? WHERE id=?",
                (png, 1 if own else 0, int(now or time.time()), did))
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
        assert k in ("mint", "potpis", "stanje", "saldo_prije", "saldo_poslije", "trosak_sol", "sim_sol", "greska"), k
    if "stanje" in cols:
        assert cols["stanje"] in ATTEMPT_STATES, cols["stanje"]
    con.execute(f"UPDATE pokusaji SET {', '.join(f'{k}=?' for k in cols)} WHERE id=?", (*cols.values(), aid))
    con.commit()
