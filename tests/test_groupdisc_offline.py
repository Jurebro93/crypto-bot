"""10.11. (Jure, flag group_discovery, kol/groupdisc.py): caller crews and hidden wallet lists, shadow only.

The lift of a caller pair against chance, the groups and their grades, one group within 10 min = one signal and the
negative weight of an exit-liquidity group (shadow lines only), wallet trades attributed to the signing owner and
never to a relayer that pays the fee for many traders (10.11. Hope research), the removal of bots, dev-funded buys
and one-owner bundles, the hidden-list signal (also in get_market_signals), traces without a call, the credit cap of
a pass, the paper gate (enforced by trade/settings.set_flag, never automatic), and that the flag off does nothing.
No network: Helius is a fake, DexScreener is patched."""
import json
import os
import sqlite3
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from kol import groupdisc as gd, store as kstore  # noqa: E402
from league import store as lstore  # noqa: E402
from live import store as livestore  # noqa: E402
from trade import executor, settings  # noqa: E402
from wallets import store as wstore  # noqa: E402

NOW = 1_800_000_000
C = gd.config()
POOL = "PooL" + "1" * 40


def W(name):
    return (name + "x" * 44)[:44]


A, B, Cw, D, E, DEV, R, F, BOT = (W(n) for n in ("Aaa", "Bbb", "Ccc", "Ddd", "Eee", "Dev", "Relay", "Fund", "Bot"))
XS = [W(f"Xb{i}") for i in range(4)]
US = [W(f"Usr{i}") for i in range(6)]
MINTS = [("Mint" + str(k) + "z" * 44)[:44] for k in range(1, 4)]


def tx(sig, slot, ts, mint, trades, signers=None, payer=None):
    """A getTransactionsForAddress-style tx. trades: [(owner, token delta (UI), SOL delta)]; the pool takes the
    other side and never signs."""
    signers = list(signers or [o for o, *_ in trades])
    payer = payer or signers[0]
    keys = [payer] + [s for s in signers if s != payer]
    keys += [o for o, *_ in trades if o not in keys] + [POOL]
    pre_b = [10_000_000_000] * len(keys)
    post_b = list(pre_b)
    pre_t, post_t = [], []
    for o, d, sol in trades:
        post_b[keys.index(o)] += int(sol * 1e9)
        pre_t.append({"owner": o, "mint": mint, "uiTokenAmount": {"amount": str(0 if d > 0 else int(-d * 1e6)), "decimals": 6}})
        post_t.append({"owner": o, "mint": mint, "uiTokenAmount": {"amount": str(int(d * 1e6) if d > 0 else 0), "decimals": 6}})
    moved = int(sum(d for _, d, _ in trades) * 1e6)
    pre_t.append({"owner": POOL, "mint": mint, "uiTokenAmount": {"amount": str(10 ** 15), "decimals": 6}})
    post_t.append({"owner": POOL, "mint": mint, "uiTokenAmount": {"amount": str(10 ** 15 - moved), "decimals": 6}})
    return {"slot": slot, "blockTime": ts,
            "meta": {"err": None, "preBalances": pre_b, "postBalances": post_b, "preTokenBalances": pre_t,
                     "postTokenBalances": post_t},
            "transaction": {"signatures": [sig], "message": {
                "accountKeys": [{"pubkey": k, "signer": k in signers or k == payer} for k in keys]}}}


BUY = (1_000_000, -0.01)   # 1M tokens for 0.01 SOL: ~$1.5k market cap at $150 (pump supply 1e9)


