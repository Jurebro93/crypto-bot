"""27.11. (kol/rotacija.py): weekly rotation of the Helius webhook set and the daily transfer batch. Never deletes a
row, never takes out a protected wallet, respects the 20 % cap, a parked wallet can return, the webhook asks for SWAP
only (no TRANSFER), the transfer batch stays inside its day budget and its rows reach kol/traces."""
import json
import os
import re
import sqlite3
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from kol import chainwatch, rotacija, store as kstore  # noqa: E402

NOW = 1_800_000_000
D = 86400
CFG = {"max_wallets": 30, "resync_h": 24, "rotacija": {"night_only": False, "cap_share": 0.2},
       "transferi": {"credits_day": 30, "max_pages": 2}}


def W(i):
    return f"W{i:03d}" + "x" * 36


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        j = lambda n: os.path.join(self.tmp, n)  # noqa: E731
        self.p = {"kol": j("kol.db"), "hype": j("hype.db"), "insajderi": j("insajderi.db"), "early": j("early.db"),
                  "wallets": j("wallets.db"), "league": j("league.db")}
        self.con = kstore.connect(self.p["kol"])
        h = sqlite3.connect(self.p["hype"])
        chainwatch._create(h)
        self.cur = [W(i) for i in range(20)]
        rows = []
        for i, w in enumerate(self.cur):   # every wallet watched for 10 days; W000.. trade more (cost more)
            for k in range(20 - i):
                rows.append((f"s{i}-{k}", w, "MINT", "buy", NOW - 10 * D + k * 60, 0.1))
        h.executemany("INSERT INTO chain_trades VALUES (?,?,?,?,?,?)", rows)
        h.execute("INSERT INTO chain_transfers VALUES ('t1', 'A', 'B', 'SOL', 1.0, ?)", (NOW - D,))
        h.commit()
        h.close()
        self.con.execute("INSERT OR REPLACE INTO kv VALUES ('chain_hook', ?)",
                         (json.dumps({"id": "h", "wallets": self.cur, "ts": NOW - D, "auth": chainwatch.AUTH_V}),))
        self.con.commit()
        i = sqlite3.connect(self.p["insajderi"])
        i.executescript("""CREATE TABLE i2_part (eid TEXT, wallet TEXT, owner TEXT, buy_ts INTEGER, sol_in REAL,
            n_sells INTEGER, sol_out REAL, first_sell_ts INTEGER, bought_before INTEGER, sold_into INTEGER, lead_s INTEGER,
            src TEXT, PRIMARY KEY (eid, wallet));
            CREATE TABLE i2_smart (wallet TEXT PRIMARY KEY, owner TEXT, cluster TEXT, roles TEXT, score REAL, n_jumps INTEGER,
            n_calls INTEGER, holder_profit REAL, last_buy_ts INTEGER, last_token TEXT, updated INTEGER);
            CREATE TABLE ik_wallets (inf TEXT, owner TEXT, members TEXT, cls TEXT, score REAL);""")
        # W019 bought before a pump 3 days ago: useful
        i.execute("INSERT INTO i2_part (eid, wallet, buy_ts, bought_before) VALUES ('e1', ?, ?, 1)", (W(19), NOW - 3 * D))
        # W018 is in an influencer's cluster (person): protected
        i.execute("INSERT INTO ik_wallets VALUES ('inf', 'o', ?, 'kandidat', 1.0)", (json.dumps([W(18)]),))
        for k in range(10):   # replacement candidates
            i.execute("INSERT INTO i2_smart (wallet, score) VALUES (?, ?)", (f"C{k:02d}" + "y" * 38, 100 - k))
        i.commit()
        i.close()
        lg = sqlite3.connect(self.p["league"])
        lg.execute("CREATE TABLE follows (id INTEGER, user TEXT, kind TEXT, target TEXT, active INTEGER)")
        lg.execute("INSERT INTO follows VALUES (1, 'igrac', 'wallet', ?, 1)", (W(0),))   # W000: busiest, but followed
        lg.commit()
        lg.close()
        self.con.execute("INSERT INTO kol_ids (wallet) VALUES (?)", (W(1),))   # W001: a public KOL (person)
        self.con.commit()
        self.cfg = json.loads(json.dumps(CFG))
        self.cfg["rotacija"]["pinned"] = [W(2)]   # W002: pinned by the owner
        self.nolive = lambda n: []

    def counts(self):
        out = {}
        for k, path in self.p.items():
            if not os.path.exists(path):
                continue
            c = sqlite3.connect(path)
            for (t,) in c.execute("SELECT name FROM sqlite_master WHERE type = 'table'"):
                if not t.startswith(("rot_", "tb_")):
                    out[f"{k}.{t}"] = c.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            c.close()
        return out

    def rotate(self, now=NOW, **kw):
        return rotacija.rotate(self.con, self.cfg, now, self.p, log=lambda *a: None, live_fn=self.nolive,
                               precall_fn=lambda: [], **kw)


