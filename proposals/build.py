"""Merge and rank: ONE row per token over the proposal sources (proposals/strategies.py; 11.11. also "fast", the fast
path's KUPI decisions, fast/live.kupi_rows), built on
ui/kandidati.build (the same sources, market, rug view, run-up, crew counting and keyed blocks; no second scoring
system). Read-only on every database; proposals/job.py writes the result into proposals.db.

Per token (11.11., the owner's consolidated correction, rules A-E: trade/cost.py and trade/edge.py):
  sources        the strategies that propose it (each with its own entry zone, exit, record and expiry)
  EV per strategy = P x TP - (1 - P) x SL - cost   (fractions of the stake; TP / SL of that strategy's exit from the
                 MIDDLE of its entry zone, 11.11. decision 4, proposals/publish.at_mid; P its measured record shrunk
                 toward no edge, proposals/calib.estimate, Grok's p_tp
                 calibrated, calib.apply; then x the P modifiers below)
  cost           trade/cost.round_trip(size in USD at kandidati.SOL_USD, liquidity): 2 x fee_side + 2 x impact, the ONE
                 model (the old 3 / 5 / 8 % by liquidity is gone); under $15k liquidity: blocked
  size           min(MAX_SOL, the owner's per-trade and per-token caps, the stake whose buy impact stays <= 2 %)
                 x the volume factor (1 h volume / $10k under $10k) x the size modifiers (trade/cost.size_sol)
  modifiers      (trade/edge.modifiers, never blocks) run-up >= 4x from the first signal: P x 0.7 and size x 0.5 (not
                 when X is bursting and buys >= 60 % of 5 min); wash volume (topcheck/safety.volume_check 'fail', or
                 few unique traders for the transactions) or shill-driven (every caller a paid shiller or a shill-network
                 member): P x 0.5
  primary        the strategy with the best EV per expected minute (strategies.duration_min): its exit, entry zone and
                 why are the row's
  n_independent  independent sources: every strategy once, the influencer strategy once per independent caller
                 signal (a known crew within 10 min is one, kol/groupdisc.dedupe as ui/kandidati counts it; callers
                 <= 30 s apart are one: coordinated), a caller crew counted under group not again when its callers are
                 the influencer's
  blocks         (rule B: only these) rug high (a collapse / mint / freeze / honeypot, or a rug risk rating Grok did not
                 override), liquidity under $15k, 1 h volume under $3k, no live market, under $30k, still on the
                 curve, a fake or tiny pool, not trading now, the owner's per-token cap already used
Shown: EV > 0 (paper: to collect n) and no block; published (11.11., proposals/publish.check) only while the market
cap is inside the entry zone and >= 1 x ATR above the stop, else stored as "čeka zonu" (row wait_why). Ranked (rule D)
by EV per expected minute, then the lower end of the EV's 90 % interval (P at the low end of the record's Wilson
interval), then liquidity. The rest are near misses (why) for the report. Live / autotrade needs more
(trade/edge.live_proof: EV >= +3 %, interval above 0, n >= 10).
"""
import json
import time

from trade import cost as tcost, edge
from ui import kandidati

from . import calib, publish, strategies

LIQ_THIN = 25_000           # under this the risks say the pool is thin (the size already follows the slippage)
COORD_S = 30
MAX_SOL = 0.15              # the recommended size never above this
OVERRIDE_SHARE = 0.5        # a rug risk rating lifted by Grok's fresh evidence: half the size (ui/kandidati)
# 11.11. (owner's rule B): kandidati's keyed blocks the proposals keep (run-up, liq_share and shill_driven are no longer
# blocks there; the liquidity floor is this pass's own "liq")
KANDIDATI_BLOCKS = ("market", "under_30k", "curve", "fake_pool", "too_big", "not_trading", "rug_hard", "rug_risk")
BLOCK_HR = {"liq": "likvidnost ispod $15k", "vol": "volumen 1 h ispod $3k", "cap": "strop po tokenu je potrošen"}


def cost_for(liq, size_usd=None):
    """The round-trip cost of a proposal (trade/cost.round_trip, a fraction); None under $15k liquidity (blocked)."""
    liq = kandidati._f(liq)
    if tcost.liq_block(liq):
        return None
    return tcost.round_trip(size_usd, liq)


def buy_share_5m(r):
    """Buys / transactions of the last 5 min from the row's raw DexScreener reading (None unknown)."""
    w = ((r.get("live_raw") or {}).get("w") or {}).get("m5") or {}
    b, s = w.get("buys"), w.get("sells")
    if b is None or s is None or b + s <= 0:
        return None
    return b / (b + s)


def shill_driven(r, ctx):
    """Every caller of the row is a paid shiller or a shill-network member (their call is exit liquidity)."""
    cal = (r.get("sources") or {}).get("caller") or {}
    who = [str(c.get("who")).lower() for c in cal.get("callers") or [] if c.get("who")]
    shill = {str(h).lower() for h in (ctx.get("shillers") or ())} | {str(h).lower() for h in (ctx.get("shill_members") or ())}
    return bool(who) and all(h in shill for h in who) or "shill_driven" in (r.get("flags") or [])


