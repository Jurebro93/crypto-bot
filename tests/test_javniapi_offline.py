"""27.11.: the public API with a key per user (ui/javniapi.py, ui/javniapistr.py): auth, daily cap, burst, 429 with
Retry-After, canary determinism and tracing, no internal words in answers, the owner MCP kept apart, owner-only page."""
import importlib
import json
import os
import sqlite3
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.parse
import urllib.request
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from league import profiles, roles, store  # noqa: E402
from trade import settings  # noqa: E402
from ui import javniapi as A  # noqa: E402
from ui import javniapistr as S  # noqa: E402

TOK = "So11111111111111111111111111111111111111112"
TOK2 = "7GCihgDB8fe6KNjn2MYtkzZcRjQy3t9GHdC8uHYmW2hr"
WAL = "9WzDXwBbmkg8ZTbNMqUxvQRAyrZzDsGYdLVL9zYtAWWM"
# words that must never leave the API: internal sources, tables, scores, thresholds, the MCP
FORBIDDEN = ("rug filter", "topcheck", "rugcheck", "kol.db", "wallets.db", "hype", "copy_rank", "dokazani", "score",
             "weight", "threshold", "granica", "mcap0", "kandidati", "mcp", "helius", "dexscreener", "beta",
             "hidden_group", "scan_", "VISOK RIZIK", "ODBAČEN", "copy_score", "tier", "rug_verdict", "_source")


def no_internal(tc, out):
    txt = json.dumps(out, ensure_ascii=False).lower()
    for w in FORBIDDEN:
        tc.assertNotIn(w.lower(), txt, w)


