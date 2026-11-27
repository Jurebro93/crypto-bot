"""Osobe iza novčanika (27.11., vlasnik; osobe/) on synthetic databases, no network:

  - wallets tied by a first funding, a fee payer and same-block buys become ONE person; a hub's wallets do not
  - a frenzy minute and a wallet that co-buys with everybody add no link
  - the nickname comes from the fixed vocabulary only, is stable between nights and unique
  - a possible X link only for a TRACKED account, above the threshold, owner-only on the page, hideable for good;
    a wallet the person denied never counts; an untracked account is never evaluated
  - group call power: events by 30 min window, buckets 1 / 2-3 / 4+, cost never under 3 %, sellers into calls
  - the pages render without weights / thresholds; the night job is scheduled in the night window

    python3 -m unittest tests.test_osobe_offline
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

from osobe import dokazi, grupe, nadimak, run, store, xveza  # noqa: E402

BASE = (1794000000 // 86400) * 86400
NOW = BASE + 30 * 86400
H = 3600


def addr(name):
    return (name + "1" * 44)[:44]


A1, A2, A3 = addr("Alfa1"), addr("Alfa2"), addr("Alfa3")
HUB = addr("Hubx")
HW = [addr(f"Hubw{i:02d}") for i in range(25)]
LONE = addr("Lonely")
DENIED = addr("Denied")


def _mk(path, sql):
    con = sqlite3.connect(path)
    con.executescript(sql)
    con.commit()
    return con


class Fixture:
    def __init__(self):
        self.dir = tempfile.mkdtemp(prefix="osobe-")
        d = self.dir
        self.p = {k: os.path.join(d, f"{k[:-3]}.db") for k in
                  ("insajderi_db", "kol_db", "wallet_db", "hype_db", "early_db", "osobe_db", "rug_db", "corr_db")}
        from insajderi import kolwallets, store as istore
        ic = _mk(self.p["insajderi_db"], istore.SCHEMA + kolwallets.SCHEMA)
        for col in ("tier TEXT", "peak_mc REAL"):
            try:
                ic.execute(f"ALTER TABLE i2_events ADD COLUMN {col}")
            except sqlite3.OperationalError:
                pass
        from kol import store as kstore
        kc = kstore.connect(self.p["kol_db"])
        from wallets import store as wstore
        wc = wstore.connect(self.p["wallet_db"])
        hc = _mk(self.p["hype_db"], "CREATE TABLE chain_trades (sig TEXT, wallet TEXT, mint TEXT, side TEXT, ts INTEGER,"
                                    " sol REAL, PRIMARY KEY (sig, mint)); CREATE TABLE chain_transfers (sig TEXT, src TEXT,"
                                    " dst TEXT, mint TEXT, amount REAL, ts INTEGER, PRIMARY KEY (sig, src, dst, mint));")
        _mk(self.p["early_db"], "").close()
        n = [0]

        def trade(w, mint, ts, side, slot=None, payer=None, sol=0.5):
            n[0] += 1
            ic.execute("INSERT INTO i2_trades VALUES (?,?,?,?,?,?,?,?,?,?)",
                       (mint, w, f"s{n[0]}", ts, slot, side, sol, 1000.0, payer, None))

        # person Alfa: A1 funds A2 (first funding), A2 + A3 buy in the same block on 2 tokens, A3 pays A1's fee
        ic.execute("INSERT INTO ik_transfers VALUES (?,?,?,?,?,?,?,?)", ("f1", BASE, "sol", A1, A2, 1.0, "SOL", 1))
        for i, tok in enumerate(("DogeMint", "WifMint")):
            trade(A2, tok, BASE + i * H, "buy", slot=1000 + i)
            trade(A3, tok, BASE + i * H + 1, "buy", slot=1000 + i)
        trade(A1, "PupMint", BASE + 5 * H, "buy", payer=A3)
        # a hub funds 25 wallets: never a person
        for j, w in enumerate(HW):
            ic.execute("INSERT INTO ik_transfers VALUES (?,?,?,?,?,?,?,?)", (f"h{j}", BASE, "sol", HUB, w, 1.0, "SOL", 1))
            trade(w, "HubTok", BASE + 9 * H + j * 120, "buy")
        # timing: A1 bought before 2 pumps and sold into both
        for k, tok in enumerate(("DogeMint", "WifMint")):
            ic.execute("INSERT INTO i2_events (eid, kind, token, symbol, t0, tier) VALUES (?,?,?,?,?,?)",
                       (f"e{k}", "mkt", tok, tok[:4].upper(), BASE + 2 * 86400, "pumpa15"))
            ic.execute("INSERT INTO i2_part (eid, wallet, owner, buy_ts, bought_before, sold_into, lead_s) VALUES "
                       "(?,?,?,?,?,?,?)", (f"e{k}", A1, A1, BASE, 1, 1, 7200))
        # the tracked caller: A-wallets buy 1 h before each of 5 calls and sell 30 min after
        kc.execute("INSERT INTO kols (handle, followers) VALUES ('caller1', 50000)")
        kc.execute("INSERT INTO kols (handle, followers) VALUES ('caller2', 9000)")
        kc.execute("INSERT INTO kols (handle, followers) VALUES ('caller3', 9000)")
        for i in range(5):
            tok, t0 = f"Call{i}Mint", BASE + (10 + i) * 86400
            trade(A2 if i % 2 else A3, tok, t0 - H, "buy")
            trade(A2 if i % 2 else A3, tok, t0 + 1800, "sell")
            kc.execute("INSERT INTO calls (tweet_id, token, handle, ts, kind, r1h, r6h, r24h) VALUES (?,?,?,?,?,?,?,?)",
                       (f"t{i}", tok, "caller1", t0, "call", 0.2, 0.1, -0.1))
            # an account we do NOT track called the same tokens: never evaluated
            kc.execute("INSERT INTO calls (tweet_id, token, handle, ts, kind, r1h, r6h, r24h) VALUES (?,?,?,?,?,?,?,?)",
                       (f"p{i}", tok, "privatna_osoba", t0 + 60, "call", 0.2, 0.1, -0.1))
        # caller2 calls 20 other tokens the person never touched (the universe a front-run is measured against)
        for i in range(20):
            kc.execute("INSERT INTO calls (tweet_id, token, handle, ts, kind) VALUES (?,?,?,?,?)",
                       (f"u{i}", f"Other{i}Mint", "caller2", BASE + i * 3000, "call"))
        # a group call: caller1 + caller2 + caller3 within 20 min on GrpMint; solo calls elsewhere
        g0 = BASE + 20 * 86400
        for j, h in enumerate(("caller1", "caller2", "caller3")):
            kc.execute("INSERT INTO calls (tweet_id, token, handle, ts, kind, r1h, r6h, r24h) VALUES (?,?,?,?,?,?,?,?)",
                       (f"g{j}", "GrpMint", h, g0 + j * 600, "call", 0.5, 0.6, 0.8))
        # tokens and wallets.db rows for PnL
        kc.execute("INSERT INTO tokens (token, symbol, name) VALUES ('DogeMint', 'DOGE2', 'Doge two')")
        kc.execute("INSERT INTO tokens (token, symbol, name) VALUES ('WifMint', 'WIFF', 'dog wif hat')")
        kc.execute("INSERT INTO tokens (token, symbol, name) VALUES ('PupMint', 'PUPPY', 'puppy')")
        wc.executemany("INSERT INTO wallet_trades VALUES (?,?,?,?,?,?,?)",
                       [(A1, "w1", BASE, "PupMint", 100.0, -1.0, "buy"), (A1, "w2", BASE + H, "PupMint", -100.0, 3.0, "sell")])
        wc.executemany("INSERT INTO wallets (wallet, first_seen, last_seen, tier, score) VALUES (?,?,?,?,?)",
                       [(A2, BASE, BASE, "B", 45), (A3, BASE, BASE, "B", 41)])
        for c in (ic, kc, wc, hc):
            c.commit()
            c.close()
        self.seed = os.path.join(d, "seed.json")
        with open(self.seed, "w", encoding="utf-8") as f:
            json.dump({"influenceri": [{"id": "caller3", "name": "Caller Three", "handles": ["caller3"],
                                        "wallets": [{"address": DENIED, "status": "osporeno"}]}]}, f)

    def run(self, now=NOW):
        with mock.patch("insajderi.kolwallets.SEED", self.seed):
            return run.run(self.p, now=now, log=lambda s: None)

    def con(self):
        return sqlite3.connect(self.p["osobe_db"])


class PersonsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fx = Fixture()
        cls.summ = cls.fx.run()

    def _person_of(self, w):
        con = self.fx.con()
        try:
            r = con.execute("SELECT pid FROM os_member WHERE wallet = ?", (w,)).fetchone()
            return r[0] if r else None
        finally:
            con.close()

    def test_one_person_from_funding_payer_and_block(self):
        pa = self._person_of(A1)
        self.assertIsNotNone(pa)
        self.assertEqual(pa, self._person_of(A2))
        self.assertEqual(pa, self._person_of(A3))
        con = self.fx.con()
        kinds = set()
        for (k,) in con.execute("SELECT kinds FROM os_links"):
            kinds |= set(json.loads(k))
        con.close()
        self.assertTrue({"financiranje", "placa_naknadu", "isti_blok"} <= kinds, kinds)

    def test_hub_is_no_person(self):
        self.assertIsNone(self._person_of(HUB))
        self.assertIsNone(self._person_of(HW[0]))

    def test_profile_and_nickname(self):
        con = self.fx.con()
        name, prof = con.execute("SELECT nickname, profile FROM os_persons WHERE pid = ?",
                                 (self._person_of(A1),)).fetchone()
        con.close()
        prof = json.loads(prof)
        self.assertEqual(prof["timing"]["pre_pump"], 2)
        self.assertEqual(prof["timing"]["sold_into"], 2)
        self.assertEqual(prof["tokens"]["theme"], "pas")
        self.assertAlmostEqual(prof["pnl"]["realized_sol"], 2.0, places=3)
        self.assertTrue(name.endswith("s psećim tokenima"), name)
        self.assertTrue(any(name.startswith(r) for r in nadimak.ROLES["ranoranilac"]), name)
        self.assertNotIn("caller", name.lower())
        self.assertTrue(2 <= len(prof["reasons"]) <= 3)

    def test_name_and_id_stable_between_nights(self):
        con = self.fx.con()
        before = con.execute("SELECT pid, nickname FROM os_persons").fetchall()
        con.close()
        self.fx.run(NOW + 86400)
        con = self.fx.con()
        after = con.execute("SELECT pid, nickname FROM os_persons").fetchall()
        con.close()
        self.assertEqual(sorted(before), sorted(after))

    def test_xlink_tracked_only_and_hide(self):
        pid = self._person_of(A1)
        con = self.fx.con()
        rows = con.execute("SELECT handle, prob FROM os_xlinks WHERE pid = ?", (pid,)).fetchall()
        handles = {h for h, _p in rows}
        self.assertIn("caller1", handles)
        self.assertNotIn("privatna_osoba", handles)
        vis = xveza.visible(con, pid)
        self.assertTrue(vis and vis[0][1] == "caller1" and vis[0][2] >= xveza.SHOW_MIN)
        xveza.hide(con, pid, "caller1", "jure", NOW)
        con.commit()
        self.assertEqual([v for v in xveza.visible(con, pid) if v[1] == "caller1"], [])
        con.close()
        self.fx.run(NOW + 2 * 86400)   # a later night computes it again: still hidden
        con = self.fx.con()
        self.assertEqual([v for v in xveza.visible(con, pid) if v[1] == "caller1"], [])
        con.execute("DELETE FROM os_hidden")
        con.commit()
        con.close()

    def test_group_power_buckets(self):
        con = self.fx.con()
        g = store.kv(con, "grupe")
        con.close()
        self.assertEqual(g["sizes"]["2-3"]["24h"]["n"], 1)
        self.assertEqual(g["sizes"]["1"]["24h"]["n"], 5)
        self.assertEqual(g["sizes"]["4+"]["24h"]["n"], 0)
        # 5 solo calls all sold into by person Alfa
        self.assertEqual(g["sizes"]["1"]["24h"]["sold_into_share"], 1.0)

    def test_pages(self):
        pid = self._person_of(A1)
        from ui import osobe as uo
        with mock.patch.dict(os.environ, {"OSOBE_DB": self.fx.p["osobe_db"], "TRADE_OWNER": "jure"}):
            _t, lst = uo.page({}, "ana")
            _t, prof_other = uo.profile_page(pid, {}, "ana", owner=False)
            _t, prof_owner = uo.profile_page(pid, {}, "jure", owner=True)
            _t, found = uo.page({"q": A2}, "ana")
        self.assertIn("Osobe iza novčanika", lst)
        self.assertIn(f"/osobe/{pid}", lst)
        self.assertIn("Moć grupnih poziva", lst)
        self.assertNotIn("caller1", prof_other)
        self.assertIn("moguća veza", prof_owner)
        self.assertIn("Sakrij", prof_owner)
        self.assertIn("pripada osobi", found)
        for html in (lst, prof_owner):
            for secret in ("KIND_P", "0.85", "SHOW_MIN", "prag", "težin", "formul"):
                self.assertNotIn(secret, html)

    def test_server_login_noindex_owner_only_and_hide(self):
        import importlib
        import threading
        import urllib.error
        import urllib.parse
        import urllib.request
        from league import profiles, roles, store as lstore
        d = tempfile.mkdtemp(prefix="osobe-ui-")
        keys = ("UI_PASSWORD", "UI_PASS_JURE", "UI_PASS_ANA", "UI_USERS", "UI_ADMINS", "DATA_DIR", "OSOBE_DB",
                "TRADE_OWNER")
        old, old_db = {k: os.environ.get(k) for k in keys}, lstore.DB

        def restore():
            for k, v in old.items():
                os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)
            lstore.DB = old_db
            roles.reset_cache()
        self.addCleanup(restore)
        lstore.DB = os.path.join(d, "league.db")
        os.environ.pop("TRADE_OWNER", None)
        os.environ.update(DATA_DIR=d, UI_USERS="Jure,Ana", UI_PASS_JURE="jurepw", UI_PASS_ANA="anapw",
                          UI_PASSWORD="shared", UI_ADMINS="Jure", OSOBE_DB=self.fx.p["osobe_db"])
        profiles.reset_cache()
        roles.reset_cache()
        import run_ui
        importlib.reload(run_ui)
        srv = run_ui.ThreadingHTTPServer(("127.0.0.1", 0), run_ui.Handler)
        srv.verbose = False
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.server_close)
        self.addCleanup(srv.shutdown)
        base = f"http://127.0.0.1:{srv.server_address[1]}"

        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *a):
                return None
        op = urllib.request.build_opener(NoRedirect)

        def call(path, data=None, cookie=""):
            headers = {"Cookie": cookie} if cookie else {}
            if data is not None:
                headers["Origin"] = base
            req = urllib.request.Request(base + path, data=urllib.parse.urlencode(data).encode() if data else None,
                                         headers=headers)
            try:
                r = op.open(req)
            except urllib.error.HTTPError as e:
                r = e
            with r:
                return r.code, r.read().decode("utf-8", "replace"), r.headers

        def login(name, pw):
            req = urllib.request.Request(base + "/prijava", headers={"Origin": base}, data=urllib.parse.urlencode(
                {"name": name, "pw": pw, "next": "/osobe"}).encode())
            try:
                r = op.open(req)
            except urllib.error.HTTPError as e:
                r = e
            with r:
                return r.headers["Set-Cookie"].split(";")[0]
        jure, ana = login("Jure", "jurepw"), login("Ana", "anapw")
        pid = self._person_of(A1)
        code, body, _h = call("/osobe")
        self.assertEqual(code, 401)
        self.assertNotIn("Ranoranilac", body)
        code, body, hdr = call("/osobe", cookie=ana)
        self.assertEqual(code, 200)
        self.assertIn("noindex", hdr.get("X-Robots-Tag") or "")
        self.assertIn("Osobe iza novčanika", body)
        code, body, _h = call(f"/osobe/{pid}", cookie=ana)
        self.assertEqual(code, 200)
        self.assertNotIn("caller1", body)                                   # not the owner: no X link
        code, body, _h = call(f"/osobe/{pid}", cookie=jure)
        self.assertIn("@caller1", body)
        self.assertIn("moguća veza", body)
        code, _b, _h = call("/osobe/sakrij", {"pid": pid, "handle": "caller1"}, cookie=ana)
        self.assertEqual(code, 403)
        csrf = run_ui.csrf_token(jure.split("=", 1)[1])
        code, _b, _h = call("/osobe/sakrij", {"pid": pid, "handle": "caller1", "_csrf": csrf}, cookie=jure)
        self.assertEqual(code, 303)
        code, body, _h = call(f"/osobe/{pid}", cookie=jure)
        self.assertNotIn("@caller1", body)
        con = self.fx.con()
        con.execute("DELETE FROM os_hidden")
        con.commit()
        con.close()


class PureTest(unittest.TestCase):
    def test_cobuy_frenzy_and_busy(self):
        links = dokazi.Links()
        rows = []
        ws = [addr(f"Fr{i:02d}") for i in range(30)]
        for t in ("m1", "m2", "m3"):   # 30 buyers in the same minute on 3 tokens: a frenzy, nothing
            rows += [(w, t, 100 + i, 5, "buy", 1.0, None) for i, w in enumerate(ws)]
        dokazi.add_cobuys(links, rows, set(ws))
        self.assertEqual(len(links.ev), 0)
        links = dokazi.Links()
        bot = addr("Botty")
        others = [addr(f"Ot{i:02d}") for i in range(35)]
        rows = []
        for i, o in enumerate(others):
            for k in range(2):
                tok, ts = f"tok{i}-{k}", 10_000 * i + 1000 * k
                rows += [(bot, tok, ts, 7 + k, "buy", 1, None), (o, tok, ts, 7 + k, "buy", 1, None)]
        busy = dokazi.add_cobuys(links, rows, set(others) | {bot})
        self.assertIn(bot, busy)
        self.assertEqual(len(links.ev), 0)

    def test_nickname_vocab_unique_deterministic(self):
        tr = {"pre_pump": 0, "theme": "macka"}
        a = nadimak.make("o123", tr)
        self.assertEqual(a, nadimak.make("o123", tr))
        b = nadimak.make("o123", tr, taken={a})
        self.assertNotEqual(a, b)
        self.assertTrue(b.startswith(a + " · "))
        self.assertIn("mačjeg", a)

    def test_cost_floor_and_events(self):
        self.assertGreaterEqual(grupe.cost(10_000_000), 0.03)
        self.assertGreater(grupe.cost(1000), 0.03)
        evs = grupe.events([("a", "T", 0, 0.1, 0.1, 0.1), ("b", "T", 600, 0, 0, 0), ("c", "T", 4000, 0, 0, 0)])
        self.assertEqual([e["n"] for e in evs], [2, 1])
        grupe.excess(evs, {}, {})
        self.assertLess(evs[0]["x"]["24h"], 0.1)   # baseline + cost taken off

    def test_denied_wallet_never_evidence(self):
        handles = {"caller3": "caller3"}
        public = {DENIED: ("caller3", "osporeno")}
        res = xveza.evaluate({"p": {DENIED}}, [], {"caller3": [("X", 100)]}, handles, public)
        self.assertEqual(res, {})
        public = {DENIED: ("caller3", "javna_oznaka")}
        res = xveza.evaluate({"p": {DENIED}}, [], {"caller3": [("X", 100)]}, handles, public)
        self.assertGreaterEqual(res["p"][0][1], xveza.SHOW_MIN)

    def test_untracked_handle_never_evaluated(self):
        rows = [(A1, f"T{i}", 1000 * i, None, "buy", 1, None) for i in range(6)]
        rows += [(A1, f"T{i}", 1000 * i + 400, None, "sell", 1, None) for i in range(6)]
        cm = {"stranac": [(f"T{i}", 1000 * i + 100) for i in range(6)]}
        self.assertEqual(xveza.evaluate({"p": {A1}}, rows, cm, {"caller1": "caller1"}, {}), {})
        res = xveza.evaluate({"p": {A1}}, rows, cm, {"stranac": "stranac"}, {})
        self.assertIn("p", res)

    def test_scheduled_at_night(self):
        import run_sched
        job = [j for j in run_sched.JOBS if j[0] == "osobe"]
        self.assertEqual(len(job), 1)
        _n, fn, args = job[0]
        self.assertIs(fn, run_sched.daily_local)
        self.assertEqual(args[0], ["run_osobe.py", "noc"])
        self.assertTrue(1 <= args[1] < 6 and args[2] is False)


if __name__ == "__main__":
    unittest.main()
