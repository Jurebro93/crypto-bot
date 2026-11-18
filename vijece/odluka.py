"""Vijeće: the decision on a proposal, taken after every new review (18.11., vlasnik: "automatski prihvati sve
prijedloge koji imaju smisla ... doraditi ga i prihvatiti ako se slažu").

The two reviewers of a note are the members who did not write it. With both reviews in:
  neither is "protiv"     accepted. The change in force is the reviewer's refined_change when exactly one gave one (or
                          both gave the same), the original when none did; two DIFFERENT refinements go to the owner.
  both "protiv"           rejected (ui/assistnotes.decide "odbijeno").
  one "protiv", one not   the owner decides; the note stays novo, the reason carries both critiques.
Grok answers through the MCP tools when it polls: when Grok is a reviewer and has not answered VIJECE_GROK_WAIT_S (6 h)
after the note was written, the API reviewer decides alone and the reason says so. No other decision is taken on one
voice: a reviewer without a key or budget makes the note wait.

An accepted proposal by class (klasa):
  pravi_novac  size_sol, max_open, tp_default, sl_default, copy.*, or a key naming pravi / live / autotrade / kill:
               NEVER applied here (CLAUDE.md: real money is switched and sized only by the owner) -> vlasniku.
  auto         a key of ui/assistnotes.APPLY that is not real money, a caller weight, an insider or group label:
               ui/assistnotes.apply (its ranges, its "from" check, flags at most to shadow) -> prihvaceno_primijenjeno.
  kod          no proposed_change or an unknown key (it needs code): marked prihvaćeno "(za izvedbu)" ->
               prihvaceno_za_izvedbu; vijece.za_izvedbu lists them for the coding session.
"""
import json
import time

from ui import assistnotes
from vijece import store

REAL_KEYS = frozenset({"size_sol", "max_open", "tp_default", "sl_default"})
REAL_WORDS = ("pravi", "live", "autotrade", "kill")
REAL_PREFIX = "vijeće preporučuje prihvatiti, ali dira pravi novac"
KEY_FIELDS = ("key", "flag", "setting", "name", "to", "mode")   # where a change names what it switches
ODLUKA_LOG = {"prihvaceno_primijenjeno": "PRIHVAĆENO I PRIMIJENJENO", "prihvaceno_za_izvedbu": "PRIHVAĆENO ZA IZVEDBU",
              "odbijeno": "ODBIJENO", "vlasniku": "VLASNIKU"}


def _key_texts(pc):
    out = [str(k) for k in pc]
    out += [pc[f] for f in KEY_FIELDS if isinstance(pc.get(f), str)]
    return [t.lower() for t in out]


def klasa(pc):
    """pravi_novac | auto | kod of a proposed change (see the module text)."""
    if not isinstance(pc, dict) or not pc:
        return "kod"
    key = str(pc.get("key") or "")
    if key in REAL_KEYS or key.lower().startswith("copy.") or any(w in t for t in _key_texts(pc) for w in REAL_WORDS):
        return "pravi_novac"
    if ("caller" in pc and "weight" in pc) or isinstance(pc.get("insider_label"), dict) \
            or isinstance(pc.get("group_label"), dict):
        return "auto"
    return "auto" if key in assistnotes.APPLY else "kod"


def _isto(a, b):
    return json.dumps(a, sort_keys=True, ensure_ascii=False) == json.dumps(b, sort_keys=True, ensure_ascii=False)


def _pc_txt(pc, cap=300):
    return store.kratko(json.dumps(pc, ensure_ascii=False), cap) if pc else "bez promjene postavke"


def _glas(o, cap=200):
    return f"{o['verdict']}: {store.kratko(o.get('critique'), cap)}"


def _zamijeni(con, n, pc):
    """Write the change in force into the note, the original kept in evidence under "izvorni_prijedlog". Returns the
    raw (proposed_change, evidence) from before, for _vrati."""
    old = con.execute("SELECT proposed_change, evidence FROM assistant_notes WHERE id=?", (n["id"],)).fetchone()
    ev = n.get("evidence")
    new_ev = ({**ev, "izvorni_prijedlog": n.get("proposed_change")} if isinstance(ev, dict) else
              {"izvorni_prijedlog": n.get("proposed_change"), **({"izvorni_dokazi": ev} if ev else {})})
    con.execute("UPDATE assistant_notes SET proposed_change=?, evidence=? WHERE id=?",
                (json.dumps(pc, ensure_ascii=False), json.dumps(new_ev, ensure_ascii=False), n["id"]))
    con.commit()
    return old


def _vrati(con, nid, old):
    con.execute("UPDATE assistant_notes SET proposed_change=?, evidence=? WHERE id=?", (old[0], old[1], nid))
    con.commit()


def _zapisi(con, nid, odl, razlog, primijenjeno, now):
    con.execute("UPDATE vijece_odluke SET ts=?, odluka=?, razlog=?, primijenjeno=? WHERE note_id=?",
                (int(now), odl, (razlog or "")[:4000], primijenjeno, int(nid)))
    con.commit()


