"""Autopilot (/pravi-trade) as a trading terminal (11.11., Jure: "brzo, pregledno, svježe, na svakom uređaju"; uzori
Axiom/Photon i spot raspored Binance/Bybit).

Layout: on a desktop (>= 1024 px) two columns, the chart and the tables on the left (~65 %), the order panel on the
right (~35 %); below 1024 px one column, the panel opens as a bottom sheet from a sticky "Kupi / Prodaj" bar.
  1. chart of the selected token (TradingView Lightweight Charts, self-hosted ui/static/ap, Apache-2.0 with the
     TradingView attribution under the chart): candles 1m/5m/15m/1h from data we already store (rangedca.data.series:
     range.db snaps + hype.db token_pulse + GeckoTerminal / minute.db candles), MC or price, lines for my average
     entry, the DCA orders, SL (red), TP (green) and the rangedca zones as bands with their computed_ts;
     the header above it: symbol, MC, 5m/1h/24h, liquidity, 1h volume, buys/sells 5m, rug badge.
  2. the order panel: Kupi / Prodaj tabs posting to the SAME routes with the same field names as before
     (/pravi-trade/buy: token, sol, at, tp, sl, exit, prijedlog; /pravi-trade/sell: id, frac; /pravi-trade/dca:
     token, lvl, sol); quick amounts only fill fields; the cost estimate (cost_pct) and the wallet / day numbers.
  3. tabs under the chart: Pozicije (live first, paper grey), Otvoreni nalozi, Povijest (lazy), Dnevnik (lazy).
  4. "Što kupiti" (one list of every proposal + the tool's live picks, sorted by EV per minute, lazy, every 30 s)
     and "Koga pratimo" (wallets / influencers / tokens, lazy).
  5. "Postavke i dijagnostika": the older sections of this page (pravila, Grok, zastavice, ...), loaded when opened.

Speed: the first HTML holds only the header, the chart's frame, the positions, the orders and the panel, built from
cached reads (no DexScreener request waits for the page: live numbers come with the first tick); everything else is
fetched when it scrolls into view or is opened. One aggregated read-only endpoint (first_view, cached FIRST_TTL_S),
one shared price tick (tick, at most every TICK_S for every viewer) streamed by SSE (stream) with a 5-s poll as the
fallback. Every block says "ažurirano prije X s" (freshness), older than STALE_S is a yellow badge.
Nothing here writes a database or changes how a trade is made: every POST still goes through ui/pravitrade.post.
"""
import gzip
import hashlib
import json
import os
import re
import sqlite3
import threading
import time
from urllib.parse import quote

from trade import executor, settings
from ui import pravitrade as pt
from ui import redak
from ui.html import esc, short

TITLE = pt.TITLE
HERE = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(HERE, "static", "ap")
LWC_FILE = "lightweight-charts-4.2.3.js"   # pinned TradingView Lightweight Charts release (Apache-2.0)
FIRST_TTL_S = 3          # the aggregated first view is built at most this often per (viewer kind, token)
TICK_S = 2.0             # one shared live tick for every viewer and stream, at most this often
STREAM_MAX = int(os.environ.get("AP_STREAM_MAX", "6"))   # SSE connections at once (each holds one server thread)
STREAM_MAX_S = int(os.environ.get("AP_STREAM_MAX_S", "300"))   # one connection lives this long, then reconnects
STREAM_HB_S = 15         # a heartbeat event when nothing changed for this long
POLL_S = 5               # the browser's fallback poll when the stream is refused or broken
KUPITI_EVERY_S = 30      # "Što kupiti" while it is on screen
PRATIMO_EVERY_S = 60
ZOVU_EVERY_S = 15        # "Tko sada zove" feed inside "Koga pratimo"
DNEVNIK_EVERY_S = 5
STALE_S = 60             # older data shows a yellow badge
CANDLE_TTL_S = 20
CANDLE_KEEP = 6          # token series kept in memory (RAM: ~1-2 MB at most)
WANT_TTL_S = 30          # a token a viewer looks at stays in the shared tick this long after the last ask
WANT_MAX = 4             # tokens beyond the open positions in the shared tick
HIST_PAGE = 20
QUICK_SOL = (0.05, 0.1, 0.15)
SELL_FRACS = ((0.25, "25 %"), (0.5, "50 %"), (1.0, "100 %"))
TP_CHIPS = (15, 30, 50, 100)
SL_CHIPS = (20, 40, 60)
DCA_ROWS = 3
TFS = {"1m": (60, 6), "5m": (300, 24), "15m": (900, 72), "1h": (3600, 168)}   # tf -> (bucket s, hours read)
MINT = re.compile(r"[1-9A-HJ-NP-Za-km-z]{32,44}")
OSTALO_ANCHORS = ("limiti", "cilj", "stop", "trigger", "mcp", "grok-auto", "pozivnice", "postavljanje", "exit-planovi",
                  "pregled-inf", "jos", "zastita", "sazetak", "ev-znacajke", "zastavice", "pravila", "fast-path",
                  "preshill", "eventi", "preporuke", "vrijednost")

_LOCK = threading.RLock()
_FIRST = {}                       # (owner, mint) -> (ts, dict)
_TICK = {"ts": 0.0, "val": None}
_WANT = {}                        # mint -> ts of the last viewer that asked for it
_CANDLES = {}                     # (mint, hours) -> (ts, candles, snap)
_RUG = {}                         # mint -> (ts, status)
_STREAMS = threading.BoundedSemaphore(max(1, STREAM_MAX))
_STATIC = {}                      # name -> (raw, gz, ctype, version)


# ---------- small pure helpers (tested offline) -------------------------------------------------------------------

def cost_pct(size_usd, liq, fee_side=None):
    """The panel's cost estimate in percent from trade/cost.py, the one cost model (11.11., rules A-C):
    round trip = 2 x fee_side + 2 x impact, impact = size_usd / (liq/2 + size_usd); fee_side is its calibrated value
    unless given. {'fee_pct', 'slip_pct' (both sides), 'buy_slip_pct', 'cost_pct', 'warn'}; warn: the buy's own
    slippage is above cost.SLIP_MAX (2 %, the size-by-slippage rule C). None when the size or the liquidity is unknown.
    The browser computes the same (ap.js costEst) with the fee_side and slip_max of the first view."""
    from trade import cost
    try:
        size_usd, liq = float(size_usd), float(liq)
    except (TypeError, ValueError):
        return None
    if size_usd <= 0 or liq <= 0:
        return None
    fee = cost.fee_side() if fee_side is None else float(fee_side)
    imp = cost.impact(size_usd, liq)
    return {"fee_pct": round(200 * fee, 3), "slip_pct": round(200 * imp, 3), "buy_slip_pct": round(100 * imp, 3),
            "cost_pct": round(100 * cost.round_trip(size_usd, liq, fee), 3), "warn": imp > cost.SLIP_MAX}


def freshness(ts, now=None, stale_s=STALE_S):
    """("ažurirano prije 12 s", stale) for a block's data time; stale when older than stale_s (the page shows a
    yellow badge). No time = ("nema podataka", True). The browser counts the same way every second (ap.js age())."""
    if not ts:
        return "nema podataka", True
    age = max(0, int((now or time.time()) - float(ts)))
    if age < 60:
        words = f"{age} s"
    elif age < 3600:
        words = f"{age // 60} min"
    else:
        words = f"{age // 3600} h"
    return f"ažurirano prije {words}", age > stale_s


def age_badge(ts, now=None):
    """The freshness badge a block carries; ap.js keeps it counting."""
    words, stale = freshness(ts, now)
    return (f'<span class="apx-age{" old" if stale else ""}" data-ts="{int(ts) if ts else 0}">{esc(words)}</span>')


def mc(x):
    """Market cap / USD short, as everywhere on this page: $82.0k, $1.25M."""
    return pt._usd_short(x) if x else "–"


def level(text, base_mc, kind):
    """(pct, mc) of a TP / SL text ("30%", "-60%", "$200k") against the average entry MC; (None, None) when it
    cannot be read. Uses league/auto.parse_level, the rule the exits themselves use."""
    from league import auto
    if not text or not base_mc:
        return None, None
    try:
        px, _lab = auto.parse_level(str(text), 1.0, float(base_mc), kind)
    except (ValueError, TypeError):
        return None, None
    if px is None:
        return None, None
    return round((px - 1) * 100, 2), round(px * float(base_mc), 2)


def src_kind(reason):
    """manual / auto / paper of a position's source (pravitrade._who words)."""
    w = pt._who(reason) or ""
    if w == "ručno" or str(reason or "").startswith("ručno"):
        return "ručno"
    if w == "demo strategija" or str(reason or "").startswith("paper"):
        return "paper"
    return "auto"


def ev_per_min(p):
    """EV per minute of a proposal: its EV % over the minutes the trade is expected to take (the exit's time stop,
    else the exit plan's, else 60 min). None without an EV."""
    ev = p.get("ev_pct")
    if ev is None:
        return None
    r = p.get("row") or {}
    t = (r.get("exits_mcap") or {}).get("time_min")
    ts = (r.get("exit_plan") or {}).get("time_stop")
    if not t and isinstance(ts, dict):
        t = ts.get("after_min")
    try:
        t = float(t) if t else 60.0
    except (TypeError, ValueError):
        t = 60.0
    return round(float(ev) / max(1.0, t), 4)


def empty_meta(html):
    """True when a settings section's one-line summary says it has nothing ("0 …", "nema …", "isključen"): such a
    section goes grey to the bottom of "Postavke i dijagnostika"."""
    m = re.search(r'<div class="ms-s">(.*?)</div>', html or "", re.S)
    meta = re.sub(r"<[^>]+>", "", m.group(1)).strip().lower() if m else ""
    return bool(re.match(r"^(0\b|0 |nema\b|još nema|isključen|ništa|ugašen)", meta))


# ---------- reads ---------------------------------------------------------------------------------------------------

def can_view(user):
    tcon = pt._tcon()
    try:
        return settings.can_view(tcon, user)
    finally:
        tcon.close()


def _peek_live(tokens, now):
    """{mint: live dict}, (oldest data time) from the shared DexScreener cache of ui/pravitrade WITHOUT a request:
    the page never waits for DexScreener; the set is marked wanted so the refresher (or the first tick) fills it."""
    out, ts = {}, None
    toks = [t for t in tokens if t]
    if not toks:
        return out, ts
    key = tuple(sorted(set(toks)))
    with pt._LOCK:
        pt._LIVE_WANT[key] = now
        slots = sorted(pt._LIVE_CACHE.items(), key=lambda kv: -kv[1][0])
    for t in toks:
        for _k, (sts, data) in slots:
            if t in (data or {}) and now - sts < 120:
                out[t] = data[t]
                ts = sts if ts is None else min(ts, sts)
                break
    try:
        pt._bg_start()
    except Exception:  # noqa: BLE001
        pass
    return out, ts


def _rug(mint, mcap=None, liq=None, now=None):
    """{'level': 'rug' | 'oprez' | 'ok' | '', 'text'} of a token: collapsed from its peak (rugfilter.collapse, the
    check the manual buy uses), else the newest rug report's verdict. Cached 120 s per token."""
    now = now or time.time()
    with _LOCK:
        hit = _RUG.get(mint)
    if hit and now - hit[0] < 120:
        return hit[1]
    st = {"level": "", "text": "rug: nije provjeren"}
    try:
        from rugfilter import collapse
        from ui import data
        col = collapse.check(collapse.peaks(data.HYPE_DB, [mint]).get(mint), mcap, liq) if mcap else None
        if col:
            st = {"level": "rug", "text": f"rug: {col['text']}"}
        else:
            rows = data.rug_reports(mint)
            v = ((rows[0].get("verdict") if rows else "") or "").upper()
            if v == "PROLAZI":
                st = {"level": "ok", "text": "rug: prolazi"}
            elif v:
                st = {"level": "oprez", "text": f"rug: {v.lower()}"}
    except Exception:  # noqa: BLE001 - no rug data: the badge says so
        pass
    with _LOCK:
        _RUG[mint] = (now, st)
        if len(_RUG) > 200:
            for k in sorted(_RUG, key=lambda k: _RUG[k][0])[:100]:
                _RUG.pop(k, None)
    return st


