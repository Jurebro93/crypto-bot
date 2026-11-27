"""Evidence that two wallets belong to one person, from data the other jobs already stored (no API call here).

Loaders read the other modules' databases read-only and return plain rows; the link builders are pure functions on
those rows, so the offline tests feed synthetic data. Every link carries its evidence (kind, a count, a detail) and
a confidence; osobe/profil.py joins the links into persons.

Evidence kinds (the weights live in KIND_P and are never shown to a user: the owner wants the method hidden):
  placa_naknadu   one wallet paid the network fee of the other's trade (not a relayer that pays for many)
  financiranje    one wallet funded the other (first funding / a funder that is not a hub or an exchange)
  isti_vlasnik    the insider tool already merged them into one owner (shared funder, fee payer, corr.db groups)
  skupljanje      tokens or SOL swept into one common wallet (that is not a hub)
  isti_blok       the same tokens bought in the same block (slot) repeatedly
  ista_minuta     the same tokens bought within the same minute repeatedly (weaker than a block)
  bundle          members of a repeated launch bundle (insajderi i2_bundle: same owner / fee payer in one block, or
                  one owner's wallets holding a big share of the early buys, on 2+ pumps)
  ista_grupa      the insider tool's owner groups (i2_pp / i2_groups / ik_wallets members)
"""
import json
from collections import Counter, defaultdict

from osobe import store

DAY = 86400
LOOKBACK_D = 120
MAX_CANDIDATES = 30_000      # wallets considered for co-buys and profiles (bounded memory on the 512 MB server)
HUB_MIN = 20                 # a funder / sweep target with more distinct counterparties than this is a hub
RELAYER_MIN = 5              # a fee payer for this many distinct wallets is a relayer, never a link
COBUY_GAP_S = 60
COBUY_MAX_WINDOW = 25        # more buyers than this inside the minute: a frenzy, no pair evidence from it
COBUY_MIN_SLOT = 2           # distinct tokens bought in the same block
COBUY_MIN_MIN = 3            # distinct tokens bought in the same minute
BUSY_PARTNERS = 30           # a wallet that co-buys with more wallets than this is a bot / sniper: its co-buys drop
SWEEP_MIN_SOL = 0.05
LINK_MIN = 0.5               # a link joins two wallets into one person from this confidence

# hidden weights (code only): the chance a single piece of evidence of this kind means one person
KIND_P = {"placa_naknadu": 0.85, "financiranje": 0.7, "isti_vlasnik": 0.7, "skupljanje": 0.55, "isti_blok": 0.3,
          "ista_minuta": 0.12, "bundle": 0.6, "ista_grupa": 0.55}
KIND_CAP = {"isti_blok": 0.9, "ista_minuta": 0.6, "skupljanje": 0.85}
KIND_HR = {"placa_naknadu": "jedan je platio naknadu za kupnju drugoga",
           "financiranje": "jedan je financirao drugoga",
           "isti_vlasnik": "isti izvor sredstava ili isti platitelj naknade",
           "skupljanje": "tokeni ili SOL skupljeni na zajednički novčanik",
           "isti_blok": "isti tokeni kupljeni u istom bloku, više puta",
           "ista_minuta": "isti tokeni kupljeni u istoj minuti, više puta",
           "bundle": "zajedno u snopu kupnji na lansiranju, na više pumpi",
           "ista_grupa": "u istoj grupi vlasnika po alatu za insajdere"}


def _chunks(xs, n=400):
    xs = list(xs)
    for i in range(0, len(xs), n):
        yield xs[i:i + n]


def _in(xs):
    return ",".join("?" * len(xs))


def _members(raw):
    try:
        ms = json.loads(raw or "[]")
    except (ValueError, TypeError):
        return []
    return [m for m in ms if isinstance(m, str) and m]


# ---------- loaders (read-only, every one tolerates a missing database or table) -----------------------------------

