"""Autopilot uklonjen (27.11., vlasnik: "Ugasi Autopilot, ne treba nam praćenje uživo. Radije više učiti nego trgovati
uživo i osvježavati iste tokene. Autopilot prestaje trošiti ikakve resurse, uklanja se potpuno."). Ranije iste večeri:
"demo trade-ovi rade u pozadini", i stalno pravilo "demo nikad ne staje" (CLAUDE.md 23.11.).

ONE switch, env AUTOPILOT_OFF (default "1" = the Autopilot is gone; "0" = exactly the old behaviour). The code stays in
the repository behind it; what it does while on:

  stopped    run_ui.py: the live sampler of the skipped buys (ui/pravitrade.skip_sampler_loop, every 5 s); the hourly
             auto pick of whom the real account follows (ui/autopilot.maybe_sync) and SimianX on the real account
             (league/simianx_feed) in league/auto.loop; the public /autopilot pages (410), their chat and live parts,
             the menu item, the landing block, the start page's Autopilot rows, the sitemap entry; the terminal of
             /pravi-trade (SSE stream, 1-5 s fragments) -> a minimal owner page; Grok autotrade BUYS (its sells stay:
             they only close open positions). run_trade.py: the wallet snapshots every 5 min (trade/equity), the
             Jupiter Trigger probe, the paper mirror and the cost measurement.
  slower     league/auto.fast_loop (TP/SL of the demo accounts + exit plans, range, oscilator, veliki, momentum):
             every DEMO_EXIT_S (30 s) from the shared price cache instead of every second; REAL_EXIT_S (15 s) while
             trade.db still has an OPEN real position (its existing stops / targets), back to 30 s by itself when
             none is left. run_trade.py: one pass every TRADE_POLL_S (15 s) instead of every second, at once when an
             exit or an owner's button rings trade/wake. The owner's DCA / buy orders every DCA_S (15 s).
  kept       demo accounts, the researcher, the shadow book, kopija_demo, insajderi demo, the wallet measurement,
             copy trading of the players (league/auto.loop every 20 s), the owner's manual buy and sell buttons,
             "Prodaj sve", the kill switch (trade/STOP, checked first by every buy), the caps (never changed here).
Nothing here sells, buys or changes a cap or a switch.
"""
import os
import sqlite3
import time

ENV = "AUTOPILOT_OFF"
DEMO_EXIT_S = float(os.environ.get("AUTOPILOT_OFF_DEMO_EXIT_S", "30"))
REAL_EXIT_S = float(os.environ.get("AUTOPILOT_OFF_REAL_EXIT_S", "15"))
TRADE_POLL_S = float(os.environ.get("AUTOPILOT_OFF_TRADE_POLL_S", "15"))
DCA_S = float(os.environ.get("AUTOPILOT_OFF_DCA_S", "15"))
OPEN_TTL_S = 30   # the count of open real positions is asked at most this often
_OPEN = {"ts": 0.0, "n": None}

GONE_HR = ("Autopilot je uklonjen",
           "Autopilot više ne postoji: ne trgujemo automatski pravim novcem i ne objavljujemo rezultate bota. "
           "MemeSonar mjeri novčanike i tokene u demo načinu, da bi učio.")
GONE_EN = ("Autopilot has been removed",
           "The Autopilot no longer exists: there is no automatic real-money trading and no bot results to show. "
           "MemeSonar measures wallets and tokens in demo mode, to learn.")


def on():
    """True while the Autopilot is removed (env AUTOPILOT_OFF unset or anything but 0/no/off)."""
    return (os.environ.get(ENV) or "1").strip().lower() not in ("0", "no", "off", "false")


def open_real(path=None):
    """Open (or half-booked pending) REAL positions in trade.db; None when it cannot be read (the caller then keeps
    the watcher, never the other way round). Read-only, never raises."""
    if path is None:
        try:
            from trade import settings
            path = settings.DB
        except Exception:  # noqa: BLE001
            return None
    if not os.path.exists(path):
        return 0
    try:
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5)
        try:
            return int(con.execute("SELECT COUNT(*) FROM positions WHERE mode='live' AND status IN ('open','pending')")
                       .fetchone()[0])
        finally:
            con.close()
    except sqlite3.OperationalError as e:
        if "no such table" in str(e):
            return 0
        return None
    except sqlite3.Error:
        return None


def open_real_cached(now=None, path=None):
    now = now or time.time()
    if path is not None or now - _OPEN["ts"] >= OPEN_TTL_S:
        _OPEN["n"], _OPEN["ts"] = open_real(path), now
    return _OPEN["n"]


def exit_every(now=None, path=None):
    """(seconds, open real positions or None) for league/auto.fast_loop while the Autopilot is removed: REAL_EXIT_S
    while an open real position exists (or the count is unknown), else DEMO_EXIT_S."""
    n = open_real_cached(now, path)
    return (REAL_EXIT_S if n is None or n > 0 else DEMO_EXIT_S), n


def gone_html(lang="hr"):
    """The simple page every removed Autopilot address answers with (410)."""
    h, p = GONE_EN if lang == "en" else GONE_HR
    home = "/" if lang == "en" else "/hr"
    back = "Back to MemeSonar" if lang == "en" else "Natrag na MemeSonar"
    return ("<!doctype html><html lang=" + ("en" if lang == "en" else "hr") + "><meta charset=utf-8>"
            "<meta name=viewport content='width=device-width,initial-scale=1'><meta name=robots content=noindex>"
            f"<title>{h}</title><body style='font:16px/1.5 system-ui,sans-serif;max-width:640px;margin:48px auto;"
            f"padding:0 16px;background:#fff;color:#111'><h1 style='font-size:24px'>{h}</h1><p>{p}</p>"
            f"<p><a href='{home}'>{back}</a></p></body></html>")