def mint_txs(k, mint):
    """The first minutes of one token: the dev's create+buy, the list A-D within 3 slots, E paid by the dev, two
    traders through relayer R in the list's slots, a one-funder bundle X0-X3 in one slot, and a bot."""
    s, t = 1000 * k, NOW - 2 * 86400 + k * 3600
    out = [tx(f"c{k}", s, t, mint, [(DEV, *BUY)])]
    for i, w in enumerate((A, B, Cw, D)):
        out.append(tx(f"g{k}{i}", s + 10 + i, t + 5, mint, [(w, *BUY)]))
    out.append(tx(f"e{k}", s + 10, t + 5, mint, [(E, *BUY)], signers=[DEV, E], payer=DEV))
    for j, u in enumerate((US[k - 1], US[k + 2])):
        out.append(tx(f"r{k}{j}", s + 11, t + 5, mint, [(u, *BUY)], signers=[R, u], payer=R))
    for i, x in enumerate(XS):
        out.append(tx(f"x{k}{i}", s + 50, t + 25, mint, [(x, *BUY)]))
    out.append(tx(f"b{k}", s + 12, t + 5, mint, [(BOT, *BUY)]))
    if k == 1:   # 60 more trades of the bot inside one minute
        out += [tx(f"bb{i}", s + 100 + i, t + 60, mint, [(BOT, 10, -0.000001)]) for i in range(60)]
    return out


class FakeHelius:
    """wallets/rpc.fetch stand-in: the token's txs, c["pages"] pages of 10 credits each."""

    def __init__(self, by_mint):
        self.by_mint, self.asked = by_mint, []

    def __call__(self, mint, max_pages=3, oldest_first=False, on_credits=None, **_kw):
        self.asked.append(mint)
        for _ in range(max_pages):
            on_credits(10)
        return list(self.by_mint.get(mint, [])), True


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = self.tmp.name
        self.p = {k: os.path.join(d, f"{k[:-3]}.db") for k in ("kol_db", "hype_db", "tg_db", "wallet_db", "rug_db",
                                                              "early_db", "minute_db", "league_db")}
        self._env = os.environ.get("EARLY_DB")
        os.environ["EARLY_DB"] = self.p["early_db"]
        self._db = settings.DB
        settings.DB = os.path.join(d, "trade.db")
        settings._FLAG_CACHE.clear()
        self.tc = executor.connect(settings.DB)
        self.kc = kstore.connect(self.p["kol_db"])
        lstore.connect(self.p["league_db"]).close()

    def tearDown(self):
        settings.DB = self._db
        settings._FLAG_CACHE.clear()
        if self._env is None:
            os.environ.pop("EARLY_DB", None)
        else:
            os.environ["EARLY_DB"] = self._env
        self.tc.close()
        self.kc.close()
        self.tmp.cleanup()

    def shadow(self, since=NOW - 8 * 86400):
        settings.set_flag(self.tc, gd.FLAG, "shadow", "Jure", now=since)
        settings._FLAG_CACHE.clear()

    def call(self, tid, tok, h, ts, **kw):
        cols = {"tweet_id": tid, "token": tok, "handle": h, "ts": ts, "kind": "call", **kw}
        self.kc.execute(f"INSERT INTO calls ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})", list(cols.values()))


