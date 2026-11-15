"""Osvrti: what the numbers on the public market pages mean, in small boxes (15.11., vlasnik: "najbitnije je
interpretacija ... kritičar može interpretirati te podatke i napisati svoje osvrte u malim boksevima").

Two kinds of box, both in English and Croatian:
  * rules(): sentences computed from the same snapshot the page shows (free, always there, never older than the data);
  * critic(): the Kritičar's own short reads (critic/market.py, OpenAI, twice a day, a few cents a month), shown while
    they are younger than CRITIC_MAX_AGE_S and written for the data day the page shows or the day before.
Nothing here names a token, a wallet or a caller, and nothing is a buy or sell call.

locked(): the "members see more" box of a page: what is behind the login, with blurred placeholder rows (the real rows
are never in the public HTML) and the request-access button.
"""
import json
import os
import sqlite3
import time

from ui.html import esc

D = 86400
CRITIC_MAX_AGE_S = 36 * 3600
CRITIC_KEY = "market_osvrt"
MAX_BOXES = 3

CSS = """
.osv{display:grid;grid-template-columns:repeat(auto-fit,minmax(250px,1fr));gap:12px;margin:0 0 26px}
.osv>div{border:1px solid var(--line);border-left:4px solid var(--acc);border-radius:14px;background:#fff;padding:14px 16px}
.osv>div.up{border-left-color:#1baf7a}.osv>div.dn{border-left-color:#eb6834}.osv>div.ai{border-left-color:#7c5cff;background:#faf9ff}
.osv .ot{display:block;font-size:12px;font-weight:700;letter-spacing:.06em;text-transform:uppercase;color:var(--mut);margin:0 0 6px}
.osv h3{margin:0 0 6px;font-size:16.5px;line-height:1.3}.osv p{margin:0;color:#3a4252;font-size:14.5px;line-height:1.5}
.osv .ow{display:block;margin-top:8px;font-size:12px;color:var(--mut)}
.lvdot{display:inline-block;width:8px;height:8px;border-radius:50%;background:#1baf7a;margin-right:8px;
animation:lvp 1.6s ease-in-out infinite}@keyframes lvp{50%{opacity:.35}}
.livebar{display:flex;flex-wrap:wrap;gap:8px 22px;align-items:center;border:1px solid var(--line);border-radius:14px;
background:#fff;padding:12px 16px;margin:0 0 18px;font-size:14.5px}.livebar b{font-weight:740}
.livebar .lt{font-weight:700;font-size:12px;letter-spacing:.06em;text-transform:uppercase;color:var(--mut)}
.lkd{border:1px solid var(--line);border-radius:18px;background:#fff;margin:26px 0 18px;overflow:hidden}
.lkd .lh{padding:18px 20px 6px}.lkd h2{margin:0 0 6px;font-size:21px}.lkd .lh p{margin:0;color:var(--mut)}
.lkd .lrows{position:relative;padding:8px 20px 4px}
.lkd .lr{display:flex;justify-content:space-between;gap:12px;padding:10px 0;border-bottom:1px solid var(--line);font-size:15px}
.lkd .lr span:last-child{filter:blur(6px);user-select:none;color:var(--mut);white-space:nowrap}
.lkd .lf{display:flex;flex-wrap:wrap;gap:12px 18px;align-items:center;justify-content:space-between;background:var(--fg);
color:#fff;padding:16px 20px}.lkd .lf p{margin:0;color:#cbd2df;max-width:560px}.lkd .lf .btn{background:#fff;color:var(--fg)}
"""


# ---------- the rule-based reads ---------------------------------------------------------------------------------------

def _g(a, b):
    return (a / b - 1) if a is not None and b else None


def _sum(ser, day, n):
    w = [ser.get(day - i * D) for i in range(n)]
    return sum(w) if all(v is not None for v in w) else None


