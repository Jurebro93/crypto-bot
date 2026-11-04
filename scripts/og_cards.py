"""Share cards (og:image / twitter:image, 1200x630) for the landing page and the main public sections, EN and HR.

ui/static/landing/og-<key>[-hr].jpg, picked in ui/public.og_card(path). Blog posts keep their own covers (scripts/blog_covers.py).
Sources: app screenshots in ui/static/landing (mob-*.jpg) and public page screenshots in scripts/og_src/.
Run from the repo root: python3 scripts/og_cards.py  (needs Node + Playwright + Chromium + the Inter font).
"""
import base64
import json
import os
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from ui.html import logo  # noqa: E402

OUT = os.path.join(ROOT, "ui", "static", "landing")
SRC = os.path.join(ROOT, "scripts", "og_src")

# key -> lang -> (headline, sub, chips, footer, images); images: [("phone"|"page", path)]
CARDS = {
    "home": {
        "en": ("Smarter entries into <em>Solana tokens.</em>",
               "Token picks, influencer scores, wallet tracking and event tokens in one app.",
               ["Token picks", "Influencer scores", "Wallet tracking", "Rug shield"], "Free for now · access on request",
               [("phone", f"{OUT}/en-mob-kol-profil.jpg"), ("phone", f"{OUT}/en-mob-tokeni.jpg")]),
        "hr": ("Pametniji ulaz u <em>Solana tokene.</em>",
               "Prijedlozi tokena, ocjena influencera, praćenje novčanika i event tokeni u jednoj aplikaciji.",
               ["Prijedlozi tokena", "Ocjena influencera", "Praćenje novčanika", "Štit od ruga"],
               "Za sada besplatno · pristup na zahtjev",
               [("phone", f"{OUT}/mob-kol-profil.jpg"), ("phone", f"{OUT}/mob-tokeni.jpg")]),
    },
    "kols": {
        "en": ("Which crypto influencers <em>actually move the price?</em>",
               "Every Solana call measured: what the price did 1 hour and 24 hours later.",
               ["Hit rate", "Rugs", "Late calls", "Rising stars"], "Free, no login",
               [("page", f"{SRC}/pub_influencers.jpg")]),
        "hr": ("Koji kripto influenceri <em>stvarno pomiču cijenu?</em>",
               "Svaki Solana poziv izmjeren: što je cijena napravila sat i dan kasnije.",
               ["Pogodak", "Rugovi", "Kasni pozivi", "Rastuće zvijezde"], "Besplatno, bez prijave",
               [("page", f"{SRC}/pub_hr_influenceri.jpg")]),
    },
    "coins": {
        "en": ("Top 100 Solana meme coins, <em>live.</em>",
               "Price, liquidity, holders and a rug check for every coin.",
               ["Top gainers", "Trending", "New coins", "How to buy"], "Free, no login",
               [("page", f"{SRC}/pub_solana_meme_coins.jpg")]),
        "hr": ("Top 100 Solana meme coina, <em>uživo.</em>",
               "Cijena, likvidnost, holderi i provjera ruga za svaki coin.",
               ["Najveći rast", "Popularni", "Novi coini", "Kako kupiti"], "Besplatno, bez prijave",
               [("page", f"{SRC}/pub_hr_solana_meme_coini.jpg")]),
    },
    "tools": {
        "en": ("The best crypto tools, <em>compared with real prices.</em>",
               "Wallet trackers, analysis, trading bots, wallets and rug checkers side by side.",
               ["Wallet trackers", "Trading bots", "Rug checkers", "APIs"], "Prices checked by date",
               [("page", f"{SRC}/pub_best_crypto_tools.jpg")]),
        "hr": ("Najbolji kripto alati, <em>usporedba s pravim cijenama.</em>",
               "Praćenje novčanika, analiza, trading botovi, novčanici i provjera ruga na jednom mjestu.",
               ["Praćenje novčanika", "Trading botovi", "Provjera ruga", "API-ji"], "Cijene provjerene s datumom",
               [("page", f"{SRC}/pub_hr_najbolji_kripto_alati.jpg")]),
    },
    "learn": {
        "en": ("Crypto, <em>in plain words.</em>",
               "Guides, a glossary and research on Solana meme coins, rugs and influencers.",
               ["Guides", "Glossary", "Rugs and scams", "Tax"], "Free to read",
               [("page", f"{SRC}/pub_glossary.jpg")]),
        "hr": ("Kripto, <em>običnim riječima.</em>",
               "Vodiči, rječnik i istraživanja o Solana meme coinima, rugovima i influencerima.",
               ["Vodiči", "Rječnik", "Rugovi i prevare", "Porez"], "Besplatno za čitanje",
               [("page", f"{SRC}/pub_hr_rjecnik.jpg")]),
    },
}

