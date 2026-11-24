"""Exchange (CEX) wallets on Solana and whether a token is listed on each exchange.

Registry (registry()): {address: {"exchange", "kind", "confidence", "status", "source"}} from, strongest first:
  1. holderi/burze_vlasnik.json  the owner's confirmations / additions: status "potvrđeno", confidence 1.0
  2. holderi/burze.json          the curated seed (versioned): every address "nepotvrđeno" with its source; only
                                 addresses that behave like an exchange hot wallet on chain were kept (see its note)
  3. holderi.db burze_dodane     Grok's proposals (MCP submit_exchange_wallet) and the heuristics' finds: "nepotvrđeno"
  4. wallets.db label "cex"      our own registry (dugo/: top holder of many long-term tokens = custodian): heuristic
An address is never "certain" unless the owner confirmed it; its weight in a signal is weight(conf) = 0.5 + 0.5 x conf.

Heuristics (no address list needed):
  cross_token   an owner among the top 20 holders of >= cross_min (5) different midcaps in our snapshots of 14 days,
                not a pool: a custodian / exchange (confidence 0.5)
  behaviour     a destination wallet with >= busy_sol SOL and 1000 signatures within busy_h hours (2 Helius credits):
                an exchange-like hot wallet (confidence 0.45; a bot can be busy too, so never alone above the threshold)
  sweep         a destination that forwards the token on to a known exchange wallet = a per-user deposit address of
                that exchange (confidence = the hot wallet's x 0.9)

Listing status (listed(mint, symbol)): the exchanges' own public market lists (free, no keys, cached a day in holderi.db
kv lst:<exchange>; Gate, MEXC, Bitget and Binance Alpha carry Solana contract addresses) and CoinGecko's free
coin-by-contract tickers (dugo/holders.listings). A symbol match is resolved by contract where the exchange tells it per
currency (KuCoin, Coinbase; cached a day). A contract match is "da"; a symbol-only match is "nesigurno" (symbols
collide); a symbol whose contract differs is "ne"; nothing is "ne". Binance and Bybit refuse some regions (geo block):
then "nepoznato" unless CoinGecko knows.
"""
import json
import os
import re
import sqlite3
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SEED = os.path.join(HERE, "burze.json")
OWNER = os.path.join(HERE, "burze_vlasnik.json")
BURN = {"1nc1nerator11111111111111111111111111111111", "11111111111111111111111111111111"}
TIER = {"binance": 1, "coinbase": 1, "okx": 1, "bybit": 1, "upbit": 1, "kucoin": 2, "gate": 2, "bitget": 2, "mexc": 2,
        "htx": 2, "kraken": 2, "crypto_com": 2, "bithumb": 2, "bingx": 3, "lbank": 3}
NAMES = {"binance": "Binance", "coinbase": "Coinbase", "okx": "OKX", "bybit": "Bybit", "upbit": "Upbit", "kucoin": "KuCoin",
         "gate": "Gate", "bitget": "Bitget", "mexc": "MEXC", "htx": "HTX", "kraken": "Kraken", "crypto_com": "Crypto.com",
         "bithumb": "Bithumb", "bingx": "BingX", "lbank": "LBank", "nepoznata": "nepoznata burza"}
# CoinGecko ticker market identifiers -> our exchange keys
CG_IDS = {"binance": "binance", "gdax": "coinbase", "coinbase": "coinbase", "okex": "okx", "okx": "okx",
          "bybit_spot": "bybit", "bybit": "bybit", "kucoin": "kucoin", "gate": "gate", "bitget": "bitget", "mxc": "mexc",
          "mexc": "mexc", "huobi": "htx", "htx": "htx", "kraken": "kraken", "upbit": "upbit", "bithumb": "bithumb",
          "crypto_com": "crypto_com", "bingx": "bingx", "lbank": "lbank"}
NAME_RE = re.compile(r"binance|coinbase|okx|okex|bybit|kucoin|gate\.?io|bitget|mexc|htx|huobi|kraken|crypto\.com|upbit|"
                     r"bithumb|bingx|lbank", re.I)
FETCH = {}   # tests: "lists" (exchange) -> {"symbols": [...], "contracts": [...]}, "cg" (mint) -> [exchange keys]
_C = {"ts": 0.0, "v": None}


