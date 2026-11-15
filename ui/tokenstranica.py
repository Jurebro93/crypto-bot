"""Stranice tokena: javna stranica (EN glavna + HR), dijelovi za top 100 (ui/public.coin_page), privatni blok na
/token/<adresa> u aplikaciji i povratne informacije (tokenstranice/, 15.11.2026.).

Javno (ui/public.route ih sprema CACHE_S, pa tražilice ne koštaju ništa; pregled stranice ne ide na mrežu):
    page(slug, lang)        cijela stranica tokena midcap svemira koji nema stranicu top 100 (isti /coin/<slug>)
    coin_calls(mint, lang)  "tko ga je zvao" za top 100 (čisti pozivi s X-a i Telegrama), "" bez snimke
    coin_extra(r, lang)     statistika, tumačenje, mišljenje AI-ja, holderi, insajderi, povratne za top 100
    urls()                  karta weba: samo stranice s dovoljno podataka (ne top 100, oni su već tamo)
Što je javno: brojke iz snimke (tokenstranice.db, jednom na sat) u kojoj su pozivi, listing signali i signali
pametnog novca stariji od 24 h; holderi samo kao zbrojevi po klasi, burze po imenu, nikad adresa novčanika. Što nije:
svježi pozivi, živi signali, naše zone ulaza i tradeovi (samo poruka "za članove"), ključevi, imena env varijabli,
interni servisi, troškovi, tekst grešaka (pravila ui/apjavno).
Privatno (aplikacija, svježe, bez odgode):
    private_html(mint, qs)  blok na /token/<adresa>: poveznica na javnu stranicu i isti dijelovi bez odgode, naša zona
                            ulaza, naši tradeovi, svježi signali; povratne se učitaju po igraču (fragment)
    fb_fragment(user, mint, err)  komentari + 👍/👎 za jednog igrača (GET /tokenstranica/povratne?m=)
    fb_post(path, form, user)     POST /tokenstranica/poruka | glas | sakrij -> (ok, kod, mint)
"""
import json
import re
import time

from ui.html import esc

AI_LABEL = {"en": "AI opinion, not financial advice", "hr": "Mišljenje AI-ja, nije financijski savjet"}
FB_PATH = "/tokenstranica/povratne"
SITEMAP_FROZEN_D = 30
CSS = """.tpo{border:1px solid var(--line);border-radius:18px;padding:18px 20px;background:#fff;margin:6px 0 10px}
.tpo .tpl{display:inline-block;font-size:12px;font-weight:700;letter-spacing:.02em;text-transform:uppercase;
background:#fff7e6;color:#8a5a00;border:1px solid #f5d08a;border-radius:999px;padding:3px 10px;margin-bottom:8px}
.tpo p{margin:6px 0}.tpo ul{margin:6px 0 0;padding-left:20px;color:var(--mut)}
.tpnote{border:1px solid #f5d08a;background:#fff7e6;border-radius:14px;padding:12px 16px;margin:12px 0}
.tpfb{list-style:none;padding:0;margin:10px 0}.tpfb li{border:1px solid var(--line);border-radius:14px;padding:10px 14px;
margin:8px 0;background:#fff}.tpfb b{font-size:14px}.tpfb span{color:var(--mut);font-size:13px;margin-left:8px}
.tpfb div{margin-top:4px;overflow-wrap:anywhere}.tpv{display:flex;gap:10px;align-items:center;margin:8px 0}
.tpv b{font-size:18px}ul.tpi{padding-left:20px}ul.tpi li{margin:6px 0}"""

