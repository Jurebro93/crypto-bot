"""11.11. (Jure, flag pre_shill G15, kol/preshill.py): wallets that buy before the paid shill network, shadow only;
and the group grade rule of kol/groupdisc (quality needs 8+ measured events, 4 h / 24 h results and EV > 0 at both).

The chain check (a component joined through chains of pairs is split, a chain part is never a shill network), T0 and
the 6 h window, trades attributed to the signing owner (never a fee payer), bundles / dev-funded / bots / LP / CEX out,
the candidate thresholds and the out-of-sample confirmation, clusters by funder, the shadow signal and the network's
call as the exit, a Helius mint read only for the missing window and never twice, the credit cap, the MCP tools, the
Autopilot card (closed, under "Još", no chip), ui/kandidati's negative weight, and that the flag off does nothing.
No network: Helius is a fake.

    python3 -m unittest tests.test_preshill_offline
"""
import json
import os
import re
import sqlite3
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from kol import groupdisc as gd, preshill as ps, store as kstore  # noqa: E402
from league import store as lstore  # noqa: E402
from live import store as livestore  # noqa: E402
from trade import executor, settings  # noqa: E402
from wallets import store as wstore  # noqa: E402
from tests.test_apui_offline import Base as ApBase, SUMMARY, fake_aplog, fake_equity, history  # noqa: E402

NOW = 1_800_000_000
H, D = 3600, 86400
POOL = "PooL" + "1" * 40
QUIET = {"log": lambda *a, **k: None}


def W(name):
    return (name + "x" * 44)[:44]


def M(k):
    return ("Shl" + str(k) + "z" * 44)[:44]


INS1, INS2, INS3, INS4, INS5 = (W(n) for n in ("Insa", "Insb", "Insc", "Insd", "Inse"))
BOTW, DEVW, DFUND, CEXW, FUND, R = (W(n) for n in ("Botw", "Devw", "Dfund", "Cexw", "Fund", "Relay"))
B1, B2, B3, US0 = W("Bunda"), W("Bundb"), W("Bundc"), W("Usr0")
NET = [f"shill{i:02d}" for i in range(22)]
CHAIN = [f"chain{i:02d}" for i in range(25)]
TOKS = [M(k) for k in range(12)]
T0 = {M(k): NOW - (13 - k) * D + 3 * H for k in range(12)}   # k 0..8 older 2/3 (select), 9..11 newer 1/3 (confirm)


def tx(sig, slot, ts, mint, trades, signers=None, payer=None):
    """A getTransactionsForAddress-style tx: trades [(owner, token delta, SOL delta)]; the pool never signs."""
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
    return {"slot": slot, "blockTime": ts,
            "meta": {"err": None, "preBalances": pre_b, "postBalances": post_b, "preTokenBalances": pre_t,
                     "postTokenBalances": post_t},
            "transaction": {"signatures": [sig], "message": {
                "accountKeys": [{"pubkey": k, "signer": k in signers or k == payer} for k in keys]}}}