def weight(conf):
    """An address's weight in a signal: 1.0 confirmed, 0.85 a 0.7 seed, 0.75 a 0.5 heuristic."""
    return round(0.5 + 0.5 * max(0.0, min(1.0, float(conf or 0))), 3)


def _load(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f) or {}
    except (OSError, ValueError):
        return {}


def norm_exchange(name):
    s = (name or "").strip().lower().replace(".", "_").replace(" ", "_")
    s = {"gate_io": "gate", "huobi": "htx", "okex": "okx", "crypto_com_exchange": "crypto_com"}.get(s, s)
    return s or "nepoznata"


def registry(db_path=None, wallet_db=None, fresh=False):
    """{address: {"exchange", "kind", "confidence", "status", "source"}} (see the module text), cached 60 s."""
    if not fresh and db_path is None and wallet_db is None and _C["v"] is not None and time.time() - _C["ts"] < 60:
        return _C["v"]
    out = {}

    def put(a, e, src_default, status, conf):
        if not a or not isinstance(a, str):
            return
        old = out.get(a)
        if old and old["status"] == "potvrđeno" and status != "potvrđeno":
            return
        out[a] = {"exchange": norm_exchange(e.get("exchange")), "kind": e.get("kind") or "hot",
                  "confidence": round(float(conf), 2), "status": status,
                  "source": e.get("source") or src_default}
    try:   # 4. our own registry (weakest)
        p = wallet_db or os.environ.get("WALLET_DB", os.path.join(ROOT, "wallets.db"))
        if os.path.exists(p):
            con = sqlite3.connect(f"file:{p}?mode=ro", uri=True, timeout=5)
            try:
                for w, lab in con.execute("SELECT wallet, labels FROM wallets WHERE labels LIKE '%cex%'"):
                    if "cex" in json.loads(lab or "[]"):
                        put(w, {"exchange": "nepoznata", "kind": "custodian"}, "wallets.db oznaka cex (dugo: top holder "
                            "mnogih tokena)", "nepotvrđeno", 0.5)
            finally:
                con.close()
    except (sqlite3.Error, ValueError):
        pass
    try:   # 3. Grok / heuristics
        from holderi import store
        con = store.ro(db_path)
        if con is not None:
            try:
                for a, e, k, c, st, src in con.execute(
                        "SELECT address, exchange, kind, confidence, status, source FROM burze_dodane"):
                    put(a, {"exchange": e, "kind": k, "source": src}, "dodano", "nepotvrđeno", min(0.6, c or 0.4))
            finally:
                con.close()
    except sqlite3.Error:
        pass
    for e in _load(SEED).get("adrese") or []:   # 2. the seed
        put(e.get("address"), e, "burze.json", "nepotvrđeno", min(0.8, float(e.get("confidence") or 0.5)))
    for e in _load(OWNER).get("adrese") or []:   # 1. the owner
        base = out.get(e.get("address")) or {}
        put(e.get("address"), {**base, **{k: v for k, v in e.items() if v}}, "vlasnik", "potvrđeno",
            float(e.get("confidence") or 1.0))
    if db_path is None and wallet_db is None:
        _C.update(ts=time.time(), v=out)
    return out


def seed_counts():
    """{"potvrđeno": n, "nepotvrđeno": n, "po_burzi": {exchange: n}} of the seed + the owner's file (for the report)."""
    reg = {}
    for e in _load(SEED).get("adrese") or []:
        reg[e["address"]] = ("nepotvrđeno", norm_exchange(e.get("exchange")))
    for e in _load(OWNER).get("adrese") or []:
        if e.get("address"):
            reg[e["address"]] = ("potvrđeno", norm_exchange(e.get("exchange") or (reg.get(e["address"]) or ("", ""))[1]))
    out = {"potvrđeno": 0, "nepotvrđeno": 0, "po_burzi": {}}
    for st, ex in reg.values():
        out[st] += 1
        out["po_burzi"][ex] = out["po_burzi"].get(ex, 0) + 1
    return out


