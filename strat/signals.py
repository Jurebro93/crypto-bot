"""What each strategy would buy right now. Read-only on kol.db, tg.db, hype.db and paper.db; no network, no cost.

Every reader returns [(token, ts, who, score)]: the token, when the signal happened, a short reason shown on the page
and a priority (higher first when a strategy's hourly cap is tight).
"""
import json
import os
import random
import sqlite3

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def wallet_label(w, names=None):
    """The label a wallet signal carries ('novčanik @twitter' / 'novčanik name' / 'novčanik 5YnHVD…'); the same
    text keys the copy results (strat positions.why) and the allow-list (strat/run.wallets_allowed)."""
    names = names or {}
    return "novčanik " + names.get(w, w[:6] + "…")


def kol_names(kol_db=None):
    """{wallet: '@twitter' | name} from kol.db kol_ids, for wallet_label."""
    kc = _ro(kol_db or _path("kol.db", "KOL_DB"))
    try:
        return {w: (tw and "@" + tw) or name or w[:6] for w, tw, name in _q(kc, "SELECT wallet, twitter, name FROM kol_ids")}
    finally:
        if kc is not None:
            kc.close()


def _path(name, env):
    return os.environ.get(env) or os.path.join(ROOT, name)


def _ro(path):
    if not os.path.exists(path) or not os.path.getsize(path):
        return None
    try:
        return sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=10)
    except sqlite3.OperationalError:
        return None


def _q(con, sql, args=()):
    if con is None:
        return []
    try:
        return con.execute(sql, args).fetchall()
    except sqlite3.OperationalError:
        return []


def _ok(tok):
    return bool(tok) and 32 <= len(tok) <= 50


