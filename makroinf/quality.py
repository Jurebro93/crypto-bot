"""The classification quality check (the critic: "300 stratificiranih ručnih provjera, preciznost / odziv po
kategoriji, ne samo 85 % ukupno") and the gate of the expansion to 300 accounts.

export     300 classified posts, stratified by account category x label (macro up / down / turn / range /
           conditional / not macro), proportional with a floor per stratum, deterministic (a hash of the id, no seed);
           written to output/makroinf_provjera.md for the owner (each with a link and our labels).
critic     ~100 of them (an even spread over the categories) re-labelled by OPENAI_MODEL_DEEP (critic/openai_api) in
           batches, within quality_openai_usd (1 $): its own is_macro / asset / direction.
metrics    per account category: is_macro precision (ours macro -> the critic agrees) and recall (the critic macro ->
           ours macro), direction agreement on the posts both call macro; with n.
passed     every main category with >= MIN_N reviewed posts has precision, recall and direction >= 85 %, and at least
           MIN_CATS categories could be checked. The expansion refuses otherwise unless the owner forces it.
"""
import hashlib
import json
import os
import time

from makroinf import classify, racuni, store

N_EXPORT, N_CRITIC = 300, 100
FLOOR, MIN_N, MIN_CATS, PASS = 5, 10, 3, 0.85
OUT_MD = os.path.join(store.ROOT, "output", "makroinf_provjera.md")

CRITIC_INSTRUCTIONS = """You audit labels of crypto posts. For each post give YOUR OWN labels, independent of the
proposed ones: is_macro (does the author state a view on where a crypto MARKET goes: BTC, ETH, SOL, altcoins in
general, memecoins in general or the whole market; news without a view, ads, single small-coin shills and questions
are not macro), asset (BTC | ETH | SOL | alts | memes | total | none) and direction (up | down | bottom_in | top_in |
range | none) of the main call. Then say whether the proposed is_macro and direction are correct."""
CRITIC_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["items"], "properties": {"items": {
    "type": "array", "items": {"type": "object", "additionalProperties": False,
                               "required": ["id", "is_macro", "asset", "direction", "proposed_ok"],
                               "properties": {"id": {"type": "string"}, "is_macro": {"type": "boolean"},
                                              "asset": {"type": "string", "enum": list(classify.ASSETS) + ["none"]},
                                              "direction": {"type": "string",
                                                            "enum": list(classify.DIRECTIONS) + ["none"]},
                                              "proposed_ok": {"type": "boolean"}}}}}}


def _h(x):
    return int(hashlib.sha256(str(x).encode()).hexdigest()[:12], 16)


def label(macro, calls):
    if not macro or not calls:
        return "ne_makro"
    c = calls[0]
    if c["conditional"]:
        return "uvjetno"
    return {"up": "gore", "down": "dolje", "bottom_in": "preokret", "top_in": "preokret", "range": "raspon"}.get(
        c["direction"], "ostalo")


def population(con):
    """[{id, handle, category, macro, calls, stratum, text, url, ts}] of the LLM-classified posts."""
    cats = {h: c for h, c in store.q(con, "SELECT handle, category FROM accounts")}
    calls = {}
    for i, a, d, cond in store.q(con, "SELECT id, asset, direction, conditional FROM calls"):
        calls.setdefault(i, []).append({"asset": a, "direction": d, "conditional": cond})
    out = []
    for i, h, ts, text, url, macro in store.q(con, "SELECT id, handle, ts, text, url, macro FROM tweets WHERE cls_ts IS "
                                                   "NOT NULL AND cls_v NOT IN ('predfiltar', 'propusteno')"):
        cat = cats.get(h) or "ta"
        lab = label(macro, calls.get(i))
        out.append({"id": i, "handle": h, "category": cat, "macro": bool(macro), "calls": calls.get(i) or [],
                    "stratum": f"{cat}/{lab}", "text": text or "", "url": url, "ts": ts})
    return out


def sample(pop, n=N_EXPORT, floor=FLOOR):
    """A stratified, deterministic sample: every stratum min(floor, its size), the rest proportional to size."""
    by = {}
    for x in sorted(pop, key=lambda x: _h(x["id"])):
        by.setdefault(x["stratum"], []).append(x)
    if not by:
        return []
    take = {k: min(floor, len(v)) for k, v in by.items()}
    rest = max(0, n - sum(take.values()))
    total = sum(len(v) - take[k] for k, v in by.items())
    if total > 0:
        for k, v in by.items():
            take[k] += min(len(v) - take[k], int(round(rest * (len(v) - take[k]) / total)))
    out = []
    for k, v in sorted(by.items()):
        out += v[:take[k]]
    return out[:n] if len(out) > n else out


