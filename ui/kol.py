"""The "KOL-ovi" page: influencers on X, their calls with links, what the price and volume did after each call,
group calls, KOL pairs that call together, wallets that sell into calls, and which call features correlate
with a pump. /kol/<handle> lists one KOL's calls. All read-only from kol.db (written by run_kol.py)."""
import json
import os
from urllib.parse import quote

from kol import score as kscore, store
from ui.html import ago, badge, breakdown, esc, filt, num, signed, table, tdesc, tlink, ts, usd, wlink

CONFIG = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "kol", "config.json")


def _cfg():
    with open(CONFIG) as f:
        return json.load(f)


def _rows(con, sql, args=()):
    cur = con.execute(sql, args)
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in cur]


def pct(x):
    return signed(None if x is None else x * 100, "{:+.0f}%")


def lift(x):
    if x is None:
        return ("–", -1, "n")
    c = "pos" if x >= 2 else "neg" if x < 1 else ""
    return (f'<span class="{c}">{x:.1f}×</span>', x, "n")


def share(x):
    return ("–", -1, "n") if x is None else (f"{x * 100:.0f}%", x, "n")


def klink(h):
    return (f'<a href="/kol/{quote(h)}">@{esc(h)}</a> '
            f'<a href="https://x.com/{quote(h)}" target=_blank rel=noopener class=mut style="text-decoration:none">↗</a>')


def post(url):
    return f'<a href="{esc(url)}" target=_blank rel=noopener>post ↗</a>' if url and "/status/" in url else "–"


def kindb(kind, match):
    b = badge("poziv", "good") if kind == "call" else badge("hvalisanje", "warn")
    return b + (" " + badge("ticker") if match == "ticker" else "")


def _syms(con):
    return dict(con.execute("SELECT token, symbol FROM tokens"))


def _flows(con):
    return {(r[0], r[1]): r[2:] for r in con.execute(
        "SELECT tweet_id, token, insiders, insider_sol, post_sell_sol, post_buy_sol, rotation_selling FROM flows")}


def _flowcell(f):
    if not f:
        return ("–", -1, "n")
    ins, ins_sol, sell, buy, rot = f
    kind = "neg" if ins or rot else ""
    txt = f"{ins} ins. · {sell:.1f}/{buy:.1f} SOL" + (f" · {rot} rot.dev" if rot else "")
    return (f'<span class="{kind}">{esc(txt)}</span>', ins, "n")


def _groupsize(con):
    out = {}
    for token, start, end, n in con.execute("SELECT token, start_ts, end_ts, n_authors FROM groups"):
        out.setdefault(token, []).append((start, end, n))
    return out


def _gcell(gs, token, t):
    for start, end, n in gs.get(token, ()):
        if start <= t <= end:
            return (badge(f"{n} autora", "good" if n >= 3 else ""), n, "n")
    return ("–", 0, "n")


def calls_table(con, where="1=1", args=(), limit=300, tid="calls", show_kol=True):
    syms, fl, gs = _syms(con), _flows(con), _groupsize(con)
    rows = _rows(con, f"SELECT * FROM calls WHERE {where} ORDER BY ts DESC LIMIT ?", (*args, limit))
    head = ["Vrijeme"] + (["X račun", ("Pratitelji", "n")] if show_kol else []) + [
        "Token", "Vrsta poziva", "Post", ("Mcap u pozivu", "n"), ("2 h prije", "n"), ("1 h", "n"), ("6 h", "n"),
        ("24 h", "n"), ("Max 24 h", "n"), ("Volumen ×", "n"), ("Grupa", "n"), ("Prodaja u poziv", "n"), ("Tekst", "wrap")]
    out = []
    for c in rows:
        r = [ts(c["ts"])] + ([klink(c["handle"]), num(c["followers"])] if show_kol else []) + [
            tlink(c["token"], syms.get(c["token"]) or c["symbol"]), kindb(c["kind"], c["match"]), post(c["url"]),
            usd(c["mcap0"]), pct(c["pre2h"]), pct(c["r1h"]), pct(c["r6h"]), pct(c["r24h"]), pct(c["max24"]),
            lift(c["vol_lift"]), _gcell(gs, c["token"], c["ts"]), _flowcell(fl.get((c["tweet_id"], c["token"]))),
            (f'<span class=mut>{esc((c["text"] or "")[:160])}</span>', "", "wrap")]
        out.append(r)
    return table(head, out, tid=tid, empty="Još nema poziva. run_kol.py ih kopira iz X pretraga koje bot već plaća.")


