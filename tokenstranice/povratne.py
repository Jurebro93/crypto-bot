"""Komentari i glasovi 👍/👎 na stranici tokena (league.db; piše samo aplikacija, kao chat javne Autopilot stranice).

Pravila (ui/apjavno): pišu i glasaju samo prijavljeni igrači; gost samo čita. Poruka najviše MAX_LEN (500) znakova,
RATE_N (5) poruka u RATE_S (10 min) po igraču (preko svih tokena), ista poruka dvaput zaredom se odbija; glasovi
VOTE_N (30) u minuti po igraču. Glas je jedan po igraču i tokenu: isti glas ponovno ga makne, drugi ga zamijeni.
Tekst se spremi očišćen (apjavno.clean_text), a prikazuje se uvijek escapean, nikad kao poveznica; e-mail adrese,
nizovi dugi kao ključ i Solana adrese (osim adrese samog tokena) skrivaju se pri prikazu (javne stranice nikad ne
pokazuju adrese novčanika). Poruku skriva vlasnik ili admin (apjavno.can_moderate); skrivena se gostu ne pokazuje.
"""
import re
import sqlite3
import time
from urllib.parse import quote

MAX_LEN = 500
RATE_N, RATE_S = 5, 600
VOTE_N, VOTE_S = 30, 60
PAGE_N = 30
ADDR = re.compile(r"[1-9A-HJ-NP-Za-km-z]{32,44}")
MINT = re.compile(r"[1-9A-HJ-NP-Za-km-z]{32,44}")
SCHEMA = """
CREATE TABLE IF NOT EXISTS tp_fb (id INTEGER PRIMARY KEY AUTOINCREMENT, mint TEXT, ts INTEGER, user TEXT COLLATE NOCASE,
    text TEXT, hidden INTEGER DEFAULT 0);
CREATE INDEX IF NOT EXISTS tp_fb_mint ON tp_fb (mint, hidden, id);
CREATE INDEX IF NOT EXISTS tp_fb_user ON tp_fb (user, ts);
CREATE TABLE IF NOT EXISTS tp_votes (mint TEXT, user TEXT COLLATE NOCASE, v INTEGER, ts INTEGER, PRIMARY KEY (mint, user));
"""
_ENSURED = set()
_TAPS = {}


class FbError(ValueError):
    def __init__(self, code):
        super().__init__(code)
        self.code = code


ERR = {
    "login": "Pisati i glasati mogu igrači prijavljeni svojim imenom.",
    "empty": "Poruka je prazna.",
    "long": f"Poruka je preduga: najviše {MAX_LEN} znakova.",
    "rate": f"Previše poruka u kratko vrijeme: najviše {RATE_N} u {RATE_S // 60} minuta. Pokušaj malo kasnije.",
    "dup": "Tu si poruku već poslao.",
    "gone": "Te poruke više nema.",
    "no": "Poruke može sakriti samo vlasnik.",
    "votes": "Previše klikova u minuti. Pričekaj trenutak.",
    "token": "Ovaj token nema stranicu.",
    "db": "Spremanje trenutno ne radi. Pokušaj ponovno za minutu.",
    "what": "Nepoznata radnja.",
}


def reset():
    _TAPS.clear()


def ensure(con):
    key = con.execute("PRAGMA database_list").fetchone()[2]
    if key in _ENSURED:
        return
    con.executescript(SCHEMA)
    _ENSURED.add(key)


def connect():
    from league import store
    con = sqlite3.connect(store.DB, timeout=30)
    ensure(con)
    return con


def ro():
    """league.db read-only for the pages; None before the tables exist (nothing written yet)."""
    from league import store
    import os
    p = os.path.abspath(store.DB)
    if not os.path.exists(p) or not os.path.getsize(p):
        return None
    try:
        con = sqlite3.connect("file:" + quote(p) + "?mode=ro", uri=True, timeout=5)
        con.execute("SELECT 1 FROM tp_fb LIMIT 1")
        return con
    except sqlite3.Error:
        return None


def clean_text(text):
    from ui import apjavno
    return apjavno.clean_text(text)


def show_text(text, mint=None):
    """Escaped, never a link; e-mails, key-long strings and every Solana address but the token's own hidden."""
    from ui import apjavno
    t = ADDR.sub(lambda m: m.group(0) if m.group(0) == mint else "[adresa skrivena]", text or "")
    return apjavno.show_text(t)


def can_moderate(user):
    from ui import apjavno
    return apjavno.can_moderate(user)