L = {
    "en": dict(
        title="{sym} price, chart, holders and who called it | MemeSonar",
        desc="{ns} on Solana: market cap {mc}, typical daily range {rng}, {n} measured influencer calls, holder "
             "classes and listing status. Updated hourly.",
        h1="{name} ({sym})", sub="price, volume, holders and who called it",
        lead="{name} is a Solana meme coin with a market cap of {mc}, {liq} of liquidity and {vol} traded in the last 24 "
             "hours. MemeSonar has tracked it since {since}.",
        back="← Top Solana meme coins", lb="/solana-meme-coins", prof="/coin/", infl="/influencer/", tg="/telegram/",
        frozen={"rug": "We no longer track this token: it was flagged as a rug on {d}. The numbers below are frozen as "
                       "of that day.",
                "mc_low": "We no longer track this token: its market cap fell under $2M on {d}. The numbers below are "
                          "frozen as of that day.",
                "mc_high": "We no longer track this token on this list: its market cap rose above $200M on {d}. The "
                           "numbers below are frozen as of that day.",
                "out": "We no longer track this token (since {d}). The numbers below are frozen as of that day."},
        thin="Too little data so far: {n} days of price history (we need {m}). The page stays out of search results "
             "until there is enough, and the AI opinion is written once there is.",
        cards=("Price", "Market cap", "24h change", "Liquidity", "24h volume", "Category"),
        ch_px="Price", ch_mc="Market cap", ch_vol="Daily volume", ch_liq="Liquidity", ch_hold="Holders",
        ch_d="daily, last {n} days", ch_14="last 14 days",
        stats_h="Statistics", stats=("Typical daily range", "Half of the days between", "30-day range",
                                     "Position in the 30-day range", "Change 7 / 30 / 90 days", "Under the high",
                                     "Days with $50k+ volume (30 / 90 d)", "Average daily volume (30 d)",
                                     "Correlation with Bitcoin (daily / 4 h)", "Beta to Bitcoin (daily)",
                                     "Higher 72 h after a Bitcoin +3 % day", "Bounces from the 30-day bottom",
                                     "Bounces that reached +15 % in 7 days", "Median best / worst 7 days after",
                                     "Age", "Category"),
        days="{n} days", of="{k} of {n}", cat={"A": "A: old, steady volume, follows Bitcoin",
                                               "B": "B: steady volume", "C": "C: young or sporadic volume"},
        b_h="Last bounces from the bottom of the 30-day range", bcols=("Day", "Best in 7 days", "Worst in 7 days"),
        int_h="What the numbers say", int_note="Plain-language reading of the numbers above, by fixed rules. Not "
                                               "advice.", risks_h="Risks",
        op_h="Opinion", op_none="No AI opinion yet: it is written once a day for tokens with enough data.",
        op_date="Written {d} from the numbers on this page by {model}.",
        calls_h="Who called it", calls_note="Influencer and Telegram calls older than 24 hours and what the price did "
        "after them. Clean calls only: measured, not posted after the price had already doubled, not found through "
        "searches for winners, no bot accounts.",
        calls_sum="{n} clean calls by {c} accounts: higher 1 hour later {up}, reached +15 % within 24 h {hit}, median "
                  "24 h result {med}, rugged (−90 %+) {rug}.",
        ccols=("Date", "Caller", "Market cap at call", "1 h", "24 h", "24h peak", "Post"), post="post",
        no_calls="No clean influencer call of this token has been measured yet.",
        fresh="{n} newer calls from the last 24 hours are for members.",
        hold_h="Holders", hold_note="Shares of the supply held by the top 20 holders, by class (our classification of "
                                    "the wallets; no wallet addresses are shown).",
        cls={"lp": "Liquidity pools", "burn": "Burned", "exchange": "Exchanges", "team": "Team / dev",
             "insider": "Insiders", "whale": "Whales", "normal": "Other top 20 holders"},
        conc=("Team + insiders (exchanges and pools not counted)", "Top 10 other holders", "Concentration (HHI)",
              "Holders", "Top 10 wallets (RugCheck)", "Liquidity locked", "Mint authority", "Freeze authority"),
        auth_off="revoked ✓", auth_on="active ⚠",
        ex_h="Exchange wallets", lst_h="Listing status by exchange",
        lst_note="From the exchanges' own public market lists and CoinGecko, refreshed daily.",
        lcols=("Exchange", "Status", "Source"),
        st={"da": "listed", "nesigurno": "same symbol, contract not confirmed", "ne": "not listed",
            "nepoznato": "unknown (list not available)"},
        src={"cg": "CoinGecko", "list": "{ex} public market list"}, cg_cex="CoinGecko lists it on {n} exchanges{names}.",
        lsig_h="Listing signals (older than 24 hours)",
        lsig_cols=("Date", "Signal", "Exchange", "Price after 24 h", "after 7 d"),
        lsig_kind={"pre_listing": "supply moved to an exchange that does not list it yet",
                   "deposit_sell": "deposit to an exchange that already lists it (possible selling)",
                   "other": "other"},
        ins_h="Insiders and smart money",
        ins_note="Counts only, from our wallet analysis of this token's jumps and calls older than 24 hours.",
        ins=("Price jumps and calls analysed", "Wallets that traded them", "Bought before the jump or call",
             "Sold into the jump", "Confirmed insider groups involved", "Smart-money buy signals (2+ groups at once)"),
        ins_none="No insider analysis of this token yet.",
        lock_h="What members see on top",
        lock=("{n} influencer calls from the last 24 hours, live", "Live influencer and Telegram calls",
              "Live signals: smart money, listings and the odds of a jump", "Our entry zone for this token",
              "Our demo and Autopilot trades on this token",
              "Fresh listing and insider signals (public here after 24 hours)"),
        cta="Request access", home="/",
        fb_h="Feedback", fb_none="No comments yet.", fb_login="Log in to comment and vote", fb_acc="No account?",
        fb_note="Comments by MemeSonar players. Everyone can read them.",
        addr="Contract address", copy="Copy", similar="Similar tokens",
        faq_h="Questions about {sym}",
        faq=(("What is the {sym} contract address?", "The Solana contract address of {name} is {mint}."),
             ("Who called {sym}?", "{calls}"),
             ("How much does {sym} move in a day?", "{rng}")),
        faq_calls="{n} clean influencer and Telegram calls of {sym} have been measured; the price was higher one hour "
                  "later {up} of the time.", faq_nocalls="No clean influencer call of {sym} has been measured yet.",
        faq_rng="On a typical day {sym} moves {med} between its low and high (last {n} days).",
        faq_norng="Not enough daily history yet to say.",
        upd="Updated {d} UTC · data: DexScreener, GeckoTerminal, RugCheck, Jupiter, exchange lists, MemeSonar",
    ),
    "hr": dict(
        title="{sym} cijena, graf, holderi i tko ga je zvao | MemeSonar",
        desc="{ns} na Solani: tržišna vrijednost {mc}, tipičan dnevni raspon {rng}, {n} izmjerenih poziva "
             "influencera, klase holdera i burze. Osvježava se svaki sat.",
        h1="{name} ({sym})", sub="cijena, volumen, holderi i tko ga je zvao",
        lead="{name} je Solana meme coin s tržišnom vrijednošću {mc}, {liq} likvidnosti i {vol} trgovanja u zadnja 24 "
             "sata. MemeSonar ga prati od {since}.",
        back="← Najveći Solana meme coini", lb="/hr/solana-meme-coini", prof="/hr/coin/", infl="/hr/influencer/",
        tg="/hr/telegram/",
        frozen={"rug": "Ovaj token više ne pratimo: {d} je označen kao rug. Brojke ispod su zamrznute na taj dan.",
                "mc_low": "Ovaj token više ne pratimo: tržišna vrijednost pala je ispod 2M $ {d}. Brojke ispod su "
                          "zamrznute na taj dan.",
                "mc_high": "Ovaj token više ne pratimo na ovoj listi: tržišna vrijednost narasla je iznad 200M $ {d}. "
                           "Brojke ispod su zamrznute na taj dan.",
                "out": "Ovaj token više ne pratimo (od {d}). Brojke ispod su zamrznute na taj dan."},
        thin="Premalo podataka: dosad {n} dana povijesti cijene (treba nam {m}). Stranica ostaje izvan rezultata "
             "pretrage dok ne skupi dovoljno, a mišljenje AI-ja piše se tek tada.",
        cards=("Cijena", "Tržišna vrijednost", "Promjena 24 h", "Likvidnost", "Volumen 24 h", "Kategorija"),
        ch_px="Cijena", ch_mc="Tržišna vrijednost", ch_vol="Dnevni volumen", ch_liq="Likvidnost", ch_hold="Holderi",
        ch_d="dnevno, zadnjih {n} dana", ch_14="zadnjih 14 dana",
        stats_h="Statistika", stats=("Tipičan dnevni raspon", "Pola dana između", "Raspon 30 dana",
                                     "Položaj u rasponu 30 dana", "Promjena 7 / 30 / 90 dana", "Ispod vrha",
                                     "Dani s volumenom 50k $+ (30 / 90 d)", "Prosječan dnevni volumen (30 d)",
                                     "Korelacija s Bitcoinom (dnevno / 4 h)", "Beta prema Bitcoinu (dnevno)",
                                     "Viši 72 h nakon dana Bitcoina +3 %", "Odbijanja s dna 30 dana",
                                     "Odbijanja koja su dosegla +15 % u 7 dana", "Medijan najboljeg / najgoreg u 7 dana",
                                     "Dob", "Kategorija"),
        days="{n} dana", of="{k} od {n}", cat={"A": "A: star, stalan volumen, prati Bitcoin", "B": "B: stalan volumen",
                                               "C": "C: mlad ili nestalan volumen"},
        b_h="Zadnja odbijanja s dna 30-dnevnog raspona", bcols=("Dan", "Najbolje u 7 dana", "Najgore u 7 dana"),
        int_h="Što kažu brojke", int_note="Čitanje brojki iznad jednostavnim riječima, po stalnim pravilima. Nije "
                                          "savjet.", risks_h="Rizici",
        op_h="Mišljenje", op_none="Još nema mišljenja AI-ja: piše se jednom dnevno za tokene s dovoljno podataka.",
        op_date="Napisano {d} iz brojki s ove stranice, model {model}.",
        calls_h="Tko ga je zvao", calls_note="Pozivi influencera i Telegram kanala stariji od 24 sata i što je cijena "
        "napravila nakon njih. Samo čisti pozivi: izmjereni, ne nakon što se cijena već udvostručila, ne nađeni preko "
        "pretrage pobjednika, bez bot računa.",
        calls_sum="{n} čistih poziva od {c} računa: viša sat kasnije {up}, doseglo +15 % unutar 24 h {hit}, medijan "
                  "nakon 24 h {med}, rug (−90 %+) {rug}.",
        ccols=("Datum", "Tko", "Vrijednost kod poziva", "1 h", "24 h", "Vrh 24 h", "Objava"), post="objava",
        no_calls="Još nije izmjeren nijedan čisti poziv influencera za ovaj token.",
        fresh="{n} novijih poziva iz zadnja 24 sata je za članove.",
        hold_h="Holderi", hold_note="Udio ponude koji drži top 20 holdera, po klasi (naša klasifikacija novčanika; "
                                    "adrese novčanika se ne prikazuju).",
        cls={"lp": "Poolovi likvidnosti", "burn": "Spaljeno", "exchange": "Burze", "team": "Tim / dev",
             "insider": "Insajderi", "whale": "Kitovi", "normal": "Ostali iz top 20"},
        conc=("Tim + insajderi (bez burzi i poolova)", "Top 10 ostalih holdera", "Koncentracija (HHI)", "Holderi",
              "Top 10 novčanika (RugCheck)", "Zaključana likvidnost", "Mint ovlast", "Freeze ovlast"),
        auth_off="ukinuta ✓", auth_on="aktivna ⚠",
        ex_h="Novčanici burzi", lst_h="Status po burzama",
        lst_note="Iz javnih lista tržišta samih burzi i CoinGecka, osvježava se svaki dan.",
        lcols=("Burza", "Status", "Izvor"),
        st={"da": "listan", "nesigurno": "isti simbol, ugovor nepotvrđen", "ne": "nije listan",
            "nepoznato": "nepoznato (lista nedostupna)"},
        src={"cg": "CoinGecko", "list": "javna lista burze {ex}"}, cg_cex="CoinGecko ga vodi na {n} burzi{names}.",
        lsig_h="Listing signali (stariji od 24 sata)",
        lsig_cols=("Datum", "Signal", "Burza", "Cijena nakon 24 h", "nakon 7 d"),
        lsig_kind={"pre_listing": "ponuda poslana na burzu koja ga još ne lista",
                   "deposit_sell": "depozit na burzu koja ga već lista (moguća prodaja)", "other": "ostalo"},
        ins_h="Insajderi i pametni novac",
        ins_note="Samo zbrojevi, iz naše analize novčanika na skokovima i pozivima ovog tokena starijim od 24 sata.",
        ins=("Analiziranih skokova cijene i poziva", "Novčanika koji su njima trgovali", "Kupili prije skoka ili poziva",
             "Prodavali u skok", "Potvrđenih insajderskih grupa", "Signala kupnje pametnog novca (2+ grupe odjednom)"),
        ins_none="Još nema analize insajdera za ovaj token.",
        lock_h="Što članovi vide uz to",
        lock=("{n} poziva influencera iz zadnja 24 sata, uživo", "Pozivi influencera i Telegram kanala uživo",
              "Živi signali: pametni novac, listinzi i šansa za skok", "Naša zona ulaza za ovaj token",
              "Naši demo i Autopilot tradeovi na ovom tokenu",
              "Svježi listing i insajderski signali (ovdje javno nakon 24 sata)"),
        cta="Zatraži pristup", home="/hr",
        fb_h="Povratne informacije", fb_none="Još nema komentara.", fb_login="Prijavi se za komentar i glas",
        fb_acc="Nemaš račun?", fb_note="Komentari igrača MemeSonara. Čitati ih mogu svi.",
        addr="Adresa ugovora", copy="Kopiraj", similar="Slični tokeni",
        faq_h="Pitanja o {sym}",
        faq=(("Koja je adresa ugovora za {sym}?", "Solana adresa ugovora za {name} je {mint}."),
             ("Tko je zvao {sym}?", "{calls}"),
             ("Koliko se {sym} pomakne u danu?", "{rng}")),
        faq_calls="Izmjereno je {n} čistih poziva influencera i Telegram kanala za {sym}; cijena je sat kasnije bila "
                  "viša u {up} slučajeva.", faq_nocalls="Još nije izmjeren nijedan čisti poziv influencera za {sym}.",
        faq_rng="Tipičan dan {sym} prijeđe {med} između najniže i najviše cijene (zadnjih {n} dana).",
        faq_norng="Još nema dovoljno dnevne povijesti.",
        upd="Osvježeno {d} UTC · podaci: DexScreener, GeckoTerminal, RugCheck, Jupiter, liste burzi, MemeSonar",
    ),
}


