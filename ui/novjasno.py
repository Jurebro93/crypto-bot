"""The plain-words layer of /novcanici-admin (20.11., vlasnik na mobitelu: "Nista ja ovdje ne razumijem..."): the
app's rule since 10.11. (one clear answer first, rows instead of cards, details one tap away) on the owner's wallet
page. Presentation and wording only: every number comes from what ui/novpodaci.py / league/mjera.py already read.

  headline(con, pp, now)   the three answers: "Što smo našli", "Isplati li se kopirati ih", "Što alat sada radi i što
                           slijedi" (each {"tone", "text"}), computed from the stored numbers, plurals right
  ranked(con, n, offset)   the groups best first (confirmed, then pump tokens worth 15 M $ or more, then profit)
  cards_html(con, gs, now) one card per group, in sentences (a line whose data is missing is left out)
  excluded_text(ex)        who was left out and why, one paragraph with counts
  mjera_sentence(st, ...)  one sentence about the per-entry measurement (the Autopilot section uses it too)

Read-only, no network. Wording rules: second person, short sentences, Croatian only, "novčanik ili skupina novčanika"
the first time and "skupina" after, numbers in the app's own format (ui/redak.num), dates "19.11.", times "prije 2 h".
"""
import re
import time
from urllib.parse import quote

from ui import novkartice as K
from ui import novpodaci as P
from ui import redak as rd

TOP_N = 10
ALL_N = 20
NEED_TOKENS = 3


# ---------- words ------------------------------------------------------------------------------------------------------

def plural(n, one, few, many):
    """Croatian noun form for a count: 1 / 21 -> one, 2-4 / 22-24 -> few, the rest -> many."""
    try:
        n = abs(int(round(float(n))))
    except (TypeError, ValueError):
        return many
    if n % 10 == 1 and n % 100 != 11:
        return one
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return few
    return many


def cnt(n, one, few, many):
    """"3 tokena", "1 token", "1 234 novčanika" (the app's number format)."""
    return f"{rd.num(n)} {plural(n, one, few, many)}"


def join(parts):
    parts = [p for p in parts if p]
    if len(parts) <= 1:
        return "".join(parts)
    return ", ".join(parts[:-1]) + " i " + parts[-1]


def when_lead(minutes):
    """Median lead in a human unit: "oko 25 minuta", "oko 3 sata", "oko 2 dana"; None when unknown."""
    if minutes is None:
        return None
    m = max(0.0, float(minutes))
    if m < 90:
        n = max(1, round(m))
        return f"oko {n} {plural(n, 'minutu', 'minute', 'minuta')}"
    if m < 36 * 60:
        n = round(m / 60)
        return f"oko {n} {plural(n, 'sat', 'sata', 'sati')}"
    n = round(m / 1440)
    return f"oko {n} {plural(n, 'dan', 'dana', 'dana')}"


def about_sol(x):
    """"oko 2 SOL", "oko 0,4 SOL" (absolute value; the caller says won or lost)."""
    v = abs(float(x))
    n = rd.num(v, 1 if v < 10 else 0)
    return f"oko {n[:-2] if n.endswith(',0') else n} SOL"


def pct_plain(x, sign=True):
    """A percent in the app's format, one decimal ("+3,4 %")."""
    return rd.pct(x, 1, sign=sign)


def day(ts):
    return time.strftime("%d.%m.", time.localtime(int(ts))).lstrip("0").replace(".0", ".") if ts else ""


# ---------- 1. what we found ---------------------------------------------------------------------------------------------

def _counts(con):
    r = P.q(con, "SELECT SUM(cls='prije_pumpe'), SUM(cls='prije_pumpe' AND confirmed_ts IS NOT NULL), "
                 "SUM(cls='kandidat') FROM i2_pp")
    n, c, k = (r[0] if r else (0, 0, 0))
    return int(n or 0), int(c or 0), int(k or 0)


