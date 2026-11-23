"""The state NOW of the global machines (see stanja/__init__.py): one row per machine, read-only.

now(): [{"key", "title", "area", "state", "label", "since", "who", "detail", "changes", "caveats"}] for the machines
marked board=True in stanja/registar.py. Every row is read on its own (try / except): a source that cannot be read
gives state "?" with the reason in detail and never costs the others. Nothing is written, nothing is fetched from the
network, no secret is returned (the MCP key only as "set / not set" and when it was made).

17.11. (owner: "Jel sad dobar?" about a key, "uključi Groka nazad ... iste ovlasti koje je imao prije pauziranja"):
neither the owner nor the assistant could tell what was switched on, by whom and since when. This is that answer in
one read, for the page /stanje (the owner) and the MCP tool get_system_state (Grok, the critic, a coding assistant).
"""
import os
import sqlite3
import time

from stanja import registar

UNKNOWN = "?"
CLIENT_S = 3600        # an MCP client that called within the hour is "active" (ui/mcpapi.note_call)
HEART_S = 180          # the same threshold ui/pravitrade._warnings uses for "ne radi"
REAL_SWITCHES = (("pravi_novac_veliki", "midcap raspon"), ("pravi_novac_nauceno", "naučeno pravilo (model učenja)"),
                 ("pravi_novac_sve", "sve strategije"),
                 ("pravi_novac_izvori", "konsenzus izvora"), ("pravi_novac_oscilator", "oscilator"))


def _ro(path):
    if not path or not os.path.exists(path):
        return None
    return sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5)


def _settings(con):
    """{key: (value, ts, who)} of trade.db settings (JSON decoded; a row that does not decode is skipped)."""
    import json
    out = {}
    for k, v, ts, who in con.execute("SELECT k, v, ts, who FROM settings"):
        try:
            out[k] = (json.loads(v), int(ts or 0), who or "")
        except (ValueError, TypeError):
            continue
    return out


def _row(key, state, since=None, who=None, detail=None, sub=None):
    m = registar.BY_KEY[key]
    return {"key": key + (":" + sub if sub else ""), "title": m.title + (f": {sub}" if sub else ""), "area": m.area,
            "state": state, "label": m.label(state) if state != UNKNOWN else "nepoznato",
            "since": int(since) if since else None, "who": who or None, "detail": detail or None,
            "changes": [f"{a} → {b}: {c}" for a, b, c in m.moves], "caveats": list(m.caveats)}


def _try(rows, key, fn, sub=None):
    try:
        got = fn()
        for r in (got if isinstance(got, list) else [got]):
            rows.append(r)
    except Exception as e:  # noqa: BLE001 - one unreadable source never costs the board
        why = str(e) if isinstance(e, RuntimeError) and str(e) else f"ne mogu pročitati ({type(e).__name__})"
        rows.append(_row(key, UNKNOWN, detail=why, sub=sub))


def _flag(s, name):
    from trade import settings
    return settings._flag_value((s.get(f"flag:{name}") or (None,))[0], settings.FLAG_DEFAULTS.get(name, "off"))


