"""What makroinf shows (read-only): the hourly log line, output/makroinf.md, the owner's card "Makro influenceri"
under Ostalo, the MCP read tool get_macro_influencers, the OpenAI critic's context block and the morning-report line.
Deletions are always "naknadno nedostupno" (never an accusation)."""
import json
import os
import time

from makroinf import racuni, rules, store

D = 86400
DIR_HR = {"up": "gore", "down": "dolje", "bottom_in": "dno je tu", "top_in": "vrh je tu", "range": "raspon"}
STATE_HR = {"aktivan": "aktivan", "na_cekanju": "na čekanju", "iskljucen": "isključen (degradacija)"}


def pct(x, signed=False):
    if x is None:
        return "—"
    return f"{x * 100:+.0f} %" if signed else f"{x * 100:.0f} %"


def pp(x):
    return "—" if x is None else f"{x * 100:+.1f} pp"


def _usd(x):
    return f"{(x or 0):.2f} $".replace(".", ",")


def _idx(x):
    return "—" if x is None else f"{x:+.2f}".replace(".", ",")


def data(path=None, con=None):
    """Everything the views read, from makroinf.db (read-only), or None before the database exists."""
    own = con is None
    con = con or store.ro(path)
    if con is None:
        return None
    try:
        summ = store.kv_json(con, "summary", {}) or {}
        scores = {h: json.loads(d) for h, d in store.q(con, "SELECT handle, data FROM scores")}
        keys = ("handle", "name", "category", "lang", "followers", "statuses", "status", "why", "source", "owner_seed")
        accs = {r[0]: dict(zip(keys, r)) for r in store.q(con, f"SELECT {', '.join(keys)} FROM accounts")}
        walk = {k: v for k, v in (store.kv_json(con, "walk", {}) or {}).items() if k != "dani"}
        idx = {}
        for asset, mode, kind, v, n, day in store.q(con, """SELECT asset, mode, kind, value, coverage, day FROM index_d i
                WHERE day = (SELECT MAX(day) FROM index_d j WHERE j.asset = i.asset AND j.mode = i.mode AND
                j.kind = i.kind)"""):
            idx[f"{asset}:{mode}:{kind}"] = {"v": v, "n": n, "day": day}
        prev = {f"{a}:{m}:{k}": v for a, m, k, v in store.q(con, """SELECT asset, mode, kind, value FROM index_d i WHERE
                day = (SELECT MAX(day) FROM index_d j WHERE j.asset = i.asset AND j.mode = i.mode AND j.kind = i.kind
                AND j.day < (SELECT MAX(day) FROM index_d k WHERE k.asset = i.asset AND k.mode = i.mode AND
                k.kind = i.kind))""")}
        dels = dict(store.q(con, "SELECT COALESCE(state, 'neprovjereno'), COUNT(*) FROM deletions GROUP BY 1"))
        out = {"summary": summ, "scores": scores, "accounts": accs, "walk": walk, "index": idx, "index_prev": prev,
               "stavovi": store.kv_json(con, "stavovi", {}) or {}, "ulaz": store.kv_json(con, "ulaz", {}) or {},
               "provjera": store.kv_json(con, "provjera", {}) or {}, "costs": store.costs(con),
               "candidates": racuni.candidates(con), "deletions": dels,
               "pilot": {"twapi_done": store.kv(con, "pilot_twapi_done"), "twapi_why": store.kv(con, "pilot_twapi_why"),
                         "openai_done": store.kv(con, "pilot_openai_done")},
               "counts": {"tweets": (store.q(con, "SELECT COUNT(*) FROM tweets") or [[0]])[0][0],
                          "macro_posts": (store.q(con, "SELECT COUNT(*) FROM tweets WHERE macro = 1") or [[0]])[0][0],
                          "classified": (store.q(con, "SELECT COUNT(*) FROM tweets WHERE cls_ts IS NOT NULL") or
                                         [[0]])[0][0]},
               "chart": chart_rows(con), "meme_cov": _meme_cov(con)}
        return out
    finally:
        if own:
            con.close()


def _meme_cov(con):
    from makroinf import prices
    return prices.coverage(con)


