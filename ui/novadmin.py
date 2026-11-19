"""/novcanici-admin: "Novčanici: administracija" (19.11., vlasnik: "The admin must have a dashboard with more data about
the wallets than an ordinary user, in any case ... most important, insider wallets. That item is the most important to
me, I want a very big focus there.").

The OWNER only (run_ui.py checks trade/settings.is_owner before anything is read, like /kol-insajderi and /stanje);
the page itself never decides access. Built from read-only reads (ui/novpodaci.py) and kept by ui/pagecache under a
key of its own (45 s fresh), so a phone gets it at once; nothing here reaches the network.

  1  Stanje           pumps covered, Helius today / cap, the last pass, the social window, the real-money pause
  2  Kupuje prije pumpe   one row per owner group (paginated, PAGE_N), confirmed first, then pumps >= 15M; a filter
                      (confirmed only, tier); the row opens: every pump, the group's wallets, what links them
  3  Bundle novčanici  i2_bundle
  4  Isključeni i zašto  counts per reason, each with its list
  5  Test kopiranja   60 s, brzo 2 s (Pretpostavka klizanja 1 %), random wallets per MC bucket; the verdict line
  6  Povijesni PnL    wallets.db per listed wallet (the groups' wallets and the best scored), the history queue
  7  Veliki holderi   holderi.db holder_pos: the profitable holders of the midcaps, longest held first
  8  Birdeye          insajderi/birdeye.py: the month's CU, the pump tokens read, the cross-check, the new candidates

20.11. (vlasnik na mobitelu: "Nista ja ovdje ne razumijem..."): the app's rule since 10.11. on this page too: the first
screen is three plain answers (ui/novjasno.py: what we found, does copying pay, what the tool does next), then the ten
most interesting wallets as cards in sentences ("Prikaži sve" pages through all of them), who was left out and why in
one paragraph, and every section above under ONE collapsed block "Detalji za provjeru", each opening with one plain
sentence and with plain labels (the technical word in brackets only where needed).

Every value that is not stored yet says "nije još izmjereno"; every empty section says when its data comes.
"""
import time
from urllib.parse import quote, urlencode

from ui import novkartice as K
from ui import novpodaci as P
from ui import redak as rd

PATH = "/novcanici-admin"
TITLE = "Novčanici: administracija"
PAGE_N = 50
NOT_YET = "nije još izmjereno"
EMPTY_NIGHT = "još nema podataka: puni ih prva noćna obrada (od 1 do 6 sati)"

CSS = """<style>
.na h2.ms-h2{margin-top:30px}
.na-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:10px;margin:14px 0 6px}
.na-st{border:1px solid var(--line);border-radius:12px;padding:10px 12px;background:var(--card);min-width:0}
.na-st span{display:block;font-size:12.5px;color:var(--mut);line-height:1.3}
.na-st b{display:block;font-size:17px;font-weight:700;margin:3px 0 1px;overflow-wrap:anywhere}
.na-st small{display:block;font-size:12.5px;color:var(--mut);line-height:1.35;overflow-wrap:anywhere}
.na-st.warn b{color:var(--warn)}.na-st.good b{color:var(--good)}
.na-f{display:flex;flex-wrap:wrap;gap:6px;margin:10px 0 0;font-size:13.5px}
.na-f a{border:1px solid var(--line);border-radius:999px;padding:4px 11px;color:var(--fg);text-decoration:none;background:var(--card)}
.na-f a.on{border-color:var(--acc);color:var(--acc);font-weight:600}
.na-pg{display:flex;gap:12px;align-items:center;font-size:13.5px;margin:10px 0 0;color:var(--mut)}
.na-pg a{color:var(--acc);text-decoration:none}
.na.ms-page{max-width:none}
.na .rt{min-width:0}.na .rt th{white-space:normal;vertical-align:bottom;line-height:1.25;padding:9px 6px}
.na .rt td{padding:9px 6px}
.na .rt td.na-w{text-align:left;white-space:nowrap;min-width:0}
.na .rt td.na-w code{font-size:12.5px;white-space:nowrap;background:var(--soft);border-radius:5px;padding:1px 5px;
 color:var(--fg);display:inline-block;max-width:100%}
.na .nk-cp{font:inherit;font-size:12px;line-height:1.4;border:1px solid var(--line);border-radius:6px;background:var(--card);
 color:var(--fg);padding:1px 7px;margin:3px 6px 0 0;cursor:pointer;min-height:0;box-shadow:none;font-weight:500}
.na .nk-cp:hover{border-color:var(--acc);color:var(--acc)}
.na table.cards{min-width:0!important}.na .rt-d td{max-width:calc(100vw - 32px)}
.na-in p{overflow-wrap:anywhere}.na-in li a{font-size:12.5px;color:var(--acc);text-decoration:none;font-weight:500}
.na .rt td.na-w a{font-weight:500;font-size:12.5px;color:var(--acc)}
.na .rt td.na-l{text-align:left}.na .rt td.na-hist{white-space:normal;min-width:130px;max-width:180px}
.na .rt .ok{color:var(--good);font-weight:600}
.na-in{display:block;white-space:normal}
.na-in table{border-collapse:collapse;width:100%;font-size:13px;margin:6px 0 10px;background:var(--card)}
.na-in th,.na-in td{padding:5px 6px;border-bottom:1px solid var(--line);text-align:right;white-space:nowrap}
.na-in th:first-child,.na-in td:first-child{text-align:left}
.na-in .scr{overflow-x:auto;max-width:calc(100vw - 48px)}
.na-in ul{margin:4px 0 8px;padding-left:18px}.na-in li{margin:3px 0;overflow-wrap:anywhere}
.na-in code{word-break:break-all}
.na-ex details{border-bottom:1px solid var(--line);padding:8px 0}
.na-ex summary{cursor:pointer;font-size:14.5px}.na-ex summary b{font-weight:700}
.na-ex li{font-size:13px;color:var(--mut);margin:4px 0;overflow-wrap:anywhere}
.na-v{font-size:15px;font-weight:600;margin:10px 0 4px}
.na-v.warn{color:var(--warn)}.na-v.good{color:var(--good)}.na-v.bad{color:var(--bad)}
.na-empty{font-size:14px;color:var(--mut);border:1px dashed var(--line);border-radius:12px;padding:12px 14px;margin:12px 0 0;
 line-height:1.45}
.na-note{font-size:12.5px;color:var(--mut);margin:8px 0 0;line-height:1.45}
</style>"""


def _t(ts, fmt="%d.%m.%Y. %H:%M"):
    return time.strftime(fmt, time.localtime(int(ts))) if ts else rd.DASH


def _empty(text):
    return f'<p class=na-empty>{rd.h(text)}</p>'


def _stat(label, value, sub=None, tone=""):
    return (f'<div class="na-st {tone}"><span>{rd.h(label)}</span><b>{rd.h(value)}</b>'
            + (f'<small>{rd.h(sub)}</small>' if sub else "") + '</div>')


def _how(how):
    """How the Helius day cap was set, in plain Croatian (never a config key)."""
    if not how:
        return None
    if "helius_day" in how:
        return "dnevni strop"
    if "bez mjerenja" in how:
        return "dnevni strop: procjena (stari poslovi još nisu izmjereni)"
    return "dnevni strop: " + how.split(" (")[0]


def _n(x):
    try:
        return f"{float(x):.6g}"
    except (TypeError, ValueError):
        return "-1e9"


