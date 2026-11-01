"""Per-user settings (⚙️ Postavke): own password, e-mail, social links, profile picture, language, sessions.

league.db table `profiles` (one row per user name, any kind of user: UI_USERS players, invite-link players):
  pw_salt/pw_hash   a password the player set himself. For a UI_USERS player it overrides UI_PASS_<NAME> (the
                    Render setting can't be changed from the app); a registered player's own password lives in
                    `members` and is changed there.
  sessions_after    logins made before this time are no longer valid ("odjavi me sa svih uređaja", password change)
  email, social (JSON {x, telegram, instagram, tiktok, youtube, discord, web}), bio, lang ('hr'|'en'),
  avatar (version timestamp of DATA_DIR/avatars/<file>.jpg, 0 = none), email_report (1 = morning report by e-mail)

Only the dashboard process writes league.db, so every row is also kept in memory (`_cache`): cookies are checked on
every request and must not cost a database read.
"""
import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
import threading
import time

from league import store

SCHEMA = """
CREATE TABLE IF NOT EXISTS profiles (name TEXT PRIMARY KEY COLLATE NOCASE, pw_salt TEXT, pw_hash TEXT,
    sessions_after INTEGER DEFAULT 0, email TEXT, social TEXT, bio TEXT, lang TEXT, avatar INTEGER DEFAULT 0,
    email_report INTEGER DEFAULT 0, updated INTEGER);
"""
ITER = 120_000
SOCIAL = [  # key, label, icon, how a handle becomes a link
    ("x", "X (Twitter)", "𝕏", "https://x.com/{}"),
    ("telegram", "Telegram", "✈️", "https://t.me/{}"),
    ("instagram", "Instagram", "📷", "https://instagram.com/{}"),
    ("tiktok", "TikTok", "🎵", "https://tiktok.com/@{}"),
    ("youtube", "YouTube", "▶️", "https://youtube.com/@{}"),
    ("discord", "Discord", "💬", None),          # a Discord name is no link, it is shown as text
    ("web", "Web stranica", "🌐", "{}"),
]
HANDLE = re.compile(r"[A-Za-z0-9_.\-]{1,40}")
EMAIL = re.compile(r"[^@\s]{1,64}@[^@\s]{1,190}\.[A-Za-z]{2,24}")
AVATAR_MAX = 300_000      # bytes of the stored JPEG (the browser shrinks the picture to 256x256 first)
_lock = threading.Lock()
_cache = None             # lower-case name -> dict(row)


def _dir():
    d = os.path.join(os.environ.get("DATA_DIR") or os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                     "avatars")
    os.makedirs(d, exist_ok=True)
    return d


def connect():
    con = store.connect()
    try:
        con.executescript(SCHEMA)
    except sqlite3.OperationalError:
        pass
    return con


def _load():
    global _cache
    with _lock:
        if _cache is not None:
            return _cache
        out = {}
        try:
            con = connect()
            try:
                for r in con.execute("SELECT * FROM profiles"):
                    out[r["name"].lower()] = dict(r)
            finally:
                con.close()
        except sqlite3.OperationalError:
            pass
        _cache = out
        return out


def reset_cache():
    global _cache
    with _lock:
        _cache = None


def get(name):
    """The user's settings row (empty dict when nothing was set yet)."""
    return dict(_load().get((name or "").strip().lower(), {}))


def _set(name, **fields):
    name = (name or "").strip()
    if not name:
        raise ValueError("nisi prijavljen.")
    fields["updated"] = int(time.time())
    con = connect()
    try:
        con.execute("INSERT OR IGNORE INTO profiles (name) VALUES (?)", (name,))
        con.execute(f"UPDATE profiles SET {', '.join(k + '=?' for k in fields)} WHERE name=?",
                    (*fields.values(), name))
        con.commit()
        row = dict(con.execute("SELECT * FROM profiles WHERE name=?", (name,)).fetchone())
    finally:
        con.close()
    _load()
    with _lock:
        _cache[name.lower()] = row
    return row


# --- password ---------------------------------------------------------------------------------------------------

def _hash(pw, salt):
    return hashlib.pbkdf2_hmac("sha256", pw.encode(), bytes.fromhex(salt), ITER).hex()


def has_password(name):
    return bool(get(name).get("pw_hash"))


def check_password(name, pw):
    """True/False when the player set his own password here, None when he did not (then the Render one counts)."""
    p = get(name)
    if not p.get("pw_hash"):
        return None
    return hmac.compare_digest(_hash(pw or "", p["pw_salt"]), p["pw_hash"])


def validate_new(new, new2):
    if len(new or "") < 6:
        raise ValueError("nova lozinka mora imati barem 6 znakova.")
    if len(new) > 200:
        raise ValueError("nova lozinka je preduga.")
    if new != new2:
        raise ValueError("nove lozinke se ne podudaraju, upiši ih ponovo.")


def set_password(name, new):
    """Own password for a UI_USERS player (overrides UI_PASS_<NAME>); logs out every other device."""
    salt = secrets.token_hex(16)
    _set(name, pw_salt=salt, pw_hash=_hash(new, salt), sessions_after=int(time.time()))


def set_member_password(name, new):
    """Registered (invite link) player: the password in `members` changes; other devices are logged out."""
    from league import members
    salt = secrets.token_hex(16)
    con = members.connect()
    try:
        con.execute("UPDATE members SET salt=?, hash=? WHERE name=?", (salt, members._hash(new, salt), name))
        con.commit()
    finally:
        con.close()
    _set(name, sessions_after=int(time.time()))


