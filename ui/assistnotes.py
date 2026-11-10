"""Notes of an outside AI assistant (through the MCP endpoint, ui/mcpapi.py) for the owner: trade reviews, opinions on
a signal, improvement suggestions and a daily summary (10.11., Jure: "asistent piše analizu svakog trejda i prijedloge;
ja ih vidim na Autopilotu i ručno prihvaćam ili odbijam; asistent nikad ne mijenja trgovanje sam").

Storage: trade.db table assistant_notes. The MCP write tools only INSERT here (validated, text capped at TEXT_MAX,
at most RATE_PER_HOUR writes an hour per key). Nothing reads a note for trading. Only the owner's "Primijeni" on the
Autopilot page applies a note's proposed_change, and only for the keys in APPLY (each with its own check); the old and
the new value go to the log (settings "applied_log"). Anything else is marked 'prihvaćeno' for a manual change.
"""
import hashlib
import json
import time

from trade import settings

KINDS = ("trade_review", "signal_opinion", "suggestion", "daily_summary")
VERDICTS = ("dobar", "loš", "neutralan", "preskoči", "kupi")
STATUSES = ("novo", "prihvaćeno", "odbijeno", "primijenjeno")
TEXT_MAX = 4000
TITLE_MAX = 200
JSON_MAX = 20_000
RATE_PER_HOUR = 60

SCHEMA = f"""CREATE TABLE IF NOT EXISTS assistant_notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT, ts INTEGER NOT NULL,
    kind TEXT NOT NULL CHECK(kind IN ({",".join(repr(k) for k in KINDS)})),
    position_id INTEGER, token TEXT, symbol TEXT,
    verdict TEXT CHECK(verdict IS NULL OR verdict IN ({",".join(repr(v) for v in VERDICTS)})),
    confidence REAL CHECK(confidence IS NULL OR (confidence >= 0 AND confidence <= 1)),
    title TEXT, interpretation TEXT, improvement TEXT, evidence TEXT, proposed_change TEXT,
    status TEXT NOT NULL DEFAULT 'novo' CHECK(status IN ({",".join(repr(s) for s in STATUSES)})),
    decided_ts INTEGER, owner_note TEXT, key_id TEXT)"""
INDEXES = ("CREATE INDEX IF NOT EXISTS assistant_notes_kind ON assistant_notes (kind, status, id)",
           "CREATE INDEX IF NOT EXISTS assistant_notes_pos ON assistant_notes (position_id)",
           "CREATE INDEX IF NOT EXISTS assistant_notes_tok ON assistant_notes (token, id)",
           "CREATE INDEX IF NOT EXISTS assistant_notes_key ON assistant_notes (key_id, ts)")


def ensure(con):
    """Create the table (or add a column a first version lacked); never drops or rewrites rows."""
    con.execute(SCHEMA)
    have = {r[1] for r in con.execute("PRAGMA table_info(assistant_notes)")}
    if "key_id" not in have:
        con.execute("ALTER TABLE assistant_notes ADD COLUMN key_id TEXT")
    for sql in INDEXES:
        con.execute(sql)
    con.commit()


def key_id(key):
    """A short fingerprint of the client's key (the key itself is never stored)."""
    return hashlib.sha256((key or "").encode()).hexdigest()[:16] if key else "local"


# ---------- validation ---------------------------------------------------------------------------------------------

def _text(x, name, need=False, cap=TEXT_MAX):
    s = "" if x is None else str(x).strip()
    if need and not s:
        raise ValueError(f"{name} is required")
    if len(s) > cap:
        raise ValueError(f"{name} is longer than {cap} characters")
    return s or None


def _json(x, name):
    if x is None or x == "":
        return None
    if isinstance(x, str):
        try:
            x = json.loads(x)
        except ValueError:
            raise ValueError(f"{name} must be a JSON object or list")
    if not isinstance(x, (dict, list)):
        raise ValueError(f"{name} must be a JSON object or list")
    s = json.dumps(x, ensure_ascii=False)
    if len(s) > JSON_MAX:
        raise ValueError(f"{name} is larger than {JSON_MAX} characters")
    return s


def _conf(x):
    if x is None or x == "":
        return None
    try:
        c = float(x)
    except (TypeError, ValueError):
        raise ValueError("confidence must be a number between 0 and 1")
    if not 0 <= c <= 1:
        raise ValueError("confidence must be between 0 and 1")
    return round(c, 3)