class Sources:
    """One read of every source for one pass; paths can be overridden (tests)."""

    def __init__(self, kol_db=None, tg_db=None, hype_db=None, paper_db=None):
        self.kol_db = kol_db or _path("kol.db", "KOL_DB")
        self.tg_db = tg_db or _path("tg.db", "TG_DB")
        self.hype_db = hype_db or _path("hype.db", "HYPE_DB")
        self.paper_db = paper_db or _path("paper.db", "PAPER_DB")

    def read(self, now, window_s):
        since = now - window_s
        kc, tc, hc, pc = (_ro(p) for p in (self.kol_db, self.tg_db, self.hype_db, self.paper_db))
        try:
            from kol import bots as _bots
            bad = _bots.handles(kc)   # scanner bots + hacked spam accounts, paid-group sellers, self-pumping devs
            from kol import discover
            # "na probi" (fewer than 10 measured calls, followed < 14 days, few views): out of the live watch and
            # copy trading, so out of this account too
            bad |= {h for h, st in _q(kc, "SELECT handle, stats FROM kols WHERE stats LIKE '%trial%'")
                    if discover.excluded(st)}
            scores = dict(_q(kc, "SELECT handle, COALESCE(score, 0) FROM kols"))
            names = {w: (tw and "@" + tw) or name or w[:6]
                     for w, tw, name in _q(kc, "SELECT wallet, twitter, name FROM kol_ids")}

            wallets = [(m, int(ts), wallet_label(w, names), 0)
                       for w, m, ts in _q(hc, "SELECT wallet, mint, ts FROM chain_trades WHERE side='buy' AND ts >= ?",
                                          (since,)) if _ok(m) and ts]

            kols, veliki, potvrdjen = [], [], []
            # 5.11.: big accounts (reach): followers + followed by proven KOLs, trial or not (bots never)
            from kol import reach as _reach
            fby = _reach.followed_by(kc) if kc is not None else {}
            foll = dict(_q(kc, "SELECT handle, COALESCE(followers, 0) FROM kols"))
            bots_only = _bots.handles(kc)
            vcfg = _reach.config(self.kol_cfg if hasattr(self, "kol_cfg") else None)
            for tok, ts, h in _q(kc, "SELECT token, ts, handle FROM calls WHERE kind='call' AND ts >= ?", (since,)):
                if h.startswith("w:") or h.startswith("tg:"):
                    continue
                if h not in bad:
                    kols.append((tok, int(ts), h, scores.get(h) or 0))
                    # 7.11. retro (22.896 poziva): računi 20–100k pratitelja na tokenu 100k–1M uz volumen ≥ 3×
                    # u satu poslije = 87 % dosegne +15 %, rug 4 %. Razred i volumen se provjeravaju pri cijeni.
                    if 20_000 <= (foll.get(h) or 0) < 100_000 and h not in bots_only:
                        potvrdjen.append((tok, int(ts), f"{h} ({(foll.get(h) or 0) // 1000}k pratitelja)", scores.get(h) or 0))
                if h not in bots_only and _reach.is_big(foll.get(h), fby.get(h.lower(), 0), vcfg):
                    veliki.append((tok, int(ts), f"{h} ({foll.get(h, 0) // 1000}k, prate ga {fby.get(h.lower(), 0)})", foll.get(h, 0)))
            for h, ca, ts in _q(hc, "SELECT handle, ca, ts FROM kol_mentions WHERE ts >= ? AND ca != ''", (since,)):
                if h not in bad:
                    kols.append((ca, int(ts), h, scores.get(h) or 0))
            for ch, ts, cas, fwd in _q(tc, "SELECT channel, ts, cas, fwd_from FROM posts WHERE ts >= ? AND cas != ''",
                                       (since,)):
                h = f"tg:{ch}"
                if fwd or h in bad:
                    continue
                for ca in (cas or "").split(","):
                    kols.append((ca, int(ts), h, scores.get(h) or 0))
            kols = [k for k in kols if _ok(k[0]) and k[1]]

            tool = []
            for tok, ts, cfg in _q(pc, "SELECT token, opened_ts, config FROM trades WHERE opened_ts >= ?", (since,)):
                try:
                    mode = json.loads(cfg or "{}").get("entry_mode") or "ocjena"
                except ValueError:
                    mode = "ocjena"
                if mode != "konv" and _ok(tok):   # konv = bought because of KOL convergence, that is not the tool's pick
                    tool.append((tok, int(ts), "demo bot kupio (" + mode + ")", 1))

            scored = [(t, int(ts), f"ocjena {sc:.0f}", sc or 0)
                      for t, ts, sc in _q(hc, "SELECT token, ts, score FROM hype_signals WHERE ts >= ?", (since,))
                      if _ok(t) and ts]
            # 5.11.: the token's own socials (hype/socials.py features stored with the signal)
            ozbiljni, sumnjivi, seen_s = [], [], set()
            for t, ts, sc, feats in _q(hc, "SELECT token, MIN(ts), score, features FROM hype_signals WHERE ts >= ? AND "
                                           "(features LIKE '%\"ozbiljan_projekt\": 1%' OR features LIKE '%\"sumnjivi_socijali\": 1%') "
                                           "GROUP BY token", (since,)):
                if not _ok(t) or not ts or t in seen_s:
                    continue
                seen_s.add(t)
                try:
                    f = json.loads(feats or "{}")
                except ValueError:
                    continue
                if f.get("ozbiljan_projekt"):
                    ozbiljni.append((t, int(ts), "ozbiljan projekt (plaćeni profil, X profil, živ TG)", sc or 0))
                elif f.get("sumnjivi_socijali"):
                    sumnjivi.append((t, int(ts), "sumnjivi socijali (tweet/pretraga umjesto profila ili bez TG-a)", sc or 0))
        finally:
            for c in (kc, tc, hc, pc):
                if c is not None:
                    c.close()
        ekipa = []
        try:   # 5.11.: the crew (kol/crew.py): 2+ big accounts reacting to a call, 1+ of them bought before it
            from kol import crew as _crew
            ekipa = [e for e in _crew.signals(self.kol_db, since) if _ok(e[0])]
        except Exception:  # noqa: BLE001
            ekipa = []
        ins = []
        try:   # insider wallets (kol/insiders.py): 2+ of them buying the same token before any call
            from kol import insiders as _ins
            good = _ins.good_set(self.kol_db, None)
            ins = _ins.signal(self.hype_db, self.kol_db, good, now, window_s, _ins.DEFAULT["min_wallets"])
            self.insiders = good
        except Exception:  # noqa: BLE001
            self.insiders = set()
        return {"novcanici": wallets, "kol": kols, "alat": tool, "scored": scored, "insajderi": ins,
                "ozbiljni": ozbiljni, "sumnjivi": sumnjivi, "veliki": veliki, "ekipa": ekipa, "potvrdjen": potvrdjen}


def mix(src, min_score, window_s):
    """Tokens that at least two of the three groups (wallets, KOLs, the tool) flagged within window_s of each other.
    For the tool, a hype score >= the demo's min_score counts too, not only an actual demo buy."""
    first = {}   # token -> {group: earliest ts}
    groups = {"novčanici": src.get("novcanici", []), "KOL": src.get("kol", []), "alat": src.get("alat", []) +
              [s for s in src.get("scored", []) if s[3] >= min_score]}
    for g, evs in groups.items():
        for tok, ts, _who, _sc in evs:
            d = first.setdefault(tok, {})
            d[g] = min(ts, d.get(g, ts))
    out = []
    for tok, d in first.items():
        if len(d) < 2:
            continue
        ts = sorted(d.values())
        if ts[1] - ts[0] <= window_s:
            out.append((tok, ts[1], " + ".join(sorted(d)), len(d)))   # the moment the second group agreed
    return out


def random_pick(src, now, last_ts, every_s, seed=None):
    """Control group: one random token the scanner saw in the last 10 minutes, at most once every every_s."""
    if last_ts and now - last_ts < every_s:
        return []
    pool = sorted({t for t, ts, _w, _s in src.get("scored", []) if now - ts <= 600})
    if not pool:
        return []
    rnd = random.Random(seed if seed is not None else int(now))
    return [(rnd.choice(pool), int(now), "nasumičan izbor", 0)]