def plain_why(text):
    """The data layer's reason in the page's words (skok, not pumpa; M $, not M)."""
    import re as _re
    t = str(text or "")
    for a, b in (("prodao u pumpu", "prodao dok je rastao"), ("prodali u pumpu", "prodali dok je rastao"),
                 ("do ≥ 15M", "do 15 M $ ili više"), ("do 2-15M", "do 2–15 M $"), ("pumpi", "skokova"),
                 ("pumpe", "skoka"), ("pumpu", "skok"), ("pumpa", "skok")):
        t = t.replace(a, b)
    return _re.sub(r"\bkandidat\b", "skupina s dva tokena", t)


# ---------- 1. status ------------------------------------------------------------------------------------------------

def status_html(con, pp, now):
    cards = []
    if pp:
        f15 = pp.get("fetched15")
        cards.append(_stat("Skokovi tokena od 15 M $ naviše", f"{rd.num(pp.get('covered15'))} pregledano od {rd.num(pp.get('pumps15'))}",
                           (f"podaci skinuti za {rd.num(f15)}, čeka {rd.num(max(0, (pp.get('pumps15') or 0) - (f15 or 0)))}"
                            if f15 is not None else f"skinuti podaci: {NOT_YET}")))
        cards.append(_stat("Skokovi tokena od 2 do 15 M $", f"{rd.num(pp.get('covered2'))} pregledano od {rd.num(pp.get('pumps2'))}",
                           (f"podaci skinuti za {rd.num(pp.get('fetched2'))}" if pp.get("fetched2") is not None
                            else f"skinuti podaci: {NOT_YET}")))
    else:
        cards.append(_stat("Skokovi tokena", NOT_YET, "nakon prve noćne obrade"))
    spent, cap, how = P.helius(con, now)
    cards.append(_stat("Potrošnja izvora podataka danas", (f"{rd.num(spent) if spent is not None else 0} od {rd.num(cap)} jedinica"
                                        if cap is not None else (rd.num(spent) if spent is not None else NOT_YET)),
                       _how(how), "warn" if cap and spent and spent >= cap else ""))
    run = P.last_run(con)
    stg = P.stages(con) if con is not None else None
    if run:
        det = run.get("detail") or {}
        dur = det.get("duration_s") or det.get("trajanje_s")
        cut = det.get("cut") if "cut" in det else det.get("prekinut")
        if stg:   # 19.11.: the pass stores its stage seconds and whether the time limit cut it (i2_kv stage_s)
            dur = sum(float(v) for k, v in stg.items() if k not in ("ts", "kind", "cut") and isinstance(v, (int, float)))
            cut = bool(stg.get("cut"))
            if stg.get("kind") and stg.get("ts"):
                run = {**run, "kind": stg["kind"], "ts": stg["ts"]}
        kind = {"night": "noćna", "once": "nakon nove verzije", "incr": "dopunska", "report": "samo izvještaj"}.get(
            run.get("kind"), "obrada")
        cards.append(_stat("Zadnja obrada", f"{kind} · {rd.ago(run['ts'], now)}",
                           f"{_t(run['ts'])}; trajala {rd.num(dur) + ' s' if dur is not None else NOT_YET}; prekinuta jer je "
                           f"isteklo vrijeme: {('da' if cut else 'ne') if cut is not None else NOT_YET}; potrošeno "
                           f"{rd.num(run.get('credits'))} jedinica podataka"))
    else:
        cards.append(_stat("Zadnja obrada", NOT_YET, "nijedna obrada još nije zapisana"))
    st = P.social()
    if st:
        word = {"open": "otvoren", "closed": "zatvoren", "first": "čeka prvi start", "always": "uvijek otvoren",
                "nopersist": "otvoren (bez trajnog stanja)"}.get(st.get("mode"), st.get("mode") or "?")
        from ops import drustveni
        cards.append(_stat("Osvježavanje influencera i Telegrama", word,
                           f"sljedeći prozor {drustveni.when(st['next'])}" if st.get("next") else None))
    paused = P.pause_on()
    cards.append(_stat("Pravi novac", "pauziran" if paused else "nije pauziran",
                       "demo prati novčanike bez pravog novca" if paused else None, "warn" if paused else "good"))
    return f'<div class=na-grid>{"".join(cards)}</div>'


# ---------- 2. groups ------------------------------------------------------------------------------------------------

def _link(qs, **over):
    q = {k: v for k, v in {**{k: qs.get(k) for k in ("f", "t", "p")}, **over}.items() if v}
    return PATH + ("?" + urlencode(q) if q else "") + "#grupe"


def sh6(w):
    """The list rows' short address: first 6 … last 6 (the full one is in the title, the copy payload and the detail)."""
    w = str(w or "")
    return w if len(w) <= 14 else f"{w[:6]}…{w[-6:]}"


def _wcell(w, extra=""):
    """One wallet cell of a list row: the short address (monospace, full one in title), copy, Solscan, extra."""
    w = str(w or "")
    return (f'<td class=na-w><code translate=no title="{rd.h(w)}">{rd.h(sh6(w))}</code><br>'
            f'<button type=button class=nk-cp data-cp="{rd.h(w)}" aria-label="Kopiraj adresu">Kopiraj</button>'
            f'<a href="https://solscan.io/account/{quote(w)}" target=_blank rel="noopener noreferrer">Solscan ↗</a>'
            + (f' <span class=mut>{extra}</span>' if extra else "") + '</td>')


def _wallet_cell(ws, owner):
    ws = ws or [owner]
    more = len(ws) - 1
    return _wcell(ws[0], f"+{more} u grupi" if more > 0 else "")


def _pump_rows(pumps, now):
    if not pumps:
        return '<p class=na-note>Pojedinačni skokovi još nisu spremljeni za ovu skupinu.</p>'
    out = []
    for p in pumps[:40]:
        tok = p.get("token") or ""
        sym = rd.h(p.get("symbol") or K.short(tok))
        lead = p.get("lead_s")
        if lead is None and p.get("buy_ts") and p.get("t0"):
            lead = p["t0"] - p["buy_ts"]
        rel = (f"{rd.num(lead / 60)} min prije skoka" if lead is not None and lead >= 0 else
               f"{rd.num(-lead / 60)} min nakon" if lead is not None else rd.DASH)
        tier = {"pumpa15": "15 M $ i više", "pumpa2": "2–15 M $"}.get(p.get("tier"), rd.DASH)
        out.append(f'<tr><td><a href="/token/{quote(tok)}" translate=no>{sym}</a></td><td>{rd.h(tier)}</td>'
                   f'<td>{rd.h(_t(p.get("t0"), "%d.%m. %H:%M"))}</td><td>{rd.h(rel)}</td>'
                   f'<td>{rd.h(rd.sol(p.get("sol_in"), 2))}</td><td>{rd.h(rd.sol(p.get("sol_out"), 2))}</td>'
                   f'<td>{"da" if p.get("sold_into") else "ne"}</td>'
                   f'<td class=na-l><code translate=no>{rd.h(K.short(p.get("wallet")))}</code></td></tr>')
    more = f'<p class=na-note>Prikazano 40 od {len(pumps)} skokova.</p>' if len(pumps) > 40 else ""
    return ('<div class=scr><table><thead><tr><th>Token</th><th>Vrijednost na vrhu</th><th>Skok</th><th>Kupnja</th><th>Uloženo</th>'
            '<th>Izašlo</th><th>Prodao u rastu</th><th>Novčanik</th></tr></thead><tbody>' + "".join(out)
            + '</tbody></table></div>' + more)


