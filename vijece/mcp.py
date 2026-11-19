"""Vijeće: Grok's side and the read tool (18.11., vlasnik: "kad Grok pošalje prijedlog, Claude i OpenAI moraju biti
kritični ... ako OpenAI ima prijedlog, Grok i Claude moraju biti kritični").

Grok has no API in the app: Grok Bot polls our MCP server (ui/mcpapi.py). So its reviews are asynchronous:
  get_council_queue      the notes that wait for Grok's review (the proposal, the other member's review when it is
                         in), and direction_request (the brief and what to answer) while a direction session is open
                         and Grok has not answered; read-only
  submit_council_review  Grok's review of one note, validated like the note tools (text cap, the verdict's three
                         words, refined_change one JSON object); a review of Grok's own proposal is refused; the
                         decision is taken at once when this was the missing review
  get_council            the whole picture for Grok, the critic and the operator: the queue with who is missing, the
                         last 20 decisions with the critiques, what waits for the coding session, the last direction
grok_tasks() adds the same work to get_grok_tasks (kinds council_review and council_direction), the queue Grok reads
first. Nothing here applies a change by itself: the decision is vijece/odluka.py's, with its real-money rule.
"""
import json
import time

from ui import assistnotes
from vijece import odluka, smjer, store

MAX_TASKS = 5
ALIAS = {"slažem": "slazem", "slazem se": "slazem", "slažem se": "slazem", "agree": "slazem", "accept": "slazem",
         "refine": "doradi", "against": "protiv", "reject": "protiv"}
VERDIKT_ARG = " | ".join(store.VERDIKTI)     # the three words as an argument hint
OFF = {"enabled": False, "note": "the council is switched off on the server; nothing waits"}
RULES = ("Three members: Grok, OpenAI, Claude. A proposal (a suggestion note) is reviewed by the two members who did "
         "not write it: slazem (it makes sense as it stands), doradi (agree with a concrete better version; "
         "refined_change = the change as one JSON object when it is a setting), protiv (with the reason). Both reviews "
         "without a protiv = accepted: an allow-listed setting that is not real money is applied at once (flags at "
         "most to shadow), anything that needs code is queued for the coding session; both protiv = rejected; a split "
         "or two different refinements = the owner decides. Real money (size_sol, max_open, tp_default, sl_default, "
         "copy.*, anything live / autotrade / kill) is never applied by the council, only by the owner. When Grok "
         "does not review within the wait (6 h), the API reviewer decides alone.")


def _item(n, oc, wait):
    others = {m: {"verdict": o["verdict"], "critique": o["critique"], "refined_change": o["refined_change"]}
              for m, o in oc.items() if m != "grok"}
    return {"note_id": n["id"], "ts": n["ts"], "title": n.get("title"), "proposer": n["predlagac"],
            "interpretation": n.get("interpretation"), "improvement": n.get("improvement"), "evidence": n.get("evidence"),
            "proposed_change": n.get("proposed_change"), "other_reviews": others or None,
            "review_by_ts": int(n["ts"] or 0) + wait}


def ceka_groka(con):
    """[(note, its reviews)] of the queue's notes that Grok reviews and has not reviewed yet."""
    notes = [n for n in store.red(con) if "grok" in store.ocjenjivaci(n["predlagac"])]
    oc = store.ocjene_za(con, [n["id"] for n in notes])
    return [(n, oc.get(n["id"]) or {}) for n in notes if "grok" not in (oc.get(n["id"]) or {})]


