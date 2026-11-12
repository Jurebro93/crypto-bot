"""Paper proof of the proposals (flag proposals G21 in paper): the demo account PAPER_USER (autopilot-paper) takes
the shown proposals with their exits, so each strategy gets its own paper record. Runs inside league/auto.loop (20 s;
run_ui.py is league.db's only writer). run_trade.py never mirrors PAPER_USER: no real money moves.

  off            nothing
  shadow         no entries (the list and the measurements only); 11.11.: the publication and the stop rule below
  paper / live   11.11. (the owner's rules after HAOBIBI, where a proposal was bought at $88k, outside its $104-112k
                 zone and under its own $88.6k stop, 2 s after range_dca's round in the same token closed on its stop):
                 every WAITING proposal (status novo, expires_ts in the future, not yet taken by the demo account, at
                 most PASS_CAP a pass by EV) is priced every pass (one batched league/copy.market read, at most every
                 CHECK_EVERY_S) and entered ONLY when
                   - the market cap is inside its entry zone (strategies.zone_of: the primary strategy's entry_zone, or
                     the proposal's market cap +- 5 %) and above its stop (exits_mcap sl)
                   - the EV is still > 0 at this market cap and liquidity (the primary strategy's p on its record,
                     calib.estimate x its modifiers, at the exit's TP / SL from this market cap, cost =
                     trade/cost.round_trip of the stake in this pool)
                   - the guards hold: MC >= $30k, liquidity >= $15k (trade/cost.LIQ_HARD_MIN, owner's rule B; was $20k),
                     a DexScreener price (not the bonding-curve / Jupiter fallback), no rug (league/copy._rugged), the
                     demo account does not hold the token, the stake (the proposal's size,
                     within the 2 % slippage stake of this pool) >= 0.005 SOL
                   - range_dca has no claim on the token on the demo account (rangedca/trade.busy: an open round, a
                     round closed within its 20 min cooldown, the range paused by range_flip): one position per token;
                     a second buy would be a lot of the same round, which range does itself, so it is skipped
                 A proposal made earlier than 10 min ago is entered too when the price comes into its zone later. The
                 stop rule (strategies.wait_check): under the stop after the proposal was made -> isteklo ("pao ispod
                 SL-a"); made while already under it -> it waits for the zone. What this loop reads is written back
                 (last_mcap, the first time in the zone, the paper entry "ušao (paper) na MC ...": status stays novo).
                 Size = the proposal's size at the SOL price; its exit = the proposal's TP / SL as the lot's own TP/SL
                 (league/auto "tpsl", MC levels or %, hold time for a time stop that takes everything out) and the full
                 exit plan (league/exitplan, accounts [PAPER_USER]) when no other plan is active on the token. live is
                 never set by code and is refused (live_refusal): the real account only buys on the owner's tap (Kupi
                 on the Autopilot card); Grok autotrade may read get_proposals and buy through execute_trade within its
                 own limits, as before.
league.db proposal_trades: one row per proposal and account, closed from the lot's own result (trades.ret).
11.11. (the owner's decision 4, proposals/publish.py): this 20-s loop also decides the publication of every waiting
proposal at the market cap it reads (shown only inside the entry zone and >= 1 x ATR above the stop, else "čeka zonu"
with the reason, proposals.db wait_why), in shadow too (shadow publishes and keeps the stop rule, it never enters);
the demo account enters only a proposal published at this market cap.
"""
import json
import sqlite3
import time

from . import calib, store, strategies

FLAG = "proposals"
SRC = "prijedlog (demo)"
PASS_CAP = 50               # waiting proposals priced per pass, the best EV first
CHECK_EVERY_S = 20          # the loop wakes on every followed wallet's webhook; the zones are priced at most this often
MIN_MCAP = 30_000
MIN_SOL = 0.005
_LAST = {}                  # proposals.db path -> the last pass that priced the waiting proposals
SCHEMA = """CREATE TABLE IF NOT EXISTS proposal_trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT, user TEXT, proposal_id INTEGER, token TEXT, strategy TEXT, sources TEXT,
    trade_id INTEGER, opened_ts INTEGER, status TEXT, closed_ts INTEGER, ret REAL, UNIQUE (user, proposal_id));
CREATE INDEX IF NOT EXISTS proposal_trades_status ON proposal_trades (status, user);"""


