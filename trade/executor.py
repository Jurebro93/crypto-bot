"""Real buys and sells, behind a risk gate. trade.db logs every attempt.

Routes, tried in order until one works (trade/jupiter.py, trade/pumpportal.py):
  1. Jupiter Swap API v2 (api.jup.ag/swap/v2), 2. Jupiter Ultra (lite-api.jup.ag), 3. PumpPortal (0.5% fee,
  live only, can be switched off on the page). A route is only left for the next one when the swap surely did not
  happen (no quote, not landed, expired, slippage); when Jupiter never answers, the wallet is checked first.
Costs: the Jupiter swap fee (0.05-0.1%) is inside the amounts; network costs (signature, priority fee, rent of a new
token account) are logged per order (fee_lamports) and taken off the profit. After a full sale the empty token
account is closed and its ~0.002 SOL rent comes back (logged as a negative fee).

Live trading needs all three: the switch on the page /pravi-trade (cfg["on"], trade/settings.py), env TRADE_LIVE=1
and SOLANA_PRIVATE_KEY (both set by the owner in Render). Anything less is dry-run: the same quote is fetched and
logged, nothing is signed or sent. Switch off = no new real buys; sells of real positions still go through as long
as the key is there. Kill switch file trade/STOP also stops every new buy.
"""
import json
import os
import sqlite3
import time

from trade import aplog, equity, jupiter, pumpportal, settings, wallet

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(HERE, "config.json")
STOP_FILE = os.path.join(HERE, "STOP")
LAMPORTS = 1_000_000_000

SCHEMA = """
CREATE TABLE IF NOT EXISTS positions (
    id INTEGER PRIMARY KEY AUTOINCREMENT, paper_id INTEGER UNIQUE, token TEXT, symbol TEXT, opened_ts INTEGER,
    mode TEXT, status TEXT, reason TEXT, sol_in REAL, qty_raw INTEGER, qty_left INTEGER, sol_back REAL,
    fills_done INTEGER DEFAULT 0, closed_ts INTEGER, league_id INTEGER, fees_sol REAL DEFAULT 0);
CREATE TABLE IF NOT EXISTS orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT, ts INTEGER, position_id INTEGER, token TEXT, side TEXT, mode TEXT,
    amount_in INTEGER, amount_out INTEGER, cost_pct REAL, status TEXT, reason TEXT, error TEXT, signature TEXT,
    request_id TEXT, route TEXT, code INTEGER, fee_lamports INTEGER, prio_lamports INTEGER);
CREATE TABLE IF NOT EXISTS exit_fills (
    id INTEGER PRIMARY KEY AUTOINCREMENT, ts INTEGER, position_id INTEGER, event_id INTEGER, plan_id INTEGER,
    token TEXT, symbol TEXT, trigger TEXT, level_px REAL, seen_px REAL, mc_ratio REAL, px_src TEXT, px_age_s REAL,
    trigger_ts REAL, sent_ts REAL, done_ts REAL, fill_px REAL, slip_level_pct REAL, slip_seen_pct REAL,
    sent_after_s REAL, latency_s REAL, cap_pct REAL, cap_result TEXT, status TEXT, signature TEXT, mode TEXT);
CREATE INDEX IF NOT EXISTS exit_fills_event ON exit_fills (event_id, position_id);
"""
# exit_fills (13.11., owner's order point 2: "Jučerašnji live izlazi imali su ~5 % slip preko triggera"): one row per
# real sale that mirrors an exit plan's trigger (run_trade._exit_fill): the trigger's level and the price the
# executor saw (league.db exit_events), when the order went out and when it came back, the fill in USD per token and
# the slip against both, and how the protective slippage try went. *_px are USD per token; mc_ratio = market cap per
# unit of price, so the page and the log can say it in market cap.
NEW_COLS = {"positions": [("league_id", "INTEGER"), ("fees_sol", "REAL DEFAULT 0"),
                          # 10.11. (plan 1.5): the demo's exit price next to the real one, and how far apart
                          ("demo_exit_px", "REAL"), ("real_exit_px", "REAL"), ("exit_slip_pct", "REAL"),
                          # 11.11. (owner: "ručno uvijek nadjačava sve ostalo"): the limits the owner confirmed he
                          # overrides for this manual lot (buy(override=...)); NULL for every other buy
                          ("override", "TEXT")],
            "orders": [("route", "TEXT"), ("code", "INTEGER"), ("fee_lamports", "INTEGER"), ("prio_lamports", "INTEGER")]}
ROUTES = ("v2", "ultra", "pump")
ROUTE_HR = {"v2": "Jupiter", "ultra": "Jupiter Ultra", "pump": "PumpPortal"}


def load_config(path=None):
    with open(path or CONFIG_PATH) as f:
        return json.load(f)


def connect(path):
    con = sqlite3.connect(path, timeout=30)
    con.executescript(SCHEMA)
    con.execute(settings.SCHEMA)
    for table, cols in NEW_COLS.items():
        have = {r[1] for r in con.execute(f"PRAGMA table_info({table})")}
        for col, typ in cols:
            if col not in have:
                try:
                    con.execute(f"ALTER TABLE {table} ADD COLUMN {col} {typ}")
                except sqlite3.OperationalError as e:
                    # 10.11. (deploy #95): the trade loop and its equity thread both added a new column at start;
                    # the second one saw "duplicate column name". The column is there: nothing to do.
                    if "duplicate column" not in str(e):
                        raise
    _extras(con)
    return con


_EXTRAS_FAILED = {"said": False}


def _extras(con):
    """10.11. (Jure: graf vrijednosti walleta, dnevnik Autopilota): the equity table (trade/equity.py) and the indexes
    the decision log and this loop's own every-second reads walk (trade/aplog.py). A full disk or a locked file
    here must not take the trade loop down: no swap needs either, so it is one log line and the connection stands."""
    try:
        equity.ensure(con)
        aplog.ensure(con)
    except sqlite3.Error as e:
        if not _EXTRAS_FAILED["said"]:
            _EXTRAS_FAILED["said"] = True
            print(f"trade: tablica equity / indeksi dnevnika nisu pripremljeni ({type(e).__name__}: {e})", flush=True)


def armed():
    """The owner put the key and TRADE_LIVE=1 into Render: real swaps are possible (the switch decides buys)."""
    return os.environ.get("TRADE_LIVE") == "1" and wallet.can_sign()


def is_live(cfg):
    return bool(cfg.get("on")) and armed()


DAY_TZ = "Europe/Zagreb"   # audit 4.11. §14.4: "midnight" is Zagreb midnight, not whatever zone the server has


def day_pnl(con, now, mode, tz=None, strategije=False):
    """Today's cash result in this mode (since midnight in DAY_TZ): SOL back minus SOL in on positions closed today,
    minus EVERY network fee charged today, also the ones of failed buys and sells (audit 4.11. C09/T24).
    strategije (18.11., trade/mjerenje.py): True leaves out the owner's one-time cost measurement (positions and orders
    whose reason starts with MJERENJE_SRC): what the day's loss STOPS compare with their caps (buy_checks, auto_hard).
    The default counts everything: the wallet's real result of the day, the measurement included."""
    start = _day_start(now, tz)
    skip = _mjerenje_ids(con, start) if strategije else []
    q = ",".join("?" * len(skip))
    closed = con.execute("SELECT COALESCE(SUM(sol_back - sol_in),0) FROM positions WHERE mode=? AND status='closed' "
                         "AND closed_ts>=?" + (f" AND id NOT IN ({q})" if skip else ""), (mode, start, *skip)).fetchone()[0]
    fees = con.execute("SELECT COALESCE(SUM(fee_lamports),0) FROM orders WHERE mode=? AND ts>=?"
                       + (f" AND COALESCE(position_id, -1) NOT IN ({q})" if skip else ""),
                       (mode, start, *skip)).fetchone()[0] / LAMPORTS
    return closed - fees


# 18.11. (vlasnik: „Smiješ.” na pitanje smije li se trošak izmjeriti jednim pravim krugom pri 0,3 i 0,5 SOL;
# trade/mjerenje.py): the one-time cost measurement buys and sells through buy() / sell() like the owner's own manual buy
# (manual=True, his override with the reason), and its positions and orders carry a reason that starts with this. It is
# no strategy: its buys are apart from the day's automatic counts and spend (OWN_REASONS), its result is apart from the
# day's loss stops (day_pnl(strategije=True)) and from the cost model's calibration (trade/cost), and strategy_of
# names it "mjerenje". It IS in the wallet's real result of the day (day_pnl's default).
MJERENJE_SRC = "mjerenje troška"


def is_mjerenje(reason):
    return str(reason or "").strip().lower().startswith(MJERENJE_SRC)


def _mjerenje_ids(con, start):
    """The ids of the measurement's positions that touch the day from `start`: by the position's own reason, and by
    its orders' (a failed buy's position keeps the error as its reason; its orders keep the measurement's)."""
    like = MJERENJE_SRC + "%"
    try:
        return sorted({r[0] for r in con.execute(
            "SELECT id FROM positions WHERE COALESCE(closed_ts, opened_ts)>=? AND COALESCE(reason, '') LIKE ? "
            "UNION SELECT position_id FROM orders WHERE ts>=? AND COALESCE(reason, '') LIKE ? AND position_id IS NOT NULL",
            (start, like, start, like))})
    except sqlite3.Error:   # unreadable: nothing is left out (the stricter answer)
        return []


def _day_start(now, tz=None):
    """Unix time of the last midnight in `tz` (default DAY_TZ)."""
    import datetime
    from zoneinfo import ZoneInfo
    z = ZoneInfo(tz or DAY_TZ)
    d = datetime.datetime.fromtimestamp(now, z)
    return int(datetime.datetime(d.year, d.month, d.day, tzinfo=z).timestamp())


# 10.11. (Jure: "Dnevni limit potrošnje je dosegnut (2,850 SOL) ... Ovo nema smisla."): the day's spending limit is for
# the Autopilot's AUTOMATIC buys; the owner's own buys (reason "ručno ...": quick buy, DCA, buy orders, approved Grok
# requests) and Grok's autotrades ("Grok auto ...", which have their own limits, ui/grokauto) are not held by it, so
# they must not use it up either (they did: his Hope lots stopped every copy for the day).
# 18.11.: and the owner's one-time cost measurement (MJERENJE_SRC, trade/mjerenje.py): approved by him, no strategy's buy
OWN_REASONS = ("ručno%", "Grok auto%", MJERENJE_SRC + "%")
_NOT_OWN = "".join(" AND COALESCE(reason, '') NOT LIKE ?" for _ in OWN_REASONS)


def auto_spent(con, now, mode, tz=None):
    """SOL put into automatic buys today (since midnight in tz) in this mode: what max_sol_per_day limits."""
    return con.execute("SELECT COALESCE(SUM(sol_in),0) FROM positions WHERE opened_ts>=? AND mode=? "
                       "AND status IN ('open','closed','pending')" + _NOT_OWN,
                       (_day_start(now, tz), mode, *OWN_REASONS)).fetchone()[0] or 0.0


# 11.11. (owner's rule C): automatic real money is never above the grok_autotrade limits (ui/grokauto.LIMITS'
# defaults), whatever the trade settings say: 0.1 SOL a buy, 0.3 SOL of automatic buys a Zagreb day (auto_spent: the
# owner's own and Grok's own buys are counted apart, Grok has its own 0.3), 3 open positions, and a day loss of 0.15 SOL
# stops automatic buying until midnight. The owner's own buys (manual=True: quick buy, his DCA, an approved Grok
# request) keep his trade settings (Jure 10.11.: "makni limit"). Every real buy goes through buy() -> gate_buy().
LIVE_CAPS = {"max_sol_per_trade": 0.1, "max_sol_per_day": 0.3, "max_open": 3, "max_loss_day": 0.15}