def chart_rows(con, days=120):
    """[(day, BTC close, top index historic, top index prospective)] of the last `days` days."""
    from makroinf import prices
    since = (int(time.time()) // D - days) * D
    btc = {t // D * D: p for t, p in store.q(con, "SELECT ts, close FROM px WHERE asset = ? AND res = 'd' AND ts >= ?",
                                             (prices.COINS["BTC"], since))}
    hi = {d: v for d, v in store.q(con, "SELECT day, value FROM index_d WHERE asset = 'BTC' AND mode = 'povijesno' AND "
                                        "kind = 'top' AND day >= ?", (since,))}
    pr = {d: v for d, v in store.q(con, "SELECT day, value FROM index_d WHERE asset = 'BTC' AND mode = 'prospektivno' "
                                        "AND kind = 'top' AND day >= ?", (since,))}
    return [(d, btc.get(d), hi.get(d), pr.get(d)) for d in sorted(set(btc) | set(hi) | set(pr))]


def rank_rows(d, limit=None, owner=True):
    """Rows of the rank table (the summary's rank order)."""
    out = []
    rank = (d.get("summary") or {}).get("rank") or sorted(d.get("scores") or {})
    stav = ((d.get("stavovi") or {}).get("sada") or {}).get("BTC") or {}
    for h in rank:
        s = (d.get("scores") or {}).get(h)
        if not s:
            continue
        a = (d.get("accounts") or {}).get(h) or {}
        p, e, g = s["prediktivno"], s["ekonomski"], s["integritet"]
        st = stav.get(h)
        out.append({"handle": h, "name": a.get("name"), "category": a.get("category"), "followers": a.get("followers"),
                    "n_epizoda": p["n_epizoda"], "pogodak": p["pogodak"], "wilson95": p["wilson95"],
                    "najbolja_bazna": p["najbolja_bazna"], "razlika": p["razlika_prema_najboljoj"],
                    "skupljeno": p["skupljeno"], "presuda": p["presuda"], "brier": p.get("brier"),
                    "ekonomski": {k: e.get(k) for k in ("n", "razlika", "razlika95", "presuda")},
                    "integritet": {k: g.get(k) for k in ("makro_izjava", "naknadno_nedostupno", "udio", "wilson95",
                                                         "promocije")},
                    "po_horizontu": s.get("po_horizontu"),
                    "stav_btc": ({"smjer": st["dir"], "od": st["ts"]} if st else None)})
        if limit and len(out) >= limit:
            break
    return out


