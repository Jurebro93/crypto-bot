"""5.11. (Nicholas: "MOŽE"): live KOL calls through twitterapi.io filter rules + webhook, instead of the Apify
monitor (10 accounts every 15 min). Rules: "from:a OR from:b ..." (<= 255 chars, ~15 handles each) checked every
`xhook.interval_s` seconds; twitterapi.io POSTs matching posts to our public URL (set once in their dashboard:
https://app.memesonar.app/hook/x?key=<KOL_HOOK_KEY>). Handles: the live watch list (best scores), the stars list and
big accounts by reach, up to xhook.max_handles. Posts land in kol.db calls (source 'x_hook') through the same
parser as every other read, so strategies, scores and the demo see them within seconds.
The delivered payload shape is not documented: ingest() looks for tweet dicts in the usual places and logs the first
few raw payloads (kv xhook_samples) so the shape can be confirmed in the log.
"""
import json
import os
import sqlite3
import time
import urllib.request

API = "https://api.twitterapi.io/oapi/tweet_filter"
DEFAULT = {"max_handles": 100, "interval_s": 30, "resync_h": 6, "tag": "memesonar", "max_value": 250}


def config(cfg):
    return {**DEFAULT, **((cfg or {}).get("xhook") or {})}


def hook_url():
    from kol import store
    base = os.environ.get("RENDER_EXTERNAL_URL") or os.environ.get("KOL_HOOK_BASE")
    key = store.hook_key()
    return f"{base.rstrip('/')}/hook/x?key={key}" if base and key else None


def _api(method, path, body=None):
    from kol import twapi
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(f"{API}/{path}", data=data, method=method,
                                 headers={"X-API-Key": twapi.key() or "", "Content-Type": "application/json",
                                          "User-Agent": "memesonar/1"})
    with urllib.request.urlopen(req, timeout=30) as r:
        txt = r.read().decode()
    return json.loads(txt) if txt else {}


def handles(con, cfg):
    """Accounts worth seconds-level delivery: watch list, stars, big accounts by reach; bots never."""
    c = config(cfg)
    from kol import bots, discover, reach
    bad = bots.handles(con)
    out = []
    try:   # 9.11.: the hot list (kol/minute.hot, minute.db) goes first: measured +10 % before the stop on recent calls
        from kol import minute as _minute
        hot = list(_minute.hot_list().get("x") or [])
    except Exception:  # noqa: BLE001
        hot = []
    try:   # the X accounts the real-money account follows (single or as a crew) must arrive within seconds
        from league import copy as _copy
        from trade import settings as _settings
        followed = sorted(h for h in _copy.followed_handles(_settings.LEAGUE_USER) if not h.startswith("tg:"))
    except Exception:  # noqa: BLE001
        followed = []
    for h in followed + hot:
        if h not in bad and h not in out:
            out.append(h)
    for (h,) in con.execute("SELECT handle FROM watch ORDER BY score DESC"):
        if h not in bad and h not in out:
            out.append(h)
    fby = reach.followed_by(con)
    rows = con.execute("SELECT handle, COALESCE(followers, 0), COALESCE(score, 0) FROM kols WHERE handle NOT LIKE 'tg:%' "
                       "AND handle NOT LIKE 'w:%' AND COALESCE(bot, 0) = 0 ORDER BY COALESCE(score, 0) DESC").fetchall()
    for h, foll, _sc in rows:
        if reach.is_big(foll, fby.get(h.lower(), 0), cfg) and h not in out:
            out.append(h)
    for h in discover.list_stars():
        if h not in bad and h not in out:
            out.append(h)
    for h, _foll, _sc in rows:
        if h not in out and len(out) < c["max_handles"]:
            out.append(h)
    return out[:c["max_handles"]]


