"""The five checks of a fast_check, always all five and in this order, each
{"key", "name", "status": ok | fail | error, "values": {...}, "threshold": {...}, "text", "ms"}:

  a) rug       mint / freeze authority, LP locked or burned, RugCheck "rugged", honeypot traps, top 10 %, dev %,
               insiders, bundle and sniper share: topcheck/safety.judge on a FRESH RugCheck summary (or Helius when
               RugCheck does not answer), then ui/kandidati.rug_view on it (collapse, rug archive, the rug filter's
               rug.db verdict: the same hard / risk rating the candidates and proposals use; no second rug filter)
  b) holders   the top 20 holders without pools, lockers and exchanges (RugCheck's known accounts, wallets.db label
               cex), top 10 %, the biggest single wallet, fresh wallets (the rug filter's on-chain share, rug.db
               fresh_holders_pct; unknown without a report, never a block)
  c) flow      fresh flow: buys / sells, buy share and transactions in 5 min (DexScreener m5), buys / sells and unique
               traders in the last minute and 5 min from the PumpPortal trades we already store (hype.db live_trades,
               only while run_live follows the token; else "nepoznato", never a GeckoTerminal call), vol_5m / liq,
               and topcheck/safety.volume_check (wash, unique traders per transaction, PR #117; 11.11. owner's rule
               B: a 'fail' is a tag "wash" for the decision's P x 0.5, never a block)
  d) price     price, market cap, liquidity now; the wallet's entry (the swap's own SOL per token, else the price we
               saw at the signal), how far above it we would buy and how late (seconds after its buy), the run-up from
               the token's first call (11.11. rule B: 4x+ is a tag, P x 0.7 / size x 0.5 in the decision), the buy
               slippage of the stake (trade/cost.impact) and the ONE cost model (trade/cost.round_trip of the stake,
               rule A); liquidity under $15k fails (trade/cost.LIQ_HARD_MIN), a pool under 3 % of MC is a tag.
               11.11. (Jure): a market cap outside our band (CFG mcap_min / mcap_max, FAST_MC_MIN 30k / FAST_MC_MAX
               5M) fails first ("MC $14.0M izvan raspona (30k–5M)"); the lag from the source's entry (its swap
               price, else the market cap at the signal for a call / convergence) in words (fast/estimate.lag:
               "jeftinije od njega" / "skuplje od njega"), and the source's own sale after its buy fails ("izvor
               izlazi": the copy exit would sell at once)
  e) source    the source's record (fast/sources.quality): closed trades, PnL, winners, tier, the proof

A check whose data could not be read (an API error, a timeout, the Helius credit cap) is "error": the whole signal is
CHECK_FAILED and retried, never skipped. "fail" always names the rule and the number ("holderi: top10 62 % > 45 %").

Token data (market, RugCheck / Helius, stored reports, PumpPortal trades) is fetched once per token and kept CACHE_S
(60 s) for every signal on that token; a part that errored is not kept (the retry asks again). Cost (CLAUDE.md):
DexScreener (free, the 3-s live cache), RugCheck (free; at most RC_PARALLEL at once: a report is up to 2 MB), Helius
only when RugCheck failed or had no holders: scan/filters.helius_facts without holder pages = getAccountInfo +
getTokenLargestAccounts + two getMultipleAccounts = 4 credits, at most HELIUS_PER_CHECK a check and FAST_HELIUS_DAY
(20,000) a Zagreb day; past either the check is an error "strop kredita".
"""
import os
import sqlite3
import threading
import time

from . import sources, store

CACHE_S = 60
RC_FRESH_S = 600            # a topcheck RugCheck summary this fresh is used without a new call
RC_TIMEOUT_S = 6
RPC_TIMEOUT_S = 6
RC_PARALLEL = 3
HELIUS_DAY = int(os.environ.get("FAST_HELIUS_DAY", "20000"))
HELIUS_PER_CHECK = int(os.environ.get("FAST_HELIUS_CHECK", "8"))
HELIUS_FACTS = 4            # scan/filters.HELIUS_COST
CAP_TEXT = "strop kredita"

CFG = {
    "top10_max": 45.0,       # b) top 10 holders without pools / CEX (Jure's example "holderi: top10 62 % > 45 %")
    "one_max": 20.0,         # b) one wallet
    "fresh_max": 50.0,       # b) fresh wallets among the top holders (rugfilter/score fresh_warn)
    "bundle_max": 20.0,      # a) bundle share (rugfilter/score bundle_hard)
    "sniper_max": 30.0,      # a) snipers + bundle holding / in the first slots (topics/view.sniper_shares)
    "cluster_max": 25.0,     # a) one wallet cluster (rugfilter/score cluster_hard)
    "insider_max": 25.0,     # a) insiders (rugfilter/score insider_hard)
    "min_tx_m5": 5,          # c) transactions in 5 min
    "min_buy_share": 0.40,   # c) buys / transactions in 5 min
    # d) 11.11. (Jure, 4CxjZy at $14M): our market-cap band for the live signals, env FAST_MC_MIN / FAST_MC_MAX; the
    # floor never under CLAUDE.md's $30k. No existing constant is "our range" for these signals (league/copy max_mcap
    # $50M is "velik token", rangedca/market.MAX_MCAP $5M is the range watchlist's own filter): a band of its own
    "mcap_min": max(30_000.0, float(os.environ.get("FAST_MC_MIN") or 30_000)),
    "mcap_max": float(os.environ.get("FAST_MC_MAX") or 5_000_000),
    "liq_min": 15_000,       # d) trade/cost.LIQ_HARD_MIN (11.11. owner's rule B: the only liquidity block)
    "liq_mcap_min": 0.03,    # d) league/copy.CFG min_liq_mcap: under it a tag (rule B), not a fail
    "chase_max": 0.20,       # d) at most +20 % above the wallet's entry
    "late_max_s": 600,       # d) at most 10 min after the signal when its entry price is unknown
    "runup_max_x": 4.0,      # d) trade/edge.RUNUP_X: a tag (P x 0.7, size x 0.5), not a fail (rule B)
}
NAMES = {"rug": "rug", "holders": "holderi", "flow": "tok", "price": "cijena", "source": "izvor"}
ORDER = ("rug", "holders", "flow", "price", "source")


