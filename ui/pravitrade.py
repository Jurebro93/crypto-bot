"""Page /pravi-trade, shown as "Autopilot": the bot trades real SOL from one dedicated wallet (Nicholas 3.11.,
redesigned 4.11.: the wallet on top with setup steps, everything else in short sections that open on a tap, the
tool's own picks of influencers, wallets and tokens from the last 7/14/30 days, no demo tables).

- The owner (trade/settings.owner(), Render TRADE_OWNER, default Jure) switches it on and off, sets the limits, picks
  the KOLs and wallets to follow and invites registered players.
- Invited players only look (no key or money of theirs is involved); a "Kupi i ti" link opens Jupiter in their own
  wallet.
- Follows are competition follows of the account "pravi-trade" (league/copy.py makes the demo entries and exits
  every minute); run_trade.py follow turns each of them into a real swap through Jupiter (trade/executor.py).
- Real money needs the switch here AND TRADE_LIVE=1 + SOLANA_PRIVATE_KEY in Render, which only the owner sets.
  The page never asks for the key: the owner can save the wallet's public address here (or connect Phantom, which
  only hands over the public address) so the balance and the setup steps show before the key is in Render.
- Recommendations: ui/autopilot.py.

Before anything is listed on this page (Jure 9.11., after WBTC led "Zovu sada"), it has to answer three questions,
and the code that lists it must enforce the answers, not a note: (1) does it belong here at all (a memecoin someone
actually called or bought on purpose, not a major, a wrapped asset, a tokenised share or routing noise:
kol/converge.not_a_memecoin); (2) how does it help the user make money from it right now (a live market this hour,
a measured reason, a buy form that uses the chosen exit); (3) would the owner lose money or time if it were wrong
(then it is not shown, or shown as "ne kupuj" with the reason).
"""
import os
import re
import sqlite3
import time
from urllib.parse import quote

from league import copy, store
from trade import executor, pumpportal, settings, wallet
from ui.html import ago, badge, esc, short, tip, tlink, wlink

BACK = "/pravi-trade"
TITLE = "Autopilot"
USDC = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
_BAL = {}   # (address, what) -> (ts, value): one RPC call a minute at most

CSS = """<style>
.ap-sub{color:var(--mut);margin:-4px 0 14px;font-size:14px}
.ap-card{border:1px solid var(--line);border-radius:18px;padding:14px 16px;margin:0 0 14px;background:var(--card)}
.ap-card.live{border:2px solid var(--good)}.ap-card.half{border:2px solid var(--warn)}
.ap-top{display:flex;justify-content:space-between;align-items:center;gap:8px;flex-wrap:wrap}
.ap-top b{font-size:16px}
.ap-addr{font-size:13px;margin:6px 0 2px;word-break:break-all}
.ap-bal{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin:10px 0}
.ap-bal div{background:var(--soft);border-radius:12px;padding:8px 10px}
.ap-bal b{display:block;font-size:18px;font-variant-numeric:tabular-nums}.ap-bal span{font-size:12px;color:var(--mut)}
.ap-btns{display:flex;gap:8px;flex-wrap:wrap;margin-top:8px}.ap-btns form{margin:0}
.ap-btns button{min-height:42px}
.ap-go{background:var(--good)!important;color:#fff!important;border-color:var(--good)!important;font-weight:600}
.ap-stop{background:var(--bad)!important;color:#fff!important;border-color:var(--bad)!important}
.ap-w{margin:6px 0;padding:7px 10px;border-radius:10px;font-size:13px;background:var(--warnbg)}
.ap-w.bad{background:var(--badbg)}
.ap-day{font-size:13px;color:var(--mut);margin:6px 0 0}
details.ap-sec{border:1px solid var(--line);border-radius:16px;padding:0;margin:0 0 10px;background:var(--card)}
details.ap-sec>summary{list-style:none;padding:13px 16px;display:flex;justify-content:space-between;gap:10px;
  align-items:center;color:var(--fg);font-weight:600;cursor:pointer;user-select:none;-webkit-user-select:none;
  -webkit-touch-callout:none;touch-action:manipulation}
details.ap-sec>summary::-webkit-details-marker{display:none}
details.ap-sec>summary .m{font-weight:400;color:var(--mut);font-size:13px;text-align:right}
details.ap-sec>summary::after{content:'▾';color:var(--mut);margin-left:4px}details.ap-sec[open]>summary::after{content:'▴'}
details.ap-sec>.in{padding:0 16px 14px}
details.ap-it{border-top:1px solid var(--line);padding:0}
details.ap-it>summary{list-style:none;padding:10px 0;display:flex;justify-content:space-between;gap:8px;align-items:center;
  cursor:pointer;user-select:none;-webkit-user-select:none;-webkit-touch-callout:none;touch-action:manipulation}
details.ap-it>summary::-webkit-details-marker{display:none}
details.ap-it>summary .k{font-size:13px;color:var(--mut);text-align:right;white-space:nowrap}
details.ap-it p{margin:0 0 8px;font-size:14px;line-height:1.45}
details.ap-it form{margin:0 0 10px;display:flex;gap:6px;flex-wrap:wrap;align-items:center}
.ap-win{display:inline-flex;border:1px solid var(--line);border-radius:999px;overflow:hidden;margin:2px 0 8px}
.ap-win button{border:0;border-radius:0;background:none;padding:6px 14px;min-height:34px;color:var(--mut)}
.ap-win button.on{background:var(--fg);color:#fff}
.ap-steps{margin:8px 0 0;padding-left:0;list-style:none;counter-reset:s}
.ap-steps li{margin:0 0 12px;padding-left:30px;position:relative;font-size:14px;line-height:1.45}
.ap-steps li::before{position:absolute;left:0;top:0;width:22px;height:22px;border-radius:50%;text-align:center;
  line-height:22px;font-size:12px;background:var(--soft);counter-increment:s;content:counter(s)}
.ap-steps li.ok::before{content:'✓';background:var(--good);color:#fff}
.ap-steps code{font-size:12px}.ap-steps form{margin:6px 0 0;display:flex;gap:6px;flex-wrap:wrap}
.ap-tag{font-size:11px;padding:1px 7px;border-radius:999px;background:var(--soft);color:var(--mut);margin-left:4px;
  font-weight:400}
.ap-tag.moon{background:var(--warnbg);color:var(--warn)}.ap-tag.dugo{background:var(--goodbg);color:var(--good)}
.ap-lim label{display:flex;justify-content:space-between;gap:10px;align-items:center;margin:8px 0;font-size:14px}
.ap-lim input[type=text],.ap-lim input:not([type]){width:90px}
.ap-pos{border-top:1px solid var(--line);padding:10px 0;font-size:14px}
.ap-pos .r{display:flex;justify-content:space-between;gap:8px;flex-wrap:wrap}
@media(max-width:700px){.ap-bal b{font-size:16px}}
</style>"""

JS = """<script>(()=>{document.querySelectorAll('.ap-win').forEach(sw=>{const g=sw.dataset.g;
sw.querySelectorAll('button').forEach(b=>b.onclick=()=>{sw.querySelectorAll('button').forEach(x=>x.classList.toggle('on',x===b));
document.querySelectorAll('[data-pane="'+g+'"]').forEach(p=>p.hidden=p.dataset.w!==b.dataset.w)})});
const pb=document.getElementById('ap-phantom');if(pb)pb.onclick=async()=>{const p=(window.phantom&&window.phantom.solana)||window.solana;
if(p&&p.isPhantom){try{const r=await p.connect();document.getElementById('ap-addr').value=r.publicKey.toString();
document.getElementById('ap-addr-f').submit()}catch(e){alert('Phantom nije dao adresu: '+(e.message||e))}}
else{location.href='https://phantom.app/ul/browse/'+encodeURIComponent(location.href)+'?ref='+encodeURIComponent(location.origin)}}})()</script>"""


def _rpc_cached(addr, what, fn):
    if not addr:
        return None
    hit = _BAL.get((addr, what))
    if hit and time.time() - hit[0] < 60:
        return hit[1]
    try:
        val = fn(addr)
    except Exception:  # noqa: BLE001 - RPC down: the page still renders
        val = None
    _BAL[(addr, what)] = (time.time(), val)
    return val


def _balance(addr):
    return _rpc_cached(addr, "sol", wallet.sol_balance)


def _usdc(addr):
    return _rpc_cached(addr, "usdc", lambda a: wallet.token_raw_balance(a, USDC) / 1e6)


def _cfg(tcon):
    try:
        base = executor.load_config()
    except (OSError, ValueError):
        base = {}
    return settings.merged({"size_sol": 0.05, "max_sol_per_day": 0.5, "max_open": 5, "min_sol_reserve": 0.05,
                            "max_cost_pct": 6, "max_loss_day": 0.3, "max_signal_age_s": 180, **base}, tcon)


def _tcon():
    return executor.connect(settings.DB)


def _league_account(con):
    """The follows' demo account gets a big balance, so the demo side never skips a call for lack of cash
    (the real limits are the ones on this page)."""
    con.execute("INSERT OR IGNORE INTO accounts VALUES (?,?,?)", (settings.LEAGUE_USER, 1e9, int(time.time())))
    con.commit()


def _addr(tcon):
    """(address the page shows, address of the key in Render or None, address the owner saved here or None)."""
    key = wallet.address() if wallet.can_sign() else None
    saved = settings.raw(tcon).get("wallet_pub") or None
    env = os.environ.get("SOLANA_PUBLIC_KEY") or None
    return key or saved or env, key, saved or env


def _render_env_url():
    sid = os.environ.get("RENDER_SERVICE_ID")
    return f"https://dashboard.render.com/web/{quote(sid)}/env" if sid else "https://dashboard.render.com"


def _need_sol(cfg, n_open):
    return cfg["size_sol"] + executor.BUY_OVERHEAD_SOL + executor.reserve_sol(cfg, n_open + 1)