class Rotation(Base):
    def test_never_deletes_rows(self):
        before = self.counts()
        self.rotate()
        rotacija.returns(self.con, self.cfg, NOW + 2 * D, self.p, log=lambda *a: None)
        after = self.counts()
        for k, n in before.items():
            self.assertGreaterEqual(after.get(k, 0), n, k)
        src = open(os.path.join(ROOT, "kol", "rotacija.py")).read()
        self.assertIsNone(re.search(r"\bDELETE\b", src.upper().replace("NIŠTA SE NE BRIŠE", "")
                                    .replace("NEMA NIJEDAN DELETE", "")))

    def test_protected_never_out_and_cap(self):
        r = self.rotate()
        self.assertEqual(r["status"], "ok")
        out = {w for (w,) in self.con.execute("SELECT wallet FROM rot_log WHERE action = 'out'")}
        self.assertEqual(len(out), 4)                          # 20 % of 20
        self.assertLessEqual(len(out), int(len(self.cur) * 0.2))
        for w in (W(0), W(1), W(2), W(18), W(19)):             # followed, person, pinned, influencer, useful
            self.assertNotIn(w, out)
        self.assertEqual(out, {W(3), W(4), W(5), W(6)})         # the costliest idle ones first
        ins = [w for (w,) in self.con.execute("SELECT wallet FROM rot_log WHERE action = 'in'")]
        self.assertEqual(len(ins), 4)
        # the webhook list: parked out, replacements in, protected still there, cap kept
        got = chainwatch.wanted(self.con, {"max_wallets": 30}, wallet_db=self.p["wallets"])
        for w in out:
            self.assertNotIn(w, got)
        for w in ins:
            self.assertIn(w, got)
        self.assertIn(W(1), got)   # the KOL (person) stays; league follows are read from league.db by wanted()
        self.assertLessEqual(len(got), 30)

    def test_weekly_only_and_no_rotation_on_unreadable_source(self):
        self.assertEqual(self.rotate()["status"], "ok")
        self.assertEqual(self.rotate(now=NOW + D)["status"], "nije_na_redu")
        bad = dict(self.p, early=os.path.join(self.tmp, "early.db"))
        with open(bad["early"], "wb") as f:
            f.write(b"not a database" * 100)
        r = rotacija.rotate(self.con, self.cfg, NOW + 8 * D, bad, log=lambda *a: None, live_fn=self.nolive,
                            precall_fn=lambda: [])
        self.assertEqual(r["status"], "greska_izvora")
        n = self.con.execute("SELECT COUNT(*) FROM rot_log WHERE action = 'out'").fetchone()[0]
        self.assertEqual(n, 4)   # nothing more went out

    def test_young_wallets_not_judged(self):
        rotacija.ensure(self.con)
        self.con.executemany("INSERT INTO rot_seen VALUES (?, ?, ?)", [(w, NOW - D, NOW) for w in self.cur])
        h = sqlite3.connect(self.p["hype"])
        h.execute("UPDATE chain_trades SET ts = ?", (NOW - 3600,))
        h.commit()
        h.close()
        self.assertEqual(self.rotate()["van"], 0)

    def test_parked_wallet_returns(self):
        self.rotate()
        parked = W(3)
        self.assertEqual(self.con.execute("SELECT state FROM rot_state WHERE wallet = ?", (parked,)).fetchone()[0], "parked")
        self.assertEqual(rotacija.returns(self.con, self.cfg, NOW + D, self.p, log=lambda *a: None), 0)
        i = sqlite3.connect(self.p["insajderi"])
        i.execute("INSERT INTO i2_part (eid, wallet, buy_ts, bought_before) VALUES ('e2', ?, ?, 1)", (parked, NOW + D))
        i.commit()
        i.close()
        self.assertEqual(rotacija.returns(self.con, self.cfg, NOW + 2 * D, self.p, log=lambda *a: None), 1)
        self.assertEqual(self.con.execute("SELECT state FROM rot_state WHERE wallet = ?", (parked,)).fetchone()[0], "returned")
        self.assertIn(parked, chainwatch.wanted(self.con, {"max_wallets": 30}, wallet_db=self.p["wallets"]))
        acts = [a for (a,) in self.con.execute("SELECT action FROM rot_log WHERE wallet = ? ORDER BY ts", (parked,))]
        self.assertEqual(acts, ["out", "return"])

    def test_report_line(self):
        self.rotate()
        r = rotacija.report(self.p["kol"], None, NOW)
        self.assertEqual(r["parkirano"], 4)
        self.assertIn("rotacija novčanika", rotacija.report_line(r))