def live_capped(cfg):
    """The settings with the live caps applied (each the smaller of the two)."""
    out = dict(cfg)
    for k, v in LIVE_CAPS.items():
        out[k] = min(type(v)(cfg[k]), v) if cfg.get(k) is not None else v
    return out


# 14.11. (owner: "nema više demo ... idemo s pravim novcem"; his answers: "0,1 SOL po tradeu", "dnevni gubitak 0,5 SOL",
# "najviše 10 otvorenih", "100 tradeova dnevno"): while his switch trade/settings "pravi_novac_sve" is on, every
# AUTOMATIC live buy is held to these INSTEAD of LIVE_CAPS and the page's own limits (LIVE_CAPS stay Grok autotrade's
# money limits and hold, unchanged, while the switch is off). max_open counts EVERY live position (all strategies, the
# owner's and Grok's lots too: one global 10); max_buys_day and max_sol_per_day count the automatic real buys of the
# Zagreb day (OWN_REASONS apart, as auto_spent); max_loss_day is the day's realized result of every live position, fees
# included (day_pnl): at -0.5 SOL no new automatic real buy until the next Zagreb day, open positions keep their exits.
# max_sol_per_day 11 = 100 x 0.1 SOL plus room for a buy whose swap took a little more. trade/config.json
# "pravi_novac_sve" may set lower values, never higher (switch_capped takes the smaller). The owner's manual buys are
# not held by them (manual=True keeps his settings, 11.11.).
SWITCH_CAPS = {"size_sol": 0.1, "max_sol_per_trade": 0.1, "max_open": 10, "max_buys_day": 100, "max_loss_day": 0.5,
               "max_sol_per_day": 11.0}


# 15.11. (konsenzus/, owner switch trade/settings "pravi_novac_izvori"): the real buys of the source consensus strategy
# (a league.db trade of LEAGUE_USER whose source starts with IZVORI_SRC) are held to these INSTEAD of LIVE_CAPS /
# SWITCH_CAPS, and only while that switch is on (run_trade checks the holdout proof before the buy): 0.1 SOL a trade,
# max_open counts EVERY live position (all strategies together), max_buys_day counts the konsenzus buys of the Zagreb
# day, max_loss_day the day's realized result of every live position, max_cost_pct caps the swap's cost at 6 %.
# trade/config.json "pravi_novac_izvori" may set lower values, never higher.
IZVORI_SRC = "konsenzus"
IZVORI_CAPS = {"size_sol": 0.1, "max_sol_per_trade": 0.1, "max_open": 5, "max_buys_day": 30, "max_loss_day": 0.3,
               "max_sol_per_day": 3.1, "max_cost_pct": 6.0}


def is_izvori(reason):
    return str(reason or "").strip().lower().startswith(IZVORI_SRC)


def izvori_caps(cfg=None):
    """IZVORI_CAPS, each the smaller of the code's and trade/config.json "pravi_novac_izvori"'s."""
    own = (cfg or {}).get("pravi_novac_izvori")
    own = own if isinstance(own, dict) else {}
    out = {}
    for k, v in IZVORI_CAPS.items():
        try:
            out[k] = min(type(v)(own[k]), v) if own.get(k) is not None else v
        except (TypeError, ValueError):
            out[k] = v
    return out


def izvori_capped(cfg):
    out = dict(cfg)
    caps = izvori_caps(cfg)
    for k in ("max_sol_per_trade", "max_open", "max_loss_day", "max_sol_per_day", "max_buys_day", "size_sol"):
        out[k] = caps[k]
    out["max_cost_pct"] = min(float(cfg.get("max_cost_pct") or caps["max_cost_pct"]), caps["max_cost_pct"])
    return out


def izvori_on(con):
    return settings.pravi_novac_izvori(con=con)


def izvori_buys(con, now, mode="live", tz=None):
    """The konsenzus buys of the Zagreb day in this mode (open, closed or in flight)."""
    return con.execute("SELECT COUNT(*) FROM positions WHERE opened_ts>=? AND mode=? AND status IN "
                       "('open','closed','pending') AND LOWER(COALESCE(reason, '')) LIKE ?",
                       (_day_start(now, tz), mode, IZVORI_SRC + "%")).fetchone()[0] or 0


# 15.11. popodne (owner: "Kreni odmah tradeat s pravim novcem" for the midcaps; "Dnevni gubitak može ići do 0,3, ali
# cilj je napraviti više tradeova"; veliki/, switch pravi_novac_veliki): a real buy of the midcap range (a league.db
# trade whose source starts with VELIKI_SRC) is held to veliki/gate.real_caps INSTEAD of LIVE_CAPS (Grok autotrade's
# money limits: 0.3 SOL of automatic buys a day stopped the first midcap buy at 12:48 because other strategies had used
# 0.7 SOL earlier that day) and never pravi_novac_sve's: 0.1 SOL a trade, max_open counts EVERY live position (all
# strategies), max_buys_day and max_sol_per_day count the midcap buys of the Zagreb day (its DCA lots included),
# max_loss_day the day's realized result of every live position (-0.3 SOL stops new buys), max_cost_pct 6 %. run_trade
# asks veliki/gate.real_refusal (switch + proof mode + BTC) before; buy() asks the switch again.
VELIKI_SRC = "veliki:"


def is_veliki(reason):
    return str(reason or "").strip().lower().startswith(VELIKI_SRC)


def veliki_caps(cfg=None):
    """veliki/gate.real_caps as executor caps (trade/config.json "pravi_novac_veliki" may lower them)."""
    try:
        from veliki import gate
        rc = gate.real_caps(cfg)
    except Exception:  # noqa: BLE001 - unreadable: the code's caps of 15.11.
        rc = {"size_sol": 0.1, "max_open": 5, "max_buys_day": 20, "max_loss_day_sol": 0.3}   # unreadable: the smaller
    size = float(rc["size_sol"])
    n = int(rc["max_buys_day"])
    return {"size_sol": size, "max_sol_per_trade": size, "max_open": int(rc["max_open"]), "max_buys_day": n,
            "max_loss_day": float(rc["max_loss_day_sol"]), "max_sol_per_day": round(n * size + 0.1, 3),
            "max_cost_pct": 6.0}


def veliki_capped(cfg):
    out = dict(cfg)
    caps = veliki_caps(cfg)
    for k in ("max_sol_per_trade", "max_open", "max_loss_day", "max_sol_per_day", "max_buys_day", "size_sol"):
        out[k] = caps[k]
    out["max_cost_pct"] = min(float(cfg.get("max_cost_pct") or caps["max_cost_pct"]), caps["max_cost_pct"])
    return out


def veliki_on(con):
    try:
        return settings.flag("pravi_novac_veliki", con) == "live"
    except Exception:  # noqa: BLE001 - unreadable = off
        return False


# 18.11. (vlasnik: "da tradeovi s pravim novcem postanu profitabilni"; veliki/ucenik.py, owner switch
# pravi_novac_nauceno, default off): the real twin of a learned-rule demo entry is a league.db trade of LEAGUE_USER whose
# source starts with NAUCENO_SRC. It IS a midcap buy (is_veliki: the same caps, the same day count and spend as the
# midcap range, shared by both), with two differences: its switch is pravi_novac_nauceno, never pravi_novac_veliki
# (each is decided apart), and its stake is never above NAUCENO_SOL (0.1 SOL), whatever the midcap range's own stake is.
NAUCENO_SRC = "veliki: naučeno"
NAUCENO_SOL = 0.1


def is_nauceno(reason):
    return str(reason or "").strip().lower().startswith(NAUCENO_SRC)


def nauceno_on(con):
    try:
        return settings.flag(settings.NAUCENO_SWITCH, con) == "live"
    except Exception:  # noqa: BLE001 - unreadable = off
        return False


def veliki_buys(con, now, mode="live", tz=None):
    """The midcap buys of the Zagreb day in this mode (open, closed or in flight), DCA lots included."""
    return con.execute("SELECT COUNT(*) FROM positions WHERE opened_ts>=? AND mode=? AND status IN "
                       "('open','closed','pending') AND LOWER(COALESCE(reason, '')) LIKE ?",
                       (_day_start(now, tz), mode, VELIKI_SRC + "%")).fetchone()[0] or 0


def veliki_spent(con, now, mode="live", tz=None):
    """SOL put into midcap buys of the Zagreb day in this mode."""
    return con.execute("SELECT COALESCE(SUM(sol_in),0) FROM positions WHERE opened_ts>=? AND mode=? AND status IN "
                       "('open','closed','pending') AND LOWER(COALESCE(reason, '')) LIKE ?",
                       (_day_start(now, tz), mode, VELIKI_SRC + "%")).fetchone()[0] or 0.0


def switch_on(con):
    """The owner's switch pravi_novac_sve, read from this trade.db connection (unreadable = off)."""
    return settings.pravi_novac_sve(con=con)


def switch_caps(cfg=None):
    """SWITCH_CAPS, each the smaller of the code's and trade/config.json "pravi_novac_sve"'s (cfg = merged settings)."""
    own = (cfg or {}).get("pravi_novac_sve")
    own = own if isinstance(own, dict) else {}
    out = {}
    for k, v in SWITCH_CAPS.items():
        try:
            out[k] = min(type(v)(own[k]), v) if own.get(k) is not None else v
        except (TypeError, ValueError):
            out[k] = v
    return out


def switch_capped(cfg):
    """The settings an automatic real buy under the switch is checked with: SWITCH_CAPS replace the stake, the day's
    spend and loss and the open count (the reserve, the cost cap and the rest stay the owner's)."""
    out = dict(cfg)
    caps = switch_caps(cfg)
    for k in ("max_sol_per_trade", "max_open", "max_loss_day", "max_sol_per_day", "max_buys_day"):
        out[k] = caps[k]
    out["size_sol"] = caps["size_sol"]
    return out


def auto_buys(con, now, mode="live", tz=None):
    """Automatic buys today (Zagreb day) in this mode: what SWITCH_CAPS max_buys_day counts (open, closed or in
    flight; refused and failed ones are not buys)."""
    return con.execute("SELECT COUNT(*) FROM positions WHERE opened_ts>=? AND mode=? "
                       "AND status IN ('open','closed','pending')" + _NOT_OWN,
                       (_day_start(now, tz), mode, *OWN_REASONS)).fetchone()[0] or 0


def strategy_of(source):
    """The strategy behind a demo trade's source (league.db trades.source = the real position's reason), in the words
    of the flags: copies of the owner's follows "kopiranje", insider wallets "insider_copy", the fast path, momentum,
    range, proposals, SimianX; the owner's own and Grok's buys "ručno" / "grok"."""
    s = (source or "").strip()
    low = s.lower()
    if low.startswith("ručno"):
        return "ručno"
    if low.startswith("grok auto"):
        return "grok"
    if low.startswith(MJERENJE_SRC):   # 18.11.: the owner's one-time cost measurement, never a strategy's result
        return "mjerenje"
    if low.startswith("copy ") and low.endswith("(fast)") or low.startswith("fast path"):
        return "fast_path"
    if low.startswith("copy wallet insajder prije poziva"):
        return "insider_copy"
    if low.startswith("copy "):
        return "kopiranje"
    if low.startswith("momentum"):
        return "momentum_scalp"
    if low.startswith("range lot"):
        return "range_dca"
    if low.startswith("prijedlog"):
        return "proposals"
    if low.startswith("simianx"):
        return "simianx"
    return (s.split(":")[0].split(" ")[0] or "?")[:30]


