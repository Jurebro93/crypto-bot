"""Tumačenje stranice tokena: pravila pretvaraju brojke u kratke rečenice, engleski i hrvatski (besplatno, bez AI-ja).

explain(d, lang) -> {"lines": [rečenice], "risks": [rizici]}; svaka rečenica navodi broj iz kojeg slijedi. Pragovi su
zapisani ovdje (LIQ_THIN ...), isti za svaki token. Ništa ovdje nije savjet: opisuje što su brojke bile.
"""

LIQ_THIN, LIQ_DEEP = 0.02, 0.08      # liquidity / MC
STEADY, SPORADIC = 0.8, 0.4          # share of the last 30 days with $50k+ volume
CORR_HI, CORR_LO = 0.5, 0.2          # daily correlation with BTC
INSIDER_HI = 30.0                    # % of supply with team + insiders (exchanges and LP not counted; holderi/klasa)
DD_DEEP = -0.8                       # 80 % under the high of our daily history
YOUNG_D = 30
SALE_USD, IMPACT_RISK = 10_000, 3.0  # a $10k sale moving the price 3 %+ is a risk worth naming


def _n(x, lang, nd=1):
    s = f"{x:,.{nd}f}"
    return s.replace(",", "\0").replace(".", ",").replace("\0", ".") if lang == "hr" else s


def usd(x, lang):
    if not x:
        return "–"
    for div, suf in ((1e9, "B"), (1e6, "M"), (1e3, "k")):
        if abs(x) >= div:
            return "$" + _n(x / div, lang) + suf
    return "$" + _n(x, lang, 0)


def pct(x, lang, nd=0, sign=False):
    """x in percent (already x 100)."""
    if x is None:
        return "–"
    s = f"{x:+,.{nd}f}" if sign else f"{x:,.{nd}f}"
    if lang == "hr":
        s = s.replace(",", "\0").replace(".", ",").replace("\0", ".")
    return s + " %"


def share(x, lang, sign=False, nd=0):
    """x a fraction (0.42 -> 42 %); under 10 % with one decimal when nd is None."""
    if x is None:
        return "–"
    if nd is None:
        nd = 1 if abs(x) < 0.1 else 0
    return pct(x * 100, lang, nd, sign)


