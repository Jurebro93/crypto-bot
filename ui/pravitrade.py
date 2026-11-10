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
from ui import redak
from ui.html import ago, esc, short, tlink, wlink
from ui.redak import Html, cat, dot, raw, row

BACK = "/pravi-trade"
TITLE = "Autopilot"
USDC = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
_BAL = {}   # (address, what) -> (ts, value): one RPC call a minute at most
# 9.11. (audit P47): callers whose minute check (kol/minute.py) says they reach +15 % before the stop in fewer than
# WEAK_HIT15 of WEAK_MIN_N+ measured calls are a reason against, in the pop-up and in the manual buy. Only when the
# statistic exists: no measurement is "nepoznato", never a block.
WEAK_HIT15, WEAK_MIN_N = 0.3, 5

# 10.11. (Jure: "Ostalo mi se sviđa", prijedlog 3.4, maketa audit/2026-11-10/makete/autopilot.html): the page speaks the
# shared calm language of ui/redak.py and ui/html.MS_CSS (rows, hero, five type sizes 34/22/17/15/13, colours only
# for signed numbers, a dot for a state). What is below is only what this page needs on top of it: the switch in the
# title row, sections that open on a tap and look like the shared row, the chart's range under the plot, the sell
# buttons and forms inside an opened row. Values are copied from the mock-up.
CSS = """<style>
.ap{font-size:17px;line-height:1.4;font-variant-numeric:tabular-nums}
.ap p{margin:0 0 10px}
.ap .mut,.ap small{font-size:15px}.ap code{font-size:13px}
.ap a{color:var(--acc)}
.ap button{background:var(--card);color:var(--fg);border-color:var(--line2);font-size:15px}
.ap button:hover{background:var(--soft);border-color:var(--line2);box-shadow:none}
.ap button.ap-go{background:var(--fg);color:#fff;border-color:var(--fg)}.ap button.ap-go:hover{background:#1f2937}
.ap button.ap-stop{color:var(--bad)}
.ap-top{padding:8px 0 0}
.ap-tog{display:flex;align-items:center;gap:10px;font-size:15px;color:var(--mut)}.ap-tog form{margin:0}
.ap button.ap-sw{flex:none;display:block;width:51px;height:31px;min-height:0;padding:0;border:0;border-radius:999px;
  background:var(--line2);position:relative;cursor:pointer;box-shadow:none;transform:none}
.ap button.ap-sw:hover{background:var(--line2)}.ap button.ap-sw.on,.ap button.ap-sw.on:hover{background:var(--good)}
.ap button.ap-sw::after{content:"";position:absolute;top:2px;left:2px;width:27px;height:27px;border-radius:50%;background:#fff;
  box-shadow:0 2px 4px rgba(0,0,0,.2)}
.ap button.ap-sw.on::after{left:auto;right:2px}
.ap-state{display:flex;align-items:center;justify-content:space-between;gap:4px 12px;flex-wrap:wrap;font-size:15px;color:var(--mut);margin:8px 0 0}
.ap-state a{color:var(--acc);font-weight:500;text-decoration:none}
.ap .ms-hero .ms-line .pos,.ap .ms-hero .ms-line .neg{font-weight:500}
.ap-alerts:empty{display:none}.ap-alerts{margin:14px 0 0}
.ap p.ap-w{margin:6px 0 0;font-size:15px;color:var(--fg)}
.ap p.ap-w::before{content:"";display:inline-block;width:8px;height:8px;border-radius:50%;background:var(--warn);margin:0 8px 1px 0;vertical-align:middle}
.ap p.ap-w.bad::before{background:var(--bad)}.ap p.ap-w.ok::before{background:var(--good)}
.ap-chart{margin:22px 0 0}.ap-chart:empty{display:none}
.ap .apc{display:flex;flex-direction:column}
.ap .apc-read{order:0;margin:0 0 6px}.ap .apc-plot{order:1}.ap .apc-top{order:2;margin:14px 0 0;gap:8px;flex-wrap:nowrap}
.ap .apc-leg{order:3;margin-top:10px}.ap .apc-tbl{order:4}
.ap .apc-seg{display:flex;background:var(--soft);border-radius:11px;padding:3px;gap:0}.ap .apc-seg[data-k=r]{flex:1}
.ap .apc-seg button{flex:1;font-size:13px;font-weight:400;padding:5px 12px;min-height:0;border-radius:9px;color:var(--fg)}
.ap .apc-seg button.on{background:#fff;font-weight:600;box-shadow:0 1px 3px rgba(11,18,32,.12)}
@media(max-width:700px){.ap .apc-seg[data-k=u]{display:none}}
.ap-grp{margin:0}
.ap-grp.ap-first{margin-top:18px}
details.ap-sec,details.ap-it{margin:0;padding:0;background:none;border:0;border-radius:0;border-bottom:1px solid var(--line)}
.ap-grp>details:last-child,#ap-pos>details:last-of-type{border-bottom:0}
details.ap-sec>summary,details.ap-it>summary{list-style:none;display:block;padding:0;cursor:pointer;color:var(--fg);
  user-select:none;-webkit-user-select:none;-webkit-touch-callout:none;touch-action:manipulation}
details.ap-sec>summary::-webkit-details-marker,details.ap-it>summary::-webkit-details-marker{display:none}
details.ap-sec>summary>.ms-row,details.ap-it>summary>.ms-row{border-bottom:0}
details[open]>summary>.ms-row>.ms-chev{transform:rotate(135deg);margin-top:-5px}
details>summary>.ms-row .ms-v.mut{font-weight:400}
.ap .in{font-size:15px;padding:2px 0 22px}.ap .in>:last-child{margin-bottom:0}
.ap .in details.ap-sec,.ap .in details.ap-it{border-top:1px solid var(--line);border-bottom:0}
.ap .in>details:first-child{border-top:0}
.ap h3.ap-sub{font-size:17px;font-weight:600;letter-spacing:-.01em;margin:18px 0 6px;display:flex;justify-content:space-between;gap:12px}
.ap .in>h3.ap-sub:first-child,.ap .in>div:first-child>h3.ap-sub:first-child,.ap-sk>h3.ap-sub:first-child{margin-top:0}.ap h3.ap-sub span+span{font-weight:400;color:var(--mut);font-size:15px}
.ap .ms-hint{font-size:15px}
.ap-wrap .ms-s,.ap-wrap.ms-row .ms-s{white-space:normal;overflow:visible;overflow-wrap:anywhere}
.ap-wrap.ms-row,.ap-wrap .ms-row{align-items:flex-start}.ap-wrap.ms-row .ms-e{max-width:45%}
.ap-wrap.ms-row .ms-e .ms-s{white-space:normal}
.ap .ms-row .ms-s a{color:var(--acc)}
.ap .ms-h2 .ap-n{font-size:15px;font-weight:400;color:var(--mut);letter-spacing:0}
.ap-btns{display:flex;gap:8px;flex-wrap:wrap;margin:10px 0 0}.ap-btns form{margin:0}.ap-btns button{min-height:42px}
.ap form.ap-danger{margin:0}
.ap button.ap-danger{display:block;width:100%;text-align:left;font-size:17px;color:var(--bad);background:none;border:0;
  border-top:1px solid var(--line);border-radius:0;padding:16px 0;min-height:0;box-shadow:none;cursor:pointer}
.ap button.ap-danger:hover{background:none;color:var(--bad);text-decoration:underline}
.ap-lnk{color:var(--acc);cursor:pointer;font-weight:500}
details.ap-it p,details.ap-sec p{margin:0 0 8px}
details.ap-it form,details.ap-sec form{margin:0 0 10px;display:flex;gap:6px;flex-wrap:wrap;align-items:center}
.ap-win{display:inline-flex;background:var(--soft);border-radius:11px;padding:3px;gap:0;margin:2px 0 10px}
.ap .ap-win button{border:0;background:none;padding:0 12px;min-height:30px;border-radius:9px;color:var(--fg);font-size:13px;font-weight:400}
.ap .ap-win button.on{background:#fff;font-weight:600;box-shadow:0 1px 3px rgba(11,18,32,.12)}
.ap-steps{margin:8px 0 0;padding-left:0;list-style:none;counter-reset:s}
.ap-steps li{margin:0 0 12px;padding-left:32px;position:relative}
.ap-steps li::before{position:absolute;left:0;top:0;width:22px;height:22px;border-radius:50%;text-align:center;
  line-height:22px;font-size:13px;background:var(--soft);color:var(--mut);counter-increment:s;content:counter(s)}
.ap-steps li.ok::before{background:var(--good);color:#fff}
.ap-steps form{margin:6px 0 0;display:flex;gap:6px;flex-wrap:wrap}
.ap-tag{font-size:13px;padding:0 7px;border-radius:999px;background:var(--soft);color:var(--mut);margin-left:6px;
  font-weight:400;white-space:nowrap}
.ap-tok{color:var(--acc);font-weight:600}
.ap-lim label{display:flex;justify-content:space-between;gap:10px;align-items:center;margin:10px 0}.ap-lim label.ap-chk{display:block}
.ap-lim input[type=text],.ap-lim input:not([type]){width:90px}
.ap .ms-row u{text-decoration:underline;text-decoration-color:var(--line2);text-underline-offset:3px;cursor:pointer}
.ap-sk{margin:0 0 6px}.ap .ap-sk p.ap-sk-h{font-size:17px;margin:0 0 4px}
.ap-sk .ms-row{min-height:0}
.ap-skr{flex-wrap:wrap;row-gap:2px}.ap-skr>.ms-m{flex:1 1 0}
.ap-skl{flex:1 0 100%;order:3;font-size:15px;color:var(--mut)}.ap-skl b{font-weight:400;color:var(--fg)}
.ap-skl .ap-skx{white-space:nowrap}
@media(max-width:560px){.ap-skl .ap-skc{display:block}.ap-skl .ap-sks{display:none}}
.ap .in table.t{font-size:13px}
#dnevnik>summary .ms-s,#influenceri>summary .ms-s{white-space:normal}
/* 10.11. (Jure): sticky section menu under the app header and the open quick buy under the chart */
.ap-fn{position:sticky;top:60px;z-index:20;display:flex;gap:6px;overflow-x:auto;padding:8px 0;margin:0 0 4px;
background:var(--bg);scrollbar-width:none}.ap-fn::-webkit-scrollbar{display:none}
.ap-fn a{flex:none;padding:6px 12px;border:1px solid var(--line);border-radius:999px;background:var(--card);
color:var(--fg);font-size:15px;text-decoration:none;white-space:nowrap}.ap-fn a:active{background:var(--line)}
.ap [id]{scroll-margin-top:120px}
.ap-qb{margin:16px 0 6px;padding:14px 16px;border:1px solid var(--line);border-radius:14px;background:var(--card)}
.ap-split{margin:-6px 0 8px;font-size:13px}
.ap-pnl{margin:4px 0 10px;padding:10px 12px;border:1px solid var(--line);border-radius:12px;background:var(--card)}
.ap-pnl .ap-pnl-v{font-size:22px}.ap-pnl>div{margin:2px 0}
/* 10.11. (Jure: "kako mjenjačnice rade na mobitelu"): green buy, red close, open orders with Otkaži, panels as tabs */
.ap button.ap-buy{background:var(--good,#16a34a);border-color:var(--good,#16a34a);color:#fff;font-weight:600}
.ap button.ap-wide{flex-basis:100%;min-height:48px;font-size:17px}
.ap-sellbar{display:grid;grid-template-columns:1fr 1fr 1.4fr;gap:8px}.ap-sellbar form{display:flex}
.ap-sellbar button{flex:1;min-height:48px;font-weight:600}
.ap button.ap-sellall{background:var(--bad,#dc2626);border-color:var(--bad,#dc2626);color:#fff}
.ap-ord{margin:8px 0 10px;border:1px solid var(--line);border-radius:12px;overflow:hidden}
.ap-ord-h{padding:8px 12px;font-size:13px;font-weight:600;background:var(--soft);color:var(--mut,#6b7280)}
.ap-ord-r{display:flex;align-items:center;justify-content:space-between;gap:8px;padding:8px 12px;margin:0;
border-top:1px solid var(--line);font-size:15px}
.ap button.ap-cancel{color:var(--bad,#dc2626);border-color:var(--bad,#dc2626);min-height:36px;padding:0 14px}
details.ap-pan{margin:8px 0;border:1px solid var(--line);border-radius:12px}
details.ap-pan>summary{list-style:none;cursor:pointer;padding:12px 14px;font-weight:600;display:flex;
justify-content:space-between}details.ap-pan>summary::-webkit-details-marker{display:none}
details.ap-pan>summary::after{content:"›";transform:rotate(90deg);color:var(--mut,#6b7280)}
details.ap-pan[open]>summary::after{transform:rotate(-90deg)}details.ap-pan>.in{padding:0 14px 10px}
.ap-toast{position:fixed;left:12px;right:12px;bottom:84px;z-index:60;padding:14px 40px 14px 16px;border-radius:14px;
font-size:15px;box-shadow:0 8px 24px rgba(0,0,0,.18);color:#fff;background:var(--good,#16a34a);max-width:640px;margin:0 auto}
.ap-toast.bad{background:var(--bad,#dc2626)}
.ap-grok{margin:8px 0;padding:10px 12px;border-radius:12px;background:var(--soft);border:1px solid var(--line)}.ap-grok p{margin:4px 0 0}.ap-grok-h{display:flex;gap:8px;align-items:center;font-weight:600}
.ap-sug{border-top:1px solid var(--line);padding:10px 0}.ap-sug:first-child{border-top:0}.ap-ev{white-space:pre-wrap;font-size:13px;max-height:240px;overflow:auto}
.ap-sum p{margin:0}.ap-toast-x{position:absolute;right:14px;top:10px;font-size:22px}
.ap-exit{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin:6px 0}
.ap-exit input{width:auto}
.ap-qb .ap-qb-h{font-size:17px;font-weight:600;margin:0 0 10px}
.ap-qb form{display:flex;flex-wrap:wrap;gap:8px;align-items:center}.ap-qb form input[name=token]{flex:1;min-width:200px}
.ap-qb p.mut{font-size:13px;margin:8px 0 0}
</style>"""

# 10.11. (Jure: "stranica mora biti čista"): the 7/14/30-day switch and the Phantom button are handled from the
# document, because the recommendations they sit in are fetched only when their section is opened.
JS = """<script>(()=>{document.addEventListener('click',async e=>{const b=e.target.closest('.ap-win button');
if(b){const sw=b.parentNode,g=sw.dataset.g;sw.querySelectorAll('button').forEach(x=>x.classList.toggle('on',x===b));
document.querySelectorAll('[data-pane="'+g+'"]').forEach(p=>p.hidden=p.dataset.w!==b.dataset.w);return}
if(!e.target.closest('#ap-phantom'))return;const p=(window.phantom&&window.phantom.solana)||window.solana;
if(p&&p.isPhantom){try{const r=await p.connect();document.getElementById('ap-addr').value=r.publicKey.toString();
document.getElementById('ap-addr-f').submit()}catch(x){alert('Phantom nije dao adresu: '+(x.message||x))}}
else{location.href='https://phantom.app/ul/browse/'+encodeURIComponent(location.href)+'?ref='+encodeURIComponent(location.origin)}})})()</script>"""

# 10.11. (Jure: "tu su tokeni na koje ne mogu kliknuti"): every live box was replaced as a whole once a second (the
# fetched text was compared with the browser's own innerHTML, which never matches), so a tap that landed while the
# rows were being replaced was lost, an opened "Zatvorene" closed again and a stake typed into a pop-up form could
# vanish. apPatch swaps only the top-level parts whose HTML really changed (compared with what the server sent last
# time, not with the live DOM), never while a finger is down or a field inside has focus; an empty answer shows the
# box's own sentence (data-empty); a part with data-meta copies its text where it says (a section's one-line summary).
# A box that still holds only its "učitavam…" is filled even right after the tap that opened it (that tap is what
# asked for it); a refused swap (finger down, field in focus) returns false and the poller asks again a moment later
# (10.11., screenshots: the recommendations, fetched once, stayed at "učitavam…" for ever).
PATCH_JS = """<script>(()=>{if(window.apPatch)return;const SRC=new WeakMap();let down=0,held=false;
addEventListener('pointerdown',()=>{down=Date.now();held=true},true);
addEventListener('pointerup',()=>{down=Date.now();held=false},true);addEventListener('pointercancel',()=>{held=false},true);
addEventListener('touchstart',()=>{down=Date.now();held=true},{capture:true,passive:true});
addEventListener('touchend',()=>{down=Date.now();held=false},{capture:true,passive:true});
window.apSeen=box=>{for(const c of box.children)if(!SRC.has(c))SRC.set(c,c.outerHTML)};
window.apPatch=(box,h)=>{const virgin=![...box.children].some(c=>SRC.has(c));
if((!virgin&&(held||Date.now()-down<1200))||box.contains(document.activeElement))return false;
if(!h.trim()&&box.dataset.empty){const p=document.createElement('p');p.className='mut';p.textContent=box.dataset.empty;h=p.outerHTML}
const t=document.createElement('template');t.innerHTML=h;const a=[...box.children],b=[...t.content.children];
b.forEach((n,i)=>{const s=n.outerHTML,o=a[i];if(o&&SRC.get(o)===s)return;SRC.set(n,s);if(o)o.replaceWith(n);else box.appendChild(n)});
a.slice(b.length).forEach(o=>o.remove());
box.querySelectorAll('[data-meta]').forEach(m=>{const to=document.querySelector(m.dataset.meta);if(to&&to.textContent!==m.textContent)to.textContent=m.textContent});
if(window.apOpen)window.apOpen(box);if(window.apcInit)window.apcInit();return true}})()</script>"""


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


def _steps_ok(cfg, addr, sol, n_open):
    """Which of the four setup steps are done, from what we can see without asking anybody: [address saved, enough
    SOL for the first buy, key in Render, switch on]. Shared by the setup list and the state line's "Dovrši 3/4"."""
    return [bool(addr), sol is not None and sol >= _need_sol(cfg, n_open), executor.armed(), bool(cfg["on"])]


def _setup(tcon, cfg, addr, key_addr, saved, sol, usdc, n_open):
    """The four steps to a working wallet, ticked from what we can see: {'html', 'warn', 'done', 'total', 'ready'}.
    10.11. (Jure, prijedlog 3.4 "spaja pilulu stanja i Postavljanje walleta"): the steps live inside the row "Wallet i
    uplata" under "Još"; while the wallet is not ready (address, SOL, key: 'ready' False) the state line under the
    title says "Dovrši 3/4" and opens them. 'html' is the inside of that row (the row itself is _wallet_row)."""
    need = _need_sol(cfg, n_open)
    texts = [
        "<b>Napravi zaseban račun u Phantomu.</b> U Phantomu dodirni ikonu računa gore lijevo → "
        "<i>Add / Connect Wallet</i> → <i>Create New Account</i>. Ne koristi glavni wallet: bot smije "
        "potrošiti sve što je u ovom."
        + ('<form method=post action=/pravi-trade/wallet id=ap-addr-f>'
           f'<input id=ap-addr name=addr placeholder="javna adresa walleta" value="{esc(saved or "")}" '
           'style="flex:1;min-width:200px" autocomplete=off spellcheck=false>'
           '<button>Spremi adresu</button>'
           '<button type=button id=ap-phantom title="Phantom daje samo javnu adresu, ništa ne potpisuje">'
           'Poveži Phantom (samo adresa)</button></form>'),
        f"<b>Uplati SOL na tu adresu.</b> Za prvu kupnju treba barem <b>{redak.sol(need, 3)}</b> (ulog "
        f"{_g(cfg['size_sol'])} + naknade i rezerva koja uvijek ostaje u walletu da bot može "
        "platiti mrežne naknade prodaje). Imaš USDC? Bot kupuje SOL-om i njime plaća naknade, pa USDC prvo zamijeni: "
        '<a href="https://jup.ag/swap/USDC-SOL" target=_blank rel=noopener>Zamijeni USDC u SOL na Jupiteru ↗</a>'
        + (f'<br><span class=mut>Sada u walletu: {redak.num(usdc, 2)} USDC.</span>' if usdc else ""),
        "<b>Ključ bot-walleta postavlja samo vlasnik, izravno u Renderu.</b> U "
        f'<a href="{_render_env_url()}" target=_blank rel=noopener>Render → Environment ↗</a> moraju postojati '
        "<code>SOLANA_PRIVATE_KEY</code> i <code>TRADE_LIVE</code> = <code>1</code>. Aplikacija ključ nikad ne traži, "
        "ne sprema i ne prikazuje, i nitko ga ne upisuje ovdje ni u chat.",
        "<b>Odaberi koga bot prati</b> (redak „Koga prati”) i uključi prekidač gore desno. "
        "Za prvi put stavi ulog 0,01 SOL u Pravilima i pogledaj prvu kupnju na Solscanu.",
    ]
    oks = _steps_ok(cfg, addr, sol, n_open)
    done = sum(oks)
    warn = ""
    if key_addr and saved and key_addr != saved:
        warn = (f'<p class="ap-w bad">Ključ u Renderu pripada drugom walletu (<code>{esc(short(key_addr))}</code>) '
                f'nego spremljena adresa (<code>{esc(short(saved))}</code>). Bot trguje s walletom ključa.</p>')
    items = "".join(f'<li class="{"ok" if ok else ""}">{txt}</li>' for ok, txt in zip(oks, texts))
    ready = all(oks[:3])
    html = (f'<h3 class=ap-sub><span>Postavljanje walleta</span><span>{done}/{len(texts)} gotovo</span></h3>'
            f"<ol class=ap-steps>{items}</ol>")
    return {"html": html, "warn": warn, "done": done, "total": len(texts), "ready": ready, "sol": sol, "usdc": usdc}


def _dec(x):
    """Decimals a setting needs to be read as typed: 0.05 -> 2, 0.005 -> 3, 1 -> 0 (for redak.num)."""
    t = f"{float(x):g}"
    return len(t.split(".")[1]) if "." in t and "e" not in t else 0


def _g(x):
    """A setting as typed, with a decimal comma: 0.05 -> "0,05", 1 -> "1" (the old f"{x:g}")."""
    try:
        return redak.num(x, _dec(x))
    except (TypeError, ValueError):
        return str(x)


# ---------- money over time: trade/equity.py (another group's module, so always behind try/except) --------------

HEAD_EVERY_S = 45      # the browser asks for the header + chart again this often (dizajn.md: at most every 30-60 s)
EQ_TTL_S = 30          # the series, summary and deposits are read from trade.db at most this often (a snapshot is 5 min)
RATES_TTL_S = 60       # trade.equity.rates() keeps SOL for 60 s itself; asked from a side thread, never from a request
RATES_MAX_AGE_S = 600  # older live rates are not "live": the header falls back to the rates of the last snapshot
_EQ = {"ts": 0.0, "key": None, "val": None}
_RATES = {"ts": 0.0, "val": None, "busy": False}
_NO_EQUITY = {"series": [], "summary": {}, "deposits": []}


def _equity_mod():
    try:
        from trade import equity
        return equity
    except Exception:  # noqa: BLE001 - not merged yet, or broken: the header shows the plain balance instead
        return None


def equity_data(tcon, now=None):
    """{'series', 'summary', 'deposits'} from trade.equity for the header and the chart; empty parts when the module
    or its table is missing. The whole history comes thinned to 600 points, the last 24 h once more in full, so the
    24-h view is not a handful of dots. Cached EQ_TTL_S per database: the 45-s header poll of every viewer and the
    page itself share one read."""
    now = now or time.time()
    with _LOCK:
        if _EQ["val"] is not None and _EQ["key"] == settings.DB and now - _EQ["ts"] < EQ_TTL_S:
            return _EQ["val"]
    eq = _equity_mod()
    out = dict(_NO_EQUITY)
    if eq is not None:
        try:
            coarse = list(eq.series(tcon, since=None, max_points=600) or [])
            fine = list(eq.series(tcon, since=int(now - 86400), max_points=300) or []) if coarse else []
            if fine:
                coarse = [p for p in coarse if p["ts"] < fine[0]["ts"]] + fine
            out = {"series": coarse, "summary": dict(eq.summary(tcon, now) or {}), "deposits": list(eq.deposits(tcon) or [])}
        except Exception as e:  # noqa: BLE001 - the page and the 45-s fragment must render without the history
            print(f"autopilot: povijest vrijednosti walleta nije dostupna: {type(e).__name__}: {e}", flush=True)
            out = dict(_NO_EQUITY)
    with _LOCK:
        _EQ.update(ts=now, key=settings.DB, val=out)
    return out


def _rates_fetch(eq):
    try:
        val = eq.rates()
    except Exception as e:  # noqa: BLE001
        print(f"autopilot: tečaj SOL-a nije dostupan: {type(e).__name__}: {e}", flush=True)
        val = None
    with _LOCK:
        _RATES.update(ts=time.time(), busy=False, val=val if val and val.get("sol_usd") else _RATES["val"])


def _rates(summary, now=None):
    """{'sol_usd', 'usd_eur'} for the header ("pokraj 1 SOL živa pretvorba u dolare i eure"): trade.equity.rates(),
    asked in a side thread at most once in RATES_TTL_S (its first call in this process may go to the network, and a
    request must never wait for that); until it answers, and when it is older than RATES_MAX_AGE_S, the rates of
    the last snapshot. With the refresher off (tests) the call is made here."""
    now = now or time.time()
    snap = {"sol_usd": summary.get("sol_usd"), "usd_eur": summary.get("usd_eur")}
    eq = _equity_mod()
    if eq is None or not hasattr(eq, "rates"):
        return snap
    with _LOCK:
        due = now - _RATES["ts"] >= RATES_TTL_S and not _RATES["busy"]
        if due:
            _RATES["busy"] = True
    if due and BG_REFRESH:
        try:
            threading.Thread(target=_rates_fetch, args=(eq,), daemon=True, name="autopilot-tecaj").start()
        except RuntimeError:   # 10.11. (Jure): no thread to spare must not leave "busy" set for ever (no rate again)
            with _LOCK:
                _RATES.update(ts=time.time(), busy=False)
    elif due:
        _rates_fetch(eq)
    with _LOCK:
        live, ts = _RATES["val"], _RATES["ts"]
    if live and live.get("sol_usd") and now - (live.get("ts") or ts) < RATES_MAX_AGE_S:
        return {"sol_usd": live["sol_usd"], "usd_eur": live.get("usd_eur") or snap["usd_eur"]}
    return snap


def _fiat(x):
    """187 / 12,40 / 1 234: whole units from 100 up, a decimal comma below (pravilo 8), a space between thousands."""
    return redak.num(x, 0 if abs(x) >= 100 else 2)


def _state(cfg):
    """(dot colour, words) of the line under the title: real money, on without the key (trial only), or off.
    10.11. (maketa autopilot.html: "● Probno: ključ još nije postavljen"): plain words after a dot, no capitals;
    "Uključen" / "Isključen" is said once, in the title row (with the switch for the owner)."""
    if cfg["on"] and executor.armed():
        return "good", "Trguje pravim novcem"
    if cfg["on"]:
        return "warn", "Probno: ključ još nije postavljen"
    return "", "Samo probno, bez novca"


def _addr_html(addr):
    if not addr:
        return "<span>Wallet još nije postavljen.</span>"
    return (f'<span translate=no title="{esc(addr)}"><code>{esc(short(addr))}</code> · '
            f'<a href="#" role=button data-m="{esc(addr)}" onclick="var m=this.dataset.m,b=this;'
            f"(navigator.clipboard?navigator.clipboard.writeText(m):Promise.reject()).then(function(){{b.textContent='kopirano'}},"
            f"function(){{prompt('Kopiraj adresu:',m)}});return false\">kopiraj adresu</a> · "
            f'<a href="https://solscan.io/account/{quote(addr)}" target=_blank rel=noopener>Solscan ↗</a></span>')


def _signed(x, dec=3, unit="SOL"):
    """A signed number coloured by its sign (pravilo 4, the only place for green and red): "+0,029 SOL", "−3,7 %"."""
    txt = redak.sol(x, dec, sign=True) if unit == "SOL" else redak.pct(x, dec)
    t = redak.tone(x)
    return Html(f'<span class="{t}">{redak.h(txt)}</span>') if t else redak.h(txt)


def _value_html(s, r):
    """The big number (maketa: "2,00 SOL", under it "≈ 323 $ · 278 € · danas 0,00 SOL"): the wallet's whole value in
    SOL and one line with the same in dollars and euros at the live rate, the result of the last 24 h and the result
    in total against the money put in. 10.11.: the rate of 1 SOL, the money put in, the part in open positions and
    USDC moved one tap away, into "Wallet i uplata" under "Još" (pravilo 6)."""
    val, usd, eur = float(s["value_sol"]), r.get("sol_usd"), r.get("usd_eur")
    bits = []
    if usd:
        bits.append(f"≈ {_fiat(val * usd)} $" + (f" · {_fiat(val * usd * eur)} €" if eur else ""))
    p24, pnl, net = s.get("pnl_24h_sol"), s.get("pnl_sol"), s.get("net_in_sol")
    if p24 is not None:
        bits.append(cat("24 h ", _signed(p24)))
    if pnl is not None and net and net > 0:   # the share is counted from the two SOL amounts, never another unit
        bits.append(cat("ukupno ", _signed(100.0 * pnl / net, 1, "%")))
    return redak.hero(redak.num(val, 3), why=cat(*bits, sep=" · ") if bits else None, big=True, unit="SOL")


def _split_html(s):
    """10.11. (Jure: "glavni kredit se nije pomakao nakon kupovine"): the big number is the wallet's whole value, SOL
    plus open positions at the market price, so a buy only moves SOL into a position and the number stays (minus the
    fees). This line says where the value is: free SOL, the part in positions, and the clock time of the snapshot it
    comes from (trade/equity, one every 5 min, none in the 45 s after a swap)."""
    import datetime as _dt
    import zoneinfo
    sol, tok, ts = s.get("sol"), s.get("tokens_sol") or 0.0, s.get("last_ts")
    if sol is None:
        return ""
    when = (_dt.datetime.fromtimestamp(ts, zoneinfo.ZoneInfo("Europe/Zagreb")).strftime("%H:%M") if ts else "")
    bits = [f"slobodno {redak.num(sol, 3)} SOL", f"u pozicijama {redak.num(tok, 3)} SOL"] + ([f"stanje u {when}"] if when else [])
    return f'<p class="mut ap-split">{esc(" · ".join(bits))}</p>'


def _switch_html(on, n_open=0):
    """The owner's switch in the title row (maketa: "Uključen" and a switch; it replaces the button "Isključi
    Autopilot (nove kupnje staju)"). Same form and the same confirmation as the buttons before it. "Prodaj sve i
    isključi" is under the open positions now (SELL_ALL), where the positions it sells are."""
    if on:
        form = ('<form method=post action=/pravi-trade/switch onsubmit="return confirm(\'Isključiti Autopilot? Nove '
                'kupnje staju odmah, otvorene pozicije se i dalje prodaju po pravilima.\')"><input type=hidden name=on '
                'value=0><button class="ap-sw on" role=switch aria-checked=true aria-label="Isključi Autopilot" '
                'title="Isključi Autopilot"></button></form>')
    else:
        form = ('<form method=post action=/pravi-trade/switch onsubmit="return confirm(\'Uključiti Autopilot? Bot će '
                'SAM kupovati pravim SOL-om iz walleta, i preko noći, unutar Limita, dok ne dodirneš Isključi.\')">'
                '<input type=hidden name=on value=1><button class=ap-sw role=switch aria-checked=false '
                'aria-label="Uključi Autopilot (pravi novac)" title="Uključi Autopilot (pravi novac)"></button></form>')
    return f'<div class=ap-tog><span>{"Uključen" if on else "Isključen"}</span>{form}</div>'


