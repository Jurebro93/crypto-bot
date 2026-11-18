"""The learner's own DEMO account ("učenik"): the forward test of what veliki/nauceno found
(owner: "želim da demo što prije bude profitabilan").

What was found (18.11.2026, 39 unseen days, the real cost, round trip never under 3 %): all imagined trades -4.5 %
per token-day; the ones the model predicted above +1 % net: +4.9 % [+1.7; +8.2], n=111 trades in 71 token-days. Two
reasons not to believe that number: the threshold was looked at on the same days as the result, and the walk-forward
of that day had a look-ahead leak (a trade's final result entered the model before the trade was closed; purged the
same day, veliki/nauceno, whose line now carries the corrected number). So it is a hypothesis. This account tests it
on days that had not happened yet, with a rule written down BEFORE the first trade:

  THE RULE, registered 18.11.2026, never tuned afterwards (a change of any number below is a NEW rule under a new
  account and a new date, never an edit of this one):
    candidate  every candidate the shadow book considers (veliki/sjena.consider: every token of the demo universe once
               per completed 15m bar), whatever the day rule thinks of it
    facts      veliki/sjena.known(): the same code path that builds the book's row, read by nauceno.facts()
    model      nauceno.load_model(): the sums over all book rows the learner stored at its last run (every 6 h);
               missing or older than 24 h = no entry
    entry      nauceno.predict_best(): the exit profile with the highest predicted net return; entered only when that
               prediction is above THR = +1 % net
    exit       that profile's target and stop (veliki/sjena.levels at the real round trip, never under
               replay.RT_FLOOR), or the time limit sjena.MAX_H (72 h). As in the book, a level crossed on one quote is
               filled at the NEXT quote of the token (a spike books nothing it could not have traded). Nothing else: no
               DCA, no trailing, no break-even, no BTC stop, no reasoned exit.
    size       live.INTRA_DEMO_SOL (0.1 SOL, the stake of the other demo accounts and of the real account)
    caps       one open position per token, at most MAX_OPEN = 10 open, intra.COOLDOWN_S (30 min) after an exit of the
               token; the hard entry rules of every account (live.guards: bonded, market cap, liquidity, the rug archive)
    verdict    after VERDICT_DAYS = 21 days from the account's first entry or VERDICT_CLUSTERS = 60 closed token-days,
               whichever comes first: KANDIDAT when the low end of the 90 % interval over token-days (nauceno._stat) is
               above zero, else "nema plusa"; before that only "još se mjeri"
  The only switch is VEL_UCENIK=0: no new entries (open positions still exit by the rule).

Kept apart from the day rule: its own league account USER (demo, never the rule's account PAPER_USER), rows in
league.db veliki_trades tagged varijanta "nauceno:<profile>" with kind "intra", closed only by mark() here (live.tick
skips them in the day rule's manage()); the prediction and the facts of each entry in veliki_ucenik (id = the
veliki_trades id), so the result can be split by predicted band; the rule's cooldown, gate.demo_proof, the hourly
"veliki demo" line and the morning report do not see it (live.intra_entries, live.RULE_ROWS, report/midcap.vrows). A
candidate may be held by the rule's demo account and by this one at the same time. Its result is one line an hour,
"veliki naučeno (demo): ...", the `demo` block of the MCP tool get_shadow_book and the council's direction brief.

REAL MONEY (18.11., owner: "Ne želim da se pravi novac pauzira, nego ... da tradeovi s pravim novcem postanu
profitabilni"; then "Odmah želim da pravi novac krene raditi"): the owner switch pravi_novac_nauceno
(trade/settings.NAUCENO_SWITCH), off by default. It goes on by his own tap, or by his order of 18.11.
(ui/assistnotes.owner_nauceno_real), which acts only if the learner's PURGED result confirms the +1 % threshold (at
least 30 token-days, the interval's low above zero) and is otherwise parked for him.
  off  nothing here touches the real account: no LEAGUE_USER trade is created, and the mirror (run_trade) and
       executor.buy each refuse a learned-rule buy by themselves while the switch is off.
  on   a demo entry ALSO gets a real twin (_enter_real) when ALL of these hold; else the reason is logged, stored with
       the demo entry (veliki_ucenik.real) and the candidate is not tried again (the demo twin holds the token):
         - this process can tell that a real buy is possible now (_real_ready): no kill switch file, the Autopilot on
           with the key in place (executor.is_live), no "Prodaj sve" in progress;
         - the day rule's own refusals of a candidate (live.intra_entries): no dip from a bad reason, no holder
           block, no static risk (concentration / dev / authority), the token is on the veliki list (age >= 15 d);
         - live.enter() for the real account with a `plan`: the SAME function, checks and booking as the day rule's
           real entry (the account does not hold the token, the midcap caps max open / buys a day / day loss counted
           TOGETHER with the day rule's rows, live.guards: bonded, MC, liquidity, the rug archive, a rug collapse; MC
           5-150M, liquidity >= $500k, the priority row known, round trip <= 6 %, nothing the reasoned exit would
           sell at once), only the levels, the time limit, the source and the tag are the plan's; the stake is
           0.1 SOL (trade/executor.NAUCENO_SOL), never more.
       live.enter writes a league.db trade of LEAGUE_USER whose source starts with trade/executor.NAUCENO_SRC and a
       veliki_trades row (user LEAGUE_USER, the same varijanta tag, the same levels, link_id = the demo row). The real
       swap is then placed where every real midcap buy is placed: run_trade.follow_league_once mirrors the league
       trade into trade/executor.buy, which asks the switch again and holds it to the midcap caps and the global ones
       (kill switch, the wallet floor 1 SOL, the day's loss 0.3 / 0.5 SOL, max open, buys a day, MC 5M+, cost <= 6 %,
       a fresh DexScreener quote, a stop on the server). A buy the executor refuses is never retried (the mirror
       books it once); mark() then closes the twin's league row WITHOUT a result (reason "odbijeno"), so only twins
       that were really bought are counted.
       Exits of a real twin: mark() on the same quotes and levels as the demo twin (target, stop, 72 h; live.close
       sells the league trade, run_trade._league_sells sells the real position), the levels are in the row, so a
       restart loses nothing. On top, for the REAL twin only, the two hard safety exits every real midcap position
       has: a rug collapse (league/copy._rugged) and the pool's liquidity at half of its last hour's high
       (live.liq_drop). The day rule's own exits (break-even at +5 %, the BTC tight stop, reasoned exits, trailing,
       DCA) never touch it: live.tick skips these rows in manage(). Outside this module only the owner can close it:
       "Prodaj sve", a manual sale, an exit plan he or Grok puts on that token.
  It does not read or change pravi_novac_veliki; both may be on. The real account holds one position a token, so a
  token the day rule holds with real money gets no real twin (and the reverse).
"""
import json
import os
import sqlite3
import time