class Base(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.old = (store.DB, settings.DB, dict(os.environ))
        store.DB, settings.DB = os.path.join(self.d, "league.db"), os.path.join(self.d, "trade.db")
        os.environ["KOL_DB"] = os.path.join(self.d, "kol.db")
        os.environ.pop("JAVNIAPI_PLANS", None)
        A.reset_burst()
        A.reset_cache()
        self.con = A.connect()

    def tearDown(self):
        self.con.close()
        store.DB, settings.DB = self.old[0], self.old[1]
        os.environ.clear()
        os.environ.update(self.old[2])

    def key(self, plan="free", cap=None):
        return A.create(self.con, "Ivan", plan, "test", cap, by="Jure")

    def get(self, path, key, qs=None, now=None):
        return A.handle(path, qs or {}, {"Authorization": f"Bearer {key}"} if key else {}, now=now)


class Keys(Base):
    def test_only_the_hash_is_stored_and_key_shown_once(self):
        kid, key = self.key()
        self.assertTrue(key.startswith("msk_"))
        dump = "\n".join(self.con.iterdump())
        self.assertNotIn(key, dump)
        self.assertIn(A._hash(key), dump)
        self.assertEqual(A.lookup(self.con, key)["id"], kid)

    def test_auth_bearer_x_api_key_wrong_revoked(self):
        kid, key = self.key()
        self.assertEqual(self.get("/api/v1/usage", key)[0], 200)
        self.assertEqual(A.handle("/api/v1/usage", {}, {"X-API-Key": key})[0], 200)
        self.assertEqual(self.get("/api/v1/usage", None)[0], 401)
        self.assertEqual(self.get("/api/v1/usage", key + "x")[0], 401)
        self.assertEqual(self.get("/api/v1/usage", "ms_" + key[4:])[0], 401)
        A.revoke(self.con, kid)
        self.assertEqual(self.get("/api/v1/usage", key)[0], 401)

    def test_removed_user_key_stops(self):
        _kid, key = self.key()
        with mock.patch("league.izbaceni.is_out", return_value=True):
            self.assertEqual(self.get("/api/v1/usage", key)[0], 401)

    def test_owner_mcp_key_is_not_an_api_key_and_back(self):
        _kid, key = self.key()
        os.environ["MCP_API_KEY"] = "ms_ownerkey"
        self.assertEqual(self.get("/api/v1/usage", "ms_ownerkey")[0], 401)
        from ui import mcpapi
        self.assertFalse(mcpapi.authorized("Bearer " + key))
        src = open(A.__file__, encoding="utf-8").read()
        self.assertNotIn("MCP_API_KEY\")", src)
        self.assertNotIn("mcpapi.key(", src)

    def test_plans_configurable(self):
        os.environ["JAVNIAPI_PLANS"] = json.dumps({"free": {"daily": 3}, "team": {"daily": 50, "fresh": True}})
        self.assertEqual(A.plans()["free"]["daily"], 3)
        self.assertTrue(A.plans()["team"]["fresh"])
        self.assertEqual(A.plans()["pro"]["daily"], 5000)
        with self.assertRaises(ValueError):
            A.create(self.con, "Ivan", "gold")
        with self.assertRaises(ValueError):
            A.create(self.con, "<b>", "free")


class Limits(Base):
    def test_daily_cap_429_until_utc_midnight_and_usage_counted(self):
        kid, key = self.key(cap=3)
        now = 1_800_000_000.0
        rows = [{"token": TOK, "symbol": "X", "kind": "social_call", "callers": 2, "first_seen_ts": int(now) - 600,
                 "market_cap_usd": 1e6, "risk": "low_risk"}]
        with mock.patch.object(A, "_delayed_signals", return_value=rows):
            for i in range(3):
                code, _out, hdr = self.get("/api/v1/signals", key, now=now + i * 20)
                self.assertEqual(code, 200)
                self.assertEqual(hdr["X-RateLimit-Remaining"], str(2 - i))
            code, out, hdr = self.get("/api/v1/signals", key, now=now + 100)
        self.assertEqual(code, 429)
        midnight = (int(now + 100) // 86400 + 1) * 86400
        self.assertEqual(int(hdr["Retry-After"]), midnight - int(now + 100))
        self.assertEqual(out["retry_after_s"], int(hdr["Retry-After"]))
        k = next(r for r in A.keys(self.con, now=now) if r["id"] == kid)
        self.assertEqual((k["today"], k["refused_today"], k["cap"]), (3, 1, 3))
        # the next UTC day starts again
        self.assertEqual(self.get("/api/v1/wallet/" + "x", key, now=midnight + 5)[0], 400)

    def test_burst_limit(self):
        _kid, key = self.key(plan="pro")
        now = 1_800_000_000.0
        with mock.patch.object(A, "wallet_result", return_value=(404, {"error": "wallet not known to us"})):
            codes = [self.get("/api/v1/wallet/" + WAL, key, now=now + i * 0.1)[0] for i in range(A.BURST_N + 1)]
            self.assertEqual(codes[:-1], [404] * A.BURST_N)
            self.assertEqual(codes[-1], 429)
            code, out, hdr = self.get("/api/v1/wallet/" + WAL, key, now=now + A.BURST_N * 0.1)
            self.assertEqual(code, 429)
            self.assertGreaterEqual(int(hdr["Retry-After"]), 1)
            self.assertLessEqual(int(hdr["Retry-After"]), A.BURST_S + 1)
            self.assertEqual(self.get("/api/v1/wallet/" + WAL, key, now=now + A.BURST_S + 1)[0], 404)

    def test_usage_endpoint_and_unknown_paths_are_not_counted(self):
        kid, key = self.key()
        for p in ("/api/v1/usage", "/api/v1/nope", "/api/v1/signals/x", "/api/v1/token/"):
            self.get(p, key)
        self.assertEqual(A.used_today(self.con, kid), 0)


class Canary(Base):
    ROWS = [{"token": t, "symbol": s, "kind": "social_call", "callers": 1, "first_seen_ts": 1_799_999_000 + i * 77,
             "market_cap_usd": 5e5, "risk": "low_risk"} for i, (t, s) in enumerate(((TOK, "A"), (TOK2, "B"),
                                                                                    (WAL, "C")))]

    def signals(self, key, now):
        with mock.patch.object(A, "_delayed_signals", return_value=[dict(r) for r in self.ROWS]):
            A.reset_cache()
            A.reset_burst()
            return self.get("/api/v1/signals", key, now=now)[1]["signals"]

    def test_deterministic_per_key_and_day_and_different_between_keys(self):
        _k1, key1 = self.key()
        _k2, key2 = self.key()
        now = 1_800_000_000.0
        a, b = self.signals(key1, now), self.signals(key1, now + 1500)
        self.assertEqual(a, b)                     # same key, same hour: the same answer
        later = self.signals(key1, now + 5 * 3600)   # same day: the same fake token, numbers and place
        self.assertEqual([r["token"] for r in later], [r["token"] for r in a])
        c = self.signals(key2, now)
        real = {r["token"] for r in self.ROWS}
        ca = [r for r in a if r["token"] not in real]
        cc = [r for r in c if r["token"] not in real]
        self.assertEqual(len(ca), 1)
        self.assertEqual(len(cc), 1)
        self.assertNotEqual(ca[0]["token"], cc[0]["token"])
        self.assertTrue(A.MINT.fullmatch(ca[0]["token"]))
        self.assertEqual(set(ca[0]), set(self.ROWS[0]))   # looks like any other row
        nd = self.signals(key1, now + 86400)
        self.assertNotIn(ca[0]["token"], {r["token"] for r in nd})   # a new canary each UTC day
        # the watermark moves timestamps by under a minute and differs between keys
        ta = {r["token"]: r["first_seen_ts"] for r in a if r["token"] in real}
        tc = {r["token"]: r["first_seen_ts"] for r in c if r["token"] in real}
        for r in self.ROWS:
            self.assertLess(abs(ta[r["token"]] - r["first_seen_ts"]), 60)
        self.assertNotEqual(ta, tc)

    def test_trace_names_the_key_from_canary_and_from_watermark_only(self):
        k1, key1 = self.key()
        k2, key2 = self.key()
        now = time.time()
        a = self.signals(key1, now)
        found = A.trace(self.con, json.dumps({"signals": a}), now=now)
        self.assertEqual(found[0]["key_id"], k1)
        self.assertEqual(len(found[0]["canaries"]), 1)
        self.assertNotIn(k2, [f["key_id"] for f in found if f["canaries"]])
        # the leaker deleted the fake row: the seconds watermark still points at key 1
        real = {r["token"] for r in self.ROWS}
        stripped = [r for r in a if r["token"] in real]
        found = A.trace(self.con, json.dumps(stripped), now=now)
        self.assertEqual([f["key_id"] for f in found][:1], [k1])
        self.assertEqual(found[0]["wm_match"], 3)
        self.assertEqual(A.trace(self.con, "nothing here " + TOK, now=now), [])

    def test_canary_never_stored_or_seen_by_our_own_reads(self):
        _k, key = self.key()
        now = time.time()
        a = self.signals(key, now)
        fake = [r["token"] for r in a if r["token"] not in {x["token"] for x in self.ROWS}][0]
        self.assertNotIn(fake, "\n".join(self.con.iterdump()))   # only the secret is stored, no row
        self.assertNotIn(fake, json.dumps(A._cache, default=str))  # the shared copy stays clean
        self.assertNotIn("canary_secret", json.dumps(a))
        for mod in ("ui/mcpapi.py", "ui/mcpdata.py", "ui/pages.py", "ui/public.py", "ui/pravitrade.py"):
            src = open(os.path.join(os.path.dirname(A.__file__), "..", mod), encoding="utf-8").read()
            self.assertNotIn("javniapi", src, mod)


class Results(Base):
    def test_token_result_plain_reasons_only(self):
        rows = [{"token": TOK, "market": {}, "rug_verdict": "risk", "rug_reasons": [
            "rug filter: VISOK RIZIK (score 71)", "top 10 drže 64 % supplyja (granica 50 %)", "RugCheck: mint ovlast"],
            "runup_x": 6.2, "runup_from": "kol.db first call"}]
        with mock.patch("ui.mcpapi._hygiene", return_value=([], rows)):
            code, out = A.token_result(TOK, fresh=False, market={"mcap": 1.2e6, "liq": 9e4, "ch_h1": 3.0, "ch_h24": -5})
        self.assertEqual(code, 200)
        self.assertEqual(out["risk"], "high_risk")
        self.assertTrue(out["late"])
        self.assertIn("supply held by few wallets", out["reasons"])
        self.assertIn("mint authority is still active", out["reasons"])
        self.assertNotIn("calls_last_hour", out)
        no_internal(self, out)
        self.assertEqual(A.token_result("nope", False)[0], 400)

    def test_wallet_result(self):
        w = {"wallet": WAL, "tier": "A", "labels": ["sniper", "x_internal"], "stats": {"median_hold_min": 1,
             "trades_per_day": 400, "bag_share": 0.1}, "rang": None, "score": 0.93, "copy_score": 3}
        code, out = A.wallet_result(WAL, w=w, row=None)
        self.assertEqual(code, 200)
        self.assertEqual(out["verdict"], "do_not_copy")
        self.assertFalse(out["copyable"])
        self.assertEqual(out["labels"], ["sniper"])
        self.assertEqual(out["grade"], "A")
        no_internal(self, out)
        w2 = dict(w, stats={"median_hold_min": 90, "trades_per_day": 3, "bag_share": 0}, labels=[],
                  rang={"copyable": 1, "proven": 1, "score": 9})
        code, out = A.wallet_result(WAL, w=w2, row={"passed": 1, "closed_before": 12})
        self.assertEqual((out["verdict"], out["copyable"], out["proven_twice"]), ("worth_copying", True, True))
        no_internal(self, out)
        with mock.patch("ui.data.wallet", return_value=None):
            self.assertEqual(A.wallet_result(WAL)[0], 404)

    def test_influencer_result_public_delay_and_no_bots(self):
        con = sqlite3.connect(os.environ["KOL_DB"])
        con.executescript("CREATE TABLE kols (handle TEXT, bot INTEGER, score REAL, stats TEXT, name TEXT, followers INT);"
                          "CREATE TABLE calls (ts INT, token TEXT, symbol TEXT, url TEXT, mcap0 REAL, r1h REAL, r24h REAL,"
                          " max24 REAL, handle TEXT, kind TEXT, bad INT, pre2h REAL, source TEXT);")
        con.execute("INSERT INTO kols VALUES ('alice', 0, 1, '{}', 'A', 10), ('robo', 1, 1, '{}', 'R', 1)")
        now = time.time()
        for i in range(12):
            con.execute("INSERT INTO calls VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (now - 3 * 86400 - i, f"T{i}", "S", "", 1e5, 0.1, -0.2, 0.3, "alice", "call", None, 0, "x"))
        con.execute("INSERT INTO calls VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (now - 60, "FRESH", "S", "", 1e5, 0.1, None, 0.3, "alice", "call", None, 0, "x"))
        con.commit()
        con.close()
        code, out = A.influencer_result("@Alice")
        self.assertEqual(code, 200)
        self.assertEqual(out["measured_calls"], 12)      # the fresh call is members-only (24 h delay)
        self.assertTrue(out["enough_data"])
        self.assertEqual(out["price_up_after_1h_share"], 1.0)
        no_internal(self, out)
        self.assertEqual(A.influencer_result("robo")[0], 404)
        self.assertEqual(A.influencer_result("nobody")[0], 404)

    def test_fresh_signals_map_kinds_and_drop_internal(self):
        sig = {"signals": [
            {"token": TOK, "symbol": "A", "source": "caller", "n_callers": 3, "first_call_ts": 1000,
             "market": {"market_cap_usd": 2e6}, "under_30k": False, "rug_verdict": "oprez", "beta_score": 0.9,
             "callers": [{"who": "secret_handle"}], "scan_via": "x"},
            {"token": TOK2, "symbol": "B", "source": "hidden_group", "market": {"market_cap_usd": 2e6}},
            {"token": WAL, "symbol": "C", "source": "scan", "scan_found_ts": 2000, "market": {"market_cap_usd": 1e4},
             "under_30k": True}]}
        with mock.patch("ui.mcpapi.signals", return_value=sig):
            rows = A._fresh_signals()
        self.assertEqual([(r["token"], r["kind"], r["risk"]) for r in rows], [(TOK, "social_call", "caution")])
        no_internal(self, rows)
        self.assertNotIn("secret_handle", json.dumps(rows))

    def test_whole_answers_have_no_internal_words(self):
        _k, key = self.key(plan="pro")
        with mock.patch.object(A, "_fresh_signals", return_value=Canary.ROWS):
            code, out, _h = self.get("/api/v1/signals", key)
        self.assertEqual(code, 200)
        self.assertFalse(out["delayed"])
        no_internal(self, out)
        code, out, _h = self.get("/api/v1/usage", key)
        no_internal(self, out)


class Http(unittest.TestCase):
    """Through run_ui: JSON 429 with Retry-After, noindex, the owner-only key page, the docs page for users."""

    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.old = (store.DB, settings.DB, dict(os.environ))
        store.DB, settings.DB = os.path.join(self.d, "league.db"), os.path.join(self.d, "trade.db")
        os.environ.update(DATA_DIR=self.d, UI_USERS="Ivan,Jure", UI_PASS_IVAN="ivanpw", UI_PASS_JURE="jurepw",
                          TRADE_OWNER="Jure", KOL_DB=os.path.join(self.d, "kol.db"))
        for k in ("UI_ADMINS", "SITE_URL", "APP_URL", "UI_PASSWORD", "MCP_API_KEY"):
            os.environ.pop(k, None)
        profiles.reset_cache()
        roles.reset_cache()
        A.reset_burst()
        import run_ui
        importlib.reload(run_ui)
        self.ui = run_ui
        self.srv = run_ui.ThreadingHTTPServer(("127.0.0.1", 0), run_ui.Handler)
        self.srv.verbose = False
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.srv.server_address[1]}"

        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *a):
                return None
        self.opener = urllib.request.build_opener(NoRedirect)

    def tearDown(self):
        self.srv.shutdown()
        self.srv.server_close()
        store.DB, settings.DB = self.old[0], self.old[1]
        os.environ.clear()
        os.environ.update(self.old[2])
        roles.reset_cache()

    def call(self, path, data=None, cookie="", headers=None):
        h = dict(headers or {})
        if cookie:
            h["Cookie"] = cookie
        if data is not None:
            h["Origin"] = self.base
            sess = cookie.split("=", 1)[1] if cookie else ""
            data = {**data, "_csrf": self.ui.csrf_token(sess)}
        req = urllib.request.Request(self.base + path, headers=h,
                                     data=urllib.parse.urlencode(data).encode() if data is not None else None)
        try:
            r = self.opener.open(req)
        except urllib.error.HTTPError as e:
            r = e
        return r.code, r.headers, r.read().decode("utf-8", "replace")

    def login(self, name, pw):
        code, hdr, _ = self.call("/prijava", {"name": name, "pw": pw, "next": "/"})
        self.assertEqual(code, 303)
        return hdr["Set-Cookie"].split(";")[0]

    def test_owner_makes_key_shown_once_then_429_with_retry_after(self):
        jure, ivan = self.login("Jure", "jurepw"), self.login("Ivan", "ivanpw")
        self.assertEqual(self.call("/api-kljucevi", cookie=ivan)[0], 403)
        self.assertEqual(self.call("/api-kljucevi/novi", {"owner": "Ivan", "plan": "free"}, cookie=ivan)[0], 403)
        self.assertEqual(self.call("/api-kljucevi")[0], 401)
        code, _h, body = self.call("/api-kljucevi/novi", {"owner": "Ivan", "plan": "free", "cap": "2"}, cookie=jure)
        self.assertEqual(code, 200)
        import re
        key = re.search(r"msk_[A-Za-z0-9_\-]+", body).group(0)
        code, _h, page = self.call("/api-kljucevi", cookie=jure)
        self.assertEqual(code, 200)
        self.assertNotIn(key, page)                                  # shown once only
        code, hdr, docs = self.call("/api", cookie=ivan)
        self.assertEqual(code, 200)
        self.assertIn("noindex", hdr["X-Robots-Tag"])
        self.assertIn("/api/v1/signals", docs)
        self.assertEqual(self.call("/api")[0], 401)                  # logged-in only
        auth = {"Authorization": "Bearer " + key}
        with mock.patch.object(A, "_delayed_signals", return_value=[]):
            for _ in range(2):
                code, hdr, out = self.call("/api/v1/signals", headers=auth)
                self.assertEqual(code, 200, out)
                self.assertEqual(hdr["Content-Type"].split(";")[0], "application/json")
                self.assertIn("noindex", hdr["X-Robots-Tag"])
            code, hdr, out = self.call("/api/v1/signals", headers=auth)
        self.assertEqual(code, 429)
        self.assertTrue(int(hdr["Retry-After"]) > 0)
        self.assertEqual(json.loads(out)["error"], "daily request cap reached")
        self.assertEqual(self.call("/api/v1/signals")[0], 401)
        self.assertEqual(self.call("/api/mcp/signals", headers=auth)[0], 404)   # the MCP stays its own (off here)
        self.assertEqual(self.call("/api/v1/signals", data={})[0], 405)
        _c, _h, page = self.call("/api-kljucevi", cookie=jure)
        self.assertIn("1 odbijeno", page)
        kid = re.search(r"Novi ključ #(\d+)", body).group(1)
        self.assertEqual(self.call("/api-kljucevi/opozovi", {"id": kid}, cookie=jure)[0], 303)
        self.assertEqual(self.call("/api/v1/usage", headers=auth)[0], 401)


if __name__ == "__main__":
    unittest.main()
