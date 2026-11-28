"""Prices, early-access sign-ups and B2B enquiries (28.11.2026, vlasnik: poslovni plan prihvaćen).

  /hr/cijene, /pricing        the packages: Besplatno 0 €, Pro 29 €/mj ili 290 €/god, Pro+ 79 €/mj, the founding offer
                              (first 50 subscribers -40 % for life) and the B2B section ("javite se")
  POST /cekanje               early access / weekly report: e-mail, optional name, plan, GDPR consent (league.db
                              rani_pristup). There is no payment provider yet: nothing is charged, the page says
                              billing opens soon.
  POST /b2b-upit              company, e-mail, what they need, consent (league.db b2b_upiti) + one line to the owner on
                              Telegram when TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID are set (same path as ops/diskguard)
  /prijave, /prijave.csv      the owner's list of both, CSV export (run_ui: the OWNER only)
Spam: a honeypot field (a hit pretends to succeed and stores nothing), at most PER_IP_HOUR forms per hour per visitor
(hashed address, never the address itself), a cap on unhandled rows. Nobody is ever e-mailed automatically.
"""
import csv
import hashlib
import io
import os
import re
import secrets
import sqlite3
import threading
import time
import urllib.parse
import urllib.request

from ui.html import esc

PER_IP_HOUR = 5
MAX_ROWS = 5000
PLANS = {"tjedni": ("Tjedni izvještaj", "Weekly report"), "pro": ("Pro mjesečno", "Pro monthly"),
         "pro_god": ("Pro godišnje", "Pro yearly"), "proplus": ("Pro+", "Pro+")}
WAITLIST_PLANS = ("pro", "pro_god", "proplus")
NEEDS = {"api_starter": ("API Starter", "API Starter"), "api_business": ("API Business", "API Business"),
         "integracija": ("Integracija", "Integration"), "licenca": ("Licenca podataka", "Data licence"),
         "kol": ("KOL izvještaji za agenciju", "KOL reports for an agency"), "drugo": ("Nešto drugo", "Something else")}
EMAIL = re.compile(r"[^@\s<>\"']{1,64}@[^@\s<>\"']{1,190}\.[A-Za-z]{2,24}")
SCHEMA = """
CREATE TABLE IF NOT EXISTS rani_pristup (id INTEGER PRIMARY KEY AUTOINCREMENT, ts INTEGER, plan TEXT, name TEXT,
    email TEXT, lang TEXT, consent_ts INTEGER, src TEXT, ip_hash TEXT, status TEXT DEFAULT 'novi', UNIQUE (email, plan));
CREATE TABLE IF NOT EXISTS b2b_upiti (id INTEGER PRIMARY KEY AUTOINCREMENT, ts INTEGER, company TEXT, email TEXT,
    need TEXT, interest TEXT, lang TEXT, consent_ts INTEGER, src TEXT, ip_hash TEXT, status TEXT DEFAULT 'novi');
CREATE INDEX IF NOT EXISTS rani_pristup_ip ON rani_pristup (ip_hash, ts);
CREATE INDEX IF NOT EXISTS b2b_upiti_ip ON b2b_upiti (ip_hash, ts);
CREATE TABLE IF NOT EXISTS prijave_meta (k TEXT PRIMARY KEY, v TEXT);
"""
_IPS = {}            # ip hash -> [ts] in this process (the database count also holds across restarts)
_LOCK = threading.Lock()
NOTIFY = {"fn": None}   # tests: a function(text) instead of Telegram

ERR = {
    "email": ("Upiši ispravan e-mail.", "Please enter a valid e-mail."),
    "consent": ("Za prijavu je potreban pristanak na čuvanje e-maila.", "Please tick the consent box to sign up."),
    "company": ("Upiši ime tvrtke.", "Please enter the company name."),
    "need": ("Napiši ukratko što trebate.", "Please write briefly what you need."),
    "plan": ("Odaberi paket.", "Please choose a plan."),
    "rate": ("Previše prijava s ove adrese. Pokušaj ponovno za sat vremena.",
             "Too many sign-ups from this address. Try again in an hour."),
    "full": ("Popis je trenutno pun. Pokušaj ponovno za par dana.", "The list is full right now. Try again in a few days."),
    "db": ("Prijavu trenutno nije moguće spremiti. Pokušaj ponovno za par minuta.",
           "We couldn't save this right now. Try again in a few minutes."),
}