def modifiers_of(r, ctx):
    """trade/edge.modifiers of one kandidati row (run-up with X and the buy share, wash, shill-driven; 11.11. a dump
    after a pump, rugfilter/collapse kind "dump", P x 0.7 where the old "rugan" blocked)."""
    x = r.get("x") or {}
    return edge.modifiers(runup_x=(r.get("runup") or {}).get("x"),
                          x_score=x.get("x_momentum_score") if x.get("fresh") else None,
                          buy_share_5m=buy_share_5m(r), wash=bool(ctx["wash"].get(r["token"], (False,))[0]),
                          shill=shill_driven(r, ctx), dump=(r.get("rug") or {}).get("dump"))


def caller_signals(calls, member_of=None, crew_s=kandidati.CREW_S, coord_s=COORD_S):
    """calls [(ts, handle)] of one token -> [[handles]]: independent caller signals. A known crew within crew_s is one
    (kol/groupdisc.dedupe, as ui/kandidati counts it), then signals <= coord_s apart are one (coordinated)."""
    if not calls:
        return []
    try:
        from kol import groupdisc
        sigs = groupdisc.dedupe(list(calls), member_of or {}, crew_s)
    except Exception:  # noqa: BLE001
        sigs, seen = [], set()
        for ts, h in sorted(calls):
            if h not in seen:
                seen.add(h)
                sigs.append({"ts": ts, "handles": [h]})
    out, last = [], None
    for s in sorted(sigs, key=lambda s: s["ts"]):
        if out and last is not None and s["ts"] - last <= coord_s:
            out[-1] += [h for h in s["handles"] if h not in out[-1]]
        else:
            out.append(list(s["handles"]))
        last = s["ts"]
    return out


def independent(evs, member_of=None):
    """The number of independent sources behind a row (see the module text)."""
    n, infl = 0, set()
    e = evs.get("influencer")
    if e:
        n += max(1, len(caller_signals(e.get("calls") or [], member_of)))
        infl = {str(h).lower() for h in e.get("handles") or []}
    for k, v in evs.items():
        if k == "influencer":
            continue
        if k == "group" and infl and v.get("crew_handles") and not v["detail"].get("hidden_group") \
                and not v["detail"].get("pre_shill") and {str(h).lower() for h in v["crew_handles"]} <= infl:
            continue   # the same callers as the influencer source: not a second, independent source
        if k == "fast" and infl and str((v.get("detail") or {}).get("source_id") or "").lower().lstrip("@") in infl:
            continue   # 11.11.: the fast check of a call the influencer source already counts
        n += 1
    return max(1, n) if evs else 0


def wash_view(m_raw, trades=None, wash_score=None):
    """(blocked, status, text) of topcheck/safety.volume_check on the row's DexScreener windows and its PumpPortal
    trades of the hour: blocked on 'fail' or on too few unique traders for the transactions (the same lines)."""
    try:
        from topcheck import safety
    except Exception:  # noqa: BLE001
        return False, None, None
    m = m_raw or {}
    w = m.get("w") or {}
    pair = {"liquidity": {"usd": m.get("liq") or 0},
            "txns": {k: {"buys": (w.get(k) or {}).get("buys") or 0, "sells": (w.get(k) or {}).get("sells") or 0}
                     for k in ("h1", "h24")},
            "volume": {"h1": m.get("vol_h1") or (w.get("h1") or {}).get("vol") or 0,
                       "h24": m.get("vol_h24") or (w.get("h24") or {}).get("vol") or 0}} if m else None
    try:
        status, text = safety.volume_check(pair, trades or [], wash_score)
    except Exception:  # noqa: BLE001 - an unreadable check blocks nothing; it is said in the risks
        return False, None, "provjera volumena nije uspjela"
    traders = False
    rows = [t for t in trades or [] if t.get("side") in ("buy", "sell")]
    if status == "warn" and len(rows) >= safety.WASH_MIN_TRADES:
        try:
            from rugfilter import analysis
            vq = analysis.volume_quality(rows)
            traders = (vq["trades"] >= safety.MIN_TRADERS_TX and vq["wallets"] < safety.MIN_TRADERS) or \
                vq["trades_per_wallet"] > safety.MAX_TRADES_PER_TRADER
        except Exception:  # noqa: BLE001
            traders = False
    return status == "fail" or traders, status, text


# ---------- the data seams (the offline tests replace each method) ---------------------------------------------------