class CheckError(Exception):
    """The data of a check could not be read: the signal is CHECK_FAILED and retried."""


# ---------- costs and the Helius cap ---------------------------------------------------------------------------------

class Meter:
    """Calls and credits per source this Zagreb day (flushed into fast.db costs by the worker) and the Helius cap."""

    def __init__(self, day_cap=None):
        self.lock = threading.Lock()
        self.day, self.helius_used = None, 0.0
        self.pending = {}
        self.day_cap = HELIUS_DAY if day_cap is None else day_cap

    def _roll(self, now):
        d = store.day_of(now)
        if d != self.day:
            self.day, self.helius_used = d, 0.0

    def load(self, con, now=None):
        now = now or time.time()
        with self.lock:
            self._roll(now)
            self.helius_used = float((store.costs(con, self.day).get("helius") or {}).get("credits") or 0)

    def can(self, credits, now=None):
        with self.lock:
            self._roll(now or time.time())
            return self.helius_used + credits <= self.day_cap

    def add(self, source, calls=1, credits=0.0, now=None):
        with self.lock:
            self._roll(now or time.time())
            if source == "helius":
                self.helius_used += credits
            c = self.pending.setdefault(source, [0, 0.0])
            c[0] += calls
            c[1] += credits

    def flush(self, con, now=None):
        with self.lock:
            got, self.pending = self.pending, {}
        for s, (n, cr) in got.items():
            store.add_cost(con, s, n, cr, now)
        return got


METER = Meter()


# ---------- the network and the stores, behind one object the tests replace -----------------------------------------

class Net:
    """Every read a fast_check makes. Each method raises on a failure it cannot answer (an error, not "no data")."""

    def __init__(self, meter=None):
        self.meter = meter or METER
        self.rc_sem = threading.BoundedSemaphore(RC_PARALLEL)

    def market(self, tokens):
        """{token: market dict} of the deepest DexScreener pair (the live 3-s cache, 5 s timeout); a token with no pair
        is missing. Raises when DexScreener does not answer."""
        from dexscreener import client
        pairs = client.tokens_live("solana", list(tokens))
        self.meter.add("dexscreener")
        return parse_pairs(pairs)

    def rugcheck(self, token, pool=None):
        """(summary, top holders) of a fresh RugCheck report (free): topcheck/safety.summarize_rc and the holders that
        are not pools / lockers / known infrastructure. Raises on an error or a timeout."""
        import urllib.parse
        from event_calendar import http
        from rugfilter import rugcheck as rc
        from topcheck import safety
        with self.rc_sem:
            raw = http.get_json(f"{rc.BASE}/tokens/{urllib.parse.quote(token, safe='')}/report", ttl=0,
                                timeout=RC_TIMEOUT_S, retries=0)
        self.meter.add("rugcheck")
        if not isinstance(raw, dict) or not raw:
            raise CheckError("RugCheck nije vratio izvještaj")
        summ = safety.summarize_rc(raw, extra_pools=[pool] if pool else ())
        return summ, rc_holders(raw, pool)

    def rpc(self, method, params):
        """One Helius RPC call (no retry, short timeout); the meter counts its credits."""
        import json
        import urllib.request
        from event_calendar import http
        key = os.environ.get("HELIUS_API_KEY")
        if not key:
            raise CheckError("nema HELIUS_API_KEY")
        body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode()
        req = urllib.request.Request(f"https://mainnet.helius-rpc.com/?api-key={key}", data=body,
                                     headers={"Content-Type": "application/json", "User-Agent": http.USER_AGENT})
        self.meter.add("helius", 1, 10 if method in ("getTransactionsForAddress", "getTokenAccounts") else 1)
        data = http._fetch(req, RPC_TIMEOUT_S, retries=0)
        if "error" in data:
            raise CheckError(f"Helius {method}: {str(data['error'])[:80]}")
        return data["result"]

    def helius_facts(self, token, rpc):
        from scan import filters
        facts, _credits = filters.helius_facts(token, rpc, pages=0)
        if facts is None:
            raise CheckError("Helius nije odgovorio")
        return facts

    def stored(self, token):
        """{"tc": topcheck row (RugCheck summary rc, rc_ts, verdict) or None, "rug": newest rug.db report or None}."""
        out = {"tc": None, "rug": None}
        try:
            from topcheck import store as tstore
            tc = _ro(tstore.DB)
            if tc is not None:
                try:
                    tc.row_factory = sqlite3.Row
                    r = tc.execute("SELECT * FROM top_check WHERE token=?", (token,)).fetchone()
                    if r:
                        import json
                        d = dict(r)
                        for k in ("state_json", "safety_json", "rc_json", "sell_json"):
                            try:
                                d[k[:-5]] = json.loads(d.pop(k) or "null")
                            except (ValueError, KeyError):
                                d[k[:-5]] = None
                        out["tc"] = d
                finally:
                    tc.close()
        except Exception:  # noqa: BLE001 - no topcheck: unknown
            pass
        try:
            from topcheck import holders as th
            rc = _ro(th.RUG_DB)
            if rc is not None:
                try:
                    rc.row_factory = sqlite3.Row
                    r = rc.execute("SELECT * FROM rug_reports WHERE mint=? ORDER BY checked_at DESC LIMIT 1",
                                   (token,)).fetchone()
                    if r:
                        import json
                        d = dict(r)
                        try:
                            d["data"] = json.loads(d.get("data") or "{}") or {}
                        except ValueError:
                            d["data"] = {}
                        out["rug"] = d
                finally:
                    rc.close()
        except Exception:  # noqa: BLE001
            pass
        return out

    def live_trades(self, token, since):
        """PumpPortal trades of the token since `since` (hype.db live_trades, indexed), [] when not followed."""
        from live import store as lv
        hc = lv.ro()
        if hc is None:
            return []
        try:
            return [{"side": s, "wallet": w, "amount": sol or 0, "ts": ts} for s, w, sol, ts in hc.execute(
                "SELECT side, wallet, sol, ts FROM live_trades WHERE mint=? AND ts>=? LIMIT 3000", (token, int(since)))]
        except sqlite3.Error:
            return []
        finally:
            hc.close()

    def snipers(self, token):
        try:
            from topics import view
            return view.sniper_shares([token]).get(token) or (None, None)
        except Exception:  # noqa: BLE001
            return None, None

    def collapse(self, token, mcap, liq):
        """11.11.: the rug or the dump after a pump (league/copy._collapse); a dump is P x 0.7 in decide, no block."""
        from league import copy as lcopy
        return lcopy._collapse(token, mcap, liq)

    def archived(self, token):
        """11.11.: "rug" | "dump" (rugfilter/archive.kinds) or None when the token is not archived."""
        try:
            from rugfilter import archive
            return archive.kinds().get(token)
        except Exception:  # noqa: BLE001
            return None

    def first_mcap(self, token, now):
        try:
            from ui import kandidati
            return (kandidati.Sources().first_calls([token], now).get(token) or (None, None))[1]
        except Exception:  # noqa: BLE001
            return None

    def sol_usd(self):
        try:
            from rangedca import trade as rtrade
            return rtrade.sol_usd()
        except Exception:  # noqa: BLE001
            return None

    def wallet_meta(self, owners):
        """{owner: (first_seen, labels)} of the owners wallets.db knows."""
        import json
        try:
            from wallets import store as wstore
        except Exception:  # noqa: BLE001
            return {}
        wc = _ro(wstore.DB)
        if wc is None or not owners:
            return {}
        try:
            q = ",".join("?" * len(owners))
            out = {}
            for w, fs, lab in wc.execute(f"SELECT wallet, first_seen, labels FROM wallets WHERE wallet IN ({q})",
                                         list(owners)):
                try:
                    out[w] = (fs, json.loads(lab or "[]") or [])
                except ValueError:
                    out[w] = (fs, [])
            return out
        except sqlite3.Error:
            return {}
        finally:
            wc.close()

    def quality(self, sig, now):
        return sources.quality(sig, now)

    def source_sold(self, sig, since):
        """11.11. (Jure, DOPE -10 % from the signal: "bolji ulaz ili znak da izlazi?"): {"ts", "via"} of the source's
        first sale of the token at or after its buy (a wallet source: hype.db chain_trades, the Helius webhook; a
        convergence: kol.db converge kol_selling, a tracked KOL wallet sells), None when none is seen."""
        from league import copy as lcopy
        kind, tok = sig.get("kind"), sig.get("token")
        p = lcopy._paths()
        if kind in sources.WALLET_KINDS and sig.get("source_id"):
            c = _ro(p["hype"])
            if c is None:
                return None
            try:
                r = c.execute("SELECT MIN(ts) FROM chain_trades WHERE wallet=? AND mint=? AND side='sell' AND ts >= ?",
                              (sig["source_id"], tok, int(since or 0))).fetchone()
            except sqlite3.Error:
                return None
            finally:
                c.close()
            return {"ts": int(r[0]), "via": "Helius (chain_trades)"} if r and r[0] else None
        if kind == "convergence":
            c = _ro(p["kol"])
            if c is None:
                return None
            try:
                r = c.execute("SELECT kol_selling, ts FROM converge WHERE token=?", (tok,)).fetchone()
            except sqlite3.Error:
                return None
            finally:
                c.close()
            return {"ts": int(r[1] or 0), "via": "konvergencija: praćeni KOL novčanik prodaje"} if r and r[0] else None
        return None


