"""27.11. (ops/autopilot_off): the Autopilot is removed by default (AUTOPILOT_OFF unset = "1"); its code stays behind
the switch. A test module of the old Autopilot (its terminal page, public page, Grok autotrade, the 1-s loops) imports
setUpModule / tearDownModule from here and runs with AUTOPILOT_OFF=0, i.e. exactly the old behaviour; what changes
while it is removed is in tests/test_bezautopilota_offline.py. Not a test module itself (no test_ prefix)."""
import os

_SAVED = []


def setUpModule():
    _SAVED.append(os.environ.get("AUTOPILOT_OFF"))
    os.environ["AUTOPILOT_OFF"] = "0"


def tearDownModule():
    old = _SAVED.pop() if _SAVED else None
    if old is None:
        os.environ.pop("AUTOPILOT_OFF", None)
    else:
        os.environ["AUTOPILOT_OFF"] = old