def switch_status(con, now, cfg=None, tz=None):
    """The switch's day in numbers (trade.db only, no network): {"on", "buys", "max_buys_day", "open", "max_open",
    "pnl", "max_loss_day", "spent", "max_sol_per_day", "stopped", "by": {strategy: {"buys", "pnl", "open"}}}. pnl =
    day_pnl (every live position closed today, every fee of the day); per strategy the closed positions' SOL back
    minus in and their own fees."""
    caps = switch_caps(cfg)
    start = _day_start(now, tz)
    by = {}
    for reason, st, opened, closed, sin, sback, fees in con.execute(
            "SELECT reason, status, opened_ts, closed_ts, sol_in, sol_back, fees_sol FROM positions WHERE mode='live' "
            "AND ((opened_ts>=? AND status IN ('open','closed','pending')) OR (status='closed' AND closed_ts>=?) "
            "OR status IN ('open','pending'))", (start, start)).fetchall():
        d = by.setdefault(strategy_of(reason), {"buys": 0, "pnl": 0.0, "open": 0})
        if (opened or 0) >= start:
            d["buys"] += 1
        if st in ("open", "pending"):
            d["open"] += 1
        if st == "closed" and (closed or 0) >= start:
            d["pnl"] += (sback or 0) - (sin or 0) - (fees or 0)
    n_open = con.execute("SELECT COUNT(DISTINCT COALESCE(token, '#' || id)) FROM positions WHERE status IN "
                         "('open','pending') AND mode='live'").fetchone()[0]
    pnl = day_pnl(con, now, "live", tz)
    return {"on": switch_on(con), "buys": auto_buys(con, now, "live", tz), "max_buys_day": caps["max_buys_day"],
            "open": n_open, "max_open": caps["max_open"], "pnl": pnl, "max_loss_day": caps["max_loss_day"],
            "spent": auto_spent(con, now, "live", tz), "max_sol_per_day": caps["max_sol_per_day"],
            "size_sol": caps["size_sol"],
            # 18.11.: the stop compares the day without the owner's cost measurement (as buy_checks / auto_hard do)
            "stopped": day_pnl(con, now, "live", tz, strategije=True) <= -caps["max_loss_day"], "by": by}


def switch_line(st):
    """One Croatian log line of switch_status (the daily summary run_trade prints)."""
    def sol(v):
        return f"{v:+.3f}".replace(".", ",")

    def g(v):
        return f"{v:g}".replace(".", ",")
    parts = [f"{k}: kupnji {v['buys']}, otvoreno {v['open']}, {sol(v['pnl'])} SOL"
             for k, v in sorted(st["by"].items(), key=lambda kv: (-kv[1]["buys"], kv[0]))]
    return (f"PRAVI NOVAC danas: kupnji {st['buys']}/{st['max_buys_day']}, otvoreno {st['open']}/{st['max_open']}, "
            f"ostvareno {sol(st['pnl'])} SOL (stop -{g(st['max_loss_day'])} SOL"
            + (", DOSEGNUT: nove automatske kupnje stoje do sljedećeg dana" if st["stopped"] else "")
            + f"), potrošeno {st['spent']:.2f}/{g(st['max_sol_per_day'])} SOL".replace(".", ",")
            + (" | po strategiji: " + "; ".join(parts) if parts else ""))


# 18.11. (vijeće: "separate the real trades since 15.11., realised and open PnL, per strategy"): the real-money result
# by strategy since 15.11.2026 00:00 UTC, read-only (SELECTs on positions; no schema change). The strategy of a real
# position is its `reason`: for a mirrored buy that is the demo trade's source (run_trade passes league.db
# trades.source), for the owner's and Grok's own buys "ručno ..." / "Grok auto ...", so strategy_of() names it without
# a guess. The midcap range is split by its rule only where the reason itself says it (veliki/live.enter writes
# "veliki: dnevna zona ..." for the intraday rule, "veliki: podrška ..." / "veliki: bez raspona" for the 7-day rule,
# "veliki: DCA ..." for a DCA lot, "veliki: naučeno ..." for the learned rule's real twin, veliki/ucenik). A reason
# that names no strategy stays under its own first word.
# What it does NOT say: the unrealised result of the open positions (that needs live quotes; only their count and the
# SOL in them), and positions opened before 15.11. that closed after it.
STRATEGY_SINCE = 1794700800     # 2026-11-15 00:00:00 UTC
STRATEGY_PREFIX = "pravi novac po strategiji od 15.11.: "


def strategy_label(reason):
    """strategy_of(reason), the midcap range split by its rule where the reason says which one it was."""
    k = strategy_of(reason)
    if k != "veliki":
        return k
    low = str(reason or "").lower()
    if is_nauceno(reason):
        return "naučeno"
    if low.startswith("veliki: dca"):
        return "veliki DCA lot"
    if "dnevna zona" in low:
        return "veliki dnevni raspon"
    if "podrška" in low or "bez raspona" in low:
        return "veliki raspon 7 d"
    return "veliki"


def strategy_result(con, since=STRATEGY_SINCE):
    """{"since", "by": {strategy: {"closed", "sol", "ret" (mean net return per closed trade, None without one),
    "wins", "open", "open_sol"}}, "total": the same over all} of the LIVE positions opened at or after `since`
    (trade.db positions; read-only). sol = SOL back minus SOL in minus the position's network fees, as day_pnl and
    switch_status count it; ret per trade = that over its SOL in. Refused and failed buys are not positions."""
    by = {}
    tot = {"closed": 0, "sol": 0.0, "rets": [], "wins": 0, "open": 0, "open_sol": 0.0}
    for reason, st, sin, sback, fees in con.execute(
            "SELECT reason, status, sol_in, sol_back, fees_sol FROM positions WHERE mode='live' AND opened_ts>=? "
            "AND status IN ('open','closed','pending') ORDER BY id", (int(since),)).fetchall():
        # a buy in flight carries the intent's text, not its source yet: said as that, never as a strategy
        name = "kupnja u tijeku" if st == "pending" else strategy_label(reason)
        d = by.setdefault(name, {"closed": 0, "sol": 0.0, "rets": [], "wins": 0, "open": 0, "open_sol": 0.0})
        sin, sback, fees = sin or 0.0, sback or 0.0, fees or 0.0
        for x in (d, tot):
            if st == "closed":
                pnl = sback - sin - fees
                x["closed"] += 1
                x["sol"] += pnl
                x["wins"] += 1 if pnl > 0 else 0
                if sin > 0:
                    x["rets"].append(pnl / sin)
            else:
                x["open"] += 1
                x["open_sol"] += sin
    for x in list(by.values()) + [tot]:
        rets = x.pop("rets")
        x["ret"] = sum(rets) / len(rets) if rets else None
    return {"since": int(since), "by": by, "total": tot}


def strategy_line(res):
    """One Croatian line of strategy_result (run_trade prints it at the start and once a day; the council's brief)."""
    def one(name, d):
        avg = f"{d['ret'] * 100:+.1f}%" if d["ret"] is not None else "—"
        return (f"{name} n={d['closed']}, zbroj {d['sol']:+.3f} SOL, prosjek {avg}, otvoreno {d['open']}"
                + (f" ({d['open_sol']:.2f} SOL)" if d["open"] else ""))
    by = (res or {}).get("by") or {}
    if not by:
        return STRATEGY_PREFIX + "još nema pravih pozicija"
    parts = [one(k, v) for k, v in sorted(by.items(), key=lambda kv: (-(kv[1]["closed"] + kv[1]["open"]), kv[0]))]
    return (STRATEGY_PREFIX + "; ".join(parts) + "; " + one("UKUPNO", res["total"])
            + " (zatvorene: SOL natrag − SOL unutra − mrežne naknade; nerealizirano otvorenih nije uračunato)")


# 16.11. (vlasnik, jutarnji izvještaj; CLAUDE.md "dnevni gubitak 0,5 SOL", "0,1 SOL po tradeu"): ONE global cap over
# EVERY automatic real buy together, whatever path or switch (LIVE_CAPS, pravi_novac_sve, pravi_novac_izvori,
# pravi_novac_veliki, oscilator, Grok autotrade): the day's realized result of every live position, fees included
# (day_pnl), at or under -max_loss_day stops every automatic real buy until the next Zagreb day, and no automatic real
# stake is above max_sol_per_trade. HARD (no override, no flag, no config raises it); each path's own caps above stay
# and the strictest wins (buy() cuts the stake to the smallest, buy_checks refuses the rest, and buy() asks
# final_check once more right before the swap). The owner's own manual buys keep his rules (11.11.: "ručno nadjačava");
# Grok autotrade's buys reach buy() through his buy path as a manual stake (ui/grokauto -> ui/pravitrade._post_buy ->
# run_trade manual=True) but no person placed them, so they are automatic here (is_auto).
AUTO_HARD_CAPS = {"max_sol_per_trade": 0.1, "max_loss_day": 0.5}
# 16.11. popodne (vlasnik, odgovor na pitanje o kapitalu: "5 pozicija × 0,2 SOL"): the midcap range's automatic buys
# (reason "veliki: ...") may stake 0.2 SOL; every other automatic buy (Grok, the other strategies) stays at 0.1, and
# the day's loss cap is one for all of them
AUTO_VELIKI_SOL = 0.2


def auto_cap(veliki=False):
    """The global stake cap of one automatic real buy (SOL)."""
    return AUTO_VELIKI_SOL if veliki else AUTO_HARD_CAPS["max_sol_per_trade"]
GROK_AUTO_SRC = "grok auto"   # ui/grokauto.SRC "Grok auto (MCP)"; a Grok request the owner approved is his own buy


def is_auto(reason, manual):
    """True for an automatic real buy: every buy that is not the owner's own (manual=False) and Grok autotrade's."""
    return (not manual) or str(reason or "").strip().lower().startswith(GROK_AUTO_SRC)


def auto_hard(con, size_sol, now, tz=None, veliki=False):
    """The global cap's refusals of one automatic real buy: [(key, text)] (empty = within the cap)."""
    out = []
    cap = auto_cap(veliki)
    if size_sol > cap + 1e-9:
        out.append(("auto_stake", f"globalni strop automatskih pravih kupnji: ulog {size_sol:g} SOL iznad {cap:g} SOL"))
    lost = day_pnl(con, now, "live", tz, strategije=True)   # 18.11.: without the owner's cost measurement
    lim = AUTO_HARD_CAPS["max_loss_day"]
    if lost <= -lim + 1e-12:
        out.append(("auto_day_loss", f"globalni dnevni gubitak {lost:+.3f} SOL (sve prave pozicije, s naknadama), "
                                     f"granica -{lim:g} SOL: sve automatske prave kupnje stoje do sljedećeg dana "
                                     "(Zagreb), otvorene pozicije zadržavaju izlaze"))
    return out


def final_check(con, size_sol, now, live, auto, tz=None, veliki=False):
    """16.11.: the last check before the swap is sent (after the gate and the sell check, which may take seconds):
    the kill switch for every buy, the global cap for every automatic real buy. The refusal text or None."""
    if os.path.exists(STOP_FILE):
        return "kill switch (trade/STOP)"
    if live and auto:
        refused = auto_hard(con, size_sol, now, tz, veliki)
        if refused:
            return refused[0][1]
    return None


