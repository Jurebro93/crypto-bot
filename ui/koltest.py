"""/kol-test: the separate 7-day KOL test book. Every fresh KOL call gets a $50 demo entry; the page shows how far
tokens move after a call, how fast, how deep they drop first, and what each exit (+20/30/40/50%) would have made."""
import json
import os
import time

from ui.html import note, ago, badge, esc, mins, num, signed, table, tdesc, tlink
from ui.kol import klink

SRC = {"x": "X objava", "tg": "Telegram kanal", "chain": "kupnja KOL novčanika"}


def _cfg():
    from koltest import run
    return run.load_config()


def _pct(x, signed_=True, cls="n"):
    if x is None:
        return ("–", -1e18, cls)
    c = "pos" if x > 0 else "neg" if x < 0 else ""
    return (f'<span class="{c}">{x:+.0%}</span>' if signed_ else f"{x:.0%}", x, cls)


def _share(k, n):
    return (f"{k}/{n} ({k / n:.0%})" if n else "–", (k / n) if n else -1, "n")


def _stat(v, label, kind=""):
    return f"<div class=stat><div class='v {kind}'>{v}</div><div class=l>{esc(label)}</div></div>"


def drop_bots(ps):
    """(real KOL entries, scanner-bot entries). Automated alert accounts on X post every fresh token and counted as
    KOL calls until PR #65 (1.11.); their early entries stay in the book but out of the statistics."""
    try:
        from kol import store as kstore
        bots = set(kstore.bot_handles() or [])
    except Exception:  # noqa: BLE001 - no kol.db / older kol module: nothing to drop
        bots = set()
    real = [p for p in ps if p["caller"] not in bots]
    return real, [p for p in ps if p["caller"] in bots]


def _left(end, now):
    d = end - now
    if d <= 0:
        return "završen"
    return f"{int(d // 86400)} d {int(d % 86400 // 3600)} h"


