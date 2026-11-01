"""Public front page for visitors who are not logged in ("/" and /dobrodosli), plus access requests.

- page_html(): sales page in plain Croatian: invite only, live numbers from the databases, real screenshots of the app
  (ui/static/landing/*.jpg, player names replaced), "Zatraži pristup" form and the login button.
- Live numbers are counted in a background thread (start(), every STATS_EVERY_S) with cheap queries only
  (MAX(rowid) for the big tables), so a visitor never waits for a database and the bot's writers are never slowed.
- Access requests: league.db table access_requests (the dashboard process is league.db's only writer). /zahtjevi lists
  them for players who may invite (ui/register.can_invite); "Pozovi" makes a single-use invite link
  (league/members.single) for that person, ready to copy or send on WhatsApp / e-mail.
"""
import os
import re
import sqlite3
import threading
import time
from urllib.parse import quote

from ui.html import ago, esc, logo
from ui import favicon as _fav  # noqa: E402

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATIC = os.path.join(HERE, "ui", "static", "landing")
STATS_EVERY_S = int(os.environ.get("LANDING_STATS_EVERY_S", "1800"))
MAX_PENDING = 500            # a bot filling the form cannot fill the disk
PER_IP_HOUR = 5

SCHEMA = """
CREATE TABLE IF NOT EXISTS access_requests (
    id INTEGER PRIMARY KEY AUTOINCREMENT, ts INTEGER, name TEXT, contact TEXT, experience TEXT, interest TEXT,
    source TEXT, ip TEXT, status TEXT DEFAULT 'novi', handled_by TEXT, handled_ts INTEGER, invite TEXT);
"""

_STATS = {"ts": 0, "v": {}}
_LOCK = threading.Lock()
_IPS = {}   # ip -> [ts, ...] of recent requests (in memory: enough against a form-filling bot)


# ---------- live numbers ------------------------------------------------------------------------------------------

def _db(name):
    return os.path.join(HERE, name)


def _one(path, sql, args=()):
    """First column of the first row, or None (missing file/table, locked, anything)."""
    if not os.path.exists(path) or not os.path.getsize(path):
        return None
    try:
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5)
    except sqlite3.Error:
        return None
    try:
        r = con.execute(sql, args).fetchone()
        return r[0] if r else None
    except sqlite3.Error:
        return None
    finally:
        con.close()


def compute():
    """Every number on the page, from the live databases. Missing ones are simply left out."""
    v = {}
    hype, wal, kol, tg, dugo, paper = (_db(n) for n in ("hype.db", "wallets.db", "kol.db", "tg.db", "dugo.db", "paper.db"))
    v["tokens"] = (_one(hype, "SELECT COUNT(*) FROM token_tier") or 0) + (_one(hype, "SELECT COUNT(*) FROM rug_archive") or 0)
    v["rugs"] = _one(hype, "SELECT COUNT(*) FROM rug_archive")
    v["scans"] = _one(hype, "SELECT MAX(rowid) FROM hype_signals")
    v["wallets"] = _one(wal, "SELECT COUNT(*) FROM wallets")
    v["wallet_trades"] = _one(wal, "SELECT MAX(rowid) FROM wallet_trades")
    v["kols"] = _one(kol, "SELECT COUNT(*) FROM kols")
    v["calls"] = _one(kol, "SELECT COUNT(*) FROM calls WHERE kind='call'")
    v["kol_wallets"] = _one(kol, "SELECT COUNT(*) FROM kol_wallets")
    v["snaps"] = _one(kol, "SELECT MAX(rowid) FROM snaps")
    v["channels"] = _one(tg, "SELECT COUNT(*) FROM channels WHERE status IN ('active','quiet','slow')")
    v["dugo"] = _one(dugo, "SELECT COUNT(*) FROM tokens")
    v["demo_trades"] = _one(paper, "SELECT COUNT(*) FROM trades")
    # what happens after an influencer call: share of measured calls whose token at least doubled in 24 h
    if os.path.exists(kol) and os.path.getsize(kol):
        try:
            con = sqlite3.connect(f"file:{kol}?mode=ro", uri=True, timeout=5)
            try:
                r = con.execute("SELECT COUNT(*), SUM(max24 >= 1.0), SUM(max24 >= 0.5) FROM calls "
                                "WHERE kind='call' AND max24 IS NOT NULL").fetchone()
                if r and r[0]:
                    v["measured"], v["call_2x"], v["call_50"] = r[0], (r[1] or 0) / r[0], (r[2] or 0) / r[0]
            finally:
                con.close()
        except sqlite3.Error:
            pass
    try:
        from ourtoken import advisor
        lift = advisor.cocall_lift()
        if lift:
            v["group_rate"], v["solo_rate"], v["group_n"] = lift["group_rate"], lift["solo_rate"], lift["group_n"]
    except Exception:  # noqa: BLE001
        pass
    try:
        from league import store
        v["players"] = len(store.users())
    except Exception:  # noqa: BLE001
        pass
    return {k: x for k, x in v.items() if x}


def _refresh():
    try:
        val = compute()
    except Exception:  # noqa: BLE001
        val = None
    with _LOCK:
        if val:
            _STATS["v"] = val
        _STATS["ts"] = time.time()
        _STATS["busy"] = False


def stats():
    """Latest numbers (possibly empty right after a restart); starts a recount in the background when stale."""
    with _LOCK:
        stale = time.time() - _STATS["ts"] > STATS_EVERY_S and not _STATS.get("busy")
        if stale:
            _STATS["busy"] = True
        v, ts = dict(_STATS["v"]), _STATS["ts"]
    if stale:
        threading.Thread(target=_refresh, daemon=True, name="landing-stats").start()
    return v, ts


def start():
    """Count once soon after boot (the boot itself is busy) and keep the numbers fresh."""
    def loop():
        time.sleep(int(os.environ.get("LANDING_STATS_DELAY_S", "45")))
        while True:
            with _LOCK:
                _STATS["busy"] = True
            _refresh()
            time.sleep(STATS_EVERY_S)
    threading.Thread(target=loop, daemon=True, name="landing-stats-loop").start()