def now(now_ts=None, trade_db=None, env=None):
    """The board (see the module text). trade_db / env: for tests; default the real trade.db and os.environ."""
    from trade import settings
    t = int(now_ts or time.time())
    env = os.environ if env is None else env
    rows = []
    con = None
    try:
        con = _ro(trade_db or settings.DB)
        s = _settings(con) if con is not None else None
    except sqlite3.Error:
        s = None
    if s is None:
        s_err = "trade.db se ne može pročitati"

    def need():
        if s is None:
            raise RuntimeError(s_err)
        return s

    def autopilot():
        from trade import executor
        v, ts, who = need().get("on") or (False, 0, "")
        if not v:
            return _row("autopilot_switch", "<off>", ts, who)
        return _row("autopilot_switch", "<live>" if executor.armed() else "<dry>", ts, who,
                    None if executor.armed() else "TRADE_LIVE nije 1 ili ključ nije postavljen")

    def kill():
        from trade import executor
        on = os.path.exists(executor.STOP_FILE)
        return _row("kill_switch", "<active>" if on else "<clear>", os.path.getmtime(executor.STOP_FILE) if on else None)

    def sell_all():
        v, ts, who = need().get("sell_all") or (0, 0, "")
        return _row("sell_all", "<running>" if v else "<idle>", v if v else None, who if v else None)

    def switches():
        out = []
        try:
            v = need().get("pravi_novac_pauza")
            paused = bool(v and v[0] and v[0].get("on"))
        except Exception:  # noqa: BLE001 - an unreadable pause is shown as none; the switches' own rows stand
            paused = False
        for name, what in REAL_SWITCHES:
            f = _flag(need(), name)
            note = None if f["mode"] in ("live", "off") else f"spremljeno '{f['mode']}', što znači isključeno"
            if paused and f["mode"] != "live":   # 19.11.: the owner's pause of every automatic real buy
                note = (note + "; " if note else "") + "pauza kupnji pravim novcem (nalog vlasnika 19.11.)"
            out.append(_row("real_money_switch", "live" if f["mode"] == "live" else "off", f["since"], f["who"], note,
                            sub=what))
        return out

    def flags():
        by = {}
        for name in settings.FLAGS:
            by.setdefault(_flag(need(), name)["mode"], []).append(name)
        newest = max((_flag(need(), n) for n in settings.FLAGS), key=lambda f: f["since"])
        txt = "; ".join(f"{registar.label('flag', m)}: {', '.join(sorted(by[m]))}" for m in ("live", "paper", "shadow")
                        if by.get(m))
        return _row("flag", "live" if by.get("live") else "paper" if by.get("paper") else "off", newest["since"],
                    newest["who"], f"{len(by.get('live', []))} uživo, {len(by.get('paper', []))} demo, "
                                   f"{len(by.get('shadow', []))} sjena, {len(by.get('off', []))} isključeno. {txt}")

    def day_loss():
        from trade import executor
        need()
        st = executor.switch_status(con, t)
        return _row("day_loss_stop", "<stopped>" if st["stopped"] else "<allowed>", None, None,
                    f"danas {st['pnl']:+.3f} SOL, strop −{st['max_loss_day']:g} SOL; kupnji {st['buys']} od "
                    f"{st['max_buys_day']}, otvoreno {st['open']} od {st['max_open']}")

    def grok():
        v = (need().get("grok_autotrade") or ({}, 0, ""))[0]
        v = v if isinstance(v, dict) else {}
        pu = v.get("paused_until") or 0
        st = "<off>" if not v.get("on") else "<paused>" if pu and t < pu else "<on>"
        lim = ", ".join(f"{k.replace('grok_', '')} {need()[k][0]:g}" for k in
                        ("grok_max_sol_per_trade", "grok_max_sol_per_day", "grok_max_open", "grok_max_loss_day")
                        if k in need() and isinstance(need()[k][0], (int, float)))
        return _row("grok_autotrade", st, v.get("since"), v.get("who"),
                    (f"pauza: {v.get('pause_reason')}. " if st == "<paused>" and v.get("pause_reason") else "")
                    + (f"limiti koje je vlasnik upisao: {lim}" if lim else "limiti: zadani"))

    def plans():
        v, ts, who = need().get("exit_plans_paused") or (False, 0, "")
        return _row("exit_plans_pause", "<paused>" if v else "<running>", ts or None, who)

    def proof():
        v, ts, who = need().get("veliki_dokaz") or ("", 0, "")
        if str(v) == "nalog_vlasnika":
            return _row("veliki_proof", "nalog_vlasnika", ts, who)
        from veliki import gate
        return _row("veliki_proof", gate.proof_mode())

    def mcp():
        if (env.get("MCP_API_KEY") or "").strip():
            return _row("mcp_access", "<on>", None, None, "ključ je postavljen na Renderu (MCP_API_KEY)")
        v, ts, who = need().get("mcp_key") or ("", 0, "")
        return _row("mcp_access", "<on>" if v else "<off>", ts or None, who,
                    "ključ sa stranice Autopilot; „od” je trenutak kad je zadnji put napravljen ili ugašen" if ts else None)

    def client():
        v, _ts, who = need().get("mcp_seen") or ({}, 0, "")
        v = v if isinstance(v, dict) else {}
        if not v.get("ts"):
            return _row("mcp_client", "<never>")
        age = t - int(v["ts"])
        return _row("mcp_client", "<active>" if age <= CLIENT_S else "<quiet>", int(v["ts"]), None,
                    f"zadnji alat {v.get('tool') or '?'}; poziva na dan {v.get('day') or '?'}: {v.get('n_day') or 0}")

    def heart():
        v, _ts, _who = need().get("heartbeat") or (0, 0, "")
        if not v:
            return _row("bot_heartbeat", "<never>")
        return _row("bot_heartbeat", "<alive>" if t - int(v) <= HEART_S else "<silent>", int(v), "bot",
                    f"zadnji znak prije {max(0, t - int(v))} s")

    def btc():
        from veliki import live
        b = live.btc_state(t)
        return _row("btc_regime", b["state"], b.get("last_end"), None,
                    (b.get("why") or "") + ("" if b.get("known") else " (BTC podaci nisu svježi)"))

    def macro():
        from veliki import makro
        v = makro.current(t)
        if not v:
            return _row("macro_regime", UNKNOWN, detail="nema očitanja mlađeg od 3 h: strategija ga vodi kao neutralno")
        op = (v.get("oporavak") or {})
        return _row("macro_regime", v.get("regime") or "neutral", v.get("ts"), None,
                    "oporavak: " + ("DA" if op.get("ok") else "ne") + (f" ({op.get('why')})" if op.get("why") else ""))

    def fokus():
        f = _flag(need(), "fokus_midcap")
        return _row("fokus_midcap", "live" if f["mode"] == "live" else "off", f["since"], f["who"])

    def measure():
        from league import mjera
        from league import store as lstore
        m = mjera.mode()
        sw = None
        lc = _ro(lstore.DB)
        if lc is not None:
            try:
                r = lc.execute("SELECT v FROM mjera_kv WHERE k='prebaceno'").fetchone()
                import json as _json
                sw = _json.loads(r[0]) if r else None
            except sqlite3.Error:
                sw = None
            finally:
                lc.close()
        state = "<switched>" if m == "auto" and sw else m
        det = (f"potvrđeno: {sw.get('n')} parova, medijan razlike {sw.get('median_pp')} pp" if sw else
               "mjerenje teče u svakom načinu")
        return _row("wallet_measure_mode", state, (sw or {}).get("ts"), None, det)

    def social():
        from ops import drustveni
        st = drustveni.state(t, create=False)
        m = st["mode"]
        state = {"open": "<open>", "closed": "<closed>", "first": "<first>", "always": "<always>"}.get(m, "<nopersist>")
        when = drustveni.when
        det = (f"zadnji {when(st['last'])}, " if st.get("last") else "") + (
            f"otvoren do {when(st['end'])}, " if m == "open" else "") + (
            f"sljedeći {when(st['next'])}" if st.get("next") else "još nije bilo prozora")
        return _row("social_window", state, st.get("last"), "sat",
                    f"{det}; svakih {drustveni.days_word()} dana po {drustveni.window_h():g} h")

    try:
        for key, fn in (("autopilot_switch", autopilot), ("kill_switch", kill), ("sell_all", sell_all),
                        ("real_money_switch", switches), ("day_loss_stop", day_loss), ("grok_autotrade", grok),
                        ("exit_plans_pause", plans), ("mcp_access", mcp), ("mcp_client", client),
                        ("bot_heartbeat", heart),
                        ("veliki_proof", proof), ("btc_regime", btc), ("macro_regime", macro), ("fokus_midcap", fokus),
                        ("social_window", social), ("wallet_measure_mode", measure),
                        ("flag", flags)):
            _try(rows, key, fn)
    finally:
        if con is not None:
            con.close()
    return rows


def text(rows, now_ts=None):
    """The board as plain lines (a log line, an agent's context): "Grok autotrade: ugašen · od 15.11. 10:12 · Jure"."""
    out = []
    for r in rows:
        when = time.strftime("%d.%m. %H:%M UTC", time.gmtime(r["since"])) if r.get("since") else ""
        out.append(" · ".join(x for x in (f"{r['title']}: {r['label']}", f"od {when}" if when else "", r.get("who") or "",
                                          r.get("detail") or "") if x))
    return out


def mcp(args=None):
    """get_system_state: {"now", "board": [...]}; with definitions=true also the registry (states, moves, caveats);
    area / key narrow the registry part."""
    args = args or {}
    t = int(time.time())
    out = {"now": t, "board": now(t),
           "how_to_read": "state = the code's literal (<...> = derived, no literal); label = the Croatian word; since "
                          "/ who = when and by whom it was last set, when stored; changes = what moves it."}
    if args.get("definitions") or args.get("area") or args.get("key"):
        out["definitions"] = registar.describe(area=args.get("area"), key=args.get("key"))
    return out
