"""Branded cover image for every blog post: one template, EN + HR, drawn as SVG (no files, no requests).

- svg(view, lang): the cover, inline in blog cards and post headers (ui/blog.py). Light landing colours, the sonar
  rings of the logo, a black pill with the post's tag and one big number from the post (COVER). The blip on the radar
  sits in a different spot for every post. A post without a COVER entry gets its title instead, so new posts have a
  cover from day one.
- og:image needs a raster image (social networks ignore SVG): `python3 scripts/blog_covers.py` renders the same SVG into
  ui/static/landing/blog-<slug>.jpg (EN) and blog-<slug>-hr.jpg (HR). Run it after adding a post or a COVER entry;
  tests/test_blogcover_offline.py fails while a JPG is missing.
"""
import hashlib
import math

from ui.html import esc, logo

W, H = 1200, 630

# Category colour: (accent, light tint of the background).
COLORS = {"guides": ("#4f46e5", "#eceeff"), "exchanges-and-cards": ("#0fb5a0", "#e3f8f3"),
          "tax-and-law": ("#d97706", "#fff3df"), "rugs-and-scams": ("#e11d48", "#ffecf0"),
          "wallets-and-influencers": ("#0891b2", "#e4f6fb"), "prediction-markets": ("#7c3aed", "#f2ecff"),
          "for-crypto-projects": ("#16a34a", "#e7f7ec")}
DEFAULT = COLORS["guides"]

