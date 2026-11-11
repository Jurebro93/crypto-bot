"""Grokovi prijedlozi na Autopilotu (10.11., Jure: "prihvaćaju li se promjene kad kliknem Prihvati?" -> "napravi oboje"):
the buttons say what they do; "Primijeni na bota" now also sets the per-token SOL cap, the no-signal rule and the run-up
cap, each moving its flag from off to shadow only; applied caller weights rank the auto pick under caller_weights; the
MCP shows what was applied and the values in force.

    python3 -m unittest tests.test_primijeni_offline
"""
import json
import os
import sqlite3
import sys
import tempfile
import time
import unittest
from urllib.parse import unquote

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from league import copy, flags, store  # noqa: E402
from trade import executor, settings  # noqa: E402
from ui import assistnotes, autopilot  # noqa: E402

NOW = int(time.time())
MINT = "So11111111111111111111111111111111111111117"


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = self.tmp.name
        self._saved = (settings.DB, store.DB, os.environ.get("TRADE_OWNER"), os.environ.get("KOL_DB"),
                       os.environ.get("HYPE_DB"), os.environ.get("WALLET_DB"))
        settings.DB, store.DB = os.path.join(d, "trade.db"), os.path.join(d, "league.db")
        os.environ.update(TRADE_OWNER="Jure", KOL_DB=os.path.join(d, "kol.db"), HYPE_DB=os.path.join(d, "hype.db"),
                          WALLET_DB=os.path.join(d, "wallets.db"))
        settings._FLAG_CACHE.clear()
        self.tc = executor.connect(settings.DB)
        self.lc = store.connect(store.DB)
        copy.ensure(self.lc)
        assistnotes.ensure(self.tc)

    def tearDown(self):
        settings.DB, store.DB = self._saved[:2]
        for k, v in zip(("TRADE_OWNER", "KOL_DB", "HYPE_DB", "WALLET_DB"), self._saved[2:]):
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        settings._FLAG_CACHE.clear()
        self.tc.close()
        self.lc.close()
        self.tmp.cleanup()

    def suggest(self, pc):
        self._n = getattr(self, "_n", 0) + 1
        out = assistnotes.submit_suggestion(self.tc, f"k{self._n}", "t", "i", proposed_change=pc)
        return out["id"] if isinstance(out, dict) else out


class Apply(Base):
    def test_accept_changes_nothing_apply_changes_and_moves_the_flag_to_shadow_only(self):
        nid = self.suggest({"key": "dca_token_cap", "to": 0.2})
        assistnotes.decide(self.tc, nid, "prihvaćeno")
        self.assertIsNone(settings.raw(self.tc).get("dca_token_cap"))          # "Označi prihvaćenim": nothing changed
        self.assertEqual(settings.flag("dca_cap", con=self.tc), "off")
        nid = self.suggest({"key": "dca_token_cap", "from": 0.3, "to": 0.2})
        st, words = assistnotes.apply(self.tc, nid)
        self.assertEqual(st, "primijenjeno")
        self.assertIn("sjena", words)
        self.assertEqual(settings.raw(self.tc)["dca_token_cap"], 0.2)
        self.assertEqual(settings.flag("dca_cap", con=self.tc), "shadow")
        settings.put(self.tc, "backtest:runup_default", {"pass": True})
        settings.set_flag(self.tc, "runup_default", "paper", "Jure")
        assistnotes.apply(self.tc, self.suggest({"key": "runup_max", "to": 15}))   # "15" = 15 %
        self.assertEqual(settings.raw(self.tc)["runup_max"], 0.15)
        self.assertEqual(settings.flag("runup_default", con=self.tc), "paper")   # an owner's choice stays
        assistnotes.apply(self.tc, self.suggest({"key": "require_signal", "to": True}))
        self.assertEqual(settings.flag("require_signal", con=self.tc), "shadow")
        assistnotes.apply(self.tc, self.suggest({"caller": "@Ansem", "platform": "x", "weight": 1.5}))
        self.assertEqual(settings.flag("caller_weights", con=self.tc), "shadow")
        with self.assertRaises(ValueError):
            assistnotes.apply(self.tc, self.suggest({"key": "dca_token_cap", "to": 9}))
        for f in ("dca_cap", "require_signal", "runup_default", "caller_weights"):
            self.assertNotEqual(settings.flag(f, con=self.tc), "live")

    def test_effective_values_and_the_applied_log_for_grok(self):
        nid = self.suggest({"key": "dca_token_cap", "to": 0.25})
        assistnotes.apply(self.tc, nid)
        eff = assistnotes.effective(self.tc)
        self.assertEqual(eff["dca_token_cap"], {"value": 0.25, "flag": "dca_cap", "flag_mode": "shadow"})
        self.assertEqual(eff["runup_max"]["value"], copy.RUNUP_DEFAULT)
        self.assertFalse(eff["require_signal"]["value"])
        a = assistnotes.applied(self.tc)[0]
        self.assertEqual((a["note_id"], a["key"], a["new"]), (nid, "dca_token_cap", 0.25))

    def test_mcp_scoring_config_and_notes_show_what_was_applied(self):
        from ui import mcpdata
        nid = self.suggest({"key": "tp_default", "to": 30})
        assistnotes.apply(self.tc, nid)
        self.tc.commit()
        cfg = mcpdata.scoring_config()
        self.assertEqual(cfg["applied_suggestions"][0]["key"], "tp_default")
        self.assertEqual(cfg["effective_values"]["tp_default"]["value"], 30)
        self.assertIn("dca_token_cap", cfg["effective_values"])
        rows = mcpdata.assistant_notes(status="primijenjeno")["rows"]
        self.assertEqual((rows[0]["applied_key"], rows[0]["new_value"]), ("tp_default", 30))
        self.assertIsNotNone(rows[0]["applied_ts"])


