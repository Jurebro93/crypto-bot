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
    if "proposal" not in have:   # 11.11. (proposals/, G21): submit_signal_opinion's optional trade proposal
        con.execute("ALTER TABLE assistant_notes ADD COLUMN proposal TEXT")
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


# 11.11. (Jure, proposals/ flag proposals G21): submit_signal_opinion may carry a trade proposal. Every field is optional
# and an opinion without them is stored exactly as before. The proposals pass reads a "kupi" with p_tp as the grok
# strategy's proposal (its p_tp calibrated on Grok's measured record first); nothing here buys.
PROPOSAL_STRATEGIES = ("range", "momentum", "influencer", "group", "insider", "event", "catalyst", "grok")
STRATEGY_ALIAS = {"range_dca": "range", "momentum_scalp": "momentum", "caller": "influencer", "kol": "influencer",
                  "callers": "influencer", "hidden_group": "group", "pre_shill": "group", "insider_copy": "insider",
                  "events": "event", "team_catalyst": "catalyst", "other": "grok"}
PROPOSAL_KEYS = ("strategy", "p_tp", "entry_zone", "exit_zone", "valid_min")


def _mc(x, name):
    try:
        v = float(x)
    except (TypeError, ValueError):
        raise ValueError(f"{name} must be a market cap in USD")
    if not 0 < v <= 1e12:
        raise ValueError(f"{name} must be a market cap in USD above 0")
    return round(v, 2)


def proposal_fields(strategy=None, p_tp=None, entry_zone=None, exit_zone=None, valid_min=None):
    """The optional proposal of a signal opinion, validated -> dict, or None when no field is given."""
    if all(x in (None, "", {}) for x in (strategy, p_tp, entry_zone, exit_zone, valid_min)):
        return None
    out = {}
    if strategy not in (None, ""):
        s = str(strategy).strip().lower()
        s = STRATEGY_ALIAS.get(s, s)
        if s not in PROPOSAL_STRATEGIES:
            raise ValueError(f"strategy must be one of {', '.join(PROPOSAL_STRATEGIES)}")
        out["strategy"] = s
    if p_tp not in (None, ""):
        try:
            p = float(p_tp)
        except (TypeError, ValueError):
            raise ValueError("p_tp must be a probability between 0 and 1")
        if not 0 <= p <= 1:
            raise ValueError("p_tp must be between 0 and 1")
        out["p_tp"] = round(p, 4)
    if entry_zone not in (None, "", {}):
        if not isinstance(entry_zone, dict):
            raise ValueError("entry_zone must be {mcap_low, mcap_high}")
        lo, hi = _mc(entry_zone.get("mcap_low"), "entry_zone.mcap_low"), _mc(entry_zone.get("mcap_high"), "entry_zone.mcap_high")
        if lo > hi:
            raise ValueError("entry_zone.mcap_low must not be above mcap_high")
        out["entry_zone"] = {"mcap_low": lo, "mcap_high": hi}
    if exit_zone not in (None, "", {}):
        if not isinstance(exit_zone, dict):
            raise ValueError("exit_zone must be {tp_mcap, sl_mcap, trailing_pct}")
        ez = {}
        for k in ("tp_mcap", "sl_mcap"):
            if exit_zone.get(k) not in (None, ""):
                ez[k] = _mc(exit_zone[k], f"exit_zone.{k}")
        if exit_zone.get("trailing_pct") not in (None, ""):
            try:
                tr = float(exit_zone["trailing_pct"])
            except (TypeError, ValueError):
                raise ValueError("exit_zone.trailing_pct must be a number 1-90")
            if not 1 <= tr <= 90:
                raise ValueError("exit_zone.trailing_pct must be 1-90")
            ez["trailing_pct"] = round(tr, 2)
        if "tp_mcap" in ez and "sl_mcap" in ez and ez["sl_mcap"] >= ez["tp_mcap"]:
            raise ValueError("exit_zone.sl_mcap must be under tp_mcap")
        ent = out.get("entry_zone")
        if ent and "tp_mcap" in ez and ez["tp_mcap"] <= ent["mcap_low"]:
            raise ValueError("exit_zone.tp_mcap must be above the entry zone")
        if ent and "sl_mcap" in ez and ez["sl_mcap"] >= ent["mcap_high"]:
            raise ValueError("exit_zone.sl_mcap must be under the entry zone")
        out["exit_zone"] = ez
    if valid_min not in (None, ""):
        try:
            v = int(float(valid_min))
        except (TypeError, ValueError):
            raise ValueError("valid_min must be minutes 5-1440")
        if not 5 <= v <= 1440:
            raise ValueError("valid_min must be 5-1440 minutes")
        out["valid_min"] = v
    return out


