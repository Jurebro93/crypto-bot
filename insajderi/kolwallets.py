"""Insajderski novčanici influencera (16.11., vlasnik: "Pratiš li sve ove? Kako naći njihove sekundarne wallete. To su
ljudi koji moraju generirati kupovine da bi mogli izaći. Mora postojati stavka 'insider wallet' i algoritam koji ih
traži"): for each influencer of the seed list (insajderi/kol_seed.json) the wallets that are PROBABLY linked to him.

Everything here is a statistical inference from public on-chain data about real, named people: the rows carry their
evidence (which calls, times, transactions), the wording is "vjerojatno povezani novčanici", never a stated fact, and
nothing of it goes to a public page, the sitemap or share/novosti (the owner's view and the MCP read tool only).

  seed      load_seed: kol_seed.json (name, X handles, publicly documented wallets with a source; an unresolved handle
            or address stays empty) + kol.db kol_ids (public tracker wallets of the same handle) + the proposals of
            the MCP tool submit_kol_wallet (ik_seed_dodano, "nepotvrđeno": shown, never used). A wallet the person
            publicly denied ("osporeno") is shown and never used as an anchor.
  calls     find_calls: his FIRST public signal per token: a post with the mint (kol.db calls kind call / brag, X and
            Telegram 'tg:<kanal>'; makroinf.db tweets with a mint in the text; our own ik_posts) or, kol_public_buys,
            a buy of his public tracker wallet (kol.db calls kind 'buy', what copy traders follow). t0 = that time.
            Nothing here needs a new X read. fetch_posts is the OPTIONAL one (twitterapi.io, off while kol_x_usd_day is
            0, capped a day, metered in usage.db): a refusal (HTTP 402) is one line "nema kredita" and a pause.
  trades    around: per call the wallets that BOUGHT in [t0 - pre_days, t0) and still held (their last trade before t0
            is a buy), bucket under 10 min / 24 h / 7 d, and SOLD in [t0, t0 + 60 min] / 24 h. Data: the existing chain
            machinery (chain.sources: every free source + i2_trades); Helius through chain.fetch_event with its own
            small share of the day cap (kol_helius_share, kol_pass_credits), each window read once.
  owners    chain.owners (shared funder, fee payer, corr.db) + our own ties (first funding, token transfers), so a
            wallet rotation or a split to side wallets is ONE group.
  score     per influencer and group: calls it front-ran, share of those it sold into, lift against chance
            (score.lift: how often the group front-runs ANY event of the universe), exclusivity (share of the group's
            front-run events that are this influencer's), median lead, SOL in / out.
  links     to his public wallet(s): the same owner by our funding data, a SOL or token transfer FROM the public
            wallet (a token transfer shortly before the sale = the "split"), a shared first funder, at most kol_hops
            hops, never through a hub (exchange, relayer, a funder of many). A transfer INTO the public wallet is
            weak (people gift tokens to public wallets) and never counts.
  classes   potvrđen: >= 3 of his calls front-run AND confirmed on the newer third (the older two thirds already hold
            2) AND lift >= kol_min_lift on a universe of >= kol_min_universe events, or a strong link AND >= 2 calls;
            kandidat: 2 calls or a strong link alone; else not listed. Bots, snipers, relayers and wallets that
            front-run most of all events are out (score.py's rules).
  live      predpoziv (flag insajderi_kol, default shadow, NEVER live, no account ever buys): a buy of a "potvrđen"
            group in the trades we already store -> an event; later whether he called the token, the lead time, the
            price after the call (kol.db r1h / r24h) and whether the group sold after the post.

Tables ik_* in insajderi.db; the pass (run_pass) runs inside run_insajderi's once / night / incr passes, bounded in
time and credits, and never raises into its caller.
"""
import json
import os
import re
import statistics
import time
from collections import defaultdict

from insajderi import chain, score, store

PREFIX = "insajderi kol: "
FLAG = "insajderi_kol"
SEED = os.path.join(store.ROOT, "insajderi", "kol_seed.json")
ADDR = re.compile(r"[1-9A-HJ-NP-Za-km-z]{32,44}")
HANDLE = re.compile(r"[A-Za-z0-9_]{1,15}")
WALLET_STATUS = ("javna_oznaka", "vlasnik", "osporeno")
ANCHOR = {"javna_oznaka", "vlasnik"}          # public wallets a link may be anchored to
WALLET_STATUS_HR = {"javna_oznaka": "javna oznaka trackera", "vlasnik": "potvrdio vlasnik",
                    "osporeno": "osporeno (osoba kaže da nije njezin)"}
STATUS_HR = {"pratimo": "pratimo", "nema_poziva": "nema poziva u podacima", "bez_handlea": "handle nije potvrđen"}
KIND_HR = {"objava": "objava", "javna_kupnja": "kupnja javnog novčanika"}
LINK_HR = {"isti_vlasnik": "isti vlasnik po našim podacima o financiranju",
           "financiranje": "prvo financiranje novčanika",
           "prijenos_sol": "prijenos SOL-a s javnog novčanika",
           "prijenos_tokena": "prijenos tokena s javnog novčanika",
           "podjela_tokena": "prijenos tokena s javnog novčanika malo prije prodaje",
           "zajednicki_izvor": "isti prvi izvor sredstava",
           "uplata_na_javni": "uplata na javni novčanik (slabo: javnim novčanicima se često šalje)"}
POSTS = ("call", "brag")
XFER_MAX_SOL = 0.01      # a signer that "sold" for less than this received no SOL: it moved the tokens
CAVEAT = ("Ovo je statistički zaključak iz javnih on-chain podataka: novčanici su VJEROJATNO povezani, to nije "
          "dokazana činjenica ni tvrdnja o nečijoj namjeri. Svaki redak ima dokaze koje možeš sam provjeriti.")

SCHEMA = """
CREATE TABLE IF NOT EXISTS ik_calls (inf TEXT, token TEXT, symbol TEXT, t0 INTEGER, handle TEXT, kind TEXT, ref TEXT,
    url TEXT, mcap0 REAL, n_front INTEGER, covered INTEGER DEFAULT 0, fetched INTEGER DEFAULT 0, seen_ts INTEGER,
    PRIMARY KEY (inf, token));
CREATE TABLE IF NOT EXISTS ik_transfers (sig TEXT, ts INTEGER, kind TEXT, src TEXT, dst TEXT, amount REAL, mint TEXT,
    first_in INTEGER DEFAULT 0, PRIMARY KEY (sig, kind, src, dst, mint));
CREATE INDEX IF NOT EXISTS ik_transfers_dst ON ik_transfers (dst);
CREATE INDEX IF NOT EXISTS ik_transfers_src ON ik_transfers (src);
CREATE TABLE IF NOT EXISTS ik_wallets (inf TEXT, owner TEXT, members TEXT, cls TEXT, why TEXT, n_front INTEGER,
    n_sold INTEGER, n_sold60 INTEGER, n_any INTEGER, share_sold REAL, lift REAL, exclusivity REAL, med_lead_min REAL,
    sol_in REAL, sol_out REAL, link INTEGER, links TEXT, evidence TEXT, score REAL, first_ts INTEGER,
    confirmed_ts INTEGER, updated INTEGER, PRIMARY KEY (inf, owner));
CREATE TABLE IF NOT EXISTS ik_status (inf TEXT PRIMARY KEY, name TEXT, handles TEXT, public TEXT, status TEXT,
    n_calls INTEGER, n_covered INTEGER, n_listed INTEGER, n_confirmed INTEGER, note TEXT, ord INTEGER, updated INTEGER);
CREATE TABLE IF NOT EXISTS ik_seed_dodano (id INTEGER PRIMARY KEY AUTOINCREMENT, inf TEXT, name TEXT, handle TEXT,
    address TEXT, source TEXT, status TEXT, who TEXT, ts INTEGER);
CREATE TABLE IF NOT EXISTS ik_posts (inf TEXT, handle TEXT, tweet_id TEXT, token TEXT, ts INTEGER, url TEXT, kind TEXT,
    PRIMARY KEY (tweet_id, token));
CREATE TABLE IF NOT EXISTS ik_predpoziv (inf TEXT, token TEXT, symbol TEXT, owner TEXT, wallet TEXT, buy_ts INTEGER,
    sol REAL, seen_ts INTEGER, called INTEGER, call_ts INTEGER, call_ref TEXT, r1h REAL, r24h REAL, sold_ts INTEGER,
    closed INTEGER DEFAULT 0, PRIMARY KEY (inf, token));
"""


def ensure(con):
    con.executescript(SCHEMA)


def mode():
    """off | shadow | paper of the flag insajderi_kol (default shadow; never live). Unreadable = off."""
    try:
        from trade import settings
        m = settings.flag(FLAG)
        return "shadow" if m == "live" else m
    except Exception:  # noqa: BLE001
        return "off"


def _chunks(xs, n=400):
    xs = list(xs)
    for i in range(0, len(xs), n):
        yield xs[i:i + n]


def _in(xs):
    return ",".join("?" * len(xs))


def _med(xs):
    xs = [x for x in xs if x is not None]
    return statistics.median(xs) if xs else None


# ===================================================================================================================
# the seed
# ===================================================================================================================
def _handle(h):
    h = str(h or "").strip().lstrip("@")
    return h if HANDLE.fullmatch(h) else None


