"""11.11. (Jure: "Marko ima naviku objaviti X post pa ga za sekundu izbrisati ... to ne treba ući u statistiku"):
fresh X calls checked again after ~1 and ~5 min; gone = kind 'flash', out of every stat."""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from kol import deleted, score, store   # noqa: E402

NOW = 1794346000
MARKO = "2120269096952770895"


class Base(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.path = os.path.join(self.d, "kol.db")
        self.con = store.connect(self.path)
        self.log = []

    def tearDown(self):
        self.con.close()

    def call(self, tid, ts, handle="0xmarko77", token="TOKa", kind="call", text="$AAA buy"):
        self.con.execute("INSERT INTO calls (tweet_id, token, handle, ts, kind, symbol, text, source) VALUES (?,?,?,?,?,?,?,?)",
                         (tid, token, handle, ts, kind, "AAA", text, "x_hook"))
        self.con.commit()

    def kind(self, tid):
        return self.con.execute("SELECT kind FROM calls WHERE tweet_id=?", (tid,)).fetchone()[0]

    def check(self, now, present):
        return deleted.flash_check(self.con, {}, now=now, fetch=lambda b: [t for t in b if t in present],
                                   log=self.log.append)


class FlashCheck(Base):
    def test_gone_at_first_check_is_flash_present_stays(self):
        self.call("101", NOW - 50)
        self.call("102", NOW - 50, token="TOKb")
        self.assertEqual(self.check(NOW, {"102"}), (2, 1))
        self.assertEqual(self.kind("101"), "flash")
        self.assertEqual(self.kind("102"), "call")
        self.assertIsNotNone(self.con.execute("SELECT deleted_ts FROM calls WHERE tweet_id='101'").fetchone()[0])
        self.assertIn("ne ulazi u statistiku", self.log[-1])

    def test_second_check_after_5_min_then_never_again(self):
        self.call("201", NOW - 50)
        self.check(NOW, {"201"})                                     # first: still there
        self.assertEqual(self.check(NOW + 100, set()), (0, 0))       # not due before 300 s
        self.assertEqual(self.check(NOW + 260, set()), (1, 1))       # second: gone within ~5 min
        self.assertEqual(self.kind("201"), "flash")
        self.call("202", NOW - 50, token="TOKc")
        self.check(NOW, {"202"})
        self.check(NOW + 260, {"202"})                               # both checks passed
        self.assertEqual(self.check(NOW + 2000, set()), (0, 0))      # deleted later: keeps counting (old rule)
        self.assertEqual(self.kind("202"), "call")

    def test_old_calls_tg_and_wallets_are_not_checked(self):
        self.call("301", NOW - 3600)
        self.call("tg:1", NOW - 60, handle="tg:chan")
        self.call("302", NOW - 60, handle="w:abc")
        self.assertEqual(self.check(NOW, set()), (0, 0))

    def test_empty_answer_for_many_is_a_hiccup(self):
        for i in range(6):
            self.call(str(400 + i), NOW - 60, token=f"T{i}")
        self.assertEqual(self.check(NOW, set())[1], 0)
        self.assertEqual(self.kind("400"), "call")

    def test_day_cap(self):
        for i in range(5):
            self.call(str(500 + i), NOW - 60, token=f"T{i}")
        got = deleted.flash_check(self.con, {"flash": {"day_cap": 2}}, now=NOW, fetch=lambda b: list(b), log=self.log.append)
        self.assertEqual(got, (2, 0))
        self.assertEqual(deleted.flash_check(self.con, {"flash": {"day_cap": 2}}, now=NOW + 5, fetch=lambda b: list(b),
                                             log=self.log.append), (0, 0))

    def test_flash_leaves_the_stats_and_reclassify_keeps_it(self):
        self.call("601", NOW - 60)
        self.check(NOW, set())
        n_calls = self.con.execute("SELECT COUNT(*) FROM calls WHERE kind IN ('call', 'bot')").fetchone()[0]
        self.assertEqual(n_calls, 0)
        score.reclassify(self.con)
        self.assertEqual(self.kind("601"), "flash")
        self.assertEqual(deleted.summary(self.con, "0xmarko77")["deleted"], 0)


class OwnerFlash(Base):
    def test_markos_post_once_with_what_was_stored(self):
        self.call(MARKO, 1794346520, token="29JjbX5pZvp1k5vNKWqNp3HjDyocK33xMJusvyr8pump")
        out = deleted.owner_flash(self.con, now=NOW, log=self.log.append)
        self.assertTrue(any("0xmarko77" in t and "vrsta call" in t for t in out))
        self.assertTrue(any("više ne ulazi u statistiku" in t for t in out))
        self.assertEqual(self.kind(MARKO), "flash")
        self.assertEqual(deleted.owner_flash(self.con, now=NOW, log=self.log.append), [])   # once

    def test_not_stored_says_so(self):
        out = deleted.owner_flash(self.con, now=NOW, log=self.log.append)
        self.assertEqual(out, [f"objava {MARKO}: nije u bazi (bot je nije spremio kao poziv)"])

    def test_round_adds_the_column_on_an_old_file(self):
        got = deleted.flash_round({}, log=self.log.append, now=NOW, fetch=lambda b: list(b), path=self.path)
        self.assertEqual(got, (0, 0))
        self.assertTrue(any("nije u bazi" in t for t in self.log))


if __name__ == "__main__":
    unittest.main()
