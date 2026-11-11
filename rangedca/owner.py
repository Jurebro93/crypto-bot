"""The owner's word on range tokens (11.11., Jure: "HAOBIBI je bio jako dobar ulaz, zapiši ga kao dobitak; sad je na
170.000 MC, trade je samo trebalo malo držati kako je preporučeno. Pogledaj kako naći slične tokene i zadrži ovaj
token: neka bude preporuka ako padne u raspon i volumen se drži").

LABELS  league.db owner_labels (league.db's writer is run_ui.py, where the owner's orders run): a learning label of a
        token, e.g. label "win" kind "missed_win_stop_too_early" = the setup and the entry were right, the stop hit at
        the low, the take profit would have been reached. A COUNTERFACTUAL: the booked round (league.db range_rounds,
        its trades) never changes; the label only links it (round_id, booked_pnl_usd as booked) and keeps the numbers
        of the setup (entry, lot 2, stop, peak, TP in market cap) and its entry-time features for the similarity
        below. Read by get_range_candidates (owner_labels), get_proposals (owner_labels), get_hourly_brief (range
        part) and the 23:30 report (events/evreport, range part, and its log line).
PINS    trade settings "range_pins" ({token: {symbol, ts, who, note, zones_mc}}): a pinned token is ALWAYS in the
        signal pass of run_range.py (data.candidates extra=, first, so the 40-token cap never pushes it out) and in
        get_range_candidates (pinned true, whatever its score or status). It gets a proposal through the normal range
        strategy (proposals/strategies.range_ready) when pin_check passes:
          lower zone    the price (market cap) in the bottom 15 % of the range or inside the bottom zone, and not under
                        range_low_low x 0.92 (the range computed now when it has a pair of zones, else the zones the
                        owner pinned it with)
          volume holds  volume of the last hour >= 50 % of the median of the last 6 hourly volumes AND >= $10k
                        (vol_hold(), computed by run_range.py from the token's minute series: pin_vol in the range JSON)
          fresh         the range's 5-minute numbers at most 4 min old
        The hard blocks of the owner's rules B (rug, liquidity < $15k, 1 h volume < $3k, under $30k, curve, fake pool)
        still apply in proposals/build. The score threshold, the exclusions, the 5-minute change and the buys share are
        NOT required for a pinned token (they are listed in pin.notes): the owner vouches for the range. Nothing buys
        real money from a pin: the demo account's paper takes shown proposals, the real account only on the owner's
        tap. A pin ends only when the owner removes it (POST /pravi-trade/rangepin action=remove, owner only).
SIMILAR the watched range tokens against the labelled wins: features at entry time, each scaled by a fixed typical
        spread (FEATURES; log10 for sizes and touch counts), D2 = the mean of the squared scaled differences over the
        features both sides know (at least MIN_FEATURES), similarity = exp(-D2 / 2) in 0..1 (1 = the same setup; 0.8 =
        the features differ on average by about 2/3 of a typical spread). Fixed spreads, not the watched set's standard
        deviation: the score of a token does not move with whatever else is watched that hour, and a handful of rows
        gives no stable deviation. Unknown features (liquidity in history, holders, top 10) are left out, never guessed.
        get_range_candidates: similar_to per row (the best label,
        never the token itself) and meta similar (top 10); a daily log line (the 23:30 report). Proposals: a range
        proposal with similarity >= SIM_BONUS_MIN gets a P bonus ONLY IN SHADOW (proposals/build: recorded as
        similar_shadow, P and EV unchanged).
The one-time owner order of 11.11. (owner_once: HAOBIBI's label and pin) runs at the first start after the deploy
(ui/assistnotes.owner_once_b, run_ui.py), each part once (its own trade settings marker).
"""
import json
import math
import os
import sqlite3
import time

PINS_KEY = "range_pins"
PIN_ZONE_BOTTOM = 0.15        # rules.RULES["entry_bottom"]
PIN_FLOOR_X = 0.92            # rules.RULES["floor_x"]
PIN_VOL_SHARE = 0.5           # volume 1 h >= 50 % of the median of the last 6 hourly volumes ...
PIN_VOL_MIN = 10_000.0        # ... and >= $10k
PIN_FRESH_S = 4 * 60          # rangedca/trade.METRICS_FRESH_S
SIM_BONUS_MIN = 0.8
SIM_P_BONUS = 0.05            # shadow only: P + 0.05 (never above 0.95)
MIN_FEATURES = 5
_CACHE = {"at": 0.0, "path": None, "pins": {}}
PINS_TTL_S = 10

