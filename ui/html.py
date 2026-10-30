"""Small HTML helpers: layout, tables, badges, bars. No templates, no JS framework."""
import datetime as dt
import html
import json
import time
from urllib.parse import quote

NAV = [("/", "Pregled"), ("/radar", "Radar"), ("/wallets", "Walleti"), ("/tokens", "Tokeni"), ("/events", "Eventi"), ("/watch", "Prije eventa"),
       ("/paper", "Demo trading"), ("/criteria", "Kriteriji"), ("/outputs", "Izvještaji")]

CSS = """
:root{--bg:#f6f7f9;--card:#fff;--fg:#1b1f24;--mut:#5f6b7a;--line:#e3e6ea;--acc:#3b5bdb;
--good:#2b8a3e;--warn:#e67700;--bad:#c92a2a;--goodbg:#ebfbee;--warnbg:#fff4e6;--badbg:#fff5f5;--bar:#4c6ef5}
@media (prefers-color-scheme:dark){:root{--bg:#101318;--card:#181c23;--fg:#e6e9ee;--mut:#8b96a5;--line:#2a303a;
--acc:#7a92ff;--good:#51cf66;--warn:#ffa94d;--bad:#ff6b6b;--goodbg:#13261a;--warnbg:#2b2012;--badbg:#2c1517;--bar:#748ffc}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:14px/1.45 system-ui,-apple-system,Segoe UI,sans-serif}
header{background:var(--card);border-bottom:1px solid var(--line);padding:0 16px;display:flex;gap:4px;align-items:center;flex-wrap:wrap;position:sticky;top:0;z-index:2}
header b{margin-right:16px}header a{padding:12px 10px;color:var(--mut);text-decoration:none;border-bottom:2px solid transparent}
header a.on{color:var(--fg);border-color:var(--acc)}main{max-width:1400px;margin:0 auto;padding:16px}
h1{font-size:20px;margin:8px 0 4px}h2{font-size:16px;margin:24px 0 8px}h3{font-size:14px;margin:16px 0 6px}
.mut{color:var(--mut)}.tdesc{color:var(--mut);font-size:13px;margin:4px 0 8px;padding-left:8px;border-left:3px solid var(--line)}.card{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:12px 14px;margin:10px 0}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:10px}
.stat{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:10px 14px}
.stat .v{font-size:22px;font-weight:600}.stat .l{color:var(--mut);font-size:12px}
.two{display:grid;grid-template-columns:1fr 1fr;gap:14px}@media(max-width:900px){.two{grid-template-columns:1fr}}
.tw{overflow-x:auto;background:var(--card);border:1px solid var(--line);border-radius:8px}
table{border-collapse:collapse;width:100%}th,td{padding:6px 9px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top;white-space:nowrap}
td.wrap,th.wrap{white-space:normal;min-width:220px}th{font-size:12px;color:var(--mut);font-weight:600;cursor:pointer;user-select:none;position:sticky;top:0;background:var(--card)}
tr:hover td{background:color-mix(in srgb,var(--acc) 5%,transparent)}td.n,th.n{text-align:right;font-variant-numeric:tabular-nums}
a{color:var(--acc)}code{font:12px ui-monospace,Menlo,monospace}
.b{display:inline-block;padding:1px 7px;border-radius:10px;font-size:12px;font-weight:600;border:1px solid var(--line)}
.b.good{color:var(--good);background:var(--goodbg);border-color:transparent}.b.warn{color:var(--warn);background:var(--warnbg);border-color:transparent}
.b.bad{color:var(--bad);background:var(--badbg);border-color:transparent}
.pos{color:var(--good)}.neg{color:var(--bad)}
.bar{display:inline-block;height:8px;border-radius:4px;background:var(--line);width:120px;vertical-align:middle;overflow:hidden}
.bar i{display:block;height:100%;background:var(--bar)}
ul.r{margin:4px 0;padding-left:18px}ul.r li{margin:2px 0}li.good::marker{color:var(--good)}li.bad::marker{color:var(--bad)}li.warn::marker{color:var(--warn)}
.flt{margin:8px 0;display:flex;gap:8px;flex-wrap:wrap;align-items:center}
input,select{background:var(--card);color:var(--fg);border:1px solid var(--line);border-radius:6px;padding:5px 8px;font:inherit}
pre{white-space:pre-wrap;background:var(--card);border:1px solid var(--line);border-radius:8px;padding:12px;font:12px/1.5 ui-monospace,Menlo,monospace;overflow-x:auto}
details summary{cursor:pointer;color:var(--acc)}
.cand{text-align:left;cursor:pointer;font:inherit;color:inherit;width:100%}.cand:hover{border-color:var(--acc)}
dialog#ev{max-width:980px;width:calc(100% - 32px);max-height:88vh;border:1px solid var(--line);border-radius:10px;background:var(--bg);color:var(--fg);padding:0}
dialog#ev::backdrop{background:rgba(0,0,0,.45)}dialog#ev .bar2{position:sticky;top:0;display:flex;justify-content:flex-end;padding:8px;background:var(--bg)}
dialog#ev .body{padding:0 18px 18px}tr.clk{cursor:pointer}
.tip{color:var(--acc);cursor:help;font-weight:400;font-size:12px}
#tipbox{position:fixed;z-index:50;max-width:300px;background:var(--fg);color:var(--bg);padding:7px 10px;border-radius:6px;font:12px/1.4 system-ui,sans-serif;white-space:normal;pointer-events:none;display:none;box-shadow:0 4px 14px rgba(0,0,0,.25)}.empty{color:var(--mut);padding:14px}
"""