def _P():
    from ui import public
    return public


def _K():
    from ui import coins
    return coins


def _ts_store():
    from tokenstranice import store
    return store


def _read(slug=None, mint=None):
    """(page row, opinion) from tokenstranice.db, (None, None) without it."""
    S = _ts_store()
    con = S.ro()
    if con is None:
        return None, None
    try:
        p = S.page(con, mint=mint, slug=slug)
        return p, (S.opinion(con, p["mint"]) if p else None)
    except Exception:  # noqa: BLE001 - an older or broken file: no extra sections
        return None, None
    finally:
        con.close()


def _fb(mint, user=None, mod=False):
    from tokenstranice import povratne
    con = povratne.ro()
    try:
        return povratne.read(con, mint, user, with_hidden=mod)
    finally:
        if con is not None:
            con.close()


# ---------- small formatters ------------------------------------------------------------------------------------------

def _pc(x, lang, nd=0, sign=False):
    from tokenstranice import tumac
    return tumac.pct(x, lang, nd, sign)


def _sh(x, lang, sign=False):
    from tokenstranice import tumac
    return tumac.share(x, lang, sign)


def _num(x, lang, nd=2):
    if x is None:
        return "–"
    s = f"{x:,.{nd}f}"
    return s.replace(",", "\0").replace(".", ",").replace("\0", ".") if lang == "hr" else s


def _day(ts):
    return time.strftime("%Y-%m-%d", time.gmtime(ts)) if ts else "–"


def _cls(x):
    return "" if x is None else ("pos" if x > 0 else "neg" if x < 0 else "")


def _table(head, rows, num_from=1):
    h = "".join(f"<th{' class=n' if j >= num_from else ''}>{x}</th>" for j, x in enumerate(head))
    b = "".join("<tr>" + "".join(f"<td{' class=n' if j >= num_from else ''}>{c}</td>" for j, c in enumerate(r)) + "</tr>"
                for r in rows)
    return f"<div class=tw><table><thead><tr>{h}</tr></thead><tbody>{b}</tbody></table></div>"


def _chart(title, pts, src, color, fmt, sym):
    pts = [(x, y) for x, y in pts if y is not None]
    svg = _K().svg_line(pts, color=color, label=f"{sym} {title}")
    if not svg:
        return ""
    return (f"<div class=card style='padding:18px'><div style='display:flex;justify-content:space-between'>"
            f"<b style='font-size:16px'>{title}</b><span class=mut style='font-size:13px'>{src}</span></div>{svg}"
            f"<div class=rng><span>{fmt(pts[0][1])}</span><span>{fmt(pts[-1][1])}</span></div></div>")


# ---------- sections (public; the private block reuses them in Croatian) -----------------------------------------------

