"""Copy trading page (/copy-trading), part of Natjecanje: pick an influencer and enter on their next call, or copy a
wallet's buys and sells, on your own competition demo account. The trading itself is league/copy.py (every minute in
the dashboard's auto sell thread); this page shows the stats to choose by, the follows and what they did.
"""
import json
import os
import sqlite3
import time
from urllib.parse import quote

from league import copy, store
from ui.html import ago, badge, esc, num, signed, table, tdesc, tlink, usd, wlink
from ui.kol import klink, pct, share

KOL_ROWS = 60
WALLET_ROWS = 100
_CACHE = {}   # name -> (ts, value): the stats tables change slowly, several viewers share one computation
CACHE_S = 300


def _cached(name, fn):
    hit = _CACHE.get(name)
    if hit and time.time() - hit[0] < CACHE_S:
        return hit[1]
    val = fn()
    _CACHE[name] = (time.time(), val)
    return val


def _ro(path):
    return copy._ro(path)


def _koltest():
    """caller -> {'x': stats of their X/TG calls, 'chain': stats of their wallet buys} from the KOL test book
    ($50 on every fresh call, ladder +20..50%, stop -35%)."""
    try:
        from koltest import store as kstore
        con = kstore.ro()
    except Exception:  # noqa: BLE001
        con = None
    out = {}
    for caller, src, pnl, hits, status in copy._q(con, "SELECT caller, source, pnl_usd, hits, status FROM positions "
                                                       "WHERE status IN ('open', 'done')"):
        k = "chain" if src == "chain" else "x"
        r = out.setdefault(caller, {}).setdefault(k, {"n": 0, "pnl": 0.0, "hit20": 0})
        r["n"] += 1
        r["pnl"] += pnl or 0
        try:
            r["hit20"] += 1 if "0.2" in json.loads(hits or "{}") else 0
        except ValueError:
            pass
    if con is not None:
        con.close()
    return out


def kol_rows():
    """Influencers to follow: measured X/Telegram callers, best call power first, bots out."""
    p = copy._paths()
    con = _ro(p["kol"])
    if con is None:
        return []
    try:
        try:
            bots = {h for (h,) in con.execute("SELECT handle FROM kols WHERE bot = 1")}
        except sqlite3.OperationalError:
            bots = set()
        live = {h for (h,) in copy._q(con, "SELECT handle FROM monitor")}
        week = dict(copy._q(con, "SELECT handle, COUNT(DISTINCT token) FROM calls WHERE kind='call' AND ts >= ? "
                                 "GROUP BY handle", (int(time.time()) - 7 * 86400,)))
        last = dict(copy._q(con, "SELECT handle, MAX(ts) FROM calls WHERE kind='call' GROUP BY handle"))
        rows = copy._q(con, "SELECT handle, followers, score, stats FROM kols WHERE score IS NOT NULL "
                            "ORDER BY score DESC")
    finally:
        con.close()
    kt = _koltest()
    out = []
    for h, fol, sc, st in rows:
        if h in bots or h.startswith("w:"):
            continue
        s = json.loads(st or "{}")
        if s.get("measured", 0) < 3:
            continue
        out.append({"handle": h, "followers": fol, "score": sc, "s": s, "live": h in live, "week": week.get(h, 0),
                    "last": last.get(h), "kt": kt.get(h, {}).get("x")})
    # live-watched first: only their calls arrive fast enough to be copied; then call power
    return sorted(out, key=lambda r: (r["live"], r["score"] or 0), reverse=True)