def found(con, pp):
    n, c, k = _counts(con)
    need = int((pp or {}).get("min_tokens") or NEED_TOKENS)
    if not n:
        seen = int((pp or {}).get("covered15") or 0) + int((pp or {}).get("covered2") or 0)
        total = int((pp or {}).get("pumps15") or 0) + int((pp or {}).get("pumps2") or 0)
        if not pp:
            text = "Još tražimo. Prvo pretraživanje je noćas, od 1 do 6 sati."
        else:
            text = (f"Još tražimo. Pregledali smo {rd.num(seen)} od {rd.num(total)} "
                    f"{plural(total, 'tokena', 'tokena', 'tokena')} koji su skočili, i još nismo našli novčanik ili "
                    f"skupinu novčanika koja je barem {need} puta kupila prije skoka i prodala dok je rastao.")
        if k:
            text += f" {cnt(k, 'skupina je', 'skupine su', 'skupina je')} blizu: {plural(k, 'ima', 'imaju', 'ima')} dva takva tokena i čeka treći."
        return {"tone": "warn", "text": text}
    one = n % 10 == 1 and n % 100 != 11
    what = "novčanik ili skupinu novčanika" if one else "novčanika ili skupina novčanika"
    verb = "koji je" if n == 1 else "koji su"
    did = "kupio" if n == 1 else "kupili"
    sold = "prodao" if n == 1 else "prodali"
    text = (f"Našli smo {rd.num(n)} {what} {verb} barem {need} puta {did} token prije nego što je skočio i {sold} dok "
            "je rastao.")
    if c:
        text += f" Za {rd.num(c)} od njih to se ponovilo i na novijim podacima."
    else:
        text += " Ni za jednu skupinu se to još nije ponovilo na novijim podacima."
    if k:
        text += f" Još {cnt(k, 'skupina ima', 'skupine imaju', 'skupina ima')} dva takva tokena i čeka treći."
    return {"tone": "good" if c else "warn", "text": text}


# ---------- 2. does it pay ----------------------------------------------------------------------------------------------

def copy_verdict(pp):
    """(tone, sentence, word) from the stored copy test: word is "da", "zasad da", "zasad ne", "ne znamo"."""
    pp = pp or {}
    prog = pp.get("copy_progress")
    cp = pp.get("copy") if isinstance(pp.get("copy"), dict) else None
    if prog:
        m = re.search(r"izračunato do (\d+\.\d+\.)", str(prog))
        upto = m.group(1).lstrip("0").replace(".0", ".") if m else None
        return "warn", ("Još ne znamo: test još nije gotov" + (f" (izračunato do {upto})." if upto else ".")), "ne znamo"
    if not cp:
        return "warn", "Još ne znamo: test kopiranja još nije napravljen, prvi rezultat stiže nakon noćne obrade.", \
            "ne znamo"
    a = ((cp.get("60s") or {}).get("svi") or {}) if isinstance(cp.get("60s"), dict) else {}
    need = int(pp.get("min_n") or 20)
    n = int(a.get("n") or 0)
    if n < need:
        return "warn", f"Još ne znamo: premalo primjera ({rd.num(n)}, treba {rd.num(need)}).", "ne znamo"
    ev, lo, hi = a.get("ev_pct"), a.get("lo_pct"), a.get("hi_pct")
    if ev is None:
        return "warn", "Još ne znamo: nema izmjerenih kupnji.", "ne znamo"
    if lo is None or hi is None:
        return "warn", (f"Još ne znamo: u prosjeku {pct_plain(ev)} po kupnji nakon troška, ali primjeri su s premalo "
                        "različitih tokena da bismo znali raspon."), "ne znamo"
    if lo > 0:
        return "good", (f"Da: {pct_plain(ev)} po kupnji nakon troška, i u najlošijem slučaju iz raspona iznad nule."), "da"
    if ev <= 0 or hi < 0:
        return "bad", (f"Zasad ne: kopiranje bi u prosjeku gubilo {pct_plain(abs(ev), sign=False)} po kupnji nakon "
                       "troška."), "zasad ne"
    return "warn", (f"Zasad da: u prosjeku {pct_plain(ev)} po kupnji nakon troška, ali raspon još dira nulu."), "zasad da"


MJERA_SOURCES = ("prije_pumpe", "prije_pumpe_kandidat")


def mjera_stats(sources=MJERA_SOURCES, now=None):
    """(stats, first seen_ts) of league/mjera's rows of the given sources over its 30 days; (None, None) without
    the table."""
    try:
        from league import mjera
        con = P.ro(P.league_db())
        if con is None or not P.has_table(con, "signal_mjera"):
            if con is not None:
                con.close()
            return None, None
        try:
            now = int(now or time.time())
            rows = [r for r in mjera._rows(con, since=now - 30 * 86400) if not sources or r["source"] in sources]
            first = min((r["seen_ts"] for r in rows if r.get("seen_ts")), default=None)
            return mjera.stats(rows), first
        finally:
            con.close()
    except Exception:  # noqa: BLE001
        return None, None