# ---------- formatting ---------------------------------------------------------------------------------------------

def _n(x):
    """12,345 -> '12.345' (Croatian grouping); big numbers rounded: 1,234,567 -> '1,2 mil.'."""
    if x is None:
        return "–"
    x = float(x)
    if x >= 1_000_000:
        return f"{x / 1_000_000:.1f}".replace(".", ",") + " mil."
    return f"{x:,.0f}".replace(",", ".")


def _pct(x):
    return f"{x * 100:.0f}%"


# ---------- page ---------------------------------------------------------------------------------------------------

SHOTS = {   # file -> alt text
    "mob-pregled.jpg": "Radar: najjači tokeni upravo sada, na mobitelu",
    "mob-kol.jpg": "Ocjena influencera na mobitelu",
    "mobitel.jpg": "Liga tradera na mobitelu",
    "pregled.jpg": "Radar novih tokena: istaknuti kandidati sa Šansom za skok",
    "kol.jpg": "Ocjena influencera: moć poziva, pogodak, rugovi",
    "moc-poziva.jpg": "Koliko tržište sluša influencera",
    "copy.jpg": "Kopiraj najbolje: uđi na sljedeći call influencera",
    "natjecanje.jpg": "Liga tradera: ljestvica s demo računima",
    "token.jpg": "Analiza tokena običnim riječima",
    "dugorocni.jpg": "Jaki tokeni koji traju",
    "korelacije.jpg": "Tko radi zajedno, AI sažetak",
}

FEATURES = [
    ("📡", "Radar novih tokena", "Svake 2 minute pregleda nove Solana tokene i pokaže samo one s najvećom šansom."),
    ("📣", "Ocjena influencera", "Za svaki poziv izmjerimo što je cijena napravila. Vidiš tko pomiče tržište, a tko samo viče."),
    ("🔁", "Kopiraj najbolje", "Odaberi influencera ili novčanik. Alat ulazi i izlazi kad i on, i noću."),
    ("🛡", "Štit od ruga", "Lažni poolovi, povučena likvidnost i dev koji prodaje odbačeni su prije nego ih vidiš."),
    ("🌱", "Jaki tokeni", "Tokeni koji su preživjeli tjednima i imaju stalan volumen, za mirniji dio portfelja."),
    ("🏆", "Liga tradera", "Demo račun od $1.000, žive cijene i ljestvica s prijateljima. Bez pravog novca."),
]

GALLERY = [("pregled.jpg", "Radar novih tokena"), ("kol.jpg", "Ocjena influencera"),
           ("copy.jpg", "Kopiraj najbolje"), ("natjecanje.jpg", "Liga tradera"), ("token.jpg", "Analiza tokena")]

