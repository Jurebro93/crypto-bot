"""Public page /autopilot (Jure 10.11.: "svi igrači mogu pratiti statistiku autopilota ... ispod chat gdje svatko može
dati primjedbu, čuva se, svi vide i reagiraju s plus jedan ... javno stoji adresa novčanika"), the "Autopilot je live"
banner of the app and the highlighted block for the public front page.

    page(qs, user, lang, logged_in)  (title, body): the same body for a guest and a player; a player also gets the chat form
    guest_html(qs, lang)       the whole document for a visitor without a login (light frame, no app menu)
    chat_fragment(user, qs)    the message list alone (GET /autopilot/chat), re-fetched every POLL_S seconds
    post(path, form, user)     chat forms /autopilot/poruka, /autopilot/plus, /autopilot/sakrij -> where to go next
    banner_html(user, path)    the big line on top of every app page (ui/html.page); "" while Autopilot is not live
    landing_strip(lang)        the highlighted block for the public front page; "" while Autopilot is not live
    live_state()               {"live", "on", "since"}, kept LIVE_TTL_S

Rules of this page: it is PUBLIC, every visitor and every search bot can open it.
  * "Uživo, pravi novac" is said only when trade.executor.is_live says so; anything else is called trial mode.
  * Shown: the wallet's public address (Jure asked for it), its value, the chart, statistics of closed trades, who is
    followed and who chose them, entries and exits, the chat. Never shown: keys, env names, internal services, costs,
    trading buttons, e-mail addresses, raw error text. A reason is only the short group from trade.aplog.why_short,
    and even that is replaced by a neutral word when it looks like an error or a link (errors can carry URLs with keys).
  * Cheap: what comes from the databases is one snapshot kept SNAP_TTL_S; the guest page and the guest message list
    are kept GUEST_TTL_S as finished HTML. Nothing here ever calls the network (the wallet value is what
    trade/equity.py stored at its last 5-minute snapshot) and trade.db is opened read-only.
  * Modules of the other groups (trade.equity, trade.aplog, ui.apchart) are called in try/except with a plain
    fallback: one log line, the section shows less, the page stays up.
  * Chat (league.db: ap_chat, ap_chat_votes): only logged-in players write and give +1, 500 characters, RATE_N
    messages in RATE_S seconds per player, text always escaped and never turned into links, the owner hides a message.
"""
import hashlib
import os
import re
import sqlite3
import threading
import time
from urllib.parse import quote

from ui.html import ago as _html_ago, esc, short

PATH = "/autopilot"
PATH_EN = "/en/autopilot"
CHAT_PATH = "/autopilot/chat"
TITLE = "Autopilot uživo"
MAX_LEN = 500
RATE_N, RATE_S = 5, 600      # messages per player: 5 in 10 minutes
VOTE_N, VOTE_S = 30, 60      # +1 taps per player in a minute (each one is a small write)
PAGE_N = 50                  # messages per page of the chat
MOVES_N = 12                 # entries and exits listed
LOG_N = 200                  # newest rows asked from trade.aplog for the entries and exits (skips come with them)
DAY_N = 1000                 # decisions of the last 24 h read for the day's line (trade.aplog.DAY_LIMIT)
FOLLOWS_N = 30
LIVE_TTL_S = 30
SNAP_TTL_S = 30
GUEST_TTL_S = 10
POLL_S = 15                  # the message list refreshes this often, never every second
# 10.11. (Jure: "nakon svakog tradea bi se trebala osvježiti stranica, da korisnici u bilo kojem momentu vide što bot
# radi"): the wallet value, the chart, the statistics, who is followed and the entries and exits are re-fetched every
# LIVE_POLL_S while the tab is visible (LIVE_PATH, the same HTML for everybody, kept GUEST_TTL_S); a part whose HTML
# did not change is left alone, so a chosen range or filter stays.
LIVE_PATH = "/autopilot/zivo"
LIVE_POLL_S = 15
LIVE_PARTS = ("hero", "chart", "stats", "follows", "moves")

ADDR = re.compile(r"[1-9A-HJ-NP-Za-km-z]{32,44}")       # a Solana address (a secret key is 87+ characters: never matches)
SIG = re.compile(r"[1-9A-HJ-NP-Za-km-z]{64,90}")        # a transaction signature
HANDLE = re.compile(r"[A-Za-z0-9_]{1,30}")
_EMAIL = re.compile(r"[\w.+\-]+@[\w\-]+(?:\.[\w\-]+)+")
_LONG = re.compile(r"[1-9A-HJ-NP-Za-km-z]{80,}")        # as long as a secret key: hidden when someone pastes one by mistake
_PCT = re.compile(r"[+\-−]?\d{1,4}(?:[.,]\d{1,2})?\s?%")
# 10.11.: what a reason must not contain to be printed; raw errors carry links, query strings, braces, quotes, stack
# traces and exception names ("KeyError: 'x'", "JSONDecodeError"), none of which a short reason of trade.aplog has
_NOT_A_REASON = re.compile(r"https?:|://|www\.|[?&=<>{}\[\]\\'\"`]|\bapi\b|\bkey\b|\bhttp|traceback|error\b|exception|"
                           r"errno|timed? ?out|\bline \d|\bfile \"", re.I)
NEUTRAL_REASON = "tehnički razlog"
MODE_TAG = {"live": "pravi novac", "dry": "probno, bez pravog novca"}   # which money a section counts

_lock = threading.Lock()
_LIVE = {"ts": 0.0, "val": None}
_SNAP = {"ts": 0.0, "val": None}
_GUEST = {}          # ("page", lang) / ("chat",) -> (ts, html)
_WARNED = {}         # (section, error type) -> last log time
_RW = {"need": False, "retry": False}
_ENSURED = set()
_VOTES = {}          # player -> [times of the last +1 taps]


class ChatError(ValueError):
    """A refusal the player may read: .code picks the sentence from ERR (never the text of an exception)."""

    def __init__(self, code):
        super().__init__(code)
        self.code = code


ERR = {
    "login": "Pisati i dati +1 mogu igrači prijavljeni svojim imenom.",
    "empty": "Poruka je prazna.",
    "long": f"Poruka je preduga: najviše {MAX_LEN} znakova.",
    "rate": f"Previše poruka u kratko vrijeme: najviše {RATE_N} u {RATE_S // 60} minuta. Pokušaj malo kasnije.",
    "dup": "Tu si poruku već poslao.",
    "gone": "Te poruke više nema.",
    "no": "Poruke može sakriti samo vlasnik.",
    "votes": "Previše klikova u minuti. Pričekaj trenutak.",
    "db": "Spremanje trenutno ne radi. Pokušaj ponovno za minutu.",
    "what": "Nepoznata radnja.",
}


def ago(ts_):
    """('prije 5 min', ...) like ui.html.ago, but the first minute and a half reads "upravo" instead of "prije 0 min"."""
    if ts_ and time.time() - ts_ < 90:
        return ("upravo", ts_, "")
    return _html_ago(ts_)


def reset_cache():
    """Tests, and after a chat change: nothing kept from before."""
    _LIVE.update(ts=0.0, val=None)
    _SNAP.update(ts=0.0, val=None)
    _GUEST.clear()
    _VOTES.clear()


def _warn(what, e):
    """One log line per section and error type in 10 minutes. The page never sees the text."""
    if isinstance(e, sqlite3.OperationalError) and "readonly" in str(e).lower() and not _RW["need"]:
        _RW["need"] = _RW["retry"] = True   # another group's helper wanted to create its table first: see _tcon
        return
    key = (what, type(e).__name__)
    now = time.time()
    if now - _WARNED.get(key, 0) < 600:
        return
    _WARNED[key] = now
    text = re.sub(r"(https?://[^/\s?]+)\S*", r"\1/…", str(e))[:160]   # an RPC address carries its key in the URL
    print(f"apjavno: {what}: {type(e).__name__}: {text}", flush=True)


# ---------- databases ---------------------------------------------------------------------------------------------

def _trade_db():
    from trade import settings
    return settings.DB


def _tcon():
    """trade.db for reading. Read-only with a short wait, so a public page can neither write to the real-money
    database nor hang behind it. Only when a helper of another group (trade.equity, trade.aplog) has to create its
    own table or index first does this process switch to the normal handle the Autopilot page uses."""
    p = _trade_db()
    if _RW["need"]:
        from trade import executor
        return executor.connect(p)
    if not os.path.exists(p) or not os.path.getsize(p):
        return None
    return sqlite3.connect("file:" + quote(os.path.abspath(p)) + "?mode=ro", uri=True, timeout=3)


CHAT_SCHEMA = """
CREATE TABLE IF NOT EXISTS ap_chat (
    id INTEGER PRIMARY KEY AUTOINCREMENT, ts INTEGER, user TEXT COLLATE NOCASE, text TEXT, hidden INTEGER DEFAULT 0);
CREATE INDEX IF NOT EXISTS ap_chat_user_ts ON ap_chat (user, ts);
CREATE INDEX IF NOT EXISTS ap_chat_vis ON ap_chat (hidden, id);
CREATE TABLE IF NOT EXISTS ap_chat_votes (
    msg_id INTEGER, user TEXT COLLATE NOCASE, ts INTEGER, PRIMARY KEY (msg_id, user));
"""


def ensure(con):
    """The two chat tables, once per process and database file (league.db; the dashboard is its only writer)."""
    key = con.execute("PRAGMA database_list").fetchone()[2]
    if key in _ENSURED:
        return
    con.executescript(CHAT_SCHEMA)
    _ENSURED.add(key)


def _lcon():
    from league import store
    con = store.connect()
    ensure(con)
    return con


def _lcon_read():
    """league.db for the message list, asked every POLL_S by every open page: read-only and without league's whole
    schema script (store.connect runs it on every open), once this process has made sure the chat tables exist."""
    from league import store
    p = os.path.abspath(store.DB)
    if p not in _ENSURED or not os.path.exists(p):
        return _lcon()
    return sqlite3.connect("file:" + quote(p) + "?mode=ro", uri=True, timeout=5)


# ---------- chat: data --------------------------------------------------------------------------------------------

def clean_text(text):
    """What is stored: no control or direction-override characters, at most one empty line in a row."""
    t = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    t = "".join(ch for ch in t if ch == "\n" or (ch >= " " and ch not in "\x7f​‎‏‪‫‬‭‮"
                                                 "⁦⁧⁨⁩﻿"))
    return re.sub(r"\n{3,}", "\n\n", t).strip()


