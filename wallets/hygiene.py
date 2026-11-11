"""Higijena popisa za kopiranje (11.11., Grok's accepted note #85: "top 60 wallets inactive 20-47 h; bot/sniper
S-tier not copyable").

A wallet leaves a copy or webhook list when
  idle    its newest known trade is older than max_idle_h (24 h)
  label   it carries a label of wallets/store.BAD_LABELS (bot, sniper, bundler, mev, rugger, cex, dev, insider,
          funder_of_rugger) or 'izbačen' (ops/prune)
  bot     its scored stats show a bot: wallets/pnl's own bot flag or style 'bot', more than max_tpd trades a day, or
          a median hold under min_hold_s seconds
Tier S does not protect it: tier S is a profitable bot or sniper (wallets/pnl.tier), a signal, never a copy.

ONLY REMOVES. screen() returns each given list minus the dropped wallets, in the same order, and never adds a wallet,
so it is applied directly, without a flag, where copy candidates are chosen:
  ui/autopilot.auto_targets     the wallet auto pick (proven twice + the 7/14/30-day list)
  kol/chainwatch.wanted         the Helius webhook's own-registry groups: copy (copy_score), signal (tier S) and the
                                proven-twice wallets (wallets/dokazani.current); the wallets a player follows and the
                                public leaderboard / insider groups are not screened here
Unknown is kept: a wallet without a wallets.db row, without stats or without any known trade time is not dropped for
that missing fact (the rule acts on known data only). Each screen logs how many it dropped and why.

The newest trade is the newest of wallets.last_tx_ts (the scorer), wallet_trades (stored swaps) and hype.db
chain_trades (the webhook and the PumpPortal mirror). An idle wallet comes back once a newer trade is seen: the scorer
rechecks tier A every 6 h, tiers B and S every 24 h (wallets/pnl.tier), so a webhook slot freed today returns within
a day of the wallet trading again. Read-only on every database; no API call.

Config: wallets/config.json "copy_hygiene" (max_idle_h, max_tpd, min_hold_s); DEFAULT when the file or a key is missing.
"""
import json
import os
import sqlite3
import time

from wallets import store as wstore

DEFAULT = {"max_idle_h": 24, "max_tpd": 200, "min_hold_s": 30}
CONFIG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")
LABELS = frozenset(wstore.BAD_LABELS | {"izbačen"})
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def rule(path=None):
    """DEFAULT with wallets/config.json "copy_hygiene" on top (numbers only)."""
    r = dict(DEFAULT)
    try:
        with open(path or CONFIG, encoding="utf-8") as f:
            over = json.load(f).get("copy_hygiene") or {}
        r.update({k: float(v) for k, v in over.items() if k in DEFAULT and isinstance(v, (int, float))})
    except (OSError, ValueError, AttributeError, TypeError):
        pass
    return r


def _ro(path):
    if not path or not os.path.exists(path) or not os.path.getsize(path):
        return None
    try:
        return sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5)
    except sqlite3.Error:
        return None


def _chunks(xs, n=500):
    for i in range(0, len(xs), n):
        yield xs[i:i + n]


def facts(wallets, wallet_db=None, hype_db=None, since=None):
    """{wallet: {"known", "labels", "stats", "last_ts"}} for the given wallets; known False = no wallets.db row.
    since: chain_trades are read only from this time on (the idle window; older trades cannot change the answer)."""
    ws = sorted({w for w in wallets if w})
    out = {w: {"known": False, "labels": set(), "stats": {}, "last_ts": None} for w in ws}
    if not ws:
        return out

    def newer(w, ts):
        if ts and (out[w]["last_ts"] is None or ts > out[w]["last_ts"]):
            out[w]["last_ts"] = int(ts)

    wc = _ro(wallet_db or wstore.DB)
    if wc is not None:
        try:
            for part in _chunks(ws):
                q = ",".join("?" * len(part))
                for w, lab, st, last in wc.execute(f"SELECT wallet, labels, stats, last_tx_ts FROM wallets "
                                                   f"WHERE wallet IN ({q})", part):
                    f = out[w]
                    f["known"] = True
                    try:
                        f["labels"] = set(json.loads(lab or "[]"))
                    except (ValueError, TypeError):
                        pass
                    try:
                        f["stats"] = json.loads(st or "{}") or {}
                    except (ValueError, TypeError):
                        pass
                    newer(w, last)
                for w, ts in wc.execute(f"SELECT wallet, MAX(ts) FROM wallet_trades WHERE wallet IN ({q}) GROUP BY wallet",
                                        part):
                    newer(w, ts)
        except sqlite3.Error:
            pass
        finally:
            wc.close()
    hc = _ro(hype_db or os.environ.get("HYPE_DB") or os.path.join(ROOT, "hype.db"))
    if hc is not None:
        try:
            for part in _chunks(ws):
                q = ",".join("?" * len(part))
                for w, ts in hc.execute(f"SELECT wallet, MAX(ts) FROM chain_trades WHERE ts >= ? AND wallet IN ({q}) "
                                        f"GROUP BY wallet", (int(since or 0), *part)):
                    newer(w, ts)
        except sqlite3.Error:
            pass
        finally:
            hc.close()
    return out


def why(f, now, r=None):
    """(kind, reason in Croatian) when the wallet is out, else None. kind: 'label' | 'bot' | 'idle'."""
    r = r or rule()
    bad = sorted(set(f.get("labels") or ()) & LABELS)
    if bad:
        return "label", "oznaka " + ", ".join(bad)
    s = f.get("stats") or {}
    tpd = s.get("trades_per_day")
    hold = s.get("median_hold_min")
    if s.get("bot") or s.get("style") == "bot":
        return "bot", "bot po statistici (stil bot)"
    if tpd is not None and float(tpd) > r["max_tpd"]:
        return "bot", f"bot: {float(tpd):.0f} tradeova dnevno (granica {r['max_tpd']:g})"
    if hold is not None and float(hold) * 60 < r["min_hold_s"]:
        return "bot", f"bot: medijan držanja {float(hold) * 60:.0f} s (granica {r['min_hold_s']:g} s)"
    last = f.get("last_ts")
    if last is not None and now - last > r["max_idle_h"] * 3600:
        return "idle", f"neaktivan {(now - last) / 3600:.0f} h (granica {r['max_idle_h']:g} h)"
    return None


def screen(groups, where, now=None, wallet_db=None, hype_db=None, r=None, log=print):
    """({name: kept wallets, same order}, {wallet: reason}) for groups {name: [wallet, ...]}. Only removes. One read
    of the facts for the union of the groups, one log line when anything was dropped."""
    now = int(now or time.time())
    r = r or rule()
    allw = [w for ws in groups.values() for w in ws or []]
    fs = facts(allw, wallet_db, hype_db, since=now - r["max_idle_h"] * 3600)
    dropped, kinds = {}, {}
    for w in set(allw):
        out = why(fs.get(w) or {}, now, r)
        if out:
            dropped[w] = out[1]
            kinds[out[0]] = kinds.get(out[0], 0) + 1
    kept = {name: [w for w in ws or [] if w not in dropped] for name, ws in groups.items()}
    if dropped and log:
        names = {"idle": "neaktivni", "label": "oznaka", "bot": "bot po statistici"}
        parts = ", ".join(f"{names.get(k, k)} {n}" for k, n in sorted(kinds.items()))
        log(f"higijena kopiranja ({where}): izbačeno {len(dropped)} od {len(set(allw))} novčanika ({parts})")
    return kept, dropped