def wallet_rows():
    """Wallets we see trade within seconds (Helius webhook on the KOL wallets): who they are, what the public lists
    say about their profit, how often they trade, and how their buys did in the KOL test book."""
    p = copy._paths()
    con = _ro(p["kol"])
    if con is None:
        return []
    try:
        hook = json.loads((copy._q(con, "SELECT value FROM kv WHERE key='chain_hook'") or [("{}",)])[0][0] or "{}")
        ids = {r[0]: r for r in copy._q(con, "SELECT wallet, name, twitter, source, pnl, wins, losses, rank FROM kol_ids")}
    finally:
        con.close()
    followed = hook.get("wallets") or []
    watched = set(followed)
    wallets = followed or list(ids)[:WALLET_ROWS]
    act = {}
    hc = _ro(p["hype"])
    if hc is not None and wallets:
        q = ",".join("?" * len(wallets))
        for w, side, n, toks, last in copy._q(hc, f"SELECT wallet, side, COUNT(*), COUNT(DISTINCT mint), MAX(ts) "
                                                  f"FROM chain_trades WHERE ts >= ? AND wallet IN ({q}) "
                                                  f"GROUP BY wallet, side", (int(time.time()) - 7 * 86400, *wallets)):
            a = act.setdefault(w, {"buys": 0, "sells": 0, "tokens": 0, "last": 0})
            a["buys" if side == "buy" else "sells"] += n
            if side == "buy":
                a["tokens"] = toks
            a["last"] = max(a["last"], last or 0)
        hc.close()
    wstats = {}
    try:
        from wallets import store as wstore
        wc = _ro(os.path.abspath(wstore.DB))
        if wc is not None and wallets:
            q = ",".join("?" * len(wallets))
            for w, sc, st in copy._q(wc, f"SELECT wallet, score, stats FROM wallets WHERE wallet IN ({q}) "
                                         f"AND stats IS NOT NULL", wallets):
                wstats[w] = {"score": sc, **json.loads(st or "{}")}
            wc.close()
    except Exception:  # noqa: BLE001 - our own scoring is extra; the list works without it
        pass
    kt = _koltest()
    out = []
    for w in wallets:
        _, name, tw, src, pnl, wins, losses, rank = ids.get(w, (w, None, None, None, None, None, None, None))
        caller = tw or "w:" + (name or w[:6])
        out.append({"wallet": w, "name": name, "twitter": tw, "source": src, "pnl": pnl, "wins": wins,
                    "losses": losses, "rank": rank, "live": w in watched, "act": act.get(w, {}),
                    "ws": wstats.get(w), "kt": kt.get(caller, {}).get("chain")})

    def rank_key(r):
        k = r["kt"]
        mine = (k["pnl"] / k["n"]) if k and k["n"] >= 5 else None
        # a wallet that has not traded this week gives nothing to copy, whatever its profit on the list
        return (r["live"], (r["act"].get("buys") or 0) > 0, mine is not None, mine or 0, r["pnl"] or 0)
    return sorted(out, key=rank_key, reverse=True)


# ---------- page -------------------------------------------------------------------------------------------------

def _panel(kind):
    """Settings used by every 'follow' button of the table below (copied into the form by a few lines of JS)."""
    if kind == "kol":
        opts = [("smart", "Smart sell (prodaje kako raste)"), ("tpsl", "moj TP/SL"), ("manual", "prodajem sam")]
    else:
        opts = [("mirror", "prodaj kad on proda"), ("mirror_smart", "kad on proda + Smart sell"),
                ("tpsl", "moj TP/SL + kad on proda")]
    sel = "".join(f'<option value={v}>{esc(t)}</option>' for v, t in opts)
    return (f'<div class="card flt" id=panel-{kind}><b>Postavke za novo praćenje:</b> '
            f'<label>ulog po ulazu $ <input data-k=size type=number min={copy.CFG["min_size"]} '
            f'max={copy.CFG["max_size"]} step=1 value=25 style="width:70px"></label>'
            f'<label>najviše ulaza na dan <input data-k=per_day type=number min=1 max={copy.CFG["max_per_day"]} '
            f'value={5 if kind == "wallet" else 10} style="width:60px"></label>'
            + ('<label>koliko callova <select data-k=once><option value="">svaki njegov call dok ga pratiš</option>'
               '<option value=1>samo sljedeći call, pa stani</option></select></label>' if kind == "kol" else '')
            + f'<label>izlaz <select data-k=exit>{sel}</select></label>'
            '<input data-k=tp placeholder="TP npr. 100%" size=11><input data-k=sl placeholder="SL npr. -30%" size=11>'
            '</div>')


_JS = """<script>
document.querySelectorAll('form.cpf').forEach(function(f){f.addEventListener('submit',function(){
  var p=document.getElementById('panel-'+f.dataset.panel); if(!p) return;
  p.querySelectorAll('[data-k]').forEach(function(i){var h=f.querySelector('input[name='+i.dataset.k+']');
    if(!h){h=document.createElement('input');h.type='hidden';h.name=i.dataset.k;f.appendChild(h);} h.value=i.value;});
});});
</script>"""