def rules_for(hs, cfg=None):
    """[(tag, value)]: handles packed into "from:a OR from:b" values under max_value characters."""
    c = config(cfg)
    out, cur = [], []
    for h in hs:
        cand = " OR ".join(f"from:{x}" for x in cur + [h])
        if len(cand) > c["max_value"] and cur:
            out.append((f"{c['tag']}-{len(out) + 1}", " OR ".join(f"from:{x}" for x in cur)))
            cur = [h]
        else:
            cur.append(h)
    if cur:
        out.append((f"{c['tag']}-{len(out) + 1}", " OR ".join(f"from:{x}" for x in cur)))
    return out


def sync(con, cfg, api=None, now=None, log=print, force=False):
    """Make twitterapi.io's rules match our handle list. False when nothing changed, None when it cannot run."""
    from kol import twapi
    api = api or _api
    now = now or int(time.time())
    if (not twapi.key() and api is _api) or not hook_url():
        return None
    c = config(cfg)
    hs = handles(con, cfg)
    want = rules_for(hs, cfg)
    state = json.loads((con.execute("SELECT value FROM kv WHERE key='xhook'").fetchone() or ("{}",))[0])
    if not force and state.get("values") == [v for _, v in want] and now - state.get("ts", 0) < c["resync_h"] * 3600:
        return False
    have = {r.get("tag"): r for r in (api("GET", "get_rules") or {}).get("rules") or [] if r.get("tag")}
    ids = {}
    for tag, value in want:
        r = have.get(tag)
        if r and r.get("rule_id"):
            api("POST", "update_rule", {"rule_id": r["rule_id"], "tag": tag, "value": value,
                                        "interval_seconds": c["interval_s"], "is_effect": 1})
            ids[tag] = r["rule_id"]
        else:
            res = api("POST", "add_rule", {"tag": tag, "value": value, "interval_seconds": c["interval_s"]}) or {}
            rid = res.get("rule_id")
            if rid:
                api("POST", "update_rule", {"rule_id": rid, "tag": tag, "value": value,
                                            "interval_seconds": c["interval_s"], "is_effect": 1})
                ids[tag] = rid
    for tag, r in have.items():   # our old rules that are no longer wanted: switched off, not deleted
        if tag.startswith(c["tag"] + "-") and tag not in ids and r.get("rule_id"):
            api("POST", "update_rule", {"rule_id": r["rule_id"], "tag": tag, "value": r.get("value") or "from:memesonar",
                                        "interval_seconds": 86400, "is_effect": 0})
    con.execute("INSERT OR REPLACE INTO kv VALUES ('xhook', ?)",
                (json.dumps({"ts": now, "values": [v for _, v in want], "ids": ids, "handles": len(hs)}),))
    con.commit()
    log(f"xhook: twitterapi pravila: {len(want)} pravila za {len(hs)} računa, provjera svakih {c['interval_s']} s")
    return True


def _tweets(payload):
    if isinstance(payload, list):
        out = []
        for p in payload:
            out += _tweets(p)
        return out
    if not isinstance(payload, dict):
        return []
    for k in ("tweets", "data", "tweet", "items", "results"):
        if k in payload and payload[k]:
            v = payload[k]
            return _tweets(v) if isinstance(v, (list, dict)) and not (isinstance(v, dict) and v.get("id")) else [v] if isinstance(v, dict) else []
    if payload.get("id") and (payload.get("text") or payload.get("fullText")):
        return [payload]
    return []


def spool_dir(kol_db=None):
    """9.11. (audit P3): payloads that could not be written (kol.db locked by the scoring round for minutes) wait here,
    next to the real kol.db file (realpath: start.sh symlinks it into $DATA_DIR), and drain() copies them in."""
    from kol import store
    return os.path.join(os.path.dirname(os.path.realpath(kol_db or store.DB)), "xhook_spool")


