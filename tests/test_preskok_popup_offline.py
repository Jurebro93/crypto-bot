"""Pop-up preskočenog signala (10.11., Jure: "za ove preskočene tokene ... stavi na koliko market capa ga je zvao
dotični wallet ili influencer ... koliko se cijena makla u 5, 10, 15 minuta ... pop-up gdje piše koliko je skočio u 5
minuta, kad je, na koliko ga je zvao market capa i koliko je trenutno market capa sa točnim vremenom, satom").

What is checked: trade/aplog's sig_ts (the call behind a decision) for the demo stage and for the real-money stage;
kol/preskoceni measuring from the call's minute in one candle request (price at the call, +5/+10/+15 min, gaps, no
trade in the call's minute, a decision before or after the call, the supply from kol.db or DexScreener, the 1000-
candle cap), the migration of an old skip_path and the one extra measurement of its rows; the compact line in the
box rows; the pop-up /pravi-trade/preskok (its table, the access check, owner vs invited reason, unmeasured and
under-$30k skips, no network beyond the live cache). No network, databases in a temp dir.

    python3 -m unittest tests.test_preskok_popup_offline -v
"""
import json
import os
import re
import sqlite3
import sys
import tempfile
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from kol import minute, preskoceni, store as kstore  # noqa: E402
from league import copy, store  # noqa: E402
from trade import aplog, executor, settings  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
with open(os.path.join(ROOT, "kol", "config.json")) as _f:
    CFG = json.load(_f)
NOW = int(time.time()) // 60 * 60
H, M = 3600, 60
P = 85e-6           # the price at the call: 85k $ with a supply of 1e9
SUPPLY = 1e9
_WAKE = mock.patch.object(copy, "WAKE", os.path.join(tempfile.mkdtemp(), ".copy_wake"))


def setUpModule():   # a follow wakes the copy loop: never the repo's own .copy_wake
    _WAKE.start()


def tearDownModule():
    _WAKE.stop()


def candles(m_from, m_to, closes, peak=None):
    """1-minute candles from m_from to m_to; the price is carried forward from `closes` {minute ts: close} (a minute
    listed with None has no candle: a gap). peak: (minute ts, high), a body-wide spike there."""
    out, cur = [], None
    for m in range(m_from, m_to + M, M):
        if m in closes and closes[m] is None:
            continue
        c = closes.get(m, cur)
        if c is None:
            continue
        o = cur if cur is not None else c
        hi, lo = max(o, c), min(o, c)
        if peak and peak[0] == m:
            o, hi, c = peak[1] * 0.96, peak[1], peak[1] * 0.96
        out.append((m, o, hi, lo, c, 100.0))
        cur = c
    return out


def text(html):
    return " ".join(re.sub(r"<[^>]+>", " ", html).replace("\u00a0", " ").split())


def table(html):
    """[[cell text, ...], ...] of the pop-up's table, the header first."""
    t = re.search(r"<table class=\"ap-mk ap-skt\">(.*?)</table>", html, re.S).group(1)
    return [[text(c) for c in re.findall(r"<t[dh]>(.*?)</t[dh]>", r, re.S)] for r in re.findall(r"<tr[^>]*>(.*?)</tr>", t, re.S)]