class CallerGroups(Base):
    def test_lift_is_shared_tokens_against_chance(self):
        by_token = [[(0, "a"), (30, "b"), (7200, "c")] for _ in range(5)]          # a+b within 30 s, c 2 h later
        by_token += [[(0, "a")]] * 5 + [[(0, "b")]] * 5 + [[(0, "c")]] * 5 + [[(0, f"x{i}")] for i in range(60)]
        by_token += [[(0, "d"), (50, "e")], [(0, "d"), (40, "e")]]                   # only 2 shared tokens
        table, n_of, u, f = gd.lift_table(by_token, (120, 600))
        self.assertEqual(u, 82)
        self.assertEqual((n_of["a"], n_of["b"]), (10, 10))
        self.assertAlmostEqual(f[1], 7 / 17)                    # 15 + 2 same-token pairs, 5 + 2 within 10 min
        ab = table[("a", "b")]
        self.assertEqual(ab["n"], [5, 5])
        exp = 10 * 10 / 82 * 7 / 17
        self.assertAlmostEqual(ab["exp"][1], round(exp, 4), places=4)
        self.assertAlmostEqual(ab["lift"][1], round(5 / exp, 2))
        self.assertNotIn(("a", "c"), table)                     # 2 h apart: never "together"
        self.assertEqual(gd.links(table, 3, 5.0), [("a", "b")])   # d+e: lift high, but only 2 tokens
        self.assertEqual([sorted(g) for g in gd.components(gd.links(table, 3, 5.0))], [["a", "b"]])
        small, *_ = gd.lift_table(by_token, (120, 600), cand={"a", "c"})
        self.assertEqual(small, {})                             # b is not a candidate: no row for a+b

    def test_groups_from_kol_db_order_delay_and_grades(self):
        t0 = NOW - 5 * 86400
        for i in range(3):
            ts = t0 + i * 7200
            self.call(f"a{i}", f"TOKA{i}", "a", ts, r1h=0.5, r24h=0.2, mcap0=40000)
            self.call(f"b{i}", f"TOKA{i}", "b", ts + 40, r1h=0.3)
            self.call(f"z{i}", f"TOKA{i}", "zz", ts + 1200, r1h=-0.3)      # the public call 20 min later falls
            self.call(f"c{i}", f"TOKC{i}", "c", ts + 3600, r1h=0.2, mcap0=60000)
            self.call(f"d{i}", f"TOKC{i}", "d", ts + 3650, r1h=0.1)
            self.call(f"y{i}", f"TOKC{i}", "yy", ts + 5400, r1h=0.2)       # ... here it holds
        for i in range(60):
            self.call(f"f{i}", f"FILL{i}", f"solo{i}", t0 + i * 100)
        self.kc.commit()
        got = {tuple(sorted(m)): (gid, m, met) for gid, m, met in gd.build_caller_groups(self.kc, C, NOW)}
        self.assertEqual(sorted(got), [("a", "b"), ("c", "d")])
        _gid, members, met = got[("a", "b")]
        self.assertEqual(members, ["a", "b"])                   # a calls first
        self.assertEqual(met["first_counts"], {"a": 3})
        self.assertEqual((met["events"], met["mcap_first_med"], met["public_delay_min_med"]), (3, 40000, 20.0))
        self.assertEqual(met["grade"], "exit_liquidity")
        self.assertAlmostEqual(met["ev_1h"], 0.48)
        self.assertEqual(got[("c", "d")][2]["grade"], "quality")
        self.assertGreaterEqual(met["pairs"][0]["lift_10min"], 5)


class ShadowScoring(Base):
    def test_one_group_within_10_min_is_one_signal_and_exit_liquidity_weighs_minus_one(self):
        member_of = {"a": "g1", "b": "g1"}
        sig = gd.dedupe([(100, "a"), (400, "b"), (500, "x"), (520, "x")], member_of)
        self.assertEqual([(s["gid"], s["handles"]) for s in sig], [("g1", ["a", "b"]), (None, ["x"])])
        self.assertEqual(len(gd.dedupe([(100, "a"), (900, "b")], member_of)), 2)   # 13 min apart: two signals
        self.assertEqual(gd.weighted(sig, {"g1": "exit_liquidity"}), 0.0)
        self.assertEqual(gd.weighted(sig, {"g1": "quality"}), 2.0)

    def test_the_15_min_pass_logs_the_change_in_the_shadow_only(self):
        self.shadow()
        ec = gd.connect(self.p["early_db"])
        gd.save_groups(ec, "caller", [("cexit", ["a", "b"], {"grade": "exit_liquidity"})], NOW)
        ec.close()
        for tid, h, dt in (("1", "a", 600), ("2", "b", 500), ("3", "x", 400)):
            self.call(tid, "TOKS", h, NOW - dt)
        self.kc.commit()
        r = gd.incremental(now=NOW, sol_usd=150.0, log=lambda *a, **k: None, **self.p)
        self.assertEqual(r["shadow"], 1)
        lc = sqlite3.connect(self.p["league_db"])
        rows = lc.execute("SELECT flag, token, old_action, new_action FROM shadow_decisions").fetchall()
        lc.close()
        self.assertEqual(rows, [(gd.FLAG, "TOKS", "3 računa zove", "2 neovisnih signala, težina +0.0")])
        self.assertEqual(gd.incremental(now=NOW + 60, sol_usd=150.0, log=lambda *a, **k: None, **self.p)["shadow"], 0)
        act = gd.group_activity(now=NOW)
        self.assertEqual(sorted(a["who"] for a in act["activity"]), ["a", "b"])
        self.assertEqual(act["signals"], [])                     # an exit-liquidity group never makes a "first call"

    def test_first_call_of_a_quality_group_is_a_case_for_the_gate(self):
        self.shadow()
        ec = gd.connect(self.p["early_db"])
        gd.save_groups(ec, "caller", [("cq", ["c", "d"], {"grade": "quality"})], NOW)
        ec.close()
        self.call("1", "TOKQ", "c", NOW - 300, mcap0=45000)
        self.call("2", "TOKQ", "d", NOW - 250)
        self.call("3", "TOKQ2", "x", NOW - 900)                 # somebody else first: not the group's first call
        self.call("4", "TOKQ2", "c", NOW - 200)
        self.kc.commit()
        gd.incremental(now=NOW, sol_usd=150.0, log=lambda *a, **k: None, **self.p)
        sig = gd.group_activity(now=NOW)["signals"]
        self.assertEqual([(s["source"], s["token"], s["who"], s["mcap_usd"]) for s in sig],
                         [("caller_group_first", "TOKQ", "c", 45000)])