SELL_ALL = ('<form method=post action=/pravi-trade/sellall class=ap-danger onsubmit="return confirm(\'Prodati SVE otvorene '
            'pozicije odmah i isključiti Autopilot?\')"><button class=ap-danger>Prodaj sve i isključi</button></form>')


def _title(owner=False, on=None, n_open=0):
    """The title row: "Autopilot" and the switch for the owner; an invited player reads the same word without it."""
    right = (_switch_html(on, n_open) if owner else
             f'<div class=ap-tog><span>{"Uključen" if on else "Isključen"}</span></div>' if on is not None else "")
    return f'<div class="ms-top ap-top"><h1 class=ms-h1>{TITLE}</h1>{right}</div>'


def _head_inner(tcon, cfg, con, owner, now=None, msg=""):
    """Inside of the header (#ap-head), also the answer of /pravi-trade/graf: the title with the owner's switch, the
    state line (with "Dovrši 3/4" while the wallet is not ready), the wallet's value as one big number, whatever stops
    a trade right now, and the chart. Every part is one top-level element, so the 45-s refresh swaps only the parts
    that changed (PATCH_JS). Without trade.equity (or before its first snapshot) the value is the plain SOL balance
    of the wallet, as before. msg: the answer to the owner's last form (page view only; the refresh drops it)."""
    now = now or time.time()
    armed, on = executor.armed(), cfg["on"]
    addr, _key_addr, _saved = _addr(tcon)
    eq = equity_data(tcon, now)
    s = eq["summary"]
    has_eq = s.get("value_sol") is not None
    n_open = tcon.execute("SELECT COUNT(*) FROM positions WHERE status='open' AND mode=?",
                          ("live" if on and armed else "dry",)).fetchone()[0]
    if has_eq:
        hero = _value_html(s, _rates(s, now))
        sol_now = s.get("sol")
    else:   # no history yet (or no trade.equity): the plain balance, with the live rate when there is one
        sol_now = _balance(addr)
        r = _rates({}, now) if sol_now is not None else {}
        usd, eur = r.get("sol_usd"), r.get("usd_eur")
        bits = [f"≈ {_fiat(sol_now * usd)} $" + (f" · {_fiat(sol_now * usd * eur)} €" if eur else "")] if usd else []
        try:   # without the history the line says today's result (all fees in), as the header did before
            day = _today(tcon, cfg)
            if day["spent"] or day["pnl"]:
                bits.append(cat("danas ", _signed(day["pnl"], 4)))
        except Exception:  # noqa: BLE001
            pass
        hero = redak.hero("–" if sol_now is None else redak.num(sol_now, 3), why=cat(*bits, sep=" · ") if bits else None,
                          big=True, unit="SOL")
    d, words = _state(cfg)
    link = ""
    if owner:   # the setup steps are under "Još"; while the wallet is not ready the state line leads there
        oks = _steps_ok(cfg, addr, sol_now, n_open)
        if not all(oks[:3]):
            link = f'<a href="#postavljanje">Dovrši {sum(oks)}/{len(oks)}</a>'
    b = [_title(owner, on, n_open), f"<div class=ap-state><span>{dot(d, words)}</span>{link}</div>", hero]
    if has_eq:
        b.append(_split_html(s))
    alerts = msg + ('<p class="ap-w bad">Prodaja svega je u tijeku…</p>' if cfg.get("sell_all") else "")
    try:
        alerts += _warnings(tcon, cfg, con)
    except Exception as e:  # noqa: BLE001 - a broken check must not cost the owner the switch above it
        print(f"autopilot: upozorenja nisu složena: {type(e).__name__}: {e}", flush=True)
    b.append(f"<div class=ap-alerts>{alerts}</div>")
    chart = ""
    if _equity_mod() is not None:   # without trade.equity no snapshot will ever come: no promise of a chart either
        try:
            from ui import apchart
            chart = apchart.chart_html(eq["series"], s, eq["deposits"], ident="ap")
        except Exception as e:  # noqa: BLE001 - the header stays without the chart
            print(f"autopilot: graf nije nacrtan: {type(e).__name__}: {e}", flush=True)
    b.append(f"<div class=ap-chart>{chart}</div>")
    try:   # the closed log's one-line summary rides along, so it is never older than the header
        b.append(f'<span hidden data-meta="#ap-dn-sum">{esc(dnevnik_line(tcon, now))}</span>')
    except Exception:  # noqa: BLE001
        pass
    return "".join(b)


def _head(tcon, cfg, con, owner, msg=""):
    return (f'<section class=ap-head id=ap-head data-src=/pravi-trade/graf data-every={HEAD_EVERY_S}>'
            f'{_head_inner(tcon, cfg, con, owner, msg=msg)}</section>')


def head_fragment(user):
    """GET /pravi-trade/graf: the header with the chart, same access as the page."""
    tcon = _tcon()
    try:
        if not settings.can_view(tcon, user):
            return None
        cfg, owner = _cfg(tcon), settings.is_owner(user)
        con = store.connect()
        try:
            copy.ensure(con)
            return _head_inner(tcon, cfg, con, owner)
        finally:
            con.close()
    finally:
        tcon.close()


def _today(tcon, cfg, result=True, now=None):
    """Today's spend (in the mode the switch trades in) and, with result=True, today's result with all fees:
    {'spent', 'pnl', 'live'}. 10.11.: the spend is said in the "Pravila" row against the daily limit; the result
    is the "danas" in the line under the big number while there is no value history (with it, that line says the
    last 24 h)."""
    now = now or time.time()
    live = executor.is_live(cfg)
    mode = "live" if live else "dry"
    start = executor._day_start(now, cfg.get("day_tz"))
    spent = tcon.execute("SELECT COALESCE(SUM(sol_in),0) FROM positions WHERE mode=? AND opened_ts>=? AND status IN "
                         "('open','closed','pending')", (mode, start)).fetchone()[0]
    pnl = executor.day_pnl(tcon, now, mode, cfg.get("day_tz")) if result else 0
    return {"spent": float(spent or 0), "pnl": float(pnl or 0), "live": live}


POP_HTML = ('<dialog id=ap-pop><div class=bar2><span class=mut id=ap-pop-age style="font-size:13px"></span>'
            '<button onclick="this.closest(\'dialog\').close()">Zatvori</button></div><div class=body><p class=mut>Učitavam…</p></div></dialog>')
# 9.11. (Jure): everything opens in a pop-up, never a new page, and the pop-up re-fetches its content every second
# while it is open (the swap is skipped while a field inside it has focus, so a stake being typed is never lost)
# 9.11. 23:10 (Jure: the pop-up stays at "Učitavam…"): setInterval fired a new request every second whether or not
# the previous one had come back; with the server busy they piled up (each one more work for it) and none returned.
# Now one request at a time per pop-up (cur = the URL in flight), given up after POP_TIMEOUT_MS, an answer for a
# pop-up that was closed or changed meanwhile is dropped, and a slow server is said in the header instead of silence.
# 10.11.: the body is no longer replaced as a whole every second (PATCH_JS): a stake typed into the buy form stays
# when the field loses focus, and a tap on "Kupi" cannot land on a form that is being replaced.
# 10.11. (Jure: pop-up preskočenog signala): a [data-pop] inside an open pop-up (its link to the token's live check)
# swaps the content in place; showModal() is called only on a closed dialog (on an open one older browsers throw).
POP_TIMEOUT_MS = 8000
POP_JS = ("<script>(()=>{const d=document.getElementById('ap-pop');if(!d||window.__appop)return;window.__appop=1;let url='',t=null,n=0,cur=null,ctl=null;"
          "const age=document.getElementById('ap-pop-age');"
          "async function load(){if(!url||cur===url)return;const u=url;cur=u;let to=null;"
          "try{ctl=new AbortController();const c=ctl;to=setTimeout(()=>c.abort()," + str(POP_TIMEOUT_MS) + ");"
          "const r=await fetch(u,{cache:'no-store',signal:c.signal});if(u!==url)return;"
          "if(!r.ok){age.textContent='nema svježih podataka';return}const h=await r.text();if(u!==url)return;"
          "const b=d.querySelector('.body');if(window.apPatch)window.apPatch(b,h);else if(!b.contains(document.activeElement))b.innerHTML=h;"
          "n++;age.textContent='uživo · osvježeno '+new Date().toLocaleTimeString()}"
          "catch(e){if(u===url)age.textContent='server je spor, pokušavam ponovno…'}"
          "finally{clearTimeout(to);if(cur===u)cur=null}}"
          "document.addEventListener('click',e=>{const el=e.target.closest('[data-pop]');if(!el||e.target.closest('a,button,input,select,form'))return;"
          "e.preventDefault();if(ctl)ctl.abort();url=el.dataset.pop;age.textContent='';d.querySelector('.body').innerHTML='<p class=mut>Učitavam…</p>';if(!d.open)d.showModal();load();"
          "clearInterval(t);t=setInterval(load,1000)});"
          "d.addEventListener('close',()=>{clearInterval(t);url='';if(ctl)ctl.abort()});d.addEventListener('click',e=>{if(e.target===d)d.close()})})()</script>")
POP_CSS = ("<style>dialog#ap-pop{border:0;border-radius:18px;padding:0;max-width:min(96vw,680px);width:96vw;background:var(--card);color:var(--fg)}"
           "dialog#ap-pop::backdrop{background:rgba(0,0,0,.45)}dialog#ap-pop .bar2{display:flex;justify-content:space-between;align-items:center;padding:10px 14px;border-bottom:1px solid var(--line)}"
           "dialog#ap-pop .body{padding:10px 14px 16px;font-size:15px;line-height:1.45}dialog#ap-pop .body h3{margin:10px 0 4px;font-size:17px}"
           ".ap-row{display:flex;justify-content:space-between;gap:8px;align-items:center;padding:10px 0;border-top:1px solid var(--line);cursor:pointer;"
           "user-select:none;-webkit-user-select:none;-webkit-touch-callout:none;touch-action:manipulation}.ap-row .k{font-size:13px;color:var(--mut);text-align:right;white-space:nowrap}"
           ".ap-row b{font-weight:600}.ap-za{color:var(--good)}.ap-protiv{color:var(--bad)}.ap-verdict{font-weight:700;padding:6px 10px;border-radius:10px;margin:6px 0;display:inline-block}"
           ".ap-verdict.ok{background:var(--goodbg);color:var(--good)}.ap-verdict.ne{background:var(--badbg);color:var(--bad)}"
           ".ap-tag.ap-mine{background:var(--goodbg);color:var(--good)}"
           "table.ap-mk{width:100%;border-collapse:collapse;font-size:13px;margin:6px 0}table.ap-mk th,table.ap-mk td{padding:5px 6px;"
           "text-align:right;border-top:1px solid var(--line);white-space:nowrap}table.ap-mk th{font-weight:600;color:var(--mut)}"
           "table.ap-mk td:first-child,table.ap-mk th:first-child{text-align:left;color:var(--mut)}"
           ".ap-mk .pos{color:var(--good)}.ap-mk .neg{color:var(--bad)}"
           ".ap-box{display:flex;gap:8px;flex-wrap:wrap;margin:6px 0}.ap-box div{flex:1;min-width:92px;border:1px solid var(--line);"
           "border-radius:10px;padding:6px 8px;text-align:center}.ap-box small{display:block;color:var(--mut);font-size:13px}"
           ".ap-box b{font-size:15px}"
           # 10.11. (Jure: pop-up preskočenog signala): one small table, the market cap the strongest number in a row
           "table.ap-skt{font-size:15px;margin:12px 0 10px;max-width:480px}table.ap-skt th{font-size:13px;font-weight:500}"
           "table.ap-skt td,table.ap-skt th{padding:7px 4px}table.ap-skt td:first-child{color:var(--fg);white-space:normal;padding-left:0}"
           "table.ap-skt td:last-child,table.ap-skt th:last-child{padding-right:0}"
           "table.ap-skt td:nth-child(2){color:var(--mut)}table.ap-skt td:nth-child(3){font-weight:600}"
           "table.ap-skt tr.ap-now td{border-top:1px solid var(--line2)}"
           ".ap-skp-w{margin:0;color:var(--mut)}.ap-skp-s{color:var(--fg)}.ap-skp-v{margin:0 0 6px}</style>")


_CHEV = '<span class="ms-chev" aria-hidden="true"></span>'


def _srow(name, reason=None, value=None, sub=None, **kw):
    """The shared row (ui/redak.row) for inside a <summary>: the same look and the same arrow, but no link of its
    own, because the tap opens the section (TOGGLE_JS) instead of leaving the page."""
    r = row(name, reason, value, sub, **kw)
    return raw(r[:-len("</div>")] + _CHEV + "</div>")


def _prow(tok, **kw):
    """The shared row for a token on this page: a tap opens the Autopilot's own live pop-up (/pravi-trade/token,
    POP_JS: verdict, market, buy form), the same as before 10.11., not the evidence pop-up of the other pages that
    redak.row(mint=...) would open."""
    if not tok:
        return row(**kw)
    r = row(mint=tok, **kw)
    return raw(r.replace(f'data-mint="{redak.h(tok)}"', f'data-pop="/pravi-trade/token?m={quote(tok)}"', 1))


def _sec(title, meta, inner, open_=False, sid="", hidden=False, value=None, sub=None):
    """A section that opens on a tap. 10.11. (maketa autopilot.html): closed it is one shared row (name, one line,
    at most one number, the arrow; ui/redak.row), opened the content follows under it. title/meta are text, or Html
    when they carry markup."""
    r = _srow(title, meta or None, value, sub, value_tone="mut" if value not in (None, "") else None)
    return (f'<details class=ap-sec{f" id={sid}" if sid else ""}{" open" if open_ else ""}{" hidden" if hidden else ""}>'
            f'<summary>{r}</summary><div class=in>{inner}</div></details>')


def _item(name, reason, inner, value=None, sub=None, iid="", value_tone=None):
    """One opening row inside a section (a follow, a recommendation, a position): the same row as _sec, one level
    down. iid: an id, so the row stays open across the 1-s refresh (TOGGLE_JS remembers open rows by id)."""
    r = _srow(name, reason or None, value, sub, value_tone=value_tone)
    return (f'<details class=ap-it{f" id={iid}" if iid else ""}><summary>{r}</summary>'
            f'<div class=in>{inner}</div></details>')


def _group(*parts, first=False):
    """Rows that belong together (maketa: "Kako trguje", "Još"); the last one has no line under it."""
    body = "".join(p for p in parts if p)
    return f'<div class="ap-grp{" ap-first" if first else ""}">{body}</div>' if body else ""


def _h2(title, right="", rid="", sid=""):
    """Section title (22 px) with a quiet count on the right, e.g. "Otvorene pozicije 3 od 5"."""
    i = f" id={sid}" if sid else ""
    r = f'<span class=ap-n{f" id={rid}" if rid else ""}>{esc(right)}</span>' if (right or rid) else ""
    # data-sec="": no chip bar (ui/secnav) built from these titles (prijedlog pravilo 6: no standing bars)
    return f'<h2 class=ms-h2{i} data-sec=""><span>{esc(title)}</span>{r}</h2>'


# ---------- who the bot follows ----------------------------------------------------------------------------------

def _auto_box(st, owner):
    """The switch that lets the tool choose whom to follow (Nicholas 4.11.: "neka alat sam odredi koga pratit")."""
    from ui.autopilot import WINDOWS
    on, days, n = bool(st.get("auto_pick")), int(st.get("auto_days") or 14), int(st.get("auto_n") or 3)
    what = f"<b>Alat sam bira koga prati:</b> {'uključeno' if on else 'isključeno'}."
    if on:
        what += f" Bira {n} influencera i {n} walleta po rezultatima zadnjih {days} dana, provjera svaki sat."
    # 10.11. (pravilo 6: bez ⓘ): what the tool does with its picks, as one quiet sentence under the switch
    how = ('<p class=mut>Svaki sat uzme najbolje influencere (samo one koje pratimo uživo) i wallete iz preporuka; koga '
           'je on dodao, njega i makne kad ispadne iz najboljih. Tvoja ručna praćenja ne dira, a koga sam prestaneš '
           'pratiti, ne vraća.</p>')
    log = st.get("auto_log") or []
    hist = "".join(f'<li>{"dodao" if x["op"] == "+" else "maknuo"} '
                   f'{"@" + esc(x["target"]) if x["kind"] == "kol" else esc(short(x["target"]))} '
                   f'<span class=mut>({esc(redak.ago(x["ts"]))}): {esc(x["why"])}</span></li>' for x in log[:5])
    hist = _item("Zadnje promjene alata", None, f'<ul class=mut style="margin:0;padding-left:18px">{hist}</ul>',
                 value=str(len(log)), value_tone="mut") if log else ""
    if not owner:
        return f'<p>{what}</p>{how}{hist}'
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
               'prati pravim novcem (kad je Autopilot uključen). Uključiti?\')">Neka alat sam bira</button>')
            + '</form>')
    return f'<p>{what}</p>{form}{how}{hist}'


_KIND_WORD = {"kol": "influencer", "ekipa": "ekipa", "wallet": "wallet"}


def _follow_name(f):
    """A follow as plain text for its row: @handle, the Telegram channel, the crew's members, a wallet's label or
    its short address (a wallet's label can be the whole address)."""
    if f["kind"] == "ekipa":
        return " + ".join(m[3:] if m.startswith("tg:") else "@" + m for m in copy.members_of(f["target"]))
    if f["kind"] == "kol":
        return f["target"][3:] if f["target"].startswith("tg:") else "@" + f["target"]
    lab = f.get("label") or ""
    return lab if lab and len(lab) < 30 else short(f["target"])


def _follow_exit_form(f, st):
    """10.11. (Jure: "za svakog influencera mogu odabrati poseban take profit ili stop loss"): this follow's own TP /
    SL for every new entry: quick TP buttons (the stop stays) and both to type; optionally also on its open positions.
    POST /pravi-trade/followexit."""
    ex = f["exit"] or {}
    tp_now = ex.get("tp", "") if ex.get("mode") == "tpsl" else ""
    sl_now = ex.get("sl", "") if ex.get("mode") == "tpsl" else ""
    sl0 = settings.sl_text((st or {}).get("sl_default") or settings.SL_DEFAULT)
    quick = "".join(
        f'<form method=post action=/pravi-trade/followexit style="margin:0"><input type=hidden name=id value={f["id"]}>'
        f'<input type=hidden name=tp value="{v}%"><input type=hidden name=sl value="{esc(sl_now)}">'
        f'<button{" class=ap-go" if tp_now.lstrip("+") in (f"{v}%", str(v)) else ""}>TP +{v} %</button></form>'
        for v in EXIT_TP_QUICK)
    return (f'<h3 class=ap-sub><span>Izlaz za ovo praćenje</span><span>{esc(copy.describe_exit(ex, copy.default_sl(f["user"])) or "zadano")}</span></h3>'
            f'<div class=ap-btns>{quick}</div>'
            f'<form method=post action=/pravi-trade/followexit class=ap-exit><input type=hidden name=id value={f["id"]}>'
            f'<label>TP <input name=tp value="{esc(tp_now)}" placeholder="npr. 30%" size=7 autocomplete=off></label> '
            f'<label>SL <input name=sl value="{esc(sl_now)}" placeholder="zadano {esc(sl0)}" size=9 autocomplete=off></label> '
            '<label class=ap-chk><input type=checkbox name=open value=1> i na njegove otvorene pozicije</label> '
            '<button>Spremi izlaz</button></form>'
            '<p class=mut>Vrijedi za svaki novi ulaz na njegov signal. Postotak od ulaza ili MC (npr. $200k); prazan SL = '
            'zadani stop iz „Pravila”.</p>')


def _follows(con, owner, st=None, prefill=""):
    """"Koga prati" under "Kako trguje" (maketa): one row with the names and how many; opened, the tool's own
    choice, the form to follow anybody (owner), and one row per follow (who, what kind, entries) that opens its
    numbers and "Prestani pratiti"."""
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
            who = " + ".join(f'<a href="/kol/{quote(m)}">{esc(m) if m.startswith("tg:") else "@" + esc(m)}</a>'
                                    for m in copy.members_of(f["target"]))
        else:
            who = (f'<a href="/kol/{quote(f["target"])}">@{esc(f["target"])}</a>' if f["kind"] == "kol"
                   else wlink(f["target"]) + (f" {esc(f['label'])}" if f["label"] else ""))
        stop = (f'<form method=post action=/pravi-trade/stop><input type=hidden name=id value={f["id"]}>'
                '<button>Prestani pratiti</button></form>') if owner else ""
        if owner and f["exit"].get("mode") != "podaci":
            stop = _follow_exit_form(f, st) + stop
        by = f["id"] in auto_ids
        try:
            dline = _data_exit_line(f)
        except Exception:  # noqa: BLE001 - the list renders without the statistic
            dline = ""
        ex_words = copy.describe_exit(f["exit"], copy.default_sl(f["user"]))
        reason = " · ".join(x for x in (_KIND_WORD.get(f["kind"], f["kind"]), "odabrao alat" if by else "",
                                         esc(ex_words or "zadani izlaz")) if x)
        inner = (f'<p>{who}</p><p>Najviše {f["per_day"]} ulaza na dan · izlaz: {esc(ex_words or "zadano")}'
                 f' · prati od {esc(redak.ago(f["created"]))}{" · dodao ga je alat" if by else ""}</p>'
                 f'<p class=mut>{last24}</p>'
                 + (f'<p class=mut>{dline}</p>' if dline else '')
                 + f'<p class=mut>{proof}</p>{stop}')
        items.append(_item(_follow_name(f), raw(reason), inner, value=str(r["n"]), sub="ulaza",
                           iid=f"prati-{f['id']}", value_tone="mut"))
    # 10.11. (screenshots): the closed row names two at most, a wallet by its short address
    names = ", ".join(_follow_name(f) for f in fl[:2])
    pre = esc(prefill or "")
    meta = ((f"{names} i još {len(fl) - 2}" if len(fl) > 2 else names) if fl else "još nikoga") + (
        " · alat bira sam" if st.get("auto_pick") else "")
    anyone = ""
    if owner:   # 9.11. (Jure): follow any wallet or influencer from the whole database, not only the recommended ones
        anyone = ('<h3 class=ap-sub><span>Zaprati</span></h3>'
                  '<form method=post action=/pravi-trade/follow style="margin:0 0 4px"><input type=hidden name=kind value=auto>'
                  f'<input name=target placeholder="adresa walleta, @influencer, tg:kanal ili ekipa: tg:a, tg:b, @c" required value="{pre}" style="flex:1;min-width:220px">'
                  '<label>na dan <input name=per_day value=5 inputmode=numeric style="width:46px"></label>'
                  '<select name=exit aria-label="Izlaz"><option value="">zadano</option><option value=mirror>prodaj kad on proda</option>'
                  f'<option value=tpsl{" selected" if pre else ""}>moj TP/SL</option>'
                  '<option value=podaci>po podacima (alat bira TP/SL)</option></select><input name=tp placeholder="TP %" size=6> <input name=sl placeholder="SL %" size=6>'
                  '<label>do MC <input name=max_mcap placeholder="npr. 1M" size=6></label> <label>ne ako je već <input name=max_runup placeholder="+25 %" size=5></label> '
                  '<label>od <select name=min_callers aria-label="Koliko iz ekipe mora zvati"><option value=1>1. poziva</option><option value=2>2 zovu</option><option value=3>3 zovu</option></select></label>'
                  '<button class=ap-go>Zaprati</button></form><p class=mut>Ekipa = više računa odvojenih zarezom: '
                  'jedan ulaz po tokenu čim prvi od njih objavi (ili kad ih zove 2–3), samo dok je token ispod zadanog MC-a (zadano 1M $) i '
                  'nije već narastao više od zadanog (+25 %) od poziva. Wallet koji još ne pratimo uživo dodaje se u Helius webhook odmah. '
                  'Izlaz „po podacima” (influenceri i ekipe): alat pri svakom ulazu sam bira TP/SL iz izmjerenih poziva tog računa '
                  'i ne ulazi kad nijedan par nije u plusu; ulazi samo do 2 min nakon poziva i dok cijena nije već +10 % '
                  '(tako je i mjereno), a pozicija se zatvara najkasnije nakon 60 min.</p>')
    try:
        pool_box = _pool_line()
    except Exception:  # noqa: BLE001
        pool_box = ""
    listed = ("".join(items) or '<p class=mut>Još nikoga. Upiši koga pratiti ili odaberi iz preporuka alata pod „Još”.</p>')
    inner = (listed + pool_box + '<h3 class=ap-sub><span>Automatski izbor</span></h3>' + _auto_box(st, owner) + anyone)
    # 10.11. (Jure: "nek su sve zatvorene kartice za početak, osim grafa, brze kupnje i otvorenih pozicija"): open
    # only when a crew is being filled in from "Zovu sada" (prefill)
    return _sec("Koga prati", meta, inner, open_=bool(prefill), sid="pratim", value=str(len(fl)) if fl else None)


_DATA_EXIT = {}        # follow id -> (wall time, exit signature, decision): the page asks once a minute, not per render
DATA_EXIT_TTL_S = 60
POOL_SHOW = ((15, 20), (20, 40), (20, 20), (30, 15), (15, 60), (30, 60))   # the pairs Jure asked about, two with the
# target >= the stop, and (10.11., plan 1.3) the Autopilot's own default TP 15 / SL 60 next to TP 30 / SL 60


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
        tail = (f" Do tada vrijedi zadani izlaz TP +{copy.DATA_TP.rstrip('%')} % / SL {copy.default_sl(f['user']).rstrip('%')} %."
                if own else "")
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
        cells.append(f'<tr><td>TP +{tp} % / SL −{sl} %{" (najbolji)" if k == best[0] else ""}</td>'
                     f'<td class=n>{redak.pct(d["tp"], sign=False, frac=True)}</td>'
                     f'<td class=n>{redak.pct(d["need"], sign=False, frac=True)}</td>'
                     f'<td class="n {"pos" if d["ev"] > 0 else "neg"}">{redak.pct(d["ev"], 1)}</td></tr>')
    inner = ('<table class=t><tr><th>izlaz</th><th class=n>cilj prije stopa</th>'
             '<th class=n>treba za nulu</th><th class=n>po tradeu</th></tr>' + "".join(cells) + '</table>'
             f'<p class=mut>Račun: treba = (SL + trošak) / (TP + SL), trošak {_g(p.get("cost", 2))} % '
             'po krugu. Širi stop traži VIŠE pogodaka, ne manje; isplati se samo ako dovoljno zaustavljenih tradeova pretvori '
             'u dobitne. Mjereno 60 min nakon poziva; što ne dotakne ni cilj ni stop, izlazi po cijeni nakon 60 min. '
             'Stariji pozivi (prije 10.11.) imaju točnu minutu samo za stop −20 %, ostali stopovi se za njih računaju oprezno; '
             'stop −60 % se mjeri od 10.11. navečer, stari pozivi se premjeravaju po noći.</p>')
    return _item("Koji TP/SL se isplati", f"svi izmjereni pozivi, 30 d", inner, value=redak.num(p["n"]), sub="poziva",
                 value_tone="mut")


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
    # 10.11. (Jure: "koga već pratim ne prikazuj u prijedlozima"): this went through copy.follows(), which needs a
    # Row connection; "Zovu sada" calls it with a plain read-only one, the TypeError was swallowed there and the
    # followed set was always EMPTY, so nobody ever left that list. A plain query works on any connection.
    try:
        rows = con.execute("SELECT kind, target FROM follows WHERE user = ? AND active = 1", (settings.LEAGUE_USER,)).fetchall()
    except sqlite3.OperationalError:   # no follows table yet
        return out
    for kind, target in rows:
        out.add(target)
        if kind == "ekipa":
            out |= set(copy.members_of(target))
    return out


def _is_followed(name, followed):
    """Is this account (X handle, 'tg:kanal', wallet or 'w:wallet') one the bot already follows? X handles and
    Telegram names in any letter case (a follow typed as @Ansem is the account stored as ansem)."""
    n = name[2:] if name.startswith("w:") else name
    return n in followed or n.lower() in {x.lower() for x in followed}


def _canonical(handle, kol_db=None):
    """The handle as kol.db stores it (X and Telegram names are case-insensitive, the databases are not): a follow
    typed as '@Ansem' must become 'ansem', or league/copy.events (exact match) never sees his calls and the lists
    keep offering him. Unknown accounts stay as typed."""
    if not handle or re.fullmatch(r"[1-9A-HJ-NP-Za-km-z]{32,44}", handle):
        return handle
    try:
        kc = copy._ro(kol_db or copy._paths()["kol"])
        if kc is None:
            return handle
        try:
            r = copy._q(kc, "SELECT handle FROM kols WHERE handle = ? COLLATE NOCASE LIMIT 1", (handle,))
        finally:
            kc.close()
        return r[0][0] if r else handle
    except Exception:  # noqa: BLE001 - the name as typed is still a valid follow
        return handle


def _follow_btn(kind, target, label, have, owner):
    if (kind, target) in have:
        return (f"<p>{dot('good', 'već pratiš')}" + (' · <a href="/pravi-trade#pratim">promijeni TP/SL</a>' if owner else "")
                + "</p>")
    if not owner:
        return ""
    return ('<form method=post action=/pravi-trade/follow onsubmit="return confirm(\'Bot će kupovati pravim novcem na '
            'svaki njegov ' + ("call" if kind == "kol" else "kup") + ' (kad je Autopilot uključen), dok ga ne prestaneš '
            f'pratiti. Pratiti?\')"><input type=hidden name=kind value={kind}><input type=hidden name=target '
            f'value="{esc(target)}"><input type=hidden name=label value="{esc(label or "")}">'
            # 10.11. (Jure: "za svakog influencera poseban TP ili SL, to isto može biti u pop-upu"): his own TP / SL
            # right on the button; empty = the targets set under "Pravila"
            '<input type=hidden name=per_day value=5><input type=hidden name=exit value=tpsl>'
            '<input name=tp placeholder="TP zadano" size=8 autocomplete=off aria-label="Take profit"> '
            '<input name=sl placeholder="SL zadano" size=8 autocomplete=off aria-label="Stop loss"> '
            '<button>Prati pravim novcem</button></form>')


def _kol_verdict(r, days):
    """(dot colour, word) of the shared influencer verdict (ui/kolsummary, prijedlog 4.0: "drži se", "samo brzo",
    "ne isplati se", "premalo poziva") for a recommendation row: the row's own when ui/autopilot gives it, else
    asked from kolsummary (one cached build per window for every page). None when neither is there."""
    w, k = r.get("verdict"), r.get("verdict_key")
    try:
        from ui import kolsummary
        if not w:
            v = kolsummary.kol_verdict(r["handle"], days=days)
            w, k = v["word"], v["key"]
        return kolsummary.VERDICT_DOT.get(k, ""), w
    except Exception:  # noqa: BLE001 - the list renders without the word
        return ("", w) if w else None


def _can_copy(r):
    """10.11. (Jure, influencer ranking): an account the bot can actually copy is one we watch live (we enter in
    seconds); ui/autopilot gives it as "can_copy", older rows say the same as "live"."""
    return bool(r.get("can_copy", r.get("live")))


