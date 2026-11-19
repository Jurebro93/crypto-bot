"""Tjedni trošak po izvoru (19.11., audit; CLAUDE.md: "svaki tjedan u izvještaju navedi trošak po izvoru i što je od toga
donijelo odluku ili trade"): one section of the morning e-mail (run_report.py) every Monday, and in the first report
after a deploy when none went out in the last 7 days.

  when      due(): the Zagreb day is a Monday, or the report is the first one after a deploy (RENDER_GIT_COMMIT differs
            from the one the last sent report was built under; no commit = no deploy known) and the last weekly
            section was sent more than 7 days ago. run_report.send_today marks both in output/report-state.json
            (tjedni_ts, report_commit) only after the e-mail went out, so a failed send tries again.
  window    the last 7 whole UTC days before today (usage.db daily_cost rows, written by usage/daily.py at 23:59 UTC)
            against the 7 before them; a week with fewer saved days says so.
  per source  spend in its own unit and in $ where the unit has a known price (twitterapi.io, OpenAI, Anthropic and
            Apify are booked in $; PumpPortal SOL at today's SOL price; Helius credits, CoinGecko calls and Birdeye CU
            have no per-unit $ here: a plan, not a per-call price), the change against the week before, the jobs that
            spent it (the daily rows' own split), and "što je donijelo":
              Helius, PumpPortal  the demo entries of wallet following (league.db insajderi2_trades, pp_trades,
                                  kopija_trades): their buys come from hype.db chain_trades, which the Helius webhook
                                  fills and PumpPortal mirrors, so the two share them (no split is measurable)
              CoinGecko           the midcap entries (league.db veliki_trades, demo and real): the midcap universe and
                                  its prices come from it, next to other price sources
              OpenAI              the critic's verdicts, the owner's decisions on its suggestions, the council's
                                  decisions (shared with Anthropic)
              Anthropic           the council's decisions (shared with OpenAI); the AI labels of posts led to no trade
                                  that can be traced
              twitterapi, Apify, Birdeye   "nije mjerljivo" (no trade or decision row names them)
Read-only; no network (the SOL price is trade/equity's cached rate); never raises (None on any failure)."""
import os
import sqlite3
import time

DAY = 86400
NM = "nije mjerljivo"


def _f(x):
    try:
        return float(x or 0)
    except (TypeError, ValueError):
        return 0.0


def _day(ts):
    return time.strftime("%Y-%m-%d", time.gmtime(ts))


# ---------- when -------------------------------------------------------------------------------------------------------

def commit():
    return (os.environ.get("RENDER_GIT_COMMIT") or "").strip()


def due(now, st, local_weekday, cur_commit=None):
    """(True/False, why). local_weekday: the Zagreb day's weekday (Monday = 0)."""
    cur = commit() if cur_commit is None else cur_commit
    if local_weekday == 0:
        return True, "ponedjeljak"
    last = int(st.get("tjedni_ts") or 0)
    if cur and st.get("report_commit") != cur and now - last >= 7 * DAY:
        return True, "prvi izvještaj nakon deploya, tjedni trošak nije poslan 7 dana"
    return False, ""


# ---------- the numbers ------------------------------------------------------------------------------------------------

def _add(acc, d, scale=1.0):
    for k, v in (d or {}).items():
        if k and _f(v):
            acc[k] = acc.get(k, 0.0) + _f(v) * scale