def _setup(tcon, cfg, addr, key_addr, saved, sol, usdc, n_open):
    """The four steps to a working wallet, ticked from what we can see. Open while anything is missing."""
    need = _need_sol(cfg, n_open)
    steps = [
        (bool(addr), "<b>Napravi zaseban račun u Phantomu.</b> U Phantomu dodirni ikonu računa gore lijevo → "
                     "<i>Add / Connect Wallet</i> → <i>Create New Account</i>. Ne koristi glavni wallet: bot smije "
                     "potrošiti sve što je u ovom."
         + ('<form method=post action=/pravi-trade/wallet id=ap-addr-f>'
            f'<input id=ap-addr name=addr placeholder="javna adresa walleta" value="{esc(saved or "")}" '
            'style="flex:1;min-width:200px" autocomplete=off spellcheck=false>'
            '<button>Spremi adresu</button>'
            '<button type=button id=ap-phantom title="Phantom daje samo javnu adresu, ništa ne potpisuje">'
            'Poveži Phantom (samo adresa)</button></form>')),
        (sol is not None and sol >= need,
         f"<b>Uplati SOL na tu adresu.</b> Za prvu kupnju treba barem <b>{need:.3f} SOL</b> (ulog {cfg['size_sol']:g} + "
         f"naknade i rezerva za prodaju {tip('Rezerva: dio SOL-a uvijek ostaje u walletu da bot može platiti mrežne naknade prodaje, i kad je sve drugo uloženo.')}). "
         "Imaš USDC? Bot kupuje SOL-om i njime plaća naknade, pa USDC prvo zamijeni: "
         '<a href="https://jup.ag/swap/USDC-SOL" target=_blank rel=noopener>Zamijeni USDC u SOL na Jupiteru ↗</a>'
         + (f'<br><span class=mut>Sada u walletu: {usdc:.2f} USDC.</span>' if usdc else "")),
        (executor.armed(),
         "<b>Ključ bot-walleta postavlja samo vlasnik, izravno u Renderu.</b> U "
         f'<a href="{_render_env_url()}" target=_blank rel=noopener>Render → Environment ↗</a> moraju postojati '
         "<code>SOLANA_PRIVATE_KEY</code> i <code>TRADE_LIVE</code> = <code>1</code>. Aplikacija ključ nikad ne traži, "
         "ne sprema i ne prikazuje, i nitko ga ne upisuje ovdje ni u chat."),
        (bool(cfg["on"]), "<b>Odaberi koga bot prati</b> (preporuke ispod) i dodirni <i>Uključi Autopilot</i>. "
                          "Za prvi put stavi ulog 0,01 SOL u Limitima i pogledaj prvu kupnju na Solscanu."),
    ]
    done = sum(1 for ok, _ in steps if ok)
    warn = ""
    if key_addr and saved and key_addr != saved:
        warn = (f'<p class="ap-w bad">⛔ Ključ u Renderu pripada drugom walletu (<code>{esc(short(key_addr))}</code>) '
                f'nego spremljena adresa (<code>{esc(short(saved))}</code>). Bot trguje s walletom ključa.</p>')
    items = "".join(f'<li class="{"ok" if ok else ""}">{txt}</li>' for ok, txt in steps)
    return (f'{warn}<details class=ap-sec style="margin:10px 0 0"{"" if done == len(steps) else " open"}><summary>'
            f'Postavljanje walleta <span class=m>{done}/{len(steps)} gotovo</span></summary>'
            f'<div class=in><ol class=ap-steps>{items}</ol></div></details>')


def _wallet_card(tcon, cfg, con, owner):
    """Top of the page: the trading wallet, its money, the switch and anything that stops a trade right now."""
    armed, on = executor.armed(), cfg["on"]
    addr, key_addr, saved = _addr(tcon)
    sol, usdc = _balance(addr), _usdc(addr)
    n_open = tcon.execute("SELECT COUNT(*) FROM positions WHERE status='open' AND mode=?",
                          ("live" if on and armed else "dry",)).fetchone()[0]
    if on and armed:
        cls, state = "live", badge("🟢 UKLJUČEN: trguje pravim novcem", "good")
    elif on:
        cls, state = "half", badge("🟡 Uključen, ali bez ključa: radi probno", "warn")
    else:
        cls, state = "", badge("⚪ ISKLJUČEN: samo probno, bez novca")
    b = [f'<section class="ap-card {cls}"><div class=ap-top><b>Wallet za trade</b>{state}</div>']
    if addr:
        b.append(f'<div class=ap-addr translate=no><code>{esc(addr)}</code> '
                 f'<a href="#" role=button data-m="{esc(addr)}" onclick="var m=this.dataset.m,b=this;'
                 f"(navigator.clipboard?navigator.clipboard.writeText(m):Promise.reject()).then(function(){{b.textContent='✅ kopirano'}},"
                 f"function(){{prompt('Kopiraj adresu:',m)}});return false\">📋 kopiraj</a> · "
                 f'<a href="https://solscan.io/account/{quote(addr)}" target=_blank rel=noopener>Solscan ↗</a></div>')
    else:
        b.append('<p class=mut style="margin:6px 0">Wallet još nije postavljen.</p>')
    b.append('<div class=ap-bal>'
             f'<div><b>{"–" if sol is None else f"{sol:.3f}"}</b><span>SOL</span></div>'
             f'<div><b>{"–" if usdc is None else f"{usdc:.2f}"}</b><span>USDC</span></div>'
             f'<div><b>{n_open}/{cfg["max_open"]}</b><span>otvoreno {tip("Koliko pozicija bot sada drži, od najviše dopuštenih u Limitima.")}</span></div></div>')
    if cfg.get("sell_all"):
        b.append('<p class="ap-w bad">Prodaja svega je u tijeku…</p>')
    if owner:
        b.append('<div class=ap-btns>')
        if on:
            b.append('<form method=post action=/pravi-trade/switch onsubmit="return confirm(\'Isključiti Autopilot? Nove '
                     'kupnje staju odmah, otvorene pozicije se i dalje prodaju po pravilima.\')"><input type=hidden name=on '
                     'value=0><button>⏸ Isključi Autopilot (nove kupnje staju)</button></form>')
        else:
            b.append('<form method=post action=/pravi-trade/switch onsubmit="return confirm(\'Uključiti Autopilot? Bot će '
                     'SAM kupovati pravim SOL-om iz walleta, i preko noći, unutar Limita, dok ne dodirneš Isključi.\')">'
                     '<input type=hidden name=on value=1><button class=ap-go>▶ Uključi Autopilot (pravi novac)</button></form>')
        if on or n_open:   # nothing to sell and nothing running: no red button
            b.append('<form method=post action=/pravi-trade/sellall onsubmit="return confirm(\'Prodati SVE otvorene '
                     'pozicije odmah i isključiti Autopilot?\')"><button class=ap-stop>🛑 Prodaj sve i isključi</button></form>')
        b.append('</div>')
    b.append(_warnings(tcon, cfg, con))
    b.append(_today(tcon, cfg))
    if owner:
        b.append(_setup(tcon, cfg, addr, key_addr, saved, sol, usdc, n_open))
    b.append("</section>")
    return "".join(b)


def _today(tcon, cfg):
    now = time.time()
    mode = "live" if executor.is_live(cfg) else "dry"
    start = executor._day_start(now, cfg.get("day_tz"))
    spent = tcon.execute("SELECT COALESCE(SUM(sol_in),0) FROM positions WHERE mode=? AND opened_ts>=? AND status IN "
                         "('open','closed','pending')", (mode, start)).fetchone()[0]
    pnl = executor.day_pnl(tcon, now, mode, cfg.get("day_tz"))
    if not spent and not pnl:
        return ""
    word = "pravo" if mode == "live" else "probno"
    return (f'<p class=ap-day>Danas ({word}): potrošeno {spent:.3f} od {cfg["max_sol_per_day"]:g} SOL · rezultat (uz sve naknade) '
            f'<span class="{"pos" if pnl > 0 else "neg" if pnl < 0 else ""}">{pnl:+.4f} SOL</span></p>')


def _sec(title, meta, inner, open_=False, sid="", hidden=False):
    return (f'<details class=ap-sec{f" id={sid}" if sid else ""}{" open" if open_ else ""}{" hidden" if hidden else ""}><summary>{title}'
            f'<span class=m>{meta}</span></summary><div class=in>{inner}</div></details>')


# ---------- who the bot follows ----------------------------------------------------------------------------------

def _auto_box(st, owner):
    """The switch that lets the tool choose whom to follow (Nicholas 4.11.: "neka alat sam odredi koga pratit")."""
    from ui.autopilot import WINDOWS
    on, days, n = bool(st.get("auto_pick")), int(st.get("auto_days") or 14), int(st.get("auto_n") or 3)
    what = (f"<b>🤖 Alat sam bira koga prati:</b> {'uključeno' if on else 'isključeno'}. "
            f"{tip('Svaki sat alat uzme najbolje influencere (samo one koje pratimo uživo) i wallete iz preporuka za odabrano razdoblje. Koga je on dodao, njega i makne kad ispadne iz najboljih (dvostruko širi popis, da se ne mijenja svaki sat). Tvoja ručna praćenja ne dira. Kad nekoga sam prestaneš pratiti, alat ga više ne vraća.')}")
    if on:
        what += f" Bira {n} influencera i {n} walleta po rezultatima zadnjih {days} dana, provjera svaki sat."
    log = st.get("auto_log") or []
    hist = "".join(f'<li>{"➕ dodao" if x["op"] == "+" else "➖ maknuo"} '
                   f'{"@" + esc(x["target"]) if x["kind"] == "kol" else esc(short(x["target"]))} '
                   f'<span class=mut>({esc(ago(x["ts"])[0])}): {esc(x["why"])}</span></li>' for x in log[:5])
    hist = f'<details class=ap-it><summary><span>Zadnje promjene alata</span><span class=k>{len(log)}</span></summary><ul style="margin:0 0 8px;padding-left:18px;font-size:13px">{hist}</ul></details>' if log else ""
    if not owner:
        return f'<p style="font-size:14px;margin:0 0 8px">{what}</p>{hist}'
    days_opt = "".join(f'<option value={d}{" selected" if d == days else ""}>zadnjih {d} dana</option>' for d in WINDOWS)
    n_opt = "".join(f'<option value={k}{" selected" if k == n else ""}>{k} + {k}</option>' for k in (1, 2, 3, 5))
    form = ('<form method=post action=/pravi-trade/auto class=ap-btns style="align-items:center;margin:0 0 10px">'
            f'<input type=hidden name=on value={"0" if on else "1"}>'
            f'<label>po <select name=days>{days_opt}</select></label>'
            f'<label>koliko <select name=n aria-label="Koliko influencera + walleta">{n_opt}</select></label>'
            + ('<button name=save value=1 onclick="this.form.on.value=1">Spremi</button>'
               '<button onclick="return confirm(\'Isključiti? Koga je alat dodao, ostaje praćen dok ga ne makneš.\')">'
               'Isključi automatski izbor</button>' if on else
               '<button class=ap-go onclick="return confirm(\'Alat će sam dodavati i micati influencere i wallete koje bot '
               'prati pravim novcem (kad je Autopilot uključen). Uključiti?\')">🤖 Neka alat sam bira</button>')
            + '</form>')
    return f'<p style="font-size:14px;margin:0 0 6px">{what}</p>{form}{hist}'