def _ro(path):
    if not path or not os.path.exists(path) or not os.path.getsize(path):
        return None
    try:
        return sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5)
    except sqlite3.Error:
        return None


def _f(x):
    try:
        return float(x) if x is not None else None
    except (TypeError, ValueError):
        return None


def parse_pairs(pairs):
    """DexScreener pairs -> {token: {"price", "mcap", "liq", "symbol", "pair" (the raw deepest pair), "pool", "dex",
    "w": {m5, h1, h24: {buys, sells, vol, ch}}}} of the deepest pair per token."""
    out = {}
    for pr in pairs or []:
        t = (pr.get("baseToken") or {}).get("address")
        liq = _f((pr.get("liquidity") or {}).get("usd")) or 0.0
        if not t or (t in out and liq < out[t]["liq"]):
            continue
        tx, vol, ch = pr.get("txns") or {}, pr.get("volume") or {}, pr.get("priceChange") or {}
        out[t] = {"price": _f(pr.get("priceUsd")) or 0.0, "liq": liq, "mcap": _f(pr.get("marketCap") or pr.get("fdv")),
                  "symbol": (pr.get("baseToken") or {}).get("symbol"), "pool": pr.get("pairAddress"),
                  "dex": pr.get("dexId"), "pair": pr,
                  "w": {w: {"buys": int((tx.get(w) or {}).get("buys") or 0), "sells": int((tx.get(w) or {}).get("sells") or 0),
                            "vol": _f(vol.get(w)) or 0.0, "ch": _f(ch.get(w))} for w in ("m5", "h1", "h24")}}
    return out


