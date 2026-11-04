"""Settings of the real-money trader that the owner changes on the page /pravi-trade, kept in trade.db (on the
persistent disk, so a redeploy keeps them). trade/config.json holds the defaults.

Who may change them: TRADE_OWNER (Render env, default "Jure", Nicholas's account). Other players see the page only
when the owner invites them, and only to look.
"""
import json
import os
import sqlite3
import time

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.environ.get("TRADE_DB", os.path.join(HERE, "trade.db"))
LEAGUE_USER = "pravi-trade"   # the competition account whose follows (KOL/wallet) drive the real trades

# key -> (label, type, min, max); the owner edits these on the page
LIMITS = {
    "size_sol": ("Ulog po kupnji (SOL)", float, 0.005, 5.0),
    "max_sol_per_day": ("Najviše potrošeno na kupnje u danu (SOL)", float, 0.01, 50.0),
    "max_loss_day": ("Najveći gubitak u danu, onda stop (SOL)", float, 0.01, 50.0),
    "max_open": ("Najviše otvorenih pozicija", int, 1, 50),
    "min_sol_reserve": ("Uvijek ostavi u walletu (SOL)", float, 0.01, 10.0),
    "max_cost_pct": ("Najveći trošak swapa (%)", float, 0.5, 20.0),
}

# Audit 4.11. §14.4/§22: switches that stay off whatever is saved, until the proof the audit asks for exists.
# The page shows them greyed out with this reason; run_trade and the SimianX job read the effective value.
LOCKED = {
    "follow_paper": "zaključano: demo strategija smije u pravi novac tek kad dobije status „kandidat” "
                    "(bije kontrolu nakon troška, na obje polovice, i bez 5 najboljih trejdova)",
    "simianx": "zaključano: SimianX signali nemaju isti dokaz kao praćeni influenceri i novčanici "
               "(odgođena kopija koja bije kontrolu), pa ne idu u pravi novac",
}

SCHEMA = "CREATE TABLE IF NOT EXISTS settings (k TEXT PRIMARY KEY, v TEXT, ts INTEGER, who TEXT)"


def connect(path=None):
    con = sqlite3.connect(path or DB, timeout=30)
    con.execute(SCHEMA)
    return con


def owner():
    return (os.environ.get("TRADE_OWNER") or "Jure").strip().lower()


def is_owner(user):
    return bool(user) and user.lower() == owner()


def raw(con):
    return {k: json.loads(v) for k, v in con.execute("SELECT k, v FROM settings")}


def put(con, key, value, who=""):
    con.execute("INSERT OR REPLACE INTO settings VALUES (?,?,?,?)", (key, json.dumps(value), int(time.time()), who))
    con.commit()


def merged(cfg, con):
    """config.json defaults + what the owner set on the page. The switch ("on") lives only here: off by default."""
    s = raw(con)
    out = dict(cfg)
    for k in LIMITS:
        if k in s:
            out[k] = s[k]
    out["max_sol_per_trade"] = max(out.get("max_sol_per_trade", 0), out["size_sol"])
    out["on"] = bool(s.get("on", False))
    out["follow_paper"] = bool(s.get("follow_paper", False)) and "follow_paper" not in LOCKED
    out["use_pump"] = bool(s.get("use_pump", True))
    out["simianx"] = bool(s.get("simianx", False)) and "simianx" not in LOCKED
    out.setdefault("day_tz", "Europe/Zagreb")
    out["sell_all"] = s.get("sell_all") or 0
    out["sell_req"] = s.get("sell_req") or {}
    out["manual_size"] = s.get("manual_size") or {}
    out["heartbeat"] = s.get("heartbeat") or 0
    return out


def parse_limits(form):
    """Form -> {key: value}; raises ValueError with a Croatian message on a bad number."""
    out = {}
    for k, (label, typ, lo, hi) in LIMITS.items():
        txt = (form.get(k) or "").strip().replace(",", ".")
        if not txt:
            continue
        try:
            v = typ(float(txt))
        except ValueError:
            raise ValueError(f"{label}: upiši broj")
        if not lo <= v <= hi:
            raise ValueError(f"{label}: mora biti između {lo:g} i {hi:g}")
        out[k] = v
    return out


def invited(con):
    return [u for u in raw(con).get("invited", []) if u]


def can_view(con, user):
    return is_owner(user) or bool(user) and user.lower() in {u.lower() for u in invited(con)}


def simianx_on(con=None):
    """The owner's approval for SimianX long signals on the real-trade account (off by default). The SimianX job
    opens its demo trades on LEAGUE_USER only while this is on (league.store.buy + auto.set_auto with its stop and
    target); run_trade.py then mirrors them like any copy trade, inside the same limits."""
    own = con is None
    con = con or connect()
    try:
        return bool(raw(con).get("simianx", False)) and "simianx" not in LOCKED
    finally:
        if own:
            con.close()
