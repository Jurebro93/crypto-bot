"""AI reads every KOL / Telegram post that names a token (Claude Haiku 5.5, Message Batches = half price).

One row per post in ai.db posts_ai (this module is its only writer; kol.db and tg.db are only read):
  kind: call / mention / warning / ad / brag / joke / repost
  paid_promo: the post is a paid promotion (ad, partner, sponsored, #ad)
  conviction 1-5, already_bought (the author says they hold it), narrative (a few words), model, classified_at.
The KOL thread reads the same table (KOL power and groups), so there is one reader, not two.

Signals for learning (features(), point-in-time: only posts written BEFORE the decision moment count):
  ai_poziv        calls on the token in the 6 h before (0..1, 3+ = 1)
  ai_uvjerenje    highest conviction among those calls (0..1)
  ai_placeno      share of the posts that were paid promotion
  ai_upozorenje   someone warned about the token (1/0)
  ai_kupio        a caller says they already bought (1/0)
Missing (no post read) = the feature is absent, which the model treats as "not measured".

Cost is metered to usage.db (service anthropic, method postai) from the token counts of every result, and shown on
the Učenje page next to what the AI signals add (champion ablation), so it is visible whether it pays for itself.
"""
import json
import os
import re
import sqlite3
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.path.join(ROOT, "ai.db")
KOL_DB = os.path.join(ROOT, "kol.db")
TG_DB = os.path.join(ROOT, "tg.db")
MODEL = os.environ.get("POSTAI_MODEL", "claude-haiku-5-5")
# $ per million tokens (input, output) for Claude Haiku 5.5; Message Batches bill half of it
PRICE = {"claude-haiku-5-5": (0.10, 0.50)}
BATCH_DISCOUNT = 0.5
DEFAULT = {"enabled": True, "window_h": 6, "per_run": 2500, "per_day": 12000, "max_chars": 1200}
KINDS = ["call", "mention", "warning", "ad", "brag", "joke", "repost"]

SCHEMA = """
CREATE TABLE IF NOT EXISTS posts_ai (
    src TEXT, post_id TEXT, ts INTEGER, handle TEXT, tokens TEXT, kind TEXT, paid_promo INTEGER, conviction INTEGER,
    already_bought INTEGER, narrative TEXT, model TEXT, classified_at INTEGER, cost_usd REAL,
    PRIMARY KEY (src, post_id));
CREATE INDEX IF NOT EXISTS posts_ai_ts ON posts_ai (ts);
CREATE TABLE IF NOT EXISTS post_tokens (src TEXT, post_id TEXT, token TEXT, ts INTEGER, PRIMARY KEY (src, post_id, token));
CREATE INDEX IF NOT EXISTS post_tokens_tok ON post_tokens (token, ts);
CREATE TABLE IF NOT EXISTS batches (
    id TEXT PRIMARY KEY, created INTEGER, n INTEGER, status TEXT, ids TEXT, kind TEXT, done_ts INTEGER, cost_usd REAL);
CREATE TABLE IF NOT EXISTS kv (k TEXT PRIMARY KEY, v TEXT);
"""

SYSTEM = (
    "You label crypto social-media posts (X / Telegram) about Solana meme tokens for a research tool. For each post "
    "return: kind = call (author recommends buying / says it will go up), mention (names the token without a "
    "recommendation), warning (says rug, scam, sell, avoid), ad (paid promotion or listing advert), brag (shows "
    "profit already made), joke, repost (shares someone else's call); paid_promo = true if it reads as paid "
    "(ad, partner, sponsored, #ad, 'promo'); conviction 1-5 (1 = casual, 5 = all-in, very strong); already_bought = "
    "the author says they hold or bought it; narrative = 1-4 words for the theme (e.g. 'AI agent', 'cat', "
    "'political'). Judge only the text. Never give advice.")

OUT_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["kind", "paid_promo", "conviction", "already_bought", "narrative"],
    "properties": {
        "kind": {"type": "string", "enum": KINDS},
        "paid_promo": {"type": "boolean"},
        "conviction": {"type": "integer", "description": "1-5"},  # min/max are rejected by structured outputs
        "already_bought": {"type": "boolean"},
        "narrative": {"type": "string"},
    },
}


def config():
    from learn import outcomes
    return {**DEFAULT, **(outcomes.config().get("postai") or {})}


def connect(path=None):
    con = sqlite3.connect(path or DB, timeout=60)
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    return con


def _ro(path):
    if not path or not os.path.exists(path):
        return None
    c = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=30)
    c.row_factory = sqlite3.Row
    return c


def _cid(src, post_id):
    return (src + "_" + re.sub(r"[^A-Za-z0-9_-]", "-", str(post_id)))[:64]