def can_moderate(user):
    """The owner of the trading account (and the app's admins) may hide a message."""
    if not user:
        return False
    try:
        from trade import settings
        if settings.is_owner(user):
            return True
        from league import roles
        return roles.role(user) == "admin"
    except Exception as e:  # noqa: BLE001 - no answer = no right
        _warn("uloga", e)
        return False


def add_message(con, user, text, now=None):
    """Store one message of a logged-in player; ChatError says why not."""
    if not user:
        raise ChatError("login")
    now = int(now or time.time())
    t = clean_text(text)
    if not t:
        raise ChatError("empty")
    if len(t) > MAX_LEN:
        raise ChatError("long")
    recent = con.execute("SELECT text FROM ap_chat WHERE user=? AND ts>=? ORDER BY ts DESC LIMIT ?",
                         (user, now - RATE_S, RATE_N)).fetchall()
    if len(recent) >= RATE_N:
        raise ChatError("rate")
    if recent and recent[0][0] == t:
        raise ChatError("dup")
    cur = con.execute("INSERT INTO ap_chat (ts, user, text) VALUES (?,?,?)", (now, user, t))
    con.commit()
    return cur.lastrowid


def toggle_vote(con, user, msg_id, now=None):
    """+1 on, or off when it was on. True = this player's +1 is now on."""
    if not user:
        raise ChatError("login")
    now = now or time.time()
    taps = [x for x in _VOTES.get(user.lower(), []) if x > now - VOTE_S]
    if len(taps) >= VOTE_N:
        raise ChatError("votes")
    _VOTES[user.lower()] = taps + [now]
    row = con.execute("SELECT hidden FROM ap_chat WHERE id=?", (msg_id,)).fetchone()
    if not row or row[0]:
        raise ChatError("gone")
    had = con.execute("DELETE FROM ap_chat_votes WHERE msg_id=? AND user=?", (msg_id, user)).rowcount
    if not had:
        con.execute("INSERT INTO ap_chat_votes (msg_id, user, ts) VALUES (?,?,?)", (msg_id, user, int(now)))
    con.commit()
    return not had


def set_hidden(con, user, msg_id, hidden=True):
    if not can_moderate(user):
        raise ChatError("no")
    n = con.execute("UPDATE ap_chat SET hidden=? WHERE id=?", (1 if hidden else 0, msg_id)).rowcount
    con.commit()
    if not n:
        raise ChatError("gone")


def messages(con, user=None, before=None, limit=PAGE_N, with_hidden=False):
    """Newest first: [{id, ts, user, text, hidden, votes, mine}]. Three queries, each by an index and limited."""
    where, args = [], []
    if not with_hidden:
        where.append("hidden=0")
    if before:
        where.append("id<?")
        args.append(int(before))
    sql = ("SELECT id, ts, user, text, hidden FROM ap_chat" + (" WHERE " + " AND ".join(where) if where else "")
           + " ORDER BY id DESC LIMIT ?")
    rows = [{"id": r[0], "ts": r[1], "user": r[2], "text": r[3], "hidden": bool(r[4]), "votes": 0, "mine": False}
            for r in con.execute(sql, (*args, int(limit)))]
    if not rows:
        return rows
    ids = [r["id"] for r in rows]
    q = ",".join("?" * len(ids))
    votes = dict(con.execute(f"SELECT msg_id, COUNT(*) FROM ap_chat_votes WHERE msg_id IN ({q}) GROUP BY msg_id", ids))
    mine = ({r[0] for r in con.execute(f"SELECT msg_id FROM ap_chat_votes WHERE user=? AND msg_id IN ({q})", (user, *ids))}
            if user else set())
    for r in rows:
        r["votes"] = votes.get(r["id"], 0)
        r["mine"] = r["id"] in mine
    return rows


_ID = re.compile(r"[0-9]{1,18}")   # 10.11. (pregled): a message id or "prije" fits a SQLite integer; isdigit() let
                                   # 20+ digits and Unicode digits ("²") through to int() and SQLite (500, dropped POST)


def _before_ok(x):
    return bool(_ID.fullmatch(str(x or "")))


def _int(x):
    t = str(x or "").strip()
    if not _ID.fullmatch(t):
        raise ChatError("gone")
    return int(t)


def act(path, form, user):
    """One chat form. (True, "") or (False, code from ERR)."""
    if not user:
        return False, "login"
    try:
        con = _lcon()
    except sqlite3.Error as e:
        _warn("chat", e)
        return False, "db"
    try:
        if path == PATH + "/poruka":
            add_message(con, user, form.get("text"))
        elif path == PATH + "/plus":
            toggle_vote(con, user, _int(form.get("id")))
        elif path == PATH + "/sakrij":
            set_hidden(con, user, _int(form.get("id")), form.get("on") != "0")
        else:
            return False, "what"
    except ChatError as e:
        return False, e.code if e.code in ERR else "what"
    except sqlite3.Error as e:
        _warn("chat", e)
        return False, "db"
    finally:
        con.close()
    _GUEST.clear()   # guests see the change at their next refresh, not GUEST_TTL_S later
    return True, ""


def post(path, form, user):
    """Chat form -> where the browser goes next (the page, at the chat; a refusal as ?e=<code>)."""
    ok, code = act(path, form, user)
    return PATH + ("" if ok else f"?e={quote(code)}") + "#chat"


# ---------- chat: HTML --------------------------------------------------------------------------------------------

def show_text(text):
    """A stored message as the page prints it: escaped, never a link, e-mail addresses and key-long strings hidden."""
    t = _EMAIL.sub("[e-mail skriven]", text or "")
    t = _LONG.sub("[dugi niz skriven]", t)
    return esc(t).replace("\n", "<br>")


def _avatar(name):
    hue = int(hashlib.md5((name or "?").lower().encode()).hexdigest()[:4], 16) % 360
    return (f'<span class=apj-av aria-hidden=true translate=no style="background:hsl({hue} 70% 92%);color:hsl({hue} 45% 30%)">'
            f'{esc((name or "?")[:1].upper())}</span>')


def _msgs_html(rows, user, mod, note=""):
    items = []
    for m in rows:
        n = m["votes"]
        if user:
            vote = (f'<form method=post action="{PATH}/plus" class="apj-ajax apj-vote"><input type=hidden name=id value={m["id"]}>'
                    f'<button class="apj-plus{" on" if m["mine"] else ""}" aria-pressed={"true" if m["mine"] else "false"} '
                    f'title="{"Makni svoj +1" if m["mine"] else "Slažem se: +1"}"><i>+1</i>{f"<b>{n}</b>" if n else ""}</button></form>')
        else:
            vote = f'<span class=apj-plus title="+1 daju igrači prijavljeni svojim imenom"><i>+1</i>{f"<b>{n}</b>" if n else ""}</span>'
        hide = ""
        if mod:
            hide = (f'<form method=post action="{PATH}/sakrij" class="apj-ajax apj-hide"><input type=hidden name=id value={m["id"]}>'
                    f'<input type=hidden name=on value={"0" if m["hidden"] else "1"}>'
                    f'<button type=submit class=apj-x>{"Vrati" if m["hidden"] else "Sakrij"}</button></form>')
        items.append(f'<li class="apj-msg{" hid" if m["hidden"] else ""}" id=apj-m{m["id"]} data-id={m["id"]} data-n={n}>'
                     f'{_avatar(m["user"])}<div class=apj-mb><div class=apj-mh><b translate=no>{esc(m["user"])}</b>'
                     f'<span>{esc(ago(m["ts"])[0])}</span>{"<em>skriveno</em>" if m["hidden"] else ""}</div>'
                     f'<div class=apj-mt translate=no>{show_text(m["text"])}</div></div>'
                     f'<div class=apj-ma>{vote}{hide}</div></li>')
    body = "".join(items) or ('<li class=apj-empty>Još nema poruka. '
                              + ("Budi prvi: napiši što bi Autopilot trebao raditi bolje." if user else
                                 "Prva poruka se pojavi ovdje čim je netko napiše.") + '</li>')
    v = hashlib.md5(body.encode("utf-8")).hexdigest()[:10]
    more = (f'<p class=apj-more><a href="{PATH}?prije={rows[-1]["id"]}#chat">Starije poruke</a></p>'
            if len(rows) >= PAGE_N else "")
    return f'{note}<ul class=apj-msgs data-v={v}>{body}</ul>{more}'


def _note(code):
    return f'<p class="apj-note bad" role=alert>{esc(ERR[code])}</p>' if code in ERR else ""


def chat_fragment(user=None, qs=None, err=""):
    """The message list (GET /autopilot/chat and the answer to a chat form sent by the page script). The guest
    version is the same for everybody and kept GUEST_TTL_S."""
    qs = qs or {}
    before = qs.get("prije") if _before_ok(qs.get("prije")) else None
    key = ("chat",)
    if not user and not before and not err:
        hit = _GUEST.get(key)
        if hit and time.time() - hit[0] < GUEST_TTL_S:
            return hit[1]
    try:
        con = _lcon_read()
        try:
            mod = can_moderate(user)
            rows = messages(con, user, before=before, with_hidden=mod)
        finally:
            con.close()
        out = _msgs_html(rows, user, mod, _note(err))
    except sqlite3.Error as e:
        _warn("chat", e)
        return '<ul class=apj-msgs data-v=0><li class=apj-empty>Poruke se trenutno ne mogu učitati.</li></ul>'
    if not user and not before and not err:
        _GUEST[key] = (time.time(), out)
    return out


