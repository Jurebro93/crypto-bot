"""What Insajderi 2.0 shows: the log lines, output/insajderi.md, output/pametni_novac.md (the owner's daily digest),
the MCP read tool get_insiders2, the card under "Ostalo" and the OpenAI critic's context block. Read-only."""
import json
import os
import time

from insajderi import store

OUT_DIR = os.path.join(store.ROOT, "output")


def _ev(x):
    return "—" if x is None else f"{x:+.1f} %"


def _sh(w):
    return (w or "?")[:4] + "…" + (w or "?")[-4:]


def lines(s):
    """The pass's log lines (the first is the owner's: events, sellers, bought before, confirmed groups, copy)."""
    if not s:
        return [store.PREFIX + "još nema prolaza"]
    cp = s.get("copy") or {}
    ours, al = cp.get("nasa_pravila") or {}, cp.get("svi") or {}
    out = [f"{store.PREFIX}događaja {s.get('events', 0)} (pozivi {s.get('call_events', 0)}, skokovi {s.get('jump_events', 0)}), "
           f"prodavača {s.get('sellers', 0)}, kupili prije poziva {s.get('bought_before', 0)}, potvrđenih grupa "
           f"{s.get('confirmed', 0)}; kopiranje: MC≥5M n={ours.get('n', 0)}, EV {_ev(ours.get('ev_pct'))}; svi "
           f"n={al.get('n', 0)}, EV {_ev(al.get('ev_pct'))}"]
    pn = cp.get("poziv_nakon") or {}
    out.append(f"{store.PREFIX}odluka: {'KOPIRATI U DEMU' if s.get('copyable') else 'ne kopirati'} — {s.get('verdict')}; "
               f"poziv nakon njihove kupnje: 1 d {pn.get('1d_pct')} %, 3 d {pn.get('3d_pct')} %, 7 d {pn.get('7d_pct')} % "
               f"(n={pn.get('n', 0)}); Helius danas {s.get('helius_today', 0):,} od {s.get('helius_cap', 0):,} kr.")
    cats = s.get("catalysts") or {}
    if cats:
        from insajderi.events import CAT_HR
        out.append(store.PREFIX + "katalizatori skokova: " + ", ".join(
            f"{CAT_HR.get(k, k)} {v}" for k, v in sorted(cats.items(), key=lambda kv: -kv[1])))
    sm = s.get("smart") or {}
    if sm:
        sg = sm.get("signal") or {}
        out.append(f"{store.PREFIX}pametni novac: {sm.get('n_wallets', 0)} novčanika u {sm.get('n_clusters', 0)} klastera; "
                   f"signal {sm.get('min_clusters', 2)}+ klastera: n={sg.get('n', 0)}, medijan {_ev(sg.get('median_pct'))} "
                   f"(prosjek {_ev(sg.get('ev_pct'))} vuku rijetki mikrokapovi); MC ≥ 5M: "
                   f"n={(sg.get('mc5m') or {}).get('n', 0)}, EV {_ev((sg.get('mc5m') or {}).get('ev_pct'))}, "
                   f"medijan {_ev((sg.get('mc5m') or {}).get('median_pct'))}")
    try:   # 19.11.: the owner's daily wallet line (insajderi/prijepumpe.py)
        from insajderi import prijepumpe
        out.append(prijepumpe.line(s.get("prije_pumpe"), s.get("helius_today", 0), s.get("helius_cap", 0)))
    except Exception as e:  # noqa: BLE001
        out.append(f"{store.PREFIX}novčanici prije pumpe: linija ({type(e).__name__}: {e})")
    tr = s.get("trending") or {}
    if tr:
        out.append(f"{store.PREFIX}uskoro trending: ulazaka {tr.get('entries', 0)}, holdout n={tr.get('n_test', 0)}, "
                   f"preciznost top {tr.get('top', 0)} {tr.get('precision_pct')} % prema osnovi {tr.get('base_pct')} %")
    return out


def kol_line():
    """The last "insajderi kol: ..." line (run_insajderi.py report)."""
    from insajderi import kolwallets
    return kolwallets.line(kolwallets.summary())


# ---------- the database views ---------------------------------------------------------------------------------------

