"""Site log (ui/sitelog.py): live_days, what a night added compared with the night before, the marker the web process
watches; the daily data blocks of the blog (ui/bloglive.py); the landing block "MemeSonar je live N dana" with and
without data, its internal links, and the guarded Autopilot strip. No network, temp databases only."""
import datetime as dt
import json
import os
import re
import sqlite3
import sys
import tempfile
import time
import types
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ui import blog, bloglive, coins, landing, public, sitelog  # noqa: E402

ENV = ("KOL_DB", "WALLET_DB", "TG_DB", "HYPE_DB", "SITE_LIVE_SINCE", "RENDER_EXTERNAL_URL")
UTC = dt.timezone.utc


def ts(y, m, d, hh=12, mm=0):
    return dt.datetime(y, m, d, hh, mm, tzinfo=UTC).timestamp()


def seed(d, kols=4, wallets=30, trades=200, channels=5, tokens=50, rugs=7):
    """Small real-schema databases in directory d; calling it again with bigger numbers adds rows."""
    from kol import store as kstore
    from tg import store as tstore
    from wallets import store as wstore
    old = int(time.time()) - 5 * 86400
    con = kstore.connect(os.path.join(d, "kol.db"))
    for i in range(kols):
        con.execute("INSERT OR REPLACE INTO kols (handle, name, followers, score, stats, bot) VALUES (?,?,?,?,?,0)",
                    (f"caller{i}", f"C{i}", 5000, 50, json.dumps({"measured": 12})))
        for j in range(12):
            con.execute("INSERT OR REPLACE INTO calls (tweet_id, token, handle, ts, kind, symbol, mcap0, pre2h, r1h, r24h, "
                        "max24, source) VALUES (?,?,?,?,'call','X',50000,0.1,0.2,-0.3,0.6,'timeline')",
                        (f"x{i}-{j}", f"T{j}", f"caller{i}", old - j * 3600))
    con.execute("INSERT OR REPLACE INTO kols (handle, name, followers, score, stats, bot) VALUES ('tg:alpha','A',900,40,'{}',0)")
    for j in range(11):
        con.execute("INSERT OR REPLACE INTO calls (tweet_id, token, handle, ts, kind, symbol, mcap0, pre2h, r1h, r24h, max24, "
                    "source) VALUES (?,?,'tg:alpha',?,'call','X',50000,0.1,0.2,-0.3,0.6,'tg')", (f"tg{j}", f"T{j}", old - j))
    con.execute("INSERT OR REPLACE INTO calls (tweet_id, token, handle, ts, kind) VALUES ('unmeasured','T','caller0',?,'call')",
                (old,))
    con.execute("INSERT OR REPLACE INTO kol_wallets (wallet, label) VALUES ('KW1','kol')")
    con.commit()
    con.close()
    con = wstore.connect(os.path.join(d, "wallets.db"))
    for i in range(wallets):
        con.execute("INSERT OR REPLACE INTO wallets (wallet, scored_at) VALUES (?,?)", (f"W{i}", old if i % 2 else None))
    for i in range(trades):
        con.execute("INSERT OR REPLACE INTO wallet_trades (wallet, sig, ts, mint) VALUES ('W0',?,?,'M')", (f"s{i}", old))
    con.commit()
    con.close()
    con = tstore.connect(os.path.join(d, "tg.db"))
    for i in range(channels):
        con.execute("INSERT OR REPLACE INTO channels (name, status) VALUES (?, 'active')", (f"ch{i}",))
    con.execute("INSERT OR REPLACE INTO channels (name, status) VALUES ('kandidat', 'candidate')")
    con.commit()
    con.close()
    con = sqlite3.connect(os.path.join(d, "hype.db"))
    con.executescript("CREATE TABLE IF NOT EXISTS token_tier (token TEXT PRIMARY KEY);"
                      "CREATE TABLE IF NOT EXISTS rug_archive (token TEXT PRIMARY KEY);")
    con.executemany("INSERT OR REPLACE INTO token_tier VALUES (?)", [(f"t{i}",) for i in range(tokens)])
    con.executemany("INSERT OR REPLACE INTO rug_archive VALUES (?)", [(f"r{i}",) for i in range(rugs)])
    con.commit()
    con.close()


