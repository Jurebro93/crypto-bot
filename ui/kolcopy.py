"""/kol-kopiranje: the KOL copy replay (kolcopy/). Would a follower who buys seconds after a KOL wallet and sells
seconds after it sells have made money, net of costs? Per delay and exit, the out-of-sample test, and per wallet."""
import time

from ui.html import ago, esc, num, table, tdesc, wlink

EXIT_LABEL = {"mirror": "kad KOL proda", "h1": "nakon 1 h", "h6": "nakon 6 h", "h24": "nakon 24 h"}
VERDICT_KIND = {"u plusu": "pos", "u minusu": "neg"}


def _pct(x):
    if x is None:
        return ("–", -1e18, "n")
    c = "pos" if x > 0 else "neg" if x < 0 else ""
    return (f'<span class="{c}">{x:+.1%}</span>', x, "n")


def _ci(s):
    if not s or s["lo"] is None:
        return ("–", -1e18, "n")
    return (f"{s['lo']:+.1%} do {s['hi']:+.1%}", s["lo"], "n")


def _delay(d):
    return "KOL sam" if d == 0 else f"{d} s" if d < 60 else f"{d // 60} min"


def _stat(v, label, kind=""):
    return f"<div class=stat><div class='v {kind}'>{v}</div><div class=l>{esc(label)}</div></div>"


def _names():
    try:
        from kol import store as kstore
        con = kstore.ro()
    except Exception:  # noqa: BLE001 - no kol.db: addresses only
        return {}
    if con is None:
        return {}
    try:
        return {w: (tw or nm) for w, nm, tw in con.execute("SELECT wallet, name, twitter FROM kol_ids")}
    except Exception:  # noqa: BLE001
        return {}
    finally:
        con.close()


