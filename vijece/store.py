"""Vijeće: storage, roles, the queue and the day's spend (18.11., vlasnik: "kad Grok pošalje prijedlog, Claude i OpenAI
moraju biti kritični ... isto tako ako OpenAI ima prijedlog, Grok i Claude").

trade.db (next to assistant_notes, created lazily like ui/assistnotes.ensure):
  vijece_ocjene  one review per (note, reviewer): verdict slazem | doradi | protiv, the critique, the refined change
                 (a JSON object in the shape of a note's proposed_change, NULL when the refinement is only text), the
                 model and what the call cost
  vijece_odluke  one decision per note: prihvaceno_primijenjeno | prihvaceno_za_izvedbu | odbijeno | vlasniku, the
                 reason (both critiques) and what was applied
  vijece_kv      small state: the day's spend per member (trosak:<UTC day>), the direction session, "said once" marks

Who proposed a note is read from its key fingerprint: critic/notes.KID = OpenAI, key_id("claude-vijece") = Claude, any
other key (the MCP client's) = Grok. The reviewers are the other two. Only suggestion notes with status novo written
after the feature's first run (trade settings vijece_start_ts) are the council's: the old backlog stays the owner's.
"""
import json
import os
import sqlite3
import time

from critic import notes as cnotes
from trade import settings
from ui import assistnotes

CLANOVI = ("openai", "claude", "grok")
IME = {"openai": "OpenAI", "claude": "Claude", "grok": "Grok"}
API_CLANOVI = ("openai", "claude")          # asked from here; Grok answers through the MCP tools when it polls
CLAUDE_KEY = "claude-vijece"
CLAUDE_KID = assistnotes.key_id(CLAUDE_KEY)
OPENAI_KID = cnotes.KID
VERDIKTI = ("slazem", "doradi", "protiv")
VERDIKT_HR = {"slazem": "slaže se", "doradi": "slaže se uz doradu", "protiv": "protiv"}
ODLUKE = ("prihvaceno_primijenjeno", "prihvaceno_za_izvedbu", "odbijeno", "vlasniku")
ODLUKA_HR = {"prihvaceno_primijenjeno": "prihvaćeno i primijenjeno", "prihvaceno_za_izvedbu": "prihvaćeno za izvedbu",
             "odbijeno": "odbijeno", "vlasniku": "odlučuje vlasnik"}
SMJER_PREFIX = "Smjer: "
START_KEY = "vijece_start_ts"
PREFIX = "vijeće: "
MAX_LINE = 900
DAY_USD = 0.60          # per member a UTC day (env VIJECE_OPENAI_DAY_USD / VIJECE_CLAUDE_DAY_USD)
GROK_WAIT_S = 6 * 3600  # env VIJECE_GROK_WAIT_S
NOTE_COLS = assistnotes.COLS + ("key_id",)

SCHEMA = """
CREATE TABLE IF NOT EXISTS vijece_ocjene (
    id INTEGER PRIMARY KEY AUTOINCREMENT, note_id INTEGER NOT NULL, reviewer TEXT NOT NULL, ts INTEGER NOT NULL,
    verdict TEXT NOT NULL CHECK(verdict IN ('slazem', 'doradi', 'protiv')), critique TEXT, refined_change TEXT,
    model TEXT, usd REAL, UNIQUE(note_id, reviewer));
CREATE TABLE IF NOT EXISTS vijece_odluke (
    note_id INTEGER PRIMARY KEY, ts INTEGER NOT NULL,
    odluka TEXT NOT NULL CHECK(odluka IN ('prihvaceno_primijenjeno', 'prihvaceno_za_izvedbu', 'odbijeno', 'vlasniku')),
    razlog TEXT, primijenjeno TEXT);
CREATE INDEX IF NOT EXISTS vijece_odluke_ts ON vijece_odluke (ts);
CREATE TABLE IF NOT EXISTS vijece_kv (k TEXT PRIMARY KEY, v TEXT);
"""


def ukljuceno(env=None):
    """Env VIJECE=0 switches the whole council off (the pass prints one line and does nothing)."""
    env = os.environ if env is None else env
    return str(env.get("VIJECE", "1")).strip().lower() not in ("0", "off", "false", "ne")


def _env_f(name, default):
    try:
        return float(os.environ.get(name) or default)
    except ValueError:
        return default


def grok_wait_s():
    return max(0, int(_env_f("VIJECE_GROK_WAIT_S", GROK_WAIT_S)))


def strop(clan):
    """The member's budget for a UTC day in USD."""
    return _env_f("VIJECE_OPENAI_DAY_USD" if clan == "openai" else "VIJECE_CLAUDE_DAY_USD", DAY_USD)