def _leaderboard(con, minf, minc):
    rows = _rows(con, "SELECT * FROM kols WHERE score IS NOT NULL AND COALESCE(followers, 0) >= ? ORDER BY score DESC",
                 (minf,))
    last = dict(con.execute("SELECT handle, MAX(ts) FROM calls WHERE kind = 'call' GROUP BY handle"))
    out = []
    for k in rows:
        s = json.loads(k["stats"] or "{}")
        if s.get("measured", 0) < minc:
            continue
        out.append([klink(k["handle"]), num(k["followers"]), (f"<b>{k['score']:.0f}</b>", k["score"], "n"),
                    lift(k["power_rel"]), num(s.get("measured")), share(s.get("hit_rate")), pct(s.get("med_max24")),
                    pct(s.get("med_r1h")), lift(s.get("med_lift")), share(s.get("rug_rate")),
                    share(s.get("prepump_rate")), share(s.get("first_rate")), num(s.get("brags")),
                    ago(last.get(k["handle"]))])
    return table(["X račun", ("Pratitelji", "n"), ("Moć poziva", "n"), ("Moć/pratitelj", "n"), ("Poziva", "n"),
                  ("Pogodak", "n"), ("Medijan max 24 h", "n"), ("Medijan 1 h", "n"), ("Medijan volumen ×", "n"),
                  ("Rugovi", "n"), ("Kasni pozivi", "n"), ("Prvi", "n"), ("Hvalisanja", "n"), "Zadnji poziv"],
                 out, tid="kols", empty="Još nema KOL-ova s izmjerenim pozivom (mjerenje kreće 1 h nakon poziva).")


def _groups(con):
    syms = _syms(con)
    rows = _rows(con, "SELECT * FROM groups ORDER BY start_ts DESC LIMIT 200")
    out = [[ts(g["start_ts"]), tlink(g["token"], syms.get(g["token"])), num(g["n_authors"]), num(g["good_authors"]),
            ((", ".join(klink(h) for h in json.loads(g["handles"]))), "", "wrap"),
            num((g["end_ts"] - g["start_ts"]) / 60, "{:.0f} min"), pct(g["r1h"]), pct(g["max24"]), lift(g["vol_lift"]),
            num(g["insiders"]), badge("DA", "bad") if g["dev_selling"] else badge("ne", "good")] for g in rows]
    return table(["Početak", "Token", ("Autora", "n"), ("Dobrih KOL-ova", "n"), ("KOL-ovi (redom)", "wrap"),
                  ("Trajanje", "n"), ("1 h", "n"), ("Max 24 h", "n"), ("Volumen ×", "n"), ("Insajdera", "n"),
                  "Dev prodaje"], out, tid="groups", empty="Još nema grupnih poziva.")


def _pairs(con):
    syms = _syms(con)
    ps = kscore.pairs(con, 2) or kscore.pairs(con, 1, 20)
    out = [[klink(a), klink(b), num(n), (", ".join(tlink(t, syms.get(t)) for t in toks[:8]), "", "wrap")]
           for a, b, n, toks in ps]
    return table(["KOL A", "KOL B", ("Puta zajedno", "n"), ("Zajednički tokeni", "wrap")], out,
                 empty="Još nema KOL-ova koji su zajedno zvali isti token.")


def _wallets(con):
    syms = _syms(con)
    rows = _rows(con, "SELECT * FROM kol_wallets ORDER BY tokens DESC, sol_out DESC LIMIT 200")
    out = [[wlink(w["wallet"]), badge("rotacijski dev", "bad") if w["label"] == "rotation_dev" else badge("insajder", "warn"),
            num(w["tokens"]), num(w["sol_in"], "{:,.2f}"), num(w["sol_out"], "{:,.2f}"),
            (", ".join(tlink(t, syms.get(t)) for t in json.loads(w["token_list"] or "[]")[:8]), "", "wrap"),
            ago(w["last_seen"])] for w in rows]
    return table(["Wallet", "Oznaka", ("Tokena", "n"), ("Kupio SOL", "n"), ("Prodao u poziv SOL", "n"),
                  ("Tokeni", "wrap"), "Zadnje"], out, tid="kolw",
                 empty="Još nema walleta koji prodaju u pozive (Helius provjera ide za grupne i jake pozive).")


MEANING = {
    "Pratitelji (log)": "veći računi pomiču cijenu više?",
    "Autora u grupi": "više KOL-ova u 30 min = jači skok?",
    "Prvi autor na tokenu": "prvi koji zove vrijedi više od ponavljanja?",
    "Rast 2 h prije poziva": "pozivi nakon već velikog skoka (kasni ili plaćeni)",
    "Mcap u pozivu (log)": "manji tokeni rastu više nakon poziva?",
    "Lajkovi (log)": "angažman na postu",
    "Pregledi (log)": "koliko je ljudi vidjelo post",
    "Pronađen samo po tickeru": "post bez CA, samo $TICKER (možda drugi token)",
}