def candidates(p, limit=MAX_CANDIDATES):
    """Wallets worth grouping, most interesting first: the insider tool's groups and bundles, wallets bought before a
    pump on 2+ events, scored wallets, KOL insiders, tracked wallets. Returns (list, {wallet: why set})."""
    why = defaultdict(set)
    order = []

    def add(ws, tag):
        for w in ws:
            if isinstance(w, str) and 30 <= len(w) <= 44:
                if w not in why:
                    order.append(w)
                why[w].add(tag)

    ic = store.ro(p.get("insajderi_db"))
    for (raw,) in store.q(ic, "SELECT members FROM i2_bundle"):
        add(_members(raw), "bundle")
    for t in ("i2_pp", "i2_groups"):
        for (raw,) in store.q(ic, f"SELECT members FROM {t}"):
            add(_members(raw), "grupa")
    for (raw,) in store.q(ic, "SELECT members FROM ik_wallets"):
        add(_members(raw), "influencer")
    add([w for (w,) in store.q(ic, "SELECT wallet FROM i2_smart ORDER BY score DESC LIMIT 5000")], "smart")
    add([w for (w,) in store.q(ic, "SELECT wallet FROM i2_part WHERE bought_before = 1 GROUP BY wallet "
                                   "HAVING COUNT(DISTINCT eid) >= 2 ORDER BY COUNT(DISTINCT eid) DESC LIMIT 15000")],
        "prije_pumpe")
    if ic is not None:
        ic.close()
    kc = store.ro(p.get("kol_db"))
    add([w for (w,) in store.q(kc, "SELECT wallet FROM kol_wallets")], "kol_insajder")
    add([w for (w,) in store.q(kc, "SELECT wallet FROM insiders GROUP BY wallet HAVING COUNT(*) >= 2")], "kol_insajder")
    add([w for (w,) in store.q(kc, "SELECT wallet FROM kol_ids")], "javni")
    if kc is not None:
        kc.close()
    wc = store.ro(p.get("wallet_db"))
    add([w for (w,) in store.q(wc, "SELECT wallet FROM wallets WHERE tier IN ('S','A','B') OR labels LIKE '%bundler%' "
                                   "ORDER BY COALESCE(score, 0) DESC LIMIT 10000")], "ocijenjen")
    if wc is not None:
        wc.close()
    ec = store.ro(p.get("early_db"))
    add([w for (w,) in store.q(ec, "SELECT member FROM group_member WHERE kind = 'wallet'")], "ekipa")
    if ec is not None:
        ec.close()
    hc = store.ro(p.get("hype_db"))
    add([w for (w,) in store.q(hc, "SELECT DISTINCT wallet FROM chain_trades")], "praceni")
    if hc is not None:
        hc.close()
    out = order[:limit]
    return out, {w: why[w] for w in out}


def trades(p, wallets, now, days=LOOKBACK_D):
    """[(wallet, mint, ts, slot, side, sol, payer)] of `wallets` from every stored source (deduplicated by wallet,
    mint, ts, side). side is 'buy' / 'sell'; slot and payer None where the source has none."""
    ws = list(wallets)
    since = int(now - days * DAY)
    seen, out = set(), []

    def put(w, m, ts, slot, side, sol, payer):
        if not m or ts is None or side not in ("buy", "sell"):
            return
        k = (w, m, int(ts), side)
        if k in seen:
            return
        seen.add(k)
        out.append((w, m, int(ts), slot, side, abs(sol) if sol is not None else None, payer))

    ic = store.ro(p.get("insajderi_db"))
    ec = store.ro(p.get("early_db"))
    for ch in _chunks(ws):
        for r in store.q(ic, f"SELECT wallet, mint, ts, slot, side, sol, payer FROM i2_trades WHERE wallet IN ({_in(ch)}) "
                             "AND ts >= ?", (*ch, since)):
            put(*r)
        for t in ("group_buys", "preshill_trades", "precall_trades"):
            for r in store.q(ec, f"SELECT wallet, mint, ts, slot, side, sol, payer FROM {t} WHERE wallet IN ({_in(ch)}) "
                                 "AND ts >= ?", (*ch, since)):
                put(*r)
    for c in (ic, ec):
        if c is not None:
            c.close()
    wc = store.ro(p.get("wallet_db"))
    for ch in _chunks(ws):
        for w, m, ts, kind, sol in store.q(wc, f"SELECT wallet, mint, ts, kind, sol FROM wallet_trades WHERE wallet IN "
                                               f"({_in(ch)}) AND ts >= ?", (*ch, since)):
            put(w, m, ts, None, kind, sol, None)
    if wc is not None:
        wc.close()
    hc = store.ro(p.get("hype_db"))
    want = set(ws)
    for w, m, side, ts, sol in store.q(hc, "SELECT wallet, mint, side, ts, sol FROM chain_trades WHERE ts >= ?", (since,)):
        if w in want:
            put(w, m, ts, None, side, sol, None)
    if hc is not None:
        hc.close()
    return out


def wallet_rows(p, wallets):
    """{wallet: [pnl rows]} from wallets.db wallet_trades (what wallets/pnl.positions reads)."""
    out = defaultdict(list)
    wc = store.ro(p.get("wallet_db"))
    for ch in _chunks(wallets):
        for w, sig, ts, mint, tokens, sol, kind in store.q(
                wc, f"SELECT wallet, sig, ts, mint, tokens, sol, kind FROM wallet_trades WHERE wallet IN ({_in(ch)})", ch):
            out[w].append({"sig": sig, "ts": ts, "mint": mint, "tokens": tokens or 0.0, "sol": sol or 0.0, "kind": kind})
    if wc is not None:
        wc.close()
    return out


