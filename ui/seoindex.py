"""One indexing policy for the public site (23.11.2026., vlasnik: "Ne želimo izlistavati podatke koji nisu dobro
profiltrirani, kao Telegram kanali ... niti toliko odjedanput stranice dodavati ... smanjiš sitemapu, staviš samo
relevantne stranice").

Every public page and the sitemap ask this module:

    indexable(path) -> bool       the page is in the core: no noindex, in the sitemap
    core_urls()     -> [(en, hr or None, priority, lastmod or None)]   the sitemap, nothing else
    tg_listed(name) -> bool       the Telegram channel is on the filtered list (else its page answers 410)

The core (sections):
    (28.11.: glossary, tools, how-to-buy, price predictions, the methodology, blog / tools / glossary / Telegram hubs
    are out of the core: OUT_SECTIONS, OUT_HUB below)
    hub         the homepage, the prices / free influencer check pages (28.11.), and the hubs that show real data (influencer ranking, the meme coin list and its daily
                lists, glossary, blog and its categories, best crypto tools, how-to-buy and rug-check hubs, the market
                pages of ui/marketpub, the macro influencer hub, Autopilot, the Telegram hub while its filtered list
                is not empty)
    blog, glossary, tools   every post, every term, every tools page (editorial: written by hand)
    coin        at most SEO_COINS (30): the biggest coins (market cap) whose page carries enough of OUR OWN data
                (tokenstranice.db: enough=1, i.e. 7+ daily prices, tightened here: 14+ days and at least two of
                clean calls >= 3 / holder classes or 7+ days of holder counts / statistics)
    influencer  at most SEO_INFLUENCERS (30): the most clean measured calls (ui/kolstats, still >= MIN_CLEAN)
    macro       at most SEO_MACRO (20): the most scored episodes among the ranked macro influencers (10+)
Everything else that is public stays reachable (200, links work) and is noindex,follow, out of the sitemap.

Stable and slow: the members are stored with the day they entered (public.db seo_core); a data page stays in the core
for at least STABLE_D (30) days whatever its rank does (it leaves at once only when its page no longer exists, i.e.
would be 404). The first run fills each data section up to its cap (SEO_COINS / SEO_INFLUENCERS / SEO_MACRO); after
that a section refills free slots up to its cap plus what the weekly steps added, and grows past that only through
the weekly step:

grow_step (once a week, 23.11., vlasnik: "kako impresije i klikovi budu rasli, da se dodaju nove stranice ...
postepeno s vremenom"), from analytics.db (Search Console, read-only):
    healthy    the indexed share of the inspected core URLs ("Submitted and indexed" / "Indexed, not submitted in
               sitemap") >= SEO_GROW_MIN_INDEXED (0.6) AND impressions of the last 7 complete days (today - 3 back)
               >= the 7 before AND > 0
    then       max(5, 10 % of the core) pages, never more than SEO_GROW_MAX_WEEK (25) in 7 days, spread over the
               sections by what their core pages earn (impressions + 10 x clicks; earning sections first), the best
               candidates of each section (coins by market cap with our own data, influencers by clean measured calls,
               macro by scored calls; how-to-buy / rug-check / price-prediction only of coins in the core whose own
               page is indexed)
    pause      indexed share < SEO_GROW_PAUSE (0.4), or impressions fell two weeks in a row: nothing added, nothing
               removed, the log says why
    no data    no gsc_daily, or its newest day older than 5 days: no growth
    owner      SEO_GROW_MAX_WEEK=0 stops it
Editorial pages and hubs follow their modules. A source that cannot be read leaves its section as it was.
"""
import datetime as dt
import json
import os
import re
import sqlite3
import threading
import time

STABLE_D = 30
STATE_TTL_S = 60          # the core set in memory, read again from public.db at most this often
ENSURE_EVERY_S = 6 * 3600  # the UI process recomputes the core this often (start(), a background thread)
SECTIONS = ("hub", "blog", "glossary", "tools", "coin", "influencer", "macro", "buy", "rug", "pp")
DATA = ("coin", "influencer", "macro", "buy", "rug", "pp")
CAPS = {"coin": ("SEO_COINS", 30), "influencer": ("SEO_INFLUENCERS", 30), "macro": ("SEO_MACRO", 20)}
PRODUCT_PAGES = (("/pricing", "/hr/cijene", "0.8"), ("/check-influencer", "/hr/provjeri-influencera", "0.8"))
# 28.11. (ui/cijene, ui/provjeri). /methodology + /hr/metodologija are public but noindex for now (owner 28.11.)

# 28.11. (vlasnik: glossary out, thin out, "jezgra" of about 40 addresses). Two layers:
#   candidates  every section as before (hubs, editorial, coin / influencer / macro with their own quality bars:
#               influencer ui/kolstats.MIN_CLEAN clean measured calls, coin coin_ok = 14+ days of our own data and two
#               kinds of it, macro 10+ scored episodes, a template only for a coin whose page Google indexed), stored in
#               seo_core with their 30-day stability. Never in the candidates (OUT_SECTIONS / OUT_HUB): the glossary
#               (hub and terms), the methodology page, the Telegram hub.
#   the core    what the sitemap lists and what is indexable (_jezgra, kv "jezgra"): the homepage, prices and the free
#               check (CORE_ALWAYS); every candidate that had Search Console impressions in the last 28 days or the 28
#               before (analytics.db gsc_pages: never drop a page that earns impressions); then filled up to
#               SEO_CORE_MAX addresses (40, English and Croatian counted apart) from the strongest candidates, a quota
#               per section (CORE_FILL: influencer profiles by clean measured calls, coins by market cap with our own
#               data, blog posts, the three market pages), round robin, the members of the last core first (stable).
#               Growth: the weekly step (same gates as before: Search Console fresh, the core's indexed share, the
#               impressions growing) adds SEO_CORE_GROW_WEEK (10, at most 20) addresses to the size, the best
#               candidates first. SEO_CORE_MAX=0: the old behaviour (every candidate is in the core).
# Everything outside the core stays reachable (200, links followed), noindex,follow, out of the sitemap; robots.txt
# keeps allowing the crawl, so Google sees the noindex.
OUT_SECTIONS = ("glossary",)
OUT_HUB = re.compile(r"/(glossary|methodology|telegram-channels)")
CORE_ALWAYS = ("/", "/pricing", "/check-influencer")
CORE_MARKET = ("/solana-meme-coins", "/rug-check", "/meme-coin-season-index")
CORE_FILL = (("influencer", "SEO_CORE_INFLUENCERS", 7), ("coin", "SEO_CORE_COINS", 4), ("market", "SEO_CORE_MARKET", 3),
             ("blog", "SEO_CORE_BLOG", 3))
