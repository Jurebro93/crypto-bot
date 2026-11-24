"""Vijeće: one pass, the state, the page's one line (18.11., vlasnik: "neka alat sam sebe popravlja i uči i odlučuje").

tick() (run_vijece.py tick, every 15 min from start.sh; a light job, it only waits on the two APIs):
  1. the first run remembers when the council started (older notes stay the owner's) and stores Claude's four
     proposals once (vijece/sjeme.py)
  2. the direction session: opened when due, members that owe an answer asked again (vijece/smjer.py)
  3. every waiting note: the API reviewers (OpenAI, then Claude, who sees OpenAI's review) that have not reviewed it,
     within their day budgets; then the decision when it can be taken (vijece/odluka.py)
  4. the session is closed when all its proposals are decided
Every review and every decision is one log line "vijeće: ocjena ..." / "vijeće: odluka ..." (split at 900 characters);
a member that cannot review (no key, budget spent) is said once a day and its notes wait: no decision is taken on one
voice except the Grok wait rule. Env VIJECE=0: one line, nothing else.
"""
import sqlite3
import time

from vijece import kriticari, odluka, sjeme, smjer, store

MAX_CALLS = 8     # reviews per member in one pass (the pass stays short; the rest waits 15 min)
SYM = {"slazem": "✔", "doradi": "✎", "protiv": "✘"}


def _ocijeni(con, clan, n, oc, stanje, now, log):
    """One API review stored and logged. Returns "ok", "note" (only this note failed) or "clan" (the member is out
    for this pass, said once a day)."""
    try:
        res = kriticari.ocijeni(con, clan, n, {"ocjene": oc, "stanje": stanje()}, now)
    except kriticari.Nedostupan as e:
        if store.jednom(con, f"nedostupan:{clan}:{'budzet' if 'budžet' in str(e) else str(e)[:40]}", store.dan(now)):
            store.reci(log, "", f"{store.IME[clan]} danas ne može ocjenjivati ({e}); prijedlozi koji čekaju njegovu ocjenu "
                                "ostaju u redu i ne odlučuju se jednim glasom")
        return "clan"
    except kriticari.Greska as e:
        store.reci(log, "", f"ocjena #{n['id']} ({store.IME[clan]}) nije uspjela: {e}"
                            + (f", trošak {e.usd:.4f} $".replace(".", ",") if e.usd else ""))
        return "note" if "privatnost" in str(e) or "neispravan" in str(e) else "clan"
    crit = res["critique"] + (f"\nNeto zarada: {res['kako_povecava_zaradu']}" if res.get("kako_povecava_zaradu") else "")
    try:
        store.upisi_ocjenu(con, n["id"], clan, res["verdict"], crit, res.get("refined_change"), res.get("model"),
                           res.get("usd"), now)
    except ValueError as e:
        store.reci(log, "", f"ocjena #{n['id']} ({store.IME[clan]}) nije zapisana: {e}")
        return "note"
    store.reci_ocjenu(log, n, clan, store.ocjene(con, n["id"])[clan])
    return "ok"


def stanje(con, now=None):
    """The council now: the queue with who is missing, today's numbers, what waits for the coding session."""
    now = int(now or time.time())
    notes = store.red(con)
    oc = store.ocjene_za(con, [n["id"] for n in notes])
    ceka = {m: 0 for m in store.CLANOVI}
    rows = []
    for n in notes:
        got = oc.get(n["id"]) or {}
        miss = [m for m in store.ocjenjivaci(n["predlagac"]) if m not in got]
        for m in miss:
            ceka[m] += 1
        rows.append({"id": n["id"], "title": n.get("title"), "predlagac": n["predlagac"], "ts": n["ts"],
                     "ocjene": {m: o["verdict"] for m, o in got.items()}, "ceka": miss})
    return {"red": rows, "ceka": ceka, "danas": store.dnevno(con, now), "za_izvedbu": store.broj_za_izvedbu(con)}


def stanje_redak(st):
    d = st["danas"]
    ck = ", ".join(f"{store.IME[m]} {n}" for m, n in st["ceka"].items() if n)
    return (f"stanje: u redu {len(st['red'])}" + (f" (čeka ocjenu: {ck})" if ck else "")
            + f" · danas ocjena {d['ocjena']}, odluka {d['odluka']} · za izvedbu {st['za_izvedbu']} · trošak danas OpenAI "
            + f"{d['openai_usd']:.3f} $ od {store.strop('openai'):.2f}, Claude {d['claude_usd']:.3f} $ od "
            + f"{store.strop('claude'):.2f}").replace(".", ",")