JS = """
(()=>{const box=document.createElement('div');box.id='tipbox';document.body.appendChild(box);
 const show=el=>{box.textContent=el.dataset.tip;box.style.display='block';const r=el.getBoundingClientRect();
  box.style.left=Math.max(8,Math.min(innerWidth-box.offsetWidth-8,r.left-20))+'px';
  box.style.top=(r.bottom+6+box.offsetHeight>innerHeight?r.top-box.offsetHeight-6:r.bottom+6)+'px'},hide=()=>box.style.display='none';
 document.addEventListener('mouseover',e=>{const t=e.target.closest('.tip');t?show(t):hide()});
 document.addEventListener('focusin',e=>{const t=e.target.closest('.tip');if(t)show(t)});
 document.addEventListener('click',e=>{const t=e.target.closest('.tip');if(t){e.stopPropagation();show(t)}},true);
 addEventListener('scroll',hide,true)})();
document.querySelectorAll('table.s').forEach(t=>{t.querySelectorAll('th').forEach((th,i)=>th.onclick=e=>{if(e.target.closest('.tip'))return;
 const b=t.tBodies[0],rows=[...b.rows],asc=th.dataset.asc!=='1';t.querySelectorAll('th').forEach(x=>delete x.dataset.asc);th.dataset.asc=asc?'1':'0';
 const v=r=>{const c=r.cells[i];const s=c?(c.dataset.v??c.innerText):'';const n=parseFloat(s.replace(/[$,%+ ]/g,''));return isNaN(n)?s.toLowerCase():n};
 rows.sort((a,c)=>{const x=v(a),y=v(c);return (x>y?1:x<y?-1:0)*(asc?1:-1)});rows.forEach(r=>b.appendChild(r))})});
document.querySelectorAll('input[data-f]').forEach(inp=>inp.oninput=()=>{const q=inp.value.toLowerCase();
 document.querySelectorAll('#'+inp.dataset.f+' tbody tr').forEach(r=>r.style.display=r.innerText.toLowerCase().includes(q)?'':'none')});
"""


def esc(x):
    return html.escape("" if x is None else str(x))


