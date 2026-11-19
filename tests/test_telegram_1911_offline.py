"""19.11.2026. (vlasnik: "Makni Telegram KOL-ove iz izračuna. Ali zadrži popis kanala, osvježen jednom tjedno, samo za
broj pratitelja. Neka to bude samo informativni popis sakriven negdje sa strane. Očisti sve ostalo vezano za Telegram
ako više nije bitno.").

  - the one predicate (kol/tgout.py) and every calculation: a Telegram caller's call changes nothing (numbers identical
    with and without the 'tg:' rows) in konsenzus, zadnjih 5, the copy ranking, the insajderi call events, the copy
    loop's signals, the moonshot callers, the convergence, the caller score
  - a follow of a Telegram channel: refused when new, stopped with a note when it exists (nothing deleted)
  - the weekly follower count (tg/pratitelji.py): a fixture page, one row a week per channel, never more often, nothing
    but the page header read
  - start.sh / ops/cpuguard / ops/drustveni / ops/fokus agree; the app page /telegram-kanali (data, empty, English,
    escaping, search) and the /izvori redirect; the public /telegram-channels pages in both languages, the sitemap
No network: the page fetch is a fake.

    python3 -m unittest tests.test_telegram_1911_offline
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

from kol import store as kstore, tgout  # noqa: E402
from tg import pratitelji, reader, store as tstore  # noqa: E402

NOW = 1_795_000_000
D = 86400
TOK = "So1aNaTokenAAAAAAAAAAAAAAAAAAAAAAAAAAAAApump"
TOK2 = "So1aNaTokenBBBBBBBBBBBBBBBBBBBBBBBBBBBBBpump"
TOK3 = "So1aNaTokenCCCCCCCCCCCCCCCCCCCCCCCCCCCCCpump"


def page(subs="12.5K", title="Gem Calls"):
    """A t.me/s page: the header and one post (the post must never be read)."""
    return ('<div class="tgme_channel_info"><div class="tgme_channel_info_header_title"><span>' + title + '</span></div>'
            f'<span class="counter_value">{subs}</span> <span class="counter_type">subscribers</span></div>'
            '<div class="tgme_widget_message_wrap"><div class="tgme_widget_message_text">ape ' + TOK + '</div></div>')


class Tmp(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = self.tmp.name
        self.addCleanup(self.tmp.cleanup)

    def p(self, name):
        return os.path.join(self.d, name)

    def kol(self, calls, name="kol.db"):
        """kol.db with calls [(tweet_id, token, handle, ts, r1h, r6h, mcap0, max24, r24h)]."""
        con = kstore.connect(self.p(name))
        for tid, tok, h, ts, r1, r6, mc, mx, r24 in calls:
            con.execute("INSERT INTO calls (tweet_id, token, handle, ts, kind, r1h, r6h, mcap0, max24, r24h) "
                        "VALUES (?,?,?,?,'call',?,?,?,?,?)", (tid, tok, h, ts, r1, r6, mc, mx, r24))
        con.commit()
        con.close()
        return self.p(name)


X_CALLS = [("x1", TOK, "alice", NOW - 3 * D, 0.5, 0.8, 200_000, 1.2, 0.3),
           ("x2", TOK2, "bob", NOW - 2 * D, -0.2, -0.4, 300_000, 0.1, -0.5),
           ("x3", TOK, "bob", NOW - 3 * D + 600, 0.4, 0.6, 210_000, 1.0, 0.2)]
TG_CALLS = [("tg:chan/1", TOK, "tg:chan", NOW - 3 * D - 900, 0.9, 1.5, 150_000, 2.0, 0.9),     # Telegram FIRST
            ("tg:chan/2", TOK3, "tg:chan", NOW - D, 2.0, 3.0, 100_000, 3.0, 1.0),
            ("tg:other/9", TOK2, "TG:Other", NOW - 2 * D - 60, 0.1, 0.2, 290_000, 0.5, 0.1)]


class Predicate(unittest.TestCase):
    def test_one_predicate(self):
        for h in ("tg:chan", "TG:Chan", " tg:x", "@tg:x"):
            self.assertTrue(tgout.is_tg(h), h)
        for h in ("alice", "w:abc", "", None, "tgalpha", "@tg_fan"):
            self.assertFalse(tgout.is_tg(h), h)
        self.assertEqual(tgout.drop(["a", "tg:b", "w:c"]), ["a", "w:c"])
        con = sqlite3.connect(":memory:")
        con.execute("CREATE TABLE calls (handle TEXT)")
        con.executemany("INSERT INTO calls VALUES (?)", [("a",), ("tg:b",), ("TG:c",), (None,)])
        self.assertEqual(con.execute(f"SELECT COUNT(*) FROM calls WHERE {tgout.sql()}").fetchone()[0], 2)


class SameNumbers(Tmp):
    """A Telegram caller's call changes nothing: every calculation gives the same answer with and without it."""

    def both(self):
        return self.kol(X_CALLS, "x.db"), self.kol(X_CALLS + TG_CALLS, "xtg.db")

    def test_zadnjih5(self):
        from kol import zadnjih5
        a, b = self.both()
        self.assertEqual(zadnjih5.sample_events(a, NOW), zadnjih5.sample_events(b, NOW))
        self.assertTrue(zadnjih5.sample_events(a, NOW)[0])

    def test_copy_ranking(self):
        from wallets import rang
        a, b = self.both()
        ra, rb = rang.kol_calls({"kol": a}, NOW), rang.kol_calls({"kol": b}, NOW)
        self.assertEqual(ra, rb)
        self.assertEqual({r[2] for r in ra}, {"alice", "bob"})
        # a Telegram row stored by an earlier run is not ranked any more
        w = self.p("wallets.db")
        con = sqlite3.connect(w)
        con.execute("CREATE TABLE copy_rank (kind TEXT, target TEXT, as_of INTEGER, score REAL, proven INTEGER, "
                    "copyable INTEGER, n INTEGER, data TEXT)")
        con.executemany("INSERT INTO copy_rank VALUES ('kol', ?, ?, ?, 1, 1, 12, '{}')",
                        [("alice", NOW, 60.0), ("tg:chan", NOW, 90.0)])
        con.commit()
        con.close()
        rang._CACHE.clear()
        self.assertEqual(set(rang.load("kol", w)), {"alice"})
        self.assertIsNone(rang.get("kol", "tg:chan", w))

    def test_insajderi_call_events(self):
        from insajderi import events, store as istore
        a, b = self.both()
        c = istore.config()
        ea = events.call_events({"kol_db": a}, c, NOW)
        eb = events.call_events({"kol_db": b}, c, NOW)
        self.assertEqual(ea, eb)
        self.assertTrue(ea and all(not tgout.is_tg(e["handle"]) for e in ea))
        self.assertTrue(all(not tgout.is_tg(h) for e in ea for h in e["callers"]))
        # a stored call event of a Telegram first caller stays in the table but is not loaded
        con = istore.connect(self.p("insajderi.db"))
        con.execute("INSERT OR IGNORE INTO i2_events (eid, kind, token, t0, handle, callers) VALUES "
                    "('c:tg2', 'call', ?, ?, 'tg:chan', ?)", (TOK3, NOW - D, json.dumps({"tg:chan": NOW - D})))
        con.execute("INSERT OR IGNORE INTO i2_events (eid, kind, token, t0, handle, callers) VALUES "
                    "('c:x', 'call', ?, ?, 'alice', ?)", (TOK, NOW - D, json.dumps({"alice": NOW - D, "tg:chan": NOW})))
        con.commit()
        got = {e["eid"]: e for e in events.load(con)}
        self.assertNotIn("c:tg2", got)
        self.assertEqual(got["c:x"]["callers"], {"alice": NOW - D})
        self.assertEqual(con.execute("SELECT COUNT(*) FROM i2_events WHERE handle = 'tg:chan'").fetchone()[0] >= 1, True)
        con.close()

    def test_konsenzus(self):
        from konsenzus import live, research
        entries = [{"src": "alice", "kind": "x", "tok": TOK, "ts": NOW - 3600},
                   {"src": "W" * 44, "kind": "wallet", "tok": TOK2, "ts": NOW - 1800}]
        tg = [{"src": "tg:chan", "kind": "tg", "tok": TOK, "ts": NOW - 7200},
              {"src": "tg:chan", "kind": "tg", "tok": TOK3, "ts": NOW - 600}]
        with mock.patch.object(research, "exit_result", lambda e, ex, s: 0.1), \
                mock.patch.object(research, "known_at", lambda e, ex=None: e["ts"]), \
                mock.patch.object(research, "refresh_cut", lambda ts: ts):
            ea = research.make_events(entries, None, 0.0)
            eb = research.make_events(entries + tg, None, 0.0)
        strip = lambda evs: [{k: v for k, v in e.items() if k != "entry"} for e in evs]   # noqa: E731
        self.assertEqual(strip(ea), strip(eb))
        kp = self.kol([("x1", TOK, "alice", NOW - 600, None, None, None, None, None),
                       ("t1", TOK2, "tg:chan", NOW - 500, None, None, None, None, None)])
        tp = self.p("tg.db")
        t = sqlite3.connect(tp)
        t.execute("CREATE TABLE posts (channel TEXT, ts INTEGER, cas TEXT, fwd_from TEXT)")
        t.execute("INSERT INTO posts VALUES ('chan', ?, ?, NULL)", (NOW - 400, TOK3))
        t.commit()
        t.close()
        sigs = live.read_signals(NOW, 3600, {"kol": kp, "tg": tp, "hype": self.p("nema.db")})
        self.assertEqual({(s["src"], s["kind"]) for s in sigs}, {("alice", "x")})

    def test_copy_signals_and_moonshot_callers_and_convergence(self):
        from kol import converge
        from league import copy
        from trade import capgate
        kp = self.kol([("x1", TOK, "alice", NOW - 300, None, None, None, None, None),
                       ("t0", TOK, "tg:chan", NOW - 900, None, None, None, None, None),
                       ("t1", TOK2, "tg:chan", NOW - 100, None, None, None, None, None)])
        tp = self.p("tg.db")
        t = sqlite3.connect(tp)
        t.execute("CREATE TABLE posts (channel TEXT, post INTEGER, ts INTEGER, cas TEXT, fwd_from TEXT)")
        t.execute("INSERT INTO posts VALUES ('chan', 5, ?, ?, NULL)", (NOW - 50, TOK3))
        t.commit()
        t.close()
        paths = {"kol": kp, "tg": tp, "hype": self.p("nema.db")}
        self.assertEqual(copy.events(["alice", "tg:chan"], [], NOW - 3600, paths), [("alice", TOK, "buy", NOW - 300)])
        self.assertEqual(copy.events(["tg:chan"], [], NOW - 3600, paths), [])
        self.assertEqual(copy.first_call(TOK, paths)["handle"], "alice")        # the earlier Telegram call is not first
        ok, why = copy.signal_for(TOK2, NOW, paths=paths)                       # only a Telegram call: no signal
        self.assertFalse(ok, why)
        self.assertTrue(copy.signal_for(TOK, NOW, paths=paths)[0])
        self.assertEqual(copy._signal_call(TOK2, ["tg:chan"], NOW - 100, paths), (None, None))
        self.assertEqual([s for _ts, s in capgate.callers(TOK, NOW, 3600, {"kol": kp, "tg": tp})], ["alice"])
        self.assertEqual(capgate.callers(TOK3, NOW, 3600, {"kol": kp, "tg": tp}), [])
        ev, _sc, _f = converge.events(NOW, 3600, kol_db=kp, tg_db=tp, hype_db=self.p("nema.db"))
        self.assertEqual([(e[0], e[2], e[3]) for e in ev], [(TOK, "x", "alice")])

    def test_caller_score(self):
        from kol import score
        cfg = json.load(open(os.path.join(ROOT, "kol", "config.json")))
        kp = self.kol(X_CALLS + TG_CALLS)
        con = sqlite3.connect(kp)
        con.executemany("INSERT OR IGNORE INTO kols (handle, followers) VALUES (?, ?)",
                        [("alice", 50_000), ("bob", 20_000), ("tg:chan", 9_000), ("TG:Other", 1_000)])
        con.execute("UPDATE calls SET measured_ts = ts + 86400, complete = 1")
        score.mark_first(con)
        score.score_kols(con, cfg, NOW)
        sc = dict(con.execute("SELECT handle, score FROM kols"))
        self.assertIsNone(sc["tg:chan"])
        self.assertIsNone(sc["TG:Other"])
        self.assertIsNotNone(sc["alice"])
        st = json.loads(con.execute("SELECT stats FROM kols WHERE handle = 'tg:chan'").fetchone()[0])
        self.assertIn("tg_score", st)                                           # kept for history only
        first = dict(con.execute("SELECT tweet_id, first_overall FROM calls"))
        self.assertEqual((first["x1"], first["tg:chan/1"]), (1, 0))           # the first X call is "first"
        con.close()


