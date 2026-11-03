"""User roles: who may see and do what in the app. Checked on the SERVER for every page and every form (run_ui.py
calls deny_get / deny_post before anything else runs), so a hidden button is never the only lock.

Three roles:
  admin      everything: spending (/usage), Google visits, access requests, module logs, roles of other users,
             manual runs that cost credits ("Osvježi walletove"), invite links, the bot's demo sells.
  prijatelj  trusted friend: every page except the admin ones above; may use Naš token and Za WhatsApp.
  osnovni    look only at the core of the app (tokens, influencers, wallets, events, demo bot) and play with their own
             demo account in Natjecanje. No spending, settings of the bot, AI costs, reports, admin pages, nothing
             that costs money or load.

Defaults (nothing stored): UI_ADMINS names (or TRADE_OWNER / "Jure" when UI_ADMINS is empty) are admins and cannot be
changed from the app, so nobody can lock the owner out; everyone else (UI_USERS players, invite-link friends, the
view-only account, the shared password) starts as `osnovni` (Nicholas, 3.11.). An admin changes anyone else's
role on /korisnici; the choice lives in league.db table `roles`.
"""
import os
import sqlite3
import threading
import time

from league import store

ROLES = ("admin", "prijatelj", "osnovni")
RANK = {"osnovni": 0, "prijatelj": 1, "admin": 2}
LABEL = {"admin": "Admin", "prijatelj": "Prijatelj", "osnovni": "Osnovni"}
WHAT = {
    "admin": "Sve: potrošnja, zahtjevi za pristup, uloge korisnika, ručna osvježavanja koja troše kredite, pozivnice.",
    "prijatelj": "Sve stranice osim administratorskih (potrošnja, zahtjevi, uloge, zapisi modula). Ne pokreće ništa "
                 "što troši kredite.",
    "osnovni": "Gleda tokene, influencere, novčanike i demo bota, igra svojim demo računom u Natjecanju. Ne vidi "
               "potrošnju, pravila bota ni izvještaje i ne pokreće ništa što troši novac ili opterećuje server.",
}

# pages (exact path or path + "/...") and the lowest role that may open them
PAGES = {
    "/usage": "admin", "/analitika": "admin", "/zahtjevi": "admin", "/outputs": "admin", "/korisnici": "admin",
    "/learn": "prijatelj", "/criteria": "prijatelj", "/izvjestaj": "prijatelj", "/nas-token": "prijatelj",
    "/whatsapp": "prijatelj",
}
# forms (path prefix) and the lowest role that may send them; anything not listed needs only a login
POSTS = (
    ("/run/", "admin"),                    # manual runs, e.g. "Osvježi walletove" = ~12,000 Helius credits
    ("/korisnici/", "admin"),
    ("/zahtjevi/", "admin"),
    ("/natjecanje/pozivnica/", "admin"),   # invite links: who gets into the app is the admin's call
    ("/prijedlozi/status", "admin"),
    ("/paper/izlaz", "admin"),             # sells the bot's own demo position
    ("/nas-token/", "prijatelj"),          # includes /nas-token/rpc, which goes through our paid Helius key
    ("/whatsapp/", "prijatelj"),
)

SCHEMA = "CREATE TABLE IF NOT EXISTS roles (name TEXT PRIMARY KEY COLLATE NOCASE, role TEXT, by TEXT, ts INTEGER);"
_lock = threading.Lock()
_cache = None   # lower-case name -> role; only the dashboard process writes league.db, so memory stays true


def locked_admins():
    """Admins set on the server; the app cannot change them."""
    names = {a.strip().lower() for a in os.environ.get("UI_ADMINS", "").split(",") if a.strip()}
    return names or {(os.environ.get("TRADE_OWNER") or "Jure").strip().lower()}


def connect():
    con = store.connect()
    try:
        con.executescript(SCHEMA)
    except sqlite3.OperationalError:
        pass
    return con


def _stored():
    global _cache
    with _lock:
        if _cache is None:
            try:
                con = connect()
                try:
                    _cache = {r["name"].lower(): r["role"] for r in con.execute("SELECT name, role FROM roles")}
                finally:
                    con.close()
            except sqlite3.Error:
                return {}
        return _cache


def default(name):
    if not name:
        return "osnovni"
    if name.lower() in locked_admins():
        return "admin"
    return "osnovni"   # Nicholas 3.11.: everyone but the admin starts basic, he raises roles on /korisnici


def role(name):
    """Role of a login name (player, registered friend or the view-only account); None = shared password."""
    if not name:
        return "osnovni"
    if name.lower() in locked_admins():
        return "admin"
    r = _stored().get(name.lower())
    return r if r in ROLES else default(name)


def at_least(name_or_role, need):
    r = name_or_role if name_or_role in ROLES else role(name_or_role)
    return RANK[r] >= RANK[need]


def set_role(name, new, by):
    """Admin changes `name` to `new`. Raises ValueError with a plain-Croatian reason."""
    global _cache
    if new not in ROLES:
        raise ValueError("nepoznata uloga")
    if not name:
        raise ValueError("koga mijenjaš?")
    if not at_least(by, "admin"):
        raise ValueError("uloge mijenja samo admin")
    if name.lower() in locked_admins():
        raise ValueError(f"{name} je admin postavljen na serveru (UI_ADMINS) i ne mijenja se ovdje")
    con = connect()
    try:
        con.execute("INSERT INTO roles VALUES (?,?,?,?) ON CONFLICT(name) DO UPDATE SET role=excluded.role, "
                    "by=excluded.by, ts=excluded.ts", (name, new, by, int(time.time())))
        con.commit()
    finally:
        con.close()
    with _lock:
        _cache = None
    print(f"uloge: {by} je {name} postavio na {new}", flush=True)


def _need_page(path):
    for p, need in PAGES.items():
        if path == p or path.startswith(p + "/"):
            return need
    return None


def deny_get(path, r):
    """None if role `r` may open `path`, else the role it would need."""
    need = _need_page(path)
    return need if need and RANK[r] < RANK[need] else None


def deny_post(path, r):
    for pre, need in POSTS:
        if path == pre.rstrip("/") or path.startswith(pre):
            return need if RANK[r] < RANK[need] else None
    return None


def reset_cache():
    global _cache
    with _lock:
        _cache = None