def groups(limit=20, path=None, cls=None):
    con = store.ro(path or store.db_path())
    sql = ("SELECT owner, members, n_members, cls, why, n_hits, n_early, n_callers, lift, med_lead_min, pnl_sol, tokens, "
           "callers, crews, confirmed_ts, score FROM i2_groups")
    args = []
    if cls:
        sql += " WHERE cls = ?"
        args.append(cls)
    rows = store.q(con, sql + " ORDER BY (confirmed_ts IS NULL), score DESC LIMIT ?", (*args, int(limit)))
    if con is not None:
        con.close()
    keys = ("owner", "members", "n_members", "cls", "why", "n_hits", "n_early", "n_callers", "lift", "med_lead_min",
            "pnl_sol", "tokens", "callers", "crews", "confirmed_ts", "score")
    out = []
    for r in rows:
        d = dict(zip(keys, r))
        for k in ("members", "tokens", "callers", "crews"):
            try:
                d[k] = json.loads(d[k] or "null")
            except ValueError:
                d[k] = None
        d["confirmed"] = d.pop("confirmed_ts") is not None
        out.append(d)
    return out


def top_events(limit=10, since=None, path=None):
    con = store.ro(path or store.db_path())
    rows = store.q(con, """SELECT eid, kind, token, symbol, t0, handle, n_callers, mcap0, peak_x, catalyst, catalysts,
        n_part FROM i2_events WHERE t0 >= ? ORDER BY peak_x DESC LIMIT ?""", (int(since or 0), int(limit)))
    early = {}
    for (eid, *_r) in rows:
        early[eid] = store.q(con, """SELECT wallet, owner, buy_ts, sol_in, sold_into, sol_out FROM i2_part WHERE eid = ? AND
            bought_before = 1 ORDER BY COALESCE(sol_in, 0) DESC LIMIT 5""", (eid,))
    if con is not None:
        con.close()
    out = []
    for eid, kind, tok, sym, t0, h, nc, mc0, px, cat, cats, n in rows:
        try:
            cats = json.loads(cats or "[]")
        except ValueError:
            cats = []
        out.append({"eid": eid, "kind": kind, "token": tok, "symbol": sym, "t0": t0, "first_caller": h, "n_callers": nc,
                    "mcap0": mc0, "peak_pct": round((px or 0) * 100, 1), "catalyst": cat, "catalysts": cats[:5],
                    "participants": n,
                    "early_buyers": [{"wallet": w, "owner": o, "buy_ts": b, "sol_in": si, "sold_into": bool(so),
                                      "sol_out": sout} for w, o, b, si, so, sout in early.get(eid, [])]})
    return out


def catalyst_tasks(limit=5, now=None, path=None, trade_db=None):
    """[event] of the biggest jumps of the last 48 h whose catalyst Grok has not checked yet (catalyst_check answers:
    submit_signal_opinion with evidence source catalyst_check, archived in trade.db assistant_notes)."""
    now = int(now or time.time())
    tops = top_events(20, now - 48 * 3600, path)
    if not tops:
        return []
    from insajderi import events as iev
    if trade_db is None:
        try:
            from trade import settings
            trade_db = settings.DB
        except Exception:  # noqa: BLE001
            trade_db = None
    done = iev._grok_answers(trade_db, [e["token"] for e in tops])
    return [e for e in tops if not any(ts >= e["t0"] for ts, _t in done.get(e["token"], []))][:int(limit)]


def mcp(args=None):
    """MCP get_insiders2 (read-only): the last pass's summary, the copy verdict, the groups (confirmed insiders first),
    the top jumps with their catalyst and early buyers, smart money; limit 1-100."""
    a = args or {}
    try:
        lim = max(1, min(100, int(a.get("limit") or 20)))
    except (TypeError, ValueError):
        lim = 20
    from insajderi import run
    s = run.summary()
    if not s:
        return {"available": False, "note": "Insajderi 2.0 još nije odradio prvi prolaz (nakon deploya ~10 min, pa noću)"}
    out = {"available": True, "summary": {k: s.get(k) for k in ("ts", "events", "call_events", "jump_events", "covered",
                                                                 "fetched", "sellers", "bought_before", "confirmed",
                                                                 "classes", "helius_today", "helius_cap", "catalysts")},
           "copyability": s.get("copy"), "copyable": s.get("copyable"), "verdict": s.get("verdict"),
           "groups": groups(lim, cls=a.get("class")), "top_jumps": top_events(min(lim, 20), time.time() - 7 * 86400),
           "smart_money": (s.get("smart") or {}).get("top"), "trending": s.get("trending"),
           "prije_pumpe": _prije_pumpe(s, lim),
           "real_money": "nikad iz ovog alata (NEVER_LIVE); vlasnik odlučuje kasnije s brojkama"}
    return out


