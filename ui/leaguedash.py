"""Natjecanje dashboard: podium, leaderboard, account value chart, highlights, player cards and every trade.

Built from league.db (league/store.py, league/history.py) and the live DexScreener prices the page already
fetches. /api/natjecanje returns the live numbers as JSON; the page refreshes them every minute without a reload.
Each player keeps one colour everywhere (by their place in UI_USERS, never by rank); the bot is grey.
"""
import json
import time

from league import history, store
from ui import data
from ui.html import ago, badge, esc, num, signed, table, tlink, ts, usd

REFRESH_S = 60
DAY = 86400

# categorical slots in fixed order (validated palette, light / dark), then the bot's neutral grey
CSS = """
.lg{--p1:#2a78d6;--p2:#eb6834;--p3:#1baf7a;--p4:#eda100;--p5:#e87ba4;--p6:#008300;--p7:#6250d6;--p8:#e34948;--pb:#8a8f98}
@media (prefers-color-scheme:dark){.lg{--p1:#3987e5;--p2:#d95926;--p3:#199e70;--p4:#c98500;--p5:#d55181;--p6:#008300;--p7:#9085e9;--p8:#e66767;--pb:#7d838c}}
.lg h2{display:flex;align-items:baseline;gap:10px;flex-wrap:wrap}.lg h2 small{font-weight:400;color:var(--mut);font-size:13px}
.about{margin:0 0 10px;display:flex;flex-wrap:wrap;gap:6px 12px;align-items:center;font-size:13px}
.about .soc{border:1px solid var(--line);border-radius:999px;padding:2px 10px;text-decoration:none;color:var(--fg)}
.av{display:inline-flex;align-items:center;justify-content:center;width:30px;height:30px;border-radius:50%;color:#fff;
 font-weight:700;font-size:14px;flex:none;background:var(--c)}.av.img{background:var(--c) center/cover no-repeat;
 box-shadow:0 0 0 2px var(--c)}.av.sm{width:22px;height:22px;font-size:11px}
.pod{display:grid;grid-template-columns:repeat(auto-fit,minmax(210px,1fr));gap:12px;margin:12px 0}
.pc{position:relative;background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px 16px 12px;
 border-top:4px solid var(--c);cursor:pointer;transition:box-shadow .15s,transform .15s}
.pc:hover{box-shadow:0 6px 18px rgba(16,24,40,.10);transform:translateY(-1px)}
.pc .hd{display:flex;align-items:center;gap:10px}.pc .nm{font-weight:700;font-size:16px}.pc .rk{margin-left:auto;font-size:22px}
.pc .eq{font-size:26px;font-weight:700;margin:8px 0 0;letter-spacing:-.02em}.pc .pr{font-size:14px;font-weight:600}
.pc .mini{display:flex;gap:12px;flex-wrap:wrap;color:var(--mut);font-size:12px;margin-top:8px}.pc .mini b{color:var(--fg)}
.pc.me{box-shadow:0 0 0 2px var(--c) inset}
.mv{font-size:12px;font-weight:600}.mv.up{color:var(--good)}.mv.dn{color:var(--bad)}
.hl{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:10px;margin:10px 0}
.hl .stat .v{font-size:18px}.hl .stat .s{font-size:12px;color:var(--mut);margin-top:2px}
.chartbox{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:12px 14px;position:relative}
.ctl{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin-bottom:8px}
.chip{border:1px solid var(--line);background:var(--card);color:var(--fg);border-radius:999px;padding:3px 11px;font:13px system-ui,sans-serif;
 cursor:pointer;display:inline-flex;align-items:center;gap:6px}.chip:hover{border-color:var(--acc)}
.chip.on{background:color-mix(in srgb,var(--acc) 12%,var(--card));border-color:var(--acc);font-weight:600}
.chip.off{opacity:.45}.chip i{display:inline-block;width:14px;height:3px;border-radius:2px;background:var(--c)}
.chip i.dash{background:repeating-linear-gradient(90deg,var(--c) 0 4px,transparent 4px 7px)}
.ctl .sp{flex:1}
#eqc{width:100%;height:300px;display:block;touch-action:pan-y}@media(max-width:700px){#eqc{height:240px}}
#eqc text{font:11px system-ui,sans-serif;fill:var(--mut)}#eqc .lbl{font-weight:600;fill:var(--fg);font-size:12px}
#eqtip{position:absolute;pointer-events:none;background:var(--card);border:1px solid var(--line);border-radius:8px;padding:7px 10px;
 font-size:12px;box-shadow:0 6px 18px rgba(0,0,0,.18);display:none;min-width:150px;z-index:5}
#eqtip .r{display:flex;align-items:center;gap:6px;justify-content:space-between}#eqtip .r span:last-child{font-weight:600}
details.pl{background:var(--card);border:1px solid var(--line);border-left:4px solid var(--c);border-radius:10px;margin:8px 0;padding:0}
details.pl>summary{color:var(--fg);display:flex;align-items:center;gap:10px;padding:10px 14px;cursor:pointer;list-style:none;flex-wrap:wrap}
details.pl>summary::-webkit-details-marker{display:none}details.pl>summary::after{content:'▾';margin-left:auto;color:var(--mut)}
details.pl[open]>summary::after{content:'▴'}details.pl .in{padding:0 14px 12px}
details.pl .grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:8px;margin:4px 0 10px}
details.pl .stat .v{font-size:17px}
@media(max-width:700px){.pod{grid-template-columns:1fr 1fr;gap:8px}.pc{padding:10px 11px 9px}.pc .eq{font-size:19px;margin-top:6px}
 .pc .nm{font-size:14px}.pc .rk{font-size:18px}.pc .av{width:24px;height:24px;font-size:12px}.pc .pr{font-size:12px}
 .pc .mini{gap:2px 8px;font-size:11px}.hl{grid-template-columns:1fr 1fr;gap:8px}.hl .stat{padding:8px 10px}.hl .stat .v{font-size:15px}}
details.more>summary{color:var(--fg);cursor:pointer;font-weight:600;font-size:15px;margin:18px 0 4px}
.upd{font-size:12px;color:var(--mut)}a.chip{text-decoration:none}
"""


