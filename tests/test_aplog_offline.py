"""The Autopilot decision log (trade/aplog.py): every outcome of a signal shows once, with the right kind and reason.

The pipeline is the real one (league/copy.py tables, run_trade.follow_league_once, trade/executor.py) against a fake
Jupiter; no network, databases in a temp dir.

    python3 -m unittest tests.test_aplog_offline -v
"""
import os
import re
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import run_trade  # noqa: E402
from league import copy, store  # noqa: E402
from trade import aplog, executor, jupiter, settings  # noqa: E402

CFG = {"mode": "dry", "size_sol": 0.05, "max_sol_per_trade": 0.1, "max_sol_per_day": 0.12, "max_open": 5,
       "min_sol_reserve": 0.05, "max_cost_pct": 6, "max_signal_age_s": 180, "poll_s": 5}
NOW = 1_800_000_000
L = aplog.LAMPORTS
KEYS = {"ts", "kind", "token", "symbol", "source", "why", "why_short", "sol", "pnl_pct", "mode", "stage", "sig", "trebao"}
WORDS = {r[1] for r in aplog.REASONS} | {e[1] for e in aplog.EXITS} | {"", aplog.OTHER}


class FakeJup:
    """route: 'ok' quotes 1000 tokens per lamport (and `back` of that on the way out), 'none' has no route,
    '429' answers like the keyless limit."""

    def __init__(self):
        self.route, self.back = "ok", 1.0

    def order(self, inp, out, amount, taker=None, route="v2"):
        if self.route == "429":
            return {"http_status": 429, "error": "Rate limit exceeded"}
        if self.route == "none":
            return {"inAmount": str(amount), "outAmount": "0", "error": None}
        rate = 1000 if inp == jupiter.SOL else self.back / 1000
        return {"inAmount": str(amount), "outAmount": str(int(amount * rate)), "requestId": "rq", "inUsdValue": 100,
                "outUsdValue": 99, "transaction": "dHg=", "error": None}

    def execute(self, signed, rid, route="v2"):
        raise AssertionError("dry-run nikad ne šalje")


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = self.tmp.name
        self.fake = FakeJup()
        self._saved = (jupiter.order, jupiter.execute, run_trade.LEAGUE_DB, run_trade.DB, settings.DB, store.DB,
                       executor.is_live, executor.STOP_FILE)
        jupiter.order, jupiter.execute = self.fake.order, self.fake.execute
        run_trade.LEAGUE_DB = store.DB = os.path.join(d, "league.db")
        run_trade.DB = settings.DB = os.path.join(d, "trade.db")
        executor.STOP_FILE = os.path.join(d, "STOP")
        self.con = executor.connect(settings.DB)
        self.lg = store.connect(store.DB)
        copy.ensure(self.lg)
        self.lg.execute("INSERT OR IGNORE INTO accounts VALUES (?,?,?)", (settings.LEAGUE_USER, 1e9, 0))
        self.lg.commit()
        self._env = {k: os.environ.pop(k, None) for k in ("TRADE_LIVE", "SOLANA_PRIVATE_KEY")}
        self.cfg = settings.merged(CFG, self.con)
        self.fid = copy.follow(self.lg, settings.LEAGUE_USER, "kol", "ansem", "Ansem", 25, 5, "tpsl", "15%", "")
        aplog._DAY.clear()
        aplog._LOGGED.clear()

    def tearDown(self):
        (jupiter.order, jupiter.execute, run_trade.LEAGUE_DB, run_trade.DB, settings.DB, store.DB, executor.is_live,
         executor.STOP_FILE) = self._saved
        for k, v in self._env.items():
            if v is not None:
                os.environ[k] = v
        self.con.close()
        self.lg.close()
        self.tmp.cleanup()

    def demo(self, token, opened=NOW - 30, mcap=None, ev_ts=None, source="copy KOL Ansem", log=True):
        """A demo copy trade of the real-trade account with its copy_log 'ulaz' row, as league/copy.py leaves it."""
        tid = store.buy(self.lg, settings.LEAGUE_USER, token, token, 25, 1.0, 1e6, source, None, mcap)
        self.lg.execute("UPDATE trades SET opened_ts=?, follow_id=? WHERE id=?", (int(opened), self.fid, tid))
        if log:
            self.lg.execute("INSERT INTO copy_log VALUES (?,?,?,?,?,?,?,?,?)",
                            (self.fid, token, "buy", int(ev_ts or opened - 5), int(opened), token, "ulaz", "kupljeno", tid))
        self.lg.commit()
        return tid

    def skip(self, token, note, ts=NOW - 20, fid=None, side="buy", action="preskočeno"):
        self.lg.execute("INSERT INTO copy_log VALUES (?,?,?,?,?,?,?,?,?)",
                        (fid or self.fid, token, side, ts - 60, ts, token, action, note, None))
        self.lg.commit()

    def mirror(self, now=NOW, cfg=None):
        run_trade.follow_league_once(self.con, cfg or self.cfg, since=0, now=now, quiet=True)

    def log(self, **kw):
        kw.setdefault("now", NOW + 300)
        return aplog.entries(self.con, self.lg, **kw)

    def one(self, token, **kw):
        rows = [e for e in self.log(**kw) if e["token"] == token]
        self.assertEqual(len(rows), 1, f"{token}: {[(e['kind'], e['why']) for e in rows]}")
        return rows[0]