def _verdict(x, allowed=VERDICTS):
    v = str(x or "").strip().lower()
    alias = {"good": "dobar", "bad": "loš", "los": "loš", "neutral": "neutralan", "skip": "preskoči",
             "preskoci": "preskoči", "buy": "kupi"}
    v = alias.get(v, v)
    if v not in allowed:
        raise ValueError(f"verdict must be one of {', '.join(allowed)}")
    return v


def _rate(con, kid, now):
    n = con.execute("SELECT COUNT(*) FROM assistant_notes WHERE key_id=? AND ts>?", (kid, now - 3600)).fetchone()[0]
    if n >= RATE_PER_HOUR:
        raise ValueError(f"rate limit: at most {RATE_PER_HOUR} notes an hour per key")


def _insert(con, kid, **row):
    now = int(time.time())
    ensure(con)
    _rate(con, kid, now)
    cols = ["ts", "key_id"] + list(row)
    cur = con.execute(f"INSERT INTO assistant_notes ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
                      [now, kid] + list(row.values()))
    con.commit()
    return cur.lastrowid


def _done(nid, kind):
    print(f"mcp: asistent je zapisao {kind} #{nid} (čeka vlasnika)", flush=True)
    return {"id": nid, "kind": kind, "status": "novo",
            "message": "Stored for the owner on the MemeSonar Autopilot page; nothing in live trading changed."}


# ---------- the four write tools (insert only) ---------------------------------------------------------------------

def submit_trade_review(con, kid, position_id, verdict, confidence=None, interpretation=None, improvement=None,
                        evidence=None):
    try:
        pid = int(position_id)
    except (TypeError, ValueError):
        raise ValueError("position_id must be the id of an Autopilot position (get_autopilot_trades)")
    row = con.execute("SELECT token, symbol FROM positions WHERE id=?", (pid,)).fetchone()
    if row is None:
        raise ValueError(f"position {pid} does not exist")
    nid = _insert(con, kid, kind="trade_review", position_id=pid, token=row[0], symbol=row[1],
                  verdict=_verdict(verdict, ("dobar", "loš", "neutralan")), confidence=_conf(confidence),
                  interpretation=_text(interpretation, "interpretation", need=True),
                  improvement=_text(improvement, "improvement"), evidence=_json(evidence, "evidence"))
    return _done(nid, "trade_review")


def submit_signal_opinion(con, kid, token, verdict, confidence=None, interpretation=None, evidence=None):
    tok = _text(token, "token", need=True, cap=64)
    if not 32 <= len(tok) <= 64:
        raise ValueError("token must be a Solana token address")
    pos = con.execute("SELECT id, symbol FROM positions WHERE token=? ORDER BY id DESC LIMIT 1", (tok,)).fetchone()
    nid = _insert(con, kid, kind="signal_opinion", position_id=pos[0] if pos else None, token=tok,
                  symbol=pos[1] if pos else None, verdict=_verdict(verdict), confidence=_conf(confidence),
                  interpretation=_text(interpretation, "interpretation", need=True), evidence=_json(evidence, "evidence"))
    return _done(nid, "signal_opinion")


def submit_suggestion(con, kid, title, interpretation=None, improvement=None, evidence=None, proposed_change=None):
    pc = _json(proposed_change, "proposed_change")
    if pc and not isinstance(json.loads(pc), dict):
        raise ValueError("proposed_change must be one JSON object, e.g. {\"key\": \"sl_default\", \"from\": 60, \"to\": 40}")
    nid = _insert(con, kid, kind="suggestion", title=_text(title, "title", need=True, cap=TITLE_MAX),
                  interpretation=_text(interpretation, "interpretation", need=True),
                  improvement=_text(improvement, "improvement"), evidence=_json(evidence, "evidence"), proposed_change=pc)
    return _done(nid, "suggestion")


def submit_daily_summary(con, kid, title, interpretation=None, evidence=None):
    nid = _insert(con, kid, kind="daily_summary", title=_text(title, "title", need=True, cap=TITLE_MAX),
                  interpretation=_text(interpretation, "interpretation", need=True), evidence=_json(evidence, "evidence"))
    return _done(nid, "daily_summary")