LABELS_SCHEMA = """CREATE TABLE IF NOT EXISTS owner_labels (
    id INTEGER PRIMARY KEY AUTOINCREMENT, token TEXT NOT NULL, symbol TEXT, ts INTEGER, label TEXT, kind TEXT,
    strategy TEXT, round_id INTEGER, booked_pnl_usd REAL, data TEXT, note TEXT, who TEXT, created_ts INTEGER,
    UNIQUE (token, kind, ts));"""

# ---------- HAOBIBI, 11.11. (the owner's order) ---------------------------------------------------------------------
HAOBIBI = "8tbfkL8LZYUN3ygzWMKfffqVd7tLRpWkuh2fowsepump"
HAOBIBI_TS = 1794390600   # 2026-11-11 09:50 UTC (10:50 CET), lot 1
HAOBIBI_LABEL = {
    "token": HAOBIBI, "symbol": "HAOBIBI", "ts": HAOBIBI_TS, "label": "win", "kind": "missed_win_stop_too_early",
    "strategy": "range", "booked_pnl_usd": -4.26,
    "data": {
        "account": "autopilot-paper", "entry_mc": 112_828, "lot2_mc": 96_210, "stop_mc": 88_120,
        "lot1_ts": HAOBIBI_TS, "lot2_ts": HAOBIBI_TS + 49 * 60, "stop_ts": HAOBIBI_TS + 54 * 60,
        "range_mc": {"range_low_low": 102_894, "range_high_top": 183_000}, "range_score": [0.79, 0.82],
        "tp_mc": 172_300, "tp_from": "TP prijedloga #2 (= range_high_low)",
        # GeckoTerminal 1-minute candles (tests/fixtures/range_haobibi_20261111.json.gz): the minute of the stop had its
        # low at 88,865 (the live feed printed 88,120) and closed at 124,563; the first take profit (172.3k) was traded
        # at 10:55 UTC, the high 179,091 at 10:56 UTC; DexScreener ~170k at 12:00 CET
        "peak_mc": 179_091, "peak_ts": HAOBIBI_TS + 66 * 60, "now_mc": 170_000, "tp_reached": True,
        "tp_reached_ts": HAOBIBI_TS + 65 * 60,
        "proposal": {"id": 2, "strategy": "range", "entry_mc": 88_120, "pnl_usd": -0.28,
                     "note": "kupljen izvan zone (104-112k) i ispod svog SL-a 88,6k; ispravlja se u drugoj grani"},
        # the setup at entry for the similarity (see the module text): the live numbers where the log has them (score,
        # market cap, position in the range from the live range 102,894-183,000), the rest from the GeckoTerminal
        # candles at 10:16 UTC (the same bottom zone; ratio, bottom touches, buys share 5 min as volume proxy),
        # volume of the hour before lot 1 (62.9k), liquidity ~32k (DexScreener 11.11. ~12:00 CET; at the entry not
        # recorded), age 7.15 h (the pool was created 02:41 UTC)
        "features": {"ratio": 1.717, "range_score": 0.80, "pos_pct": 12.4, "vol_liq": round(62_925 / 32_000, 3),
                     "liq": 32_000.0, "mcap": 112_828.0, "age_h": 7.15, "bottom_touches": 9, "buy_share_5m": 0.54,
                     "holders": None, "top10_pct": None},
    },
    "note": ("Vlasnik 11.11.: HAOBIBI je bio jako dobar ulaz. Postav i ulaz su bili točni (lot 1 na 112,8k, lot 2 na "
             "96,2k), tvrdi stop (range_low_low × 0,85) pogođen je jednim fitiljem na dnu (88,1k; 5-minutno zatvaranje "
             "96,4k pa 124,6k), a TP 172,3k dosegnut je 11 minuta kasnije (vrh 179k, sada ~170k). Knjižena runda "
             "ostaje −4,26 $; ova oznaka je protučinjenična, za učenje i izvještaje."),
    "who": "Jure (chat 11.11.)",
}
HAOBIBI_PIN = {"symbol": "HAOBIBI", "zones_mc": {"range_low_low": 102_894, "range_low_top": 112_000,
                                                 "range_high_low": 172_300, "range_high_top": 183_000},
               "note": "vlasnik 11.11.: preporuka kad padne u raspon (donja zona 103-112k) i volumen se drži"}