def load_seed(path=None, con=None, kol_db=None):
    """[{id, name, handles, telegram, wallets [{address, status, label, source}], proposals, note, public_buys}].
    Never invents: a handle or an address that does not parse is dropped, an empty list stays empty."""
    try:
        with open(path or SEED, encoding="utf-8") as f:
            raw = json.load(f)
    except (OSError, ValueError):
        raw = {}
    out, by_id = [], {}
    for e in (raw.get("influenceri") if isinstance(raw, dict) else None) or []:
        if not isinstance(e, dict) or not e.get("name"):
            continue
        iid = re.sub(r"[^a-z0-9_]", "", str(e.get("id") or e["name"]).lower())[:24]
        if not iid or iid in by_id:
            continue
        wallets = []
        for w in e.get("wallets") or []:
            a = w.get("address") if isinstance(w, dict) else None
            if isinstance(a, str) and ADDR.fullmatch(a) and a not in {x["address"] for x in wallets}:
                wallets.append({"address": a, "status": w.get("status") if w.get("status") in WALLET_STATUS
                                else "javna_oznaka", "label": str(w.get("label") or "")[:120],
                                "source": str(w.get("source") or "")[:300]})
        d = {"id": iid, "name": str(e["name"])[:60],
             "handles": [h for h in (_handle(x) for x in e.get("handles") or []) if h],
             "telegram": [t for t in (_handle(x) for x in e.get("telegram") or []) if t],
             "handle_source": e.get("handle_source"), "wallets": wallets, "proposals": [],
             "note": e.get("note")}
        by_id[iid] = d
        out.append(d)
    by_handle = {h.lower(): e for e in out for h in e["handles"]}
    kc = store.ro(kol_db)
    for w, name, tw, src in store.q(kc, "SELECT wallet, name, twitter, source FROM kol_ids WHERE twitter IS NOT NULL"):
        e = by_handle.get(str(tw).lstrip("@").lower())
        if e is not None and ADDR.fullmatch(w or "") and w not in {x["address"] for x in e["wallets"]}:
            e["wallets"].append({"address": w, "status": "javna_oznaka", "label": f"{src or 'tracker'}: {name or tw}",
                                 "source": f"kol.db kol_ids ({src or 'javna ljestvica'})"})
    if kc is not None:
        kc.close()
    for inf, name, handle, a, source, status, who, ts in store.q(
            con, "SELECT inf, name, handle, address, source, status, who, ts FROM ik_seed_dodano ORDER BY ts DESC LIMIT 200"):
        e = by_id.get(inf)
        if e is not None:
            e["proposals"].append({"handle": handle, "address": a, "source": source, "status": status, "who": who,
                                   "ts": ts})
    for e in out:   # a disputed wallet: its buys are not his public signal
        e["public_buys"] = bool(e["wallets"]) and all(w["status"] in ANCHOR for w in e["wallets"])
    return out


def submit(args, who="grok", path=None, now=None):
    """MCP submit_kol_wallet {influencer, handle?, address?, source}: one row in ik_seed_dodano as "nepotvrđeno" (as
    holderi's submit_exchange_wallet): shown to the owner, never used by the algorithm until he writes it into
    kol_seed.json. At most 30 an hour per caller."""
    a = args or {}
    now = int(now or time.time())
    inf = re.sub(r"[^a-z0-9_]", "", str(a.get("influencer") or "").lower())[:24]
    handle = _handle(a.get("handle")) if a.get("handle") else None
    addr = str(a.get("address") or "").strip() or None
    source = str(a.get("source") or a.get("evidence") or "").strip()[:300]
    if not inf:
        return {"error": "influencer je obavezan (id iz get_kol_insider_wallets ili kratko ime)"}
    if a.get("handle") and not handle:
        return {"error": "handle nije valjan (slova, brojke i _, najviše 15 znakova)"}
    if addr and not ADDR.fullmatch(addr):
        return {"error": "adresa nije valjana Solana adresa"}
    if not handle and not addr:
        return {"error": "treba handle ili adresa"}
    if not source:
        return {"error": "source je obavezan (javna poveznica na kojoj to piše)"}
    con = store.connect(path)
    try:
        ensure(con)
        n = con.execute("SELECT COUNT(*) FROM ik_seed_dodano WHERE who = ? AND ts >= ?", (who, now - 3600)).fetchone()[0]
        if n >= 30:
            return {"error": "najviše 30 prijedloga na sat"}
        con.execute("INSERT INTO ik_seed_dodano (inf, name, handle, address, source, status, who, ts) VALUES "
                    "(?,?,?,?,?,?,?,?)", (inf, str(a.get("name") or "")[:60] or None, handle, addr, source,
                                          "nepotvrđeno", who, now))
        con.commit()
        return {"stored": True, "status": "nepotvrđeno",
                "note": "vlasnik potvrđuje u insajderi/kol_seed.json; dotad se prijedlog samo prikazuje"}
    finally:
        con.close()


# ===================================================================================================================
# his calls
# ===================================================================================================================
def find_calls(p, c, now, infs, since=None, posts_only=False):
    """{inf id: {token: call}}: the first public signal per token (see the module text). call: {token, symbol, t0,
    handle, kind 'objava' | 'javna_kupnja', ref, url, mcap0, r1h, r24h}. Tokens whose market cap at the signal is
    known and under min_mcap are left out; at most kol_max_calls per influencer (posts first, newest first)."""
    since = int(since if since is not None else now - int(c["kol_days"]) * 86400)
    hmap = {}
    for e in infs:
        for h in e["handles"]:
            hmap[h.lower()] = e
        for t in e["telegram"]:
            hmap["tg:" + t.lower()] = e
    out = {e["id"]: {} for e in infs}
    if not hmap:
        return out

    def put(e, tok, ts, h, kind, ref, url, sym, mc0, r1h=None, r24h=None):
        cur = out[e["id"]].get(tok)
        if cur is None or ts < cur["t0"]:
            out[e["id"]][tok] = {"token": tok, "symbol": sym or (cur or {}).get("symbol"), "t0": int(ts), "handle": h,
                                 "kind": kind, "ref": ref, "url": url, "mcap0": mc0, "r1h": r1h, "r24h": r24h}
        elif sym and not cur.get("symbol"):
            cur["symbol"] = sym

    kinds = POSTS + (("buy",) if c.get("kol_public_buys") and not posts_only else ())
    kc = store.ro(p.get("kol_db"))
    for tok, h, kind, ts, tid, url, sym, mc0, r1h, r24h in store.q(
            kc, f"SELECT token, handle, kind, ts, tweet_id, url, symbol, mcap0, r1h, r24h FROM calls WHERE ts >= ? AND "
                f"ts <= ? AND kind IN ({_in(kinds)})", (since, int(now), *kinds)):
        e = hmap.get(str(h or "").lower())
        if e is None or len(tok or "") < 32 or not ts:
            continue
        if kind == "buy" and not e["public_buys"]:
            continue
        put(e, tok, ts, h, "javna_kupnja" if kind == "buy" else "objava", tid, url, sym, mc0, r1h, r24h)
    if kc is not None:
        kc.close()
    mc = store.ro(p.get("makroinf_db"))
    hs = sorted(h for h in hmap if not h.startswith("tg:"))
    if mc is not None and hs:
        try:
            from kol.collect import cas_in
        except Exception:  # noqa: BLE001
            cas_in = None
        for tid, h, ts, text, url in store.q(mc, f"SELECT id, handle, ts, text, url FROM tweets WHERE ts >= ? AND ts <= ? "
                                                 f"AND lower(handle) IN ({_in(hs)})", (since, int(now), *hs)):
            for ca in (cas_in(text) if cas_in and text else []):
                put(hmap[str(h).lower()], ca, ts, h, "objava", tid, url, None, None)
        mc.close()
    ic = store.ro(p.get("insajderi_db"))   # the optional X read's own posts (fetch_posts)
    for iid, h, tid, tok, ts, url, kind in store.q(ic, "SELECT inf, handle, tweet_id, token, ts, url, kind FROM ik_posts "
                                                       "WHERE ts >= ? AND ts <= ?", (since, int(now))):
        e = hmap.get(str(h or "").lower())
        if e is not None and e["id"] == iid and kind in POSTS:
            put(e, tok, ts, h, "objava", tid, url, None, None)
    if ic is not None:
        ic.close()
    floor = float(c["min_mcap"])
    for iid, d in out.items():
        keep = sorted((x for x in d.values() if x["mcap0"] is None or x["mcap0"] >= floor),
                      key=lambda x: (x["kind"] != "objava", -x["t0"]))   # his posts first, then the public buys
        out[iid] = {x["token"]: x for x in keep[:int(c["kol_max_calls"])]}
    return out


def save_calls(con, calls, now):
    for iid, d in calls.items():
        for x in d.values():
            cur = con.execute("SELECT t0 FROM ik_calls WHERE inf = ? AND token = ?", (iid, x["token"])).fetchone()
            if cur is None:
                con.execute("INSERT INTO ik_calls (inf, token, symbol, t0, handle, kind, ref, url, mcap0, seen_ts) VALUES "
                            "(?,?,?,?,?,?,?,?,?,?)", (iid, x["token"], x["symbol"], x["t0"], x["handle"], x["kind"],
                                                      x["ref"], x["url"], x["mcap0"], int(now)))
            elif cur[0] != x["t0"]:   # an earlier signal turned up: the window moved, so it is read again
                con.execute("UPDATE ik_calls SET t0 = ?, handle = ?, kind = ?, ref = ?, url = ?, fetched = 0 WHERE inf = ? "
                            "AND token = ?", (x["t0"], x["handle"], x["kind"], x["ref"], x["url"], iid, x["token"]))
    con.commit()