def rc_holders(raw, pool=None):
    """[{owner, address, pct, insider}] of a RugCheck report's top holders that are not pools, lockers or other known
    infrastructure (the same exclusion as topcheck/safety.summarize_rc; the creator stays a holder)."""
    known = raw.get("knownAccounts") or {}
    pools = {a for a, v in known.items() if (v or {}).get("type") != "CREATOR"} | ({pool} if pool else set())
    for m in raw.get("markets") or []:
        pools.add(m.get("pubkey"))
        for side in ("liquidityAAccount", "liquidityBAccount"):
            pools.add((m.get(side) or {}).get("owner"))
            pools.add(m.get(side.replace("Account", "")))
    pools.discard(None)
    out = []
    for h in raw.get("topHolders") or []:
        pct = _f(h.get("pct")) or 0
        if h.get("address") in pools or h.get("owner") in pools or pct <= 0:
            continue
        out.append({"owner": h.get("owner") or h.get("address"), "address": h.get("address"), "pct": round(pct, 2),
                    "insider": bool(h.get("insider"))})
    return out[:20] if raw.get("markets") else None   # a partial report cannot tell a pool from a whale


# ---------- the token data, cached --------------------------------------------------------------------------------------

class Cache:
    """token -> its data for CACHE_S, shared by every signal on the token; one fetch per token at a time."""

    def __init__(self, ttl=CACHE_S):
        self.ttl, self.d, self.lock, self.locks = ttl, {}, threading.Lock(), {}

    def token_lock(self, tok):
        with self.lock:
            return self.locks.setdefault(tok, threading.Lock())

    def get(self, tok, now):
        with self.lock:
            hit = self.d.get(tok)
            return hit if hit and now - hit["ts"] < self.ttl else None

    def put(self, tok, data):
        with self.lock:
            self.d[tok] = data
            if len(self.d) > 400:
                cut = time.time() - self.ttl
                for k in [k for k, v in self.d.items() if v["ts"] < cut]:
                    self.d.pop(k, None)
                    self.locks.pop(k, None)

    def clear(self):
        with self.lock:
            self.d.clear()
            self.locks.clear()


CACHE = Cache()


def gather(tok, net, now=None, cache=None, budget=None):
    """The token's data (see the module text): {"ts", "market", "market_err", "rc", "holders", "rc_src", "rc_err",
    "stored", "trades", "snip", "collapse", "archived", "first_mcap", "ms": {part: ms}, "cached": bool}."""
    cache = CACHE if cache is None else cache
    now = now or time.time()
    budget = budget if budget is not None else {"credits": 0}
    with cache.token_lock(tok):
        hit = cache.get(tok, now)
        if hit and not hit.get("market_err") and not hit.get("rc_err") and not hit.get("holders_err"):
            return dict(hit, cached=True)
        d = dict(hit or {}, ts=now, ms={}, cached=False)
        need_m = not hit or bool(hit.get("market_err"))
        need_rc = not hit or bool(hit.get("rc_err") or hit.get("holders_err"))
        if need_m or "stored" not in d:
            d["stored"] = net.stored(tok)   # local, first: a fresh topcheck RugCheck summary saves the call
        th = None
        if need_rc:   # RugCheck (1-3 s) runs while DexScreener answers: the two network reads overlap
            def _rc():
                t1 = time.time()
                _rug_data(tok, d, net, now, budget)
                d["ms"]["rc"] = int((time.time() - t1) * 1000)
            if need_m:
                th = threading.Thread(target=_rc, daemon=True, name="fast-rc")
                th.start()
            else:
                _rc()
        if need_m:
            t0 = time.time()
            try:
                d["market"], d["market_err"] = (net.market([tok]) or {}).get(tok), None
            except Exception as e:  # noqa: BLE001 - an error, not "no pair"
                d["market"], d["market_err"] = None, f"DexScreener: {type(e).__name__}: {str(e)[:80]}"
            d["ms"]["market"] = int((time.time() - t0) * 1000)
            t0 = time.time()
            d["trades"] = net.live_trades(tok, now - 3600)
            d["snip"] = net.snipers(tok)
            d["archived"] = net.archived(tok)
            d["first_mcap"] = net.first_mcap(tok, now)
            m = d.get("market") or {}
            d["collapse"] = net.collapse(tok, m.get("mcap"), m.get("liq")) if m else None
            d["ms"]["local"] = int((time.time() - t0) * 1000)
        if th is not None:
            th.join(RC_TIMEOUT_S * 3)
            if th.is_alive():
                d["rc_err"] = "RugCheck / Helius: bez odgovora u roku"
        cache.put(tok, d)
        return d


def _rug_data(tok, d, net, now, budget):
    """d["rc"] / d["holders"] / d["rc_src"] or d["rc_err"]: a fresh topcheck summary, else RugCheck, else Helius."""
    d["rc"], d["holders"], d["rc_err"], d["facts"] = None, None, None, None
    d.pop("holders_err", None)
    d.pop("cap_hit", None)
    tc = (d.get("stored") or {}).get("tc") or {}
    if tc.get("rc") and tc.get("rc_ts") and now - tc["rc_ts"] < RC_FRESH_S and (tc["rc"] or {}).get("top10") is not None:
        d["rc"], d["rc_src"] = tc["rc"], f"topcheck (RugCheck prije {int((now - tc['rc_ts']) // 60)} min)"
        return
    errs = []
    pool = (d.get("market") or {}).get("pool")
    try:
        d["rc"], d["holders"] = net.rugcheck(tok, pool)
        d["rc_src"] = "RugCheck"
        if (d["rc"] or {}).get("top10") is not None:
            return
        errs.append("RugCheck: djelomičan izvještaj bez holdera")
    except Exception as e:  # noqa: BLE001
        errs.append(f"RugCheck: {type(e).__name__}: {str(e)[:60]}")
    # Helius: only for what RugCheck did not give (authorities and the top 10 wallets), within both caps
    if budget["credits"] + HELIUS_FACTS > HELIUS_PER_CHECK or not net.meter.can(HELIUS_FACTS, now):
        errs.append(f"Helius: {CAP_TEXT} (dan {net.meter.day_cap}, provjera {HELIUS_PER_CHECK})")
        if d["rc"] is None:
            d["rc_err"] = "; ".join(errs)
        else:
            d["holders_err"] = "; ".join(errs)
        d["cap_hit"] = True
        return
    try:
        budget["credits"] += HELIUS_FACTS
        facts = net.helius_facts(tok, net.rpc)
        d["facts"] = facts
        if d["rc"] is None:
            d["rc"] = {"rugged": False, "mint_auth": facts.get("mint_auth"), "freeze_auth": facts.get("freeze_auth"),
                       "launchpad": None, "lp_locked": None, "has_market": True, "top10": facts.get("top10_pct"),
                       "insiders": None, "dev_pct": None, "creator_tokens": 0, "holders": None, "fee": 0,
                       "perm_delegate": False, "non_transferable": False, "transfer_hook": False,
                       "frozen_default": False, "danger": [], "light": True}
            d["rc_src"] = "Helius (RugCheck nije odgovorio)"
        else:
            d["rc"] = dict(d["rc"], top10=facts.get("top10_pct"))
            d["rc_src"] += " + Helius top 10"
    except Exception as e:  # noqa: BLE001
        errs.append(f"Helius: {type(e).__name__}: {str(e)[:60]}")
        if d["rc"] is None:
            d["rc_err"] = "; ".join(errs)
        else:
            d["holders_err"] = "; ".join(errs)


