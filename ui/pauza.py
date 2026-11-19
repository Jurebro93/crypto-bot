"""The public notice "Autopilot is paused" (19.11., vlasnik: "On the web page write a message that Autopilot is
currently paused because of a change in strategy and that users will be notified when it continues").

Driven by state, never hard-coded: the real-money pause is the trade.db settings key "pravi_novac_pauza" with JSON
{"on": true, ...} (written by the owner's pause; trade/settings.pauza(con) in its own branch). This module reads it
itself, read-only, and never raises: no trade.db, no settings table, no key, an unreadable value = not paused (no
notice). The answer is kept TTL_S (60 s) per process, so the public pages do not open trade.db on every request.
When the owner turns real money back on the key becomes {"on": false} and the notice disappears by itself within
TTL_S (+ the page's own copy: /autopilot GUEST_TTL_S 10 s; the landing page is built on every request).

The notice is one block of the same family as the influencer / Telegram notice (ops/drustveni: class soc-note).
Public text only: no balance, no switch name, no env name, no address, no cost.
"""
import json
import os
import sqlite3
import threading
import time

KEY = "pravi_novac_pauza"
TTL_S = 60
TEXT = {
    "hr": ("Autopilot je trenutno pauziran zbog promjene strategije. Sve resurse usmjerili smo na pronalaženje "
           "novčanika koji kupuju prije rasta. Korisnike ćemo obavijestiti kada se Autopilot nastavi."),
    "en": ("Autopilot is currently paused while we change the strategy. All resources now go to finding wallets that "
           "buy before a rise. We will notify users when Autopilot resumes."),
}
# 19.11. (vlasnik: "while real money is off, do as many demo trades as possible with wallet following"): one sentence
# under the notice on the public /autopilot page, as state-driven as the notice
DEMO = {"hr": "U međuvremenu testiramo praćenje novčanika na demo računu.",
        "en": "Meanwhile we are testing wallet following on a demo account."}
_lock = threading.Lock()
_CACHE = {"ts": 0.0, "val": False}


def _db():
    try:
        from trade import settings
        return settings.DB
    except Exception:  # noqa: BLE001
        return os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "trade.db")


def read(path=None):
    """True when the key says {"on": true}. Read-only; never raises (anything missing or odd = False)."""
    p = path or _db()
    try:
        if not p or not os.path.exists(p):
            return False
        con = sqlite3.connect(f"file:{p}?mode=ro", uri=True, timeout=3)
        try:
            row = con.execute("SELECT v FROM settings WHERE k = ?", (KEY,)).fetchone()
        finally:
            con.close()
        if not row:
            return False
        v = json.loads(row[0]) if isinstance(row[0], (str, bytes)) else row[0]
        return bool(isinstance(v, dict) and v.get("on") is True)
    except Exception:  # noqa: BLE001 - a public page never fails on this
        return False


def on(now=None):
    """The pause, kept TTL_S per process."""
    t = time.time() if now is None else float(now)
    with _lock:
        if _CACHE["ts"] and 0 <= t - _CACHE["ts"] < TTL_S:
            return _CACHE["val"]
    v = read()
    with _lock:
        _CACHE.update(ts=t, val=v)
    return v


def reset():
    with _lock:
        _CACHE.update(ts=0.0, val=False)


def notice_html(lang="hr", notr=True):
    """The block (escaped), or "" while Autopilot is not paused. notr=False on the /autopilot page, which is Croatian
    and translated on the way out by ui/i18n (the sentences are in ui/i18n_en.json)."""
    if not on():
        return ""
    from ops import drustveni
    return drustveni.block_html(TEXT["en" if lang == "en" else "hr"], cls="ap-pauza", style=drustveni.PUBLIC_STYLE,
                                notr=notr)


def demo_html(lang="hr", notr=True):
    """The extra sentence under the notice, or "" while Autopilot is not paused."""
    if not on():
        return ""
    from html import escape
    t = DEMO["en" if lang == "en" else "hr"]
    return f'<p class="ms-hint ap-pauza-demo"{" translate=no" if notr else ""} style="margin:-12px 0 18px">{escape(t)}</p>'