class Sources(kandidati.Sources):
    """ui/kandidati's reads plus the proposals pass's own (each returns plain data; one failing is named in
    sources_failed and never hides the others)."""

    def __init__(self, trade_db=None, path=None):
        super().__init__(trade_db)
        self.path = path

    def range_candidates(self, now):
        from rangedca import view
        d = view.candidates(now=now)
        return d.get("candidates") or [] if isinstance(d, dict) else []

    def range_record(self, now):
        from rangedca import gate
        return gate.proof()

    def momentum_record(self, now):
        from momentum import view
        b = view.base_rate(now, 30)
        return {"n": b["n"], "hits": b["hits"]}

    def preshill_record(self, now):
        from kol import groupdisc as gd   # kol/preshill.py writes preshill_signals into early.db
        ec = kandidati._ro(gd.db_path())
        try:
            r = kandidati._q(ec, "SELECT COUNT(*), COALESCE(SUM(hit4h), 0) FROM preshill_signals WHERE measured_ts IS NOT "
                                 "NULL AND hit4h IS NOT NULL AND ts >= ?", (int(now) - 30 * 86400,))
        finally:
            if ec is not None:
                ec.close()
        return {"n": int(r[0][0]), "hits": int(r[0][1])} if r else {"n": 0, "hits": 0}

    def insider_record(self, now):
        """The demo account's closed copies of the pre-call insiders (kol/precall): hits = ret > 0."""
        from kol import groupdisc as gd
        from league import store as lstore
        from trade import settings
        ec = kandidati._ro(gd.db_path())
        try:
            fids = [f for (f,) in kandidati._q(ec, "SELECT follow_id FROM precall_follows WHERE user = ?",
                                               (settings.PAPER_USER,))]
        finally:
            if ec is not None:
                ec.close()
        if not fids:
            return {"n": 0, "hits": 0}
        lc = kandidati._ro(lstore.DB)
        try:
            rets = [r for (r,) in kandidati._q(lc, f"SELECT ret FROM trades WHERE user = ? AND status = 'closed' AND ret IS "
                                                   f"NOT NULL AND follow_id IN ({kandidati._in(fids)})",
                                               (settings.PAPER_USER, *fids))]
        finally:
            if lc is not None:
                lc.close()
        return {"n": len(rets), "hits": sum(1 for r in rets if r > 0)}

    def confirmed_insiders(self):
        from kol import precall
        if precall.mode() == "off":
            return set()
        return {w for w, _s in precall.copy_set()}

    def event_rows(self, now):
        """topics.view.proposal_rows(now, days=7) of the event work (noc/eventi); [] while that module is not here or
        fails (guarded: this branch works without it)."""
        try:
            from topics import view as tview
            rows = tview.proposal_rows(now, days=strategies.EVENT_DAYS)
        except Exception:  # noqa: BLE001 - ImportError or any error: no event proposals
            return []
        return [r for r in rows or [] if isinstance(r, dict) and r.get("token") and (r.get("role") or "main") == "main"]

    def event_record(self, now):
        try:
            from topics import view as tview
            rec = getattr(tview, "record", None)
            return rec(now) if callable(rec) else None
        except Exception:  # noqa: BLE001
            return None

    def catalyst_rows(self, now):
        """catalyst.view.proposal_rows(now, hours=2) of the catalyst work (noc/katalizator, team_catalyst G22); []
        while that module is not here or fails (guarded, like the event rows)."""
        try:
            from catalyst import view as cview
            rows = cview.proposal_rows(now, hours=strategies.CATALYST_HOURS)
        except Exception:  # noqa: BLE001 - ImportError or any error: no catalyst proposals
            return []
        return [r for r in rows or [] if isinstance(r, dict) and r.get("token")]

    def catalyst_record(self, now):
        """{"n", "hits"} of the catalysts' measured +50 % within 4 h (catalyst.view.record) or None."""
        try:
            from catalyst import view as cview
            fn = getattr(cview, "record", None)
            d = fn(now) if callable(fn) else None
        except Exception:  # noqa: BLE001
            return None
        if not isinstance(d, dict) or not d.get("n"):
            return None
        n = int(d["n"])
        hits = d.get("hits")
        if hits is None:
            rate = next((d[k] for k in ("hit_rate", "rate", "rate_50_4h", "up50_4h") if d.get(k) is not None), None)
            hits = round(float(rate) * n) if rate is not None else None
        if hits is None:
            return None
        return {"n": n, "hits": int(hits), "from": d.get("from") or "izmjerena stopa +50 % u 4 h"}

    def range_zones(self, tokens):
        """{token: zones in market cap} of range.db (any range, active or not) for the catalyst exits."""
        from rangedca import data
        if not tokens:
            return {}
        return {t: (r.get("zones") or {}).get("mc") for t, r in data.read_ranges(tokens=list(tokens)).items()
                if (r.get("zones") or {}).get("mc")}

    def range_tier(self, token):
        """rangedca.tier.view(token) of the tier work (noc/tier): {"tier", "size_sol", "reason", ..., "text"} with
        "text" = rangedca.tier.reason_text (e.g. "Tier T2 · ulog 0.25 · razlog: 4 runde +, higher lows 95k→103k");
        None while that module is not here or fails (guarded)."""
        try:
            from rangedca import tier
            v = tier.view(token)
        except Exception:  # noqa: BLE001 - ImportError or any error: no tier
            return None
        if not isinstance(v, dict):
            return None
        v = dict(v)
        try:
            v["text"] = tier.reason_text(v)
        except Exception:  # noqa: BLE001 - another signature: the same line from the fields
            try:
                v["text"] = tier.reason_text(v.get("tier"), v.get("size_sol"), v.get("reason"))
            except Exception:  # noqa: BLE001
                v["text"] = None
        if not v.get("text") and v.get("tier"):
            v["text"] = (f"Tier {v['tier']}" + (f" · ulog {v['size_sol']:g}" if isinstance(v.get("size_sol"), (int, float))
                                                else "") + (f" · razlog: {v['reason']}" if v.get("reason") else ""))
        return v

    def grok_proposals(self, now, window_s=24 * 3600):
        """{token: newest signal_opinion of the window with verdict kupi and a proposal with p_tp}, unless a newer
        opinion on the token says otherwise (trade.db assistant_notes; the proposal column may not exist yet)."""
        tc = self._tcon()
        if tc is None:
            return {}
        try:
            rows = kandidati._q(tc, "SELECT id, ts, token, verdict, confidence, interpretation, proposal FROM "
                                    "assistant_notes WHERE kind='signal_opinion' AND ts >= ? ORDER BY ts, id",
                                (int(now) - window_s,))
        finally:
            tc.close()
        out = {}
        for nid, ts, tok, v, c, txt, pr in rows:
            try:
                prop = json.loads(pr) if pr else None
            except ValueError:
                prop = None
            if v == "kupi" and isinstance(prop, dict) and prop.get("p_tp") is not None:
                out[tok] = {"id": nid, "ts": ts, "verdict": v, "confidence": c, "interpretation": txt, "proposal": prop}
            else:
                out.pop(tok, None)   # a newer opinion without a proposal (or against it) takes it back
        return out

    def calib_model(self, now):
        """Grok's calibration from proposals.db kv (the pass refreshes it every CALIB_EVERY_S)."""
        from . import store
        con = store.ro(self.path)
        if con is None:
            return None
        try:
            return store.kv_get(con, "grok_calib")
        finally:
            con.close()

    def fast_rows(self, now):
        """11.11. (fast/live): {token: the best KUPI fast_check of the last 15 min}; {} without fast.db."""
        from fast import live
        return live.kupi_rows(now)

    def bench(self, handles):
        """{handle: {"n", "hits", "sl_first", "ev_pct"}} of the callers' cached quick-exit benchmark."""
        from . import store
        hs = sorted({h for h in handles if h} | {str(h).lower() for h in handles if h})
        con = store.ro(self.path)
        if con is None or not hs:
            return {}
        try:
            return {h: {"n": n, "hits": k, "sl_first": s, "ev_pct": e} for h, n, k, s, e in kandidati._q(
                con, f"SELECT handle, n, hits, sl_first, ev_pct FROM bench WHERE handle IN ({kandidati._in(hs)})", hs)}
        finally:
            con.close()

    def live_trades(self, token, now):
        """PumpPortal trades of the last hour (hype.db live_trades) for the wash check; [] without them."""
        hc = kandidati._ro(kandidati._hype_db())
        try:
            import run_top
            return run_top.live_trades(hc, token, now)
        except Exception:  # noqa: BLE001
            return []
        finally:
            if hc is not None:
                hc.close()

    def caps(self):
        """{"max_sol_per_trade", "dca_token_cap", "held": {token: SOL in open / pending positions}}: the owner's caps."""
        from trade import executor, settings
        tc = self._tcon()
        try:
            cfg = settings.merged(executor.load_config(), tc) if tc is not None else executor.load_config()
            held = {t: s or 0.0 for t, s in kandidati._q(tc, "SELECT token, SUM(sol_in) FROM positions WHERE status IN "
                                                             "('open','pending') GROUP BY token")} if tc is not None else {}
        finally:
            if tc is not None:
                tc.close()
        return {"max_sol_per_trade": float(cfg.get("max_sol_per_trade") or MAX_SOL),
                "dca_token_cap": float(cfg.get("dca_token_cap") or settings.DCA_TOKEN_CAP), "held": held}


