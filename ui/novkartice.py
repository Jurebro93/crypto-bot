"""What an ordinary user sees about the wallets, and the Autopilot's demo section (19.11., vlasnik: "The ordinary user
should only be informed: follow this wallet because of this and this"; "On the Autopilot page, while real money is
off, do as many demo trades as possible with wallet following").

  card_html()        "Novčanici koje vrijedi pratiti" on /wallets (every user): at most CARD_N CONFIRMED groups of
                     "kupuje prije pumpe", each with ONE sentence built from its numbers; the honest empty card when
                     none is confirmed yet. No PnL, no copy test, no exclusions here (those are the admin's page).
  reason(g, b)       the sentence of one group (b: its bundle row, when the group is also one)
  demo_html(owner)   "Demo praćenje novčanika (bez pravog novca)" on /pravi-trade while the real-money pause is on:
                     the open and recently closed demo trades of the sources in novpodaci.DEMO_SOURCES, each with the
                     wallet / group it followed and that one sentence. Display only: it reads league.db, never trades.

Neutral wording always: "kupuje prije pumpe", never a statement about who a wallet belongs to.
"""
import time
from urllib.parse import quote

from ui import novpodaci as P
from ui import redak as rd

CARD_N = 10
CARD_TITLE = "Novčanici koje vrijedi pratiti"
CARD_EMPTY = ("Još skupljamo dokaze. Prvi popis objavit ćemo kad novčanici budu potvrđeni na novijim podacima.")
CARD_FOOT = "Statistika iz javnih podataka s lanca, nije financijski savjet; prošli rezultat ne jamči budući."
DEMO_TITLE = "Demo praćenje novčanika (bez pravog novca)"

CSS = """<style>
.nk-card{border:1px solid var(--line);border-radius:14px;background:var(--card);padding:6px 16px 12px;margin:14px 0 18px}
.nk-card h2{font-size:18px;font-weight:700;margin:10px 0 4px;letter-spacing:-.01em}
.nk-row{display:flex;flex-direction:column;gap:4px;padding:11px 0;border-bottom:1px solid var(--line)}
.nk-row:last-of-type{border-bottom:0}
.nk-a{display:flex;align-items:center;gap:8px;flex-wrap:wrap;font-size:14px}
.nk-a code{font-size:13.5px;background:var(--soft);border-radius:6px;padding:2px 6px;color:var(--fg)}
.nk-a a{color:var(--acc);text-decoration:none;font-size:13px}
.nk-a button.nk-cp{font:inherit;font-size:12.5px;border:1px solid var(--line);border-radius:6px;background:var(--card);
 color:var(--fg);padding:2px 8px;cursor:pointer}
.nk-a button.nk-cp:hover{border-color:var(--acc);color:var(--acc)}
.nk-s{font-size:14.5px;line-height:1.45;color:var(--fg)}
.nk-foot{font-size:12.5px;color:var(--mut);margin:10px 0 0;line-height:1.4}
.nk-empty{font-size:14.5px;color:var(--mut);margin:8px 0 6px;line-height:1.45}
.nk-tag{font-size:12px;color:var(--mut)}
</style>"""
# capture phase + stopPropagation: a copy button inside a table row never also opens / closes the row (rangtable.JS)
COPY_JS = ("<script>if(!window.__nkcp){window.__nkcp=1;document.addEventListener('click',e=>{const b=e.target.closest"
           "&&e.target.closest('button[data-cp]');if(!b)return;e.stopPropagation();e.preventDefault();"
           "const m=b.dataset.cp,t=b.textContent;(navigator.clipboard?navigator.clipboard.writeText(m):Promise.reject())"
           ".then(()=>{b.textContent='Kopirano';setTimeout(()=>b.textContent=t,1500)},()=>prompt('Kopiraj adresu:',m))},true)}"
           "</script>")


def short(w):
    w = str(w or "")
    return w if len(w) <= 12 else f"{w[:4]}…{w[-4:]}"


def addr_html(w, full=False):
    """The address (short or full) + a copy button + Solscan in a new tab; all escaped."""
    w = str(w or "")
    if not w:
        return rd.DASH
    shown = w if full else short(w)
    return (f'<code translate=no title="{rd.h(w)}">{rd.h(shown)}</code>'
            f'<button type=button class=nk-cp data-cp="{rd.h(w)}" aria-label="Kopiraj adresu {rd.h(short(w))}">Kopiraj</button>'
            f'<a href="https://solscan.io/account/{quote(w)}" target=_blank rel="noopener noreferrer">Solscan ↗</a>')


def _na_tokenu(n):
    n = int(n or 0)
    return "tokenu" if n % 10 == 1 and n % 100 != 11 else "tokena"


