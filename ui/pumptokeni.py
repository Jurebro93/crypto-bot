"""/pump-tokeni: „Pump Fun tokeni” (25.11., vlasnik). Vidi ga SAMO vlasnik (run_ui.py provjerava is_owner prije
svega; ostalima 403 „nije za tvoj račun”; stavka izbornika own-only se ostalima reže na poslužitelju). Nije javno,
noindex, nije u sitemapu.

26.11. raspored (mobitel prvi): nadzorna ploča na vrhu čim postoji lansiran token (inače traka koraka Novčanik →
Provjera → Nacrti → Pilot s jednim pozivom na akciju), skupljeni novčanik, provjera u jednom retku, nacrti kao kartice
(tablica na širem zaslonu), „Odobri pilot” onemogućen s razlogom, „Podigni naknadu”, pokušaji i knjiga ishoda
skupljeni. Ploča se čita iz baze (snimci posla pumptokeni.posao) i sama se osvježava (/pump-tokeni/ploca). Sve
slanje radi posao pumptokeni.posao, jedno po jedno; podizanje naknade samo vlasnikov potvrđeni dodir.

26.11. večer: po nacrtu vlastita kupnja (0–0,1 SOL), poveznice (X, Telegram, web; zadane u „Više”), termin (CET) u
proširenju „Uredi”; kartica kratko: termin, kupnja, poveznice da/ne. „Odobri pilot” odobrava raspored. Uz lansiran
token blok „Objava za kopiranje” (samo kopiranje; ništa se nigdje ne objavljuje automatski).
"""
import base64
import datetime as dt
import json
import os
import time

from pumptokeni import devwallet, guards, image, launch, outcomes, provjera, store
from ui.html import badge, esc, table

PATH = "/pump-tokeni"
STATE_WORDS = {"nacrt": ("nacrt", ""), "u_redu": ("u redu za slanje", "warn"), "salje": ("šalje se", "warn"),
               "lansiran": ("lansiran", "good"), "greska": ("greška", "bad"), "odbijen": ("odbijen", "bad"),
               "propusten": ("termin propušten", "warn")}
ATTEMPT_WORDS = {"priprema": "priprema", "poslano": "poslano, čeka potvrdu", "lansiran": "lansiran",
                 "neuspio": "nije uspio", "nepoznato": "nepoznato (potpis se provjerava)", "odbijeno": "odbijeno prije slanja"}
_BAL = {}


def _con():
    con = store.connect()
    store.seed(con)
    return con


def _sol(x, d=4):
    return "–" if x is None else f"{x:.{d}f}"


def _short(a):
    return f"{a[:4]}…{a[-4:]}" if a and len(a) > 10 else (a or "")


def balance(addr, max_age=300):
    """SOL saldo (RPC, predmemorija 5 min; 27.11. rjeđe radi kredita) ili None."""
    if not addr:
        return None
    hit = _BAL.get(addr)
    if hit and time.time() - hit[0] < max_age:
        return hit[1]
    try:
        from trade import wallet
        v = wallet.sol_balance(addr)
    except Exception:  # noqa: BLE001
        v = None
    _BAL[addr] = (time.time(), v)
    return v


def suggest(con, today=None, days=60, path=None):
    """Opći praznici iz event_calendar/events_manual.json (kind 'holiday') u sljedećih `days` dana koji još nemaju
    nacrt. [(tema, datum)]. Ništa o osobama ni brendovima (samo kind holiday)."""
    today = today or dt.date.today()
    path = path or os.path.join(store.ROOT, "event_calendar", "events_manual.json")
    try:
        with open(path, encoding="utf-8") as f:
            evs = json.load(f)
    except (OSError, ValueError):
        return []
    have = {(d.get("tema") or "").lower() for d in store.drafts(con)}
    out = []
    for e in evs:
        if e.get("kind") != "holiday":
            continue
        ds = e.get("date") or ""
        try:
            if len(ds) == 5:   # recurring MM-DD
                d = dt.date(today.year, int(ds[:2]), int(ds[3:]))
                if d < today:
                    d = d.replace(year=today.year + 1)
            else:
                d = dt.date.fromisoformat(ds)
        except ValueError:
            continue
        if today <= d <= today + dt.timedelta(days=days) and (e.get("title") or "").lower() not in have:
            out.append((e["title"], d.isoformat()))
    return sorted(out, key=lambda x: x[1])


# ---------- page -------------------------------------------------------------------------------------------------
# 26.11. (vlasnik: „po karticama, novčanik minimiziran, čist dizajn, tablica s tokenima, bolji pregled na mobitelu,
# proces od početka do kraja s manje smetnji; kad se tokeni lansiraju, na vrhu nadzorna ploča”). Mobitel prvi
# (360 px bez vodoravnog pomicanja); široke tablice samo unutar svog okvira.

WLABEL = {launch.TOOL: "Novčanik pokusa (u alatu)", launch.SEPARATE: "Zasebni novčanik (ključ na Renderu)",
          launch.TRADING: "Trgovački novčanik", launch.OFF: "Isključeno"}
CAN_LAUNCH = ("nacrt", "odbijen", "greska", "propusten")
BUY_NOTE = "kupljeni tokeni ostaju u novčaniku; alat ih ne prodaje"
LINK_NOTES = ("Poveznice moraju voditi na tvoje stranice ili profile.",
              "Ista poveznica na više tokena može pasti na filtre duplikata.")
BRAND_LABEL = "želim javno povezati MemeSonar s ovim tokenom"

CSS = """<style>
.pt{max-width:1100px;min-width:0}.pt *{min-width:0}
.pt h1{margin:4px 0 2px}.pt .pt-sub{color:var(--mut);font-size:13.5px;margin:0 0 12px}
.pt h2{margin:26px 0 8px;font-size:18px}
.pt details.card{padding:0}.pt details.card>summary{list-style:none;padding:12px 14px;color:var(--fg);display:flex;
 flex-wrap:wrap;align-items:center;gap:6px 10px}.pt details.card>summary::-webkit-details-marker{display:none}
.pt details.card>summary::after{content:'▾';margin-left:auto;color:var(--mut)}.pt details.card[open]>summary::after{content:'▴'}
.pt details.card>.in{padding:0 14px 14px;border-top:1px solid var(--line)}
.pt .pt-t{font-weight:650}.pt code.addr{word-break:break-all;font-size:12.5px}
.pt-btn{display:inline-flex;align-items:center;justify-content:center;gap:6px;min-height:42px;padding:8px 16px;border-radius:10px;
 border:1px solid var(--acc);background:var(--acc);color:#fff;font:600 14.5px/1.2 inherit;cursor:pointer;text-decoration:none}
.pt-btn[disabled]{background:var(--soft);color:var(--mut);border-color:var(--line);cursor:not-allowed}
.pt-btn2{display:inline-flex;align-items:center;min-height:38px;padding:6px 12px;border-radius:10px;border:1px solid var(--line2);
 background:var(--card);color:var(--fg);font:500 13.5px/1.2 inherit;cursor:pointer;text-decoration:none}
.pt-btn2:hover{border-color:var(--acc);color:var(--acc)}.pt-cp{min-height:30px;padding:3px 10px;font-size:12.5px}
.pt-row{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin:10px 0 0}
.pt form{margin:0}.pt label.blk{display:block;margin:8px 0}.pt label.blk input,.pt label.blk textarea{width:100%;max-width:560px;margin-top:3px}
.pt textarea{background:var(--card);color:var(--fg);border:1px solid var(--line);border-radius:6px;padding:6px 8px;font:inherit}
.pt-steps{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:6px;margin:0 0 10px;padding:0;list-style:none}
.pt-steps li{background:var(--soft);border-radius:10px;padding:8px 6px;text-align:center;font-size:12.5px;color:var(--mut)}
.pt-steps li b{display:block;font-size:15px}.pt-steps li.done{background:var(--goodbg);color:var(--good)}
.pt-steps li.cur{background:var(--card);color:var(--fg);box-shadow:inset 0 0 0 2px var(--acc)}
.pt-next{display:flex;flex-wrap:wrap;gap:10px;align-items:center;justify-content:space-between}
.pt-tiles{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px}
@media(min-width:760px){.pt-tiles{grid-template-columns:repeat(4,minmax(0,1fr))}}
.pt-tiles .stat{padding:10px 12px}.pt-tiles .stat .v{font-size:19px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.pt-tiles .stat .s{font-size:12px;color:var(--mut)}
.pt-tok{display:grid;gap:8px}.pt-tc{display:grid;grid-template-columns:64px 1fr;gap:4px 12px;align-items:start}
.pt-tc img,.pt-d img{border-radius:12px;background:var(--soft);display:block}
.pt-kv{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:4px 8px;font-size:13px;grid-column:1/-1}
.pt-kv div span{display:block;color:var(--mut);font-size:11.5px}.pt-kv div b{font-variant-numeric:tabular-nums;font-weight:600}
.pt-sp{grid-column:1/-1;display:grid;grid-template-columns:1fr 1fr;gap:10px}.pt-sp small{color:var(--mut);font-size:11.5px}
.pt-sp svg{display:block;width:100%;height:36px}.pt-sp small{display:block}
.pt-links{grid-column:1/-1;display:flex;gap:8px;flex-wrap:wrap}
.pt-wide{display:none}@media(min-width:900px){.pt-wide{display:block}.pt-narrow{display:none}}
.pt-tw{overflow-x:auto;background:var(--card);border:1px solid var(--line);border-radius:12px}
.pt-tab td{vertical-align:top;font-size:13px;padding:8px}.pt-tab th{padding:8px;font-size:12px}
.pt-tk{display:flex;gap:8px;align-items:flex-start}.pt-tk img{border-radius:8px;flex:none}
.pt-hist{min-width:110px}.pt-hist svg{display:block;width:104px;height:24px;margin-bottom:4px}.pt-hist small{font-size:11px;color:var(--mut);display:block}.pt-nw{white-space:nowrap}
.pt-lk{display:flex;gap:10px;font-size:12.5px;margin-top:2px;white-space:nowrap}.pt-tab th,.pt-tab td{white-space:normal}
.pt-tab td.n span.mut{font-size:12px;white-space:nowrap}
.pt-dl{display:grid;gap:8px}.pt-dh{display:none}
.pt-d{display:grid;grid-template-columns:auto 96px 1fr;gap:6px 12px;align-items:start;background:var(--card);
 border:1px solid var(--line);border-radius:12px;padding:12px}
.pt-d .c-op{grid-column:1/-1;font-size:13.5px;line-height:1.45}.pt-d .c-ck,.pt-d .c-st{grid-column:1/-1}
.pt-d .c-tm{grid-column:1/-1;color:var(--mut);font-size:12.5px}.pt-d .pt-ed{grid-column:1/-1}
.pt-d input[type=checkbox]{width:22px;height:22px;margin:2px 0 0}.pt-mst{margin-top:6px}
.pt-d .c-ck:empty{display:none}
@media(min-width:900px){
 .pt-dh,.pt-d{grid-template-columns:30px 96px minmax(120px,1fr) minmax(100px,.8fr) minmax(200px,2.2fr) minmax(130px,1fr)}
 .pt-dh{display:grid;gap:12px;padding:0 12px;font-size:12px;color:var(--mut);font-weight:600}
 .pt-d .c-op,.pt-d .c-ck,.pt-d .c-st,.pt-d .c-tm{grid-column:auto}.pt-d .c-tm{color:var(--fg);font-size:13.5px}
 .pt-d .c-ck:empty{display:block}}
.pt-ed>summary{font-size:13.5px}.pt-why{margin:8px 0 0;padding-left:18px;color:var(--mut);font-size:13px}
.pt ul.pt-pf{list-style:none;padding:0;margin:10px 0 0}.pt ul.pt-pf li{padding:6px 0;border-bottom:1px solid var(--line);font-size:13.5px}
.pt ul.pt-pf li span{display:block;color:var(--mut);font-size:12.5px;word-break:break-word}
.pt-note{color:var(--mut);font-size:12.5px;margin:8px 0 0}
.pt-pl{display:block;margin:0 0 4px;color:var(--fg);font-size:12.5px;font-weight:600}.pt-warn{color:var(--warn,#b26b00)}
.pt-post{display:grid;gap:8px}.pt-post pre{white-space:pre-wrap;word-break:break-word;margin:8px 0 0;padding:10px;
 background:var(--soft);border-radius:10px;font:13px/1.45 ui-monospace,Menlo,Consolas,monospace}
.pt label.chk{display:flex;gap:8px;align-items:flex-start;margin:8px 0;font-size:13.5px}
.pt label.chk input{width:20px;height:20px;flex:none;margin:1px 0 0}
.pt fieldset{border:1px solid var(--line);border-radius:10px;padding:4px 12px 10px;margin:10px 0;max-width:584px}
.pt fieldset legend{font-weight:600;font-size:13.5px;padding:0 4px}
</style>"""