def ensure(con):
    con.executescript(SCHEMA)


def mode():
    try:
        from league import flags
        return flags.mode(FLAG)
    except Exception:  # noqa: BLE001
        return "off"


def live_refusal(con, now=None):
    """trade/settings.LIVE_GATES: proposals never go live (no automatic path to the real account)."""
    return ("prijedlozi nemaju live: pravi račun kupuje prijedlog samo na tvoj dodir (Kupi), demo račun ih dokazuje "
            "u paper modu")


def _sl_default():
    """The owner's default stop (trade settings sl_default): a plan's stop may not be looser."""
    try:
        from trade import executor, settings
        tc = settings.connect()
        try:
            return float(settings.merged(executor.load_config(), tc).get("sl_default") or 60)
        finally:
            tc.close()
    except Exception:  # noqa: BLE001
        return 60.0


def waiting(now, path=None, taken=(), cap=PASS_CAP):
    """The waiting proposals (status novo, not expired, not in `taken`), the best EV first, at most cap
    (proposals.db, read-only)."""
    con = store.ro(path)
    if con is None:
        return []
    try:
        ps = store.read(con, "status='novo' AND expires_ts > ?", (int(now),), order="ev_pct DESC, id", limit=1000)
    finally:
        con.close()
    return [p for p in ps if p["id"] not in taken][:cap]


def sync_closed(con, user):
    """Close our rows whose demo lot was sold (trades.status closed): ret from the lot."""
    for pid_, tid in con.execute("SELECT id, trade_id FROM proposal_trades WHERE status='open' AND user=?", (user,)).fetchall():
        t = con.execute("SELECT status, ret, closed_ts FROM trades WHERE id=?", (tid,)).fetchone()
        if t and t[0] == "closed":
            con.execute("UPDATE proposal_trades SET status='closed', ret=?, closed_ts=? WHERE id=?", (t[1], t[2], pid_))


def _frac(level, mcap, side):
    """A plan level ({"at_mc_usd"} or {"at_pct"}) as the TP / SL fraction from a market cap."""
    if not level:
        return None
    if level.get("at_mc_usd") and mcap:
        x = float(level["at_mc_usd"]) / mcap - 1
        return x if side == "tp" else -x
    if level.get("at_pct") is not None:
        x = float(level["at_pct"]) / 100
        return x if side == "tp" else abs(x)
    return None


def ev_now(p, mcap, liq, size_usd, fee=None):
    """(EV fraction, cost) of entering the proposal now: the primary strategy's p (its record shrunk toward no edge at
    this TP / SL / cost, x its modifiers; a calibrated p, e.g. Grok's, as it is) at the exit's TP / SL from this market
    cap, cost = trade/cost.round_trip of the stake in this pool. None when its exit cannot be read."""
    from trade import cost as tcost
    r = p.get("row") or {}
    plan = r.get("exit_plan") or {}
    tps = plan.get("take_profits") or []
    tp = _frac(tps[0], mcap, "tp") if tps else None
    sl = _frac(plan.get("stop"), mcap, "sl")
    if tp is None:
        tp = (r.get("tp_pct") or p.get("tp_pct") or 0) / 100 or None
    if sl is None:
        sl = (r.get("sl_pct") or p.get("sl_pct") or 0) / 100 or None
    if tp is None or sl is None:
        return None
    cost = tcost.round_trip(size_usd, liq, fee)
    st = (r.get("strategies") or {}).get(p.get("strategy") or r.get("strategy")) or {}
    if st.get("n") is not None and st.get("hits") is not None and not st.get("calibrated"):
        pp = calib.estimate(st["hits"], st["n"], tp, sl, cost)["p"] * float(st.get("p_mult") or 1.0)
    else:
        pp = st.get("p_tp") if st.get("p_tp") is not None else (p.get("p_tp") or r.get("p_tp") or 0.0)
    return calib.ev(float(pp), tp, sl, cost), cost


def _range_rows(tokens):
    """{token: range} of range.db for the range pause (read-only); {} without it."""
    try:
        from rangedca import data
        return data.read_ranges(tokens=sorted(tokens)) if tokens else {}
    except Exception:  # noqa: BLE001
        return {}