def charts_html(d, lang):
    t, P = L[lang], _P()
    sym = esc(d.get("symbol") or "")
    h = d.get("hist") or {}
    px = [tuple(x) for x in h.get("px") or []]
    up = len(px) >= 2 and px[-1][1] >= px[0][1]
    n = len(px)
    out = "".join((
        _chart(t["ch_px"], px, t["ch_d"].format(n=n), "#16a34a" if up else "#dc2626", lambda v: P._price(v, lang), sym),
        _chart(t["ch_mc"], [tuple(x) for x in h.get("mc") or []], t["ch_d"].format(n=len(h.get("mc") or [])), "#4f46e5",
               lambda v: P._usd(v, lang), sym),
        _chart(t["ch_vol"], [tuple(x) for x in h.get("vol") or []], t["ch_d"].format(n=len(h.get("vol") or [])),
               "#0891b2", lambda v: P._usd(v, lang), sym),
        _chart(t["ch_liq"], [tuple(x) for x in h.get("liq") or []], t["ch_14"], "#7c3aed", lambda v: P._usd(v, lang), sym),
        _chart(t["ch_hold"], [tuple(x) for x in (d.get("holders") or {}).get("hist") or []],
               t["ch_d"].format(n=len((d.get("holders") or {}).get("hist") or [])), "#0f766e",
               lambda v: P._int(round(v), lang), sym)))
    return f"<div class=charts>{out}</div>" if out else ""


def stats_html(d, lang):
    t = L[lang]
    m, rg, ch, P = d.get("m") or {}, d.get("range") or {}, d.get("chg") or {}, _P()
    rows = []

    def add(i, v):
        if v not in (None, "", "–"):
            rows.append((t["stats"][i], v))
    if rg:
        add(0, _pc(rg.get("med"), lang, 1))
        add(1, f"{_pc(rg.get('p25'), lang, 1)} – {_pc(rg.get('p75'), lang, 1)}")
        add(2, f"{P._price(rg.get('lo30'), lang)} – {P._price(rg.get('hi30'), lang)} ({_pc(rg.get('width30'), lang)})")
        add(3, _pc(rg.get("pos30"), lang))
    if any(ch.get(k) is not None for k in ("7d", "30d", "90d")):
        add(4, " / ".join(f"<span class={_cls(ch.get(k))}>{_pc(ch.get(k), lang, 0, True)}</span>" for k in ("7d", "30d", "90d")))
    if m.get("dd_ath") is not None:
        add(5, _pc(-m["dd_ath"] * 100, lang))
    if m.get("pers30") is not None:
        add(6, f"{_sh(m.get('pers30'), lang)} / {_sh(m.get('pers90'), lang)}")
    if m.get("vol_day_avg30"):
        add(7, P._usd(m["vol_day_avg30"], lang))
    if m.get("corr_d") is not None:
        add(8, f"{_num(m.get('corr_d'), lang)} / {_num(m.get('corr_4h'), lang)}")
        add(9, _num(m.get("beta_d"), lang))
    if m.get("btc_up_n"):
        add(10, f"{_sh(m.get('btc_up_hit'), lang)} ({t['of'].format(k=round((m.get('btc_up_hit') or 0) * m['btc_up_n']), n=m['btc_up_n'])})")
    if m.get("bounce_n"):
        add(11, str(m["bounce_n"]))
        add(12, _sh(m.get("hit15"), lang))
        add(13, f"{_pc(m.get('med_up7'), lang, 0, True)} / {_pc(m.get('med_dn7'), lang, 0, True)}")
    if m.get("age_d") is not None:
        add(14, t["days"].format(n=int(m["age_d"])))
    if m.get("cat") in t["cat"]:
        add(15, t["cat"][m["cat"]])
    if not rows:
        return ""
    body = "".join(f"<tr><td>{k}</td><td class=n><b>{v}</b></td></tr>" for k, v in rows)
    out = f"<h2 class=s>{t['stats_h']}</h2><div class=tw><table><tbody>{body}</tbody></table></div>"
    bl = d.get("bounces") or []
    if bl:
        out += (f"<h3 style='margin:18px 0 8px'>{t['b_h']}</h3>" + _table(t["bcols"], [
            (_day(b["ts"]), f"<span class=pos>{_pc(b['up7'], lang, 0, True)}</span>",
             f"<span class=neg>{_pc(b['dn7'], lang, 0, True)}</span>") for b in bl[::-1]]))
    return out


def interpret_html(d, lang, private=False):
    from tokenstranice import tumac
    t = L[lang]
    x = tumac.explain(d, lang)
    tn = " translate=no" if private else ""
    lines = "".join(f"<li>{esc(s)}</li>" for s in x["lines"])
    risks = "".join(f"<li>{esc(s)}</li>" for s in x["risks"])
    return (f"<h2 class=s>{t['int_h']}</h2><p class=mut>{t['int_note']}</p><ul class=tpi{tn}>{lines}</ul>"
            f"<h3 style='margin:14px 0 6px'>{t['risks_h']}</h3><ul class=tpi{tn}>{risks}</ul>")


def opinion_html(op, d, lang, private=False):
    """The AI opinion with its label and date; for a page without enough data nothing (the thin note says so)."""
    t = L[lang]
    if not d.get("enough"):
        return ""
    head = f"<h2 class=s>{t['op_h']}</h2>"
    if not op or not op.get(lang):
        return head + f"<p class=mut>{t['op_none']}</p>"
    o = op[lang]
    tn = " translate=no" if private else ""
    risks = "".join(f"<li>{esc(r)}</li>" for r in o.get("risks") or [])
    model = re.sub(r"[^a-z0-9.\-]", "", str(op.get("model") or "").lower())[:30] or "AI"
    return (head + f"<div class=tpo><span class=tpl>{AI_LABEL[lang]}</span><p{tn}>{esc(o.get('text'))}</p>"
            + (f"<ul{tn}>{risks}</ul>" if risks else "")
            + f"<p class=mut style='font-size:13px'>{t['op_date'].format(d=_day(op.get('ts')), model=esc(model))}</p></div>")


def _who(c, lang):
    t, P = L[lang], _P()
    w = c.get("who") or ""
    if P.BAD.search(w):
        return None
    if c.get("kind") == "tg":
        return f"<a href=\"{t['tg']}{esc(w)}\">Telegram: {esc(w)}</a>"
    return f"<a href=\"{t['infl']}{esc(w)}\">@{esc(w)}</a>"


def calls_html(d, lang, private=False, with_head=True):
    t, P = L[lang], _P()
    c = d.get("calls") or {}
    s = c.get("stats") or {}
    rows = []
    for x in c.get("list") or []:
        who = _who(x, lang)
        if not who:
            continue
        post = (f"<a href=\"{esc(x['url'])}\" target=_blank rel=\"nofollow noopener\">{t['post']} ↗</a>"
                if x.get("url") else "")
        mark = ("" if x.get("clean") or not private else " <span class=mut>(još se mjeri)</span>"
                if x.get("max24") is None else " <span class=mut>(nije čist)</span>")
        rows.append((f"<span class=mut>{_day(x['ts'])}</span>", who + mark, P._usd(x.get("mcap0"), lang),
                     *(f"<span class={_cls(x.get(k))}>{P._pct(x.get(k), True)}</span>" for k in ("r1h", "r24h", "max24")),
                     post))
    head = f"<h2 class=s>{t['calls_h']}</h2><p class=mut>{t['calls_note']}</p>" if with_head else ""
    summ = (f"<p>{t['calls_sum'].format(n=s['n'], c=s.get('callers', 0), up=_sh(s.get('up1h'), lang), hit=_sh(s.get('hit15'), lang), med=_sh(s.get('med24'), lang, True), rug=_sh(s.get('rug'), lang))}</p>"
            if s.get("n") else "")
    table = _table(t["ccols"], rows, 2) if rows else f"<p class=mut>{t['no_calls']}</p>"
    fresh = (f"<p class=mut>🔒 {t['fresh'].format(n=c['fresh'])}</p>" if c.get("fresh") and not private else "")
    return head + summ + table + fresh