def _follows(con, owner, st=None, prefill=""):
    st = st or {}
    auto_ids = {int(i) for i in st.get("auto_follows") or []}
    fl = copy.follows(con, settings.LEAGUE_USER)
    res = copy.follow_results(con)
    items = []
    for f in fl:
        r = res.get(f["id"], {"n": 0, "closed": 0, "wins": 0, "pnl": 0.0})
        if f["kind"] == "ekipa":
            who = "🤝 " + " + ".join(f'<a href="/kol/{quote(m)}">{"✈ " + esc(m[3:]) if m.startswith("tg:") else "@" + esc(m)}</a>'
                                    for m in copy.members_of(f["target"]))
        else:
            who = (f'<a href="/kol/{quote(f["target"])}">@{esc(f["target"])}</a>' if f["kind"] == "kol"
                   else wlink(f["target"]) + (f" {esc(f['label'])}" if f["label"] else ""))
        stop = (f'<form method=post action=/pravi-trade/stop><input type=hidden name=id value={f["id"]}>'
                '<button>Prestani pratiti</button></form>') if owner else ""
        by = '<span class="ap-tag dugo">🤖 alat</span>' if f["id"] in auto_ids else ""
        items.append(f'<details class=ap-it><summary><span>{who}<span class=ap-tag>'
                     f'{"influencer" if f["kind"] == "kol" else ("ekipa" if f["kind"] == "ekipa" else "wallet")}</span>{by}</span><span class=k>{r["n"]} ulaza</span>'
                     f'</summary><p>Najviše {f["per_day"]} ulaza na dan · izlaz: {esc(copy.describe_exit(f["exit"]) or "zadano")}'
                     f' · prati od {esc(ago(f["created"])[0])}{" · dodao ga je alat" if by else ""}</p>{stop}</details>')
    names = ", ".join(("@" + f["target"]) if f["kind"] == "kol" else (f["label"] or short(f["target"])) for f in fl[:3])
    pre = esc(prefill or "")
    meta = (("🤖 " if st.get("auto_pick") else "")
            + (f"{len(fl)}: {esc(names)}{'…' if len(fl) > 3 else ''}" if fl else "još nikoga"))
    anyone = ""
    if owner:   # 9.11. (Jure): follow any wallet or influencer from the whole database, not only the recommended ones
        anyone = ('<form method=post action=/pravi-trade/follow style="margin:10px 0 4px"><input type=hidden name=kind value=auto>'
                  f'<input name=target placeholder="adresa walleta, @influencer, tg:kanal ili ekipa: tg:a, tg:b, @c" required value="{pre}" style="flex:1;min-width:220px">'
                  '<label>na dan <input name=per_day value=5 inputmode=numeric style="width:46px"></label>'
                  '<select name=exit aria-label="Izlaz"><option value="">zadano</option><option value=mirror>prodaj kad on proda</option>'
                  f'<option value=tpsl{" selected" if pre else ""}>moj TP/SL</option></select><input name=tp placeholder="TP %" size=6> <input name=sl placeholder="SL %" size=6>'
                  '<label>do MC <input name=max_mcap placeholder="npr. 1M" size=6></label> <label>ne ako je već <input name=max_runup placeholder="+25 %" size=5></label> '
                  '<label>od <select name=min_callers aria-label="Koliko iz ekipe mora zvati"><option value=1>1. poziva</option><option value=2>2 zovu</option><option value=3>3 zovu</option></select></label>'
                  '<button>Zaprati</button></form><p class=mut style="font-size:13px;margin:0 0 8px">Ekipa = više računa odvojenih zarezom: '
                  'jedan ulaz po tokenu čim prvi od njih objavi (ili kad ih zove 2–3), samo dok je token ispod zadanog MC-a (zadano $1M) i '
                  'nije već narastao više od zadanog (+25 %) od poziva. Wallet koji još ne pratimo uživo dodaje se u Helius webhook odmah.</p>')
    inner = _auto_box(st, owner) + anyone + ("".join(items) or '<p class=mut style="margin:0">Još nikoga. Upiši koga pratiti ili odaberi iz preporuka ispod.</p>')
    return _sec("Koga bot prati", meta, inner, open_=not fl, sid="pratim")


def _detect_kind(target):
    """'auto' follow form: a base58 address is a wallet, 'tg:kanal' a Telegram channel, anything else an X handle."""
    t = (target or "").strip().lstrip("@")
    if "," in t:   # 9.11.: several accounts = a crew (one entry per token, conditions on MC and run-up)
        return "ekipa", t
    if t.startswith("tg:"):
        return "kol", t
    if re.fullmatch(r"[1-9A-HJ-NP-Za-km-z]{32,44}", t):
        return "wallet", t
    return "kol", t.split("/")[-1]


def _parse_usd(x):
    """'1M', '1,5M', '800k', '1000000' -> float; None when blank."""
    t = (x or "").strip().lower().replace("$", "").replace(" ", "").replace(",", ".")
    if not t:
        return None
    mult = 1e6 if t.endswith("m") else (1e3 if t.endswith("k") else 1)
    return float(t.rstrip("mk")) * mult


def _parse_pct(x):
    t = (x or "").strip().replace("%", "").replace("+", "").replace(",", ".")
    return float(t) / 100 if t else None


EKIPA_MAX_MCAP, EKIPA_MAX_RUNUP = 1_000_000, 0.25   # Jure 9.11.: "ulaz čim objave, ako je ispod 1 M $ i još nije +25 %"


def _add_live_wallet(wallet_addr):
    """A followed wallet that is not in the Helius webhook yet: resync the webhook now (kol/chainwatch.sync puts a
    player's follows first). Returns True when the webhook now has it, False when it will take the next KOL round."""
    try:
        import json as _json
        from kol import chainwatch, store as kstore
        with open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "kol", "config.json")) as f:
            cfg = _json.load(f)
        kcon = kstore.connect()
        try:
            chainwatch.sync(kcon, cfg["chain"])
        finally:
            kcon.close()
        return wallet_addr in _live_wallets()
    except Exception as e:  # noqa: BLE001
        print(f"pravi trade: webhook sync nakon praćenja nije uspio: {type(e).__name__}: {e}", flush=True)
        return False


# ---------- the tool's picks ------------------------------------------------------------------------------------

def _windows(group, panes, default=14):
    from ui.autopilot import WINDOWS
    sw = (f'<div class=ap-win data-g={group}>' + "".join(
        f'<button type=button data-w={d} class="{"on" if d == default else ""}">{d} d</button>' for d in WINDOWS) + '</div>')
    return sw + "".join(f'<div data-pane={group} data-w={d}{"" if d == default else " hidden"}>{panes.get(d, "")}</div>'
                        for d in WINDOWS)


def followed_targets(con):
    """Everything the real-money account already follows: KOL handles, crew members, wallets, and whole crews
    (the sorted member list). 9.11. (Jure): "once a crew or account is followed it must leave the 'whom to follow'
    lists" (he followed Arc Trending and it stayed on top)."""
    out = set()
    for f in copy.follows(con, settings.LEAGUE_USER):
        out.add(f["target"])
        if f["kind"] == "ekipa":
            out |= set(copy.members_of(f["target"]))
    return out


def _follow_btn(kind, target, label, have, owner):
    if (kind, target) in have:
        return badge("već pratiš ✓", "good")
    if not owner:
        return ""
    return ('<form method=post action=/pravi-trade/follow onsubmit="return confirm(\'Bot će kupovati pravim novcem na '
            'svaki njegov ' + ("call" if kind == "kol" else "kup") + ' (kad je Autopilot uključen), dok ga ne prestaneš '
            f'pratiti. Pratiti?\')"><input type=hidden name=kind value={kind}><input type=hidden name=target '
            f'value="{esc(target)}"><input type=hidden name=label value="{esc(label or "")}">'
            '<input type=hidden name=per_day value=5><button>Prati pravim novcem</button></form>')


def _kol_section(con, owner):
    from ui import autopilot
    recs = autopilot.kol_recs()
    have = {(f["kind"], f["target"]) for f in copy.follows(con, settings.LEAGUE_USER)}
    followed = followed_targets(con)
    panes = {}
    any_items = False
    for d, rows in recs.items():
        items = []
        for r in [x for x in rows if x["handle"] not in followed][:autopilot.SHOW]:
            s = r["s"]
            any_items = True
            items.append(f'<details class=ap-it><summary><span><a href="/kol/{quote(r["handle"])}">@{esc(r["handle"])}</a>'
                         f'{" ⚡" if r["live"] else ""}</span><span class=k>{s["hit"]:.0%} pogodaka · {s["n"]} callova</span>'
                         f'</summary><p>{esc(r["why"])}</p>{_follow_btn("kol", r["handle"], "", have, owner)}</details>')
        panes[d] = "".join(items) or f'<p class=mut>U zadnjih {d} dana nitko nema barem {autopilot.MIN_CALLS} izmjerena calla s malo rugova.</p>'
    if not any_items:   # 9.11. (Jure): an empty list is noise; the section appears when there is somebody to follow
        return ""
    best = next((r for r in recs.get(14) or [] if r["handle"] not in followed), None)
    meta = f'najbolji 14 d: @{esc(best["handle"])}' if best else "po zadnjih 7/14/30 dana"
    inner = (f'<p class=mut style="margin:0 0 6px;font-size:13px">Pogodak = cijena je u 24 h nakon calla narasla +50% ili '
             f'više {tip("Mjerimo svaki call: najveći rast u 24 h, rezultat nakon 24 h i je li token rugan. Rugovi se broje dvostruko protiv. ⚡ = pratimo ga uživo, pa bot stigne ući na vrijeme.")}</p>'
             + _windows("kol", panes))
    return _sec("Preporučeni influenceri", meta, inner, sid="influenceri")


def _dokazani_items(rows, have, owner, names=None):
    """The proven-twice wallets (wallets/dokazani.py) with their own on-chain result before and after the cut."""
    names = names or {}
    items = []
    for r in rows:
        nm = names.get(r["wallet"])
        nm = f' <span class=mut>{esc(nm)}</span>' if nm else ""
        style = {"swing": "swing", "scalper": "scalper", "bot": "bot", "sniper": "sniper"}.get(r.get("style") or "", r.get("style") or "")
        why = (f'Prije reza: {r["realized_before"]:+.1f} SOL na {r["closed_before"]} zatvorenih ({r["win_before"]:.0%} u plusu). '
               f'Poslije reza: {r["realized_after"]:+.1f} SOL na {r["closed_after"]} zatvorenih'
               + (f' ({r["win_after"]:.0%} u plusu)' if r.get("win_after") is not None else "") + ". "
               + (f'Drži medijan {r["hold_min"]:.0f} min, {r["tpd"]:.0f} tradeova dnevno' if r.get("hold_min") is not None and r.get("tpd") is not None else "")
               + (f', stil {style}.' if style else "."))
        items.append(f'<details class=ap-it><summary><span>{wlink(r["wallet"])}{nm}</span>'
                     f'<span class=k>{r["realized_after"]:+.1f} SOL poslije reza · {r["closed_before"] + r["closed_after"]} zatv.</span></summary>'
                     f'<p>{why}</p>{_follow_btn("wallet", r["wallet"], names.get(r["wallet"]) or "", have, owner)}</details>')
    return "".join(items)