def _msg(qs):
    if qs.get("err"):
        return f'<div class=card style="border-color:var(--bad)"><b class=neg>Nije prošlo:</b> {esc(qs["err"])}</div>'
    if qs.get("ok"):
        return f'<div class=card style="border-color:var(--good)">{esc(qs["ok"])}</div>'
    return ""


def _hm(ts, fmt="%d.%m. %H:%M"):
    if not ts:
        return "–"
    try:
        from zoneinfo import ZoneInfo
        return dt.datetime.fromtimestamp(ts, ZoneInfo("Europe/Zagreb")).strftime(fmt)
    except Exception:  # noqa: BLE001
        return time.strftime(fmt, time.localtime(ts))


def _age(sec):
    if sec is None:
        return "–"
    sec = max(0, int(sec))
    return f"{sec // 60} min" if sec < 5400 else f"{sec / 3600:.0f} h" if sec < 48 * 3600 else f"{sec / 86400:.0f} d"


def _usd(x):
    if x is None:
        return "–"
    return f"${x / 1e6:,.2f}M" if x >= 1e6 else f"${x / 1e3:,.1f}k" if x >= 1e3 else f"${x:,.0f}"


def _n(x):
    return "–" if x is None else f"{int(x):,}".replace(",", ".")


def _copy(addr, label="Kopiraj"):
    return (f"<button type=button class='pt-btn2 pt-cp' data-a='{esc(addr)}' onclick=\"return ptCopy(event,this)\">"
            f"{label}</button>")


def wallet_state(con, c=None, ch=None, now=None):
    """{"ch", "addr", "bal", "need", "ready", "n"}: izabrani novčanik, saldo i koliko treba za nacrte koji čekaju."""
    c = c or launch.cfg()
    ch = launch.wallet_choice(con) if ch is None else ch
    addr = launch.address(ch) if ch != launch.OFF else None
    bal = balance(addr) if addr else None
    n_open = sum(1 for d in store.drafts(con) if d["stanje"] in CAN_LAUNCH + ("u_redu",))
    left = max(1, c["dnevno"] - launch.sent_today(con, int(now or time.time())))
    n = max(1, min(n_open, left))
    need = max(c["min_sol"].get(ch, 0.03) if ch != launch.OFF else 0.03, n * c["max_sol"] + c["rezerva_sol"])
    return {"ch": ch, "addr": addr, "bal": bal, "need": need, "ready": bool(addr) and bal is not None and bal >= need,
            "n": n}


def pilot_gate(con, ws, c=None, now=None):
    """[razlozi] zašto je „Odobri pilot” onemogućen (prazno = smije). Ime env varijable samo u poruci što nedostaje."""
    from trade import executor
    c = c or launch.cfg()
    now = int(now or time.time())
    why = []
    if os.path.exists(executor.STOP_FILE):
        why.append("kill switch je aktivan")
    if ws["ch"] == launch.OFF:
        why.append("novčanik je isključen")
    elif not ws["addr"]:
        why.append({launch.TOOL: "nema novčanika pokusa: stvori ga",
                    launch.SEPARATE: "PUMP_DEV_PRIVATE_KEY nije upisan na Renderu",
                    launch.TRADING: "SOLANA_PRIVATE_KEY nije postavljen"}.get(ws["ch"], "nema ključa"))
    elif ws["bal"] is None:
        why.append("saldo novčanika nije pročitan: osvježi stranicu")
    elif ws["bal"] < ws["need"]:
        why.append(f"saldo {ws['bal']:.4f} SOL: treba još {ws['need'] - ws['bal']:.4f} SOL")
    if c["ipfs"] != "pinata":
        why.append("PINATA_JWT nije upisan na Renderu: bez njega slika i opis ne idu na IPFS")
    pf = store.get(con, "provjera") or {}
    if not pf:
        why.append("provjera prije lansiranja još nije pokrenuta")
    elif not pf.get("zeleno"):
        why.append("provjera prije lansiranja ne prolazi")
    elif now - (pf.get("ts") or 0) > launch.PREFLIGHT_MAX_AGE_S:
        why.append("provjera je starija od 30 min: ponovi je")
    if not any(d["stanje"] in CAN_LAUNCH and guards.fresh_ok(store.check_of(d), now) for d in store.drafts(con)):
        why.append("nijedan nacrt nema prolaznu provjeru imena")
    return why


# ---- nadzorna ploča -------------------------------------------------------------------------------------------