def holders_html(d, lang, top=False):
    """top: on the top 100 page, whose safety table already has the holder count and Jupiter's authorities."""
    t, P = L[lang], _P()
    h = d.get("holders") or {}
    out = []
    sh = h.get("shares") or {}
    if sh:
        cols = {"lp": "#94a3b8", "burn": "#64748b", "exchange": "#0891b2", "team": "#dc2626", "insider": "#ea580c",
                "whale": "#7c3aed", "normal": "#16a34a"}
        bars = "".join(f"<div class=cbr><span>{t['cls'][k]}</span><i><em style='width:{min(100, v):.1f}%;"
                       f"background:{cols[k]}'></em></i><b>{_pc(v, lang, 1)}</b></div>"
                       for k, v in sorted(sh.items(), key=lambda kv: -kv[1]) if k in t["cls"] and v > 0)
        out.append(f"<p class=mut>{t['hold_note']}</p>{bars}")
    rows = []
    rc, jp = h.get("rc") or {}, h.get("jup") or {}
    if h.get("insider_ex") is not None:
        rows.append((t["conc"][0], _pc(h["insider_ex"], lang, 1)))
        rows.append((t["conc"][1], _pc(h.get("top10_ex"), lang, 1)))
        if h.get("hhi") is not None:
            rows.append((t["conc"][2], _num(h["hhi"], lang, 0)))
    n_h = rc.get("holders") or (None if top else h.get("n_holders_jup"))
    if n_h:
        rows.append((t["conc"][3], P._int(n_h, lang)))
    if rc.get("top10") is not None:
        rows.append((t["conc"][4], _pc(rc["top10"] * (100 if rc["top10"] <= 1 else 1), lang, 1)))
    if rc.get("lp_locked") is not None:
        rows.append((t["conc"][5], _pc(rc["lp_locked"], lang)))
    if rc:
        rows.append((t["conc"][6], t["auth_on"] if rc.get("mint_auth") else t["auth_off"]))
        rows.append((t["conc"][7], t["auth_on"] if rc.get("freeze_auth") else t["auth_off"]))
    elif jp and not top:
        rows.append((t["conc"][6], t["auth_off"] if jp.get("mint_off") else t["auth_on"]))
        rows.append((t["conc"][7], t["auth_off"] if jp.get("freeze_off") else t["auth_on"]))
    if rows:
        out.append("<div class=tw style='margin-top:12px'><table><tbody>" + "".join(
            f"<tr><td>{k}</td><td class=n><b>{v}</b></td></tr>" for k, v in rows) + "</tbody></table></div>")
    exs = h.get("exchanges") or {}
    if exs:
        out.append(f"<h3 style='margin:16px 0 6px'>{t['ex_h']}</h3><div class=chips>" + "".join(
            f"<a>{esc(k)} · {_pc(v, lang, 2)}</a>" for k, v in sorted(exs.items(), key=lambda kv: -kv[1])) + "</div>")
    lst = [x for x in d.get("listing") or [] if x["st"] != "nepoznato"]
    if lst:
        rws = [(esc(x["ex"]), f"<b>{t['st'][x['st']]}</b>" if x["st"] == "da" else t["st"][x["st"]],
                t["src"][x["src"]].format(ex=esc(x["ex"])) if x.get("src") else "–") for x in lst]
        out.append(f"<h3 style='margin:16px 0 6px'>{t['lst_h']}</h3><p class=mut>{t['lst_note']}</p>"
                   + _table(t["lcols"], rws, 9))
    if h.get("cg_cex"):
        names = (": " + ", ".join(esc(x) for x in h.get("cg_major") or [])) if h.get("cg_major") else ""
        out.append(f"<p>{t['cg_cex'].format(n=h['cg_cex'], names=names)}</p>")
    ls = (d.get("lsig") or {}).get("list") or []
    if ls:
        out.append(f"<h3 style='margin:16px 0 6px'>{t['lsig_h']}</h3>" + _table(t["lsig_cols"], [
            (_day(s["ts"]), t["lsig_kind"].get(s["kind"], s["kind"]), esc(s.get("ex") or "–"),
             f"<span class={_cls(s.get('r24h'))}>{_pc(s.get('r24h'), lang, 1, True)}</span>",
             f"<span class={_cls(s.get('r7d'))}>{_pc(s.get('r7d'), lang, 1, True)}</span>") for s in ls], 3))
    if not out:
        return ""
    return f"<h2 class=s>{t['hold_h']}</h2>" + "".join(out)


def insiders_html(d, lang):
    t = L[lang]
    i = d.get("ins") or {}
    if not i or not (i.get("events") or i.get("smart_sig")):
        return f"<h2 class=s>{t['ins_h']}</h2><p class=mut>{t['ins_none']}</p>" if i else ""
    vals = (i.get("events"), i.get("wallets"), i.get("before"), i.get("sold_into"), i.get("groups"), i.get("smart_sig"))
    body = "".join(f"<tr><td>{k}</td><td class=n><b>{int(v or 0)}</b></td></tr>" for k, v in zip(t["ins"], vals))
    return (f"<h2 class=s>{t['ins_h']}</h2><p class=mut>{t['ins_note']}</p><div class=tw><table><tbody>{body}"
            f"</tbody></table></div>")


def lock_html(d, lang):
    t, base = L[lang], _P().L[lang]
    fresh = (d.get("calls") or {}).get("fresh") or 0
    items = [t["lock"][0].format(n=fresh) if fresh else t["lock"][1]] + list(t["lock"][2:])
    return ("<div class=lock style='display:block'><b style='font-size:18px'>" + t["lock_h"] + "</b><ul class=lk>"
            + "".join(f"<li>🔒 {x}</li>" for x in items)
            + f"</ul><a class='btn sm' href={base['home']}#pristup>{base['cta']}</a></div>")


def feedback_public(mint, lang):
    from tokenstranice import povratne
    from ui import urls
    t = L[lang]
    fb = _fb(mint)
    msgs = "".join(f"<li><b translate=no>{esc(m['user'])}</b><span>{_day(m['ts'])}</span>"
                   f"<div translate=no>{povratne.show_text(m['text'], mint)}</div></li>" for m in fb["msgs"])
    login = esc(urls.app_link(f"/token/{mint}#povratne"))
    return (f"<h2 class=s id=povratne>{t['fb_h']}</h2><p class=mut>{t['fb_note']}</p>"
            f"<div class=tpv><b>👍 {fb['up']}</b><b>👎 {fb['down']}</b></div>"
            + (f"<ul class=tpfb>{msgs}</ul>" if msgs else f"<p class=mut>{t['fb_none']}</p>")
            + f"<p><a href=\"{login}\">{t['fb_login']}</a> · {t['fb_acc']} <a href={t['home']}#pristup>{t['cta']}</a></p>")


