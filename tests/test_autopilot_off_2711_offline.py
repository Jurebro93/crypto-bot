import os
import tempfile
import unittest

from trade import settings as st


class AutopilotOff2711(unittest.TestCase):
    """27.11. (vlasnik: "Autopilot gasi za pravi novac, ali demo trade-ove neka rade u pozadini"): jednom."""

    def test_switches_off_pause_on_demo_kept_once(self):
        with tempfile.TemporaryDirectory() as d:
            con = st.connect(os.path.join(d, "trade.db"))
            st._FLAG_CACHE.clear()
            strat = [n for n in sorted(st.FLAGS) if n not in st.REAL_SWITCHES
                     and n not in st.AUTOPILOT_KEEP_LIVE and n != st.PUMP_TRGOVACKI][0]
            for n in (st.VEL_SWITCH, st.RISKOFF_SWITCH, strat):   # stored as if the owner had set them live
                st.put(con, f"flag:{n}", {"mode": "live", "since": 1, "who": st.owner()}, st.owner())
            st._FLAG_CACHE.clear()
            done = st.autopilot_order_2711(con, now=1795740000)
            self.assertTrue(any(st.VEL_SWITCH in x for x in done))
            st._FLAG_CACHE.clear()
            fs = st.flag_state(con)
            for n in st.REAL_SWITCHES:
                self.assertEqual(fs[n]["mode"], "off", n)
            self.assertEqual(fs[strat]["mode"], "live")   # only the real-money switches change
            self.assertTrue(st.pauza(con))
            self.assertEqual(st.autopilot_order_2711(con, now=1795740100), [])   # once
            self.assertIn("ISKLJUČEN", st.autopilot_order_line(done))
            con.close()


if __name__ == "__main__":
    unittest.main()


class Restore2711(unittest.TestCase):
    """27.11. 21:38: the order also moved on/off flags to paper; they go back to live once."""

    def test_order_touches_only_real_switches_and_restore_puts_back(self):
        with tempfile.TemporaryDirectory() as d:
            con = st.connect(os.path.join(d, "trade.db"))
            st._FLAG_CACHE.clear()
            name = "mikrokap_blokada"
            self.assertIn(name, st.FLAGS)
            # the state production was left in: the first version recorded it and set it to paper
            st.put(con, f"flag:{name}", {"mode": "paper", "since": 1, "who": st.owner()}, st.owner())
            st.put(con, st.AUTOPILOT_ONCE, {"ts": 1, "promjene": [f"{name}: live → paper (demo)"]}, st.owner())
            st._FLAG_CACHE.clear()
            self.assertEqual(st.autopilot_restore_2711(con, now=1795740000), [name])
            st._FLAG_CACHE.clear()
            self.assertEqual(st.flag_state(con)[name]["mode"], "live")
            self.assertEqual(st.autopilot_restore_2711(con, now=1795740100), [])   # once
            con.close()

    def test_fresh_order_leaves_on_off_flags_alone(self):
        with tempfile.TemporaryDirectory() as d:
            con = st.connect(os.path.join(d, "trade.db"))
            st._FLAG_CACHE.clear()
            st.put(con, "flag:fokus_midcap", {"mode": "live", "since": 1, "who": st.owner()}, st.owner())
            st._FLAG_CACHE.clear()
            st.autopilot_order_2711(con, now=1795740000)
            st._FLAG_CACHE.clear()
            self.assertEqual(st.flag_state(con)["fokus_midcap"]["mode"], "live")
            con.close()