def hour_line(con, now=None, c=None):
    """The hourly line: accounts, posts, calls, episodes, deletions, spend vs caps, the index, the DEMO input."""
    now = int(now or time.time())
    c = c or store.config()
    st = dict(store.q(con, "SELECT status, COUNT(*) FROM accounts GROUP BY status"))
    n_tw = (store.q(con, "SELECT COUNT(*) FROM tweets") or [[0]])[0][0]
    n_new = (store.q(con, "SELECT COUNT(*) FROM tweets WHERE fetched_ts >= ?", (now - 3600,)) or [[0]])[0][0]
    n_cls = (store.q(con, "SELECT COUNT(*) FROM tweets WHERE cls_ts IS NOT NULL") or [[0]])[0][0]
    n_calls = (store.q(con, "SELECT COUNT(DISTINCT id) FROM calls") or [[0]])[0][0]
    summ = store.kv_json(con, "summary", {}) or {}
    oc = summ.get("outcomes") or {}
    dl = dict(store.q(con, "SELECT state, COUNT(*) FROM deletions WHERE state IS NOT NULL GROUP BY state"))
    gone = sum(v for k, v in dl.items() if k in ("confirmed_deleted", "unavailable", "account_protected",
                                                  "account_suspended"))
    tp, td = store.spent(con, "twitterapi", "pilot"), store.spent(con, "twitterapi", "dan", store.day(now))
    op, od = store.spent(con, "openai", "pilot"), store.spent(con, "openai", "dan", store.day(now))
    r = store.q(con, "SELECT value, coverage FROM index_d WHERE asset = 'BTC' AND mode = 'prospektivno' AND kind = 'top' "
                     "ORDER BY day DESC LIMIT 1")
    ul = store.kv_json(con, "ulaz", {}) or {}
    pilot = "gotov" if store.kv(con, "pilot_twapi_done") else "u tijeku"
    exp = ""
    if store.kv(con, "prosirenje"):
        cap = store.kv_json(con, "prosirenje", {}) or {}
        exp = (f"; proširenje twitterapi {_usd(store.spent(con, 'twitterapi', 'prosirenje'))} / "
               f"{_usd(cap.get('twapi_usd') or c['expand_twapi_usd'])}, OpenAI "
               f"{_usd(store.spent(con, 'openai', 'prosirenje'))} / {_usd(cap.get('openai_usd') or c['expand_openai_usd'])}")
    if store.kv(con, "prosirenje2"):   # 16.11.: the second wave (30k+, the ceiling 800) under its own caps
        cap = store.kv_json(con, "prosirenje2", {}) or {}
        exp += (f"; 2. val (30k+) twitterapi {_usd(store.spent(con, 'twitterapi', 'prosirenje2'))} / "
                f"{_usd(cap.get('twapi_usd') or c['expand2_twapi_usd'])}, OpenAI "
                f"{_usd(store.spent(con, 'openai', 'prosirenje2'))} / "
                f"{_usd(cap.get('openai_usd') or c['expand2_openai_usd'])}")
    m = store.kv_json(con, "raspolozenje", {}) or {}
    b = (m.get("okviri") or {}).get("24h") or {}
    from makroinf import mood
    md = (f"; raspoloženje 24 h: {mood.VERDICT['hr'].get(b.get('presuda'), '—').lower()} ({b.get('n', 0)} računa)"
          if b else "")
    return (
        f"{store.PREFIX}sat: računi {st.get('aktivan', 0)} aktivnih, {st.get('odbijen', 0)} odbijenih, "
        f"{st.get('needs_owner_confirm', 0)} čeka potvrdu vlasnika; objave {n_tw} (+{n_new} u satu), klasificirano "
        f"{n_cls}, makro izjava {n_calls}; epizode {summ.get('episodes', 0)} (izmjereno "
        f"{oc.get('hit', 0) + oc.get('miss', 0) + oc.get('flat', 0)}, čeka {oc.get('ceka', 0)}); s dovoljno dokaza "
        f"{summ.get('enough', 0)} računa; naknadno nedostupno {gone} od {sum(dl.values())} provjerenih; twitterapi pilot "
        f"{_usd(tp)} / {_usd(c['pilot_twapi_usd'])} ({pilot}), danas {_usd(td)} / {_usd(c['day_twapi_usd'])}; OpenAI "
        f"pilot {_usd(op)} / {_usd(c['pilot_openai_usd'])}, danas {_usd(od)} / {_usd(c['day_openai_usd'])}; indeks "
        f"najtočnijih BTC {_idx(r[0][0] if r else None)} ({r[0][1] if r else 0} računa); ulaz u demo: "
        f"{STATE_HR.get(ul.get('state'), ul.get('state') or 'na čekanju')}{exp}{md}")


def lines(con, now=None):
    d = data(con=con)
    if not d:
        return [store.PREFIX + "još nema podataka"]
    out = [hour_line(con, now)]
    top = [r for r in rank_rows(d, 5) if r["presuda"] != "nedovoljno dokaza"]
    if top:
        out.append(store.PREFIX + "najtočniji: " + "; ".join(
            f"@{r['handle']} {pct(r['pogodak'])} [{pct(r['wilson95'][0])}–{pct(r['wilson95'][1])}] n={r['n_epizoda']}, "
            f"prema najboljoj baznoj {pp(r['razlika'])}" for r in top))
    else:
        out.append(store.PREFIX + "još nijedan račun nema 10+ izmjerenih epizoda (nedovoljno dokaza)")
    q = d.get("provjera") or {}
    if q:
        out.append(store.PREFIX + f"provjera klasifikacije: {'prošla' if q.get('passed') else 'nije prošla'} "
                                  f"({q.get('why')})" + ("; vlasnik forsirao proširenje" if q.get("forced") else "")
                                  + ("; proširenje po izričitom nalogu vlasnika (vrata nadjačana)" if q.get("nalog")
                                     else ""))
    return out


# ---------- output/makroinf.md ----------------------------------------------------------------------------------------