def _chat_box(user, qs, lang="hr", logged_in=None):
    qs = qs or {}
    older = _before_ok(qs.get("prije"))
    b = ['<h2 id=chat data-sec="">Prijedlozi i komentari</h2>'
         '<p class=apj-sub>Što bi Autopilot trebao raditi bolje? Napiši prijedlog ili primjedbu i daj +1 onima s kojima '
         'se slažeš. Poruke vide svi.</p>']
    if user:
        b.append(f'<form method=post action="{PATH}/poruka" class="apj-ajax apj-form">'
                 f'<textarea name=text rows=3 maxlength={MAX_LEN} required placeholder="Tvoj prijedlog ili primjedba" '
                 'aria-label="Tvoj prijedlog ili primjedba"></textarea>'
                 f'<div class=apj-fr><span>kao <b translate=no>{esc(user)}</b> · <span id=apj-cnt>0</span>/{MAX_LEN}</span>'
                 '<button>Pošalji</button></div></form>')
    elif logged_in:   # in the app without an own name: a login link would only reload this page
        b.append(f'<p class=apj-guest>Čitati mogu svi. {esc(ERR["login"])}</p>')
    else:
        from ui import urls
        home = "/" if lang == "en" else "/hr"
        b.append(f'<p class=apj-guest>Čitati mogu svi. <a href="{esc(urls.app_link(PATH + "?prijava=1"))}">Prijavi se</a> '
                 'da napišeš prijedlog i daš +1. Nemaš račun? '
                 f'<a href="{home}#pristup">Zatraži pristup</a>.</p>')
    b.append('<div class=apj-seg data-sort><button type=button class=on data-s=new>Najnovije</button>'
             '<button type=button data-s=top>Najviše +1</button></div>')
    src = "" if older else f' data-src="{CHAT_PATH}{"?l=en" if lang == "en" and not user else ""}"'
    b.append(f'<div id=apj-chat-list{src}>{chat_fragment(user, qs, err=qs.get("e") or "")}</div>')
    if older:
        b.append(f'<p class=apj-more><a href="{PATH}#chat">Na najnovije poruke</a></p>')
    return "".join(b)


# ---------- state and data snapshot -------------------------------------------------------------------------------

def _cfg(tcon):
    """The merged settings the Autopilot page reads: trade/config.json defaults + what the owner set there."""
    from trade import executor, settings
    try:
        base = executor.load_config()
    except (OSError, ValueError):
        base = {}
    return settings.merged({"size_sol": 0.05, **base}, tcon)


def _state(tcon):
    from trade import executor
    cfg = _cfg(tcon)
    on = bool(cfg.get("on"))
    live = bool(executor.is_live(cfg))
    row = tcon.execute("SELECT ts FROM settings WHERE k='on'").fetchone() if on else None
    since = int(row[0]) if row and row[0] else None
    if live and since:
        # 10.11.: the switch can go on in trial mode, before the key and TRADE_LIVE are there; "pravim novcem od" is
        # then the first real buy after it (walks positions_opened from the switch time, stops at the first match)
        first = tcon.execute("SELECT opened_ts FROM positions WHERE opened_ts >= ? AND mode='live' AND "
                             "status IN ('open','closed') ORDER BY opened_ts LIMIT 1", (since,)).fetchone()
        since = int(first[0]) if first and first[0] else since
    return {"live": live, "on": on, "since": since}


def live_state():
    """{"live": real money is being traded right now (trade.executor.is_live), "on": the owner's switch, "since":
    when it was switched on}. Kept LIVE_TTL_S, so the banner on every page costs one small read in 30 seconds.
    Anything that goes wrong reads as "not live": the page never claims real money by mistake."""
    now = time.time()
    hit = _LIVE["val"]
    if hit is not None and now - _LIVE["ts"] < LIVE_TTL_S:
        return hit
    val = {"live": False, "on": False, "since": None}
    try:
        tcon = _tcon()
        if tcon is not None:
            try:
                val = _state(tcon)
            finally:
                tcon.close()
    except Exception as e:  # noqa: BLE001 - the banner sits in every page: it must never raise
        _warn("stanje", e)
    _LIVE.update(ts=now, val=val)
    return val


def _address(raw):
    """The PUBLIC address of the trading wallet: the key's own when there is a key, else what the owner saved on the
    Autopilot page, else the public one from the environment. Printed only when it looks like an address."""
    addr = None
    try:
        from trade import wallet
        addr = wallet.address() if wallet.can_sign() else None
    except Exception as e:  # noqa: BLE001
        _warn("adresa", e)
    addr = addr or raw.get("wallet_pub") or os.environ.get("SOLANA_PUBLIC_KEY") or ""
    return addr if isinstance(addr, str) and ADDR.fullmatch(addr) else None


def _num(x):
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if v == v and abs(v) != float("inf") else None


def _equity(tcon):
    """(summary, series, deposits) of the wallet value from trade/equity.py; empty when it has nothing yet."""
    try:
        from trade import equity
        summ = equity.summary(tcon) or {}
        if not summ:
            return {}, [], []
        return summ, list(equity.series(tcon, max_points=600) or []), list(equity.deposits(tcon) or [])
    except Exception as e:  # noqa: BLE001
        _warn("vrijednost", e)
        return {}, [], []


def _eq_public(summ):
    """The few numbers of the summary the page prints, as plain floats (None = not known)."""
    out = {k: _num(summ.get(k)) for k in ("value_sol", "value_usd", "value_eur", "pnl_sol", "pnl_24h_sol", "net_in_sol")}
    out["last_ts"] = int(_num(summ.get("last_ts")) or 0) or None
    # the share is worked out here from the two SOL amounts, so it cannot be read in the wrong unit
    out["pnl_pct"] = (100 * out["pnl_sol"] / out["net_in_sol"]
                      if out["pnl_sol"] is not None and (out["net_in_sol"] or 0) > 0 else None)
    return out


def _spark(series):
    """The plain stand-in for the chart while ui/apchart.py is missing or fails: one line of the wallet value."""
    pts = [(_num(p.get("ts")), _num(p.get("value_sol"))) for p in series or [] if isinstance(p, dict)]
    pts = [(t, v) for t, v in pts if t is not None and v is not None]
    if len(pts) < 2:
        return '<p class=apj-wait>Graf kreće s prvom snimkom vrijednosti, za najviše 5 minuta.</p>'
    t0, t1 = pts[0][0], pts[-1][0]
    lo, hi = min(v for _, v in pts), max(v for _, v in pts)
    span_t, span_v = (t1 - t0) or 1, (hi - lo) or 1
    line = " ".join(f"{700 * (t - t0) / span_t:.1f},{150 - 140 * (v - lo) / span_v:.1f}" for t, v in pts)
    return ('<svg class=apj-spark viewBox="0 0 700 160" preserveAspectRatio="none" role=img '
            'aria-label="Vrijednost novčanika kroz vrijeme"><polyline fill="none" stroke="currentColor" stroke-width="2" '
            f'vector-effect="non-scaling-stroke" points="{line}"/></svg>'
            f'<div class=apj-ax><span>{lo:.3f} SOL</span><span>vrijednost novčanika kroz vrijeme</span><span>{hi:.3f} SOL</span></div>')


def _chart(summ, series, deposits, lang="hr"):
    try:
        from ui import apchart
        return apchart.chart_html(series, summ, deposits, ident="apj", compact=True, lang=lang)
    except Exception as e:  # noqa: BLE001 - the chart is another group's module
        _warn("graf", e)
        return _spark(series)


def chart_for(s, lang="hr"):
    """The chart of a snapshot in one language, drawn once per snapshot and language: ui/apchart.py has its own
    English words, and its script data is not something ui/i18n translates on the way out."""
    lang = "en" if lang == "en" else "hr"
    charts = s.setdefault("charts", {})
    if lang not in charts:
        summ, series, deposits = s.get("chart_in") or ({}, [], [])
        charts[lang] = _chart(summ, series, deposits, lang)
    return charts[lang]


_PNL = "COALESCE(sol_back,0)-COALESCE(sol_in,0)-COALESCE(fees_sol,0)"


def _stats(tcon, live):
    """Closed positions of one kind of money: real when real money trades now or ever did, else the trial ones.
    Result of a trade = SOL back - SOL in - network fees, as on the Autopilot page."""
    by = {}
    for mode, status, n, wins, pnl in tcon.execute(
            f"SELECT mode, status, COUNT(*), COALESCE(SUM({_PNL}>0),0), COALESCE(SUM({_PNL}),0) FROM positions "
            "WHERE status IN ('open','closed') GROUP BY mode, status"):
        by[(mode, status)] = (n, wins, pnl)
    mode = "live" if live or ("live", "closed") in by or ("live", "open") in by else "dry"
    n, wins, pnl = by.get((mode, "closed"), (0, 0, 0.0))
    out = {"mode": mode, "n": n, "wins": wins, "pnl": pnl, "open": by.get((mode, "open"), (0, 0, 0.0))[0],
           "best": None, "worst": None}
    if n:
        for key, order in (("best", "DESC"), ("worst", "ASC")):
            r = tcon.execute(f"SELECT symbol, {_PNL} FROM positions WHERE mode=? AND status='closed' ORDER BY 2 {order} "
                             "LIMIT 1", (mode,)).fetchone()
            out[key] = {"symbol": str(r[0] or "")[:20], "pnl": r[1]}
    return out


def _tool_targets(raw):
    """{(kind, target)} the tool itself put forward: the additions in its own log (trade settings auto_log) and the
    recommendation lists ui/autopilot.py already holds in memory. Nothing is computed for this: those lists read 30
    days of calls, too much for a public page, so a list nobody opened since the restart just does not count and
    the follow reads "odabir vlasnika" (never the other way round)."""
    out = set()
    for x in raw.get("auto_log") or []:
        if isinstance(x, dict) and x.get("op") == "+":
            out.add((x.get("kind"), str(x.get("target") or "").lower()))
    try:
        from ui import autopilot
        for name, (_ts, val) in list(autopilot._CACHE.items()):
            if not val:
                continue
            if name == "proven":
                out.update(("wallet", str(r["wallet"]).lower()) for r in val)
            elif name.startswith(("kol", "wal")):
                kind, field = ("kol", "handle") if name.startswith("kol") else ("wallet", "wallet")
                out.update((kind, str(r[field]).lower()) for rows in val.values() for r in rows)
    except Exception as e:  # noqa: BLE001
        _warn("preporuke", e)
    return out


def _exit_text(ex):
    """The exit rule of a follow in public words; only numbers that look like percentages are printed."""
    mode = (ex or {}).get("mode")
    if mode == "tpsl":
        parts = [f"{lab} {v.strip()}" for lab, v in (("cilj", str(ex.get("tp") or "")), ("stop", str(ex.get("sl") or "")))
                 if _PCT.fullmatch(v.strip())]
        return "izlaz: " + (", ".join(parts) if parts else "zadani cilj i stop")
    return {"mirror": "izlaz: prodaje kad on proda", "mirror_smart": "izlaz: prodaje kad on proda ili po pametnoj prodaji",
            "smart": "izlaz: pametna prodaja", "podaci": "izlaz: cilj i stop koje alat bira iz izmjerenih poziva",
            "manual": "izlaz: ručno"}.get(mode, "")


