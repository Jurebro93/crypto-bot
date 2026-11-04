"""Top of the Demo trading page (Nicholas 4.11.): which strategies earn, which are near zero, how they could earn.

"Ogroman zid teksta iz kojeg ništa ne mogu razumjeti": the page now opens with one card per strategy (entry mode)
and a plain verdict, the market-cap bands measured separately, and the loss reasons as tap-to-open explanations.
Everything else on the page folds away under "Detalji". Read-only: built from closed demo trades in paper.db,
manual sales left out (not the bot's result), one trade counts at most +300% so a single lucky hit cannot decide.
"""
import json
import statistics
import time

from paper import arms
from ui.html import esc

CAP = 3.0          # one trade counts at most +300%
MIN_N = 10         # fewer closed trades = "premalo podataka", no verdict
GOOD = 0.03        # average per trade at least +3% (and money up) = earns
BAD = -0.05        # average per trade under -5% = loses; in between = near zero
MIN_BAND = 5       # trades a band needs before we call it better or worse
RECENT_D = 7

MODES = [  # entry mode -> (name, one-line what it is)
    ("aktivni", "Aktivni stariji tokeni", "token star 3+ dana koji danas ima najviše kupnji i prodaja"),
    ("mc100k", "Prvi prelazak 100k $", "ulaz kad token prvi put prijeđe 100k $ vrijednosti"),
    ("mc100k2", "Ponovni prelazak 100k $", "drugi ulaz kad token padne pa opet prijeđe 100k $"),
    ("kol3", "3+ KOL-a u 15 min", "ulaz kad ga 3 ili više različitih KOL-ova objave u 15 minuta"),
    ("konv", "Konvergencija izvora", "KOL-ovi, Telegram i KOL novčanici na istom tokenu u par minuta"),
    ("core", "Glavni (visoka ocjena)", "hype ocjena iznad praga"),
    ("explore", "Istraživački", "ocjena ispod praga, ali u vrhu dana; mali ulog da bot brže uči"),
]
MODE_NAME = {k: n for k, n, _ in MODES}

# every loss reason from paper/arms.loss_reason: what it means, why it happens, what the bot does about it
REASONS = {
    "kasni ulaz (odmah pad)": (
        "Kupili smo, a cijena je odmah krenula dolje i nikad nije bila ni +5% u plusu, pa je prodano na stop lossu.",
        "Najčešće smo ušli kad je token već skočio (gomila je kupila prije nas), pa smo kupili vrh.",
        "Bot smanjuje težinu signala koji su jaki kod takvih gubitnika (npr. nagli skok zadnji sat), a krakovi i "
        "razredi market capa koji tako gube dobivaju sve manje ulaza. Novi izvor „Aktivni” ne ulazi ako je token u "
        "zadnjem satu već skočio više od 40%."),
    "nema pokreta (vremenski izlaz)": (
        "Token se nakon kupnje nije ni digao ni srušio; bot ga je prodao kad je isteklo vrijeme držanja.",
        "Interes je nestao: nitko novi nije kupovao. Gubitak je obično mali (naknade i proklizavanje), ali novac je "
        "stajao umjesto da radi.",
        "Bot pri učenju izlaza isprobava kraće držanje i raniji izlaz kad nema rasta, i uzima ga sam ako je bolji i "
        "na starijim i na novijim trejdovima."),
    "dobit nije uzeta na vrijeme": (
        "Trade je bio barem +20% u plusu, ali se vratio i završio na stop lossu.",
        "Cilj za djelomičnu prodaju bio je predaleko ili trailing stop preširok, pa je dobit nestala.",
        "Bot uči izlaze po klasi tokena: raniji djelomični take profit ili stroži trailing uzima sam kad se pokažu "
        "boljima."),
    "stop loss": (
        "Trade je bio malo u plusu (5–20%), a onda pao do stop lossa.",
        "Token je krenuo, ali nije imao snage; obični gubitak.",
        "Ulazi u učenje težina i izlaza kao i svaki drugi ishod."),
    "rug (likvidnost nestala)": (
        "Likvidnost je nestala (developer ili veliki holder izvukao je novac iz poola), cijena je pala skoro na nulu.",
        "Najčešće kod vrlo malih i svježih tokena.",
        "Tvrdi filter ne ulazi u tokene ispod 20k $ vrijednosti, s lažnim poolom ili bez T0 provjere. Dnevni pregled "
        "broji rugove po presudi rug filtra; kad barem pola od 10+ tokena s istom presudom rugne, bot ih prestaje "
        "kupovati."),
    "pad nakon malog rasta": (
        "Token je narastao pa pao; trailing stop ili prodaja na ulaznoj cijeni zatvorili su ga oko nule ili malo u minusu.",
        "Rast je bio kratak; zaštita je spriječila veći gubitak.",
        "Bot uči koliko široko pratiti vrh (trailing) po klasi tokena."),
    "KOL novčanik prodao": (
        "KOL čiji je novčanik kupio taj token počeo je prodavati, pa je bot odmah izašao.",
        "Pratimo pametni novac: kad on izlazi, izlazimo i mi.",
        "Mjeri se kao dio konvergencije; ako ti izlazi gube, učenje to vidi u krakovima."),
}