def submit_signal_opinion(con, kid, token, verdict, confidence=None, interpretation=None, evidence=None, proposal=None):
    """proposal (11.11., optional): {strategy, p_tp, entry_zone, exit_zone, valid_min} (proposal_fields)."""
    tok = _text(token, "token", need=True, cap=64)
    if not 32 <= len(tok) <= 64:
        raise ValueError("token must be a Solana token address")
    v = _verdict(verdict)
    prop = proposal_fields(**{k: (proposal or {}).get(k) for k in PROPOSAL_KEYS}) if proposal else None
    pos = con.execute("SELECT id, symbol FROM positions WHERE token=? ORDER BY id DESC LIMIT 1", (tok,)).fetchone()
    extra = {"proposal": json.dumps(prop, ensure_ascii=False)} if prop else {}
    nid = _insert(con, kid, kind="signal_opinion", position_id=pos[0] if pos else None, token=tok,
                  symbol=pos[1] if pos else None, verdict=v, confidence=_conf(confidence),
                  interpretation=_text(interpretation, "interpretation", need=True), evidence=_json(evidence, "evidence"),
                  **extra)
    out = _done(nid, "signal_opinion")
    if prop:
        out["proposal"] = prop
        out["proposal_note"] = (
            "Stored as a proposal source (strategy grok): shown on the Autopilot's Prijedlozi and in get_proposals only "
            "while verdict is kupi with p_tp, your p_tp CALIBRATED on your measured record gives EV > 0 after cost, "
            "and no block applies (rug high, liquidity under $15k; wash, run-up and shill only lower p). Valid valid_min "
            "minutes (default 60). Nothing is bought." if v == "kupi" and "p_tp" in prop else
            "Stored with the opinion; it becomes a proposal only with verdict kupi and p_tp.")
    return out


def submit_suggestion(con, kid, title, interpretation=None, improvement=None, evidence=None, proposed_change=None):
    pc = _json(proposed_change, "proposed_change")
    if pc and not isinstance(json.loads(pc), dict):
        raise ValueError("proposed_change must be one JSON object, e.g. {\"key\": \"sl_default\", \"from\": 60, \"to\": 40}")
    nid = _insert(con, kid, kind="suggestion", title=_text(title, "title", need=True, cap=TITLE_MAX),
                  interpretation=_text(interpretation, "interpretation", need=True),
                  improvement=_text(improvement, "improvement"), evidence=_json(evidence, "evidence"), proposed_change=pc)
    out = _done(nid, "suggestion")
    if _is_weight(json.loads(pc) if pc else None):   # 11.11.: a caller weight is applied on arrival (auto_apply_weight)
        out.update(_auto_weight_answer(con, nid, f"mcp:{kid}"))
    return out


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


def latest_summary(con, status=None):
    """The newest daily summary (only one with this status when given), or None."""
    ensure(con)
    where = "kind='daily_summary'" + (" AND status=?" if status else "")
    r = con.execute(f"SELECT {', '.join(COLS)} FROM assistant_notes WHERE {where} ORDER BY id DESC LIMIT 1",
                    (status,) if status else ()).fetchone()
    return _row(r) if r else None


def dismiss_summaries(con, upto_id, note=""):
    """10.11. 23:04 (Jure: "kad stisnem ukloni obavijest, ne ukloni se"): "Pročitano, makni" on the newest daily summary
    marks it AND every older unread one read (prihvaćeno), so an older one does not take its place. Returns the count."""
    ensure(con)
    n = con.execute("UPDATE assistant_notes SET status='prihvaćeno', decided_ts=?, owner_note=COALESCE(owner_note, ?) "
                    "WHERE kind='daily_summary' AND status='novo' AND id<=?",
                    (int(time.time()), (note or "")[:1000] or None, int(upto_id))).rowcount
    con.commit()
    return n


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


INSIDER_LABELS_MAX = 5000


def _apply_insider_label(con, x, nid):
    """10.11. (flag insider_copy, kol/precall.py): Grok's verdict on a pre-call wallet, {"wallet", "label": insider |
    team | bot | sniper | legit, "note"}, stored in settings insider_labels only by the owner's "Primijeni"; bot and
    sniper keep the wallet out of the insider copy. Changes no flag and no trading setting. -> (wallet, old, new)."""
    from kol import precall
    w, lab, note = precall.parse_label(x)
    cur = dict(settings.raw(con).get("insider_labels") or {})
    old = (cur.get(w) or {}).get("label")
    cur.pop(w, None)
    cur[w] = {"label": lab, "note": note, "ts": int(time.time()), "note_id": int(nid)}
    if len(cur) > INSIDER_LABELS_MAX:   # the oldest out (dicts keep insertion order; a re-label moved to the end above)
        cur = dict(list(cur.items())[-INSIDER_LABELS_MAX:])
    _set_settings(con, "insider_labels", cur)
    return w, old, lab


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