def _plans(tokens):
    """{token: trailing dict} of the active exit plans (league/exitplan), read-only; {} on any trouble."""
    if not tokens:
        return {}
    lg = pt._league_ro()
    if lg is None:
        return {}
    try:
        lg.row_factory = sqlite3.Row
        q = ",".join("?" * len(tokens))
        out = {}
        for r in lg.execute(f"SELECT token, plan FROM exit_plans WHERE status='active' AND token IN ({q}) ORDER BY id",
                            list(tokens)):
            try:
                tr = (json.loads(r["plan"]) or {}).get("trailing")
            except ValueError:
                tr = None
            if tr:
                out[r["token"]] = tr
        return out
    except sqlite3.Error:
        return {}
    finally:
        lg.close()


def _notes(tcon, ids, toks):
    """The assistant's newest review / opinion per position and per token (ui/assistnotes, advice only); {} on trouble."""
    try:
        from ui import assistnotes
        return assistnotes.latest_for(tcon, ids, toks)
    except Exception:  # noqa: BLE001 - the rows render without the notes
        return {}


def _slim(nt):
    return {k: nt.get(k) for k in ("verdict", "confidence", "interpretation")} if nt else None


def _note_html(nt):
    """One line under a row: "Grok: dobar · sigurnost 80 % · Lijep TP"."""
    if not nt:
        return ""
    conf = f' · sigurnost {nt["confidence"] * 100:.0f} %' if nt.get("confidence") is not None else ""
    return (f'<div class=apx-gnote>Grok: {esc(nt.get("verdict") or "bilješka")}{conf}'
            + (f' · {esc(nt.get("interpretation") or "")}' if nt.get("interpretation") else "") + '</div>')


def positions_data(tcon, cfg, now=None, live=None):
    """Open positions, one row per token and mode (live and paper apart), live first: lots, stake, how much is
    held, the average entry MC (SOL-weighted, as ui/pravitrade._lot_group), MC now, PnL % and an estimate in SOL,
    the exit (TP / SL as % and MC, trailing), the source and a pending sale."""
    now = now or time.time()
    rows = tcon.execute("SELECT id, token, symbol, opened_ts, mode, reason, sol_in, sol_back, qty_raw, qty_left, "
                        "league_id FROM positions WHERE status='open' ORDER BY id").fetchall()
    if not rows:
        return []
    groups = {}
    for r in rows:
        groups.setdefault((r[1], r[4] or "dry"), []).append(r)
    demo = pt._demo_sides(r[10] for r in rows)
    if live is None:
        live, _ts = _peek_live([k[0] for k in groups], now)
    pending = (cfg or {}).get("sell_req") or {}
    trails = _plans(sorted({k[0] for k in groups}))
    notes = _notes(tcon, [r[0] for r in rows], {r[1] for r in rows})
    out = []
    for (tok, mode), lots in groups.items():
        ids = [r[0] for r in lots]
        mcs, rule = [], None
        lot_rows = []
        for (pid, _t, _s, ts, _m, why, sin, sback, q, ql, lid) in lots:
            lmc, lrule, lopen = demo.get(lid, (None, None, False))
            mcs.append((lmc, sin or 0))
            if lrule and lopen and rule is None:
                rule = lrule
            held = (ql / q) if q else 1.0
            lot_rows.append([round(sin or 0, 6), round(held, 4), lmc, round(sback or 0, 6)])
        wsum = sum(w for m, w in mcs if m and w)
        avg = wsum / sum(w / m for m, w in mcs if m and w) if wsum else None
        lv = (live or {}).get(tok) or {}
        mc_now = lv.get("mcap") or None
        pnl_pct = (mc_now / avg - 1) * 100 if avg and mc_now else None
        pnl_sol = _pnl_sol(lot_rows, mc_now, avg)
        tp_txt = sl_txt = ""
        if rule and rule.get("mode") == "tpsl":
            tp_txt = rule.get("tp_in") or rule.get("tp") or ""
            sl_txt = rule.get("sl_in") or rule.get("sl") or ""
        g = (rule or {}).get("grp") or {}
        tp_txt, sl_txt = g.get("tp", tp_txt) or tp_txt, g.get("sl", sl_txt) or sl_txt
        tp_pct, tp_mc = level(tp_txt, avg, "tp")
        sl_pct, sl_mc = level(sl_txt, avg, "sl")
        pend = next((pending.get(str(i)) for i in ids if pending.get(str(i)) is not None), None)
        sin_all = sum(r[6] or 0 for r in lots)
        q_all, ql_all = sum(r[8] or 0 for r in lots), sum(r[9] or 0 for r in lots)
        first = lots[0]
        out.append({"key": f"{tok}:{mode}", "token": tok, "sym": first[2] or short(tok or ""), "mode": mode,
                    "paper": mode != "live", "ids": ids, "pid": ids[0], "lots": lot_rows, "n_lots": len(lots),
                    "sol_in": round(sin_all, 6), "held": round(ql_all / q_all, 4) if q_all else 1.0,
                    "avg_mc": round(avg, 2) if avg else None, "mc_now": mc_now,
                    "pnl_pct": round(pnl_pct, 3) if pnl_pct is not None else None,
                    "pnl_sol": round(pnl_sol, 6) if pnl_sol is not None else None,
                    "exit": pt._exit_words(rule), "smart": bool(rule and rule.get("mode") == "smart"),
                    "tp": tp_txt, "tp_pct": tp_pct, "tp_mc": tp_mc, "sl": sl_txt, "sl_pct": sl_pct, "sl_mc": sl_mc,
                    "trail": trails.get(tok), "src": src_kind(first[5]), "who": pt._who(first[5]) or "",
                    "opened_ts": max(r[3] or 0 for r in lots), "pending": pend, "has_demo": bool(first[10]),
                    "note": _slim(next((notes[("p", i)] for i in ids if ("p", i) in notes), None) or notes.get(("t", tok))),
                    "rule": rule})
    out.sort(key=lambda p: (p["paper"], -(p["opened_ts"] or 0)))
    return out


def _pnl_sol(lots, mc_now, avg):
    """Estimated PnL in SOL of a position: every lot's held part at MC now against its entry MC (the average when
    the lot has none), plus what came back, minus what went in. No fees; None without a price."""
    if not mc_now or not avg:
        return None
    tot = 0.0
    for sin, held, lmc, sback in lots:
        base = lmc or avg
        tot += sin * held * (mc_now / base) + sback - sin
    return tot


def orders_data(tcon, cfg, positions):
    """Every open order: the owner's DCA orders and buy orders at a market cap (with their cancel routes), the
    positions' TP / SL / trailing triggers and pending sales (changed on the position: "Uredi SL-TP")."""
    st = settings.raw(tcon)
    syms = {p["token"]: p["sym"] for p in positions}
    out = []
    for o in st.get("dca_orders") or []:
        out.append({"kind": "dca", "word": "DCA dokup", "id": str(o.get("id")), "token": o.get("token"),
                    "sym": o.get("sym") or syms.get(o.get("token")) or short(o.get("token") or ""), "mc": o.get("mc"),
                    "sol": o.get("sol"), "status": "čeka", "cancel": "/pravi-trade/dcadel"})
    for o in (cfg or {}).get("buy_orders") or st.get("buy_orders") or []:
        ex = (o.get("exit") or "tpsl")
        out.append({"kind": "limit", "word": "Limit kupnja", "id": str(o.get("id")), "token": o.get("token"),
                    "sym": o.get("sym") or short(o.get("token") or ""), "mc": o.get("mc"), "sol": o.get("sol"),
                    "status": "čeka do " + time.strftime("%d.%m. %H:%M", time.localtime(o.get("until") or 0)),
                    "note": (f"TP {o.get('tp') or 'zadani'} · SL {o.get('sl') or pt._sl0(cfg)}" if ex == "tpsl" else ex),
                    "cancel": "/pravi-trade/limitdel"})
    for p in positions:
        if p.get("tp_mc"):
            out.append({"kind": "tp", "word": "TP", "token": p["token"], "sym": p["sym"], "mc": p["tp_mc"],
                        "pct": p["tp_pct"], "status": "aktivan", "pid": p["pid"], "paper": p["paper"]})
        if p.get("sl_mc"):
            out.append({"kind": "sl", "word": "SL", "token": p["token"], "sym": p["sym"], "mc": p["sl_mc"],
                        "pct": p["sl_pct"], "status": "aktivan", "pid": p["pid"], "paper": p["paper"]})
        if p.get("trail"):
            tr = p["trail"]
            out.append({"kind": "trail", "word": "Trailing", "token": p["token"], "sym": p["sym"], "mc": None,
                        "pct": tr.get("trail_pct"), "status": f"od +{tr.get('activate_pct')} %", "pid": p["pid"],
                        "paper": p["paper"]})
        if p.get("smart"):
            out.append({"kind": "smart", "word": "Smart sell", "token": p["token"], "sym": p["sym"], "mc": None,
                        "status": "aktivan", "pid": p["pid"], "paper": p["paper"]})
        if p.get("pending") is not None:
            out.append({"kind": "sell", "word": "Prodaja", "token": p["token"], "sym": p["sym"], "mc": None,
                        "pct": round(float(p["pending"]) * 100), "status": "u tijeku", "pid": p["pid"],
                        "paper": p["paper"]})
    return out


def header_data(mint, live_row, now=None, data_ts=None, sym=None):
    """The header above the chart: symbol, MC, price, 5m/1h/24h, liquidity, 1h volume, buys/sells 5m, rug badge."""
    if not mint:
        return None
    lv = live_row or {}
    w5 = (lv.get("w") or {}).get("m5") or {}
    b, s = w5.get("buys"), w5.get("sells")
    return {"mint": mint, "sym": lv.get("symbol") or sym or short(mint), "mcap": lv.get("mcap"), "price": lv.get("price"),
            "ch_m5": lv.get("ch_m5"), "ch_h1": lv.get("ch_h1"), "ch_h24": lv.get("ch_h24"), "liq": lv.get("liq"),
            "vol_h1": lv.get("vol_h1"), "buys_m5": b, "sells_m5": s,
            "bs_m5": round(b / s, 2) if b is not None and s else None,
            "rug": _rug(mint, lv.get("mcap"), lv.get("liq"), now) if lv else {"level": "", "text": "rug: čekam cijenu"},
            "ts": int(data_ts) if data_ts else None}


def _sol_usd(tcon):
    """SOL in USD for the cost estimate: the header's rate (trade/equity.rates through ui/pravitrade), else the last
    SOL price trade/equity read even when the EUR rate is missing (its 60-s cache; no request here)."""
    try:
        v = pt._rates(pt.equity_data(tcon)["summary"]).get("sol_usd")
        if v:
            return v
        eq = pt._equity_mod()
        return (getattr(eq, "_RATES", None) or {}).get("sol") if eq is not None else None
    except Exception:  # noqa: BLE001
        return None