def markdown(d):
    s = d.get("summary") or {}
    w = d.get("walk") or {}
    L = ["# Makro influenceri", "", f"Izračun {time.strftime('%d.%m.%Y. %H:%M', time.gmtime(s.get('ts') or 0))} UTC, "
         f"{rules.RULES_VERSION} (hash {rules.RULES_HASH}).", "", "## Provjereno (iz baze)", "",
         f"- računi: {sum(1 for a in d['accounts'].values() if a['status'] == 'aktivan')} aktivnih; objava "
         f"{d['counts']['tweets']}, klasificirano {d['counts']['classified']}, makro objava {d['counts']['macro_posts']}",
         f"- epizode {s.get('episodes', 0)}; ishodi {s.get('outcomes')}; preskočeno {s.get('skipped')}",
         f"- s dovoljno dokaza (10+ epizoda): {s.get('enough', 0)} računa", "",
         "## Rang (tri odvojene ocjene)", "",
         "| # | račun | kat. | n ep. | pogodak [Wilson 95 %] | prema najboljoj baznoj | ekonomski (prema uvijek-bik) | "
         "naknadno nedostupno | stav BTC |", "|---|---|---|---|---|---|---|---|---|"]
    for i, r in enumerate(rank_rows(d), 1):
        g = r["integritet"]
        L.append(f"| {i if r['presuda'] != 'nedovoljno dokaza' else '—'} | @{r['handle']} | {r['category']} | "
                 f"{r['n_epizoda']} | {pct(r['pogodak'])} [{pct(r['wilson95'][0])}–{pct(r['wilson95'][1])}] | "
                 f"{pp(r['razlika'])} | {pp(r['ekonomski'].get('razlika'))} | {g.get('naknadno_nedostupno', 0)} / "
                 f"{g.get('makro_izjava', 0)} | {DIR_HR.get((r['stav_btc'] or {}).get('smjer'), '—')} |")
    L += ["", "## Indeks (walk-forward, povijesno, pristrano)", ""]
    if w.get("available"):
        for k in ("trening", "validacija", "test_zakljucan", "svi_test", "kontra_test"):
            x = w.get(k) or {}
            L.append(f"- {k}: n={x.get('n')}, pogodak {pct(x.get('pogodak'))} {x.get('wilson95')}, uvijek-bik "
                     f"{pct(x.get('uvijek_bik'))} ({x.get('od')} – {x.get('do')})")
        L.append(f"- K={w.get('k')}, prag {w.get('thr')}, klastera {w.get('klasteri')}")
    else:
        L.append(f"- {w.get('why') or 'još nema'}")
    ul = d.get("ulaz") or {}
    L += [f"- ulaz u demo (veliki/makro): {STATE_HR.get(ul.get('state'), ul.get('state'))} — {ul.get('why')}", "",
          "## Pretpostavka / pristranosti", "",
          "- povijesni indeks vidi samo objave koje su preživjele do našeg dohvata; računi su odabrani jer su poznati sada",
          f"- košara memeova: bez podataka za {', '.join(d['meme_cov']['bez_podataka']) or 'nijedan'} (pristranost "
          "preživjelih gdje CoinGecko više nema povijest)",
          "- ukupno tržište mjereno BTC-om; altovi = jednaka težina ETH, SOL, XRP, ADA, LINK, AVAX, DOGE",
          "- oznake izjava daje gpt-5-mini (provjera: output/makroinf_provjera.md)", ""]
    return "\n".join(L) + "\n"


def write(con):
    d = data(con=con)
    if not d:
        return
    try:
        os.makedirs(os.path.join(store.ROOT, "output"), exist_ok=True)
        with open(os.path.join(store.ROOT, "output", "makroinf.md"), "w", encoding="utf-8") as f:
            f.write(markdown(d))
    except OSError:
        pass


# ---------- the card --------------------------------------------------------------------------------------------------