def record_applied(con, nid, key, old, new, note="", client=None, extra=None):
    """An owner-ordered change that is already done: one line in applied_log for note `nid` (with the time) and the
    note marked primijenjeno, so get_assistant_notes / get_scoring_config show it. A note that is missing or was
    rejected only gets the log line. extra: more fields of the log line (e.g. suggestion_id)."""
    ensure(con)
    now = int(time.time())
    log = list(settings.raw(con).get("applied_log") or [])
    log.insert(0, {"ts": now, "note_id": int(nid), "key": key, "old": old, "new": new, **({"client": client} if client else {}),
                   **(extra or {})})
    _set_settings(con, "applied_log", log[:200])
    con.execute("UPDATE assistant_notes SET status='primijenjeno', decided_ts=?, owner_note=COALESCE(owner_note, ?) "
                "WHERE id=? AND status IN ('novo', 'prihvaćeno')", (now, (note or "")[:1000] or None, int(nid)))
    con.commit()


# 10.11. (Jure, in the chat: "Grok bilješke sa statusom prihvaćeno nisu ništa promijenile ... primijeni #41 odmah;
# uvezi sve prihvaćene težine #45-#62; #40 #42 #43 #44 ugradi iza zastavice, prvo shadow; kad primijeniš, status
# primijenjeno s applied_ts"): done ONCE, at the first start of the UI process after the deploy (owner_once), then
# never again (settings OWNER_ONCE_KEY). The values are the owner's own list, not read from the notes' text.
OWNER_ONCE_KEY = "owner_once_1011"
OWNER_SL = (41, 30)
OWNER_WEIGHTS = ((45, "0xMarko77", 1.4), (46, "ddddddd8a", 0.5), (47, "GoatGems", 0.6),
                 (48, "tg:what_yteiiiidbdksndjdb", 0.3), (56, "EarlyChad_", 0.3), (57, "CipherEdgeCalls", 0.5),
                 (58, "DegenFlow_", 0.3), (59, "itsmeflow18", 0.3), (60, "plsea", 0.4), (61, "AlphaBullishups", 0.4),
                 (62, "Strong69106", 0.5))
OWNER_RULES = ((40, "require_signal", None), (42, "runup_default", ("runup_max", 0.10)),
               (43, "dca_cap", ("dca_token_cap", 0.3)), (44, "caller_ev_rank", None))


def owner_once(con):
    """Apply the owner's list above once. Returns [text] of what was done ([] when it ran before)."""
    if settings.raw(con).get(OWNER_ONCE_KEY):
        return []
    ensure(con)
    done, why = [], "vlasnik u chatu 10.11."
    nid, sl = OWNER_SL
    if sl in settings.SL_CHOICES:
        old = settings.merged({"size_sol": 0.1, "max_sol_per_trade": 0.1}, con).get("sl_default")
        _set_settings(con, "sl_default", sl)
        record_applied(con, nid, "sl_default", old, sl, why)
        done.append(f"#{nid} sl_default {old} → {sl}")
    cur = dict(settings.raw(con).get("caller_weights") or {})
    for nid, h, w in OWNER_WEIGHTS:
        old = cur.get(h)
        cur[h] = w
        _set_settings(con, "caller_weights", cur)
        record_applied(con, nid, f"caller_weights.{h}", old, w, why)
        done.append(f"#{nid} {h} {old} → {w}")
    done.append("caller_weights" + _to_shadow(con, "caller_weights"))
    for nid, flag, val in OWNER_RULES:
        if val is not None:
            key, v = val
            old = _current(con, key)
            _set_settings(con, key, v)
            record_applied(con, nid, key, old, v, why)
        old_mode = settings.flag(flag, con=con)
        _to_shadow(con, flag)
        record_applied(con, nid, f"flag:{flag}", old_mode, settings.flag(flag, con=con), why)
        done.append(f"#{nid} zastavica {flag}: {old_mode} → {settings.flag(flag, con=con)}")
    settings.put(con, OWNER_ONCE_KEY, int(time.time()), "Jure")
    for t in done:
        print(f"pravi trade: primijenjeno po nalogu vlasnika: {t}", flush=True)
    return done



# 10.11. ~19:40 (Jure, in the chat): "promijeni ove zastavice u trade.db settings (flag:<name>) i zapiši promjenu u
# log s ts, starom i novom vrijednošću: x_features_ingest off -> shadow, require_signal shadow -> paper, dca_cap
# shadow -> paper. Ništa od ovoga ne ide na live." and the discovery job "iza zastavice smart_discovery (shadow)".
# Done ONCE (settings OWNER_ONCE_B_KEY) at the first start of the UI process after the deploy; every change is a line
# in applied_log (note_id 0: no note behind it), which get_scoring_config shows with the flag modes.
OWNER_ONCE_B_KEY = "owner_once_1011b"
OWNER_FLAGS_B = (("x_features_ingest", "shadow"), ("require_signal", "paper"), ("dca_cap", "paper"),
                 ("smart_discovery", "shadow"), ("confluence", "shadow"),
                 ("exit_plans", "paper"))   # 10.11. ~21:45 (Jure): "flag exit_plans, start = paper, pa live nakon testa"