def fetch_posts(con, c, now, infs, get=None, log=print):
    """The OPTIONAL X read (see the module text): the newest posts of the seeded handles, one request each (about 20
    posts, ~$0.003), least recently read first, into ik_posts (only posts that name a token address). Returns
    {"state": "isključeno" | "nema ključa" | "nema kredita" | "strop" | "ok", "posts": n, "usd": x}. Never raises."""
    cap = float(c.get("kol_x_usd_day") or 0)
    if cap <= 0:
        return {"state": "isključeno", "posts": 0, "usd": 0.0}
    try:
        from kol import twapi
        from kol.collect import calls_from_tweet
    except Exception:  # noqa: BLE001
        return {"state": "nema ključa", "posts": 0, "usd": 0.0}
    if get is None and not twapi.key():
        return {"state": "nema ključa", "posts": 0, "usd": 0.0}
    if now < float(store.kv(con, "kolw_x_pause") or 0):
        return {"state": "nema kredita", "posts": 0, "usd": 0.0}
    get = get or twapi._get
    k_day = f"kolw_x_usd:{store.day(now)}"
    spent, usd, n, state = float(store.kv(con, k_day) or 0), 0.0, 0, "ok"
    todo = sorted(((float(store.kv(con, f"kolw_x:{h.lower()}") or 0), h, e["id"]) for e in infs for h in e["handles"]))
    for last, h, iid in todo[:int(c["kol_x_handles"])]:
        if now - last < float(c["kol_x_every_h"]) * 3600:
            continue
        if spent + usd >= cap:
            state = "strop"
            break
        from usage import xbudzet   # 27.11. (vlasnik): wallet <-> influencer linking is priority 1 of the X budget
        if not xbudzet.room("pozivi", twapi.cost(20), now):
            state = "strop"
            break
        try:
            d = get(f"from:{h} since_time:{int(max(last, now - int(c['kol_x_days']) * 86400))}", "")
        except Exception as e2:  # noqa: BLE001 - a refusal or an outage: this pass reads nothing more from X
            if getattr(e2, "code", None) == 402:
                state = "nema kredita"
                store.kv(con, "kolw_x_pause", int(now + float(c["kol_x_pause_h"]) * 3600))
            else:
                state = f"greška ({type(e2).__name__})"
            break
        tweets = (d or {}).get("tweets") or []
        cost = twapi.cost(len(tweets))
        usd += cost
        xbudzet.book("pozivi", cost, now, "insajderi")
        try:
            from usage import meter
            meter.record("twitterapi", "kol_insajderi", cost)
        except Exception:  # noqa: BLE001
            pass
        for t in tweets:
            for x in calls_from_tweet(t):
                if x.get("match", "ca") == "ca" and str(x.get("handle") or "").lower() == h.lower():
                    n += con.execute("INSERT OR IGNORE INTO ik_posts VALUES (?,?,?,?,?,?,?)",
                                     (iid, x["handle"], x["tweet_id"], x["token"], x["ts"], x.get("url"),
                                      x.get("kind") or "call")).rowcount
        store.kv(con, f"kolw_x:{h.lower()}", int(now))
    store.kv(con, k_day, round(spent + usd, 6))
    con.commit()
    return {"state": state, "posts": n, "usd": round(usd, 5)}


# ===================================================================================================================
# the trades around a call
# ===================================================================================================================
def bucket(lead_s):
    """How long before the call the last buy was: '<10 min' | '<24 h' | '<7 d'."""
    return "<10 min" if lead_s < 600 else "<24 h" if lead_s < 86400 else "<7 d"


def _row():
    return {"first_buy": None, "last_buy": None, "n_buys": 0, "sol_in": 0.0, "known_in": False, "pre_sell": None,
            "n_sells": 0, "n_sells60": 0, "first_sell": None, "sol_out": 0.0, "sol_out60": 0.0, "known_out": False,
            "front": 0, "sold": 0, "sold60": 0, "lead_s": None}


def around(trades, t0, c):
    """trades of one token [(wallet, ts, side, sol, payer, src)] -> {wallet: row} for a call at t0 (pure): the buys in
    [t0 - pre_days, t0), the sells in [t0, t0 + kol_post_s] (and those within kol_fast_s). front = bought before and
    its last trade before t0 is a buy (a wallet that sold again before the call did not front-run it); dust (a known
    SOL under min_sol on that side) does not count; the same trade from several sources counts once."""
    t0 = int(t0)
    lo, fast, post = t0 - int(c["pre_days"]) * 86400, t0 + int(c["kol_fast_s"]), t0 + int(c["kol_post_s"])
    seen, out = set(), {}
    for w, ts, side, sol, _payer, _src in sorted(trades, key=lambda x: x[1] or 0):
        if not w or ts is None or side not in ("buy", "sell"):
            continue
        k = (w, side, int(ts))
        if k in seen:
            continue
        seen.add(k)
        if lo <= ts < t0:
            o = out.setdefault(w, _row())
            if side == "sell":
                o["pre_sell"] = int(ts)
                continue
            if o["first_buy"] is None:
                o["first_buy"] = int(ts)
            o["last_buy"] = int(ts)
            o["n_buys"] += 1
            if sol is not None:
                o["sol_in"] += abs(sol)
                o["known_in"] = True
        elif side == "sell" and t0 <= ts <= post:
            o = out.setdefault(w, _row())
            o["n_sells"] += 1
            if o["first_sell"] is None:
                o["first_sell"] = int(ts)
            if ts <= fast:
                o["n_sells60"] += 1
            if sol is not None:
                o["sol_out"] += abs(sol)
                o["known_out"] = True
                if ts <= fast:
                    o["sol_out60"] += abs(sol)
    res = {}
    for w, o in out.items():
        small_in = o["known_in"] and o["sol_in"] < c["min_sol"]
        small_out = o["known_out"] and o["sol_out"] < c["min_sol"]
        held = o["last_buy"] is not None and (o["pre_sell"] is None or o["pre_sell"] < o["last_buy"])
        o["front"] = int(held and not small_in)
        o["sold"] = int(o["n_sells"] > 0 and not small_out)
        o["sold60"] = int(o["sold"] and o["n_sells60"] > 0)
        if o["front"]:
            o["lead_s"] = t0 - o["last_buy"]
        if o["front"] or o["sold"]:
            res[w] = o
    return res


# ===================================================================================================================
# transfers (the raw transactions the Helius reads return anyway)
# ===================================================================================================================
def _keys(tx):
    raw = ((tx.get("transaction") or {}).get("message") or {}).get("accountKeys") or []
    return [k.get("pubkey") if isinstance(k, dict) else k for k in raw], \
        {k.get("pubkey") for k in raw if isinstance(k, dict) and k.get("signer")}


def _sig(tx):
    return ((tx.get("transaction") or {}).get("signatures") or ["?"])[0]


def token_moves(tx, mint=None):
    """[(sig, ts, src, dst, tokens, mint)] of one raw transaction: a SIGNER whose balance of the mint fell without
    receiving SOL (under XFER_MAX_SOL: a swap pays, a transfer only costs the fee) and the owners whose balance rose.
    mint None: every mint of the transaction (wrapped SOL is not a token here). Pure."""
    from kol import groupdisc as gd
    meta = tx.get("meta") or {}
    if meta.get("err"):
        return []
    mints = [mint] if mint else sorted({b.get("mint") for side in ("preTokenBalances", "postTokenBalances")
                                        for b in meta.get(side) or [] if b.get("mint") and b.get("mint") != gd.WSOL})
    out = []
    for m in mints:
        trades, _payer, _signers = gd.owner_trades(tx, m)
        senders = [(o, amt) for o, side, amt, sol in trades if side == "sell" and sol < XFER_MAX_SOL]
        if not senders:
            continue
        delta = {}
        for sign, side in ((-1, "preTokenBalances"), (1, "postTokenBalances")):
            for b in meta.get(side) or []:
                if b.get("mint") != m or not b.get("owner"):
                    continue
                ui = b.get("uiTokenAmount") or {}
                try:
                    amt = int(ui.get("amount") or 0) / 10 ** int(ui.get("decimals") or 0)
                except (TypeError, ValueError):
                    continue
                delta[b["owner"]] = delta.get(b["owner"], 0.0) + sign * amt
        got = [(o, d) for o, d in delta.items() if d > 1e-9]
        for s, _amt in senders:
            for o, d in got:
                if o != s:
                    out.append((_sig(tx), int(tx.get("blockTime") or 0), s, o, round(d, 6), m))
    return out


def sol_moves(tx, min_sol=0.05):
    """[(sig, ts, src, dst, sol)] of a plain SOL transfer (a transaction that touches no token balance): the signer
    whose balance fell most and every account that gained at least min_sol. Pure."""
    meta = tx.get("meta") or {}
    if meta.get("err") or meta.get("preTokenBalances") or meta.get("postTokenBalances"):
        return []
    keys, signers = _keys(tx)
    pre, post = meta.get("preBalances") or [], meta.get("postBalances") or []
    if not keys or len(pre) != len(keys) or len(post) != len(keys):
        return []
    d = [(keys[i], (post[i] - pre[i]) / 1e9) for i in range(len(keys))]
    src = min((x for x in d if x[0] in (signers or {keys[0]})), key=lambda x: x[1], default=None)
    if src is None or src[1] > -min_sol:
        return []
    return [(_sig(tx), int(tx.get("blockTime") or 0), src[0], k, round(v, 6)) for k, v in d
            if v >= min_sol and k != src[0]]


def save_transfers(con, txs, c, mint=None, first_in_for=None):
    """Store the transfers of raw transactions. first_in_for: the wallet whose OLDEST page this is: its earliest
    inbound SOL transfer is marked first_in (its first funding)."""
    rows, first = [], None
    for tx in sorted(txs or [], key=lambda t: t.get("blockTime") or 0):
        for sig, ts, s, d, amt, m in token_moves(tx, mint):
            rows.append((sig, ts, "token", s, d, amt, m, 0))
        for sig, ts, s, d, sol in sol_moves(tx, float(c["kol_min_transfer_sol"])):
            fi = int(first_in_for is not None and d == first_in_for and first is None)
            if fi:
                first = sig
            rows.append((sig, ts, "sol", s, d, sol, "", fi))
    con.executemany("INSERT OR IGNORE INTO ik_transfers VALUES (?,?,?,?,?,?,?,?)", rows)
    return len(rows)


