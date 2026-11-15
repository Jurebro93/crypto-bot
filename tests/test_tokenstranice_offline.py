"""Stranice tokena (tokenstranice/, ui/tokenstranica.py): pokrivenost iz midcap.db, slugovi, javna odgoda, zabranjeni
sadržaj, tanke stranice (noindex, izvan karte weba), zamrznute stranice, povratne informacije (strop, escape, vlasnik
skriva), strop AI troška, oznaka mišljenja, privatni blok, red u logu. Bez mreže."""
import importlib
import json
import os
import re
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

from league import store as lstore  # noqa: E402
from tokenstranice import misljenje, osvjezi, podaci, povratne, store as TS  # noqa: E402
from trade import settings  # noqa: E402
from ui import coins, public, tokenstranica  # noqa: E402

D = 86400
NOW = int(time.time())
A = "MidAaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaapump"      # a midcap with history, calls, holders, insiders
B = "ThinBbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbpump"      # a new midcap: 3 days of candles
C = "GoneCccccccccccccccccccccccccccccccccccccpump"      # will fall under 2M
E = "RuggEeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeepump"      # in the rug archive
F = "TinyFfffffffffffffffffffffffffffffffffffpump"      # a microcap that slipped in
G = "PengGggggggggggggggggggggggggggggggggggggpump"     # a midcap with the symbol of a top 100 coin
V = "VeliVvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvpump"     # only on the veliki list
P = "PengPppppppppppppppppppppppppppppppppppppppp"      # the top 100 coin PENG
W1 = "7xKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU"     # a holder's wallet: never on a public page
W2 = "9WzDXwBbmkg8ZTbNMqUxvQRAyrZzDsGYdLVL9zYtAWWM"     # an insider's wallet: never on a public page
SECRET = "sk-OVO-SE-NE-SMIJE-VIDJETI"


def bars(n, start, p0=0.01, step=0.0002, vol=200_000):
    out = []
    for i in range(n):
        c = p0 + step * ((i % 9) - 4) + step * i * 0.2
        out.append((start + i * D, c * 0.99, c * 1.12, c * 0.9, c, vol))
    return out