def err_text(code, lang):
    return ERR.get(code, ERR["db"])[lang == "en"]


# ---------- store ------------------------------------------------------------------------------------------------------

def connect():
    from league import store
    con = store.connect()
    con.executescript(SCHEMA)
    return con


def _salt(con):
    r = con.execute("SELECT v FROM prijave_meta WHERE k='salt'").fetchone()
    if r:
        return r[0]
    s = secrets.token_hex(16)
    con.execute("INSERT OR IGNORE INTO prijave_meta (k, v) VALUES ('salt', ?)", (s,))
    con.commit()
    return con.execute("SELECT v FROM prijave_meta WHERE k='salt'").fetchone()[0]


def ip_hash(con, ip):
    """The visitor's address as a salted hash (never stored in the clear)."""
    return hashlib.sha256(f"{_salt(con)}|{ip or '-'}".encode()).hexdigest()[:24]


def _limited(con, h, now):
    with _LOCK:
        hits = [t for t in _IPS.get(h, []) if now - t < 3600]
        _IPS[h] = hits
        mem = len(hits)
    db = 0
    for tbl in ("rani_pristup", "b2b_upiti"):
        db += con.execute(f"SELECT COUNT(*) FROM {tbl} WHERE ip_hash=? AND ts>?", (h, int(now - 3600))).fetchone()[0]
    return max(mem, db) >= PER_IP_HOUR


def _hit(h, now):
    with _LOCK:
        _IPS.setdefault(h, []).append(now)


def _clean(s, n):
    return re.sub(r"[\x00-\x1f<>]", " ", re.sub(r"\s+", " ", (s or "").strip()))[:n].strip()


def submit(form, ip="", now=None):
    """Early access / weekly report. -> (True, None) when stored (or a honeypot hit / a repeat), else (False, code)."""
    now = now or time.time()
    if (form.get("web") or "").strip():
        return True, None
    plan = form.get("plan") or ""
    if plan not in PLANS:
        return False, "plan"
    email = (form.get("email") or "").strip()[:120]
    if not EMAIL.fullmatch(email):
        return False, "email"
    if form.get("consent") != "1":
        return False, "consent"
    lang = "en" if form.get("lang") == "en" else "hr"
    try:
        con = connect()
        try:
            h = ip_hash(con, ip)
            if _limited(con, h, now):
                return False, "rate"
            if (con.execute("SELECT COUNT(*) FROM rani_pristup WHERE status='novi'").fetchone()[0] or 0) >= MAX_ROWS:
                return False, "full"
            cur = con.execute("INSERT OR IGNORE INTO rani_pristup (ts, plan, name, email, lang, consent_ts, src, ip_hash) "
                              "VALUES (?,?,?,?,?,?,?,?)", (int(now), plan, _clean(form.get("name"), 60), email.lower(),
                                                          lang, int(now), _clean(form.get("src"), 40), h))
            con.commit()
            _hit(h, now)
        finally:
            con.close()
    except sqlite3.Error as e:
        print(f"cijene: prijava nije spremljena: {type(e).__name__}: {e}"[:200], flush=True)
        return False, "db"
    if cur.rowcount:
        print(f"cijene: nova prijava ({plan})", flush=True)
    return True, None


