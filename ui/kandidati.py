"""Trade candidates over every signal source, and the Grok work queue (10.11., Jure: "kombiniraj Grok kad god je
korisno; najvažnije je naći tokene kojima treba trgovati"). MCP tools get_trade_candidates and get_grok_tasks.
Read-only on every database; nothing here buys. The scanner pass (scan/market.pass_once) logs the top of the list in
scan.db shadow as its own sources (kandidati, grok_override), so the daily report and get_source_stats can tell
whether confluence beats a single source and whether listening to Grok over the rug rating pays.

ONE row per token. The sources (a loader that fails is named in sources_failed, never hides the others):
  caller        X / Telegram calls of the last hour (ui/pravitrade.gather_callers: live-checked, 30k+, awake), each
                caller with its own measured record (one call per token, the 1 h result after a 2 % cost: minute.db
                r60 when measured, else kol.db r1h, as get_caller_leaderboard; +10 % before -20 % within 60 min; the
                Influenceri verdict). Calls of one caller CREW (kol/groupdisc caller group) within 10 min are ONE
                signal; a crew graded exit_liquidity counts 0 (its calls come before the dump)
  wallet        buys in the last hour of the wallets the Autopilot follows (+ wallets/dokazani) and of tier S/A wallets
                (wallets.db), from hype.db chain_trades
  scan / beta   the market scanner's passers of the last hour and its beta candidates (scan.db), plus scanner rows
                that passed every filter but a rug RISK rating (shown; tradeable only through a Grok override)
  hidden_group  group_signals of the last hour: 3+ wallets of one quality wallet group bought, no public call; a
                quality caller crew that called first (caller_group_first) is evidence on the caller signal instead
  range         active ranges (range_score >= 0.7, computed in the last 15 min; rangedca). 11.11.: a range only the
                market watchlist or an event topic brought (rangedca/market.py, watch_source market / event) is
                evidence, never a real-money signal: a row with nothing else is not tradeable (paper only, range_dca
                on the demo account)
  event         11.11. (topics/, flag event_tokens): the main / other tokens of Grok's active event topics, with the
                topic, its event time and buzz trend; counts as one signal, never tradeable on its own (event tokens
                are measured, at most paper-traded on the demo account through range_dca, never real money)
  momentum      momentum_scalp signals of the last 15 min (momentum/: a bonded jump that met every entry rule); its
                record is the base rate of every signal (EV of the exit rules after cost), its exit plan the strategy's
  tool          the tool's own fresh top list (topcheck: rug check 'prolazi', not pumping or falling) and the Pregled
                box's 'visoka' picks: the live list's independent sources (ui/zivo; its 'zovu' and 'konvergencija'
                are the callers and wallets above)
  insider       2+ pre-call insider wallets (kol/insiders, snipers out) bought it in the last hour and nobody called it
                yet; kol.insiders.mcp_candidates(now) is used instead when that module has it
  pre_shill     11.11. (kol/preshill.py, flag pre_shill on): 2+ wallets that buy before the paid shill network (or
                one of their clusters) bought in the last hour, no public call. A call of the shill network itself
                counts 0 in the confluence and -1 in the score (exit liquidity: flag shill_network_call); on a token
                held through a pre_shill signal of the last 24 h it is the exit (flag exit_signal, "sell_into_calls")
Confluence = the independent signals: every caller signal after the crew rule, plus one for each other source kind.

Tradeable = bonded (a pool with liquidity, not the pump.fun curve), market cap >= 30k (CLAUDE.md), the pool gates
(liquidity >= $15k: trade/cost.LIQ_HARD_MIN, the owner's only liquidity block, 11.11. rule B; under $50M, pool not
bigger than the market cap), no confirmed rug, trading now (10+ transactions and $1,000+ volume in the hour, not down
20 %: ui/prijedlog.LIVE_MIN; 1 h volume >= $3k: trade/cost.VOL_FLOOR), and no rug RISK rating unless Grok overrides it.
11.11. (owner's rule B, trade/edge.modifiers): run-up >= RUNUP_MAX_X (4x) from the first signal, shill-driven (only paid
shillers call it) and a pool under 3 % of the market cap (liq_share) are no longer blocks: they are tags ("tags"), and
run-up / shill change P (EV through trade/edge.ev_p_mult on the signal exit: run-up P x 0.7 unless X bursts and buys
>= 60 % of 5 min, shill P x 0.5) and run-up halves the size; the size is also capped at the stake with <= 2 % slippage
and x (1 h volume / $10k) under $10k (trade/cost.size_sol).
Rug, two kinds (10.11., Jure: "ako je BOXCAT označen kao rug, ipak slušaj Groka, jer Grok ima najnovije pozive"):
  hard   NEVER overridden: a rug that already happened (rugfilter/collapse, 11.11. owner's rule: the pool pulled
         > 50 % from its peak, or 70 %+ under the peak with the dev / a top holder selling or a high rug risk), the
         rug archive's rugs, mint / freeze authority still set, RugCheck "rugged", a failed sell test (honeypot).
         A fall from the peak without that is a "dump nakon pumpe": rug.dump, a warning and P x 0.7 (trade/edge)
  risk   a rating of what may happen: the rug filter's verdict ODBAČEN / VISOK RIZIK (scan/filters.rug_filter_why),
         supply concentration (league/copy._concentration), topcheck 'pao' on anything but the mechanics above
A risk row stays tradeable=false, unless Grok sent FRESH evidence for the token in the last GROK_FRESH_S (30 min): an
X features row (submit_x_features) that names known callers / large accounts or shows growing organic momentum, or a
submit_signal_opinion with verdict kupi / dobar, and its newest piece of evidence is not against it (preskoči / loš,
or a falling X count). Then grok_override is set: the rug warning stays on the row, the suggested size is half of
Grok's own per-trade limit, the exit plan is tight (EXIT_TIGHT), and the row is logged as shadow source grok_override.
execute_trade with require_approval=false applies the same rule (ui/grokauto.py: a risk rating without fresh Grok
evidence is refused; with it the buy may be at most half of grok_max_sol_per_trade).
11.11. (Jure: "Dacity score 2.384, ev -0.166, MC $6.6M, tradeable"): tradeable ALSO needs ev_pct > 0 (ev_estimate:
the n-weighted EV of the measured records the sources rest on, shrunk by SHRINK_N, net of the cost model (trade/cost:
the records are net of its fee part, the calibration difference and the price impact of the suggested size come off
on top) and of the P modifiers; n_samples, ev_confidence low under 10); else why_not says "negativan EV" / the
fast_check's state. 11.11. (fast/live, Jure: every live candidate gets a fast_check and an EV): each row carries
"fast" (the token's fast_check verdict); a row without a measured record takes its EV (fast_ev), a PRESKOČI on a check
is the block "fast_skip".

The ranking (rank_key): tradeable rows first, then ev_pct, then confluence, then the score (SCORE_TEXT):
    score = 1.0 * log2(1 + confluence)
          + 3.0 * sum over source kinds of clamp(ev * n / (n + 20), -0.10, +0.10)
          + 0.5 * freshness                    1 when the newest signal is <= 10 min old, falling to 0 at 60 min
          + 0.4 * clamp(x_momentum_score, -1, 1)   only a fresh X row: Grok's (2 h, it wins) or the scanner's (1 h)
          - 1.5 * chase                        run-up: max(log2(run_x) / 2, (log2(24 h multiple) - 2) / 3) in 0..1
          - rug penalty                        0 ok or unknown, 0.3 oprez, 1.5 risk (also when overridden), 3 hard
          - 1.0 * shill-network call signals   flag pre_shill on (kol/preshill.py): exit liquidity
  ev, n: the source's measured shadow record (scan.db shadow, tradeable rows, the gate window; group_signals for
  hidden_group; the range paper rounds), for callers the mean of the calling accounts' own records. A source with no
  measured outcome adds 0: confluence alone never makes a row look proven.
"""
import json
import math
import os
import sqlite3
import time

from trade import cost as _tcost, edge as _tedge

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WINDOW_S = 3600            # signals of the last hour
CREW_S = 600               # one caller crew within 10 min = one signal
GROK_FRESH_S = 1800        # Grok evidence counts this long (override, x_check task done)
CONFLICT_DONE_S = 3600     # a submit_signal_opinion on the token this recent answers a conflict task
MIN_MCAP = 30_000          # CLAUDE.md: never bought under 30k
MEASURE_MIN_MCAP = 10_000  # 10.11. (owner): may be measured (shown, never tradeable) from 10k
RUNUP_MAX_X = 4.0          # 4x or more since the first signal: a tag and P x 0.7 / size x 0.5 (trade/edge.RUNUP_X)
CACHE_S = 60
MAX_TOKENS = 240           # tokens priced in one build (8 DexScreener requests of 30, free; 11.11.: was 60 and cut
                           # off every token after the 60th, the range rows came last and showed "no live market")
RANGE_FRESH_S = 300        # 11.11.: rangedca's own DexScreener snapshot (range.db snaps) used as is when this fresh
RANGE_STALE_S = 900        # ... and as the fallback, labelled, up to this age when DexScreener does not answer
SHRINK_N = 20              # a source's EV is pulled toward 0 by this many pseudo-outcomes
EV_CAP = 0.10
W = {"confluence": 1.0, "ev": 3.0, "fresh": 0.5, "x": 0.4, "chase": 1.5, "shill": 1.0}
RUG_PEN = {"ok": 0.0, "unknown": 0.0, "oprez": 0.3, "risk": 1.5, "hard": 3.0}
POSITIVE = ("kupi", "dobar")
NEGATIVE = ("preskoči", "loš")
OVERRIDE_SIZE = 0.5
EXIT_TIGHT = {"take_profits": [{"at_pct": 15, "sell_share": 0.5}], "trailing": {"activate_pct": 15, "trail_pct": 10},
              "stop": {"at_pct": -12}, "time_stop": {"after_min": 30, "if_pnl_below_pct": 5},
              "reason": "Grok je nadjačao rug ocjenu: pola uloga, stop -12 %, pola van na +15 %, trailing 10 %"}
HARD_MECHANICS = ("mint authority", "freeze authority", "RugCheck ga je označio kao rugan")
SOL_USD = float(os.environ.get("KAND_SOL_USD") or 250)   # SOL price for the price impact of the suggested size (high = cautious)
SCORE_TEXT = ("tradeable first (tradeable needs ev_pct > 0), then ev_pct (unmeasured = 0), then confluence, then "
              "score = 1.0*log2(1+confluence) + 3.0*sum_k clamp(ev_k*n_k/(n_k+20), -0.10, "
              "0.10) + 0.5*freshness(1 at <=10 min, 0 at 60 min) + 0.4*clamp(x_momentum_score,-1,1) (fresh X only, "
              "Grok first) - 1.5*chase(run-up from the first signal; 24 h pump) - rug penalty (0 ok, 0.3 oprez, 1.5 "
              "risk even when overridden, 3 hard) - 1.0*shill-network call signals (flag pre_shill: exit liquidity)")
_CACHE = {"ts": 0.0, "rows": None, "meta": None}


def _f(x):
    try:
        return float(x) if x is not None else None
    except (TypeError, ValueError):
        return None


def _ro(path):
    if not path or not os.path.exists(path) or not os.path.getsize(path):
        return None
    try:
        return sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=10)
    except sqlite3.Error:
        return None


def _q(con, sql, args=()):
    if con is None:
        return []
    try:
        return con.execute(sql, args).fetchall()
    except sqlite3.Error:
        return []


def _in(xs):
    return ",".join("?" * len(xs))


def _hype_db():
    return os.environ.get("HYPE_DB") or os.path.join(ROOT, "hype.db")


def _names(x):
    from scan import xmom
    return xmom._names(x)


# ---------- the data seams (the offline tests replace each method) -------------------------------------------------