def pending_posts(con, now, cfg, kol_db=KOL_DB, tg_db=TG_DB):
    """Posts from the last window_h hours that have no label yet: [(src, post_id, ts, handle, text, [tokens])]."""
    since = now - cfg["window_h"] * 3600
    done = {(r[0], r[1]) for r in con.execute("SELECT src, post_id FROM posts_ai WHERE ts >= ?", (since,))}
    inflight = set()
    if not con.execute("SELECT 1 FROM kv WHERE k='popravak_sheme_1'").fetchone():
        con.execute("DELETE FROM kv WHERE k LIKE 'greska:%'")  # failures from the rejected min/max schema
        con.execute("INSERT INTO kv VALUES ('popravak_sheme_1', '1')")
        con.commit()
    for (k,) in con.execute("SELECT k FROM kv WHERE k LIKE 'greska:%'"):
        _, src, pid = k.split(":", 2)
        inflight.add((src, pid))
    for (ids,) in con.execute("SELECT ids FROM batches WHERE status='poslano'"):
        for v in json.loads(ids or "{}").values():
            inflight.add((v[0], v[1]))
    out = {}
    k = _ro(kol_db)
    if k is not None:
        try:
            try:
                from kol import bots as kbots
                bots = set(kbots.handles(k))
            except Exception:  # noqa: BLE001
                bots = set()
            for tid, token, handle, ts, text in k.execute(
                    "SELECT tweet_id, token, handle, ts, text FROM calls WHERE ts >= ? AND text IS NOT NULL AND text != ''",
                    (since,)):
                if handle in bots:
                    continue
                key = ("x", str(tid))
                if key in done or key in inflight:
                    continue
                o = out.setdefault(key, ["x", str(tid), ts, handle, text, []])
                if token not in o[5]:
                    o[5].append(token)
        except sqlite3.OperationalError as e:
            print(f"postai: kol.db: {e}")
        finally:
            k.close()
    t = _ro(tg_db)
    if t is not None:
        try:
            for ch, post, ts, text, cas in t.execute(
                    "SELECT channel, post, ts, text, cas FROM posts WHERE ts >= ? AND cas IS NOT NULL AND cas != '' "
                    "AND (fwd_from IS NULL OR fwd_from = '') AND text IS NOT NULL", (since,)):
                key = ("tg", f"{ch}/{post}")
                if key in done or key in inflight:
                    continue
                try:
                    toks = json.loads(cas) if cas.strip().startswith("[") else [c for c in cas.split(",") if c]
                except ValueError:
                    toks = [c for c in cas.split(",") if c]
                out[key] = ["tg", f"{ch}/{post}", ts, f"tg:{ch}", text, toks]
        except sqlite3.OperationalError as e:
            print(f"postai: tg.db: {e}")
        finally:
            t.close()
    return sorted(out.values(), key=lambda r: -r[2])


def _request(text, cfg):
    return {"model": MODEL, "max_tokens": 400, "system": SYSTEM,
            "output_config": {"effort": "low", "format": {"type": "json_schema", "schema": OUT_SCHEMA}},
            "messages": [{"role": "user", "content": "Post:\n" + text[:cfg["max_chars"]]}]}


def cost(usage, model=MODEL, batch=True):
    pin, pout = PRICE.get(model, PRICE["claude-haiku-5-5"])
    usd = ((getattr(usage, "input_tokens", 0) or 0) * pin + (getattr(usage, "output_tokens", 0) or 0) * pout) / 1e6
    return usd * (BATCH_DISCOUNT if batch else 1)


def _today_count(con, now):
    day0 = now - now % 86400
    return con.execute("SELECT COALESCE(SUM(n), 0) FROM batches WHERE created >= ?", (day0,)).fetchone()[0]


def submit(con, client, now=None, cfg=None, kol_db=KOL_DB, tg_db=TG_DB):
    """Send unlabelled posts as one batch (within per_run / per_day caps). Returns the number sent."""
    cfg = cfg or config()
    now = now or time.time()
    room = min(cfg["per_run"], cfg["per_day"] - _today_count(con, now))
    if room <= 0:
        return 0
    posts = pending_posts(con, now, cfg, kol_db, tg_db)[:room]
    if not posts:
        return 0
    ids, reqs = {}, []
    for src, pid, ts, handle, text, toks in posts:
        cid = _cid(src, pid)
        if cid in ids:
            continue
        ids[cid] = [src, pid, ts, handle, toks]
        reqs.append({"custom_id": cid, "params": _request(text, cfg)})
    b = client.messages.batches.create(requests=reqs)
    con.execute("INSERT INTO batches VALUES (?,?,?,?,?,?,?,?)",
                (b.id, int(now), len(reqs), "poslano", json.dumps(ids), "postai", None, 0.0))
    con.commit()
    return len(reqs)