def _market_rules(d):
    from ui import marketpub as M
    out = []
    day, ser = d["day"], d["ser"]
    lp, dx = ser["launchpad"], ser["dex"]
    cur = d["regime"][-1] if d["regime"] else None
    lp7, lpp = _sum(lp, day, 7), _sum(lp, day - 7 * D, 7)
    gr = _g(lp7, lpp)
    if cur:
        score, f = cur[1], cur[3]
        p = f.get("launchpad_pct90")
        rank = f"{100 * p:.0f}" if p is not None else None
        if score <= 33:
            out.append(("dn", "The trenches are quiet", "Rovovi su tihi",
                        f"The season index is {score:.0f}/100. Launchpad volume of the last 7 days is "
                        + (f"higher than only {rank}% of the last 90 days. " if rank else "low against the last 90 days. ")
                        + "In weeks like this fewer new coins find buyers and moves fade faster, so the same call is "
                          "worth less than it was a month ago.",
                        f"Indeks sezone je {score:.0f}/100. Volumen launchpada u zadnjih 7 dana "
                        + (f"veći je od samo {rank}% zadnjih 90 dana. " if rank else "nizak je prema zadnjih 90 dana. ")
                        + "U ovakvim tjednima manje novih coina nađe kupce i skokovi kraće traju, pa isti poziv vrijedi "
                          "manje nego prije mjesec dana."))
        elif score >= 66:
            out.append(("up", "Meme season is on", "Sezona meme coina traje",
                        f"The season index is {score:.0f}/100: launchpads and Solana DEXs both trade near the top of "
                        "their last 90 days. More coins run in weeks like this, and more of them are copies and rugs, "
                        "so checks matter more, not less.",
                        f"Indeks sezone je {score:.0f}/100: launchpadi i Solana DEX-ovi trguju blizu vrha zadnjih 90 "
                        "dana. U ovakvim tjednima više coina poleti, ali je i više kopija i rugova, pa provjere vrijede "
                        "više, a ne manje."))
        else:
            out.append(("", "Neither hot nor cold", "Ni vruće ni hladno",
                        f"The season index is {score:.0f}/100, the middle band. Volume is ordinary for the last 90 "
                        "days: single coins move on their own story, not on a market-wide wave.",
                        f"Indeks sezone je {score:.0f}/100, srednji pojas. Volumen je običan za zadnjih 90 dana: "
                        "pojedini coini se kreću zbog svoje priče, a ne zbog vala na cijelom tržištu."))
    if gr is not None and abs(gr) >= 0.08:
        streak, x = 0, day
        while streak < 12 and _g(_sum(lp, x, 7), _sum(lp, x - 7 * D, 7)) is not None and \
                (_g(_sum(lp, x, 7), _sum(lp, x - 7 * D, 7)) > 0) == (gr > 0):
            streak, x = streak + 1, x - 7 * D
        wk_en = f" It is the {streak}{'th' if streak > 3 else ('st', 'nd', 'rd')[streak - 1]} week in a row." if streak >= 2 else ""
        wk_hr = f" To je {streak}. tjedan zaredom." if streak >= 2 else ""
        out.append(("up" if gr > 0 else "dn",
                    "Launchpad volume is growing" if gr > 0 else "Launchpad volume is shrinking",
                    "Volumen launchpada raste" if gr > 0 else "Volumen launchpada pada",
                    f"{M.usd(lp7)} in 7 days, {M.pct(gr)} against the week before.{wk_en} Launchpads are where new "
                    "meme coins are born, so this is the first number that moves when interest comes or goes.",
                    f"{M.usd(lp7, 'hr')} u 7 dana, {M.pct(gr, 'hr')} prema tjednu prije.{wk_hr} Na launchpadima "
                    "nastaju novi meme coini, pa je ovo prvi broj koji se pomakne kad interes dolazi ili odlazi."))
    dx7 = _sum(dx, day, 7)
    sh = lp7 / dx7 if lp7 and dx7 else None
    lp30, dx30 = _sum(lp, day, 30), _sum(dx, day, 30)
    sh30 = lp30 / dx30 if lp30 and dx30 else None
    if sh is not None and sh30 and abs(sh / sh30 - 1) >= 0.1:
        more = sh > sh30
        out.append(("up" if more else "dn",
                    "Memes take a bigger slice of Solana" if more else "Memes take a smaller slice of Solana",
                    "Meme coini uzimaju veći dio Solane" if more else "Meme coini uzimaju manji dio Solane",
                    f"Launchpads made {M.pct(sh, signed=False, dec=1)} of Solana DEX volume this week against "
                    f"{M.pct(sh30, signed=False, dec=1)} over 30 days: "
                    + ("money on Solana is moving towards new coins." if more else
                       "money on Solana is going to bigger coins and stable pairs, not to new launches."),
                    f"Launchpadi su ovaj tjedan činili {M.pct(sh, 'hr', signed=False, dec=1)} Solana DEX volumena, prema "
                    f"{M.pct(sh30, 'hr', signed=False, dec=1)} kroz 30 dana: "
                    + ("novac na Solani ide prema novim coinima." if more else
                       "novac na Solani ide u veće coine i stabilne parove, a ne u nova lansiranja.")))
    p0, p7 = d["price"].get(day), d["price"].get(day - 7 * D)
    pg = _g(p0, p7)
    if pg is not None and abs(pg) >= 0.1 and len(out) < MAX_BOXES:
        out.append(("up" if pg > 0 else "dn", "SOL is doing part of the work", "SOL radi dio posla",
                    f"SOL closed at ${p0:.2f}, {M.pct(pg)} in 7 days. Volumes here are in dollars, so a "
                    + ("falling" if pg < 0 else "rising") + " SOL price alone moves them the same way even when the same "
                    "number of coins changes hands.",
                    f"SOL je zatvorio na {M._n(f'${p0:.2f}', 'hr')}, {M.pct(pg, 'hr')} u 7 dana. Volumeni su ovdje u "
                    "dolarima, pa ih sam " + ("pad" if pg < 0 else "rast") + " cijene SOL-a pomiče u istom smjeru i kad "
                    "isti broj coina promijeni vlasnika."))
    return out