def add(con, mint, user, text, now=None):
    if not user:
        raise FbError("login")
    now = int(now or time.time())
    t = clean_text(text)
    if not t:
        raise FbError("empty")
    if len(t) > MAX_LEN:
        raise FbError("long")
    recent = con.execute("SELECT text, mint FROM tp_fb WHERE user=? AND ts>=? ORDER BY ts DESC, id DESC LIMIT ?",
                         (user, now - RATE_S, RATE_N)).fetchall()
    if len(recent) >= RATE_N:
        raise FbError("rate")
    if recent and recent[0][0] == t and recent[0][1] == mint:
        raise FbError("dup")
    cur = con.execute("INSERT INTO tp_fb (mint, ts, user, text) VALUES (?,?,?,?)", (mint, now, user, t))
    con.commit()
    return cur.lastrowid


def vote(con, mint, user, v, now=None):
    """+1 / -1; the same vote again takes it back. Returns the player's vote now (1, -1 or 0)."""
    if not user:
        raise FbError("login")
    if v not in (1, -1):
        raise FbError("what")
    now = now or time.time()
    taps = [x for x in _TAPS.get(user.lower(), []) if x > now - VOTE_S]
    if len(taps) >= VOTE_N:
        raise FbError("votes")
    _TAPS[user.lower()] = taps + [now]
    old = con.execute("SELECT v FROM tp_votes WHERE mint=? AND user=?", (mint, user)).fetchone()
    if old and old[0] == v:
        con.execute("DELETE FROM tp_votes WHERE mint=? AND user=?", (mint, user))
        con.commit()
        return 0
    con.execute("INSERT OR REPLACE INTO tp_votes (mint, user, v, ts) VALUES (?,?,?,?)", (mint, user, v, int(now)))
    con.commit()
    return v


def hide(con, user, msg_id, hidden=True):
    if not can_moderate(user):
        raise FbError("no")
    n = con.execute("UPDATE tp_fb SET hidden=? WHERE id=?", (1 if hidden else 0, int(msg_id))).rowcount
    con.commit()
    if not n:
        raise FbError("gone")
    r = con.execute("SELECT mint FROM tp_fb WHERE id=?", (int(msg_id),)).fetchone()
    return r[0] if r else None


def read(con, mint, user=None, with_hidden=False, limit=PAGE_N):
    """{"up", "down", "mine" (the player's vote), "msgs": [{id, ts, user, text, hidden}] newest first}."""
    out = {"up": 0, "down": 0, "mine": 0, "msgs": []}
    if con is None:
        return out
    try:
        for v, n in con.execute("SELECT v, COUNT(*) FROM tp_votes WHERE mint=? GROUP BY v", (mint,)):
            out["up" if v == 1 else "down"] = n
        if user:
            r = con.execute("SELECT v FROM tp_votes WHERE mint=? AND user=?", (mint, user)).fetchone()
            out["mine"] = r[0] if r else 0
        sql = "SELECT id, ts, user, text, hidden FROM tp_fb WHERE mint=?" + ("" if with_hidden else " AND hidden=0")
        out["msgs"] = [{"id": r[0], "ts": r[1], "user": r[2], "text": r[3], "hidden": bool(r[4])}
                       for r in con.execute(sql + " ORDER BY id DESC LIMIT ?", (mint, int(limit)))]
    except sqlite3.Error:
        pass
    return out


def act(path, form, user, known=None):
    """One feedback form (/tokenstranica/poruka | glas | sakrij). (ok, code, mint). known(mint) -> bool: the mint
    has a page (no comments on tokens without one)."""
    if not user:
        return False, "login", None
    mint = str(form.get("m") or "").strip()
    try:
        con = connect()
    except sqlite3.Error:
        return False, "db", mint
    try:
        if path.endswith("/sakrij"):
            ident = str(form.get("id") or "").strip()
            if not re.fullmatch(r"[0-9]{1,18}", ident):
                raise FbError("gone")
            mint = hide(con, user, int(ident), form.get("on") != "0") or mint
            return True, "", mint
        if not MINT.fullmatch(mint) or (known is not None and not known(mint)):
            raise FbError("token")
        if path.endswith("/poruka"):
            add(con, mint, user, form.get("text"))
        elif path.endswith("/glas"):
            vote(con, mint, user, 1 if form.get("v") == "1" else -1 if form.get("v") == "-1" else 0)
        else:
            raise FbError("what")
        return True, "", mint
    except FbError as e:
        return False, e.code if e.code in ERR else "what", mint
    except sqlite3.Error:
        return False, "db", mint
    finally:
        con.close()