def _colors(users):
    return {u: f"var(--p{i % 8 + 1})" for i, u in enumerate(users)}


def _streak(closed):
    """('W', 3) for three wins in a row on the latest closed trades, ('L', 2) for two losses."""
    seq = sorted(closed, key=lambda t: t["closed_ts"] or 0, reverse=True)
    if not seq:
        return None, 0
    kind = "W" if (seq[0]["pnl_usd"] or 0) > 0 else "L"
    n = 0
    for t in seq:
        if ("W" if (t["pnl_usd"] or 0) > 0 else "L") != kind:
            break
        n += 1
    return kind, n


def _streak_text(s):
    kind, n = s
    if not n:
        return "–"
    return f"{'🔥' if kind == 'W' else '🧊'} {n} {'dobitn' if kind == 'W' else 'gubitn'}{'i' if n == 1 else 'a'} zaredom"


def _tie_rank(values, me):
    return 1 + sum(1 for v in values if v > me + 1e-6)


def _open_live(t, mk):
    """Live numbers of one open position: (pnl $, pnl %, mcap now) or Nones without a price."""
    v = mk.get(t["token"])
    if not v or not v[0]:
        return None, None, None
    price, liq, _, mc = v
    val = store.value(t, price, liq)
    pnl = val - t["size_usd"]
    mc_now = mc or (t["entry_mcap"] * price / t["entry_px"] if t.get("entry_mcap") and t.get("entry_px") else None)
    return pnl, pnl / t["size_usd"] if t["size_usd"] else None, mc_now


def _bot(since):
    """Bot's demo account on the same footing as a player: $1,000 at the competition start + its trades since."""
    try:
        tr = data.paper_trades()
    except Exception:
        return None
    base = store.START_USD
    pts = history.bot_series(tr, since or time.time(), base)
    open_pnl = sum(t["pnl_usd"] or 0 for t in tr if t["status"] == "open" and (t["opened_ts"] or 0) >= (since or 0))
    closed = [t for t in tr if t["status"] == "closed" and (t["closed_ts"] or 0) >= (since or 0)]
    eq = pts[-1][1] + open_pnl
    try:
        from paper import sim
        bank = sim.load_config().get("bankroll_usd", 1000)
    except Exception:
        bank = 1000
    total = sum(t["pnl_usd"] or 0 for t in tr)
    return {"user": "bot", "equity": eq, "profit": eq - base, "ret": (eq - base) / base, "pts": pts,
            "open": sum(1 for t in tr if t["status"] == "open"), "closed": len(closed),
            "wins": sum(1 for t in closed if (t["pnl_usd"] or 0) > 0), "total_ret": total / bank if bank else 0}


def compute(con, mk):
    """Everything the dashboard shows, as plain data (also the JSON for the live refresh)."""
    live = {t: v[:3] for t, v in mk.items()}
    users = store.users()
    board = store.leaderboard(con, live)
    ser = history.series(con, users)
    now = time.time()
    t0 = history.start_ts(con)
    players = []
    for r in board:
        u = r["user"]
        closed = store.trades(con, u, "closed")
        opened = store.trades(con, u, "open")
        for t in opened:
            t["pnl"], t["pct"], t["mc_now"] = _open_live(t, mk)
        pts = ser.get(u, []) + [(int(now), r["equity"])]
        worst = min(closed, key=lambda t: t["pnl_usd"] or 0, default=None)
        players.append({**r, "closed_list": closed, "open_list": opened, "worst": worst, "streak": _streak(closed),
                        "pts": pts, "prev": history.value_at(pts, now - DAY),
                        "winrate": r["wins"] / r["closed"] if r["closed"] else None,
                        "avg": sum(t["ret"] or 0 for t in closed) / len(closed) if closed else None,
                        "in_open": sum(t["size_usd"] for t in opened)})
    eqs = [p["equity"] for p in players]
    # rank change only among players who already had an account 24 h ago, compared with their own ranks then and now
    had = [p for p in players if p["prev"] is not None]
    flat = len({round(p["prev"], 2) for p in had}) <= 1
    for p in players:
        p["rank"] = _tie_rank(eqs, p["equity"])
        p["move"] = None
        if not flat and p["prev"] is not None:
            p["move"] = (_tie_rank([q["prev"] for q in had], p["prev"])
                         - _tie_rank([q["equity"] for q in had], p["equity"]))
    bot = _bot(t0)
    if bot:
        bot["pts"] = bot["pts"] + [(int(now), bot["equity"])]
    return {"users": users, "players": players, "bot": bot, "start": t0, "now": now}