def _wallet_section(con, owner):
    from ui import autopilot
    recs = autopilot.wallet_recs()
    have = {(f["kind"], f["target"]) for f in copy.follows(con, settings.LEAGUE_USER)}
    followed = followed_targets(con)
    # 9.11. (Jure: "preporučeni walleti trebali bi biti povijesno analizirani, s PnL-om"): the proven-twice list
    # first (wallets/dokazani.py: own on-chain result before AND after a 5-day cut, copyable style only)
    try:
        from wallets import dokazani as _dok
        proven = [r for r in _dok.latest() if r["wallet"] not in followed][:autopilot.TOP]
    except Exception:  # noqa: BLE001
        proven = []
    recs = {d: [r for r in rows if r["wallet"] not in followed] for d, rows in recs.items()}
    if not proven and not any(recs.values()):
        return ""
    names = {}
    try:
        kc = copy._ro(copy._paths()["kol"])
        if kc is not None:
            names = {w: (f"@{tw}" if tw else (n or "")) for w, n, tw in copy._q(kc, "SELECT wallet, name, twitter FROM kol_ids")}
            kc.close()
    except Exception:  # noqa: BLE001
        pass
    dok = (f'<p class=mut style="margin:0 0 6px;font-size:13px"><b>Dokazani dvaput</b>: 5+ zatvorenih pozicija s plusom i 50 %+ dobitnih '
           f'prije reza od 5 dana, pa opet plus poslije reza; samo walleti koje se može kopirati (drže 10+ min, do 50 tradeova dnevno, '
           f'bez bot/sniper oznaka). Brojke su njihov vlastiti rezultat na lancu, ne naša kopija.</p>'
           + (_dokazani_items(proven, have, owner, names) or
              '<p class=mut>Lista se računa svaka 3 sata iz pohranjenih tradeova; prvi put nakon današnjeg deploya. Dok je prazna, nema koga kopirati.</p>'))
    panes = {}
    for d, rows in recs.items():
        items = []
        for r in rows[:autopilot.SHOW]:
            s = r["s"]
            nm = f' <span class=mut>{esc(r["name"])}</span>' if r["name"] else ""
            items.append(f'<details class=ap-it><summary><span>{wlink(r["wallet"])}{nm}</span>'
                         f'<span class=k>{100 * s["roi"]:+.0f}% · {s["win"]:.0%} u plusu</span></summary>'
                         f'<p>{esc(r["why"])}</p>{_follow_btn("wallet", r["wallet"], r["name"], have, owner)}</details>')
        panes[d] = "".join(items) or (f'<p class=mut>U zadnjih {d} dana nijedan wallet koji pratimo uživo nema barem '
                                      f'{autopilot.MIN_CLOSED} prodana tokena u plusu.</p>')
    best = next((r for r in recs.get(14) or []), None)
    meta = f'najbolji 14 d: {100 * best["s"]["roi"]:+.0f}%' if best else "po zadnjih 7/14/30 dana"
    inner = (dok + '<p style="margin:14px 0 4px"><b>Po zadnjih 7/14/30 dana</b> (samo walleti koje pratimo uživo)</p>'
             + f'<p class=mut style="margin:0 0 6px;font-size:13px">Povrat = koliko je SOL-a vratio na tokenima koje je '
             f'kupio i prodao u tom razdoblju {tip("Iz njegovih stvarnih kupnji i prodaja na lancu (Helius). Gledamo postotak, ne SOL, jer bot ulaže svoj, manji iznos. Samo walleti koje pratimo uživo, da bot kupi u sekundama nakon njih.")}</p>'
             + _windows("wal", panes))
    meta = f"{len(proven)} dokazanih · " + meta
    return _sec("Preporučeni walleti", meta, inner, sid="walleti")


def _buy_form(mint, cfg, exit_mode, owner):
    if not owner:
        return (f'<p><a href="https://jup.ag/swap/SOL-{quote(mint)}" target=_blank rel=noopener>Kupi i ti iz svog '
                'walleta (Jupiter) ↗</a></p>')
    opts = "".join(f'<option value={v}{" selected" if v == exit_mode else ""}>{lab}</option>'
                   for v, lab in (("smart", "Smart sell"), ("tpsl", "moj TP/SL"), ("manual", "prodajem sam")))
    tp_default = cfg.get("tp_default", 15)   # the exit target chosen at the top of the page (_tp_card)
    return ('<form method=post action=/pravi-trade/buy onsubmit="return confirm(\'Kupiti ovaj token pravim novcem '
            f'(ako je Autopilot uključen)?\')"><input type=hidden name=token value="{esc(mint)}">'
            f'<label>SOL <input name=sol value="{cfg["size_sol"]:g}" inputmode=decimal style="width:64px"></label>'
            f'<select name=exit aria-label="Kako prodati">{opts}</select>'
            f'<input name=tp placeholder="TP npr. 100%" size=9{f" value={tp_default}%" if exit_mode == "tpsl" else ""}> '
            '<input name=sl placeholder="SL npr. -30%" size=9>'
            '<button>Kupi</button></form>')


def _buy_now_card(cfg, owner):
    """9.11. (Jure): at the top of the page, buy any token right now with the amount you choose: address + SOL + Kupi.
    Exit defaults to the target chosen below (TP) and the usual stop; the rest sits behind "Više"."""
    if not owner:
        return ""
    tp_default = cfg.get("tp_default", 15)
    return ('<div class=card id=kupi-odmah><b>Kupi odmah</b> <span class=mut>bilo koji token, iznos po želji</span>'
            '<form method=post action=/pravi-trade/buy onsubmit="return confirm(\'Kupiti ovaj token pravim novcem '
            '(ako je Autopilot uključen)?\')" style="margin-top:8px"><input name=token placeholder="adresa tokena ili DexScreener link" '
            'required style="flex:1;min-width:200px" autocomplete=off spellcheck=false>'
            f'<label>SOL <input name=sol value="{cfg["size_sol"]:g}" inputmode=decimal style="width:64px"></label>'
            '<button class=ap-go>Kupi</button>'
            f'<details style="flex-basis:100%"><summary class=mut style="font-size:13px">Više (izlaz: moj TP/SL, cilj +{tp_default} %)</summary>'
            '<select name=exit aria-label="Kako prodati"><option value=tpsl>moj TP/SL</option><option value=smart>Smart sell</option>'
            f'<option value=manual>prodajem sam</option></select> <input name=tp placeholder="TP" value="{tp_default}%" size=6> '
            '<input name=sl placeholder="SL npr. -20%" size=9></details></form>'
            '<p class=mut style="font-size:13px;margin:6px 0 0">Prolazi iste provjere i limite kao automatske kupnje. Pravi novac ide '
            'samo kad je Autopilot uključen; inače je ovo probna kupnja. Prodaja: gumbi 20 % / 50 % / sve kod svake pozicije.</p></div>')


TP_CHOICES = (5, 10, 15, 20, 30)


def _tp_card(cfg, owner):
    """9.11. (Jure): the exit target for new copies, chosen at the top because it is the most important part of
    the trade: 5 / 10 / 15 / 20 / 30 %. New follows and buys with 'moj TP/SL' get it when their TP box is empty."""
    cur = int(cfg.get("tp_default") or 15)
    if not owner:
        return f'<p class=mut style="font-size:13px">Cilj izlaza za nove kopije: +{cur} %.</p>'
    btns = "".join(f'<form method=post action=/pravi-trade/tp style="margin:0"><input type=hidden name=tp value={v}>'
                   f'<button class="{"on" if v == cur else ""}" style="min-height:40px{";font-weight:700" if v == cur else ""}">+{v} %</button></form>'
                   for v in TP_CHOICES)
    return (f'<div class=card id=cilj><b>Cilj izlaza za nove kopije</b> <span class=mut>sada +{cur} %</span>'
            f'<div class=ap-btns>{btns}</div><p class=mut style="font-size:13px;margin:6px 0 0">Vrijedi za svako novo praćenje i '
            'kupnju s izlazom "moj TP/SL" bez upisanog TP-a; postojeće pozicije zadržavaju svoj. Stop ostaje kako je upisan ili zadani.</p></div>')


IDEAS_EVERY_S = 60
_IDEAS_CACHE = {}   # owner flag -> (ts, html)


def latest_picks(now=None, limit=3):
    """Today's "Prijedlog za danas" picks as the Pregled box logged them (ui/prijedlog_log in hype.db), best grade
    first. 9.11. 12:30: the first version built the picks here (overview.token_rows, every hype signal) on every
    10-s poll; the UI process went 100 MB -> 1.6 GB in three minutes and the service was OOM-restarted. The box on
    Pregled is built in a child process and logs its picks; this only reads that log."""
    import sqlite3
    from ui import data
    now = now or time.time()
    path = data.HYPE_DB
    if not os.path.exists(path):
        return []
    try:
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5)
    except sqlite3.Error:
        return []
    try:
        rows = con.execute("SELECT token, razina, mcap0, conf, ts FROM prijedlog_log WHERE ts >= ? ORDER BY ts DESC LIMIT 30",
                           (int(now - 24 * 3600),)).fetchall()
    except sqlite3.Error:
        return []
    finally:
        con.close()
    order = {"visoka": 0, "srednja": 1, "niska": 2}
    out, seen = [], set()
    for tok, raz, mcap0, conf, ts in rows:
        if tok in seen:
            continue
        seen.add(tok)
        out.append({"token": tok, "razina": raz or "visoka", "mcap0": mcap0, "conf": conf, "ts": ts})
    out.sort(key=lambda p: (order.get(p["razina"], 3), -(p["conf"] or 0), -(p["ts"] or 0)))
    return out[:limit]


def ideas_inner(cfg, owner, now=None):
    """The same picks as "Prijedlog za danas" on Pregled, read from the suggestion log (never built here), with a buy
    form each. Cached IDEAS_EVERY_S."""
    now = now or time.time()
    c = _IDEAS_CACHE.get(bool(owner))
    if c and now - c[0] < IDEAS_EVERY_S:
        return c[1]
    try:
        picks = latest_picks(now)
        syms = {}
        if picks:
            from kol import store as kstore
            kc = copy._ro(kstore.DB)
            if kc is not None:
                q = ",".join("?" * len(picks))
                syms = dict(copy._q(kc, f"SELECT token, symbol FROM tokens WHERE token IN ({q})", [p["token"] for p in picks]))
                kc.close()
    except Exception as e:  # noqa: BLE001
        return f'<p class=mut>Prijedlozi trenutno nisu dostupni ({esc(type(e).__name__)}).</p>'
    if not picks:
        html = ""   # nothing concrete: the section stays hidden (Jure 9.11.: the page shows only what matters)
    else:
        out = []
        for p in picks:
            raz = p.get("razina") or "visoka"
            cls = {"visoka": "good", "srednja": "warn", "niska": "bad"}.get(raz, "")
            out.append(f'<details class=ap-it open><summary><span>{tlink(p["token"], syms.get(p["token"]))} {badge("vjerojatnost " + raz, cls)}</span>'
                       f'<span class=k>na ${(p.get("mcap0") or 0) / 1000:,.0f}k · pouzdanost {p.get("conf") or 0:.0f} · {esc(ago(p["ts"])[0])}</span></summary>'
                       f'<p>Prijedlog s Pregleda. <a href="https://dexscreener.com/solana/{quote(p["token"])}" target=_blank rel=noopener>DexScreener ↗</a></p>'
                       f'{_buy_form(p["token"], cfg, "tpsl", owner)}</details>')
        html = "".join(out)
    _IDEAS_CACHE[bool(owner)] = (now, html)
    return html


def ideas_fragment(user):
    tcon = _tcon()
    try:
        if not settings.can_view(tcon, user):
            return None
        return ideas_inner(_cfg(tcon), settings.is_owner(user))
    finally:
        tcon.close()


def _ideas_section(cfg, owner):
    inner = ideas_inner(cfg, owner)
    return _sec("Što kupiti sada", f"isti prijedlozi kao na Pregledu · ⟳ {IDEAS_EVERY_S} s", f'<div id=ap-ideje>{inner}</div>', hidden=not inner,
                open_=True, sid="ideje")


CALLERS_WINDOW_S = 3600
_CALLERS_CACHE = {"ts": 0, "html": ""}


def group_callers(events, now, window_s=CALLERS_WINDOW_S, limit=8):
    """[(token, callers[(who, platform, ts)], first_ts, last_ts)] from kol/converge.events rows, most callers first,
    then newest. 'buy' events are followed wallets' buys ('chain'); calls from X and Telegram."""
    by = {}
    for tok, ts, plat, who, kind in events:
        if kind not in ("call", "buy") or now - ts > window_s:
            continue
        d = by.setdefault(tok, {})
        if who not in d or d[who][1] > ts:
            d[who] = (plat, ts)
    out = []
    for tok, d in by.items():
        callers = sorted(((who, plat, ts) for who, (plat, ts) in d.items()), key=lambda c: c[2])
        out.append((tok, callers, callers[0][2], callers[-1][2]))
    out.sort(key=lambda r: (-len(r[1]), -r[3]))
    return out[:limit]