D = 86400
USER = "autopilot-nauceno"
RULE_DATE = "18.11."
THR = 0.01
MAX_OPEN = 10
VERDICT_DAYS = 21
VERDICT_CLUSTERS = 60
TAG = "nauceno:"
KEY = "nauceno"
PREFIX = "veliki naučeno (demo): "
REAL_HEAD = "veliki naučeno PRAVI NOVAC"
NO_BUY_S = 240     # a real twin the mirror never took (run_trade's max_signal_age_s is 180 s) is closed without a result
BANDS = ((0.02, "+1 do +2 %"), (0.03, "+2 do +3 %"), (float("inf"), "iznad +3 %"))
VERDICT_HR = {"mjeri": "još se mjeri", "kandidat": "KANDIDAT (donja granica iznad nule)", "nema_plusa": "nema plusa"}
SCHEMA = ("CREATE TABLE IF NOT EXISTS veliki_ucenik (id INTEGER PRIMARY KEY, ts INTEGER, token TEXT, profil TEXT, "
          "pred REAL, model_ts INTEGER, facts TEXT, real TEXT)")
_PEND = {}      # veliki_trades id -> (reason, the time of the quote that crossed the level): filled at the next quote
_BOUGHT = set()  # veliki_trades ids of real twins whose real buy is confirmed in trade.db (asked again after a restart)


def on():
    return os.environ.get("VEL_UCENIK", "1") != "0"


def owns(r):
    """True for a veliki_trades row of this rule, the demo account's or its real twin (live.tick: its exits are
    mark()'s, never manage()'s)."""
    return ((r or {}).get("varijanta") or "").startswith(TAG)


def is_real(r):
    from trade import settings
    return owns(r) and (r or {}).get("user") == settings.LEAGUE_USER


def profile_of(r):
    v = (r or {}).get("varijanta") or ""
    return v[len(TAG):] if v.startswith(TAG) else None