def _corr(con):
    rows = []
    for name, rho, n in kscore.correlations(con):
        kind = "" if rho is None or abs(rho) < 0.15 else ("pos" if rho > 0 else "neg")
        cell = ("–", -9, "n") if rho is None else (f'<span class="{kind}">{rho:+.2f}</span>', rho, "n")
        rows.append([esc(name), cell, num(n), (esc(MEANING.get(name, "")), "", "wrap mut")])
    return table(["Značajka poziva", ("Korelacija s max 24 h", "n"), ("Poziva", "n"), ("Pitanje", "wrap")], rows)


def page(qs):
    con = store.ro()
    b = ["<h1>KOL-ovi i njihovi pozivi</h1><p class=mut>Svaki X post koji spominje CA tokena (iz pretraga koje bot ionako "
         "plaća, plus praćenje najboljih KOL-ova), što su cijena i volumen napravili nakon njega, tko je zvao zajedno i "
         "tko je prodavao u poziv. Mjeri <code>run_kol.py</code> svakih 20 min; ništa ne treba ručno.</p>"]
    if con is None:
        return "KOL-ovi", "".join(b) + "<p>Baza kol.db još ne postoji: prvi krug run_kol.py kreće nakon deploya.</p>"
    try:
        cfg = _cfg()
        st = con.execute("""SELECT (SELECT COUNT(*) FROM kols), (SELECT COUNT(*) FROM calls WHERE kind='call'),
            (SELECT COUNT(*) FROM calls WHERE kind='brag'), (SELECT COUNT(*) FROM calls WHERE p0 IS NOT NULL),
            (SELECT COUNT(*) FROM groups), (SELECT COUNT(*) FROM kol_wallets WHERE label='rotation_dev'),
            (SELECT COUNT(*) FROM flows), (SELECT MAX(measured_ts) FROM calls)""").fetchone()
        b.append("<div class=grid>")
        for v, l in [(st[0], "KOL-ova (autora)"), (st[1], "poziva"), (st[2], "hvalisanja (nakon skoka)"),
                     (st[3], "izmjereno cijenom"), (st[4], "grupnih poziva"), (st[5], "rotacijskih devova"),
                     (st[6], "Helius provjera tokova"), (ago(st[7])[0], "zadnje mjerenje")]:
            b.append(f"<div class=stat><div class=v>{esc(v)}</div><div class=l>{l}</div></div>")
        b.append("</div>")

        minf, minc = int(qs.get("minf") or 0), int(qs.get("minc") or 1)
        b.append("<h2 id=ljestvica>Ljestvica KOL-ova</h2>")
        b.append(f'<form class=flt>Min. pratitelja <input name=minf value="{minf}" size=7> Min. poziva '
                 f'<input name=minc value="{minc}" size=3><button>Primijeni</button> {filt("kols", "Traži KOL-a…")}</form>')
        b.append(tdesc(f"Moć poziva 0-100 iz KOL-ovih prvih poziva na token: pogodak (+{cfg['hit_x']:.0%} u 24 h), "
                       "medijan rasta, volumen nakon poziva, je li prvi, rugovi; kasni pozivi (cijena već 2× prije poziva) "
                       f"oduzimaju. S malo poziva ocjena je bliže {cfg['prior_score']} (nesigurno). Dobar KOL za signal: "
                       f"{cfg['good_score']}+. Klik na ime otvara sve njegove pozive.") + _leaderboard(con, minf, minc))

        b.append("<h2 id=grupe>Grupni pozivi</h2>" + tdesc(
            f"Dva ili više različitih autora zovu isti token unutar {cfg['group_secs'] // 60} min. Brojke su od prvog poziva "
            "u grupi. Dva dobra KOL-a bez prodaje devova = signal kol_group u hype ocjeni.") + _groups(con))
        b.append("<h2 id=parovi>KOL-ovi koji zovu zajedno</h2>" + tdesc(
            "Parovi računa koji su više puta zvali isti token u istom prozoru. Isti par na puno tokena često je "
            "ista grupa ili plaćena kampanja.") + _pairs(con))
        b.append(f"<h2 id=pozivi>Zadnji pozivi</h2>{filt('calls', 'Filtriraj pozive…')}" + tdesc(
            "Svaki post s CA tokena. Postoci su promjena cijene od trenutka posta; Volumen × = volumen sat nakon "
            "posta naspram sata prije. Prodaja u poziv: insajderi (kupili sat prije, prodali 30 min poslije) i SOL "
            "prodano/kupljeno u 30 min nakon posta.") + calls_table(con))
        b.append("<h2 id=devovi>Walleti koji prodaju u pozive</h2>" + tdesc(
            f"Kupili sat prije poziva i prodali do {cfg['flow_post_secs'] // 60} min nakon njega. Na "
            f"{cfg['rotation_min_tokens']}+ tokena = rotacijski dev: seli s tokena na token i prodaje u pozive. "
            "Rotacijski devovi ulaze u registar walleta s oznakom insider (nikad na copy listu).") + _wallets(con))
        b.append("<h2 id=korelacije>Što predviđa skok nakon poziva</h2>" + tdesc(
            "Spearman korelacija svake značajke poziva s najvećim rastom u 24 h, preko svih izmjerenih prvih poziva. "
            "+0.3 i više = jasna veza, oko 0 = nema veze, minus = obrnuto. Mijenja se kako se skupljaju podaci.")
                 + _corr(con))
    finally:
        con.close()
    return "KOL-ovi", "".join(b)


