"""Paid shillers (kol/shillers.py), Telegram history (tg/history.py), 'Zovu zajedno' (kol/together.py) and the
reorganised Influenceri page, on synthetic data."""
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from kol import discover, shillers, store, together  # noqa: E402
from tg import history, store as tstore  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CFG = json.load(open(os.path.join(ROOT, "kol", "config.json")))
T0 = 1793390000


def page_html(posts):
    """A minimal t.me/s page with the given (post id, ts, text) posts."""
    import datetime as dt
    out = ['<div class="tgme_channel_info"></div>']
    for pid, ts, text in posts:
        iso = dt.datetime.fromtimestamp(ts, dt.timezone.utc).isoformat()
        out.append(f'<div class="tgme_widget_message_wrap"><div data-post="chan/{pid}"></div>'
                   f'<div class="tgme_widget_message_text">{text}</div><time datetime="{iso}"></time></div>')
    return "".join(out)


class ShillList(unittest.TestCase):
    def test_list_loaded_from_his_table(self):
        tg, x = shillers.tg_channels(), shillers.x_handles()
        self.assertIn("csducks_movecall", tg)
        self.assertIn("cryptoprolegend", x)
        self.assertTrue(shillers.is_shill("tg:CsDucks_MoveCall"))
        self.assertTrue(shillers.is_shill("CRYPTOPROLEGEND"))
        self.assertFalse(shillers.is_shill("someone_else"))
        self.assertIn("2 sol", shillers.info("tg:csducks_movecall").get("price", "").lower())
        # nothing personal from his sheet made it into the repo
        raw = open(shillers.PATH).read()
        self.assertNotIn("@gmail", raw)
        self.assertNotIn("Hello,", raw)

    def test_shill_stays_on_trial_until_proven(self):
        d = tempfile.mkdtemp()
        con = store.connect(os.path.join(d, "kol.db"))
        good = {"measured": 30, "score_lo": 60}
        con.execute("INSERT INTO kols (handle, score, stats) VALUES (?,?,?)", ("cryptoprolegend", 70, json.dumps(good)))
        con.execute("INSERT INTO kols (handle, score, stats) VALUES (?,?,?)", ("tg:csducks_movecall", 70,
                                                                               json.dumps({"measured": 5, "score_lo": 60})))
        con.execute("INSERT INTO kols (handle, score, stats) VALUES (?,?,?)", ("normal_kol", 70, json.dumps(good)))
        for h in ("cryptoprolegend", "tg:csducks_movecall", "normal_kol"):
            con.execute("INSERT INTO calls (tweet_id, token, handle, ts, kind) VALUES (?,?,?,?, 'call')",
                        (h + "1", "TOK", h, T0 - 30 * 86400))
        trial = discover.annotate(con, CFG, now=T0)
        st = {h: json.loads(s) for h, s in con.execute("SELECT handle, stats FROM kols")}
        self.assertTrue(st["tg:csducks_movecall"]["paid_shill"])
        self.assertIn("tg:csducks_movecall", trial)          # 5 calls: not proven
        self.assertNotIn("cryptoprolegend", trial)           # 30 calls, safe score 60: proven even if paid
        self.assertNotIn("normal_kol", trial)
        self.assertFalse(st["normal_kol"]["paid_shill"])


