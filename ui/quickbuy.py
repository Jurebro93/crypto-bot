"""Quick buying in Natjecanje: suggested tokens (Fartcoin/Useless style strong tokens from Dugoročni plus the best
new candidates right now) as cards with one-click buy, and the buy box + copy-address button on every token page.

Nicholas 1.11.: "u natjecanju trebaju biti predloženi tokeni kao useless, fartcoin i slični, a na njihovoj stranici
kopiraj kripto adresu ili pošalji u natjecanje kao moju kupovinu; sve uvezano da je kupnja što brža".
Buys go through the normal /natjecanje/buy form (league.post), so all checks (rug lock, liquidity, cash) stay in one place.
"""
import json
import re

from ui.html import esc, usd

MINT = re.compile(r"[1-9A-HJ-NP-Za-km-z]{32,44}")
N_STRONG = 8          # long-term cards
N_NEW = 3             # new-candidate cards
KIND = {"uzor": ("⭐ Uzor", "good"), "jaki": ("💪 Jaki token", "good"), "dugorocni": ("🌱 Dugoročni", "good"),
        "novi": ("🚀 Novi kandidat", "warn")}
STAKES = (25, 50, 100)


def copy_btn(mint, label="📋 Kopiraj adresu", small=False, big=False):
    """Copies the token address; falls back to a prompt where the clipboard is blocked (old phones, http)."""
    if not mint or not MINT.fullmatch(mint):
        return ""
    style = (' style="font-size:12px;padding:2px 8px"' if small else
             ' style="font-size:17px;padding:12px 18px;border-radius:10px;font-weight:700;width:100%;max-width:420px"'
             if big else "")
    js = ("var m=this.dataset.m,b=this;(navigator.clipboard?navigator.clipboard.writeText(m):Promise.reject())"
          ".then(function(){b.textContent='✅ Kopirano'},function(){prompt('Kopiraj adresu:',m)});return false")
    return (f'<button type=button class=qb-copy data-m="{esc(mint)}" title="Kopiraj adresu tokena {esc(mint)}"'
            f'{style} onclick="{js}">{label}</button>')


def strong(n=N_STRONG):
    """The top strong / long-term survivors from dugo.db's latest snapshot, best first.
    [] when the Dugoročni module has not run yet."""
    try:
        from dugo import run, store
        cfg = run.config()
        con = store.ro()
    except Exception:
        return []
    if con is None:
        return []
    out, seen = [], set()
    try:
        day = con.execute("SELECT MAX(day) FROM snap").fetchone()[0]
        if not day:
            return []

        def add(mint, sym, kind, why, mcap, f):
            if mint in seen or len(out) >= n:
                return
            seen.add(mint)
            out.append({"mint": mint, "symbol": sym, "kind": kind, "why": why or "", "mcap": mcap,
                        "ret30": f.get("povrat_30d"), "age": f.get("starost_d")})

        # Fartcoin and Useless are the reference profile the long-term list is measured against, not buy picks
        # (Nicholas 2.11.: they topped the list while down 33-43% in 30 days). They stay on Dugoročni → Uzori.
        rows = con.execute("""SELECT s.mint, t.symbol, s.kind, s.mcap, s.features, s.why FROM snap s JOIN tokens t
            ON t.mint=s.mint WHERE s.day=? AND s.kind IN ('jaki','dugorocni') AND t.status IS NOT 'mrtav'
            ORDER BY CASE s.kind WHEN 'jaki' THEN 0 ELSE 1 END, s.rank LIMIT 40""", (day,)).fetchall()
        # alternate strong / long-term so both lists show up
        jaki = [r for r in rows if r["kind"] == "jaki"]
        dug = [r for r in rows if r["kind"] == "dugorocni"]
        for pair in zip(jaki + [None] * len(dug), dug + [None] * len(jaki)):
            for r in pair:
                if r is not None:
                    add(r["mint"], r["symbol"], r["kind"], r["why"], r["mcap"], json.loads(r["features"] or "{}"))
    except Exception:
        return out
    finally:
        con.close()
    return out


def fresh(cands, live, n=N_NEW):
    """The best new candidates from Natjecanje's suggestion list that still have a price and did not dump."""
    out = []
    for r in cands:
        if r.get("collapse") or r["token"] not in live:
            continue
        out.append({"mint": r["token"], "symbol": r["symbol"], "kind": "novi",
                    "why": f"confidence {r['conf']}" + (f", klasa {r['klasa']}" if r.get("klasa") else ""),
                    "mcap": r.get("mcap"), "ret30": None, "age": None})
        if len(out) >= n:
            break
    return out


