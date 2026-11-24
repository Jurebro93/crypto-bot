"""Classification of the stored posts: is it a market call, on what, which way, when, under what condition
(OpenAI Responses API, Structured Outputs: strict JSON; critic/openai_api.py is the client).

Model: gpt-5-mini (the cheapest model of critic/openai_api.PRICES that reasons well enough: 0.25 / 2.00 $ per 1M
tokens), reasoning effort "minimal", ~20 posts a request. A post the local keyword prefilter (fetch.kw_pass) rejects is
not sent ("ne makro", cls_v predfiltar). Every answer stores the model that answered, PROMPT_VERSION and the time
(the audit trail); a post the model skipped is asked again (cls_max_tries), then marked missed.

Budget: before each request the most it can cost (openai_api.max_cost of the input and max output) must fit what is
left of the phase's cap (store.left "openai": pilot 4 $, then the daily cap; each wave of the expansion its own cap). At the cap
the pass stops cleanly.
"""
import json
import time

from makroinf import store

PROMPT_VERSION = "klasifikacija-v1 (15.11.2026.)"
ASSETS = ("BTC", "ETH", "SOL", "alts", "memes", "total")
DIRECTIONS = ("up", "down", "bottom_in", "top_in", "range")
CONFIDENCE = ("high", "medium", "low", "joke")

INSTRUCTIONS = """You label crypto posts from X. For EACH post decide whether it states a view on where a crypto MARKET
goes (a "macro call"). Not a call: news without a view, ads, giveaways, questions, charts without words, single-token
shills of a small coin (those are not macro; but "memecoins will run" IS macro, asset memes), jokes without a view.

For every macro call output one object per asset it covers:
- asset: BTC | ETH | SOL | alts (altcoins in general, altseason) | memes (memecoins in general) | total (the whole
  crypto market, "crypto")
- direction: up | down | bottom_in ("the bottom is in", "lows are in") | top_in ("the top is in", "cycle top") |
  range (sideways / chop between levels)
- horizon_days: the horizon the author STATES, in days (a week = 7, "this month" = 30, "by year end" = days left to
  Dec 31 from the post date, "this cycle" = 365); null when no time is stated. Never invent one.
- conditional: true when the call depends on a condition ("if BTC loses 60k we go to 50k");
  condition: the condition in <= 12 words, else null; trigger_level: the price level of the condition (a number in
  USD, 60k = 60000), else null; trigger_dir: below | above | none
- target: the price level the author expects (number in USD), else null; invalidation: the level that would prove
  him wrong / his stop, else null
- confidence: high | medium | low (hedged, "maybe", "could") | joke (sarcasm, meme, irony)
- probability: an explicit probability the author gives (0..1, "80% chance" = 0.8), else null
- promo: true when the post promotes a paid product, exchange, referral, course or sponsor
- unclear: true when the view is too vague, sarcastic or contradictory to measure ("we're so back", "wagmi")
- withdraws: true when the author explicitly abandons an earlier view on this asset ("I was wrong, no longer bullish")
List the ids of posts that contain NO macro call in not_macro. Use the post date to resolve relative times. Quoted text
is context only: label what the AUTHOR says. Every id must appear in calls or in not_macro."""

_NUM = {"type": ["number", "null"]}
CALL_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["id", "asset", "direction", "horizon_days", "conditional", "condition", "trigger_level", "trigger_dir",
                 "target", "invalidation", "confidence", "probability", "promo", "unclear", "withdraws"],
    "properties": {
        "id": {"type": "string"}, "asset": {"type": "string", "enum": list(ASSETS)},
        "direction": {"type": "string", "enum": list(DIRECTIONS)}, "horizon_days": _NUM,
        "conditional": {"type": "boolean"}, "condition": {"type": ["string", "null"]}, "trigger_level": _NUM,
        "trigger_dir": {"type": "string", "enum": ["below", "above", "none"]}, "target": _NUM, "invalidation": _NUM,
        "confidence": {"type": "string", "enum": list(CONFIDENCE)}, "probability": _NUM,
        "promo": {"type": "boolean"}, "unclear": {"type": "boolean"}, "withdraws": {"type": "boolean"}}}
SCHEMA = {"type": "object", "additionalProperties": False, "required": ["calls", "not_macro"],
          "properties": {"calls": {"type": "array", "items": CALL_SCHEMA},
                         "not_macro": {"type": "array", "items": {"type": "string"}}}}


def prefilter(con):
    """Posts the keyword prefilter rejected are 'ne makro' without a request. Returns how many were marked."""
    now = int(time.time())
    n = con.execute("UPDATE tweets SET cls_ts = ?, cls_v = 'predfiltar', macro = 0 WHERE cls_ts IS NULL AND kw = 0",
                    (now,)).rowcount
    con.commit()
    return n