# One big number per post (EN slug): (EN number, EN caption, HR number, HR caption). Same figures as in the posts.
COVER = {
    "best-crypto-telegram-channels": ("5%", "of 40,772 Telegram calls had a measured outcome",
                                      "5%", "od 40.772 Telegram poziva imalo je izmjeren ishod"),
    "top-crypto-twitter-accounts-by-call-accuracy": ("29%", "of influencer calls were up one hour later",
                                                     "29%", "poziva influencera bilo je u plusu sat kasnije"),
    "memecoin-telegram-groups-explained": ("47%", "of Telegram call posts came from alert bots",
                                           "47%", "Telegram objava poziva došlo je od alert botova"),
    "how-to-spot-a-pump-fun-runner": ("0 of 129", "fresh pump.fun launches matched the 'runner' rule",
                                      "0 od 129", "svježih pump.fun lansiranja prošlo je 'runner' pravilo"),
    "how-to-check-a-kol-track-record": ("5,192 of 6,995", "crypto accounts have no measured call",
                                        "5.192 od 6.995", "kripto računa nema nijedan izmjeren poziv"),
    "what-is-wallet-tracking": ("2 of 469", "tracked 'smart money' wallets were worth copying",
                                "2 od 469", "'smart money' novčanika vrijedilo je kopirati"),
    "what-is-copy-trading": ("22%", "of active Solana wallets were in profit",
                             "22%", "aktivnih Solana novčanika bilo je u plusu"),
    "what-is-a-kol-in-crypto": ("52% vs 14%", "of called tokens reached 2x, with vs. without a KOL call",
                                "52% : 14%", "tokena doseglo je 2x, s pozivom KOL-a i bez njega"),
    "influencer-clustering": ("59% vs 33%", "reached 2x when 3+ KOLs called within 15 minutes",
                              "59% : 33%", "doseglo je 2x kad ih je 3+ KOL-a pozvalo unutar 15 minuta"),
    "how-to-spot-a-rug-pull": ("1.4%", "of tokens from serial creators (20+ launches) reached 2x",
                               "1,4%", "tokena serijskih kreatora (20+ lansiranja) doseglo je 2x"),
    "what-is-pump-fun": ("0.8%", "of random new pump.fun tokens ever doubled",
                         "0,8%", "nasumičnih novih pump.fun tokena ikad se udvostručilo"),
    "bundles-and-snipers": ("-54%", "typical drop from the top for heavily bundled tokens",
                            "-54%", "tipičan pad s vrha za jako bundlane tokene"),
    "how-to-trade-meme-coins": ("24%", "reached 2x when bought at the first $100k market cap cross",
                                "24%", "doseglo 2x uz kupnju na prvom prelasku $100k"),
    "what-is-dca-in-crypto": ("+38% vs -10%", "DCA vs. one buy, same token, same end price",
                              "+38% : -10%", "DCA naspram jedne kupnje, isti token, ista završna cijena"),
    "market-cap-liquidity-slippage": ("-17%", "fewer tokens for a $1,000 buy in a $10k pool",
                                      "-17%", "manje tokena za kupnju od $1.000 u poolu od $10k"),
    "best-crypto-exchanges-croatia": ("5 + 9", "Croatian and EU exchanges licensed under MiCA, compared",
                                      "5 + 9", "hrvatskih i EU mjenjačnica s MiCA licencom, usporedba"),
    "how-to-buy-solana-meme-coins": ("24%", "reached 2x when bought at the first $100k market cap",
                                     "24%", "doseglo je 2x kad je kupljeno na prvih $100k tržišne kap."),
    "how-to-use-jupiter-swap": ("-17%", "price impact of a $1,000 buy in a $10k pool",
                                "-17%", "utjecaj na cijenu kupnje od $1.000 u poolu od $10k"),
    "what-is-a-pump-and-dump": ("-54%", "median fall from the top for heavily bundled tokens",
                                "-54%", "medijan pada s vrha za jako bundlane tokene"),
    "crypto-cards-croatia": ("0-2%", "cashback on free tiers; every payment is a crypto sale",
                             "0-2%", "povrata besplatno; svako plaćanje je prodaja kripta"),
    "crypto-tax-croatia": ("12%", "on gains under 2 years; swaps and 2+ years tax-free",
                           "12%", "na dobit ispod dvije godine; zamjene i 2+ godine bez poreza"),
    "why-big-influencer-calls-are-hard-to-trade": ("+44%", "your entry price after 20 bots buy $500 each",
                                                   "+44%", "tvoja ulazna cijena nakon što 20 botova kupi po $500"),
    "company-crypto-investment-croatia": ("20.8%", "total tax on a d.o.o. crypto gain paid out as a dividend",
                                          "20,8%", "ukupan porez na kripto dobit d.o.o.-a kao dividendu"),
    "address-poisoning": ("$0 transfer", "is the bait: a look-alike address lands in your history",
                          "$0 uplata", "je mamac: slična adresa sjedne u tvoju povijest"),
    "zero-trust-support-calls": ("0 calls", "real support never calls first or asks for your seed phrase",
                                 "0 poziva", "prava podrška nikad ne zove prva niti traži seed frazu"),
    "polymarket-rules-checklist": ("2+ days", "a disputed market can take this long to pay out",
                                   "2+ dana", "toliko može trajati isplata spornog tržišta"),
    "polymarket-insider-moves": ("No news", "yet the odds of an unlikely outcome jump: a typical leak",
                                 "Bez vijesti", "a kvota malo vjerojatnog ishoda skoči: tipično curenje"),
    "perps-settings-after-october-10": ("5 rules", "that decided who survived 10 October 2025",
                                        "5 pravila", "koja su odlučila tko je preživio 10. 10. 2025."),
    "tokens-sent-to-kol-wallets": ("0 SOL", "left the wallet? Then it was a gift, not a buy",
                                   "0 SOL", "izašlo iz novčanika? Onda je poklon, a ne kupnja"),
    "what-to-do-with-an-airdrop": ("~85%", "of 2025 token launches traded below their launch price",
                                   "~85%", "tokena lansiranih 2025. palo je ispod početne cijene"),
    "fake-volume-check": ("Vol ÷ Liq", "dozens of times more volume than liquidity is a red flag",
                          "Vol ÷ Lik", "desetke puta veći volumen od likvidnosti: alarm"),
    "after-kaito-yaps": ("Jan 2026", "X cut paid-posting apps off; Kaito ended Yaps",
                         "Sij. 2026", "X ugasio plaćene objave; Kaito ukinuo Yaps"),
    "fair-token-launch-cca": ("No rush", "each block has one price, so being first gives no edge",
                              "Bez žurbe", "svaki blok ima jednu cijenu, biti prvi ne pomaže"),
}


def _wrap(text, width, lines):
    """Words into at most `lines` lines of ~width characters (last line ends with … when cut)."""
    out, cur = [], ""
    for w in text.split():
        if cur and len(cur) + 1 + len(w) > width:
            out.append(cur)
            cur = w
        else:
            cur = f"{cur} {w}".strip()
    if cur:
        out.append(cur)
    if len(out) > lines:
        out = out[:lines]
        out[-1] = out[-1].rstrip(".,;:") + "…"
    return out


def _cat(en_slug):
    from ui.blog import CAT_OF
    c = CAT_OF.get(en_slug)
    return c[0] if c else None