def _u_skoku(n):
    n = int(n or 0)
    if n % 10 == 1 and n % 100 != 11:
        return "skoku"
    if n % 10 in (2, 3, 4) and n % 100 not in (12, 13, 14):
        return "skoka"
    return "skokova"


def reason(g, b=None):
    """One plain sentence from a group's numbers (and its bundle row, when it is one)."""
    if b and (b.get("n_pumps") or 0) >= 2 and (b.get("n_members") or 0) >= 2:
        k, n = int(b["n_members"]), int(b["n_pumps"])
        return (f"Skupina od {k} povezanih novčanika koja je u {n} {_u_skoku(n)} kupila zajedno prije rasta"
                + ("; potvrđeno na novijim podacima." if g.get("confirmed_ts") else "."))
    n, n15 = int(g.get("n_tokens") or 0), int(g.get("n_pumps15") or 0)
    k = int(g.get("n_members") or len(g.get("members") or []) or 1)
    who = f"Skupina od {k} povezanih novčanika kupila je" if k > 1 else "Kupio je"
    sold = "prodala u rast" if k > 1 else "prodao u rast"
    big = f" ({n15} od 15 M $ naviše)" if n15 else ""
    tail = "; potvrđeno na novijim podacima." if g.get("confirmed_ts") else "; još se potvrđuje na novijim podacima."
    return f"{who} prije skoka na {n} {_na_tokenu(n)}{big} i {sold}{tail}"


def _bundle_by_owner(con):
    out = {}
    for b in P.bundles(con, limit=200):
        if b["bid"].startswith("o:"):
            out[b["bid"][2:]] = b
    return out


def card_html(con=None, n=CARD_N):
    """The card (HTML). Only confirmed groups; the honest empty card before the first one."""
    own = con is None
    con = con if con is not None else P.ins_con()
    try:
        gs = P.confirmed_groups(con, n) if con is not None else []
        bun = _bundle_by_owner(con) if gs else {}
    finally:
        if own and con is not None:
            con.close()
    rows = []
    for g in gs:
        lead = (g["members"] or [g["owner"]])[0]
        more = len(g["members"]) - 1
        rows.append('<div class=nk-row><div class=nk-a>' + addr_html(lead)
                    + (f'<span class=nk-tag>+{more} povezan{"" if more == 1 else "ih" if more >= 5 else "a"}</span>'
                       if more > 0 else "")
                    + f'</div><div class=nk-s>{rd.h(reason(g, bun.get(g["owner"])))}</div></div>')
    body = "".join(rows) if rows else f'<p class=nk-empty>{rd.h(CARD_EMPTY)}</p>'
    return (f'{CSS}<section class=nk-card id=vrijedi-pratiti><h2>{rd.h(CARD_TITLE)}</h2>{body}'
            f'<p class=nk-foot>{rd.h(CARD_FOOT)}</p></section>{COPY_JS}')


# ---------- the Autopilot's demo section -----------------------------------------------------------------------------

def _wallet_sentence(h):
    if not h or not h.get("scored"):
        return "povijest novčanika još se računa."
    bits = [f"{rd.num(h.get('closed'))} zatvorenih tradeova",
            f"{rd.pct(h.get('win_rate'), sign=False, frac=True)} u plusu"]
    if h.get("realized") is not None:
        bits.append(f"ostvareno {rd.sol(h.get('realized'), 2, sign=True)}")
    txt = ", ".join(bits) + ("; dokazan dvaput na starijim i novijim danima." if h.get("proven") else ".")
    return txt[:1].upper() + txt[1:]


def _why(t, icon, hist, bundles=None):
    f = t.get("follow")
    if f and f[0] == "bundle":
        b = (bundles or {}).get(f[1]) or next((x for k, x in (bundles or {}).items() if k[2:] == f[1]), None)
        who = f"bundle {short(f[1][2:] if str(f[1])[:2] in ('o:', 'p:') else f[1])}" + (
            f" (novčanik {short(f[2])})" if f[2] else "")
        return who, (reason({}, b) if b else "bundle više nije na popisu.")
    if f and f[0] == "group":
        g = P.group_of(icon, f[1]) if icon is not None else None
        who = f"grupa {short(f[1])} (novčanik {short(f[2])})"
        if g:
            return who, reason(g)
        old = P.i2_group_why(icon, f[1]) if icon is not None else None
        return who, (str(old[0]) if old and old[0] else "razlog grupe još nije spremljen.")
    if f and f[0] == "wallet":
        return f"novčanik {short(f[1])}", _wallet_sentence(hist.get(f[1]))
    return str(t.get("source") or "")[:80], ""


def _ret_cell(t):
    if t["status"] == "open":
        return '<span class=mut>otvoreno</span>'
    r = t.get("ret")
    if r is None:
        return rd.DASH
    tone = rd.tone(r)
    return f'<span class="{tone}">{rd.h(rd.pct(r, 1, sign=True, frac=True))}</span>'


