"""Grokovi prijedlozi skupno (12.11., Jure: "Možeš nekako grupirati ove prijedloge od groka ... teško mi je jedan po
jedan svaki put otvarati prijedloge i onda ići dolje do prihvati, primjeni na bota"): one tick per suggestion, all
ticked, one "Primijeni označene na bota" / "Odbij označene"; each goes through the same apply() (allow-list, ranges,
flags at most to shadow), newest first, and an older one changing the same setting is rejected as superseded.

    python3 -m unittest tests.test_prijedlozi_skupno_offline
"""
import json
import os
import re
import sys
import unittest
from urllib.parse import unquote

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tests.test_primijeni_offline import Base  # noqa: E402
from trade import settings  # noqa: E402
from ui import assistnotes  # noqa: E402


def status(con, nid):
    return con.execute("SELECT status, owner_note FROM assistant_notes WHERE id=?", (nid,)).fetchone()


class ApplyMany(Base):
    def test_all_ticked_apply_in_one_tap_newest_wins_bad_ones_wait(self):
        tp_old = self.suggest({"key": "tp_default", "to": 40})
        cap = self.suggest({"key": "dca_token_cap", "to": 0.2})
        crit = self.suggest(None)                                   # a critique: only marked accepted
        bad = self.suggest({"key": "sl_default", "to": 33})          # not one of SL_CHOICES: refused, keeps waiting
        tp_new = self.suggest({"key": "tp_default", "to": 30})
        res = assistnotes.apply_many(self.tc, [tp_old, cap, crit, bad, tp_new])
        self.assertEqual(settings.raw(self.tc)["tp_default"], 30)  # the newest one is in force
        self.assertEqual(settings.raw(self.tc)["dca_token_cap"], 0.2)
        self.assertEqual(settings.flag("dca_cap", con=self.tc), "shadow")   # never live from here
        self.assertEqual(sorted(i for i, _w in res["applied"]), sorted([cap, tp_new]))
        self.assertEqual(res["accepted"], [crit])
        self.assertEqual(res["superseded"], [(tp_old, tp_new, "tp_default")])
        self.assertEqual([i for i, _w in res["failed"]], [bad])
        self.assertEqual(status(self.tc, tp_old)[0], "odbijeno")
        self.assertIn(f"#{tp_new}", status(self.tc, tp_old)[1])
        self.assertEqual(status(self.tc, bad)[0], "novo")
        self.assertEqual(status(self.tc, crit)[0], "prihvaćeno")
        words = assistnotes.bulk_words(res)
        self.assertIn("Primijenjeno 2", words)
        self.assertIn("nije prošlo 1", words)

    def test_post_routes_only_the_ticked_ones(self):
        from ui import pravitrade
        a = self.suggest({"key": "tp_default", "to": 30})
        b = self.suggest({"key": "max_open", "to": 2})
        loc = unquote(pravitrade.post("/pravi-trade/asbulk", {f"sel_{a}": "1", "_csrf": "x"}, "Jure"))
        self.assertIn("Primijenjeno 1", loc)
        self.assertEqual(status(self.tc, a)[0], "primijenjeno")
        self.assertEqual(status(self.tc, b)[0], "novo")
        loc = unquote(pravitrade.post("/pravi-trade/asbulkno", {f"sel_{b}": "1"}, "Jure"))
        self.assertIn("Odbijeno prijedloga: 1", loc)
        self.assertEqual(status(self.tc, b)[0], "odbijeno")
        self.assertIn("err=", pravitrade.post("/pravi-trade/asbulk", {}, "Jure"))                 # nothing ticked
        self.assertIn("err=", pravitrade.post("/pravi-trade/asbulk", {f"sel_{a}": "1"}, "Netko")) # owner only

    def test_accepted_ones_can_be_applied_in_bulk_too(self):
        nid = self.suggest({"key": "tp_default", "to": 25})
        assistnotes.decide(self.tc, nid, "prihvaćeno")
        res = assistnotes.apply_many(self.tc, [nid])
        self.assertEqual([i for i, _w in res["applied"]], [nid])
        self.assertEqual(settings.raw(self.tc)["tp_default"], 25)

    def test_caller_weights_conflict_by_handle(self):
        self.assertEqual(assistnotes.change_key({"caller": "@Ansem", "weight": 1}), "caller_weights.Ansem")
        self.assertEqual(assistnotes.change_key({"caller": "x", "platform": "telegram", "weight": 1}),
                         "caller_weights.tg:x")
        self.assertIsNone(assistnotes.change_key({"key": "auto_skip", "to": [["kol", "a"]]}))   # appends, no conflict
        self.assertIsNone(assistnotes.change_key({"key": "grok_max_sol_per_trade", "to": 1}))  # not applicable


