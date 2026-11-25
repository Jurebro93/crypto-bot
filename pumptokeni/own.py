"""Zabrana samotrgovanja (25.11., vlasnik): naši mintovi iz pokusa (pump_tokeni.db pokusaji.mint, i oni čije
lansiranje nije prošlo) ne smiju biti kupljeni ni prodani nijednim automatskim putem alata (pravi novac, demo,
istraživač, kopije, sjena) niti izaći korisnicima kao kandidati ili na javnim stranicama.

Uska grla koja pitaju is_own(): trade/executor.buy_checks (svaka prava i probna kupnja) i executor.sell,
league/store.buy (svaki demo račun: Autopilot demo, istraživač, kopije, konsenzus, oscilator...), veliki/sjena.consider
(knjiga sjene), scan/shadow.enter (sjena skenera), veliki/universe.judge i data_judge (popis kandidata),
veliki/midcap.members, tokenstranice/podaci.universe (javne stranice tokena) i ui/pages.token.

Brzo i nikad ne baca: skup se čita iz baze najviše jednom u CACHE_S po procesu; nema baze = prazan skup.
"""
import os
import sqlite3
import time

REASON = "vlastiti token pokusa"
CACHE_S = 30.0
_C = {"ts": 0.0, "path": None, "mints": frozenset()}


def _path():
    from pumptokeni import store
    return store.db_path()


def mints(max_age_s=CACHE_S):
    """frozenset naših mintova (svaki pokušaj s upisanim mintom)."""
    p = _path()
    if _C["path"] == p and time.monotonic() - _C["ts"] < max_age_s:
        return _C["mints"]
    out = frozenset()
    if os.path.exists(p):
        try:
            con = sqlite3.connect(f"file:{p}?mode=ro", uri=True, timeout=2)
            try:
                out = frozenset(r[0] for r in con.execute("SELECT DISTINCT mint FROM pokusaji WHERE mint IS NOT NULL "
                                                          "AND mint != ''"))
            finally:
                con.close()
        except sqlite3.Error:
            out = _C["mints"] if _C["path"] == p else frozenset()   # zadnji poznati skup, nikad manje sigurno od njega
    _C.update(ts=time.monotonic(), path=p, mints=out)
    return out


def is_own(mint):
    return bool(mint) and mint in mints()


def reset():
    _C.update(ts=0.0, path=None, mints=frozenset())
