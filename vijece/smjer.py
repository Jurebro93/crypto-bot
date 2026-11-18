"""Vijeće: the direction session (18.11., vlasnik: "neka pomognu odlučiti u kojem smjeru ići ... neka alat sam sebe
popravlja i uči i odlučuje kako i u kojem smjeru ići i na što usmjeriti sve resurse, i zašto").

brief(now)   what is measured, as one compact Croatian block (at most BRIEF_MAX characters): the learner's result
             (veliki/nauceno), the call power (veliki/moc), the cost per source of the last 7 days (usage/daily), the
             state board (stanja/ploca), the stored strategy tests that have a reader (replay, the wallets' copy, the
             source consensus, Insajderi 2.0), the real cost of a round trip, the stake and the trades a day. A source
             that cannot be read is NAMED as missing and never raises. Nothing private is in it (ocisti: critic/
             privacy.scrub plus env-style names and key-looking strings).
otvori()     asks OpenAI and Claude (their council day budgets) for ONE direction for all resources; each answers
             with at most 3 proposals, stored as suggestion notes "Smjer: ..." under the member's key, evidence
             {"vijece": "smjer", "sjednica": ts}. They then go through the normal cross-review (vijece/odluka.py).
             Grok gets the same brief as direction_request in get_council_queue and answers with submit_suggestion.
zakljuci()   once every proposal of the session is decided (or 24 h passed): the "vijeće: smjer: ..." lines and the
             result in vijece_kv "smjer_zadnji" (get_council, the report).

A session is due once after the deploy (trade settings vijece_smjer_1811), then once in every week that starts on
Monday (Zagreb), and when the learner's verdict changed since the last session (at most one session a day).
"""
import datetime as dt
import json
import re
import sqlite3
import time

from critic import privacy
from trade import settings
from ui import assistnotes
from vijece import kriticari, store

BRIEF_MAX = 8000
PART_MAX = 900
BOARD_MAX = 2200
ONCE_KEY = "vijece_smjer_1811"
SESSION_S = 24 * 3600
VERDICT_GAP_S = 24 * 3600
MAX_PRIJEDLOGA = 3
TZ = "Europe/Zagreb"
OPENAI_MAX_OUT = 6000
CLAUDE_MAX_TOKENS = 10000

PITANJE = ("Jedan smjer za SVE resurse alata: na što se fokusirati, zašto baš to, što ugasiti, koji podaci nedostaju i "
           "zašto, je li brzina važna, prva tri koraka i KAKO svaki korak povećava neto zaradu (PnL trgovanja minus "
           "trošak rada), uz mjerenje koje će to pokazati unutar 14 dana.")

SYSTEM = """Ti si član vijeća alata MemeSonar (trading bot za Solana midcap memecoine, market cap 2M-200M $). Vijeće
čine Grok, OpenAI i Claude; vlasnik traži da vijeće samo odluči u kojem smjeru alat ide i na što troši SVE resurse
(novac za API-je, vrijeme poslužitelja, demo i pravi kapital). Dobit ćeš što je izmjereno (stanje alata) i pitanje.

Odgovori s najviše 3 prijedloga, najvažniji prvi; svaki mora stajati sam za sebe jer ga druga dva člana zatim kritički
ocjenjuju i prihvaća se samo ako se slože. Za svaki prijedlog:
- naslov: jedna rečenica što napraviti;
- obrazlozenje: zašto baš to, s brojevima iz stanja (n, postotci, $, SOL); ako nešto nije izmjereno, reci;
- koraci: prva tri konkretna koraka;
- sto_ugasiti: što ugasiti ili smanjiti da se oslobode resursi (ili "ništa");
- koji_podaci: koji podaci nedostaju i zašto; je li brzina važna;
- kako_povecava_zaradu: kako i koliko svaki korak mijenja NETO zaradu (PnL trgovanja minus trošak rada);
- mjerenje: koji broj će unutar 14 dana pokazati da je uspjelo, i prag;
- proposed_change: samo ako je prijedlog jedna promjena postavke, JSON objekt kao tekst (npr. {"key": "runup_max",
  "from": 0.15, "to": 0.10}); inače null.

Pravila: ne izmišljaj podatke; ne predlaži ništa za mikrokapove (ispod 2M $); pravi novac (ulog, broj pozicija, TP,
SL, prekidači, autotrade) mijenja samo vlasnik, to vijeće ne primjenjuje. Piši hrvatski, jednostavno i kratko."""