def followed_wallets():
    """Wallets whose buys count as "zovu": the ones the real-money account follows plus the proven-twice list; the
    other ~100 webhook wallets are data for the leaderboards, not calls."""
    out = set()
    try:
        from league import store as lstore
        con = copy._ro(lstore.DB)
        if con is not None:
            try:
                out |= {f["target"] for f in copy.follows(con, settings.LEAGUE_USER) if f["kind"] == "wallet"}
            finally:
                con.close()
    except Exception:  # noqa: BLE001
        pass
    try:
        from wallets import dokazani
        out |= set(dokazani.current())
    except Exception:  # noqa: BLE001
        pass
    return out


def gather_callers(now, window_s=CALLERS_WINDOW_S, kol_db=None, tg_db=None, hype_db=None, followed=None, limit=8, live=None):
    """[(token, callers, first_ts, last_ts, symbol, live)] worth showing: X/Telegram calls from kol/converge.events
    and buys of the followed wallets only, minus everything kol/converge.not_a_memecoin rules out, each checked live
    on DexScreener (live: {token: market} for tests; None = fetch)."""
    from kol import converge, store as kstore
    ev, _scores, _fac = converge.events(int(now), window_s, kol_db=kol_db, tg_db=tg_db, hype_db=hype_db)
    ev = [e for e in ev if e[2] != "chain"]   # chain events there are every webhook wallet: replaced below
    followed = followed_wallets() if followed is None else followed
    if followed:
        hc = copy._ro(hype_db or copy._paths()["hype"])
        if hc is not None:
            try:
                q = ",".join("?" * len(followed))
                for w, mint, ts in copy._q(hc, f"SELECT wallet, mint, ts FROM chain_trades WHERE ts >= ? AND side = 'buy' "
                                               f"AND wallet IN ({q})", (int(now) - window_s, *sorted(followed))):
                    ev.append((mint, ts, "chain", "w:" + w, "buy"))
            finally:
                hc.close()
    from kol.collect import is_solana_mint
    ev = [e for e in ev if is_solana_mint(e[0])]   # an EVM tail from a Telegram post is not a token (Jure 9.11.)
    rows = group_callers(ev, now, window_s, limit=limit * 4)
    syms, liqs = {}, {}
    kc = copy._ro(kol_db or kstore.DB)
    if kc is not None and rows:
        try:
            q = ",".join("?" * len(rows))
            for tok, sym, liq in copy._q(kc, f"SELECT token, symbol, liquidity FROM tokens WHERE token IN ({q})", [r[0] for r in rows]):
                syms[tok], liqs[tok] = sym, liq
        finally:
            kc.close()
    rows = [r for r in rows if not converge.not_a_memecoin(r[0], syms.get(r[0]), liqs.get(r[0]))]
    # every token shown is checked live (DexScreener) right now: a pair must exist, the market cap must be 30k+, it
    # must not be a big liquid token, and the rug filter must not have archived it. No pair = no row, no link.
    lv = live if live is not None else _live_cached([r[0] for r in rows[:limit * 2]], now)
    if lv is None:
        return []   # the check could not run: better nothing than an unchecked token with real money
    try:
        from rugfilter import archive
        archived = archive.blocked()
    except Exception:  # noqa: BLE001
        archived = frozenset()
    out = []
    for tok, callers, first, last in rows:
        m = lv.get(tok)
        if not m or not m.get("price") or (m.get("mcap") or 0) < 30_000 or tok in archived:
            continue
        if converge.not_a_memecoin(tok, syms.get(tok), m.get("liq")):
            continue
        out.append((tok, callers, first, last, syms.get(tok), m))
        if len(out) >= limit:
            break
    return out


_LIVE_CACHE = {"ts": 0.0, "key": (), "data": {}}


def _live_cached(tokens, now, ttl=10):
    """DexScreener state of the tokens in "Zovu sada", shared by the 2-s poll for ttl seconds (one request)."""
    key = tuple(tokens)
    if not key:
        return {}
    if _LIVE_CACHE["key"] == key and now - _LIVE_CACHE["ts"] < ttl:
        return _LIVE_CACHE["data"]
    from ui import prijedlog
    data = prijedlog.live_market(list(key))
    if data is None:
        return None
    _LIVE_CACHE.update(ts=now, key=key, data=data)
    return data


def callers_inner(cfg, owner, now=None):
    """Live: who called which token in the last hour (X, Telegram, followed wallets). The point (Jure 9.11.): see the
    FIRST caller of a token at once and buy before the rest of his crew calls it."""
    now = now or time.time()
    if now - _CALLERS_CACHE["ts"] < 2 and _CALLERS_CACHE["html"]:
        return _CALLERS_CACHE["html"]
    try:
        rows = gather_callers(now)
    except Exception as e:  # noqa: BLE001
        return f'<p class=mut>Pozivi trenutno nisu dostupni ({esc(type(e).__name__)}).</p>'
    followed = set()
    try:
        from league import store as lstore
        lc = copy._ro(lstore.DB)
        if lc is not None:
            try:
                followed = followed_targets(lc)
            finally:
                lc.close()
    except Exception:  # noqa: BLE001
        pass
    # a token whose every caller the bot already follows is the bot's job, not a suggestion (Jure 9.11.)
    rows = [r for r in rows if not all((c[0][2:] if c[1] == "chain" else c[0]) in followed for c in r[1])]
    if not rows:
        html = ""   # the section hides itself while there is nothing to show
    else:
        items = []
        for tok, callers, first, last, sym, m in rows:
            who = ", ".join((f"👛 {c[0][2:8]}…" if c[1] == "chain" else ("✈ " + c[0][3:] if c[0].startswith("tg:") else "@" + c[0])) for c in callers[:6])
            state = (f"MC ${m['mcap'] / 1000:,.0f}k · likv. ${m['liq'] / 1000:,.0f}k · 1 h {m['ch_h1']:+.0f} %"
                     if m.get("ch_h1") is not None else f"MC ${m['mcap'] / 1000:,.0f}k · likv. ${m['liq'] / 1000:,.0f}k")
            more = f" +{len(callers) - 6}" if len(callers) > 6 else ""
            handles = ",".join(c[0] for c in callers if c[1] != "chain")
            follow = (f'<form method=post action=/pravi-trade/followall onsubmit="return confirm(\'Zapratiti ove račune kao ekipu?\')">'
                      f'<input type=hidden name=handles value="{esc(handles)}"><button>Zaprati kao ekipu ({len(handles.split(","))})</button></form>'
                      if owner and handles else "")
            items.append(f'<details class=ap-it open><summary><span>{tlink(tok, sym)} <span class=ap-tag>{len(callers)} {"zove" if len(callers) == 1 else "zovu"}</span></span>'
                         f'<span class=k>prvi {esc(ago(first)[0])}{(" · zadnji " + esc(ago(last)[0])) if last != first else ""}</span></summary>'
                         f'<p>{esc(who)}{more} · {esc(state)} · <a href="https://dexscreener.com/solana/{quote(tok)}" target=_blank rel=noopener>DexScreener ↗</a></p>'
                         f'{_buy_form(tok, cfg, "tpsl", owner)}{follow}</details>')
        html = "".join(items)
    _CALLERS_CACHE.update(ts=now, html=html)
    return html


def callers_fragment(user):
    tcon = _tcon()
    try:
        if not settings.can_view(tcon, user):
            return None
        return callers_inner(_cfg(tcon), settings.is_owner(user))
    finally:
        tcon.close()


def _callers_section(cfg, owner):
    inner = callers_inner(cfg, owner)
    return _sec("Zovu sada", f"zadnjih 60 min · X, Telegram, tvoji i dokazani novčanici · ⟳ {LOG_EVERY_S} s",
                f'<div id=ap-zovu>{inner}</div><p class=mut style="font-size:13px;margin:8px 0 0">'
                'Tko od njih stvarno nosi +5/10/15/20/30 % nakon poziva: <a href="/ekipe">Ekipe i minutna provjera</a>.</p>',
                open_=True, sid="zovu", hidden=not inner)


def _token_section(cfg, owner):
    from ui import autopilot
    recs = autopilot.token_recs()
    items = []
    from kol import converge
    for kind, lab, ex in (("dugo", "dugoročno", "manual"), ("moon", "moonshot", "smart")):
        for r in recs.get(kind) or []:
            if converge.not_a_memecoin(r["mint"], r.get("symbol")):   # 9.11.: never a major, wrapped asset or xStock
                continue
            items.append(f'<details class=ap-it><summary><span>{tlink(r["mint"], r["symbol"])}</span>'
                         f'<span class="ap-tag {kind}">{lab}</span></summary><p>{esc(r["why"])}</p>'
                         f'{_buy_form(r["mint"], cfg, ex, owner)}</details>')
    nd = sum(1 for r in recs.get("dugo") or [] if not converge.not_a_memecoin(r["mint"], r.get("symbol")))
    nm = sum(1 for r in recs.get("moon") or [] if not converge.not_a_memecoin(r["mint"], r.get("symbol")))
    meta = f"{nd} dugoročna · {nm} moonshot" if items else "trenutno nema"
    head = (f'<p class=mut style="margin:0 0 6px;font-size:13px">Dugoročni su stariji tokeni koji su preživjeli; moonshot '
            f'je svjež token s jakim signalom i prošlim rug checkom {tip("Moonshot: mali, novi token koji može narasti puno, ali i pasti na nulu. Bot ga preporuča samo kad je među najjačim prijedlozima, prošao rug check i nije usred pumpe ili pada. Nijedna preporuka nije jamstvo zarade.")}</p>')
    if not items:   # 9.11. (Jure): shown only with concrete suggestions; "Kupi odmah" at the top takes any token
        return ""
    inner = head + "".join(items)
    return _sec("Preporučeni tokeni", meta, inner, sid="tokeni")


# ---------- positions -------------------------------------------------------------------------------------------

def _sell_btns(pid, pending):
    if pending is not None:
        return badge(f"prodaja {float(pending):.0%} u tijeku", "warn")
    return ('<div class=ap-btns>' + "".join(
        f'<form method=post action=/pravi-trade/sell onsubmit="return confirm(\'Prodati {lab} ove pozicije odmah?\')">'
        f'<input type=hidden name=id value={pid}><input type=hidden name=frac value={fr}><button{" class=ap-stop" if fr == "1" else ""}>Prodaj {lab}</button></form>'
        for fr, lab in (("0.2", "20%"), ("0.5", "50%"), ("1", "sve"))) + '</div>')


def _positions(tcon, viewer_buy, owner=False, pending=None):
    """Positions section: open ones first with 20/50/100 % sell buttons, closed ones behind one more tap. The inner
    part is re-fetched every LOG_EVERY_S seconds (positions_fragment) and swapped only when it changed, so a tap is
    never lost to a redraw (9.11., Jure: real money, every second counts)."""
    inner, meta, has_open = positions_inner(tcon, viewer_buy, owner, pending)
    return _sec("Pozicije", meta, f'<div id=ap-pos>{inner}</div>', open_=True, sid="pozicije")


def positions_fragment(user):
    """GET /pravi-trade/pozicije: the inner HTML of the positions section, same access as the page."""
    tcon = _tcon()
    try:
        if not settings.can_view(tcon, user):
            return None
        cfg = _cfg(tcon)
        owner = settings.is_owner(user)
        return positions_inner(tcon, not owner, owner, cfg.get("sell_req"))[0]
    finally:
        tcon.close()