def spool(payload, kol_db=None, now=None, log=print):
    """Write one raw payload to the spool; returns the file path (None when even that fails)."""
    try:
        d = spool_dir(kol_db)
        os.makedirs(d, exist_ok=True)
        # pid + random tail: two dashboard threads in the same millisecond must not overwrite each other (review izvori)
        path = os.path.join(d, f"{int((now or time.time()) * 1000)}-{os.getpid()}-{os.urandom(4).hex()}.json")
        with open(path, "w") as f:
            json.dump(payload, f)
        log(f"xhook: kol.db zauzet, objava čeka u spoolu ({os.path.basename(path)})")
        return path
    except OSError as e:
        log(f"xhook: spool nije uspio: {e}")
        return None


def drain(kol_db=None, now=None, log=print, max_files=200):
    """Spooled payloads -> kol.db (run_kol collect, after the writer is free). Returns the number of new calls;
    a file stays when kol.db is still locked."""
    d = spool_dir(kol_db)
    try:
        names = sorted(os.listdir(d))[:max_files]
    except OSError:
        return 0
    n = 0
    for name in names:
        path = os.path.join(d, name)
        try:
            with open(path) as f:
                payload = json.load(f)
        except (OSError, ValueError):
            try:
                os.remove(path)
            except OSError:
                pass
            continue
        try:
            n += ingest(payload, kol_db, now, log, _spool=False)
        except sqlite3.OperationalError:
            break   # still locked: next collect
        try:
            os.remove(path)
        except OSError:
            pass
    if n:
        log(f"xhook: {n} poziva iz spoola")
    return n


def ingest(payload, kol_db=None, now=None, log=print, _spool=True):
    """Webhook POST -> kol.db calls (source 'x_hook'). Returns the number of new calls. 9.11. (audit P3/P25): when
    kol.db is locked (score.run holds a write transaction for minutes) the payload goes to the spool and 0 comes back,
    so the dashboard answers 200 and nothing is lost; new calls wake the copy loop (league/copy.wake)."""
    from kol import collect, store
    try:
        con = store.connect(kol_db or store.DB)
    except sqlite3.OperationalError:
        if _spool and spool(payload, kol_db, now, log) is not None:
            return 0
        raise
    try:
        tweets = _tweets(payload)
        calls = []
        for t in tweets:
            calls += collect.calls_from_tweet(t, source="x_hook")
        try:
            n = collect.save(con, calls)
        except sqlite3.OperationalError:
            if _spool and calls and spool(payload, kol_db, now, log) is not None:
                return 0
            raise
        try:   # the first few raw payloads, for confirming the shape in the log / on the page
            k = con.execute("SELECT value FROM kv WHERE key='xhook_samples'").fetchone()
            samples = json.loads(k[0]) if k else []
            if len(samples) < 5:
                samples.append({"ts": int(now or time.time()), "tweets": len(tweets), "calls": len(calls),
                                "raw": json.dumps(payload)[:800]})
                con.execute("INSERT OR REPLACE INTO kv VALUES ('xhook_samples', ?)", (json.dumps(samples),))
            con.execute("INSERT INTO kv VALUES ('xhook_count', '1') ON CONFLICT(key) DO UPDATE SET value = CAST(value AS INTEGER) + 1")
        except Exception:  # noqa: BLE001
            pass
        try:
            con.commit()
        except sqlite3.OperationalError:
            if _spool and calls and spool(payload, kol_db, now, log) is not None:
                return 0
            raise
        if n:
            log(f"xhook: {n} novih poziva iz {len(tweets)} objava")
            try:   # 9.11. (audit P25): the copy loop runs now, not at its next 20-second tick
                from league import copy as _copy
                _copy.wake()
            except Exception:  # noqa: BLE001
                pass
            try:   # 11.11. (Jure, flag fast_path G24): a followed influencer's call -> a fast_check (fast/enqueue)
                from fast import enqueue as _fast
                _fast.from_calls(calls)
            except Exception:  # noqa: BLE001 - never fails the webhook
                pass
        return n
    finally:
        con.close()