_NT = {"anyOf": [{"type": "string"}, {"type": "null"}]}
SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["prijedlozi"],
    "properties": {"prijedlozi": {"type": "array", "items": {
        "type": "object", "additionalProperties": False,
        "required": ["naslov", "obrazlozenje", "koraci", "sto_ugasiti", "koji_podaci", "kako_povecava_zaradu", "mjerenje",
                     "proposed_change"],
        "properties": {"naslov": {"type": "string"}, "obrazlozenje": {"type": "string"},
                       "koraci": {"type": "array", "items": {"type": "string"}},
                       "sto_ugasiti": {"type": "string"}, "koji_podaci": {"type": "string"},
                       "kako_povecava_zaradu": {"type": "string"}, "mjerenje": {"type": "string"},
                       "proposed_change": {**_NT, "description": "JSON objekt promjene postavke kao tekst, ili null"}}}}},
}

# ---------- privacy --------------------------------------------------------------------------------------------------
ENV_NAME = re.compile(r"\b[A-Z][A-Z0-9]+(?:_[A-Z0-9]+)+\b")                      # FOO_BAR_KEY: an environment-style name
KEYLIKE = re.compile(r"\b(?:sk|pk|rk|xai|ghp|gho|key|tok)[-_][A-Za-z0-9_\-]{12,}|[A-Za-z0-9+/_\-]{40,}={0,2}")


def ocisti(text, extra=()):
    """The text with nothing private in it: critic/privacy.scrub (secret values and names of this environment, wallet
    addresses, hosts, paths, internal file names) and, on top, every environment-style name and key-looking string
    whether or not it is set on this machine."""
    s = privacy.scrub(text, (), extra=extra)
    s = KEYLIKE.sub("[skriveno]", s)
    return ENV_NAME.sub("[skriveno]", s)


# ---------- the brief ------------------------------------------------------------------------------------------------

def _ucenje(now, con):
    from veliki import nauceno
    s = nauceno.summary()
    if not s:
        return None
    return (f"presuda: {s.get('verdict_text') or s.get('verdict')}; {s.get('rows')} zamišljenih tradeova, {s.get('days')} "
            f"dana, provjera na zadnjih {s.get('test_days')} neviđenih; odabrani: {nauceno._s(s.get('picked'))}; svi tih "
            f"dana: {nauceno._s(s.get('all'))}; najviše pomaže: {'; '.join((s.get('helps') or [])[:3]) or '—'}; najviše "
            f"šteti: {'; '.join((s.get('hurts') or [])[:3]) or '—'}")


def presuda_ucenja():
    """The learner's stored verdict (kandidat | premalo | nema_plusa), or None without a result."""
    try:
        from veliki import nauceno
        return (nauceno.latest() or {}).get("verdict") or None
    except Exception:  # noqa: BLE001 - no result is not an error
        return None


def _moc(now, con):
    from veliki import moc
    r = moc.latest()
    if not r or not r.get("ts"):
        return None
    return moc.line(r)[len(moc.PREFIX):]


def _f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return 0.0