def positions_inner(tcon, viewer_buy, owner=False, pending=None):
    """(inner html, meta text, has open) of the positions section."""
    pending = pending or {}
    rows = tcon.execute("SELECT id, token, symbol, opened_ts, mode, status, reason, sol_in, sol_back, qty_raw, qty_left, "
                        "closed_ts, COALESCE(fees_sol,0) FROM positions WHERE status IN ('open','closed') "
                        "ORDER BY id DESC LIMIT 60").fetchall()
    if not rows:
        return '<p class=mut style="margin:0">Još nema pozicija. Kupi odmah gore ili zaprati nekoga.</p>', "0 otvoreno", False
    sigs = dict(tcon.execute("SELECT position_id, signature FROM orders WHERE signature IS NOT NULL ORDER BY id"))
    open_, closed, tot = [], [], 0.0
    for (pid, tok, sym, ts, mode, st, why, sin, sback, q, ql, cts, fees) in rows:
        kind = badge("PRAVO", "good") if mode == "live" else badge("probno")
        if st == "open":
            act = _sell_btns(pid, pending.get(str(pid))) if owner else (
                f'<a href="https://jup.ag/swap/SOL-{quote(tok)}" target=_blank rel=noopener>Kupi i ti ↗</a>' if viewer_buy else "")
            open_.append(f'<div class=ap-pos><div class=r><span>{tlink(tok, sym)} {kind}</span><span class=mut>'
                         f'{esc(ago(ts)[0])}</span></div><div class=mut style="font-size:13px">uloženo {sin or 0:.3f} SOL · '
                         f'još drži {f"{ql / q:.0%}" if q else "–"}{f" · vraćeno {sback:.4f} SOL" if sback else ""}'
                         f'{" · " + esc(why) if why else ""}</div>{act}</div>')
        else:
            pnl = (sback or 0) - (sin or 0) - (fees or 0)
            tot += pnl if mode == "live" else 0
            sig = sigs.get(pid)
            link = (f' · <a href="https://solscan.io/tx/{esc(sig)}" target=_blank rel=noopener>Solscan ↗</a>'
                    if sig else "")
            closed.append(f'<div class=ap-pos><div class=r><span>{tlink(tok, sym)} {kind}</span>'
                          f'<span class="{"pos" if pnl > 0 else "neg" if pnl < 0 else ""}">{pnl:+.4f} SOL</span></div>'
                          f'<div class=mut style="font-size:13px">{esc(ago(cts or ts)[0])}{link}</div></div>')
    inner = "".join(open_) or '<p class=mut style="margin:0">Ništa otvoreno.</p>'
    if closed:
        inner += (f'<details class=ap-it><summary><span>Zatvorene ({len(closed)})</span><span class=k>zarada = vraćeno − '
                  f'uloženo − mrežne naknade {tip("Jupiterova naknada (0,05–0,1%) je već u iznosima. Mrežne naknade su potpis, prioritet i depozit za novi token račun (~0,002 SOL), koji se vrati kad se pozicija proda do kraja.")}'
                  f'</span></summary>{"".join(closed)}</details>')
    meta = f"{len(open_)} otvoreno" + (f" · {len(closed)} zatvoreno" if closed else "")
    return inner, meta, bool(open_)


# ---------- live trade log (Nicholas 4.11.: "log tradeova u real timeu, osvježava se puno češće") ----------------

LOG_N = 15
LOG_EVERY_S = 2   # 9.11. (Jure): every second is money; the log and the positions are re-fetched every 2 s
SIDE = {"buy": ("🟢", "kupnja"), "sell": ("🔴", "prodaja"), "rent": ("↩️", "depozit natrag")}
STATUS = {"ok": ("prošlo", "good"), "dry": ("probno", ""), "failed": ("greška", "bad"), "blocked": ("preskočeno", "warn")}


def log_html(tcon, cfg):
    """The last orders, newest first, as a small block the page re-fetches every few seconds (/pravi-trade/log)."""
    now = time.time()
    beat = cfg.get("heartbeat") or 0
    alive = f"Trade proces javio se {esc(ago(beat)[0])}" if beat else "Trade proces se još nije javio"
    head = (f'<p class=mut style="font-size:12px;margin:0 0 6px">{alive} · osvježeno '
            f'{time.strftime("%H:%M:%S", time.gmtime(now))} UTC</p>')
    rows = tcon.execute("SELECT o.ts, o.token, o.side, o.mode, o.status, o.amount_in, o.amount_out, o.error, o.reason, "
                        "o.signature, p.symbol FROM orders o LEFT JOIN positions p ON p.id = o.position_id "
                        f"ORDER BY o.id DESC LIMIT {LOG_N}").fetchall()
    if not rows:
        return head + '<p class=mut style="margin:0">Još nema nijednog naloga. Čim bot nešto kupi ili proda, pojavi se ovdje.</p>'
    # 9.11. (Jure): "osvježeno sada, a nalozi od prije 5.8 dana, što mi to govori?" Only the last 24 h (and every real
    # order of the last 7 days) is listed; older trial/skipped attempts are one line, so nothing stale looks live.
    recent = [r for r in rows if r[0] >= now - 86400 or (r[3] == "live" and r[0] >= now - 7 * 86400)]
    older = [r for r in rows if r not in recent]
    items = []
    if not recent:
        items.append('<p class=mut style="margin:0 0 6px">Danas nema naloga: bot nije ništa kupio ni pokušao kupiti.</p>')
    if older:
        kinds = ", ".join(f"{sum(1 for r in older if r[4] == k)} {STATUS.get(k, (k,))[0]}" for k in ("ok", "dry", "blocked", "failed")
                          if any(r[4] == k for r in older))
        items.append(f'<p class=mut style="font-size:12px;margin:0 0 6px">Starije od 24 h: {len(older)} naloga ({esc(kinds)}), '
                     f'zadnji {esc(ago(older[0][0])[0])}; probno = bez pravog novca, preskočeno = bot nije kupio (limit, rug, '
                     'likvidnost…).</p>')
    for ts, tok, side, mode, st, ain, aout, err, why, sig, sym in recent:
        icon, word = SIDE.get(side, ("•", side))
        lab, css = STATUS.get(st, (st, ""))
        lam = ain if side == "buy" else aout
        sol = f" {lam / executor.LAMPORTS:.4f} SOL" if lam and side in ("buy", "rent") or (lam and side == "sell" and st in ("ok", "dry")) else ""
        link = (f' · <a href="https://solscan.io/tx/{esc(sig)}" target=_blank rel=noopener>Solscan ↗</a>' if sig else "")
        note = esc((err or why or "")[:140])
        items.append(f'<div class=ap-pos><div class=r><span>{icon} {word} {tlink(tok, sym) if tok else ""}'
                     f'{esc(sol)}</span><span>{badge("PRAVO", "good") if mode == "live" else badge("probno")} '
                     f'{badge(lab, css)}</span></div><div class=mut style="font-size:12px">{esc(ago(ts)[0])}{link}'
                     f'{" · " + note if note else ""}</div></div>')
    return head + "".join(items)


def log_fragment(user):
    """GET /pravi-trade/log: same access as the page."""
    tcon = _tcon()
    try:
        if not settings.can_view(tcon, user):
            return None
        return log_html(tcon, _cfg(tcon))
    finally:
        tcon.close()


def _log_section(tcon, cfg):
    js = ("<script>(()=>{const L=[['ap-log','/pravi-trade/log'],['ap-pos','/pravi-trade/pozicije'],['ap-zovu','/pravi-trade/zovu']];"
          "setInterval(()=>one('ap-ideje','/pravi-trade/ideje'),60000);"
          "async function one(id,url){const box=document.getElementById(id);if(!box)return;"
          "try{const r=await fetch(url,{cache:'no-store'});if(!r.ok)return;const h=await r.text();"
          "if(h!==box.innerHTML&&!box.contains(document.activeElement)){box.innerHTML=h;const d=box.closest('details.ap-sec');"
          "if(d&&(id==='ap-zovu'||id==='ap-ideje'))d.hidden=!h.trim()}}catch(e){}}"
          "async function f(){if(document.visibilityState!=='visible')return;for(const [id,url] of L)await one(id,url)}"
          f"setInterval(f,{LOG_EVERY_S * 1000});document.addEventListener('visibilitychange',f)}})()</script>")
    n = tcon.execute("SELECT COUNT(*) FROM orders WHERE ts >= ?", (int(time.time() - 86400),)).fetchone()[0]
    return _sec("Uživo: nalozi", f"⟳ svakih {LOG_EVERY_S} s · {n} danas",
                f'<div id=ap-log>{log_html(tcon, cfg)}</div>{js}', open_=True, sid="uzivo")


# 9.11. (Jure, mobitel): the section headers needed 5-6 taps to open, sometimes closed instead. Their <summary> is
# display:flex, and mobile Safari/Chrome drop or double-fire taps on such summaries. The tap is handled by hand:
# one tap = one toggle, and open sections are remembered for the page's reloads (sessionStorage).
TOGGLE_JS = ("<script>(()=>{const K='ap-open';let open={};try{open=JSON.parse(sessionStorage.getItem(K)||'{}')}catch(e){}"
             "document.querySelectorAll('details.ap-sec,details.ap-it').forEach((d,i)=>{const id=d.id||('ap'+i);"
             "if(id in open)d.open=!!open[id];const s=d.querySelector(':scope>summary');if(!s)return;"
             "s.addEventListener('click',e=>{if(e.target.closest('a,button,input,select'))return;e.preventDefault();"
             "d.open=!d.open;open[id]=d.open;try{sessionStorage.setItem(K,JSON.stringify(open))}catch(x){}})})})()</script>")


# ---------- limits, invites, safety -----------------------------------------------------------------------------

def _limits(cfg, owner):
    meta = f'ulog {cfg["size_sol"]:g} SOL · najviše {cfg["max_sol_per_day"]:g}/dan · stop −{cfg["max_loss_day"]:g}'
    if not owner:
        items = "".join(f"<li>{esc(lab)}: <b>{cfg.get(k, '–')}</b></li>" for k, (lab, *_rest) in settings.LIMITS.items())
        items += f"<li>SimianX signali: <b>{'uključeni' if cfg.get('simianx') else 'isključeni'}</b></li>"
        return _sec("Limiti", meta, f"<ul style='margin:0;padding-left:18px'>{items}</ul>", sid="limiti")
    fields = "".join(f'<label>{esc(lab)} <input name={k} value="{cfg.get(k, "")}" inputmode=decimal></label>'
                     for k, (lab, *_rest) in settings.LIMITS.items())
    def box(k, c, t):
        if k in settings.LOCKED:   # audit 4.11.: greyed out with the reason, the server ignores it anyway
            return (f'<label style="justify-content:flex-start;opacity:.6"><input type=checkbox disabled> {t}'
                    f'<br><span class=mut style="font-size:12px">🔒 {esc(settings.LOCKED[k])}</span></label>')
        return f'<label style="justify-content:flex-start"><input type=checkbox name={k} value=1{c}> {t}</label>'
    extra = (box(k="follow_paper", c=" checked" if cfg.get("follow_paper") else "",
                 t="prati i demo strategiju bota (uz influencere i wallete gore)")
             + box(k="use_pump", c=" checked" if cfg.get("use_pump", True) else "",
                   t=f"ako Jupiter ne prođe, probaj preko PumpPortala (naknada {pumpportal.FEE_PCT}%)")
             + box(k="simianx", c=" checked" if cfg.get("simianx") else "",
                   t="kupuj i na SimianX signale „kupi”, s njihovim stopom i ciljem (uključi tek kad se pokažu dobri u demu)"))
    inner = (f'<form method=post action=/pravi-trade/limits class=ap-lim>{fields}{extra}'
             '<p class=mut style="font-size:13px">Ulog vrijedi za svako praćenje. Kad se dosegne dnevna potrošnja ili '
             'dnevni gubitak, nove kupnje staju do ponoći (po zagrebačkom vremenu); prodaje idu dalje. Dnevni gubitak uključuje i naknade '
             'neuspjelih pokušaja.</p><button>Spremi limite</button></form>')
    return _sec("Limiti", meta, inner, sid="limiti")


