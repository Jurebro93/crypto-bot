"""Merge and rank: ONE row per token over the seven proposal sources (proposals/strategies.py), built on
ui/kandidati.build (the same sources, market, rug view, run-up, crew counting and keyed blocks; no second scoring
system). Read-only on every database; proposals/job.py writes the result into proposals.db.

Per token:
  sources        the strategies that propose it (each with its own entry zone, exit, record and expiry)
  EV per strategy = p_tp x TP - (1 - p_tp) x SL - cost   (fractions of the stake; TP / SL of that strategy's exit
                 from the market cap now; p_tp its measured record shrunk toward no edge, proposals/calib.estimate,
                 Grok's p_tp calibrated, calib.apply)
  cost           by the pool's liquidity: 3 % above $50k, 5 % from $25k to $50k, 8 % under $25k; under $20k blocked
  primary        the strategy with the best EV: its exit, entry zone and why are the row's
  n_independent  independent sources: every strategy once, the influencer strategy once per independent caller
                 signal (a known crew within 10 min is one, kol/groupdisc.dedupe as ui/kandidati counts it; callers
                 <= 30 s apart are one: coordinated), a caller crew counted under group not again when its callers are
                 the influencer's
  blocks         rug high (a collapse / mint / freeze / honeypot, or a rug risk rating Grok did not override), wash volume
                 (topcheck/safety.volume_check: 'fail', or few unique traders for the transactions), run-up 5x+ from the
                 first signal, liquidity under $20k, shill-driven (every caller is a paid shiller or a shill-network
                 member: their call is exit liquidity, never an entry), no live market, under $30k, still on the curve,
                 a fake or tiny pool, not trading now, the owner's per-token cap already used
Shown: EV > 0 and no block, ranked by EV, then n_independent. The rest are near misses (why) for the report.
"""
import json
import time

from ui import kandidati

from . import calib, strategies

COST_HI, COST_MID, COST_LO = 0.03, 0.05, 0.08
LIQ_HI, LIQ_MID, LIQ_MIN = 50_000, 25_000, 20_000
RUNUP_BLOCK_X = 5.0
COORD_S = 30
MAX_SOL = 0.15              # the recommended size never above this
OVERRIDE_SHARE = 0.5        # a rug risk rating lifted by Grok's fresh evidence: half the size (ui/kandidati)
KANDIDATI_BLOCKS = ("market", "under_30k", "curve", "fake_pool", "too_big", "liq_share", "not_trading", "rug_hard",
                    "rug_risk", "shill_driven")
BLOCK_HR = {"liq": "likvidnost ispod $20k", "runup": "već 5x ili više od prvog signala", "wash": "lažni volumen",
            "shill": "vođeno shillanjem", "cap": "strop po tokenu je potrošen"}


def cost_for(liq):
    """The round-trip cost of a proposal by the pool's liquidity; None under $20k (blocked)."""
    liq = kandidati._f(liq)
    if liq is None or liq < LIQ_MIN:
        return None
    if liq > LIQ_HI:
        return COST_HI
    if liq >= LIQ_MID:
        return COST_MID
    return COST_LO


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

def _price(ev, cost):
    """(p dict, EV fraction) of one strategy's evidence at this cost."""
    pf = ev.get("p_fixed")
    if pf:
        p = {"p": pf["p"], "p_raw": pf.get("raw"), "n": pf.get("n") or 0, "ci90": pf.get("ci90"), "from": pf.get("from"),
             "calibrated": True}
    else:
        p = calib.estimate(ev.get("hits"), ev.get("n"), ev["tp"], ev["sl"], cost)
        p["from"] = ev.get("record_from")
    return p, calib.ev(p["p"], ev["tp"], ev["sl"], cost)


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
    return out


def blocks_of(r, ctx, evs, cost, size):
    """[{"key", "text"}] of what keeps the row from being shown (see the module text)."""
    out = [b for b in r.get("blocks") or [] if b.get("key") in KANDIDATI_BLOCKS]
    m = r.get("market") or {}
    liq = kandidati._f(m.get("liquidity_usd"))
    if cost is None and not any(b["key"] in ("market", "curve") for b in out):
        out.append({"key": "liq", "text": f"likvidnost ${liq or 0:,.0f} ispod $20k"})
    ru = (r.get("runup") or {}).get("x")
    if ru and ru >= RUNUP_BLOCK_X:
        out.append({"key": "runup", "text": f"kasno: već {ru:.1f}x od prvog signala (granica 5x)"})
    if ctx["wash"].get(r["token"], (False,))[0]:
        out.append({"key": "wash", "text": f"lažni volumen: {ctx['wash'][r['token']][2]}"})
    cal = (r.get("sources") or {}).get("caller") or {}
    who = [str(c.get("who")).lower() for c in cal.get("callers") or [] if c.get("who")]
    shill = {str(h).lower() for h in (ctx.get("shillers") or ())} | {str(h).lower() for h in (ctx.get("shill_members") or ())}
    if who and all(h in shill for h in who) and not any(b["key"] == "shill_driven" for b in out):
        out.append({"key": "shill", "text": "vođeno shillanjem: zovu ga samo plaćeni shilleri / shill mreža (izlazna "
                                            "likvidnost)"})
    if size is not None and size < 0.01:
        out.append({"key": "cap", "text": "strop po tokenu ili po tradeu je već potrošen"})
    return out