def panel_data(tcon, cfg, owner, now=None):
    """The panel's numbers: wallet SOL, today's automatic spend against the day limit, the limits, the defaults the
    forms prefill (last TP / SL used), the fee and the SOL rate for the cost estimate."""
    now = now or time.time()
    mode = "live" if executor.is_live(cfg) else "dry"
    try:
        spent = executor.auto_spent(tcon, now, mode, cfg.get("day_tz"))
    except Exception:  # noqa: BLE001
        spent = None
    bal = val = None
    try:
        s = pt.equity_data(tcon, now)["summary"]
        bal = s.get("sol") if s.get("value_sol") is not None else None
        val = s.get("value_sol")
    except Exception:  # noqa: BLE001
        s = {}
    if bal is None:
        bal = pt._balance(pt._addr(tcon)[0])   # 60-s cache; the same read the header made before
    from trade import cost
    try:
        fee = cost.fee_side()   # the calibrated per-side fee (cached 10 min per trade.db)
    except Exception:  # noqa: BLE001
        fee = cost.FEE_DEMO
    tp_last, sl_last = pt._last_exit(cfg)
    lo, hi = settings.LIMITS["size_sol"][2:4]
    return {"balance_sol": bal, "value_sol": val, "auto_today": round(spent, 4) if spent is not None else None,
            "max_day": cfg.get("max_sol_per_day"), "size_sol": cfg.get("size_sol"),
            "max_trade": cfg.get("max_sol_per_trade"), "sol_lo": lo, "sol_hi": hi, "tp_last": tp_last,
            "sl_last": sl_last, "sl_default": pt._sl0(cfg), "fee_side": fee, "slip_max": cost.SLIP_MAX,
            "sol_usd": _sol_usd(tcon),
            "max_cost_pct": cfg.get("max_cost_pct"), "live": mode == "live", "on": bool(cfg.get("on")),
            "dca_cap": cfg.get("dca_token_cap", settings.DCA_TOKEN_CAP)}


def _pick(positions, qs_m):
    """The token the chart opens on: ?m= when it is a mint, else the newest live position, else any position."""
    m = (qs_m or "").strip()
    if MINT.fullmatch(m):
        return m
    return positions[0]["token"] if positions else ""


def _sig(positions, orders):
    """What the tables show, in one short string: a tick whose sig differs makes the browser fetch the tables again."""
    a = ",".join(f'{p["key"]}:{"-".join(map(str, p["ids"]))}:{p["pending"]}:{p["tp"]}:{p["sl"]}' for p in positions)
    b = ",".join(f'{o["kind"]}:{o.get("id") or o.get("pid")}' for o in orders)
    return hashlib.sha1(f"{a}|{b}".encode()).hexdigest()[:12]


def first_view(user, mint="", now=None, fresh=False):
    """The aggregated first view (GET /pravi-trade/api/first and the data the page renders): positions, orders,
    the selected token's header, the panel's numbers. Read-only; cached FIRST_TTL_S per (owner, token).
    None when the user may not see the Autopilot."""
    now = now or time.time()
    tcon = pt._tcon()
    try:
        if not settings.can_view(tcon, user):
            return None
        owner = settings.is_owner(user)
        key = (settings.DB, owner, mint or "")
        with _LOCK:
            hit = _FIRST.get(key)
        if hit and not fresh and now - hit[0] < FIRST_TTL_S:
            return hit[1]
        cfg = pt._cfg(tcon)
        pos0 = tcon.execute("SELECT DISTINCT token FROM positions WHERE status='open'").fetchall()
        sel = mint if MINT.fullmatch(mint or "") else ""
        live, live_ts = _peek_live([r[0] for r in pos0] + ([sel] if sel else []), now)
        positions = pt._safe("pozicije", positions_data, tcon, cfg, now, live, fallback=[])
        sel = _pick(positions, mint)
        if sel and sel not in live:
            more, mts = _peek_live([sel], now)
            live.update(more)
            live_ts = mts if live_ts is None else (min(live_ts, mts) if mts else live_ts)
        orders = pt._safe("nalozi", orders_data, tcon, cfg, positions, fallback=[])
        sym = next((p["sym"] for p in positions if p["token"] == sel), None)
        d = {"v": 1, "ts": int(now), "owner": owner, "on": bool(cfg.get("on")), "live": executor.is_live(cfg),
             "m": sel, "data_ts": int(live_ts) if live_ts else None,
             "positions": [{k: v for k, v in p.items() if k != "rule"} for p in positions], "orders": orders,
             "header": pt._safe("zaglavlje", header_data, sel, live.get(sel), now, live_ts, sym, fallback=None),
             "panel": pt._safe("panel", panel_data, tcon, cfg, owner, now, fallback={}),
             "sig": _sig(positions, orders), "_cfg": cfg, "_rules": {p["key"]: p.get("rule") for p in positions}}
        with _LOCK:
            _FIRST[key] = (now, d)
            if len(_FIRST) > 32:
                for k in sorted(_FIRST, key=lambda k: _FIRST[k][0])[:16]:
                    _FIRST.pop(k, None)
        return d
    finally:
        tcon.close()


def first_json(user, mint="", with_html=False):
    """The JSON of GET /pravi-trade/api/first (private keys dropped); with_html adds the tables' HTML, so the browser
    swaps them in one request when a tick says they changed."""
    d = first_view(user, mint)
    if d is None:
        return None
    out = {k: v for k, v in d.items() if not k.startswith("_")}
    if with_html:
        sel_pos = next((p for p in d["positions"] if p["token"] == d.get("m")), None)
        out["html"] = {"pos": positions_html(d), "ord": orders_html(d), "hdr": _hdr_html(d.get("header"), time.time()),
                       "side": panel_html(d, sel_pos)}
    return json.dumps(out, ensure_ascii=False, separators=(",", ":"), default=str)


# ---------- the shared live tick and the SSE stream ---------------------------------------------------------------

def want(mint, now=None):
    if mint and MINT.fullmatch(mint):
        with _LOCK:
            _WANT[mint] = now or time.time()


def tick(mint="", now=None):
    """One live state for every viewer, at most every TICK_S: {ts, data_ts, sig, tok: {mint: numbers}}. The tokens
    are the open positions plus up to WANT_MAX tokens viewers looked at in the last WANT_TTL_S; the numbers come from
    ui/pravitrade's shared DexScreener cache (its refresher renews them; one request per token set). Each stream
    only formats this dict, nothing is fetched per viewer."""
    now = now or time.time()
    want(mint, now)
    with _LOCK:
        cur = _TICK["val"]
        if (cur is not None and now - _TICK["ts"] < TICK_S and _TICK.get("db") == settings.DB
                and (not mint or mint in _TICK.get("toks", ()) or not MINT.fullmatch(mint))):
            return cur
        for k in [k for k, ts in _WANT.items() if now - ts > WANT_TTL_S]:
            _WANT.pop(k, None)
        wanted = [k for k, _ts in sorted(_WANT.items(), key=lambda kv: -kv[1])[:WANT_MAX]]
    tcon = pt._tcon()
    try:
        rows = tcon.execute("SELECT id, token FROM positions WHERE status IN ('open','pending') ORDER BY id").fetchall()
        st = settings.raw(tcon)
    finally:
        tcon.close()
    toks = sorted({r[1] for r in rows} | set(wanted))
    live, data_ts = {}, None
    if toks:
        try:
            live = pt._live_cached(tuple(toks), now) or {}
        except Exception:  # noqa: BLE001 - the tick goes out without numbers; the badge then turns yellow
            live = {}
        with pt._LOCK:
            hit = pt._LIVE_CACHE.get(tuple(toks))
        data_ts = hit[0] if hit and live else None
    keep = ("mcap", "price", "liq", "vol_h1", "ch_m5", "ch_h1", "ch_h24")
    tok = {}
    for t in toks:
        lv = live.get(t)
        if not lv:
            continue
        w5 = (lv.get("w") or {}).get("m5") or {}
        tok[t] = {**{k: lv.get(k) for k in keep}, "buys_m5": w5.get("buys"), "sells_m5": w5.get("sells")}
    sig_src = (",".join(str(r[0]) for r in rows) + "|" + json.dumps(st.get("sell_req") or {}, sort_keys=True) + "|"
               + str(len(st.get("dca_orders") or [])) + "|" + str(len(st.get("buy_orders") or [])))
    val = {"ts": int(now), "data_ts": int(data_ts) if data_ts else None, "tok": tok,
           "sig": hashlib.sha1(sig_src.encode()).hexdigest()[:12]}
    with _LOCK:
        _TICK.update(ts=now, val=val, toks=set(toks), db=settings.DB)
    return val


def reset():
    """Forget every cache of this module (tests; a deploy starts empty anyway)."""
    with _LOCK:
        _FIRST.clear()
        _TICK.update(ts=0.0, val=None, toks=set(), db=None)
        _WANT.clear()
        _CANDLES.clear()
        _RUG.clear()


def tick_json(user, mint=""):
    if not can_view(user):
        return None
    return json.dumps(tick(mint), separators=(",", ":"))


STREAM_HEADERS = (("Content-Type", "text/event-stream; charset=utf-8"), ("Cache-Control", "no-store"),
                  ("X-Accel-Buffering", "no"), ("Connection", "close"))


def stream_slot():
    """A free SSE slot (True) or False when STREAM_MAX streams are open (the browser then polls every POLL_S)."""
    return _STREAMS.acquire(blocking=False)


def stream_release():
    try:
        _STREAMS.release()
    except ValueError:
        pass


def stream(mint="", clock=time.time, sleep=time.sleep, max_s=None, every=None, hb_s=None, tick_fn=None):
    """The SSE body as bytes chunks: a retry hint, then an event "tick" whenever the shared tick changed (checked
    every `every` s), an event "hb" after hb_s s of no change, and "bye" after max_s s (EventSource reconnects).
    Nothing is computed here per viewer: tick() is shared."""
    max_s = STREAM_MAX_S if max_s is None else max_s
    every = TICK_S if every is None else every
    hb_s = STREAM_HB_S if hb_s is None else hb_s
    tick_fn = tick_fn or tick
    t0 = clock()
    yield f"retry: {POLL_S * 1000}\n\n".encode()
    last, last_out = None, t0
    while clock() - t0 < max_s:
        try:
            t = tick_fn(mint)
        except Exception as e:  # noqa: BLE001 - a locked database: the stream lives on, the badge turns yellow
            print(f"autopilot: tick nije složen: {type(e).__name__}: {e}", flush=True)
            t = {"ts": int(clock()), "data_ts": None, "tok": {}, "sig": None, "err": 1}
        body = {k: v for k, v in t.items() if k != "ts"}
        sig = json.dumps(body, sort_keys=True, separators=(",", ":"))
        now = clock()
        if sig != last:
            last, last_out = sig, now
            yield f"event: tick\ndata: {json.dumps(t, separators=(',', ':'))}\n\n".encode()
        elif now - last_out >= hb_s:
            last_out = now
            yield f"event: hb\ndata: {int(now)}\n\n".encode()
        sleep(every)
    yield b"event: bye\ndata: {}\n\n"


# ---------- candles for the chart ---------------------------------------------------------------------------------

def _series(mint, hours, now):
    """(minute candles, latest snapshot) of a token from the data we already store (rangedca.data: range.db snaps
    and GeckoTerminal candles, hype.db token_pulse, minute.db call candles). Read-only, no request; cached."""
    key = (mint, hours)
    with _LOCK:
        hit = _CANDLES.get(key)
    if hit and now - hit[0] < CANDLE_TTL_S:
        return hit[1], hit[2]
    from rangedca import data as rdata
    t0 = int(now - hours * 3600) - 120
    con = rdata.ro()
    try:
        snaps = (rdata.own_rows(con, mint, t0) if con is not None else []) + rdata.pulse_rows(mint, t0)
        true = (rdata.gt_rows(con, mint, t0, now) if con is not None else []) + rdata.call_candles(mint, t0, now)
    except sqlite3.Error:
        snaps, true = [], []
    finally:
        if con is not None:
            con.close()
    cs = rdata.merge(true, snaps)
    snap = max(snaps, key=lambda s: s["ts"]) if snaps else None
    with _LOCK:
        _CANDLES[key] = (now, cs, snap)
        if len(_CANDLES) > CANDLE_KEEP:
            for k in sorted(_CANDLES, key=lambda k: _CANDLES[k][0])[:len(_CANDLES) - CANDLE_KEEP]:
                _CANDLES.pop(k, None)
    return cs, snap