# 10.11. ~21:00 (Jure: "Primijeni ovo i makni sa autopilot screena" on Grok's "Prihvaćeno, ali nije primijenjeno: SL je
# još 60 %, Hope DCA 0.6 SOL (cap 0.3)"): sl_default 30 was applied at 17:34 UTC (log "#41 sl_default 60 → 30"); the
# cap becomes the owner's hard limit on his own buys (dca_cap_owner, ui/pravitrade._owner_buy_rules); Grok's rule
# "2+ callers and a smart-wallet buy" goes in as the flag confluence (shadow); the note itself is marked applied, so
# it leaves the page.
GROK_NOTE_TITLE = "Prihvaćeno, ali nije primijenjeno%"
# "otvorena Hope pozicija još ima stop na -40 %. Postavi je na novi sl_default 30 %": a stop is written into the
# position when it opens (league/copy._enter -> auto.set_auto), so a later sl_default change only reaches new
# positions. Here once: the open Hope positions of the Autopilot accounts and the owner with a -40 % stop get -30 %
# from the same base (the effective entry when the stop was set from it), the rest of the exit untouched. NOT when
# the price is already at or within 2 % of the new stop: that change would sell at once (a sale cannot be undone),
# so it is left as it was and the reason is logged.
HOPE_MINT = "GxRPJsRK9TE9EgBhLxrFGcRYLGqPJe4fxtiPmdXCpump"
HOPE_SL_OLD, HOPE_SL_NEW = -40.0, -30.0
HOPE_KEY = "owner_once_1011b_hope"
HOPE_TRIES = 30


def owner_flags_b(con, now=None):
    """The flag part of the owner's 10.11. order (OWNER_FLAGS_B), once. [text] of what was done ([] when done before)."""
    if settings.raw(con).get(OWNER_ONCE_B_KEY):
        return []
    ensure(con)
    why, done = "vlasnik u chatu 10.11.", []
    for name, mode in OWNER_FLAGS_B:
        if mode not in ("off", "shadow", "paper"):   # never live from here
            continue
        old = settings.flag_state(con)[name]["mode"]
        if old == mode:
            done.append(f"zastavica {name}: već {mode}")
            continue
        settings.set_flag(con, name, mode, "Jure (chat 10.11.)", now=now)
        new = settings.flag_state(con)[name]["mode"]
        record_applied(con, 0, f"flag:{name}", old, new, why)
        done.append(f"zastavica {name}: {old} → {new}")
    raw = settings.raw(con)
    if not raw.get("dca_cap_owner"):
        cap = raw.get("dca_token_cap") or settings.DCA_TOKEN_CAP
        _set_settings(con, "dca_cap_owner", True)
        record_applied(con, 43, "dca_cap_owner", "samo zapis (shadow)", f"tvrdi strop {cap:g} SOL po tokenu", why)
        done.append(f"#43 strop po tokenu za tvoje kupnje: {cap:g} SOL (tvrdo)")
    # 10.11. ~21:45 (Jure: "Uključi je, neka Grok trada"): Grok autotrade on, within its own limits (ui/grokauto)
    from ui import grokauto
    if not grokauto.state(con, now)["on"]:
        grokauto.set_on(con, True, "Jure (chat 10.11.)", now)
        record_applied(con, 0, "grok_autotrade", "off", "on", why)
        done.append("Grok autotrade: uključen (limiti " + ", ".join(f"{k} {v:g}" for k, v in grokauto.limits(con).items()) + ")")
    for (nid,) in con.execute("SELECT id FROM assistant_notes WHERE title LIKE ? AND status IN ('novo', 'prihvaćeno')",
                              (GROK_NOTE_TITLE,)).fetchall():
        record_applied(con, nid, "grok_note", "novo", "primijenjeno: sl_default 30 (17:34 UTC), strop 0,3 SOL tvrdo, "
                       "confluence u sjeni", why)
        done.append(f"#{nid} Grokova bilješka označena primijenjenom")
    settings.put(con, OWNER_ONCE_B_KEY, int(now or time.time()), "Jure")
    for t in done:
        print(f"pravi trade: primijenjeno po nalogu vlasnika: {t}", flush=True)
    return done