def _follows(lcon, raw):
    """Who the real-money account follows and who chose each one: 'alat' when the tool added the follow itself (its id
    is in trade settings auto_follows) or the target is among the tool's own recommendations, else 'vlasnik'."""
    from league import copy
    from trade import settings
    auto_ids = set()
    for i in raw.get("auto_follows") or []:
        try:
            auto_ids.add(int(i))
        except (TypeError, ValueError):
            pass
    tool = _tool_targets(raw)
    out = []
    for f in copy.follows(lcon, settings.LEAGUE_USER)[:FOLLOWS_N]:
        kind, target = f.get("kind"), str(f.get("target") or "")
        by_tool = f.get("id") in auto_ids or (kind, target.lower()) in tool
        label = str(f.get("label") or "")
        label = "" if label == target else label[:40]   # league.copy stores the target itself when no name was given
        out.append({"kind": kind, "target": target, "label": label, "since": f.get("created"),
                    "exit": _exit_text(f.get("exit")), "by": "alat" if by_tool else "vlasnik"})
    return out


def reason(text):
    """A reason as this page may print it: the short group from trade.aplog.why_short and nothing longer. Whatever
    looks like raw error text (a link, a query string, a stack trace, a whole sentence) becomes a neutral word."""
    t = " ".join(str(text or "").split())
    if not t:
        return ""
    return NEUTRAL_REASON if len(t) > 48 or _NOT_A_REASON.search(t) else t


def _source_text(src):
    """trade.aplog's source ("KOL ansem", "wallet Kit 12", "ekipa ...") in the words the rest of the page uses."""
    kind, _, name = (src or "").partition(" ")
    if kind == "KOL" and HANDLE.fullmatch(name.lstrip("@")):
        return "@" + name.lstrip("@")
    if kind == "wallet" and name:
        return "novčanik " + name
    return src or ""


def _why(text):
    """10.11. (pregled): "ostalo" says nothing to a visitor (the 24-h line already leaves it out): no reason printed."""
    w = reason(text)
    return "" if w == "ostalo" else w


def _move(r):
    """One row of trade.aplog.entries reduced to what the page prints, every field checked."""
    token, sig = str(r.get("token") or ""), str(r.get("sig") or "")
    # the source goes through reason() whole (cut first, a long raw text would slip under its length rule); a source
    # that is not fit to print is left out, "izvor: tehnički razlog" would say nothing
    source = _source_text(reason(r.get("source")))
    return {"ts": int(_num(r.get("ts")) or 0), "kind": r.get("kind"), "token": token if ADDR.fullmatch(token) else None,
            "symbol": str(r.get("symbol") or "")[:20], "source": "" if source == NEUTRAL_REASON else source,
            "why": _why(r.get("why_short")), "sol": _num(r.get("sol")), "pnl_pct": _num(r.get("pnl_pct")),
            "mode": "live" if r.get("mode") == "live" else "dry", "sig": sig if SIG.fullmatch(sig) else None}


def _moves_fallback(tcon, mode, before=None):
    """Entries and exits straight from the positions while trade/aplog.py is missing (or to fill the list up below
    what it returned): no reasons, only what happened, in one kind of money. `before`: only events older than this."""
    out = []
    for token, sym, opened, closed, status, sin, sback, fees in tcon.execute(
            "SELECT token, symbol, opened_ts, closed_ts, status, sol_in, sol_back, COALESCE(fees_sol,0) FROM positions "
            "WHERE mode=? AND status IN ('open','closed') ORDER BY id DESC LIMIT ?", (mode, MOVES_N)):
        base = {"token": token, "symbol": sym, "mode": mode, "source": "", "why_short": "", "sig": None}
        out.append({**base, "ts": opened, "kind": "kupio", "sol": sin, "pnl_pct": None})
        if status == "closed":
            pnl = (sback or 0) - (sin or 0) - (fees or 0)
            out.append({**base, "ts": closed or opened, "kind": "prodao", "sol": sback,
                        "pnl_pct": 100 * pnl / sin if sin else None})
    if before is not None:
        out = [r for r in out if (r["ts"] or 0) < before]
    out.sort(key=lambda r: r["ts"] or 0, reverse=True)
    return [_move(r) for r in out[:MOVES_N]]


def _day(summ):
    """The last 24 h in one line of counts; the reasons are the short groups, checked once more. The three most
    frequent that say something: "ostalo" (a reason trade.aplog has no word for yet) and an unfit text are left out."""
    if not isinstance(summ, dict):
        return None
    out = {k: int(_num(summ.get(k)) or 0) for k in ("signali", "kupio", "prodao", "preskocio", "nije_proslo", "capped")}
    out["razlozi"] = []
    for item in list(summ.get("razlozi") or [])[:20]:
        try:
            why, n = item
            why, n = reason(why), int(n)
        except (TypeError, ValueError):
            continue
        if why and why not in ("ostalo", NEUTRAL_REASON) and len(out["razlozi"]) < 3:
            out["razlozi"].append((why, n))
    return out


def _day_rows(aplog, tcon, lcon, now):
    """The 24-h summary over the WHOLE day: summary_24h when trade/aplog.py has it (kept a few seconds there), else
    summary() of the day's decisions. Not of the LOG_N newest rows: on a busy day those cover a few hours only."""
    fn = getattr(aplog, "summary_24h", None)
    if callable(fn):
        return fn(tcon, lcon, now=now)
    return aplog.summary(aplog.entries(tcon, lcon, limit=DAY_N, since=int(now) - 86400), now)


def _moves(tcon, lcon, now, mode):
    """(entries and exits, 24-h line or None) from trade.aplog; from the positions alone when that is not there.
    10.11.: only the money the statistics count (`mode`): a trial buy of last week among real ones would read as
    a real trade nobody can find on Solscan."""
    try:
        from trade import aplog
        rows = [r for r in (aplog.entries(tcon, lcon, limit=LOG_N) or []) if isinstance(r, dict)]
        moves = [_move(r) for r in rows if r.get("kind") in ("kupio", "prodao")]
        moves = [m for m in moves if m["mode"] == mode][:MOVES_N]
        if len(moves) < MOVES_N and len(rows) >= LOG_N:
            # LOG_N decisions were mostly skips: the older buys and sells come straight from the positions
            oldest = min(int(_num(r.get("ts")) or 0) for r in rows)
            moves += _moves_fallback(tcon, mode, before=oldest)[:MOVES_N - len(moves)]
        try:
            day = _day(_day_rows(aplog, tcon, lcon, now))
        except Exception as e:  # noqa: BLE001 - the line is a nicety, the list stays
            _warn("dnevnik 24 h", e)
            day = None
        return moves, day
    except Exception as e:  # noqa: BLE001 - another group's module
        _warn("dnevnik", e)
    return _moves_fallback(tcon, mode), None


def _empty(now):
    """A snapshot with nothing in it: every section shows its plain "not yet" sentence, nothing claims real money."""
    return {"ts": now, "state": {"live": False, "on": False, "since": None}, "addr": None, "eq": _eq_public({}),
            "chart_in": None, "stats": None, "follows": [], "moves": [], "day": None}


def _mode(s):
    """The kind of money the page reports on: the statistics' choice, or the switch state when they failed."""
    st = s.get("stats")
    return st["mode"] if st else ("live" if s["state"]["live"] else "dry")


def _read(now):
    """Everything from the databases, each part on its own: a part that fails leaves its place empty."""
    snap = _empty(now)
    raw = {}
    tcon = _tcon()
    lcon = None
    try:
        if tcon is not None:
            try:
                from trade import settings
                snap["state"] = _state(tcon)
                raw = settings.raw(tcon)
            except Exception as e:  # noqa: BLE001
                _warn("stanje", e)
            summ, series, deposits = _equity(tcon)
            snap["eq"] = _eq_public(summ)
            snap["chart_in"] = (summ, series, deposits)   # drawn per language by chart_for()
            try:
                snap["stats"] = _stats(tcon, snap["state"]["live"])
            except Exception as e:  # noqa: BLE001
                _warn("statistika", e)
        snap["addr"] = _address(raw)
        try:
            lcon = _lcon()
            snap["follows"] = _follows(lcon, raw)
        except Exception as e:  # noqa: BLE001
            _warn("praćeni", e)
        if tcon is not None:
            try:
                snap["moves"], snap["day"] = _moves(tcon, lcon, now, _mode(snap))
            except Exception as e:  # noqa: BLE001
                _warn("ulazi i izlazi", e)
    finally:
        for c in (tcon, lcon):
            if c is not None:
                c.close()
    return snap


def snapshot(now=None):
    """What the page shows from the databases, kept SNAP_TTL_S. One builder at a time; when the build itself fails
    the last good snapshot stays."""
    t = time.time()
    hit = _SNAP["val"]
    if hit is not None and t - _SNAP["ts"] < SNAP_TTL_S:
        return hit
    with _lock:
        hit = _SNAP["val"]
        if hit is not None and time.time() - _SNAP["ts"] < SNAP_TTL_S:
            return hit
        try:
            val = _read(now or t)
            if _RW["retry"]:   # a helper needed the read-write handle: once more with it (see _tcon)
                _RW["retry"] = False
                val = _read(now or t)
        except Exception as e:  # noqa: BLE001
            _warn("snimka", e)
            val = hit or _empty(t)
        _SNAP.update(ts=time.time(), val=val)
        _LIVE.update(ts=time.time(), val=val["state"])   # the banner and the page never disagree
        return val


# ---------- page: HTML --------------------------------------------------------------------------------------------

