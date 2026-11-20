"""Swap logs -> parsed trades (pure), and the trader of each swap.

Pools (the dexes GeckoTerminal lists for the BSC memes we read): PancakeSwap v2 and its forks (the Uniswap v2 Swap),
PancakeSwap v3 (the Uniswap v3 Swap with two protocol-fee fields), Uniswap v3, and PancakeSwap Infinity CL (one
CLPoolManager emits every pool's Swap, topic1 = the pool id; the v4 sign convention). Four.meme and other launchpad
bonding curves are out (CLAUDE.md: only bonded tokens; no curve trades are read).

    v2        Swap(address indexed sender, uint amount0In, uint amount1In, uint amount0Out, uint amount1Out,
              address indexed to)
    v3        Swap(address indexed sender, address indexed recipient, int256 amount0, int256 amount1, uint160, uint128,
              int24[, uint128, uint128])   amounts from the POOL's side: > 0 = into the pool
    infinity  Swap(bytes32 indexed id, address indexed sender, int128 amount0, int128 amount1, uint160, uint128, int24,
              uint24, uint16)              amounts from the SWAPPER's side: > 0 = to the swapper (checked on a live
              PIEVERSE/USDT swap 19.11.: +48 PIEVERSE, -140 USDT at a GeckoTerminal price of 2.97 $)

token0 / token1: the lower / higher address (v2 / v3 / infinity all sort them; infinity's native BNB is address 0).

The trader (attribute): the Swap's `to` / `recipient` is often a router or an aggregator, and infinity has no
recipient at all, so the trader is taken from the TOKEN's own Transfer logs of the same transaction: for a buy, the
tokens that left the pool are followed hop by hop (pool -> router -> wallet) to the address where they stay; for a
sell, the tokens that entered the pool are followed back to the address they came from. That is the address that
holds and later sells the tokens (the one the tracker watches), with smart wallets, solvers and aggregators handled
alike. No Transfer chain found: the Swap's recipient (v2 / v3), else the sender (how = "recipient" / "sender").
Measured against the transaction's sender (eth_getTransactionByHash from) in bnb/izvori.md.
"""
from bnb.keccak import keccak256, topic

TRANSFER = topic("Transfer(address,address,uint256)")
V2 = topic("Swap(address,uint256,uint256,uint256,uint256,address)")
V3 = topic("Swap(address,address,int256,int256,uint160,uint128,int24)")
V3_PCS = topic("Swap(address,address,int256,int256,uint160,uint128,int24,uint128,uint128)")
INF_CL = topic("Swap(bytes32,address,int128,int128,uint160,uint128,int24,uint24,uint16)")
SWAP_TOPICS = (V2, V3, V3_PCS, INF_CL)
INF_CL_MANAGER = "0xa0ffb9c1ce1fe56963b0321b32e7a0302114058b"
INF_VAULT = "0x238a358808379702088667322f80ac48bad5e6c4"
SEL_POOLKEY = "0x" + keccak256("poolIdToPoolKey(bytes32)")[:4].hex()
SEL_DECIMALS = "0x313ce567"
SEL_TOKEN0 = "0x0dfe1681"
ZERO = "0x" + "0" * 40

WBNB = "0xbb4cdb9cbd36b01bd1cbaebf2de08d9173bc095c"
QUOTES = {   # address -> (symbol, decimals, USD series): what a memecoin is priced in on BSC
    WBNB: ("WBNB", 18, "bnb"), ZERO: ("BNB", 18, "bnb"),
    "0x55d398326f99059ff775485246999027b3197955": ("USDT", 18, "usd"),
    "0x8ac76a51cc950d9822d68b83fe1ad97b32cd580d": ("USDC", 18, "usd"),
    "0xe9e7cea3dedca5984780bafc599bd69add087d56": ("BUSD", 18, "usd"),
    "0x8d0d000ee44948fc98c9b98a4fa4921476f08b0d": ("USD1", 18, "usd"),
    "0xc5f0f7b66764f6ec8c8dff7ba683102295e16409": ("FDUSD", 18, "usd"),
}
DEX_KIND = {"pancakeswap_v2": "v2", "pancakeswap-v3-bsc": "v3", "uniswap-bsc": "v2", "uniswap-v3-bsc": "v3",
            "pancakeswap-infinity-clmm": "inf", "biswap": "v2", "apeswap_bsc": "v2", "babydogeswap": "v2",
            "sushiswap-bsc": "v2", "thena-fusion": "v3a", "squadswap-v2": "v2", "squadswap-v3": "v3"}


def addr(t):
    """The address in a 32-byte topic / word ('0x' + 40 hex, lower case)."""
    return "0x" + t[-40:].lower()


def _words(data):
    d = data[2:] if data.startswith("0x") else data
    return [d[i:i + 64] for i in range(0, len(d), 64)]


def _s(w):
    v = int(w, 16)
    return v - (1 << 256) if v >= 1 << 255 else v


def kind_of(dex, pool):
    """'v2' | 'v3' | 'inf' | None of a GeckoTerminal dex id (an infinity pool's address is its 32-byte id)."""
    if pool and len(pool) == 66:
        return "inf"
    return DEX_KIND.get(dex) or ("v3" if "v3" in (dex or "") else "v2" if "v2" in (dex or "") or "swap" in (dex or "")
                                 else None)


def token_is0(token, quote):
    return token.lower() < quote.lower()


