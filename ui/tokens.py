"""The "Tokeni" page, where the app opens: one list with three views (Novi · Jaki · Dugoročni). Novi = active
candidates by confidence (event tokens and older ones folded below), Jaki = the strong long-term list, Dugoročni is
its own page (/dugorocno) with the same switch on top. Rugged, rejected and weak tokens are never listed as candidates.

10.11. (Jure: "Ostalo mi se sviđa", prijedlog 3.2 i 4.2, makete tokeni.html i tokeni-popis.html): the list is calm rows
instead of cards with six fields and an ⓘ each. A row is symbol, one short reason and "prije 3 min" on the left,
pouzdanost and mcap on the right; on a computer the same row carries Likv., Rug and Zadnji signal as columns. The
day's suggestion is a group on top ("U zoni ulaza · današnji prijedlog") instead of the repeated Pregled block. One
field filters the list and opens a pasted address; one sheet sorts and filters ("Poredaj i filtriraj"). Weak, rejected,
event and older tokens are one tap below the list (same rows), nothing is dropped.
"""
import re
import time

from ui import overview
from ui.html import tdesc, ago, badge, esc, filt, modal, rugcell, scorecell, seg, table, tlink, usd  # noqa: F401
from ui import redak as R

ACTIVE_H = 24
STALE_MARKET_S = 900      # 9.11. (audit P83): a market check older than this shows its age in the cell
RULE_MCAP = 30_000        # CLAUDE.md: tokens under $30k are not analysed (and never bought)
SCAN_MIN = 2              # the hype scan runs as a child of the demo loop every 2 min (ops/cpuguard "hype")
WARM_S = 300              # run_ui WARM: /tokens is pre-rendered every UI_WARM_EVERY_S (default 300 s)
# prijedlog.js: the share of the analysis mcap where a suggested token is still "u zoni ulaza" (same numbers as Pregled)
ZONE_LO, ZONE_HI = 0.80, 1.25


def market(status, mcap, now=None):
    """9.11. (audit P83/P84): hype/tokenstatus.market_cell plus what the number cannot say by itself: the age of the
    market check when it is older than STALE_MARKET_S (the status job runs every 6 h, so the cell looked live while
    the Autopilot had the token live), and 'ispod 30k' when the KNOWN mcap is under the rule (the row stays, with its
    number, so the drop is visible; nothing is bought from this page). An unknown mcap gets no mark."""
    from hype.tokenstatus import market_cell
    now = now or time.time()
    txt, val, cls = market_cell(status, mcap, now)
    st = status or {}
    if st.get("has_pair") and st.get("checked_ts") and now - st["checked_ts"] > STALE_MARKET_S:
        txt += (f' <small class=mut title="Tržišna provjera (hype/tokenstatus, svakih 6 h) {ago(st["checked_ts"])[0]}; '
                f'Autopilot isti token gleda uživo">{esc(ago(st["checked_ts"])[0])}</small>')
    if val is not None and 0 < val < RULE_MCAP:
        txt += ' <span class="b warn" title="Ispod $30k: pravilo ga ne analizira ni ne kupuje">ispod 30k</span>'
    return txt, val, cls


def _why(r):
    try:
        from ui.radar import reasons
        why = reasons(r["features"], r["det"])[:2]
    except Exception:
        why = []
    if not why:
        why = [t for p, t in r["conf_parts"] if p > 0][:2]
    return ("<ul class=r>" + "".join(f"<li class=good>{esc(w)}</li>" for w in why) + "</ul>") if why else "<span class=mut>–</span>"


def _checks(r):
    return " ".join(badge(("✓ " if ok else "✗ ") + lab, "good" if ok else "bad") for lab, ok, _ in r["checks"] if ok is not None)


def _status():
    """7.11.: hype/tokenstatus rows: exact pair page, dead tokens, fresh market caps."""
    try:
        from hype import tokenstatus
        from ui import data as _d
        return tokenstatus.read(_d.HYPE_DB)
    except Exception:  # noqa: BLE001
        return {}


