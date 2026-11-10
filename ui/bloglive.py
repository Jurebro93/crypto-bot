"""Daily data blocks of the public blog: "Stanje danas" under the posts that are about our own measurements.

10.11.2026. (Jure): "osvježili smo taj i taj blog s novim podacima". The posts are written once, with numbers from a
dated snapshot ("copy of 8 Nov 2026"), and their text does not change. A post listed in BLOCK_OF now ends with a small
block of the same kind of numbers, counted fresh from our own databases by the daily 02:00 job (run_web.py daily) and
kept in public.db blog_live. The text keeps its dated snapshot; the block says what the database holds today.

- refresh(): the job. Counts every block, stores it, returns the English slugs of the posts whose numbers changed
  tonight; only those count as "blog osvježen novim podacima" in the site log (ui/sitelog.py).
- html(en_slug, lang): the block for a post, '' when there is none (no job yet, no data, post without a block).
- modified(en_slug): the day the post's numbers last changed (dateModified, sitemap lastmod), or None.
Only our own databases are read: no network, no paid source. A block with fewer than two numbers is not shown.
"""
import json
import sqlite3
import time

from ui.html import esc
from ui import sitelog

# post (English slug) -> block. Only posts whose subject is something we count ourselves every day.
BLOCK_OF = {
    "what-is-a-kol-in-crypto": "kol", "influencer-clustering": "kol", "why-big-influencer-calls-are-hard-to-trade": "kol",
    "top-crypto-twitter-accounts-by-call-accuracy": "kol", "how-to-check-a-kol-track-record": "kol",
    "best-crypto-telegram-channels": "telegram", "memecoin-telegram-groups-explained": "telegram",
    "what-is-wallet-tracking": "wallets", "what-is-copy-trading": "wallets", "tokens-sent-to-kol-wallets": "wallets",
    "how-to-spot-a-rug-pull": "rugs", "bundles-and-snipers": "rugs", "what-is-a-pump-and-dump": "rugs",
}

