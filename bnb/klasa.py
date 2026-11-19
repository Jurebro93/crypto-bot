"""Step 3: the class "kupuje prije pumpe" on BSC and the funnel.

The class is insajderi/prijepumpe.classify ITSELF, called on bnb_part rows in i2_part's shape (eid, wallet, owner,
buy_ts, sol_in, n_sells, sol_out, first_sell_ts, bought_before, sold_into, lead_s): bought before AND sold into >= 3
distinct pump tokens, a paid buy >= min_sol (sol_in here is the buy's USD / SOLUSDT of that hour, so 0.05 means
"0.05 SOL in USD at the time"), median lead >= 2 min, confirmed when the older 2/3 of the covered pumps already hold
3 tokens and the newer 1/3 adds >= 1 more. Its exclusions with the same names, fed from the BSC rows:

  bot           (bad) the same address buys AND sells one token in the same BLOCK (sandwich / arbitrage), or makes >
                bot_tx_min trades in one minute, or > 4 x bot_tx_min trades of one token in our windows
  snajper       first buy within sniper_secs of the pool's creation (first_trade = GeckoTerminal / DexScreener pool age)
  kupuje_sve    early in >= busy_events_share of >= 10 covered pumps
  market_maker  >= mm_min_side buys AND sells of one token inside one window [t0 - 6 h, win_end] on >= 2 windows
  jednokratni   seen in one event only
And two the chain adds (applied over classify's verdict, they take precedence):
  ugovor        the address has code (eth_getCode, read only for addresses with >= 2 hits: the list and "near the
                threshold"): a bot / router / vault contract. An EIP-7702 account (code 0xef0100 + delegate: an EOA that
                delegates to a smart-wallet implementation) is NOT a contract here: it is a person's wallet.
  router        a known router / aggregator / CEX hot wallet (KNOWN; an EOA hot wallet has no code)

Owner groups: the single address (owner = wallet). Funder grouping (the first inbound BNB transfer of an address)
needs an indexer: the public RPC cannot list an address's transactions (no getTransactionsForAddress, eth_getLogs
cannot see native BNB transfers), so it is not done (bnb/izvori.md).
"""
import json
import statistics
from collections import Counter, defaultdict

from bnb import store

KNOWN = {   # lower case; routers / aggregators / CEX hot wallets (public labels)
    "0x10ed43c718714eb63d5aa57b78b54704e256024e": "PancakeSwap v2 router",
    "0x13f4ea83d0bd40e75c8222255bc855a974568dd4": "PancakeSwap smart router",
    "0x1b81d678ffb9c0263b24a97847620c99d213eb14": "PancakeSwap v3 router",
    "0x1a0a18ac4becddbd6389559687d1a73d8927e416": "PancakeSwap universal router",
    "0x1111111254eeb25477b68fb85ed929f73a960582": "1inch v5",
    "0x111111125421ca6dc452d289314280a0f8842a65": "1inch v6",
    "0xdef1c0ded9bec7f1a1670819833240f027b25eff": "0x exchange proxy",
    "0x9333c74bdd1e118634fe5664aca7a9710b108bab": "OKX DEX router",
    "0x6131b5fae19ea4f9d964eac0408e4408b66337b5": "KyberSwap router",
    "0x8894e0a0c962cb723c1976a4421c95949be2d4e3": "Binance hot wallet",
    "0xe2fc31f816a9b94326492132018c3aecc4a93ae1": "Binance hot wallet",
    "0x3c783c21a0383057d128bae431894a5c19f9cf06": "Binance hot wallet",
    "0xdccf3b77da55107280bd850ea519df3705d1a75a": "Binance hot wallet",
    "0xf977814e90da44bfa03b6295a0616a897441acec": "Binance hot wallet",
    "0x5a52e96bacdabb82fd05763e25335261b270efcb": "Binance hot wallet",
    "0x0d0707963952f2fba59dd06f2b425ace40b492fe": "Gate.io hot wallet",
    "0x161ba15a5f335c9f06bb5bbb0a9ce14076fbb645": "Bitget hot wallet",
}
WHY = {"ugovor": "ugovor (adresa ima kod: bot, router ili trezor)", "router": "router / agregator / burza"}


def _med(xs):
    xs = [x for x in xs if x is not None]
    return statistics.median(xs) if xs else None


def parts(con):
    return store.q(con, "SELECT eid, wallet, owner, buy_ts, sol_in, n_sells, sol_out, first_sell_ts, bought_before, "
                        "sold_into, lead_s FROM bnb_part")


def bots(con, c, cand):
    """Addresses among cand that trade like bots (see the module text)."""
    if not cand:
        return set()
    out = {w for (w,) in store.q(con, "SELECT DISTINCT trader FROM bnb_trades GROUP BY trader, token, block "
                                      "HAVING COUNT(DISTINCT side) > 1")}
    out |= {w for (w,) in store.q(con, "SELECT DISTINCT trader FROM bnb_trades GROUP BY trader, ts / 60 "
                                       "HAVING COUNT(*) > ?", (int(c["bot_tx_min"]),))}
    out |= {w for (w,) in store.q(con, "SELECT DISTINCT trader FROM bnb_trades GROUP BY trader, token "
                                       "HAVING COUNT(*) > ?", (4 * int(c["bot_tx_min"]),))}
    return out & set(cand)