class Sources:
    """Every read of build(); each returns plain data. trade_db: trade.db (assistant notes, Grok's limits)."""

    def __init__(self, trade_db=None):
        self.trade_db = trade_db

    def callers(self, now):
        """[(token, [(who, platform, ts)], first_ts, last_ts, symbol, live market)]."""
        from ui import pravitrade
        return pravitrade.gather_callers(now, limit=20)

    def wallet_buys(self, now):
        """[(wallet, mint, first buy ts, tier or 'prati')]: followed wallets and tier S/A wallets, last hour."""
        from ui import pravitrade
        from wallets import store as wstore
        tiers = {}
        wc = _ro(wstore.DB)
        try:
            tiers = {w: t for w, t in _q(wc, "SELECT wallet, tier FROM wallets WHERE tier IN ('S', 'A')")}
        finally:
            if wc is not None:
                wc.close()
        followed = pravitrade.followed_wallets()
        ws = sorted(set(tiers) | set(followed))
        if not ws:
            return []
        hc = _ro(_hype_db())
        out = []
        try:
            for i in range(0, len(ws), 900):
                part = ws[i:i + 900]
                for w, m, ts in _q(hc, f"SELECT wallet, mint, MIN(ts) FROM chain_trades WHERE ts >= ? AND side='buy' "
                                       f"AND wallet IN ({_in(part)}) GROUP BY wallet, mint",
                                   (int(now) - WINDOW_S, *part)):
                    out.append((w, m, int(ts), tiers.get(w) or "prati"))
        finally:
            if hc is not None:
                hc.close()
        return out

    def scan_rows(self, now):
        """{token: scanner row} of the last hour: passers, tokens with a shadow entry, and rows that failed only on a
        rug risk rating (scan/filters.is_rug_risk)."""
        from scan import filters, store
        con = store.ro()
        if con is None:
            return {}
        since = int(now) - WINDOW_S
        out = {}
        try:
            con.row_factory = sqlite3.Row
            pre = " OR ".join("why LIKE ?" for _ in filters.RUG_RISK_PREFIXES)
            for r in con.execute(
                    f"SELECT * FROM cand WHERE checked_ts >= ? AND (passed=1 OR token IN (SELECT token FROM shadow WHERE "
                    f"found_ts >= ?) OR {pre}) ORDER BY checked_ts DESC LIMIT 100",
                    (since, since, *(p + "%" for p in filters.RUG_RISK_PREFIXES))):
                d = dict(r)
                try:
                    d["reasons"] = json.loads(d.get("reasons") or "[]")
                except ValueError:
                    d["reasons"] = []
                d["sources"] = sorted({s for (s,) in con.execute(
                    "SELECT source FROM shadow WHERE token=? AND found_ts >= ?", (d["token"], since))})
                out[d["token"]] = d
        except sqlite3.Error:
            return out
        finally:
            con.close()
        return out

    def scan_first(self, tokens):
        """{token: (ts, mcap)} of the token's first shadow entry with a market cap (any source)."""
        from scan import store
        con = store.ro()
        if con is None or not tokens:
            return {}
        try:
            return {t: (ts, mc) for t, ts, mc in _q(con, f"SELECT token, MIN(found_ts), mcap0 FROM shadow WHERE token IN "
                                                       f"({_in(tokens)}) AND mcap0 > 0 GROUP BY token", list(tokens))}
        finally:
            con.close()

    def group_signals(self, now, since=None):
        """[(ts, source, gid, token, who, mcap_usd)] of group_discovery (empty while the flag is off)."""
        from kol import groupdisc
        if groupdisc.mode() == "off":
            return []
        ec = _ro(groupdisc.db_path())
        try:
            return _q(ec, "SELECT ts, source, gid, token, who, mcap_usd FROM group_signals WHERE ts >= ? ORDER BY ts",
                      (int(since if since is not None else now - WINDOW_S),))
        finally:
            if ec is not None:
                ec.close()

    def groups(self):
        """({caller handle: gid}, {gid: (kind, grade, members, metrics)}) of group_discovery ({} while off)."""
        from kol import groupdisc
        if groupdisc.mode() == "off":
            return {}, {}
        ec = _ro(groupdisc.db_path())
        try:
            member = {m: g for m, g in _q(ec, "SELECT member, gid FROM group_member WHERE kind='caller'")}
            gl = {}
            for gid, kind, grade, members, metrics in _q(ec, "SELECT id, kind, grade, members, metrics FROM group_list"):
                try:
                    met = json.loads(metrics or "{}")
                    # 11.11.: the grade by today's rule (quality needs 8+ measured events and 4 h / 24 h results)
                    gl[gid] = (kind, groupdisc.grade_of(kind, grade, met), json.loads(members or "[]"), met)
                except ValueError:
                    gl[gid] = (kind, grade, [], {})
            return member, gl
        finally:
            if ec is not None:
                ec.close()

    def group_activity(self, now):
        """[(ts, kind, gid, token, who)] of the last 24 h (for the label tasks)."""
        from kol import groupdisc
        if groupdisc.mode() == "off":
            return []
        ec = _ro(groupdisc.db_path())
        try:
            return _q(ec, "SELECT ts, kind, gid, token, who FROM group_activity WHERE ts >= ? ORDER BY ts DESC LIMIT 500",
                      (int(now) - 86400,))
        finally:
            if ec is not None:
                ec.close()

    def ranges(self, now):
        from rangedca import data, rules, trade, view
        ms = rules.RULES["score_min"]
        return {t: r for t, r in data.read_ranges(since=now - trade.RANGE_FRESH_S, active_only=True).items()
                if r.get("active") and (r.get("score") or 0) >= ms - 1e-9
                and not view.is_breakout(r)}   # 11.11.: above its range it is no range candidate

    def events(self, now):
        """11.11. (flag event_tokens): the main / other tokens of the active event topics (topics/view.py)."""
        from topics import view
        return view.kandidati_rows(now)

    def momentum(self, now):
        """11.11. (flag momentum_scalp): the newest momentum signal per token of the last 15 min (momentum.db)."""
        from momentum import view
        return view.kandidati_rows(now)

    def tool_rows(self, now):
        """The live list's own sources (ui/zivo._sources 'alat' and 'prijedlog')."""
        out = []
        from topcheck import store as tstore
        for tok, r in tstore.read_all(max_age_h=1).items():
            st = (r.get("state") or {}).get("state")
            if r.get("rank") is not None and r.get("verdict") == "prolazi" and st not in ("pumpa", "pada"):
                out.append({"token": tok, "symbol": r.get("symbol"), "src": "alat", "ts0": r.get("ts"),
                            "mcap0": r.get("mcap"), "rank": r.get("rank")})
        from ui import pravitrade
        for p in pravitrade.latest_picks(now, limit=10):
            if p.get("razina") == "visoka" and now - (p.get("ts") or 0) <= 6 * 3600:
                out.append({"token": p["token"], "symbol": None, "src": "prijedlog", "ts0": p.get("ts"),
                            "mcap0": p.get("mcap0"), "conf": p.get("conf")})
        return out

    def pre_shill(self, now):
        """kol/preshill.kandidati_view: the shill networks' members, the pre-shill signals of the last hour and the
        tokens held through one (24 h); empty while the flag pre_shill is off."""
        from kol import preshill
        return preshill.kandidati_view(now)

    def insider_rows(self, now):
        """[{"token", "ts", "wallets", "mcap_usd"}]: kol.insiders.mcp_candidates(now) when the module has it (the
        insiders work, merged later), else 2+ insider wallets (snipers out) bought within the hour, no call yet."""
        from kol import insiders, store as kstore
        fn = getattr(insiders, "mcp_candidates", None)
        if callable(fn):
            rows = fn(now)
            rows = rows.get("candidates", []) if isinstance(rows, dict) else rows
            return [r for r in rows or [] if isinstance(r, dict) and r.get("token")]
        good = set(insiders.good_set())
        try:   # 10.11. (kol/precall.py, merged the same night): the confirmed pre-call insiders count too
            from kol import precall
            good |= {w for w, _s in precall.copy_set()}
        except Exception:  # noqa: BLE001 - no precall data yet
            pass
        good = sorted(good)
        if not good:
            return []
        hc = _ro(_hype_db())
        by = {}
        try:
            for w, m, ts in _q(hc, f"SELECT wallet, mint, MIN(ts) FROM chain_trades WHERE side='buy' AND ts >= ? AND "
                                   f"wallet IN ({_in(good)}) GROUP BY wallet, mint", (int(now) - WINDOW_S, *good)):
                by.setdefault(m, {})[w] = int(ts)
        finally:
            if hc is not None:
                hc.close()
        by = {m: ws for m, ws in by.items() if len(ws) >= 2}
        if not by:
            return []
        kc = kstore.ro()
        try:
            called = {t for (t,) in _q(kc, f"SELECT DISTINCT token FROM calls WHERE kind='call' AND token IN ({_in(by)})",
                                        list(by))}
        finally:
            if kc is not None:
                kc.close()
        return [{"token": m, "ts": sorted(ws.values())[1], "wallets": sorted(ws, key=ws.get)} for m, ws in by.items()
                if m not in called]

    def live(self, tokens):
        """{token: market} from DexScreener for every token (batches of 30); raises when the request failed, so the
        build says why ("market fetch failed: ...") instead of a $0 row."""
        from ui import prijedlog
        out = prijedlog.live_market(list(tokens)[:MAX_TOKENS])
        if out is None:
            raise RuntimeError("DexScreener nije odgovorio")
        return out

    def range_market(self, tokens, now):
        """{token: market} from rangedca's own snapshots (range.db snaps, the same DexScreener pairs the range pass reads
        every minute): the newest row per token not older than RANGE_STALE_S, with its "ts"."""
        from rangedca import data as rdata
        p = rdata.db_path()
        tokens = list(tokens)
        if not tokens or not os.path.exists(p):
            return {}
        con = sqlite3.connect(f"file:{p}?mode=ro", uri=True, timeout=5)
        out = {}
        try:
            for i in range(0, len(tokens), 400):
                part = tokens[i:i + 400]
                q = ",".join("?" * len(part))
                for t, ts, price, mcap, liq, vm5, vh1, b5, s5, ch5 in con.execute(
                        f"SELECT token, ts, price, mcap, liq, vol_m5, vol_h1, buys_m5, sells_m5, ch_m5 FROM snaps s "
                        f"WHERE token IN ({q}) AND ts >= ? AND ts = (SELECT MAX(ts) FROM snaps WHERE token = s.token)",
                        (*part, int(now) - RANGE_STALE_S)):
                    if price and mcap:
                        out[t] = {"price": price, "mcap": mcap, "liq": liq, "vol_m5": vm5, "vol_h1": vh1,
                                  "buys_m5": b5, "sells_m5": s5, "ch_m5": ch5, "ts": ts}
        finally:
            con.close()
        return out

    def x_latest(self, tokens, now):
        from scan import xmom
        return xmom.latest(list(tokens), since=now - 6 * 3600, now=now)

    def grok_rows(self, tokens, now):
        """{token: [{"ts_observed", "ts_asof", "features", "source"}]} of Grok's live X rows received in the last
        GROK_FRESH_S (any features: they answer an x_check task even when they carry no momentum key)."""
        from ui import xfeat
        con = xfeat.ro()
        out = {}
        if con is None or not tokens:
            return out
        try:
            for subj, obs, asof, f, src in _q(con, f"SELECT subject, ts_observed, ts_asof, features, source FROM x_features "
                                                    f"WHERE subject_kind='token' AND subject IN ({_in(tokens)}) AND "
                                                    f"source LIKE 'mcp:%' AND backfill=0 AND ts_observed >= ? "
                                                    f"ORDER BY ts_observed, id", (*tokens, int(now) - GROK_FRESH_S)):
                try:
                    feats = json.loads(f)
                except ValueError:
                    feats = {}
                out.setdefault(subj, []).append({"ts_observed": obs, "ts_asof": asof, "features": feats, "source": src})
        finally:
            con.close()
        return out

    def _tcon(self):
        from trade import settings
        return _ro(self.trade_db or settings.DB)

    def opinions(self, tokens, now, since_s=GROK_FRESH_S):
        """{token: [{"ts", "verdict", "confidence", "interpretation"}]} of submit_signal_opinion notes, oldest first."""
        tc = self._tcon()
        out = {}
        if tc is None or not tokens:
            return out
        try:
            for tok, ts, v, c, txt in _q(tc, f"SELECT token, ts, verdict, confidence, interpretation FROM assistant_notes "
                                             f"WHERE kind='signal_opinion' AND token IN ({_in(tokens)}) AND ts >= ? "
                                             f"ORDER BY ts, id", (*tokens, int(now) - since_s)):
                out.setdefault(tok, []).append({"ts": ts, "verdict": v, "confidence": c,
                                                "interpretation": (txt or "")[:300]})
        finally:
            tc.close()
        return out

    def labels(self):
        """(group ids with a group_label note, tokens / wallets with an insider_label note), any status."""
        tc = self._tcon()
        gids, ins = set(), set()
        try:
            for (pc,) in _q(tc, "SELECT proposed_change FROM assistant_notes WHERE kind='suggestion' AND "
                                "(proposed_change LIKE '%group_label%' OR proposed_change LIKE '%insider_label%')"):
                try:
                    d = json.loads(pc) or {}
                except ValueError:
                    continue
                gl, il = d.get("group_label"), d.get("insider_label")
                if isinstance(gl, dict) and gl.get("group_id"):
                    gids.add(str(gl["group_id"]))
                if isinstance(il, dict):
                    for k in ("token", "wallet"):
                        if il.get(k):
                            ins.add(str(il[k]))
                    ins |= {str(w) for w in il.get("wallets") or [] if w}
        finally:
            if tc is not None:
                tc.close()
        return gids, ins

    def limits(self):
        """{"grok_max_sol_per_trade", "sl_default"} from trade settings (defaults when unreadable)."""
        from ui import grokauto
        tc = self._tcon()
        try:
            if tc is None:
                return {"grok_max_sol_per_trade": grokauto.LIMITS["grok_max_sol_per_trade"][0], "sl_default": 30.0}
            lim = grokauto.limits(tc)
            from trade import settings
            sl = _f(settings.raw(tc).get("sl_default"))
            return {"grok_max_sol_per_trade": lim["grok_max_sol_per_trade"], "sl_default": sl or 30.0}
        finally:
            if tc is not None:
                tc.close()

    def known_handles(self):
        """Scored callers of kol.db (lower case, no bots): a handle Grok names is checked against these."""
        from kol import store as kstore
        kc = kstore.ro()
        try:
            return {h.lower() for (h,) in _q(kc, "SELECT handle FROM kols WHERE COALESCE(score, 0) > 0 AND "
                                                 "COALESCE(bot, 0) = 0")}
        finally:
            if kc is not None:
                kc.close()

    def first_calls(self, tokens, now):
        """{token: (ts, mcap0)} of the token's first call of the last 24 h (kol.db)."""
        from kol import store as kstore
        kc = kstore.ro()
        try:
            return {t: (ts, mc) for t, ts, mc in _q(kc, f"SELECT token, MIN(ts), mcap0 FROM calls WHERE token IN "
                                                       f"({_in(tokens)}) AND kind='call' AND ts >= ? GROUP BY token",
                                                   (*tokens, int(now) - 86400))} if tokens else {}
        finally:
            if kc is not None:
                kc.close()

    def caller_records(self, handles, now):
        return caller_records(handles, now)

    def records(self, now):
        return source_records(now)

    def rug_tables(self):
        from scan import filters
        return filters.rug_tables()

    def archived(self):
        """11.11.: {token: "rug" | "dump"} (rugfilter/archive.kinds: a "srusen" row without the pool pulled is a dump
        after a pump, no longer a hard block)."""
        from rugfilter import archive
        return archive.kinds()

    def collapse(self, token, mcap, liq):
        """11.11.: the rug or the dump after a pump (league/copy._collapse, rugfilter/collapse.assess)."""
        from league import copy as lcopy
        return lcopy._collapse(token, mcap, liq)

    def concentration(self, token):
        from league import copy as lcopy
        return lcopy._concentration(token)

    def shillers(self):
        """11.11.: the owner's paid shillers (kol/shillers.json), lowercased kol.db handles."""
        from kol import shillers
        return shillers.handles()

    def tpsl(self, handles):
        from kol import tpsl
        return tpsl.for_handles(handles)

    def fast_verdicts(self, tokens, now):
        """11.11. (fast/live): {token: the fast_check verdict of the last 15 min} (fast.db read-only, {} without it)."""
        from fast import live
        return live.lookup(tokens, now)


