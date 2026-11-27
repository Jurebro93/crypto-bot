"""Possible links between a person (a group of wallets) and a TRACKED X account (27.11., vlasnik: "pokušaj korelacije
s Twitter profilima: daj vjerojatnost čiji bi to novčanik mogao biti").

DEFAMATION RISK (read before changing anything here): this module attaches a probability that wallets belong to a
real, named public figure. That is a statistical inference from public on-chain data and public posts, never a fact
and never a statement about anybody's intent. Therefore:
  * only accounts we already track because they publicly call tokens (kol.db kols, insajderi/kol_seed.json handles)
    are ever considered; a private individual or any other account is never linked, guessed or searched for;
  * the wording is always "moguća veza, X %" with the evidence, never "this is X's wallet";
  * below SHOW_MIN nothing is shown; the owner can hide a link (os_hidden) and a hidden link never comes back;
  * the links live only on logged-in, noindex pages for the OWNER (run_ui.py checks it on the server), never on a
    public page, the sitemap, share/novosti or an X post;
  * a wallet the person publicly denied ("osporeno" in kol_seed.json) is never used as evidence.

Evidence for person P and account H (no new API call: kol.db calls + the trades the other jobs stored):
  javni_novcanik  a member is H's publicly labelled wallet (a tracker's label: a claim, not a proof of ownership)
  insajder_alat   the insider tool (insajderi/kolwallets) listed these wallets as probably linked to H
  kupio_prije     a member bought H's called token in the PRE_S before H's first post about it, repeatedly
  prodao_nakon    ... and sold within POST_S after the post
  iskljucivost    how much of P's front-running is on H's calls rather than on everyone's
The weights are in this file only; the page shows the result and the evidence in words.
"""
import bisect
import json
import math
from collections import defaultdict

from osobe import store

PRE_S = 24 * 3600
POST_S = 2 * 3600
MIN_PRE = 3          # fewer front-run calls than this: no statistical link at all
SHOW_MIN = 0.5       # below this nothing is shown on the page
KEEP_MIN = 0.2       # below this nothing is stored
CAP_STAT = 0.85      # statistics alone never say more than this
CAP = 0.95


def tracked(p, seed=None):
    """{handle lower: display handle} of X accounts we track as public callers, and {wallet: (handle lower, status)}
    of their publicly labelled wallets. Telegram channels and wallet pseudo-handles are not X accounts."""
    hs, pub = {}, {}
    kc = store.ro(p.get("kol_db"))
    rows = store.q(kc, "SELECT handle FROM kols WHERE COALESCE(bot, 0) = 0") or store.q(kc, "SELECT handle FROM kols")
    for (h,) in rows:
        if h and not h.startswith(("tg:", "w:")):
            hs[h.lower()] = h
    for w, tw in store.q(kc, "SELECT wallet, twitter FROM kol_ids WHERE twitter IS NOT NULL AND twitter != ''"):
        h = str(tw).lstrip("@")
        if h.lower() in hs:
            pub.setdefault(w, (h.lower(), "javna_oznaka"))
    if kc is not None:
        kc.close()
    if seed is None:
        try:
            from insajderi import kolwallets
            seed = kolwallets.load_seed(kol_db=p.get("kol_db"))
        except Exception:  # noqa: BLE001
            seed = []
    for e in seed or []:
        for h in e.get("handles") or []:
            hs.setdefault(h.lower(), h)
        for w in e.get("wallets") or []:
            if e.get("handles"):
                pub[w["address"]] = (e["handles"][0].lower(), w.get("status") or "javna_oznaka")
    return hs, pub


def calls(p, handles):
    """{handle lower: [(token, t0)]}: each tracked account's FIRST post per token (kind call / brag, not deleted)."""
    kc = store.ro(p.get("kol_db"))
    out = defaultdict(list)
    for h, tok, t0 in store.q(kc, "SELECT handle, token, MIN(ts) FROM calls WHERE kind IN ('call', 'brag') "
                                  "GROUP BY handle, token"):
        if h and h.lower() in handles:
            out[h.lower()].append((tok, int(t0)))
    if kc is not None:
        kc.close()
    return out


def ik_groups(p):
    """{handle lower: [(members set, cls)]} from insajderi/kolwallets (ik_wallets, its own classes)."""
    ic = store.ro(p.get("insajderi_db"))
    handles = {}
    for inf, raw in store.q(ic, "SELECT inf, handles FROM ik_status"):
        try:
            handles[inf] = [h.lower() for h in json.loads(raw or "[]")]
        except (ValueError, TypeError):
            pass
    out = defaultdict(list)
    for inf, raw, cls in store.q(ic, "SELECT inf, members, cls FROM ik_wallets"):
        try:
            ms = set(json.loads(raw or "[]"))
        except (ValueError, TypeError):
            continue
        for h in handles.get(inf, []):
            out[h].append((ms, cls))
    if ic is not None:
        ic.close()
    return out


def _book(trade_rows, members):
    """{mint: (sorted buy ts, sorted sell ts)} of the members."""
    b, s = defaultdict(list), defaultdict(list)
    for w, m, ts, _slot, side, _sol, _payer in trade_rows:
        if w in members:
            (b if side == "buy" else s)[m].append(ts)
    return {m: (sorted(b.get(m, [])), sorted(s.get(m, []))) for m in set(b) | set(s)}