def chart_svg(rows, w=600, h=120):
    """Inline SVG: BTC (orange, scaled to its own range) and the top index (blue, -1..+1); "" with < 5 points."""
    btc = [(i, p) for i, (_d, p, _a, _b) in enumerate(rows) if p]
    ix = [(i, b if b is not None else a) for i, (_d, _p, a, b) in enumerate(rows) if (b if b is not None else a) is not None]
    if len(rows) < 5 or (len(btc) < 5 and len(ix) < 5):
        return ""
    n = max(1, len(rows) - 1)
    out = []
    if len(btc) >= 2:
        lo, hi = min(p for _i, p in btc), max(p for _i, p in btc)
        sp = (hi - lo) or 1.0
        pts = " ".join(f"{i * w / n:.1f},{h - 4 - (h - 8) * (p - lo) / sp:.1f}" for i, p in btc)
        out.append(f'<polyline points="{pts}" fill=none stroke="#d97706" stroke-width=2 />')
    if len(ix) >= 2:
        pts = " ".join(f"{i * w / n:.1f},{h / 2 - (h / 2 - 4) * v:.1f}" for i, v in ix)
        out.append(f'<polyline points="{pts}" fill=none stroke="#2563eb" stroke-width=2 />')
    zero = f'<line x1=0 y1={h / 2} x2={w} y2={h / 2} stroke="#cbd5e1" stroke-dasharray="4 4" />'
    return (f'<svg viewBox="0 0 {w} {h}" width="100%" height="{h}" preserveAspectRatio="none" role=img '
            f'aria-label="indeks najtočnijih prema BTC-u">{zero}{"".join(out)}</svg>'
            '<p class=mut style="font-size:12px;margin:2px 0 8px"><span style="color:#2563eb">■</span> indeks najtočnijih '
            '(−1 … +1; povijesno do prvog dohvata, dalje prospektivno) · <span style="color:#d97706">■</span> BTC</p>')


