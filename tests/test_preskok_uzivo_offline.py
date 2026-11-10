"""10.11. (Jure): "u tablici (pop-up preskočenog tokena) treba biti koliko je taj token u tom momentu bio vrijedan; to
treba dobiti prioritet u mjerenju, real-time podaci", "iz pop-up prozora fali link na objavu gdje je korisnik zvao".

- league/copy._log keeps the MC a skip saw (copy_mc), so the pop-up has it before any candle is measured
- ui/pravitrade._skip_ctx: the follow and the MC of a copy-stage skip (copy_mc) or a real-money skip (demo entry)
- ui/pravitrade._call_post: the X post (kol.db calls.url, mcap0), the Telegram post, the wallet's buy on Solscan
- ui/pravitrade.sample_skips: our own live samples at the decision and +5/+10/+15 min after the call
- the pop-up shows them, and the link to the post

    python3 -m unittest tests.test_preskok_uzivo_offline
"""
import os
import sqlite3
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from league import copy, store  # noqa: E402
from trade import executor, settings  # noqa: E402

MINT = "Hope" + "x" * 36 + "pump"
NOW = 1_794_310_000


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = self.tmp.name
        self._saved = (settings.DB, store.DB, {k: os.environ.get(k) for k in ("KOL_DB", "TG_DB", "HYPE_DB", "TRADE_OWNER")})
        store.DB = os.path.join(d, "league.db")
        settings.DB = os.path.join(d, "trade.db")
        os.environ.update(KOL_DB=os.path.join(d, "kol.db"), TG_DB=os.path.join(d, "tg.db"),
                          HYPE_DB=os.path.join(d, "hype.db"), TRADE_OWNER="Jure")
        self.con = executor.connect(settings.DB)
        self.lg = store.connect(store.DB)
        copy.ensure(self.lg)
        k = sqlite3.connect(os.environ["KOL_DB"])
        k.execute("CREATE TABLE calls (tweet_id TEXT, token TEXT, handle TEXT, ts INTEGER, url TEXT, mcap0 REAL, kind TEXT)")
        k.execute("INSERT INTO calls VALUES ('1', ?, '0xMarko77', ?, 'https://x.com/0xMarko77/status/1', 41000, 'call')",
                  (MINT, NOW - 300))
        k.commit()
        k.close()
        t = sqlite3.connect(os.environ["TG_DB"])
        t.execute("CREATE TABLE posts (channel TEXT, post INTEGER, ts INTEGER, cas TEXT, fwd_from TEXT)")
        t.execute("INSERT INTO posts VALUES ('alpha', 77, ?, ?, NULL)", (NOW - 290, MINT))
        t.commit()
        t.close()
        h = sqlite3.connect(os.environ["HYPE_DB"])
        h.execute("CREATE TABLE chain_trades (sig TEXT, wallet TEXT, mint TEXT, side TEXT, ts INTEGER, sol REAL)")
        h.execute("INSERT INTO chain_trades VALUES ('5sig', ?, ?, 'buy', ?, 1.0)", ("W" * 44, MINT, NOW - 280))
        h.commit()
        h.close()
        self.fk = copy.follow(self.lg, settings.LEAGUE_USER, "kol", "0xMarko77", "0xMarko77", 25, 5, "tpsl", "15%", "")

    def tearDown(self):
        settings.DB, store.DB, env = self._saved
        for k, v in env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        self.con.close()
        self.lg.close()
        self.tmp.cleanup()


class DecisionMarketCap(Base):
    def test_copy_skip_keeps_the_mc_it_saw_and_the_popup_context_finds_it(self):
        from ui import pravitrade
        f = {"id": self.fk}
        copy._log(self.lg, f, MINT, "buy", NOW - 300, NOW - 280, "preskočeno", "praćenje bez dokaza", "Hope", mcap=52_000)
        self.lg.commit()
        ctx = pravitrade._skip_ctx(self.con, {"id": f"c{self.fk}:{MINT}:buy"}, MINT, NOW - 280)
        self.assertEqual((ctx["kind"], ctx["target"], ctx["mc_seen"]), ("kol", "0xMarko77", 52_000))

    def test_real_money_skip_takes_the_demo_entry_mc_and_the_call_time(self):
        from ui import pravitrade
        tid = store.buy(self.lg, settings.LEAGUE_USER, MINT, "Hope", 25, 1.0, 1e6, "copy KOL 0xMarko77", None, 61_000)
        self.lg.execute("UPDATE trades SET follow_id=? WHERE id=?", (self.fk, tid))
        self.lg.execute("INSERT INTO copy_log VALUES (?,?,?,?,?,?,?,?,?)",
                        (self.fk, MINT, "buy", NOW - 300, NOW - 298, "Hope", "ulaz", "kupljeno", tid))
        self.lg.commit()
        self.con.execute("INSERT INTO positions (league_id, token, opened_ts, mode, status, reason) VALUES (?,?,?,?,?,?)",
                         (tid, MINT, NOW - 297, "live", "blocked", "praćenje bez dokaza u demu"))
        self.con.commit()
        ctx = pravitrade._skip_ctx(self.con, {"id": "p1"}, MINT, NOW - 297)
        self.assertEqual((ctx["mc_seen"], ctx["ev_ts"], ctx["target"]), (61_000, NOW - 300, "0xMarko77"))