def ensure(con):
    con.executescript(SCHEMA)
    assistnotes.ensure(con)


def connect(path=None):
    con = settings.connect(path)
    ensure(con)
    return con


def ro(path=None):
    """trade.db read-only (the MCP read tools, the task queue), or None when it does not exist yet."""
    path = path or settings.DB
    if not path or not os.path.exists(path):
        return None
    try:
        return sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=10)
    except sqlite3.Error:
        return None


# ---------- small state ----------------------------------------------------------------------------------------------

def kv_get(con, k, default=None):
    try:
        r = con.execute("SELECT v FROM vijece_kv WHERE k=?", (k,)).fetchone()
    except sqlite3.Error:   # a read-only connection before the first pass made the table
        return default
    if not r:
        return default
    try:
        return json.loads(r[0])
    except (ValueError, TypeError):
        return default


def kv_put(con, k, v):
    con.execute("INSERT OR REPLACE INTO vijece_kv VALUES (?,?)", (k, json.dumps(v, ensure_ascii=False)))
    con.commit()


def jednom(con, key, period):
    """True the first time `key` is asked in `period` (a log line said once a day), False after."""
    if kv_get(con, f"log:{key}") == period:
        return False
    kv_put(con, f"log:{key}", period)
    return True


def dan(now):
    return time.strftime("%Y-%m-%d", time.gmtime(int(now)))


def start_ts(con, now=None, create=True):
    """When the council first ran here (trade settings vijece_start_ts); set on the first pass, so the notes that
    waited before it (the old backlog) are never swept. None on a read before the first pass."""
    try:
        v = settings.raw(con).get(START_KEY)
    except sqlite3.Error:
        v = None
    if v or not create:
        return int(v) if v else None
    v = int(now or time.time())
    settings.put(con, START_KEY, v, "vijeće")
    return v


# ---------- roles ----------------------------------------------------------------------------------------------------

def predlagac(kid):
    """The member who wrote a note, from its key fingerprint."""
    if kid == OPENAI_KID:
        return "openai"
    if kid == CLAUDE_KID:
        return "claude"
    return "grok"


def ocjenjivaci(clan):
    """The two members who review `clan`'s proposal."""
    return tuple(c for c in CLANOVI if c != clan)


def kid_of(clan):
    return {"openai": OPENAI_KID, "claude": CLAUDE_KID}[clan]


# ---------- notes ----------------------------------------------------------------------------------------------------

def _note(r):
    d = dict(zip(NOTE_COLS, r))
    for k in ("evidence", "proposed_change"):
        try:
            d[k] = json.loads(d[k]) if d[k] else None
        except (ValueError, TypeError):
            pass
    d["predlagac"] = predlagac(d.get("key_id"))
    return d


def note(con, nid):
    try:
        r = con.execute(f"SELECT {', '.join(NOTE_COLS)} FROM assistant_notes WHERE id=?", (int(nid),)).fetchone()
    except sqlite3.Error:
        return None
    return _note(r) if r else None


def u_vijecu(n, start):
    """A note the council handles: a suggestion that still waits, written after the start (or by the council's Claude)."""
    return bool(n and n.get("kind") == "suggestion" and n.get("status") == "novo" and start is not None
                and ((n.get("ts") or 0) >= start or n.get("key_id") == CLAUDE_KID))


def red(con, limit=200):
    """The council's queue, oldest first: suggestion notes with status novo, written after the start, without a decision."""
    start = start_ts(con, create=False)
    if start is None:
        return []
    try:
        rows = con.execute(
            f"SELECT {', '.join('n.' + c for c in NOTE_COLS)} FROM assistant_notes n WHERE n.kind='suggestion' AND "
            "n.status='novo' AND (n.ts >= ? OR n.key_id = ?) AND NOT EXISTS (SELECT 1 FROM vijece_odluke o WHERE "
            "o.note_id = n.id) ORDER BY n.id LIMIT ?", (start, CLAUDE_KID, int(limit))).fetchall()
    except sqlite3.Error:
        return []
    return [_note(r) for r in rows]


# ---------- reviews and decisions ------------------------------------------------------------------------------------

OCJENA_COLS = ("note_id", "reviewer", "ts", "verdict", "critique", "refined_change", "model", "usd")


def _ocjena(r):
    d = dict(zip(OCJENA_COLS, r))
    try:
        d["refined_change"] = json.loads(d["refined_change"]) if d["refined_change"] else None
    except (ValueError, TypeError):
        d["refined_change"] = None
    if not isinstance(d["refined_change"], dict):
        d["refined_change"] = None
    return d


def ocjene(con, nid):
    """{reviewer: review} of one note."""
    return ocjene_za(con, [nid]).get(int(nid), {})


