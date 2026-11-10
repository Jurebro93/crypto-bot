"""Istraživanje tokena Hope (10.11.2026., Jure: "nađi tko je zvao CA prije Marka, poveži influencere s novčanicima
koji su kupili prije Marka, odnosno prije pumpe; budi kritičan; bez primjene na algoritam").

READ-ONLY. Nothing here writes to a trading database or changes a setting. It reads:
  - the chain (Helius getTransactionsForAddress, counted by usage/meter): every transaction of the pump.fun bonding
    curve and of the PumpSwap pool;
  - kol.db calls (who posted the CA, when, at which market cap), kol_ids (wallet -> X / Telegram account),
    wallets.db (tier, score, labels), hype.db chain_trades (buys of the wallets we follow live).
Output: DATA_DIR/research/hope-20261110.json (every wallet and every call) and .md (the summary), a summary in the
log, and the JSON gzip+base64 in log lines "RESEARCH-HOPE i/n ..." (report/dump style). The MCP tool get_research
(ui/mcpapi) serves the files to Grok.

Cost (CLAUDE.md: measure before spending): Helius getTransactionsForAddress, 100 full transactions a page at ~10
credits, so the ~2.2k curve and ~10k pool transactions are ~120 pages, ~1.2k credits (getTransaction one by one would
be ~12k). Pages are not written to the file cache (they would be ~80 MB of disk for one report).

Run: python3 -m research.hope [--force] [--max-pages N]; start.sh runs it once (marker file .done next to the report).
"""
import argparse
import base64
import gzip
import json
import os
import sqlite3
import sys
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

MINT = "GxRPJsRK9TE9EgBhLxrFGcRYLGqPJe4fxtiPmdXCpump"
CURVE = "BwGRcHJGA6CK8VJfNALiSpc7qDMiq49jwNhs4Smv4dUZ"    # pump.fun bonding curve (launched 2025-08-28)
POOL = "63ucbB1ZAzdmFCZaPWL1Z2aa9XAr7ht95TaoghzwnabB"      # PumpSwap pool (migration 2026-11-10 10:01:56 UTC)
WSOL = "So11111111111111111111111111111111111111112"
MARKO = "0xmarko77"
NAME = "hope-20261110"
SUPPLY = 1e9
MAX_PAGES = 300          # getTransactionsForAddress: 100 transactions a page, ~10 credits a page (30k tx, ~3k credits)
LOG_CHUNK = 3000


def out_dir():
    data = os.environ.get("DATA_DIR")
    base = data if data and os.path.isdir(data) else ROOT
    d = os.path.join(base, "research")
    os.makedirs(d, exist_ok=True)
    return d


def _post(method, params):
    """One Helius call, not cached (wallets/rpc._rpc writes every answer to the file cache), counted by the usage meter
    (event_calendar/http._fetch); retries with back-off on errors."""
    from event_calendar import http
    from wallets import rpc
    key = os.environ.get("HELIUS_API_KEY")
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode()
    for i in range(5):
        try:
            req = urllib.request.Request(f"{rpc.URL}?api-key={key}", data=body, method="POST",
                                         headers={"Content-Type": "application/json", "User-Agent": http.USER_AGENT})
            data = http._fetch(req, 60)
            if "error" in data:
                raise RuntimeError(f"Helius {method}: {data['error']}")
            return data["result"]
        except Exception:  # noqa: BLE001 - 429 / timeouts: back off and try again
            if i == 4:
                raise
            time.sleep(3 * (i + 1))


def pages(addr, since_ts=0, max_pages=MAX_PAGES, post=None):
    """All successful transactions of addr that moved a token balance, oldest first: (list of full transactions,
    complete). getTransactionsForAddress pages of 100."""
    post = post or _post
    flt = {"status": "succeeded", "tokenAccounts": "balanceChanged"}
    if since_ts:
        flt["blockTime"] = {"gt": int(since_ts)}
    out, token = [], None
    for _ in range(max_pages):
        opts = {"transactionDetails": "full", "encoding": "jsonParsed", "maxSupportedTransactionVersion": 0,
                "limit": 100, "sortOrder": "asc", "filters": flt}
        if token:
            opts["paginationToken"] = token
        res = post("getTransactionsForAddress", [addr, opts]) or {}
        data = res.get("data") or []
        out += [parse_tx(t) for t in data]
        token = res.get("paginationToken")
        if not token or not data:
            return out, True
    return out, False


