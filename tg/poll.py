"""Which channels to read now, and reading them: validation of new candidates, then a schedule by heat.

hot (CA posted in the last hot_hours, or KOL score >= hot_score): every poll_hot_s; active: poll_active_s;
quiet (public, few CAs) and slow (measured and bad): poll_quiet_s. A 429 from t.me pauses all reads 5 minutes.
"""
import time
import urllib.error

from tg import reader, store

PRIORITY = {"shill_list": 0, "kolscan": 0, "solanatracker": 0, "tgstat": 1, "channels.txt": 1, "x": 2}


def interval(row, cfg, scores, now):
    name, status, last_ca_ts = row
    if status == "active" and ((last_ca_ts or 0) >= now - cfg["hot_hours"] * 3600
                               or scores.get(name, 0) >= cfg["hot_score"]):
        return cfg["poll_hot_s"]
    return cfg["poll_active_s"] if status == "active" else cfg["poll_quiet_s"]


def due(con, cfg, scores, now):
    """(to validate, to poll): names, most urgent first."""
    cands = con.execute("""SELECT name, found_via FROM channels WHERE status='candidate'
                           AND COALESCE(checked_ts,0) < ? ORDER BY found_ts""", (now - 3600,)).fetchall()
    dead = con.execute("SELECT name, found_via FROM channels WHERE status='dead' AND COALESCE(checked_ts,0) < ?",
                       (now - cfg["recheck_dead_d"] * 86400,)).fetchall()
    order = sorted(cands, key=lambda r: PRIORITY.get((r[1] or "").split(":")[0], 3)) + dead
    validate = [n for n, _ in order][:cfg["validate_per_tick"]]
    rows = con.execute("SELECT name, status, last_ca_ts, last_poll FROM channels "
                       "WHERE status IN ('active','quiet','slow')").fetchall()
    late = [(now - (lp or 0) - interval((n, s, ca), cfg, scores, now), n) for n, s, ca, lp in rows]
    poll = [n for over, n in sorted(late, reverse=True) if over >= 0]
    return validate, poll


def _distinct_cas(posts):
    return len({c for p in posts for c in p["cas"]})


def visit(con, name, cfg, now=None, read=reader.read, hype_db=None):
    """Read one channel, store new posts, update its status. Returns new CA posts. Raises on HTTP 429."""
    now = now or int(time.time())
    row = con.execute("SELECT status, fails FROM channels WHERE name=?", (name,)).fetchone()
    status, fails = row if row else ("candidate", 0)
    try:
        info = read(name)
    except urllib.error.HTTPError as e:
        if e.code == 429:
            raise
        info = {"public": False, "posts": [], "subs": 0, "title": None}
    except Exception:
        con.execute("UPDATE channels SET last_poll=?, checked_ts=? WHERE name=?", (now, now, name))
        return []
    if not info["public"]:
        fails += 1
        new_status = "dead" if status in ("candidate", "dead") or fails >= cfg["max_fails"] else status
        con.execute("UPDATE channels SET fails=?, status=?, checked_ts=?, last_poll=? WHERE name=?",
                    (fails, new_status, now, now, name))
        return []
    posts = info["posts"]
    if status in ("candidate", "dead", "quiet"):
        status = "active" if _distinct_cas(posts) >= cfg["min_cas"] else "quiet"
    con.execute("UPDATE channels SET title=COALESCE(?, title), subs=?, status=?, fails=0, checked_ts=?, last_poll=? "
                "WHERE name=?", (info["title"], info["subs"] or None, status, now, now, name))
    first = not (con.execute("SELECT last_post FROM channels WHERE name=?", (name,)).fetchone() or (0,))[0]
    new = store.save_posts(con, name, posts, "web", now, hype_db)
    if new and not first:  # how late we see a post: drives the choice between t.me/s and a live listener
        lag = sorted(max(0, now - (p["ts"] or now)) for p in new)[len(new) // 2]
        con.execute("UPDATE channels SET lag_s = CASE WHEN lag_s IS NULL THEN ? ELSE lag_s*0.8 + ?*0.2 END "
                    "WHERE name=?", (lag, lag, name))
    # snowball: channels this one forwards or links become candidates
    found = {p["fwd_from"] for p in posts if p.get("fwd_from")} | {l for p in posts for l in p.get("links", [])}
    found.discard(name)
    store.add_candidates(con, found, f"kanal:{name}", now)
    return new


def tick(con, cfg, scores, now=None, read=reader.read, sleep=time.sleep, hype_db=None):
    """One round: validate a few candidates, read the channels that are due. Returns (visited, new CA posts)."""
    now = now or int(time.time())
    if (store.kv_get(con, "backoff_until", 0) or 0) > now:
        return 0, 0
    validate, poll = due(con, cfg, scores, now)
    todo = validate + poll[:max(0, cfg["max_fetch_per_tick"] - len(validate))]
    n_new = 0
    for i, name in enumerate(todo):
        if i:
            sleep(cfg["fetch_gap_s"])
        try:
            n_new += len(visit(con, name, cfg, now, read, hype_db))
        except urllib.error.HTTPError:
            store.kv_set(con, "backoff_until", now + 300)
            store.kv_set(con, "last_429", now)
            break
        con.commit()
    con.commit()
    return len(todo), n_new


def rebalance(con, cfg, scores, calls):
    """Measured-bad channels go slow, good ones come back; too many active -> the stalest go quiet."""
    for name, n in calls.items():
        sc = scores.get(name)
        if sc is not None and n >= cfg["drop_min_calls"] and sc < cfg["drop_score"]:
            con.execute("UPDATE channels SET status='slow' WHERE name=? AND status='active'", (name,))
        elif sc is not None and sc >= cfg["drop_score"]:
            con.execute("UPDATE channels SET status='active' WHERE name=? AND status='slow'", (name,))
    act = [n for n, in con.execute("SELECT name FROM channels WHERE status='active' "
                                   "ORDER BY COALESCE(last_ca_ts,0) DESC")]
    for name in act[cfg["max_active"]:]:
        if scores.get(name, 0) < cfg["hot_score"]:
            con.execute("UPDATE channels SET status='quiet' WHERE name=?", (name,))