def _manual(t):
    return t.get("exit_reason") == "rucno" or '"rucno"' in json.dumps(t.get("state") or {})


def _mode(t):
    try:
        c = json.loads(t["config"]) if isinstance(t.get("config"), str) else (t.get("config") or {})
    except ValueError:
        c = {}
    return c.get("entry_mode") or "core"


def _r(t):
    return min(CAP, t.get("ret") or 0)


def summarize(trades):
    """{key: {n, win, mean, median, pnl}} for a list of closed trades."""
    if not trades:
        return {"n": 0}
    rs = [_r(t) for t in trades]
    return {"n": len(trades), "win": sum(1 for t in trades if (t.get("ret") or 0) > 0) / len(trades),
            "mean": sum(rs) / len(rs), "median": statistics.median(rs),
            "pnl": sum(t.get("pnl_usd") or 0 for t in trades)}


def verdict(s):
    """'good' / 'zero' / 'bad' / 'few'."""
    if s.get("n", 0) < MIN_N:
        return "few"
    if s["mean"] >= GOOD and s["pnl"] > 0:
        return "good"
    if s["mean"] < BAD:
        return "bad"
    return "zero"


VERDICT_HR = {"good": ("zarađuje", "good"), "zero": ("blizu nule", "warn"), "bad": ("gubi", "bad"),
              "few": ("premalo podataka", "")}


def closed_trades(trades):
    return [t for t in trades if t.get("status") == "closed" and not _manual(t)]


def by_mode(closed):
    out = {}
    for t in closed:
        out.setdefault(_mode(t), []).append(t)
    return out


def by_band(closed):
    out = {}
    for t in closed:
        out.setdefault(arms.mc_band(t.get("entry_mcap")), []).append(t)
    return out


def reasons_of(closed):
    out = {}
    for t in closed:
        why = arms.loss_reason(t.get("exit_reason"), t.get("max_ret"), t.get("min_ret"), t.get("ret"))
        if why:
            out[why] = out.get(why, 0) + 1
    return out


FIX = {  # dominant loss reason -> how this strategy could get to profit, in one sentence
    "kasni ulaz (odmah pad)": "većina gubitaka je kasni ulaz: treba ulaziti ranije ili preskočiti token koji je već skočio",
    "nema pokreta (vremenski izlaz)": "većina gubitaka je token koji stoji: kraće držanje i raniji izlaz bez rasta",
    "dobit nije uzeta na vrijeme": "dobit se vraća: raniji djelomični take profit ili stroži trailing stop",
    "rug (likvidnost nestala)": "previše rugova: stroži filter, manje malih i svježih tokena",
    "stop loss": "tokeni krenu pa padnu: stroži izbor ulaza",
    "pad nakon malog rasta": "rast je kratak: brže uzimanje male dobiti",
    "KOL novčanik prodao": "KOL-ovi brzo prodaju: manje oslanjanja na njihove novčanike",
}