def submit_b2b(form, ip="", now=None):
    """B2B enquiry. -> (True, None) or (False, code); a stored one sends the owner one short line."""
    now = now or time.time()
    if (form.get("web") or "").strip():
        return True, None
    company = _clean(form.get("company"), 80)
    email = (form.get("email") or "").strip()[:120]
    need = _clean(form.get("need"), 1500)
    interest = form.get("interest") if form.get("interest") in NEEDS else "drugo"
    if len(company) < 2:
        return False, "company"
    if not EMAIL.fullmatch(email):
        return False, "email"
    if len(need) < 5:
        return False, "need"
    if form.get("consent") != "1":
        return False, "consent"
    lang = "en" if form.get("lang") == "en" else "hr"
    try:
        con = connect()
        try:
            h = ip_hash(con, ip)
            if _limited(con, h, now):
                return False, "rate"
            if (con.execute("SELECT COUNT(*) FROM b2b_upiti WHERE status='novi'").fetchone()[0] or 0) >= MAX_ROWS:
                return False, "full"
            con.execute("INSERT INTO b2b_upiti (ts, company, email, need, interest, lang, consent_ts, src, ip_hash) "
                        "VALUES (?,?,?,?,?,?,?,?,?)", (int(now), company, email.lower(), need, interest, lang, int(now),
                                                       _clean(form.get("src"), 40), h))
            con.commit()
            _hit(h, now)
        finally:
            con.close()
    except sqlite3.Error as e:
        print(f"cijene: B2B upit nije spremljen: {type(e).__name__}: {e}"[:200], flush=True)
        return False, "db"
    notify(f"novi B2B upit: {company} ({NEEDS[interest][0]}). Pogledaj /prijave.")
    return True, None


def notify(text):
    """The owner: the server log always, Telegram when TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID are set (a thread)."""
    print(f"cijene: {text}", flush=True)
    if NOTIFY["fn"]:
        return NOTIFY["fn"](text)
    tok, chat = os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    if not (tok and chat):
        return False

    def send():
        try:
            data = urllib.parse.urlencode({"chat_id": chat, "text": f"MemeSonar · {text}",
                                           "disable_web_page_preview": "true"}).encode()
            urllib.request.urlopen(f"https://api.telegram.org/bot{tok}/sendMessage", data, timeout=15).read()
        except Exception as e:  # noqa: BLE001 - the log line is there anyway
            print(f"cijene: Telegram nije poslan ({type(e).__name__})", flush=True)
    threading.Thread(target=send, daemon=True).start()
    return True


def rows(table):
    con = connect()
    try:
        con.row_factory = sqlite3.Row
        return [dict(r) for r in con.execute(f"SELECT * FROM {table} ORDER BY id DESC")]
    finally:
        con.close()


# ---------- owner page --------------------------------------------------------------------------------------------------

def owner_page(qs=None):
    """(title, body) for /prijave: both lists, newest first, with CSV links. The caller checks the owner."""
    wl, b2b = rows("rani_pristup"), rows("b2b_upiti")
    when = (lambda ts: time.strftime("%d.%m.%Y. %H:%M", time.localtime(ts)) if ts else "–")
    cnt = {}
    for r in wl:
        cnt[r["plan"]] = cnt.get(r["plan"], 0) + 1
    summary = " · ".join(f"{PLANS.get(p, (p,))[0]}: <b>{n}</b>" for p, n in sorted(cnt.items())) or "još nitko"
    trs = "".join(f"<tr><td>{when(r['ts'])}</td><td>{esc(PLANS.get(r['plan'], (r['plan'],))[0])}</td>"
                  f"<td>{esc(r['email'])}</td><td>{esc(r['name'] or '')}</td><td>{esc(r['lang'] or '')}</td>"
                  f"<td>{esc(r['src'] or '')}</td></tr>" for r in wl[:500])
    brs = "".join(f"<tr><td>{when(r['ts'])}</td><td>{esc(r['company'])}</td><td>{esc(r['email'])}</td>"
                  f"<td>{esc(NEEDS.get(r['interest'], (r['interest'],))[0])}</td><td>{esc(r['need'])}</td></tr>"
                  for r in b2b[:500])
    body = (
        "<h1>Prijave i B2B upiti</h1>"
        "<div class=card><p>Rani pristup i tjedni izvještaj s javnih stranica (/hr/cijene, naslovnica). Naplata još ne "
        "postoji: nitko nije ništa platio, a nikome se ništa ne šalje automatski.</p>"
        f"<p>{summary} · B2B upita: <b>{len(b2b)}</b></p>"
        "<p><a href='/prijave.csv?t=cekanje'>Izvoz prijava (CSV)</a> · <a href='/prijave.csv?t=b2b'>Izvoz B2B upita "
        "(CSV)</a></p></div>"
        "<h2>Rani pristup i tjedni izvještaj</h2><div class=card><table><tr><th>Vrijeme</th><th>Paket</th><th>E-mail</th>"
        f"<th>Ime</th><th>Jezik</th><th>Izvor</th></tr>{trs or '<tr><td colspan=6>Još nema prijava.</td></tr>'}</table></div>"
        "<h2>B2B upiti</h2><div class=card><table><tr><th>Vrijeme</th><th>Tvrtka</th><th>E-mail</th><th>Zanima ih</th>"
        f"<th>Što trebaju</th></tr>{brs or '<tr><td colspan=5>Još nema upita.</td></tr>'}</table></div>")
    return "Prijave", body