def ocjene_za(con, ids):
    """{note id: {reviewer: review}}."""
    ids = [int(i) for i in ids if i]
    out = {}
    if not ids:
        return out
    try:
        rows = con.execute(f"SELECT {', '.join(OCJENA_COLS)} FROM vijece_ocjene WHERE note_id IN "
                           f"({','.join('?' * len(ids))}) ORDER BY id", ids).fetchall()
    except sqlite3.Error:
        return out
    for r in rows:
        d = _ocjena(r)
        out.setdefault(d["note_id"], {})[d["reviewer"]] = d
    return out


def upisi_ocjenu(con, nid, reviewer, verdict, critique, refined_change=None, model=None, usd=0.0, now=None):
    """Store one review. ValueError when the member already reviewed the note or the values are not valid."""
    if reviewer not in CLANOVI:
        raise ValueError("nepoznat član vijeća")
    if verdict not in VERDIKTI:
        raise ValueError(f"verdict must be one of {', '.join(VERDIKTI)}")
    if refined_change is not None and not isinstance(refined_change, dict):
        raise ValueError("refined_change must be one JSON object")
    try:
        con.execute("INSERT INTO vijece_ocjene (note_id, reviewer, ts, verdict, critique, refined_change, model, usd) "
                    "VALUES (?,?,?,?,?,?,?,?)",
                    (int(nid), reviewer, int(now or time.time()), verdict, (critique or "")[:assistnotes.TEXT_MAX],
                     json.dumps(refined_change, ensure_ascii=False) if refined_change else None, model,
                     round(float(usd or 0), 6)))
        con.commit()
    except sqlite3.IntegrityError:
        con.rollback()
        raise ValueError(f"{IME[reviewer]} je ovaj prijedlog već ocijenio") from None


ODLUKA_COLS = ("note_id", "ts", "odluka", "razlog", "primijenjeno")


def odluka(con, nid):
    try:
        r = con.execute(f"SELECT {', '.join(ODLUKA_COLS)} FROM vijece_odluke WHERE note_id=?", (int(nid),)).fetchone()
    except sqlite3.Error:
        return None
    return dict(zip(ODLUKA_COLS, r)) if r else None


def odluke_za(con, ids):
    ids = [int(i) for i in ids if i]
    if not ids:
        return {}
    try:
        rows = con.execute(f"SELECT {', '.join(ODLUKA_COLS)} FROM vijece_odluke WHERE note_id IN "
                           f"({','.join('?' * len(ids))})", ids).fetchall()
    except sqlite3.Error:
        return {}
    return {r[0]: dict(zip(ODLUKA_COLS, r)) for r in rows}


def zadnje_odluke(con, limit=20):
    """The newest decisions with the note's title, proposer and both critiques (get_council, run_vijece.py stanje)."""
    try:
        rows = con.execute(
            "SELECT o.note_id, o.ts, o.odluka, o.razlog, o.primijenjeno, n.title, n.key_id, n.status, n.proposed_change "
            "FROM vijece_odluke o JOIN assistant_notes n ON n.id = o.note_id ORDER BY o.ts DESC, o.note_id DESC LIMIT ?",
            (int(limit),)).fetchall()
    except sqlite3.Error:
        return []
    oc = ocjene_za(con, [r[0] for r in rows])
    out = []
    for nid, ts, odl, razlog, prim, title, kid, status, pc in rows:
        try:
            pc = json.loads(pc) if pc else None
        except (ValueError, TypeError):
            pc = None
        out.append({"note_id": nid, "ts": ts, "decision": odl, "decision_hr": ODLUKA_HR.get(odl, odl), "reason": razlog,
                    "applied": prim, "title": title, "proposer": predlagac(kid), "note_status": status,
                    "change_in_force": pc,
                    "reviews": {m: {"verdict": o["verdict"], "critique": o["critique"],
                                    "refined_change": o["refined_change"]} for m, o in (oc.get(nid) or {}).items()}})
    return out


def za_izvedbu(con, limit=50):
    """The proposals the council accepted that need code (class kod), not implemented yet (the note is still
    prihvaćeno): id, title, the change in force, both critiques. The Claude Code session works this list."""
    try:
        rows = con.execute(
            "SELECT o.note_id, o.ts, o.razlog, n.title, n.key_id, n.interpretation, n.improvement, n.proposed_change "
            "FROM vijece_odluke o JOIN assistant_notes n ON n.id = o.note_id WHERE o.odluka='prihvaceno_za_izvedbu' "
            "AND n.status='prihvaćeno' ORDER BY o.ts, o.note_id LIMIT ?", (int(limit),)).fetchall()
    except sqlite3.Error:
        return []
    oc = ocjene_za(con, [r[0] for r in rows])
    out = []
    for nid, ts, razlog, title, kid, interp, impr, pc in rows:
        try:
            pc = json.loads(pc) if pc else None
        except (ValueError, TypeError):
            pc = None
        out.append({"id": nid, "ts": ts, "title": title, "proposer": predlagac(kid), "change": pc,
                    "interpretation": interp, "improvement": impr, "reason": razlog,
                    "critiques": {m: {"verdict": o["verdict"], "critique": o["critique"]}
                                  for m, o in (oc.get(nid) or {}).items()}})
    return out