def range_block(con, user, tok, now, rng=None):
    """rangedca/trade.busy (an open round, its cooldown, the range paused) or None; never fails the pass."""
    try:
        from rangedca import trade as rtrade
        return rtrade.busy(con, user, tok, now, rng)
    except Exception:  # noqa: BLE001
        return None


def _write_back(path, seen, dead, entered, now, pubs=()):
    """The waiting columns, the stop rule's isteklo, the paper entries and (11.11., decision 4) the publication state
    into proposals.db (a short timeout: the pass may hold its write lock; what fails here is written again by the next
    pass or the next proposals pass)."""
    if not (seen or dead or entered or pubs):
        return
    try:
        pc = store.connect(path, timeout=5)
    except sqlite3.Error:
        return
    try:
        store.mark_seen(pc, seen, now)
        store.mark_published(pc, pubs, now)
        for pid, why in dead:
            store.set_status(pc, pid, "isteklo", why, now)
        for pid, mc in entered:
            store.mark_paper(pc, pid, mc, now)
        pc.commit()
    except sqlite3.Error as e:
        print(f"prijedlozi paper: stanje čekanja nije zapisano ({e})", flush=True)
    finally:
        pc.close()


def run_once(con, market_fn=None, now=None, path=None, sol=None):
    """One pass: [(user, text)]. Every mode but off: the publication of the waiting proposals (11.11., decision 4,
    proposals/publish.check at the market cap read here) and the stop rule; paper / live also the entries, only on
    PAPER_USER, only of a proposal published at this market cap."""
    m = mode()
    if m == "off":
        return []
    trading = m in ("paper", "live")
    from league import auto, copy, exitplan
    from league import store as lstore
    from trade import cost as tcost, settings
    from . import publish
    now = int(now or time.time())
    user = settings.PAPER_USER
    if trading:
        ensure(con)
        sync_closed(con, user)
        con.commit()
    key = (path or store.db_path(), trading)
    last = _LAST.get(key)
    if last is not None and 0 <= now - last < CHECK_EVERY_S:
        return []
    _LAST[key] = now
    try:
        taken = {p for (p,) in con.execute("SELECT proposal_id FROM proposal_trades WHERE user=?", (user,))}
    except sqlite3.Error:   # shadow: the table may not exist yet
        taken = set()
    ps = waiting(now, path, taken)
    if not ps:
        return []
    if trading and sol is None:
        from rangedca import trade as rtrade
        sol = rtrade.sol_usd()
    mk = (market_fn or copy.market)(sorted({p["token"] for p in ps})) or {}
    seen, dead, entered, done, inz, pubs = [], [], [], [], [], []
    for p in ps:
        mq = mk.get(p["token"])
        if not mq or not mq[0]:
            continue
        chk = strategies.wait_check(p, mq[3])
        if chk is None:
            continue
        seen.append((p["id"], mq[3], chk["state"] == strategies.IN_ZONE))
        if chk["dead"]:
            dead.append((p["id"], chk["dead"]))
            continue
        why = publish.check(p.get("row") or {}, mq[3])   # 11.11. (decision 4): in the zone and >= 1 ATR above the stop
        pubs.append((p["id"], why, mq[3]))
        if why is None and chk["state"] == strategies.IN_ZONE:
            inz.append((p, mq, chk))
    if not trading or not sol:
        _write_back(path, seen, dead, [], now, pubs)
        return []
    rngs = _range_rows({p["token"] for p, _mq, _c in inz})
    for p, mq, chk in inz:
        tok, r = p["token"], p.get("row") or {}
        if con.execute("SELECT 1 FROM trades WHERE user=? AND token=? AND status='open'", (user, tok)).fetchone():
            continue   # already held by the demo account: never doubled
        if range_block(con, user, tok, now, rngs.get(tok)):
            continue   # range_dca's round (open, in its cooldown or paused): one position per token
        price, liq, _url, mcap = mq[:4]
        if (mcap or 0) < MIN_MCAP or tcost.liq_block(liq) or copy._bonding_curve(mq) or copy._rugged(tok, mcap, liq):
            continue   # under 30k, liquidity under $15k, a Jupiter-only (curve / no pair) price, a rug
        size = min(float(p.get("size_sol") or 0), tcost.max_size_usd(liq) / sol)
        if size < MIN_SOL:
            continue
        got = ev_now(p, mcap, liq, size * sol)
        if got is None or got[0] <= 0:
            continue
        b = r.get("buy") or {}
        try:
            tid = lstore.buy(con, user, tok, p.get("symbol"), size * sol, price, liq,
                             f"{SRC}: {p.get('strategy')}", None, mcap)
        except ValueError as e:
            print(f"prijedlozi paper {tok[:6]}: ulaz nije prošao ({e})", flush=True)
            continue
        try:
            auto.set_auto(con, user, tid, "tpsl", b.get("tp") or "", b.get("sl") or "", hold_s=b.get("hold_s"))
        except ValueError as e:   # e.g. an MC target already under the entry: the stop alone, then smart sell
            try:
                auto.set_auto(con, user, tid, "tpsl", "", b.get("sl") or "", hold_s=b.get("hold_s"))
            except ValueError:
                auto.set_auto(con, user, tid, "smart")
            print(f"prijedlozi paper {tok[:6]}: TP iz prijedloga nije postavljen ({e})", flush=True)
        plan = dict(r.get("exit_plan") or {})
        if plan and exitplan.active(con, tok) is None:
            plan["accounts"] = [user]
            sl_default = _sl_default()
            try:
                exitplan.set_plan(con, tok, plan, sl_default, client=f"prijedlog #{p['id']}", now=now)
            except ValueError as e:
                print(f"prijedlozi paper {tok[:6]}: plan izlaza nije postavljen ({e})", flush=True)
        con.execute("INSERT OR IGNORE INTO proposal_trades (user, proposal_id, token, strategy, sources, trade_id, "
                    "opened_ts, status) VALUES (?,?,?,?,?,?,?,?)",
                    (user, p["id"], tok, p.get("strategy"), json.dumps(p.get("sources") or []), tid, now, "open"))
        con.commit()
        entered.append((p["id"], mcap))
        done.append((user, f"prijedlog #{p['id']} ({p.get('strategy')}) {p.get('symbol') or tok[:6]}: ušao (paper) na MC "
                           f"${mcap or 0:,.0f} u zoni {strategies.zone_text(chk['zone'])}, {size:g} SOL, EV "
                           f"{got[0] * 100:+.1f} %, izlaz {b.get('tp')} / {b.get('sl')}"))
    _write_back(path, seen, dead, entered, now, pubs)
    return done


