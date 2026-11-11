"""Trade candidates over every source and the Grok work queue (10.11., ui/kandidati.py; MCP get_trade_candidates,
get_grok_tasks), offline: every source is an in-memory stand-in, no network.

Covers: one row per token across sources; confluence (a caller crew within 10 min counts once, an exit-liquidity crew
not at all); the run-up penalty and the 4x line; a rug RISK rating never tradeable without Grok, a confirmed collapse
never tradeable even with Grok; the scanner's BOXCAT inconsistency (rug filter VISOK RIZIK while the pass said "rug
provjera prolazi"); the measured Grok override (fresh evidence only, half size, tight exit plan, the warning, the
newest piece of evidence wins, execute_trade applies the same rule); the task queue (a task disappears once Grok
answered it); Grok's X rows first (derived momentum, no paid lookup); the shadow log of the combined sources
(kandidati, grok_override) in scan.db, get_source_stats and the daily report.

    python3 -m unittest tests.test_kandidati_offline
"""
import calendar
import json
import os
import sqlite3
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scan import filters, market, shadow, store, xmom  # noqa: E402
from trade import settings  # noqa: E402
from ui import kandidati  # noqa: E402

NOW = calendar.timegm((2026, 11, 10, 23, 30, 0))
ALPH = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"


def b58(b):
    n, s = int.from_bytes(b, "big"), ""
    while n:
        n, r = divmod(n, 58)
        s = ALPH[r] + s
    return s


def mint(i):
    return b58(bytes([i + 40]) * 30 + b"\x07\x03")


A, B, C, D, E = (mint(i) for i in range(1, 6))


def live(mcap=300_000, liq=40_000, price=0.0003, ch_h1=5.0, ch_h24=40.0):
    return {"price": price, "mcap": mcap, "liq": liq, "vol_h1": 50_000, "vol_h24": 400_000, "txns_h1": 400,
            "buys_h1": 250, "txns_h24": 3000, "vol_m5": 4000, "txns_m5": 30, "ch_m5": 1.0, "ch_h1": ch_h1,
            "ch_h24": ch_h24}


class FakeSources(kandidati.Sources):
    """Every read of kandidati.build in memory."""

    def __init__(self):
        super().__init__()
        self.c, self.w, self.scan, self.gsig, self.member, self.glist = [], [], {}, [], {}, {}
        self.rng, self.tools, self.ins, self.mk, self.recs, self.crec = {}, [], [], {}, {}, {}
        self.xm, self.gx, self.ops, self.known, self.firsts, self.sfirst = {}, {}, {}, set(), {}, {}
        self.arch, self.tc, self.rug, self.col, self.conc = frozenset(), {}, {}, {}, {}
        self.lab, self.act = (set(), set()), []
        self.lim = {"grok_max_sol_per_trade": 0.1, "sl_default": 60.0}

    def callers(self, now):
        return self.c

    def wallet_buys(self, now):
        return self.w

    def scan_rows(self, now):
        return self.scan

    def scan_first(self, tokens):
        return self.sfirst

    def group_signals(self, now, since=None):
        return [g for g in self.gsig if g[0] >= (since if since is not None else now - kandidati.WINDOW_S)]

    def groups(self):
        return self.member, self.glist

    def group_activity(self, now):
        return self.act

    def ranges(self, now):
        return self.rng

    def tool_rows(self, now):
        return self.tools

    def insider_rows(self, now):
        return self.ins

    def live(self, tokens):
        return {t: self.mk[t] for t in tokens if t in self.mk}

    def x_latest(self, tokens, now):
        return {t: self.xm[t] for t in tokens if t in self.xm}

    def grok_rows(self, tokens, now):
        return {t: [r for r in self.gx.get(t, []) if r["ts_observed"] >= now - kandidati.GROK_FRESH_S] for t in tokens
                if t in self.gx}

    def opinions(self, tokens, now, since_s=kandidati.GROK_FRESH_S):
        return {t: [o for o in self.ops.get(t, []) if o["ts"] >= now - since_s] for t in tokens if t in self.ops}

    def labels(self):
        return self.lab

    def limits(self):
        return self.lim

    def known_handles(self):
        return self.known

    def first_calls(self, tokens, now):
        return self.firsts

    def caller_records(self, handles, now):
        return {h: self.crec[h] for h in handles if h in self.crec}

    def records(self, now):
        return self.recs

    def rug_tables(self):
        return self.tc, self.rug

    def archived(self):
        return self.arch

    def collapse(self, token, mcap, liq):
        return self.col.get(token)

    def concentration(self, token):
        return self.conc.get(token, (None, "nepoznato"))

    def tpsl(self, handles):
        return None


