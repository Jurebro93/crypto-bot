"""Public homepage of MemeSonar as a data product (28.11.2026, vlasnik: poslovni plan prihvaćen, "ne želimo tvrditi da
smo napravili profitabilan bot").

One promise: measured data about Solana memecoins, i.e. what influencer calls and wallets really returned after cost,
and next to every score its measured out-of-sample accuracy. The page:

  hero             the promise, two buttons (the free influencer check, the prices)
  proof strip      three measured numbers from our own data, each with its sample size and date (proof()); a number
                   without enough data says "still measuring" instead, never a made-up value
  products         influencers, wallets and people, token risk, pump.fun statistics
  how we measure   four plain sentences and a link to the methodology page
  prices           the three packages in short, link to the prices page
  weekly report    e-mail + consent (ui/cijene.submit, plan "tjedni"); section id=pristup, every "#pristup" link of
                   the public site lands here
  site log, FAQ, footer with "Podaci, ne financijski savjet"
No Autopilot, no trading bot, no locked block that promises a feature a visitor cannot get. proof() runs in the
background count of ui/landing (compute), never on a page view.
"""
import os
import sqlite3
import time

from ui.html import esc, logo

COST = 0.03                 # the cost every public "after cost" number uses: never below 3 % a round trip (CLAUDE.md)
KOL_DAYS = 30               # the influencer number: clean calls of the last 30 days (older than the public 24 h)
KOL_MIN_N = 100             # fewer calls: "still measuring"
TOC_MIN_N = 30              # fewer checked scores: "still measuring"
KOP_MIN_SOURCES = 10        # fewer wallets with a verdict: "still measuring"
KOP_DELAY = 30
TOC_ORDER = ("rug", "topcheck", "kol", "dokazani", "pouzdanost")
TOC_NAME = {"rug": ("provjere ruga", "the rug check"), "topcheck": ("provjere ruga", "the rug check"),
            "kol": ("presude za influencera", "the influencer verdict"),
            "dokazani": ("ocjene novčanika", "the wallet verdict"),
            "pouzdanost": ("ocjene pouzdanosti", "the reliability score")}

# every path of the new public pages: (English, Croatian); the old addresses the owner named redirect here
PATHS = {"home": ("/", "/hr"), "pricing": ("/pricing", "/hr/cijene"), "check": ("/check-influencer", "/hr/provjeri-influencera"),
         "method": ("/methodology", "/hr/metodologija")}
ALIASES = {"/cijene": "/hr/cijene", "/en/pricing": "/pricing", "/en/cijene": "/pricing",
           "/provjeri-influencera": "/hr/provjeri-influencera", "/en/check-influencer": "/check-influencer",
           "/metodologija": "/hr/metodologija", "/en/methodology": "/methodology"}


def href(key, lang):
    return PATHS[key][0 if lang == "en" else 1]


# ---------- the proof strip ---------------------------------------------------------------------------------------

def _ro(path):
    if not path or not os.path.exists(path) or not os.path.getsize(path):
        return None
    try:
        return sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5)
    except sqlite3.Error:
        return None


def kol_number(now=None, path=None):
    """{"share", "n", "day"}: of the clean measured influencer calls of the last KOL_DAYS days (older than 24 h, the
    public delay), the share whose token was higher a day later after a COST round trip; None below KOL_MIN_N."""
    from ui import kolstats as KS
    from ui import public
    now = now or time.time()
    con = _ro(path or public._kol_db())
    if con is None:
        return None
    q = ",".join("?" * len(KS.BIASED_SOURCES))
    base = (f"FROM calls WHERE kind='call' AND max24 IS NOT NULL AND r24h IS NOT NULL AND bad IS NULL AND ts < ? "
            f"AND ts >= ? AND COALESCE(pre2h, 0) < 1.0 AND COALESCE(source, '') NOT IN ({q}) "
            f"AND handle NOT LIKE 'w:%' AND handle NOT LIKE 'tg:%'")
    args = (1.0 - COST, int(now - KS.PUBLIC_DELAY_S), int(now - KS.PUBLIC_DELAY_S - KOL_DAYS * 86400), *KS.BIASED_SOURCES)
    sel = "SELECT COUNT(*), SUM(CASE WHEN (1.0 + r24h) * ? > 1.0 THEN 1 ELSE 0 END), MAX(ts) "
    try:
        try:
            r = con.execute(sel + base + " AND handle NOT IN (SELECT handle FROM kols WHERE COALESCE(bot, 0) = 1)",
                            args).fetchone()
        except sqlite3.OperationalError:
            r = con.execute(sel + base, args).fetchone()
    except sqlite3.Error:
        return None
    finally:
        con.close()
    n = int(r[0] or 0) if r else 0
    if n < KOL_MIN_N:
        return None
    return {"share": (r[1] or 0) / n, "n": n, "day": time.strftime("%Y-%m-%d", time.gmtime(r[2]))}