class Page(Base):
    def test_one_bar_ticks_for_every_waiting_one_and_folded_details(self):
        from ui import pravitrade
        a = self.suggest({"key": "tp_default", "to": 30})
        b = self.suggest(None)
        c = self.suggest({"key": "max_open", "to": 2})
        assistnotes.decide(self.tc, c, "prihvaćeno")
        html = pravitrade._suggest_section(self.tc, True)
        self.assertEqual(html.count("id=as-bulk"), 1)
        self.assertIn("Primijeni označene na bota", html)
        self.assertIn("Odbij označene", html)
        for nid in (a, b, c):
            self.assertRegex(html, rf'form=as-bulk name=sel_{nid} value=1 data-keep data-what="[^"]+" checked')
        self.assertIn(f'data-what="#{a} tp_default', html)
        self.assertIn(f'data-what="#{b} samo označi prihvaćenim', html)
        self.assertIn(f"id=as-more-{a}", html)                 # reasoning and single buttons folded under the row
        # the bulk bar's confirm is valid JS: the two \n are escaped once in the page
        onclick = re.search(r'<button class=ap-buy onclick="([^"]+)">Primijeni označene', html).group(1)
        self.assertIn("\\n\\n", onclick)
        self.assertNotIn("\\\\n", onclick)

    def test_patch_keeps_the_ticks(self):
        from ui import pravitrade
        self.assertIn("input[data-keep]", pravitrade.PATCH_JS)


FULL = "7xKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU"
OTHER = "9WzDXwBbmkg8ZTbNMqUxvQRAyrZzDsGYdLVL9zYtAWWM"


class InsiderWallet(Base):
    """12.11. (owner's screenshot: "nije prošlo 3: #190 insider_label.wallet nije Solana adresa")."""

    def setUp(self):
        super().setUp()
        self._early = os.environ.get("EARLY_DB")
        os.environ["EARLY_DB"] = os.path.join(self.tmp.name, "early.db")
        from kol import precall
        con = precall.connect(os.environ["EARLY_DB"])
        con.execute("INSERT INTO precall_wallets (wallet, status) VALUES (?, 'candidate'), (?, 'candidate')",
                    (FULL, OTHER))
        con.commit()
        con.close()

    def tearDown(self):
        if self._early is None:
            os.environ.pop("EARLY_DB", None)
        else:
            os.environ["EARLY_DB"] = self._early
        super().tearDown()

    def test_a_shortened_address_with_one_match_is_resolved(self):
        from kol import precall
        self.assertEqual(precall.resolve_wallet("7xKX…gAsU"), FULL)
        self.assertEqual(precall.resolve_wallet("7xKX...gAsU"), FULL)
        self.assertIsNone(precall.resolve_wallet("7xkx…gasu"))           # base58 is case-sensitive
        self.assertIsNone(precall.resolve_wallet("Zzzz…zzzz"))
        out = assistnotes.submit_suggestion(self.tc, "k1", "t", "i", proposed_change={
            "insider_label": {"wallet": "7xKX…gAsU", "label": "bot", "note": "n"}})
        nid = out["id"] if isinstance(out, dict) else out
        pc = assistnotes.notes(self.tc, "novo", "suggestion", 5, 0)[0][0]["proposed_change"]
        self.assertEqual(pc["insider_label"]["wallet"], FULL)            # stored with the full address
        res = assistnotes.apply_many(self.tc, [nid])
        self.assertEqual([i for i, _w in res["applied"]], [nid])
        self.assertEqual(settings.raw(self.tc)["insider_labels"][FULL]["label"], "bot")

    def test_a_bad_address_is_refused_on_arrival_and_left_unticked_on_the_page(self):
        with self.assertRaisesRegex(ValueError, "full wallet address"):
            assistnotes.submit_suggestion(self.tc, "k2", "t", "i", proposed_change={
                "insider_label": {"wallet": "nekiwallet", "label": "bot"}})
        # an older note stored before the check (as #175, #176, #190 in production)
        assistnotes.ensure(self.tc)
        nid = self.suggest({"key": "tp_default", "to": 30})
        self.tc.execute("UPDATE assistant_notes SET proposed_change=? WHERE id=?",
                        ('{"insider_label": {"wallet": "Abc…xyz", "label": "bot"}}', nid))
        self.tc.commit()
        from ui import pravitrade
        html = pravitrade._suggest_section(self.tc, True)
        self.assertIn("Ne može se primijeniti", html)
        self.assertRegex(html, rf'name=sel_{nid} value=1 data-keep data-what="[^"]+">')   # no "checked"
        res = assistnotes.apply_many(self.tc, [nid])
        self.assertIn("nije puna Solana adresa", res["failed"][0][1])