# ---------- the checks -------------------------------------------------------------------------------------------------

def _res(key, status, text, values=None, threshold=None, ms=0):
    return {"key": key, "name": NAMES[key], "status": status, "text": text, "values": values or {},
            "threshold": threshold or {}, "ms": int(ms)}


def _pct(x, nd=0):
    return "?" if x is None else (f"{x:.{nd}f}".replace(".", ",") + " %")


class _RugSrc:
    """ui/kandidati.rug_view's reads for one token: collapse from the gathered data; concentration is check b's."""

    def __init__(self, d):
        self.d = d

    def collapse(self, token, mcap, liq):
        return self.d.get("collapse")

    def concentration(self, token):
        return None, "check holderi"


def check_rug(sig, d, cfg=CFG):
    t0 = time.time()
    ms = (d.get("ms") or {}).get("rc", 0)
    if d.get("rc") is None:
        return _res("rug", "error", f"rug: {d.get('rc_err') or 'RugCheck i Helius bez odgovora'}", ms=ms)
    from topcheck import safety
    from ui import kandidati
    tok, m, rc = sig["token"], d.get("market") or {}, d["rc"]
    st = d.get("stored") or {}
    rug = st.get("rug") or None
    full = {"verdict": rug.get("verdict"), "data": _full_data(rug.get("data"))} if rug else None
    judge = safety.judge(tok, rc, None, full, pair=m.get("pair"), trades=d.get("trades"))
    tc = {tok: {"verdict": judge["verdict"], "safety": judge, "rc": rc}}
    ak = d.get("archived")
    rv = kandidati.rug_view(tok, m.get("mcap"), m.get("liq"), _RugSrc(d), (tc, {tok: rug} if rug else {}),
                            archived={tok: ak if isinstance(ak, str) else "rug"} if ak else {})
    rdata = (rug or {}).get("data") or {}
    launch = rdata.get("launch") or {}
    bundle = _f((rug or {}).get("bundle_pct")) if rug else None
    bundle = bundle if bundle is not None else _f(launch.get("bundle_pct"))
    cluster = _f((rug or {}).get("cluster_pct")) if rug else None
    snip, snip_src = d.get("snip") or (None, None)
    v = {"mint_auth": bool(rc.get("mint_auth")), "freeze_auth": bool(rc.get("freeze_auth")),
         "lp_locked_pct": rc.get("lp_locked"), "rugcheck_rugged": bool(rc.get("rugged")), "top10_pct": rc.get("top10"),
         "dev_pct": rc.get("dev_pct"), "insiders_pct": rc.get("insiders"), "bundle_pct": bundle, "cluster_pct": cluster,
         "sniper_bundle_pct": _f(snip), "sniper_src": snip_src, "level": rv["level"], "verdict": judge["verdict"],
         "rug_filter": rv.get("rug_filter"), "src": d.get("rc_src"), "checks": judge.get("checks"),
         "dump": rv.get("dump")}   # 11.11.: a dump after a pump, no block: P x 0.7 in decide
    thr = {"dev_max": safety.DEV_FAIL, "lp_min": safety.LP_FAIL, "bundle_max": cfg["bundle_max"],
           "sniper_max": cfg["sniper_max"], "cluster_max": cfg["cluster_max"], "insider_max": cfg["insider_max"]}
    chk = judge.get("checks") or {}
    why = None
    if rv["level"] == "hard":
        why = f"rug: {rv['hard'][0]}"
    elif rv["level"] == "risk":
        why = f"rug rizik: {rv['risk'][0]}"
    elif (chk.get("dev") or [None])[0] == "fail":
        why = f"rug: dev drži {_pct(v['dev_pct'])} > {_pct(safety.DEV_FAIL)}"
    elif (chk.get("lp") or [None])[0] == "fail":
        why = f"rug: LP zaključan/spaljen {_pct(v['lp_locked_pct'])} < {_pct(safety.LP_FAIL)}"
    elif bundle is not None and bundle > cfg["bundle_max"]:
        why = f"rug: bundle {_pct(bundle)} > {_pct(cfg['bundle_max'])}"
    elif v["sniper_bundle_pct"] is not None and v["sniper_bundle_pct"] > cfg["sniper_max"]:
        why = f"rug: snajperi + bundle {_pct(v['sniper_bundle_pct'])} > {_pct(cfg['sniper_max'])}"
    elif cluster is not None and cluster > cfg["cluster_max"]:
        why = f"rug: klaster novčanika {_pct(cluster)} > {_pct(cfg['cluster_max'])}"
    elif _f(v["insiders_pct"]) is not None and v["insiders_pct"] > cfg["insider_max"]:
        why = f"rug: insajderi {_pct(v['insiders_pct'])} > {_pct(cfg['insider_max'])}"
    ms += (time.time() - t0) * 1000
    if why:
        return _res("rug", "fail", why, v, thr, ms)
    ok = (f"rug u redu ({judge['verdict']}): mint {'aktivan' if v['mint_auth'] else 'ugašen'}, freeze "
          f"{'aktivan' if v['freeze_auth'] else 'ugašen'}, LP {_pct(v['lp_locked_pct'])}, dev {_pct(v['dev_pct'])}, "
          f"bundle {_pct(bundle)}, snajperi {_pct(v['sniper_bundle_pct'])} ({d.get('rc_src')})")
    return _res("rug", "ok", ok, v, thr, ms)