class WalletGroups(Base):
    def test_trade_goes_to_the_signing_owner_never_to_a_relayer(self):
        t = tx("s", 5, NOW, MINTS[0], [(US[0], *BUY)], signers=[R, US[0]], payer=R)
        trades, payer, signers = gd.owner_trades(t, MINTS[0])
        self.assertEqual(payer, R)
        self.assertEqual([(o, side, amt, sol) for o, side, amt, sol in trades], [(US[0], "buy", 1_000_000, 0.01)])
        self.assertNotIn(POOL, signers)
        self.assertEqual(gd.relayers([(R, u) for u in US] + [(DEV, E)], 5), {R})

    def test_bots_bundles_dev_funded_and_relayers_are_removed(self):
        wc = wstore.connect(self.p["wallet_db"])
        for x in XS:
            wc.execute("INSERT INTO wallet_sightings VALUES (?, 'T', 'rug', 'holder', ?, 0, ?)", (x, NOW, json.dumps({"funder": F})))
        wc.commit()
        wc.close()
        livestore.connect(self.p["hype_db"]).close()
        for k, m in enumerate(MINTS, 1):
            self.call(f"k{k}", m, "caller1", NOW - 2 * 86400 + k * 3600 + 3600, mcap0=50000)
        self.kc.commit()
        self.shadow()
        helius = FakeHelius({m: mint_txs(k, m) for k, m in enumerate(MINTS, 1)})
        d = gd.night(now=NOW, credits=3000, fetch=helius, sol_usd=150.0, force=True, log=lambda *a, **k: None, **self.p)
        self.assertEqual(sorted(helius.asked), sorted(MINTS))
        self.assertEqual((d["mints_read"], d["wallet_groups"], d["relayers"]), (3, 1, 1))
        ec = sqlite3.connect(self.p["early_db"])
        self.assertEqual(ec.execute("SELECT COUNT(*) FROM group_buys WHERE wallet = ?", (R,)).fetchone()[0], 0)
        self.assertEqual(ec.execute("SELECT COUNT(DISTINCT wallet) FROM group_buys WHERE payer = ?", (R,)).fetchone()[0], 6)
        members = json.loads(ec.execute("SELECT members FROM group_list WHERE kind = 'wallet'").fetchone()[0])
        self.assertEqual(ec.execute("SELECT credits FROM group_runs WHERE kind = 'night'").fetchone()[0], 90)
        ec.close()
        self.assertEqual(members, sorted([A, B, Cw, D]))        # not R, the dev, E, the bundle, the bot or the users
        g = gd.trader_groups("wallet")
        self.assertEqual(g["groups"][0]["members"], sorted([A, B, Cw, D]))
        self.assertEqual(g["groups"][0]["metrics"]["tokens"], 3)
        # without the funder tie the one-owner bundle alone would be a fake "list" of four
        rows = [(m, x, NOW, 1000 * k + 50) for k, m in enumerate(MINTS, 1) for x in XS]
        self.assertEqual(len(gd.wallet_groups(gd.wallet_links(rows, C), C)), 1)
        owner = gd.owner_ids({x: {F} for x in XS})
        self.assertEqual(gd.wallet_groups(gd.wallet_links(rows, C, owner=owner), C), [])
        # paid by the relayer for everybody: attributing to the payer would have made R a member next to A-D
        payer_rows = [(m, w, NOW, 1000 * k + s) for k, m in enumerate(MINTS, 1) for w, s in
                      ((A, 10), (B, 11), (Cw, 12), (D, 13), (R, 11))]
        self.assertIn(R, set().union(*gd.wallet_groups(gd.wallet_links(payer_rows, C), C)))
        self.assertNotIn(R, set().union(*gd.wallet_groups(gd.wallet_links(payer_rows, C, skip={R}), C)))
        self.assertEqual(gd.bots([(BOT, MINTS[0], NOW, i, "buy") for i in range(51)]), {BOT})
        self.assertEqual(gd.bots([(A, MINTS[0], NOW, 7, "buy"), (A, MINTS[0], NOW, 7, "sell")]), {A})   # sandwich
        self.assertEqual(gd.bots([], labels={E: ["mev"], A: ["smart"]}), {E})

    def test_credit_cap_of_a_pass(self):
        ec = gd.connect(self.p["early_db"])
        helius = FakeHelius({})
        n, spent = gd.fetch_early(ec, MINTS, C, 70, helius, 150.0, log=lambda *a: None)
        self.assertEqual((n, spent, len(helius.asked)), (2, 60, 2))   # a third mint would pass 70
        n, spent = gd.fetch_early(ec, MINTS, C, 29, helius, 150.0, log=lambda *a: None)
        self.assertEqual((n, spent), (0, 0))
        self.assertEqual(sorted(m for (m,) in ec.execute("SELECT mint FROM group_fetched")), MINTS[:2])
        self.assertEqual(gd.fetch_candidates(ec, self.kc, C, NOW, extra=MINTS), [MINTS[2]])   # cached: not again
        ec.close()


