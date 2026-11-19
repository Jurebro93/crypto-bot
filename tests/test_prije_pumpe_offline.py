"""19.11. (vlasnik: "svaki dan želim novčanike ... koji kupuju PRIJE pumpe i prodaju u pumpu"; isti dan: "midcapovi od
2 do 15 miliona ostaju, veći fokus na 15 do 200 ... bundle novčanici"), offline:

  - pump tiers: a market jump's peak MC >= 15M is "pumpa15", 2-15M "pumpa2"; the stored events of an OLD insajderi.db
    get the columns (migration) and their tier; Helius order pumpa15, pumpa2, the rest; max_mkt_tokens never cuts a
    token that pumped into a tier; a call event takes a merged jump's tier
  - the class "kupuje prije pumpe" and every exclusion with its reason (relayer, bot, snajper, kupuje sve, market
    maker, jednokratni, bez plaćene kupnje); confirmation out of sample by time; a planted future event changes nothing
  - only a PAID swap is a buy (chain._rows_of)
  - the copy test: misses counted (no price, liquidity), buckets 5M-15M / 15M+, the "brzo" variant's assumption label,
    the random-wallet null, the bootstrap by token, the cost floor 3 %
  - the bundles (same slot + one fee payer; a large share of the early buy volume)
  - the log line with thin data and with data
  - the midcap floor: a NEW real-money entry needs MC >= 15M (a 10M token: refused for real, the demo enters), an
    open real position at 10M still exits on its stop; the config values

    python3 -m unittest tests.test_prije_pumpe_offline
"""
import json
import os
import sqlite3
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from insajderi import chain, copy, events as ev, prijepumpe as pp, store  # noqa: E402