ONCE_LABEL_KEY = "owner_once_1111:range_label:HAOBIBI"
ONCE_PIN_KEY = "owner_once_1111:range_pin:HAOBIBI"


# ---------- labels (league.db) --------------------------------------------------------------------------------------
def _league_db():
    from league import store
    return store.DB


def ensure_labels(lcon):
    lcon.execute(LABELS_SCHEMA)


def add_label(lcon, token, ts, label, kind, strategy=None, symbol=None, data=None, note=None, who="",
              booked_pnl_usd=None, now=None):
    """One label (INSERT OR IGNORE on token + kind + ts: the same label twice is one). The booked round of that token
    (range_rounds, the newest closed one opened within 2 h before ts .. 6 h after) is linked by id and its booked PnL
    is read from it (never written). Returns the label id, None when it was there already."""
    ensure_labels(lcon)
    rid, booked = None, booked_pnl_usd
    try:
        r = lcon.execute("SELECT id, pnl_usd FROM range_rounds WHERE token=? AND status='closed' AND opened_ts BETWEEN ? "
                         "AND ? ORDER BY opened_ts DESC LIMIT 1", (token, int(ts) - 7200, int(ts) + 6 * 3600)).fetchone()
        if r:
            rid = r[0]
            booked = round(float(r[1]), 2) if r[1] is not None else booked
    except sqlite3.Error:   # no range_rounds table (range_dca never on): the label alone
        pass
    cur = lcon.execute("INSERT OR IGNORE INTO owner_labels (token, symbol, ts, label, kind, strategy, round_id, "
                       "booked_pnl_usd, data, note, who, created_ts) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                       (token, symbol, int(ts), label, kind, strategy, rid, booked,
                        json.dumps(data or {}, separators=(",", ":")), note, who, int(now or time.time())))
    lcon.commit()
    return cur.lastrowid if cur.rowcount else None


def labels(path=None, token=None, label=None):
    """[{id, token, symbol, ts, label, kind, strategy, round_id, booked_pnl_usd, data, note, who}] read-only, newest
    first; [] without league.db or the table."""
    p = path or _league_db()
    if not p or not os.path.exists(p) or not os.path.getsize(p):
        return []
    try:
        con = sqlite3.connect(f"file:{p}?mode=ro", uri=True, timeout=5)
    except sqlite3.Error:
        return []
    try:
        sql, args = "SELECT id, token, symbol, ts, label, kind, strategy, round_id, booked_pnl_usd, data, note, who " \
                    "FROM owner_labels WHERE 1=1", []
        if token:
            sql += " AND token=?"
            args.append(token)
        if label:
            sql += " AND label=?"
            args.append(label)
        out = []
        for row in con.execute(sql + " ORDER BY ts DESC, id DESC", args):
            d = dict(zip(("id", "token", "symbol", "ts", "label", "kind", "strategy", "round_id", "booked_pnl_usd",
                          "data", "note", "who"), row))
            try:
                d["data"] = json.loads(d["data"] or "{}")
            except ValueError:
                d["data"] = {}
            out.append(d)
        return out
    except sqlite3.Error:
        return []
    finally:
        con.close()


def label_view(lb):
    """A label as the MCP API and the reports show it (counterfactual next to the booked result)."""
    d = lb.get("data") or {}
    return {"token": lb["token"], "symbol": lb.get("symbol"), "ts": lb.get("ts"), "label": lb.get("label"),
            "kind": lb.get("kind"), "strategy": lb.get("strategy"), "round_id": lb.get("round_id"),
            "booked_pnl_usd": lb.get("booked_pnl_usd"),
            "booked_note": "knjiženi rezultat runde se ne mijenja; oznaka je protučinjenična (za učenje i izvještaje)",
            "entry_mc": d.get("entry_mc"), "lot2_mc": d.get("lot2_mc"), "stop_mc": d.get("stop_mc"),
            "tp_mc": d.get("tp_mc"), "tp_reached": d.get("tp_reached"), "peak_mc": d.get("peak_mc"),
            "now_mc": d.get("now_mc"), "range_mc": d.get("range_mc"), "features": d.get("features"),
            "note": lb.get("note"), "who": lb.get("who")}