CSS = """<style>
.apj{max-width:760px;margin:0 auto;padding:0 0 28px}
.apj h1{font-size:30px;font-weight:800;letter-spacing:-.035em;margin:12px 0 0;line-height:1.15}
.apj h2{font-size:19px;font-weight:750;letter-spacing:-.02em;margin:36px 0 10px;padding:0;line-height:1.25}
.apj h2[id]{scroll-margin-top:84px}
.apj h2 small{font-size:12px;font-weight:600;color:var(--mut);background:var(--soft);border-radius:999px;padding:2px 9px;
 margin-left:6px;vertical-align:middle;letter-spacing:0}
.apj a{color:var(--acc,#4f46e5)}
.apj-state{display:inline-flex;align-items:center;gap:8px;border-radius:999px;padding:6px 13px;font-size:12.5px;font-weight:750;
 letter-spacing:.06em;text-transform:uppercase;background:var(--soft);color:var(--mut);line-height:1}
.apj-state.live{background:#ecfdf5;color:#15803d}
.apj-state i{width:8px;height:8px;border-radius:50%;background:currentColor;position:relative;flex:none}
.apj-state.live i::after{content:"";position:absolute;inset:0;border-radius:50%;background:currentColor;
 animation:apjp 2s cubic-bezier(.2,.6,.4,1) infinite}
@keyframes apjp{0%{transform:scale(1);opacity:.55}80%,100%{transform:scale(3);opacity:0}}
@media(prefers-reduced-motion:reduce){.apj-state.live i::after{animation:none}}
.apj-cap{font-size:13px;color:var(--mut);margin:18px 0 0}
.apj-big{font-size:clamp(46px,12vw,68px);font-weight:820;letter-spacing:-.045em;line-height:1.05;
 font-variant-numeric:tabular-nums;margin:2px 0 0}
.apj-big small{font-size:.4em;font-weight:700;color:var(--mut);letter-spacing:-.01em}
.apj-conv{font-size:20px;color:var(--mut);font-variant-numeric:tabular-nums;margin:2px 0 0}
.apj-pnl{display:flex;flex-wrap:wrap;gap:4px 18px;margin:10px 0 0;font-size:15px;font-variant-numeric:tabular-nums}
.apj-pnl>span{white-space:nowrap}.apj-pnl b{font-weight:650}.apj-pnl .mut{color:var(--mut)}
.apj .pos{color:var(--good,#16a34a)}.apj .neg{color:var(--bad,#dc2626)}
.apj-say{color:var(--mut);font-size:15.5px;line-height:1.5;margin:14px 0 0;max-width:62ch}
.apj-wait{color:var(--mut);font-size:14.5px;margin:10px 0 0}
.apj-wallet{display:flex;align-items:center;gap:8px 10px;flex-wrap:wrap;border:1px solid var(--line);border-radius:18px;
 padding:12px 14px;margin:20px 0 0;background:var(--card,#fff)}
.apj-wallet .l{flex-basis:100%;font-size:12.5px;color:var(--mut)}
.apj-wallet code{flex:1;min-width:0;font:13.5px ui-monospace,Menlo,monospace;word-break:break-all;color:var(--fg)}
.apj-btn{display:inline-flex;align-items:center;gap:6px;border:1px solid var(--line);border-radius:999px;padding:7px 14px;
 font:inherit;font-size:13.5px;font-weight:600;background:#fff;color:var(--fg)!important;text-decoration:none;cursor:pointer;
 white-space:nowrap}.apj-btn:hover{border-color:var(--line2,#cfd5e1);background:#fff;box-shadow:none}
.apj-chart{margin:20px 0 0;min-width:0}.apj-spark{display:block;width:100%;height:160px;color:var(--acc,#4f46e5)}
.apj-ax{display:flex;justify-content:space-between;gap:8px;font-size:12px;color:var(--mut);margin-top:4px}
.apj-stats{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px}
.apj-stat{background:var(--soft);border-radius:18px;padding:13px 15px;min-width:0}
.apj-stat b{display:block;font-size:22px;font-weight:760;letter-spacing:-.02em;font-variant-numeric:tabular-nums;
 white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.apj-stat span{display:block;font-size:12.5px;color:var(--mut);margin-top:1px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.apj-stat span i{font-style:normal;font-weight:600;color:var(--fg)}.apj-stat b small{font-size:.6em;font-weight:650;color:var(--mut)}
.apj-sub{color:var(--mut);font-size:14.5px;margin:-4px 0 12px;max-width:62ch}
.apj-list{list-style:none;margin:0;padding:0;border:1px solid var(--line);border-radius:18px;background:var(--card,#fff);overflow:hidden}
.apj-list>li{display:flex;align-items:center;gap:12px;padding:12px 14px;border-top:1px solid var(--line);min-width:0}
.apj-list>li:first-child{border-top:0}.apj-list>li[hidden]{display:none}
.apj-list .mid{flex:1;min-width:0}.apj-list .mid b{font-weight:650}.apj-list .mid b a{color:var(--fg);text-decoration:none}
.apj-list .mid b a:hover{text-decoration:underline}
.apj-list small{display:block;color:var(--mut);font-size:12.5px;line-height:1.4;margin-top:1px;overflow-wrap:anywhere}
.apj-list .r{flex:none;font-variant-numeric:tabular-nums;font-weight:650;white-space:nowrap;text-align:right}
.apj-list .r small{font-weight:400;white-space:nowrap}.apj-list .r small a{color:var(--mut);text-decoration:none}
.apj-list .r small a:hover{text-decoration:underline}
.apj-tag{display:inline-block;font-size:11.5px;font-weight:600;color:var(--mut);background:var(--soft);border-radius:999px;
 padding:1px 8px;margin-left:6px;vertical-align:middle;white-space:nowrap}
.apj-by{flex:none;font-size:12px;font-weight:650;border-radius:999px;padding:4px 10px;background:var(--soft);color:var(--mut);
 white-space:nowrap}.apj-by.tool{background:#eef2ff;color:#4338ca}
.apj-k{flex:none;width:62px;text-align:center;font-size:12px;font-weight:700;border-radius:999px;padding:4px 0;
 background:var(--soft);color:var(--fg)}.apj-k.buy{background:#ecfdf5;color:#15803d}
.apj-seg{display:inline-flex;background:var(--soft);border-radius:999px;padding:3px;gap:2px;margin:0 0 10px}
.apj-seg button{border:0;background:none;color:var(--mut);border-radius:999px;padding:6px 14px;font:inherit;font-size:13.5px;
 font-weight:600;cursor:pointer;box-shadow:none}.apj-seg button:hover{background:none;color:var(--fg);box-shadow:none}
.apj-seg button.on{background:#fff;color:var(--fg);box-shadow:0 1px 2px rgba(11,18,32,.12)}
.apj-day{color:var(--mut);font-size:13.5px;margin:10px 2px 0}
.apj-form{margin:0 0 14px}.apj-form textarea{display:block;width:100%;min-height:84px;resize:vertical;padding:12px 14px;
 border:1px solid var(--line);border-radius:16px;background:var(--soft);color:var(--fg);font:inherit;font-size:16px;line-height:1.45}
.apj-form textarea:focus{outline:none;border-color:var(--acc,#4f46e5);background:#fff;box-shadow:0 0 0 4px rgba(79,70,229,.12)}
.apj-fr{display:flex;justify-content:space-between;align-items:center;gap:10px;margin-top:8px;font-size:13px;color:var(--mut)}
.apj-fr button{border:1px solid var(--fg);background:var(--fg);color:#fff;border-radius:999px;padding:9px 20px;font:inherit;
 font-weight:650;cursor:pointer}.apj-fr button:disabled{opacity:.5}
.apj-guest{background:var(--soft);border-radius:16px;padding:12px 14px;font-size:14.5px;margin:0 0 14px}
.apj-note{border-radius:14px;padding:10px 14px;font-size:14px;margin:0 0 10px;background:var(--soft)}
.apj-note.bad{background:#fef2f2;color:#991b1b}
.apj-msgs{list-style:none;margin:0;padding:0}
.apj-msg{display:flex;gap:11px;align-items:flex-start;padding:13px 0;border-top:1px solid var(--line)}
.apj-msgs>li:first-child{border-top:0}.apj-msg.hid{opacity:.5}
.apj-av{flex:none;width:34px;height:34px;border-radius:50%;display:grid;place-items:center;font-weight:750;font-size:14px}
.apj-mb{flex:1;min-width:0}.apj-mh{display:flex;gap:8px;align-items:baseline;flex-wrap:wrap;font-size:14px}
.apj-mh span{color:var(--mut);font-size:12.5px}.apj-mh em{font-style:normal;font-size:11.5px;color:var(--mut);
 border:1px solid var(--line);border-radius:999px;padding:0 7px}
.apj-mt{font-size:15px;line-height:1.5;margin-top:2px;overflow-wrap:anywhere}
.apj-ma{flex:none;display:flex;flex-direction:column;align-items:flex-end;gap:6px}.apj-ma form{margin:0}
.apj-plus{display:inline-flex;align-items:center;gap:7px;border:1px solid var(--line);border-radius:999px;padding:6px 12px;
 background:#fff;color:var(--fg);font:inherit;font-size:13.5px;font-weight:650;line-height:1.2;white-space:nowrap;box-shadow:none}
button.apj-plus{cursor:pointer}button.apj-plus:hover{border-color:var(--line2,#cfd5e1);background:#fff;box-shadow:none}
.apj-plus i{font-style:normal;color:var(--mut)}.apj-plus b{font-variant-numeric:tabular-nums;min-width:1ch;text-align:center}
.apj-plus.on{background:var(--fg);border-color:var(--fg);color:#fff}.apj-plus.on i{color:#cbd2df}
button.apj-plus.on:hover{background:#1f2937;border-color:#1f2937}
.apj-x{border:0;background:none;color:var(--mut);font:inherit;font-size:12px;padding:2px 4px;cursor:pointer;
 text-decoration:underline;box-shadow:none;border-radius:6px}.apj-x:hover{background:none;color:var(--fg);box-shadow:none}
.apj-empty{color:var(--mut);padding:18px 0;font-size:14.5px}.apj-more{font-size:14px;margin:10px 0 0}
.apj-fine{color:var(--mut);font-size:12.5px;line-height:1.5;margin:32px 0 0;border-top:1px solid var(--line);padding-top:14px}
@media(max-width:560px){.apj h1{font-size:26px}.apj-stats{grid-template-columns:1fr 1fr}.apj-stat b{font-size:19px}
 .apj-conv{font-size:18px}.apj-wallet code{flex-basis:100%;font-size:11.6px;letter-spacing:-.01em}.apj-list>li{padding:11px 12px;gap:10px}
 .apj-k{width:56px}.apj-by{font-size:11.5px;padding:4px 8px}}
.apj-ownp{margin:14px 0 0}.apj-own{display:inline-block;padding:11px 18px;border-radius:999px;background:var(--fg);color:var(--bg,#fff);font-weight:650;text-decoration:none}
</style>"""