CSS = """
:root{--bg:#fff;--soft:#f6f7fb;--fg:#0b1220;--mut:#5b6474;--line:#e8ebf2;--acc:#4f46e5;--acc2:#0fb5a0;--good:#16a34a}
*{box-sizing:border-box}html{scroll-behavior:smooth}
body{margin:0;background:var(--bg);color:var(--fg);font:17px/1.6 Inter,system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;
-webkit-font-smoothing:antialiased}
a{color:inherit;text-decoration:none}img{max-width:100%;display:block}
.w{max-width:1080px;margin:0 auto;padding:0 20px}
nav{position:sticky;top:0;z-index:20;background:rgba(255,255,255,.85);backdrop-filter:blur(12px);border-bottom:1px solid transparent}
nav.s{border-bottom-color:var(--line)}
nav .w{display:flex;align-items:center;gap:18px;height:64px}
.brand{display:flex;align-items:center;gap:9px;font-weight:750;font-size:18px;letter-spacing:-.02em}.sp{flex:1}
.lnk{color:var(--mut);font-size:15px;font-weight:500}.lnk:hover{color:var(--fg)}
.btn{display:inline-flex;align-items:center;justify-content:center;border-radius:999px;padding:14px 26px;font-weight:650;font-size:16px;
border:1px solid transparent;cursor:pointer;font-family:inherit;transition:transform .15s,box-shadow .15s,background .15s}
.btn:active{transform:scale(.98)}
.btn.p{background:var(--fg);color:#fff}.btn.p:hover{background:#1f2937;box-shadow:0 10px 30px -10px rgba(11,18,32,.5)}
.btn.g{background:#fff;border-color:var(--line);color:var(--fg)}.btn.g:hover{border-color:#cfd5e1}
.btn.sm{padding:9px 18px;font-size:14px}
.hero{text-align:center;padding:84px 0 24px}
.pill{display:inline-flex;align-items:center;gap:8px;background:var(--soft);border:1px solid var(--line);border-radius:999px;padding:6px 14px;
font-size:14px;color:var(--mut);font-weight:500}
.dot{width:7px;height:7px;border-radius:50%;background:var(--good)}
h1{font-size:clamp(38px,7vw,68px);line-height:1.04;letter-spacing:-.04em;margin:22px auto 18px;font-weight:800;max-width:820px}
.g{background:linear-gradient(90deg,var(--acc),var(--acc2));-webkit-background-clip:text;background-clip:text;color:transparent}
.sub{font-size:clamp(17px,2.2vw,20px);color:var(--mut);max-width:600px;margin:0 auto 32px}
.ctas{display:flex;gap:10px;justify-content:center;flex-wrap:wrap}
.small{color:var(--mut);font-size:14px;margin-top:16px}
.phones{display:flex;justify-content:center;align-items:flex-end;gap:22px;margin:64px auto 0;padding:0 0 10px}
.ph{width:250px;flex:none;border-radius:34px;background:#0b1220;padding:8px;box-shadow:0 40px 80px -30px rgba(11,18,32,.35)}
.ph img{border-radius:27px;width:100%;aspect-ratio:390/780;object-fit:cover;object-position:top}
.ph.side{width:215px;opacity:.95}@media(min-width:761px){.ph.main{order:2}.ph.side+.ph.side{order:3}}
@media(max-width:760px){.phones{justify-content:flex-start;overflow-x:auto;scroll-snap-type:x mandatory;padding:0 20px 20px;margin:48px -20px 0;
gap:14px;scrollbar-width:none}.phones::-webkit-scrollbar{display:none}.ph,.ph.side{width:72vw;scroll-snap-align:center}}
section{padding:88px 0}.soft{background:var(--soft)}
.eyebrow{color:var(--acc);font-weight:650;font-size:14px;margin-bottom:10px}
h2{font-size:clamp(28px,4.5vw,44px);letter-spacing:-.035em;line-height:1.1;margin:0 0 14px;font-weight:780}
.lead{color:var(--mut);font-size:18px;max-width:600px;margin:0 0 40px}
.center{text-align:center}.center .lead{margin-left:auto;margin-right:auto}
.nums{display:grid;grid-template-columns:repeat(var(--n,4),1fr);gap:0;border-top:1px solid var(--line);border-bottom:1px solid var(--line)}
.num{padding:30px 18px;text-align:center}.num+.num{border-left:1px solid var(--line)}
.num b{display:block;font-size:clamp(28px,4vw,40px);letter-spacing:-.03em;font-weight:780;font-variant-numeric:tabular-nums}
.num span{color:var(--mut);font-size:14px}
@media(max-width:760px){.num{padding:22px 4px}.num b{font-size:24px}.num span{font-size:12px;line-height:1.3;display:block}}
.live{display:flex;justify-content:center;align-items:center;gap:8px;color:var(--mut);font-size:13px;margin-top:14px}
.feats{display:grid;grid-template-columns:repeat(3,1fr);gap:18px}@media(max-width:900px){.feats{grid-template-columns:1fr 1fr}}
@media(max-width:600px){.feats{grid-template-columns:1fr;gap:10px}.f{display:grid;grid-template-columns:46px 1fr;gap:4px 16px;padding:18px;border-radius:18px}.f .i{grid-row:span 2}.f h3{margin:2px 0 0;font-size:17px}.f p{font-size:15px}}
.f{background:#fff;border:1px solid var(--line);border-radius:22px;padding:26px}
.f .i{width:46px;height:46px;border-radius:14px;background:var(--soft);display:flex;align-items:center;justify-content:center;font-size:22px}
.f h3{font-size:19px;letter-spacing:-.02em;margin:18px 0 6px}.f p{margin:0;color:var(--mut);font-size:15.5px}
.hl{display:grid;grid-template-columns:auto 1fr;gap:40px;align-items:center;background:var(--fg);color:#fff;border-radius:28px;padding:48px}
.hl .big{font-size:clamp(64px,11vw,120px);font-weight:820;letter-spacing:-.05em;line-height:1}
.hl .big .g{background:linear-gradient(90deg,#a5b4fc,#5eead4);-webkit-background-clip:text;background-clip:text}
.hl h3{font-size:clamp(22px,3vw,30px);letter-spacing:-.025em;margin:0 0 10px;line-height:1.2}.hl p{margin:0;color:#aab3c5}
.bars{margin-top:22px;display:grid;gap:10px;max-width:420px}.bar{display:grid;grid-template-columns:1fr 54px;gap:12px;align-items:center;font-size:14px;color:#cbd2df}
.bar i{display:block;height:8px;border-radius:8px;background:#26314a;overflow:hidden}.bar i em{display:block;height:100%;border-radius:8px}
.bar b{color:#fff;text-align:right}
@media(max-width:760px){.hl{grid-template-columns:1fr;gap:18px;padding:32px 24px;border-radius:24px}}
.gal{display:flex;gap:18px;overflow-x:auto;scroll-snap-type:x mandatory;padding:4px 20px 20px;margin:0 -20px;scrollbar-width:thin}
.gal figure{margin:0;flex:none;width:min(820px,86vw);scroll-snap-align:center}
.gal img{border-radius:18px;border:1px solid var(--line);box-shadow:0 20px 50px -25px rgba(11,18,32,.25);cursor:zoom-in;background:#fff}
.gal figcaption{color:var(--mut);font-size:14px;margin-top:10px;font-weight:500}
.req{max-width:520px;margin:0 auto}
form.rq{background:#fff;border:1px solid var(--line);border-radius:24px;padding:28px;text-align:left;box-shadow:0 30px 60px -40px rgba(11,18,32,.25)}
form.rq label{display:block;font-weight:600;font-size:14px;margin:0 0 16px}
form.rq input,form.rq select{width:100%;margin-top:6px;background:var(--soft);color:var(--fg);border:1px solid var(--line);border-radius:14px;
padding:14px 16px;font:inherit;font-size:16px;-webkit-appearance:none;appearance:none}
form.rq input:focus,form.rq select:focus{outline:none;border-color:var(--acc);background:#fff;box-shadow:0 0 0 4px rgba(79,70,229,.12)}
form.rq .btn{width:100%;margin-top:6px}form.rq .hp{position:absolute;left:-9999px;width:1px;height:1px;overflow:hidden}
.fine{color:var(--mut);font-size:13px;margin:14px 0 0;text-align:center}
.ok{background:#ecfdf5;border:1px solid #a7f3d0;color:#065f46;border-radius:16px;padding:16px;margin-bottom:16px}
.err{background:#fef2f2;border:1px solid #fecaca;color:#991b1b;border-radius:16px;padding:14px;margin-bottom:16px}
.faq{max-width:680px;margin:0 auto}details{border-bottom:1px solid var(--line);padding:20px 0}
summary{cursor:pointer;font-weight:620;list-style:none;display:flex;justify-content:space-between;gap:16px}
summary::-webkit-details-marker{display:none}summary:after{content:"+";color:var(--mut);font-size:22px;line-height:1}
details[open] summary:after{content:"–"}details p{color:var(--mut);margin:10px 0 0}
footer{padding:36px 0 48px;color:var(--mut);font-size:13px;text-align:center;border-top:1px solid var(--line)}
dialog#lb{border:0;padding:0;background:transparent;max-width:96vw;max-height:94vh}dialog#lb::backdrop{background:rgba(11,18,32,.8)}
dialog#lb img{max-width:96vw;max-height:94vh;border-radius:12px}
.mcta{position:fixed;left:14px;right:14px;bottom:14px;z-index:30;display:none;transition:opacity .2s,transform .2s}
.mcta.h{opacity:0;transform:translateY(20px);pointer-events:none}
@media(max-width:760px){.gsec{display:none}body{font-size:16px}.hero{padding:56px 0 8px}section{padding:64px 0}.hm{display:none}.mcta{display:flex}
.mcta .btn{flex:1;box-shadow:0 12px 30px -10px rgba(11,18,32,.5)}footer{padding-bottom:100px}nav .btn.p{display:none}}
"""