# ---------- measured records ----------------------------------------------------------------------------------------

def caller_records(handles, now, days=30, kol_db=None, minute_db=None):
    """{handle: record} of each account, the get_caller_leaderboard rule on the account's own rows (indexed by handle):
    one call per token (its first, last `days`), the 1 h result after the 2 % cost (minute.db r60 when the minute check
    measured it, else kol.db r1h; under-30k calls without a minute row out), n / mean / ev_lower (mean - 2 standard
    errors); hit10 = +10 % before -20 % within 60 min and stop_first from the minute check; the Influenceri verdict
    (ui/kolsummary.verdict) from its last 14 days."""
    from kol import minute, store as kstore
    from ui import kolsummary
    hs = sorted({h for h in handles if h})
    out = {}
    if not hs:
        return out
    since, since14 = int(now) - days * 86400, int(now) - 14 * 86400
    kc, mc = kstore.ro(kol_db), minute.ro(minute_db)
    try:
        bad = ""
        if mc is not None and "bad" in {r[1] for r in _q(mc, "PRAGMA table_info(call_path)")}:
            bad = " AND bad IS NULL"
        for h in hs:
            calls = _q(kc, "SELECT token, MIN(ts), r1h, r24h, mcap0 FROM calls WHERE handle=? AND kind='call' AND ts >= ? "
                           "GROUP BY token", (h, since))
            mins = {t: (ts, r60, t10, sl) for t, ts, r60, t10, sl in _q(
                mc, f"SELECT token, MIN(ts), r60, t10, sl_min FROM call_path WHERE handle=? AND ts >= ? AND entry IS NOT "
                    f"NULL{bad} GROUP BY token", (h, since))}
            ev = []
            for tok, _ts, r1h, _r24, mcap0 in calls:
                m = mins.get(tok)
                if m is None and mcap0 is not None and mcap0 < MIN_MCAP:
                    continue
                r = m[1] if m and m[1] is not None else r1h
                if r is not None:
                    ev.append(r - _tcost.FEE_ROUND_TRIP)   # the cost model's fee part (trade/cost)
            n = len(ev)
            mean = sum(ev) / n if n else None
            lo = None
            if n >= 2:
                sd = math.sqrt(sum((x - mean) ** 2 for x in ev) / (n - 1))
                lo = mean - 2 * sd / math.sqrt(n)
            mm = list(mins.values())
            hits = [m for m in mm if m[2] is not None and (m[3] is None or m[2] < m[3])]
            stops = [m for m in mm if m[3] is not None and m not in hits]
            m14 = [m for m in mm if m[0] >= since14]
            h14 = sum(1 for m in m14 if m[2] is not None and (m[3] is None or m[2] < m[3]))
            c14 = [c for c in calls if c[1] >= since14 and (c[4] is None or c[4] >= MIN_MCAP)]
            n24 = [c for c in c14 if c[3] is not None]
            d24 = (sum(1 for c in n24 if c[3] > 0) / len(n24)) if len(n24) >= kolsummary.VERDICT_MIN_N else None
            key, word, _s = kolsummary.verdict(h14 / len(m14) if m14 else None, d24, len(m14))
            out[h] = {"ev_n": n, "ev_mean": round(mean, 4) if mean is not None else None,
                      "ev_lower": round(lo, 4) if lo is not None else None, "minute_n": len(mm),
                      "hit10": round(len(hits) / len(mm), 3) if mm else None,
                      "stop_first": round(len(stops) / len(mm), 3) if mm else None, "verdict": key, "verdict_hr": word}
    finally:
        for c in (kc, mc):
            if c is not None:
                c.close()
    return out


def source_records(now, scan_con=None):
    """{kind: {"n", "hit1h", "hit4h", "sl_first", "ev", "window_days", "from"}} measured so far: scan.db shadow
    (tradeable rows, the gate window) for caller / wallet / scan / beta / kandidati / grok_override; group_signals
    (30 days, measured) for hidden_group and caller_group_first (sl_first: the stop came first, ev = -30 % - cost);
    the range paper rounds; None for a kind nothing measures yet (tool, insider)."""
    out = {k: None for k in ("caller", "wallet", "scan", "beta", "hidden_group", "caller_group_first", "range", "tool",
                             "insider", "kandidati", "grok_override", "momentum", "event")}
    try:
        from scan import shadow, store
        cfg = store.config()
        con = scan_con or store.ro()
        if con is not None:
            try:
                for r in shadow.stats(con, cfg, int(now) - int(cfg["gate_days"]) * 86400, now):
                    if r["source"] in out:
                        out[r["source"]] = {"n": r["n"], "hit1h": r["hit1h"], "hit4h": r["hit4h"],
                                            "sl_first": r["sl_first"], "ev": r["ev"], "window_days": cfg["gate_days"],
                                            "from": "scan.db shadow (+20 % / -30 %, 4 h, 2 % cost)"}
            finally:
                if scan_con is None:
                    con.close()
    except Exception:  # noqa: BLE001 - a record that cannot be read is unknown, never a guess
        pass
    try:
        from kol import groupdisc
        c = groupdisc.config()
        ec = _ro(groupdisc.db_path())
        try:
            by = {}
            for src, h1, h4, ev in _q(ec, "SELECT source, hit1h, hit4h, ev FROM group_signals WHERE ts >= ? AND "
                                          "measured_ts IS NOT NULL AND ev IS NOT NULL", (int(now) - 30 * 86400,)):
                by.setdefault(src, []).append((h1 or 0, h4 or 0, ev))
        finally:
            if ec is not None:
                ec.close()
        stop = c["sl"] - c["cost"] + 1e-6
        for src, xs in by.items():
            if src in out:
                n = len(xs)
                out[src] = {"n": n, "hit1h": round(sum(x[0] for x in xs) / n, 3), "hit4h": round(sum(x[1] for x in xs) / n, 3),
                            "sl_first": round(sum(1 for x in xs if x[2] <= stop) / n, 3),
                            "ev": round(sum(x[2] for x in xs) / n, 4), "window_days": 30,
                            "from": "early.db group_signals (+20 % before -30 %, 4 h, cost)"}
    except Exception:  # noqa: BLE001
        pass
    try:
        from rangedca import gate
        p = gate.proof()
        out["range"] = {"n": p["n"], "hit1h": None, "hit4h": None, "sl_first": None,
                        "ev": round(p["ev_pct"] / 100, 4) if p.get("ev_pct") is not None else None,
                        "wins": p["wins"], "from": "range.db closed paper rounds (EV per round)"}
    except Exception:  # noqa: BLE001
        pass
    try:   # 11.11.: the momentum base rate (every signal, traded or not; EV of the exit rules after cost)
        from momentum import view
        rec = view.record(now)
        out["momentum"] = rec if rec["n"] else None
    except Exception:  # noqa: BLE001
        pass
    return out


def _ev_part(rec):
    """A record's EV pulled toward 0 by SHRINK_N pseudo-outcomes and capped at +-EV_CAP (0 without one)."""
    if not rec or rec.get("ev") is None or not rec.get("n"):
        return 0.0
    n = rec["n"]
    return max(-EV_CAP, min(EV_CAP, rec["ev"] * n / (n + SHRINK_N)))


# ---------- rug, Grok evidence, run-up --------------------------------------------------------------------------------