def live_spent(con, now, tz=None):
    """SOL put into EVERY live buy today (the owner's own included): what LIVE_CAPS max_sol_per_day limits."""
    return con.execute("SELECT COALESCE(SUM(sol_in),0) FROM positions WHERE opened_ts>=? AND mode='live' "
                       "AND status IN ('open','closed','pending')", (_day_start(now, tz),)).fetchone()[0] or 0.0


# 11.11. (owner: "Ako ručno postavim drugačije ... ručno uvijek nadjačava ono što je zapisano programski. I ne samo za
# to, nego za količinu kupljenoga. Može izaći upozorenje ... ali ako se složim, ručno uvijek nadjačava sve ostalo"):
# every reason a buy is refused is HARD or SOFT. HARD = physics and safety, nothing overrides it: the kill switch, an
# empty stake, too little SOL for the stake, its fees and the fees to sell what is held, no route to sell back. SOFT =
# the owner's own limits (stake per trade, open positions, the day's loss stop, his reserve, the swap's cost cap, his
# per-token cap): his confirmed manual buy passes them (ui/pravitrade._post_buy with override=1, then run_trade hands
# the mark to buy(override=...)). Grok's buys, copies and every automatic buy never carry an override.
HARD, SOFT = "hard", "soft"
# The rules of the owner's CLAUDE.md that stay hard even for his own confirmed buy: "rug" (a rugged token locks the
# buy). 11.11. (owner: "Mogu se kupovati tokeni ispod 30.000 market capa uz dovoljno dobar razlog"): "mc30k" is out
# of the set, so MC under $30k is a SOFT reason of the owner's own manual buy only, and it also needs his typed
# reason (ui/pravitrade.REASON_MIN); Grok, copies and every automatic buy never buy under $30k. Putting "mc30k" back
# makes it hard again everywhere (the page and run_trade's MIN_MCAP check); taking "rug" out would make that soft.
HARD_RULES = frozenset({"rug"})


def buy_checks(con, cfg, size_sol, now, live, balance=None, token=None, add=False, manual=False, izvori=False,
               mcap=None, veliki=False, auto=None):
    """Every reason this buy is refused, in gate_buy's order, as (kind, key, text): kind HARD or SOFT (above), key a
    short name of the rule (stop, stake, dup, day_spend, day_loss, max_open, balance, reserve, mikrokap). A generator:
    gate_buy stops at the first reason, the owner's buy (ui/pravitrade) and an overridden one read on, so the wallet's
    RPC is asked only when the checks before it are through. mcap (15.11.): the entry's market cap, for the microcap
    gate of an automatic buy (trade/capgate). auto (16.11.): an automatic buy (default: not manual; Grok autotrade's
    manual stake passes auto=True, is_auto): the global cap AUTO_HARD_CAPS, HARD, after the path's own caps."""
    if os.path.exists(STOP_FILE):   # always the first check: no flag, path or override comes before it
        yield HARD, "stop", "kill switch (trade/STOP)"
    auto = (not manual) if auto is None else bool(auto)
    # 15.11. (vlasnik: "inače sada tradamo samo mid-capove: 5M-150M $"; trade/capgate): an AUTOMATIC real buy under
    # MIN_MC is a HARD reason (no override, no moonshot: the exception is demo only); the owner's own buy is not held
    if not manual and mcap is not None:
        from trade import capgate
        if capgate.on(con) and mcap < capgate.cfg()["min_mc"]:
            mm = capgate.money(capgate.cfg()["min_mc"])
            yield HARD, "mikrokap", (f"MC ispod {mm} (mikrokap): MC ${mcap:,.0f}; automatski pravi ulaz samo uz MC od "
                                     f"{mm} $ naviše, moonshot iznimka samo u demu")
    # 14.11.: the owner's switch pravi_novac_sve: an automatic live buy is held to SWITCH_CAPS (each refusal names its
    # cap); with the switch off, LIVE_CAPS exactly as before
    # 15.11.: a konsenzus buy under its own switch pravi_novac_izvori: IZVORI_CAPS (never pravi_novac_sve's)
    iz = live and not manual and izvori and izvori_on(con)
    ve = live and not manual and veliki and not izvori   # 15.11.: a midcap buy: veliki/gate.real_caps (VELIKI_SRC)
    sw = live and not manual and not izvori and not veliki and switch_on(con)
    if iz:
        cfg = izvori_capped(cfg)
    elif ve:
        cfg = veliki_capped(cfg)
    elif sw:
        cfg = switch_capped(cfg)
    elif live and not manual:   # 11.11.: the owner's own buy keeps his settings (Jure 10.11.: "makni limit")
        cfg = live_capped(cfg)
    cap = "strop pravi_novac_izvori " if iz else "strop pravi_novac_veliki " if ve else "strop pravi_novac_sve " if sw else ""
    mode = "live" if live else "dry"
    if token is not None and not add:   # T22: an auto follow and a manual follow of the same coin = one real position
        dup = con.execute("SELECT id FROM positions WHERE token=? AND mode=? AND status IN ('open','pending')",
                          (token, mode)).fetchone()
        if dup:
            yield SOFT, "dup", f"već postoji otvorena pozicija u ovom tokenu (#{dup[0]})"
    if size_sol <= 0 or size_sol > cfg["max_sol_per_trade"]:
        yield (HARD if size_sol <= 0 else SOFT), "stake", (f"{cap}max_sol_per_trade: " if sw and size_sol > 0 else "") + \
            f"{size_sol} SOL iznad limita {cfg['max_sol_per_trade']}"
    tz = cfg.get("day_tz")
    if sw or iz or ve:
        n_buys = izvori_buys(con, now, mode, tz) if iz else veliki_buys(con, now, mode, tz) if ve else \
            auto_buys(con, now, mode, tz)
        if n_buys >= cfg["max_buys_day"]:
            yield SOFT, "max_buys_day", (f"{cap}max_buys_day: danas već {n_buys} automatskih pravih kupnji od "
                                         f"{cfg['max_buys_day']}; nove sutra (Zagreb)")
    if not manual:
        spent = veliki_spent(con, now, mode, tz) if ve else auto_spent(con, now, mode, tz)
        if spent + size_sol > cfg["max_sol_per_day"] + 1e-9:
            yield SOFT, "day_spend", (f"{cap}max_sol_per_day: " if sw or ve else "") + \
                f"dnevni limit automatskih kupnji: potrošeno {spent:.3f} od {cfg['max_sol_per_day']} SOL"
    if "max_loss_day" in cfg:
        lost = day_pnl(con, now, mode, tz, strategije=True)   # 18.11.: without the owner's cost measurement
        if lost <= -cfg["max_loss_day"]:
            yield SOFT, "day_loss", ((f"{cap}max_loss_day: dnevni gubitak {lost:+.3f} SOL, granica -{cfg['max_loss_day']} "
                                      "SOL: nove automatske kupnje stoje do sljedećeg dana (Zagreb), otvorene pozicije "
                                      "zadržavaju izlaze") if sw or ve else
                                     f"dnevni gubitak {lost:+.3f} SOL, granica -{cfg['max_loss_day']} SOL: stop do ponoći")
    if live and auto:   # 16.11.: the global cap of every automatic real buy, HARD (never overridden); after the
        # path's own caps so a refusal both give names the path's cap first (the strictest wins either way)
        for key, text in auto_hard(con, size_sol, now, tz, ve):
            yield HARD, key, text
    n_open = con.execute("SELECT COUNT(*) FROM positions WHERE status IN ('open','pending') AND mode=?",
                         (mode,)).fetchone()[0]
    # 10.11. (Jure: dokupnja u istu poziciju): a token bought in two lots is one position against max_open; the
    # reserve for selling (below) still counts every lot, each is sold by its own swap
    n_tok = con.execute("SELECT COUNT(DISTINCT COALESCE(token, '#' || id)) FROM positions WHERE status IN ('open','pending') AND mode=?",
                        (mode,)).fetchone()[0]
    held = token is not None and con.execute(
        "SELECT 1 FROM positions WHERE token=? AND mode=? AND status IN ('open','pending') LIMIT 1",
        (token, mode)).fetchone() is not None
    if n_tok >= cfg["max_open"] and not held:
        yield SOFT, "max_open", (f"{cap}max_open: {n_tok} otvorenih pravih pozicija (sve strategije zajedno), najviše "
                                 f"{cfg['max_open']}" if sw or ve else f"{n_tok} otvorenih pozicija")
    if live:
        if balance is None:
            balance = wallet.sol_balance(wallet.address())
        need = size_sol + BUY_OVERHEAD_SOL + reserve_sol(cfg, n_open + 1)
        if balance < need:
            text = (f"premalo SOL-a: stanje {balance:.4f}, treba {need:.4f} (ulog {size_sol:g} + naknade i depozit "
                    f"{BUY_OVERHEAD_SOL:g} + rezerva za prodaju {reserve_sol(cfg, n_open + 1):.4f})")
            # the fees of this buy and of selling every position that would be open are physics; only the owner's
            # own "Uvijek ostavi u walletu" (min_sol_reserve) above that floor is his limit
            floor = size_sol + BUY_OVERHEAD_SOL + reserve_sol({}, n_open + 1)
            if balance < floor:
                yield HARD, "balance", text
            else:
                yield SOFT, "reserve", (f"{text}; bez tvoje rezerve „Uvijek ostavi u walletu” "
                                        f"({cfg.get('min_sol_reserve', 0):g} SOL) dovoljno je {floor:.4f}")
        # 15.11. (vlasnik: "neka trguje s pravim novcem, dok ako padne ispod jedne solane, onda ćemo ugasiti"): the
        # wallet's VALUE (SOL + open real positions + USDC) under EQUITY_FLOOR_SOL (trade/config.json min_equity_sol)
        # stops every AUTOMATIC real buy until it is back above (or the owner lowers the floor); exits keep running and
        # his own manual buys are not held
        if not manual:
            val, src = equity_value(con, now, balance)
            fl = equity_floor(cfg)
            if val is not None and val < fl:
                yield HARD, "equity_floor", (f"vrijednost novčanika {val:.3f} SOL ispod poda {fl:g} SOL ({src}): "
                                             "automatske prave kupnje stoje, izlazi rade; vlasnik odlučuje")


EQUITY_FLOOR_SOL = 1.0
EQUITY_FRESH_S = 1800


def equity_floor(cfg=None):
    """The owner's floor of the wallet's value for automatic real buys (trade/config.json min_equity_sol, 1 SOL)."""
    try:
        v = (cfg or {}).get("min_equity_sol")
        return float(v) if v is not None else EQUITY_FLOOR_SOL
    except (TypeError, ValueError):
        return EQUITY_FLOOR_SOL


def equity_value(con, now, balance=None):
    """(value in SOL or None, where from): the newest trade/equity snapshot (SOL + open real positions + USDC) when it
    is at most EQUITY_FRESH_S old, else the wallet's SOL balance + the SOL put into the open real positions."""
    try:
        r = con.execute("SELECT ts, sol, usdc, tokens_sol, sol_usd FROM equity ORDER BY ts DESC LIMIT 1").fetchone()
    except Exception:  # noqa: BLE001 - no equity table yet
        r = None
    if r and r[0] and now - r[0] <= EQUITY_FRESH_S and r[1] is not None:
        usdc = (r[2] or 0.0) / r[4] if r[4] else 0.0
        return round((r[1] or 0.0) + (r[3] or 0.0) + usdc, 6), "zadnja snimka vrijednosti"
    if balance is None or balance == float("inf"):
        return None, "nepoznato"
    try:
        held = con.execute("SELECT COALESCE(SUM(sol_in), 0) FROM positions WHERE mode='live' AND status IN "
                           "('open','pending')").fetchone()[0] or 0.0
    except Exception:  # noqa: BLE001
        held = 0.0
    return round(balance + held, 6), "stanje SOL-a + uloženo u otvorene pozicije"