T = {
    "en": dict(
        size="Market cap {mc} with {liq} of liquidity, {ratio} of the market cap: {how}.",
        thin="a thin pool, a large sale moves the price a lot", ok="a normal pool for its size",
        deep="a deep pool for its size",
        turn="{vol} traded in 24 hours, {turn} of the market cap.",
        steady="Volume was above $50k on {k} of the last {n} days: steady interest.",
        sporadic="Volume was above $50k on only {k} of the last {n} days: interest comes and goes.",
        mid="Volume was above $50k on {k} of the last {n} days.",
        trend="Price change: {c7} in 7 days, {c30} in 30 days{c90}.", c90=", {c} in 90 days",
        ath="The price is {dd} under the highest point of the {n} days we have.",
        rng="On a typical day it moves {med} between its low and high (half of the days between {p25} and {p75}).",
        pos="Right now it stands at {pos} of its 30-day range (0 % = the bottom, 100 % = the top).",
        btc_hi="It follows Bitcoin closely: daily correlation {c}, beta {b} (a 1 % Bitcoin move came with about {b} % "
               "here).",
        btc_mid="It partly follows Bitcoin: daily correlation {c}, beta {b}.",
        btc_lo="It mostly goes its own way: daily correlation with Bitcoin {c}.",
        btc_up="After {n} days when Bitcoin rose 3 % or more, it was higher 72 hours later {hit} of the time.",
        bounce="From the bottom of its 30-day range it bounced {n} times: {hit} reached +15 % within 7 days (median best "
               "{up}, median worst {dn}).",
        cat={"A": "Category A: older than 90 days, steady volume and it follows Bitcoin.",
             "B": "Category B: older than 30 days with fairly steady volume.",
             "C": "Category C: young or with volume that comes and goes."},
        calls="{n} clean influencer and Telegram calls measured: the price was higher one hour later {up} of the time, "
              "{hit} reached +15 % within 24 hours, the median 24-hour result was {med}.",
        calls_none="No clean influencer call of this token has been measured yet.",
        ins="Team and insider wallets hold {x} of the supply (exchanges and pools not counted), the top 10 other "
            "holders {t}.",
        ex="Exchange wallets hold {x} of the supply.",
        listed="Listed on: {names}.", not_listed="Not listed on any of the large exchanges whose lists we read.",
        r_thin="Liquidity {liq}: selling $10k would move the price about {imp} (constant-product estimate).",
        r_ins="High team and insider share ({x}): they can sell into any rise.",
        r_auth="Mint or freeze authority is still active.",
        r_dd="{dd} under its high: a fall like that can continue.",
        r_young="Young token ({d} days): little history to judge from.",
        r_sporadic="Interest comes and goes: volume can dry up quickly.",
        r_rug="{x} of the measured calls of this token ended 90 % or more lower within 24 hours.",
        r_beta="High beta to Bitcoin ({b}): Bitcoin drops hit it harder.",
        r_dep="Supply was recently sent to an exchange that already lists it (possible selling).",
        r_meme="Meme coins are very risky: the price can fall to almost zero.",
    ),
    "hr": dict(
        size="Tržišna vrijednost {mc} uz {liq} likvidnosti, {ratio} tržišne vrijednosti: {how}.",
        thin="tanak pool, veća prodaja jako pomiče cijenu", ok="uobičajen pool za tu veličinu",
        deep="dubok pool za tu veličinu",
        turn="U 24 sata trgovano {vol}, {turn} tržišne vrijednosti.",
        steady="Volumen je bio iznad 50k $ u {k} od zadnjih {n} dana: stalan interes.",
        sporadic="Volumen je bio iznad 50k $ u samo {k} od zadnjih {n} dana: interes dolazi i odlazi.",
        mid="Volumen je bio iznad 50k $ u {k} od zadnjih {n} dana.",
        trend="Promjena cijene: {c7} u 7 dana, {c30} u 30 dana{c90}.", c90=", {c} u 90 dana",
        ath="Cijena je {dd} ispod najviše točke u {n} dana koje imamo.",
        rng="Tipičan dan prijeđe {med} između najniže i najviše cijene (pola dana između {p25} i {p75}).",
        pos="Sada stoji na {pos} svog 30-dnevnog raspona (0 % = dno, 100 % = vrh).",
        btc_hi="Usko prati Bitcoin: dnevna korelacija {c}, beta {b} (pomak Bitcoina od 1 % došao je s oko {b} % ovdje).",
        btc_mid="Djelomično prati Bitcoin: dnevna korelacija {c}, beta {b}.",
        btc_lo="Uglavnom ide svojim putem: dnevna korelacija s Bitcoinom {c}.",
        btc_up="Nakon {n} dana kad je Bitcoin narastao 3 % ili više, 72 sata kasnije bio je viši u {hit} slučajeva.",
        bounce="S dna 30-dnevnog raspona odbio se {n} puta: {hit} je doseglo +15 % unutar 7 dana (medijan najboljeg "
               "{up}, medijan najgoreg {dn}).",
        cat={"A": "Kategorija A: stariji od 90 dana, stalan volumen i prati Bitcoin.",
             "B": "Kategorija B: stariji od 30 dana, prilično stalan volumen.",
             "C": "Kategorija C: mlad ili s volumenom koji dolazi i odlazi."},
        calls="Izmjereno {n} čistih poziva influencera i Telegram kanala: cijena je sat kasnije bila viša u {up} "
              "slučajeva, {hit} je doseglo +15 % unutar 24 sata, medijan rezultata nakon 24 sata {med}.",
        calls_none="Još nije izmjeren nijedan čisti poziv influencera za ovaj token.",
        ins="Novčanici tima i insajdera drže {x} ponude (burze i poolovi se ne broje), ostalih top 10 holdera {t}.",
        ex="Novčanici burzi drže {x} ponude.",
        listed="Na burzama: {names}.", not_listed="Nije na nijednoj od velikih burzi čije liste čitamo.",
        r_thin="Likvidnost {liq}: prodaja od 10k $ pomaknula bi cijenu oko {imp} (procjena za AMM pool).",
        r_ins="Velik udio tima i insajdera ({x}): mogu prodavati u svaki rast.",
        r_auth="Mint ili freeze ovlast je još aktivna.",
        r_dd="{dd} ispod vrha: takav pad se može nastaviti.",
        r_young="Mlad token ({d} dana): malo povijesti za procjenu.",
        r_sporadic="Interes dolazi i odlazi: volumen može brzo presušiti.",
        r_rug="{x} izmjerenih poziva ovog tokena završilo je 90 % ili više niže unutar 24 sata.",
        r_beta="Visoka beta prema Bitcoinu ({b}): padovi Bitcoina jače ga pogađaju.",
        r_dep="Ponuda je nedavno poslana na burzu koja ga već lista (moguća prodaja).",
        r_meme="Meme coini su vrlo rizični: cijena može pasti gotovo na nulu.",
    ),
}