def _mv(move):
    if move is None:
        return ""
    if move > 0:
        return f'<span class="mv up" title="mjesta gore u zadnja 24 h">▲{move}</span>'
    if move < 0:
        return f'<span class="mv dn" title="mjesta dolje u zadnja 24 h">▼{-move}</span>'
    return ""


def _medal(rank):
    return "🥇🥈🥉"[rank - 1] if rank <= 3 else f"{rank}."


def _live(key, html):
    return f'<span data-live="{esc(key)}">{html}</span>'


def live_pnl(trade_id, pnl):
    """PnL $ of an open position that the live refresh keeps current."""
    k = str(trade_id)
    return (f'<span class="{_cls(pnl)}" data-live-cls="tp:{k}">{_live("tp:" + k, f"{pnl:+.2f}" if pnl is not None else "–")}</span>')


def _cls(x):
    return "pos" if (x or 0) > 0 else "neg" if (x or 0) < 0 else ""


def _av(u, color, sm=False):
    """Round badge: the player's profile picture (⚙️ Postavke) or the first letter in his colour."""
    try:
        from league import profiles
        url = profiles.avatar_url(u)
    except Exception:
        url = None
    if url:
        return (f'<span class="av{" sm" if sm else ""} img" style="--c:{color};background-image:url({esc(url)})" '
                f'role=img aria-label="{esc(u)}"></span>')
    return f'<span class="av{" sm" if sm else ""}" style="--c:{color}">{esc(u[:1].upper())}</span>'


def podium(d, me):
    col = _colors(d["users"])
    cards = []
    for p in d["players"]:
        u = p["user"]
        eq, pr, ret = f"${p['equity']:,.2f}", f"{p['profit']:+,.2f}", f"{p['ret']:+.1%}"
        wr = f"{p['winrate']:.0%}" if p["winrate"] is not None else "–"
        cards.append(
            f'<div class="pc{" me" if u == me else ""}" style="--c:{col[u]}" data-open="pl-{esc(u)}" role=button tabindex=0 '
            f'title="Klikni za sve tradeove igrača {esc(u)}">'
            f'<div class=hd>{_av(u, col[u])}<span class=nm>{esc(u)}{" (ti)" if u == me else ""}</span> {_mv(p["move"])}'
            f'<span class=rk>{_medal(p["rank"])}</span></div>'
            f'<div class=eq>{_live("eq:" + u, eq)}</div>'
            f'<div class="pr {_cls(p["profit"])}" data-live-cls="pr:{esc(u)}">{_live("pr:" + u, pr + " $")} · '
            f'{_live("ret:" + u, ret)}</div>'
            f'<div class=mini><span>tradeova <b>{p["open"] + p["closed"]}</b></span><span>uspješnost <b>{wr}</b></span>'
            f'<span>otvoreno <b>{p["open"]}</b></span><span>{_streak_text(p["streak"])}</span></div></div>')
    return "<div class=pod>" + "".join(cards) + "</div>"