def by_token(rows):
    return {r["token"]: r for r in rows}


def scan_row(tok, passed=1, why=None, sources=("scan",), mcap=300_000, stage="migrated"):
    return {"token": tok, "symbol": "SC", "passed": passed, "why": why, "stage": stage, "tradeable": 1,
            "reasons": ["migriran"], "price": 0.0003, "mcap": mcap, "liq": 40_000, "vol_h1": 50_000, "ch_h1": 5.0,
            "ch_h24": 40.0, "first_pass_ts": NOW - 900, "checked_ts": NOW - 120, "sources": list(sources),
            "beta_score": None}


class Build(unittest.TestCase):
    def setUp(self):
        self.S = FakeSources()

    def build(self):
        rows, meta = kandidati.build(NOW, self.S)
        return by_token(rows), rows, meta

    def test_one_row_per_token_across_sources(self):
        S = self.S
        S.c = [(A, [("ansem", "x", NOW - 600), ("tg:gems", "tg", NOW - 500), ("w:" + "W1", "chain", NOW - 400)],
                NOW - 600, NOW - 400, "AAA", live())]
        S.w = [("W1", A, NOW - 400, "S"), ("W2", A, NOW - 300, "prati"), ("W3", B, NOW - 200, "A")]
        S.scan = {A: scan_row(A), B: scan_row(B)}
        S.gsig = [(NOW - 700, "hidden_group", "w1", A, "x1,x2,x3", 280_000)]
        S.rng = {A: {"symbol": "AAA", "score": 0.8, "zones": {"mc": {"range_high_low": 400_000, "range_high_top": 450_000,
                                                                      "range_low_low": 250_000}}}}
        S.mk = {B: live(mcap=200_000)}
        got, rows, _m = self.build()
        self.assertEqual(sorted(got), sorted([A, B]))                        # one row per token
        self.assertEqual(len(rows), 2)
        self.assertEqual(got[A]["source_kinds"], ["caller", "hidden_group", "range", "scan", "wallet"])
        self.assertEqual(got[A]["sources"]["wallet"]["n_wallets"], 2)           # the followed wallet is the wallet source
        self.assertEqual(got[A]["sources"]["caller"]["n_callers"], 2)           # not counted again among the callers
        self.assertEqual(got[B]["source_kinds"], ["scan", "wallet"])
        self.assertTrue(got[A]["tradeable"], got[A]["why_not"])
        self.assertEqual(rows[0]["token"], A)                                    # more confluence ranks higher
        self.assertIn("take_profits", got[A]["exit_plan"])
        self.assertEqual(got[A]["exit_plan"]["stop"], {"at_mc_usd": round(250_000 * 0.85)})   # the range's own zones

    def test_confluence_counts_a_crew_once(self):
        S = self.S
        S.member = {"a1": "crew1", "a2": "crew1", "x1": "bad1", "x2": "bad1"}
        S.glist = {"crew1": ("caller", "quality", ["a1", "a2"], {}), "bad1": ("caller", "exit_liquidity", ["x1", "x2"], {})}
        S.c = [(A, [("a1", "x", NOW - 900), ("a2", "x", NOW - 700), ("solo", "x", NOW - 600)], NOW - 900, NOW - 600,
                "AAA", live()),
               (B, [("a1", "x", NOW - 3000), ("a2", "x", NOW - 600)], NOW - 3000, NOW - 600, "BBB", live()),   # 40 min apart
               (C, [("x1", "x", NOW - 900), ("x2", "x", NOW - 800)], NOW - 900, NOW - 800, "CCC", live())]
        got, _r, _m = self.build()
        self.assertEqual(got[A]["confluence"], 2)                               # crew (2 calls) = 1, solo = 1
        self.assertEqual(got[A]["sources"]["caller"]["crews"][0]["handles"], ["a1", "a2"])
        self.assertEqual(got[B]["confluence"], 2)                               # outside 10 min: two signals
        self.assertEqual(got[C]["confluence"], 0)                               # an exit-liquidity crew counts nothing

    def test_runup_penalty_and_the_late_line(self):
        S = self.S
        S.c = [(t, [("ansem", "x", NOW - 600)], NOW - 600, NOW - 600, "T", live(mcap=mc, ch_h24=10.0))
               for t, mc in ((A, 100_000), (B, 300_000), (C, 500_000))]
        S.firsts = {A: (NOW - 600, 100_000), B: (NOW - 600, 100_000), C: (NOW - 600, 100_000)}
        got, rows, _m = self.build()
        self.assertEqual(got[A]["runup"]["x"], 1.0)
        self.assertEqual(got[B]["runup"]["x"], 3.0)
        self.assertGreater(got[B]["runup"]["chase"], 0.7)
        self.assertLess(got[B]["score"], got[A]["score"])                       # chasing costs score
        self.assertTrue(got[B]["tradeable"])
        self.assertFalse(got[C]["tradeable"])                                   # 5x since the first signal: too late
        self.assertTrue(any("kasno" in w for w in got[C]["why_not"]))
        self.assertEqual([r["token"] for r in rows], [A, B, C])
        # a 39x 24 h pump with no known first market cap is penalised too
        S.c, S.firsts = [(D, [("ansem", "x", NOW - 60)], NOW - 60, NOW - 60, "D", live(ch_h1=2.0, ch_h24=3800.0))], {}
        got, _r, _m = self.build()
        self.assertEqual(got[D]["runup"]["chase"], 1.0)

    def test_a_token_that_does_not_trade_now_is_not_tradeable(self):
        S = self.S
        dead = dict(live(), txns_h1=0, vol_h1=0.0)
        S.tools = [{"token": A, "src": "prijedlog", "ts0": NOW - 600, "mcap0": 300_000}]
        S.c = [(B, [("ansem", "x", NOW - 600)], NOW - 600, NOW - 600, "B", live(ch_h1=-35.0))]
        S.mk = {A: dead}
        got, _r, _m = self.build()
        self.assertFalse(got[A]["tradeable"])
        self.assertTrue(got[A]["why_not"][0].startswith("ne trguje se sada"))
        self.assertFalse(got[B]["tradeable"])
        self.assertIn("pada", got[B]["why_not"][0])

    def test_under_30k_is_measured_never_tradeable_and_under_10k_dropped(self):
        S = self.S
        S.scan = {A: scan_row(A, mcap=20_000), B: scan_row(B, mcap=8_000)}
        S.mk = {A: live(mcap=20_000, liq=8_000), B: live(mcap=8_000, liq=4_000)}
        got, _r, _m = self.build()
        self.assertNotIn(B, got)
        self.assertFalse(got[A]["tradeable"])
        self.assertTrue(got[A]["under_30k"])
        self.assertIsNone(got[A]["suggested_size_sol"])

    def test_rug_high_risk_never_tradeable_without_grok_and_a_collapse_never(self):
        S = self.S
        S.c = [(t, [("ansem", "x", NOW - 600)], NOW - 600, NOW - 600, "T", live()) for t in (A, B, C)]
        S.rug = {A: {"verdict": "VISOK RIZIK", "score": 41, "data": {"flags": ["snajperi kupili 25%"], "hard_fails": []}},
                 C: {"verdict": "ODBAČEN", "score": None, "data": {"hard_fails": ["mint authority nije ugašena (ab12…)"]}}}
        S.conc = {B: ("koncentriran supply: top 10 holdera drži 72% (granica 60%)", "top10 72%")}
        got, _r, _m = self.build()
        for t in (A, B):
            self.assertEqual(got[t]["rug"]["level"], "risk")
            self.assertFalse(got[t]["tradeable"])
            self.assertTrue(got[t]["why_not"][-1].startswith("rug ocjena"))
        self.assertIn("visok rizik", got[A]["rug"]["risk"][0])
        self.assertEqual(got[C]["rug"]["level"], "hard")                       # mint authority: a mechanic, not a rating
        # Grok's fresh evidence on all three, a collapse on a fourth: only the ratings are lifted
        S.c.append((D, [("ansem", "x", NOW - 600)], NOW - 600, NOW - 600, "D", live()))
        S.col = {D: {"text": "MC 85 % ispod vrha"}}
        S.known = {"ansem"}
        for t in (A, B, C, D):
            S.gx[t] = [{"ts_observed": NOW - 300, "ts_asof": NOW - 300, "source": "mcp:k",
                        "features": {"known_callers": ["ansem"], "posts_15m": 9}}]
        got, _r, _m = self.build()
        self.assertTrue(got[A]["tradeable"] and got[B]["tradeable"])
        self.assertFalse(got[C]["tradeable"])
        self.assertFalse(got[D]["tradeable"])
        self.assertTrue(any("rugan" in w for w in got[D]["why_not"]))
        self.assertIsNone(got[D]["grok_override"])

    def test_grok_override_is_measured_half_size_tight_exit_and_warned(self):
        S = self.S
        S.c = [(A, [("ansem", "x", NOW - 600)], NOW - 600, NOW - 600, "BOXCAT", live()),
               (B, [("ansem", "x", NOW - 600)], NOW - 600, NOW - 600, "OK", live())]
        S.rug = {A: {"verdict": "VISOK RIZIK", "score": 38, "data": {"flags": ["dev je prodao 80%"]}}}
        S.known = {"ansem"}
        stale = {"ts_observed": NOW - 1900, "ts_asof": NOW - 1900, "source": "mcp:k",
                 "features": {"known_callers": ["ansem"]}}
        S.gx[A] = [stale]
        got, _r, _m = self.build()
        self.assertFalse(got[A]["tradeable"])                                   # older than 30 min: no override
        S.gx[A] = [stale, {"ts_observed": NOW - 120, "ts_asof": NOW - 120, "source": "mcp:k",
                           "features": {"known_callers": ["@Ansem"], "large_accounts": [{"handle": "big", "followers": 2e5}],
                                        "unique_authors_15m": 6, "unique_authors_60m": 8}}]
        got, rows, _m = self.build()
        r = got[A]
        self.assertTrue(r["tradeable"])
        self.assertEqual(r["flags"], ["grok_override"])
        self.assertIn("RUG RIZIK", r["warning"])
        self.assertIn("visok rizik", r["grok_override"]["rug_warning"])
        self.assertIn("@ansem", r["grok_override"]["reason"])
        self.assertEqual(r["grok_override"]["strength"], "jak")
        self.assertEqual(r["suggested_size_sol"], 0.05)                         # half of grok_max_sol_per_trade
        self.assertEqual(got[B]["suggested_size_sol"], 0.1)
        self.assertEqual(r["exit_plan"]["stop"], {"at_pct": -12})               # tight
        self.assertEqual(r["exit_plan"], kandidati.EXIT_TIGHT)
        self.assertEqual(r["score_parts"]["rug"], -kandidati.RUG_PEN["risk"])  # the risk still costs score
        self.assertLess(r["score"], got[B]["score"])
        # an opinion against it, newer than the X row, takes the override back
        S.ops[A] = [{"ts": NOW - 30, "verdict": "preskoči", "confidence": 0.8, "interpretation": "dev prodaje"}]
        got, _r, _m = self.build()
        self.assertFalse(got[A]["tradeable"])
        # a kupi opinion alone is evidence too
        S.gx[A], S.ops[A] = [], [{"ts": NOW - 60, "verdict": "kupi", "confidence": 0.6, "interpretation": "3 KOL-a"}]
        got, _r, _m = self.build()
        self.assertTrue(got[A]["tradeable"])
        self.assertEqual(got[A]["grok_override"]["strength"], "slab")

    def test_grok_x_rows_first_in_the_candidate_view(self):
        S = self.S
        S.c = [(A, [("ansem", "x", NOW - 600)], NOW - 600, NOW - 600, "AAA", live())]
        S.xm = {A: {"source": "grok", "ts": NOW - 900, "x_momentum_score": 1.5, "x_early": True}}
        got, _r, _m = self.build()
        self.assertEqual(got[A]["x"]["source"], "grok")
        self.assertEqual(got[A]["score_parts"]["x"], 0.4)
        S.xm = {A: {"source": "scan", "ts": NOW - 2 * 3600, "x_momentum_score": 1.5}}   # the scanner's, 2 h old: stale
        got, _r, _m = self.build()
        self.assertFalse(got[A]["x"]["fresh"])
        self.assertEqual(got[A]["score_parts"]["x"], 0.0)

    def test_source_records_and_ev_part(self):
        S = self.S
        S.c = [(A, [("good", "x", NOW - 600)], NOW - 600, NOW - 600, "A", live()),
               (B, [("bad", "x", NOW - 600)], NOW - 600, NOW - 600, "B", live())]
        S.crec = {"good": {"ev_n": 40, "ev_mean": 0.12, "ev_lower": 0.03, "verdict": "drzi_se"},
                  "bad": {"ev_n": 40, "ev_mean": -0.2, "ev_lower": -0.3, "verdict": "ne_isplati_se"}}
        S.recs = {"caller": {"n": 100, "hit1h": 0.3, "hit4h": 0.4, "sl_first": 0.4, "ev": -0.02}}
        got, rows, meta = self.build()
        self.assertEqual(rows[0]["token"], A)
        self.assertGreater(got[A]["score_parts"]["ev"], 0)
        self.assertLess(got[B]["score_parts"]["ev"], 0)
        self.assertEqual(got[A]["sources"]["caller"]["record"]["n"], 100)       # the source's shadow record rides along
        self.assertEqual(got[A]["sources"]["caller"]["callers"][0]["record"]["verdict"], "drzi_se")
        self.assertEqual(kandidati._ev_part({"n": 20, "ev": 0.5}), kandidati.EV_CAP)   # shrunk and capped

    def test_a_broken_source_is_named_never_hides_the_others(self):
        S = self.S
        S.c = [(A, [("ansem", "x", NOW - 600)], NOW - 600, NOW - 600, "A", live())]
        S.ranges = lambda now: 1 / 0
        got, _r, meta = self.build()
        self.assertIn(A, got)
        self.assertEqual(meta["sources_failed"], ["range: ZeroDivisionError"])