def _calls_rules(d):
    from ui import marketpub as M
    c = d.get("calls")
    if not c:
        return []
    out = []
    y = c["x"].get(c["day"]) or {}
    ch = _g(y.get("calls"), c["calls_avg7"])
    if ch is not None and abs(ch) >= 0.15:
        up = ch > 0
        out.append(("up" if up else "dn", "Influencers are louder than usual" if up else "Influencers went quiet",
                    "Influenceri su glasniji nego inače" if up else "Influenceri su utihnuli",
                    f"{y['calls']:,} calls on X on the last full day, {M.pct(ch)} against their 7-day average. "
                    + ("More calls means more noise per good coin: the same token is often shouted by many accounts at once."
                       if up else "Fewer calls usually comes with a cold market: callers post less when their last calls did not move."),
                    M._n(f"{y['calls']:,}", "hr") + f" poziva na X-u zadnjeg punog dana, {M.pct(ch, 'hr')} prema prosjeku 7 dana. "
                    + ("Više poziva znači više buke po dobrom coinu: isti token često u isto vrijeme viče mnogo računa."
                       if up else "Manje poziva obično ide uz hladno tržište: calleri objavljuju manje kad im se zadnji pozivi nisu pomaknuli.")))
    h7, h30 = c.get("hit7"), c.get("hit30")
    if h7 is not None and h30 is not None and c.get("n7", 0) >= 40 and abs(h7 - h30) >= 0.04:
        up = h7 > h30
        out.append(("up" if up else "dn", "Calls are working better this week" if up else "Calls are working worse this week",
                    "Pozivi ovaj tjedan prolaze bolje" if up else "Pozivi ovaj tjedan prolaze lošije",
                    f"{M.pct(h7, signed=False)} of first calls touched +50% within 24 h in the last 7 measured days, "
                    f"against {M.pct(h30, signed=False)} over 30 days. It is a peak, not a profit: it says how often "
                    "there was a move to catch, not that following the call paid.",
                    f"{M.pct(h7, 'hr', signed=False)} prvih poziva dotaknulo je +50% unutar 24 h u zadnjih 7 izmjerenih dana, "
                    f"prema {M.pct(h30, 'hr', signed=False)} kroz 30 dana. To je vrh, a ne zarada: govori koliko je često "
                    "bilo pomaka koji se mogao uhvatiti, a ne da se praćenje poziva isplatilo."))
    m7, m30 = c.get("mc7"), c.get("mc30")
    if m7 and m30 and abs(m7 / m30 - 1) >= 0.2:
        up = m7 > m30
        out.append(("", "Callers are picking bigger coins" if up else "Callers are picking smaller coins",
                    "Calleri biraju veće coine" if up else "Calleri biraju manje coine",
                    f"The median market cap at the call is {M.usd(m7)} this week against {M.usd(m30)} over 30 days. "
                    + ("Bigger coins move less in a day, but fewer of them go to zero." if up else
                       "Smaller coins can multiply faster and die faster: the rug share is the number to watch next to this one."),
                    f"Medijan market capa u trenutku poziva ovaj je tjedan {M.usd(m7, 'hr')}, prema {M.usd(m30, 'hr')} kroz 30 dana. "
                    + ("Veći coini se u danu manje pomaknu, ali ih manje ode na nulu." if up else
                       "Manji coini se brže umnože i brže umru: uz ovaj broj treba gledati i udio rugova.")))
    reg = c.get("regime") or {}
    if "cold" in reg and "hot" in reg and len(out) < MAX_BOXES:
        a, b = reg["hot"]["rate"], reg["cold"]["rate"]
        out.append(("", "The market decides more than the caller", "Tržište odlučuje više nego caller",
                    f"On hot days {M.pct(a, signed=False)} of first calls touched +50% within 24 h, on cold days "
                    f"{M.pct(b, signed=False)} (last 90 days). The same accounts, the same kind of coins: the difference "
                    "is the day they were called on.",
                    f"U vruće dane {M.pct(a, 'hr', signed=False)} prvih poziva dotaknulo je +50% unutar 24 h, u hladne "
                    f"{M.pct(b, 'hr', signed=False)} (zadnjih 90 dana). Isti računi, ista vrsta coina: razlika je dan "
                    "u kojem su pozvani."))
    return out