# ---------- reading --------------------------------------------------------------------------------------------------

COLS = ("id", "ts", "kind", "position_id", "token", "symbol", "verdict", "confidence", "title", "interpretation",
        "improvement", "evidence", "proposed_change", "status", "decided_ts", "owner_note")


def _row(r):
    d = dict(zip(COLS, r))
    for k in ("evidence", "proposed_change"):
        try:
            d[k] = json.loads(d[k]) if d[k] else None
        except ValueError:
            pass
    return d


def notes(con, status=None, kind=None, limit=100, offset=0):
    """(rows newest first, total)."""
    ensure(con)
    where, args = [], []
    if status:
        where.append("status=?")
        args.append(status)
    if kind:
        where.append("kind=?")
        args.append(kind)
    w = (" WHERE " + " AND ".join(where)) if where else ""
    total = con.execute(f"SELECT COUNT(*) FROM assistant_notes{w}", args).fetchone()[0]
    rows = [_row(r) for r in con.execute(f"SELECT {', '.join(COLS)} FROM assistant_notes{w} ORDER BY id DESC "
                                         "LIMIT ? OFFSET ?", args + [limit, offset])]
    return rows, total


def latest_for(con, position_ids=(), tokens=()):
    """{("p", id) | ("t", token): newest trade_review / signal_opinion} for position cards."""
    ensure(con)
    out = {}
    ids = [int(i) for i in position_ids if i]
    toks = [t for t in tokens if t]
    if ids:
        for r in con.execute(f"SELECT {', '.join(COLS)} FROM assistant_notes WHERE kind IN ('trade_review','signal_opinion') "
                             f"AND position_id IN ({','.join('?' * len(ids))}) ORDER BY id", ids):
            d = _row(r)
            out[("p", d["position_id"])] = d
    if toks:
        for r in con.execute(f"SELECT {', '.join(COLS)} FROM assistant_notes WHERE kind IN ('trade_review','signal_opinion') "
                             f"AND token IN ({','.join('?' * len(toks))}) ORDER BY id", toks):
            d = _row(r)
            out[("t", d["token"])] = d
    return out


def latest_summary(con):
    ensure(con)
    r = con.execute(f"SELECT {', '.join(COLS)} FROM assistant_notes WHERE kind='daily_summary' ORDER BY id DESC LIMIT 1").fetchone()
    return _row(r) if r else None


def reviewed_positions(con):
    ensure(con)
    return {r[0] for r in con.execute("SELECT DISTINCT position_id FROM assistant_notes WHERE kind='trade_review' "
                                      "AND position_id IS NOT NULL")}


# ---------- the owner's decision -----------------------------------------------------------------------------------

def _set_settings(con, key, value):
    settings.put(con, key, value, settings.owner())


def _apply_tp(con, v):
    v = int(float(v))
    if not 1 <= v <= 1000:
        raise ValueError("tp_default mora biti 1-1000 %")
    _set_settings(con, "tp_default", v)
    return v


def _apply_sl(con, v):
    v = abs(int(float(v)))
    if v not in settings.SL_CHOICES:
        raise ValueError(f"sl_default mora biti jedan od {', '.join(map(str, settings.SL_CHOICES))}")
    _set_settings(con, "sl_default", v)
    return v


def _apply_limit(key):
    def f(con, v):
        lab, typ, lo, hi = settings.LIMITS[key]
        v = typ(float(v))
        if not lo <= v <= hi:
            raise ValueError(f"{key} mora biti između {lo:g} i {hi:g}")
        _set_settings(con, key, v)
        return v
    return f


def _apply_auto_skip(con, v):
    pairs = v if isinstance(v, list) else [v]
    clean = []
    for p in pairs:
        if not (isinstance(p, (list, tuple)) and len(p) == 2 and p[0] in ("kol", "wallet", "ekipa") and str(p[1]).strip()):
            raise ValueError('auto_skip: popis parova ["kol"|"wallet"|"ekipa", "meta"]')
        clean.append([p[0], str(p[1]).strip()])
    cur = [list(x) for x in settings.raw(con).get("auto_skip") or []]
    new = (cur + [c for c in clean if c not in cur])[-200:]
    _set_settings(con, "auto_skip", new)
    return new


