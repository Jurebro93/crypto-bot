"""Public page "Influencer calls today" (15.11., vlasnik: "sve to staviti na javne stranice"), part of ui/marketpub:

  /crypto-influencer-calls     /hr/pozivi-kripto-influencera

How many calls influencers made on X per day (19.11.: Telegram channels are no longer measured, kol/tgout.py) against their own week, how many different callers, how many
of the calls reached +50 % within 24 h, the median market cap at the call, the rug share, how calls do in a cold vs a
hot market, graduated pump.fun tokens we saw per day and how many tokens trade in a range right now.

Only aggregates leave the databases: no handle, no channel, no token, no wallet. Outcomes (the +50 % share, rugs) are
shown only for calls older than 24 h, the same delay as the public influencer pages. Everything is read-only and
computed once per marketpub.snapshot() (CACHE_S), never on a page view. It costs nothing: our own databases only.
"""
import os
import sqlite3
import time

D = 86400
DAYS = 30
HIT_X, X2 = 0.5, 1.0
MULTI = 3                # a token "many called": this many different callers on the same UTC day
MIN_OUT = 8              # a day's outcome share is shown from this many measured first calls


def _ro(path):
    if not path or not os.path.exists(path) or not os.path.getsize(path):
        return None
    return sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=10)


def _median(xs):
    xs = sorted(x for x in xs if x is not None)
    if not xs:
        return None
    m = len(xs) // 2
    return xs[m] if len(xs) % 2 else (xs[m - 1] + xs[m]) / 2


def _x(now, first, regime_of):
    """Per UTC day from kol.db calls (bots left out): activity for every day, outcomes for calls older than 24 h."""
    from ui import public
    con = _ro(public._kol_db())
    if con is None:
        return None
    q = ("SELECT c.ts, c.handle, c.token, c.first_by_kol, c.max24, c.mcap0, c.rug FROM calls c {join} "
         "WHERE c.kind='call' AND c.ts>=? AND c.ts<? AND c.handle NOT LIKE 'tg:%' {bot}")   # 19.11.: X only
    try:
        try:
            rows = con.execute(q.format(join="LEFT JOIN kols k ON k.handle=c.handle", bot="AND COALESCE(k.bot,0)=0"),
                               (first, now)).fetchall()
        except sqlite3.OperationalError:
            rows = con.execute(q.format(join="", bot=""), (first, now)).fetchall()
        grad = {}
        try:
            for day, n in con.execute("SELECT first_seen/86400*86400, COUNT(*) FROM graduates WHERE first_seen>=? "
                                      "AND first_seen<? GROUP BY 1", (first, now)):
                grad[int(day)] = n
        except sqlite3.OperationalError:
            grad = {}
    finally:
        con.close()
    act, per_tok, out, reg = {}, {}, {}, {}
    for ts, handle, token, first_by, max24, mcap0, rug in rows:
        day = int(ts) // D * D
        a = act.setdefault(day, {"calls": 0, "callers": set(), "tokens": set(), "first": 0})
        a["calls"] += 1
        a["callers"].add(handle)
        a["tokens"].add(token)
        per_tok.setdefault((day, token), set()).add(handle)
        if not first_by:
            continue
        a["first"] += 1
        if ts < now - D and max24 is not None:          # measured and old enough to be public
            o = out.setdefault(day, {"n": 0, "hit": 0, "x2": 0, "rug": 0, "mc": []})
            o["n"] += 1
            o["hit"] += max24 >= HIT_X
            o["x2"] += max24 >= X2
            o["rug"] += 1 if rug else 0
            if mcap0:
                o["mc"].append(mcap0)
            lab = regime_of(day)
            if lab:
                r = reg.setdefault(lab, [0, 0])
                r[0] += 1
                r[1] += max24 >= HIT_X
    multi = {}
    for (day, _tok), hs in per_tok.items():
        if len(hs) >= MULTI:
            multi[day] = multi.get(day, 0) + 1
    x = {d: {"calls": a["calls"], "callers": len(a["callers"]), "tokens": len(a["tokens"]), "first": a["first"],
             "multi": multi.get(d, 0)} for d, a in act.items()}
    outs = {d: {"n": o["n"], "hit": o["hit"] / o["n"], "x2": o["x2"] / o["n"], "rug": o["rug"] / o["n"],
                "med_mc": _median(o["mc"])} for d, o in out.items() if o["n"]}
    return {"x": x, "out": outs, "grad": grad,
            "regime": {k: {"n": n, "rate": h / n} for k, (n, h) in reg.items() if n >= 30}}