def tick(now=None, log=None, con=None, smjer_sada=False):
    """One pass (see the module text). Returns a small dict of what happened."""
    log = log or print
    if not store.ukljuceno():
        log(store.PREFIX + "isključeno (VIJECE=0), ništa ne radim", flush=True)
        return {"skip": "isključeno"}
    now = int(now or time.time())
    own = con is None
    if own:
        con = store.connect()
    try:
        store.ensure(con)
        first = store.start_ts(con, create=False) is None
        store.start_ts(con, now)
        if first:
            store.reci(log, "", "prvi prolaz: prijedlozi (bilješke vrste suggestion) zapisani od sada idu na ocjenu "
                                "druga dva člana; stariji ostaju vlasniku")
        out = {"sjeme": len(sjeme.jednom(con, now, log)), "ocjena": 0, "odluka": 0}
        try:
            smjer.korak(con, now, log, force=smjer_sada)
        except Exception as e:  # noqa: BLE001 - the session never costs the reviews their pass
            store.reci(log, "smjer: ", f"prolaz sjednice nije uspio: {type(e).__name__}: {e}")
        cache = {}

        def stanje_txt():
            if "t" not in cache:
                s = smjer.sjednica(con) or {}
                cache["t"] = s.get("brief") or smjer.brief(now, con)
            return cache["t"]
        out_clan, calls = set(), {m: 0 for m in store.API_CLANOVI}
        for n in store.red(con):
            oc = store.ocjene(con, n["id"])
            for m in store.API_CLANOVI:
                if m not in store.ocjenjivaci(n["predlagac"]) or m in oc or m in out_clan or calls[m] >= MAX_CALLS:
                    continue
                calls[m] += 1
                r = _ocijeni(con, m, n, oc, stanje_txt, now, log)
                if r == "ok":
                    out["ocjena"] += 1
                    oc = store.ocjene(con, n["id"])
                elif r == "clan":
                    out_clan.add(m)
            try:
                if odluka.odluci(con, n, now, log):
                    out["odluka"] += 1
            except (sqlite3.Error, ValueError) as e:
                store.reci(log, "", f"odluka #{n['id']} nije donesena: {type(e).__name__}: {e}")
        try:
            smjer.zakljuci(con, now, log)
        except Exception as e:  # noqa: BLE001
            store.reci(log, "smjer: ", f"zaključak sjednice nije uspio: {type(e).__name__}: {e}")
        line = stanje_redak(stanje(con, now))
        if out["ocjena"] or out["odluka"] or out["sjeme"] or store.kv_get(con, "zadnji_redak") != line:
            store.kv_put(con, "zadnji_redak", line)
            log(store.PREFIX + line, flush=True)
        return out
    finally:
        if own:
            con.close()


def ispis(now=None, log=None, con=None):
    """run_vijece.py stanje: the queue and the last decisions as lines."""
    log = log or print
    now = int(now or time.time())
    own = con is None
    if own:
        con = store.connect()
    try:
        if not store.ukljuceno():
            log(store.PREFIX + "isključeno (VIJECE=0)")
        st = stanje(con, now)
        log(store.PREFIX + stanje_redak(st))
        for r in st["red"]:
            oc = ", ".join(f"{store.IME[m]} {v}" for m, v in r["ocjene"].items()) or "bez ocjena"
            log(f"  red #{r['id']} „{store.kratko(r['title'], 100)}” ({store.IME[r['predlagac']]}): {oc}; čeka: "
                + (", ".join(store.IME[m] for m in r["ceka"]) or "odluku"))
        for d in store.zadnje_odluke(con, 20):
            when = time.strftime("%d.%m. %H:%M", time.gmtime(d["ts"]))
            log(f"  odluka #{d['note_id']} {when} „{store.kratko(d['title'], 100)}” ({store.IME[d['proposer']]}): "
                f"{d['decision_hr']}" + (f" · {d['applied']}" if d.get("applied") else "")
                + f" · {store.kratko(d.get('reason'), 300)}")
        zi = store.za_izvedbu(con, 50)
        for z in zi:
            log(f"  za izvedbu #{z['id']} „{store.kratko(z['title'], 120)}”"
                + (f" · promjena {store.kratko(str(z['change']), 200)}" if z.get("change") else ""))
        s = smjer.sjednica(con)
        if s and not s.get("zakljuceno"):
            log("  smjer: sjednica otvorena " + time.strftime("%d.%m. %H:%M UTC", time.gmtime(s["ts"]))
                + f" ({s.get('razlog')}); članovi: " + ", ".join(f"{store.IME[m]} {v}" for m, v in (s.get("clanovi") or {}).items()))
        z = smjer.zadnji(con)
        if z:
            log(f"  smjer, zadnja sjednica: prihvaćeno {len(z['prihvaceno'])}, odbijeno {len(z['odbijeno'])}, vlasniku "
                f"{len(z['vlasniku'])}, čeka {len(z['ceka'])}")
        return st
    finally:
        if own:
            con.close()


def ui_linije(con, ids, esc):
    """{note id: one small HTML line} for the notes on the Autopilot page that have a council review or decision:
    "Vijeće: OpenAI ✔ · Claude ✎ · Grok … → prihvaćeno i primijenjeno". Read-only; every text escaped with esc."""
    ids = [int(i) for i in ids if i]
    oc, od = store.ocjene_za(con, ids), store.odluke_za(con, ids)
    out = {}
    for nid in ids:
        got, d = oc.get(nid) or {}, od.get(nid)
        if not got and not d:
            continue
        n = store.note(con, nid)
        if not n:
            continue
        bits = []
        for m in store.ocjenjivaci(n["predlagac"]):
            o = got.get(m)
            mark = SYM.get(o["verdict"], "?") if o else "…"
            tip = f' title="{esc(store.kratko(o.get("critique"), 600))}"' if o else ""
            bits.append(f"<span{tip}>{esc(store.IME[m])} {esc(mark)}</span>")
        line = "Vijeće: " + " · ".join(bits)
        if d:
            line += " → " + esc(store.ODLUKA_HR.get(d["odluka"], d["odluka"]))
            if d.get("razlog") and d["odluka"] == "vlasniku":
                line += f': {esc(store.kratko(d["razlog"], 240))}'
        out[nid] = f"<p class=mut>{line}</p>"
    return out