def taken_ids(lcon, user=None):
    """{proposal id: (opened_ts, status)} of the demo account's paper entries (league.db proposal_trades)."""
    from trade import settings
    try:
        return {pid: (ts, st) for pid, ts, st in lcon.execute(
            "SELECT proposal_id, opened_ts, status FROM proposal_trades WHERE user=?", (user or settings.PAPER_USER,))}
    except sqlite3.Error:
        return {}


def proof(lcon=None):
    """{strategy: {"n", "hits", "hit_rate", "ev_pct"}} of the demo account's closed proposal trades (by the
    proposal's primary strategy), plus "all"."""
    from trade import settings
    own = lcon is None
    if lcon is None:
        try:
            from league import store as lstore
            lcon = sqlite3.connect(f"file:{lstore.DB}?mode=ro", uri=True, timeout=5)
        except sqlite3.Error:
            return {}
    try:
        rows = lcon.execute("SELECT strategy, ret FROM proposal_trades WHERE user=? AND status='closed' AND ret IS NOT "
                            "NULL", (settings.PAPER_USER,)).fetchall()
    except sqlite3.Error:
        rows = []
    finally:
        if own:
            lcon.close()
    by = {}
    for s, r in rows:
        by.setdefault(s, []).append(r)
        by.setdefault("all", []).append(r)
    return {s: {"n": len(xs), "hits": sum(1 for x in xs if x > 0), "hit_rate": round(sum(1 for x in xs if x > 0) / len(xs), 3),
                "ev_pct": round(sum(xs) / len(xs) * 100, 2)} for s, xs in by.items()}