class FakeHelius:
    """wallets/rpc.fetch stand-in: txs of an address inside (since, until], 10 credits a page."""

    def __init__(self, by_addr=None):
        self.by_addr, self.asked = by_addr or {}, []

    def __call__(self, addr, since_ts=None, until_ts=None, max_pages=3, oldest_first=False, on_credits=None, **_kw):
        self.asked.append((addr, since_ts, until_ts, max_pages))
        for _ in range(max_pages):
            on_credits(10)
        out = [t for t in self.by_addr.get(addr, []) if (since_ts is None or t["blockTime"] > since_ts)
               and (until_ts is None or t["blockTime"] <= until_ts)]
        return sorted(out, key=lambda t: t["blockTime"], reverse=not oldest_first), True


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = self.tmp.name
        self.p = {k: os.path.join(d, f"{k[:-3]}.db") for k in ("kol_db", "hype_db", "tg_db", "wallet_db", "rug_db",
                                                              "early_db", "minute_db", "league_db", "events_db")}
        self._env = os.environ.get("EARLY_DB")
        os.environ["EARLY_DB"] = self.p["early_db"]
        self._db = settings.DB
        settings.DB = os.path.join(d, "trade.db")
        self.p["trade_db"] = settings.DB
        settings._FLAG_CACHE.clear()
        self.tc = executor.connect(settings.DB)
        self.kc = kstore.connect(self.p["kol_db"])
        lstore.connect(self.p["league_db"]).close()
        self.hc = livestore.connect(self.p["hype_db"])
        self.hc.execute("CREATE TABLE IF NOT EXISTS chain_trades (sig TEXT, wallet TEXT, mint TEXT, side TEXT, ts INTEGER, "
                        "sol REAL, PRIMARY KEY (sig, mint))")
        self.wc = wstore.connect(self.p["wallet_db"])
        self.n = 0

    def tearDown(self):
        settings.DB = self._db
        settings._FLAG_CACHE.clear()
        if self._env is None:
            os.environ.pop("EARLY_DB", None)
        else:
            os.environ["EARLY_DB"] = self._env
        for c in (self.tc, self.kc, self.hc, self.wc):
            c.close()
        self.tmp.cleanup()

    def flag(self, m="shadow", since=NOW - 8 * D):
        settings.set_flag(self.tc, ps.FLAG, m, "Jure", now=since)
        settings._FLAG_CACHE.clear()

    def call(self, tok, h, ts, **kw):
        self.n += 1
        cols = {"tweet_id": f"t{self.n}", "token": tok, "handle": h, "ts": ts, "kind": "call", **kw}
        self.kc.execute(f"INSERT INTO calls ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})", list(cols.values()))

    def trade(self, m, w, ts, side="buy", sol=0.5, tokens=1000.0, mcap_sol=None):
        """A PumpPortal trade (hype.db live_trades): the trader is the signer."""
        self.n += 1
        self.hc.execute("INSERT INTO live_trades (sig, mint, wallet, side, sol, tokens, price_sol, mcap_sol, ts) VALUES "
                        "(?,?,?,?,?,?,?,?,?)", (f"lt{self.n}", m, w, side, sol, tokens, sol / tokens, mcap_sol, ts))

    def network(self):
        """22 accounts that call 12 tokens together within 4 min (r1h -30 %, no outside callers: graded bad), a chain
        of 25 accounts (each pair shares 3 tokens) hanging on shill00, and 300 solo calls (the base rate)."""
        for k, tok in enumerate(TOKS):
            for i, h in enumerate(NET):
                self.call(tok, h, T0[tok] + i * 10, mcap0=50_000, r1h=-0.3, r24h=-0.6)
        prev = "shill00"
        for j, h in enumerate(CHAIN):
            for x in range(3):
                tok = f"CHN{j:02d}{x}" + "q" * 40
                t = NOW - 20 * D + j * 3 * H + x * 600
                self.call(tok, prev, t, mcap0=40_000)
                self.call(tok, h, t + 30, mcap0=40_000)
            prev = h
        for i in range(300):
            self.call(f"FILL{i:03d}" + "f" * 40, f"solo{i}", NOW - 25 * D + i * 60)
        self.kc.commit()
        groups = gd.build_caller_groups(self.kc, gd.config(), NOW)
        ec = gd.connect(self.p["early_db"])
        gd.save_groups(ec, "caller", groups, NOW)
        ec.close()
        return groups


