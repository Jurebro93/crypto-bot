"""Per-token evidence: every analysis the bot ran on one token, with the raw numbers and links to the source.

Used by the pop-up on the overview page (/api/evidence/<mint> returns an HTML fragment).
Each section names the API it came from, so a claim can be checked at the source.
"""
import datetime as dt
import html
import time
from urllib.parse import quote

from ui import data
from ui.labels import feat, feat_low, sources as sources_hr
from ui.html import tdesc, ago, badge, esc, ext_token, num, short, signed, table, ts, usd, verdict, wlink

SOURCES = {
    "dex": ("DexScreener API", "https://docs.dexscreener.com/api/reference"),
    "hype": ("hype skener", None),
    "x": ("X / Twitter preko Apify apidojo/tweet-scraper", "https://apify.com/apidojo/tweet-scraper"),
    "pumpfun": ("pump.fun preko Apify pump-fun-token-scraper", "https://apify.com/muhammetakkurtt/pump-fun-token-scraper-monitor"),
    "kol": ("praćenje KOL-ova na X-u", None),
    "tg": ("javni Telegram kanali (t.me/s)", None),
    "rug": ("Helius + RugCheck", "https://rugcheck.xyz"),
    "event": ("kalendar: Polymarket, Wikipedia, RocketLaunch, ručni eventi", None),
    "smart": ("smart walleti: naša Helius analiza + GMGN preko Apifyja", None),
    "paper": ("demo trading", None),
    "wallets": ("registar walleta (Helius)", None),
}


def _src(key, when=None):
    name, url = SOURCES[key]
    label = f'<a href="{url}" target=_blank rel=noopener>{esc(name)}</a>' if url else esc(name)
    return f'<div class=mut style="font-size:12px">Izvor: {label}' + (f" · {ago(when)[0]}" if when else "") + "</div>"


def tweets(mint):
    """Raw tweets of the newest X buzz search for this token (kept by hype/apify.py in apify_cache)."""
    rows = data.q(data.HYPE_DB, "SELECT ts, items FROM apify_cache WHERE key LIKE ? ORDER BY ts DESC LIMIT 1",
                  (f"x_buzz:%{mint}%",))
    if not rows:
        return None, []
    items = [t for t in (data.js(rows[0]["items"], []) or []) if isinstance(t, dict) and not t.get("noResults")]
    return rows[0]["ts"], items


def _author(t):
    a = t.get("author") or t.get("user") or {}
    return (a.get("userName") or a.get("screen_name") or "?"), (a.get("followers") or a.get("followersCount") or 0), a


def details(mint):
    rows = data.q(data.HYPE_DB, "SELECT ts, extra FROM hype_details WHERE token=? ORDER BY ts DESC LIMIT 1", (mint,))
    return (rows[0]["ts"], data.js(rows[0]["extra"], {}) or {}) if rows else (None, {})


def live_pair(mint):
    try:
        from dexscreener import client
        pairs = client.tokens("solana", [mint])
    except Exception:
        return None
    pairs = [p for p in pairs if p["baseToken"]["address"] == mint]
    return max(pairs, key=lambda p: (p.get("liquidity") or {}).get("usd") or 0) if pairs else None