def parse_tx(tx):
    """One full transaction -> {sig, ts, slot, signer, tok (the signer's change of this token), sol (the signer's SOL
    + wSOL change, fees and account rent included), others (other owners whose balance of this token changed)}."""
    meta = tx.get("meta") or {}
    msg = tx["transaction"]["message"]
    keys = [k["pubkey"] if isinstance(k, dict) else k for k in msg["accountKeys"]]
    sig = (tx["transaction"].get("signatures") or [None])[0]
    signer = keys[0]

    def bal(rows, mint):
        out = {}
        for b in rows or []:
            if b.get("mint") == mint:
                o = b.get("owner")
                out[o] = out.get(o, 0.0) + float(b["uiTokenAmount"].get("uiAmount") or 0)
        return out
    pre, post = bal(meta.get("preTokenBalances"), MINT), bal(meta.get("postTokenBalances"), MINT)
    wpre, wpost = bal(meta.get("preTokenBalances"), WSOL), bal(meta.get("postTokenBalances"), WSOL)
    tok = post.get(signer, 0.0) - pre.get(signer, 0.0)
    sol = (meta["postBalances"][0] - meta["preBalances"][0]) / 1e9 + (wpost.get(signer, 0.0) - wpre.get(signer, 0.0))
    others = {o: round(post.get(o, 0.0) - pre.get(o, 0.0), 3) for o in set(pre) | set(post)
              if o != signer and abs(post.get(o, 0.0) - pre.get(o, 0.0)) > 0}
    return {"sig": sig, "ts": tx.get("blockTime"), "slot": tx.get("slot"), "signer": signer, "tok": tok, "sol": sol,
            "others": others}


def _ro(path):
    if not path or not os.path.exists(path):
        return None
    try:
        return sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=20)
    except sqlite3.Error:
        return None


def _paths():
    from kol import store as kstore
    from wallets import store as wstore
    from ui import data
    return kstore.DB, wstore.DB, data.HYPE_DB


def calls():
    kdb, _w, _h = _paths()
    kc = _ro(kdb)
    if kc is None:
        return []
    try:
        cols = [r[1] for r in kc.execute("PRAGMA table_info(calls)")]
        want = [c for c in ("tweet_id", "handle", "ts", "kind", "source", "mcap0", "p0", "followers", "url", "text",
                            "first_overall", "views", "likes") if c in cols]
        rows = kc.execute(f"SELECT {', '.join(want)} FROM calls WHERE token=? ORDER BY ts", (MINT,)).fetchall()
        out = [dict(zip(want, r)) for r in rows]
        fol = {}
        try:
            for h, f in kc.execute("SELECT handle, followers FROM kols"):
                fol[(h or "").lower()] = f
        except sqlite3.Error:
            pass
        for c in out:
            c["followers_now"] = fol.get((c.get("handle") or "").lower())
            if c.get("text"):
                c["text"] = c["text"][:280]
        return out
    except sqlite3.Error:
        return []
    finally:
        kc.close()