def market_makers(con, events, c):
    by_tok = defaultdict(list)
    for e in events:
        if e.get("tier"):
            by_tok[e["token"]].append((int(e["t0"]) - 6 * 3600, int(e["win_end"])))
    side_min, ev_min = int(c["mm_min_side"]), int(c["mm_min_events"])
    hits = Counter()
    for tok, wins in by_tok.items():
        rows = store.q(con, "SELECT trader, ts, side FROM bnb_trades WHERE token = ?", (tok,))
        for lo, hi in wins:
            n = defaultdict(lambda: [0, 0])
            for w, ts, side in rows:
                if lo <= (ts or 0) <= hi:
                    n[w][0 if side == "buy" else 1] += 1
            for w, (b, s) in n.items():
                if b >= side_min and s >= side_min:
                    hits[w] += 1
    return {w for w, k in hits.items() if k >= ev_min}


def code_kinds(con, rpc, addrs, now):
    """{addr: "eoa" | "7702" | "ugovor"} (eth_getCode, batched; cached in bnb_code)."""
    have = {a: k for a, k in store.q(con, "SELECT addr, kind FROM bnb_code")}
    todo = [a for a in addrs if a not in have]
    if todo and rpc is not None:
        res = rpc.batch([("eth_getCode", [a, "latest"]) for a in todo])
        rows = []
        for a, code in zip(todo, res):
            if code is None:
                continue
            k = "eoa" if code in ("0x", "0x0") else ("7702" if code.lower().startswith("0xef0100") else "ugovor")
            have[a] = k
            rows.append((a, k, int(now)))
        con.executemany("INSERT OR REPLACE INTO bnb_code VALUES (?,?,?)", rows)
        con.commit()
    return {a: have.get(a) for a in addrs}


def hit_counts(ps, events, c):
    """{wallet: distinct pump tokens bought (paid) before and sold into}."""
    tiered = {e["eid"]: e for e in events if e.get("tier")}
    toks = defaultdict(set)
    for r in ps:
        if r[0] in tiered and r[8] and r[9] and (r[4] or 0) >= float(c["min_sol"]):
            toks[r[1]].add(tiered[r[0]]["token"])
    return toks


def first_trades(con):
    return {t: ts for t, ts in store.q(con, "SELECT token, pool_created FROM bnb_tokens WHERE pool_created IS NOT NULL")}


def run(con, c, events, now, rpc=None):
    """Classify every owner (prijepumpe.classify + the chain's two exclusions), store bnb_pp. -> (stats, funnel)."""
    from insajderi import prijepumpe
    ev = [dict(e, n_part=e.get("n_part")) for e in events if e.get("fetched")]
    ps = parts(con)
    cand = {r[1] for r in ps if r[8]}
    bad = bots(con, c, cand)
    mm = market_makers(con, ev, c)
    st = prijepumpe.classify(ps, ev, now + 1, c, bad, first_trades(con), mm)
    hits = hit_counts(ps, ev, c)
    look = sorted(w for w, t in hits.items() if len(t) >= int(c["pump_min_tokens"]) - 1)
    kinds = code_kinds(con, rpc, look, now) if look else {}
    for o, s in st.items():
        if o in KNOWN:
            s["cls"], s["why"], s["confirmed"] = "router", f"{WHY['router']}: {KNOWN[o]}", False
        elif kinds.get(o) == "ugovor":
            s["cls"], s["why"], s["confirmed"] = "ugovor", WHY["ugovor"], False
    save(con, st, ps, ev, c, now)
    return st, funnel(con, c, events, ps, st, now)


def pump_detail(owner_rows, ev, c):
    """[{eid, token, symbol, t0, tier, lead_min, usd_in, usd_out}] of an owner's paid before-and-into pumps."""
    out = []
    for r in owner_rows:
        e = ev.get(r[0])
        if not e or not (r[8] and r[9] and (r[4] or 0) >= float(c["min_sol"])):
            continue
        out.append({"eid": r[0], "token": e["token"], "symbol": e.get("symbol"), "t0": int(e["t0"]), "tier": e["tier"],
                    "lead_min": round(r[10] / 60, 1) if r[10] is not None else None,
                    "usd_in": round(r[11] or 0, 2), "usd_out": round(r[12] or 0, 2)})
    return sorted(out, key=lambda x: x["t0"])


