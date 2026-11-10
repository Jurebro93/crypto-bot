"""Local look at the Autopilot page (/pravi-trade) with small, realistic databases in a temp dir: no network, no keys.

10.11. (Jure: "stranica autopilot mora biti čista, minimalistička"): the page is checked by eye at 390 px and 1280 px
before it ships; this builds what it needs and serves it the way run_ui.py does (ui.html.page around
ui.pravitrade.page, the /pravi-trade/* fragments beside it).

    python3 audit/2026-11-10/seed_apui.py --serve 8765 [--moduli /home/user/wt/novac/trade] [--prazno] [--iskljucen]
    -> http://127.0.0.1:8765/pravi-trade         (owner)
       http://127.0.0.1:8765/pravi-trade?gost=1  (an invited player: looks only)
       http://127.0.0.1:8765/apchart?tema=tamna  (the chart alone, dark; tema=svijetla for light)

What is seeded: trade.db with the equity history of 10 days (3 rebuilt from orders, src='recon', then a snapshot
every 5 min; the opening deposit and two more), open, closed, blocked and failed positions with their orders;
league.db with three follows of the real-trade account and copy_log skips of the demo stage; minute.db with what
the price did after the skips (kol/preskoceni.py skip_path: every verdict of the box under the log's summary line).
--moduli DIR: load trade/equity.py and trade/aplog.py from DIR (read only, no bytecode written) when this checkout
does not have them yet; without them the page shows its fallback (plain balance, the order list). --prazno: no
equity rows (the chart's empty state). Everything that would reach the network or a key is replaced in this
process only: the wallet balance, the SOL/EUR rate, the "armed" check.
"""
import argparse
import importlib.util
import math
import os
import random
import sys
import tempfile
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

sys.dont_write_bytecode = True   # --moduli points into another checkout: never write into it
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OWNER, GUEST = "Jure", "Ivan"
PUB = "9xQeWvG816bUx9EPjHmaT23yvVM2ZWbrrpZb9PusVFin"
DAY = 86400


def _env(d):
    """Every database the page may open, in the temp dir (set before the app's modules read them at import)."""
    for k, name in (("TRADE_DB", "trade.db"), ("LEAGUE_DB", "league.db"), ("KOL_DB", "kol.db"), ("HYPE_DB", "hype.db"),
                    ("TG_DB", "tg.db"), ("TOPCHECK_DB", "topcheck.db"), ("WALLET_DB", "wallets.db"), ("RUG_DB", "rug.db")):
        os.environ[k] = os.path.join(d, name)
    os.environ["DATA_DIR"] = d   # league/copy.WAKE (a follow wakes the copy loop): never the checkout's .copy_wake
    os.environ["TRADE_OWNER"] = OWNER
    os.environ["SOLANA_PUBLIC_KEY"] = PUB
    os.environ.setdefault("AP_BG_REFRESH", "1")


def _load(moduli):
    """trade.equity / trade.aplog from `moduli` when this checkout has none (another group writes them tonight)."""
    import trade
    for name in ("equity", "aplog"):
        if os.path.exists(os.path.join(ROOT, "trade", f"{name}.py")) or not moduli:
            continue
        path = os.path.join(moduli, f"{name}.py")
        if not os.path.exists(path):
            continue
        spec = importlib.util.spec_from_file_location(f"trade.{name}", path)
        mod = importlib.util.module_from_spec(spec)
        sys.modules[f"trade.{name}"] = mod
        spec.loader.exec_module(mod)
        setattr(trade, name, mod)


def _mint(rng):
    abc = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
    return "".join(rng.choice(abc) for _ in range(43)) + "p"