def real_on():
    """True while the owner's switch pravi_novac_nauceno is on (trade.db, read-only, cached a few seconds by
    trade/settings); unreadable = off."""
    try:
        from trade import settings
        return settings.flag(settings.NAUCENO_SWITCH) == "live"
    except Exception:  # noqa: BLE001
        return False


def _real_ready():
    """None when, as far as this process can tell, a real buy can be placed now, else why not (Croatian): the kill
    switch file, the Autopilot off or no key (a buy would only be a probe), "Prodaj sve" in progress. The executor
    asks all of it again on the buy itself; this only keeps a twin from being opened that could never be bought."""
    try:
        from trade import executor, settings
        if os.path.exists(executor.STOP_FILE):
            return "kill switch (trade/STOP)"
        con = sqlite3.connect(f"file:{settings.DB}?mode=ro", uri=True, timeout=5)
        try:
            raw = settings.raw(con)
        finally:
            con.close()
        if raw.get("sell_all"):
            return "„Prodaj sve” je u tijeku"
        if not executor.is_live({"on": bool(raw.get("on", False))}):
            return "Autopilot je isključen ili ključ nije postavljen (kupnja bi bila samo proba)"
        return None
    except Exception as e:  # noqa: BLE001 - what cannot be read is not ready
        return f"stanje pravog računa se ne može pročitati ({type(e).__name__})"


def _say(out, key, text, now):
    """One line an hour per key (a refusal that repeats every bar must not fill the log)."""
    from veliki import live
    said = live._ST.setdefault("said", {})
    if now - said.get(("ucenik", key), 0) > 3600:
        said[("ucenik", key)] = now
        out.append(text)


def _note_real(con, vid, text):
    """What became of the real twin of the entry vid (veliki_ucenik.real), for the later comparison."""
    try:
        con.execute("UPDATE veliki_ucenik SET real=? WHERE id=?", (str(text)[:300], vid))
        con.commit()
    except sqlite3.Error:
        pass