def transfers(p, now, days=LOOKBACK_D):
    """[(src, dst, mint, amount, ts, first_in)] from hype.db chain_transfers and insajderi.db ik_transfers."""
    since = int(now - days * DAY)
    out = []
    hc = store.ro(p.get("hype_db"))
    for src, dst, mint, amount, ts in store.q(hc, "SELECT src, dst, mint, amount, ts FROM chain_transfers WHERE ts >= ?",
                                               (since,)):
        out.append((src, dst, mint or "SOL", amount or 0.0, ts, 0))
    if hc is not None:
        hc.close()
    ic = store.ro(p.get("insajderi_db"))
    for src, dst, mint, amount, ts, first in store.q(ic, "SELECT src, dst, mint, amount, ts, first_in FROM ik_transfers"):
        out.append((src, dst, mint or "SOL", amount or 0.0, ts, first or 0))
    if ic is not None:
        ic.close()
    return [t for t in out if t[0] and t[1] and t[0] != t[1]]


def funders(p, wallets):
    """{wallet: set(funder)} from wallets.db sightings and rug reports (kol/groupdisc._funders, no API)."""
    try:
        from kol import groupdisc as gd
        return gd._funders(p, [], set(wallets))
    except Exception:  # noqa: BLE001
        return {}


def exchanges(p):
    try:
        from holderi import burze
        return set(burze.registry(wallet_db=p.get("wallet_db")))
    except Exception:  # noqa: BLE001
        return set()


def insider_owners(p):
    """[(wallet, owner)] where the insider tool merged a wallet into another owner, and [(kind, members)] of its
    owner groups and bundles."""
    ic = store.ro(p.get("insajderi_db"))
    owners = store.q(ic, "SELECT DISTINCT wallet, owner FROM i2_part WHERE owner IS NOT NULL AND owner != wallet")
    groups = []
    for t in ("i2_pp", "i2_groups"):
        groups += [("ista_grupa", _members(raw)) for (raw,) in store.q(ic, f"SELECT members FROM {t} WHERE n_members >= 2")]
    groups += [("ista_grupa", _members(raw)) for (raw,) in store.q(ic, "SELECT members FROM ik_wallets")]
    bundles = [("bundle", _members(raw)) for (raw,) in store.q(ic, "SELECT members FROM i2_bundle WHERE n_members >= 2")]
    if ic is not None:
        ic.close()
    try:
        from insajderi import chain
        corr = [("isti_vlasnik", g) for g in chain.corr_groups(p.get("corr_db"))]
    except Exception:  # noqa: BLE001
        corr = []
    return owners, groups + bundles + corr


# ---------- link builders (pure) -----------------------------------------------------------------------------------

class Links:
    """Pair evidence: add(a, b, kind, n, detail); conf(a, b) = 1 - prod(1 - p_kind) over the kinds seen."""

    def __init__(self):
        self.ev = defaultdict(dict)   # (a, b) -> {kind: {"n": int, "d": [details]}}

    def add(self, a, b, kind, n=1, detail=None):
        if not a or not b or a == b:
            return
        k = (a, b) if a < b else (b, a)
        e = self.ev[k].setdefault(kind, {"n": 0, "d": []})
        e["n"] += n
        if detail and len(e["d"]) < 5 and detail not in e["d"]:
            e["d"].append(detail)

    @staticmethod
    def kind_p(kind, n):
        p1 = KIND_P[kind]
        p = 1 - (1 - p1) ** max(1, n)
        return min(p, KIND_CAP.get(kind, 0.97))

    def conf(self, k):
        miss = 1.0
        for kind, e in self.ev[k].items():
            miss *= 1 - self.kind_p(kind, e["n"])
        return round(1 - miss, 3)

    def items(self):
        for k in self.ev:
            yield k, self.conf(k), self.ev[k]


def relayers(paid, min_wallets=RELAYER_MIN):
    by = defaultdict(set)
    for payer, w in paid:
        if payer and w and payer != w:
            by[payer].add(w)
    return {x for x, ws in by.items() if len(ws) >= min_wallets}


def add_payers(links, trade_rows):
    """A fee payer that paid for another wallet's trade (not a relayer)."""
    paid = [(r[6], r[0]) for r in trade_rows if r[6] and r[6] != r[0]]
    relay = relayers(paid)
    for (payer, w), n in Counter(paid).items():
        if payer not in relay:
            links.add(payer, w, "placa_naknadu", n)
    return relay


def hubs_of(pairs, extra=(), hub_min=HUB_MIN):
    """Senders or receivers with more than hub_min distinct counterparties, plus exchanges."""
    out_n, in_n = defaultdict(set), defaultdict(set)
    for a, b in pairs:
        out_n[a].add(b)
        in_n[b].add(a)
    return ({a for a, s in out_n.items() if len(s) > hub_min} | {b for b, s in in_n.items() if len(s) > hub_min}
            | set(extra))


