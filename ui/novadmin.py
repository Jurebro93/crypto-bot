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
EMPTY_NIGHT = "još nema podataka: prvi noćni prolaz (01–06 CET) ih puni"

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


# ---------- 1. status ------------------------------------------------------------------------------------------------

def status_html(con, pp, now):
    cards = []
    if pp:
        f15 = pp.get("fetched15")
        cards.append(_stat("Pumpe ≥ 15 M $", f"{rd.num(pp.get('covered15'))} pokriveno od {rd.num(pp.get('pumps15'))}",
                           (f"dohvaćeno {rd.num(f15)}, čeka {rd.num(max(0, (pp.get('pumps15') or 0) - (f15 or 0)))}"
                            if f15 is not None else f"dohvaćeno: {NOT_YET}")))
        cards.append(_stat("Pumpe 2–15 M $", f"{rd.num(pp.get('covered2'))} pokriveno od {rd.num(pp.get('pumps2'))}",
                           (f"dohvaćeno {rd.num(pp.get('fetched2'))}" if pp.get("fetched2") is not None
                            else f"dohvaćeno: {NOT_YET}")))
    else:
        cards.append(_stat("Pumpe ≥ 15 M $ / 2–15 M $", NOT_YET, "nakon prvog prolaza"))
    spent, cap, how = P.helius(con, now)
    cards.append(_stat("Helius danas", (f"{rd.num(spent) if spent is not None else 0} / {rd.num(cap)} kr."
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
        kind = {"night": "noćni", "once": "nakon deploya", "incr": "dopunski", "report": "samo izvještaj"}.get(
            run.get("kind"), "prolaz")
        cards.append(_stat("Zadnji prolaz", f"{kind} · {rd.ago(run['ts'], now)}",
                           f"{_t(run['ts'])}; trajanje {rd.num(dur) + ' s' if dur is not None else NOT_YET}; prekinut vremenskim "
                           f"limitom: {('da' if cut else 'ne') if cut is not None else NOT_YET}; Helius "
                           f"{rd.num(run.get('credits'))} kr."))
    else:
        cards.append(_stat("Zadnji prolaz", NOT_YET, "nijedan prolaz još nije zapisan"))
    st = P.social()
    if st:
        word = {"open": "otvoren", "closed": "zatvoren", "first": "čeka prvi start", "always": "uvijek otvoren",
                "nopersist": "otvoren (bez trajnog stanja)"}.get(st.get("mode"), st.get("mode") or "?")
        from ops import drustveni
        cards.append(_stat("Influenceri i Telegram", word,
                           f"sljedeći prozor {drustveni.when(st['next'])}" if st.get("next") else None))
    paused = P.pause_on()
    cards.append(_stat("Pravi novac", "pauziran" if paused else "nije pauziran",
                       "demo prati novčanike" if paused else None, "warn" if paused else "good"))
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
        return '<p class=na-note>Pojedinačne pumpe još nisu spremljene za ovu grupu.</p>'
    out = []
    for p in pumps[:40]:
        tok = p.get("token") or ""
        sym = rd.h(p.get("symbol") or K.short(tok))
        lead = p.get("lead_s")
        if lead is None and p.get("buy_ts") and p.get("t0"):
            lead = p["t0"] - p["buy_ts"]
        rel = (f"{rd.num(lead / 60)} min prije skoka" if lead is not None and lead >= 0 else
               f"{rd.num(-lead / 60)} min nakon" if lead is not None else rd.DASH)
        tier = {"pumpa15": "≥ 15 M $", "pumpa2": "2–15 M $"}.get(p.get("tier"), rd.DASH)
        out.append(f'<tr><td><a href="/token/{quote(tok)}" translate=no>{sym}</a></td><td>{rd.h(tier)}</td>'
                   f'<td>{rd.h(_t(p.get("t0"), "%d.%m. %H:%M"))}</td><td>{rd.h(rel)}</td>'
                   f'<td>{rd.h(rd.sol(p.get("sol_in"), 2))}</td><td>{rd.h(rd.sol(p.get("sol_out"), 2))}</td>'
                   f'<td>{"da" if p.get("sold_into") else "ne"}</td>'
                   f'<td class=na-l><code translate=no>{rd.h(K.short(p.get("wallet")))}</code></td></tr>')
    more = f'<p class=na-note>Prikazano 40 od {len(pumps)} pumpi.</p>' if len(pumps) > 40 else ""
    return ('<div class=scr><table><thead><tr><th>Token</th><th>Vrh</th><th>Skok</th><th>Kupnja</th><th>Uloženo</th>'
            '<th>Izašlo</th><th>Prodao u skok</th><th>Novčanik</th></tr></thead><tbody>' + "".join(out)
            + '</tbody></table></div>' + more)


def _links_html(links, members):
    if len(members) < 2:
        return '<p class=na-note>Grupa ima jedan novčanik.</p>'
    if not links:
        return ('<p class=na-note>Povezani su zajedničkim financijerom ili grupom iz korelacija; koja je veza točno, nije '
                'spremljeno po novčaniku.</p>')
    bits = []
    for kind, who, n in links:
        if kind == "platitelj":
            bits.append(f'<li>isti platitelj naknada za {rd.num(n)} novčanika: <code translate=no>{rd.h(who)}</code></li>')
        else:
            bits.append(f'<li>kupovali su u istom bloku {rd.num(n)} put{"a" if 2 <= n % 10 <= 4 else "" if n == 1 else "a"}</li>')
    return '<ul>' + "".join(bits) + '</ul>'


AGREE = {1: "slaže se", 0: "ne slaže se", None: "još nema povijesti"}


def hist_sentence(h, n_members=None):
    """"povijest članova: ocijenjeno X od Y, u plusu Z %, ostvareno N SOL; slaže se s rezultatom na pumpama" (i2_pp_hist,
    the members' own scored history; a report, not a selection rule)."""
    if not h or not h.get("n_scored"):
        return f"ocijenjeno 0 od {rd.num((h or {}).get('n_members') or n_members)}; još nema povijesti."
    agree = {1: "slaže se s rezultatom na pumpama", 0: "ne slaže se s rezultatom na pumpama"}.get(h.get("agrees"),
                                                                                              "još nema povijesti")
    return (f"ocijenjeno {rd.num(h['n_scored'])} od {rd.num(h.get('n_members'))}, u plusu "
            f"{rd.pct(h.get('profitable_share'), sign=False, frac=True)}, ostvareno "
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
        return "još nijedan signal (bilježi se svaka kupnja grupe)."
    mean = rd.pct(d["mean01"], 1, sign=True, frac=True) if d["mean01"] is not None else rd.DASH
    return (f"{rd.num(d['n'])} signala, izmjereno {rd.num(d['measured'])}, srednje neto uz 0,1 SOL {mean} "
            "(30 dana).")


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
                     f'{rd.h(lab)}</a>' for fv, lab in ((None, f"Sve grupe · {rd.num(all_n)}"),
                                                         ("potvrdeni", f"Samo potvrđene · {rd.num(conf_n)}")))
           + "".join(f'<a href="{rd.h(_link(qs, t=tv, p=None))}"{" class=on" if (qs.get("t") or "") == (tv or "") else ""}>'
                     f'{rd.h(lab)}</a>' for tv, lab in ((None, "Svi vrhovi"), ("15", "Ima ≥ 15 M $"), ("2", "Ima 2–15 M $")))
           + '</div>')
    if not all_n:
        return flt.replace("class=na-f", "class=na-f hidden") + _empty(
            f"{EMPTY_NIGHT}. Grupa ulazi ovdje kad kupi prije pumpe i proda u pumpu na barem 3 tokena.")
    gs = P.groups(con, conf_only, tier, PAGE_N, (page - 1) * PAGE_N)
    pumps = P.pumps_of(con, [g["owner"] for g in gs])
    hist = P.hist_of(con, [g["owner"] for g in gs])
    mj = _mjera_groups(now)
    head = [("w", "Novčanici", "s"), ("p15", "Pumpe ≥ 15 M $", "n"), ("p2", "2–15 M $", "n"), ("tok", "Tokena", "n"),
            ("lead", "Vodstvo (medijan)", "n"), ("pnl", "Ostvareno", "n"), ("hist", "Povijest članova", "n"),
            ("st", "Status", "n"), ("last", "Zadnji put", "n")]
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
            f'<td>{"<span class=ok>potvrđeno</span>" if conf else "<span class=warn>kandidat</span>" if g.get("cls") == "kandidat" else "<span class=mut>čeka potvrdu</span>"}</td>'
            f'<td class=mut>{rd.h(rd.ago(g.get("last_seen"), now))}</td></tr>'
            f'<tr class=rt-d hidden><td colspan={len(head)}><div class=na-in>'
            f'<p><b>Zašto:</b> {rd.h(g.get("why") or K.reason(g))}</p>'
            f'<p><b>Povijest članova:</b> {rd.h(hist_sentence(h, len(g["members"])))}</p>'
            f'<p><b>Mjerenje po ulazu:</b> {rd.h(_mjera_sentence(mj, g["owner"]))}</p>'
            f'<p><b>Pumpe</b> ({rd.num(len(ps))})</p>{_pump_rows(ps, now)}'
            f'<p><b>Novčanici grupe</b> ({rd.num(len(g["members"]))})</p><ul>'
            + "".join(f'<li><code translate=no>{rd.h(w)}</code> <button type=button class=nk-cp data-cp="{rd.h(w)}">Kopiraj'
                      f'</button> <a href="https://solscan.io/account/{quote(w)}" target=_blank rel="noopener noreferrer">'
                      f'Solscan ↗</a></li>' for w in g["members"][:60])
            + '</ul>' + (f'<p class=na-note>+{len(g["members"]) - 60} novčanika</p>' if len(g["members"]) > 60 else "")
            + f'<p><b>Što ih povezuje</b></p>{_links_html(P.links(con, g["members"][:60]), g["members"])}'
            '</div></td></tr>')
    pages = max(1, -(-total // PAGE_N))
    pg = (f'<div class=na-pg><span>Stranica {rd.num(page)} od {rd.num(pages)} · {rd.num(total)} grupa</span>'
          + (f'<a href="{rd.h(_link(qs, p=str(page - 1)))}">← prethodna</a>' if page > 1 else "")
          + (f'<a href="{rd.h(_link(qs, p=str(page + 1)))}">sljedeća →</a>' if page < pages else "") + '</div>')
    tbl = (f'<div class=rt-wrap><table class=rt data-rt><thead><tr>{th}</tr></thead><tbody>{"".join(body)}</tbody>'
           f'</table></div>') if body else _empty("Nijedna grupa ne prolazi ovaj filter.")
    return flt + tbl + pg + ('<p class=na-note>Dodir na redak otvara pumpe, novčanike grupe i što ih povezuje. Stupci se '
                             'poredaju klikom na naslov (unutar stranice). Statistika, ne optužba.</p>')


# ---------- 3. bundles -----------------------------------------------------------------------------------------------

def bundles_html(con, now):
    bs = P.bundles(con, 50)
    if not bs:
        return _empty(f"{EMPTY_NIGHT}. Bundle: 3+ novčanika jednog vlasnika ili platitelja kupuje u istom bloku, ili "
                      "grupa nosi 30 %+ ranih kupnji, na barem 2 pumpe.")
    syms = P.demo_tokens(con, [t for b in bs for t in b["tokens"]])
    head = ("Bundle", "Vrsta", "Novčanika", "Pumpi", "≥ 15 M $", "Udio ranih kupnji", "Prodali u pumpu", "Zadnji put")
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
            f'{rd.h(sh6(bid[2:] if who else bid))}</code><br><span class=mut>{rd.h(who)}</span></td><td class=na-l>{rd.h(b.get("kind") or rd.DASH)}</td>'
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
            f'</table></div><p class=na-note>Udio ranih kupnji = medijan udjela grupe u SOL-u kupljenom od sat prije '
            f'skoka do sat nakon. Isti blok samo za pumpe koje je Helius pročitao.</p>')


# ---------- 4. exclusions --------------------------------------------------------------------------------------------

def excluded_html(con, pp):
    ex = P.exclusions(con, pp)
    if not any(v["n"] for v in ex.values()):
        return _empty(f"{EMPTY_NIGHT}. Ovdje se broje novčanici koje pravila isključuju (bot, snajper, relayer, kupuje "
                      "sve, market maker, jednokratni, bez plaćanja) s razlogom.")
    out = []
    for c, v in ex.items():
        rows = "".join(f'<li><code translate=no>{rd.h(K.short(r["owner"]))}</code> · {rd.num(r["n_members"] or len(r["members"]))} '
                       f'nov. · {rd.h(r["why"] or rd.DASH)}</li>' for r in v["rows"])
        note = ("Jednokratni se ne spremaju pojedinačno (samo broj)." if c == "jednokratni" and not rows else
                f"Prikazano {len(v['rows'])} od {rd.num(v['n'])}." if v["n"] > len(v["rows"]) and rows else "")
        out.append(f'<details><summary><b>{rd.h(P.EXCL_HR[c])}</b> · {rd.num(v["n"])}</summary>'
                   + (f'<ul>{rows}</ul>' if rows else "") + (f'<p class=na-note>{rd.h(note)}</p>' if note else "")
                   + '</details>')
    return f'<div class=na-ex>{"".join(out)}</div>'


# ---------- 5. copy test ---------------------------------------------------------------------------------------------

def copy_html(pp):
    v = P.verdict(pp)
    tone = "good" if v.startswith("Kopiranje 60 s je u plusu") else "bad" if "u minusu" in v else "warn"
    rows = P.copy_table(pp)
    if not rows:
        return f'<p class="na-v {tone}">{rd.h(v)}</p>' + _empty("Brojke testa kopiranja dolaze s prvim punim prolazom.")
    th = "".join(f'<th scope=col>{rd.h(h)}</th>' for h in ("Varijanta", "MC pri ulazu", "Kupnji", "Kopija", "Tokena",
                                                            "Grupa", "Promašeno", "Prosjek", "95 % interval", "Uz 0,5 SOL"))
    body = []
    for lab, b, s in rows:
        lo, hi = s.get("lo_pct"), s.get("hi_pct")
        ci = f"[{rd.num(lo, 1, sign=True)}; {rd.num(hi, 1, sign=True)}] %" if lo is not None and hi is not None else rd.DASH
        body.append(f'<tr><td>{rd.h(lab)}</td><td>{rd.h(b)}</td><td>{rd.num(s.get("n_buys"))}</td><td>{rd.num(s.get("n"))}</td>'
                    f'<td>{rd.num(s.get("n_tokens"))}</td><td>{rd.num(s.get("n_owners"))}</td>'
                    f'<td>{rd.h(rd.pct(s.get("miss_pct"), 1, sign=False))}</td>'
                    f'<td class="{rd.tone(s.get("ev_pct"))}">{rd.h(rd.pct(s.get("ev_pct"), 1))}</td><td>{rd.h(ci)}</td>'
                    f'<td>{rd.h(rd.pct(s.get("ev_big_pct"), 1))}</td></tr>')
    diff = (pp or {}).get("copy", {}).get("razlika_pct") if isinstance((pp or {}).get("copy"), dict) else None
    return (f'<p class="na-v {tone}">{rd.h(v)}</p><div class=rt-wrap><table class="rt na-ct"><thead><tr>{th}</tr></thead>'
            f'<tbody>{"".join(body)}</tbody></table></div>'
            + (f'<p class=na-note>Odabrani minus nasumični (60 s, svi): {rd.h(rd.num(diff, 1, sign=True))} postotnih bodova.'
               '</p>' if diff is not None else "")
            + '<p class=na-note>Odabir samo iz prošlosti (walk-forward po danu), trošak nikad ispod 3 %, promašene '
              'kupnje brojane. „Brzo 2 s”: ulaz po tradeu tokena unutar 5 s, inače njihova cijena + 1 % (pretpostavka, '
              'ne mjerenje).</p>')


# ---------- 6. wallet history ----------------------------------------------------------------------------------------

QUEUE_HR = (("prije_pumpe", "grupe prije pumpe"), ("prije_pumpe_kandidat", "kandidati"), ("birdeye", "Birdeye vrh"),
            ("bundle", "bundle"),
            ("rani_pumpa15", "rani kupci pumpi ≥ 15 M $"), ("rani_pumpa2", "rani kupci 2–15 M $"),
            ("rani_bez_prodaje", "rani kupci bez prodaje"), ("holder", "holderi"), ("registar", "stari registar"))
KIND_HR = {"day": "dnevni", "night": "noćni", "once": "nakon deploya", "incr": "dopunski"}


def povijest_html(st, now):
    """The history job's status (wallets/povijest.status): the queue per source, credits, the last pass."""
    if not st:
        return _empty("Red za povijest novčanika još ne postoji: prvi prolaz ga slaže.")
    qd = st.get("queue") or {}
    waiting = sum(int(v or 0) for v in qd.values())
    last = st.get("last")
    cards = [_stat("Ocijenjeno poviješću", rd.num(st.get("scored_povijest")),
                   f"u plusu {rd.num(st.get('profitable'))}; ukupno ocijenjenih novčanika {rd.num(st.get('scored'))}"),
             _stat("Čeka u redu", rd.num(waiting), f"preskočeno {rd.num(st.get('skipped'))} (burze, botovi, relayeri)"),
             _stat("Helius danas (povijest)", f"{rd.num(st.get('credits_today'))} / {rd.num(st.get('cap_day'))} kr.",
                   "dnevni strop", "warn" if st.get("cap_day") and (st.get("credits_today") or 0) >= st["cap_day"] else "")]
    if last:
        cards.append(_stat("Zadnji prolaz povijesti", f"{KIND_HR.get(last.get('kind'), 'prolaz')} · {rd.ago(last['ts'], now)}",
                           f"obrađeno {rd.num(last.get('n'))}, ocijenjeno {rd.num(last.get('scored'))}, u plusu "
                           f"{rd.num(last.get('profitable'))}; trajanje {rd.num(last.get('secs'))} s; prekinut "
                           f"vremenskim limitom: {'da' if last.get('cut') else 'ne'}"))
    else:
        cards.append(_stat("Zadnji prolaz povijesti", NOT_YET, "nijedan prolaz još nije zapisan"))
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
            f'{rd.num(len(rows) - have)} čeka. Popis: novčanici grupa „kupuje prije pumpe” i 50 najbolje ocijenjenih.</p>')
    cols = (("w", "Novčanik", "s"), ("g", "Grupa", "s"), ("n", "Zatvorenih", "n"), ("win", "U plusu", "n"),
            ("pnl", "Ostvareno", "n"), ("first", "Prvi trade", "n"), ("days", "Dana povijesti", "n"),
            ("pr", "Dokazan dvaput", "n"), ("cp", "Kopirljiv", "n"), ("rk", "Rang", "n"))
    th = "".join(f'<th data-k="{k}" data-t="{t}" scope=col>{rd.h(lab)}</th>' for k, lab, t in cols)
    body = []
    for r in rows[:400]:
        g = member_of.get(r["wallet"])
        gtxt = (f'{K.short(g["owner"])} · {"potvrđeno" if g.get("confirmed_ts") else "kandidat"}' if g else rd.DASH)
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
        return _empty("Popis velikih holdera još ne postoji: slaže ga prolaz povijesti novčanika iz podataka o "
                      "holderima midcapova.")
    if not rows:
        return _empty("Još nema velikih holdera s dugom poviješću (barem 50k $ midcapa, držano 30+ dana, bez burzi, "
                      "poolova i tima).")
    cols = (("w", "Novčanik", "s"), ("t", "Token", "s"), ("tier", "MC", "s"), ("v", "Vrijednost", "n"),
            ("pct", "Udio u ponudi", "n"), ("f", "Drži od", "n"), ("d", "Dana", "n"), ("h", "Povijest novčanika", "n"))
    th = "".join(f'<th data-k="{k}" data-t="{t}" scope=col>{rd.h(lab)}</th>' for k, lab, t in cols)
    body = []
    for r in rows:
        data = {"w": rd.h(r["wallet"].lower()), "t": rd.h((r["symbol"] or r["mint"]).lower()),
                "tier": rd.h(r.get("tier") or ""), "pct": _n(r["pct"]), "v": _n(r["value_usd"]),
                "f": _n(r["first_ts"]), "d": _n(r["held_days"]), "h": _n(r["realized"] if r["scored"] else -1e9)}
        attrs = " ".join(f'data-{k}="{v}"' for k, v in data.items())
        hist = (f'{rd.num(r["closed"])} zatv. · {rd.pct(r["win_rate"], sign=False, frac=True)} u plusu · '
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
            f'</table></div><p class=na-note>{rd.num(info.get("wallets"))} novčanika s barem 50k $ midcapa držanih 30+ '
            f'dana (bez burzi, poolova i tima), 15–200 M $ prvo. Povijest trgovanja izvan ovog tokena poznata je tek kad '
            f'novčanik dođe na red za povijest; početak držanja iz snimki holdera seže oko 45 dana unatrag, pa je '
            f'„drži od” za starije držače najranije što znamo, ne stvarni početak.</p>')


# ---------- 8. Birdeye ------------------------------------------------------------------------------------------------

def birdeye_html(con, pp, now):
    """Birdeye: provjera iz drugog izvora (insajderi/birdeye.py): the month's usage, the tokens read, the cross-check,
    the new candidates (Birdeye's top traders by realized PnL on 3+ pumps). Report only; an honest empty state."""
    b = P.birdeye(con, pp, now)
    if not b["key"] and not b["calls"]:
        return _empty("Birdeye ključ nije postavljen (varijabla BIRDEYE_API_KEY na serveru): ovaj dio čeka ključ.")
    if not b["table"] or not b["tokens"]:
        return _empty("Birdeye još ništa nije pročitao: prvi prolaz nakon postavljanja ključa čita najbolje trgovce "
                      "tokena s pumpom (najviše 25.000 CU mjesečno).")
    ck = b["check"]
    cap = f" / {rd.num(b['cap'])}" if b["cap"] else ""
    cards = [_stat("Birdeye ovaj mjesec", f"{rd.num(b['cu'])}{cap} CU", f"{rd.num(b['calls'])} poziva",
                   "warn" if b["cap"] and b["cu"] >= b["cap"] else ""),
             _stat("Pročitano tokena s pumpom", rd.num(b["tokens"]), "najboljih 30 po ostvarenoj zaradi"),
             _stat("Grupe viđene u Birdeyeovu vrhu",
                   rd.share(ck.get("groups_seen_in_top"), ck.get("groups_checked")) if ck.get("groups_checked")
                   else NOT_YET,
                   (f"od {rd.num(ck.get('groups_checked'))} provjerenih grupa; oznake bundler / sniper / dev: slaže se "
                    f"{rd.num(ck.get('tag_agree'))}, ne slaže {rd.num(ck.get('tag_disagree'))}") if ck else None)]
    head = ("Novčanik", "Pumpi", "≥ 15 M $", "Ostvareno $", "Oznake", "Zadnji trade")
    th = "".join(f'<th data-k="c{i}" data-t="{"s" if i in (0, 4) else "n"}" scope=col>{rd.h(h)}</th>'
                 for i, h in enumerate(head))
    rows = []
    for r in b["cand"]:
        data = {"c0": rd.h(str(r["owner"]).lower()), "c1": _n(r["n_tokens"]), "c2": _n(r["n15"]),
                "c3": _n(r["realized"]), "c4": rd.h(",".join(r["tags"])), "c5": _n(r["last_ts"])}
        attrs = " ".join(f'data-{k}="{v}"' for k, v in data.items())
        rows.append(f'<tr class=rt-r {attrs}>{_wcell(r["owner"])}<td>{rd.h(rd.num(r["n_tokens"]))}</td>'
                    f'<td>{rd.h(rd.num(r["n15"]))}</td><td>{rd.h(rd.num(r["realized"], 0))}</td>'
                    f'<td class=na-l>{rd.h(", ".join(r["tags"]) or rd.DASH)}</td>'
                    f'<td class=mut>{rd.h(rd.ago(r["last_ts"], now))}</td></tr>')
    table = (f'<div class=rt-wrap><table class=rt data-rt><thead><tr>{th}</tr></thead><tbody>{"".join(rows)}</tbody>'
             f'</table></div>' if rows else _empty("Još nema novčanika u Birdeyeovu vrhu na 3+ pumpe."))
    smart = ", ".join(f'{sh6(s["owner"])} ({s["smart_n"]})' for s in b["smart"][:20])
    return (f'<div class=na-grid>{"".join(cards)}</div><p class=na-v>Birdeye: u vrhu po ostvarenoj zaradi na 3+ pumpe</p>'
            + table + (f'<p class=na-note><b>Oznaka smart_trader na 2+ pumpe:</b> {rd.h(smart)}</p>' if smart else "")
            + '<p class=na-note>Drugi izvor, samo izvještaj: ne mijenja pravila odabira. Kandidati idu u red povijesti '
              'novčanika. Bez oznaka bundler / sniper / dev na tim pumpama.</p>')


# ---------- the page -------------------------------------------------------------------------------------------------

def _safe(name, fn, *a):
    try:
        return fn(*a)
    except Exception as e:  # noqa: BLE001 - one broken section never costs the page
        print(f"novcanici-admin: {name}: {type(e).__name__}: {e}", flush=True)
        return _empty(f"Ovaj dio se trenutno ne može prikazati ({type(e).__name__}).")


def page(qs=None, user=None, now=None):
    """(title, html) of the owner's wallet dashboard. Access is checked by run_ui.py before this is called."""
    from ui import rangtable
    qs = qs if isinstance(qs, dict) else {}
    now = int(now or time.time())
    con = P.ins_con()
    try:
        _s, pp = P.summary(con) if con is not None else ({}, {})
        parts = [
            ("stanje", "Stanje", _safe("stanje", status_html, con, pp, now)),
            ("grupe", "Kupuje prije pumpe", _safe("grupe", groups_html, con, qs, now) if con is not None
             else _empty(f"{EMPTY_NIGHT} (baza još ne postoji).")),
            ("bundle", "Bundle novčanici (pomiču cijenu)", _safe("bundle", bundles_html, con, now) if con is not None
             else _empty(EMPTY_NIGHT + ".")),
            ("iskljuceni", "Isključeni i zašto", _safe("iskljuceni", excluded_html, con, pp) if con is not None
             else _empty(EMPTY_NIGHT + ".")),
            ("kopija", "Test kopiranja", _safe("kopija", copy_html, pp)),
            ("mjerenje", "Mjerenje po ulazu", _safe("mjerenje", _mjera_html, now)),
            ("pnl", "Povijesni PnL novčanika", _safe("pnl", history_html, con, now)),
            ("holderi", "Veliki holderi s dugom poviješću", _safe("holderi", holders_html, now)),
            ("birdeye", "Birdeye: provjera iz drugog izvora", _safe("birdeye", birdeye_html, con, pp, now)
             if con is not None else _empty("Birdeye još ništa nije pročitao (baza još ne postoji).")),
        ]
    finally:
        if con is not None:
            con.close()
    body = "".join(str(rd.section(t, sid=sid)) + h for sid, t, h in parts)
    sub = ("Samo vlasnik. Statistika iz javnih podataka s lanca, ne optužba: „kupuje prije pumpe” znači samo da je grupa "
           f"više puta kupila prije skoka i prodala u skok. Stanje {_t(now)}.")
    return TITLE, (f'{CSS}{rangtable.CSS}<div class="ms-page ms-wide na">{rd.top(TITLE)}'
                   f'<p class=ms-sub>{rd.h(sub)} <a href="/wallets">← Novčanici</a></p>{body}</div>'
                   + rangtable.JS + K.COPY_JS)