COPY_CFG = {   # league/copy.CFG values the owner may move into settings ("copy_cfg"), with their allowed range
    "max_delay_min": (1, 60), "min_liq": (1000, 1_000_000), "max_mcap": (100_000, 1e9),
    "min_mcap": (30_000, 10_000_000),   # CLAUDE.md: never under 30k
    "min_liq_mcap": (0.0, 0.5), "crew_window_min": (1, 240), "max_per_day": (1, 200)}


def _apply_copy(key):
    def f(con, v):
        lo, hi = COPY_CFG[key]
        v = float(v)
        if not lo <= v <= hi:
            raise ValueError(f"copy.{key} mora biti između {lo:g} i {hi:g}")
        cur = dict(settings.raw(con).get("copy_cfg") or {})
        cur[key] = v
        _set_settings(con, "copy_cfg", cur)
        return v
    return f


def _apply_caller(con, pc):
    h = str(pc.get("caller") or "").strip().lstrip("@")
    plat = str(pc.get("platform") or "x").lower()
    if plat == "telegram" and not h.startswith("tg:"):
        h = "tg:" + h
    w = float(pc.get("weight"))
    if not h or not 0 <= w <= 2:
        raise ValueError("težina callera mora biti 0-2")
    cur = dict(settings.raw(con).get("caller_weights") or {})
    old = cur.get(h)
    cur[h] = round(w, 3)
    _set_settings(con, "caller_weights", cur)
    return h, old, cur[h]


def _to_shadow(con, flag):
    """10.11. (Jure: "svaku iza zastavice, prvo shadow"): a rule an applied suggestion sets is switched to shadow when
    it is off; a flag already in shadow, paper or live stays where the owner put it. Never live from here."""
    if settings.flag(flag, con=con) == "off":
        settings.set_flag(con, flag, "shadow", "asistent (Primijeni)")
        return f"; zastavica {flag}: sjena"
    return ""


def _apply_dca_cap(con, v):
    v = round(float(v), 4)
    if not 0.01 <= v <= 5:
        raise ValueError("dca_token_cap mora biti 0,01-5 SOL")
    _set_settings(con, "dca_token_cap", v)
    _to_shadow(con, "dca_cap")
    return v


def _apply_require_signal(con, v):
    on = v if isinstance(v, bool) else str(v).strip().lower() in ("1", "true", "da", "on", "yes")
    if on:
        _to_shadow(con, "require_signal")
    elif settings.flag("require_signal", con=con) != "off":
        settings.set_flag(con, "require_signal", "off", "asistent (Primijeni)")
    return on


def _apply_runup(con, v):
    v = float(v)
    if v > 2:   # "15" is meant as 15 %
        v = v / 100
    if not 0.02 <= v <= 2.0:
        raise ValueError("runup_max mora biti 0,02-2 (2 % do 200 % iznad prvog poziva)")
    _set_settings(con, "runup_max", round(v, 4))
    _to_shadow(con, "runup_default")
    return round(v, 4)


APPLY = {"tp_default": _apply_tp, "sl_default": _apply_sl, "size_sol": _apply_limit("size_sol"),
         "max_open": _apply_limit("max_open"), "auto_skip": _apply_auto_skip,
         **{f"copy.{k}": _apply_copy(k) for k in COPY_CFG},
         # 10.11. (Jure): rules behind a flag; applying one sets its value and moves its flag from off to shadow
         "dca_token_cap": _apply_dca_cap, "require_signal": _apply_require_signal, "runup_max": _apply_runup}
FLAG_OF = {"dca_token_cap": "dca_cap", "require_signal": "require_signal", "runup_max": "runup_default"}


def _current(con, key):
    raw = settings.raw(con)
    if key.startswith("copy."):
        from league import copy
        return (raw.get("copy_cfg") or {}).get(key[5:], copy.CFG.get(key[5:]))
    if key in ("tp_default", "sl_default"):
        return settings.merged({"size_sol": 0.1, "max_sol_per_trade": 0.1}, con).get(key)
    if key == "dca_token_cap":
        return raw.get(key, settings.DCA_TOKEN_CAP)
    if key == "require_signal":
        return settings.flag("require_signal", con=con) != "off"
    if key == "runup_max":
        from league import copy
        return raw.get(key, copy.RUNUP_DEFAULT)
    return raw.get(key, None)