CORE_GROW_ORDER = ("influencer", "coin", "blog", "macro", "market", "rug", "hub", "pp", "buy", "tools")
PRODUCT_DATE = "2026-11-28"    # their last text change
GLOSSARY_DATE = "2026-11-20"   # the glossary's last text change (git), until ui/glossary_public.py has UPDATED
COIN_MIN_DAYS = 14
COIN_MIN_CALLS = 3
TG_MIN_CALLS = None            # None = ui/kolstats.MIN_CLEAN
SPECIAL = ("/robots.txt", "/sitemap.xml")

SCHEMA = """
CREATE TABLE IF NOT EXISTS seo_core (en TEXT PRIMARY KEY, hr TEXT, section TEXT, prio TEXT, lastmod TEXT,
    added TEXT, seen TEXT, seed INTEGER DEFAULT 0, rank INTEGER);
CREATE TABLE IF NOT EXISTS seo_grow (day TEXT, section TEXT, n INTEGER);
CREATE TABLE IF NOT EXISTS seo_kv (k TEXT PRIMARY KEY, v TEXT);
CREATE TABLE IF NOT EXISTS seo_tg (name TEXT PRIMARY KEY COLLATE NOCASE, calls INTEGER, ts INTEGER);
"""

_lock = threading.RLock()
_mem = {"t": 0.0, "state": None, "db": None, "computed": 0.0}   # the state read from the database (or computed, without one)


# ---------- small helpers ---------------------------------------------------------------------------------------------

def _today(now=None):
    return dt.datetime.fromtimestamp(now or time.time(), dt.timezone.utc).strftime("%Y-%m-%d")


def _day(ts):
    try:
        return dt.datetime.fromtimestamp(int(ts), dt.timezone.utc).strftime("%Y-%m-%d") if ts else None
    except (TypeError, ValueError, OverflowError, OSError):
        return None


def _days_between(a, b):
    return (dt.date.fromisoformat(b) - dt.date.fromisoformat(a)).days


def _cap(section):
    name, default = CAPS[section]
    try:
        return max(0, int(os.environ.get(name) or default))
    except ValueError:
        return default


def norm(path):
    p = (path or "/").split("?", 1)[0].split("#", 1)[0]
    return p.rstrip("/") or "/"


def db_path():
    """SEO_DB, else public.db (ui/coins.DB: the UI process writes it already). None when that file does not exist
    yet (the state is then computed in memory, not stored)."""
    if os.environ.get("SEO_DB"):
        return os.environ["SEO_DB"]
    try:
        from ui import coins
        p = coins.DB
    except Exception:  # noqa: BLE001
        return None
    return p if p and os.path.exists(p) and os.path.getsize(p) else None


def _source_paths():
    """(public.db coins, kol.db, tg.db, tokenstranice.db, makroinf.db, analytics.db): the files the core is computed
    from (the core's own database is db_path())."""
    out = []
    for fn in (lambda: __import__("ui.coins", fromlist=["x"]).DB, lambda: __import__("ui.public", fromlist=["x"])._kol_db(),
               lambda: __import__("ui.telegrampub", fromlist=["x"])._path(),
               lambda: __import__("tokenstranice.store", fromlist=["x"]).db_path(),
               lambda: __import__("makroinf.store", fromlist=["x"]).db_path(), _analytics_path):
        try:
            out.append(fn())
        except Exception:  # noqa: BLE001
            out.append(None)
    return tuple(out)


def _version(path):
    """(size, mtime_ns) of a file, None when it is not there: a cheap "did it change" (one stat)."""
    try:
        st = os.stat(path)
        return st.st_size, st.st_mtime_ns
    except (OSError, TypeError):
        return None


def _sig():
    """(core database, source paths, their versions). The paths decide WHICH data the state belongs to (another
    path = another site: never reuse that state); the versions say the data moved (the in-memory copy is read again,
    at most every RELOAD_S; the stored core is still recomputed only by ensure(), every ENSURE_EVERY_S)."""
    paths = _source_paths()
    db = db_path()
    return db, paths, tuple(_version(p) for p in (db,) + paths)


def connect(path):
    con = sqlite3.connect(path, timeout=30)
    con.executescript(SCHEMA)
    return con


# ---------- candidates (one function per section; None = the source could not be read, keep the section) -----------

def _hubs(now):
    """[(en, hr, prio, lastmod)] of the hubs with real data."""
    from ui import public
    out = [("/", "/hr", "1.0", _site_day())]
    # 28.11. (vlasnik, poslovni plan): three hand-written pages of the data product, both languages (6 URLs)
    out += [(en, hr, pr, PRODUCT_DATE) for en, hr, pr in PRODUCT_PAGES]
    rows = _coin_rows()
    coins_day = _day(max((r.get("updated") or 0 for r in rows), default=0)) if rows else None
    try:   # one broken source must not take the other hubs out
        infl = public.influencers()
    except Exception as e:  # noqa: BLE001
        print(f"seo: influenceri nedostupni: {type(e).__name__}: {e}"[:200], flush=True)
        infl = []
    if infl:
        out.append(("/influencers", "/hr/influenceri", "0.9", _infl_hub_day(now)))
    if rows:
        out.append(("/solana-meme-coins", "/hr/solana-meme-coini", "0.9", coins_day))
        try:
            from ui import coinseo
            out += [(v["en"], v["hr"], "0.8", coins_day) for v in coinseo.LISTS.values()]
            out += [(coinseo.T["en"]["buy_hub"], coinseo.T["hr"]["buy_hub"], "0.7", coins_day),
                    (coinseo.T["en"]["rug_hub"], coinseo.T["hr"]["rug_hub"], "0.7", coins_day)]
        except Exception as e:  # noqa: BLE001
            print(f"seo: coinseo nedostupan: {type(e).__name__}: {e}"[:200], flush=True)
    from ops import autopilot_off   # 27.11. (vlasnik: Autopilot uklonjen): its pages answer 410, out of the sitemap
    if not autopilot_off.on():
        out.append(("/autopilot", "/hr/autopilot", "0.8", None))
    out.append(("/glossary", "/hr/rjecnik", "0.8", _glossary_day()))
    try:
        from ui import blog
        posts = blog.urls(with_lastmod=True)
        newest = max((u[3] for u in posts if u[3]), default=None)
        out += [(en, hr, pr, newest if en == "/blog" else None) for en, hr, pr, _m in posts if not _is_post(en)]
    except Exception as e:  # noqa: BLE001
        print(f"seo: blog nedostupan: {type(e).__name__}: {e}"[:200], flush=True)
    try:
        from ui import tools
        en, hr, pr = tools.urls()[0][:3]
        out.append((en, hr, pr, _tools_day(en)))
    except Exception as e:  # noqa: BLE001
        print(f"seo: alati nedostupni: {type(e).__name__}: {e}"[:200], flush=True)
    try:
        from ui import marketpub
        out += [(en, hr, pr, None) for en, hr, pr in marketpub.urls()]
    except Exception as e:  # noqa: BLE001
        print(f"seo: tržište nedostupno: {type(e).__name__}: {e}"[:200], flush=True)
    try:
        from makroinf import public as mpub
        out += [u[:4] for u in mpub.urls() if u[0] == "/macro-influencers"]
    except Exception as e:  # noqa: BLE001
        print(f"seo: makro nedostupan: {type(e).__name__}: {e}"[:200], flush=True)
    return out