def _trosak(now, con):
    from usage import daily
    rows = daily.days(7, now)
    if not rows:
        return None
    s = {"x": 0.0, "apify": 0.0, "pp_sol": 0.0, "helius": 0.0, "ai": 0.0, "openai": 0.0, "vijece": 0.0}
    xp = {}
    for d in rows:
        tw = d.get("twitterapi") or {}
        s["x"] += _f(tw.get("usd"))
        for k, v in (tw.get("dijelovi") or {}).items():
            xp[k] = xp.get(k, 0.0) + _f(v)
        s["apify"] += _f((d.get("apify") or {}).get("usd_bot"))
        s["pp_sol"] += _f((d.get("pumpportal") or {}).get("sol"))
        s["helius"] += _f((d.get("helius") or {}).get("krediti_bot"))
        s["ai"] += _f((d.get("ai") or {}).get("usd"))
        s["openai"] += _f((d.get("openai") or {}).get("usd"))
        v = d.get("vijece") or {}
        s["vijece"] += _f(v.get("openai_usd")) + _f(v.get("claude_usd"))
    top = ", ".join(f"{k} {v:.2f}" for k, v in sorted(xp.items(), key=lambda kv: -kv[1])[:4] if v)
    return (f"{len(rows)} spremljenih dana: X (twitterapi) {s['x']:.2f} $" + (f" ({top})" if top else "")
            + f"; Apify {s['apify']:.2f} $; PumpPortal {s['pp_sol']:.3f} SOL; Helius {s['helius']:.0f} kredita; AI oznake "
            f"{s['ai']:.2f} $; OpenAI kritičar {s['openai']:.2f} $; vijeće {s['vijece']:.2f} $")


def _ploca(now, con):
    from stanja import ploca
    lines = ploca.text(ploca.now(now), now)
    return "\n".join("- " + ln[:260] for ln in lines)[:BOARD_MAX] if lines else None


def _replay(now, con):
    from veliki import replay
    r = replay.latest()
    if not r or not r.get("ts"):
        return None
    return replay.line(r)[len(replay.PREFIX):]


def _kopija(now, con):
    from wallets import kopija
    r = kopija.latest()
    if not r or not r.get("ts"):
        return None
    return kopija.line(r)[len(kopija.PREFIX):]


def _compact(d):
    from critic import data as cdata
    return json.dumps(cdata.compact(d, max_list=4, max_str=160, max_depth=3), ensure_ascii=False, default=str)


def _konsenzus(now, con):
    from konsenzus import view
    d = view.critic_summary()
    return _compact(d) if d else None


def _insajderi(now, con):
    from insajderi import report
    d = report.critic_summary()
    return _compact(d) if d else None


def _ulog(now, con):
    from veliki import replay
    bits = [f"povratni trošak jednog tradea (kupnja + prodaja): nikad ispod {replay.RT_FLOOR * 100:.1f} % pri ulogu "
            f"{replay.SIZE_SOL:g} SOL"]
    if con is not None:
        try:
            size = settings.raw(con).get("size_sol")
            if size:
                bits.append(f"ulog po automatskoj kupnji {float(size):g} SOL")
        except (sqlite3.Error, TypeError, ValueError):
            pass
        try:
            rows = con.execute("SELECT COALESCE(mode, 'dry'), COUNT(*) FROM positions WHERE opened_ts >= ? GROUP BY 1",
                               (int(now) - 7 * 86400,)).fetchall()
            if rows:
                hr = {"live": "pravi novac", "dry": "probno"}
                bits.append("pozicija dnevno (7 d): " + ", ".join(f"{hr.get(m, m)} {n / 7:.1f}" for m, n in rows))
        except sqlite3.Error:
            pass
    return "; ".join(bits)


IZVORI = (   # (the name the brief uses, the reader): a reader returns text or None (nothing stored yet)
    ("Učenje (knjiga sjene, neviđeni dani)", _ucenje),
    ("Moć poziva (X računi na midcapovima)", _moc),
    ("Trošak po izvoru, zadnjih 7 dana", _trosak),
    ("Trošak i veličina tradea", _ulog),
    ("Test: povijesna simulacija dnevnog raspona", _replay),
    ("Test: kopiranje dokazanih novčanika", _kopija),
    ("Test: konsenzus izvora", _konsenzus),
    ("Test: Insajderi 2.0", _insajderi),
    ("Ploča stanja (što je uključeno)", _ploca),
)


