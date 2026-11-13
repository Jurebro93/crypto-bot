"""Snimke "sada" za drugi krug prijedloga dizajna (10.11.2026.): pokreće DANAŠNJI kod (kopija f4dc160, npr.
git archive u scratchpad/wt/sada, pa seed_app.py --reset) tako da naslovna pokaže današnju traku "Tradanje pravim
sredstvima je live" i dnevnik "MemeSonar je live N dana": upiše tri noći u site_log (public.db TE kopije) i samo u
OVOM procesu javi da je Autopilot live (apjavno.live_state). Ništa ne dira produkciju, ključeve ni mrežu.
    python3 audit/2026-11-10/sada_drugi_krug.py <korijen kopije> <port>   pa   node audit/2026-11-10/shots.js --base http://127.0.0.1:<port>
Okruženje kao u run_local.sh (env -i, UI_USERS=Jure,..., UI_PASS_*=demo, UI_TTL_DIR... u scratchpadu). Odbija ako kopija
nije pod .../wt/ ili ako okruženje izgleda kao produkcija.
"""
import json
import os
import sqlite3
import sys
import time

root, port = sys.argv[1], sys.argv[2]
if os.environ.get("RENDER") or os.environ.get("DATA_DIR") or os.path.exists("/var/data") or "/wt/" not in os.path.abspath(root) + "/":
    sys.exit("sada_drugi_krug: ovo nije lokalna kopija pod .../wt/ (ili izgleda kao produkcija). Ne pokrećem.")
os.chdir(root)
sys.path.insert(0, root)
sys.path.insert(0, os.path.join(root, "audit/2026-11-10/local"))
import sitecustomize  # noqa: E402,F401  (odbija mrežu, cijene iz local/market.json)

con = sqlite3.connect(os.path.join(root, "public.db"))
con.executescript("CREATE TABLE IF NOT EXISTS site_log (day TEXT PRIMARY KEY, ts INTEGER, counts TEXT, added TEXT, "
                  "blogs TEXT, posts TEXT);")
now = int(time.time())
rows = [
    ("2026-11-10", now - 6 * 3600, {"kols": 358, "calls": 6969}, {"kols": 4, "calls": 212, "wallets": 3, "trades": 1840, "tokens": 96},
     ["top-crypto-twitter-accounts-by-call-accuracy", "best-crypto-telegram-channels", "how-to-check-a-kol-track-record"], []),
    ("2026-11-09", now - 30 * 3600, {}, {"kols": 6, "calls": 188, "trades": 1630, "tokens": 88},
     [], ["best-crypto-telegram-channels", "top-crypto-twitter-accounts-by-call-accuracy", "memecoin-telegram-groups-explained",
          "how-to-spot-a-pump-fun-runner", "how-to-check-a-kol-track-record"]),
    ("2026-11-08", now - 54 * 3600, {}, {"kols": 3, "calls": 201, "wallets": 2, "trades": 1702, "tokens": 91}, ["what-is-wallet-tracking"], []),
]
for d, ts, c, a, b, p in rows:
    con.execute("INSERT OR REPLACE INTO site_log VALUES (?,?,?,?,?,?)", (d, ts, json.dumps(c), json.dumps(a), json.dumps(b), json.dumps(p)))
con.commit()
con.close()

from ui import apjavno  # noqa: E402

apjavno.live_state = lambda: {"live": True, "on": True, "since": now - 9 * 3600}
_snap = apjavno.snapshot


def snap(now=None):
    try:
        s = _snap(now)
    except Exception:  # noqa: BLE001
        s = {"eq": {}, "stats": None}
    s.setdefault("eq", {})["value_sol"] = 2.000
    s["stats"] = dict(s.get("stats") or {}, mode="live", n=8, pnl=-0.042)
    return s


apjavno.snapshot = snap
sys.argv = ["run_ui.py", "--port", port]
import run_ui  # noqa: E402

run_ui.main()