def mjera_sentence(st, first, who="praćenih novčanika", live=False):
    """One sentence about the per-entry measurement: what was measured since when, the mean, the verdict in words."""
    from league import mjera
    who = f" {who}" if who else ""
    if not st or not st.get("signals"):
        return f"Uživo još nismo zabilježili nijednu njihovu kupnju." if not who else \
            f"Uživo još nismo zabilježili nijednu kupnju{who}."
    word = "uživo " if live else ""
    lead = f"Od {day(first)} smo {word}" if first else f"{'Uživo' if live else 'Do sada'} smo "
    m = int(st.get("measured") or 0)
    if not m:
        return (f"{lead}zabilježili {cnt(st['signals'], 'kupnju', 'kupnje', 'kupnji')}{who}; nijedna još nije "
                "zatvorena, pa rezultata još nema.")
    head = (f"{lead}izmjerili {cnt(m, 'kupnju', 'kupnje', 'kupnji')}{who}: u prosjeku "
            f"{pct_plain((st.get('mean01') or 0) * 100)} po kupnji nakon troška.")
    v = mjera.verdict(st)
    need = mjera.MIN_TOKEN_DAYS
    if v.startswith("premalo"):
        tail = (f" Premalo je za zaključak (treba {rd.num(need)} dana s kupnjama, sada "
                f"{rd.num(st.get('token_days') or 0)}).")
    elif v == "u plusu":
        tail = " To je dokazano: i u najlošijem slučaju iz raspona iznad nule."
    elif v == "u minusu":
        tail = " To je dokazano u minusu: i u najboljem slučaju iz raspona ispod nule."
    else:
        tail = " Još nije dokazano: raspon u kojem je pravi rezultat vjerojatno još dira nulu."
    return head + tail


def pays(pp, now=None):
    tone, text, word = copy_verdict(pp)
    st, first = mjera_stats(now=now)
    live = mjera_sentence(st, first, "", live=True) if st is not None else ""
    paused = P.pause_on()
    if word == "da":
        money = ("Pravi novac je pauziran; kopiranje pravim novcem možeš uključiti samo ti." if paused else
                 "Pravi novac ih kopira tek kad ti to uključiš.")
    else:
        money = ("Pravi novac ostaje pauziran dok ovo ne bude „Da”." if paused else
                 "Pravi novac ih ne kopira dok ovo ne bude „Da”.")
    return {"tone": tone, "text": " ".join(x for x in (text, live, money) if x), "word": word}


# ---------- 3. what now --------------------------------------------------------------------------------------------------

def _night(now):
    h = time.localtime(int(now)).tm_hour
    return "Upravo (do 6 sati ujutro)" if 1 <= h < 6 else "Noćas, od 1 do 6 sati,"


def what_now(con, pp, now, verdict_word=None, birdeye=None):
    n, c, k = _counts(con) if con is not None else (0, 0, 0)
    st = P.povijest_status(now=now)
    wait = sum(int(v or 0) for v in ((st or {}).get("queue") or {}).values()) if st else 0
    lead = _night(now)
    if not pp and not n:
        doing = (f"{lead} prvi put pregledava tokene koji su skočili i traži tko je kupio prije skoka. Ujutro ovdje "
                 "piše što je našao.")
    else:
        bits = []
        if wait:
            bits.append(f"čita povijest još {cnt(wait, 'novčanika', 'novčanika', 'novčanika')}")
        bits.append("traži nove skupine u tokenima koji su skočili")
        doing = f"{lead} {join(bits)}."
        if n + k:
            doing += (f" Cijelo vrijeme prati nove kupnje {'te' if n + k == 1 else 'svih'} "
                      f"{cnt(n + k, 'skupine', 'skupine', 'skupina')}.")
        w = verdict_word or copy_verdict(pp)[2]
        prog = (pp or {}).get("copy_progress") or not (pp or {}).get("copy")
        if w == "ne znamo" and prog:
            doing += " Sutra ujutro ovdje će pisati isplati li se kopirati ih."
        elif w == "ne znamo":
            doing += " Svaku noć dodaje nove primjere; odgovor stiže kad ih bude dovoljno."
        else:
            doing += " Svaku noć ponovno provjerava odgovor s novim podacima."
    needs = []
    if (verdict_word or copy_verdict(pp)[2]) == "da":
        needs.append("odluči želiš li kopiranje ovih skupina pravim novcem; to možeš uključiti samo ti")
    if birdeye is not None and not birdeye.get("key") and not birdeye.get("calls"):
        needs.append("ako želiš drugu provjeru novčanika iz drugog izvora (Birdeye), treba postaviti njegov ključ na "
                     "serveru")
    you = ("Što trebaš napraviti ti: " + "; ".join(needs) + ".") if needs else "Od tebe sada ne treba ništa."
    return {"tone": "warn" if needs else "", "text": doing + " " + you}