def bucket(candles, step, mult=1.0):
    """Minute candles [(ts, o, h, l, c, ...)] -> [{time, open, high, low, close}] in buckets of `step` seconds,
    every value x mult (the supply for market cap)."""
    out = []
    for c in candles:
        t = int(c[0]) - int(c[0]) % step
        o, h, lo, cl = (float(c[1]) * mult, float(c[2]) * mult, float(c[3]) * mult, float(c[4]) * mult)
        if out and out[-1]["time"] == t:
            b = out[-1]
            b["high"], b["low"], b["close"] = max(b["high"], h), min(b["low"], lo), cl
        else:
            out.append({"time": t, "open": o, "high": h, "low": lo, "close": cl})
    return out


def _zones(mint):
    """The rangedca zones of the token as MC bands (bottom, DCA under it, top) with the time they were computed."""
    try:
        from rangedca import data as rdata, rules
        r = rdata.read_ranges(tokens=[mint]).get(mint)
    except Exception:  # noqa: BLE001
        return None
    if not r or not r.get("zones"):
        return None
    z = r["zones"]
    m = z.get("mc") or {}
    sup = (r.get("metrics") or {}).get("supply")

    def v(k):
        return m.get(k) or (z.get(k) * sup if sup and z.get(k) else None)
    rll, rlt, rhl, rht = v("range_low_low"), v("range_low_top"), v("range_high_low"), v("range_high_top")
    bands = []
    if rll and rlt:
        bands.append({"kind": "bottom", "lo": rll, "hi": rlt, "label": "dno"})
        bands.append({"kind": "dca", "lo": rll * rules.RULES["floor_x"], "hi": rll, "label": "DCA"})
    if rhl and rht:
        bands.append({"kind": "top", "lo": rhl, "hi": rht, "label": "vrh"})
    return {"computed_ts": r.get("ts"), "status": r.get("status"), "active": bool(r.get("active")), "bands": bands,
            "supply": sup}


def candles_data(user, mint, tf="5m", unit="mc", now=None):
    """GET /pravi-trade/api/candles: candles, the lines (average entry, DCA orders, SL, TP) and the zones of one
    token, in market cap (unit=mc) or price. None without access; candles [] when we store nothing for it."""
    now = now or time.time()
    if not MINT.fullmatch(mint or ""):
        return {"error": "nije adresa tokena"}
    fv = first_view(user, mint, now)
    if fv is None:
        return None
    step, hours = TFS.get(tf, TFS["5m"])
    cs, snap = _series(mint, hours, now)
    hdr = fv.get("header") or {}
    supply = None
    if hdr.get("mcap") and hdr.get("price"):
        supply = hdr["mcap"] / hdr["price"]
    elif snap and snap.get("mcap") and snap.get("price"):
        supply = snap["mcap"] / snap["price"]
    zones = _zones(mint)
    if not supply and zones and zones.get("supply"):
        supply = zones["supply"]
    unit = "mc" if unit == "mc" and supply else "price"
    mult = supply if unit == "mc" else 1.0
    out = bucket(cs, step, mult)
    conv = (lambda x: x) if unit == "mc" else (lambda x: x / supply if x and supply else None)
    lines = []
    for p in fv["positions"]:
        if p["token"] != mint:
            continue
        tag = " (paper)" if p["paper"] else ""
        if p.get("avg_mc"):
            lines.append({"kind": "entry", "value": conv(p["avg_mc"]), "label": "Ulaz" + tag})
        if p.get("sl_mc"):
            lines.append({"kind": "sl", "value": conv(p["sl_mc"]), "label": "SL" + tag})
        if p.get("tp_mc"):
            lines.append({"kind": "tp", "value": conv(p["tp_mc"]), "label": "TP" + tag})
    for o in fv["orders"]:
        if o.get("token") == mint and o["kind"] in ("dca", "limit") and o.get("mc"):
            lines.append({"kind": "dca" if o["kind"] == "dca" else "limit", "value": conv(o["mc"]),
                          "label": "DCA" if o["kind"] == "dca" else "Limit"})
    zones_mc = zones
    if zones:
        zones = {**zones, "bands": [{**b, "lo": conv(b["lo"]), "hi": conv(b["hi"])} for b in zones["bands"]]}
    return {"mint": mint, "tf": tf if tf in TFS else "5m", "unit": unit, "ts": int(now),
            "data_ts": int(cs[-1][0]) if cs else None, "candles": out[-2000:], "supply": supply,
            "lines": [ln for ln in lines if ln["value"]], "zones": zones, "zones_mc": zones_mc}


# ---------- HTML of the first view -------------------------------------------------------------------------------

BADGE_PAPER = '<span class="apx-badge paper">paper</span>'
BADGE_LIVE = '<span class="apx-badge live">uživo</span>'


def _pct(x, dec=1):
    return redak.pct(x, dec) if x is not None else "–"


def _tone(x):
    return "up" if (x or 0) > 0 else "dn" if (x or 0) < 0 else ""


def _sel_btn(tok, sym, cls="apx-tok"):
    return (f'<button type=button class={cls} data-sel="{esc(tok)}" title="Prikaži na grafu" translate=no>'
            f'{esc(sym)}</button>')


def positions_html(d):
    """Pozicije: one row per position (a table on a desktop, a card on a phone), live first, paper grey under a
    divider; the owner's Zatvori 50 % / 100 % (the sell request route) and Uredi SL-TP (the exit route and DCA)."""
    owner, cfg = d["owner"], d.get("_cfg") or {}
    rows = d["positions"]
    rules = d.get("_rules") or {}
    head = ('<div class="apx-tr apx-th" aria-hidden=true><span>Token</span><span class=n>Veličina</span>'
            '<span class=n>Ulaz (MC)</span><span class=n>Sada (MC)</span><span class=n>PnL</span><span class=n>SL</span>'
            '<span class=n>TP</span><span>Izvor</span></div>')
    if not rows:
        body = ('<p class=apx-empty>Nema otvorenih pozicija. Kupi u panelu desno (na mobitelu gumb Kupi dolje) ili '
                'zaprati nekoga pod „Koga pratimo”.</p>')
        return f'<div class=apx-tbl data-n=0>{body}</div>' + (pt.SELL_ALL if owner and cfg.get("on") else "")
    out, paper_seen = [], False
    for p in rows:
        if p["paper"] and not paper_seen:
            paper_seen = True
            out.append('<div class=apx-div>Probno (paper): bez pravog novca</div>')
        out.append(_pos_row(p, owner, cfg, rules.get(p["key"])))
    tail = pt.SELL_ALL if owner and (cfg.get("on") or rows) else ""
    return f'<div class=apx-tbl data-n={len(rows)}>{head}{"".join(out)}</div>{tail}'


def _pos_row(p, owner, cfg, rule):
    tok, ids = p["token"], ",".join(map(str, p["ids"]))
    badge = ('<span class="apx-badge paper">paper</span>' if p["paper"] else '<span class="apx-badge live">uživo</span>')
    size = redak.sol(p["sol_in"], 3) + (f' · {p["n_lots"]} ulaza' if p["n_lots"] > 1 else "")
    if p["held"] < 0.999:
        size += f" · drži {redak.pct(p['held'], sign=False, frac=True)}"
    pnl = (f'{_pct(p["pnl_pct"])}<small>{redak.sol(p["pnl_sol"], 4, sign=True) if p["pnl_sol"] is not None else ""}</small>'
           if p["pnl_pct"] is not None else '<span class=apx-sk>čekam cijenu</span>')
    sl = (f'{_pct(p["sl_pct"], 0)}<small>{mc(p["sl_mc"])}</small>' if p["sl_mc"]
          else ('<span class=apx-mut title="Smart sell: alat sam bira izlaz">Smart</span>' if p["smart"] else "–"))
    tp = (f'{_pct(p["tp_pct"], 0)}<small>{mc(p["tp_mc"])}</small>' if p["tp_mc"] else "–")
    if p.get("trail"):
        tp += f'<small>trailing {esc(str(p["trail"].get("trail_pct")))} %</small>'
    src = esc(p["src"]) + (f'<small>{esc(p["who"])}</small>' if p["who"] and p["who"] != p["src"] else "")
    act = ""
    edit = ""
    if owner:
        if p["pending"] is not None:
            act = f'<span class=apx-mut>prodaja {redak.pct(p["pending"], sign=False, frac=True)} u tijeku</span>'
        else:
            act = "".join(
                f'<form method=post action=/pravi-trade/sell onsubmit="return confirm(\'Zatvoriti {lab} pozicije '
                f'{esc(p["sym"])} odmah?\')"><input type=hidden name=id value="{ids}"><input type=hidden name=frac '
                f'value={fr}><button class="apx-b sell{" full" if fr == "1" else ""}">Zatvori {lab}</button></form>'
                for fr, lab in (("0.5", "50 %"), ("1", "100 %")))
            if p["has_demo"]:
                act += f'<button type=button class=apx-b data-edit="ed-{p["pid"]}">Uredi SL-TP</button>'
                lv = pt._dca_block(tok, p["sym"], [], [], cfg, p["avg_mc"], p["mc_now"])
                edit = (f'<div class=apx-edit id=ed-{p["pid"]} hidden><div><h4>SL / TP</h4>{pt._exit_form(p["pid"], rule, cfg)}'
                        f'</div><div><h4>DCA dokup</h4>{lv}</div></div>')
    pnl_cls = _tone(p["pnl_pct"])
    return (f'<div class="apx-tr apx-pos{" is-paper" if p["paper"] else ""}" id=poz-{p["pid"]} data-key="{esc(p["key"])}" '
            f'data-tok="{esc(tok)}">'
            f'<span class=apx-c-tok data-l="Token">{_sel_btn(tok, p["sym"])}{badge}</span>'
            f'<span class=n data-l="Veličina">{size}</span>'
            f'<span class=n data-l="Ulaz (MC)">{mc(p["avg_mc"])}</span>'
            f'<span class=n data-l="Sada (MC)" data-f=mc>{mc(p["mc_now"])}</span>'
            f'<span class="n apx-pnl {pnl_cls}" data-l="PnL" data-f=pnl>{pnl}</span>'
            f'<span class="n dn" data-l="SL">{sl}</span><span class="n up" data-l="TP">{tp}</span>'
            f'<span data-l="Izvor">{src}</span>{_note_html(p.get("note"))}<span class=apx-act>{act}</span>{edit}</div>')