def _prije_pumpe(s, lim):
    """19.11.: the wallets that buy BEFORE a pump (prijepumpe.py): the day's line, the copy numbers, the list and the
    bundles (statistics, never accusations)."""
    from insajderi import prijepumpe
    pp = s.get("prije_pumpe")
    con = store.ro(store.db_path())
    try:
        return {"line": prijepumpe.line(pp, s.get("helius_today", 0), s.get("helius_cap", 0)),
                "summary": {k: v for k, v in (pp or {}).items() if k != "copy"}, "copy": (pp or {}).get("copy"),
                "groups": prijepumpe.groups(con, lim), "bundles": prijepumpe.bundle_rows(con, min(lim, 30)),
                "note": "statistika, ne optužba: grupa je više puta kupila prije skoka i prodala u skok"}
    finally:
        if con is not None:
            con.close()


def critic_summary():
    """The OpenAI critic's block: the copy walk-forward per MC bucket, the verdict, the classes, the demo."""
    from insajderi import run
    s = run.summary()
    if not s:
        return None
    cp = s.get("copy") or {}
    d = {"dogadaja": s.get("events"), "pozivi": s.get("call_events"), "skokovi": s.get("jump_events"),
         "potvrdenih_grupa": s.get("confirmed"), "klase": s.get("classes"),
         "kopiranje_walk_forward": {k: cp.get(k) for k in ("nasa_pravila", "bondani", "svi", "<1M", "1M-5M", "5M+",
                                                            "5M-15M", "15M+",
                                                            "poziv_nakon", "izlazi", "bez_cijene")},
         "odluka": s.get("verdict"), "katalizatori": s.get("catalysts"),
         "pametni_novac_signal": (s.get("smart") or {}).get("signal"),
         "uskoro_trending": s.get("trending"),
         "helius": {"danas": s.get("helius_today"), "strop": s.get("helius_cap")},
         "napomena": "ulaz nakon njihove kupnje +60 s, trošak trade/cost.round_trip, izlaz kad prodaju / stop -25 % / 24 h; "
                     "Pretpostavka: cijene iz tradeova kad nema svijeća"}
    try:
        from insajderi import live
        d["demo"] = live.demo_stats()
    except Exception:  # noqa: BLE001
        pass
    return d


# ---------- markdown ---------------------------------------------------------------------------------------------------

def _t(ts):
    return time.strftime("%d.%m. %H:%M", time.gmtime(ts)) if ts else "—"