def toc_number(path=None):
    """{"score", "acc", "n", "day"}: the measured out-of-sample accuracy of the first score in TOC_ORDER that has
    enough checked cases in the newest night (tocnost/), None when none has."""
    try:
        from tocnost import store
        from ui import tocnost as UT
        rows = store.latest(path or UT.db_path())
    except Exception:  # noqa: BLE001
        return None
    for score in TOC_ORDER:
        got = [r for (s, _b), r in rows.items() if s == score and r.get("enough") and r.get("correct") is not None]
        n = sum(int(r.get("n") or 0) for r in got)
        if n >= TOC_MIN_N:
            k = sum(int(r.get("correct") or 0) for r in got)
            as_of = max(int(r.get("as_of") or 0) for r in got)
            return {"score": score, "acc": k / n, "n": n, "day": time.strftime("%Y-%m-%d", time.gmtime(as_of))}
    return None


def kop_number(path=None):
    """{"good", "rated", "n", "day"}: of the wallets with a copyability verdict at a KOP_DELAY s delay (wallets/
    kopirljivost), how many are copyable after the real cost; n = their priced copies. None below KOP_MIN_SOURCES."""
    try:
        from wallets import kopirljivost as K
        p = path or K.db_path()
    except Exception:  # noqa: BLE001
        return None
    con = _ro(p)
    if con is None:
        return None
    try:
        rows = con.execute("SELECT verdict, COUNT(*), SUM(n), MAX(updated) FROM kopirljivost WHERE kind='novcanik' "
                           "AND delay=? AND verdict IN ('kopirljivo', 'nije') GROUP BY verdict", (KOP_DELAY,)).fetchall()
    except sqlite3.Error:
        return None
    finally:
        con.close()
    by = {v: (c or 0, s or 0, u or 0) for v, c, s, u in rows}
    rated = sum(x[0] for x in by.values())
    if rated < KOP_MIN_SOURCES:
        return None
    return {"good": by.get("kopirljivo", (0, 0, 0))[0], "rated": rated, "n": sum(x[1] for x in by.values()),
            "day": time.strftime("%Y-%m-%d", time.gmtime(max(x[2] for x in by.values())))}


def proof(now=None):
    """The three numbers of the proof strip (each may be None); for ui/landing.compute, never on a page view."""
    out = {}
    for key, fn in (("kol", lambda: kol_number(now)), ("toc", toc_number), ("kop", kop_number)):
        try:
            out[key] = fn()
        except Exception as e:  # noqa: BLE001 - one source never costs the others
            print(f"naslovnica: dokaz {key}: {type(e).__name__}: {e}"[:200], flush=True)
            out[key] = None
    return out


# ---------- formatting -------------------------------------------------------------------------------------------

_MON_EN = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def day_text(day, lang):
    try:
        y, m, d = (int(x) for x in day.split("-"))
    except (AttributeError, ValueError):
        return ""
    return f"{d} {_MON_EN[m - 1]} {y}" if lang == "en" else f"{d}. {m}. {y}."


def num(x, lang):
    s = f"{int(x):,}"
    return s if lang == "en" else s.replace(",", ".")


def pct(x, lang):
    return f"{x * 100:.0f}%" if lang == "en" else f"{x * 100:.0f} %"


# ---------- texts ----------------------------------------------------------------------------------------------