class Tasks(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.trade = os.path.join(self.d, "trade.db")
        self.env = mock.patch.dict(os.environ, {"XFEAT_DB": os.path.join(self.d, "xfeat.db")})
        self.env.start()
        from trade import executor
        tcon = executor.connect(self.trade)
        settings.put(tcon, "flag:x_features_ingest", {"mode": "shadow", "since": NOW, "who": "t"}, "t")
        from ui import assistnotes
        assistnotes.ensure(tcon)
        tcon.close()
        settings._FLAG_CACHE.clear()
        S = self.S = FakeSources()
        S.trade_db = self.trade
        S.grok_rows = lambda toks, now: kandidati.Sources.grok_rows(S, toks, now)      # the real reads
        S.opinions = lambda toks, now, since_s=kandidati.GROK_FRESH_S: kandidati.Sources.opinions(S, toks, now, since_s)
        S.labels = lambda: kandidati.Sources.labels(S)
        S.c = [(A, [("ansem", "x", NOW - 600)], NOW - 600, NOW - 600, "AAA", live()),
               (B, [("ansem", "x", NOW - 600)], NOW - 600, NOW - 600, "BOX", live())]
        S.rug = {B: {"verdict": "VISOK RIZIK", "score": 40, "data": {}}}
        S.crec = {"ansem": {"ev_n": 30, "ev_mean": 0.08, "verdict": "drzi_se"}}
        S.xm = {A: {"source": "scan", "ts": NOW - 300, "x_momentum_score": -0.8}}
        S.gsig = [(NOW - 5000, "hidden_group", "w1", C, "x1,x2,x3", 90_000)]
        S.glist = {"w1": ("wallet", "quality", ["x1", "x2", "x3", "x4"], {})}

    def tearDown(self):
        self.env.stop()
        settings._FLAG_CACHE.clear()

    def tasks(self):
        with mock.patch("time.time", return_value=NOW):
            return kandidati.tasks(20, NOW, self.S)

    def test_queue_and_it_empties_as_grok_answers(self):
        t = self.tasks()
        self.assertTrue(t["how_to_work"])
        self.assertEqual(t["x_features_intake"], "on")                   # the owner has the X intake on here
        ids = [x["id"] for x in t["tasks"]]
        self.assertEqual(ids[0], f"x:{B}")                     # blocked only by the rug risk rating: Grok decides it
        self.assertIn(f"x:{A}", ids)
        self.assertIn(f"op:{A}", ids)                          # a good caller, X momentum falling
        self.assertIn("grp:w1", ids)
        x = next(x for x in t["tasks"] if x["id"] == f"x:{B}")
        self.assertEqual(x["answer_with"]["tool"], "submit_x_features")
        # Grok answers: an X row for B, an opinion on A, a label for w1
        from ui import assistnotes, xfeat
        tcon = settings.connect(self.trade)
        try:
            with mock.patch("time.time", return_value=NOW):
                xfeat.submit(B, "token", {"known_callers": ["ansem"], "posts_15m": 7}, NOW - 60, kid="k", now=NOW,
                             tcon=tcon)
                assistnotes.submit_signal_opinion(tcon, "k", A, "preskoči", 0.7, "X pada, calleri kasne")
                assistnotes.submit_suggestion(tcon, "k", "Group label", "plaćena grupa",
                                              proposed_change={"group_label": {"group_id": "w1", "label": "alpha"}})
        finally:
            tcon.close()
        ids = [x["id"] for x in self.tasks()["tasks"]]
        self.assertNotIn(f"x:{B}", ids)
        self.assertNotIn(f"op:{A}", ids)
        self.assertNotIn("grp:w1", ids)
        self.assertIn(f"x:{A}", ids)                           # A still has no X row of Grok's
        # and B is now tradeable through the override (the known caller is in kol.db's scored list)
        self.S.known = {"ansem"}
        with mock.patch("time.time", return_value=NOW):
            got = by_token(kandidati.build(NOW, self.S)[0])
        self.assertTrue(got[B]["tradeable"])
        self.assertEqual(got[B]["flags"], ["grok_override"])

    def test_mcp_tools_are_listed_read_only_and_answer(self):
        from ui import mcpapi
        names = {t["name"]: t for t in mcpapi.TOOLS}
        for n in ("get_trade_candidates", "get_grok_tasks"):
            self.assertTrue(names[n]["annotations"]["readOnlyHint"], n)
        with mock.patch.object(kandidati, "_cached", lambda now=None, src=None: kandidati.build(NOW, self.S)), \
                mock.patch.object(kandidati, "Sources", lambda *a, **k: self.S):
            res = json.loads(mcpapi.rpc(json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {
                "name": "get_trade_candidates", "arguments": {"min_sources": 1, "limit": 5}}}).encode())[1])["result"]
            self.assertFalse(res["isError"])
            sc = res["structuredContent"]
            self.assertEqual(sc["total"], 2)
            self.assertIn("log2(1+confluence)", sc["ranking"])
            res = json.loads(mcpapi.rpc(json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {
                "name": "get_grok_tasks", "arguments": {"limit": 2}}}).encode())[1])["result"]
            self.assertFalse(res["isError"])
            self.assertEqual(len(res["structuredContent"]["tasks"]), 2)