def load_transfers(con):
    keys = ("sig", "ts", "kind", "src", "dst", "amount", "mint", "first_in")
    return [dict(zip(keys, r)) for r in store.q(con, "SELECT sig, ts, kind, src, dst, amount, mint, first_in FROM "
                                                     "ik_transfers ORDER BY ts")]


# ===================================================================================================================
# ties and links
# ===================================================================================================================
def hub_set(transfers, relay, hub_min, extra=()):
    """Addresses that are never a link nor an intermediate: relayers, known exchange wallets (`extra`) and any address
    that sent to, or received from, more than hub_min different addresses (an exchange, a pool, a distributor)."""
    fan, fin = defaultdict(set), defaultdict(set)
    for t in transfers:
        fan[t["src"]].add(t["dst"])
        fin[t["dst"]].add(t["src"])
    return (set(relay) | set(extra) | {a for a, ds in fan.items() if len(ds) > int(hub_min)}
            | {a for a, ss in fin.items() if len(ss) > int(hub_min)})


def ties(transfers, public, hubs, sells, c, actors=None, checked=None):
    """(strong {a: {b: tie}}, weak [(wallet, public wallet, tie)]) from the stored transfers. Strong (undirected): a
    first funding between two non-hub addresses, any SOL or token transfer OUT of a public wallet (a token transfer
    whose receiver sold that token within kol_split_s is the split), a token transfer between two other wallets.
    Weak: a transfer INTO a public wallet. public: {address: status}; sells: {(wallet, mint): [ts]}.
    actors: the wallets we saw trade (a token "transfer" to anything else, a pool, ties nothing). checked: addresses
    whose own oldest page we hold; a funder that is neither checked (so it could still turn out to be an exchange),
    public nor an actor gives a tie with ok False: shown, but it merges nothing and proves nothing."""
    strong, weak = defaultdict(dict), []
    trusted = None if checked is None else set(checked) | set(public) | set(actors or ())

    def add(a, b, tie):
        if a in hubs or b in hubs or a == b:
            return
        tie["ok"] = trusted is None or tie["kind"] != "financiranje" or tie["src"] in trusted
        strong[a].setdefault(b, tie)
        strong[b].setdefault(a, tie)

    for t in transfers:
        s, d = t["src"], t["dst"]
        base = {"sig": t["sig"], "ts": t["ts"], "src": s, "dst": d, "amount": t["amount"], "mint": t["mint"] or None}
        if d in public and s not in public:
            weak.append((s, d, dict(base, kind="uplata_na_javni")))
            if not (t["kind"] == "sol" and t["first_in"]):
                continue   # only the public wallet's own first funder ties further
        if t["kind"] == "sol":
            if s in public:
                add(s, d, dict(base, kind="prijenos_sol"))
            elif t["first_in"]:
                add(s, d, dict(base, kind="financiranje"))
        elif actors is None or d in actors:
            split = any(0 <= ts - t["ts"] <= int(c["kol_split_s"]) for ts in sells.get((d, t["mint"]), ()))
            add(s, d, dict(base, kind="podjela_tokena" if (split and s in public) else "prijenos_tokena"))
    return strong, weak


def find_links(members, public, strong, weak, hops=2):
    """Links of a group to the public wallets: a path of at most `hops` strong ties from a public wallet to a member
    (never through a hub: ties() left those out), plus the weak inbound ones. public: {address: status}. A link to an
    "osporeno" wallet is kept but not strong. -> [link dict] (pure)."""
    members = set(members)
    out, seen = [], set()
    for pw, status in public.items():
        frontier, dist, via = [pw], {pw: 0}, {}
        for depth in range(1, int(hops) + 1):
            nxt = []
            for a in frontier:
                for b, tie in strong.get(a, {}).items():
                    if b in dist:
                        continue
                    dist[b] = depth
                    via[b] = (a, tie)
                    nxt.append(b)
            frontier = nxt
        for w in sorted(members & set(dist)):
            if w == pw or (pw, w) in seen:
                continue
            seen.add((pw, w))
            a, tie = via[w]
            path = [tie]
            if a != pw:
                path.insert(0, via[a][1])
            kind = tie["kind"]
            if dist[w] == 2:   # one funder of both = a shared source; else what left the public wallet first
                kind = ("zajednicki_izvor" if all(x["kind"] == "financiranje" for x in path) and path[0]["dst"] == pw
                        else path[0]["kind"])
            ok = all(x.get("ok", True) for x in path)
            out.append({"public": pw, "wallet": w, "kind": kind, "hops": dist[w], "via": a if a != pw else None,
                        "sigs": [x["sig"] for x in path], "ts": tie["ts"], "disputed": status not in ANCHOR,
                        "unchecked": not ok, "strong": status in ANCHOR and ok})
    for w, pw, tie in weak:
        if w in members and (pw, w) not in seen:
            seen.add((pw, w))
            out.append({"public": pw, "wallet": w, "kind": "uplata_na_javni", "hops": 1, "via": None,
                        "sigs": [tie["sig"]], "ts": tie["ts"], "disputed": public.get(pw) not in ANCHOR,
                        "strong": False})
    return out


def link_text(lk):
    """One Croatian sentence of a link (the page and the report)."""
    t = LINK_HR.get(lk["kind"], lk["kind"])
    if lk.get("via"):
        t += f" (preko {lk['via'][:4]}…{lk['via'][-4:]})"
    if lk.get("no_tx"):
        t += "; iz naših podataka o financiranju, bez transakcije za provjeru"
    if lk.get("disputed"):
        t += "; javni novčanik je osporen, veza se ne broji"
    elif lk.get("unchecked"):
        t += "; izvor sredstava još nije provjeren (mogla bi biti burza), veza se zasad ne broji"
    return t


def group_owners(own0, wallets, pairs):
    """{wallet: owner id}: chain.owners' groups merged further by our own ties (first funding, token transfers)."""
    from kol import together
    out = {}
    for comp in together.components([(w, own0.get(w, w)) for w in wallets] + list(pairs)):
        oid = min(comp)
        for w in comp:
            out[w] = oid
    return {w: out.get(w, w) for w in wallets}


# ===================================================================================================================
# scoring and classes
# ===================================================================================================================
def aggregate(calls, parts, owner_of):
    """{owner: {token: agg}} of one influencer: per call the group's front (any member bought before and held),
    the closest buy, sold within 24 h / 60 min, SOL in and out, the wallets. calls: {token: call}; parts: {token:
    {wallet: around row}}."""
    out = defaultdict(dict)
    for tok, call in calls.items():
        for w, o in (parts.get(tok) or {}).items():
            g = owner_of.get(w)
            if g is None:
                continue
            a = out[g].get(tok)
            if a is None:
                a = out[g][tok] = {"t0": call["t0"], "kind": call["kind"], "front": False, "first_buy": None,
                                   "last_buy": None, "sold": False,
                                   "sold60": False, "first_sell": None, "sol_in": 0.0, "sol_out": 0.0, "wallets": {}}
            a["wallets"][w] = o
            if o["front"]:
                a["front"] = True
                a["first_buy"] = o["first_buy"] if a["first_buy"] is None else min(a["first_buy"], o["first_buy"])
                a["last_buy"] = o["last_buy"] if a["last_buy"] is None else max(a["last_buy"], o["last_buy"])
                a["sol_in"] += o["sol_in"]
            if o["sold"]:
                a["sold"] = True
                a["sold60"] = a["sold60"] or bool(o["sold60"])
                a["first_sell"] = o["first_sell"] if a["first_sell"] is None else min(a["first_sell"], o["first_sell"])
                a["sol_out"] += o["sol_out"]
    return out


def stats_of(by_tok, order, n_w, u, c):
    """The numbers of one group for one influencer (pure). by_tok: aggregate()'s {token: agg}; order: his covered
    calls' (t0, token) oldest first; n_w: tokens of the whole universe the group front-ran; u: universe size."""
    front = sorted((a["t0"], tok) for tok, a in by_tok.items() if a["front"])
    n_front = len(front)
    hit = [tok for _t, tok in front if by_tok[tok]["sold"]]
    n_any = sum(1 for a in by_tok.values() if a["front"] or a["sold"])
    n_h = len(order)
    cut_t = order[int(n_h * 2 / 3)][0] if n_h >= 3 else None
    older = [t for t, _tok in front if cut_t is not None and t < cut_t]
    newer = [t for t, _tok in front if cut_t is not None and t >= cut_t]
    n_w = max(int(n_w or 0), n_front)
    lf, exp = score.lift(n_front, n_w, max(n_h, n_front), max(int(u or 0), n_h, 1)) if n_front else (None, 0)
    leads = [(by_tok[tok]["t0"] - by_tok[tok]["last_buy"]) / 60 for _t, tok in front]
    med = _med(leads)
    return {"n_front": n_front, "n_sold": len(hit), "n_sold60": sum(1 for tok in hit if by_tok[tok]["sold60"]),
            "n_posts": sum(1 for _t, tok in front if by_tok[tok].get("kind", "objava") == "objava"),
            "n_any": n_any, "share_sold": round(len(hit) / n_front, 3) if n_front else None,
            "lift": lf, "expected": exp, "exclusivity": round(n_front / n_w, 3) if n_front else None,
            "n_w": n_w, "n_h": n_h, "u": int(u or 0),
            "med_lead_min": round(med, 1) if med is not None else None,
            "buckets": {b: sum(1 for x in leads if bucket(x * 60) == b) for b in ("<10 min", "<24 h", "<7 d")},
            "sol_in": round(sum(by_tok[tok]["sol_in"] for _t, tok in front), 4),
            "sol_out": round(sum(by_tok[tok]["sol_out"] for tok in hit), 4),
            "n_older": len(older), "n_newer": len(newer),
            "oos": bool(n_front >= int(c["kol_confirm_calls"]) and len(older) >= int(c["kol_min_calls"])
                        and len(newer) >= 1),
            "first_ts": front[0][0] if front else None}