def try_enter(con, out, held, tok, q, now, sol, z, b15, icfg, btc, pr=None, lset=None, prioritet=None):
    """Called by live.intra_entries for every candidate the shadow book considered. Enters this account when the
    stored model's best profile is predicted above THR, and, while the owner's switch pravi_novac_nauceno is on, its
    real twin (_enter_real). The demo veliki_trades id or None. Never raises (the učenik's error must not cost the
    rule's pass)."""
    if not on() or (USER, tok) in held:
        return None
    try:
        from league import store as lstore
        from veliki import intra, live, nauceno, rule, sjena
        m = nauceno.load_model(now=now)
        if m is None:
            return None
        k = sjena.known(tok, q, now, z, b15, (pr or {}).get(tok), btc, icfg, sol, size_sol=live.INTRA_DEMO_SOL)
        if k is None:
            return None
        f = nauceno.facts({**k, "opened_ts": int(now)})
        prof, pred = nauceno.predict_best(m, f)
        if prof is None or pred <= THR:
            return None
        if con.execute("SELECT 1 FROM veliki_trades WHERE user=? AND token=? AND status='open'", (USER, tok)).fetchone():
            return None
        if con.execute("SELECT COUNT(*) FROM veliki_trades WHERE user=? AND status='open'",
                       (USER,)).fetchone()[0] >= MAX_OPEN:
            return None
        last = con.execute("SELECT MAX(closed_ts) FROM veliki_trades WHERE token=? AND user=?", (tok, USER)).fetchone()[0]
        if last and now - last < intra.COOLDOWN_S:
            return None
        sym, px, liq, mcap, rt = k["symbol"], k["px"], k["liq"], k["mcap"], k["rt"]
        why = live.guards(tok, q)
        if why:
            _say(out, tok, f"veliki naučeno {sym}: prognoza {pred:+.1%} [{prof}], bez ulaza ({why})", now)
            return None
        tp_px, stop_px = sjena.levels(px, prof, rt)
        size_sol = live.INTRA_DEMO_SOL
        size_usd = size_sol * (sol or live._sol())
        src = (f"veliki naučeno (demo): profil {prof}, prognoza {pred:+.1%} neto, cilj {tp_px / px - 1:+.1%}, stop "
               f"{stop_px / px - 1:+.0%}, najdulje {sjena.MAX_H} h")
        try:
            tid = lstore.buy(con, USER, tok, sym, size_usd, px, liq, src[:200], None, mcap)
        except ValueError as e:
            _say(out, tok, f"veliki naučeno {sym}: prognoza {pred:+.1%} [{prof}], ulaz nije prošao ({e})", now)
            return None
        con.execute("UPDATE trades SET auto=NULL, auto_state=NULL WHERE id=?", (tid,))   # mark() here sells it
        zj = {key: round(z[key], 10) for key in ("lo", "hi", "mid", "width") if (z or {}).get(key) is not None}
        cur = con.execute(
            "INSERT INTO veliki_trades (user, token, symbol, opened_ts, trade_id, size_sol, size_usd, entry_px, tp_px, "
            "stop_px, rt, drt, liq, mcap, cfg, zone, regime, status, why, btc_state, trail, time_h, dip, kind, half_frac, "
            "be_px, first_px, makro, lots, varijanta) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'open',?,?,0.0,?,?,'intra',"
            "0.0,?,?,?,1,?)",
            (USER, tok, sym, int(now), tid, size_sol, size_usd, px, tp_px, stop_px, rt, rule.demo_rt(size_usd, liq), liq,
             mcap, KEY, json.dumps(zj), live._regime(now), src[:200], (btc or {}).get("state"), float(sjena.MAX_H),
             k["dip"], rule.be_price(px, rt, {"exit_slip": 0.0}), px, k["makro"], TAG + prof))
        vid = cur.lastrowid
        con.execute(SCHEMA)
        con.execute("INSERT OR REPLACE INTO veliki_ucenik (id, ts, token, profil, pred, model_ts, facts) VALUES "
                    "(?,?,?,?,?,?,?)", (vid, int(now), tok, prof, pred, m.ts, json.dumps(f, ensure_ascii=False)))
        con.commit()
        held.add((USER, tok))
        out.append(f"veliki naučeno ulaz [{prof}] {sym} {size_sol:g} SOL na MC ${(mcap or 0) / 1e6:,.1f}M: prognoza "
                   f"{pred:+.1%} neto (prag {THR:+.0%}), cilj {tp_px:.6g} ({tp_px / px - 1:+.1%}), stop {stop_px:.6g} "
                   f"({stop_px / px - 1:+.0%}), najdulje {sjena.MAX_H} h; pravi trošak runde {rt:.2%}")
    except Exception as e:  # noqa: BLE001
        try:
            con.rollback()
        except Exception:  # noqa: BLE001
            pass
        out.append(f"veliki naučeno: ulaz nije uspio ({type(e).__name__}: {str(e)[:120]})")
        return None
    if real_on():   # the owner's switch pravi_novac_nauceno: the same entry also with real money (never raises)
        _enter_real(con, out, held, tok, q, now, sol, z, icfg, btc, pr, lset, prioritet,
                    {"k": k, "prof": prof, "pred": pred, "tp_px": tp_px, "stop_px": stop_px, "demo_id": vid,
                     "model_ts": m.ts, "facts": f})
    return vid