def effective(con):
    """10.11. (Jure: Grok mora moći provjeriti): every key "Primijeni" can change with its value in force now, the
    flag it sits behind (and that flag's mode), and the caller weights."""
    out = {}
    for key in APPLY:
        try:
            v = _current(con, key)
        except Exception:  # noqa: BLE001
            v = None
        row = {"value": v}
        if key in FLAG_OF:
            row.update(flag=FLAG_OF[key], flag_mode=settings.flag(FLAG_OF[key], con=con))
        out[key] = row
    out["caller_weights"] = {"value": settings.raw(con).get("caller_weights") or {}, "flag": "caller_weights",
                             "flag_mode": settings.flag("caller_weights", con=con)}
    return out


def applied(con, limit=50):
    """The applied suggestions, newest first: [{ts, note_id, key, old, new}] (settings applied_log)."""
    return list(settings.raw(con).get("applied_log") or [])[:limit]


def decide(con, nid, status, owner_note=""):
    """Mark a note prihvaćeno / odbijeno (no other effect)."""
    ensure(con)
    if status not in ("prihvaćeno", "odbijeno"):
        raise ValueError("status mora biti prihvaćeno ili odbijeno")
    n = con.execute("UPDATE assistant_notes SET status=?, decided_ts=?, owner_note=? WHERE id=? AND status='novo'",
                    (status, int(time.time()), (owner_note or "")[:1000] or None, int(nid))).rowcount
    con.commit()
    if not n:
        raise ValueError("ta bilješka više ne čeka odluku")
    return n


def apply(con, nid, owner_note=""):
    """The owner's "Primijeni": apply the note's proposed_change when its key is in APPLY (or a caller weight) and
    log old -> new; otherwise mark it 'prihvaćeno' for a manual change. Returns (status, words)."""
    ensure(con)
    r = con.execute(f"SELECT {', '.join(COLS)} FROM assistant_notes WHERE id=? AND status='novo'", (int(nid),)).fetchone()
    if r is None:
        raise ValueError("ta bilješka više ne čeka odluku")
    d = _row(r)
    pc = d.get("proposed_change") if isinstance(d.get("proposed_change"), dict) else None
    note = (owner_note or "")[:1000] or None
    words, applied = "", None
    if pc and "caller" in pc and "weight" in pc:
        h, old, new = _apply_caller(con, pc)
        applied = {"key": f"caller_weights.{h}", "old": old, "new": new}
        words = f"težina callera {h}: {old} → {new}" + _to_shadow(con, "caller_weights")
    elif pc and pc.get("key") in APPLY:
        key = pc["key"]
        old = _current(con, key)
        if "from" in pc and pc["from"] is not None and old is not None and str(pc["from"]) != str(old) \
                and _num(pc["from"]) != _num(old):
            raise ValueError(f"{key} je sada {old}, ne {pc['from']} kako prijedlog pretpostavlja; prihvati ga ručno")
        flag_was = settings.flag(FLAG_OF[key], con=con) if key in FLAG_OF else None
        new = APPLY[key](con, pc.get("to"))
        applied = {"key": key, "old": old, "new": new}
        words = f"{key}: {old} → {new}"
        if key in FLAG_OF and flag_was == "off" and settings.flag(FLAG_OF[key], con=con) == "shadow":
            words += f"; zastavica {FLAG_OF[key]}: sjena (uživo uključuješ ti)"
    if applied is None:
        con.execute("UPDATE assistant_notes SET status='prihvaćeno', decided_ts=?, owner_note=? WHERE id=?",
                    (int(time.time()), note, d["id"]))
        con.commit()
        return "prihvaćeno", "Ova promjena se ne primjenjuje sama; označena je kao prihvaćena za ručnu izmjenu."
    log = list(settings.raw(con).get("applied_log") or [])
    log.insert(0, {"ts": int(time.time()), "note_id": d["id"], **applied})
    _set_settings(con, "applied_log", log[:200])
    con.execute("UPDATE assistant_notes SET status='primijenjeno', decided_ts=?, owner_note=? WHERE id=?",
                (int(time.time()), note, d["id"]))
    con.commit()
    print(f"pravi trade: primijenjen prijedlog asistenta #{d['id']}: {words}", flush=True)
    return "primijenjeno", f"Primijenjeno: {words}."


def _num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None