class AcceptedAndOwnerList(Base):
    """10.11. (Jure: "16 prihvaćenih bilješki nije ništa promijenilo ... primijeni #41 odmah, uvezi težine #45-#62,
    #40 #42 #43 #44 iza zastavica u sjenu, status primijenjeno s applied_ts")."""

    def test_an_accepted_note_can_still_be_applied_a_rejected_cannot(self):
        nid = self.suggest({"key": "tp_default", "to": 30})
        assistnotes.decide(self.tc, nid, "prihvaćeno")
        st, _ = assistnotes.apply(self.tc, nid)
        self.assertEqual(st, "primijenjeno")
        self.assertEqual(settings.raw(self.tc)["tp_default"], 30)
        nid2 = self.suggest({"key": "tp_default", "to": 50})
        assistnotes.decide(self.tc, nid2, "odbijeno")
        with self.assertRaises(ValueError):
            assistnotes.apply(self.tc, nid2)

    def test_the_owners_list_is_applied_once_and_every_note_says_so(self):
        for _ in range(62):
            self.suggest({"key": "tp_default", "to": 20})     # notes #1..#62 exist; some get accepted first
        for nid in (41, 45, 46, 56):
            assistnotes.decide(self.tc, nid, "prihvaćeno")
        done = assistnotes.owner_once(self.tc)
        self.assertTrue(any("#41 sl_default 60 → 30" in t for t in done))
        self.assertEqual(settings.raw(self.tc)["sl_default"], 30)
        w = settings.raw(self.tc)["caller_weights"]
        self.assertEqual((w["0xMarko77"], w["ddddddd8a"], w["tg:what_yteiiiidbdksndjdb"], w["Strong69106"]),
                         (1.4, 0.5, 0.3, 0.5))
        self.assertEqual(len(w), 11)
        for f in ("caller_weights", "require_signal", "runup_default", "dca_cap", "caller_ev_rank"):
            self.assertEqual(settings.flag(f, con=self.tc), "shadow")
        self.assertEqual(settings.raw(self.tc)["dca_token_cap"], 0.3)
        self.assertEqual(settings.raw(self.tc)["runup_max"], 0.10)
        rows = {r["id"]: r for r in assistnotes.notes(self.tc, "primijenjeno", "suggestion", 100, 0)[0]}
        for nid in (40, 41, 42, 43, 44, 45, 46, 47, 48, 56, 57, 58, 59, 60, 61, 62):
            self.assertIn(nid, rows)
        log = assistnotes.applied(self.tc, 200)
        self.assertTrue(any(a["note_id"] == 41 and a["key"] == "sl_default" and (a["old"], a["new"]) == (60, 30)
                            for a in log))
        self.assertTrue(any(a["note_id"] == 44 and a["key"] == "flag:caller_ev_rank" and a["new"] == "shadow"
                            for a in log))
        self.assertEqual(assistnotes.owner_once(self.tc), [])                 # never twice
        self.assertEqual(settings.raw(self.tc)["sl_default"], 30)

    def test_mcp_notes_show_applied_ts_for_the_owners_list(self):
        from ui import mcpdata
        for _ in range(45):
            self.suggest({"key": "tp_default", "to": 20})
        assistnotes.owner_once(self.tc)
        self.tc.commit()
        rows = {r["id"]: r for r in mcpdata.assistant_notes(status="primijenjeno", limit=100)["rows"]}
        self.assertEqual((rows[41]["applied_key"], rows[41]["old_value"], rows[41]["new_value"]), ("sl_default", 60, 30))
        self.assertIsNotNone(rows[41]["applied_ts"])
        self.assertEqual(rows[45]["new_value"], 1.4)

    def test_the_page_lists_accepted_notes_with_the_apply_button(self):
        from ui import pravitrade
        pravitrade._LIVE_CACHE.clear()
        pravitrade._LIVE_FAIL.clear()
        nid = self.suggest({"key": "tp_default", "to": 30})
        assistnotes.decide(self.tc, nid, "prihvaćeno")
        _, body = pravitrade.page({}, "Jure")
        self.assertIn("Prihvaćeni, još nisu primijenjeni", body)
        self.assertIn("1 prihvaćeno bez promjene", body)
        loc = unquote(pravitrade.post("/pravi-trade/asapply", {"id": str(nid)}, "Jure"))
        self.assertIn("Primijenjeno", loc)