def _invites(tcon):
    inv = {u.lower() for u in settings.invited(tcon)}
    boxes = "".join(f'<label style="display:block;margin:4px 0"><input type=checkbox name=u value="{esc(u)}"'
                    f'{" checked" if u.lower() in inv else ""}> {esc(u)}</label>'
                    for u in store.users() if not settings.is_owner(u))
    inner = ('<form method=post action=/pravi-trade/invite><p class=mut style="font-size:13px;margin-top:0">Pozvani vide '
             'stanje, pozicije i koga bot prati. Ne mogu ništa mijenjati ni trošiti tvoj novac; „Kupi i ti” im otvara '
             f'Jupiter u <b>njihovom</b> walletu.</p>{boxes or "<p>Nema drugih igrača.</p>"}<button>Spremi tko vidi</button></form>')
    return _sec("Tko još vidi stranicu", f"{len(inv)} pozvanih", inner, sid="pozivnice")


def _safety():
    items = ("Pravi novac ide samo kad je Autopilot uključen <b>i</b> u Renderu stoje ključ i TRADE_LIVE=1. Ključ nikad "
             "nije u kodu ni na ovoj stranici.",
             "U walletu drži samo iznos kojim bot smije trgovati.",
             "Dnevni limit potrošnje i dnevni gubitak zaustavljaju nove kupnje do ponoći.",
             f"U walletu uvijek ostaje barem {executor.RESERVE_FLOOR_SOL:g} SOL (i {executor.SELL_COST_SOL:g} SOL po otvorenoj "
             "poziciji) za mrežne naknade prodaje.",
             "Swap se ne radi ako je trošak (klizanje + naknada) veći od limita.",
             "Rute redom: Jupiter → Jupiter Ultra → PumpPortal (ako je uključen). Na sljedeću se ide samo kad swap sigurno "
             "nije prošao, da se ništa ne kupi dvaput.",
             "Neuspjela prodaja se ponavlja: nakon 5 s, 10 s, 20 s… najviše svakih 10 min, dok ne prođe.",
             "Ulazi se samo dok je signal svjež; rugani tokeni, lažni poolovi i premala likvidnost se preskaču.",
             "Preporuke su izračun iz povijesti, ne obećanje: memecoini mogu pasti na nulu.",
             "Prekidač mijenja samo vlasnik; pozvani samo gledaju.")
    return _sec("Kako je zaštićeno", "", "<ul style='margin:0;padding-left:18px;font-size:14px'>"
                + "".join(f"<li>{t}</li>" for t in items) + "</ul>")


def _with_toggle(html_body):
    return html_body + TOGGLE_JS


def page(qs, user):
    tcon = _tcon()
    try:
        if not settings.can_view(tcon, user):
            return (TITLE, f'<h1>{TITLE}</h1><div class=card>Ova stranica je samo za pozvane. '
                    'Ako želiš pristup, javi se vlasniku aplikacije.</div>')
        owner = settings.is_owner(user)
        cfg = _cfg(tcon)
        msg = ""
        if qs.get("err"):
            msg = f'<p class="ap-w bad"><b>Nije prošlo:</b> {esc(qs["err"])}</p>'
        elif qs.get("ok"):
            msg = f'<p class=ap-w style="background:var(--goodbg)">✓ {esc(qs["ok"])}</p>'
        con = store.connect()
        try:
            copy.ensure(con)
            b = [CSS, f'<h1>{TITLE}</h1><p class=ap-sub>Bot trguje pravim novcem iz tvog zasebnog walleta, samo po '
                 'influencerima i walletima koje odabereš, unutar tvojih limita.</p>', msg,
                 _wallet_card(tcon, cfg, con, owner), _positions(tcon, not owner, owner, cfg.get("sell_req")),
                 _buy_now_card(cfg, owner), _tp_card(cfg, owner), _callers_section(cfg, owner),
                 _ideas_section(cfg, owner), _log_section(tcon, cfg),
                 _follows(con, owner, settings.raw(tcon), prefill=(qs.get("ekipa") or "") if isinstance(qs, dict) else ""), _kol_section(con, owner),
                 _wallet_section(con, owner), _token_section(cfg, owner), _limits(cfg, owner)]
        finally:
            con.close()
        if owner:
            b.append(_invites(tcon))
        b += [_safety(), JS]
        return TITLE, _with_toggle("".join(b))
    finally:
        tcon.close()


def _live_wallets():
    import json
    con = copy._ro(copy._paths()["kol"])
    if con is None:
        return set()
    try:
        row = copy._q(con, "SELECT value FROM kv WHERE key='chain_hook'")
        return set(json.loads((row[0][0] if row else None) or "{}").get("wallets") or [])
    finally:
        con.close()


def _warnings(tcon, cfg, con):
    """Everything that would stop or hurt a trade right now, in plain words (Nicholas 3.11.: network congestion,
    too little SOL to sell, anything else worth knowing)."""
    now = time.time()
    w = []   # (level, text)
    live_ready = executor.armed()
    beat = cfg.get("heartbeat") or 0
    if not beat:
        w.append(("warn", "Trade proces se još nije javio (prvih minutu nakon pokretanja to je normalno)."))
    elif now - beat > 180:
        w.append(("bad", f"Trade proces ne radi već {int((now - beat) // 60)} min: nove kupnje i prodaje stoje. "
                         "Provjeri Render logove (run_trade.py)."))
    if os.path.exists(executor.STOP_FILE):
        w.append(("bad", "Uključen je kill switch (datoteka trade/STOP): nove kupnje su zaustavljene."))
    n_open_live = tcon.execute("SELECT COUNT(*) FROM positions WHERE mode='live' AND status='open'").fetchone()[0]
    if live_ready:
        bal = _balance(wallet.address())
        if bal is not None:
            reserve = executor.reserve_sol(cfg, n_open_live)
            need = cfg["size_sol"] + executor.BUY_OVERHEAD_SOL + executor.reserve_sol(cfg, n_open_live + 1)
            if bal < reserve:
                w.append(("bad", f"Opasno malo SOL-a: {bal:.4f}. Za prodaju {n_open_live} otvorenih pozicija treba "
                                 f"barem {reserve:.4f} SOL za mrežne naknade. Uplati SOL u wallet."))
            elif bal < need:
                w.append(("warn", f"Premalo SOL-a za novu kupnju: stanje {bal:.4f}, treba {need:.4f} (ulog "
                                  f"{cfg['size_sol']:g} + naknade i depozit {executor.BUY_OVERHEAD_SOL:g} + rezerva za "
                                  f"prodaju {executor.reserve_sol(cfg, n_open_live + 1):.4f}). Bot neće kupovati, "
                                  "prodaje rade."))
    mode = "live" if executor.is_live(cfg) else "dry"
    start = executor._day_start(now, cfg.get("day_tz"))
    spent = tcon.execute("SELECT COALESCE(SUM(sol_in),0) FROM positions WHERE mode=? AND opened_ts>=? AND status IN "
                         "('open','closed','pending')", (mode, start)).fetchone()[0]
    if spent >= cfg["max_sol_per_day"] - 1e-9:
        w.append(("warn", f"Dnevni limit potrošnje je dosegnut ({spent:.3f} SOL): nove kupnje tek nakon ponoći (Zagreb)."))
    if executor.day_pnl(tcon, now, mode, cfg.get("day_tz")) <= -cfg["max_loss_day"]:
        w.append(("bad", f"Dnevni gubitak je dosegnuo -{cfg['max_loss_day']:g} SOL: nove kupnje stoje do ponoći (Zagreb). Uključene su i naknade neuspjelih pokušaja."))
    recent = tcon.execute("SELECT code, error, prio_lamports, status FROM orders WHERE ts>=? ORDER BY id DESC LIMIT 30",
                          (now - 1800,)).fetchall()
    landed_fail = sum(1 for c, *_ in recent if c in (-1000, -1005, -1006, -2000))
    prio = [p for _, _, p, _ in recent if p]
    if landed_fail >= 2:
        w.append(("warn", f"Mreža je zagušena: {landed_fail} transakcija u zadnjih 30 min nije stiglo u blok. Bot "
                          "ponavlja automatski, ali ulazi mogu kasniti."))
    if prio and max(prio[:5]) >= 1_000_000:
        p = max(prio[:5]) / executor.LAMPORTS
        w.append(("warn", f"Mreža je zagušena: naknada za prioritet je sad oko {p:.4f} SOL po swapu, to je "
                          f"{100 * p / cfg['size_sol']:.1f}% uloga od {cfg['size_sol']:g} SOL."))
    if any(c == 2 for c, *_ in recent):
        w.append(("bad", "Jupiter javlja da wallet nema dovoljno SOL-a za mrežnu naknadu. Uplati malo SOL-a."))
    if any("429" in (e or "") or "HTTPError" in (e or "") for _, e, _, _ in recent):
        w.append(("warn", "Jupiter je odbio dio zahtjeva (previše upita bez ključa). Besplatan JUP_API_KEY s "
                          "portal.jup.ag u Renderu to rješava."))
    stuck = []
    for pid, sym, tok in tcon.execute("SELECT id, symbol, token FROM positions WHERE status='open'").fetchall():
        last = [r[0] for r in tcon.execute("SELECT status FROM orders WHERE position_id=? AND side='sell' ORDER BY id "
                                           "DESC LIMIT 3", (pid,))]
        if len(last) == 3 and all(x == "failed" for x in last):
            stuck.append(sym or tok[:6])
    if stuck:
        w.append(("bad", f"Ne može se prodati: {', '.join(stuck)}. Zadnja 3 pokušaja nisu prošla (moguće nema "
                         "likvidnosti ili je rug). Bot pokušava i dalje, najviše svakih 10 min."))
    if cfg["size_sol"] < 0.03:
        w.append(("warn", f"Ulog {cfg['size_sol']:g} SOL je malen: mrežne naknade i depozit (~0,003 SOL po kupnji, "
                          "depozit se vrati) su velik dio uloga."))
    if not copy.follows(con, settings.LEAGUE_USER) and not cfg.get("follow_paper") and not cfg.get("simianx"):
        w.append(("warn", "Bot nikoga ne prati: neće ništa kupiti dok ne dodaš influencera ili wallet."))
    # nothing to say = nothing shown (the page stays clean); otherwise one short line per problem
    return "".join(f'<p class="ap-w {lv}">{"⛔" if lv == "bad" else "⚠️"} {esc(t)}</p>' for lv, t in w)