def _main_table(rows, tid, empty, st=None, now=None):
    """The old table (one row per token, every column). 10.11.: the page shows rows (token_rows) instead; kept for
    callers and tests that still want the table."""
    from ui import confidence
    st = st if st is not None else _status()
    now = now or time.time()
    # 9.11. (audit P83/P84): "Zadnji signal" is the newest signal / rug check / candidate, not the market check;
    # the market check's age sits in the Mcap cell when it is older than 15 min
    return table(["Token", ("Confidence", "n"), ("Mcap", "n"), ("Likv.", "n"), ("Zašto", "wrap"), "Rug", "Zadnji signal"],
                 [[tlink(r["token"], r["symbol"], st.get(r["token"])), (confidence.badge_html(r["conf"]), r["conf"], "n"),
                   market(st.get(r["token"]), r["mcap"], now),
                   usd((st.get(r["token"]) or {}).get("liq") if (st.get(r["token"]) or {}).get("has_pair") else r["liq"]),
                   (_why(r), "", "wrap"), rugcell(r), ago(r["last_seen"])] for r in rows], tid, empty,
                 mints=[r["token"] for r in rows])


# ---------- 10.11.: calm rows (prijedlog 3.2 / 4.2) ----------------------------------------------------------------

def plural(n, one, few, many):
    """Croatian noun form after a number: plural(21, "token", "tokena", "tokena") -> "token"."""
    n = abs(int(n or 0))
    if n % 10 == 1 and n % 100 != 11:
        return one
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return few
    return many


def analysed_line(n24, zone):
    """Subtitle: "21 token analiziran u zadnja 24 h · 3 u zoni ulaza" (the zone part only when there is one)."""
    out = f"{R.num(n24)} {plural(n24, 'token', 'tokena', 'tokena')} {plural(n24, 'analiziran', 'analizirana', 'analizirano')} u zadnja {ACTIVE_H} h"
    return out + (f" · {zone} u zoni ulaza" if zone else "")


def _smart_n(n):
    return f"{n} smart {'wallet' if plural(n, 1, 2, 3) == 1 else 'walleta'}"


def shorten(s):
    """One short reason out of a radar / confidence sentence: "Novac ulazi brzo: volumen ..." -> "Novac ulazi brzo",
    "3 provjerenih smart walleta je među prvim kupcima." -> "3 smart walleta" (maketa: kratki razlog, ostalo na dodir)."""
    s = (s or "").strip()
    m = re.match(r"^(\d+) provjeren\w* smart walleta", s)
    if m:
        return _smart_n(int(m.group(1)))
    if s.startswith("Praćeni influenceri su ga objavili"):
        return "Zvali influenceri na X-u"
    m = re.match(r"^Cijena raste: (?:oko )?\+(\d+)%", s)
    if m:
        return f"Cijena +{m.group(1)}{R.NBSP}% u 1 h"
    if s.startswith("Ime je upravo trending"):
        return "Trending tema na X-u"
    if s.startswith("Hype ocjena"):
        m = re.match(r"^Hype ocjena (\d+)", s)
        return f"Hype ocjena {m.group(1)}" if m else "Hype ocjena"
    return re.split(r"[:(„]", s)[0].strip().rstrip(".").strip()


def short_reason(r):
    """The strongest reason of a token row in a few words (radar.reasons first, then a positive confidence part)."""
    try:
        from ui.radar import reasons
        why = reasons(r.get("features") or {}, r.get("det") or {})
    except Exception:  # noqa: BLE001
        why = []
    for w in why + [t for p, t in (r.get("conf_parts") or []) if p > 0]:
        s = shorten(w)
        if s:
            return s
    return ""


def rug_word(r):
    """'oprez', 'prolazi' or '' from the rug filter and the fresh check of a recommended token (topcheck)."""
    rv = ((r.get("rug") or {}).get("verdict") or "").upper()
    tv = ((r.get("top") or {}).get("verdict") or "").lower()
    if rv == "OPREZ" or tv == "oprez":
        return "oprez"
    if rv == "PROLAZI" or tv == "prolazi":
        return "prolazi"
    return ""


def mcap_now(r, st):
    """(mcap, liq): the fresher of the token status pass (DexScreener, every 6 h) and the token's last signal."""
    s = st or {}
    sig_ts = r.get("signal_ts") or r.get("last_seen") or 0
    if s.get("has_pair") and s.get("mcap") and (s.get("checked_ts") or 0) >= sig_ts:
        return s["mcap"], s.get("liq") or r.get("liq")
    return r.get("mcap") or (s.get("mcap") if s.get("has_pair") else None), r.get("liq") or (s.get("liq") if s.get("has_pair") else None)


def zone_tokens(hype_db, now=None, picks=None):
    """{mint: mcap0} of today's suggestion (Pregled box, prijedlog_log: one row per token per UTC day, a few rows a
    day) shown in the last 24 h. picks: test seam."""
    if picks is not None:
        return dict(picks)
    now = now or time.time()
    try:
        from ui import data as _d
        rows = _d.q(hype_db, "SELECT token, mcap0 FROM prijedlog_log WHERE ts >= ? ORDER BY ts", (int(now - 86400),))
    except Exception:  # noqa: BLE001
        return {}
    return {r["token"]: r["mcap0"] for r in rows if r.get("mcap0")}