T = {
    "hr": dict(
        title="MemeSonar · izmjereni podaci o Solana memecoinima",
        desc="Što su pozivi influencera i novčanici stvarno donijeli nakon troška. Uz svaku ocjenu i njezina izmjerena "
             "točnost. Podaci, ne financijski savjet.",
        pill="Podaci, ne financijski savjet",
        h1="Izmjereni podaci o Solana memecoinima",
        sub="Što su pozivi influencera i novčanici stvarno donijeli, nakon troška. Uz svaku ocjenu piše koliko je "
            "točno pogađala na danima koje nije vidjela.",
        cta1="Provjeri influencera besplatno", cta2="Pogledaj cijene", login="Prijava", app="Otvori aplikaciju",
        prices="Cijene",
        proof_eye="Izmjereno", proof_h="Tri broja iz naših podataka.",
        proof_p="Svaki broj ima veličinu uzorka i datum. Kad uzorak nije dovoljno velik, to i piše.",
        p_kol="poziva influencera bilo je u plusu dan nakon objave, nakon troška od 3 %",
        p_kol_m="n = {n} poziva · zadnjih 30 dana, do {d}",
        p_toc="točnost {name} na danima koje ocjena nije vidjela",
        p_toc_m="n = {n} provjerenih slučajeva · noćna provjera {d}",
        p_kop="izmjerenih novčanika kopirljivo je uz kašnjenje od 30 s, nakon troška",
        p_kop_v="{k} od {m}", p_kop_m="n = {n} kopiranja s cijenom · {d}",
        p_wait="Mjerenje je u tijeku: broj objavljujemo kad uzorak bude dovoljno velik.",
        p_kol_w="poziva influencera u plusu dan kasnije, nakon troška",
        p_toc_w="točnost ocjene na danima koje nije vidjela",
        p_kop_w="novčanika kopirljivo uz kašnjenje, nakon troška",
        prod_eye="Što dobivaš", prod_h="Četiri skupa podataka.",
        prods=[
            ("Influenceri", "Ishod svakog poziva, nakon troška",
             "Za svaki poziv Solana tokena na X-u mjerimo što je cijena stvarno napravila: sat kasnije, dan kasnije i "
             "koliko je tokena završilo kao rug. Kasni pozivi i pozivi nađeni tek nakon rasta se ne broje.",
             [("/hr/influenceri", "Ljestvica influencera"), ("/hr/provjeri-influencera", "Provjeri influencera")]),
            ("Novčanici i osobe", "Tko kupuje prije pumpe",
             "Novčanici i skupine povezanih novčanika koji opetovano kupe prije naglog rasta i prodaju u rast, bundle "
             "novčanici koji pomiču cijenu, i kopirljivost: bi li kopiranje s kašnjenjem od 5 s, 30 s ili 2 min "
             "nakon stvarnog troška bilo u plusu.",
             [("/hr/cijene", "U paketu Pro"), ("/hr/metodologija#novcanici", "Kako mjerimo")]),
            ("Rizik tokena", "Provjera ruga s izmjerenom točnošću",
             "Provjera ruga za svaki praćeni token. Uz presudu piše koliko je takva presuda bila točna u zadnjih 30 "
             "dana, provjereno na kasnijim danima.",
             [("/hr/provjera", "Provjere ruga"), ("/hr/solana-meme-coini", "Top 100 meme coina")]),
            ("pump.fun statistika", "Launchpadi u brojkama",
             "Dnevni volumen pump.funa i drugih Solana launchpada, njihova usporedba i stanje tržišta, osvježeno "
             "svaki dan.",
             [("/hr/solana-launchpadi", "Solana launchpadi"), ("/hr/solana-trziste", "Solana tržište")]),
        ],
        how_eye="Kako mjerimo", how_h="Pošteno, i kad je rezultat loš.",
        how=[("Izvan uzorka", "Točnost ocjene brojimo samo na danima koje ocjena nije vidjela."),
             ("Stvarni trošak", "Kupnja i prodaja s naknadama i utjecajem na cijenu, nikad manje od 3 %."),
             ("Kašnjenje", "Kopiranje mjerimo kao da kasnimo 5 s, 30 s i 2 minute."),
             ("Promašeni ulazi", "Ulaz bez cijene ostaje u statistici kao promašen, ne nestaje.")],
        how_more="Cijela metodologija",
        pr_eye="Cijene", pr_h="Počni besplatno.",
        pr_p="Naplata se uskoro otvara. Prvih 50 pretplatnika dobiva −40 % zauvijek.",
        plans=[("Besplatno", "0 €", "podaci s 24 h zakašnjenja, 3 provjere influencera dnevno, osnovni rizik tokena"),
               ("Pro", "29 €/mj", "svježi podaci, profili osoba, kopirljivost, točnost uz svaku ocjenu, alarmi"),
               ("Pro+", "79 €/mj", "sve iz Pro, API, izvoz CSV, moć poziva skupina influencera")],
        pr_more="Sve cijene i usporedba",
        rq_eye="Tjedni izvještaj", rq_h="Jednom tjedno, samo brojke.",
        rq_p="Što su izmjerili pozivi influencera, novčanici i provjere ruga taj tjedan, s veličinom uzorka. "
             "Izvještaj šaljemo ručno, a e-mail ne dijelimo ni s kim.",
        f_email="E-mail", f_ph="ime@mail.com",
        f_consent="Pristajem da MemeSonar čuva moj e-mail i šalje mi tjedni izvještaj. Odjava jednim odgovorom.",
        f_btn="Prijavi me", f_ok="<b>Prijava je spremljena.</b> Javit ćemo ti se kad pošaljemo prvi izvještaj.",
        f_priv="Bez kartice. Nikad ne tražimo seed frazu ni privatni ključ.",
        faq_h="Pitanja", faq=[
            ("Je li MemeSonar trading bot?", "Nije. MemeSonar ne trguje umjesto tebe i ne obećava zaradu. Nudimo "
             "izmjerene podatke: što su pozivi i novčanici stvarno donijeli u prošlosti, nakon troška."),
            ("Je li ovo financijski savjet?", "Nije. Prikazujemo mjerenja prošlih događaja. Memecoini su vrlo rizični "
             "i odluka je uvijek tvoja."),
            ("Odakle su podaci?", "Iz javnog lanca i licenciranih tržišnih podataka. Sve brojke računamo sami i uz "
             "svaku pišemo veličinu uzorka."),
            ("Koliko košta?", "Osnovno je besplatno. Pro stoji 29 € mjesečno ili 290 € godišnje, Pro+ 79 € mjesečno. "
             "Naplata se uskoro otvara, a do tada se možeš upisati za rani pristup.")],
        foot="Podaci, ne financijski savjet. Kripto nosi visok rizik.",
        flinks=(("Cijene", "/hr/cijene"), ("Metodologija", "/hr/metodologija"),
                ("Provjeri influencera", "/hr/provjeri-influencera")),
        mcta="Provjeri influencera",
    ),
    "en": dict(
        title="MemeSonar · measured data on Solana memecoins",
        desc="What influencer calls and wallets really returned after cost, with the measured accuracy next to every "
             "score. Data, not financial advice.",
        pill="Data, not financial advice",
        h1="Measured data on Solana memecoins",
        sub="What influencer calls and wallets really returned, after cost. Every score shows how often it was right "
            "on days it had not seen.",
        cta1="Check an influencer for free", cta2="See pricing", login="Log in", app="Open the app", prices="Pricing",
        proof_eye="Measured", proof_h="Three numbers from our data.",
        proof_p="Each number comes with its sample size and date. When the sample is too small, it says so.",
        p_kol="of influencer calls were up a day after the post, after a 3% cost",
        p_kol_m="n = {n} calls · last 30 days, up to {d}",
        p_toc="accuracy of {name} on days the score had not seen",
        p_toc_m="n = {n} checked cases · nightly check {d}",
        p_kop="of measured wallets are copyable with a 30 s delay, after cost",
        p_kop_v="{k} of {m}", p_kop_m="n = {n} priced copies · {d}",
        p_wait="Still measuring: we publish the number once the sample is large enough.",
        p_kol_w="of influencer calls up a day later, after cost",
        p_toc_w="accuracy of a score on days it had not seen",
        p_kop_w="of wallets copyable with a delay, after cost",
        prod_eye="What you get", prod_h="Four data sets.",
        prods=[
            ("Influencers", "The outcome of every call, after cost",
             "For every Solana token call on X we measure what the price really did: an hour later, a day later and "
             "how many tokens ended as a rug. Late calls and calls found only after a rise are not counted.",
             [("/influencers", "Influencer ranking"), ("/check-influencer", "Check an influencer")]),
            ("Wallets and people", "Who buys before the pump",
             "Wallets and groups of linked wallets that buy before a sharp rise and sell into it again and again, "
             "bundle wallets that move the price, and copyability: would copying them 5 s, 30 s or 2 min late have "
             "been in profit after the real cost.",
             [("/pricing", "In the Pro plan"), ("/methodology#wallets", "How we measure")]),
            ("Token risk", "A rug check with measured accuracy",
             "A rug check for every tracked token. Next to the verdict it says how often such a verdict was right in "
             "the last 30 days, checked on later days.",
             [("/rug-check", "Rug checks"), ("/solana-meme-coins", "Top 100 meme coins")]),
            ("pump.fun statistics", "Launchpads in numbers",
             "Daily volume of pump.fun and the other Solana launchpads, how they compare and the state of the market, "
             "refreshed every day.",
             [("/solana-launchpads", "Solana launchpads"), ("/solana-market", "Solana market")]),
        ],
        how_eye="How we measure", how_h="Honest, also when the result is bad.",
        how=[("Out of sample", "A score's accuracy is counted only on days the score had not seen."),
             ("Real cost", "Buy and sell with fees and price impact, never less than 3%."),
             ("Delay", "Copying is measured as if we were 5 s, 30 s and 2 minutes late."),
             ("Missed entries", "An entry without a price stays in the numbers as missed; it does not disappear.")],
        how_more="The full methodology",
        pr_eye="Pricing", pr_h="Start for free.",
        pr_p="Billing opens soon. The first 50 subscribers get 40% off for life.",
        plans=[("Free", "€0", "data with a 24 h delay, 3 influencer checks a day, basic token risk"),
               ("Pro", "€29/mo", "fresh data, people profiles, copyability, accuracy next to every score, alerts"),
               ("Pro+", "€79/mo", "everything in Pro, API, CSV export, call power of influencer groups")],
        pr_more="All plans compared",
        rq_eye="Weekly report", rq_h="Once a week, numbers only.",
        rq_p="What influencer calls, wallets and rug checks measured that week, with the sample size. We send the "
             "report by hand and never share your e-mail.",
        f_email="E-mail", f_ph="name@mail.com",
        f_consent="Yes, MemeSonar may keep my e-mail and send me the weekly report. Unsubscribe with one reply.",
        f_btn="Sign me up", f_ok="<b>You are signed up.</b> We will be in touch when the first report goes out.",
        f_priv="No card. We never ask for a seed phrase or private key.",
        faq_h="Questions", faq=[
            ("Is MemeSonar a trading bot?", "No. MemeSonar does not trade for you and promises no profit. We offer "
             "measured data: what calls and wallets really returned in the past, after cost."),
            ("Is this financial advice?", "No. We show measurements of past events. Memecoins are very risky and the "
             "decision is always yours."),
            ("Where does the data come from?", "From the public chain and licensed market data. We compute every "
             "number ourselves and show its sample size."),
            ("How much does it cost?", "The basics are free. Pro is €29 a month or €290 a year, Pro+ €79 a month. "
             "Billing opens soon; until then you can sign up for early access.")],
        foot="Data, not financial advice. Crypto carries a high risk.",
        flinks=(("Pricing", "/pricing"), ("Methodology", "/methodology"), ("Check an influencer", "/check-influencer")),
        mcta="Check an influencer",
    ),
}