def pending(con, limit=2000, expansion=None, which=None, wave=None):
    """[(id, handle, ts, text, quoted_text)] still to classify, interleaved over the accounts (newest first within
    each), so a cap leaves every account partly covered. expansion True / False: only / no posts of expansion accounts.
    which "dnevno": only the daily fetch's posts; "povijest": only the backfill's (15.11. navečer: the history of the
    owner-ordered expansion goes under its own cap, the day's new posts under the daily one). wave 2 / 1: only / no
    posts of the second wave's accounts (16.11.: their history goes under the second wave's own cap)."""
    cond = ""
    if expansion is True:
        cond = " AND a.source LIKE 'prosirenje%'"
    elif expansion is False:
        cond = " AND COALESCE(a.source, '') NOT LIKE 'prosirenje%'"
    if wave == 2:
        cond += " AND a.source = 'prosirenje2'"
    elif wave == 1:
        cond += " AND COALESCE(a.source, '') <> 'prosirenje2'"
    if which == "dnevno":
        cond += " AND t.src = 'dnevno'"
    elif which == "povijest":
        cond += " AND COALESCE(t.src, '') <> 'dnevno'"
    rows = store.q(con, f"""SELECT t.id, t.handle, t.ts, t.text, t.quoted_text FROM tweets t JOIN accounts a ON
        a.handle = t.handle WHERE t.cls_ts IS NULL AND t.kw = 1 AND a.status IN ('aktivan', 'neaktivan'){cond}
        ORDER BY t.cls_tries, t.ts DESC LIMIT ?""", (int(limit) * 4,))
    by = {}
    for r in rows:
        by.setdefault(r[1], []).append(r)
    out = []
    while by and len(out) < limit:
        for h in list(by):
            out.append(by[h].pop(0))
            if not by[h]:
                del by[h]
            if len(out) >= limit:
                break
    return out


def user_text(batch):
    items = [{"id": str(i), "author": f"@{h}", "date": time.strftime("%Y-%m-%d", time.gmtime(ts)),
              "text": (tx or "")[:600], **({"quoted": q[:300]} if q else {})} for i, h, ts, tx, q in batch]
    return "Posts (JSON lines):\n" + "\n".join(json.dumps(x, ensure_ascii=False) for x in items)


def _num(x):
    try:
        v = float(x)
        return v if v == v and abs(v) < 1e12 else None
    except (TypeError, ValueError):
        return None


def clean_call(x, ids):
    """A validated call dict (enums, numbers) or None."""
    if not isinstance(x, dict) or str(x.get("id")) not in ids:
        return None
    if x.get("asset") not in ASSETS or x.get("direction") not in DIRECTIONS:
        return None
    hz = _num(x.get("horizon_days"))
    pr = _num(x.get("probability"))
    if pr is not None and pr > 1 and pr <= 100:
        pr = pr / 100
    return {"id": str(x["id"]), "asset": x["asset"], "direction": x["direction"],
            "horizon_days": hz if hz is not None and 0 < hz <= 3650 else None,
            "conditional": bool(x.get("conditional")), "condition": (str(x.get("condition") or "")[:120] or None),
            "trigger_level": _num(x.get("trigger_level")),
            "trigger_dir": x.get("trigger_dir") if x.get("trigger_dir") in ("below", "above") else None,
            "target": _num(x.get("target")), "invalidation": _num(x.get("invalidation")),
            "confidence": x.get("confidence") if x.get("confidence") in CONFIDENCE else "medium",
            "probability": pr if pr is not None and 0 <= pr <= 1 else None,
            "promo": bool(x.get("promo")), "unclear": bool(x.get("unclear")), "withdraws": bool(x.get("withdraws"))}


