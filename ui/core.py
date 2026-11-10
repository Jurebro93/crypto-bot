"""Pregled blocks for the two core features that had no block there yet (Nicholas 2.11.: the app is about token
suggestions, influencer analysis and wallet tracking; Natjecanje is a bonus): the best influencers with their last
call, and what the tracked wallets bought and sold lately. Small read-only queries on kol.db, a few rows each,
so Pregled's build time does not change in any noticeable way.
"""
import json
import time

from ui.html import esc, tlink


def _con():
    from kol import store
    return store.ro()


def _pct(x):
    if x is None:
        return "–"
    return f'<span class="{"pos" if x > 0 else "neg" if x < 0 else ""}">{x:+.0%}</span>'


def _ago(t):
    if not t:
        return "–"
    d = time.time() - t
    return f"prije {d / 60:.0f} min" if d < 3600 else f"prije {d / 3600:.0f} h" if d < 86400 else f"prije {d / 86400:.0f} d"


def top_kols(con, n=5, min_measured=5):
    """The n best-scored influencers that are not on trial and have enough measured calls, with their last call."""
    from kol.discover import excluded
    rows = con.execute("SELECT handle, name, followers, score, stats FROM kols WHERE score IS NOT NULL "
                       "ORDER BY score DESC LIMIT 60").fetchall()
    out = []
    for h, name, fol, score, stats in rows:
        try:
            s = json.loads(stats or "{}")
        except ValueError:
            s = {}
        if excluded(stats) or s.get("measured", 0) < min_measured:
            continue
        out.append({"handle": h, "name": name, "followers": fol, "score": score, "s": s})
        if len(out) >= n:
            break
    for k in out:
        last = con.execute("SELECT token, symbol, ts, max24 FROM calls WHERE handle = ? AND kind = 'call' "
                           "ORDER BY ts DESC LIMIT 1", (k["handle"],)).fetchone()
        k["last"] = last
    return out


def kol_block():
    from ui.kol import klink
    con = _con()
    if con is None:
        return "<div class=card>Još nema podataka o influencerima.</div>"
    try:
        kols = top_kols(con)
        syms = {}
        if kols:
            toks = [k["last"][0] for k in kols if k["last"]]
            if toks:
                q = ",".join("?" * len(toks))
                syms = dict(con.execute(f"SELECT token, symbol FROM tokens WHERE token IN ({q})", toks).fetchall())
    finally:
        con.close()
    if not kols:
        return "<div class=card>Još nema influencera s dovoljno izmjerenih poziva (treba barem 5).</div>"
    li = []
    for k in kols:
        s, last = k["s"], k["last"]
        lc = (f'zadnje zvao {tlink(last[0], syms.get(last[0]) or last[1])} <span class=mut>{_ago(last[2])}</span>'
              if last else "<span class=mut>nema poziva</span>")
        li.append(f'<li><span class=who>{klink(k["handle"])}</span><span class=st>'
                  f'<span>moć poziva <b>{k["score"]:.0f}</b></span>'
                  f'<span>pogodak <b>{(s.get("hit_rate") or 0):.0%}</b></span>'
                  f'<span>medijan max 24 h <b>{_pct(s.get("med_max24"))}</b></span>'
                  f'<span>{s.get("measured", 0)} poziva</span></span><span class=st>{lc}</span></li>')
    return "<ul class=core-list>" + "".join(li) + "</ul>"


def wallet_block(n=8, hours=48):
    from ui.kol import wallet_cell
    con = _con()
    if con is None:
        return "<div class=card>Još nema podataka o praćenim novčanicima.</div>"
    try:
        rows = con.execute("SELECT handle, token, symbol, kind, ts, text, max24 FROM calls WHERE kind IN ('buy', 'sell') "
                           "AND ts >= ? ORDER BY ts DESC LIMIT ?", (time.time() - hours * 3600, n)).fetchall()
        wmap = {}
        if rows:  # names -> addresses from kol_ids only (the full swap-feed scan of the KOL page is too slow here)
            try:
                from kol.collect import wallet_handles
                wmap = {h: w for w, h in wallet_handles(con).items()}
            except Exception:
                wmap = {}
        syms = {}
        if rows:
            toks = list({r[1] for r in rows})
            q = ",".join("?" * len(toks))
            syms = dict(con.execute(f"SELECT token, symbol FROM tokens WHERE token IN ({q})", toks).fetchall())
    finally:
        con.close()
    if not rows:
        return f"<div class=card>Praćeni novčanici u zadnjih {hours} h nisu ništa kupili ni prodali.</div>"
    from ui.kol import _sol
    li = []
    for h, tok, sym, kind, t, text, mx in rows:
        sol = _sol(text)
        act = '<b class=pos>kupio</b>' if kind == "buy" else '<b class=neg>prodao</b>'
        li.append(f'<li><span class=who>{wallet_cell(h, wmap)}</span><span class=st><span>{act} '
                  f'{tlink(tok, syms.get(tok) or sym)}</span>' + (f'<span><b>{sol:.2f}</b> SOL</span>' if sol else "")
                  + (f'<span>max nakon {_pct(mx)}</span>' if mx is not None else "")
                  + f'<span>{_ago(t)}</span></span></li>')
    return "<ul class=core-list>" + "".join(li) + "</ul>"


def blocks():
    """Influencer + wallet sections for Pregled, each with a link to its full page."""
    out = []
    for hid, title, lead, fn, links in [
        ("influenceri", "📣 Influenceri", "Najbolji KOL-ovi po izmjerenim pozivima (koliko često token poslije naraste) i "
         "što su zadnje zvali.", kol_block, [("/kol", "Svi KOL-ovi i ljestvica"), ("/izvori", "Telegram kanali")]),
        ("novcanici", "👛 Praćenje novčanika", "Zadnje kupnje i prodaje novčanika koje alat prati (KOL-ovi i "
         "pametni novac), najnovije prvo.", wallet_block, [("/wallets", "Svi novčanici"), ("/kol/analize#kupnje", "Sve kupnje")])]:
        try:
            body = fn()
        except Exception as e:  # a broken block must never take Pregled down
            body = f"<div class=card>Ovaj dio se trenutno ne može prikazati ({esc(type(e).__name__)}).</div>"
        more = " · ".join(f'<a href="{h}">{esc(t)} →</a>' for h, t in links)
        out.append(f"<h2 id={hid} data-sec=\"{esc(title[2:])}\">{esc(title)}</h2><p class=lead>{esc(lead)}</p>"
                   f"{body}<p class=core-more>{more}</p>")
    return "".join(out)