def _launchpad_rules(d):
    from ui import marketpub as M
    ps = d["plats"]["launchpad"]
    if not ps:
        return []
    out = []
    tot = sum(p["v7"] for p in ps) or 1
    totp = sum(p["p7"] for p in ps) or 0
    top = ps[0]
    nm = M.plabel(top, "en")[0]
    sh, shp = top["v7"] / tot, (top["p7"] / totp if totp else None)
    if sh >= 0.6:
        out.append(("", f"{nm} is the market", f"{nm} je tržište",
                    f"{M.pct(sh, signed=False)} of launchpad volume went through {nm} in the last 7 days"
                    + (f" ({M.pct(shp, signed=False)} the week before)" if shp else "") + ". When one launchpad is this "
                    "big, its own rules and fees are the rules of the whole meme coin market.",
                    f"{M.pct(sh, 'hr', signed=False)} volumena launchpada prošlo je kroz {nm} u zadnjih 7 dana"
                    + (f" ({M.pct(shp, 'hr', signed=False)} tjedan prije)" if shp else "") + ". Kad je jedan launchpad ovoliki, "
                    "njegova pravila i naknade su pravila cijelog tržišta meme coina."))
    movers = [(p, _g(p["v7"], p["p7"])) for p in ps[1:4] if p["p7"] and p["v7"] >= 0.02 * tot]
    movers = [(p, g) for p, g in movers if g is not None and abs(g) >= 0.25]
    if movers:
        p, g = max(movers, key=lambda x: abs(x[1]))
        n2 = M.plabel(p, "en")[0]
        out.append(("up" if g > 0 else "dn", f"{n2} is " + ("gaining" if g > 0 else "losing ground"),
                    f"{n2} " + ("raste" if g > 0 else "gubi tlo"),
                    f"{M.usd(p['v7'])} in 7 days, {M.pct(g)} against the week before, {M.pct(p['v7'] / tot, signed=False, dec=1)} "
                    "of all launchpad volume. Challengers usually grow in bursts around one or two big coins, then fall back.",
                    f"{M.usd(p['v7'], 'hr')} u 7 dana, {M.pct(g, 'hr')} prema tjednu prije, {M.pct(p['v7'] / tot, 'hr', signed=False, dec=1)} "
                    "volumena svih launchpada. Izazivači obično rastu u naletima oko jednog ili dva velika coina, pa se vrate."))
    return out