def _kol_item(r, days, have, owner):
    """One recommended influencer: the shared verdict word and the minute check's share as the one number (maketa:
    "● samo brzo · 30 poziva", "70 %"). An account the minute check has not measured often enough says so instead
    of a percentage; the old 24-h wick is only a detail inside. An account we do not watch live gets no follow
    button (the bot would come too late)."""
    s = r["s"]
    mi = s.get("minute") or {}
    v = _kol_verdict(r, days)
    if s.get("mjera") == "minutna" and mi.get("n"):   # 9.11. (audit P12/P15/P16): the minute measure first
        value, sub = redak.pct(mi.get("hit10") or 0, sign=False, frac=True), "u 1 h"
        fact = f'{mi["n"]} poziva'
        detail = f'{value} poziva dođe do +10 % prije stopa −20 % u prvom satu ({mi["n"]} izmjerenih).'
    else:
        value = sub = None
        fact = "premalo minutnih poziva"
        detail = (f'Stara mjera: {redak.pct(s.get("hit") or 0, sign=False, frac=True)} pogodaka u {s.get("n") or 0} '
                  'poziva (vrh +50 % u 24 h); minutna provjera još nema dovoljno poziva.')
    if v and v[1].startswith("premalo") and fact.startswith("premalo"):   # one "premalo", in the words that say why
        v, fact = (v[0], fact), (f'{s["n"]} poziva' if s.get("n") else "")
    reason = cat(dot(v[0], v[1]) if v else None, fact, "uživo" if r.get("live") else None, sep=" · ")
    inner = (f'<p>{esc(r.get("why") or "")}</p><p class=mut>{esc(detail)}</p>'
             f'<p><a href="/kol/{quote(r["handle"])}">Profil @{esc(r["handle"])}</a></p>'
             + (_follow_btn("kol", r["handle"], "", have, owner) if _can_copy(r) else
                "<p class=mut>Ne pratimo ga uživo, pa bi bot u njegove pozive ušao prekasno.</p>"))
    return _item(f'@{r["handle"]}', reason, inner, value=value, sub=sub)


def _kol_section(con, owner):
    """Preporučeni influenceri. 10.11. (Jure, the ranking made honest): the best of 14 days is named only when the
    bot can copy him (watched live) and the minute check has measured him; accounts we do not watch live are a quiet
    group of their own without the follow button; every row carries the shared verdict word."""
    from ui import autopilot
    recs = autopilot.kol_recs()
    have = {(f["kind"], f["target"]) for f in copy.follows(con, settings.LEAGUE_USER)}
    followed = followed_targets(con)
    need = getattr(autopilot, "MIN_MINUTE", 10)
    panes = {}
    any_items = False
    for d, rows_d in recs.items():
        cand = [x for x in rows_d if not _is_followed(x["handle"], followed)][:autopilot.SHOW]
        any_items = any_items or bool(cand)
        fast, slow = [r for r in cand if _can_copy(r)], [r for r in cand if not _can_copy(r)]
        html = "".join(_kol_item(r, d, have, owner) for r in fast)
        if not html:
            html = (f'<p class=mut>U zadnjih {d} dana nitko nema barem {autopilot.MIN_CALLS} izmjerena calla s malo rugova.</p>'
                    if not cand else f'<p class=mut>Nijedan praćeni uživo još nema {need} izmjerenih poziva.</p>')
        if slow:
            html += ('<h3 class=ap-sub><span>Dobri, ali prespori za nas (ne pratimo ih uživo)</span></h3>'
                     + "".join(_kol_item(r, d, have, owner) for r in slow))
        panes[d] = html
    if not any_items:   # 9.11. (Jure): an empty list is noise; the section appears when there is somebody to follow
        return ""
    best = next((r for r in recs.get(14) or [] if not _is_followed(r["handle"], followed) and _can_copy(r)
                 and (r.get("s") or {}).get("mjera") == "minutna"), None)
    if best:
        v = _kol_verdict(best, 14)
        meta = f'najbolji 14 d: @{best["handle"]}' + (f" · {v[1]}" if v else "")
    else:
        meta = f"nijedan praćeni uživo još nema {need} izmjerenih poziva"
    inner = (_windows("kol", panes)
             + '<p class=ms-hint>Minutna provjera = +10 % prije stopa −20 % u 60 min od minute poziva; "pogodak" (stara '
               'mjera, samo gdje minutne provjere još nema) = +50 % u 24 h. Uživo = pratimo ga uživo, pa bot stigne ući '
               'na vrijeme.</p>')
    return _sec("Preporučeni influenceri", meta, inner, sid="influenceri")


def _dokazani_items(rows, have, owner, names=None):
    """The proven-twice wallets (wallets/dokazani.py) with their own on-chain result before and after the cut."""
    names = names or {}
    items = []
    for r in rows:
        nm = names.get(r["wallet"])
        style = {"swing": "swing", "scalper": "scalper", "bot": "bot", "sniper": "sniper"}.get(r.get("style") or "", r.get("style") or "")
        why = (f'Prije reza: {redak.sol(r["realized_before"], 1, sign=True)} na {r["closed_before"]} zatvorenih '
               f'({redak.pct(r["win_before"], sign=False, frac=True)} u plusu). '
               f'Poslije reza: {redak.sol(r["realized_after"], 1, sign=True)} na {r["closed_after"]} zatvorenih'
               + (f' ({redak.pct(r["win_after"], sign=False, frac=True)} u plusu)' if r.get("win_after") is not None else "") + ". "
               + (f'Drži medijan {r["hold_min"]:.0f} min, {r["tpd"]:.0f} tradeova dnevno' if r.get("hold_min") is not None and r.get("tpd") is not None else "")
               + (f', stil {style}' if style else "")
               # 9.11. (audit P55): open losers he never closed ("bags"), so a nice realized PnL is read with them
               + (f' · {int(r["bags"])} bagova (kupljeni tokeni koje nije zatvorio)' if r.get("bags") is not None else "") + ".")
        reason = " · ".join(x for x in (short(r["wallet"]) if nm else "",
                                         f'{r["closed_before"] + r["closed_after"]} zatvorenih', style) if x)
        inner = (f'<p>{esc(why)}</p><p>{wlink(r["wallet"])}</p>'
                 + _follow_btn("wallet", r["wallet"], nm or "", have, owner))
        items.append(_item(nm or short(r["wallet"]), reason, inner, value=redak.sol(r["realized_after"], 1, sign=True),
                           sub="poslije reza", value_tone=redak.tone(r["realized_after"])))
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
    dok = ('<h3 class=ap-sub><span>Dokazani dvaput</span></h3>'
           + (_dokazani_items(proven, have, owner, names) or
              '<p class=mut>Lista se računa svaka 3 sata iz pohranjenih tradeova; prvi put nakon današnjeg deploya. Dok je prazna, nema koga kopirati.</p>')
           + '<p class=ms-hint>5+ zatvorenih pozicija s plusom i 50 %+ dobitnih prije reza od 5 dana, pa opet plus poslije '
             'reza; samo walleti koje se može kopirati (drže 10+ min, do 50 tradeova dnevno, bez bot/sniper oznaka). Brojke '
             'su njihov vlastiti rezultat na lancu, ne naša kopija.</p>')
    panes = {}
    for d, rows_d in recs.items():
        items = []
        for r in rows_d[:autopilot.SHOW]:
            st = r["s"]
            inner = (f'<p>{esc(r["why"])}</p><p>{wlink(r["wallet"])}</p>'
                     + _follow_btn("wallet", r["wallet"], r["name"], have, owner))
            items.append(_item(r["name"] or short(r["wallet"]),
                               f'{short(r["wallet"]) + " · " if r["name"] else ""}{redak.pct(st["win"], sign=False, frac=True)} u plusu',
                               inner, value=redak.pct(st["roi"], frac=True), sub="povrat", value_tone=redak.tone(st["roi"])))
        # 9.11. (audit P14): chain_trades sells carry no SOL amount, so the window return is mostly unknown; say so
        panes[d] = "".join(items) or (f'<p class=mut>U zadnjih {d} dana nijedan wallet koji pratimo uživo nema barem '
                                      f'{autopilot.MIN_CLOSED} prodana tokena s poznatim povratom u plusu (iznos prodaja '
                                      f'se često ne zapisuje, pa je povrat po prozoru nepoznat; auto-izbor uzima '
                                      f'"dokazane dvaput" gore).</p>')
    best = next((r for r in recs.get(14) or []), None)
    meta = f'najbolji 14 d: {redak.pct(best["s"]["roi"], frac=True)}' if best else "po zadnjih 7/14/30 dana"
    inner = (dok + '<h3 class=ap-sub><span>Po zadnjih 7/14/30 dana</span></h3>'
             + _windows("wal", panes)
             + '<p class=ms-hint>Samo walleti koje pratimo uživo, da bot kupi u sekundama nakon njih. Povrat = koliko je '
               'SOL-a vratio na tokenima koje je kupio i prodao u tom razdoblju, iz njegovih kupnji i prodaja na lancu; '
               'gledamo postotak, ne SOL, jer bot ulaže svoj, manji iznos.</p>')
    meta = f"{len(proven)} dokazanih · " + meta
    return _sec("Preporučeni walleti", meta, inner, sid="walleti")


def _buy_form(mint, cfg, exit_mode, owner):
    if not owner:
        return (f'<p><a href="https://jup.ag/swap/SOL-{quote(mint)}" target=_blank rel=noopener>Kupi i ti iz svog '
                'walleta (Jupiter) ↗</a></p>')
    opts = "".join(f'<option value={v}{" selected" if v == exit_mode else ""}>{lab}</option>'
                   for v, lab in (("smart", "Smart sell"), ("tpsl", "moj TP/SL"), ("manual", "prodajem sam")))
    sl0 = _sl0(cfg)
    tp_last, sl_last = _last_exit(cfg)   # 10.11. (Jure): the TP / SL used last, not always the default
    return ('<form method=post action=/pravi-trade/buy class=ap-buyf onsubmit="return confirm(\'Kupiti ovaj token pravim novcem '
            f'(ako je Autopilot uključen)?\')"><input type=hidden name=token value="{esc(mint)}">'
            f'<label>SOL <input name=sol value="{cfg["size_sol"]:g}" inputmode=decimal style="width:64px"></label>'
            f'<select name=exit aria-label="Kako prodati">{opts}</select>'
            f'<label>TP <input name=tp placeholder="npr. 100%" size=7{f" value={esc(tp_last)}" if exit_mode == "tpsl" else ""}></label> '
            f'<label>SL <input name=sl placeholder="zadano {sl0}" size=8 value="{esc(sl_last)}"></label>'
            '<button class=ap-buy>Kupi</button></form>')


def _last_exit(cfg):
    """(TP, SL) to put in a buy form: what the owner used last (settings last_exit), else the default target and an
    empty stop (= the default stop)."""
    le = (cfg or {}).get("last_exit") or {}
    return (le.get("tp") or f'{(cfg or {}).get("tp_default", 15)}%'), (le.get("sl") or "")


FLOAT_NAV = (("ap-head", "Graf", False), ("kupi-odmah", "Kupi", True), ("dnevnik", "Dnevnik", False),
             ("pozicije", "Pozicije", False), ("pratim", "Prati", False), ("pravila", "Pravila", False), ("jos", "Još", False))
FLOAT_JS = ("<script>(()=>{document.querySelectorAll('.ap-fn a').forEach(a=>a.addEventListener('click',()=>{"
            "const t=document.getElementById(a.getAttribute('href').slice(1));"
            "if(t&&t.tagName==='DETAILS')t.open=true}))})()</script>")


def _float_nav(owner):
    """10.11. (Jure: "dodaj gore floating izbornik da lakše dođem do pojedinih stavki na autopilot stranici"): a
    sticky row of links under the app header; a link to a closed section also opens it."""
    links = "".join(f'<a href="#{sid}">{esc(word)}</a>' for sid, word, own in FLOAT_NAV if owner or not own)
    return f'<nav class=ap-fn aria-label="Dijelovi stranice">{links}</nav>' + FLOAT_JS


MCP_URL = os.environ.get("MCP_PUBLIC_URL") or "https://app.memesonar.app/mcp"


def _mcp_section(tcon, owner):
    """10.11. (Jure: "napravi mcp key, ne znam raditi s pip install"): Grok connects to the MCP endpoint the app
    hosts; the owner makes the key with one tap and copies it from here (it never goes through a chat)."""
    if not owner:
        return ""
    from ui import mcpapi
    k = str(settings.raw(tcon).get("mcp_key") or "")
    env = bool((os.environ.get("MCP_API_KEY") or "").strip())
    if env:
        inner = ("<p>Ključ je postavljen na Renderu (MCP_API_KEY); vrijedi on, ne ovaj s stranice.</p>")
    elif k:
        inner = (f'<p><b>Adresa:</b> <code>{esc(MCP_URL)}</code></p>'
                 f'<p><b>Ključ:</b> <input id=mcpk type=password value="{esc(k)}" readonly style="width:100%;max-width:440px" '
                 'autocomplete=off> <button type=button onclick="var i=document.getElementById(\'mcpk\');'
                 'i.type=i.type===\'password\'?\'text\':\'password\'">Prikaži</button> '
                 '<button type=button class=ap-buy onclick="var i=document.getElementById(\'mcpk\');'
                 '(navigator.clipboard?navigator.clipboard.writeText(i.value):Promise.reject()).then(()=>{this.textContent='
                 '\'Kopirano\'},()=>{i.type=\'text\';i.select()})">Kopiraj ključ</button></p>'
                 '<p class=mut>U Groku dodaj MCP server: URL gornja adresa, zaglavlje <code>Authorization</code> s '
                 'vrijednošću <code>Bearer &lt;ključ&gt;</code>. Ključ ne šalji u chat ni u objave.</p>'
                 '<div class=ap-btns><form method=post action=/pravi-trade/mcpkey onsubmit="return confirm(\'Napraviti novi '
                 'ključ? Stari prestaje raditi odmah.\')" style="margin:0"><button>Novi ključ</button></form>'
                 '<form method=post action=/pravi-trade/mcpkeyoff onsubmit="return confirm(\'Ugasiti pristup za Groka?\')" '
                 'style="margin:0"><button class=ap-cancel>Ugasi pristup</button></form></div>')
    else:
        inner = ('<p>Grok se spaja na MemeSonar preko adrese <code>' + esc(MCP_URL) + '</code>. Ništa ne treba '
                 'instalirati.</p><form method=post action=/pravi-trade/mcpkey style="margin:0"><button class="ap-buy ap-wide">'
                 'Napravi MCP ključ</button></form>')
    inner += ('<p class=mut>Grok vidi signale, token i portfelj; trgovinu samo traži, a ona čeka tvoje „Odobri” na vrhu '
              'ove stranice.</p>')
    meta = "uključen" if (k or env) else "isključen"
    return _sec("Grok (MCP)", meta, inner, sid="mcp")


VERDICT_TONE = {"dobar": "good", "kupi": "good", "loš": "bad", "preskoči": "warn", "neutralan": ""}


def _grok_box(note, compact=False):
    """10.11.: the assistant's newest trade_review / signal_opinion of a position or a token: verdict, confidence,
    interpretation, improvement. Advice only; nothing in trading reads it."""
    if not note:
        return ""
    v = note.get("verdict") or "bilješka"
    conf = f' · sigurnost {note["confidence"] * 100:.0f} %' if note.get("confidence") is not None else ""
    head = (f'<div class=ap-grok-h>{dot(VERDICT_TONE.get(v, ""), "Grok: " + v)}<span class=mut>{conf} · '
            f'{esc(redak.ago(note.get("ts")))}</span></div>')
    body = f'<p>{esc(note.get("interpretation") or "")}</p>'
    if note.get("improvement") and not compact:
        body += f'<p><b>Poboljšanje:</b> {esc(note["improvement"])}</p>'
    return f'<div class=ap-grok>{head}{body}</div>'


def _change_words(pc):
    """A proposed_change as one readable line ("sl_default: 60 → 40", "težina callera @x → 0.5")."""
    if not isinstance(pc, dict):
        return ""
    if "caller" in pc:
        return f'težina callera {pc.get("caller")} ({pc.get("platform") or "x"}) → {pc.get("weight")}'
    if "key" in pc:
        return f'{pc.get("key")}: {pc.get("from", "?")} → {pc.get("to", "?")}' + (f' ({pc["file"]})' if pc.get("file") else "")
    return json.dumps(pc, ensure_ascii=False)[:300]


def _suggest_section(tcon, owner):
    """10.11.: "Prijedlozi asistenta": the assistant's suggestions (kind suggestion, status novo), newest first, with
    the evidence and the proposed change as a readable line, and Prihvati / Odbij / Primijeni with an optional note.
    Primijeni applies only the allow-listed keys (ui/assistnotes.APPLY) and logs old -> new."""
    if not owner:
        return ""
    from ui import assistnotes
    rows, total = assistnotes.notes(tcon, "novo", "suggestion", 30, 0)
    if not rows:
        return ""
    items = []
    for r in rows:
        pc = r.get("proposed_change")
        auto = isinstance(pc, dict) and ("caller" in pc or pc.get("key") in assistnotes.APPLY)
        ev = (f'<details><summary class=mut>Dokazi</summary><pre class=ap-ev>{esc(json.dumps(r["evidence"], ensure_ascii=False, indent=1)[:4000])}</pre></details>'
              if r.get("evidence") else "")
        diff = (f'<p class=ap-diff><b>Promjena:</b> <code>{esc(_change_words(pc))}</code>'
                + ("" if auto else ' <span class=mut>(bot je ne zna primijeniti sam: „Primijeni na bota” je samo '
                                   'označi kao prihvaćenu za ručnu izmjenu)</span>')
                + "</p>") if pc else ""
        items.append(
            f'<div class=ap-sug id=as-{r["id"]}><p><b>{esc(r.get("title") or "")}</b> <span class=mut>· {esc(redak.ago(r["ts"]))}</span></p>'
            f'<p>{esc(r.get("interpretation") or "")}</p>'
            + (f'<p><b>Poboljšanje:</b> {esc(r["improvement"])}</p>' if r.get("improvement") else "")
            + diff + ev
            + f'<form method=post action=/pravi-trade/asok class=ap-exit><input type=hidden name=id value={int(r["id"])}>'
            '<input name=note placeholder="tvoja bilješka (nije obavezno)" maxlength=1000 style="flex:1;min-width:160px" autocomplete=off>'
            # 10.11. (Jure: "prihvaćaju li se promjene kad kliknem Prihvati?"): the words say what each tap does
            '<button>Označi prihvaćenim (bez promjene)</button>'
            '<button formaction=/pravi-trade/asno class=ap-cancel>Odbij</button>'
            '<button formaction=/pravi-trade/asapply class=ap-buy onclick="return confirm(\'Primijeniti ovu promjenu na bota?\')">'
            'Primijeni na bota</button>'
            '</form></div>')
    inner = ("".join(items) + '<p class=mut>Prijedloge piše asistent preko MCP-a; ništa se ne mijenja dok ne tapneš. '
             '„Označi prihvaćenim” samo zapiše da se slažeš, bot radi isto. „Primijeni na bota” mijenja postavku: TP, '
             'stop, ulog, broj pozicija, preskočeni, filtri kopiranja, strop SOL-a po tokenu, prag rasta od prvog poziva, '
             'pravilo bez signala i težina callera; staru i novu vrijednost zapisuje. Pravila iza zastavice (težina '
             'callera, strop po tokenu, prag rasta, bez signala) tako idu u sjenu: zapisuju što bi napravila, a uživo '
             'ih uključuješ ti pod „Zastavice plana”, nakon backtesta.</p>')
    return _sec("Prijedlozi asistenta", f"{total} čeka", inner, sid="prijedlozi")


def _summary_card(tcon, owner):
    """10.11.: the assistant's newest daily summary, at the top of the page (owner only)."""
    if not owner:
        return ""
    from ui import assistnotes
    n = assistnotes.latest_summary(tcon)
    if not n:
        return ""
    return (f'<section class="ap-qb ap-sum" id=sazetak><h2 class=ap-qb-h>{esc(n.get("title") or "Dnevni sažetak")} '
            f'<span class=mut>· Grok · {esc(redak.ago(n["ts"]))}</span></h2><p>{esc(n.get("interpretation") or "")}</p></section>')


def _mcp_requests(tcon, owner):
    """10.11. (MCP server MemeSonar, Grok's execute_trade): the trade requests that wait for the owner, each with
    Odobri / Odbij. Nothing a client asks for moves money before this tap (ui/mcpapi.py)."""
    if not owner:
        return ""
    from ui import mcpapi
    reqs = mcpapi.pending(tcon)
    if not reqs:
        return ""
    from ui import assistnotes
    ops = assistnotes.latest_for(tcon, tokens=[r["token"] for r in reqs])
    rows = []
    for r in reqs:
        amt = float(r["amount"])   # 10.11.: no nested quotes inside an f-string (Python 3.11 on older hosts)
        what = (f"Kupi <b>{esc(format(amt, 'g'))} SOL</b>" if r["side"] == "buy"
                else f"Prodaj <b>{esc(format(amt * 100, 'g'))} %</b>")
        rows.append(
            f'<div class=ap-ord-r><span>{what} · <code>{esc(short(r["token"]))}</code>'
            + (f'<br><span class=mut>{esc(r.get("reason") or "")}</span>' if r.get("reason") else "")
            + _grok_box(ops.get(("t", r["token"])), compact=True)
            + f'</span><span style="display:flex;gap:6px">'
            f'<form method=post action=/pravi-trade/mcpok style="margin:0" onsubmit="return confirm(\'Odobriti ovaj zahtjev? '
            f'Ide pravim novcem ako je Autopilot uključen.\')"><input type=hidden name=id value="{esc(r["id"])}">'
            '<button class=ap-buy>Odobri</button></form>'
            f'<form method=post action=/pravi-trade/mcpno style="margin:0"><input type=hidden name=id value="{esc(r["id"])}">'
            '<button class=ap-cancel>Odbij</button></form></span></div>')
    return (f'<section class=ap-qb id=mcp-zahtjevi><h2 class=ap-qb-h>Zahtjevi s Groka · {len(reqs)}</h2>'
            f'<div class=ap-ord>{"".join(rows)}</div><p class=mut>Zahtjev vrijedi 15 min. Kupnja ide kao tvoja ručna '
            'kupnja (zadnji TP/SL), prodaja kao tvoj gumb Prodaj.</p></section>')


def _buy_now_card(cfg, owner):
    """9.11. (Jure): buy any token right now with the amount you choose: address + SOL + Kupi.
    Exit defaults to the target chosen in "Pravila" (TP) and, with no stop typed in, the default stop
    league/copy.DEFAULT_SL (audit P17/P19: the page used to promise "the usual stop" that did not exist); the rest
    sits behind "Više". 10.11. (maketa): the row "Kupi ručno" under "Kako trguje"; the form and its confirmation
    are the same."""
    if not owner:
        return ""
    sl0 = _sl0(cfg)
    tp_last, sl_last = _last_exit(cfg)   # 10.11. (Jure: "neka ostane zapamćen za sljedeću narudžbu, a ne default")
    # 10.11. (Jure: "kako mjenjačnice rade na mobitelu"): the order ticket as on an exchange: token, amount, TP and SL
    # in sight (prefilled with the last ones used), one wide green "Kupi"; the exit kind behind "Više"
    inner = ('<form method=post action=/pravi-trade/buy onsubmit="return confirm(\'Kupiti ovaj token pravim novcem '
             '(ako je Autopilot uključen)?\')"><input name=token placeholder="adresa tokena ili DexScreener link" '
             'required style="flex:1;min-width:200px" autocomplete=off spellcheck=false>'
             f'<label>SOL <input name=sol value="{cfg["size_sol"]:g}" inputmode=decimal style="width:64px"></label>'
             # 10.11. (Jure: "buy order na određenom market capu i odmah TP i SL; sad je 90k, kupi ako dođe na 50k"):
             # empty = buy now; a market cap (or -40 % from now) = a waiting buy order, its TP/SL count from that entry
             '<label>Kupi na MC <input name=at placeholder="odmah ili $50k" size=9 autocomplete=off></label>'
             f'<label>TP <input name=tp value="{esc(tp_last)}" placeholder="npr. 30%" size=6 autocomplete=off></label>'
             f'<label>SL <input name=sl value="{esc(sl_last)}" placeholder="zadano {sl0}" size=8 autocomplete=off></label>'
             '<button class="ap-buy ap-wide">Kupi</button>'
             '<details style="flex-basis:100%"><summary class=mut>Više (način izlaza)</summary>'
             '<select name=exit aria-label="Kako prodati"><option value=tpsl>moj TP/SL</option><option value=smart>Smart sell</option>'
             '<option value=manual>prodajem sam</option></select></details></form>'
             '<p class=mut>Prolazi iste provjere i limite kao automatske kupnje. Pravi novac ide samo kad je Autopilot '
             'uključen; inače je ovo probna kupnja. Prodaja: dodirni poziciju pod „Otvorene pozicije”. „Kupi na MC” '
             '(npr. $50k ili -40%) postavlja nalog koji kupi kad MC padne na tu razinu, s TP-om i SL-om od tog ulaza; '
             f'vrijedi {LIMIT_HOURS} h.</p>' + _limit_orders_html(cfg))
    # 10.11. (Jure: "nema opcije za brzo kupovanje koja treba biti odmah ispod grafa jer je to glavna stvar"): an open
    # block right under the chart, not a closed row under "Kako trguje"; the form and its confirmation are the same
    return f'<section class=ap-qb id=kupi-odmah><h2 class=ap-qb-h>Brza kupnja</h2>{inner}</section>'


TP_CHOICES = (5, 10, 15, 20, 30)


def _tp_card(cfg, owner):
    """9.11. (Jure): the exit target for new copies: 5 / 10 / 15 / 20 / 30 %. New follows and buys with 'moj TP/SL'
    get it when their TP box is empty. 10.11. (maketa: "Pravila" spaja "Cilj izlaza" i "Limiti"): the first block
    inside the row "Pravila" (id=cilj stays the anchor the form returns to)."""
    cur = int(cfg.get("tp_default") or 15)
    head = f'<h3 class=ap-sub><span>Cilj izlaza za nove kopije</span><span>sada +{cur} %</span></h3>'
    if not owner:
        return f'<div id=cilj>{head}</div>'
    btns = "".join(f'<form method=post action=/pravi-trade/tp style="margin:0"><input type=hidden name=tp value={v}>'
                   f'<button{" class=ap-go" if v == cur else ""}>+{v} %</button></form>' for v in TP_CHOICES)
    return (f'<div id=cilj>{head}<div class=ap-btns style="margin:0 0 10px">{btns}</div><p class=mut>Vrijedi za svako novo '
            'praćenje i kupnju s izlazom "moj TP/SL" bez upisanog TP-a; postojeće pozicije zadržavaju svoj (mijenja se '
            'na samoj poziciji pod „Otvorene pozicije”). Praćenja s izlazom "zadano" (Smart sell) imaju svoj stop.</p></div>')


def _sl0(cfg):
    """The Autopilot's default stop as a level ("-60%"): the owner's choice under "Pravila"."""
    return settings.sl_text((cfg or {}).get("sl_default") or settings.SL_DEFAULT)


def _sl_card(cfg, owner):
    """10.11. (Jure: "default stop loss treba biti na minus 60 %, a to moram negdje na stranici Autopilota kao
    administrator moći promijeniti"): the stop of every new entry with "moj TP/SL" and no stop typed in (copies,
    the auto pick, crews, manual buys). Open positions keep theirs (changed on the position itself)."""
    cur = int((cfg or {}).get("sl_default") or settings.SL_DEFAULT)
    head = f'<h3 class=ap-sub><span>Zadani stop</span><span>sada −{cur} %</span></h3>'
    if not owner:
        return f'<div id=stop>{head}</div>'
    btns = "".join(f'<form method=post action=/pravi-trade/sl style="margin:0"><input type=hidden name=sl value={v}>'
                   f'<button{" class=ap-go" if v == cur else ""}>−{v} %</button></form>' for v in settings.SL_CHOICES)
    return (f'<div id=stop>{head}<div class=ap-btns style="margin:0 0 10px">{btns}</div><p class=mut>Pozicija se prodaje '
            'kad padne toliko ispod ulaza. Vrijedi za svaki novi ulaz s izlazom "moj TP/SL" bez upisanog stopa: kopije, '
            'automatski odabir, ekipe i ručnu kupnju. Otvorene pozicije zadržavaju svoj stop (mijenja se na poziciji).</p></div>')


def _rules(tcon, cfg, owner):
    """10.11. (maketa: "Pravila · ulog 0,1 SOL · cilj +15 % · najviše 1 dnevno"): one row under "Kako trguje" for
    the exit target and the limits; its line also says today's spend against the daily limit (it was a line in the
    header before)."""
    try:
        spent = _today(tcon, cfg, result=False)["spent"]
    except Exception:  # noqa: BLE001
        spent = None
    meta = (f'ulog {_g(cfg["size_sol"])} SOL · cilj +{int(cfg.get("tp_default") or 15)} % · '
            f'stop −{int(cfg.get("sl_default") or settings.SL_DEFAULT)} % · '
            + (f'danas {redak.num(spent, 2)} od {_g(cfg["max_sol_per_day"])} SOL' if spent is not None
               else f'najviše {_g(cfg["max_sol_per_day"])} SOL dnevno'))
    return _sec("Pravila", meta, _tp_card(cfg, owner) + _sl_card(cfg, owner) + _trigger_card(tcon, owner)
                + _limits(cfg, owner), sid="pravila")


def _trigger_card(tcon, owner):
    """10.11. (Jure: "da, v1"): Jupiter Trigger, step 1. A button asks run_trade.py to request one TP order from
    Jupiter for an open real position WITHOUT signing or sending it; the answer is shown here. Step 2 (orders for real)
    comes after a probe that passed."""
    import datetime as _dt
    import zoneinfo
    raw = settings.raw(tcon)
    pr = raw.get("trigger_probe") or {}
    asked = (raw.get("trigger_probe_req") or 0) > (pr.get("ts") or 0)
    head = '<h3 class=ap-sub><span>TP na lancu (Jupiter Trigger)</span><span>korak 1: proba</span></h3>'
    if pr:
        when = _dt.datetime.fromtimestamp(pr["ts"], zoneinfo.ZoneInfo("Europe/Zagreb")).strftime("%H:%M:%S")
        if pr.get("ok"):
            res = (f'{dot("good", "proba prošla")} · {when} · Jupiter je vratio nalog za {esc(pr.get("symbol") or "")}: '
                   f'prodaja za {esc(str(pr.get("taking_sol")))} SOL na TP-u')
        else:
            why = pr.get("why") or json.dumps(pr.get("answer") or {}, ensure_ascii=False)[:200]
            res = f'{dot("warn", "proba nije prošla")} · {when} · {esc(why)}'
    else:
        res = "Proba još nije pokrenuta."
    btn = ""
    if owner:
        btn = ('<p class=mut>Čekam trade proces (do nekoliko sekundi)…</p>' if asked else
               '<form method=post action=/pravi-trade/triggerprobe style="margin:0"><button>Provjeri Jupiter Trigger '
               '(bez novca)</button></form>')
    return (f'<div id=trigger>{head}<p>{res}</p>{btn}<p class=mut>Proba traži od Jupitera nalog za TP otvorene prave '
            'pozicije, ali ga ne potpisuje i ne šalje: novac se ne miče. Kad proba prođe, uključujemo prave naloge, prvi '
            'mali dok gledaš.</p></div>')


def _review_section(tcon, owner):
    """10.11. (Jure: "isključi influencere koje sam ja stavio ako nema smisla da ih se prati" -> "Isključi ih sam"):
    what league/followreview paused and why, with "Vrati" for the owner; the last hourly pass in the header."""
    import datetime as _dt
    import zoneinfo
    raw = settings.raw(tcon)
    last = raw.get("review_last") or {}
    log = [x for x in (raw.get("review_log") or []) if not x.get("back")]
    tz = zoneinfo.ZoneInfo("Europe/Zagreb")
    when = (_dt.datetime.fromtimestamp(last["ts"], tz).strftime("%d.%m. %H:%M") if last.get("ts") else None)
    meta = (f"isključeno {len(log)} · zadnji pregled {when}, pregledano {last.get('judged', 0)}" if when
            else "prvi pregled u roku od sat vremena")
    rows = []
    for x in log:
        t = _dt.datetime.fromtimestamp(x["ts"], tz).strftime("%d.%m. %H:%M")
        btn = (f'<form method=post action=/pravi-trade/reviewback style="margin:0"><input type=hidden name=id '
               f'value={int(x["fid"])}><button>Vrati</button></form>' if owner else "")
        rows.append(_item(x.get("label") or x["target"], f'isključen {t}', f'<p>{esc(x["why"])}.</p>{btn}',
                          value=str(x.get("n") or ""), sub="poziva", iid=f"rv-{int(x['fid'])}", value_tone="mut"))
    intro = ('<p class=mut>Svaki sat alat pregleda influencere i ekipe koje si ti dodao. Isključi onoga kod kojeg se na '
             f'najmanje {10} izmjerenih poziva njegov izlaz ne isplati nakon troška, nijedan drugi TP/SL par ga ne spašava '
             'i nije u plusu u demu. S premalo podataka nitko se ne isključuje. Otvorene pozicije zadržavaju svoj izlaz. '
             '„Vrati” ga ponovno uključuje i pregled ga više ne dira.</p>')
    body = intro + ("".join(rows) if rows else '<p class=mut>Trenutno nitko nije isključen.</p>')
    return _sec("Pregled influencera", meta, body, sid="pregled-inf")