# ---------- one row ----------------------------------------------------------------------------------------------------

def _price(ev, cost, p_mult=1.0):
    """(p dict, EV fraction, EV at the low end of P's 90 % interval) of one strategy's evidence at this cost, P x
    p_mult (the owner's rule B modifiers)."""
    pf = ev.get("p_fixed")
    if pf:
        p = {"p": pf["p"], "p_raw": pf.get("raw"), "n": pf.get("n") or 0, "ci90": pf.get("ci90"), "from": pf.get("from"),
             "calibrated": True}
    else:
        p = calib.estimate(ev.get("hits"), ev.get("n"), ev["tp"], ev["sl"], cost)
        p["from"] = ev.get("record_from")
    # the low end: the Wilson 90 % low of the raw record, never above the shrunk estimate itself
    lo = min((p.get("ci90") or [0.0])[0] or 0.0, p["p"]) * p_mult
    if p_mult < 1:
        p["p_unmodified"] = p["p"]
        p["p"] = round(p["p"] * p_mult, 4)
    return p, calib.ev(p["p"], ev["tp"], ev["sl"], cost), calib.ev(lo, ev["tp"], ev["sl"], cost)


def detect(r, ctx, now):
    """{strategy: evidence} of one kandidati row (invalid ones included, with their reason)."""
    srcs = r.get("sources") or {}
    m = r.get("market") or {}
    mcap = kandidati._f(m.get("market_cap_usd"))
    tok = r["token"]
    out = {}

    def put(ev):
        if ev:
            out[ev["strategy"]] = ev
    rc = ctx["ranges"].get(tok)
    if rc:
        put(strategies.range_ev(rc, mcap, ctx["records"].get("range_proof"), now))
    put(strategies.momentum_ev(srcs.get("momentum"), mcap, ctx["records"].get("momentum"), now))
    shill = set(ctx.get("shillers") or ()) | set(ctx.get("shill_members") or ())
    put(strategies.influencer_ev(srcs.get("caller"), mcap, ctx["bench"], ctx["firsts"].get(tok), shill, now))
    put(strategies.group_ev(srcs, ctx.get("glist"), ctx["records"], ctx["records"].get("pre_shill"), mcap, now))
    put(strategies.insider_ev(srcs.get("insider"), ctx["confirmed"], ctx["records"].get("insider"), mcap, now))
    put(strategies.event_ev(ctx["events"].get(tok), mcap, ctx["records"].get("event"), now))
    put(strategies.catalyst_ev(ctx["catalysts"].get(tok), ctx["zones"].get(tok), mcap, ctx["records"].get("catalyst"),
                               now))
    put(strategies.grok_ev(ctx["grok"].get(tok), mcap, ctx["calib"], now))
    put(strategies.fast_ev((ctx.get("fast") or {}).get(tok), mcap, now))
    return out