def rug_view(token, mcap, liq, src, tables, archived=frozenset(), scan_row=None):
    """{"level": ok | unknown | oprez | risk | hard, "hard": [...], "risk": [...], "warn": [...], "rug_filter",
    "topcheck", "dump"}: hard = never overridden (collapse, archive, mint / freeze, RugCheck rugged, honeypot), risk = a
    rating (see the module text). 11.11. (owner's rug rule, rugfilter/collapse): a collapse of kind "dump" (70 %+ under
    the peak without the pool pulled, the dev / a top holder selling or a high rug risk) and an archive row read as a
    dump are no block: "dump" carries the line (a P x 0.7 modifier, trade/edge); with the rug filter's high risk it is
    a rug. archived: a set (every token in it a rug, as before) or {token: "rug" | "dump"} (rugfilter/archive.kinds)."""
    from scan import filters
    tc, rug = tables
    hard, risk, warn = [], [], []
    dump = None
    ak = archived.get(token) if isinstance(archived, dict) else ("rug" if token in archived else None)
    if ak == "rug":
        hard.append("token je u arhivi rugova (izvučena likvidnost ili rug mehanika)")
    elif ak:
        dump = "dump nakon pumpe: u arhivi kao srušen, ali bez izvlačenja likvidnosti"
    try:
        col = src.collapse(token, mcap, liq)
    except Exception:  # noqa: BLE001
        col = None
    if col and (col.get("kind") or "rug") == "rug":
        hard.append(f"rugan: {col.get('text') or 'kolaps'}")
    elif col:
        dump = col.get("text") or "dump nakon pumpe"
    t = (tc or {}).get(token) or {}
    checks = ((t.get("safety") or {}).get("checks") or {}) if isinstance(t.get("safety"), dict) else {}
    for k in ("rugcheck", "mint", "freeze", "honeypot"):
        st = checks.get(k)
        if isinstance(st, (list, tuple)) and len(st) >= 2 and st[0] == "fail":
            hard.append(str(st[1]))
    r = (rug or {}).get(token) or {}
    data = r.get("data") or {}
    if isinstance(data, str):
        try:
            data = json.loads(data) or {}
        except ValueError:
            data = {}
    for h in data.get("hard_fails") or []:
        if any(str(h).startswith(m) for m in HARD_MECHANICS):
            hard.append(f"rug filter: {h}")
    sw = (scan_row or {}).get("why") or ""
    if sw.startswith(("mint ovlast", "freeze ovlast")):
        hard.append(sw)
    try:
        why_c, _shown = src.concentration(token)
    except Exception:  # noqa: BLE001
        why_c = None
    if why_c:
        risk.append(why_c)
    rf = filters.rug_filter_why(token, rug)
    if rf:
        risk.append(rf)
    if filters.is_rug_risk(sw):
        risk.append(sw)
    if dump and rf:   # 11.11.: a crash with the rug filter's high risk is a rug (owner's rule)
        hard.append(f"rugan: {dump.replace('dump nakon pumpe: ', '')}; {rf}")
        dump = None
    if r.get("verdict") == "OPREZ":
        flags = data.get("flags") or []
        warn.append("rug filter: oprez" + (f" ({flags[0]})" if flags else ""))
    if t.get("verdict") == "oprez":
        warn.append("topcheck: oprez")
    if dump:
        warn.append(f"{dump} (nije blok, P × 0,7)")
    risk = [x for i, x in enumerate(risk) if x not in risk[:i] and x not in hard]
    level = "hard" if hard else "risk" if risk else "oprez" if warn else "ok" if (r or t) else "unknown"
    return {"level": level, "hard": hard, "risk": risk, "warn": warn, "rug_filter": r.get("verdict"),
            "rug_filter_score": r.get("score"), "topcheck": t.get("verdict"), "dump": dump if not hard else None}


def grok_evidence(rows, opinions, known, now):
    """Grok's fresh evidence on one token -> {"for": [...], "against": [...], "strength", "newest"} or None when
    there is none. x rows: for = names known callers or large accounts, or growing organic momentum (score > 0 or
    x_early); against = momentum <= 0 with nobody named. Opinions: kupi / dobar for, preskoči / loš against."""
    from scan import xmom
    pro, con = [], []
    for row in rows or []:
        f = row.get("features") or {}
        g = xmom._grok(row.get("ts_asof"), json.dumps(f)) or {}
        named = _names(f.get("known_callers"))
        verified = [h for h in named if h in known]
        large = _names(f.get("large_accounts"))
        sc, early = g.get("x_momentum_score"), g.get("x_early")
        e = {"kind": "x", "ts": row.get("ts_observed"), "age_min": round((now - (row.get("ts_observed") or now)) / 60, 1),
             "known_callers": named[:10], "verified_known_callers": verified[:10], "large_accounts": large[:10],
             "x_momentum_score": sc, "x_early": early, "posts_60m": g.get("posts60"),
             "unique_authors_15m": g.get("authors15"), "note": str(f.get("note") or "")[:200] or None}
        if named or large or (sc is not None and sc > 0) or early is True:
            pro.append(e)
        elif sc is not None or early is False:
            con.append(e)
    for o in opinions or []:
        e = {"kind": "opinion", "ts": o.get("ts"), "age_min": round((now - (o.get("ts") or now)) / 60, 1),
             "verdict": o.get("verdict"), "confidence": o.get("confidence"), "note": o.get("interpretation")}
        if o.get("verdict") in POSITIVE:
            pro.append(e)
        elif o.get("verdict") in NEGATIVE:
            con.append(e)
    if not pro and not con:
        return None
    newest = max(pro + con, key=lambda e: e.get("ts") or 0)
    strong = any(e.get("verified_known_callers") or e.get("large_accounts") for e in pro) or \
        any(e["kind"] == "opinion" and (e.get("confidence") or 0) >= 0.7 for e in pro)
    return {"for": pro, "against": con, "strength": "jak" if strong else "slab",
            "newest": "for" if newest in pro else "against"}


def override_of(ev, rug):
    """The grok_override of a row whose only blocker is a rug RISK rating, or None (no evidence, the newest piece is
    against, or a hard rug)."""
    if rug["level"] != "risk" or not ev or not ev["for"] or ev["newest"] != "for":
        return None
    first = ev["for"][-1]
    named = first.get("verified_known_callers") or first.get("known_callers") or first.get("large_accounts") or []
    how = ("Grokov X: " + ", ".join("@" + h for h in named[:3]) if named else
           f"Grokovo mišljenje: {first.get('verdict')}" if first["kind"] == "opinion" else
           f"Grokov X: zamah {first.get('x_momentum_score')}")
    return {"active": True, "rug_warning": "; ".join(rug["risk"]), "strength": ev["strength"],
            "reason": (f"rug ocjena kaže rizik ({rug['risk'][0]}), ali Grok ima svjež dokaz ({how}, prije "
                       f"{first.get('age_min')} min): kupuje se samo pola uloga, uski stop; kolaps se nikad ne nadjačava"),
            "evidence": ev["for"][-3:], "against": ev["against"][-2:]}


def override_now(token, now=None, src=None):
    """Grok's fresh evidence FOR the token right now (grok_evidence with "for" newest), or None: what execute_trade
    (ui/grokauto.execute) asks before it lets a rug risk rating pass at half size."""
    S = src or Sources()
    now = int(now or time.time())
    try:
        known = S.known_handles()
    except Exception:  # noqa: BLE001
        known = set()
    ge = grok_evidence(S.grok_rows([token], now).get(token), S.opinions([token], now).get(token), known, now)
    return ge if ge and ge["for"] and ge["newest"] == "for" else None


def runup(m, first_mcap):
    """{"x", "from", "mcap_at_first_signal", "change_24h_pct", "chase"}: market cap now over the first signal's
    (else 1 + the 1 h change), and chase in 0..1 (see the module text)."""
    mc = _f((m or {}).get("mcap"))
    ch1, ch24 = _f((m or {}).get("ch_h1")), _f((m or {}).get("ch_h24"))
    if mc and first_mcap and first_mcap > 0:
        x, how = mc / first_mcap, "MC prvog signala"
    elif ch1 is not None:
        x, how = 1 + ch1 / 100, "promjena 1 h (MC prvog signala nepoznat)"
    else:
        x, how = None, "nepoznato"
    chase = max(0.0, min(1.0, math.log2(x) / 2)) if x and x > 0 else 0.0
    if ch24 is not None and ch24 > -100:
        p24 = 1 + ch24 / 100
        chase = max(chase, max(0.0, min(1.0, (math.log2(p24) - 2) / 3)))
    return {"x": round(x, 2) if x else None, "from": how, "mcap_at_first_signal": round(first_mcap) if first_mcap else None,
            "change_24h_pct": ch24, "chase": round(chase, 3)}


# ---------- the build ----------------------------------------------------------------------------------------------------

def _market(m, ts=None, how="dexscreener"):
    from ui import mcpapi
    row = mcpapi._market_row(m) if m else None
    if row is not None:
        row["source"] = how
        if ts:
            row["ts"] = int(ts)
    return row