# ===================================================================================================================
# B) the group grade
# ===================================================================================================================
class GradeRule(unittest.TestCase):
    def met(self, **kw):
        m = {"events": 12, "ev_1h": 0.05, "n_measured": 12, "n_measured_4h": 12, "n_measured_24h": 12, "ev_4h": 0.04,
             "r4h_med": 0.03, "r24h_med": -0.1, "rug_share": 0.0, "n_public": 0, "public_r1h_med": None}
        m.update(kw)
        return gd.caller_grade(m, gd.config())

    def test_quality_needs_8_measured_and_4h_24h_ev(self):
        self.assertEqual(self.met(), "quality")
        self.assertEqual(self.met(n_measured=7), "insufficient_data")          # good numbers on 7: not yet
        self.assertEqual(self.met(n_measured_4h=7), "insufficient_data")
        self.assertEqual(self.met(r4h_med=None, ev_4h=None), "insufficient_data")
        self.assertEqual(self.met(r4h_med=0.0), "bad")                          # r4h_med must be above 0
        self.assertEqual(self.met(ev_4h=-0.01), "bad")                          # EV > 0 at 4 h too
        self.assertEqual(self.met(r24h_med=-0.3), "bad")                        # r24h_med > -30 %
        self.assertEqual(self.met(ev_1h=-0.01), "bad")

    def test_lilistormx_is_no_quality_group_any_more(self):
        # 11.11.: "quality" with r24h -88 % on 6 samples; saved metrics of the old rule (no 4 h EV) are graded again
        old = {"events": 6, "ev_1h": 0.12, "n_measured": 6, "r4h_med": None, "r24h_med": -0.88, "rug_share": 0.0,
               "n_public": 1, "public_r1h_med": 0.1, "grade": "quality"}
        self.assertEqual(gd.grade_of("caller", "quality", old), "bad")
        self.assertEqual(gd.grade_of("caller", "quality", json.dumps({**old, "r24h_med": 0.2})), "insufficient_data")
        self.assertEqual(gd.grade_of("wallet", "quality", old), "quality")      # wallet groups keep their own rule
        self.assertEqual(gd.grade_text("bad", 6), "loša (n=6)")

    def test_n_measured_next_to_every_grade(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        p, tdb = os.path.join(tmp.name, "early.db"), os.path.join(tmp.name, "trade.db")
        tc = executor.connect(tdb)
        settings.set_flag(tc, gd.FLAG, "shadow", "Jure", now=NOW - D)
        tc.close()
        settings._FLAG_CACHE.clear()
        self.addCleanup(settings._FLAG_CACHE.clear)
        ec = gd.connect(p)
        old = {"events": 6, "ev_1h": 0.12, "n_measured": 6, "r24h_med": -0.88, "rug_share": 0.0, "n_public": 0,
               "public_r1h_med": None, "grade": "quality"}
        gd.save_groups(ec, "caller", [("cLili", ["LiLiStormX", "b"], old)], NOW)
        ec.execute("INSERT INTO group_activity VALUES (?,?,?,?,?,?,?)", (NOW - 60, "call", "cLili", "TOK", "b", 40000, 1))
        ec.commit()
        ec.close()
        g = gd.trader_groups(path=p, trade_db=tdb)["groups"][0]
        self.assertEqual((g["grade"], g["n_measured"], g["grade_text"]), ("bad", 6, "loša (n=6)"))
        a = gd.group_activity(path=p, trade_db=tdb, now=NOW)["activity"][0]
        self.assertEqual((a["grade"], a["n_measured"]), ("bad", 6))
        ec = gd.connect(p)
        _member, grades, _o = gd.load_groups(ec, "caller")
        ec.close()
        self.assertEqual(grades["cLili"], "bad")                                 # no "first call" signals from it


# ===================================================================================================================
# 0) the chain check
# ===================================================================================================================
class ChainCheck(Base):
    def test_truss_drops_chain_links_and_keeps_a_crew(self):
        crew = [(a, b) for i, a in enumerate("abcde") for b in "abcde"[i + 1:]]
        chain = [("e", "x1"), ("x1", "x2"), ("x2", "x3"), ("x3", "x4")]
        kept = ps.truss(crew + chain, 4)
        self.assertEqual(sorted(kept), sorted(tuple(sorted(e)) for e in crew))
        self.assertEqual(ps.kcore(crew + chain, 3), set("abcde"))
        d = ps.density(list("abcde") + ["x1", "x2", "x3", "x4"], crew + chain)
        self.assertEqual((d["n_links"], d["core"]), (14, 5))
        self.assertLess(d["density"], 0.5)

    def test_a_chained_component_is_split_and_only_the_crew_is_the_network(self):
        self.flag()
        groups = self.network()
        big = [g for g in groups if len(g[1]) >= 20]
        self.assertEqual(len(big), 1)
        gid, members, met = big[0]
        self.assertEqual(len(members), 47)                                       # groupdisc: one component of 47
        self.assertLess(met["density"], 0.3)                                     # ... linked through a chain
        ec = ps.connect(self.p["early_db"])
        out = ps.build_networks(ec, ps.paths(**self.p), ps.config(), NOW, **QUIET)
        self.assertEqual((out["groups_checked"], out["shill_networks"]), (1, 1))
        nets = ps.networks(ec)
        self.assertEqual(len(nets), 1)
        self.assertEqual(set(next(iter(nets.values()))), set(NET))             # the chain is not the network
        row = ec.execute("SELECT size, grade, shill, chained, how FROM preshill_networks WHERE shill = 1").fetchone()
        self.assertEqual(row[:4], (22, "bad", 1, 0))
        self.assertIn("truss", row[4])
        chk = ec.execute("SELECT size, periphery, diag FROM preshill_checks").fetchone()
        self.assertEqual(chk[:2], (47, 25))                                      # 25 accounts only through the chain
        ec.close()
        marks = ps.group_marks(trade_db=self.p["trade_db"])
        self.assertFalse(marks[gid]["shill_network"])                            # the whole component is NOT labelled
        self.assertEqual([x["size"] for x in marks[gid]["shill_parts"]], [22])
        self.assertEqual(marks[gid]["shill_parts"][0]["label"], "plaćena shill mreža")
        self.assertEqual(marks[gid]["chain_check"]["verdict"], "lanac, podijeljena")
        settings.set_flag(self.tc, gd.FLAG, "shadow", "Jure", now=NOW - D)
        settings._FLAG_CACHE.clear()
        g = next(x for x in gd.trader_groups(trade_db=self.p["trade_db"])["groups"] if x["group_id"] == gid)
        self.assertEqual((g["size"], g["shill_network"], g["shill_label"]), (47, False, None))   # get_trader_groups
        self.assertEqual(g["shill_parts"][0]["size"], 22)
        self.assertEqual(g["metrics"]["n_links"], 256)                       # 231 inside the crew, 24 chain, 1 bridge

    def test_a_chain_alone_is_never_a_network(self):
        table = {}
        for i in range(29):
            table[(f"c{i:02d}", f"c{i + 1:02d}")] = {"n": [4, 4], "exp": [0.1, 0.1], "lift": [9.0, 9.0]}
        parts = ps.refine([f"c{i:02d}" for i in range(30)], table, gd.config(), ps.config())
        self.assertTrue(all(len(p["members"]) < 20 or p["chained"] for p in parts))
        self.assertFalse(any(len(p["members"]) >= 3 and not p["chained"] for p in parts))


# ===================================================================================================================
# 1-3) tokens, buyers, wallets
# ===================================================================================================================
class Wallets(Base):
    def scene(self):
        """The network and its 12 tokens; pre-shill buyers from PumpPortal trades and Helius; the noise around."""
        self.flag()
        self.network()
        for tok in TOKS:
            livestore.add_launches(self.hc, [(tok, T0[tok] - 20 * H, DEVW, "", "S", 1.0, "s" + tok[:8], "pump")])
            self.kc.execute("INSERT OR REPLACE INTO tokens (token, pair, supply) VALUES (?,?,?)", (tok, POOL, 1e9))
        self.kc.commit()
        ins = {INS1: [0, 2, 4, 6, 9, 10], INS2: [1, 3, 5], INS3: [7, 8], BOTW: [0, 1, 2], DEVW: [3, 4, 5],
               DFUND: [6, 7, 8], CEXW: [0, 1, 2], POOL: [3, 4, 5]}
        for w, ks in ins.items():
            for k in ks:
                tok = TOKS[k]
                self.trade(tok, w, T0[tok] - 30 * 60, sol=0.5, mcap_sol=100)            # 30 min before T0
                self.trade(tok, w, T0[tok] + 15 * 60, side="sell", sol=0.9)             # sold into the wave
        for k in (0, 1, 2):                                                             # 200 min before: out of band
            self.trade(TOKS[k], INS4, T0[TOKS[k]] - 200 * 60, sol=0.5)
            self.trade(TOKS[k], INS4, T0[TOKS[k]] + 600, side="sell", sol=0.9)
        for k in (3, 4, 5):                                                             # sells at a loss
            self.trade(TOKS[k], INS5, T0[TOKS[k]] - 20 * 60, sol=0.5)
            self.trade(TOKS[k], INS5, T0[TOKS[k]] + 600, side="sell", sol=0.2)
        for i in range(250):                                                            # 250 trades in one day: a bot
            self.trade(W("Junk"), BOTW, NOW - 3 * D + i * 60, sol=0.01)
        self.hc.commit()
        for w, f in ((INS1, FUND), (INS2, FUND), (DFUND, DEVW)):                        # funders we already know
            wstore.observe(self.wc, w, token="x", source="rug", role="early_buyer", ts=NOW - D, extra={"funder": f})
        wstore.label(self.wc, CEXW, "cex")
        self.wc.commit()
        # Helius: the bundle (3 wallets, one slot) and a relayed buy (fee payer R, signer US0) on three tokens
        fake = {}
        for k in (9, 10, 11):
            tok, t = TOKS[k], T0[TOKS[k]]
            fake[tok] = [tx(f"b{k}{i}", 500 + k, t - 40 * 60, tok, [(w, 1_000_000, -0.4)]) for i, w in
                         enumerate((B1, B2, B3))]
            fake[tok].append(tx(f"r{k}", 600 + k, t - 25 * 60, tok, [(US0, 1_000_000, -0.3)], signers=[R, US0], payer=R))
        return FakeHelius(fake)

    def test_t0_window_exclusions_candidates_and_clusters(self):
        fake = self.scene()
        d = ps.night(now=NOW, fetch=fake, sol_usd=150.0, **QUIET, **self.p)
        self.assertEqual(d["shill_networks"], 1)
        ec = sqlite3.connect(self.p["early_db"])
        t = ec.execute("SELECT t0, first_handle, n_callers, window_start, wave_end, mcap_t0, dev FROM preshill_tokens "
                       "WHERE token = ?", (TOKS[0],)).fetchone()
        self.assertEqual(t[:3], (T0[TOKS[0]], "shill00", 22))                        # T0 = the network's first call
        self.assertEqual(t[3], T0[TOKS[0]] - 6 * H)                                  # 6 h before (launch was 20 h)
        self.assertEqual(t[4], T0[TOKS[0]] + 21 * 10 + 1800)                         # the last call + 30 min
        self.assertEqual((t[5], t[6]), (50_000, DEVW))
        st = {w: (s, why, cl) for w, s, why, cl in ec.execute("SELECT wallet, status, why, cluster FROM preshill_wallets")}
        self.assertEqual(st[INS1][0], "confirmed")                                   # 4 old tokens select, 2 new confirm
        self.assertEqual(st[INS2][0], "candidate")                                   # 3 tokens, only the older part
        self.assertEqual(st[INS3][0], "watch")                                       # 2 tokens
        self.assertEqual(st[INS4][0], "watch")                                       # 200 min before: out of the band
        self.assertEqual(st[INS5][0], "watch")                                       # PnL < 0
        self.assertEqual(st[INS1][2], st[INS2][2])                                   # one funder: one cluster
        self.assertEqual(st[BOTW][:1], ("excluded",))
        self.assertIn("bot", st[BOTW][1])
        self.assertIn("cex", st[CEXW][1])
        self.assertIn("LP", st[POOL][1])
        for w in (DEVW, DFUND, B1, B2, B3):                                          # dev, dev-funded, bundle: no row
            self.assertNotIn(w, st)
        self.assertEqual(ec.execute("SELECT SUM(bundle) FROM preshill_buys WHERE wallet IN (?,?,?)",
                                    (B1, B2, B3)).fetchone()[0], 9)
        buyers = {w for (w,) in ec.execute("SELECT wallet FROM preshill_buys WHERE token = ?", (TOKS[9],))}
        self.assertIn(US0, buyers)                                                   # the signer bought ...
        self.assertNotIn(R, buyers)                                                  # ... never the fee payer
        pnl, n, mm, into = ec.execute("SELECT pnl_sol, n_tokens, med_min, sold_into_wave FROM preshill_wallets WHERE "
                                      "wallet = ?", (INS1,)).fetchone()
        self.assertEqual((n, mm, into), (6, 30.0, 1.0))
        self.assertAlmostEqual(pnl, 6 * 0.4)
        ec.close()

    def test_helius_only_for_the_missing_window_never_twice_and_capped(self):
        fake = self.scene()
        ec = ps.connect(self.p["early_db"])
        # precall already read the window before the first call of TOKS[11] (complete): nothing to fetch for it
        ec.executescript("CREATE TABLE IF NOT EXISTS precall_fetched (mint TEXT PRIMARY KEY, ts INTEGER, credits INTEGER, "
                         "n_tx INTEGER, since_ts INTEGER, until_ts INTEGER, oldest_ts INTEGER, complete INTEGER)")
        ec.execute("INSERT INTO precall_fetched VALUES (?,?,?,?,?,?,?,?)",
                   (TOKS[11], NOW, 30, 5, T0[TOKS[11]] - 7 * H, T0[TOKS[11]], T0[TOKS[11]] - 7 * H, 1))
        ec.commit()
        p, c = ps.paths(**self.p), ps.config()
        ps.build_networks(ec, p, c, NOW, **QUIET)
        ps.collect_tokens(ec, p, c, NOW)
        n, spent = ps.fetch_windows(ec, c, NOW, 65, fake, **QUIET)
        self.assertEqual((n, spent), (2, 60))                                     # 30 credits a mint, the cap holds
        self.assertNotIn(TOKS[11], [a[0] for a in fake.asked])                    # covered by precall: not read
        asked = {a[0]: a for a in fake.asked}
        tok = next(iter(asked))
        self.assertEqual(asked[tok][1:3], (T0[tok] - 6 * H, T0[tok]))             # only [T0 - 6 h, T0]
        before = list(fake.asked)
        ps.fetch_windows(ec, c, NOW, 10_000, fake, **QUIET)
        self.assertFalse(set(a[0] for a in fake.asked[len(before):]) & set(asked))   # never twice
        self.assertEqual(ec.execute("SELECT credits FROM preshill_fetched WHERE key = ?", (TOKS[11],)).fetchone(), (0,))
        ec.close()

    def test_candidate_thresholds(self):
        c = ps.config()
        cut = NOW - 5 * D

        def obs(n, mins, pnl, t0=NOW - 10 * D):
            return [{"token": f"T{i}", "t0": t0 + i, "buy_ts": t0 + i - mins * 60, "sol_in": 1.0, "mcap_usd": 40000,
                     "sold_ts": t0 + 600, "sol_out": 1.0 + pnl, "wave_end": t0 + 3600, "peak_ts": None}
                    for i in range(n)]
        self.assertEqual(ps.wallet_stats(obs(3, 25, 0.5), cut, c)["status"], "candidate")
        self.assertEqual(ps.wallet_stats(obs(2, 25, 0.5), cut, c)["status"], "watch")       # 2 tokens
        self.assertEqual(ps.wallet_stats(obs(3, 4, 0.5), cut, c)["status"], "watch")        # under 5 min
        self.assertEqual(ps.wallet_stats(obs(3, 121, 0.5), cut, c)["status"], "watch")      # over 120 min
        self.assertEqual(ps.wallet_stats(obs(3, 25, -0.1), cut, c)["status"], "watch")      # PnL <= 0
        both = obs(3, 25, 0.5) + obs(2, 40, 0.3, t0=NOW - 2 * D)
        st = ps.wallet_stats(both, cut, c)
        self.assertEqual((st["status"], st["n_sel"], st["n_conf"]), ("confirmed", 3, 2))
        self.assertEqual(ps.sentence({"n_tokens": 4, "avg_min": 25, "sold_into_wave": 1.0, "pnl_sol": 3.2}),
                         "kupio 4 tokena prosječno 25 min prije mreže, prodao u val callova, +3,2 SOL")


# ===================================================================================================================
# 4) signal and exit, MCP, the card, ui/kandidati
# ===================================================================================================================
class Signal(Wallets):
    def test_signal_then_the_networks_call_is_the_exit(self):
        fake = self.scene()
        ps.night(now=NOW, fetch=fake, sol_usd=150.0, **QUIET, **self.p)
        new = M(99)
        self.trade(new, INS1, NOW - 900, sol=0.5, mcap_sol=300)
        self.trade(new, INS2, NOW - 600, sol=0.4, mcap_sol=320)
        self.trade(M(98), INS1, NOW - 700, sol=0.5)                     # one wallet of a cluster is enough ...
        self.call(M(97), "outsider", NOW - 3000)
        self.trade(M(97), INS1, NOW - 800, sol=0.5)                     # ... but not after a public call
        self.hc.commit()
        self.kc.commit()
        polls = FakeHelius()
        d = ps.incremental(now=NOW, fetch=polls, sol_usd=150.0, **QUIET, **self.p)
        self.assertEqual(d["signals"], 2)
        self.assertLessEqual(d["credits"], 1000)
        self.assertEqual(len(polls.asked), 2)                           # INS1 and INS2 read once (30 min apart)
        ec = sqlite3.connect(self.p["early_db"])
        sig = {t: (ts, bts, ws) for t, ts, bts, ws in ec.execute("SELECT token, ts, buy_ts, wallets FROM preshill_signals")}
        self.assertEqual(set(sig), {new, M(98)})
        self.assertEqual(sig[new][:2], (NOW, NOW - 900))                 # detected now; INS1 is in a cluster of 2
        self.assertEqual(sig[new][2].split(","), [INS1, INS2])          # every pre-shill wallet of that hour
        # the network calls the token 20 min later: negative weight and the exit ("sell into the calls")
        self.call(new, "shill03", NOW + 1200, mcap0=90_000)
        self.kc.commit()
        ps.incremental(now=NOW + 1800, fetch=polls, sol_usd=150.0, **QUIET, **self.p)
        ex = ec.execute("SELECT exit_ts, shill_ts FROM preshill_signals WHERE token = ?", (new,)).fetchone()
        self.assertEqual(ex, (NOW + 1200, NOW + 1200))
        ec.close()
        lc = sqlite3.connect(self.p["league_db"])
        lines = lc.execute("SELECT token, old_action, new_action FROM shadow_decisions WHERE flag = ? ORDER BY id",
                           (ps.FLAG,)).fetchall()
        lc.close()
        self.assertIn((new, "drži (kupci prije shill mreže)", "prodaj u callove"), lines)
        self.assertIn((new, "poziv callera (+1)", "shill mreža: težina -1, izlazna likvidnost"), lines)
        self.assertTrue(any(t == new and n.startswith("kupci prije shill mreže: 2 novčanika") for t, _o, n in lines))
        # MCP
        from ui import mcpapi
        names = {t["name"]: t for t in mcpapi.TOOLS}
        for n in ("get_pre_shill_wallets", "get_pre_shill_signals"):
            self.assertTrue(names[n]["annotations"]["readOnlyHint"])
        out, err = mcpapi._tool("get_pre_shill_wallets", {"limit": 5})
        self.assertFalse(err)
        self.assertEqual(out["networks"][0]["label"], "plaćena shill mreža")
        self.assertEqual(out["wallets"][0]["wallet"], INS1)
        self.assertTrue(out["wallets"][0]["solscan"].startswith("https://solscan.io/account/"))
        tl = {t["token"]: t for t in out["wallets"][0]["tokens"]}
        self.assertEqual((tl[TOKS[10]]["min_before_shill"], tl[TOKS[10]]["sold_into_wave"]), (30.0, True))
        self.assertEqual(tl[TOKS[10]]["first_shill_caller"], "shill00")
        # the new token became a network token with the call: bought 35 min before it, not sold yet
        self.assertEqual((tl[new]["min_before_shill"], tl[new]["sold_ts"]), (35.0, None))
        out, err = mcpapi._tool("get_pre_shill_signals", {"since_ts": NOW - D})
        self.assertFalse(err)
        s = next(x for x in out["signals"] if x["token"] == new)
        self.assertEqual(s["exit_ts"], NOW + 1200)

    def test_kandidati_counts_the_network_negative_and_flags_the_exit(self):
        fake = self.scene()
        ps.night(now=NOW, fetch=fake, sol_usd=150.0, **QUIET, **self.p)
        ec = sqlite3.connect(self.p["early_db"])
        ec.execute("INSERT INTO preshill_signals (ts, buy_ts, token, wallets) VALUES (?,?,?,?)",
                   (NOW - 1800, NOW - 2000, M(50), INS1 + "," + INS2))
        ec.commit()
        ec.close()
        from tests.test_kandidati_offline import FakeSources, live
        from ui import kandidati
        ps_view = ps.kandidati_view(NOW, trade_db=self.p["trade_db"])
        self.assertIn("shill05", ps_view["members"])
        self.assertIn(M(50), ps_view["held"])

        class S(FakeSources):
            def pre_shill(self, now):
                return ps_view
        src = S()
        src.c = [(M(50), [("shill05", "x", NOW - 60), ("other", "x", NOW - 50)], NOW - 60, NOW - 50, "S", live())]
        rows, _meta = kandidati.build(NOW, src, details=False)
        r = next(x for x in rows if x["token"] == M(50))
        self.assertEqual(r["score_parts"]["shill"], -1.0)
        self.assertIn("shill_network_call", r["flags"])
        self.assertIn("exit_signal", r["flags"])
        self.assertEqual(r["sources"]["caller"]["exit_signal"]["action"], "sell_into_calls")
        self.assertEqual(r["confluence"], 2)                             # "other" + the pre_shill signal; shill 0


class Detect(unittest.TestCase):
    def test_two_wallets_or_one_cluster_before_any_public_call(self):
        c = ps.config()
        a, b, k = W("Alone"), W("Btwo"), W("Klust")
        ws = {a: ("candidate", a, 1), b: ("confirmed", b, 1), k: ("candidate", "cl", 2)}
        self.assertEqual(ps.detect([("T1", a, NOW, None)], ws, {}, c), [])                     # one wallet: no
        got = ps.detect([("T1", a, NOW, 40000), ("T1", b, NOW + 600, 52000)], ws, {}, c)
        self.assertEqual([(s["buy_ts"], s["wallets"], s["mcap_usd"]) for s in got], [(NOW + 600, [a, b], 52000)])
        self.assertEqual(ps.detect([("T1", a, NOW, None), ("T1", b, NOW + 4000, None)], ws, {}, c), [])  # > 1 h
        self.assertEqual(ps.detect([("T1", a, NOW, None), ("T1", b, NOW + 600, None)], ws, {"T1": NOW + 300}, c), [])
        self.assertEqual([s["wallets"] for s in ps.detect([("T2", k, NOW, None)], ws, {}, c)], [[k]])  # a cluster
        self.assertEqual(ps.detect([("T2", k, NOW, None)], ws, {}, c, have={"T2"}), [])          # once per token
        self.assertEqual(ps.detect([("T3", W("Nobody"), NOW, None)], ws, {}, c), [])

    def test_one_trade_in_two_feeds_counts_once(self):
        from events import store as estore
        self.assertEqual(ps._uid("sigA", "mintB"), estore.uid("wallet|sigA|mintB"))   # events.db's own key
        u = ps._uid("s1", "T")
        rows = [("w", 100, "buy", 0.5, 10.0, 7, None, None, "pumpportal", u),
                ("w", 100, "buy", 0.5, 10.0, 7, "p", None, "helius", u),           # the same trade from Helius
                ("w", 90, "buy", 0.4, None, None, None, None, "rani", None),       # early_buyers: no key, not needed
                ("w", 200, "sell", 0.9, None, None, None, None, "rani", None)]     # ... but the only sell we know
        got = ps.merge(rows)["w"]
        self.assertEqual([(r[2], r[8]) for r in got], [("buy", "helius"), ("sell", "rani")])
        b = ps.token_buyers(rows, {"t0": 150, "window_start": 0}, ps.config())["w"]
        self.assertEqual((b["sol_in"], b["sold_ts"], b["sol_out"], b["payer"]), (0.5, 200, 0.9, "p"))


class Card(ApBase):
    """The Autopilot page (the fakes of tests/test_apui_offline): the card under "Još", closed, owner only."""

    def test_the_card_is_closed_under_jos_with_solscan_and_no_chip(self):
        from ui import pravitrade
        env = mock.patch.dict(os.environ, {"EARLY_DB": os.path.join(self.tmp.name, "early.db")})
        env.start()
        self.addCleanup(env.stop)
        self.addCleanup(settings._FLAG_CACHE.clear)
        settings.set_flag(self.con, ps.FLAG, "shadow", "Jure", now=NOW - D)
        settings._FLAG_CACHE.clear()
        ec = ps.connect()
        ec.execute("INSERT INTO preshill_tokens (token, t0, first_handle, wave_end, mcap_t0, peak_ts, peak_mcap) "
                   "VALUES (?,?,?,?,?,?,?)", (M(1), NOW - 2 * D, "shill00", NOW - 2 * D + 3600, 50000,
                                              NOW - 2 * D + 1800, 150000))
        ec.execute("INSERT INTO preshill_buys VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                   (M(1), INS1, NOW - 2 * D - 1500, None, 0.5, 30000, NOW - 2 * D + 900, 1.3, None, 0, "x"))
        ec.execute("INSERT INTO preshill_wallets (wallet, status, cluster, score, n_tokens, med_min, avg_min, "
                   "entry_mcap_med, pnl_sol, hit_rate, med_hold_min, sold_into_wave, n_sel, n_conf, last_ts, stats, "
                   "first_seen, status_ts, updated) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                   (INS1, "candidate", INS1, 5, 4, 25, 25, 30000, 3.2, 0.75, 40, 1.0, 3, 1, NOW - 2 * D,
                    json.dumps({"cluster_size": 2}), NOW, NOW, NOW))
        ec.commit()
        ec.close()
        self.mods(fake_equity(history(), SUMMARY), fake_aplog())
        self.assertNotIn("id=preshill", pravitrade.page({}, "Jure")[1])                 # 11.11.: lazy (ui/apterm)
        _, body = pravitrade.page({"sve": "1"}, "Jure")
        at = body.index('id=preshill')
        # 11.11. (Jure: "prikazuj samo ono što ima zaključak"): with wallets found it is a card of the main view, under
        # "Koga pratimo" and above "Postavke", that shows itself once it has data (data-hide-empty, polled)
        self.assertGreater(at, body.index("id=pratimo"))
        self.assertLess(at, body.index("id=apx-ostalo"))
        self.assertIn("id=apx-preshill data-x-src=/pravi-trade/l/preshill data-x-every=120 data-hide-empty>", body)
        tag = body[body.rindex("<details", 0, at):body.index(">", at)]
        self.assertNotIn(" open", tag)                                                    # closed
        self.assertIn("Kupci prije shill mreže", body)
        self.assertIn(f"https://solscan.io/account/{INS1}", body)
        self.assertIn("kupio 4 tokena prosječno 25 min prije mreže, prodao u val callova, +3,2 SOL", body)
        self.assertIn("prvi shill call", body)
        h2s = re.findall(r"<h2[^>]*>", body)
        self.assertEqual([h for h in h2s if 'data-sec=""' not in h and "nosec" not in h], [])   # no chip bar
        _, viewer = pravitrade.page({"sve": "1"}, "Ivan")
        self.assertNotIn("id=preshill", viewer)                                           # owner only


class FlagOff(Base):
    def test_flag_off_does_nothing(self):
        fake = FakeHelius({TOKS[0]: [tx("a", 1, NOW - H, TOKS[0], [(INS1, 1_000_000, -0.5)])]})
        self.assertIsNone(ps.night(now=NOW, fetch=fake, **QUIET, **self.p))
        self.assertIsNone(ps.incremental(now=NOW, fetch=fake, **QUIET, **self.p))
        self.assertEqual(fake.asked, [])
        self.assertFalse(os.path.exists(self.p["early_db"]))
        self.assertEqual(ps.wallets_view(trade_db=self.p["trade_db"])["wallets"], [])
        self.assertEqual(ps.signals_view(trade_db=self.p["trade_db"])["signals"], [])
        self.assertEqual(ps.card_html(None, None, None, trade_db=self.p["trade_db"]), "")
        self.assertEqual(ps.kandidati_view(NOW, trade_db=self.p["trade_db"])["members"], {})
        self.assertEqual(settings.FLAGS[ps.FLAG][0], "G15")             # appended to FLAGS, default off
        self.assertEqual(settings.flag(ps.FLAG, path=self.p["trade_db"]), "off")

    def test_paper_needs_its_own_proof(self):
        self.flag("shadow", since=NOW - 8 * D)
        with self.assertRaises(ValueError) as e:
            settings.set_flag(self.tc, ps.FLAG, "paper", "Jure", now=NOW)
        self.assertIn("izmjereno tek 0 od 30", str(e.exception))


if __name__ == "__main__":
    unittest.main()