def blocks_of(r, ctx, evs, cost, size, cap=None):
    """[{"key", "text"}] of what keeps the row from being shown (only the owner's hard blocks, rule B)."""
    out = [b for b in r.get("blocks") or [] if b.get("key") in KANDIDATI_BLOCKS]
    m = r.get("market") or {}
    liq = kandidati._f(m.get("liquidity_usd"))
    if cost is None and not any(b["key"] in ("market", "curve") for b in out):
        out.append({"key": "liq", "text": tcost.liq_block(liq) or "likvidnost ispod $15k"})
    vb = tcost.vol_block(m.get("volume_1h_usd"))
    if vb and not any(b["key"] in ("market", "curve", "not_trading") for b in out):
        out.append({"key": "vol", "text": vb})
    c = cap if cap is not None else size
    if c is not None and c < 0.01:
        out.append({"key": "cap", "text": "strop po tokenu ili po tradeu je već potrošen"})
    return out


def risks_of(r, ctx, prim, est, cost=None, mods=None):
    out = []
    rug = r.get("rug") or {}
    if r.get("grok_override"):
        out.append("rug ocjena kaže rizik, Grok ju je nadjačao svježim dokazom: pola uloga")
    out += [w for w in rug.get("warn") or []][:2]
    if rug.get("level") == "unknown":
        out.append("rug provjera još nema podataka o ovom tokenu")
    st, txt = ctx["wash"].get(r["token"], (False, None, None))[1:3]
    if st in ("warn", "fail") and txt:
        out.append(txt)
    out += [t["text"] for t in (mods or {}).get("tags") or []]
    if r.get("shill_n"):
        out.append("zove ga i plaćena shill mreža: njen poziv je znak za izlaz, ne za ulaz")
    m = r.get("market") or {}
    ch1 = kandidati._f(m.get("change_1h_pct"))
    if ch1 is not None and ch1 <= -20:
        out.append(f"pada {ch1:+.0f} % u zadnjem satu")
    liq = kandidati._f(m.get("liquidity_usd")) or 0
    if liq < LIQ_THIN:
        out.append(f"tanak pool (${liq:,.0f}): ulog po klizanju do 2 %, trošak ulaza i izlaza "
                   f"~{(cost or 0) * 100:.1f} %".replace(".", ","))
    vol = kandidati._f(m.get("volume_1h_usd"))
    if vol is not None and vol < tcost.VOL_FULL:
        out.append(f"volumen 1 h ${vol:,.0f}: ulog × {tcost.vol_factor(vol):.2f}".replace(".", ","))
    ru = (r.get("runup") or {}).get("x")
    if ru and 2 <= ru < edge.RUNUP_X:
        out.append(f"već {ru:.1f}x od prvog signala")
    if (est.get("n") or 0) < edge.N_MIN:
        out.append(f"malo izmjerenih ishoda (n={est.get('n') or 0}): procjena je oprezna")
    if prim == "event":
        out.append("tokeni događaja često padaju nakon događaja: izlaz prije njega")
    return out


def expiry(row, created_ts):
    """When a proposal stops being valid: the latest expiry of its strategies with EV > 0 (a range's 2 h count from
    the proposal's creation)."""
    st = row.get("strategies") or {}
    xs = [(v.get("expires_ts") or (int(created_ts) + int(v.get("expires_after_s") or 3600)))
          for k, v in st.items() if k in (row.get("sources") or []) and v.get("valid")]
    return int(max(xs)) if xs else int(row.get("expires_ts") or created_ts)