def csv_export(kind):
    """(file name, csv text) of one list; kind 'cekanje' or 'b2b'."""
    table, cols = (("b2b_upiti", ("id", "ts", "company", "email", "interest", "need", "lang", "consent_ts", "src", "status"))
                   if kind == "b2b" else
                   ("rani_pristup", ("id", "ts", "plan", "email", "name", "lang", "consent_ts", "src", "status")))
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(cols)
    for r in rows(table):
        w.writerow([_csv_cell(r.get(c)) for c in cols])
    return f"memesonar-{'b2b' if kind == 'b2b' else 'prijave'}-{time.strftime('%Y%m%d')}.csv", buf.getvalue()


def _csv_cell(v):
    s = "" if v is None else str(v)
    return "'" + s if s[:1] in ("=", "+", "-", "@") else s   # no formula runs when the owner opens it in a sheet


# ---------- the public page -------------------------------------------------------------------------------------------

T = {
    "hr": dict(
        title="Cijene MemeSonara: besplatno, Pro i Pro+ za Solana podatke",
        desc="Besplatno 0 €, Pro 29 € mjesečno, Pro+ 79 € mjesečno. Izmjereni podaci o Solana memecoinima s točnošću "
             "uz svaku ocjenu. Prvih 50 pretplatnika −40 % zauvijek.",
        h1="Cijene", lead="Plaćaš izmjerene podatke, ne obećanje zarade. Uz svaku ocjenu piše koliko je točno pogađala "
                          "na danima koje nije vidjela.",
        founding="<b>Osnivačka ponuda:</b> prvih 50 pretplatnika dobiva −40 % zauvijek (Pro 17,40 €/mj ili 174 €/god, "
                 "Pro+ 47,40 €/mj).",
        soon="Naplata se uskoro otvara. Upis za rani pristup ništa ne naplaćuje: javimo ti se e-mailom kad se otvori, "
             "a osnivačka cijena vrijedi za prvih 50 koji se tada pretplate.",
        plans=[("free", "Besplatno", "0 €", "zauvijek",
                ["Podaci s 24 h zakašnjenja", "„Provjeri influencera”: 3 provjere dnevno", "Osnovni rizik tokena",
                 "Ljestvica influencera i stranice tokena"], "Počni besplatno"),
               ("pro", "Pro", "29 €", "mjesečno ili 290 € godišnje",
                ["Svježi podaci, bez zakašnjenja", "Profili osoba: skupine povezanih novčanika",
                 "Kopirljivost novčanika i influencera", "Točnost uz svaku ocjenu",
                 "Alarmi na Telegramu za 20 novčanika ili influencera"], "Rani pristup"),
               ("proplus", "Pro+", "79 €", "mjesečno",
                ["Sve iz paketa Pro", "API: 5.000 zahtjeva dnevno", "Izvoz u CSV",
                 "Moć poziva skupina influencera"], "Rani pristup")],
        wl_h="Rani pristup", wl_p="Ostavi e-mail i odaberi paket. Ime nije obavezno.",
        f_name="Ime (nije obavezno)", f_plan="Paket",
        f_ok="<b>Upisan si za rani pristup.</b> Javimo ti se e-mailom kad se naplata otvori.",
        f_consent="Pristajem da MemeSonar čuva moj e-mail i javi mi se kad se naplata otvori. Podatke ne dijelimo ni s "
                  "kim i brišemo ih na zahtjev.",
        f_btn="Upiši me",
        b2b_h="Za tvrtke", b2b_p="Podaci za vaš proizvod, istraživanje ili klijente. Javite se i dogovorimo.",
        b2b=[("API Starter", "199 $/mj", "Rizik tokena, novčanici, influenceri i signali s 24 h zakašnjenja ili svježe."),
             ("API Business", "499 $/mj", "Veći broj zahtjeva, svježi podaci i podrška za integraciju."),
             ("Integracije", "javite se", "Naši podaci u vašem botu, terminalu ili aplikaciji."),
             ("Licenca podataka", "javite se", "Povijesni izmjereni podaci za istraživanje ili modele."),
             ("KOL izvještaji za agencije", "javite se", "Što su pozivi pojedinih influencera stvarno donijeli, nakon "
                                                         "troška, prije nego što ih angažirate.")],
        b_company="Tvrtka", b_email="Poslovni e-mail", b_interest="Što vas zanima", b_need="Što trebate",
        b_ph="Npr. API za rizik tokena u našoj aplikaciji, oko 50.000 zahtjeva mjesečno.",
        b_consent="Pristajem da MemeSonar čuva ove podatke i javi se na ovaj e-mail u vezi s upitom.",
        b_btn="Pošalji upit", b_ok="<b>Upit je poslan.</b> Javimo se na tvoj e-mail, obično unutar dva radna dana.",
        faq=[("Što dobivam besplatno?", "Javne stranice s podacima starijima od 24 sata, tri provjere influencera "
              "dnevno i osnovni rizik tokena. Bez kartice i bez registracije."),
             ("Kad se otvara naplata?", "Uskoro. Do tada se možeš upisati za rani pristup; nitko ti ništa ne naplaćuje "
              "dok se sam ne pretplatiš."),
             ("Je li ovo trading bot ili financijski savjet?", "Ni jedno ni drugo. Prodajemo izmjerene podatke o "
              "prošlim pozivima, novčanicima i tokenima, s veličinom uzorka i točnošću. Odluka je uvijek tvoja.")],
        faq_h="Pitanja o cijenama", free_href="/hr/provjeri-influencera"),
    "en": dict(
        title="MemeSonar pricing: Free, Pro and Pro+ for Solana data",
        desc="Free €0, Pro €29 a month, Pro+ €79 a month. Measured data on Solana memecoins with the accuracy next to "
             "every score. First 50 subscribers get 40% off for life.",
        h1="Pricing", lead="You pay for measured data, not a promise of profit. Every score shows how often it was "
                           "right on days it had not seen.",
        founding="<b>Founding offer:</b> the first 50 subscribers get 40% off for life (Pro €17.40/mo or €174/yr, Pro+ "
                 "€47.40/mo).",
        soon="Billing opens soon. Signing up for early access charges nothing: we e-mail you when it opens, and the "
             "founding price holds for the first 50 who subscribe then.",
        plans=[("free", "Free", "€0", "forever",
                ["Data with a 24 h delay", "“Check an influencer”: 3 checks a day", "Basic token risk",
                 "Influencer ranking and token pages"], "Start for free"),
               ("pro", "Pro", "€29", "a month or €290 a year",
                ["Fresh data, no delay", "People profiles: groups of linked wallets", "Copyability of wallets and influencers",
                 "Accuracy next to every score", "Telegram alerts for 20 wallets or influencers"], "Early access"),
               ("proplus", "Pro+", "€79", "a month",
                ["Everything in Pro", "API: 5,000 requests a day", "CSV export", "Call power of influencer groups"],
                "Early access")],
        wl_h="Early access", wl_p="Leave your e-mail and choose a plan. Your name is optional.",
        f_name="Name (optional)", f_plan="Plan",
        f_ok="<b>You are on the early-access list.</b> We will e-mail you when billing opens.",
        f_consent="Yes, MemeSonar may keep my e-mail and contact me when billing opens. We never share it and "
                  "delete it on request.",
        f_btn="Sign me up",
        b2b_h="For companies", b2b_p="Data for your product, research or clients. Get in touch and we will agree the "
                                     "details.",
        b2b=[("API Starter", "$199/mo", "Token risk, wallets, influencers and signals, delayed by 24 h or fresh."),
             ("API Business", "$499/mo", "More requests, fresh data and help with the integration."),
             ("Integrations", "get in touch", "Our data inside your bot, terminal or app."),
             ("Data licence", "get in touch", "Historical measured data for research or models."),
             ("KOL reports for agencies", "get in touch", "What an influencer's calls really returned, after cost, "
                                                         "before you hire them.")],
        b_company="Company", b_email="Work e-mail", b_interest="What interests you", b_need="What you need",
        b_ph="E.g. a token risk API inside our app, about 50,000 requests a month.",
        b_consent="Yes, MemeSonar may keep these details and reply to this e-mail about the enquiry.",
        b_btn="Send the enquiry", b_ok="<b>Enquiry sent.</b> We will reply to your e-mail, usually within two working days.",
        faq=[("What do you get for free?", "The public pages with data older than 24 hours, three influencer checks a day "
              "and basic token risk. No card and no sign-up."),
             ("When does billing open?", "Soon. Until then you can sign up for early access; nothing is charged until "
              "you subscribe yourself."),
             ("Is this a trading bot or financial advice?", "Neither. We sell measured data on past calls, wallets and "
              "tokens, with the sample size and accuracy. The decision is always yours.")],
        faq_h="Pricing questions", free_href="/check-influencer"),
}