def brief(now=None, con=None, izvori=None):
    """The state block (see the module text). izvori: the test seam, ((name, fn(now, con)), ...)."""
    now = int(now or time.time())
    parts = [f"STANJE ALATA, izmjereno do {time.strftime('%d.%m.%Y %H:%M', time.gmtime(now))} UTC (svi rezultati neto, "
             "nakon troška)"]
    missing = []
    for name, fn in (izvori if izvori is not None else IZVORI):
        try:
            txt = fn(now, con)
        except Exception as e:  # noqa: BLE001 - a source that fails is named as missing, never raises
            missing.append(f"{name} (ne može se pročitati: {type(e).__name__})")
            continue
        if not txt:
            missing.append(f"{name} (još nema spremljenog rezultata)")
            continue
        txt = str(txt).strip()
        cap = BOARD_MAX if "\n" in txt else PART_MAX
        parts.append(f"{name}: " + (txt if len(txt) <= cap else txt[:cap] + " …"))
    if missing:
        parts.append("NEDOSTAJE (nije izmjereno ili se ne može pročitati): " + "; ".join(missing))
    try:
        extra = privacy.owner_wallets(con)
    except Exception:  # noqa: BLE001
        extra = set()
    out = ocisti("\n".join(parts), extra)
    return out if len(out) <= BRIEF_MAX else out[:BRIEF_MAX - 2] + " …"


# ---------- when a session is due ------------------------------------------------------------------------------------

def tjedan(ts):
    """The ordinal of the Monday (Zagreb) that starts the week of ts."""
    from zoneinfo import ZoneInfo
    d = dt.datetime.fromtimestamp(int(ts), ZoneInfo(TZ)).date()
    return d.toordinal() - d.weekday()


def sjednica(con):
    return store.kv_get(con, "sjednica") or None


def na_redu(con, now=None):
    """Why a new session is due now (Croatian), or None."""
    now = int(now or time.time())
    s = sjednica(con)
    if s and not s.get("zakljuceno"):
        return None                                   # one at a time
    first = settings.raw(con).get(ONCE_KEY)
    if not first:
        return "prva sjednica nakon deploya"
    last_ts = int((s or {}).get("ts") or first)
    if tjedan(now) > tjedan(last_ts):
        return "tjedna sjednica (ponedjeljak)"
    v = presuda_ucenja()
    old = (s or {}).get("presuda_ucenja")
    if v and s and not old:                           # no learner result at the last session: remembered, no session
        s["presuda_ucenja"] = v
        store.kv_put(con, "sjednica", s)
    elif v and old and v != old and now - last_ts >= VERDICT_GAP_S:
        return f"presuda učenja se promijenila ({old} → {v})"
    return None


# ---------- the session ----------------------------------------------------------------------------------------------

def _pc(x):
    return kriticari._refined(x)


def _validiraj(d):
    if not isinstance(d, dict) or not isinstance(d.get("prijedlozi"), list):
        raise ValueError("nema popisa prijedlozi")
    out = []
    for x in d["prijedlozi"]:
        if not isinstance(x, dict):
            continue
        naslov = str(x.get("naslov") or "").strip()
        obr = str(x.get("obrazlozenje") or "").strip()
        if not naslov or not obr:
            continue
        koraci = [str(k).strip()[:400] for k in (x.get("koraci") or []) if str(k or "").strip()][:5]
        out.append({"naslov": naslov[:150], "obrazlozenje": obr[:2500], "koraci": koraci,
                    **{k: str(x.get(k) or "").strip()[:800] for k in ("sto_ugasiti", "koji_podaci",
                                                                     "kako_povecava_zaradu", "mjerenje")},
                    "proposed_change": _pc(x.get("proposed_change"))})
        if len(out) >= MAX_PRIJEDLOGA:
            break
    if not out:
        raise ValueError("nijedan prijedlog nije valjan")
    return out