def _sum(rows):
    """One week of usage/daily rows -> {source: {"unit": n, "usd": x or None, "jobs": {job: n}}}."""
    s = {k: {"n": 0.0, "usd": 0.0, "jobs": {}} for k in ("twitterapi", "openai", "anthropic", "helius", "coingecko",
                                                         "pumpportal", "apify")}
    for d in rows:
        tw = d.get("twitterapi") or {}
        s["twitterapi"]["n"] += _f(tw.get("usd"))
        s["twitterapi"]["usd"] += _f(tw.get("usd"))
        _add(s["twitterapi"]["jobs"], tw.get("dijelovi"))
        oa, vj, ai = d.get("openai") or {}, d.get("vijece") or {}, d.get("ai") or {}
        s["openai"]["n"] += _f(oa.get("usd")) + _f(vj.get("openai_usd"))
        _add(s["openai"]["jobs"], oa.get("po_vrsti"))
        _add(s["openai"]["jobs"], {"vijeće": vj.get("openai_usd")})
        s["anthropic"]["n"] += _f(ai.get("usd")) + _f(vj.get("claude_usd"))
        _add(s["anthropic"]["jobs"], ai.get("po_poslu"))
        _add(s["anthropic"]["jobs"], {"vijeće": vj.get("claude_usd")})
        he = d.get("helius") or {}
        s["helius"]["n"] += _f(he.get("krediti_bot"))
        _add(s["helius"]["jobs"], he.get("po_poslu"))
        cg = d.get("coingecko") or {}
        s["coingecko"]["n"] += _f(cg.get("kljuc")) + _f(cg.get("besplatno_ukupno"))
        _add(s["coingecko"]["jobs"], cg.get("po_poslu"))
        _add(s["coingecko"]["jobs"], {f"{k} (besplatno)": v for k, v in (cg.get("besplatno") or {}).items()})
        pp = d.get("pumpportal") or {}
        s["pumpportal"]["n"] += _f(pp.get("sol"))
        _add(s["pumpportal"]["jobs"], {"tok tradeova (live)": pp.get("sol")})
        ap = d.get("apify") or {}
        s["apify"]["n"] += _f(ap.get("usd_bot"))
        _add(s["apify"]["jobs"], ap.get("po_izvoru"))
    for k in ("openai", "anthropic", "apify"):
        s[k]["usd"] = s[k]["n"]
    for k in ("helius", "coingecko", "pumpportal"):
        s[k]["usd"] = None
    return s


def _usage_service(path, service, t0, t1):
    """(total amount, {script/method: amount}) of usage.db usage for one service in [t0, t1); None when the service
    has no row at all (a source that is not there yet, e.g. Birdeye before its first call)."""
    con = _ro(path)
    if con is None:
        return None
    try:
        rows = con.execute("SELECT COALESCE(method, script), SUM(amount), SUM(calls) FROM usage WHERE service = ? AND "
                           "hour >= ? AND hour < ? GROUP BY 1", (service, int(t0), int(t1))).fetchall()
        any_ = con.execute("SELECT 1 FROM usage WHERE service = ? LIMIT 1", (service,)).fetchone()
    except sqlite3.Error:
        return None
    finally:
        con.close()
    if not any_:
        return None
    jobs = {k or "ostalo": _f(a) or _f(n) for k, a, n in rows}
    return sum(jobs.values()), jobs


def _ro(path):
    if not path or not os.path.exists(path) or not os.path.getsize(path):
        return None
    try:
        return sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5)
    except sqlite3.Error:
        return None


def _entries(lpath, table, t0, t1, users=None):
    """(entries opened in [t0, t1), of them closed, net $ of the closed) from one league.db table; None without it."""
    con = _ro(lpath)
    if con is None:
        return None
    try:
        if not con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone():
            return None
        q, args = f"SELECT COUNT(*), SUM(status='closed'), SUM(CASE WHEN status='closed' THEN pnl_usd END) FROM {table} " \
                  "WHERE opened_ts >= ? AND opened_ts < ?", [int(t0), int(t1)]
        if users:
            q += f" AND user IN ({','.join('?' * len(users))})"
            args += list(users)
        n, c, pnl = con.execute(q, args).fetchone()
        return int(n or 0), int(c or 0), round(_f(pnl), 2)
    except sqlite3.Error:
        return None
    finally:
        con.close()


def _ent_txt(parts):
    """"12 ulaza (insajderi2 5, prije pumpe 7), zatvoreno 9, neto +3,10 $" or None when nothing was opened."""
    have = [(name, x) for name, x in parts if x]
    n = sum(x[0] for _name, x in have)
    if not n:
        return None
    c = sum(x[1] for _name, x in have)
    pnl = sum(x[2] for _name, x in have)
    split = ", ".join(f"{name} {x[0]}" for name, x in have if x[0])
    return f"{n} demo/pravih ulaza ({split}), zatvoreno {c}, neto {pnl:+.2f} $".replace(".", ",")