def card_html(sec, item, esc, owner=True, path=None):
    """"Makro influenceri" under Ostalo (owner only): the rank table with the three scores, n, the stance now,
    "naknadno nedostupno", the index vs BTC, the quality check, the DEMO input state, the costs, the open owner
    decisions (candidates). Nothing before the first database."""
    if not owner:
        return ""
    d = data(path)
    if not d or not d.get("accounts"):
        return ""
    s = d.get("summary") or {}
    ix = (d.get("index") or {}).get("BTC:prospektivno:top") or {}
    q = d.get("provjera") or {}
    meta = (f"{sum(1 for a in d['accounts'].values() if a['status'] == 'aktivan')} računa, {s.get('enough', 0)} s "
            f"dovoljno dokaza; indeks BTC {_idx(ix.get('v'))}; provjera "
            f"{'prošla' if q.get('passed') else 'nije prošla' if q.get('ts') else 'čeka'}")
    rows = []
    for i, r in enumerate(rank_rows(d, 25), 1):
        few = r["presuda"] == "nedovoljno dokaza"
        g = r["integritet"]
        rows.append(f"<tr><td>{'—' if few else i}</td><td>@{esc(r['handle'])} <span class=mut>{esc(r['category'] or '')}"
                    f"</span></td><td>{r['n_epizoda']}</td><td>{'nedovoljno dokaza' if few else esc(pct(r['pogodak']))}"
                    f" <span class=mut>[{esc(pct(r['wilson95'][0]))}–{esc(pct(r['wilson95'][1]))}]</span></td>"
                    f"<td>{esc(pp(r['razlika']))}</td><td>{esc(pp(r['ekonomski'].get('razlika')))}</td>"
                    f"<td>{g.get('naknadno_nedostupno', 0)}/{g.get('makro_izjava', 0)}</td>"
                    f"<td>{esc(DIR_HR.get((r['stav_btc'] or {}).get('smjer'), '—'))}</td></tr>")
    table = ("<table><tr><th>#</th><th>račun</th><th>n ep.</th><th>pogodak</th><th>prema baznoj</th><th>ekonomski</th>"
             "<th>naknadno nedostupno</th><th>stav BTC</th></tr>" + "".join(rows) + "</table>") if rows else \
        "<p class=mut>Još nema izmjerenih epizoda (pilot u tijeku).</p>"
    w = d.get("walk") or {}
    ul = d.get("ulaz") or {}
    from makroinf import index as mindex
    ev = mindex.incremental_ev()
    ev_txt = (f"midcap EV bez indeksa {ev['bez'].get('ev_pct')} %, s indeksom {ev['s_indeksom'].get('ev_pct')} % "
              f"(razlika {ev.get('razlika_pp')} pp, n {ev['s_indeksom'].get('n')})" if ev.get("bez") else
              f"TODO: {ev.get('todo')}")
    wt = (f"validacija {pct((w.get('validacija') or {}).get('pogodak'))} (n {(w.get('validacija') or {}).get('n')}, "
          f"uvijek-bik {pct((w.get('validacija') or {}).get('uvijek_bik'))}), zaključani test "
          f"{pct((w.get('test_zakljucan') or {}).get('pogodak'))} (n {(w.get('test_zakljucan') or {}).get('n')})"
          if w.get("available") else (w.get("why") or "još nema walk-forwarda"))
    cs = d.get("costs") or {}
    tot = cs.get("ukupno") or {}
    cost_txt = "; ".join(f"{src} " + ", ".join(f"{ph} {_usd(v)}" for ph, v in phs.items()) for src, phs in tot.items()) \
        or "još nema troška"
    pend = [x for x in d.get("candidates") or [] if x.get("status") == "needs_owner_confirm"]
    cand = "".join(f"<li>za „{esc(x['for_name'])}”: @{esc(x['handle'])} ({(x.get('followers') or 0):,} pratitelja) — "
                   f"{esc((x.get('bio') or '')[:80])}</li>" for x in pend[:8])
    rej = [a for a in d["accounts"].values() if a["status"] in ("odbijen", "needs_owner_confirm")]
    rej_txt = ", ".join(f"@{a['handle'].lstrip('?')} ({a.get('why') or a['status']})" for a in rej[:12])
    inner = (f"{table}{chart_svg(d.get('chart') or [])}"
             f"<p class=mut>Indeks: {esc(wt)}. Ulaz u demo (veliki/makro): <b>{esc(STATE_HR.get(ul.get('state'), ul.get('state') or 'na čekanju'))}</b>"
             f" — {esc(ul.get('why') or '')}. Dodatni EV: {esc(ev_txt)}.</p>"
             f"<p class=mut>Provjera klasifikacije: {esc(q.get('why') or 'čeka kraj pilota')}"
             f"{' (vlasnik forsirao)' if q.get('forced') else ''}. Trošak dosad: {esc(cost_txt)}.</p>"
             + _order_html(path, esc)
             + (f"<p class=mut>Čeka tvoju potvrdu (racuni_vlasnik.json → potvrdi):</p><ul>{cand}</ul>" if cand else "")
             + (f"<p class=mut>Nerazriješeni / odbijeni: {esc(rej_txt)}</p>" if rej_txt else "")
             + "<p class=mut>Brisanja: „naknadno nedostupno” = objavu više ne vidimo (obrisana, nedostupna ili račun "
               "zaključan); bez kazne i bez optužbi.</p>")
    return sec("Makro influenceri", meta, inner, sid="makroinf")