def queue(args=None, now=None, path=None):
    """get_council_queue (read-only)."""
    if not store.ukljuceno():
        return dict(OFF)
    now = int(now or time.time())
    con = store.ro(path)
    if con is None:
        return {"enabled": True, "now": now, "total": 0, "reviews": [], "direction_request": None, "last_direction": None}
    try:
        try:
            lim = max(1, min(50, int((args or {}).get("limit") or 20)))
        except (TypeError, ValueError):
            return {"error": "limit must be a whole number 1-50"}
        wait = store.grok_wait_s()
        rows = ceka_groka(con)
        return {"enabled": True, "now": now, "total": len(rows), "reviews": [_item(n, oc, wait) for n, oc in rows[:lim]],
                "direction_request": smjer.zahtjev_groku(con, now), "last_direction": smjer.zadnji(con),
                "answer_with": {"tool": "submit_council_review",
                                "arguments": {"note_id": "<note_id>", "verdict": VERDIKT_ARG,
                                              "critique": "<evidence for and against, what could go wrong, does it "
                                                          "raise NET profit and how, is it measurable and reversible>",
                                              "refined_change": "<only with doradi: the better change as one JSON "
                                                                "object in the shape of proposed_change>"}},
                "how": ("Be critical: say which numbers support the proposal, what could go wrong, whether it raises "
                        "net profit (trading PnL minus running cost) and how. slazem only when it makes sense as it "
                        "stands; doradi with a concrete better version; protiv with the reason. Your X knowledge "
                        "(who really moves these tokens, what the accounts post) is what the other two members lack. "
                        f"A note you do not review within {wait / 3600:g} h is decided without you."),
                "rules": RULES}
    finally:
        con.close()


def _verdict(x):
    v = str(x or "").strip().lower()
    v = ALIAS.get(v, v)
    if v not in store.VERDIKTI:
        raise ValueError(f"verdict must be one of {', '.join(store.VERDIKTI)}")
    return v


def submit_review(args, kid="local", now=None, path=None, log=None):
    """submit_council_review: store Grok's review of one note and decide the note when that was the missing voice."""
    log = log or print
    if not store.ukljuceno():
        return {"error": OFF["note"]}
    a = args if isinstance(args, dict) else {}
    now = int(now or time.time())
    con = store.connect(path)
    try:
        try:
            nid = int(a.get("note_id"))
        except (TypeError, ValueError):
            raise ValueError("note_id must be the id of a note from get_council_queue") from None
        verdict = _verdict(a.get("verdict"))
        critique = assistnotes._text(a.get("critique"), "critique", need=True)
        rc = assistnotes._json(a.get("refined_change"), "refined_change")
        rc = json.loads(rc) if rc else None
        if rc is not None and not isinstance(rc, dict):
            raise ValueError("refined_change must be one JSON object, e.g. {\"key\": \"runup_max\", \"from\": 0.15, \"to\": 0.1}")
        if rc and verdict != "doradi":
            raise ValueError("refined_change goes only with verdict doradi")
        n = store.note(con, nid)
        if n is None or n.get("kind") != "suggestion":
            raise ValueError(f"note {nid} is not a suggestion in the council's queue")
        if n["predlagac"] == "grok":
            raise ValueError("this is your own proposal: OpenAI and Claude review it, you cannot")
        if store.odluka(con, nid):
            raise ValueError(f"note {nid} is already decided (get_council shows the decision)")
        if not store.u_vijecu(n, store.start_ts(con, create=False)):
            raise ValueError(f"note {nid} does not wait for the council (the owner decided it, or it is older than the council)")
        store.upisi_ocjenu(con, nid, "grok", verdict, critique, rc or None, f"mcp:{kid}", 0.0, now)
        o = store.ocjene(con, nid)["grok"]
        store.reci_ocjenu(log, n, "grok", o)
        d = odluka.odluci(con, n, now, log)
        return {"note_id": nid, "verdict": verdict, "status": "stored",
                "decision": d["odluka"] if d else None,
                "message": (f"Stored. Decision: {store.ODLUKA_HR[d['odluka']]}." if d else
                            "Stored. The note waits for the other reviewer; the decision follows its review.")}
    except ValueError as e:
        return {"error": str(e)}
    finally:
        con.close()