def build(now=None, src=None, details=True, extra=None, raw=False):
    """(rows ranked, meta). details=False skips the per-row caller records' exit plans (the scanner's shadow log
    needs only the ranking).
    11.11. (proposals/, flag proposals G21: one scoring system, not two): extra = [{"token", "kind", "symbol", "ts",
    "mcap"}] adds tokens of sources only the proposals pass knows (range entries, event tokens, Grok's proposals) as
    their own source kind, so they get the same market, rug, run-up and block checks; raw=True keeps each row's
    DexScreener reading ("live_raw") and the structured blocks ("blocks": [{"key", "text"}], the same lines as
    why_not), and puts the rug tables and the caller crews into meta. The MCP answer (candidates) passes neither."""
    now = int(now or time.time())
    S = src or Sources()
    failed = []

    def safe(name, fn, default):
        try:
            return fn()
        except Exception as e:  # noqa: BLE001 - one broken source never hides the others
            failed.append(f"{name}: {type(e).__name__}")
            return default

    rows = {}

    def row(tok, sym=None):
        r = rows.setdefault(tok, {"token": tok, "symbol": None, "sources": {}, "sig": [], "count": {}, "live": None,
                                  "scan_row": None})
        if sym and not r["symbol"]:
            r["symbol"] = sym
        return r

    member, glist = safe("groups", S.groups, ({}, {}))
    gsig = safe("group_signals", lambda: S.group_signals(now), [])
    # 11.11. (kol/preshill.py, flag pre_shill): a shill-network call is exit liquidity (-1); a token held through a
    # pre_shill signal gets the network's call as its exit; the pre_shill signals of the hour are a source
    ps = safe("pre_shill", lambda: getattr(S, "pre_shill", lambda _n: {})(now), {}) or {}
    shill_of, held = ps.get("members") or {}, ps.get("held") or {}
    crew_first = {}
    for ts, s, gid, tok, who, mc in gsig:
        if s == "caller_group_first":
            crew_first.setdefault(tok, (ts, gid, who, mc))
    # callers
    handles, lives = set(), {}
    for tok, callers, first, last, sym, live in safe("caller", lambda: S.callers(now), []):
        calls = [(int(ts), w) for w, p, ts in callers if p in ("x", "tg")]
        if live:
            lives[tok] = live   # a followed wallet's buy is the wallet source below; its live check is reused
        if not calls:
            continue
        r = row(tok, sym)
        from kol import groupdisc
        sigs = groupdisc.dedupe(calls, member, CREW_S)
        crews, n, shill = [], 0, []
        for s in sigs:
            sh = [h for h in s["handles"] if h in shill_of]
            if sh:   # the paid shill network: its call is the exit liquidity of the ones who bought before it
                shill += sh
                r["shill_n"] = r.get("shill_n", 0) + 1   # counts 0 in the confluence and -1 in the score
                if s["gid"]:
                    kind, grade, _m, met = glist.get(s["gid"], ("caller", None, [], {}))
                    crews.append({"group_id": s["gid"], "handles": s["handles"], "grade": grade,
                                  "n_measured": groupdisc.n_measured_of(kind, met), "shill_network": True})
            elif s["gid"]:
                kind, grade, _m, met = glist.get(s["gid"], ("caller", None, [], {}))
                crews.append({"group_id": s["gid"], "handles": s["handles"], "grade": grade,
                              "n_measured": groupdisc.n_measured_of(kind, met)})
                n += 0 if grade == "exit_liquidity" else 1
            else:
                n += 1
        handles |= {w for _ts, w in calls}
        ev = {"n_callers": len({w for _t, w in calls}), "signals": len(sigs), "crews": crews,
              "first_ts": min(t for t, _w in calls), "last_ts": max(t for t, _w in calls),
              "callers": [{"who": w, "platform": p, "ts": int(ts)} for w, p, ts in callers if p in ("x", "tg")][:8]}
        if tok in crew_first:
            ts, gid, who, mc = crew_first[tok]
            ev["crew_first"] = {"group_id": gid, "ts": int(ts), "who": who, "mcap_usd": mc}
        if shill:
            ev["shill_network"] = {"handles": sorted(set(shill))[:8], "weight": -1,
                                   "note": "plaćena shill mreža: njen poziv je izlazna likvidnost (sjena)"}
            if tok in held:
                ev["exit_signal"] = {"action": "sell_into_calls", "pre_shill_signal_ts": int(held[tok]),
                                     "note": "drži se preko signala kupaca prije shill mreže: prodaj u val callova (sjena)"}
        r["sources"]["caller"] = ev
        r["count"]["caller"] = n
        r["sig"].append((ev["first_ts"], None, "caller"))
    # followed and tiered wallets
    wb = {}
    for w, m, ts, tier in safe("wallet", lambda: S.wallet_buys(now), []):
        wb.setdefault(m, []).append((ts, w, tier))
    for tok, xs in wb.items():
        xs.sort()
        r = row(tok)
        r["sources"]["wallet"] = {"n_wallets": len({w for _t, w, _x in xs}), "first_ts": xs[0][0],
                                  "wallets": [{"wallet": w, "tier": t, "ts": ts} for ts, w, t in xs[:6]]}
        r["count"]["wallet"] = 1
        r["sig"].append((xs[0][0], None, "wallet"))
    # scanner
    from scan import filters
    for tok, sr in safe("scan", lambda: S.scan_rows(now), {}).items():
        passed = bool(sr.get("passed"))
        rug_only = not passed and filters.is_rug_risk(sr.get("why"))
        in_shadow = "scan" in (sr.get("sources") or [])
        beta = "beta" in (sr.get("sources") or []) and (sr.get("beta_score") or 0) >= 0.6
        if not (passed or rug_only or in_shadow or beta or tok in rows):
            continue   # a caller / wallet signal the scanner only checked: its numbers ride along, it is no source
        r = row(tok, sr.get("symbol"))
        r["scan_row"] = sr
        if passed or rug_only or in_shadow:
            r["sources"]["scan"] = {"passed": passed, "why_now": sr.get("why"), "stage": sr.get("stage"),
                                    "pass_reasons": (sr.get("reasons") or [])[:6], "fees_paid_sol": sr.get("fees_paid_sol"),
                                    "holders": sr.get("holders"), "top10_pct": sr.get("top10_pct"),
                                    "lead_time_min": sr.get("lead_time_min"),
                                    "first_pass_ts": sr.get("first_pass_ts"), "checked_ts": sr.get("checked_ts")}
            r["count"]["scan"] = 1
            r["sig"].append((sr.get("first_pass_ts") or sr.get("checked_ts"), None, "scan"))
        if beta:
            r["sources"]["beta"] = {"beta_score": sr.get("beta_score"), "beta_parent": sr.get("beta_parent")}
            r["count"]["beta"] = 1
            r["sig"].append((sr.get("checked_ts"), None, "beta"))
    # hidden wallet lists
    for ts, s, gid, tok, who, mc in gsig:
        if s != "hidden_group":
            continue
        kind, grade, _m, met = glist.get(gid, ("wallet", None, [], {}))
        r = row(tok)
        from kol import groupdisc
        r["sources"]["hidden_group"] = {"group_id": gid, "grade": grade, "n_measured": groupdisc.n_measured_of(kind, met),
                                        "ts": int(ts), "mcap_usd": mc,
                                        "wallets": (who or "").split(",")[:8]}
        r["count"]["hidden_group"] = 1
        r["sig"].append((int(ts), mc, "hidden_group"))
    # 11.11. (kol/preshill.py, flag pre_shill): 2+ wallets that buy before the paid shill network bought, no call yet
    for ts, tok, wallets, mc in ps.get("signals") or []:
        r = row(tok)
        r["sources"]["pre_shill"] = {"ts": int(ts), "wallets": list(wallets)[:8], "mcap_usd": mc,
                                     "note": "kupci prije shill mreže (sjena); poziv mreže je znak za izlaz"}
        r["count"]["pre_shill"] = 1
        r["sig"].append((int(ts), mc, "pre_shill"))
    # ranges
    for tok, rg in safe("range", lambda: S.ranges(now), {}).items():
        r = row(tok, rg.get("symbol"))
        z = rg.get("zones") or {}
        srcs = rg.get("sources") or [rg.get("source") or "signal"]
        r["sources"]["range"] = {"range_score": rg.get("score"), "position_in_range_pct": rg.get("pos_pct"),
                                 "recoveries": rg.get("recoveries"), "zones_mc": z.get("mc"), "computed_ts": rg.get("ts"),
                                 "watch_source": "signal" if "signal" in srcs else "event" if "event" in srcs
                                 else "missed" if "missed" in srcs else "market"}   # 11.11.: range_missed (G27)
        r["range"] = z
        r["count"]["range"] = 1
    # 11.11. (topics/, flag event_tokens): the tokens of Grok's active event topics
    for e in safe("event", lambda: getattr(S, "events", lambda _n: [])(now), []) or []:
        r = row(e["token"], e.get("symbol"))
        ev = r["sources"].setdefault("event", {"topics": []})
        ev["topics"].append({k: e.get(k) for k in ("topic_id", "topic", "role", "event_ts", "buzz_score", "buzz_trend")})
        r["count"]["event"] = 1
        if e.get("first_seen"):
            r["sig"].append((int(e["first_seen"]), None, "event"))
    # 11.11. momentum_scalp signals (momentum/): every entry rule met in the last 15 min
    for t in safe("momentum", lambda: S.momentum(now), []):
        r = row(t["token"], t.get("symbol"))
        r["sources"]["momentum"] = {k: t.get(k) for k in ("signal_id", "ts", "mcap_usd", "change_5m_pct", "volume_x",
                                                           "buy_share_5m", "unique_buyers_5m")}
        r["count"]["momentum"] = 1
        r["sig"].append((int(t["ts"]), t.get("mcap_usd"), "momentum"))
    # the live list's own sources
    for t in safe("tool", lambda: S.tool_rows(now), []):
        r = row(t["token"], t.get("symbol"))
        ev = r["sources"].setdefault("tool", {"from": []})
        ev["from"].append({k: t.get(k) for k in ("src", "rank", "conf", "ts0", "mcap0") if t.get(k) is not None})
        r["count"]["tool"] = 1
        if t.get("ts0"):
            r["sig"].append((int(t["ts0"]), t.get("mcap0"), "tool"))
    # insiders
    for t in safe("insider", lambda: S.insider_rows(now), []):
        r = row(t["token"])
        r["sources"]["insider"] = {"wallets": list(t.get("wallets") or [])[:8], "ts": t.get("ts"),
                                   "mcap_usd": t.get("mcap_usd")}
        r["count"]["insider"] = 1
        if t.get("ts"):
            r["sig"].append((int(t["ts"]), t.get("mcap_usd"), "insider"))
    # 11.11. (proposals/): the proposals pass's own sources, each its own kind (never passed by the MCP answer)
    for t in extra or []:
        if not isinstance(t, dict) or not t.get("token") or not t.get("kind") or t["kind"] in rows.get(t["token"], {}).get(
                "sources", {}):
            continue
        r = row(t["token"], t.get("symbol"))
        r["sources"][t["kind"]] = {k: t.get(k) for k in ("ts", "mcap") if t.get(k) is not None}
        r["count"][t["kind"]] = 1
        if t.get("ts"):
            r["sig"].append((int(t["ts"]), t.get("mcap"), t["kind"]))
    if not rows:
        return [], {"sources_failed": failed, "records": {}}
    # market now (11.11.: every row gets a reading or the reason it has none, never a $0 row): the callers' live
    # check first; rangedca's own snapshot when fresh (the same DexScreener pairs the range pass reads each minute);
    # one DexScreener read for the rest, in batches of 30, up to MAX_TOKENS; else rangedca's older snapshot, the
    # scanner's numbers, or the reason
    toks = list(rows)
    need = [t for t in toks if not rows[t]["live"] and t not in lives]
    rng = safe("range_market", lambda: S.range_market(need, now), {}) if need and hasattr(S, "range_market") else {}
    rng_fresh = {t for t, m in rng.items() if now - int(m.get("ts") or 0) <= RANGE_FRESH_S}
    ask = [t for t in need if t not in rng_fresh]
    dex_err = None
    try:
        lv = S.live(ask) if ask else {}
    except Exception as e:  # noqa: BLE001
        lv, dex_err = {}, f"{type(e).__name__}: {e}"[:160]
        failed.append(f"market: {type(e).__name__}")
    cut = set(ask[MAX_TOKENS:])
    msrc = {"live": 0, "range": 0, "dexscreener": 0, "range_stale": 0, "scan": 0, "none": 0}
    for t in toks:
        r = rows[t]
        r["live"] = r["live"] or lives.get(t)
        r["market_why"] = None
        if r["live"]:
            r["market"], r["m"] = _market(r["live"]), r["live"]
            r["msrc"] = "live"
        elif t in rng_fresh:
            r["market"], r["m"] = _market(rng[t], rng[t]["ts"], "range.db (rangedca, DexScreener)"), rng[t]
            r["msrc"] = "range"
        elif lv.get(t):
            r["market"], r["m"] = _market(lv[t]), lv[t]
            r["msrc"] = "dexscreener"
        elif rng.get(t):
            r["market"], r["m"] = _market(rng[t], rng[t]["ts"], "range.db (do 15 min staro)"), rng[t]
            r["msrc"] = "range_stale"
        elif r["scan_row"]:
            sr = r["scan_row"]
            m = {k: sr.get(k) for k in ("price", "mcap", "liq", "vol_h1", "ch_h1", "ch_h24")}
            r["market"], r["m"] = _market(m, sr.get("checked_ts"), "scan.db (do 10 min staro)"), m
            r["msrc"] = "scan"
        else:
            r["market"], r["m"] = None, None
            r["market_why"] = (f"market fetch failed: {dex_err}" if dex_err and t not in cut else
                               f"nije dohvaćeno: preko {MAX_TOKENS} tokena u ovom prolazu" if t in cut else
                               "DexScreener nema para za token (ni rangedca snimke u zadnjih 15 min)")
            r["msrc"] = "none"
    # drop what may not even be measured (under 10k) before the per-token reads
    rows = {t: r for t, r in rows.items() if not r["m"] or (_f(r["m"].get("mcap")) or 0) >= MEASURE_MIN_MCAP}
    for r in rows.values():   # 11.11.: counted after the under-10k drop, so the sources add up to the rows
        msrc[r.get("msrc") or "none"] += 1
    toks = list(rows)
    records = safe("records", lambda: S.records(now), {}) or {}
    crec = safe("caller_records", lambda: S.caller_records(handles, now), {}) if handles else {}
    xm = safe("x", lambda: S.x_latest(toks, now), {})
    grows = safe("grok_x", lambda: S.grok_rows(toks, now), {})
    ops = safe("opinions", lambda: S.opinions(toks, now), {})
    known = safe("known", S.known_handles, set())
    firsts = safe("first_calls", lambda: S.first_calls(toks, now), {})
    sfirst = safe("scan_first", lambda: S.scan_first(toks), {})
    archived = safe("archive", S.archived, frozenset())
    lim = safe("limits", S.limits, {"grok_max_sol_per_trade": 0.1, "sl_default": 30.0})
    # 11.11. (fast/live, Jure: "nikad 'nije izmjeren'"): the tokens' fast_check verdicts (a source without the reader,
    # e.g. a test double, has none)
    fastv = safe("fast", lambda: getattr(S, "fast_verdicts", lambda _t, _n: {})(toks, now), {}) or {}
    from league import copy as lcopy
    tables = safe("rug", S.rug_tables, ({}, {}))
    mine = None
    if lcopy._CONC_CACHE is None:   # league/copy._concentration reads the same two tables once for the whole build
        mine = lcopy._CONC_CACHE = {"tc": tables[0], "rug": tables[1]}
    try:
        out = [_finish(r, now, S, records, crec, xm, grows, ops, known, firsts, sfirst, archived, lim, tables, details,
                       raw, fastv=fastv) for r in rows.values()]
    finally:
        # the dashboard's copy loop (league/auto -> copy.run_once) sets and clears the same cache in its own thread:
        # only our own dict is taken back, never one a running pass put there
        if mine is not None and lcopy._CONC_CACHE is mine:
            lcopy._CONC_CACHE = None
    out.sort(key=rank_key)
    for i, r in enumerate(out, 1):
        r["rank"] = i
    # 11.11.: where each row's market came from, and how many trade (one line in the proposals pass log)
    meta = {"sources_failed": failed, "records": records,
            "market": {**msrc, "rows": len(out), "tradeable": sum(1 for r in out if r.get("tradeable"))}}
    if raw:   # 11.11. (proposals/): what the proposals pass checks again without a second read
        meta.update(rug_tables=tables, member=member, glist=glist, shill_members=shill_of)
    return out, meta


