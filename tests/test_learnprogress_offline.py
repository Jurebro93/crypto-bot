"""Učenje page top (ui/learnprogress.py): start vs now, where it earned/lost, plain words. Synthetic paper.db."""
import json
import os
import sqlite3
import tempfile
import time
import unittest

from paper import store
from ui import data, learnprogress as lp

DAY = 86400


def make_db(path, now, start_ret, now_ret, days=10, per_day=6):
    con = store.connect(path)
    for d in range(days):
        for i in range(per_day):
            ts = int(now - (days - 1 - d) * DAY - 3600 - i * 60)
            early = d < 3
            ret = start_ret if early else now_ret
            if i == 0:
                ret, ex = -0.3, "stop_loss"
            elif i == 1 and early:
                ret, ex = -0.9, "rug"
            else:
                ex = "take_profit_2x" if ret > 0 else "time"
            arm = "tg+x|us" if i % 2 else "dex|asia"
            con.execute("INSERT INTO trades (token, symbol, opened_ts, closed_ts, status, exit_reason, size_usd, "
                        "pnl_usd, ret, state, config) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                        (f"t{d}{i}", "X", ts - 600, ts, "closed", ex, 20, 20 * ret, ret, "{}",
                         json.dumps({"arm": arm, "entry_mode": "explore"})))
    # a manual sale must not count
    con.execute("INSERT INTO trades (token, opened_ts, closed_ts, status, exit_reason, pnl_usd, ret, state, config) "
                "VALUES ('m', ?, ?, 'closed', 'manual', 999, 5, '{\"fills\":[{\"reason\":\"rucno\"}]}', '{}')",
                (int(now - DAY), int(now - DAY)))
    con.commit()
    con.close()


class T(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.db = os.path.join(self.d, "paper.db")
        self.now = time.time()

    def test_better(self):
        make_db(self.db, self.now, -0.1, 0.2)
        rows = lp.trades(self.db)
        self.assertEqual(len(rows), 60)  # manual sale left out
        c = lp.compare(rows, self.now)
        self.assertEqual(c["start"]["n"], 18)
        self.assertEqual(c["now"]["n"], 18)
        cls, line = lp.verdict(c)
        self.assertEqual(cls, "good")
        self.assertIn("bolji nego na početku", line)
        self.assertIn("+12%", line)
        h = lp.progress_html(self.now, self.db)
        self.assertIn("<svg", h)
        self.assertIn("U plusu", h)
        self.assertIn("/pravi-trade", h)

    def test_worse_and_young(self):
        make_db(self.db, self.now, 0.2, -0.1)
        self.assertEqual(lp.verdict(lp.compare(lp.trades(self.db), self.now))[0], "bad")
        db2 = os.path.join(self.d, "p2.db")
        make_db(db2, self.now, 0.1, 0.1, days=4)
        c = lp.compare(lp.trades(db2), self.now)
        self.assertIsNone(c["now"])
        self.assertIn("tek 4 dana", lp.verdict(c)[1])
        self.assertIn("Još nema", lp.verdict(None)[1])

    def test_story(self):
        make_db(self.db, self.now, -0.1, 0.2)
        rows = lp.trades(self.db, full=True)
        h = lp.earn_lose_html(rows, self.now)
        self.assertIn("Na čemu zarađuje", h)
        self.assertIn("Telegram + KOL-ovi na X-u", h)
        self.assertIn("take profitom", h)
        self.assertIn("Odakle dolazi izgubljeni novac", h)
        self.assertIn("Je li zaradio?", lp.money_html(rows, self.now))

    def test_fold_keeps_content_and_anchor(self):
        body = "<h2 id=liga>Bot</h2><p>a</p><h2>Drugo</h2><table></table>"
        f = lp.fold(body)
        self.assertIn("<details class=uc-sec id=liga><summary>Bot</summary>", f)
        self.assertIn("<summary>Drugo</summary><div class=in><table></table>", f)

    def test_page_renders(self):
        make_db(self.db, self.now, -0.1, 0.2)
        old = data.PAPER_DB
        data.PAPER_DB = self.db
        try:
            from ui import learnpage
            title, body = learnpage.page({})
        finally:
            data.PAPER_DB = old
        self.assertEqual(title, "Učenje")
        self.assertIn("bolji nego na početku", body)
        self.assertIn("Kako se sam popravlja", body)


if __name__ == "__main__":
    unittest.main()