def _unreadable_hubs():
    """Hubs whose source cannot be read right now (a file missing at start, a locked database): they keep their
    place in the core instead of dropping out until the next ensure() (6 h) - a hub leaves only when its source
    says it has no data."""
    out = set()
    try:
        from ui import public
        con = public._con()
        if con is None:
            out.add("/influencers")
        else:
            con.close()
    except Exception:  # noqa: BLE001
        out.add("/influencers")
    try:
        from ui import coins
        con = coins._ro(coins.DB)
        if con is None:
            out.update(("/solana-meme-coins", "/solana-meme-coins/gainers", "/solana-meme-coins/trending",
                        "/solana-meme-coins/new", "/how-to-buy", "/rug-check"))
        else:
            con.close()
    except Exception:  # noqa: BLE001
        pass
    return out


def _is_post(en):
    return en.startswith("/blog/") and not en.startswith("/blog/category/")


def _site_day():
    try:
        from ui import sitelog
        r = sitelog.recent(1)
        return r[0]["day"] if r else None
    except Exception:  # noqa: BLE001
        return None


def _glossary_day():
    try:
        from ui import glossary_public as GP
        return getattr(GP, "UPDATED", None) or GLOSSARY_DATE
    except Exception:  # noqa: BLE001
        return GLOSSARY_DATE


def _tools_day(en):
    """The day the tools page's facts were checked (ui/toolsdata or ui/botguides CHECKED, or a later UPDATED)."""
    mods = ["toolsdata"]
    try:
        from ui import botguides
        if en in {u[0] for u in botguides.urls()}:
            mods = ["botguides"]
    except Exception:  # noqa: BLE001
        pass
    days = []
    for mod in mods:
        try:
            m = __import__(f"ui.{mod}", fromlist=["x"])
            days += [d for d in (getattr(m, "UPDATED", None), getattr(m, "CHECKED", None)) if d]
        except Exception:  # noqa: BLE001
            pass
    return max(days) if days else None


def _editorial():
    """{section: [(en, hr, prio, lastmod)]} of the hand-written pages, or None for a section that cannot be read."""
    out = {}
    try:
        from ui import blog
        out["blog"] = [(en, hr, pr, mod) for en, hr, pr, mod in blog.urls(with_lastmod=True) if _is_post(en)]
    except Exception as e:  # noqa: BLE001
        print(f"seo: blog nedostupan: {type(e).__name__}: {e}"[:200], flush=True)
        out["blog"] = None
    try:
        from ui import glossary_public as GP
        day = _glossary_day()
        out["glossary"] = [(f"/glossary/{e['en']}", f"/hr/rjecnik/{e['hr']}", "0.6", day) for e in GP.ENTRIES]
    except Exception as e:  # noqa: BLE001
        print(f"seo: rječnik nedostupan: {type(e).__name__}: {e}"[:200], flush=True)
        out["glossary"] = None
    try:
        from ui import tools
        out["tools"] = [(en, hr, pr, _tools_day(en)) for en, hr, pr in (u[:3] for u in tools.urls()[1:])]
    except Exception as e:  # noqa: BLE001
        print(f"seo: alati nedostupni: {type(e).__name__}: {e}"[:200], flush=True)
        out["tools"] = None
    return out


def _coin_rows():
    try:
        from ui import coins
        return coins.top()
    except Exception:  # noqa: BLE001
        return []


def own_data(d):
    """(clean calls, holder data, statistics) of a token page's numbers (tokenstranice.db pages.data)."""
    d = d or {}
    calls = int(((d.get("calls") or {}).get("stats") or {}).get("n") or 0)
    h = d.get("holders") or {}
    holders = bool(h.get("n_top") or h.get("top10_ex") is not None or len(h.get("hist") or []) >= 7)
    m, rg = d.get("m") or {}, d.get("range") or {}
    stats = bool(m) and not m.get("error") and int(rg.get("n") or 0) >= COIN_MIN_DAYS
    return calls, holders, stats


def coin_ok(d):
    """Enough of our own data for the index (tighter than tokenstranice 'enough': 7 daily prices and a market cap)."""
    if not d or not d.get("enough") or int(d.get("days") or 0) < COIN_MIN_DAYS:
        return False
    calls, holders, stats = own_data(d)
    return (calls >= COIN_MIN_CALLS) + holders + stats >= 2


def _coins(now):
    """(ordered eligible [(en, hr, prio, lastmod)], base set of en paths) or None without tokenstranice.db."""
    from tokenstranice import store as TS
    con = TS.ro()
    if con is None:
        return None
    try:
        rows = con.execute("SELECT mint, slug, mcap, data, updated FROM pages WHERE enough = 1 AND data IS NOT NULL "
                           "AND slug IS NOT NULL").fetchall()
    except sqlite3.Error:
        return None
    finally:
        con.close()
    top = {r["mint"]: r for r in _coin_rows()}
    base = {f"/coin/{r['slug']}" for r in top.values() if r.get("slug")}
    elig = []
    for mint, slug, mcap, data, updated in rows:
        t = top.get(mint)
        s = (t or {}).get("slug") or slug
        base.add(f"/coin/{s}")
        try:
            d = json.loads(data or "{}")
        except ValueError:
            continue
        if not coin_ok(d):
            continue
        px = ((d.get("hist") or {}).get("px") or [])
        mod = _day(px[-1][0]) if px and px[-1] and px[-1][0] else _day(updated)
        cap = (t or {}).get("mcap") or mcap or 0
        elig.append((-(cap or 0), s, (f"/coin/{s}", f"/hr/coin/{s}", "0.7", mod)))
    elig.sort(key=lambda x: (x[0], x[1]))
    return [e[2] for e in elig], base


def _influencers(now):
    from ui import kolstats as KS, public
    con = public._con()
    if con is None:
        return None
    try:
        cl = KS.clean_last(con, now=now, prefix="")
    finally:
        con.close()
    base, elig = set(), []
    for r in public.influencers():
        n, ts = cl.get(r["handle"], (0, None))
        if n < KS.MIN_CLEAN:
            continue
        base.add(f"/influencer/{r['handle']}")
        mod = _day((ts or 0) + KS.PUBLIC_DELAY_S) if ts else None
        elig.append((-n, r["handle"].lower(), (f"/influencer/{r['handle']}", f"/hr/influencer/{r['handle']}", "0.7", mod)))
    elig.sort(key=lambda x: (x[0], x[1]))
    return [e[2] for e in elig], base