class Mapping(Base):
    def test_bought_once_although_demo_and_three_tables_know_it(self):
        self.demo("BUY")
        self.mirror()
        e = self.one("BUY")
        self.assertTrue(KEYS <= set(e))
        self.assertEqual((e["kind"], e["mode"], e["stage"], e["trebao"], e["side"]), ("kupio", "dry", "pravi", None, "buy"))
        self.assertEqual((e["source"], e["symbol"], e["ts"]), ("KOL Ansem", "BUY", NOW))
        self.assertAlmostEqual(e["sol"], 0.05)
        self.assertEqual((e["why"], e["why_short"], e["pnl_pct"], e["sig"]), (None, "", None, None))
        self.assertEqual(len(self.log()), 1)                      # the copy_log 'ulaz' row is not a second entry

    def test_skipped_by_a_rule_of_the_real_money_mirror(self):
        self.demo("LATE", opened=NOW - 5, ev_ts=NOW - 500)        # the call is 500 s old
        self.demo("SMALL", mcap=12_000)
        executor.is_live = lambda cfg: True
        self.demo("NOPROOF")                                      # live: this follow has no closed demo trades
        self.mirror()
        late, small, proof = self.one("LATE"), self.one("SMALL"), self.one("NOPROOF")
        for e in (late, small, proof):
            self.assertEqual((e["kind"], e["stage"], e["trebao"], e["sol"]), ("preskocio", "pravi", False, None))
            self.assertEqual(e["source"], "KOL Ansem")            # no order exists: the demo trade names the source
        self.assertEqual((late["why_short"], small["why_short"], proof["why_short"]),
                         ("signal star", "MC ispod 30k", "bez dokaza u demu"))
        self.assertIn("signal star 500 s", late["why"])
        self.assertEqual((late["mode"], proof["mode"]), ("live", "live"))
        self.assertEqual(self.con.execute("SELECT COUNT(*) FROM orders").fetchone()[0], 0)

    def test_skipped_by_a_limit_inside_the_executor_is_one_row(self):
        for t in ("A", "B", "C"):
            self.demo(t)
        self.mirror()                                             # 0.05 + 0.05 fit the 0.12 SOL day, the third does not
        kinds = sorted((e["token"], e["kind"]) for e in self.log())
        self.assertEqual([k for _, k in kinds].count("kupio"), 2)
        blocked = [e for e in self.log() if e["kind"] == "preskocio"]
        self.assertEqual(len(blocked), 1)                         # positions row + orders row = one decision
        self.assertEqual((blocked[0]["why_short"], blocked[0]["trebao"], blocked[0]["stage"]), ("limit", False, "pravi"))
        self.assertAlmostEqual(blocked[0]["sol"], 0.05)           # what it meant to spend
        self.assertEqual(blocked[0]["source"], "KOL Ansem")

    def test_failed_technically_is_one_row_however_many_routes(self):
        self.fake.route = "none"
        self.demo("NOROUTE")
        self.mirror()
        self.assertEqual(self.con.execute("SELECT COUNT(*) FROM orders").fetchone()[0], 3)   # v2, ultra, pump
        e = self.one("NOROUTE")
        self.assertEqual((e["kind"], e["trebao"], e["stage"], e["why_short"]), ("nije_proslo", True, "pravi", "nema rute"))
        self.assertAlmostEqual(e["sol"], 0.05)
        self.assertEqual(e["source"], "KOL Ansem")                # the "· pokušaj N" suffix of a failed route is off

    def test_blocked_for_a_technical_reason_should_have_been_bought(self):
        self.fake.route = "429"
        self.demo("LIMITED")
        self.mirror()
        self.assertEqual(self.con.execute("SELECT status FROM positions").fetchone()[0], "blocked")
        e = self.one("LIMITED")
        self.assertEqual((e["kind"], e["trebao"], e["why_short"]), ("nije_proslo", True, "provjera prodaje nije uspjela"))

    def test_skipped_in_the_demo_copy_stage(self):
        self.skip("THIN", "premala likvidnost ($3,200), ne bi se moglo izaći")
        self.skip("CURVE", "token je još na pump.fun krivulji (nema DexScreener para), uzimaju se bondani", ts=NOW - 10)
        self.skip("INFO", "prodao je token koji nismo kopirali", action="info", side="sell")
        self.skip("EXIT", "Ansem je prodao, i mi: +3.00 $", action="izlaz", side="sell")
        other = copy.follow(self.lg, "Ivan", "kol", "ansem", "", 25, 5, "tpsl", "15%", "")
        self.skip("IVAN", "premala likvidnost ($1), ne bi se moglo izaći", fid=other)       # another player's follow
        rows = self.log()
        self.assertEqual([e["token"] for e in rows], ["CURVE", "THIN"])                     # newest first
        for e in rows:
            self.assertEqual((e["kind"], e["stage"], e["trebao"], e["mode"], e["source"]),
                             ("preskocio", "demo", False, "dry", "KOL Ansem"))
        self.assertEqual([e["why_short"] for e in rows], ["nije bondan", "likvidnost"])
        executor.is_live = lambda cfg: True
        self.assertEqual(self.log()[0]["mode"], "live")           # what the mirror would have traded in

    def test_demo_entry_the_mirror_never_saw(self):
        """The trade process was down: the demo copy entered, no trade.db row exists. Not silence: nije_proslo."""
        self.demo("MISSED", opened=NOW - 4000)
        self.demo("FRESH", opened=NOW + 290)                      # seconds old: the mirror's turn is still coming
        rows = self.log()
        self.assertEqual([e["token"] for e in rows], ["MISSED"])
        e = rows[0]
        self.assertEqual((e["kind"], e["trebao"], e["why_short"], e["stage"]),
                         ("nije_proslo", True, "trade proces nije radio", "pravi"))
        self.mirror(now=NOW + 300)                                # the mirror runs: both get their row
        kinds = {e["token"]: (e["kind"], e["why_short"]) for e in self.log(now=NOW + 600)}
        self.assertEqual(kinds, {"MISSED": ("preskocio", "signal star"), "FRESH": ("kupio", "")})

    def test_sold_with_the_result_on_the_closing_sale(self):
        tid = self.demo("WIN")
        self.mirror()
        self.fake.back = 1.3                                      # the token is worth 30 % more on the way out
        store.sell_part(self.lg, tid, 0.5, 1.3, 1e6)              # the demo sells half ...
        self.mirror(now=NOW + 60)
        store.sell(self.lg, settings.LEAGUE_USER, tid, 1.3, 1e6, "auto TP +15%")   # ... then the rest
        self.mirror(now=NOW + 120)
        rows = [e for e in self.log() if e["token"] == "WIN"]
        self.assertEqual([e["kind"] for e in rows], ["prodao", "prodao", "kupio"])
        close, part = rows[0], rows[1]
        self.assertEqual((part["pnl_pct"], part["why_short"], part["ts"]), (None, "djelomična prodaja", NOW + 60))
        self.assertEqual((close["why"], close["why_short"], close["trebao"], close["side"], close["source"]),
                         ("auto TP +15%", "cilj (TP)", None, "sell", "KOL Ansem"))
        self.assertAlmostEqual(close["pnl_pct"], 30.0)
        self.assertAlmostEqual(part["sol"] + close["sol"], 0.065)

    def test_result_is_after_network_fees_and_rent_rows_are_not_listed(self):
        self.con.execute("INSERT INTO positions (token, symbol, opened_ts, mode, status, reason, sol_in, qty_raw, qty_left, "
                         "sol_back, fees_sol, closed_ts) VALUES ('FEE','FEE',?,'live','closed','copy KOL x',0.1,10,0,0.12,0.004,?)",
                         (NOW, NOW + 50))
        for side, st, a_in, a_out, sig in (("buy", "ok", int(0.1 * L), 10, "SIGB"), ("sell", "ok", 10, int(0.12 * L), "SIGS"),
                                            ("rent", "ok", 0, 2_000_000, None)):
            self.con.execute("INSERT INTO orders (ts, position_id, token, side, mode, amount_in, amount_out, status, reason, "
                             "signature) VALUES (?,1,'FEE',?,'live',?,?,?,?,?)",
                             (NOW + (0 if side == "buy" else 50), side, a_in, a_out, st, "copy KOL x" if side == "buy" else "auto SL -20%", sig))
        self.con.commit()
        rows = self.log()
        self.assertEqual([(e["kind"], e["sig"]) for e in rows], [("prodao", "SIGS"), ("kupio", "SIGB")])
        self.assertAlmostEqual(rows[0]["pnl_pct"], 16.0)          # (0.12 - 0.1 - 0.004) / 0.1
        self.assertEqual((rows[0]["mode"], rows[0]["why_short"], rows[1]["source"]), ("live", "stop (SL)", "KOL x"))

    def test_sale_that_keeps_failing_is_one_row_until_it_goes_through(self):
        self.con.execute("INSERT INTO positions (token, symbol, opened_ts, mode, status, reason, sol_in, qty_raw, qty_left, "
                         "sol_back, fees_sol) VALUES ('RUG','RUG',?,'live','open','copy wallet w',0.1,10,10,0,0)", (NOW - 900,))
        for i in range(6):   # the backoff's retries, each with the route's raw answer
            self.con.execute("INSERT INTO orders (ts, position_id, token, side, mode, amount_in, status, reason, error) "
                             "VALUES (?,1,'RUG','sell','live',10,'failed','auto SL -20%',?)",
                             (NOW - 600 + i * 60, "Jupiter: nema rute · Jupiter Ultra ne odgovara (URLError)"))
        self.con.commit()
        rows = self.log()
        self.assertEqual(len(rows), 2)
        e = rows[0]
        self.assertEqual((e["kind"], e["side"], e["trebao"], e["ts"], e["token"]), ("nije_proslo", "sell", True, NOW - 300, "RUG"))
        self.assertIn(e["why_short"], ("mreža", "nema rute"))
        self.con.execute("INSERT INTO orders (ts, position_id, token, side, mode, amount_in, amount_out, status, reason) "
                         "VALUES (?,1,'RUG','sell','live',10,1000,'ok','auto SL -20%')", (NOW - 100,))
        self.con.execute("UPDATE positions SET status='closed', sol_back=0.000001 WHERE id=1")
        self.con.commit()
        self.assertEqual([e["kind"] for e in self.log()], ["prodao", "kupio"])   # the failed tries are history

    def test_real_copy_pass_then_mirror_then_log(self):
        """10.11. (review novac): the real chain on realistic rows. league/copy.run_once decides on three calls of the
        followed KOL (one entered, one pool too thin, one under 30k), the mirror buys the entered one, and the log
        shows each signal exactly once with the stage it was decided in."""
        d = self.tmp.name
        paths = {"kol": os.path.join(d, "kol.db"), "hype": os.path.join(d, "hype.db"), "tg": os.path.join(d, "tg.db")}
        k = sqlite3.connect(paths["kol"])
        k.execute("CREATE TABLE calls (token TEXT, handle TEXT, ts INTEGER, kind TEXT)")
        good, thin, small = "G" * 44, "T" * 44, "S" * 44
        k.executemany("INSERT INTO calls VALUES (?, 'ansem', ?, 'call')", [(t, NOW - 30) for t in (good, thin, small)])
        k.commit()
        k.close()
        mk = {good: (1.0, 500_000, None, 2e6, "GOOD"), thin: (1.0, 2_000, None, 2e6, "THIN"),
              small: (1.0, 15_000, None, 20_000, "SMALL")}
        copy.run_once(self.lg, lambda toks: {t: mk[t] for t in toks if t in mk}, NOW, paths)
        self.assertEqual(dict(self.lg.execute("SELECT token, action FROM copy_log")),
                         {good: "ulaz", thin: "preskočeno", small: "preskočeno"})
        self.lg.execute("UPDATE trades SET opened_ts=? WHERE user=?", (NOW, settings.LEAGUE_USER))   # store.buy: wall clock
        self.lg.commit()
        self.mirror(now=NOW + 1)
        rows = self.log()
        self.assertEqual(sorted((e["symbol"], e["kind"], e["stage"], e["why_short"], e["trebao"]) for e in rows),
                         [("GOOD", "kupio", "pravi", "", None), ("SMALL", "preskocio", "demo", "MC ispod 30k", False),
                          ("THIN", "preskocio", "demo", "likvidnost", False)])
        self.assertTrue(all(e["source"] == "KOL Ansem" for e in rows))
        s = aplog.summary(rows, now=NOW + 300)
        self.assertEqual((s["signali"], s["kupio"], s["preskocio"], s["nije_proslo"]), (3, 1, 2, 0))

    def test_pending_rows_are_not_decisions_yet(self):
        self.con.execute("INSERT INTO positions (token, opened_ts, mode, status, reason, sol_in) VALUES ('P',?,'dry','pending','x',0.05)", (NOW,))
        self.con.execute("INSERT INTO orders (ts, position_id, token, side, mode, amount_in, status) VALUES (?,1,'P','sell','dry',5,'pending')", (NOW,))
        self.con.commit()
        self.assertEqual(self.log(), [])