CSS = """
.hero.ns{padding:72px 0 8px}.hero.ns h1{max-width:900px}.hero.ns .sub{max-width:680px}
.ns-proof{display:grid;grid-template-columns:repeat(3,1fr);gap:14px}
.ns-proof>div{background:#fff;border:1px solid var(--line);border-radius:20px;padding:22px 20px;text-align:left}
.ns-proof b{display:block;font-size:clamp(30px,4.4vw,42px);letter-spacing:-.03em;font-weight:800;line-height:1.05;
font-variant-numeric:tabular-nums}.ns-proof b.w{color:var(--mut)}
.ns-proof span{display:block;font-size:15px;margin:8px 0 10px;line-height:1.4}
.ns-proof small{display:block;color:var(--mut);font-size:12.5px;line-height:1.4}
.ns-prod{display:grid;grid-template-columns:repeat(2,1fr);gap:16px}
.ns-prod article{background:#fff;border:1px solid var(--line);border-radius:22px;padding:24px}
.ns-prod .k{color:var(--acc);font-weight:700;font-size:13px;text-transform:uppercase;letter-spacing:.06em}
.ns-prod h3{font-size:21px;letter-spacing:-.02em;margin:6px 0 8px;line-height:1.25}
.ns-prod p{margin:0 0 14px;color:var(--mut);font-size:15.5px}
.ns-prod .ln{display:flex;flex-wrap:wrap;gap:6px 18px}.ns-prod .ln a{color:var(--acc);font-weight:620;font-size:15px}
.ns-how{list-style:none;padding:0;margin:0 0 22px;display:grid;grid-template-columns:repeat(4,1fr);gap:14px}
.ns-how li{border-top:3px solid var(--acc);padding:14px 2px 0}.ns-how b{display:block;font-size:16px;margin-bottom:4px}
.ns-how span{color:var(--mut);font-size:15px}
.ns-plans{display:grid;grid-template-columns:repeat(3,1fr);gap:14px;margin-bottom:18px}
.ns-plans div{background:#fff;border:1px solid var(--line);border-radius:20px;padding:20px}
.ns-plans b{display:block;font-size:17px}.ns-plans em{display:block;font-style:normal;font-size:28px;font-weight:800;
letter-spacing:-.02em;margin:4px 0 6px}.ns-plans span{color:var(--mut);font-size:14.5px}
.ns-plans div.hi{border-color:var(--acc);box-shadow:0 20px 50px -30px rgba(79,70,229,.6)}
form.rq .ck{display:flex;gap:10px;align-items:flex-start;font-weight:500;font-size:14px;color:var(--mut)}
form.rq .ck input{width:20px;height:20px;margin:2px 0 0;flex:none;-webkit-appearance:checkbox;appearance:auto}
.ns-foot{display:flex;flex-wrap:wrap;justify-content:center;gap:6px 18px;margin:0 0 12px}.ns-foot a{color:var(--fg)}
.ns-disc{font-weight:650;color:var(--fg)}
@media(max-width:860px){.ns-proof,.ns-plans{grid-template-columns:1fr}.ns-prod{grid-template-columns:1fr}
.ns-how{grid-template-columns:1fr 1fr}}
@media(max-width:480px){.ns-how{grid-template-columns:1fr}.hero.ns{padding:44px 0 0}.ns-proof>div{padding:18px}}
"""