# ---------- the whole public page (midcaps without a top 100 page) ------------------------------------------------------

def _similar(p, lang):
    S = _ts_store()
    con = S.ro()
    if con is None:
        return ""
    try:
        rows = con.execute("SELECT slug, symbol, mcap FROM pages WHERE active=1 AND enough=1 AND mint<>? AND "
                           "COALESCE(cat, '')=COALESCE(?, '') ORDER BY ABS(COALESCE(mcap, 0) - ?) LIMIT 8",
                           (p["mint"], p.get("cat"), p.get("mcap") or 0)).fetchall()
    except Exception:  # noqa: BLE001
        rows = []
    finally:
        con.close()
    t, P = L[lang], _P()
    chips = "".join(f"<a href=\"{t['prof']}{esc(s)}\">{esc(P._sym(sym, ''))} · {P._usd(mc, lang)}</a>"
                    for s, sym, mc in rows if s)
    return f"<h2 class=s>{t['similar']}</h2><div class=chips>{chips}</div>" if chips else ""


def _addr(mint, lang):
    t, m = L[lang], esc(mint)
    links = (f"<a href=\"https://dexscreener.com/solana/{m}\" target=_blank rel=\"nofollow noopener\">DexScreener ↗</a> · "
             f"<a href=\"https://solscan.io/token/{m}\" target=_blank rel=\"nofollow noopener\">Solscan ↗</a>")
    return (f"<div class=card style='margin:18px 0'><span class=mut style='font-size:13px'>{t['addr']}</span>"
            f"<div style='display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-top:6px'><code style='font-size:13px;"
            f"word-break:break-all'>{m}</code><button class='btn g sm' type=button onclick=\"navigator.clipboard&&"
            f"navigator.clipboard.writeText('{m}');this.textContent='✓'\">{t['copy']}</button></div>"
            f"<div style='margin-top:8px;font-size:14px'>{links}</div></div>")


def page(slug, lang):
    """The public page of a tracked token without a top 100 page (or None: unknown slug)."""
    from tokenstranice import podaci
    if not re.fullmatch(r"[a-z0-9\-]{1,40}", slug or ""):
        return None
    p, op = _read(slug=slug)
    if not p or not p.get("data"):
        return None
    d, t, P = p["data"], L[lang], _P()
    canon = p["slug"]
    mint, sym_raw = p["mint"], P._sym(p.get("symbol") or d.get("symbol"), p["mint"])
    name_raw = (p.get("name") or "").strip()
    if not name_raw or P.BAD.search(name_raw):
        name_raw = sym_raw
    sym, name = esc(sym_raw), esc(name_raw)
    nw = d.get("now") or {}
    rg = d.get("range") or {}
    cs = (d.get("calls") or {}).get("stats") or {}
    enough = bool(p.get("enough"))
    lead = t["lead"].format(name=name, mc=P._usd(nw.get("mcap"), lang), liq=P._usd(nw.get("liq"), lang),
                            vol=P._usd(nw.get("vol24"), lang), since=_day(d.get("since") or p.get("first_ts")))
    note = ""
    if not p.get("active"):
        note += f"<div class=tpnote>{t['frozen'].get(p.get('out_why') or 'out', t['frozen']['out']).format(d=_day(p.get('out_ts')))}</div>"
    if not enough:
        note += f"<div class=tpnote>{t['thin'].format(n=d.get('days') or 0, m=podaci.ENOUGH_DAYS)}</div>"
    c24 = nw.get("chg24")
    chg = (f"<b class={'pos' if c24 > 0 else 'neg'}>{P._loc(f'{c24:+.1f}', lang)}%</b>" if c24 is not None else "<b>–</b>")
    cat = (d.get("m") or {}).get("cat")
    cards = "".join(f"<div class=card>{v if v.startswith('<b') else f'<b>{v}</b>'}<span>{lab}</span></div>"
                    for v, lab in zip((P._price(nw.get("price"), lang), P._usd(nw.get("mcap"), lang), chg,
                                       P._usd(nw.get("liq"), lang), P._usd(nw.get("vol24"), lang), esc(cat or "–")),
                                      t["cards"]))
    calls_ans = (t["faq_calls"].format(n=cs["n"], sym=sym, up=_sh(cs.get("up1h"), lang)) if cs.get("n")
                 else t["faq_nocalls"].format(sym=sym))
    rng_ans = (t["faq_rng"].format(sym=sym, med=_pc(rg.get("med"), lang, 1), n=rg.get("n")) if rg else t["faq_norng"])
    faq = [(q.format(sym=sym), a.format(name=name, mint=esc(mint), calls=calls_ans, rng=rng_ans)) for q, a in t["faq"]]
    faq_html = "".join(f"<details><summary>{q}</summary><p>{a}</p></details>" for q, a in faq)
    jsonld = ('<script type="application/ld+json">' + json.dumps({
        "@context": "https://schema.org", "@type": "FAQPage",
        "mainEntity": [{"@type": "Question", "name": q, "acceptedAnswer": {"@type": "Answer", "text": a}}
                       for q, a in faq]}).replace("</", "<\\/") + "</script>")
    body = (f"<style>{CSS}</style><section class=ph1><div class=crumb><a href={t['lb']}>{t['back']}</a></div>"
            f"<h1>{t['h1'].format(name=name, sym=sym) if name_raw.lower().lstrip('$') != sym_raw.lower().lstrip('$') else sym} "
            f"<span class=mut style='font-weight:500;font-size:.5em'>{t['sub']}</span></h1>"
            f"<p class=lead>{lead}</p></section>{note}<div class=cards>{cards}</div>{charts_html(d, lang)}"
            f"{stats_html(d, lang)}{interpret_html(d, lang)}{opinion_html(op, d, lang)}{calls_html(d, lang)}"
            f"{holders_html(d, lang)}{insiders_html(d, lang)}{lock_html(d, lang)}{feedback_public(mint, lang)}"
            f"{_addr(mint, lang)}<h2 class=s>{t['faq_h'].format(sym=sym)}</h2><div class=faq style='margin:0'>{faq_html}</div>"
            f"{_similar(p, lang)}<p class=mut style='font-size:13px;margin-top:24px'>"
            f"{t['upd'].format(d=time.strftime('%Y-%m-%d %H:%M', time.gmtime(p.get('updated') or d.get('ts') or 0)))}</p>")
    title = t["title"].format(sym=sym_raw)
    same = name_raw.lower().lstrip("$") == sym_raw.lower().lstrip("$")
    desc = t["desc"].format(ns=sym_raw if same else f"{name_raw} ({sym_raw})", mc=P._usd(nw.get("mcap"), lang),
                            rng=_pc(rg.get("med"), lang, 1) if rg else "–", n=cs.get("n") or 0)
    return P._shell(lang, title, desc, f"/coin/{canon}", f"/hr/coin/{canon}", body, jsonld=jsonld,
                    noindex=not enough or slug != canon)


# ---------- hooks for the top 100 page (ui/public.coin_page) -----------------------------------------------------------

def coin_calls(mint, lang):
    """The clean calls table of a top 100 coin from our snapshot (X and Telegram), "" before the first snapshot."""
    p, _op = _read(mint=mint)
    if not p or not p.get("data"):
        return ""
    return calls_html(p["data"], lang, with_head=False)