def orders_html(d):
    """Otvoreni nalozi: DCA and buy orders (Otkaži = the routes they always had), the positions' triggers."""
    owner = d["owner"]
    rows = d["orders"]
    if not rows:
        return '<div class=apx-tbl data-n=0><p class=apx-empty>Nema otvorenih naloga.</p></div>'
    head = ('<div class="apx-tr apx-th apx-ord" aria-hidden=true><span>Token</span><span>Vrsta</span><span class=n>Razina</span>'
            '<span class=n>Iznos</span><span>Status</span><span></span></div>')
    out = []
    for o in sorted(rows, key=lambda o: (bool(o.get("paper")), o["kind"] not in ("dca", "limit"))):
        cls = {"tp": "up", "sl": "dn", "dca": "", "limit": "", "trail": "up", "sell": "dn"}.get(o["kind"], "")
        lvl = mc(o.get("mc")) if o.get("mc") else "–"
        if o.get("pct") is not None and o["kind"] in ("tp", "sl"):
            lvl = f'{_pct(o["pct"], 0)}<small>{lvl}</small>'
        elif o["kind"] == "trail":
            lvl = f'−{esc(str(o.get("pct")))} %'
        elif o["kind"] == "sell":
            lvl = f'{o.get("pct")} %'
        amt = redak.sol(o["sol"], 3) if o.get("sol") else "–"
        act = ""
        if owner and o.get("cancel"):
            act = (f'<form method=post action={o["cancel"]} onsubmit="return confirm(\'Otkazati ovaj nalog?\')">'
                   f'<input type=hidden name=id value="{esc(o["id"])}"><button class="apx-b sell">Otkaži</button></form>')
        elif owner and o["kind"] in ("tp", "sl", "trail") and o.get("pid"):
            act = f'<button type=button class=apx-b data-edit="ed-{o["pid"]}" data-goto="poz-{o["pid"]}">Uredi</button>'
        note = f'<small>{esc(o["note"])}</small>' if o.get("note") else ""
        paper = '<span class="apx-badge paper">paper</span>' if o.get("paper") else ""
        out.append(f'<div class="apx-tr apx-ord{" is-paper" if o.get("paper") else ""}">'
                   f'<span data-l="Token">{_sel_btn(o["token"] or "", o["sym"] or "")}{paper}</span>'
                   f'<span class={cls} data-l="Vrsta">{esc(o["word"])}</span><span class="n {cls}" data-l="Razina">{lvl}</span>'
                   f'<span class=n data-l="Iznos">{amt}</span><span data-l="Status">{esc(o["status"])}{note}</span>'
                   f'<span class=apx-act>{act}</span></div>')
    return f'<div class=apx-tbl data-n={len(rows)}>{head}{"".join(out)}</div>'


def _hdr_html(h, now):
    """The token header above the chart (numbers carry data-f so a tick only rewrites the text)."""
    if not h:
        return ('<div class=apx-hdr id=apx-hdr><div class=apx-hsym><b>Odaberi token</b></div><p class=apx-mut>Dodirni '
                'poziciju ili upiši adresu tokena u panel: graf, zone i brojevi se otvore ovdje.</p></div>')
    rug = h.get("rug") or {}
    bs = h.get("bs_m5")
    bs_txt = f"{h.get('buys_m5')}/{h.get('sells_m5')} ({redak.num(bs, 2)})" if bs is not None else "–"
    cells = [("MC", f'<b data-f=mcap>{mc(h.get("mcap"))}</b>'),
             ("5 min", f'<b data-f=ch_m5 class={_tone(h.get("ch_m5"))}>{_pct(h.get("ch_m5"))}</b>'),
             ("1 h", f'<b data-f=ch_h1 class={_tone(h.get("ch_h1"))}>{_pct(h.get("ch_h1"))}</b>'),
             ("24 h", f'<b data-f=ch_h24 class={_tone(h.get("ch_h24"))}>{_pct(h.get("ch_h24"))}</b>'),
             ("Likvidnost", f'<b data-f=liq>{mc(h.get("liq"))}</b>'),
             ("Volumen 1 h", f'<b data-f=vol_h1>{mc(h.get("vol_h1"))}</b>'),
             ("Kup./prod. 5 min", f'<b data-f=bs>{esc(bs_txt)}</b>')]
    stats = "".join(f'<div><span>{esc(k)}</span>{v}</div>' for k, v in cells)
    return (f'<div class=apx-hdr id=apx-hdr data-mint="{esc(h["mint"])}"><div class=apx-hsym>'
            f'<b translate=no data-f=sym>{esc(h.get("sym") or short(h["mint"]))}</b>'
            f'<span class="apx-rug {esc(rug.get("level") or "")}" data-f=rug>{esc(rug.get("text") or "")}</span>'
            f'<a class=apx-mut href="https://dexscreener.com/solana/{quote(h["mint"])}" target=_blank rel=noopener>DexScreener ↗</a>'
            f'<span class=apx-sp></span>{age_badge(h.get("ts"), now)}</div><div class=apx-stats>{stats}</div></div>')


def panel_html(d, sel_pos):
    """The order panel (owner): Kupi / Prodaj. Every form posts to the route and fields it always had."""
    pn = d.get("panel") or {}
    owner = d["owner"]
    m = d.get("m") or ""
    h = d.get("header") or {}
    sym = h.get("sym") or (short(m) if m else "")
    bal, val = pn.get("balance_sol"), pn.get("value_sol")
    tot = f'<small>ukupno {redak.sol(val, 3)}</small>' if val is not None and bal is not None and abs(val - bal) > 5e-4 else ""
    wal = (f'<div class=apx-wal><div><span>Wallet</span><b>{redak.sol(bal, 3) if bal is not None else "–"}</b>{tot}</div>'
           f'<div><span>Danas auto</span><b>{redak.num(pn.get("auto_today"), 2)} od {pt._g(pn.get("max_day") or 0)} SOL</b></div>'
           f'<div><span>Limit po tradeu</span><b>{pt._g(pn.get("max_trade") or 0)} SOL</b></div>'
           f'<div class=apx-wal-age>{age_badge(d.get("ts"))}</div></div>')
    head = ('<div class=apx-sheet-h><b>Nalog</b><button type=button class=apx-x data-sheet-close aria-label="Zatvori">'
            '×</button></div>')
    if not owner:
        link = (f'<p><a class="apx-go buy" href="https://jup.ag/swap/SOL-{quote(m)}" target=_blank rel=noopener>'
                f'Kupi i ti {esc(sym)} iz svog walleta (Jupiter) ↗</a></p>' if m else "")
        return (f'<aside class=apx-side id=apx-pregled aria-label="Wallet">{head}{wal}<p class=apx-mut>Trguje samo vlasnik; ti '
                f'vidiš stanje, pozicije i naloge.</p>{link}</aside>')
    quick = "".join(f'<button type=button class=apx-chip data-sol="{v:g}">{pt._g(v)}</button>' for v in QUICK_SOL)
    quick += '<button type=button class=apx-chip data-sol="">vlastito</button>'
    tpc = "".join(f'<button type=button class="apx-chip up" data-tp="{v}%">+{v} %</button>' for v in TP_CHIPS)
    slc = "".join(f'<button type=button class="apx-chip dn" data-sl="-{v}%">−{v} %</button>' for v in SL_CHIPS)
    sol0 = pn.get("size_sol") or 0.1
    tp_last, sl_last = pn.get("tp_last") or "", pn.get("sl_last") or ""
    buy = ('<form method=post action=/pravi-trade/buy class=apx-f id=apx-buy onsubmit="return confirm(\'Kupiti ovaj token pravim '
           'novcem (ako je Autopilot uključen)?\')">'
           f'<label class=apx-fl>Token<input name=token required value="{esc(m)}" placeholder="adresa tokena ili DexScreener link" '
           'autocomplete=off spellcheck=false></label>'
           f'<div class=apx-fl><span>Iznos (SOL)</span><div class=apx-amt><div class=apx-chips>{quick}</div>'
           f'<input name=sol value="{sol0:g}" inputmode=decimal aria-label="Iznos u SOL-u"></div></div>'
           f'<div class=apx-two><label class="apx-fl up">TP<input name=tp value="{esc(tp_last)}" placeholder="npr. 30% ili $200k" '
           'autocomplete=off><small data-hint=tp></small></label>'
           f'<label class="apx-fl dn">SL<input name=sl value="{esc(sl_last)}" placeholder="zadano {esc(pn.get("sl_default") or "")}" '
           'autocomplete=off><small data-hint=sl></small></label></div>'
           f'<div class=apx-chips>{tpc}{slc}</div>'
           '<details class=apx-more><summary>Limit (kupi na MC), trailing i način izlaza</summary>'
           '<label class=apx-fl>Kupi na MC <small>(prazno = odmah; npr. $50k ili -40%)</small>'
           '<input name=at placeholder="odmah" autocomplete=off></label>'
           '<label class="apx-fl apx-dis">Trailing %<input disabled placeholder="—" data-trail aria-describedby=apx-trail-n>'
           '<small id=apx-trail-n>Trailing postavlja plan izlaza prijedloga (ili Grok); ručna kupnja ga nema.</small></label>'
           '<label class=apx-fl>Način izlaza<select name=exit aria-label="Kako prodati">'
           '<option value=tpsl>moj TP/SL</option><option value=smart>Smart sell</option><option value=manual>prodajem sam</option>'
           '</select></label></details>'
           '<div class=apx-cost data-cost>Procjena troška: upiši token i iznos.</div>'
           f'<button class="apx-go buy" data-go=buy>Kupi {esc(sym)}</button>'
           '<p class=apx-note>Prolazi iste provjere i limite kao i prije (ulog, dan, trošak, rug, MC 30k+). Pravi novac ide samo '
           'kad je Autopilot uključen.</p></form>')
    dca = _dca_rows(m, sel_pos, pn)
    if sel_pos:
        ids = ",".join(map(str, sel_pos["ids"]))
        fr = "".join(f'<label class=apx-chip><input type=radio name=frac value="{v:g}"{" checked" if v == 0.5 else ""}>{lab}</label>'
                     for v, lab in SELL_FRACS)
        sell = (f'<form method=post action=/pravi-trade/sell class=apx-f id=apx-sell hidden onsubmit="return confirm(\'Prodati '
                f'odabrani dio pozicije {esc(sel_pos["sym"])} odmah?\')"><input type=hidden name=id value="{ids}">'
                f'<p class=apx-mut>{esc(sel_pos["sym"])}: {redak.sol(sel_pos["sol_in"], 3)} · '
                f'{"paper" if sel_pos["paper"] else "uživo"}</p><div class=apx-chips>{fr}</div>'
                f'<button class="apx-go sell" data-go=sell>Prodaj 50 % {esc(sel_pos["sym"])}</button>'
                '<p class=apx-note>Prodaja ide istim putem kao i prije: zahtjev trade procesu, za nekoliko sekundi je u '
                'tablici.</p></form>')
    else:
        sell = ('<div class=apx-f id=apx-sell hidden><p class=apx-mut>Za odabrani token nema otvorene pozicije. Odaberi '
                'poziciju u tablici.</p></div>')
    seg = ('<div class=apx-seg role=tablist><button type=button class="on buy" data-side=buy role=tab aria-selected=true>Kupi'
           '</button><button type=button class=sell data-side=sell role=tab aria-selected=false>Prodaj</button></div>')
    return f'<aside class=apx-side id=kupi-odmah aria-label="Nalog">{head}{wal}{seg}{buy}{sell}{dca}</aside>'


def _dca_rows(m, sel_pos, pn):
    """Up to DCA_ROWS dokup levels of the selected position: each its own form to /pravi-trade/dca (token, lvl, sol),
    the route the position's DCA always used; a rangedca zone fills the level. Without an open position: why not."""
    if not sel_pos or not sel_pos.get("has_demo"):
        return ('<div class=apx-dca><h4>DCA razine</h4><p class=apx-mut>DCA se postavlja na otvorenu poziciju: kupi, pa '
                'ovdje postavi do 3 razine (postotak ispod ulaza ili zona raspona).</p></div>')
    size = pn.get("size_sol") or 0.1
    rows = "".join(
        f'<form method=post action=/pravi-trade/dca class=apx-dcar><input type=hidden name=token value="{esc(m)}">'
        f'<input name=lvl placeholder="-{10 * (i + 1)}% ili $50k" aria-label="Razina {i + 1}" autocomplete=off>'
        f'<select data-zone aria-label="Zona raspona"><option value="">zona…</option></select>'
        f'<input name=sol value="{size:g}" inputmode=decimal aria-label="SOL">'
        '<button class=apx-b>Postavi</button></form>' for i in range(DCA_ROWS))
    return (f'<div class=apx-dca><h4>DCA razine <small>{esc(sel_pos["sym"])}, prosjek {mc(sel_pos.get("avg_mc"))}</small></h4>'
            f'{rows}<p class=apx-note>Kad MC padne na razinu, bot dokupi taj iznos u istu poziciju (jednom po nalogu).</p></div>')


def _skel(lines=3):
    return '<div class=apx-skel>' + "".join("<i></i>" for _ in range(lines)) + '</div>'