def page(title, body, path="/"):
    nav = "".join(f'<a href="{h}" class="{"on" if (h == path or (h != "/" and path.startswith(h.rstrip("s")))) else ""}">{t}</a>'
                  for h, t in NAV)
    return (f"<!doctype html><html lang=hr><head><meta charset=utf-8><meta name=viewport content='width=device-width,"
            f"initial-scale=1'><title>{esc(title)} · crypto-bot</title><style>{CSS}</style></head><body>"
            f"<header><b>crypto-bot</b>{nav}</header><main>{body}</main><script>{JS}</script></body></html>")


def tdesc(text):
    """Short "what this table covers" line shown above a table."""
    return f'<p class=tdesc>{text}</p>'


def tip(text):
    """Small ⓘ that shows `text` on hover or tap."""
    return f'<span class=tip tabindex=0 data-tip="{esc(text)}">ⓘ</span>'


def th(label, cls=""):
    """Column header with its explanation from ui/help.py, if there is one."""
    from ui.help import HELP
    h = HELP.get(label)
    return f'<th class="{cls}">{label}{" " + tip(h) if h else ""}</th>'


def table(headers, rows, tid=None, empty="Nema podataka.", mints=None):
    """headers: [(label, cls)] or labels; rows: [[cell]] where a cell is html or (html, sort_value, cls).
    mints: one token address per row; the row then opens the evidence pop-up (needs modal() on the page)."""
    if not rows:
        return f'<div class="tw"><div class="empty">{empty}</div></div>'
    hs = [th(*(h if isinstance(h, tuple) else (h, ""))) for h in headers]
    body = []
    for r in rows:
        tds = []
        for c in r:
            if isinstance(c, tuple):
                h, v, cls = (c + ("",))[:3]
                tds.append(f'<td class="{cls}" data-v="{esc(v)}">{h}</td>')
            else:
                tds.append(f"<td>{c}</td>")
        m = mints[len(body)] if mints else None
        body.append((f'<tr class=clk data-mint="{esc(m)}">' if m else "<tr>") + "".join(tds) + "</tr>")
    idattr = f' id="{tid}"' if tid else ""
    return f'<div class="tw"><table class="s"{idattr}><thead><tr>{"".join(hs)}</tr></thead><tbody>{"".join(body)}</tbody></table></div>'


def filt(tid, placeholder="Filtriraj…"):
    return f'<input data-f="{tid}" placeholder="{placeholder}" size=30>'


def num(x, fmt="{:,.0f}", cls="n"):
    if x is None:
        return ("–", -1e18, cls)
    return (esc(fmt.format(x)), x, cls)


def signed(x, fmt="{:+.2f}"):
    if x is None:
        return ("–", -1e18, "n")
    c = "pos" if x > 0 else "neg" if x < 0 else ""
    return (f'<span class="{c}">{esc(fmt.format(x))}</span>', x, "n")


def usd(x):
    if x is None:
        return ("–", -1, "n")
    s = f"${x / 1e6:,.2f}M" if x >= 1e6 else f"${x / 1e3:,.1f}k" if x >= 1e3 else f"${x:,.0f}"
    return (s, x, "n")


def bar(v, mx=100, w=120):
    pct = 0 if not mx else max(0, min(100, 100 * (v or 0) / mx))
    return f'<span class="bar" style="width:{w}px"><i style="width:{pct:.0f}%"></i></span>'


def scorecell(v, mx=100):
    if v is None:
        return ("–", -1, "n")
    return (f"{bar(v, mx, 60)} {v:g}", v, "n")


def badge(text, kind=""):
    return f'<span class="b {kind}">{esc(text)}</span>'


VERDICT = {"PROLAZI": "good", "OPREZ": "warn", "VISOK RIZIK": "bad", "ODBAČEN": "bad"}


def verdict(v):
    return badge(v, VERDICT.get(v, "")) if v else "–"


def tierb(t):
    return badge(t, {"A": "good", "B": "warn", "D": "bad"}.get(t, "")) if t else badge("neocijenjen")


def short(a, n=4):
    return f"{a[:n]}…{a[-n:]}" if a and len(a) > 2 * n + 1 else (a or "")


def wlink(w):
    return f'<a href="/wallet/{quote(w)}"><code>{esc(short(w))}</code></a>'