def _order_html(path, esc):
    """The owner's card: his order of 15.11. navečer (the gate overridden), discovery, the estimate, the spend per
    phase (owner only, so costs are fine here)."""
    con = store.ro(path)
    if con is None:
        return ""
    try:
        from makroinf import discover
        sm = discover.summary(con)
    except Exception:  # noqa: BLE001
        return ""
    finally:
        con.close()
    n = sm.get("nalog")
    if not n:
        return ""
    est = sm.get("procjena") or {}
    sp = sm.get("trosak_po_fazi") or {}
    v2 = sm.get("val2") or {}
    n2, e2 = v2.get("nalog") or {}, v2.get("procjena") or {}
    wave2 = ("<p class=mut>2. val po tvom nalogu (" + esc(n2.get("kada") or "") + f": „{esc(n2.get('citat') or '')}”): prag "
             f"{(n2.get('prag_pratitelja') or 0) // 1000}k pratitelja, strop {n2.get('cilj', 0)} računa (sada "
             f"{v2.get('racuna', 0)}); otkrivanje: {esc(v2.get('korak') or '—')}, ponovno razmotreno "
             f"{v2.get('ponovno') or 0}, dodano {v2.get('dodano', 0)}; procjena twitterapi "
             f"{_usd((e2.get('twapi') or {}).get('ukupno'))}, potrošeno {_usd((v2.get('potroseno') or {}).get('twapi'))} / "
             f"{_usd((v2.get('stropovi') or {}).get('twapi'))}; OpenAI procjena {_usd((e2.get('openai') or {}).get('ukupno'))}, "
             f"potrošeno {_usd((v2.get('potroseno') or {}).get('openai'))} / "
             f"{_usd((v2.get('stropovi') or {}).get('openai'))}.</p>") if n2 else ""
    return ("<p class=mut>Proširenje po tvom nalogu (" + esc(n.get("kada") or "") + "): "
            + ("vrata provjere kvalitete nadjačana nalogom; " if n.get("provjera_nadjacana") else "")
            + f"otkrivanje: {esc(sm.get('korak') or '—')}, kandidata {sm.get('kandidata', 0)}, dodano "
            f"{sm.get('dodano', 0)}; procjena twitterapi {_usd((est.get('twapi') or {}).get('ukupno'))} / "
            f"{_usd((est.get('stropovi') or {}).get('twapi'))}, OpenAI {_usd((est.get('openai') or {}).get('ukupno'))} / "
            f"{_usd((est.get('stropovi') or {}).get('openai'))}. Stvarno po fazi: "
            + esc(", ".join(f"{k} {_usd(v)}" for k, v in sp.items()) or "još ništa") + ".</p>" + wave2)


# ---------- MCP, critic, morning report ---------------------------------------------------------------------------------

def mcp(args=None):
    """get_macro_influencers (read-only): the rank with the three scores, the stances now, the index and its
    walk-forward, the DEMO input state, the quality check, the incremental EV, the costs; handle -> one account's
    episodes and thesis register."""
    a = args or {}
    try:
        lim = max(1, min(300, int(a.get("limit") or 30)))
    except (TypeError, ValueError):
        lim = 30
    d = data()
    if not d or not d.get("accounts"):
        return {"available": False, "note": "makro influenceri: pilot još nije počeo (prvi krug ~8 min nakon deploya)"}
    from makroinf import index as mindex
    out = {"available": True, "rules": {"version": rules.RULES_VERSION, "hash": rules.RULES_HASH,
                                        "index_hash": mindex.INDEX_HASH},
           "summary": {k: (d["summary"] or {}).get(k) for k in ("ts", "calls", "episodes", "outcomes", "skipped",
                                                                 "enough", "accounts_scored")},
           "rank": rank_rows(d, lim), "index_now": d.get("index"), "walk_forward": d.get("walk"),
           "demo_input": d.get("ulaz"), "quality_check": d.get("provjera"), "incremental_ev": mindex.incremental_ev(),
           "costs": d.get("costs"), "deletions": d.get("deletions"),
           "owner_to_confirm": [x for x in d.get("candidates") or [] if x.get("status") == "needs_owner_confirm"],
           "note": "deletions = 'naknadno nedostupno' (no penalty, no accusation); historic index is biased (only posts "
                   "that survived until fetched); real money never from this tool"}
    con = store.ro()
    try:   # 15.11. navečer: the owner's expansion order and the market mood (fresh)
        from makroinf import discover, mood
        if con is not None:
            out["expansion"] = discover.summary(con)
            m = mood.load(con) or {}
            out["mood"] = {"t": m.get("t"), "rules": mood.MOOD_RULES, "windows": {
                k: {x: b.get(x) for x in ("n", "broj", "strane", "strane_pond", "presuda", "presuda_pond")}
                for k, b in (m.get("okviri") or {}).items()}, "changes": (m.get("promjene") or [])[:20]}
    except Exception as e:  # noqa: BLE001
        out["expansion_error"] = f"{type(e).__name__}"
    finally:
        if con is not None:
            con.close()
    h = (a.get("handle") or "").lstrip("@")
    if h:
        con = store.ro()
        try:
            eps = store.q(con, """SELECT eid, horizon, asset, direction, t_call, t_start, res, ret, thr, level, follow,
                hz, n_calls, first_id FROM outcomes WHERE lower(handle) = lower(?) AND rules_v = ? ORDER BY t_call DESC
                LIMIT 60""", (h, rules.RULES_VERSION))
            reg = store.q(con, "SELECT asset, ts, event, eid FROM register WHERE lower(handle) = lower(?) ORDER BY ts "
                               "DESC LIMIT 60", (h,))
        finally:
            if con is not None:
                con.close()
        keys = ("eid", "horizon", "asset", "direction", "t_call", "t_start", "res", "ret", "thr", "level", "follow", "hz",
                "n_calls", "first_id")
        out["account"] = {"handle": h, "scores": d["scores"].get(h) or next(
            (v for k, v in d["scores"].items() if k.lower() == h.lower()), None),
            "episodes": [dict(zip(keys, r)) for r in eps],
            "register": [dict(zip(("asset", "ts", "event", "eid"), r)) for r in reg]}
    return out