class Follows(Tmp):
    def test_new_follow_refused_existing_one_stopped_with_a_note(self):
        from league import copy
        con = sqlite3.connect(self.p("league.db"))
        copy.ensure(con)
        with self.assertRaisesRegex(ValueError, "Telegram"):
            copy.follow(con, "pravi-trade", "kol", "tg:chan", "", 25, 5)
        with self.assertRaisesRegex(ValueError, "Telegram"):
            copy.follow(con, "pravi-trade", "ekipa", "tg:a, tg:b", "", 25, 5)
        fid = copy.follow(con, "pravi-trade", "ekipa", "tg:a, bigx", "", 25, 5)
        self.assertEqual(con.execute("SELECT target FROM follows WHERE id = ?", (fid,)).fetchone()[0], "bigx")
        # follows made before 19.11. (the real account's too): written straight into the table, as they are on prod
        rows = [("pravi-trade", "kol", "tg:chan", "chan"), ("autopilot-paper", "ekipa", "tg:a,tg:b", "ekipa a+b"),
                ("pravi-trade", "ekipa", "tg:c,carol", "mix"), ("pravi-trade", "kol", "alice", "alice")]
        for u, k, t, lab in rows:
            con.execute("INSERT INTO follows (user, kind, target, label, size_usd, per_day, exit, created, active) "
                        "VALUES (?,?,?,?,25,5,'{}',?,1)", (u, k, t, lab, NOW - D))
        con.commit()
        stopped = copy.stop_tg_follows(con, NOW)
        self.assertEqual(sorted(t for _i, _u, t in stopped), ["tg:a,tg:b", "tg:chan"])
        st = {t: (a, lab, s) for t, a, lab, s in con.execute("SELECT target, active, label, stopped FROM follows")}
        self.assertEqual(st["tg:chan"], (0, "chan" + copy.TG_STOPPED, NOW))
        self.assertEqual(st["tg:a,tg:b"][0], 0)
        self.assertEqual(st["tg:c,carol"][0], 1)                     # the X member keeps the crew alive
        self.assertEqual(st["alice"][0], 1)
        self.assertEqual(con.execute("SELECT COUNT(*) FROM follows").fetchone()[0], 5)   # nothing deleted
        self.assertEqual(copy.stop_tg_follows(con, NOW + 60), [])   # once
        con.close()
        with mock.patch.object(copy, "_ro", lambda p: sqlite3.connect(self.p("league.db"))):
            self.assertEqual(copy.followed_handles(path=self.p("league.db")), {"alice", "bigx", "carol"})


