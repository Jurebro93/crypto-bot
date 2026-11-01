"""AI detective + hypothesis queue: ideas are tested automatically on the shadow book, never applied on trust.

Once a day Claude Opus 5.5 reads the week's biggest shadow-book wins, worst losses and missed winners (with the
signals they had at the decision moment), the open hypotheses and Nicholas's ideas (`run_learn.py ideja "..."`),
and proposes up to 5 hypotheses as machine-checkable rules: "signal op value" conditions (AND).

Each hypothesis is pre-registered: only decision points that arrive AFTER it was written count. It passes when the
points it matches earn more than the rest (mean return capped at +300%, also without the top 1%) and the 90%
bootstrap range of the difference is above zero, on at least `min_n` matched points. It fails when the range is
below zero or it has not passed in `max_days`. A passed hypothesis becomes a model signal h_<id> (learn/gbm.context),
so the model can use it, and the champion trial still decides whether the model gets better with it.

ai.db tables hipoteze + ideje. Cost metered (usage.db anthropic/detektiv) and shown next to the passed count.
"""
import json
import os
import sys
import time

from learn import postai

MODEL = os.environ.get("DETEKTIV_MODEL", "claude-opus-5-5")
PRICE = (4.0, 20.0)  # $ per million tokens in / out, Claude Opus 5.5
DEFAULT = {"enabled": True, "max_new": 5, "min_n": 80, "max_days": 21, "points": ["mc100k", "kandidat"], "days": 7}
SCHEMA = """
CREATE TABLE IF NOT EXISTS hipoteze (
    id INTEGER PRIMARY KEY AUTOINCREMENT, created INTEGER, naslov TEXT, objasnjenje TEXT, uvjeti TEXT, tocka TEXT,
    izvor TEXT, status TEXT DEFAULT 'testira se', n INTEGER, eval TEXT, decided_ts INTEGER);
CREATE TABLE IF NOT EXISTS ideje (
    id INTEGER PRIMARY KEY AUTOINCREMENT, created INTEGER, tekst TEXT, autor TEXT, status TEXT DEFAULT 'čeka',
    hipoteza INTEGER);
CREATE TABLE IF NOT EXISTS detektiv_runs (ts INTEGER PRIMARY KEY, model TEXT, cost_usd REAL, n_new INTEGER, note TEXT);
"""
OPS = (">=", "<=", "==")
OUT_SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["hipoteze"],
    "properties": {"hipoteze": {"type": "array", "items": {
        "type": "object", "additionalProperties": False,
        "required": ["naslov", "objasnjenje", "uvjeti", "tocka", "iz_ideje"],
        "properties": {
            "naslov": {"type": "string"}, "objasnjenje": {"type": "string"},
            "tocka": {"type": "string", "enum": ["sve", "mc100k", "kandidat", "prvi_signal", "mc1m"]},
            "iz_ideje": {"type": "integer"},
            "uvjeti": {"type": "array", "items": {
                "type": "object", "additionalProperties": False, "required": ["signal", "op", "vrijednost"],
                "properties": {"signal": {"type": "string"}, "op": {"type": "string", "enum": list(OPS)},
                               "vrijednost": {"type": "string"}}}}}}}}}
SYSTEM = (
    "Ti si analitičar alata za demo trgovanje Solana meme tokenima (istraživanje, ne savjet). Dobivaš virtualne "
    "trgovine iz sjenovite knjige: za svaku točku odluke signale (0..1, osim log_mcap/log_liq/hype_ocjena) u tom "
    "trenutku i ostvarivu zaradu nakon 24 h. Predloži najviše 5 hipoteza koje bi mogle razlikovati dobitke od gubitaka "
    "i koje još nisu na popisu. Svaka je skup uvjeta 'signal op vrijednost' (svi moraju vrijediti). Koristi SAMO "
    "signale s popisa. Za kategorije (sess: asia/eu/us, klasa, point) op je '==' a vrijednost tekst. Ako postoje "
    "ideje korisnika, prvo njih pretvori u hipoteze i upiši njihov id u iz_ideje (inače 0). Piši na hrvatskom, "
    "kratko i jasno; objašnjenje jednom rečenicom kaže zašto bi to moglo vrijediti. Nemoj izmišljati brojeve.")


def config():
    from learn import outcomes
    return {**DEFAULT, **(outcomes.config().get("detektiv") or {})}


def connect(path=None):
    con = postai.connect(path)
    con.executescript(SCHEMA)
    return con


def _ro(path=None):
    return postai._ro(path or postai.DB)


# ---------------------------------------------------------------- matching

def _val(x, cond):
    s = cond["signal"]
    if cond["op"] == "==" and s in ("sess", "klasa", "point"):
        return x.get(f"{s}={cond['vrijednost']}", 0.0), 1.0
    try:
        return x.get(s), float(cond["vrijednost"])
    except (TypeError, ValueError):
        return None, None