def headline(con, pp, now, birdeye=None):
    f = found(con, pp)
    p = pays(pp, now)
    w = what_now(con, pp, now, p["word"], birdeye)
    return {"found": f, "pays": p, "next": w}


def headline_html(hd):
    def block(title, d):
        tone = {"good": "nj-good", "bad": "nj-bad", "warn": "nj-warn"}.get(d.get("tone"), "")
        return (f'<div class="nj-a {tone}"><h3>{rd.h(title)}</h3><p>{rd.h(d["text"])}</p></div>')
    return ('<div class=nj-head>' + block("Što smo našli", hd["found"]) + block("Isplati li se kopirati ih", hd["pays"])
            + block("Što alat sada radi i što slijedi", hd["next"]) + '</div>'
            '<p class=nj-how>Kako čitati ovu stranicu: zeleno = dobro za nas, narančasto = još ne znamo, crveno = loše. '
            'Sve brojke su iz javnih podataka s lanca; statistika, ne optužba.</p>')


# ---------- the cards ------------------------------------------------------------------------------------------------------

def ranked(con, limit=TOP_N, offset=0):
    """The groups best first: confirmed, then pumps of tokens worth 15 M $ or more, then profit."""
    rows = P.q(con, f"SELECT {', '.join(P.GKEYS)} FROM i2_pp WHERE cls IN ('prije_pumpe', 'kandidat') ORDER BY "
                    "(confirmed_ts IS NULL), (cls != 'prije_pumpe'), COALESCE(n_pumps15, 0) DESC, "
                    "COALESCE(pnl_sol, -1e9) DESC, owner LIMIT ? OFFSET ?", (int(limit), int(offset)))
    return [P._group(r) for r in rows]


def shown_count(con):
    r = P.q(con, "SELECT COUNT(*) FROM i2_pp WHERE cls IN ('prije_pumpe', 'kandidat')")
    return int(r[0][0] or 0) if r else 0


def _birdeye_of(con, owners):
    if not owners or not P.has_table(con, "be_pp"):
        return {}
    return {o: (int(c or 0), int(s or 0)) for o, c, s in P.q(
        con, f"SELECT owner, n_checked, n_seen FROM be_pp WHERE owner IN ({','.join('?' * len(owners))})", owners)}


def _history_of(gs):
    """{owner: (n scored, n members, closed, win share, realized SOL)} from the members' own scored history."""
    members = [w for g in gs for w in g["members"][:60]]
    try:
        rows, ok = P.wallet_history(members, extra_top=0)
    except Exception:  # noqa: BLE001
        return {}
    by = {r["wallet"]: r for r in rows if r.get("scored")}
    out = {}
    for g in gs:
        sc = [by[w] for w in g["members"][:60] if w in by]
        if not sc:
            continue
        closed = sum(int(r.get("closed") or 0) for r in sc)
        wins = sum(float(r.get("win_rate") or 0) * int(r.get("closed") or 0) for r in sc)
        real = sum(float(r.get("realized") or 0) for r in sc)
        out[g["owner"]] = (len(sc), len(g["members"]), closed, (wins / closed) if closed else None, real)
    return out


def _tokens(ps):
    """[(symbol, tier)] distinct tokens of a group's pumps, 15 M $+ first."""
    seen = {}
    for p in ps:
        t = p.get("token")
        if not t:
            continue
        big = p.get("tier") == "pumpa15"
        if t not in seen or big:
            seen[t] = (p.get("symbol") or K.short(t), big or (seen.get(t, (None, False))[1]))
    return sorted(seen.values(), key=lambda x: (not x[1], str(x[0])))