def _brought(p, rows, t0, t1):
    """{source: sentence} of what each source fed in the week (see the module text)."""
    lpath = p.get("league")
    wallet = _ent_txt([("insajderi2", _entries(lpath, "insajderi2_trades", t0, t1)),
                       ("prije pumpe / bundle", _entries(lpath, "pp_trades", t0, t1)),
                       ("kopija dokazanih", _entries(lpath, "kopija_trades", t0, t1))])
    try:
        from report import midcap
        us = midcap.users()
    except Exception:  # noqa: BLE001
        us = {"demo": "autopilot-paper", "pravi": "pravi-trade"}
    mid = _ent_txt([("demo", _entries(lpath, "veliki_trades", t0, t1, [us["demo"]])),
                    ("pravi novac", _entries(lpath, "veliki_trades", t0, t1, [us["pravi"]]))])
    ver = sum(int((d.get("openai") or {}).get("presuda") or 0) for d in rows)
    dec = {}
    for d in rows:
        _add(dec, (d.get("openai") or {}).get("odluke_vlasnika"))
    council = sum(int((d.get("vijece") or {}).get("odluka") or 0) for d in rows)
    labels = sum(int((d.get("ai") or {}).get("objava") or 0) for d in rows)
    oa = []
    if ver:
        oa.append(f"{ver} presuda kritičara otvorenim pozicijama")
    if dec:
        oa.append("odluke vlasnika o prijedlozima: " + ", ".join(f"{k} {int(v)}" for k, v in sorted(dec.items())))
    if council:
        oa.append(f"vijeće {council} odluka (zajedno s Anthropicom)")
    an = [f"vijeće {council} odluka (zajedno s OpenAI-jem)"] if council else []
    if labels:
        an.append(f"oznake {labels} objava: trade iz njih {NM}")
    shared = " (Helius webhook i PumpPortal zajedno pune isti tok kupnji; podjela " + NM + ")"
    return {
        "helius": (wallet + shared) if wallet else f"nijedan ulaz praćenja novčanika; ostalo {NM}",
        "pumpportal": (wallet + shared) if wallet else f"nijedan ulaz praćenja novčanika; ostalo {NM}",
        "coingecko": (mid + " (midcap svemir i cijene; uz druge izvore cijena)") if mid else f"nijedan midcap ulaz; {NM}",
        "openai": "; ".join(oa) if oa else NM,
        "anthropic": "; ".join(an) if an else NM,
        "twitterapi": NM, "apify": NM, "birdeye": NM}


NAMES = (("twitterapi", "X (twitterapi.io)", "$"), ("openai", "OpenAI", "$"), ("anthropic", "Anthropic (Claude)", "$"),
         ("helius", "Helius", "kredita"), ("coingecko", "CoinGecko", "poziva"), ("pumpportal", "PumpPortal", "SOL"),
         ("apify", "Apify", "$"), ("birdeye", "Birdeye", "CU"))


def _change(a, b):
    if not b:
        return "novo" if a else "0"
    return f"{(a - b) / b:+.0%}".replace(".", ",")


