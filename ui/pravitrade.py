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
import json
import os
import re
import sqlite3
import threading
import time
from urllib.parse import quote

from league import copy, store
from trade import executor, pumpportal, settings, wallet
from ui.html import ago, badge, esc, short, tip, tlink, wlink

BACK = "/pravi-trade"
TITLE = "Autopilot"
USDC = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
_BAL = {}   # (address, what) -> (ts, value): one RPC call a minute at most
# 9.11. (audit P47): callers whose minute check (kol/minute.py) says they reach +15 % before the stop in fewer than
# WEAK_HIT15 of WEAK_MIN_N+ measured calls are a reason against, in the pop-up and in the manual buy. Only when the
# statistic exists: no measurement is "nepoznato", never a block.
WEAK_HIT15, WEAK_MIN_N = 0.3, 5

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


POP_HTML = ('<dialog id=ap-pop><div class=bar2><span class=mut id=ap-pop-age style="font-size:12px"></span>'
            '<button onclick="this.closest(\'dialog\').close()">Zatvori ✕</button></div><div class=body><p class=mut>Učitavam…</p></div></dialog>')
# 9.11. (Jure): everything opens in a pop-up, never a new page, and the pop-up re-fetches its content every second
# while it is open (the swap is skipped while a field inside it has focus, so a stake being typed is never lost)
# 9.11. 23:10 (Jure: the pop-up stays at "Učitavam…"): setInterval fired a new request every second whether or not
# the previous one had come back; with the server busy they piled up (each one more work for it) and none returned.
# Now one request at a time per pop-up (cur = the URL in flight), given up after POP_TIMEOUT_MS, an answer for a
# pop-up that was closed or changed meanwhile is dropped, and a slow server is said in the header instead of silence.
POP_TIMEOUT_MS = 8000
POP_JS = ("<script>(()=>{const d=document.getElementById('ap-pop');if(!d||window.__appop)return;window.__appop=1;let url='',t=null,n=0,cur=null,ctl=null;"
          "const age=document.getElementById('ap-pop-age');"
          "async function load(){if(!url||cur===url)return;const u=url;cur=u;let to=null;"
          "try{ctl=new AbortController();const c=ctl;to=setTimeout(()=>c.abort()," + str(POP_TIMEOUT_MS) + ");"
          "const r=await fetch(u,{cache:'no-store',signal:c.signal});if(u!==url)return;"
          "if(!r.ok){age.textContent='nema svježih podataka';return}const h=await r.text();if(u!==url)return;"
          "const b=d.querySelector('.body');if(h!==b.innerHTML&&!b.contains(document.activeElement))b.innerHTML=h;"
          "n++;age.textContent='uživo · osvježeno '+new Date().toLocaleTimeString()}"
          "catch(e){if(u===url)age.textContent='server je spor, pokušavam ponovno…'}"
          "finally{clearTimeout(to);if(cur===u)cur=null}}"
          "document.addEventListener('click',e=>{const el=e.target.closest('[data-pop]');if(!el||e.target.closest('a,button,input,select,form'))return;"
          "e.preventDefault();if(ctl)ctl.abort();url=el.dataset.pop;age.textContent='';d.querySelector('.body').innerHTML='<p class=mut>Učitavam…</p>';d.showModal();load();"
          "clearInterval(t);t=setInterval(load,1000)});"
          "d.addEventListener('close',()=>{clearInterval(t);url='';if(ctl)ctl.abort()});d.addEventListener('click',e=>{if(e.target===d)d.close()})})()</script>")
POP_CSS = ("<style>dialog#ap-pop{border:0;border-radius:18px;padding:0;max-width:min(96vw,680px);width:96vw;background:var(--card);color:var(--fg)}"
           "dialog#ap-pop::backdrop{background:rgba(0,0,0,.45)}dialog#ap-pop .bar2{display:flex;justify-content:space-between;align-items:center;padding:10px 14px;border-bottom:1px solid var(--line)}"
           "dialog#ap-pop .body{padding:10px 14px 16px;font-size:14px;line-height:1.45}dialog#ap-pop .body h3{margin:10px 0 4px;font-size:15px}"
           ".ap-row{display:flex;justify-content:space-between;gap:8px;align-items:center;padding:10px 0;border-top:1px solid var(--line);cursor:pointer;"
           "user-select:none;-webkit-user-select:none;-webkit-touch-callout:none;touch-action:manipulation}.ap-row .k{font-size:13px;color:var(--mut);text-align:right;white-space:nowrap}"
           ".ap-row b{font-weight:600}.ap-za{color:var(--good)}.ap-protiv{color:var(--bad)}.ap-verdict{font-weight:700;padding:6px 10px;border-radius:10px;margin:6px 0;display:inline-block}"
           ".ap-verdict.ok{background:var(--goodbg);color:var(--good)}.ap-verdict.ne{background:var(--badbg);color:var(--bad)}</style>")


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
    try:   # 9.11. (Jure): what each follow did in the last 24 h (signals, entries, skips with reasons), from copy_log
        day = copy.follow_log_summary(con, time.time() - 86400)
    except Exception:  # noqa: BLE001 - the page must render even if the log table is missing
        day = {}
    items = []
    for f in fl:
        r = res.get(f["id"], {"n": 0, "closed": 0, "wins": 0, "pnl": 0.0})
        proof = _proof_line(r)
        d = day.get(f["id"])
        if d:
            why = "; ".join(f"{esc(k)}{' ×' + str(n) if n > 1 else ''}" for k, n in d["razlozi"])
            last24 = (f'Zadnjih 24 h: {d["signali"]} signala · {d["ulaz"]} ulaza · preskočeno {d["preskočeno"]}'
                      + (f' ({why})' if why else ''))
        else:
            last24 = "Zadnjih 24 h: nijedan signal koji bi prošao pravila kopiranja (nije zvao/kupio, ili poziv nije stigao na vrijeme)"
        if f["kind"] == "ekipa":
            who = "🤝 " + " + ".join(f'<a href="/kol/{quote(m)}">{"✈ " + esc(m[3:]) if m.startswith("tg:") else "@" + esc(m)}</a>'
                                    for m in copy.members_of(f["target"]))
        else:
            who = (f'<a href="/kol/{quote(f["target"])}">@{esc(f["target"])}</a>' if f["kind"] == "kol"
                   else wlink(f["target"]) + (f" {esc(f['label'])}" if f["label"] else ""))
        stop = (f'<form method=post action=/pravi-trade/stop><input type=hidden name=id value={f["id"]}>'
                '<button>Prestani pratiti</button></form>') if owner else ""
        by = '<span class="ap-tag dugo">🤖 alat</span>' if f["id"] in auto_ids else ""
        try:
            dline = _data_exit_line(f)
        except Exception:  # noqa: BLE001 - the list renders without the statistic
            dline = ""
        items.append(f'<details class=ap-it><summary><span>{who}<span class=ap-tag>'
                     f'{"influencer" if f["kind"] == "kol" else ("ekipa" if f["kind"] == "ekipa" else "wallet")}</span>{by}</span><span class=k>{r["n"]} ulaza</span>'
                     f'</summary><p>Najviše {f["per_day"]} ulaza na dan · izlaz: {esc(copy.describe_exit(f["exit"]) or "zadano")}'
                     f' · prati od {esc(ago(f["created"])[0])}{" · dodao ga je alat" if by else ""}</p>'
                     f'<p class=mut style="font-size:13px">{last24}</p>'
                     + (f'<p class=mut style="font-size:13px">{dline}</p>' if dline else '')
                     + f'<p class=mut style="font-size:13px">{proof}</p>{stop}</details>')
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
                  f'<option value=tpsl{" selected" if pre else ""}>moj TP/SL</option>'
                  '<option value=podaci>po podacima (alat bira TP/SL)</option></select><input name=tp placeholder="TP %" size=6> <input name=sl placeholder="SL %" size=6>'
                  '<label>do MC <input name=max_mcap placeholder="npr. 1M" size=6></label> <label>ne ako je već <input name=max_runup placeholder="+25 %" size=5></label> '
                  '<label>od <select name=min_callers aria-label="Koliko iz ekipe mora zvati"><option value=1>1. poziva</option><option value=2>2 zovu</option><option value=3>3 zovu</option></select></label>'
                  '<button>Zaprati</button></form><p class=mut style="font-size:13px;margin:0 0 8px">Ekipa = više računa odvojenih zarezom: '
                  'jedan ulaz po tokenu čim prvi od njih objavi (ili kad ih zove 2–3), samo dok je token ispod zadanog MC-a (zadano $1M) i '
                  'nije već narastao više od zadanog (+25 %) od poziva. Wallet koji još ne pratimo uživo dodaje se u Helius webhook odmah. '
                  'Izlaz „po podacima” (influenceri i ekipe): alat pri svakom ulazu sam bira TP/SL iz izmjerenih poziva tog računa '
                  'i ne ulazi kad nijedan par nije u plusu; pozicija se zatvara najkasnije nakon 60 min.</p>')
    try:
        pool_box = _pool_line()
    except Exception:  # noqa: BLE001
        pool_box = ""
    inner = (_auto_box(st, owner) + anyone
             + ("".join(items) or '<p class=mut style="margin:0">Još nikoga. Upiši koga pratiti ili odaberi iz preporuka ispod.</p>')
             + pool_box)
    return _sec("Koga bot prati", meta, inner, open_=not fl, sid="pratim")


