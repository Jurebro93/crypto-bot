"""The measurement of wallet following per entry on the pages (19.11., vlasnik: "for every entry one can simply measure
whether it was profitable or not in percent, not in demo money"; league/mjera.py):

  autopilot_html(owner)   the Autopilot page's section while real money is paused: "Praćenje novčanika: mjerenje po
                          ulazu (bez pravog novca)": the table per source and MC bucket in percent with the verdict, the
                          capacity line, the latest rows; the owner's three-way setting (auto / demo / mjera)
  admin_html()            the admin dashboard's "Mjerenje po ulazu": the full table, the proof per source, misses by
                          reason, delays, parity with the demos, per group / wallet its own rows and mean

Read-only (league.db opened read-only; nothing here writes); no demo dollars anywhere.
"""
import time
from urllib.parse import quote

from ui import novpodaci as P
from ui import redak as rd

TITLE = "Praćenje novčanika: mjerenje po ulazu (bez pravog novca)"
BUCKET_HR = {"15-200M": "15–200 M $", "2-15M": "2–15 M $", "<2M": "ispod 2 M $", ">200M": "iznad 200 M $",
             "?": "MC nepoznat", "svi": "svi"}
EXIT_HR = {"prodali su": "prodali su", "stop": "stop −25 %", "vrijeme": "24 h", "bez cijene": "bez cijene",
           "nije kopirljivo": "nije kopirljivo"}
MODE_HR = {"auto": "auto: demo do potvrde da se mjerenje slaže, zatim samo mjerenje",
           "demo": "demo: demo tradeovi teku usporedno", "mjera": "mjera: samo mjerenje, bez novih demo tradeova"}


def _con():
    return P.ro(P.league_db())


def _pct(x, dec=1):
    return rd.DASH if x is None else rd.pct(x, dec, sign=True, frac=True)


def _ci(st):
    if st.get("lo") is None or st.get("hi") is None:
        return rd.DASH
    return f"[{rd.num(st['lo'] * 100, 1, sign=True)}; {rd.num(st['hi'] * 100, 1, sign=True)}] %"


def _tone(x):
    return rd.tone(x) or ""


def _verdict_cell(st):
    """The short word in the cell, the whole verdict in its title (so the table fits at 1280)."""
    from league import mjera
    v = mjera.verdict(st)
    cls = "pos" if v == "u plusu" else "neg" if v == "u minusu" else "mut"
    short = ("premalo" if v.startswith("premalo") else "nije dokazano" if v.startswith("još nije") else v)
    return f'<span class={cls} title="{rd.h(v)}">{rd.h(short)}</span>'


def summary_table(s, full=False):
    """The table per source (and MC bucket) from league/mjera.summary."""
    from league import mjera
    head = ["Izvor", "MC pri ulazu", "Signala", "Mjereno", "Promašeno", "Otvoreno", "Neto 0,1 SOL", "95 % (token-dani)",
            "Neto 0,5 SOL", "Dobitnih", "Kašnjenje", "Presuda"]   # the verdict's whole sentence is in its title
    rows = []
    for src in mjera.SOURCES:
        keys = ["svi"] + [b for b in mjera.BUCKETS if (src, b) in s["by"]]
        for b in keys:
            st = s["by"].get((src, b))
            if not st or not st["signals"]:
                continue
            if not full and b != "svi" and not (src == "prije_pumpe" and b in ("15-200M", "2-15M")):
                continue
            rows.append(
                f'<tr><td>{rd.h(mjera.LABEL[src]) if b == "svi" else f"<span class=mut>{rd.h(mjera.LABEL[src])}</span>"}</td><td>{rd.h(BUCKET_HR.get(b, b))}</td>'
                f'<td>{rd.num(st["signals"])}</td><td>{rd.num(st["measured"])}</td>'
                f'<td>{rd.h(rd.pct(st["miss_share"], 0, sign=False, frac=True) if st["miss_share"] is not None else rd.DASH)}</td>'
                f'<td>{rd.num(st["open"])}</td><td class="{_tone(st["mean01"])}">{rd.h(_pct(st["mean01"]))}</td>'
                f'<td>{rd.h(_ci(st))}</td><td class="{_tone(st["mean05"])}">{rd.h(_pct(st["mean05"]))}</td>'
                f'<td>{rd.h(rd.pct(st["win_share"], 0, sign=False, frac=True) if st["win_share"] is not None else rd.DASH)}</td>'
                f'<td>{rd.h(rd.num(st["delay_med"]) + " s" if st["delay_med"] is not None else rd.DASH)}</td>'
                f'<td>{_verdict_cell(st)}</td></tr>')
    if not rows:
        return ""
    th = "".join(f"<th scope=col>{rd.h(h)}</th>" for h in head)
    return (f'<div class=rt-wrap><table class="rt nm-t"><thead><tr>{th}</tr></thead><tbody>{"".join(rows)}</tbody>'
            f'</table></div><p class=apx-mut style="font-size:12.5px;margin-top:4px">Presuda: „premalo” = manje od '
            f'{mjera.MIN_TOKEN_DAYS} izmjerenih token-dana; „nije dokazano” = interval dira nulu; „u plusu” / „u minusu” '
            'kad je cijeli interval iznad / ispod nule.</p>')