def gate_buy(con, cfg, size_sol, now, live, balance=None, token=None, add=False, manual=False, override=False,
             izvori=False, mcap=None, veliki=False, auto=None):
    """Reason the buy is blocked, or None. add (10.11.): the owner's manual buy of a token already held: one more
    lot of the same position, so the duplicate check does not apply (every other limit does).
    manual (10.11., Jure: "makni limit"): the owner's own buy (quick buy, a lot added, his DCA order, a Grok request
    he approved) is not held by the day's spending limit max_sol_per_day; the Autopilot's copies still are. The
    stake per trade, the day's loss stop, the number of positions and the wallet balance hold for every buy.
    live (11.11., owner's rule C): LIVE_CAPS on top for every automatic live buy (not for manual).
    override (11.11.): the owner confirmed this manual buy over his limits: only the HARD reasons hold (buy_checks);
    without manual it is ignored. mcap (15.11.): the microcap gate of an automatic buy (buy_checks). auto (16.11.):
    an automatic buy (default not manual; Grok autotrade: is_auto), held to the global AUTO_HARD_CAPS."""
    return _gate(con, cfg, size_sol, now, live, balance, token, add, manual, override, izvori, mcap, veliki, auto)[0]


def _gate(con, cfg, size_sol, now, live, balance=None, token=None, add=False, manual=False, override=False,
          izvori=False, mcap=None, veliki=False, auto=None):
    """(reason the buy is blocked or None, the SOFT reasons an override let pass)."""
    ov = bool(override) and manual and not ((not manual) if auto is None else auto)
    passed = []
    for kind, _key, text in buy_checks(con, cfg, size_sol, now, live, balance, token, add, manual, izvori, mcap,
                                       veliki, auto):
        if kind == HARD or not ov:
            return text, passed
        passed.append(text)
    return None, passed


# what one sale costs at most in network fees (signature + a high priority fee), what a buy adds on top of its
# stake (rent of the new token account ~0.00204 + fees), and the floor that always stays in the wallet so the
# open positions can still be sold (Nicholas 3.11.: "mora ostati minimum, barem za dvije transakcije")
SELL_COST_SOL = 0.002
BUY_OVERHEAD_SOL = 0.003
RESERVE_FLOOR_SOL = 2 * SELL_COST_SOL + 0.006   # 0.01: two sales + a margin


def reserve_sol(cfg, n_positions):
    """SOL that must stay in the wallet: the owner's reserve, but never less than the floor or than the fees to
    sell every position that would be open."""
    return max(cfg.get("min_sol_reserve", 0), RESERVE_FLOOR_SOL, n_positions * SELL_COST_SOL)


def _jup(route, input_mint, output_mint, amount_raw, live, max_cost_pct, limit=None, slippage_bps=None):
    try:
        if slippage_bps:   # 13.11.: only an exit's capped first try (sell(slip_cap_pct)); fakes keep their signature
            o = jupiter.order(input_mint, output_mint, amount_raw, taker=wallet.address(), route=route,
                              slippage_bps=slippage_bps)
        else:
            o = jupiter.order(input_mint, output_mint, amount_raw, taker=wallet.address(), route=route)
    except Exception as e:
        # 13.11.: no_answer = the endpoint itself is down, so an exit's fallback does not wait on it a second time
        return {"status": "failed", "retry": True, "error": f"{ROUTE_HR[route]} ne odgovara ({type(e).__name__})",
                "amount_in": amount_raw, "no_answer": True}
    res = {"amount_in": int(o.get("inAmount") or amount_raw), "amount_out": int(o.get("outAmount") or 0),
           "cost_pct": jupiter.cost_pct(o), "request_id": o.get("requestId"), "error": None,
           "fee_lamports": jupiter.fee_lamports(o), "prio_lamports": int(o.get("prioritizationFeeLamports") or 0),
           "error_code": o.get("errorCode"),
           "impact_pct": jupiter.impact_pct(o)}   # 18.11.: the quote's price impact, reporting only (trade/mjerenje.py)
    if not res["amount_out"]:
        hs = o.get("http_status") if isinstance(o, dict) else None
        return {**res, "status": "failed", "retry": True, "error": o.get("error") or "nema rute",
                "http_status": hs, "no_answer": bool(hs and (hs == 429 or hs >= 500))}
    if max_cost_pct is not None and res["cost_pct"] is not None and res["cost_pct"] > max_cost_pct:
        return {**res, "status": "blocked", "error": f"trošak {res['cost_pct']}% > {max_cost_pct}%"}
    if limit is not None:   # 10.11. (Grok MCP audit 3): the price this very order pays, before anything is signed
        why = _over_limit(limit, output_mint, o, res)
        if why:
            return {**res, "status": "blocked", "error": why}
    if not live:
        return {**res, "status": "dry"}
    if not o.get("transaction"):
        return {**res, "status": "failed", "retry": o.get("errorCode") != 1,
                "error": o.get("errorMessage") or o.get("error") or "Jupiter nije dao transakciju"}
    before = None
    if output_mint != jupiter.SOL:   # to tell later whether a buy landed when Jupiter does not answer
        try:
            before = wallet.token_raw_balance(wallet.address(), output_mint)
        except Exception:  # noqa: BLE001
            before = None
    try:
        signed = wallet.sign(o["transaction"])
    except Exception as e:  # noqa: BLE001 - 18.11. (audit): nothing was sent, so this is a failed try like any other:
        # it gets its order row (the token in the log, the sale's backoff) and the next route goes out in the same
        # pass, instead of an exception that ended the whole real-money pass once a second for minutes
        return {**res, "status": "failed", "retry": True,
                "error": f"{ROUTE_HR[route]}: nalog nije potpisan ({type(e).__name__}: {str(e)[:80]})"}
    r = jupiter.execute(signed, o["requestId"], route=route)
    if r is None:   # never answered: the swap may or may not have landed, never try another route blind
        if before is not None:
            try:
                after = wallet.token_raw_balance(wallet.address(), output_mint)
            except Exception:  # noqa: BLE001
                after = before
            if after > before:
                return {**res, "status": "ok", "amount_out": after - before, "error": None,
                        "note": "Jupiter nije odgovorio, ali tokeni su u walletu"}
        return {**res, "status": "failed", "retry": False, "error": f"{ROUTE_HR[route]} nije potvrdio swap; "
                "provjeri wallet na Solscanu"}
    code = r.get("code")
    if r.get("status") != "Success":
        return {**res, "status": "failed", "code": code, "signature": r.get("signature"),
                "retry": code in jupiter.NOT_LANDED or code == 6001, "error": jupiter.explain(code, r.get("error")),
                # a transaction that landed and failed onchain still paid its network fee
                "fee_lamports": res["fee_lamports"] if r.get("signature") and code not in jupiter.NOT_LANDED else 0}
    return {**res, "status": "ok", "signature": r.get("signature"), "error": None, "code": 0,
            "amount_in": int(r.get("totalInputAmount") or r.get("inputAmountResult") or res["amount_in"]),
            "amount_out": int(r.get("totalOutputAmount") or r.get("outputAmountResult") or res["amount_out"])}


def _pump(input_mint, output_mint, amount_raw, live):
    """PumpPortal fallback (live only): amounts read from the wallet before and after, fees included in them."""
    if not live:
        return {"status": "failed", "retry": False, "error": "nema rute (PumpPortal radi samo uživo)",
                "amount_in": amount_raw}
    addr = wallet.address()
    buying = input_mint == jupiter.SOL
    mint = output_mint if buying else input_mint
    try:
        sol0, tok0 = wallet.sol_balance(addr), wallet.token_raw_balance(addr, mint)
        if buying:
            tx = pumpportal.trade_local(addr, "buy", mint, round(amount_raw / LAMPORTS, 9), True)
        else:
            pct = min(100.0, 100.0 * amount_raw / tok0) if tok0 else 100.0
            tx = pumpportal.trade_local(addr, "sell", mint, f"{pct:.4f}%", False)
        sig = wallet.send(wallet.sign_raw(tx))
    except Exception as e:
        return {"status": "failed", "retry": False, "error": f"PumpPortal: {type(e).__name__}: {e}"[:300],
                "amount_in": amount_raw}
    ok = wallet.confirmed(sig)
    sol1, tok1 = wallet.sol_balance(addr), wallet.token_raw_balance(addr, mint)
    if not ok:
        return {"status": "failed", "retry": False, "signature": sig, "amount_in": amount_raw,
                "error": "PumpPortal transakcija nije prošla" if ok is False else "PumpPortal: nije potvrđeno u 45 s",
                "fee_lamports": max(0, int(round((sol0 - sol1) * LAMPORTS))) if ok is False else 0}
    if buying:
        return {"status": "ok", "signature": sig, "amount_in": int(round((sol0 - sol1) * LAMPORTS)),
                "amount_out": tok1 - tok0, "fee_lamports": 0, "cost_pct": None, "error": None}
    return {"status": "ok", "signature": sig, "amount_in": tok0 - tok1, "amount_out": int(round((sol1 - sol0) * LAMPORTS)),
            "fee_lamports": 0, "cost_pct": None, "error": None}


def swap(input_mint, output_mint, amount_raw, live, max_cost_pct=None, routes=ROUTES, limit=None, slippage_bps=None):
    """One swap (live) or one quote (dry), route by route until one works. Returns {status, route, amount_in,
    amount_out, cost_pct, fee_lamports, error, tried, attempts, fee_total, ...}.
    attempts = every route's own result (its signature and the fee it was charged), fee_total = the sum of the fees
    of all attempts: a failed first try that landed onchain still cost money (audit 4.11. C09).
    slippage_bps (13.11.): Jupiter routes only (PumpPortal has its own SLIPPAGE_PCT), see sell(slip_cap_pct)."""
    tried, res, attempts = [], None, []
    for route in routes:
        res = (_pump(input_mint, output_mint, amount_raw, live) if route == "pump" else
               _jup(route, input_mint, output_mint, amount_raw, live, max_cost_pct, limit, slippage_bps)
               if slippage_bps else
               _jup(route, input_mint, output_mint, amount_raw, live, max_cost_pct, limit) if limit is not None
               else _jup(route, input_mint, output_mint, amount_raw, live, max_cost_pct))
        res["route"] = route
        attempts.append(dict(res))
        tried.append(f"{ROUTE_HR[route]}: {res.get('error') or res['status']}")
        if res["status"] != "failed" or not res.get("retry"):
            break
    if res["status"] == "failed" and len(tried) > 1:
        res["error"] = " · ".join(tried)
    res["tried"] = tried
    res["attempts"] = attempts
    res["fee_total"] = sum(a.get("fee_lamports") or 0 for a in attempts)
    return res


def routes_for(cfg):
    return ROUTES if cfg.get("use_pump", True) else ROUTES[:2]


def _log(con, now, pid, token, side, mode, res, reason):
    """One orders row per attempt: earlier failed routes first (each with its own signature and fee), then the
    final result, so the ledger keeps every try and every fee (audit 4.11. C09)."""
    for i, a in enumerate((res.get("attempts") or [])[:-1]):
        _log_one(con, now, pid, token, side, mode, {**a, "status": "failed"}, f"{reason} · pokušaj {i + 1}")
    _log_one(con, now, pid, token, side, mode, res, reason)