def _btn(kind, target, label, mine, user):
    if not user:
        return '<span class=mut>prijavi se</span>'
    f = mine.get((kind, target))
    if f:
        return (badge("pratiš ✓", "good") + " " +
                f'<form method=post action="/natjecanje/copy/stop" style="display:inline"><input type=hidden name=id '
                f'value={f["id"]}><button>Prestani</button></form>')
    text = "Prati i ulazi na svaki njegov call" if kind == "kol" else "Copy trade-aj ovaj wallet"
    ask = ("Alat će SAM kupovati na tvom demo računu na svaki njegov novi call, i preko noći, dok ne klikneš Prestani. "
           "Uključiti?" if kind == "kol" else
           "Alat će SAM kupovati i prodavati na tvom demo računu kad i ovaj wallet, i preko noći, dok ne klikneš "
           "Prestani. Uključiti?")
    return (f'<form method=post action="/natjecanje/copy/follow" class=cpf data-panel={kind} style="margin:0" '
            f'onsubmit="return confirm(\'{ask}\')">'
            f'<input type=hidden name=kind value={kind}><input type=hidden name=target value="{esc(target)}">'
            f'<input type=hidden name=label value="{esc(label)}"><button>{text}</button></form>')


def _kt_cells(k):
    if not k or not k["n"]:
        return [("–", -1e18, "n"), ("–", -1e18, "n")]
    return [(f'{k["hit20"] / k["n"]:.0%} <span class=mut>od {k["n"]}</span>', k["hit20"] / k["n"], "n"),
            signed(k["pnl"] / k["n"], "{:+.2f} $")]


def _kol_table(rows, mine, user, q):
    if q:
        rows = [r for r in rows if q in r["handle"].lower()]
    out = []
    for r in rows[:KOL_ROWS]:
        s = r["s"]
        speed = badge("⚡ uživo", "good") if r["live"] else badge("sporije", "warn")
        out.append([klink(r["handle"]) + " " + speed, num(r["followers"]), (f"<b>{r['score']:.0f}</b>", r["score"], "n"),
                    num(s.get("measured")), share(s.get("hit_rate")), pct(s.get("med_max24")), share(s.get("rug_rate")),
                    share(s.get("prepump_rate")), num(r["week"]), *_kt_cells(r["kt"]), ago(r["last"]),
                    _btn("kol", r["handle"], "@" + r["handle"] if not r["handle"].startswith("tg:") else r["handle"],
                         mine, user)])
    return table(["Influencer", ("Pratitelji", "n"), ("Moć poziva", "n"), ("Izmjerenih poziva", "n"),
                  ("Pogodak (+50% u 24 h)", "n"), ("Medijan max 24 h", "n"), ("Rugovi", "n"), ("Kasni pozivi", "n"),
                  ("Tokena u 7 dana", "n"), ("KOL test: +20%", "n"), ("KOL test: $ po ulazu", "n"),
                  "Zadnji poziv", ""], out, tid="cpkol",
                 empty="Još nema influencera s dovoljno izmjerenih poziva (barem 3).")


def _wallet_table(rows, mine, user, q):
    if q:
        rows = [r for r in rows if q in (r["name"] or "").lower() or q in (r["twitter"] or "").lower()
                or q in r["wallet"].lower()]
    out = []
    for r in rows[:WALLET_ROWS]:
        a, ws = r["act"], r["ws"] or {}
        who = esc(r["name"] or "") + (f' <a href="https://x.com/{quote(r["twitter"])}" target=_blank rel=noopener '
                                      f'class=mut>@{esc(r["twitter"])}</a>' if r["twitter"] else "")
        speed = badge("⚡ uživo", "good") if r["live"] else badge("ne pratimo uživo", "bad")
        wl = (r["wins"] or 0) + (r["losses"] or 0)
        out.append([wlink(r["wallet"]) + " " + speed + (f"<div>{who}</div>" if who else ""),
                    signed(r["pnl"], "{:+,.0f} $") if r["pnl"] is not None else ("–", -1e18, "n"),
                    share((r["wins"] or 0) / wl if wl else None), num(a.get("buys")), num(a.get("tokens")),
                    num(a.get("sells")), share(ws.get("win_rate")) if ws.get("closed") else ("–", -1, "n"),
                    num(ws.get("median_hold_min"), "{:,.0f} min") if ws else ("–", -1, "n"),
                    *_kt_cells(r["kt"]), ago(a.get("last")),
                    _btn("wallet", r["wallet"], r["name"] or r["twitter"] or r["wallet"][:6], mine, user)])
    return table(["Wallet", ("Profit po javnoj listi", "n"), ("Uspješnost po listi", "n"), ("Kupnji u 7 dana", "n"),
                  ("Različitih tokena", "n"), ("Prodaja u 7 dana", "n"), ("Uspješnost po našem izračunu", "n"),
                  ("Tipično drži", "n"), ("KOL test: +20%", "n"), ("KOL test: $ po ulazu", "n"), "Zadnja aktivnost",
                  ""], out, tid="cpwal",
                 empty="Još nema walleta koje pratimo uživo (lista KOL walleta se puni sama nakon pokretanja bota).")