def seed(d, now=None, empty=False, on=True):
    """Fill trade.db and league.db in `d`. Returns {'sol': last free SOL} for the faked wallet balance."""
    from league import copy, store
    from trade import executor, settings
    now = int(now or time.time())
    rng = random.Random(1011)
    tcon = executor.connect(os.environ["TRADE_DB"])
    try:
        from trade import equity
        equity.ensure(tcon)
    except Exception:  # noqa: BLE001 - no module: the contract's table (audit/2026-11-10/dizajn.md, section 1)
        tcon.execute("CREATE TABLE IF NOT EXISTS equity (ts INTEGER PRIMARY KEY, sol REAL, usdc REAL, tokens_sol REAL, "
                     "sol_usd REAL, usd_eur REAL, flow_sol REAL DEFAULT 0, src TEXT DEFAULT 'live')")
    try:
        from trade import aplog
        aplog.ensure(tcon)
    except Exception:  # noqa: BLE001
        pass
    settings.put(tcon, "on", on, OWNER)
    settings.put(tcon, "heartbeat", now - 12, "trade")
    settings.put(tcon, "wallet_pub", PUB, OWNER)
    settings.put(tcon, "invited", [GUEST], OWNER)
    settings.put(tcon, "size_sol", 0.05, OWNER)

    # ---- the equity history: 10 days, deposits at the start, on day 4 and on day 8 ----
    t0 = now - 10 * DAY
    flows = {t0: 1.0, t0 + 4 * DAY + 3 * 3600: 0.5, t0 + 8 * DAY + 7 * 3600: 0.25}
    pts = list(range(t0, t0 + 3 * DAY, 3600)) + list(range(t0 + 3 * DAY, now - 60, 300))
    net, rows, sol_last = 0.0, [], 0.0
    for i, ts in enumerate(pts):
        x = (ts - t0) / DAY
        flow = 0.0
        for fts, amt in flows.items():   # a deposit lands on the first point at or after it
            if fts <= ts and fts > (pts[i - 1] if i else -1):
                flow += amt
        net += flow
        recon = ts < t0 + 3 * DAY
        if recon:   # rebuilt from orders: realised only, moves in steps at sales
            pnl = [0.0, -0.012, -0.031, -0.018, 0.006, 0.021][min(5, int(x * 2))]
        else:
            pnl = (0.02 + 0.05 * math.sin((x - 3) / 1.3) + 0.012 * (x - 3) - 0.045 * math.exp(-((x - 7.6) ** 2) / 0.3)
                   + rng.gauss(0, 0.004))
        sol_usd = 166 + 7 * math.sin(x / 1.7) + rng.gauss(0, 0.6)
        usd_eur = 0.861 + 0.004 * math.sin(x / 3)
        tokens = 0.0 if recon else max(0.0, 0.11 + 0.08 * math.sin(x * 2.3))
        usdc = 4.2 if 5 < x < 7 else 0.0
        value = net + pnl
        sol = value - tokens - usdc / sol_usd
        sol_last = sol
        rows.append((ts, round(sol, 6), usdc, round(tokens, 6), round(sol_usd, 3), round(usd_eur, 5), flow,
                     "recon" if recon else "live"))
    tcon.execute("DELETE FROM equity")
    if not empty:
        tcon.executemany("INSERT INTO equity (ts, sol, usdc, tokens_sol, sol_usd, usd_eur, flow_sol, src) "
                         "VALUES (?,?,?,?,?,?,?,?)", rows)

    # ---- positions and orders: open, closed, blocked by a rule, failed technically ----
    L = 1_000_000_000
    pos = [  # symbol, opened ago (s), status, reason, sol_in, sol_back, source
        ("PNUT2", 50 * 60, "open", None, 0.05, None, "copy KOL ansem"),
        ("GIGA", 3 * 3600, "open", None, 0.05, 0.012, "copy wallet 7xKX…"),
        ("MOODENG", 5 * 3600, "closed", None, 0.05, 0.0712, "copy ekipa murad +1"),
        ("WIF3", 9 * 3600, "closed", None, 0.05, 0.0391, "copy KOL ansem"),
        ("CHILL", 20 * 3600, "closed", None, 0.05, 0.0644, "ručno (pravi trade)"),
        ("RETARDIO", 30 * 3600, "closed", None, 0.05, 0.0473, "copy wallet 7xKX…"),
        ("LATE", 25 * 60, "blocked", "signal star 4 min: kupnja samo dok je poziv svjež (do 180 s)", 0.05, None, "copy KOL ansem"),
        ("NOPROOF", 2 * 3600, "blocked", "praćenje bez dokaza u demu (zatvorenih 3 od 10)", 0.05, None, "copy KOL blknoiz06"),
        ("TINY", 6 * 3600, "blocked", "MC 21k ispod 30k", 0.05, None, "copy ekipa murad +1"),
        ("STUCK", 7 * 3600, "failed", "transakcija nije stigla u blok (Jupiter, Ultra)", 0.05, None, "copy wallet 7xKX…"),
    ]
    tcon.execute("DELETE FROM positions")
    tcon.execute("DELETE FROM orders")
    toks = {}   # symbol -> (mint, decision ts): the skip_path rows below are keyed by them
    for sym, ago_s, status, reason, sin, sback, src in pos:
        tok, ts = _mint(rng), now - ago_s
        toks[sym] = (tok, ts)
        closed_ts = ts + rng.randint(600, 5400) if status == "closed" else None
        q = 1_000_000_000 if status in ("open", "closed") else None
        left = 0 if status == "closed" else (q // 2 if sback else q)
        cur = tcon.execute("INSERT INTO positions (token, symbol, opened_ts, mode, status, reason, sol_in, qty_raw, qty_left, "
                           "sol_back, closed_ts, fees_sol) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                           (tok, sym, ts, "live", status, reason, sin if status in ("open", "closed") else None, q, left,
                            sback, closed_ts, 0.0021 if status in ("open", "closed") else 0))
        pid = cur.lastrowid
        ost = {"open": "ok", "closed": "ok", "blocked": "blocked", "failed": "failed"}[status]
        tcon.execute("INSERT INTO orders (ts, position_id, token, side, mode, amount_in, amount_out, status, reason, error, "
                     "signature, route, fee_lamports) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                     (ts, pid, tok, "buy", "live", int(sin * L), q, ost, src, reason if status == "failed" else None,
                      ("5" + _mint(rng)[:86]) if ost == "ok" else None, "v2", 105_000))
        if sback:
            tcon.execute("INSERT INTO orders (ts, position_id, token, side, mode, amount_in, amount_out, status, reason, "
                         "signature, route, fee_lamports) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                         (closed_ts or ts + 1800, pid, tok, "sell", "live", q, int(sback * L), "ok",
                          "TP +40 %" if sback > sin else "SL -20 %", "4" + _mint(rng)[:86], "v2", 105_000))
    tcon.commit()
    tcon.close()

    # ---- league.db: the follows of the real-trade account and the demo stage's skips ----
    lg = store.connect(os.environ["LEAGUE_DB"])
    copy.ensure(lg)
    lg.execute("INSERT OR IGNORE INTO accounts VALUES (?,?,?)", (settings.LEAGUE_USER, 1e9, now))
    f1 = copy.follow(lg, settings.LEAGUE_USER, "kol", "ansem", "", 25, 5, "tpsl", "15%", "-20%")
    f2 = copy.follow(lg, settings.LEAGUE_USER, "wallet", "7xKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU", "", 25, 5, "mirror")
    f3 = copy.follow(lg, settings.LEAGUE_USER, "ekipa", "murad,tg:alpha_calls", "", 25, 5, "tpsl", "15%", "-20%",
                     max_mcap=1e6, max_runup=0.25)
    lg.execute("DELETE FROM copy_log")
    for ago_s, sym, note, fid in ((12 * 60, "BONK9", "signal star 11 min (vidjeli smo ga tek sada)", f1),
                                  (80 * 60, "PEPE4", "MC nepoznat: bez cijene na DexScreeneru", f1),
                                  (4 * 3600, "SLOP", "likvidnost $6k je samo 1.1% MC-a", f1),
                                  (9 * 3600, "RUGME", "rug filter: lažni pool", f1),
                                  # 10.11. (Jure: the box of skipped buys): enough skips of every kind for "prikaži sve"
                                  (3 * 3600, "MOCHI", "praćenje bez dokaza u demu (zatvorenih 2 od 10)", f3),
                                  (5 * 3600, "ZEUS", "MC 24k ispod 30k", f2),
                                  (8 * 3600, "FROGE", "signal star 6 min (vidjeli smo ga tek sada)", f1),
                                  (11 * 3600, "KITTY", "likvidnost $4k je samo 0.9% MC-a", f3),
                                  (13 * 3600, "NEIRO2", "token je još na pump.fun krivulji: uzimaju se bondani", f1),
                                  (15 * 3600, "DOGEAI", "cijena je već +31 % od poziva (strop +25 %)", f3),
                                  (17 * 3600, "BRETT3", "honeypot: nema rute za prodaju", f2),
                                  (19 * 3600, "POPCAT2", "praćenje bez dokaza u demu (zatvorenih 3 od 10)", f1),
                                  (21 * 3600, "TRUMPX", "MC 18k ispod 30k", f2),
                                  (23 * 3600, "SIGMA", "limit: 5 otvorenih pozicija", f1)):
        tok = _mint(rng)
        toks[sym] = (tok, now - ago_s)
        lg.execute("INSERT INTO copy_log (follow_id, token, side, ev_ts, ts, symbol, action, note, trade_id) "
                   "VALUES (?,?,?,?,?,?,?,?,?)", (fid, tok, "buy", now - ago_s - 30, now - ago_s, sym, "preskočeno", note, None))
    lg.commit()
    lg.close()
    _skip_paths(toks, now)
    return {"sol": sol_last}


