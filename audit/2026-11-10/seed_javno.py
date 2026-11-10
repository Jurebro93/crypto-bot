"""Local preview of the public Autopilot page (ui/apjavno.py) with made-up but realistic data. Nothing here touches the
real databases, the network or a wallet: two temporary SQLite files are filled and the dashboard is served from them.

    cd /home/user/wt/javno && python3 audit/2026-11-10/seed_javno.py                 # http://127.0.0.1:8765/autopilot
    python3 audit/2026-11-10/seed_javno.py --probno                                  # the same in trial mode (no real money)
    python3 audit/2026-11-10/seed_javno.py --port 9000 --dir /tmp/moj-prikaz
    python3 audit/2026-11-10/seed_javno.py --moduli /home/user/wt/novac /home/user/wt/apui   # the other groups' real modules

Log in at /prijava as Ivan (lozinka: demo-ivan-123), Panda (demo-panda-123) or the owner Jure (demo-jure-123).
"Live" is simulated only inside this process (executor.armed is replaced here); no key or env switch is involved.

The modules of the other groups (trade/equity.py, trade/aplog.py, ui/apchart.py) are used when they exist in the tree.
--moduli DIR... loads them from other checkouts (DIR/trade/equity.py, ...) into THIS PROCESS ONLY, so the preview shows
the real chart and the real decision log before the branches are merged; nothing is copied into this tree.
While one is still missing, a small stand-in defined below is put in its place FOR THIS PREVIEW ONLY, so the page shows
every section: equity and aplog follow the contract in audit/2026-11-10/dizajn.md; the chart has no stand-in, the page
then shows its own plain fallback line.
"""
import argparse
import importlib.util
import os
import random
import sqlite3
import sys
import tempfile
import time
import types

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
WALLET = ("DemoWa11etMemeSonarAutopi1ot" + "1" * 44)[:44]      # clearly not a real wallet
TOKENS = [("BONK", "DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263"), ("WIF", "EKpQGSJtjMFqKZ9KQanSqYXRcF8fBopzLHYxdM65zcjm"),
          ("POPCAT", "7GCihgDB8fe6KNjn2MYtkzZcRjQy3t9GHdC8uHYmW2hr"), ("MEW", "MEW1gQWJ3nEXg2qgERiKu7FAFj79PHvQVREQUzScPP5"),
          ("PNUT", "2qEHjDLDLbuBgRYvsxhc5D6uDWAivNFZGan56P1tpump"), ("GOAT", "CzLSujWBLFsSjncfkh59rUFqvafWcY5tzedWJSuypump"),
          ("FARTCOIN", "9BB6NFEcjBCtnNLFko2FqVQBq8HHM13kCyYcdQbgpump"), ("MOODENG", "ED5nyyWEzpPPiWimP8vYm7sD7TD3LAt3Q3gRTWHzPJBY")]
KOLS = ["memeLovac", "dnevni_gem", "sol_snajper"]
WALLETS = [(("Kit12" + "x" * 44)[:44].replace("x", "7"), "Kit 12"), (("Rani" + "y" * 44)[:44].replace("y", "9"), "Rani kupac")]
CHAT = [
    ("Ivan", 30 * 3600, "Prijedlog: neka Autopilot ne ulazi u token koji je u zadnjih sat vremena već narastao više od 50 %. "
                        "Tada obično kupimo vrh.", ["Panda", "Jure", "Marko", "Luka"]),
    ("Panda", 26 * 3600, "Može li se na stranici vidjeti i koliko je prosječno trajao jedan trade? Zanima me drži li bot "
                         "minute ili sate.", ["Ivan", "Marko"]),
    ("Marko", 21 * 3600, "Meni se sviđa što je adresa javna. Provjerio sam dvije kupnje na Solscanu i brojke se slažu.",
     ["Ivan", "Panda", "Jure"]),
    ("Luka", 9 * 3600, "Stop na -20 % mi se čini preširok za tokene ispod 100k market capa.\nMožda -12 % za male, -20 % za veće?",
     ["Ivan"]),
    ("Jure", 6 * 3600, "Hvala na prijedlozima. Pravilo za tokene koji su već jako narasli ide u probu ovaj tjedan, javim "
                       "ovdje kako je prošlo.", ["Ivan", "Panda", "Marko", "Luka"]),
    ("Panda", 95 * 60, "Bilo bi dobro označiti koji je influencer donio najviše dobitnih ulaza, ne samo ukupni rezultat.", ["Luka"]),
    ("Ivan", 12 * 60, "Današnji ulaz u WIF je bio brz, 40 sekundi nakon poziva. Svaka čast.", []),
]