_DATA_EXIT = {}        # follow id -> (wall time, exit signature, decision): the page asks once a minute, not per render
DATA_EXIT_TTL_S = 60
POOL_SHOW = ((15, 20), (20, 40), (20, 20), (30, 15))   # the pairs Jure asked about, plus two with the target >= the stop


def _data_exit_line(f, now=None):
    """9.11. (Jure: "neka alat dinamički odluči kad može biti profitabilno"): what kol/tpsl.py says about this KOL /
    crew follow right now, from its measured calls: the TP/SL it would take, or that no pair is in the plus (then a
    follow with the exit "po podacima" does not enter), or how many measured calls are still missing. '' for wallets
    (their buys are not measured by the minute) and when minute.db cannot be read."""
    if f["kind"] not in ("kol", "ekipa"):
        return ""
    sig = json.dumps(f["exit"], sort_keys=True)
    hit = _DATA_EXIT.get(f["id"])
    if hit and time.time() - hit[0] < DATA_EXIT_TTL_S and hit[1] == sig:
        d = hit[2]
    else:
        d = copy.data_exit(f, now)
        _DATA_EXIT[f["id"]] = (time.time(), sig, d)
    if not d:
        return ""
    own = f["exit"].get("mode") == "podaci"
    if d.get("ok") is None:
        tail = (f" Do tada vrijedi zadani izlaz TP +{copy.DATA_TP.rstrip('%')} % / SL {copy.DEFAULT_SL.rstrip('%')} %." if own else "")
        return f"Po podacima: {esc(d['why'])}.{tail}"
    if d["ok"]:
        return (f"Po podacima alat bi uzeo {esc(d['base'])}; na novijih {d['n_new']} poziva {d['ev_new']:+.1f} %."
                + ("" if own else " (Ovo praćenje koristi svoj izlaz; „po podacima” se bira u formi.)"))
    return (f"{esc(d['why'][:1].upper() + d['why'][1:])}." + (" Bot zato sada NE ulazi u njegove pozive." if own
                                                               else " (Ovo praćenje ipak ulazi, jer koristi svoj izlaz.)"))


def _pool_line():
    """Everybody's measured calls under a few TP/SL pairs (kol/tpsl.save_pool, written by the minute loop): the share
    that reached the target before the stop, the share the pair needs for zero, and the result per trade after cost."""
    try:
        from kol import minute, tpsl
        mc = minute.ro()
        if mc is None:
            return ""
        try:
            p = tpsl.load_pool(mc)
        finally:
            mc.close()
    except Exception:  # noqa: BLE001 - a missing statistic never breaks the page
        return ""
    if not p.get("n") or not p.get("pairs"):
        return ""
    best = max(p["pairs"].items(), key=lambda kv: kv[1]["ev"])
    show = [f"{tp}/{sl}" for tp, sl in POOL_SHOW if f"{tp}/{sl}" in p["pairs"]]
    if best[0] not in show:
        show.append(best[0])
    cells = []
    for k in show:
        d = p["pairs"][k]
        tp, sl = k.split("/")
        cells.append(f'<tr><td>TP +{tp} % / SL −{sl} %{" (najbolji)" if k == best[0] else ""}</td><td class=n>{d["tp"]:.0%}</td>'
                     f'<td class=n>{d["need"]:.0%}</td><td class="n {"pos" if d["ev"] > 0 else "neg"}">{d["ev"]:+.1f} %</td></tr>')
    n_txt = f'{p["n"]:,}'.replace(",", ".")
    return ('<details class=ap-it><summary><span>Koji TP/SL se isplati (svi izmjereni pozivi)</span>'
            f'<span class=k>{n_txt} poziva · 30 d</span></summary>'
            '<table class=t style="font-size:13px"><tr><th>izlaz</th><th class=n>cilj prije stopa</th>'
            '<th class=n>treba za nulu</th><th class=n>po tradeu</th></tr>' + "".join(cells) + '</table>'
            f'<p class=mut style="font-size:13px">Račun: treba = (SL + trošak) / (TP + SL), trošak {p.get("cost", 2):g} % po krugu. '
            'Širi stop traži VIŠE pogodaka, ne manje; isplati se samo ako dovoljno zaustavljenih tradeova pretvori u dobitne. '
            'Mjereno 60 min nakon poziva; što ne dotakne ni cilj ni stop, izlazi po cijeni nakon 60 min. '
            'Stariji pozivi (prije 10.11.) imaju točnu minutu samo za stop −20 %, ostali stopovi se za njih računaju oprezno.</p></details>')


def _proof_line(r):
    """9.11. (audit P39): what run_trade.follow_league_once needs before a follow's copies go into real money
    (run_trade.PROOF: closed demo copies, PnL > 0, share of winners), shown per follow so a LIVE buy "blocked:
    praćenje bez dokaza u demu" is no surprise. Same thresholds, read from run_trade, never a second copy."""
    try:
        from run_trade import PROOF
    except Exception:  # noqa: BLE001 - the page must render without the trade process module
        PROOF = {"closed": 10, "win_rate": 0.4}
    closed, wins, pnl = r.get("closed", 0), r.get("wins", 0), r.get("pnl", 0.0)
    have = f"zatvorenih {closed}, dobitnih {wins}, PnL {pnl:+.0f} $"
    need = f"treba {PROOF['closed']}+ zatvorenih, PnL > 0 i {PROOF['win_rate']:.0%}+ dobitnih"
    proven = closed >= PROOF["closed"] and pnl > 0 and wins / closed >= PROOF["win_rate"]
    return (f"Dokaz u demu: {esc(have)} · pravi novac: <b>{'da' if proven else 'još ne'}</b> ({esc(need)})"
            + ("" if proven else "; do tada se njegove kopije kupuju samo probno"))


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
            mi = s.get("minute") or {}
            if s.get("mjera") == "minutna" and mi.get("n"):   # 9.11. (audit P12/P15/P16): the minute measure first
                k = f'{(mi.get("hit10") or 0):.0%} +10 % prije stopa · {mi["n"]} poziva'
            else:
                k = f'{s["hit"]:.0%} pogodaka · {s["n"]} callova (stara mjera)'
            items.append(f'<details class=ap-it><summary><span><a href="/kol/{quote(r["handle"])}">@{esc(r["handle"])}</a>'
                         f'{" ⚡" if r["live"] else ""}</span><span class=k>{k}</span>'
                         f'</summary><p>{esc(r["why"])}</p>{_follow_btn("kol", r["handle"], "", have, owner)}</details>')
        panes[d] = "".join(items) or f'<p class=mut>U zadnjih {d} dana nitko nema barem {autopilot.MIN_CALLS} izmjerena calla s malo rugova.</p>'
    if not any_items:   # 9.11. (Jure): an empty list is noise; the section appears when there is somebody to follow
        return ""
    best = next((r for r in recs.get(14) or [] if r["handle"] not in followed), None)
    meta = f'najbolji 14 d: @{esc(best["handle"])}' if best else "po zadnjih 7/14/30 dana"
    inner = (f'<p class=mut style="margin:0 0 6px;font-size:13px">Minutna provjera = +10 % prije stopa −20 % u 60 min od minute '
             f'poziva; "pogodak" (stara mjera, samo gdje minutne provjere još nema) = +50 % u 24 h '
             f'{tip("Minutna mjera (kol/minute.py) rangira; stara mjera: najveći rast u 24 h, rezultat nakon 24 h i je li token rugan, rugovi dvostruko protiv. ⚡ = pratimo ga uživo, pa bot stigne ući na vrijeme.")}</p>'
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
               + (f', stil {style}' if style else "")
               # 9.11. (audit P55): open losers he never closed ("bags"), so a nice realized PnL is read with them
               + (f' · {int(r["bags"])} bagova (kupljeni tokeni koje nije zatvorio)' if r.get("bags") is not None else "") + ".")
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
        # 9.11. (audit P14): chain_trades sells carry no SOL amount, so the window return is mostly unknown; say so
        panes[d] = "".join(items) or (f'<p class=mut>U zadnjih {d} dana nijedan wallet koji pratimo uživo nema barem '
                                      f'{autopilot.MIN_CLOSED} prodana tokena s poznatim povratom u plusu (iznos prodaja '
                                      f'se često ne zapisuje, pa je povrat po prozoru nepoznat; auto-izbor uzima '
                                      f'"dokazane dvaput" gore).</p>')
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
            f'<input name=sl placeholder="SL (zadano {copy.DEFAULT_SL})" size=14>'
            '<button>Kupi</button></form>')