def _links_html(links, members):
    if len(members) < 2:
        return '<p class=na-note>Skupina ima jedan novčanik.</p>'
    if not links:
        return ('<p class=na-note>Povezani su istim izvorom novca ili time što često trguju zajedno; koja je veza točno, '
                'nije spremljeno po novčaniku.</p>')
    bits = []
    for kind, who, n in links:
        if kind == "platitelj":
            bits.append(f'<li>isti novčanik plaća naknade za {rd.num(n)} od njih: <code translate=no>{rd.h(who)}</code></li>')
        else:
            bits.append(f'<li>kupovali su u istom trenutku (istom bloku) {rd.num(n)} put{"a" if 2 <= n % 10 <= 4 else "" if n == 1 else "a"}</li>')
    return '<ul>' + "".join(bits) + '</ul>'


AGREE = {1: "slaže se", 0: "ne slaže se", None: "još nema povijesti"}   # with the result on the jumps


def hist_sentence(h, n_members=None):
    """"povijest članova: ocijenjeno X od Y, u plusu Z %, ostvareno N SOL; slaže se s rezultatom na pumpama" (i2_pp_hist,
    the members' own scored history; a report, not a selection rule)."""
    if not h or not h.get("n_scored"):
        return f"izračunata za 0 od {rd.num((h or {}).get('n_members') or n_members)}; još nema povijesti."
    agree = {1: "slaže se s rezultatom na skokovima", 0: "ne slaže se s rezultatom na skokovima"}.get(
        h.get("agrees"), "još nema povijesti")
    return (f"izračunata za {rd.num(h['n_scored'])} od {rd.num(h.get('n_members'))}, u plusu "
            f"{rd.pct(h.get('profitable_share'), sign=False, frac=True)} njih, zaradili "
            f"{rd.sol(h.get('realized_sol'), 2, sign=True)}; {agree}.")


def _hist_cell(h):
    if not h:
        return '<span class=mut>još nema povijesti</span>'
    word = AGREE.get(h.get("agrees"), AGREE[None])
    tone = "ok" if h.get("agrees") == 1 else "warn" if h.get("agrees") == 0 else "mut"
    return (f'{rd.num(h.get("n_scored"))} od {rd.num(h.get("n_members"))}<br>'
            f'<span class={tone}>{rd.h(word)}</span>')


def _mjera_html(now):
    from ui import novmjera
    return novmjera.admin_html(now)


def _mjera_groups(now):
    """{gid: {"n", "measured", "mean01"}} of the "prije pumpe" sources from league/mjera.per_group ({} without data)."""
    try:
        from league import mjera
        con = P.ro(P.league_db())
        if con is None or not P.has_table(con, "signal_mjera"):
            return {}
        try:
            out = {}
            for (src, gid), d in mjera.per_group(con, now).items():
                if src in ("prije_pumpe", "prije_pumpe_kandidat"):
                    o = out.setdefault(gid, {"n": 0, "measured": 0, "_s": 0.0})
                    o["n"] += d["n"]
                    o["measured"] += d["measured"]
                    o["_s"] += (d["mean01"] or 0) * d["measured"]
            for o in out.values():
                o["mean01"] = o.pop("_s") / o["measured"] if o["measured"] else None
            return out
        finally:
            con.close()
    except Exception:  # noqa: BLE001
        return {}


def _mjera_sentence(mj, owner):
    d = mj.get(owner)
    if not d or not d["n"]:
        return "još nijedna nova kupnja (bilježi se svaka kupnja skupine)."
    mean = rd.pct(d["mean01"], 1, sign=True, frac=True) if d["mean01"] is not None else rd.DASH
    return (f"{rd.num(d['n'])} novih kupnji, zatvoreno {rd.num(d['measured'])}, u prosjeku {mean} po kupnji nakon "
            "troška (zadnjih 30 dana).")