class PostLink(Base):
    def test_x_telegram_and_wallet_links(self):
        from ui import pravitrade
        url, words, mc = pravitrade._call_post("kol", "0xMarko77", MINT, NOW - 290)
        self.assertEqual((url, mc), ("https://x.com/0xMarko77/status/1", 41000))
        self.assertIn("X-u", words)
        url, words, _ = pravitrade._call_post("kol", "tg:alpha", MINT, NOW - 290)
        self.assertEqual(url, "https://t.me/alpha/77")
        url, _, _ = pravitrade._call_post("ekipa", "nobody,tg:alpha", MINT, NOW - 290)
        self.assertEqual(url, "https://t.me/alpha/77")
        url, words, _ = pravitrade._call_post("wallet", "W" * 44, MINT, NOW - 280)
        self.assertEqual(url, "https://solscan.io/tx/5sig")
        url, words, _ = pravitrade._call_post("kol", "netko", MINT, NOW - 290)   # not stored: the account at least
        self.assertEqual(url, "https://x.com/netko")
        self.assertEqual(pravitrade._call_post(None, None, MINT, NOW), (None, None, None))


class LiveSamples(Base):
    def test_samples_at_the_decision_and_after_5_10_15_min_of_the_call(self):
        from ui import pravitrade
        call, t = NOW - 300, NOW - 280
        copy._log(self.lg, {"id": self.fk}, MINT, "buy", call, t, "preskočeno", "DexScreener ima par, ali bez cijene", "Hope")
        copy._log(self.lg, {"id": self.fk}, "Tiny" + "y" * 40, "buy", call, t, "preskočeno", "MC $21,000 ispod 30k", "T")
        self.lg.commit()
        asked = []

        def live(toks):
            asked.append(list(toks))
            return {tk: {"price": 0.0001, "mcap": 60_000.0} for tk in toks}
        self.assertEqual(pravitrade.sample_skips(self.con, now=t + 1, live_fn=live), 1)      # k=0, under 30k never
        self.assertEqual(asked, [[MINT]])
        self.assertEqual(pravitrade.sample_skips(self.con, now=t + 2, live_fn=live), 0)      # nothing twice
        self.assertEqual(pravitrade.sample_skips(self.con, now=call + 5 * 60 + 3, live_fn=live), 1)
        self.assertEqual(pravitrade.sample_skips(self.con, now=call + 10 * 60 + 200, live_fn=live), 0)   # too late
        got = pravitrade._skip_samples(self.con, MINT, t)
        self.assertEqual(sorted(got), [0, 5])
        self.assertEqual(got[5][1], 60_000.0)


class Popup(Base):
    def test_popup_shows_call_mc_decision_mc_samples_and_the_post_link(self):
        from ui import pravitrade
        call, t = NOW - 300, NOW - 280
        copy._log(self.lg, {"id": self.fk}, MINT, "buy", call, t, "preskočeno", "praćenje bez dokaza", "Hope", mcap=52_000)
        self.lg.commit()
        pravitrade.sample_skips(self.con, now=call + 5 * 60 + 2,
                                live_fn=lambda toks: {tk: {"price": 1.0, "mcap": 63_000.0} for tk in toks})
        e = {"id": f"c{self.fk}:{MINT}:buy", "token": MINT, "ts": t, "sig_ts": call, "symbol": "Hope",
             "source": "KOL 0xMarko77", "kind": "preskocio", "why": "praćenje bez dokaza"}
        saved = (pravitrade._skip_decision, pravitrade._live_quote, pravitrade._bg_start, pravitrade._skip_paths)
        pravitrade._skip_decision = lambda *a: e
        pravitrade._live_quote = lambda m, now: ({"price": 1.2, "mcap": 80_000.0}, now - 1)
        pravitrade._bg_start = lambda: None
        pravitrade._skip_paths = lambda keys: {}
        try:
            html = pravitrade.skip_popup("Jure", MINT, t, now=call + 6 * 60)
        finally:
            (pravitrade._skip_decision, pravitrade._live_quote, pravitrade._bg_start, pravitrade._skip_paths) = saved
        self.assertIn("41k $", html.replace("\xa0", " "))                    # MC at the post (kol.db mcap0)
        self.assertIn("52k $", html.replace("\xa0", " "))                    # MC the decision saw
        self.assertIn("<td>+5 min</td>", html)                                 # our live sample
        self.assertIn("63k $", html.replace("\xa0", " "))
        self.assertIn('href="https://x.com/0xMarko77/status/1"', html)
        self.assertIn("Objava @0xMarko77 na X-u", html)
        guest = None
        pravitrade._skip_decision = lambda *a: e
        pravitrade._live_quote = lambda m, now: (None, None)
        pravitrade._bg_start = lambda: None
        pravitrade._skip_paths = lambda keys: {}
        try:
            settings.put(self.con, "invited", ["gost"], "Jure")
            guest = pravitrade.skip_popup("gost", MINT, t, now=call + 6 * 60)
        finally:
            (pravitrade._skip_decision, pravitrade._live_quote, pravitrade._bg_start, pravitrade._skip_paths) = saved
        self.assertNotIn("x.com/0xMarko77/status", guest)                      # the link is the owner's


if __name__ == "__main__":
    unittest.main()
