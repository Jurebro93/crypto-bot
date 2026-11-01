"""The WhatsApp digest: one short plain-Croatian message for the traders' group.

Sections (each left out when it has nothing): what's new in the app (share/novosti.json, newer than the last
update that went to the group), Natjecanje top 3 + the bot, best and worst trade of the last 24 h, strong tokens
(✨ = new on the list today), link to the app. WhatsApp formatting: *bold*, _italic_. Kept well under WhatsApp's
limits and short enough to read on a phone.

Every app change worth telling the group goes into share/novosti.json as {"datum": "YYYY-MM-DD", "tekst": "..."},
newest first, written for traders (what they can do now), not for developers.
"""
import json
import os
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
NEWS = os.path.join(HERE, "novosti.json")
STATE = os.path.join(ROOT, "output", "whatsapp-state.json")
DAY = 86400
MAX_NEWS = 6
NEWS_DAYS = 7
DEFAULT_URL = "https://crypto-bot-ylvn.onrender.com"


def base_url():
    return (os.environ.get("PUBLIC_URL") or os.environ.get("RENDER_EXTERNAL_URL") or DEFAULT_URL).rstrip("/")


def load_state():
    try:
        with open(STATE) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_state(**kw):
    st = load_state()
    st.update(kw)
    try:
        os.makedirs(os.path.dirname(STATE), exist_ok=True)
        with open(STATE + ".tmp", "w") as f:
            json.dump(st, f, indent=1)
        os.replace(STATE + ".tmp", STATE)
    except OSError as e:
        print(f"whatsapp: stanje nije spremljeno: {e}", flush=True)
    return st


def _key(item):
    return f"{item.get('datum')}|{item.get('tekst')}"


def news(now=None, path=None, sent=None, days=NEWS_DAYS):
    """Entries of novosti.json from the last `days` days that have not gone to the group yet (newest first)."""
    now = now or time.time()
    try:
        with open(path or NEWS, encoding="utf-8") as f:
            items = json.load(f)
    except (OSError, ValueError):
        return []
    sent = set(load_state().get("sent_news") or []) if sent is None else set(sent)
    out = [i for i in items if i.get("tekst") and _day_ts(i.get("datum")) >= now - days * DAY and _key(i) not in sent]
    return sorted(out, key=lambda i: i.get("datum") or "", reverse=True)[:MAX_NEWS]


def mark_shared(how, now=None, path=None):
    """The update went to the group (copied on /whatsapp or sent automatically): its news are not repeated."""
    now = now or time.time()
    st = load_state()
    sent = list(st.get("sent_news") or [])
    for i in news(now, path, sent=sent):
        sent.append(_key(i))
    return save_state(sent_news=sent[-200:], **{f"{how}_ts": int(now)})


def _day_ts(day):
    import datetime as dt
    try:
        return dt.datetime.strptime(day, "%Y-%m-%d").timestamp()
    except (TypeError, ValueError):
        return 0


def _money(x):
    s = f"{abs(x):,.0f}" if abs(x) >= 100 else f"{abs(x):,.2f}"
    return ("+" if x >= 0 else "−") + "$" + s


def _pct(x):
    return f"{x:+.0%}".replace("-", "−") if x is not None else ""


def league_part(now=None):
    """Natjecanje for the message and the picture: players by rank, bot, best and worst trade of the last 24 h."""
    from league import store
    from ui import leaguedash
    from ui.paper import market
    now = now or time.time()
    con = store.connect()
    try:
        mk = market({t["token"] for t in store.trades(con, status="open")})
        d = leaguedash.compute(con, mk)
    finally:
        con.close()
    players = [{"user": p["user"], "rank": p["rank"], "equity": round(p["equity"], 2), "ret": p["ret"],
                "move": p.get("move")} for p in d["players"]]
    bot = d.get("bot")
    trades = []
    for p in d["players"]:
        for t in p["closed_list"]:
            if (t.get("closed_ts") or 0) >= now - DAY:
                trades.append((t["pnl_usd"] or 0, t.get("ret"), p["user"], t, False))
        for t in p["open_list"]:
            if t.get("pnl") is not None:
                trades.append((t["pnl"], t.get("pct"), p["user"], t, True))

    def tr(x):
        if not x:
            return None
        pnl, ret, user, t, is_open = x
        return {"user": user, "symbol": t.get("symbol") or t["token"][:6], "pnl": round(pnl, 2), "ret": ret,
                "open": is_open}
    best = max(trades, key=lambda x: x[0], default=None)
    worst = min(trades, key=lambda x: x[0], default=None)
    return {"players": players, "bot_ret": bot["ret"] if bot else None,
            "best": tr(best) if best and best[0] > 0 else None,
            "worst": tr(worst) if worst and worst[0] < 0 else None}