def _buy_now_card(cfg, owner):
    """9.11. (Jure): at the top of the page, buy any token right now with the amount you choose: address + SOL + Kupi.
    Exit defaults to the target chosen below (TP) and, with no stop typed in, the default stop league/copy.DEFAULT_SL
    (audit P17/P19: the page used to promise "the usual stop" that did not exist); the rest sits behind "Više"."""
    if not owner:
        return ""
    tp_default = cfg.get("tp_default", 15)
    return ('<div class=card id=kupi-odmah><b>Kupi odmah</b> <span class=mut>bilo koji token, iznos po želji</span>'
            '<form method=post action=/pravi-trade/buy onsubmit="return confirm(\'Kupiti ovaj token pravim novcem '
            '(ako je Autopilot uključen)?\')" style="margin-top:8px"><input name=token placeholder="adresa tokena ili DexScreener link" '
            'required style="flex:1;min-width:200px" autocomplete=off spellcheck=false>'
            f'<label>SOL <input name=sol value="{cfg["size_sol"]:g}" inputmode=decimal style="width:64px"></label>'
            '<button class=ap-go>Kupi</button>'
            f'<details style="flex-basis:100%"><summary class=mut style="font-size:13px">Više (izlaz: moj TP/SL, cilj +{tp_default} %, stop {copy.DEFAULT_SL})</summary>'
            '<select name=exit aria-label="Kako prodati"><option value=tpsl>moj TP/SL</option><option value=smart>Smart sell</option>'
            f'<option value=manual>prodajem sam</option></select> <input name=tp placeholder="TP" value="{tp_default}%" size=6> '
            f'<input name=sl placeholder="SL (zadano {copy.DEFAULT_SL})" size=14></details></form>'
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
            'kupnju s izlazom "moj TP/SL" bez upisanog TP-a; postojeće pozicije zadržavaju svoj. Stop: kako je upisan, inače '
            f'zadani {esc(copy.DEFAULT_SL)} (isti prag kao minutna provjera). Praćenja s izlazom "zadano" (Smart sell) imaju svoj stop.</p></div>')


IDEAS_EVERY_S = 60   # the suggestion log (latest_picks) cadence; the live box below is LIVE_IDEAS_S
LIVE_IDEAS_S = 1
_IDEAS_CACHE = {}   # owner flag -> (ts, html)
# 9.11. (audit P48/P33/P75): the 1-s fragments (/zovu, /ideje) and the 1-s pop-ups are read by the browser every
# second per viewer. Their DexScreener state lives LIVE_TTL_S (DexScreener's 300/min IP limit is shared by every
# process: never 1 s), and in the UI process a daemon thread (_bg_loop) renews it plus the two fragments' HTML, so a
# request thread only reads the caches: no HTTP, no retry sleep, no five-database pass per viewer per second. The
# caches are guarded by _LOCK (ThreadingHTTPServer). BG_REFRESH False (tests) = the old synchronous path.
LIVE_TTL_S = 3
BG_REFRESH = os.environ.get("AP_BG_REFRESH", "1") == "1"
BG_WANT_S = 8          # a token set a pop-up / fragment asked for in the last BG_WANT_S s is kept fresh
_LOCK = threading.RLock()
_BG = {"thread": None, "ts": 0.0, "runs": 0}
_LIVE_WANT = {}        # token tuple -> ts of the last request for it (what the background thread keeps fresh)


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
    order = {"uživo": 0, "visoka": 0, "srednja": 1, "niska": 2}   # 9.11. (audit P50/P51): zivo rows rank with 'visoka'
    out, seen = [], set()
    for tok, raz, mcap0, conf, ts in rows:
        if tok in seen:
            continue
        seen.add(tok)
        out.append({"token": tok, "razina": raz or "visoka", "mcap0": mcap0, "conf": conf, "ts": ts})
    out.sort(key=lambda p: (order.get(p["razina"], 3), -(p["conf"] or 0), -(p["ts"] or 0)))
    return out[:limit]


def ideas_inner(cfg, owner, now=None, force=False):
    """9.11. (Jure): live, not "the same as Pregled every 60 s". ui/zivo: candidates through every slow filter, then
    price / volume / new callers / smart-wallet buys refreshed every 2 s; a token stays only while it trades now.
    The HTML does not depend on cfg/owner; force=True (background thread) recomputes past the cache."""
    now = now or time.time()
    c = _IDEAS_CACHE.get(bool(owner))
    if c and now - c[0] < LIVE_IDEAS_S and not force:
        return c[1]
    try:
        from ui import zivo
        rs = zivo.rows(now)
    except Exception as e:  # noqa: BLE001
        return f'<p class=mut>Živi prijedlozi trenutno nisu dostupni ({esc(type(e).__name__)}).</p>'
    if not rs and not zivo._ROWS.get("ts"):   # 9.11. (audit P33 review): the zivo thread has not filled its cache yet
        return '<p class=mut>učitavam…</p>'   # not cached, so the next poll gets the real list
    data_ts = now
    if not rs:
        html = ""
    else:
        out = []
        # 9.11. (audit): the stamp shows the time of the DexScreener numbers (each zivo row carries 'checked'), not
        # the time this HTML was assembled: after zivo's IDLE_STOP_S the rows can be old while the HTML is fresh
        data_ts = min((r.get("checked") or now) for r in rs[:8])
        for r in rs[:8]:
            m = r["live"]
            ch5 = f"{m['ch_m5']:+.0f} %" if m.get("ch_m5") is not None else "?"
            ch1 = f"{m['ch_h1']:+.0f} %" if m.get("ch_h1") is not None else "?"
            why = (r.get("reasons") or [""])[0]
            out.append(f'<div class=ap-row data-pop="/pravi-trade/token?m={quote(r["token"])}"><span><b>{esc(r.get("symbol") or m.get("symbol") or r["token"][:6])}</b>'
                       f'{badge(r["src"], "")} <span class=mut style="font-size:13px">{esc(why)}</span></span>'
                       f'<span class=k>MC ${m["mcap"] / 1000:,.0f}k · 5 min {ch5} · 1 h {ch1}</span></div>')
        html = "".join(out)
    with _LOCK:   # the same HTML for both viewer kinds (one computation in the background thread serves both)
        _IDEAS_CACHE[bool(owner)] = (now, html, data_ts)   # (compute time for the TTL, HTML, data time for the stamp)
        _IDEAS_CACHE[not bool(owner)] = (now, html, data_ts)
    return html


def _stamp(html, ts):
    """The data time of a cached fragment (never the render time), under the rows; nothing when there are no rows,
    so the section's hide-when-empty logic still works."""
    if not html or not ts:
        return html or ""
    return html + (f'<p class=mut style="font-size:12px;margin:6px 0 0">podaci od '
                   f'{time.strftime("%H:%M:%S", time.gmtime(ts))} UTC</p>')