def board_table(d, me):
    col = _colors(d["users"])
    rows = []
    for p in d["players"]:
        u = p["user"]
        eq, pr, ret = f"${p['equity']:,.2f}", f"{p['profit']:+,.2f}", f"{p['ret']:+.1%}"
        b, w = p["best"], p["worst"]
        rows.append([
            (f'{_medal(p["rank"])} {_av(u, col[u], True)} <b>{esc(u)}</b>{" (ti)" if u == me else ""} {_mv(p["move"])}',
             p["rank"], ""),
            (_live("eq:" + u, f"${p['equity']:,.2f}"), p["equity"], "n"),
            (f'<span class="{_cls(p["profit"])}" data-live-cls="pr:{esc(u)}">{_live("pr:" + u, pr)}</span>',
             p["profit"], "n"),
            (f'<span class="{_cls(p["ret"])}" data-live-cls="ret:{esc(u)}">{_live("ret:" + u, ret)}</span>',
             p["ret"], "n"),
            num(p["cash"], "${:,.2f}"),
            num(p["open"] + p["closed"]),
            (f"{p['winrate']:.0%} <span class=mut>({p['wins']}/{p['closed']})</span>" if p["closed"] else "–",
             p["winrate"] if p["winrate"] is not None else -1, "n"),
            num(p["open"]),
            (_streak_text(p["streak"]), (p["streak"][1] if p["streak"][0] == "W" else -p["streak"][1]), ""),
            (f"{esc(b['symbol'] or b['token'][:6])} <span class=pos>{b['pnl_usd']:+.2f} $</span>" if b and (b["pnl_usd"] or 0) > 0
             else "–", (b["pnl_usd"] or 0) if b else -1e9, ""),
            (f"{esc(w['symbol'] or w['token'][:6])} <span class=neg>{w['pnl_usd']:+.2f} $</span>" if w and (w["pnl_usd"] or 0) < 0
             else "–", (w["pnl_usd"] or 0) if w else 1e9, ""),
        ])
    bot = d["bot"]
    if bot:
        rows.append([('<span class="av sm" style="--c:var(--pb)">🤖</span> bot <span class=mut>(za usporedbu)</span>', 99, ""),
                     num(bot["equity"], "${:,.2f}"), signed(bot["profit"]), signed(bot["ret"], "{:+.1%}"), ("–", -1, "n"),
                     num(bot["closed"]), (f"{bot['wins'] / bot['closed']:.0%} <span class=mut>({bot['wins']}/{bot['closed']})</span>"
                                          if bot["closed"] else "–", bot["wins"] / bot["closed"] if bot["closed"] else -1, "n"),
                     num(bot["open"]), "–", "–", "–"])
    return table(["Igrač", ("Stanje računa", "n"), ("Profit $", "n"), ("Povrat", "n"), ("Slobodno", "n"),
                  ("Broj tradeova", "n"), ("Uspješnost", "n"), ("Otvoreno", "n"), "Serija", "Najbolji trade", "Najgori trade"],
                 rows, "lboard")


def highlights(d):
    trades = []
    for p in d["players"]:
        for t in p["closed_list"]:
            trades.append((t["pnl_usd"] or 0, t["ret"], p["user"], t, False))
        for t in p["open_list"]:
            if t.get("pnl") is not None:
                trades.append((t["pnl"], t["pct"], p["user"], t, True))
    tiles = []
    if d["players"]:
        lead = d["players"][0]
        top = [p["user"] for p in d["players"] if p["rank"] == 1]
        if len(top) > 1:
            tiles.append(("Vodi", "izjednačeno", f'{esc(", ".join(top))} · {lead["profit"]:+,.2f} $', ""))
        else:
            tiles.append(("Vodi", esc(lead["user"]), f'{lead["profit"]:+,.2f} $ ({lead["ret"]:+.1%})', _cls(lead["profit"])))
    if trades:
        best = max(trades, key=lambda x: x[0])
        worst = min(trades, key=lambda x: x[0])
        for label, x in (("Najbolji trade", best), ("Najgori trade", worst)):
            pnl, ret, u, t, is_open = x
            tiles.append((label, f'{esc(t["symbol"] or t["token"][:6])} <span class="{_cls(pnl)}">{pnl:+,.2f} $</span>',
                          f'{esc(u)} · {ret:+.0%}' + (" · još otvoren" if is_open else ""), ""))
    n_open = sum(p["open"] for p in d["players"])
    n_all = sum(p["open"] + p["closed"] for p in d["players"])
    tiles.append(("Tradeova ukupno", f"{n_all}", f"{n_open} otvorenih sada", ""))
    bot = d["bot"]
    if bot and d["players"]:
        avg = sum(p["ret"] for p in d["players"]) / len(d["players"])
        who = "ljudi vode" if avg > bot["ret"] else "bot vodi" if avg < bot["ret"] else "izjednačeno"
        tiles.append(("Ljudi protiv bota", f'<span class="{_cls(avg - bot["ret"])}">{who}</span>',
                      f"prosjek igrača {avg:+.1%}, bot {bot['ret']:+.1%} od početka natjecanja", ""))
    return "<div class=hl>" + "".join(
        f'<div class=stat><div class=l>{lbl}</div><div class="v {c}">{v}</div><div class=s>{s}</div></div>'
        for lbl, v, s, c in tiles) + "</div>"


def chart_data(d):
    col = _colors(d["users"])
    ser = [{"name": p["user"], "c": col[p["user"]], "pts": [[int(t), round(v, 2)] for t, v in p["pts"]]}
           for p in sorted(d["players"], key=lambda p: d["users"].index(p["user"]) if p["user"] in d["users"] else 99)]
    if d["bot"]:
        ser.append({"name": "bot", "c": "var(--pb)", "dash": 1, "pts": [[int(t), round(v, 2)] for t, v in d["bot"]["pts"]]})
    return {"series": ser, "base": store.START_USD, "now": int(d["now"])}


def chart(d):
    cd = chart_data(d)
    chips = "".join(f'<button class="chip" data-s="{i}" style="--c:{s["c"]}"><i{" class=dash" if s.get("dash") else ""}></i>'
                    f'{esc(s["name"])}</button>' for i, s in enumerate(cd["series"]))
    rng = "".join(f'<button class="chip{" on" if k == "all" else ""}" data-r="{k}">{t}</button>'
                  for k, t in (("1", "24 h"), ("7", "7 dana"), ("all", "Sve")))
    return (f'<div class=chartbox><div class=ctl>{chips}<span class=sp></span>{rng}</div>'
            f'<svg id=eqc role=img aria-label="Stanje računa igrača kroz vrijeme"></svg><div id=eqtip></div></div>'
            f'<script>window.EQ={json.dumps(cd)}</script>')