def tlink(mint, sym=None):
    """Token name opens its DexScreener page; the small ⓘ opens our own analysis of the token."""
    label = esc(sym) if sym else f"<code>{esc(short(mint))}</code>"
    return (f'<a href="https://dexscreener.com/solana/{quote(mint)}" target=_blank rel=noopener>{label}</a> '
            f'<a href="/token/{quote(mint)}" class=mut title="analiza tokena" style="text-decoration:none">ⓘ</a>')


def ext_wallet(w):
    return (f'<a href="https://gmgn.ai/sol/address/{quote(w)}" target=_blank>GMGN</a> · '
            f'<a href="https://solscan.io/account/{quote(w)}" target=_blank>Solscan</a>')


def ext_token(mint, url=None):
    parts = [f'<a href="{esc(url)}" target=_blank>DexScreener</a>'] if url else [
        f'<a href="https://dexscreener.com/solana/{quote(mint)}" target=_blank>DexScreener</a>']
    parts += [f'<a href="https://gmgn.ai/sol/token/{quote(mint)}" target=_blank>GMGN</a>',
              f'<a href="https://rugcheck.xyz/tokens/{quote(mint)}" target=_blank>RugCheck</a>',
              f'<a href="https://solscan.io/token/{quote(mint)}" target=_blank>Solscan</a>']
    return " · ".join(parts)


def ts(t, fmt="%Y-%m-%d %H:%M"):
    if not t:
        return ("–", 0, "")
    return (dt.datetime.fromtimestamp(t, dt.timezone.utc).strftime(fmt), t, "")


def ago(t):
    if not t:
        return ("–", 0, "")
    d = time.time() - t
    s = f"{d / 60:.0f} min" if d < 3600 else f"{d / 3600:.1f} h" if d < 86400 else f"{d / 86400:.1f} d"
    return (f"prije {s}", t, "")


def breakdown(parts, total_label="Zbroj", stored=None, mult=None, mult_label=None):
    """Score parts as a table with bars."""
    rows = [[esc(n), (f"{p:+.1f}" if p < 0 else f"{p:.1f}", p, "n"), (f"/ {m}", m, "n mut"),
             bar(p, m) if m else "", f'<span class="mut">{esc(x)}</span>'] for n, p, m, x in parts]
    raw = sum(p for _, p, _, _ in parts)
    foot = f"<b>{total_label}: {raw:.1f}</b>"
    if mult is not None:
        foot += f" × {mult:.2f} {esc(mult_label or '')} = <b>{raw * mult:.1f}</b>"
    if stored is not None:
        foot += f' <span class="mut">(spremljeno u bazi: {esc(stored)})</span>'
    return table(["Dio", ("Bodovi", "n"), ("Max", "n"), "", ("Objašnjenje", "wrap")], rows) + f'<p>{foot}</p>'


MODAL_JS = """
const dlg=document.getElementById('ev');
document.querySelectorAll('[data-mint]').forEach(b=>b.addEventListener('click',async e=>{if(e.target.closest('a,.tip'))return;
 dlg.querySelector('.body').innerHTML='<p class=mut>Učitavam analizu…</p>';dlg.showModal();
 try{const r=await fetch('/api/evidence/'+encodeURIComponent(b.dataset.mint));dlg.querySelector('.body').innerHTML=await r.text()}
 catch(err){dlg.querySelector('.body').innerHTML='<p>Greška pri učitavanju.</p>'}}));
dlg.addEventListener('click',e=>{if(e.target===dlg)dlg.close()});
"""


def modal():
    """The evidence pop-up: any element with data-mint opens /api/evidence/<mint> in it."""
    return ("<dialog id=ev><div class=bar2><button onclick=\"this.closest('dialog').close()\">Zatvori ✕</button></div>"
            f"<div class=body></div></dialog><script>{MODAL_JS}</script>")


def jsonblock(o):
    return f"<details><summary>Sirovi podaci (JSON)</summary><pre>{esc(json.dumps(o, indent=1, ensure_ascii=False))}</pre></details>"