class Base(unittest.TestCase):
    ENV = ("MIDCAP_DB", "VELIKI_DB", "DUGO_DB", "KOL_DB", "HOLDERI_DB", "INSAJDERI_DB", "TOKENSTRANICE_DB", "MARKET_DB",
           "RENDER_EXTERNAL_URL", "APP_URL", "OPENAI_API_KEY", "TRADE_OWNER", "UI_ADMINS")

    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.old_env = {k: os.environ.get(k) for k in self.ENV}
        for k in self.ENV:
            os.environ.pop(k, None)
        j = lambda n: os.path.join(self.d, n)  # noqa: E731
        for k, n in (("MIDCAP_DB", "midcap.db"), ("VELIKI_DB", "veliki.db"), ("DUGO_DB", "dugo.db"), ("KOL_DB", "kol.db"),
                     ("HOLDERI_DB", "holderi.db"), ("INSAJDERI_DB", "insajderi.db"),
                     ("TOKENSTRANICE_DB", "tokenstranice.db"), ("MARKET_DB", "market.db")):
            os.environ[k] = j(n)
        os.environ["RENDER_EXTERNAL_URL"] = "https://example.com"
        self.old = (coins.DB, lstore.DB, settings.DB, misljenje.METER, misljenje.CALL, misljenje.DAY_USD)
        coins.DB, lstore.DB, settings.DB = j("public.db"), j("league.db"), j("trade.db")
        misljenje.METER, misljenje.CALL = False, None
        public._cache.clear()
        TS.reset_cache()
        povratne.reset()
        povratne._ENSURED.clear()
        self.arch = mock.patch("rugfilter.archive.blocked", lambda *a, **k: frozenset({E}))
        self.arch.start()
        self.paths = podaci.default_paths()
        self.fixtures()

    def tearDown(self):
        self.arch.stop()
        coins.DB, lstore.DB, settings.DB, misljenje.METER, misljenje.CALL, misljenje.DAY_USD = self.old
        for k, v in self.old_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        public._cache.clear()
        TS.reset_cache()

    # ---------- fixtures ----------
    def fixtures(self):
        from veliki import midcap, store as vstore
        mc = midcap.connect(os.environ["MIDCAP_DB"])
        toks = [(A, 1, "MIDA", 12e6, 600e3, 2e6, NOW - 120 * D, 1, None), (B, 2, "THIN", 3e6, 200e3, 500e3, NOW - 4 * D, 1, None),
                (C, 3, "GONE", 4e6, 300e3, 400e3, NOW - 60 * D, 1, None), (E, 4, "RUGG", 9e6, 300e3, 900e3, NOW - 90 * D, 1, None),
                (F, 5, "TINY", 5e5, 90e3, 100e3, NOW - 30 * D, 1, None), (G, 6, "PENG", 8e6, 400e3, 700e3, NOW - 80 * D, 1, None),
                ("UsdcHhhhhhhhhhhhhhhhhhhhhhhhhhhhhhhhhhhhhh", 7, "USDC", 50e6, 5e6, 9e6, NOW - 900 * D, 1, None)]
        for m, i, sym, mcap, liq, vol, created, member, why in toks:
            mc.execute("INSERT INTO tokens (mint, id, symbol, mcap, liq, vol24, created_ts, first_ts, last_ts, member, why) "
                       "VALUES (?,?,?,?,?,?,?,?,?,?,?)", (m, i, sym, mcap, liq, vol, created, NOW - 10 * D, NOW, member, why))
            for k in range(6):
                mc.execute("INSERT INTO snap (id, ts, px, mc, liq, v24, c24) VALUES (?,?,?,?,?,?,?)",
                           (i, NOW - k * 3 * 3600, 0.012, int(mcap), int(liq), int(vol), 4.5))
        for m, n in ((A, 60), (G, 40), (C, 30), (E, 40), (F, 40)):
            mc.executemany("INSERT INTO c1d VALUES (?,?,?,?,?,?,?)", [(m, *b) for b in bars(n, NOW // D * D - (n - 1) * D)])
        mc.executemany("INSERT INTO c1d VALUES (?,?,?,?,?,?,?)", [(B, *b) for b in bars(3, NOW // D * D - 2 * D)])
        mc.executemany("INSERT INTO c1h VALUES (?,?,?,?,?,?,?)",
                       [(A, NOW // 3600 * 3600 - k * 3600, 0.011, 0.0125, 0.0105, 0.0115 + 0.0005 * (k % 4), 9000)
                        for k in range(1, 49)])
        mc.execute("INSERT INTO safety VALUES (?,?,?,?,?,?,?,?,?,?)", (A, NOW - 3600, 18.5, 4321, 99.0, 2.0, 0.5, 0, 0,
                                                                     json.dumps(["Low amount of LP Providers"])))
        mc.commit()
        mc.close()
        vc = vstore.connect(os.environ["VELIKI_DB"])
        vc.executemany("INSERT INTO btc_d VALUES (?,?)", [(NOW // D * D - k * D, 90000 + 900 * ((k * 7) % 11)) for k in range(120)])
        vc.executemany("INSERT INTO btc_h VALUES (?,?)", [(NOW // 3600 * 3600 - k * 3600, 90000 + 50 * (k % 13)) for k in range(500)])
        vstore.kv_put(vc, "list", {"ts": NOW, "tokens": [{"mint": V, "symbol": "VELI", "mcap": 20e6, "liq": 900e3,
                                                          "vol24": 1.5e6, "created_ts": NOW - 200 * D}]})
        vc.executemany("INSERT INTO c1d VALUES (?,?,?,?,?,?,?)", [(V, *b) for b in bars(30, NOW // D * D - 29 * D)])
        vc.execute("INSERT INTO tokens (mint, symbol, name) VALUES (?,?,?)", (V, "VELI", "Veliki Coin"))
        vc.commit()
        vc.close()
        # public.db: the top 100 coin PENG
        coins.store([{"id": P, "symbol": "PENG", "name": "Pudgy Peng", "mcap": 500e6, "fdv": 500e6, "usdPrice": 0.03,
                      "liquidity": 3e6, "holderCount": 50_000, "audit": {"mintAuthorityDisabled": True,
                                                                        "freezeAuthorityDisabled": True},
                      "stats24h": {"priceChange": 2.0, "buyVolume": 1e6, "sellVolume": 1e6}}], now=NOW)
        # kol.db
        from kol import store as kstore
        kc = kstore.connect(os.environ["KOL_DB"])
        kc.execute("INSERT INTO kols (handle, name, followers, score, bot) VALUES ('botty', 'Bot', 10, 1, 1)")
        rows = [("1", "goodcaller", NOW - 3 * D, "https://x.com/goodcaller/status/123456789", None, 0.1, None, 0.12, 0.3, 0.5),
                ("2", "tg:alphachan", NOW - 4 * D, "https://t.me/alphachan/55", None, 0.0, None, -0.1, -0.2, 0.2),
                ("3", "freshcaller", NOW - 3600, "https://x.com/freshcaller/status/99999999", None, 0.0, None, None, None, None),
                ("4", "latecaller", NOW - 5 * D, "u", None, 1.5, None, 0.1, 0.1, 0.2),
                ("5", "biasedcaller", NOW - 5 * D, "u", "kol_win", 0.0, None, 0.1, 0.1, 0.9),
                ("6", f"w:{W1}", NOW - 5 * D, "u", None, 0.0, None, 0.1, 0.1, 0.9),
                ("7", "botty", NOW - 5 * D, "u", None, 0.0, None, 0.1, 0.1, 0.9),
                ("8", "badflag", NOW - 5 * D, "u", None, 0.0, "x", 0.1, 0.1, 0.9)]
        for tid, h, ts, url, src, pre, bad, r1, r24, mx in rows:
            kc.execute("INSERT INTO calls (tweet_id, token, handle, ts, url, kind, source, pre2h, bad, mcap0, r1h, r24h, max24) "
                       "VALUES (?,?,?,?,?,'call',?,?,?,?,?,?,?)", (tid, A, h, ts, url, src, pre, bad, 9e6, r1, r24, mx))
        kc.execute("INSERT INTO tokens (token, symbol, name) VALUES (?,?,?)", (A, "MIDA", "Mida Coin"))
        kc.commit()
        kc.close()
        # holderi.db
        from holderi import store as hstore
        hc = hstore.connect(os.environ["HOLDERI_DB"])
        hc.execute("INSERT INTO profile VALUES (?,?,?,?,?,?)", (A, NOW - 7200, "MIDA", 12e6, "rugcheck", json.dumps({
            "shares": {"lp": 10.0, "burn": 0, "exchange": 4.2, "team": 20.0, "insider": 15.5, "whale": 6.0, "normal": 8.0},
            "insider_ex": 35.5, "hhi": 900.0, "top10_ex": 44.0, "exchanges": {"binance": 3.2, "nepoznata": 1.0}, "n": 20})))
        hc.execute("INSERT INTO snap VALUES (?,?,?,?,?,?,?,?,?)", (A, NOW - 7200, 1, W1, W1, 1e6, 15.5, "insider", "x"))
        hstore.kv_put(hc, "lst:binance", {"ts": NOW, "symbols": ["MIDA"], "contracts": [A]})
        hstore.kv_put(hc, "lst:okx", {"ts": NOW, "symbols": ["OTHER"], "contracts": []})
        hc.execute("INSERT INTO signals (mint, symbol, ts, kind, exchange, score, reasons, px, px_24h, px_7d) VALUES "
                   "(?,?,?,?,?,?,?,?,?,?)", (A, "MIDA", NOW - 3 * D, "pre_listing", "okx", 72, "[]", 0.01, 0.012, 0.009))
        hc.execute("INSERT INTO signals (mint, symbol, ts, kind, exchange, score, reasons, px) VALUES (?,?,?,?,?,?,?,?)",
                   (A, "MIDA", NOW - 1800, "deposit_sell", "bybit", 40, json.dumps([W2]), 0.012))
        hc.commit()
        hc.close()
        # insajderi.db
        from insajderi import store as istore
        ic = istore.connect(os.environ["INSAJDERI_DB"])
        ic.execute("INSERT INTO i2_events (eid, kind, token, symbol, t0, peak_x) VALUES ('j:1','jump',?, 'MIDA', ?, 0.8)",
                   (A, NOW - 5 * D))
        ic.execute("INSERT INTO i2_events (eid, kind, token, symbol, t0, peak_x) VALUES ('j:2','jump',?, 'MIDA', ?, 0.4)",
                   (A, NOW - 600))
        for w, bb, so in ((W1, 1, 1), (W2, 1, 0), ("3" * 40, 0, 1)):
            ic.execute("INSERT INTO i2_part (eid, wallet, owner, bought_before, sold_into) VALUES ('j:1',?,?,?,?)", (w, w, bb, so))
        ic.execute("INSERT INTO i2_groups (owner, cls, confirmed_ts) VALUES (?, 'insajder', ?)", (W2, NOW - 9 * D))
        ic.execute("INSERT INTO i2_signals VALUES (?,?,?,?,?,?,?)", (A, NOW - 3 * D, 3, json.dumps([W1]), 9e6, 0.1, "tp"))
        ic.execute("INSERT INTO i2_signals VALUES (?,?,?,?,?,?,?)", (A, NOW - 600, 2, json.dumps([W2]), 9e6, None, None))
        ic.execute("INSERT INTO i2_smart (wallet, owner, last_buy_ts, last_token) VALUES (?,?,?,?)", (W1, W1, NOW - 900, A))
        ic.commit()
        ic.close()
        from dugo import store as dstore
        dc = dstore.connect(os.environ["DUGO_DB"])
        dc.executemany("INSERT INTO holders VALUES (?,?,?)", [(A, NOW // D * D - k * D, 4000 + 10 * k) for k in range(10)])
        dc.commit()
        dc.close()

    def refresh(self, now=NOW, ai=False):
        lines = []
        r = osvjezi.run(now=now, log=lines.append, paths=self.paths, ai=ai)
        public._cache.clear()
        TS.reset_cache()
        return r, lines

    def html(self, path):
        code, body, _ = public.route(path)
        return code, body.decode("utf-8")

    def rows(self):
        con = TS.ro()
        try:
            return {m: (s, a, e, w) for m, s, a, e, w in con.execute("SELECT mint, slug, active, enough, out_why FROM pages")}
        finally:
            con.close()


class Coverage(Base):
    def test_every_midcap_and_veliki_token_gets_a_page_no_microcaps_no_rugs(self):
        r, lines = self.refresh()
        pages = self.rows()
        for m in (A, B, C, G, V, P):
            self.assertIn(m, pages, m)
        for m in (E, F, "UsdcHhhhhhhhhhhhhhhhhhhhhhhhhhhhhhhhhhhhhh"):     # rug, microcap, not a meme
            self.assertNotIn(m, pages, m)
        self.assertEqual(len(lines), 1)
        self.assertTrue(lines[0].startswith("tokenstranice: sat: 6 stranica, mišljenja 0, trošak $0.000"), lines[0])

    def test_slugs_collision_safe_and_stable(self):
        self.refresh()
        pages = self.rows()
        self.assertEqual(pages[A][0], "mida")
        self.assertEqual(pages[P][0], "peng")                       # the top 100 coin keeps its own slug
        self.assertEqual(pages[G][0], "peng-peng")                  # a midcap with the same symbol: never "peng"
        self.assertEqual(pages[V][0], "veli")
        self.refresh(NOW + 3600)
        self.assertEqual(self.rows()[G][0], "peng-peng")            # stable
        # a new top 100 coin whose symbol is a token page's slug gets another one; the page's own mint reuses it
        coins.store([{"id": "OtherMidaMintxxxxxxxxxxxxxxxxxxxxxxxxxxxx", "symbol": "MIDA", "mcap": 400e6, "liquidity": 2e6},
                     {"id": A, "symbol": "MIDA", "mcap": 300e6, "liquidity": 2e6}], now=NOW)
        slugs = {r["mint"]: r["slug"] for r in coins.top()}
        self.assertEqual(slugs[A], "mida")
        self.assertNotEqual(slugs["OtherMidaMintxxxxxxxxxxxxxxxxxxxxxxxxxxxx"], "mida")

    def test_old_slug_keeps_working_with_canonical_to_the_new_one(self):
        self.refresh()
        con = sqlite3.connect(coins.DB)                             # the coin list gives G its own slug later
        con.execute("INSERT INTO coins (mint, slug, symbol, mcap) VALUES (?, 'pengish', 'PENG', 8e6)", (G,))
        con.commit()
        con.close()
        self.refresh(NOW + 3600)
        self.assertEqual(self.rows()[G][0], "pengish")
        code, html = self.html("/coin/peng-peng")                   # the old URL still answers
        self.assertEqual(code, 200)
        self.assertIn('rel=canonical href="https://example.com/coin/pengish"', html)
        self.assertIn("noindex", html)


class PublicPage(Base):
    def test_page_sections_and_public_delay(self):
        self.refresh()
        code, html = self.html("/coin/mida")
        self.assertEqual(code, 200)
        for s in ("Mida Coin (MIDA)", "Statistics", "Typical daily range", "What the numbers say", "Who called it",
                  "@goodcaller", "/influencer/goodcaller", "Telegram: alphachan", "/telegram/alphachan",
                  "https://x.com/goodcaller/status/123456789", "1 newer calls from the last 24 hours are for members",
                  "Holders", "Team + insiders", "Binance", "listed", "Listing signals (older than 24 hours)", "OKX",
                  "Insiders and smart money", "What members see on top", "Feedback", "<svg", "FAQPage",
                  'hreflang=hr', "Risks", "High team and insider share"):
            self.assertIn(s, html, s)
        for s in ("freshcaller", "latecaller", "biasedcaller", "botty", "badflag", f"w:{W1[:6]}", "Bybit"):
            self.assertNotIn(s, html, s)
        self.assertNotIn("noindex", html)
        hr = self.html("/hr/coin/mida")[1]
        for s in ("Tko ga je zvao", "Statistika", "Što kažu brojke", "Povratne informacije", "/hr/influencer/goodcaller",
                  "/hr/telegram/alphachan", "Tipičan dnevni raspon"):
            self.assertIn(s, hr, s)

    def test_no_forbidden_content(self):
        os.environ["OPENAI_API_KEY"] = SECRET
        self.refresh()
        for path in ("/coin/mida", "/hr/coin/mida", "/coin/thin", "/coin/peng"):
            html = self.html(path)[1]
            addrs = set(re.findall(r"[1-9A-HJ-NP-Za-km-z]{32,44}", html))
            self.assertLessEqual(addrs, {A, B, P}, path)            # only the token's own contract address
            for s in (W1, W2, SECRET, "OPENAI", "TOKENSTRANICE", "MIDCAP_DB", "midcap.db", "insajderi.db", "holderi.db",
                      "Traceback", "Error:", "cost_usd", "0.30 $", "$0.30", "gpt-5-mini cost", "api-key"):
                self.assertNotIn(s, html, (path, s))

    def test_thin_page_noindex_and_not_in_sitemap(self):
        self.refresh()
        code, html = self.html("/coin/thin")
        self.assertEqual(code, 200)
        self.assertIn('<meta name=robots content="noindex,follow">', html)
        self.assertIn("Too little data so far: 3 days of price history", html)
        self.assertNotIn("AI opinion, not financial advice", html)
        sm = public.sitemap()
        self.assertIn("/coin/mida<", sm)
        self.assertIn("/hr/coin/mida<", sm)
        self.assertNotIn("/coin/thin<", sm)
        self.assertEqual(sm.count("example.com/coin/peng</loc>"), 1)   # the top 100 coin is listed once
        self.assertEqual(self.html("/coin/nema-takvog")[0], 404)

    def test_frozen_page_keeps_working(self):
        self.refresh()
        con = sqlite3.connect(os.environ["MIDCAP_DB"])
        con.execute("UPDATE tokens SET member=0, out_since=?, why='MC $1.2M ispod $2M' WHERE mint=?", (NOW, C))
        con.commit()
        con.close()
        r, _ = self.refresh(NOW + 3600)
        self.assertEqual(r["frozen"], 1)
        self.assertEqual(self.rows()[C][1:4:2], (0, "mc_low"))
        code, html = self.html("/coin/gone")
        self.assertEqual(code, 200)
        self.assertIn("We no longer track this token: its market cap fell under $2M", html)
        self.assertIn("Ovaj token više ne pratimo", self.html("/hr/coin/gone")[1])

    def test_no_freezing_when_midcap_db_is_missing(self):
        self.refresh()
        os.remove(os.environ["MIDCAP_DB"])
        r, lines = self.refresh(NOW + 3600)
        self.assertEqual(r["frozen"], 0)
        self.assertTrue(all(a for _s, a, _e, _w in self.rows().values()))

    def test_top100_page_gets_the_new_sections(self):
        code, html = self.html("/coin/peng")
        self.assertNotIn("What the numbers say", html)              # before the first snapshot: as before
        self.refresh()
        code, html = self.html("/coin/peng")
        self.assertEqual(code, 200)
        for s in ("PENG price, market cap", "What the numbers say", "Feedback"):
            self.assertIn(s, html, s)


class Feedback(Base):
    def test_rate_limit_length_duplicate_escape_and_hide(self):
        self.refresh()
        con = povratne.connect()
        for i in range(povratne.RATE_N):
            povratne.add(con, A, "ana", f"poruka {i} <script>alert(1)</script> {W1}", NOW + i)
        with self.assertRaises(povratne.FbError) as e:
            povratne.add(con, A, "ana", "još jedna", NOW + 10)
        self.assertEqual(e.exception.code, "rate")
        for text, code in (("x" * 501, "long"), ("   ", "empty")):
            with self.assertRaises(povratne.FbError) as e:
                povratne.add(con, A, "ivo", text, NOW)
            self.assertEqual(e.exception.code, code)
        povratne.add(con, A, "ivo", "Isto", NOW)
        with self.assertRaises(povratne.FbError) as e:
            povratne.add(con, A, "ivo", "Isto", NOW + 1)
        self.assertEqual(e.exception.code, "dup")
        with self.assertRaises(povratne.FbError) as e:
            povratne.add(con, A, None, "gost", NOW)
        self.assertEqual(e.exception.code, "login")
        con.close()
        html = self.html("/coin/mida")[1]
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", html)
        self.assertNotIn("<script>alert(1)", html)
        self.assertNotIn(W1, html)
        self.assertIn("[adresa skrivena]", html)
        self.assertNotIn("/tokenstranica/poruka", html)              # guests read only
        self.assertIn("/token/" + A + "#povratne", html)             # the way in to write
        # only the owner hides
        con = povratne.connect()
        mid = con.execute("SELECT id FROM tp_fb WHERE user='ivo'").fetchone()[0]
        con.close()
        ok, code, _m = tokenstranica.fb_post("/tokenstranica/sakrij", {"id": str(mid), "m": A}, "ana")
        self.assertEqual((ok, code), (False, "no"))
        ok, code, _m = tokenstranica.fb_post("/tokenstranica/sakrij", {"id": str(mid), "m": A}, "Jure")
        self.assertTrue(ok, code)
        html = self.html("/coin/mida")[1]                              # the post dropped the cached copy
        self.assertNotIn("Isto", html)
        self.assertIn("Isto", tokenstranica.fb_fragment("Jure", A))  # the owner still sees it, marked
        self.assertIn("skriveno", tokenstranica.fb_fragment("Jure", A))
        self.assertNotIn("Isto", tokenstranica.fb_fragment("ana", A))

    def test_votes_toggle_and_unknown_tokens(self):
        self.refresh()
        for user, v, up, down in (("ana", "1", 1, 0), ("ana", "1", 0, 0), ("ana", "-1", 0, 1), ("ivo", "1", 1, 1)):
            ok, code, _m = tokenstranica.fb_post("/tokenstranica/glas", {"m": A, "v": v}, user)
            self.assertTrue(ok, code)
            con = povratne.connect()
            fb = povratne.read(con, A)
            con.close()
            self.assertEqual((fb["up"], fb["down"]), (up, down))
        self.assertIn("👍 1", self.html("/coin/mida")[1])
        ok, code, _m = tokenstranica.fb_post("/tokenstranica/poruka", {"m": E, "text": "rug?"}, "ana")
        self.assertEqual((ok, code), (False, "token"))
        ok, code, _m = tokenstranica.fb_post("/tokenstranica/poruka", {"m": A, "text": "hi"}, None)
        self.assertEqual((ok, code), (False, "login"))
        povratne.reset()
        con = povratne.connect()
        for _ in range(povratne.VOTE_N):
            povratne.vote(con, A, "brzi", 1)
        with self.assertRaises(povratne.FbError) as e:
            povratne.vote(con, A, "brzi", 1)
        con.close()
        self.assertEqual(e.exception.code, "votes")


class Opinions(Base):
    def fake(self, cost=0.002, text=None):
        calls = []

        def call(model, instr, user, schema, name, max_out, effort):
            calls.append(json.loads(user))
            self.assertEqual(model, "gpt-5-mini")
            self.assertNotIn(A, user)
            return {"data": {"opinion_en": text or "With a typical daily range of 12 % and 27 of 30 days above $50k, "
                                                   "the volume is steady, but insiders hold 35.5 %.",
                             "opinion_hr": text or "Uz tipičan dnevni raspon od 12 % i 27 od 30 dana iznad 50k $ "
                                                   "volumen je stalan, ali insajderi drže 35,5 %.",
                             "risks_en": ["High insider share"], "risks_hr": ["Visok udio insajdera"]},
                    "usage": {"in": 900, "out": 700}, "model": model, "cost_usd": cost}
        misljenje.CALL = call
        return calls

    def test_budget_cap_stops_and_label_is_on_the_page(self):
        self.refresh()
        calls = self.fake(cost=0.002)
        misljenje.DAY_USD = 0.005                                    # room for one call (each may cost ~0.003)
        con = TS.connect()
        res = misljenje.run_batch(con, NOW, batch=6)
        self.assertEqual(res["n"], 1)
        self.assertIn("dnevni strop", res["why"])
        self.assertEqual(len(calls), 1)
        res2 = misljenje.run_batch(con, NOW + 60, batch=6)            # the same day: nothing more
        self.assertEqual(res2["n"], 0)
        self.assertLessEqual(TS.spent(con, TS.day_start(NOW)), 0.005)
        mint = con.execute("SELECT mint FROM opinions").fetchone()[0]
        enough = {m for m, _s, a, e, _w in [(m, *v) for m, v in self.rows().items()] if e}
        self.assertIn(mint, enough)
        self.assertNotIn(B, {m for (m,) in con.execute("SELECT mint FROM ai_calls")})   # thin pages get none
        con.close()
        slug = self.rows()[mint][0]
        public._cache.clear()
        en, hr = self.html(f"/coin/{slug}")[1], self.html(f"/hr/coin/{slug}")[1]
        self.assertIn("AI opinion, not financial advice", en)
        self.assertIn("Mišljenje AI-ja, nije financijski savjet", hr)
        self.assertIn("typical daily range of 12 %", en)

    def test_at_most_daily_and_bad_answers_refused(self):
        self.refresh()
        misljenje.DAY_USD = 1.0
        calls = self.fake()
        con = TS.connect()
        n_enough = sum(1 for v in self.rows().values() if v[2])
        res = misljenje.run_batch(con, NOW, batch=50)
        self.assertEqual(res["n"], n_enough)
        self.assertEqual(misljenje.run_batch(con, NOW + 3600, batch=50)["n"], 0)    # at most once a day
        self.assertEqual(misljenje.run_batch(con, NOW + 86400 + 60, batch=50)["n"], n_enough)
        self.assertEqual(len(calls), 2 * n_enough)
        for bad in (f"Buy it at https://scam.example now, the wallet {W1} is loaded.", "Kupi odmah, ovo ide 100x!"):
            self.assertIsNone(misljenje.clean({"opinion_en": bad, "opinion_hr": bad, "risks_en": [], "risks_hr": []}))
        con.close()

    def test_without_key_or_cap_zero_no_call(self):
        self.refresh()
        con = TS.connect()
        self.assertEqual(misljenje.run_batch(con, NOW)["why"], "nema ključa")
        misljenje.DAY_USD = 0
        self.fake()
        self.assertIn("isključeno", misljenje.run_batch(con, NOW)["why"])
        con.close()

    def test_hourly_run_line_with_opinions(self):
        misljenje.DAY_USD = 1.0
        self.fake(cost=0.0015)
        r, lines = self.refresh(ai=True)
        self.assertRegex(lines[0], r"^tokenstranice: sat: 6 stranica, mišljenja [1-6], trošak \$0\.0\d\d ")


class Private(Base):
    def test_private_block_is_fresh_and_links_the_public_page(self):
        self.refresh()
        html = tokenstranica.private_html(A, {})
        for s in ("Stranica tokena", "/hr/coin/mida", "freshcaller", "goodcaller", "Pametni novčanici koji su ga kupili",
                  "Svježih listing signala (24 h): <b>1</b>", "Naša zona ulaza", "tp-fb", "/tokenstranica/povratne?m=" + A,
                  "translate=no"):
            self.assertIn(s, html, s)
        self.assertEqual(tokenstranica.private_html("nije-adresa", {}), "")
        self.assertEqual(tokenstranica.private_html(F, {}) .count("/hr/coin/"), 0)   # a microcap: no public page

    def test_interpretation_is_rule_based_in_both_languages(self):
        self.refresh()
        con = TS.ro()
        d = TS.page(con, mint=A)["data"]
        con.close()
        from tokenstranice import tumac
        en, hr = tumac.explain(d, "en"), tumac.explain(d, "hr")
        self.assertTrue(any("Market cap $12.0M" in x for x in en["lines"]), en["lines"])
        self.assertTrue(any("Tržišna vrijednost $12,0M" in x for x in hr["lines"]), hr["lines"])
        self.assertTrue(any("2 clean influencer and Telegram calls" in x for x in en["lines"]), en["lines"])
        self.assertIn("Meme coins are very risky: the price can fall to almost zero.", en["risks"])


class Schedule(unittest.TestCase):
    def test_hourly_low_priority_job_runs_under_fokus_midcap(self):
        import run_sched
        from ops import cpuguard, fokus
        job = [j for j in run_sched.JOBS if j[0] == "tokenstranice"]
        self.assertEqual(len(job), 1)
        self.assertEqual(job[0][2][0], ["run_tokenstranice.py", "sat"])
        self.assertTrue(job[0][2][2])                                   # light: no heavy lock
        self.assertIsNone(fokus.off_key(["python3", "run_tokenstranice.py", "sat"]))
        name, rank, _why = cpuguard.classify(["python3", "run_tokenstranice.py", "sat"])[:3]
        self.assertEqual((name, rank), ("tokenstranice", cpuguard.JOBS))


class Http(Base):
    """run_ui: the feedback box and its forms are for logged-in players, with the form token and a same-site Origin."""
    UI = ("UI_USERS", "UI_PASS_IVAN", "UI_PASS_JURE", "UI_PASSWORD", "DATA_DIR", "SITE_URL")

    def setUp(self):
        super().setUp()
        self.old_ui = {k: os.environ.get(k) for k in self.UI}
        os.environ.update(DATA_DIR=self.d, UI_USERS="Ivan,Jure", UI_PASS_IVAN="ivanpw", UI_PASS_JURE="jurepw",
                          UI_PASSWORD="shared")
        os.environ.pop("SITE_URL", None)
        from league import profiles, roles
        profiles.reset_cache()
        roles.reset_cache()
        self.refresh()
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
        for k, v in self.old_ui.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        importlib.reload(self.ui)
        super().tearDown()

    def call(self, path, data=None, cookie="", token=True, origin=True):
        headers = {"Cookie": cookie} if cookie else {}
        if data is not None:
            if origin:
                headers["Origin"] = self.base
            sess = cookie.split("=", 1)[1] if cookie.startswith(self.ui.COOKIE + "=") else ""
            if token:
                data = {**data, "_csrf": self.ui.csrf_token(sess)}
        req = urllib.request.Request(self.base + path, headers=headers,
                                     data=urllib.parse.urlencode(data).encode() if data is not None else None)
        try:
            r = self.opener.open(req)
        except urllib.error.HTTPError as e:
            r = e
        return r.code, r.headers, r.read().decode("utf-8", "replace")

    def test_feedback_routes(self):
        code, hdr, _ = self.call("/prijava", {"name": "Ivan", "pw": "ivanpw", "next": "/tokens"})
        self.assertEqual(code, 303)
        ivan = hdr["Set-Cookie"].split(";")[0]
        self.assertEqual(self.call(f"/tokenstranica/povratne?m={A}")[0], 401)          # guests: no box
        code, _h, body = self.call(f"/tokenstranica/povratne?m={A}", cookie=ivan)
        self.assertEqual(code, 200)
        self.assertIn("/tokenstranica/poruka", body)
        self.assertEqual(self.call("/tokenstranica/poruka", {"m": A, "text": "bez tokena"}, ivan, token=False)[0], 403)
        self.assertEqual(self.call("/tokenstranica/poruka", {"m": A, "text": "tuđi"}, ivan, origin=False)[0], 403)
        code, _h, body = self.call("/tokenstranica/poruka", {"m": A, "text": "Zanimljiv <b>token</b>", "ajax": "1"}, ivan)
        self.assertEqual(code, 200)
        self.assertIn("Zanimljiv &lt;b&gt;token&lt;/b&gt;", body)
        code, hdr, _ = self.call("/tokenstranica/glas", {"m": A, "v": "1"}, ivan)
        self.assertEqual((code, hdr["Location"]), (303, f"/token/{A}#povratne"))
        code, hdr, _ = self.call("/tokenstranica/poruka", {"m": A, "text": "x" * 600}, ivan)
        self.assertEqual(hdr["Location"], f"/token/{A}?e=long#povratne")
        code, _h, body = self.call("/coin/mida")
        self.assertEqual(code, 200)
        self.assertIn("Zanimljiv &lt;b&gt;token&lt;/b&gt;", body)
        self.assertIn("👍 1", body)


if __name__ == "__main__":
    unittest.main()