class Weekly(Tmp):
    def db(self, chans=(("alpha", "active"), ("beta", "quiet"), ("gamma", "slow"), ("cand", "candidate"),
                        ("gone", "dead"))):
        con = tstore.connect(self.p("tg.db"))
        con.executemany("INSERT INTO channels (name, status, subs) VALUES (?, ?, 100)", chans)
        con.commit()
        return con

    def test_header_only(self):
        self.assertEqual(reader.parse_header(page("3.53K", "A &amp; B")), {"public": True, "title": "A & B", "subs": 3530})
        self.assertEqual(reader.parse_header("<html>redirect</html>")["subs"], 0)
        for gone in ("parse", "links_in", "channel_name"):
            self.assertFalse(hasattr(reader, gone), gone)
        with self.assertRaises(ValueError):
            reader.fetch("../etc")                                         # never a URL built from a bad name

    def test_once_a_week_per_channel_never_more_often(self):
        con = self.db()
        asked = []

        def fetch(name):
            asked.append(name)
            return page({"alpha": "12.5K", "beta": "1,200", "gamma": "845"}[name])
        out = pratitelji.run(con, NOW, fetch=fetch, sleep=lambda s: None, log=lambda *a: None)
        self.assertEqual(sorted(asked), ["alpha", "beta", "gamma"])        # the list only: no candidate, no dead
        self.assertEqual((out["due"], out["rows"]), (3, 3))
        rows = con.execute("SELECT kanal, ts, pratitelji FROM tg_pratitelji ORDER BY kanal").fetchall()
        self.assertEqual(rows, [("alpha", NOW, 12500), ("beta", NOW, 1200), ("gamma", NOW, 845)])
        for later in (NOW + 60, NOW + D, NOW + 6 * D + 23 * 3600):          # within the week: nothing is read
            asked.clear()
            self.assertEqual(pratitelji.run(con, later, fetch=fetch, sleep=lambda s: None, log=lambda *a: None)["due"], 0)
            self.assertEqual(asked, [])
        asked.clear()
        pratitelji.run(con, NOW + 7 * D, fetch=fetch, sleep=lambda s: None, log=lambda *a: None)
        self.assertEqual(len(asked), 3)                                     # the next week: one more row each
        self.assertEqual(con.execute("SELECT COUNT(*) FROM tg_pratitelji").fetchone()[0], 6)
        self.assertEqual(con.execute("SELECT COUNT(*) FROM posts").fetchone()[0], 0)   # no post is ever stored
        self.assertEqual(con.execute("SELECT COUNT(*) FROM channels").fetchone()[0], 5)  # no discovery
        self.assertEqual(con.execute("SELECT subs, title FROM channels WHERE name='alpha'").fetchone(), (12500, "Gem Calls"))
        con.close()

    def test_a_failed_channel_is_due_again_and_one_failure_does_not_stop_the_pass(self):
        con = self.db((("alpha", "active"), ("beta", "active")))

        def fetch(name):
            if name == "alpha":
                raise OSError("timeout")
            return page("2K")
        out = pratitelji.run(con, NOW, fetch=fetch, sleep=lambda s: None, log=lambda *a: None)
        self.assertEqual((out["rows"], out["fails"]), (1, 1))
        self.assertEqual(pratitelji.due(con, NOW + 60), ["alpha"])
        con.close()

    def test_changes_in_7_and_30_days(self):
        con = self.db((("alpha", "active"), ("beta", "active"), ("new", "active")))
        con.executemany("INSERT INTO tg_pratitelji VALUES (?,?,?)",
                        [("alpha", NOW - 35 * D, 900), ("alpha", NOW - 28 * D, 1000), ("alpha", NOW - 7 * D, 1400),
                         ("alpha", NOW, 1500), ("beta", NOW - 7 * D, 600), ("beta", NOW, 500)])
        con.execute("UPDATE channels SET checked_ts = ? WHERE name = 'new'", (NOW - 3600,))
        con.commit()
        con.close()
        rows = {r["kanal"]: r for r in pratitelji.pregled(self.p("tg.db"))}
        self.assertEqual([r["kanal"] for r in pratitelji.pregled(self.p("tg.db"))], ["alpha", "beta", "new"])
        self.assertEqual((rows["alpha"]["pratitelji"], rows["alpha"]["d7"], rows["alpha"]["d30"]), (1500, 100, 600))
        self.assertEqual((rows["beta"]["d7"], rows["beta"]["d30"]), (-100, None))
        self.assertEqual((rows["new"]["pratitelji"], rows["new"]["d7"], rows["new"]["ts"]), (100, None, NOW - 3600))
        self.assertEqual(pratitelji.pregled(self.p("nema.db")), [])