def _dex_rules(d):
    from ui import marketpub as M
    ps, ts = d["plats"]["dex"], d["plats"]["terminal"]
    out = []
    movers = [(p, _g(p["v7"], p["p7"])) for p in ps[:10] if p["p7"]]
    movers = [(p, g) for p, g in movers if g is not None and abs(g) >= 0.2]
    if movers:
        p, g = max(movers, key=lambda x: abs(x[1]))
        nm = M.plabel(p, "en")[0]
        out.append(("up" if g > 0 else "dn", f"Biggest mover in the top 10: {nm}", f"Najveći pomak u top 10: {nm}",
                    f"{M.usd(p['v7'])} in 7 days, {M.pct(g)} against the week before. Many of the biggest Solana DEXs are "
                    "market-maker pools behind aggregators, so a move here is mostly routing, not a crowd of traders coming or going.",
                    f"{M.usd(p['v7'], 'hr')} u 7 dana, {M.pct(g, 'hr')} prema tjednu prije. Mnogi od najvećih Solana DEX-ova "
                    "su bazeni market makera iza agregatora, pa je pomak ovdje uglavnom usmjeravanje, a ne dolazak ili odlazak trejdera."))
    if len(ts) >= 2:
        a, b = ts[0], ts[1]
        tot = sum(p["v7"] for p in ts) or 1
        na, nb = M.plabel(a, "en")[0], M.plabel(b, "en")[0]
        out.append(("", f"Where meme traders click: {na}", f"Gdje trejderi klikaju: {na}",
                    f"{na} did {M.pct(a['v7'] / tot, signed=False)} of terminal volume in 7 days, {nb} "
                    f"{M.pct(b['v7'] / tot, signed=False)}. Terminal volume is people trading by hand, the closest public "
                    "number to how many retail traders are active.",
                    f"{na} je napravio {M.pct(a['v7'] / tot, 'hr', signed=False)} volumena terminala u 7 dana, {nb} "
                    f"{M.pct(b['v7'] / tot, 'hr', signed=False)}. Volumen terminala su ljudi koji trguju ručno: javni broj "
                    "najbliži tome koliko je malih trejdera aktivno."))
    return out