FLAG_WORDS = {"off": "isključeno", "shadow": "sjena (samo bilježi)", "paper": "paper račun", "live": "uživo"}
FLAG_TONE = {"off": "mut", "shadow": "warn", "paper": "warn", "live": "good"}


def _slip_item(tcon, n=20):
    """10.11. (plan 1.5): how far the real exits were from the demo's (trade/executor.exit_reconcile): the average
    and the worst of the last n closed positions, and one row each. Negative = the real sale got less."""
    try:
        rows = tcon.execute("SELECT symbol, token, closed_ts, demo_exit_px, real_exit_px, exit_slip_pct FROM positions "
                            "WHERE status='closed' AND exit_slip_pct IS NOT NULL ORDER BY closed_ts DESC LIMIT ?",
                            (n,)).fetchall()
    except sqlite3.Error:
        rows = []
    if not rows:
        return _item("Demo naspram pravog izlaza", "još nema zatvorene pozicije s usporedbom (puni se od 10.11.)",
                     '<p class=mut>Za svaku zatvorenu pravu poziciju bilježi se cijena izlaza u demu i stvarna cijena '
                     'prodaje; razlika pokazuje koliko demo rezultat precjenjuje pravi.</p>', iid="fl-slip")
    sl = [r[5] for r in rows]
    avg, worst = sum(sl) / len(sl), min(sl)
    cells = "".join(f'<tr><td>{esc(r[0] or short(r[1]))}</td><td class=n>{redak.ago(r[2])}</td>'
                    f'<td class="n {"pos" if r[5] >= 0 else "neg"}">{redak.pct(r[5], 1)}</td></tr>' for r in rows[:10])
    inner = (f'<table class=t><tr><th>token</th><th class=n>zatvoreno</th><th class=n>pravi naspram dema</th></tr>{cells}'
             '</table><p class=mut>Minus znači da je prava prodaja dobila manje od izlazne cijene u demu (slippage, '
             'kašnjenje swapa, naknade). Prosjek se oduzima od demo rezultata kad se procjenjuje pravi novac.</p>')
    return _item("Demo naspram pravog izlaza", f"zadnjih {len(rows)}, najgori {redak.pct(worst, 1)}", inner,
                 value=redak.pct(avg, 1), value_tone=redak.tone(avg), iid="fl-slip")


def _flags_section(tcon, con, owner):
    """10.11. (Jure, "Specifikacija za Claudea", Phase 0): every rule of the profitability plan behind its own flag.
    The owner moves a flag off -> sjena -> paper -> uživo; uživo only with a passed backtest and 7 days of paper in
    the plus (trade/settings.live_refusal says why not). Others see the modes only."""
    import datetime as _dt
    import zoneinfo
    from league import flags as lflags
    st = settings.flag_state(tcon)
    raw_ = settings.raw(tcon)
    now = int(time.time())
    week = lflags.shadow_summary(con, now - 7 * 86400)
    on = [n for n, v in st.items() if v["mode"] != "off"]
    paper_since = min((v["since"] for v in st.values() if v["mode"] == "paper" and v["since"]), default=None)
    pr = lflags.paper_result(con, paper_since) if paper_since else None
    meta = (f"{len(on)} od {len(st)} uključeno" if on else "sve isključeno: bot radi kao prije")
    if pr:
        meta += f" · paper: {pr['n']} zatvorenih, {pr['pnl']:+.2f} $"
    tz = zoneinfo.ZoneInfo("Europe/Zagreb")
    rows = []
    for name, (item, words) in settings.FLAGS.items():
        v = st[name]
        m = v["mode"]
        since = (_dt.datetime.fromtimestamp(v["since"], tz).strftime("%d.%m. %H:%M") if v["since"] else "")
        bt = raw_.get(f"backtest:{name}") or {}
        bits = [f'<p>{esc(words)}.</p>',
                f'<p class=mut>Stanje: {dot(FLAG_TONE[m], FLAG_WORDS[m])}'
                + (f" od {esc(since)}" if since and m != "off" else "") + "</p>"]
        if name in settings.DATA_FLAGS:
            bits.append('<p class=mut>Podatkovna zastavica: bilo koji mod osim „isključeno” uključuje skupljanje '
                        'ili upis; na trgovanje ne utječe.</p>')
        else:
            sh = week.get(name)
            bits.append(f'<p class=mut>Sjena, zadnjih 7 dana: '
                        + (f'{sh["n"]} odluka bi bilo drugačije' if sh else "nijedna odluka nije drugačija") + "</p>")
            if isinstance(bt, dict) and bt:
                bits.append(f'<p class=mut>Backtest: {dot("good" if bt.get("pass") else "bad", "prošao" if bt.get("pass") else "nije prošao")}'
                            f' · n {esc(str(bt.get("n", "?")))} · donja granica EV-a {esc(str(bt.get("ev_lo", "?")))} %</p>')
            else:
                bits.append('<p class=mut>Backtest: još nije pokrenut (uživo nije moguće bez njega).</p>')
        if owner:
            opts = "".join(f'<option value={mm}{" selected" if mm == m else ""}>{FLAG_WORDS[mm]}</option>'
                           for mm in settings.FLAG_MODES)
            bits.append(f'<form method=post action=/pravi-trade/flag class=ap-btns style="margin:0 0 10px">'
                        f'<input type=hidden name=name value={esc(name)}><select name=mode>{opts}</select>'
                        f'<button>Spremi</button></form>')
        rows.append(_item(f"{item} {name}", words, "".join(bits), value=FLAG_WORDS[m].split(" ")[0],
                          iid=f"fl-{name}", value_tone=FLAG_TONE[m]))
    rows.insert(0, _slip_item(tcon))
    intro = ('<p class=mut>Svako novo pravilo iz plana ima svoju zastavicu. Isključeno: bot radi kao prije. Sjena: '
             'novo pravilo samo zapisuje što bi napravilo drugačije. Paper: pravilo radi na zasebnom demo računu '
             f'„{esc(settings.PAPER_USER)}”, koji prati iste influencere i novčanike kao Autopilot; taj račun nikad ne '
             f'kupuje pravim novcem. Uživo: tek nakon prolaza backtesta i najmanje {settings.PAPER_DAYS} dana u paper '
             'modu s paper računom u plusu; stranica inače odbije.</p>')
    return _sec("Zastavice plana", meta, intro + "".join(rows), sid="zastavice")


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
_BG = {"thread": None, "ts": 0.0, "runs": 0, "cold": set()}
# 10.11. (Jure: "sekundni poslovi ne smiju čitati bazu svake sekunde, samo ono što ima smisla"): the refresher used to
# rebuild "Zovu sada" and "Što kupiti sada" every second for ever once anybody had opened the page. Both lists are
# closed sections now, so it works only for what a browser asked for in the last BG_WANT_S seconds: "zovu" and
# "ideje" (the two open sections) and "pop" (an open pop-up needs the last hour of calls). Nobody looking = one lock
# and a dictionary scan a second. A list it stopped renewing is "cold": the next request for it gets "učitavam…"
# instead of minutes-old rows, and the fresh list a second later.
_FRAG_WANT = {"zovu": 0.0, "ideje": 0.0, "pop": 0.0}
LOADING = '<p class=mut>učitavam…</p>'
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
            # 10.11. (maketa): the shared row; name, where the reason came from and the reason, the market cap
            # as the one number and the price moves under it; a tap opens the live pop-up as before
            out.append(_prow(r["token"], name=r.get("symbol") or m.get("symbol") or r["token"][:6],
                             reason=" · ".join(x for x in (r.get("src") or "", why) if x),
                             value=redak.usd(m.get("mcap")), sub=f"5 min {ch5} · 1 h {ch1}"))
        html = "".join(out)
    with _LOCK:   # the same HTML for both viewer kinds (one computation in the background thread serves both)
        _IDEAS_CACHE[bool(owner)] = (now, html, data_ts)   # (compute time for the TTL, HTML, data time for the stamp)
        _IDEAS_CACHE[not bool(owner)] = (now, html, data_ts)
    return html


def _stamp(html, ts):
    """The data time of a cached fragment (never the render time), under the rows; nothing when there are no rows
    (the page then shows the section's own "nothing right now" sentence)."""
    if not html or not ts:
        return html or ""
    return html + (f'<p class=mut style="margin:8px 0 0">podaci od '
                   f'{time.strftime("%H:%M:%S", time.gmtime(ts))} UTC</p>')


def _want(name, now=None):
    """A browser asked for this live list (or a pop-up for the calls of the last hour): the refresher keeps it fresh
    for the next BG_WANT_S seconds. Returns True when the refresher had let it go cold."""
    with _LOCK:
        _FRAG_WANT[name] = now or time.time()
        return name in _BG["cold"]


def _wanted(now):
    with _LOCK:
        return {k for k, ts in _FRAG_WANT.items() if now - ts <= BG_WANT_S}


def ideas_fragment(user):
    tcon = _tcon()
    try:
        if not settings.can_view(tcon, user):
            return None
        cfg, owner = _cfg(tcon), settings.is_owner(user)
    finally:
        tcon.close()
    if _bg_start():   # the background thread fills the cache; this request thread only reads it
        cold = _want("ideje")
        with _LOCK:
            c = _IDEAS_CACHE.get(bool(owner)) or (0.0, "")
        if not c[0] or cold:   # 9.11. (audit): no pass yet (zivo's thread still fetching): say so instead of an empty box
            return LOADING     # 10.11.: the same while the refresher wakes up after nobody looked for a while
        return _stamp(c[1], c[2] if len(c) > 2 else c[0])
    return ideas_inner(cfg, owner)


def _live_box(box_id, url, empty):
    """A box the page fills only while its section is open: nothing is fetched (and nothing computed on the server)
    until somebody opens it, then it is re-fetched every LOG_EVERY_S seconds."""
    return (f'<div id={box_id} data-src={url} data-every={LOG_EVERY_S} data-lazy data-empty="{esc(empty)}">{LOADING}</div>')