def _full_data(r):
    """The rug.db report's data in the shape topcheck/safety.judge reads (run_top._full_data)."""
    r = r or {}
    L, h, c = r.get("launch") or {}, r.get("holders") or {}, r.get("cluster") or {}
    out = {"hard_fails": r.get("hard_fails") or [], "flags": r.get("flags") or [], "score": r.get("score"),
           "holders": {"top10_pct": h.get("top10_pct")},
           "launch": {"bundle_pct": L.get("bundle_pct"), "sniper_pct": L.get("sniper_pct")},
           "cluster": {"holding_pct": c.get("holding_pct")}}
    if r.get("wash_score") is not None:
        out["wash_score"] = r["wash_score"]
    return out


def check_holders(sig, d, net, now, cfg=CFG):
    t0 = time.time()
    ms = (d.get("ms") or {}).get("rc", 0)
    rc = d.get("rc") or {}
    hs = d.get("holders")
    rug = (d.get("stored") or {}).get("rug") or {}
    top10 = _f(rc.get("top10"))
    if top10 is None:
        top10 = _f(((rug.get("data") or {}).get("holders") or {}).get("top10_pct")) or _f(rug.get("top10_pct"))
    if top10 is None:
        why = d.get("holders_err") or d.get("rc_err") or "RugCheck i Helius bez podatka o holderima"
        return _res("holders", "error", f"holderi: top 10 nepoznat ({why})", ms=ms)
    v = {"top10_pct": round(top10, 1), "top20_pct": None, "max_one_pct": None, "n_top": None, "cex_excluded": 0,
         "fresh_pct": None, "fresh_src": None, "holders_total": rc.get("holders"), "src": d.get("rc_src")}
    if hs:
        meta = net.wallet_meta([h["owner"] for h in hs if h.get("owner")])
        cex = [h for h in hs if "cex" in ((meta.get(h["owner"]) or (None, []))[1] or [])]
        keep = [h for h in hs if h not in cex]
        v["cex_excluded"] = len(cex)
        v["n_top"] = len(keep)
        v["top20_pct"] = round(sum(h["pct"] for h in keep[:20]), 1)
        v["max_one_pct"] = round(max((h["pct"] for h in keep), default=0), 1)
        if cex:   # an exchange's wallet is not a holder that can dump: top 10 without it
            v["top10_pct"] = round(sum(h["pct"] for h in keep[:10]), 1)
    # fresh wallets only from the rug filter's on-chain wallet ages (rug.db); wallets.db first_seen is when WE first saw a
    # wallet, not its age, so it is no measure of "fresh": without a report the share stays unknown (never a block)
    fh = _f(((rug.get("data") or {}).get("holders") or {}).get("fresh_holders_pct"))
    if fh is not None:
        v["fresh_pct"], v["fresh_src"] = fh, "rug filter (rug.db)"
    else:
        v["fresh_src"] = "nepoznato (nema rug filter izvještaja)"
    thr = {"top10_max": cfg["top10_max"], "one_max": cfg["one_max"], "fresh_max": cfg["fresh_max"]}
    ms += (time.time() - t0) * 1000
    if v["top10_pct"] > cfg["top10_max"]:
        return _res("holders", "fail", f"holderi: top10 {_pct(v['top10_pct'])} > {_pct(cfg['top10_max'])}", v, thr, ms)
    if v["max_one_pct"] is not None and v["max_one_pct"] > cfg["one_max"]:
        return _res("holders", "fail", f"holderi: jedan novčanik {_pct(v['max_one_pct'])} > {_pct(cfg['one_max'])}",
                    v, thr, ms)
    if v["fresh_pct"] is not None and v["fresh_pct"] > cfg["fresh_max"]:
        return _res("holders", "fail", f"holderi: svježi novčanici {_pct(v['fresh_pct'])} > {_pct(cfg['fresh_max'])}",
                    v, thr, ms)
    return _res("holders", "ok", (f"holderi u redu: top10 {_pct(v['top10_pct'])}, top20 {_pct(v['top20_pct'])}, "
                                  f"najveći {_pct(v['max_one_pct'])}, svježi {_pct(v['fresh_pct'])}"), v, thr, ms)