def links(wallets):
    """{wallet: {"x", "tg", "name", "src"}} from kol.db kol_ids; {wallet: {"tier", "score", "labels"}} from wallets.db;
    {wallet: [(ts, side, sol)]} from hype.db chain_trades for this token (wallets we follow live)."""
    kdb, wdb, hdb = _paths()
    ids, tiers, live = {}, {}, {}
    ws = sorted(set(wallets))
    kc = _ro(kdb)
    if kc is not None:
        try:
            for w, name, tw, tg, src in kc.execute("SELECT wallet, name, twitter, telegram, source FROM kol_ids"):
                if w in wallets:
                    ids[w] = {"name": name, "x": tw, "tg": tg, "src": src}
        except sqlite3.Error:
            pass
        finally:
            kc.close()
    wc = _ro(wdb)
    if wc is not None:
        try:
            have = {r[1] for r in wc.execute("PRAGMA table_info(wallets)")}
            cols = [c for c in ("tier", "score", "labels") if c in have]
            for i in range(0, len(ws), 500):
                part = ws[i:i + 500]
                for r in wc.execute(f"SELECT wallet, {', '.join(cols) or 'NULL'} FROM wallets "
                                    f"WHERE wallet IN ({','.join('?' * len(part))})", part):
                    tiers[r[0]] = dict(zip(cols, r[1:]))
        except sqlite3.Error:
            pass
        finally:
            wc.close()
    hc = _ro(hdb)
    if hc is not None:
        try:
            for w, side, ts, sol in hc.execute("SELECT wallet, side, ts, sol FROM chain_trades WHERE mint=? ORDER BY ts",
                                               (MINT,)):
                live.setdefault(w, []).append((ts, side, sol))
        except sqlite3.Error:
            pass
        finally:
            hc.close()
    return ids, tiers, live


def caller_wallets(handles):
    """{handle: [wallet]} of the callers' known wallets (kol_ids by X / Telegram name, any case)."""
    kdb, _w, _h = _paths()
    kc = _ro(kdb)
    out = {}
    if kc is None:
        return out
    want = {h.lower().lstrip("@").replace("tg:", ""): h for h in handles}
    try:
        for w, tw, tg in kc.execute("SELECT wallet, twitter, telegram FROM kol_ids"):
            for v in (tw, tg):
                k = (v or "").lower().lstrip("@").split("/")[-1]
                if k in want:
                    out.setdefault(want[k], []).append(w)
    except sqlite3.Error:
        pass
    finally:
        kc.close()
    return out


def holders(post=None):
    _p = post or _post
    try:
        res = _p("getTokenLargestAccounts", [MINT])
        accs = [(a["address"], float(a.get("uiAmount") or 0)) for a in (res or {}).get("value", [])][:20]
        info = _p("getMultipleAccounts", [[a for a, _ in accs], {"encoding": "jsonParsed"}]) or {}
        owners = []
        for (addr, amt), acc in zip(accs, info.get("value") or []):
            o = (((acc or {}).get("data") or {}).get("parsed") or {}).get("info", {}).get("owner")
            owners.append({"token_account": addr, "owner": o, "amount": amt, "pct": round(100 * amt / SUPPLY, 2)})
        return owners
    except Exception as e:  # noqa: BLE001
        return [{"error": str(e)[:120]}]


def sol_usd():
    try:
        from trade import equity
        return (equity.rates() or {}).get("sol_usd") or 150.0
    except Exception:  # noqa: BLE001
        return 150.0