def card_sentences(g, ps, hist=None, be=None, mj=None):
    """The card's sentences (plain text, escaped by the caller): [main, history, Birdeye, measurement] without the
    lines whose data is missing."""
    one = len(g["members"]) <= 1
    toks = _tokens(ps)
    n_tok = int(g.get("n_tokens") or len(toks) or 0)
    n15 = sum(1 for _s, big in toks if big) if toks else int(g.get("n_pumps15") or 0)
    names = list(dict.fromkeys(s for s, _b in toks))[:5]   # two tokens can share a name: shown once
    rest = max(0, n_tok - len(names))
    where = "na jednom tokenu" if n_tok == 1 else f"na {rd.num(n_tok)} tokena"
    lst = (": " + ", ".join(names) + (f" i još {rd.num(rest)}" if rest and names else "")) if names else ""
    verb = plural(n15, "vrijedio je", "vrijedila su", "vrijedilo je")
    big = (f" ({rd.num(n15)} od njih {verb} 15 M $ ili više)" if n15 and n_tok > 1 else
           " (vrijedio je 15 M $ ili više)" if n15 else "")
    s1 = f"{'Kupio je' if one else 'Skupina je kupila'} prije skoka {where}{lst}{big}."
    if g.get("cls") == "kandidat":
        s1 += f" {'Treba mu' if one else 'Treba joj'} još jedan takav token da uđe na popis."
    lead = when_lead(g.get("med_lead_min"))
    if lead:
        s1 += f" U prosjeku {'je kupovao' if one else 'su kupovali'} {lead} prije skoka."
    pnl = g.get("pnl_sol")
    if pnl is None:
        s1 += f" Koliko {'je' if one else 'su'} na tim tokenima {'zaradio' if one else 'zaradili'}, nepoznato je."
    elif pnl >= 0:
        s1 += f" Na tim {'je' if one else 'su'} tokenima {'zaradio' if one else 'zaradili'} {about_sol(pnl)}."
    else:
        s1 += f" Na tim {'je' if one else 'su'} tokenima {'izgubio' if one else 'izgubili'} {about_sol(pnl)}."
    out = [s1]
    if hist:
        n_sc, n_m, closed, win, real = hist
        if closed:
            who = "Njegova cijela povijest" if one else (
                "Cijela povijest novčanika u skupini" + (f" (izračunata za {rd.num(n_sc)} od {rd.num(n_m)})"
                                                         if n_sc < n_m else ""))
            out.append(f"{who}: {cnt(closed, 'zatvoren trade', 'zatvorena tradea', 'zatvorenih tradeova')}, "
                       f"{rd.pct(win, 0, sign=False, frac=True)} u plusu, ukupno {rd.sol(real, 1 if abs(real) < 10 else 0, sign=True)}.")
    if be and be[0]:
        of = f"{rd.num(be[0])} {plural(be[0], 'provjerenog tokena', 'provjerena tokena', 'provjerenih tokena')}"
        out.append(f"Druga provjera (Birdeye): među najboljim trgovcima na {rd.num(be[1])} od {of}." if be[1] else
                   f"Druga provjera (Birdeye): nije među najboljim trgovcima ni na jednom od {of}.")
    if mj and mj.get("n"):
        m = int(mj.get("measured") or 0)
        buys = cnt(mj["n"], "nova kupnja", "nove kupnje", "novih kupnji")
        if m and mj.get("mean01") is not None:
            out.append(f"Od kad {'ga' if one else 'ih'} pratimo: {buys}, prosjek {pct_plain(mj['mean01'] * 100)} nakon troška"
                       + (f" (zatvoreno {rd.num(m)})" if m < mj["n"] else "") + ".")
        else:
            out.append(f"Od kad {'ga' if one else 'ih'} pratimo: {buys}, još nijedna nije zatvorena.")
    return out