def front_runs(book, call_list):
    """[(token, t0, sold_after)] of the calls where a member bought in [t0 - PRE_S, t0)."""
    out = []
    for tok, t0 in call_list:
        bs = book.get(tok)
        if not bs:
            continue
        buys, sells = bs
        i = bisect.bisect_left(buys, t0 - PRE_S)
        if i < len(buys) and buys[i] < t0:
            j = bisect.bisect_left(sells, t0)
            out.append((tok, t0, j < len(sells) and sells[j] <= t0 + POST_S))
    return out


def score(n_pre, n_sold, excl, lift, public=None, ik_cls=None):
    """The probability (hidden weights). public: the wallet status when a member is the account's labelled wallet."""
    parts = []
    if public in ("javna_oznaka", "vlasnik"):
        parts.append(0.9 if public == "vlasnik" else 0.8)
    if ik_cls == "potvrđen":
        parts.append(0.6)
    elif ik_cls == "kandidat":
        parts.append(0.35)
    if n_pre >= MIN_PRE:
        base = 1 - math.exp(-0.3 * n_sold - 0.12 * (n_pre - n_sold))
        parts.append(min(CAP_STAT, base * min(1.0, 0.3 + excl) * min(1.0, lift / 3)))
    if not parts:
        return 0.0
    miss = 1.0
    for x in parts:
        miss *= 1 - x
    return round(min(CAP, 1 - miss), 3)


def evaluate(persons, trade_rows, call_map, handles, public, ik=None):
    """persons: {pid: members set}; call_map: {handle lower: [(token, t0)]}. -> {pid: [(handle, prob, evidence)]}
    for links >= KEEP_MIN. Only handles in `handles` (the tracked set) are ever evaluated."""
    ik = ik or {}
    n_all = len({tok for cl in call_map.values() for tok, _t in cl}) or 1
    out = {}
    for pid, ms in persons.items():
        book = _book(trade_rows, ms)
        fr = {h: front_runs(book, cl) for h, cl in call_map.items() if h in handles}
        any_pre = {tok for rows in fr.values() for tok, _t, _s in rows}
        res = []
        cand = {h for h, rows in fr.items() if rows}
        pub_h = {}
        for w in ms:
            if w in public and public[w][0] in handles and public[w][1] != "osporeno":
                pub_h[public[w][0]] = public[w][1]
        ik_h = {}
        for h, groups in ik.items():
            if h not in handles:
                continue
            for gms, cls in groups:
                if gms & ms and (cls == "potvrđen" or h not in ik_h):
                    ik_h[h] = cls
        for h in cand | set(pub_h) | set(ik_h):
            rows = fr.get(h, [])
            toks = {t for t, _x, _s in rows}
            n_pre, n_sold = len(toks), len({t for t, _x, s in rows if s})
            excl = n_pre / len(any_pre) if any_pre else 0.0
            expected = len(any_pre) / n_all * len(call_map.get(h, ()))
            lift = n_pre / max(expected, 0.5)
            prob = score(n_pre, n_sold, excl, lift, pub_h.get(h), ik_h.get(h))
            if prob < KEEP_MIN:
                continue
            ev = {"kupio_prije": n_pre, "prodao_nakon": n_sold, "poziva": len(call_map.get(h, ())),
                  "iskljucivost": round(excl, 2), "javni_novcanik": pub_h.get(h), "insajder_alat": ik_h.get(h),
                  "primjeri": [t for t, _x, s in sorted(rows, key=lambda r: -r[1])[:5]]}
            res.append((handles[h], prob, ev))
        if res:
            out[pid] = sorted(res, key=lambda r: -r[1])
    return out


def text(ev):
    """The evidence in words (results only)."""
    out = []
    if ev.get("javni_novcanik"):
        out.append("jedan od novčanika javno je označen kao njegov (oznaka trackera, ne dokaz)")
    if ev.get("insajder_alat"):
        out.append("alat za insajderske novčanike ga vodi kao vjerojatno povezanog")
    if ev.get("kupio_prije"):
        s = f"kupio prije {ev['kupio_prije']} od {ev.get('poziva') or '?'} njegovih poziva"
        if ev.get("prodao_nakon"):
            s += f", na {ev['prodao_nakon']} prodao ubrzo nakon objave"
        out.append(s)
    return out


def save(con, res, now):
    con.execute("DELETE FROM os_xlinks")
    con.executemany("INSERT OR REPLACE INTO os_xlinks VALUES (?,?,?,?,?)",
                    [(pid, h, prob, json.dumps(ev, ensure_ascii=False), int(now))
                     for pid, rows in res.items() for h, prob, ev in rows])


def visible(con, pid=None):
    """[(pid, handle, prob, evidence)] at or above SHOW_MIN and not hidden by the owner."""
    hidden = {(a, b.lower()) for a, b in store.q(con, "SELECT pid, handle FROM os_hidden")}
    sql = "SELECT pid, handle, prob, evidence FROM os_xlinks WHERE prob >= ?"
    args = [SHOW_MIN]
    if pid:
        sql += " AND pid = ?"
        args.append(pid)
    out = []
    for p_, h, prob, ev in store.q(con, sql + " ORDER BY prob DESC", args):
        if (p_, h.lower()) in hidden:
            continue
        try:
            ev = json.loads(ev or "{}")
        except ValueError:
            ev = {}
        out.append((p_, h, prob, ev))
    return out


def hide(con, pid, handle, who, now):
    con.execute("INSERT OR REPLACE INTO os_hidden VALUES (?,?,?,?)", (pid, handle, who, int(now)))