def _season_rules(d):
    reg = d["regime"]
    if not reg:
        return []
    out = []
    day, score, _lb, f = reg[-1]
    band = lambda s: "hot" if s >= 66 else "cold" if s <= 33 else "neutral"   # noqa: E731
    streak = 0
    for _d, s, *_ in reversed(reg):
        if band(s) != band(score):
            break
        streak += 1
    last_hot = next((x[0] for x in reversed(reg) if x[1] >= 66), None)
    if band(score) != "neutral" and streak >= 2:
        hot = band(score) == "hot"
        since = int((day - last_hot) / D) if last_hot and not hot else None
        out.append(("up" if hot else "dn", f"{streak} {'hot' if hot else 'cold'} days in a row",
                    f"{streak} {'vrućih' if hot else 'hladnih'} dana zaredom",
                    (f"The index has been {'above 66' if hot else 'below 34'} for {streak} days."
                     + (f" The last hot day was {since} days ago." if since else "")
                     + " Runs like this end when launchpad volume turns, which shows in the week-on-week number first."),
                    (f"Indeks je {'iznad 66' if hot else 'ispod 34'} već {streak} dana."
                     + (f" Zadnji vrući dan bio je prije {since} dana." if since else "")
                     + " Ovakvi nizovi završe kad se okrene volumen launchpada, što se prvo vidi u broju tjedan na tjedan.")))
    parts = [("launchpad volume", "volumen launchpada", f.get("launchpad_pct90")),
             ("Solana DEX volume", "volumen Solana DEX-a", f.get("dex_pct90")),
             ("launchpad growth", "rast launchpada", f.get("launchpad_growth_pct90"))]
    parts = [p for p in parts if p[2] is not None]
    if len(parts) == 3:
        lo, hi = min(parts, key=lambda p: p[2]), max(parts, key=lambda p: p[2])
        if hi[2] - lo[2] >= 0.15:
            out.append(("", f"What holds the index down: {lo[0]}", f"Što drži indeks dolje: {lo[1]}",
                        f"Of the three parts, {lo[0]} ranks lowest ({100 * lo[2]:.0f}/100 against the last 90 days) and "
                        f"{hi[0]} highest ({100 * hi[2]:.0f}/100). The index turns when its weakest part does.",
                        f"Od tri dijela najniže stoji {lo[1]} ({100 * lo[2]:.0f}/100 prema zadnjih 90 dana), a najviše "
                        f"{hi[1]} ({100 * hi[2]:.0f}/100). Indeks se okrene kad se okrene njegov najslabiji dio."))
    return out


def _besttime_rules(d):
    from ui import marketpub as M
    h = d.get("hours")
    if not h or not h.get("sess"):
        return []
    rated = {k: v for k, v in h["sess"].items() if v.get("rate") is not None and v.get("n", 0) >= 100}
    if len(rated) < 2:
        return []
    best, worst = max(rated, key=lambda k: rated[k]["rate"]), min(rated, key=lambda k: rated[k]["rate"])
    busy = max(h["sess"], key=lambda k: h["sess"][k].get("vol") or 0)
    en, hr = M.SESSION_NAMES["en"], M.SESSION_NAMES["hr"]
    out = []
    if rated[best]["rate"] - rated[worst]["rate"] >= 0.03:
        out.append(("", "The busiest hours are not the best ones" if best != busy else "The busiest session also works best",
                    "Najprometniji sati nisu najbolji" if best != busy else "Najprometnija sesija ujedno prolazi najbolje",
                    f"Calls posted in the {en[best]} session touched +50% most often ({M.pct(rated[best]['rate'], signed=False)}), "
                    f"in the {en[worst]} session least ({M.pct(rated[worst]['rate'], signed=False)}), while most volume "
                    f"trades in the {en[busy]} session. More volume also means more bots competing for the same entry.",
                    f"Pozivi objavljeni u sesiji {hr[best]} najčešće su dotaknuli +50% ({M.pct(rated[best]['rate'], 'hr', signed=False)}), "
                    f"u sesiji {hr[worst]} najrjeđe ({M.pct(rated[worst]['rate'], 'hr', signed=False)}), a najviše volumena "
                    f"trguje se u sesiji {hr[busy]}. Više volumena znači i više botova koji se natječu za isti ulaz."))
    return out


RULES = {"market": _market_rules, "calls": _calls_rules, "launchpads": _launchpad_rules, "dex": _dex_rules,
         "season": _season_rules, "besttime": _besttime_rules}


def rules(key, d):
    """[(tone, title_en, title_hr, text_en, text_hr)] for one page; a rule that fails is left out."""
    try:
        return (RULES[key](d) if key in RULES else [])[:MAX_BOXES]
    except Exception as e:  # noqa: BLE001 - a box must never break a page
        print(f"marketnotes: {key}: {type(e).__name__}: {e}", flush=True)
        return []


# ---------- the Kritičar's reads --------------------------------------------------------------------------------------