JS = """
const lb=document.getElementById('lb');document.querySelectorAll('img[data-zoom]').forEach(i=>i.onclick=()=>{
 lb.querySelector('img').src=i.src;lb.querySelector('img').alt=i.alt;lb.showModal()});lb.onclick=()=>lb.close();
const nav=document.querySelector('nav'),cta=document.querySelector('.mcta'),form=document.getElementById('pristup');
const tick=()=>{nav.classList.toggle('s',scrollY>8);const r=form.getBoundingClientRect();
 cta.classList.toggle('h',scrollY<300||(r.top<innerHeight&&r.bottom>0))};addEventListener('scroll',tick,{passive:true});tick();
"""


def _img(name, eager=False):
    return (f'<img src="/static/landing/{name}" alt="{esc(SHOTS.get(name, ""))}" '
            f'{"" if eager else "loading=lazy "}decoding=async>')


FEATURES_EN = [
    ("📡", "New token radar", "Scans new Solana tokens every 2 minutes and shows only the ones with the best odds."),
    ("📣", "Influencer scores", "We measure what the price did after every call. See who moves the market and who just shouts."),
    ("🔁", "Copy the best", "Pick an influencer or a wallet. The tool buys and sells when they do, even at night."),
    ("🛡", "Rug shield", "Fake pools, pulled liquidity and selling devs are filtered out before you ever see them."),
    ("🌱", "Strong tokens", "Tokens that survived for weeks with steady volume, for the calmer part of your portfolio."),
    ("🏆", "Trader league", "A $1,000 demo account, live prices and a leaderboard with friends. No real money."),
]
GALLERY_EN = [("pregled.jpg", "New token radar"), ("kol.jpg", "Influencer scores"), ("copy.jpg", "Copy the best"),
              ("natjecanje.jpg", "Trader league"), ("token.jpg", "Token analysis")]

T = {
    "hr": dict(
        title="MemeSonar · pametniji ulaz u Solana tokene",
        desc="Radar novih Solana tokena, ocjena influencera, kopiranje najboljih i liga tradera. Samo na pozivnicu.",
        pill="Samo na pozivnicu", h1a="Pametniji ulaz u", h1b="Solana tokene.",
        sub="MemeSonar prati nove tokene, influencere i pametne novčanike i pokaže ti samo ono što ima smisla.",
        req="Zatraži pristup", login="Prijava", app="Otvori aplikaciju", nav_feat="Funkcije", nav_inf="Influenceri", ex_eye="Istraži besplatno", ex_h="Javni podaci MemeSonara",
        n_tokens="tokena provjereno", n_wallets="novčanika praćeno", n_kols="influencera ocijenjeno",
        n_calls="poziva izmjereno", live="Uživo iz baze · osvježeno", feat_eye="Funkcije", feat_h="Sve bitno, ništa viška.",
        feat_lead="Šest alata koji rade 24/7, da ti ne moraš.",
        pw_h="Veća šansa za udvostručenje kad token zove 3+ influencera u 15 minuta.",
        pw_p="Alat to vidi u trenutku i javi ti, prije nego cijena ode.", pw_m="Izmjereno na {n} poziva.",
        pw_a="3+ influencera", pw_b="1 ili 2 influencera",
        inf_eye="Javno", inf_h="Ljestvica influencera.", inf_p="Pogledaj kako su prošli pozivi najpoznatijih "
        "crypto influencera na Solani. Besplatno, bez prijave.", inf_btn="Otvori ljestvicu",
        gal_eye="Iznutra", gal_h="Pogledaj kako izgleda.", gal_p="Prave slike iz aplikacije. Povuci lijevo za još.",
        rq_eye="Samo na pozivnicu", rq_h="Zatraži svoje mjesto.",
        rq_p="Mjesta puštamo postupno. Ostavi kontakt i javimo ti se s osobnim linkom.",
        f_name="Ime", f_ph_name="Marko", f_contact="E-mail, mobitel ili Telegram", f_ph_contact="marko@mail.com",
        f_exp="Koliko tradaš?", f_opts=("Odaberi", "Tek počinjem", "Povremeno", "Aktivno", "Svaki dan"),
        f_fine="Bez novca, kartice i seed fraze. Kontakt koristimo samo za pozivnicu.",
        f_ok="<b>Zahtjev je poslan.</b> Javit ćemo ti se s osobnim linkom za registraciju.",
        faq_h="Pitanja", faq=[
            ("Trebam li pravi novac?", "Ne. Dobiješ demo račun od $1.000 i trguješ po živim cijenama. Ako kasnije želiš "
             "pravi novac, to radiš u svom novčaniku, a alat ti samo da adresu tokena."),
            ("Je li ovo financijski savjet?", "Nije. Alat mjeri i pokazuje podatke. Memecoini su vrlo rizični i odluka je "
             "uvijek tvoja."),
            ("Koliko košta?", "Za pozvane je trenutno besplatno."),
            ("Radi li na mobitelu?", "Da. Otvoriš link, prijaviš se jednom i alat te pamti 60 dana.")],
        foot="Nije financijski savjet. Kripto nosi visok rizik.", feats=FEATURES, gallery=GALLERY,
        fallback=[("2 min", "novi sken"), ("24/7", "radi bez pauze"), ("7", "slojeva provjere"), ("0 €", "za pozvane")]),
    "en": dict(
        title="MemeSonar · smarter entries into Solana tokens",
        desc="New Solana token radar, influencer call scores, copy trading and a trader league. Invite only.",
        pill="Invite only", h1a="Smarter entries into", h1b="Solana tokens.",
        sub="MemeSonar tracks new tokens, influencers and smart wallets, and shows you only what makes sense.",
        req="Request access", login="Log in", app="Open the app", nav_feat="Features", nav_inf="Influencers", ex_eye="Explore for free", ex_h="Public MemeSonar data",
        n_tokens="tokens checked", n_wallets="wallets tracked", n_kols="influencers scored", n_calls="calls measured",
        live="Live from the database · updated", feat_eye="Features", feat_h="Everything that matters. Nothing else.",
        feat_lead="Six tools working 24/7, so you don't have to.",
        pw_h="Higher chance of a 2× when 3+ influencers call a token within 15 minutes.",
        pw_p="The tool sees it the moment it happens and tells you, before the price runs.", pw_m="Measured on {n} calls.",
        pw_a="3+ influencers", pw_b="1 or 2 influencers",
        inf_eye="Public", inf_h="Influencer leaderboard.", inf_p="See how the calls of well-known Solana crypto "
        "influencers actually played out. Free, no login.", inf_btn="Open the leaderboard",
        gal_eye="Inside", gal_h="See what it looks like.", gal_p="Real screenshots from the app. Swipe for more.",
        rq_eye="Invite only", rq_h="Request your spot.",
        rq_p="We open spots gradually. Leave your contact and we'll send you a personal invite link.",
        f_name="Name", f_ph_name="Alex", f_contact="E-mail, phone or Telegram", f_ph_contact="alex@mail.com",
        f_exp="How often do you trade?", f_opts=("Choose", "Just starting", "Now and then", "Actively", "Every day"),
        f_fine="No money, no card, no seed phrase. We use your contact only to send the invite.",
        f_ok="<b>Request sent.</b> We'll get back to you with a personal sign-up link.",
        faq_h="Questions", faq=[
            ("Do I need real money?", "No. You get a $1,000 demo account and trade at live prices. If you later want to "
             "use real money, you do it in your own wallet; the tool only gives you the token address."),
            ("Is this financial advice?", "No. The tool measures and shows data. Memecoins are very risky and the "
             "decision is always yours."),
            ("How much does it cost?", "It's currently free for invited members."),
            ("Does it work on my phone?", "Yes. Open the link, log in once and the app remembers you for 60 days.")],
        foot="Not financial advice. Crypto carries a high risk.", feats=FEATURES_EN, gallery=GALLERY_EN,
        fallback=[("2 min", "new scan"), ("24/7", "always on"), ("7", "layers of checks"), ("$0", "for members")]),
}