def matches(h, r, x=None):
    """Does decision point r (shadow row) meet every condition of hypothesis h?"""
    from learn import gbm
    if h.get("tocka") not in (None, "", "sve") and r.get("point") != h["tocka"]:
        return False
    x = x if x is not None else gbm.context(r, hyps=False)
    for c in h["uvjeti"]:
        v, t = _val(x, c)
        if v is None or t is None:
            return False
        if c["op"] == ">=" and not v >= t or c["op"] == "<=" and not v <= t or c["op"] == "==" and not v == t:
            return False
    return True


_PASSED = {"ts": 0, "list": []}


def passed(path=None, now=None):
    """Hypotheses that passed (cached 10 min): [{"id", "uvjeti", "tocka"}]."""
    now = now or time.time()
    if now - _PASSED["ts"] > 600:
        con = _ro(path)
        lst = []
        if con is not None:
            try:
                lst = [{"id": r[0], "uvjeti": json.loads(r[1]), "tocka": r[2]} for r in
                       con.execute("SELECT id, uvjeti, tocka FROM hipoteze WHERE status='prošla'")]
            except Exception:  # noqa: BLE001
                lst = []
            finally:
                con.close()
        _PASSED.update(ts=now, list=lst)
    return _PASSED["list"]


# ---------------------------------------------------------------- evaluation

def evaluate(con, now=None, cfg=None, shadow_path=None):
    """Judge every open hypothesis on the points labelled after it was written. Returns [(id, status)]."""
    from learn import champion, shadow
    cfg = cfg or config()
    now = now or time.time()
    out = []
    for hid, created, uvjeti, tocka in con.execute(
            "SELECT id, created, uvjeti, tocka FROM hipoteze WHERE status='testira se'").fetchall():
        h = {"uvjeti": json.loads(uvjeti), "tocka": tocka}
        rs = [r for r in shadow.rows(shadow_path, since=created) if r["point"] in cfg["points"] or tocka not in ("sve", None, "")]
        flags = [matches(h, r) for r in rs]
        m = [r for r, f in zip(rs, flags) if f]
        rest = [r for r, f in zip(rs, flags) if not f]
        sm, sr = shadow.stats(m), shadow.stats(rest)
        d = champion.boot_diff([r["ret"] for r in m], [r["ret"] for r in rest]) if m and rest else None
        ev = {"n": len(m), "n_rest": len(rest), "match": sm, "rest": sr, "razlika": d}
        status = "testira se"
        age = (now - created) / 86400
        if len(m) >= cfg["min_n"] and d:
            if d[0] > 0 and sm["mean_trim"] > sr.get("mean_trim", 0):
                status = "prošla"
            elif d[1] < 0:
                status = "pala"
        if status == "testira se" and age > cfg["max_days"]:
            status = "pala" if len(m) >= cfg["min_n"] else "premalo podataka"
        con.execute("UPDATE hipoteze SET status=?, n=?, eval=?, decided_ts=? WHERE id=?",
                    (status, len(m), json.dumps(ev), int(now) if status != "testira se" else None, hid))
        out.append((hid, status))
    con.commit()
    _PASSED["ts"] = 0
    return out


# ---------------------------------------------------------------- proposing

def _brief(r, top=14):
    f = sorted(((k, round(v, 2)) for k, v in (r["features"] or {}).items() if isinstance(v, (int, float)) and v),
               key=lambda kv: -abs(kv[1]))[:top]
    return {"tocka": r["point"], "klasa": r["klasa"], "sess": r["sess"], "mcap": round(r["mcap"] or 0),
            "zarada": round(r["ret"], 3), "kupljeno": r["kupljeno"], "signali": dict(f)}


def brief(con, now, cfg, shadow_path=None):
    from learn import shadow
    rs = [r for p in cfg["points"] for r in shadow.rows(shadow_path, point=p, since=now - cfg["days"] * 86400)]
    if len(rs) < 50:
        return None
    srt = sorted(rs, key=lambda r: -r["ret"])
    missed = [r for r in srt if r["point"] == "kandidat" and not r["kupljeno"] and r["ret"] >= 0.5][:15]
    sigs = sorted({k for r in rs for k in r["features"]} | {"log_mcap", "log_liq", "hype_ocjena", "sess", "klasa", "point"})
    hyps = [{"naslov": r[0], "uvjeti": json.loads(r[1]), "status": r[2]} for r in
            con.execute("SELECT naslov, uvjeti, status FROM hipoteze ORDER BY id DESC LIMIT 40")]
    ideas = [{"id": r[0], "tekst": r[1]} for r in con.execute("SELECT id, tekst FROM ideje WHERE status='čeka' LIMIT 10")]
    return {"razdoblje_dana": cfg["days"], "n_tocaka": len(rs), "knjiga": shadow.stats(rs),
            "najbolji": [_brief(r) for r in srt[:15]], "najgori": [_brief(r) for r in srt[-15:]],
            "propusteni": [_brief(r) for r in missed], "signali": sigs, "postojece_hipoteze": hyps, "ideje": ideas}