def add(con, address, exchange, kind="hot", confidence=0.4, source="", who="grok", now=None):
    """Grok's proposal or a heuristic find into burze_dodane (never "potvrđeno": the owner confirms in his JSON file)."""
    if not isinstance(address, str) or not re.fullmatch(r"[1-9A-HJ-NP-Za-km-z]{32,44}", address or ""):
        raise ValueError("adresa nije Solana adresa")
    con.execute("INSERT OR REPLACE INTO burze_dodane VALUES (?,?,?,?,?,?,?,?)",
                (address, norm_exchange(exchange), (kind or "hot")[:20], round(min(0.6, max(0.0, float(confidence))), 2),
                 "nepotvrđeno", (source or "")[:300], int(now or time.time()), (who or "")[:40]))
    _C.update(ts=0.0)


def cross_token(con, now, min_tokens=5, days=14):
    """{owner: n midcaps} of owners among the top holders of >= min_tokens different midcaps (not pools / burn)."""
    rows = con.execute("SELECT owner, COUNT(DISTINCT mint) FROM snap WHERE ts >= ? AND cls NOT IN ('lp', 'burn') "
                       "GROUP BY owner HAVING COUNT(DISTINCT mint) >= ?", (int(now) - days * 86400, int(min_tokens)))
    return {o: n for o, n in rows if o}


def behaviour(sol, sigs_n, span_h, busy_sol=5000, busy_h=24):
    """An exchange-like hot wallet by behaviour: rich in SOL and very busy (see the module text). conf or None."""
    if sol is None or not sigs_n:
        return None
    if sol >= busy_sol and sigs_n >= 1000 and span_h is not None and span_h <= busy_h:
        return 0.45
    return None


def known_name(name):
    """An exchange key from a name RugCheck / a label gives ("Binance 2 Hot Wallet" -> "binance"), else None."""
    m = NAME_RE.search(name or "")
    return norm_exchange(m.group(0)) if m else None


# ---------- listing status ---------------------------------------------------------------------------------------------

def _g(url, params=None, ttl=86400):
    from event_calendar import http
    return http.get_json(url, params, ttl=ttl, timeout=20, retries=1)


def _sym(x):
    return str(x or "").strip().upper()


def _lists_binance():
    d = _g("https://api.binance.com/api/v3/exchangeInfo")
    syms = {_sym(s.get("baseAsset")) for s in d.get("symbols") or [] if s.get("status") == "TRADING"}
    out = {"symbols": sorted(syms), "contracts": []}
    try:   # Binance Alpha (public list with contract addresses); missing / changed: the spot list alone
        a = _g("https://www.binance.com/bapi/defi/v1/public/wallet-direct/buw/wallet/cex/alpha/all/token/list")
        for t in a.get("data") or []:
            if str(t.get("chainId") or "").upper() in ("CT_501", "SOL", "501") and t.get("contractAddress"):
                out["contracts"].append(t["contractAddress"])
                out.setdefault("alpha", []).append(t["contractAddress"])
    except Exception:  # noqa: BLE001
        pass
    return out


def _lists_okx():
    d = _g("https://www.okx.com/api/v5/public/instruments", {"instType": "SPOT"})
    return {"symbols": sorted({_sym(x.get("baseCcy")) for x in d.get("data") or [] if x.get("state") == "live"}),
            "contracts": []}


def _lists_bybit():
    d = _g("https://api.bybit.com/v5/market/instruments-info", {"category": "spot"})
    return {"symbols": sorted({_sym(x.get("baseCoin")) for x in (d.get("result") or {}).get("list") or []
                               if x.get("status") == "Trading"}), "contracts": []}


def _lists_kucoin():
    d = _g("https://api.kucoin.com/api/v2/symbols")
    return {"symbols": sorted({_sym(x.get("baseCurrency")) for x in d.get("data") or [] if x.get("enableTrading")}),
            "contracts": []}


def _lists_gate():
    d = _g("https://api.gateio.ws/api/v4/spot/currencies")
    syms, cons = set(), []
    for x in d if isinstance(d, list) else []:
        if x.get("trade_disabled") or x.get("delisted"):
            continue
        syms.add(_sym(str(x.get("currency") or "").split("_")[0]))
        for ch in x.get("chains") or []:
            if str(ch.get("name") or "").upper() == "SOL" and ch.get("addr"):
                cons.append(ch["addr"])
    return {"symbols": sorted(syms), "contracts": cons}