def markdown(s):
    cp = s.get("copy") or {}
    L = ["# Insajderi 2.0", "",
         f"Prolaz {_t(s.get('ts'))} UTC. Pravi novac: nikad iz ovog alata (NEVER_LIVE); vlasnik odlučuje s brojkama.", "",
         "## Provjereno (iz baza)", "",
         f"- događaja: {s.get('events', 0)} (pozivi sa skokom {s.get('call_events', 0)}, tržišni skokovi "
         f"{s.get('jump_events', 0)}); s podacima o tradeovima {s.get('covered', 0)}, Helius pročitan {s.get('fetched', 0)}",
         f"- prodavača u skok: {s.get('sellers', 0)}; od njih kupili prije: {s.get('bought_before', 0)}",
         f"- grupe po vlasniku: {s.get('classes')}; potvrđenih insajdera: {s.get('confirmed', 0)}; botova isključeno "
         f"{s.get('bots', 0)}, relayera {s.get('relayers', 0)}",
         f"- Helius danas: {s.get('helius_today', 0):,} od {s.get('helius_cap', 0):,} kredita", "",
         "## Kopiranje (walk-forward, ulaz nakon njihove kupnje, nakon troška)", "",
         "| skupina | n | pogodak % | EV % | CI90 od | CI90 do |", "|---|---|---|---|---|---|"]
    for k in ("nasa_pravila", "bondani", "svi", "15M+", "5M-15M", "5M+", "1M-5M", "<1M"):
        x = cp.get(k) or {}
        L.append(f"| {k} | {x.get('n', 0)} | {x.get('hit_pct')} | {x.get('ev_pct')} | {x.get('ci90_lo_pct')} | "
                 f"{x.get('ci90_hi_pct')} |")
    pn = cp.get("poziv_nakon") or {}
    L += ["", f"Poziv nakon njihove kupnje: 1 d {pn.get('1d_pct')} %, 3 d {pn.get('3d_pct')} %, 7 d {pn.get('7d_pct')} % "
              f"(n={pn.get('n', 0)}); izlazi {cp.get('izlazi')}; bez cijene {cp.get('bez_cijene')}.", "",
          f"**Odluka:** {'kopirati u demu' if s.get('copyable') else 'ne kopirati'} — {s.get('verdict')}", "",
          "## Grupe (potvrđeni prvi)", "", "| vlasnik | klasa | novčanika | pogodaka | callera | lift | vodstvo min | PnL SOL |",
          "|---|---|---|---|---|---|---|---|"]
    for g in groups(25):
        L.append(f"| {_sh(g['owner'])} | {g['cls']}{' ✓' if g['confirmed'] else ''} | {g['n_members']} | {g['n_hits']} | "
                 f"{g['n_callers']} | {g['lift']} | {g['med_lead_min']} | {g['pnl_sol']} |")
    L += ["", "## Pretpostavka", "",
          "- vrh skoka bez minutnih svijeća = povrat na 1 / 6 h (donja granica); tržišni skokovi iz 1h zatvaranja",
          "- kupnja prije poziva traži se do 7 dana unatrag preko token računa prodavača (jedna stranica, ~10 kredita)",
          "- ulaz +60 s, 5 % lošije kad nema cijene; izlaz kad grupa proda, stop -25 % ili 24 h; bondan = MC ≥ 60k ili "
          "migracija ili midcap lista", ""]
    try:   # 16.11.: the influencers' probably linked wallets (insajderi/kolwallets.py). output/insajderi.md is read by
        # every admin (/outputs), and what this says about named people is the owner's alone: only the one-line count
        # goes here, the names and the evidence stay on the owner-only page /kol-insajderi
        from insajderi import kolwallets
        L += ["## Insajderski novčanici influencera", "", kolwallets.line(kolwallets.summary()),
              "Detalji su na stranici /kol-insajderi (samo vlasnik).", ""]
    except Exception:  # noqa: BLE001 - the section never costs the report
        pass
    return "\n".join(L) + "\n"


def digest(s, now=None):
    """output/pametni_novac.md: the owner's daily digest (top jumps of the day with catalyst and early buyers, the top
    smart wallets / clusters and what they are buying now)."""
    from insajderi.events import CAT_HR
    now = int(now or s.get("ts") or time.time())
    L = ["# Pametni novac — dnevni pregled", "", f"{_t(now)} UTC. Samo mjerenje i demo; pravi novac ne.", "",
         "## Najveći skokovi u zadnja 24 h", ""]
    tops = top_events(10, now - 86400)
    if not tops:
        L.append("- nema izmjerenih skokova u zadnja 24 h")
    for e in tops:
        eb = ", ".join(f"{_sh(b['wallet'])} ({(b['sol_in'] or 0):.2f} SOL{', prodao u skok' if b['sold_into'] else ''})"
                       for b in e["early_buyers"][:3]) or "nepoznati"
        L.append(f"- **{e['symbol'] or e['token'][:6]}** +{e['peak_pct']:.0f} % od {_t(e['t0'])} (MC "
                 f"${(e['mcap0'] or 0) / 1e6:,.2f}M), katalizator: {CAT_HR.get(e['catalyst'], e['catalyst'] or '—')}; "
                 f"rani kupci: {eb}")
    sm = s.get("smart") or {}
    L += ["", "## Najbolji pametni novčanici / klasteri", ""]
    for x in (sm.get("top") or [])[:10]:
        L.append(f"- {_sh(x['wallet'])} (klaster {x.get('cluster') or '—'}): {', '.join(x.get('roles') or [])}; ocjena "
                 f"{x.get('score')}; zadnja kupnja {x.get('last_symbol') or (x.get('last_token') or '')[:6]} "
                 f"{_t(x.get('last_buy_ts'))}")
    if not sm.get("top"):
        L.append("- još nema popisa (prvi prolaz nakon deploya / noću)")
    L += ["", "## Što kupuju sada (2+ neovisna klastera)", ""]
    for x in (sm.get("now") or [])[:10]:
        L.append(f"- {x.get('symbol') or x['token'][:6]}: {x['n_clusters']} klastera od {_t(x['ts'])}")
    if not sm.get("now"):
        L.append("- ništa u zadnjih 6 h")
    sg = sm.get("signal") or {}
    L += ["", f"Signal (walk-forward, ulaz nakon njih, nakon troška): n={sg.get('n', 0)}, EV {_ev(sg.get('ev_pct'))}, "
              f"CI90 od {_ev(sg.get('ci90_lo_pct'))}.", ""]
    return "\n".join(L) + "\n"