def static_url(name):
    s = static_asset(name)
    return f"/pravi-trade/static/{name}?v={s[3]}" if s else f"/pravi-trade/static/{name}"


def _top_html(d, tcon, cfg, owner):
    """Title, state, the owner's switch, the warnings and Grok's requests that wait for the owner's tap."""
    dot_, words = pt._state(cfg)
    st = f'<span class="apx-state {"on" if dot_ == "good" else "warn" if dot_ == "warn" else ""}">{esc(words)}</span>'
    switch = pt._switch_html(cfg["on"]) if owner else f'<span class=apx-mut>{"Uključen" if cfg["on"] else "Isključen"}</span>'
    alerts = ('<p class="ap-w bad">Prodaja svega je u tijeku…</p>' if cfg.get("sell_all") else "")
    con = None
    try:
        from league import store
        con = store.connect()
        alerts += pt._warnings(tcon, cfg, con)
    except Exception as e:  # noqa: BLE001 - a broken check must not cost the owner the switch
        print(f"autopilot: upozorenja nisu složena: {type(e).__name__}: {e}", flush=True)
    finally:
        if con is not None:
            con.close()
    req = pt._safe("mcp", pt._mcp_requests, tcon, owner)
    # 10.11.: Grok's autotrade while it is on, with its red "Ugasi" (a kill switch stays in sight, never lazy)
    grok = pt._safe("grok-auto", pt._grok_auto_live, tcon, owner)
    link = ""
    if owner:   # the wallet's setup steps live in "Postavke i dijagnostika"; until it is ready the bar leads there
        try:
            addr = pt._addr(tcon)[0]
            n_open = tcon.execute("SELECT COUNT(*) FROM positions WHERE status='open'").fetchone()[0]
            oks = pt._steps_ok(cfg, addr, (d.get("panel") or {}).get("balance_sol"), n_open)
            if not all(oks[:3]):
                link = f'<a class=apx-state href="#postavljanje">Dovrši {sum(oks)}/{len(oks)}</a>'
        except Exception:  # noqa: BLE001
            link = ""
    return (f'<div class=apx-top><h1>{TITLE}</h1>{st}{link}<span class=apx-sp></span>{switch}</div>'
            + (f'<div class="ap apx-alerts">{alerts}</div>' if alerts else "")
            + "".join(f'<div class="ap apx-blk">{x}</div>' for x in (req, grok) if x))


def page(qs, user, full=False):
    """GET /pravi-trade. full (qs sve=1, the no-JavaScript link): every lazy part is rendered into the page."""
    qs = qs if isinstance(qs, dict) else {}
    full = full or qs.get("sve") == "1"
    now = time.time()
    tcon = pt._tcon()
    try:
        if not settings.can_view(tcon, user):
            return (TITLE, f'<div class="ap ms-page">{pt._title()}<p class=ms-hint>Ova stranica je samo za pozvane. '
                    'Ako želiš pristup, javi se vlasniku aplikacije.</p></div>' + pt.CSS)
        owner = settings.is_owner(user)
        cfg = pt._cfg(tcon)
        # right after a form (?ok= / ?err=) the cached view may predate what the form changed: build it anew
        d = first_view(user, qs.get("m", ""), now, fresh=bool(qs.get("ok") or qs.get("err")))
        sel = d.get("m") or ""
        sel_pos = next((p for p in d["positions"] if p["token"] == sel), None)
        toast = ""
        if qs.get("err") or qs.get("ok"):
            bad = bool(qs.get("err"))
            toast = (f'<div class="ap-toast {"bad" if bad else "ok"}" role={"alert" if bad else "status"} '
                     f'onclick="this.remove()">{"<b>Nije prošlo:</b> " if bad else ""}{esc(qs.get("err") or qs.get("ok"))}'
                     '<span class=ap-toast-x aria-hidden=true>×</span></div>'
                     + ("" if bad else "<script>setTimeout(()=>{const t=document.querySelector('.ap-toast');if(t)t.remove()},6000)</script>"))
        npos, nord = len(d["positions"]), len(d["orders"])
        chart = ('<div class=apx-card id=apx-chartbox><div class=apx-cbar><div class=apx-tf role=group aria-label="Vremenski okvir">'
                 + "".join(f'<button type=button data-tf={k}{" class=on" if k == "5m" else ""}>{k}</button>' for k in TFS)
                 + '</div><div class=apx-tf role=group aria-label="Jedinica"><button type=button data-unit=mc class=on>MC</button>'
                 '<button type=button data-unit=price>Cijena</button></div><span class=apx-sp></span>'
                 '<span class=apx-leg><i class=e></i>ulaz <i class=d></i>DCA <i class=s></i>SL <i class=t></i>TP <i class=z></i>zone'
                 '</span><span class=apx-age data-ts=0 id=apx-chart-age>graf se učitava</span></div>'
                 f'<div id=apx-chart class=apx-chart data-m="{esc(sel)}">{_skel(1) if sel else ""}'
                 + ('' if sel else '<p class=apx-empty>Nema odabranog tokena.</p>') + '</div>'
                 '<p class=apx-zinfo id=apx-zinfo></p>'
                 '<p class=apx-attr>Graf: <a href="https://www.tradingview.com/" target=_blank rel=noopener>TradingView Lightweight '
                 'Charts™</a> · Copyright (c) 2025 TradingView, Inc. · podaci: naše snimke (DexScreener, GeckoTerminal)</p></div>')
        tabs = ('<div class=apx-tabs role=tablist>'
                f'<button type=button class=on data-tab=pozicije role=tab>Pozicije <b id=apx-npos>{npos}</b></button>'
                f'<button type=button data-tab=nalozi role=tab>Otvoreni nalozi <b id=apx-nord>{nord}</b></button>'
                '<button type=button data-tab=povijest role=tab>Povijest</button>'
                '<button type=button data-tab=dnevnik role=tab>Dnevnik</button>'
                f'<span class=apx-sp></span>{age_badge(d.get("data_ts"), now).replace("apx-age", "apx-age apx-live-age", 1)}</div>')
        hist = lazy("povijest", user, qs) if full else _skel(4)
        dn = pt._safe("dnevnik", pt.dnevnik_fragment, user) if full else _skel(4)
        panes = (f'<div class=apx-pane id=pozicije>{positions_html(d)}</div>'
                 f'<div class=apx-pane id=nalozi hidden>{orders_html(d)}'
                 # 10.11.: the exit plans' kill switch stays with the orders, never lazy (only while plans exist)
                 f'<div class="ap apx-blk">{pt._safe("exit-planovi", pt._exit_plans_block, tcon, owner)}</div></div>'
                 f'<div class=apx-pane id=povijest hidden data-x-src=/pravi-trade/l/povijest>{hist}</div>'
                 f'<div class="apx-pane ap" id=dnevnik hidden><div data-x-src=/pravi-trade/dnevnik data-x-every={DNEVNIK_EVERY_S}>'
                 f'{dn}</div><p class=ms-hint><u data-pop="/pravi-trade/log" style="cursor:pointer">Tehnički zapis naloga</u> '
                 '(svaki pokušaj kupnje i prodaje s rutom i greškom)</p></div>')
        ek = (qs.get("ekipa") or "").strip()
        pr_src = "/pravi-trade/l/pratimo" + (f"?ekipa={quote(ek)}" if ek else "")
        k_in = lazy("kupiti", user, qs) if full else '<h2 data-sec="" class=apx-h2>Što kupiti</h2>' + _skel(4)
        p_in = lazy("pratimo", user, qs) if full else '<h2 data-sec="" class=apx-h2>Koga pratimo</h2>' + _skel(4)
        o_in = lazy("ostalo", user, qs) if full else _skel(5)
        cards = (f'<section class="apx-card apx-lz" id=kupiti data-x-src=/pravi-trade/l/kupiti data-x-every={KUPITI_EVERY_S}>'
                 f'{k_in}</section>'
                 f'<section class="apx-card apx-lz" id=pratimo data-x-src="{esc(pr_src)}" data-x-every={PRATIMO_EVERY_S}>'
                 f'{p_in}</section>')
        ost = (f'<details class=apx-acc id=apx-ostalo{" open" if full else ""}><summary><h2 data-sec="">Postavke i dijagnostika</h2>'
               '<span class=apx-mut>pravila, Grok, zastavice, preporuke, wallet…</span></summary>'
               f'<div class="ap apx-acc-in" data-x-src=/pravi-trade/l/ostalo>{o_in}</div></details>')
        mbar = ('<div class=apx-mbar>'
                + ('<button type=button class="apx-go buy" data-sheet=buy>Kupi</button><button type=button class="apx-go sell" '
                   'data-sheet=sell>Prodaj</button>' if owner else '<button type=button class=apx-go data-sheet=buy>Nalog i wallet</button>')
                + '</div><div class=apx-scrim data-sheet-close></div>')
        fj = {k: v for k, v in d.items() if not k.startswith("_")}
        fj["urls"] = {"lwc": static_url(LWC_FILE), "poll_s": POLL_S}
        boot = json.dumps(fj, ensure_ascii=False, separators=(",", ":"), default=str).replace("</", "<\\/")
        noscript = ('<noscript><p class=apx-mut>Bez JavaScripta: <a href="/pravi-trade?sve=1">otvori sve dijelove odjednom</a>'
                    '</p></noscript>')
        # pravitrade.CSS first: the older sections (tabs, settings) keep their shapes; ap.css after it sets the colours
        body = [pt.CSS, CSS, '<div class=apx id=apx data-owner=' + ("1" if owner else "0") + '>', toast,
                _top_html(d, tcon, cfg, owner), noscript,
                '<div class=apx-grid><div class=apx-main>', _hdr_html(d.get("header"), now), chart, tabs, panes, '</div>',
                panel_html(d, sel_pos), '</div>', cards, ost, mbar,
                f'<script type=application/json id=apx-first>{boot}</script>', '</div>',
                pt.POP_CSS, pt.POP_HTML, f'<script src="{static_url("ap.js")}" defer></script>']
        return TITLE, "".join(body)
    finally:
        tcon.close()


# ---------- lazy parts (GET /pravi-trade/l/<name>) ------------------------------------------------------------------

def lazy(name, user, qs=None):
    """The HTML of a part fetched when it scrolls into view or is opened; None without access (403), "" unknown."""
    qs = qs or {}
    tcon = pt._tcon()
    try:
        if not settings.can_view(tcon, user):
            return None
        owner = settings.is_owner(user)
        cfg = pt._cfg(tcon)
        now = time.time()
        if name == "kupiti":
            return kupiti_html(tcon, cfg, owner, now)
        if name == "pratimo":
            return pratimo_html(tcon, cfg, owner, now, (qs.get("ekipa") or "").strip())
        if name == "povijest":
            try:
                p = max(1, min(50, int(qs.get("p") or 1)))
            except ValueError:
                p = 1
            return povijest_html(tcon, cfg, owner, now, p)
        if name == "ostalo":
            return ostalo_html(tcon, cfg, owner, now)
        return ""
    finally:
        tcon.close()


def _proposals(owner, now):
    """(open proposals, near misses, recent decided, flag mode) from proposals/view (its own 30-s cache)."""
    if not owner:
        return [], [], [], "off"
    try:
        from proposals import view
        mode = view._mode()
        if mode == "off":
            return [], [], [], mode
        d = view.load()
        return d.get("active") or [], (d.get("last_pass") or {}).get("near") or [], d.get("recent") or [], mode
    except Exception as e:  # noqa: BLE001
        print(f"autopilot: prijedlozi nisu dostupni: {type(e).__name__}: {e}", flush=True)
        return [], [], [], "off"