def _spremi(con, clan, p, ts, model):
    """One direction proposal as a suggestion note under the member's key; the note id."""
    title = (store.SMJER_PREFIX + p["naslov"])[:assistnotes.TITLE_MAX]
    interp = f"{p['obrazlozenje']}\nKako povećava neto zaradu: {p['kako_povecava_zaradu'] or 'nije navedeno'}"
    impr = "\n".join(x for x in (
        "Koraci: " + " ".join(f"{i}. {k}" for i, k in enumerate(p["koraci"], 1)) if p["koraci"] else "",
        f"Što ugasiti: {p['sto_ugasiti']}" if p["sto_ugasiti"] else "",
        f"Koji podaci nedostaju: {p['koji_podaci']}" if p["koji_podaci"] else "",
        f"Mjerenje (14 dana): {p['mjerenje']}" if p["mjerenje"] else "") if x)
    ev = {"vijece": "smjer", "sjednica": int(ts), "clan": clan, "model": model,
          "kako_povecava_zaradu": p["kako_povecava_zaradu"], "mjerenje": p["mjerenje"]}
    d = assistnotes.submit_suggestion(con, store.kid_of(clan), title, interp[:assistnotes.TEXT_MAX],
                                      impr[:assistnotes.TEXT_MAX] or None, ev, p["proposed_change"])
    return d["id"]


def _pitaj(con, clan, s, now, log):
    """Ask one member for its direction proposals; the member's state in the session ("ok" or "ceka: why")."""
    text = PITANJE + "\n\n" + (s.get("brief") or "")
    try:
        text = kriticari.siguran_tekst(text, con)
        max_out = OPENAI_MAX_OUT if clan == "openai" else CLAUDE_MAX_TOKENS
        res = kriticari.pitaj(con, clan, SYSTEM, text, SCHEMA, "vijece_smjer", max_out, now)
        props = _validiraj(res["data"])
    except kriticari.Nedostupan as e:
        return f"ceka: {e}"
    except (kriticari.Greska, ValueError) as e:
        store.reci(log, f"smjer: {store.IME[clan]} nije odgovorio: ", f"{e}; pokušavam ponovno u idućem prolazu")
        return f"ceka: poziv nije uspio ({store.kratko(e, 120)})"
    ids = []
    for p in props:
        try:
            ids.append(_spremi(con, clan, p, s["ts"], res.get("model")))
        except ValueError as e:
            store.reci(log, "smjer: ", f"prijedlog „{store.kratko(p['naslov'], 80)}” ({store.IME[clan]}) nije zapisan: {e}")
    usd = f"{res.get('usd') or 0:.4f} $".replace(".", ",")
    store.reci(log, f"smjer: {store.IME[clan]} predlaže ({len(ids)}, {usd}, {res.get('model')}): ",
               " | ".join(f"#{i} {p['naslov']}" for i, p in zip(ids, props)), f"smjer: {store.IME[clan]} predlaže")
    return "ok"


def otvori(con, now=None, log=print, razlog="ručno"):
    """Open a direction session: the brief, the question to OpenAI and Claude, their proposals as notes. Returns the
    session dict, or None when no API member can be asked now (it is tried again in the next pass)."""
    now = int(now or time.time())
    store.ensure(con)
    missing = {m: kriticari.nedostupan(con, m) for m in store.API_CLANOVI}
    if all(missing.values()):
        if store.jednom(con, "smjer_ceka", store.dan(now)):
            store.reci(log, "smjer: ", "sjednica čeka (" + "; ".join(f"{store.IME[m]}: {w}" for m, w in missing.items())
                       + "); pokušavam u svakom prolazu")
        return None
    od_id = int(con.execute("SELECT COALESCE(MAX(id), 0) FROM assistant_notes").fetchone()[0])
    s = {"ts": now, "razlog": razlog, "presuda_ucenja": presuda_ucenja(), "od_id": od_id, "brief": brief(now, con),
         "clanovi": {}, "zakljuceno": None}
    store.reci(log, "smjer: ", f"sjednica otvorena ({razlog}); pitanje: {PITANJE}")
    for m in store.API_CLANOVI:
        s["clanovi"][m] = _pitaj(con, m, s, now, log)
    if all(v != "ok" for v in s["clanovi"].values()):
        if store.jednom(con, "smjer_ceka", store.dan(now)):
            store.reci(log, "smjer: ", "sjednica nije otvorena: " + "; ".join(
                f"{store.IME[m]} {v.removeprefix('ceka: ')}" for m, v in s["clanovi"].items()))
        return None
    store.kv_put(con, "sjednica", s)
    if not settings.raw(con).get(ONCE_KEY):
        settings.put(con, ONCE_KEY, now, "vijeće")
    return s


