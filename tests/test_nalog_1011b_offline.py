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
                                 "smart_discovery": "shadow"})
        log = assistnotes.applied(self.tc)
        self.assertEqual({(x["key"], x["old"], x["new"]) for x in log},
                         {("flag:x_features_ingest", "off", "shadow"), ("flag:require_signal", "shadow", "paper"),
                          ("flag:dca_cap", "shadow", "paper"), ("flag:smart_discovery", "off", "shadow")})
        self.assertTrue(all(x["ts"] and x["note_id"] == 0 for x in log))
        self.assertEqual(len(done), 4)
        self.assertEqual(assistnotes.owner_flags_b(self.tc, now=NOW), [])          # once
        self.assertNotIn("live", modes.values())
        # what Grok reads
        with mock.patch.object(mcpdata, "_ro", side_effect=lambda name: settings.connect() if name == "trade" else None):
            cfg = mcpdata.scoring_config()
        self.assertEqual(cfg["flags"]["require_signal"]["mode"], "paper")
        self.assertEqual(cfg["flags"]["x_features_ingest"]["mode"], "shadow")
        self.assertEqual(cfg["flags"]["dca_cap"]["mode"], "paper")
        self.assertIn("flag:dca_cap", [x["key"] for x in cfg["applied_suggestions"]])


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
        self.assertIn("−40 % → -30 %".replace("−40", "-40"), out[0].replace("−", "-"))
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
