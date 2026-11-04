"""SimianX parts of /dugorocno: the "SimianX" column of the three lists and the section with the latest opinions,
the demo test of its long signals and whether they may trade real money (owner's switch on /pravi-trade)."""
import json
import time

from ui.html import ago, badge, esc, num, signed, table, tlink, usd

VIEW = {"long": ("kupi (long)", "good"), "short": ("pada (short)", "warn"), "wait": ("čekaj", "")}


def load():
    """-> (latest opinion per mint, instruments per mint, con or None). Never raises: an empty db is fine."""
    try:
        from simianx import store
        con = store.ro()
        if con is None:
            return {}, {}, None
        ops = store.latest(con)
        ins = {r["mint"]: r for r in con.execute("SELECT * FROM instruments")}
        return ops, ins, con
    except Exception:  # noqa: BLE001 - the page must render without SimianX
        return {}, {}, None


def cell(ops, ins, mint):
    o = ops.get(mint)
    if o is not None:
        label, kind = VIEW.get(o["view"], VIEW["wait"])
        conf = f" {o['confidence']:.0%}" if o["confidence"] is not None else ""
        return (f'<span title="{esc(_says(o))}">{badge(label + conf, kind)}</span>', o["confidence"] or 0, "")
    i = ins.get(mint)
    if i is not None and not i["ok"]:
        return (f'<span class=mut title="{esc(i["note"] or "")}">nije pokriven</span>', -1, "")
    return ("–", -2, "")


def _says(o):
    try:
        s = json.loads(o["says"] or "{}")
    except ValueError:
        s = {}
    parts = [s.get(k) for k in ("indicator", "intelligence", "fundamental", "decision") if s.get(k)]
    return " · ".join(parts) or (o["reason"] or "")


def _pct(x):
    return signed(None if x is None else 100 * x, "{:+.0f}%")


def section(con, ops, ins):
    if con is None:
        return ("<h2 id=simianx>SimianX: drugo mišljenje</h2><div class=empty>SimianX još nije uključen: treba ključ "
                "SIMIANX_API_KEY na Renderu. Do tada ovaj dio ostaje prazan.</div>")
    b = ["<h2 id=simianx>SimianX: drugo mišljenje</h2>",
         "<p class=mut>SimianX AI (vanjski alat, Free plan) za tokene s ovih popisa koji su i na burzama OKX/Bybit "
         "pusti svoja četiri AI analitičara na dnevni graf: graf, vijesti, fundamenti i odluka. Bot ga pita svakih "
         "nekoliko sati, najviše ~15 bodova dnevno (0 $). Mišljenje vrijedi za burzovni par istog tokena; tokene s "
         "istim tickerom a drugom cijenom bot preskače. Analiza, ne savjet za ulaganje.</p>"]
    blocked = [i for i in ins.values() if not i["ok"] and "Free plan" in (i["note"] or "")]
    if blocked:
        b.append("<p>" + badge("Free plan ne pokriva ove tokene", "warn") + " SimianX na Free planu vraća prazan odgovor "
                 f"za tokene s našeg popisa ({esc(', '.join(i['symbol'] for i in blocked[:8]))}). Za prava mišljenja "
                 "treba plaćeni plan (Starter $7/mj); dok ga nema, bot ih ponovno proba jednom tjedno.</p>")
    rows = []
    for m, o in sorted(ops.items(), key=lambda kv: -kv[1]["ts"]):
        label, kind = VIEW.get(o["view"], VIEW["wait"])
        try:
            s = json.loads(o["says"] or "{}")
        except ValueError:
            s = {}
        rows.append([tlink(m, o["symbol"]), badge(label, kind), num(None if o["confidence"] is None else 100 * o["confidence"], "{:.0f}%"),
                     ago(o["ts"]), esc(s.get("indicator") or ""), esc(s.get("intelligence") or ""),
                     esc(s.get("fundamental") or ""), esc((o["reason"] or "")[:300])])
    b.append(table(["Token", "SimianX mišljenje", "Sigurnost", "Kada", "Graf", "Vijesti", "Fundamenti", "Obrazloženje"],
                   rows, tid="sxop", empty="Prva mišljenja stižu nakon prvog prolaza (svakih 3 h)."))

    brows, inv, tot, tot_sol, n_closed, wins = [], 0.0, 0.0, 0.0, 0, 0
    last = {m: o["dex_price"] for m, o in ops.items()}
    for r in con.execute("SELECT * FROM book ORDER BY exit_ts IS NOT NULL, entry_ts DESC").fetchall():
        px = r["exit_price"] if r["exit_ts"] else last.get(r["mint"])
        ret = px / r["entry_price"] - 1 if px and r["entry_price"] else None
        sret = (r["sol_exit"] / r["sol_entry"] - 1) if r["exit_ts"] and r["sol_exit"] and r["sol_entry"] else None
        if ret is not None:
            inv += r["usd"]
            tot += r["usd"] * ret
            tot_sol += r["usd"] * (sret or 0)
        if r["exit_ts"]:
            n_closed += 1
            wins += 1 if (ret or 0) > 0 else 0
        brows.append([tlink(r["mint"], r["symbol"]), (time.strftime("%d.%m.", time.gmtime(r["entry_ts"])), r["entry_ts"], ""),
                      usd(r["usd"]), _pct(r["stop_pct"]), _pct(r["target_pct"]), _pct(ret), _pct(sret),
                      esc(r["reason"]) if r["exit_ts"] else badge("otvoreno", "good")])
    b.append("<h3>Demo test SimianX signala (bez pravog novca)</h3><p class=mut>Svaki SimianX \"kupi\" postane demo "
             "pozicija od $100 na Solana cijeni, sa SimianX stopom i ciljem preračunatim u postotke; zatvara se na "
             "stopu, cilju, nakon 14 dana ili kad SimianX okrene mišljenje. Cilj: 2 tjedna usporedbe s našim demo "
             "portfeljem gore i s držanjem SOL-a prije nego što ga pustiš na pravi novac."
             + (f" Do sada: {tot:+,.0f} $ na {inv:,.0f} $ uloženih, zatvoreno {n_closed}, u plusu {wins}." if inv else "")
             + "</p>")
    b.append(table(["Token", "Ulaz", "Uloženo", "SimianX stop", "SimianX cilj", "Rezultat", "SOL u isto vrijeme", "Stanje"],
                   brows, tid="sxbook", empty="Još nijedan SimianX \"kupi\" signal."))
    try:
        from trade import settings
        on = settings.simianx_on()
    except Exception:  # noqa: BLE001
        on = False
    b.append("<p>" + (badge("Pravi novac: UKLJUČENO", "warn") + " Vlasnik je na stranici Autopilot odobrio da SimianX "
                      "\"kupi\" signali otvaraju i prave kupnje, unutar tamošnjih limita." if on else
                      badge("Pravi novac: isključeno", "") + " SimianX signali idu samo u demo test. Uključuje ih "
                      "samo vlasnik, kvačicom na stranici <a href=/pravi-trade>Autopilot</a>.") + "</p>")
    return "".join(b)
