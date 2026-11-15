"""15.11. (Jure, two asks about the Autopilot page):

1. "Previše vertikalnog mjesta zauzimaju prekidači, svaka kartica mora biti minimizirana i tek na dodir se otvori i
   proširi." Every card in "Prekidači" is one closed row (name, one line, its state) that opens on a tap; only Grok's
   requests that wait for his Odobri / Odbij come open (they expire).
2. "Ovdje pod preporuke alata karticu stavi OpenAI preporuke koje se mogu jednom prihvatiti i primijeniti na bota ili
   odbiti. I nakon svakoga audita algoritma i baze tu izlaze prijedlozi." The OpenAI critic's suggestions have their
   own card under "Preporuke alata" (always there, with the newest review's summary); Grok's "Prijedlozi asistenta"
   leaves them out.

    python3 -m unittest tests.test_prekidaci_1511_offline
"""
import os
import re
import sys
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import tests.test_raspored_1411_offline as base  # noqa: E402  (module import: its own test classes are not rerun here)
from ui import assistnotes, mcpapi  # noqa: E402

REQ = base.REQ


class _Base(base.Layout):
    """The 14.11. layout fixture (Card's database, scenario, page) without its tests."""


for _n in dir(base.Layout):
    if _n.startswith("test_"):
        setattr(_Base, _n, None)


class Prekidaci(_Base):
    def switches(self, body):
        return body[body.index("id=prekidaci"):body.index("id=apx-ostalo")]

    def test_every_card_is_one_closed_row_with_its_state(self):
        self.scenario(time.time())   # Grok on, an exit plan on MINT
        sw = self.switches(self.page("Jure", {"sve": "1"}))
        for iid in ("sw-pravi", "sw-grok", "sw-planovi"):
            m = re.search(rf"<details class=ap-it id={iid}( open)?>", sw)
            self.assertIsNotNone(m, iid)
            self.assertIsNone(m.group(1), f"{iid} must start closed")
        pravi = sw[sw.index("id=sw-pravi"):sw.index("</details>", sw.index("id=sw-pravi"))]
        self.assertIn("Pravi novac za sve strategije", pravi)
        self.assertRegex(pravi, r"uključen|isključen")
        self.assertIn("danas kupnji", pravi)                                   # today's numbers in the closed row
        # the content is still in the page (a kill switch is never lazy), only folded
        for k in ("name=name value=pravi_novac_sve", "Ugasi Grok autotrade", "Pauziraj exit planove", "id=grok-auto"):
            self.assertIn(k, sw, k)
        self.assertIn("id=fl-pravi_novac_sve", sw)

    def test_a_waiting_grok_request_is_a_badge_on_the_closed_card(self):
        # 15.11. navečer (owner, the 3rd time: "minimizira pa da se na klikom na karticu otvori tijelo"): the request
        # opens nothing by itself: a badge on the closed card, a closed row inside; his tap opens it
        code, out = mcpapi.trade_request({"token": REQ, "side": "buy", "amount": 0.1, "require_approval": True,
                                          "reason": "range dno"})
        self.assertEqual(out["status"], "pending_approval", out)
        sw = self.switches(self.page())
        self.assertIn('<details class="apx-acc apx-sws" id=prekidaci-d data-tap><summary>', sw)
        self.assertIn('<b class=apx-swbadge title="Grokov zahtjev čeka tvoje Odobri / Odbij">1 čeka</b>', sw)
        self.assertRegex(sw, r"\d+ prekidača, \d+ uključen\w*, 1 čeka tebe")
        self.assertIn("<details class=ap-it id=sw-mcp>", sw)
        self.assertNotRegex(sw, r"<details[^>]*\sopen[\s>]")
        self.assertIn("action=/pravi-trade/mcpok", sw)                         # the buttons are inside, folded

    def test_no_request_no_request_row(self):
        self.assertNotIn("id=sw-mcp", self.switches(self.page()))