def page(qs):
    from kolcopy import replay, stats, store
    cfg = replay.load_config()
    try:
        delay = int(qs.get("k", cfg["verdict_delay_s"]))
    except (TypeError, ValueError):
        delay = cfg["verdict_delay_s"]
    if delay not in cfg["delays_s"]:
        delay = cfg["verdict_delay_s"]
    now = time.time()
    h = ["<h1>Kopiranje KOL novčanika</h1>" + tdesc(
        "Samo mjerenje, bez novca: za svaku kupnju praćenog KOL novčanika (Helius javlja u sekundama) gledamo što bi "
        "zaradio netko tko kupi isti token nekoliko sekundi kasnije i proda nekoliko sekundi nakon što KOL proda. "
        "Cijene su stvarni swapovi tokena s lanca, ne svijeće. Od svakog trejda oduzet je trošak "
        f"{replay.cost(cfg):.1%} (kupnja i prodaja {cfg['round_trip_pct']:.1f}% plus priority fee "
        f"{cfg['tip_sol']} SOL po transakciji na ulog {cfg['stake_sol']} SOL). Ako KOL proda prije našeg ulaza, "
        "kopija se ne računa (vidjeli bismo prodaju prije kupnje). chain_trades bilježi da je KOL prodao, ne koliko: "
        "prva prodaja vrijedi kao cijeli izlaz.")]
    con = store.ro()
    if con is None:
        return "KOL kopiranje", "".join(h) + tdesc(
            "Replay još nije pokrenut. Pokreće se sam svakih 30 minuta nakon objave nove verzije; prve točke "
            f"(cijena {cfg['lag_s'] // 60} min nakon kupnje) bit će ovdje nakon prvog prolaza.")
    try:
        evs = stats.load(con)
        last = store.kv_get(con, "last_run")
        day = time.strftime("%Y-%m-%d", time.gmtime(now))
        spent = float(store.kv_get(con, f"credits:{day}", 0) or 0)
    finally:
        con.close()
    rs = stats.rets(evs, cfg, now)
    done = sum(e["status"] == "done" for e in evs)
    wallets = len({e["wallet"] for e in evs})
    tab, skips = stats.by_delay(rs, cfg)
    main = tab.get((delay, "mirror"))
    v = stats.verdict(main, cfg["min_n_verdict"])
    h.append("<div class=grid>" + "".join([
        _stat(f"{len(evs)}", f"kupnji KOL novčanika, {done} potpuno izmjereno"),
        _stat(f"{wallets}", "različitih novčanika"),
        _stat(v, f"presuda uz kašnjenje {_delay(delay)}, izlaz kad KOL proda", VERDICT_KIND.get(v, "")),
        _stat(stats.fmt_pct(main["mean"]) if main else "–", "prosjek po trejdu (neto)"),
        _stat(f"{main['win']:.0%}" if main else "–", "trejdova u plusu"),
        _stat(f"{spent:,.0f}", f"Helius kredita danas (strop {cfg['credits_per_day']:,})"),
        _stat(ago(int(float(last)))[0] if last else "–", "zadnji prolaz"),
    ]) + "</div>")
    if not rs:
        h.append(tdesc("Još nema izmjerenih kupnji. Webhook mora biti postavljen (stranica Telegram i novčanici "
                       "pokazuje KOL novčanike na lancu)."))

    rows = []
    for d in [0] + list(cfg["delays_s"]):
        for x in stats.EXITS:
            s = tab.get((d, x))
            if not s:
                continue
            vv = stats.verdict(s, cfg["min_n_verdict"]) if d else "referenca"
            rows.append([esc(_delay(d)), esc(EXIT_LABEL[x]), num(s["n"]), _pct(s["mean"]), _pct(s["median"]),
                         (f"{s['win']:.0%}", s["win"], "n"), _pct(s["trim"]), _ci(s),
                         num(skips.get((d, x)) or None), f'<span class="{VERDICT_KIND.get(vv, "")}">{esc(vv)}</span>'])
    h.append("<h2 id=kasnjenje>Rezultat po kašnjenju</h2>" + tdesc(
        "Svaki red: kupimo toliko nakon KOL-a i izađemo kad on proda (ili na fiksni sat). \"KOL sam\" je njegova "
        "vlastita cijena, za usporedbu: razlika do ostalih redova je cijena našeg kašnjenja. \"Bez najboljih 1%\" "
        "pokazuje ovisi li rezultat o par sretnih trejdova. Presuda: u plusu ili u minusu tek kad cijeli 90% raspon "
        f"prosjeka ostane na jednoj strani nule i ima barem {cfg['min_n_verdict']} trejdova.")
             + table(["Kašnjenje", "Izlaz", ("Trejdova", "n"), ("Prosjek", "n"), ("Medijan", "n"), ("U plusu", "n"),
                      ("Bez najboljih 1%", "n"), ("90% raspon prosjeka", "n"), ("KOL prodao prije ulaza", "n"),
                      "Presuda"], rows, empty="Još nema trejdova s poznatim izlazom."))

    links = " · ".join(f'<a href="?k={d}">{_delay(d)}</a>' if d != delay else f"<b>{_delay(d)}</b>"
                       for d in cfg["delays_s"])
    o = stats.oos(rs, cfg, delay)
    h.append(f"<h2 id=unaprijed>Možemo li unaprijed izabrati dobre KOL-ove?</h2><p>Kašnjenje: {links}</p>" + tdesc(
        "Ovo je pravi test. Podatke dijelimo na stariju i noviju polovicu. Na starijoj biramo novčanike s barem "
        f"{(cfg.get('oos') or {}).get('min_first', 3)} kopiranja i prosjekom iznad nule (najviše "
        f"{(cfg.get('oos') or {}).get('top', 10)} najboljih), pa gledamo kako su prošli na novijoj, koju pri izboru "
        "nismo vidjeli. Ako su izabrani i dalje bolji od svih, odabir radi; ako padnu na prosjek, bila je sreća."))
    if o:
        orows = []
        for k, label in (("picked_first", "Izabrani, starija polovica (na kojoj smo birali)"),
                         ("picked_second", "Izabrani, novija polovica (test)"), ("all_second", "Svi, novija polovica")):
            s = o[k]
            orows.append([esc(label), num(s["n"] if s else None), _pct(s["mean"] if s else None),
                          _pct(s["median"] if s else None), (f"{s['win']:.0%}", s["win"], "n") if s else "–", _ci(s)])
        h.append(table(["Skupina", ("Trejdova", "n"), ("Prosjek", "n"), ("Medijan", "n"), ("U plusu", "n"),
                        ("90% raspon prosjeka", "n")], orows)
                 + f"<p class=mut>Podjela: {time.strftime('%d.%m. %H:%M', time.gmtime(o['split']))} UTC, "
                   f"izabrano {len(o['picked'])} novčanika.</p>")
    else:
        h.append(tdesc("Premalo trejdova s poznatim izlazom za ovu provjeru (treba barem 10)."))

    names = _names()
    pw = stats.per_wallet(rs, cfg, delay)
    wrows = []
    for w, s in sorted(pw.items(), key=lambda x: (x[1]["n"] >= 3, x[1]["mean"]), reverse=True):
        wrows.append([wlink(w), esc(names.get(w) or ""), num(s["n"]), _pct(s["mean"]), _pct(s["median"]),
                      (f"{s['win']:.0%}", s["win"], "n"), num(s["hold_min"], "{:.0f} min")])
    h.append(f"<h2 id=novcanici>Po novčaniku (kašnjenje {_delay(delay)}, izlaz kad KOL proda)</h2>" + tdesc(
        "Novčanici s barem 3 kopiranja su gore. Prosjek s malo trejdova je sreća ili peh, ne vještina: gledaj stupac "
        "Trejdova. \"KOL drži\" je medijan vremena od njegove kupnje do prve prodaje; što je kraće, to manje "
        "ostaje nama nakon kašnjenja.")
             + table(["Novčanik", "Ime", ("Trejdova", "n"), ("Prosjek", "n"), ("Medijan", "n"), ("U plusu", "n"),
                      ("KOL drži", "n")], wrows, empty="Još nema novčanika s poznatim izlazom."))
    return "KOL kopiranje", "".join(h)
