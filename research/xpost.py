"""One X post the owner asked about (10.11., Jure: "transkribiraj ovu metodu, istraži i pošalji mi na mail s
zaključcima i kako se može primijeniti na naš algoritam"): https://x.com/iiamjeph/status/2120056013063671846.

x.com does not answer from the research sandbox, so the server reads the post with the X API it already pays for
(kol/twapi.py, twitterapi.io, $0.00015 a post): the post itself, the author's posts in its conversation (the
thread), the X article text when the post is one, and the quoted post. Cost: a few posts, under $0.01, counted in
the twapi day total and usage/meter. READ ONLY: nothing else is written.

Output: DATA_DIR/research/xpost-<id>.json (raw answers) and .md (the text), the text in the log as
"XPOST i/n <gzip+base64>" lines (report/dump style), and the MCP tool get_research(name="xpost-<id>").
Run: python3 -m research.xpost [--force]; start.sh runs it once (marker .done next to the files).
"""
import argparse
import base64
import gzip
import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

POST_ID = "2120056013063671846"
AUTHOR = "iiamjeph"
NAME = f"xpost-{POST_ID}"
ARTICLE_URL = "https://api.twitterapi.io/twitter/article"
LOG_CHUNK = 3000


def _text(t):
    """The readable part of one post: author, time, counts, text, links, media, quoted post."""
    if not isinstance(t, dict):
        return ""
    a = t.get("author") or {}
    ents = t.get("entities") or {}
    urls = [u.get("expanded_url") or u.get("url") for u in (ents.get("urls") or []) if isinstance(u, dict)]
    media = [m.get("media_url_https") or m.get("url") for m in ((t.get("extendedEntities") or {}).get("media")
                                                                 or ents.get("media") or []) if isinstance(m, dict)]
    head = (f"@{a.get('userName')} ({a.get('name')}, {a.get('followers')} pratitelja) · {t.get('createdAt')} · "
            f"lajkova {t.get('likeCount')}, repostova {t.get('retweetCount')}, odgovora {t.get('replyCount')}, "
            f"pregleda {t.get('viewCount')} · {t.get('url') or ''}")
    out = [head, t.get("text") or ""]
    if urls:
        out.append("Linkovi: " + ", ".join(u for u in urls if u))
    if media:
        out.append("Slike/video: " + ", ".join(m for m in media if m))
    q = t.get("quoted_tweet")
    if isinstance(q, dict) and q:
        out.append("Citira:\n" + _text(q))
    return "\n".join(out)


def fetch(get=None, kcon=None):
    """{"post", "thread", "article", "errors"} from the X API. get(url, params) -> dict (tests pass a fake)."""
    from kol import store as kstore, twapi
    get = get or twapi._get_url
    own = kcon is None
    kcon = kcon or kstore.connect()
    out = {"post": None, "thread": [], "article": None, "errors": []}
    try:
        try:
            ts = twapi.tweets(kcon, [POST_ID], get=get)
            out["post"] = ts[0] if ts else None
        except Exception as e:  # noqa: BLE001
            out["errors"].append(f"post: {type(e).__name__}: {e}")
        try:   # the author's own posts in the conversation (the thread), oldest first
            d = get(twapi.URL, {"query": f"conversation_id:{POST_ID} from:{AUTHOR}", "queryType": "Latest", "cursor": ""})
            th = [t for t in (d.get("tweets") or []) if str(t.get("id")) != POST_ID]
            twapi._add(kcon, twapi.cost(len(th)), time.time())
            out["thread"] = sorted(th, key=lambda t: str(t.get("id")))
        except Exception as e:  # noqa: BLE001
            out["errors"].append(f"thread: {type(e).__name__}: {e}")
        try:   # a long-form X article (the post is then a link card)
            d = get(ARTICLE_URL, {"tweet_id": POST_ID})
            art = d.get("article") or d.get("data")
            if art:
                out["article"] = art
                twapi._add(kcon, twapi.MIN_REQ, time.time())
        except Exception as e:  # noqa: BLE001
            out["errors"].append(f"article: {type(e).__name__}: {e}")
        kcon.commit()
    finally:
        if own:
            kcon.close()
    return out


def article_text(art):
    if not isinstance(art, dict):
        return ""
    parts = [art.get("title") or ""]
    for c in art.get("contents") or art.get("content") or []:
        if isinstance(c, dict):
            parts.append(c.get("text") or "")
        elif isinstance(c, str):
            parts.append(c)
    if isinstance(art.get("text"), str):
        parts.append(art["text"])
    return "\n\n".join(p for p in parts if p)


def markdown(r):
    L = [f"# X objava {POST_ID} (@{AUTHOR})", "", "## Objava", _text(r.get("post")) or "(nije dohvaćena)"]
    if r.get("article"):
        L += ["", "## X članak", article_text(r["article"]) or json.dumps(r["article"], ensure_ascii=False)[:20000]]
    if r.get("thread"):
        L += ["", f"## Nit autora ({len(r['thread'])})"]
        for t in r["thread"]:
            L += ["", _text(t)]
    if r.get("errors"):
        L += ["", "## Greške", *r["errors"]]
    return "\n".join(L)


def main(argv=None, get=None, log=None):
    log = log or (lambda s: print(s, flush=True))
    p = argparse.ArgumentParser(description="Jedna X objava (samo čitanje)")
    p.add_argument("--force", action="store_true")
    a = p.parse_args(argv)
    from research import hope
    d = hope.out_dir()
    marker = os.path.join(d, NAME + ".done")
    if os.path.exists(marker) and not a.force:
        log("research xpost: već napravljeno")
        return 0
    from kol import twapi
    if not twapi.key() and get is None:
        log("research xpost: nema TWITTERAPI_IO_KEY")
        return 1
    r = fetch(get)
    r["generated_ts"] = int(time.time())
    with open(os.path.join(d, NAME + ".json"), "w") as f:
        json.dump(r, f, ensure_ascii=False)
    md = markdown(r)
    with open(os.path.join(d, NAME + ".md"), "w") as f:
        f.write(md)
    blob = base64.b64encode(gzip.compress(md.encode(), 9)).decode()
    parts = [blob[i:i + LOG_CHUNK] for i in range(0, len(blob), LOG_CHUNK)] or [""]
    for i, part in enumerate(parts):
        log(f"XPOST {i + 1}/{len(parts)} {part}")
    log(f"research xpost: gotovo, objava {'da' if r['post'] else 'ne'}, nit {len(r['thread'])}, "
        f"članak {'da' if r['article'] else 'ne'}, greške {len(r['errors'])}")
    if r["post"] or r["article"]:
        with open(marker, "w") as f:
            f.write(str(int(time.time())))
    return 0


if __name__ == "__main__":
    sys.exit(main())