class Wiring(unittest.TestCase):
    def setUp(self):
        with open(os.path.join(ROOT, "start.sh"), encoding="utf-8") as f:
            self.sh = f.read()
        self.code = "\n".join(ln for ln in self.sh.splitlines() if not ln.strip().startswith("#"))

    def test_start_sh_runs_only_the_follower_count(self):
        self.assertNotIn("run_tg.py loop", self.code)
        self.assertNotIn("telethon", self.code)
        self.assertIn("low python3 run_tg.py pratitelji", self.code)
        self.assertEqual(self.code.count("run_tg.py"), 1)
        self.assertEqual(pratitelji.EVERY_D, 7.0)

    def test_cpuguard_drustveni_fokus_agree(self):
        from ops import cpuguard, drustveni, fokus
        self.assertEqual(cpuguard.classify(["python3", "run_tg.py", "pratitelji"])[:2], ("tg", cpuguard.JOBS))
        self.assertFalse([j for j in drustveni.JOBS if j[0][0] == "run_tg"])
        self.assertFalse([p for p in drustveni.PARTS if p[0].startswith("tg")])
        self.assertIsNone(drustveni.skip_cmd(["python3", "run_tg.py", "pratitelji"], NOW))
        self.assertTrue(any("tg pratitelji" in k for k in fokus.KEPT))
        for gone in ("discover", "history", "live", "poll", "tgstat", "config.json"):
            self.assertFalse(os.path.exists(os.path.join(ROOT, "tg", gone + ("" if "." in gone else ".py"))), gone)
        import run_kol
        with open(run_kol.__file__, encoding="utf-8") as f:
            self.assertNotIn("from_telegram", f.read())
        from kol import collect
        self.assertFalse(hasattr(collect, "from_telegram"))

    def test_the_whatsapp_digest_job_is_gone(self):
        """19.11. (vlasnik: "Makni 'za whatsapp' ... jer je nepotrebno"): no scheduled digest, no guard row."""
        import run_sched
        from ops import cpuguard
        self.assertFalse([j for j in run_sched.JOBS if j[0] == "whatsapp" or "run_whatsapp.py" in str(j[2])])
        self.assertFalse(hasattr(run_sched, "whatsapp"))
        self.assertFalse([p for p in cpuguard.PROCESSES if p[1] == "run_whatsapp.py"])
        self.assertTrue(os.path.exists(os.path.join(ROOT, "share", "novosti.json")))   # "Što je novo" and the X posts

    def test_izvori_redirects_and_the_page_is_routed(self):
        src = open(os.path.join(ROOT, "run_ui.py"), encoding="utf-8").read()
        self.assertRegex(src, r'if path == "/izvori":[^\n]*\n\s+return self\._redirect\("/telegram-kanali", code=301\)')
        self.assertRegex(src, r'if path == "/telegram-kanali":[^\n]*\n\s+from ui import tgkanali\n\s+return tgkanali\.page')
        from ui import izvori
        self.assertFalse(hasattr(izvori, "page"))
        self.assertIn("jednom tjedno", izvori.paid_section())