def critic_subset(smp, n=N_CRITIC):
    """An even spread over the account categories (round-robin), n posts."""
    by = {}
    for x in smp:
        by.setdefault(x["category"], []).append(x)
    out = []
    while by and len(out) < n:
        for k in sorted(by):
            out.append(by[k].pop(0))
            if not by[k]:
                del by[k]
            if len(out) >= n:
                break
    return out


def markdown(smp, res=None, now=None):
    now = int(now or time.time())
    L = ["# Makro influenceri — provjera klasifikacije", "",
         f"{time.strftime('%d.%m.%Y. %H:%M', time.gmtime(now))} UTC. {len(smp)} stratificiranih uzoraka (kategorija "
         f"računa × oznaka). Model: {classify.PROMPT_VERSION}. Za svaki: je li oznaka točna? (prepravi ručno ako nije)", ""]
    if res:
        L += ["## Kritičar (OPENAI_MODEL_DEEP) na ~100 uzoraka", "", f"Prošlo: **{'DA' if res.get('passed') else 'NE'}** — "
              f"{res.get('why')}", "", "| kategorija | n | preciznost makro | odziv makro | smjer | prolazi |",
              "|---|---|---|---|---|---|"]
        for cat, m in (res.get("by_cat") or {}).items():
            L.append(f"| {racuni.CATS.get(cat, cat)} | {m['n']} | {m.get('precision')} | {m.get('recall')} | "
                     f"{m.get('direction')} | {m.get('ok')} |")
        L.append("")
    L += ["## Uzorci", ""]
    for x in smp:
        lab = ", ".join(f"{c['asset']} {c['direction']}{' (uvjetno)' if c['conditional'] else ''}" for c in x["calls"]) \
            or "nije makro izjava"
        txt = " ".join((x["text"] or "").split())[:280]
        L += [f"- **{x['stratum']}** @{x['handle']} {time.strftime('%Y-%m-%d', time.gmtime(x['ts']))} "
              f"[objava]({x['url']}) — oznaka: {lab}", f"  > {txt}", "  - [ ] točno  [ ] netočno: ____", ""]
    return "\n".join(L) + "\n"


def metrics(rows):
    """rows: [{category, ours_macro, ours_dir, critic_macro, critic_dir}] -> {cat: {n, precision, recall, direction,
    ok}}, passed, why."""
    by = {}
    for r in rows:
        by.setdefault(r["category"], []).append(r)
    out, checked, failed = {}, 0, []
    for cat, xs in sorted(by.items()):
        om = [x for x in xs if x["ours_macro"]]
        cm = [x for x in xs if x["critic_macro"]]
        both = [x for x in xs if x["ours_macro"] and x["critic_macro"]]
        prec = (sum(1 for x in om if x["critic_macro"]) / len(om)) if om else None
        rec = (sum(1 for x in cm if x["ours_macro"]) / len(cm)) if cm else None
        dr = (sum(1 for x in both if x["ours_dir"] == x["critic_dir"]) / len(both)) if both else None
        m = {"n": len(xs), "n_makro_nasi": len(om), "n_makro_kriticar": len(cm),
             "precision": None if prec is None else round(prec, 3), "recall": None if rec is None else round(rec, 3),
             "direction": None if dr is None else round(dr, 3)}
        if len(xs) >= MIN_N:
            checked += 1
            ok = all(v is None or v >= PASS for v in (prec, rec, dr)) and prec is not None
            m["ok"] = ok
            if not ok:
                failed.append(cat)
        else:
            m["ok"] = "premalo uzoraka"
        out[cat] = m
    passed = checked >= MIN_CATS and not failed
    why = (f"{checked} kategorija provjereno, sve ≥ {PASS:.0%}" if passed else
           f"pada: {', '.join(failed)}" if failed else f"premalo provjerenih kategorija ({checked} < {MIN_CATS})")
    return out, passed, why