class Base(unittest.TestCase):
    """Every test gets its own directory of databases; module state other tests rely on is put back."""

    def setUp(self):
        self.d = tempfile.mkdtemp()
        self._env = {k: os.environ.get(k) for k in ENV}
        for env, name in (("KOL_DB", "kol.db"), ("WALLET_DB", "wallets.db"), ("TG_DB", "tg.db"), ("HYPE_DB", "hype.db")):
            os.environ[env] = os.path.join(self.d, name)
        os.environ.pop("SITE_LIVE_SINCE", None)
        os.environ["RENDER_EXTERNAL_URL"] = "https://example.com"
        self._coins_db, self._stats = coins.DB, dict(landing._STATS)
        coins.DB = os.path.join(self.d, "public.db")
        sitelog.DB = None
        sitelog._SEEN.update(init=False, m=None)
        public._cache.clear()

    def tearDown(self):
        for k, v in self._env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        coins.DB = self._coins_db
        landing._STATS.clear()
        landing._STATS.update(self._stats)
        sitelog._SEEN.update(init=False, m=None)
        public._cache.clear()


class LiveDays(Base):
    def test_start_date_is_the_documented_launch_day_and_env_overrides_it(self):
        self.assertEqual(sitelog.start_date(), dt.date(2026, 11, 1))
        os.environ["SITE_LIVE_SINCE"] = "2026-09-24"
        self.assertEqual(sitelog.start_date(), dt.date(2026, 9, 24))
        self.assertEqual(sitelog.live_days(ts(2026, 11, 10)), 47)          # Jure's "live 47 dana"
        os.environ["SITE_LIVE_SINCE"] = "jučer"                              # unreadable: the constant, not a crash
        self.assertEqual(sitelog.start_date(), dt.date(2026, 11, 1))

    def test_days_follow_the_zagreb_calendar_and_never_go_negative(self):
        self.assertEqual(sitelog.live_days(ts(2026, 11, 10)), 9)
        self.assertEqual(sitelog.live_days(ts(2026, 11, 9, 22, 59)), 8)     # 23:59 in Zagreb on the 9th
        self.assertEqual(sitelog.live_days(ts(2026, 11, 9, 23, 0)), 9)      # midnight in Zagreb: the 10th
        self.assertEqual(sitelog.live_days(ts(2026, 11, 1)), 0)
        self.assertEqual(sitelog.live_days(ts(2026, 10, 1)), 0)
        self.assertEqual(sitelog.local_day(ts(2026, 7, 1, 22, 30)), "2026-07-02")   # summer time: UTC+2
        self.assertEqual(sitelog.live_days(dt.datetime(2026, 11, 3, 8, tzinfo=UTC)), 2)   # a datetime works too


class Counting(Base):
    def test_counts_come_from_our_databases_and_missing_ones_are_left_out(self):
        self.assertEqual(sitelog.counts(), {"kols": 0})                     # nothing there yet: no crash, no guesses
        seed(self.d)
        coins.connect().close()
        c = sitelog.counts()
        self.assertEqual(c, {"kols": 4, "calls": 4 * 12 + 11, "channels": 5, "wallets": 30, "trades": 200, "coins": 0,
                             "tokens": 57})
        self.assertEqual(c["kols"], len(public.influencers()))              # the public leaderboard, row for row

    def test_diff_shows_only_growth_of_things_counted_on_both_days(self):
        prev = {"kols": 10, "calls": 100, "wallets": 50, "trades": 900}
        cur = {"kols": 12, "calls": 100, "wallets": 45, "trades": 1000, "coins": 100}
        self.assertEqual(sitelog.diff(prev, cur), {"kols": 2, "trades": 100})   # same, fallen and new keys are not news
        self.assertEqual(list(sitelog.diff({k: 0 for k in sitelog.KEYS}, {k: 1 for k in sitelog.KEYS})), list(sitelog.KEYS))