def _ranges():
    """How many bonded tokens trade in a range right now (rangedca), a number only."""
    try:
        from rangedca import data as rdata
        con = rdata.ro()
    except Exception:  # noqa: BLE001
        con = None
    if con is None:
        return None
    try:
        n, act = con.execute("SELECT COUNT(*), SUM(CASE WHEN active=1 THEN 1 ELSE 0 END) FROM ranges").fetchone()
        return {"total": n or 0, "active": act or 0} if n else None
    except sqlite3.Error:
        return None
    finally:
        con.close()


def _avg(vals):
    vals = [v for v in vals if v is not None]
    return sum(vals) / len(vals) if vals else None


def stats(now=None, regime_of=lambda day: None):
    """Everything the page shows. None when kol.db has no calls yet. `regime_of(day)` -> "hot" | "neutral" | "cold"."""
    now = int(now or time.time())
    today = now // D * D
    first = today - (DAYS + 60) * D            # 90 days for the cold / hot comparison, 30 shown
    x = _x(now, first, regime_of)
    if not x or not x["x"]:
        return None
    full = [d_ for d_ in x["x"] if d_ < today]
    if not full:
        return None
    day = max(full)                             # the last full UTC day that has calls (normally yesterday)
    days = [day - i * D for i in range(DAYS - 1, -1, -1)]
    xs, outs = x["x"], x["out"]

    def wk(get, end, n=7):
        return _avg([get(end - i * D) for i in range(n)])

    calls = lambda d_: (xs.get(d_) or {}).get("calls")          # noqa: E731
    callers = lambda d_: (xs.get(d_) or {}).get("callers")      # noqa: E731
    oday = max((d_ for d_ in outs if d_ <= day - D and outs[d_]["n"] >= MIN_OUT), default=None)

    def pooled(end, n, key):
        ds = [end - i * D for i in range(n) if (end - i * D) in outs]
        tot = sum(outs[d_]["n"] for d_ in ds)
        return sum(outs[d_][key] * outs[d_]["n"] for d_ in ds) / tot if tot >= MIN_OUT else None

    return {
        "day": day, "days": days, "x": xs, "out": outs, "grad": x["grad"], "regime": x["regime"],
        "ranges": _ranges(), "today": xs.get(today), "hours_today": (now - today) / 3600,
        "calls_avg7": wk(calls, day - D), "callers_avg7": wk(callers, day - D),
        "out_day": oday,
        "hit7": pooled(oday, 7, "hit") if oday else None, "hit30": pooled(oday, 30, "hit") if oday else None,
        "x27": pooled(oday, 7, "x2") if oday else None, "rug7": pooled(oday, 7, "rug") if oday else None,
        "rug30": pooled(oday, 30, "rug") if oday else None,
        "mc7": _median([outs[oday - i * D]["med_mc"] for i in range(7) if (oday - i * D) in outs]) if oday else None,
        "mc30": _median([outs[oday - i * D]["med_mc"] for i in range(30) if (oday - i * D) in outs]) if oday else None,
        "n7": sum(outs[oday - i * D]["n"] for i in range(7) if (oday - i * D) in outs) if oday else 0,
    }


# ---------- the page -------------------------------------------------------------------------------------------------

