"""Smarter search for real KOLs and traders (2.11.2026, after fake "KOLs" were found at the top of the KOL tab).

  winners   start from tokens that really rose (2x+ in 24 h) and ask twitterapi.io who posted the CA BEFORE the rise
            (until_time = the first post that came after the price had already doubled). Those authors become
            candidates; the timeline rotation already reads early winner callers first.
  annotate  per KOL in kols.stats (also rugger: more than rug_max of 10+ measured calls ended as a rug):
              bought   tokens it called and that its own known wallet also bought (kol/idents + chainwatch): a trader
                       who puts money where the post is
              trial    "na probi": fewer than trial.min_calls measured calls, less than trial.days of history with
                       us, or posts nobody sees (median views < trial.min_views). On trial = no live watch, no copy
                       trading, no "good KOL" in the group signal; the page shows the badge and why.
  audit     once a week the top accounts get a profile check: twitterapi.io profile (bio, age, pinned post) plus the
            last posts, read by Claude Haiku: real caller / trader, or hacked account, dev of its own tokens, paid
            group seller, news bot, suspended. A bad verdict marks the account as "not a KOL" (kol/bots.py reads
            the audits table), the reason is shown on its page.

Spend: discovery has its own twitterapi.io daily cap (discover.daily_usd, kv twdisc:<day>), kept out of the timeline
share (timeline_twapi.reserve_usd), so it runs even after the timelines used theirs; winners at most
discover.winners_usd of it. Audit: ~20 profiles + ~20 short Haiku calls a week (< $0.05).
"""
import json
import os
import re
import time

DEFAULTS = {"daily_usd": 0.15, "rug_max": 0.3, "rug_min_calls": 10, "win_x": 1.0, "win_hours": 48, "win_per_run": 4, "win_pages": 3, "winners_usd": 0.12, "win_back_h": 48,
            "trial": {"min_calls": 10, "days": 14, "min_views": 200},
            "audit": {"top": 20, "every_d": 7, "per_run": 5, "posts": 8,
                      "model": "claude-haiku-5-5", "bad": ["hakiran", "dev", "placena_grupa", "bot", "suspendiran"]}}
VERDICTS = {"kol": "pravi KOL (zove tokene)", "trader": "trader (objavljuje svoje trejdove)",
            "hakiran": "hakiran račun (profil nema veze s kriptom, objave su spam)",
            "dev": "dev koji pumpa vlastite tokene", "placena_grupa": "prodaje pristup plaćenoj grupi",
            "bot": "bot ili račun s vijestima, nije osoba", "suspendiran": "račun je suspendiran ili ne postoji",
            "nejasno": "nejasno"}
SCHEMA = """CREATE TABLE IF NOT EXISTS audits (
    handle TEXT PRIMARY KEY, ts INTEGER, verdict TEXT, why TEXT, bio TEXT, created TEXT, followers INTEGER,
    pinned TEXT, cost_usd REAL)"""


def _kv_add(con, key, usd):
    con.execute("INSERT INTO kv VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = CAST(value AS REAL) + ?",
                (key, str(usd), usd))


def disc_left(con, cfg, now):
    """USD the discovery searches (winners, profile check, follow graph) may still spend today. They have their own
    daily cap (discover.daily_usd), separate from the timeline reading, so a timeline that used its share does not
    stop the search for new KOLs."""
    day = time.strftime("%Y-%m-%d", time.gmtime(now))
    row = con.execute("SELECT value FROM kv WHERE key = ?", (f"twdisc:{day}",)).fetchone()
    return dcfg(cfg)["daily_usd"] - (float(row[0]) if row else 0.0)


def _charge(con, now, before):
    """Book what twitterapi.io calls since `before` (twapi.spent) cost to the discovery counter."""
    from kol import twapi
    usd = twapi.spent(con, now) - before
    _kv_add(con, f"twdisc:{time.strftime('%Y-%m-%d', time.gmtime(now))}", usd)
    return usd


def dcfg(cfg):
    d = dict(DEFAULTS, **(cfg.get("discover") or {}))
    d["trial"] = dict(DEFAULTS["trial"], **(d.get("trial") or {}))
    d["audit"] = dict(DEFAULTS["audit"], **(d.get("audit") or {}))
    return d


def ensure(con):
    con.execute(SCHEMA)