def rank_key(r):
    """11.11.: tradeable first, then the EV (an unmeasured EV counts as 0), then the confluence, then the score:
    confluence never outranks a better EV."""
    ev = r.get("ev_pct")
    return (not r["tradeable"], -(ev if ev is not None else 0.0), -r["confluence"], -r["score"], r["token"])


def shill_driven(srcs, S):
    """11.11.: the handles when the token's only signal is callers and every one of them is a paid shill (kol/shillers,
    the owner's list); [] otherwise."""
    if set(srcs) != {"caller"}:
        return []
    who = [c["who"] for c in srcs["caller"].get("callers") or []]
    try:
        paid = S.shillers()
    except Exception:  # noqa: BLE001 - the list unreadable: nobody counts as a shill
        return []
    return who if who and all(str(w).lower() in paid for w in who) else []


def ev_estimate(srcs, records, size_sol, liq):
    """{"ev_pct", "n_samples", "ev_confidence", "detail"}: what a trade on this row is expected to make, in % per trade.
    The measured records the row's sources rest on (the calling accounts' own records for the caller signal, else
    the caller source's shadow record; each other source kind its shadow record), n-weighted and pulled toward 0 by
    SHRINK_N pseudo-outcomes: sum(n * ev) / (sum(n) + SHRINK_N). The records are already net of the cost model's fee
    part (trade/cost.FEE_ROUND_TRIP); its calibration difference (calib_delta) and the price impact of suggested_size_sol
    in the pool, in and out (trade/cost.impact), come off on top: together trade/cost.round_trip.
    ev_pct None when no source has a measured outcome; ev_confidence low under 10 samples, medium under 30."""
    samples = []
    for k, ev in srcs.items():
        if k == "caller":
            own = [("caller:" + str(c["who"]), c["record"]["ev_n"], c["record"]["ev_mean"])
                   for c in ev.get("callers") or []
                   if (c.get("record") or {}).get("ev_n") and c["record"].get("ev_mean") is not None]
            if own:
                samples += own
                continue
        rec = records.get(k)
        if rec and rec.get("n") and rec.get("ev") is not None:
            samples.append((k, rec["n"], rec["ev"]))
    n = int(sum(x[1] for x in samples))
    if not n:
        return {"ev_pct": None, "n_samples": 0, "ev_confidence": "low", "detail": []}
    pooled = sum(x[1] * x[2] for x in samples) / (n + SHRINK_N)
    cal = _tcost.calib_delta()
    imp = 2 * _tcost.impact(size_sol * SOL_USD, liq) if liq else 0.0
    slip = cal + imp
    # 11.11. (owner: live only when the EV does not rest more than half on one source with n < 10): each source's
    # share of the positive part of the pooled EV (n x ev)
    pos = [(k, nn, max(0.0, nn * e)) for k, nn, e in samples]
    tot = sum(c for _k, _n, c in pos)
    top = max(pos, key=lambda x: x[2]) if tot > 0 else None
    return {"ev_pct": round((pooled - slip) * 100, 2), "n_samples": n,
            "top_source": ({"from": top[0], "n": int(top[1]), "share": round(top[2] / tot, 3)} if top else None),
            "ev_confidence": "low" if n < 10 else ("medium" if n < 30 else "high"),
            "detail": [{"from": k, "n": int(nn), "ev_pct": round(e * 100, 2)} for k, nn, e in samples][:10]
            + [{"from": "price_impact", "ev_pct": round(-imp * 100, 3)}]
            + ([{"from": "cost_calibration", "ev_pct": round(-cal * 100, 3)}] if cal else [])}


LIVE_EV_MIN = 3.0          # 11.11. (owner): live_eligible needs EV >= +3 % per trade after cost ...
LIVE_N_MIN = 10            # ... on at least 10 measured outcomes ...
LIVE_TOP_SHARE = 0.5       # ... and not more than half of it from one source with n < LIVE_N_MIN


def live_state(tradeable, evx, paper=False):
    """("live" | "paper" | "no", why or None). 11.11. (owner: "tradeable (EV > 0) ne znači da se smije kupiti s pravim
    novcem"): live = tradeable AND ev_pct >= LIVE_EV_MIN AND n_samples >= LIVE_N_MIN AND the EV does not rest more
    than LIVE_TOP_SHARE on one source with n < LIVE_N_MIN (and the row is not paper only); tradeable but short of that
    = "paper" (samo papir, the demo account); not tradeable = "no"."""
    if not tradeable:
        return "no", None
    ev, n = evx.get("ev_pct"), int(evx.get("n_samples") or 0)
    top = evx.get("top_source") or {}
    if paper:
        return "paper", "samo papir: izvor je samo event / tržišna lista (nikad pravi novac)"
    if ev is None or ev < LIVE_EV_MIN:
        return "paper", f"samo papir: EV {ev if ev is not None else 0:+.2f} % ispod +{LIVE_EV_MIN:g} %"
    if n < LIVE_N_MIN:
        return "paper", f"samo papir: n = {n} izmjerenih ishoda, treba {LIVE_N_MIN}"
    if top.get("n") is not None and top["n"] < LIVE_N_MIN and (top.get("share") or 0) > LIVE_TOP_SHARE:
        return "paper", (f"samo papir: {top['share']:.0%} EV-a dolazi od jednog izvora ({top['from']}) s n = {top['n']} "
                         f"(< {LIVE_N_MIN})")
    return "live", None


def prijedlog_live_min():
    """The live lists' activity floor (ui/prijedlog.LIVE_MIN: 10+ transactions and $1,000+ volume in the hour, not
    down 20 % in it)."""
    try:
        from ui import prijedlog
        return prijedlog.LIVE_MIN
    except Exception:  # noqa: BLE001
        return {"txns_h1": 10, "vol_h1": 1000.0, "max_drop_h1": -20.0}


def _record_of(kind, records):
    rec = records.get(kind)
    if not rec:
        return None
    return {k: rec.get(k) for k in ("n", "hit1h", "hit4h", "sl_first", "ev")}


def paper_only(srcs):
    """True when a row's only evidence is an event topic and / or a range the market watchlist, an event topic or the
    missed list (range_missed) brought (11.11.): measured and at most paper-traded on the demo account, never a
    real-money candidate here (a missed token reaches the real account only through range_dca past its own gate)."""
    if not srcs or not set(srcs) <= {"event", "range"}:
        return False
    return "event" in srcs or (srcs.get("range") or {}).get("watch_source") in ("market", "event", "missed")


def fast_ev(evx, fv, why_not):
    """11.11. (fast/live, Jure: "nikad 'nije izmjeren'"): a row whose sources have no measured record takes the EV of
    its token's fast_check (P from the source's record or its strategy's prior, after the cost model) when that check
    decided on the EV (KUPI, or PRESKOČI because EV <= 0); a PRESKOČI on a check (rug, holders, flow, price / MC band,
    the source leaving) is a block of its own ("fast_skip"). Returns the verdict or None."""
    if not fv:
        return None
    if fv.get("state") != "done":
        return fv
    if fv.get("decision") == "SKIP" and fv.get("key") != "ev":
        why_not.add("fast_skip", f"fast_check PRESKOČI: {fv.get('reason') or ''}".strip())
    elif evx["ev_pct"] is None and fv.get("ev_pct") is not None:
        n = int(fv.get("n") or 0)
        evx.update(ev_pct=round(float(fv["ev_pct"]), 2), n_samples=n,
                   ev_confidence="low" if n < 10 else ("medium" if n < 30 else "high"),
                   top_source={"from": "fast_check", "n": n, "share": 1.0})
        evx["detail"].append({"from": "fast_check", "ev_pct": fv["ev_pct"],
                              "ci90": [fv.get("ev_lo_pct"), fv.get("ev_hi_pct")], "p_tp": fv.get("p"), "n": n,
                              "origin": fv.get("origin"), "label": fv.get("n_label")})
    return fv


def _fast_out(fv):
    """The fast_check verdict as the MCP row carries it (None without one)."""
    if not fv:
        return None
    keep = ("state", "label", "decision", "ev_pct", "ev_lo_pct", "ev_hi_pct", "p", "p_lo", "p_hi", "n", "origin",
            "n_label", "lag_pct", "lag_txt", "reason", "kind", "source", "sig_ts", "decided_ts")
    return {k: fv.get(k) for k in keep if k in fv}


class _WhyNot(list):
    """why_not, and next to each line its key (11.11., proposals/: the proposals pass applies its own subset of the
    blocks by key, never by parsing the Croatian text)."""

    def __init__(self):
        super().__init__()
        self.keys = []

    def add(self, key, text):
        self.append(text)
        self.keys.append({"key": key, "text": text})


