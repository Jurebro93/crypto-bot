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
            self.assertIn(fs[strat]["mode"], ("paper", "off"))
            self.assertTrue(st.pauza(con))
            self.assertEqual(st.autopilot_order_2711(con, now=1795740100), [])   # once
            self.assertIn("ISKLJUČEN", st.autopilot_order_line(done))
            con.close()


if __name__ == "__main__":
    unittest.main()