CSS = """<style>
.cj-found{background:#eef2ff;border:1px solid #c7d2fe;border-radius:16px;padding:14px 18px;margin:0 0 22px;font-size:15.5px}
.cj-plans{display:grid;grid-template-columns:repeat(3,1fr);gap:16px;margin:0 0 14px}
.cj-plan{background:#fff;border:1px solid var(--line);border-radius:22px;padding:24px;display:flex;flex-direction:column}
.cj-plan.hi{border-color:var(--acc);box-shadow:0 24px 60px -36px rgba(79,70,229,.65)}
.cj-plan h2{font-size:22px;margin:0 0 6px}.cj-plan .pr{font-size:38px;font-weight:800;letter-spacing:-.03em;line-height:1.1}
.cj-plan .per{color:var(--mut);font-size:14px;margin:2px 0 16px}
.cj-plan ul{list-style:none;padding:0;margin:0 0 20px;display:grid;gap:9px;flex:1}
.cj-plan li{position:relative;padding-left:26px;font-size:15px}.cj-plan li:before{content:"✓";position:absolute;left:0;
color:var(--good);font-weight:800}.cj-plan .btn{width:100%}
.cj-soon{color:var(--mut);font-size:14.5px;margin:0 0 40px}
.cj-b2b{display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:12px;margin:0 0 22px}
.cj-b2b div{border:1px solid var(--line);border-radius:18px;padding:16px;background:#fff}
.cj-b2b b{display:block}.cj-b2b em{display:block;font-style:normal;font-weight:750;color:var(--acc);margin:2px 0 6px}
.cj-b2b span{color:var(--mut);font-size:14px}
form.rq textarea{width:100%;margin-top:6px;background:var(--soft);color:var(--fg);border:1px solid var(--line);
border-radius:14px;padding:14px 16px;font:inherit;font-size:16px;min-height:110px}
.cj-wrap{max-width:560px}
@media(max-width:860px){.cj-plans{grid-template-columns:1fr}}
</style>"""