def _finish(r, now, S, records, crec, xm, grows, ops, known, firsts, sfirst, archived, lim, tables, details, raw=False,
            fastv=None):
    tok, m = r["token"], r["m"] or {}
    from league import copy as lcopy
    srcs = r["sources"]
    # each source's measured record; the callers' own records on the caller signal
    ev_parts = {}
    for k, ev in srcs.items():
        if k == "caller":
            recs = []
            for c in ev["callers"]:
                cr = crec.get(c["who"])
                if cr:
                    c["record"] = cr
                    if cr.get("ev_n"):
                        recs.append({"n": cr["ev_n"], "ev": cr["ev_mean"]})
            ev["record"] = _record_of("caller", records)
            ev["own_records"] = len(recs)
            ev_parts[k] = (sum(_ev_part(x) for x in recs) / len(recs)) if recs else _ev_part(records.get("caller"))
            if ev.get("crew_first"):
                ev["crew_first"]["record"] = _record_of("caller_group_first", records)
        else:
            ev["record"] = _record_of(k, records)
            ev_parts[k] = _ev_part(records.get(k))
    confluence = sum(r["count"].values())
    sigs = [s for s in r["sig"] if s[0]]
    first_ts = min((s[0] for s in sigs), default=None)
    last_ts = max((s[0] for s in sigs), default=None)
    # the first signal's market cap: the earliest of the first call (kol.db), the first shadow entry, a group signal
    cands = [(ts, mc) for ts, mc, _k in sigs if mc]
    if tok in firsts and firsts[tok][1]:
        cands.append(firsts[tok])
    if tok in sfirst and sfirst[tok][1]:
        cands.append(sfirst[tok])
    first_mc = min(cands)[1] if cands else None
    ru = runup(m, first_mc)
    mcap, liq = _f(m.get("mcap")) or 0, _f(m.get("liq"))
    sr = r["scan_row"] or {}
    curve = sr.get("stage") in ("final_stretch", "curve") or (r["m"] is not None and not liq)
    rug = rug_view(tok, mcap or None, liq, S, tables, archived, sr)
    why_not = _WhyNot()
    tags = []
    if not r["m"] or not _f(m.get("price")):
        why_not.add("market", r.get("market_why") or "nema živog tržišta (DexScreener)")
    elif mcap < MIN_MCAP:   # 11.11.: without a market reading the MC is unknown, never "$0 under 30k"
        why_not.add("under_30k", f"MC ${mcap:,.0f} ispod 30k: samo mjerenje, ne kupuje se")
    if curve:
        why_not.add("curve", "još na krivulji ili bez poola: uzimaju se samo bondani")
    elif r["m"]:   # 11.11.: without any market reading the row already says so ("market"); no pool gate on None
        c = lcopy.CFG
        if liq < max(c["min_liq"], _tcost.LIQ_HARD_MIN):   # 11.11. owner's rule B: the only liquidity block, $15k
            why_not.add("liq_low", f"premala likvidnost (${liq:,.0f}, treba ${_tcost.LIQ_HARD_MIN / 1000:.0f}k)")
        elif mcap and mcap > c["max_mcap"]:
            why_not.add("too_big", "velik token (preko $50M)")
        elif mcap and liq > mcap:
            why_not.add("fake_pool", "lažni pool (likvidnost veća od market capa)")
        elif mcap and liq < c["min_liq_mcap"] * mcap:   # 11.11. (rule B): a tag, no longer a block
            tags.append({"key": "liq_share", "text": f"likvidnost je samo {liq / mcap:.1%} MC-a (oznaka, ne blok)"})
    if r["m"]:   # it must trade NOW (ui/prijedlog.alive's activity lines; liquidity is the pool gate above)
        tx, vol, ch1 = m.get("txns_h1"), _f(m.get("vol_h1")) or 0, _f(m.get("ch_h1"))
        lv = prijedlog_live_min()
        if (tx is not None and tx < lv["txns_h1"]) or vol < max(lv["vol_h1"], _tcost.VOL_FLOOR):
            why_not.add("not_trading", f"ne trguje se sada (volumen 1 h ${vol:,.0f}" + (f", {tx} transakcija" if tx is not None else "")
                           + ")")
        elif ch1 is not None and ch1 <= lv["max_drop_h1"]:
            why_not.add("falling", f"pada: {ch1:+.0f} % u zadnjem satu")
    for h in rug["hard"]:
        why_not.add("rug_hard", f"rug (nikad se ne nadjačava): {h}")
    if paper_only(srcs):   # 11.11.: an event topic / the market watchlist alone never buys with real money
        why_not.add("paper_only", "samo event tema ili tržišna range lista: mjeri se, najviše paper na demo računu "
                    "(range_dca), nikad pravi novac")
    ge = grok_evidence(grows.get(tok), ops.get(tok), known, now)
    ov = override_of(ge, rug) if not why_not else None
    if rug["level"] == "risk" and not ov:
        why_not.add("rug_risk", f"rug ocjena: {rug['risk'][0]} (svjež Grokov dokaz s X-a može je nadjačati: get_grok_tasks)")
    shill = shill_driven(srcs, S)
    # X: Grok's row first (2 h), the scanner's own (1 h)
    x = xm.get(tok) or {}
    x_fresh = bool(x) and ((x.get("source") == "grok" and now - (x.get("ts") or 0) <= 2 * 3600)
                           or now - (x.get("ts") or 0) <= 3600)
    xs = _f(x.get("x_momentum_score")) if x_fresh else None
    # 11.11. (owner's rule B, trade/edge.modifiers): run-up 4x+ and shill-driven change P and the size, never block
    w5 = ((m.get("w") or {}).get("m5") or {})
    b5, s5 = w5.get("buys"), w5.get("sells")
    mods = _tedge.modifiers(runup_x=ru["x"], x_score=xs,
                            buy_share_5m=(b5 / (b5 + s5)) if b5 is not None and s5 is not None and b5 + s5 > 0 else None,
                            shill=bool(shill), dump=rug.get("dump"))   # 11.11.: a dump after a pump, P x 0.7
    tags += mods["tags"]
    if shill:
        tags.append({"key": "shill_driven", "text": f"vođeno shillanjem: zovu ga samo plaćeni shilleri "
                                                    f"({', '.join(shill[:3])})"})
    # 11.11. (Jure: Dacity score 2.384, ev -0.166, still tradeable): the score carries confluence, not expected profit;
    # tradeable needs a measured EV above 0 after cost and price impact, whatever the confluence
    # 11.11. (owner's rule C): the stake within Grok's limit, the 2 % slippage stake and the volume factor
    size = _tcost.size_sol(lim.get("grok_max_sol_per_trade") or 0.1, liq, SOL_USD, m.get("vol_h1"), mods["size_mult"])
    evx = ev_estimate(srcs, records, size, liq)
    if evx["ev_pct"] is not None and mods["p_mult"] < 1:   # P x m on the signal exit (trade/edge.ev_p_mult)
        e0 = evx["ev_pct"] / 100
        e1 = _tedge.ev_p_mult(e0, mods["p_mult"], _tcost.round_trip(size * SOL_USD, liq))
        evx["detail"].append({"from": "p_modifiers", "p_mult": mods["p_mult"], "ev_pct": round((e1 - e0) * 100, 2)})
        evx["ev_pct"] = round(e1 * 100, 2)
    fv = fast_ev(evx, (fastv or {}).get(tok), why_not)
    if evx["ev_pct"] is None:
        why_not.add("ev_unmeasured", "EV: izvori bez izmjerenih ishoda, " + (
            f"fast_check: {fv.get('label') or 'provjera u tijeku'}" if fv
            else "nema fast_check-a (nema kupnje praćenog novčanika, poziva ni konvergencije u 15 min)")
            + ": tradeable traži EV > 0")
    elif evx["ev_pct"] <= 0:
        why_not.add("ev_negative", f"negativan EV: {evx['ev_pct']:+.1f} % po tradeu nakon troška i slippagea "
                       f"(n={evx['n_samples']})")
    tradeable = not why_not
    fresh = 0.0
    if last_ts:
        age = (now - last_ts) / 60
        fresh = 1.0 if age <= 10 else max(0.0, 1 - (age - 10) / 50)
    parts = {"confluence": round(W["confluence"] * math.log2(1 + confluence), 3),
             "ev": round(W["ev"] * sum(ev_parts.values()), 3), "fresh": round(W["fresh"] * fresh, 3),
             "x": round(W["x"] * max(-1.0, min(1.0, xs)), 3) if xs is not None else 0.0,
             "chase": round(-W["chase"] * ru["chase"], 3), "rug": -RUG_PEN[rug["level"]],
             # 11.11. (flag pre_shill): every call signal of the paid shill network -1 (exit liquidity)
             "shill": -W["shill"] * r["shill_n"] if r.get("shill_n") else 0.0}
    flags = (["grok_override"] if ov else []) + (["shill_network_call"] if r.get("shill_n") else []) \
        + (["exit_signal"] if (srcs.get("caller") or {}).get("exit_signal") else []) \
        + (["shill_driven"] if shill else []) + (["runup_4x"] if ru["x"] and ru["x"] >= RUNUP_MAX_X else [])
    # a row whose only block is "paper only" (event / market range list) with a positive EV is "samo papir", not "ne"
    papered = (not tradeable and {k["key"] for k in why_not.keys} == {"paper_only"}
               and evx.get("ev_pct") is not None and evx["ev_pct"] > 0)
    lstate, lwhy = live_state(tradeable or papered, evx, paper_only(srcs))
    out = {"token": tok, "symbol": r["symbol"] or sr.get("symbol"), "tradeable": tradeable, "why_not": list(why_not),
           "live_eligible": lstate == "live", "live_state": lstate, "live_why": lwhy,
           "ev_top_source": evx.get("top_source"),
           "ev_pct": evx["ev_pct"], "n_samples": evx["n_samples"], "ev_confidence": evx["ev_confidence"],
           "ev_detail": evx["detail"], "fast": _fast_out(fv),
           "flags": flags, "tags": tags, "modifiers": {"p_mult": mods["p_mult"], "size_mult": mods["size_mult"]},
           "score": round(sum(parts.values()), 3), "score_parts": parts,
           "confluence": confluence, "source_kinds": sorted(srcs), "sources": srcs,
           "first_signal_ts": first_ts, "last_signal_ts": last_ts,
           "age_min": round((now - first_ts) / 60, 1) if first_ts else None,
           "market": r["market"], "market_why": r.get("market_why"), "bonded": not curve,
           "under_30k": (mcap < MIN_MCAP) if r["m"] else None, "runup": ru, "rug": rug,
           "x": ({"source": x.get("source"), "age_min": round((now - (x.get("ts") or now)) / 60, 1),
                  "x_momentum_score": x.get("x_momentum_score"), "x_early": x.get("x_early"),
                  "posts60": x.get("posts60"), "fresh": x_fresh} if x else None),
           "warning": (f"RUG RIZIK, nadjačano Grokovim dokazom: {ov['rug_warning']}" if ov else None),
           "grok_evidence": ge, "grok_override": ov,
           "suggested_size_sol": round(size * (OVERRIDE_SIZE if ov else 1.0), 4) if tradeable else None}
    if details and tradeable:
        out["exit_plan"] = exit_plan(r, ov, lim, S)
    if raw:   # 11.11. (proposals/): the keyed blocks, the raw market reading, the shill-network call count
        out.update(blocks=list(why_not.keys), live_raw=r["m"], shill_n=r.get("shill_n") or 0)
    return out


def exit_plan(r, ov, lim, S):
    """A plan in set_exit_plan's format: tight for a Grok override; the range's own zones (in market cap) for a range
    candidate; else (11.11., owner's rule E: callers, groups, insiders, wallets, momentum, every signal source) the
    signal exit of trade/edge: half at +15 %, trailing 8 % from the peak, stop -10 %, everything out after 45 min (the
    benchmark the influencer's P is measured on; the old +10 / -20 data pair and +20 / -30 / 4 h shadow rule are gone).
    The stop is never looser than sl_default."""
    if ov:
        return dict(EXIT_TIGHT)
    z = r.get("range") or {}
    mc = z.get("mc") or {}
    if mc.get("range_high_low") and mc.get("range_high_top") and mc.get("range_low_low"):
        return {"take_profits": [{"at_mc_usd": mc["range_high_low"], "sell_share": 0.5},
                                 {"at_mc_usd": mc["range_high_top"], "sell_share": 0.5}],
                "stop": {"at_mc_usd": round(mc["range_low_low"] * 0.85)},
                "reason": "raspon: pola van na range_high_low, ostatak na range_high_top, stop range_low_low × 0,85"}
    tp, sl, tr, mins = _tedge.TP * 100, _tedge.SL * 100, _tedge.TRAIL * 100, _tedge.TIME_MIN
    sl = min(sl, float(lim.get("sl_default") or sl))
    what = "momentum" if "momentum" in r["sources"] else "signal"
    return {"take_profits": [{"at_pct": tp, "sell_share": _tedge.TP_SHARE}],
            "trailing": {"activate_pct": tp, "trail_pct": tr}, "stop": {"at_pct": -sl},
            "time_stop": {"after_min": mins, "if_pnl_below_pct": 1000},
            "reason": f"{what}: pola van na +{tp:g} %, ostatak trailing {tr:g} % od vrha, stop -{sl:g} %, van nakon "
                      f"{mins} min"}


# ---------- the MCP tools ---------------------------------------------------------------------------------------------

def _cached(now=None, src=None):
    t = time.time()
    if src is None and now is None and _CACHE["rows"] is not None and t - _CACHE["ts"] < CACHE_S:
        return _CACHE["rows"], _CACHE["meta"]
    rows, meta = build(now, src)
    if src is None and now is None:
        _CACHE.update(ts=t, rows=rows, meta=meta)
    return rows, meta


def _int(x, default, lo, hi):
    try:
        return max(lo, min(hi, int(x)))
    except (TypeError, ValueError):
        return default