def coin_extra(r, lang):
    """Statistics, interpretation, opinion, holders, insiders and feedback for a top 100 coin page ("" without a
    snapshot: the page is then exactly as before)."""
    p, op = _read(mint=r["mint"])
    if not p or not p.get("data"):
        return ""
    d, t = p["data"], L[lang]
    note = ("" if p.get("active") else f"<div class=tpnote>{t['frozen'].get(p.get('out_why') or 'out', t['frozen']['out'])}"
            f"</div>".format(d=_day(p.get("out_ts"))))
    return (f"<style>{CSS}</style>{note}{stats_html(d, lang)}{interpret_html(d, lang)}{opinion_html(op, d, lang)}"
            f"{holders_html(d, lang, top=True)}{insiders_html(d, lang)}{feedback_public(r['mint'], lang)}")


def urls(now=None):
    """[(path_en, path_hr, priority)]: token pages with enough data that are not in today's top 100 (those are in
    the sitemap already); frozen ones for SITEMAP_FROZEN_D days."""
    S = _ts_store()
    con = S.ro()
    if con is None:
        return []
    now = now or time.time()
    try:
        rows = con.execute("SELECT mint, slug FROM pages WHERE enough=1 AND (active=1 OR COALESCE(out_ts, 0) >= ?) "
                           "ORDER BY vol24 DESC", (int(now - SITEMAP_FROZEN_D * 86400),)).fetchall()
    except Exception:  # noqa: BLE001
        return []
    finally:
        con.close()
    try:
        top = {c["mint"] for c in _K().top()}
    except Exception:  # noqa: BLE001
        top = set()
    return [(f"/coin/{s}", f"/hr/coin/{s}", "0.6") for m, s in rows if s and m not in top]


def drop_public_cache(mint):
    """After a comment or a vote: the cached public copies of this token's page go (guests see it at the next view)."""
    p, _op = _read(mint=mint)
    slugs = {p["slug"]} if p else set()
    try:
        from ui import coins as K
        con = K._ro(K.DB)
        if con is not None:
            try:
                slugs |= {s for (s,) in con.execute("SELECT slug FROM coins WHERE mint=?", (mint,))}
            finally:
                con.close()
    except Exception:  # noqa: BLE001
        pass
    P = _P()
    with P._lock:
        for s in slugs:
            P._cache.pop(f"/coin/{s}", None)
            P._cache.pop(f"/hr/coin/{s}", None)


# ---------- the private block on /token/<address> (Croatian, fresh, no delay) -------------------------------------------

PRIV_CSS = """<style>.tps{margin:18px 0}.tps h2{font-size:20px;margin:26px 0 10px}.tps .tw{overflow-x:auto;border:1px solid
var(--line);border-radius:14px}.tps table{border-collapse:collapse;width:100%;font-size:14px}.tps th,.tps td{padding:8px
10px;text-align:left;border-bottom:1px solid var(--line);white-space:nowrap}.tps td.n,.tps th.n{text-align:right}
.tps .cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:10px}.tps .card{border:1px solid
var(--line);border-radius:14px;padding:12px}.tps .card b{display:block;font-size:20px}.tps .card span{color:var(--mut);
font-size:12px}.tps .charts{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:10px}
.tps .rng{display:flex;justify-content:space-between;font-size:12px;color:var(--mut)}.tps .cbr{display:grid;
grid-template-columns:150px 1fr 70px;gap:8px;align-items:center;font-size:13px;margin:3px 0}.tps .cbr i{height:9px;
background:var(--soft);border-radius:8px;overflow:hidden;display:block}.tps .cbr em{display:block;height:100%}
.tps .cbr b{text-align:right}.tps .chips{display:flex;flex-wrap:wrap;gap:6px}.tps .chips a{border:1px solid var(--line);
border-radius:999px;padding:4px 10px;font-size:13px}.tps .pos{color:#16a34a}.tps .neg{color:#dc2626}
.tps .lock{display:none}.tpfbx form{margin:6px 0}.tpfbx textarea{width:100%;box-sizing:border-box;border:1px solid
var(--line);border-radius:12px;padding:10px;font:inherit}.tpfbx button{border:1px solid var(--line);border-radius:999px;
padding:6px 14px;background:var(--card);cursor:pointer}.tpfbx button.on{background:#e0f2fe;border-color:#7dd3fc}
.tpfbx .bad{color:#dc2626}.tpfbx li.hid{opacity:.5}""" + CSS.replace("\n", "") + "</style>"

PRIV_JS = """<script>(function(){var b=document.getElementById('tp-fb');if(!b||!window.fetch)return;
function put(h){if(h!=null)b.innerHTML=h}
function load(){fetch(b.getAttribute('data-src'),{credentials:'same-origin'}).then(function(r){return r.ok?r.text():null}).then(put).catch(function(){})}
b.addEventListener('submit',function(e){var f=e.target;if(!f.classList||!f.classList.contains('tp-ajax'))return;e.preventDefault();
var fd=new FormData(f);fd.append('ajax','1');var m=/(^|; )cb_csrf=(\\w+)/.exec(document.cookie);if(m&&!fd.has('_csrf'))fd.append('_csrf',m[2]);
fetch(f.getAttribute('action'),{method:'POST',body:new URLSearchParams(fd),credentials:'same-origin'}).then(function(r){return r.ok?r.text():null}).then(put).catch(function(){})});
load();})();</script>"""


def _ours_html(d):
    o = d.get("ours") or {}
    P = _P()
    out = ["<h2>Naša zona ulaza i tradeovi</h2>"]
    z = o.get("zone") or {}
    if z.get("ok"):
        out.append(f"<p>Dnevno pravilo (48 h zona): dno {P._price(z.get('lo'), 'hr')}, vrh {P._price(z.get('hi'), 'hr')}, "
                   f"ulaz ispod {P._price(z.get('s_hi'), 'hr')} (širina {_pc((z.get('width') or 0) * 100, 'hr')}).</p>")
    elif z:
        out.append(f"<p class=mut>Dnevno pravilo trenutno nema zonu: {esc(z.get('why') or 'nema podataka')}.</p>")
    tr = o.get("trades") or []
    if tr:
        out.append(_table(("Otvoreno", "Što", "Status", "Rezultat", "Razlog"), [
            (_day(x.get("ts")), esc(x.get("what")), esc(x.get("status")),
             f"<span class={_cls(x.get('ret'))}>{P._pct(x.get('ret'), True)}</span>", esc((x.get("why") or "")[:60]))
            for x in tr], 3))
    else:
        out.append("<p class=mut>Još nismo trgovali ovim tokenom.</p>")
    return "".join(out)


def _private_fresh(d):
    """Fresh signals (members only on the public page)."""
    i, ls = d.get("ins") or {}, d.get("lsig") or {}
    li = []
    if i.get("smart_buying_24h"):
        li.append(f"Pametni novčanici koji su ga kupili u zadnja 24 sata: <b>{i['smart_buying_24h']}</b>")
    if i.get("fresh_sig"):
        li.append(f"Svježih signala pametnog novca (24 h): <b>{i['fresh_sig']}</b>")
    if i.get("fresh_events"):
        li.append(f"Svježih skokova / poziva u analizi insajdera (24 h): <b>{i['fresh_events']}</b>")
    if ls.get("fresh"):
        li.append(f"Svježih listing signala (24 h): <b>{ls['fresh']}</b>")
    if not li:
        return ""
    return "<h2>Svježi signali</h2><ul class=tpi>" + "".join(f"<li>{x}</li>" for x in li) + "</ul>"