def label_text(lb):
    """One Croatian line of a label (the 23:30 report, the logs)."""
    d = lb.get("data") or {}

    def k(x):
        return f"{x / 1000:.1f}k".replace(".", ",") if x else "?"
    kind = {"missed_win_stop_too_early": "dobitak propušten preranim stopom"}.get(lb.get("kind"), lb.get("kind") or "")
    return (f"{lb.get('symbol') or lb['token'][:6]}: oznaka vlasnika {lb.get('label')} ({kind}): ulaz {k(d.get('entry_mc'))}"
            + (f", lot 2 {k(d.get('lot2_mc'))}" if d.get("lot2_mc") else "") + f", stop {k(d.get('stop_mc'))}, TP "
            f"{k(d.get('tp_mc'))}" + (" dosegnut" if d.get("tp_reached") else "") + f", vrh {k(d.get('peak_mc'))}"
            + (f", knjiženo {lb['booked_pnl_usd']:+.2f} $ ostaje".replace(".", ",")
               if lb.get("booked_pnl_usd") is not None else ""))


# ---------- pins (trade settings) -------------------------------------------------------------------------------------
def _trade_db():
    from trade import settings
    return settings.DB


def pins(path=None, fresh=False):
    """{token: pin} of trade settings range_pins, read-only, cached PINS_TTL_S; {} when unreadable."""
    p = path or _trade_db()
    now = time.monotonic()
    if not fresh and _CACHE["path"] == p and now - _CACHE["at"] < PINS_TTL_S:
        return _CACHE["pins"]
    out = {}
    try:
        if os.path.exists(p) and os.path.getsize(p):
            con = sqlite3.connect(f"file:{p}?mode=ro", uri=True, timeout=5)
            try:
                r = con.execute("SELECT v FROM settings WHERE k=?", (PINS_KEY,)).fetchone()
            finally:
                con.close()
            v = json.loads(r[0]) if r else {}
            out = {t: x for t, x in (v or {}).items() if isinstance(x, dict)} if isinstance(v, dict) else {}
    except (sqlite3.Error, ValueError, TypeError):
        out = {}
    _CACHE.update(at=now, path=p, pins=out)
    return out


def pin_tokens(path=None):
    """The pinned tokens, oldest pin first (they go first into the signal pass)."""
    return [t for t, _x in sorted(pins(path).items(), key=lambda kv: kv[1].get("ts") or 0)]


def pin(tcon, token, who="", symbol=None, note=None, zones_mc=None, now=None):
    """Pin a token (the owner's order or route). Returns the pin; an existing pin keeps its ts."""
    from trade import settings
    token = (token or "").strip()
    if not (32 <= len(token) <= 44) or not token.isalnum():
        raise ValueError("to nije Solana adresa tokena")
    cur = dict(settings.raw(tcon).get(PINS_KEY) or {})
    old = cur.get(token) or {}
    cur[token] = {"symbol": symbol or old.get("symbol"), "ts": old.get("ts") or int(now or time.time()), "who": who,
                  "note": note if note is not None else old.get("note"), "zones_mc": zones_mc or old.get("zones_mc")}
    settings.put(tcon, PINS_KEY, cur, who)
    _CACHE["at"] = 0.0
    return cur[token]


def unpin(tcon, token, who=""):
    """Remove a pin (owner only: the route checks). True when there was one."""
    from trade import settings
    cur = dict(settings.raw(tcon).get(PINS_KEY) or {})
    if token not in cur:
        return False
    cur.pop(token)
    settings.put(tcon, PINS_KEY, cur, who)
    _CACHE["at"] = 0.0
    return True