def add_funding(links, fund, xfers, hubs):
    """fund: {wallet: set(funder)}; xfers: transfers rows. A SOL transfer of >= SWEEP_MIN_SOL marked first funding,
    or a funder from the stored sightings, is "financiranje" when the funder is no hub."""
    for w, fs in fund.items():
        for f in fs:
            if f and f not in hubs and w not in hubs:
                links.add(f, w, "financiranje", 1, "prvo financiranje")
    for src, dst, mint, amount, ts, first in xfers:
        if mint == "SOL" and first and amount >= SWEEP_MIN_SOL and src not in hubs and dst not in hubs:
            links.add(src, dst, "financiranje", 1, "prvo financiranje")


def add_sweeps(links, xfers, hubs, cands):
    """Tokens (or SOL that is no first funding) moved from a wallet into a common one: a link when the same pair moved
    twice, or the target collected from 2+ of our candidate wallets. Never into a hub or an exchange."""
    pair_n = Counter()
    senders = defaultdict(set)
    for src, dst, mint, amount, ts, first in xfers:
        if src in hubs or dst in hubs or first:
            continue
        if mint == "SOL" and amount < SWEEP_MIN_SOL:
            continue
        pair_n[(src, dst)] += 1
        if src in cands:
            senders[dst].add(src)
    for (src, dst), n in pair_n.items():
        if n >= 2 or len(senders.get(dst, ())) >= 2:
            links.add(src, dst, "skupljanje", n, f"{n} prijenosa")


def add_cobuys(links, trade_rows, cands, gap_s=COBUY_GAP_S, max_window=COBUY_MAX_WINDOW):
    """Pairs of candidate wallets whose FIRST buy of a token came in the same block (slot) or within gap_s, on several
    distinct tokens. A minute with more than max_window buyers adds nothing (a frenzy), and a wallet that co-buys with
    more than BUSY_PARTNERS others is dropped (a bot or a sniper co-buys with everybody)."""
    first = {}
    for w, m, ts, slot, side, _sol, _payer in trade_rows:
        if side != "buy" or w not in cands:
            continue
        k = (m, w)
        if k not in first or ts < first[k][0]:
            first[k] = (ts, slot)
    by_mint = defaultdict(list)
    for (m, w), (ts, slot) in first.items():
        by_mint[m].append((ts, slot, w))
    slot_tok, min_tok = defaultdict(set), defaultdict(set)
    for m, bs in by_mint.items():
        bs.sort()
        n = len(bs)
        j0 = 0
        for i in range(n):
            ti, si, wi = bs[i]
            while bs[j0][0] < ti - gap_s:
                j0 += 1
            j = i + 1
            while j < n and bs[j][0] - ti <= gap_s:
                j += 1
            if j - j0 > max_window:
                continue
            for k in range(i + 1, j):
                tk, sk, wk = bs[k]
                pair = (wi, wk) if wi < wk else (wk, wi)
                if si is not None and si == sk:
                    slot_tok[pair].add(m)
                else:
                    min_tok[pair].add(m)
    partners = defaultdict(set)
    keep = {}
    for pair in set(slot_tok) | set(min_tok):
        ns, nm = len(slot_tok.get(pair, ())), len(min_tok.get(pair, ()))
        if ns >= COBUY_MIN_SLOT or ns + nm >= COBUY_MIN_MIN:
            keep[pair] = (ns, nm)
            partners[pair[0]].add(pair[1])
            partners[pair[1]].add(pair[0])
    busy = {w for w, s in partners.items() if len(s) > BUSY_PARTNERS}
    for (a, b), (ns, nm) in keep.items():
        if a in busy or b in busy:
            continue
        if ns:
            links.add(a, b, "isti_blok", ns, f"{ns} tokena u istom bloku")
        if nm and ns + nm >= COBUY_MIN_MIN:
            links.add(a, b, "ista_minuta", nm, f"{nm} tokena u istoj minuti")
    return busy


def add_groups(links, owners, groups, hubs=frozenset()):
    """The insider tool's owner merges (wallet -> owner) and member lists: a star to the smallest member, so a list
    of k wallets gives k - 1 links (enough to join them, no k^2 pairs)."""
    for w, o in owners:
        if w not in hubs and o not in hubs:
            links.add(w, o, "isti_vlasnik", 1)
    for kind, ms in groups:
        ms = sorted({m for m in ms if m not in hubs})
        if len(ms) < 2 or len(ms) > 60:
            continue
        for m in ms[1:]:
            links.add(ms[0], m, kind, 1)