JS = """
const nav=document.querySelector('nav.top'),cta=document.querySelector('.mcta'),form=document.getElementById('pristup');
const tick=()=>{nav.classList.toggle('s',scrollY>8);if(!cta||!form)return;const r=form.getBoundingClientRect();
 cta.classList.toggle('h',scrollY<300||(r.top<innerHeight&&r.bottom>0))};addEventListener('scroll',tick,{passive:true});tick();
"""


def proof_html(lang, d):
    """The three cards of the proof strip from the numbers counted in the background (d: proof() or {})."""
    t = T[lang]
    d = d or {}
    cards = []
    k = d.get("kol")
    if k:
        cards.append((pct(k["share"], lang), t["p_kol"], t["p_kol_m"].format(n=num(k["n"], lang), d=day_text(k["day"], lang))))
    else:
        cards.append(("—", t["p_kol_w"], t["p_wait"]))
    a = d.get("toc")
    if a:
        name = TOC_NAME.get(a["score"], ("ocjene", "the score"))[lang == "en"]
        cards.append((pct(a["acc"], lang), t["p_toc"].format(name=name),
                      t["p_toc_m"].format(n=num(a["n"], lang), d=day_text(a["day"], lang))))
    else:
        cards.append(("—", t["p_toc_w"], t["p_wait"]))
    c = d.get("kop")
    if c:
        cards.append((t["p_kop_v"].format(k=num(c["good"], lang), m=num(c["rated"], lang)), t["p_kop"],
                      t["p_kop_m"].format(n=num(c["n"], lang), d=day_text(c["day"], lang))))
    else:
        cards.append(("—", t["p_kop_w"], t["p_wait"]))
    body = "".join(f"<div><b{' class=w' if v == '—' else ''}>{esc(v)}</b><span>{esc(lab)}</span><small>{esc(m)}</small></div>"
                   for v, lab, m in cards)
    return (f"<section id=dokaz style='padding-top:48px'><div class=w><div class=eyebrow>{t['proof_eye']}</div>"
            f"<h2>{t['proof_h']}</h2><p class=lead>{t['proof_p']}</p><div class=ns-proof>{body}</div></div></section>")