def _pump_lines(ps):
    out = []
    for p in ps[:30]:
        tok = p.get("token") or ""
        sym = rd.h(p.get("symbol") or K.short(tok))
        lead = p.get("lead_s")
        if lead is None and p.get("buy_ts") and p.get("t0"):
            lead = p["t0"] - p["buy_ts"]
        when = when_lead(lead / 60) + " prije skoka" if lead is not None and lead >= 0 else "nakon početka skoka"
        sold = ("prodao u rastu" if p.get("sold_into") else "nije prodao u rastu")
        put = f", uložio {rd.h(rd.sol(p.get('sol_in'), 2))}" if p.get("sol_in") is not None else ""
        big = " · 15 M $ ili više" if p.get("tier") == "pumpa15" else ""
        out.append(f'<li><a href="/token/{quote(tok)}" translate=no>{sym}</a>{big}: kupio {rd.h(when)}{put}, '
                   f'{rd.h(sold)} <span class=mut>({rd.h(time.strftime("%d.%m.", time.localtime(int(p["t0"]))) if p.get("t0") else "")})</span></li>')
    more = f'<li class=mut>i još {rd.num(len(ps) - 30)}</li>' if len(ps) > 30 else ""
    return f'<ul class=nj-l>{"".join(out)}{more}</ul>' if out else ""


def _addr(w):
    return (f'<code translate=no title="{rd.h(w)}">{rd.h(K.short(w) if len(w) > 14 else w)}</code>'
            f'<button type=button class=nk-cp data-cp="{rd.h(w)}" aria-label="Kopiraj adresu">Kopiraj</button>'
            f'<a class=nj-x href="https://solscan.io/account/{quote(w)}" target=_blank rel="noopener noreferrer">Solscan ↗</a>')


def cards_html(con, gs, now, mj=None):
    if not gs:
        return ""
    owners = [g["owner"] for g in gs]
    pumps = P.pumps_of(con, owners)
    hist = _history_of(gs)
    be = _birdeye_of(con, owners)
    mj = mj or {}
    out = []
    for g in gs:
        ms = g["members"] or [g["owner"]]
        first = ms[0]
        conf = bool(g.get("confirmed_ts"))
        badge = ('<span class="nj-b good">potvrđen</span>' if conf else '<span class="nj-b warn">čeka potvrdu</span>')
        ss = card_sentences(g, pumps.get(g["owner"], []), hist.get(g["owner"]), be.get(g["owner"]), mj.get(g["owner"]))
        more = len(ms) - 1
        links = ""
        if more > 0:
            from ui import novadmin
            lis = "".join(f'<li>{_addr(w)}</li>' for w in ms[1:60])
            links = (f'<details class=nj-d><summary>Povezan s još {cnt(more, "novčanikom", "novčanika", "novčanika")}'
                     f'</summary><ul class=nj-l>{lis}</ul>'
                     + (f'<p class=mut>i još {rd.num(len(ms) - 60)}</p>' if len(ms) > 60 else "")
                     + f'<p class=nj-s>Što ih povezuje:</p>{novadmin._links_html(P.links(con, ms[:60]), ms)}</details>')
        ps = pumps.get(g["owner"], [])
        tokens = (f'<details class=nj-d><summary>Svaki token posebno ({rd.num(len(ps))})</summary>{_pump_lines(ps)}'
                  f'</details>') if ps else ""
        out.append(f'<article class=nj-c><div class=nj-ch>{_addr(first)}{badge}</div>'
                   f'<p>{rd.h(ss[0])}</p>' + "".join(f'<p class=nj-m>{rd.h(s)}</p>' for s in ss[1:])
                   + links + tokens + '</article>')
    return '<div class=nj-cards>' + "".join(out) + '</div>'


# ---------- who was left out ------------------------------------------------------------------------------------------------

def _one(n):
    try:
        n = int(n)
    except (TypeError, ValueError):
        return False
    return n % 10 == 1 and n % 100 != 11


def _rel(n, sg, pl):
    return sg if _one(n) else pl