def sig(rnd):
    return "".join(rnd.choice(B58) for _ in range(88))


def seed_trade(path, now, live, rnd):
    from trade import executor, settings
    con = executor.connect(path)
    con.execute("CREATE TABLE IF NOT EXISTS equity (ts INTEGER PRIMARY KEY, sol REAL, usdc REAL, tokens_sol REAL, sol_usd REAL, "
                "usd_eur REAL, flow_sol REAL DEFAULT 0, src TEXT DEFAULT 'live')")
    mode = "live" if live else "dry"
    start = now - 6 * 86400
    settings.put(con, "on", bool(live), "Jure")
    con.execute("UPDATE settings SET ts=? WHERE k='on'", (int(start),))
    settings.put(con, "wallet_pub", WALLET, "Jure")
    settings.put(con, "auto_pick", True, "Jure")
    settings.put(con, "auto_follows", [1, 4], "alat")      # the tool added follow 1 (influencer) and 4 (wallet) itself
    settings.put(con, "auto_log", [{"ts": int(start + 3600), "op": "+", "kind": "kol", "target": KOLS[0],
                                    "why": "minutna provjera: +10 % prije stopa u 62 %"}], "alat")
    # closed and open positions, each buy and sell with its order row
    results = [0.021, -0.018, 0.034, 0.009, -0.021, 0.015, 0.027, -0.012, 0.041, -0.019, 0.012, 0.018, -0.006, 0.023]
    cash, events = 2.0, []     # events: (ts, change of SOL in the wallet, change of SOL held in tokens)
    for i, res in enumerate(results):
        sym, mint = TOKENS[i % len(TOKENS)]
        opened = int(start + 5400 + i * (5.2 * 86400 / len(results)))
        closed = opened + rnd.randint(8, 55) * 60
        fees = 0.0006
        back = 0.1 + res + fees
        src = f"KOL {KOLS[i % 3]}" if i % 4 else f"wallet {WALLETS[i % 2][1]}"   # as league/copy.py writes it
        cur = con.execute("INSERT INTO positions (token, symbol, opened_ts, mode, status, reason, sol_in, qty_raw, qty_left, "
                          "sol_back, closed_ts, fees_sol) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                          (mint, sym, opened, mode, "closed", f"copy {src}", 0.1, 10 ** 9, 0, back, closed, fees))
        pid = cur.lastrowid
        for ts, side, why in ((opened, "buy", f"copy {src}"), (closed, "sell", "TP +15 %" if res > 0 else "SL -20 %")):
            con.execute("INSERT INTO orders (ts, position_id, token, side, mode, amount_in, amount_out, status, reason, signature, "
                        "route, fee_lamports) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                        (ts, pid, mint, side, mode, int(0.1e9), int(back * 1e9), "ok" if live else "dry", why,
                         sig(rnd) if live else None, "v2", 300_000))
        events += [(opened, -0.1, 0.1), (closed, back - fees, -0.1)]
    for j, (sym, mint) in enumerate(TOKENS[1:3]):      # two positions still open
        opened = int(now - (50 + 70 * j) * 60)
        cur = con.execute("INSERT INTO positions (token, symbol, opened_ts, mode, status, reason, sol_in, qty_raw, qty_left, "
                          "sol_back, fees_sol) VALUES (?,?,?,?,?,?,?,?,?,0,0.0003)",
                          (mint, sym, opened, mode, "open", f"copy KOL {KOLS[j]}", 0.1, 10 ** 9, 10 ** 9))
        con.execute("INSERT INTO orders (ts, position_id, token, side, mode, amount_in, amount_out, status, reason, signature, "
                    "route, fee_lamports) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                    (opened, cur.lastrowid, mint, "buy", mode, int(0.1e9), 10 ** 9, "ok" if live else "dry",
                     f"copy KOL {KOLS[j]}", sig(rnd) if live else None, "v2", 300_000))
        events.append((opened, -0.1, 0.1))
    # signals the rules refused, and one technical failure whose raw text must never reach the public page
    skips = ["signal star 412 s (granica 180 s)", "MC 21 400 $ ispod 30k", "praćenje bez dokaza u demu "
             "(6 zatvorenih, treba 10+)", "likvidnost 2 900 $ ispod 5 000 $", "signal star 233 s (granica 180 s)",
             "praćenje bez dokaza u demu (3 zatvorenih, treba 10+)", "dnevni limit: potrošeno 0.500 od 0.5 SOL"]
    for k, why in enumerate(skips):
        sym, mint = TOKENS[(k + 3) % len(TOKENS)]
        con.execute("INSERT INTO positions (token, symbol, opened_ts, mode, status, reason) VALUES (?,?,?,?,?,?)",
                    (mint, sym, int(now - (k + 1) * 2.6 * 3600), mode, "blocked", why))
    con.execute("INSERT INTO orders (ts, token, side, mode, status, error, route) VALUES (?,?,?,?,?,?,?)",
                (int(now - 7 * 3600), TOKENS[5][1], "buy", mode, "failed",
                 "HTTPError 429 https://rpc.primjer.invalid/?api-key=OVO-SE-NE-SMIJE-VIDJETI", "v2"))
    # wallet value every 5 minutes: 2 SOL paid in at the start, 1 SOL more on the fourth day
    events.sort()
    tokens, t, e, first = 0.0, int(start), 0, True
    top_up = int(start + 3.1 * 86400)
    while t <= now:
        flow = 0.0
        if first:
            flow, first = 2.0, False
        elif t <= top_up < t + 300:
            flow, cash = 1.0, cash + 1.0
        while e < len(events) and events[e][0] <= t:
            cash, tokens, e = cash + events[e][1], tokens + events[e][2], e + 1
        drift = 1 + 0.06 * rnd.uniform(-1, 1) if tokens > 1e-9 else 1
        sol_usd = 152.4 + 6 * rnd.uniform(-1, 1) + (t - start) / 86400 * 0.9
        con.execute("INSERT OR REPLACE INTO equity VALUES (?,?,?,?,?,?,?,?)",
                    (t, round(cash, 6), 0.0, round(max(tokens, 0) * drift, 6), round(sol_usd, 2), 0.921, flow, "live"))
        t += 300
    con.commit()
    con.close()