def how_to_fix(s, bands, reasons):
    """Plain sentences: where this strategy already earns and what would push it into profit."""
    out = []
    good = [(b, x) for b, x in bands.items() if x["n"] >= MIN_BAND and x["mean"] > 0]
    bad = [(b, x) for b, x in bands.items() if x["n"] >= MIN_BAND and x["mean"] < BAD]
    if good and verdict(s) != "good":
        b, x = max(good, key=lambda kv: kv[1]["mean"])
        out.append(f"Na tokenima {b[3:]} već zarađuje ({x['mean']:+.0%} po tradeu, {x['n']} tradeova).")
    if bad:
        b, x = min(bad, key=lambda kv: kv[1]["mean"])
        out.append(f"Najviše gubi na {b[3:]} ({x['mean']:+.0%} po tradeu); bot tom rasponu sam daje sve manje ulaza.")
    if reasons:
        top, n = max(reasons.items(), key=lambda kv: kv[1])
        tot = sum(reasons.values())
        if top in FIX and n / tot >= 0.3:
            out.append(f"{FIX[top][0].upper()}{FIX[top][1:]} ({n} od {tot} gubitaka).")
    if not out and verdict(s) == "good":
        out.append("Radi: bot joj daje pune ulaze.")
    return out


def _fmt(s):
    if not s.get("n"):
        return "još nema zatvorenih tradeova"
    return (f"{s['n']} tradeova · pogodak {s['win']:.0%} · prosjek {s['mean']:+.0%} po tradeu · "
            f"{s['pnl']:+,.2f} $".replace(",", "."))


def strategies_html(closed, now=None):
    now = now or time.time()
    modes = by_mode(closed)
    cards = []
    order = {"good": 0, "zero": 1, "bad": 2, "few": 3}
    rows = []
    for key, name, what in MODES:
        ts = modes.get(key) or []
        if not ts and key not in ("aktivni",):
            continue
        s = summarize(ts)
        recent = summarize([t for t in ts if (t.get("closed_ts") or 0) >= now - RECENT_D * 86400])
        bands = {b: summarize(x) for b, x in by_band(ts).items()}
        rows.append((order[verdict(s)], -(s.get("pnl") or 0), key, name, what, s, recent, bands, reasons_of(ts)))
    for _, _, key, name, what, s, recent, bands, reasons in sorted(rows):
        v, cls = VERDICT_HR[verdict(s)]
        fix = how_to_fix(s, bands, reasons) if s.get("n") else []
        if key == "aktivni" and not s.get("n"):
            fix = ["Nova strategija od 4.11.: mjeri se zasebno, presuda kad ima barem 10 zatvorenih tradeova."]
        cards.append(
            f"<div class='uc-card pv {cls}'><h3>{esc(name)} <span class='b {cls}'>{esc(v)}</span></h3>"
            f"<p class=uc-small style='margin:0 0 6px!important'>{esc(what)}</p><p>{esc(_fmt(s))}</p>"
            + (f"<p class=uc-small>Zadnjih {RECENT_D} dana: {esc(_fmt(recent))}</p>" if recent.get("n") and
               recent["n"] != s["n"] else "")
            + (("<ul class=uc-ul style='margin-top:8px'>" + "".join(f"<li>{esc(x)}</li>" for x in fix) + "</ul>")
               if fix else "") + "</div>")
    good = [r[3] for r in rows if r[0] == 0]
    zero = [r[3] for r in rows if r[0] == 1]
    head = ("Zarađuje: " + ", ".join(good) + "." if good else "Nijedna strategija još nije u plusu.") + (
        " Blizu nule: " + ", ".join(zero) + "." if zero else "")
    return (f"<div class=uc-top><p class='uc-v {'good' if good else ''}'>{esc(head)}</p><p class=uc-sub>Presuda "
            f"po strategiji iz zatvorenih demo tradeova (ručne prodaje se ne broje; jedan trade najviše +300%). "
            f"Zarađuje = prosjek barem +{GOOD:.0%} po tradeu i ukupno u plusu; blizu nule = između {BAD:.0%} i "
            f"+{GOOD:.0%}; ispod {MIN_N} tradeova nema presude.</p></div>" + "".join(cards))


