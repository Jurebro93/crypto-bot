"""The box on top of a list page that says what to do with it (Nicholas 4.11.: "users want to make money, not read
numbers"): three concrete picks with the reason, a confidence that grows with the data, what the demo copies of
that wallet actually earned, and the one action. Everything here is derived from numbers the pages already show
(wallets.db stats, strat.db copies), so the box and the table can never disagree."""
from ui.html import esc, wlink

MIN_CLOSED, MIN_COPY = 10, 50
CAP_HOLD_MIN = 6 * 60     # a wallet that holds for days is not copyable with the bot's exits


def confidence(s):
    """('visoka'|'srednja'|'niska', why): how much the closed-trade history can be trusted."""
    n, d = s.get("closed") or 0, s.get("last_trade_days")
    stale = d is not None and d > 3
    if n >= 30 and not stale and (s.get("top_trade_share") or 1) <= 0.5:
        return "visoka", f"{n} zatvorenih, dobitak nije jedan sretan trade"
    if n >= 15 and not stale:
        return "srednja", f"{n} zatvorenih"
    return "niska", f"{n} zatvorenih" + ("; neaktivan" if stale else "")


def _hold(m):
    return "–" if m is None else f"{m:.0f} min" if m < 90 else f"{m / 60:.1f} h" if m < 48 * 60 else f"{m / 1440:.0f} d"


def rank_wallets(ws, copies=None):
    """[(wallet row, reasons dict)] best first: only wallets that pass the copy list, ordered by confidence tier,
    then copy score, then closed PnL. copies: {wallet prefix (6 chars): (n, mean return, pnl $)} from the demo
    strategy that copied them (strat/run.wallet_rank)."""
    from ui import explain
    copies = copies or {}
    out = []
    for w in ws:
        s = w.get("stats") or {}
        ok, _why = explain.shortlist(w, MIN_COPY, MIN_CLOSED)
        if not ok or (s.get("closed_pnl_sol") or 0) <= 0:
            continue
        if (s.get("median_hold_min") or 0) > CAP_HOLD_MIN:
            continue
        tier, twhy = confidence(s)
        c = copies.get(w["wallet"][:6])
        out.append((w, {"tier": tier, "tier_why": twhy, "copy": c}))
    order = {"visoka": 0, "srednja": 1, "niska": 2}
    out.sort(key=lambda r: (order[r[1]["tier"]], -(r[0].get("copy_score") or 0), -(r[0]["stats"].get("closed_pnl_sol") or 0)))
    return out


def _sentence(w, r):
    s = w["stats"]
    d = s.get("last_trade_days")
    active = "danas" if d is not None and d < 1 else f"prije {d:.0f} d" if d is not None else "–"
    per = (s.get("closed_pnl_sol") or 0) / max(1, s.get("closed") or 1)
    txt = (f"Zaradio {s.get('closed_pnl_sol', 0):+.1f} SOL na {s.get('closed', 0)} zatvorenih tradeova "
           f"(prosječno {per:+.2f} SOL po tradeu, {(s.get('win_rate') or 0):.0%} dobitnih). Drži ~{_hold(s.get('median_hold_min'))}, "
           f"zadnji trade {active}.")
    if r["copy"]:
        n, mean, pnl = r["copy"]
        txt += (f" Kad je naš demo bot kupio isto što i on ({n}×, s našim izlazima), ispalo je {mean:+.0%} po tradeu, "
                f"ukupno {pnl:+,.0f} $ — to je jedini stvarni test kopiranja.")
    else:
        txt += " Demo bot ga još nije kopirao, pa za kopiranje imamo samo njegovu povijest, ne i naš rezultat."
    return txt