def _spark(pts, label, fmt):
    """Mali graf jedne veličine kroz vrijeme (jedna os, jedna serija): linija 2 px, točka na zadnjoj vrijednosti,
    oblačić (title) po točki. pts = [(ts, v)]."""
    pts = [(t, v) for t, v in pts if v is not None]
    if len(pts) < 2:
        return f"<small>{esc(label)}: još nema povijesti</small>"
    step = max(1, len(pts) // 48)
    pts = pts[::step] + ([pts[-1]] if (len(pts) - 1) % step else [])
    t0, t1 = pts[0][0], pts[-1][0]
    hi = max(v for _, v in pts)
    if not hi:
        return f"<small>{esc(label)}: još ništa</small>"
    W, H = 120.0, 30.0

    def xy(t, v):
        return (W * (t - t0) / ((t1 - t0) or 1), H - 2 - (H - 4) * v / hi)
    xs = [xy(t, v) for t, v in pts]
    line = " ".join(f"{x:.1f},{y:.1f}" for x, y in xs)
    hits = "".join(f"<rect x='{max(0, x - 3):.1f}' y='0' width='6' height='{H:.0f}' fill='transparent'><title>"
                   f"{esc(_hm(t))}: {esc(fmt(v))}</title></rect>" for (x, _y), (t, v) in zip(xs, pts))
    lx, ly = xs[-1]
    return (f"<small>{esc(label)} {esc(fmt(pts[-1][1]))}</small>"
            f"<svg viewBox='0 0 {W:.0f} {H:.0f}' preserveAspectRatio='none' role=img aria-label='{esc(label)}'>"
            f"<line x1=0 y1='{H - 1:.0f}' x2='{W:.0f}' y2='{H - 1:.0f}' stroke='var(--line)' stroke-width=1 />"
            f"<polyline points='{line}' fill=none stroke='var(--acc)' stroke-width=2 stroke-linejoin=round "
            f"vector-effect=non-scaling-stroke />"
            f"<circle cx='{lx:.1f}' cy='{ly:.1f}' r=2.5 fill='var(--acc)' />{hits}</svg>")


def _sparks(r):
    sn = r["snimci"][-7 * 144:]
    vol = _spark([(s["ts"], s["promet_h24"]) for s in sn], "Promet 24 h", _usd)
    tx = _spark([(s["ts"], (s["kupnje_h24"] or 0) + (s["prodaje_h24"] or 0) if s["kupnje_h24"] is not None else None)
                 for s in sn], "Transakcije 24 h", _n)
    return vol, tx


def _links(mint, small=False):
    m = esc(mint)
    if small:
        return (f"<a href='https://pump.fun/coin/{m}' target=_blank rel='noopener noreferrer'>pump.fun ↗</a> "
                f"<a href='https://dexscreener.com/solana/{m}' target=_blank rel='noopener noreferrer'>DexScreener ↗</a>")
    return (f"<a class='pt-btn2 pt-cp' href='https://pump.fun/coin/{m}' target=_blank rel='noopener noreferrer'>pump.fun ↗</a>"
            f"<a class='pt-btn2 pt-cp' href='https://dexscreener.com/solana/{m}' target=_blank rel='noopener noreferrer'>"
            "DexScreener ↗</a>")


def _net(x, d=4):
    if x is None:
        return "–"
    return f"<b class={'pos' if x >= 0 else 'neg'}>{x:+.{d}f}</b>"


def _fee_cell(r, d=4):
    if r["naknada_sol"] is None:
        return "–"
    return _sol(r["naknada_sol"], d) + (" <span class=mut>(procjena samo za krivulju)</span>" if r["bondan"] else "")


def dash_html(con, now=None):
    """Nadzorna ploča (samo baza, bez mreže). Isti HTML vraća /pump-tokeni/ploca za osvježavanje svakih ~10 min."""
    now = int(now or time.time())
    db = outcomes.dashboard(con, now)
    t, rows = db["tiles"], db["rows"]
    every = outcomes.refresh_every_s()
    fresh = (f"osvježeno {_hm(t['osvjezeno_ts'], '%H:%M')} (prije {_age(now - t['osvjezeno_ts'])})"
             if t["osvjezeno_ts"] else "prvi snimak stiže u sljedećih ~10 min")

    def tile(label, v, sub=""):
        return f"<div class=stat><div class=l>{label}</div><div class=v>{v}</div><div class=s>{sub}</div></div>"
    trez = ("–" if t["za_podici_sol"] is None else _sol(t["za_podici_sol"], 4))
    tiles = "".join([
        tile("Lansirano", str(t["lansirano"]), f"s prometom {t['s_prometom']} · bondano {t['bondano']}"),
        tile("Promet", _usd(t["promet_usd"]), f"≈ {t['promet_sol']:.2f} SOL"),
        tile("Transakcije", _n(t["kupnje"] + t["prodaje"]), f"kupnje {_n(t['kupnje'])} · prodaje {_n(t['prodaje'])}"),
        tile("Naknada (procjena)", _sol(t["naknada_sol"]), "SOL, 0,30 % prometa, bez vlastite kupnje"),
        tile("Trošak lansiranja", _sol(t["trosak_sol"]), "SOL, izmjereno"),
        tile("Neto", _net(t["neto_sol"]), "SOL, naknada − trošak"
             + (f" · u tokenima {t['u_tokenima_sol']:.3f}" if t.get("u_tokenima_sol") else "")),
        tile("Za podići", trez, ("SOL u trezoru" if t["za_podici_sol"] is not None else "samo procjena")
             + f" · podignuto {t['podignuto_sol']:.4f}"),
        tile("Osvježeno", _hm(t["osvjezeno_ts"], "%H:%M") if t["osvjezeno_ts"] else "–", f"svakih {every // 60} min"),
    ])
    claim = ("<form method=post action=/pump-tokeni/podigni onsubmit=\"return ptClaim(this)\" class=pt-row>"
             "<input type=hidden name=potvrda value=''>"
             f"<input type=hidden name=iznos value='{(t['za_podici_sol'] or 0):.6f}'>"
             "<button class=pt-btn2>💰 Podigni naknadu</button>"
             "<span class=pt-note style=margin:0>Naknada čeka u trezoru novčanika; ne isplaćuje se sama.</span></form>")
    cards, trs, posts = [], [], []
    for r in rows:
        posts.append(post_block(con, r, open_=not posts))
        img = f"<img src='/pump-tokeni/slika/{r['nacrt_id']}' width=64 height=64 alt='' loading=lazy>"
        bond = badge("bondan", "good") if r["bondan"] else badge("na krivulji", "") if r["bondan"] == 0 else ""
        vol, tx = _sparks(r)
        cards.append(
            f"<div class='card pt-tc'>{img}<div><div class=pt-t>{esc(r['simbol'])} <span class=mut style='font-weight:400'>"
            f"{esc(r['ime'] or '')}</span></div><div class=mut style='font-size:12.5px'>staro {_age(r['starost_s'])} "
            f"{bond}</div></div><div class=pt-kv>"
            f"<div><span>Promet 5 min</span><b>{_usd(r['promet_m5'])}</b></div>"
            f"<div><span>1 h</span><b>{_usd(r['promet_h1'])}</b></div><div><span>24 h</span><b>{_usd(r['promet_h24'])}</b></div>"
            f"<div><span>Kupnje / prodaje</span><b>{_n(r['kupnje'])} / {_n(r['prodaje'])}</b></div>"
            f"<div><span>Mcap sada</span><b>{_usd(r['mcap_usd'])}</b></div><div><span>Najviši</span><b>{_usd(r['max_mcap_usd'])}</b></div>"
            f"<div><span>Naknada SOL</span><b>{_sol(r['naknada_sol'])}</b></div><div><span>Trošak SOL</span>"
            f"<b>{_sol(r['trosak_sol'])}</b></div><div><span>Neto SOL</span>{_net(r['neto_sol'])}</div></div>"
            + ("<div class=pt-note style='grid-column:1/-1;margin:0'>Naknada: procjena samo za krivulju.</div>"
               if r["bondan"] else "")
            + f"<div class=pt-sp><div>{vol}</div><div>{tx}</div></div><div class=pt-links>{_links(r['mint'])}</div></div>")
        def td(h, v=None):
            return f"<td class=n data-v='{esc(v if v is not None else 0)}'>{h}</td>"
        trs.append(
            f"<tr><td data-v='{esc(r['simbol'])}'><div class=pt-tk><img src='/pump-tokeni/slika/{r['nacrt_id']}' "
            f"width=40 height=40 alt='' loading=lazy><div><b>{esc(r['simbol'])}</b> {bond}<br><span class=mut>"
            f"{esc(r['ime'] or '')} · {_age(r['starost_s'])}</span><div class=pt-lk>{_links(r['mint'], small=True)}"
            "</div></div></div></td>"
            + td(_usd(r["promet_m5"]), r["promet_m5"])
            + td(_usd(r["promet_h1"]), r["promet_h1"]) + td(_usd(r["promet_h24"]), r["promet_h24"])
            + td(f"<span class=pt-nw>{_n(r['kupnje'])} / {_n(r['prodaje'])}</span>",
                 (r["kupnje"] or 0) + (r["prodaje"] or 0))
            + td(f"{_usd(r['mcap_usd'])}<br><span class=mut>max {_usd(r['max_mcap_usd'])}</span>", r["mcap_usd"])
            + td(f"{_net(r['neto_sol'])}<br><span class=mut>naknada {_sol(r['naknada_sol'])}</span>"
                 + ("<br><span class=mut>samo krivulja</span>" if r["bondan"] else "")
                 + f"<br><span class=mut>trošak {_sol(r['trosak_sol'])}</span>", r["neto_sol"])
            + f"<td class=pt-hist>{vol}{tx}</td></tr>")
    heads = [("Token", ""), ("5 min", "n"), ("1 h", "n"), ("24 h", "n"), ("Kupnje / prodaje", "n"), ("Mcap", "n"),
             ("Neto SOL", "n"), ("Povijest (7 d)", "")]
    table_html = ("<div class=pt-tw><table class='s nocols pt-tab' id=ptdt><thead><tr>"
                  + "".join(f"<th class='{c}'>{h}</th>" for h, c in heads) + "</tr></thead><tbody>"
                  + "".join(trs) + "</tbody></table></div>") if trs else ""
    return (f"<section id=ptdash data-every='{every}'><div class=pt-next><h2 style='margin:4px 0'>Nadzorna ploča</h2>"
            f"<span class=mut style='font-size:12.5px'>{esc(fresh)}</span></div>"
            f"<div class=pt-tiles>{tiles}</div>{claim}"
            f"<div class='pt-narrow pt-tok' style='margin-top:10px'>{''.join(cards)}</div>"
            f"<div class=pt-wide style='margin-top:10px'>{table_html}</div>"
            + (f"<h2 style='margin:18px 0 8px'>Objava za kopiranje</h2><div class=pt-post>{''.join(posts)}</div>"
               "<p class=pt-note>Samo za kopiranje: alat ništa ne objavljuje (ni X, ni Buffer, ni Telegram).</p>"
               if posts else "")
            + f"<p class=pt-note>Promet i transakcije: DexScreener, zbroj od lansiranja (za tokene starije od 24 h donja "
            f"granica). Naknada: {esc(outcomes.RATE_NOTE)}; bez naknade od vlastite kupnje. Neto = procjena naknade − "
            f"izmjereni trošak lansiranja; vlastita kupnja je vezan kapital u tokenima ({BUY_NOTE}).</p></section>")


def post_text(ime, simbol, opis, mint):
    """Tekst objave za kopiranje: ime ($SIMBOL), opis (isti kao na lancu), CA, poveznica na pump.fun."""
    return f"{ime} (${simbol})\n{opis}\nCA: {mint}\nhttps://pump.fun/coin/{mint}"


def post_block(con, r, open_=False):
    """„Objava za kopiranje” uz lansiran token: tekst, gumb Kopiraj (clipboard, zamjena prompt), Preuzmi sliku. Ništa
    se ne šalje nikamo."""
    d = store.draft(con, r["nacrt_id"]) or {}
    txt = post_text(d.get("ime") or r.get("ime") or "", d.get("simbol") or r.get("simbol") or "", d.get("opis") or "",
                    r["mint"])
    fn = f"{(d.get('simbol') or 'token').lower()}.png"
    return (f"<details class=card{' open' if open_ else ''}><summary><span class=pt-t>{esc(r['simbol'] or '')}</span>"
            "<span class=mut>objava za kopiranje</span></summary><div class=in>"
            f"<pre>{esc(txt)}</pre><div class=pt-row>{_copy(txt, '📋 Kopiraj')}"
            f"<a class=pt-btn2 href='/pump-tokeni/slika/{r['nacrt_id']}' download='{esc(fn)}'>⬇ Preuzmi sliku</a></div>"
            "</div></details>")


def dash_fragment():
    con = _con()
    try:
        return dash_html(con)
    finally:
        con.close()


# ---- koraci, novčanik, provjera -------------------------------------------------------------------------------

def _steps_html(con, ws, gate, now):
    pf = store.get(con, "provjera") or {}
    pf_ok = bool(pf.get("zeleno")) and now - (pf.get("ts") or 0) <= launch.PREFLIGHT_MAX_AGE_S
    names_ok = any(d["stanje"] in CAN_LAUNCH and guards.fresh_ok(store.check_of(d), now) for d in store.drafts(con))
    pilot = bool(launch.queue(con)) and not launch.stopped(con)
    done = [ws["ready"], pf_ok, names_ok, pilot]
    cur = next((i for i, x in enumerate(done) if not x), None)
    names = ("Novčanik", "Provjera", "Nacrti", "Pilot")
    lis = "".join(f"<li class='{'done' if done[i] else 'cur' if i == cur else ''}'><b>{'✓' if done[i] else i + 1}</b>"
                  f"{n}</li>" for i, n in enumerate(names))
    if cur == 0 and not ws["addr"]:
        cta = ("Prvo novčanik pokusa.", "<form method=post action=/pump-tokeni/stvori onsubmit=\"if(!confirm('Stvoriti "
               "novčanik pokusa? Ključ ostaje samo na disku servisa i nikad se ne prikazuje. Šalji mu samo male iznose.'))"
               "return false;this.potvrda.value='1'\"><input type=hidden name=potvrda value=''>"
               "<button class=pt-btn>🔑 Stvori novčanik</button></form>") if ws["ch"] == launch.TOOL else \
            ("Odaberi novčanik.", "<a class=pt-btn href='#ptw' onclick=\"document.getElementById('ptw').open=true\">"
                                  "Novčanik ↓</a>")
    elif cur == 0:
        miss = ws["need"] - (ws["bal"] or 0)
        cta = (f"Pošalji još {miss:.4f} SOL na novčanik.", _copy(ws["addr"], "Kopiraj adresu"))
    elif cur == 1:
        cta = ("Pokreni provjeru prije lansiranja.", "<button class=pt-btn type=submit form=ptl "
                                                    "formaction=/pump-tokeni/provjera>🩺 Pokreni provjeru</button>")
    elif cur == 2:
        cta = ("Provjeri imena nacrta.", "<form method=post action=/pump-tokeni/provjeri><input type=hidden name=id "
                                         "value=sve><button class=pt-btn>🔎 Provjeri imena</button></form>")
    elif cur == 3:
        cta = (("Odaberi nacrte i odobri pilot." if not gate else "Još nedostaje: " + gate[0] + "."),
               "<a class=pt-btn href='#ptnacrti'>Nacrti ↓</a>")
    else:
        cta = ("Pilot je odobren: posao lansira jedan po jedan.", "")
    return (f"<div class=card><ol class=pt-steps>{lis}</ol><div class=pt-next><span>{esc(cta[0])}</span>{cta[1]}</div>"
            "</div>")


def _wallet_html(con, c, ws, steps=False):
    ch, addr, bal = ws["ch"], ws["addr"], ws["bal"]
    saved = store.get(con, "novcanik", launch.TOOL)
    if ch == launch.OFF:
        state = badge("isključen", "bad")
    elif not addr:
        state = badge("nema novčanika", "bad")
    elif ws["ready"]:
        state = badge("spreman", "good")
    else:
        state = badge(f"treba još {ws['need'] - (bal or 0):.4f} SOL", "warn")
    summ = ("<span class=pt-t>Novčanik</span>"
            + (f"<code>{esc(_short(addr))}</code>{_copy(addr)}" if addr else "")
            + (f"<span>{bal:.4f} SOL</span>" if bal is not None else "") + state)
    inner = [f"<p style='margin:10px 0 4px'><b>{esc(WLABEL[ch])}</b></p>"]
    if addr:
        inner.append(f"<p style='margin:0'><code class=addr>{esc(addr)}</code></p>"
                     f"<p class=pt-note>Za {ws['n']} nacrt(a) treba najmanje {ws['need']:.4f} SOL.</p>")
    if saved == launch.TRADING and ch == launch.OFF:
        inner.append("<p class=neg>Trgovački je bio izabran, ali njegov prekidač nije uključen.</p>")
    tool = devwallet.address()
    if tool:
        tb = balance(tool)
        inner.append("<form method=post action=/pump-tokeni/vrati onsubmit=\"return ptRefund(this)\" class=pt-row>"
                     "<input name=adresa placeholder='adresa za povrat' style='flex:1 1 220px' autocomplete=off>"
                     "<input type=hidden name=potvrda value=''>"
                     f"<input type=hidden name=saldo value='{tb or 0:.6f}'><button class=pt-btn2>↩ Vrati ostatak</button>"
                     "</form><p class=pt-note>Šalje sav SOL s novčanika pokusa (minus mrežna naknada); prije slanja "
                     "simulacija.</p>")
    elif ch == launch.TOOL and not steps:   # s trakom koraka gumb je već gore (jedan poziv na akciju)
        inner.append("<form method=post action=/pump-tokeni/stvori class=pt-row onsubmit=\"if(!confirm('Stvoriti "
                     "novčanik pokusa? Ključ ostaje samo na disku servisa i nikad se ne prikazuje.'))return false;"
                     "this.potvrda.value='1'\"><input type=hidden name=potvrda value=''><button class=pt-btn2>"
                     "🔑 Stvori novčanik pokusa</button></form>")
    radios = "".join(f"<label style='display:block;margin:6px 0'><input type=radio name=izbor value={k} "
                     f"{'checked' if k == ch else ''}> {esc(v)}</label>" for k, v in WLABEL.items())
    inner.append("<details style='margin-top:10px'><summary>Promijeni novčanik</summary>"
                 "<form method=post action=/pump-tokeni/novcanik onsubmit=\"return ptWallet(this)\">" + radios +
                 "<p class=neg style='font-size:13px'>Trgovački novčanik miješa trošak s pravim novcem i ostaje javno "
                 f"označen kao kreator. Ne lansira se ispod {c['min_sol'][launch.TRADING]:g} SOL.</p>"
                 "<label style='display:block;margin:6px 0'><input type=checkbox name=potvrda value=1> Potvrđujem "
                 "trgovački novčanik</label><button class=pt-btn2>Spremi</button></form></details>")
    inner.append("<p class='pt-note neg'>Samo mali iznosi. Ključ je samo na disku servisa: ako se disk izgubi, gubi "
                 "se i SOL. Nakon svake faze „Vrati ostatak”.</p>")
    op = " open" if not ws["ready"] else ""
    return f"<details id=ptw class=card{op}><summary>{summ}</summary><div class=in>{''.join(inner)}</div></details>"


def _preflight_html(con, now):
    pf = store.get(con, "provjera") or {}
    st = launch.stopped(con)
    pil = store.get(con, "pilot") or {}
    steps = pf.get("koraci") or []
    bad = [x for x in steps if x["ok"] is False]
    if not pf:
        head = badge("nije pokrenuta", "warn") + " <span>Provjera prije lansiranja</span>"
    elif not bad:
        old = now - (pf.get("ts") or 0) > launch.PREFLIGHT_MAX_AGE_S
        head = (badge("zastarjela", "warn") if old else badge("sve u redu", "good")) + \
            f" <span>Provjera prije lansiranja · {_hm(pf.get('ts'), '%H:%M')}</span>"
    else:
        head = (badge(f"{len(bad)} od {len(steps)} ne prolazi", "bad") + " <span>"
                + esc(", ".join(x["naziv"] for x in bad)) + "</span>")
    lis = "".join(f"<li>{badge('radi', 'good') if x['ok'] else badge('ne radi', 'bad') if x['ok'] is False else badge('pri lansiranju', 'warn')} "
                  f"{esc(x['naziv'])}<span>{esc(x['tekst'])}</span></li>" for x in steps)
    per = pf.get("nacrti") or []
    if per:
        lis += "<li><b>Suha proba po nacrtu</b>" + "".join(
            f"<span>{'✓' if r.get('ok') else '✗'} {esc(r.get('simbol') or '')} · {esc(store.cet(r.get('termin')))} CET · "
            f"{esc(_kupnja_txt(r.get('kupnja')))} · poveznice {'da' if r.get('poveznice') else 'ne'} · "
            + (f"−{r['sol']:.5f} SOL" if r.get("sol") is not None else "–")
            + f" · rezerva {({True: 'ok', False: 'ne', None: '?'})[r.get('rezerva_ok')]}"
            + (" (bez kupnje)" if r.get("bez_kupnje") else "")
            + (f" · {esc((r.get('why') or '')[:140])}" if not r.get("ok") else "") + "</span>" for r in per) + "</li>"
    q = launch.queue(con)
    red = (f"<span class=neg>zaustavljen: {esc(st.get('razlog'))}</span>" if st else
           f"radi, u redu {len(q)} (odobren {_hm(pil.get('odobren_ts'))})" if pil and q else
           "prazan" if pil else "pilot nije odobren")
    note = store.get(con, "red_razlog") or {}
    return (f"<details class=card{' open' if bad else ''}><summary>{head}</summary><div class=in>"
            + (f"<ul class=pt-pf>{lis}</ul>" if lis else "<p class=pt-note>Još nema rezultata.</p>")
            + "<div class=pt-row><button class=pt-btn2 type=submit form=ptl formaction=/pump-tokeni/provjera>🩺 Pokreni "
              "provjeru</button><span class=pt-note style=margin:0>za odabrane nacrte, bez odabira za sve</span></div>"
            + f"<p style='margin:10px 0 0'><b>Red:</b> {red}"
            + (f"<br><span class=pt-note>Zadnja napomena: {esc(note.get('tekst', ''))}</span>" if note and q else "")
            + "</p><form method=post action=/pump-tokeni/zaustavi class=pt-row><button class=pt-btn2>⏹ Zaustavi red"
              "</button></form></div></details>")


# ---- nacrti ---------------------------------------------------------------------------------------------------

def _check_cell(d):
    r = store.check_of(d)
    if not r:
        return badge("ime nije provjereno", "")
    if r.get("ok") and guards.fresh_ok(r):
        return badge("ime prolazi", "good")
    if r.get("ok"):
        return badge("provjera starija od 24 h", "warn")
    return badge("ime ne prolazi", "bad") + "<div class=pt-note style='margin:4px 0 0'>" + \
        "; ".join(esc(x) for x in r.get("razlozi") or []) + "</div>"


def _termin_of(d, now=None):
    return d.get("termin_ts") or store.default_termin(now)


def _kupnja_txt(k):
    k = float(k or 0)
    return "bez kupnje" if not k else f"kupnja {k:g} SOL".replace(".", ",")


def _plan_line(con, d, defaults=None, now=None):
    """Kratko na kartici: termin (CET), kupnja, poveznice da/ne."""
    links = store.link_urls(con, d, defaults)
    return (f"<span class=pt-pl>⏰ {esc(store.cet(_termin_of(d, now)))} CET"
            + ("" if d.get("termin_ts") else " <span class=mut>(zadano)</span>")
            + f" · {esc(_kupnja_txt(d.get('kupnja_sol')))} · poveznice {'da' if links else 'ne'}</span>")


def _edit_form(d, defaults=None, now=None):
    did = d["id"]
    lock = d["stanje"] in ("salje", "lansiran")
    if lock:
        return "<details class=pt-ed><summary>Detalji</summary><p class=pt-note>Lansiran ili se šalje: ne mijenja se.</p></details>"
    defaults = defaults or {}

    def inp(name, label, maxlen, value=None, extra=""):
        v = d.get(name) if value is None else value
        return (f"<label class=blk><b>{label}</b><br><input name={name} maxlength={maxlen} {extra}"
                f"value=\"{esc(v if v is not None else '')}\"></label>")

    def link(name, label, ph):
        dv = defaults.get(name) or ""
        hint = f"prazno = zadana ({esc(dv)})" if dv else "prazno = bez poveznice"
        return (f"<label class=blk><b>{label}</b> <span class=mut style='font-size:12px'>{hint}; „-” = bez</span><br>"
                f"<input name={name} maxlength=100 inputmode=url autocomplete=off placeholder='{ph}' "
                f"value=\"{esc(d.get(name) or '')}\"></label>")
    termin = store.cet(_termin_of(d, now), "%Y-%m-%dT%H:%M")
    k = float(d.get("kupnja_sol") or 0)
    return ("<details class=pt-ed><summary>Uredi</summary>"
            f"<form method=post action=/pump-tokeni/uredi><input type=hidden name=id value={did}>"
            + inp("ime", "Ime", 32) + inp("simbol", "Simbol (2-10 slova ili brojki)", 10)
            + inp("tema", "Tema", 80) + inp("datum_teme", "Datum teme (GGGG-MM-DD)", 10)
            + "<label class=blk><b>Opis</b> <span class=mut>(engleski, istinit, bez obećanja i poveznica)</span><br>"
              f"<textarea name=opis rows=4 maxlength=500>{esc(d['opis'] or '')}</textarea></label>"
            + inp("skupina", "Skupina pokusa", 40)
            + f"<fieldset><legend>Lansiranje</legend>"
              f"<label class=blk><b>Lansiraj u (CET)</b><br><input type=datetime-local name=termin value='{termin}' "
              "step=60></label>"
            + inp("kupnja_sol", f"Vlastita kupnja (SOL, 0–{store.HARD_MAX_KUPNJA:g})", 8,
                  value=(f"{k:g}" if k else "0"), extra=f"inputmode=decimal list=ptkup ")
            + f"<p class=pt-note style='margin:0'>U istoj transakciji lansiranja, javno vidljiva kao devova; "
              f"{BUY_NOTE}. Ako bi kupnja ostavila manje od rezerve, lansira se bez nje.</p></fieldset>"
            + "<fieldset><legend>Poveznice (u metapodacima tokena)</legend>"
            + link("twitter", "X / Twitter", "https://x.com/…") + link("telegram", "Telegram", "https://t.me/…")
            + link("website", "Web stranica", "https://…")
            + f"<label class=chk><input type=checkbox name=brend_ok value=1 {'checked' if d.get('brend_ok') else ''}>"
              f"<span>{esc(BRAND_LABEL)} <span class=mut>(trajno i javno veže brend uz token)</span></span></label>"
            + "".join(f"<p class=pt-note style='margin:2px 0'>{esc(x)}</p>" for x in LINK_NOTES) + "</fieldset>"
            + "<button class=pt-btn2>💾 Spremi</button></form>"
            + f"<form method=post action=/pump-tokeni/slika class=pt-row><input type=hidden name=id value={did}>"
              "<input type=hidden name=data><label class=pt-btn2>🖼 Vlastita slika<input type=file accept='image/*' "
              "onchange=\"ptImg(this)\" style='display:none'></label></form>"
            + f"<div class=pt-row><form method=post action=/pump-tokeni/generiraj><input type=hidden name=id value={did}>"
              "<button class=pt-btn2>🎨 Slika iz generatora</button></form>"
              f"<form method=post action=/pump-tokeni/provjeri><input type=hidden name=id value={did}>"
              "<button class=pt-btn2>🔎 Provjeri ime</button></form></div></details>")


def _draft_card(con, d, defaults=None, now=None):
    did = d["id"]
    w, k = STATE_WORDS.get(d["stanje"], (d["stanje"], ""))
    can = d["stanje"] in CAN_LAUNCH
    done = d["stanje"] in ("salje", "lansiran")
    img = (f"<img src='/pump-tokeni/slika/{did}' width=96 height=96 alt='' loading=lazy>" if d["slika"] else
           "<span class=mut>nema slike</span>")
    return (f"<div class=pt-d id=n{did}><label title='Za pilot'><input type=checkbox name=id value={did} form=ptl "
            f"{'disabled' if not can else ''} aria-label='Odaberi {esc(d['simbol'] or '')} za pilot'></label>{img}"
            f"<div><div class=pt-t>{esc(d['ime'] or '(bez imena)')}</div><code>{esc(d['simbol'] or '')}</code>"
            f"<div class=pt-mst>{badge(w, k)}</div></div>"
            f"<div class=c-tm>{esc(d['tema'] or '')}{(' · ' + esc(d['datum_teme'])) if d['datum_teme'] else ''}</div>"
            f"<div class=c-op>{'' if done else _plan_line(con, d, defaults, now)}{esc(d['opis'] or '')}</div><div class=c-ck>{'' if done else _check_cell(d)}</div>"
            f"{_edit_form(d, defaults, now)}</div>")


def _drafts_html(con):
    head = ("<div class=pt-dh><span></span><span>Slika</span><span>Ime</span><span>Tema</span>"
            "<span>Termin · opis</span><span>Provjera imena</span></div>")
    ds = store.drafts(con)
    defaults = store.link_defaults(con)
    now = int(time.time())
    open_ = sorted([d for d in ds if d["stanje"] not in ("salje", "lansiran")], key=lambda d: (_termin_of(d, now), d["id"]))
    done = [d for d in ds if d["stanje"] in ("salje", "lansiran")]
    out = ("<datalist id=ptkup><option value=0><option value=0.04></datalist><div class=pt-dl>" + head
           + ("".join(_draft_card(con, d, defaults, now) for d in open_) or
              "<div class=card>Nema nacrta koji čekaju. Dodaj novi pod „Više”.</div>") + "</div>")
    if done:
        out += (f"<details class=card style='margin-top:8px'><summary><span class=pt-t>Lansirani i u slanju</span>"
                f"<span class=mut>{len(done)}</span></summary><div class=in><div class=pt-dl style='margin-top:10px'>"
                + "".join(_draft_card(con, d, defaults, now) for d in done) + "</div></div></details>")
    return out


def _pilot_html(gate):
    dis = " disabled" if gate else ""
    why = ("<ul class=pt-why>" + "".join(f"<li>{esc(x)}</li>" for x in gate) + "</ul>") if gate else ""
    return ("<div class=card><div class=pt-row style='margin:0'>"
            f"<button class=pt-btn type=submit form=ptl{dis}>✅ Odobri pilot</button>"
            "<button type=button class=pt-btn2 onclick=\"document.querySelectorAll('input[name=id][form=ptl]:not([disabled])')"
            ".forEach(function(x){x.checked=true})\">Odaberi sve</button>"
            "<button class=pt-btn2 type=submit form=ptl formaction=/pump-tokeni/provjera>🩺 Provjera za odabrane</button>"
            "</div>" + (f"<p class=pt-note><b>Još nedostaje:</b></p>{why}" if gate else
                        "<p class=pt-note>Odobravaš raspored: okvir potvrde pokazuje za svaki nacrt termin (CET), "
                        "vlastitu kupnju, poveznice i ukupni trošak; posao lansira svaki u njegovom terminu. Termin koji "
                        "prođe više od 15 min se ne nadoknađuje.</p>") + "</div>")


def _more_html(con, c, now):
    why = launch.blocked_reason(con, now)
    dflt = store.link_defaults(con)
    return ("<details class=card><summary><span class=pt-t>Više</span><span class=mut>novi nacrt, teme, zabranjene "
            "riječi, stropovi</span></summary><div class=in>"
            "<div class=pt-row><form method=post action=/pump-tokeni/provjeri><input type=hidden name=id value=sve>"
            "<button class=pt-btn2>🔎 Provjeri sva imena</button></form><form method=post action=/pump-tokeni/teme>"
            "<button class=pt-btn2>💡 Predloži teme</button></form></div>"
            "<h3>Novi nacrt</h3><form method=post action=/pump-tokeni/nacrt>"
            + "".join(f"<label class=blk><b>{lab}</b><br><input name={n} maxlength={m}></label>"
                      for n, lab, m in (("ime", "Ime", 32), ("simbol", "Simbol", 10), ("tema", "Tema", 80),
                                        ("datum_teme", "Datum (GGGG-MM-DD)", 10), ("skupina", "Skupina", 40)))
            + "<label class=blk><b>Opis</b><br><textarea name=opis rows=3 maxlength=500></textarea></label>"
              "<button class=pt-btn2>➕ Dodaj</button></form>"
              "<h3>Zadane poveznice</h3><p class=pt-note>Upišeš jednom; nacrt bez vlastite vrijednosti ih nasljeđuje, "
              "prazno = bez poveznice. Idu u metapodatke tokena (pump.fun ih prikazuje).</p>"
              "<form method=post action=/pump-tokeni/zadane>"
            + "".join(f"<label class=blk><b>{lab}</b><br><input name={n} maxlength=100 inputmode=url autocomplete=off "
                      f"placeholder='{ph}' value=\"{esc(dflt.get(n) or '')}\"></label>"
                      for n, lab, ph in (("twitter", "X / Twitter", "https://x.com/…"),
                                         ("telegram", "Telegram", "https://t.me/…"),
                                         ("website", "Web stranica", "https://…")))
            + f"<label class=chk><input type=checkbox name=brend_ok value=1 {'checked' if dflt.get('brend_ok') else ''}>"
              f"<span>{esc(BRAND_LABEL)} <span class=mut>(trajno i javno veže brend uz token)</span></span></label>"
            + "".join(f"<p class=pt-note style='margin:2px 0'>{esc(x)}</p>" for x in LINK_NOTES)
            + "<button class=pt-btn2>Spremi zadane</button></form>"
              "<h3>Zabranjene riječi</h3>"
              f"<p class=pt-note>Uvijek: {esc(', '.join(guards.BANNED))}, „by &lt;ime&gt;”, poveznice. Tvoje (zarezom):</p>"
              "<form method=post action=/pump-tokeni/zabranjene class=pt-row><input name=rijeci style='flex:1 1 240px' "
            f"value=\"{esc(', '.join(store.get(con, 'zabranjene', []) or []))}\"><button class=pt-btn2>Spremi</button>"
            "</form><h3>Stropovi</h3>"
            f"<p class=pt-note>Danas poslano {launch.sent_today(con, now)} od {c['dnevno']} (tvrdi max "
            f"{launch.HARD_MAX_DNEVNO}) · razmak najmanje {int(c['razmak_s'] // 60)} min · simulacija najviše "
            f"{c['max_sol']:g} SOL po tokenu + kupnja × {launch.BUY_CAP_MULT:g} · vlastita kupnja najviše "
            f"{store.HARD_MAX_KUPNJA:g} SOL · rezerva {c['rezerva_sol']:g} SOL · očekivano "
            f"{launch.EXPECTED[0]:g}–{launch.EXPECTED[1]:g} SOL po tokenu bez kupnje · red: "
            f"{esc(why) if why else 'spreman'}</p></div></details>")


def _attempt_rows(con):
    rows = []
    for a in store.attempts(con, 200):
        mint = a["mint"] or ""
        rows.append([_hm(a["ts"]), f"<code>{esc(a['simbol'] or '')}</code>",
                     esc(WLABEL.get(a["novcanik"], a["novcanik"] or "")),
                     (f"<a href='https://pump.fun/coin/{esc(mint)}' target=_blank rel='noopener noreferrer'>"
                      f"{esc(_short(mint))} ↗</a>" if mint and a["stanje"] == "lansiran" else esc(_short(mint))),
                     (f"<a href='https://solscan.io/tx/{esc(a['potpis'])}' target=_blank rel='noopener noreferrer'>"
                      f"{esc(_short(a['potpis']))} ↗</a>" if a["potpis"] else ""),
                     (_sol(a["trosak_sol"], 5), a["trosak_sol"] or 0, "n"), (_sol(a["sim_sol"], 5), a["sim_sol"] or 0, "n"),
                     (_sol(a.get("kupnja_sol"), 3) if a.get("kupnja_sol") else "0", a.get("kupnja_sol") or 0, "n"),
                     esc(ATTEMPT_WORDS.get(a["stanje"], a["stanje"] or "")),
                     (f"<span class=neg>{esc(a['greska'])}</span>" if a["greska"] else "")
                     + (f" <span class=pt-warn>{esc(a['upozorenje'])}</span>" if a.get("upozorenje") else "")])
    return rows


def _book_html(con):
    rows, groups = outcomes.book(con)

    def pt(r, k, f):
        x = r["tocke"].get(k, {}).get(f)
        return "–" if x is None else (f"{x:,.0f}" if isinstance(x, float) else str(x))
    trs = [[f"<code>{esc(r['simbol'])}</code>", esc(r["skupina"] or ""), esc(store.cet(r["ts"], "%d.%m. %H:%M")),
            _sol(float(r.get("kupnja_sol") or 0), 3), "da" if r.get("ima_poveznice") else "ne",
            esc(outcomes.buyers_text(r)),
            pt(r, "1h", "promet_usd"), pt(r, "12h", "promet_usd"), pt(r, "24h", "promet_usd"), pt(r, "7d", "promet_usd"),
            pt(r, "24h", "txns"), "–" if r["max_mcap_usd"] is None else f"{r['max_mcap_usd']:,.0f}",
            "–" if r["bondan"] is None else ("da" if r["bondan"] else "ne"),
            _sol(r.get("trosak_sol"), 5), _sol(r["naknada_sol"], 5), _net(r["neto_sol"], 5),
            _sol(r["u_tokenima_sol"], 3)] for r in rows]
    gs = [[esc(k), str(g["n"]), str(g["s_ishodom"]), str(g["bondano"]), _sol(g["trosak_sol"], 5),
           _sol(g["naknada_sol"], 5), _net(g["neto_sol"], 5), _sol(g["u_tokenima_sol"], 3)]
          for k, g in sorted(groups.items())]
    return (f"<details class=card><summary><span class=pt-t>Knjiga ishoda</span><span class=mut>+1 h, +12 h, +24 h, "
            f"+7 d · CSV</span></summary><div class=in><p class=pt-note>{esc(outcomes.RATE_NOTE)}.</p>"
            + table(["Simbol", "Skupina", "Sat (CET)", ("Vlastita kupnja SOL", "n"), "Ima poveznice",
                     ("Kupaca u 10 min", "n"), ("Promet 1 h", "n"), ("12 h", "n"), ("24 h", "n"), ("7 d (dan)", "n"),
                     ("Tx 24 h", "n"), ("Najviši mcap", "n"), "Bondan", ("Trošak SOL", "n"),
                     ("Naknada bez vlastite kupnje SOL", "n"), ("Neto SOL", "n"), ("U tokenima SOL", "n")], trs,
                    tid="ptbook", empty="Još nema lansiranih tokena.")
            + "<p class=pt-note>Naknada bez vlastite kupnje = procjena − 0,30 % × vlastita kupnja. Neto ne uključuje "
              "kupnju: ona je vezan kapital u tokenima (stupac „U tokenima”), ne gubitak. Kupaca u 10 min: različiti "
              "novčanici bez kreatora (RPC); „≥ N” = dosegnut strop poziva; „kupnji” = DexScreener broji kupnje, ne "
              "kupce.</p>"
            + "<h3>Zbroj po skupini</h3>"
            + table(["Skupina", ("Tokena", "n"), ("S ishodom", "n"), ("Bondano", "n"), ("Trošak SOL", "n"),
                     ("Naknada bez vl. kupnje SOL", "n"), ("Neto SOL", "n"), ("U tokenima SOL", "n")], gs, tid="ptgrp",
                    empty="Nema skupina s lansiranjem.")
            + "<p><a class=pt-btn2 href=/pump-tokeni/csv download>⬇ CSV</a></p></div></details>")


JS = """<script>
function ptCopy(e,b){e.preventDefault();e.stopPropagation();var a=b.dataset.a;
(navigator.clipboard?navigator.clipboard.writeText(a):Promise.reject()).then(function(){var t=b.textContent;b.textContent='✓ Kopirano';
setTimeout(function(){b.textContent=t},1500)},function(){prompt('Kopiraj:',a)});return false}
function ptWallet(f){var r=f.querySelector('input[name=izbor]:checked');if(!r)return false;
if(r.value==='trgovacki'){if(!f.potvrda.checked){alert('Za trgovački novčanik označi kvačicu potvrde.');return false}
return confirm('Trgovački novčanik plaća lansiranja pokusa.\\nTrošak se miješa s rezultatom pravog novca, a novčanik ostaje javno označen kao kreator.\\nPotvrđuješ?')}return true}
function ptLaunch(f,ev){var b=ev&&ev.submitter;if(b&&b.getAttribute('formaction'))return true;
var sel=[];document.querySelectorAll('input[name=id][form=ptl]').forEach(function(x){if(x.checked)sel.push(x.value)});
if(!sel.length){alert('Odaberi barem jedan nacrt (kvačica na kartici).');return false}var c=PT,n=sel.length,kb=0;
var ds=sel.map(function(i){return c.d[i]||{s:'#'+i,t:0,tc:'?',k:0,l:false}}).sort(function(a,b){return a.t-b.t});
var lines=ds.map(function(d){kb+=d.k;return '• '+d.s+'  '+d.tc+' CET · '+(d.k?'kupnja '+d.k+' SOL':'bez kupnje')+' · poveznice '+(d.l?'da':'ne')}).join('\n');
var lo=n*c.lo+kb*(1+c.fee),hi=n*c.hi+kb*c.capm;
var t='ODOBRI RASPORED\nNovčanik: '+c.w+'\n'+lines+'\nRazmak najmanje '+c.gap+' min (bliži termin se pomiče), najviše '+c.day+' dnevno\nUkupni trošak: oko '+lo.toFixed(4)+'–'+hi.toFixed(4)+' SOL (lansiranje '+c.lo+'–'+c.hi+' po tokenu, izmjereno; vlastite kupnje '+kb.toFixed(3)+' SOL + naknada); strop simulacije '+c.max+' SOL + kupnja × '+c.capm+'\nKupljeni tokeni ostaju u novčaniku; alat ih ne prodaje. Ako bi kupnja ostavila manje od '+c.rez+' SOL, lansira se bez nje.\nTermin koji prođe više od 15 min se ne nadoknađuje. Ako prvo lansiranje ne uspije ili trošak prijeđe strop, red staje sam.';
if(!confirm(t))return false;f.potvrda.value='1';return true}
function ptRefund(f){var a=(f.adresa.value||'').trim();if(!a){alert('Upiši adresu.');return false}
if(!confirm('Vrati ostatak s novčanika pokusa\\nNa adresu: '+a+'\\nIznos: oko '+(parseFloat(f.saldo.value)-0.000005).toFixed(6)+' SOL (sav saldo minus mrežna naknada; točan iznos se čita pri slanju)\\nPrije slanja ide simulacija.'))return false;f.potvrda.value='1';return true}
function ptClaim(f){var v=parseFloat(f.iznos.value||'0');
if(!confirm('PODIGNI NAKNADU KREATORA\\nNovčanik: '+PT.w+'\\nU trezoru: '+(v>0?'oko '+v.toFixed(6)+' SOL':'nepoznato (samo procjena)')+'\\nMrežna naknada najviše '+PT.cfee+' SOL; prije slanja simulacija (mora pokazati dobitak).'))return false;f.potvrda.value='1';return true}
function ptImg(i){var f=i.files&&i.files[0];if(!f)return;if(f.size>3000000){alert('Slika je veća od 3 MB.');return}
var r=new FileReader();r.onload=function(){var fm=i.form;fm.data.value=r.result;fm.submit()};r.readAsDataURL(f)}
(function(){var d=document.getElementById('ptdash');if(!d)return;var ms=Math.max(300,parseInt(d.dataset.every||'600',10))*1000;
setInterval(function(){fetch('/pump-tokeni/ploca',{credentials:'same-origin'}).then(function(r){return r.ok?r.text():null})
.then(function(h){var e=document.getElementById('ptdash');if(h&&e&&h.indexOf('id=ptdash')>=0)e.outerHTML=h}).catch(function(){})},ms)})();
</script>"""


def _bond_html():
    """27.11. (vlasnik): procjena bondanja tuđih lansiranja (ui/bondmodel.py); greška nikad ne ruši stranicu."""
    try:
        from ui import bondmodel
        return bondmodel.section_html()
    except Exception as e:  # noqa: BLE001
        print(f"procjena bondanja: odjeljak nije uspio ({type(e).__name__})", flush=True)
        return ""


def page(qs, user, auto=None):
    con = _con()
    try:
        auto = (os.environ.get("PUMP_TOKENI_AUTO_PROVJERA", "1") != "0") if auto is None else auto
        if auto and provjera.due(con):
            try:
                provjera.run(con)
            except Exception as e:  # noqa: BLE001 - the page always opens
                print(f"pump tokeni provjera: nije uspjela ({type(e).__name__})", flush=True)
        c = launch.cfg()
        now = int(time.time())
        ws = wallet_state(con, c, now=now)
        gate = pilot_gate(con, ws, c, now)
        any_launched = bool(outcomes.launched(con))
        from pumptokeni import naknada
        dflt = store.link_defaults(con)
        pt = {"w": WLABEL[ws["ch"]] + (f" {_short(ws['addr'])}" if ws["addr"] else ""), "lo": launch.EXPECTED[0],
              "hi": launch.EXPECTED[1], "max": c["max_sol"], "gap": int(c["razmak_s"] // 60), "day": c["dnevno"],
              "cfee": naknada.CLAIM_MAX_FEE_SOL,
              "names": {str(d["id"]): f"{d['simbol']} {d['ime']}" for d in store.drafts(con)},
              "fee": launch.BUY_FEE, "capm": launch.BUY_CAP_MULT, "rez": c["rezerva_sol"],
              "d": {str(d["id"]): {"s": d["simbol"] or "", "t": _termin_of(d, now),
                                   "tc": store.cet(_termin_of(d, now)), "k": float(d.get("kupnja_sol") or 0),
                                   "l": bool(store.link_urls(con, d, dflt))} for d in store.drafts(con)}}
        b = ["<meta name=robots content='noindex,nofollow'>", CSS, "<div class=pt>",
             "<h1>🧪 Pump Fun tokeni</h1>",
             "<p class=pt-sub>Samo za tebe. Vlastita kupnja samo u transakciji lansiranja (do "
             f"{store.HARD_MAX_KUPNJA:g} SOL); {BUY_NOTE}. Ništa se ne objavljuje automatski.</p>",
             _msg(qs),
             dash_html(con, now) if any_launched else _steps_html(con, ws, gate, now),
             _wallet_html(con, c, ws, steps=not any_launched),
             _preflight_html(con, now),
             "<h2 id=ptnacrti>Nacrti</h2>",
             "<form id=ptl method=post action=/pump-tokeni/lansiraj onsubmit=\"return ptLaunch(this,event)\">"
             "<input type=hidden name=potvrda value=''></form>",
             _drafts_html(con),
             _pilot_html(gate),
             _more_html(con, c, now),
             "<h2>Zapisi</h2>",
             "<details class=card><summary><span class=pt-t>Pokušaji lansiranja</span><span class=mut>"
             f"{len(store.attempts(con, 500))}</span></summary><div class=in>"
             + table(["Vrijeme", "Simbol", "Novčanik", "Mint", "Potpis", ("Trošak SOL", "n"), ("Simulacija SOL", "n"),
                      ("Kupnja SOL", "n"), "Stanje", "Greška / upozorenje"], _attempt_rows(con), tid="ptpok",
                     empty="Još nijedan pokušaj.")
             + "</div></details>",
             _book_html(con),
             _bond_html(),
             "</div>",
             f"<script>var PT={json.dumps(pt, ensure_ascii=False)};</script>" + JS]
        return "Pump Fun tokeni", "".join(b)
    finally:
        con.close()


def viewers(env=None):
    """26.11. (vlasnik: "dodaj korisnika Panda da može vidjeti pump fun dio"): korisnici koji smiju GLEDATI stranicu
    (PUMP_TOKENI_GLEDATELJI, zarezom odvojeno; zadano Panda). Samo čitanje: nijedan gumb, nijedan POST."""
    raw = (os.environ if env is None else env).get("PUMP_TOKENI_GLEDATELJI", "Panda")
    return {x.strip().lower() for x in raw.split(",") if x.strip()}


def is_viewer(user, env=None):
    return bool(user) and str(user).strip().lower() in viewers(env)


def view_page():
    """Stranica za gledatelja: nadzorna ploča, raspored i knjiga ishoda. Bez obrazaca, novčanika i postavki."""
    con = _con()
    try:
        now = int(time.time())
        rows = []
        for d in sorted(store.drafts(con), key=lambda d: (_termin_of(d, now), d["id"])):
            w, _k = STATE_WORDS.get(d["stanje"], (d["stanje"], ""))
            img = f"<img src='/pump-tokeni/slika/{d['id']}' width=56 height=56 alt='' loading=lazy>" if d["slika"] else ""
            rows.append([img, f"<b>{esc(d['ime'] or '')}</b> <span class=mut>{esc(d['simbol'] or '')}</span>",
                         esc(store.cet(_termin_of(d, now))), f"{float(d.get('kupnja_sol') or 0):g}", esc(w),
                         esc(d["opis"] or "")])
        b = ["<meta name=robots content='noindex,nofollow'>", CSS, "<div class=pt>", "<h1>🧪 Pump Fun tokeni</h1>",
             "<p class=pt-sub>Pregled pokusa, samo za čitanje. Lansiranja odobrava vlasnik.</p>",
             dash_html(con, now) if outcomes.launched(con) else "<div class=card>Još nema lansiranih tokena.</div>",
             "<h2>Raspored</h2>",
             table(["", "Token", "Termin (CET)", ("Kupnja SOL", "n"), "Stanje", "Opis"], rows, tid="ptgl",
                   empty="Nema nacrta."),
             "</div>"]
        return "Pump Fun tokeni", "".join(b)
    finally:
        con.close()


def image_png(did):
    con = _con()
    try:
        d = store.draft(con, did)
        return d["slika"] if d else None
    finally:
        con.close()


def csv_bytes():
    con = _con()
    try:
        return outcomes.csv_text(con).encode("utf-8")
    finally:
        con.close()


# ---------- POST ---------------------------------------------------------------------------------------------------

def _ids(form):
    out = []
    for x in form.get("id_list") or ([form["id"]] if form.get("id") else []):
        try:
            out.append(int(x))
        except (TypeError, ValueError):
            continue
    return out


def post(path, form, user, search=None):
    """Vlasnikov POST; vraća adresu preusmjeravanja (s ?ok= ili ?err=)."""
    from urllib.parse import quote
    from trade import settings
    if not settings.is_owner(user):
        return PATH + "?err=" + quote("samo vlasnik")
    act = path[len(PATH) + 1:] if path.startswith(PATH + "/") else ""
    con = _con()
    try:
        msg = _do(con, act, form, user, search)
        return PATH + "?ok=" + quote(msg)
    except ValueError as e:
        return PATH + "?err=" + quote(str(e))
    finally:
        con.close()


def _do(con, act, form, user, search=None):
    extra = store.get(con, "zabranjene", []) or []
    if act == "nacrt":
        f = {k: form.get(k, "") for k in store.DRAFT_FIELDS}
        if not (f.get("ime") and f.get("simbol")):
            raise ValueError("ime i simbol su obavezni")
        did = store.add_draft(con, f, image.generate(f["ime"].strip(), f["simbol"].strip().upper()))
        return f"nacrt #{did} dodan; provjeri ime prije lansiranja"
    if act == "uredi":
        did = (_ids(form) or [0])[0]
        keys = store.DRAFT_FIELDS + ("kupnja_sol", "termin") + store.LINK_KINDS
        f = {k: form[k] for k in keys if k in form}
        if any(k in form for k in store.LINK_KINDS):
            f["brend_ok"] = form.get("brend_ok") or ""
        was = (store.draft(con, did) or {}).get("stanje")
        d = store.update_draft(con, did, f)
        if not d["slika_vlastita"]:   # 26.11.: sjemenski simbol s datotekom pumptokeni/slike/ zadržava tu sliku
            store.set_image(con, did, store.seed_image(d["ime"] or "", d["simbol"] or ""), False)
        return (f"#{did} spremljen; provjera imena se ponavlja" +
                ("; izašao iz reda: odobri raspored ponovno" if was == "u_redu" else ""))
    if act in ("slika", "generiraj"):
        did = (_ids(form) or [0])[0]
        d = store.draft(con, did)
        if not d or d["stanje"] in ("salje", "lansiran"):
            raise ValueError("slika se mijenja samo na nacrtu koji nije lansiran")
        if act == "generiraj":
            store.set_image(con, did, image.generate(d["ime"] or "", d["simbol"] or ""), False)
            return f"#{did}: nova slika iz generatora"
        data = form.get("data") or ""
        raw = base64.b64decode(data.split(",", 1)[-1] or "", validate=False) if data else b""
        store.set_image(con, did, image.normalize(raw), True)
        return f"#{did}: tvoja slika spremljena (512×512 PNG)"
    if act == "provjeri":
        ids = [d["id"] for d in store.drafts(con)] if form.get("id") == "sve" else _ids(form)
        n_ok = 0
        for did in ids:
            d = store.draft(con, did)
            if not d or d["stanje"] in ("salje", "lansiran"):
                continue
            r = guards.check(d, extra, search=search)
            store.save_check(con, did, r)
            n_ok += 1 if r["ok"] else 0
        return f"provjereno {len(ids)}, prolazi {n_ok}"
    if act == "lansiraj":
        ids = _ids(form)
        n, why = launch.approve_pilot(con, ids, user, str(form.get("potvrda") or "") == "1")
        plan = (store.get(con, "pilot") or {}).get("raspored") or [] if n else []
        txt = ", ".join(f"{x['simbol']} {store.cet(x['termin'], '%H:%M')}" for x in plan)
        print(f"pump tokeni: raspored odobren ({n} nacrta: {txt})" + (f"; {'; '.join(why)}" if why else ""), flush=True)
        return f"raspored odobren: {n} ({txt})" + (f"; napomene: {'; '.join(why)}" if why else "")
    if act == "provjera":
        steps = provjera.run(con, _ids(form) or None, search=search)
        bad = [x for x in steps if x["ok"] is False]
        return "provjera: zeleno" if not bad else f"provjera: ne radi {', '.join(str(x['k']) for x in bad)}"
    if act == "zaustavi":
        launch.stop_queue(con, "vlasnik: Zaustavi red")
        return "red zaustavljen"
    if act == "stvori":
        if str(form.get("potvrda") or "") != "1":
            raise ValueError("stvaranje samo uz potvrdu")
        addr = devwallet.create()
        print(f"pump tokeni: novčanik pokusa stvoren, adresa {addr}", flush=True)
        if store.get(con, "novcanik") is None:
            store.put(con, "novcanik", launch.TOOL)
        return f"novčanik pokusa stvoren: {addr} (pošalji mu malo SOL-a, npr. 0,2)"
    if act == "vrati":
        r = devwallet.refund(form.get("adresa"), user, str(form.get("potvrda") or "") == "1")
        return (f"vraćeno {r['iznos_sol']:.6f} SOL, potpis {r['potpis']}" +
                ("" if r["ok"] else " (potvrda još nije stigla)" if r["ok"] is None else " (palo na lancu)"))
    if act == "makni":
        for did in _ids(form):
            launch.dequeue(con, did)
        return "maknuto iz reda"
    if act == "teme":
        sug = suggest(con)
        if not sug:
            return "kalendar nema novih općih praznika u sljedećih 60 dana: unesi temu ručno"
        for tema, datum in sug:
            store.add_draft(con, {"tema": tema, "datum_teme": datum, "ime": "", "simbol": "", "opis": ""})
        return f"dodano {len(sug)} tema iz kalendara: upiši ime, simbol i opis"
    if act == "novcanik":
        choice = form.get("izbor") or launch.OFF
        launch.set_wallet(con, choice, user, tap=str(form.get("potvrda") or "") == "1")
        return f"novčanik: {launch.CHOICES[choice]}"
    if act == "podigni":
        from pumptokeni import naknada
        r = naknada.claim(con, user, str(form.get("potvrda") or "") == "1")
        return f"naknada: {r['tekst']}, potpis {r['potpis']}"
    if act == "zadane":
        store.set_link_defaults(con, {k: form.get(k, "") for k in store.LINK_KINDS},
                                str(form.get("brend_ok") or "") in ("1", "on"))
        return "zadane poveznice spremljene"
    if act == "zabranjene":
        words = [w.strip() for w in (form.get("rijeci") or "").split(",") if w.strip()][:200]
        store.put(con, "zabranjene", words)
        return f"zabranjenih riječi (tvojih): {len(words)}"
    raise ValueError("nepoznata radnja")