def _infl_hub_day(now):
    try:
        from ui import kolstats as KS, public
        con = public._con()
        if con is None:
            return None
        try:
            ts = max((t or 0 for _n, t in KS.clean_last(con, now=now, prefix="").values()), default=0)
        finally:
            con.close()
        return _day(ts + KS.PUBLIC_DELAY_S) if ts else None
    except Exception:  # noqa: BLE001
        return None


def _macro(now):
    from makroinf import public as mpub
    if not mpub.on():
        return [], set()
    v = mpub._view()
    if not v:
        return None
    mod = _day(v.get("ts") or 0)
    base = {f"/macro-influencer/{r['handle']}" for r in (v.get("ranked") or []) + (v.get("few") or [])}
    elig = sorted(v.get("ranked") or [], key=lambda r: (-(r.get("n_epizoda") or 0), r["handle"].lower()))
    return [(f"/macro-influencer/{r['handle']}", f"/hr/makro-influencer/{r['handle']}", "0.6", mod) for r in elig], base


def tg_filtered(now=None):
    """{channel: clean measured calls} of the Telegram channels that were tracked as crypto call channels: handle
    'tg:<channel>' in kol.db with at least MIN_CLEAN clean measured calls (the old hub's "enough data", before
    19.11. nothing new comes in) AND on the weekly follower list of tg.db (so its page exists). None when kol.db or
    tg.db cannot be read (the stored list then stays)."""
    from ui import kolstats as KS, public, telegrampub
    con = public._con()
    if con is None:
        return None
    try:
        cc = KS.clean_counts(con, now=now, prefix="tg:")
    finally:
        con.close()
    need = TG_MIN_CALLS or KS.MIN_CLEAN
    want = {h[3:].lower(): n for h, n in cc.items() if n >= need and telegrampub.CH.fullmatch(h[3:] or "")}
    from tg import pratitelji, store
    tcon = store.ro(telegrampub._path())
    if tcon is None:
        return None
    out = {}
    try:
        names = list(want)
        for i in range(0, len(names), 500):
            part = names[i:i + 500]
            q = f"SELECT name FROM channels WHERE lower(name) IN ({','.join('?' * len(part))}) AND {pratitelji.LIST_SQL}"
            for (name,) in tcon.execute(q, part):
                if not public.BAD.search(name):
                    out[name] = want[name.lower()]
    except sqlite3.Error:
        return None
    finally:
        tcon.close()
    return out


# ---------- the state --------------------------------------------------------------------------------------------------

def _empty():
    return {"rows": {}, "tg": {}, "tg_known": False, "kv": {}}


def _load(con):
    st = _empty()
    for en, hr, sec, pr, mod, added, seed, rank in con.execute(
            "SELECT en, hr, section, prio, lastmod, added, seed, rank FROM seo_core"):
        st["rows"][en] = {"en": en, "hr": hr, "section": sec, "prio": pr, "lastmod": mod, "added": added,
                          "seed": seed, "rank": rank}
    st["tg"] = {n.lower(): (n, c) for n, c in con.execute("SELECT name, calls FROM seo_tg")}
    st["kv"] = dict(con.execute("SELECT k, v FROM seo_kv"))
    st["tg_known"] = st["kv"].get("tg_state") == "ok"
    return st


def _finish(st):
    """st["core"]: the rows of the core (kv "jezgra"; without it every candidate), st["set"]: its addresses."""
    pick = None
    try:
        pick = json.loads(st["kv"]["jezgra"]) if st["kv"].get("jezgra") else None
    except (ValueError, TypeError):
        pick = None
    rows = st["rows"]
    st["core"] = {e: rows[e] for e in pick if e in rows} if pick is not None else dict(rows)
    st["set"] = frozenset(p for r in st["core"].values() for p in (r["en"], r["hr"]) if p)
    return st


def core_max():
    return int(_f("SEO_CORE_MAX", 40))


def earning():
    """{path} with any Search Console impressions in the last 28 days or the 28 before (analytics.db gsc_pages)."""
    con = _analytics()
    if con is None:
        return set()
    try:
        return {_path_of(p) for (p,) in con.execute("SELECT page FROM gsc_pages WHERE COALESCE(imp_cur, 0) > 0 OR "
                                                    "COALESCE(imp_prev, 0) > 0")}
    except sqlite3.Error:
        return set()
    finally:
        con.close()


def _jezgra(rows, kv, earn):
    """[en path] of the core, in the order picked (see CORE_* above)."""
    try:
        prev = set(json.loads(kv.get("jezgra") or "[]"))
    except ValueError:
        prev = set()
    limit = core_max() + int(kv.get("jezgra_extra") or 0)
    pick, seen = [], set()

    def add(en):
        if en in rows and en not in seen:
            seen.add(en)
            pick.append(en)
            return True
        return False

    def size():
        return sum(1 + bool(rows[e]["hr"]) for e in pick)
    for en in CORE_ALWAYS:
        add(en)
    for en, r in sorted(rows.items(), key=lambda x: (ORDER.get(x[1]["section"], 99), x[1].get("rank") or 0, x[0])):
        if en in earn or (r["hr"] and r["hr"] in earn):
            add(en)
    key = (lambda e: (e not in prev, rows[e].get("rank") or 0, e))
    queues = {sec: sorted((e for e, r in rows.items() if r["section"] == sec), key=key) for sec in CORE_GROW_ORDER}
    queues["market"] = [e for e in CORE_MARKET if e in rows]
    queues["hub"] = [e for e in queues["hub"] if e not in CORE_MARKET]
    have = {sec: sum(1 for e in q if e in seen) for sec, q in queues.items()}
    quota = {sec: int(_f(env, n)) for sec, env, n in CORE_FILL}

    def fill(order, capped):
        while size() < limit:
            moved = False
            for sec in order:
                if size() >= limit:
                    break
                if capped and have.get(sec, 0) >= quota.get(sec, 0):
                    continue
                nxt = next((e for e in queues.get(sec, []) if e not in seen), None)
                if nxt and add(nxt):
                    have[sec] = have.get(sec, 0) + 1
                    moved = True
            if not moved:
                return
    fill([sec for sec, _e, _n in CORE_FILL], True)
    fill(CORE_GROW_ORDER, False)   # room left (growth, or a section without enough candidates): the best of any
    return pick


