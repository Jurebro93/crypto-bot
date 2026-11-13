"""Optional real-time listener on a Telegram user account (Telethon / MTProto), the paid-ish upgrade over t.me/s:
messages arrive in under a second, and private groups the account is a member of are read too.

Needs TG_API_ID + TG_API_HASH (my.telegram.org) and TG_SESSION (a StringSession, made once with
`python3 run_tg.py login` on any computer) and the `telethon` package. Without them nothing starts.
Joins at most telethon.join_per_day of the best active channels a day (up to max_joined), so the account looks
like a person and not a bot. Writes posts through tg.store.save_posts (source 'telethon').
"""
import asyncio
import os
import time

from tg import reader, store


def enabled():
    return all(os.environ.get(k) for k in ("TG_API_ID", "TG_API_HASH", "TG_SESSION"))


def _post(msg, text):
    raw = text or ""
    from kol.collect import cas_in
    cas = cas_in(raw)
    fwd = None
    if getattr(msg, "fwd_from", None) and getattr(msg.fwd_from, "from_name", None):
        fwd = reader.channel_name(msg.fwd_from.from_name)
    return {"post": msg.id, "ts": int(msg.date.timestamp()), "text": raw[:600], "cas": cas,
            "tickers": sorted({t.upper() for t in reader._TICKER.findall(raw)}), "views": msg.views or 0,
            "fwd_from": fwd, "links": sorted(reader.links_in(raw))}


async def _join_some(client, cfg, log):
    from telethon.tl.functions.channels import JoinChannelRequest
    con = store.connect()
    day = time.strftime("%Y-%m-%d")
    joined_today = store.kv_get(con, "joined_" + day, 0)
    total = con.execute("SELECT COUNT(*) FROM channels WHERE joined=1").fetchone()[0]
    want = con.execute("""SELECT name FROM channels WHERE status='active' AND joined=0
                          ORDER BY COALESCE(last_ca_ts,0) DESC LIMIT ?""",
                       (max(0, min(cfg["join_per_day"] - joined_today, cfg["max_joined"] - total)),)).fetchall()
    for (name,) in want:
        try:
            await client(JoinChannelRequest(name))
            con.execute("UPDATE channels SET joined=1 WHERE name=?", (name,))
            joined_today += 1
            log(f"telethon: pridružen @{name}")
            await asyncio.sleep(60)
        except Exception as e:
            log(f"telethon join @{name}: {type(e).__name__}: {e}")
            break
    store.kv_set(con, "joined_" + day, joined_today)
    con.commit()
    con.close()


def run(cfg, log=print):
    if not enabled():
        log("telethon: nema TG_API_ID/TG_API_HASH/TG_SESSION, ne pokrećem")
        return
    from telethon import TelegramClient, events
    from telethon.sessions import StringSession
    client = TelegramClient(StringSession(os.environ["TG_SESSION"]), int(os.environ["TG_API_ID"]),
                            os.environ["TG_API_HASH"])

    @client.on(events.NewMessage())
    async def on_msg(ev):
        chat = await ev.get_chat()
        name = reader.channel_name(getattr(chat, "username", None) or "") or f"id{ev.chat_id}"
        p = _post(ev.message, ev.raw_text)
        if not (p["cas"] or p["tickers"]):
            return
        con = store.connect()
        store.add_candidates(con, [name], "telethon")
        con.execute("UPDATE channels SET joined=1, title=COALESCE(title, ?) WHERE name=?",
                    (getattr(chat, "title", None), name))
        new = store.save_posts(con, name, [p], "telethon")
        con.execute("UPDATE channels SET lag_s=? WHERE name=?", (max(0, time.time() - p["ts"]), name))
        con.commit()
        con.close()
        if new:
            log(f"telethon: @{name} CA {', '.join(p['cas'])}")

    async def main():
        await client.start()
        log("telethon: slušam uživo")
        while True:
            await _join_some(client, cfg["telethon"], log)
            await asyncio.sleep(3600)

    with client:
        client.loop.run_until_complete(main())


def login():
    """Interactive, once: prints the TG_SESSION string to put on Render."""
    from telethon.sync import TelegramClient
    from telethon.sessions import StringSession
    api_id, api_hash = int(input("TG_API_ID: ")), input("TG_API_HASH: ")
    with TelegramClient(StringSession(), api_id, api_hash) as c:
        print("TG_SESSION =", c.session.save())