# One script for the whole page: copy the address, filter the entries and exits, sort and refresh the chat (one
# request at a time, never while the tab is in the background), send chat forms without leaving the page. Words the
# visitor reads live in the HTML (title, data-ready), so the English version translates them with everything else.
JS = """<script>(()=>{const R=document.querySelector('.apj');if(!R||R.dataset.on)return;R.dataset.on=1;
const box=document.getElementById('apj-chat-list');let busy=false,sort='new';
R.addEventListener('click',e=>{const c=e.target.closest('.apj-copy');
 if(c){e.preventDefault();const m=c.dataset.m,t=c.textContent;
  (navigator.clipboard?navigator.clipboard.writeText(m):Promise.reject()).then(()=>{c.textContent=c.dataset.ready;
   setTimeout(()=>{c.textContent=t},1600)},()=>prompt(c.title,m));return}
 const b=e.target.closest('.apj-seg button');if(!b)return;const g=b.parentNode;
 g.querySelectorAll('button').forEach(x=>x.classList.toggle('on',x===b));
 if(g.dataset.for){const k=b.dataset.k;document.querySelectorAll('#'+g.dataset.for+'>li').forEach(li=>{li.hidden=!!k&&li.dataset.k!==k})}
 if('sort' in g.dataset){sort=b.dataset.s;order()}});
function order(){const ul=box&&box.querySelector('.apj-msgs');if(!ul)return;const li=[...ul.querySelectorAll('li[data-id]')];
 li.sort((a,b)=>sort==='top'&&b.dataset.n!==a.dataset.n?b.dataset.n-a.dataset.n:b.dataset.id-a.dataset.id);li.forEach(x=>ul.appendChild(x))}
function put(h,force){const t=document.createElement('template');t.innerHTML=h;const nu=t.content.querySelector('[data-v]'),
 cur=box.querySelector('[data-v]');if(!nu)return;if(!force&&cur&&cur.dataset.v===nu.dataset.v&&!box.querySelector('.apj-note'))return;
 box.innerHTML=h;order()}
async function poll(){if(busy||document.hidden||!box||!box.dataset.src)return;busy=true;
 try{const r=await fetch(box.dataset.src,{cache:'no-store'});if(r.ok)put(await r.text())}catch(e){}finally{busy=false}}
if(box)setInterval(poll,__POLL__);
let lbusy=false;async function live(){if(lbusy||document.hidden||!R.dataset.live)return;lbusy=true;
 try{const r=await fetch(R.dataset.live,{cache:'no-store'});if(!r.ok)return;const t=document.createElement('template');
  t.innerHTML=await r.text();let chart=false;
  t.content.querySelectorAll('.apj-live[id]').forEach(nu=>{const cur=document.getElementById(nu.id);
   if(!cur||cur.dataset.v===nu.dataset.v)return;
   const g=cur.querySelector('.apj-seg[data-for] button.on'),k=g?g.dataset.k:'';
   cur.replaceWith(nu);if(nu.id==='apj-l-chart')chart=true;
   if(k){const b=nu.querySelector('.apj-seg[data-for] button[data-k="'+k+'"]');if(b)b.click()}});
  if(chart&&window.apcInit)window.apcInit()}catch(e){}finally{lbusy=false}}
setInterval(live,__LIVE__);document.addEventListener('visibilitychange',()=>{if(!document.hidden)live()});
const ta=R.querySelector('.apj-form textarea'),cnt=document.getElementById('apj-cnt');
const count=()=>{if(ta&&cnt)cnt.textContent=ta.value.length};
if(ta){ta.addEventListener('input',count);ta.addEventListener('keydown',e=>{if(e.key==='Enter'&&(e.ctrlKey||e.metaKey)&&ta.form.requestSubmit){e.preventDefault();ta.form.requestSubmit()}})}
R.addEventListener('submit',async e=>{const f=e.target.closest('form.apj-ajax');if(!f||!window.fetch||!box)return;e.preventDefault();
 const d=new URLSearchParams(new FormData(f));d.set('ajax','1');const btn=f.querySelector('button');if(btn)btn.disabled=true;busy=true;
 try{const r=await fetch(f.getAttribute('action'),{method:'POST',headers:{'Content-Type':'application/x-www-form-urlencoded'},body:d});
  if(!r.ok){location.reload();return}put(await r.text(),true);
  if(f.classList.contains('apj-form')&&!box.querySelector('.apj-note.bad')){f.reset();count()}}
 catch(err){f.submit()}finally{busy=false;if(btn)btn.disabled=false}})})()</script>""".replace(
    "__POLL__", str(POLL_S * 1000)).replace("__LIVE__", str(LIVE_POLL_S * 1000))


def _cls(v, nd=3):
    """pos / neg for a number as it is printed: +0.0003 SOL shown as +0.000 is neither."""
    v = round(v, nd) if v is not None else 0
    return "pos" if v > 0 else "neg" if v < 0 else ""


def _money(v):
    return f"{v:,.2f}" if abs(v) < 10 else f"{v:,.0f}"


def _date(ts_):
    """6.11.2026. in Zagreb time (the day the owner's switch went on)."""
    import datetime
    from zoneinfo import ZoneInfo
    d = datetime.datetime.fromtimestamp(ts_, ZoneInfo("Europe/Zagreb"))
    return f"{d.day}.{d.month}.{d.year}."


def _hero(s):
    st, eq = s["state"], s["eq"]
    if st["live"]:
        since = f" Pravim novcem od {_date(st['since'])}" if st.get("since") else ""
        pill = '<span class="apj-state live"><i></i>Uživo · pravi novac</span>'
        say = ("Bot sam kupuje i prodaje meme tokene pravim novcem, prema podacima alata. Sve je javno: novčanik, svaki "
               f"ulaz i svaki izlaz.{since}")
    else:
        pill = '<span class=apj-state><i></i>Probni rad · bez pravog novca</span>'
        say = ("Autopilot sada radi probno: prati iste signale i bilježi što bi kupio i prodao, ali ne troši pravi novac. "
               "Kad krene pravim novcem, ovdje će pisati UŽIVO.")
    b = [f'<div class=apj-hero>{pill}<h1>Autopilot</h1>']
    v = eq.get("value_sol")
    if v is not None:
        conv = " · ".join(f"{_money(x)} {unit}" for x, unit in ((eq.get("value_usd"), "$"), (eq.get("value_eur"), "€"))
                          if x is not None)
        b.append(f'<p class=apj-cap>Vrijednost novčanika{" · izmjereno " + esc(ago(eq["last_ts"])[0]) if eq.get("last_ts") else ""}</p>'
                 f'<div class=apj-big translate=no>{v:.3f} <small>SOL</small></div>'
                 + (f'<div class=apj-conv translate=no>{conv}</div>' if conv else ""))
        pnl, pct, d24 = eq.get("pnl_sol"), eq.get("pnl_pct"), eq.get("pnl_24h_sol")
        if pnl is not None:   # two pieces that wrap as a whole on a phone, never in the middle of a number
            line = (f'<span><span class=mut>Od početka</span> <b class="{_cls(pnl)}">{pnl:+.3f} SOL'
                    f'{f" ({pct:+.1f} %)" if pct is not None else ""}</b></span>')
            if d24 is not None:
                line += f'<span><span class=mut>Zadnja 24 h</span> <b class="{_cls(d24)}">{d24:+.3f} SOL</b></span>'
            b.append(f'<p class=apj-pnl>{line}</p>')
    else:
        b.append('<p class=apj-wait>Vrijednost novčanika mjeri se svakih 5 minuta. Prva snimka još nije stigla.</p>')
    b.append(f'<p class=apj-say>{say} <a href="#chat">Dodaj svoj prijedlog</a>.</p></div>')
    return "".join(b)


def _wallet(addr):
    if not addr:
        return '<div class=apj-wallet><span class=l>Javna adresa novčanika</span><span class=mut>Još nije postavljena.</span></div>'
    return ('<div class=apj-wallet><span class=l>Javna adresa novčanika: svatko može provjeriti svaku transakciju</span>'
            f'<code translate=no>{esc(addr)}</code>'
            f'<button type=button class="apj-btn apj-copy" data-m="{esc(addr)}" data-ready="Kopirano" title="Kopiraj adresu">Kopiraj</button>'
            f'<a class=apj-btn href="https://solscan.io/account/{quote(addr)}" target=_blank rel="noopener nofollow">Solscan ↗</a></div>')


def _stats_html(st):
    if not st:
        return ('<h2 data-sec="">Statistika</h2><p class=apj-wait>Statistika se trenutno ne može učitati. Pokušaj ponovno '
                'za minutu.</p>')
    head = f'<h2 data-sec="">Statistika <small>{MODE_TAG[st["mode"]]}</small></h2>'
    if not st["n"]:
        return (head + '<p class=apj-wait>Još nema zatvorenih tradeova. Čim bot zatvori prvi, brojke se pojave ovdje.'
                + (f' Otvoreno sada: {st["open"]}.' if st["open"] else "") + '</p>')

    def tile(value, label, cls=""):
        return f'<div class=apj-stat><b{f" class={cls}" if cls else ""}>{value}</b><span>{label}</span></div>'

    def edge(key, label):
        r = st.get(key)
        if not r or r.get("pnl") is None:
            return tile("–", label)
        sym = f' · <i translate=no>{esc(r["symbol"])}</i>' if r.get("symbol") else ""
        return tile(f'{r["pnl"]:+.3f} SOL', label + sym, _cls(r["pnl"]))
    return (head + '<div class=apj-stats>'
            + tile(st["n"], "Zatvoreni tradeovi")
            + tile(f'{st["wins"]} <small>({round(100 * st["wins"] / st["n"])} %)</small>', "Dobitni")
            + tile(f'{st["pnl"]:+.3f} SOL', "Ukupni rezultat", _cls(st["pnl"]))
            + edge("best", "Najbolji trade") + edge("worst", "Najgori trade")
            + tile(st["open"], "Otvoreno sada") + '</div>'
            '<p class=apj-day>Rezultat tradea = SOL koji se vratio, minus uloženi SOL, minus mrežne naknade.</p>')


