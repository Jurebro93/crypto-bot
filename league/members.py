"""Players who registered themselves through an invite link (no Render settings needed).

league.db tables:
  members  name, salted PBKDF2 password hash, when, through which invite
  invites  invite links: one reusable link ('stalni', a new one replaces the old) and single-use links ('jednokratni')

Players from UI_USERS / UI_PASS_<NAME> keep working exactly as before; a registered name can never take one of
theirs (or the view-only test account's). Only the dashboard process writes here (league.db's single writer).
"""
import hashlib
import hmac
import os
import re
import secrets
import sqlite3
import time

from league import store

MIN_PW = 12   # audit 4.11. §4.3: was 6

SCHEMA = """
CREATE TABLE IF NOT EXISTS members (name TEXT PRIMARY KEY COLLATE NOCASE, salt TEXT, hash TEXT, created INTEGER,
                                    invite TEXT);
CREATE TABLE IF NOT EXISTS invites (token TEXT PRIMARY KEY, kind TEXT, created INTEGER, created_by TEXT,
                                    used_by TEXT, used_ts INTEGER, revoked INTEGER DEFAULT 0);
"""
ITER = 120_000
NAME = re.compile(r"[A-Za-zČčĆćĐđŠšŽž0-9_\-]{2,20}")
RESERVED = {"bot", "admin", "svi", "gost"}


def connect():
    con = store.connect()
    try:
        con.executescript(SCHEMA)
    except sqlite3.OperationalError:
        pass
    _migrate(con)
    return con


def _migrate(con):
    """`deleted`: the player removed his account in ⚙️ Postavke (the name stays taken)."""
    try:
        cols = {r[1] for r in con.execute("PRAGMA table_info(members)")}
        if cols and "deleted" not in cols:
            con.execute("ALTER TABLE members ADD COLUMN deleted INTEGER")
            con.commit()
    except sqlite3.OperationalError:
        pass


def _hash(pw, salt):
    return hashlib.pbkdf2_hmac("sha256", pw.encode(), bytes.fromhex(salt), ITER).hex()


def names(con=None):
    """Registered players in the order they joined (empty if the table is not there yet)."""
    own = con is None
    try:
        con = con or store.connect()
        _migrate(con)
        return [r[0] for r in con.execute("SELECT name FROM members WHERE deleted IS NULL ORDER BY created, rowid")]
    except sqlite3.OperationalError:
        return []
    finally:
        if own and con is not None:
            con.close()


def verify(name, pw):
    """The registered player's name as stored, if name + password match; else None."""
    try:
        con = store.connect()
    except sqlite3.OperationalError:
        return None
    try:
        _migrate(con)
        r = con.execute("SELECT name, salt, hash FROM members WHERE name=? AND deleted IS NULL",
                        ((name or "").strip(),)).fetchone()
    except sqlite3.OperationalError:
        r = None
    finally:
        con.close()
    if r and hmac.compare_digest(_hash(pw or "", r["salt"]), r["hash"]):
        return r["name"]
    return None


def exists(name, with_deleted=False):
    try:
        con = store.connect()
        try:
            _migrate(con)
            r = con.execute("SELECT name FROM members WHERE name=?" + ("" if with_deleted else " AND deleted IS NULL"),
                            ((name or "").strip(),)).fetchone()
        finally:
            con.close()
    except sqlite3.OperationalError:
        return None
    return r[0] if r else None


# --- invite links -------------------------------------------------------------------------------------------------

def standing(con, by=None):
    """The reusable invite token; made on first use."""
    r = con.execute("SELECT token FROM invites WHERE kind='stalni' AND revoked=0 ORDER BY created DESC").fetchone()
    if r:
        return r[0]
    return renew(con, by)


def renew(con, by=None):
    """A new reusable link; the old one stops working (accounts made with it stay)."""
    con.execute("UPDATE invites SET revoked=1 WHERE kind='stalni'")
    tok = secrets.token_urlsafe(12)
    con.execute("INSERT INTO invites (token, kind, created, created_by) VALUES (?,?,?,?)",
                (tok, "stalni", int(time.time()), by))
    con.commit()
    return tok


def single(con, by=None):
    tok = secrets.token_urlsafe(12)
    con.execute("INSERT INTO invites (token, kind, created, created_by) VALUES (?,?,?,?)",
                (tok, "jednokratni", int(time.time()), by))
    con.commit()
    return tok


def open_singles(con):
    return [dict(r) for r in con.execute(
        "SELECT token, created, created_by FROM invites WHERE kind='jednokratni' AND revoked=0 AND used_by IS NULL "
        "ORDER BY created DESC LIMIT 20")]


def revoke(con, token):
    con.execute("UPDATE invites SET revoked=1 WHERE token=?", (token,))
    con.commit()


def all_invites(con, limit=200):
    """Every invite link, newest first, with how many accounts were made with it (for /zahtjevi)."""
    used = {r[0]: r[1] for r in con.execute(
        "SELECT invite, GROUP_CONCAT(name, ', ') FROM members WHERE invite IS NOT NULL GROUP BY invite")}
    out = []
    for r in con.execute("SELECT * FROM invites ORDER BY revoked, created DESC LIMIT ?", (limit,)):
        d = dict(r)
        d["joined"] = used.get(d["token"]) or ""
        d["active"] = not d["revoked"] and not (d["kind"] == "jednokratni" and d["used_by"])
        out.append(d)
    return out


def delete(con, token):
    """Removes the link: it stops working and leaves the list. Accounts already made with it stay."""
    con.execute("DELETE FROM invites WHERE token=?", (token,))
    con.commit()


def valid(con, token):
    """The invite row if the link still works."""
    if not token:
        return None
    r = con.execute("SELECT * FROM invites WHERE token=? AND revoked=0", (token,)).fetchone()
    if not r or (r["kind"] == "jednokratni" and r["used_by"]):
        return None
    return dict(r)


def joined(con, limit=50):
    return [dict(r) for r in con.execute(
        "SELECT m.name, m.created, i.created_by FROM members m LEFT JOIN invites i ON i.token=m.invite "
        "ORDER BY m.created DESC LIMIT ?", (limit,))]


def register(con, token, name, pw, pw2, taken=()):
    """Creates the player; returns the name. Raises ValueError with a plain-Croatian reason."""
    inv = valid(con, token)
    if not inv:
        raise ValueError("ovaj link za registraciju više ne vrijedi. Zatraži novi od onoga tko te pozvao.")
    name = (name or "").strip()
    if not NAME.fullmatch(name):
        raise ValueError("ime mora imati 2 do 20 slova ili brojki, bez razmaka (dopušteni su - i _).")
    low = name.lower()
    if low in RESERVED or low in {t.lower() for t in taken} or exists(name, with_deleted=True):
        raise ValueError(f"ime {name} je već zauzeto, odaberi drugo.")
    if len(pw or "") < MIN_PW:
        raise ValueError("lozinka mora imati barem 12 znakova.")
    if pw != pw2:
        raise ValueError("lozinke se ne podudaraju, upiši ih ponovo.")
    salt = secrets.token_hex(16)
    con.execute("INSERT INTO members (name, salt, hash, created, invite) VALUES (?,?,?,?,?)", (name, salt, _hash(pw, salt), int(time.time()), token))
    if inv["kind"] == "jednokratni":
        con.execute("UPDATE invites SET used_by=?, used_ts=? WHERE token=?", (name, int(time.time()), token))
    con.commit()
    store.account(con, name)      # $1,000 demo account right away, so the player is on the board at once
    con.commit()
    return name