def ideas_fragment(user):
    tcon = _tcon()
    try:
        if not settings.can_view(tcon, user):
            return None
        cfg, owner = _cfg(tcon), settings.is_owner(user)
    finally:
        tcon.close()
    if _bg_start():   # the background thread fills the cache; this request thread only reads it
        with _LOCK:
            c = _IDEAS_CACHE.get(bool(owner)) or (0.0, "")
        if not c[0]:   # 9.11. (audit): no pass yet (zivo's thread still fetching): say so instead of hiding the box
            return '<p class=mut>učitavam…</p>'
        return _stamp(c[1], c[2] if len(c) > 2 else c[0])
    return ideas_inner(cfg, owner)


def _ideas_section(cfg, owner):
    inner = ideas_inner(cfg, owner)
    return _sec("Što kupiti sada", f"svi filteri + uživo cijena, volumen, pozivatelji, pametni novčanici · ⟳ {LIVE_IDEAS_S} s",
                f'<div id=ap-ideje>{inner}</div><p class=mut style="font-size:13px;margin:8px 0 0">Token je ovdje samo dok prolazi '
                'rug check, tier i arhiv ruga, ima MC 30k+, 10+ tx i $1k+ volumena u zadnjem satu, $20k+ likvidnosti i ne pada; '
                'red: tko je zadnji zvao, kupnje pametnih novčanika, promjena u 5 min, brzina novca.</p>', hidden=not inner,
                sid="ideje")


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


EVENTS_TTL_S = 3   # the last hour of calls is read from the databases at most this often for the pop-ups
_EVENTS = {"ts": 0.0, "ev": None}


def _events_hour(now=None, fresh=False):
    """[(token, ts, platform, author, kind)] of the last CALLERS_WINDOW_S (kol/converge.events), shared by the
    "Zovu sada" box and every pop-up. 9.11. 23:10 (Jure: the pop-up stays at "Učitavam…"): each pop-up poll (once a
    second) read kol.db, tg.db and hype.db again in its request thread; with the CPU busy the polls piled up and
    none came back. The refresher thread stores what it reads each pass (fresh=True) and the request threads take
    that copy while it is younger than EVENTS_TTL_S. With the refresher off (tests) every call reads the databases."""
    from kol import converge
    now = now or time.time()
    if BG_REFRESH and not fresh:
        with _LOCK:
            ts, ev = _EVENTS["ts"], _EVENTS["ev"]
        if ev is not None and time.time() - ts < EVENTS_TTL_S:
            return ev
    ev = converge.events(int(now), CALLERS_WINDOW_S)[0]
    if BG_REFRESH:
        with _LOCK:
            _EVENTS.update(ts=time.time(), ev=ev)
    return ev


def gather_callers(now, window_s=CALLERS_WINDOW_S, kol_db=None, tg_db=None, hype_db=None, followed=None, limit=8, live=None):
    """[(token, callers, first_ts, last_ts, symbol, live)] worth showing: X/Telegram calls from kol/converge.events
    and buys of the followed wallets only, minus everything kol/converge.not_a_memecoin rules out, each checked live
    on DexScreener (live: {token: market} for tests; None = fetch)."""
    from kol import converge, store as kstore
    if window_s == CALLERS_WINDOW_S and not (kol_db or tg_db or hype_db):
        ev = list(_events_hour(now, fresh=True))   # the refresher's own read, kept for the pop-ups
    else:
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
    if kc is not None:   # 9.11. (audit P75): closed even when there is nothing to look up (it leaked a handle a second)
        try:
            if rows:
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


_LIVE_CACHE = {}   # token tuple -> (ts, data): "Zovu sada", each open pop-up and each crew pop-up keep their own slot
_LIVE_FAIL = {}    # token tuple -> ts of the last fetch that returned None (9.11. (audit): negative cache, see below)


def _live_cached(tokens, now, ttl=LIVE_TTL_S, wait=None):
    """DexScreener state of a token set, shared for ttl seconds (one request per set). 9.11. (audit P48): wait=False
    (a request thread while the background thread runs) never fetches when a slot exists: it returns the slot, up to
    a few seconds old, and the background thread renews it; only a set nobody asked for yet is fetched here, once."""
    key = tuple(tokens)
    if not key:
        return {}
    with _LOCK:
        hit = _LIVE_CACHE.get(key)
        failed = _LIVE_FAIL.get(key, 0.0)
        if wait is not True:   # the refresher's own renewals do not count as a request (a closed pop-up expires)
            _LIVE_WANT[key] = now
    if wait is None:   # the refresher itself and the synchronous path fetch; request threads beside a refresher read
        wait = threading.current_thread() is _BG["thread"] or not _bg_running()
    if hit and (now - hit[0] < ttl or (not wait and now - hit[0] < 60)):
        return hit[1]
    # 9.11. (audit): a fetch that returned None (DexScreener 429/5xx) used to leave no slot, so every 1-s poll of an
    # open pop-up fetched again in the request thread, with the http retry sleeps; the failure is remembered for ttl
    # seconds and the old slot (at most 60 s, the same bound the read-only path accepts) or None is returned
    old = hit[1] if hit and now - hit[0] < 60 else None
    if now - failed < ttl:
        return old
    from ui import prijedlog
    data = prijedlog.live_market(list(key))
    if data is None:
        with _LOCK:
            _LIVE_FAIL[key] = now
        return old
    with _LOCK:
        _LIVE_FAIL.pop(key, None)
        _LIVE_CACHE[key] = (now, data)
        if len(_LIVE_CACHE) > 64:   # pop-ups come and go: forget the sets nobody asks for
            for k in [k for k in _LIVE_CACHE if now - _LIVE_WANT.get(k, 0) > BG_WANT_S]:
                _LIVE_CACHE.pop(k, None)
                _LIVE_WANT.pop(k, None)
                _LIVE_FAIL.pop(k, None)
    return data


def _bg_running():
    t = _BG["thread"]
    return bool(t and t.is_alive())


def _bg_start():
    """Start the refresher once per UI process (first fragment request); False when it is off (tests) or dead."""
    if not BG_REFRESH:
        return False
    with _LOCK:
        if _bg_running():
            return True
        t = threading.Thread(target=_bg_loop, daemon=True, name="autopilot-live")
        _BG["thread"] = t
        t.start()
    return True


def _bg_pass(now=None):
    """One refresher pass: the token sets asked for in the last BG_WANT_S s (pop-ups, crews) renewed when older
    than LIVE_TTL_S, then the "Zovu sada" and "Što kupiti sada" HTML. Every step in its own try: a failing source
    leaves the others' caches alone (stale data with its time beats no data)."""
    now = now or time.time()
    with _LOCK:
        # 9.11. (review): a set whose fetch returned None never enters _LIVE_CACHE, so the eviction there never saw
        # its WANT entry; forget requests nobody repeated in 10 x BG_WANT_S
        for k in [k for k, ts in _LIVE_WANT.items() if now - ts > 10 * BG_WANT_S]:
            _LIVE_WANT.pop(k, None)
            _LIVE_FAIL.pop(k, None)
        want = [k for k, ts in _LIVE_WANT.items() if now - ts <= BG_WANT_S and now - (_LIVE_CACHE.get(k) or (0,))[0] >= LIVE_TTL_S]
    for key in want:
        try:
            _live_cached(key, now, wait=True)
        except Exception as e:  # noqa: BLE001
            print(f"autopilot uživo: DexScreener za {len(key)} tokena nije uspio: {type(e).__name__}: {e}", flush=True)
    with _LOCK:   # "Što kupiti sada" goes through zivo.rows (its own DexScreener request): at most once per LIVE_TTL_S
        ideas_due = now - (_IDEAS_CACHE.get(False) or (0.0,))[0] >= LIVE_TTL_S
    steps = [lambda: callers_inner(None, False, now, force=True)]
    if ideas_due:
        steps.append(lambda: ideas_inner(None, False, now, force=True))
    for fn in steps:
        try:
            fn()
        except Exception as e:  # noqa: BLE001
            print(f"autopilot uživo: osvježavanje nije uspjelo: {type(e).__name__}: {e}", flush=True)
    _BG["ts"], _BG["runs"] = now, _BG["runs"] + 1


def _bg_loop():
    while True:
        t0 = time.time()
        _bg_pass(t0)
        time.sleep(max(0.2, LIVE_IDEAS_S - (time.time() - t0)))   # the owner's 1-s cadence, for the DB-sourced parts