class History(unittest.TestCase):
    def test_backfill_walks_back_and_marks_done(self):
        d = tempfile.mkdtemp()
        con = tstore.connect(os.path.join(d, "tg.db"))
        hype = os.path.join(d, "hype.db")
        con.execute("INSERT INTO channels (name, status, last_post) VALUES ('chan', 'active', 50)")
        ca = "HgxEGTZ1Epb64RrYqcuHkqb1gGWWnF5WcPTCDWzApump"
        con.execute("INSERT INTO posts (channel, post, ts, cas) VALUES ('chan', 41, ?, '')", (T0,))
        pages = {41: page_html([(30, T0 - 3000, f"buy {ca}"), (35, T0 - 2000, "gm")]),
                 30: page_html([(2, T0 - 9000, "first post")])}
        p, n, done = history.backfill(con, "chan", max_pages=2, fetch=lambda ch, before: pages[before],
                                      sleep=lambda s: None,
                                      hype_db=hype)
        self.assertEqual((p, n), (2, 1))
        self.assertFalse(done)  # an empty page can be a gap of deleted posts: keep looking a few times
        for _ in range(6):
            p, n, done = history.backfill(con, "chan", fetch=lambda ch, before: page_html([]), sleep=lambda s: None,
                                          hype_db=hype)
            if done:
                break
        self.assertTrue(done)
        rows = con.execute("SELECT post, cas, source FROM posts ORDER BY post").fetchall()
        self.assertEqual([r[0] for r in rows], [2, 30, 35, 41])
        self.assertEqual(rows[1][2], "history")
        self.assertEqual(history.backfill(con, "chan", fetch=None), (0, 0, True))  # done: never reads again


class Discover(unittest.TestCase):
    def test_tg_channels_with_imported_calls_become_candidates(self):
        from tg import discover as tdisc
        d = tempfile.mkdtemp()
        k = store.connect(os.path.join(d, "kol.db"))
        k.execute("INSERT INTO kols (handle) VALUES ('tg:wctcalls'), ('someone'), ('tg:x')")
        k.commit()
        k.close()
        con = tstore.connect(os.path.join(d, "tg.db"))
        self.assertEqual(tdisc.from_kol_calls(con, os.path.join(d, "kol.db")), 1)  # 'x' is not a valid channel name
        self.assertEqual(con.execute("SELECT found_via FROM channels WHERE name='wctcalls'").fetchone()[0], "kol_calls")


class Together(unittest.TestCase):
    def _db(self):
        d = tempfile.mkdtemp()
        con = store.connect(os.path.join(d, "kol.db"))
        rows = []
        # 10 tokens called by one account: 2 double; 10 tokens called by 3 accounts together: 7 double
        for i in range(10):
            rows.append((f"s{i}", f"SOLO{i}", "solo", T0 + i * 7200, 1.5 if i < 2 else 0.2))
        for i in range(10):
            for j, h in enumerate(("a", "b", "tg:c")):
                rows.append((f"g{i}{h}", f"GRP{i}", h, T0 + i * 7200 + j * 300, 1.5 if i < 7 else 0.1))
        for tid, tok, h, ts, m in rows:
            con.execute("INSERT INTO calls (tweet_id, token, handle, ts, kind, max24, r24h) VALUES (?,?,?,?,?,?,?)",
                        (tid, tok, h, ts, "call", m, m - 0.3))
        from kol import score
        score.build_groups(con, CFG)
        con.execute("INSERT INTO pair_tests VALUES ('a', 'b', 10, 1.0, 10.0, 0.001, 1)")
        con.execute("INSERT INTO pair_tests VALUES ('a', 'tg:c', 10, 1.0, 10.0, 0.001, 1)")
        return con

    def test_group_beats_solo_and_cluster_found(self):
        con = self._db()
        d = together.build(con, shill={"tg:c"})
        self.assertEqual(d["sizes"]["1"]["n"], 10)
        self.assertAlmostEqual(d["sizes"]["1"]["hit"], 0.2)
        self.assertEqual(d["sizes"]["3"]["n"], 10)
        self.assertAlmostEqual(d["sizes"]["3"]["hit"], 0.7)
        self.assertEqual(d["mixes"]["X + Telegram"]["n"], 10)
        self.assertIn("s plaćenim shillerom", d["shills"])
        cl = d["clusters"][0]
        self.assertEqual(set(cl["members"]), {"a", "b", "tg:c"})
        self.assertEqual(cl["leader"], "a")
        self.assertEqual(cl["shill"], ["tg:c"])
        lines = together.verdict(d)
        self.assertIn("jači signal", lines[0])

    def test_empty_db_says_too_little(self):
        d = tempfile.mkdtemp()
        con = store.connect(os.path.join(d, "kol.db"))
        self.assertIn("premalo", together.verdict(together.build(con))[0])