# ---------- 1. backwards from winners ----------

def winner_targets(con, cfg, now=None):
    """[(token, since, until)] for tokens that rose win_x in 24 h after a call made in the last win_hours, not
    searched yet. until = the first post made after the price had already doubled (pre2h >= win_x), else the first
    post + 3 h: who posted before that moment called it before the rise."""
    d = dcfg(cfg)
    now = now or int(time.time())
    done = {t[4:] for (t,) in con.execute("SELECT target FROM searches WHERE target LIKE 'win:%'")}
    rows = con.execute("""
        SELECT token, MIN(ts), MIN(CASE WHEN COALESCE(pre2h, 0) >= ? THEN ts END), MAX(COALESCE(max24, 0)) AS up
        FROM calls WHERE kind IN ('call', 'bot') AND ts >= ? GROUP BY token HAVING up >= ? ORDER BY up DESC""",
                       (d["win_x"], now - d["win_hours"] * 3600, d["win_x"])).fetchall()
    out = []
    for tok, first, late, _ in rows:
        if tok in done:
            continue
        until = late if late else first + 3 * 3600
        out.append((tok, until - d["win_back_h"] * 3600, min(until, now)))
    return out


def winners(con, cfg, get=None, now=None):
    """Search who posted each winner's CA before it rose (twitterapi.io). Returns new calls."""
    from kol import collect, twapi
    if not twapi.key() and get is None:
        return 0
    ensure(con)
    d = dcfg(cfg)
    now = now or int(time.time())
    day = time.strftime("%Y-%m-%d", time.gmtime(now))
    row = con.execute("SELECT value FROM kv WHERE key = ?", (f"twwin:{day}",)).fetchone()
    mine = float(row[0]) if row else 0.0
    n = 0
    for tok, since, until in winner_targets(con, cfg, now)[:d["win_per_run"]]:
        left = min(d["winners_usd"] - mine, disc_left(con, cfg, now))
        if left <= 0:
            break
        before = twapi.spent(con, now)
        budget = before + left
        try:
            items = twapi.search(con, tok, since, budget, get=get, max_pages=d["win_pages"], now=now, until_ts=until)
        except Exception as e:  # noqa: BLE001 - one bad query must not stop the round
            print(f"kol winners: upit nije uspio ({type(e).__name__}: {e})", flush=True)
            items = []
        mine += _charge(con, now, before)
        collect._searched(con, f"win:{tok}", "winner", now)
        n += collect.save(con, [c for it in items for c in collect.calls_from_tweet(it, tok, None, "kol_win")])
    con.execute("INSERT INTO kv VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (f"twwin:{day}", str(mine)))
    con.commit()
    return n


# ---------- 2+3. wallet proof and trial ----------

def annotate(con, cfg, now=None):
    """Write bought / trial / trial_why into kols.stats. Returns the set of handles on trial."""
    d = dcfg(cfg)
    t = d["trial"]
    now = now or int(time.time())
    bought = dict(con.execute("""
        SELECT c.handle, COUNT(DISTINCT c.token) FROM calls c
        WHERE c.kind = 'call' AND EXISTS (SELECT 1 FROM calls b WHERE b.kind = 'buy' AND b.token = c.token
                                          AND LOWER(b.handle) = LOWER(c.handle))
        GROUP BY c.handle"""))
    first = dict(con.execute("SELECT handle, MIN(ts) FROM calls WHERE kind = 'call' GROUP BY handle"))
    from kol import shillers
    shill_set, sh = shillers.handles(), shillers.cfg(cfg)
    trial, upd = set(), []
    for h, st in con.execute("SELECT handle, stats FROM kols WHERE handle NOT LIKE 'w:%'").fetchall():
        try:
            s = json.loads(st or "{}")
        except ValueError:
            s = {}
        why = []
        if s.get("measured", 0) < t["min_calls"]:
            why.append(f"tek {s.get('measured', 0)} izmjerenih poziva (treba {t['min_calls']})")
        if first.get(h) and now - first[h] < t["days"] * 86400:
            why.append(f"pratimo ga {max(0, (now - first[h]) // 86400)} dana (treba {t['days']})")
        mv = s.get("med_views")
        if mv is not None and mv < t["min_views"] and not h.startswith("tg:"):
            why.append(f"objave vidi malo ljudi (medijan {mv:.0f} pregleda)")
        rr, m = s.get("rug_rate"), s.get("measured", 0)
        s["rugger"] = bool(rr is not None and m >= d["rug_min_calls"] and rr > d["rug_max"])
        s["rug_why"] = f"{rr:.0%} njegovih poziva završi kao rug ({m} izmjerenih)" if s["rugger"] else ""
        s["bought"] = bought.get(h, 0)
        # paid shill from Nicholas's own list (kol/shillers.py): proven only with many calls and a safe score
        s["paid_shill"] = h.lower() in shill_set
        if s["paid_shill"] and (m < sh["min_calls"] or (s.get("score_lo") or 0) < cfg.get("good_score", 50)):
            why.append(f"plaćeni shill s naše liste: treba {sh['min_calls']}+ izmjerenih poziva i sigurnu ocjenu "
                       f"{cfg.get('good_score', 50)}+ (ima {m})")
        s["trial"] = bool(why)
        s["trial_why"] = "; ".join(why)
        if why:
            trial.add(h)
        upd.append((json.dumps(s), h))
    con.executemany("UPDATE kols SET stats = ? WHERE handle = ?", upd)
    return trial


def on_trial(stats_json):
    try:
        return bool(json.loads(stats_json or "{}").get("trial"))
    except ValueError:
        return False


def excluded(stats_json):
    """On trial: kept out of the live watch, copy trading and "good KOL" in the group signal. A 'rugger' (more than
    rug_max of 10+ measured calls ended as a rug) is NOT excluded (Nicholas 2.11.: still give it a chance); it is
    only read less often (timeline rug_refresh_d) and marked on the page."""
    return on_trial(stats_json)


def ruggers(con):
    """Handles flagged as ruggers by the last annotate() ({} on an old kol.db)."""
    try:
        return {h for h, st in con.execute("SELECT handle, stats FROM kols WHERE stats LIKE '%\"rugger\": true%'")}
    except Exception:  # noqa: BLE001
        return set()


# ---------- 4. weekly AI profile check ----------

def audit_targets(con, cfg, now=None):
    """Top accounts (watch list first, then by score) not checked in audit.every_d days."""
    a = dcfg(cfg)["audit"]
    now = now or int(time.time())
    ensure(con)
    last = dict(con.execute("SELECT handle, ts FROM audits"))
    watch = [h for (h,) in con.execute("SELECT handle FROM watch ORDER BY score DESC")]
    top = [h for (h,) in con.execute(
        "SELECT handle FROM kols WHERE score IS NOT NULL AND COALESCE(bot, 0) = 0 AND handle NOT LIKE 'tg:%' "
        "AND handle NOT LIKE 'w:%' ORDER BY score DESC LIMIT ?", (a["top"],))]
    seen, out = set(), []
    for h in watch + top:
        if h in seen:
            continue
        seen.add(h)
        if now - (last.get(h) or 0) >= a["every_d"] * 86400:
            out.append(h)
    return out


PROMPT = """You check whether an X (Twitter) account is a real crypto KOL / trader worth tracking.
Answer ONLY with JSON: {{"verdict": one of "kol", "trader", "hakiran", "dev", "placena_grupa", "bot", "nejasno",
"why": "one short sentence in Croatian"}}.
- hakiran: a hacked account. The profile (bio, pinned post, account age) is about something unrelated to crypto
  (a sports player, musician, artist, student...) but the posts are copy-paste token spam ("vote", "listing window").
- dev: promotes its own token launches (dex paid, buybacks, "my coin", livestreams of its own chart).
- placena_grupa: mainly sells access to a paid / VIP / private group.
- bot: automated alerts or a news / listings feed, not a person.
- kol / trader: a person calling tokens or sharing their own trades.

Handle: @{handle}
Name: {name}
Bio: {bio}
Account created: {created}; followers: {followers}
Pinned post: {pinned}
Recent posts:
{posts}"""


def _ask(client, model, text):
    r = client.messages.create(model=model, max_tokens=200, messages=[{"role": "user", "content": text}])
    out = "".join(b.text for b in r.content if getattr(b, "type", "") == "text")
    m = re.search(r"\{.*\}", out, re.S)
    v = json.loads(m.group(0)) if m else {}
    from learn import postai
    usd = postai.cost(r.usage, model, batch=False)
    return v, usd


def audit(con, cfg, client=None, get=None, now=None):
    """Profile check of up to audit.per_run accounts. Returns how many were checked."""
    from kol import twapi
    a = dcfg(cfg)["audit"]
    now = now or int(time.time())
    if (not twapi.key() and get is None) or (client is None and not os.environ.get("ANTHROPIC_API_KEY")):
        return 0
    ensure(con)
    if client is None:
        import anthropic
        client = anthropic.Anthropic(timeout=60, max_retries=2)
    n = 0
    for h in audit_targets(con, cfg, now)[:a["per_run"]]:
        if disc_left(con, cfg, now) <= 0:
            break
        before = twapi.spent(con, now)
        try:
            u = twapi.user_info(con, h, get=get, now=now)
            if u is None or u.get("unavailable"):
                why = (u or {}).get("unavailableReason") or "račun ne postoji"
                con.execute("INSERT OR REPLACE INTO audits VALUES (?,?,?,?,?,?,?,?,?)",
                            (h, now, "suspendiran", f"X kaže: {why}", None, None, None, None, 0.0))
                _charge(con, now, before)
                n += 1
                continue
            pins = twapi.tweets(con, (u.get("pinnedTweetIds") or [])[:1], get=get, now=now)
            pinned = (pins[0].get("text") if pins else "") or "(nema)"
            posts = [t for (t,) in con.execute("SELECT text FROM calls WHERE handle = ? AND kind IN "
                                               "('call', 'brag', 'warn', 'bot') ORDER BY ts DESC LIMIT ?",
                                               (h, a["posts"]))]
            text = PROMPT.format(handle=h, name=u.get("name") or "", bio=(u.get("description") or "")[:400],
                                 created=u.get("createdAt") or "?", followers=u.get("followers") or 0,
                                 pinned=pinned[:400], posts="\n".join(f"- {(p or '')[:280]}" for p in posts) or "-")
            v, usd = _ask(client, a["model"], text)
        except Exception as e:  # noqa: BLE001 - one account must not stop the round
            print(f"kol audit @{h}: {type(e).__name__}: {e}", flush=True)
            _charge(con, now, before)
            continue
        _charge(con, now, before)
        verdict = v.get("verdict") if v.get("verdict") in VERDICTS else "nejasno"
        con.execute("INSERT OR REPLACE INTO audits VALUES (?,?,?,?,?,?,?,?,?)",
                    (h, now, verdict, str(v.get("why") or "")[:300], (u.get("description") or "")[:400],
                     u.get("createdAt"), u.get("followers"), pinned[:400], usd))
        try:
            from usage import meter
            meter.record("anthropic", "kol_audit", amount=usd, calls=1)
        except Exception:  # noqa: BLE001
            pass
        n += 1
    con.commit()
    return n


def bad_audits(con, cfg):
    """{handle: reason} of accounts whose latest profile check says they are not a KOL."""
    bad = set(dcfg(cfg)["audit"]["bad"])
    try:
        rows = con.execute("SELECT handle, verdict, why FROM audits").fetchall()
    except Exception:  # noqa: BLE001 - no table yet
        return {}
    return {h: f"AI provjera profila: {VERDICTS.get(v, v)}" + (f" ({w})" if w else "")
            for h, v, w in rows if v in bad}


# ---------- 5. who the proven KOLs follow ----------

GRAPH = {"kols": 60, "every_d": 7, "per_run": 10, "min_followed_by": 2, "min_followers": 1000, "page": 200}
FOLLOW_SCHEMA = """CREATE TABLE IF NOT EXISTS follows (
    src TEXT, dst TEXT, ts INTEGER, followers INTEGER, bio TEXT, PRIMARY KEY (src, dst))"""
CRYPTO = re.compile(r"crypto|sol(?:ana)?\b|memecoin|degen|trader|trading|calls?\b|gems?\b|alpha|\$[a-z]{2,}|web3|"
                    r"defi|nft|onchain|on-chain|pump|100x|1000x", re.I)


def gcfg(cfg):
    return dict(GRAPH, **(cfg.get("discover") or {}).get("graph", {}))


def graph(con, cfg, get=None, now=None):
    """Read the newest followings (one page of 200) of up to graph.per_run proven KOLs not read in graph.every_d
    days (twitterapi.io, ~$0.002 each). Returns how many KOLs were read."""
    from kol import twapi
    if not twapi.key() and get is None:
        return 0
    g = gcfg(cfg)
    now = now or int(time.time())
    con.execute(FOLLOW_SCHEMA)
    last = {t[3:]: ts for t, ts in con.execute("SELECT target, last_ts FROM searches WHERE target LIKE 'fg:%'")}
    rows = con.execute("SELECT handle, stats FROM kols WHERE score IS NOT NULL AND COALESCE(bot, 0) = 0 AND handle "
                       "NOT LIKE 'tg:%' AND handle NOT LIKE 'w:%' ORDER BY score DESC").fetchall()
    proven = [h for h, st in rows if not on_trial(st)][:g["kols"]]
    due = [h for h in proven if now - (last.get(h) or 0) >= g["every_d"] * 86400][:g["per_run"]]
    from kol import collect
    n = 0
    for h in due:
        if disc_left(con, cfg, now) <= 0:
            break
        before = twapi.spent(con, now)
        try:
            fs = twapi.followings(con, h, g["page"], get=get, now=now)
        except Exception as e:  # noqa: BLE001
            print(f"kol graph @{h}: {type(e).__name__}: {e}", flush=True)
            continue
        finally:
            _charge(con, now, before)
        con.executemany("INSERT OR REPLACE INTO follows VALUES (?,?,?,?,?)",
                        [(h, f.get("userName") or f.get("screen_name"), now, f.get("followers_count"),
                          (f.get("description") or "")[:200]) for f in fs if f.get("userName") or f.get("screen_name")])
        collect._searched(con, f"fg:{h}", "graph", now)
        n += 1
    con.commit()
    return n


def graph_candidates(con, cfg):
    """Accounts followed by at least graph.min_followed_by proven KOLs that we have not seen post yet, with a crypto
    bio or name and enough followers; most-followed-by first."""
    g = gcfg(cfg)
    try:
        # 9.11. 22:00 (Jure: "nešto guši aplikaciju"): this used to be one query with
        # "NOT EXISTS (SELECT 1 FROM calls c WHERE LOWER(c.handle) = LOWER(f.dst))" - LOWER() cannot use the calls
        # index, so SQLite scanned the whole calls table (130 MB) once PER follows row (thousands of rows): every
        # search round sat 30-47 min at 100 % of the one CPU in this function (faulthandler dumps at 20:06-21:36
        # all showed this line) and the dashboard starved (502/499). The handles that ever posted are read once
        # through the (handle, ts) index and compared in Python; the result is the same.
        seen = {h.lower() for (h,) in con.execute("SELECT DISTINCT handle FROM calls") if h}
        rows = con.execute("""SELECT f.dst, COUNT(DISTINCT f.src) AS n, MAX(f.followers), MAX(f.bio) FROM follows f
            GROUP BY LOWER(f.dst) HAVING n >= ? ORDER BY n DESC, MAX(f.followers) DESC""",
                           (g["min_followed_by"],)).fetchall()
    except Exception:  # noqa: BLE001 - no follows table yet
        return []
    from kol import bots
    return [h for h, n, fol, bio in rows if h and h.lower() not in seen and (fol or 0) >= g["min_followers"]
            and CRYPTO.search(f"{h} {bio or ''}") and not bots.HANDLE.search(h)]


STARS_LIST = os.path.join(os.path.dirname(os.path.abspath(__file__)), "stars_list.json")


def list_stars(path=None):
    """Handles from the curated public-list file kol/stars_list.json ([...] or {"handles": [...]}; entries may be
    "@handle" strings or {"handle": ...}); [] when the file is missing. They are candidates like any other account:
    trial, AI profile check and bot rules apply once they post."""
    try:
        with open(path or STARS_LIST) as f:
            d = json.load(f)
    except (OSError, ValueError):
        return []
    items = d.get("handles", []) if isinstance(d, dict) else d
    out = []
    for it in items:
        h = it.get("handle") if isinstance(it, dict) else it
        if isinstance(h, str) and h.strip().lstrip("@"):
            out.append(h.strip().lstrip("@"))
    return list(dict.fromkeys(out))