def page(qs):
    from koltest import book, run, store
    cfg = _cfg()
    now = time.time()
    con = store.ro()
    if con is None:
        return "KOL test", ("<h1>KOL test (7 dana)</h1>" + tdesc(
            "Test se pokreće sam s prvim krugom demo tradinga nakon objave nove verzije. Za par minuta ovdje će biti "
            "prvi ulazi."))
    try:
        start = store.kv_get(con, "start_ts")
        ps = store.rows(con)
        sk = run.skips(con)
        bad = dict(con.execute("SELECT close_reason, COUNT(*) FROM positions WHERE status='skip' GROUP BY close_reason"))
    finally:
        con.close()
    start = int(float(start)) if start else int(now)
    end = start + int(cfg["days"] * 86400)
    ps, bot_ps = drop_bots(ps)
    s = book.summary(ps, cfg)
    lad = ", ".join(f"{int(f * 100)}% na +{lv:.0%}" for lv, f in cfg["ladder"])
    b = ["<h1>KOL test (7 dana)</h1>" + tdesc(
        f"Odvojena demo knjiga, samo za mjerenje: na svaki svjež poziv KOL-a (objava na X-u, Telegram kanal, kupnja "
        f"poznatog KOL novčanika) bot odmah \"kupi\" za ${cfg['size_usd']} i prati cijenu {cfg['track_h']} h. Ne miješa "
        f"se s glavnim demo tradingom i bot iz nje ne uči. Pitanje na koje odgovara: kad uđemo odmah na poziv, koliko "
        f"se token pomakne i možemo li izaći na +20, +30, +40 ili +50%. Poziv koji vidimo kasnije od "
        f"{cfg['max_delay_min']} min ne ulazi (to bi bila tuđa pumpa).")]
    pnl_kind = "pos" if s["pnl"] > 0 else "neg" if s["pnl"] < 0 else ""
    b.append("<div class=grid>" + "".join([
        _stat(_left(end, now), f"do kraja testa (počeo {time.strftime('%d.%m. %H:%M', time.gmtime(start))} UTC)"),
        _stat(f"{s['n']}", f"ulaza, od toga {s['open']} još se prati"),
        _stat(_share(s["hit20"], s["n"])[0], "dosegnulo +20%"),
        _stat(_share(s["hit50"], s["n"])[0], "dosegnulo +50%"),
        _stat(_share(s["never20"], s["n"] - s["open"])[0] if s["n"] - s["open"] > 0 else "–",
              f"završenih nije doseglo +20%; još nisu dosegnuli (prate se): {s.get('pending20', 0)}"),
        _stat(f"{s['med_peak']:+.0%}" if s["med_peak"] is not None else "–", "medijan najvišeg rasta"),
        _stat(mins(s["med_min20"])[0], "medijan vremena do +20%"),
        _stat(f"{s['med_delay']:.0f} s" if s["med_delay"] is not None else "–", "kašnjenje od poziva do ulaza"),
        _stat(f"${s['pnl']:+,.0f}", f"rezultat knjige (uloženo ${s['staked']:,.0f})", pnl_kind),
    ]) + "</div>")

    if bot_ps:
        bs = book.summary(bot_ps, cfg)
        b.append(note(f"Izuzeto iz statistike: {bs['n']} ulaza na objave računa koji nisu KOL-ovi (skener botovi "
                       f"od 1.11., a od 2.11. i hakirani spam računi, prodavači plaćenih grupa i dev-ovi koji zovu "
                       f"vlastite tokene). Njihov rezultat odvojeno: "
                       f"{bs['hit20']} od {bs['n']} doseglo +20%, knjiga ${bs['pnl']:+,.0f}."))
    if not ps:
        b.append(tdesc("Još nema ulaza. Čim neki KOL objavi token ili KOL novčanik kupi, ovdje se pojavi."))

    # levels
    rows = []
    for r in book.levels_table(ps, cfg):
        rows.append([f"+{r['level']:.0%}", _share(r["hit"], r["n"]), mins(r["med_min"]), _pct(r["med_drop"]),
                     _pct(r["q_drop"]), _share(r["stopped_first"], r["n"])])
    b.append("<h2 id=razine>Koliko daleko token ode nakon poziva</h2>" + tdesc(
        "Za svaku razinu rasta od cijene ulaza: koliko ih je stiglo do nje, za koliko vremena, i koliko je cijena prvo "
        "pala prije nego što je stigla (to je pad koji moraš izdržati). \"Najgora četvrtina\" znači: kod svakog "
        f"četvrtog je pad bio barem toliki. Zadnji stupac: koliko bi ih stop na {cfg['stop']:.0%} izbacio prije te razine.")
             + table(["Razina", ("Doseglo", "n"), ("Medijan vremena", "n"), ("Medijan pada prije", "n"),
                      ("Najgora četvrtina pada", "n"), (f"Stop {cfg['stop']:.0%} prije", "n")], rows))

    # exit grid
    rows = []
    for g in book.grid(ps, cfg):
        lab = book.sl_label(g["sl"])
        if not g["n"] and "tek nakon" in lab:   # late stops are recorded only for entries from 2.11. on
            rows.append([f"+{g['tp']:.0%}", lab, ("mjeri se od 2.11.", 0, "mut"), ("–", -1, "n"), ("–", -1, "n"),
                         ("–", -1, "n")])
            continue
        rows.append([f"+{g['tp']:.0%}", lab, num(g["n"]),
                     _share(g["wins"], g["n"]), _pct(g["avg"]), signed(g["usd"], "${:+,.0f}")])
    b.append("<h2 id=izlazi>Što bi koji izlaz zaradio</h2>" + tdesc(
        f"Isti ulazi, različita pravila: prodaj sve na +X% ili na stopu. Uračunat trošak ~{cfg['fee']:.0%} po strani i "
        f"klizanje cijene za ${cfg['size_usd']}. Ako nije stigao ni do cilja ni do stopa, računa se cijena nakon "
        f"{cfg['track_h']} h. Ulazi koji se još prate i nisu odlučeni nisu ubrojeni.")
             + table(["Prodaj na", "Stop", ("Ulaza", "n"), ("U plusu", "n"), ("Prosjek po ulazu", "n"),
                      (f"Ukupno na ${cfg['size_usd']}", "n")], rows))

    # per source
    rows = []
    for src, g in sorted(book.by(ps, "source").items()):
        x = book.summary(g, cfg)
        rows.append([esc(SRC.get(src, src)), num(x["n"]), _share(x["hit20"], x["n"]),
                     _share(x["hit50"], x["n"]), _pct(x["med_peak"]), mins(x["med_min20"]),
                     num(x["med_delay"], "{:.0f} s"), signed(x["pnl"], "${:+,.0f}")])
    b.append("<h2 id=izvori>Po izvoru poziva</h2>" + table(
        ["Izvor", ("Ulaza", "n"), ("+20%", "n"), ("+50%", "n"), ("Medijan vrha", "n"), ("Vrijeme do +20%", "n"),
         ("Kašnjenje", "n"), ("Knjiga", "n")], rows, empty="Još nema ulaza."))

    # per caller
    rows = []
    groups = sorted(book.by(ps, "caller").items(), key=lambda kv: (-len(kv[1]), -sum(p["pnl_usd"] or 0 for p in kv[1])))
    for caller, g in groups:
        x = book.summary(g, cfg)
        rows.append([klink(caller), esc(", ".join(sorted({SRC.get(p["source"], p["source"]) for p in g}))),
                     num(x["n"]), _share(x["hit20"], x["n"]), _share(x["hit50"], x["n"]), _pct(x["med_peak"]),
                     mins(x["med_min20"]), signed(x["pnl"], "${:+,.0f}"), ago(max(p["call_ts"] or 0 for p in g))])
    b.append("<h2 id=kolovi>Po KOL-u</h2>" + tdesc(
        "Svaki KOL, kanal i novčanik zasebno. S manje od 5 ulaza rezultat je više sreća nego pravilo; nakon 7 dana "
        "ovdje se vidi koga vrijedi pratiti.") + table(
        ["Tko", "Izvor", ("Ulaza", "n"), ("+20%", "n"), ("+50%", "n"), ("Medijan vrha", "n"),
         ("Vrijeme do +20%", "n"), ("Knjiga", "n"), "Zadnji poziv"], rows, tid="ktk", empty="Još nema ulaza."))

    # entries
    rows = []
    for p in sorted(ps, key=lambda p: -(p["entry_ts"] or 0))[:300]:
        h = p["hits"]
        stat = (badge("prati se", "good") if p["status"] == "open" else badge("gotovo"))
        rows.append([ago(p["entry_ts"]), tlink(p["token"], p["symbol"]), klink(p["caller"]),
                     esc(SRC.get(p["source"], p["source"])), num((p["entry_ts"] or 0) - (p["call_ts"] or 0), "{:.0f} s"),
                     num(p["entry_mcap"], "${:,.0f}"), _pct(p["peak"]), _pct(p["trough"]),
                     *[mins(h[k][0] / 60) if k in h else ("–", 1e18, "n") for k in ("0.2", "0.5")],
                     _pct(book.final_ret(p)), signed(p["pnl_usd"], "${:+,.2f}"),
                     esc(p["book_reason"] or "") or "–", stat])
    b.append("<h2 id=ulazi>Ulazi</h2>" + tdesc(
        f"Najnoviji prvi. Knjiga prodaje po dijelovima: {lad}; ostatak na stopu {cfg['stop']:.0%} ili nakon "
        f"{cfg['track_h']} h. Vrh i dno su od cijene ulaza; mjeri se svaku minutu prva {cfg['fast_h']} h, onda svakih "
        f"{cfg['slow_every_min']} min.") + table(
        ["Ulaz", "Token", "Tko", "Izvor", ("Kašnjenje", "n"), ("MC na ulazu", "n"), ("Vrh", "n"), ("Dno", "n"),
         ("Do +20%", "n"), ("Do +50%", "n"), ("Sada / na kraju", "n"), ("Knjiga", "n"), "Izlaz", "Stanje"],
        rows, empty="Još nema ulaza."))

    # skipped
    names = {"kasno": "viđen prekasno", "limit po satu": "puno poziva u tom satu", "limit po KOL-u": "isti KOL već "
             f"{cfg['per_caller_day']}× danas", "premala likvidnost": f"likvidnost ispod ${cfg['min_liq']:,}",
             "nema cijene": "DexScreener nema cijenu",
             "lažni pool": "lažni pool (likvidnost veća od cijele vrijednosti tokena)",
             "velik token": f"velik token (MC iznad ${cfg.get('max_mcap', 5e7) / 1e6:,.0f}M, npr. WBTC)"}
    rows = [[esc(SRC.get(src, src)), esc(names.get(r, r)), num(n)] for (src, r), n in sorted(sk.items())]
    rows += [["–", esc(names.get(r, r)), num(n)] for r, n in bad.items() if r]
    b.append("<h2 id=preskoceno>Pozivi bez ulaza</h2>" + tdesc(
        f"Da knjiga ostane pregledna: najviše {', '.join(f'{n} po satu iz izvora {SRC.get(k, k)}' for k, n in cfg['per_hour'].items())}"
        f" i {cfg['per_caller_day']} po istom KOL-u dnevno; kad je limit pun, prednost imaju KOL-ovi s boljom ocjenom. "
        "KOL novčanici kupuju stotine tokena dnevno, pa je ovdje najviše njih.")
             + table(["Izvor", "Razlog", ("Broj", "n")], rows, empty="Nijedan poziv nije preskočen."))

    b.append("<h2 id=trosak>Trošak</h2>" + tdesc(
        "Test ne troši ništa novo: pozive već skupljaju postojeće praćenje X-a, Telegrama i KOL novčanika, a cijene "
        "su s DexScreenera (besplatno). Plaćene opcije ako želimo više: (1) uživo praćenje još 20 KOL-ova na X-u "
        "≈ $2.2 dnevno (~$66 mjesečno, Apify); (2) Solana Tracker KOL API s puno više KOL novčanika ≈ €50 mjesečno; "
        "(3) Birdeye cijene u sekundi umjesto svake minute ≈ $39-99 mjesečno (točnije vrijeme do +20%). "
        "Telegram račun za poruke ispod 1 s je besplatan, ali treba broj mobitela."))
    return "KOL test", "".join(b)