def grow_core(core, kv, now, con):
    """The weekly step of the core (28.11.): the same gates as grow_step; a healthy week raises the core's size by
    SEO_CORE_GROW_WEEK addresses (default 10, never more than 20). Never removes anything. -> the log line."""
    kv["grow_ts"] = str(int(now))
    if int(_f("SEO_GROW_MAX_WEEK", 25)) <= 0:
        return "seo jezgra: rast stoji — vlasnik je zaustavio rast (SEO_GROW_MAX_WEEK=0)"
    h = health(core, now)
    if h is None or not h.get("fresh"):
        return "seo jezgra: rast stoji — nema svježih podataka Search Consolea"
    imp = h["imp"]
    head = (f"jezgra {sum(1 + bool(r['hr']) for r in core.values())} adresa (indeksirano {h['a']} od {h['b']}); "
            f"impresije 7 d {imp[0]:.0f} (prije {imp[1]:.0f})")
    if not h["b"] or (h["share"] or 0) < _f("SEO_GROW_MIN_INDEXED", 0.6):
        return f"seo jezgra: rast stoji — {head}; premalo indeksiranih adresa jezgre"
    if imp[0] <= 0 or imp[0] <= imp[1]:
        return f"seo jezgra: rast stoji — {head}; impresije nisu rasle"
    n = max(0, min(20, int(_f("SEO_CORE_GROW_WEEK", 10))))
    kv["jezgra_extra"] = str(int(kv.get("jezgra_extra") or 0) + n)
    con.execute("INSERT INTO seo_grow (day, section, n) VALUES (?,?,?)", (_today(now), "jezgra", n))
    return f"seo jezgra: {head}; veličina +{n} adresa"


def ensure(now=None, db=None, log=True):
    """Recompute the core from the sources and store it (idempotent: the same data gives the same rows). Returns the
    counts of daily_line(). Without a database the state lives in this process only."""
    now = now or time.time()
    today = _today(now)
    path = db or db_path()
    with _lock:
        con = connect(path) if path else None
        try:
            src = _source_paths()
            if con is not None:
                st = _load(con)
                old = st["kv"].get("sources")
                if old and old != json.dumps(src):   # computed from other files: a different site, start clean
                    st = {**_empty(), "kv": {k: v for k, v in st["kv"].items() if k == "log_day"}}
            else:
                mine = _mem["state"] if _mem["db"] and _mem["db"][1] == src else None
                st = mine or _empty()
            st["kv"]["sources"] = json.dumps(src)
            before = _finish(dict(st))["set"]
            rows = st["rows"]
            added_today = []
            # hubs and editorial: exactly what the modules list today
            fixed = {"hub": _safe(lambda: _hubs(now))}
            fixed.update(_editorial())
            tg = _safe(lambda: tg_filtered(now))
            if tg is not None:
                st["tg"] = {n.lower(): (n, c) for n, c in tg.items()}
                st["tg_known"] = bool(tg)
            if fixed["hub"] is not None:   # 28.11.: only the important hubs (OUT_HUB stays reachable, noindex)
                fixed["hub"] = [u for u in fixed["hub"] if not OUT_HUB.fullmatch(norm(u[0]))]
            for sec in OUT_SECTIONS:
                if sec in fixed:
                    fixed[sec] = []
            for sec, urls in fixed.items():
                if urls is None:
                    continue
                keep = {}
                for en, hr, pr, mod in urls:
                    keep.setdefault(norm(en), (norm(hr) if hr else None, pr, mod))
                unread = {u for u in _unreadable_hubs() if not OUT_HUB.fullmatch(u)} if sec == "hub" else set()
                for en in [k for k, r in rows.items() if r["section"] == sec and k not in keep and k not in unread]:
                    del rows[en]
                for i, (en, (hr, pr, mod)) in enumerate(keep.items()):
                    old = rows.get(en)
                    if old is None:
                        added_today.append(en)
                    rows[en] = {"en": en, "hr": hr, "section": sec, "prio": pr, "lastmod": _past(mod, today),
                                "added": (old or {}).get("added") or today, "seed": 0, "rank": i}
            # data sections: seeded up to their cap, stable for STABLE_D days, refilled up to their size; they grow
            # only through the weekly step (grow_step), as Google responds
            elig_by = {}
            for sec, fn in (("coin", _coins), ("influencer", _influencers), ("macro", _macro)):
                got = _safe(lambda fn=fn: fn(now))
                if got is None:
                    continue
                elig_by[sec] = got[0]
                added_today += _refresh(rows, st["kv"], sec, got[0], got[1], today, _cap(sec))
            indexed = _safe(lambda: gsc_indexed()) or set()
            tpl = _safe(lambda: _templates(rows, indexed))
            for sec, (elig, base) in (tpl or {}).items():
                elig_by[sec] = elig
                added_today += _refresh(rows, st["kv"], sec, elig, base, today, 0)
            for en in [k for k, r in rows.items() if r["section"] in OUT_SECTIONS or OUT_HUB.fullmatch(k)]:
                del rows[en]   # 28.11.: out at once, the 30-day stability does not apply
            if core_max() <= 0:   # the old behaviour: every candidate is in the core, the sections grow
                st["kv"].pop("jezgra", None)
                if con is not None and _grow_due(st["kv"], now):
                    line, grown = grow_step(rows, st["kv"], elig_by, now, con)
                    added_today += grown
                    if log:
                        print(line, flush=True)
            else:   # 28.11.: the core of about 40 addresses
                earn = _safe(earning) or set()
                pick = _jezgra(rows, st["kv"], earn)
                if con is not None and _grow_due(st["kv"], now):
                    line = grow_core({e: rows[e] for e in pick}, st["kv"], now, con)
                    pick = _jezgra(rows, st["kv"], earn)
                    if log:
                        print(line, flush=True)
                st["kv"]["jezgra"] = json.dumps(pick)
            counts = _counts(_finish(st), now)
            st["kv"]["tg_state"] = "ok" if st["tg_known"] else "unknown"
            if con is not None:
                _store(con, st)
                if log and st["kv"].get("log_day") != today:
                    print(daily_line(counts), flush=True)
                    con.execute("INSERT OR REPLACE INTO seo_kv (k, v) VALUES ('log_day', ?)", (today,))
                con.commit()
            elif log and st["kv"].get("log_day") != today:
                print(daily_line(counts), flush=True)
                st["kv"]["log_day"] = today
            changed = _finish(st)["set"] != before
            _mem.update(t=time.monotonic(), state=st, db=_sig(), computed=time.monotonic())
        finally:
            if con is not None:
                con.close()
    if changed and before:   # the first state of a process changes no copy made under another one
        _drop_public_copies()
    return counts


