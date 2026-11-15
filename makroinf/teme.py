"""The topics (narratives) of the day (15.11. navečer, the owner: "... zaključke donositi koje su korisnije, koje
interpretiraju veliku količinu podataka i sažimaju ih u jednostavne izjave").

Once in narr_every_s (6 h) the macro posts of the last 24 h (tweets.macro = 1, the classified market calls; at most
narr_max_posts, the most engaged first) are grouped into at most 5 topics by the cheap model (narr_model, gpt-5-mini,
strict JSON): a short title and one plain sentence in Croatian and English, and the ids of the posts of each topic.
The side of a topic is NOT the model's: it is counted from our own classification of its posts (mood.verdict on the
accounts' sides). Ids not in the request are dropped; a topic needs 2+ posts; sorted by accounts, then posts.

Budget: inside the daily OpenAI cap (store phase "dan", what "teme") and at most narr_openai_usd (0,05 $) a UTC day;
a request is sent only when the most it can cost fits both. Without a key, at the cap, or when the model fails, the
topics come from a fixed keyword lexicon (LEXICON, model "ključne riječi"), so the page never goes empty and never
pays twice. Stored in topics_d (one row a UTC day, replaced by each run). The text the model writes is cleaned: no
links, no addresses, no "$" signs, no handles.
"""
import json
import re
import time

from makroinf import mood, store

D = 86400
PROMPT_VERSION = "teme-v1 (15.11.2026.)"
LEXICON = (
    ("etf", "ETF tokovi", "ETF flows", r"\betfs?\b|inflows?|outflows?"),
    ("fed", "Fed, kamate i inflacija", "Fed, rates and inflation",
     r"\bfed\b|fomc|rate cuts?|rate hikes?|powell|interest rates?|\bcpi\b|inflation"),
    ("altseason", "Altcoini i altseason", "Altcoins and altseason", r"altseason|alt season|altcoins?|\balts\b"),
    ("memes", "Meme coini", "Meme coins", r"memecoins?|meme coins?|\bmemes\b"),
    ("ath", "Novi vrh BTC-a", "New BTC highs", r"\bath\b|all[- ]time highs?|new highs?|price discovery"),
    ("bottom", "Dno i korekcija", "Bottom and correction", r"\bbottom|correction|capitulat|bear market|crash"),
    ("cycle", "Ciklus i halving", "Cycle and halving", r"\bcycle\b|halving|4[- ]year"),
    ("liquidity", "Likvidnost", "Liquidity", r"liquidity|\bm2\b|money printing|\bqe\b|\bqt\b"),
    ("eth", "Ethereum", "Ethereum", r"\beth\b|ethereum"),
    ("sol", "Solana", "Solana", r"\bsol\b|solana"),
    ("levels", "Ključne razine BTC-a", "Key BTC levels", r"support|resistance|\d{2,3}k\b"),
    ("stocks", "Dionice, dolar i obveznice", "Stocks, dollar and bonds",
     r"s&p|\bspx\b|nasdaq|stocks?|equities|\bdxy\b|dollar|bonds?|yields?"),
    ("regulation", "Regulacija", "Regulation", r"\bsec\b|regulat|congress|senate|\bbill\b|stablecoin"),
    ("leverage", "Poluga i likvidacije", "Leverage and liquidations",
     r"liquidat|leverage|funding|open interest|\blongs\b|\bshorts\b"),
)
INSTRUCTIONS = """You group crypto market posts from X by the TOPIC (narrative) they discuss, e.g. ETF flows, the Fed
and rates, altseason, a key BTC level, meme coins, the cycle. Return at most 5 topics, the biggest first; a topic needs
at least 2 posts. For each: title_en and title_hr (Croatian), at most 6 words; summary_en and summary_hr, ONE plain
sentence of at most 25 words saying what these accounts say about it (no advice, no names, no links, no tickers with $,
no numbers that are not in the posts); ids: the ids of the posts in the topic (only ids from the input)."""
SCHEMA = {"type": "object", "additionalProperties": False, "required": ["topics"], "properties": {"topics": {
    "type": "array", "items": {"type": "object", "additionalProperties": False,
                               "required": ["title_en", "title_hr", "summary_en", "summary_hr", "ids"],
                               "properties": {"title_en": {"type": "string"}, "title_hr": {"type": "string"},
                                              "summary_en": {"type": "string"}, "summary_hr": {"type": "string"},
                                              "ids": {"type": "array", "items": {"type": "string"}}}}}}}