def _fb_initial(mint):
    fb = _fb(mint)
    return _fb_html(fb, mint, user=None, mod=False, generic=True)


def private_html(mint, qs=None):
    """The token page's sections inside the app (fresh: delay 0), '' for a mint without data. Never raises."""
    from tokenstranice import podaci, povratne
    if not povratne.MINT.fullmatch(mint or ""):
        return ""
    p, op = _read(mint=mint)
    if not p:   # only tokens with a page (midcap universe + top 100): nothing is read for microcaps (owner, 15.11.)
        return ""
    try:
        ctx = podaci.Ctx()
        try:
            base = {"symbol": (p or {}).get("symbol"), "name": (p or {}).get("name"), "src": (p or {}).get("src")}
            d = podaci.sections(mint, ctx, 0, base=base)
        finally:
            ctx.close()
    except Exception as e:  # noqa: BLE001 - the token page stays up without this block
        print(f"tokenstranica {mint[:6]}: {type(e).__name__}: {e}"[:200], flush=True)
        return ""
    from ui import urls
    head = ["<div class=tps id=stranica-tokena>", PRIV_CSS, "<h2>Stranica tokena</h2>"]
    site = urls.site()
    head.append(f"<p>Javna stranica: <a href=\"{site}/hr/coin/{esc(p['slug'])}\" target=_blank rel=noopener>"
                f"/hr/coin/{esc(p['slug'])}</a> · <a href=\"{site}/coin/{esc(p['slug'])}\" target=_blank rel=noopener>"
                f"engleski</a>" + ("" if p.get("active") else " <span class=mut>(zamrznuta: više ne pratimo)</span>")
                + ("" if p.get("enough") else " <span class=mut>(premalo podataka, noindex)</span>") + "</p>")
    head.append("<p class=mut>Ovdje svježe, bez odgode od 24 h koju ima javna stranica.</p>")
    body = (charts_html(d, "hr") + stats_html(d, "hr").replace("<h2 class=s>", "<h2>") + _private_fresh(d)
            + interpret_html(d, "hr", private=True).replace("<h2 class=s>", "<h2>")
            + opinion_html(op, {**d, "enough": bool(p.get("enough"))}, "hr", private=True).replace("<h2 class=s>", "<h2>")
            + "<h2>Tko ga je zvao (svi pozivi, i svježi)</h2>" + calls_html(d, "hr", private=True, with_head=False)
            + holders_html(d, "hr").replace("<h2 class=s>", "<h2>") + insiders_html(d, "hr").replace("<h2 class=s>", "<h2>")
            + _ours_html(d))
    err = (qs or {}).get("e")
    note = f"<p class=bad role=alert>{esc(povratne.ERR[err])}</p>" if err in povratne.ERR else ""
    fb = (f"<h2 id=povratne>Povratne informacije</h2><div id=tp-fb class=tpfbx data-src=\"{FB_PATH}?m={esc(mint)}\">"
          f"{note}{_fb_initial(mint)}</div>{PRIV_JS}")
    return "".join(head) + body + fb + "</div>"


# ---------- feedback inside the app (per player) ------------------------------------------------------------------------

def _fb_html(fb, mint, user, mod, generic=False, err=""):
    from tokenstranice import povratne
    m = esc(mint)
    up_on = " on" if fb.get("mine") == 1 else ""
    dn_on = " on" if fb.get("mine") == -1 else ""
    votes = (f"<div class=tpv><form method=post action=/tokenstranica/glas class=tp-ajax><input type=hidden name=m value={m}>"
             f"<input type=hidden name=v value=1><button class='{up_on.strip()}' title='Sviđa mi se'>👍 {fb['up']}</button></form>"
             f"<form method=post action=/tokenstranica/glas class=tp-ajax><input type=hidden name=m value={m}>"
             f"<input type=hidden name=v value=-1><button class='{dn_on.strip()}' title='Ne sviđa mi se'>👎 {fb['down']}"
             f"</button></form></div>")
    form = ""
    if user or generic:
        who = f" kao <b translate=no>{esc(user)}</b>" if user else ""
        form = (f"<form method=post action=/tokenstranica/poruka class=tp-ajax><input type=hidden name=m value={m}>"
                f"<textarea name=text rows=3 maxlength={povratne.MAX_LEN} required placeholder='Tvoj komentar o ovom "
                f"tokenu' aria-label='Tvoj komentar o ovom tokenu'></textarea><p class=mut style='font-size:13px'>"
                f"Najviše {povratne.MAX_LEN} znakova{who}. Komentar vide svi, i na javnoj stranici. "
                f"<button>Pošalji</button></p></form>")
    else:
        form = f"<p class=mut>{esc(povratne.ERR['login'])}</p>"
    items = []
    for x in fb.get("msgs") or []:
        hide = ""
        if mod:
            hide = (f"<form method=post action=/tokenstranica/sakrij class=tp-ajax style='display:inline'>"
                    f"<input type=hidden name=m value={m}><input type=hidden name=id value={int(x['id'])}>"
                    f"<input type=hidden name=on value={'0' if x['hidden'] else '1'}><button>"
                    f"{'Vrati' if x['hidden'] else 'Sakrij'}</button></form>")
        items.append(f"<li class='{'hid' if x['hidden'] else ''}'><b translate=no>{esc(x['user'])}</b>"
                     f"<span>{_day(x['ts'])}</span>{' <em>skriveno</em>' if x['hidden'] else ''} {hide}"
                     f"<div translate=no>{povratne.show_text(x['text'], mint)}</div></li>")
    lst = f"<ul class=tpfb>{''.join(items)}</ul>" if items else "<p class=mut>Još nema komentara.</p>"
    note = f"<p class=bad role=alert>{esc(povratne.ERR[err])}</p>" if err in povratne.ERR else ""
    return note + votes + form + lst


def _known(mint):
    p, _op = _read(mint=mint)
    if p:
        return True
    try:
        from ui import coins as K
        con = K._ro(K.DB)
        if con is None:
            return False
        try:
            return con.execute("SELECT 1 FROM coins WHERE mint=?", (mint,)).fetchone() is not None
        finally:
            con.close()
    except Exception:  # noqa: BLE001
        return False


def fb_fragment(user, mint, err=""):
    """The feedback box of one token for one player (GET /tokenstranica/povratne?m=, and the answer to a form)."""
    from tokenstranice import povratne
    if not povratne.MINT.fullmatch(mint or ""):
        return "<p class=mut>Nepoznat token.</p>"
    mod = povratne.can_moderate(user)
    return _fb_html(_fb(mint, user, mod), mint, user, mod, err=err)


def fb_post(path, form, user):
    """A feedback form -> (ok, code, mint); the public copies of the page are dropped on success."""
    from tokenstranice import povratne
    ok, code, mint = povratne.act(path, form, user, known=_known)
    if ok and mint:
        try:
            drop_public_cache(mint)
        except Exception:  # noqa: BLE001
            pass
    return ok, code, mint