def vol_hold(candles, now, snap=None):
    """{vol_h1, vol_h1_med6, hourly, holds, why}: the volume of the last hour (the fresh snapshot's vol_h1 when there
    is one, else the candles') against the median of the last 6 hourly volumes from the candles (the current hour
    included), the pin's "volume holds" rule (module text)."""
    now = int(now)
    hourly = [sum(c[5] or 0 for c in candles if now - 3600 * (k + 1) < c[0] <= now - 3600 * k) for k in range(6)]
    v1 = hourly[0]
    if snap and snap.get("vol_h1") is not None and snap.get("ts") and now - snap["ts"] <= 300:
        v1 = float(snap["vol_h1"])
        hourly[0] = v1
    srt = sorted(hourly)
    med = (srt[2] + srt[3]) / 2
    holds = v1 >= PIN_VOL_MIN and v1 >= PIN_VOL_SHARE * med
    why = None if holds else (f"volumen 1 h ${v1:,.0f} ispod $10k" if v1 < PIN_VOL_MIN else
                              f"volumen 1 h ${v1:,.0f} ispod 50 % medijana 6 h (${med:,.0f})")
    return {"vol_h1": round(v1, 2), "vol_h1_med6": round(med, 2), "hourly": [round(h) for h in hourly],
            "holds": holds, "why": why}


def _zones_mc(r, p):
    """(zones in market cap, "range" | "pin"): the range's own when it has a pair of zones, else the pinned ones."""
    from . import detect
    z = ((r or {}).get("zones") or {}).get("mc") or {}
    if detect.has_pair(r) and all(z.get(k) for k in ("range_low_low", "range_low_top", "range_high_low", "range_high_top")):
        return z, "range"
    pz = (p or {}).get("zones_mc") or {}
    if pz.get("range_low_low") and pz.get("range_high_top"):
        pz = dict(pz)
        pz.setdefault("range_low_top", pz["range_low_low"])
        pz.setdefault("range_high_low", pz["range_high_top"])
        return pz, "pin"
    return None, None


def pin_check(r, p, now=None):
    """(ready, why, detail) of a pinned token's range r (range.db JSON) under its pin p: the module text's rule."""
    from . import rules, view
    now = now or time.time()
    z, zfrom = _zones_mc(r, p)
    m = (r or {}).get("metrics") or {}
    mc = m.get("mcap")
    detail = {"zones_from": zfrom, "zones_mc": z, "mcap": mc, "volume": (r or {}).get("pin_vol"), "notes": []}
    if not r:
        return False, "token još nema izračunat raspon (run_range ga prati od sljedećeg prolaza)", detail
    if now - (r.get("mts") or r.get("ts") or 0) > PIN_FRESH_S:
        return False, "5-minutni podaci nisu svježi", detail
    if not z:
        return False, "nema zona raspona", detail
    if not mc:
        return False, "MC nepoznat", detail
    rll, rlt, rht = z["range_low_low"], z["range_low_top"], z["range_high_top"]
    pos = (mc - rll) / (rht - rll) if rht > rll else None
    detail["position_in_range_pct"] = round(pos * 100, 1) if pos is not None else None
    if view.is_breakout(r) and zfrom == "range":
        return False, "probijen gore (iznad raspona)", detail
    if mc < rll * PIN_FLOOR_X:
        return False, f"MC ${mc:,.0f} ispod range_low_low × 0,92 (${rll * PIN_FLOOR_X:,.0f})", detail
    if not ((pos is not None and pos <= PIN_ZONE_BOTTOM) or rll <= mc <= rlt):
        return False, (f"cijena na {pos:.0%} raspona; preporuka tek u donjoj zoni (${rll:,.0f}-${rlt:,.0f}) ili donjih "
                       f"15 %"), detail
    vh = r.get("pin_vol")
    if not vh:
        return False, "volumen 6 h još nije izračunat", detail
    if not vh.get("holds"):
        return False, vh.get("why") or "volumen se ne drži", detail
    # what the normal range rules would still say (shown, not required for a pin)
    sc = r.get("score")
    if sc is None or sc < rules.RULES["score_min"]:
        detail["notes"].append(f"ocjena raspona {sc if sc is not None else '-'} ispod {rules.RULES['score_min']}")
    if r.get("status") != "aktivan":
        detail["notes"].append(f"status raspona: {r.get('status')}")
    if m.get("ch_5m") is not None and m["ch_5m"] <= rules.RULES["ch5_min"]:
        detail["notes"].append(f"pada {m['ch_5m']:+.1%} u 5 min")
    if m.get("buy_share_5m") is not None and m["buy_share_5m"] < rules.RULES["buy_share_min"]:
        detail["notes"].append(f"kupnje {m['buy_share_5m']:.0%} u 5 min")
    return True, None, detail