def _mins_left(ts, now):
    if not ts:
        return "–"
    m = int((ts - now) // 60)
    return "isteklo" if m < 0 else f"{m} min" if m < 120 else f"{m // 60} h"


def kupiti_html(tcon, cfg, owner, now):
    """"Što kupiti": ONE list of what to buy now, every strategy's proposals (proposals/, EV after cost) and the tool's
    live picks (ui/zivo, "Što alat sada predlaže"), sorted by EV per minute (no EV last). Kupi only fills the order
    panel (token, size capped by the per-trade limit, TP / SL of the proposal); it never buys by itself. "Prikaži
    skoro": the near misses with the block that stopped them. The assistant's suggestions wait behind a badge."""
    from proposals import strategies, view
    act, near, recent, mode = _proposals(owner, now)
    cap = float(cfg.get("max_sol_per_trade") or 0) or None
    rows = []
    for p in act:
        r = p.get("row") or {}
        ez = r.get("entry_zone") or {}
        b = r.get("buy") or {}
        size = float(p.get("size_sol") or cfg.get("size_sol") or 0.1)
        if cap:
            size = min(size, cap)
        trail = (r.get("exits_mcap") or {}).get("trailing_pct")
        pk = json.dumps({"id": p["id"], "token": p["token"], "sol": f"{size:g}", "tp": b.get("tp") or "",
                         "sl": b.get("sl") or "", "sym": p.get("symbol") or p["token"][:6], "trail": trail})
        buy_btn = f'<button type=button class="apx-b buy" data-pk="{esc(pk)}">Kupi</button>' if owner else ""
        rows.append({"epm": ev_per_min(p), "html": (
            f'<div class=apx-krow id=pr-{int(p["id"])}><div class=apx-kmain>{_sel_btn(p["token"], p.get("symbol") or p["token"][:6])}'
            f'<span class=apx-mut>{esc(strategies.HR.get(p.get("strategy"), p.get("strategy") or ""))} · '
            f'{esc(", ".join(strategies.HR.get(s, s) for s in p.get("sources") or []))}</span></div>'
            f'<span class="n {_tone(p.get("ev_pct"))}" data-l="EV">{_pct(p.get("ev_pct"))}<small>{redak.num(ev_per_min(p), 3)} %/min</small></span>'
            f'<span class=n data-l="p_tp (n)">{redak.pct(p.get("p_tp"), sign=False, frac=True)}<small>n={int(r.get("n") or 0)}</small></span>'
            f'<span class=n data-l="Ulaz (MC)">{mc(ez.get("mcap_low"))}–{mc(ez.get("mcap_high"))}</span>'
            f'<span class=n data-l="Istječe za">{_mins_left(p.get("expires_ts"), now)}</span>'
            f'<span class=apx-act>{buy_btn}</span>'
            f'<details class=apx-kmore><summary>detalji</summary><div class=ap>{view._row_inner(p, esc)}</div></details></div>')})
    try:
        from ui import zivo
        live = zivo.rows(now)[:8]
    except Exception:  # noqa: BLE001
        live = []
    seen = {p["token"] for p in act}
    for z in live:
        if z["token"] in seen:
            continue
        m = z.get("live") or {}
        why = z.get("why_not") or (z.get("reasons") or [""])[0]
        sym = z.get("symbol") or m.get("symbol") or z["token"][:6]
        fill = json.dumps({"token": z["token"], "sym": sym, "sol": f"{min(float(cfg.get('size_sol') or 0.1), cap or 9e9):g}"})
        fill_btn = f'<button type=button class=apx-b data-fill="{esc(fill)}">U panel</button>' if owner else ""
        rows.append({"epm": None, "html": (
            f'<div class=apx-krow><div class=apx-kmain>{_sel_btn(z["token"], sym)}<span class=apx-mut>alat (živo) · '
            f'{esc(z.get("src") or "")}{" · " + esc(why) if why else ""}</span></div>'
            '<span class=n data-l="EV">–<small>nije izmjeren</small></span><span class=n data-l="p_tp (n)">–</span>'
            f'<span class=n data-l="MC">{mc(m.get("mcap"))}</span><span class=n data-l="5 min / 1 h">'
            f'{_pct(m.get("ch_m5"), 0)}<small>{_pct(m.get("ch_h1"), 0)}</small></span>'
            f'<span class=apx-act>{fill_btn}'
            f'<span class="ap-lnk" role=button tabindex=0{pt._pop(z["token"])}>provjera</span></span></div>')})
    rows.sort(key=lambda r: (r["epm"] is None, -(r["epm"] or 0)))
    head = ('<div class="apx-krow apx-th" aria-hidden=true><span>Token · strategija i izvori</span><span class=n>EV</span>'
            '<span class=n>p_tp (n)</span><span class=n>Ulaz</span><span class=n>Istječe</span><span></span></div>')
    body = head + "".join(r["html"] for r in rows) if rows else (
        '<p class=apx-empty>Trenutno ništa ne prolazi: nijedan prijedlog nema EV iznad nule bez blokade, a alat nema živog '
        'kandidata.' + ("" if owner else " Prijedlozi strategija vide se samo vlasniku.") + '</p>')
    near_rows = "".join(
        f'<div class="apx-krow is-paper"><div class=apx-kmain>{_sel_btn(n.get("token") or "", n.get("symbol") or (n.get("token") or "")[:6])}'
        f'<span class=apx-mut>{esc(", ".join(strategies.HR.get(s, s) for s in n.get("strategies") or []))}</span></div>'
        f'<span class=n data-l="EV">{_pct(n.get("ev_pct"))}</span>'
        f'<span data-l="Blokada" class=apx-why>{esc("; ".join(n.get("blocks") or []) or n.get("why") or "")}</span></div>'
        for n in near[:20])
    skoro = (f'<details class=apx-skoro><summary>prikaži skoro ({len(near)})</summary>{near_rows}</details>' if near else "")
    sug = ""
    if owner:
        try:
            from ui import assistnotes
            _r, n_sug = assistnotes.notes(tcon, "novo", "suggestion", 1, 0)
        except Exception:  # noqa: BLE001
            n_sug = 0
        inner = pt._safe("prijedlozi", pt._suggest_section, tcon, owner)
        if inner:
            sug = (f'<details class=apx-sug id=prijedlozi><summary>Prijedlozi asistenta <span class=apx-cnt>{n_sug} čeka'
                   f'</span></summary><div class=ap>{inner}</div></details>')
    rec = ""
    if recent:
        n = {s: sum(1 for p in recent if p["status"] == s) for s in ("kupljeno", "odbijeno", "isteklo")}
        rec = (f'<p class=apx-mut>Zadnja 24 h: kupljeno {n["kupljeno"]}, odbijeno {n["odbijeno"]}, isteklo {n["isteklo"]}.</p>')
    flag = f' · prijedlozi: {esc(mode)}' if owner else ""
    return (f'<h2 data-sec="" class=apx-h2>Što kupiti <span class=apx-cnt>{len(rows)}</span>{age_badge(now, now)}</h2>'
            f'<p class=apx-mut>Svi prijedlozi strategija i živi kandidati alata, poredani po EV po minuti{flag}. Kupi samo '
            'popuni panel; kupuješ ti.</p>'
            f'<div class="apx-tbl apx-ktbl" id=prijedlozi-trade>{body}</div>{skoro}{sug}{rec}')


def _follow_last(con):
    try:
        return {fid: ts for fid, ts in con.execute("SELECT follow_id, MAX(ts) FROM copy_log GROUP BY follow_id")}
    except sqlite3.Error:
        return {}


def pratimo_html(tcon, cfg, owner, now, prefill=""):
    """"Koga pratimo": Walleti / Influenceri / Tokeni (rangedca watchlist); per row hit rate, n, PnL, last activity;
    stopped / excluded ones behind "prikaži isključene"; the live feed of who calls which token in the last 60 min;
    the old "Koga prati" with its forms (zaprati, izlaz, prestani) behind "Uredi praćenja"."""
    from league import copy, store
    con = store.connect()
    try:
        copy.ensure(con)
        fl = copy.follows(con, settings.LEAGUE_USER, active=None)
        res = copy.follow_results(con)
        last = _follow_last(con)
        manage = pt._safe("praćenja", pt._follows, con, owner, settings.raw(tcon), prefill)
    finally:
        con.close()

    def frow(f):
        r = res.get(f["id"], {"n": 0, "closed": 0, "wins": 0, "pnl": 0.0})
        hit = (r["wins"] / r["closed"]) if r["closed"] else None
        return (f'<div class="apx-krow apx-frow{"" if f.get("active") else " is-paper"}" id=prati-{f["id"]}>'
                f'<div class=apx-kmain><b>{esc(pt._follow_name(f))}</b><span class=apx-mut>'
                f'{esc(copy.describe_exit(f["exit"], copy.default_sl(f["user"])) or "zadani izlaz")}</span></div>'
                f'<span class=n data-l="Pogodak">{redak.pct(hit, sign=False, frac=True) if hit is not None else "–"}</span>'
                f'<span class=n data-l="n">{r["n"]}<small>{r["closed"]} zatv.</small></span>'
                f'<span class="n {_tone(r["pnl"])}" data-l="PnL">{redak.usd(r["pnl"], sign=True) if r["closed"] else "–"}</span>'
                f'<span class=n data-l="Zadnje">{esc(redak.ago(last.get(f["id"]), now)) if last.get(f["id"]) else "–"}</span></div>')

    def group(kinds, empty):
        act = [f for f in fl if f["kind"] in kinds and f.get("active")]
        off = [f for f in fl if f["kind"] in kinds and not f.get("active")]
        head = ('<div class="apx-krow apx-th" aria-hidden=true><span>Tko</span><span class=n>Pogodak</span><span class=n>n</span>'
                '<span class=n>PnL</span><span class=n>Zadnje</span></div>')
        body = (head + "".join(frow(f) for f in act)) if act else f'<p class=apx-empty>{empty}</p>'
        if off:
            body += (f'<details class=apx-skoro><summary>prikaži isključene ({len(off)})</summary>'
                     + "".join(frow(f) for f in off) + '</details>')
        return f'<div class=apx-tbl>{body}</div>'
    tok = _watch_tokens(now)
    tabs = ('<div class="apx-tabs apx-sub" role=tablist><button type=button class=on data-sub=pr-w>Walleti</button>'
            '<button type=button data-sub=pr-i>Influenceri</button><button type=button data-sub=pr-t>Tokeni</button></div>')
    feed = (f'<h3 class=apx-h3>Tko sada zove koji token (60 min)</h3><div class=ap><div id=ap-zovu data-x-src=/pravi-trade/zovu '
            f'data-x-every={ZOVU_EVERY_S} data-empty="U zadnjih 60 minuta nema poziva koji sada prolazi provjere.">{_skel(3)}'
            '</div><p class=ms-hint>Tokeni koje su u zadnjih 60 minuta objavili influenceri i Telegram kanali ili kupili walleti '
            'koje pratiš i dokazani walleti, a upravo se trguju. Dodirni token za provjeru uživo, podcrtano ime za cijelu ekipu. '
            'Tko od njih stvarno nosi +5/10/15/20/30 % nakon poziva: <a href="/ekipe">Ekipe i minutna provjera</a>.</p></div>')
    edit = (f'<details class="apx-sug ap" id=pratim{" open" if prefill else ""}><summary>Uredi praćenja (zaprati, izlaz, '
            f'prestani)</summary>{manage}</details>' if manage else "")
    return (f'<h2 data-sec="" class=apx-h2>Koga pratimo <span class=apx-cnt>{sum(1 for f in fl if f.get("active"))}</span>'
            f'{age_badge(now, now)}</h2>{tabs}'
            f'<div class=apx-subp id=pr-w>{group(("wallet",), "Ne pratimo nijedan wallet.")}</div>'
            f'<div class=apx-subp id=pr-i hidden>{group(("kol", "ekipa"), "Ne pratimo nijednog influencera.")}</div>'
            f'<div class=apx-subp id=pr-t hidden>{tok}</div>{feed}{edit}')


def _watch_tokens(now, limit=30):
    """The rangedca watchlist as rows: status, score, MC, position in the range, source, when computed; the ones
    that are not an active range behind "prikaži isključene". Columns only, no JSON parsed."""
    try:
        from rangedca import data as rdata
        con = rdata.ro()
    except Exception:  # noqa: BLE001
        con = None
    if con is None:
        return '<p class=apx-empty>Watchlista raspona je prazna (range.db još ne postoji).</p>'
    try:
        src = ", src" if rdata.has_src(con) else ", NULL"
        rows = con.execute(f"SELECT token, symbol, status, active, score, mcap, pos_pct, ts{src} FROM ranges "
                           "ORDER BY active DESC, score DESC, ts DESC LIMIT ?", (limit * 3,)).fetchall()
    except sqlite3.Error:
        rows = []
    finally:
        con.close()
    if not rows:
        return '<p class=apx-empty>Watchlista raspona je prazna.</p>'

    def trow(r):
        tok, sym, st, act, score, mcap, pos, ts, src = r
        return (f'<div class="apx-krow{"" if act else " is-paper"}"><div class=apx-kmain>{_sel_btn(tok, sym or tok[:6])}'
                f'<span class=apx-mut>{esc(st or "")} · {esc(src or "signal")}</span></div>'
                f'<span class=n data-l="Ocjena">{redak.num(score, 2) if score is not None else "–"}</span>'
                f'<span class=n data-l="MC">{mc(mcap)}</span>'
                f'<span class=n data-l="U rasponu">{redak.pct(pos, sign=False) if pos is not None else "–"}</span>'
                f'<span class=n data-l="Izračunato">{esc(redak.ago(ts, now))}</span></div>')
    on = [r for r in rows if r[3]][:limit]
    off = [r for r in rows if not r[3]][:limit]
    head = ('<div class="apx-krow apx-th" aria-hidden=true><span>Token</span><span class=n>Ocjena</span><span class=n>MC</span>'
            '<span class=n>U rasponu</span><span class=n>Izračunato</span></div>')
    body = (head + "".join(trow(r) for r in on)) if on else '<p class=apx-empty>Nijedan aktivan raspon.</p>'
    if off:
        body += f'<details class=apx-skoro><summary>prikaži isključene ({len(off)})</summary>{"".join(trow(r) for r in off)}</details>'
    return f'<div class=apx-tbl>{body}</div>'


def povijest_html(tcon, cfg, owner, now, page_no=1):
    """Povijest: positions closed today (Zagreb midnight) with the day's PnL on top, live first; older ones one page of
    HIST_PAGE at a time ("Starije")."""
    start = executor._day_start(now, cfg.get("day_tz"))
    off = (page_no - 1) * HIST_PAGE
    rows = tcon.execute("SELECT id, token, symbol, opened_ts, closed_ts, mode, reason, sol_in, sol_back, "
                        "COALESCE(fees_sol,0) FROM positions WHERE status='closed' ORDER BY COALESCE(closed_ts, opened_ts) "
                        "DESC LIMIT ? OFFSET ?", (HIST_PAGE + 1, off)).fetchall()
    more = len(rows) > HIST_PAGE
    rows = rows[:HIST_PAGE]
    today = tcon.execute("SELECT mode, COUNT(*), COALESCE(SUM(sol_back - sol_in - COALESCE(fees_sol,0)),0), "
                         "SUM(CASE WHEN sol_back - sol_in - COALESCE(fees_sol,0) > 0 THEN 1 ELSE 0 END) FROM positions "
                         "WHERE status='closed' AND COALESCE(closed_ts, opened_ts) >= ? GROUP BY mode", (start,)).fetchall()
    sums = "".join(
        f'<div><span>Danas {"uživo" if m == "live" else "paper"}</span><b class={_tone(s)}>{redak.sol(s, 4, sign=True)}</b>'
        f'<small>{n} zatvoreno, {w or 0} u plusu</small></div>'
        for m, n, s, w in sorted(today, key=lambda r: r[0] != "live")) or '<div><span>Danas</span><b>nijedna zatvorena</b></div>'
    ids = [r[0] for r in rows]
    sigs = dict(tcon.execute(f"SELECT position_id, signature FROM orders WHERE position_id IN ({','.join('?' * len(ids))}) "
                             "AND side='sell' AND signature IS NOT NULL ORDER BY id", ids)) if ids else {}
    rows.sort(key=lambda r: (r[5] != "live", -(r[4] or r[3] or 0)))
    notes = _notes(tcon, ids, ())
    out = []
    for pid, tok, sym, ots, cts, mode, why, sin, sback, fees in rows:
        pnl = (sback or 0) - (sin or 0) - (fees or 0)
        pp = pnl / sin * 100 if sin else None
        link = (f'<a href="https://solscan.io/tx/{esc(sigs[pid])}" target=_blank rel=noopener>Solscan ↗</a>'
                if sigs.get(pid) else "")
        paper = mode != "live"
        out.append(f'<div class="apx-tr apx-hist{" is-paper" if paper else ""}"><span data-l="Token">{_sel_btn(tok, sym or short(tok))}'
                   f'{BADGE_PAPER if paper else BADGE_LIVE}</span>'
                   f'<span class=n data-l="Zatvoreno">{esc(time.strftime("%d.%m. %H:%M", time.localtime(cts or ots or 0)))}</span>'
                   f'<span class=n data-l="Uloženo">{redak.sol(sin, 3)}</span><span class=n data-l="Vraćeno">{redak.sol(sback, 4)}</span>'
                   f'<span class="n {_tone(pnl)}" data-l="PnL">{redak.sol(pnl, 4, sign=True)}<small>{_pct(pp)}</small></span>'
                   f'<span data-l="Izvor">{esc(src_kind(why))}<small>{esc(pt._who(why) or "")}</small></span>'
                   f'<span class=apx-act>{link}</span>{_note_html(_slim(notes.get(("p", pid))))}</div>')
    head = ('<div class="apx-tr apx-th apx-hist" aria-hidden=true><span>Token</span><span class=n>Zatvoreno</span>'
            '<span class=n>Uloženo</span><span class=n>Vraćeno</span><span class=n>PnL</span><span>Izvor</span><span></span></div>')
    body = head + "".join(out) if out else '<p class=apx-empty>Još nema zatvorenih pozicija.</p>'
    nav = ""
    if more or page_no > 1:
        nav = ('<div class=apx-pg>' + (f'<button type=button class=apx-b data-page="/pravi-trade/l/povijest?p={page_no - 1}">'
                                       '← Novije</button>' if page_no > 1 else "")
               + (f'<button type=button class=apx-b data-page="/pravi-trade/l/povijest?p={page_no + 1}">Starije →</button>'
                  if more else "") + '</div>')
    return (f'<div class=apx-sum>{sums}<span class=apx-sp></span>{age_badge(now, now)}</div>'
            f'<p class=apx-mut>Zarada = vraćeno − uloženo − mrežne naknade.</p><div class=apx-tbl>{body}</div>{nav}')


def _wrap(title, html, sid):
    """A part that is not a pravitrade _sec (its own card or block) as one closed row."""
    if not html:
        return ""
    return pt._sec(title, "", html, sid=sid)


def ostalo_html(tcon, cfg, owner, now):
    """"Postavke i dijagnostika": the page's older sections, each one closed row with its one-line summary (details
    on a tap); a section with nothing in it ("0 …", "nema …", "isključen") goes grey to the bottom; a section that
    returns nothing is left out."""
    from league import store
    con = store.connect()
    try:
        from league import copy
        copy.ensure(con)
        parts = [
            ("pravila", pt._safe("pravila", pt._rules, tcon, cfg, owner)),
            ("grok", pt._safe("grok", pt._mcp_section, tcon, owner)),
            ("grok-postavke", pt._safe("grok-postavke", pt._grok_auto_setup, tcon, owner)),
            ("zastavice", pt._safe("zastavice", pt._flags_section, tcon, con, owner)),
            ("pregled", pt._safe("pregled", pt._review_section, tcon, owner)),
            ("preshill", pt._safe("preshill", pt._preshill_card, owner)),
            ("eventi", pt._safe("eventi", pt._eventi_card, owner)),
            ("ev", pt._safe("ev", pt._ev_card, owner)),
            ("fast-path", pt._safe("fast-path", pt._fast_card, owner)),
            ("preporuke", pt._recs_section()),
            ("sazetak", _wrap("Grokov dnevni sažetak", pt._safe("sazetak", pt._summary_card, tcon, owner), "sazetak-r")),
            ("vrijednost", _wrap("Vrijednost walleta (graf)", pt._safe("vrijednost", _equity_chart, tcon), "vrijednost")),
            ("wallet", pt._safe("wallet", pt._wallet_row, tcon, owner, _setup(tcon, cfg) if owner else {})),
            ("pozivnice", pt._safe("pozivnice", pt._invites, tcon) if owner else ""),
            ("zastita", pt._safety()),
        ]
    finally:
        con.close()
    full = [h for _k, h in parts if h and not empty_meta(h)]
    dim = [h for _k, h in parts if h and empty_meta(h)]
    out = "".join(full)
    if dim:
        out += f'<div class=apx-dim><p class=apx-mut>Bez sadržaja trenutno ({len(dim)}):</p>{"".join(dim)}</div>'
    out += ('<p class=apx-mut style="margin-top:14px"><a href="/pravi-trade?stari=1">Stari prikaz stranice</a> (privremeno, '
            'za usporedbu)</p>')
    return f'<div class=ap-grp>{out}</div>'


def _setup(tcon, cfg):
    addr, key_addr, saved = pt._addr(tcon)
    n_open = tcon.execute("SELECT COUNT(*) FROM positions WHERE status='open'").fetchone()[0]
    return pt._setup(tcon, cfg, addr, key_addr, saved, pt._balance(addr), pt._usdc(addr), n_open)


def _equity_chart(tcon):
    """The wallet's value over time (ui/apchart), the old header's chart, now one row under the settings."""
    if pt._equity_mod() is None:
        return ""
    from ui import apchart
    eq = pt.equity_data(tcon)
    if not eq["series"]:
        return ""
    return apchart.chart_html(eq["series"], eq["summary"], eq["deposits"], ident="ap")


# ---------- static files (the chart library and the page script), cached by the browser for a year -----------------

def _strip(js):
    return re.sub(r"^<script>|</script>$", "", js.strip())


def static_asset(name):
    """(raw, gzipped, content type, version) of /pravi-trade/static/<name>, built once per process; None unknown."""
    with _LOCK:
        hit = _STATIC.get(name)
    if hit:
        return hit
    if name == LWC_FILE:
        p = os.path.join(STATIC_DIR, LWC_FILE)
        if not os.path.isfile(p):
            return None
        with open(p, "rb") as f:
            raw = f.read()
        ctype = "text/javascript"
    elif name == "ap.js":
        with open(os.path.join(STATIC_DIR, "ap.js"), "rb") as f:
            own = f.read().decode("utf-8")
        # the older page's helpers the lazy sections need (pop-ups, the poller of data-src boxes, opening rows)
        old = "\n;".join(_strip(x) for x in (pt.PATCH_JS, pt.POP_JS, pt.POLL_JS, pt.JS, pt.TOGGLE_JS))
        raw = (old + "\n;" + own).encode("utf-8")
        ctype = "text/javascript"
    else:
        return None
    out = (raw, gzip.compress(raw, 9), ctype, hashlib.sha256(raw).hexdigest()[:10])
    with _LOCK:
        _STATIC[name] = out
    return out


def _read_css():
    """ui/static/ap/ap.css, inlined into the page: the first paint needs no second request."""
    try:
        with open(os.path.join(STATIC_DIR, "ap.css"), encoding="utf-8") as f:
            return "<style>" + f.read() + "</style>"
    except OSError:
        return ""


CSS = _read_css()