def klass(st, strong_link, c):
    """(class or None, why in Croatian) of one group for one influencer (pure): see the module text."""
    lift_ok = st["u"] >= int(c["kol_min_universe"]) and (st["lift"] or 0) >= float(c["kol_min_lift"])
    posts_ok = st["n_posts"] >= int(c["kol_min_calls"])   # buys of the public wallet alone never confirm
    stat = st["n_front"] >= int(c["kol_confirm_calls"]) and st["oos"] and lift_ok and posts_ok
    if stat or (strong_link and st["n_any"] >= int(c["kol_min_calls"])):
        if stat:
            why = (f"kupio prije {st['n_front']} njegovih poziva ({st['n_older']} u starijem dijelu, {st['n_newer']} u "
                   f"novijem), {st['lift']}× češće nego slučajno")
            if strong_link:
                why += "; uz to izravna veza s javnim novčanikom"
        else:
            why = f"izravna veza s javnim novčanikom i {st['n_any']} njegova poziva"
        return "potvrđen", why
    if st["n_front"] >= int(c["kol_min_calls"]) or strong_link:
        if strong_link and st["n_front"] < int(c["kol_min_calls"]):
            return "kandidat", "izravna veza s javnim novčanikom, ali premalo poziva"
        miss = []
        if st["n_front"] < int(c["kol_confirm_calls"]):
            miss.append(f"treba {c['kol_confirm_calls']} poziva")
        elif not st["oos"]:
            miss.append(f"nije potvrđeno na novijim pozivima ({st['n_older']} starijih, {st['n_newer']} novijih)")
        if not lift_ok:
            miss.append("premalo događaja za usporedbu sa slučajnošću" if st["u"] < int(c["kol_min_universe"])
                        else f"nije dovoljno iznad slučajnosti ({st['lift']}×)")
        if not posts_ok and not miss:
            miss.append(f"samo {st['n_posts']} od toga su objave (ostalo su kupnje javnog novčanika)")
        return "kandidat", f"kupio prije {st['n_front']} njegovih poziva" + ("; " + ", ".join(miss) if miss else "")
    return None, None


def excluded(owner, members, by_tok, n_w, u, c, bad, first_trade):
    """Why a group is out (a Croatian reason) or None: a relayer, a bot (score.bots), a sniper (most of its early buys
    within sniper_secs of the token's first trade), or it front-runs most of all events (buys everything)."""
    if str(owner).startswith("relayer:"):
        return "plaća naknade za mnogo drugih vlasnika"
    if set(members) & set(bad):
        return "bot (brzina tradeova, oznaka ili previše tradeova dnevno)"
    snipe = [a["first_buy"] - first_trade[tok] for tok, a in by_tok.items()
             if a["front"] and tok in first_trade and a["first_buy"] is not None]
    if len(snipe) >= 2 and sum(1 for x in snipe if 0 <= x <= c["sniper_secs"]) / len(snipe) >= c["sniper_share"]:
        return f"snajper (kupuje u prvih {c['sniper_secs']} s lansiranja)"
    if u >= 10 and n_w / u >= c["busy_events_share"]:
        return f"kupio rano u {n_w} od {u} događaja (kupuje sve)"
    return None


def _score(st, cls, strong_link):
    return round(st["n_front"] + (2 if strong_link else 0) + min(st["lift"] or 0, 10) / 5 + (st["share_sold"] or 0)
                 + (3 if cls == "potvrđen" else 0), 2)


# ===================================================================================================================
# the analysis of a pass
# ===================================================================================================================
def _exchanges(p):
    try:
        from holderi import burze
        return set(burze.registry(wallet_db=p.get("wallet_db")))
    except Exception:  # noqa: BLE001
        return set()


def _evidence(con, calls, by_tok, members, limit=20):
    """The evidence a person can check: per call the token, the signal (time, kind, link), each wallet's buy and
    sell times and SOL, and the transactions we hold for them (i2_trades signatures)."""
    out = []
    ms = sorted(members)
    for tok, a in sorted(by_tok.items(), key=lambda kv: -kv[1]["t0"])[:limit]:
        call = calls[tok]
        sigs = defaultdict(list)
        for ch in _chunks(ms, 300):
            for w, sig, ts, side, sol in store.q(con, f"SELECT wallet, sig, ts, side, sol FROM i2_trades WHERE mint = ? AND "
                                                      f"ts >= ? AND ts <= ? AND wallet IN ({_in(ch)}) ORDER BY ts",
                                                 (tok, a["t0"] - 8 * 86400, a["t0"] + 2 * 86400, *ch)):
                if len(sigs[w]) < 6:
                    sigs[w].append({"sig": sig, "ts": ts, "side": side, "sol": sol})
        out.append({"token": tok, "symbol": call.get("symbol"), "t0": a["t0"], "kind": call["kind"],
                    "handle": call.get("handle"), "url": call.get("url"), "front": a["front"], "sold": a["sold"],
                    "sold60": a["sold60"],
                    "wallets": [{"wallet": w, "first_buy": o["first_buy"], "last_buy": o["last_buy"],
                                 "bucket": bucket(o["lead_s"]) if o["lead_s"] is not None else None,
                                 "sol_in": round(o["sol_in"], 4) if o["known_in"] else None,
                                 "first_sell": o["first_sell"], "n_sells": o["n_sells"],
                                 "sol_out": round(o["sol_out"], 4) if o["known_out"] else None,
                                 "tx": sigs.get(w, [])} for w, o in sorted(a["wallets"].items())]})
    return out