def in_zone(mcap, mcap0):
    """Same rule as the Pregled box (prijedlog.js): still near the analysis mcap, not run away, not falling."""
    if not mcap or not mcap0:
        return False
    x = mcap / mcap0
    return ZONE_LO < x < ZONE_HI


def token_row(r, st=None, now=None, reason=None, why_warn=None):
    """One token as a calm row (Html). On a phone: symbol, reason + age left, pouzdanost + mcap right. On a computer
    the same row shows Likv., Rug and Zadnji signal as columns. data-* carry what the sort / filter sheet needs."""
    now = now or time.time()
    mc, lq = mcap_now(r, st)
    rw = rug_word(r)
    why = reason if reason is not None else short_reason(r)
    age = R.ago(r.get("last_seen"), now)
    f = r.get("features") or {}
    sm = len((r.get("det") or {}).get("smart_buyers") or []) or (1 if f.get("smart_money") else 0)
    small = bool(mc) and 0 < mc < RULE_MCAP
    warn = why_warn or ("Rug: oprez" if rw == "oprez" else None)
    if warn:
        wtxt = R.cat(R.raw(f'<span class="ms-warn">{esc(warn)}</span>'),
                     R.raw(f'<span class="tk-dk"> · {esc(why)}</span>') if why else "",
                     R.raw(f'<span class="tk-ph"> · {esc(age)}</span>'))
    else:
        wtxt = R.cat(why or "", R.raw(f'<span class="tk-ph">{" · " if why else ""}{esc(age)}</span>'))
    sym = r.get("symbol") or (r["token"][:4] + "…" + r["token"][-4:])
    attrs = (f'data-s="{esc((sym + " " + r["token"]).lower())}" data-cf="{int(r.get("conf") or 0)}" '
             f'data-sn="{int(r.get("sansa") or 0)}" data-ts="{int(r.get("last_seen") or 0)}" data-mc="{int(mc or 0)}" '
             f'data-h1="{round(200 * (f.get("momentum") or 0))}" data-rug="{1 if rw == "oprez" else 0}" data-sm="{sm}"')
    mct = R.usd(mc) if mc else R.DASH
    return R.raw(
        f'<a class="tk-r" href="/token/{esc(r["token"])}" {attrs}>'
        f'<span class="tk-n" translate=no>{esc(sym)}</span><span class="tk-w">{wtxt}</span>'
        f'<span class="tk-c">{int(r.get("conf") or 0)}</span>'
        f'<span class="tk-m{" ms-warn" if small else ""}"'
        + (' title="Ispod 30k $: pravilo ga ne analizira ni ne kupuje"' if small else "")
        + f'>{esc(mct)}</span>'
        f'<span class="tk-l" data-col="l">{esc(R.usd(lq) if lq else R.DASH)}</span>'
        f'<span class="tk-g{" ms-warn" if rw == "oprez" else ""}" data-col="g">{esc(rw or R.DASH)}</span>'
        f'<span class="tk-t" data-col="t">{esc(age)}</span><span class="ms-chev" aria-hidden="true"></span></a>')


def _group(title, note, rows_html, gid):
    head = f'<div class="tk-sec"><b>{esc(title)}</b>{" · " + esc(note) if note else ""}</div>'
    return R.raw(f'<div class="tk-grp" id="{gid}">{head}<div class="tk-list">{"".join(rows_html)}</div></div>')


def _more(title, note, rows_html, mid):
    """A folded group one tap below the list (same rows): odbačeni, uz evente, stariji."""
    if not rows_html:
        return ""
    return (f'<details class="tk-more" id="{mid}"><summary class="tk-foot"><span>{esc(title)} · {len(rows_html)}'
            + (f' <span class="mut">({esc(note)})</span>' if note else "")
            + f'</span><span class="ms-chev" aria-hidden="true"></span></summary><div class="tk-list">{"".join(rows_html)}</div></details>')


def rejected_reason(r):
    """Why a token is off the list, in a few words (odbačeni)."""
    if r.get("collapse"):
        return "Srušio se"
    rv = ((r.get("rug") or {}).get("verdict") or "").upper()
    if rv == "ODBAČEN":
        return "Rug: odbačen"
    if rv == "VISOK RIZIK":
        return "Rug: visok rizik"
    if ((r.get("top") or {}).get("verdict") or "") == "pao":
        return "Pao na provjeri ruga"
    if (r.get("tier") or {}).get("t0") == "pad":
        return "Pao na mehanici ruga"
    return "Odbačen"