def hope_stop(con, lcon=None, market=None):
    """The Hope stop part of the order: (finished, [text]); finished=False only when a price was missing (retried).
    Per account, every open Hope lot with a TP/SL exit gets the stop at -30 % from the AVERAGE entry of its lots
    (one level for the whole position, as the group exit does; one lot = its own entry), wherever it was looser
    (-40 %, -60 % of the old default); a tighter stop stays; TP and every other part of the exit stay. Not when the
    price is at or within 2 % of the new level: that would sell at once."""
    from league import copy as lcopy, store as lstore
    users = (settings.LEAGUE_USER, settings.PAPER_USER, settings.owner())
    own = lcon is None
    lcon = lcon or lstore.connect()
    try:
        rows = lcon.execute(f"SELECT * FROM trades WHERE token=? AND status='open' AND user IN ({','.join('?' * len(users))}) "
                            "ORDER BY id", (HOPE_MINT, *users)).fetchall()
        if not rows:
            return True, ["Hope: nema otvorene pozicije (Autopilot / vlasnik), stop nije mijenjan"]
        mk = (market or lcopy.market)({HOPE_MINT}) or {}
        m = mk.get(HOPE_MINT)
        price = m[0] if m else None
        out = []
        groups = {}
        for t in rows:
            a = json.loads(t["auto"]) if t["auto"] else None
            if not a or a.get("mode") != "tpsl":
                out.append(f"Hope #{t['id']} ({t['user']}): izlaz {(a or {}).get('mode') or 'bez izlaza'}, stop nije mijenjan")
                continue
            groups.setdefault(t["user"], []).append((t, a))
        if groups and price is None:
            return False, out + ["Hope: nema cijene, pokušavam ponovno"]
        for user, lots in groups.items():
            qty = sum(t["qty"] or 0 for t, _ in lots)
            bases = [((t["entry_eff"] or t["entry_px"]) if a.get("from_eff") else t["entry_px"], t["qty"] or 0) for t, a in lots]
            avg = (sum(b * q for b, q in bases) / qty) if qty else bases[0][0]
            new_px = avg * (1 + HOPE_SL_NEW / 100)
            if price <= new_px * 1.02:
                out.append(f"Hope ({user}, {len(lots)} lot.): cijena je {(price / avg - 1) * 100:+.0f} % od prosječnog ulaza, "
                           "stop −30 % bi odmah prodao; ostaje kakav je (prodaju odluči vlasnik)")
                continue
            for t, a in lots:
                cur = a.get("sl_px")
                cur_pct = (cur / avg - 1) * 100 if cur else None
                if cur and cur >= new_px * 0.999:
                    out.append(f"Hope #{t['id']} ({user}): stop je već {cur_pct:+.0f} % od prosjeka, ostaje")
                    continue
                a.update(sl_px=new_px, sl=f"{HOPE_SL_NEW:+g}%", sl_in=f"{HOPE_SL_NEW:g}%")
                lcon.execute("UPDATE trades SET auto=? WHERE id=?", (json.dumps(a), t["id"]))
                lcon.commit()
                old_txt = f"{cur_pct:+.0f}%" if cur_pct is not None else "bez stopa"
                record_applied(con, 0, f"sl:trade#{t['id']}", old_txt, f"{HOPE_SL_NEW:+g}% od prosječnog ulaza",
                               "vlasnik u chatu 10.11.: Hope stop na novi sl_default")
                out.append(f"Hope #{t['id']} ({user}): stop {old_txt} → {HOPE_SL_NEW:+g} % od prosječnog ulaza "
                           f"(cijena sada {(price / avg - 1) * 100:+.0f} %)")
        return True, out
    finally:
        if own:
            lcon.close()


# 10.11. later orders of the owner, each applied ONCE (its own settings key, so a new entry added in a later deploy
# runs once too): (flag, mode, why). Never live from here, except an owner switch (settings.OWNER_SWITCHES: live = on,
# it only sells) the owner ordered in the chat.
OWNER_FLAG_ORDERS = (
    ("market_scan", "shadow", "vlasnik u chatu 10.11.: skener tržišta, start = shadow"),
    ("group_discovery", "shadow", "vlasnik u chatu 10.11.: grupe tradera i skrivene liste, start = shadow"),
    ("range_dca", "paper", "vlasnik u chatu 10.11.: range_dca, start = paper (samo demo račun)"),
    ("insider_copy", "shadow", "vlasnik u chatu 10.11.: insajderi prije poziva, start = shadow (paper tek na njegov zahtjev)"),
    ("momentum_scalp", "paper", "vlasnik u chatu 11.11.: momentum_scalp, start = paper (samo demo račun)"),
    ("grok_ev_gate", "shadow", "vlasnik u chatu 11.11.: Grokov EV gate, prvo shadow"),
    ("pre_shill", "shadow", "vlasnik u chatu 11.11.: kupci prije shill mreže, prvo shadow (nikad ne kupuje)"),
    ("grok_predictions", "shadow", "vlasnik u chatu 11.11.: submit_grok_prediction sprema predviđanja i kalibraciju"),
    ("event_tokens", "shadow", "vlasnik u chatu 11.11.: event tokeni s Grokom, prvo shadow"),
    ("range_market", "paper", "vlasnik u chatu 11.11.: range watchlist cijelog tržišta, prvo paper (samo demo račun)"),
    ("proposals", "paper", "vlasnik u chatu 11.11.: Prijedlozi svih strategija, prvo paper (demo račun; pravi samo na tvoj dodir)"),
    ("fast_path", "shadow", "vlasnik u chatu 11.11.: faza 1 fast_check, prvo shadow (mjeri odluke i latenciju)"),
    ("zonewatch", "shadow", "vlasnik u chatu 11.11.: zonski alarmi Grok Botu (zone samo iz rangedca), spoji odmah"),
    ("range_flip", "shadow", "vlasnik u chatu 11.11.: rangedca flip/pauza/ATR stop, prvo shadow (backtest: DD isti, PnL niži)"),
    ("range_missed", "paper", "vlasnik u chatu 11.11.: propušteni tokeni na range listu 72 h, paper po range pravilima"),
    ("fast_path", "paper", "vlasnik u chatu 11.11.: živi kandidati KUPI (paper ako n < 10) — fast_check iz shadowa u paper"),
    ("exit_plan_live", "live", "vlasnik u chatu 11.11.: exit_plan_live DA, svaka live Grok pozicija (autotrade i odobreni tradeovi) ima aktivan plan izlaza"),
)