def analyze(con, p, c, now, infs, calls, deadline=None):
    """Participants of every call from the stored trades, owners, links, classes -> ik_wallets, ik_status. Returns the
    counts, or None when the time bound cut it (nothing stored: the last full result stays)."""
    public = {w["address"]: w["status"] for e in infs for w in e["wallets"]}
    pub_of = {e["id"]: {w["address"]: w["status"] for w in e["wallets"]} for e in infs}
    transfers = load_transfers(con)
    known = {t["src"] for t in transfers} | {t["dst"] for t in transfers} | set(public)
    by_tok = defaultdict(list)
    for iid, d in calls.items():
        for tok in d:
            by_tok[tok].append(iid)
    parts, covered, sells = defaultdict(dict), set(), defaultdict(list)
    for ch in _chunks(sorted(by_tok), 100):
        if deadline is not None and time.monotonic() > deadline:
            return None
        src = chain.sources(con, p, ch)
        for tok in ch:
            trades = src.get(tok) or []
            for iid in by_tok[tok]:
                t0 = calls[iid][tok]["t0"]
                rows = around(trades, t0, c)
                if any(x[1] is not None and t0 - int(c["pre_days"]) * 86400 <= x[1] <= t0 + int(c["kol_post_s"])
                       for x in trades):
                    covered.add((iid, tok))   # we hold trades of this token around the call
                # a public wallet is never its own "secondary" wallet; a seller without a buy counts only when a
                # transfer we know of could have given it the tokens
                parts[iid][tok] = {w: o for w, o in rows.items() if w not in public and (o["front"] or w in known)}
                for w, o in parts[iid][tok].items():
                    if o["first_sell"]:
                        sells[(w, tok)].append(o["first_sell"])
    wallets = {w for d in parts.values() for rows in d.values() for w in rows} | set(public)
    own0, relay = chain.owners(con, p, c, wallets, set(by_tok))
    exch = _exchanges(p)
    hubs = hub_set(transfers, relay, c["hub_min"], exch) - set(public)
    checked = {k[len("kolw:fund:"):] for (k,) in store.q(con, "SELECT key FROM i2_fetch WHERE key LIKE 'kolw:fund:%'")}
    strong, weak = ties(transfers, public, hubs, sells, c, actors=wallets, checked=checked)
    live = wallets - set(relay)
    owner_of = group_owners(own0, live, [(a, b) for a, bs in strong.items() for b, tie in bs.items() if tie["ok"]])
    try:   # the funders our databases already hold (what chain.owners merged by): the evidence of "one owner"
        from kol import groupdisc as gd
        fund = gd._funders(p, set(by_tok), live)
    except Exception:  # noqa: BLE001
        fund = {}
    members_of = defaultdict(set)
    for w, g in owner_of.items():
        members_of[g].add(w)
    # the universe of events (ours + Insajderi 2.0's): how often a group front-runs anything
    uni, front_all = set(), defaultdict(set)
    for tok, w in store.q(con, "SELECT e.token, p.wallet FROM i2_part p JOIN i2_events e ON e.eid = p.eid WHERE "
                               "p.bought_before = 1"):
        g = owner_of.get(w)
        if g is not None:
            front_all[g].add(tok)
    uni |= {t for (t,) in store.q(con, "SELECT DISTINCT token FROM i2_events WHERE n_part > 0")}
    for iid, d in parts.items():
        for tok, rows in d.items():
            if (iid, tok) in covered:
                uni.add(tok)
            for w, o in rows.items():
                if o["front"] and w in owner_of:
                    front_all[owner_of[w]].add(tok)
    u = len(uni)
    aggs = {iid: aggregate(calls[iid], parts[iid], owner_of) for iid in calls}
    cand = {w for iid, ag in aggs.items() for g, bt in ag.items()
            if sum(1 for a in bt.values() if a["front"]) >= 2 or members_of[g] & known for w in members_of[g]}
    bad = score.bots(con, p, c, cand - set(public), now - int(c["kol_days"]) * 86400) if cand else set()
    for (ms,) in store.q(con, "SELECT members FROM i2_groups WHERE cls IN ('bot_snajper', 'relayer')"):
        try:
            bad |= set(json.loads(ms or "[]")) & cand
        except ValueError:
            pass
    bad -= set(public)
    ft = score.first_trades(p, set(by_tok))
    old = {(i, o): ts for i, o, ts in store.q(con, "SELECT inf, owner, confirmed_ts FROM ik_wallets")}
    res = {"listed": 0, "confirmed": 0, "linked": 0, "excluded": 0, "universe": u, "with_calls": 0, "calls": 0,
           "covered": 0}
    for n, e in enumerate(infs):
        iid = e["id"]
        mine = calls.get(iid) or {}
        order = sorted((x["t0"], tok) for tok, x in mine.items() if (iid, tok) in covered)
        rows = []
        for g, bt in aggs.get(iid, {}).items():
            members = sorted(members_of[g] - set(public))
            if not members:
                continue
            st = stats_of(bt, order, len(front_all.get(g, ())), u, c)
            links = find_links(members, pub_of[iid], strong, weak, c["kol_hops"])
            for pw in sorted(members_of[g] & set(pub_of[iid])):   # one owner by the funding data we already held
                if any(lk["public"] == pw and lk["kind"] != "uplata_na_javni" for lk in links):
                    continue
                anchor = pub_of[iid][pw] in ANCHOR
                direct = next((m for m in members if pw in fund.get(m, ()) or m in fund.get(pw, ())), None)
                shared = next(((m, f) for m in members for f in sorted(set(fund.get(m, ())) & set(fund.get(pw, ())))
                               if f not in hubs and f not in exch), None)
                lk = {"public": pw, "hops": None, "via": None, "sigs": [], "ts": None, "disputed": not anchor,
                      "no_tx": True}
                if direct:      # the public wallet funded it (or the other way round)
                    lk.update(wallet=direct, kind="financiranje", hops=1, strong=anchor)
                elif shared:    # both were first funded by the same non-exchange address
                    lk.update(wallet=shared[0], kind="zajednicki_izvor", hops=2, via=shared[1], strong=anchor)
                else:           # merged by a fee payer or an owner group: no funder we can show, so it proves nothing
                    lk.update(wallet=members[0], kind="isti_vlasnik", strong=False)
                links.append(lk)
            strong_link = any(lk["strong"] for lk in links)
            if st["n_front"] < int(c["kol_min_calls"]) and not strong_link:
                continue
            why_out = excluded(g, members, bt, st["n_w"], u, c, bad, ft)
            if why_out:
                res["excluded"] += 1
                continue
            cls, why = klass(st, strong_link, c)
            if cls is None:
                continue
            rows.append((g, members, cls, why, st, links, strong_link, bt))
        rows.sort(key=lambda r: -_score(r[4], r[2], r[6]))
        rows = rows[:int(c["kol_max_listed"])]
        con.execute("DELETE FROM ik_wallets WHERE inf = ?", (iid,))
        for g, members, cls, why, st, links, strong_link, bt in rows:
            cts = (old.get((iid, g)) or int(now)) if cls == "potvrđen" else None
            for lk in links:
                lk["text"] = link_text(lk)
            con.execute("INSERT INTO ik_wallets VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (iid, g, json.dumps(members), cls, why, st["n_front"], st["n_sold"], st["n_sold60"], st["n_any"],
                         st["share_sold"], st["lift"], st["exclusivity"], st["med_lead_min"], st["sol_in"],
                         st["sol_out"], int(strong_link), json.dumps(links, ensure_ascii=False),
                         json.dumps({"calls": _evidence(con, mine, bt, members), "buckets": st["buckets"],
                                     "expected": st["expected"], "n_w": st["n_w"], "n_h": st["n_h"], "u": st["u"],
                                     "n_older": st["n_older"], "n_newer": st["n_newer"]}, ensure_ascii=False),
                         _score(st, cls, strong_link), st["first_ts"], cts, int(now)))
        n_conf = sum(1 for r in rows if r[2] == "potvrđen")
        status = "bez_handlea" if not (e["handles"] or e["telegram"]) else "pratimo" if mine else "nema_poziva"
        con.execute("INSERT OR REPLACE INTO ik_status VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                    (iid, e["name"], json.dumps(e["handles"] + ["tg:" + t for t in e["telegram"]]),
                     json.dumps(e["wallets"], ensure_ascii=False), status, len(mine), len(order), len(rows), n_conf,
                     e.get("note"), n, int(now)))
        for tok, x in mine.items():
            con.execute("UPDATE ik_calls SET covered = ?, n_front = ? WHERE inf = ? AND token = ?",
                        (int((iid, tok) in covered), sum(1 for o in parts[iid].get(tok, {}).values() if o["front"]),
                         iid, tok))
        res["listed"] += len(rows)
        res["confirmed"] += n_conf
        res["linked"] += sum(1 for r in rows if r[6])
        res["with_calls"] += int(bool(mine))
        res["calls"] += len(mine)
        res["covered"] += len(order)
    con.execute(f"DELETE FROM ik_status WHERE inf NOT IN ({_in(infs)})" if infs else "DELETE FROM ik_status",
                [e["id"] for e in infs])
    con.execute(f"DELETE FROM ik_wallets WHERE inf NOT IN ({_in(infs)})" if infs else "DELETE FROM ik_wallets",
                [e["id"] for e in infs])
    con.commit()
    return res


# ===================================================================================================================
# Helius (inside the day cap, its own small share)
# ===================================================================================================================
class _Tap:
    """A fetch that keeps the raw transactions it returned (their transfers are free once the page is paid)."""

    def __init__(self, fetch=None):
        self.fetch, self.txs = fetch, []

    def __call__(self, address, **kw):
        fn = self.fetch
        if fn is None:
            from wallets import rpc
            fn = rpc.fetch
        txs, complete = fn(address, **kw)
        self.txs += list(txs or [])
        return txs, complete


def _spent_today(con, now):
    return int(float(store.kv(con, f"kolw_helius:{store.day(now)}") or 0))


def budget(con, p, c, now, credits=None):
    """Credits this pass may spend: what is left of the tool's day cap, of our own day share of it (kol_helius_share)
    and of the pass's own cap (kol_pass_credits); `credits` (the caller's --credits) only lowers it."""
    cap, _how = store.helius_cap(c, now, p.get("usage_db"))
    b = min(store.helius_left(con, c, now, p.get("usage_db")),
            int(cap * float(c["kol_helius_share"])) - _spent_today(con, now), int(c["kol_pass_credits"]))
    if credits is not None:
        b = min(b, int(credits))
    return max(0, b)


def reserve(con, p, c, now):
    """Credits the night pass of Insajderi 2.0 (which otherwise takes all that is left of the day cap) leaves for this
    pass: ~90 a post still to be read, at most what is left of our day share and of one pass. 0 when nothing waits."""
    try:
        ensure(con)
        n = store.q(con, "SELECT COUNT(*) FROM ik_calls WHERE fetched = 0 AND kind = 'objava' AND t0 >= ?",
                    (int(now) - int(c["kol_days"]) * 86400,))[0][0]
        cap, _how = store.helius_cap(c, now, p.get("usage_db"))
        return max(0, min(n * 90, int(cap * float(c["kol_helius_share"])) - _spent_today(con, now),
                          int(c["kol_pass_credits"])))
    except Exception:  # noqa: BLE001
        return 0


def _charge(con, now, n):
    if n > 0:
        store.add_spent(con, now, n)
        store.kv(con, f"kolw_helius:{store.day(now)}", _spent_today(con, now) + int(n))
        con.commit()


def fetch_calls(con, p, c, calls, now, left, fetch=None, log=print, deadline=None):
    """Helius for the calls not read yet (chain.fetch_event: the hour after the call, the 6 h before, the sellers'
    token accounts 7 days back), newest first, within `left` credits: his POSTS only (kol_helius_public_buys adds the
    public wallet's buys, after the posts). A call whose token an Insajderi 2.0 event already read at the same time
    costs nothing. -> (calls read, credits)."""
    cc = dict(c, sell_pages=int(c["kol_sell_pages"]), pre_pages=int(c["kol_pre_pages"]),
              lookups_per_event=int(c["kol_lookups"]))
    done = {(i, t) for i, t in store.q(con, "SELECT inf, token FROM ik_calls WHERE fetched > 0")}
    todo = sorted((x for iid, d in calls.items() for x in ({**v, "inf": iid} for v in d.values())
                   if (x["inf"], x["token"]) not in done and x["t0"] + int(c["kol_fast_s"]) <= now
                   and (x["kind"] == "objava" or c.get("kol_helius_public_buys"))),
                  key=lambda x: (x["kind"] != "objava", -x["t0"]))
    spent, n = 0, 0
    for x in todo:
        if left - spent < 10 or (deadline is not None and time.monotonic() > deadline):
            break
        tok, t0 = x["token"], x["t0"]
        if store.q(con, "SELECT 1 FROM i2_events WHERE token = ? AND fetched = 1 AND ABS(t0 - ?) <= 600", (tok, t0)):
            con.execute("UPDATE ik_calls SET fetched = 2 WHERE inf = ? AND token = ?", (x["inf"], tok))
            con.commit()
            continue
        e = {"eid": f"k:{tok}:{t0}", "token": tok, "t0": t0, "win_end": t0 + int(c["kol_fast_s"]),
             "callers": {x["handle"] or x["inf"]: t0}}
        tap = _Tap(fetch)
        got = chain.fetch_event(con, p, cc, e, now, left - spent, fetch=tap, log=log)
        _charge(con, now, got)
        spent += got
        save_transfers(con, tap.txs, c, mint=tok)
        keys = [f"mint:{s}:{e['eid']}" for s, pages in (("sell", cc["sell_pages"]), ("pre", cc["pre_pages"])) if pages > 0]
        if all(store.q(con, "SELECT 1 FROM i2_fetch WHERE key = ?", (k,)) for k in keys):
            con.execute("UPDATE ik_calls SET fetched = 1 WHERE inf = ? AND token = ?", (x["inf"], tok))
            n += 1
        con.commit()
    return n, spent