class GrokXFirst(unittest.TestCase):
    def test_task_keys_make_a_grok_row_and_save_the_paid_lookup(self):
        g = xmom._grok(NOW, json.dumps({"unique_authors_15m": 6, "unique_authors_60m": 9, "posts_60m": 20}))
        self.assertEqual(g["source"], "grok")
        self.assertAlmostEqual(g["x_momentum_score"], round(__import__("math").log2(7 / 2), 3))
        self.assertTrue(g["x_early"])
        self.assertEqual(g["posts60"], 20)
        self.assertFalse(xmom._grok(NOW, json.dumps({"unique_authors_15m": 6, "unique_authors_60m": 9,
                                                     "known_callers": ["ansem"]}))["x_early"])
        self.assertIsNotNone(xmom._grok(NOW, json.dumps({"known_callers": ["a"]})))     # names alone count
        self.assertIsNone(xmom._grok(NOW, json.dumps({"note": "x"})))
        with tempfile.TemporaryDirectory() as d, mock.patch.dict(os.environ, {"XFEAT_DB": os.path.join(d, "x.db"),
                                                                              "SCAN_DB": os.path.join(d, "s.db")}):
            from ui import xfeat
            xc = xfeat.connect()
            xc.execute("INSERT INTO x_features (subject_kind, subject, ts_observed, ts_asof, features, source, backfill, "
                       "created) VALUES ('token', ?, ?, ?, ?, 'mcp:k', 0, ?)",
                       (A, NOW, NOW - 60, json.dumps({"posts_15m": 4, "known_callers": ["ansem"]}), NOW))
            xc.commit()
            xc.close()
            calls = []
            scon, kcon = store.connect(), sqlite3.connect(os.path.join(d, "k.db"))
            try:
                r = xmom.measure(A, "AAA", NOW, scon, kcon, store.config(), get=lambda *a: calls.append(a))
            finally:
                scon.close()
                kcon.close()
            self.assertEqual((r["source"], r["measured"]), ("grok", False))
            self.assertEqual(calls, [])                                          # no paid X search