class Reading(Base):
    def test_limit_since_and_order(self):
        for i in range(6):
            self.skip(f"T{i}", "premala likvidnost ($1), ne bi se moglo izaći", ts=NOW - 100 + i)
        self.demo("BUY")
        self.mirror(now=NOW - 50)
        self.assertEqual([e["token"] for e in self.log()], ["BUY", "T5", "T4", "T3", "T2", "T1", "T0"])
        self.assertEqual([e["token"] for e in self.log(limit=3)], ["BUY", "T5", "T4"])
        self.assertEqual([e["token"] for e in self.log(since=NOW - 97)], ["BUY", "T5", "T4", "T3"])
        self.assertEqual(len({e["id"] for e in self.log()}), 7)   # a stable key per row

    def test_league_db_is_opened_read_only_when_no_connection_is_given(self):
        self.skip("THIN", "premala likvidnost ($1), ne bi se moglo izaći")
        self.demo("BUY")
        self.mirror()
        rows = aplog.entries(self.con, now=NOW + 300)
        self.assertEqual([(e["token"], e["kind"]) for e in rows], [("BUY", "kupio"), ("THIN", "preskocio")])

    def test_without_league_tables_the_real_money_part_still_shows(self):
        self.demo("BUY")
        self.mirror()
        empty = sqlite3.connect(os.path.join(self.tmp.name, "prazno.db"))
        self.assertEqual([e["kind"] for e in aplog.entries(self.con, empty, now=NOW + 300)], ["kupio"])
        empty.close()
        store.DB = os.path.join(self.tmp.name, "nema.db")
        self.assertEqual([e["kind"] for e in aplog.entries(self.con, now=NOW + 300)], ["kupio"])

    def test_never_raises(self):
        dead = sqlite3.connect(":memory:")
        dead.close()
        self.assertEqual(aplog.entries(dead), [])
        self.assertEqual(aplog.entries(sqlite3.connect(":memory:")), [])   # no tables at all
        s = aplog.summary_24h(dead, now=NOW)
        self.assertEqual((s["signali"], s["razlozi"]), (0, []))

    def test_no_query_reads_a_whole_table(self):
        """The log is read every second: each query must go through an index (or the primary key)."""
        for i in range(30):
            self.skip(f"T{i}", "premala likvidnost ($1), ne bi se moglo izaći", ts=NOW - 100 + i)
        for t in ("A", "B", "C"):
            self.demo(t)
        self.mirror()
        seen = {"t": [], "l": []}
        self.con.set_trace_callback(seen["t"].append)
        self.lg.set_trace_callback(seen["l"].append)
        rows = self.log()
        self.con.set_trace_callback(None)
        self.lg.set_trace_callback(None)
        self.assertGreater(len(rows), 30)
        selects = [(c, q) for c, qs in ((self.con, seen["t"]), (self.lg, seen["l"])) for q in qs if q.lstrip().upper().startswith("SELECT")]
        self.assertGreaterEqual(len(selects), 6)
        for con, q in selects:
            for row in con.execute("EXPLAIN QUERY PLAN " + q):
                self.assertNotRegex(row[3], r"^SCAN \w+$", f"cijela tablica: {q}")
        have = {r[1] for t in ("positions", "orders") for r in self.con.execute(f"PRAGMA index_list({t})")}
        self.assertTrue({"positions_opened", "positions_status", "positions_league", "orders_pos", "orders_side",
                         "orders_ts"} <= have)
        # 10.11. (review novac): (follow_id, action, ts) instead of (follow_id, ts), so the walk never passes the
        # follow's "info" rows; see test_a_wallet_follows_info_rows_are_never_walked
        self.assertIn("copy_log_follow_action", {r[1] for r in self.lg.execute("PRAGMA index_list(copy_log)")})

    def test_a_wallet_follows_info_rows_are_never_walked(self):
        """10.11. (review novac): a followed wallet writes an "info" row for every sale of a coin we never copied.
        The log reads each follow's skips and entries through (follow_id, action, ts): thousands of those rows cost
        nothing, where (follow_id, ts) walked past all of them until it found LIMIT skips."""
        wid = copy.follow(self.lg, settings.LEAGUE_USER, "wallet", "W" * 44, "Whale", 25, 5, "mirror", "", "")
        self.skip("OLD1", "premala likvidnost ($1), ne bi se moglo izaći", ts=NOW - 80000, fid=wid)
        self.skip("OLD2", "DexScreener nema cijenu tog tokena", ts=NOW - 70000, fid=wid)

        def steps():
            n = [0]

            def tick():
                n[0] += 1
            self.lg.set_progress_handler(tick, 100)
            rows = self.log()
            self.lg.set_progress_handler(None, 0)
            return n[0], rows
        before, rows = steps()
        self.lg.executemany("INSERT INTO copy_log VALUES (?,?,?,?,?,?,?,?,?)",
                            [(wid, f"I{i:05d}", "sell", NOW - 60000 + i, NOW - 60000 + i, None, "info",
                              "prodao je token koji nismo kopirali", None) for i in range(5000)])
        self.lg.commit()
        after, rows2 = steps()
        self.assertEqual([e["token"] for e in rows2], ["OLD2", "OLD1"])
        self.assertEqual(rows, rows2)
        self.assertLess(after, before + 20)                       # not one step per info row
        plans = [r[3] for r in self.lg.execute(
            "EXPLAIN QUERY PLAN SELECT follow_id, token, side, ts, symbol, action, note, trade_id FROM copy_log "
            "WHERE follow_id=? AND action=? AND ts >= ? ORDER BY ts DESC LIMIT ?", (wid, "ulaz", 0, 80))]
        self.assertTrue(any("copy_log_follow_action" in p for p in plans), plans)
        self.assertFalse([p for p in plans if "TEMP B-TREE" in p], plans)

    def test_trade_loop_pass_reads_no_whole_table_either(self):
        """run_trade's 1-second pass over trade.db: pending rows, open positions and "is it mirrored" by index."""
        self.demo("A")
        self.mirror()
        self.demo("B")
        seen = []
        self.con.set_trace_callback(seen.append)
        executor.reconcile_pending(self.con, now=NOW + 5)
        self.mirror(now=NOW + 5)
        self.con.set_trace_callback(None)
        for q in [q for q in seen if q.lstrip().upper().startswith("SELECT")]:
            for row in self.con.execute("EXPLAIN QUERY PLAN " + q):
                self.assertNotRegex(row[3], r"^SCAN \w+$", f"cijela tablica: {q}")
        self.assertEqual(dict(self.con.execute("SELECT token, status FROM positions")), {"A": "open", "B": "open"})
        self.mirror(now=NOW + 6)                                  # and nothing is mirrored twice
        self.assertEqual(self.con.execute("SELECT COUNT(*) FROM positions").fetchone()[0], 2)


