"""Kritičar (OpenAI) -> the assistant's notes (ui/assistnotes.py, trade.db assistant_notes), so its advice shows where
Grok's does and the owner accepts or rejects it on the Autopilot page like Grok's notes (nothing applies by itself).

Every critic note carries the key fingerprint KID (assistnotes.key_id("openai-kriticar")), so the pages tell the
critic's line ("Kritičar (OpenAI)") from Grok's, and Grok's own lists (latest_for, reviewed_positions) leave it out.

Open-trade verdicts map to submit_trade_review's verdicts (it allows dobar | loš | neutralan): drzi -> dobar when the
PnL is above 0 else neutralan, prodaj / prodaj_dio -> loš, stegni_sl / prosiri_sl -> neutralan. The critic's own
verdict, its reasons and levels are in the text and in evidence {"kriticar": "openai", "verdict": ...}.
"""
import json
import time

from ui import assistnotes

KEY_NAME = "openai-kriticar"
KID = assistnotes.key_id(KEY_NAME)
LABEL = "Kritičar (OpenAI)"
TITLE_PREFIX = "Kritičar: "
WORDS = {"drzi": "drži", "prodaj": "prodaj", "prodaj_dio": "prodaj dio", "stegni_sl": "stegni SL",
         "prosiri_sl": "proširi SL"}
NOTE_GAP_S = 3600   # the same verdict on the same position is written again only after this (the disk; critic_verdicts has all)


def review_verdict(verdict, pnl_pct):
    if verdict == "drzi":
        return "dobar" if (pnl_pct or 0) > 0 else "neutralan"
    if verdict in ("prodaj", "prodaj_dio"):
        return "loš"
    return "neutralan"


def _mc(x):
    if not x:
        return "–"
    x = float(x)
    return f"{x / 1e6:.2f}M $" if x >= 1e6 else f"{x / 1e3:.0f}k $"


def review_text(v):
    """The note's interpretation: "PRODAJ DIO · razlog 1 · razlog 2 · promijenilo bi: ... · SL 40k $ · TP 90k $"."""
    bits = [WORDS.get(v["verdict"], v["verdict"]).upper()] + list(v.get("razlozi") or [])
    if v.get("promijenilo_bi"):
        bits.append("promijenilo bi: " + v["promijenilo_bi"])
    if v.get("predlozeni_sl_mc"):
        bits.append("SL " + _mc(v["predlozeni_sl_mc"]))
    if v.get("predlozeni_tp_mc"):
        bits.append("TP " + _mc(v["predlozeni_tp_mc"]))
    return " · ".join(bits)[:assistnotes.TEXT_MAX]


def _last_note(con, pid):
    r = con.execute("SELECT ts, evidence FROM assistant_notes WHERE kind='trade_review' AND key_id=? AND position_id=? "
                    "ORDER BY id DESC LIMIT 1", (KID, int(pid))).fetchone()
    if not r:
        return None, None
    try:
        return r[0], (json.loads(r[1] or "{}") or {}).get("verdict")
    except ValueError:
        return r[0], None


def store_review(con, pos, v, model, call_id, now=None, log=print):
    """One trade_review note for a position (or None when the same verdict was written within NOTE_GAP_S, or the
    notes' hourly limit refused it). Returns the note id."""
    now = int(now or time.time())
    assistnotes.ensure(con)
    ts, last = _last_note(con, pos["pid"])
    if last == v["verdict"] and ts and now - ts < NOTE_GAP_S:
        return None
    ev = {"kriticar": "openai", "verdict": v["verdict"], "model": model, "call_id": call_id,
          "mc": round(pos.get("mc_now") or 0, 2), "pnl_pct": pos.get("pnl_pct"),
          "sl_mc": v.get("predlozeni_sl_mc"), "tp_mc": v.get("predlozeni_tp_mc")}
    try:
        d = assistnotes.submit_trade_review(con, KID, pos["pid"], review_verdict(v["verdict"], pos.get("pnl_pct")),
                                            v["confidence"], review_text(v), None, ev)
        return d["id"]
    except ValueError as e:   # the notes' hourly limit per key, a position gone meanwhile
        log(f"kritičar: bilješka za poziciju {pos['pid']} nije zapisana ({e})", flush=True)
        return None


def store_finding(con, f, model):
    title = (TITLE_PREFIX + f["naslov"])[:assistnotes.TITLE_MAX]
    interp = f"[{f['ozbiljnost']}] {f['dokaz']}"
    impr = f"{f['prijedlog']}\nKako provjeriti: {f['kako_provjeriti']}"
    d = assistnotes.submit_suggestion(con, KID, title, interp[:assistnotes.TEXT_MAX], impr[:assistnotes.TEXT_MAX],
                                      {"kriticar": "openai", "ozbiljnost": f["ozbiljnost"], "model": model}, None)
    return d["id"]


def store_summary(con, title, text, evidence):
    d = assistnotes.submit_daily_summary(con, KID, title[:assistnotes.TITLE_MAX], text[:assistnotes.TEXT_MAX], evidence)
    return d["id"]


def rejected_titles(con, days=60, now=None, limit=40):
    """Titles of the critic's suggestions the owner rejected (without the prefix), newest first."""
    now = int(now or time.time())
    try:
        rows = con.execute("SELECT title FROM assistant_notes WHERE kind='suggestion' AND key_id=? AND status='odbijeno' "
                           "AND ts >= ? ORDER BY id DESC LIMIT ?", (KID, now - days * 86400, limit)).fetchall()
    except Exception:  # noqa: BLE001 - no notes table yet
        return []
    return [str(t or "").replace(TITLE_PREFIX, "", 1) for (t,) in rows]


def suggestion_status(con, since):
    """{status: n} of the critic's suggestions since `since` (what the owner did with them)."""
    out = {}
    for st, n in con.execute("SELECT status, COUNT(*) FROM assistant_notes WHERE kind='suggestion' AND key_id=? "
                             "AND ts >= ? GROUP BY status", (KID, int(since))):
        out[st] = n
    return out


def latest_summary(con):
    """The critic's newest daily summary (dict of assistnotes COLS) or None."""
    try:
        assistnotes.ensure(con)
        r = con.execute(f"SELECT {', '.join(assistnotes.COLS)} FROM assistant_notes WHERE kind='daily_summary' AND "
                        "key_id=? ORDER BY id DESC LIMIT 1", (KID,)).fetchone()
    except Exception:  # noqa: BLE001
        return None
    return assistnotes._row(r) if r else None


def latest_findings(con, since, limit=5):
    try:
        rows = con.execute(f"SELECT {', '.join(assistnotes.COLS)} FROM assistant_notes WHERE kind='suggestion' AND "
                           "key_id=? AND ts >= ? ORDER BY id LIMIT ?", (KID, int(since), limit)).fetchall()
    except Exception:  # noqa: BLE001
        return []
    return [assistnotes._row(r) for r in rows]