def page_html(qs=None, logged_in=False, ok=False, err="", form=None, lang="hr"):
    qs = qs or {}
    form = form or {}
    from ui import public as P
    from ui import sitenav as SN
    lang = "en" if lang == "en" else "hr"
    t = T[lang]
    en = lang == "en"
    home = "/" if en else "/hr"
    v, ts = stats()
    svg, name = logo(30)
    base = os.environ.get("RENDER_EXTERNAL_URL", "").rstrip("/")
    from ui import urls
    app_href, app_label = (urls.app_link("/"), t["app"]) if logged_in else (urls.app_link("/prijava"), t["login"])
    num = _n_en if en else _n

    nums = [(v.get(k), t["n_" + k]) for k in ("tokens", "wallets", "kols", "calls")]
    nums = [(x, lab) for x, lab in nums if x]
    nums = [(num(x), lab) for x, lab in nums] if len(nums) >= 2 else t["fallback"]
    nums_html = (f"<div class=nums style='--n:{min(4, len(nums))}'>"
                 + "".join(f"<div class=num><b>{x}</b><span>{lab}</span></div>" for x, lab in nums[:4]) + "</div>")
    if ts and v:
        age = ago(ts)[0]
        if en:
            age = age.replace("prije ", "").replace(" min", " min ago").replace(" h", " h ago").replace(" d", " d ago")
        nums_html += f"<div class=live><span class=dot></span>{t['live']} {age}</div>"

    g, s = v.get("group_rate") or .57, v.get("solo_rate") or .33
    measured = (" " + t["pw_m"].format(n=num(v["measured"]))) if v.get("measured") else ""
    power = (f"<div class=hl><div class=big><span class=g>{g / s:.1f}×</span></div><div>"
             f"<h3>{t['pw_h']}</h3><p>{t['pw_p']}{measured}</p><div class=bars>"
             f"<div class=bar><div>{t['pw_a']}<i><em style='width:{min(100, g * 100):.0f}%;"
             f"background:linear-gradient(90deg,#818cf8,#2dd4bf)'></em></i></div><b>{_pct(g)}</b></div>"
             f"<div class=bar><div>{t['pw_b']}<i><em style='width:{min(100, s * 100):.0f}%;background:#56627d'>"
             f"</em></i></div><b>{_pct(s)}</b></div></div></div></div>")

    feats = "".join(f"<div class=f><div class=i>{i}</div><h3>{a}</h3><p>{d}</p></div>" for i, a, d in t["feats"])
    gal = "".join(f"<figure><img src=\"/static/landing/{f}\" alt=\"{esc(c)}\" data-zoom loading=lazy "
                  f"decoding=async><figcaption>{esc(c)}</figcaption></figure>" for f, c in t["gallery"])
    inf_href = "/influencers" if en else "/hr/influenceri"

    msg = f"<div class=ok>{t['f_ok']}</div>" if ok else (f"<div class=err>{esc(err)}</div>" if err else "")
    fv = {k: esc(form.get(k, "")) for k in ("name", "contact")}
    exp = form.get("experience", "")
    opts = "".join(f"<option value=\"{val}\"{' selected' if exp == val else ''}>{lab}</option>"
                   for val, lab in zip(("", "pocetnik", "povremeno", "aktivno", "profi"), t["f_opts"]))
    request_form = (
        f"<form class=rq method=post action=/zatrazi-pristup id=forma>{msg}"
        f"<input type=hidden name=lang value={'en' if en else 'hr'}>"
        f"<label>{t['f_name']}<input name=name required maxlength=40 autocomplete=name value=\"{fv['name']}\" "
        f"placeholder='{t['f_ph_name']}'></label>"
        f"<label>{t['f_contact']}<input name=contact required maxlength=120 value=\"{fv['contact']}\" "
        f"placeholder='{t['f_ph_contact']}'></label>"
        f"<label>{t['f_exp']}<select name=experience>{opts}</select></label>"
        "<div class=hp aria-hidden=true><label>Web<input name=web tabindex=-1 autocomplete=off></label></div>"
        f"<input type=hidden name=src value=\"{esc(qs.get('src', qs.get('utm_source', ''))[:40])}\">"
        f"<button class='btn p' type=submit>{t['req']}</button><p class=fine>{t['f_fine']}</p></form>")
    faq = "".join(f"<details><summary>{q}</summary><p>{a}</p></details>" for q, a in t["faq"])

    og_img = f"{base}/static/landing/pregled.jpg"
    canon = f"{base}{home}"
    switch = (f"<a class=lnk href=/hr hreflang=hr lang=hr>HR</a>" if en else
              f"<a class=lnk href=/ hreflang=en lang=en>EN</a>")
    return f"""<!doctype html><html lang={'en' if en else 'hr'}><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1,viewport-fit=cover"><title>{esc(t['title'])}</title>
<meta name=description content="{esc(t['desc'])}"><link rel=canonical href="{canon}">
<link rel=alternate hreflang=en href="{base}/"><link rel=alternate hreflang=hr href="{base}/hr">
<link rel=alternate hreflang=x-default href="{base}/">
<meta property="og:type" content="website"><meta property="og:title" content="{esc(t['title'])}">
<meta property="og:description" content="{esc(t['desc'])}"><meta property="og:image" content="{esc(og_img)}">
<meta property="og:url" content="{canon}"><meta name="twitter:card" content="summary_large_image">
<meta name=theme-color content="#ffffff">{_fav.HEAD}
<script type="application/ld+json">{{"@context":"https://schema.org","@type":"WebApplication","name":"{esc(name)}",
"url":"{canon}","applicationCategory":"FinanceApplication","operatingSystem":"Web","description":"{esc(t['desc'])}",
"offers":{{"@type":"Offer","price":"0","priceCurrency":"USD"}}}}</script>
<style>{CSS}{P._nav_css()}</style></head><body>
<nav><div class=w><a class=brand href={home}>{svg}<span>{esc(name)}</span></a><span class=sp></span>
{P.nav_links(lang)}{switch}
<a class=lnk href={app_href}>{app_label}</a><a class='btn p sm' href=#pristup>{t['req']}</a>{P.mobile_menu(lang)}</div></nav>

<header class=hero><div class=w>
<span class=pill><span class=dot></span>{t['pill']}</span>
<h1>{t['h1a']} <span class=g>{t['h1b']}</span></h1>
<p class=sub>{t['sub']}</p>
<div class=ctas><a class='btn p' href=#pristup>{t['req']}</a><a class='btn g' href={app_href}>{app_label}</a></div>
<div class=phones><div class='ph main'>{_img("mob-pregled.jpg", True)}</div><div class='ph side'>{_img("mob-kol.jpg", True)}</div>
<div class='ph side'>{_img("mobitel.jpg", True)}</div></div>
</div></header>

<section style='padding-top:40px'><div class=w>{nums_html}</div></section>

<section class=soft id=funkcije><div class=w><div class=center><div class=eyebrow>{t['feat_eye']}</div>
<h2>{t['feat_h']}</h2><p class=lead>{t['feat_lead']}</p></div>
<div class=feats>{feats}</div></div></section>

<section id=moc><div class=w>{power}</div></section>

<section style='padding-top:0'><div class='w center'><div class=eyebrow>{t['inf_eye']}</div><h2>{t['inf_h']}</h2>
<p class=lead>{t['inf_p']}</p><a class='btn g' href={inf_href}>{t['inf_btn']} →</a></div></section>

<section style='padding-top:0'><div class=w><div class=eyebrow>{t['ex_eye']}</div><h2>{t['ex_h']}</h2>
{P.explore(lang)}</div></section>

<section style='padding-top:0'><div class=w>{SN.coin_board(lang)}</div></section>

<section class='soft gsec' style='padding-bottom:64px'><div class=w><div class=eyebrow>{t['gal_eye']}</div>
<h2>{t['gal_h']}</h2><p class=lead>{t['gal_p']}</p><div class=gal>{gal}</div></div></section>

<section id=pristup><div class='w center'><div class=eyebrow>{t['rq_eye']}</div><h2>{t['rq_h']}</h2>
<p class=lead>{t['rq_p']}</p><div class=req>{request_form}</div></div></section>

<section class=soft><div class=w><div class=faq><h2 class=center style='margin-bottom:24px'>{t['faq_h']}</h2>
{faq}</div></div></section>

<footer><div class=w>{P._foot_links(lang)}<p style='margin:0 0 10px'>{switch.replace("class=lnk ", "")}</p>
© {time.gmtime().tm_year} {esc(name)} · {t['foot']}</div></footer>
<div class='mcta h'><a class='btn p' href=#pristup>{t['req']}</a></div>
<dialog id=lb><img alt=""></dialog><script>{JS}</script>{P._ga_tag(lang)}</body></html>"""