def critic_summary():
    d = data()
    if not d or not (d.get("summary") or {}).get("ts"):
        return None
    from makroinf import index as mindex
    top = rank_rows(d, 10)
    return {"pravila": f"{rules.RULES_VERSION} ({rules.RULES_HASH})", "epizoda": d["summary"].get("episodes"),
            "s_dovoljno_dokaza": d["summary"].get("enough"),
            "rang_top10": [{k: r[k] for k in ("handle", "category", "n_epizoda", "pogodak", "wilson95", "razlika",
                                              "presuda", "ekonomski", "integritet", "stav_btc")} for r in top],
            "indeks_sada": {k: v for k, v in (d.get("index") or {}).items() if k.startswith("BTC")},
            "walk_forward": {k: (d.get("walk") or {}).get(k) for k in ("k", "thr", "validacija", "test_zakljucan",
                                                                       "kontra_test", "mode")},
            "ulaz_u_demo": d.get("ulaz"), "dodatni_ev": mindex.incremental_ev(), "provjera": {
                k: (d.get("provjera") or {}).get(k) for k in ("passed", "why", "by_cat", "forced")},
            "trosak": d.get("costs"),
            "napomena": "tri odvojene ocjene; n < 10 epizoda = nedovoljno dokaza; povijesni indeks pristran (preživjele "
                        "objave); ulaz u veliki/makro samo DEMO (NEVER_LIVE)"}


def morning(now=None):
    """{"top3": [...], "index": {"sada", "prije", "n"}, "ulaz"} for the morning report, None before scores."""
    d = data()
    if not d or not d.get("scores"):
        return None
    top = [r for r in rank_rows(d) if r["presuda"] != "nedovoljno dokaza"][:3]
    ix = (d.get("index") or {}).get("BTC:prospektivno:top") or {}
    prev = (d.get("index_prev") or {}).get("BTC:prospektivno:top")
    from makroinf import mood
    m = mood.load() or {}
    return {"top3": [{"handle": r["handle"], "pogodak": r["pogodak"], "n": r["n_epizoda"],
                      "stav": DIR_HR.get((r["stav_btc"] or {}).get("smjer"))} for r in top],
            "index": {"sada": ix.get("v"), "prije": prev, "n": ix.get("n")},
            "ulaz": (d.get("ulaz") or {}).get("state"), "enough": d["summary"].get("enough", 0),
            "raspolozenje": (m.get("okviri") or {}).get("24h")}


def morning_text(m):
    if not m:
        return "Makro influenceri: još nema izmjerenih epizoda (pilot)."
    tops = ", ".join(f"@{t['handle']} ({pct(t['pogodak'])}, n {t['n']}, sada BTC {t['stav'] or 'bez stava'})"
                     for t in m["top3"]) or "još nitko nema 10+ izmjerenih epizoda"
    ix = m.get("index") or {}
    chg = ("" if ix.get("sada") is None or ix.get("prije") is None else
           f", promjena {(ix['sada'] - ix['prije']):+.2f}".replace(".", ","))
    from makroinf import mood
    md = (" Raspoloženje 24 h: " + mood.line(m["raspolozenje"])) if (m.get("raspolozenje") or {}).get("n") else ""
    return (f"Makro influenceri: najtočniji {tops}. Indeks najtočnijih BTC {_idx(ix.get('sada'))} ({ix.get('n') or 0} "
            f"računa{chg}); ulaz u demo: {STATE_HR.get(m.get('ulaz'), m.get('ulaz') or 'na čekanju')}.{md}")
