"""Makro influenceri za sve korisnike aplikacije i dnevno osvježavanje javnih stranica (15.11., vlasnik: "Možeš ti
odmah objaviti te stranice javno i staviti ih za sve korisnike aplikacije pod influencere, makroinfluencer i tab ...
kako budeš punio podatke o makroinfluencerima na dnevnoj bazi, osvježavati i stranice koje vide korisnici i Google").

  view(fresh)       one read of makroinf.db for every view: the rank rows split into ranked (10+ measured episodes)
                    and "nedovoljno dokaza", the stance on BTC and the consensus index of the most accurate accounts.
                    fresh=True (members, the app) = as of the last scoring; fresh=False (the public pages) = 7 days
                    ago (PUBLIC_DELAY_S), like the public influencer pages keep fresh calls for members.
  tab_html()        the "Makro" tab of /kol (Influenceri) for every logged-in user, fetched from /kol-makro/lista:
                    since 15.11. navečer first the interpretation (makroinf/appviews.py: the market mood with its
                    sources, the topics of the day, the stance changes, per asset), then the ranking
  profile_page(h)   /kol-makro/<handle>: one account in the app (fresh stance, every call incl. the last 7 days)
  library(qs)       /kol-makro/biblioteka: every stored post with its classification, filtered (makroinf/library.py)
  stamp() / sync()  freshness in the UI process: the newest score time and the owner switch; when either moves, every
                    cached copy of the macro pages is dropped (public pages, sitemap, robots, the app tab, profiles),
                    so users and Google see the numbers of the last scoring (the light one every 30 min, the night's)
  refreshed(con)    after every scoring (makroinf/run.py): kv "javno" {ts, racuna, sitemap}; the night run logs
                    "makroinf: javne stranice osvježene (N računa, M u sitemapu)"

Never in any view: keys, env names, internal services, costs, wallets or token addresses. Deletions are "naknadno
nedostupno" (never an accusation); the integrity badge is never red.
"""
import re
import threading
import time
from urllib.parse import quote

from makroinf import report, rules, score, store

D = 86400
PUBLIC_DELAY_S = 7 * D
MIN_EP = rules.LOCKED["min_episodes"]
HANDLE = re.compile(r"[A-Za-z0-9_]{1,15}")
GONE = score.GONE
LEAN = 0.25            # |index| from which the consensus reads bullish / bearish (the smallest locked threshold)
STAMP_S = 20           # the UI process looks at makroinf.db at most this often
APP = "/kol-makro"     # in-app routes: /kol-makro/lista (the tab), /kol-makro/<handle> (one account)
TAB_PAGE = 100         # accounts in one view of the app list (16.11.: up to 800 accounts): the rest is /kol-makro?str=N

CAT_HR = {"ta": "Trader / TA", "makro": "Makro / on-chain", "edukacija": "YouTube / edukacija",
          "memecoin": "Memecoin KOL", "vijesti": "Vijesti / agregator"}
DIR_HR = {"up": "gore", "down": "dolje", "bottom_in": "dno je tu", "top_in": "vrh je tu", "range": "raspon"}
SIGN = {"up": 1, "bottom_in": 1, "down": -1, "top_in": -1, "range": 0}
ASSET_HR = {"BTC": "BTC", "ETH": "ETH", "SOL": "SOL", "alts": "altcoini", "memes": "meme coini", "total": "kripto tržište"}
RES_HR = {"hit": "pogodak", "miss": "promašaj", "flat": "bez jasnog pomaka", "ceka": "čeka", "neaktiviran":
          "uvjet nije ispunjen", "bez_podataka": "nema cijene", "dugo": "dugoročno (ne mjeri se)"}
HZ = {"7": "7\u00a0d", "30": "30\u00a0d", "oba": "7\u00a0+\u00a030\u00a0d", "dugo": ">\u00a060\u00a0d"}


def on():
    """The owner switch makroinf_javno is "live" (the public pages exist). Never raises: unreadable = off."""
    try:
        from trade import settings
        return settings.flag(settings.MAKROINF_JAVNO) == "live"
    except Exception:  # noqa: BLE001
        return False


# ---------- the view model ---------------------------------------------------------------------------------------------

def lean(v):
    """"bull" / "bear" / "neutral" of an index value (None = no consensus)."""
    if v is None:
        return None
    return "bull" if v >= LEAN else "bear" if v <= -LEAN else "neutral"