def signup_form(lang, ok=False, err="", form=None, plan="tjedni", action="/cekanje", fid="forma", extra="",
                button=None, src=""):
    """The e-mail + consent form (weekly report on the homepage; the pricing page passes its own plan and fields)."""
    t = T[lang]
    form = form or {}
    msg = f"<div class=ok role=status>{t['f_ok']}</div>" if ok else (f"<div class=err role=alert>{esc(err)}</div>" if err else "")
    em = esc(form.get("email", form.get("contact", "")))
    return (f"<form class=rq method=post action={action} id={fid}>{msg}"
            f"<input type=hidden name=lang value={lang}>"
            + (f"<input type=hidden name=plan value={esc(plan)}>" if plan else "") +
            f"<input type=hidden name=src value=\"{esc((src or '')[:40])}\">{extra}"
            f"<label>{t['f_email']}<input name=email type=email required maxlength=120 autocomplete=email "
            f"value=\"{em}\" placeholder='{t['f_ph']}'></label>"
            f"<label class=ck><input type=checkbox name=consent value=1 required>"
            f"<span>{t['f_consent']}</span></label>"
            "<div class=hp aria-hidden=true><label>Web<input name=web tabindex=-1 autocomplete=off></label></div>"
            f"<button class='btn p' type=submit>{button or t['f_btn']}</button><p class=fine>{t['f_priv']}</p></form>")