def critic(now=None):
    """{"ts", "day", "notes": [{"tema", "hr", "en"}]} stored by critic/market.py, or None (off, no key, too old)."""
    now = now or time.time()
    try:
        from trade import settings
        p = settings.DB
        if not os.path.exists(p):
            return None
        con = sqlite3.connect(f"file:{p}?mode=ro", uri=True, timeout=5)
        try:
            r = con.execute("SELECT v FROM critic_kv WHERE k=?", (CRITIC_KEY,)).fetchone()
        finally:
            con.close()
        v = json.loads(r[0]) if r else None
    except Exception:  # noqa: BLE001 - no table yet, no database: no box
        return None
    if not isinstance(v, dict) or now - (v.get("ts") or 0) > CRITIC_MAX_AGE_S:
        return None
    return v


def boxes(key, d, lang):
    """The row of boxes for one page: the rule-based reads, then the Kritičar's read of that page when there is one."""
    en = lang == "en"
    items = []
    for tone, t_en, t_hr, x_en, x_hr in rules(key, d):
        items.append(f"<div class='{tone}'><span class=ot>{'What it means' if en else 'Što to znači'}</span>"
                     f"<h3>{esc(t_en if en else t_hr)}</h3><p>{esc(x_en if en else x_hr)}</p></div>")
    cr = d.get("critic")
    if cr and (cr.get("day") or 0) >= d["day"] - D:
        for n in cr.get("notes") or []:
            if n.get("tema") == key and n.get("en" if en else "hr"):
                when = time.strftime("%H:%M UTC", time.gmtime(cr["ts"]))
                items.append(f"<div class=ai><span class=ot>{'The Critic (AI) says' if en else 'Kritičar (AI) kaže'}</span>"
                             f"<p>{esc(n['en' if en else 'hr'])}</p><span class=ow>"
                             + ("Written by an AI model from the numbers on this page" if en else
                                "Napisao AI model iz brojki na ovoj stranici") + f", {when}.</span></div>")
                break
    return f"<div class=osv>{''.join(items)}</div>" if items else ""


# ---------- the members box -------------------------------------------------------------------------------------------

LOCKED = {
    "market": (("What members see on top of this", "Što članovi vide povrh ovoga"),
               ("The public page is the weather. Inside is what to do about it, live.",
                "Javna stranica je vremenska prognoza. Unutra je što s tim napraviti, uživo."),
               [("New tokens getting volume right now", "Novi tokeni koji upravo dobivaju volumen"),
                ("Which influencers called them, and their record", "Koji su ih influenceri pozvali i kakav im je učinak"),
                ("Wallets that bought before the call", "Novčanici koji su kupili prije poziva"),
                ("Rug check of every token on the list", "Rug provjera svakog tokena na popisu")]),
    "calls": (("What members see on top of this", "Što članovi vide povrh ovoga"),
              ("Totals are public. The calls themselves, minutes old, are for members.",
               "Zbrojevi su javni. Sami pozivi, stari nekoliko minuta, su za članove."),
              [("Tokens called in the last hour", "Tokeni pozvani u zadnjih sat vremena"),
               ("Tokens several influencers called together", "Tokeni koje je više influencera pozvalo zajedno"),
               ("Each caller's result after costs, not the peak", "Rezultat svakog callera nakon troškova, a ne vrh"),
               ("Telegram channels that are first, not loudest", "Telegram kanali koji su prvi, a ne najglasniji")]),
}


def locked(key, lang):
    """The members box: a heading, placeholder rows (blurred dummy text, never real data) and the access button."""
    en = lang == "en"
    (h_en, h_hr), (p_en, p_hr), rows = LOCKED.get(key) or LOCKED["market"]
    home = "/" if en else "/hr"
    r = "".join(f"<div class=lr><span>{esc(a if en else b)}</span><span aria-hidden=true>●●●●●● ●●●●</span></div>"
                for a, b in rows)
    return (f"<div class=lkd><div class=lh><h2>🔒 {esc(h_en if en else h_hr)}</h2><p>{esc(p_en if en else p_hr)}</p></div>"
            f"<div class=lrows>{r}</div><div class=lf><p>"
            + ("Free for now. Access is by request." if en else "Za sada besplatno. Pristup je na zahtjev.")
            + f"</p><a class='btn sm' href={home}#pristup>{'Request access' if en else 'Zatraži pristup'}</a></div></div>")