_CLEAN = (re.compile(r"https?://\S+"), re.compile(r"(?<![\w/])[1-9A-HJ-NP-Za-km-z]{32,44}(?!\w)"),
          re.compile(r"0x[0-9a-fA-F]{40}"), re.compile(r"@\w{1,15}"))


def clean(text, n=220):
    t = " ".join(str(text or "").split())
    for rx in _CLEAN:
        t = rx.sub("", t)
    t = re.sub(r"\$\s?(?=[\d.])", "", t)          # "$100k" -> "100k"
    t = re.sub(r"\$([A-Za-z]{2,10})", r"\1", t)   # "$BTC" -> "BTC"
    t = t.replace("$", "")
    return " ".join(t.split())[:n]


def posts(con, t0, t1, limit):
    """[(id, handle, ts, text, engagement)] of the macro posts in [t0, t1), the most engaged first."""
    return store.q(con, """SELECT t.id, t.handle, t.ts, t.text, COALESCE(t.likes, 0) + 2 * COALESCE(t.retweets, 0) +
        COALESCE(t.quotes, 0) e FROM tweets t JOIN accounts a ON a.handle = t.handle WHERE t.macro = 1 AND
        a.status IN ('aktivan', 'neaktivan') AND t.ts >= ? AND t.ts < ? ORDER BY e DESC, t.ts DESC LIMIT ?""",
                   (int(t0), int(t1), int(limit)))


def _sides(con, ids):
    """{handle: side} of the posts' own calls (our classification), and the per-post call list."""
    if not ids:
        return {}
    q = ",".join("?" * len(ids))
    rows = store.q(con, f"SELECT id, asset, handle, ts, direction, conditional, confidence, promo, unclear, withdraws, "
                        f"trigger_level, trigger_dir FROM calls WHERE id IN ({q})", tuple(ids))
    keys = ("id", "asset", "handle", "ts", "direction", "conditional", "confidence", "promo", "unclear", "withdraws",
            "trigger_level", "trigger_dir")
    return mood.sides([dict(zip(keys, r)) for r in rows])


def finish(con, topics, by_id):
    """Validated topics with their sources: [{title_hr, title_en, summary_hr, summary_en, ids, handles, n_posts,
    n_accounts, broj, presuda}] (at most 5)."""
    out, used = [], set()
    for tp in topics or []:
        ids = [str(i) for i in tp.get("ids") or [] if str(i) in by_id and str(i) not in used]
        if len(ids) < 2:
            continue
        used.update(ids)
        st = _sides(con, ids)
        b = {"bik": sum(1 for x in st.values() if x["s"] > 0), "medvjed": sum(1 for x in st.values() if x["s"] < 0),
             "neutralno": sum(1 for x in st.values() if x["s"] == 0)}
        hs = []
        for i in ids:
            if by_id[i][1] not in hs:
                hs.append(by_id[i][1])
        out.append({"title_hr": clean(tp.get("title_hr"), 60), "title_en": clean(tp.get("title_en"), 60),
                    "summary_hr": clean(tp.get("summary_hr")), "summary_en": clean(tp.get("summary_en")),
                    "ids": ids[:40], "posts": [[i, by_id[i][1]] for i in ids[:40]], "handles": hs,
                    "n_posts": len(ids), "n_accounts": len(hs), "broj": b,
                    "presuda": mood.verdict(b["bik"], b["medvjed"], b["neutralno"]) if sum(b.values()) >= 3 else
                    "premalo"})
    out.sort(key=lambda x: (-x["n_accounts"], -x["n_posts"]))
    return out[:5]


def lexicon_topics(rows):
    """The fallback: posts per lexicon topic (a post in its first matching topic only)."""
    groups = {}
    for i, h, _ts, text, _e in rows:
        for key, hr, en, pat in LEXICON:
            if re.search(pat, text or "", re.I):
                groups.setdefault(key, (hr, en, []))[2].append(str(i))
                break
    out = []
    for key, (hr, en, ids) in groups.items():
        hs = len({r[1] for r in rows if str(r[0]) in set(ids)})
        out.append({"title_hr": hr, "title_en": en,
                    "summary_hr": f"{hs} računa piše o temi „{hr.lower()}” u {len(ids)} objava.",
                    "summary_en": f"{hs} accounts write about {en.lower()} in {len(ids)} posts.", "ids": ids})
    return out