# block -> its numbers in display order: (key, English label, Croatian label)
BLOCKS = {
    "kol": (("x_accounts", "X accounts tracked", "praćenih X računa"),
            ("board", "on the public leaderboard", "na javnoj ljestvici"),
            ("x_measured", "calls measured", "izmjerenih poziva"),
            ("x_clean10", "accounts with 10+ clean calls", "računa s 10+ čistih poziva")),
    "telegram": (("tg_channels", "Telegram channels tracked", "praćenih Telegram kanala"),
                 ("tg_measured", "Telegram calls measured", "izmjerenih Telegram poziva"),
                 ("tg_clean10", "channels with 10+ clean calls", "kanala s 10+ čistih poziva")),
    "wallets": (("wallets", "wallets tracked", "praćenih novčanika"),
                ("scored", "wallets scored", "ocijenjenih novčanika"),
                ("trades", "wallet trades recorded", "zabilježenih tradeova novčanika"),
                ("kol_wallets", "influencer wallets known", "poznatih novčanika influencera")),
    "rugs": (("tokens", "tokens checked", "provjerenih tokena"),
             ("rugs", "rugs caught and archived", "uhvaćenih i arhiviranih rugova")),
}
# block -> where the live table is (English, Croatian, English label, Croatian label); None = members only
MORE = {
    "kol": ("/influencers", "/hr/influenceri", "Open the live leaderboard", "Otvori ljestvicu uživo"),
    "telegram": ("/telegram-channels", "/hr/telegram-kanali", "Open the live channel list", "Otvori popis kanala uživo"),
    "rugs": ("/rug-check", "/hr/provjera", "Rug check for the top 100 coins", "Provjera ruga za top 100 coina"),
}
T = {   # {d}: the day as the blog writes dates; the Croatian one ends with a full stop itself ("10. studenoga 2026.")
    "en": dict(h="Today's numbers", sub="Counted from our database on {d}. Refreshed every night. The figures in the "
               "text above are from the dated snapshot named next to them."),
    "hr": dict(h="Stanje danas", sub="Izbrojano iz naše baze {d} Osvježava se svake noći. Brojke u tekstu iznad su sa "
               "snimke čiji je datum naveden uz njih."),
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS blog_live (key TEXT PRIMARY KEY, ts INTEGER, day TEXT, changed TEXT, data TEXT);
"""


# ---------- counting (the daily job) --------------------------------------------------------------------------------

def measure():
    """{block: {key: number}} from our own databases. A number that cannot be read is left out, never guessed."""
    one, f = sitelog._one, sitelog._file
    kol, wal, hype = f("KOL_DB", "kol.db"), f("WALLET_DB", "wallets.db"), f("HYPE_DB", "hype.db")
    not_x = "handle NOT LIKE 'tg:%' AND handle NOT LIKE 'w:%'"
    measured = "kind='call' AND max24 IS NOT NULL"
    k = {"x_accounts": one(kol, f"SELECT COUNT(*) FROM kols WHERE {not_x}"),
         "x_measured": one(kol, f"SELECT COUNT(*) FROM calls WHERE {measured} AND {not_x}")}
    tg = {"tg_channels": one(f("TG_DB", "tg.db"), "SELECT COUNT(*) FROM channels WHERE status IN ('active','quiet','slow')"),
          "tg_measured": one(kol, f"SELECT COUNT(*) FROM calls WHERE {measured} AND handle LIKE 'tg:%'")}
    try:   # one read of the kols table and one of the calls table, both in this short process
        from ui import kolstats as KS, public
        k["board"] = len(public.influencers())      # exactly the rows of the public leaderboard
        con = public._con()
        if con is not None:
            try:
                clean = KS.clean_counts(con)
            finally:
                con.close()
            if clean:   # accounts and channels with enough clean calls for a verdict on their page
                k["x_clean10"] = sum(1 for h, n in clean.items() if not h.startswith("tg:") and n >= KS.MIN_CLEAN)
                tg["tg_clean10"] = sum(1 for h, n in clean.items() if h.startswith("tg:") and n >= KS.MIN_CLEAN)
    except Exception as e:  # noqa: BLE001
        print(f"blog uživo: ljestvica i čisti pozivi nisu izbrojani: {type(e).__name__}: {e}", flush=True)
    tiers, rugs = one(hype, "SELECT COUNT(*) FROM token_tier"), one(hype, "SELECT COUNT(*) FROM rug_archive")
    out = {
        "kol": k, "telegram": tg,
        "wallets": {"wallets": one(wal, "SELECT COUNT(*) FROM wallets"),
                    "scored": one(wal, "SELECT COUNT(*) FROM wallets WHERE scored_at IS NOT NULL"),
                    "trades": one(wal, "SELECT MAX(rowid) FROM wallet_trades"),
                    "kol_wallets": one(kol, "SELECT COUNT(*) FROM kol_wallets")},
        "rugs": {"tokens": (tiers or 0) + (rugs or 0) if (tiers is not None or rugs is not None) else None, "rugs": rugs},
    }
    return {b: {key: int(x) for key, x in d.items() if x} for b, d in out.items()}


def refresh(now=None, measured=None, db=None):
    """Count every block and store it. Returns the English slugs of the posts whose block changed (first numbers
    count as a change: the post got its block). A block that could not be counted keeps what it had."""
    ts = int(time.time() if now is None else now)
    day = sitelog.local_day(ts)
    cur = measure() if measured is None else measured
    changed = set()
    con = sqlite3.connect(db or sitelog.path(), timeout=30)
    try:
        con.executescript(SCHEMA)
        old = {r[0]: r for r in con.execute("SELECT key, changed, data FROM blog_live")}
        for key in BLOCKS:
            data = {k: v for k, v in (cur.get(key) or {}).items() if v}
            if len(data) < 2:
                continue
            was = old.get(key)
            same = was is not None and _json(was[2]) == data
            if not same:
                changed.add(key)
            con.execute("INSERT INTO blog_live (key, ts, day, changed, data) VALUES (?,?,?,?,?) ON CONFLICT(key) DO UPDATE "
                        "SET ts=excluded.ts, day=excluded.day, changed=excluded.changed, data=excluded.data",
                        (key, ts, day, was[1] if same else day, json.dumps(data)))
        con.commit()
    finally:
        con.close()
    return [slug for slug, key in BLOCK_OF.items() if key in changed]


def _json(s):
    try:
        return json.loads(s) if s else {}
    except ValueError:
        return {}


# ---------- reading (blog pages; they are cached by ui.public.route) -------------------------------------------------

def blocks(db=None):
    """{block: {day, changed, data}} of every stored block (one read of a table of four rows)."""
    out = {}
    for key, day, changed, data in sitelog._read("SELECT key, day, changed, data FROM blog_live", (), db):
        data = _json(data)
        if len(data) >= 2:
            out[key] = {"day": day, "changed": changed, "data": data}
    return out


def modified(en_slug, stored=None, db=None):
    """'YYYY-MM-DD' of the night the post's numbers last changed, or None (no block, nothing stored yet).
    stored: blocks() read once by a caller that asks for many posts (the sitemap)."""
    key = BLOCK_OF.get(en_slug)
    b = (blocks(db) if stored is None else stored).get(key) if key else None
    return b["changed"] if b else None


def _num(x, lang):
    s = f"{x:,.0f}"
    return s if lang == "en" else s.replace(",", ".")


def html(en_slug, lang="en", db=None):
    """The block for one post, '' when there is nothing to show."""
    key = BLOCK_OF.get(en_slug)
    b = blocks(db).get(key) if key else None
    if not b:
        return ""
    from ui import blog
    i = 1 if lang == "en" else 2
    tiles = "".join(f"<div class=card><b>{_num(b['data'][m[0]], lang)}</b><span>{esc(m[i])}</span></div>"
                    for m in BLOCKS[key] if m[0] in b["data"])
    t = T["en" if lang == "en" else "hr"]
    more = MORE.get(key)
    link = (f"<a class=blvm href={more[0 if lang == 'en' else 1]}>{esc(more[2 if lang == 'en' else 3])} →</a>"
            if more else "")
    return (f"<figure class='bv blv' id=live-data><figcaption><b>{t['h']}</b>"
            f"<span>{t['sub'].format(d=blog._date(b['day'], lang))}</span></figcaption>"
            f"<div class='cards bst'>{tiles}</div>{link}</figure>")