HEAD = ('<div class="tk-head"><button type="button" class="tk-sort" data-sheet aria-haspopup="dialog">'
        '<span id="tk-sortlbl">Poredano po pouzdanosti</span></button>'
        '<span class="tk-p">pouzdanost · mcap</span>'
        # 10.11. (prijedlog 3.2: "na računalu tooltip na zaglavlju stupca"): one sentence per column instead of an ⓘ
        '<button type="button" class="tk-h tk-hc" data-k="cf" title="Pouzdanost 0 do 100: koliko se neovisni izvori '
        'slažu (hype, smart walleti, KOL-ovi, X, rug). Dodir poreda po njoj.">Pouzdanost</button>'
        '<button type="button" class="tk-h tk-hm" data-k="mc" title="Tržišna vrijednost sada (DexScreener ili zadnji '
        'signal). Ispod 30k $ se ne analizira ni ne kupuje.">Mcap</button>'
        '<span class="tk-h tk-hl" data-col="l" title="Likvidnost para: koliko se može kupiti i prodati bez velikog '
        'pomaka cijene.">Likv.</span><span class="tk-h tk-hg" data-col="g" title="Rug filter i svježa provjera '
        'preporučenih tokena: prolazi ili oprez.">Rug</span>'
        '<button type="button" class="tk-h tk-ht" data-k="ts" data-col="t" title="Zadnji signal, rug provjera ili '
        'kandidat za demo.">Zadnji signal</button><span></span></div>')

SEARCH = ('<form class="tk-fld" action="/trazi" role="search" autocomplete="off" id="tk-f">'
          '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="11" cy="11" r="6.5"/><path d="M20 20l-4.2-4.2"/></svg>'
          '<input id="tk-q" name="q" type="search" placeholder="Simbol ili adresa" aria-label="Simbol ili adresa" '
          'enterkeyhint="search" autocapitalize="none" spellcheck="false"></form>')

SORTS = [("cf", "Pouzdanost"), ("sn", "Šansa za skok"), ("ts", "Zadnji signal"), ("mc", "Mcap"), ("h1", "Rast 1 h")]


def sheet():
    """The "Poredaj i filtriraj" sheet (one control instead of Sortiraj, Tablica and Stupci on the phone)."""
    opts = "".join(f'<button type="button" class="tk-o" data-k="{k}">{esc(t)}<span class="tk-ck"></span></button>'
                   for k, t in SORTS)
    sw = ('<label class="tk-o">Rug: oprez<input type="checkbox" class="tk-sw" id="tk-rug" checked></label>'
          '<label class="tk-o">Samo sa smart walletima<input type="checkbox" class="tk-sw" id="tk-sm"></label>')
    return (f'<dialog class="tk-sheet" id="tk-sheet" aria-label="Poredaj i filtriraj"><div class="tk-grab"></div>'
            f'<div class="tk-sh">Poredaj i filtriraj</div><div class="tk-gl">Poredaj po</div><div class="tk-grp2">{opts}</div>'
            f'<div class="tk-gl">Prikaži</div><div class="tk-grp2">{sw}</div>'
            '<button type="button" class="tk-done" data-close>Gotovo</button></dialog>')


# the bottom sheet (Poredaj i filtriraj here, Kupi on the token page): one look for both, values from tokeni-popis.html
SHEET_CSS = """
.tk-sheet{border:0;padding:10px 12px 18px;background:var(--soft);border-radius:18px 18px 0 0;width:100%;max-width:520px;margin:auto auto 0;color:var(--fg)}
.tk-sheet::backdrop{background:rgba(11,18,32,.35)}
.tk-grab{width:36px;height:5px;border-radius:3px;background:var(--line2);margin:2px auto 12px}
.tk-sh{font-size:17px;font-weight:600;text-align:center;margin:0 0 12px}
.tk-gl{font-size:13px;color:var(--mut);margin:0 4px 6px}
.tk-grp2{background:#fff;border-radius:12px;overflow:hidden;margin:0 0 12px}
.tk-o{all:unset;box-sizing:border-box;display:flex;justify-content:space-between;align-items:center;width:100%;min-height:46px;padding:0 14px;font-size:17px;cursor:pointer}
.tk-o+.tk-o{border-top:1px solid var(--line)}
.tk-o.on .tk-ck{width:12px;height:7px;border-left:2px solid var(--acc);border-bottom:2px solid var(--acc);transform:rotate(-45deg);margin:-4px 4px 0 0}
.tk-sw{appearance:none;-webkit-appearance:none;flex:none;width:43px;height:26px;border-radius:999px;background:var(--line2)!important;border:0!important;position:relative;margin:0;padding:0;cursor:pointer;transition:background .15s}
.tk-sw::after{content:"";position:absolute;top:2px;left:2px;width:22px;height:22px;border-radius:50%;background:#fff;box-shadow:0 2px 4px rgba(0,0,0,.2);transition:left .15s}
.tk-sw:checked{background:var(--good)!important}.tk-sw:checked::after{left:19px}
.tk-done{all:unset;box-sizing:border-box;display:block;width:100%;text-align:center;background:var(--fg);color:#fff;border-radius:12px;padding:12px;font-size:17px;font-weight:600;cursor:pointer}
@media(min-width:900px){.tk-sheet{margin:auto;border-radius:18px}}
"""