def svg(v, lang="en", css_class="cv", decorative=False):
    """Cover of a post view (ui.blog.view) as an inline <svg> element, 1200x630, scales to its box."""
    en = v["en"]
    acc, tint = COLORS.get(_cat(en), DEFAULT)
    uid = "c" + hashlib.md5(f"{en}{lang}".encode()).hexdigest()[:7]   # unique gradient ids when many sit on one page
    seed = int(hashlib.md5(en.encode()).hexdigest()[:8], 16)
    cx, cy = 955, 315
    ang = math.radians(200 + seed % 140)                   # blip somewhere top/left of centre, own spot per post
    rb = (150, 240)[seed % 2]
    bx, by = cx + rb * math.cos(ang), cy + rb * math.sin(ang)
    a0 = ang + math.radians(4)                             # sweep wedge trailing behind the blip
    a1 = a0 + math.radians(38)
    R = 470
    wedge = (f"M{cx},{cy} L{cx + R * math.cos(a0):.0f},{cy + R * math.sin(a0):.0f} "
             f"A{R},{R} 0 0 1 {cx + R * math.cos(a1):.0f},{cy + R * math.sin(a1):.0f} Z")
    rings = "".join(f'<circle cx="{cx}" cy="{cy}" r="{r}" stroke-opacity="{o}"/>'
                    for r, o in ((70, .55), (150, .38), (240, .24), (340, .14), (450, .08)))
    mark, name = logo(48)
    mark = mark.replace('id="lgm"', f'id="{uid}m"').replace("url(#lgm)", f"url(#{uid}m)").replace(
        'width="48" height="48"', 'x="72" y="58" width="48" height="48"')
    tag = esc(v.get("tag") or "Blog")
    tw = int(len(v.get("tag") or "Blog") * 15 + 56)
    cov = COVER.get(en)
    if cov:
        big, cap = (cov[0], cov[1]) if lang == "en" else (cov[2], cov[3])
        fs = 150 if len(big) <= 6 else 118 if len(big) <= 9 else 96
        lines = _wrap(cap, 30, 2)
        text = (f'<text x="66" y="440" font-size="{fs}" font-weight="800" letter-spacing="-4" fill="#0b1220">{esc(big)}</text>'
                + "".join(f'<text x="72" y="{510 + i * 54}" font-size="43" font-weight="500" fill="#5b6474">{esc(t)}</text>'
                          for i, t in enumerate(lines)))
    else:                                                  # new post without a number yet: its title
        lines = _wrap(v.get("h1") or v.get("title") or "", 24, 3)
        text = "".join(f'<text x="70" y="{330 + i * 76}" font-size="66" font-weight="780" letter-spacing="-1.5" '
                       f'fill="#0b1220">{esc(t)}</text>' for i, t in enumerate(lines))
    aria = 'aria-hidden="true"' if decorative else f'role="img" aria-label="{esc(v.get("h1") or "")}"'
    return (f'<svg class="{css_class}" viewBox="0 0 {W} {H}" {aria} '
            f'xmlns="http://www.w3.org/2000/svg" font-family="Inter,system-ui,-apple-system,Segoe UI,Roboto,sans-serif">'
            f'<defs><linearGradient id="{uid}b" x1="1" y1="0" x2="0" y2="1"><stop offset="0" stop-color="{tint}"/>'
            f'<stop offset=".62" stop-color="#fff"/></linearGradient>'
            f'<radialGradient id="{uid}w" cx="{cx}" cy="{cy}" r="{R}" gradientUnits="userSpaceOnUse">'
            f'<stop offset="0" stop-color="{acc}" stop-opacity=".22"/><stop offset="1" stop-color="{acc}" stop-opacity="0"/>'
            f'</radialGradient></defs>'
            f'<rect width="{W}" height="{H}" fill="url(#{uid}b)"/>'
            f'<path d="{wedge}" fill="url(#{uid}w)"/>'
            f'<g fill="none" stroke="{acc}" stroke-width="3">{rings}</g>'
            f'<circle cx="{cx}" cy="{cy}" r="16" fill="{acc}"/><circle cx="{cx}" cy="{cy}" r="6" fill="#fff"/>'
            f'<circle cx="{bx:.0f}" cy="{by:.0f}" r="28" fill="#34d399" fill-opacity=".18"/>'
            f'<circle cx="{bx:.0f}" cy="{by:.0f}" r="13" fill="#10b981"/>'
            f'{mark}<text x="134" y="94" font-size="30" font-weight="750" letter-spacing="-.5" fill="#0b1220">{esc(name)}</text>'
            f'<rect x="72" y="146" width="{tw}" height="52" rx="26" fill="#0b1220"/>'
            f'<text x="{72 + tw / 2:.0f}" y="181" font-size="26" font-weight="650" fill="#fff" text-anchor="middle">{tag}</text>'
            f'{text}</svg>')