def capacity_line(s):
    from league import mjera
    bits = []
    for n in mjera.CAPACITY:
        k, m, sol = s["capacity"][n]
        bits.append(f"najviše {n} otvorenih: uzeto {rd.num(k)}, srednje {_pct(m)}, ukupno "
                    f"{rd.sol(sol, 2, sign=True)} uz 0,1 SOL po ulazu" if k else f"najviše {n} otvorenih: još ništa")
    return "Kapacitet (signali redom kad je mjesto slobodno): " + "; ".join(bits) + "."


def latest_rows(con, n=15):
    keys = ("source", "gid", "wallet", "token", "symbol", "status", "mc_bucket", "entry_ts", "ret_net_01", "exit_reason",
            "guard", "delay_s", "seen_ts")
    rows = [dict(zip(keys, r)) for r in P.q(con, f"SELECT {', '.join(keys)} FROM signal_mjera ORDER BY seen_ts DESC "
                                                 "LIMIT ?", (int(n),))]
    return rows


def _why(r):
    from league import mjera
    w = str(r.get("wallet") or "")
    g = str(r.get("gid") or "")
    who = (f"novčanik {w[:4]}…{w[-4:]}" if r["source"] == "kopija" else
           f"{'bundle' if r['source'] == 'bundle' else 'grupa'} {(g[2:] if g[:2] in ('o:', 'p:') else g)[:6]}")
    d = f", vidjeli {rd.num(r['delay_s'])} s nakon njihove kupnje" if r.get("delay_s") is not None else ""
    return f"{mjera.LABEL.get(r['source'], r['source'])}: {who}{d}"


def rows_table(rows):
    if not rows:
        return ""
    body = []
    for r in rows:
        tok = r.get("token") or ""
        name = rd.h(r.get("symbol") or (tok[:6] if tok else rd.DASH))
        tag = BUCKET_HR.get(r.get("mc_bucket") or "?", r.get("mc_bucket"))
        if r["status"] == "open":
            res = '<span class=mut>otvoreno</span>' if r.get("entry_ts") else '<span class=mut>čeka cijenu</span>'
        elif r["status"] == "miss":
            res = f'<span class=warn>promašaj: {rd.h((r.get("guard") or r.get("exit_reason") or "")[:60])}</span>'
        else:
            res = (f'<span class="{_tone(r["ret_net_01"])}">{rd.h(_pct(r["ret_net_01"]))}</span>'
                   f' <span class=mut>({rd.h(EXIT_HR.get(r.get("exit_reason"), r.get("exit_reason") or ""))})</span>')
        ent = time.strftime("%d.%m. %H:%M", time.localtime(r["entry_ts"])) if r.get("entry_ts") else rd.DASH
        body.append(f'<tr><td><a href="/token/{quote(tok)}" translate=no>{name}</a><br><span class=mut '
                    f'style="font-weight:400;font-size:12.5px">{rd.h(tag)}</span></td><td class=mut>{rd.h(ent)}</td>'
                    f'<td>{res}</td><td class="nk-why wrap">{rd.h(_why(r))}</td></tr>')
    return ('<div class=rt-wrap><table class="rt nk-dt"><thead><tr><th scope=col>Token</th><th scope=col>Ulaz</th>'
            '<th scope=col>Neto 0,1 SOL</th><th scope=col>Zašto</th></tr></thead><tbody>' + "".join(body)
            + '</tbody></table></div>')


