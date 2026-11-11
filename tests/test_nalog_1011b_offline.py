"""10.11. ~19:40 (Jure, chat): x_features_ingest off -> shadow, require_signal shadow -> paper, dca_cap shadow -> paper
(and smart_discovery -> shadow), each with a line in applied_log (ts, old, new) that get_scoring_config shows; never
live; once. The open Hope position's -40 % stop -> -30 % (the new sl_default), unless that would sell at once.
dca_cap in paper caps the demo account autopilot-paper at dca_token_cap SOL per token.

    python3 -m unittest tests.test_nalog_1011b_offline
"""
import json
import os
import sys
import time
import unittest
from unittest import mock
from urllib.parse import unquote

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from league import copy, flags  # noqa: E402
from trade import settings  # noqa: E402
from ui import assistnotes, mcpdata  # noqa: E402
from tests.test_primijeni_offline import Base, NOW, MINT  # noqa: E402

H = assistnotes.HOPE_MINT


class Flags(Base):
    def test_four_flags_logged_once_never_live(self):
        settings.set_flag(self.tc, "require_signal", "shadow", "t")
        settings.set_flag(self.tc, "dca_cap", "shadow", "t")
        done = assistnotes.owner_flags_b(self.tc, now=NOW)
        modes = {n: settings.flag_state(self.tc)[n]["mode"] for n, _ in assistnotes.OWNER_FLAGS_B}
        self.assertEqual(modes, {"x_features_ingest": "shadow", "require_signal": "paper", "dca_cap": "paper",
                                 "smart_discovery": "shadow", "confluence": "shadow", "exit_plans": "paper"})
        log = assistnotes.applied(self.tc)
        self.assertEqual({(x["key"], x["old"], x["new"]) for x in log},
                         {("flag:x_features_ingest", "off", "shadow"), ("flag:require_signal", "shadow", "paper"),
                          ("flag:dca_cap", "shadow", "paper"), ("flag:smart_discovery", "off", "shadow"),
                          ("flag:confluence", "off", "shadow"), ("flag:exit_plans", "off", "paper"),
                          ("dca_cap_owner", "samo zapis (shadow)", "tvrdi strop 0.3 SOL po tokenu"),
                          ("grok_autotrade", "off", "on")})
        self.assertTrue(all(x["ts"] for x in log))
        self.assertEqual(len(done), 8)
        from ui import grokauto
        self.assertTrue(grokauto.state(self.tc)["on"])                             # "Uključi je, neka Grok trada"
        self.assertEqual(assistnotes.owner_flags_b(self.tc, now=NOW), [])          # once
        self.assertNotIn("live", modes.values())
        # what Grok reads
        with mock.patch.object(mcpdata, "_ro", side_effect=lambda name: settings.connect() if name == "trade" else None):
            cfg = mcpdata.scoring_config()
        self.assertEqual(cfg["flags"]["require_signal"]["mode"], "paper")
        self.assertEqual(cfg["flags"]["x_features_ingest"]["mode"], "shadow")
        self.assertEqual(cfg["flags"]["dca_cap"]["mode"], "paper")
        self.assertIn("flag:dca_cap", [x["key"] for x in cfg["applied_suggestions"]])


class LaterOrders(Base):
    def test_each_order_once_never_live(self):
        done = assistnotes.owner_flag_orders(self.tc, now=NOW)
        self.assertEqual(done, ["zastavica market_scan: off → shadow", "zastavica group_discovery: off → shadow",
                                "zastavica range_dca: off → paper", "zastavica insider_copy: off → shadow",
                                "zastavica momentum_scalp: off → paper", "zastavica grok_ev_gate: off → shadow", "zastavica pre_shill: off → shadow",
                                "zastavica grok_predictions: off → shadow", "zastavica event_tokens: off → shadow",
                                "zastavica range_market: off → paper", "zastavica proposals: off → paper",
                                "zastavica fast_path: off → shadow",
                                "zastavica zonewatch: off → shadow", "zastavica exit_plan_live: off → live"])
        self.assertEqual(settings.flag_state(self.tc)["market_scan"]["mode"], "shadow")
        keys = {x["key"] for x in assistnotes.applied(self.tc)}
        self.assertTrue({"flag:market_scan", "flag:group_discovery", "flag:range_dca", "flag:insider_copy"} <= keys)
        settings.set_flag(self.tc, "market_scan", "off", "Jure")                   # the owner turns it off later
        self.assertEqual(assistnotes.owner_flag_orders(self.tc, now=NOW), [])     # it stays off
        self.assertEqual(settings.flag_state(self.tc)["market_scan"]["mode"], "off")