def decode(log, token, quote, tdec=18, qdec=18, is0=None):
    """One Swap log -> {"tx", "li", "block", "ts", "side", "amt", "qamt", "recip", "sender", "kind"} from the
    memecoin's side (side "buy" = the swapper received the token), or None (not a swap of this pair / zero)."""
    t0 = log["topics"][0]
    w = _words(log.get("data") or "0x")
    is0 = token_is0(token, quote) if is0 is None else is0
    if t0 == V2 and len(w) >= 4:
        a0i, a1i, a0o, a1o = (int(x, 16) for x in w[:4])
        ti, to_, qi, qo = (a0i, a0o, a1i, a1o) if is0 else (a1i, a1o, a0i, a0o)
        if to_ > ti:
            side, amt, qamt = "buy", to_ - ti, qi - qo
        elif ti > to_:
            side, amt, qamt = "sell", ti - to_, qo - qi
        else:
            return None
        kind, recip, sender = "v2", addr(log["topics"][2]), addr(log["topics"][1])
    elif t0 in (V3, V3_PCS) and len(w) >= 2:
        a0, a1 = _s(w[0]), _s(w[1])
        ta, qa = (a0, a1) if is0 else (a1, a0)          # pool side: > 0 into the pool
        if ta < 0:
            side, amt, qamt = "buy", -ta, qa
        elif ta > 0:
            side, amt, qamt = "sell", ta, -qa
        else:
            return None
        kind, recip, sender = "v3", addr(log["topics"][2]), addr(log["topics"][1])
    elif t0 == INF_CL and len(w) >= 2:
        a0, a1 = _s(w[0]), _s(w[1])
        ta, qa = (a0, a1) if is0 else (a1, a0)          # swapper side: > 0 to the swapper
        if ta > 0:
            side, amt, qamt = "buy", ta, -qa
        elif ta < 0:
            side, amt, qamt = "sell", -ta, qa
        else:
            return None
        kind, recip, sender = "inf", None, addr(log["topics"][2])
    else:
        return None
    if qamt <= 0:
        qamt = 0
    ts = log.get("blockTimestamp")
    return {"tx": log["transactionHash"].lower(), "li": int(log["logIndex"], 16), "block": int(log["blockNumber"], 16),
            "ts": int(ts, 16) if ts else None, "side": side, "amt": amt / 10 ** tdec, "qamt": qamt / 10 ** qdec,
            "recip": recip, "sender": sender, "kind": kind}


def transfers_by_tx(logs):
    """{tx: [(li, from, to, value)]} of Transfer logs (sorted by log index)."""
    out = {}
    for lg in logs:
        if lg["topics"][0] != TRANSFER or len(lg["topics"]) < 3:
            continue
        v = int((lg.get("data") or "0x0")[2:] or "0", 16)
        out.setdefault(lg["transactionHash"].lower(), []).append(
            (int(lg["logIndex"], 16), addr(lg["topics"][1]), addr(lg["topics"][2]), v))
    for v in out.values():
        v.sort()
    return out


def _follow_out(trs, start, holder, raw, skip):
    """From `holder` (who just got `raw` at log index `start`): the next transfer of most of it onward (>= 50 %), hop
    by hop -> the address where the tokens stay."""
    seen = {holder}
    li = start
    while True:
        nxt = [t for t in trs if t[0] > li and t[1] == holder and t[3] >= raw * 0.5 and t[2] not in seen
               and t[2] not in skip]
        if not nxt:
            return holder
        li, _f, holder, raw = max(nxt, key=lambda t: t[3])
        seen.add(holder)


def _follow_in(trs, end, holder, raw, skip):
    """Back from `holder` (who sent `raw` at log index `end`): the transfer that brought most of it to it, hop by hop
    -> the address the tokens came from."""
    seen = {holder}
    li = end
    while True:
        prv = [t for t in trs if t[0] < li and t[2] == holder and t[3] >= raw * 0.5 and t[1] not in seen
               and t[1] != ZERO and t[1] not in skip]
        if not prv:
            return holder
        li, holder, _t, raw = max(prv, key=lambda t: t[3])
        seen.add(holder)


def attribute(sw, trs, pools, used=None):
    """(trader, how) of decoded swap sw, given its tx's token transfers trs [(li, from, to, value)] and the set of
    pool / vault addresses. used: transfer log indexes already matched in this tx (several swaps in one tx)."""
    used = used if used is not None else set()
    pools = {p.lower() for p in pools}
    if trs:
        if sw["side"] == "buy":
            cand = [t for t in trs if t[1] in pools and t[0] not in used]
        else:
            cand = [t for t in trs if t[2] in pools and t[0] not in used]
        if cand:
            # the transfer nearest the Swap log (v2 / v3 move the tokens just before emitting it)
            t = min(cand, key=lambda x: abs(x[0] - sw["li"]))
            used.add(t[0])
            if sw["side"] == "buy":
                return _follow_out(trs, t[0], t[2], t[3], pools), "transfer"
            return _follow_in(trs, t[0], t[1], t[3], pools), "transfer"
    if sw.get("recip"):
        return sw["recip"], "recipient"
    return sw.get("sender"), "sender"


def parse(swap_logs, transfer_logs, token, quote, pools, tdec=18, qdec=18, is0=None):
    """Swap logs + the token's Transfer logs of the same blocks -> [trade dict with "trader", "how"], deduplicated by
    (tx, log index)."""
    trs = transfers_by_tx(transfer_logs)
    out, seen, used = [], set(), {}
    for lg in sorted(swap_logs, key=lambda x: (int(x["blockNumber"], 16), int(x["logIndex"], 16))):
        sw = decode(lg, token, quote, tdec, qdec, is0)
        if not sw or (sw["tx"], sw["li"]) in seen:
            continue
        seen.add((sw["tx"], sw["li"]))
        sw["trader"], sw["how"] = attribute(sw, trs.get(sw["tx"]), pools, used.setdefault(sw["tx"], set()))
        out.append(sw)
    return out