CSS = ("<style>.nm-t{min-width:0}.nm-t th{white-space:normal;vertical-align:bottom;line-height:1.25}"
       ".nm-t th,.nm-t td{padding:8px 5px}.nm-t td:last-child{white-space:normal;text-align:left;min-width:70px}"
       ".nm-t td:first-child,.nm-t th:first-child,.nm-t td:nth-child(2){text-align:left}"
       "table.nm-t.cards td:first-child:empty{display:none}"
       ".nk-dt{min-width:0}.nk-dt td.nk-why{white-space:normal;text-align:left;min-width:220px;line-height:1.4}"
       ".nk-dt td:nth-child(2),.nk-dt th:nth-child(2),.nk-dt th:nth-child(4){text-align:left}"
       "table.nk-dt.cards td.nk-why{min-width:0;max-width:none;grid-column:1/-1}"
       ".nm-f{display:flex;flex-wrap:wrap;gap:6px;align-items:center;margin:10px 0 0;font-size:13.5px}"
       ".nm-f button{font:inherit;font-size:13px;border:1px solid var(--line);border-radius:999px;padding:4px 11px;"
       "background:var(--card);color:var(--fg);cursor:pointer}.nm-f button.on{border-color:var(--acc);color:var(--acc);"
       "font-weight:600}</style>")


def _mode_html(owner, con):
    from league import mjera
    m = mjera.mode()
    sw = mjera.switched(con) if con is not None else None
    state = ("demo tradeovi praćenja novčanika ugašeni (mjerenje se slaže s demom"
             + (f", {time.strftime('%d.%m.', time.localtime(sw['ts']))}" if sw and sw.get("ts") else "") + ")"
             if not mjera.demo_entries_ok(con) else "demo tradeovi praćenja novčanika teku usporedno")
    if not owner:
        return f'<p class=apx-mut>Način: {rd.h(MODE_HR.get(m, m))}; {rd.h(state)}.</p>'
    btns = "".join(f'<form method=post action=/pravi-trade/mjera-nacin style="display:inline"><input type=hidden '
                   f'name=nacin value={v}><button type=submit{" class=on" if v == m else ""}>{v}</button></form>'
                   for v in mjera.MODES)
    return (f'<div class=nm-f><span class=apx-mut>Način:</span>{btns}</div>'
            f'<p class=apx-mut style="margin-top:4px">{rd.h(MODE_HR.get(m, m))}; {rd.h(state)}.</p>')


def autopilot_html(owner=False, now=None):
    """The Autopilot section while the real-money pause is on; "" otherwise."""
    if not P.pause_on():
        return ""
    from league import mjera
    from ui import rangtable
    con = _con()
    try:
        if con is None or not P.has_table(con, "signal_mjera") or not P.q(con, "SELECT 1 FROM signal_mjera LIMIT 1"):
            body = ('<p class=apx-empty>Mjerenje još nije zabilježilo nijedan signal. Bilježi se svaka kupnja praćenog '
                    'novčanika ili grupe, bez računa i bez stropova.</p>')
            return (f'{rangtable.CSS}{CSS}<h2 class=apx-h2 data-sec="">{rd.h(TITLE)}</h2>{body}'
                    + _mode_html(owner, con))
        s = mjera.summary(con, now)
        a = s["svi"]
        lead = (f"Svaka kupnja praćenog novčanika ili grupe mjeri se u postocima od naše cijene ulaza (nikad njihove) do "
                f"izlaza po istom pravilu (prodali su / stop −25 % / 24 h), neto nakon stvarnog troška (nikad ispod 3 %). "
                f"Zadnjih 30 dana: {rd.num(a['signals'])} signala, {rd.num(a['measured'])} izmjereno, promašeno "
                f"{rd.pct(a['miss_share'] or 0, 0, sign=False, frac=True)}, otvoreno {rd.num(a['open'])}.")
        table = summary_table(s) or ""
        rows = rows_table(latest_rows(con))
        mode = _mode_html(owner, con)
    finally:
        if con is not None:
            con.close()
    return (f'{rangtable.CSS}{CSS}<h2 class=apx-h2 data-sec="">{rd.h(TITLE)}</h2><p class=apx-mut>{rd.h(lead)}</p>'
            f'{table}<p class=apx-mut style="margin-top:8px">{rd.h(capacity_line(s))}</p>'
            + (f'<h3 class=apx-h3 style="margin-top:14px">Zadnji signali</h3>{rows}' if rows else "")
            + mode)