def seed_league(path, now):
    from league import copy, store
    from trade import settings
    from ui import apjavno
    con = store.connect(path)
    copy.ensure(con)
    apjavno.ensure(con)
    user = settings.LEAGUE_USER
    rows = [("kol", KOLS[0], "", "tpsl", "15%", "-20%", 5.5), ("kol", KOLS[1], "", "podaci", "", "", 4.2),
            ("kol", KOLS[2], "", "tpsl", "20%", "-15%", 2.0), ("wallet", WALLETS[0][0], WALLETS[0][1], "mirror", "", "", 5.5),
            ("wallet", WALLETS[1][0], WALLETS[1][1], "mirror", "", "", 1.3),
            ("ekipa", f"tg:gem_kanal, {KOLS[1]}", "", "tpsl", "15%", "-20%", 0.6)]
    for kind, target, label, mode, tp, sl, days in rows:
        fid = copy.follow(con, user, kind, target, label, 25, 5, mode, tp, sl)
        con.execute("UPDATE follows SET created=? WHERE id=?", (int(now - days * 86400), fid))
    # the demo copy stage's own skips (trade.aplog reads them for the follows of the real-money account)
    fids = [r[0] for r in con.execute("SELECT id FROM follows WHERE user=? ORDER BY id", (user,))]
    notes = ["poziv je star 9 min (granica 3 min)", "MC 18 400 $ ispod 30k", "likvidnost 2 100 $ ispod 3 % MC-a",
             "poziv je star 5 min (granica 3 min)", "token još na krivulji: uzimaju se bondani"]
    for k, note in enumerate(notes):
        sym, mint = TOKENS[(k + 2) % len(TOKENS)]
        con.execute("INSERT OR REPLACE INTO copy_log (follow_id, token, side, ev_ts, ts, symbol, action, note) "
                    "VALUES (?,?,?,?,?,?,?,?)", (fids[k % len(fids)], mint, "buy", int(now - (k + 1) * 3.3 * 3600),
                                                 int(now - (k + 1) * 3.3 * 3600), sym, "preskočeno", note))
    for who, age, text, voters in CHAT:
        cur = con.execute("INSERT INTO ap_chat (ts, user, text) VALUES (?,?,?)", (int(now - age), who, text))
        for v in voters:
            con.execute("INSERT INTO ap_chat_votes (msg_id, user, ts) VALUES (?,?,?)", (cur.lastrowid, v, int(now - age + 600)))
    con.commit()
    con.close()