PIN_RULE = ("Owner pin (rangedca/owner.py): always watched (first in the signal pass, never pushed out by the 40 cap); a "
            "range proposal when the market cap is in the bottom 15 % of the range or inside the bottom zone and not "
            "under range_low_low x 0.92 (the range computed now, else the zones it was pinned with) AND the volume "
            "holds: volume 1 h >= 50 % of the median of the last 6 hourly volumes and >= $10k; the owner's hard "
            "blocks (rug, liquidity < $15k, volume 1 h < $3k, under $30k, curve, fake pool) still apply; score, "
            "exclusions, 5 min change and buys share are not required (listed in pin.notes). Never an automatic "
            "real-money buy; removed only by the owner (POST /pravi-trade/rangepin action=remove).")


# ---------- similarity ------------------------------------------------------------------------------------------------
# name -> (typical spread, log10?): the scale a difference is measured in (see the module text)
FEATURES = {"ratio": (0.3, False), "range_score": (0.1, False), "pos_pct": (15.0, False), "vol_liq": (0.3, True),
            "liq": (0.25, True), "mcap": (0.3, True), "age_h": (0.4, True), "bottom_touches": (0.25, True),
            "buy_share_5m": (0.15, False), "holders": (0.3, True), "top10_pct": (10.0, False)}
AGE_CAP_H = 24.0


def features(r):
    """The similarity features of a computed range (range.db JSON): ratio, range_score, pos_pct, vol_liq (volume 1 h
    / liquidity), liq, mcap, age_h (capped at 24 h: run_range.py keeps a lower bound, age_h), bottom_touches,
    buy_share_5m, holders and top10_pct when known; None for what is not."""
    r = r or {}
    m = r.get("metrics") or {}
    liq, v1 = m.get("liq"), m.get("vol_h1")
    age = r.get("age_h")
    t = (r.get("touches") or {}).get("bottom")
    return {"ratio": r.get("ratio"), "range_score": r.get("score"), "pos_pct": r.get("pos_pct"),
            "vol_liq": (v1 / liq) if liq and v1 is not None and liq > 0 else None, "liq": liq, "mcap": m.get("mcap"),
            "age_h": min(AGE_CAP_H, age) if age is not None else None,
            "bottom_touches": len(t) if t is not None else None, "buy_share_5m": m.get("buy_share_5m"),
            "holders": r.get("holders"), "top10_pct": r.get("top10_pct")}


def similarity(a, b):
    """exp(-D2 / 2) of two feature dicts (module text), None with fewer than MIN_FEATURES features known on both."""
    zs = []
    for k, (scale, lg) in FEATURES.items():
        x, y = a.get(k), b.get(k)
        if x is None or y is None:
            continue
        if k == "age_h":
            x, y = min(AGE_CAP_H, x), min(AGE_CAP_H, y)
        if lg:
            if x <= 0 or y <= 0:
                continue
            x, y = math.log10(x), math.log10(y)
        zs.append(((x - y) / scale) ** 2)
    if len(zs) < MIN_FEATURES:
        return None
    return round(math.exp(-sum(zs) / len(zs) / 2), 4)


REF_MIN_AGE_S = 24 * 3600   # 11.11. (Jure): a reference win must have stood 24 h without a rug


def wins(path=None, lbs=None, now=None):
    """The labelled wins with their entry features: [{token, symbol, features}] (lbs: labels() already read).
    11.11. (Jure: HAOBIBI rugged after it was labelled): a reference for the similarity is only a "win" label older
    than REF_MIN_AGE_S whose token got no hard block since (invalidate() turns such a label into "rug")."""
    now = now or time.time()
    void = _void()   # 11.11. evening: a rug by any label voids the counterfactual win (rugfilter/labels)
    return [{"token": lb["token"], "symbol": lb.get("symbol"), "features": (lb.get("data") or {}).get("features") or {}}
            for lb in (labels(path) if lbs is None else lbs)
            if lb.get("label") == "win" and (lb.get("data") or {}).get("features")
            and now - int(lb.get("ts") or now) >= REF_MIN_AGE_S and lb["token"] not in void]