def index_btc(fresh=True, now=None, con=None):
    """The consensus of the most accurate accounts on BTC (prospective availability, kind "top"): {"v", "n", "day",
    "lean"} of the newest day (fresh) or the newest at least PUBLIC_DELAY_S old; None without one."""
    own = con is None
    con = con or store.ro()
    if con is None:
        return None
    try:
        sql = ("SELECT day, value, coverage FROM index_d WHERE asset = 'BTC' AND mode = 'prospektivno' AND kind = 'top' "
               "AND value IS NOT NULL")
        args = ()
        if not fresh:
            sql += " AND day <= ?"
            args = ((int(now or time.time()) - PUBLIC_DELAY_S) // D * D,)
        r = store.q(con, sql + " ORDER BY day DESC LIMIT 1", args)
    finally:
        if own:
            con.close()
    if not r:
        return None
    day, v, n = r[0]
    return {"v": v, "n": int(n or 0), "day": int(day), "lean": lean(v)}


def view(fresh=True, d=None, now=None):
    """Everything a list view shows, or None before the first scores (see the module text)."""
    d = d or report.data()
    if not d or not d.get("scores"):
        return None
    stav = (((d.get("stavovi") or {}).get("sada" if fresh else "prije_7d") or {}).get("BTC")) or {}
    rows = []
    for r in report.rank_rows(d):
        if not HANDLE.fullmatch(r["handle"] or ""):
            continue
        st = stav.get(r["handle"])
        r = dict(r, few=r["presuda"] == score.VERDICT_FEW,
                 stav={"dir": st["dir"], "ts": st["ts"], "id": str(st.get("id") or "")} if st else None)
        rows.append(r)
    ranked = [r for r in rows if not r["few"]]
    few = sorted((r for r in rows if r["few"]), key=lambda r: (-r["n_epizoda"], r["handle"].lower()))
    s = d.get("summary") or {}
    oc = s.get("outcomes") or {}
    con = store.ro()
    try:
        idx = index_btc(fresh, now, con)
        k_top = len(store.kv_json(con, "top_sada", []) or []) if con is not None else 0
    finally:
        if con is not None:
            con.close()
    return {"ranked": ranked, "few": few, "n": len(rows), "index": idx, "k_top": k_top, "ts": s.get("ts"),
            "episodes": s.get("episodes", 0), "measured": sum(oc.get(k, 0) for k in ("hit", "miss", "flat")),
            "scores": d.get("scores") or {}, "accounts": d.get("accounts") or {}}


def episodes(h, fresh=True, now=None, limit=60):
    """[(eid, asset, direction, hz, t_call, "7:hit,30:ceka", first_id)] newest first (public: older than
    PUBLIC_DELAY_S only) and {tweet id: deletion state}."""
    con = store.ro()
    if con is None:
        return [], {}
    cut = (int(now or time.time()) - PUBLIC_DELAY_S) if not fresh else 2 ** 62
    try:
        rows = store.q(con, """SELECT eid, asset, direction, hz, MAX(t_call), GROUP_CONCAT(horizon || ':' || res),
            first_id FROM outcomes WHERE lower(handle) = lower(?) AND rules_v = ? AND t_call < ? GROUP BY eid
            ORDER BY MAX(t_call) DESC LIMIT ?""", (h, rules.RULES_VERSION, cut, int(limit)))
        gone = {str(i): s for i, s in store.q(con, "SELECT id, state FROM deletions WHERE lower(handle) = lower(?) AND "
                                                   "state IS NOT NULL", (h,))}
    finally:
        con.close()
    return rows, gone


def sitemap_count(v=None):
    """Account pages offered to search engines: every account (15.11. navečer, the owner: "Neka Google sve indeksira";
    0 while the switch is off)."""
    if not on():
        return 0
    v = v or view(fresh=False)
    return v["n"] if v else 0


# ---------- freshness: after every scoring ------------------------------------------------------------------------------

_LOCK = threading.Lock()
_STAMP = {"at": -1e9, "v": None}     # memo of stamp()
_SEEN = {"v": None}                  # the stamp the caches were last dropped for
_FRAG = {}                           # key -> (stamp, html) of the app views built in this process


def stamp(force=False):
    """(newest score time, kv "javno" time of the last refreshed(), owner switch on) from makroinf.db, memoised
    STAMP_S seconds in this process."""
    now = time.monotonic()
    with _LOCK:
        if not force and _STAMP["v"] is not None and now - _STAMP["at"] < STAMP_S:
            return _STAMP["v"]
    con = store.ro()
    try:
        ts = int(((store.q(con, "SELECT MAX(ts) FROM scores") or [[0]])[0][0]) or 0) if con is not None else 0
        pub = int((store.kv_json(con, "javno", {}) or {}).get("ts") or 0) if con is not None else 0
    finally:
        if con is not None:
            con.close()
    v = (ts, pub, on())
    with _LOCK:
        _STAMP.update(at=now, v=v)
    return v


def _is_ours(path):
    return bool(re.fullmatch(r"/macro-influencers(/\d+)?|/hr/makro-influenceri(/\d+)?|/macro-influencer/.*|"
                             r"/hr/makro-influencer/.*", path or ""))


def drop(everything=False):
    """Drop the cached copies of the macro pages in this process: the public pages (all of them when the switch moved:
    every page carries the menu link), the sitemap and robots.txt, the app tab and the in-app account pages.
    Returns how many copies were dropped."""
    n = 0
    try:
        from ui import public
        with public._lock:
            for k in list(public._cache):
                if everything or _is_ours(k) or k in ("/sitemap.xml", "/robots.txt"):
                    public._cache.pop(k, None)
                    n += 1
    except Exception:  # noqa: BLE001 - the copies then simply live out their own cache time
        pass
    try:
        from ui import pagecache
        with pagecache._lock:
            for k in list(pagecache._store):
                if str(k[0]).startswith(APP):
                    pagecache._store.pop(k, None)
                    n += 1
    except Exception:  # noqa: BLE001
        pass
    with _LOCK:
        n += len(_FRAG)
        _FRAG.clear()
    return n


def sync(force=False):
    """In the UI process, before a macro page is served: when the scores (or the switch) moved since the last look,
    every cached copy is dropped. True when something was dropped."""
    v = stamp(force)
    with _LOCK:
        old = _SEEN["v"]
        if old == v:
            return False
        _SEEN["v"] = v
    drop(everything=old is not None and old[-1] != v[-1])
    return True


def _cached(key, build):
    v = stamp()
    with _LOCK:
        hit = _FRAG.get(key)
    if hit and hit[0] == v:
        return hit[1]
    html = build()
    with _LOCK:
        if len(_FRAG) > 200:
            _FRAG.clear()
        _FRAG[key] = (v, html)
    return html


def refreshed(con, now=None):
    """After a scoring (makroinf/run.py, the light one and the night's): kv "javno" with what the pages now show.
    The UI process notices the new score time itself (sync). Returns (accounts, account pages in the sitemap)."""
    now = int(now or time.time())
    d = report.data(con=con)
    v = view(fresh=False, d=d, now=now) if d else None
    n = v["n"] if v else 0
    m = n if v and on() else 0   # every profile is in the sitemap (15.11. navečer: "Neka Google sve indeksira")
    store.kv(con, "javno", {"ts": now, "racuna": n, "sitemap": m, "uzivo": on()})
    return n, m


def refreshed_line(n, m):
    tail = "" if on() else "; prekidač makroinf_javno isključen: stranice su 404"
    return store.PREFIX + f"javne stranice osvježene ({n} računa, {m} u sitemapu{tail})"


# ---------- formatting -------------------------------------------------------------------------------------------------

def _pct(x):
    from ui import redak as R
    return R.pct(x, sign=False, frac=True)


def _pp(x):
    from ui import redak as R
    return "–" if x is None else f"{R.num(x * 100, 1, sign=True)}{R.NBSP}pp"


def _ci(lo, hi):
    if lo is None or hi is None:
        return ""
    return f"{round(lo * 100)}–{round(hi * 100)}\u00a0%"


def _day(ts):
    return time.strftime("%d.%m.", time.gmtime(ts)) if ts else "–"


def _date(ts):
    return time.strftime("%d.%m.%Y.", time.gmtime(ts)) if ts else "–"


def zg(ts, fmt="%d.%m. %H:%M"):
    """A Zagreb clock time whatever zone the server runs in (Render: UTC); "" without ts."""
    if not ts:
        return ""
    try:
        import datetime as _dt
        import zoneinfo
        return _dt.datetime.fromtimestamp(float(ts), zoneinfo.ZoneInfo("Europe/Zagreb")).strftime(fmt)
    except Exception:  # noqa: BLE001 - no zone data: UTC, said so
        return time.strftime(fmt, time.gmtime(ts)) + " UTC"


def _idx_txt(v):
    from ui import redak as R
    return "–" if v is None else R.num(v, 2, sign=True)


PRED_TONE = {"bolji od baznih strategija": "good", "lošiji od baznih strategija": "bad"}
PRED_WORD = {"bolji od baznih strategija": "Bolji od jednostavnih osnova",
             "lošiji od baznih strategija": "Ispod jednostavnih osnova",
             "ne razlikuje se od baznih strategija": "Ne razlikuje se od jednostavnih osnova"}
ECON_TONE = {"dodaje vrijednost": "good", "gubi prema uvijek-bik": "bad"}
LEAN_HR = {"bull": ("Bikovski", "good"), "bear": ("Medvjeđi", "bad"), "neutral": ("Neutralno", "")}

CSS = """
.mi-how{background:var(--soft);border-radius:14px;padding:12px 14px;margin:14px 0 0;font-size:14px;line-height:1.45;color:var(--mut)}
.mi-how b{color:var(--fg);font-weight:600}.mi-how a{color:var(--acc);text-decoration:none;font-weight:500}
.mi-how p{margin:0}.mi-how p+p{margin-top:6px}
.mi-list{margin:4px 0 0}
.mi-r{display:grid;grid-template-columns:24px minmax(0,1fr) auto 12px;column-gap:10px;align-items:center;padding:12px 0;
border-bottom:1px solid var(--line);color:var(--fg);text-decoration:none}
a.mi-r:hover .t b{color:var(--acc)}
.mi-r .rk{font-size:15px;color:var(--mut);align-self:start;padding-top:2px}
.mi-r .t{font-size:17px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.mi-r .t b{font-weight:600}
.mi-r .t span{font-size:13px;color:var(--mut);margin-left:6px}
.mi-r .s{font-size:15px;color:var(--mut);margin-top:1px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.mi-up{color:var(--good);font-weight:500}.mi-dn{color:var(--bad);font-weight:500}.mi-fl{color:var(--fg);font-weight:500}
b.mi-up,b.mi-dn,b.mi-fl{font-weight:600}
.mi-r .bd{display:flex;flex-wrap:wrap;gap:5px;margin-top:7px}
.mi-b{display:inline-flex;align-items:baseline;gap:4px;font-size:12.5px;line-height:1;padding:5px 8px;border-radius:999px;
background:var(--soft);color:var(--fg);border:1px solid var(--line);white-space:nowrap}
.mi-b i{font-style:normal;color:var(--mut)}.mi-b.good{background:var(--goodbg);border-color:color-mix(in srgb,var(--good) 30%,transparent)}
.mi-b.bad{background:var(--badbg);border-color:color-mix(in srgb,var(--bad) 25%,transparent)}
.mi-b.few{color:var(--mut);background:transparent;border-style:dashed}
.mi-r .e{text-align:right;align-self:start;padding-top:2px}.mi-r .e b{display:block;font-size:17px;font-weight:600}
.mi-r .e span{font-size:13px;color:var(--mut)}
.mi-r .chev{width:8px;height:8px;border-right:2px solid var(--line2);border-top:2px solid var(--line2);transform:rotate(45deg)}
.mi-r.few .t b{font-weight:500}.mi-r.few .e b{font-weight:400;color:var(--mut)}
.mi-foot{font-size:13px;color:var(--mut);margin:14px 0 0;line-height:1.5}.mi-foot a{color:var(--acc);text-decoration:none}
.mi-pg{display:flex;flex-wrap:wrap;gap:8px 12px;align-items:center;justify-content:space-between;margin:14px 0 0;font-size:14px;
color:var(--mut)}.mi-pg a{border:1px solid var(--line);border-radius:999px;padding:8px 14px;color:var(--fg);
text-decoration:none;font-weight:600;background:var(--card)}
.mi-3{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px;margin:16px 0 0}
@media(max-width:640px){.mi-3{grid-template-columns:1fr}}
.mi-c{background:var(--card);border:1px solid var(--line);border-radius:16px;padding:14px 16px}
.mi-c .l{font-size:13px;color:var(--mut)}.mi-c .v{font-size:26px;font-weight:700;letter-spacing:-.02em;margin:2px 0}
.mi-c .w{font-size:14px;color:var(--mut);line-height:1.4}.mi-c .w b{color:var(--fg);font-weight:600}
.mi-ep{display:grid;grid-template-columns:minmax(0,1fr) auto;column-gap:12px;padding:11px 0;border-bottom:1px solid var(--line);align-items:center}
.mi-ep .t{font-size:16px;font-weight:600}.mi-ep .s{font-size:14px;color:var(--mut);margin-top:1px}
.mi-ep .r{text-align:right;font-size:15px;font-weight:600}.mi-ep .r>span{display:block;white-space:nowrap}
.mi-ep .r .mut{font-weight:400;color:var(--mut)}.mi-ep .r .good{color:var(--good)}.mi-ep .r .bad{color:var(--bad)}
.mi-ep .p{display:block;font-size:13px;font-weight:400;margin-top:2px}.mi-ep .p a{color:var(--acc);text-decoration:none}
.mi-ep .p span{color:var(--mut)}
"""


def _stance_html(st, fresh=True):
    """"BTC: gore · 12.11." with the colour of the direction; "BTC: bez stava" without one."""
    if not st:
        return "BTC: <span>bez stava</span>"
    from ui.html import esc
    sg = SIGN.get(st["dir"], 0)
    cls = "mi-up" if sg > 0 else "mi-dn" if sg < 0 else "mi-fl"
    arrow = "↑ " if sg > 0 else "↓ " if sg < 0 else "↔ "
    return f"BTC: <span class={cls}>{arrow}{esc(DIR_HR.get(st['dir'], st['dir']))}</span> · od {_day(st['ts'])}"


def _badges(r):
    from ui.html import esc
    if r["few"]:
        return f"<span class='mi-b few'>nedovoljno dokaza · treba {MIN_EP}</span>"
    lo, hi = r["wilson95"]
    e, g = r["ekonomski"], r["integritet"]
    p_t = PRED_TONE.get(r["presuda"], "")
    e_t = ECON_TONE.get(e.get("presuda"), "")
    return (f"<span class='mi-b {p_t}' title='prediktivno: {esc(r['presuda'])}'>Pogodak {esc(_pct(r['pogodak']))} "
            f"<i>{esc(_ci(lo, hi))}</i></span>"
            f"<span class='mi-b {e_t}' title='ekonomski: povrat praćenja prema uvijek-bik po izjavi'>Povrat "
            f"{esc(_pp(e.get('razlika')))}</span>"
            f"<span class=mi-b title='integritet: objave koje više ne vidimo'>Nedostupno "
            f"{g.get('naknadno_nedostupno') or 0}/{g.get('makro_izjava') or 0}</span>")


def _row(r, rank=None):
    from ui.html import esc
    cat = CAT_HR.get(r.get("category") or "", "")
    return (f"<a class='mi-r{' few' if r['few'] else ''}' href='{APP}/{quote(r['handle'])}'>"
            f"<span class=rk>{'' if rank is None else rank}</span><div class=m>"
            f"<div class=t><b>@{esc(r['handle'])}</b>" + (f"<span>{esc(cat)}</span>" if cat else "") + "</div>"
            f"<div class=s>{_stance_html(r['stav'])}</div><div class=bd>{_badges(r)}</div></div>"
            f"<div class=e><b>{r['n_epizoda']}</b><span>epizoda</span></div>"
            "<span class=chev aria-hidden=true></span></a>")


def _index_hero(v, now=None):
    from ui import redak as R
    ix = v.get("index")
    lab = "Konsenzus najtočnijih o BTC-u"
    if not ix or not ix["n"]:
        return R.hero("Još nema konsenzusa", "Indeks se računa kad najtočniji računi (5+ izmjerenih ishoda) imaju stav "
                      "o BTC-u; dotad svaki račun stoji sam za sebe.", label=lab)
    word, tone = LEAN_HR[ix["lean"]]
    from makroinf import index as mindex
    small = ix["n"] < mindex.INDEX_LOCKED["min_coverage"]
    k = v.get("k_top") or 0
    who = f"{ix['n']} od {k} najtočnijih ima stav" if k else f"{ix['n']} računa sa stavom"
    facts = R.cat(R.dot(tone), f"{_idx_txt(ix['v'])} · {who} · izračun {zg(v.get('ts'))}")
    why = ("Od −1 (svi medvjeđi) do +1 (svi bikovski); glasaju samo najtočniji računi koji imaju stav."
           + (" Još malo računa sa stavom, pa je signal slab." if small else ""))
    return R.hero(word, why, label=lab, facts=facts)


def _how(public_link):
    from ui.html import esc
    link = (f" <a href='{esc(public_link)}'>Cijela metodologija →</a>" if public_link else "")
    return ("<div class=mi-how><p><b>Kako mjerimo.</b> Svaku izjavu o smjeru tržišta mjerimo prema cijeni nakon 7 i 30 "
            "dana, pravilima zaključanima unaprijed, i uspoređujemo s jednostavnim osnovama na istim datumima. "
            f"<b>Pogodak</b>, <b>povrat</b> praćenja i <b>nedostupne</b> objave su tri odvojene ocjene; ispod {MIN_EP} "
            f"izmjerenih epizoda nema ranga.{link}</p></div>")


def tab_html(now=None, page=1):
    """The "Makro" tab of /kol (Croatian; the app's English layer translates it), cached until the next scoring.
    page: which TAB_PAGE accounts of the list (the tab itself is page 1; the next ones are /kol-makro?str=N)."""
    try:
        page = min(999, max(1, int(page or 1)))
    except (TypeError, ValueError):
        page = 1
    return _cached(("tab", page), lambda: _tab_html(now, page))


def _pager(page, pages, total, lo, hi):
    """"Show more" of the app list: the next / previous TAB_PAGE accounts as their own view."""
    if pages <= 1:
        return ""
    href = lambda p: APP + (f"?str={p}" if p > 1 else "")  # noqa: E731
    prev = f"<a href='{href(page - 1)}'>← Prethodnih {TAB_PAGE}</a>" if page > 1 else "<span></span>"
    nxt = (f"<a href='{href(page + 1)}'>Sljedećih {min(TAB_PAGE, total - hi)} →</a>" if page < pages else
           "<span></span>")
    return (f"<nav class=mi-pg aria-label='Još računa'>{prev}<span>Računi {lo + 1}–{min(hi, total)} od {total} · "
            f"stranica {page} od {pages}</span>{nxt}</nav>")


def _tab_html(now=None, page=1):
    from makroinf import appviews
    from ui import redak as R
    v = view(fresh=True, now=now)
    pub = "/hr/makro-influenceri#kako-mjerimo" if on() else None
    if not v:
        return (f"<style>{CSS}{appviews.CSS}</style>" + appviews.subnav("/kol#makro")
                + str(R.hero("Još nema ocjena", "Makro influencere tek mjerimo: objave se razvrstavaju, a prve ocjene "
                             "stižu nakon prvog izračuna.", label="Makro influenceri")) + _how(pub))
    total = len(v["ranked"]) + len(v["few"])
    pages = max(1, -(-total // TAB_PAGE))
    page = min(page, pages)
    lo, hi = (page - 1) * TAB_PAGE, page * TAB_PAGE
    ranked = list(enumerate(v["ranked"], 1))[lo:hi]
    few = v["few"][max(0, lo - len(v["ranked"])):max(0, hi - len(v["ranked"]))]
    out = [f"<style>{CSS}</style>"]
    if page == 1:
        out += [appviews.overview_html(), str(R.section("Konsenzus i rang", sid="makro-konsenzus")),
                str(_index_hero(v, now)), _how(pub)]
    if ranked or page == 1:
        out.append(str(R.section(f"Najtočniji · {len(v['ranked'])}", sid="makro-rang")))
    if ranked:
        out.append("<div class=mi-list>" + "".join(_row(r, i) for i, r in ranked) + "</div>")
    elif page == 1:
        out.append(str(R.hint(f"Još nijedan račun nema {MIN_EP} izmjerenih epizoda; poredak se pojavi čim ih skupe.")))
    if few:
        out.append(str(R.section(f"Skupljaju dokaze · {len(v['few'])}", sid="makro-malo")))
        out.append(str(R.hint(f"Manje od {MIN_EP} izmjerenih epizoda: bez ranga i bez presude, samo ono što su rekli.")))
        out.append("<div class='mi-list mi-few'>" + "".join(_row(r) for r in few) + "</div>")
    out.append(_pager(page, pages, total, lo, hi))
    foot = (f"Ocjene od {zg(v.get('ts'), '%d.%m.%Y. %H:%M')} · {v['n']} računa · "
            f"{v['episodes']} epizoda, izmjereno {v['measured']}. Stav o BTC-u je svjež (javne stranice ga pokazuju s "
            "odgodom od 7 dana).")
    if on():
        foot += " <a href='/hr/makro-influenceri'>Javna stranica →</a>"
    out.append(f"<p class=mi-foot>{foot}</p>")
    return "".join(out).replace('<h2 class="ms-h2"', '<h2 class="ms-h2 nosec"')   # no chip row (kol._calm)


def profile_page(handle, now=None):
    """(title, body) of /kol-makro/<handle>, or None (unknown handle)."""
    if not HANDLE.fullmatch(handle or ""):
        return None
    return _cached(("prof", handle.lower()), lambda: _profile(handle, now))


def _profile(handle, now=None):
    from ui import kol, redak as R
    from ui.html import esc
    v = view(fresh=True, now=now)
    me = next((r for r in (v["ranked"] + v["few"]) if r["handle"].lower() == handle.lower()), None) if v else None
    if not me:
        return None
    h = me["handle"]
    rank = next((i for i, r in enumerate(v["ranked"], 1) if r is me), None)
    a = v["accounts"].get(h) or {}
    name = a.get("name") if a.get("name") and a.get("name") != h else ""
    sc = v["scores"].get(h) or {}
    p = sc.get("prediktivno") or {}
    e, g = me["ekonomski"], me["integritet"]
    lo, hi = me["wilson95"]
    cat = CAT_HR.get(me.get("category") or "", "")
    sub = " · ".join(x for x in (esc(name), esc(cat), f"<a href='https://x.com/{esc(h)}' target=_blank "
                                                       f"rel='noopener nofollow'>x.com/{esc(h)} ↗</a>") if x)
    out = [f"<style>{kol.KL_CSS}{CSS}</style>", kol._back("/kol#makro", "Makro influenceri"),
           f"<div class=kl-dh><h1 class=ms-h1>@{esc(h)}</h1><div class=s>{sub}</div></div>"]
    base = p.get("bazne") or {}
    best_name = {"uvijek_bik": "uvijek bikovski", "nasumicno": "bacanje novčića", "trend_7d": "trend 7 dana"}
    best_k = max((k for k in base if base.get(k) is not None), key=lambda k: base[k], default=None)
    if me["few"]:
        out.append(str(R.verdict("Nedovoljno dokaza", f"Izmjereno {me['n_epizoda']} od {MIN_EP} epizoda potrebnih za "
                                 "presudu. Dotad nema ranga; brojke ispod su samo informativne.",
                                 label="Prediktivna kvaliteta", facts=f"{me['n_epizoda']} izmjerenih epizoda", kind="")))
    else:
        tone = PRED_TONE.get(me["presuda"], "")
        sent = (f"Pogodak {_pct(me['pogodak'])} (95 % interval {_ci(lo, hi)}) na {me['n_epizoda']} izmjerenih epizoda; "
                + (f"najbolja jednostavna osnova na istim datumima {_pct(base[best_k])} ({best_name[best_k]})."
                   if best_k else "osnove još nisu izmjerene."))
        out.append(str(R.verdict(PRED_WORD.get(me["presuda"], me["presuda"]), sent, label="Prediktivna kvaliteta",
                                 facts=f"#{rank} od {len(v['ranked'])} s dovoljno dokaza", kind=tone)))
    st = me["stav"]
    st_txt = R.raw(_stance_html(st).replace("<span class=", "<b class=").replace("</span>", "</b>"))
    post = (f"https://x.com/{h}/status/{st['id']}" if st and st.get("id") and str(st["id"]).isdigit() else None)
    out.append(str(R.section("Stav sada")))
    out.append(str(R.rows([R.row(st_txt, "svježe, bez odgode od 7 dana" if st else
                                 "nema izjave o BTC-u koja još vrijedi", "objava ↗" if post else None,
                                 href=post, value_tone="acc")])))
    e95 = e.get("razlika95") or [None, None]
    cards = [("Prediktivno", _pct(me["pogodak"]) if not me["few"] else "–",
              f"95 % interval <b>{_ci(lo, hi) or '–'}</b> · n {me['n_epizoda']}" + (
                  f" · osnova {_pct(base[best_k])}" if best_k else "")),
             ("Ekonomski", _pp(e.get("razlika")),
              f"povrat praćenja prema uvijek-bik po izjavi · 95 % {_pp(e95[0])} do {_pp(e95[1])} · n {e.get('n') or 0}"),
             ("Integritet", f"{g.get('naknadno_nedostupno') or 0} od {g.get('makro_izjava') or 0}",
              f"naknadno nedostupno (obrisano, zaključano ili suspendirano; bez optužbi) · promocija "
              f"{g.get('promocije') or 0}")]
    out.append(str(R.section("Tri ocjene")))
    out.append("<div class=mi-3>" + "".join(f"<div class=mi-c><div class=l>{lab}</div><div class=v>{esc(val)}</div>"
                                           f"<div class=w>{w}</div></div>" for lab, val, w in cards) + "</div>")
    hz = me.get("po_horizontu") or {}
    names = {"s_rokom_7d": "S rokom, 7 dana", "s_rokom_30d": "S rokom, 30 dana",
             "bez_roka_7d": "Bez roka, mjereno na 7 dana", "bez_roka_30d": "Bez roka, mjereno na 30 dana"}
    items = []
    for k, lab in names.items():
        x = hz.get(k) or {}
        w = x.get("wilson95") or [None, None]
        items.append(R.row(lab, f"95 % interval {_ci(w[0], w[1])}" if x.get("n") else "još nema izmjerenih",
                           _pct(x.get("pogodak")) if x.get("n") else "–", f"n {x.get('n') or 0}",
                           value_tone=None if x.get("n") else "mut"))
    out.append(str(R.section("Po horizontu")))
    out.append(str(R.rows(items)))
    eps, gone = episodes(h, fresh=True, now=now)
    out.append(str(R.section(f"Izjave · {len(eps)}")))
    out.append(str(R.hint("Najnovije prve, uključujući zadnjih 7 dana (javna stranica ih pokazuje tek nakon tjedan dana). "
                          "Ponovljena ista izjava je jedna epizoda.")))
    ep = []
    for _eid, asset, dr, hzb, ts, res, fid in eps:
        parts = sorted((x.split(":", 1) for x in (res or "").split(",") if ":" in x),
                       key=lambda p_: int(p_[0]) if p_[0].isdigit() else 999)
        tone = {"hit": "good", "miss": "bad"}
        res_html = "".join(f"<span class='{tone.get(rr, 'mut')}'>{esc(hh + ' d: ' if hh.isdigit() else '')}"
                           f"{esc(RES_HR.get(rr, rr))}</span>" for hh, rr in parts) or "<span class=mut>–</span>"
        link = ("<span>naknadno nedostupno</span>" if gone.get(str(fid)) in GONE else
                f"<a href='https://x.com/{esc(h)}/status/{esc(str(fid))}' target=_blank rel='noopener nofollow'>objava ↗</a>")
        ep.append(f"<div class=mi-ep><div><div class=t>{esc(ASSET_HR.get(asset, asset))}: {esc(DIR_HR.get(dr, dr))}</div>"
                  f"<div class=s>{_date(ts)} · horizont {esc(HZ.get(hzb, hzb or ''))}</div></div>"
                  f"<div class=r>{res_html}<span class=p>{link}</span></div></div>")
    out.append("".join(ep) if ep else str(R.hint("Još nema izmjerenih izjava.")))
    foot = (f"Ocjene se osvježavaju nakon svakog izračuna (svakih 30 min i noću). <a href='/kol-makro/biblioteka?racun="
            f"{quote(h)}&amp;vrsta=sve'>Sve objave @{esc(h)} u biblioteci →</a>")
    if on():
        foot += (f" <a href='/hr/makro-influencer/{quote(h)}'>Javna stranica (s odgodom 7 dana) →</a> · "
                 "<a href='/hr/makro-influenceri#kako-mjerimo'>Kako mjerimo →</a>")
    out.append(f"<p class=mi-foot>{foot}</p>")
    return f"@{h} · makro", kol._calm(f'<div class="ms-page kl">{"".join(out)}</div>')


def library(qs, now=None):
    """(title, body) of /kol-makro/biblioteka (cached until the next scoring, per query)."""
    from makroinf import appviews
    key = ("lib",) + tuple(sorted((k, str(v)) for k, v in (qs or {}).items()))
    return _cached(key, lambda: appviews.library_page(qs, now))


def list_page(now=None, qs=None):
    """(title, body) of /kol-makro: the tab's list as its own page (search, a direct link, no JS); ?str=N: the N-th
    TAB_PAGE accounts of the list."""
    from ui import kol, redak as R
    body = kol._calm(f'<div class="ms-page kl"><style>{kol.KL_CSS}</style>{kol._back("/kol#makro", "Influenceri")}'
                     f'{R.top("Makro influenceri", "Izjave o BTC-u i tržištu, izmjerene pravilima zadanima unaprijed")}'
                     f'{tab_html(now, (qs or {}).get("str"))}</div>')
    return "Makro influenceri", body