class AppPage(Tmp):
    def fill(self):
        con = tstore.connect(self.p("tg.db"))
        con.executemany("INSERT INTO channels (name, title, status, subs, checked_ts) VALUES (?,?,?,?,?)",
                        [("alpha_calls", "Alpha <b>Calls</b>", "active", 5000, NOW), ("beta_gems", None, "quiet", 9000, NOW),
                         ("hidden", None, "candidate", 99999, NOW)])
        con.executemany("INSERT INTO tg_pratitelji VALUES (?,?,?)", [("alpha_calls", NOW - 7 * D, 4000), ("alpha_calls", NOW, 5000)])
        con.commit()
        con.close()

    def test_data_order_search_and_escaping(self):
        from ui import tgkanali
        self.fill()
        title, body = tgkanali.page({}, path=self.p("tg.db"))
        self.assertEqual(title, "Telegram kanali (informativno)")
        self.assertIn("Ovo je samo popis kanala i broja pratitelja, osvježava se jednom tjedno. Pozive s Telegrama više ne "
                      "mjerimo i ne ulaze ni u jedan izračun.", body)
        self.assertLess(body.index("beta_gems"), body.index("alpha_calls"))   # most followers first
        self.assertNotIn("hidden", body)
        self.assertIn('href="https://t.me/alpha_calls"', body)
        self.assertIn("Alpha &lt;b&gt;Calls&lt;/b&gt;", body)
        self.assertNotIn("<b>Calls</b>", body)
        self.assertIn("+1,000", body)                                           # the change in 7 days
        _t, found = tgkanali.page({"q": "ALPHA"}, path=self.p("tg.db"))
        self.assertIn("alpha_calls", found)
        self.assertNotIn("beta_gems", found)
        _t, evil = tgkanali.page({"q": '"><script>x</script>'}, path=self.p("tg.db"))
        self.assertNotIn("<script>x</script>", evil)

    def test_empty_and_english(self):
        from ui import i18n, tgkanali
        _t, body = tgkanali.page({}, path=self.p("nema.db"))
        self.assertIn("prvo tjedno brojanje još nije prošlo", body)
        self.fill()
        _t, body = tgkanali.page({}, path=self.p("tg.db"))
        tok = i18n.LANG.set("en")
        try:
            with mock.patch.object(i18n, "_start_worker"):
                en = i18n.translate(f"<html><body>{body}</body></html>")
        finally:
            i18n.LANG.reset(tok)
        self.assertIn("Telegram channels (informational)", en)
        self.assertIn("This is only a list of channels and their follower counts, refreshed once a week.", en)
        self.assertIn("Followers", en)


