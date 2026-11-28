"""Free public tool "Provjeri influencera" / "Check an influencer" (28.11.2026, poslovni plan: besplatni paket).

  GET  /hr/provjeri-influencera, /check-influencer      the form, handles to try (the indexed influencer profiles)
  POST the same paths                                     one check: what the account's clean calls returned after
                                                          cost (ui/kolstats via ui/javniapi.influencer_result), plain
                                                          words and the sample size
Without a login a visitor gets DAILY checks a UTC day: counted per visitor cookie (ms_vid, random, set on the first
check) and per hashed address (IP_DAILY, so clearing cookies does not reset it); both counters live in league.db
provjere_dan as salted hashes. A handle we do not track gets a friendly message and the sign-up link, and is counted
too (otherwise the tool would list who we track). Results only: no formula, weight or threshold in the text.
"""
import hashlib
import re
import secrets
import sqlite3
import statistics
import time

from ui.html import esc

DAILY = 3
IP_DAILY = 6
COOKIE = "ms_vid"
COST = 0.03
SUGGEST_N = 8
SCHEMA = """CREATE TABLE IF NOT EXISTS provjere_dan (day TEXT, vkey TEXT, n INTEGER DEFAULT 0, PRIMARY KEY (day, vkey));"""

T = {
    "hr": dict(
        title="Provjeri influencera: što su stvarno donijeli kripto pozivi",
        desc="Upiši X račun kripto influencera i besplatno vidi što su njegovi pozivi Solana tokena donijeli nakon "
             "troška, s brojem izmjerenih poziva. Tri provjere dnevno.",
        h1="Provjeri influencera",
        lead="Upiši X račun influencera kojeg pratimo i vidi što su njegovi pozivi Solana tokena stvarno donijeli, "
             "nakon troška od 3 %. Besplatno, tri provjere dnevno, bez prijave.",
        label="X račun", ph="npr. ansem", btn="Provjeri", try_="Probaj:", left="Danas ti je ostalo provjera: {n} od {d}.",
        limit="Danas si iskoristio sve tri besplatne provjere. Nove stižu sutra (ponoć po UTC-u). Za neograničene "
              "provjere i svježe podatke pogledaj paket Pro.",
        bad="Upiši X račun: slova, brojke i donja crta, do 30 znakova.",
        unknown="Račun @{h} još ne pratimo ili za njega nemamo izmjerenih poziva. Pratimo influencere koji redovito "
                "zovu Solana tokene; probaj jedan od ovih ili se prijavi na tjedni izvještaj.",
        signup="Prijavi se na tjedni izvještaj", pricing="Pogledaj paket Pro",
        res_h="@{h}: {n} izmjerenih poziva",
        since="Mjereno od {d}. Brojimo samo čiste pozive starije od 24 sata.",
        cards=("U plusu dan kasnije, nakon troška", "Tipičan ishod nakon 24 h, nakon troška", "Cijena viša sat nakon objave",
               "Završilo kao rug (pad 90 %+)"),
        few="Premalo izmjerenih poziva za presudu: brojke su samo orijentacija.",
        better="Sat nakon objave cijena je kod ovog računa češće viša nego kod tipičnog praćenog računa.",
        worse="Sat nakon objave cijena je kod ovog računa rjeđe viša nego kod tipičnog praćenog računa.",
        same="Sat nakon objave ovaj račun prolazi otprilike kao tipičan praćeni račun.",
        profile="Cijeli profil @{h} →", note="Prošli rezultati, ne predviđanje i ne financijski savjet.",
        how="Kako mjerimo"),
    "en": dict(
        title="Check an influencer: what their crypto calls really returned",
        desc="Enter a crypto influencer's X handle and see for free what their Solana token calls returned after cost, "
             "with the number of calls measured. Three checks a day.",
        h1="Check an influencer",
        lead="Enter the X handle of an influencer we track and see what their Solana token calls really returned, after "
             "a 3% cost. Free, three checks a day, no sign-up.",
        label="X handle", ph="e.g. ansem", btn="Check", try_="Try:", left="Checks left today: {n} of {d}.",
        limit="You have used all three free checks for today. New ones arrive tomorrow (midnight UTC). For unlimited "
              "checks and fresh data, see the Pro plan.",
        bad="Enter an X handle: letters, digits and underscores, up to 30 characters.",
        unknown="We do not track @{h} yet, or have no measured calls for it. We track influencers who regularly call "
                "Solana tokens; try one of these or sign up for the weekly report.",
        signup="Sign up for the weekly report", pricing="See the Pro plan",
        res_h="@{h}: {n} measured calls",
        since="Measured since {d}. We count clean calls older than 24 hours only.",
        cards=("Up a day later, after cost", "Typical result after 24 h, after cost", "Price higher an hour after the post",
               "Ended as a rug (fell 90%+)"),
        few="Too few measured calls for a verdict: treat the numbers as a rough guide.",
        better="An hour after the post, the price was higher more often than for a typical tracked account.",
        worse="An hour after the post, the price was higher less often than for a typical tracked account.",
        same="An hour after the post, this account does about as well as a typical tracked account.",
        profile="Full profile of @{h} →", note="Past results, not a prediction and not financial advice.",
        how="How we measure"),
}