CSS = """
*{box-sizing:border-box}body{margin:0;width:1200px;height:630px;overflow:hidden;font-family:Inter,system-ui,sans-serif;
background:radial-gradient(900px 500px at 100% 0%,#eef2ff 0%,rgba(238,242,255,0) 60%),
radial-gradient(700px 500px at 70% 110%,#ecfeff 0%,rgba(236,254,255,0) 60%),#fff;color:#0b1220;position:relative}
.l{position:absolute;left:64px;top:56px;width:560px;height:518px;display:flex;flex-direction:column}
.brand{display:flex;align-items:center;gap:12px;font-weight:750;font-size:26px;letter-spacing:-.02em}
h1{font-family:"Inter Display",Inter,sans-serif;font-size:58px;line-height:1.04;letter-spacing:-.035em;margin:34px 0 18px;font-weight:800}
h1 em{font-style:normal;background:linear-gradient(90deg,#4f46e5,#0fb5a0);-webkit-background-clip:text;background-clip:text;color:transparent}
p{font-size:23px;line-height:1.4;color:#5b6474;margin:0 0 24px}
.chips{display:flex;flex-wrap:wrap;gap:10px}.chips span{border:1px solid #e3e7f0;background:#fff;border-radius:999px;padding:8px 16px;
font-size:18px;font-weight:600;color:#0b1220}
.foot{margin-top:auto;display:flex;align-items:center;gap:12px;font-size:20px;font-weight:650}
.dot{width:10px;height:10px;border-radius:50%;background:#22c55e;box-shadow:0 0 0 6px rgba(34,197,94,.18)}
.url{color:#5b6474;font-weight:550;margin-left:auto}
.page{position:absolute;left:668px;top:64px;width:620px;height:600px;border-radius:20px;overflow:hidden;background:#fff;
border:1px solid #e3e7f0;box-shadow:0 40px 80px -30px rgba(11,18,32,.35)}
.page .bar{height:34px;background:#f6f7fb;border-bottom:1px solid #e8ebf2;display:flex;align-items:center;gap:7px;padding:0 14px}
.page .bar i{width:10px;height:10px;border-radius:50%;background:#d7dce6}
.page img{width:100%;display:block}
.ph{position:absolute;width:250px;border-radius:36px;background:#0b1220;padding:8px;box-shadow:0 40px 80px -30px rgba(11,18,32,.45)}
.ph img{display:block;width:100%;border-radius:29px;aspect-ratio:390/844;object-fit:cover;object-position:top}
.ph.a{left:700px;top:96px;transform:rotate(-4deg)}.ph.b{left:900px;top:46px;transform:rotate(3deg)}
"""


def _data(path):
    with open(path, "rb") as f:
        return "data:image/jpeg;base64," + base64.b64encode(f.read()).decode()


def html(key, lang):
    h, sub, chips, foot, imgs = CARDS[key][lang]
    svg, name = logo(44)
    pics = ""
    for i, (kind, path) in enumerate(imgs):
        if kind == "phone":
            pics += f"<div class='ph {'ab'[i]}'><img src='{_data(path)}'></div>"
        else:
            pics += f"<div class=page><div class=bar><i></i><i></i><i></i></div><img src='{_data(path)}'></div>"
    return (f"<!doctype html><meta charset=utf-8><style>{CSS}</style>{pics}<div class=l>"
            f"<div class=brand>{svg}<span>{name}</span></div><h1>{h}</h1><p>{sub}</p>"
            f"<div class=chips>{''.join(f'<span>{c}</span>' for c in chips)}</div>"
            f"<div class=foot><span class=dot></span>{foot}<span class=url>memesonar.app</span></div></div>")


def main():
    tmp = tempfile.mkdtemp(prefix="og-")
    jobs = []
    for key in CARDS:
        for lang in ("en", "hr"):
            name = f"og-{key}{'' if lang == 'en' else '-hr'}.jpg"
            page = os.path.join(tmp, name + ".html")
            with open(page, "w", encoding="utf-8") as f:
                f.write(html(key, lang))
            jobs.append([page, os.path.join(OUT, name)])
    js = os.path.join(tmp, "render.js")
    with open(js, "w") as f:
        f.write("const {chromium}=require('playwright');(async()=>{const b=await chromium.launch();"
                "const p=await b.newPage({viewport:{width:1200,height:630}});for(const [h,o] of " + json.dumps(jobs) + ")"
                "{await p.goto('file://'+h);await p.waitForTimeout(300);"
                "await p.screenshot({path:o,type:'jpeg',quality:86});console.log(o)}await b.close()})();")
    subprocess.run(["node", js], check=True)


if __name__ == "__main__":
    main()