def post(path, form, user):
    from urllib.parse import quote as qq
    tcon = _tcon()
    try:
        if not settings.is_owner(user):
            return f"{BACK}?err={qq('samo vlasnik može mijenjati pravi trade')}"
        if path == "/pravi-trade/switch":
            on = form.get("on") == "1"
            settings.put(tcon, "on", on, user)
            print(f"pravi trade: {user} je {'UKLJUČIO' if on else 'isključio'} prekidač", flush=True)
            return f"{BACK}?ok={qq('Autopilot je uključen.' if on else 'Autopilot je isključen: nove kupnje staju.')}"
        if path == "/pravi-trade/tp":   # 9.11.: the exit target for new copies (owner only)
            if not settings.is_owner(user):
                return f"{BACK}?err={qq('samo vlasnik')}"
            v = int(float(form.get("tp") or 15))
            if v not in TP_CHOICES:
                return f"{BACK}?err={qq('cilj izlaza: 5, 10, 15, 20 ili 30 %')}"
            settings.put(tcon, "tp_default", v, user)
            return f"{BACK}?ok={qq(f'Cilj izlaza za nove kopije: +{v} %.')}#cilj"
        if path == "/pravi-trade/sellall":
            settings.put(tcon, "on", False, user)
            settings.put(tcon, "sell_all", int(time.time()), user)
            print(f"pravi trade: {user} je kliknuo Prodaj sve", flush=True)
            return f"{BACK}?ok={qq('Isključeno. Sve otvorene pozicije se prodaju (pokušava svakih 30 s dok ne uspije).')}"
        if path == "/pravi-trade/limits":
            for k, v in settings.parse_limits(form).items():
                settings.put(tcon, k, v, user)
            settings.put(tcon, "follow_paper", form.get("follow_paper") == "1", user)
            settings.put(tcon, "use_pump", form.get("use_pump") == "1", user)
            settings.put(tcon, "simianx", form.get("simianx") == "1", user)
            return f"{BACK}?ok={qq('Limiti spremljeni.')}#limiti"
        if path == "/pravi-trade/sell":
            pid, frac = str(int(form.get("id") or 0)), float(form.get("frac") or 1)
            if not 0 < frac <= 1:
                raise ValueError("udio mora biti između 0 i 100%")
            if not tcon.execute("SELECT 1 FROM positions WHERE id=? AND status='open'", (int(pid),)).fetchone():
                raise ValueError("ta pozicija nije otvorena")
            req = dict(settings.raw(tcon).get("sell_req") or {})
            req[pid] = frac
            settings.put(tcon, "sell_req", req, user)
            return f"{BACK}?ok={qq(f'Prodaja {frac:.0%} poslana, za nekoliko sekundi je u tablici.')}#pozicije"
        if path == "/pravi-trade/wallet":
            from ui.real import ADDR
            addr = (form.get("addr") or "").strip()
            if addr and not ADDR.fullmatch(addr):
                raise ValueError("to nije Solana adresa (32-44 znaka, bez 0, O, I i l)")
            settings.put(tcon, "wallet_pub", addr or None, user)
            _BAL.clear()
            return f"{BACK}?ok={qq('Adresa walleta spremljena.' if addr else 'Adresa walleta obrisana.')}"
        if path == "/pravi-trade/invite":
            names = set(form.get("u_list") or [])
            known = {u.lower(): u for u in store.users()}
            settings.put(tcon, "invited", sorted(known[n.lower()] for n in names if n.lower() in known), user)
            return f"{BACK}?ok={qq('Spremljeno tko vidi stranicu.')}#pozivnice"
        con = store.connect()
        try:
            _league_account(con)
            if path == "/pravi-trade/follow":
                kind = form.get("kind", "")
                target = (form.get("target") or "").strip().lstrip("@")
                if kind == "auto":
                    kind, target = _detect_kind(target)
                if not target:
                    raise ValueError("upiši adresu walleta ili @influencera")
                tp = form.get("tp", "") or (f"{_cfg(tcon).get('tp_default', 15)}%" if form.get("exit") == "tpsl" else "")
                max_mcap, max_runup = _parse_usd(form.get("max_mcap")), _parse_pct(form.get("max_runup"))
                if kind == "ekipa":   # the crew defaults (Jure 9.11.); a KOL follow takes them only when filled in
                    max_mcap = EKIPA_MAX_MCAP if max_mcap is None else max_mcap
                    max_runup = EKIPA_MAX_RUNUP if max_runup is None else max_runup
                ex_mode = form.get("exit", "")
                if kind == "ekipa" and ex_mode == "mirror":
                    ex_mode = ""
                copy.follow(con, settings.LEAGUE_USER, kind, target, form.get("label", ""), 25,
                            form.get("per_day") or 5, ex_mode, tp, form.get("sl", ""),
                            max_mcap=max_mcap, max_runup=max_runup, min_callers=int(form.get("min_callers") or 1))
                con.commit()
                note = ""
                if kind == "ekipa":
                    mem = copy.members_of(target)
                    return f"{BACK}?ok={qq(f'Bot prati ekipu ({len(mem)} računa): ulaz čim prvi od njih objavi, do MC ${max_mcap:,.0f}, ne ako je već +{max_runup:.0%}.')}#pratim"
                if kind == "wallet" and target not in _live_wallets():
                    # 9.11.: any wallet from the database can be followed; it goes into the Helius webhook right now
                    note = (" Dodan u Helius webhook." if _add_live_wallet(target)
                            else " U webhook ulazi u sljedećem KOL krugu (do 45 min); do tada bot ne vidi njegove kupnje.")
                return f"{BACK}?ok={qq(f'Bot prati {target}.{note}')}#pratim"
            if path == "/pravi-trade/followall":   # 9.11.: follow the callers of a token from "Zovu sada" as ONE crew
                mem = sorted({h.strip().lstrip("@") for h in (form.get("handles") or "").split(",") if h.strip().lstrip("@")})
                if not mem:
                    raise ValueError("nema računa za praćenje")
                target = ",".join(mem)
                if any(f["target"] == target for f in copy.follows(con, settings.LEAGUE_USER) if f["kind"] == "ekipa"):
                    return f"{BACK}?ok={qq('Tu ekipu već pratiš.')}#pratim"
                tp = f"{_cfg(tcon).get('tp_default', 15)}%"
                copy.follow(con, settings.LEAGUE_USER, "ekipa", target, "", 25, 5, "tpsl", tp, "",
                            max_mcap=EKIPA_MAX_MCAP, max_runup=EKIPA_MAX_RUNUP, min_callers=1)
                con.commit()
                return f"{BACK}?ok={qq(f'Bot prati ekipu ({len(mem)} računa): ulaz čim prvi od njih objavi, do MC $1M, ne ako je već +25 %.')}#pratim"
            if path == "/pravi-trade/copyfollow":
                src = next((f for f in copy.follows(con, active=None) if f["id"] == int(form.get("id") or 0)), None)
                if not src:
                    raise ValueError("to praćenje ne postoji")
                ex = src["exit"]
                copy.follow(con, settings.LEAGUE_USER, src["kind"], src["target"], src["label"], 25, src["per_day"],
                            ex.get("mode", ""), ex.get("tp", ""), ex.get("sl", ""))
                who = src["label"] or src["target"]
                return f"{BACK}?ok={qq(f'Bot prati {who}.')}#pratim"
            if path == "/pravi-trade/buy":
                return _post_buy(con, tcon, form, user)
            if path == "/pravi-trade/auto":
                from ui import autopilot
                days, n = int(form.get("days") or 14), int(form.get("n") or 3)
                if days not in autopilot.WINDOWS or not 1 <= n <= 5:
                    raise ValueError("neispravno razdoblje ili broj")
                on = form.get("on") == "1"
                for k, v in (("auto_pick", on), ("auto_days", days), ("auto_n", n)):
                    settings.put(tcon, k, v, user)
                print(f"autopilot: {user} je {'uključio' if on else 'isključio'} automatski izbor ({days} d, {n}+{n})",
                      flush=True)
                if not on:
                    return f"{BACK}?ok={qq('Automatski izbor isključen. Koga je alat dodao, ostaje dok ga ne makneš.')}#pratim"
                _league_account(con)
                ch = autopilot.sync_follows(con, tcon, force=True)
                return f"{BACK}?ok={qq(f'Alat sada sam bira koga prati ({len(ch)} promjena).')}#pratim"
            if path == "/pravi-trade/stop":
                fid = int(form.get("id") or 0)
                raw = settings.raw(tcon)
                ids = [int(i) for i in raw.get("auto_follows") or []]
                if fid in ids:   # stopped by hand: the auto pick must not bring it back
                    f = next((x for x in copy.follows(con, settings.LEAGUE_USER) if x["id"] == fid), None)
                    if f:
                        skip = [list(x) for x in raw.get("auto_skip") or []] + [[f["kind"], f["target"]]]
                        settings.put(tcon, "auto_skip", skip[-200:], user)
                    settings.put(tcon, "auto_follows", [i for i in ids if i != fid], user)
                copy.unfollow(con, settings.LEAGUE_USER, fid)
                return f"{BACK}?ok={qq('Praćenje zaustavljeno. Otvorene pozicije se prodaju po svom pravilu izlaza.')}#pratim"
        finally:
            con.close()
        return BACK
    except (ValueError, sqlite3.OperationalError) as e:
        return f"{BACK}?err={qq(str(e))}"
    finally:
        tcon.close()


def _post_buy(con, tcon, form, user):
    """Manual buy: a demo trade on the real-trade account (same rug/liquidity checks as Natjecanje), its own SOL
    stake for the mirror, and its exit rule; run_trade.py turns it into the real swap within the limits."""
    from urllib.parse import quote as qq
    from league import auto
    from rugfilter import collapse
    from ui import data, real
    from ui.league import MINT, _symbol, market
    token = (form.get("token") or "").strip()
    if not MINT.fullmatch(token):
        token = real.resolve(token)[0]
    sol = float((form.get("sol") or "0").replace(",", "."))
    lab, _typ, lo, hi = settings.LIMITS["size_sol"]
    if not lo <= sol <= hi:
        raise ValueError(f"SOL mora biti između {lo:g} i {hi:g}")
    live = market({token})
    if token not in live:
        raise ValueError("nema cijene za tu adresu (je li to adresa tokena, a ne walleta?)")
    price, liq, _, mcap = live[token]
    col = collapse.check(collapse.peaks(data.HYPE_DB, [token]).get(token), mcap, liq)
    if col:
        raise ValueError(f"token je rugan ({col['text']}), kupnja je zaključana")
    sym = _symbol(token)
    tid = store.buy(con, settings.LEAGUE_USER, token, sym, 25, price, liq, "ručno (pravi trade)", None, mcap)
    ex = form.get("exit") or "smart"
    if ex == "smart":
        auto.set_auto(con, settings.LEAGUE_USER, tid, "smart")
    elif ex == "tpsl":
        auto.set_auto(con, settings.LEAGUE_USER, tid, "tpsl", form.get("tp", ""), form.get("sl", ""))
    sizes = dict(settings.raw(tcon).get("manual_size") or {})
    sizes[str(tid)] = sol
    settings.put(tcon, "manual_size", dict(list(sizes.items())[-200:]), user)
    return f"{BACK}?ok={qq(f'Kupnja {sym or token[:6]} za {sol:g} SOL poslana, za nekoliko sekundi je u tablici.')}#pozicije"


_VIEW = {"ts": 0, "names": set()}


def can_view_cached(user):
    """For the menu cookie on every page: owner + invited, the invite list re-read at most every 30 s."""
    if not user:
        return False
    if settings.is_owner(user):
        return True
    if time.time() - _VIEW["ts"] > 30:
        try:
            con = settings.connect()
            try:
                _VIEW["names"] = {u.lower() for u in settings.invited(con)}
            finally:
                con.close()
        except sqlite3.Error:
            pass
        _VIEW["ts"] = time.time()
    return user.lower() in _VIEW["names"]