def page(lang):
    from ui import marketnotes as N
    from ui import marketpub as M
    d = M.snapshot()
    c = (d or {}).get("calls")
    if not d or not c:
        return M._empty("calls", lang)
    t, en = M.T[lang], lang == "en"
    day, xs, outs = c["day"], c["x"], c["out"]
    usd, pct, _n = M.usd, M.pct, M._n
    num = lambda v: "–" if v is None else _n(f"{v:,.0f}", lang)      # noqa: E731
    g = lambda a, b: (a / b - 1) if a is not None and b else None    # noqa: E731
    y = xs.get(day) or {}
    ch_calls, ch_callers = g(y.get("calls"), c["calls_avg7"]), g(y.get("callers"), c["callers_avg7"])
    louder = (("busier" if (ch_calls or 0) > 0.1 else "quieter" if (ch_calls or 0) < -0.1 else "about as busy") if en else
              ("glasniji" if (ch_calls or 0) > 0.1 else "tiši" if (ch_calls or 0) < -0.1 else "podjednako glasni"))
    inf = "/influencers" if en else "/hr/influenceri"
    if en:
        h1 = "Crypto influencer calls today"
        lead = (f"On {M._date(day, lang)} the influencers we track made <b>{num(y.get('calls'))} token calls on X</b> "
                f"from {num(y.get('callers'))} different accounts"
                + f": {louder} than their own week"
                + (f" ({pct(ch_calls)})" if ch_calls is not None else "") + "."
                + (f" Of the first calls in the last 7 measured days, <b>{pct(c['hit7'], signed=False)}</b> rose 50%+ "
                   f"at some point within 24 hours." if c["hit7"] is not None else "")
                + f" Who is behind the numbers: <a href={inf}>influencer ranking</a>.")
    else:
        h1 = "Pozivi kripto influencera danas"
        lead = (f"Dana {M._date(day, lang)} influenceri koje pratimo objavili su <b>{num(y.get('calls'))} poziva tokena na X-u</b> "
                f"s {num(y.get('callers'))} različitih računa"
                + f": {louder} nego u svom tjednu"
                + (f" ({pct(ch_calls, lang)})" if ch_calls is not None else "") + "."
                + (f" Od prvih poziva u zadnjih 7 izmjerenih dana, <b>{pct(c['hit7'], lang, signed=False)}</b> je u nekom "
                   f"trenutku unutar 24 sata naraslo 50%+." if c["hit7"] is not None else "")
                + f" Tko stoji iza brojki: <a href={inf}>ljestvica influencera</a>.")
    L = (dict(calls="Calls on X · last full day", callers="Different callers on X",
              hit="First calls that rose 50%+ within 24 h (7 days)", mc="Median market cap at the call (7 days)",
              rug="First calls that ended as a rug (7 days)", multi=f"Tokens called by {MULTI}+ influencers that day",
              grad="Graduated pump.fun tokens we saw", rng="Tokens trading in a range right now", vs7="vs 7-day average",
              vs30="30-day figure", sofar="so far today (UTC)") if en else
         dict(calls="Pozivi na X-u · zadnji puni dan", callers="Različitih callera na X-u",
              hit="Prvi pozivi koji su narasli 50%+ u 24 h (7 dana)", mc="Medijan market capa u trenutku poziva (7 dana)",
              rug="Prvi pozivi koji su završili kao rug (7 dana)", multi=f"Tokeni koje je taj dan zvalo {MULTI}+ influencera",
              grad="Graduirani pump.fun tokeni koje smo vidjeli", rng="Tokeni koji se sada trguju u rasponu",
              vs7="prema prosjeku 7 dana", vs30="vrijednost za 30 dana", sofar="danas dosad (UTC)"))

    def card(v, lab, sub=None, chg=None):
        s = ""
        if chg is not None:
            s = f"<span class=sub><em{M._cls(chg)} style='font-style:normal'>{pct(chg, lang)}</em> {L['vs7']}</span>"
        elif sub:
            s = f"<span class=sub>{sub}</span>"
        return f"<div class=card><b>{v}</b>{s}<span>{lab}</span></div>"

    grad_y = c["grad"].get(day)
    cards = [card(num(y.get("calls")), L["calls"], chg=ch_calls), card(num(y.get("callers")), L["callers"], chg=ch_callers)]
    if c["hit7"] is not None:
        cards.append(card(pct(c["hit7"], lang, signed=False), L["hit"],
                          sub=f"{L['vs30']}: {pct(c['hit30'], lang, signed=False)}" if c["hit30"] is not None else None))
    if c["mc7"]:
        cards.append(card(usd(c["mc7"], lang), L["mc"], sub=f"{L['vs30']}: {usd(c['mc30'], lang)}" if c["mc30"] else None))
    if c["rug7"] is not None:
        cards.append(card(pct(c["rug7"], lang, signed=False, dec=1), L["rug"],
                          sub=f"{L['vs30']}: {pct(c['rug30'], lang, signed=False, dec=1)}" if c["rug30"] is not None else None))
    cards.append(card(num(y.get("multi")), L["multi"]))
    if grad_y:
        cards.append(card(num(grad_y), L["grad"]))
    if c["ranges"]:
        cards.append(card(num(c["ranges"]["active"]), L["rng"]))
    from ops import drustveni   # 19.11. (vlasnik): influencer and Telegram calls refreshed once in 5 days
    body = [M._head("calls", lang, h1, lead, d), M.subnav("calls", lang), drustveni.public_notice(lang),
            f"<div class=cards>{''.join(cards)}</div>"]
    td = c.get("today")
    if td and c["hours_today"] >= 1:
        body.append(f"<p class=mut style='margin:-8px 0 22px'><span class=lvdot></span>{L['sofar']}: <b>{num(td['calls'])}</b> "
                    + ("calls on X from " if en else "poziva na X-u s ") + f"<b>{num(td['callers'])}</b> "
                    + ("accounts" if en else "računa") + ".</p>")
    body.append(N.boxes("calls", d, lang))
    days = c["days"]
    xl = M._xs(days, lang)
    series = [("X: " + ("calls" if en else "pozivi"), M.C1, [(xs.get(x) or {}).get("calls") for x in days], None, None)]
    body.append(M.line_chart("Influencer calls per day (30 days)" if en else "Pozivi influencera po danu (30 dana)",
                             "Token calls on X. Bot accounts are left out. Telegram channels are no longer measured "
                             "(since 19 Nov 2026)."
                             if en else "Pozivi tokena na X-u. Bot računi su izostavljeni. Telegram kanale više ne mjerimo "
                             "(od 19. 11. 2026.).",
                             xl, series, fmt="num", lang=lang))
    odays = [x for x in days if x in outs and outs[x]["n"] >= MIN_OUT]
    if len(odays) >= 5:
        body.append(M.line_chart(
            "Share of first calls that rose 50%+ within 24 h" if en else "Udio prvih poziva koji su narasli 50%+ u 24 h",
            "By the day the call was posted. It is the 24-hour peak: the price touched +50% at some moment, which is not the "
            "same as a profit you could have taken. Calls younger than 24 hours are not shown." if en else
            "Po danu objave poziva. Riječ je o vrhu unutar 24 sata: cijena je u nekom trenutku dotaknula +50%, što nije "
            "isto što i zarada koju si mogao uzeti. Pozivi mlađi od 24 sata nisu prikazani.",
            M._xs(odays, lang), [("+50%", M.C3, [outs[x]["hit"] for x in odays], None, None),
                                 ("2x", M.C4, [outs[x]["x2"] for x in odays], None, None)],
            fmt="pct", lang=lang, ymin=0))
    reg = c["regime"]
    if len(reg) >= 2:
        order = [k for k in ("cold", "neutral", "hot") if k in reg]
        rows = [[t[k].capitalize(), num(reg[k]["n"]), pct(reg[k]["rate"], lang, signed=False)] for k in order]
        body.append(("<h2 class=s>Do calls work better in a hot market?</h2><p class=mut>First calls of the last 90 days, "
                     f"split by the <a href={M.PAGES['season'][0]}>meme coin season index</a> on the day of the call.</p>"
                     if en else
                     "<h2 class=s>Prolaze li pozivi bolje na vrućem tržištu?</h2><p class=mut>Prvi pozivi u zadnjih 90 dana, "
                     f"podijeljeni po <a href={M.PAGES['season'][1]}>indeksu sezone meme coina</a> na dan poziva.</p>")
                    + M._table(["Market" if en else "Tržište", "First calls" if en else "Prvih poziva",
                                "Rose 50%+ in 24 h" if en else "Naraslo 50%+ u 24 h"], rows))
    rows = []
    for x in reversed(days):
        a, o = xs.get(x) or {}, outs.get(x) or {}
        ok = o.get("n", 0) >= MIN_OUT
        rows.append([M._date(x, lang, year=False), num(a.get("calls")), num(a.get("callers")), num(a.get("tokens")),
                     num(a.get("multi")), pct(o.get("hit"), lang, signed=False) if ok else "–",
                     usd(o.get("med_mc"), lang) if ok else "–", num(c["grad"].get(x))])
    body.append(("<h2 class=s>Day by day (30 days)</h2><p class=mut>Full UTC days. Results appear once a call is 24 hours old.</p>"
                 if en else "<h2 class=s>Po danu (30 dana)</h2><p class=mut>Puni UTC dani. Rezultat se vidi kad poziv "
                 "navrši 24 sata.</p>")
                + M._table([t["day"], "X calls" if en else "X pozivi", "Callers" if en else "Calleri",
                            "Tokens" if en else "Tokeni", f"{MULTI}+ callers" if en else f"{MULTI}+ callera",
                            "+50% in 24 h" if en else "+50% u 24 h", "Median mcap" if en else "Medijan mcapa",
                            "Graduated" if en else "Graduirani"], rows))
    body.append(N.locked("calls", lang))
    body.append(M._more("calls", lang))
    if en:
        qa = [("How many calls do crypto influencers make a day?",
               f"On {M._date(day, lang)} the accounts MemeSonar tracks made {num(y.get('calls'))} token calls on X from "
               f"{num(y.get('callers'))} different accounts; their 7-day average is {num(c['calls_avg7'])} a day."),
              ("How many influencer calls actually go up?",
               (f"In the last 7 measured days {pct(c['hit7'], signed=False)} of first calls touched +50% within 24 hours"
                + (f" and {pct(c['x27'], signed=False)} doubled" if c["x27"] is not None else "") + ". That is the peak, "
                "not the result of holding: most of those coins were lower again a day later.") if c["hit7"] is not None
               else "Results appear here once enough calls are 24 hours old."),
              ("What counts as a call?", "A post by a tracked account that names a Solana token (by address or ticker we "
               "could match). Only an account's first call of a token is used for results. Bot accounts are left out."),
              ("Why can't I see which tokens were called?", "The page shows totals only. Which tokens are being called "
               "right now, by whom and how those callers did before is what members see live."),
              ("Where is this data from?", "From MemeSonar's own tracking of crypto influencers on X and "
               "price checks of every called token. Telegram channels are no longer measured (since 19 Nov 2026). It refreshes automatically every 30 minutes.")]
        title = f"Crypto Influencer Calls Today ({M._date(day, lang)}): How Many, How Many Work | MemeSonar"
        desc = (f"{num(y.get('calls'))} token calls on X from {num(y.get('callers'))} influencers on {M._date(day, lang)}"
                + (f", {pct(c['hit7'], signed=False)} of first calls rose 50%+ within 24 h" if c["hit7"] is not None else "")
                + ". Daily counts, hit rate, median market cap and rugs, measured, updated automatically.")
    else:
        qa = [("Koliko poziva dnevno objave kripto influenceri?",
               f"Dana {M._date(day, lang)} računi koje MemeSonar prati objavili su {num(y.get('calls'))} poziva tokena na X-u s "
               f"{num(y.get('callers'))} različitih računa; njihov prosjek kroz 7 dana je {num(c['calls_avg7'])} dnevno."),
              ("Koliko poziva influencera stvarno naraste?",
               (f"U zadnjih 7 izmjerenih dana {pct(c['hit7'], lang, signed=False)} prvih poziva dotaknulo je +50% unutar 24 sata"
                + (f", a {pct(c['x27'], lang, signed=False)} se udvostručilo" if c["x27"] is not None else "") + ". To je vrh, "
                "a ne rezultat držanja: većina tih coina dan kasnije opet je bila niže.") if c["hit7"] is not None
               else "Rezultati se pojave kad dovoljno poziva navrši 24 sata."),
              ("Što se broji kao poziv?", "Objava praćenog računa koja imenuje Solana token (adresom ili tickerom koji smo "
               "mogli spojiti). Za rezultate se uzima samo prvi poziv tokena po računu. Bot računi su izostavljeni."),
              ("Zašto ne vidim koji su tokeni pozvani?", "Stranica pokazuje samo zbrojeve. Koje tokene upravo zovu, tko ih zove "
               "i kako su ti calleri prije prošli, članovi vide uživo."),
              ("Odakle su podaci?", "Iz MemeSonarovog vlastitog praćenja kripto influencera na X-u i provjere "
               "cijene svakog pozvanog tokena. Telegram kanale više ne mjerimo (od 19. 11. 2026.). Osvježava se automatski svakih 30 minuta.")]
        title = f"Pozivi kripto influencera danas ({M._date(day, lang)}): koliko ih je i koliko prolazi | MemeSonar"
        desc = (f"{num(y.get('calls'))} poziva tokena na X-u od {num(y.get('callers'))} influencera, {M._date(day, lang)}"
                + (f"; {pct(c['hit7'], lang, signed=False)} prvih poziva naraslo je 50%+ u 24 h" if c["hit7"] is not None else "")
                + ". Dnevni brojevi, pogodak, medijan market capa i rugovi, izmjereno, osvježava se samo.")
    body.append(M._faq(qa, lang))
    body.append(f"<p class=mut style='margin-top:26px;font-size:13px'>{t['nf_calls']}</p>")
    return M._page("calls", lang, title, desc, "".join(body), qa, d)