class Summary(Base):
    def rows(self):
        def e(kind, why_short="", side="buy", ts=NOW - 100):
            return {"ts": ts, "kind": kind, "why_short": why_short, "side": side}
        return ([e("kupio")] * 2 + [e("prodao", "cilj (TP)", "sell")] * 3
                + [e("preskocio", "bez dokaza u demu")] * 5 + [e("preskocio", "signal star")] * 3 + [e("preskocio", "rug")]
                + [e("nije_proslo", "nema rute")] + [e("nije_proslo", "mreža", "sell")]
                + [e("preskocio", "nema cijene", "sell")]                  # a mirrored sale the demo could not price
                + [e("kupio", ts=NOW - 90000), e("preskocio", "limit", ts=NOW - 90000)])   # older than a day

    def test_counts_and_reasons_of_the_last_24_h(self):
        s = aplog.summary(self.rows(), now=NOW)
        self.assertEqual({k: s[k] for k in ("signali", "kupio", "prodao", "preskocio", "nije_proslo")},
                         {"signali": 12, "kupio": 2, "prodao": 3, "preskocio": 9, "nije_proslo": 1})
        self.assertEqual(s["signali"], s["kupio"] + s["preskocio"] + s["nije_proslo"])
        self.assertEqual(s["razlozi"], [("bez dokaza u demu", 5), ("signal star", 3), ("rug", 1)])
        self.assertEqual((s["razlozi_nije_proslo"], s["prodaja_nije_prosla"]), ([("nema rute", 1)], 1))
        empty = aplog.summary([], now=NOW)
        self.assertEqual((empty["signali"], empty["razlozi"]), (0, []))

    def test_summary_of_real_entries(self):
        self.demo("BUY")
        self.demo("LATE", opened=NOW - 5, ev_ts=NOW - 500)
        self.skip("THIN", "premala likvidnost ($3,200), ne bi se moglo izaći")
        self.skip("OLD", "premala likvidnost ($3,200), ne bi se moglo izaći", ts=NOW - 90000)
        self.mirror()
        s = aplog.summary(self.log(), now=NOW + 300)
        self.assertEqual((s["signali"], s["kupio"], s["preskocio"], s["nije_proslo"]), (3, 1, 2, 0))
        self.assertEqual(s["razlozi"], [("likvidnost", 1), ("signal star", 1)])

    def test_summary_24h_covers_a_busy_day_and_is_kept_for_seconds(self):
        for i in range(150):                                      # more than the list's default 80 rows
            self.skip(f"T{i}", "vidjeli smo ga tek 12 min nakon poziva, prekasno za ulaz", ts=NOW - 5000 + i)
        self.assertEqual(aplog.summary(self.log(), now=NOW + 300)["preskocio"], 80)
        s = aplog.summary_24h(self.con, self.lg, now=NOW + 300)
        self.assertEqual((s["signali"], s["preskocio"], s["razlozi"]), (150, 150, [("kasni poziv", 150)]))
        self.skip("NEW", "token je rugan (x)", ts=NOW + 299)
        self.assertEqual(aplog.summary_24h(self.con, self.lg, now=NOW + 302)["preskocio"], 150)   # the kept answer
        self.assertEqual(aplog.summary_24h(self.con, self.lg, now=NOW + 306)["preskocio"], 151)


