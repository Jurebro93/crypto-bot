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

SHOTS = {   # file -> (alt text)
    "pregled.jpg": "Pregled: istaknuti kandidati po vrsti, sa Šansom za skok i provjerama",
    "token.jpg": "Stranica tokena: tumačenje običnim riječima, za i protiv, slojevita analiza",
    "moc-poziva.jpg": "Koliko tržište sluša influencera: volumen i cijena nakon objave",
    "kol.jpg": "Profil influencera: moć poziva, pogodak, kasni pozivi i rugovi",
    "copy.jpg": "Copy trading: uđi na sljedeći call influencera automatski",
    "natjecanje.jpg": "Natjecanje: ljestvica igrača s demo računima",
    "mobitel.jpg": "Natjecanje na mobitelu",
    "dugorocni.jpg": "Dugoročni i oživljeni tokeni",
    "korelacije.jpg": "Korelacije: tko radi zajedno, AI tumačenje",
}

CSS = """
:root{--bg:#07090f;--bg2:#0d111b;--card:#121827;--line:#1f2738;--fg:#eef1f7;--mut:#97a1b5;--acc:#6d6cf7;--acc2:#12c9a4;
--warm:#ff9f43;--good:#3ddc84;--bad:#ff6b6b}
*{box-sizing:border-box}html{scroll-behavior:smooth}
body{margin:0;background:var(--bg);color:var(--fg);font:16px/1.6 Inter,system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;
-webkit-font-smoothing:antialiased}
a{color:inherit}img{max-width:100%;display:block}
.wrap{max-width:1180px;margin:0 auto;padding:0 22px}
nav.lt{position:sticky;top:0;z-index:20;background:color-mix(in srgb,var(--bg) 82%,transparent);backdrop-filter:blur(10px);
border-bottom:1px solid var(--line)}
nav.lt .wrap{display:flex;align-items:center;gap:14px;height:64px}
.brand{display:flex;align-items:center;gap:10px;font-weight:800;font-size:19px;letter-spacing:-.02em;text-decoration:none}
.sp{flex:1}.navl{color:var(--mut);text-decoration:none;font-size:15px}.navl:hover{color:var(--fg)}
.btn{display:inline-flex;align-items:center;justify-content:center;gap:8px;border-radius:12px;padding:12px 20px;font-weight:700;
font-size:16px;text-decoration:none;border:1px solid transparent;cursor:pointer;font-family:inherit;transition:transform .12s,box-shadow .12s}
.btn:hover{transform:translateY(-1px)}
.btn.p{background:linear-gradient(135deg,var(--acc),var(--acc2));color:#fff;box-shadow:0 8px 30px -8px rgba(109,108,247,.7)}
.btn.g{background:transparent;border-color:var(--line);color:var(--fg)}.btn.g:hover{border-color:var(--mut)}
.btn.sm{padding:8px 14px;font-size:14px;border-radius:10px}
.hero{position:relative;overflow:hidden;padding:72px 0 40px}
.hero:before{content:"";position:absolute;inset:-30% -10% auto;height:720px;background:
radial-gradient(600px 340px at 20% 30%,rgba(109,108,247,.35),transparent 70%),
radial-gradient(520px 320px at 80% 10%,rgba(18,201,164,.25),transparent 70%);pointer-events:none}
.hero .wrap{position:relative}
.pill{display:inline-flex;align-items:center;gap:8px;border:1px solid var(--line);background:rgba(255,255,255,.03);border-radius:999px;
padding:6px 14px;font-size:14px;color:var(--mut)}.pill b{color:var(--warm)}
.dot{width:8px;height:8px;border-radius:50%;background:var(--good);box-shadow:0 0 0 4px rgba(61,220,132,.2);animation:pl 1.8s infinite}
@keyframes pl{50%{box-shadow:0 0 0 8px rgba(61,220,132,0)}}
h1.big{font-size:clamp(36px,6vw,64px);line-height:1.05;letter-spacing:-.035em;margin:22px 0 18px;font-weight:850;max-width:900px}
.grad{background:linear-gradient(90deg,#9d9cff,#3fe0c0);-webkit-background-clip:text;background-clip:text;color:transparent}
.sub{font-size:clamp(17px,2vw,20px);color:var(--mut);max-width:720px;margin:0 0 28px}
.ctas{display:flex;gap:12px;flex-wrap:wrap;align-items:center}.note{color:var(--mut);font-size:14px;margin-top:14px}
.frame{margin-top:54px;border-radius:16px;border:1px solid var(--line);background:var(--bg2);box-shadow:0 40px 120px -30px rgba(0,0,0,.8),
0 0 0 1px rgba(255,255,255,.02);overflow:hidden;position:relative}
.frame .bar{display:flex;gap:6px;padding:10px 14px;border-bottom:1px solid var(--line);align-items:center}
.frame .bar i{width:11px;height:11px;border-radius:50%;background:#2a3245}.frame .bar span{margin-left:10px;color:var(--mut);font-size:12px}
.frame img{width:100%;cursor:zoom-in}
.phone{position:absolute;right:-14px;bottom:-30px;width:200px;border-radius:26px;border:6px solid #1b2232;overflow:hidden;
box-shadow:0 30px 80px rgba(0,0,0,.7);display:none}
@media(min-width:900px){.heroimg{position:relative;padding-right:120px}.phone{display:block;right:0}}
section{padding:72px 0}section.alt{background:var(--bg2);border-top:1px solid var(--line);border-bottom:1px solid var(--line)}
h2{font-size:clamp(28px,4vw,42px);letter-spacing:-.03em;line-height:1.1;margin:0 0 14px;font-weight:800}
.kick{color:var(--acc2);font-weight:700;font-size:14px;letter-spacing:.08em;text-transform:uppercase;margin-bottom:10px}
.lead{color:var(--mut);font-size:18px;max-width:760px;margin:0 0 30px}
.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:14px}
.st{background:var(--card);border:1px solid var(--line);border-radius:16px;padding:20px}
.st .v{font-size:34px;font-weight:800;letter-spacing:-.02em;font-variant-numeric:tabular-nums}
.st .l{color:var(--mut);font-size:14px;line-height:1.4}.live{color:var(--mut);font-size:13px;margin-top:14px;display:flex;gap:8px;align-items:center}
.power{display:grid;grid-template-columns:1fr 1fr;gap:34px;align-items:center}@media(max-width:900px){.power{grid-template-columns:1fr}}
.cmp{background:var(--card);border:1px solid var(--line);border-radius:18px;padding:26px}
.cmp .row{margin:16px 0}.cmp .lab{display:flex;justify-content:space-between;font-size:15px;margin-bottom:6px}
.cmp .lab b{font-size:22px}.trk{height:14px;border-radius:8px;background:#1b2232;overflow:hidden}
.trk i{display:block;height:100%;border-radius:8px}.hi i{background:linear-gradient(90deg,var(--acc),var(--acc2))}.lo i{background:#3b4560}
.fx{font-size:13px;color:var(--mut);margin-top:14px}
.feat{display:grid;grid-template-columns:1fr 1.25fr;gap:44px;align-items:center;margin:0 0 84px}
.feat:last-child{margin-bottom:0}.feat.r{grid-template-columns:1.25fr 1fr}.feat.r .txt{order:2}
@media(max-width:900px){.feat,.feat.r{grid-template-columns:1fr;gap:22px;margin-bottom:60px}.feat.r .txt{order:0}}
.feat h3{font-size:clamp(24px,3vw,32px);letter-spacing:-.025em;line-height:1.15;margin:0 0 12px}
.feat p{color:var(--mut);margin:0 0 14px}.feat ul{margin:0;padding:0;list-style:none}
.feat li{padding:6px 0 6px 30px;position:relative}.feat li:before{content:"✓";position:absolute;left:0;top:6px;width:20px;height:20px;
border-radius:6px;background:rgba(18,201,164,.15);color:var(--acc2);font-size:13px;display:flex;align-items:center;justify-content:center;font-weight:800}
.shot{border-radius:14px;border:1px solid var(--line);overflow:hidden;box-shadow:0 30px 80px -30px rgba(0,0,0,.8);background:var(--bg2)}
.shot img{width:100%;cursor:zoom-in}.tag{display:inline-block;font-size:13px;font-weight:700;border-radius:999px;padding:3px 11px;
margin-bottom:12px;background:rgba(109,108,247,.15);color:#a9a8ff}
.steps{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:14px;counter-reset:s}
.step{background:var(--card);border:1px solid var(--line);border-radius:16px;padding:22px;position:relative}
.step:before{counter-increment:s;content:counter(s);position:absolute;top:18px;right:20px;font-size:40px;font-weight:900;color:#1f2840}
.step .i{font-size:28px}.step h4{margin:10px 0 6px;font-size:18px}.step p{margin:0;color:var(--mut);font-size:15px}
.req{display:grid;grid-template-columns:1fr 1fr;gap:40px;align-items:start}@media(max-width:900px){.req{grid-template-columns:1fr}}
form.rq{background:var(--card);border:1px solid var(--line);border-radius:18px;padding:26px}
form.rq label{display:block;font-weight:600;font-size:14px;margin:0 0 14px}
form.rq input,form.rq select,form.rq textarea{width:100%;margin-top:6px;background:var(--bg);color:var(--fg);border:1px solid var(--line);
border-radius:10px;padding:12px 14px;font:inherit;font-size:16px}
form.rq input:focus,form.rq select:focus,form.rq textarea:focus{outline:none;border-color:var(--acc)}
form.rq .hp{position:absolute;left:-9999px;width:1px;height:1px;overflow:hidden}
.ok{background:rgba(61,220,132,.12);border:1px solid rgba(61,220,132,.4);border-radius:14px;padding:18px;margin-bottom:16px}
.err{background:rgba(255,107,107,.12);border:1px solid rgba(255,107,107,.4);border-radius:14px;padding:14px;margin-bottom:14px}
.perks{display:grid;gap:12px}.perk{display:flex;gap:14px;align-items:flex-start}.perk .i{font-size:24px;line-height:1}
.perk b{display:block}.perk span{color:var(--mut);font-size:15px}
details.faq{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:16px 20px;margin:10px 0}
details.faq summary{cursor:pointer;font-weight:700;list-style:none}details.faq summary::-webkit-details-marker{display:none}
details.faq summary:after{content:"+";float:right;color:var(--mut);font-size:20px;line-height:1}details.faq[open] summary:after{content:"–"}
details.faq p{color:var(--mut);margin:10px 0 0}
.final{text-align:center;padding:80px 0}.final h2{margin-bottom:12px}.final .ctas{justify-content:center}
footer{border-top:1px solid var(--line);padding:30px 0 50px;color:var(--mut);font-size:13px}
dialog#lb{border:0;padding:0;background:transparent;max-width:96vw;max-height:94vh}dialog#lb::backdrop{background:rgba(0,0,0,.85)}
dialog#lb img{max-width:96vw;max-height:94vh;border-radius:10px}
.mob-cta{position:fixed;left:12px;right:12px;bottom:12px;z-index:30;display:none}
@media(max-width:700px){.mob-cta{display:flex}.mob-cta .btn{flex:1}footer{padding-bottom:100px}.navl{display:none}nav.lt .btn.g{display:none}}
"""