# --- sessions ---------------------------------------------------------------------------------------------------

def logout_everywhere(name):
    _set(name, sessions_after=int(time.time()))


def session_ok(name, issued):
    """A login cookie issued at `issued` (unix s) is still valid for this user."""
    return issued >= int(get(name).get("sessions_after") or 0)


# --- profile ----------------------------------------------------------------------------------------------------

def social(name):
    try:
        return json.loads(get(name).get("social") or "{}")
    except ValueError:
        return {}


def clean_handle(key, v):
    """A handle typed or pasted as a whole link -> just the handle (web: the full https address)."""
    v = (v or "").strip()
    if not v:
        return ""
    if key == "web":
        if not re.match(r"https?://", v):
            v = "https://" + v
        if len(v) > 200 or not re.fullmatch(r"https?://[^\s\"'<>]+\.[^\s\"'<>]+", v):
            raise ValueError("web stranica nije ispravna adresa.")
        return v
    v = re.sub(r"^https?://(www\.)?(x|twitter|t|instagram|tiktok|youtube)\.(com|me)/", "", v)
    v = v.lstrip("@").strip("/")
    if key == "discord":
        if not re.fullmatch(r"[A-Za-z0-9_.#]{2,40}", v):
            raise ValueError("Discord ime smije imati slova, brojke, točku i _.")
        return v
    if not HANDLE.fullmatch(v):
        raise ValueError(f"{dict((k, l) for k, l, _, _ in SOCIAL)[key]}: upiši samo ime računa (npr. @ime).")
    return v


def save_profile(name, form):
    email = (form.get("email") or "").strip()
    if email and not EMAIL.fullmatch(email):
        raise ValueError("e-mail adresa nije ispravna.")
    soc = {k: clean_handle(k, form.get("s_" + k)) for k, _, _, _ in SOCIAL}
    bio = re.sub(r"\s+", " ", (form.get("bio") or "")).strip()[:160]
    _set(name, email=email, social=json.dumps({k: v for k, v in soc.items() if v}), bio=bio,
         email_report=1 if form.get("email_report") and email else 0)


def links(name):
    """[(label, icon, url or None, handle)] of the user's social profiles, in SOCIAL order."""
    s = social(name)
    out = []
    for k, label, icon, fmt in SOCIAL:
        v = s.get(k)
        if v:
            out.append((label, icon, (fmt.format(v) if fmt else None), v))
    return out


def report_emails():
    """E-mail addresses of players who want the morning report."""
    return [p["email"] for p in _load().values() if p.get("email_report") and p.get("email")]


# --- language ---------------------------------------------------------------------------------------------------

def set_lang(name, lang):
    if name and lang in ("hr", "en"):
        _set(name, lang=lang)


# --- profile picture --------------------------------------------------------------------------------------------

def _file(name):
    return hashlib.sha1(("av|" + name.strip().lower()).encode()).hexdigest()[:20] + ".jpg"


def avatar_url(name):
    """/avatar/<file>.jpg?v=<version> or None."""
    v = get(name).get("avatar")
    return f"/avatar/{_file(name)}?v={v}" if v else None


def avatar_path(file):
    if not re.fullmatch(r"[0-9a-f]{20}\.jpg", file or ""):
        return None
    p = os.path.join(_dir(), file)
    return p if os.path.isfile(p) else None


def save_avatar(name, data_url):
    """data:image/jpeg;base64,... from the browser (already cut to a 256x256 square) -> DATA_DIR/avatars."""
    import base64
    m = re.fullmatch(r"data:image/(jpeg|png|webp);base64,([A-Za-z0-9+/=\s]+)", (data_url or "").strip())
    if not m:
        raise ValueError("slika nije stigla. Odaberi sliku (JPG ili PNG) i pokušaj ponovo.")
    raw = base64.b64decode(m.group(2))
    if len(raw) > AVATAR_MAX:
        raise ValueError("slika je prevelika (najviše 300 KB nakon smanjivanja).")
    if not (raw[:3] == b"\xff\xd8\xff" or raw[:8] == b"\x89PNG\r\n\x1a\n" or raw[8:12] == b"WEBP"):
        raise ValueError("to nije slika (JPG, PNG ili WEBP).")
    p = os.path.join(_dir(), _file(name))
    tmp = p + ".tmp"
    with open(tmp, "wb") as f:
        f.write(raw)
    os.replace(tmp, p)
    _set(name, avatar=int(time.time()))


def remove_avatar(name):
    try:
        os.remove(os.path.join(_dir(), _file(name)))
    except OSError:
        pass
    _set(name, avatar=0)


# --- delete account (invite-link players only) ----------------------------------------------------------------

def delete_member(name):
    """The registered player can no longer log in and leaves the board; his copy trading and DCA plans stop.
    His name stays taken, so a new player never inherits the old trades."""
    from league import members
    now = int(time.time())
    con = members.connect()
    try:
        con.execute("UPDATE members SET deleted=? WHERE name=?", (now, name))
        for table in ("follows", "dca_plans"):
            try:
                con.execute(f"UPDATE {table} SET active=0, stopped=? WHERE user=? AND active=1", (now, name))
            except sqlite3.OperationalError:
                pass
        con.commit()
    finally:
        con.close()
    remove_avatar(name)
    _set(name, sessions_after=now, email="", social="{}", bio="", email_report=0)