def callers_inner(cfg, owner, now=None, force=False):
    """Live: who called which token in the last hour (X, Telegram, followed wallets). The point (Jure 9.11.): see the
    FIRST caller of a token at once and buy before the rest of his crew calls it. The HTML does not depend on
    cfg/owner; force=True (background thread) recomputes past the 1-s cache."""
    now = now or time.time()
    if now - _CALLERS_CACHE["ts"] < 1 and _CALLERS_CACHE["html"] and not force:
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
        html = "".join(_crew_row(c, now) for c in crew_rows(rows, now))
    with _LOCK:
        _CALLERS_CACHE.update(ts=now, html=html)
    return html


def crew_rows(rows, now):
    """One line per crew (Jure 9.11.: "Robinhood six times in a row cannot be"): the callers of a token form the crew;
    a crew is named after its leader (the first caller of its newest token). [{key, name, members, tokens, last,
    first}] newest first."""
    by = {}
    for tok, callers, first, last, sym, m in rows:
        members = tuple(sorted(c[0] for c in callers))
        g = by.setdefault(members, {"members": members, "tokens": [], "first": first, "last": last, "leader": callers[0][0]})
        g["tokens"].append({"token": tok, "symbol": sym, "first": first, "last": last, "live": m, "callers": callers})
        if last > g["last"]:
            g["last"], g["leader"] = last, callers[0][0]
        g["first"] = min(g["first"], first)
    out = []
    for members, g in by.items():
        lead = g["leader"]
        name = (lead[3:] if lead.startswith("tg:") else ("👛 " + lead[2:8] if lead.startswith("w:") else "@" + lead))
        if len(members) > 1:
            name = f"ekipa {name} +{len(members) - 1}"
        g["name"], g["key"] = name, ",".join(h for h in members if not h.startswith("w:"))
        g["tokens"].sort(key=lambda t: -t["last"])
        out.append(g)
    out.sort(key=lambda g: -g["last"])
    return out


def _crew_row(g, now):
    t = g["tokens"][0]
    m = t["live"]
    ch5 = f"{m['ch_m5']:+.0f} %" if m.get("ch_m5") is not None else "?"
    n = len(g["tokens"])
    # 9.11. (audit P73): a crew made only of wallets has no X/Telegram handle to follow as a crew (their buys are
    # already copied by the wallet follows), so the row opens its newest token, not a crew pop-up with "w:…"
    pop = (f"/pravi-trade/ekipa?h={quote(g['key'])}" if g["key"] else f"/pravi-trade/token?m={quote(t['token'])}")
    return (f'<div class=ap-row data-pop="{pop}"><span><b>{esc(g["name"])}</b> '
            f'<span class=mut style="font-size:13px">{n} {"token" if n == 1 else "tokena"} u 60 min · zadnji {esc(t["symbol"] or t["token"][:6])} '
            f'{esc(ago(t["last"])[0])}</span></span><span class=k>MC ${m["mcap"] / 1000:,.0f}k · 5 min {ch5}</span></div>')


def _live_one(mint, now):
    """DexScreener state of one token for a pop-up, shared with the 1-s cache."""
    lv = _live_cached([mint], now)
    return (lv or {}).get(mint) if lv is not None else None


def _callers_veto(handles, mstats):
    """9.11. (audit P47): the reason against when the callers' own minute check (kol/minute.py, hit15 = reached +15 %
    before the stop) is weak: WEAK_MIN_N+ measured calls and fewer than WEAK_HIT15 of them. None when nobody has a
    measurement (then zivo.expectation falls back to the MC band's chance, which is NOT a caller statistic and must
    not veto). Used by the pop-up verdict and the manual buy alike."""
    # 9.11. (review): handles deduplicated (a caller who called twice in the hour is one account, not two) and the
    # rate pooled over their calls, weighted by n: the same formula as zivo.expectation (P85), so the pop-up's
    # "Očekivanje +15 %" and this veto can never disagree. A plain mean let a noise account (n=3, 0 %) veto next to
    # a strong one (n=50, 55 %).
    hs = [mstats[h] for h in dict.fromkeys(handles or []) if h in (mstats or {})]
    if not hs:
        return None
    n = sum(int(s.get("n") or 0) for s in hs)
    v = sum(float(s.get("hit15") or 0) * int(s.get("n") or 0) for s in hs) / n if n else 0.0
    if n >= WEAK_MIN_N and v < WEAK_HIT15:
        return f"pozivatelji dođu do +15 % prije stopa samo u {v:.0%} ({n} izmjerenih poziva, minutna provjera)"
    return None


_SUPPLY_CACHE = {}   # mint -> (ts, shape): the rug.db row is read at most once a minute per open pop-up


def _pct(v):
    return "nepoznato" if v is None else f"{float(v):.0f} %"


def _supply_line(mint, top, now):
    """9.11. (audit P77/P76/P56): who holds the supply, from data already on disk (topcheck RugCheck summary, rug.db
    full report through topcheck.holders.pumpfun_shape), with the time of the RugCheck data (rc_ts), not of the last
    run_top pass (ts). Unknown stays "nepoznato": a holder count is never shown, missing data is never "u redu"."""
    shape = None
    try:
        from topcheck import holders
        c = _SUPPLY_CACHE.get(mint)
        if c and now - c[0] < 60:
            shape = c[1]
        else:
            shape = holders.pumpfun_shape([mint], tc={mint: top} if top else {}).get(mint)
            _SUPPLY_CACHE[mint] = (now, shape)
            if len(_SUPPLY_CACHE) > 200:
                for k in [k for k, (ts, _) in _SUPPLY_CACHE.items() if now - ts > 600]:
                    _SUPPLY_CACHE.pop(k, None)
    except Exception:  # noqa: BLE001 - no rug.db / topcheck: unknown, never an error on the page
        shape = None
    if not shape:
        return "tko drži supply: nepoznato (nema RugCheck ni rug filter podatka)"
    parts = [f"top 10 {_pct(shape.get('top10HoldersPercent'))} (bez poolova)", f"insajderi {_pct(shape.get('insidersPercent'))}",
             f"dev {_pct(shape.get('devHoldingsPercent'))}", f"bundle {_pct(shape.get('bundlerOwnedPercent'))}",
             f"snajperi {_pct(shape.get('snipersOwnedPercent'))}"]
    when = ""
    if top and top.get("rc_ts"):
        when = f" · RugCheck podatak {ago(top['rc_ts'])[0]}"
    return f"tko drži supply: {', '.join(parts)} ({shape.get('izvor') or 'izvor nepoznat'}){when}"


