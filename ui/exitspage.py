"""The "Izlazi" page: which exit rules each token class uses now, why, and how they did on history and live."""
import datetime as dt
import time

from ui import data
from ui.html import badge, esc, klasab, num, table, tdesc

_CACHE = {}


def _pct(x):
    return (f"{x:+.0%}" if isinstance(x, (int, float)) else "–", x if isinstance(x, (int, float)) else -9, "n")


def _share(x):
    return (f"{x:.0%}" if isinstance(x, (int, float)) else "–", x if isinstance(x, (int, float)) else -1, "n")


def _compare():
    """Per entry type: base rules (paper/config.json) vs. what the class uses now. Cached 10 min (replays ~2k paths)."""
    if _CACHE.get("ts", 0) > time.time() - 600:
        return _CACHE["rows"], _CACHE["kol"]
    from exits import learn, paths, profiles
    from paper import sim
    ecfg, base, state = learn.load_config(), sim.load_config(), profiles.load()
    ps = paths.load_seed() + paths.from_paper(data.PAPER_DB, data.HYPE_DB, since=time.time() - ecfg["live_days"] * 86400)
    lam, cap = ecfg["lambda_loss"], ecfg.get("ret_cap", 10)
    by = {}
    for p in ps:
        by.setdefault(p.get("entry") or "live", []).append(p)
    rows = []
    for name, sub in sorted(by.items()):
        k = max({p["klasa"] for p in sub}, key=lambda c: sum(p["klasa"] == c for p in sub))
        a = learn.evaluate(sub, learn.to_sim(base, learn.params_of(base)), lam, cap)
        b = learn.evaluate(sub, learn.to_sim(base, profiles.current(state, k, base)[0]), lam, cap)
        rows.append((name, k, a, b))
    sess = []
    for s, a_h, b_h in paths.SESSIONS:
        sub = [p for p in ps if paths.session_of(p["ts"]) == s]
        if not sub:
            continue
        rets = []
        for p in sub:  # each path with the rules its class+session would get now
            cfg = learn.to_sim(base, profiles.current(state, p["klasa"], base, s)[0])
            rets.append(learn.replay_path(p, cfg)["ret"])
        n = len(rets)
        sess.append({"s": s, "hours": f"{a_h:02d}-{b_h:02d} UTC", "n": n, "win": sum(r > 0 for r in rets) / n,
                     "mean": sum(rets) / n, "median": sorted(rets)[n // 2],
                     "own": sorted(k for k in state.get("profiles", {}) if k.endswith("/" + s))})
    _CACHE["sess"] = sess
    with_kol = [p for p in ps if p.get("kol")]
    kol = None
    if with_kol:
        rest = [p for p in ps if not p.get("kol")]
        pk = lambda xs, m: sum(paths.peak(p) >= m for p in xs) / len(xs) if xs else None  # noqa: E731
        kol = {"n": len(with_kol), "n_rest": len(rest), "x2": pk(with_kol, 2), "x10": pk(with_kol, 10),
               "x2_rest": pk(rest, 2), "x10_rest": pk(rest, 10)}
    _CACHE.update(ts=time.time(), rows=rows, kol=kol)
    return rows, kol


def _live_by_session():
    """session -> (closed paper trades, share in profit), by the hour the trade was opened."""
    import os
    import sqlite3
    from exits import paths
    if not os.path.exists(data.PAPER_DB):
        return {}
    try:
        con = sqlite3.connect(f"file:{data.PAPER_DB}?mode=ro", uri=True, timeout=10)
        rows = con.execute("SELECT opened_ts, ret FROM trades WHERE status='closed'").fetchall()
        con.close()
    except sqlite3.OperationalError:
        return {}
    out = {}
    for ts, ret in rows:
        s = paths.session_of(ts)
        n, w = out.get(s, (0, 0))
        out[s] = (n + 1, w + ((ret or 0) > 0))
    return {s: (n, w / n) for s, (n, w) in out.items()}


ENTRY = {"krivulja_10k": "na krivulji, prvi put $10k mcap", "krivulja_20k": "na krivulji, prvi put $20k mcap",
         "krivulja_40k": "na krivulji, prvi put $40k mcap", "graduacija": "u trenutku graduacije",
         "100k": "prvi put $100k mcap nakon graduacije", "live": "naši stvarni kandidati iz demo tradinga"}


def _note(n):
    import re
    n = str(n or "")
    m = re.match(r"premalo putanja \((\d+) < (\d+)\)", n)
    return f"premalo putanja ({m.group(1)} od potrebnih {m.group(2)})" if m else n


def page(qs):
    from exits import learn, profiles
    from paper import sim
    ecfg, base, state = learn.load_config(), sim.load_config(), profiles.load()
    b = ["<h1>Izlazi</h1><p class=mut>Kada prodati, naučeno iz povijesnih putanja cijena. Svaki skup pravila "
         "odigra se nad tisućama stvarnih putanja (retrospektiva pump.fun tokena + svaki token koji je naš bot pratio), "
         "s naknadom i slippageom, kroz isti kod koji trguje. Ocjena = prosječni povrat po tradeu minus "
         f"{ecfg['lambda_loss']:g}× prosječni gubitak (gubitak boli više od jednakog dobitka), a jedan trade se broji najviše "
         f"do +{ecfg.get('ret_cap', 10):.0%} da jedan 600x ne odredi pravila. Novi skup se primjenjuje sam, samo ako: ima barem "
         f"{ecfg['min_paths']} putanja, bolji je i na starijoj i na novijoj polovici podataka (i na našim live putanjama kad ih "
         f"je barem {ecfg['min_live_check']}), zadržava barem {ecfg.get('moon_keep', 0.8):.0%} ishoda na tokenima koji su "
         f"napravili 10x+, a svako pravilo se pomakne najviše {ecfg['max_steps']} koraka dnevno. Ako live tradeovi s novim "
         "pravilima prođu lošije nego što bi prošla prethodna, sam se vraća na prethodna.</p>"]
    if not ecfg.get("enabled"):
        b.append("<div class=card>" + badge("isključeno", "bad") + " Učenje izlaza je isključeno; svi demo trejdovi "
                 "koriste osnovna pravila.</div>")

    prof = state.get("profiles", {})
    rows = []
    for k in sorted(set(prof) | {"default"}):
        p = prof.get(k)
        params = p["params"] if p else learn.params_of(base)
        ev = (p or {}).get("eval") or {}
        rows.append([klasab(k) if k != "default" else badge("sve klase"),
                     f"v{p['v']} · {dt.datetime.fromtimestamp(p['ts']):%d.%m. %H:%M}" if p else badge("osnovna"),
                     esc(learn.describe(params)), num(ev.get("n")), _pct(ev.get("mean")), _pct(ev.get("median")),
                     _share(ev.get("win")), (f"{ev['moon_mult']:.1f}x" if ev.get("moon_mult") else "–", ev.get("moon_mult") or 0, "n")])
    b.append("<h2>Pravila koja se koriste sada</h2>" + tdesc(
        "Novi demo trade dobije pravila svoje klase (ako klasa nema svoja, \"sve klase\"); trade zadržava pravila s kojima je "
        "otvoren. Moonbag = mali ostatak koji ostaje nakon što je ulog vraćen i čeka moonshot sa širokim trailingom.")
             + table(["Klasa", "Verzija", "Pravila", ("Putanja", "n"), ("Prosjek", "n"), ("Medijan", "n"), ("U plusu", "n"),
                      ("Na 10x+ tokenima", "n")], rows))

    try:
        cmp_rows, kol = _compare()
    except Exception as e:
        cmp_rows, kol = [], None
        print(f"izlazi: usporedba nije uspjela: {type(e).__name__}: {e}")
        b.append("<div class=card>Usporedba se trenutno ne može izračunati; pokušat će ponovno pri sljedećem osvježavanju.</div>")
    if cmp_rows:
        b.append("<h2>Osnovna vs. naučena pravila, po točki ulaza</h2>" + tdesc(
            "Ista putanja, dva skupa pravila. Izlazi ne mogu popraviti loš ulaz: kod graduacije 81% tokena padne 30%+ u prvom "
            "satu, a povijesni podaci nakon graduacije imaju rupe do ~1 h, pa se stop tamo izvrši kasno (pesimistično). "
            "Live putanje (svaka minuta) to s vremenom zamjenjuju.")
                 + table(["Ulaz", "Klasa", ("Putanja", "n"), ("Osnovna: prosjek", "n"), ("medijan", "n"), ("u plusu", "n"),
                          ("Naučena: prosjek", "n"), ("medijan", "n"), ("u plusu", "n"), ("gubitak 30%+", "n")],
                         [[esc(ENTRY.get(n, n)), klasab(k), num(a["n"]), _pct(a["mean"]), _pct(a["median"]), _share(a["win"]),
                           _pct(c["mean"]), _pct(c["median"]), _share(c["win"]), _share(c["big_loss"])]
                          for n, k, a, c in cmp_rows]))
    sess = _CACHE.get("sess") or []
    live_sess = _live_by_session()
    if sess:
        HRS = {"asia": "Azija/Kina", "eu": "Europa", "us": "SAD"}
        b.append("<h2>Po trading sesiji</h2>" + tdesc(
            "Sesija po satu ulaza (UTC): Azija 00-08, Europa 08-14, SAD 14-24. Ako sesija unutar klase ima dovoljno putanja i "
            "njezina pravila prođu iste zaštite, dobije vlastita pravila (npr. moonshot/us); inače vrijede pravila klase. "
            "\"Demo tradeovi\" su stvarni zatvoreni paper tradeovi otvoreni u toj sesiji, da se vidi točnost uživo.")
                 + table(["Sesija", "Sati", ("Putanja", "n"), ("U plusu", "n"), ("Prosjek", "n"), ("Medijan", "n"),
                          "Vlastita pravila", ("Demo tradeova", "n"), ("Demo u plusu", "n")],
                         [[esc(HRS.get(x["s"], x["s"])), x["hours"], num(x["n"]), _share(x["win"]), _pct(x["mean"]),
                           _pct(x["median"]), esc(", ".join(x["own"]) or "ne (pravila klase)"),
                           num(live_sess.get(x["s"], (0, None))[0]), _share(live_sess.get(x["s"], (0, None))[1])]
                          for x in sess]))
    if kol:
        b.append("<h2>Influenceri i izlaz</h2>" + tdesc(
            "Tokeni na koje je bio call influencera (X) za vrijeme putanje, iz povijesti KOL-ova. Pravilo \"KOL hold\" nakon calla "
            "ne izlazi zbog mirovanja i širi trailing; koliko dugo, uči se kao i ostala pravila.")
                 + table(["", ("Putanja", "n"), ("Dosegne 2x", "n"), ("Dosegne 10x", "n")],
                         [["s callom", num(kol["n"]), _share(kol["x2"]), _share(kol["x10"])],
                          ["bez calla", num(kol["n_rest"]), _share(kol["x2_rest"]), _share(kol["x10_rest"])]]))
    runs = state.get("runs", [])[-10:]
    if runs:
        b.append("<h2>Zadnja učenja</h2>" + table(["Kada", "Klasa", ("Putanja", "n"), ("Live", "n"), "Odluka", "Zašto"], [
            [f"{dt.datetime.fromtimestamp(r['ts']):%d.%m. %H:%M}", klasab(i["klasa"]) if i["klasa"] != "default" else "sve",
             num(i.get("n")), num(i.get("n_live")),
             badge("primijenjeno", "good") if i.get("applied") else badge("vraćeno na staro", "bad") if i.get("rollback") else badge("bez promjene"),
             esc(_note(i.get("note")))] for r in reversed(runs) for i in r["items"]]))
    else:
        b.append("<div class=card>Učenje još nije pokrenuto; bot ga radi sam jednom dnevno u "
                 f"{esc(ecfg['run_at_utc'])} UTC.</div>")
    return "Izlazi", "".join(b)