class Page(unittest.TestCase):
    def test_page_sections_open_on_tap_and_have_summary(self):
        con = Together()._db()
        path = con.execute("PRAGMA database_list").fetchone()[2]
        con.commit()
        con.close()
        old = store.DB
        store.DB = path
        try:
            from ui import kol
            title, body = kol.analize_page({})   # 10.11. (prijedlog 3.3): these sections live on /kol/analize now
        finally:
            store.DB = old
        self.assertEqual(title, "Analize influencera")
        self.assertIn("uc-top", body)
        for sid in ("tablica", "zajedno", "shilleri", "pozivi", "parovi", "brojke"):   # the old table: id tablica
            self.assertIn(f"<details class=uc-sec id={sid}>", body)
        self.assertNotIn("<h2 id=analiza>", body)  # the old closed "Analiza" box that hid 8 sections is gone
        self.assertIn("Zovu zajedno", body)
        self.assertIn("<details class=uc-sec id=tgpovijest>", body)  # Call Analyser + SpyDefi history


class LastFifty(unittest.TestCase):
    """4.11.: a channel with 1 measured call showed 'Pogodak 100%'. Now: last 50, and nothing below 10 measured."""

    def test_stats_use_last_50(self):
        from kol import score
        calls = [{"kind": "call", "first_by_kol": 1, "token": f"t{i}", "ts": T0 + i, "max24": 2.0 if i < 60 else -0.5,
                  "r1h": 0, "vol_lift": 1, "rug": 0, "pre2h": 0, "first_overall": 0, "views": 0, "likes": 0,
                  "retweets": 0, "followers": 0} for i in range(100)]
        s, _ = score.kol_stats(calls, CFG)
        self.assertEqual(s["measured"], 100)
        self.assertEqual(s["n_last"], 50)
        self.assertAlmostEqual(s["hit_last"], 0.2)  # newest 50 = 50..99: only 50..59 doubled
        self.assertAlmostEqual(s["hit_rate"], 0.6)

    def test_channels_table_hides_lucky_percentages(self):
        from ui import izvori
        d = tempfile.mkdtemp()
        t = tstore.connect(os.path.join(d, "tg.db"))
        for name in ("lucky", "proven"):
            t.execute("INSERT INTO channels (name, status, n_ca, last_ca_ts) VALUES (?, 'active', 5, ?)",
                      (name, T0 + (100 if name == "lucky" else 0)))
        t.commit()
        k = store.connect(os.path.join(d, "kol.db"))
        k.execute("INSERT INTO kols (handle, score, stats) VALUES ('tg:lucky', 48, ?)",
                  (json.dumps({"measured": 1, "n_last": 1, "hit_last": 1.0, "hit_rate": 1.0}),))
        k.execute("INSERT INTO kols (handle, score, stats) VALUES ('tg:proven', 30, ?)",
                  (json.dumps({"measured": 40, "n_last": 40, "hit_last": 0.35, "hit_rate": 0.35}),))
        k.commit()
        old = izvori.HERE
        izvori.HERE = d
        try:
            _, body = izvori.page({})
        finally:
            izvori.HERE = old
        sec = body[body.index("id=kanali"):body.index("Zadnje Telegram objave")]
        self.assertNotIn("100%", sec)
        self.assertIn("premalo", sec)
        self.assertIn("35%", sec)
        self.assertLess(sec.index("proven"), sec.index("lucky"))  # enough data goes on top, even if older

    def test_history_table_uses_last_50_and_min_sample(self):
        from ui import kolsummary
        h = kolsummary.tg_history_html()
        self.assertIn("zadnjih 50 poziva", h)
        self.assertIn("Zadnjih poziva", h)


if __name__ == "__main__":
    unittest.main()
