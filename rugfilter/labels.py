"""Which rug label counts where, until the owner confirms the SOL-side relabel (11.11. evening, Jure: "Dok se ne
preoznači ponovno, za blokiranje vrijedi stroža oznaka. Nijedan token se ne odblokira." / "Statistike callera,
walleta i izvora (hit rate, EV) dok se ovo ne riješi računaj sa starim oznakama. ... Rug poništava i counterfactual
'pobjeda'.").

Three label versions exist for a token (rugfilter/collapse, rugfilter/archive, rugfilter/relabel):
  usd      11.11. noon: the USD liquidity more than 50 % down (collapse.judge_usd, archive.kind_usd); the OLD label
  pool_v1  11.11. afternoon (PR #140): the pool invariant L 50 %+ down (collapse.judge_pool_v1)
  sol_v2   11.11. evening, the owner's rule: the SOL (quote) side 50 %+ down from the first snapshot to the last /
           lowest, or the price 90 %+ and the SOL side 90 %+ down, or 70 %+ down with the dev / a top holder selling
           or a high rug risk (collapse.judge_v2)
The owner switch rug_labels_v2_ok (trade/settings, G28; live = on, default off):
  off  blocking: a rug if ANY version says rug (effective()); statistics: the OLD label (for_stats())
  on   sol_v2 decides both
A rug voids ONLY the owner's counterfactual "win" labels (rangedca/owner; void_set(), void_win()), by the label
statistics may use: the OLD one (usd) and the owner's own "rug" labels while the switch is off, sol_v2 once on.
11.11. (owner: "Rug poništava samo counterfactual 'pobjeda' … hit rate i EV idu samo po booked rezultatu"): the
measured statistics (callers' hit rate kol/score, events/outcomes, fast/outcomes, proposals/report) are not
changed by the rug labels.
"""
import os
import sqlite3
import time

FLAG = "rug_labels_v2_ok"
VERSIONS = ("usd", "pool_v1", "sol_v2")
RANK = {None: 0, "dump": 1, "rug": 2}
VOID_TTL_S = 300
_VOID = {"ts": 0.0, "key": None, "set": frozenset()}


def v2_ok():
    """True once the owner switched rug_labels_v2_ok on (live); any read error is off (the stricter side)."""
    try:
        from trade import settings
        return settings.flag(FLAG) == "live"
    except Exception:  # noqa: BLE001
        return False


def strict():
    return not v2_ok()


def worst(*kinds):
    """The strictest of the labels: "rug" over "dump" over None."""
    return max(kinds, key=lambda k: RANK.get(k, 0)) if kinds else None


def effective(kinds, strict_mode=None):
    """The label that blocks: the strictest of every version until the owner's switch, then sol_v2."""
    strict_mode = strict() if strict_mode is None else strict_mode
    kinds = kinds or {}
    return worst(*(kinds.get(v) for v in VERSIONS)) if strict_mode else kinds.get("sol_v2")


def for_stats(kinds, v2=None):
    """The label a statistic may use: the OLD one (usd) until the owner's switch, then sol_v2."""
    v2 = v2_ok() if v2 is None else v2
    kinds = kinds or {}
    return kinds.get("sol_v2") if v2 else kinds.get("usd")


def _hype_db():
    try:
        from rugfilter import archive
        return archive.HYPE_DB
    except Exception:  # noqa: BLE001
        return None


def void_set(path=None, ttl=VOID_TTL_S, v2=None, league_db=None):
    """frozenset of tokens whose counterfactual wins are void: a rug by the label statistics may use, the OLD one
    (usd; switch off) or sol_v2 (switch on): the rug archive, the relabel tables' rows (their old_kind while off,
    rug_relabel_sol new_kind once on) and always the owner's own "rug" labels (rangedca/owner). Cached `ttl` seconds;
    an unreadable store adds nothing."""
    path = path or _hype_db()
    v2 = v2_ok() if v2 is None else v2
    if league_db is None:
        try:
            from league import store
            league_db = store.DB
        except Exception:  # noqa: BLE001
            league_db = None
    key = (path, v2, league_db)
    now = time.time()
    if _VOID["key"] == key and now - _VOID["ts"] < ttl:
        return _VOID["set"]
    out = set()
    if path and os.path.exists(path) and os.path.getsize(path) > 0:
        try:
            from rugfilter import archive
            for t, ks in archive.kinds_detail(path).items():
                if for_stats(ks, v2) == "rug":
                    out.add(t)
        except Exception:  # noqa: BLE001
            pass
        try:
            con = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=10)
            try:
                for sql in (("SELECT token FROM rug_relabel_sol WHERE new_kind='rug'",) if v2 else
                            ("SELECT token FROM rug_relabel_sol WHERE old_kind='rug'",
                             "SELECT token FROM rug_relabel WHERE old_kind='rug'")):
                    try:
                        out |= {t for (t,) in con.execute(sql)}
                    except sqlite3.OperationalError:
                        continue
            finally:
                con.close()
        except sqlite3.Error:
            pass
    try:
        from rangedca import owner
        out |= {lb["token"] for lb in owner.labels(league_db, label="rug")}
    except Exception:  # noqa: BLE001
        pass
    s = frozenset(out)
    _VOID.update(ts=now, key=key, set=s)
    return s


def void_win(token, **kw):
    return bool(token) and token in void_set(**kw)


def forget():
    _VOID.update(ts=0.0, key=None, set=frozenset())