def _void():
    try:
        from rugfilter import labels as rlabels
        return rlabels.void_set()
    except Exception:  # noqa: BLE001
        return frozenset()


# ---------- 11.11. (Jure: "HAOBIBI je RUGAN u 12:51"): a hard block ends a pin and a counterfactual win ------------
HARD_LIQ = 15_000.0
INVALIDATE = (("8tbfkL8LZYUN3ygzWMKfffqVd7tLRpWkuh2fowsepump",
               "rugan 11.11. 12:51 CET: likvidnost ~24k → 2,6k $, buy share 5m 0,11, rug_risk hard (vlasnik)"),)
CHECK_EVERY_S = 60
_CHK = {"at": 0.0}


def hard_block(token, mcap=None, liq=None):
    """The reason of a hard block of the owner's rules B for a pinned / labelled token, else None: a rug (the 11.11.
    rule, league/copy._rugged), liquidity under $15k."""
    try:
        from league import copy
        rug = copy._rugged(token, mcap, liq)
    except Exception:  # noqa: BLE001
        rug = None
    if rug:
        return "rug" + (f": {rug}" if isinstance(rug, str) else "")
    if liq is not None and liq < HARD_LIQ:
        return f"likvidnost ${liq:,.0f} ispod $15k"
    return None


def invalidate(lcon, token, why, now=None, log=print, quote=None):
    """A hard block on a pinned / labelled token: the pin goes, its "win" labels become "rug" (the counterfactual win
    is void), an open range round of the token is closed at the market as rug (when a price is known) or marked.
    [text] of what was done."""
    from trade import settings
    from . import trade as rtrade
    now = int(now or time.time())
    out = []
    tcon = settings.connect()
    try:
        if unpin(tcon, token, who=f"auto: {why}"[:120]):
            out.append("pin skinut")
    finally:
        tcon.close()
    ensure_labels(lcon)
    stamp = time.strftime("%d.%m. %H:%M", time.gmtime(now + 3600))
    n = lcon.execute("UPDATE owner_labels SET label='rug', kind='rug_after_label', note=COALESCE(note, '') || ? "
                     "WHERE token=? AND label='win'", (f" | {stamp} CET poništeno: {why}", token)).rowcount
    if n:
        out.append(f"oznaka pobjeda → rug ({n})")
    try:
        for r in rtrade.rounds(lcon, token=token):
            lots = rtrade._lots(lcon, r)
            q = (quote or {}).get(token)
            if lots and q and q[0]:
                price, mcap, liq = q[0], q[1], q[2]
                rtrade._sell(lcon, r, lots, "rug", 1.0, price, liq, mcap)
                pnl = rtrade._finish(lcon, r, "rug", now)
                out.append(f"range runda {r['user']} zatvorena kao rug ({pnl:+.2f} $)")
            else:
                st = dict(r.get("state") or {})
                st["rug"] = {"ts": now, "why": why}
                lcon.execute("UPDATE range_rounds SET state=? WHERE id=?", (json.dumps(st), r["id"]))
                out.append(f"range runda {r['user']} označena kao rug (nema cijene za zatvaranje)")
    except Exception as e:  # noqa: BLE001 - the pin and the label above still hold
        out.append(f"range runde: {type(e).__name__}")
    lcon.commit()
    if out:
        log(f"range {token[:6]}: tvrdi blok ({why}): " + ", ".join(out))
    return out


def auto_check(lcon, market_fn=None, now=None, log=print):
    """Once a minute (rangedca/trade.exits_once, run_ui): the owner's one-time list (INVALIDATE, each once), then
    every pinned token and every "win"-labelled token against hard_block() at the market. [text]."""
    from trade import settings
    now = int(now or time.time())
    if now - _CHK["at"] < CHECK_EVERY_S:
        return []
    _CHK["at"] = now
    done = []
    tcon = settings.connect()
    try:
        raw = settings.raw(tcon)
        todo = [(t, w) for t, w in INVALIDATE if not raw.get(f"owner_invalidate:{t}")]
        for t, _w in todo:
            settings.put(tcon, f"owner_invalidate:{t}", now, "Jure")
    finally:
        tcon.close()
    wins_ = {lb["token"] for lb in labels(label="win")}
    toks = set(pins(fresh=True)) | wins_
    void = _void() & wins_   # 11.11. evening: a stored rug label (any version) voids a win even when the market is calm
    for t in sorted(void):
        done += invalidate(lcon, t, "rug po oznaci (stara ili nova, rugfilter/labels): pobjeda poništena", now, log)
        toks.discard(t)
    q = {}
    if market_fn and (toks or todo):
        try:
            from league import exitplan
            raw_q = exitplan.quote(market_fn, toks | {t for t, _w in todo}, now) or {}
            q = {t: (v[0], v[1], v[2]) for t, v in raw_q.items()}   # (price, mcap, liq)
        except Exception:  # noqa: BLE001
            q = {}
    for t, why in todo:
        done += invalidate(lcon, t, why, now, log, q)
        toks.discard(t)
    for t in sorted(toks):
        price, mcap, liq = q.get(t, (None, None, None))
        if price is None:
            continue
        why = hard_block(t, mcap, liq)
        if why:
            done += invalidate(lcon, t, why, now, log, q)
    return done