def checks(mint, sig=None, det=None, rug=None, ev=None, cand=None):
    """[(label, passed True/False/None, detail)]: one row per analysis layer. None = not analysed."""
    det = det or {}
    x = det.get("x") or {}
    f = (data.js(sig["features"], {}) or {}) if sig else {}
    pf = det.get("pumpfun") or {}
    pct = lambda v: (v or 0) / 100 if (v or 0) > 100 else (v or 0)  # noqa: E731
    out = [
        ("Hype ≥ 50", None if sig is None else (sig["score"] or 0) >= 50,
         f"ocjena {sig['score']:.0f}" if sig else "nije skeniran"),
        ("X buzz", None if not x else (x.get("authors") or 0) >= 5 or bool(x.get("influencers")),
         f"{x.get('authors', 0)} autora, {len(x.get('influencers') or [])} influencera" if x else "nije provjeren"),
        ("Smart money", None if sig is None else bool(det.get("smart_buyers") or f.get("smart_money")),
         f"{len(det.get('smart_buyers') or [])} smart walleta među prvim kupcima" if sig else "–"),
        ("KOL", None if sig is None else bool(f.get("kol_wallets", 0) >= 0.4 or f.get("kol_x") or pf.get("kolCount")),
         f"{pf.get('kolCount') or 0} KOL walleta na pump.fun" + (", objavili na X-u" if f.get("kol_x") else "") if sig else "–"),
        ("Holderi", None if not pf else pct(pf.get("top10HoldersPercent")) < 35 and pct(pf.get("bundlerOwnedPercent")) < 15,
         f"top10 {pct(pf.get('top10HoldersPercent')):.0f}%, bundleri {pct(pf.get('bundlerOwnedPercent')):.0f}%" if pf else "nema pump.fun podataka"),
        ("Rug filter", None if not rug else rug["verdict"] in ("PROLAZI", "OPREZ"), rug["verdict"] if rug else "nije provjeren"),
        ("Event", None if not ev else any(e["role"] == "canonical" for e in ev),
         (ev[0]["event"] + (" (pravi)" if any(e["role"] == "canonical" for e in ev) else " (kopija)")) if ev else "nije vezan uz event"),
        ("Paper uzeo", None if not cand else bool(cand.get("trade_id")),
         (cand.get("decision") or "") + (f": {cand['reason']}" if cand.get("reason") else "") if cand else "nije razmatran"),
    ]
    return out


def check_badges(cs):
    return " ".join(badge(("✓ " if ok else "✗ ") + lab, "good" if ok else "bad") for lab, ok, _ in cs if ok is not None)