def dopuni(con, s, now=None, log=print):
    """A member that could not answer when the session opened (budget, a failed call) is asked again."""
    changed = False
    for m, v in list((s.get("clanovi") or {}).items()):
        if v == "ok":
            continue
        new = _pitaj(con, m, s, int(now or time.time()), log)
        if new != v:
            s["clanovi"][m] = new
            changed = True
    if changed:
        store.kv_put(con, "sjednica", s)
    return s


def prijedlozi(con, s):
    """The session's proposals: suggestion notes "Smjer: ..." written after it opened (the members' and Grok's)."""
    try:
        rows = con.execute(f"SELECT {', '.join(store.NOTE_COLS)} FROM assistant_notes WHERE kind='suggestion' AND id > ? "
                           "AND title LIKE ? ORDER BY id", (int(s.get("od_id") or 0), store.SMJER_PREFIX + "%")).fetchall()
    except sqlite3.Error:
        return []
    return [store._note(r) for r in rows]


def grok_odgovorio(con, s):
    return any(n["predlagac"] == "grok" for n in prijedlozi(con, s))


def zahtjev_groku(con, now=None):
    """The direction_request of get_council_queue while a session is open and Grok has not answered, else None."""
    s = sjednica(con)
    if not s or s.get("zakljuceno") or grok_odgovorio(con, s):
        return None
    return {"session_ts": s["ts"], "closes_ts": s["ts"] + SESSION_S, "question": PITANJE, "brief": s.get("brief") or "",
            "answer_with": {"tool": "submit_suggestion", "arguments": {
                "title": store.SMJER_PREFIX + "<one sentence: what to focus all resources on>",
                "interpretation": "<why this one, with numbers from the brief and from X; what to switch off; which "
                                  "data are missing; does speed matter; HOW it raises net profit>",
                "improvement": "<the first three steps and the measurement that shows it within 14 days>",
                "evidence": {"vijece": "smjer", "sjednica": s["ts"]}}},
            "how": ("Answer in Croatian with at most 3 submit_suggestion calls whose title starts with \"Smjer: \". "
                    "OpenAI and Claude then review each one critically; it is accepted only when they agree.")}