def check_flow(sig, d, now, cfg=CFG):
    t0 = time.time()
    ms = (d.get("ms") or {}).get("market", 0)
    if d.get("market_err"):
        return _res("flow", "error", f"tok: {d['market_err']}", ms=ms)
    m = d.get("market")
    if not m:
        return _res("flow", "fail", "tok: nema DexScreener para (nema prometa za mjeriti)", {}, {}, ms)
    from topcheck import safety
    w5 = (m.get("w") or {}).get("m5") or {}
    b5, s5, vol5 = w5.get("buys", 0), w5.get("sells", 0), w5.get("vol", 0.0)
    n5 = b5 + s5
    tr = d.get("trades") or []
    t1 = [t for t in tr if t["ts"] >= now - 60]
    t5 = [t for t in tr if t["ts"] >= now - 300]
    st, txt = safety.volume_check(m.get("pair"), tr, ((((d.get("stored") or {}).get("rug") or {}).get("data") or {})
                                                      .get("wash_score")))
    v = {"buys_5m": b5, "sells_5m": s5, "tx_5m": n5, "buy_share_5m": round(b5 / n5, 3) if n5 else None,
         "vol_5m_usd": round(vol5, 0), "vol5_liq": round(vol5 / m["liq"], 3) if m.get("liq") else None,
         "buys_1m": sum(1 for t in t1 if t["side"] == "buy") if tr else None,
         "sells_1m": sum(1 for t in t1 if t["side"] == "sell") if tr else None,
         "traders_1m": len({t["wallet"] for t in t1}) if tr else None,
         "traders_5m": len({t["wallet"] for t in t5}) if tr else None, "tx_5m_pumpportal": len(t5) if tr else None,
         "tx_per_trader_5m": round(len(t5) / len({t["wallet"] for t in t5}), 2) if t5 else None,
         "flow_1m_src": "PumpPortal (hype.db)" if tr else "nepoznato: token nije u PumpPortal toku (DexScreener ima samo 5 min)",
         "volume_check": [st, txt]}
    thr = {"min_tx_5m": cfg["min_tx_m5"], "min_buy_share_5m": cfg["min_buy_share"]}
    ms += (time.time() - t0) * 1000
    v["tags"] = ["wash"] if st == "fail" else []   # 11.11. (owner's rule B): wash = P x 0.5 in the decision
    if n5 < cfg["min_tx_m5"]:
        return _res("flow", "fail", f"tok: {n5} transakcija u 5 min < {cfg['min_tx_m5']}", v, thr, ms)
    if v["buy_share_5m"] is not None and v["buy_share_5m"] < cfg["min_buy_share"]:
        return _res("flow", "fail", f"tok: kupnje {_pct(v['buy_share_5m'] * 100)} u 5 min < "
                                    f"{_pct(cfg['min_buy_share'] * 100)}", v, thr, ms)
    one = (f", 1 min {v['buys_1m']}/{v['sells_1m']} ({v['traders_1m']} tradera)" if tr else "")
    wash = f"; oznaka lažni volumen ({txt}): P × 0,5" if v["tags"] else ""
    return _res("flow", "ok", f"tok u redu: 5 min {b5}/{s5} kupnji/prodaja ({_pct(v['buy_share_5m'] * 100)}), "
                              f"${vol5:,.0f} = {v['vol5_liq'] or 0:.2f}× likv.{one}{wash}", v, thr, ms)


def usd(x):
    """$14.0M / $250k / $900."""
    x = float(x or 0)
    if x >= 1e6:
        return f"${x / 1e6:.1f}M"
    if x >= 1e3:
        return f"${x / 1e3:.0f}k"
    return f"${x:,.0f}"


def _short(x):
    x = float(x)
    if x >= 1e6:
        return f"{x / 1e6:g}M".replace(".", ",")
    return f"{x / 1e3:g}k".replace(".", ",") if x >= 1e3 else f"{x:g}"


def band_text(cfg=CFG):
    """"30k–5M": the market-cap band of the live signals."""
    return f"{_short(cfg['mcap_min'])}–{_short(cfg['mcap_max'])}"


def _source_sold(sig, d, net):
    """The source's sale of the token after its signal (Net.source_sold; for a wallet also the PumpPortal trades
    gathered for check c), None when none is seen or it cannot be read (an unknown sale is not a block)."""
    since = int(sig.get("sig_ts") or 0)
    if sig.get("kind") in sources.WALLET_KINDS:
        for t in d.get("trades") or []:
            if t.get("wallet") == sig.get("source_id") and t.get("side") == "sell" and (t.get("ts") or 0) >= since:
                return {"ts": int(t["ts"]), "via": "PumpPortal"}
    try:
        return net.source_sold(sig, since)
    except Exception:  # noqa: BLE001 - a fake / broken read: no sale seen
        return None


def entry_usd(sig, sol_usd):
    """The wallet's entry in USD per token: the signal's own (entry_px), else the swap's SOL per token x SOL price."""
    if sig.get("entry_px"):
        return float(sig["entry_px"]), "cijena iz signala"
    if sig.get("entry_sol_px") and sol_usd:
        return float(sig["entry_sol_px"]) * float(sol_usd), "iz swapa novčanika (SOL po tokenu)"
    return None, None