def owner_flag_orders(con, now=None):
    """Apply the entries of OWNER_FLAG_ORDERS not applied yet. [text] of what was done."""
    done = []
    for name, mode, why in OWNER_FLAG_ORDERS:
        key = f"owner_flag_once:{name}:{mode}"
        if (mode not in ("off", "shadow", "paper") and not (mode == "live" and name in settings.OWNER_SWITCHES)) \
                or name not in settings.FLAGS or settings.raw(con).get(key):   # live only for an owner switch
            continue
        old = settings.flag_state(con)[name]["mode"]
        if old != mode:
            settings.set_flag(con, name, mode, "Jure (chat 10.11.)", now=now)
            new = settings.flag_state(con)[name]["mode"]
            record_applied(con, 0, f"flag:{name}", old, new, why)
            done.append(f"zastavica {name}: {old} → {new}")
        settings.put(con, key, int(now or time.time()), "Jure")
    for t in done:
        print(f"pravi trade: primijenjeno po nalogu vlasnika: {t}", flush=True)
    return done


# 11.11. (Jure: "Prihvati ih. Primjeni ih i makni sa liste. Lista treba biti čista ako nema što što zahtjeva pažnju"):
# Grok's accepted critiques, now in the code; each note marked primijenjeno ONCE (its own settings key) with what was
# actually done, so Grok reads in get_assistant_notes / get_scoring_config what changed.
_SIGNALS = ("signali: token s rug ocjenom risk/hard ili rastom 4x+ od prvog poziva skriven je po zadanom (include_hidden="
            "true ga vraća s razlogom, hidden_count je uvijek u odgovoru); skener ima gornju granicu rasta 4x (runup_max_x)")
_CALLERS = ("loši calleri: Grokove težine callera primjenjuju se automatski čim stignu (caller_weights, raspon 0-2, "
            "zapis u applied_log); djeluju kroz zastavicu caller_weights koja je još u shadowu; ocjene ekipa su "
            "strože (ocjena traži izmjerene pozive, lanac računa se ne označava kao mreža)")
OWNER_NOTE_ORDERS = (
    (54, "signals_clean", _SIGNALS),
    (96, "signals_clean", _SIGNALS),
    (105, "grok_ev_gate", "Grokova vrata po EV-u (grok_ev_gate, shadow): EV = p x TP - (1 - p) x SL - trošak, execute_trade "
                          "prima p_tp i strategy, kalibracija u get_hourly_brief.grok_calibration; momentum_scalp (paper) "
                          "hvata skokove bez callera; " + _SIGNALS),
    (84, "grok_ev_gate", "Grokova kalibracija: execute_trade prima p_tp (0-1) i strategy, grok_ev_gate (shadow) bilježi što "
                         "bi odbio po EV-u, Brierova kalibracija u get_hourly_brief.grok_calibration; momentum_scalp (paper)"),
    (74, "volume_check", "topcheck: nova provjera volumena (wash score, novčanici prema tradeovima, promet prema likvidnosti, "
                         "simetrija kupnji i prodaja, sitne transakcije); wash 60+ = pad, ostalo oprez; vrijedi i za "
                         "kopiranja na Autopilotu"),
    (77, "volume_check", "topcheck: nova provjera botovskog volumena (wash score, novčanici prema tradeovima, promet prema "
                         "likvidnosti, simetrija kupnji i prodaja, sitne transakcije); wash 60+ = pad, ostalo oprez"),
    (85, "wallet_hygiene", "higijena novčanika (wallets/hygiene.py): neaktivni i botovski/sniper novčanici izbačeni iz "
                           "kopiranja Autopilota i webhooka (copy, signal, dokazani); bilježi se koliko je izbačeno"),
    (82, "caller_weights", _CALLERS),
    (75, "caller_weights", _CALLERS),
    (92, "zivo_runup", "živa lista: token 4x+ od prvog poziva označen kao kasno (pick=False), Pregled ga preskače; ekipa "
                       "se u kandidatima za trade broji jednom"),
)


def owner_note_orders(con, now=None):
    """Mark the notes of OWNER_NOTE_ORDERS primijenjeno, each once. [text] of what was done."""
    ensure(con)
    done = []
    for nid, key, what in OWNER_NOTE_ORDERS:
        k = f"owner_note_once:{nid}"
        if settings.raw(con).get(k):
            continue
        r = con.execute("SELECT status FROM assistant_notes WHERE id=?", (nid,)).fetchone()
        if r and r[0] in ("novo", "prihvaćeno"):
            record_applied(con, nid, key, r[0], "primijenjeno", what)
            done.append(f"bilješka #{nid} primijenjena ({key})")
        settings.put(con, k, int(now or time.time()), "Jure")
    for t in done:
        print(f"pravi trade: primijenjeno po nalogu vlasnika: {t}", flush=True)
    return done