class Env(unittest.TestCase):
    """trade.db, league.db, kol.db and minute.db in a temp dir, the owner Jure and the invited player Ivan."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = self.tmp.name
        self.kp, self.mp = os.path.join(d, "kol.db"), os.path.join(d, "minute.db")
        self.kc = kstore.connect(self.kp)
        self.mc = minute.connect(self.mp)
        preskoceni.ensure(self.mc)
        self._saved = (settings.DB, store.DB, kstore.DB)
        settings.DB, store.DB, kstore.DB = os.path.join(d, "trade.db"), os.path.join(d, "league.db"), self.kp
        self._env = mock.patch.dict(os.environ, {"MINUTE_DB": self.mp, "TRADE_OWNER": "Jure"})
        self._env.start()
        self.tc = executor.connect(settings.DB)
        self.lg = store.connect(store.DB)
        copy.ensure(self.lg)
        self.lg.execute("INSERT OR IGNORE INTO accounts VALUES (?,?,?)", (settings.LEAGUE_USER, 1e9, 0))
        self.fid = copy.follow(self.lg, settings.LEAGUE_USER, "kol", "ansem", "", 25, 5, "tpsl", "15%", "-20%")
        settings.put(self.tc, "invited", ["Ivan"])
        aplog._DAY.clear()
        preskoceni._LAST["ts"] = 0.0
        self.fetched = []
        from ui import pravitrade
        self.pt = pravitrade
        self._reset()

    def tearDown(self):
        self._reset()
        settings.DB, store.DB, kstore.DB = self._saved
        self._env.stop()
        for c in (self.tc, self.lg, self.kc, self.mc):
            c.close()
        self.tmp.cleanup()

    def _reset(self):
        pt = self.pt
        with pt._LOCK:
            pt._SK.update(ts=0.0, key=None, html=None, rows=None)
            pt._SKP.update(ts=0.0, key=None, rows=None)
            pt._DN.update(ts=0.0, key=None, rows=None)
            pt._DN_LINE.update(ts=0.0, key=None, line=None)
            pt._LIVE_CACHE.clear()
            pt._LIVE_FAIL.clear()
            pt._LIVE_WANT.clear()

    # ---- the decisions ----
    def demo_skip(self, token, sym, ts, note, ev_ts=None):
        """A skip of the demo copy stage (copy_log 'preskočeno'); ev_ts = when the followed account called."""
        self.lg.execute("INSERT INTO copy_log (follow_id, token, side, ev_ts, ts, symbol, action, note, trade_id) "
                        "VALUES (?,?,?,?,?,?,?,?,?)", (self.fid, token, "buy", ev_ts, ts, sym, "preskočeno", note, None))
        self.lg.commit()

    def demo_entry(self, token, sym, ts, ev_ts, trade_id=None):
        """A demo entry of the follow (league trade + copy_log 'ulaz' with the call's time); its trade id."""
        tid = self.lg.execute("INSERT INTO trades (user, token, symbol, opened_ts, status, size_usd, source, follow_id) "
                              "VALUES (?,?,?,?,?,?,?,?)", (settings.LEAGUE_USER, token, sym, ts, "open", 25,
                                                           "copy KOL ansem", self.fid)).lastrowid
        self.lg.execute("INSERT INTO copy_log (follow_id, token, side, ev_ts, ts, symbol, action, note, trade_id) "
                        "VALUES (?,?,?,?,?,?,?,?,?)", (self.fid, token, "buy", ev_ts, ts, sym, "ulaz", "kupljeno",
                                                       trade_id or tid))
        self.lg.commit()
        return tid

    def position(self, token, sym, ts, status, reason, league_id=None, src="copy KOL ansem"):
        pid = self.tc.execute("INSERT INTO positions (token, symbol, opened_ts, mode, status, reason, sol_in, league_id) "
                              "VALUES (?,?,?,?,?,?,?,?)", (token, sym, ts, "dry", status, reason,
                                                           0.05 if status in ("open", "closed") else None, league_id)).lastrowid
        self.tc.execute("INSERT INTO orders (ts, position_id, token, side, mode, amount_in, status, reason) VALUES "
                        "(?,?,?,?,?,?,?,?)", (ts, pid, token, "buy", "dry", 50_000_000,
                                              {"blocked": "blocked", "failed": "failed"}.get(status, "dry"), src))
        self.tc.commit()
        return pid

    def real_skip(self, token, sym, ts, reason, ev_ts):
        """A signal the real-money mirror refused: the demo entry it mirrors carries the call's time."""
        tid = self.demo_entry(token, sym, ts - 2, ev_ts)
        return self.position(token, sym, ts, "blocked", reason, league_id=tid)

    def log(self, now=NOW + 30):
        return aplog.entries(self.tc, self.lg, limit=500, since=int(now) - 86400, now=now)

    def one(self, token, now=NOW + 30):
        rows = [e for e in self.log(now) if e["token"] == token and e["side"] == "buy"]
        self.assertEqual(len(rows), 1, rows)
        return rows[0]

    # ---- the measurement ----
    def fetch(self, data):
        def f(pool, start, end):
            self.fetched.append((pool, start, end))
            v = data.get(pool, [])
            if isinstance(v, Exception):
                raise v
            return v
        return f

    def measure(self, data, now=NOW, pairs_fn=None):
        return preskoceni.run(self.mc, self.kc, CFG, now, fetch=self.fetch(data), entries=preskoceni.decisions(now),
                              pairs_fn=pairs_fn, log=lambda *a, **k: None)

    def far_call(self):
        """FAR: called 11 min before the skip and nobody traded from the call's minute to 5 min after it, so the
        call keeps only its time and the moves count from the decision (close 1.08 P = 92k $)."""
        self.kc.execute("INSERT INTO tokens (token, pair, supply) VALUES ('FAR', 'PFAR', ?)", (SUPPLY,))
        self.kc.commit()
        ts = NOW - 3 * H + 41
        sig = ts - 11 * M
        self.demo_skip("FAR", "FAR", ts, "signal star 11 min", sig)
        m_sig, m_dec = preskoceni.minute_of(sig), preskoceni.minute_of(ts)
        d = 1.08 * P
        c = [x for x in candles(m_sig - 15 * M, m_dec + 70 * M,
                                {m_sig - 15 * M: P, m_dec: d, m_dec + 5 * M: 1.02 * d, m_dec + 10 * M: 1.11 * d,
                                 m_dec + 15 * M: 0.93 * d}, peak=(m_dec + 20 * M, 1.2 * d))
             if not (m_sig <= x[0] <= m_sig + 5 * M)]
        self.measure({"PFAR": c})
        return ts

    def row(self, token, ts):
        return preskoceni.lookup(self.mc, [(token, preskoceni.minute_of(ts))]).get((token, preskoceni.minute_of(ts)))

    def hot(self, token="HOT", pool="PHOT", supply=SUPPLY, real=False):
        """A skip 3 h ago whose call came 4 min 7 s before the decision; its candles."""
        if supply is not None or pool:
            self.kc.execute("INSERT INTO tokens (token, pair, supply) VALUES (?,?,?)", (token, pool, supply))
            self.kc.commit()
        ts = NOW - 3 * H + 41
        sig = ts - 247
        m_sig, m_dec = preskoceni.minute_of(sig), preskoceni.minute_of(ts)
        if real:
            self.real_skip(token, token, ts, "signal star 4 min: kupnja samo dok je poziv svjež (do 180 s)", sig)
        else:
            self.demo_skip(token, token, ts, "signal star 4 min: kupnja samo dok je poziv svjež (do 180 s)", sig)
        c = candles(m_sig - 15 * M, m_dec + 70 * M,
                    {m_sig: P, m_dec: 1.08 * P, m_sig + 5 * M: 1.14 * P, m_sig + 10 * M: 1.22 * P, m_sig + 15 * M: 1.09 * P,
                     m_dec + 28 * M: 1.2 * P}, peak=(m_dec + 27 * M, 1.08 * 1.35 * P))
        return ts, sig, c


# ---------- 1. the time of the signal ----------------------------------------------------------------------------

class SignalTime(Env):
    def test_demo_stage_rows_carry_the_time_of_the_call(self):
        ts = NOW - 2 * H
        self.demo_skip("DEMO", "DMO", ts, "signal star 4 min (vidjeli smo ga tek sada)", ev_ts=ts - 247)
        e = self.one("DEMO")
        self.assertEqual((e["kind"], e["stage"], e["ts"], e["sig_ts"]), ("preskocio", "demo", ts, ts - 247))
        self.demo_skip("NOEV", "NOE", ts, "likvidnost premala", ev_ts=None)    # an old row without ev_ts
        self.assertIsNone(self.one("NOEV")["sig_ts"])

    def test_real_money_rows_carry_the_call_of_the_demo_entry_they_mirror(self):
        ts = NOW - H
        self.real_skip("REAL", "RL", ts, "praćenje bez dokaza u demu (zatvorenih 3 od 10)", ev_ts=ts - 41)
        e = self.one("REAL")
        self.assertEqual((e["kind"], e["stage"], e["source"], e["sig_ts"]), ("preskocio", "pravi", "KOL ansem", ts - 41))
        # a demo entry the mirror never saw (nije_proslo): its own ev_ts
        self.demo_entry("MISS", "MS", ts - 600, ts - 650)
        m = self.one("MISS")
        self.assertEqual((m["kind"], m["sig_ts"]), ("nije_proslo", ts - 650))
        # a manual buy, and a 'ulaz' row that belongs to another trade of the follow: no call time
        self.position("HAND", "HD", ts, "blocked", "limit: 5 otvorenih pozicija", src="ručno (pravi trade)")
        self.assertIsNone(self.one("HAND")["sig_ts"])
        other = self.demo_entry("OTHER", "OT", ts - 5, ts - 30)
        tid = self.lg.execute("INSERT INTO trades (user, token, symbol, opened_ts, status, follow_id) VALUES (?,?,?,?,?,?)",
                              (settings.LEAGUE_USER, "OTHER", "OT", ts, "open", self.fid)).lastrowid
        self.lg.commit()
        self.assertNotEqual(tid, other)
        self.position("OTHER", "OT", ts, "blocked", "limit: 5 otvorenih pozicija", league_id=tid)
        self.assertIsNone([e for e in self.log() if e["token"] == "OTHER" and e["kind"] == "preskocio"][0]["sig_ts"])

    def test_existing_keys_are_unchanged_and_a_sale_has_none(self):
        ts = NOW - H
        pid = self.position("SOLD", "SD", ts - 600, "closed", None)
        self.tc.execute("UPDATE positions SET sol_back=0.07 WHERE id=?", (pid,))
        self.tc.execute("INSERT INTO orders (ts, position_id, token, side, mode, amount_out, status, reason) VALUES "
                        "(?,?,?,?,?,?,?,?)", (ts, pid, "SOLD", "sell", "dry", 70_000_000, "dry", "TP +40 %"))
        self.tc.commit()
        keys = {"ts", "kind", "token", "symbol", "source", "why", "why_short", "sol", "pnl_pct", "mode", "stage", "sig",
                "trebao", "side", "id", "sig_ts"}
        for e in self.log():
            self.assertEqual(set(e), keys)
            self.assertFalse(any(k.startswith("_") for k in e))
        sale = [e for e in self.log() if e["kind"] == "prodao"][0]
        self.assertIsNone(sale["sig_ts"])

    def test_without_league_db_the_log_still_reads(self):
        self.real_skip("REAL", "RL", NOW - H, "signal star 5 min", ev_ts=NOW - H - 300)
        rows = aplog.entries(self.tc, None, now=NOW + 30)   # opens league.db read-only itself
        self.assertEqual([e["sig_ts"] for e in rows if e["token"] == "REAL"], [NOW - H - 300])
        os.remove(store.DB)
        self.assertEqual([e["sig_ts"] for e in aplog.entries(self.tc, None, now=NOW + 30) if e["token"] == "REAL"], [None])


# ---------- 2. the prices from the call ---------------------------------------------------------------------------

class Prices(unittest.TestCase):
    M0 = NOW - 3 * H     # the call's minute

    def test_call_minute_and_the_three_steps(self):
        m = self.M0
        c = candles(m - 10 * M, m + 70 * M, {m - M: 0.9 * P, m: P, m + 5 * M: 1.14 * P, m + 10 * M: 1.22 * P,
                                              m + 15 * M: 1.09 * P, m + 16 * M: 2 * P})
        o = preskoceni.at_signal(c, m + 4 * M + 41, m + 13)
        self.assertEqual(o["sig_ts"], m + 13)
        self.assertAlmostEqual(o["p_sig"], P)
        self.assertAlmostEqual(o["p5"], 1.14 * P)
        self.assertAlmostEqual(o["p10"], 1.22 * P)
        self.assertAlmostEqual(o["p15"], 1.09 * P)                   # minute 16 is after it

    def test_gaps_take_the_last_close_before(self):
        m = self.M0
        c = candles(m - 10 * M, m + 70 * M, {m: P, m + 3 * M: 1.3 * P, m + 4 * M: None, m + 5 * M: None,
                                              m + 6 * M: 1.5 * P, m + 9 * M: None, m + 10 * M: None, m + 11 * M: None})
        o = preskoceni.at_signal(c, m + 20 * M, m)
        self.assertAlmostEqual(o["p5"], 1.3 * P)                     # no trade at minutes 4 and 5: the close of 3
        self.assertAlmostEqual(o["p10"], 1.5 * P)                    # nor 9 to 11: the close of 8 (carried 1.5)

    def test_no_trade_in_the_call_minute(self):
        m = self.M0
        c = [x for x in candles(m - 10 * M, m + 70 * M, {m - 5 * M: 0.8 * P, m + 2 * M: P, m + 7 * M: 1.2 * P})
             if not (m - 4 * M <= x[0] <= m + M)]                     # nothing from 4 min before to 1 min after the call
        o = preskoceni.at_signal(c, m + 3 * M, m + 30)
        self.assertAlmostEqual(o["p_sig"], 0.8 * P)                  # the open of the next candle (minute 2)
        self.assertAlmostEqual(o["p5"], P)
        # nothing within 5 minutes after the call: the moves count from the decision, the call keeps only its time
        c2 = [x for x in c if not (m < x[0] <= m + 6 * M)]
        o2 = preskoceni.at_signal(c2, m + 8 * M, m + 30)
        self.assertEqual((o2["sig_ts"], o2["p_sig"]), (m + 30, None))
        self.assertAlmostEqual(o2["p5"], c2[-1][4])                  # decision minute + 5: the flat 1.2 P

    def test_decision_before_or_after_the_call_and_no_call(self):
        m = self.M0
        c = candles(m - 30 * M, m + 90 * M, {m - 10 * M: 0.5 * P, m: P, m + 5 * M: 2 * P, m + 10 * M: 3 * P})
        before = preskoceni.at_signal(c, m - 10 * M + 5, m + 20)     # the bot decided 10 min BEFORE the call's minute
        self.assertAlmostEqual(before["p_sig"], P)
        self.assertAlmostEqual(before["p5"], 2 * P)                  # still counted from the call
        none = preskoceni.at_signal(c, m - 10 * M + 5, None)
        self.assertEqual((none["sig_ts"], none["p_sig"]), (None, None))
        self.assertAlmostEqual(none["p5"], 0.5 * P)                  # from the decision's minute
        self.assertAlmostEqual(none["p10"], P)

    def test_moves_market_caps_and_changes(self):
        row = {"ts": self.M0 + 4 * M, "entry": 1.08 * P, "hi60": 0.35, "max_min": 27, "sig_ts": self.M0 + 13, "p_sig": P,
               "p5": 1.14 * P, "p10": 1.22 * P, "p15": 1.09 * P, "supply": SUPPLY, "bad": None}
        mv = preskoceni.moves(row)
        self.assertEqual(mv["ref"], "poziv")
        self.assertAlmostEqual(mv["poziv"][1], 85_000)
        self.assertAlmostEqual(mv["odluka"][2], 0.08)
        self.assertEqual([(k, at) for k, at, *_ in mv["steps"]],
                         [(5, self.M0 + 5 * M), (10, self.M0 + 10 * M), (15, self.M0 + 15 * M)])
        self.assertAlmostEqual(mv["steps"][1][3], 103_700)
        self.assertEqual(mv["hi"][0], self.M0 + 31 * M)
        self.assertAlmostEqual(mv["hi"][3], 1.08 * 1.35 - 1)
        # no supply on the row: the live quote's, else only the moves
        no_sup = {**row, "supply": None}
        self.assertIsNone(preskoceni.moves(no_sup)["poziv"][1])
        self.assertAlmostEqual(preskoceni.moves(no_sup, 2e9)["poziv"][1], 170_000)
        dec = preskoceni.moves({**row, "p_sig": None})
        self.assertEqual((dec["ref"], dec["ref_min"], dec["poziv"]), ("odluka", self.M0 + 4 * M, None))
        self.assertIsNone(preskoceni.moves({"bad": "pool"}))
        self.assertIsNone(preskoceni.moves(None))

    def test_clock_in_zagreb(self):
        ts = 1794300000   # 10.11.2026. 08:40:00 UTC = 09:40:00 in Zagreb (CET)
        self.assertEqual(preskoceni.clock(ts, ts), "09:40:00")
        self.assertEqual(preskoceni.clock(ts, ts, sec=False), "09:40")
        self.assertEqual(preskoceni.clock(ts, ts + 86400), "jučer 09:40:00")
        self.assertEqual(preskoceni.hm(ts, ts), "09:40")


# ---------- 2. the measurement --------------------------------------------------------------------------------------

class Measure(Env):
    def test_one_request_from_the_call_and_every_new_column(self):
        ts, sig, c = self.hot(real=True)
        res = self.measure({"PHOT": c}, pairs_fn=lambda t: self.fail("kol.db had the pool and the supply"))
        self.assertEqual(res, (1, 1, 0))
        m_sig, m_dec = preskoceni.minute_of(sig), preskoceni.minute_of(ts)
        self.assertEqual(self.fetched, [("PHOT", m_sig - 10 * M, m_dec + preskoceni.WAIT_S)])
        r = self.row("HOT", ts)
        self.assertEqual((r["sig_ts"], r["supply"], r["ver"], r["max_min"], r["bad"]), (sig, SUPPLY, preskoceni.VER, 27, None))
        for k, want in (("p_sig", P), ("entry", 1.08 * P), ("p5", 1.14 * P), ("p10", 1.22 * P), ("p15", 1.09 * P)):
            self.assertAlmostEqual(r[k], want, msg=k)
        self.assertEqual(preskoceni.verdict(r, ts, NOW)["kind"], "miss")   # the old verdict is still there

    def test_supply_from_the_dexscreener_pairs_in_one_request(self):
        t1, _, c1 = self.hot("NEW1", pool=None, supply=None)
        self.kc.execute("DELETE FROM tokens")
        self.kc.execute("INSERT INTO tokens (token, pair, supply) VALUES ('NEW2', 'P2', NULL)")   # a pool, no supply
        self.kc.commit()
        self.demo_skip("NEW2", "N2", t1 - 60, "likvidnost premala", t1 - 90)
        asked = []

        def dex(toks):
            asked.append(sorted(toks))
            return [{"chainId": "solana", "baseToken": {"address": "NEW1"}, "pairAddress": "SHALLOW", "priceUsd": "0.0001",
                     "marketCap": 1, "liquidity": {"usd": 10}},
                    {"chainId": "solana", "baseToken": {"address": "NEW1"}, "pairAddress": "DEEP", "priceUsd": "0.00009",
                     "marketCap": 90000, "fdv": 95000, "liquidity": {"usd": 30000}},
                    {"chainId": "solana", "baseToken": {"address": "NEW2"}, "pairAddress": "P2DEX", "priceUsd": "0.002",
                     "fdv": 2_000_000, "liquidity": {"usd": 50000}}]
        self.measure({"DEEP": c1, "P2": c1}, pairs_fn=dex)
        self.assertEqual(asked, [["NEW1", "NEW2"]])                  # one batched request for both
        self.assertEqual(sorted(f[0] for f in self.fetched), ["DEEP", "P2"])   # kol.db's pool stays NEW2's pool
        self.assertAlmostEqual(self.row("NEW1", t1)["supply"] / 1e9, 1)   # marketCap / price of the deepest pair
        self.assertAlmostEqual(self.row("NEW2", t1 - 60)["supply"] / 1e9, 1)   # fdv when there is no marketCap
        self.assertIsNone(preskoceni.pair_supply({"priceUsd": "0", "marketCap": 5}))
        self.assertIsNone(preskoceni.pair_supply({"priceUsd": "x"}))

    def test_dexscreener_down_leaves_the_supply_unknown_not_the_measurement(self):
        ts, _, c = self.hot(supply=None)

        def down(toks):
            raise OSError("DexScreener ne odgovara")
        self.measure({"PHOT": c}, pairs_fn=down)
        r = self.row("HOT", ts)
        self.assertIsNone(r["supply"])
        self.assertAlmostEqual(r["p5"], 1.14 * P)

    def test_a_call_older_than_a_thousand_candles(self):
        self.kc.execute("INSERT INTO tokens (token, pair, supply) VALUES ('OLD', 'POLD', 1e9)")
        self.kc.commit()
        ts = NOW - 2 * H
        sig = ts - 20 * H
        self.demo_skip("OLD", "OLD", ts, "signal star 20 h", sig)
        m_dec = preskoceni.minute_of(ts)
        c = candles(m_dec - 900 * M, m_dec + 70 * M, {m_dec: P, m_dec + 5 * M: 1.1 * P})
        self.measure({"POLD": c})
        end = m_dec + preskoceni.WAIT_S
        self.assertEqual(self.fetched, [("POLD", end - preskoceni.MAX_SPAN_S, end)])
        self.assertLessEqual(minute.math.ceil((end - self.fetched[0][1]) / M) + 2, 1000)
        r = self.row("OLD", ts)
        self.assertEqual((r["sig_ts"], r["p_sig"]), (sig, None))   # the call keeps its time; moves from the decision
        self.assertAlmostEqual(r["p5"], 1.1 * P)


class Migration(Env):
    OLD = """CREATE TABLE skip_path (
    token TEXT, ts INTEGER, pool TEXT, entry REAL, lag_s INTEGER, t15 INTEGER, sl_min INTEGER, hi60 REAL, lo60 REAL,
    r60 REAL, max_min INTEGER, lv TEXT, bad TEXT, retry_ts INTEGER, done_ts INTEGER, PRIMARY KEY (token, ts));
CREATE INDEX skip_path_ts ON skip_path (ts)"""

    def old_db(self):
        """minute.db as it was before 10.11.: one measured skip of HOT and one without a pool."""
        self.mc.execute("DROP TABLE skip_path")
        self.mc.executescript(self.OLD)
        self.ts, self.sig, self.c = self.hot()
        m = preskoceni.minute_of(self.ts)
        self.mc.execute("INSERT INTO skip_path VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        ("HOT", m, "PHOT", 1.08 * P, 19, 27, None, 0.35, -0.04, 0.12, 27, "{}", None, None, NOW - 7000))
        self.mc.execute("INSERT INTO skip_path (token, ts, bad, retry_ts, done_ts) VALUES ('GONE', ?, 'pool', ?, ?)",
                        (m, NOW + 80000, NOW - 7000))
        self.demo_skip("GONE", "GN", self.ts, "likvidnost premala", self.sig)
        self.mc.commit()

    def test_columns_are_added_once_and_old_rows_keep_their_numbers(self):
        self.old_db()
        ro = sqlite3.connect(f"file:{self.mp}?mode=ro", uri=True)
        try:   # the page reads an unmigrated table (read-only) without an error: the new columns are None
            r = preskoceni.lookup(ro, [("HOT", preskoceni.minute_of(self.ts))])[("HOT", preskoceni.minute_of(self.ts))]
        finally:
            ro.close()
        self.assertEqual((r["entry"], r["t15"], r["p5"], r["supply"], r["ver"]), (1.08 * P, 27, None, None, None))
        preskoceni.ensure(self.mc)
        preskoceni.ensure(self.mc)                                   # idempotent
        cols = [x[1] for x in self.mc.execute("PRAGMA table_info(skip_path)")]
        self.assertEqual(cols, list(preskoceni.COLS))
        r = self.row("HOT", self.ts)
        self.assertEqual((r["entry"], r["t15"], r["hi60"], r["p5"], r["ver"]), (1.08 * P, 27, 0.35, None, None))

    def test_old_rows_are_measured_once_more(self):
        self.old_db()
        preskoceni.ensure(self.mc)
        due = preskoceni.due(self.mc, preskoceni.decisions(NOW), NOW, 20)
        self.assertEqual(due, {"HOT": [preskoceni.minute_of(self.ts)]})   # GONE waits for its retry, as before
        self.assertEqual(self.measure({"PHOT": self.c})[:2], (1, 1))
        r = self.row("HOT", self.ts)
        self.assertEqual((r["ver"], r["sig_ts"], r["supply"]), (preskoceni.VER, self.sig, SUPPLY))
        self.assertAlmostEqual(r["p10"], 1.22 * P)
        self.assertEqual(preskoceni.due(self.mc, preskoceni.decisions(NOW), NOW, 20), {})   # and not again
        self.assertEqual(self.measure({"PHOT": self.c}, now=NOW + 300)[:2], (0, 0))

    def test_a_failed_second_measurement_keeps_the_old_numbers(self):
        self.old_db()
        self.measure({"PHOT": OSError("HTTP Error 403")})            # network: kept, tried again in an hour
        r = self.row("HOT", self.ts)
        self.assertEqual((r["entry"], r["t15"], r["bad"], r["ver"], r["retry_ts"]),
                         (1.08 * P, 27, None, None, NOW + preskoceni.RETRY_ERR_S))
        self.assertEqual(preskoceni.due(self.mc, preskoceni.decisions(NOW + 60), NOW + 60, 20), {})
        gone = OSError("HTTP Error 404")
        gone.code = 404
        self.measure({"PHOT": gone}, now=NOW + preskoceni.RETRY_ERR_S + 1)   # the pool is gone: kept, not asked again
        r = self.row("HOT", self.ts)
        self.assertEqual((r["entry"], r["bad"], r["ver"], r["retry_ts"]), (1.08 * P, None, preskoceni.VER, None))
        self.assertEqual(preskoceni.verdict(r, self.ts, NOW)["kind"], "miss")


# ---------- 3. the line in the box's rows -------------------------------------------------------------------------

class RowLine(Env):
    def box(self, owner=True, now=NOW + 30):
        return self.pt.skip_box(self.tc, self.pt._cfg(self.tc), now, owner)

    def lines(self, html):
        """{symbol: the row's compact line} of the rows that have one."""
        out = {}
        for chunk in html.split('class="ms-row')[1:]:
            name = re.search(r'<div class="ms-t">(.*?)</div>', chunk, re.S)
            line = re.search(r"<div class=ap-skl>(.*?)</div></div>", chunk, re.S)
            if name and line:
                out[text(name.group(1))] = text(line.group(1))
        return out

    def test_market_cap_at_the_call_and_the_three_moves(self):
        ts, _, c = self.hot()
        self.measure({"PHOT": c})
        html = self.box()
        self.assertEqual(self.lines(html)["HOT"], "zvan na 85k $ · 5 min +14 % · 10 min +22 % · 15 min +9 %")
        self.assertIn('class="ms-row ap-wrap ap-skr ms-tap"', html)
        self.assertIn(f'data-pop="/pravi-trade/preskok?m=HOT&amp;t={ts}"', html)   # the pop-up of this skip
        self.assertIn("<span class=ap-sks> · </span>", html)        # a phone puts the moves on their own line
        self.assertIn("@media(max-width:560px){.ap-skl .ap-skc{display:block}", self.pt.CSS)

    def test_young_unmeasured_under_floor_and_no_supply(self):
        ts, sig, c = self.hot(supply=None)
        self.measure({"PHOT": c})
        self.demo_skip("YOUNG", "YNG", NOW - 10 * M, "signal star 5 min", NOW - 10 * M - 300)
        self.demo_skip("NOSIG", "NSG", NOW - 20 * M, "likvidnost premala", None)
        self.demo_skip("TINY", "TNY", NOW - 2 * H, "MC 21k ispod 30k", NOW - 2 * H - 40)
        html = self.box()
        got = self.lines(html)
        self.assertEqual(got["HOT"], "od poziva: 5 min +14 % · 10 min +22 % · 15 min +9 %")   # no supply anywhere
        self.assertEqual(got["YNG"], "zvan u " + preskoceni.clock(NOW - 10 * M - 300, NOW + 30))
        self.assertEqual(got["TNY"], "zvan u " + preskoceni.clock(NOW - 2 * H - 40, NOW + 30))
        self.assertNotIn("NSG", got)                                 # nothing known yet: no line at all
        self.assertIsNone(self.row("TINY", NOW - 2 * H))             # under $30k: never measured (CLAUDE.md)
        self.assertNotIn("TINY", {f[0] for f in self.fetched})

    def test_moves_from_the_decision_when_the_calls_price_is_unknown(self):
        self.far_call()
        self.assertEqual(self.lines(self.box())["FAR"], "preskočen na 92k $ · 5 min +2 % · 10 min +11 % · 15 min −7 %")


# ---------- 4. the pop-up -----------------------------------------------------------------------------------------

class Popup(Env):
    def live(self, mint, price, mcap, at):
        """The shared live cache as the background thread leaves it (no fetch in a test)."""
        with self.pt._LOCK:
            self.pt._LIVE_CACHE[(mint,)] = (at, {mint: {"price": price, "mcap": mcap, "liq": 20000.0}})

    def pop(self, user, mint, t, now=NOW + 30):
        return self.pt.skip_popup(user, mint, str(t), now=now)

    def test_the_table_with_clock_times_market_caps_and_moves(self):
        ts, sig, c = self.hot()
        self.measure({"PHOT": c})
        self.live("HOT", 95.2e-6, 95_200, NOW + 28)
        from event_calendar import http
        from ui import prijedlog
        before = os.path.getmtime(self.mp)
        with mock.patch.object(http, "get_json", side_effect=AssertionError("network")), \
                mock.patch.object(http, "_fetch", side_effect=AssertionError("network")), \
                mock.patch.object(prijedlog, "live_market", side_effect=AssertionError("past the live cache")):
            html = self.pop("Jure", "HOT", ts)
        self.assertEqual(os.path.getmtime(self.mp), before)          # minute.db only read
        ck = lambda x, sec=True: preskoceni.clock(x, NOW + 30, sec)   # noqa: E731
        m_sig, m_dec = preskoceni.minute_of(sig), preskoceni.minute_of(ts)
        self.assertEqual(table(html), [
            ["", "Vrijeme", "Market cap", "Od poziva"],
            ["Poziv", ck(sig), "85k $", ""],
            ["Preskočeno", ck(ts), "92k $", "+8 %"],
            ["+5 min", ck(m_sig + 5 * M, False), "97k $", "+14 %"],
            ["+10 min", ck(m_sig + 10 * M, False), "104k $", "+22 %"],
            ["+15 min", ck(m_sig + 15 * M, False), "93k $", "+9 %"],
            ["Najviše u 60 min", ck(m_dec + 27 * M, False), "124k $", "+46 %"],
            ["Sada", ck(NOW + 28), "95k $", "+12 %"]])
        self.assertIn("<h3 translate=no>HOT</h3>", html)
        self.assertIn("KOL ansem", html)
        self.assertIn("signal star 4 min: kupnja samo dok je poziv svjež (do 180 s)", html)   # the owner: as written
        self.assertIn("propušteno · od preskoka: +15 % za 27 min", text(html))
        self.assertIn('data-pop="/pravi-trade/token?m=HOT">Provjera tokena uživo', html)   # the full token pop-up
        self.assertRegex(ck(sig), r"^\d\d:\d\d:\d\d$")

    def test_invited_viewer_reads_the_short_reason_a_stranger_nothing(self):
        ts, _, c = self.hot(real=True)
        self.measure({"PHOT": c})
        self.live("HOT", 95.2e-6, 95_200, NOW + 28)
        guest = self.pop("Ivan", "HOT", ts)
        self.assertIn("signal star", guest)
        self.assertNotIn("kupnja samo dok je poziv svjež", guest)
        self.assertEqual(len(table(guest)), 8)
        self.assertIsNone(self.pop("Netko", "HOT", ts))             # same access as the page: None -> 403
        self.assertIsNone(self.pop(None, "HOT", ts))
        with open(os.path.join(ROOT, "run_ui.py"), encoding="utf-8") as f:
            src = f.read()
        self.assertIn('if path == "/pravi-trade/preskok":', src)
        self.assertIn('pravitrade.skip_popup(self.user, qs.get("m", ""), qs.get("t", ""))', src)
        self.assertIn("if(!d.open)d.showModal()", self.pt.POP_JS)    # the link inside swaps the open pop-up

    def test_unknown_young_and_under_floor(self):
        self.assertIn("Ta odluka nije pronađena", self.pop("Jure", "HOT", "x"))
        self.assertIn("nije među preskočenima u zadnja 24 h", self.pop("Jure", "NEMA", NOW - H))
        young = NOW - 10 * M
        self.demo_skip("YOUNG", "YNG", young, "signal star 5 min", young - 300)
        self._reset()   # the decisions are kept SKIP_TTL_S: a new one shows after that (here: at once)
        self.live("YOUNG", 1e-4, 100_000, NOW + 29)
        html = self.pop("Jure", "YOUNG", young)
        self.assertEqual([r[0] for r in table(html)], ["", "Poziv", "Preskočeno", "Sada"])   # only what is known
        self.assertEqual(table(html)[1][1:3], [preskoceni.clock(young - 300, NOW + 30), "–"])
        self.assertEqual(table(html)[3][2:], ["100k $", ""])
        self.assertIn("mjeri se · rezultat oko", text(html))
        tiny = NOW - 2 * H
        self.demo_skip("TINY", "TNY", tiny, "MC 21k ispod 30k", tiny - 40)
        self._reset()
        with mock.patch.object(self.pt, "_live_cached", side_effect=AssertionError("under $30k is not analysed")):
            html = self.pop("Jure", "TINY", tiny)
        self.assertEqual([r[0] for r in table(html)], ["", "Poziv", "Preskočeno"])
        self.assertIn("ispod 30k · po pravilu se ne kupuje ni ne mjeri", text(html))

    def test_rows_measured_before_and_moves_from_the_decision(self):
        ts = self.far_call()
        html = self.pop("Jure", "FAR", ts)
        rows = table(html)
        self.assertEqual(rows[0][3], "Od preskoka")
        self.assertEqual(rows[1][2:], ["–", ""])                     # the call's time, no price
        self.assertEqual(rows[2][2:], ["92k $", ""])                 # the reference
        self.assertEqual(rows[3], ["+5 min", preskoceni.clock(preskoceni.minute_of(ts) + 5 * M, NOW + 30, False),
                                   "94k $", "+2 %"])                  # counted from the decision's minute
        self.assertIn("Cijena u minuti poziva nije poznata", html)
        # a row from before 10.11. (no call price, no steps, no supply): the moves it has, said why the rest is missing
        self.mc.execute("UPDATE skip_path SET p_sig=NULL, p5=NULL, p10=NULL, p15=NULL, supply=NULL, ver=NULL")
        self.mc.commit()
        self._reset()
        html = self.pop("Jure", "FAR", ts)
        self.assertEqual([r[0] for r in table(html)], ["", "Poziv", "Preskočeno", "Najviše u 60 min"])
        self.assertEqual(table(html)[3][2:], ["–", "+20 %"])
        self.assertIn("Izmjereno prije nego što se bilježio poziv", html)

    def test_cheap_the_decision_comes_from_the_box_rows(self):
        ts, _, c = self.hot()
        self.measure({"PHOT": c})
        self.pt.skip_box(self.tc, self.pt._cfg(self.tc), NOW + 20, True)
        with mock.patch.object(self.pt, "_skip_rows", side_effect=AssertionError("the log read again")):
            self.assertIn("<table", self.pop("Jure", "HOT", ts, now=NOW + 30))
        self._reset()
        n = []
        real = self.pt._skip_rows
        with mock.patch.object(self.pt, "_skip_rows", lambda *a: n.append(1) or real(*a)):
            for k in range(5):   # the pop-up asks every second: one log read per SKIP_TTL_S
                self.pop("Jure", "HOT", ts, now=NOW + 30 + k)
        self.assertEqual(len(n), 1)


if __name__ == "__main__":
    unittest.main()