class WhyShort(unittest.TestCase):
    CASES = {
        # the real-money mirror (run_trade.follow_league_once)
        "signal star 412 s": "signal star",
        "MC $12,000 ispod 30k (pravilo: ispod 30k se ne kupuje)": "MC ispod 30k",
        "praćenje bez dokaza u demu (zatvorenih 3, dobitnih 1, PnL -4 $; treba 10+ zatvorenih, PnL > 0 i 40%+ dobitnih)": "bez dokaza u demu",
        "kopija bez zapisa praćenja (follow_id); bez dokaza u demu ne ide u pravi novac": "bez dokaza u demu",
        "istraživački / konvergencijski demo trade, ne kopira se": "samo demo",
        # the executor's gate and sell check
        "kill switch (trade/STOP)": "ručno zaustavljeno",
        "već postoji otvorena pozicija u ovom tokenu (#12)": "već u poziciji",
        "0.2 SOL iznad limita 0.1": "limit",
        "dnevni limit: potrošeno 0.100 od 0.12 SOL": "limit",
        "5 otvorenih pozicija": "limit",
        "dnevni gubitak -0.412 SOL, granica -0.4 SOL: stop do ponoći": "dnevni stop",
        "premalo SOL-a: stanje 0.0100, treba 0.1130 (ulog 0.1 + naknade i depozit 0.003 + rezerva za prodaju 0.0100)": "premalo SOL-a",
        "trošak 7.2% > 6%": "trošak swapa",
        "simulacija prodaje: kupnja pa odmah prodaja gubi 14.2% (granica 12%)": "trošak swapa",
        "trošak kupnje i prodaje 8.1% (swap 6.0% + mrežne naknade) pojeo bi pola cilja +15%: nema ruba": "trošak swapa",
        "simulacija prodaje: nema rute za prodaju natrag u SOL (moguć honeypot)": "honeypot",
        "provjera prodaje nije uspjela (HTTP 429); ne kupujem naslijepo": "provjera prodaje nije uspjela",
        # routes
        "Jupiter: nema rute · Jupiter Ultra: nema rute · PumpPortal: nema rute (PumpPortal radi samo uživo)": "nema rute",
        "Jupiter ne odgovara (URLError)": "mreža",
        "cijena se pomaknula više od dopuštenog klizanja (slippage)": "klizanje cijene",
        "nalog je istekao prije slanja": "transakcija nije stigla na vrijeme",
        "transakcija nije stigla u blok": "transakcija nije stigla na vrijeme",
        "Jupiter nije potvrdio swap; provjeri wallet na Solscanu": "swap nije potvrđen",
        "prekinuto prije potvrde; u walletu nema tokena": "prekid usred naloga",
        "prava pozicija, ali ključ ili TRADE_LIVE nisu postavljeni": "ključ nije spreman",
        "PumpPortal transakcija nije prošla": "greška rute",
        "Insufficient funds": "premalo SOL-a",
        # the demo copy stage (league/copy.py)
        "vidjeli smo ga tek 12 min nakon poziva, prekasno za ulaz": "kasni poziv",
        "poziv je star 150 s: izlaz po podacima mjeren je za ulaz u prvoj minuti nakon poziva (najviše 120 s)": "kasni poziv",
        "DexScreener nema cijenu tog tokena": "nema cijene",
        "DexScreener ima par, ali trenutno bez cijene/likvidnosti": "nema cijene",
        "premala likvidnost ($3,200), ne bi se moglo izaći": "likvidnost",
        "likvidnost $4,000 je samo 2.1% MC-a (granica 3%): najveći holder bi srušio cijenu prije stopa": "likvidnost",
        "token je još na pump.fun krivulji (nema DexScreener para), uzimaju se bondani": "nije bondan",
        "MC nepoznat, a ispod 30k se ne kupuje": "MC ispod 30k",
        "velik token (preko $50M), to nije poziv na memecoin": "prevelik token",
        "lažni pool (likvidnost veća od market capa), tipičan rug": "rug",
        "token je rugan (pao 95 % od vrha)": "rug",
        "rug check: pao (topcheck)": "rug",
        "koncentriran supply: top 10 holdera drži 72% (granica 60%)": "koncentracija",
        "već 10 ulaza danas (tvoj limit)": "limit",
        "već imaš otvorenu poziciju u tom tokenu": "već u poziciji",
        "token je već na MC $2,000,000 (tvoj strop $1,000,000)": "MC iznad stropa",
        "cijena je već +35% u zadnjih 5 min (tvoj prag +20% od poziva)": "cijena već otišla",
        "po podacima se ne isplati: najbolji izlaz TP 15 % / SL 20 %": "ne isplati se po podacima",
    }
    EXITS = {
        "auto TP +15%": "cilj (TP)", "auto SL -20%": "stop (SL)", "auto: take_profit_2x": "cilj (TP)",
        "auto: stop_loss": "stop (SL)", "auto vrijeme (ni TP ni SL u izmjerenom roku)": "istek vremena",
        "auto: moonbag_trailing": "Smart sell", "copy: RugDoctor je prodao": "prodao i praćeni",
        "djelomična prodaja (demo)": "djelomična prodaja", "ručna prodaja (gumb)": "ručno", "prodaj sve (gumb)": "ručno",
        "demo izlaz": "izlaz kao u demu", "auto: rug": "rug",
        # 10.11. (review novac): paper/sim.py's other closing reasons, as league/auto.py writes them
        "auto: time": "istek vremena", "auto: breakeven": "stop na ulazu", "auto: stale": "bez pomaka",
        "auto: trailing": "Smart sell", "auto: smart_sell_eksplozija": "Smart sell",
    }

    def test_buckets(self):
        for text, want in self.CASES.items():
            self.assertEqual(aplog.why_short(text), want, text)
        for text, want in self.EXITS.items():
            self.assertEqual(aplog.why_short(text, "prodao"), want, text)

    def test_contract_words(self):
        for w in ("signal star", "MC ispod 30k", "bez dokaza u demu", "kasni poziv", "likvidnost", "rug", "limit"):
            self.assertIn(w, WORDS)

    def test_never_the_raw_text(self):
        nasty = ["HTTPError: https://mainnet.helius-rpc.com/?api-key=123e4567-e89b-12d3-a456-426614174000 403",
                 "neka sasvim nova poruka koju nitko nije predvidio", "drugi pool daje cijenu 5x drugačiju",
                 "<script>alert(1)</script>", "x" * 5000, "TRADE_LIVE", "SOLANA_PRIVATE_KEY=abc", 12345, object()]
        for text in nasty + list(self.CASES) + list(self.EXITS):
            for kind in (None, "prodao", "preskocio"):
                self.assertIn(aplog.why_short(text, kind), WORDS, text)
        self.assertEqual(aplog.why_short(nasty[1]), "ostalo")
        self.assertEqual(aplog.why_short("drugi pool daje cijenu 5x drugačiju"), "ostalo")   # "drugi" is not a rug
        for empty in (None, "", "   "):
            self.assertEqual(aplog.why_short(empty), "")
        for w in WORDS:
            self.assertNotRegex(w, r"https?:|[A-Z_]{6,}|—")       # no address, no env-like name, no em-dash