def _trade_rows(players, col, with_player=True):
    rows = []
    for p in players:
        u = p["user"]
        eq, pr, ret = f"${p['equity']:,.2f}", f"{p['profit']:+,.2f}", f"{p['ret']:+.1%}"
        for t in p["open_list"] + p["closed_list"]:
            is_open = t["status"] == "open"
            if is_open:
                pnl, pct, mc = t.get("pnl"), t.get("pct"), t.get("mc_now")
                st = (badge("otvoreno", "good"), "s:open", "")
            else:
                pnl, pct = t["pnl_usd"], t["ret"]
                mc = t.get("exit_mcap") if t.get("exit_mcap") is not None else (
                    t["entry_mcap"] * t["exit_px"] / t["entry_px"] if t.get("entry_mcap") and t.get("entry_px") else None)
                st = (f'prodano <span class=mut>{ago(t["closed_ts"])[0]}</span>', "s:closed", "")
            k = str(t["id"])
            pnl_html = (f'<span class="{_cls(pnl)}" data-live-cls="tp:{k}">{_live("tp:" + k, f"{pnl:+.2f}" if pnl is not None else "–")}</span>'
                        if is_open else signed(pnl)[0])
            pct_html = (f'<span class="{_cls(pct)}" data-live-cls="tr:{k}">{_live("tr:" + k, f"{pct:+.0%}" if pct is not None else "–")}</span>'
                        if is_open else signed(pct, "{:+.0%}")[0])
            row = [(f'{_av(u, col[u], True)} <b>{esc(u)}</b>', f"p:{u}", "")] if with_player else []
            row += [tlink(t["token"], t["symbol"]), ts(t["opened_ts"]), usd(t["size_usd"]), usd(t.get("entry_mcap")),
                    ((_live("tm:" + k, usd(mc)[0]) if is_open else usd(mc)[0]), mc or -1, "n"),
                    (pnl_html, pnl if pnl is not None else -1e18, "n"), (pct_html, pct if pct is not None else -1e18, "n"),
                    st, esc(t.get("note") or t.get("source") or "")]
            rows.append((t["opened_ts"] or 0, row))
    return [r for _, r in sorted(rows, key=lambda x: -x[0])]


TRADE_HEAD = ["Token", "Kupljeno", ("Ulog", "n"), ("Ulazni MC", "n"), ("MC sada / izlaz", "n"), ("PnL $", "n"),
              ("Povrat", "n"), "Status", "Odakle / napomena"]


def all_trades(d):
    col = _colors(d["users"])
    rows = _trade_rows(d["players"], col)
    chips = ('<div class=ctl id=tflt><button class="chip on" data-f="">Svi</button>'
             + "".join(f'<button class=chip data-f="p:{esc(u)}" style="--c:{col[u]}"><i></i>{esc(u)}</button>'
                       for u in d["users"])
             + '<span class=sp></span><button class="chip on" data-g="">Sve</button>'
               '<button class=chip data-g="s:open">Otvoreni</button><button class=chip data-g="s:closed">Zatvoreni</button></div>')
    return chips + table(["Igrač"] + TRADE_HEAD, rows, "allp", empty="Nitko još nije kupio nijedan token.")


def _about(u):
    """Short bio + social links the player entered in ⚙️ Postavke (nothing when empty)."""
    try:
        from league import profiles
        bio, links = profiles.get(u).get("bio"), profiles.links(u)
    except Exception:
        return ""
    if not bio and not links:
        return ""
    ls = " ".join(
        (f'<a class=soc href="{esc(url)}" target=_blank rel="noopener nofollow">{icon} {esc(h if label != "Web stranica" else "web")}</a>'
         if url else f'<span class=soc title="{esc(label)}">{icon} {esc(h)}</span>') for label, icon, url, h in links)
    return (f'<div class=about>{"<i>" + esc(bio) + "</i> " if bio else ""}{ls}</div>')