# what the price did in the hour after each skip (kol/preskoceni.py): t15 / sl_min = first minute of +15 % / -20 %,
# hi60 / lo60 / r60 = the highest, the lowest and the close after 60 min. LATE and BONK9 are younger than 65 min
# ("mjeri se"), KITTY has no row yet ("čeka mjerenje"), PEPE4 / BRETT3 have no pool / no candle ("nema podataka").
SKIP_PATHS = {   # symbol: (t15, sl_min, hi60, lo60, r60, peak minute) or the bad word
    "PEPE4": "pool", "BRETT3": "svijeca",
    "NOPROOF": (6, None, 0.42, -0.05, 0.18, 23), "MOCHI": (14, 31, 0.23, -0.27, -0.22, 17),
    "SLOP": (None, None, 0.09, -0.14, -0.08, 4), "ZEUS": (None, 7, 0.04, -0.48, -0.35, 2),
    "TINY": (40, 3, 0.20, -0.31, 0.05, 41), "STUCK": (9, None, 0.61, -0.03, 0.33, 38),
    "FROGE": (None, None, 0.11, -0.19, -0.12, 9), "RUGME": (None, 2, 0.01, -0.86, -0.82, 1),
    "NEIRO2": (22, None, 0.17, -0.12, 0.06, 24), "DOGEAI": (None, 44, 0.05, -0.21, -0.18, 3),
    "POPCAT2": (None, None, 0.13, -0.09, 0.02, 31), "TRUMPX": (3, None, 1.05, -0.10, 0.40, 12),
    "SIGMA": (None, 12, 0.06, -0.33, -0.25, 1),
}