def owner_once_b(con, lcon=None, market=None, now=None):
    """Both parts once; the Hope part is retried (HOPE_TRIES times, by dca_loop once a minute) while a price is
    missing. Returns True when nothing is left to do."""
    owner_flags_b(con, now)
    owner_flag_orders(con, now)
    owner_note_orders(con, now)
    try:   # 11.11. (Jure: HAOBIBI): the learning label (league.db) and the range pin, each once (rangedca/owner.py)
        from rangedca import owner as range_owner
        range_owner.owner_once(con, lcon, now)
    except Exception as e:  # noqa: BLE001 - logged; its markers are not set, so the next start tries again
        print(f"pravi trade: nalog vlasnika 11.11. (HAOBIBI): {type(e).__name__}: {e}", flush=True)
    raw = settings.raw(con)
    if raw.get(HOPE_KEY):
        return True
    tries = int(raw.get(HOPE_KEY + "_tries") or 0) + 1
    try:
        finished, out = hope_stop(con, lcon, market)
    except Exception as e:  # noqa: BLE001 - logged, retried
        finished, out = False, [f"Hope stop: {type(e).__name__}: {e}"]
    for t in out:
        print(f"pravi trade: nalog vlasnika: {t}", flush=True)
    if finished or tries >= HOPE_TRIES:
        settings.put(con, HOPE_KEY, {"ts": int(now or time.time()), "out": out}, "Jure")
        return True
    settings.put(con, HOPE_KEY + "_tries", tries, "alat")
    return False

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
    # 10.11. (Jure: "omogući Primijeni na bota i za bilješke koje su već prihvaćeno"): an accepted note can still be
    # applied; a rejected or an applied one cannot
    r = con.execute(f"SELECT {', '.join(COLS)} FROM assistant_notes WHERE id=? AND status IN ('novo', 'prihvaćeno')",
                    (int(nid),)).fetchone()
    if r is None:
        raise ValueError("ta bilješka više ne čeka primjenu (odbijena je ili već primijenjena)")
    d = _row(r)
    pc = d.get("proposed_change") if isinstance(d.get("proposed_change"), dict) else None
    note = (owner_note or "")[:1000] or None
    words, applied = "", None
    if pc and "caller" in pc and "weight" in pc:
        h, old, new = _apply_caller(con, pc)
        applied = {"key": f"caller_weights.{h}", "old": old, "new": new}
        words = f"težina callera {h}: {old} → {new}" + _to_shadow(con, "caller_weights")
    elif pc and isinstance(pc.get("insider_label"), dict):
        w, old, new = _apply_insider_label(con, pc["insider_label"], d["id"])
        applied = {"key": f"insider_label.{w}", "old": old, "new": new}
        words = f"oznaka novčanika {w[:6]}…: {old or 'bez oznake'} → {new}"
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


# ---------- caller weights: applied on arrival ----------------------------------------------------------------------
# 11.11. (Jure: "Automatically accept all weight changes and apply them."): a caller weight suggested by the assistant
# (a suggestion note with proposed_change {"caller", "platform", "weight"}, from submit_suggestion or
# submit_caller_weights; or a row of the older table assistant_suggestions) is written into trade settings
# caller_weights the moment it arrives, through the same path as "Primijeni na bota" (_apply_caller, range 0-2), logged
# in applied_log (ts, note_id or suggestion_id, key caller_weights.<handle>, old, new, client) and marked applied. The
# weights act only through the flag caller_weights (ui/autopilot.caller_weights_flag); this NEVER moves that flag.
AUTO_WEIGHT_WHY = "vlasnik 11.11.: težine callera primjenjuju se automatski"
WEIGHTS_ONCE_KEY = "owner_once_1111_weights"
SUGG_COLS = ("applied_ts",)


def _is_weight(pc):
    return isinstance(pc, dict) and "caller" in pc and "weight" in pc


def auto_apply_weight(con, nid, client=None):
    """Apply note `nid`'s caller weight now. (key, old, new); None when the note carries no weight or no longer
    waits (rejected / applied). ValueError (weight outside 0-2, no handle): the note stays as it is."""
    ensure(con)
    r = con.execute("SELECT proposed_change FROM assistant_notes WHERE id=? AND kind='suggestion' AND status IN "
                    "('novo', 'prihvaćeno')", (int(nid),)).fetchone()
    try:
        pc = json.loads(r[0]) if r and r[0] else None
    except ValueError:
        pc = None
    if not _is_weight(pc):
        return None
    h, old, new = _apply_caller(con, pc)
    key = f"caller_weights.{h}"
    record_applied(con, nid, key, old, new, AUTO_WEIGHT_WHY, client=client or "auto")
    print(f"pravi trade: težina callera {h}: {old} → {new} (bilješka #{nid}, automatski)", flush=True)
    return key, old, new