def player_cards(d, me):
    col = _colors(d["users"])
    out = []
    for p in d["players"]:
        u = p["user"]
        eq, pr, ret = f"${p['equity']:,.2f}", f"{p['profit']:+,.2f}", f"{p['ret']:+.1%}"
        b, w = p["best"], p["worst"]
        stats = [("Stanje računa", _live("eq:" + u, f"${p['equity']:,.2f}"), ""),
                 ("Profit", _live("pr:" + u, f"{p['profit']:+,.2f} $"), _cls(p["profit"])),
                 ("Slobodno za ulaganje", f"${p['cash']:,.2f}", ""),
                 ("U otvorenim pozicijama", f"${p['in_open']:,.2f}", ""),
                 ("Uspješnost", f"{p['winrate']:.0%} ({p['wins']}/{p['closed']})" if p["closed"] else "–", ""),
                 ("Prosječni trade", f"{p['avg']:+.0%}" if p["avg"] is not None else "–", _cls(p["avg"])),
                 ("Najbolji", f"{esc(b['symbol'] or b['token'][:6])} {b['pnl_usd']:+.2f} $" if b else "–", "pos" if b and (b["pnl_usd"] or 0) > 0 else ""),
                 ("Najgori", f"{esc(w['symbol'] or w['token'][:6])} {w['pnl_usd']:+.2f} $" if w else "–", "neg" if w and (w["pnl_usd"] or 0) < 0 else ""),
                 ("Serija", _streak_text(p["streak"]), "")]
        grid = "".join(f'<div class=stat><div class=l>{lbl}</div><div class="v {c}">{v}</div></div>' for lbl, v, c in stats)
        rows = _trade_rows([p], col, with_player=False)
        about = _about(u)
        out.append(
            f'<details class=pl id="pl-{esc(u)}" style="--c:{col[u]}"><summary>{_av(u, col[u])}<b>{_medal(p["rank"])} {esc(u)}'
            f'{" (ti)" if u == me else ""}</b> {_mv(p["move"])}<span>{_live("eq:" + u, eq)}</span>'
            f'<span class="{_cls(p["profit"])}" data-live-cls="pr:{esc(u)}">{_live("pr:" + u, pr + " $")}</span>'
            f'<span class=mut>{p["open"]} otvoreno · {p["closed"]} zatvoreno</span></summary>'
            f'<div class=in>{about}<div class=grid>{grid}</div>'
            + table(TRADE_HEAD, rows, f"pt-{esc(u)}", empty=f"{esc(u)} još nije kupio nijedan token.")
            + "</div></details>")
    return "".join(out)


def dashboard(con, mk, me):
    d = compute(con, mk)
    when = f"Natjecanje traje od {ts(d['start'], '%d.%m.%Y')[0]}. " if d["start"] else ""
    return (f"<style>{CSS}</style><div class=lg>"
            f'<h2>Ljestvica <small><span class=upd id=upd>brojke se same osvježavaju svake minute</span></small></h2>'
            "<p class=tdesc>Poredak po stanju računa: slobodan novac + ono što bi otvorene pozicije donijele da ih prodaš "
            "sada (uz naknadu i klizanje cijene). ▲▼ je promjena mjesta u zadnja 24 sata. Klikni karticu igrača za "
            "njegove tradeove.</p>"
            + podium(d, me) + highlights(d)
            + "<h2>Svi tradeovi</h2><p class=tdesc>Svi vide sve: tko je kada kupio, na kojem market capu, gdje je sada i koliko "
              "je u plusu ili minusu. Filtriraj po igraču i statusu bez ponovnog učitavanja. PnL otvorenih je ono što bi "
              "prodaja sada donijela.</p>" + all_trades(d)
            + "<details class=more id=allnum open><summary>Sve brojke po igraču</summary><p class=tdesc>Klikni naslov stupca za sortiranje. Uspješnost = udio zatvorenih "
              "tradeova u plusu. Serija = koliko zadnjih zatvorenih tradeova zaredom je bilo u plusu (🔥) ili minusu (🧊). "
              "Bot je račun koji alat vodi sam, preračunat na istih $1,000 od početka natjecanja; cijela njegova "
              "povijest je u <a href=/paper>Demo tradingu</a>"
            + (f" (od prvog dana {d['bot']['total_ret']:+.0%})" if d["bot"] else "") + ".</p>"
            + board_table(d, me) + "</details>"
            + f"<h2>Stanje računa kroz vrijeme</h2><p class=tdesc>{when}Bilježi se svakih 15 minuta, s otvorenim pozicijama po "
              "živoj cijeni; prije početka bilježenja graf broji samo zatvorene tradeove. Prijeđi prstom ili mišem preko "
              "grafa za iznose, klikni ime da ga sakriješ ili pokažeš. Isprekidana linija je početnih "
              f"${store.START_USD:,.0f}.</p>" + chart(d)
            + "<h2>Igrači</h2><p class=tdesc>Otvori igrača za njegove brojke i sve tradeove, otvorene i zatvorene.</p>"
            + player_cards(d, me)

            + f"</div><script>{JS.replace('__REFRESH__', str(REFRESH_S * 1000))}</script>")


def api(con, mk):
    """Live numbers for the page: {key: [text, sign]} with the keys the page's data-live spans carry."""
    d = compute(con, mk)
    out = {}
    for p in d["players"]:
        u = p["user"]
        eq, pr, ret = f"${p['equity']:,.2f}", f"{p['profit']:+,.2f}", f"{p['ret']:+.1%}"
        out["eq:" + u] = [f"${p['equity']:,.2f}", 0]
        out["pr:" + u] = [f"{p['profit']:+,.2f}", p["profit"]]
        out["ret:" + u] = [f"{p['ret']:+.1%}", p["ret"]]
        for t in p["open_list"]:
            k = str(t["id"])
            if t.get("pnl") is not None:
                out["tp:" + k] = [f"{t['pnl']:+.2f}", t["pnl"]]
                out["tr:" + k] = [f"{t['pct']:+.0%}", t["pct"]]
            if t.get("mc_now"):
                out["tm:" + k] = [usd(t["mc_now"])[0], 0]
    return json.dumps({"v": out, "ts": int(d["now"]), "chart": chart_data(d)})