def groups_html(con, qs, now):
    conf_only = qs.get("f") == "potvrdeni"
    tier = qs.get("t") if qs.get("t") in ("15", "2") else None
    try:
        page = max(1, min(1000, int(qs.get("p") or 1)))
    except ValueError:
        page = 1
    total = P.group_count(con, conf_only, tier)
    all_n = P.group_count(con)
    conf_n = P.group_count(con, True)
    flt = ('<div class=na-f>'
           + "".join(f'<a href="{rd.h(_link(qs, f=fv, p=None))}"{" class=on" if (qs.get("f") or "") == (fv or "") else ""}>'
                     f'{rd.h(lab)}</a>' for fv, lab in ((None, f"Sve skupine · {rd.num(all_n)}"),
                                                         ("potvrdeni", f"Samo potvrđene · {rd.num(conf_n)}")))
           + "".join(f'<a href="{rd.h(_link(qs, t=tv, p=None))}"{" class=on" if (qs.get("t") or "") == (tv or "") else ""}>'
                     f'{rd.h(lab)}</a>' for tv, lab in ((None, "Svi tokeni"), ("15", "Ima token od 15 M $"), ("2", "Ima token 2–15 M $")))
           + '</div>')
    if not all_n:
        return flt.replace("class=na-f", "class=na-f hidden") + _empty(
            f"{EMPTY_NIGHT}. Skupina ulazi ovdje kad na barem 3 tokena kupi prije skoka i proda dok token raste.")
    gs = P.groups(con, conf_only, tier, PAGE_N, (page - 1) * PAGE_N)
    pumps = P.pumps_of(con, [g["owner"] for g in gs])
    hist = P.hist_of(con, [g["owner"] for g in gs])
    mj = _mjera_groups(now)
    head = [("w", "Novčanici", "s"), ("p15", "Skokova od 15 M $", "n"), ("p2", "Skokova 2–15 M $", "n"),
            ("tok", "Tokena", "n"), ("lead", "Koliko prije skoka je kupio (vodstvo)", "n"), ("pnl", "Zaradio", "n"),
            ("hist", "Povijest novčanika", "n"), ("st", "Status", "n"), ("last", "Zadnji put", "n")]
    th = "".join(f'<th data-k="{k}" data-t="{t}" scope=col>{rd.h(lab)}</th>' for k, lab, t in head)
    body = []
    for g in gs:
        ps = pumps.get(g["owner"], [])
        conf = bool(g.get("confirmed_ts"))
        lead = g.get("med_lead_min")
        data = {"w": rd.h((g["members"] or [g["owner"]])[0].lower()), "p15": _n(g.get("n_pumps15")),
                "p2": _n(g.get("n_pumps2")), "tok": _n(g.get("n_tokens")), "lead": _n(lead), "pnl": _n(g.get("pnl_sol")),
                "st": "2" if conf else "1", "last": _n(g.get("last_seen"))}
        h = hist.get(g["owner"])
        data["hist"] = _n((h or {}).get("n_scored") if h else -1)
        attrs = " ".join(f'data-{k}="{v}"' for k, v in data.items())
        tone = rd.tone(g.get("pnl_sol"))
        body.append(
            f'<tr class=rt-r {attrs} aria-expanded="false">{_wallet_cell(g["members"], g["owner"])}'
            f'<td>{rd.h(rd.num(g.get("n_pumps15")))}</td><td>{rd.h(rd.num(g.get("n_pumps2")))}</td>'
            f'<td>{rd.h(rd.num(g.get("n_tokens")))}</td>'
            f'<td>{rd.h(rd.num(lead, 0) + " min" if lead is not None else rd.DASH)}</td>'
            f'<td class="{tone}">{rd.h(rd.sol(g.get("pnl_sol"), 2, sign=True))}</td>'
            f'<td class=na-l>{_hist_cell(h)}</td>'
            f'<td>{"<span class=ok>potvrđeno</span>" if conf else "<span class=warn>dva tokena</span>" if g.get("cls") == "kandidat" else "<span class=mut>čeka potvrdu</span>"}</td>'
            f'<td class=mut>{rd.h(rd.ago(g.get("last_seen"), now))}</td></tr>'
            f'<tr class=rt-d hidden><td colspan={len(head)}><div class=na-in>'
            f'<p><b>Zašto:</b> {rd.h(plain_why(g.get("why") or K.reason(g)))}</p>'
            f'<p><b>Povijest novčanika u skupini:</b> {rd.h(hist_sentence(h, len(g["members"])))}</p>'
            f'<p><b>Mjerenje uživo:</b> {rd.h(_mjera_sentence(mj, g["owner"]))}</p>'
            f'<p><b>Skokovi</b> ({rd.num(len(ps))})</p>{_pump_rows(ps, now)}'
            f'<p><b>Novčanici skupine</b> ({rd.num(len(g["members"]))})</p><ul>'
            + "".join(f'<li><code translate=no>{rd.h(w)}</code> <button type=button class=nk-cp data-cp="{rd.h(w)}">Kopiraj'
                      f'</button> <a href="https://solscan.io/account/{quote(w)}" target=_blank rel="noopener noreferrer">'
                      f'Solscan ↗</a></li>' for w in g["members"][:60])
            + '</ul>' + (f'<p class=na-note>+{len(g["members"]) - 60} novčanika</p>' if len(g["members"]) > 60 else "")
            + f'<p><b>Što ih povezuje</b></p>{_links_html(P.links(con, g["members"][:60]), g["members"])}'
            '</div></td></tr>')
    pages = max(1, -(-total // PAGE_N))
    pg = (f'<div class=na-pg><span>Stranica {rd.num(page)} od {rd.num(pages)} · {rd.num(total)} skupina</span>'
          + (f'<a href="{rd.h(_link(qs, p=str(page - 1)))}">← prethodna</a>' if page > 1 else "")
          + (f'<a href="{rd.h(_link(qs, p=str(page + 1)))}">sljedeća →</a>' if page < pages else "") + '</div>')
    tbl = (f'<div class=rt-wrap><table class=rt data-rt><thead><tr>{th}</tr></thead><tbody>{"".join(body)}</tbody>'
           f'</table></div>') if body else _empty("Nijedna skupina ne prolazi ovaj filter.")
    return flt + tbl + pg + ('<p class=na-note>Dodir na redak otvara skokove, novčanike skupine i što ih povezuje. '
                             'Stupci se poredaju klikom na naslov (unutar stranice). Statistika, ne optužba.</p>')


BUNDLE_KIND = {"isti blok": "u istom trenutku", "udio ranih kupnji": "velik dio ranih kupnji"}


# ---------- 3. bundles -----------------------------------------------------------------------------------------------

def bundles_html(con, now):
    bs = P.bundles(con, 50)
    if not bs:
        return _empty(f"{EMPTY_NIGHT}. Ovdje ulaze 3 ili više novčanika jednog vlasnika ili platitelja koji kupuju u "
                      "istom trenutku, ili skupina koja nosi 30 % ili više ranih kupnji, na barem 2 skoka.")
    syms = P.demo_tokens(con, [t for b in bs for t in b["tokens"]])
    head = ("Skupina", "Kako kupuju", "Novčanika", "Skokova", "Od 15 M $", "Udio u ranim kupnjama", "Prodali u rastu",
            "Zadnji put")
    th = "".join(f'<th data-k="c{i}" data-t="{"s" if i < 2 else "n"}" scope=col>{rd.h(h)}</th>' for i, h in enumerate(head))
    rows = []
    for b in bs:
        bid = b["bid"]
        who = "vlasnik" if bid.startswith("o:") else "platitelj" if bid.startswith("p:") else ""
        sh = b.get("share_med")
        data = {"c0": rd.h(bid.lower()), "c1": rd.h(b.get("kind") or ""), "c2": _n(b.get("n_members")),
                "c3": _n(b.get("n_pumps")), "c4": _n(b.get("n_pumps15")), "c5": _n(sh), "c6": _n(b.get("sold_into")),
                "c7": _n(b.get("last_seen"))}
        attrs = " ".join(f'data-{k}="{v}"' for k, v in data.items())
        toks = ", ".join(f'<a href="/token/{quote(t)}" translate=no>{rd.h(syms.get(t) or K.short(t))}</a>'
                         for t in b["tokens"][:20])
        rows.append(
            f'<tr class=rt-r {attrs} aria-expanded="false"><td class=na-w><code translate=no title="{rd.h(bid[2:] if who else bid)}">'
            f'{rd.h(sh6(bid[2:] if who else bid))}</code><br><span class=mut>{rd.h(who)}</span></td><td class=na-l>{rd.h(BUNDLE_KIND.get(b.get("kind"), b.get("kind") or rd.DASH))}</td>'
            f'<td>{rd.h(rd.num(b.get("n_members")))}</td><td>{rd.h(rd.num(b.get("n_pumps")))}</td>'
            f'<td>{rd.h(rd.num(b.get("n_pumps15")))}</td><td>{rd.h(rd.pct(sh, sign=False, frac=True) if sh is not None else rd.DASH)}</td>'
            f'<td>{rd.h(rd.share(b.get("sold_into"), b.get("n_pumps")))}</td>'
            f'<td class=mut>{rd.h(rd.ago(b.get("last_seen"), now))}</td></tr>'
            f'<tr class=rt-d hidden><td colspan=8><div class=na-in><p><b>Tokeni:</b> {toks or rd.DASH}</p>'
            f'<p><b>Novčanici</b> ({rd.num(len(b["members"]))})</p><ul>'
            + "".join(f'<li><code translate=no>{rd.h(w)}</code> <button type=button class=nk-cp data-cp="{rd.h(w)}">'
                      f'Kopiraj</button> <a href="https://solscan.io/account/{quote(w)}" target=_blank '
                      f'rel="noopener noreferrer">Solscan ↗</a></li>' for w in b["members"][:40])
            + '</ul></div></td></tr>')
    return (f'<div class=rt-wrap><table class=rt data-rt><thead><tr>{th}</tr></thead><tbody>{"".join(rows)}</tbody>'
            f'</table></div><p class=na-note>Udio u ranim kupnjama = koliko je skupina kupila od sat prije skoka do '
            f'sat nakon, u odnosu na sve kupce (srednja vrijednost). „Isti trenutak” znamo samo za skokove koje smo '
            f'pročitali do kraja.</p>')


EXCL_LABEL = {"relayer": "posrednici (plaćaju naknade za tuđe novčanike)", "bot": "botovi",
              "snajper": "snajperi (kupuju u prvim sekundama)", "kupuje_sve": "kupuju gotovo sve",
              "market_maker": "market makeri (kupuju i prodaju cijelo vrijeme)",
              "jednokratni": "pojavili se samo jednom", "bez_placanja": "tokene dobili prijenosom, nisu kupili"}


# ---------- 4. exclusions --------------------------------------------------------------------------------------------

def excluded_html(con, pp):
    ex = P.exclusions(con, pp)
    if not any(v["n"] for v in ex.values()):
        return _empty(f"{EMPTY_NIGHT}. Ovdje se broje novčanici koje pravila izbacuju, svaki s razlogom.")
    out = []
    for c, v in ex.items():
        rows = "".join(f'<li><code translate=no>{rd.h(K.short(r["owner"]))}</code> · {rd.num(r["n_members"] or len(r["members"]))} '
                       f'novčanika · {rd.h(plain_why(r["why"]) or rd.DASH)}</li>' for r in v["rows"])
        note = ("Oni koji su se pojavili samo jednom ne spremaju se pojedinačno (samo broj)." if c == "jednokratni" and not rows else
                f"Prikazano {len(v['rows'])} od {rd.num(v['n'])}." if v["n"] > len(v["rows"]) and rows else "")
        out.append(f'<details><summary><b>{rd.h(EXCL_LABEL.get(c, P.EXCL_HR[c]))}</b> · {rd.num(v["n"])}</summary>'
                   + (f'<ul>{rows}</ul>' if rows else "") + (f'<p class=na-note>{rd.h(note)}</p>' if note else "")
                   + '</details>')
    return f'<div class=na-ex>{"".join(out)}</div>'


# ---------- 5. copy test ---------------------------------------------------------------------------------------------

COPY_VARIANT = {"60 s": "kupnja minutu nakon njih", "brzo 2 s (Pretpostavka klizanja 1 %)":
                "kupnja 2 sekunde nakon njih (pretpostavka: 1 % lošija cijena)",
                "nasumični novčanici": "nasumični rani kupci (za usporedbu)"}
BUCKET_PLAIN = {"svi": "svi", "15M+": "15 M $ i više", "5M-15M": "5–15 M $", "1M-5M": "1–5 M $", "<1M": "ispod 1 M $"}


def copy_html(pp):
    from ui import novjasno
    tone, v, _w = novjasno.copy_verdict(pp)
    rows = P.copy_table(pp)
    if not rows:
        return f'<p class="na-v {tone}">{rd.h(v)}</p>' + _empty("Brojke testa kopiranja dolaze s prvom punom obradom.")
    th = "".join(f'<th scope=col>{rd.h(h)}</th>' for h in (
        "Kako kopiramo", "Vrijednost tokena pri kupnji", "Njihovih kupnji", "Kopiranih", "Tokena", "Skupina",
        "Ne bismo stigli kopirati (promašaji)", "Prosjek po kupnji", "Raspon u kojem je pravi rezultat vjerojatno "
        "(95 % interval)", "Uz 0,5 SOL po kupnji"))
    body = []
    for lab, b, s_ in rows:
        lo, hi = s_.get("lo_pct"), s_.get("hi_pct")
        ci = f"od {rd.num(lo, 1, sign=True)} do {rd.num(hi, 1, sign=True)} %" if lo is not None and hi is not None else rd.DASH
        body.append(f'<tr><td>{rd.h(COPY_VARIANT.get(lab, lab))}</td><td>{rd.h(BUCKET_PLAIN.get(b, b))}</td>'
                    f'<td>{rd.num(s_.get("n_buys"))}</td><td>{rd.num(s_.get("n"))}</td>'
                    f'<td>{rd.num(s_.get("n_tokens"))}</td><td>{rd.num(s_.get("n_owners"))}</td>'
                    f'<td>{rd.h(rd.pct(s_.get("miss_pct"), 1, sign=False))}</td>'
                    f'<td class="{rd.tone(s_.get("ev_pct"))}">{rd.h(rd.pct(s_.get("ev_pct"), 1))}</td><td>{rd.h(ci)}</td>'
                    f'<td>{rd.h(rd.pct(s_.get("ev_big_pct"), 1))}</td></tr>')
    diff = (pp or {}).get("copy", {}).get("razlika_pct") if isinstance((pp or {}).get("copy"), dict) else None
    return (f'<p class="na-v {tone}">{rd.h(v)}</p><div class=rt-wrap><table class="rt na-ct"><thead><tr>{th}</tr></thead>'
            f'<tbody>{"".join(body)}</tbody></table></div>'
            + (f'<p class=na-note>Naše skupine u odnosu na nasumične rane kupce (kupnja minutu nakon njih, svi tokeni): '
               f'{rd.h(rd.num(diff, 1, sign=True))} postotnih bodova.</p>' if diff is not None else "")
            + '<p class=na-note>Svaki dan biramo skupine samo iz onoga što se znalo prije tog dana, trošak kupnje i '
              'prodaje je uvijek barem 3 %, a kupnje koje ne bismo stigli kopirati ostaju u brojanju. „2 sekunde nakon '
              'njih” je pretpostavka (cijena 1 % lošija od njihove), ne mjerenje.</p>')


# ---------- 6. wallet history ----------------------------------------------------------------------------------------

QUEUE_HR = (("prije_pumpe", "skupine koje kupuju prije skoka"), ("prije_pumpe_kandidat", "skupine s dva tokena"),
            ("birdeye", "najbolji trgovci iz druge provjere"), ("bundle", "skupine koje kupuju zajedno"),
            ("rani_pumpa15", "rani kupci tokena od 15 M $"), ("rani_pumpa2", "rani kupci tokena od 2–15 M $"),
            ("rani_bez_prodaje", "rani kupci koji nisu prodali"), ("holder", "veliki vlasnici"),
            ("registar", "stari popis"))
KIND_HR = {"day": "dnevna", "night": "noćna", "once": "nakon nove verzije", "incr": "dopunska"}


def povijest_html(st, now):
    """The history job's status (wallets/povijest.status): the queue per source, credits, the last pass."""
    if not st:
        return _empty("Red za povijest novčanika još ne postoji: slaže ga prva obrada.")
    qd = st.get("queue") or {}
    waiting = sum(int(v or 0) for v in qd.values())
    last = st.get("last")
    cards = [_stat("Novčanika s izračunatom poviješću", rd.num(st.get("scored_povijest")),
                   f"u plusu {rd.num(st.get('profitable'))}; ukupno ocijenjenih novčanika {rd.num(st.get('scored'))}"),
             _stat("Čeka na red", rd.num(waiting), f"preskočeno {rd.num(st.get('skipped'))} (burze, botovi, posrednici)"),
             _stat("Potrošnja izvora podataka danas (povijest)",
                   f"{rd.num(st.get('credits_today'))} od {rd.num(st.get('cap_day'))} jedinica",
                   "dnevni strop", "warn" if st.get("cap_day") and (st.get("credits_today") or 0) >= st["cap_day"] else "")]
    if last:
        cards.append(_stat("Zadnja obrada povijesti", f"{KIND_HR.get(last.get('kind'), 'obrada')} · {rd.ago(last['ts'], now)}",
                           f"pročitano {rd.num(last.get('n'))}, ocijenjeno {rd.num(last.get('scored'))}, u plusu "
                           f"{rd.num(last.get('profitable'))}; trajala {rd.num(last.get('secs'))} s; prekinuta jer je "
                           f"isteklo vrijeme: {'da' if last.get('cut') else 'ne'}"))
    else:
        cards.append(_stat("Zadnja obrada povijesti", NOT_YET, "nijedna obrada još nije zapisana"))
    per = " · ".join(f"{lab} {rd.num(qd.get(k, 0))}" for k, lab in QUEUE_HR)
    return (f'<div class=na-grid>{"".join(cards)}</div><p class=na-note><b>Čeka po izvoru:</b> {rd.h(per)}.</p>')


def history_html(con, now):
    gs = P.groups(con, False, None, 300, 0)
    member_of = {}
    for g in gs:
        for w in g["members"]:
            member_of.setdefault(w, g)
    rows, ok = P.wallet_history(list(member_of), extra_top=50)
    queue = povijest_html(P.povijest_status(now=now), now)
    if not ok:
        return queue + _empty("Baza ocijenjenih novčanika još ne postoji: prvo ocjenjivanje je noću.")
    if not rows:
        return queue + _empty("Još nema ocijenjenih novčanika ni novčanika iz grupa.")
    have = sum(1 for r in rows if r["scored"])
    head = (f'<p class=na-note>{rd.num(have)} od {rd.num(len(rows))} navedenih novčanika ima izračunatu povijest, '
            f'{rd.num(len(rows) - have)} čeka. Popis: novčanici skupina koje kupuju prije skoka i 50 najbolje '
            f'ocijenjenih.</p>')
    cols = (("w", "Novčanik", "s"), ("g", "Skupina", "s"), ("n", "Zatvorenih tradeova", "n"), ("win", "U plusu", "n"),
            ("pnl", "Zaradio", "n"), ("first", "Prvi trade", "n"), ("days", "Dana povijesti", "n"),
            ("pr", "Dokazan dvaput", "n"), ("cp", "Može se kopirati", "n"), ("rk", "Mjesto na ljestvici", "n"))
    th = "".join(f'<th data-k="{k}" data-t="{t}" scope=col>{rd.h(lab)}</th>' for k, lab, t in cols)
    body = []
    for r in rows[:400]:
        g = member_of.get(r["wallet"])
        gtxt = (f'{K.short(g["owner"])} · {"potvrđena" if g.get("confirmed_ts") else "čeka potvrdu"}' if g else rd.DASH)
        data = {"w": rd.h(r["wallet"].lower()), "g": rd.h(gtxt), "n": _n(r["closed"]), "win": _n(r["win_rate"]),
                "pnl": _n(r["realized"]), "first": _n(r["first_ts"]), "days": _n(r["days"]),
                "pr": "1" if r["proven"] else "0", "cp": "1" if r["copyable"] else "0", "rk": _n(r["rank"] or 1e9)}
        attrs = " ".join(f'data-{k}="{v}"' for k, v in data.items())
        cp = rd.DASH if r["copyable"] is None else ("da" if r["copyable"] else "ne")
        body.append(
            f'<tr class=rt-r {attrs}>{_wcell(r["wallet"])}'
            f'<td class="na-l na-hist">{rd.h(gtxt)}</td>'
            + (f'<td>{rd.num(r["closed"])}</td><td>{rd.h(rd.pct(r["win_rate"], sign=False, frac=True))}</td>'
               f'<td class="{rd.tone(r["realized"])}">{rd.h(rd.sol(r["realized"], 2, sign=True))}</td>'
               if r["scored"] else '<td colspan=3 class="na-l mut">povijest čeka</td>')
            + f'<td class=mut>{rd.h(_t(r["first_ts"], "%d.%m.%Y."))}</td><td>{rd.h(rd.num(r["days"], 0))}</td>'
              f'<td>{"<span class=ok>da</span>" if r["proven"] else "ne"}</td><td>{rd.h(cp)}</td>'
              f'<td>{rd.h(rd.num(r["rank"]) if r["rank"] else rd.DASH)}</td></tr>')
    return (queue + head + f'<div class=rt-wrap><table class=rt data-rt><thead><tr>{th}</tr></thead><tbody>{"".join(body)}'
            f'</tbody></table></div>')


# ---------- 7. big holders -------------------------------------------------------------------------------------------

def holders_html(now):
    rows, info = P.holders(60, now=now)
    if info is False:
        return _empty("Popis velikih vlasnika još ne postoji: slaže ga obrada povijesti novčanika iz podataka o "
                      "vlasnicima tokena.")
    if not rows:
        return _empty("Još nema velikih vlasnika s dugom poviješću (barem 50k $ jednog tokena, držano 30 ili više "
                      "dana, bez burzi, poolova i tima).")
    cols = (("w", "Novčanik", "s"), ("t", "Token", "s"), ("tier", "Vrijednost tokena", "s"), ("v", "Koliko drži", "n"),
            ("pct", "Udio u svim tokenima", "n"), ("f", "Drži od", "n"), ("d", "Dana", "n"), ("h", "Povijest novčanika", "n"))
    th = "".join(f'<th data-k="{k}" data-t="{t}" scope=col>{rd.h(lab)}</th>' for k, lab, t in cols)
    body = []
    for r in rows:
        data = {"w": rd.h(r["wallet"].lower()), "t": rd.h((r["symbol"] or r["mint"]).lower()),
                "tier": rd.h(r.get("tier") or ""), "pct": _n(r["pct"]), "v": _n(r["value_usd"]),
                "f": _n(r["first_ts"]), "d": _n(r["held_days"]), "h": _n(r["realized"] if r["scored"] else -1e9)}
        attrs = " ".join(f'data-{k}="{v}"' for k, v in data.items())
        hist = (f'{rd.num(r["closed"])} zatvorenih · {rd.pct(r["win_rate"], sign=False, frac=True)} u plusu · '
                f'<span class="{rd.tone(r["realized"])}">{rd.h(rd.sol(r["realized"], 2, sign=True))}</span>'
                if r["scored"] else '<span class=mut>još se računa</span>')
        tier = {"15-200M": "15–200 M $", "2-15M": "2–15 M $"}.get(r.get("tier"), r.get("tier") or rd.DASH)
        body.append(
            f'<tr class=rt-r {attrs}>{_wcell(r["wallet"])}'
            f'<td class=na-l><a href="/token/{quote(r["mint"])}" translate=no>{rd.h(r["symbol"] or K.short(r["mint"]))}</a></td>'
            f'<td>{rd.h(tier)}</td><td>{rd.h(rd.usd(r["value_usd"]))}</td>'
            f'<td>{rd.h(rd.pct(r["pct"], 2, sign=False))}</td>'
            f'<td class=mut>{rd.h(_t(r["first_ts"], "%d.%m.%Y."))}</td><td>{rd.h(rd.num(r["held_days"], 0))}</td>'
            f'<td class="na-l na-hist">{hist}</td></tr>')
    return (f'<div class=rt-wrap><table class=rt data-rt><thead><tr>{th}</tr></thead><tbody>{"".join(body)}</tbody>'
            f'</table></div><p class=na-note>{rd.num(info.get("wallets"))} novčanika s barem 50k $ jednog tokena '
            f'držanih 30 ili više dana (bez burzi, poolova i tima), tokeni od 15 do 200 M $ prvo. Povijest trgovanja '
            f'izvan ovog tokena poznata je tek kad novčanik dođe na red za povijest; naše snimke vlasnika sežu oko 45 '
            f'dana unatrag, pa je „drži od” za starije vlasnike najranije što znamo, ne stvarni početak.</p>')


# ---------- 8. Birdeye ------------------------------------------------------------------------------------------------

def birdeye_html(con, pp, now):
    """Birdeye: provjera iz drugog izvora (insajderi/birdeye.py): the month's usage, the tokens read, the cross-check,
    the new candidates (Birdeye's top traders by realized profit on 3+ jumps). Report only; an honest empty state."""
    b = P.birdeye(con, pp, now)
    if not b["key"] and not b["calls"]:
        return _empty("Ključ za Birdeye nije postavljen na serveru: ovaj dio čeka ključ.")
    if not b["table"] or not b["tokens"]:
        return _empty("Birdeye još ništa nije pročitao: prva obrada nakon postavljanja ključa čita najbolje trgovce "
                      "tokena koji su skočili (najviše 25.000 jedinica mjesečno).")
    ck = b["check"]
    cap = f" od {rd.num(b['cap'])}" if b["cap"] else ""
    cards = [_stat("Potrošnja Birdeyea ovaj mjesec", f"{rd.num(b['cu'])}{cap} jedinica", f"{rd.num(b['calls'])} upita",
                   "warn" if b["cap"] and b["cu"] >= b["cap"] else ""),
             _stat("Pročitano tokena koji su skočili", rd.num(b["tokens"]), "najboljih 30 trgovaca po zaradi"),
             _stat("Naše skupine među Birdeyeovim najboljim trgovcima",
                   rd.share(ck.get("groups_seen_in_top"), ck.get("groups_checked")) if ck.get("groups_checked")
                   else NOT_YET,
                   (f"od {rd.num(ck.get('groups_checked'))} provjerenih skupina; Birdeyeove oznake (bot, snajper, "
                    f"tim tokena) slažu se s našima {rd.num(ck.get('tag_agree'))} puta, ne slažu "
                    f"{rd.num(ck.get('tag_disagree'))}") if ck else None)]
    head = ("Novčanik", "Skokova", "Od 15 M $", "Zaradio $", "Birdeyeove oznake", "Zadnji trade")
    th = "".join(f'<th data-k="c{i}" data-t="{"s" if i in (0, 4) else "n"}" scope=col>{rd.h(h)}</th>'
                 for i, h in enumerate(head))
    rows = []
    for r in b["cand"]:
        data = {"c0": rd.h(str(r["owner"]).lower()), "c1": _n(r["n_tokens"]), "c2": _n(r["n15"]),
                "c3": _n(r["realized"]), "c4": rd.h(",".join(r["tags"])), "c5": _n(r["last_ts"])}
        attrs = " ".join(f'data-{k}="{v}"' for k, v in data.items())
        tags = ", ".join(TAG_HR.get(t, t) for t in r["tags"])
        rows.append(f'<tr class=rt-r {attrs}>{_wcell(r["owner"])}<td>{rd.h(rd.num(r["n_tokens"]))}</td>'
                    f'<td>{rd.h(rd.num(r["n15"]))}</td><td>{rd.h(rd.num(r["realized"], 0))}</td>'
                    f'<td class=na-l>{rd.h(tags or rd.DASH)}</td>'
                    f'<td class=mut>{rd.h(rd.ago(r["last_ts"], now))}</td></tr>')
    table = (f'<div class=rt-wrap><table class=rt data-rt><thead><tr>{th}</tr></thead><tbody>{"".join(rows)}</tbody>'
             f'</table></div>' if rows else _empty("Još nema novčanika među Birdeyeovim najboljima na 3 ili više skokova."))
    smart = ", ".join(f'{sh6(s_["owner"])} ({s_["smart_n"]})' for s_ in b["smart"][:20])
    return (f'<div class=na-grid>{"".join(cards)}</div><p class=na-v>Novi novčanici iz Birdeyea: među najboljima po '
            f'zaradi na 3 ili više skokova</p>'
            + table + (f'<p class=na-note><b>Birdeye ih označava kao pametne trgovce na 2 ili više skokova:</b> '
                       f'{rd.h(smart)}</p>' if smart else "")
            + '<p class=na-note>Drugi izvor, samo za provjeru: ne mijenja koga biramo. Novi novčanici odavde idu u red '
              'za povijest. Novčanici koje Birdeye označi kao bot, snajper ili tim tokena nisu na ovom popisu.</p>')


TAG_HR = {"smart_trader": "pametni trgovac", "bundler": "kupuje zajedno s drugima", "sniper": "snajper",
          "dev": "tim tokena", "bot": "bot", "insider": "insajder", "kol": "influencer", "whale": "veliki igrač"}


# ---------- the funnel -----------------------------------------------------------------------------------------------

def funnel_html(pp):
    """How deep the search looked (the summary's "lijevak"), in sentences."""
    from ui.novjasno import cnt
    f = (pp or {}).get("lijevak") if isinstance((pp or {}).get("lijevak"), dict) else None
    if not f:
        return _empty("Još nema brojki o pretraživanju: dolaze s prvom noćnom obradom.")
    p15 = int(f.get("pumpe15_1h") or 0) + int(f.get("pumpe15_1d") or 0)
    p2 = int(f.get("pumpe2_1h") or 0) + int(f.get("pumpe2_1d") or 0)
    bits = [f"Pronašli smo {cnt(p15, 'skok', 'skoka', 'skokova')} tokena od 15 M $ naviše i {cnt(p2, 'skok', 'skoka', 'skokova')} "
            "tokena od 2 do 15 M $.",
            f"Do kraja smo pročitali {rd.num(f.get('duboko'))} od njih.",
            f"U njima je {cnt(f.get('rani') or 0, 'novčanik', 'novčanika', 'novčanika')} kupilo prije skoka, a "
            f"{rd.num(f.get('rani_prodali'))} od njih i prodalo dok je token rastao.",
            f"{cnt(f.get('blizu_praga') or 0, 'novčanik ima', 'novčanika imaju', 'novčanika ima')} dva takva tokena "
            "(za popis trebaju tri).",
            f"Na popisu je {cnt(f.get('grupe') or 0, 'skupina', 'skupine', 'skupina')}, od toga "
            f"{rd.num(f.get('potvrdjeno'))} potvrđeno na novijim podacima."]
    if f.get("pokrivenost_pre_med") is not None:
        bits.append(f"Dio vremena prije skoka koji smo pregledali (pokrivenost): u sredini "
                    f"{rd.num(f['pokrivenost_pre_med'], 0)} %, a samog skoka {rd.num(f.get('pokrivenost_skok_med'), 0)} % "
                    f"(na {cnt(f.get('n_pokrivenost') or 0, 'skoku', 'skoka', 'skokova')}).")
    return '<p class=nj-intro>' + rd.h(" ".join(bits)) + '</p>'


# ---------- the page -------------------------------------------------------------------------------------------------

INTRO = {
    "stanje": "Ovdje vidiš kad je bila zadnja obrada, koliko smo tokena koji su skočili pregledali i koliko smo danas "
              "potrošili na podatke.",
    "lijevak": "Ovdje vidiš koliko smo tokena koji su skočili stvarno pregledali i koliko duboko. Što je pokrivenost "
               "manja, to više ranih kupaca nismo vidjeli.",
    "grupe": "Sve skupine u jednoj tablici, da možeš provjeriti brojke s kartica. Stupci se poredaju dodirom na naslov.",
    "bundle": "Skupine novčanika koje kupuju u istom trenutku ili zajedno nose velik dio ranih kupnji. One mogu same "
              "pomaknuti cijenu, pa ih pratimo odvojeno.",
    "kopija": "Ovdje je test: da smo ove skupine kopirali u prošlosti, koliko bismo zaradili ili izgubili po kupnji, "
              "nakon troška. Na tome se temelji odgovor „Isplati li se kopirati ih”.",
    "mjerenje": "Ovdje je svaka nova kupnja praćenih novčanika od kad ih pratimo, izmjerena u postocima, bez pravog "
                "novca. To je provjera testa na stvarnim, novim kupnjama.",
    "pnl": "Ovdje je cijela povijest trgovanja pojedinih novčanika, ne samo na skokovima. Ako novčanik i inače "
           "zarađuje, njegove kupnje prije skoka vrijede više.",
    "holderi": "Novčanici koji dugo drže velik iznos jednog tokena. Nisu dio popisa, ali ih pratimo kao moguće "
               "dobre vlasnike.",
    "birdeye": "Druga provjera iz drugog izvora podataka (Birdeye): jesu li naše skupine i tamo među najboljim "
               "trgovcima, i koje nove novčanike taj izvor predlaže.",
}


def _safe(name, fn, *a):
    try:
        return fn(*a)
    except Exception as e:  # noqa: BLE001 - one broken section never costs the page
        print(f"novcanici-admin: {name}: {type(e).__name__}: {e}", flush=True)
        return _empty(f"Ovaj dio se trenutno ne može prikazati ({type(e).__name__}).")


def _cards_part(con, qs, now):
    from ui import novjasno as J
    total = J.shown_count(con)
    if not total:
        return "Najzanimljiviji novčanici", _empty("Još nema nijednog novčanika ni skupine na popisu. Prvi stižu "
                                                        "nakon noćne obrade, od 1 do 6 sati.")
    mj = _mjera_groups(now)
    if qs.get("sve") == "1":
        try:
            page = max(1, min(1000, int(qs.get("sp") or 1)))
        except ValueError:
            page = 1
        pages = max(1, -(-total // J.ALL_N))
        page = min(page, pages)
        gs = J.ranked(con, J.ALL_N, (page - 1) * J.ALL_N)
        nav = (f'<div class=na-pg><span>Stranica {rd.num(page)} od {rd.num(pages)} · {rd.num(total)} ukupno</span>'
               + (f'<a href="{PATH}?sve=1&amp;sp={page - 1}#najbolji">← prethodna</a>' if page > 1 else "")
               + (f'<a href="{PATH}?sve=1&amp;sp={page + 1}#najbolji">sljedeća →</a>' if page < pages else "") + '</div>')
        more = (f'<div class=nj-more><a href="{PATH}#najbolji">← Samo deset najzanimljivijih</a>'
                f'<a href="{PATH}?tablica=1#grupe">Tablica za provjeru</a></div>')
        return f"Svi novčanici i skupine ({rd.num(total)})", J.cards_html(con, gs, now, mj) + nav + more
    gs = J.ranked(con, J.TOP_N, 0)
    more = ('<div class=nj-more>' + (f'<a href="{PATH}?sve=1#najbolji">Prikaži sve ({rd.num(total)})</a>'
                                     if total > len(gs) else "")
            + f'<a href="{PATH}?tablica=1#grupe">Tablica za provjeru</a></div>')
    title = "Deset najzanimljivijih novčanika" if total >= J.TOP_N else "Najzanimljiviji novčanici"
    return title, J.cards_html(con, gs, now, mj) + more


def _excluded_part(con, pp):
    from ui import novjasno as J
    ex = P.exclusions(con, pp)
    return (f'<p class=nj-ex>{rd.h(J.excluded_text(ex))}</p>'
            + (f'<details class=nj-d><summary>Pogledaj po razlogu</summary>{excluded_html(con, pp)}</details>'
               if any(v["n"] for v in ex.values()) else ""))


def page(qs=None, user=None, now=None):
    """(title, html) of the owner's wallet dashboard. Access is checked by run_ui.py before this is called."""
    from ui import novjasno as J
    from ui import rangtable
    qs = qs if isinstance(qs, dict) else {}
    now = int(now or time.time())
    con = P.ins_con()
    nodb = _empty(f"{EMPTY_NIGHT} (baza još ne postoji).")
    try:
        _s, pp = P.summary(con) if con is not None else ({}, {})
        try:
            be = P.birdeye(con, pp, now) if con is not None else None
        except Exception:  # noqa: BLE001
            be = None
        try:
            head = J.headline_html(J.headline(con, pp, now, be))
        except Exception as e:  # noqa: BLE001 - the page never fails on its first screen
            print(f"novcanici-admin: naslov: {type(e).__name__}: {e}", flush=True)
            head = _empty("Odgovor se trenutno ne može složiti; detalji su niže.")
        r = _safe("kartice", _cards_part, con, qs, now) if con is not None else nodb
        ctitle, cards = r if isinstance(r, tuple) else ("Deset najzanimljivijih novčanika", r)
        excl = _safe("iskljuceni", _excluded_part, con, pp) if con is not None else _empty(J.excluded_text({}))
        parts = [
            ("stanje", "Stanje pretraživanja", _safe("stanje", status_html, con, pp, now)),
            ("lijevak", "Koliko smo duboko gledali", _safe("lijevak", funnel_html, pp)),
            ("grupe", "Sve skupine u tablici", _safe("grupe", groups_html, con, qs, now) if con is not None else nodb),
            ("bundle", "Skupine koje kupuju zajedno", _safe("bundle", bundles_html, con, now) if con is not None
             else _empty(EMPTY_NIGHT + ".")),
            ("kopija", "Test kopiranja na prošlim podacima", _safe("kopija", copy_html, pp)),
            ("mjerenje", "Mjerenje uživo, kupnja po kupnja", _safe("mjerenje", _mjera_html, now)),
            ("pnl", "Povijest trgovanja novčanika", _safe("pnl", history_html, con, now)),
            ("holderi", "Veliki dugoročni vlasnici tokena", _safe("holderi", holders_html, now)),
            ("birdeye", "Druga provjera (Birdeye)", _safe("birdeye", birdeye_html, con, pp, now)
             if con is not None else _empty("Birdeye još ništa nije pročitao (baza još ne postoji).")),
        ]
    finally:
        if con is not None:
            con.close()
    det = "".join(str(rd.section(t, sid=sid)).replace('class="ms-h2"', 'class="ms-h2 nosec"')
                  + f'<p class=nj-intro>{rd.h(INTRO[sid])}</p>' + h for sid, t, h in parts)
    open_ = any(qs.get(k) for k in ("tablica", "f", "t", "p"))
    sub = f"Samo ti vidiš ovu stranicu. Stanje {_t(now, '%d.%m. %H:%M')}."
    body = (head + str(rd.section(ctitle, sid="najbolji")) + cards
            + str(rd.section("Koga smo izbacili i zašto", sid="iskljuceni")) + excl
            + f'<details class=nj-det{" open" if open_ else ""}><summary>Detalji za provjeru</summary>{det}</details>')
    return TITLE, (f'{CSS}{J.CSS}{rangtable.CSS}<div class="ms-page ms-wide na">{rd.top(TITLE)}'
                   f'<p class=ms-sub>{rd.h(sub)} <a href="/wallets">← Novčanici</a></p>{body}</div>'
                   + rangtable.JS + K.COPY_JS)