def _buy_form(mint, symbol, source, size=50, button="🛒 Kupi", back=""):
    stakes = "".join(f'<option value={s}{" selected" if s == size else ""}>${s}</option>' for s in STAKES)
    return ('<form method=post action="/natjecanje/buy" style="display:flex;gap:4px;margin:0;flex-wrap:wrap">'
            f'<input type=hidden name=token value="{esc(mint)}"><input type=hidden name=symbol value="{esc(symbol or "")}">'
            f'<input type=hidden name=source value="{esc(source)}">'
            + (f'<input type=hidden name=back value="{esc(back)}">' if back else "")
            + f'<select name=size title="ulog u $">{stakes}</select><button>{button}</button></form>')


def _card(t, live, user, compact=False):
    label, cls = KIND[t["kind"]]
    price, liq, _, mcap = live.get(t["mint"], (None, None, None, None))
    mcap = mcap or t["mcap"]
    ret = t.get("ret30")
    ret_html = (f' · 30 dana <b class={"pos" if ret > 0 else "neg"}>{100 * ret:+.0f}%</b>' if ret is not None else "")
    sym = t["symbol"] or t["mint"][:6]
    if not user:
        act = '<a href=/prijava?next=/natjecanje><button>Prijavi se za kupnju</button></a>'
    elif not price:
        act = '<span class=mut>trenutno nema cijene</span>'
    else:
        act = _buy_form(t["mint"], t["symbol"], f"predloženo: {label[2:].strip().lower()}")
    w = "min-width:170px;max-width:190px;padding:10px" if compact else "min-width:210px;max-width:250px"
    return (f'<div class=card style="{w};flex:0 0 auto;margin:0;display:flex;'
            f'flex-direction:column;gap:6px"><div><span class="b {cls}">{esc(label)}</span></div>'
            f'<div style="font-size:17px"><a href="/token/{esc(t["mint"])}"><b>{esc(sym)}</b></a></div>'
            f'<div class=mut style="font-size:12px">vrijednost {usd(mcap)[0]}'
            f'{ret_html}</div><div class=mut style="font-size:12px;flex:1">{esc(t["why"][:60 if compact else 110])}</div>'
            f'{act}<div style="display:flex;gap:6px;flex-wrap:wrap">{copy_btn(t["mint"], small=True)}'
            + (f'<a href="/natjecanje?dca={esc(t["mint"])}#dca" style="font-size:12px;align-self:center" '
               'title="kupuj isti iznos u pravilnim razmacima">🔄 DCA</a>' if user else "")
            + f'<a href="/token/{esc(t["mint"])}" style="font-size:12px;align-self:center">detalji →</a></div></div>')


def block(tokens, live, user, compact=False):
    """The "Predloženi tokeni" strip on Natjecanje. compact (Nicholas 1.11. 20:46: it took too much room near the top):
    one short line and narrower cards in a single sideways-scrolling row."""
    if not tokens:
        return ""
    if compact:
        cards = "".join(_card(t, live, user, compact=True) for t in tokens)
        return ('<h2 id=predlozeni>⭐ Predloženi tokeni</h2><p class=mut style="font-size:13px;margin:2px 0 6px">'
                'Jaki i dugoročni tokeni su sigurniji, novi kandidati rizičniji. Povuci vodoravno za više.'
                + ("" if user else " Za kupnju se prijavi.") + '</p>'
                f'<div style="display:flex;gap:8px;overflow-x:auto;padding-bottom:6px;max-width:100%">{cards}</div>')
    intro = ("Sigurniji izbor su jaki i dugoročni tokeni (kao Fartcoin i Useless: preživjeli su tjednima, imaju stalan "
             "volumen i oporavljaju se od padova). Novi kandidati su rizičniji, ali mogu narasti brže. Odaberi ulog i "
             "klikni Kupi, trade ide na tvoj račun u natjecanju po živoj cijeni.")
    if not user:
        intro += " Za kupnju se prijavi svojim imenom."
    cards = "".join(_card(t, live, user) for t in tokens)
    return (f'<h2 id=predlozeni>⭐ Predloženi tokeni</h2><p class=mut>{intro}</p>'
            f'<div style="display:flex;gap:10px;overflow-x:auto;padding-bottom:6px">{cards}</div>')