def _n_en(x):
    if x is None:
        return "–"
    x = float(x)
    if x >= 1_000_000:
        return f"{x / 1_000_000:.1f}M"
    return f"{x:,.0f}"



# ---------- access requests ----------------------------------------------------------------------------------------

def _con():
    from league import store
    con = store.connect()
    con.executescript(SCHEMA)
    return con


ERR_EN = {
    "Upiši ime ili nadimak.": "Please enter your name.",
    "Upiši kontakt: e-mail, broj mobitela ili Telegram @ime.": "Please enter a contact: e-mail, phone or Telegram @name.",
    "Previše zahtjeva s ove adrese. Pokušaj ponovno za sat vremena.": "Too many requests from this address. Try again in an hour.",
    "Lista čekanja je trenutno puna. Pokušaj ponovno za par dana.": "The waiting list is full right now. Try again in a few days.",
    "Zahtjev trenutno nije moguće spremiti. Pokušaj ponovno za par minuta.": "We couldn't save your request. Try again in a few minutes.",
}


def submit(form, ip=""):
    """(True, None) when stored, else (False, plain-Croatian reason). Honeypot hits pretend to succeed."""
    if (form.get("web") or "").strip():
        return True, None
    name = re.sub(r"\s+", " ", (form.get("name") or "").strip())[:40]
    contact = (form.get("contact") or "").strip()[:120]
    if len(name) < 2:
        return False, "Upiši ime ili nadimak."
    if len(contact) < 5:
        return False, "Upiši kontakt: e-mail, broj mobitela ili Telegram @ime."
    now = time.time()
    hits = [t for t in _IPS.get(ip, []) if now - t < 3600]
    if len(hits) >= PER_IP_HOUR:
        return False, "Previše zahtjeva s ove adrese. Pokušaj ponovno za sat vremena."
    _IPS[ip] = hits + [now]
    try:
        con = _con()
        try:
            if (con.execute("SELECT COUNT(*) FROM access_requests WHERE status='novi'").fetchone()[0] or 0) >= MAX_PENDING:
                return False, "Lista čekanja je trenutno puna. Pokušaj ponovno za par dana."
            dup = con.execute("SELECT id FROM access_requests WHERE contact=? AND status='novi'", (contact,)).fetchone()
            if dup:
                return True, None
            con.execute("INSERT INTO access_requests (ts, name, contact, experience, interest, source, ip) "
                        "VALUES (?,?,?,?,?,?,?)",
                        (int(now), name, contact, (form.get("experience") or "")[:20],
                         (form.get("interest") or "").strip()[:600], (form.get("src") or "")[:40], ip[:64]))
            con.commit()
        finally:
            con.close()
    except sqlite3.OperationalError as e:
        print(f"zahtjev za pristup nije spremljen: {e}", flush=True)
        return False, "Zahtjev trenutno nije moguće spremiti. Pokušaj ponovno za par minuta."
    print(f"natjecanje: zahtjev za pristup od {name}", flush=True)
    return True, None