def _log_one(con, now, pid, token, side, mode, res, reason):
    con.execute("INSERT INTO orders (ts, position_id, token, side, mode, amount_in, amount_out, cost_pct, status, "
                "reason, error, signature, request_id, route, code, fee_lamports, prio_lamports) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (int(now), pid, token, side, mode, res.get("amount_in"), res.get("amount_out"), res.get("cost_pct"),
                 res["status"], reason, res.get("error"), res.get("signature"), res.get("request_id"), res.get("route"),
                 res.get("code") if res.get("code") is not None else res.get("error_code"),
                 # 9.11. (audit P67): dry also keeps the network fee the quote estimated, so a dry day_pnl and
                 # max_loss_day behave like live (the quote's price impact and Jupiter fee are in the amounts already)
                 res.get("fee_lamports"), res.get("prio_lamports")))


NET_FEES_SOL = 0.002   # 9.11. (audit P38): network fees of a buy + a sell net of the rent that comes back


def _quote_error(q):
    """9.11. (audit P40): jupiter._call hands an HTTP error (429 keyless limit, 400, 5xx) back as the JSON body with
    http_status instead of raising; a quote like that is no answer, not "no route". A 200 answer with 'error' and no
    outAmount (e.g. "No route found") is a real answer and stays on the honeypot path in sell_check (review novac)."""
    if not isinstance(q, dict):
        return "neispravan odgovor"
    if q.get("http_status"):
        return f"HTTP {q['http_status']}"
    return None


def sell_check(token, size_sol, max_cost_pct, tp_pct=None, override=None):
    """Before every buy: can the same amount be sold straight back? (audit 4.11. §20.4, T26). Quotes SOL -> token
    and then token -> SOL for what the first would give; no sell route, or a round trip losing more than twice the
    allowed swap cost, = reason to refuse the buy, whatever the score. A quote is not an executed sale (F10), but a
    honeypot or a pool too thin to exit shows up here for free. Returns None when fine, else the reason.
    tp_pct (9.11., audit P38): the exit target in percent; when the round trip plus network fees would eat half of
    it, the buy has no edge left and is refused (TP +5 % with a 4 % round trip is a coin flip at best).
    override (11.11.): a list for the owner's confirmed manual buy: the two cost lines (round trip over the cap, no
    edge left) are SOFT, so they are appended to it instead of refusing; no sell route and a check that could not be
    made stay HARD."""
    amount = int(size_sol * LAMPORTS)
    err = None
    for route in ("v2", "ultra"):         # the same fallback as the swap itself
        try:
            q1 = jupiter.order(jupiter.SOL, token, amount, route=route)
            bad = _quote_error(q1)
            if bad:
                err = bad
                continue             # a limit or an error is not "no route": ask the other endpoint
            got = int(q1.get("outAmount") or 0)
            if not got:
                return None          # no buy route: swap() reports that itself
            q2 = jupiter.order(token, jupiter.SOL, got, route=route)
            bad = _quote_error(q2)
            if bad:
                err = bad
                continue
            back = int(q2.get("outAmount") or 0)
            break
        except Exception as e:  # noqa: BLE001
            err = e
    else:
        what = err if isinstance(err, str) else type(err).__name__
        return f"provjera prodaje nije uspjela ({what}); ne kupujem naslijepo"
    if not back:
        return "simulacija prodaje: nema rute za prodaju natrag u SOL (moguć honeypot)"
    loss = 100 * (1 - back / amount)
    soft = []
    if max_cost_pct is not None and loss > 2 * max_cost_pct:
        soft.append(f"simulacija prodaje: kupnja pa odmah prodaja gubi {loss:.1f}% (granica {2 * max_cost_pct:g}%)")
    if tp_pct:
        total = loss + 100 * NET_FEES_SOL / size_sol
        if total >= tp_pct / 2:
            soft.append(f"trošak kupnje i prodaje {total:.1f}% (swap {loss:.1f}% + mrežne naknade) pojeo bi pola cilja "
                        f"+{tp_pct:g}%: nema ruba")
    if soft and override is not None:
        override.extend(soft)
        return None
    return soft[0] if soft else None


def swap_px_usd(token, o, res):
    """10.11. (Grok MCP audit 3): USD per whole token a SOL -> token order pays: its input in USD (Jupiter's
    inUsdValue, else the SOL in at trade/equity's SOL price) over the tokens it gives (outAmount / 10^decimals; a
    pump.fun mint has 6, any other is read once per process from the RPC). None when any part is unknown."""
    usd = float(o.get("inUsdValue") or 0)
    if usd <= 0:
        sol_usd = (equity.rates() or {}).get("sol_usd")
        usd = (res.get("amount_in") or 0) / LAMPORTS * sol_usd if sol_usd else 0
    try:
        dec = 6 if token.endswith("pump") else equity._decimals(token)
    except Exception:  # noqa: BLE001 - RPC down: unknown
        return None
    tokens = (res.get("amount_out") or 0) / 10 ** int(dec)
    return usd / tokens if usd > 0 and tokens > 0 else None


def _over_limit(limit, token, o, res):
    """The reason the order pays more than limit["max_px"] USD per token (or its price cannot be told), else None.
    limit = {"max_px": USD, "call_px": the call's price, "px": optional price function (tests)}."""
    px = (limit.get("px") or swap_px_usd)(token, o, res)
    if px is None:
        return "limit cijene poziva: cijena ovog swapa ne može se izračunati (nema cijene SOL-a ili decimala tokena)"
    if px > limit["max_px"]:
        call = limit.get("call_px")
        over = f" (+{px / call - 1:.0%} iznad prvog poziva)" if call else ""
        return (f"limit cijene poziva: swap bi platio ${px:.4g} po tokenu{over}, najviše ${limit['max_px']:.4g} "
                "(poziv + 10 %)")
    return None


def buy(con, cfg, token, symbol=None, paper_id=None, size_sol=None, now=None, reason="", league_id=None, tp_pct=None,
        add=False, manual=False, limit=None, override=None, mcap=None):
    """Gate, then swap SOL -> token. Always leaves one positions row (open, blocked or failed) so a signal
    is never retried by accident. The row is written as 'pending' and committed BEFORE anything is sent, so a crash
    between the swap and the bookkeeping leaves a trace that reconcile_pending() matches with the chain (audit C09).
    tp_pct (9.11., audit P38): the exit target of this position in percent (default cfg tp_default) for sell_check.
    override (11.11., owner: "ručno uvijek nadjačava sve ostalo"): the owner confirmed this manual buy over his limits
    on the page (the text of what he confirmed; only with manual): the SOFT reasons pass (gate_buy's, sell_check's
    cost and edge lines, the swap's cost cap), the HARD ones hold (kill switch, wallet balance, no route to sell back).
    The text is the lot's positions.override; the result's "overridden" lists the SOFT reasons that were passed.
    mcap (15.11.): the entry's market cap; an automatic buy under the microcap gate's MIN_MC is HARD (buy_checks).
    16.11.: the kill switch is the FIRST check of every buy (before any path's own switch or cap), and every automatic
    real buy (is_auto: Grok autotrade's manual stake included) is held to the global AUTO_HARD_CAPS: the stake cut to
    the smallest cap, the gate's HARD refusal, and final_check once more right before the swap."""
    now, live = now or time.time(), is_live(cfg)
    auto = is_auto(reason, manual)
    if os.path.exists(STOP_FILE):   # 16.11.: the kill switch before everything, whatever the path, flag or override
        size_sol = size_sol or cfg.get("size_sol") or 0
        res = {"status": "blocked", "error": "kill switch (trade/STOP)", "amount_in": int(size_sol * LAMPORTS)}
        mode = "live" if live else "dry"
        cur = con.execute("INSERT INTO positions (paper_id, league_id, token, symbol, opened_ts, mode, status, reason, "
                          "sol_in, qty_raw, qty_left, sol_back, fees_sol) VALUES (?,?,?,?,?,?,?,?,0,0,0,0,0)",
                          (paper_id, league_id, token, symbol, int(now), mode, "blocked", res["error"]))
        con.commit()
        return {**res, "id": cur.lastrowid, "mode": mode, "swap_status": "blocked", "overridden": []}
    iz = not manual and is_izvori(reason)   # 15.11.: a konsenzus buy: its own caps and switch (never pravi_novac_sve)
    ve = not manual and not iz and is_veliki(reason)   # 15.11.: a midcap buy: veliki/gate.real_caps (never LIVE_CAPS)
    sw = live and not manual and not iz and not ve and switch_on(con)   # 14.11.: the owner's switch pravi_novac_sve
    nau = ve and is_nauceno(reason)   # 18.11.: the learned rule's real twin: the midcap caps, its OWN switch, 0.1 SOL
    if ve:
        caps = veliki_caps(cfg)
        size_sol = min(size_sol or caps["size_sol"], caps["max_sol_per_trade"])
        if nau:
            size_sol = min(size_sol, NAUCENO_SOL)
        cfg = dict(cfg, max_cost_pct=veliki_capped(cfg)["max_cost_pct"])
        # the switch is checked here again: off = no real midcap buy at all (each rule its own switch)
        if live and not (nauceno_on(con) if nau else veliki_on(con)):
            res = {"status": "blocked", "error": f"{settings.NAUCENO_SWITCH if nau else 'pravi_novac_veliki'} je isključen",
                   "amount_in": int(size_sol * LAMPORTS)}
            cur = con.execute("INSERT INTO positions (paper_id, league_id, token, symbol, opened_ts, mode, status, "
                              "reason, sol_in, qty_raw, qty_left, sol_back, fees_sol) VALUES (?,?,?,?,?,?,?,?,0,0,0,0,0)",
                              (paper_id, league_id, token, symbol, int(now), "live", "blocked", res["error"]))
            con.commit()
            return {**res, "id": cur.lastrowid, "mode": "live", "swap_status": "blocked", "overridden": []}
    if iz:
        caps = izvori_caps(cfg)
        size_sol = min(size_sol or caps["size_sol"], caps["max_sol_per_trade"])
        cfg = dict(cfg, max_cost_pct=izvori_capped(cfg)["max_cost_pct"])
        if live and not izvori_on(con):   # the switch is checked here again: off = no real konsenzus buy at all
            res = {"status": "blocked", "error": "pravi_novac_izvori je isključen", "amount_in": int(size_sol * LAMPORTS)}
            cur = con.execute("INSERT INTO positions (paper_id, league_id, token, symbol, opened_ts, mode, status, "
                              "reason, sol_in, qty_raw, qty_left, sol_back, fees_sol) VALUES (?,?,?,?,?,?,?,?,0,0,0,0,0)",
                              (paper_id, league_id, token, symbol, int(now), "live", "blocked", res["error"]))
            con.commit()
            return {**res, "id": cur.lastrowid, "mode": "live", "swap_status": "blocked", "overridden": []}
    if sw:   # the stake of every automatic real buy under the switch: 0.1 SOL (a strategy's smaller lot stays smaller)
        caps = switch_caps(cfg)
        size_sol = min(size_sol or caps["size_sol"], caps["max_sol_per_trade"])
    mode, size_sol = "live" if live else "dry", size_sol or cfg["size_sol"]
    ov = bool(override) and manual and not auto   # 16.11.: an automatic buy never carries an override
    if live and not manual and not sw and not ve:   # 11.11. (owner's rule C): an automatic stake above the live cap is cut to it;
        size_sol = min(size_sol, LIVE_CAPS["max_sol_per_trade"])   # the owner's own amount is refused by gate_buy instead
    if live and auto:   # 16.11.: the global cap: no automatic real stake above it (a path's smaller one stays smaller)
        size_sol = min(size_sol, auto_cap(ve and not nau))
    why, passed = _gate(con, cfg, size_sol, now, live, token=token, add=add, manual=manual, override=ov, izvori=iz,
                        mcap=mcap, veliki=ve, auto=auto)
    if not why and cfg.get("sell_check", True):
        why = sell_check(token, size_sol, cfg.get("max_cost_pct"), cfg.get("tp_default") if tp_pct is None else tp_pct,
                         override=passed if ov else None)
    if not why:   # 16.11.: the last check before the swap (the sell check above may have taken seconds)
        why = final_check(con, size_sol, now, live, auto, cfg.get("day_tz"), ve)
    mark = (str(override) if isinstance(override, str) else "nadjačano")[:500] if ov else None
    # 9.11. (audit P11): the pending row carries the intended stake, so a buy that a crash leaves half-booked still
    # counts in the day limit and day_pnl (reconcile_pending keeps it); blocked/failed rows go back to 0 below
    cur = con.execute("INSERT INTO positions (paper_id, league_id, token, symbol, opened_ts, mode, status, reason, sol_in, "
                      "qty_raw, qty_left, sol_back, fees_sol, override) VALUES (?,?,?,?,?,?,?,?,?,0,0,0,0,?)",
                      (paper_id, league_id, token, symbol, int(now), mode, "blocked" if why else "pending",
                       why or "namjera zapisana, šaljem", 0 if why else size_sol, mark))
    pid = cur.lastrowid
    con.commit()
    cap = None if ov else cfg["max_cost_pct"]   # 11.11.: the owner's confirmed buy is not held by the cost cap (SOFT)
    if why:
        res = {"status": "blocked", "error": why, "amount_in": int(size_sol * LAMPORTS)}
    elif limit is not None:   # 10.11. (Grok MCP audit 3): only routes that quote first (PumpPortal swaps blind)
        res = swap(jupiter.SOL, token, int(size_sol * LAMPORTS), live, cap,
                   tuple(r for r in routes_for(cfg) if r != "pump"), limit=limit)
    else:
        res = swap(jupiter.SOL, token, int(size_sol * LAMPORTS), live, cap, routes_for(cfg))
    if ov and res.get("cost_pct") is not None and cfg.get("max_cost_pct") is not None \
            and res["cost_pct"] > cfg["max_cost_pct"]:
        passed.append(f"trošak {res['cost_pct']}% > {cfg['max_cost_pct']}%")
    ok = res["status"] in ("ok", "dry")
    status = "open" if ok else ("blocked" if res["status"] == "blocked" else "failed")
    fees = (res.get("fee_total", res.get("fee_lamports")) or 0) / LAMPORTS   # dry: the quote's estimate (P67)
    con.execute("UPDATE positions SET status=?, reason=?, sol_in=?, qty_raw=?, qty_left=?, fees_sol=? WHERE id=?",
                (status, reason if ok else res.get("error"), res["amount_in"] / LAMPORTS if ok else 0,
                 res.get("amount_out") if ok else 0, res.get("amount_out") if ok else 0, fees, pid))
    _log(con, now, pid, token, "buy", mode, res, reason)
    con.commit()
    return {**res, "id": pid, "status": status, "mode": mode, "swap_status": res["status"], "overridden": passed if ov else []}