def _verdict(ranked):
    """'Što bih ja napravio': one decision in plain words, from the same numbers."""
    if not ranked:
        return ("Ne bih kopirao nikoga ovaj tjedan: nitko nema dovoljno zatvorenih tradeova u plusu uz razumno "
                "držanje. Pustio bih bota da ocjenjuje dalje (svakih 6 h) i vratio se za dan-dva.")
    w, r = ranked[0]
    s = w["stats"]
    per = (s.get("closed_pnl_sol") or 0) / max(1, s.get("closed") or 1)
    c = r["copy"]
    if c and c[0] >= 3 and c[1] <= 0:
        return (f"Ne bih kopirao ni {wlink(w['wallet'])}, iako je prvi na listi: kad ga je demo bot kopirao {c[0]}×, "
                f"ispalo je {c[1]:+.0%} po tradeu. Njegova zarada ne prenosi se na našu kopiju (kasnimo, drugačiji izlazi). "
                "Čekao bih da se to promijeni.")
    stake = "50 $ po tradeu (5 % demo računa)" if r["tier"] == "visoka" else "20–25 $ po tradeu (2 %), dok ne skupi više povijesti"
    second = ""
    if len(ranked) > 1 and ranked[1][1]["tier"] != "niska":
        w2 = ranked[1][0]
        second = f" Kao drugi izbor {wlink(w2['wallet'])}, s pola tog uloga."
    proof = (f" Potvrda u demu: {c[0]} kopija, {c[1]:+.0%} po tradeu." if c and c[0] >= 3 else
             " Demo ga još nije dovoljno kopirao, pa bih krenuo malo i gledao prve 3 kopije.")
    return (f"Kopirao bih {wlink(w['wallet'])} s ulogom {stake}, najviše 3 otvorene pozicije odjednom, izlazi po "
            f"pravilima bota (ne ručno). Razlog: {s.get('closed', 0)} zatvorenih u plusu, {(s.get('win_rate') or 0):.0%} dobitnih, "
            f"prosječno {per:+.2f} SOL po tradeu, drži ~{_hold(s.get('median_hold_min'))} pa ga kopija stigne."
            f"{proof}{second}"
            + (f" Ako se povijest ponovi, 20 takvih tradeova po 50 $ daje otprilike {20 * 50 * s['roi_on_cost']:+,.0f} $ "
               "— to je procjena iz prošlosti, ne obećanje." if s.get("roi_on_cost") else ""))


def wallets_box(ws, copies=None):
    """HTML for the top of /wallets."""
    ranked = rank_wallets(ws, copies)
    cls = {"visoka": "good", "srednja": "warn", "niska": "mut"}
    head = f"<p><b>Što bih ja napravio:</b> {_verdict(ranked)}</p>"
    if not ranked:
        return ("<div class=card>" + head + "<p class=mut>Uvjeti za preporuku: barem "
                f"{MIN_CLOSED} zatvorenih tradeova, copy ocjena {MIN_COPY}+, u plusu, drži kraće od {CAP_HOLD_MIN // 60} h, "
                "bez loših oznaka. Tablica ispod je za one koji žele kopati sami.</p></div>")
    top = ranked[:3]
    items = "".join(
        f"<li>{wlink(w['wallet'])} <span class='b {cls[r['tier']]}'>pouzdanost {r['tier']}</span> "
        f"<span class=mut>({esc(r['tier_why'])})</span><br>{_sentence(w, r)}</li>" for w, r in top)
    rest = ranked[3:]
    skip = ""
    if rest:
        big = max(rest, key=lambda r: r[0]["stats"].get("closed_pnl_sol") or 0)
        w, r = big
        if (w["stats"].get("closed_pnl_sol") or 0) > max((t[0]["stats"].get("closed_pnl_sol") or 0) for t in top):
            why = []
            if (w["stats"].get("win_rate") or 0) < 0.5:
                why.append(f"samo {(w['stats'].get('win_rate') or 0):.0%} dobitnih")
            if (w["stats"].get("top_trade_share") or 0) > 0.5:
                why.append("većina dobitka iz jednog tradea")
            if r["tier"] == "niska":
                why.append("premalo podataka ili neaktivan")
            skip = (f"<p class=mut>Najveći PnL ima {wlink(w['wallet'])} ({w['stats'].get('closed_pnl_sol', 0):+.1f} SOL), "
                    f"ali ga ne bih uzeo prvog: {esc(', '.join(why) or 'niža copy ocjena')}.</p>")
    how = ("<p class=mut>Pouzdanost raste s podacima: niska → srednja na 15 zatvorenih, visoka na 30 bez jednog dominantnog "
           "dobitka. Strategija „Top novčanici” u demu kopira ove novčanike sama i izbacuje one koji se ne dokažu.</p>")
    return (f"<div class=card>{head}<p><b>Tri najbolja po podacima</b> ({len(ranked)} prolazi uvjete):</p><ol>{items}</ol>"
            f"{skip}{how}</div>")


def copies_from_strat():
    """{wallet prefix: (n, mean return, pnl $)} from the demo copies of tracked wallets, {} when strat.db is missing."""
    try:
        from strat import run, store
        con = store.ro()
        if con is None:
            return {}
        try:
            out = {}
            for label, n, mean, pnl in run.wallet_rank(con, run.load_config()):
                key = label.replace("novčanik ", "").rstrip("…")[:6]
                out[key] = (n, mean, pnl)
            return out
        finally:
            con.close()
    except Exception:  # noqa: BLE001 - the box never takes the page down
        return {}