def fetch_funding(con, p, c, now, left, fetch=None, log=print, deadline=None):
    """The OLDEST page of a wallet's history (10 credits, once): its first funding, for the public wallets and the
    listed groups' wallets, then their funders (the second hop); at most kol_fund_lookups a pass. -> (wallets, credits)."""
    pub = []   # only of influencers that have a group to link: no calls in the data = no credit spent
    for (js,) in store.q(con, "SELECT public FROM ik_status WHERE n_listed > 0 ORDER BY ord"):
        try:
            pub += [w["address"] for w in json.loads(js or "[]") if w.get("status") in ANCHOR]
        except (ValueError, TypeError, AttributeError):
            pass
    cand = []
    for (ms,) in store.q(con, "SELECT members FROM ik_wallets ORDER BY score DESC"):
        try:
            cand += json.loads(ms or "[]")[:4]
        except ValueError:
            pass
    hop2 = [s for (s,) in store.q(con, "SELECT src FROM ik_transfers WHERE kind = 'sol' AND first_in = 1")]
    seen, todo = set(_exchanges(p)), []   # an exchange's own history says nothing about who it paid
    for w in cand + pub + hop2:
        if w not in seen and not store.q(con, "SELECT 1 FROM i2_fetch WHERE key = ?", (f"kolw:fund:{w}",)):
            todo.append(w)
        seen.add(w)
    spent, n = 0, 0
    for w in todo[:int(c["kol_fund_lookups"])]:
        if left - spent < 10 or (deadline is not None and time.monotonic() > deadline):
            break
        got = [0]
        tap = _Tap(fetch)
        try:
            txs, complete = tap(w, max_pages=1, oldest_first=True, on_credits=lambda k: got.__setitem__(0, got[0] + k))
        except Exception as e2:  # noqa: BLE001 - one wallet fails, the pass goes on
            log(f"{PREFIX}{w[:6]}… Helius {type(e2).__name__}: {str(e2)[:80]}")
            continue
        _charge(con, now, got[0])
        spent += got[0]
        save_transfers(con, txs, c, first_in_for=w)
        con.execute("INSERT OR REPLACE INTO i2_fetch VALUES (?,?,?,?,?)",
                    (f"kolw:fund:{w}", int(now), got[0], len(txs or []), int(bool(complete))))
        con.commit()
        n += 1
    return n, spent


# ===================================================================================================================
# live measurement (shadow): a confirmed group's buy before his call
# ===================================================================================================================
def _wallet_trades(con, p, wallets, since, side):
    """[(wallet, mint, ts, sol)] of `wallets` since `since` from the trades we already store (our Helius rows, the
    scored wallets' histories, the webhook)."""
    out = []
    ws = sorted(wallets)
    wc, hc = store.ro(p.get("wallet_db")), store.ro(p.get("hype_db"))
    for ch in _chunks(ws, 300):
        out += store.q(con, f"SELECT wallet, mint, ts, sol FROM i2_trades WHERE side = ? AND ts >= ? AND wallet IN "
                            f"({_in(ch)})", (side, int(since), *ch))
        out += store.q(wc, f"SELECT wallet, mint, ts, ABS(sol) FROM wallet_trades WHERE kind = ? AND ts >= ? AND wallet "
                           f"IN ({_in(ch)})", (side, int(since), *ch))
        out += store.q(hc, f"SELECT wallet, mint, ts, sol FROM chain_trades WHERE side = ? AND ts >= ? AND wallet IN "
                           f"({_in(ch)})", (side, int(since), *ch))
    for x in (wc, hc):
        if x is not None:
            x.close()
    return out


def predpoziv(con, p, c, now, infs):
    """Record and settle the "predpoziv" events (see the module text). Nothing while the flag is off. -> stats."""
    if mode() == "off":
        return None
    groups = {}
    for iid, g, ms in store.q(con, "SELECT inf, owner, members FROM ik_wallets WHERE cls = 'potvrđen'"):
        try:
            for w in json.loads(ms or "[]"):
                groups[w] = (iid, g)
        except ValueError:
            continue
    posts = find_calls(p, c, now, infs, since=now - (int(c["kol_pred_days"]) + int(c["kol_pred_call_days"]) + 30) * 86400,
                       posts_only=True)
    if groups:
        first = {}
        for w, mint, ts, sol in _wallet_trades(con, p, groups, now - int(c["kol_pred_days"]) * 86400, "buy"):
            k = (groups[w][0], mint)
            if k not in first or ts < first[k][0]:
                first[k] = (int(ts), w, sol)
        for (iid, mint), (ts, w, sol) in first.items():
            call = posts.get(iid, {}).get(mint)
            if call is not None and call["t0"] <= ts:
                continue   # he had already posted it: not a buy before the call
            con.execute("INSERT OR IGNORE INTO ik_predpoziv (inf, token, symbol, owner, wallet, buy_ts, sol, seen_ts) "
                        "VALUES (?,?,?,?,?,?,?,?)", (iid, mint, (call or {}).get("symbol"), groups[w][1], w, ts, sol,
                                                     int(now)))
    members = defaultdict(set)
    for w, (iid, g) in groups.items():
        members[(iid, g)].add(w)
    for iid, tok, g, buy_ts, called, call_ts in store.q(
            con, "SELECT inf, token, owner, buy_ts, called, call_ts FROM ik_predpoziv WHERE closed = 0"):
        call = posts.get(iid, {}).get(tok)
        if call is not None and call["t0"] > buy_ts:
            sold = [ts for _w, m, ts, _s in _wallet_trades(con, p, members.get((iid, g), ()), call["t0"], "sell")
                    if m == tok]
            con.execute("UPDATE ik_predpoziv SET called = 1, call_ts = ?, call_ref = ?, symbol = COALESCE(symbol, ?), "
                        "r1h = ?, r24h = ?, sold_ts = ?, closed = ? WHERE inf = ? AND token = ?",
                        (call["t0"], call.get("url") or call.get("ref"), call.get("symbol"), call.get("r1h"),
                         call.get("r24h"), min(sold) if sold else None,
                         int(now - call["t0"] > 2 * 86400), iid, tok))
        elif now - buy_ts > int(c["kol_pred_call_days"]) * 86400:
            con.execute("UPDATE ik_predpoziv SET called = 0, closed = 1 WHERE inf = ? AND token = ?", (iid, tok))
    con.commit()
    return pred_stats(con)


def pred_stats(con):
    """{n, settled, called, hit_pct, med_lead_min, sold_after, r1h_med_pct} of the predpoziv events; settled = he
    called it, or the waiting time ran out."""
    rows = store.q(con, "SELECT called, buy_ts, call_ts, r1h, sold_ts, closed FROM ik_predpoziv")
    done = [r for r in rows if r[0] == 1 or r[5]]
    hit = [r for r in done if r[0] == 1]
    lead = _med([(r[2] - r[1]) / 60 for r in hit if r[2]])
    r1 = _med([r[3] for r in hit])
    return {"n": len(rows), "settled": len(done), "called": len(hit),
            "hit_pct": round(100 * len(hit) / len(done), 1) if done else None,
            "med_lead_min": round(lead, 1) if lead is not None else None,
            "sold_after": sum(1 for r in hit if r[4]), "r1h_med_pct": round(r1 * 100, 1) if r1 is not None else None}


# ===================================================================================================================
# the pass
# ===================================================================================================================
def run_pass(con, p, c, now, kind="incr", fetch=None, credits=None, log=print, seed=None, x_get=None, left_s=None):
    """One bounded pass inside run_insajderi (once / night / incr). Never raises: a failure is one log line and the
    last stored result stays. Returns the summary (also i2_kv 'kolw_summary'). left_s (19.11.): the seconds the whole
    insajderi pass has left (store.Clock): its own bound kol_max_s / kol_incr_s never goes past it."""
    t = time.monotonic()
    try:
        ensure(con)
        deadline = t + min(float(c["kol_incr_s"] if kind == "incr" else c["kol_max_s"]),
                           float("inf") if left_s is None else max(0.0, float(left_s)))
        infs = load_seed(seed, con, p.get("kol_db"))
        try:
            xs = fetch_posts(con, c, now, infs, get=x_get, log=log)
        except Exception as e2:  # noqa: BLE001 - the optional read never costs the pass
            xs = {"state": f"greška ({type(e2).__name__})", "posts": 0, "usd": 0.0}
        calls = find_calls(p, c, now, infs)
        save_calls(con, calls, now)
        b = budget(con, p, c, now, credits)
        n_f, spent = fetch_calls(con, p, c, calls, now, b, fetch=fetch, log=log, deadline=deadline) if b >= 10 else (0, 0)
        res = analyze(con, p, c, now, infs, calls, deadline)
        if res is not None and b - spent >= 10:
            n_w, got = fetch_funding(con, p, c, now, b - spent, fetch=fetch, log=log, deadline=deadline)
            spent += got
            if n_w:   # the new ties may merge groups and add links
                res = analyze(con, p, c, now, infs, calls, deadline) or res
        prev = summary_of(con)
        s = {"ts": int(now), "kind": kind, "influencers": len(infs),
             "with_handle": sum(1 for e in infs if e["handles"] or e["telegram"]),
             "helius": int(spent), "helius_today": _spent_today(con, now), "budget": int(b), "calls_read": n_f,
             "truncated": res is None, "flag": mode(), "x": xs, "secs": round(time.monotonic() - t, 1)}
        s.update(res if res is not None else {k: prev.get(k, 0) for k in ("listed", "confirmed", "linked", "excluded",
                                                                           "universe", "with_calls", "calls",
                                                                           "covered")})
        try:
            s["pred"] = predpoziv(con, p, c, now, infs)
        except Exception as e2:  # noqa: BLE001 - the measurement never costs the analysis
            log(f"{PREFIX}predpoziv ({type(e2).__name__}: {e2})")
        store.kv(con, "kolw_summary", json.dumps(s, ensure_ascii=False))
        con.commit()
        log(line(s))
        return s
    except Exception as e:  # noqa: BLE001 - never into the caller (the Insajderi 2.0 pass goes on)
        try:
            con.rollback()
        except Exception:  # noqa: BLE001
            pass
        log(f"{PREFIX}prolaz nije uspio ({type(e).__name__}: {str(e)[:160]}); zadnji rezultat ostaje")
        return {}