D = 86400
BASE = (1794000000 // D) * D
C = store.config({"warmup_days": 1, "sol_usd_hist": False, "boot_n": 200, "pp_min_n": 2, "null_k": 1})


def addr(name):
    return (name + "1" * 44)[:44]


def jump(k, tier="pumpa15", token=None, n_part=5):
    t0 = BASE + k * D + 6 * 3600
    return {"eid": f"j:{token or addr(f'T{k}')}:{t0}", "kind": "jump", "token": token or addr(f"T{k}"), "t0": t0,
            "win_end": t0 + 8 * 3600, "tier": tier, "n_part": n_part, "callers": {}, "prio": 1.0, "symbol": f"T{k}"}


def part(e, w, owner=None, sol_in=1.0, sold=True, lead_s=3 * 3600, bought=True):
    return (e["eid"], w, owner or w, e["t0"] - lead_s if bought else None, sol_in if bought else None,
            2 if sold else 0, 2.0 if sold else None, e["t0"] + 600 if sold else None, int(bought), int(sold),
            lead_s if bought else None)


class Tiers(unittest.TestCase):
    def test_tier_merge_order_and_migration(self):
        self.assertEqual(ev.tier_of(20e6, C), "pumpa15")
        self.assertEqual(ev.tier_of(15e6, C), "pumpa15")
        self.assertEqual(ev.tier_of(5e6, C), "pumpa2")
        self.assertIsNone(ev.tier_of(1e6, C))
        self.assertIsNone(ev.tier_of(None, C))
        call = {"eid": "c:x:1", "token": "x", "t0": 1000, "kind": "call"}
        j = {"eid": "j:x:2", "token": "x", "t0": 3000, "kind": "jump", "tier": "pumpa15", "peak_mc": 3e7}
        out = ev.merge([call], [j])
        self.assertEqual([e["eid"] for e in out], ["c:x:1"])
        self.assertEqual((out[0]["tier"], out[0]["peak_mc"]), ("pumpa15", 3e7))     # the pump is not lost
        es = [{"tier": None, "prio": 9}, {"tier": "pumpa2", "prio": 5}, {"tier": "pumpa15", "prio": 1},
              {"tier": "pumpa15", "prio": 3}]
        self.assertEqual([(e["tier"], e["prio"]) for e in sorted(es, key=chain.order_key)],
                         [("pumpa15", 3), ("pumpa15", 1), ("pumpa2", 5), (None, 9)])
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "i.db")
            old = sqlite3.connect(path)   # the production table before 19.11.: no tier / peak_mc
            old.execute("""CREATE TABLE i2_events (eid TEXT PRIMARY KEY, kind TEXT, token TEXT, symbol TEXT, t0 INTEGER,
                handle TEXT, crew TEXT, n_callers INTEGER, callers TEXT, mcap0 REAL, peak_ts INTEGER, peak_x REAL,
                win_end INTEGER, catalyst TEXT, catalysts TEXT, src TEXT, prio REAL, fetched INTEGER DEFAULT 0,
                n_part INTEGER, built_ts INTEGER)""")
            old.executemany("INSERT INTO i2_events (eid, kind, token, t0, mcap0, peak_x, win_end) "
                            "VALUES (?,?,?,?,?,?,?)",
                            [("j:a:1", "jump", "a", 1, 6e6, 1.5, 10), ("j:b:1", "jump", "b", 1, 3e6, 0.6, 10),
                             ("c:c:1", "call", "c", 1, 9e6, 3.0, 10)])
            old.commit()
            old.close()
            con = store.connect(path)
            store.connect(path).close()                                  # idempotent
            self.assertEqual(ev.mark_tiers(con, C), {"pumpa15": 1, "pumpa2": 1})
            got = {e["eid"]: (e["tier"], round(e["peak_mc"] or 0)) for e in ev.load(con)}
            self.assertEqual(got, {"j:a:1": ("pumpa15", 15_000_000), "j:b:1": ("pumpa2", 4_800_000),
                                   "c:c:1": (None, 0)})   # a call event gets a tier only from a merged jump
            con.close()

    def test_helius_reads_pumpa15_then_pumpa2_then_calls(self):
        evs = [dict(jump(1, None), kind="call", prio=50.0, eid="c1"), dict(jump(2, "pumpa2"), prio=9.0, eid="p2"),
               dict(jump(3, "pumpa15"), prio=0.5, eid="p15")]
        seen = []

        def fake(con, p, c, e, now, left, **k):
            seen.append(e["eid"])
            return 10
        with tempfile.TemporaryDirectory() as d, mock.patch.object(chain, "fetch_event", fake), \
                mock.patch.object(chain, "fetch_event_deep", fake):   # 19.11. navečer: a pump is read deep
            con = store.connect(os.path.join(d, "i.db"))
            chain.fetch_due(con, {}, C, evs, BASE + 40 * D, 25)
            con.close()
        self.assertEqual(seen, ["p15", "p2"])                             # the budget ran out before the call event

    def test_market_events_never_cut_a_pumped_token(self):
        from veliki import midcap
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "m.db")
            mc = midcap.connect(path)
            now = BASE + 10 * D
            rows = []
            for i in range(12):   # busy tokens, no jump
                rows.append((addr(f"Busy{chr(65 + i)}"), i, f"B{i}", "P", "raydium", 5e6, 1e5, 1e7 - i, None, 0, 0,
                             None, "dex", None, 1, None))
            rows.append((addr("Quiet"), 99, "Q", "P", "raydium", 8e6, 1e5, 10.0, None, 0, 0, None, "dex", None, 1,
                         None))
            mc.executemany("INSERT INTO tokens VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)
            for i in range(12):
                mc.executemany("INSERT INTO c1h (token, ts, c) VALUES (?,?,?)",
                               [(addr(f"Busy{chr(65 + i)}"), now - h * 3600, 1.0) for h in range(30)])
            closes = [1.0] * 10 + [1.4, 2.0, 3.0] + [1.0] * 10   # +200 % within 3 h, back to 1.0 now (MC 8M)
            mc.executemany("INSERT INTO c1h (token, ts, c) VALUES (?,?,?)",
                           [(addr("Quiet"), now - (len(closes) - i) * 3600, px) for i, px in enumerate(closes)])
            mc.commit()
            mc.close()
            c = {**C, "max_mkt_tokens": 5}
            got = ev.market_events({"midcap_db": path}, c, now, now - 5 * D)
            q = [e for e in got if e["token"] == addr("Quiet")]
            self.assertEqual(len(q), 1, got)
            self.assertEqual(q[0]["tier"], "pumpa15")                     # peak 8M x 3.0 = 24M
            self.assertAlmostEqual(q[0]["peak_mc"], 24e6, delta=1)

    def test_only_a_paid_swap_is_a_buy(self):
        from tests.test_insajderi2_offline import Chain
        ch = Chain()
        w, m = addr("Buyer"), addr("Mint")
        paid = ch.tx(m, w, "buy", 1.0, 1000, 100)
        rebate = ch.tx(m, w, "buy", -0.5, 1000, 200)      # tokens AND SOL arrive: no payment, no buy
        rows = chain._rows_of([paid, rebate], m)
        self.assertEqual([(r[3], r[5], r[6]) for r in rows], [(100, "buy", 1.0)])


class Classify(unittest.TestCase):
    def world(self, future=False):
        evs = [jump(k) for k in range(1, 7)] + [jump(k, "pumpa2") for k in (7, 8)] + [jump(9, None)]
        if future:
            evs.append(jump(30))
        A, B, M, T, S = addr("Alpha"), addr("Bot"), addr("Mm"), addr("Transfer"), addr("Sniper")
        parts = []
        for e in evs[:8]:
            parts += [part(e, A), part(e, B), part(e, M), part(e, T, sol_in=0.0), part(e, S)]
        parts.append(part(evs[0], addr("Fresh")))
        parts += [part(e, addr("Relayed"), owner="relayer:" + addr("Pay")) for e in evs[:4]]
        if future:   # only the future event: a new owner and A's hit on it
            parts += [part(evs[-1], addr("Late")), part(evs[-1], A)]
        ft = {}
        return evs, parts, {"A": A, "B": B, "M": M, "T": T, "S": S}, ft

    def test_class_rules_and_each_exclusion(self):
        evs, parts, w, _ft = self.world()
        st = pp.classify(parts, evs, BASE + 40 * D, C, bad={w["B"]}, mm={w["M"]})
        self.assertEqual(st[w["A"]]["cls"], "prije_pumpe")
        self.assertTrue(st[w["A"]]["confirmed"])
        self.assertEqual((st[w["A"]]["n_pumps15"], st[w["A"]]["n_pumps2"]), (6, 2))   # both tiers, apart
        self.assertEqual(st[w["A"]]["med_lead_min"], 180.0)
        self.assertEqual(st[w["B"]]["cls"], "bot")
        self.assertEqual(st[w["M"]]["cls"], "market_maker")
        self.assertEqual(st[w["T"]]["cls"], "bez_placanja")                  # sold, but no paid buy: cost basis 0
        self.assertEqual(st[addr("Fresh")]["cls"], "jednokratni")
        self.assertEqual(st["relayer:" + addr("Pay")]["cls"], "relayer")
        self.assertTrue(all(st[o]["why"] for o in st if st[o]["cls"] != "promatra"))
        # a sniper: its early buys within 60 s of launch
        ft = {e["token"]: e["t0"] - 3 * 3600 - 10 for e in evs}
        st2 = pp.classify(parts, evs, BASE + 40 * D, C, first_trade=ft)
        self.assertEqual(st2[w["S"]]["cls"], "snajper")
        # kupuje sve: early in >= 60 % of >= 10 covered pumps
        many = [jump(k) for k in range(1, 13)]
        busy = [part(e, addr("Busy")) for e in many]
        self.assertEqual(pp.classify(busy, many, BASE + 40 * D, C)[addr("Busy")]["cls"], "kupuje_sve")
        # the lead floor: bought 1 minute before is not "before the pump"
        quick = [part(e, addr("Quick"), lead_s=60) for e in evs[:6]]
        self.assertNotEqual(pp.classify(quick, evs, BASE + 40 * D, C)[addr("Quick")]["cls"], "prije_pumpe")

    def test_confirmation_out_of_sample_and_no_look_ahead(self):
        evs, parts, w, _ft = self.world()
        early = pp.classify(parts, evs, BASE + 5 * D, C)          # events 1-3 ended: 3 tokens, nothing newer
        self.assertEqual(early[w["A"]]["cls"], "prije_pumpe")
        self.assertFalse(early[w["A"]]["confirmed"])
        evs2, parts2, _w, _ft2 = self.world(future=True)
        as_of = BASE + 20 * D
        strip = (lambda d: {o: (x["cls"], x["n_tokens"], x["confirmed"]) for o, x in d.items()})
        self.assertEqual(strip(pp.classify(parts, evs, as_of, C)), strip(pp.classify(parts2, evs2, as_of, C)))

    def test_market_makers_from_two_sided_flow(self):
        with tempfile.TemporaryDirectory() as d:
            con = store.connect(os.path.join(d, "i.db"))
            evs = [jump(1), jump(2)]
            rows = []
            for e in evs:
                for i in range(3):
                    rows.append((e["token"], addr("Mm"), f"b{e['t0']}{i}", e["t0"] + i, None, "buy", 1, 1, None, None))
                    rows.append((e["token"], addr("Mm"), f"s{e['t0']}{i}", e["t0"] + 10 + i, None, "sell", 1, 1, None,
                                 None))
                rows.append((e["token"], addr("Dir"), f"d{e['t0']}", e["t0"] - 100, None, "buy", 1, 1, None, None))
            con.executemany("INSERT INTO i2_trades VALUES (?,?,?,?,?,?,?,?,?,?)", rows)
            con.commit()
            self.assertEqual(pp.market_makers(con, evs, C), {addr("Mm")})
            self.assertEqual(pp.market_makers(con, evs[:1], C), set())   # one window is not a pattern
            con.close()


class FakePrices(copy.Prices):
    """SOL prints per token from a dict; MC = price x 1e9 x $150; liquidity per token."""

    def __init__(self, prints, liq=None):
        super().__init__(None, {}, C)
        self.prints, self.liq = prints, liq or {}

    def _load_meta(self, tok):
        self.supply[tok] = 1e9

    def _sol_series(self, tok):
        return sorted(self.prints.get(tok, []))

    def series(self, tok, ts):
        return "sol", self._sol_series(tok)

    def sol_usd(self, ts):
        return 150.0

    def liq_at(self, tok, ts):
        return self.liq.get(tok)

    def bonded(self, tok, mcap, ts):
        return True


class Copy(unittest.TestCase):
    def setUp(self):
        self.evs = [jump(k) for k in range(1, 7)]
        self.A, self.Z = addr("Alpha"), addr("Zed")
        self.parts = [part(e, self.A) for e in self.evs] + [part(e, self.Z, sold=False) for e in self.evs[:2]]
        self.day = BASE + 12 * D
        n = [addr(f"New{i}") for i in range(5)]
        self.n = n
        b = self.day + 3600
        # A buys five NEW tokens on the day: priced (15M+), priced (5-15M), no price at all, thin pool, assumed price
        self.trades = [(self.A, n[0], b, "buy", 1.0, 1e5), (self.A, n[0], b + 7200, "sell", 2.0, 1e5),
                       (self.A, n[1], b, "buy", 1.0, 1e5), (self.A, n[1], b + 7200, "sell", 0.9, 1e5),
                       (self.A, n[2], b, "buy", None, None),
                       (self.A, n[3], b, "buy", 1.0, 1e5), (self.A, n[3], b + 7200, "sell", 1.0, 1e5),
                       (self.A, n[4], b, "buy", 1.0, 1e7), (self.A, n[4], b + 3600, "sell", 2.0, 1e7),
                       (self.Z, n[1], b + 60, "buy", 1.0, 1e5), (self.Z, n[1], b + 9000, "sell", 0.5, 1e5)]
        p0, p1 = 1.2e-4, 0.5e-4                    # x 1e9 x $150: 18M and 7.5M
        self.prints = {n[0]: [(b + 3, p0), (b + 60, p0), (b + 7203, p0 * 1.8), (b + 7260, p0 * 1.8)],
                       n[1]: [(b + 60, p1), (b + 120, p1), (b + 7260, p1 * 0.9), (b + 9060, p1 * 0.5)],
                       n[3]: [(b + 60, p0), (b + 3, p0), (b + 7260, p0)], n[4]: [(b + 3600, 2e-7)]}
        self.pr = FakePrices(self.prints, {n[3]: 5_000.0})

    def run_walk(self, parts=None, events=None):
        return pp.walk(None, {}, C, events or self.evs, parts or self.parts, self.day + D - 1, trades=self.trades,
                       prices=self.pr)

    def test_misses_buckets_fast_label_null_and_cost(self):
        res, sel = self.run_walk()
        self.assertIn(self.A, sel[self.day])
        rows = {r["token"]: r for r in res["60s"]}
        self.assertEqual(set(rows), set(self.n))                         # every buy is a row, misses included
        self.assertEqual(rows[self.n[2]]["miss"], "bez cijene")
        self.assertEqual(rows[self.n[3]]["miss"], "likvidnost")
        self.assertEqual(rows[self.n[0]]["bucket"], "15M+")
        self.assertEqual(rows[self.n[1]]["bucket"], "5M-15M")
        floor = pp.rt_floor()
        self.assertEqual(floor, 0.03)
        self.assertLessEqual(rows[self.n[0]]["ret"], 1.8 - 1 - floor + 1e-9)   # never under the 3 % floor
        self.assertLess(rows[self.n[0]]["ret_big"], rows[self.n[0]]["ret"] + 1e-9)
        st = pp.stats(res["60s"], C)
        self.assertEqual((st["n_buys"], st["miss_pct"]), (5, 40.0))
        self.assertEqual(st["misses"], {"bez cijene": 1, "likvidnost": 1})
        self.assertEqual((st["n_tokens"], st["n_owners"]), (st["n"], 1))
        fast = {r["token"]: r for r in res["brzo"]}
        self.assertFalse(fast[self.n[0]]["assumed"])                    # its own print 3 s after their buy
        self.assertTrue(fast[self.n[1]]["assumed"])                     # no print within 5 s: their price + 1 %
        self.assertTrue(res["null"])                                    # Z (early buyer, not selected) copied
        self.assertTrue(all(r["owner"] == self.Z for r in res["null"]))
        sm = pp.summarize(res, C)
        self.assertEqual(sm["60s"]["15M+"]["n"], 1)
        self.assertIsNotNone(sm["razlika_pct"])

    def test_planted_future_event_does_not_change_the_selection(self):
        _res, sel = self.run_walk()
        fut = jump(40)
        planted = self.parts + [part(fut, addr("Ghost"), lead_s=4 * 3600)] + \
            [part(e, addr("Ghost")) for e in self.evs[:2]]
        _res2, sel2 = self.run_walk(planted, self.evs + [fut])
        self.assertEqual(sel, {d: v for d, v in sel2.items() if d in sel})

    def test_bootstrap_by_token(self):
        rows = [{"token": "a", "ret": 0.1}, {"token": "a", "ret": 0.1}, {"token": "b", "ret": -0.1}]
        m, lo, hi = pp.boot(rows, "ret", 500)
        self.assertAlmostEqual(m, 0.1 / 3)
        self.assertLess(lo, m)
        self.assertGreater(hi, m)
        self.assertEqual(pp.boot([{"token": "a", "ret": 0.1}], "ret")[1:], (None, None))


class Bundles(unittest.TestCase):
    def test_same_slot_payer_and_early_share(self):
        with tempfile.TemporaryDirectory() as d:
            con = store.connect(os.path.join(d, "i.db"))
            evs = [jump(1), jump(2, "pumpa2")]
            rows = []
            for e in evs:
                for i in range(3):   # three wallets, one fee payer, one slot
                    rows.append((e["token"], addr(f"Bw{i}"), f"x{e['t0']}{i}", e["t0"] - 60, 777, "buy", 5.0, 1,
                                 addr("Pay"),
                                 None))
                rows.append((e["token"], addr("Other"), f"o{e['t0']}", e["t0"] - 3 * 3600, 1, "buy", 1.0, 1, None,
                             None))
            con.executemany("INSERT INTO i2_trades VALUES (?,?,?,?,?,?,?,?,?,?)", rows)
            con.executemany("INSERT INTO i2_part (eid, wallet, owner, sold_into) VALUES (?,?,?,?)",
                            [(evs[0]["eid"], addr("Bw0"), addr("Bw0"), 1)])
            con.commit()
            bs = pp.bundles(con, evs, C, BASE + 40 * D)
            b = bs["p:" + addr("Pay")]
            self.assertEqual((len(b["members"]), len(b["pumps"]), len(b["pumps15"]), len(b["sold"])), (3, 2, 1, 1))
            self.assertAlmostEqual(pp._med(list(b["shares"].values())), 15 / 16)
            self.assertEqual(pp.save_bundles(con, bs, C, BASE), 1)          # one-pump owners are under the floor
            # 19.11. (fix): a second event of the SAME token is the same pump: n_pumps counts tokens, not events
            same = dict(jump(3), token=evs[0]["token"], eid="j:again")
            con.executemany("INSERT INTO i2_trades VALUES (?,?,?,?,?,?,?,?,?,?)",
                            [(same["token"], addr(f"Bw{i}"), f"y{i}", same["t0"] - 60, 778, "buy", 5.0, 1, addr("Pay"),
                              None) for i in range(3)])
            con.commit()
            b2 = pp.bundles(con, evs + [same], C, BASE + 40 * D)["p:" + addr("Pay")]
            self.assertEqual((len(b2["pumps"]), len(b2["pumps15"])), (2, 1))
            self.assertEqual(pp.bundle_rows(con)[0]["n_pumps"], 2)
            con.close()


class Line(unittest.TestCase):
    def test_thin_and_data(self):
        thin = {"covered15": 4, "covered2": 9, "pumps15": 10, "pumps2": 20, "groups": 1, "confirmed": 0, "bundles": 0,
                "min_n": 20, "min_tokens": 3, "copy": {"60s": {"svi": {"n": 0, "n_buys": 0}}, "null": {"svi": {}}}}
        ln = pp.line(thin, 1200, 60000)
        self.assertTrue(ln.startswith("novčanici prije pumpe: 4 pumpi ≥ 15M"), ln)
        self.assertIn("premalo podataka", ln)
        self.assertIn("Helius danas 1,200/60,000", ln)
        s = {"n": 30, "n_buys": 40, "ev_pct": 2.5, "lo_pct": -1.0, "hi_pct": 6.0, "miss_pct": 25.0, "ev_big_pct": 1.0}
        full = dict(thin, confirmed=2, groups=3, slip_fast_pct=1.0,
                    copy={"60s": {"svi": s, "15M+": s}, "brzo": {"svi": s}, "null": {"svi": dict(s, ev_pct=-3.0)},
                          "razlika_pct": 5.5})
        ln = pp.line(full, 10, 60000)
        for want in ("3 grupa kupuje prije pumpe (2 potvrđeno)",
                     "kopija 60 s: +2.5 % [-1.0; +6.0] n=30 (promašeno 25.0 %",
                     "brzo 2 s (Pretpostavka klizanja 1 %)", "nasumični: -3.0 %", "Helius danas 10/60,000"):
            self.assertIn(want, ln)
        self.assertIn("još nema prolaza", pp.line(None))


class Pass(unittest.TestCase):
    def test_a_whole_pass_writes_the_list_and_the_line(self):
        from insajderi import report, run
        from tests.test_insajderi2_offline import build_world, cfg, t0_of
        with tempfile.TemporaryDirectory() as d:
            p, ch = build_world(d)
            lines = []
            env = {"INSAJDERI_DB": p["insajderi_db"]}
            with mock.patch.object(report, "OUT_DIR", d), mock.patch.dict(os.environ, env):
                s = run.run("once", now=t0_of(6) + 2 * 86400, cfg=cfg(), credits=100_000, fetch=ch.fetch,
                            log=lines.append, **p)
                self.assertIn("prije_pumpe", s)
                self.assertTrue(any(x.startswith("novčanici prije pumpe: ") for x in lines), lines)
                with open(os.path.join(d, pp.OUT_NAME), encoding="utf-8") as f:
                    md = f.read()
                self.assertIn("# Novčanici koji kupuju prije pumpe", md)
                self.assertIn("Statistika, ne optužba", md)
                self.assertIn("prije_pumpe", report.mcp({"limit": 3}))
            self.assertTrue(any(x.startswith("insajderi2: događaja") for x in lines))   # the old line stays


class TimeBudget(unittest.TestCase):
    """19.11.: the wall-clock budget of a pass (pass_max_s) on a fake clock, the light incr, ONE read of the trades."""

    def setUp(self):
        from tests.test_insajderi2_offline import build_world, t0_of
        self.tmp = tempfile.TemporaryDirectory()
        self.p, self.ch = build_world(self.tmp.name)
        self.now = t0_of(6) + 2 * 86400
        self.t = [0.0]
        env = mock.patch.dict(os.environ, {"INSAJDERI_DB": self.p["insajderi_db"]})
        env.start()
        self.addCleanup(env.stop)
        from insajderi import report
        out = mock.patch.object(report, "OUT_DIR", self.tmp.name)
        out.start()
        self.addCleanup(out.stop)

    def tearDown(self):
        self.tmp.cleanup()

    def fetch(self, *a, **k):
        self.t[0] += 1000.0          # every Helius call costs 1000 s on the fake clock
        return self.ch.fetch(*a, **k)

    def go(self, kind="once", limit=None, now=None, **k):
        from insajderi import run
        from tests.test_insajderi2_offline import cfg
        lines = []
        c = cfg(pass_max_s={"once": limit, "incr": limit, "night": limit}, **k)
        s = run.run(kind, now=now or self.now, cfg=c, credits=100_000, fetch=self.fetch, log=lines.append,
                    clock=lambda: self.t[0], **self.p)
        return s, lines

    def fetched(self):
        con = store.connect(self.p["insajderi_db"])
        n = con.execute("SELECT COUNT(*) FROM i2_events WHERE fetched = 1").fetchone()[0]
        con.close()
        return n

    def test_cut_pass_saves_logs_and_the_next_pass_continues(self):
        s, lines = self.go(limit=1500)
        n1 = self.fetched()
        self.assertGreaterEqual(n1, 1)
        self.assertLess(n1, 6)                                            # stopped before the rest
        cut = [x for x in lines if "prekinuto na vremenskoj granici 1500 s" in x]
        self.assertEqual(len(cut), 1, lines)
        self.assertTrue(cut[0].startswith("insajderi2: prolaz once: trajanje: događaji "), cut[0])
        self.assertIn(f"Helius ostaje {6 - n1} događaja", cut[0])
        self.assertIn("popis i kopija nisu izračunati", cut[0])
        self.assertTrue(os.path.exists(os.path.join(self.tmp.name, "insajderi.md")))   # the report from what it has
        self.assertEqual(s["prekinuto"][0][:13], "Helius ostaje")
        calls = len(self.ch.calls)
        self.t[0] = 0.0
        s2, lines2 = self.go(limit=None)                                  # the next pass, no bound
        self.assertEqual(self.fetched(), 6)
        self.assertFalse([x for x in lines2 if "prekinuto" in x])
        self.assertEqual(s2["confirmed"], 1)
        con = store.connect(self.p["insajderi_db"])
        done = {k for (k,) in con.execute("SELECT key FROM i2_fetch")}
        con.close()
        self.assertEqual(len(done), len(set(done)))
        self.assertGreater(len(self.ch.calls), calls)
        self.assertTrue(any(x.startswith("insajderi2: prolaz once: trajanje: događaji") and "kopija" in x
                            for x in lines2), lines2)

    def test_call_events_get_half_the_pass_time_so_the_list_is_computed(self):
        """19.11. (the first production pass spent all 900 s on Helius for untiered call events): the rest stops at
        rest_time_share of the pass time; the pass is NOT cut, the list and the copy tests run."""
        s, lines = self.go(limit=20000)            # every Helius call is 1000 s: the calls stop at 10 000 s
        n1 = self.fetched()
        self.assertGreaterEqual(n1, 1)
        self.assertLess(n1, 6)
        stop = [x for x in lines if "Helius za pozive stao na 50% vremena prolaza" in x]
        self.assertEqual(len(stop), 1, lines)
        self.assertIn(f"ostaje {6 - n1} događaja", stop[0])
        self.assertFalse([x for x in lines if "prekinuto na vremenskoj granici" in x], lines)
        self.assertIn("popis", s["trajanje"])      # the list stage ran
        self.assertTrue(any(x.startswith("novčanici prije pumpe:") for x in lines), lines)

    def test_pump_events_keep_the_whole_deadline(self):
        s, _l = self.go(limit=20000)               # build the events first
        con = store.connect(self.p["insajderi_db"])
        con.execute("UPDATE i2_events SET fetched = 0, tier = 'pumpa15'")
        con.execute("DELETE FROM i2_fetch")
        con.commit()
        con.close()
        self.t[0] = 0.0
        from insajderi import events as ev
        with mock.patch.object(ev, "mark_tiers", lambda *a, **k: None):   # one slice a window: one call a window
            s2, lines = self.go(limit=20000, pump_slices_pre=1, pump_slices_jump=1)
        self.assertGreater(self.fetched(), 2)      # pumps were read past the half-time mark

    def test_incr_is_light_and_the_trades_are_read_once(self):
        n_reads = []
        real = copy.wallet_trades

        def counted(con, p, ws):
            n_reads.append(len(ws))
            return real(con, p, ws)
        from insajderi import smart
        with mock.patch.object(copy, "wallet_trades", counted), \
                mock.patch.object(smart, "run", lambda *a, **k: {}):   # smart money reads its own wallets (ostalo)
            s, _l = self.go()
        self.assertEqual(len(n_reads), 1)                                 # ONE read for both copy tests
        self.assertIn("popis", s["trajanje"])
        con = store.connect(self.p["insajderi_db"])
        st = json.loads(store.kv(con, "stage_s"))
        self.assertIn("kopija", st)
        store.kv(con, "stage_s", json.dumps({**st, "popis": 100.0}))   # the list was slow on the last full pass
        con.commit()
        con.close()
        boom = mock.patch.object(copy, "selection", side_effect=AssertionError("incr must not copy"))
        with boom:
            s2, lines = self.go("incr", now=self.now + 3 * 3600)
        self.assertTrue(any("popis i bundle preskočeni (popis je u zadnjem punom prolazu trajao 100 s" in x
                            for x in lines), lines)
        self.assertEqual(s2["copy"], s["copy"])                           # the stored numbers
        con = store.connect(self.p["insajderi_db"])
        store.kv(con, "stage_s", json.dumps({**st, "popis": 1.0}))
        con.commit()
        con.close()
        with mock.patch.object(copy, "selection", side_effect=AssertionError("incr must not copy")):
            s3, lines3 = self.go("incr", now=self.now + 6 * 3600)
        self.assertIn("popis", s3["trajanje"])                            # fast list: it runs in incr
        self.assertNotIn("kopija", s3["trajanje"])
        pl = [x for x in lines3 if x.startswith("novčanici prije pumpe:")]
        self.assertTrue(pl)

    def test_kol_pass_never_runs_past_the_pass(self):
        from insajderi import kolwallets
        got = {}

        def fake(con, p, c, now, **k):
            got["left_s"] = k.get("left_s")
        with mock.patch.object(kolwallets, "run_pass", fake):
            self.go(limit=100_000)
        self.assertIsNotNone(got["left_s"])
        self.assertLessEqual(got["left_s"], 100_000)


class Config(unittest.TestCase):
    def test_values(self):
        c = store.config()
        self.assertEqual((c["helius_day"], c["kol_helius_share"], c["focus_mcap"], c["pump2_mcap"]),
                         (60000, 0.0, 15_000_000, 2_000_000))
        with open(os.path.join(ROOT, "wallets", "config.json")) as f:
            k = json.load(f)["kopija"]
        self.assertEqual((k["kredita_dan"], k["najvise_novcanika"]), (6000, 300))
        from veliki import universe
        self.assertEqual((universe.REAL_MIN_MCAP, universe.MIN_MCAP, universe.MAX_MCAP, universe.DATA_MIN_MCAP),
                         (15e6, 5e6, 200e6, 2e6))
        with open(os.path.join(ROOT, "start.sh")) as f:
            sh = f.read()
        self.assertIn('"${INSAJDERI_ONCE:-1}" = "1"', sh)
        self.assertIn('"${INSAJDERI_INCR:-1}" = "1"', sh)
        from trade import settings
        self.assertIn("insajderi2", settings.NEVER_LIVE)


# ---------- the midcap floor of real money (veliki/live.enter) --------------------------------------------------------
from tests.test_pravi_novac_sve_offline import LU, PU, tok  # noqa: E402
from tests import test_veliki_intra_offline as tvi  # noqa: E402
from veliki import live  # noqa: E402


class RealFloor15(tvi.Live):
    def mk_at(self, toks, mcap, px=1.0e-4):
        return {t: (px, 2_000_000.0, "https://dexscreener.com/solana/raydium", mcap, "BIG", {"m5": 0.0}) for t in toks}

    def test_real_needs_15m_demo_does_not_and_open_positions_still_exit(self):
        self.flag("veliki_range", "paper")
        from veliki import gate
        with mock.patch.object(gate, "real_refusal", lambda *a, **k: None), self._prio():
            out = live.tick(self.lg, lambda ts: self.mk_at([t for t in ts if t == tok(31)], 1e7), now=self.now,
                            force=True)
        rows = {(r[0], r[1]) for r in self.lg.execute("SELECT user, token FROM veliki_trades")}
        self.assertIn((PU, tok(31)), rows)                    # the demo enters a 10M token (its floor is unchanged)
        self.assertNotIn((LU, tok(31)), rows, out)            # real money does not: under 15M
        self.assertTrue(any("izvan 15-200M" in x for x in out), out)
        # a real position opened at 50M; the token falls to 10M: the stop still sells it
        self.lg.execute("DELETE FROM veliki_trades")
        self.lg.execute("DELETE FROM trades")
        self.lg.commit()
        live._ST["bar15"] = {}
        with mock.patch.object(gate, "real_refusal", lambda *a, **k: None), self._prio():
            live.tick(self.lg, lambda ts: self.mk_at([t for t in ts if t == tok(31)], 5e7), now=self.now + 1000,
                      force=True)
        rid, stop = self.lg.execute("SELECT id, stop_px FROM veliki_trades WHERE user=? AND status='open'",
                                    (LU,)).fetchone()
        live.tick(self.lg, lambda ts: self.mk_at([t for t in ts if t == tok(31)], 1e7, stop * 0.99),
                  now=self.now + 1100, force=True)
        st, reason = self.lg.execute("SELECT status, reason FROM veliki_trades WHERE id=?", (rid,)).fetchone()
        self.assertEqual((st, reason), ("closed", "stop"))


for _n in [n for n in dir(tvi.Live) if n.startswith("test_")]:   # only this class's own test above
    setattr(RealFloor15, _n, None)


if __name__ == "__main__":
    unittest.main()