class HiddenList(Base):
    def test_three_wallets_of_one_quality_group_without_a_call(self):
        mo = {A: "w1", B: "w1", Cw: "w1", D: "w1"}
        buys = [("TOKH", A, NOW - 500, 25000), ("TOKH", B, NOW - 400, None), ("TOKH", Cw, NOW - 100, 26000)]
        s = gd.hidden_signals(buys, mo, {"w1": "quality"}, set(), C)
        self.assertEqual([(x["token"], x["gid"], x["wallets"], x["ts"], x["mcap_usd"]) for x in s],
                         [("TOKH", "w1", [A, B, Cw], NOW - 100, 26000)])
        self.assertEqual(gd.hidden_signals(buys, mo, {"w1": "quality"}, {"TOKH"}, C), [])     # a public call exists
        self.assertEqual(gd.hidden_signals(buys, mo, {"w1": "bad"}, set(), C), [])
        self.assertEqual(gd.hidden_signals(buys[:2] + [("TOKH", Cw, NOW + 400, None)], mo, {"w1": "quality"}, set(), C), [])
        self.assertEqual(gd.hidden_signals(buys, mo, {"w1": "quality"}, set(), C, owner_of={B: A}), [])   # 2 owners

    def test_signal_in_the_pass_the_shadow_and_get_market_signals(self):
        self.shadow()
        ec = gd.connect(self.p["early_db"])
        gd.save_groups(ec, "wallet", [("wq", [A, B, Cw, D], {"grade": "quality", "tokens": 5})], NOW)
        ec.close()
        hc = livestore.connect(self.p["hype_db"])
        for i, (w, dt) in enumerate(((A, 500), (B, 400), (Cw, 100))):
            hc.execute("INSERT INTO live_trades VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                       (f"s{i}", "TOKH", w, "buy", 0.5, 1e6, 1e-7, 100.0, "pump", NOW - dt, None))
        hc.close()
        r = gd.incremental(now=NOW, sol_usd=150.0, log=lambda *a, **k: None, **self.p)
        self.assertEqual((r["hidden"], r["shadow"]), (1, 1))
        rows = gd.mcp_signals(now=NOW, live={})
        self.assertEqual([(x["token"], x["source"], x["group"]["group_id"], x["under_30k"]) for x in rows],
                         [("TOKH", "hidden_group", "wq", True)])   # $15k: analysed, never bought
        from ui import mcpapi, prijedlog, pravitrade
        with mock.patch.object(pravitrade, "gather_callers", return_value=[]), \
                mock.patch.object(prijedlog, "live_market", return_value={}):
            out = mcpapi.signals(now=NOW)["signals"]
        self.assertEqual([x["source"] for x in out], ["hidden_group"])
        d, err = mcpapi._tool("get_group_activity", {"since_ts": NOW - 3600})
        self.assertFalse(err)
        self.assertEqual(d["signals"][0]["source"], "hidden_group")
        self.assertEqual(len(d["activity"]), 3)
        d, err = mcpapi._tool("get_trader_groups", {"kind": "wallet", "min_quality": "quality"})
        self.assertEqual((err, [g["group_id"] for g in d["groups"]]), (False, ["wq"]))
        self.assertTrue(mcpapi._tool("get_trader_groups", {"min_quality": "super"})[1])
        names = {t["name"]: t for t in mcpapi.TOOLS}
        for n in ("get_trader_groups", "get_group_activity"):
            self.assertTrue(names[n]["annotations"]["readOnlyHint"])
        self.assertIn("group_label", names["get_trader_groups"]["description"])

    def test_trace_without_a_call(self):
        buys = [("TOKT", f"n{i}", NOW - 60) for i in range(8)] + [("TOKT", f"o{i}", NOW - 1200) for i in range(3)]
        args = dict(mcap_of={"TOKT": 40000}, first_seen={"TOKT": NOW - 7200})
        self.assertEqual(gd.traces(buys, NOW, C, **args), [{"token": "TOKT", "buyers5": 8, "buyers30": 3, "mcap_usd": 40000}])
        self.assertEqual(gd.traces(buys, NOW, C, called={"TOKT"}, **args), [])
        self.assertEqual(gd.traces(buys, NOW, C, mcap_of={"TOKT": 60000}, first_seen={"TOKT": NOW - 7200}), [])
        self.assertEqual(gd.traces(buys, NOW, C, mcap_of={"TOKT": 40000}, first_seen={"TOKT": NOW - 600}), [])
        more = buys + [("TOKT", f"p{i}", NOW - 1000) for i in range(12)]   # 15 in 30 min: 8 < 4 x 2.5 per 5 min
        self.assertEqual(gd.traces(more, NOW, C, **args), [])


class Measure(Base):
    def test_target_before_stop_and_stop_first(self):
        up = [(NOW, 1.0, 1.0, 1.0, 1.0, 1), (NOW + 600, 1.0, 1.25, 1.0, 1.2, 1), (NOW + 1200, 1.2, 1.2, 0.6, 0.65, 1)]
        o = gd.path_outcome(up, NOW, C)
        self.assertEqual((o["hit1h"], o["hit4h"], o["ev"]), (1, 1, 0.18))
        down = [(NOW, 1.0, 1.0, 1.0, 1.0, 1), (NOW + 600, 1.0, 1.0, 0.65, 0.7, 1), (NOW + 1200, 0.7, 1.5, 0.7, 1.4, 1)]
        o = gd.path_outcome(down, NOW, C)
        self.assertEqual((o["hit1h"], o["ev"]), (0, -0.32))
        self.assertIsNone(gd.path_outcome([], NOW, C))

    def test_signals_are_measured_from_our_trades_and_the_late_callers_counted(self):
        ts = NOW - 5 * 3600
        ec = gd.connect(self.p["early_db"])
        ec.execute("INSERT INTO group_signals (ts, source, gid, token) VALUES (?, 'hidden_group', 'wq', 'TOKM')", (ts,))
        ec.commit()
        hc = livestore.connect(self.p["hype_db"])
        for i, (dt, px) in enumerate(((0, 1.0), (300, 1.1), (900, 1.3), (1500, 1.25), (5000, 1.4), (9000, 1.2))):
            hc.execute("INSERT INTO live_trades VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                       (f"m{i}", "TOKM", "w", "buy", 0.1, 1.0, px, 50.0, "pump", ts + dt, None))
        hc.close()
        self.call("late", "TOKM", "caller9", ts + 1800)
        self.kc.commit()
        n, gt = gd.measure_due(ec, self.p, C, NOW, gt_cap=0)
        row = ec.execute("SELECT hit1h, hit4h, ev, first_public_ts, r1h FROM group_signals").fetchone()
        ec.close()
        self.assertEqual((n, gt), (1, 0))
        self.assertEqual(row[:4], (1, 1, 0.18, ts + 1800))      # +20 % in 15 min; the callers came 30 min later
        self.assertAlmostEqual(row[4], 0.25)
        self.assertEqual(gd.trade_candles([(NOW + 5, 2.0), (NOW + 30, 3.0), (NOW + 61, 1.0)]),
                         [(NOW, 2.0, 3.0, 2.0, 3.0, 2), (NOW + 60, 1.0, 1.0, 1.0, 1.0, 1)])


class PaperGate(Base):
    def add_cases(self, n, ev, since):
        ec = gd.connect(self.p["early_db"])
        ec.executemany("INSERT INTO group_signals (ts, source, gid, token, ev, measured_ts) VALUES (?,?,?,?,?,?)",
                       [(since + 60 + i, gd.SOURCES[i % 2], "g", f"T{n}{ev}{i}", ev, NOW) for i in range(n)])
        ec.commit()
        ec.close()

    def test_paper_needs_7_days_of_shadow_and_ev_above_zero_on_30_cases(self):
        with self.assertRaisesRegex(ValueError, "u sjeni"):
            settings.set_flag(self.tc, gd.FLAG, "paper", "Jure", now=NOW)        # straight from off: no
        since = NOW - 3 * 86400
        self.shadow(since)
        with self.assertRaisesRegex(ValueError, "tek 3.0 od 7"):
            settings.set_flag(self.tc, gd.FLAG, "paper", "Jure", now=NOW)
        later = NOW + 5 * 86400
        self.add_cases(29, 0.1, since)
        with self.assertRaisesRegex(ValueError, "29 od 30"):
            settings.set_flag(self.tc, gd.FLAG, "paper", "Jure", now=later)
        self.add_cases(20, -0.3, since)
        with self.assertRaisesRegex(ValueError, "nije iznad nule"):
            settings.set_flag(self.tc, gd.FLAG, "paper", "Jure", now=later)
        self.add_cases(40, 0.2, since)
        self.assertIsNone(settings.paper_refusal(self.tc, gd.FLAG, later))
        self.assertEqual(settings.flag(gd.FLAG, con=self.tc), "shadow")          # never automatic
        settings.set_flag(self.tc, gd.FLAG, "paper", "Jure", now=later)
        self.assertEqual(settings.flag(gd.FLAG, con=self.tc), "paper")
        settings.set_flag(self.tc, gd.FLAG, "off", "Jure", now=later)             # down is always allowed
        settings.set_flag(self.tc, "dca_guard", "paper", "Jure", now=later)       # other flags: no gate
        self.assertIn(gd.FLAG, settings.FLAGS)   # 10.11.: later flags (insider_copy G14) come after it
        self.assertEqual(settings.FLAGS[gd.FLAG][0], "G12")


class FlagOff(Base):
    def test_flag_off_does_nothing(self):
        self.assertEqual(gd.mode(), "off")
        helius = FakeHelius({m: mint_txs(k, m) for k, m in enumerate(MINTS, 1)})
        for k, m in enumerate(MINTS, 1):
            self.call(f"k{k}", m, "caller1", NOW - 86400, mcap0=50000)
        self.kc.commit()
        said = []
        self.assertIsNone(gd.night(now=NOW, fetch=helius, sol_usd=150.0, force=True, log=said.append, **self.p))
        self.assertIsNone(gd.incremental(now=NOW, fetch=helius, sol_usd=150.0, credits=500, log=said.append, **self.p))
        self.assertEqual(helius.asked, [])
        self.assertFalse(os.path.exists(self.p["early_db"]))
        from league import flags as lflags
        lc = sqlite3.connect(self.p["league_db"])
        self.assertEqual(lflags.shadow_rows(lc), [])
        lc.close()
        self.assertEqual(gd.mcp_signals(now=NOW, live={}), [])
        self.assertEqual(gd.trader_groups("caller")["groups"], [])
        self.assertEqual(gd.group_activity(now=NOW)["activity"], [])
        self.assertEqual(len(said), 1)
        self.assertIn("isključena", said[0])


if __name__ == "__main__":
    unittest.main()