def bands_html(closed):
    bands = by_band(closed)
    order = [arms.mc_band(x) for x in (2e6, 5e5, 1e5, 1e4)] + ["mc ?"]
    rows = []
    for b in order:
        s = summarize(bands.get(b) or [])
        if not s["n"]:
            continue
        v, cls = VERDICT_HR[verdict(s)] if s["n"] >= MIN_BAND else ("premalo podataka", "")
        rows.append(f"<tr><td>{esc(b[3:] if b != 'mc ?' else 'nepoznat')}</td><td class=n>{s['n']}</td>"
                    f"<td class=n>{s['win']:.0%}</td><td class='n {'pos' if s['mean'] > 0 else 'neg'}'>{s['mean']:+.0%}</td>"
                    f"<td class='n {'pos' if s['pnl'] > 0 else 'neg'}'>{s['pnl']:+.2f} $</td>"
                    f"<td><span class='b {cls}'>{esc(v)}</span></td></tr>")
    if not rows:
        return ""
    return ("<div class=uc-card><h3>Po veličini tokena (market cap pri ulazu)</h3><p class=uc-small style='margin:0 0 "
            "8px!important'>Token od 10k $ i token od 800k $ nisu ista igra: mali puno češće rugaju, veliki teže "
            "propadnu. Zato se svaki raspon mjeri zasebno, a raspon koji gubi bot sam dobiva sve manje ulaza. Ispod "
            "20k $ bot više ne ulazi.</p><div class=tw><table><thead><tr><th>Market cap</th><th class=n>Tradeova</th>"
            "<th class=n>Dobitnih</th><th class=n>Prosjek</th><th class=n>PnL</th><th>Presuda</th></tr></thead><tbody>"
            + "".join(rows) + "</tbody></table></div></div>")


def reasons_html(closed):
    rs = reasons_of(closed)
    if not rs:
        return ""
    tot = sum(rs.values())
    items = []
    for k, n in sorted(rs.items(), key=lambda kv: -kv[1]):
        what, why, fix = REASONS.get(k, ("", "", ""))
        body = (f"<p><b>Što znači:</b> {esc(what)}</p><p class=uc-m><b>Zašto se događa:</b> {esc(why)}</p>"
                f"<p class=uc-m><b>Što bot radi:</b> {esc(fix)}</p>") if what else "<p class=mut>Bez opisa.</p>"
        items.append(f"<details class=pv-r><summary><span>{esc(k)}</span><span class=mut>{n} ({n / tot:.0%})"
                     f"</span></summary><div class=in>{body}</div></details>")
    return ("<div class=uc-card><h3>Zašto gubimo <span class=mut>· dodirni razlog za objašnjenje</span></h3>"
            + "".join(items) + "</div>")


CSS = """<style>
.pv h3{display:flex;justify-content:space-between;gap:8px;align-items:center}
.uc-card.pv.good{border-left:4px solid var(--good)}.uc-card.pv.bad{border-left:4px solid var(--bad)}
.uc-card.pv.warn{border-left:4px solid var(--warn)}
details.pv-r{border-top:1px solid var(--line)}details.pv-r:first-of-type{border-top:0}
details.pv-r>summary{list-style:none;display:flex;justify-content:space-between;gap:10px;padding:11px 0;cursor:pointer;
  font-size:14px}
details.pv-r>summary::-webkit-details-marker{display:none}
details.pv-r>summary>span:first-child::before{content:'▸ ';color:var(--mut)}
details.pv-r[open]>summary>span:first-child::before{content:'▾ '}
details.pv-r>.in{padding:0 0 12px;font-size:14px;line-height:1.5}details.pv-r>.in p{margin:0}
</style>"""


def top_html(trades, now=None):
    """Strategy verdicts + market-cap bands + clickable loss reasons; '' if nothing is closed yet."""
    closed = closed_trades(trades)
    if not closed:
        return ""
    from ui import learnprogress
    return learnprogress.CSS + CSS + strategies_html(closed, now) + bands_html(closed) + reasons_html(closed)