def finish(r, ctx, now, evs_all=None):
    """The merged row of one token: (row for proposals.db, None) when shown, (None, near-miss) otherwise; (None, None)
    when no strategy applies."""
    evs_all = evs_all if evs_all is not None else detect(r, ctx, now)
    if not evs_all:
        return None, None
    tok = r["token"]
    m = r.get("market") or {}
    mcap, liq = kandidati._f(m.get("market_cap_usd")), kandidati._f(m.get("liquidity_usd"))
    price = kandidati._f(m.get("price_usd"))
    caps = ctx["caps"]
    cap = min(MAX_SOL, caps.get("max_sol_per_trade") or MAX_SOL,
              max(0.0, (caps.get("dca_token_cap") or 0.3) - float((caps.get("held") or {}).get(tok) or 0)))
    if r.get("grok_override"):
        cap *= OVERRIDE_SHARE
    mods = modifiers_of(r, ctx)
    # 11.11. (owner's rule C): min(the caps, the 2 % slippage stake) x the volume factor x the size modifiers
    size = round(tcost.size_sol(cap, liq, kandidati.SOL_USD, m.get("volume_1h_usd"), mods["size_mult"]), 3)
    cost = cost_for(liq, size * kandidati.SOL_USD)
    strat = {}
    for k, ev in evs_all.items():
        if ev.get("invalid"):
            strat[k] = {"valid": False, "why_not": ev["invalid"], "why": ev.get("why")}
            continue
        if cost is None:
            continue
        ev = publish.at_mid(ev)   # 11.11. (decision 4): TP / SL from the middle of the entry zone, never the price now
        if ev.get("invalid"):
            strat[k] = {"valid": False, "why_not": ev["invalid"], "why": ev.get("why")}
            continue
        p, e, e_lo = _price(ev, cost, mods["p_mult"])
        dur = strategies.duration_min(ev)
        strat[k] = {"valid": True, "p_tp": p["p"], "p_tp_raw": p.get("p_raw"), "n": p["n"], "hits": p.get("hits"),
                    "ci90": p.get("ci90"), "prior": p.get("prior"), "p_from": p.get("from"), "tp_pct": round(ev["tp"] * 100, 2),
                    "sl_pct": round(ev["sl"] * 100, 2), "cost_pct": round(cost * 100, 2), "ev_pct": round(e * 100, 2),
                    "ev_lo_pct": round(e_lo * 100, 2), "duration_min": dur, "ev_per_min": round(e * 100 / dur, 4),
                    "p_mult": mods["p_mult"], "p_tp_unmodified": p.get("p_unmodified"),
                    "ts": ev.get("ts"), "expires_ts": ev.get("expires_ts"), "expires_after_s": ev.get("expires_after_s"),
                    "entry_zone": ev.get("entry_zone"), "exits_mcap": strategies.mcaps(ev, mcap),
                    "why": ev.get("why"), "detail": ev.get("detail"), "calibrated": bool(p.get("calibrated")),
                    "zone_mid_mcap": ev.get("zone_mid")}
    rc = (ctx.get("ranges") or {}).get(tok)
    if "range" in strat and strat["range"].get("valid"):
        similar_shadow(strat["range"], rc, cost)
    valid = {k: v for k, v in strat.items() if v.get("valid")}
    evs = {k: evs_all[k] for k in valid}
    blocks = blocks_of(r, ctx, evs_all, cost, size, cap)
    sym = r.get("symbol")
    if not valid or blocks:
        why = "; ".join(b["text"] for b in blocks) or "; ".join(f"{strategies.HR.get(k, k)}: {v['why_not']}"
                                                               for k, v in strat.items() if not v.get("valid")) \
            or "trošak se ne može odrediti"
        return None, {"token": tok, "symbol": sym, "strategies": sorted(evs_all), "why": why, "blocks": blocks,
                      "ev_pct": max((v["ev_pct"] for v in valid.values()), default=None), "mcap": mcap,
                      "strategy_detail": strat}
    pos = [k for k in valid if valid[k]["ev_pct"] > 0]
    if not pos:
        prim = max(valid, key=lambda k: (valid[k]["ev_pct"], -strategies.STRATEGIES.index(k)))
        return None, {"token": tok, "symbol": sym, "strategies": sorted(evs_all), "blocks": [],
                      "why": f"EV {valid[prim]['ev_pct']:+.1f} % nakon troška (najbolja: {strategies.HR[prim]})",
                      "ev_pct": valid[prim]["ev_pct"], "mcap": mcap, "strategy_detail": strat}
    # 11.11. (owner's rule D): the best EV per expected minute, then the low end of its interval
    prim = max(pos, key=lambda k: (valid[k]["ev_per_min"], valid[k]["ev_lo_pct"], -strategies.STRATEGIES.index(k)))
    best = valid[prim]
    sources = sorted(pos, key=lambda k: (-valid[k]["ev_per_min"], -valid[k]["ev_pct"]))
    ev0 = evs[prim]
    # the range's tier (rangedca.tier of the tier work, guarded): its line on the card, and for a range proposal its
    # stake as the recommended size, always within MAX_SOL and the owner's caps (size above already is)
    tier = ctx["tier_fn"](tok) if "range" in pos and ctx.get("tier_fn") else None
    if tier and prim == "range":
        ts_ = kandidati._f(tier.get("size_sol"))
        if ts_ and ts_ > 0:
            size = round(min(size, ts_), 3)
    tp_txt, sl_txt = strategies.buy_form(ev0)
    others = [strategies.HR[k] for k in sources if k != prim]
    why = ev0["why"] + (f" Potvrđuje i: {', '.join(others)}." if others else "")
    # 11.11. (trade/settings.NEVER_LIVE): a row only an event topic / the market watchlist brings is paper only
    paper_only = set(pos) <= {"event"} or any(b.get("key") == "paper_only" for b in r.get("blocks") or [])
    row = {"token": tok, "symbol": sym, "strategy": prim, "sources": sources,
           "n_independent": independent({k: evs[k] for k in pos}, ctx.get("member")),
           "ev_pct": best["ev_pct"], "ev_lo_pct": best["ev_lo_pct"], "ev_per_min": best["ev_per_min"],
           "duration_min": best["duration_min"], "p_tp": best["p_tp"], "n": best["n"], "ci90": best["ci90"],
           "tp_pct": best["tp_pct"], "sl_pct": best["sl_pct"], "cost_pct": round(cost * 100, 2),
           "size_sol": size, "why": why, "risks": risks_of(r, ctx, prim, best, cost, mods),
           "modifiers": {"p_mult": mods["p_mult"], "size_mult": mods["size_mult"], "tags": mods["tags"]},
           "paper_only": paper_only,
           "entry_zone": best["entry_zone"], "exits_mcap": best["exits_mcap"], "exit_plan": strategies.exit_plan(ev0),
           "dca": ev0.get("dca"), "buy": {"tp": tp_txt, "sl": sl_txt, "sol": size, "hold_s": strategies.hold_s(ev0)},
           "range_tier": ({k: tier.get(k) for k in ("tier", "size_sol", "reason", "text")} if tier else None),
           "strategies": strat, "also": sorted(set(r.get("source_kinds") or []) - set(strategies.STRATEGIES)),
           "market": {"price_usd": price, "market_cap_usd": mcap, "liquidity_usd": liq,
                      "volume_1h_usd": m.get("volume_1h_usd"), "change_1h_pct": m.get("change_1h_pct")},
           "rug": {k: (r.get("rug") or {}).get(k) for k in ("level", "risk", "warn")},
           "runup_x": (r.get("runup") or {}).get("x"), "grok_override": bool(r.get("grok_override")),
           "exit_signal": "exit_signal" in (r.get("flags") or []),
           "grok": ({"p_tp_raw": valid["grok"].get("p_tp_raw"), "p_tp_calibrated": valid["grok"]["p_tp"],
                     "n": valid["grok"]["n"]} if "grok" in valid else None),
           "price0": price, "mcap0": mcap, "liq0": liq}
    # 11.11. (owner: "tradeable (EV > 0) ne znači da se smije kupiti s pravim novcem"): live / samo papir, by the
    # proposal's own EV and n and the candidate row's source dependence (ui/kandidati.live_state)
    lst, lwhy = kandidati.live_state(True, {"ev_pct": best["ev_pct"], "n_samples": best["n"],
                                            "top_source": r.get("ev_top_source")}, paper_only)
    if lst == "live" and r.get("live_state") == "paper":
        lst, lwhy = "paper", r.get("live_why")
    row["live_state"], row["live_why"] = lst, lwhy
    if rc and rc.get("pinned"):   # 11.11. (the owner's pin, rangedca/owner.py): marked; never an automatic real buy
        row["pinned"] = True
        row["pin_only"] = "range" in pos and not rc.get("entry_ready")
        row["risks"].append("vlasnikov pin: preporuka (demo paper i tvoj dodir); nikad automatska kupnja pravim novcem")
    if (strat.get("range") or {}).get("similar_shadow"):
        row["similar_shadow"] = strat["range"]["similar_shadow"]
    row["expires_ts"] = expiry(row, now)
    publication(row, rc, mcap)
    return row, None