class NoteOrders(Base):
    """11.11.: Grok's accepted critiques now in the code: each note marked primijenjeno once, with what was done."""
    def note(self, nid, status):
        assistnotes.ensure(self.tc)
        self.tc.execute("INSERT INTO assistant_notes (id, ts, kind, title, status) VALUES (?,?,?,?,?)",
                        (nid, NOW, "suggestion", f"kritika {nid}", status))
        self.tc.commit()

    def test_marks_accepted_once_leaves_rejected(self):
        self.note(54, "prihvaćeno")
        self.note(96, "novo")
        self.note(74, "odbijeno")
        self.note(82, "prihvaćeno")
        done = assistnotes.owner_note_orders(self.tc, now=NOW)
        self.assertEqual(done, ["bilješka #54 primijenjena (signals_clean)", "bilješka #96 primijenjena (signals_clean)",
                                "bilješka #82 primijenjena (caller_weights)"])
        st = dict(self.tc.execute("SELECT id, status FROM assistant_notes").fetchall())
        self.assertEqual(st, {54: "primijenjeno", 96: "primijenjeno", 74: "odbijeno", 82: "primijenjeno"})
        why = self.tc.execute("SELECT owner_note FROM assistant_notes WHERE id=54").fetchone()[0]
        self.assertIn("include_hidden", why)
        self.assertIn(54, {x["note_id"] for x in assistnotes.applied(self.tc)})
        self.assertEqual(assistnotes.owner_note_orders(self.tc, now=NOW), [])      # once


class HopeStop(Base):
    def trade(self, user=settings.LEAGUE_USER, sl="-40%", entry=1.0, eff=1.02):
        tid = self.lc.execute("INSERT INTO trades (user, token, symbol, opened_ts, size_usd, status, entry_px, entry_eff, qty)"
                              " VALUES (?,?,?,?,?,?,?,?,?)", (user, H, "HOPE", NOW, 25, "open", entry, eff, 25)).lastrowid
        self.lc.commit()
        from league import auto
        auto.set_auto(self.lc, user, tid, "tpsl", "+100%", sl, from_eff=True)
        a = json.loads(self.lc.execute("SELECT auto FROM trades WHERE id=?", (tid,)).fetchone()[0])
        a["grace_until"] = NOW + 600                                               # other keys stay
        self.lc.execute("UPDATE trades SET auto=? WHERE id=?", (json.dumps(a), tid))
        self.lc.commit()
        return tid

    def auto(self, tid):
        return json.loads(self.lc.execute("SELECT auto FROM trades WHERE id=?", (tid,)).fetchone()[0])

    def test_minus_40_becomes_minus_30_from_the_same_base(self):
        tid = self.trade()
        tp0 = self.auto(tid)["tp_px"]
        done, out = assistnotes.hope_stop(self.tc, self.lc, market=lambda t: {H: (0.95, 50_000, None, 200_000)})
        self.assertTrue(done)
        a = self.auto(tid)
        self.assertAlmostEqual(a["sl_px"], 1.02 * 0.70)
        self.assertEqual((a["sl"], a["tp_px"], a["grace_until"]), ("-30%", tp0, NOW + 600))
        self.assertIn("stop -40% → -30 % od prosječnog ulaza", out[0])
        self.assertEqual(assistnotes.applied(self.tc)[0]["key"], f"sl:trade#{tid}")

    def test_not_when_it_would_sell_at_once_and_not_other_stops(self):
        tid = self.trade()
        other = self.trade(user=settings.PAPER_USER, sl="-25%")
        done, out = assistnotes.hope_stop(self.tc, self.lc, market=lambda t: {H: (0.70, 50_000, None, 150_000)})
        self.assertTrue(done)
        self.assertAlmostEqual(self.auto(tid)["sl_px"], 1.02 * 0.60)              # unchanged: -30 % would sell now
        self.assertAlmostEqual(self.auto(other)["sl_px"], 1.02 * 0.75)
        self.assertTrue(any("odmah prodao" in x for x in out))

    def test_no_price_is_retried_no_position_is_done(self):
        self.trade()
        self.assertFalse(assistnotes.hope_stop(self.tc, self.lc, market=lambda t: {})[0])
        self.lc.execute("UPDATE trades SET status='closed'")
        self.lc.commit()
        self.assertTrue(assistnotes.hope_stop(self.tc, self.lc, market=lambda t: {})[0])

    def test_owner_once_b_retries_then_stops(self):
        self.trade()
        with mock.patch.object(assistnotes, "hope_stop", return_value=(False, ["nema cijene"])):
            self.assertFalse(assistnotes.owner_once_b(self.tc, self.lc))
        with mock.patch.object(assistnotes, "hope_stop", return_value=(True, ["ok"])) as hs:
            self.assertTrue(assistnotes.owner_once_b(self.tc, self.lc))
            self.assertTrue(assistnotes.owner_once_b(self.tc, self.lc))
        self.assertEqual(hs.call_count, 1)


