"""Satno osvježavanje stranica tokena (run_tokenstranice.py sat, run_sched svaki sat, nice, bez teške brave).

refresh(con, ctx)  svemir (podaci.universe) -> za svaki token slug (stari ostaju) i snimka svih brojki s javnim odgodom
                   (podaci.sections, PUBLIC_DELAY_S) u pages; token koji je izašao iz svemira se zamrzne (active 0, out_ts,
                   razlog kao kod: rug / mc_low / mc_high / out), a vrati se čim opet uđe. Zamrzavanje samo kad se
                   midcap.db može čitati i ima članova (inače bi prazna baza nakon deploya zamrznula sve).
run(now)           refresh + mala serija AI mišljenja (misljenje.run_batch) + JEDAN red u logu:
                   "tokenstranice: sat: N stranica, mišljenja M, trošak $x (...)"
Bez mreže osim poziva OpenAI-ja za mišljenja; sve ostale baze se samo čitaju.
"""
import json
import sqlite3
import time

from tokenstranice import misljenje, podaci, store

PREFIX = "tokenstranice: "


def _public_slugs(ctx):
    """{mint: slug} of every coin public.db ever gave a page (ui/coins: slugs stay with the mint)."""
    return {m: s for m, s in podaci.q(ctx.con("public"), "SELECT mint, slug FROM coins") if s}


def refresh(con, ctx, log=print):
    """Returns {"pages", "new", "frozen", "back", "enough", "total"}."""
    now = ctx.now
    uni = podaci.universe(ctx)
    pub = _public_slugs(ctx)
    have = {r[0]: {"slug": r[1], "active": r[2]} for r in con.execute("SELECT mint, slug, active FROM pages")}
    taken = {s for (s,) in con.execute("SELECT slug FROM slugs")} | {h["slug"] for h in have.values()} | set(pub.values())
    out = {"pages": 0, "new": 0, "frozen": 0, "back": 0, "enough": 0}
    for m, u in sorted(uni.items(), key=lambda kv: -(kv[1].get("vol24") or 0)):
        old = have.get(m)
        slug = pub.get(m) or (old or {}).get("slug")
        if not slug:
            slug = store.make_slug(u.get("symbol"), m, taken)
        taken.add(slug)
        try:
            d = podaci.sections(m, ctx, podaci.PUBLIC_DELAY_S, base=u)
        except Exception as e:  # noqa: BLE001 - one token's bad data never stops the pass
            log(PREFIX + f"{(u.get('symbol') or m[:6])}: brojke nisu složene ({type(e).__name__})")
            continue
        cat = (d.get("m") or {}).get("cat")
        nw = d.get("now") or {}
        row = (slug, d["symbol"], (u.get("name") or d.get("name") or None), u.get("src"), now, int(d["enough"]),
               nw.get("mcap") or u.get("mcap"), nw.get("vol24") or u.get("vol24"), cat, json.dumps(d, ensure_ascii=False,
                                                                                                 separators=(",", ":")), now)
        try:
            if old is None:
                con.execute("INSERT INTO pages (slug, symbol, name, src, last_ts, enough, mcap, vol24, cat, data, updated, "
                            "mint, first_ts, active) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,1)", row + (m, now))
                out["new"] += 1
            else:
                if old["slug"] != slug:   # the coin list gave it its own slug: the old one keeps working
                    con.execute("INSERT OR IGNORE INTO slugs (slug, mint, ts) VALUES (?,?,?)", (old["slug"], m, now))
                con.execute("UPDATE pages SET slug=?, symbol=?, name=?, src=?, last_ts=?, enough=?, mcap=?, vol24=?, cat=?, "
                            "data=?, updated=?, active=1, out_ts=NULL, out_why=NULL WHERE mint=?", row + (m,))
                if not old["active"]:
                    out["back"] += 1
        except sqlite3.IntegrityError:   # the slug went to another page in the meantime: a new one, once
            slug = store.make_slug(u.get("symbol"), m, taken | {slug})
            taken.add(slug)
            con.execute("DELETE FROM pages WHERE mint=?", (m,))
            con.execute("INSERT INTO pages (slug, symbol, name, src, last_ts, enough, mcap, vol24, cat, data, updated, "
                        "mint, first_ts, active) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,1)", (slug,) + row[1:] + (m, now))
        con.execute("INSERT OR IGNORE INTO slugs (slug, mint, ts) VALUES (?,?,?)", (slug, m, now))
        out["pages"] += 1
        out["enough"] += int(d["enough"])
    members = podaci.one(ctx.con("midcap"), "SELECT COUNT(*) FROM tokens WHERE member=1")
    if members and members[0]:
        for m, h in have.items():
            if h["active"] and m not in uni:
                con.execute("UPDATE pages SET active=0, out_ts=?, out_why=? WHERE mint=?", (now, podaci.out_why(ctx, m), m))
                out["frozen"] += 1
    elif any(h["active"] and m not in uni for m, h in have.items()):
        log(PREFIX + "midcap.db se ne može čitati ili nema članova: ovaj put nijedna stranica nije zamrznuta")
    con.commit()
    out["total"] = con.execute("SELECT COUNT(*) FROM pages").fetchone()[0]
    store.reset_cache()
    return out


def line(r, ai, spent_day):
    s = (PREFIX + f"sat: {r['pages']} stranica, mišljenja {ai['n']}, trošak ${ai['usd']:.3f} (danas ${spent_day:.3f} od "
         f"${misljenje.DAY_USD:.2f}); dovoljno podataka {r['enough']}, novih {r['new']}, zamrznuto {r['frozen']}, "
         f"vraćeno {r['back']}, ukupno {r['total']}")
    if ai.get("fail"):
        s += f"; neuspjelih mišljenja {ai['fail']}"
    if ai.get("why"):
        s += f"; mišljenja stala: {ai['why']}"
    return s


def run(now=None, log=print, paths=None, path=None, ai=True):
    now = int(now or time.time())
    t0 = time.monotonic()
    ctx = podaci.Ctx(now, paths)
    con = store.connect(path)
    try:
        r = refresh(con, ctx, log)
        res = misljenje.run_batch(con, now, log) if ai else {"n": 0, "usd": 0.0, "fail": 0, "why": "preskočeno"}
        spent = store.spent(con, store.day_start(now))
        s = line(r, res, spent) + f"; {time.monotonic() - t0:.0f} s"
        log(s)
        store.kv_put(con, "last", {"ts": now, "line": s})
        con.commit()
        return {**r, "ai": res, "line": s}
    finally:
        ctx.close()
        con.close()