class CleanList(Base):
    def test_accepted_critique_without_an_applicable_change_leaves_the_page(self):
        """11.11. (Jure: "lista treba biti čista ako nema što što zahtijeva pažnju")."""
        from ui import pravitrade
        nid = self.suggest(None)
        assistnotes.decide(self.tc, nid, "prihvaćeno")
        self.assertEqual(pravitrade._suggest_section(self.tc, True), "")           # nothing needs the owner
        nid2 = self.suggest({"key": "tp_default", "to": 30})
        assistnotes.decide(self.tc, nid2, "prihvaćeno")
        html = pravitrade._suggest_section(self.tc, True)
        self.assertIn(f"as-{nid2}", html)
        self.assertNotIn(f"as-{nid}\"", html)
        self.assertIn("1 prihvaćeno bez promjene", html)


class Page(Base):
    def test_the_buttons_say_what_they_do(self):
        from ui import pravitrade
        pravitrade._LIVE_CACHE.clear()
        pravitrade._LIVE_FAIL.clear()
        self.suggest({"key": "tp_default", "to": 30})
        _, body = pravitrade.page({}, "Jure")
        self.assertIn("Označi prihvaćenim (bez promjene)", body)
        self.assertIn("Primijeni na bota", body)
        self.assertNotIn(">Prihvati<", body)


class DcaCap(Base):
    def position(self, sol):
        self.tc.execute("INSERT INTO positions (token, opened_ts, mode, status, sol_in) VALUES (?,?,?,?,?)",
                        (MINT, NOW, "dry", "open", sol))
        self.tc.commit()

    def test_cap_refuses_live_logs_in_shadow_and_is_silent_off(self):
        from ui import pravitrade
        self.position(0.25)
        pravitrade._owner_buy_rules(self.lc, self.tc, MINT, 0.1, NOW)              # off: nothing
        self.assertEqual(flags.shadow_rows(self.lc, "dca_cap"), [])
        settings.set_flag(self.tc, "dca_cap", "shadow", "Jure")
        pravitrade._owner_buy_rules(self.lc, self.tc, MINT, 0.1, NOW)              # shadow: logged, goes through
        self.assertEqual(len(flags.shadow_rows(self.lc, "dca_cap")), 1)
        settings.put(self.tc, "backtest:dca_cap", {"pass": True})
        settings.put(self.tc, "flag:dca_cap", {"mode": "live", "since": NOW})
        settings._FLAG_CACHE.clear()
        with self.assertRaisesRegex(ValueError, "najviše 0.3 SOL po tokenu"):
            pravitrade._owner_buy_rules(self.lc, self.tc, MINT, 0.1, NOW)
        pravitrade._owner_buy_rules(self.lc, self.tc, MINT, 0.05, NOW)             # 0.30 fits