class Lots(HopeStop):
    def test_lots_get_one_level_from_the_average_entry(self):
        a = self.trade(sl="-60%", entry=1.0, eff=1.0)
        b = self.trade(sl="-60%", entry=0.5, eff=0.5)                              # same qty 25: average 0.75
        done, out = assistnotes.hope_stop(self.tc, self.lc, market=lambda t: {H: (0.70, 50_000, None, 150_000)})
        self.assertTrue(done)
        for tid in (a, b):
            self.assertAlmostEqual(self.auto(tid)["sl_px"], 0.75 * 0.70)
        self.assertEqual(sum("od prosječnog ulaza" in x for x in out), 2)


class OwnerCap(Base):
    def test_owner_cap_refuses_his_buys_over_the_cap_whatever_the_flag(self):
        from ui import pravitrade
        self.tc.execute("INSERT INTO positions (token, opened_ts, mode, status, sol_in) VALUES (?,?,?,?,?)",
                        (MINT, NOW, "dry", "open", 0.6))
        self.tc.commit()
        pravitrade._owner_buy_rules(self.lc, self.tc, MINT, 0.15, NOW)              # no owner cap, flag off: goes
        assistnotes.owner_flags_b(self.tc, now=NOW)
        with self.assertRaisesRegex(ValueError, "tvoj strop po tokenu"):
            pravitrade._owner_buy_rules(self.lc, self.tc, MINT, 0.15, NOW)
        pravitrade._owner_buy_rules(self.lc, self.tc, "other", 0.15, NOW)          # another token: fine

    def test_grok_note_is_marked_applied_and_summaries_can_be_dismissed(self):
        from ui import pravitrade
        n = assistnotes.submit_suggestion(self.tc, "k", "Prihvaćeno, ali nije primijenjeno: SL je još 60 %", "i")
        nid = n["id"] if isinstance(n, dict) else n
        assistnotes.owner_flags_b(self.tc, now=NOW)
        st = self.tc.execute("SELECT status FROM assistant_notes WHERE id=?", (nid,)).fetchone()[0]
        self.assertEqual(st, "primijenjeno")
        old = assistnotes.submit_daily_summary(self.tc, "k1", "Stari sažetak", "tekst", {"a": 1})
        s = assistnotes.submit_daily_summary(self.tc, "k2", "Sažetak", "tekst", {"a": 1})
        sid = s["id"] if isinstance(s, dict) else s
        card = pravitrade._summary_card(self.tc, True)
        self.assertIn("Pročitano, makni", card)
        self.assertIn('data-sec=""', card)                                         # no chip bar from its title
        # 10.11. 23:04 (Jure: "ne ukloni se"): the older unread one must not take its place
        loc = pravitrade.post("/pravi-trade/sumread", {"id": str(sid)}, "Jure")
        self.assertIn("ok=", loc)
        self.assertEqual(pravitrade._summary_card(self.tc, True), "")