def page(lang, qs=None, form=None, err="", which=None):
    """(html) of the prices page. which: 'cekanje' or 'b2b' (the form an error belongs to)."""
    from ui import naslovnica as N
    from ui import public as P
    qs = qs or {}
    lang = "en" if lang == "en" else "hr"
    t = T[lang]
    form = form or {}
    want = form.get("plan") or qs.get("plan") or "pro"
    want = want if want in WAITLIST_PLANS else "pro"
    cards = []
    for key, name, price, per, feats, btn in t["plans"]:
        go = t["free_href"] if key == "free" else f"?plan={key}#cekanje"
        cards.append(f"<div class='cj-plan{' hi' if key == 'pro' else ''}'><h2>{esc(name)}</h2><div class=pr>{esc(price)}</div>"
                     f"<div class=per>{esc(per)}</div><ul>{''.join(f'<li>{esc(x)}</li>' for x in feats)}</ul>"
                     f"<a class='btn {'g' if key == 'free' else 'p'}' href=\"{go}\">{esc(btn)}</a></div>")
    opts = "".join(f"<option value={p}{' selected' if p == want else ''}>{esc(PLANS[p][lang == 'en'])}"
                   f"{'' if p != 'pro_god' else (' (290 €)' if lang == 'hr' else ' (€290)')}</option>"
                   for p in WAITLIST_PLANS)
    wl_ok = qs.get("prijava") == "ok" and not err
    wl_err = err if which == "cekanje" else ""
    plan_field = (f"<label>{t['f_name']}<input name=name maxlength=60 autocomplete=name value=\"{esc(form.get('name', ''))}\">"
                  f"</label><label>{t['f_plan']}<select name=plan>{opts}"
                  "</select></label>")
    wl_form = N.signup_form(lang, wl_ok, wl_err, form if which == "cekanje" else None, plan=None, fid="cekanje-forma",
                            extra=plan_field, button=t["f_btn"], src=qs.get("src", ""))
    wl_form = wl_form.replace(N.T[lang]["f_consent"], t["f_consent"]).replace(N.T[lang]["f_ok"], t["f_ok"])
    b_ok = qs.get("upit") == "ok" and not err
    b_err = err if which == "b2b" else ""
    bf = form if which == "b2b" else {}
    b_msg = f"<div class=ok role=status>{t['b_ok']}</div>" if b_ok else (f"<div class=err role=alert>{esc(b_err)}</div>" if b_err else "")
    interest = bf.get("interest") or "api_starter"
    iopts = "".join(f"<option value={k}{' selected' if k == interest else ''}>{esc(v[lang == 'en'])}</option>"
                    for k, v in NEEDS.items())
    b2b_form = (f"<form class=rq method=post action=/b2b-upit id=b2b-forma>{b_msg}<input type=hidden name=lang value={lang}>"
                f"<label>{t['b_company']}<input name=company required maxlength=80 autocomplete=organization "
                f"value=\"{esc(bf.get('company', ''))}\"></label>"
                f"<label>{t['b_email']}<input name=email type=email required maxlength=120 autocomplete=email "
                f"value=\"{esc(bf.get('email', ''))}\"></label>"
                f"<label>{t['b_interest']}<select name=interest>{iopts}</select></label>"
                f"<label>{t['b_need']}<textarea name=need required maxlength=1500 placeholder=\"{esc(t['b_ph'])}\">"
                f"{esc(bf.get('need', ''))}</textarea></label>"
                f"<label class=ck><input type=checkbox name=consent value=1 required><span>{t['b_consent']}</span></label>"
                "<div class=hp aria-hidden=true><label>Web<input name=web tabindex=-1 autocomplete=off></label></div>"
                f"<button class='btn p' type=submit>{t['b_btn']}</button></form>")
    b2b = "".join(f"<div><b>{esc(n)}</b><em>{esc(p)}</em><span>{esc(d)}</span></div>" for n, p, d in t["b2b"])
    faq = "".join(f"<details><summary>{esc(q)}</summary><p>{esc(a)}</p></details>" for q, a in t["faq"])
    body = (f"{CSS}<style>{N.CSS}</style><section class=ph1><h1>{t['h1']}</h1><p class=lead>{t['lead']}</p></section>"
            f"<p class=cj-found>{t['founding']}</p><div class=cj-plans>{''.join(cards)}</div>"
            f"<p class=cj-soon>{t['soon']}</p>"
            f"<h2 id=cekanje>{t['wl_h']}</h2><p class=lead>{t['wl_p']}</p><div class=cj-wrap>{wl_form}</div>"
            f"<h2 id=b2b style='margin-top:56px'>{t['b2b_h']}</h2><p class=lead>{t['b2b_p']}</p><div class=cj-b2b>{b2b}</div>"
            f"<div class=cj-wrap>{b2b_form}</div>"
            f"<h2 style='margin-top:56px'>{t['faq_h']}</h2><div class=faq style='margin:0'>{faq}</div>")
    en, hr = N.PATHS["pricing"]
    return P._shell(lang, t["title"], t["desc"], en, hr, body)
