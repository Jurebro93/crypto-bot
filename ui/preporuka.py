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
    txt = (f"{s.get('closed_pnl_sol', 0):+.1f} SOL na {s.get('closed', 0)} zatvorenih ({(s.get('win_rate') or 0):.0%} "
           f"dobitnih), drži ~{_hold(s.get('median_hold_min'))}, zadnji trade {active}.")
    if r["copy"]:
        n, mean, pnl = r["copy"]
        txt += f" Naša demo kopija: {n} tradeova, prosjek {mean:+.0%}, {pnl:+,.0f} $."
    else:
        txt += " Demo ga još nije kopirao (kopira se čim kupi nešto što prolazi gate)."
    return txt


def wallets_box(ws, copies=None):
    """HTML for the top of /wallets."""
    ranked = rank_wallets(ws, copies)
    cls = {"visoka": "good", "srednja": "warn", "niska": "mut"}
    if not ranked:
        return ("<div class=card><b>Što s ovim:</b> još nijedan novčanik ne zadovoljava uvjete za kopiranje "
                f"(barem {MIN_CLOSED} zatvorenih, copy ocjena {MIN_COPY}+, u plusu, drži kraće od {CAP_HOLD_MIN // 60} h, "
                "bez loših oznaka). Bot ocjenjuje nove svakih 6 h; tablica ispod je za one koji žele kopati sami.</div>")
    top = ranked[:3]
    items = "".join(
        f"<li>{wlink(w['wallet'])} <span class='b {cls[r['tier']]}'>pouzdanost {r['tier']}</span> "
        f"<span class=mut>({esc(r['tier_why'])})</span><br>{esc(_sentence(w, r))}</li>" for w, r in top)
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
                    f"ali nije u vrhu: {esc(', '.join(why) or 'niža copy ocjena')}.</p>")
    how = ("<p><b>Kako koristiti:</b> kopiraj najviše 1–2 novčanika s pouzdanošću visoka/srednja, ulog do 5 % računa po "
           "tradeu, izlazi po pravilima bota (stop i ciljevi), ne ručno. Strategija „Top novčanici” u demu to već radi "
           "sama i izbacuje one koji se ne dokažu (3+ kopije). Pouzdanost raste s brojem zatvorenih tradeova: niska → "
           "srednja na 15, visoka na 30 bez jednog dominantnog dobitka.</p>")
    return (f"<div class=card><b>Što s ovim:</b> {len(ranked)} novčanika prolazi uvjete; najbolja tri:<ol>{items}</ol>"
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
