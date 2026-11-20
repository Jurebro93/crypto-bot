#!/usr/bin/env python3
"""Fixture for the wallet pages (19.11.): NOT production data, never run on the server. Fills the databases the wallet
pages read with a made-up but plausible set, for the offline tests and for the local screenshots:

    insajderi.db  ~40 owner groups of i2_pp (confirmed, unconfirmed, candidates, every excluded class), their pumps
                  (i2_events + i2_part), shared fee payers / same-block buys (i2_trades), bundles, the last pass's
                  summary with the copy test, one i2_runs row, Helius spent today; hostile strings in symbols / reasons
    wallets.db    scored wallets for part of the groups' members, their trades, the "dokazani" run and the copy rank
    holderi.db    profitable holders of a few midcaps (holder_pos, profile)
    league.db     the demo account's wallet-following trades (kopija dokazanih, insajderi2), open and closed
    trade.db      the real-money pause key (pravi_novac_pauza)

    python3 scripts/seed_novcanici.py DIR            # into DIR (the screenshots: the worktree root)
    python3 scripts/seed_novcanici.py DIR --empty    # empty insajderi.db (the empty states)
    python3 scripts/seed_novcanici.py DIR --prva-noc # the first night: lists, the copy test walking, no measurement

seed(paths, empty=False, now=None) is what the tests call with their temporary paths.
"""
import hashlib
import json
import os
import random
import sqlite3
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
D, H = 86400, 3600
HOSTILE_SYM = '<script>alert(1)</script>'
HOSTILE_ADDR = 'Evil"><img src=x onerror=alert(2)>wallet1111111111'


def b58(seed, n=44):
    h = b"".join(hashlib.sha256(f"{seed}:{i}".encode()).digest() for i in range(3))
    return "".join(B58[b % 58] for b in h[:n])


def paths_in(d):
    return {k: os.path.join(d, f"{k}.db") for k in ("insajderi", "wallets", "holderi", "league", "trade")}