def _skip_paths(toks, now):
    from kol import minute, preskoceni
    mcon = minute.connect()
    try:
        preskoceni.ensure(mcon)
        mcon.execute("DELETE FROM skip_path")
        for sym, v in SKIP_PATHS.items():
            tok, ts = toks[sym]
            m = preskoceni.minute_of(ts)
            if isinstance(v, str):
                mcon.execute("INSERT INTO skip_path (token, ts, bad, retry_ts, done_ts) VALUES (?,?,?,?,?)",
                             (tok, m, v, now + 86400, now))
                continue
            t15, sl, hi, lo, r60, peak = v
            mcon.execute("INSERT INTO skip_path (token, ts, pool, entry, lag_s, t15, sl_min, hi60, lo60, r60, max_min, lv, "
                         "done_ts) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                         (tok, m, "POOL" + sym, 0.0001, 30, t15, sl, hi, lo, r60, peak, "{}", now))
        mcon.commit()
    finally:
        mcon.close()


def _fakes(sol):
    """The wallet, the rates and the switch's key check, in this process only."""
    from trade import executor, wallet
    wallet.sol_balance = lambda addr: round(sol, 4)
    wallet.token_raw_balance = lambda owner, mint: 0
    wallet.address = lambda: PUB
    wallet.can_sign = lambda: True
    executor.armed = lambda: True
    try:
        from trade import equity
        equity.rates = lambda now=None: {"sol_usd": 171.24, "usd_eur": 0.8623, "ts": int(time.time())}
    except Exception:  # noqa: BLE001
        pass


def _chart_page(dark):
    """The chart alone, for the light and the dark surface (the public Autopilot page reuses it)."""
    from trade import executor
    from ui import apchart, pravitrade
    tcon = executor.connect(os.environ["TRADE_DB"])
    try:
        eq = pravitrade.equity_data(tcon)
    finally:
        tcon.close()
    bg = "#1a1a19" if dark else "#ffffff"
    return ("<!doctype html><html><head><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>"
            f"<style>body{{margin:0;padding:16px;background:{bg};font:14px/1.45 system-ui,sans-serif}}</style></head>"
            f"<body class='{'apc-dark' if dark else ''}'>"
            + apchart.chart_html(eq["series"], eq["summary"], eq["deposits"], ident="pub")
            + apchart.chart_html(eq["series"][:1], eq["summary"], ident="one", compact=True)
            + apchart.chart_html([], {}, ident="none") + "</body></html>")


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):   # quiet
        pass

    def _send(self, code, body, ctype="text/html; charset=utf-8"):
        b = body.encode("utf-8") if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        from ui import html, pravitrade
        u = urlparse(self.path)
        qs = {k: v[0] for k, v in parse_qs(u.query).items()}
        # the page's fragments carry no query: the invited player's view is told by the page they came from
        user = GUEST if qs.pop("gost", None) or "gost=1" in (self.headers.get("Referer") or "") else OWNER
        frags = {"/pravi-trade/graf": pravitrade.head_fragment, "/pravi-trade/dnevnik": pravitrade.dnevnik_fragment,
                 "/pravi-trade/preporuke": pravitrade.recs_fragment, "/pravi-trade/pozicije": pravitrade.positions_fragment,
                 "/pravi-trade/zovu": pravitrade.callers_fragment, "/pravi-trade/ideje": pravitrade.ideas_fragment,
                 "/pravi-trade/log": pravitrade.log_fragment}
        try:
            if u.path == "/pravi-trade":
                return self._send(200, html.page(*pravitrade.page(qs, user), "/pravi-trade"))
            if u.path in frags:
                frag = frags[u.path](user)
                return self._send(200 if frag is not None else 403, frag or "")
            if u.path == "/pravi-trade/token":
                return self._send(200, "<p class=mut>Lokalni pregled: provjera tokena uživo ide na DexScreener, ovdje je nema.</p>")
            if u.path == "/apchart":
                return self._send(200, _chart_page(qs.get("tema") == "tamna"))
        except Exception as e:  # noqa: BLE001
            import traceback
            traceback.print_exc()
            return self._send(500, f"{type(e).__name__}: {e}", "text/plain; charset=utf-8")
        return self._send(404, "nema", "text/plain; charset=utf-8")

    def do_POST(self):
        self.send_response(303)
        self.send_header("Location", "/pravi-trade?err=lokalni%20pregled%2C%20ni%C5%A1ta%20se%20ne%20sprema")
        self.end_headers()


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--serve", type=int, default=0, help="port; 0 = only build the databases and print the dir")
    ap.add_argument("--dir", default="", help="where to build (default: a new temp dir)")
    ap.add_argument("--moduli", default="", help="folder with equity.py and aplog.py when this checkout lacks them")
    ap.add_argument("--prazno", action="store_true", help="no equity history (the chart's empty state)")
    ap.add_argument("--iskljucen", action="store_true", help="the Autopilot switched off")
    a = ap.parse_args()
    d = a.dir or tempfile.mkdtemp(prefix="apui-")
    os.makedirs(d, exist_ok=True)
    _env(d)
    sys.path.insert(0, ROOT)
    _load(a.moduli)
    info = seed(d, empty=a.prazno, on=not a.iskljucen)
    print(f"baze: {d}", flush=True)
    if not a.serve:
        return
    _fakes(info["sol"])
    srv = ThreadingHTTPServer(("127.0.0.1", a.serve), H)
    print(f"http://127.0.0.1:{a.serve}/pravi-trade", flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