def _auto_weight_answer(con, nid, client):
    """The part of submit_suggestion's answer for a caller weight."""
    try:
        got = auto_apply_weight(con, nid, client)
    except (ValueError, TypeError) as e:
        return {"status": "novo", "message": f"Stored, NOT applied: {e}. The owner decides it on the Autopilot page."}
    if not got:
        return {}
    key, old, new = got
    mode = settings.flag("caller_weights", con=con)
    return {"status": "primijenjeno", "applied": {"key": key, "old": old, "new": new},
            "flag_caller_weights": mode,
            "message": (f"Applied at once (the owner's standing order): {key} {old} -> {new}. Caller weights act only "
                        f"through the flag caller_weights, now {mode}; this never changes the flag.")}


def _sugg_ensure(con):
    """The older table assistant_suggestions (ui/mcpdata.SUGG_SCHEMA) with its applied_ts column."""
    from ui import mcpdata
    con.execute(mcpdata.SUGG_SCHEMA)
    have = {r[1] for r in con.execute("PRAGMA table_info(assistant_suggestions)")}
    for c in SUGG_COLS:
        if c not in have:
            con.execute(f"ALTER TABLE assistant_suggestions ADD COLUMN {c} INTEGER")
    con.commit()


def apply_suggestion_weight(con, sid, client=None):
    """A row of assistant_suggestions (pending, or approved by /pravi-trade/sugok and not applied yet): its weight
    into caller_weights, the log line (suggestion_id), status approved with applied_ts. (key, old, new) or None."""
    _sugg_ensure(con)
    r = con.execute("SELECT handle, platform, weight FROM assistant_suggestions WHERE id=? AND (status='pending' OR "
                    "(status='approved' AND applied_ts IS NULL))", (int(sid),)).fetchone()
    if not r:
        return None
    h, old, new = _apply_caller(con, {"caller": r[0], "platform": r[1] or "x", "weight": r[2]})
    now = int(time.time())
    key = f"caller_weights.{h}"
    record_applied(con, 0, key, old, new, AUTO_WEIGHT_WHY, client=client or "auto", extra={"suggestion_id": int(sid)})
    con.execute("UPDATE assistant_suggestions SET status='approved', decided_ts=COALESCE(decided_ts, ?), applied_ts=? "
                "WHERE id=?", (now, now, int(sid)))
    con.commit()
    print(f"pravi trade: težina callera {h}: {old} → {new} (prijedlog #{sid}, automatski)", flush=True)
    return key, old, new


def apply_waiting_weights(con, client="vlasnik 11.11. (jednom)"):
    """Every caller weight still waiting: suggestion notes novo / prihvaćeno with a weight, and assistant_suggestions
    rows pending or approved-not-applied, oldest first (a newer weight of the same caller wins). [text] of what was
    done; a weight that fails its check is logged and left waiting."""
    ensure(con)
    done = []
    for nid, pc in con.execute("SELECT id, proposed_change FROM assistant_notes WHERE kind='suggestion' AND status IN "
                               "('novo', 'prihvaćeno') AND proposed_change IS NOT NULL ORDER BY id").fetchall():
        try:
            if not _is_weight(json.loads(pc)):
                continue
            got = auto_apply_weight(con, nid, client)
        except (ValueError, TypeError) as e:
            done.append(f"#{nid}: nije primijenjeno ({e})")
            continue
        if got:
            done.append(f"#{nid} {got[0]}: {got[1]} → {got[2]}")
    try:
        _sugg_ensure(con)
        ids = [i for (i,) in con.execute("SELECT id FROM assistant_suggestions WHERE status='pending' OR "
                                         "(status='approved' AND applied_ts IS NULL) ORDER BY id")]
    except Exception:  # noqa: BLE001 - no older table: nothing waits there
        ids = []
    for sid in ids:
        try:
            got = apply_suggestion_weight(con, sid, client)
        except (ValueError, TypeError) as e:
            done.append(f"prijedlog #{sid}: nije primijenjen ({e})")
            continue
        if got:
            done.append(f"prijedlog #{sid} {got[0]}: {got[1]} → {got[2]}")
    return done


def owner_once_1111(con, now=None):
    """11.11. (Jure), once at the first start after the deploy (dca_loop): every caller weight still waiting is
    applied (apply_waiting_weights), and the stale Grok trade requests are tidied (ui/mcpapi.cleanup_requests_once).
    [text] of what was done ([] when both ran before)."""
    done = []
    if not settings.raw(con).get(WEIGHTS_ONCE_KEY):
        done += apply_waiting_weights(con)
        settings.put(con, WEIGHTS_ONCE_KEY, int(now or time.time()), "Jure")
    try:
        from ui import mcpapi
        n = mcpapi.cleanup_requests_once(con, now)
        if n:
            done.append(f"zastarjelih zahtjeva s Groka pospremljeno: {n}")
    except Exception as e:  # noqa: BLE001 - the 5-min tick tidies them anyway
        done.append(f"zahtjevi s Groka nisu pospremljeni ({type(e).__name__})")
    for t in done:
        print(f"pravi trade: nalog vlasnika 11.11.: {t}", flush=True)
    return done


def _num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None