CSS = """<style>
.pv-form{display:flex;gap:10px;max-width:560px;margin:0 0 12px}.pv-form label{flex:1;position:relative}
.pv-form input{width:100%;background:var(--soft);border:1px solid var(--line);border-radius:14px;padding:14px 16px 14px 34px;
font:inherit;font-size:17px}.pv-form label:before{content:"@";position:absolute;left:15px;top:13px;color:var(--mut);font-size:17px}
.pv-form .btn{flex:none}.pv-sr{position:absolute;left:-9999px}
.pv-chips{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin:0 0 8px;color:var(--mut);font-size:14px}
.pv-chips button{border:1px solid var(--line);background:#fff;border-radius:999px;padding:6px 12px;font:inherit;font-size:14px;
cursor:pointer;color:var(--fg)}.pv-left{color:var(--mut);font-size:14px;margin:0 0 26px}
.pv-res{border:1px solid var(--line);border-radius:22px;padding:22px;background:#fff;max-width:820px;margin:0 0 26px}
.pv-res h2{margin:0 0 4px;font-size:24px}.pv-cards{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin:16px 0}
.pv-cards div{background:var(--soft);border-radius:14px;padding:14px}.pv-cards b{display:block;font-size:26px;font-weight:800}
.pv-cards span{color:var(--mut);font-size:13.5px;line-height:1.35;display:block}
.pv-msg{border-radius:16px;padding:16px;margin:0 0 20px;max-width:820px;background:#fff7ed;border:1px solid #fed7aa}
@media(max-width:700px){.pv-cards{grid-template-columns:1fr 1fr}.pv-form{flex-direction:column}}
</style>"""


def path(lang):
    return "/check-influencer" if lang == "en" else "/hr/provjeri-influencera"


def _con():
    from ui import cijene
    con = cijene.connect()
    con.executescript(SCHEMA)
    return con


def _day(now):
    return time.strftime("%Y-%m-%d", time.gmtime(now))


def keys(con, cookie_id, ip):
    """(cookie key or None, address key): salted hashes, never the cookie or the address itself."""
    from ui import cijene
    salt = cijene._salt(con)
    ck = ("c:" + hashlib.sha256(f"{salt}|vid|{cookie_id}".encode()).hexdigest()[:24]) if cookie_id else None
    return ck, "i:" + cijene.ip_hash(con, ip)


def used(cookie_id, ip, now=None):
    """Checks this visitor used today (the larger of the cookie count and the address count scaled to DAILY)."""
    now = now or time.time()
    try:
        con = _con()
        try:
            return _used(con, *keys(con, cookie_id, ip), _day(now))
        finally:
            con.close()
    except sqlite3.Error:
        return 0