MC_HR = {"15-200M": "15–200 M $", "2-15M": "2–15 M $", "<2M": "ispod 2 M $", ">200M": "iznad 200 M $", "?": "MC nepoznat"}


def _summary_line(st):
    """Per source and MC bucket from insajderi/pp_live.day_stats: the closed trades' mean NET of the real round trip
    (never under 3 %), the same rule as the data job's daily line."""
    def part(src, key="svi"):
        x = (st.get(src) or {}).get(key) or {}
        return (f"n={rd.num(x['n'])}, {rd.pct(x.get('mean_pct'), 1, sign=True)}" if x.get("n") else "n=0")
    return ("Zatvoreni, neto nakon stvarnog troška (nikad ispod 3 %): prije pumpe 15–200 M $ "
            f"{part('prije_pumpe', '15-200M')}; 2–15 M $ {part('prije_pumpe', '2-15M')}; kandidati "
            f"{part('prije_pumpe_kandidat')}; bundle {part('bundle')}; kopija dokazanih {part('kopija')}; "
            f"insajderi2 {part('insajderi2')}.")


def demo_html(owner=False, now=None, path_league=None):
    """The section while real money is paused; "" otherwise (the page hides the card)."""
    if not P.pause_on():
        return ""
    now = int(now or time.time())
    opened, closed = P.demo_trades(P.DEMO_SOURCES, 20, 14, path_league, now)
    s = P.demo_summary(P.DEMO_SOURCES, 14, path_league, now)
    icon = P.ins_con()
    try:
        ws = [t["follow"][1] for t in opened + closed if t.get("follow") and t["follow"][0] == "wallet"]
        hist = {h["wallet"]: h for h in P.wallet_history(ws, extra_top=0)[0]} if ws else {}
        bundles = {b["bid"]: b for b in P.bundles(icon, 200)} if icon is not None else {}
        rows = []
        for t in opened + closed:
            who, why = _why(t, icon, hist, bundles)
            tok = t.get("token") or ""
            name = rd.h(t.get("symbol") or short(tok))
            label = P.DEMO_LABEL.get(t.get("kind"), t.get("kind") or "")
            tag = " · ".join(x for x in (label, MC_HR.get(t.get("mc_bucket") or "?", t.get("mc_bucket"))) if x)
            rows.append(
                f'<tr><td><a href="/token/{quote(tok)}" translate=no>{name}</a><br><span class=mut '
                f'style="font-weight:400;font-size:12.5px">{rd.h(tag)}</span></td>'
                f'<td class=mut>{rd.h(time.strftime("%d.%m. %H:%M", time.localtime(t["opened_ts"])) if t.get("opened_ts") else rd.DASH)}'
                f'<br>{rd.h(rd.usd(t.get("size_usd")))}</td><td>{_ret_cell(t)}</td>'
                f'<td class="nk-why wrap"><b>{rd.h(who)}</b>{": " + rd.h(why) if why else ""}</td></tr>')
    finally:
        if icon is not None:
            icon.close()
    rng = ""
    if s["from"] and s["to"]:
        rng = f' ({time.strftime("%d.%m.", time.localtime(s["from"]))}–{time.strftime("%d.%m.", time.localtime(s["to"]))})'
    summ = f"Otvoreno: {rd.num(s['open'])}; zatvoreno u 14 dana: {rd.num(s['closed'])}{rng}."
    table = ('<div class=rt-wrap><table class="rt nk-dt"><thead><tr><th scope=col>Token</th><th scope=col>Ulaz</th>'
             '<th scope=col>Rezultat (bez troška)</th><th scope=col>Zašto</th></tr></thead><tbody>' + "".join(rows)
             + '</tbody></table></div>') if rows else (
        '<p class=apx-empty>Demo još nije otvorio nijedan trade po novčanicima. Kupuje kad praćeni novčanik ili grupa '
        'kupi novi token.</p>')
    from ui import rangtable
    return (rangtable.CSS + f'<style>.nk-dt{{min-width:640px}}.nk-dt td.nk-why{{white-space:normal;text-align:left;min-width:280px;'
            f'line-height:1.4}}.nk-dt td:nth-child(2),.nk-dt th:nth-child(2),.nk-dt th:nth-child(4){{text-align:left}}table.nk-dt.cards{{min-width:0!important}}table.nk-dt.cards td.nk-why{{min-width:0;max-width:none;grid-column:1/-1}}</style>'
            f'<h2 class=apx-h2 data-sec="">{rd.h(DEMO_TITLE)}</h2>'
            f'<p class=apx-mut>Pravi novac je pauziran; demo računi prate novčanike i grupe koje kupuju prije pumpe. '
            f'{rd.h(summ)}</p><p class=apx-mut style="margin-top:4px">{rd.h(_summary_line(s.get("stats") or {}))}</p>'
            f'{table}')