def token_popup(user, mint, now=None):
    """GET /pravi-trade/token?m=: why this token is (or is not) worth entering RIGHT NOW, re-fetched every second
    by the pop-up: live market, buyers vs sellers, callers in the last hour, smart-wallet buys, the tool's fresh
    rug check and tier, a verdict with the reasons against, the expectation for +15 % and the buy form."""
    from kol import converge
    from kol.collect import is_solana_mint
    from ui import prijedlog, zivo
    tcon = _tcon()
    try:
        if not settings.can_view(tcon, user):
            return None
        cfg, owner = _cfg(tcon), settings.is_owner(user)
    finally:
        tcon.close()
    now = now or time.time()
    if not is_solana_mint(mint):
        return "<p class=ap-protiv>To nije Solana adresa tokena.</p>"
    m = _live_one(mint, now)
    if m is None:
        return "<p class=mut>Provjera uživo (DexScreener) trenutno ne uspijeva; bez nje ne nudim ulaz.</p>"
    if not m:
        return '<div class="ap-verdict ne">NE KUPUJ: nema živog para na DexScreeneru.</div>'
    sym = m.get("symbol") or mint[:6]
    try:
        ev = _events_hour(now)
    except Exception:  # noqa: BLE001
        ev = []
    callers = sorted({(e[3], e[1]) for e in ev if e[0] == mint and e[4] == "call" and e[2] != "chain"}, key=lambda x: -x[1])
    smart = zivo._smart_buys(now, {mint}).get(mint, 0)
    top = {}
    try:
        from topcheck import store as tstore
        top = tstore.read_all(max_age_h=1).get(mint) or {}
    except Exception:  # noqa: BLE001
        pass
    tier = (zivo._tiers() or {}).get(mint) or {}
    archived = False
    try:
        from rugfilter import archive
        archived = mint in archive.blocked()
    except Exception:  # noqa: BLE001
        pass
    # 9.11. (audit P45): "za" is split: fresh reasons (the same three ui/zivo.fresh_reasons counts, same thresholds)
    # decide the verdict; the static ones (hourly buyer share, rug check, tier) only describe. Without a fresh reason
    # the verdict is NE KUPUJ, as in the live list, so the pop-up never offers real money on yesterday's call.
    za, za_static, protiv = [], [], []
    if callers:
        fresh = [h for h, ts in callers if now - ts <= 600]
        if fresh:
            za.append("novi pozivatelj u 10 min: " + ", ".join((h[3:] if h.startswith("tg:") else "@" + h) for h in fresh[:4]))
    if smart:
        za.append(f"{smart} pametnih novčanika kupilo u 10 min")
    if ((m.get("ch_m5") or 0) >= zivo.MOVE_M5 and (m.get("vol_m5") or 0) >= zivo.MOVE_VOL_M5
            and (m.get("txns_m5") or 0) >= zivo.MOVE_TX_M5):
        za.append(f"+{m['ch_m5']:.0f} % u 5 min na ${m['vol_m5']:,.0f} ({m['txns_m5']} tx)")
    buys, tx = m.get("buys_h1") or 0, m.get("txns_h1") or 0
    if tx and buys / tx >= 0.55:
        za_static.append(f"kupci prevladavaju: {buys} od {tx} transakcija u satu su kupnje")
    safety = top.get("safety") or {}
    checks = safety.get("checks") or {}
    hold = checks.get("holderi") or (None, "")
    # 9.11. (audit P29/P36, handoff izvori): 'oprez' now also means "holders unknown"; that alone is shown as
    # "nepoznato" (never a block: no data -> no buy would kill every fresh token), any other warn or fail is a reason
    holders_unknown = hold[0] == "warn" and "nepoznat" in (hold[1] or "")
    rc_issues = [t for t in (safety.get("fails") or []) + (safety.get("warns") or []) if "nepoznat" not in t]
    if top.get("verdict") == "prolazi":
        # 9.11. (audit P76): the time of the RugCheck data (rc_ts), not of the last run_top pass (ts)
        za_static.append(f"rug check alata prošao (RugCheck podatak {esc(ago(top.get('rc_ts') or top.get('ts'))[0])})")
    if tier.get("razina"):
        za_static.append(f"tier T{tier['razina']}" + (f" ({tier.get('klasa')})" if tier.get("klasa") else ""))
    why_not = prijedlog.alive(m)
    if why_not:
        protiv.append(why_not)
    if (m.get("mcap") or 0) < 30_000:
        protiv.append(f"MC ${m['mcap']:,.0f}, ispod 30k")
    if (m.get("ch_m5") or 0) <= -10:
        protiv.append(f"pada {m['ch_m5']:+.0f} % u 5 min")
    if tx and buys / tx < 0.45:
        protiv.append(f"prodavači prevladavaju: samo {buys} od {tx} transakcija u satu su kupnje")
    # 9.11. (audit P41, handoff novac): the same pool-depth gate the automatic entry has (league/copy.CFG min_liq_mcap)
    min_liq = copy.CFG.get("min_liq_mcap", 0.03)
    if m.get("mcap") and m.get("liq") and m["liq"] < min_liq * m["mcap"]:
        protiv.append(f"likvidnost ${m['liq']:,.0f} je samo {m['liq'] / m['mcap']:.1%} MC-a (granica {min_liq:.0%}): "
                      "najveći holder bi srušio cijenu prije stopa")
    if archived:
        protiv.append("rug filter ga je arhivirao")
    if top.get("verdict") == "pao" or (top.get("verdict") == "oprez" and rc_issues):
        protiv.append(f"rug check alata: {top['verdict']}" + (f" ({'; '.join(rc_issues[:3])})" if rc_issues else ""))
    nm = converge.not_a_memecoin(mint, sym, m.get("liq"))
    if nm:
        protiv.append(nm)
    mstats = zivo._minute_stats(now)
    caller_hs = sorted({h for h, _ in callers})   # 9.11. (review): one entry per account for the veto and the expectation
    veto = _callers_veto(caller_hs, mstats)
    if veto:
        protiv.append(veto)
    if not za:
        protiv.append("nema svježeg razloga za ulaz (bez novog pozivatelja u 10 min, kupnje pametnog novčanika ili pokreta "
                      f"+{zivo.MOVE_M5:.0f} % u 5 min s prometom)")
    ok = not protiv
    # 9.11. (audit P49): a token outside the top 20 has no rug check at all; the verdict says so instead of looking
    # like a safety confirmation, and the supply line below says "nepoznato"
    rc_missing = not top or top.get("verdict") in (None, "nepoznato")
    # 9.11. (review): a topcheck row with verdict 'nepoznato' means the token WAS on the list but RugCheck did not
    # answer; say that instead of "nije rađen" so Jure knows the difference
    rc_missing_txt = "RugCheck nije odgovorio" if top else "rug check nije rađen"
    band = prijedlog._band(m["mcap"])
    exp_txt, _v = zivo.expectation(caller_hs, mstats, (zivo._chances() or {}).get(band))
    ch5 = f"{m['ch_m5']:+.0f} %" if m.get("ch_m5") is not None else "?"
    ch1 = f"{m['ch_h1']:+.0f} %" if m.get("ch_h1") is not None else "?"
    ch24 = f"{m['ch_h24']:+.0f} %" if m.get("ch_h24") is not None else "?"
    verdict = ("NE KUPUJ" if not ok else
               f"U REDU ZA ULAZ · {rc_missing_txt}, tko drži supply nepoznato" if rc_missing else
               "U REDU ZA ULAZ · holderi nepoznati" if holders_unknown else "U REDU ZA ULAZ")
    liq_pct = f" ({m['liq'] / m['mcap']:.0%} MC-a)" if m.get("mcap") and m.get("liq") else ""
    b = [f'<h3>{tlink(mint, sym)}</h3>',
         f'<div class="ap-verdict {"ok" if ok else "ne"}">{esc(verdict)}</div>',
         f'<p>MC ${m["mcap"] / 1000:,.0f}k · likv. ${m["liq"] / 1000:,.0f}k{liq_pct} · cijena 5 min {ch5} · 1 h {ch1} · 24 h {ch24}<br>'
         f'Vol 5 min ${m["vol_m5"]:,.0f} ({m["txns_m5"]} tx) · 1 h ${m["vol_h1"]:,.0f} ({tx} tx, {buys} kupnji) · '
         f'brzina novca {(m["vol_h1"] / m["liq"] if m.get("liq") else 0):.1f}× likvidnosti</p>']
    if za or za_static:
        b.append("<p class=ap-za><b>Za:</b> " + "; ".join(esc(x) for x in za)
                 + (("; " if za else "") + '<span class=mut>' + "; ".join(esc(x) for x in za_static) + "</span>" if za_static else "")
                 + ".</p>")
    if protiv:
        b.append("<p class=ap-protiv><b>Protiv:</b> " + "; ".join(esc(x) for x in protiv) + ".</p>")
    if top:
        sup = _supply_line(mint, top, now)
    else:
        sup = "rug check alata: nije rađen (token nije među top 20 prijedloga) · tko drži supply: nepoznato"
    b.append(f"<p><b>Holderi:</b> {esc(sup)}.</p>")
    b.append(f"<p><b>Očekivanje:</b> {esc(exp_txt)}.</p>")   # 9.11. (audit P85): the fallback text is "stara mjera: ... +30 % u 24 h"
    if callers:
        b.append("<p><b>Zvali u zadnjih 60 min:</b> " + ", ".join(
            f'{esc(h[3:] if h.startswith("tg:") else "@" + h)} ({esc(ago(ts)[0])})' for h, ts in callers[:8]) + "</p>")
    if top.get("state") and (top["state"] or {}).get("advice"):
        b.append(f'<p class=mut>Svježa provjera alata: {esc(top["state"]["advice"])}</p>')
    b.append(f'<p><a href="https://dexscreener.com/solana/{quote(mint)}" target=_blank rel=noopener>DexScreener ↗</a> · '
             f'<a href="/token/{quote(mint)}">cijela stranica tokena</a></p>')
    if ok or owner:
        b.append(_buy_form(mint, cfg, "tpsl", owner) if ok else
                 '<p class=mut style="font-size:13px">Gumb za kupnju je skriven dok token ne prolazi provjere.</p>')
    return "".join(b)