JS = """
const lb=document.getElementById('lb');document.querySelectorAll('img[data-zoom]').forEach(i=>i.onclick=()=>{
 lb.querySelector('img').src=i.src;lb.querySelector('img').alt=i.alt;lb.showModal()});lb.onclick=()=>lb.close();
"""


def _img(name, eager=False):
    return (f'<img src="/static/landing/{name}" alt="{esc(SHOTS.get(name, ""))}" data-zoom '
            f'{"" if eager else "loading=lazy "}decoding=async>')


def _stat(v, label):
    return f"<div class=st><div class=v>{v}</div><div class=l>{label}</div></div>"


def page_html(qs=None, logged_in=False, ok=False, err="", form=None):
    qs = qs or {}
    form = form or {}
    v, ts = stats()
    svg, name = logo(34)
    base = os.environ.get("RENDER_EXTERNAL_URL", "").rstrip("/")

    stat_cards = []
    for key, label in (("tokens", "tokena analizirano od prvog dana, svaki kroz više slojeva provjere"),
                       ("scans", "mjerenja tokena: cijena, volumen, likvidnost i kupci, svake 2 minute"),
                       ("wallets", "novčanika pod nadzorom: tko kupuje rano i tko stvarno zarađuje"),
                       ("wallet_trades", "kupnji i prodaja novčanika analizirano"),
                       ("kols", "influencera (KOL-ova) praćeno na X-u, s ocjenom svakog poziva"),
                       ("calls", "poziva influencera izmjereno: što je cijena napravila 1 h, 6 h i 24 h poslije"),
                       ("channels", "Telegram call kanala koje čitamo uživo"),
                       ("rugs", "rug pullova prepoznato i izbačeno, a alat uči iz svakog")):
        if v.get(key):
            stat_cards.append(_stat(_n(v[key]), label))
    stats_html = ""
    if stat_cards:
        stats_html = (f"<div class=stats>{''.join(stat_cards[:8])}</div>"
                      f"<div class=live><span class=dot></span>Brojke se čitaju uživo iz baze alata"
                      + (f" · osvježeno {ago(ts)[0]}" if ts else "") + "</div>")
    else:
        stats_html = ("<div class=stats>" + _stat("2 min", "koliko često skener prolazi kroz nove tokene")
                      + _stat("24/7", "alat radi i noću, i za vikend") + _stat("7", "slojeva provjere svakog tokena")
                      + "</div>")

    # call power: tokens called by 3+ influencers within 15 minutes vs fewer
    g, s = v.get("group_rate"), v.get("solo_rate")
    if g and s:
        power = (f"<div class=cmp><div class=row><div class=lab><span>3+ influencera u 15 minuta</span><b>{_pct(g)}</b></div>"
                 f"<div class='trk hi'><i style='width:{min(100, g * 100):.0f}%'></i></div></div>"
                 f"<div class=row><div class=lab><span>Jedan ili dva influencera</span><b>{_pct(s)}</b></div>"
                 f"<div class='trk lo'><i style='width:{min(100, s * 100):.0f}%'></i></div></div>"
                 f"<div class=fx>Udio tokena koji su se barem udvostručili u 24 h nakon prvog poziva. "
                 f"Izmjereno na našim podacima" + (f", {_n(v['measured'])} poziva" if v.get("measured") else "")
                 + f". Kad se poklope, šansa je {g / s:.1f}× veća.</div></div>")
    else:
        power = ("<div class=cmp><div class=row><div class=lab><span>3+ influencera u 15 minuta</span><b>57%</b></div>"
                 "<div class='trk hi'><i style='width:57%'></i></div></div><div class=row><div class=lab>"
                 "<span>Jedan ili dva influencera</span><b>33%</b></div><div class='trk lo'><i style='width:33%'></i></div>"
                 "</div><div class=fx>Udio tokena koji su se barem udvostručili u 24 h nakon prvog poziva, "
                 "izmjereno na našim podacima.</div></div>")
    calls_line = ""
    if v.get("call_2x") and v.get("measured"):
        calls_line = (f"<li>Od {_n(v['measured'])} izmjerenih poziva, {_pct(v['call_50'])} je dalo barem +50%, a "
                      f"{_pct(v['call_2x'])} barem 2× u 24 h. Alat zna koji influenceri nose taj postotak, a koji ga ruše.</li>")

    msg = ""
    if ok:
        msg = ("<div class=ok><b>✅ Zahtjev je poslan.</b><br>Javit ćemo ti se na kontakt koji si ostavio s osobnim "
               "linkom za registraciju. Mjesta puštamo u malim grupama.</div>")
    elif err:
        msg = f"<div class=err>{esc(err)}</div>"
    f = {k: esc(form.get(k, "")) for k in ("name", "contact", "interest")}
    exp = form.get("experience", "")

    def opt(val, label):
        return f"<option value=\"{val}\"{' selected' if exp == val else ''}>{label}</option>"

    request_form = (
        f"<form class=rq method=post action=/zatrazi-pristup id=forma>{msg}"
        f"<label>Ime ili nadimak<input name=name required maxlength=40 autocomplete=name value=\"{f['name']}\" "
        "placeholder='npr. Marko'></label>"
        f"<label>Kako da ti se javimo<input name=contact required maxlength=120 value=\"{f['contact']}\" "
        "placeholder='e-mail, broj mobitela ili Telegram @ime'></label>"
        "<label>Iskustvo s kriptom<select name=experience>"
        + opt("", "odaberi…") + opt("pocetnik", "Tek počinjem") + opt("povremeno", "Tradam povremeno")
        + opt("aktivno", "Tradam aktivno, memecoini i Solana") + opt("profi", "Ozbiljno, svaki dan") + "</select></label>"
        f"<label>Što te najviše zanima? <span style='color:var(--mut);font-weight:400'>(nije obavezno)</span>"
        f"<textarea name=interest rows=3 maxlength=600 placeholder='npr. copy trading, pozivi influencera, novi tokeni…'>"
        f"{f['interest']}</textarea></label>"
        "<div class=hp aria-hidden=true><label>Web stranica<input name=web tabindex=-1 autocomplete=off></label></div>"
        f"<input type=hidden name=src value=\"{esc(qs.get('src', qs.get('utm_source', ''))[:40])}\">"
        "<button class='btn p' type=submit style='width:100%'>🔓 Zatraži pristup</button>"
        "<p style='color:var(--mut);font-size:13px;margin:12px 0 0'>Nikad ne tražimo seed frazu, privatni ključ ni "
        "novac. Tvoj kontakt vidi samo organizator i koristi ga samo da ti pošalje pozivnicu.</p></form>")

    login_btn = ("<a class='btn g sm' href=/>Otvori aplikaciju →</a>" if logged_in
                 else "<a class='btn g sm' href=/prijava>Prijava</a>")
    title = "KriptoRadar · vidi sljedeći Solana token prije gomile"
    desc = ("Skener novih Solana tokena, influencera i pametnih novčanika. Moć poziva, copy trading, natjecanje "
            "s demo računom. Samo na pozivnicu.")
    og_img = f"{base}/static/landing/pregled.jpg" if base else "/static/landing/pregled.jpg"
    from urllib.parse import quote as _q
    return f"""<!doctype html><html lang=hr><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1"><title>{esc(title)}</title>
<meta name=description content="{esc(desc)}">
<meta property="og:type" content="website"><meta property="og:title" content="{esc(title)}">
<meta property="og:description" content="{esc(desc)}"><meta property="og:image" content="{esc(og_img)}">
<meta name="twitter:card" content="summary_large_image"><meta name=theme-color content="#07090f">
<link rel=icon href="data:image/svg+xml,{_q(logo(32)[0])}"><style>{CSS}</style></head><body>
<nav class=lt><div class=wrap><a class=brand href=/dobrodosli>{svg}<span>{esc(name)}</span></a><span class=sp></span>
<a class=navl href=#funkcije>Funkcije</a><a class=navl href=#moc>Moć poziva</a><a class=navl href=#pitanja>Pitanja</a>
{login_btn}<a class='btn p sm' href=#pristup>Zatraži pristup</a></div></nav>

<header class=hero><div class=wrap>
<span class=pill><b>🔒 Samo na pozivnicu</b> · ograničen broj mjesta</span>
<h1 class=big>Vidi sljedeći Solana token <span class=grad>prije gomile.</span></h1>
<p class=sub>KriptoRadar svake 2 minute prolazi kroz nove tokene, prati influencere i pametne novčanike i mjeri što se
stvarno dogodi nakon svakog poziva. Ti dobiješ kratku listu tokena s najvećom šansom, objašnjenu običnim riječima.</p>
<div class=ctas><a class='btn p' href=#pristup>🔓 Zatraži pristup</a>
<a class='btn g' href={'/' if logged_in else '/prijava'}>{'Otvori aplikaciju' if logged_in else 'Već imam račun · Prijava'}</a></div>
<p class=note>Bez kartice, bez novca, bez seed fraze. Pozvani dobiju demo račun od $1.000 i odmah kreću.</p>
<div class=heroimg><div class=frame><div class=bar><i></i><i></i><i></i><span>kriptoradar · Pregled</span></div>
{_img("pregled.jpg", True)}</div><div class=phone>{_img("mobitel.jpg", True)}</div></div>
</div></header>

<section class=alt><div class=wrap><div class=kick>Uživo iz baze</div>
<h2>Iza svakog prijedloga stoje stvarni podaci.</h2>
<p class=lead>Ne nagađamo i ne prepisujemo tuđe signale. Sve brojke ispod alat je sam skupio i izmjerio, i rastu
svakih nekoliko minuta.</p>{stats_html}</div></section>

<section id=moc><div class=wrap><div class=power><div>
<div class=kick>Moć poziva</div><h2>Znaš koji poziv influencera pomiče cijenu, a koji je samo buka.</h2>
<p class=lead style='margin-bottom:18px'>Za svaku objavu s adresom tokena alat izmjeri volumen i cijenu sat prije i
poslije, 1 h, 6 h i 24 h kasnije. Tako svaki influencer dobije ocjenu: koliko ga tržište sluša, koliko mu poziva
uspije, koliko kasni i koliko mu tokena završi kao rug.</p>
<div class=feat style='margin:0;display:block'><ul>{calls_line}
<li>Botovi koji samo objavljuju svaki novi token su izbačeni iz ljestvice.</li>
<li>Vidiš i tko je zvao token nakon njega te koliko pregleda i pratitelja ima.</li></ul></div>
</div>{power}</div>
<div class=shot style='margin-top:40px'>{_img("moc-poziva.jpg")}</div></div></section>

<section class=alt id=funkcije><div class=wrap><div class=kick>Što sve radi</div>
<h2>Sve što profesionalni trader prati, na jednom mjestu.</h2>
<p class=lead>Alat radi 24/7 i ne umara se. Ti otvoriš aplikaciju i odmah vidiš što je bitno sada.</p>

<div class=feat><div class=txt><span class=tag>🧠 Vlastiti algoritam</span>
<h3>Šansa za skok, izračunata iz 7 slojeva provjere.</h3>
<p>Svaki novi token prolazi kroz anti-rug filter, provjeru likvidnosti i holdera, hype na X-u i Telegramu, smart money
novčanike i pozive influencera. Na kraju dobije jednu ocjenu i objašnjenje: zašto bi mogao rasti i što govori protiv.</p>
<ul><li>Lažni poolovi, zaključana likvidnost i dev koji prodaje se odbacuju prije nego što ih vidiš.</li>
<li>Algoritam uči iz svakog ishoda i sam prilagođava težine, uz zaštitne ograde.</li>
<li>Uz svaki token linkovi na DexScreener, pump.fun, GMGN, RugCheck i Jupiter.</li></ul></div>
<div class=shot>{_img("token.jpg")}</div></div>

<div class='feat r'><div class=txt><span class=tag>📣 Influenceri (KOL-ovi)</span>
<h3>Profil svakog influencera, s brojkama umjesto obećanja.</h3>
<p>Moć poziva, pogodak, rast u 1 h i 24 h, kasni pozivi i rugovi. Odmah vidiš kome vjerovati, a tko ulazi tek nakon
što je cijena već skočila.</p>
<ul><li>Najbolji influenceri se prate uživo: objavu vidimo u sekundama.</li>
<li>Grupe influencera koje zovu iste tokene i novčanici koji kupe prije poziva.</li></ul></div>
<div class=shot>{_img("kol.jpg")}</div></div>

<div class=feat><div class=txt><span class=tag>🔁 Copy trading</span>
<h3>Prati influencera ili novčanik. Alat ulazi i izlazi umjesto tebe.</h3>
<p>Klikneš „Prati” i svaki njegov novi call se kupi na tvom računu u roku od minute, i preko noći. Kod novčanika:
kad on kupi, kupiš i ti; kad proda, prodaš i ti.</p>
<ul><li>Sam biraš ulog, koliko ulaza dnevno i kako se izlazi.</li><li>Jedan klik za „samo sljedeći call”.</li>
<li>Tablica „Što se dogodilo” pokazuje svaki ulaz i izlaz.</li></ul></div>
<div class=shot>{_img("copy.jpg")}</div></div>

<div class='feat r'><div class=txt><span class=tag>🏆 Natjecanje</span>
<h3>Ljudi protiv bota, s demo računom od $1.000.</h3>
<p>Kupuješ i prodaješ po živoj cijeni, s naknadom i klizanjem kao u pravoj trgovini, ali bez pravog novca. Ljestvica,
medalje, svi tradeovi vidljivi svima. Najbrži način da naučiš i vidiš tko stvarno zna.</p>
<ul><li>Predloženi tokeni i kupnja jednim klikom.</li><li>Automatski DCA: kupuj u ratama dok token pada.</li>
<li>Pošalji stanje ljestvice u WhatsApp grupu jednim klikom.</li></ul></div>
<div class=shot>{_img("natjecanje.jpg")}</div></div>

<div class=feat><div class=txt><span class=tag>🌱 Jaki i dugoročni tokeni</span>
<h3>Sigurniji sloj uz lov na nove tokene.</h3>
<p>Tokeni koji su preživjeli tjednima, imaju pravu likvidnost i stalan volumen, poput Fartcoina i Uselessa. Alat prati
i što kupuju veliki holderi i koliko tokena drže burze.</p>
<ul><li>Popisi se osvježavaju svakih 6 sati.</li><li>Rug tokeni i slabi tokeni se automatski skrivaju.</li></ul></div>
<div class=shot>{_img("dugorocni.jpg")}</div></div>

<div class='feat r'><div class=txt><span class=tag>🕸 Korelacije i AI</span>
<h3>Tko radi zajedno, objašnjeno u par rečenica.</h3>
<p>Alat spaja X, Telegram i on-chain podatke: koje ekipe zovu iste tokene, koji novčanici kupe prije poziva i što te
grupe diraju upravo sada. AI to svaki dan sažme u tumačenje koje se čita za minutu.</p>
<ul><li>Jutarnji izvještaj sa svim bitnim, gotov prije 8 h.</li></ul></div>
<div class=shot>{_img("korelacije.jpg")}</div></div>
</div></section>

<section><div class=wrap><div class=kick>Kako radi</div><h2>Od novog tokena do odluke za par minuta.</h2>
<p class=lead>Cijeli lanac radi sam. Tvoje je samo da pogledaš i odlučiš.</p>
<div class=steps>
<div class=step><div class=i>📡</div><h4>Skener</h4><p>Svake 2 minute pokupi nove tokene s pump.funa, DexScreenera, X-a i Telegrama.</p></div>
<div class=step><div class=i>🛡</div><h4>Provjera</h4><p>Anti-rug filter, likvidnost, holderi, dev novčanik, lažni poolovi. Loši ispadaju.</p></div>
<div class=step><div class=i>🎯</div><h4>Šansa</h4><p>Hype, pametni novčanici i influenceri spoje se u jednu ocjenu s objašnjenjem.</p></div>
<div class=step><div class=i>🧠</div><h4>Učenje</h4><p>Svaki ishod se mjeri. Što je radilo dobije veću težinu, što nije, manju.</p></div>
</div></div></section>

<section class=alt id=pristup><div class=wrap><div class=req><div>
<div class=kick>Samo na pozivnicu</div><h2>Zatraži svoje mjesto.</h2>
<p class=lead>KriptoRadar je zatvorena zajednica. Mjesta puštamo postupno da alat ostane brz, a ekipa kvalitetna.
Ostavi kontakt i javit ćemo ti se s osobnim linkom.</p>
<div class=perks>
<div class=perk><div class=i>💵</div><div><b>Demo račun od $1.000</b><span>Uči i natječi se bez rizika, po živim cijenama.</span></div></div>
<div class=perk><div class=i>⚡</div><div><b>Sve funkcije odmah</b><span>Pregled, influenceri, copy trading, natjecanje, jutarnji izvještaj.</span></div></div>
<div class=perk><div class=i>📱</div><div><b>Radi na mobitelu</b><span>Otvoriš link, prijaviš se jednom i alat te pamti 60 dana.</span></div></div>
<div class=perk><div class=i>🔐</div><div><b>Bez novca i ključeva</b><span>Nikad ne tražimo seed frazu ni privatni ključ.</span></div></div>
</div></div>{request_form}</div></div></section>

<section id=pitanja><div class=wrap style='max-width:820px'><div class=kick>Pitanja</div><h2>Često pitaju</h2>
<details class=faq><summary>Je li ovo financijski savjet?</summary><p>Nije. KriptoRadar je alat koji skuplja i mjeri
podatke i pokazuje ih jasno. Memecoini su vrlo rizični i većina ih propadne. Odluka i rizik su uvijek tvoji.</p></details>
<details class=faq><summary>Trebam li uložiti pravi novac?</summary><p>Ne. Svaki član dobije demo račun od $1.000 na kojem
kupuje i prodaje po živoj cijeni. Ako kasnije želiš trgovati pravim novcem, to radiš u svom novčaniku (npr. Phantom),
a alat ti samo da adresu tokena.</p></details>
<details class=faq><summary>Koje mreže pratite?</summary><p>Solanu: nove tokene s pump.funa i DexScreenera, starije jake
tokene i Telegram i X objave o njima.</p></details>
<details class=faq><summary>Koliko košta?</summary><p>Za pozvane je trenutno besplatno.</p></details>
<details class=faq><summary>Zašto samo na pozivnicu?</summary><p>Podaci (Helius, Apify, AI) koštaju i alat mora ostati
brz. Zato mjesta puštamo postupno i biramo ljude koji će ga stvarno koristiti.</p></details>
<details class=faq><summary>Kako se prijavim kad dobijem pozivnicu?</summary><p>Otvoriš link, upišeš ime i lozinku i za
deset sekundi si unutra. Na drugom uređaju se prijaviš istim imenom i lozinkom.</p></details>
</div></section>

<section class=final><div class=wrap><h2>Sljedeći token koji napravi 10× već je negdje u bazi.</h2>
<p class=lead style='margin:0 auto 26px'>Pitanje je samo hoćeš li ga vidjeti na vrijeme.</p>
<div class=ctas><a class='btn p' href=#pristup>🔓 Zatraži pristup</a>
<a class='btn g' href={'/' if logged_in else '/prijava'}>{'Otvori aplikaciju' if logged_in else 'Prijava'}</a></div></div></section>

<footer><div class=wrap>© {time.gmtime().tm_year} {esc(name)} · Alat za analizu podataka, ne financijski savjet.
Kripto i memecoini nose visok rizik gubitka cijelog uloga. Prošli rezultati ne jamče buduće.</div></footer>
<div class=mob-cta><a class='btn p' href=#pristup>🔓 Zatraži pristup</a></div>
<dialog id=lb><img alt=""></dialog><script>{JS}</script></body></html>"""