JS = r"""
(()=>{
const $=s=>document.querySelector(s),NS='http://www.w3.org/2000/svg';
// phone: the full numbers table is folded (the cards above already show the main numbers)
if(innerWidth<700){const a=$('#allnum');if(a)a.open=false}
// podium card -> open that player's card
document.querySelectorAll('.pc[data-open]').forEach(c=>{const go=()=>{const d=document.getElementById(c.dataset.open);
 if(d){d.open=true;d.scrollIntoView({behavior:'smooth',block:'start'})}};c.onclick=go;c.onkeydown=e=>{if(e.key==='Enter')go()}});
// trade filters (player, status) without reload
const tf=$('#tflt');if(tf){let f='',g='';const apply=()=>{document.querySelectorAll('#allp tbody tr').forEach(r=>{
 const ok=(!f||r.querySelector(`td[data-v="${CSS.escape(f)}"]`))&&(!g||r.querySelector(`td[data-v="${g}"]`));r.style.display=ok?'':'none'})};
 tf.querySelectorAll('[data-f]').forEach(b=>b.onclick=()=>{f=b.dataset.f;tf.querySelectorAll('[data-f]').forEach(x=>x.classList.toggle('on',x===b));apply()});
 tf.querySelectorAll('[data-g]').forEach(b=>b.onclick=()=>{g=b.dataset.g;tf.querySelectorAll('[data-g]').forEach(x=>x.classList.toggle('on',x===b));apply()})}
// account value chart
const svg=$('#eqc'),tip=$('#eqtip');if(!svg||!window.EQ)return;
let range='all',hidden=new Set();
const fmt=v=>'$'+v.toLocaleString('en-US',{minimumFractionDigits:2,maximumFractionDigits:2});
const at=(pts,t)=>{let v=null;for(const p of pts){if(p[0]>t)break;v=p[1]}return v};
const dfmt=(t,long)=>{const d=new Date(t*1000),p=n=>String(n).padStart(2,'0');return long?`${p(d.getDate())}.${p(d.getMonth()+1)}. ${p(d.getHours())}:${p(d.getMinutes())}`:`${p(d.getDate())}.${p(d.getMonth()+1)}.`};
function el(n,a,parent){const e=document.createElementNS(NS,n);for(const k in a)e.setAttribute(k,a[k]);(parent||svg).appendChild(e);return e}
function draw(){
 const E=window.EQ,W=svg.clientWidth||600,H=svg.clientHeight||300,L=58,R=58,T=12,B=26;svg.setAttribute('viewBox',`0 0 ${W} ${H}`);svg.innerHTML='';
 const t1=E.now,first=Math.min(...E.series.map(s=>s.pts.length?s.pts[0][0]:t1)),t0=range==='all'?first:Math.max(first,t1-(+range)*86400);
 const vis=E.series.map((s,i)=>({...s,i})).filter(s=>!hidden.has(s.i)&&s.pts.length);
 // each series clipped to [t0,t1] with its value at t0 as the first point (step line)
 const cl=vis.map(s=>{const v0=at(s.pts,t0);const p=s.pts.filter(p=>p[0]>t0&&p[0]<=t1);return {...s,cp:(v0!=null?[[t0,v0]]:[]).concat(p)}});
 let ys=[E.base];cl.forEach(s=>s.cp.forEach(p=>ys.push(p[1])));let y0=Math.min(...ys),y1=Math.max(...ys);const pad=Math.max((y1-y0)*.12,5);y0-=pad;y1+=pad;
 const X=t=>L+(t-t0)/Math.max(1,t1-t0)*(W-L-R),Y=v=>T+(y1-v)/(y1-y0)*(H-T-B);
 // grid + y labels
 for(let k=0;k<=4;k++){const v=y0+(y1-y0)*k/4,y=Y(v);el('line',{x1:L,x2:W-R,y1:y,y2:y,stroke:'var(--line)','stroke-width':1});
  el('text',{x:L-6,y:y+4,'text-anchor':'end'}).textContent='$'+Math.round(v).toLocaleString('en-US')}
 const yb=Y(E.base);el('line',{x1:L,x2:W-R,y1:yb,y2:yb,stroke:'var(--mut)','stroke-width':1,'stroke-dasharray':'3 4',opacity:.7});
 // x labels
 const nx=Math.max(2,Math.min(6,Math.floor((W-L-R)/90)));for(let k=0;k<=nx;k++){const t=t0+(t1-t0)*k/nx;
  el('text',{x:X(t),y:H-6,'text-anchor':k===0?'start':k===nx?'end':'middle'}).textContent=dfmt(t,t1-t0<3*86400)}
 // lines (step: value holds until the next point)
 const ends=[];
 cl.forEach(s=>{if(!s.cp.length)return;let d='';s.cp.forEach((p,j)=>{d+=(j?`H${X(p[0])}V${Y(p[1])}`:`M${X(p[0])},${Y(p[1])}`)});
  const last=s.cp[s.cp.length-1];d+=`H${X(t1)}`;
  el('path',{d,fill:'none',stroke:s.c,'stroke-width':2,'stroke-linejoin':'round','stroke-dasharray':s.dash?'5 4':'none'});
  el('circle',{cx:X(t1),cy:Y(last[1]),r:4,fill:s.c,stroke:'var(--card)','stroke-width':2});ends.push({y:Y(last[1]),s})});
 // direct labels at the right end, nudged apart
 ends.sort((a,b)=>a.y-b.y);for(let k=1;k<ends.length;k++)if(ends[k].y-ends[k-1].y<13)ends[k].y=ends[k-1].y+13;
 ends.forEach(e=>{el('text',{x:X(t1)+8,y:e.y+4,class:'lbl'}).textContent=e.s.name});
 // hover: crosshair + every visible player's value at that time
 const cross=el('line',{y1:T,y2:H-B,stroke:'var(--mut)','stroke-width':1,opacity:0});
 const hit=el('rect',{x:L,y:T,width:W-L-R,height:H-T-B,fill:'transparent'});
 const move=ev=>{const r=svg.getBoundingClientRect(),cx=(ev.touches?ev.touches[0].clientX:ev.clientX)-r.left,
  t=t0+(Math.min(Math.max(cx,L),W-R)-L)/(W-L-R)*(t1-t0);cross.setAttribute('x1',X(t));cross.setAttribute('x2',X(t));cross.setAttribute('opacity',.6);
  const rows=cl.map(s=>({s,v:at(s.cp,t)})).filter(x=>x.v!=null).sort((a,b)=>b.v-a.v);
  tip.innerHTML=`<div class=mut style="margin-bottom:4px">${dfmt(t,true)}</div>`+rows.map(x=>`<div class=r><span><span class="av sm" style="--c:${x.s.c};width:10px;height:10px"></span> ${x.s.name}</span><span>${fmt(x.v)}</span></div>`).join('');
  tip.style.display='block';const bx=svg.parentNode.getBoundingClientRect(),ox=r.left-bx.left,oy=r.top-bx.top;
  let left=cx+ox+14;if(left+tip.offsetWidth>bx.width-6)left=cx+ox-tip.offsetWidth-14;
  tip.style.left=Math.max(4,left)+'px';tip.style.top=(oy+10)+'px'};
 const out=()=>{tip.style.display='none';cross.setAttribute('opacity',0)};
 hit.addEventListener('mousemove',move);hit.addEventListener('touchstart',move,{passive:true});hit.addEventListener('touchmove',move,{passive:true});
 hit.addEventListener('mouseleave',out);hit.addEventListener('touchend',()=>setTimeout(out,1500))}
document.querySelectorAll('.chartbox [data-s]').forEach(b=>b.onclick=()=>{const i=+b.dataset.s;hidden.has(i)?hidden.delete(i):hidden.add(i);b.classList.toggle('off',hidden.has(i));draw()});
document.querySelectorAll('.chartbox [data-r]').forEach(b=>b.onclick=()=>{range=b.dataset.r;document.querySelectorAll('.chartbox [data-r]').forEach(x=>x.classList.toggle('on',x===b));draw()});
let rt;addEventListener('resize',()=>{clearTimeout(rt);rt=setTimeout(draw,150)});draw();
// live numbers every minute, no reload
const upd=$('#upd');let last=Date.now();
async function poll(){if(document.hidden)return;try{const r=await fetch('/api/natjecanje',{cache:'no-store'});if(!r.ok)throw 0;const j=await r.json();
 for(const k in j.v){const [txt,sg]=j.v[k];document.querySelectorAll(`[data-live="${CSS.escape(k)}"]`).forEach(e=>{e.textContent=txt;const td=e.closest('td');
   if(td&&td.dataset.v!==undefined&&sg)td.dataset.v=sg});document.querySelectorAll(`[data-live-cls="${CSS.escape(k)}"]`).forEach(e=>{
   e.classList.toggle('pos',sg>0);e.classList.toggle('neg',sg<0)})}
 window.EQ=j.chart;draw();last=Date.now();upd.textContent='osvježeno upravo sada'}catch(e){upd.textContent='veza prekinuta, pokušavam ponovo…'}}
setInterval(()=>{const s=Math.round((Date.now()-last)/1000);if(!upd.textContent.startsWith('veza'))upd.textContent=s<10?'osvježeno upravo sada':`osvježeno prije ${s<60?s+' s':Math.round(s/60)+' min'}`},10000);
setInterval(poll,__REFRESH__);document.addEventListener('visibilitychange',()=>{if(!document.hidden&&Date.now()-last>__REFRESH__)poll()});
})();
"""