def pending_count():
    try:
        con = _con()
        try:
            return con.execute("SELECT COUNT(*) FROM access_requests WHERE status='novi'").fetchone()[0] or 0
        finally:
            con.close()
    except sqlite3.Error:
        return 0


EXP = {"pocetnik": "tek počinje", "povremeno": "povremeno", "aktivno": "aktivno, memecoini", "profi": "svaki dan"}
STATUS = {"novi": ("novi", "warn"), "pozvan": ("pozvan", "good"), "odbijen": ("odbijen", ""),
          "registriran": ("registriran", "good")}


def _invite_text(row, url):
    return (f"Bok {row['name']}! Evo tvoje pozivnice za MemeSonar: {url}\n"
            "Otvori link, upiši ime i lozinku i dobiješ demo račun od $1.000.")


def _share(row, url):
    """Buttons to send the invite: WhatsApp (to the number when we have one), e-mail (to the address when we have one),
    Telegram share, and the phone's own share sheet when the browser has one."""
    text = _invite_text(row, url)
    c = (row["contact"] or "").strip()
    digits = re.sub(r"[^\d+]", "", c)
    if re.fullmatch(r"\+?\d{8,15}", digits) and "@" not in c:
        num = digits.lstrip("+")
        if num.startswith("0"):
            num = "385" + num[1:]   # Croatian number written locally
        wa = f"https://wa.me/{num}?text={quote(text)}"
    else:
        wa = f"https://wa.me/?text={quote(text)}"
    to = esc(c) if ("@" in c and "." in c.split("@")[-1] and not c.startswith("@")) else ""
    mail = f"mailto:{to}?subject={quote('Tvoja pozivnica za MemeSonar')}&body={quote(text)}"
    tg = f"https://t.me/share/url?url={quote(url)}&text={quote(text.split(': ')[0] + ':')}"
    return (f"<a class='sh wa' href=\"{wa}\" target=_blank rel=noopener>📲 WhatsApp</a>"
            f"<a class='sh em' href=\"{mail}\">✉️ E-mail</a>"
            f"<a class='sh tg' href=\"{tg}\" target=_blank rel=noopener>✈️ Telegram</a>"
            f"<button type=button class='sh ns' hidden data-t=\"{esc(text)}\" "
            "onclick=\"navigator.share({text:this.dataset.t}).catch(function(){})\">📤 Više…</button>")


INV_CSS = """<style>
.inv{border:1px solid var(--line,#2a3446);border-radius:16px;padding:14px;margin:12px 0;display:grid;gap:10px}
.inv h3{margin:0;font-size:17px}.inv .ct{color:var(--mut,#8b95a7);font-size:14px;word-break:break-all}
.inv .lk{display:flex;gap:8px;align-items:stretch}
.inv .lk input{flex:1;min-width:0;width:100%;font-size:14px;padding:10px 12px;border-radius:10px}
.inv .cp{white-space:nowrap;padding:10px 14px;border-radius:10px;font-weight:600}
.inv .shs{display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:8px}
.inv .sh{display:flex;align-items:center;justify-content:center;gap:6px;padding:12px;border-radius:12px;font-weight:650;
font-size:15px;text-decoration:none!important;color:#fff!important;border:0;cursor:pointer;font-family:inherit}
.inv .sh[hidden]{display:none}.inv .wa{background:#16a34a}.inv .em{background:#2563eb}.inv .tg{background:#0ea5e9}.inv .ns{background:#475569}
</style>"""