def propose(path=None, now=None, shadow_path=None, client=None):
    """Daily: evaluate open hypotheses, then ask Claude for new ones. Returns a short note."""
    cfg = config()
    now = now or time.time()
    con = connect(path)
    try:
        ev = evaluate(con, now, cfg, shadow_path)
        note = f"ocijenjeno {len(ev)}" + (f" ({', '.join(f'#{i} {s}' for i, s in ev if s != 'testira se')})" if ev else "")
        if not cfg["enabled"]:
            return note + "; prijedlozi isključeni"
        if client is None:
            if not os.environ.get("ANTHROPIC_API_KEY"):
                return note + "; nema ANTHROPIC_API_KEY"
            import anthropic
            client = anthropic.Anthropic(timeout=600, max_retries=2)
        b = brief(con, now, cfg, shadow_path)
        if not b:
            return note + "; premalo točaka za prijedloge"
        kw = dict(model=MODEL, max_tokens=16000, system=SYSTEM,
                  messages=[{"role": "user", "content": json.dumps(b, ensure_ascii=False)}],
                  output_config={"effort": "medium", "format": {"type": "json_schema", "schema": OUT_SCHEMA}})
        try:
            resp = client.beta.messages.create(betas=["server-side-fallback-2026-07-01"], fallbacks="default", **kw)
        except Exception as e:  # noqa: BLE001 - fallback parameter refused: plain call
            if type(e).__name__ != "BadRequestError":
                raise
            resp = client.messages.create(**kw)
        u = resp.usage
        usd = ((u.input_tokens or 0) * PRICE[0] + (u.output_tokens or 0) * PRICE[1]) / 1e6
        try:
            from usage import meter
            meter.record("anthropic", "detektiv", amount=usd)
            meter.flush()
        except Exception:  # noqa: BLE001
            pass
        n_new = 0
        if resp.stop_reason != "refusal":
            out = json.loads("".join(blk.text for blk in resp.content if blk.type == "text"))
            known = set(b["signali"])
            for h in out.get("hipoteze", [])[:cfg["max_new"]]:
                conds = [c for c in h.get("uvjeti") or [] if c.get("signal") in known and c.get("op") in OPS]
                if not conds:
                    continue
                cur = con.execute("INSERT INTO hipoteze (created, naslov, objasnjenje, uvjeti, tocka, izvor) VALUES (?,?,?,?,?,?)",
                                  (int(now), h["naslov"][:120], h["objasnjenje"][:400], json.dumps(conds), h.get("tocka") or "sve",
                                   "ideja" if h.get("iz_ideje") else "AI"))
                if h.get("iz_ideje"):
                    con.execute("UPDATE ideje SET status='u testu', hipoteza=? WHERE id=?", (cur.lastrowid, h["iz_ideje"]))
                n_new += 1
        con.execute("INSERT OR REPLACE INTO detektiv_runs VALUES (?,?,?,?,?)",
                    (int(now), getattr(resp, "model", MODEL), round(usd, 4), n_new, note))
        con.commit()
        return note + f"; novih hipoteza {n_new} (${usd:.2f})"
    finally:
        con.close()


def add_idea(text, autor="Nicholas", path=None, now=None):
    con = connect(path)
    try:
        con.execute("INSERT INTO ideje (created, tekst, autor) VALUES (?,?,?)", (int(now or time.time()), text, autor))
        con.commit()
    finally:
        con.close()


def overview(path=None, days=30, now=None):
    """For the Učenje page: hypotheses by status, the newest ones, the detective's spend."""
    now = now or time.time()
    con = _ro(path)
    if con is None:
        return None
    try:
        by = dict(con.execute("SELECT status, COUNT(*) FROM hipoteze GROUP BY status").fetchall())
        rows = [dict(zip(("id", "created", "naslov", "objasnjenje", "uvjeti", "tocka", "izvor", "status", "n", "eval"), r))
                for r in con.execute("SELECT id, created, naslov, objasnjenje, uvjeti, tocka, izvor, status, n, eval "
                                     "FROM hipoteze ORDER BY (status='prošla') DESC, id DESC LIMIT 30")]
        usd = con.execute("SELECT COALESCE(SUM(cost_usd), 0) FROM detektiv_runs WHERE ts >= ?", (now - days * 86400,)).fetchone()[0]
        ideas = con.execute("SELECT COUNT(*) FROM ideje WHERE status='čeka'").fetchone()[0]
        return {"by": by, "rows": rows, "usd": round(usd, 2), "ideje": ideas}
    except Exception:  # noqa: BLE001
        return None
    finally:
        con.close()


if __name__ == "__main__":
    print(propose())
    sys.exit(0)