def candidates(min_sources=1, limit=30, now=None, src=None):
    """get_trade_candidates."""
    ms, lim = _int(min_sources, 1, 1, 10), _int(limit, 30, 1, 100)
    rows, meta = _cached(now, src)
    keep = [r for r in rows if r["confluence"] >= ms]
    return {"ts": int(now or time.time()), "min_sources": ms, "total": len(keep),
            "tradeable": sum(1 for r in keep if r["tradeable"]),
            "live_eligible": sum(1 for r in keep if r.get("live_eligible")), "candidates": keep[:lim],
            "ranking": SCORE_TEXT, "source_records": meta.get("records"), "sources_failed": meta.get("sources_failed"),
            "rules": {"min_mcap_usd": MIN_MCAP, "measured_from_mcap_usd": MEASURE_MIN_MCAP,
                      "runup_modifier_x": RUNUP_MAX_X, "min_liq_usd": _tcost.LIQ_HARD_MIN,
                      "min_vol_h1_usd": _tcost.VOL_FLOOR, "crew_window_min": CREW_S // 60,
                      "grok_fresh_min": GROK_FRESH_S // 60, "override_size_share": OVERRIDE_SIZE,
                      "cost_model": _tcost.describe(), "ev_rule": _tedge.RULE_TEXT},
            "notes": ("Read-only: nothing is bought here. 11.11. (owner): tradeable (EV > 0) is NOT a real-money buy: "
                      "live_eligible = tradeable AND ev_pct >= 3 AND n_samples >= 10 AND the EV does not rest more than "
                      "50 % on one source with n < 10 (ev_top_source); live_state = live | paper (samo papir: demo only) | "
                      "no, live_why says why not live. Buy with real money only a live_eligible row. "
                      "tradeable = ev_pct > 0 (the measured EV after the cost model "
                      "and the P modifiers; n_samples = the measured outcomes it rests on, ev_confidence low under 10), "
                      "bonded, 30k+, liquidity $15k+, 1 h volume $3k+, no confirmed rug, trading now, and no rug risk "
                      "rating unless grok_override. Run-up 4x+, shill-driven and a thin pool vs MC are tags (P / size "
                      "modifiers), never blocks. Autotrade needs more: EV >= +3 %, its 90 % interval above 0, n >= 10 "
                      "(grok_ev_gate) "
                      "(fresh Grok evidence; half size, tight exit_plan; a collapse is never overridden). Buy only through "
                      "execute_trade within grok_autotrade limits at suggested_size_sol, then set_exit_plan with "
                      "exit_plan. Shadow: the top rows are measured as source kandidati, overrides as grok_override "
                      "(get_source_stats).")}


HOW_TO_WORK = [
    "Your X and web searches cost MemeSonar nothing; its own X API does (about $6 a day at full speed). Every fresh "
    "row you send with submit_x_features replaces a paid lookup of that token for 2 hours.",
    "Work the tasks in order (priority 1 first). Each task says which tool answers it and with which arguments; a "
    "task disappears once your answer is stored (X rows: 30 min; opinions: 60 min; labels: once).",
    "Be critical, also of yourself: report what you find against a token too (falling post counts, only bots, paid "
    "shills, a caller deleting the post). A row of yours with x_momentum_score <= 0 and nobody named counts against.",
    "Your fresh X evidence (known callers / large accounts naming the CA, growing organic authors) or a kupi / dobar "
    "opinion can override MemeSonar's rug RISK rating (never a collapse that already happened); such a buy is half "
    "size with a tight exit plan, and it is measured as source grok_override so the owner sees whether it pays.",
    "Never trade outside the grok_autotrade limits (get_portfolio_status); buy only a tradeable row of "
    "get_trade_candidates at its suggested_size_sol, then set_exit_plan with its exit_plan.",
]
X_FEATURES = {"posts_15m": "<posts with the CA or $TICKER in the last 15 min>", "posts_60m": "<... last 60 min>",
              "unique_authors_15m": "<unique organic authors, 15 min>", "unique_authors_60m": "<... 60 min>",
              "known_callers": ["<handle of a known caller who posted it>"],
              "large_accounts": [{"handle": "<handle>", "followers": "<n>"}], "bot_share": "<0-1>",
              "note": "<one line: what you saw>"}


def tasks(limit=20, now=None, src=None):
    """get_grok_tasks: the queue (see HOW_TO_WORK), most useful first."""
    now_i = int(now or time.time())
    lim = _int(limit, 20, 1, 100)
    S = src or Sources()

    def safe(fn, default):
        try:
            return fn()
        except Exception:  # noqa: BLE001 - a part that cannot be read gives no tasks, never an error
            return default
    rows, _meta = _cached(now, src)
    out = []
    toks = [r["token"] for r in rows[:40]]
    grows = safe(lambda: S.grok_rows(toks, now_i), {}) if toks else {}
    ops = safe(lambda: S.opinions(toks, now_i, CONFLICT_DONE_S), {}) if toks else {}
    # (a) X checks: rows Grok can decide (tradeable, or blocked only by the rug risk rating) without a fresh X row
    for r in rows[:25]:
        risk_only = r["rug"]["level"] == "risk" and len(r["why_not"]) == 1 and r["why_not"][0].startswith("rug ocjena")
        if not (r["tradeable"] or risk_only) or grows.get(r["token"]):
            continue
        sym = r.get("symbol") or r["token"][:6]
        out.append({"id": f"x:{r['token']}", "kind": "x_check", "priority": 1 if risk_only else 2,
                    "token": r["token"], "symbol": sym, "rank": r["rank"],
                    "why": ("blocked only by the rug risk rating: your fresh X evidence decides it" if risk_only else
                            f"rank {r['rank']} tradeable candidate without your X check in the last 30 min"),
                    "instruction": (f"Search X for the CA {r['token']} and ${sym}: posts in the last 15 and 60 min, unique "
                                    "organic authors in both windows (no bots, no alert bots), which known callers and "
                                    "large accounts (>= 50k followers) posted it and when. Send it even when it is "
                                    "nothing (zeros are evidence)."),
                    "answer_with": {"tool": "submit_x_features",
                                    "arguments": {"subject": r["token"], "subject_kind": "token", "ts_asof": "<now>",
                                                  "features": X_FEATURES}}})
    # (c) sources disagree
    for r in rows[:25]:
        if ops.get(r["token"]):
            continue
        srcs, x = r["sources"], r.get("x") or {}
        conflicts = []
        sc = srcs.get("scan") or {}
        if sc.get("passed") and r["rug"]["level"] in ("risk", "hard"):
            conflicts.append("the scanner passed it, but the rug check rates it " + r["rug"]["level"])
        cal = srcs.get("caller") or {}
        good = [c for c in cal.get("callers") or [] if (c.get("record") or {}).get("verdict") in ("drzi_se", "samo_brzo")
                or ((c.get("record") or {}).get("ev_mean") or 0) > 0]
        if good and x.get("fresh") and (x.get("x_momentum_score") or 0) < 0:
            conflicts.append(f"{len(good)} caller(s) with a good record call it, but X momentum is "
                             f"{x.get('x_momentum_score')} (falling)")
        ge = r.get("grok_evidence") or {}
        if ge.get("for") and ge.get("against"):
            conflicts.append("your own fresh evidence points both ways")
        if (srcs.get("hidden_group") or srcs.get("insider")) and r["rug"]["level"] in ("risk", "hard"):
            conflicts.append("wallet groups / insiders buy it while the rug check rates it " + r["rug"]["level"])
        if not conflicts:
            continue
        out.append({"id": f"op:{r['token']}", "kind": "resolve_conflict", "priority": 3, "token": r["token"],
                    "symbol": r.get("symbol"), "rank": r["rank"], "why": "; ".join(conflicts),
                    "instruction": ("Check who is right (X, the callers' posts, the chart, holders) and give one verdict: "
                                    "kupi or preskoči, with your confidence and the numbers you used."),
                    "answer_with": {"tool": "submit_signal_opinion",
                                    "arguments": {"token": r["token"], "verdict": "kupi | preskoči",
                                                  "confidence": "<0-1>", "interpretation": "<why>",
                                                  "evidence": {"conflict": conflicts}}}})
    # (b) labels: hidden lists, caller crews, insiders
    gids, ins = safe(S.labels, (set(), set()))
    _member, glist = safe(S.groups, ({}, {}))
    seen = set()
    for ts, s, gid, tok, who, mc in safe(lambda: S.group_signals(now_i, since=now_i - 86400), [])[::-1]:
        if gid in gids or gid in seen:
            continue
        seen.add(gid)
        kind, grade, members, met = glist.get(gid, ("wallet" if s == "hidden_group" else "caller", None, [], {}))
        out.append(_label_task(gid, kind, grade, members, s, tok, met))
    for ts, k, gid, tok, who in safe(lambda: S.group_activity(now_i), []):
        if gid in gids or gid in seen or k != "call":
            continue
        seen.add(gid)
        kind, grade, members, met = glist.get(gid, ("caller", None, [], {}))
        out.append(_label_task(gid, kind, grade, members, "caller_crew_activity", tok, met))
    for t in safe(lambda: S.insider_rows(now_i), []):
        ws = list(t.get("wallets") or [])
        if t["token"] in ins or (ws and all(w in ins for w in ws)):
            continue
        out.append({"id": f"ins:{t['token']}", "kind": "label_insiders", "priority": 4, "token": t["token"],
                    "wallets": ws[:8], "why": "2+ wallets that bought before earlier calls bought it, nobody called yet",
                    "instruction": ("Look the wallets up (get_wallet_history, X, Solscan): the team, a paid list, snipers "
                                    "or real early buyers? Name them in one short label."),
                    "answer_with": {"tool": "submit_suggestion",
                                    "arguments": {"title": "Insider label", "interpretation": "<what you found>",
                                                  "proposed_change": {"insider_label": {"token": t["token"], "wallets": ws[:8],
                                                                                        "label": "<short name>",
                                                                                        "note": "<why>"}}}}})
    out.sort(key=lambda t: (t["priority"], t.get("rank") or 999))

    def intake():
        from trade import settings
        tc = S._tcon()
        try:
            return settings.flag("x_features_ingest", con=tc) if tc is not None else "off"
        finally:
            if tc is not None:
                tc.close()
    on = safe(intake, "off") != "off"
    return {"ts": now_i, "how_to_work": HOW_TO_WORK, "total": len(out), "tasks": out[:lim],
            "x_features_intake": "on" if on else "off",
            "note": None if on else ("the owner has the X feature intake (flag x_features_ingest) switched off: "
                                     "submit_x_features is refused until he switches it on; answer x_check tasks "
                                     "with submit_signal_opinion meanwhile")}


def _label_task(gid, kind, grade, members, why, token, met=None):
    from kol import groupdisc
    return {"id": f"grp:{gid}", "kind": "label_group", "priority": 4, "group_id": gid, "group_kind": kind,
            "grade": grade, "n_measured": groupdisc.n_measured_of(kind, met), "members": list(members)[:12],
            "token": token,
            "why": ("a hidden wallet list bought without a public call" if why == "hidden_group" else
                    "a caller crew called first" if why == "caller_group_first" else "a caller crew is active"),
            "instruction": ("Who is this group (get_trader_groups / get_group_activity, X)? A paid alpha group, a KOL's "
                            "friends, a bot farm? Give a short name and why."),
            "answer_with": {"tool": "submit_suggestion",
                            "arguments": {"title": "Group label", "interpretation": "<what you found>",
                                          "proposed_change": {"group_label": {"group_id": gid, "label": "<short name>",
                                                                              "note": "<why>"}}}}}


# ---------- shadow log (the scanner pass, scan/market.pass_once: the only writer of scan.db) --------------------------

def log_shadow(con, rows, now, top_n=5):
    """Shadow entries for the combined list: source kandidati for each tradeable row the first time it ranks in the top
    `top_n`, source grok_override for every tradeable row with a Grok override; the entry is the row's live price.
    Returns {"kandidati": n, "grok_override": n} of NEW entries (scan/shadow.enter keeps the first per token)."""
    from scan import shadow
    out = {"kandidati": 0, "grok_override": 0}
    for r in rows:
        if not r.get("tradeable"):
            continue
        m = r.get("market") or {}
        price, mcap = m.get("price_usd"), m.get("market_cap_usd")
        srcs = (["kandidati"] if (r.get("rank") or 999) <= top_n else []) + (["grok_override"] if r.get("grok_override") else [])
        for s in srcs:
            if shadow.enter(con, r["token"], s, "migrated", True, now, price, mcap, r.get("symbol")):
                out[s] += 1
    return out