class Boxcat(unittest.TestCase):
    """10.11. Grok: the scanner said "rug provjera prolazi" for BOXCAT while the rug filter said VISOK RIZIK."""

    def setUp(self):
        from league import copy as lcopy
        self.lcopy = lcopy
        self.rug = {A: {"verdict": "VISOK RIZIK", "score": 35, "data": {"flags": ["snajperi 22%"], "hard_fails": []}},
                    B: {"verdict": "OPREZ", "score": 60, "data": {"flags": ["klaster 18%"]}},
                    C: {"verdict": "ODBAČEN", "score": None, "data": {"hard_fails": ["likvidnost samo $3,000"]}},
                    D: {"verdict": "ODBAČEN", "score": None, "data": {"hard_fails": ["serijski kreator: 40 tokena, živih 1"]}}}
        lcopy._CONC_CACHE = {"tc": {}, "rug": self.rug}
        self.p = mock.patch.object(lcopy, "_concentration", lambda t: (None, "top10 20%"))
        self.p.start()

    def tearDown(self):
        self.p.stop()
        self.lcopy._CONC_CACHE = None

    def test_rug_filter_verdict_fails_the_scanner(self):
        cfg = store.config()
        ok = {"top10_pct": 20, "holders": 300, "holders_capped": 0, "mint_auth": None, "freeze_auth": None}
        why, _s = filters.rug_check(A, ok, cfg)
        self.assertTrue(why.startswith("rug filter: visok rizik"))
        self.assertIn("snajperi", why)
        self.assertTrue(filters.is_rug_risk(why))
        self.assertIsNone(filters.rug_check(B, ok, cfg)[0])                        # oprez passes
        self.assertIsNone(filters.rug_check(C, ok, cfg)[0])                        # a curve-time liquidity fail: gates
        self.assertIn("serijski kreator", filters.rug_check(D, ok, cfg)[0])
        self.assertIsNone(filters.rug_check(E, ok, cfg)[0])                        # no report

    def test_the_pass_label_is_truthful(self):
        class Ctx:
            archived, dead, sol_usd, facts_why = frozenset(), frozenset(), 150.0, None

            def trades(self, tok):
                return []

            def facts(self, tok, tradeable=True):
                return {"top10_pct": 20, "holders": 300, "holders_capped": 0, "mint_auth": None, "freeze_auth": None,
                        "src": "helius"}
        cfg = store.config()
        m = {"token": A, "symbol": "BOXCAT", "price": 0.0003, "mcap": 300_000, "liq": 40_000, "vol_h1": 60_000,
             "txns_h1": 400, "buys_h1": 250, "buyers_h1": 180, "curve": False, "dex": "pumpswap", "src": "dexscreener"}
        with mock.patch.object(self.lcopy, "_rugged", lambda *a: None), \
                mock.patch("kol.converge.not_a_memecoin", lambda *a, **k: None):
            bad = market.check(dict(m), cfg, Ctx(), False)
            good = market.check(dict(m, token=B), cfg, Ctx(), False)
        self.assertTrue(bad["why"].startswith("rug filter: visok rizik"))          # BOXCAT no longer passes
        self.assertFalse(any("rug provjera prolazi" in x for x in bad["reasons"]))
        self.assertIsNone(good["why"])
        self.assertIn("rug filter: oprez", good["reasons"][-1])                   # what was checked, said