def _enter_real(con, out, held, tok, q, now, sol, z, icfg, btc, pr, lset, prioritet, e):
    """The real twin of the demo entry e["demo_id"] (called only while real_on()): see the module text for every
    condition. Buys nothing by itself: live.enter writes the real account's league trade and veliki_trades row, and
    run_trade mirrors that trade into trade/executor.buy, which asks the switch and every cap again. A refusal is
    logged, stored with the demo entry and not tried again. The veliki_trades id or None; never raises and never
    undoes the demo entry."""
    k, prof, pred, demo_id = e["k"], e["prof"], e["pred"], e["demo_id"]
    sym = k["symbol"]
    try:
        from trade import executor, settings
        from veliki import live, sjena
        user = settings.LEAGUE_USER
        p = (pr or {}).get(tok) or {}
        why = _real_ready()
        if not why:
            if (p.get("dip") or {}).get("kind") == "los":
                why = "pad iz lošeg razloga"
            elif p.get("block"):
                why = f"oprez, holderi ({p['block']})"
            elif p.get("risk"):
                why = f"oprez ({p['risk']})"
            elif not lset or tok not in lset:
                why = "token nije na velikoj listi (pravi novac samo tokeni stariji od 15 d)"
            elif (user, tok) in held:
                why = "pravi račun već drži token"
        rid = None
        if not why:
            src = (f"{executor.NAUCENO_SRC} [{prof}], prognoza {pred:+.1%} neto, cilj {e['tp_px'] / k['px'] - 1:+.1%}, "
                   f"stop {e['stop_px'] / k['px'] - 1:+.0%}, najdulje {sjena.MAX_H} h")
            plan = {"src": src, "tp_px": e["tp_px"], "stop_px": e["stop_px"], "time_h": float(sjena.MAX_H), "key": KEY,
                    "varijanta": TAG + prof, "size_sol": executor.NAUCENO_SOL, "rt": k["rt"],
                    "proof": f"prekidač {settings.NAUCENO_SWITCH}; pravilo još nije dokazano na novim danima"}
            _text, why, rid = live.enter(con, user, tok, q, now, sol, z, icfg, live._regime(now), btc, demo_id,
                                         meta=prioritet.meta(tok, pr) if prioritet else None, kind="intra", plan=plan)
        if not rid:
            why = why or "ulaz nije zapisan"
            _note_real(con, demo_id, f"odbijeno: {why}")
            out.append(f"{REAL_HEAD} {sym}: bez kupnje ({why}); demo ulaz #{demo_id} ostaje, ne pokušava se ponovno")
            return None
        con.execute("INSERT OR REPLACE INTO veliki_ucenik (id, ts, token, profil, pred, model_ts, facts, real) VALUES "
                    "(?,?,?,?,?,?,?,?)", (rid, int(now), tok, prof, pred, e["model_ts"],
                                          json.dumps(e["facts"], ensure_ascii=False), f"blizanac demo ulaza #{demo_id}"))
        con.commit()
        _note_real(con, demo_id, f"pravi blizanac #{rid}")
        held.add((user, tok))
        out.append(f"{REAL_HEAD}: kupnja [{prof}] {sym} {executor.NAUCENO_SOL:g} SOL (blizanac demo ulaza #{demo_id}, "
                   f"prekidač {settings.NAUCENO_SWITCH}): cilj {e['tp_px']:.6g}, stop {e['stop_px']:.6g}, najdulje "
                   f"{sjena.MAX_H} h")
        return rid
    except Exception as ex:  # noqa: BLE001
        try:
            con.rollback()
        except Exception:  # noqa: BLE001
            pass
        _note_real(con, demo_id, f"odbijeno: greška {type(ex).__name__}")
        out.append(f"{REAL_HEAD} {sym}: ulaz nije uspio ({type(ex).__name__}: {str(ex)[:120]}); demo ulaz ostaje")
        return None


def _close(con, r, q, reason, now, why=None):
    """Booked exactly as the other midcap exits (live.close: the league sale at the quote, ret at the row's real round
    trip; for a real twin run_trade then sells the real position)."""
    from veliki import live
    _PEND.pop(r["id"], None)
    text = live.close(con, r, q[0], q[1] if len(q) > 1 else None, q[3] if len(q) > 3 else None, reason, now, why=why)
    for pre, head in (("veliki PRAVI NOVAC ", REAL_HEAD + " izlaz"), ("veliki ", "veliki naučeno izlaz")):
        if text.startswith(pre):
            return f"{head} [{profile_of(r) or '?'}] {text[len(pre):]}"
    return text


def _chain(ids, path=None):
    """{league trade id: (status, mode, reason)} of the newest trade.db position that mirrors each (read-only); None
    when trade.db cannot be read."""
    try:
        from trade import settings
        tc = sqlite3.connect(f"file:{path or settings.DB}?mode=ro", uri=True, timeout=5)
        try:
            q = ",".join("?" * len(ids))
            return {lid: (st, mode, why) for lid, st, mode, why in tc.execute(
                f"SELECT league_id, status, mode, reason FROM positions WHERE league_id IN ({q}) ORDER BY id", ids)}
        finally:
            tc.close()
    except Exception:  # noqa: BLE001
        return None


def _drop_unbought(con, r, why, now):
    """A real twin whose real buy did not happen: its league trade is closed (bookkeeping only: there is no real
    position to sell) and its row is closed WITHOUT a result (reason "odbijeno", ret NULL), so it is counted nowhere.
    The line for the log."""
    from league import store as lstore
    from veliki import live
    _PEND.pop(r["id"], None)
    q = (live._ST["q"].get(r["token"]) or (None, 0))[0]
    px = (q[0] if q and q[0] else None) or r["entry_px"]
    booked = None
    try:
        t = con.execute("SELECT status FROM trades WHERE id=?", (r["trade_id"],)).fetchone()
        if t and t[0] == "open":
            booked = lstore.sell(con, r["user"], r["trade_id"], px, (q[1] if q and len(q) > 1 else None) or r.get("liq"),
                                 "veliki naučeno: prava kupnja nije izvršena", exit_rule="smart_other")
    except ValueError:
        pass
    con.execute("UPDATE veliki_trades SET status='closed', closed_ts=?, exit_px=?, reason='odbijeno', ret=NULL, "
                "pnl_usd=NULL, pnl_booked=?, exit_why=? WHERE id=? AND status='open'",
                (int(now), px, booked, str(why)[:300], r["id"]))
    con.commit()
    _note_real(con, r["id"], f"odbijeno na izvršenju: {why}")
    if r.get("link_id"):
        _note_real(con, r["link_id"], f"odbijeno na izvršenju: {why}")
    return (f"{REAL_HEAD} {r['symbol']}: kupnja nije izvršena ({why}); zapis na pravom računu zatvoren bez rezultata, "
            "demo ulaz ostaje, ne pokušava se ponovno")