CSS = """<style>
.tk-fld{display:flex;align-items:center;gap:8px;background:var(--soft);border-radius:11px;padding:0 12px;margin:14px 0 0}
.tk-fld svg{width:17px;height:17px;fill:none;stroke:var(--mut);stroke-width:2;stroke-linecap:round;flex:none}
.tk-fld input{flex:1;min-width:0;border:0!important;background:none!important;font-size:17px;padding:9px 0;color:var(--fg);outline:none;box-shadow:none}
.tk-fld input::placeholder{color:var(--mut)}
.tk-head{display:flex;justify-content:space-between;align-items:baseline;font-size:15px;color:var(--mut);padding:18px 0 8px;border-bottom:1px solid var(--line)}
.tk-head button{all:unset;cursor:pointer}
.tk-head .tk-sort{color:var(--acc);font-weight:500;text-align:left}.tk-sort::after{content:"";display:inline-block;width:6px;height:6px;border-right:1.5px solid var(--acc);border-bottom:1.5px solid var(--acc);transform:rotate(45deg);margin:0 0 3px 7px}
.tk-head .tk-h,.tk-h{display:none}
.tk-sec{font-size:15px;font-weight:600;color:var(--mut);margin:26px 0 0;padding:0 0 6px;border-bottom:1px solid var(--line)}
.tk-sec b{color:var(--fg)}
.tk-r{display:grid;grid-template-columns:minmax(0,1fr) auto 14px;grid-template-areas:"n c v" "w m v";column-gap:12px;align-items:center;padding:11px 0;border-bottom:1px solid var(--line);min-height:64px;color:var(--fg);text-decoration:none}
.tk-list>.tk-r:last-child{border-bottom:0}
.tk-r[hidden],.tk-grp[hidden],.tk-more[hidden],.tk-empty[hidden]{display:none!important}
#tk-root .ms-hint a{text-decoration:none}
.tk-r:hover .tk-n{color:var(--acc)}
.tk-n{grid-area:n;font-size:17px;font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.tk-w{grid-area:w;font-size:15px;color:var(--mut);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;margin-top:1px}
.tk-c{grid-area:c;text-align:right;font-size:17px;font-weight:600;font-variant-numeric:tabular-nums}
.tk-m{grid-area:m;text-align:right;font-size:15px;color:var(--mut);white-space:nowrap;font-variant-numeric:tabular-nums}
.tk-m.ms-warn{color:var(--warn)}
.tk-l,.tk-g,.tk-t,.tk-dk{display:none}
.tk-r .ms-chev{grid-area:v}
.tk-foot{display:flex;justify-content:space-between;align-items:center;gap:12px;padding:14px 0;border-top:1px solid var(--line);margin:18px 0 0;font-size:15px;color:var(--mut);cursor:pointer;list-style:none}
.tk-foot::-webkit-details-marker{display:none}.tk-more[open] .tk-foot .ms-chev{transform:rotate(135deg)}
.tk-more+.tk-more .tk-foot{margin-top:0}
.tk-empty{text-align:center;padding:26px 6px 18px}.tk-empty b{display:block;font-size:17px;font-weight:600}
.tk-empty p{font-size:15px;color:var(--mut);margin:6px 0 12px;line-height:1.4}.tk-empty a,.tk-empty button{all:unset;cursor:pointer;font-size:15px;color:var(--acc);font-weight:500}
__SHEET__@media(min-width:900px){
 .tk-r,.tk-head{display:grid;grid-template-columns:var(--gc-cols,minmax(0,1fr) 96px 92px 92px 92px 112px 14px);column-gap:16px}
 .tk-r{grid-template-areas:none}.tk-r>*{grid-area:auto}
 .tk-n{grid-column:1;grid-row:1}.tk-w{grid-column:1;grid-row:2}
 .tk-c,.tk-m,.tk-l,.tk-g,.tk-t{display:block;grid-row:1/3;text-align:right}
 .tk-m{font-size:17px;color:var(--fg)}.tk-l,.tk-g,.tk-t{font-size:15px;color:var(--mut)}.tk-g.ms-warn{color:var(--warn)}
 .tk-r .ms-chev{grid-area:auto;grid-row:1/3;justify-self:end}
 .tk-ph{display:none}.tk-dk{display:inline}
 .tk-head{align-items:end;font-size:13px}.tk-p{display:none}.tk-head .tk-h{display:block;text-align:right}
 .tk-head button.tk-h:hover{color:var(--fg)}
}
</style>""".replace("__SHEET__", SHEET_CSS)