class Signal(Base):
    def kol(self, rows):
        con = sqlite3.connect(os.environ["KOL_DB"])
        con.execute("CREATE TABLE IF NOT EXISTS calls (tweet_id TEXT, token TEXT, handle TEXT, ts INTEGER, kind TEXT)")
        con.executemany("INSERT INTO calls VALUES (?,?,?,?,?)", rows)
        con.commit()
        con.close()

    def wallets(self, tiers, buys):
        w = sqlite3.connect(os.environ["WALLET_DB"])
        w.execute("CREATE TABLE IF NOT EXISTS wallets (wallet TEXT PRIMARY KEY, tier TEXT)")
        w.executemany("INSERT INTO wallets VALUES (?,?)", tiers)
        w.commit()
        w.close()
        h = sqlite3.connect(os.environ["HYPE_DB"])
        h.execute("CREATE TABLE IF NOT EXISTS chain_trades (sig TEXT, wallet TEXT, mint TEXT, side TEXT, ts INTEGER, sol REAL)")
        h.executemany("INSERT INTO chain_trades VALUES (?,?,?,?,?,?)", buys)
        h.commit()
        h.close()

    def test_a_caller_or_a_tiered_wallet_is_a_signal_nothing_else_is(self):
        self.assertFalse(copy.signal_for(MINT, NOW)[0])
        self.kol([("w1", MINT, "w:abc", NOW - 60, "call"), ("x0", MINT, "ansem", NOW - 7200, "call")])
        self.assertFalse(copy.signal_for(MINT, NOW)[0])                           # a pseudo-call and an old call
        self.wallets([("W1", "C"), ("W2", "A")], [("s1", "W1", MINT, "buy", NOW - 30, 0.5)])
        self.assertFalse(copy.signal_for(MINT, NOW)[0])                           # tier C is not enough
        self.assertTrue(copy.signal_for(MINT, NOW, wallet="W2")[0])               # the copied wallet has a tier
        self.wallets([], [("s2", "W2", MINT, "buy", NOW - 30, 0.5)])
        self.assertTrue(copy.signal_for(MINT, NOW)[0])
        self.kol([("x1", MINT + "z", "ansem", NOW - 60, "call")])
        self.assertTrue(copy.signal_for(MINT + "z", NOW)[0])

    def test_wallet_copy_gate_live_skips_shadow_logs_kol_always_passes(self):
        f = {"id": 7, "kind": "wallet", "target": "W9", "user": settings.LEAGUE_USER, "exit": {}}
        self.assertIsNone(copy._signal_gate(self.lc, f, MINT, NOW, "off"))
        self.assertIsNone(copy._signal_gate(self.lc, f, MINT, NOW, "shadow"))
        self.assertEqual(len(flags.shadow_rows(self.lc, "require_signal")), 1)
        self.assertIn("bez signala", copy._signal_gate(self.lc, f, MINT, NOW, "live"))
        k = dict(f, kind="kol", target="ansem")
        self.assertIsNone(copy._signal_gate(self.lc, k, MINT, NOW, "live"))
        self.assertIsNone(copy._signal_gate(self.lc, dict(f, user="Ivan"), MINT, NOW, "live"))   # players never


class RunupCap(Base):
    def test_the_applied_cap_is_the_flags_cap(self):
        copy.apply_cfg_overrides()
        self.assertEqual(copy._RUNUP["cap"], copy.RUNUP_DEFAULT)
        settings.put(self.tc, "runup_max", 0.25)
        copy.apply_cfg_overrides()
        self.assertEqual(copy._RUNUP["cap"], 0.25)
        settings.put(self.tc, "runup_max", 7)                                       # nonsense: the default holds
        copy.apply_cfg_overrides()
        self.assertEqual(copy._RUNUP["cap"], copy.RUNUP_DEFAULT)


class Weights(unittest.TestCase):
    def rows(self):
        return [{"handle": h, "s": {"score": sc}} for h, sc in (("a", 0.30), ("B", 0.20), ("c", 0.10), ("d", -0.05))]

    def test_weights_reorder_drop_at_zero_and_keep_direction_for_negative_scores(self):
        self.assertEqual([r["handle"] for r in autopilot._weighted(self.rows(), {})], ["a", "B", "c", "d"])
        out = autopilot._weighted(self.rows(), {"b": 2.0, "@A": 0, "d": 1.5})
        self.assertEqual([r["handle"] for r in out], ["B", "c", "d"])   # a dropped, B doubled to the top
        low = autopilot._weighted(self.rows(), {"d": 0.5})
        self.assertEqual(low[-1]["handle"], "d")                          # a lower weight never lifts a negative score


if __name__ == "__main__":
    unittest.main()