def footer_html(lang, name):
    from ui import public as P
    from analytics import ga4
    t = T[lang]
    links = "".join(f"<a href={h}>{esc(lab)}</a>" for lab, h in t["flinks"]) + ga4.settings_link(lang)
    switch = "<a href=/hr hreflang=hr lang=hr>Hrvatski</a>" if lang == "en" else "<a href=/ hreflang=en lang=en>English</a>"
    return (f"<footer><div class=w>{P._foot_links(lang)}<p class=ns-foot>{links}{switch}</p>"
            f"<p style='margin:0'>© {time.gmtime().tm_year} {esc(name)} · <span class=ns-disc>{t['foot']}</span></p>"
            f"</div></footer>")


def page_html(qs=None, logged_in=False, ok=False, err="", form=None, lang="hr", v=None, site_log=""):
    """The whole homepage. v: the numbers of ui/landing.stats() (proof under "dokaz")."""
    from ui import public as P
    from ui import urls
    from ui.landing import CSS as BASE_CSS
    from ui import favicon as _fav
    qs = qs or {}
    lang = "en" if lang == "en" else "hr"
    t = T[lang]
    en = lang == "en"
    home = "/" if en else "/hr"
    svg, name = logo(30)
    base = os.environ.get("RENDER_EXTERNAL_URL", "").rstrip("/")
    app_href, app_label = (urls.app_link("/"), t["app"]) if logged_in else (urls.app_link("/prijava"), t["login"])
    ok = ok or qs.get("prijava") == "ok"
    v = v or {}

    def part(nm, fn, *a):
        try:
            return fn(*a)
        except Exception as e:  # noqa: BLE001 - one block never costs the front page
            print(f"naslovnica: {nm}: {type(e).__name__}: {e}", flush=True)
            return ""

    prods = "".join(
        f"<article><div class=k>{esc(k)}</div><h3>{esc(h)}</h3><p>{esc(p)}</p><div class=ln>"
        + "".join(f"<a href={u}>{esc(lab)} →</a>" for u, lab in links) + "</div></article>"
        for k, h, p, links in t["prods"])
    how = "".join(f"<li><b>{esc(h)}</b><span>{esc(d)}</span></li>" for h, d in t["how"])
    plans = "".join(f"<div{' class=hi' if i == 1 else ''}><b>{esc(n)}</b><em>{esc(p)}</em><span>{esc(d)}</span></div>"
                    for i, (n, p, d) in enumerate(t["plans"]))
    faq = "".join(f"<details><summary>{esc(q)}</summary><p>{esc(a)}</p></details>" for q, a in t["faq"])
    faq_ld = ",".join('{"@type":"Question","name":%s,"acceptedAnswer":{"@type":"Answer","text":%s}}'
                      % (_j(q), _j(a)) for q, a in t["faq"])
    og_img, og_alt = P.og_card("/", lang)
    og_img = base + og_img
    canon = f"{base}{home}"
    switch = (f"<a class=lnk href=/hr hreflang=hr lang=hr>HR</a>" if en else
              f"<a class=lnk href=/ hreflang=en lang=en>EN</a>")
    pricing, check, method = href("pricing", lang), href("check", lang), href("method", lang)
    src = (qs.get("src") or qs.get("utm_source") or "")[:40]
    return f"""<!doctype html><html lang={lang}><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1,viewport-fit=cover"><title>{esc(t['title'])}</title>
<meta name=description content="{esc(t['desc'])}"><link rel=canonical href="{canon}">
<link rel=alternate hreflang=en href="{base}/"><link rel=alternate hreflang=hr href="{base}/hr">
<link rel=alternate hreflang=x-default href="{base}/">
<meta property="og:type" content="website"><meta property="og:title" content="{esc(t['title'])}">
<meta property="og:description" content="{esc(t['desc'])}">{P.og_tags(lang, esc(og_img), og_alt)}
<meta property="og:url" content="{canon}"><meta name="twitter:title" content="{esc(t['title'])}">
<meta name="twitter:description" content="{esc(t['desc'])}">
<meta name=theme-color content="#ffffff">{_fav.HEAD}
<script type="application/ld+json">{{"@context":"https://schema.org","@graph":[{{"@type":"Organization","name":"{esc(name)}",
"url":"{base}/"}},{{"@type":"WebSite","name":"{esc(name)}","url":"{canon}","inLanguage":"{lang}","description":{_j(t['desc'])}}},
{{"@type":"FAQPage","inLanguage":"{lang}","mainEntity":[{faq_ld}]}}]}}</script>
<style>{BASE_CSS}{P._nav_css()}{CSS}</style></head><body>
<nav class=top><div class=w><a class=brand href={home}>{svg}<span>{esc(name)}</span></a><span class=sp></span>
{P.nav_links(lang)}{switch}
<a class=lnk href={app_href}>{app_label}</a><a class='btn p sm' href={pricing}>{t['prices']}</a>{P.mobile_menu(lang)}</div></nav>
<header class='hero ns'><div class=w>
<span class=pill><span class=dot></span>{t['pill']}</span>
<h1>{t['h1']}</h1>
<p class=sub>{t['sub']}</p>
<div class=ctas><a class='btn p' href={check}>{t['cta1']}</a><a class='btn g' href={pricing}>{t['cta2']}</a></div>
</div></header>
{part("dokaz", proof_html, lang, v.get("dokaz"))}

<section id=proizvodi style='padding-top:40px'><div class=w><div class=eyebrow>{t['prod_eye']}</div><h2>{t['prod_h']}</h2>
<div class=ns-prod>{prods}</div></div></section>

<section id=kako class=soft><div class=w><div class=eyebrow>{t['how_eye']}</div><h2>{t['how_h']}</h2>
<ul class=ns-how>{how}</ul><a class=lk href={method}>{t['how_more']} →</a></div></section>

<section id=cijena><div class=w><div class=eyebrow>{t['pr_eye']}</div><h2>{t['pr_h']}</h2><p class=lead>{t['pr_p']}</p>
<div class=ns-plans>{plans}</div><a class=lk href={pricing}>{t['pr_more']} →</a></div></section>

<section id=pristup class=soft><div class='w center'><div class=eyebrow>{t['rq_eye']}</div><h2>{t['rq_h']}</h2>
<p class=lead>{t['rq_p']}</p><div class=req>{signup_form(lang, ok, err, form, src=src)}</div></div></section>
{site_log}
<section><div class=w><div class=faq><h2 class=center style='margin-bottom:24px'>{t['faq_h']}</h2>
{faq}</div></div></section>
{footer_html(lang, name)}
<div class='mcta h'><a class='btn p' href={check}>{t['mcta']}</a></div>
<script>{JS}</script>{P._ga_tag(lang)}</body></html>"""


def _j(s):
    import json
    return json.dumps(s, ensure_ascii=False).replace("</", "<\\/")