def _used(con, ck, ik, day):
    get = (lambda k: (con.execute("SELECT n FROM provjere_dan WHERE day=? AND vkey=?", (day, k)).fetchone() or (0,))[0]
           if k else 0)
    c, i = get(ck), get(ik)
    return DAILY if i >= IP_DAILY else min(DAILY, c)


def take(cookie_id, ip, now=None):
    """One check: True and counted when the visitor has one left today, else False. Fails closed on a database error."""
    now = now or time.time()
    day = _day(now)
    try:
        con = _con()
        try:
            ck, ik = keys(con, cookie_id, ip)
            if _used(con, ck, ik, day) >= DAILY:
                return False
            for k in (ck, ik):
                if k:
                    con.execute("INSERT INTO provjere_dan (day, vkey, n) VALUES (?,?,1) ON CONFLICT(day, vkey) "
                                "DO UPDATE SET n = n + 1", (day, k))
            con.execute("DELETE FROM provjere_dan WHERE day < ?", (_day(now - 3 * 86400),))
            con.commit()
            return True
        finally:
            con.close()
    except sqlite3.Error as e:
        print(f"provjeri: brojač nedostupan: {type(e).__name__}"[:200], flush=True)
        return False


def new_cookie_id():
    return secrets.token_hex(16)


def suggestions(lang):
    """Handles of the indexed influencer profiles (ui/seoindex core, by clean measured calls)."""
    try:
        from ui import seoindex
        return [p.rsplit("/", 1)[1] for p in seoindex.section_paths("influencer", lang)][:SUGGEST_N]
    except Exception:  # noqa: BLE001
        return []


def result(handle):
    """(code, data): javniapi.influencer_result plus the after-cost numbers of the same clean calls."""
    from ui import javniapi
    code, d = javniapi.influencer_result(handle)
    if code != 200:
        return code, d
    from ui import kolstats as KS
    from ui import public
    con = public._con()
    if con is None:
        return 404, {"error": "account not known to us"}
    try:
        calls = KS.clean_calls(con, d["handle"])
    finally:
        con.close()
    net = [(1 + c["r24h"]) * (1 - COST) - 1 for c in calls if c["r24h"] is not None]
    d["plus_after_cost_share"] = (sum(1 for x in net if x > 0) / len(net)) if net else None
    d["median_24h_after_cost"] = statistics.median(net) if net else None
    if not d["measured_calls"]:
        return 404, {"error": "account not known to us"}
    return 200, d


def _pct(x, lang, signed=False):
    if x is None:
        return "–"
    s = f"{x * 100:+.0f}" if signed else f"{x * 100:.0f}"
    return s + ("%" if lang == "en" else " %")


def _day_txt(ts, lang):
    if not ts:
        return "–"
    g = time.gmtime(ts)
    from ui import naslovnica as N
    return N.day_text(f"{g.tm_year}-{g.tm_mon:02d}-{g.tm_mday:02d}", lang)


def result_html(lang, d):
    t = T[lang]
    h = esc(d["handle"])
    n = d["measured_calls"]
    vals = (_pct(d.get("plus_after_cost_share"), lang), _pct(d.get("median_24h_after_cost"), lang, True),
            _pct(d.get("price_up_after_1h_share"), lang), _pct(d.get("fell_90pct_share"), lang))
    cards = "".join(f"<div><b>{v}</b><span>{esc(lab)}</span></div>" for v, lab in zip(vals, t["cards"]))
    if not d.get("enough_data"):
        verdict = t["few"]
    else:
        verdict = {"better": t["better"], "worse": t["worse"], "same": t["same"]}.get(d.get("vs_median_account"), "")
    prof = (f"/influencer/{h}" if lang == "en" else f"/hr/influencer/{h}")
    from ui import public
    link = f"<p><a class=lk href={prof}>{t['profile'].format(h=h)}</a></p>" if n >= public.MIN_MEASURED else ""
    return (f"<div class=pv-res id=rezultat><h2>{t['res_h'].format(h=h, n=n)}</h2>"
            f"<p class=small style='margin:0'>{t['since'].format(d=_day_txt(d.get('measured_since'), lang))}</p>"
            f"<div class=pv-cards>{cards}</div><p style='margin:0 0 6px'>{esc(verdict)}</p>{link}"
            f"<p class=small style='margin:6px 0 0'>{t['note']}</p></div>")