EXCL_PLAIN = (
    ("jednokratni", lambda n: f"{cnt(n, 'novčanik', 'novčanika', 'novčanika')} "
                              f"{_rel(n, 'koji se pojavio', 'koji su se pojavili')} samo kod jednog skoka"),
    ("bot", lambda n: f"{cnt(n, 'bota', 'bota', 'botova')} (programi koji trguju bez prestanka)"),
    ("snajper", lambda n: f"{cnt(n, 'snajpera', 'snajpera', 'snajpera')} (kupuju u prvim sekundama novog tokena)"),
    ("market_maker", lambda n: f"{cnt(n, 'market makera', 'market makera', 'market makera')} "
                               "(kupuju i prodaju cijelo vrijeme)"),
    ("kupuje_sve", lambda n: f"{cnt(n, 'novčanik', 'novčanika', 'novčanika')} {_rel(n, 'koji kupuje', 'koji kupuju')} "
                             "gotovo svaki token koji skoči"),
    ("relayer", lambda n: f"{cnt(n, 'posrednika', 'posrednika', 'posrednika')} (plaćaju naknade za mnogo tuđih "
                          "novčanika)"),
    ("bez_placanja", lambda n: f"{cnt(n, 'novčanik', 'novčanika', 'novčanika')} "
                               f"{_rel(n, 'koji je tokene dobio prijenosom, a nije ih kupio', 'koji su tokene dobili prijenosom, a nisu ih kupili')}"),
)


def excluded_text(ex):
    parts = [fn(ex[c]["n"]) for c, fn in EXCL_PLAIN if (ex.get(c) or {}).get("n")]
    if not parts:
        return "Još nikoga nismo izbacili: prvo pretraživanje je noćas."
    return ("Izbacili smo " + join(parts) + ". Njih ne pratimo: njihove kupnje prije skoka su slučajne ili automatske, "
            "pa ne pomažu predvidjeti skok.")


CSS = """<style>
.nj-head{display:grid;gap:10px;margin:14px 0 6px}
@media(min-width:900px){.nj-head{grid-template-columns:repeat(3,1fr)}}
.nj-a{border:1px solid var(--line);border-left:5px solid var(--line);border-radius:12px;padding:10px 14px;background:var(--card)}
.nj-a h3{margin:0 0 4px;font-size:15px;font-weight:700}.nj-a p{margin:0;font-size:15px;line-height:1.45}
.nj-a.nj-good{border-left-color:var(--good)}.nj-a.nj-warn{border-left-color:var(--warn)}.nj-a.nj-bad{border-left-color:var(--bad)}
.nj-how{font-size:13px;color:var(--mut);margin:6px 0 0;line-height:1.45}
.nj-cards{display:grid;gap:10px;margin:12px 0 0}
@media(min-width:900px){.nj-cards{grid-template-columns:repeat(2,1fr)}}
.nj-c{border:1px solid var(--line);border-radius:12px;padding:10px 14px;background:var(--card);min-width:0}
.nj-c p{margin:6px 0 0;font-size:14.5px;line-height:1.45;overflow-wrap:anywhere}.nj-c p.nj-m{font-size:13.5px;color:var(--mut)}
.nj-ch{display:flex;flex-wrap:wrap;gap:6px 8px;align-items:center}
.nj-ch code,.nj-l code{font-size:13px;background:var(--soft);border-radius:5px;padding:1px 5px}
.nj-x{font-size:12.5px;color:var(--acc);text-decoration:none;font-weight:500}
.nj-b{font-size:12px;font-weight:600;border-radius:999px;padding:1px 9px;margin-left:auto}
.nj-b.good{color:var(--good);border:1px solid var(--good)}.nj-b.warn{color:var(--warn);border:1px solid var(--warn)}
.nj-d{margin:8px 0 0;font-size:13.5px}.nj-d summary{cursor:pointer;color:var(--acc);font-weight:500}
.nj-l{margin:6px 0 4px;padding-left:18px}.nj-l li{margin:4px 0;line-height:1.45;overflow-wrap:anywhere}
.nj-l .nk-cp{margin-left:6px}.nj-s{font-size:13px;color:var(--mut)}
.nj-more{display:flex;flex-wrap:wrap;gap:8px 16px;margin:12px 0 0;font-size:14px}
.nj-more a{color:var(--acc);text-decoration:none;font-weight:600}
.nj-ex{font-size:14.5px;line-height:1.5;margin:8px 0 0}
details.nj-det{margin:28px 0 0;border-top:1px solid var(--line);padding-top:6px}
details.nj-det>summary{cursor:pointer;font-size:19px;font-weight:700;padding:8px 0}
.nj-intro{font-size:14px;line-height:1.45;margin:4px 0 6px}
.na .nk-cp{font:inherit;font-size:12px;line-height:1.4;border:1px solid var(--line);border-radius:6px;background:var(--card);
 color:var(--fg);padding:1px 7px;cursor:pointer;min-height:0;box-shadow:none;font-weight:500}
</style>"""