def report_data(now=None):
    """Small dict for the morning e-mail: totals, levels, best exit, last 24 h, top callers."""
    from koltest import book, store
    now = now or time.time()
    con = store.ro()
    if con is None:
        return None
    try:
        cfg = _cfg()
        start = store.kv_get(con, "start_ts")
        ps = store.rows(con)
    except Exception:  # noqa: BLE001 - the report must never fail on this section
        return None
    finally:
        con.close()
    if not start:
        return None
    start = int(float(start))
    end = start + int(cfg["days"] * 86400)
    ps, _ = drop_bots(ps)
    day = [p for p in ps if (p["entry_ts"] or 0) >= now - 86400]
    gr = [g for g in book.grid(ps, cfg) if g["n"] >= 5]
    best = max(gr, key=lambda g: g["avg"]) if gr else None
    callers = []
    for c, g in book.by(ps, "caller").items():
        if len(g) >= 3:
            x = book.summary(g, cfg)
            callers.append({"caller": c, "n": x["n"], "hit20": x["hit20"], "pnl": x["pnl"]})
    callers.sort(key=lambda x: -x["pnl"])
    return {"day_n": int((now - start) // 86400) + 1, "days": cfg["days"], "left": _left(end, now),
            "all": book.summary(ps, cfg), "day": book.summary(day, cfg), "levels": book.levels_table(ps, cfg),
            "best": best, "top": callers[:3], "worst": callers[-2:][::-1] if len(callers) > 3 else [],
            "size": cfg["size_usd"]}