def token_box(mint, symbol, locked=None):
    """Buy box on the token page. The page is the same for everyone (cached), so it does not know who is logged in;
    a guest who clicks gets the normal "prijavi se" message on Natjecanje."""
    if not MINT.fullmatch(mint or ""):
        return ""
    sym = symbol or mint[:6]
    head = ('<div class=card style="border:1px solid #c7d2fe;background:linear-gradient(135deg,rgba(79,70,229,.06),rgba(15,181,160,.06)),#fff;display:flex;gap:12px;align-items:center;'
            'flex-wrap:wrap;margin:10px 0"><div style="font-size:26px">🏆</div><div style="flex:1;min-width:220px">'
            f'<b>Kupi {esc(sym)} u natjecanju</b><br><span class=mut style="font-size:13px">')
    if locked:
        return (head + f'Kupnja je zaključana: {esc(locked)}.</span></div>{copy_btn(mint)}</div>')
    return (head + 'Trade ide na tvoj demo račun u natjecanju po živoj cijeni (1% naknade). Moraš biti prijavljen '
            'svojim imenom. Adresu možeš i kopirati pa je zalijepiti u svoj wallet.</span></div>'
            + _buy_form(mint, symbol, "stranica tokena", button="🛒 Kupi kao moj trade", back=f"/token/{mint}")
            + f'<a href="/natjecanje?dca={esc(mint)}#dca"><button title="kupuj isti iznos u pravilnim razmacima">'
            '🔄 Pokreni DCA</button></a>' + copy_btn(mint) + '</div>')


def dugo_info(mint):
    """(symbol, list label) when the token is on today's Dugoročni lists, else (None, None)."""
    try:
        from dugo import store
        con = store.ro()
    except Exception:
        return None, None
    if con is None:
        return None, None
    try:
        r = con.execute("""SELECT t.symbol, s.kind FROM tokens t LEFT JOIN snap s ON s.mint=t.mint
            AND s.day=(SELECT MAX(day) FROM snap) WHERE t.mint=? ORDER BY s.rank LIMIT 1""", (mint,)).fetchone()
        return (r[0], {"jaki": "Jaki tokeni", "dugorocni": "Dugoročni kandidati",
                       "budjenje": "Bude se"}.get(r[1])) if r else (None, None)
    except Exception:
        return None, None
    finally:
        con.close()


def top_buy(user):
    """Big "paste address and buy" box at the very top of Natjecanje (Nicholas 1.11. 16:09: it was far down and the
    address field ran off the phone screen). Full-width field, one-tap paste, stake chips, big buy button."""
    if not user:
        return ""
    paste = ("var i=document.getElementById('qb-addr');if(navigator.clipboard&&navigator.clipboard.readText)"
             "{navigator.clipboard.readText().then(function(t){i.value=t.trim();i.focus()},function(){i.focus()})}"
             "else{i.focus()}return false")
    chips = "".join(
        f'<label style="flex:1;min-width:56px"><input type=radio name=size value={s}{" checked" if s == 50 else ""} '
        f'style="position:absolute;opacity:0"><span class=qb-stake>${s}</span></label>' for s in (10, 25, 50, 100, 250))
    return ('<style>.qb-top{border:2px solid var(--good,#16a34a);margin:10px 0;padding:14px;box-sizing:border-box;'
            'max-width:100%}.qb-top *{box-sizing:border-box}.qb-row{display:flex;gap:8px;flex-wrap:wrap;width:100%}'
            '.qb-top input[type=text]{flex:1 1 220px;min-width:0;width:100%;font-size:16px;padding:12px;border-radius:10px}'
            '.qb-stake{display:block;text-align:center;padding:10px 0;border:1px solid var(--line);border-radius:10px;'
            'cursor:pointer;font-weight:600}input:checked+.qb-stake{background:var(--good,#16a34a);color:#fff;'
            'border-color:var(--good,#16a34a)}.qb-go{width:100%;font-size:17px;padding:12px;border-radius:10px;'
            'font-weight:700}.qb-paste{padding:12px 14px;border-radius:10px;font-size:15px}</style>'
            '<form id=kupi method=post action="/natjecanje/buy" class="card qb-top">'
            '<div style="font-size:17px;font-weight:700;margin-bottom:8px">🛒 Kupi token odmah</div>'
            '<div class=qb-row><input type=text id=qb-addr name=token required autocomplete=off autocapitalize=none '
            'spellcheck=false placeholder="zalijepi adresu tokena ili DexScreener link">'
            f'<button type=button class=qb-paste onclick="{paste}">📋 Zalijepi</button></div>'
            f'<div class=mut style="font-size:13px;margin:10px 0 6px">Ulog</div><div class=qb-row>{chips}</div>'
            '<div style="margin-top:10px"><button class=qb-go>Kupi na moj račun</button></div>'
            '<div class=mut style="font-size:12px;margin-top:6px">Kupuje po živoj cijeni s DexScreenera (1% naknade). '
            'Ne mora biti s liste prijedloga. Ako token već imaš, iznos se doda u tu poziciju (ulazna cijena postaje prosjek).</div></form>')