def _refresh(rows, kv, sec, elig, base, today, seed_cap):
    """One data section: members whose page is gone leave at once; a member older than STABLE_D days stays while it
    is among the best `size` candidates (size = the owner's cap plus what the weekly steps added); free slots are
    filled from the best candidates (so a section that had fewer candidates than its cap fills up to the cap as they
    appear, never past it without the weekly step). Returns the paths added."""
    rank = {u[0]: i for i, u in enumerate(elig)}
    seeded = f"seeded:{sec}" in kv
    target = seed_cap + int(kv.get(f"grown:{sec}") or 0)   # the owner's cap plus what the weekly steps added
    best = {u[0] for u in elig[:target]}
    for en, r in [(k, r) for k, r in rows.items() if r["section"] == sec]:
        old = _days_between(r["added"], today) >= STABLE_D if r.get("added") else True
        if en not in base or (old and en not in best):
            del rows[en]
        elif en in rank:   # still a page with data: its lastmod and rank move with the data
            r.update(lastmod=_past(elig[rank[en]][3], today), rank=rank[en])
    size = sum(1 for r in rows.values() if r["section"] == sec)
    take = [u for u in elig[:target] if u[0] not in rows][:max(0, target - size)]
    for u in take:
        rows[u[0]] = {"en": u[0], "hr": u[1], "section": sec, "prio": u[2], "lastmod": _past(u[3], today),
                      "added": today, "seed": 0 if seeded else 1, "rank": rank[u[0]]}
    kv[f"seeded:{sec}"] = kv.get(f"seeded:{sec}") or today
    return [u[0] for u in take]


TPL = {"buy": ("/how-to-buy/{s}", "/hr/kako-kupiti/{s}", "0.5"), "rug": ("/rug-check/{s}", "/hr/provjera/{s}", "0.5"),
       "pp": ("/coin/{s}/price-prediction", "/hr/coin/{s}/prognoza", "0.4")}


def _templates(rows, indexed):
    """{section: (candidates, base)} of the template pages (how to buy, rug check, price prediction): candidates only
    for coins already in the core whose own page Google reports as indexed, in the coins' order; base = every coin
    that has these pages (public.db coins)."""
    from ui import coins
    con = coins._ro(coins.DB)
    if con is None:
        return None
    try:
        slugs = {r[0] for r in con.execute("SELECT slug FROM coins WHERE slug IS NOT NULL")}
    except sqlite3.Error:
        return None
    finally:
        con.close()
    core = sorted((r for r in rows.values() if r["section"] == "coin"), key=lambda r: r.get("rank") or 0)
    ok = [r["en"].rsplit("/", 1)[1] for r in core if r["en"] in indexed or (r["hr"] and r["hr"] in indexed)]
    out = {}
    for sec, (en, hr, pr) in TPL.items():
        base = {en.format(s=x) for x in slugs}
        out[sec] = ([(en.format(s=x), hr.format(s=x), pr, r.get("lastmod")) for x in ok if x in slugs
                     for r in (rows[f"/coin/{x}"],)], base)
    return out


# ---------- the weekly growth step (23.11., vlasnik: "kako impresije i klikovi budu rasli, da se dodaju nove stranice
# ... postepeno s vremenom") -------------------------------------------------------------------------------------------

INDEXED = ("Submitted and indexed", "Indexed, not submitted in sitemap")
GROW_EVERY_S = 7 * 86400
GSC_LAG_D = 3          # the last complete day of Search Console is today - 3 (analytics/gsc: LAG_DAYS 2, +1)
GSC_FRESH_D = 5        # newer than this or no growth
GROW_ORDER = ("coin", "influencer", "macro", "buy", "rug", "pp")


def _f(name, default):
    try:
        return float(os.environ.get(name) or default)
    except ValueError:
        return default


def _analytics_path():
    if os.environ.get("ANALYTICS_DB"):
        return os.environ["ANALYTICS_DB"]
    try:
        from analytics import gsc
        return gsc.DB
    except Exception:  # noqa: BLE001
        return None


def _analytics():
    p = _analytics_path()
    if not p or not os.path.exists(p) or not os.path.getsize(p):
        return None
    try:
        return sqlite3.connect(f"file:{p}?mode=ro", uri=True, timeout=5)
    except sqlite3.Error:
        return None


def _path_of(url):
    from urllib.parse import urlparse
    return norm(urlparse(url).path if "://" in (url or "") else url)


def gsc_indexed():
    """{path} that Google reports as indexed (analytics.db gsc_inspect), empty without data."""
    con = _analytics()
    if con is None:
        return set()
    try:
        q = ",".join("?" * len(INDEXED))
        return {_path_of(u) for (u,) in con.execute(f"SELECT url FROM gsc_inspect WHERE coverage_state IN ({q})",
                                                    INDEXED)}
    except sqlite3.Error:
        return set()
    finally:
        con.close()


def _grow_due(kv, now):
    try:
        return now - float(kv.get("grow_ts") or 0) >= GROW_EVERY_S - 3600
    except ValueError:
        return True


def health(rows, now):
    """What the weekly step looks at: {fresh, a (indexed), b (inspected core URLs), share, imp [w0, w1, w2],
    clicks [w0, w1, w2], weight {section: impressions + 10 x clicks of its core pages}} or None without GSC data."""
    con = _analytics()
    if con is None:
        return None
    today = dt.date.fromisoformat(_today(now))
    end = today - dt.timedelta(days=GSC_LAG_D)
    try:
        newest = con.execute("SELECT MAX(day) FROM gsc_daily").fetchone()[0]
        if not newest or dt.date.fromisoformat(str(newest)[:10]) < today - dt.timedelta(days=GSC_FRESH_D):
            return {"fresh": False, "newest": newest}
        imp, clk = [0.0, 0.0, 0.0], [0.0, 0.0, 0.0]
        for day, c, i in con.execute("SELECT day, clicks, impressions FROM gsc_daily WHERE day >= ? AND day <= ?",
                                     ((end - dt.timedelta(days=20)).isoformat(), end.isoformat())):
            w = (end - dt.date.fromisoformat(str(day)[:10])).days // 7
            if 0 <= w <= 2:
                imp[w] += i or 0
                clk[w] += c or 0
        where = {}
        for r in rows.values():
            for p in (r["en"], r["hr"]):
                if p:
                    where[p] = r["section"]
        a = b = 0
        try:
            for url, state in con.execute("SELECT url, coverage_state FROM gsc_inspect"):
                if _path_of(url) in where:
                    b += 1
                    a += state in INDEXED
        except sqlite3.Error:
            pass
        weight = {}
        try:
            for page, i, c in con.execute("SELECT page, imp_cur, clicks_cur FROM gsc_pages"):
                sec = where.get(_path_of(page))
                if sec:
                    weight[sec] = weight.get(sec, 0) + (i or 0) + 10 * (c or 0)
        except sqlite3.Error:
            pass
    except (sqlite3.Error, ValueError):
        return None
    finally:
        con.close()
    return {"fresh": True, "a": a, "b": b, "share": (a / b) if b else None, "imp": imp, "clicks": clk,
            "weight": weight}