def crew_popup(user, handles, now=None):
    """GET /pravi-trade/ekipa?h=a,b: the crew's tokens of the last hour with live state, each member's minute-check
    record, and a follow-as-crew button; re-fetched every second."""
    from kol import converge
    from ui import zivo
    tcon = _tcon()
    try:
        if not settings.can_view(tcon, user):
            return None
        cfg, owner = _cfg(tcon), settings.is_owner(user)
    finally:
        tcon.close()
    now = now or time.time()
    hs = [h.strip().lstrip("@") for h in (handles or "").split(",") if h.strip()]
    if not hs:
        return "<p class=mut>Nema računa.</p>"
    mem = set(hs)
    try:
        ev = _events_hour(now)
    except Exception:  # noqa: BLE001
        ev = []
    toks = {}
    for tok, ts, plat, who, kind in ev:
        if kind == "call" and plat != "chain" and who in mem:
            d = toks.setdefault(tok, {"first": ts, "last": ts, "who": {}})
            d["first"], d["last"] = min(d["first"], ts), max(d["last"], ts)
            d["who"][who] = min(d["who"].get(who, ts), ts)
    ms = zivo._minute_stats(now)
    b = ["<h3>" + " + ".join(esc(h[3:] if h.startswith("tg:") else "@" + h) for h in hs) + "</h3>"]
    rec = []
    for h in hs:
        st = ms.get(h)
        rec.append(f'{esc(h[3:] if h.startswith("tg:") else "@" + h)}: ' + (
            f'+10 % prije stopa {st["hit10"]:.0%}, +15 % {st["hit15"]:.0%}, stop prvi {st["sl"]:.0%} na {st["n"]} poziva (14 d)'
            if st else "još bez minutne provjere"))
    b.append("<p><b>Uspjeh (minutna provjera):</b><br>" + "<br>".join(rec) + "</p>")
    if toks:
        # 9.11. (review): a stable cache key (the 20 latest tokens, sorted by mint): ordering by 'last' changed the
        # key with every new call, which meant a new slot and a synchronous DexScreener fetch in the 1-s handler
        lv = _live_cached(sorted(sorted(toks, key=lambda t: -toks[t]["last"])[:20]), now) or {}
        rows = []
        for tok, d in sorted(toks.items(), key=lambda kv: -kv[1]["last"]):
            m = lv.get(tok) or {}
            state = (f'MC ${m["mcap"] / 1000:,.0f}k · 5 min {m["ch_m5"]:+.0f} %' if m.get("mcap") and m.get("ch_m5") is not None
                     else ("bez para" if not m else f'MC ${m["mcap"] / 1000:,.0f}k'))
            who = ", ".join(esc(w[3:] if w.startswith("tg:") else "@" + w) for w, _ in sorted(d["who"].items(), key=lambda x: x[1]))
            rows.append(f'<div class=ap-row data-pop="/pravi-trade/token?m={quote(tok)}"><span><b>{esc(m.get("symbol") or tok[:6])}</b> '
                        f'<span class=mut style="font-size:13px">{who} · prvi {esc(ago(d["first"])[0])}</span></span><span class=k>{state}</span></div>')
        b.append("<p><b>Tokeni u zadnjih 60 min</b> (dodir = provjera tokena):</p>" + "".join(rows))
    else:
        b.append("<p class=mut>U zadnjih 60 min nema poziva ove ekipe.</p>")
    if owner:
        # 9.11. (audit P73): wallets ("w:…") are not crew members: a crew follow never fires on a wallet (copy.events
        # reads X/Telegram), and their buys are copied by the wallet follows already
        acc = [h for h in hs if not h.startswith("w:")]
        if acc:
            target = ",".join(acc)
            b.append(f'<form method=post action=/pravi-trade/followall onsubmit="return confirm(\'Zapratiti ove račune kao ekipu?\')">'
                     f'<input type=hidden name=handles value="{esc(target)}"><button>Zaprati kao ekipu ({len(acc)})</button></form>')
        else:
            b.append('<p class=mut style="font-size:13px">Samo novčanici: njih bot prati zasebno (gumb „Prati pravim novcem” kod '
                     'walleta), ekipa se radi od X/Telegram računa.</p>')
    return "".join(b)


def callers_fragment(user):
    tcon = _tcon()
    try:
        if not settings.can_view(tcon, user):
            return None
        cfg, owner = _cfg(tcon), settings.is_owner(user)
    finally:
        tcon.close()
    if _bg_start():   # the background thread fills the cache; this request thread only reads it
        with _LOCK:
            ts, html = _CALLERS_CACHE["ts"], _CALLERS_CACHE["html"]
        return _stamp(html, ts)
    return callers_inner(cfg, owner)


def _callers_section(cfg, owner):
    inner = callers_inner(cfg, owner)
    return _sec("Zovu sada", f"zadnjih 60 min · X, Telegram, tvoji i dokazani novčanici · ⟳ {LOG_EVERY_S} s",
                f'<div id=ap-zovu>{inner}</div><p class=mut style="font-size:13px;margin:8px 0 0">'
                'Tko od njih stvarno nosi +5/10/15/20/30 % nakon poziva: <a href="/ekipe">Ekipe i minutna provjera</a>.</p>',
                sid="zovu", hidden=not inner)