def similar_to(token, feats, ws):
    """{token, symbol, score} of the most similar labelled win (never the token itself), None without one."""
    best = None
    for w in ws:
        if w["token"] == token:
            continue
        s = similarity(feats, w["features"])
        if s is not None and (best is None or s > best["score"]):
            best = {"token": w["token"], "symbol": w["symbol"], "score": s}
    return best


def ranking(rows, ws, top=10):
    """[{token, symbol, similar_to, score}] of rows (dicts with token, symbol, features), best first, top n."""
    out = []
    for r in rows:
        s = similar_to(r["token"], r["features"], ws)
        if s:
            out.append({"token": r["token"], "symbol": r.get("symbol"), "similar_to": s["symbol"] or s["token"][:6],
                        "similar_to_token": s["token"], "score": s["score"]})
    out.sort(key=lambda x: (-x["score"], x["token"]))
    return out[:top]


def similar_line(rank, ws):
    """The daily log line of the similarity ranking."""
    if not ws:
        return "range slični: nema referenci (oznaka dobitka mora stajati 24 h bez ruga)"
    names = ", ".join(w["symbol"] or w["token"][:6] for w in ws)
    if not rank:
        return f"range slični ({names}): nijedan praćeni raspon nema dovoljno poznatih značajki"
    hi = [x for x in rank if x["score"] >= SIM_BONUS_MIN]
    return (f"range slični ({names}): " + ", ".join(f"{x['symbol'] or x['token'][:6]} {x['score']:.2f}".replace(".", ",")
                                                    for x in rank)
            + f"; >= 0,8: {len(hi)} (P bonus samo u sjeni, P se ne mijenja)")


# ---------- the one-time owner order of 11.11. --------------------------------------------------------------------------
def owner_once(tcon, lcon=None, now=None):
    """HAOBIBI's label (league.db) and pin (trade settings), each once (its own trade settings marker). [text]."""
    from trade import settings
    done = []
    raw = settings.raw(tcon)
    if not raw.get(ONCE_LABEL_KEY):
        own = lcon is None
        if own:
            from league import store
            lcon = store.connect()
        try:
            L = HAOBIBI_LABEL
            lid = add_label(lcon, L["token"], L["ts"], L["label"], L["kind"], L["strategy"], L["symbol"], L["data"],
                            L["note"], L["who"], L["booked_pnl_usd"], now)
            done.append(f"oznaka HAOBIBI ({L['kind']}) " + (f"zapisana (#{lid})" if lid else "već postoji"))
        finally:
            if own:
                lcon.close()
        settings.put(tcon, ONCE_LABEL_KEY, int(now or time.time()), "Jure")
    if not raw.get(ONCE_PIN_KEY):
        if HAOBIBI not in (settings.raw(tcon).get(PINS_KEY) or {}):
            pin(tcon, HAOBIBI, "Jure (chat 11.11.)", HAOBIBI_PIN["symbol"], HAOBIBI_PIN["note"], HAOBIBI_PIN["zones_mc"], now)
            done.append("HAOBIBI prikvačen u range listu (preporuka u donjoj zoni dok volumen drži)")
        settings.put(tcon, ONCE_PIN_KEY, int(now or time.time()), "Jure")
    for t in done:
        print(f"pravi trade: nalog vlasnika 11.11.: {t}", flush=True)
    return done