class Recording(Base):
    def test_first_day_has_no_diff_and_lists_last_weeks_posts(self):
        e = sitelog.record(ts(2026, 11, 10, 1, 5), blogs=["what-is-copy-trading", "best-crypto-telegram-channels"],
                           counted={"kols": 10, "calls": 100})
        self.assertEqual((e["day"], e["added"], e["first"]), ("2026-11-10", {}, True))
        self.assertEqual(len(e["posts"]), 5)                                 # the five posts dated 9.11.
        self.assertIn("best-crypto-telegram-channels", e["posts"])
        self.assertEqual(e["blogs"], ["what-is-copy-trading"])              # a new post is "new", not "refreshed"
        self.assertEqual(sitelog.recent(3)[0]["counts"], {"kols": 10, "calls": 100})

    def test_next_day_stores_what_was_added_and_a_rerun_changes_nothing(self):
        sitelog.record(ts(2026, 11, 10, 1, 5), counted={"kols": 10, "calls": 100, "wallets": 50})
        e = sitelog.record(ts(2026, 11, 11, 1, 5), blogs=["what-is-copy-trading"],
                           counted={"kols": 13, "calls": 140, "wallets": 50})
        self.assertEqual((e["added"], e["posts"], e["blogs"], e["first"]),
                         ({"kols": 3, "calls": 40}, [], ["what-is-copy-trading"], False))
        again = sitelog.record(ts(2026, 11, 11, 9, 0), blogs=[], counted={"kols": 14, "calls": 140, "wallets": 50})
        self.assertEqual(again["added"], {"kols": 4, "calls": 40})           # still compared with the 10th, not with 01:05
        self.assertEqual(again["blogs"], ["what-is-copy-trading"])          # what the night's run listed is kept
        rows = sitelog.recent(5)
        self.assertEqual([r["day"] for r in rows], ["2026-11-11", "2026-11-10"])   # one row a day, newest first
        self.assertEqual(sitelog.today(ts(2026, 11, 11, 15))["added"], {"kols": 4, "calls": 40})
        self.assertIsNone(sitelog.today(ts(2026, 11, 12, 0, 30)))            # 01:30 on the 12th: tonight's run not yet
        self.assertTrue(sitelog.has_news(rows[0]))
        self.assertFalse(sitelog.has_news({"added": {}, "blogs": [], "posts": []}))

    def test_a_post_deployed_after_the_nights_run_is_named_the_next_night_and_only_once(self):
        # 10.11.: with "dated after the previous row" a post dated the 11th that arrived by a deploy after the 02:00
        # run on the 11th fell between the rows of the 11th and the 12th and was never named
        posts = [{"slug": "old-post", "date": "2026-11-01"}]
        with mock.patch.object(blog, "_posts", side_effect=lambda: list(posts)):
            sitelog.record(ts(2026, 11, 10, 1, 5), counted={"kols": 1})
            self.assertEqual(sitelog.record(ts(2026, 11, 11, 1, 5), counted={"kols": 1})["posts"], [])
            posts.append({"slug": "late-post", "date": "2026-11-11"})          # the 14:00 deploy on the 11th
            self.assertEqual(sitelog.record(ts(2026, 11, 12, 1, 5), counted={"kols": 1})["posts"], ["late-post"])
            self.assertEqual(sitelog.record(ts(2026, 11, 12, 9, 0), counted={"kols": 1})["posts"], ["late-post"])  # rerun
            self.assertEqual(sitelog.record(ts(2026, 11, 13, 1, 5), counted={"kols": 1})["posts"], [])   # named once
            posts.append({"slug": "future-post", "date": "2026-11-20"})        # written ahead: not before its day
            posts.append({"slug": "backdated", "date": "2026-10-01"})          # older than a week: not news
            self.assertEqual(sitelog.record(ts(2026, 11, 14, 1, 5), counted={"kols": 1})["posts"], [])

    def test_reading_before_the_first_run_is_empty_not_an_error(self):
        self.assertEqual(sitelog.recent(5), [])                              # no file
        self.assertIsNone(sitelog.today())
        self.assertIsNone(sitelog.marker())
        coins.connect().close()                                              # file without the table
        self.assertEqual(sitelog.recent(5), [])
        self.assertIsNone(sitelog.marker())

    def test_old_rows_are_dropped(self):
        sitelog.record(ts(2025, 1, 1), counted={"kols": 1})
        sitelog.record(ts(2026, 11, 10), counted={"kols": 2})
        self.assertEqual([r["day"] for r in sitelog.recent(9)], ["2026-11-10"])