def reconcile_pending(con, now=None, min_age_s=60, balance_of=None):
    """After a restart: buys left 'pending' (the process died between sending and bookkeeping) are matched with the
    wallet. Tokens in the wallet -> open position with that quantity; none -> failed. Dry ones -> failed.
    Returns the number of rows settled."""
    now = now or time.time()
    rows = con.execute("SELECT id, token, mode FROM positions WHERE status='pending' AND opened_ts<=?",
                       (int(now - min_age_s),)).fetchall()
    n = 0
    for pid, token, mode in rows:
        have = 0
        if mode == "live":
            try:
                have = (balance_of or (lambda t: wallet.token_raw_balance(wallet.address(), t)))(token)
            except Exception:  # noqa: BLE001 - cannot tell yet: leave it pending, try next round
                continue
        if have > 0:
            con.execute("UPDATE positions SET status='open', qty_raw=?, qty_left=?, reason=? WHERE id=?",
                        (have, have, "usklađeno s lancem nakon restarta (SOL ulog = zapisana namjera)", pid))
        else:
            con.execute("UPDATE positions SET status='failed', sol_in=0, reason=? WHERE id=?",
                        ("prekinuto prije potvrde; u walletu nema tokena", pid))
        n += 1
    n += _reconcile_pending_sells(con, now, min_age_s, balance_of)
    con.commit()
    return n


def _reconcile_pending_sells(con, now, min_age_s, balance_of=None):
    """9.11. (audit P11): a sell whose intent row (orders status 'pending', written before the swap is sent) is still
    there after min_age_s was cut off mid-swap. Live: qty_left is set from the wallet (nothing left -> closed), so a
    partial exit is not sent twice and the books match the chain; what came back in SOL stays unknown (noted).
    Dry: nothing was sent, the intent is just marked failed."""
    rows = con.execute("SELECT o.id, o.position_id, p.token, p.mode, p.qty_left FROM orders o JOIN positions p ON p.id = o.position_id "
                       "WHERE o.side='sell' AND o.status='pending' AND o.ts<=?", (int(now - min_age_s),)).fetchall()
    n = 0
    for oid, pid, token, mode, left in rows:
        if mode == "live":
            try:
                have = (balance_of or (lambda t: wallet.token_raw_balance(wallet.address(), t)))(token)
            except Exception:  # noqa: BLE001 - cannot tell yet: leave it pending, try next round
                continue
            if have < (left or 0):
                done = have <= 0
                con.execute("UPDATE positions SET qty_left=?, status=?, closed_ts=?, reason=? WHERE id=?",
                            (max(have, 0), "closed" if done else "open", int(now) if done else None,
                             "prodaja prekinuta usred swapa; količina usklađena s walletom, vraćeni SOL nepoznat", pid))
        con.execute("UPDATE orders SET status='failed', error=? WHERE id=?",
                    ("prekinuto usred swapa (proces ugašen); usklađeno s walletom nakon restarta" if mode == "live"
                     else "prekinuto usred probe", oid))
        n += 1
    return n


SELL_BACKOFF_MAX_S = 600


def _sell_wait(con, position_id, now):
    """Seconds to wait before the next try after failed sales of this position: 5, 10, 20 ... up to 10 min,
    so a token without a route (rug) is not hammered every 5 s."""
    rows = con.execute("SELECT ts, status FROM orders WHERE position_id=? AND side='sell' ORDER BY id DESC LIMIT 12",
                       (position_id,)).fetchall()
    n = 0
    for _, st in rows:
        if st != "failed":
            break
        n += 1
    if not n:
        return 0
    return max(0, rows[0][0] + min(SELL_BACKOFF_MAX_S, 5 * 2 ** (n - 1)) - now)


# 13.11. (owner's order point 2: "zaštitni slippage prag pri triggeru ... bez gašenja sigurnosnih provjera"): an exit
# plan's sale is first sent with at most this slippage under the quote (Jupiter routes; trade config
# "exit_slip_cap_pct" overrides, 0 = off). A stop that cannot fill is worse than slippage: when that try surely did
# not swap (no route, not landed, slippage exceeded), the normal swap with Jupiter's own slippage goes out at once.
EXIT_SLIP_CAP_PCT = 3.0
_CAP_UNSUPPORTED = {}   # route -> True once Jupiter refused the slippageBps parameter itself (HTTP 400): not sent again


def exit_cap_pct(cfg):
    """The protective slippage of an exit's first try in percent, None when off."""
    try:
        v = float(cfg.get("exit_slip_cap_pct", EXIT_SLIP_CAP_PCT))
    except (TypeError, ValueError):
        v = EXIT_SLIP_CAP_PCT
    return v if v > 0 else None


def _capped_swap(token, amount, live, cfg, cap_pct):
    """13.11.: the exit's swap with the protective slippage first. Returns (result, {"cap_pct", "result"}).
    The fallback (the normal swap, every route) goes out only when the capped try surely did not swap: status failed
    with retry (no quote, not landed, 6001 slippage exceeded); an unknown outcome (Jupiter never answered after the
    signed transaction was sent) is returned as it is, so nothing is sold twice (sell's backoff and the wallet check
    of the next pass decide). One route only (the first Jupiter route that takes the parameter): in a crash the
    fallback must not wait behind a second capped try. A route that did not answer at all is not asked again in the
    fallback."""
    routes = tuple(r for r in routes_for(cfg) if r != "pump" and not _CAP_UNSUPPORTED.get(r))[:1]
    info = {"cap_pct": cap_pct, "result": None}
    if not routes:
        info["result"] = "preskočeno (Jupiter ne prima slippageBps)"
        return swap(token, jupiter.SOL, amount, live, None, routes_for(cfg)), info
    first = swap(token, jupiter.SOL, amount, live, None, routes, slippage_bps=int(round(cap_pct * 100)))
    if first["status"] in ("ok", "dry"):
        info["result"] = "ok"
        return first, info
    if first["status"] != "failed" or not first.get("retry"):
        info["result"] = f"pao, ishod nepoznat ({first.get('error')}): bez slijepog ponavljanja"
        return first, info
    for a in first.get("attempts") or []:
        if a.get("http_status") == 400 and a.get("route"):   # the parameter itself refused: do not send it again
            _CAP_UNSUPPORTED[a["route"]] = True
    skip = {a.get("route") for a in first.get("attempts") or [] if a.get("no_answer")}
    rest = tuple(r for r in routes_for(cfg) if r not in skip) or routes_for(cfg)
    res = swap(token, jupiter.SOL, amount, live, None, rest)
    res["attempts"] = list(first.get("attempts") or []) + list(res.get("attempts") or [])
    res["tried"] = list(first.get("tried") or []) + list(res.get("tried") or [])
    res["fee_total"] = sum(a.get("fee_lamports") or 0 for a in res["attempts"])
    info["result"] = f"pao ({first.get('error')}), odmah normalni slippage: {res['status']}"
    return res, info