class CapForm(Base):
    def test_owner_sets_and_clears_the_cap_in_pravila(self):
        from ui import pravitrade
        form = {k: "" for k in settings.LIMITS}
        form.update({k: str(v) for k, v in pravitrade._cfg(self.tc).items() if k in settings.LIMITS})
        loc = pravitrade.post("/pravi-trade/limits", dict(form, dca_token_cap="0,5", dca_cap_owner="1"), "Jure")
        self.assertIn("Limiti spremljeni", unquote(loc))
        raw = settings.raw(self.tc)
        self.assertEqual((raw["dca_token_cap"], raw["dca_cap_owner"]), (0.5, True))
        pravitrade.post("/pravi-trade/limits", dict(form, dca_token_cap="0.3"), "Jure")
        self.assertFalse(settings.raw(self.tc)["dca_cap_owner"])
        _, body = pravitrade.page({}, "Jure")
        self.assertIn("Najviše SOL po tokenu (tvoje kupnje i DCA)", body)


class Confluence(Base):
    def test_two_callers_and_a_tiered_wallet(self):
        from tests.test_primijeni_offline import Signal
        sig = Signal("test_a_caller_or_a_tiered_wallet_is_a_signal_nothing_else_is")
        sig.lc, sig.tc = self.lc, self.tc
        sig.kol([("x1", MINT, "ansem", NOW - 60, "call")])
        self.assertFalse(copy.confluence_for(MINT, NOW)[0])
        sig.kol([("x2", MINT, "marko", NOW - 30, "call")])
        self.assertFalse(copy.confluence_for(MINT, NOW)[0])                       # 2 callers, no wallet
        sig.wallets([("W2", "A")], [("s1", "W2", MINT, "buy", NOW - 30, 0.5)])
        self.assertTrue(copy.confluence_for(MINT, NOW)[0])
        f = {"id": 1, "kind": "kol", "target": "ansem", "user": settings.LEAGUE_USER, "exit": {}}
        self.assertIsNone(copy._confluence_gate(self.lc, f, "nope", NOW, "shadow"))
        self.assertEqual(len(flags.shadow_rows(self.lc, "confluence")), 1)
        self.assertIn("nema poklapanja", copy._confluence_gate(self.lc, f, "nope", NOW, "live"))
        self.assertIsNone(copy._confluence_gate(self.lc, dict(f, user="Ivan"), "nope", NOW, "live"))


class DcaPaper(Base):
    def test_paper_caps_only_the_paper_account(self):
        settings.put(self.tc, "dca_token_cap", 0.3)
        f = {"id": 3, "kind": "wallet", "target": "W", "user": settings.PAPER_USER, "size_usd": 60, "exit": {}}
        copy._DCA["cap"] = None
        self.assertIn("najviše 0.3 SOL", copy._dca_gate(self.lc, f, MINT, NOW, "paper", sol_usd=150))   # 0.4 SOL
        self.assertIsNone(copy._dca_gate(self.lc, dict(f, size_usd=30), MINT, NOW, "paper", sol_usd=150))
        lg = dict(f, user=settings.LEAGUE_USER)
        self.assertIsNone(copy._dca_gate(self.lc, lg, MINT, NOW, "paper", sol_usd=150))     # real account: logged
        self.assertEqual(len(flags.shadow_rows(self.lc, "dca_cap")), 1)
        self.assertIsNone(copy._dca_gate(self.lc, f, MINT, NOW, "off", sol_usd=150))
        self.assertIsNone(copy._dca_gate(self.lc, dict(f, user="Ivan"), MINT, NOW, "live", sol_usd=150))  # players never


if __name__ == "__main__":
    unittest.main()
