"""5.11.: the crew (kol/crew.py): who engages on a call, which engagers bought before it, the token features and
the 'Ekipa' strategy signal."""
import json
import os
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from kol import crew, store as kstore  # noqa: E402

CFG = json.load(open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "kol", "config.json")))
# 9.11.: engager reads are off in the shipped config (crew.daily_usd 0); the mechanism is tested with a budget
CFG = {**CFG, "crew": {**CFG["crew"], "daily_usd": 0.8}}
NOW = 1_800_000_000
MINT = "M" * 44
W_INS = "I" * 44


def _tw(h, foll, ts):
    import datetime as dt
    created = dt.datetime.fromtimestamp(ts, dt.timezone.utc).strftime("%a %b %d %H:%M:%S +0000 %Y")
    return {"id": str(ts), "text": "lfg", "createdAt": created, "author": {"userName": h, "followers": foll}}


class Crew(unittest.TestCase):
    def test_round_features_signal_and_page(self):
        tmp = tempfile.mkdtemp()
        hype = os.path.join(tmp, "hype.db")
        h = sqlite3.connect(hype)
        h.execute("CREATE TABLE chain_trades (sig TEXT, wallet TEXT, mint TEXT, side TEXT, ts INTEGER, sol REAL, PRIMARY KEY (sig, mint))")
        h.execute("INSERT INTO chain_trades VALUES ('b1', ?, ?, 'buy', ?, 1.0)", (W_INS, MINT, NOW - 7200))     # bought 1 h before the call
        h.commit(); h.close()
        con = kstore.connect(os.path.join(tmp, "kol.db"))
        from kol import idents
        idents.save(con, [{"wallet": W_INS, "name": "wirelyss", "twitter": "wirelyss", "telegram": None, "pnl": 1, "wins": 1, "losses": 0, "rank": 1}], "kolscan")
        con.execute("INSERT INTO kols (handle, followers) VALUES ('unipcs', 500000)")
        con.execute("INSERT INTO calls (tweet_id, token, handle, ts, kind, followers) VALUES ('777', ?, 'unipcs', ?, 'call', 500000)", (MINT, NOW - 3600))
        con.execute("INSERT INTO calls (tweet_id, token, handle, ts, kind, followers) VALUES ('778', 'OTHER', 'nobody', ?, 'call', 300)", (MINT and NOW - 3600,))
        con.commit()
        self.assertEqual([c[0] for c in crew.due_calls(con, CFG, NOW)], ["777"])         # small account: not read
        asked = []

        def get(url, params):
            asked.append(url.rsplit("/", 1)[-1])
            if url.endswith("replies"):
                return {"tweets": [_tw("wirelyss", 36800, NOW - 3600 + 120), _tw("smallfry", 200, NOW - 3600 + 60)]}
            if url.endswith("quotes"):
                return {"tweets": [_tw("moby", 90000, NOW - 3600 + 600)]}
            return {"users": [{"userName": "retweeter", "followers": 25000}]}
        n_calls, n_eng, n_ins = crew.run(con, CFG, hype, get=get, now=NOW, log=lambda s: None)
        self.assertEqual((n_calls, n_eng, n_ins), (1, 4, 1))
        self.assertEqual(sorted(asked), ["quotes", "replies", "retweeters"])
        self.assertEqual(crew.run(con, CFG, hype, get=get, now=NOW, log=lambda s: None), (0, 0, 0))   # read once
        rows = {r[0]: r for r in con.execute("SELECT engager, kind, followers, delay_s, wallet, bought_before FROM engagers")}
        self.assertEqual(rows["wirelyss"][4], W_INS)
        self.assertEqual((rows["wirelyss"][5], rows["moby"][5], rows["retweeter"][3]), (1, 0, None))
        self.assertEqual(rows["wirelyss"][3], 120)
        kol_db = os.path.join(tmp, "kol.db")
        flags = crew.token_crew(kol_db, [MINT], NOW - 86400, CFG)
        self.assertEqual(flags[MINT], {"big": 3, "insider": 1})                            # wirelyss, moby, retweeter
        sig = crew.signals(kol_db, NOW - 86400, CFG)
        self.assertEqual(len(sig), 1)
        self.assertIn("3 velika računa", sig[0][2])
        html = crew.html(con, "unipcs")
        self.assertIn("@wirelyss", html)
        self.assertIn("1× kupio prije poziva", html)
        self.assertIn("On pojačava", crew.html(con, "wirelyss"))
        from ui import confidence
        hi, parts = confidence.score(hype=60, features={"ekipa_insajder": 1.0}, mcap=250_000)
        self.assertTrue(any("Ekipa" in t for _, t in parts))
        con.close()


if __name__ == "__main__":
    unittest.main()