def publication(row, rc, mcap):
    """11.11. (the owner's decision 4, proposals/publish.py): the row's ATR in market cap (the token's range ATR when it
    has a range row, else none: publish falls back to 5 % of the MC), where its EV is measured from, and wait_why (None:
    published; else stored as "čeka zonu" with the reason, decided again by the 20-s loop)."""
    row["atr_mc"], row["atr_from"] = publish.atr_for(rc)
    mid = (row.get("strategies") or {}).get(row["strategy"], {}).get("zone_mid_mcap")
    row["ev_from"] = (f"sredina zone ulaza {strategies._usd(mid)}" if mid else "MC sada (strategija nema zonu ulaza)")
    row["wait_why"] = publish.check(row, mcap)
    return row


def similar_shadow(st, rc, cost):
    """11.11. (rangedca/owner.py): a range proposal of a token similar (>= SIM_BONUS_MIN) to one of the owner's
    labelled wins would get P + SIM_P_BONUS. ONLY IN SHADOW: st["similar_shadow"] records what that would change (P,
    EV, shown or not); st's own p_tp / ev_pct stay as they are."""
    from rangedca import owner
    s = (rc or {}).get("similar_to") or {}
    if not s or (s.get("score") or 0) < owner.SIM_BONUS_MIN or st.get("p_tp") is None:
        return None
    tp, sl = (st.get("tp_pct") or 0) / 100, (st.get("sl_pct") or 0) / 100
    p2 = min(0.95, st["p_tp"] + owner.SIM_P_BONUS)
    ev2 = calib.ev(p2, tp, sl, cost) * 100
    st["similar_shadow"] = {"similar_to": s.get("symbol") or (s.get("token") or "")[:6], "similar_to_token": s.get("token"),
                            "score": s.get("score"), "p_bonus": owner.SIM_P_BONUS, "p_tp_would_be": round(p2, 4),
                            "ev_pct_would_be": round(ev2, 2), "ev_pct_now": st.get("ev_pct"),
                            "would_be_shown": ev2 > 0, "shown_now": (st.get("ev_pct") or 0) > 0,
                            "note": "samo u sjeni: P i EV se ne mijenjaju dok vlasnik ne odluči"}
    return st["similar_shadow"]