def _lists_mexc():
    d = _g("https://api.mexc.com/api/v3/exchangeInfo")
    syms, cons = set(), []
    for x in d.get("symbols") or []:
        syms.add(_sym(x.get("baseAsset")))
        if x.get("contractAddress"):
            cons.append(x["contractAddress"])
    return {"symbols": sorted(syms), "contracts": cons}


def _lists_bitget():
    d = _g("https://api.bitget.com/api/v2/spot/public/coins")
    syms, cons = set(), []
    for x in d.get("data") or []:
        syms.add(_sym(x.get("coin")))
        for ch in x.get("chains") or []:
            if str(ch.get("chain") or "").upper() in ("SOL", "SOLANA") and ch.get("contractAddress"):
                cons.append(ch["contractAddress"])
    return {"symbols": sorted(syms), "contracts": cons}


def _lists_htx():
    d = _g("https://api.huobi.pro/v1/common/symbols")
    return {"symbols": sorted({_sym(x.get("base-currency")) for x in d.get("data") or [] if x.get("state") == "online"}),
            "contracts": []}


def _lists_kraken():
    d = _g("https://api.kraken.com/0/public/Assets")
    syms = set()
    for k, v in (d.get("result") or {}).items():
        syms.add(_sym((v or {}).get("altname") or k))
    return {"symbols": sorted(syms), "contracts": []}


def _lists_coinbase():
    d = _g("https://api.exchange.coinbase.com/products")
    return {"symbols": sorted({_sym(x.get("base_currency")) for x in d if isinstance(x, dict)
                               and not x.get("trading_disabled")}) if isinstance(d, list) else [], "contracts": []}


def _lists_upbit():
    d = _g("https://api.upbit.com/v1/market/all")
    return {"symbols": sorted({_sym(str(x.get("market") or "").split("-")[-1]) for x in d if isinstance(x, dict)})
            if isinstance(d, list) else [], "contracts": []}


def _lists_bithumb():
    d = _g("https://api.bithumb.com/v1/market/all")
    return {"symbols": sorted({_sym(str(x.get("market") or "").split("-")[-1]) for x in d if isinstance(x, dict)})
            if isinstance(d, list) else [], "contracts": []}


def _lists_crypto_com():
    d = _g("https://api.crypto.com/exchange/v1/public/get-instruments")
    return {"symbols": sorted({_sym(x.get("base_ccy")) for x in ((d.get("result") or {}).get("data") or [])
                               if x.get("inst_type") == "CCY_PAIR"}), "contracts": []}


LISTERS = {"binance": _lists_binance, "okx": _lists_okx, "bybit": _lists_bybit, "kucoin": _lists_kucoin,
           "gate": _lists_gate, "mexc": _lists_mexc, "bitget": _lists_bitget, "htx": _lists_htx, "kraken": _lists_kraken,
           "coinbase": _lists_coinbase, "upbit": _lists_upbit, "bithumb": _lists_bithumb, "crypto_com": _lists_crypto_com}


def refresh_lists(con, now=None, every_s=86400, log=print):
    """Each exchange's market list into kv lst:<exchange> once a day (free, one request each; a failure keeps the old
    list and marks it). Returns the number of requests made."""
    from holderi import store
    now = int(now or time.time())
    n = 0
    for ex, fn in LISTERS.items():
        old = store.kv_get(con, f"lst:{ex}", {}) or {}
        if now - int(old.get("ts") or 0) < every_s and (old.get("symbols") or old.get("err_ts")):
            continue
        if old.get("err_ts") and now - int(old["err_ts"]) < 6 * 3600:
            continue
        n += 1
        try:
            d = FETCH["lists"](ex) if "lists" in FETCH else fn()
            if not d.get("symbols") and not d.get("contracts"):
                raise ValueError("prazna lista")
            store.kv_put(con, f"lst:{ex}", {"ts": now, "symbols": d.get("symbols") or [],
                                             "contracts": d.get("contracts") or [], "alpha": d.get("alpha") or []})
        except Exception as e:  # noqa: BLE001 - geo-blocked / down: the old list (or none) and a mark
            old.update(err_ts=now, err=f"{type(e).__name__}"[:60])
            store.kv_put(con, f"lst:{ex}", old)
            log(f"holderi: lista burze {NAMES.get(ex, ex)} nije stigla ({type(e).__name__})")
    con.commit()
    return n