class PublicPages(Tmp):
    def setUp(self):
        super().setUp()
        con = tstore.connect(self.p("tg.db"))
        con.executemany("INSERT INTO channels (name, title, status, subs, checked_ts) VALUES (?,?,?,?,?)",
                        [("alphacalls", "Alpha Calls", "active", 5000, NOW), ("betagems", None, "slow", 9000, NOW),
                         ("candidate1", None, "candidate", 1, NOW)])
        con.executemany("INSERT INTO tg_pratitelji VALUES (?,?,?)", [("alphacalls", NOW - 7 * D, 4000), ("alphacalls", NOW, 5000)])
        tstore.kv_set(con, "pratitelji_zadnji", {"ts": NOW, "rows": 1})
        con.commit()
        con.close()
        env = mock.patch.dict(os.environ, {"TG_DB": self.p("tg.db"), "KOL_DB": self.p("nema-kol.db"),
                                           "RENDER_EXTERNAL_URL": "https://example.com"})
        env.start()
        self.addCleanup(env.stop)
        from ui import public
        public._cache.clear()
        self.addCleanup(public._cache.clear)

    def test_hub_both_languages(self):
        from ui import public
        code, raw, _ = public.route("/telegram-channels")
        html = raw.decode()
        self.assertEqual(code, 200)
        self.assertIn("Since 19 Nov 2026 we no longer measure what the calls in these channels did", html)
        self.assertLess(html.index("betagems"), html.index("alphacalls"))
        self.assertNotIn("candidate1", html)
        self.assertIn("+1,000", html)
        self.assertIn("<title>Crypto Telegram channels: follower counts", html)
        self.assertIn('hreflang=hr href="https://example.com/hr/telegram-kanali"', html)
        main = html[html.index("<h1>"):html.index("</table>")]
        self.assertNotRegex(main, r"(?i)hit rate|reached \+15|rugs\b|tgstat|telethon|TG_DB|api[_ ]?key")
        hr = public.route("/hr/telegram-kanali")[1].decode()
        self.assertIn("Od 19. 11. 2026. više ne mjerimo što su napravili pozivi", hr)
        self.assertIn("+1.000", hr)

    def test_channel_card_is_noindex_and_sitemap_has_the_hub_only(self):
        from ui import public
        card = public.route("/telegram/alphacalls")[1].decode()
        self.assertIn("noindex", card)
        self.assertIn("https://t.me/alphacalls", card)
        self.assertIn("5,000", card)
        self.assertEqual(public.route("/telegram/candidate1")[0], 404)
        self.assertEqual(public.route("/hr/telegram/nema")[0], 404)
        sm = public.route("/sitemap.xml")[1].decode()
        self.assertIn("<loc>https://example.com/telegram-channels</loc><lastmod>2026-11-18</lastmod>", sm)
        self.assertNotIn("/telegram/alphacalls", sm)


if __name__ == "__main__":
    unittest.main()