def summary_of(con):
    try:
        return json.loads(store.kv(con, "kolw_summary") or "{}")
    except (ValueError, TypeError):
        return {}


def summary(path=None):
    con = store.ro(path or store.db_path())
    rows = store.q(con, "SELECT value FROM i2_kv WHERE key = 'kolw_summary'")
    if con is not None:
        con.close()
    try:
        return json.loads(rows[0][0]) if rows else {}
    except (ValueError, TypeError):
        return {}


def line(s):
    """The pass's one log line."""
    if not s:
        return PREFIX + "još nema prolaza"
    out = (f"{PREFIX}influencera s pozivima u podacima {s.get('with_calls', 0)} od {s.get('influencers', 0)} (s potvrđenim "
           f"handleom {s.get('with_handle', 0)}; poziva {s.get('calls', 0)}, s tradeovima {s.get('covered', 0)}), grupa "
           f"{s.get('listed', 0)}, potvrđenih {s.get('confirmed', 0)}, s izravnom vezom {s.get('linked', 0)}, isključeno "
           f"botova {s.get('excluded', 0)}; Helius {s.get('helius', 0):,} kr. (danas {s.get('helius_today', 0):,}, "
           f"prolaz smije {s.get('budget', 0):,})")
    x = s.get("x") or {}
    if x.get("state") == "ok":
        out += f"; X dohvat: {x.get('posts', 0)} novih objava s adresom ({x.get('usd', 0):.4f} $)"
    elif x.get("state"):
        out += f"; X dohvat: {x['state']}"
    if s.get("truncated"):
        out += "; analiza prekinuta na vremenskoj granici, vrijede zadnji rezultati"
    pr = s.get("pred")
    if pr and pr.get("n"):
        out += (f"; predpoziv: {pr['n']} događaja, zaključeno {pr['settled']}, pogodak "
                f"{pr['hit_pct'] if pr['hit_pct'] is not None else '—'} %, medijan vodstva "
                f"{pr['med_lead_min'] if pr['med_lead_min'] is not None else '—'} min")
    return out


# ===================================================================================================================
# views (the owner's page, the MCP read tool, the report)
# ===================================================================================================================
def view(path=None, evidence=True, inf=None, limit=None):
    """[{id, name, handles, status, status_hr, public, n_calls, n_covered, note, wallets: [group]}] in the seed's
    order (read-only). inf: one influencer by id or handle."""
    con = store.ro(path or store.db_path())
    keys = ("id", "name", "handles", "public", "status", "n_calls", "n_covered", "n_listed", "n_confirmed", "note")
    out = []
    want = str(inf or "").lstrip("@").lower()
    for r in store.q(con, "SELECT inf, name, handles, public, status, n_calls, n_covered, n_listed, n_confirmed, note "
                          "FROM ik_status ORDER BY ord"):
        d = dict(zip(keys, r))
        for k in ("handles", "public"):
            try:
                d[k] = json.loads(d[k] or "[]")
            except ValueError:
                d[k] = []
        if want and want != d["id"] and want not in [h.lower() for h in d["handles"]]:
            continue
        d["status_hr"] = STATUS_HR.get(d["status"], d["status"])
        d["wallets"] = []
        gk = ("owner", "members", "cls", "why", "n_front", "n_sold", "n_sold60", "n_any", "share_sold", "lift",
              "exclusivity", "med_lead_min", "sol_in", "sol_out", "link", "links", "evidence", "score", "first_ts",
              "confirmed_ts")
        for g in store.q(con, "SELECT owner, members, cls, why, n_front, n_sold, n_sold60, n_any, share_sold, lift, "
                              "exclusivity, med_lead_min, sol_in, sol_out, link, links, evidence, score, first_ts, "
                              "confirmed_ts FROM ik_wallets WHERE inf = ? ORDER BY (cls != 'potvrđen'), score DESC",
                         (d["id"],)):
            x = dict(zip(gk, g))
            for k, empty in (("members", []), ("links", []), ("evidence", {})):
                try:
                    x[k] = json.loads(x[k] or "null") or empty
                except ValueError:
                    x[k] = empty
            if not evidence:
                x.pop("evidence")
            d["wallets"].append(x)
        if limit:
            d["wallets"] = d["wallets"][:int(limit)]
        out.append(d)
    if con is not None:
        con.close()
    return out


def proposals(path=None, limit=50):
    con = store.ro(path or store.db_path())
    rows = store.q(con, "SELECT inf, name, handle, address, source, status, who, ts FROM ik_seed_dodano ORDER BY ts DESC "
                        "LIMIT ?", (int(limit),))
    if con is not None:
        con.close()
    return [dict(zip(("influencer", "name", "handle", "address", "source", "status", "who", "ts"), r)) for r in rows]


def pred_rows(path=None, limit=30):
    con = store.ro(path or store.db_path())
    keys = ("inf", "token", "symbol", "owner", "wallet", "buy_ts", "sol", "called", "call_ts", "call_ref", "r1h", "r24h",
            "sold_ts", "closed")
    rows = [dict(zip(keys, r)) for r in store.q(
        con, "SELECT inf, token, symbol, owner, wallet, buy_ts, sol, called, call_ts, call_ref, r1h, r24h, sold_ts, closed "
             "FROM ik_predpoziv ORDER BY buy_ts DESC LIMIT ?", (int(limit),))]
    st = pred_stats(con) if con is not None else None
    if con is not None:
        con.close()
    return rows, st


def mcp(args=None):
    """MCP get_kol_insider_wallets (read-only): per seeded influencer the status, his public wallets and the probably
    linked wallet groups with their numbers, links and evidence. influencer: id or handle; limit 1-50 groups each;
    evidence: the per-call evidence (default: only when one influencer is asked for)."""
    a = args or {}
    try:
        lim = max(1, min(50, int(a.get("limit") or 10)))
    except (TypeError, ValueError):
        lim = 10
    ev = a["evidence"] is True if "evidence" in a else bool(a.get("influencer"))   # the whole list: numbers only
    rows = view(evidence=ev, inf=a.get("influencer"), limit=lim)
    s = summary()
    if not rows and not s:
        return {"available": False, "note": "prvi prolaz još nije odrađen (nakon deploya ~10 min, zatim svaka 3 h i noću)"}
    pr, st = pred_rows(limit=20)
    return {"available": True, "caveat": CAVEAT, "summary": s, "influencers": rows,
            "predpoziv": {"flag": mode(), "stats": st, "events": pr},
            "proposals": proposals(limit=20),
            "classes": {"potvrđen": "kupio prije >= 3 njegova poziva, potvrđeno na novijoj trećini i iznad slučajnosti, "
                                    "ili izravna veza s javnim novčanikom uz >= 2 poziva",
                        "kandidat": "2 poziva ili sama izravna veza"},
            "real_money": "nikad iz ovog alata (samo mjerenje); ništa od ovoga ne ide na javne stranice"}


def _sh(w):
    return (w or "?")[:4] + "…" + (w or "?")[-4:]


def markdown(path=None):
    """The section of output/insajderi.md."""
    s, rows = summary(path), view(path, evidence=False)
    L = ["## Insajderski novčanici influencera (vjerojatno povezani)", "", CAVEAT, ""]
    if not s and not rows:
        return "\n".join(L + ["- još nema prolaza", ""]) + "\n"
    L += [f"- influencera na popisu {s.get('influencers', len(rows))}, s pozivima u podacima {s.get('with_calls', 0)}; "
          f"poziva {s.get('calls', 0)}, s tradeovima {s.get('covered', 0)}; događaja za usporedbu {s.get('universe', 0)}",
          f"- grupa {s.get('listed', 0)}, potvrđenih {s.get('confirmed', 0)}, s izravnom vezom {s.get('linked', 0)}; "
          f"isključeno botova {s.get('excluded', 0)}; Helius u prolazu {s.get('helius', 0):,} kr.", "",
          "| influencer | stanje | poziva | grupa | potvrđenih | najjača grupa |", "|---|---|---|---|---|---|"]
    for d in rows:
        top = d["wallets"][0] if d["wallets"] else None
        best = (f"{_sh(top['owner'])}: {top['cls']}, {top['n_front']} poziva, prodao nakon "
                f"{round((top['share_sold'] or 0) * 100)} %, vodstvo {top['med_lead_min']} min"
                + (", izravna veza" if top["link"] else "")) if top else "—"
        L.append(f"| {d['name']} | {d['status_hr']} | {d['n_calls']} | {d['n_listed']} | {d['n_confirmed']} | {best} |")
    pr = s.get("pred") or {}
    L += ["", f"Predpoziv (mjerenje, zastavica {s.get('flag', 'off')}): {pr.get('n', 0)} događaja, zaključeno "
              f"{pr.get('settled', 0)}, pogodak {pr.get('hit_pct')} %, medijan vodstva {pr.get('med_lead_min')} min.", ""]
    return "\n".join(L) + "\n"