def _token_section(cfg, owner):
    from ui import autopilot
    recs = autopilot.token_recs()
    items = []
    from kol import converge
    for kind, lab, ex in (("dugo", "dugoročno", "manual"), ("moon", "moonshot", "smart")):
        for r in recs.get(kind) or []:
            if converge.not_a_memecoin(r["mint"], r.get("symbol")):   # 9.11.: never a major, wrapped asset or xStock
                continue
            items.append(f'<div class=ap-row data-pop="/pravi-trade/token?m={quote(r["mint"])}"><span><b>{esc(r["symbol"] or r["mint"][:6])}</b>'
                         f'<span class="ap-tag {kind}">{lab}</span> <span class=mut style="font-size:13px">{esc((r["why"] or "")[:90])}</span></span>'
                         f'<span class=k>dodir = provjera uživo</span></div>')
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
LOG_EVERY_S = 1   # 9.11. (Jure): every second is money; log, positions, callers and ideas are re-fetched every second
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
    js = ("<script>(()=>{const L=[['ap-log','/pravi-trade/log'],['ap-pos','/pravi-trade/pozicije'],['ap-zovu','/pravi-trade/zovu'],"
          "['ap-ideje','/pravi-trade/ideje']];"
          "function stale(box,on){box.style.opacity=on?'.55':'';box.title=on?'nema svježih podataka':''}"
          "async function one(id,url){const box=document.getElementById(id);if(!box)return;"
          "const c=new AbortController(),to=setTimeout(()=>c.abort()," + str(POP_TIMEOUT_MS) + ");"
          "try{const r=await fetch(url,{cache:'no-store',signal:c.signal});if(!r.ok){stale(box,true);return}const h=await r.text();stale(box,false);"
          "if(h!==box.innerHTML&&!box.contains(document.activeElement)){box.innerHTML=h;const d=box.closest('details.ap-sec');"
          "if(d&&(id==='ap-zovu'||id==='ap-ideje'))d.hidden=!h.trim()}}catch(e){stale(box,true)}finally{clearTimeout(to)}}"
          # 9.11. 23:10: one pass at a time; a tick that finds the previous pass still waiting for the server is skipped
          "let run=false;async function f(){if(run||document.visibilityState!=='visible')return;run=true;"
          "try{for(const [id,url] of L)await one(id,url)}finally{run=false}}"
          f"setInterval(f,{LOG_EVERY_S * 1000});document.addEventListener('visibilitychange',f)}})()</script>")
    n = tcon.execute("SELECT COUNT(*) FROM orders WHERE ts >= ?", (int(time.time() - 86400),)).fetchone()[0]
    return _sec("Uživo: nalozi", f"⟳ svakih {LOG_EVERY_S} s · {n} danas",
                f'<div id=ap-log>{log_html(tcon, cfg)}</div>{js}', sid="uzivo")


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
        b.append(POP_CSS + POP_HTML + POP_JS)
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
                if form.get("exit") == "podaci":   # 9.11.: the tool picks the pair at every entry (kol/tpsl.py)
                    tp = ""
                max_mcap, max_runup = _parse_usd(form.get("max_mcap")), _parse_pct(form.get("max_runup"))
                if kind == "ekipa":   # the crew defaults (Jure 9.11.); a KOL follow takes them only when filled in
                    max_mcap = EKIPA_MAX_MCAP if max_mcap is None else max_mcap
                    max_runup = EKIPA_MAX_RUNUP if max_runup is None else max_runup
                ex_mode = form.get("exit", "")
                if kind in ("ekipa", "kol") and ex_mode == "mirror":   # 9.11. (audit P74): "prodaj kad on proda" has no
                    ex_mode = ""                                         # meaning for a call; the default (Smart sell) instead
                # 9.11. (audit P10/P17/P19): "moj TP/SL" without a stop typed in gets the default stop, stored on the
                # follow so the list shows it (league/copy.run_once would apply the same DEFAULT_SL anyway)
                sl = (form.get("sl") or "").strip() or (copy.DEFAULT_SL if ex_mode == "tpsl" else "")
                min_callers = int(form.get("min_callers") or 1)
                copy.follow(con, settings.LEAGUE_USER, kind, target, form.get("label", ""), 25,
                            form.get("per_day") or 5, ex_mode, tp, sl,
                            max_mcap=max_mcap, max_runup=max_runup, min_callers=min_callers)
                con.commit()
                note = ""
                if kind == "ekipa":
                    mem = copy.members_of(target)
                    mc = max(1, min(min_callers, len(mem)))   # 9.11. (audit P72): the message says the saved condition
                    when = "čim prvi od njih objavi" if mc == 1 else f"kad token zovu {mc}+ od njih"
                    return f"{BACK}?ok={qq(f'Bot prati ekipu ({len(mem)} računa): ulaz {when}, do MC ${max_mcap:,.0f}, ne ako je već +{max_runup:.0%}.')}#pratim"
                if kind == "wallet" and target not in _live_wallets():
                    # 9.11.: any wallet from the database can be followed; it goes into the Helius webhook right now
                    note = (" Dodan u Helius webhook." if _add_live_wallet(target)
                            else " U webhook ulazi u sljedećem KOL krugu (do 45 min); do tada bot ne vidi njegove kupnje.")
                return f"{BACK}?ok={qq(f'Bot prati {target}.{note}')}#pratim"
            if path == "/pravi-trade/followall":   # 9.11.: follow the callers of a token from "Zovu sada" as ONE crew
                raw = {h.strip().lstrip("@") for h in (form.get("handles") or "").split(",") if h.strip().lstrip("@")}
                # 9.11. (audit P73): "w:…" wallets never fire a crew follow (copy.events reads X/Telegram only)
                mem = sorted(h for h in raw if not h.startswith("w:"))
                if not mem:
                    raise ValueError("nema X/Telegram računa za ekipu" + (": novčanike prati zasebno (gumb „Prati pravim novcem”)"
                                                                        if raw else ""))
                target = ",".join(mem)
                if any(f["target"] == target for f in copy.follows(con, settings.LEAGUE_USER) if f["kind"] == "ekipa"):
                    return f"{BACK}?ok={qq('Tu ekipu već pratiš.')}#pratim"
                tp = f"{_cfg(tcon).get('tp_default', 15)}%"
                copy.follow(con, settings.LEAGUE_USER, "ekipa", target, "", 25, 5, "tpsl", tp, copy.DEFAULT_SL,   # P10/P19: the default stop
                            max_mcap=EKIPA_MAX_MCAP, max_runup=EKIPA_MAX_RUNUP, min_callers=1)
                con.commit()
                return f"{BACK}?ok={qq(f'Bot prati ekipu ({len(mem)} računa): ulaz čim prvi od njih objavi, do MC $1M, ne ako je već +25 %, stop {copy.DEFAULT_SL}.')}#pratim"
            if path == "/pravi-trade/copyfollow":
                src = next((f for f in copy.follows(con, active=None) if f["id"] == int(form.get("id") or 0)), None)
                if not src:
                    raise ValueError("to praćenje ne postoji")
                ex = src["exit"]
                # 9.11. (audit P72): the copy keeps the MC cap, run-up gate and crew condition, not only the exit
                copy.follow(con, settings.LEAGUE_USER, src["kind"], src["target"], src["label"], 25, src["per_day"],
                            ex.get("mode", ""), ex.get("tp", ""), ex.get("sl", ""), once=bool(ex.get("once")),
                            max_mcap=ex.get("max_mcap"), max_runup=ex.get("max_runup"), min_callers=int(ex.get("min_callers") or 1))
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


def _buy_callers_veto(token, now=None):
    """The P47 veto for the manual buy: the token's X/Telegram callers of the last hour against their minute check.
    Any failure to read the sources means no statistic, so None (unknown is never a block)."""
    now = now or time.time()
    try:
        from kol import converge
        from ui import zivo
        ev, _s, _f = converge.events(int(now), 3600)
        handles = sorted({e[3] for e in ev if e[0] == token and e[4] == "call" and e[2] != "chain"})
        if not handles:
            return None
        return _callers_veto(handles, zivo._minute_stats(now))
    except Exception:  # noqa: BLE001
        return None


def _post_buy(con, tcon, form, user):
    """Manual buy: a demo trade on the real-trade account (same live gate as the lists: trading now, MC 30k+, not
    falling, not collapsed, callers' minute check not weak), its own SOL stake for the mirror, and its exit rule;
    run_trade.py turns it into the real swap within the limits."""
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
    # 9.11. (Jure, JENSEN 127k -> 14k): the same live gate as the lists, at the moment of the tap
    from ui import prijedlog
    lv = prijedlog.live_market([token])
    if lv is None:
        raise ValueError("provjera uživo (DexScreener) nije uspjela; kupnja odbijena")
    why_not = prijedlog.alive(lv.get(token))
    if why_not:
        raise ValueError(f"kupnja odbijena: {why_not}")
    if (lv[token].get("mcap") or 0) < 30_000:
        raise ValueError(f"kupnja odbijena: MC ${lv[token]['mcap']:,.0f}, ispod 30k")
    # 9.11. (audit P47): the callers' measured outcome is the one fact about copying such a call; when it exists and
    # is weak the buy is refused (same rule as the pop-up verdict). No measurement = no veto; a failing read = no veto.
    veto = _buy_callers_veto(token)
    if veto:
        raise ValueError(f"kupnja odbijena: {veto}")
    # 9.11. (audit N4/N10): everything is checked BEFORE the demo trade is written. A ValueError used to come after
    # store.buy, so the page showed the error while the position already existed, without an exit rule, and
    # run_trade mirrored it (for real in LIVE); a stake above max_sol_per_trade was accepted here and silently
    # blocked by gate_buy, leaving a demo position with no real one behind it.
    ex = form.get("exit") or "smart"
    tp, sl = (form.get("tp") or "").strip(), (form.get("sl") or "").strip()
    if ex == "tpsl":
        if not sl:
            sl = copy.DEFAULT_SL   # owner rule 9.11.: no explicit stop -> the default one, same as for copies
        tp_px, _ = auto.parse_level(tp, price, mcap, "tp")   # raises on a typo or an MC level without entry MC
        sl_px, _ = auto.parse_level(sl, price, mcap, "sl")
        if tp_px is None and sl_px is None:
            raise ValueError("upiši barem TP ili SL")
        if tp_px is not None and tp_px <= price:
            raise ValueError("TP mora biti iznad ulaznog MC-a")
    elif ex != "smart":
        raise ValueError("nepoznat način izlaza")
    lim = _cfg(tcon)["max_sol_per_trade"]
    if sol > lim:
        raise ValueError(f"ulog {sol:g} SOL je iznad limita {lim:g} SOL po tradeu (promijeni limit u postavkama)")
    sym = _symbol(token)
    tid = store.buy(con, settings.LEAGUE_USER, token, sym, 25, price, liq, "ručno (pravi trade)", None, mcap)
    try:
        if ex == "smart":
            auto.set_auto(con, settings.LEAGUE_USER, tid, "smart")
        else:
            auto.set_auto(con, settings.LEAGUE_USER, tid, "tpsl", tp, sl)
    except ValueError as e:   # validated above, so this should not happen; never leave the position without an exit
        auto.set_auto(con, settings.LEAGUE_USER, tid, "smart")
        print(f"pravi trade: ručna kupnja {sym or token[:6]}: TP/SL odbijen ({e}), izlaz Smart sell", flush=True)
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