def cg_listed(con, mint, now=None, ttl=86400):
    """Exchange keys CoinGecko lists the CONTRACT on (free, cached a day in kv cg:<mint>), None when unknown."""
    from holderi import store
    now = int(now or time.time())
    old = store.kv_get(con, f"cg:{mint}")
    if old and now - int(old.get("ts") or 0) < ttl:
        return old.get("ex")
    try:
        if "cg" in FETCH:
            ex = FETCH["cg"](mint)
        else:
            from dugo import holders as dh
            r = dh.listings(mint)
            ex = None if r is None else sorted({CG_IDS[i] for i in r[2] if i in CG_IDS})
    except Exception:  # noqa: BLE001
        ex = None
    store.kv_put(con, f"cg:{mint}", {"ts": now, "ex": ex})
    return ex


def _resolve_kucoin(sym):
    d = _g(f"https://api.kucoin.com/api/v3/currencies/{sym}")
    return [c.get("contractAddress") for c in ((d or {}).get("data") or {}).get("chains") or []
            if str(c.get("chainName") or c.get("chainId") or "").upper() in ("SOL", "SOLANA") and c.get("contractAddress")]


def _resolve_coinbase(sym):
    d = _g(f"https://api.exchange.coinbase.com/currencies/{sym}")
    return [n.get("contract_address") for n in (d or {}).get("supported_networks") or []
            if n.get("id") == "solana" and n.get("contract_address")]


RESOLVERS = {"kucoin": _resolve_kucoin, "coinbase": _resolve_coinbase}   # symbol -> Solana contracts (free, per symbol)


def resolve(con, ex, sym, now=None):
    """The Solana contract addresses `ex` trades under `sym` (cached a day in kv res:<ex>:<sym>), None when unknown."""
    from holderi import store
    if ex not in RESOLVERS and "resolve" not in FETCH:
        return None
    now = int(now or time.time())
    k = f"res:{ex}:{sym}"
    old = store.kv_get(con, k)
    if old and now - int(old.get("ts") or 0) < 86400:
        return old.get("c")
    try:
        c = FETCH["resolve"](ex, sym) if "resolve" in FETCH else RESOLVERS[ex](sym)
    except Exception:  # noqa: BLE001
        c = None
    store.kv_put(con, k, {"ts": now, "c": c})
    return c


def listed(con, mint, symbol, exchange, now=None, use_cg=True):
    """("da" | "nesigurno" | "ne" | "nepoznato", why) of one token on one exchange (see the module text)."""
    from holderi import store
    ex = norm_exchange(exchange)
    if ex == "nepoznata":
        return "nepoznato", "burza nepoznata"
    if use_cg:
        cg = cg_listed(con, mint, now)
        if cg and ex in cg:
            return "da", "CoinGecko: ugovor se trguje na " + NAMES.get(ex, ex)
    lst = store.kv_get(con, f"lst:{ex}", {}) or {}
    if mint in set(lst.get("contracts") or []):
        return "da", NAMES.get(ex, ex) + ": adresa ugovora na listi" + (" (Alpha)" if mint in (lst.get("alpha") or []) else "")
    if not lst.get("symbols"):
        return "nepoznato", NAMES.get(ex, ex) + ": lista nije dostupna"
    if _sym(symbol) and _sym(symbol) in set(lst["symbols"]):
        cons = resolve(con, ex, _sym(symbol), now)
        if cons and mint in cons:
            return "da", f"{NAMES.get(ex, ex)}: simbol {_sym(symbol)} s istom adresom ugovora"
        if cons:
            return "ne", f"{NAMES.get(ex, ex)}: simbol {_sym(symbol)} je drugi token (druga adresa)"
        return "nesigurno", f"{NAMES.get(ex, ex)}: isti simbol {_sym(symbol)} (možda drugi token)"
    return "ne", NAMES.get(ex, ex) + ": nije na listi"