def _follows_table(con, fl, user):
    res = copy.follow_results(con)
    rows = []
    for f in fl:
        r = res.get(f["id"], {"n": 0, "open": 0, "closed": 0, "wins": 0, "pnl": 0.0})
        who = klink(f["target"]) if f["kind"] == "kol" else wlink(f["target"]) + f" {esc(f['label'] or '')}"
        stop = (f'<form method=post action="/natjecanje/copy/stop" style="margin:0"><input type=hidden name=id '
                f'value={f["id"]}><button>Prestani</button></form>') if f["user"] == user else ""
        rows.append([esc(f["user"]), badge("influencer" if f["kind"] == "kol" else "wallet"), who,
                     usd(f["size_usd"]), num(f["per_day"]), esc(copy.describe_exit(f["exit"])), ago(f["created"]),
                     num(r["n"]), num(r["open"]),
                     share(r["wins"] / r["closed"] if r["closed"] else None), signed(r["pnl"] if r["closed"] else None),
                     stop])
    return table(["Igrač", "Što", "Koga", ("Ulog", "n"), ("Max/dan", "n"), "Izlaz", "Od", ("Ulaza", "n"),
                  ("Otvoreno", "n"), ("Uspješnost", "n"), ("Zarada zatvorenih $", "n"), ""], rows, tid="cpmy",
                 empty="Još nitko nikoga ne prati.")


def _log_table(rows):
    kinds = {"ulaz": "good", "izlaz": "good", "preskočeno": "warn", "info": ""}
    out = [[ago(r["ts"]), esc(r["user"]), esc(r["label"] or ""), tlink(r["token"], r["symbol"]),
            badge(r["action"], kinds.get(r["action"], "")), (esc(r["note"] or ""), "", "wrap")] for r in rows]
    return table(["Kada", "Igrač", "Koga prati", "Token", "Što", ("Zašto", "wrap")], out, tid="cplog",
                 empty="Još se ništa nije dogodilo. Ulazi se pojave čim praćeni objavi poziv ili kupi token.")


