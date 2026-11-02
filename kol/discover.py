"""Smarter search for real KOLs and traders (2.11.2026, after fake "KOLs" were found at the top of the KOL tab).

  winners   start from tokens that really rose (2x+ in 24 h) and ask twitterapi.io who posted the CA BEFORE the rise
            (until_time = the first post that came after the price had already doubled). Those authors become
            candidates; the timeline rotation already reads early winner callers first.
  annotate  per KOL in kols.stats:
              bought   tokens it called and that its own known wallet also bought (kol/idents + chainwatch): a trader
                       who puts money where the post is
              trial    "na probi": fewer than trial.min_calls measured calls, less than trial.days of history with
                       us, or posts nobody sees (median views < trial.min_views). On trial = no live watch, no copy
                       trading, no "good KOL" in the group signal; the page shows the badge and why.
  audit     once a week the top accounts get a profile check: twitterapi.io profile (bio, age, pinned post) plus the
            last posts, read by Claude Haiku: real caller / trader, or hacked account, dev of its own tokens, paid
            group seller, news bot, suspended. A bad verdict marks the account as "not a KOL" (kol/bots.py reads
            the audits table), the reason is shown on its page.

Spend: winners and audit use the same twitterapi.io daily budget as the timelines (timeline_twapi.daily_usd);
winners has its own share (discover.winners_usd). Audit: ~20 profiles + ~20 short Haiku calls a week (< $0.05).
"""
import json
import os
import re
import time

DEFAULTS = {"win_x": 1.0, "win_hours": 48, "win_per_run": 4, "win_pages": 3, "winners_usd": 0.12, "win_back_h": 48,
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
    total = (cfg.get("timeline_twapi") or {}).get("daily_usd", 0.7)
    day = time.strftime("%Y-%m-%d", time.gmtime(now))
    row = con.execute("SELECT value FROM kv WHERE key = ?", (f"twwin:{day}",)).fetchone()
    mine = float(row[0]) if row else 0.0
    n = 0
    for tok, since, until in winner_targets(con, cfg, now)[:d["win_per_run"]]:
        if mine >= d["winners_usd"]:
            break
        before = twapi.spent(con, now)
        budget = min(total, before + d["winners_usd"] - mine)
        try:
            items = twapi.search(con, tok, since, budget, get=get, max_pages=d["win_pages"], now=now, until_ts=until)
        except Exception as e:  # noqa: BLE001 - one bad query must not stop the round
            print(f"kol winners: upit nije uspio ({type(e).__name__}: {e})", flush=True)
            items = []
        mine += twapi.spent(con, now) - before
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
        s["bought"] = bought.get(h, 0)
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
    budget = (cfg.get("timeline_twapi") or {}).get("daily_usd", 0.7)
    n = 0
    for h in audit_targets(con, cfg, now)[:a["per_run"]]:
        if twapi.spent(con, now) >= budget:
            break
        try:
            u = twapi.user_info(con, h, get=get, now=now)
            if u is None or u.get("unavailable"):
                why = (u or {}).get("unavailableReason") or "račun ne postoji"
                con.execute("INSERT OR REPLACE INTO audits VALUES (?,?,?,?,?,?,?,?,?)",
                            (h, now, "suspendiran", f"X kaže: {why}", None, None, None, None, 0.0))
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
            continue
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