def explain(d, lang):
    t = T[lang]
    L, R = [], []
    nw, m, rg = d.get("now") or {}, d.get("m") or {}, d.get("range") or {}
    mc, liq, vol = nw.get("mcap"), nw.get("liq"), nw.get("vol24")
    if mc and liq:
        ratio = liq / mc
        how = t["thin"] if ratio < LIQ_THIN else t["deep"] if ratio > LIQ_DEEP else t["ok"]
        L.append(t["size"].format(mc=usd(mc, lang), liq=usd(liq, lang), ratio=share(ratio, lang, nd=None), how=how))
        imp = SALE_USD / (liq / 2) * 100     # a sale into one side of a constant-product pool, as a share of it
        if imp >= IMPACT_RISK:
            R.append(t["r_thin"].format(liq=usd(liq, lang), imp=pct(imp, lang, 1)))
    if mc and vol:
        L.append(t["turn"].format(vol=usd(vol, lang), turn=share(vol / mc, lang, nd=None)))
    p30 = m.get("pers30")
    if p30 is not None:
        n = min(30, int(m.get("days_history") or 30))
        k = round(p30 * n)
        key = "steady" if p30 >= STEADY else "sporadic" if p30 < SPORADIC else "mid"
        L.append(t[key].format(k=k, n=n))
        if p30 < SPORADIC:
            R.append(t["r_sporadic"])
    ch = d.get("chg") or {}
    if ch.get("7d") is not None or ch.get("30d") is not None:
        c90 = t["c90"].format(c=pct(ch["90d"], lang, 0, True)) if ch.get("90d") is not None else ""
        L.append(t["trend"].format(c7=pct(ch.get("7d"), lang, 0, True), c30=pct(ch.get("30d"), lang, 0, True), c90=c90))
    dd = m.get("dd_ath")
    if dd is not None and m.get("days_history"):
        L.append(t["ath"].format(dd=pct(-dd * 100, lang), n=m["days_history"]))
        if dd <= DD_DEEP:
            R.append(t["r_dd"].format(dd=pct(-dd * 100, lang)))
    if rg:
        L.append(t["rng"].format(med=pct(rg["med"], lang, 1), p25=pct(rg["p25"], lang, 1), p75=pct(rg["p75"], lang, 1)))
        if rg.get("pos30") is not None:
            L.append(t["pos"].format(pos=pct(rg["pos30"], lang)))
    c, b = m.get("corr_d"), m.get("beta_d")
    if c is not None:
        key = "btc_hi" if c >= CORR_HI else "btc_mid" if c >= CORR_LO else "btc_lo"
        L.append(t[key].format(c=_n(c, lang, 2), b=_n(b or 0, lang, 1)))
        if c >= CORR_LO and (b or 0) >= 2.5:
            R.append(t["r_beta"].format(b=_n(b, lang, 1)))
    if m.get("btc_up_n") and m.get("btc_up_hit") is not None:
        L.append(t["btc_up"].format(n=m["btc_up_n"], hit=share(m["btc_up_hit"], lang)))
    if m.get("bounce_n"):
        L.append(t["bounce"].format(n=m["bounce_n"], hit=share(m.get("hit15"), lang), up=pct(m.get("med_up7"), lang, 0, True),
                                    dn=pct(m.get("med_dn7"), lang, 0, True)))
    if m.get("cat") in t["cat"]:
        L.append(t["cat"][m["cat"]])
    cs = (d.get("calls") or {}).get("stats") or {}
    if cs.get("n"):
        L.append(t["calls"].format(n=cs["n"], up=share(cs.get("up1h"), lang), hit=share(cs.get("hit15"), lang),
                                   med=share(cs.get("med24"), lang, True)))
        if (cs.get("rug") or 0) >= 0.2 and cs["n"] >= 3:
            R.append(t["r_rug"].format(x=share(cs["rug"], lang)))
    else:
        L.append(t["calls_none"])
    h = d.get("holders") or {}
    if h.get("insider_ex") is not None:
        L.append(t["ins"].format(x=pct(h["insider_ex"], lang, 1), t=pct(h.get("top10_ex") or 0, lang, 1)))
        if h["insider_ex"] > INSIDER_HI:
            R.append(t["r_ins"].format(x=pct(h["insider_ex"], lang)))
    exs = (h.get("shares") or {}).get("exchange")
    if exs:
        L.append(t["ex"].format(x=pct(exs, lang, 1)))
    rc = h.get("rc") or {}
    jp = h.get("jup") or {}
    if rc.get("mint_auth") or rc.get("freeze_auth") or jp.get("mint_off") is False or jp.get("freeze_off") is False:
        R.append(t["r_auth"])
    listed = [x["ex"] for x in d.get("listing") or [] if x["st"] == "da"]
    if listed:
        L.append(t["listed"].format(names=", ".join(listed)))
    elif d.get("listing") and any(x["st"] != "nepoznato" for x in d["listing"]):
        L.append(t["not_listed"])
    if any(s["kind"] == "deposit_sell" for s in (d.get("lsig") or {}).get("list") or []):
        R.append(t["r_dep"])
    age = m.get("age_d")
    if age is not None and age < YOUNG_D:
        R.append(t["r_young"].format(d=int(age)))
    R.append(t["r_meme"])
    return {"lines": L, "risks": R}