def fragment(mint):
    sigs = data.hype_signals("token=?", (mint,), "ts DESC", limit=500)
    sig = sigs[0] if sigs else None
    det_ts, det = details(mint)
    rugs = data.rug_reports(mint)
    rug = rugs[0] if rugs else None
    ev = data.event_tokens(mint)
    cands = data.paper_candidates(mint)
    cand = cands[0] if cands else None
    pair = live_pair(mint)
    sym = (pair or {}).get("baseToken", {}).get("symbol") or (sig or {}).get("symbol") or (rug or {}).get("symbol") \
        or (ev[0]["symbol"] if ev else None) or short(mint)
    cs = checks(mint, sig, det, rug, ev, cand)
    b = [f"<h2 style='margin-top:0'>{esc(sym)} <span class=mut style='font-size:13px'><code>{esc(mint)}</code></span></h2>",
         f'<p>{ext_token(mint)}</p><p><a href="/token/{quote(mint)}"><b>Otvori stranicu tokena →</b></a></p>']
    from ui import narrative
    b.append(narrative.html(mint))

    # confidence first: the one number, with every point explained
    from ui import confidence
    role = "canonical" if any(e["role"] == "canonical" for e in ev) else None
    mk = (rug or {}).get("data", {}).get("market") or {}
    conf, parts = confidence.score(sig["score"] if sig else None, (data.js(sig["features"], {}) or {}) if sig else {}, det,
                                   rug["verdict"] if rug else None, role,
                                   (sig or {}).get("liquidity") or mk.get("liquidity"), (sig or {}).get("mcap") or mk.get("mcap"))
    from ui import sansa
    sn, an, pr, pa = sansa.score(conf, cs)
    b.append("<div class=card>" + sansa.explain_html(sn, conf, an, pr, pa) + sansa.dots_html(cs)
             + confidence.explain_html(conf, parts) + "</div>")

    # verdict in one place
    passed = sum(1 for _, ok, _ in cs if ok)
    done = sum(1 for _, ok, _ in cs if ok is not None)
    b.append(f"<div class=card><b>Prošao {passed} od {done} provedenih analiza.</b><ul class=r>"
             + "".join(f'<li class="{"good" if ok else "bad" if ok is False else ""}"><b>{esc(lab)}</b>: {esc(d)}</li>'
                       for lab, ok, d in cs) + "</ul></div>")

    # why: hype reasons from the radar wording, then the numbers behind them
    if sig:
        f = data.js(sig["features"], {}) or {}
        w = data.js(sig["weights"], {}) or {}
        try:
            from ui.radar import reasons, risks
            why = reasons(f, det)
            risk = risks(sig, det, rug)
        except Exception:
            why, risk = [], []
        b.append("<h3>Zašto ga je bot istaknuo</h3>")
        if why:
            b.append("<ul class=r>" + "".join(f"<li class=good>{esc(t)}</li>" for t in why) + "</ul>")
        if risk:
            b.append("<ul class=r>" + "".join(f"<li class=bad>{esc(t)}</li>" for t in risk) + "</ul>")
        tot = sum(w.values()) or 1
        rows = sorted(((k, f.get(k) or 0, w.get(k, 0)) for k in set(f) | set(w)), key=lambda r: -r[1] * r[2])
        b.append(tdesc('Signali iz kojih je izračunata hype ocjena; prikazani su samo oni koji nisu nula.') + table(["Signal", ("Izmjereno 0-1", "n"), ("Težina", "n"), ("Bodova", "n")],
                       [[esc(feat(k)), (f"{v:.2f}", v, "n"), (f"{wt:g}", wt, "n"), (f"{100 * v * wt / tot:.1f}", v * wt, "n")]
                        for k, v, wt in rows if v]))
        zero = [k for k, v, wt in rows if not v and wt]
        if zero:
            b.append(f"<p class=mut>Nula (nije izmjereno ili nema signala): {esc(', '.join(sorted(feat_low(k) for k in zero)))}.</p>")
        b.append(f"<p>Ocjena <b>{sig['score']:.0f}</b>/100 · prvi signal {ts(sigs[-1]['ts'])[0]} UTC po cijeni "
                 f"{sigs[-1]['price']:.3g} · {len(sigs)} signala · otkud je došao: {esc(sources_hr(sig['sources']))}</p>"
                 + _src("hype", sig["ts"]))

    # market, live
    if pair:
        tx = (pair.get("txns") or {}).get("h24") or {}
        vol = pair.get("volume") or {}
        chg = pair.get("priceChange") or {}
        age_h = (time.time() * 1000 - (pair.get("pairCreatedAt") or time.time() * 1000)) / 3.6e6
        b.append("<h3>Tržište sada</h3>")
        b.append(tdesc('Živi podaci s DexScreenera u trenutku otvaranja.') + table(["Cijena", ("Mcap", "n"), ("Likvidnost", "n"), ("Volumen 1h / 24h", "n"), ("Promjena 1h / 24h", "n"),
                        ("Kupnje / prodaje 24h", "n"), ("Starost", "n")],
                       [[esc(pair.get("priceUsd")), usd(pair.get("marketCap") or pair.get("fdv")),
                         usd((pair.get("liquidity") or {}).get("usd")),
                         f"${vol.get('h1') or 0:,.0f} / ${vol.get('h24') or 0:,.0f}",
                         f"{chg.get('h1') or 0:+.0f}% / {chg.get('h24') or 0:+.0f}%",
                         f"{tx.get('buys', 0)} / {tx.get('sells', 0)}",
                         f"{age_h:.0f} h" if age_h < 72 else f"{age_h / 24:.0f} d"]]))
        info = pair.get("info") or {}
        links = [(s.get("type") or "link", s.get("url")) for s in info.get("socials") or []] + \
                [(w.get("label") or "web", w.get("url")) for w in info.get("websites") or []]
        if links:
            b.append("<p>Službeni linkovi tokena: " + " · ".join(
                f'<a href="{esc(u)}" target=_blank rel=noopener>{esc(n)}</a>' for n, u in links if u) + "</p>")
        if (pair.get("boosts") or {}).get("active"):
            b.append(f"<p class=mut>Dev je platio {pair['boosts']['active']} DexScreener boost(ova).</p>")
        b.append(_src("dex", time.time()))

    # X / Twitter evidence
    x_ts, tw = tweets(mint)
    x = det.get("x") or {}
    if tw or x:
        b.append("<h3>X / Twitter</h3>")
        views = sum(t.get("viewCount") or 0 for t in tw)
        likes = sum(t.get("likeCount") or 0 for t in tw)
        rts = sum(t.get("retweetCount") or 0 for t in tw)
        authors = {}
        for t in tw:
            h, fol, _ = _author(t)
            authors[h] = max(authors.get(h, 0), fol)
        b.append(f"<p><b>{len(tw) or x.get('tweets', 0)}</b> objava, <b>{len(authors) or x.get('authors', 0)}</b> različitih "
                 f"autora, <b>{views:,}</b> pregleda, {likes:,} lajkova, {rts:,} retweetova.</p>")
        infl = sorted(((h, f) for h, f in authors.items() if f >= 10000), key=lambda r: -r[1]) or \
            [tuple(i) for i in x.get("influencers") or []]
        if infl:
            b.append("<p><b>Influenceri (10k+ pratitelja):</b> " + ", ".join(
                f'<a href="https://x.com/{quote(h)}" target=_blank>@{esc(h)}</a> ({f:,})' for h, f in infl[:10]) + "</p>")
        top = sorted(tw, key=lambda t: -((t.get("viewCount") or 0) + 50 * (t.get("likeCount") or 0)))[:8]
        if top:
            b.append(tdesc('Najgledanije objave na X-u koje spominju adresu ili $simbol, s linkom na objavu.') + table(["Autor", ("Pratitelja", "n"), ("Pregleda", "n"), ("Lajk", "n"), ("RT", "n"), ("Objava", "wrap"), ""],
                           [[f'<a href="https://x.com/{quote(_author(t)[0])}" target=_blank>@{esc(_author(t)[0])}</a>',
                             num(_author(t)[1]), num(t.get("viewCount")), num(t.get("likeCount")), num(t.get("retweetCount")),
                             (esc(html.unescape(t.get("text") or t.get("fullText") or "")[:220]), "", "wrap"),
                             f'<a href="{esc(t.get("url") or t.get("twitterUrl") or "")}" target=_blank>otvori</a>']
                            for t in top]))
        b.append(_src("x", x_ts or det_ts))

    if det.get("x_trend"):
        b.append(f"<p>Ime je bilo <b>trending tema na X-u</b>: „{esc(det['x_trend'])}“.</p>")

    kol = data.q(data.HYPE_DB, "SELECT ts, handle, text FROM kol_mentions WHERE ca=? ORDER BY ts DESC LIMIT 20", (mint,))
    if kol:
        b.append("<h3>Praćeni influenceri (KOL) koji su ga objavili</h3><ul class=r>" + "".join(
            f'<li><a href="https://x.com/{quote(k["handle"])}" target=_blank>@{esc(k["handle"])}</a> {ago(k["ts"])[0]}: '
            f'<span class=mut>{esc((k["text"] or "")[:200])}</span></li>' for k in kol) + "</ul>" + _src("kol"))

    tg = data.multi("hype", "SELECT channel, post, time, tickers FROM tg_mentions WHERE ca=? ORDER BY time DESC LIMIT 20",
                    (mint,), lambda r: r["post"])
    if tg:
        b.append("<h3>Telegram</h3><ul class=r>" + "".join(
            f'<li><a href="https://t.me/{esc(t["post"])}" target=_blank>{esc(t["channel"] or t["post"])}</a> '
            f'<span class=mut>{esc(t["time"])}</span></li>' for t in tg) + "</ul>" + _src("tg"))

    pf = det.get("pumpfun") or {}
    if pf:
        pct = lambda v: (v or 0) / 100 if (v or 0) > 100 else (v or 0)  # noqa: E731
        b.append("<h3>pump.fun</h3>")
        b.append(tdesc('Podaci s pump.fun: koliko ga KOL walleta trejda i kako je ponuda raspodijeljena.') + table(["Liste", ("KOL walleta", "n"), ("Holdera", "n"), ("Top 10", "n"), ("Bundleri", "n"),
                        ("Snajperi", "n"), ("Dev drži", "n"), ("Bonding curve", "n")],
                       [[esc(", ".join(pf.get("boards") or [])), num(pf.get("kolCount")), num(pf.get("holders")),
                         num(pct(pf.get("top10HoldersPercent")), "{:.0f}%"), num(pct(pf.get("bundlerOwnedPercent")), "{:.0f}%"),
                         num(pct(pf.get("snipersOwnedPercent")), "{:.0f}%"), num(pct(pf.get("devHoldingsPercent")), "{:.1f}%"),
                         num(pf.get("bondingCurveProgress"), "{:.0f}%")]]))
        if pf.get("pumpFunUrl"):
            b.append(f'<p><a href="{esc(pf["pumpFunUrl"])}" target=_blank>Otvori na pump.fun</a></p>')
        b.append(_src("pumpfun", det_ts))

    if det.get("copycats"):
        b.append(f"<p><b>{det['copycats']}</b> drugih tokena istog imena u 3 dana: tema je živa. "
                 f'<a href="https://dexscreener.com/search?q={quote(sym)}" target=_blank>Vidi ih na DexScreeneru</a>.</p>')
    if det.get("search_rise"):
        b.append(f"<p>Google pretraga imena porasla je <b>{det['search_rise']}x</b> u 24 h "
                 f'(<a href="https://trends.google.com/trends/explore?date=now%207-d&q={quote(sym)}" target=_blank>Google Trends</a>).</p>')

    sm = det.get("smart_buyers") or []
    if sm:
        known = {w["wallet"]: w for w in data.smart_wallets()}
        b.append("<h3>Smart walleti među prvim kupcima</h3>" + tdesc('Walleti s dokazanim profitom koji su kupili ovaj token rano, i gdje smo ih pronašli.') + table(
            ["Wallet", ("Ocjena", "n"), "Pronađen preko", ""],
            [[wlink(w), num((known.get(w) or {}).get("score")), esc((known.get(w) or {}).get("found_via") or "–"),
              f'<a href="https://gmgn.ai/sol/address/{quote(w)}" target=_blank>GMGN</a>'] for w in sm]) + _src("smart"))

    sg = data.sightings(token=mint)
    if sg:
        reg = {w["wallet"]: w for w in data.wallets(scored_only=True)}
        good = [s for s in sg if s["role"] in ("early_buyer", "smart", "top_trader", "holder")]
        bad = [s for s in sg if s["role"] in ("dev", "bundler", "sniper")]
        scored = [reg[s["wallet"]] for s in good if s["wallet"] in reg]
        b.append(f"<h3>Walleti na tokenu</h3><p>{len(good)} ranih kupaca/holdera, {len(bad)} dev/bundler/snajper walleta; "
                 f"{len(scored)} ocijenjenih" + (f", najbolji copy {max(w['copy_score'] or 0 for w in scored):.0f}" if scored else "")
                 + ".</p>" + _src("wallets"))

    if rug:
        d = rug["data"]
        b.append(f"<h3>Rug filter</h3><p>{verdict(rug['verdict'])} ocjena {rug['score'] if rug['score'] is not None else '–'}</p><ul class=r>"
                 + "".join(f"<li class=bad>{esc(t)}</li>" for t in d.get("hard_fails", []))
                 + "".join(f"<li class=warn>{esc(t)}</li>" for t in d.get("flags", []))
                 + "".join(f"<li class=good>{esc(t)}</li>" for t in d.get("positives", [])) + "</ul>" + _src("rug", rug["checked_at"]))

    if ev:
        evs = {(e["date"], e["title"]): e for e in data.events()}
        b.append("<h3>Event</h3><ul class=r>")
        for e in ev:
            src = evs.get((e["event_date"], e["event"])) or {}
            link = f' · <a href="{esc(src["url"])}" target=_blank>izvor eventa</a>' if src.get("url") else ""
            b.append(f"<li><b>{esc(e['event'])}</b> ({esc(e['event_date'])}), pojam <code>{esc(e['keyword'])}</code>, "
                     f"{'pravi token' if e['role'] == 'canonical' else 'kopija'}, organska ocjena {e['score']:.0f}"
                     f"{', hype eventa ' + format(src['hype'], '.0f') if src.get('hype') else ''}{link}</li>")
        b.append("</ul>" + _src("event"))

    if cand:
        tr = data.paper_trades(mint)
        b.append(f"<h3>Demo trading</h3><p>{badge(cand.get('decision') or '–', 'good' if cand.get('trade_id') else '')} "
                 f"{esc(cand.get('reason') or '')}</p>"
                 + "".join(f"<p>Trejd #{t['id']}: {esc(t['status'])}, PnL {signed(t['pnl_usd'])[0]} $ "
                           f"({(t['ret'] or 0):+.0%}), izlaz {esc(t['exit_reason'] or '–')}</p>" for t in tr) + _src("paper", cand["first_ts"]))
    b.append(f"<p class=mut style='font-size:12px'>Generirano {dt.datetime.now(dt.timezone.utc):%Y-%m-%d %H:%M} UTC iz "
             "baza bota; tržište se čita uživo.</p>")
    return "".join(b)