def _who(f):
    """One followed account as a public link: X profile, Telegram channel or the wallet on Solscan."""
    def one(h):
        h = h.strip().lstrip("@")
        if h.startswith("tg:") and HANDLE.fullmatch(h[3:]):
            return f'<a href="https://t.me/{h[3:]}" target=_blank rel="noopener nofollow" translate=no>✈ {esc(h[3:])}</a>'
        if HANDLE.fullmatch(h):
            return f'<a href="https://x.com/{h}" target=_blank rel="noopener nofollow" translate=no>@{esc(h)}</a>'
        return f'<span translate=no>{esc(h[:30])}</span>'
    kind, target = f["kind"], f["target"]
    if kind == "wallet":
        name = f' <span translate=no>{esc(f["label"])}</span>' if f["label"] else ""
        if ADDR.fullmatch(target):
            return (f'<a href="https://solscan.io/account/{quote(target)}" target=_blank rel="noopener nofollow" translate=no>'
                    f'{esc(short(target))}</a>{name}', "novčanik")
        return f'<span translate=no>{esc(short(target))}</span>{name}', "novčanik"
    if kind == "ekipa":
        return " + ".join(one(m) for m in target.split(",") if m.strip()), "ekipa"
    return one(target), "influencer"


def _follows_html(rows):
    head = ('<h2 data-sec="">Koga Autopilot prati</h2><p class=apj-sub>Bot ulazi kad netko od njih pozove ili kupi token. '
            '„Preporuka alata” znači da ga je alat sam predložio prema izmjerenim rezultatima, „odabir vlasnika” da ga je '
            'dodao vlasnik.</p>')
    if not rows:
        return head + '<p class=apj-wait>Trenutno nikoga. Čim vlasnik ili alat nekoga odabere, popis se pojavi ovdje.</p>'
    items = []
    for f in rows:
        who, kind = _who(f)
        sub = " · ".join(x for x in (f"dodan {ago(f['since'])[0]}" if f.get("since") else "", f["exit"]) if x)
        by = ('<span class="apj-by tool">preporuka alata</span>' if f["by"] == "alat"
              else '<span class=apj-by>odabir vlasnika</span>')
        items.append(f'<li><div class=mid><b>{who}</b><span class=apj-tag>{kind}</span>'
                     f'{f"<small>{esc(sub)}</small>" if sub else ""}</div>{by}</li>')
    return head + f'<ul class=apj-list>{"".join(items)}</ul>'


def _moves_html(rows, day, mode):
    head = f'<h2 data-sec="">Zadnji ulazi i izlazi <small>{MODE_TAG[mode]}</small></h2>'
    line = ""
    if day and day.get("signali"):
        why = ", ".join(f"{n} {esc(w)}" for w, n in day["razlozi"])   # short: a zero count is left out below
        parts = [f'{day["signali"]} signala', f'{day["kupio"]} kupljeno']
        parts += [f'{n} {word}' for n, word in ((day["prodao"], "prodano"),) if n]
        parts += [f'{day["preskocio"]} preskočeno{f" ({why})" if why else ""}'] if day["preskocio"] else []
        parts += [f'{day["nije_proslo"]} nije prošlo'] if day["nije_proslo"] else []
        lbl = f"Zadnjih {day['capped']} odluka" if day.get("capped") else "Zadnja 24 h"   # 10.11. (pregled)
        line = f'<p class=apj-day>{lbl}: {" · ".join(parts)}</p>'
    if not rows:
        return head + '<p class=apj-wait>Još nema nijednog ulaza. Čim bot nešto kupi ili proda, pojavi se ovdje.</p>' + line
    items = []
    for m in rows:
        buy = m["kind"] == "kupio"
        name = esc(m["symbol"] or (short(m["token"]) if m["token"] else "token"))
        if m["token"]:
            name = (f'<a href="https://dexscreener.com/solana/{quote(m["token"])}" target=_blank rel="noopener nofollow">'
                    f'{name}</a>')
        sub = esc(" · ".join(x for x in (f"izvor: {m['source']}" if m["source"] else "", m["why"]) if x))
        when = esc(ago(m["ts"])[0]) if m["ts"] else ""
        if m["sig"]:   # the time is the link to the proof: the transaction itself on Solscan
            when = (f'<a href="https://solscan.io/tx/{quote(m["sig"])}" target=_blank rel="noopener nofollow" '
                    f'title="Otvori transakciju na Solscanu">{when} ↗</a>')
        if buy:
            right = f'{m["sol"]:.3f} SOL' if m["sol"] is not None else ""
        else:
            right = (f'<span class="{_cls(m["pnl_pct"], 1)}">{m["pnl_pct"]:+.1f} %</span>' if m["pnl_pct"] is not None
                     else (f'{m["sol"]:.3f} SOL' if m["sol"] is not None else ""))
        items.append(f'<li data-k={"kupio" if buy else "prodao"}><span class="apj-k{" buy" if buy else ""}">'
                     f'{"Kupio" if buy else "Prodao"}</span><div class=mid><b translate=no>{name}</b>'
                     f'{f"<small>{sub}</small>" if sub else ""}</div>'
                     f'<div class=r><span translate=no>{right}</span><small>{when}</small></div></li>')
    seg = ('<div class=apj-seg data-for=apj-moves><button type=button class=on data-k="">Sve</button>'
           '<button type=button data-k=kupio>Ulazi</button><button type=button data-k=prodao>Izlazi</button></div>')
    return head + seg + f'<ul class=apj-list id=apj-moves>{"".join(items)}</ul>' + line


FINE = ("Ovo nije financijski savjet. Meme tokeni su vrlo rizični i prošli rezultati ne jamče buduće. Brojke su stvarno "
        "stanje jednog novčanika, sa svim naknadama. Stranica se sama osvježava svakih 15 sekundi, a vrijednost "
        "novčanika odmah nakon svakog tradea (inače svakih 5 minuta).")


def _parts(s, lang):
    """The live parts of the page, in order, as (name, html)."""
    return [("hero", _hero(s)), ("chart", f'<div class=apj-chart>{chart_for(s, lang)}</div>'),
            ("stats", _stats_html(s["stats"])), ("follows", _follows_html(s["follows"])),
            ("moves", _moves_html(s["moves"], s["day"], _mode(s)))]


def _live_div(name, html):
    v = hashlib.sha1(html.encode("utf-8")).hexdigest()[:12]
    return f'<div class=apj-live id=apj-l-{name} data-v={v}>{html}</div>'


def live_fragment(lang="hr"):
    """GET /autopilot/zivo: the live parts alone (every one in its div with a version), for the page script. The same
    for every visitor and kept GUEST_TTL_S; the snapshot behind it is SNAP_TTL_S old at most."""
    key = ("live", lang)
    hit = _GUEST.get(key)
    if hit and time.time() - hit[0] < GUEST_TTL_S:
        return hit[1]
    out = "".join(_live_div(n, h) for n, h in _parts(snapshot(), lang))
    _GUEST[key] = (time.time(), out)
    return out


def page(qs, user, lang="hr", logged_in=None):
    """(title, body). The body is Croatian; the English version is the same page run through ui/i18n by the caller
    (run_ui), like every other page of the app. logged_in: inside the app without a player's own name (the shared
    password, the view-only account): no chat form and no "Prijavi se" either, only why not (default: bool(user))."""
    s = snapshot()
    title = TITLE if s["state"]["live"] else "Autopilot (probni rad)"
    parts = dict(_parts(s, lang))
    src = LIVE_PATH + ("?l=en" if lang == "en" else "")
    own = ""
    try:   # 10.11. (Jure: "zašto preko mobitela ne mogu na autopilotu kupiti token?"): this page only shows; the
        # owner gets the way to the trading page (quick buy) right under the value. Never for anybody else.
        from trade import settings as _ts
        if user and _ts.is_owner(user):
            own = ('<p class=apj-ownp><a class=apj-own href="/pravi-trade#kupi-odmah">Kupi token · upravljaj '
                   'Autopilotom →</a></p>')
    except Exception:  # noqa: BLE001 - the public page never fails on this
        own = ""
    body = (CSS + f'<div class=apj data-live="{src}">' + _live_div("hero", parts["hero"]) + own + _wallet(s["addr"])
            + "".join(_live_div(n, parts[n]) for n in ("chart", "stats", "follows", "moves"))
            + _chat_box(user, qs, lang, logged_in)
            + f'<p class=apj-fine>{FINE}</p></div>' + JS)
    return title, body


GUEST_CSS = """
body{margin:0}.apj-top{position:sticky;top:0;z-index:30;background:rgba(255,255,255,.88);-webkit-backdrop-filter:blur(12px);
 backdrop-filter:blur(12px);border-bottom:1px solid var(--line)}
.apj-top>div{max-width:760px;margin:0 auto;padding:0 16px;height:58px;display:flex;align-items:center;gap:14px}
.apj-top .brand{display:flex;align-items:center;gap:9px;min-width:0;font-size:17px;font-weight:750;letter-spacing:-.02em;
 color:var(--fg);text-decoration:none;white-space:nowrap}.apj-top .brand svg{flex:none;display:block}.apj-top .sp{flex:1}
.apj-top a.lnk{color:var(--mut);text-decoration:none;font-size:14.5px;font-weight:500}.apj-top a.lnk:hover{color:var(--fg)}
.apj-top a.go{background:var(--fg);color:#fff;border-radius:999px;padding:8px 16px;font-size:14px;font-weight:650;
 text-decoration:none;white-space:nowrap}
main.apj-main{max-width:none;padding:18px 16px 40px}
.apj-foot{border-top:1px solid var(--line);color:var(--mut);font-size:13px;text-align:center;padding:22px 16px 34px}
.apj-foot a{color:var(--mut);margin:0 7px;text-decoration:none}.apj-foot a:hover{color:var(--fg)}
@media(max-width:560px){.apj-top a.lnk.x{display:none}.apj-top>div{gap:10px;padding:0 12px}}
"""