def kol_page(handle, qs):
    con = store.ro()
    if con is None:
        return None
    try:
        k = (_rows(con, "SELECT * FROM kols WHERE handle = ?", (handle,)) or [None])[0]
        if not k:
            return "KOL", f"<h1>@{esc(handle)}</h1><p>Nema poziva od ovog računa.</p>"
        s = json.loads(k["stats"] or "{}")
        cfg = _cfg()
        b = [f'<p><a href="/kol">← KOL-ovi</a></p><h1>@{esc(handle)} <span class=mut>{esc(k["name"] or "")}</span></h1>'
             f'<p><a href="https://x.com/{quote(handle)}" target=_blank rel=noopener>Profil na X-u ↗</a></p><div class=grid>']
        for v, l in [(f"{k['score']:.0f}" if k["score"] is not None else "–", "moć poziva"),
                     (f"{k['power_rel']:.2f}×" if k["power_rel"] is not None else "–", "moć po pratitelju"),
                     (f"{k['followers'] or 0:,}", "pratitelja"), (s.get("measured", 0), "izmjerenih poziva"),
                     (f"{s['hit_rate']:.0%}" if "hit_rate" in s else "–", "pogodak"), (s.get("brags", 0), "hvalisanja")]:
            b.append(f"<div class=stat><div class=v>{esc(v)}</div><div class=l>{l}</div></div>")
        b.append("</div>")
        if s.get("parts"):
            w, p = cfg["weights"], s["parts"]
            expl = {"hit": f"{s['hit_rate']:.0%} poziva s barem +{cfg['hit_x']:.0%} u 24 h",
                    "max24": f"medijan najvećeg rasta u 24 h {s['med_max24']:+.0%} (+200% = puni bodovi)",
                    "r1h": f"medijan nakon 1 h {(s.get('med_r1h') or 0):+.0%} (+50% = puni)",
                    "vol_lift": f"medijan volumena sat poslije / sat prije {(s.get('med_lift') or 0):.1f}× (8× = puni)",
                    "first": f"{s['first_rate']:.0%} poziva u kojima je prvi autor",
                    "no_rug": f"{s['rug_rate']:.0%} poziva palo 90%+",
                    "prepump": f"{s['prepump_rate']:.0%} poziva nakon što je cijena već udvostručena u 2 h"}
            names = {"hit": "Pogodak", "max24": "Rast 24 h", "r1h": "Rast 1 h", "vol_lift": "Volumen", "first": "Prvi",
                     "no_rug": "Bez ruga", "prepump": "Kasni pozivi"}
            b.append("<h2>Kako je dobio ocjenu</h2>" + tdesc(
                f"Izmjereni dio daje {s.get('raw', 0):.1f}; s {s.get('measured', 0)} poziva vjerujemo mu "
                f"{s.get('confidence', 0):.0%}, ostatak je {s.get('prior', cfg['prior_score'])}. Težine su u kol/config.json.")
                     + breakdown([(names[x], p[x], abs(w[x]), expl[x]) for x in w], "Izmjereno"))
        b.append("<h2>Svi pozivi</h2>" + tdesc("Svaki njegov post s CA tokena, najnoviji prvi. Postoci su od trenutka posta.")
                 + calls_table(con, "handle = ?", (handle,), 500, "kcalls", show_kol=False))
    finally:
        con.close()
    return f"@{handle}", "".join(b)


def token_section(mint):
    """'Tko ga je zvao na X-u' block for the token page; '' when kol.db has nothing on it."""
    con = store.ro()
    if con is None:
        return ""
    try:
        if not con.execute("SELECT 1 FROM calls WHERE token = ? LIMIT 1", (mint,)).fetchone():
            return ""
        return ("<h2 id=kol>Tko ga je zvao na X-u</h2>" + tdesc(
            "KOL postovi s ovim CA, najnoviji prvi, i što je cijena napravila nakon svakog. Više na stranici KOL-ovi.")
                + calls_table(con, "token = ?", (mint,), 100, "tcalls"))
    except Exception:
        return ""
    finally:
        con.close()