def run(con, c, now=None, log=print, call=None, write=True):
    """Export + the critic pass + the metrics; stores kv provjera {ts, passed, why, by_cat, usd, n}."""
    from critic import openai_api
    now = int(now or time.time())
    smp = sample(population(con))
    if len(smp) < 30:
        res = {"ts": now, "passed": False, "why": f"premalo klasificiranih objava za provjeru ({len(smp)})", "n": len(smp)}
        store.kv(con, "provjera", res)
        con.commit()
        return res
    store.kv(con, "provjera_dan", store.day(now))
    sub = critic_subset(smp)
    model = openai_api.MODEL_DEEP
    if call is None and not openai_api.has_key():
        res = {"ts": now, "passed": False, "why": "nema OPENAI_API_KEY za kritičara", "n": len(smp)}
        if write:
            _write(markdown(smp, res, now))
        store.kv(con, "provjera", res)
        con.commit()
        return res
    call = call or (lambda *a, **k: openai_api.call_json(*a, **k))
    usd, rows = 0.0, []
    for k in range(0, len(sub), 20):
        part = sub[k:k + 20]
        items = [{"id": x["id"], "text": " ".join(x["text"].split())[:500],
                  "proposed": {"is_macro": x["macro"], "calls": x["calls"]}} for x in part]
        text = "Posts:\n" + "\n".join(json.dumps(i, ensure_ascii=False) for i in items)
        max_out = 120 * len(part) + 1500
        left = store.left(con, "openai", "provjera", now, c)
        est = openai_api.max_cost(model, len(CRITIC_INSTRUCTIONS) + len(text), max_out)
        if est > left:
            log(store.PREFIX + f"provjera: strop kritičara ({c['quality_openai_usd']} $) dosegnut, stajem")
            break
        try:
            r = call(model, CRITIC_INSTRUCTIONS, text, CRITIC_SCHEMA, "provjera_oznaka", max_output_tokens=max_out,
                     effort="low")
        except openai_api.ApiError as e:
            u = openai_api.cost(e.model or model, e.usage) if e.usage else 0.0
            if u:
                store.book(con, "openai_deep", u, "provjera", "provjera (neupotrebljivo)", now)
            log(store.PREFIX + f"provjera: {str(e)[:160]}")
            break
        u = float(r.get("cost_usd") or 0.0)
        usd += u
        store.book(con, "openai_deep", u, "provjera", "provjera oznaka", now)
        got = {str(x.get("id")): x for x in (r.get("data") or {}).get("items") or [] if isinstance(x, dict)}
        for x in part:
            g = got.get(str(x["id"]))
            if not g:
                continue
            od = x["calls"][0]["direction"] if x["calls"] else "none"
            rows.append({"category": x["category"], "ours_macro": x["macro"], "ours_dir": od,
                         "critic_macro": bool(g.get("is_macro")), "critic_dir": g.get("direction") or "none"})
            con.execute("INSERT OR REPLACE INTO quality VALUES (?,?,?,?,?,?,?,?)",
                        (x["id"], x["stratum"], x["category"], json.dumps({"macro": x["macro"], "calls": x["calls"]}),
                         json.dumps(g, ensure_ascii=False), int(bool(g.get("is_macro")) == x["macro"]),
                         int((g.get("direction") or "none") == od), now))
        con.commit()
    by_cat, passed, why = metrics(rows)
    prev = store.kv_json(con, "provjera", {}) or {}
    res = {"ts": now, "passed": passed, "why": why, "by_cat": by_cat, "usd": round(usd, 4), "n": len(smp),
           "n_kriticar": len(rows), "model": model, "forced": bool(prev.get("forced"))}
    store.kv(con, "provjera", res)
    con.commit()
    if write:
        _write(markdown(smp, res, now))
    log(store.PREFIX + f"provjera klasifikacije: {'PROŠLA' if passed else 'NIJE PROŠLA'} — {why}; kritičar "
                       f"{len(rows)} objava, {usd:.2f} $; uzorci u output/makroinf_provjera.md")
    return res


def _write(text):
    os.makedirs(os.path.dirname(OUT_MD), exist_ok=True)
    with open(OUT_MD, "w", encoding="utf-8") as f:
        f.write(text)


def force(con, who, now=None):
    """The owner forces the expansion although the check did not pass (recorded)."""
    q = store.kv_json(con, "provjera", {}) or {}
    q.update(forced=True, forced_by=who, forced_ts=int(now or time.time()))
    store.kv(con, "provjera", q)
    con.commit()
    return q


def gate(con):
    """None when the expansion may run, else why not."""
    q = store.kv_json(con, "provjera", {}) or {}
    if q.get("passed") or q.get("forced"):
        return None
    return "provjera klasifikacije nije prošla" + (f" ({q.get('why')})" if q.get("why") else " (još nije odrađena)")