def due(con, c, now):
    return now - float(store.kv(con, "teme_ts") or 0) >= float(c.get("narr_every_s") or 6 * 3600)


def run(con, c=None, now=None, log=print, call=None, force=False):
    """The day's topics when due. Returns {"n", "model", "usd", "cap"} or None (not due / too few posts)."""
    from critic import openai_api
    c = c or store.config()
    now = int(now or time.time())
    if not force and not due(con, c, now):
        return None
    store.kv(con, "teme_ts", str(now))
    rows = posts(con, now - D, now, int(c.get("narr_max_posts") or 300))
    if len(rows) < 6:
        con.commit()
        return None
    by_id = {str(r[0]): r for r in rows}
    out = {"n": len(rows), "model": "ključne riječi", "usd": 0.0, "cap": None}
    topics = None
    day = store.day(now)
    left = min(store.left(con, "openai", "dan", now, c),
               max(0.0, float(c.get("narr_openai_usd") or 0) - store.spent(con, "openai", "dan", day, "teme")))
    model = c.get("narr_model") or c.get("cls_model") or "gpt-5-mini"
    items = [{"id": str(i), "author": f"@{h}", "text": " ".join((tx or "").split())[:280]} for i, h, _ts, tx, _e in rows]
    text = "Posts (JSON lines):\n" + "\n".join(json.dumps(x, ensure_ascii=False) for x in items)
    max_out = 1800
    est = openai_api.max_cost(model, len(INSTRUCTIONS) + len(text), max_out)
    if call is None and not openai_api.has_key():
        out["cap"] = "nema OPENAI_API_KEY"
    elif est > left:
        out["cap"] = f"strop tema: ostalo {left:.4f} $, zahtjev do {est:.4f} $"
    else:
        call = call or (lambda *a, **k: openai_api.call_json(*a, **k))
        try:
            r = call(model, INSTRUCTIONS, text, SCHEMA, "teme_dana", max_output_tokens=max_out, effort="minimal")
            usd = float(r.get("cost_usd") or 0.0)
            store.book(con, "openai", usd, "dan", "teme", now)
            out.update(usd=round(usd, 5), model=r.get("model") or model)
            topics = finish(con, ((r.get("data") or {}).get("topics")), by_id)
        except openai_api.ApiError as e:
            u = openai_api.cost(e.model or model, e.usage) if e.usage else 0.0
            if u:
                store.book(con, "openai", u, "dan", "teme")
            out["cap"] = f"model: {str(e)[:100]}"
    if not topics:
        topics = finish(con, lexicon_topics(rows), by_id)
        out["model"] = "ključne riječi"
    data = {"ts": now, "od": now - D, "do": now, "topics": topics, "prompt_v": PROMPT_VERSION,
            "n_objava": len(rows), "n_racuna": len({r[1] for r in rows})}
    con.execute("INSERT OR REPLACE INTO topics_d VALUES (?,?,?,?,?,?)",
                (now // D * D, now, len(rows), out["model"], out["usd"], json.dumps(data, ensure_ascii=False)))
    con.commit()
    out["n_tema"] = len(topics)
    log(store.PREFIX + f"teme dana: {len(topics)} tema iz {len(rows)} makro objava ({out['model']}"
                       + (f", {out['usd']:.4f} $" if out["usd"] else "") + (f"; {out['cap']}" if out["cap"] else "") + ")")
    return out


def load(con=None):
    """The newest topics row: {"ts", "od", "do", "topics": [...], "model", "n_objava", "n_racuna"} or None."""
    own = con is None
    con = con or store.ro()
    if con is None:
        return None
    try:
        r = store.q(con, "SELECT data, model FROM topics_d ORDER BY day DESC LIMIT 1")
    finally:
        if own:
            con.close()
    if not r:
        return None
    try:
        d = json.loads(r[0][0])
    except ValueError:
        return None
    d["model"] = r[0][1]
    return d