def _invite_card(r, url):
    return (f"<div class=inv id=inv{r['id']}><h3>📨 Pozivnica za {esc(r['name'])}</h3>"
            f"<div class=ct>{esc(r['contact'] or '')}</div>"
            f"<div class=lk><input readonly value=\"{esc(url)}\" data-inv=\"{esc('/registracija?k=' + quote(r['invite']))}\" "
            "onclick='this.select()' aria-label='Link pozivnice'>"
            "<button type=button class=cp onclick=\"var i=this.previousElementSibling;i.select();"
            "navigator.clipboard&&navigator.clipboard.writeText(i.value);this.textContent='✅ Kopirano'\">📋 Kopiraj</button></div>"
            f"<div class=shs>{_share(r, url)}</div></div>")


def admin_page(qs, user):
    """/zahtjevi: who asked for access, with one-click single-use invites."""
    from ui import register
    title = "Zahtjevi za pristup"
    if not register.can_invite(user):
        return title, ("<h1>Zahtjevi za pristup</h1><div class=card>Ovu stranicu vidi samo organizator natjecanja. "
                       "<a href=/prijava>Prijavi se svojim imenom</a>.</div>")
    try:
        con = _con()
        try:
            rows = [dict(r) for r in con.execute(
                "SELECT * FROM access_requests ORDER BY (status='novi') DESC, ts DESC LIMIT 300")]
            joined = {r[0]: r[1] for r in con.execute("SELECT invite, name FROM members WHERE invite IS NOT NULL")} \
                if con.execute("SELECT 1 FROM sqlite_master WHERE name='members'").fetchone() else {}
        finally:
            con.close()
    except sqlite3.Error as e:
        return title, f"<h1>Zahtjevi za pristup</h1><div class=card neg>Baza nije dostupna: {esc(e)}</div>"
    b = ["<h1>Zahtjevi za pristup</h1>"]
    if qs.get("ok"):
        b.append(f"<div class=card style='border-color:var(--good)'>✅ {esc(qs['ok'])}</div>")
    novi = sum(1 for r in rows if r["status"] == "novi")
    b.append(f"<p class=lead>Ljudi koji su na <a href=/dobrodosli target=_blank>naslovnoj stranici</a> kliknuli "
             f"„Zatraži pristup”. <b>{novi}</b> čeka odgovor. Klikni <b>Pozovi</b> i alat napravi jednokratni link "
             "za tu osobu, pa ga pošalješ na WhatsApp, e-mail ili Telegram jednim klikom.</p>")
    from ui.html import table
    out, cards = [], []
    from ui.register import link
    for r in rows:
        st = r["status"]
        if r["invite"] and r["invite"] in joined:
            st = "registriran"
        lab, kind = STATUS.get(st, (st, ""))
        if r["status"] == "novi":
            act = (f"<form method=post action=/zahtjevi/{r['id']}/pozovi style='display:inline;margin:0'>"
                   "<button>✉️ Pozovi</button></form> "
                   f"<form method=post action=/zahtjevi/{r['id']}/odbij style='display:inline;margin:0'>"
                   "<button class=sm onclick=\"return confirm('Odbiti zahtjev?')\">Odbij</button></form>")
        elif r["status"] == "pozvan" and r["invite"]:
            url = link(r["invite"])
            if st == "registriran":
                act = f"<span class=mut>kao {esc(joined[r['invite']])}</span>"
            else:
                cards.append(_invite_card(r, url))
                act = f"<a href=#inv{r['id']}>📨 Pošalji pozivnicu ↑</a>"
        else:
            act = f"<span class=mut>{esc(r['handled_by'] or '')}</span>"
        out.append([ago(r["ts"]), f"<b>{esc(r['name'])}</b>", esc(r["contact"]), esc(EXP.get(r["experience"], "–")),
                    f"<span style='white-space:normal'>{esc(r['interest'] or '')}</span>",
                    f"<span class='b {kind}'>{esc(lab)}</span>", act])
    if cards:
        b.append(INV_CSS + "<h2 style='margin:18px 0 4px'>Pozivnice spremne za slanje</h2>"
                 "<p class=mut style='margin:0'>Pošalji link jednim gumbom. Link vrijedi jednom; kad se osoba registrira, "
                 "nestaje s ovog popisa.</p>" + "".join(cards[:20])
                 + "<script>if(navigator.share)document.querySelectorAll('.sh.ns').forEach(function(b){b.hidden=false})</script>")
    b.append(table(["Kada", "Ime", "Kontakt", "Iskustvo", "Zanima ga", "Status", "Akcija"], out, tid="zahtjevi",
                   empty="Još nema zahtjeva. Pošalji link naslovne stranice ljudima koje želiš privući."))
    if not os.environ.get("RENDER_EXTERNAL_URL"):
        b.append("<script>document.querySelectorAll('input[data-inv]').forEach(function(i){"
                 "i.value=location.origin+i.dataset.inv})</script>")
    return title, "".join(b)


def admin_post(path, user):
    from league import members
    from ui import register
    if not register.can_invite(user):
        return "/zahtjevi"
    m = re.fullmatch(r"/zahtjevi/(\d+)/(pozovi|odbij)", path)
    if not m:
        return "/zahtjevi"
    rid, act = int(m.group(1)), m.group(2)
    con = _con()
    try:
        r = con.execute("SELECT name, status FROM access_requests WHERE id=?", (rid,)).fetchone()
        if not r or r["status"] != "novi":
            return "/zahtjevi"
        if act == "pozovi":
            members.connect().close()   # invites table exists
            tok = members.single(con, user)
            con.execute("UPDATE access_requests SET status='pozvan', invite=?, handled_by=?, handled_ts=? WHERE id=?",
                        (tok, user, int(time.time()), rid))
            msg = f"Pozivnica za {r['name']} je spremna: kopiraj link ili ga pošalji gumbom ispod."
        else:
            con.execute("UPDATE access_requests SET status='odbijen', handled_by=?, handled_ts=? WHERE id=?",
                        (user, int(time.time()), rid))
            msg = f"Zahtjev od {r['name']} je odbijen."
        con.commit()
    finally:
        con.close()
    print(f"natjecanje: {user} zahtjev {rid} {act}", flush=True)
    return f"/zahtjevi?ok={quote(msg)}"