JS = r"""<script>(()=>{
const q=document.getElementById('tk-q'),root=document.getElementById('tk-root');if(!root)return;
const rows=[...root.querySelectorAll('.tk-r')],grps=[...root.querySelectorAll('.tk-grp,.tk-more')];
const MINT=/^[1-9A-HJ-NP-Za-km-z]{32,44}$/,LBL={cf:'pouzdanosti',sn:'šansi za skok',ts:'zadnjem signalu',mc:'mcapu',h1:'rastu 1 h'};
const get=k=>{try{return localStorage.getItem(k)}catch(e){return null}},put=(k,v)=>{try{localStorage.setItem(k,v)}catch(e){}};
let key=get('tk_sort')||'cf';if(!LBL[key])key='cf';
const rug=document.getElementById('tk-rug'),sm=document.getElementById('tk-sm'),empty=document.getElementById('tk-none');
if(rug)rug.checked=get('tk_rug')!=='0';if(sm)sm.checked=get('tk_sm')==='1';
function apply(){const s=(q&&q.value||'').trim().toLowerCase();let shown=0;
 grps.forEach(g=>{const l=g.querySelector('.tk-list'),rs=[...l.children];
  rs.sort((a,b)=>(+b.dataset[key]||0)-(+a.dataset[key]||0)||(+b.dataset.cf||0)-(+a.dataset.cf||0)).forEach(r=>l.appendChild(r));
  let n=0;rs.forEach(r=>{const ok=(!s||r.dataset.s.indexOf(s)>=0)&&(!rug||rug.checked||r.dataset.rug!=='1')&&(!sm||!sm.checked||+r.dataset.sm>0);
   r.hidden=!ok;if(ok)n++});g.hidden=!n;shown+=n;
  // the folded groups (odbačeni, uz evente, stariji) open while a search finds something in them
  if(g.tagName==='DETAILS'){if(s&&n&&!g.open){g.open=true;g.dataset.auto=1}else if(!s&&g.dataset.auto){g.open=false;delete g.dataset.auto}}});
 const lb=document.getElementById('tk-sortlbl');if(lb)lb.textContent='Poredano po '+LBL[key];
 document.querySelectorAll('.tk-o[data-k]').forEach(o=>o.classList.toggle('on',o.dataset.k===key));
 if(empty){empty.hidden=!!shown||!rows.length;const t=empty.querySelector('[data-q]');if(t)t.textContent=s?'Nema tokena "'+q.value.trim()+'" na popisu':'Nijedan token ne prolazi filtar'}}
if(q){q.addEventListener('input',apply);document.getElementById('tk-f').addEventListener('submit',e=>{const v=q.value.trim();
 if(MINT.test(v)){e.preventDefault();location.href='/token/'+v;return}
 const vis=rows.filter(r=>!r.hidden);if(v&&vis.length===1){e.preventDefault();location.href=vis[0].getAttribute('href')}})}
const sh=document.getElementById('tk-sheet');
document.querySelectorAll('[data-sheet]').forEach(b=>b.addEventListener('click',()=>{if(sh&&sh.showModal)sh.showModal()}));
if(sh){sh.addEventListener('click',e=>{if(e.target===sh||e.target.closest('[data-close]'))sh.close();
  const o=e.target.closest('.tk-o[data-k]');if(o){key=o.dataset.k;put('tk_sort',key);apply()}});
 [rug,sm].forEach(c=>c&&c.addEventListener('change',()=>{put('tk_rug',rug.checked?'1':'0');put('tk_sm',sm.checked?'1':'0');apply()}))}
document.querySelectorAll('.tk-head button[data-k]').forEach(b=>b.addEventListener('click',()=>{key=b.dataset.k;put('tk_sort',key);apply()}));
const cl=document.getElementById('tk-clear');if(cl)cl.addEventListener('click',()=>{q.value='';if(rug)rug.checked=true;if(sm)sm.checked=false;put('tk_rug','1');put('tk_sm','0');apply();q.focus()});
apply();
const age=document.getElementById('tk-age');if(age){const t=+age.dataset.ts,f=()=>{const m=Math.max(0,Math.round((Date.now()/1e3-t)/60)),
 nx=Math.max(1,Math.round((t+(+age.dataset.every)-Date.now()/1e3)/60));
 age.textContent=(m<1?'Osvježeno upravo sada':'Osvježeno prije '+m+' min')+(t+(+age.dataset.every)>Date.now()/1e3?', sljedeće za '+nx+' min.':', sljedeće uskoro.')};f();setInterval(f,30000)}
})()</script>"""