def collect(con, client, now=None):
    """Store the results of finished batches. Returns the number of labelled posts."""
    now = now or time.time()
    n = 0
    waiting, errors = 0, {}
    for bid, ids in con.execute("SELECT id, ids FROM batches WHERE status='poslano'").fetchall():
        b = client.messages.batches.retrieve(bid)
        if b.processing_status != "ended":
            waiting += 1
            if now - (con.execute("SELECT created FROM batches WHERE id=?", (bid,)).fetchone()[0] or now) > 2 * 86400:
                con.execute("UPDATE batches SET status='isteklo' WHERE id=?", (bid,))
            continue
        ids = json.loads(ids or "{}")
        total = 0.0
        for res in client.messages.batches.results(bid):
            meta = ids.get(res.custom_id)
            if not meta:
                continue
            if res.result.type != "succeeded":
                err = getattr(res.result, "error", None)
                why = getattr(getattr(err, "error", err), "message", None) or res.result.type
                errors[str(why)[:120]] = errors.get(str(why)[:120], 0) + 1
                src, pid = meta[0], meta[1]
                con.execute("INSERT OR IGNORE INTO kv VALUES (?, ?)", (f"greska:{src}:{pid}", str(int(now))))
                continue
            msg = res.result.message
            c = cost(msg.usage, msg.model or MODEL)
            total += c
            if msg.stop_reason == "refusal":
                continue
            try:
                out = json.loads("".join(blk.text for blk in msg.content if blk.type == "text"))
            except ValueError:
                continue
            src, pid, ts, handle, toks = meta
            con.execute("INSERT OR REPLACE INTO posts_ai VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (src, pid, ts, handle, json.dumps(toks), out.get("kind"), int(bool(out.get("paid_promo"))),
                         max(1, min(5, int(out.get("conviction") or 1))), int(bool(out.get("already_bought"))),
                         (out.get("narrative") or "")[:60], msg.model or MODEL, int(now), round(c, 6)))
            for tok in toks:
                con.execute("INSERT OR IGNORE INTO post_tokens VALUES (?,?,?,?)", (src, pid, tok, ts))
            n += 1
        con.execute("UPDATE batches SET status='gotovo', done_ts=?, cost_usd=? WHERE id=?", (int(now), round(total, 4), bid))
        try:
            from usage import meter
            meter.record("anthropic", "postai", amount=total, calls=len(ids))
            meter.flush()
        except Exception:  # noqa: BLE001
            pass
    con.commit()
    if waiting or errors:
        print(f"postai: paketa u obradi {waiting}" + (f", greške {errors}" if errors else ""))
    return n


def step(path=None, now=None):
    """One pass (run_sched every 30 min): collect finished batches, then send new posts."""
    cfg = config()
    if not cfg["enabled"]:
        return "isključeno"
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return "nema ANTHROPIC_API_KEY"
    try:
        import anthropic
    except ImportError:
        return "nema paketa anthropic"
    client = anthropic.Anthropic(timeout=120, max_retries=2)
    con = connect(path)
    try:
        got = collect(con, client, now)
        sent = submit(con, client, now, cfg)
        return f"označeno {got}, poslano {sent}"
    finally:
        con.close()


# ---------------------------------------------------------------- features

def features(token, ts, con=None, path=None, window_h=6):
    """ai_* signals for a token at moment ts from posts written before ts; {} when no post was read."""
    own = con is None
    con = con or _ro(path or DB)
    if con is None:
        return {}
    try:
        rows = con.execute(
            "SELECT a.kind, a.paid_promo, a.conviction, a.already_bought FROM post_tokens t JOIN posts_ai a "
            "ON a.src=t.src AND a.post_id=t.post_id WHERE t.token=? AND t.ts < ? AND t.ts >= ?",
            (token, ts, ts - window_h * 3600)).fetchall()
    except sqlite3.OperationalError:
        rows = []
    finally:
        if own:
            con.close()
    if not rows:
        return {}
    calls = [r for r in rows if r[0] in ("call", "brag")]
    return {"ai_poziv": min(1.0, len(calls) / 3), "ai_uvjerenje": (max(r[2] for r in calls) - 1) / 4 if calls else 0.0,
            "ai_placeno": sum(r[1] for r in rows) / len(rows), "ai_upozorenje": 1.0 if any(r[0] == "warning" for r in rows) else 0.0,
            "ai_kupio": 1.0 if any(r[3] for r in calls) else 0.0}


def spend(days=30, now=None, path=None):
    """$ spent on post reading in the last `days` days (from ai.db batches) and posts labelled."""
    now = now or time.time()
    con = _ro(path or DB)
    if con is None:
        return {"usd": 0.0, "posts": 0}
    try:
        usd = con.execute("SELECT COALESCE(SUM(cost_usd), 0) FROM batches WHERE created >= ?", (now - days * 86400,)).fetchone()[0]
        n = con.execute("SELECT COUNT(*) FROM posts_ai WHERE classified_at >= ?", (now - days * 86400,)).fetchone()[0]
        return {"usd": round(usd, 2), "posts": n}
    except sqlite3.OperationalError:
        return {"usd": 0.0, "posts": 0}
    finally:
        con.close()


if __name__ == "__main__":
    print(step())
    sys.exit(0)