def run(max_pages=MAX_PAGES, log=print, post=None):
    t0 = time.time()
    migr = 1794304916
    curve, c_ok = pages(CURVE, 0, max_pages, post)
    pool, p_ok = pages(POOL, migr - 60, max_pages, post)
    log(f"research hope: {len(curve)} transakcija krivulje{'' if c_ok else ' (NIJE SVE)'}, {len(pool)} poola"
        f"{'' if p_ok else ' (NIJE SVE)'}")
    seen, trades = set(), []
    for venue, rows in (("curve", curve), ("pool", pool)):
        for r in rows:
            if r["sig"] in seen:
                continue
            seen.add(r["sig"])
            r["venue"] = venue
            trades.append(r)
    trades = [t for t in trades if not t.get("fail")]
    trades.sort(key=lambda t: (t.get("ts") or 0, t.get("slot") or 0))
    su = sol_usd()
    cl = calls()
    marko = next((c for c in cl if (c.get("handle") or "").lower().lstrip("@") == MARKO), None)
    marko_ts = marko["ts"] if marko else None
    # per wallet
    W = {}

    def new(addr):
        return W.setdefault(addr, {"wallet": addr, "buys": 0, "sells": 0, "sol_in": 0.0, "sol_out": 0.0, "tok_in": 0.0,
                                   "tok_out": 0.0, "first_buy_ts": None, "first_buy_venue": None, "first_buy_mc": None,
                                   "first_buy_mc_sol": None, "first_sell_ts": None, "last_sell_ts": None,
                                   "received_tok": 0.0, "received_from": [], "sent_tok": 0.0, "sent_to": []})
    for t in trades:
        # tokens that went to someone other than the signer (bought for / sent to another wallet): the classic way
        # to spread one buyer over many wallets; the curve and the pool themselves are not wallets
        for o, d_ in (t.get("others") or {}).items():
            if d_ > 0 and o not in (CURVE, POOL):
                r, sw = new(o), new(t["signer"])
                r["received_tok"] += d_
                r["tok_other"] = r.get("tok_other", 0.0) + d_
                sw["sent_tok"] += d_
                if t["signer"] not in r["received_from"]:
                    r["received_from"].append(t["signer"])
                if o not in sw["sent_to"]:
                    sw["sent_to"].append(o)
                r["first_receive_ts"] = r.get("first_receive_ts") or t["ts"]
        if abs(t["tok"]) < 1:
            continue
        w = new(t["signer"])
        if t["tok"] > 0 and t["sol"] < -0.0001:          # paid SOL, got the token: a buy
            px = -t["sol"] / t["tok"]
            w["buys"] += 1
            w["tok_in"] += t["tok"]
            w["sol_in"] += -t["sol"]
            if w["first_buy_ts"] is None:
                w.update(first_buy_ts=t["ts"], first_buy_venue=t["venue"], first_buy_mc=round(px * SUPPLY * su),
                         first_buy_mc_sol=round(px * SUPPLY, 1), first_buy_slot=t["slot"], first_buy_sig=t["sig"])
        elif t["tok"] < 0 and t["sol"] > 0:               # gave the token, got SOL: a sell
            w["sells"] += 1
            w["tok_out"] += -t["tok"]
            w["sol_out"] += t["sol"]
            w["first_sell_ts"] = w["first_sell_ts"] or t["ts"]
            w["last_sell_ts"] = t["ts"]
        elif t["tok"] > 0:                                 # got the token without paying (transfer in it signed)
            w["tok_in"] += t["tok"]
            w["received_tok"] += t["tok"]
        else:                                              # sent the token away without SOL back
            w["tok_out"] += -t["tok"]
            w["sent_tok"] += -t["tok"]
    for w in W.values():
        w["net_tok"] = round(w["tok_in"] - w["tok_out"], 2)
        w["pnl_sol"] = round(w["sol_out"] - w["sol_in"], 4)
        w["sol_in"], w["sol_out"] = round(w["sol_in"], 4), round(w["sol_out"], 4)
        w["received_tok"], w["sent_tok"] = round(w["received_tok"], 2), round(w["sent_tok"], 2)
        w["net_tok"] = round(w["tok_in"] + w.pop("tok_other", 0.0) - w["tok_out"], 2)
        fb = w["first_buy_ts"] or 0
        if fb and fb < 1757000000:
            w["phase"] = "lansiranje 2025"
        elif fb and fb < migr:
            w["phase"] = "punjenje krivulje (prije migracije)"
        elif marko_ts and fb and fb < marko_ts:
            w["phase"] = "nakon migracije, prije Marka"
        elif fb:
            w["phase"] = "nakon Marka" if marko_ts else "nakon migracije"
        elif w["received_tok"]:
            w["phase"] = "samo primio tokene (nije kupio)"
        else:
            w["phase"] = "samo prodaja/prijenos"
    ids, tiers, live = links(list(W))
    for w, d in W.items():
        d["x_or_tg"] = ids.get(w)
        d["tier"] = (tiers.get(w) or {}).get("tier")
        d["score"] = (tiers.get(w) or {}).get("score")
        d["labels"] = (tiers.get(w) or {}).get("labels")
        d["followed_live"] = live.get(w)
    # same-slot first buys (possible bundles)
    by_slot = {}
    for d in W.values():
        if d.get("first_buy_slot"):
            by_slot.setdefault(d["first_buy_slot"], []).append(d["wallet"])
    bundles = {s: ws for s, ws in by_slot.items() if len(ws) >= 3}
    before = [c for c in cl if marko_ts and c["ts"] < marko_ts]
    cw = caller_wallets([c["handle"] for c in cl if c.get("handle")])
    caller_trades = {h: [{"wallet": w, **{k: W[w].get(k) for k in ("first_buy_ts", "first_buy_mc", "sol_in", "sol_out",
                                                                       "first_sell_ts", "phase")}} for w in ws if w in W]
                     for h, ws in cw.items()}
    res = {"token": MINT, "curve": CURVE, "pool": POOL, "migration_ts": migr, "sol_usd": su,
           "complete": {"curve": c_ok, "pool": p_ok},
           "generated_ts": int(time.time()), "n_trades": len(trades), "n_wallets": len(W),
           "calls": cl, "marko_call": marko, "calls_before_marko": before, "caller_wallets": cw,
           "caller_trades": caller_trades, "bundles_first_buy_same_slot": {str(k): v for k, v in bundles.items()},
           "holders_top20": holders(post), "wallets": sorted(W.values(), key=lambda d: d.get("first_buy_ts") or 9e12)}
    d = out_dir()
    with open(os.path.join(d, NAME + ".json"), "w") as f:
        json.dump(res, f, ensure_ascii=False)
    md = summary_md(res)
    with open(os.path.join(d, NAME + ".md"), "w") as f:
        f.write(md)
    for line in md.splitlines()[:80]:
        log(f"research hope | {line}")
    blob = base64.b64encode(gzip.compress(json.dumps(compact(res), ensure_ascii=False).encode(), 9)).decode()
    parts = [blob[i:i + LOG_CHUNK] for i in range(0, len(blob), LOG_CHUNK)]
    for i, p in enumerate(parts):
        log(f"RESEARCH-HOPE {i + 1}/{len(parts)} {p}")
    log(f"research hope: gotovo za {time.time() - t0:.0f} s, {len(trades)} transakcija, {len(W)} novčanika")
    return res