def build(now=None, src=None):
    """(rows shown, ranked; near misses; meta {"sources_failed", "prices": {token: (price, mcap)}, ...})."""
    now = int(now or time.time())
    S = src or Sources()
    failed = []

    def safe(name, fn, default):
        try:
            return fn()
        except Exception as e:  # noqa: BLE001 - one broken source never hides the others
            failed.append(f"{name}: {type(e).__name__}")
            return default
    rcs = {r["token"]: r for r in safe("range", lambda: S.range_candidates(now), []) if r.get("token")
           and strategies.range_ready(r) is None}
    evr = {r["token"]: r for r in safe("event", lambda: S.event_rows(now), [])}
    cat = {r["token"]: r for r in safe("catalyst", lambda: S.catalyst_rows(now), [])}
    gps = safe("grok", lambda: S.grok_proposals(now), {}) or {}
    # 11.11. (fast/live): the fast path's KUPI decisions (a source without the reader, e.g. a test double: none)
    fst = safe("fast", lambda: getattr(S, "fast_rows", lambda _n: {})(now), {}) or {}
    extra = ([{"token": t, "kind": "range", "symbol": r.get("symbol"), "ts": r.get("computed_ts") or now,
               "mcap": ((r.get("now") or {}).get("market_cap_usd"))} for t, r in rcs.items()]
             + [{"token": t, "kind": "event", "symbol": r.get("symbol"), "ts": now, "mcap": r.get("mcap")}
                for t, r in evr.items()]
             + [{"token": t, "kind": "catalyst", "symbol": r.get("symbol"), "ts": r.get("ts") or now,
                 "mcap": r.get("mcap")} for t, r in cat.items()]
             + [{"token": t, "kind": "grok", "ts": g.get("ts")} for t, g in gps.items()]
             + [{"token": t, "kind": "fast", "symbol": f.get("symbol"), "ts": f.get("sig_ts") or f.get("decided_ts"),
                 "mcap": f.get("mcap0")} for t, f in fst.items()])
    krows, kmeta = kandidati.build(now, S, details=False, extra=extra, raw=True)
    failed += kmeta.get("sources_failed") or []
    recs = dict(kmeta.get("records") or {})
    recs["range_proof"] = safe("range_record", lambda: S.range_record(now), None)
    recs["momentum"] = safe("momentum_record", lambda: S.momentum_record(now), None)
    recs["pre_shill"] = safe("preshill_record", lambda: S.preshill_record(now), None)
    recs["insider"] = safe("insider_record", lambda: S.insider_record(now), None)
    recs["event"] = safe("event_record", lambda: S.event_record(now), None) if evr else None
    recs["catalyst"] = safe("catalyst_record", lambda: S.catalyst_record(now), None) if cat else None
    handles = {c.get("who") for r in krows for c in ((r.get("sources") or {}).get("caller") or {}).get("callers") or []}
    toks = [r["token"] for r in krows]
    ctx = {"ranges": rcs, "events": evr, "catalysts": cat, "grok": gps, "records": recs, "fast": fst,
           "zones": safe("range_zones", lambda: S.range_zones(sorted(cat)), {}) if cat else {},
           "bench": safe("bench", lambda: S.bench(handles), {}) if handles else {},
           "firsts": safe("first_calls", lambda: S.first_calls(toks, now), {}) if toks else {},
           "confirmed": safe("confirmed", S.confirmed_insiders, set()),
           "calib": safe("calib", lambda: S.calib_model(now), None),
           "shillers": safe("shillers", S.shillers, set()), "shill_members": set(kmeta.get("shill_members") or {}),
           "member": kmeta.get("member") or {}, "glist": kmeta.get("glist") or {},
           "caps": safe("caps", S.caps, {"max_sol_per_trade": MAX_SOL, "dca_token_cap": 0.3, "held": {}}), "wash": {},
           "tier_fn": lambda t: safe("range_tier", lambda: S.range_tier(t), None)}
    rug_tables = kmeta.get("rug_tables") or ({}, {})
    rows, near, prices = [], [], {}
    for r in krows:
        m = r.get("market") or {}
        if m.get("price_usd") and m.get("market_cap_usd"):
            prices[r["token"]] = (m["price_usd"], m["market_cap_usd"])
        evs = detect(r, ctx, now)
        if not evs:
            continue
        rug = ((rug_tables[1] or {}).get(r["token"]) or {}).get("data") or {}
        if isinstance(rug, str):
            try:
                rug = json.loads(rug) or {}
            except ValueError:
                rug = {}
        trades = safe("live_trades", lambda: S.live_trades(r["token"], now), [])
        ctx["wash"][r["token"]] = wash_view(r.get("live_raw"), trades, rug.get("wash_score"))
        got, miss = finish(r, ctx, now, evs)
        if got:
            rows.append(got)
        elif miss:
            near.append(miss)
    rows.sort(key=rank_key)
    for i, r in enumerate(rows, 1):
        r["rank"] = i
    near.sort(key=lambda x: -(x.get("ev_pct") if x.get("ev_pct") is not None else -99))
    return rows, near, {"sources_failed": failed, "prices": prices, "calib": ctx["calib"],
                        "market_ok": not any(f.startswith("market") for f in failed),
                        "kmarket": kmeta.get("market")}


def rank_key(r):
    """11.11. (owner's rule D): EV per expected minute first, then the low end of the EV's 90 % interval, then the
    liquidity (then the independent sources)."""
    return (-(r.get("ev_per_min") or 0), -(r.get("ev_lo_pct") if r.get("ev_lo_pct") is not None else -999),
            -(r.get("liq0") or 0), -(r.get("n_independent") or 0), r["token"])