def cols_tool():
    """'Stupci' for the token rows on a computer (ui/cols.py does it for tables; these rows are a grid)."""
    from ui import cols
    return cols.grid_chooser("tk-root", [("l", "Likv.", "92px"), ("g", "Rug", "92px"), ("t", "Zadnji signal", "112px")],
                             fixed_left="minmax(0,1fr) 96px 92px")


VIEWS = [("/tokens", "Novi"), ("/tokens/jaki", "Jaki"), ("/dugorocno", "Dugoročni")]


def switch(cur):
    """Novi · Jaki · Dugoročni on top of all three views (10.11.: the calm segment over the full width)."""
    return R.seg(VIEWS, cur)


# shown once per browser on the first visit (rule: friends use the app without explanation), then never again.
# 10.11. (Jure, prijedlog 3.2): no longer on Tokeni ("Dobro došao" → samo prvi posjet, na Pregledu); kept for Pregled.
HELLO = ("<div class=card id=hello hidden><b>Dobro došao.</b><ol style='margin:6px 0 8px;padding-left:20px'>"
         "<li><b>Tokeni</b>: najbolji prijedlozi, najjači gore.</li>"
         "<li><b>Influenceri</b>: tko stvarno pogađa i što je upravo zvao.</li>"
         "<li><b>Novčanici</b>: tko je upravo kupio ili prodao.</li></ol>"
         "<span class=mut>Dodirni ⓘ uz broj za objašnjenje.</span> <button type=button class=sm id=hello-ok>U redu</button></div>"
         "<script>(()=>{const h=document.getElementById('hello');try{if(localStorage.getItem('ms_hello'))return}catch(e){return}"
         "h.hidden=false;document.getElementById('hello-ok').onclick=()=>{h.hidden=true;try{localStorage.setItem('ms_hello','1')}catch(e){}}})()</script>")


def _strong_rows(n=5):
    """[(mint, symbol, score, mcap, why)] of the "jaki" list from the long-term layer (dugo.db)."""
    try:
        from dugo import store as dstore
        con = dstore.ro()
        if con is None:
            return []
        try:
            return [tuple(r) for r in con.execute(
                """SELECT s.mint, t.symbol, s.score, s.mcap, s.why FROM snap s JOIN tokens t
                ON t.mint=s.mint WHERE s.kind='jaki' AND s.day=(SELECT MAX(day) FROM snap) ORDER BY s.rank LIMIT ?""",
                (n,)).fetchall()]
        finally:
            con.close()
    except Exception as e:  # noqa: BLE001 - a side box must not break the page
        print(f"tokeni: jaki tokeni: {type(e).__name__}: {e}")
        return []


def _strong(n=5):
    """Top of the "jaki" list from the long-term layer (dugo.db): older, bigger tokens with steady volume and holders.
    10.11. (prijedlog 4.2: "Jaki i Dugoročni koriste isti redak"): rows, the score right and the mcap under it."""
    rows = _strong_rows(n)
    if not rows:
        return ""
    return R.rows([R.row(sym or (m[:4] + "…" + m[-4:]), reason=why or None, value=R.num(sc), sub=R.usd(mc),
                         href=f"/token/{m}") for m, sym, sc, mc, why in rows])