WCOLS = ("wallet", "first_buy_ts", "first_buy_venue", "first_buy_mc", "sol_in", "sol_out", "first_sell_ts",
         "last_sell_ts", "net_tok", "phase", "tier", "score", "buys", "sells", "first_buy_slot", "first_buy_mc_sol",
         "received_tok", "received_from", "first_receive_ts", "sent_tok", "sent_to")


def compact(res, marko_pad=1800, min_sol=1.0):
    """What goes into the log (the file and MCP keep everything): every wallet that bought before Marko's call + 30 min
    (or before the migration + 2 h when Marko is not in kol.db), put in 1+ SOL, has a tier, a linked account or is
    followed live; as rows of WCOLS, plus the calls, the callers' trades and the top holders."""
    m = res.get("marko_call") or {}
    edge = (m.get("ts") or res["migration_ts"] + 7200) + marko_pad
    def cell(w, c):
        v = w.get(c)
        return v[:10] if isinstance(v, list) else v
    rows = [[cell(w, c) for c in WCOLS] + [(w.get("x_or_tg") or {}).get("x") or (w.get("x_or_tg") or {}).get("tg"),
                                           bool(w.get("followed_live"))]
            for w in res["wallets"]
            if (w.get("first_buy_ts") or 9e12) < edge or w["sol_in"] >= min_sol or w.get("tier") or w.get("x_or_tg")
            or w.get("followed_live") or w.get("received_from") or w.get("sent_to")]
    return {k: v for k, v in res.items() if k != "wallets"} | {"wcols": list(WCOLS) + ["account", "followed"],
                                                                 "wrows": rows, "wallets_total": len(res["wallets"])}


def _t(ts):
    return time.strftime("%d.%m. %H:%M:%S", time.gmtime(ts + 3600)) if ts else "–"   # CET (UTC+1 in November)