class ShadowLog(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.env = mock.patch.dict(os.environ, {"SCAN_DB": os.path.join(self.d, "scan.db")})
        self.env.start()

    def tearDown(self):
        self.env.stop()

    def rows(self):
        S = FakeSources()
        S.c = [(t, [("ansem", "x", NOW - 600)], NOW - 600, NOW - 600, "T", live(mcap=300_000 + i))
               for i, t in enumerate((A, B, C, D))]
        S.rug = {D: {"verdict": "VISOK RIZIK", "score": 40, "data": {}}}
        S.gx[D] = [{"ts_observed": NOW - 60, "ts_asof": NOW - 60, "source": "mcp:k", "features": {"x_early": True}}]
        S.scan = {E: scan_row(E, passed=0, why="rug filter: visok rizik (snajperi)", sources=())}   # never tradeable
        return kandidati.build(NOW, S)[0]

    def test_combined_sources_in_scan_db_stats_and_the_report(self):
        rows = self.rows()
        got = by_token(rows)
        self.assertTrue(got[D]["grok_override"])
        self.assertFalse(got[E]["tradeable"])
        self.assertIn("scan", got[E]["source_kinds"])                              # failed only on the rug rating
        con = store.connect()
        try:
            n = kandidati.log_shadow(con, rows, NOW, top_n=2)
            self.assertEqual(n, {"kandidati": 2, "grok_override": 1})
            self.assertEqual(kandidati.log_shadow(con, rows, NOW + 300, top_n=2),
                             {"kandidati": 0, "grok_override": 0})               # the first entry per token wins
            con.commit()
            srcs = sorted(con.execute("SELECT source, token FROM shadow").fetchall())
            self.assertEqual([s for s, _t in srcs], ["grok_override", "kandidati", "kandidati"])
            self.assertEqual(con.execute("SELECT token FROM shadow WHERE source='grok_override'").fetchone()[0], D)
            # finished outcomes -> get_source_stats / the daily report
            cfg = store.config()
            for i in range(12):
                tok = mint(60 + i)
                shadow.enter(con, tok, "kandidati", "migrated", True, NOW - 5 * 3600, 1.0, 100_000, "K")
                shadow.enter(con, tok, "scan", "migrated", True, NOW - 5 * 3600, 1.0, 100_000, "K")
            con.execute("UPDATE shadow SET done=1, result=0.18, t_tp=found_ts+600, hi1h=1.3, hi4h=1.3, n_obs=10 "
                        "WHERE source='kandidati' AND found_ts < ?", (NOW - 3600,))
            con.execute("UPDATE shadow SET done=1, result=-0.05, hi1h=1.0, hi4h=1.0, n_obs=10 WHERE source='scan'")
            con.commit()
            d = shadow.report_data(NOW, con=con, cfg=cfg)
        finally:
            con.close()
        g = {r["source"]: r for r in d["gate_window"]}
        self.assertEqual((g["kandidati"]["n"], g["kandidati"]["ev"]), (12, 0.18))
        self.assertEqual(d["combined"]["kandidati"]["ev"], 0.18)
        self.assertEqual(d["combined"]["best_single"], {"source": "scan", "n": 12, "ev": -0.05})
        self.assertIn("grok_override", d["paper_gate"])
        from report import render
        html = render.skener_body(d)
        self.assertIn("Kandidati (spoj izvora", html)
        self.assertIn("najbolji pojedinačni izvor", html)

    def test_the_scanner_pass_logs_the_combined_list_on_its_own_clock(self):
        rows = self.rows()

        class Net:
            def kandidati(self, now):
                return rows
        cfg = dict(store.config(), kandidati_top_n=3)
        con = store.connect()
        try:
            self.assertEqual(market.log_kandidati(con, Net(), cfg, NOW), {"kandidati": 3, "grok_override": 1})
            self.assertEqual(market.log_kandidati(con, Net(), cfg, NOW + 60), {})          # inside 5 min: no build
            self.assertEqual(market.log_kandidati(con, object(), cfg, NOW + 900), {})      # a net without it: skipped

            class Broken:
                def kandidati(self, now):
                    raise RuntimeError("x")
            self.assertEqual(market.log_kandidati(con, Broken(), cfg, NOW + 900), {})      # never breaks the pass
        finally:
            con.close()


class Execute(unittest.TestCase):
    """execute_trade (grok_autotrade on) applies the same rule as the candidate view."""

    def setUp(self):
        from tests.test_grok_autotrade_offline import Grok
        self.t = Grok("test_off_by_default_and_grok_cannot_switch_it_on")
        self.addCleanup(self.t.doCleanups)   # the patches Grok.setUp registered (copy.market ...), after tearDown
        self.t.setUp()
        self.addCleanup(self.t.tearDown)
        from league import copy as lcopy
        self.lcopy = lcopy

    def test_rug_risk_needs_fresh_grok_evidence_and_half_size(self):
        from tests.test_grok_autotrade_offline import MINT
        from ui import assistnotes
        t = self.t
        t.post("/pravi-trade/grokon", {})
        risk = ("koncentriran supply: top 10 holdera drži 70% (granica 60%)", "top10 70%")
        with mock.patch.object(self.lcopy, "_concentration", lambda tok: risk), \
                mock.patch("rugfilter.archive.blocked", lambda *a, **k: frozenset()):
            code, out = t.ask(MINT, 0.05)
            self.assertEqual(out["status"], "rejected")
            self.assertIn("koncentriran supply", out["reason"])
            self.assertIn("half size", out["reason"])
            assistnotes.submit_signal_opinion(t.con, "k", MINT, "kupi", 0.8, "dva velika KOL-a upravo zovu")
            code, out = t.ask(MINT, 0.1)
            self.assertEqual((code, out["status"]), (400, "rejected"))
            self.assertIn("at most 0.05", out["reason"])
            code, out = t.ask(MINT, 0.05)
            self.assertEqual(out["status"], "executed", out)
        from ui import grokauto
        log = grokauto.log_rows(t.con, 5)
        self.assertEqual(log[0]["override"]["rug_risk"], risk[0])
        self.assertTrue(log[0]["reason"].startswith("[Grok nadjačao rug ocjenu"))
        # a collapse is never overridden
        with mock.patch.object(self.lcopy, "_rugged", lambda *a: {"text": "pao 90 %"}):
            self.assertIn("rugan", t.ask(MINT, 0.05)[1]["reason"])


if __name__ == "__main__":
    unittest.main()