def zakljuci(con, now=None, log=print, force=False):
    """Close the open session when every proposal is decided and no member still owes an answer, or after 24 h: the
    "vijeće: smjer: ..." lines and the stored result. Returns the result, or None while the session stays open."""
    now = int(now or time.time())
    s = sjednica(con)
    if not s or s.get("zakljuceno"):
        return None
    props = prijedlozi(con, s)
    odl = store.odluke_za(con, [n["id"] for n in props])
    oc = store.ocjene_za(con, [n["id"] for n in props])
    waits = [n for n in props if n["id"] not in odl and n["status"] == "novo"]
    owes = [m for m, v in (s.get("clanovi") or {}).items() if v != "ok"]
    if not force and now - s["ts"] < SESSION_S and (waits or owes or not props):
        return None
    res = {"sjednica": s["ts"], "ts": now, "razlog": s.get("razlog"), "prihvaceno": [], "odbijeno": [], "vlasniku": [],
           "ceka": []}
    for n in props:
        o = odl.get(n["id"])
        ev = n.get("evidence") if isinstance(n.get("evidence"), dict) else {}
        row = {"id": n["id"], "naslov": (n.get("title") or "").removeprefix(store.SMJER_PREFIX), "clan": n["predlagac"]}
        if o is None:
            if n["status"] != "novo":      # the owner decided it on the page meanwhile
                row["razlog"] = f"vlasnik: {n['status']}"
                res["prihvaceno" if n["status"] in ("prihvaćeno", "primijenjeno") else "odbijeno"].append(row)
                continue
            revs = store.ocjenjivaci(n["predlagac"])
            row["razlog"] = "još nema ocjenu: " + ", ".join(store.IME[m] for m in revs if m not in (oc.get(n["id"]) or {}))
            res["ceka"].append(row)
        elif o["odluka"] in ("prihvaceno_primijenjeno", "prihvaceno_za_izvedbu"):
            kako = ev.get("kako_povecava_zaradu") or _iz_teksta(n.get("interpretation"), "Kako povećava neto zaradu:")
            mj = ev.get("mjerenje") or _iz_teksta(n.get("improvement"), "Mjerenje (14 dana):")
            row.update(odluka=o["odluka"], kako_povecava_zaradu=kako, mjerenje=mj, primijenjeno=o.get("primijenjeno"))
            res["prihvaceno"].append(row)
        else:
            row["razlog"] = o.get("razlog")
            res["odbijeno" if o["odluka"] == "odbijeno" else "vlasniku"].append(row)
    when = time.strftime("%d.%m. %H:%M UTC", time.gmtime(s["ts"]))
    store.reci(log, "smjer: ", f"sjednica od {when} ({s.get('razlog')}) zaključena: prihvaćeno {len(res['prihvaceno'])}, "
               f"odbijeno {len(res['odbijeno'])}, vlasniku {len(res['vlasniku'])}, čeka {len(res['ceka'])}"
               + (f"; nisu odgovorili: {', '.join(store.IME[m] for m in owes)}" if owes else "")
               + ("" if grok_odgovorio(con, s) else "; Grok nije poslao svoj smjer"))
    for r in res["prihvaceno"]:
        if r.get("odluka"):
            store.reci(log, f"smjer: PRIHVAĆENO #{r['id']} „{store.kratko(r['naslov'], 150)}” ({store.IME[r['clan']]}, "
                       f"{store.ODLUKA_HR[r['odluka']]}): ",
                       f"kako povećava zaradu: {r.get('kako_povecava_zaradu') or 'nije navedeno'} · mjerenje: "
                       f"{r.get('mjerenje') or 'nije navedeno'}", f"smjer: PRIHVAĆENO #{r['id']}")
        else:
            store.reci(log, f"smjer: PRIHVAĆENO #{r['id']} „{store.kratko(r['naslov'], 150)}”: ", r.get("razlog"))
    for key, word in (("odbijeno", "ODBIJENO"), ("vlasniku", "ČEKA VLASNIKA"), ("ceka", "ČEKA OCJENU")):
        for r in res[key]:
            store.reci(log, f"smjer: {word} #{r['id']} „{store.kratko(r['naslov'], 150)}” ({store.IME[r['clan']]}): ",
                       r.get("razlog") or "bez razloga", f"smjer: {word} #{r['id']}")
    s["zakljuceno"] = now
    s.pop("brief", None)       # the brief is in the notes' context; the closed record stays small
    store.kv_put(con, "sjednica", s)
    store.kv_put(con, "smjer_zadnji", res)
    return res


def _iz_teksta(text, label):
    """The rest of the line that starts with `label` in a note's text (Grok's direction notes carry no evidence keys)."""
    for ln in str(text or "").splitlines():
        if ln.strip().startswith(label):
            return ln.strip()[len(label):].strip()
    return ""


def zadnji(con):
    """The last closed session's result (get_council, the report), or None."""
    return store.kv_get(con, "smjer_zadnji") or None


def korak(con, now=None, log=print, force=False):
    """The session part of one pass: ask again who owes an answer, or open a session when one is due."""
    now = int(now or time.time())
    s = sjednica(con)
    if s and not s.get("zakljuceno"):
        if force:
            store.reci(log, "smjer: ", "sjednica je već otvorena; nova se otvara kad se ova zaključi")
        return dopuni(con, s, now, log)
    why = "ručno" if force else na_redu(con, now)
    return otvori(con, now, log, why) if why else None