def save(con, st, ps, ev_list, c, now):
    ev = {e["eid"]: e for e in ev_list}
    usd = {(eid, w): (ui, uo) for eid, w, ui, uo in store.q(con, "SELECT eid, wallet, usd_in, usd_out FROM bnb_part")}
    by = defaultdict(list)
    for r in ps:
        by[r[2] or r[1]].append(tuple(r) + usd.get((r[0], r[1]), (None, None)))
    old = {o: ts for o, ts in store.q(con, "SELECT owner, confirmed_ts FROM bnb_pp")}
    con.execute("DELETE FROM bnb_pp")
    rows = []
    for o, s in st.items():
        if s["cls"] in ("promatra", "jednokratni"):
            continue
        det = pump_detail(by.get(o, []), ev, c)
        pnl_usd = round(sum(d["usd_out"] - d["usd_in"] for d in det), 2) if det else None
        cts = (old.get(o) or int(now)) if s["confirmed"] else None
        rows.append((store.CHAIN, o, json.dumps(s["members"]), len(s["members"]), s["cls"], s["why"], s["n_pumps15"],
                     s["n_pumps2"], s["n_tokens"], s["med_lead_min"], s["pnl_sol"], pnl_usd,
                     json.dumps(det[:40], ensure_ascii=False), cts, s["last_seen"], int(now)))
    con.executemany("INSERT INTO bnb_pp VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)
    con.commit()
    return len(rows)


def funnel(con, c, events, ps, st, now):
    """prijepumpe.funnel's keys on the BSC tables, plus "izvan_dosega" (pumps whose windows are older than the free
    history), "procitano" (read, any depth) and "klase" (owners per class)."""
    from insajderi import events as iev
    from insajderi import prijepumpe
    out = {k: 0 for k in ("pumpe15_1h", "pumpe15_1d", "pumpe2_1h", "pumpe2_1d", "duboko", "rani", "rani_prodali",
                          "blizu_praga", "grupe", "potvrdjeno", "izvan_dosega", "procitano")}
    tiered = {e["eid"]: e for e in events if e.get("tier") in ("pumpa15", "pumpa2")}
    for e in tiered.values():
        out[f"pumpe{'15' if e['tier'] == 'pumpa15' else '2'}_{iev.res_of(e)}"] += 1
        out["izvan_dosega"] += e.get("reach") == "izvan dosega"
    cov = {eid: (d, pc, jc) for eid, d, pc, jc in store.q(con, "SELECT eid, depth, pre_cov, jump_cov FROM bnb_cover")}
    deep = [cov[eid] for eid in tiered if eid in cov and (cov[eid][0] or 0) >= store.FETCH_DEPTH]
    out["duboko"] = out["procitano"] = len(deep)
    pre = [x[1] for x in deep if x[1] is not None]
    jmp = [x[2] for x in deep if x[2] is not None]
    out["pokrivenost_pre_med"] = round(100 * _med(pre), 1) if pre else None
    out["pokrivenost_skok_med"] = round(100 * _med(jmp), 1) if jmp else None
    out["n_pokrivenost"] = len(pre)
    rani, prodali = set(), set()
    for r in ps:
        if r[0] in tiered and r[8]:
            rani.add(r[1])
            if r[9]:
                prodali.add(r[1])
    out["rani"], out["rani_prodali"] = len(rani), len(prodali)
    need = int(c["pump_min_tokens"])
    excl = {o for o, s in st.items() if s["cls"] not in ("prije_pumpe", "kandidat", "promatra")}
    out["blizu_praga"] = sum(1 for w, v in hit_counts(ps, list(tiered.values()), c).items()
                             if len(v) == need - 1 and w not in excl)
    out["grupe"] = sum(1 for s in st.values() if s["cls"] == "prije_pumpe")
    out["potvrdjeno"] = len(prijepumpe.confirmed(st))
    out["klase"] = dict(Counter(s["cls"] for s in st.values()))
    return out


def funnel_line(f):
    if not f:
        return store.PREFIX + "lijevak: još nema prolaza"
    cov = (f"medijan {f['pokrivenost_pre_med']:.0f} % (skok {f['pokrivenost_skok_med']:.0f} %, "
           f"{f['n_pokrivenost']} pumpi)" if f.get("pokrivenost_pre_med") is not None else "još nema čitanja")
    return (f"{store.PREFIX}lijevak: pumpi ≥ 15M {f['pumpe15_1h'] + f['pumpe15_1d']} (1h {f['pumpe15_1h']}, 1d "
            f"{f['pumpe15_1d']}), 2-15M {f['pumpe2_1h'] + f['pumpe2_1d']} (1h {f['pumpe2_1h']}, 1d {f['pumpe2_1d']}); "
            f"izvan besplatne povijesti {f['izvan_dosega']}; pročitano {f['duboko']}; ranih kupaca {f['rani']}, od "
            f"njih prodali u pumpu {f['rani_prodali']}; blizu praga (2 pumpe) {f['blizu_praga']}; grupa s 3+ pumpe "
            f"{f['grupe']}; potvrđeno {f['potvrdjeno']}; pokrivenost prozora prije skoka: {cov}")