def broj_za_izvedbu(con):
    try:
        return int(con.execute("SELECT COUNT(*) FROM vijece_odluke o JOIN assistant_notes n ON n.id = o.note_id WHERE "
                               "o.odluka='prihvaceno_za_izvedbu' AND n.status='prihvaćeno'").fetchone()[0])
    except sqlite3.Error:
        return 0


# ---------- the day's spend ------------------------------------------------------------------------------------------

def trosak(con, now=None):
    """{"openai": USD, "claude": USD, "poziva": n} of the UTC day of `now`."""
    d = kv_get(con, f"trosak:{dan(now or time.time())}") or {}
    return {"openai": float(d.get("openai") or 0), "claude": float(d.get("claude") or 0), "poziva": int(d.get("poziva") or 0)}


def dodaj_trosak(con, clan, usd, now=None):
    d = trosak(con, now)
    d[clan] = round(d[clan] + max(0.0, float(usd or 0)), 6)
    d["poziva"] += 1
    kv_put(con, f"trosak:{dan(now or time.time())}", d)
    return d


def stane(con, clan, est_usd, now=None):
    """Whether a call that costs at most est_usd still fits the member's day budget."""
    return trosak(con, now)[clan] + max(0.0, float(est_usd or 0)) <= strop(clan)


def dnevno(con, now=None):
    """The day's numbers for usage/daily.py: spend per member, reviews and decisions written today, what waits for
    the coding session."""
    now = int(now or time.time())
    day0 = now // 86400 * 86400
    t = trosak(con, now)

    def one(sql, args=()):
        try:
            return int(con.execute(sql, args).fetchone()[0] or 0)
        except sqlite3.Error:
            return 0
    return {"openai_usd": round(t["openai"], 4), "claude_usd": round(t["claude"], 4), "poziva": t["poziva"],
            "ocjena": one("SELECT COUNT(*) FROM vijece_ocjene WHERE ts >= ?", (day0,)),
            "odluka": one("SELECT COUNT(*) FROM vijece_odluke WHERE ts >= ?", (day0,)),
            "za_izvedbu": broj_za_izvedbu(con)}


# ---------- log lines ------------------------------------------------------------------------------------------------

def linije(glava, tekst, kratko=None):
    """One event as log lines of at most MAX_LINE characters, each starting with "vijeće: " (the operator reads the
    results from the Render log, so the text is kept whole and split, never cut): the first is "vijeće: <glava><text>",
    a following one "vijeće: <kratko> (nastavak): <text>"."""
    head = PREFIX + glava
    cont = f"{PREFIX}{kratko or glava.strip().rstrip(':')} (nastavak): "
    rest = " ".join(str(tekst or "").split())
    out = []
    while True:
        room = max(80, MAX_LINE - len(head))
        if len(rest) <= room:
            out.append((head + rest).rstrip())
            return out
        cut = rest.rfind(" ", 0, room + 1)
        if cut < room // 2:
            cut = room
        out.append(head + rest[:cut].rstrip())
        rest = rest[cut:].lstrip()
        head = cont


def reci(log, glava, tekst, kratko=None):
    for ln in linije(glava, tekst, kratko):
        log(ln, flush=True)


def kratko(s, n):
    s = " ".join(str(s or "").split())
    return s if len(s) <= n else s[:n - 1].rstrip() + "…"


def reci_ocjenu(log, n, clan, o):
    """The log line(s) of one review: "vijeće: ocjena #id „title” (predlaže X): Y: verdict: critique · dorada · $"."""
    head = (f"ocjena #{n['id']} „{kratko(n.get('title'), 120)}” (predlaže {IME[n['predlagac']]}): {IME[clan]}: "
            f"{o['verdict']}: ")
    body = " ".join(str(o.get("critique") or "").split())
    if o.get("refined_change"):
        body += " · dorada: " + kratko(json.dumps(o["refined_change"], ensure_ascii=False), 400)
    if o.get("usd"):
        body += f" · {float(o['usd']):.4f} $".replace(".", ",") + (f" ({o['model']})" if o.get("model") else "")
    reci(log, head, body, f"ocjena #{n['id']} {IME[clan]}")