def admin_html(now=None):
    """The admin dashboard's section "Mjerenje po ulazu"."""
    from league import mjera
    con = _con()
    if con is None or not P.has_table(con, "signal_mjera"):
        if con is not None:
            con.close()
        return ('<p class=na-empty>Još nema mjerenja: prvi redak nastaje s prvom kupnjom praćenog novčanika ili '
                'grupe.</p>')
    try:
        s = mjera.summary(con, now)
        par = mjera.parity(con)
        groups = mjera.per_group(con, now)
        proofs = {src: mjera.proof(con, src) for src in mjera.SOURCES}
        mode = mjera.mode()
        sw = mjera.switched(con)
    finally:
        con.close()
    a = s["svi"]
    head = (f'<p class=na-note>Zadnjih 30 dana: {rd.num(a["signals"])} signala, {rd.num(a["measured"])} izmjereno, '
            f'{rd.num(a["misses"])} promašeno, {rd.num(a["open"])} otvoreno; medijan kašnjenja '
            f'{rd.num(a["delay_med"]) + " s" if a["delay_med"] is not None else rd.DASH}. Interval je bootstrap po '
            'token-danu (svi redci jednog tokena u jednom UTC danu su jedno izvlačenje).</p>')
    table = summary_table(s, full=True) or '<p class=na-empty>Još nema izmjerenih signala.</p>'
    pr = "".join(f'<li><b>{rd.h(mjera.LABEL[src])}</b>: {"<span class=ok>dokazano</span>" if p["ok"] else rd.h(p["why"])}'
                 f' (token-dana {rd.num(p["n"])}, srednje {rd.h(_pct(p["mean"]))})</li>' for src, p in proofs.items())
    miss = ", ".join(f"{k} {rd.num(v)}" for k, v in sorted(s["misses"].items(), key=lambda kv: -kv[1])) or rd.DASH
    par_txt = mjera.parity_line(par).replace("mjerenje vs demo: ", "")
    state = (f"prebačeno na mjerenje {time.strftime('%d.%m.%Y.', time.localtime(sw['ts']))}" if sw else
             "demo i mjerenje teku usporedno")
    top = sorted(groups.items(), key=lambda kv: (-kv[1]["measured"], -kv[1]["n"]))[:40]
    grows = "".join(f'<tr><td>{rd.h(mjera.LABEL.get(src, src))}</td><td class=na-l><code translate=no title="{rd.h(gid)}">'
                    f'{rd.h(gid[2:] if str(gid)[:2] in ("o:", "p:") else gid)[:6]}…</code></td><td>{rd.num(d["n"])}</td>'
                    f'<td>{rd.num(d["measured"])}</td><td class="{_tone(d["mean01"])}">{rd.h(_pct(d["mean01"]))}</td></tr>'
                    for (src, gid), d in top)
    gtable = (f'<div class=rt-wrap><table class=rt><thead><tr><th scope=col>Izvor</th><th scope=col>Grupa / novčanik</th>'
              f'<th scope=col>Signala</th><th scope=col>Mjereno</th><th scope=col>Neto 0,1 SOL</th></tr></thead>'
              f'<tbody>{grows}</tbody></table></div>') if grows else ""
    return (f'{CSS}{head}{table}<p class=na-note>{rd.h(capacity_line(s))}</p>'
            f'<p class=na-note><b>Dokaz za pravi novac</b> (≥ {mjera.MIN_TOKEN_DAYS} token-dana, srednje i donja granica '
            f'iznad nule; ništa ga još ne čita):</p><ul class=na-note>{pr}</ul>'
            f'<p class=na-note><b>Promašaji po razlogu:</b> {rd.h(miss)}.</p>'
            f'<p class=na-note><b>Mjerenje i demo:</b> {rd.h(par_txt)}; način {rd.h(mode)}; {rd.h(state)}.</p>'
            + (f'<p class=na-note><b>Po grupi i novčaniku</b> (njegovi signali i srednji neto):</p>{gtable}' if gtable else ""))