def seed(paths, empty=False, now=None, n_groups=40, paused=True, first_night=False):
    """first_night (20.11.): the lists exist, the copy test is still walking ("izračunato do ..."), the per-entry
    measurement has no row yet and Birdeye has read nothing."""
    now = int(now or time.time())
    R = random.Random(19112026)
    from insajderi import store as istore
    con = istore.connect(paths["insajderi"])
    for t in ("i2_pp", "i2_part", "i2_events", "i2_trades", "i2_bundle", "i2_kv", "i2_runs", "i2_groups", "i2_pp_hist"):
        con.execute(f"DELETE FROM {t}")
    con.commit()
    out = {"groups": [], "confirmed": [], "members": []}
    if not empty:
        syms = ["WIF", "POPCAT", "MEW", "GIGA", "MOODENG", "FWOG", "PNUT", "CHILLGUY", "GOAT", "ACT", "ZEREBRO",
                "AI16Z", "BONK", "MICHI", "SPX", HOSTILE_SYM, "RETARDIO", "LOCKIN", "TRUMP", "USELESS"]
        events = []
        for i, s in enumerate(syms * 3):
            tok = b58("tok" + s + str(i), 40) + "pump"
            tier = "pumpa15" if i % 3 != 2 else "pumpa2"
            t0 = now - (2 + i * 9) * H - R.randrange(3000)
            eid = f"m:{tok[:8]}:{t0}"
            peak = R.uniform(16e6, 160e6) if tier == "pumpa15" else R.uniform(2.2e6, 14e6)
            events.append((eid, tok, s, t0, tier, peak))
            con.execute("INSERT INTO i2_events (eid, kind, token, symbol, t0, mcap0, peak_ts, peak_x, win_end, src, prio, "
                        "fetched, n_part, built_ts, tier, peak_mc) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (eid, "skok", tok, s, t0, peak / 2.2, t0 + 3 * H, 1.2, t0 + 7 * H, "midcap", 1.0,
                         1 if i % 4 else 0, 5, now, tier, peak))
        classes = (["prije_pumpe"] * 20 + ["kandidat"] * 10 + ["bot", "snajper", "relayer", "kupuje_sve",
                                                                "market_maker", "bez_placanja", "bot", "snajper",
                                                                "market_maker", "relayer"])[:n_groups]
        payers = [b58(f"payer{k}") for k in range(5)]
        for gi, cls in enumerate(classes):
            owner = ("relayer:" if cls == "relayer" else "") + b58(f"owner{gi}")
            k = 1 if gi % 7 == 0 else 70 if gi == 5 else R.randint(2, 6)
            members = [b58(f"w{gi}:{j}") for j in range(k)]
            if gi == 3:
                members[0] = HOSTILE_ADDR
            conf = cls == "prije_pumpe" and gi < 8
            mine = R.sample(events, R.randint(3, 7))
            n15 = sum(1 for e in mine if e[4] == "pumpa15")
            n2 = len(mine) - n15
            pnl = None if gi == 9 else round(R.uniform(-2, 40), 3)
            lead = None if gi == 10 else round(R.uniform(3, 240), 1)
            why = {"prije_pumpe": f"kupio prije i prodao u pumpu na {len(mine)} tokena ({n15} do ≥ 15M, {n2} do 2-15M)",
                   "kandidat": None, "bot": "bot (brzina tradeova, kupnja i prodaja u istom slotu, oznaka ili previše tradeova)",
                   "snajper": "kupuje u prvih 60 s lansiranja", "relayer": "plaća naknade za mnogo drugih vlasnika",
                   "kupuje_sve": "kupio rano u 14 od 18 pumpi", "market_maker": "dvostrani promet: barem 3 kupnje i prodaje",
                   "bez_placanja": "4 pumpi samo uz kupnje bez poznate cijene"}[cls]
            if gi == 11:
                why = HOSTILE_SYM + " razlog"
            last = max(e[3] for e in mine)
            con.execute("INSERT INTO i2_pp VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (owner, json.dumps(members), len(members), cls, why, n15, n2, len(mine), lead, pnl,
                         (now - 2 * D) if conf else None, last, now))
            for e in mine:
                w = R.choice(members)
                buy = e[3] - R.randint(5 * 60, 5 * H)
                sol_in = round(R.uniform(0.2, 6), 3)
                sold = R.random() < 0.85
                con.execute("INSERT OR REPLACE INTO i2_part VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                            (e[0], w, owner, buy, sol_in, 2 if sold else 0, round(sol_in * R.uniform(1.4, 6), 3) if sold else 0,
                             e[3] + 1800 if sold else None, 1, 1 if sold else 0, e[3] - buy, "helius"))
                for j, mw in enumerate(members[:3]):
                    con.execute("INSERT OR REPLACE INTO i2_trades VALUES (?,?,?,?,?,?,?,?,?,?)",
                                (b58(f"sig{gi}{e[0]}{j}", 64), mw, e[1], buy, 200_000_000 + gi, "buy", sol_in, 1e6,
                                 payers[gi % 5] if gi % 2 == 0 else mw, None))
            out["groups"].append(owner)
            out["members"] += members
            if conf:
                out["confirmed"].append(owner)
        for bi, gi in enumerate((0, 1, 4, 12, 20)):
            owner = b58(f"owner{gi}")
            mem = [b58(f"w{gi}:{j}") for j in range(3)]
            toks = [e[1] for e in events[bi:bi + 4]]
            con.execute("INSERT INTO i2_bundle VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                        (("o:" if bi % 2 == 0 else "p:") + (owner if bi % 2 == 0 else payers[bi]),
                         "isti blok" if bi % 2 else "udio ranih kupnji", json.dumps(mem), len(mem), 3 + bi, 1 + bi % 3,
                         0.31 + bi * 0.07, 2 + bi % 2, json.dumps(toks), now - bi * D, now))

        def st(n, ev, lo, hi, miss=8.0):
            return {"n_buys": n + 3, "n": n, "n_tokens": max(1, n // 2), "n_owners": max(1, n // 4), "miss_pct": miss,
                    "ev_pct": ev, "lo_pct": lo, "hi_pct": hi, "ev_big_pct": None if ev is None else round(ev - 1.2, 2)}
        copy = {"60s": {"svi": st(64, 3.4, -1.8, 8.9), "15M+": st(30, 5.1, -0.6, 11.2), "5M-15M": st(22, 1.2, -4.0, 6.3),
                        "1M-5M": st(12, -2.0, -9.1, 4.4), "<1M": st(0, None, None, None, None)},
                "brzo": {"svi": st(64, 6.0, 0.4, 11.9), "15M+": st(30, 7.7, 1.1, 14.0)},
                "null": {"svi": st(80, -4.2, -8.8, 0.3), "15M+": st(36, -2.9, -9.0, 3.1)}, "razlika_pct": 7.6}
        pp = {"ts": now - 5 * H, "pumps15": 40, "pumps2": 20, "covered15": 29, "covered2": 11, "fetched15": 31,
              "groups": 20, "confirmed": 8, "classes": {"prije_pumpe": 20, "kandidat": 10, "bot": 2, "snajper": 2,
                                                        "relayer": 2, "kupuje_sve": 1, "market_maker": 2,
                                                        "bez_placanja": 1, "jednokratni": 1234, "promatra": 88},
              "market_makers": 2, "bundles": 5, "copy": copy, "min_tokens": 3, "min_n": 20, "slip_fast_pct": 1.0,
              "lijevak": {"pumpe15_1h": 22, "pumpe15_1d": 18, "pumpe2_1h": 12, "pumpe2_1d": 8, "duboko": 31,
                          "rani": 4812, "rani_prodali": 1907, "blizu_praga": 143, "grupe": 20, "potvrdjeno": 8,
                          "pokrivenost_pre_med": 62.5, "pokrivenost_skok_med": 88.0, "n_pokrivenost": 31}}
        if first_night:
            pp["copy"] = None
            pp["copy_progress"] = (f"kopija: izračunato do {time.strftime('%d.%m.', time.gmtime(now - 3 * D))} "
                                   "(42 od 45 dana)")
        con.execute("INSERT OR REPLACE INTO i2_kv VALUES ('summary', ?)", (json.dumps({"prije_pumpe": pp}),))
        con.execute("INSERT OR REPLACE INTO i2_kv VALUES ('stage_s', ?)", (json.dumps(
            {"dogadaji": 3.2, "lanac": 612.0, "popis": 41.5, "kopija": 88.1, "ostalo": 12.0, "ts": now - 5 * H,
             "kind": "night", "cut": True}),))
        for k, (o, cls) in enumerate(q for q in con.execute("SELECT owner, cls FROM i2_pp WHERE cls IN "
                                                             "('prije_pumpe','kandidat')").fetchall()):
            if k % 5 == 4:
                continue   # some groups have no history row yet
            n_sc = 0 if k % 7 == 3 else 1 + k % 4
            real = (round(R.uniform(0.5, 25), 3) if k % 3 else -round(R.uniform(0.5, 4), 3)) if n_sc else 0.0
            con.execute("INSERT OR REPLACE INTO i2_pp_hist VALUES (?,?,?,?,?,?,?,?,?,?)",
                        (o, cls, 1 if k < 8 else 0, 2 + k % 5, n_sc, real,
                         round(R.uniform(0.2, 0.9), 3) if n_sc else None, 1.0, int(real > 0) if n_sc else None, now))
        con.execute("INSERT OR REPLACE INTO i2_kv VALUES (?, ?)", (f"helius:{time.strftime('%Y-%m-%d', time.gmtime(now))}",
                                                                   "2140"))
        con.execute("INSERT INTO i2_runs VALUES (?,?,?,?)", (now - 5 * H, "night", 2140,
                                                            json.dumps({"new_events": 12, "fetched": 9, "budget": 3500,
                                                                        "cap": 3500, "cap_how": "zadano"})))
        con.execute("INSERT OR REPLACE INTO i2_groups (owner, why, n_hits) VALUES (?,?,?)",
                    (b58("owner2"), "kupio prije poziva na 4 tokena", 4))
        from insajderi import birdeye
        birdeye.ensure(con)
        for t in ("be_usage", "be_tok", "be_top", "be_cand", "be_pp"):
            con.execute(f"DELETE FROM {t}")
        if not first_night:   # 19.11. navečer: Birdeye read the pump tokens and cross-checked the groups
            con.execute("INSERT INTO be_usage VALUES (?,?,?)", (time.strftime("%Y-%m", time.gmtime(now)), 42, 2100))
            for i, e in enumerate(events[:20]):
                con.execute("INSERT INTO be_tok VALUES (?,?,?,?,?)", (e[1], "24h", 30, "ok", now - H))
            for gi in range(12):
                con.execute("INSERT INTO be_pp VALUES (?,?,?,?,?,?,?)", (b58(f"owner{gi}"), "prije_pumpe", 3 + gi % 3,
                                                                      gi % 4, "[]", None, now))
            for i in range(6):
                con.execute("INSERT INTO be_cand VALUES (?,?,?,?,?,?,?,?)",
                            (b58(f"becand{i}"), 3 + i % 3, 1 + i % 2, 12000.0 - i * 900,
                             json.dumps(["smart_trader"] if i % 2 else []), now - i * H, 2 if i % 2 else 0, now))
    con.commit()
    con.close()

    # wallets.db: part of the members scored, the copy rank, the proven run
    from wallets import dokazani, rang, store as wstore
    wc = wstore.connect(paths["wallets"])
    dokazani.ensure(wc)
    wc.executescript(rang.SCHEMA)
    scored = [m for i, m in enumerate(out["members"][:120]) if i % 3 != 1] + [b58(f"top{i}") for i in range(12)]
    for i, w in enumerate(scored):
        stt = {"closed": R.randint(4, 80), "win_rate": round(R.uniform(0.3, 0.8), 2),
               "closed_pnl_sol": round(R.uniform(-5, 60), 3), "median_hold_min": 45, "trades_per_day": 6}
        stt["realized_sol"] = stt["closed_pnl_sol"]
        first = now - R.randint(10, 300) * D
        wc.execute("INSERT OR REPLACE INTO wallets (wallet, first_seen, last_seen, stats, last_tx_ts, history_from, scored_at, score) "
                   "VALUES (?,?,?,?,?,?,?,?)", (w, first, now, json.dumps(stt), now - R.randint(1, 50) * H, first, now,
                                               R.uniform(10, 90)))
        wc.execute("INSERT OR REPLACE INTO wallet_trades VALUES (?,?,?,?,?,?,?)", (w, b58(f"ws{i}a", 64), first, "M", 1, 1, "buy"))
        wc.execute("INSERT OR REPLACE INTO wallet_trades VALUES (?,?,?,?,?,?,?)", (w, b58(f"ws{i}b", 64), now - 3 * H, "M", 1, 1, "sell"))
        if i % 4 == 0:
            wc.execute("INSERT OR REPLACE INTO dokazani VALUES (?,?,?,?,?,?,?,?,?)", (w, now - H, 6, 2.0, 0.6, 3, 1.1, 0.66, 1))
        wc.execute("INSERT OR REPLACE INTO copy_rank VALUES ('wallet',?,?,?,?,?,?,?)", (w, now - H, R.uniform(20, 95), i % 4 == 0,
                                                                            i % 3 == 0, R.randint(3, 40), "{}"))
    from wallets import povijest
    povijest.ensure(wc)
    for t in ("povijest_queue", "povijest_runs", "veliki_holderi"):
        wc.execute(f"DELETE FROM {t}")
    if not empty:
        srcs = povijest.SOURCES
        for i, w in enumerate(out["members"][:150]):
            st_q = "ocijenjen" if i % 3 != 1 else ("preskočen: burza" if i % 17 == 0 else "čeka")
            wc.execute("INSERT OR REPLACE INTO povijest_queue VALUES (?,?,?,?,?,?,?,?,?)",
                       (w, srcs[i % len(srcs)], i % len(srcs), "{}", now - D, now, now - H if st_q == "ocijenjen" else None,
                        st_q, 30))
        wc.execute("INSERT INTO povijest_runs VALUES (?,?,?,?,?,?,?,?,?)",
                   (now - 2 * H, "night", 120, 96, 41, 5400, 1830.5, 1, "novčanici povijest: ..."))
        wc.execute("INSERT INTO helius_credits VALUES (?,?,?,?)", (now - H, "povijest", 5400, None))
        for i in range(16):
            tier = "15-200M" if i % 3 else "2-15M"
            w = out["members"][i * 3] if i < 6 else b58(f"holder{i}")
            wc.execute("INSERT OR REPLACE INTO veliki_holderi VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                       (w, b58(f"hmint{i % 4}", 40) + "pump", ["USELESS", "TROLL", HOSTILE_SYM, "SPX"][i % 4], tier,
                        8e7 if tier == "15-200M" else 6e6, 60000 + i * 21000, 0.4 + i / 10, now - (31 + i * 9) * D,
                        31 + i * 9, "holder_pos" if i % 2 else "snap", now))
    wc.commit()
    wc.close()
    try:
        rang._CACHE.clear()
    except Exception:  # noqa: BLE001
        pass

    # holderi.db
    from holderi import store as hstore
    hc = hstore.connect(paths["holderi"])
    for i in range(14):
        mint = b58(f"hmint{i % 4}", 40) + "pump"
        hc.execute("INSERT OR REPLACE INTO profile VALUES (?,?,?,?,?,?)", (mint, now, ["USELESS", "TROLL", "GIGA", "SPX"][i % 4],
                                                                          5e7, "rugcheck", "{}"))
        hc.execute("INSERT OR REPLACE INTO holder_pos VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                   (b58(f"holder{i}"), mint, now, 1e6, 0.012 + i / 1000, None if i == 13 else now - (20 + i * 17) * D,
                    5000, 40000 + i * 9000, 2.5 + i / 3, 0.8, None, f"k{i % 3}", 1 if i % 2 == 0 else 0))
    hc.commit()
    hc.close()

    # league.db: the demo account's wallet-following trades
    from league import store as lstore
    from trade import settings
    lc = lstore.connect(paths["league"])
    from insajderi import live as ilive
    from wallets import kopija_demo
    lc.executescript(ilive.SCHEMA)
    lc.executescript(kopija_demo.SCHEMA)
    from insajderi import pp_live
    pp_live.ensure(lc)
    lc.execute("DELETE FROM trades WHERE user IN (?, ?) AND (source LIKE 'kopija dokazanih%' OR source LIKE 'insajderi2%' "
               "OR source LIKE 'prije pumpe%' OR source LIKE 'bundle%')", (settings.PAPER_USER, pp_live.USER))
    for t in ("kopija_trades", "insajderi2_trades", "pp_trades"):
        lc.execute(f"DELETE FROM {t}")
    if not empty:
        for i in range(9):
            src = ("kopija dokazanih: " if i % 2 else "insajderi2: grupa ") + b58(f"w{i}:0")[:6]
            st_ = "open" if i < 3 else "closed"
            opened = now - (i + 1) * 5 * H
            ret = None if st_ == "open" else R.uniform(-0.2, 0.4)
            cur = lc.execute("INSERT INTO trades (user, token, symbol, opened_ts, closed_ts, status, size_usd, entry_px, "
                             "exit_px, ret, pnl_usd, source) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                             (settings.PAPER_USER, b58(f"dt{i}", 40) + "pump", ["WIF", "GIGA", HOSTILE_SYM, "PNUT"][i % 4],
                              opened, None if st_ == "open" else opened + 3 * H, st_, 15.0, 0.001,
                              None if ret is None else 0.001 * (1 + ret), ret, None, src))
            tid = cur.lastrowid
            mc = [25e6, 6e6, 90e6, 1.5e6][i % 4]
            if i % 2:
                lc.execute("INSERT INTO kopija_trades (user, token, wallet, trade_id, status, entry_mcap, liq) "
                           "VALUES (?,?,?,?,?,?,?)",
                           (settings.PAPER_USER, b58(f"dt{i}", 40) + "pump", out["members"][i], tid, st_, mc, 4e5))
            else:
                lc.execute("INSERT INTO insajderi2_trades (user, token, owner, wallet, trade_id, status, entry_mcap, liq) "
                           "VALUES (?,?,?,?,?,?,?,?)",
                           (settings.PAPER_USER, b58(f"dt{i}", 40) + "pump", out["groups"][i], out["members"][i], tid,
                            st_, mc, 4e5))
        bids = [r[0] for r in sqlite3.connect(paths["insajderi"]).execute("SELECT bid FROM i2_bundle").fetchall()]
        for i in range(10):   # the new demo account: prije pumpe (confirmed / kandidat) and bundles
            kind = ("prije_pumpe", "prije_pumpe_kandidat", "bundle")[i % 3]
            gid = bids[i % len(bids)] if kind == "bundle" and bids else out["groups"][i + 1]
            st_ = "open" if i < 4 else "closed"
            mc = [40e6, 8e6, 120e6, 3e6, 17e6][i % 5]
            ret = None if st_ == "open" else R.uniform(-0.25, 0.5)
            opened = now - (i + 1) * 3 * H
            tok = b58(f"pp{i}", 40) + "pump"
            cur = lc.execute("INSERT INTO trades (user, token, symbol, opened_ts, closed_ts, status, size_usd, entry_px, "
                             "exit_px, ret, source) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                             (pp_live.USER, tok, ["MEW", "FWOG", "SPX", "GOAT", "ACT"][i % 5], opened,
                              None if st_ == "open" else opened + 2 * H, st_, 15.0, 0.002,
                              None if ret is None else 0.002 * (1 + ret), ret,
                              f"{pp_live.SRC[kind]}: {gid[:6]} (novčanik kupio prije 4 s)"))
            lc.execute("INSERT INTO pp_trades (user, token, symbol, kind, gid, wallet, buy_ts, opened_ts, trade_id, size_usd, "
                       "entry_mcap, mc_bucket, liq, status, closed_ts, ret) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                       (pp_live.USER, tok, None, kind, gid, out["members"][i + 1], opened - 4, opened, cur.lastrowid, 15.0,
                        mc, pp_live.bucket(mc), 5e5, st_, None if st_ == "open" else opened + 2 * H, ret))
    # league.db signal_mjera (league/mjera.py): the measurement per entry of every wallet-following signal
    from league import mjera
    mjera.ensure(lc)
    lc.execute("DELETE FROM signal_mjera")
    if not empty and not first_night:
        srcs = mjera.SOURCES
        for i in range(60):
            src = srcs[i % len(srcs)]
            mc = [40e6, 8e6, 120e6, 1.5e6, 17e6, 300e6][i % 6]
            seen = now - (60 - i) * 2 * H
            st_ = "open" if i >= 54 else ("miss" if i % 9 == 0 else "closed")
            g = R.uniform(-0.3, 0.6)
            gid = out["groups"][i % len(out["groups"])] if src != "kopija" else out["members"][i]
            sym = [HOSTILE_SYM, "WIF", "GIGA", "MEW", "SPX", "FWOG"][i % 6]
            lc.execute("INSERT INTO signal_mjera (source, kind, gid, wallet, members, token, symbol, their_buy_ts, "
                       "seen_ts, delay_s, entry_ts, entry_price, entry_mcap, mc_bucket, liq, guard, status, exit_ts, "
                       "exit_price, exit_reason, ret_gross, cost_01, cost_05, ret_net_01, ret_net_05, token_day) "
                       "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                       (src, mjera.LABEL[src], gid, out["members"][i], "[]", b58(f"mt{i % 25}", 40) + "pump", sym,
                        seen - 4, seen, 4 + i % 9, None if st_ == "miss" else seen, None if st_ == "miss" else 0.01, mc,
                        mjera.bucket(mc), 4e5, ("MC ispod 30k" if i % 2 else "lažni pool (likvidnost veća od MC-a)")
                        if st_ == "miss" else "ok", st_, None if st_ != "closed" else seen + 3 * H,
                        None if st_ != "closed" else 0.01 * (1 + g),
                        "nije kopirljivo" if st_ == "miss" else (["prodali su", "stop", "vrijeme"][i % 3] if st_ == "closed"
                                                                  else None),
                        g if st_ == "closed" else None, 0.03, 0.06, g - 0.03 if st_ == "closed" else None,
                        g - 0.06 if st_ == "closed" else None, mjera.day(seen)))
    lc.commit()
    lc.close()

    # trade.db: the real-money pause
    from trade import executor
    tc = executor.connect(paths["trade"])
    settings.put(tc, "pravi_novac_pauza", {"on": bool(paused), "ts": now, "who": "Jure", "why": "test"}, "Jure")
    tc.close()
    return out


if __name__ == "__main__":
    d = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else ROOT)
    res = seed(paths_in(d), empty="--empty" in sys.argv, first_night="--prva-noc" in sys.argv)
    print(f"seed: {len(res['groups'])} grupa ({len(res['confirmed'])} potvrđeno) u {d}")