class OpenAIPreporuke(_Base):
    def note(self, kid, title, change=None):
        return assistnotes.submit_suggestion(self.con, kid, title, interpretation="obrazloženje " + title,
                                             proposed_change=change)

    def card(self, body, sid):
        i = body.index(f"id={sid}")
        return body[i:body.index("</details>", body.index("<div class=in>", i))]

    def test_critic_suggestions_have_their_own_card_under_preporuke_alata(self):
        self.note(assistnotes.CRITIC_KID, "Stop momentuma preuzak", {"key": "sl_default", "to": 30})
        self.note(assistnotes.key_id("grok-key"), "Grokov prijedlog")
        body = self.page("Jure", {"sve": "1"})
        self.assertIn("OpenAI preporuke", body)
        self.assertGreater(body.index("id=openai-prijedlozi"), body.index("id=preporuke"))   # under Preporuke alata
        oa = body[body.index("id=openai-prijedlozi"):]
        oa = oa[:oa.index("</section>")] if "</section>" in oa else oa
        self.assertIn("Stop momentuma preuzak", oa)
        self.assertNotIn("Grokov prijedlog", oa)
        self.assertIn("form=oa-bulk", oa)
        self.assertIn("<form id=oa-bulk method=post action=/pravi-trade/asbulk", oa)
        for k in ("action=/pravi-trade/asok", "formaction=/pravi-trade/asno", "formaction=/pravi-trade/asapply"):
            self.assertIn(k, oa, k)
        # Grok's list leaves the critic out
        rows, total = assistnotes.notes(self.con, "novo", "suggestion", 30, 0, not_key=assistnotes.CRITIC_KID)
        self.assertEqual([r["title"] for r in rows], ["Grokov prijedlog"])
        rows, total = assistnotes.notes(self.con, "novo", "suggestion", 30, 0, key=assistnotes.CRITIC_KID)
        self.assertEqual([r["title"] for r in rows], ["Stop momentuma preuzak"])

    def test_card_is_there_without_suggestions_and_shows_the_newest_review(self):
        assistnotes.submit_daily_summary(self.con, assistnotes.CRITIC_KID, "Dubinski pregled",
                                         interpretation="Edge nije dokazan ni u jednoj strategiji (n < 30).")
        body = self.page("Jure", {"sve": "1"})
        self.assertIn("id=openai-prijedlozi", body)
        oa = body[body.index("id=openai-prijedlozi"):]
        self.assertIn("ništa ne čeka", oa[:600])
        self.assertIn("Dubinski pregled", oa)
        self.assertIn("Edge nije dokazan", oa)

    def test_a_viewer_does_not_see_the_card(self):
        self.note(assistnotes.CRITIC_KID, "Stop momentuma preuzak")
        self.assertNotIn("id=openai-prijedlozi", self.page("netko"))


class CriticLogLines(unittest.TestCase):
    def test_findings_and_verdicts_are_logged_one_line_each(self):
        from critic.daily import log_findings
        out = []
        log_findings(lambda m, **k: out.append(m), "dubinski", "Edge nije dokazan.",
                     [{"ozbiljnost": "visoka", "naslov": "Stop preuzak", "prijedlog": "SL -30 % uz 15 min čekanja"}],
                     [{"ime": "momentum_scalp", "presuda": "ugasi"}], ["koliko često: svaka 3 dana (malo novih podataka)", ""])
        self.assertEqual(out, ["kritičar: dubinski sažetak: Edge nije dokazan.",
                               "kritičar: dubinski nalaz [visoka] Stop preuzak → SL -30 % uz 15 min čekanja",
                               "kritičar: dubinski strategije: momentum_scalp=ugasi",
                               "kritičar: dubinski koliko često: svaka 3 dana (malo novih podataka)"])


class StoredReviewsOnce(_Base):
    def test_stored_reviews_are_logged_once(self):
        from critic import live, store
        store.ensure(self.con)
        assistnotes.submit_daily_summary(self.con, assistnotes.CRITIC_KID, "Kritičar: Dubinski pregled 15.11.",
                                         interpretation="Sažetak. " + "x" * 1000)
        assistnotes.submit_suggestion(self.con, assistnotes.CRITIC_KID, "Širi stop za kopije",
                                      interpretation="MAE pobjednika p75 −28 %", proposed_change={"key": "sl_default", "to": 30})
        assistnotes.submit_suggestion(self.con, assistnotes.key_id("grok-key"), "Grokov", interpretation="g")
        out = []
        n = live.log_stored_reviews(self.con, lambda m, **k: out.append(m))
        self.assertEqual(n, 2)
        self.assertTrue(out[0].startswith("kritičar: zapisani pregled #"))
        self.assertTrue(any("Širi stop za kopije | MAE pobjednika p75 −28 % | promjena:" in x for x in out))
        self.assertFalse(any("Grokov" in x for x in out))
        self.assertTrue(all(len(x) < 1100 for x in out))
        self.assertEqual(live.log_stored_reviews(self.con, lambda m, **k: out.append(m)), 0)   # once


if __name__ == "__main__":
    unittest.main()