def page(lang, left=DAILY, handle="", outcome=None):
    """The tool page. outcome: None (no check yet), ("limit",), ("bad",), ("unknown", h), ("ok", data)."""
    from ui import naslovnica as N
    from ui import public as P
    lang = "en" if lang == "en" else "hr"
    t = T[lang]
    sug = suggestions(lang)
    act = path(lang)
    chips = ("<div class=pv-chips>" + esc(t["try_"]) + "".join(
        f"<button type=submit name=h value=\"{esc(s)}\">@{esc(s)}</button>" for s in sug) + "</div>") if sug else ""
    msg = ""
    if outcome:
        kind = outcome[0]
        pricing, home = N.href("pricing", lang), N.href("home", lang)
        if kind == "limit":
            msg = (f"<div class=pv-msg role=alert>{esc(t['limit'])}<p style='margin:10px 0 0'><a class='btn p sm' "
                   f"href={pricing}>{t['pricing']}</a></p></div>")
        elif kind == "bad":
            msg = f"<div class=pv-msg role=alert>{esc(t['bad'])}</div>"
        elif kind == "unknown":
            msg = (f"<div class=pv-msg role=status>{esc(t['unknown'].format(h=outcome[1]))}<p style='margin:10px 0 0'>"
                   f"<a class='btn p sm' href={home}#pristup>{t['signup']}</a></p></div>")
        elif kind == "ok":
            msg = result_html(lang, outcome[1])
    form = (f"<form method=post action={act} id=provjera><div class=pv-form><label><span class=pv-sr>{t['label']}</span>"
            f"<input name=h required maxlength=31 pattern=\"@?[A-Za-z0-9_]{{1,30}}\" autocomplete=off autocapitalize=off "
            f"spellcheck=false placeholder=\"{esc(t['ph'])}\" value=\"{esc(handle)}\" aria-label=\"{esc(t['label'])}\">"
            f"</label><button class='btn p' type=submit>{t['btn']}</button></div>{chips}</form>")
    body = (f"{CSS}<section class=ph1><h1>{t['h1']}</h1><p class=lead>{t['lead']}</p></section>{msg}{form}"
            f"<p class=pv-left>{t['left'].format(n=max(0, left), d=DAILY)} · <a href={N.href('method', lang)}#"
            f"{'influencers' if lang == 'en' else 'influenceri'}>{t['how']}</a></p>")
    en, hr = N.PATHS["check"]
    return P._shell(lang, t["title"], t["desc"], en, hr, body)


HANDLE = re.compile(r"@?([A-Za-z0-9_]{1,30})")


def check(lang, form, cookie_id, ip, now=None):
    """POST: (html, handle) after one check (counted only for a well-formed handle)."""
    raw = (form.get("h") or "").strip()
    m = HANDLE.fullmatch(raw)
    if not m:
        return page(lang, DAILY - used(cookie_id, ip, now), raw[:31], ("bad",))
    h = m.group(1)
    if not take(cookie_id, ip, now):
        return page(lang, 0, h, ("limit",))
    left = DAILY - used(cookie_id, ip, now)
    try:
        code, d = result(h)
    except Exception as e:  # noqa: BLE001 - the visitor gets the friendly message, the log the reason
        print(f"provjeri: {type(e).__name__}: {e}"[:200], flush=True)
        code, d = 404, {}
    if code != 200:
        return page(lang, left, h, ("unknown", h))
    return page(lang, left, d["handle"], ("ok", d))