def write(s):
    os.makedirs(OUT_DIR, exist_ok=True)
    for name, text in (("insajderi.md", markdown(s)), ("pametni_novac.md", digest(s))):
        with open(os.path.join(OUT_DIR, name), "w", encoding="utf-8") as f:
            f.write(text)
    from insajderi import prijepumpe   # 19.11.: output/novcanici_prije_pumpe.md
    prijepumpe.write(s.get("prije_pumpe"), s.get("helius_today", 0), s.get("helius_cap", 0))


# ---------- the card --------------------------------------------------------------------------------------------------

def _pp_line(s):
    try:
        from insajderi import prijepumpe
        return prijepumpe.line(s.get("prije_pumpe"), s.get("helius_today", 0), s.get("helius_cap", 0))
    except Exception:  # noqa: BLE001
        return ""


def card_html(sec, item, esc, owner=True):
    """"Insajderi 2.0" under Ostalo (owner only): the copy verdict, the numbers per MC bucket, the top groups and
    today's top jumps; nothing before the first pass."""
    if not owner:
        return ""
    from insajderi import run
    s = run.summary()
    if not s:
        return ""
    cp = s.get("copy") or {}
    ours, al = cp.get("nasa_pravila") or {}, cp.get("svi") or {}
    meta = (f"{s.get('events', 0)} događaja, {s.get('confirmed', 0)} potvrđenih grupa; MC≥5M n={ours.get('n', 0)} EV "
            f"{_ev(ours.get('ev_pct'))}")
    rows = "".join(f"<tr><td>{esc(k)}</td><td>{(cp.get(k) or {}).get('n', 0)}</td><td>{esc(_ev((cp.get(k) or {}).get('ev_pct')))}"
                   f"</td><td>{esc(_ev((cp.get(k) or {}).get('ci90_lo_pct')))}</td></tr>"
                   for k in ("nasa_pravila", "bondani", "svi"))
    gs = "".join(f"<li>{esc(_sh(g['owner']))}: {esc(g['cls'])}{' ✓' if g['confirmed'] else ''}, {g['n_hits']} tokena, "
                 f"{g['n_callers']} callera</li>" for g in groups(5))
    tops = "".join(f"<li>{esc(e['symbol'] or e['token'][:6])} +{e['peak_pct']:.0f} % ({esc(e['catalyst'] or '—')})</li>"
                   for e in top_events(5, time.time() - 86400))
    inner = (f"<p><b>{'Kopirati u demu' if s.get('copyable') else 'Ne kopirati'}</b> — {esc(s.get('verdict') or '')}</p>"
             f"<table><tr><th>skupina</th><th>n</th><th>EV</th><th>CI90 od</th></tr>{rows}</table>"
             f"<p class=mut>Grupe</p><ul>{gs or '<li>—</li>'}</ul><p class=mut>Skokovi danas</p><ul>{tops or '<li>—</li>'}</ul>"
             f"<p>{esc(_pp_line(s))}</p>"
             f"<p class=mut>Helius danas {s.get('helius_today', 0):,} od {s.get('helius_cap', 0):,} kr.; pravi novac nikad "
             f"iz ovog alata.</p>"
             '<p><a href="/kol-insajderi">Insajderski novčanici influencera →</a></p>')
    return sec("Insajderi 2.0", meta, inner, sid="insajderi2")