# ---------- stand-ins for modules of the other groups, used ONLY while the real one is not in the tree ----------------

def _standin_equity():
    m = types.ModuleType("trade.equity")
    m.__doc__ = "PREVIEW STAND-IN (audit/2026-11-10/seed_javno.py), not the real trade/equity.py"

    def series(con, since=None, max_points=600):
        rows = con.execute("SELECT ts, sol, usdc, tokens_sol, sol_usd, usd_eur, flow_sol, src FROM equity WHERE ts>=? ORDER BY ts",
                           (since or 0,)).fetchall()
        out, net = [], 0.0
        for ts, sol, usdc, tok, px, eur, flow, src in rows:
            net += flow or 0
            v = sol + tok + (usdc / px if px else 0)
            out.append({"ts": ts, "sol": sol, "usdc": usdc, "tokens_sol": tok, "value_sol": v, "value_usd": v * px,
                        "value_eur": v * px * eur, "sol_usd": px, "usd_eur": eur, "flow_sol": flow, "net_in_sol": net,
                        "pnl_sol": v - net, "src": src})
        step = max(1, len(out) // max_points)
        return out[::step] + ([out[-1]] if out and (len(out) - 1) % step else [])

    def summary(con, now=None):
        s = series(con, max_points=10 ** 9)
        if not s:
            return {}
        last, first = s[-1], s[0]
        day = [p for p in s if p["ts"] <= last["ts"] - 86400]
        return {**{k: last[k] for k in ("value_sol", "value_usd", "value_eur", "sol", "usdc", "tokens_sol", "net_in_sol",
                                        "pnl_sol", "sol_usd", "usd_eur")},
                "pnl_pct": 100 * last["pnl_sol"] / last["net_in_sol"] if last["net_in_sol"] else None,
                "pnl_24h_sol": last["pnl_sol"] - day[-1]["pnl_sol"] if day else None,
                "first_ts": first["ts"], "last_ts": last["ts"], "n": len(s)}

    def deposits(con):
        return [{"ts": ts, "sol": f} for ts, f in con.execute("SELECT ts, flow_sol FROM equity WHERE flow_sol != 0 ORDER BY ts")]
    m.series, m.summary, m.deposits, m.EVERY_S = series, summary, deposits, 300
    return m


def _standin_aplog():
    m = types.ModuleType("trade.aplog")
    m.__doc__ = "PREVIEW STAND-IN (audit/2026-11-10/seed_javno.py), not the real trade/aplog.py"
    m.KINDS = ("kupio", "prodao", "preskocio", "nije_proslo")

    def why_short(text):
        t = (text or "").lower()
        for key, group in (("signal star", "signal star"), ("market cap", "MC ispod 30k"), ("dokaz u demu", "bez dokaza u demu"),
                           ("likvidnost", "likvidnost"), ("limit", "limit"), ("tp ", "cilj dosegnut"), ("sl ", "stop"),
                           ("copy ", "")):
            if key in t:
                return group
        return "tehnika"

    def entries(tcon, lcon=None, limit=80, since=None):
        out = []
        for ts, tok, sym, side, mode, status, ain, aout, err, why, sg, sin, sback, fees in tcon.execute(
                "SELECT o.ts, o.token, p.symbol, o.side, o.mode, o.status, o.amount_in, o.amount_out, o.error, o.reason, "
                "o.signature, p.sol_in, p.sol_back, p.fees_sol FROM orders o LEFT JOIN positions p ON p.id=o.position_id "
                "WHERE o.ts>=? ORDER BY o.id DESC LIMIT ?", (since or 0, limit)):
            failed = status == "failed"
            kind = "nije_proslo" if failed else ("kupio" if side == "buy" else "prodao")
            text = err if failed else why
            pnl = (100 * ((sback or 0) - (sin or 0) - (fees or 0)) / sin) if kind == "prodao" and sin else None
            out.append({"ts": ts, "kind": kind, "token": tok, "symbol": sym, "source": (why or "").replace("copy ", "")
                        if kind == "kupio" else "", "why": text, "why_short": why_short(text),
                        "sol": (ain if side == "buy" else aout or 0) / 1e9 if not failed else None, "pnl_pct": pnl,
                        "mode": mode, "stage": "pravi", "sig": sg, "trebao": True if failed else None, "side": side})
        for ts, tok, sym, mode, why in tcon.execute("SELECT opened_ts, token, symbol, mode, reason FROM positions WHERE "
                                                    "status='blocked' AND opened_ts>=? ORDER BY id DESC LIMIT ?", (since or 0, limit)):
            out.append({"ts": ts, "kind": "preskocio", "token": tok, "symbol": sym, "source": "", "why": why,
                        "why_short": why_short(why), "sol": None, "pnl_pct": None, "mode": mode, "stage": "pravi",
                        "sig": None, "trebao": False, "side": "buy"})
        out.sort(key=lambda r: r["ts"], reverse=True)
        return out[:limit]

    def summary(rows, now=None):
        now = now or time.time()
        day = [r for r in rows if r["ts"] >= now - 86400]
        out = {k: sum(1 for r in day if r["kind"] == k) for k in m.KINDS}
        why = {}
        for r in day:
            if r["kind"] == "preskocio":
                why[r["why_short"]] = why.get(r["why_short"], 0) + 1
        out["signali"] = out["kupio"] + out["preskocio"] + out["nije_proslo"]
        out["razlozi"] = sorted(why.items(), key=lambda kv: -kv[1])
        return out
    m.why_short, m.entries, m.summary = why_short, entries, summary
    return m


def load_real(dirs):
    """The other groups' real modules from their checkouts, for this process only. Returns what was loaded."""
    out = []
    for name in ("trade.equity", "trade.aplog", "ui.apchart"):
        if importlib.util.find_spec(name) is not None:
            continue   # already in this tree (after the merge): that one wins
        rel = os.path.join(*name.split(".")) + ".py"
        for d in dirs or ():
            fp = os.path.join(d, rel)
            if os.path.isfile(fp):
                spec = importlib.util.spec_from_file_location(name, fp)
                mod = importlib.util.module_from_spec(spec)
                sys.modules[name] = mod
                spec.loader.exec_module(mod)
                setattr(sys.modules[name.split(".")[0]], name.split(".")[1], mod)
                out.append(f"{name} iz {d}")
                break
    return out


def install_standins():
    used = []
    for name, make in (("trade.equity", _standin_equity), ("trade.aplog", _standin_aplog)):
        if name in sys.modules:
            continue
        if importlib.util.find_spec(name) is None:
            mod = make()
            sys.modules[name] = mod
            setattr(sys.modules[name.split(".")[0]], name.split(".")[1], mod)
            used.append(name)
    if importlib.util.find_spec("ui.apchart") is None:
        used.append("ui.apchart (bez zamjene: stranica crta svoju običnu liniju)")
    return used


def strip_preview(d):
    """The front-page block on its own, as the front page would hold it (the web group inserts the call there)."""
    from ui import apjavno, landing
    out = []
    for lang in ("hr", "en"):
        fp = os.path.join(d, f"naslovnica-blok-{lang}.html")
        with open(fp, "w", encoding="utf-8") as f:
            f.write(f"<!doctype html><html lang={lang}><meta charset=utf-8><meta name=viewport content='width=device-width,"
                    f"initial-scale=1'><style>{landing.CSS}</style><body><div class=w style='padding-top:24px'>"
                    f"{apjavno.landing_strip(lang) or '<p>(Autopilot nije uživo: blok se ne prikazuje)</p>'}</div></body></html>")
        out.append(fp)
    return out


def main(argv=None):
    p = argparse.ArgumentParser(description="Lokalni prikaz javne stranice Autopilota s izmišljenim podacima.")
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--dir", help="mapa za privremene baze (zadano: nova privremena mapa)")
    p.add_argument("--probno", action="store_true", help="probni rad: Autopilot nije uživo, bez trake i bloka na naslovnici")
    p.add_argument("--samo-baze", action="store_true", help="napuni baze i izađi, bez poslužitelja")
    p.add_argument("--moduli", nargs="*", default=[], help="checkouti drugih grupa s trade/equity.py, trade/aplog.py, "
                   "ui/apchart.py (samo za ovaj prikaz)")
    a = p.parse_args(argv)
    d = a.dir or tempfile.mkdtemp(prefix="javno-")
    os.makedirs(d, exist_ok=True)
    for name in ("trade.db", "league.db"):
        if os.path.exists(os.path.join(d, name)):
            os.remove(os.path.join(d, name))
    os.environ.update(TRADE_DB=os.path.join(d, "trade.db"), LEAGUE_DB=os.path.join(d, "league.db"), DATA_DIR=d,
                      UI_USERS="Ivan,Panda,Jure", UI_PASS_IVAN="demo-ivan-123", UI_PASS_PANDA="demo-panda-123",
                      UI_PASS_JURE="demo-jure-123", TRADE_OWNER="Jure", LEAGUE_AUTO_SELL="0", I18N_OFF="1")
    for k in ("SITE_URL", "APP_URL", "UI_PASSWORD", "ANTHROPIC_API_KEY", "TRADE_LIVE"):
        os.environ.pop(k, None)
    sys.path.insert(0, ROOT)
    now, live, rnd = time.time(), not a.probno, random.Random(7)
    import trade  # noqa: F401
    import ui  # noqa: F401
    real = load_real(a.moduli)
    seed_trade(os.environ["TRADE_DB"], now, live, rnd)
    seed_league(os.environ["LEAGUE_DB"], now)
    used = install_standins()
    if "trade.aplog" in sys.modules and hasattr(sys.modules["trade.aplog"], "ensure"):
        from trade import executor
        con = executor.connect(os.environ["TRADE_DB"])
        sys.modules["trade.aplog"].ensure(con)   # its indexes (after the merge executor.connect adds them itself)
        con.commit()
        con.close()
    if live:
        from trade import executor
        executor.armed = lambda: True     # this process only: "the key and the env switch are there"; nothing can be signed
    print(f"baze: {d}")
    if real:
        print("pravi moduli drugih grupa (samo ovaj proces): " + ", ".join(real))
    if used:
        print("zamjene samo za ovaj prikaz (pravi modul još nije u stablu): " + ", ".join(used))
    if a.samo_baze:
        return
    import run_ui
    for fp in strip_preview(d):
        print(f"blok za naslovnicu: file://{fp}")
    srv = run_ui.ThreadingHTTPServer(("127.0.0.1", a.port), run_ui.Handler)
    srv.verbose = False
    print(f"{'UŽIVO (simulirano)' if live else 'PROBNI RAD'}: http://127.0.0.1:{a.port}/autopilot   prijava: Ivan / demo-ivan-123, "
          "Jure / demo-jure-123   (Ctrl+C za kraj)", flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
