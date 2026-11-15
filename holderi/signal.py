"""The listing signal and the insider caution (pure: no network, no database).

Owner 15.11.: "if a large part of the supply is sent to an external wallet previously known as an exchange wallet, that
must be a STRONG signal"; the same evening: "if the token is NOT yet listed on that exchange, how would anyone sell it
there? Tokens not listed on bigger exchanges that send part of their supply to that exchange's wallet will potentially
be listed there."

One evidence group = one token x one exchange inside the window (72 h): the moves of supply to that exchange's wallets
(hot, cold, or a per-user deposit address that sweeps into them), a new / growing balance of that exchange, new top
holders funded by that exchange (market-maker-like distribution) and Grok's listing_check.

score (0-100) = (size + sender + tier + growth + mm + grok) x weight(address confidence) x listing factor
  size     20 x % of supply that reached the exchange (2 % = 40, at most 40)
  sender   team / deployer-linked 20, insider cluster 15, whale 8, normal holder 4, untraced (only the balance) 5,
           another exchange 0 (internal movement)
  tier     the exchange: tier 1 (Binance, Coinbase, OKX, Bybit, Upbit) 15, tier 2 10, tier 3 / unknown 5
  growth   the exchange's balance grew on 2+ snapshots in a row 10, once 5
  mm       new top holders funded by that exchange: 5 each, at most 10
  grok     Grok's listing_check: dobar / kupi +10 x confidence, loš / preskoči -10 x confidence
  weight   0.5 + 0.5 x the destination's confidence (owner-confirmed 1.0; seed 0.7 -> 0.85; heuristic 0.45 -> 0.73)
  listing  NOT listed there ("ne") 1.0, unknown 0.8, symbol-only match ("nesigurno") 0.6
           -> kind "pre_listing" ("PRE-LISTING SIGNAL" from min_score, 60)
           ALREADY listed there (contract match): kind "deposit_sell": a deposit to sell, bearish -> the caution, never
           a buy signal
Caution (per token): insider share excluding exchanges and LP over insider_max (30 %) lowers the priority by the excess
(at most 30) and blocks entries from insider_block (50 %); team / insiders moving >= sell_pct (1 %) of supply out to sell
(a swap, or a deposit to an exchange that lists it) in the window blocks entries; whales depositing >= sell_pct to a
listing exchange lower it by 15.
"""
from holderi import burze

DEFAULTS = {"min_score": 60, "window_h": 72, "insider_max": 30.0, "insider_block": 50.0, "sell_pct": 1.0}
SENDER = {"team": 20, "insider": 15, "whale": 8, "normal": 4, None: 5, "untraced": 5, "exchange": 0, "lp": 0, "burn": 0}
TIER_PTS = {1: 15, 2: 10, 3: 5}
LIST_F = {"ne": 1.0, "nepoznato": 0.8, "nesigurno": 0.6}