# ---------- access requests ----------------------------------------------------------------------------------------

def _con():
    from league import store
    con = store.connect()
    con.executescript(SCHEMA)
    return con


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


def _share(row, url):
    """Links to send the invite: WhatsApp (phone number or chooser), e-mail, Telegram."""
    text = (f"Bok {row['name']}! Evo tvoje pozivnice za KriptoRadar: {url}\n"
            "Otvori link, upiši ime i lozinku i dobiješ demo račun od $1.000.")
    c = (row["contact"] or "").strip()
    out = []
    digits = re.sub(r"[^\d+]", "", c)
    if re.fullmatch(r"\+?\d{8,15}", digits):
        num = digits.lstrip("+")
        if num.startswith("0"):
            num = "385" + num[1:]   # Croatian number written locally
        out.append(f"<a class=b href=\"https://wa.me/{num}?text={quote(text)}\" target=_blank rel=noopener>📲 WhatsApp</a>")
    else:
        out.append(f"<a class=b href=\"https://wa.me/?text={quote(text)}\" target=_blank rel=noopener>📲 WhatsApp</a>")
    if "@" in c and "." in c.split("@")[-1] and not c.startswith("@"):
        out.append(f"<a class=b href=\"mailto:{esc(c)}?subject={quote('Tvoja pozivnica za KriptoRadar')}&body={quote(text)}\">"
                   "✉️ E-mail</a>")
    if c.startswith("@") or "t.me/" in c:
        h = c.split("t.me/")[-1].lstrip("@")
        out.append(f"<a class=b href=\"https://t.me/{esc(h)}\" target=_blank rel=noopener>✈️ Telegram</a>")
    return " ".join(out)


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
    out = []
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
            act = ("" if st == "registriran" else
                   f"<input readonly value=\"{esc(url)}\" data-inv=\"{esc('/registracija?k=' + quote(r['invite']))}\" "
                   "onclick='this.select()' style='width:210px'> "
                   "<button type=button onclick=\"var i=this.previousElementSibling;i.select();"
                   "navigator.clipboard&&navigator.clipboard.writeText(i.value);this.textContent='✅'\">📋</button> "
                   + _share(r, url)) + (f" <span class=mut>kao {esc(joined[r['invite']])}</span>" if st == "registriran" else "")
        else:
            act = f"<span class=mut>{esc(r['handled_by'] or '')}</span>"
        out.append([ago(r["ts"]), f"<b>{esc(r['name'])}</b>", esc(r["contact"]), esc(EXP.get(r["experience"], "–")),
                    f"<span style='white-space:normal'>{esc(r['interest'] or '')}</span>",
                    f"<span class='b {kind}'>{esc(lab)}</span>", act])
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
            msg = f"Pozivnica za {r['name']} je spremna: kopiraj link ili ga pošalji gumbom u retku."
        else:
            con.execute("UPDATE access_requests SET status='odbijen', handled_by=?, handled_ts=? WHERE id=?",
                        (user, int(time.time()), rid))
            msg = f"Zahtjev od {r['name']} je odbijen."
        con.commit()
    finally:
        con.close()
    print(f"natjecanje: {user} zahtjev {rid} {act}", flush=True)
    return f"/zahtjevi?ok={quote(msg)}"