def _ideas_section(cfg, owner):
    """10.11. (Jure: "nije mi jasno Što kupiti sada, tu su tokeni na koje ne mogu kliknuti: makni na dno"): under
    "Još", closed, with a title and one line that say what the list is; every row opens the token pop-up. The
    sentence that explains the checks is under the list (pravilo 6)."""
    return _sec("Što alat sada predlaže za kupnju", "tokeni koji upravo prolaze sve provjere",
                _live_box("ap-ideje", "/pravi-trade/ideje", "Trenutno nijedan token ne prolazi sve provjere. Popis se puni sam čim se neki pojavi.")
                + '<p class=ms-hint>Tokeni koji u ovom trenutku prolaze sve provjere alata (rug check, tier, MC 30k+, 10+ '
                  'transakcija i 1k+ $ volumena u zadnjem satu, 20k+ $ likvidnosti, ne padaju) i imaju svjež razlog za ulaz: '
                  'novi poziv, kupnju pametnog novčanika ili pokret cijene. Dodirni token za provjeru uživo i kupnju.</p>',
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
                # 10.11. (audit sekundni S10): plain SQL. copy.follows() does dict(row) and this read-only connection
                # has no Row factory, so the TypeError was swallowed and the followed wallets never counted as "zovu"
                out |= {r[0] for r in con.execute("SELECT target FROM follows WHERE user=? AND active=1 AND kind='wallet'",
                                                  (settings.LEAGUE_USER,))}
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


# 10.11. (Jure, pop-up of a token with 0 tx in 5 min and 1 in the hour: "nema smisla da token bude tu; možda čak u
# 5 minuta više od 5 ili 10 transakcija, da vidimo tokene koji se bude"): a token is offered on this page only while
# it trades NOW. Constants, not a guess per list: "Zovu sada", "Preporučeni tokeni" and the pop-up verdict share them.
AWAKE_TX_M5 = int(os.environ.get("AP_AWAKE_TX_M5", "5"))
SOCIAL_MIN = 5   # this many different accounts posting the address inside the hour is said as a reason (Jure 10.11.)


def asleep(m):
    """None while the token trades right now (live DexScreener state `m`), else the reason it is not offered."""
    tx5 = int((m or {}).get("txns_m5") or 0)
    if tx5 < AWAKE_TX_M5:
        word = "transakcije" if tx5 % 10 in (2, 3, 4) and tx5 % 100 not in (12, 13, 14) else "transakcija"
        return f"samo {tx5} {word} u zadnjih 5 min (treba {AWAKE_TX_M5}+)"
    if ((m or {}).get("vol_m5") or 0) <= 0:
        return "bez prometa u zadnjih 5 min"
    return None


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
            _FRAG_WANT["pop"] = time.time()
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
        if asleep(m):   # 10.11. (Jure): a call nobody trades on is not a line here; it appears when the token wakes up
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


def _bg_pass(now=None, want=None):
    """One refresher pass: the token sets asked for in the last BG_WANT_S s (pop-ups, crews) renewed when older
    than LIVE_TTL_S, then the "Zovu sada" and "Što kupiti sada" HTML. Every step in its own try: a failing source
    leaves the others' caches alone (stale data with its time beats no data). want: the lists a browser asked for
    lately (_wanted); None = all of them (a direct call). A list nobody wants is not rebuilt and is marked cold."""
    now = now or time.time()
    with _LOCK:
        # 9.11. (review): a set whose fetch returned None never enters _LIVE_CACHE, so the eviction there never saw
        # its WANT entry; forget requests nobody repeated in 10 x BG_WANT_S
        for k in [k for k, ts in _LIVE_WANT.items() if now - ts > 10 * BG_WANT_S]:
            _LIVE_WANT.pop(k, None)
            _LIVE_FAIL.pop(k, None)
        live_want = [k for k, ts in _LIVE_WANT.items() if now - ts <= BG_WANT_S and now - (_LIVE_CACHE.get(k) or (0,))[0] >= LIVE_TTL_S]
    for key in live_want:
        try:
            _live_cached(key, now, wait=True)
        except Exception as e:  # noqa: BLE001
            print(f"autopilot uživo: DexScreener za {len(key)} tokena nije uspio: {type(e).__name__}: {e}", flush=True)
    zovu = want is None or "zovu" in want
    ideje = want is None or "ideje" in want
    with _LOCK:   # "Što kupiti sada" goes through zivo.rows (its own DexScreener request): at most once per LIVE_TTL_S
        ideas_due = ideje and now - (_IDEAS_CACHE.get(False) or (0.0,))[0] >= LIVE_TTL_S
        events_due = not zovu and "pop" in (want or ()) and time.time() - _EVENTS["ts"] >= EVENTS_TTL_S
    steps = []
    if zovu:
        steps.append(("zovu", lambda: callers_inner(None, False, now, force=True)))
    elif events_due:   # an open pop-up alone: only the calls of the last hour, which callers_inner would have read
        steps.append((None, lambda: _events_hour(now, fresh=True)))
    if ideas_due:
        steps.append(("ideje", lambda: ideas_inner(None, False, now, force=True)))
    done = set()
    for name, fn in steps:
        try:
            fn()
            done.add(name)
        except Exception as e:  # noqa: BLE001
            print(f"autopilot uživo: osvježavanje nije uspjelo: {type(e).__name__}: {e}", flush=True)
    with _LOCK:
        _BG["cold"] = (_BG["cold"] | {k for k, on in (("zovu", zovu), ("ideje", ideje)) if not on}) - done
        _BG["ts"], _BG["runs"] = now, _BG["runs"] + 1


def _bg_loop():
    while True:
        t0 = time.time()
        try:
            _bg_pass(t0, _wanted(t0))
        except Exception as e:  # noqa: BLE001 - the refresher must outlive anything a pass throws
            print(f"autopilot uživo: prolaz nije uspio: {type(e).__name__}: {e}", flush=True)
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
    rows = [r for r in rows if not all(_is_followed(c[0], followed) for c in r[1])]
    if not rows:
        html = ""   # the section hides itself while there is nothing to show
    else:
        html = "".join(_crew_row(c, now, followed) for c in crew_rows(rows, now))
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
        name = (lead[3:] if lead.startswith("tg:") else ("wallet " + lead[2:8] if lead.startswith("w:") else "@" + lead))
        if len(members) > 1:
            name = f"ekipa {name} +{len(members) - 1}"
        g["name"], g["key"] = name, ",".join(h for h in members if not h.startswith("w:"))
        g["tokens"].sort(key=lambda t: -t["last"])
        out.append(g)
    out.sort(key=lambda g: -g["last"])
    return out


def _crew_row(g, now, followed=()):
    """One line per crew, led by its newest TOKEN. 10.11. (Jure: "tu su tokeni na koje ne mogu kliknuti"): the row
    used to open the crew and the token was a word inside it; now the row opens the token pop-up (the same one as
    everywhere on this page) and the crew's underlined name opens the crew with all its tokens."""
    t = g["tokens"][0]
    m = t["live"]
    ch5 = f"{m['ch_m5']:+.0f} %" if m.get("ch_m5") is not None else "?"
    n = len(g["tokens"])
    # 10.11. (Jure: "ili ga zazeleni da vidim da sam ga već zapratio"): a row stays while somebody in it is not
    # followed yet; the ones the bot already follows are named after a green dot (pravilo 5: a dot, not a tick)
    mine = [h for h in g["members"] if _is_followed(h, followed)]
    tag = None
    if mine:
        names = ", ".join(h[3:] if h.startswith("tg:") else ("wallet " + h[2:8] if h.startswith("w:") else "@" + h) for h in mine)
        tag = raw(f'<span class=ap-mine title="bot ih već prati">{dot("good")}već pratiš {esc(names)}</span>')
    # 9.11. (audit P73): a crew made only of wallets has no X/Telegram handle to follow as a crew (their buys are
    # already copied by the wallet follows), so its name is plain text and only the token opens
    who = esc(g["name"])
    if g["key"]:
        who = f'<u data-pop="/pravi-trade/ekipa?h={quote(g["key"])}" title="Otvori ekipu i sve njezine tokene">{who}</u>'
    verb = "kupio" if g["leader"].startswith("w:") else "zove"
    more = f' · {n} {"tokena" if n > 1 else "token"} u 60 min' if n > 1 else ""
    # 10.11. (maketa): the shared row; the market cap as the one number, how awake the token is under it (Jure 10.11.)
    return _prow(t["token"], name=t["symbol"] or t["token"][:6],
                 reason=cat(raw(f'{verb} {who} · {esc(redak.ago(t["last"]))}{esc(more)}'), tag, sep=" · "),
                 value=redak.usd(m.get("mcap")), sub=f'5 min {ch5} · {int(m.get("txns_m5") or 0)} tx')


def _usd_short(x):
    x = float(x or 0)
    return f"${x / 1e6:.2f}M" if x >= 1e6 else f"${x / 1e3:.1f}k" if x >= 1e3 else f"${x:.0f}"


def _market_table(m):
    """10.11. (Jure: "stavi to u tablicu kao na DexScreeneru, da bude prepoznatljiv format"): market cap and liquidity
    in boxes, then one column per window (5 min, 1 h, 6 h, 24 h) with the price change, the volume and the
    transactions as buys / sells: DexScreener's own layout, from the same response the verdict uses."""
    w = m.get("w")
    if not w:   # a live state without the windows (older cache entry, tests): what the flat fields have
        b1, t1 = m.get("buys_h1"), m.get("txns_h1")
        w = {"m5": {"ch": m.get("ch_m5"), "vol": m.get("vol_m5"), "tx": m.get("txns_m5")},
             "h1": {"ch": m.get("ch_h1"), "vol": m.get("vol_h1"), "buys": b1, "sells": (t1 - b1) if t1 is not None and b1 is not None else None},
             "h24": {"ch": m.get("ch_h24"), "vol": m.get("vol_h24"), "tx": m.get("txns_h24")}}
    cols = [(k, lab) for k, lab in (("m5", "5 min"), ("h1", "1 h"), ("h6", "6 h"), ("h24", "24 h")) if k in w]

    def pct(d):
        x = d.get("ch")
        if x is None:
            return "–"
        x = float(x)
        return f'<span class="{"pos" if x > 0 else "neg" if x < 0 else ""}">{x:+.1f} %</span>'

    def txn(d):
        if d.get("buys") is None and d.get("sells") is None:
            return "–" if d.get("tx") is None else str(int(d["tx"]))
        return str(int((d.get("buys") or 0) + (d.get("sells") or 0)))

    def split(d):
        if d.get("buys") is None and d.get("sells") is None:
            return "–"
        return f'<span class=pos>{int(d.get("buys") or 0)}</span> / <span class=neg>{int(d.get("sells") or 0)}</span>'

    def row(name, fn):
        return f"<tr><td>{name}</td>" + "".join(f"<td>{fn(w.get(k) or {})}</td>" for k, _ in cols) + "</tr>"

    liq_pct = f'<small>{m["liq"] / m["mcap"]:.0%} MC-a</small>' if m.get("mcap") and m.get("liq") else ""
    turn = f'{(m.get("vol_h1") or 0) / m["liq"]:.1f}×' if m.get("liq") else "–"
    return ('<div class=ap-box>'
            f'<div><small>MARKET CAP</small><b>{_usd_short(m.get("mcap"))}</b></div>'
            f'<div><small>LIKVIDNOST</small><b>{_usd_short(m.get("liq"))}</b>{liq_pct}</div>'
            f'<div><small>PROMET 1 h / LIKV.</small><b>{turn}</b></div></div>'
            '<table class=ap-mk><tr><th></th>' + "".join(f"<th>{lab}</th>" for _, lab in cols) + "</tr>"
            + row("Cijena", pct) + row("Volumen", lambda d: "–" if d.get("vol") is None else _usd_short(d["vol"]))
            + row("Transakcije", txn) + row("Kupnje / prodaje", split) + "</table>")


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
    # 10.11.: "Zovu sada" and "Što kupiti sada" are closed now, so their 1-s polls no longer start the refresher on
    # every page view; an open pop-up starts it itself, so its DexScreener state is renewed off this request thread
    _bg_start()
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
    n_social = len({h for h, _ in callers})   # 10.11. (Jure: "5 ili 10 računa objavilo adresu = jak signal")
    smart = zivo._smart_buys(now, {mint}).get(mint, 0)
    top = {}
    try:
        from topcheck import store as tstore
        top = tstore.read_all(max_age_h=1).get(mint) or {}
    except Exception:  # noqa: BLE001
        pass
    tier = zivo._tier(mint)   # 10.11. (audit sekundni S2): one row by key, not the whole token_tier every second
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
    if n_social >= SOCIAL_MIN:   # described, not a verdict by itself: a campaign posts the same address too
        za_static.append(f"društveni signal: {n_social} različitih računa objavilo je adresu u zadnjih 60 min")
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
    quiet = asleep(m)   # 10.11. (Jure): the lists leave such a token out; here it says why
    if quiet and not why_not:
        protiv.append(quiet)
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
    verdict = ("NE KUPUJ" if not ok else
               f"U REDU ZA ULAZ · {rc_missing_txt}, tko drži supply nepoznato" if rc_missing else
               "U REDU ZA ULAZ · holderi nepoznati" if holders_unknown else "U REDU ZA ULAZ")
    b = [f'<h3>{tlink(mint, sym)}</h3>',
         f'<div class="ap-verdict {"ok" if ok else "ne"}">{esc(verdict)}</div>',
         _market_table(m)]
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
    _bg_start()   # as in token_popup: the crew's token set is kept fresh by the refresher, not by this request
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
        cold = _want("zovu")
        with _LOCK:
            ts, html = _CALLERS_CACHE["ts"], _CALLERS_CACHE["html"]
        if not ts or cold:   # 10.11.: no pass yet, or the refresher is waking up: never minutes-old rows as if live
            return LOADING
        return _stamp(html, ts)
    return callers_inner(cfg, owner)


def _callers_section(cfg, owner):
    """10.11. (Jure: "nije mi jasno Zovu sada"): under "Još", closed, named for what it is, with one line; the list
    is fetched (and built on the server) only while the section is open; the explanation is under the list."""
    return _sec("Tko sada zove koji token", "pozivi i kupnje praćenih, zadnjih 60 min",
                _live_box("ap-zovu", "/pravi-trade/zovu", "U zadnjih 60 minuta nema poziva koji sada prolazi provjere.")
                + '<p class=ms-hint>Tokeni koje su u zadnjih 60 minuta objavili influenceri i Telegram kanali ili kupili walleti '
                  'koje pratiš i dokazani walleti, a upravo se trguju. Koga bot već prati, ne ponavlja se ovdje. Dodirni token za '
                  'provjeru uživo i kupnju, podcrtano ime za cijelu ekipu. Tko od njih stvarno nosi +5/10/15/20/30 % nakon '
                  'poziva: <a href="/ekipe">Ekipe i minutna provjera</a>.</p>', sid="zovu")


def _token_section(cfg, owner):
    from ui import autopilot
    recs = autopilot.token_recs()
    items = []
    from kol import converge
    recs = {k: [r for r in recs.get(k) or [] if not converge.not_a_memecoin(r["mint"], r.get("symbol"))]   # 9.11.: never a
            for k in ("dugo", "moon")}                                                                       # major or xStock
    # 10.11. (Jure: a recommended token with 0 tx in 5 min and 1 in the hour): the list was never checked live
    # ("dodir = provjera uživo"); now every token on it is, and one that does not trade right now is left out.
    # No live answer = nothing is recommended (the same rule as "Zovu sada").
    mints = sorted({r["mint"] for rows in recs.values() for r in rows})
    lv = (_live_cached(mints, time.time()) or {}) if mints else {}
    recs = {k: [r for r in rows if lv.get(r["mint"]) and not asleep(lv[r["mint"]])] for k, rows in recs.items()}
    for kind, lab, ex in (("dugo", "dugoročno", "manual"), ("moon", "moonshot", "smart")):
        for r in recs.get(kind) or []:
            m = lv[r["mint"]]
            # 10.11. (maketa): the shared row; the market cap as the one number, how awake it is under it
            items.append(_prow(r["mint"], name=r["symbol"] or r["mint"][:6],
                               reason=" · ".join(x for x in (lab, (r["why"] or "")[:90]) if x),
                               value=redak.usd(m["mcap"]) if m.get("mcap") else None, sub=f'5 min {m["txns_m5"]} tx'))
    nd, nm = len(recs["dugo"]), len(recs["moon"])
    meta = f"{nd} dugoročna · {nm} moonshot" if items else "trenutno nema"
    if not items:   # 9.11. (Jure): shown only with concrete suggestions; "Kupi ručno" takes any token
        return ""
    inner = ("".join(items)
             + '<p class=ms-hint>Dugoročni su stariji tokeni koji su preživjeli; moonshot je mali, svjež token s jakim '
               'signalom i prošlim rug checkom, koji može narasti puno, ali i pasti na nulu. Nijedna preporuka nije jamstvo '
               'zarade.</p>')
    return _sec("Preporučeni tokeni", meta, inner, sid="tokeni")


def _safe(name, fn, *args, fallback=""):
    """One part of the page: an error in it is logged and the part left out (or replaced by `fallback`), so a broken
    statistic never costs the owner the switch, the positions or the sell buttons."""
    try:
        return fn(*args)
    except Exception as e:  # noqa: BLE001
        print(f"autopilot: dio stranice '{name}' nije složen: {type(e).__name__}: {e}", flush=True)
        return fallback


def _recs_section():
    """10.11. (Jure: "čista, minimalistička"): the tool's picks of influencers, wallets and tokens in ONE closed
    section at the bottom. Nothing is computed for it until it is opened (the token picks are checked live on
    DexScreener, which a page view should not wait for); then /pravi-trade/preporuke fills it once."""
    return _sec("Preporuke alata", "influenceri, walleti i tokeni za praćenje",
                f'<div id=ap-recs data-src=/pravi-trade/preporuke data-every=0 data-lazy '
                f'data-empty="Alat trenutno nema prijedloga koji prolaze provjere.">{LOADING}</div>'
                '<p class=ms-hint>Koga i što alat iz izmjerenih rezultata predlaže za praćenje i kupnju. Dodirni redak za '
                'detalje.</p>', sid="preporuke")


def recs_fragment(user):
    """GET /pravi-trade/preporuke: the three recommendation lists (closed sub-sections), same access as the page."""
    tcon = _tcon()
    try:
        if not settings.can_view(tcon, user):
            return None
        cfg, owner = _cfg(tcon), settings.is_owner(user)
    finally:
        tcon.close()
    con = store.connect()
    try:
        copy.ensure(con)
        return (_safe("influenceri", _kol_section, con, owner) + _safe("walleti", _wallet_section, con, owner)
                + _safe("tokeni", _token_section, cfg, owner))
    finally:
        con.close()


# ---------- positions -------------------------------------------------------------------------------------------

def _sell_btns(pid, pending):
    """pid: one positions id or several joined by commas (the lots of one token are sold together)."""
    if pending is not None:
        return f'<p class=mut>Prodaja {redak.pct(pending, sign=False, frac=True)} je u tijeku.</p>'
    # 10.11. (Jure: "pogledaj kako mjenjačnice rade na mobitelu, istaknuti botuni"): one full-width action bar, the
    # whole sale filled red like an exchange's "Close"
    return ('<div class="ap-btns ap-sellbar">' + "".join(
        f'<form method=post action=/pravi-trade/sell onsubmit="return confirm(\'Prodati {lab} ove pozicije odmah?\')">'
        f'<input type=hidden name=id value={pid}><input type=hidden name=frac value={fr}><button{" class=ap-sellall" if fr == "1" else ""}'
        f' aria-label="Prodaj {lab}">{"Prodaj sve" if fr == "1" else lab}</button></form>'
        for fr, lab in (("0.2", "20 %"), ("0.5", "50 %"), ("1", "sve"))) + '</div>')


def _tok(tok, sym=None):
    """A token's name on this page: its symbol in the accent colour. The row it stands in opens the token pop-up
    (10.11., Jure: every token must be something one can tap), which carries the outside links and the full page."""
    return f'<b class=ap-tok translate=no>{esc(sym or short(tok or ""))}</b>'


def _pop(tok):
    return f' data-pop="/pravi-trade/token?m={quote(tok)}"' if tok else ""


def _mode_tag(mode):
    return f'<span class=ap-tag>{"pravi novac" if mode == "live" else "probno"}</span>'


def _who(reason):
    """Whom a position copies, short, from its source (run_trade passes league/copy's "copy KOL ansem" through):
    "@ansem", "wallet 7xKX…gAsU", "ekipa murad, tg:alpha", "ručno", "demo strategija"; None when the text is not a
    source (then it is said in full inside the row)."""
    t = " ".join(str(reason or "").split(" · pokušaj")[0].split())
    if t.startswith("copy "):
        kind, _, name = t[5:].partition(" ")
        if kind == "KOL" and name:
            return name[3:] if name.startswith("tg:") else "@" + name.lstrip("@")
        if kind == "wallet" and name:
            return "wallet " + (short(name) if len(name) > 20 else name)
        return t[5:] or None
    if t.startswith("kopija ") and len(t) < 60:   # the same said in Croatian (hand-written or older rows)
        return t[7:]
    if t.startswith("ručno"):
        return "ručno"
    if t.startswith("paper"):
        return "demo strategija"
    return None


EXIT_TP_QUICK = (15, 30, 50, 100)   # 10.11. (Jure: "za neke tokene bi stavio take profit 30 %, a ne samo 15 %")


def _demo_sides(lids):
    """{league trade id: (entry MC, auto rule dict or None, open)} of the demo trades behind the listed open real
    positions (run_trade mirrors a demo trade on LEAGUE_USER; the demo's entry MC is where the bot bought, its auto
    rule is the exit the real position follows). One read by primary key, read-only; {} when league.db is missing."""
    lids = [int(x) for x in lids if x]
    if not lids:
        return {}
    lg = _league_ro()
    if lg is None:
        return {}
    try:
        rows = lg.execute(f"SELECT id, entry_mcap, auto, status FROM trades WHERE id IN ({','.join('?' * len(lids))}) "
                          "AND user=?", (*lids, settings.LEAGUE_USER)).fetchall()
    except sqlite3.Error:
        return {}
    finally:
        lg.close()
    out = {}
    for lid, mc, a, st in rows:
        try:
            rule = json.loads(a) if a else None
        except ValueError:
            rule = None
        out[lid] = (mc, rule, st == "open")
    return out


def _exit_words(rule):
    """'TP +15 % · SL −60 %' of a demo trade's auto rule; 'Smart sell'; '' without one."""
    if not rule:
        return ""
    if rule.get("mode") == "smart":
        return "Smart sell"
    bits = []
    if rule.get("tp"):
        bits.append(f"TP {rule['tp'].replace('%', ' %')}")
    if rule.get("sl"):
        bits.append(f"SL {rule['sl'].replace('-', '−').replace('%', ' %')}")
    return " · ".join(bits)


def _exit_form(pid, rule, cfg):
    """The owner's exit of one open position: quick TP buttons (+15/+30/+50/+100 %, the stop stays) and a TP/SL pair
    to type (percent from the entry or MC, e.g. "$200k"). POST /pravi-trade/exit."""
    rule = rule or {}
    sl_now = (rule.get("sl_in") or rule.get("sl") or "") if rule.get("mode") == "tpsl" else ""
    tp_now = (rule.get("tp_in") or rule.get("tp") or "") if rule.get("mode") == "tpsl" else ""
    keep = esc(sl_now or _sl0(cfg))
    quick = "".join(
        f'<form method=post action=/pravi-trade/exit style="margin:0"><input type=hidden name=id value={pid}>'
        f'<input type=hidden name=tp value="{v}%"><input type=hidden name=sl value="{keep}">'
        f'<button{" class=ap-go" if tp_now.lstrip("+") in (f"{v}%", f"{v}") else ""}>TP +{v} %</button></form>'
        for v in EXIT_TP_QUICK)
    return (f'<div class=ap-btns>{quick}</div>'
            f'<form method=post action=/pravi-trade/exit class=ap-exit><input type=hidden name=id value={pid}>'
            f'<label>TP <input name=tp value="{esc(tp_now)}" placeholder="npr. 30%" size=7 autocomplete=off></label> '
            f'<label>SL <input name=sl value="{esc(sl_now)}" placeholder="zadano {esc(_sl0(cfg))}" size=9 autocomplete=off></label> '
            '<button>Spremi izlaz</button></form>'
            '<p class=mut>Postotak od ulaza ili MC (npr. $200k). Prazan TP = bez cilja, samo stop; prazan SL = zadani stop. '
            'Ako je cijena već iznad TP-a ili ispod SL-a, prodaja kreće u sljedećih 20 s.</p>')


def _now_mcap(tokens):
    """({token: market cap now}, unix time of that quote) from the shared live cache (_live_cached: the background
    thread renews it every LIVE_TTL_S while it is asked for; a request thread fetches only a set nobody asked for
    yet). ({}, None) when DexScreener does not answer."""
    key = tuple(sorted(tokens))
    try:
        _bg_start()   # 10.11. (Jure: "to treba osvježavati non stop"): the renewal runs off the request thread
    except Exception:  # noqa: BLE001
        pass
    try:
        live = _live_cached(key, time.time()) or {}
    except Exception:  # noqa: BLE001 - the rows render without the move
        return {}, None
    with _LOCK:
        hit = _LIVE_CACHE.get(key)
    return {t: (live.get(t) or {}).get("mcap") for t in tokens}, (hit[0] if hit and live else None)


def _pct_html(pct, big=False):
    """+11,0 % in green, −4,2 % in red, bold (10.11., Jure: "PnL zelenim ili crvenim slovima")."""
    t = redak.tone(pct)
    cls = " ".join(x for x in (t, "ap-pnl-v" if big else "") if x)
    return f'<b class="{cls}">{esc(redak.pct(pct, 1))}</b>' if cls else f"<b>{esc(redak.pct(pct, 1))}</b>"


def _lot_group(tok, lots, demo, mc_now, pending, owner, viewer_buy, cfg, mixed, mc_ts=None, orders=None, dca_log=None,
               note=None):
    """One open position = every open lot of a token (oldest first). Closed: name, whom it copies (or "2 ulaza"), the
    entry MC(s), the move (green / red) and the stake. Open (10.11., Jure: "ništa lijepo istaknuto; boldano MC na
    kojem smo ušli, PnL zelenim/crvenim uz sat kad se točno osvježio, non stop"): one block with the move from the
    (average) entry, MC now and the clock time of that quote, the entry MC in bold; one line per lot; the exit; the
    owner's DCA orders (dokup na padu), exit form and sell buttons (every lot); the live check."""
    import datetime as _dt
    import zoneinfo
    z = zoneinfo.ZoneInfo("Europe/Zagreb")
    first = lots[0]
    pid0, sym, mode = first[0], first[2], first[4]
    ids = [r[0] for r in lots]
    pend = next((pending.get(str(i)) for i in ids if pending.get(str(i)) is not None), None)
    trial = "probno" if (mixed and mode != "live") else None
    who = _who(first[6]) if len(lots) == 1 else f"{len(lots)} ulaza"
    lines, mcs, rules = [], [], []
    for n, (pid, _t, _s, ts, _m, _st, why, sin, sback, q, ql, _c, _f, lid) in enumerate(lots, 1):
        mc, rule, demo_open = demo.get(lid, (None, None, False))
        mcs.append((mc, sin or 0))
        rules.append((lid, rule, demo_open))
        head = esc(f"{n}. ulaz {_dt.datetime.fromtimestamp(ts, z):%H:%M}") + (f" na MC <b>{esc(_usd_short(mc))}</b>" if mc else "")
        move = f" ({_pct_html((mc_now / mc - 1) * 100)})" if mc and mc_now else ""
        tail = [redak.sol(sin or 0, 3)]
        if sback:
            tail.append(f"vraćeno {redak.sol(sback, 4)}")
        if len(lots) > 1 or not _who(why):
            tail.append(_who(why) or (why or ""))
        lines.append(f"{head}{move} · {esc(' · '.join(x for x in tail if x))}")
    # the position as a whole: the average entry weighted by the SOL put in each lot, and the move from it
    wsum = sum(w for m, w in mcs if m and w)
    avg_mc = wsum / sum(w / m for m, w in mcs if m and w) if wsum else None
    pnl_all = (mc_now / avg_mc - 1) * 100 if avg_mc and mc_now else None
    clock = _dt.datetime.fromtimestamp(mc_ts, z).strftime("%H:%M:%S") if mc_ts else None
    top = '<div class=ap-pnl>'
    top += (f'<div>PnL {_pct_html(pnl_all, big=True)}</div>' if pnl_all is not None else
            '<div class=mut>PnL: čekam cijenu</div>')
    top += ('<div class=mut>' + (f"MC sada <b>{esc(_usd_short(mc_now))}</b>" if mc_now else "MC sada –")
            + (f" · osvježeno <b>{clock}</b>" if clock else "") + "</div>")
    if avg_mc:
        top += (f'<div class=mut>{"Prosječni ulaz" if len(lots) > 1 else "Ulaz"} na MC <b>{esc(_usd_short(avg_mc))}</b> · '
                f'{"pravi novac" if mode == "live" else "probno"}</div>')
    top += "</div>"
    line = top + "".join(f"<p class=mut>{x}</p>" for x in lines)
    exits = {_exit_words(r) for lid, r, _o in rules if lid}
    exit_words = (' / '.join(sorted(x or 'nije postavljen' for x in exits))
                  + (" (od prosječnog ulaza, zatvara sve ulaze)" if len(lots) > 1 else "")) if exits else ""
    lid0, rule0, open0 = next(((lid, r, o) for lid, r, o in rules if lid and o), (None, None, False))
    # 10.11. (Jure: "dodao sam DCA dokup, a nigdje se nije otvorio da je open order, da ga mogu zatvoriti"): like an
    # exchange's position card: the open orders of the position (its TP/SL and every DCA order, each with "Otkaži"),
    # then the action bar (sell), then the two panels to change them (TP / SL, DCA), closed until tapped
    mine = [o for o in (orders or []) if o.get("token") == tok]
    rows = []
    if exit_words:
        rows.append(f'<div class=ap-ord-r><span><b>TP/SL</b> · {esc(exit_words)}</span></div>')
    for o in mine:
        rows.append(f'<form method=post action=/pravi-trade/dcadel class=ap-ord-r onsubmit="return confirm(\'Otkazati ovaj DCA nalog?\')">'
                    f'<input type=hidden name=id value="{esc(str(o["id"]))}"><span><b>DCA dokup</b> {esc(redak.sol(o["sol"], 3))} '
                    f'na MC <b>{esc(_usd_short(o["mc"]))}</b></span>'
                    + ('<button class=ap-cancel>Otkaži</button>' if owner else "") + '</form>')
    orders_html = (f'<div class=ap-ord><div class=ap-ord-h>Otvoreni nalozi · {len(rows)}</div>{"".join(rows)}</div>'
                   if rows else "")
    panels = ""
    if owner and lid0 and pend is None:
        panels = (f'<details class=ap-pan id=pan-tp-{pid0}><summary>TP / SL</summary><div class=in>{_exit_form(pid0, rule0, cfg)}</div></details>'
                  f'<details class=ap-pan id=pan-dca-{pid0}><summary>DCA dokup{f" · {len(mine)}" if mine else ""}</summary>'
                  f'<div class=in>{_dca_block(tok, sym, orders or [], dca_log or [], cfg, avg_mc, mc_now)}</div></details>')
    act = _sell_btns(",".join(map(str, ids)), pend) if owner else (
        f'<p><a href="https://jup.ag/swap/SOL-{quote(tok)}" target=_blank rel=noopener>Kupi i ti ↗</a></p>' if viewer_buy else "")
    inner = (f"{line}{_grok_box(note)}{orders_html}{act}{panels}"
             f'<p><span class=ap-lnk role=button tabindex=0{_pop(tok)}>Provjeri token uživo</span></p>')
    q_all, ql_all = sum(r[9] or 0 for r in lots), sum(r[10] or 0 for r in lots)
    held = f"drži {redak.pct(ql_all / q_all, sign=False, frac=True)}" if q_all else "drži –"
    mc_words = ", ".join(_usd_short(m) for m, _w in mcs if m)
    reason = " · ".join(x for x in (who, f"ulaz MC {mc_words}" if mc_words else "", redak.ago(lots[-1][3]), trial) if x)
    stake = redak.sol(sum(r[7] or 0 for r in lots), 3)
    if pnl_all is not None:   # the move first, coloured, the stake and the quote's clock time under it
        return _item(sym or short(tok or ""), reason, inner, value=redak.pct(pnl_all, 1),
                     sub="prodaja u tijeku" if pend is not None else " · ".join(x for x in (stake, held, clock) if x),
                     iid=f"poz-{pid0}", value_tone=redak.tone(pnl_all))
    return _item(sym or short(tok or ""), reason, inner, value=stake,
                 sub="prodaja u tijeku" if pend is not None else held, iid=f"poz-{pid0}")


# ---------- DCA: dokup na padu, granice postavlja vlasnik ------------------------------------------------------------
# 10.11. (Jure: "DCA ide ručno. Postavljaju se granice ručno, ne automatski"): on an open position the owner sets a
# level (MC "$70k" or a drop from the average entry "-20%") and a SOL amount; when the live MC touches the level the
# bot buys that amount into the same position (the manual buy path: one more lot, the exit from the new average). One
# order buys once. Orders live in trade settings "dca_orders"; dca_loop (a thread in run_ui) watches them every second.
DCA_EVERY_S = 1.0
_DCA_LOCK = threading.Lock()


def _dca_orders(tcon):
    return list(settings.raw(tcon).get("dca_orders") or [])


def _dca_block(tok, sym, orders, log, cfg, avg_mc, mc_now):
    """The owner's DCA orders of one position: the active ones (with "Ukloni"), the last results, and the form."""
    mine = [o for o in orders if o.get("token") == tok]
    rows = "".join(
        f'<form method=post action=/pravi-trade/dcadel class=ap-exit><input type=hidden name=id value="{esc(str(o["id"]))}">'
        f'<span>Dokup na MC <b>{esc(_usd_short(o["mc"]))}</b> za {esc(redak.sol(o["sol"], 3))}'
        + (f' ({esc(o["txt"])} od prosjeka)' if str(o.get("txt", "")).endswith("%") else "")
        + '</span> <button>Ukloni</button></form>' for o in mine)
    done = "".join(f"<p class=mut>{esc(x['text'])}</p>" for x in log if x.get("token") == tok)[:2000]
    size = (cfg or {}).get("size_sol") or 0.1
    form = (f'<form method=post action=/pravi-trade/dca class=ap-exit><input type=hidden name=token value="{esc(tok)}">'
            '<label>Dokupi na MC <input name=lvl placeholder="$70k ili -20%" size=10 autocomplete=off></label> '
            f'<label>SOL <input name=sol value="{size:g}" inputmode=decimal size=5></label> '
            '<button>Postavi dokup</button></form>')
    hint = ('<p class=mut>Kad MC padne na tu granicu, bot dokupi taj iznos u istu poziciju (jednom po nalogu); izlaz se '
            'onda računa od novog prosjeka. Postotak je od prosječnog ulaza' + (f" ({esc(_usd_short(avg_mc))})" if avg_mc else "")
            + '.</p>')
    return f'{form}{hint}{done}'


def _dca_level(txt, avg_mc):
    """'$70k' / '70k' / '70000' -> that MC; '-20%' / '20%' -> the average entry MC minus 20 %."""
    s = (txt or "").strip().lower().replace(" ", "").replace(",", ".")
    if not s:
        raise ValueError("upiši granicu: MC (npr. $70k) ili pad od prosječnog ulaza (npr. -20%)")
    if s.endswith("%"):
        if not avg_mc:
            raise ValueError("ulazni MC ove pozicije nije poznat; upiši granicu kao MC (npr. $70k)")
        pct = abs(float(s.rstrip("%").lstrip("+-")))
        if not 0 < pct < 100:
            raise ValueError("pad mora biti između 0 i 100 %")
        return avg_mc * (1 - pct / 100)
    m = re.fullmatch(r"\$?([0-9.]+)([kmb])?(mc)?", s)
    if not m:
        raise ValueError(f"ne razumijem '{txt}': upiši MC (npr. $70k) ili postotak (npr. -20%)")
    return float(m.group(1)) * {"k": 1e3, "m": 1e6, "b": 1e9}.get(m.group(2) or "", 1)


def _post_dca(con, tcon, form, user):
    from urllib.parse import quote as qq
    tok = (form.get("token") or "").strip()
    lots = tcon.execute("SELECT id, league_id, symbol, sol_in FROM positions WHERE token=? AND status='open'", (tok,)).fetchall()
    if not lots:
        raise ValueError("ta pozicija nije otvorena")
    demo = _demo_sides(r[1] for r in lots)
    mcs = [(demo.get(r[1], (None,))[0], r[3] or 0) for r in lots]
    wsum = sum(w for m, w in mcs if m and w)
    avg_mc = wsum / sum(w / m for m, w in mcs if m and w) if wsum else None
    lvl = _dca_level(form.get("lvl"), avg_mc)
    if lvl < 30_000:
        raise ValueError(f"granica MC ${lvl:,.0f} je ispod 30k (pravilo: ispod 30k se ne kupuje)")
    sol = float((form.get("sol") or "0").replace(",", "."))
    lab, _typ, lo, hi = settings.LIMITS["size_sol"]
    cfg = _cfg(tcon)
    if not lo <= sol <= min(hi, cfg["max_sol_per_trade"]):
        raise ValueError(f"SOL mora biti između {lo:g} i {min(hi, cfg['max_sol_per_trade']):g}")
    now_mc, _ = _now_mcap([tok])
    if now_mc.get(tok) and lvl >= now_mc[tok]:
        raise ValueError(f"granica MC ${lvl:,.0f} nije ispod sadašnjeg MC-a ${now_mc[tok]:,.0f}: za kupnju sada koristi Kupi")
    sym = lots[0][2] or tok[:6]
    with _DCA_LOCK:
        orders = _dca_orders(tcon)
        if len([o for o in orders if o.get("token") == tok]) >= 5:
            raise ValueError("najviše 5 DCA naloga po poziciji")
        orders.append({"id": int(time.time() * 1000), "token": tok, "sym": sym, "mc": round(lvl, 2), "sol": sol,
                       "txt": (form.get("lvl") or "").strip(), "made": int(time.time())})
        settings.put(tcon, "dca_orders", orders, user)
    print(f"pravi trade: DCA nalog {sym}: dokup {sol:g} SOL na MC ${lvl:,.0f}", flush=True)
    pid = lots[0][0]
    return f"{BACK}?ok={qq(f'DCA: dokup {sym} za {sol:g} SOL kad MC padne na ${lvl:,.0f}.')}#poz-{pid}"


def _post_dcadel(tcon, form, user):
    from urllib.parse import quote as qq
    oid = str(form.get("id") or "")
    with _DCA_LOCK:
        orders = _dca_orders(tcon)
        left = [o for o in orders if str(o.get("id")) != oid]
        if len(left) == len(orders):
            raise ValueError("taj DCA nalog više ne postoji")
        settings.put(tcon, "dca_orders", left, user)
    return f"{BACK}?ok={qq('DCA nalog uklonjen.')}#pozicije"


def _dca_note(tcon, tok, text):
    log = list(settings.raw(tcon).get("dca_log") or [])
    log.insert(0, {"ts": int(time.time()), "token": tok, "text": text})
    settings.put(tcon, "dca_log", log[:30], "alat")


def dca_once(tcon, now=None, live_fn=None, buy_fn=None):
    """One pass over the DCA orders: an order whose position is closed is dropped; an order whose level the live MC
    touched buys once through the manual buy path (_post_buy) and is removed, with what happened in "dca_log".
    Returns [(order, result text)]."""
    now = now or time.time()
    orders = _dca_orders(tcon)
    if not orders:
        return []
    open_toks = {r[0] for r in tcon.execute("SELECT DISTINCT token FROM positions WHERE status='open'")}
    toks = sorted({o["token"] for o in orders if o["token"] in open_toks})
    live = {}
    if toks:
        if live_fn is not None:
            live = {t: (m or {}).get("mcap") for t, m in (live_fn(toks) or {}).items()}
        else:
            live, _ = _now_mcap(toks)
    done, keep = [], []
    for o in orders:
        if o["token"] not in open_toks:
            done.append((o, f"DCA {o.get('sym')}: pozicija je zatvorena, nalog uklonjen"))
            continue
        mc = live.get(o["token"])
        if not mc or mc > o["mc"]:
            keep.append(o)
            continue
        con = store.connect()
        try:
            copy.ensure(con)
            (buy_fn or _post_buy)(con, tcon, {"token": o["token"], "sol": f"{o['sol']:g}", "exit": "tpsl", "tp": "",
                                              "sl": ""}, settings.owner())
            done.append((o, f"DCA {o.get('sym')}: dokupljeno {o['sol']:g} SOL na MC ${mc:,.0f} (granica ${o['mc']:,.0f})"))
        except ValueError as e:
            done.append((o, f"DCA {o.get('sym')}: dokup na MC ${mc:,.0f} nije prošao: {e}"))
        finally:
            con.close()
    if done:
        with _DCA_LOCK:
            cur = _dca_orders(tcon)   # orders added by the page meanwhile stay
            gone = {str(o["id"]) for o, _ in done}
            settings.put(tcon, "dca_orders", [o for o in cur if str(o.get("id")) not in gone], "alat")
        for o, text in done:
            _dca_note(tcon, o["token"], text)
            print(f"pravi trade: {text}", flush=True)
    return done


# 10.11. (Jure: "da se može napraviti buy order na određenom market capu i odmah postaviti take profit i stop loss:
# sad je token na 90k, želim ga kupiti ako dođe na 50k, i od 50k staviti TP i SL"): a waiting buy order. It is kept in
# trade settings "buy_orders", watched every second with the DCA orders (same live MC), and when the MC is at or under
# its level it buys through the owner's manual buy (_post_buy) with the order's TP/SL, which then count from the real
# entry (~ the level). A DEX has no resting limit order: the bot buys at market the moment it sees the level, so:
#   - an order valid LIMIT_HOURS, then it lapses (a forgotten order must not buy a dead token days later);
#   - a market cap more than LIMIT_GAP below the level when first seen there (it fell straight through, the way a
#     rug falls) is not bought; the order is dropped with the reason;
#   - every check of the manual buy still holds at that moment (price, no rug, 30k MC, stake, wallet balance).
LIMIT_HOURS = 24
LIMIT_GAP = 0.25
LIMIT_MAX = 10
_LIMIT_LOCK = threading.Lock()


def _limit_orders(tcon):
    return list(settings.raw(tcon).get("buy_orders") or [])


def _limit_note(tcon, o, text):
    log = list(settings.raw(tcon).get("buy_log") or [])
    log.insert(0, {"ts": int(time.time()), "token": o.get("token"), "sym": o.get("sym"), "text": text})
    settings.put(tcon, "buy_log", log[:30], "alat")


def _post_limit(con, tcon, form, user):
    """The quick buy with "Kupi na MC": a buy order, or the buy itself when the market cap is already there."""
    from urllib.parse import quote as qq
    from league import auto
    from ui import real
    from ui.league import MINT, _symbol, market
    token = (form.get("token") or "").strip()
    if not MINT.fullmatch(token):
        token = real.resolve(token)[0]
    live = market({token})
    if token not in live:
        raise ValueError("nema cijene za tu adresu (je li to adresa tokena, a ne walleta?)")
    price, _liq, _, mcap = live[token]
    now_mc = (_now_mcap([token])[0] or {}).get(token) or mcap
    lvl = _dca_level(form.get("at"), now_mc)   # "$50k" / "50k" / "50000", or "-40%" from the market cap now
    if lvl < 30_000:
        raise ValueError(f"razina MC ${lvl:,.0f} je ispod 30k (pravilo: ispod 30k se ne kupuje)")
    if now_mc and lvl >= now_mc:
        return _post_buy(con, tcon, form, user)   # it is there already: the plain buy, now
    sol = float((form.get("sol") or "0").replace(",", "."))
    lab, _typ, lo, hi = settings.LIMITS["size_sol"]
    cfg = _cfg(tcon)
    if not lo <= sol <= min(hi, cfg["max_sol_per_trade"]):
        raise ValueError(f"SOL mora biti između {lo:g} i {min(hi, cfg['max_sol_per_trade']):g}")
    ex = form.get("exit") or "tpsl"
    tp, sl = (form.get("tp") or "").strip(), (form.get("sl") or "").strip()
    if ex == "tpsl":   # checked now on the entry the order would get (price scaled to the level), so a typo shows here
        px = price * lvl / mcap if price and mcap else None
        tp_px, _ = auto.parse_level(tp, px or 1.0, lvl, "tp")
        sl_px, _ = auto.parse_level(sl or _sl0(cfg), px or 1.0, lvl, "sl")
        if tp_px is not None and px and tp_px <= px:
            raise ValueError(f"TP mora biti iznad ulaza na MC ${lvl:,.0f}")
        if sl_px is not None and px and sl_px >= px:
            raise ValueError(f"SL mora biti ispod ulaza na MC ${lvl:,.0f}")
    elif ex not in ("smart", "manual"):
        raise ValueError("nepoznat način izlaza")
    sym = _symbol(token) or token[:6]
    now = int(time.time())
    with _LIMIT_LOCK:
        orders = _limit_orders(tcon)
        if len(orders) >= LIMIT_MAX:
            raise ValueError(f"najviše {LIMIT_MAX} naloga za kupnju odjednom")
        orders.append({"id": int(time.time() * 1000), "token": token, "sym": sym, "mc": round(lvl, 2), "sol": sol,
                       "exit": ex, "tp": tp, "sl": sl, "made": now, "until": now + LIMIT_HOURS * 3600,
                       "mc_made": round(now_mc or mcap or 0, 2)})
        settings.put(tcon, "buy_orders", orders, user)
        if ex == "tpsl":
            settings.put(tcon, "last_exit", {"tp": tp, "sl": sl}, user)
    print(f"pravi trade: nalog za kupnju {sym}: {sol:g} SOL kad MC padne na ${lvl:,.0f} (sada ${now_mc or 0:,.0f})",
          flush=True)
    words = f"Nalog: kupi {sym} za {sol:g} SOL kad MC padne na ${lvl:,.0f}"
    if ex == "tpsl":
        words += f", TP {tp or 'zadani'} · SL {sl or _sl0(cfg)} od tog ulaza"
    return f"{BACK}?ok={qq(words + f' (vrijedi {LIMIT_HOURS} h).')}#kupi-odmah"


def _post_limitdel(tcon, form, user):
    from urllib.parse import quote as qq
    oid = str(form.get("id") or "")
    with _LIMIT_LOCK:
        orders = _limit_orders(tcon)
        left = [o for o in orders if str(o.get("id")) != oid]
        if len(left) == len(orders):
            raise ValueError("taj nalog više ne postoji")
        settings.put(tcon, "buy_orders", left, user)
    return f"{BACK}?ok={qq('Nalog za kupnju otkazan.')}#kupi-odmah"


def limit_once(tcon, now=None, live_fn=None, buy_fn=None):
    """One pass over the buy orders (see LIMIT_HOURS / LIMIT_GAP above). Returns [(order, result text)]."""
    now = now or time.time()
    orders = _limit_orders(tcon)
    if not orders:
        return []
    toks = sorted({o["token"] for o in orders})
    if live_fn is not None:
        live = {t: (m or {}).get("mcap") for t, m in (live_fn(toks) or {}).items()}
    else:
        live, _ = _now_mcap(toks)
    done = []
    for o in orders:
        if now >= o.get("until", 0):
            done.append((o, f"Nalog {o.get('sym')}: istekao nakon {LIMIT_HOURS} h, MC nije pao na ${o['mc']:,.0f}"))
            continue
        mc = live.get(o["token"])
        if not mc or mc > o["mc"]:
            continue
        if mc < o["mc"] * (1 - LIMIT_GAP):
            done.append((o, f"Nalog {o.get('sym')}: MC je propao ravno na ${mc:,.0f} ({mc / o['mc'] - 1:+.0%} ispod "
                            f"razine ${o['mc']:,.0f}), kao kod ruga: nije kupljeno"))
            continue
        con = store.connect()
        try:
            copy.ensure(con)
            (buy_fn or _post_buy)(con, tcon, {"token": o["token"], "sol": f"{o['sol']:g}", "exit": o.get("exit") or "tpsl",
                                              "tp": o.get("tp") or "", "sl": o.get("sl") or ""}, settings.owner())
            done.append((o, f"Nalog {o.get('sym')}: kupljeno {o['sol']:g} SOL na MC ${mc:,.0f} (razina ${o['mc']:,.0f})"))
        except ValueError as e:
            done.append((o, f"Nalog {o.get('sym')}: kupnja na MC ${mc:,.0f} nije prošla: {e}"))
        finally:
            con.close()
    if done:
        with _LIMIT_LOCK:
            cur = _limit_orders(tcon)   # orders added by the page meanwhile stay
            gone = {str(o["id"]) for o, _ in done}
            settings.put(tcon, "buy_orders", [o for o in cur if str(o.get("id")) not in gone], "alat")
        for o, text in done:
            _limit_note(tcon, o, text)
            print(f"pravi trade: {text}", flush=True)
    return done


def _limit_orders_html(cfg):
    """The waiting buy orders under the quick buy: what, at which market cap, the exit, until when, "Otkaži"."""
    import datetime as _dt
    import zoneinfo
    orders = (cfg or {}).get("buy_orders") or []
    log = (cfg or {}).get("buy_log") or []
    if not orders and not log:
        return ""
    tz = zoneinfo.ZoneInfo("Europe/Zagreb")
    rows = []
    for o in orders:
        until = _dt.datetime.fromtimestamp(o.get("until", 0), tz).strftime("%d.%m. %H:%M")
        ex = (f' · TP {esc(o.get("tp") or "zadani")} · SL {esc(o.get("sl") or _sl0(cfg))}'
              if (o.get("exit") or "tpsl") == "tpsl" else f' · izlaz {esc(o.get("exit"))}')
        rows.append(f'<div class=ap-ord-r><span><b>{esc(o.get("sym") or "")}</b> · kupi na MC <b>{esc(_usd_short(o["mc"]))}</b>'
                    f' za {esc(redak.sol(o["sol"], 3))}{ex} · do {esc(until)}</span>'
                    f'<form method=post action=/pravi-trade/limitdel style="margin:0"><input type=hidden name=id '
                    f'value="{esc(str(o["id"]))}"><button class=ap-cancel>Otkaži</button></form></div>')
    head = f'<div class=ap-ord-h>Nalozi za kupnju · {len(orders)}</div>' if orders else ""
    last = "".join(f'<p class=mut>{esc(x["text"])}</p>' for x in log[:3])
    return f'<div class=ap-ord id=nalozi>{head}{"".join(rows)}</div>{last}'


def dca_loop(every=DCA_EVERY_S):
    """Background thread body for run_ui.py: dca_once every `every` seconds (one settings read when there is nothing
    to watch), its own connection."""
    con = None
    while True:
        try:
            if con is None:
                con = settings.connect()
            dca_once(con)
            limit_once(con)   # 10.11.: buy orders at a market cap, the same 1-s pass
            from league import followreview   # 10.11. (Jure: "isključi ih sam"): once an hour, never raises
            followreview.maybe_review()
        except Exception as e:  # noqa: BLE001 - a failed pass is retried in `every` seconds
            print(f"DCA: {type(e).__name__}: {e}", flush=True)
            try:
                con.close()
            except Exception:  # noqa: BLE001
                pass
            con = None
        time.sleep(every)


def _positions(tcon, viewer_buy, owner=False, pending=None, cfg=None):
    """"Otvorene pozicije 3 od 5" (maketa): one row per open position (what, whom it copies, when, the stake, how
    much of it is still held); a tap on the row opens the sell buttons 20 % / 50 % / sve (owner) and the live check;
    "Zatvorene" one more row; "Prodaj sve i isključi" in red under them. The list is re-fetched every LOG_EVERY_S
    seconds (positions_fragment) and only the rows that changed are swapped, so a tap is never lost to a redraw
    (9.11., Jure: real money, every second counts); an opened row stays open (it has an id)."""
    inner, meta, has_open = positions_inner(tcon, viewer_buy, owner, pending, cfg)
    return (_h2("Otvorene pozicije", meta, rid="ap-pos-n", sid="pozicije")
            + f'<div id=ap-pos data-src=/pravi-trade/pozicije data-every={LOG_EVERY_S}>{inner}</div>')


def positions_fragment(user):
    """GET /pravi-trade/pozicije: the rows of the positions, same access as the page. The count ("3 od 5") rides
    along and is copied into the section's title."""
    tcon = _tcon()
    try:
        if not settings.can_view(tcon, user):
            return None
        cfg = _cfg(tcon)
        owner = settings.is_owner(user)
        inner, meta, _ = positions_inner(tcon, not owner, owner, cfg.get("sell_req"), cfg)
        return inner + f'<span hidden data-meta="#ap-pos-n">{esc(meta)}</span>'
    finally:
        tcon.close()


def positions_inner(tcon, viewer_buy, owner=False, pending=None, cfg=None):
    """(inner html, meta text, has open) of the positions. meta: "3 od 5" (open of cfg max_open), or "3 otvoreno"
    without cfg. With cfg and the owner, the red "Prodaj sve i isključi" comes last whenever the switch is on or
    something is open (the same rule as before 10.11., when it stood under the header)."""
    pending = pending or {}
    # 10.11.: +status keeps the planner on the key, newest first, stopping at 60; with the (status, opened_ts) index
    # trade/aplog.py adds it would collect every open and closed position ever and sort them, once a second
    rows = tcon.execute("SELECT id, token, symbol, opened_ts, mode, status, reason, sol_in, sol_back, qty_raw, qty_left, "
                        "closed_ts, COALESCE(fees_sol,0), league_id FROM positions WHERE +status IN ('open','closed') "
                        "ORDER BY id DESC LIMIT 60").fetchall()
    sell_all = SELL_ALL if (owner and cfg and cfg.get("on")) else ""
    cap = f' od {cfg["max_open"]}' if cfg and cfg.get("max_open") else " otvoreno"
    if not rows:
        return ('<p class=ms-hint style="margin:4px 0 12px">Još nema pozicija. Kupi ručno ili zaprati nekoga pod „Kako trguje”.</p>'
                + sell_all, f"0{cap}", False)
    # 10.11. (Jure: "sekundni poslovi ne čitaju cijelu bazu"): this runs every second while the section is open; it read
    # the signature of every order ever made, now only those of the closed positions listed (orders_pos index)
    shut = [r[0] for r in rows if r[5] == "closed"]
    sigs = dict(tcon.execute(f"SELECT position_id, signature FROM orders WHERE position_id IN ({','.join('?' * len(shut))}) "
                             "AND signature IS NOT NULL ORDER BY id", shut)) if shut else {}
    # the trial word only where it tells something: when real and trial positions are listed together (the state
    # line under the title already says which mode the bot is in; prijedlog 3.4: "probno" was on every position)
    mixed = len({r[4] for r in rows}) > 1
    # 10.11. (Jure: "moram vidjeti na koliko market capa je bot kupio otvorenu poziciju"; TP 30 % za neke tokene):
    # the demo trade behind each open real position gives its entry MC and the exit it follows
    demo = _demo_sides(r[13] for r in rows if r[5] == "open")
    # 10.11. (Jure: "ako unesem adresu tokena koji je već u poziciji, pozicija se podeblja; nadopišu se dva ulaza:
    # prvi ulaz na toliko market capa i u zagradama profit/loss, i drugi"): the open lots of one token are ONE row,
    # each lot a line with its time, entry MC, stake and the move since (live MC from the shared cache, no fetch
    # per viewer); the sell buttons and the exit form act on every lot of the token
    groups = {}
    for r in rows:
        if r[5] == "open":
            groups.setdefault(r[1], []).append(r)
    now_mc, mc_ts = _now_mcap(list(groups)) if groups else ({}, None)
    st = settings.raw(tcon) if (owner and groups) else {}
    try:   # 10.11.: the assistant's newest review / opinion per position and per token (advice only)
        from ui import assistnotes
        notes = assistnotes.latest_for(tcon, [r[0] for r in rows], {r[1] for r in rows})
    except Exception:  # noqa: BLE001 - the list renders without the notes
        notes = {}

    def note_of(ids, tok):
        return next((notes[("p", i)] for i in ids if ("p", i) in notes), None) or notes.get(("t", tok))
    open_, closed = [], []
    for tok, lots in groups.items():
        lots = sorted(lots, key=lambda r: r[0])
        open_.append(_lot_group(tok, lots, demo, now_mc.get(tok), pending, owner,
                                viewer_buy, cfg, mixed, mc_ts, st.get("dca_orders") or [], st.get("dca_log") or [],
                                note_of([r[0] for r in lots], tok)))
    for (pid, tok, sym, ts, mode, st, why, sin, sback, q, ql, cts, fees, lid) in rows:
        trial = "probno" if (mixed and mode != "live") else None
        if st == "open":
            continue
        else:
            pnl = (sback or 0) - (sin or 0) - (fees or 0)
            sig = sigs.get(pid)
            link = (f'<a href="https://solscan.io/tx/{esc(sig)}" target=_blank rel=noopener>Solscan ↗</a>' if sig else None)
            nt = notes.get(("p", pid))
            if nt:   # 10.11.: a reviewed closed trade opens its review
                closed.append(_item(sym or short(tok or ""),
                                    cat(redak.ago(cts or ts), trial, f'Grok: {nt.get("verdict") or "bilješka"}', sep=" · "),
                                    _grok_box(nt) + (f"<p>{link}</p>" if link else ""), value=redak.sol(pnl, 4, sign=True),
                                    iid=f"zat-{pid}", value_tone=redak.tone(pnl)))
            else:
                closed.append(_prow(tok, name=sym or short(tok or ""),
                                    reason=cat(redak.ago(cts or ts), trial, raw(link) if link else None, sep=" · "),
                                    value=redak.sol(pnl, 4, sign=True), value_tone=redak.tone(pnl)))
    inner = "".join(open_) or '<p class=ms-hint style="margin:4px 0 12px">Ništa otvoreno.</p>'
    if closed:
        inner += _item("Zatvorene", "rezultat nakon svih naknada", "".join(closed)
                       + '<p class=ms-hint>Zarada = vraćeno − uloženo − mrežne naknade (potpis, prioritet i depozit za račun '
                         'tokena, oko 0,002 SOL, koji se vrati kad se pozicija proda do kraja); Jupiterova naknada je već u '
                         'iznosima.</p>', value=str(len(closed)), iid="zatvorene", value_tone="mut")
    if owner and cfg and (cfg.get("on") or open_):   # nothing to sell and nothing running: no red button
        inner += SELL_ALL
    meta = f"{len(open_)}{cap}"
    return inner, meta, bool(open_)


# ---------- the Autopilot's log -----------------------------------------------------------------------------------
# 10.11. (Jure: "autopilot ispisuje na klik log koji je pri vrhu: kad je kupio, kad nije, što je preskočio i zašto,
# je li morao kupiti"): one closed section right under the chart with a one-line summary of the last 24 h; opened, it
# lists every decision from trade/aplog.py (another group's module: behind try/except, and without it the plain list
# of orders that was here before). Nothing is fetched while the section is closed.

LOG_N = 15
LOG_ROWS = 80     # decisions listed when the log is open (trade.aplog.entries limit)
LOG_EVERY_S = 1   # 9.11. (Jure): every second is money; the open log and the positions are re-fetched every second
LINE_TTL_S = 15   # the closed log's one-line summary of the last 24 h: on every page view and every header refresh
DAY_ROWS = 1000   # decisions read for that line when trade.aplog has no summary_24h of its own (aplog.DAY_LIMIT)
SIDE = {"buy": "kupnja", "sell": "prodaja", "rent": "depozit natrag"}
STATUS = {"ok": ("prošlo", "good"), "dry": ("probno", ""), "failed": ("greška", "bad"), "blocked": ("preskočeno", "warn")}
# 10.11. (maketa, pravilo 5): a decision is a word after a dot, not a word in capitals
KIND_HR = {"kupio": ("kupio", "good"), "prodao": ("prodao", "acc"), "preskocio": ("preskočio", ""),
           "nije_proslo": ("nije prošlo", "warn")}
_DN = {"ts": 0.0, "key": None, "rows": None}
_DN_LINE = {"ts": 0.0, "key": None, "line": None}


def _aplog_mod():
    try:
        from trade import aplog
        return aplog
    except Exception:  # noqa: BLE001 - not merged yet, or broken: the plain order list is shown instead
        return None


def _league_ro():
    """league.db read-only for the demo side's skips (copy_log); None when the file is not there."""
    try:
        return copy._ro(store.DB)
    except Exception:  # noqa: BLE001
        return None


def dnevnik_data(tcon, now=None):
    """The newest LOG_ROWS decisions from trade.aplog.entries, newest first, or None when the module is missing or
    fails (then the old order list is shown). One read per LOG_EVERY_S per database, shared by every viewer who has
    the log open (it is asked only while it is open)."""
    now = now or time.time()
    with _LOCK:
        if _DN["ts"] and _DN["key"] == settings.DB and 0 <= now - _DN["ts"] < LOG_EVERY_S:
            return _DN["rows"]
    ap = _aplog_mod()
    rows = None
    if ap is not None:
        lcon = _league_ro()
        try:
            rows = list(ap.entries(tcon, lcon, limit=LOG_ROWS) or [])
        except Exception as e:  # noqa: BLE001 - the log falls back to the order list, the page renders
            print(f"autopilot: dnevnik odluka nije dostupan: {type(e).__name__}: {e}", flush=True)
            rows = None
        finally:
            if lcon is not None:
                lcon.close()
    with _LOCK:
        _DN.update(ts=now, key=settings.DB, rows=rows)
    return rows


def dnevnik_summ(tcon, now=None):
    """trade.aplog's summary of the whole last 24 h ({signali, kupio, prodao, preskocio, nije_proslo, razlozi}), or
    None without the module. 10.11.: never summary() over the 80 listed rows: on a busy day those are a few hours,
    and the line would say "zadnja 24 h" about less. summary_24h when the module has it (its own 5-s cache), else
    summary() over the day's entries."""
    now = now or time.time()
    ap = _aplog_mod()
    if ap is None:
        return None
    lcon = _league_ro()
    try:
        if hasattr(ap, "summary_24h"):
            return dict(ap.summary_24h(tcon, lcon, now=now) or {})
        return dict(ap.summary(ap.entries(tcon, lcon, limit=DAY_ROWS, since=int(now - 86400)) or [], now) or {})
    except Exception as e:  # noqa: BLE001
        print(f"autopilot: sažetak dnevnika nije dostupan: {type(e).__name__}: {e}", flush=True)
        return None
    finally:
        if lcon is not None:
            lcon.close()


def _signala(n):
    return f"{n} signal" if n % 10 == 1 and n % 100 != 11 else f"{n} signala"


def dnevnik_summary(summ):
    """'Zadnja 24 h: 12 signala · 2 kupljeno · 9 preskočeno (5 bez dokaza u demu, 3 signal star) · 1 nije prošlo'."""
    g = lambda k: int(summ.get(k) or 0)   # noqa: E731
    # 10.11. (pregled): when trade.aplog read only its first DAY_LIMIT decisions of a busy day, say so
    head = f"Zadnjih {g('capped')} odluka" if g("capped") else "Zadnja 24 h"
    if not any(g(k) for k in ("signali", "kupio", "prodao", "preskocio", "nije_proslo")):
        return f"{head}: nijedan signal"
    why = ", ".join(f"{int(n)} {w}" for w, n in (summ.get("razlozi") or [])[:2])   # two, as dizajn.md shows it
    parts = [_signala(g("signali")), f'{g("kupio")} kupljeno',
             f'{g("preskocio")} preskočeno' + (f" ({why})" if why and g("preskocio") else "")]
    if g("nije_proslo"):
        parts.append(f'{g("nije_proslo")} nije prošlo')
    if g("prodao"):
        parts.append(f'{g("prodao")} prodano')
    return f"{head}: " + " · ".join(parts)


def dnevnik_line(tcon, now=None):
    """The one line in the closed log's header: the decisions of the last 24 h, or, without trade.aplog, how many
    orders there were. Kept LINE_TTL_S: the page, the 45-s header and the open log all show it."""
    now = now or time.time()
    with _LOCK:
        if _DN_LINE["ts"] and _DN_LINE["key"] == settings.DB and 0 <= now - _DN_LINE["ts"] < LINE_TTL_S:
            return _DN_LINE["line"]
    summ = dnevnik_summ(tcon, now)
    if summ is not None:
        line = dnevnik_summary(summ)
    else:   # the newest orders only (a bounded read on the key), never a count over the whole table
        n = tcon.execute("SELECT COUNT(*) FROM (SELECT ts FROM orders ORDER BY id DESC LIMIT 500) WHERE ts >= ?",
                         (int(now - 86400),)).fetchone()[0]
        line = f"Zadnja 24 h: {n} naloga" if n else "Zadnja 24 h: nijedan nalog"
    with _LOCK:
        _DN_LINE.update(ts=now, key=settings.DB, line=line)
    return line


# 10.11. (Jure: "piše da je 12 redova preskočeno; zanima me zašto i kako su performali nakon toga: jesu li ipak
# dosegli 15 % ili su preskočeni s dobrim razlogom"): a small box at the top of the open log, right under its one-line
# summary. One sentence with the answer, then one row per skipped buy of the last 24 h (the set the "N preskočeno"
# counts, plus the technical failures, which the bot should have bought), each with who gave the signal, the reason
# and what the price did in the hour after the decision (kol/preskoceni.py, measured by the minute loop). The open log
# is asked for every second: the box is built at most every SKIP_TTL_S, reads minute.db read-only by key for the
# listed rows and never touches the network.
SKIP_TTL_S = 30
SKIP_SHOW = 15     # rows shown at once; the rest behind "Prikaži sve"
SKIP_WHY = 110     # characters of the owner's reason in a row (the whole text is in the row's title)
_SK = {"ts": 0.0, "key": None, "html": None, "rows": None}


def _sl_pct():
    """The stop the skipped-signal box measures against, as a positive whole percent (league/copy.DEFAULT_SL "-20%"
    -> 20, the minute check's stop; 10.11.: the Autopilot's own default stop is the owner's setting, settings.sl_default)."""
    try:
        return abs(int(float(str(copy.DEFAULT_SL).strip().rstrip("%"))))
    except ValueError:
        return 20


def _skip_rows(tcon, now):
    """(skipped buys of the last 24 h newest first, whether anything was bought) from trade.aplog; (None, False)
    without the module."""
    from kol import preskoceni
    ap = _aplog_mod()
    if ap is None:
        return None, False
    lcon = _league_ro()
    try:
        rows = list(ap.entries(tcon, lcon, limit=getattr(ap, "DAY_LIMIT", DAY_ROWS), since=int(now - 86400), now=now) or [])
    finally:
        if lcon is not None:
            lcon.close()
    rows = [e for e in rows if (e.get("ts") or 0) >= now - 86400]
    return preskoceni.skipped(rows), any(e.get("kind") == "kupio" for e in rows)


def _skip_paths(keys):
    """{(token, minute): skip_path row}, or None when minute.db (or its table) is not there yet."""
    from kol import minute, preskoceni
    try:
        con = minute.ro()
    except sqlite3.Error:
        return None
    if con is None:
        return None
    try:
        return preskoceni.lookup(con, keys)
    except sqlite3.Error:
        return None
    finally:
        con.close()


def _cut(text, n=SKIP_WHY):
    t = " ".join(str(text or "").split())
    if len(t) <= n:
        return t
    return t[:n].rsplit(" ", 1)[0].rstrip(",;:·-–(") + "…"


def _skip_src(s):
    """Who gave the signal, short: a wallet follow's label can be its whole address ("wallet 7xKX…sAsU"), a crew's
    label starts with the kind again ("ekipa ekipa: @murad + …" -> "ekipa @murad + …")."""
    s = " ".join(str(s or "").split())
    s = re.sub(r"^(\w+) \1:?\s*", r"\1 ", s)
    m = re.fullmatch(r"wallet ([1-9A-HJ-NP-Za-km-z]{20,})", s)
    return f"wallet {short(m.group(1))}" if m else s


_SKIP_DOT = {"miss": "warn", "ok": "good"}   # propušteno = a warning, dobro preskočen = fine; the rest grey


def _skip_why(e, owner):
    """The reason as this viewer may read it: the owner as written (aplog scrubs it), an invited player its short
    word only."""
    return " ".join(str(((e.get("why") or e.get("why_short")) if owner else e.get("why_short")) or "").split())


def _skip_url(e):
    """10.11. (Jure: "kad se klikne na njega, otvori pop-up"): the pop-up of one skip, by token and decision time."""
    return f'/pravi-trade/preskok?m={quote(e.get("token") or "")}&amp;t={int(e.get("ts") or 0)}'


def _skip_line(e, p, v, now):
    """10.11. (Jure: "na koliko market capa ga je zvao ... koliko se cijena makla u 5, 10, 15 minuta"): the row's
    last line, e.g. "zvan na 85k $ · 5 min +14 % · 10 min +22 % · 15 min +9 %" (moves from the call). Counted from
    the decision when the call's price is not known ("preskočen na ..."); without a supply only the moves. A row that
    is not measured says the time of the call when it is known, else nothing (None)."""
    from kol import preskoceni
    mv = preskoceni.moves(p) if v["kind"] in ("miss", "ok") else None
    if mv is None:
        if not e.get("sig_ts"):
            return None
        day, _, tm = preskoceni.clock(e["sig_ts"], now).rpartition(" ")   # "jučer 18:54:35" -> zvan jučer u 18:54:35
        return cat(f"zvan {day + ' ' if day else ''}u ", raw(f"<b>{redak.h(tm)}</b>"))
    poziv = mv["ref"] == "poziv"
    mc = (mv["poziv"] or (None, None))[1] if poziv else mv["odluka"][1]
    steps = cat(*(raw(f"<span class=ap-skx>{k} min <b>{redak.h(redak.pct(100 * chg))}</b></span>")
                  for k, _, _, _, chg in mv["steps"] if chg is not None), sep=" · ")
    if not mc:   # no supply: "od poziva: 5 min +14 % · ..."
        return cat("od poziva: " if poziv else "od preskoka: ", steps) if steps else None
    # on a phone the market cap is the first line and the three moves the second (CSS .ap-skc / .ap-sks), never a
    # line that breaks after a lone "·"
    head = cat("zvan na " if poziv else "preskočen na ", raw(f"<b>{redak.h(redak.usd(mc))}</b>"))
    return cat(raw(f"<span class=ap-skc>{head}</span>"),
               raw(f"<span class=ap-sks> · </span><span class=ap-skm>{steps}</span>") if steps else None)


def _skip_row(e, v, owner, now, p=None):
    """One skipped buy as the shared row (10.11., maketa): the token; when, whose signal and the reason under it;
    the verdict as a word after a dot on the right and what the price did under it; across the whole row the market
    cap at the call and the moves 5, 10 and 15 minutes after it (_skip_line). A tap opens the pop-up of this skip
    (/pravi-trade/preskok: the exact times, market caps and moves as a small table), which links to the token's live
    pop-up."""
    from kol import preskoceni
    tok = e.get("token") or ""
    full = _skip_why(e, owner)
    why = _cut(full)
    meta = " · ".join(x for x in (preskoceni.hm(e.get("ts") or 0, now), _skip_src(e.get("source")),
                                  "nije prošlo (tehnički)" if e.get("kind") == "nije_proslo" else "") if x)
    r = _prow(tok, name=e.get("symbol") or short(tok), reason=cat(meta, raw("<br>") if why else None, why),
              value=dot(_SKIP_DOT.get(v["kind"], ""), v["word"]), sub=v["detail"], title=full if why != full else None)
    if tok:
        r = r.replace(f'data-pop="/pravi-trade/token?m={quote(tok)}"', f'data-pop="{_skip_url(e)}"', 1)
    line = _skip_line(e, p, v, now)
    if line:   # its own line across the row (CSS .ap-skl: flex-basis 100 %), before the closing tag of the row
        r = r[:-len("</div>")] + f"<div class=ap-skl>{line}</div></div>"
    # the reason and the numbers may take two lines each on a phone (neither becomes a column of single words)
    return raw(r.replace('class="ms-row', 'class="ms-row ap-wrap ap-skr', 1))


def _skip_html(rows, paths, now, owner, tp_cfg):
    """The block for one kind of viewer (the owner reads the reason as written, an invited player its short word):
    the answer in one sentence, which rule cost the most, the rows, the rest behind "Prikaži sve", how it is measured."""
    from kol import preskoceni
    tp, sl = preskoceni.TP, _sl_pct()
    keys = [(e["token"], preskoceni.minute_of(e.get("ts"))) for e in rows]
    # 10.11. (CLAUDE.md): a skip because of the $30k floor is listed but never measured
    vs = [preskoceni.verdict(preskoceni.UNDER_FLOOR if preskoceni.under_floor(e) else (paths or {}).get(k),
                             e.get("ts") or 0, now, tp, sl) for e, k in zip(rows, keys)]
    head = preskoceni.sentence([v for e, v in zip(rows, vs) if e["kind"] == "preskocio"],
                               [v for e, v in zip(rows, vs) if e["kind"] == "nije_proslo"], tp, sl)
    b = ['<h3 class=ap-sub><span>Preskočeni u zadnja 24 h</span></h3>', f"<p class=ap-sk-h>{esc(head)}</p>"]
    missed = {}
    for e, v in zip(rows, vs):
        if v["kind"] == "miss" and e["kind"] == "preskocio":
            w = e.get("why_short") or "ostalo"
            missed[w] = missed.get(w, 0) + 1
    if missed:   # which RULE cost the most: the reasons of the rule skips that would have paid
        b.append("<p class=mut>Propušteni po razlogu: " + esc(", ".join(
            f"{n} {w}" for w, n in sorted(missed.items(), key=lambda kv: (-kv[1], kv[0])))) + ".</p>")
    items = [_skip_row(e, v, owner, now, (paths or {}).get(k)) for e, v, k in zip(rows, vs, keys)]
    b += items[:SKIP_SHOW]
    if len(items) > SKIP_SHOW:
        b.append(_item("Prikaži sve", None, "".join(items[SKIP_SHOW:]), value=f"još {len(items) - SKIP_SHOW}",
                       iid="ap-sk-sve", value_tone="mut"))
    note = (f"Mjereno od trenutka odluke, 1-minutnim svijećama, 60 min: propušteno = +{tp} % prije −{sl} %; "
            f"dobro preskočen = prvo −{sl} % ili +{tp} % nije došao.")
    if paths is None:
        note += " Mjerenje još nije pokrenuto."
    if tp_cfg != tp:   # the target the Autopilot really exits at, only when it is not the +15 % asked about here
        known = [preskoceni.hit((paths or {}).get(k), tp_cfg, sl) for k in keys]
        known = [h for h in known if h is not None]
        k = sum(known)
        note += f" Autopilot sada izlazi na +{tp_cfg} %" + (
            f": {k} od {len(known)} izmjerenih bi ga {'dosegao' if k % 10 == 1 and k % 100 != 11 else 'dosegla'} "
            f"prije −{sl} %." if known else ".")
    b.append(f"<p class=ms-hint>{esc(note)}</p>")
    return f'<div class=ap-sk id=ap-sk>{"".join(b)}</div>'


def skip_box(tcon, cfg, now=None, owner=True):
    """The box for the top of the open log (owner or invited viewer), kept SKIP_TTL_S per database. '' without
    trade.aplog or without any decision in the last 24 h; one quiet line when nothing was skipped."""
    now = now or time.time()
    with _LOCK:
        if _SK["key"] == settings.DB and _SK["html"] is not None and 0 <= now - _SK["ts"] < SKIP_TTL_S:
            return _SK["html"][bool(owner)]
    rows, bought = _skip_rows(tcon, now)
    if not rows:
        quiet = '<p class=mut id=ap-sk>U zadnja 24 h nijedan signal nije preskočen.</p>' if bought else ""
        html = {True: quiet, False: quiet}
    else:
        from kol import preskoceni
        paths = _skip_paths([(e["token"], preskoceni.minute_of(e.get("ts"))) for e in rows])
        tp_cfg = int(cfg.get("tp_default") or 15)
        html = {o: _skip_html(rows, paths, now, o, tp_cfg) for o in (True, False)}
    with _LOCK:
        _SK.update(ts=now, key=settings.DB, html=html, rows=rows or [])   # rows: the pop-up of one skip reads them
    return html[bool(owner)]


# 10.11. (Jure: "za ove preskočene tokene ... kad se klikne na njega, otvori pop-up gdje piše koliko je skočio u 5
# minuta, kad je, na koliko ga je zvao market capa i koliko je trenutno market capa sa točnim vremenom, satom"). The
# pop-up of one skipped buy: who called it and why it was skipped, then one small table (the call, the decision,
# +5/+10/+15 min, the high of the hour, now) with Zagreb clock times, market caps (supply x price, kol/preskoceni.
# moves) and the move from the call. It is re-fetched every second while open (POP_JS), so it reads only what is
# already there: the decision from the box's rows (or one aplog read every SKIP_TTL_S), minute.db read-only by key,
# and "Sada" from the shared live cache (_live_cached, renewed by the background thread). Nothing else on the network.
_SKP = {"ts": 0.0, "key": None, "rows": None}


def _skip_decision(tcon, mint, t, now):
    """The aplog row of one skip (token, exact decision time) from the last 24 h, or None."""
    with _LOCK:
        if _SK["key"] == settings.DB and _SK.get("rows") is not None and 0 <= now - _SK["ts"] < SKIP_TTL_S:
            rows = _SK["rows"]
        elif _SKP["key"] == settings.DB and _SKP["rows"] is not None and 0 <= now - _SKP["ts"] < SKIP_TTL_S:
            rows = _SKP["rows"]
        else:
            rows = None
    if rows is None:
        rows = _skip_rows(tcon, now)[0] or []
        with _LOCK:
            _SKP.update(ts=now, key=settings.DB, rows=rows)
    return next((e for e in rows if e.get("token") == mint and int(e.get("ts") or 0) == t), None)


def _live_quote(mint, now):
    """(DexScreener state of one token, unix time of that quote) from the shared live cache, or (None, None)."""
    m = _live_one(mint, now)
    with _LOCK:
        hit = _LIVE_CACHE.get((mint,))
    return m, (hit[0] if hit and m else None)


def _skp_cells(when, mc, chg, cls=""):
    c = f'<span class="{redak.tone(chg)}">{redak.h(redak.pct(100 * chg))}</span>' if chg is not None else ""
    return f"<td>{redak.h(when or redak.DASH)}</td><td>{redak.h(redak.usd(mc) if mc else redak.DASH)}</td><td>{c}</td>"


# 10.11. (Jure: "u tablici treba biti koliko je taj token u tom momentu bio vrijedan; to treba dobiti prioritet,
# real-time podaci"; "iz pop-up prozora fali link na objavu gdje je korisnik zvao"): the pop-up no longer waits for the
# candle measurement (GeckoTerminal's free limit answers 429 most minutes) for its numbers. It shows at once:
#  - the MC the decision itself saw (league copy_mc for the copy stage, the demo entry for the real-money stage),
#  - the MC at the post when the X collector measured it (kol.db calls.mcap0) and the link to the post (X, Telegram)
#    or to the wallet's buy (Solscan),
#  - +5/+10/+15 min from our own live samples (skip_live in trade.db, DexScreener, sample_skips below), until the
#    candles are measured; then the candle numbers, as before.
SKIP_LIVE_SCHEMA = ("CREATE TABLE IF NOT EXISTS skip_live (token TEXT, t INTEGER, k INTEGER, ts INTEGER, price REAL, "
                    "mcap REAL, PRIMARY KEY (token, t, k))")
SAMPLE_KS = (0, 5, 10, 15)    # minutes after the call (0 = the decision itself, when it saw no MC)
SAMPLE_LATE_S = 180           # a sample taken later than this after its minute is not that minute any more
SAMPLE_WINDOW_S = 20 * 60     # skips younger than this are sampled
SAMPLE_EVERY_S = 5


def _skip_ctx(tcon, e, mint, t):
    """{kind, target, mc_seen, mc_ts, ev_ts} of one skip: who gave the signal (the follow) and the MC the decision saw.
    Copy stage: aplog id "c<follow>:<token>:<side>" and league copy_mc; real-money stage: the blocked positions row,
    its demo trade (entry MC) and that trade's follow. {} when league.db is not there."""
    out = {}
    lg = _league_ro()
    if lg is None:
        return out
    try:
        fid, lid = None, None
        key = str(e.get("id") or "")
        if key.startswith("c") and ":" in key:
            try:
                fid = int(key[1:].split(":")[0])
            except ValueError:
                fid = None
            try:
                r = lg.execute("SELECT mcap, ts FROM copy_mc WHERE follow_id=? AND token=? ORDER BY ts DESC LIMIT 1",
                               (fid, mint)).fetchone()
                if r and r[0]:
                    out.update(mc_seen=r[0], mc_ts=r[1])
            except sqlite3.Error:
                pass
        else:
            r = tcon.execute("SELECT league_id FROM positions WHERE token=? AND opened_ts BETWEEN ? AND ? AND league_id "
                             "IS NOT NULL ORDER BY ABS(opened_ts - ?) LIMIT 1", (mint, t - 5, t + 5, t)).fetchone()
            lid = r[0] if r else None
            if lid:
                tr = lg.execute("SELECT entry_mcap, opened_ts, follow_id FROM trades WHERE id=?", (lid,)).fetchone()
                if tr:
                    if tr[0]:
                        out.update(mc_seen=tr[0], mc_ts=tr[1])
                    fid = tr[2]
                ev = lg.execute("SELECT ev_ts FROM copy_log WHERE trade_id=? AND action='ulaz' LIMIT 1", (lid,)).fetchone()
                if ev and ev[0]:
                    out["ev_ts"] = ev[0]
        if fid is not None:
            f = lg.execute("SELECT kind, target FROM follows WHERE id=?", (fid,)).fetchone()
            if f:
                out.update(kind=f[0], target=f[1])
    except sqlite3.Error:
        pass
    finally:
        lg.close()
    return out


def _call_post(kind, target, mint, sig_ts):
    """(link, its words, MC at the post or None) of the signal itself: the X post (kol.db calls.url, its mcap0), the
    Telegram post (t.me/<channel>/<post>) or the wallet's buy on Solscan; (None, None, None) when it is not found."""
    if not kind or not target or not sig_ts:
        return None, None, None
    p = copy._paths()
    win = (int(sig_ts) - 900, int(sig_ts) + 900)
    if kind == "wallet":
        hc = copy._ro(p["hype"])
        try:
            r = copy._q(hc, "SELECT sig FROM chain_trades WHERE wallet=? AND mint=? AND side='buy' AND ts BETWEEN ? AND ? "
                            "ORDER BY ABS(ts - ?) LIMIT 1", (target, mint, *win, int(sig_ts)))
        finally:
            if hc is not None:
                hc.close()
        return ((f"https://solscan.io/tx/{quote(r[0][0])}", "Kupnja walleta na Solscanu", None) if r and r[0][0]
                else (f"https://solscan.io/account/{quote(target)}", "Wallet na Solscanu", None))
    handles = copy.members_of(target) if kind == "ekipa" else [target.lstrip("@")]
    best = None   # (distance, link, words, mcap)
    kc, tc = copy._ro(p["kol"]), copy._ro(p["tg"])
    try:
        for h in handles:
            if h.startswith("tg:"):
                for ch, post, ts in copy._q(tc, "SELECT channel, post, ts FROM posts WHERE channel=? AND ts BETWEEN ? AND ? "
                                                "AND cas LIKE ? ORDER BY ABS(ts - ?) LIMIT 1", (h[3:], *win, f"%{mint}%", int(sig_ts))):
                    d = abs(ts - sig_ts)
                    if best is None or d < best[0]:
                        best = (d, f"https://t.me/{quote(ch)}/{int(post)}", f"Objava na Telegramu ({ch})", None)
            else:
                for url, ts, mc in copy._q(kc, "SELECT url, ts, mcap0 FROM calls WHERE handle=? COLLATE NOCASE AND token=? "
                                               "AND ts BETWEEN ? AND ? ORDER BY ABS(ts - ?) LIMIT 1", (h, mint, *win, int(sig_ts))):
                    d = abs(ts - sig_ts)
                    if url and (best is None or d < best[0]):
                        best = (d, url, f"Objava @{h} na X-u", mc)
    finally:
        for c in (kc, tc):
            if c is not None:
                c.close()
    if best:
        return best[1], best[2], best[3]
    h = next((x for x in handles if not x.startswith("tg:")), None)
    if h:   # the call came through another collector (hype.db): at least the account
        return f"https://x.com/{quote(h)}", f"Profil @{h} na X-u (objava nije spremljena)", None
    ch = handles[0][3:] if handles and handles[0].startswith("tg:") else None
    return (f"https://t.me/{quote(ch)}", f"Kanal {ch} na Telegramu", None) if ch else (None, None, None)


def _skip_samples(tcon, mint, t):
    """{k: (ts, mcap, price)} of our own live samples of one skip (sample_skips)."""
    try:
        return {k: (ts, mc, px) for k, ts, mc, px in tcon.execute(
            "SELECT k, ts, mcap, price FROM skip_live WHERE token=? AND t=?", (mint, int(t)))}
    except sqlite3.Error:
        return {}


def _recent_skips(tcon, now):
    """[(token, decision ts, base ts for +5/+10/+15)] of the skips of the last SAMPLE_WINDOW_S: the copy stage from
    league copy_log, the real-money stage from trade.db positions (blocked / failed rows of a demo trade). Under
    $30k is never sampled (CLAUDE.md)."""
    since = int(now - SAMPLE_WINDOW_S)
    out = []
    lg = _league_ro()
    if lg is not None:
        try:
            for tok, ts, ev, note in lg.execute(
                    "SELECT c.token, c.ts, c.ev_ts, c.note FROM copy_log c JOIN follows f ON f.id = c.follow_id "
                    "WHERE c.ts >= ? AND c.action='preskočeno' AND c.side='buy' AND f.user=?", (since, settings.LEAGUE_USER)):
                if "ispod 30k" not in (note or ""):
                    out.append((tok, int(ts), int(ev or ts)))
        except sqlite3.Error:
            pass
        finally:
            lg.close()
    for tok, ts, why in tcon.execute("SELECT token, opened_ts, reason FROM positions WHERE opened_ts >= ? AND status IN "
                                     "('blocked','failed') AND league_id IS NOT NULL", (since,)):
        if "ispod 30k" not in (why or ""):
            out.append((tok, int(ts), int(ts)))
    return out


def sample_skips(tcon, now=None, live_fn=None):
    """One pass: every recent skip whose minute has come (0 = the decision, 5/10/15 after the call) gets the live MC
    from ONE DexScreener request for all of them (prijedlog.live_market). Returns the number of samples written."""
    now = now or time.time()
    tcon.execute(SKIP_LIVE_SCHEMA)
    due = []
    for tok, t, base in _recent_skips(tcon, now):
        have = {k for (k,) in tcon.execute("SELECT k FROM skip_live WHERE token=? AND t=?", (tok, t))}
        for k in SAMPLE_KS:
            at = t if k == 0 else base + k * 60
            if k not in have and 0 <= now - at <= SAMPLE_LATE_S:
                due.append((tok, t, k))
    if not due:
        return 0
    from ui import prijedlog
    live = (live_fn or prijedlog.live_market)(sorted({d[0] for d in due})) or {}
    n = 0
    for tok, t, k in due:
        m = live.get(tok)
        if m and m.get("price"):
            tcon.execute("INSERT OR IGNORE INTO skip_live VALUES (?,?,?,?,?,?)",
                         (tok, t, k, int(now), m.get("price"), m.get("mcap")))
            n += 1
    tcon.execute("DELETE FROM skip_live WHERE ts < ?", (int(now - 3 * 86400),))
    tcon.commit()
    return n


def skip_sampler_loop(every=SAMPLE_EVERY_S):
    """Background thread body for run_ui.py: sample_skips every `every` seconds, its own connection."""
    con = None
    while True:
        try:
            if con is None:
                con = settings.connect()
            sample_skips(con)
        except Exception as e:  # noqa: BLE001 - a failed pass is retried in `every` seconds
            print(f"preskočeni uživo: {type(e).__name__}: {e}", flush=True)
            try:
                con.close()
            except Exception:  # noqa: BLE001
                pass
            con = None
        time.sleep(every)


def skip_popup(user, mint, t, now=None):
    """GET /pravi-trade/preskok?m=<mint>&t=<decision ts>: the pop-up of one skipped buy (see above); None without
    access (the same check as the page and its other fragments)."""
    from kol import preskoceni
    tcon = _tcon()
    try:
        if not settings.can_view(tcon, user):
            return None
        owner = settings.is_owner(user)
        now = now or time.time()
        try:
            t = int(t)
        except (TypeError, ValueError):
            t = 0
        # the mint is only a key into the box's own rows: anything that is not one of them is "not found", and only a
        # found one reaches the live cache
        mint = str(mint or "").strip()
        if not mint or len(mint) > 64 or t <= 0:
            return "<p class=mut>Ta odluka nije pronađena.</p>"
        e = _skip_decision(tcon, mint, t, now)
        ctx = _skip_ctx(tcon, e, mint, t) if e is not None else {}
        samples = _skip_samples(tcon, mint, t) if e is not None else {}
    finally:
        tcon.close()
    link = f'<p><span class=ap-lnk role=link tabindex=0 data-pop="/pravi-trade/token?m={quote(mint)}">Provjera tokena uživo</span></p>'
    if e is None:
        return f"<p class=mut>Ta odluka više nije među preskočenima u zadnja 24 h.</p>{link}"
    sym = e.get("symbol") or short(mint)
    floor = preskoceni.under_floor(e)
    p = None if floor else (_skip_paths([(mint, preskoceni.minute_of(t))]) or {}).get((mint, preskoceni.minute_of(t)))
    v = preskoceni.verdict(preskoceni.UNDER_FLOOR if floor else p, t, now, preskoceni.TP, _sl_pct())
    who = " · ".join(x for x in (_skip_src(e.get("source")),
                                 "nije prošlo (tehnički)" if e.get("kind") == "nije_proslo" else "") if x)
    why = _skip_why(e, owner)
    b = [f"<h3 translate=no>{esc(sym)}</h3>",
         f"<p class=ap-skp-w><span class=ap-skp-s>{esc(who or 'izvor nepoznat')}</span>"
         + (f"<br>{esc(why)}" if why else "") + "</p>"]
    # "Sada" from the live cache only for a token that is analysed at all (CLAUDE.md: under $30k it is not)
    if not floor:
        _bg_start()   # as the token pop-up: the open pop-up's quote is renewed off the request thread
    live, live_ts = (None, None) if floor else _live_quote(mint, now)
    sup_live = None
    if live and live.get("price") and live.get("mcap"):
        sup_live = live["mcap"] / live["price"]
    mv = preskoceni.moves(p, sup_live) if v["kind"] in ("miss", "ok") else None
    sig = e.get("sig_ts") or (p or {}).get("sig_ts") or ctx.get("ev_ts")
    post_url, post_words, post_mc = _call_post(ctx.get("kind"), ctx.get("target"), mint, sig)
    poziv = bool(mv and mv["ref"] == "poziv")
    head = "Od poziva" if (poziv or not mv) else "Od preskoka"
    rows = [f"<tr><th></th><th>Vrijeme</th><th>Market cap</th><th>{head}</th></tr>"]
    seen_mc = ctx.get("mc_seen") or (samples.get(0) or (None, None))[1]
    call_mc = (mv["poziv"][1] if poziv else None) or post_mc
    rows.append("<tr><td>Poziv</td>" + _skp_cells(preskoceni.clock(sig, now) if sig else None, call_mc, None) + "</tr>")
    dec = mv["odluka"] if mv else (None, None, None)
    ref_mc = call_mc or seen_mc   # 10.11.: without candles the moves are from the call's MC, else from the decision's
    rows.append("<tr><td>Preskočeno</td>" + _skp_cells(
        preskoceni.clock(t, now), dec[1] or seen_mc,
        dec[2] if poziv else ((seen_mc / call_mc - 1) if (not mv and call_mc and seen_mc) else None)) + "</tr>")
    if not mv:   # our own live samples (sample_skips) until the candles are measured
        for k in SAMPLE_KS[1:]:
            got = samples.get(k)
            if got and got[1]:
                rows.append(f"<tr><td>+{k} min</td>" + _skp_cells(preskoceni.clock(got[0], now), got[1],
                                                                  (got[1] / ref_mc - 1) if ref_mc else None) + "</tr>")
    if mv:
        for k, at, price, mc, chg in mv["steps"]:
            if price is not None:   # a row measured before 10.11. has no +5/+10/+15 until it is measured again
                rows.append(f"<tr><td>+{k} min</td>" + _skp_cells(preskoceni.clock(at, now, sec=False), mc, chg) + "</tr>")
        if mv["hi"]:
            at, _, mc, chg = mv["hi"]
            rows.append("<tr><td>Najviše u 60\u00a0min</td>"
                        + _skp_cells(preskoceni.clock(at, now, sec=False) if at else None, mc, chg) + "</tr>")
    if live_ts:
        ref = None
        if mv:
            ref = mv["poziv"][0] if poziv else mv["odluka"][0]
        chg = (live["price"] / ref - 1) if (ref and live.get("price")) else None
        if chg is None and ref_mc and live.get("mcap"):
            chg = live["mcap"] / ref_mc - 1
        rows.append('<tr class=ap-now><td>Sada</td>' + _skp_cells(preskoceni.clock(live_ts, now), live.get("mcap"), chg)
                    + "</tr>")
    b.append(f'<table class="ap-mk ap-skt">{"".join(rows)}</table>')
    d = _SKIP_DOT.get(v["kind"], "")
    # the verdict is measured from the decision (kol/preskoceni), the table from the call: said, so "+46 %" in the
    # table and "najviše +35 %" here do not look like two answers to one question
    detail = f'od preskoka: {v["detail"]}' if (poziv and v["kind"] in ("miss", "ok")) else v["detail"]
    b.append(f'<p class=ap-skp-v>{cat(dot(d, v["word"]), " · ", detail)}</p>')
    if mv and p.get("ver") is None:
        b.append("<p class=ms-hint>Izmjereno prije nego što se bilježio poziv; cijene od poziva i nakon 5, 10 i "
                 "15 min stižu kad se ponovno izmjeri.</p>")
    elif mv and not poziv:
        b.append("<p class=ms-hint>Cijena u minuti poziva nije poznata, pa su pomaci od trenutka preskoka.</p>")
    elif mv and not mv["supply"]:
        b.append("<p class=ms-hint>Supply tokena nije poznat, pa su tu samo pomaci cijene.</p>")
    elif not mv and (seen_mc or samples):
        b.append("<p class=ms-hint>Market cap iz trenutka odluke i naših živih uzoraka (DexScreener); točne svijeće "
                 "po minutama dolaze kad se izmjere.</p>")
    if post_url and owner:
        b.append(f'<p><a href="{esc(post_url)}" target=_blank rel=noopener>{esc(post_words)} ↗</a></p>')
    b.append(link)
    return "".join(b)


def _dnevnik_row(e, owner=True):
    """One decision as the shared row (10.11., maketa): the token; under it what happened as a word after a dot
    (kupio / prodao / preskočio / nije prošlo), the money it was (pravi novac / probno / demo) and on whose signal,
    the reason, and for a decision without a buy whether it should have bought (aplog 'trebao': True = every rule
    passed and the order failed; False = a rule said no, which is the correct behaviour); on the right the amount
    (or a sale's result) and when. The row opens the token pop-up. The owner reads the reason as written (aplog
    scrubs addresses and keys from it); an invited viewer gets its short word only (aplog: "anything public shows
    why_short"), never a route's raw error text."""
    kind = e.get("kind")
    word, d = KIND_HR.get(kind, (str(kind or "?"), ""))
    tok = e.get("token") or ""
    sell = e.get("side") == "sell"
    tag = "demo" if e.get("stage") == "demo" else ("pravi novac" if e.get("mode") == "live" else "probno")
    value, vt, amount = None, None, None
    if e.get("sol"):
        amount = redak.sol(e["sol"], 3)
    if kind == "prodao" and e.get("pnl_pct") is not None:   # percent units (12.4 = +12.4 %), like cost_pct elsewhere
        value, vt = redak.pct(e["pnl_pct"], 1), redak.tone(e["pnl_pct"])
    else:
        value, amount = amount, None
    lines = [cat(dot(d, word), tag, amount, f'signal: {_skip_src(e["source"])}' if e.get("source") else None, sep=" · ")]
    why = (e.get("why") or e.get("why_short")) if owner else e.get("why_short")
    if why:
        lines.append(str(why)[:180])
    should = None
    if kind in ("preskocio", "nije_proslo") and e.get("trebao") is not None:
        if sell:   # a sale that keeps failing: the bot tries again, nothing for the owner to decide
            should = raw("Trebao je prodati: da. Prodaja nije prošla, bot pokušava ponovno.") if e["trebao"] else None
        else:
            should = raw("<b>Trebao je kupiti: da.</b> Sva pravila su prošla, ali nalog nije." if e["trebao"] else
                         "Trebao je kupiti: ne, pravilo je reklo ne.")
    link = (raw(f'<a href="https://solscan.io/tx/{quote(str(e["sig"]))}" target=_blank rel=noopener>Solscan ↗</a>')
            if e.get("sig") else None)
    tail = cat(should, link, sep=" · ")
    if tail:
        lines.append(tail)
    ts = e.get("ts") or 0
    r = _prow(tok, name=e.get("symbol") or (short(tok) if tok else word), reason=cat(*lines, sep=raw("<br>")),
              value=value, value_tone=vt, sub=redak.ago(ts),
              title=f'{time.strftime("%d.%m. %H:%M:%S", time.gmtime(ts))} UTC')
    return raw(r.replace('class="ms-row', 'class="ms-row ap-wrap', 1))


def dnevnik_inner(tcon, cfg, now=None, owner=True):
    """The open log: first the skipped buys (why, and what the price did after), then when the trade process last
    reported and one row per decision, newest first. Every part is a top-level element, so the 1-s refresh swaps
    only the rows that changed. Without trade.aplog: the order list (log_html)."""
    now = now or time.time()
    rows = dnevnik_data(tcon, now)
    if rows is None:
        return log_html(tcon, cfg)
    beat = cfg.get("heartbeat") or 0
    alive = f"Autopilot se zadnji put javio {redak.ago(beat)}" if beat else "Autopilot se još nije javio"
    head = f'<p class=ms-hint>{esc(alive)}. Svaki redak je jedna odluka: što je vidio, što je napravio i zašto.</p>'
    if not rows:
        return head + '<p class=ms-hint>Još nema nijedne odluke. Čim Autopilot vidi prvi signal, pojavi se ovdje.</p>'
    # 10.11. (Jure): first, right under the one-line summary, why each skipped buy was skipped and what it did after
    box = _safe("preskočeni", skip_box, tcon, cfg, now, owner)
    return (box + '<h3 class=ap-sub><span>Sve odluke</span></h3>' + head
            + "".join(_dnevnik_row(e, owner) for e in rows[:LOG_ROWS]))


def dnevnik_fragment(user):
    """GET /pravi-trade/dnevnik: the open log, same access as the page; its one-line summary rides along."""
    tcon = _tcon()
    try:
        if not settings.can_view(tcon, user):
            return None
        try:
            inner = dnevnik_inner(tcon, _cfg(tcon), owner=settings.is_owner(user))
            line = dnevnik_line(tcon)
        except Exception as e:  # noqa: BLE001 - the box keeps its last rows and greys out (POLL_JS) instead of a 500
            print(f"autopilot: dnevnik nije složen: {type(e).__name__}: {e}", flush=True)
            return '<p class=mut>Dnevnik se trenutno ne može učitati. Pokušavam ponovno.</p>'
        return inner + f'<span hidden data-meta="#ap-dn-sum">{esc(line)}</span>'
    finally:
        tcon.close()


def log_html(tcon, cfg):
    """The last orders, newest first: the technical record (/pravi-trade/log, opened from the log section), and the
    log itself while trade/aplog.py is not there."""
    now = time.time()
    beat = cfg.get("heartbeat") or 0
    alive = f"Trade proces javio se {esc(ago(beat)[0])}" if beat else "Trade proces se još nije javio"
    head = (f'<p class=mut style="margin:0 0 6px">{alive} · osvježeno '
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
        items.append(f'<p class=mut style="margin:0 0 6px">Starije od 24 h: {len(older)} naloga ({esc(kinds)}), '
                     f'zadnji {esc(ago(older[0][0])[0])}; probno = bez pravog novca, preskočeno = bot nije kupio (limit, rug, '
                     'likvidnost…).</p>')
    for ts, tok, side, mode, st, ain, aout, err, why, sig, sym in recent:
        word = SIDE.get(side, side)
        lab, css = STATUS.get(st, (st, ""))
        lam = ain if side == "buy" else aout
        sol = f" {lam / executor.LAMPORTS:.4f} SOL" if lam and side in ("buy", "rent") or (lam and side == "sell" and st in ("ok", "dry")) else ""
        link = (f' · <a href="https://solscan.io/tx/{esc(sig)}" target=_blank rel=noopener>Solscan ↗</a>' if sig else "")
        note = esc((err or why or "")[:140])
        items.append(f'<div class=ap-pos{_pop(tok)}><div class=r><span>{word} {_tok(tok, sym) if tok else ""}'
                     f'{esc(sol)}</span><span>{_mode_tag(mode)}'
                     f'<span class=ap-tag><i class="ap-dot {css}"></i>{esc(lab)}</span></span></div><div class=mut>{esc(ago(ts)[0])}{link}'
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


# The page's one poller. A box with data-src is fetched only while every section around it is open and the tab is
# visible: data-every seconds apart (1 s for the positions and the open log, HEAD_EVERY_S for the header + chart), a
# data-lazy box for the first time when its section opens, data-every=0 once. One pass at a time (9.11. 23:10): a
# tick that finds the previous pass still waiting for the server is skipped; a failed box is retried after 3 s.
POLL_JS = ("<script>(()=>{if(window.apTick)return;const st=new WeakMap();"
           "function stale(box,on){box.style.opacity=on?'.55':'';box.title=on?'nema svježih podataka':''}"
           "function due(box,now){for(let d=box.closest('details');d;d=d.parentElement&&d.parentElement.closest('details'))if(!d.open)return false;"
           "const s=st.get(box);if(!s){if('lazy' in box.dataset)return true;st.set(box,{t:now,ok:true});return false}"
           "const ev=+box.dataset.every||0;return s.ok?ev>0&&now-s.t>=ev*1000-50:now-s.t>=3000}"
           "async function one(box,now){const s={t:now,ok:false};st.set(box,s);"
           "const c=new AbortController(),to=setTimeout(()=>c.abort()," + str(POP_TIMEOUT_MS) + ");"
           "try{const r=await fetch(box.dataset.src,{cache:'no-store',signal:c.signal});if(!r.ok){stale(box,true);return}const h=await r.text();stale(box,false);"
           "s.ok=true;if(window.apPatch(box,h)===false){s.ok=false;s.t=now-2500}}catch(e){stale(box,true)}finally{clearTimeout(to)}}"
           "let run=false;async function f(){if(run||document.visibilityState!=='visible')return;run=true;"
           "try{const now=Date.now();for(const box of document.querySelectorAll('[data-src]'))if(due(box,now))await one(box,now)}finally{run=false}}"
           f"window.apTick=f;setInterval(f,{LOG_EVERY_S * 1000});document.addEventListener('visibilitychange',f)}})()</script>")


def _log_section(tcon, cfg):
    """"Dnevnik odluka" (maketa): one row right under the chart with the one-line summary of the last 24 h (it may
    take two lines, CSS #dnevnik); the rows are fetched when it is opened and every LOG_EVERY_S seconds while it
    stays open."""
    try:
        line = dnevnik_line(tcon)
    except Exception:  # noqa: BLE001 - a missing table must not cost the page its log section
        line = ""
    box = (f'<div id=ap-dnevnik data-src=/pravi-trade/dnevnik data-every={LOG_EVERY_S} data-lazy>{LOADING}</div>'
           '<p class=ms-hint><u data-pop="/pravi-trade/log" style="cursor:pointer">Tehnički zapis naloga</u> '
           '(svaki pokušaj kupnje i prodaje s rutom i greškom)</p>')
    return _sec("Dnevnik odluka", raw(f"<span id=ap-dn-sum>{esc(line)}</span>"), box, sid="dnevnik")


# 9.11. (Jure, mobitel): the section headers needed 5-6 taps to open, sometimes closed instead. Their <summary> is
# display:flex, and mobile Safari/Chrome drop or double-fire taps on such summaries. The tap is handled by hand:
# one tap = one toggle, and open sections are remembered for the page's reloads (sessionStorage).
# 10.11. (Jure: "kad učitam stranicu, neke kartice su automatski otvorene; nek su sve zatvorene za početak"): the open
# rows are remembered only while the page is open (the 1-s refresh keeps them open), not across loads; a link with
# #anchor (the answer of a form) still opens its section. PATCH_JS leaves a list alone while a finger is on the
# screen and 1.2 s after (was 0.4 s), so a row never changes under a tap on a slow phone.
# 10.11.: handled from the document, so sections that arrive later (the recommendations, fetched when opened) get it
# too; only sections with an id are remembered; a link to a section (#limiti after saving) opens it; opening a
# section wakes the poller, so its content is there at once. 10.11. (maketa): a link inside the page ("Dovrši 3/4"
# in the state line, #postavljanje) opens its section too (hashchange), not only a link that loads the page.
TOGGLE_JS = ("<script>(()=>{const Q='details.ap-sec,details.ap-it,details.ap-pan';let open={};"
             # 10.11. (Jure: "opet piše na vrhu: nije prošlo, već imaš otvorenu poziciju"): the answer of a form is
             # shown once; the address loses ?ok=/?err=, so a reload (or the phone reopening the tab) does not show
             # an old error again as if it were new
             "if(/[?&](ok|err)=/.test(location.search))try{history.replaceState(null,'',location.pathname+location.hash)}catch(e){}"
             "window.apOpen=root=>root.querySelectorAll(Q).forEach(d=>{if(d.id&&d.id in open)d.open=!!open[d.id]});window.apOpen(document);"
             "const reveal=()=>{for(let t=location.hash.length>1&&document.getElementById(location.hash.slice(1));t;t=t.parentElement)if(t.matches&&t.matches('details'))t.open=true};"
             "reveal();addEventListener('hashchange',reveal);"
             "document.addEventListener('click',e=>{const s=e.target.closest('summary');if(!s||e.target.closest('a,button,input,select,.tip'))return;"
             "const d=s.parentElement;if(!d.matches(Q))return;e.preventDefault();"
             "d.open=!d.open;if(d.id)open[d.id]=d.open;"
             "if(d.open&&window.apTick)window.apTick()});"
             "if(window.apSeen)document.querySelectorAll('[data-src]:not([data-lazy])').forEach(window.apSeen);"
             "if(window.apTick)window.apTick()})()</script>")


# ---------- limits, invites, safety -----------------------------------------------------------------------------

def _limits(cfg, owner):
    """The limits, the second block inside "Pravila" (id=limiti stays the anchor the form returns to). The owner
    gets the form, an invited player the values."""
    head = '<h3 class=ap-sub><span>Limiti</span></h3>'
    if not owner:
        items = "".join(f"<li>{esc(lab)}: <b>{esc(_g(cfg.get(k)) if cfg.get(k) is not None else '–')}</b></li>"
                        for k, (lab, *_rest) in settings.LIMITS.items())
        items += f"<li>SimianX signali: <b>{'uključeni' if cfg.get('simianx') else 'isključeni'}</b></li>"
        return f"<div id=limiti>{head}<ul style='margin:0;padding-left:18px'>{items}</ul></div>"
    fields = "".join(f'<label>{esc(lab)} <input name={k} value="{cfg.get(k, "")}" inputmode=decimal></label>'
                     for k, (lab, *_rest) in settings.LIMITS.items())
    def box(k, c, t):
        if k in settings.LOCKED:   # audit 4.11.: greyed out with the reason, the server ignores it anyway
            return (f'<label class=ap-chk style="opacity:.6"><input type=checkbox disabled> {t}'
                    f'<br><span class=mut>{esc(settings.LOCKED[k])}</span></label>')
        return f'<label class=ap-chk><input type=checkbox name={k} value=1{c}> {t}</label>'
    extra = (box(k="follow_paper", c=" checked" if cfg.get("follow_paper") else "",
                 t="prati i demo strategiju bota (uz influencere i wallete gore)")
             + box(k="use_pump", c=" checked" if cfg.get("use_pump", True) else "",
                   t=f"ako Jupiter ne prođe, probaj preko PumpPortala (naknada {_g(pumpportal.FEE_PCT)} %)")
             + box(k="simianx", c=" checked" if cfg.get("simianx") else "",
                   t="kupuj i na SimianX signale „kupi”, s njihovim stopom i ciljem (uključi tek kad se pokažu dobri u demu)"))
    inner = (f'<form method=post action=/pravi-trade/limits class=ap-lim style="display:block">{fields}{extra}'
             '<p class=mut>Ulog vrijedi za svako praćenje. Kad se dosegne dnevna potrošnja, nove automatske kupnje '
             'staju do ponoći (po zagrebačkom vremenu); tvoje ručne kupnje (brza kupnja, dokup, DCA) idu dalje. Kad se '
             'dosegne dnevni gubitak, staju sve kupnje do ponoći. Prodaje idu uvijek. Dnevni gubitak uključuje i naknade '
             'neuspjelih pokušaja.</p><button>Spremi limite</button></form>')
    return f"<div id=limiti>{head}{inner}</div>"


def _invites(tcon):
    inv = {u.lower() for u in settings.invited(tcon)}
    boxes = "".join(f'<label style="display:block;margin:4px 0"><input type=checkbox name=u value="{esc(u)}"'
                    f'{" checked" if u.lower() in inv else ""}> {esc(u)}</label>'
                    for u in store.users() if not settings.is_owner(u))
    inner = ('<form method=post action=/pravi-trade/invite style="display:block"><p class=mut style="margin-top:0">Pozvani vide '
             'stanje, pozicije i koga bot prati. Ne mogu ništa mijenjati ni trošiti tvoj novac; „Kupi i ti” im otvara '
             f'Jupiter u <b>njihovom</b> walletu.</p>{boxes or "<p>Nema drugih igrača.</p>"}<button>Spremi tko vidi</button></form>')
    return _sec("Tko vidi stranicu", f"{len(inv)} pozvanih", inner, sid="pozivnice")


def _safety():
    items = ("Pravi novac ide samo kad je Autopilot uključen <b>i</b> u Renderu stoje ključ i TRADE_LIVE=1. Ključ nikad "
             "nije u kodu ni na ovoj stranici.",
             "U walletu drži samo iznos kojim bot smije trgovati.",
             "Dnevni limit potrošnje i dnevni gubitak zaustavljaju nove kupnje do ponoći.",
             f"U walletu uvijek ostaje barem {_g(executor.RESERVE_FLOOR_SOL)} SOL (i {_g(executor.SELL_COST_SOL)} SOL po "
             "otvorenoj poziciji) za mrežne naknade prodaje.",
             "Swap se ne radi ako je trošak (klizanje + naknada) veći od limita.",
             "Rute redom: Jupiter → Jupiter Ultra → PumpPortal (ako je uključen). Na sljedeću se ide samo kad swap sigurno "
             "nije prošao, da se ništa ne kupi dvaput.",
             "Neuspjela prodaja se ponavlja: nakon 5 s, 10 s, 20 s… najviše svakih 10 min, dok ne prođe.",
             "Ulazi se samo dok je signal svjež; rugani tokeni, lažni poolovi i premala likvidnost se preskaču.",
             "Preporuke su izračun iz povijesti, ne obećanje: memecoini mogu pasti na nulu.",
             "Prekidač mijenja samo vlasnik; pozvani samo gledaju.")
    return _sec("Kako je zaštićeno", "", "<ul style='margin:0;padding-left:18px'>"
                + "".join(f"<li>{t}</li>" for t in items) + "</ul>", sid="zastita")


def _wallet_row(tcon, owner, setup=None):
    """"Wallet i uplata" under "Još" (maketa: "1,842 SOL i 25 USDC · ytiQ…tiRAD"): the address with copy and Solscan,
    what is in the wallet, the money put in and the result against it, the rate of 1 SOL, and for the owner the
    setup steps (id=postavljanje: "Dovrši 3/4" in the state line opens it). Balances come from the value history
    (no network on a page view); without it from the owner's setup check (which read the wallet anyway)."""
    setup = setup or {}
    addr = _addr(tcon)[0]
    try:
        s = equity_data(tcon)["summary"]
    except Exception:  # noqa: BLE001
        s = {}
    sol_b = s.get("sol") if s.get("value_sol") is not None else setup.get("sol")
    usdc = s.get("usdc") if s.get("value_sol") is not None else setup.get("usdc")
    have = " i ".join(x for x in (redak.sol(sol_b, 3) if sol_b is not None else "",
                                  f"{_fiat(usdc)} USDC" if usdc else "") if x)
    meta = " · ".join(x for x in (have, short(addr) if addr else "još nije postavljen") if x)
    facts = []
    if have:
        facts.append(f"U walletu: {have}.")
    net, pnl = s.get("net_in_sol"), s.get("pnl_sol")
    if net is not None:
        facts.append(cat(f"Uplaćeno {redak.sol(net, 3)}",
                         cat(", rezultat ", _signed(pnl), f" ({redak.pct(100.0 * pnl / net, 1)})" if net and net > 0 else "")
                         if pnl is not None else None,
                         f", u otvorenim pozicijama {redak.sol(s['tokens_sol'], 3)}" if s.get("tokens_sol") else None, "."))
    if s.get("sol_usd"):
        r = _rates(s)
        facts.append(f"1 SOL = {_fiat(r['sol_usd'])} $" + (f" · {_fiat(r['sol_usd'] * r['usd_eur'])} €" if r.get("usd_eur") else ""))
    inner = (f"<p>{_addr_html(addr)}</p>" + "".join(f"<p class=mut>{redak.h(f)}</p>" for f in facts)
             + setup.get("html", ""))
    value = f'{setup["done"]}/{setup["total"]}' if setup and not setup.get("ready") else None
    return _sec("Wallet i uplata", meta, inner, sid="postavljanje", value=value)


def _with_toggle(html_body):
    return html_body + TOGGLE_JS


def page(qs, user):
    """10.11. (Jure: "Ostalo mi se sviđa", prijedlog 3.4 and the mock-up audit/2026-11-10/makete/autopilot.html, in
    the order of audit/2026-11-10/dizajn.md section 2): the header (title with the owner's switch, one state line,
    the wallet's value as one big number) with the chart; "Dnevnik odluka" as one row; "Otvorene pozicije" as rows
    with "Zatvorene" and the red "Prodaj sve i isključi" under them; "Kako trguje" (Koga prati, Pravila, Kupi ručno);
    "Još" at the bottom for the rarely used parts (who calls what now, what to buy now, the tool's recommendations,
    Wallet i uplata with the setup steps, who sees the page, how it is protected). One column (ms-page); a closed row
    fetches nothing until it is opened; every part is built behind its own try (_safe), so one broken statistic
    never costs the switch."""
    tcon = _tcon()
    try:
        if not settings.can_view(tcon, user):
            return (TITLE, f'<div class="ap ms-page">{_title()}<p class=ms-hint>Ova stranica je samo za pozvane. '
                    'Ako želiš pristup, javi se vlasniku aplikacije.</p></div>' + CSS)
        owner = settings.is_owner(user)
        cfg = _cfg(tcon)
        msg = ""
        if qs.get("err"):
            msg = f'<p class="ap-w bad"><b>Nije prošlo:</b> {esc(qs["err"])}</p>'
        elif qs.get("ok"):
            msg = f'<p class="ap-w ok">{esc(qs["ok"])}</p>'
        # 10.11. (Jure: "dodao sam DCA, a nigdje se nije vidjelo"): the answer of a form also as a toast over the page,
        # where the eye is after the tap (the line in the header is at the top of a long page); an error stays until
        # tapped, a confirmation goes after 6 s
        toast = ""
        if qs.get("err") or qs.get("ok"):
            bad = bool(qs.get("err"))
            toast = (f'<div class="ap-toast {"bad" if bad else "ok"}" role={"alert" if bad else "status"} '
                     f'onclick="this.remove()">{"<b>Nije prošlo:</b> " if bad else ""}{esc(qs.get("err") or qs.get("ok"))}'
                     '<span class=ap-toast-x aria-hidden=true>×</span></div>'
                     + ("" if bad else "<script>setTimeout(()=>{const t=document.querySelector('.ap-toast');if(t)t.remove()},6000)</script>"))
        prefill = (qs.get("ekipa") or "") if isinstance(qs, dict) else ""
        setup = {}
        if owner:   # the wallet's setup steps: inside "Wallet i uplata"; the state line says "Dovrši 3/4" until ready
            def _mk_setup():
                addr, key_addr, saved = _addr(tcon)
                n_open = tcon.execute("SELECT COUNT(*) FROM positions WHERE status='open'").fetchone()[0]
                return _setup(tcon, cfg, addr, key_addr, saved, _balance(addr), _usdc(addr), n_open)
            setup = _safe("postavljanje", _mk_setup, fallback={})
        con = store.connect()
        try:
            copy.ensure(con)
            b = [CSS, '<div class="ap ms-page">', _float_nav(owner), toast,
                 _safe("zaglavlje", _head, tcon, cfg, con, owner, msg,
                       fallback=_title(owner, cfg.get("on")) + msg
                       + '<p class="ap-w bad">Stanje walleta se trenutno ne može učitati.</p>'),
                 _safe("sazetak", _summary_card, tcon, owner),
                 _safe("kupnja", _buy_now_card, cfg, owner),
                 _safe("mcp", _mcp_requests, tcon, owner),
                 setup.get("warn", ""),
                 _group(_safe("dnevnik", _log_section, tcon, cfg), first=True),
                 _safe("pozicije", _positions, tcon, not owner, owner, cfg.get("sell_req"), cfg),
                 _h2("Kako trguje"),
                 _group(_safe("praćenja", _follows, con, owner, settings.raw(tcon), prefill),
                        _safe("pravila", _rules, tcon, cfg, owner),
                        _safe("pregled", _review_section, tcon, owner),
                        _safe("zastavice", _flags_section, tcon, con, owner))]
        finally:
            con.close()
        b += [_h2("Još", sid="jos"),
              _group(_safe("grok", _mcp_section, tcon, owner), _safe("prijedlozi", _suggest_section, tcon, owner),
                     _callers_section(cfg, owner), _ideas_section(cfg, owner), _recs_section(),
                     _safe("wallet", _wallet_row, tcon, owner, setup),
                     _safe("pozivnice", _invites, tcon) if owner else "", _safety()),
              '</div>', POP_CSS, POP_HTML, PATCH_JS, POP_JS, POLL_JS, JS]
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
                w.append(("bad", f"Opasno malo SOL-a: {redak.sol(bal, 4)}. Za prodaju {n_open_live} otvorenih pozicija "
                                 f"treba barem {redak.sol(reserve, 4)} za mrežne naknade. Uplati SOL u wallet."))
            elif bal < need:
                w.append(("warn", f"Premalo SOL-a za novu kupnju: stanje {redak.sol(bal, 4)}, treba {redak.sol(need, 4)} "
                                  f"(ulog {_g(cfg['size_sol'])} + naknade i depozit {_g(executor.BUY_OVERHEAD_SOL)} + "
                                  f"rezerva za prodaju {redak.num(executor.reserve_sol(cfg, n_open_live + 1), 4)}). Bot neće "
                                  "kupovati, prodaje rade."))
    mode = "live" if executor.is_live(cfg) else "dry"
    start = executor._day_start(now, cfg.get("day_tz"))
    spent = tcon.execute("SELECT COALESCE(SUM(sol_in),0) FROM positions WHERE mode=? AND opened_ts>=? AND status IN "
                         "('open','closed','pending')", (mode, start)).fetchone()[0]
    if spent >= cfg["max_sol_per_day"] - 1e-9:
        w.append(("warn", f"Dnevni limit potrošnje je dosegnut ({redak.sol(spent, 3)}): nove kupnje tek nakon ponoći (Zagreb)."))
    if executor.day_pnl(tcon, now, mode, cfg.get("day_tz")) <= -cfg["max_loss_day"]:
        w.append(("bad", f"Dnevni gubitak je dosegnuo −{_g(cfg['max_loss_day'])} SOL: nove kupnje stoje do ponoći (Zagreb). Uključene su i naknade neuspjelih pokušaja."))
    recent = tcon.execute("SELECT code, error, prio_lamports, status FROM orders WHERE ts>=? ORDER BY id DESC LIMIT 30",
                          (now - 1800,)).fetchall()
    landed_fail = sum(1 for c, *_ in recent if c in (-1000, -1005, -1006, -2000))
    prio = [p for _, _, p, _ in recent if p]
    if landed_fail >= 2:
        w.append(("warn", f"Mreža je zagušena: {landed_fail} transakcija u zadnjih 30 min nije stiglo u blok. Bot "
                          "ponavlja automatski, ali ulazi mogu kasniti."))
    if prio and max(prio[:5]) >= 1_000_000:
        p = max(prio[:5]) / executor.LAMPORTS
        w.append(("warn", f"Mreža je zagušena: naknada za prioritet je sad oko {redak.sol(p, 4)} po swapu, to je "
                          f"{redak.pct(100 * p / cfg['size_sol'], 1, sign=False)} uloga od {_g(cfg['size_sol'])} SOL."))
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
        w.append(("warn", f"Ulog {_g(cfg['size_sol'])} SOL je malen: mrežne naknade i depozit (~0,003 SOL po kupnji, "
                          "depozit se vrati) su velik dio uloga."))
    if not copy.follows(con, settings.LEAGUE_USER) and not cfg.get("follow_paper") and not cfg.get("simianx"):
        w.append(("warn", "Bot nikoga ne prati: neće ništa kupiti dok ne dodaš influencera ili wallet."))
    # nothing to say = nothing shown (the page stays clean); otherwise one short line per problem. 10.11. (Jure: "čista,
    # minimalistička"): the line's colour says how bad it is, no emoji in front
    return "".join(f'<p class="ap-w {lv}">{esc(t)}</p>' for lv, t in w)



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
        if path == "/pravi-trade/sl":   # 10.11. (Jure): the default stop for new entries (owner only)
            v = int(float(form.get("sl") or 0))
            if v not in settings.SL_CHOICES:
                return f"{BACK}?err={qq('zadani stop: ' + ', '.join(f'−{x}' for x in settings.SL_CHOICES) + ' %')}#stop"
            settings.put(tcon, "sl_default", v, user)
            return f"{BACK}?ok={qq(f'Zadani stop za nove ulaze: −{v} %.')}#stop"
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
            # 10.11.: "id" may name every lot of one token ("12,15"): each lot is its own swap, all with this share
            ids = [str(int(x)) for x in str(form.get("id") or "0").split(",") if x.strip()][:20]
            frac = float(form.get("frac") or 1)
            if not 0 < frac <= 1:
                raise ValueError("udio mora biti između 0 i 100%")
            ids = [i for i in ids if tcon.execute("SELECT 1 FROM positions WHERE id=? AND status='open'", (int(i),)).fetchone()]
            if not ids:
                raise ValueError("ta pozicija nije otvorena")
            req = dict(settings.raw(tcon).get("sell_req") or {})
            for pid in ids:
                req[pid] = frac
            settings.put(tcon, "sell_req", req, user)
            return f"{BACK}?ok={qq(f'Prodaja {frac:.0%} poslana, za nekoliko sekundi je u tablici.')}#pozicije"
        if path in ("/pravi-trade/asok", "/pravi-trade/asno", "/pravi-trade/asapply"):   # 10.11.: an assistant's note
            from ui import assistnotes
            nid, note = int(form.get("id") or 0), (form.get("note") or "").strip()
            if path.endswith("asapply"):
                st, words = assistnotes.apply(tcon, nid, note)
                return f"{BACK}?ok={qq(words)}#prijedlozi"
            assistnotes.decide(tcon, nid, "prihvaćeno" if path.endswith("asok") else "odbijeno", note)
            return f"{BACK}?ok={qq('Prijedlog prihvaćen.' if path.endswith('asok') else 'Prijedlog odbijen.')}#prijedlozi"
        if path in ("/pravi-trade/sugok", "/pravi-trade/sugno"):   # 10.11.: an assistant's caller weight
            from ui import mcpdata
            ok = path.endswith("ok")
            if not mcpdata.decide_suggestion(tcon, int(form.get("id") or 0), "approved" if ok else "rejected"):
                raise ValueError("taj prijedlog više ne čeka")
            return f"{BACK}?ok={qq('Prijedlog odobren.' if ok else 'Prijedlog odbijen.')}#prijedlozi"
        if path == "/pravi-trade/mcpkey":   # 10.11. (Jure: "napravi mcp key"): a new key, the old one stops
            from ui import mcpapi
            mcpapi.new_key(tcon, user)
            print(f"pravi trade: {user} je napravio novi MCP ključ", flush=True)
            return f"{BACK}?ok={qq('MCP ključ je napravljen. Kopiraj ga ispod i upiši u Groka.')}#mcp"
        if path == "/pravi-trade/mcpkeyoff":
            settings.put(tcon, "mcp_key", "", user)
            return f"{BACK}?ok={qq('Pristup za Groka je ugašen.')}#mcp"
        if path == "/pravi-trade/mcpno":   # 10.11.: the owner turns down a request of the MCP server
            from ui import mcpapi
            if not mcpapi.decide(tcon, str(form.get("id") or ""), "rejected", "vlasnik odbio"):
                raise ValueError("taj zahtjev više ne postoji")
            return f"{BACK}?ok={qq('Zahtjev odbijen.')}"
        if path == "/pravi-trade/reviewback":   # 10.11.: "Vrati" a follow the hourly review paused
            from league import followreview
            lcon = store.connect()
            try:
                row = followreview.restore(lcon, tcon, int(form.get("id") or 0), user)
            finally:
                lcon.close()
            print(f"pravi trade: {user} je vratio praćenje {row.get('label')}", flush=True)
            return f"{BACK}?ok={qq('Praćenje ' + str(row.get('label') or '') + ' je ponovno uključeno.')}#pregled-inf"
        if path == "/pravi-trade/flag":   # 10.11. (Phase 0): a flag of the profitability plan, owner only
            from league import flags as lflags
            name, mode = str(form.get("name") or ""), str(form.get("mode") or "")
            if name not in settings.FLAGS:
                raise ValueError("nepoznata zastavica")
            st = settings.flag_state(tcon)[name]
            lcon = store.connect()
            try:
                paper = lflags.paper_result(lcon, st["since"]) if st["mode"] == "paper" else None
            finally:
                lcon.close()
            settings.set_flag(tcon, name, mode, user, paper=paper)
            print(f"pravi trade: {user} je zastavicu {name} postavio na {mode}", flush=True)
            return f"{BACK}?ok={qq(f'Zastavica {name}: {FLAG_WORDS.get(mode, mode)}.')}#fl-{name}"
        if path == "/pravi-trade/triggerprobe":   # 10.11. (Jure: "da, v1"): Jupiter Trigger step 1, no money
            settings.put(tcon, "trigger_probe_req", int(time.time()), user)
            return f"{BACK}?ok={qq('Proba Jupiter Triggera poslana trade procesu; rezultat je pod Pravila za nekoliko sekundi.')}#trigger"
        if path == "/pravi-trade/dca":   # 10.11. (Jure): DCA, dokup na padu s ručnom granicom
            return _post_dca(None, tcon, form, user)
        if path == "/pravi-trade/dcadel":
            return _post_dcadel(tcon, form, user)
        if path == "/pravi-trade/limitdel":   # 10.11.: cancel a buy order at a market cap
            return _post_limitdel(tcon, form, user)
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
                if kind == "kol":      # 10.11.: '@Ansem' typed by hand is the account kol.db knows as 'ansem'
                    target = _canonical(target)
                elif kind == "ekipa":
                    target = ", ".join(_canonical(m) for m in copy.members_of(target))
                tp = form.get("tp", "") or (f"{_cfg(tcon).get('tp_default', 15)}%" if form.get("exit") == "tpsl" else "")
                if form.get("exit") == "podaci":   # 9.11.: the tool picks the pair at every entry (kol/tpsl.py)
                    tp = ""
                max_mcap, max_runup = _parse_usd(form.get("max_mcap")), _parse_pct(form.get("max_runup"))
                if form.get("exit") == "podaci" and max_runup is None:   # 10.11.: the data exit is measured for an
                    max_runup = copy.DATA_MAX_RUNUP                       # entry before the price has run (10 %)
                if kind == "ekipa":   # the crew defaults (Jure 9.11.); a KOL follow takes them only when filled in
                    max_mcap = EKIPA_MAX_MCAP if max_mcap is None else max_mcap
                    max_runup = EKIPA_MAX_RUNUP if max_runup is None else max_runup
                ex_mode = form.get("exit", "")
                if kind in ("ekipa", "kol") and ex_mode == "mirror":   # 9.11. (audit P74): "prodaj kad on proda" has no
                    ex_mode = ""                                         # meaning for a call; the default (Smart sell) instead
                # 9.11. (audit P10/P17/P19): "moj TP/SL" without a stop typed in gets the default stop. 10.11. (Jure:
                # zadani stop se mijenja na stranici): stored empty, league/copy.run_once puts the owner's default
                # stop (copy.default_sl) on each entry, so a change under "Pravila" holds for this follow too
                sl = (form.get("sl") or "").strip()
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
                copy.follow(con, settings.LEAGUE_USER, "ekipa", target, "", 25, 5, "tpsl", tp, "",   # the default stop at entry
                            max_mcap=EKIPA_MAX_MCAP, max_runup=EKIPA_MAX_RUNUP, min_callers=1)
                con.commit()
                return f"{BACK}?ok={qq(f'Bot prati ekipu ({len(mem)} računa): ulaz čim prvi od njih objavi, do MC $1M, ne ako je već +25 %, stop {_sl0(_cfg(tcon))}.')}#pratim"
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
                if (form.get("at") or "").strip():   # 10.11.: a buy order at a market cap
                    return _post_limit(con, tcon, form, user)
                return _post_buy(con, tcon, form, user)
            if path == "/pravi-trade/exit":
                return _post_exit(con, tcon, form)
            if path == "/pravi-trade/mcpok":
                return _post_mcp_ok(con, tcon, form, user)
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
            if path == "/pravi-trade/followexit":   # 10.11. (Jure): this follow's own TP / SL
                fid = int(form.get("id") or 0)
                ex = copy.set_exit(con, settings.LEAGUE_USER, fid, form.get("tp", ""), form.get("sl", ""))
                n = 0
                if form.get("open") == "1":   # also on the follow's open positions (one level per token, _group_exit)
                    cfg = _cfg(tcon)
                    toks = [r[0] for r in con.execute("SELECT DISTINCT token FROM trades WHERE user=? AND follow_id=? "
                                                      "AND status='open'", (settings.LEAGUE_USER, fid))]
                    for tok in toks:
                        try:
                            _group_exit(con, tcon, tok, ex.get("tp", ""), ex.get("sl") or _sl0(cfg), cfg)
                            n += 1
                        except ValueError as e:
                            print(f"pravi trade: izlaz praćenja na otvorenoj poziciji nije postavljen ({e})", flush=True)
                words = copy.describe_exit(ex, copy.default_sl(settings.LEAGUE_USER))
                tail = f" Primijenjeno i na {n} otvorenih pozicija." if n else ""
                return f"{BACK}?ok={qq(f'Izlaz praćenja: {words}.{tail}')}#prati-{fid}"
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


def _lot_weights(tcon, lots, cfg):
    """{demo trade id: SOL put in} of a token's lots: the real position's stake, else the manual stake asked for on
    the page (settings manual_size, the real buy may still be on its way), else the default stake."""
    ids = [t["id"] for t in lots]
    real = dict(tcon.execute(f"SELECT league_id, SUM(sol_in) FROM positions WHERE league_id IN ({','.join('?' * len(ids))}) "
                             "AND status IN ('open','pending') GROUP BY league_id", ids).fetchall()) if ids else {}
    asked = settings.raw(tcon).get("manual_size") or {}
    return {i: float(real.get(i) or asked.get(str(i)) or cfg.get("size_sol") or 0.1) for i in ids}


def _group_exit(con, tcon, token, tp, sl, cfg):
    """10.11. (Jure: "ako ima više ulaza, nek izračuna prosječan ulaz, na to doda take profit i onda na cijelu
    poziciju zatvori"): one TP and one SL for every open lot of a token, measured from the average entry (price per
    token over all lots, weighted by the SOL put in each), written as the same price level on every lot, so they all
    close in the same second (league/auto). tp/sl: percent ("40%", "-60%") or MC ("$120k"). Returns
    (rule of the first lot, average entry MC or None, number of lots); one lot = its own entry, as before."""
    from league import auto
    lots = con.execute("SELECT id, entry_px, entry_mcap, auto FROM trades WHERE user=? AND token=? AND status='open' "
                       "ORDER BY id", (settings.LEAGUE_USER, token)).fetchall()
    if not lots:
        raise ValueError("ta pozicija više nije otvorena")
    if len(lots) == 1:
        try:
            old = json.loads(lots[0]["auto"]) if lots[0]["auto"] else {}
        except ValueError:
            old = {}
        rule = auto.set_auto(con, settings.LEAGUE_USER, lots[0]["id"], "tpsl", tp, sl, from_eff=bool((old or {}).get("from_eff")))
        return rule, lots[0]["entry_mcap"], 1
    w = _lot_weights(tcon, lots, cfg)
    avg_px = sum(w.values()) / sum(w[t["id"]] / t["entry_px"] for t in lots)
    k = next((t["entry_mcap"] / t["entry_px"] for t in lots if t["entry_mcap"] and t["entry_px"]), None)
    avg_mc = avg_px * k if k else None
    tp_px, tp_l = auto.parse_level(tp, avg_px, avg_mc, "tp")
    sl_px, sl_l = auto.parse_level(sl, avg_px, avg_mc, "sl")
    if tp_px is None and sl_px is None:
        raise ValueError("upiši barem TP ili SL")
    lab = lambda l, px: (f"{l} od prosjeka" + (f" (MC {_usd_short(px * k)})" if k else "")) if l and l.endswith("%") else l
    rule = {"mode": "tpsl", "tp_px": tp_px, "sl_px": sl_px, "tp": lab(tp_l, tp_px) if tp_px else None,
            "sl": lab(sl_l, sl_px) if sl_px else None, "tp_in": tp or "", "sl_in": sl or "",
            "grp": {"tp": tp or "", "sl": sl or "", "avg_px": avg_px, "avg_mc": avg_mc, "n": len(lots)}}
    for t in lots:
        con.execute("UPDATE trades SET auto=?, auto_state=NULL WHERE id=?", (json.dumps(rule), t["id"]))
    con.commit()
    return rule, avg_mc, len(lots)


def _post_mcp_ok(con, tcon, form, user):
    """The owner approves a request of the MCP server: a buy goes through the owner's manual buy (his last TP / SL),
    a sale through the sell button's request (every lot of the token, that share)."""
    from urllib.parse import quote as qq
    from ui import mcpapi
    rid = str(form.get("id") or "")
    r = next((x for x in mcpapi.pending(tcon) if x.get("id") == rid), None)
    if r is None:
        raise ValueError("taj zahtjev više ne čeka (istekao je nakon 15 min ili je već riješen)")
    if r["side"] == "buy":
        tp, sl = _last_exit(_cfg(tcon))
        try:
            out = _post_buy(con, tcon, {"token": r["token"], "sol": f'{r["amount"]:g}', "exit": "tpsl", "tp": tp, "sl": sl}, user)
        except ValueError as e:
            mcpapi.decide(tcon, rid, "failed", str(e))
            raise
        mcpapi.decide(tcon, rid, "approved", "kupnja poslana")
        return out
    ids = [str(i) for (i,) in tcon.execute("SELECT id FROM positions WHERE token=? AND status='open'", (r["token"],))]
    if not ids:
        mcpapi.decide(tcon, rid, "failed", "pozicija više nije otvorena")
        raise ValueError("ta pozicija više nije otvorena")
    req = dict(settings.raw(tcon).get("sell_req") or {})
    for pid in ids:
        req[pid] = min(1.0, max(0.01, float(r["amount"])))
    settings.put(tcon, "sell_req", req, user)
    mcpapi.decide(tcon, rid, "approved", "prodaja poslana")
    return f"{BACK}?ok={qq('Prodaja poslana, za nekoliko sekundi je u tablici.')}#pozicije"


def _post_exit(con, tcon, form):
    """10.11. (Jure: "za neke tokene bi stavio take profit 30 %, a ne samo 15 %"): the owner's exit of one open
    position. The real position follows its demo trade (run_trade sells when the demo closes), so the TP/SL is
    written on the demo trade (league/auto.set_auto) from the same base as before (copies: the effective entry with
    fee and impact). Empty TP = only the stop; empty SL = the default stop. A data exit's one-hour limit is dropped:
    the owner's own rule holds from now on."""
    from urllib.parse import quote as qq
    from league import auto
    pid = int(form.get("id") or 0)
    row = tcon.execute("SELECT league_id, symbol, token FROM positions WHERE id=? AND status='open'", (pid,)).fetchone()
    if not row:
        raise ValueError("ta pozicija nije otvorena")
    lid, sym, tok = row
    if not lid:
        raise ValueError("ova pozicija nema demo par (demo strategija ili stara pozicija): izlaz joj se ne mijenja ovdje")
    # 10.11. (Jure: više ulaza = prosječan ulaz, TP/SL na prosjek, zatvara cijelu poziciju): _group_exit
    tp = (form.get("tp") or "").strip()
    sl = (form.get("sl") or "").strip() or _sl0(_cfg(tcon))
    rule, avg_mc, n = _group_exit(con, tcon, tok, tp, sl, _cfg(tcon))
    print(f"pravi trade: izlaz {sym or tok[:6]} promijenjen: {_exit_words(rule)} ({n} ulaza)", flush=True)
    # 10.11. (Jure: "kad se postavi izlaz za određenog influencera, neka ostane zapamćen za sljedeću narudžbu, a ne da se
    # uvijek vraća na default"): the TP / SL typed here prefill the next manual order, and a position bought on a
    # follow's signal hands them to that follow, so its next entries get them too
    sl_typed = (form.get("sl") or "").strip()
    settings.put(tcon, "last_exit", {"tp": tp, "sl": sl_typed}, settings.owner())
    note = ""
    fids = {r[0] for r in con.execute("SELECT follow_id FROM trades WHERE user=? AND token=? AND status='open' AND "
                                       "follow_id IS NOT NULL", (settings.LEAGUE_USER, tok))}
    for fid in fids:
        try:
            ex = copy.set_exit(con, settings.LEAGUE_USER, fid, tp, sl_typed)
            f = con.execute("SELECT label, target FROM follows WHERE id=?", (fid,)).fetchone()
            note = f" Zapamćeno i za sljedeće ulaze od {(f[0] or f[1]) if f else 'tog praćenja'}."
        except ValueError:   # the follow was stopped meanwhile
            pass
    return f"{BACK}?ok={qq(f'Izlaz {sym or tok[:6]}: {_exit_words(rule)}.{note}')}#poz-{pid}"


def _gate_now(tcon, sol, token, now=None):
    """The real-money gate (trade/executor.gate_buy) for an owner's buy, asked before the order is written. A manual
    buy is always "one more lot" (add=True, as run_trade.follow_league_once books it). Without an answer from the RPC
    for the balance, every other limit is still checked and run_trade checks the balance as before."""
    cfg = _cfg(tcon)
    live = executor.is_live(cfg)
    now = now or time.time()
    try:
        return executor.gate_buy(tcon, cfg, sol, now, live, token=token, add=True, manual=True)
    except Exception:  # noqa: BLE001 - the RPC for the balance did not answer
        return executor.gate_buy(tcon, cfg, sol, now, live, balance=float("inf"), token=token, add=True, manual=True)


def _owner_buy_rules(lcon, tcon, token, sol, now=None):
    """10.11. (Jure: "Primijeni" na Grokove prijedloge, svaki iza zastavice):
    dca_cap         SOL in this token (open lots + this buy) at most settings "dca_token_cap" (DCA_TOKEN_CAP):
                    live = the buy is refused with the reason; shadow / paper = logged in shadow_decisions.
    require_signal  the owner's own buy always goes through ("ručno mora proći"): a buy without a caller or a tiered
                    wallet behind it is only logged, in every mode but off, so the rule's effect can be read."""
    from league import copy as lcopy, flags as lflags
    now = now or time.time()
    U = settings.LEAGUE_USER
    m = lflags.mode("dca_cap")
    if m != "off":
        cap = float(settings.raw(tcon).get("dca_token_cap") or settings.DCA_TOKEN_CAP)
        held = tcon.execute("SELECT COALESCE(SUM(sol_in), 0) FROM positions WHERE token=? AND status IN ('open','pending')",
                            (token,)).fetchone()[0] or 0.0
        if held + sol > cap + 1e-9:
            why = (f"u tokenu bi bilo {held + sol:.3f} SOL (otvoreno {held:.3f} + {sol:g}), najviše {cap:g} SOL po tokenu")
            if lflags.applies("dca_cap", U, m):
                raise ValueError(f"kupnja nije poslana: {why} (Pravila → Zastavice plana: dca_cap)")
            if lflags.shadowing("dca_cap", U, m):
                lflags.shadow(lcon, "dca_cap", None, token, "kupi", "odbij", {"held": held, "sol": sol, "cap": cap}, now)
    if lflags.mode("require_signal") != "off":
        ok, why = lcopy.signal_for(token, now)
        if not ok:
            lflags.shadow(lcon, "require_signal", None, token, "kupi (ručno)", "bez signala", {"why": why, "manual": True},
                          now)


def _post_buy(con, tcon, form, user):
    """Manual buy: a demo trade on the real-trade account (10.11.: the owner's buy goes through: only a price, no rug
    and MC 30k+ are required), its own SOL stake for the mirror, and its exit rule; run_trade.py turns it into the
    real swap within the limits."""
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
    # 10.11. (Jure: "ručno sam išao dodati treći ulaz: kupnja odbijena, pada 23 % u zadnjem satu. Kad se ručno dodaje,
    # onda mora proći; program automatski možda ne treba, ali ručno mora proći"): the owner's own buy (and his DCA
    # orders) no longer pass the lists' live gate (activity, volume, the 1-h drop) nor the callers' veto; those stay
    # for the lists and the copies. What stays: a price exists, the pool is not rugged (above), the 30k MC rule
    # (CLAUDE.md), and the limits the real swap keeps (stake, day, cost cap).
    mc_now = mcap
    try:
        from ui import prijedlog
        lv = prijedlog.live_market([token]) or {}
        mc_now = (lv.get(token) or {}).get("mcap") or mcap
    except Exception:  # noqa: BLE001 - DexScreener down: the market() reading above decides
        pass
    if mc_now and mc_now < 30_000:
        raise ValueError(f"kupnja odbijena: MC ${mc_now:,.0f}, ispod 30k")
    # 9.11. (audit N4/N10): everything is checked BEFORE the demo trade is written. A ValueError used to come after
    # store.buy, so the page showed the error while the position already existed, without an exit rule, and
    # run_trade mirrored it (for real in LIVE); a stake above max_sol_per_trade was accepted here and silently
    # blocked by gate_buy, leaving a demo position with no real one behind it.
    ex = form.get("exit") or "smart"
    tp, sl = (form.get("tp") or "").strip(), (form.get("sl") or "").strip()
    if ex == "tpsl":
        if not sl:
            sl = _sl0(_cfg(tcon))   # owner rule 9.11.: no explicit stop -> the default one (10.11.: set under "Pravila")
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
    # 10.11. (Jure: "piše da je kupovina prošla, a nema otvorene pozicije"): the day limit, the day's loss stop, the
    # number of positions and the wallet balance were checked only by run_trade, after the page had already said
    # "poslana". The same gate now answers here, before anything is written, with the way out in the message.
    why = _gate_now(tcon, sol, token)
    if why:
        hint = " Promijeni limit pod Pravila → Limiti." if "otvorenih pozicija" in why else ""
        raise ValueError(f"kupnja nije poslana: {why}.{hint}")
    _owner_buy_rules(con, tcon, token, sol)   # 10.11. (Jure): dca_cap and require_signal, each behind its flag
    sym = _symbol(token)
    # 10.11. (Jure: "ako unesem adresu tokena koji je već u poziciji, pozicija se podeblja"): a token already held
    # gets one more lot (its own demo trade and real swap, run_trade passes add=True for a manual stake) with the exit
    # the position has, so the lots sell by the same rule, each from its own entry
    prev = con.execute("SELECT id, auto FROM trades WHERE user=? AND token=? AND status='open' ORDER BY id DESC LIMIT 1",
                       (settings.LEAGUE_USER, token)).fetchone()
    rules, pa = [(ex, tp, sl)], None
    if prev is not None:
        try:
            pa = json.loads(prev["auto"]) if prev["auto"] else None
        except ValueError:
            pa = None
        if pa and pa.get("mode") == "smart":
            rules.insert(0, ("smart", "", ""))
        elif pa and pa.get("mode") == "tpsl":
            rules.insert(0, ("tpsl", pa.get("tp_in") or pa.get("tp") or "", pa.get("sl_in") or pa.get("sl") or ""))
    tid = store.buy(con, settings.LEAGUE_USER, token, sym, 25, price, liq, "ručno (pravi trade)", None, mcap,
                    allow_open=prev is not None)
    for r_ex, r_tp, r_sl in rules:
        try:
            if r_ex == "smart":
                auto.set_auto(con, settings.LEAGUE_USER, tid, "smart")
            else:
                auto.set_auto(con, settings.LEAGUE_USER, tid, "tpsl", r_tp, r_sl)
            break
        except ValueError as e:   # e.g. the first lot's TP "$100k" under this lot's entry: the form's rule next
            print(f"pravi trade: ručna kupnja {sym or token[:6]}: izlaz {r_tp}/{r_sl} odbijen ({e})", flush=True)
    else:   # never leave the position without an exit
        auto.set_auto(con, settings.LEAGUE_USER, tid, "smart")
    sizes = dict(settings.raw(tcon).get("manual_size") or {})
    sizes[str(tid)] = sol
    settings.put(tcon, "manual_size", dict(list(sizes.items())[-200:]), user)
    if prev is None and ex == "tpsl" and user:   # 10.11. (Jure): the TP / SL typed here prefill the next order
        settings.put(tcon, "last_exit", {"tp": (form.get("tp") or "").strip(), "sl": (form.get("sl") or "").strip()}, user)
    if prev is not None and rules[0][0] == "tpsl":
        # 10.11. (Jure): the position's TP/SL from the new average entry, on every lot (the first lot's typed rule;
        # a rule already made for the position keeps its own text in "grp")
        g = (pa or {}).get("grp") or {}
        try:
            _group_exit(con, tcon, token, g.get("tp", rules[0][1]), g.get("sl", rules[0][2]), _cfg(tcon))
        except ValueError as e:   # e.g. an MC target under the new average: the lots keep the rule set above
            print(f"pravi trade: dokupnja {sym or token[:6]}: zajednički izlaz nije postavljen ({e})", flush=True)
    if prev is not None:
        return f"{BACK}?ok={qq(f'Dokupnja {sym or token[:6]} za {sol:g} SOL poslana: novi ulaz u istoj poziciji, izlaz kao i prvi.')}#pozicije"
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