def summary_md(r):
    ws = r["wallets"]
    ph = {}
    for w in ws:
        p = ph.setdefault(w["phase"], {"n": 0, "sol_in": 0.0, "pnl": 0.0, "hold": 0})
        p["n"] += 1
        p["sol_in"] += w["sol_in"]
        p["pnl"] += w["pnl_sol"]
        p["hold"] += 1 if w["net_tok"] > 1 else 0
    L = [f"# Hope ({r['token']})", f"transakcija {r['n_trades']}, novčanika {r['n_wallets']}, SOL/USD {r['sol_usd']:.0f}", ""]
    L.append("## Faze prve kupnje")
    for k, p in ph.items():
        L.append(f"- {k}: {p['n']} novčanika, uloženo {p['sol_in']:.2f} SOL, rezultat {p['pnl']:+.2f} SOL, još drži {p['hold']}")
    m = r.get("marko_call")
    L.append("")
    L.append(f"## Pozivi (kol.db): {len(r['calls'])}; Marko: {_t(m['ts']) + ' MC ' + str(m.get('mcap0')) if m else 'nije u bazi'}")
    for c in r["calls"][:40]:
        L.append(f"- {_t(c['ts'])} {c.get('handle')} ({c.get('kind')}, {c.get('source')}) MC {c.get('mcap0')} "
                 f"pratitelja {c.get('followers_now') or c.get('followers')}")
    L.append("")
    L.append("## Calleri s poznatim novčanikom i njihovi tradeovi na Hopeu")
    for h, ts_ in r["caller_trades"].items():
        for t in ts_:
            L.append(f"- {h} {t['wallet'][:6]}…: prva kupnja {_t(t['first_buy_ts'])} MC {t['first_buy_mc']} "
                     f"({t['phase']}), uložio {t['sol_in']} SOL, prodao {t['sol_out']} SOL, prva prodaja {_t(t['first_sell_ts'])}")
    L.append("")
    L.append("## Prvih 40 kupaca (po vremenu)")
    for w in ws[:40]:
        tag = " ".join(x for x in (f"tier {w['tier']}" if w.get("tier") else "",
                                    f"@{(w.get('x_or_tg') or {}).get('x')}" if (w.get("x_or_tg") or {}).get("x") else "",
                                    "praćen" if w.get("followed_live") else "") if x)
        L.append(f"- {_t(w['first_buy_ts'])} {w['wallet'][:6]}… {w['phase']}: MC {w['first_buy_mc']}, uložio {w['sol_in']} SOL, "
                 f"prodao {w['sol_out']} SOL, prva prodaja {_t(w['first_sell_ts'])}, drži {w['net_tok']:.0f} {tag}")
    L.append("")
    L.append(f"## Isti slot prve kupnje (3+ novčanika): {len(r['bundles_first_buy_same_slot'])}")
    for slot, ws_ in list(r["bundles_first_buy_same_slot"].items())[:15]:
        L.append(f"- slot {slot}: {len(ws_)} novčanika")
    send = sorted((w for w in ws if len(w.get("sent_to") or []) >= 2), key=lambda w: -len(w["sent_to"]))
    L.append(f"## Kupio/poslao tokene na druge novčanike (2+ primatelja): {len(send)}")
    for w in send[:20]:
        L.append(f"- {w['wallet'][:6]}… → {len(w['sent_to'])} novčanika, {w['sent_tok']:.0f} tokena, "
                 f"prva kupnja {_t(w['first_buy_ts'])} ({w['phase']})")
    L.append("## Top 20 holdera")
    for h in r["holders_top20"]:
        L.append(f"- {h}")
    return "\n".join(L)


def main(argv=None):
    p = argparse.ArgumentParser(description="Istraživanje tokena Hope (samo čitanje)")
    p.add_argument("--force", action="store_true")
    p.add_argument("--max-pages", type=int, default=MAX_PAGES)
    a = p.parse_args(argv)
    marker = os.path.join(out_dir(), NAME + ".done")
    if os.path.exists(marker) and not a.force:
        print("research hope: već napravljeno", flush=True)
        return 0
    if not os.environ.get("HELIUS_API_KEY"):
        print("research hope: nema HELIUS_API_KEY", flush=True)
        return 1
    run(a.max_pages, log=lambda s: print(s, flush=True))
    with open(marker, "w") as f:
        f.write(str(int(time.time())))
    return 0


if __name__ == "__main__":
    sys.exit(main())