def sell(con, cfg, position_id, frac=1.0, close=False, now=None, reason="", slip_cap_pct=None):
    """Sell frac of the originally bought quantity (close=True sells everything left).
    slip_cap_pct (13.11., owner's order point 2): an exit's protective slippage on the first try (_capped_swap); the
    result then carries "slip_cap" {cap_pct, result}. Every check stays as it was (a real position needs the key
    and TRADE_LIVE, the backoff after failed tries, the wallet's balance before a full sale). The result also
    carries t_sent / t_done (unix s, float): when the swap request went out and when its answer came."""
    now = now or time.time()
    token, mode, qty, left, sol_back = con.execute(
        "SELECT token, mode, qty_raw, qty_left, sol_back FROM positions WHERE id=?", (position_id,)).fetchone()
    live = mode == "live"
    if live and not armed():  # never "dry-sell" a real position and mark it closed
        res = {"status": "failed", "error": "prava pozicija, ali ključ ili TRADE_LIVE nisu postavljeni", "amount_in": 0}
        _log(con, now, position_id, token, "sell", mode, res, reason)
        con.commit()
        return res
    if _sell_wait(con, position_id, now) > 0:
        return {"status": "wait", "error": "čeka ponovni pokušaj"}
    if close and live:
        have = wallet.token_raw_balance(wallet.address(), token)
        if have <= 0:   # nothing left in the wallet (sold by hand or by an earlier try): just close the record
            con.execute("UPDATE positions SET qty_left=0, status='closed', closed_ts=? WHERE id=?", (int(now), position_id))
            con.commit()
            return {"status": "noop"}
        left = min(left, have)
    amount = left if close else min(left, int(qty * frac))
    if amount <= 0:
        return {"status": "noop"}
    # 9.11. (audit P11): the intent is written and committed BEFORE the swap is sent (as buy() does), so a process
    # killed mid-swap leaves a trace that reconcile_pending() settles against the wallet instead of selling twice
    cur = con.execute("INSERT INTO orders (ts, position_id, token, side, mode, amount_in, status, reason, route) "
                      "VALUES (?,?,?,?,?,?,?,?,?)", (int(now), position_id, token, "sell", mode, amount, "pending", reason, None))
    intent = cur.lastrowid
    con.commit()
    t_sent = time.time()
    if slip_cap_pct:
        res, cap = _capped_swap(token, amount, live, cfg, slip_cap_pct)
        res["slip_cap"] = cap
    else:
        res = swap(token, jupiter.SOL, amount, live, None, routes_for(cfg))
    res["t_sent"], res["t_done"] = t_sent, time.time()
    con.execute("DELETE FROM orders WHERE id=? AND status='pending'", (intent,))
    fees = (res.get("fee_total", res.get("fee_lamports")) or 0) / LAMPORTS   # dry: the quote's estimate (P67)
    if res["status"] in ("ok", "dry"):
        left -= res["amount_in"]
        sol_back += res["amount_out"] / LAMPORTS
        done = close or left <= 0
        con.execute("UPDATE positions SET qty_left=?, sol_back=?, status=?, closed_ts=?, fees_sol=COALESCE(fees_sol,0)+? "
                    "WHERE id=?", (max(left, 0), sol_back, "closed" if done else "open", int(now) if done else None,
                                   fees, position_id))
        if done and live:
            _reclaim_rent(con, now, position_id, token)
    elif fees:
        con.execute("UPDATE positions SET fees_sol=COALESCE(fees_sol,0)+? WHERE id=?", (fees, position_id))
    _log(con, now, position_id, token, "sell", mode, res, reason)
    con.commit()
    return res


RECON_WINDOW_S = 900   # positions closed this recently get their exit compared (the SOL price is still the same)


def exit_reconcile(con, lg, decimals_fn, sol_usd_fn, now=None, window_s=RECON_WINDOW_S):
    """10.11. (plan 1.5, "demo vs real exit"): for each real position closed in the last window_s seconds that
    mirrors a demo trade (league_id) and has no real_exit_px yet:
        demo_exit_px   the demo trade's exit price (league.db trades.exit_px, USD per token)
        real_exit_px   what the real sells paid, USD per token: SOL out of the sell orders x SOL/USD now, over the
                       tokens sold (raw / 10^decimals)
        exit_slip_pct  real / demo - 1, in percent (negative = the real exit was worse than the demo's)
    The demo trade still open (the owner sold the real one by hand): only real_exit_px. Returns how many were filled.
    Older positions stay empty: today's SOL price would make their USD exit wrong."""
    now = int(now or time.time())
    try:
        sol_usd = sol_usd_fn()
    except Exception:  # noqa: BLE001
        sol_usd = None
    if not sol_usd:
        return 0
    done = 0
    for pid, token, lid in con.execute(
            "SELECT id, token, league_id FROM positions WHERE status='closed' AND league_id IS NOT NULL "
            "AND real_exit_px IS NULL AND closed_ts >= ?", (now - window_s,)).fetchall():
        sold_raw, out_lam = con.execute(
            "SELECT COALESCE(SUM(amount_in),0), COALESCE(SUM(amount_out),0) FROM orders WHERE position_id=? "
            "AND side='sell' AND status IN ('ok','dry')", (pid,)).fetchone()
        if not sold_raw or not out_lam:
            continue
        try:
            dec = int(decimals_fn(token))
        except Exception:  # noqa: BLE001 - no decimals: the next tick tries again
            continue
        real_px = (out_lam / LAMPORTS) * sol_usd / (sold_raw / 10 ** dec)
        demo_px = None
        try:
            r = lg.execute("SELECT status, exit_px FROM trades WHERE id=?", (lid,)).fetchone()
            if r and r[0] == "closed" and r[1]:
                demo_px = float(r[1])
        except Exception:  # noqa: BLE001
            demo_px = None
        slip = (real_px / demo_px - 1) * 100 if demo_px else None
        con.execute("UPDATE positions SET demo_exit_px=?, real_exit_px=?, exit_slip_pct=? WHERE id=?",
                    (demo_px, real_px, slip, pid))
        done += 1
    if done:
        con.commit()
    return done


# 18.11. (audit, trošak): the deposit of a token account (~0.00204 SOL, 2.04 % of a 0.1 SOL stake) did not come back:
# 0 refunds in 11 full closes on 14.-15.11. _reclaim_rent below runs once, right after the sale answers, when the
# wallet's token account usually does not read empty yet, and nothing tried again. rent_sweep is that second try: a
# step of the trade loop, at most once a minute, ONE closed live position (of the last 7 days, closed at least 30 s
# ago, no open lot of the token, no refund booked since it closed), at most 3 tries a position, a short wait for the
# confirmation so the loop is not held. It only closes token accounts that are EMPTY (wallet.close_empty checks the
# balance itself) and books the refund exactly as _reclaim_rent does.
RENT_SWEEP_EVERY_S = 60
RENT_SWEEP_AGE_S = 30
RENT_SWEEP_DAYS = 7
RENT_SWEEP_TRIES = 3
RENT_SWEEP_WAIT_S = 5
_RENT = {"ts": 0}


def rent_sweep(con, now, wait_s=RENT_SWEEP_WAIT_S):
    """One try (see above). None when nothing was due, else the lamports that came back (0 = not yet). Never raises."""
    now = int(now)
    if now - _RENT["ts"] < RENT_SWEEP_EVERY_S:
        return None
    _RENT["ts"] = now
    try:
        tries = dict(settings.raw(con).get("rent_tries_v3") or {})
        rows = con.execute(
            "SELECT p.id, p.token, p.symbol FROM positions p WHERE p.mode='live' AND p.status='closed' "
            "AND p.closed_ts>=? AND p.closed_ts<=? AND COALESCE(p.sol_in, 0)>0 AND COALESCE(p.qty_raw, 0)>0 "
            "AND NOT EXISTS (SELECT 1 FROM positions q WHERE q.token=p.token AND q.mode='live' "
            "                AND q.status IN ('open','pending')) "
            "AND NOT EXISTS (SELECT 1 FROM orders o JOIN positions r ON r.id=o.position_id WHERE o.side='rent' "
            "                AND r.token=p.token AND o.ts>=p.closed_ts) "
            "ORDER BY p.closed_ts DESC LIMIT 60", (now - RENT_SWEEP_DAYS * 86400, now - RENT_SWEEP_AGE_S)).fetchall()
        seen = set()
        for pid, token, symbol in rows:
            if token in seen:           # one account a token: the newest closed position of the token carries the refund
                continue
            seen.add(token)
            n = int(tries.get(str(pid)) or 0)
            if n >= RENT_SWEEP_TRIES:
                continue
            tries[str(pid)] = n + 1
            settings.put(con, "rent_tries_v3", dict(sorted(tries.items(), key=lambda kv: int(kv[0]))[-300:]), "alat")
            name = symbol or token[:6]
            sent = dict(settings.raw(con).get("rent_sent") or {})

            def done():   # nothing more to try for this position
                tries[str(pid)] = RENT_SWEEP_TRIES
                settings.put(con, "rent_tries_v3", dict(sorted(tries.items(), key=lambda kv: int(kv[0]))[-300:]), "alat")

            def book(got, how):
                con.execute("UPDATE positions SET fees_sol=COALESCE(fees_sol,0)-? WHERE id=?", (got / LAMPORTS, pid))
                _log(con, now, pid, token, "rent", "live", {"status": "ok", "amount_out": got, "fee_lamports": -got,
                                                            "route": "rpc"}, "vraćen depozit token računa (naknadno)")
                con.commit()
                print(f"trade: vraćen depozit token računa {name}: +{got / LAMPORTS:.5f} SOL (pozicija #{pid}, {how})",
                      flush=True)
            try:
                # 18.11. (2nd deploy): the reason in words. Whether the deposit is really lost decides the cost every
                # test is run at (the 3 % floor), so each outcome says which of the three it is.
                accs = wallet.token_accounts(wallet.address(), token)
                if not accs:
                    if str(pid) in sent:          # our own close landed after the short wait
                        got = int(sent.pop(str(pid)))
                        settings.put(con, "rent_sent", sent, "alat")
                        done()
                        book(got, "zatvaranje potvrđeno naknadno")
                        return got
                    done()
                    print(f"trade: depozit token računa {name}: račun tokena više ne postoji, dakle depozit je vraćen "
                          f"ranije, a nije knjižen (pozicija #{pid}; knjiga ostaje kakva je)", flush=True)
                    return 0
                left = sum(int(a[1] or 0) for a in accs)
                if left > 0:
                    done()
                    print(f"trade: depozit token računa {name}: na računu je ostatak od {left} jedinica tokena, račun "
                          f"nije prazan i depozit ostaje zaključan dok se ostatak ne proda (pozicija #{pid})", flush=True)
                    return 0
                info = {}
                got = wallet.close_empty(wallet._keypair(), token, wait_s=wait_s, info=info)
            except Exception as e:  # noqa: BLE001 - only the deposit; the loop goes on
                print(f"trade: depozit token računa {name}: pokušaj {n + 1}/{RENT_SWEEP_TRIES} nije uspio "
                      f"({type(e).__name__}: {str(e)[:80]})", flush=True)
                return 0
            if got:
                book(got, f"pokušaj {n + 1}")
            elif info.get("lamports"):
                sent[str(pid)] = int(info["lamports"])
                settings.put(con, "rent_sent", dict(list(sent.items())[-100:]), "alat")
                print(f"trade: depozit token računa {name}: račun je prazan, zatvaranje je poslano, potvrda nije stigla "
                      f"u {wait_s} s (pokušaj {n + 1}/{RENT_SWEEP_TRIES}; provjera u sljedećem prolazu)", flush=True)
            else:
                print(f"trade: depozit token računa {name}: račun je prazan, ali zatvaranje nije poslano "
                      f"(pokušaj {n + 1}/{RENT_SWEEP_TRIES})", flush=True)
            return got or 0
        return None
    except Exception as e:  # noqa: BLE001 - never the trade loop's problem
        print(f"trade: povrat depozita: {type(e).__name__}: {str(e)[:100]}", flush=True)
        return None


def _reclaim_rent(con, now, position_id, token):
    """Close the now empty token account: its rent (~0.002 SOL) goes back to the wallet."""
    try:
        got = wallet.close_empty(wallet._keypair(), token)
    except Exception as e:  # noqa: BLE001 - the sale itself is done, this is only the deposit
        print(f"trade: zatvaranje token računa {token[:6]}: {type(e).__name__}: {e}", flush=True)
        return
    if got:
        con.execute("UPDATE positions SET fees_sol=COALESCE(fees_sol,0)-? WHERE id=?", (got / LAMPORTS, position_id))
        _log(con, now, position_id, token, "rent", "live", {"status": "ok", "amount_out": got, "fee_lamports": -got,
                                                            "route": "rpc"}, "vraćen depozit token računa")