def _reconcile(con, rows, now, out):
    """The open real twins against trade.db: bought (open / closed, mode live) = confirmed; refused or failed by the
    executor, bought only as a probe, or never taken by the mirror within NO_BUY_S = closed without a result
    (_drop_unbought). The ids that were dropped."""
    todo = [r for r in rows if is_real(r) and r["id"] not in _BOUGHT and r.get("trade_id")]
    if not todo:
        return set()
    got = _chain([r["trade_id"] for r in todo])
    if got is None:
        return set()
    gone = set()
    for r in todo:
        st, mode, reason = got.get(r["trade_id"]) or (None, None, None)
        why = None
        if st in ("open", "closed") and mode == "live":
            _BOUGHT.add(r["id"])
        elif st in ("blocked", "failed"):
            why = reason or st
        elif st in ("open", "closed"):
            why = "kupnja je bila samo proba (Autopilot isključen ili bez ključa)"
        elif st is None and now - r["opened_ts"] >= NO_BUY_S:
            why = "proces pravog trgovanja nije preuzeo ulaz"
        if why:
            try:
                out.append(_drop_unbought(con, r, why, now))
                gone.add(r["id"])
            except Exception as e:  # noqa: BLE001
                con.rollback()
                _say(out, ("drop", r["id"]), f"{REAL_HEAD} {r['symbol']}: neizvršena kupnja nije zatvorena "
                                             f"({type(e).__name__}: {str(e)[:100]})", now)
    return gone


def _safety(r, q, now, q_ts):
    """(reason, why) of the two hard safety exits every REAL midcap position has, for a real twin: a rug collapse
    (league/copy._rugged) or the pool's liquidity at half of its last hour's high on two fresh quotes
    (live.liq_drop); (None, None) otherwise. The demo twin has neither: it stays the registered rule."""
    from league import copy as lcopy
    from veliki import live
    ld = live.liq_drop(r, q, now, q_ts)
    if ld:
        return "likvidnost", ld
    try:
        col = lcopy._rugged(r["token"], q[3] if len(q) > 3 else None, q[1] if len(q) > 1 else None)
    except Exception:  # noqa: BLE001
        col = None
    return ("rug", col.get("text") if isinstance(col, dict) else None) if col else (None, None)


def mark(con, rows, now):
    """The exits of this rule's open rows (the demo account's and their real twins) on this pass's quotes (live.tick,
    right after the day rule's manage() of the other rows): the profile's stop or target crossed on a fresh quote
    arms the exit and the NEXT quote fills it; past sjena.MAX_H the position is sold at the quote. A token without a
    fresh quote waits; a day past the limit it is closed at the last price seen. A real twin also leaves on a rug or
    a liquidity collapse (_safety), and one whose real buy never happened is closed without a result (_reconcile).
    Everything it needs is in the row, so it works the same after a restart (only an armed exit is re-armed by the
    next quote). Runs also with VEL_UCENIK=0 and with the real switch off (they stop entries, never exits). [text]."""
    out = []
    mine = [r for r in rows or () if owns(r)]
    if not mine:
        return out
    try:
        from veliki import live, sjena
        gone = _reconcile(con, mine, now, out)
    except Exception as e:  # noqa: BLE001 - said every time: a real position may be waiting for its exit
        return [f"veliki naučeno: izlazi nisu obrađeni ({type(e).__name__}: {str(e)[:120]})"]
    for r in mine:
        if r["id"] in gone:
            continue
        try:
            q, ts = live._ST["q"].get(r["token"], (None, 0))
            if not q or not q[0]:
                continue
            held_s = now - r["opened_ts"]
            if now - ts > live.STALE_S:
                if held_s >= (sjena.MAX_H + 24) * 3600:
                    out.append(_close(con, r, q, "time", now, why="bez svježe cijene, zadnja poznata"))
                continue
            if is_real(r):
                reason, why = _safety(r, q, now, ts)
                if reason:
                    out.append(_close(con, r, q, reason, now, why=why))
                    continue
            px = q[0]
            pend = _PEND.get(r["id"])
            if pend:
                if ts - pend[1] >= sjena.FILL_GAP_S:
                    out.append(_close(con, r, q, pend[0], now))
                continue
            if px <= r["stop_px"]:
                _PEND[r["id"]] = ("stop", ts)
            elif px >= r["tp_px"]:
                _PEND[r["id"]] = ("tp", ts)
            elif held_s >= sjena.MAX_H * 3600:
                out.append(_close(con, r, q, "time", now))
        except Exception as e:  # noqa: BLE001 - one row's error never stops the others or the tick
            try:
                con.rollback()
            except Exception:  # noqa: BLE001
                pass
            text = (f"{REAL_HEAD if is_real(r) else 'veliki naučeno'}: izlaz {r.get('symbol')} nije uspio "
                    f"({type(e).__name__}: {str(e)[:120]})")
            if is_real(r):
                out.append(text)        # real money: said on every pass until it works
            else:
                _say(out, ("izlaz", r.get("id")), text, now)
    return out