def risks_of(r, ctx, prim, est):
    out = []
    rug = r.get("rug") or {}
    if r.get("grok_override"):
        out.append("rug ocjena kaže rizik, Grok ju je nadjačao svježim dokazom: pola uloga")
    out += [w for w in rug.get("warn") or []][:2]
    if rug.get("level") == "unknown":
        out.append("rug provjera još nema podataka o ovom tokenu")
    st, txt = ctx["wash"].get(r["token"], (False, None, None))[1:3]
    if st == "warn" and txt:
        out.append(txt)
    if r.get("shill_n"):
        out.append("zove ga i plaćena shill mreža: njen poziv je znak za izlaz, ne za ulaz")
    m = r.get("market") or {}
    ch1 = kandidati._f(m.get("change_1h_pct"))
    if ch1 is not None and ch1 <= -20:
        out.append(f"pada {ch1:+.0f} % u zadnjem satu")
    liq = kandidati._f(m.get("liquidity_usd")) or 0
    if liq < LIQ_MID:
        out.append(f"tanak pool (${liq:,.0f}): trošak ulaza i izlaza ~8 %")
    ru = (r.get("runup") or {}).get("x")
    if ru and ru >= 2:
        out.append(f"već {ru:.1f}x od prvog signala")
    if (est.get("n") or 0) < 20:
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
    cost = cost_for(liq)
    caps = ctx["caps"]
    size = min(MAX_SOL, caps.get("max_sol_per_trade") or MAX_SOL,
               max(0.0, (caps.get("dca_token_cap") or 0.3) - float((caps.get("held") or {}).get(tok) or 0)))
    if r.get("grok_override"):
        size *= OVERRIDE_SHARE
    size = round(size, 3)
    strat = {}
    for k, ev in evs_all.items():
        if ev.get("invalid"):
            strat[k] = {"valid": False, "why_not": ev["invalid"], "why": ev.get("why")}
            continue
        if cost is None:
            continue
        p, e = _price(ev, cost)
        strat[k] = {"valid": True, "p_tp": p["p"], "p_tp_raw": p.get("p_raw"), "n": p["n"], "hits": p.get("hits"),
                    "ci90": p.get("ci90"), "prior": p.get("prior"), "p_from": p.get("from"), "tp_pct": round(ev["tp"] * 100, 2),
                    "sl_pct": round(ev["sl"] * 100, 2), "cost_pct": round(cost * 100, 1), "ev_pct": round(e * 100, 2),
                    "ts": ev.get("ts"), "expires_ts": ev.get("expires_ts"), "expires_after_s": ev.get("expires_after_s"),
                    "entry_zone": ev.get("entry_zone"), "exits_mcap": strategies.mcaps(ev, mcap),
                    "why": ev.get("why"), "detail": ev.get("detail"), "calibrated": bool(p.get("calibrated"))}
    valid = {k: v for k, v in strat.items() if v.get("valid")}
    evs = {k: evs_all[k] for k in valid}
    blocks = blocks_of(r, ctx, evs_all, cost, size)
    sym = r.get("symbol")
    if not valid or blocks:
        why = "; ".join(b["text"] for b in blocks) or "; ".join(f"{strategies.HR.get(k, k)}: {v['why_not']}"
                                                               for k, v in strat.items() if not v.get("valid")) \
            or "trošak se ne može odrediti"
        return None, {"token": tok, "symbol": sym, "strategies": sorted(evs_all), "why": why, "blocks": blocks,
                      "ev_pct": max((v["ev_pct"] for v in valid.values()), default=None), "mcap": mcap,
                      "strategy_detail": strat}
    prim = max(valid, key=lambda k: (valid[k]["ev_pct"], -strategies.STRATEGIES.index(k)))
    best = valid[prim]
    if best["ev_pct"] <= 0:
        return None, {"token": tok, "symbol": sym, "strategies": sorted(evs_all), "blocks": [],
                      "why": f"EV {best['ev_pct']:+.1f} % nakon troška (najbolja: {strategies.HR[prim]})",
                      "ev_pct": best["ev_pct"], "mcap": mcap, "strategy_detail": strat}
    pos = [k for k in valid if valid[k]["ev_pct"] > 0]
    sources = sorted(pos, key=lambda k: -valid[k]["ev_pct"])
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
    row = {"token": tok, "symbol": sym, "strategy": prim, "sources": sources,
           "n_independent": independent({k: evs[k] for k in pos}, ctx.get("member")),
           "ev_pct": best["ev_pct"], "p_tp": best["p_tp"], "n": best["n"], "ci90": best["ci90"],
           "tp_pct": best["tp_pct"], "sl_pct": best["sl_pct"], "cost_pct": round(cost * 100, 1),
           "size_sol": size, "why": why, "risks": risks_of(r, ctx, prim, best),
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
    row["expires_ts"] = expiry(row, now)
    return row, None


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
    extra = ([{"token": t, "kind": "range", "symbol": r.get("symbol"), "ts": r.get("computed_ts") or now,
               "mcap": ((r.get("now") or {}).get("market_cap_usd"))} for t, r in rcs.items()]
             + [{"token": t, "kind": "event", "symbol": r.get("symbol"), "ts": now, "mcap": r.get("mcap")}
                for t, r in evr.items()]
             + [{"token": t, "kind": "catalyst", "symbol": r.get("symbol"), "ts": r.get("ts") or now,
                 "mcap": r.get("mcap")} for t, r in cat.items()]
             + [{"token": t, "kind": "grok", "ts": g.get("ts")} for t, g in gps.items()])
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
    ctx = {"ranges": rcs, "events": evr, "catalysts": cat, "grok": gps, "records": recs,
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
                        "market_ok": not any(f.startswith("market") for f in failed)}


def rank_key(r):
    """EV first, then the number of independent sources."""
    return (-(r.get("ev_pct") or 0), -(r.get("n_independent") or 0), r["token"])