def council(args=None, now=None, path=None):
    """get_council (read-only): the queue with who is missing, the last decisions, za_izvedbu, the direction."""
    if not store.ukljuceno():
        return dict(OFF)
    now = int(now or time.time())
    con = store.ro(path)
    if con is None:
        return {"enabled": True, "now": now, "queue": [], "decisions": [], "za_izvedbu": [], "last_direction": None}
    try:
        notes = store.red(con)
        oc = store.ocjene_za(con, [n["id"] for n in notes])
        wait = store.grok_wait_s()
        q = []
        for n in notes:
            got = oc.get(n["id"]) or {}
            revs = store.ocjenjivaci(n["predlagac"])
            q.append({"note_id": n["id"], "ts": n["ts"], "title": n.get("title"), "proposer": n["predlagac"],
                      "proposed_change": n.get("proposed_change"),
                      "reviews": {m: {"verdict": o["verdict"], "critique": o["critique"],
                                      "refined_change": o["refined_change"]} for m, o in got.items()},
                      "waits_for": [m for m in revs if m not in got],
                      "grok_deadline_ts": (int(n["ts"] or 0) + wait) if "grok" in revs and "grok" not in got else None})
        s = smjer.sjednica(con)
        return {"enabled": True, "now": now, "queue": q, "decisions": store.zadnje_odluke(con, 20),
                "za_izvedbu": store.za_izvedbu(con, 50), "last_direction": smjer.zadnji(con),
                "open_direction_session": ({"ts": s["ts"], "why": s.get("razlog"), "members": s.get("clanovi"),
                                            "grok_answered": smjer.grok_odgovorio(con, s)}
                                           if s and not s.get("zakljuceno") else None),
                "today": store.dnevno(con, now),
                "budget_usd_a_day": {m: store.strop(m) for m in store.API_CLANOVI}, "rules": RULES}
    finally:
        con.close()


def grok_tasks(con, now=None):
    """The council's work as get_grok_tasks rows (ui/kandidati.tasks): one council_review per waiting note (the
    oldest MAX_TASKS) and one council_direction while a session waits for Grok. con: trade.db (read-only is enough)."""
    if con is None or not store.ukljuceno():
        return []
    now = int(now or time.time())
    out = []   # negative ranks: ui/kandidati.tasks sorts by (priority, rank), so the council's work comes first
    req = smjer.zahtjev_groku(con, now)
    if req:
        out.append({"id": f"smjer:{req['session_ts']}", "kind": "council_direction", "priority": 1, "rank": -100,
                    "why": "the council's direction session is open and your answer is missing",
                    # 19.11. (vlasnik: "I want OpenAI and Grok bot to focus on working out the strategy for finding
                    # such wallets ... and which APIs to include"): the question is the wallet strategy
                    "instruction": ("Call get_council_queue: direction_request has the measured state (brief) and the "
                                    "question: the owner's first focus is WALLETS that buy before the pump / before "
                                    "influencer calls and sell into the pump. Work out how to FIND them (which data "
                                    "sources and APIs to add or drop besides Helius, and their cost; the definition "
                                    "of a pump and of 'bought before' / 'sold into'; excluding bots, market makers, "
                                    "team wallets and fresh one-off wallets; clustering by funder), how to PROVE it "
                                    "on history (point-in-time selection, out-of-sample copy test with 1-2 s delay "
                                    "and real cost, enough wallets and trades), how to COPY within a second (own "
                                    "executor vs an external copy tool: fees, custody, latency), the first three "
                                    "steps and how each raises net profit of real-money trades, measured within 14 "
                                    "days. Answer with at most 3 submit_suggestion calls whose title starts with "
                                    "\"Smjer: \"; add what you know from X (who finds such wallets, which tools "
                                    "they use). OpenAI and Claude then review each one."),
                    "answer_with": req["answer_with"]})
    wait = store.grok_wait_s()
    for k, (n, oc) in enumerate(ceka_groka(con)[:MAX_TASKS]):
        left = int(n["ts"] or 0) + wait - now
        out.append({"id": f"vijece:{n['id']}", "kind": "council_review", "priority": 1, "rank": -99 + k,
                    "note_id": n["id"], "title": n.get("title"), "proposer": n["predlagac"],
                    "why": (f"{store.IME[n['predlagac']]} proposed it; your critical review is missing"
                            + (f" ({max(0, left) // 60} min until it is decided without you)" if left < wait else "")),
                    "instruction": ("Call get_council_queue for the proposal's text, evidence and the other member's "
                                    "review. Be critical: which numbers support it, what could go wrong, does it raise "
                                    "NET profit (trading PnL minus running cost) and how, is it measurable and "
                                    "reversible. slazem only when it makes sense as it stands; doradi with a concrete "
                                    "better version; protiv with the reason."),
                    "answer_with": {"tool": "submit_council_review",
                                    "arguments": {"note_id": n["id"], "verdict": VERDIKT_ARG,
                                                  "critique": "<your critique>",
                                                  "refined_change": "<only with doradi: one JSON object>"}}})
    return out