def odluci(con, note, now=None, log=print):
    """Decide one note when it can be decided. Returns {"odluka", "razlog", "primijenjeno"} or None (it waits: a
    review is missing, it is decided already, or the owner decided it on the page meanwhile)."""
    now = int(now or time.time())
    n = store.note(con, note["id"] if isinstance(note, dict) else note)
    if not store.u_vijecu(n, store.start_ts(con, create=False)) or store.odluka(con, n["id"]):
        return None
    nid, pred = n["id"], n["predlagac"]
    revs = store.ocjenjivaci(pred)
    oc = store.ocjene(con, nid)
    glasovi = [(m, oc[m]) for m in revs if m in oc]
    grok_kasni = ""
    if len(glasovi) < len(revs):
        api_done = all(m in oc for m in revs if m != "grok")
        wait = store.grok_wait_s()
        if not ("grok" in revs and "grok" not in oc and api_done and glasovi and now - int(n["ts"] or 0) >= wait):
            return None
        grok_kasni = f"Grok nije odgovorio u {wait / 3600:g} h"
    # the decision is claimed first (one row per note): a second process deciding at the same moment finds it taken;
    # a crash before the end leaves the safe outcome (the owner decides)
    cur = con.execute("INSERT OR IGNORE INTO vijece_odluke (note_id, ts, odluka, razlog) VALUES (?,?,?,?)",
                      (nid, now, "vlasniku", "odluka u tijeku"))
    con.commit()
    if not cur.rowcount:
        return None
    kritike = " · ".join(f"{store.IME[m]}: {_glas(o, 600)}" for m, o in glasovi) + (f" · {grok_kasni}" if grok_kasni else "")
    tko = ", ".join(f"{store.IME[m]} {o['verdict']}" for m, o in glasovi) + (f"; {grok_kasni}" if grok_kasni else "")
    protiv = [m for m, o in glasovi if o["verdict"] == "protiv"]
    orig = n.get("proposed_change") if isinstance(n.get("proposed_change"), dict) else None
    odl, razlog, prim = "vlasniku", "", None
    try:
        if len(protiv) == len(glasovi):
            assistnotes.decide(con, nid, "odbijeno", owner_note=store.kratko(f"vijeće: {tko}. {kritike}", 1000))
            odl, razlog = "odbijeno", ("oba ocjenjivača protiv" if len(glasovi) > 1 else "ocjenjivač protiv") + f". {kritike}"
        elif protiv:
            razlog = f"ocjenjivači se ne slažu ({tko}). {kritike}"
        else:
            dorade = [(m, o["refined_change"]) for m, o in glasovi if o.get("refined_change")]
            if len(dorade) == 2 and not _isto(dorade[0][1], dorade[1][1]):
                razlog = ("dvije različite dorade: " + "; ".join(f"{store.IME[m]}: {_pc_txt(pc, 600)}" for m, pc in dorade)
                          + f". {kritike}")
            else:
                pc = dorade[0][1] if dorade else orig
                odl, razlog, prim = _prihvati(con, n, orig, pc, bool(dorade), tko, kritike)
    except ValueError as e:   # the owner decided the note on the page between the check and the write
        if (store.note(con, nid) or {}).get("status") != "novo" and odl == "vlasniku":
            con.execute("DELETE FROM vijece_odluke WHERE note_id=?", (nid,))
            con.commit()
            return None
        razlog = f"nije se moglo zapisati: {e}. {kritike}"
    _zapisi(con, nid, odl, razlog, prim, now)
    head = (f"odluka #{nid} „{store.kratko(n.get('title'), 120)}” ({store.IME[pred]}): {ODLUKA_LOG[odl]} · ")
    body = " · ".join(f"{store.IME[m]}: {_glas(o)}" for m, o in glasovi) + (f" · {grok_kasni}" if grok_kasni else "")
    extra = prim or razlog.split(". ", 1)[0]
    store.reci(log, head, body + (f" · {store.kratko(extra, 400)}" if extra else ""), f"odluka #{nid}")
    return {"odluka": odl, "razlog": razlog, "primijenjeno": prim}


def _prihvati(con, n, orig, pc, dorada, tko, kritike):
    """An accepted proposal by class -> (odluka, razlog, primijenjeno)."""
    nid = n["id"]
    k = klasa(pc)
    if k == "pravi_novac" or klasa(orig) == "pravi_novac":
        # never applied by the council, whatever a refinement turned it into
        return "vlasniku", (f"{REAL_PREFIX} ({_pc_txt(pc)}): pravi novac uključuje i mijenja samo vlasnik. "
                            f"Ocjene: {tko}. {kritike}"), None
    old = _zamijeni(con, n, pc) if dorada and not _isto(pc, orig) else None
    uz = " uz doradu" if old else ""
    if k == "auto":
        try:
            st, words = assistnotes.apply(con, nid, owner_note=store.kratko(f"vijeće: {tko}{uz}", 1000))
        except Exception as e:  # noqa: BLE001 - a refused value, a stale "from", a missing database: the owner decides
            if old:
                _vrati(con, nid, old)
            why = str(e) if isinstance(e, ValueError) else f"{type(e).__name__}: {e}"
            return "vlasniku", (f"vijeće je prihvatilo ({tko}{uz}), ali primjena nije prošla: {why}. Promjena: "
                                f"{_pc_txt(pc)}. {kritike}"), None
        if st == "primijenjeno" or isinstance((pc or {}).get("group_label"), dict):
            return "prihvaceno_primijenjeno", f"prihvaćeno ({tko}){uz}. {kritike}", words
        return "prihvaceno_za_izvedbu", f"prihvaćeno ({tko}){uz}, bot to ne zna primijeniti sam. {kritike}", None
    assistnotes.decide(con, nid, "prihvaćeno", owner_note=store.kratko(f"vijeće: {tko}{uz} (za izvedbu)", 1000))
    return "prihvaceno_za_izvedbu", f"prihvaćeno ({tko}){uz}, traži izmjenu koda. {kritike}", None