def _spread(n, weight, room):
    """{section: pages} of n new pages: by the highest-averages rule over what each section's core pages earn
    (impressions + 10 x clicks); sections that earn nothing only get what the earning ones cannot take; never more
    than a section has candidates."""
    got = {s: 0 for s in room}
    for _ in range(n):
        live = [s for s in GROW_ORDER if s in room and got[s] < room[s]]
        if not live:
            break
        earning = [s for s in live if weight.get(s, 0) > 0]
        if earning:
            s = max(earning, key=lambda x: (weight[x] / (got[x] + 1), -GROW_ORDER.index(x)))
        else:
            s = min(live, key=lambda x: (got[x], GROW_ORDER.index(x)))
        got[s] += 1
    return {s: k for s, k in got.items() if k}


def _grown_7d(con, today):
    if con is None:
        return 0
    cut = (dt.date.fromisoformat(today) - dt.timedelta(days=6)).isoformat()
    return int(con.execute("SELECT COALESCE(SUM(n), 0) FROM seo_grow WHERE day >= ?", (cut,)).fetchone()[0])


def grow_step(rows, kv, elig_by, now, con):
    """The weekly step: (log line, [paths added]). Adds pages only while the core is healthy; never removes any."""
    today = _today(now)
    kv["grow_ts"] = str(int(now))
    mx = int(_f("SEO_GROW_MAX_WEEK", 25))
    pct_min, pct_pause = _f("SEO_GROW_MIN_INDEXED", 0.6), _f("SEO_GROW_PAUSE", 0.4)

    def stop(why):
        kv["grow_last"] = why
        return f"seo rast: stoji — {why}", []
    if mx <= 0:
        return stop("vlasnik je zaustavio rast (SEO_GROW_MAX_WEEK=0)")
    h = health(rows, now)
    if h is None:
        return stop("nema podataka Search Consolea")
    if not h["fresh"]:
        return stop(f"podaci Search Consolea stari (zadnji dan {h.get('newest') or '–'}, treba unutar {GSC_FRESH_D} d)")
    imp, clk = h["imp"], h["clicks"]
    head = (f"jezgra {len(rows)} (indeksirano {h['a']} od {h['b']} pregledanih, "
            f"{(h['share'] or 0) * 100:.0f} %); impresije 7 d {imp[0]:.0f} (prije {imp[1]:.0f}), klikovi {clk[0]:.0f}")
    if not h["b"]:
        return stop(f"{head}; nijedna adresa jezgre još nije pregledana")
    if h["share"] < pct_pause:
        return stop(f"{head}; pauza: indeksirano ispod {pct_pause * 100:.0f} %")
    if imp[0] < imp[1] < imp[2]:
        return stop(f"{head}; pauza: impresije padaju dva tjedna zaredom")
    if h["share"] < pct_min:
        return stop(f"{head}; indeksirano ispod {pct_min * 100:.0f} %")
    if imp[0] <= 0 or imp[0] < imp[1]:
        return stop(f"{head}; impresije nisu rasle")
    n = min(max(5, -(-len(rows) // 10)), mx - _grown_7d(con, today))
    fresh = {s: [u for u in elig_by.get(s) or [] if u[0] not in rows] for s in GROW_ORDER}
    plan = _spread(max(0, n), h["weight"], {s: len(v) for s, v in fresh.items() if v})
    added = []
    for sec, k in plan.items():
        rank = {u[0]: i for i, u in enumerate(elig_by[sec])}
        for u in fresh[sec][:k]:
            rows[u[0]] = {"en": u[0], "hr": u[1], "section": sec, "prio": u[2], "lastmod": _past(u[3], today),
                          "added": today, "seed": 0, "rank": rank[u[0]]}
            added.append(u[0])
        kv[f"grown:{sec}"] = str(int(kv.get(f"grown:{sec}") or 0) + k)
        con.execute("INSERT INTO seo_grow (day, section, n) VALUES (?,?,?)", (today, sec, k))
    kv["grow_last"] = f"dodano {len(added)}"
    c = {s: plan.get(s, 0) for s in GROW_ORDER}
    return (f"seo rast: {head}; dodano {len(added)} (tokeni {c['coin']}, influenceri {c['influencer']}, makro "
            f"{c['macro']}, kako-kupiti {c['buy']}, provjera {c['rug']}, prognoze {c['pp']})"), added


def _safe(fn):
    try:
        return fn()
    except Exception as e:  # noqa: BLE001 - one broken source never changes the other sections
        print(f"seo: izvor nedostupan: {type(e).__name__}: {e}"[:200], flush=True)
        return None


def _past(day, today):
    return min(day, today) if day else None


def _tg_day():
    try:
        from tg import pratitelji
        from ui import telegrampub
        return _day((pratitelji.zadnji(telegrampub._path()) or {}).get("ts"))
    except Exception:  # noqa: BLE001
        return None


def _store(con, st):
    con.execute("DELETE FROM seo_core")
    con.executemany("INSERT INTO seo_core (en, hr, section, prio, lastmod, added, seen, seed, rank) "
                    "VALUES (?,?,?,?,?,?,?,?,?)",
                    [(r["en"], r["hr"], r["section"], r["prio"], r["lastmod"], r["added"], _today(), r.get("seed") or 0,
                      r.get("rank")) for r in st["rows"].values()])
    con.execute("DELETE FROM seo_tg")
    con.executemany("INSERT INTO seo_tg (name, calls, ts) VALUES (?,?,?)",
                    [(n, c, int(time.time())) for n, c in st["tg"].values()])
    con.executemany("INSERT OR REPLACE INTO seo_kv (k, v) VALUES (?,?)", list(st["kv"].items()))


def _drop_public_copies():
    try:
        from ui import public
        with public._lock:
            public._cache.clear()
    except Exception:  # noqa: BLE001
        pass


RELOAD_S = 5   # a source file changed: the in-memory copy is read again at most this often
MEMORY_RECOMPUTE_S = 300   # without a database (public.db not there yet): recomputed at most this often (kol.db
                           # changes every second in production, the computation reads all clean calls)


def state():
    """The core as this process knows it.
    With the database: the stored core, read again when STATE_TTL_S passed or a source file changed (at most every
    RELOAD_S); computed now only when nothing is stored yet or it was computed from other files (other paths).
    Without one: computed in memory, again when the source files change (at most every MEMORY_RECOMPUTE_S) or their
    paths change (at once)."""
    with _lock:
        st, sig, now = _mem["state"], _sig(), time.monotonic()
        db, paths, _v = sig
        old = _mem["db"]
        same_paths = old is not None and old[:2] == (db, paths)
        if st is not None and same_paths:
            age = now - _mem["t"]
            if (old == sig and age < STATE_TTL_S) or age < RELOAD_S:
                return st
        if db:
            try:
                con = connect(db)
                try:
                    got = _load(con)
                finally:
                    con.close()
                stored = got["kv"].get("sources")
                if got["rows"] and (not stored or stored == json.dumps(paths)):
                    _mem.update(t=now, state=_finish(got), db=sig)
                    return _mem["state"]
            except sqlite3.Error as e:
                print(f"seo: stanje nije pročitano: {e}"[:200], flush=True)
                if st is not None and same_paths:
                    return st
        elif st is not None and same_paths and now - _mem.get("computed", 0) < MEMORY_RECOMPUTE_S:
            _mem["t"] = now
            return st
        if not same_paths:
            _mem["state"] = None
        ensure(log=False)
        return _mem["state"]


_poking = threading.Event()


def poke():
    """The data behind a section moved (a macro scoring, the owner switch): the core is recomputed now (without a
    database: at the next question; with one: in a background thread, one at a time). The rules stay the same:
    stability, caps and the weekly growth are not changed by a poke."""
    if not db_path():
        with _lock:
            _mem["t"] = _mem["computed"] = -1e12
        return
    if _poking.is_set():
        return
    _poking.set()

    def run():
        try:
            ensure(log=False)
        except Exception as e:  # noqa: BLE001
            print(f"seo: jezgra nije osvježena: {type(e).__name__}: {e}"[:200], flush=True)
        finally:
            _poking.clear()
    threading.Thread(target=run, daemon=True, name="seo-poke").start()


def reset():
    """Forget the state of this process and every copy made under it: the rendered public pages and the shared
    copies of ui/javniteret (the influencer rows, the Telegram list built from the filtered set, the macro view).
    Tests; after the owner changes a cap the next ensure() applies it."""
    with _lock:
        _mem.update(t=0.0, state=None, db=None, computed=0.0)
    _drop_public_copies()
    try:
        from ui import javniteret
        javniteret.forget()
    except Exception:  # noqa: BLE001
        pass


# ---------- the answers ------------------------------------------------------------------------------------------------

TEMPLATE = re.compile(r"(/hr)?/(how-to-buy|kako-kupiti|rug-check|provjera)/.+|(/hr)?/coin/[^/]+/(price-prediction|prognoza)"
                      r"|(/hr)?/telegram/.+")


def indexable(path):
    """True when the page at this path is in the core. Never raises: if the policy cannot be read, the template pages
    and the Telegram channels are noindex and everything else keeps its own flag (the old behaviour)."""
    p = norm(path)
    if p in SPECIAL:
        return True
    try:
        return p in state()["set"]
    except Exception as e:  # noqa: BLE001
        print(f"seo: politika nedostupna: {type(e).__name__}: {e}"[:200], flush=True)
        return not TEMPLATE.fullmatch(p)


ORDER = {s: i for i, s in enumerate(SECTIONS)}


def core_urls():
    """[(en, hr or None, priority, lastmod or None)]: the sitemap (hubs first, then each section by rank)."""
    st = state()
    rows = sorted(st["core"].values(), key=lambda r: (ORDER.get(r["section"], 99), r.get("rank") or 0, r["en"]))
    today = _today()
    return [(r["en"], r["hr"], r["prio"], _past(r["lastmod"], today)) for r in rows]


def section_of(path):
    p = norm(path)
    for r in state()["core"].values():
        if p in (r["en"], r["hr"]):
            return r["section"]
    return None


def section_paths(section, lang="en"):
    """[path] of the core pages of a section in that language, by rank (hubs link to them)."""
    rows = sorted((r for r in state()["core"].values() if r["section"] == section), key=lambda r: r.get("rank") or 0)
    return [r["hr"] if lang == "hr" and r["hr"] else r["en"] for r in rows]


def tg_listed(channel):
    """True for a channel on the filtered Telegram list (in memory: no database read per request)."""
    try:
        return (channel or "").lower() in state()["tg"]
    except Exception:  # noqa: BLE001
        return False


def tg_channels():
    """{channel: clean measured calls} of the filtered list, and whether the list could be determined."""
    st = state()
    return {n: c for n, c in st["tg"].values()}, st["tg_known"]


# ---------- what is out of the index, and the daily line ---------------------------------------------------------------

def _counts(st, now):
    by = {s: 0 for s in SECTIONS}
    for r in st["core"].values():
        by[r["section"]] = by.get(r["section"], 0) + 1 + (1 if r["hr"] else 0)
    out = {"sitemap": sum(by.values()), **by}
    core = {s: sum(1 for r in st["core"].values() if r["section"] == s) for s in DATA}
    top = _coin_rows()
    n_coins = len({r["slug"] for r in top if r.get("slug")} | _ts_slugs())
    out["out_coin"] = 2 * max(0, n_coins - core["coin"])
    try:
        from ui import public
        out["out_influencer"] = 2 * max(0, len(public.influencers()) - core["influencer"])
    except Exception:  # noqa: BLE001
        out["out_influencer"] = 0
    try:
        from makroinf import public as mpub
        v = mpub._view() if mpub.on() else None
        out["out_macro"] = 2 * max(0, (len(v["ranked"]) + len(v["few"]) if v else 0) - core["macro"])
    except Exception:  # noqa: BLE001
        out["out_macro"] = 0
    for k in ("buy", "rug", "pp"):   # the template pages of every top coin, less those that grew into the core
        out[f"out_{k}"] = max(0, 2 * len(top) - by.get(k, 0))
    out["out_tg"] = 2 * len(st["tg"])
    return out


def _ts_slugs():
    try:
        from tokenstranice import store as TS
        con = TS.ro()
        if con is None:
            return set()
        try:
            return {s for (s,) in con.execute("SELECT slug FROM pages WHERE data IS NOT NULL AND slug IS NOT NULL")}
        finally:
            con.close()
    except Exception:  # noqa: BLE001
        return set()


def daily_line(c):
    """The one log line a day; every number counts addresses (English and Croatian), as the sitemap lists them."""
    tok = c["coin"] + c.get("buy", 0) + c.get("rug", 0) + c.get("pp", 0)   # every token page in the core
    return (f"seo: sitemap {c['sitemap']} adresa (naslovnica i hubovi {c['hub']}, blog {c['blog']}, rječnik "
            f"{c['glossary']}, alati {c['tools']}, tokeni {tok}, influenceri {c['influencer']}, makro "
            f"{c['macro']}); izvan indeksa: tokeni {c['out_coin']}, influenceri {c['out_influencer']}, makro "
            f"{c['out_macro']}, kako-kupiti {c['out_buy']}, provjera {c['out_rug']}, prognoze {c['out_pp']}, "
            f"telegram kanali {c['out_tg']}")


def start():
    """The UI process: the core recomputed in the background at start and every ENSURE_EVERY_S."""
    def loop():
        time.sleep(float(os.environ.get("SEO_START_DELAY_S", "20")))
        while True:
            try:
                ensure()
            except Exception as e:  # noqa: BLE001
                print(f"seo: jezgra nije osvježena: {type(e).__name__}: {e}"[:200], flush=True)
            time.sleep(ENSURE_EVERY_S)
    threading.Thread(target=loop, daemon=True, name="seo-jezgra").start()