def score_group(moves, exchange, listed="nepoznato", growth=0, mm=0, grok=None):
    """{"score", "kind", "parts", "reasons", "pct"} of one token x exchange evidence group.
    moves: [{"pct", "sender_cls", "conf", "kind", "dest"?}] (kind to_exchange / deposit_sweep / new_balance / balance_jump)."""
    ex = burze.norm_exchange(exchange)
    pct = round(sum(max(0.0, float(m.get("pct") or 0)) for m in moves), 3)
    p = {"size": round(min(40.0, 20.0 * pct), 1)}
    senders = [m.get("sender_cls") or "untraced" for m in moves] or ["untraced"]
    p["sender"] = float(max(SENDER.get(s, 4) for s in senders))
    p["tier"] = float(TIER_PTS.get(burze.TIER.get(ex, 3), 5))
    p["growth"] = 10.0 if growth >= 2 else 5.0 if growth == 1 else 0.0
    p["mm"] = float(min(10, 5 * int(mm or 0)))
    g = grok or {}
    gv = 0.0
    if g.get("verdict") in ("dobar", "kupi"):
        gv = 10.0 * float(g.get("confidence") or 0.5)
    elif g.get("verdict") in ("loš", "preskoči"):
        gv = -10.0 * float(g.get("confidence") or 0.5)
    p["grok"] = round(gv, 1)
    conf = max([float(m.get("conf") or 0) for m in moves] or [0.0])
    w = burze.weight(conf)
    raw = sum(p.values())
    name = burze.NAMES.get(ex, ex)
    best = max(senders, key=lambda s: SENDER.get(s, 4))
    reasons = [f"{pct:.2f} % ponude na {name}", f"pošiljatelj: {_who(best)}",
               f"adresa burze pouzdanost {conf:.2f}" + (" (nepotvrđeno)" if conf < 1 else " (potvrđeno)")]
    if any(m.get("kind") == "deposit_sweep" for m in moves):
        reasons.append("preko depozitne adrese koja prebacuje na burzu")
    if growth:
        reasons.append(f"stanje burze raslo {growth}x zaredom")
    if mm:
        reasons.append(f"{mm} novih holdera financirala burza (market maker?)")
    if gv:
        reasons.append(f"Grok listing_check {g.get('verdict')} ({float(g.get('confidence') or 0.5):.1f})")
    if listed == "da":
        sc = round(max(0.0, min(100.0, (p["size"] + p["sender"]) * w)), 1)
        return {"score": sc, "kind": "deposit_sell", "parts": p, "weight": w, "pct": pct, "exchange": ex,
                "reasons": reasons + [f"token je VEĆ listan na {name}: depozit za prodaju (oprez)"]}
    f = LIST_F.get(listed, 0.8)
    sc = round(max(0.0, min(100.0, raw * w * f)), 1)
    reasons.append({"ne": f"token NIJE listan na {name}", "nesigurno": f"na {name} postoji isti simbol (nesigurno)",
                    "nepoznato": f"lista {name} nepoznata"}.get(listed, ""))
    return {"score": sc, "kind": "pre_listing", "parts": p, "weight": w, "listing_factor": f, "pct": pct,
            "exchange": ex, "reasons": [r for r in reasons if r]}


def _who(cls):
    return {"team": "tim / deployer", "insider": "insajder", "whale": "kit", "normal": "običan holder",
            "untraced": "nepoznat (samo stanje)", "exchange": "druga burza", None: "nepoznat"}.get(cls, cls or "nepoznat")


def caution(profile, moves=(), cfg=None):
    """{"pts" (<= 0), "block" (text or None), "why": [..]} of one token's newest profile and its moves in the window."""
    c = dict(DEFAULTS)
    c.update(cfg or {})
    why, pts, block = [], 0.0, None
    ins = (profile or {}).get("insider_ex")
    if ins is not None and ins > c["insider_max"]:
        pts -= min(30.0, ins - c["insider_max"])
        why.append(f"insajderi (bez burzi i LP-a) drže {ins:.0f} %")
        if ins >= c["insider_block"]:
            block = f"insajderi drže {ins:.0f} % ponude (bez burzi i LP-a)"
    sold = sum(float(m.get("pct") or 0) for m in moves
               if m.get("sender_cls") in ("team", "insider") and m.get("kind") in ("sell", "deposit_sell"))
    if sold >= c["sell_pct"]:
        block = block or f"tim / insajderi izbacuju {sold:.1f} % ponude (prodaja ili burza gdje je listan)"
        why.append(f"tim / insajderi izbacuju {sold:.1f} % ponude")
        pts -= 20.0
    whale = sum(float(m.get("pct") or 0) for m in moves if m.get("sender_cls") == "whale" and m.get("kind") == "deposit_sell")
    if whale >= c["sell_pct"]:
        pts -= 15.0
        why.append(f"kitovi šalju {whale:.1f} % ponude na burzu gdje je listan (prodaja?)")
    return {"pts": round(max(-50.0, pts), 1), "block": block, "why": why}


def loud(sym, mcap, sig):
    """The log line of a strong pre-listing signal."""
    name = burze.NAMES.get(sig["exchange"], sig["exchange"])
    mc = f"${(mcap or 0) / 1e6:,.1f}M" if mcap else "$?"
    return (f"LISTING SIGNAL: {sym} (MC {mc}): score {sig['score']:.0f} — " + "; ".join(sig["reasons"][:5])
            + f" — mogući listing na {name}")