class Marker(Base):
    def test_a_new_refresh_drops_the_copies_exactly_once(self):
        calls = []
        sitelog.record(ts(2026, 11, 9, 1, 5), counted={"kols": 1})
        self.assertFalse(sitelog.check(lambda: calls.append(1)))            # first look: only remembers the marker
        self.assertFalse(sitelog.check(lambda: calls.append(1)))            # nothing happened since
        sitelog.record(ts(2026, 11, 10, 1, 5), counted={"kols": 2})         # the night's job, in another process
        with mock.patch("builtins.print"):
            self.assertTrue(sitelog.check(lambda: calls.append(1)))
            self.assertFalse(sitelog.check(lambda: calls.append(1)))        # the same refresh is not acted on twice
            self.assertEqual(calls, [1])
            sitelog.record(ts(2026, 11, 10, 9, 0), counted={"kols": 3})     # run again by hand the same day
            self.assertTrue(sitelog.check(lambda: calls.append(1)))
        self.assertEqual(calls, [1, 1])

    def test_first_refresh_ever_is_seen_and_a_broken_callback_is_survived(self):
        calls = []
        self.assertFalse(sitelog.check(lambda: calls.append(1)))            # process started before any row existed
        sitelog.record(ts(2026, 11, 10, 1, 5), counted={"kols": 2})
        with mock.patch("builtins.print") as pr:
            self.assertTrue(sitelog.check(lambda: 1 / 0))                   # the pages keep their own cache times
            self.assertIn("ZeroDivisionError", " ".join(str(c) for c in pr.call_args_list))
            with mock.patch.object(sitelog, "marker", return_value=None):  # database busy: nothing is concluded
                self.assertFalse(sitelog.check(lambda: calls.append(1)))
            self.assertFalse(sitelog.check(lambda: calls.append(1)))
        self.assertEqual(calls, [])

    def test_watch_starts_one_thread_only(self):
        started = []
        with mock.patch.object(sitelog.threading, "Thread") as th, mock.patch.object(sitelog, "_WATCHING", []):
            th.return_value.start.side_effect = lambda: started.append(1)
            sitelog.watch(lambda: None)
            sitelog.watch(lambda: None)
        self.assertEqual(started, [1])


class BlogLive(Base):
    def test_measure_counts_each_block_from_our_databases(self):
        seed(self.d)
        m = bloglive.measure()
        self.assertEqual(m["kol"], {"x_accounts": 4, "x_measured": 48, "board": 4, "x_clean10": 4})
        self.assertEqual(m["telegram"], {"tg_channels": 5, "tg_measured": 11, "tg_clean10": 1})
        self.assertEqual(m["wallets"], {"wallets": 30, "scored": 15, "trades": 200, "kol_wallets": 1})
        self.assertEqual(m["rugs"], {"tokens": 57, "rugs": 7})

    def test_refresh_reports_only_posts_whose_numbers_changed(self):
        m = {"kol": {"x_accounts": 10, "x_measured": 100}, "wallets": {"wallets": 30, "trades": 200},
             "rugs": {"tokens": 50}}                                          # one number is not a block
        first = bloglive.refresh(ts(2026, 11, 10, 1, 5), measured=m)
        self.assertEqual(set(first), {s for s, k in bloglive.BLOCK_OF.items() if k in ("kol", "wallets")})
        self.assertEqual(bloglive.refresh(ts(2026, 11, 11, 1, 5), measured=m), [])     # same numbers: nothing refreshed
        self.assertEqual(bloglive.modified("what-is-copy-trading"), "2026-11-10")
        m["wallets"] = {"wallets": 31, "trades": 260}
        changed = bloglive.refresh(ts(2026, 11, 12, 1, 5), measured=m)
        self.assertEqual(set(changed), {"what-is-wallet-tracking", "what-is-copy-trading", "tokens-sent-to-kol-wallets"})
        self.assertEqual(bloglive.modified("what-is-copy-trading"), "2026-11-12")
        self.assertEqual(bloglive.modified("what-is-a-kol-in-crypto"), "2026-11-10")   # unchanged block keeps its day
        self.assertIsNone(bloglive.modified("how-to-spot-a-rug-pull"))                 # never had two numbers
        self.assertIsNone(bloglive.modified("crypto-tax-croatia"))                     # a post without a block
        bloglive.refresh(ts(2026, 11, 13, 1, 5), measured={})                           # nothing could be counted
        self.assertEqual(bloglive.blocks()["wallets"]["data"], {"wallets": 31, "trades": 260})   # the block keeps its numbers

    def test_every_block_belongs_to_a_real_post_in_both_languages(self):
        for slug, key in bloglive.BLOCK_OF.items():
            self.assertIn(key, bloglive.BLOCKS)
            for lang in ("en", "hr"):
                self.assertIsNotNone(blog.get_en(slug, lang), (slug, lang))
        for key, more in bloglive.MORE.items():
            for href in more[:2]:
                self.assertIsNotNone(public.route(href), href)                # the "live table" link is a real page

    def test_post_shows_the_block_in_its_language_and_moves_date_modified(self):
        self.assertEqual(bloglive.html("what-is-wallet-tracking", "hr"), "")  # before the first night: no block
        before = blog.page("sto-je-pracenje-novcanika", "hr")
        self.assertNotIn("live-data", before)
        self.assertIn('"dateModified": "2026-11-01"', before)
        bloglive.refresh(ts(2026, 11, 10, 1, 5), measured={"wallets": {"wallets": 1234, "scored": 300, "trades": 56789},
                                                           "kol": {"x_accounts": 7000, "board": 350}})
        hr = blog.page("sto-je-pracenje-novcanika", "hr")
        for s in ("id=live-data", "Stanje danas", "<b>1.234</b><span>praćenih novčanika</span>", "56.789",
                  "10. studenoga 2026.", '"dateModified": "2026-11-10"'):
            self.assertIn(s, hr)
        en = blog.page("what-is-a-kol-in-crypto", "en")
        for s in ("Today's numbers", "<b>7,000</b><span>X accounts tracked</span>", "10 November 2026",
                  "href=/influencers>Open the live leaderboard"):
            self.assertIn(s, en)
        self.assertNotIn("live-data", blog.page("crypto-tax-croatia", "en"))  # a post we count nothing for
        self.assertNotIn("—", bloglive.html("what-is-a-kol-in-crypto", "hr") + bloglive.html("what-is-a-kol-in-crypto", "en"))

    def test_a_broken_block_never_breaks_the_post(self):
        with mock.patch.object(bloglive, "html", side_effect=RuntimeError("x")), mock.patch("builtins.print"):
            self.assertIn("</article>", blog.page("what-is-copy-trading", "en"))