def strong_tokens(n=3):
    """Top of the "jaki" list (dugo.db); new = not on the previous day's list."""
    from dugo import store as dstore
    con = dstore.ro()
    if con is None:
        return []
    try:
        days = [r[0] for r in con.execute("SELECT DISTINCT day FROM snap WHERE kind='jaki' ORDER BY day DESC LIMIT 2")]
        if not days:
            return []
        rows = con.execute("""SELECT s.mint, t.symbol, s.mcap FROM snap s JOIN tokens t ON t.mint=s.mint
            WHERE s.kind='jaki' AND s.day=? ORDER BY s.rank LIMIT ?""", (days[0], n)).fetchall()
        prev = {r[0] for r in con.execute("SELECT mint FROM snap WHERE kind='jaki' AND day=?", (days[1],))} \
            if len(days) > 1 else None
    finally:
        con.close()
    return [{"symbol": sym or mint[:6], "mcap": mc, "new": prev is not None and mint not in prev} for mint, sym, mc in rows]


def _mc(mc):
    if not mc:
        return ""
    return f"{mc / 1e9:.1f} mlrd $".replace(".", ",") if mc >= 1e9 else f"{mc / 1e6:.0f} M$"


def _date(now):
    import datetime as dt
    try:
        from zoneinfo import ZoneInfo
        d = dt.datetime.fromtimestamp(now, ZoneInfo("Europe/Zagreb"))
    except Exception:  # noqa: BLE001
        d = dt.datetime.utcfromtimestamp(now)
    return f"{d.day}.{d.month}.{d.year}."


def collect(now=None, with_league=True, with_tokens=True, repeat=False):
    """Everything the message and the picture show, as plain data (JSON for the picture on /whatsapp).
    repeat: show the latest app news again even if they already went to the group."""
    now = now or time.time()
    out = {"date": _date(now), "news": news(now, sent=[] if repeat else None), "league": None, "tokens": [], "url": base_url() + "/natjecanje"}
    if with_league:
        try:
            out["league"] = league_part(now)
        except Exception as e:  # noqa: BLE001 - a missing part must not stop the message
            print(f"whatsapp: natjecanje: {type(e).__name__}: {e}", flush=True)
    if with_tokens:
        try:
            out["tokens"] = strong_tokens()
        except Exception as e:  # noqa: BLE001
            print(f"whatsapp: jaki tokeni: {type(e).__name__}: {e}", flush=True)
    return out


MEDAL = {1: "🥇", 2: "🥈", 3: "🥉"}


def _trade(t):
    return (f"{t['user']} · *{t['symbol']}* {_pct(t['ret'])} ({_money(t['pnl'])})"
            + (" · još otvoren" if t["open"] else ""))


def text(d):
    """WhatsApp message: short lines, a bold heading per block, one empty line between blocks, nothing wraps
    into a wall of text on a phone."""
    blocks = [[f"📊 *KriptoRadar* · {d['date']}"]]
    if d["news"]:
        b = ["🆕 *ŠTO JE NOVO*"]
        for i in d["news"]:
            b.append(f"▪️ *{i['naslov']}*: {i['tekst']}" if i.get("naslov") else f"▪️ {i['tekst']}")
        blocks.append(b)
    lg = d.get("league")
    if lg and lg["players"]:
        b = ["🏆 *NATJECANJE*"]
        for p in [p for p in lg["players"] if p["rank"] <= 3][:5]:
            b.append(f"{MEDAL.get(p['rank'], '▫️')} {p['user']} · ${p['equity']:,.0f} ({_pct(p['ret'])})")
        if lg.get("bot_ret") is not None:
            b.append(f"🤖 Bot · {_pct(lg['bot_ret'])}")
        blocks.append(b)
        b = []
        if lg.get("best"):
            b.append("🚀 Najbolji: " + _trade(lg["best"]))
        if lg.get("worst"):
            b.append("🩸 Najgori: " + _trade(lg["worst"]))
        if b:
            blocks.append(["💰 *TRADEOVI (24 h)*"] + b)
    if d.get("tokens"):
        b = ["🌱 *JAKI TOKENI*"]
        for t in d["tokens"]:
            b.append(f"▪️ *{t['symbol']}*" + (f" · {_mc(t['mcap'])}" if t.get("mcap") else "") + (" ✨ novo" if t["new"] else ""))
        blocks.append(b)
    blocks.append([f"👉 {d['url']}", "_Demo novac, nije financijski savjet._"])
    return "\n\n".join("\n".join(b) for b in blocks)


def build(now=None, with_league=True, with_tokens=True):
    """The message text. App news: only what has not gone to the group yet."""
    return text(collect(now, with_league, with_tokens))