def _page_jaki():
    strong = _strong(n=50)
    body = (R.top("Tokeni", "Stariji tokeni sa stalnim volumenom, jednom dnevno") + switch("/tokens/jaki")
            + (R.colhead("Token", "ocjena · mcap") + strong if strong else
               '<div class="tk-empty"><b>Popis jakih tokena još se slaže</b><p>Slaže se jednom dnevno iz dnevnih cijena.</p>'
               '<a href="/tokens">Pogledaj Nove</a></div>'))
    return "Tokeni", f'{CSS}<div class="ms-page ms-wide">{body}</div>'


def page(qs, view="novi", now=None, rows=None, st=None, picks=None):
    """/tokens and /tokens/jaki. rows / st / picks: test seams (token_rows, token status, today's suggestion)."""
    if view == "jaki":
        return _page_jaki()
    now = now or time.time()
    t = time.time()
    rows = rows if rows is not None else overview.token_rows()
    from ui import data as _d
    _d.stage("/tokens token_rows", t)
    day = now - ACTIVE_H * 3600
    good = [r for r in rows if overview.relevant(r)]
    active = sorted([r for r in good if r["last_seen"] >= day], key=lambda r: (r.get("conf") or 0, r.get("sansa") or 0),
                    reverse=True)
    older = sorted([r for r in good if r["last_seen"] < day], key=overview._rank, reverse=True)
    event = [r for r in rows if r["events"] and not overview.bad(r)]
    rejected = sorted([r for r in rows if overview.bad(r) and r["last_seen"] >= day], key=lambda r: -r["last_seen"])
    n24 = sum(1 for r in rows if r["last_seen"] >= day)
    st = st if st is not None else _status()
    zmap = zone_tokens(_d.HYPE_DB, now, picks)
    zone = [r for r in active if r["token"] in zmap and in_zone(mcap_now(r, st.get(r["token"]))[0], zmap[r["token"]])]
    zset = {r["token"] for r in zone}
    rest = [r for r in active if r["token"] not in zset]

    # 10.11. (Jure, prijedlog 3.2 i 5.1): "Prijedlog za danas" (prijedlog.box) lives only on Pregled; Tokeni start
    # with their own list (on the phone the first token used to come only on the second screen)
    b = [CSS, '<div class="ms-page ms-wide" id="tk-root">', R.top("Tokeni", analysed_line(n24, len(zone))),
         switch("/tokens"), SEARCH, cols_tool(), HEAD]
    if zone:
        b.append(_group("U zoni ulaza", "današnji prijedlog", [token_row(r, st.get(r["token"]), now) for r in zone], "tk-zona"))
    if rest:
        b.append(_group("Ostali" if zone else "Kandidati", f"{len(rest)}", [token_row(r, st.get(r["token"]), now) for r in rest],
                        "tk-ostali"))
    if not active:
        b.append('<div class="tk-empty"><b>Trenutno nema novih tokena</b><p>Nijedan novi bondani token iznad 30k $ nije '
                 f'prošao provjere u zadnja {ACTIVE_H} h. Skeniramo svake {SCAN_MIN} min.</p>'
                 '<a href="/tokens/jaki">Pogledaj Jake</a></div>')
    # search or filters without a match (prijedlog 4.2, stanje 3)
    b.append('<div class="tk-empty" id="tk-none" hidden><b data-q>Nema tokena na popisu</b><p>Popis ima samo analizirane '
             'tokene. Zalijepi adresu i otvorit ćemo bilo koji token s provjerom ruga.</p>'
             '<button type="button" id="tk-clear">Očisti traženje</button></div>')
    b.append(_more("Odbačeni", "rug ili pao na provjeri",
                   [token_row(r, st.get(r["token"]), now, why_warn=rejected_reason(r)) for r in rejected], "tk-odb"))
    b.append(_more("Uz evente", None,
                   [token_row(r, st.get(r["token"]), now, reason=f'{e["event"]} · {e["event_date"]}')
                    for r in event for e in r["events"][:1]], "tk-ev"))
    b.append(_more(f"Stariji od {ACTIVE_H} h", "nisu viđeni u zadnja 24 h",
                   [token_row(r, st.get(r["token"]), now) for r in older], "tk-st"))
    b.append(f'<p class="ms-hint" style="margin-top:14px"><span id="tk-age" data-ts="{int(now)}" data-every="{WARM_S}">Popis od '
             f'{time.strftime("%H:%M", time.localtime(now))}, osvježava se svakih {WARM_S // 60} min.</span> '
             '<a class="ms-acc" href="/pojmovnik#confidence">Što znači pouzdanost</a></p>')
    b.append(sheet() + "</div>" + JS)
    return "Tokeni", "".join(b)