class Webhook(unittest.TestCase):
    def test_types_without_transfer(self):
        self.assertEqual(chainwatch.types({}), ["SWAP"])
        cfg = json.load(open(os.path.join(ROOT, "kol", "config.json")))["chain"]
        self.assertNotIn("TRANSFER", chainwatch.types(cfg))
        tmp = tempfile.mkdtemp()
        con = kstore.connect(os.path.join(tmp, "kol.db"))
        con.execute("INSERT INTO kol_ids (wallet, source, rank) VALUES ('K1', 'x', 1)")
        bodies = []

        def api(method, path="", body=None):
            if body is not None:
                bodies.append(body)
            return [] if method == "GET" else {"webhookID": "h1"}
        os.environ.setdefault("RENDER_EXTERNAL_URL", "https://example.invalid")
        old = kstore.chain_key
        kstore.chain_key = lambda: "k"
        try:
            self.assertTrue(chainwatch.sync(con, {"max_wallets": 5, "resync_h": 24}, NOW, api, log=lambda *a: None))
        finally:
            kstore.chain_key = old
        self.assertEqual(bodies[-1]["transactionTypes"], ["SWAP"])
        self.assertTrue(con.execute("SELECT 1 FROM rot_seen WHERE wallet = 'K1'").fetchone())


class Batch(Base):
    def test_budget_and_rows_reach_traces(self):
        calls = []

        def fetch(w, since, token, t):
            calls.append(w)
            tx = {"blockTime": NOW - 3600, "transaction": {"signatures": [f"sig-{w[:4]}"],
                  "message": {"accountKeys": [{"pubkey": "FUNDER", "signer": True}, {"pubkey": w, "signer": False}]}},
                  "meta": {"err": None, "preBalances": [5_000_000_000, 0], "postBalances": [3_000_000_000, 2_000_000_000],
                           "preTokenBalances": [], "postTokenBalances": []}}
            return [tx], None, 10
        self.rotate()
        before = self.counts()["hype.chain_transfers"]
        r = rotacija.transfers_batch(self.con, self.cfg, NOW, self.p, fetch=fetch, log=lambda *a: None,
                                     live_fn=self.nolive)
        self.assertLessEqual(r["krediti"], 30)
        self.assertEqual(len(calls), 2)        # 30 credits, worst case 2 pages x 10 a wallet: no third wallet
        self.assertIn(W(1), calls)              # the person (KOL) first
        h = sqlite3.connect(self.p["hype"])
        got = h.execute("SELECT src, dst, mint, amount FROM chain_transfers WHERE dst = ?", (W(1),)).fetchall()
        h.close()
        self.assertEqual(got, [("FUNDER", W(1), "SOL", 2.0)])
        self.assertGreater(self.counts()["hype.chain_transfers"], before)
        r2 = rotacija.transfers_batch(self.con, self.cfg, NOW + 60, self.p, fetch=fetch, log=lambda *a: None,
                                      live_fn=self.nolive)
        self.assertEqual(r2["novcanika"], 0)   # the day's budget is spent
        from kol import traces
        self.assertGreaterEqual(traces.run(self.con, self.p["hype"], {}, now=NOW, tracked={W(1), "FUNDER"}), 1)


if __name__ == "__main__":
    unittest.main()