def page(qs, user):
    con = store.connect()
    try:
        copy.ensure(con)
        q = (qs.get("q") or "").strip().lower()
        everyone = copy.follows(con)
        mine = {(f["kind"], f["target"]): f for f in everyone if f["user"] == user}
        ordered = [f for f in everyone if f["user"] == user] + [f for f in everyone if f["user"] != user]
        msg = ""
        if qs.get("err"):
            msg = f'<div class=card style="border-color:var(--bad)"><b class=neg>Nije prošlo:</b> {esc(qs["err"])}</div>'
        elif qs.get("ok"):
            msg = f'<div class=card style="border-color:var(--good)">{esc(qs["ok"])}</div>'
        b = ['<h1>Copy trading</h1><p class=lead>Odaberi influencera ili wallet i alat trguje umjesto tebe na tvom '
             '<a href=/natjecanje>demo računu u Natjecanju</a> (bez pravog novca). <b>Influencer:</b> čim objavi novi '
             'token, kupuješ ga i ti. <b>Wallet:</b> kad on kupi, kupiš i ti; kad on proda, prodaš i ti. '
             'Provjera ide svake minute, i preko noći.</p>', msg]
        if not user:
            b.append('<div class=card>Gledaš bez prijave pa ne možeš nikoga pratiti. '
                     '<a href="/prijava?next=/copy-trading"><button>Prijavi se svojim imenom</button></a></div>')
        b.append('<div class=ctl style="margin:8px 0"><a class=chip href="#pratim">👀 Koga pratiš</a>'
                 '<a class=chip href="#influenceri">📣 Influenceri</a><a class=chip href="#walleti">👛 Walleti</a>'
                 '<a class=chip href="#dogadjaji">📜 Što se dogodilo</a><a class=chip href="/natjecanje">🏆 Natjecanje</a></div>')
        b.append('<h2 id=pratim>Koga se prati</h2>' + tdesc(
            "Tvoja praćenja su gore, ostalih igrača ispod. Ulazi iz praćenja su obični tradeovi na računu: vide se u "
            "Natjecanju i možeš ih i sam prodati.") + _follows_table(con, ordered, user))
        b.append('<form method=get class=flt style="margin-top:12px"><input name=q placeholder="traži influencera ili wallet" '
                 f'size=30 value="{esc(qs.get("q", ""))}"><button>Traži</button> <a href=/copy-trading>očisti</a></form>')

        b.append('<h2 id=influenceri>Influenceri: uđi na njihov sljedeći call</h2>' + tdesc(
            "Influenceri s barem 3 izmjerena poziva; prvo oni koje pratimo uživo, pa najjači (bot računi koji samo objavljuju svaki novi token su "
            "izbačeni). <b>Pogodak</b> = token je narastao +50% u 24 h nakon poziva. <b>Kasni pozivi</b> = token je već "
            "skočio prije poziva. <b>KOL test</b> = kako je prošao naš probni ulaz od $50 na svaki svjež poziv tog "
            "influencera. <b>⚡ uživo</b> znači da njegove objave vidimo u sekundama; ostale vidimo tek pri skeniranju, "
            "često prekasno, a poziv stariji od 10 minuta se ne kopira. Kad ga pratiš, alat ulazi na <b>svaki</b> njegov novi "
            "call (najviše koliko upišeš na dan) dok ne klikneš Prestani; ako želiš samo jedan ulaz, odaberi "
            "„samo sljedeći call”."))
        if user:
            b.append(_panel("kol"))
        b.append(_kol_table(_cached("kol", kol_rows), mine, user, q))

        b.append('<h2 id=walleti>Walleti: copy trade</h2>' + tdesc(
            "Walleti poznatih tradera koje pratimo uživo (svaka njihova kupnja i prodaja stigne u par sekundi). "
            "Prvo oni koji su trgovali ovaj tjedan, a među njima najuspješniji: prvo po tome kako su njihove kupnje prošle u našem KOL testu (kad ih ima barem 5), "
            "zatim po profitu s javne liste. Neki kupuju desetke tokena dnevno, zato postavi limit ulaza na dan. "
            "Kad wallet proda token, prodaje se cijela tvoja pozicija u njemu."))
        if user:
            b.append(_panel("wallet"))
        b.append(_wallet_table(_cached("wallet", wallet_rows), mine, user, q))

        b.append('<h2 id=dogadjaji>Što se dogodilo</h2>' + tdesc(
            "Svaki ulaz, izlaz i preskočeni poziv s razlogom (premala likvidnost, lažni pool, prekasno, nema novca na "
            "računu…). Zadnjih 100.") + _log_table(copy.log(con, limit=100)))
        b.append('<h3>Pravila</h3><ul class=mut>'
                 f'<li>Ulazi se samo dok je poziv ili kupnja svježa (do {copy.CFG["max_delay_min"]} min).</li>'
                 f'<li>Ne ulazi se u tokene s likvidnošću ispod ${copy.CFG["min_liq"]:,.0f}, u lažne poolove '
                 '(likvidnost veća od market capa), u rugane tokene ni u tokene veće od $50M.</li>'
                 '<li>Ulazi se po živoj cijeni s DexScreenera, uz 1% naknade i klizanje cijene, isto kao ručna kupnja.</li>'
                 '<li>Ako na računu nema dovoljno slobodnog novca, ulaz se preskače.</li></ul>')
        b.append(_JS)
        return "Copy trading", "".join(b)
    finally:
        con.close()


def post(path, form, user):
    from urllib.parse import quote as qq
    back = "/copy-trading"
    if not user:
        return f"{back}?err={qq('prijavi se svojim imenom')}"
    con = store.connect()
    try:
        if path == "/natjecanje/copy/follow":
            kind = form.get("kind", "")
            copy.follow(con, user, kind, form.get("target", ""), form.get("label", ""), form.get("size") or 25,
                        form.get("per_day") or (5 if kind == "wallet" else 10), form.get("exit", ""),
                        form.get("tp", ""), form.get("sl", ""), once=bool(form.get("once")))
            who = form.get("label") or form.get("target", "")[:8]
            msg = (f"Pratiš {who}: ulaziš samo na njegov sljedeći call, pa praćenje staje" if form.get("once") and
                   kind == "kol" else f"Pratiš {who}: ulaziš na svaki njegov novi call dok ne klikneš Prestani"
                   if kind == "kol" else
                   f"Kopiraš wallet {who}: kupuješ i prodaješ kad i on")
            _CACHE.clear()
            return f"{back}?ok={qq(msg)}#pratim"
        if path == "/natjecanje/copy/stop":
            copy.unfollow(con, user, int(form.get("id") or 0))
            if form.get("back") == "natjecanje":
                return f"/natjecanje?ok={qq('Copy trading zaustavljen. Otvorene pozicije ostaju, prodaj ih kad želiš.')}#pozicije"
            return f"{back}?ok={qq('Praćenje zaustavljeno. Otvorene pozicije ostaju, prodaj ih kad želiš.')}#pratim"
        return back
    except (ValueError, sqlite3.OperationalError) as e:
        return f"{back}?err={qq(str(e))}"
    finally:
        con.close()