def apply(con, batch, data, model, now, max_tries=2):
    """Store one answer: calls rows, tweets.macro / cls_*; a post missing from the answer is asked again later.
    Returns (macro posts, not macro, missing)."""
    ids = {str(r[0]) for r in batch}
    meta = {str(r[0]): r for r in batch}
    calls = [c for c in (clean_call(x, ids) for x in (data or {}).get("calls") or []) if c]
    macro_ids = {c["id"] for c in calls}
    not_macro = {str(x) for x in (data or {}).get("not_macro") or []} & ids
    for tid in macro_ids:
        con.execute("DELETE FROM calls WHERE id = ?", (tid,))
    for c in calls:
        _i, h, ts, _t, _q = meta[c["id"]]
        av = store.q(con, "SELECT fetched_ts FROM tweets WHERE id = ?", (c["id"],))
        con.execute("INSERT OR REPLACE INTO calls VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (c["id"], c["asset"], h, ts, av[0][0] if av else now, c["direction"], c["horizon_days"],
                     int(c["conditional"]), c["condition"], c["trigger_level"], c["trigger_dir"], c["target"],
                     c["invalidation"], c["confidence"], c["probability"], int(c["promo"]), int(c["unclear"]),
                     int(c["withdraws"]), model, PROMPT_VERSION, int(now)))
    for tid in ids:
        if tid in macro_ids:
            con.execute("UPDATE tweets SET cls_ts = ?, cls_v = ?, cls_model = ?, macro = 1 WHERE id = ?",
                        (int(now), PROMPT_VERSION, model, tid))
        elif tid in not_macro:
            con.execute("UPDATE tweets SET cls_ts = ?, cls_v = ?, cls_model = ?, macro = 0 WHERE id = ?",
                        (int(now), PROMPT_VERSION, model, tid))
        else:
            con.execute("UPDATE tweets SET cls_tries = cls_tries + 1 WHERE id = ?", (tid,))
            con.execute("UPDATE tweets SET cls_ts = ?, cls_v = 'propusteno', macro = 0 WHERE id = ? AND cls_tries >= ?",
                        (int(now), tid, int(max_tries)))
    return len(macro_ids), len(not_macro - macro_ids), len(ids - macro_ids - not_macro)


def run(con, c, now=None, log=print, deadline=None, call=None, ph=None, expansion=False, max_batches=None,
        which=None, wave=None):
    """Classify pending posts within the cap and the deadline, cls_workers requests at a time (the pilot's ~1000
    requests in about an hour instead of four). A group is sent only when the most ALL its requests can cost fits what
    is left of the cap. call(model, instructions, text, schema, name, max_out, effort) -> {"data", "usage", "model",
    "cost_usd"} (tests pass a fake). Returns a summary dict."""
    from concurrent.futures import ThreadPoolExecutor
    from critic import openai_api
    now = int(now or time.time())
    out = {"batches": 0, "macro": 0, "not_macro": 0, "missing": 0, "usd": 0.0, "cap": None}
    out["prefilter"] = prefilter(con)
    if call is None and not openai_api.has_key():
        out["cap"] = "nema OPENAI_API_KEY"
        return out
    call = call or (lambda *a, **k: openai_api.call_json(*a, **k))
    model = c["cls_model"]
    size = int(c["cls_batch"])
    rows = pending(con, size * (max_batches or 200), expansion=expansion, which=which, wave=wave)
    batches = [rows[k:k + size] for k in range(0, len(rows), size)][:max_batches or None]
    workers = max(1, int(c.get("cls_workers") or 1))
    p = ph or ("prosirenje" if expansion else store.phase(con, "openai"))

    def one(job):
        batch, text, max_out = job
        try:
            return batch, call(model, INSTRUCTIONS, text, SCHEMA, "makro_izjave", max_output_tokens=max_out,
                               effort=c.get("cls_effort") or "minimal"), None
        except openai_api.ApiError as e:
            return batch, None, e
    i, stop = 0, False
    with ThreadPoolExecutor(max_workers=workers) as pool:
        while i < len(batches) and not stop:
            if deadline and time.time() > deadline:
                break
            left = store.left(con, "openai", p, now, c)
            group, reserve = [], 0.0
            while i < len(batches) and len(group) < workers:
                text = user_text(batches[i])
                max_out = int(c["cls_out_per_post"]) * len(batches[i]) + 600
                est = openai_api.max_cost(model, len(INSTRUCTIONS) + len(text), max_out)
                if reserve + est > left:
                    break
                group.append((batches[i], text, max_out))
                reserve += est
                i += 1
            if not group:
                out["cap"] = f"strop OpenAI ({p}) dosegnut: ostalo {left:.4f} $, zahtjev do {est:.4f} $"
                break
            for batch, r, err in pool.map(one, group):
                if err is not None:
                    usd = openai_api.cost(err.model or model, err.usage) if err.usage else 0.0
                    if usd:
                        store.book(con, "openai", usd, p, "klasifikacija (neupotrebljivo)", now)
                        out["usd"] += usd
                    for row in batch:
                        con.execute("UPDATE tweets SET cls_tries = cls_tries + 1 WHERE id = ?", (row[0],))
                    log(store.PREFIX + f"klasifikacija: {str(err)[:160]}")
                    if err.status in (401, 403, 429) or err.status is None:
                        stop = True
                    continue
                usd = float(r.get("cost_usd") or 0.0)
                store.book(con, "openai", usd, p, "klasifikacija", now)
                m, nm, miss = apply(con, batch, r.get("data"), r.get("model") or model, now, int(c["cls_max_tries"]))
                out["batches"] += 1
                out["macro"] += m
                out["not_macro"] += nm
                out["missing"] += miss
                out["usd"] += usd
            con.commit()
    out["usd"] = round(out["usd"], 4)
    return out