def collect(now, p=None, sol_usd=None):
    """The section's dict: {"od", "do", "dana", "dana_prije", "izvori": [{izvor, jedinica, kolicina, usd, promjena,
    poslovi, donijelo}]}; None when no day is saved yet or on any failure."""
    try:
        from report import midcap
        from usage import daily
        p = p or midcap.paths()
        end = int(now) // DAY * DAY            # today's UTC midnight: the window ends before today
        t0, tp = end - 7 * DAY, end - 14 * DAY
        rows = daily.days(14, end - DAY, p["usage"])
        cur = [d for d in rows if _day(t0) <= (d.get("day") or "") < _day(end)]
        prev = [d for d in rows if _day(tp) <= (d.get("day") or "") < _day(t0)]
        if not cur:
            return None
        a, b = _sum(cur), _sum(prev)
        bi = _usage_service(p["usage"], "birdeye", t0, end)
        if bi is not None:
            bp = _usage_service(p["usage"], "birdeye", tp, t0) or (0.0, {})
            a["birdeye"] = {"n": bi[0], "usd": None, "jobs": bi[1]}
            b["birdeye"] = {"n": bp[0], "usd": None, "jobs": bp[1]}
        if sol_usd is None:
            try:
                from trade import equity
                sol_usd = (equity.rates() or {}).get("sol_usd")
            except Exception:  # noqa: BLE001
                sol_usd = None
        if sol_usd:
            a["pumpportal"]["usd"] = a["pumpportal"]["n"] * float(sol_usd)
        got = _brought(p, cur, t0, end)
        out = []
        for key, name, unit in NAMES:
            if key not in a:
                continue
            x, y = a[key], b.get(key) or {"n": 0.0}
            jobs = sorted(((k, v) for k, v in x["jobs"].items() if v), key=lambda kv: -kv[1])[:5]
            out.append({"izvor": name, "kljuc": key, "jedinica": unit, "kolicina": round(x["n"], 4),
                        "usd": None if x["usd"] is None else round(x["usd"], 2), "prije": round(_f(y.get("n")), 4),
                        "promjena": _change(x["n"], _f(y.get("n"))), "poslovi": [[k, round(v, 4)] for k, v in jobs],
                        "donijelo": got.get(key, NM)})
        return {"od": _day(t0), "do": _day(end - DAY), "dana": len(cur), "dana_prije": len(prev), "izvori": out,
                "ukupno_usd": round(sum(r["usd"] for r in out if r["usd"] is not None), 2)}
    except Exception as e:  # noqa: BLE001 - the report never fails because of this section
        print(f"report tjedni trošak: {type(e).__name__}: {e}", flush=True)
        return None


# ---------- the e-mail -------------------------------------------------------------------------------------------------

def _qty(v, unit):
    if unit == "$":
        return f"{v:,.2f} $".replace(",", " ").replace(".", ",")
    if unit == "SOL":
        return f"{v:.3f} SOL".replace(".", ",")
    return f"{int(round(v)):,} {unit}".replace(",", ".")


def rows(t):
    """[(izvor, potrošeno, promjena, poslovi, donijelo)] as plain text (render escapes)."""
    out = []
    for r in t.get("izvori") or []:
        spent = _qty(r["kolicina"], r["jedinica"])
        if r["jedinica"] != "$":
            spent += f" ≈ {r['usd']:.2f} $".replace(".", ",") if r["usd"] is not None else " ($ po jedinici nepoznat)"
        jobs = ", ".join(f"{k} {_qty(v, r['jedinica']).rsplit(' ', 1)[0]}" for k, v in r["poslovi"]) or "-"
        out.append((r["izvor"], spent, r["promjena"], jobs, r["donijelo"]))
    return out


def html(t, render):
    """The section body for the morning e-mail (render = report.render, for its table and small text)."""
    e = render.e
    head = (f"Zadnjih {t['dana']} UTC dana ({t['od']} do {t['do']}) prema tjednu prije"
            + (f" ({t['dana_prije']} spremljenih dana)" if t.get("dana_prije", 7) < 7 else "")
            + f"; ukupno poznato u $: {t['ukupno_usd']:.2f} $.".replace(".", ",", 1))
    body = render.small(e(head))
    body += render.ctable(["Izvor", "Potrošeno", "Promjena", "Poslovi", "Što je donijelo"],
                          [[e(a) for a in r] for r in rows(t)])
    body += render.small(e("Brojke bota (usage.db), ne račun dobavljača. „Što je donijelo”: ulazi i odluke tog tjedna "
                           "koje taj izvor hrani; gdje ga nijedan trade ili odluka ne imenuje piše „nije mjerljivo”."))
    return body