def check_price(sig, d, net, now, size_sol, cfg=CFG):
    t0 = time.time()
    ms = (d.get("ms") or {}).get("market", 0)
    if d.get("market_err"):
        return _res("price", "error", f"cijena: {d['market_err']}", ms=ms)
    m = d.get("market")
    if not m or not m.get("price") or not m.get("liq"):
        return _res("price", "fail", "cijena: nema živog DexScreener para s likvidnošću (uzimaju se bondani)", {}, {}, ms)
    from trade import cost as tcost
    from ui import kandidati
    from . import estimate
    sol = net.sol_usd()
    ent, ent_src = entry_usd(sig, sol)
    late = max(0, int(now - (sig.get("sig_ts") or now)))
    chase = (m["price"] / ent - 1) if ent else None
    if chase is None and sig.get("entry_mcap") and m.get("mcap"):   # a call / convergence: its market cap (same supply)
        chase = float(m["mcap"]) / float(sig["entry_mcap"]) - 1
        ent, ent_src = m["price"] / (1 + chase), "MC u trenutku signala"
    sold = _source_sold(sig, d, net)
    lag = estimate.lag(chase, sold, sig.get("kind"))
    stake = (size_sol or 0) * (sol or 0)
    slip = tcost.impact(stake, m["liq"]) if stake else None
    ru = kandidati.runup({"mcap": m.get("mcap"), "ch_h1": (m["w"].get("h1") or {}).get("ch"),
                          "ch_h24": (m["w"].get("h24") or {}).get("ch")}, d.get("first_mcap"))
    # 11.11. (owner's rule A): the ONE cost model of this stake in this pool; None under $15k (blocked below)
    cost = None if tcost.liq_block(m["liq"]) else tcost.round_trip(stake or None, m["liq"])
    mc0 = m.get("mcap") or 0
    tags = ((["runup"] if ru.get("x") and ru["x"] >= cfg["runup_max_x"] else [])
            + (["liq_share"] if mc0 and m["liq"] < cfg["liq_mcap_min"] * mc0 else []))
    v = {"price": m["price"], "mcap": m.get("mcap"), "liq": m["liq"], "entry_px": ent, "entry_src": ent_src,
         "from_entry_pct": round(chase * 100, 1) if chase is not None else None, "late_s": late,
         "stake_usd": round(stake, 2) if stake else None, "slippage_pct": round(slip * 100, 2) if slip else None,
         "cost_pct": round(cost * 100, 2) if cost is not None else None, "runup_x": ru.get("x"),
         "runup_from": ru.get("from"),
         "sol_usd": sol, "vol_h1": (m["w"].get("h1") or {}).get("vol"), "tags": tags,
         "dex": m.get("dex"), "symbol": m.get("symbol"), "band": "in", "lag_txt": lag["txt"], "src_sold": sold}
    thr = {"mcap_min": cfg["mcap_min"], "mcap_max": cfg["mcap_max"], "liq_min": cfg["liq_min"],
           "liq_mcap_min": cfg["liq_mcap_min"], "chase_max_pct": cfg["chase_max"] * 100, "late_max_s": cfg["late_max_s"],
           "runup_max_x": cfg["runup_max_x"]}
    mc, liq = m.get("mcap") or 0, m["liq"]
    who = "kupnje novčanika" if sig.get("kind") in sources.WALLET_KINDS else (
        "poziva" if sig.get("kind") == "influencer" else "signala")
    why = None
    if mc < cfg["mcap_min"] or mc > cfg["mcap_max"]:   # 11.11. (Jure): out of our band, the first reason
        v["band"] = "out"
        why = f"cijena: MC {usd(mc)} izvan raspona ({band_text(cfg)})" + (
            "; ispod 30k se ne analizira" if mc < 30_000 else "")
    elif liq < cfg["liq_min"]:
        why = f"cijena: likvidnost ${liq:,.0f} < ${cfg['liq_min']:,.0f}"
    elif liq > mc:
        why = f"cijena: lažni pool (likvidnost ${liq:,.0f} > MC ${mc:,.0f})"
    elif sold:   # 11.11. (Jure, DOPE): under his entry after his sale is him leaving, not a cheaper entry
        frm = f"; cijena {chase * 100:+.1f} % od {who}".replace(".", ",") if chase is not None else ""
        why = (f"cijena: izvor izlazi (prodaja viđena {max(0, int((sold.get('ts') or now) - (sig.get('sig_ts') or now)))}"
               f" s nakon signala, {sold.get('via')}{frm})")
    elif chase is not None and chase > cfg["chase_max"]:
        why = f"cijena: {chase * 100:+.0f} % od {who} > +{cfg['chase_max'] * 100:.0f} %"
    elif chase is None and late > cfg["late_max_s"]:
        why = f"cijena: {late // 60} min nakon signala (ulazna cijena nepoznata) > {cfg['late_max_s'] // 60} min"
    ms += (time.time() - t0) * 1000
    if why:
        return _res("price", "fail", why, v, thr, ms)
    frm = (f"{chase * 100:+.1f} % od {who} ({lag['txt']})".replace(".", ",") if chase is not None
           else f"ulaz {who} nepoznat")
    tg = ""
    if "runup" in tags:
        tg += f"; oznaka: već {ru['x']:.1f}x od prvog poziva (P × 0,7, ulog × 0,5)".replace(".", ",", 1)
    if "liq_share" in tags:
        tg += f"; oznaka: likvidnost {liq / mc:.1%} MC-a".replace(".", ",")
    return _res("price", "ok", f"cijena u redu: {frm}, {late} s kasnije, MC ${mc:,.0f}, likv. ${liq:,.0f}, "
                               f"klizanje {_pct(v['slippage_pct'], 1)}{tg}", v, thr, ms)


def check_source(sig, net, now):
    t0 = time.time()
    try:
        q = net.quality(sig, now)
    except Exception as e:  # noqa: BLE001
        return _res("source", "error", f"izvor: zapis nije čitljiv ({type(e).__name__})", ms=(time.time() - t0) * 1000), None
    ev = (f", EV {q['ev_pct']:+.1f} %".replace(".", ",") if q.get("ev_pct") is not None else "")
    txt = (f"izvor: {q.get('label') or q.get('id')} ({q.get('kind_hr')}), zatvorenih {q['closed']}{ev}, "
           f"PnL {q['pnl_usd']:+.0f} $" + (f", tier {q['tier']}" if q.get("tier") else "")
           + ("; dokaz za pravi novac: da" if q.get("proof") else f"; bez dokaza ({q.get('proof_why')})"))
    return _res("source", "ok", txt, q, sources.proof_rule(), (time.time() - t0) * 1000), q


def run_all(sig, net, now=None, size_sol=None, cache=None, cfg=CFG):
    """(checks {key: result} in ORDER, the token data, the source quality). Never raises: a check that cannot be
    read is "error"."""
    now = now or time.time()
    budget = {"credits": 0}
    try:
        d = gather(sig["token"], net, now, cache, budget)
    except Exception as e:  # noqa: BLE001 - a broken read is an error of every token check
        err = f"{type(e).__name__}: {str(e)[:80]}"
        d = {"market_err": err, "rc_err": err, "ms": {}}
    out = {}
    for key, fn in (("rug", lambda: check_rug(sig, d, cfg)), ("holders", lambda: check_holders(sig, d, net, now, cfg)),
                    ("flow", lambda: check_flow(sig, d, now, cfg)),
                    ("price", lambda: check_price(sig, d, net, now, size_sol, cfg))):
        try:
            out[key] = fn()
        except Exception as e:  # noqa: BLE001
            out[key] = _res(key, "error", f"{NAMES[key]}: {type(e).__name__}: {str(e)[:80]}")
    out["source"], q = check_source(sig, net, now)
    return out, d, q