class InsiderWallets(InsiderWallet):
    """12.11. 13:28 (owner's screenshot): Grok labels the wallets of one token together:
    {"insider_label": {"token": <mint>, "wallets": [a, b], "label": "bot", "note": ...}}."""

    TOKEN = "A2sdaK6XiHLnREKQtqyosScUd1XBCK8xKBu6iMgDpump"

    def test_several_wallets_of_one_token_apply_together(self):
        pc = {"insider_label": {"token": self.TOKEN, "wallets": [FULL, "9WzD…AWWM"], "label": "bot",
                                "note": "flip botovi"}}
        out = assistnotes.submit_suggestion(self.tc, "k3", "t", "i", proposed_change=pc)
        nid = out["id"] if isinstance(out, dict) else out
        stored = assistnotes.notes(self.tc, "novo", "suggestion", 5, 0)[0][0]["proposed_change"]["insider_label"]
        self.assertEqual(stored["wallets"], [FULL, OTHER])              # the shortened one resolved
        from ui import pravitrade
        html = pravitrade._suggest_section(self.tc, True)
        self.assertIn("oznaka 2 novčanika 7xKXtg…, 9WzDXw… → bot (token A2sdaK…)", html)
        self.assertNotIn("Ne može se primijeniti", html)
        res = assistnotes.apply_many(self.tc, [nid])
        self.assertEqual([i for i, _w in res["applied"]], [nid])
        labels = settings.raw(self.tc)["insider_labels"]
        self.assertEqual((labels[FULL]["label"], labels[OTHER]["label"]), ("bot", "bot"))
        self.assertEqual(labels[OTHER]["token"], self.TOKEN)
        self.assertIn("oznaka 2 novčanika", res["applied"][0][1])

    def test_an_old_note_with_full_wallets_is_applied(self):
        """As #175 / #176 / #190 in production: stored before 12.11. with "wallets", full addresses."""
        nid = self.suggest({"key": "tp_default", "to": 30})
        self.tc.execute("UPDATE assistant_notes SET proposed_change=? WHERE id=?", (json.dumps(
            {"insider_label": {"token": self.TOKEN, "wallets": [FULL, OTHER], "label": "bot", "note": "x"}}), nid))
        self.tc.commit()
        self.assertIsNone(assistnotes.blocker({"insider_label": {"wallets": [FULL, OTHER], "label": "bot"}}))
        res = assistnotes.apply_many(self.tc, [nid])
        self.assertEqual(res["failed"], [])
        self.assertEqual(settings.raw(self.tc)["insider_labels"][OTHER]["label"], "bot")

    def test_no_wallet_at_all_says_so(self):
        self.assertIn("nema novčanik", assistnotes.blocker({"insider_label": {"token": self.TOKEN, "label": "bot"}}))


if __name__ == "__main__":
    unittest.main()