class Safety(Base):
    def test_why_is_scrubbed_and_why_short_is_always_a_fixed_word(self):
        secret = "123e4567-e89b-12d3-a456-426614174000"
        raw = f"PumpPortal: HTTPError: https://mainnet.helius-rpc.com/?api-key={secret} vratio 403 za {secret}"
        self.con.execute("INSERT INTO positions (token, symbol, opened_ts, mode, status, reason, sol_in) "
                         "VALUES ('BAD','BAD',?,'live','failed',?,0)", (NOW, raw))
        self.con.execute("INSERT INTO positions (token, symbol, opened_ts, mode, status, reason, sol_in) "
                         "VALUES ('NEW','NEW',?,'live','blocked','sasvim nova vrsta razloga',0)", (NOW + 1,))
        self.con.commit()
        self.skip("ODD", "nešto što league/copy.py još ne piše")
        rows = self.log()
        self.assertEqual(len(rows), 3)
        for e in rows:
            self.assertIn(e["why_short"], WORDS)
            self.assertNotIn(secret, e["why"] or "")
            self.assertNotIn("api-key", e["why"] or "")
        bad = self.one("BAD")
        self.assertEqual((bad["kind"], bad["trebao"]), ("nije_proslo", True))
        self.assertIn("mainnet.helius-rpc.com", bad["why"])      # the owner still sees which host failed
        new = self.one("NEW")
        self.assertEqual((new["kind"], new["trebao"], new["why_short"]), ("preskocio", False, "ostalo"))

    def test_scrub_hides_keys_outside_urls_too(self):
        """10.11. (review novac): an exception text can carry a key without any URL around it."""
        for raw in ("PumpPortal: api-key=abc123TAJNA nije prošao", "HTTP 401, token: abc123TAJNA",
                    "Authorization: Bearer abc123TAJNA", "https://pumpportal.fun/api/trade?api-key=abc123TAJNA",
                    "apikey=abc123TAJNA&x=1", "secret = abc123TAJNA"):
            out = aplog.scrub(raw)
            self.assertNotIn("abc123TAJNA", out, raw)
            self.assertIn("…", out)
        self.assertEqual(aplog.scrub("signal star 412 s"), "signal star 412 s")   # ordinary reasons stay as written


if __name__ == "__main__":
    unittest.main()