# 13.11. (SEO audit): the visitor's frame says its own words in each language; the English description used to be the
# Croatian one (ui/i18n translates the page text, never meta content)
GUEST_DESC = {
    "hr": "Autopilot trguje meme tokenima po podacima alata. Javno: adresa novčanika, vrijednost, svaki ulaz i izlaz, "
          "koga prati i prijedlozi igrača.",
    "en": "Autopilot trades Solana meme coins on MemeSonar's data, in public: wallet address, value, every entry and "
          "exit, whom it follows and players' suggestions.",
}
GUEST_WORDS = {
    "hr": {"home": "Naslovnica", "kols": "Influenceri", "coins": "Meme coini", "login": "Prijava", "cta": "Zatraži pristup"},
    "en": {"home": "Home", "kols": "Influencers", "coins": "Meme coins", "login": "Log in", "cta": "Request access"},
}


def guest_html(qs=None, lang="hr"):
    """The whole page for a visitor without a login: a light frame with the app's own colours (so the chart looks the
    same as inside the app), no app menu, links back to the public site and to the login. Croatian; run_ui translates
    it for /en/autopilot. The plain view is kept GUEST_TTL_S (the same for every visitor)."""
    qs = qs or {}
    plain = not qs.get("prije") and not qs.get("e")
    key = ("page", lang)
    if plain:
        hit = _GUEST.get(key)
        if hit and time.time() - hit[0] < GUEST_TTL_S:
            return hit[1]
    from ui import html as H, urls
    from ui import favicon
    title, body = page(qs, None, lang)
    svg, name = H.logo(28)
    home = "/" if lang == "en" else "/hr"
    here = PATH_EN if lang == "en" else PATH
    desc = GUEST_DESC[lang]
    base = urls.site()
    og = ""
    try:
        from ui import i18n, public
        tok = i18n.LANG.set(lang)   # og:title is an attribute ui/i18n leaves alone: in the page language here
        try:
            og_title = i18n.t(title)
        finally:
            i18n.LANG.reset(tok)
        card, alt = public.og_card(here, lang)
        og = (f'<meta property="og:type" content="website"><meta property="og:title" content="{esc(og_title)} · {esc(name)}">'
              f'<meta property="og:description" content="{esc(desc)}"><meta property="og:url" content="{esc(base + here)}">'
              + public.og_tags(lang, base + card, alt))
    except Exception as e:  # noqa: BLE001 - the share preview is a nicety
        _warn("og", e)
    # 13.11. (SEO audit): both copies name each other, so Google shows the visitor's language and never counts them as
    # duplicates (they had a canonical each but no hreflang)
    alts = (f'<link rel=alternate hreflang=en href="{esc(base + PATH_EN)}"><link rel=alternate hreflang=hr '
            f'href="{esc(base + PATH)}"><link rel=alternate hreflang=x-default href="{esc(base + PATH_EN)}">')
    try:
        from ui import public
        tail = public._ga_tag(lang)   # the public pages' visit counter + the friendly deploy page
    except Exception as e:  # noqa: BLE001
        _warn("ga", e)
        tail = ""
    w = GUEST_WORDS[lang]
    links = ((home, w["home"]), ("/influencers" if lang == "en" else "/hr/influenceri", w["kols"]),
             ("/solana-meme-coins" if lang == "en" else "/hr/solana-meme-coini", w["coins"]),
             ("/blog" if lang == "en" else "/hr/blog", "Blog"))
    other = (f'<a class="lnk x" href="{PATH}" hreflang=hr translate=no>HR</a>' if lang == "en" else
             f'<a class="lnk x" href="{PATH_EN}" hreflang=en translate=no>EN</a>')
    out = (f'<!doctype html><html lang=hr><head><meta charset=utf-8><meta name=viewport content="width=device-width,'
           f'initial-scale=1,viewport-fit=cover"><meta name=color-scheme content=light><title>{esc(title)} · {esc(name)}</title>'
           f'<meta name=description content="{esc(desc)}"><link rel=canonical href="{esc(base + here)}">{alts}{og}'
           f'<meta name=theme-color content="#ffffff">{favicon.HEAD}'
           f'<style>{H.CSS}{H.LIGHT_CSS}{GUEST_CSS}</style></head><body>'
           f'<header class=apj-top><div><a class=brand href="{home}">{svg}<span translate=no>{esc(name)}</span></a><span class=sp></span>'
           f'{other}<a class=lnk href="{esc(urls.app_link(PATH + "?prijava=1"))}">{w["login"]}</a>'
           f'<a class=go href="{home}#pristup">{w["cta"]}</a></div></header>'
           f'<main class=apj-main>{body}</main>'
           f'<footer class=apj-foot>{"".join(f"<a href={h}>{esc(t)}</a>" for h, t in links)}<br>© {time.gmtime().tm_year} '
           f'<span translate=no>{esc(name)}</span></footer>{tail}</body></html>')
    if plain:
        _GUEST[key] = (time.time(), out)
    return out


# ---------- banner in the app and block on the front page ---------------------------------------------------------

BANNER_CSS = ("<style>.apj-ban{display:flex;align-items:center;justify-content:center;gap:12px;padding:11px 18px;background:#0b1220;"
              "color:#fff!important;text-decoration:none;font-size:15.5px;line-height:1.35}.apj-ban:hover{background:#1f2937}"
              ".apj-ban b{font-weight:750}.apj-ban .t{min-width:0}"
              ".apj-ban .d{flex:none;width:9px;height:9px;border-radius:50%;background:#22c55e;box-shadow:0 0 0 4px rgba(34,197,94,.25)}"
              ".apj-ban .go{flex:none;font-weight:700;white-space:nowrap;background:#fff;color:#0b1220;border-radius:999px;padding:5px 13px;"
              "font-size:13.5px}@media(max-width:700px){.apj-ban{justify-content:flex-start;padding:9px 12px;gap:9px;font-size:13.5px}"
              ".apj-ban .t{flex:1}.apj-ban .x{display:none}.apj-ban .go{padding:4px 10px;font-size:12.5px}.apj-ban .d{width:8px;height:8px}}"
              "@media print{.apj-ban{display:none}}</style>")


def banner_html(user=None, path=""):
    """10.11. (Jure): the big line on top of every app page while Autopilot trades real money; it leads to /autopilot
    and is left out on that page itself. "" otherwise. live_state() is kept 30 s, so this costs nothing per page.
    A page kept by ui/pagecache keeps the line it was built with until it is rebuilt (at most UI_CACHE_STALE_S);
    the owner's switch is a POST, and every POST clears that cache, so switching off takes the line down at once."""
    if path in (PATH, PATH_EN) or not live_state()["live"]:
        return ""
    return (f'{BANNER_CSS}<a class=apj-ban href="{PATH}"><span class=d></span><span class=t><b>Autopilot je live:</b> podacima '
            'alata tradamo pravim novcem. <span class=x>Uđi, pogledaj statistiku i dodaj svoj prijedlog.</span></span>'
            '<span class=go>Pogledaj →</span></a>')


STRIP_CSS = ("<style>.apj-strip{display:flex;align-items:center;gap:18px 28px;flex-wrap:wrap;max-width:1040px;margin:28px auto;"
             "padding:26px 30px;border-radius:26px;background:#0b1220;color:#fff;text-decoration:none;text-align:left}"
             ".apj-strip:hover{background:#111a2e}.apj-strip .a{flex:1;min-width:240px}"
             ".apj-strip .lv{display:inline-flex;align-items:center;gap:8px;font-size:12px;font-weight:750;letter-spacing:.08em;"
             "text-transform:uppercase;color:#86efac;background:rgba(34,197,94,.14);border:1px solid rgba(34,197,94,.35);"
             "border-radius:999px;padding:5px 12px;line-height:1}.apj-strip .lv i{width:8px;height:8px;border-radius:50%;background:#22c55e}"
             ".apj-strip b.h{display:block;font-size:clamp(22px,3.4vw,30px);font-weight:780;letter-spacing:-.03em;line-height:1.15;"
             "margin:12px 0 6px;color:#fff}.apj-strip .s{color:#aab3c5;font-size:16px;line-height:1.45}"
             ".apj-strip .n{display:flex;gap:10px 22px;flex-wrap:wrap;margin-top:14px;font-variant-numeric:tabular-nums}"
             ".apj-strip .n span{color:#aab3c5;font-size:13px}.apj-strip .n b{display:block;color:#fff;font-size:20px;font-weight:750}"
             ".apj-strip .go{flex:none;background:#fff;color:#0b1220;border-radius:999px;padding:13px 24px;font-weight:700;font-size:16px;"
             "white-space:nowrap}@media(max-width:700px){.apj-strip{padding:22px 20px;border-radius:22px;margin:20px auto}"
             ".apj-strip .go{width:100%;text-align:center}}</style>")
STRIP_T = {
    "hr": ("Uživo", "Tradanje pravim sredstvima je live", "Provjeri kako nam ide: adresa novčanika, svaki ulaz i svaki "
           "izlaz su javni.", "u novčaniku", "zatvorenih tradeova", "ukupni rezultat", "Pogledaj uživo →"),
    "en": ("Live", "Real-money trading is live", "See how we are doing: the wallet address, every entry and every exit "
           "are public.", "in the wallet", "closed trades", "total result", "See it live →"),
}


def landing_strip(lang="hr"):
    """10.11. (Jure: "page koji bih istaknuo na naslovnici"): the highlighted block for the public front page with a
    few live numbers, linking to the public Autopilot page. "" while Autopilot is not trading real money."""
    try:
        if not live_state()["live"]:
            return ""
        lang = "en" if lang == "en" else "hr"
        live, head, sub, l_val, l_n, l_pnl, go = STRIP_T[lang]
        s = snapshot()
        nums = []
        if s["eq"].get("value_sol") is not None:
            nums.append(f'<span><b>{s["eq"]["value_sol"]:.3f} SOL</b>{l_val}</span>')
        st = s.get("stats")
        if st and st["mode"] == "live" and st["n"]:
            nums.append(f'<span><b>{st["n"]}</b>{l_n}</span>')
            nums.append(f'<span><b>{st["pnl"]:+.3f} SOL</b>{l_pnl}</span>')
        return (f'{STRIP_CSS}<a class=apj-strip href="{PATH_EN if lang == "en" else PATH}"><span class=a><span class=lv><i></i>{live}</span>'
                f'<b class=h>{head}</b><span class=s>{sub}</span>'
                + (f'<span class=n>{"".join(nums)}</span>' if nums else "") + f'</span><span class=go>{go}</span></a>')
    except Exception as e:  # noqa: BLE001 - the front page must never fail because of this block
        _warn("naslovnica", e)
        return ""