ROWS = [
    {"day": "2026-11-12", "ts": 3, "counts": {}, "added": {}, "blogs": [], "posts": []},          # a quiet night
    {"day": "2026-11-11", "ts": 2, "counts": {},
     "added": {"kols": 12, "calls": 1340, "wallets": 85, "trades": 12040, "channels": 3, "coins": 2, "tokens": 410},
     "blogs": ["what-is-wallet-tracking", "what-is-copy-trading", "what-is-a-kol-in-crypto", "how-to-spot-a-rug-pull"],
     "posts": []},
    {"day": "2026-11-10", "ts": 1, "counts": {}, "added": {},
     "blogs": ["influencer-clustering"], "posts": ["best-crypto-telegram-channels", "how-to-check-a-kol-track-record"]},
]


class LandingBlock(Base):
    def block(self, html):
        return re.search(r"<section id=dnevnik.*?</section>", html, re.S).group(0)

    def test_words(self):
        self.assertEqual([landing._days_words(n, "hr") for n in (1, 2, 5, 11, 21, 47, 101, 111)],
                         ["1 dan", "2 dana", "5 dana", "11 dana", "21 dan", "47 dana", "101 dan", "111 dana"])
        self.assertEqual([landing._days_words(n, "en") for n in (1, 2, 21)], ["1 day", "2 days", "21 days"])
        self.assertEqual((landing._log_date("2026-11-10", "hr"), landing._log_date("2026-11-10", "en")), ("10. 11.", "10 Nov"))
        self.assertEqual(landing._short_title("What is wallet tracking? How to track Solana wallets (and why most "
                                              "'smart money' isn't)"), "What is wallet tracking?")
        self.assertEqual(landing._short_title("KOL in crypto: how to check a KOL's track record before you follow a call"),
                         "How to check a KOL's track record before you follow a call")
        self.assertEqual(landing._short_title("Best crypto Telegram channels in 2026: ranked by what their calls did"),
                         "Best crypto Telegram channels in 2026")

    def test_without_data_the_block_says_how_long_and_waits(self):
        landing._STATS.update(ts=time.time(), v={"tokens": 5, "kols": 9}, busy=False)     # counted, but no log yet
        with mock.patch.object(sitelog, "live_days", return_value=9):
            hr, en = self.block(landing.page_html({}, lang="hr")), self.block(landing.page_html({}, lang="en"))
        for s in ("MemeSonar je live 9 dana.", "Svake noći u 02:00", "Prvi zapis stiže nakon sljedećeg noćnog osvježavanja.",
                  "href=/hr/influenceri", "href=/hr/solana-meme-coini", "href=/hr/blog"):
            self.assertIn(s, hr)
        self.assertNotIn("<ol", hr)
        for s in ("MemeSonar has been live for 9 days.", "The first entry appears after the next nightly refresh.",
                  "href=/influencers", "href=/blog"):
            self.assertIn(s, en)
        self.assertIn("MemeSonar je live od danas.", landing.log_html([], "hr", days=0))
        self.assertIn("MemeSonar je live 21 dan.", landing.log_html([], "hr", days=21))

    def test_with_data_each_day_lists_what_was_added_with_internal_links(self):
        landing._STATS.update(ts=time.time(), v={"tokens": 5, "kols": 9, "log": ROWS}, busy=False)
        with mock.patch.object(sitelog, "live_days", return_value=47):
            hr, en = self.block(landing.page_html({}, lang="hr")), self.block(landing.page_html({}, lang="en"))
        for s in ("MemeSonar je live 47 dana.", "<time datetime=2026-11-11>11. 11.</time>",
                  "<a href=/hr/influenceri>Influenceri<b>+12</b></a>", "Izmjereni pozivi<b>+1.340</b>",
                  "<a href=/hr/blog/sto-je-pracenje-novcanika>Novčanici<b>+85</b></a>",
                  "<a href=/hr/blog/sto-je-copy-trading>Tradeovi novčanika<b>+12.040</b></a>",
                  "<a href=/hr/telegram-kanali>Telegram kanali<b>+3</b></a>", "<a href=/hr/solana-meme-coini>Meme coini<b>+2</b></a>",
                  "<a href=/hr/provjera>Provjereni tokeni<b>+410</b></a>", "Blogovi s novim podacima:", "i još 2</a>",
                  "Novi članci: <a href=/hr/blog/najbolji-kripto-telegram-kanali>Najbolji kripto Telegram kanali 2026.</a>",
                  "<a href=/hr/blog/grupiranje-influencera>Grupiranje influencera</a>"):
            self.assertIn(s, hr)
        self.assertNotIn("2026-11-12", hr)                                    # a night with nothing new is not listed
        self.assertEqual(hr.count("<li class=lgr>"), 2)
        for s in ("MemeSonar has been live for 47 days.", "<time datetime=2026-11-11>11 Nov</time>",
                  "<a href=/influencers>Influencers<b>+12</b></a>", "Calls measured<b>+1,340</b>",
                  "<a href=/blog/what-is-copy-trading>Wallet trades<b>+12,040</b></a>", "Blog posts with new data:",
                  "and 2 more</a>", "New posts: <a href=/blog/best-crypto-telegram-channels>"):
            self.assertIn(s, en)
        self.assertNotIn("—", hr + en)                                        # no em-dashes in interface text

    def test_every_link_in_the_block_leads_to_a_real_public_page(self):
        seed(self.d)
        landing._STATS.update(ts=time.time(), v={"log": ROWS}, busy=False)
        for lang in ("hr", "en"):
            hrefs = set(re.findall(r"href=([^\s>]+)", self.block(landing.page_html({}, lang=lang))))
            self.assertGreaterEqual(len(hrefs), 12)
            for h in hrefs:
                self.assertTrue(h.startswith("/hr/") if lang == "hr" else not h.startswith("/hr"), h)   # stays in its language
                r = public.route(h)
                self.assertIsNotNone(r, h)                                     # a public, indexable path
                if "/blog" in h or "influenc" in h or "telegram" in h:
                    self.assertEqual(r[0], 200, h)

    def test_only_the_last_few_days_with_news_are_shown_and_odd_rows_are_skipped(self):
        rows = [{"day": f"2026-11-{d:02d}", "added": {"kols": d}, "blogs": [], "posts": []} for d in range(20, 10, -1)]
        html = landing.log_html(rows, "hr", days=30)
        self.assertEqual(html.count("<li class=lgr>"), landing.LOG_SHOW)
        self.assertIn("2026-11-20", html)
        self.assertNotIn("2026-11-15", html)
        with mock.patch("builtins.print"):
            odd = landing.log_html([{"day": None, "added": {"kols": 1}}, "smeće",
                                    {"day": "2026-11-11", "added": {"kols": 2}, "blogs": ["nema-takvog-clanka"], "posts": None}],
                                   "hr", days=3)
        self.assertEqual(odd.count("<li class=lgr>"), 1)
        self.assertNotIn("nema-takvog-clanka", odd)

    def test_blog_names_take_turns_from_day_to_day(self):
        many = list(bloglive.BLOCK_OF)
        a = landing.log_html([{"day": "2026-11-11", "added": {}, "blogs": many, "posts": []}], "hr", days=5)
        b = landing.log_html([{"day": "2026-11-12", "added": {}, "blogs": many, "posts": []}], "hr", days=5)
        first = lambda h: re.findall(r"<a href=(/hr/blog/[^>]+)>", h)[:landing.LOG_LINKS_MAX]  # noqa: E731
        self.assertNotEqual(first(a), first(b))
        self.assertIn(f"i još {len(many) - landing.LOG_LINKS_MAX}</a>", a)

    def test_log_rows_ride_with_the_cached_numbers_not_with_the_request(self):
        sitelog.record(ts(2026, 11, 10, 1, 5), counted={"kols": 10})
        sitelog.record(ts(2026, 11, 11, 1, 5), counted={"kols": 15})
        with mock.patch.object(landing, "HERE", self.d):
            v = landing.compute()
        self.assertEqual([r["day"] for r in v["log"]], ["2026-11-11", "2026-11-10"])
        landing._STATS.update(ts=time.time(), v=v, busy=False)
        with mock.patch.object(sitelog, "recent", side_effect=AssertionError("database read on a page view")), \
                mock.patch.object(sitelog, "_read", side_effect=AssertionError("database read on a page view")):
            self.assertIn("Influenceri<b>+5</b>", landing.page_html({}, lang="hr"))

    def test_seo_structure_of_the_page_is_kept(self):
        landing._STATS.update(ts=time.time(), v={"log": ROWS}, busy=False)
        html = landing.page_html({}, lang="hr")
        self.assertEqual(html.count("<h1"), 1)
        self.assertLess(html.index("<h1"), html.index("id=dnevnik"))
        self.assertLess(html.index("id=dnevnik"), html.index("id=funkcije"))    # after the numbers, before the features
        self.assertIn("<h2>MemeSonar je live", html)
        for s in ('rel=canonical href="https://example.com/hr"', "application/ld+json", "hreflang=x-default", "id=pristup"):
            self.assertIn(s, html)

    def test_autopilot_strip_shows_only_when_the_other_module_gives_one(self):
        landing._STATS.update(ts=time.time(), v={}, busy=False)
        self.assertEqual(landing._ap_strip("hr"), "")                         # the module does not exist yet
        fake = types.ModuleType("ui.apjavno")
        seen = []
        fake.landing_strip = lambda lang="hr": seen.append(lang) or "<a href=/autopilot>Tradanje pravim sredstvima je live</a>"
        import ui
        with mock.patch.dict(sys.modules, {"ui.apjavno": fake}), mock.patch.object(ui, "apjavno", fake, create=True):
            html = landing.page_html({}, lang="en")
            self.assertEqual(seen, ["en"])
            self.assertIn("<div class='w apst'><a href=/autopilot>", html)
            self.assertLess(html.index("class='w apst'"), html.index("<header class=hero>"))   # near the top
            fake.landing_strip = lambda lang="hr": ""                         # the Autopilot is not live
            self.assertNotIn("class='w apst'", landing.page_html({}, lang="hr"))
            fake.landing_strip = lambda lang="hr": 1 / 0                      # their bug is not our 500
            landing._STRIP_ERR[0] = 0.0
            with mock.patch("builtins.print") as pr:
                self.assertIn("Zatraži pristup", landing.page_html({}, lang="hr"))
                landing.page_html({}, lang="hr")
            self.assertEqual(pr.call_count, 1)                                # one line an hour, not one per visit
        self.assertNotIn("class='w apst'", landing.page_html({}, lang="hr"))


if __name__ == "__main__":
    unittest.main()