def _band(pred):
    if pred is None:
        return "bez zapisane prognoze"
    for top, name in BANDS:
        if pred < top:
            return name
    return BANDS[-1][1]


def stats(con, now, user=None):
    """{"open", "first_ts", "days", "closed": nauceno._stat over token-days, "usd", "verdict", "by_profile", "by_band",
    "model_ts", "model_ok"} of this rule's rows of one account (default the demo account USER; LEAGUE_USER = the real
    twins): closed rows with a result; SELECTs only, so a read-only connection works. A database without the tables is
    an account without trades."""
    from veliki import nauceno
    user = user or USER
    rows, n_open, first, preds = [], 0, None, {}
    tag = TAG + "%"
    try:
        rows = con.execute("SELECT id, token, opened_ts, ret, pnl_usd, varijanta FROM veliki_trades WHERE user=? AND "
                           "varijanta LIKE ? AND status='closed' AND ret IS NOT NULL ORDER BY closed_ts",
                           (user, tag)).fetchall()
        n_open = con.execute("SELECT COUNT(*) FROM veliki_trades WHERE user=? AND varijanta LIKE ? AND status='open'",
                             (user, tag)).fetchone()[0]
        first = con.execute("SELECT MIN(opened_ts) FROM veliki_trades WHERE user=? AND varijanta LIKE ?",
                            (user, tag)).fetchone()[0]
    except sqlite3.Error:
        pass
    try:
        preds = dict(con.execute("SELECT id, pred FROM veliki_ucenik").fetchall())
    except sqlite3.Error:
        preds = {}
    pairs, by_p, by_b = [], {}, {}
    for rid, tok, opened, ret, _usd, var in rows:
        pair = ((tok, opened // D), ret)
        pairs.append(pair)
        by_p.setdefault(profile_of({"varijanta": var}) or "?", []).append(pair)
        by_b.setdefault(_band(preds.get(rid)), []).append(pair)
    st = nauceno._stat(pairs)
    days = (now - first) / D if first else 0.0
    if st["clusters"] < VERDICT_CLUSTERS and days < VERDICT_DAYS:
        verdict = "mjeri"
    else:
        verdict = "kandidat" if st["lo"] is not None and st["lo"] > 0 else "nema_plusa"
    try:
        mts, ok = nauceno.model_ts(now=now), nauceno.load_model(now=now) is not None
    except Exception:  # noqa: BLE001 - an unreadable model is no model
        mts, ok = None, False
    return {"open": n_open, "first_ts": first, "days": days, "closed": st, "usd": sum(r[4] or 0.0 for r in rows),
            "verdict": verdict, "by_profile": {k: nauceno._stat(v) for k, v in by_p.items()},
            "by_band": {k: nauceno._stat(v) for k, v in by_b.items()}, "model_ts": mts, "model_ok": ok}


def line(con, now, s=None):
    """The hour's line (also the council's): the rule, what is open, the closed trades per token-day, the verdict."""
    if not on():
        return PREFIX + "isključen (VEL_UCENIK=0)"
    s = s or stats(con, now)
    st = s["closed"]
    txt = (f"{PREFIX}pravilo od {RULE_DATE}: ulaz samo uz prognozu iznad {THR:+.0%}".replace("%", " %")
           + f"; otvoreno {s['open']}; zatvoreno {st['n']}")
    if st["n"]:
        ci = f", raspon 90 % [{st['lo']:+.1%}; {st['hi']:+.1%}]" if st["lo"] is not None else ""
        txt += (f" ({st['clusters']} token-dana), prosjek po token-danu {st['ev']:+.1%}{ci}, pogodak {st['hit']:.0%}, "
                f"zbroj {s['usd']:+.2f} $")
    txt += f"; presuda nakon {VERDICT_DAYS} dana ili {VERDICT_CLUSTERS} token-dana: {VERDICT_HR[s['verdict']]}"
    if not s["model_ok"]:
        txt += "; BEZ NOVIH ULAZA: " + (
            "model učenja još nije spremljen" if not s["model_ts"] else
            f"model učenja je stariji od 24 h (zadnji {time.strftime('%d.%m. %H:%M', time.gmtime(s['model_ts']))} UTC)")
    return txt + _real_part(con, now)


def real_stats(con, now):
    """stats() of the real twins (rows of LEAGUE_USER with this rule's tag), plus "on": the owner's switch."""
    from trade import settings
    return {**stats(con, now, settings.LEAGUE_USER), "on": real_on()}


def _real_part(con, now):
    """The real twins in the hour's line: nothing while the switch is off and there never was one."""
    try:
        r = real_stats(con, now)
    except Exception:  # noqa: BLE001
        return ""
    st = r["closed"]
    if not r["on"] and not r["open"] and not st["n"]:
        return ""
    txt = f"; pravi novac (prekidač {'uključen' if r['on'] else 'isključen'}): otvoreno {r['open']}; zatvoreno {st['n']}"
    if st["n"]:
        txt += (f" ({st['clusters']} token-dana), prosjek po token-danu {st['ev']:+.1%} (po demo knjiženju, pravi "
                f"rezultat u SOL je u redu „pravi novac po strategiji”), pogodak {st['hit']:.0%}")
    return txt


def line_ro(now=None, path=None):
    """line() from league.db opened read-only (the council's brief runs outside league.db's writer); None without the
    file."""
    from league import store as lstore
    p = path or lstore.DB
    if not os.path.exists(p):
        return None
    con = sqlite3.connect(f"file:{p}?mode=ro", uri=True, timeout=5)
    try:
        return line(con, now or time.time())
    finally:
        con.close()


def _real_summary(con, now, rnd):
    try:
        r = real_stats(con, now)
    except Exception:  # noqa: BLE001
        return None
    return {"switch": "pravi_novac_nauceno", "on": r["on"], "open": r["open"], "closed": rnd(r["closed"]),
            "note": ("The owner's switch, default off, only his own tap. On: each demo entry is also bought with real "
                     "money (0.1 SOL, the midcap range's caps) and sold at the same target / stop / 72 h. closed is the "
                     "league booking of the real twins; the on-chain result in SOL is the 'naučeno' part of the "
                     "real-money result by strategy.")}


def summary(con, now):
    """The `demo` block of the MCP tool get_shadow_book (learned.demo)."""
    s = stats(con, now)

    def rnd(st):
        return {k: (round(v, 4) if isinstance(v, float) else v) for k, v in (st or {}).items()}
    return {"account": USER, "on": on(), "rule_date": "2026-11-18", "threshold": THR, "max_open": MAX_OPEN,
            "verdict_after": {"days": VERDICT_DAYS, "token_days": VERDICT_CLUSTERS},
            "open": s["open"], "first_ts": s["first_ts"], "days": round(s["days"], 2), "closed": rnd(s["closed"]),
            "pnl_usd": round(s["usd"], 2), "verdict": s["verdict"], "verdict_text": VERDICT_HR[s["verdict"]],
            "by_profile": {k: rnd(v) for k, v in s["by_profile"].items()},
            "by_predicted_band": {k: rnd(v) for k, v in s["by_band"].items()},
            "model_ts": s["model_ts"], "model_ok": s["model_ok"], "line": line(con, now, s),
            "real_money": _real_summary(con, now, rnd),
            "how": ("A separate DEMO account that tests the learner's hypothesis forward: it enters a shadow-book "
                    "candidate only when the stored model predicts its best exit profile above +1 % net, and exits at "
                    "that profile's target, stop or 72 h. The rule was written down on 18.11.2026 before the first "
                    "trade and is not tuned. closed.ev / lo / hi are per token-day, net of the real round trip.")}
