"""/pregled: the page the app opens on (Nicholas 4.11.: "da se ne otvara stranica tokens, nego pregled"). One screen
that answers: which strategy makes the most money and how much, how much data the tool holds, how that grew compared
with last week, a few things worth a look right now, and quick links to the main pages.

Everything is read-only and cheap: small queries on strat.db, kol.db and tg.db plus the shared "first seen" series of
the old Pregled (ui/overview._first_seen, file-cached 10 min). The page is the same for everyone, so it is pre-rendered
in a child process like /tokens (run_ui.HEAVY / WARM). Any block that fails shows a short line instead of breaking the
page.
"""
import glob
import os
import sqlite3
import time

from ui import data
from ui.html import esc, tlink

WEEK = 7 * 86400

CSS = """<style>
.ov-hero{background:linear-gradient(135deg,color-mix(in srgb,var(--acc) 9%,var(--card)),var(--card));border:1px solid var(--line);
 border-radius:14px;padding:16px 18px;margin:0 0 18px}
.ov-hero .k{font-size:12.5px;color:var(--mut);text-transform:uppercase;letter-spacing:.05em}
.ov-hero .n{font-size:22px;font-weight:650;margin:2px 0 4px}
.ov-hero .r{font-size:36px;font-weight:700;letter-spacing:-.02em;font-variant-numeric:tabular-nums;line-height:1.1}
.ov-hero .s{font-size:14px;margin-top:6px}
.ov-rank{list-style:none;padding:0;margin:12px 0 0;display:grid;gap:4px;font-size:14px}
.ov-rank li{display:flex;justify-content:space-between;gap:10px;border-top:1px solid var(--line);padding-top:5px}
.ov-rank li span:last-child{font-variant-numeric:tabular-nums;white-space:nowrap}
.ov-g{display:grid;grid-template-columns:repeat(auto-fill,minmax(190px,1fr));gap:10px;margin:6px 0 18px}
.ov-t{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:11px 14px}
.ov-t .l{font-size:12.5px;color:var(--mut)}.ov-t .v{font-size:24px;font-weight:650;font-variant-numeric:tabular-nums}
.ov-t .d{font-size:13px;margin-top:2px}
.ov-hl{list-style:none;padding:0;margin:6px 0 18px;display:grid;gap:8px}
.ov-hl li{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:10px 14px;display:flex;gap:12px;align-items:flex-start}
.ov-hl .i{font-size:22px;line-height:1.2}.ov-hl .x{min-width:0}.ov-hl .x .tt{display:block;font-size:13px;color:var(--mut);font-weight:500}
.ov-hl .x a.more{white-space:nowrap}
@media(max-width:700px){.ov-g{grid-template-columns:1fr 1fr}.ov-t .v{font-size:20px}.ov-hero .r{font-size:30px}}
</style>"""


def _ro(path):
    if not path or not os.path.exists(path) or not os.path.getsize(path):
        return None
    try:
        return sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5)
    except sqlite3.Error:
        return None


def _pct(x, digits=1):
    if x is None:
        return "–"
    cls = "pos" if x > 0 else "neg" if x < 0 else "mut"
    return f'<span class={cls}>{x:+.{digits}%}</span>'


# ---------- 1. the most profitable strategy ----------

def strategies(now=None):
    """The five strategy accounts ranked by account value, each with its change over the last 24 h and 7 days
    (from the equity snapshots), or None before strat.db exists."""
    from strat import run, store
    now = now or time.time()
    con = store.ro()
    if con is None:
        return None
    try:
        cfg = run.load_config()
        summ = run.summary(con, cfg, run.exit_rules(now))
        start = float(store.kv_get(con, "start_ts", now) or now)

        def value_at(key, ts):
            r = con.execute("SELECT value FROM equity WHERE strat=? AND ts<=? ORDER BY ts DESC LIMIT 1", (key, ts)).fetchone()
            return r[0] if r else None
        for s in summ:
            v1 = value_at(s["key"], now - 86400)
            v7 = value_at(s["key"], now - WEEK) if now - start >= WEEK else None   # younger: "od početka" says it
            s["d24"] = (s["value"] - v1) / cfg["bankroll_usd"] if v1 is not None else None
            s["d7"] = (s["value"] - v7) / cfg["bankroll_usd"] if v7 is not None else None
    finally:
        con.close()
    return {"cfg": cfg, "days": max(0.0, (now - start) / 86400),
            "rank": sorted(summ, key=lambda s: -s["value"])}


def _real(s, bankroll):
    """What a real $1,000 account would hold: the no-borrowing replay of the closed trades (strat/robust.portfolio).
    The research ledger keeps buying below $0 so a strategy collects trades to learn from (config cash_limit false);
    that number can read "-377 %" of a $1,000 account, which no real account can do (9.11., Jure: be self-critical)."""
    pf = s.get("portfolio") or {}
    v = pf.get("value")
    if v is None:
        return s["value"], s["ret"]
    return v, v / bankroll - 1


def _strategy_info(st, best, winners, hidden, control):
    """The pop-up behind "Vidi više": what is measured, how to read it, and the conclusion for the leader."""
    cfg = st["cfg"]
    rb = best.get("robust") or {}
    pf = best.get("portfolio") or {}
    stt = best.get("status") or ()
    n_all = len(st["rank"])
    hit = f"{best['hit']:.0%}" if best.get("hit") is not None else "–"
    p15 = f"{best['p15']:.0%}" if best.get("p15") is not None else "–"
    ctrl = (f"Nasumični ulaz (kontrola) iz istog skenera stoji na {_pct(control['ret'])} nakon {control['closed']} "
            f"zatvorenih: toliko gubi tržište samo po sebi u ovom razdoblju." if control else
            "Nasumična kontrola još nema zatvorenih tradeova.")
    conc = ""
    if rb:
        if rb.get("concentrated"):
            conc = (f"Ukupno zatvoreno {rb['total']:+,.0f} $, ali najbolji trade nosi {rb['best']:+,.0f} $; bez njega "
                    f"{rb['no_best']:+,.0f} $, bez 5 najboljih {rb['no_top5']:+,.0f} $. <b>Rezultat ovisi o jednom tradeu</b>, "
                    "to nije dokaz da pravilo radi.")
        else:
            conc = (f"Ukupno zatvoreno {rb['total']:+,.0f} $; bez najboljeg tradea {rb['no_best']:+,.0f} $, bez 5 najboljih "
                    f"{rb['no_top5']:+,.0f} $.")
    skipped = (f" ({pf['skipped']} ulaza preskočeno jer na računu nije bilo novca)" if pf.get("skipped") else "")
    verdict = f"<b>{esc(stt[1])}</b> · {esc(stt[2])}" if len(stt) >= 3 else "–"
    body = (
        f"<h3>Što se mjeri</h3>"
        f"<p>{n_all} odvojenih demo računa po ${cfg['bankroll_usd']:,.0f}, od {st['days']:.0f} dana. Svaki kupuje po jednom "
        f"pravilu (izvoru signala), s ulogom ${cfg.get('size_usd', 50)} po ulazu, a svi izlaze po istim pravilima: za tokene "
        f"ispod 1 M $ pola se proda na +15 %, ostatak prati stop 15 % ispod vrha, stop −25 %; za tokene iznad 1 M $ stop −20 % "
        f"i ljestvica +15 % / +30 %. Cijene su demo cijene s DexScreenera i GeckoTerminala, s troškom 1 % po strani. "
        f"Nikad pravi novac.</p>"
        f"<h3>Kako čitati brojke</h3>"
        f"<ul><li><b>S pravih ${cfg['bankroll_usd']:,.0f}</b>: isti zatvoreni tradeovi ponovljeni s fiksnim računom bez "
        f"posuđivanja; ulaz za koji nema gotovine se preskače. To je broj na ovoj kartici.</li>"
        f"<li><b>Istraživačka knjiga</b>: račun koji kupuje i kad potroši novac, da strategija skupi dovoljno tradeova za "
        f"učenje; zato na stranici Usporedba strategija može pasti ispod nule. Nije rezultat koji bi pravi račun imao.</li>"
        f"<li><b>Tradeova u plusu</b>: udio zatvorenih tradeova s dobiti. <b>≥ +15 %</b>: udio koji je dosegao +15 %.</li>"
        f"<li><b>Presuda</b>: <i>uči</i> dok nema 100 zatvorenih; <i>kandidat</i> tek kad po tradeu pobjeđuje nasumični ulaz, "
        f"u obje polovice razdoblja i bez 5 najboljih tradeova; inače <i>ne diraj pravi novac</i>. Kandidat znači daljnje "
        f"testiranje, ne pravi novac.</li>"
        f"<li>Ovdje su samo strategije u plusu; {hidden} ih je u minusu ili bez tradeova i vide se na punoj stranici.</li></ul>"
        f"<h3>Zaključak za {esc(best['icon'])} {esc(best['name'])}</h3>"
        f"<p>S pravih ${cfg['bankroll_usd']:,.0f}: <b>${pf.get('value', best['value']):,.0f}</b>{skipped}. "
        f"{best['closed']} zatvorenih, {hit} u plusu, {p15} doseglo +15 %. {conc}</p>"
        f"<p>{ctrl}</p><p>Presuda: {verdict}.</p>"
        f"<h3>Što još nije pouzdano</h3>"
        f"<p>Otvorene pozicije vrijede po zadnjoj viđenoj cijeni, a za mrtve tokene ta cijena može biti stara. Demo ne "
        f"plaća pravi slippage pri ulazu u tanke tokene. Razdoblje je kratko ({st['days']:.0f} dana) i jedno tržišno "
        f"stanje; presuda se mijenja kad kontrola i strategije skupe više tradeova.</p>")
    return ("<dialog id=strat-info><div class=bar2><button onclick=\"this.closest('dialog').close()\">Zatvori ✕</button></div>"
            f"<div class=body>{body}</div></dialog>"
            "<script>(function(){var d=document.getElementById('strat-info');if(d)d.addEventListener('click',function(e){"
            "if(e.target===d)d.close()})})()</script>")


def strategy_html(now=None):
    try:
        st = strategies(now)
    except Exception as e:  # noqa: BLE001 - a broken block never takes the page down
        return f"<div class=card>Usporedba strategija se trenutno ne može prikazati ({esc(type(e).__name__)}).</div>"
    if not st or not any(s["closed"] + s["open"] for s in st["rank"]):
        return ("<div class=ov-hero><div class=k>Najprofitabilnija strategija</div><div class=s>Pet demo računa po $1000 "
                "još nema nijedan trade. Prvi ulazi dolaze unutar par minuta nakon pokretanja.</div>"
                "<div class=s><a href=/strategije>Usporedba strategija →</a></div></div>")
    cfg = st["cfg"]
    bankroll = cfg["bankroll_usd"]
    # 9.11. (Jure: be self-critical): the card ranks by what a real $1,000 would hold (no borrowing), not by the
    # research ledger, which keeps buying below $0 and showed "-377 %" accounts; see _real() and the pop-up
    rows = []
    for s in st["rank"]:
        v, r = _real(s, bankroll)
        rows.append({**s, "real_value": v, "real_ret": r})
    control = next((s for s in rows if s["key"] == "kontrola"), None)
    rank = sorted((s for s in rows if s["key"] != "kontrola"), key=lambda s: -s["real_value"]) or rows
    best = rank[0]
    total = sum(s["closed"] for s in rank)
    profit = best["real_value"] - bankroll
    hit = f"{best['hit']:.0%}" if best["hit"] is not None else "–"
    early = (f"<div class=s>⏳ Još je rano: zatvoreno {total} tradeova. Pouzdan pobjednik treba ~20 zatvorenih po "
             "strategiji.</div>" if total < 20 * len(rank) else "")
    lead = "vodi" if best["real_ret"] > 0 else "najmanje gubi"
    # the same verdict as on /strategije (strat/robust.py): "uči" until 100 closed trades, "kandidat" only when it
    # beats the random control; without it "+342 %" on 33 trades read as a proven winner (4.11.)
    stt = best.get("status") or ()
    verdict = (f'<div class=s>Presuda: <b>{esc(stt[1])}</b> · {esc(stt[2])}</div>' if len(stt) >= 3 else "")
    rb = best.get("robust") or {}
    conc = (f'<div class=s>⚠ Bez najboljeg tradea: <b>{rb["no_best"]:+,.0f} $</b>. Plus nosi jedan trade.</div>'
            if rb.get("concentrated") else "")
    d7 = (f" · zadnjih 7 dana {_pct(best['d7'])}" if best.get("d7") is not None else "")
    d24 = (f" · zadnja 24 h {_pct(best['d24'])}" if best.get("d24") is not None else "")
    # 9.11. (audit P69): d24/d7 come from the equity snapshots of the research ledger (open positions at mark, buys
    # below $0), not from the "s pravih $1000" replay the card ranks by; say so instead of mixing the two books
    if d24 or d7:
        d7 += (' <span class=mut title="Promjena istraživačke knjige (equity snimke: otvorene pozicije po zadnjoj cijeni, '
               'kupnje i kad nema gotovine), ne replaya s pravih $1000; dok račun ne ostane bez gotovine brojke se poklapaju">'
               '(istraživačka knjiga)</span>')
    # 9.11. (Jure): only strategies in profit are listed here; the losers are a count and a link, the full table is
    # on /strategije. A reader deciding what to follow does not need twelve red rows.
    winners = [s for s in rank[1:] if s["real_ret"] > 0 and s["closed"]]
    hidden = len(rank) - 1 - len(winners)
    others = "".join(f'<li><span>{i}. {esc(s["icon"])} {esc(s["name"])}</span><span>{_pct(s["real_ret"])} · '
                     f'${s["real_value"]:,.0f}</span></li>' for i, s in enumerate(winners, 2))
    rest = (f'<div class=s>Još {hidden} strategija je u minusu ili bez tradeova; ovdje se ne prikazuju.</div>' if hidden else "")
    return (f'<div class=ov-hero><div class=k>Najprofitabilnija strategija · {lead} · s pravih ${bankroll:,.0f}</div>'
            f'<div class=n>{esc(best["icon"])} {esc(best["name"])}</div>'
            f'<div class="r {"pos" if best["real_ret"] > 0 else "neg" if best["real_ret"] < 0 else ""}">{best["real_ret"]:+.1%}</div>'
            f'<div class=s>${bankroll:,.0f} → <b>${best["real_value"]:,.0f}</b> ({profit:+,.0f} $) za '
            f'{st["days"]:.1f} dana{d24}{d7}</div>'
            f'<div class=s>{best["closed"]} zatvorenih tradeova, {hit} tradeova u plusu · {esc(best.get("opis") or "")}</div>'
            f'{verdict}{conc}{early}' + (f'<ul class=ov-rank>{others}</ul>' if others else "") + rest +
            '<div class=s style="margin-top:10px"><a href=/strategije>Sve strategije, graf i tradeovi →</a> · '
            '<a href="#" onclick="document.getElementById(\'strat-info\').showModal();return false">'
            'Vidi više: što se mjerilo, kako i zaključak</a></div></div>'
            + _strategy_info(st, best, winners, hidden, control))


# ---------- 2. how much data, and growth against last week ----------

def hype_db_path():
    from live import store as lstore
    return lstore.HYPE_DB


def _week_counts(tss, now):
    """(total, new in the last 7 days, new in the 7 days before)."""
    a = b = 0
    for t in tss:
        if not t:
            continue
        if t > now - WEEK:
            a += 1
        elif t > now - 2 * WEEK:
            b += 1
    return len(tss), a, b


def _sql_counts(path, table, col, now, where="1=1"):
    con = _ro(path)
    if con is None:
        return None
    try:
        r = con.execute(f"SELECT COUNT(*), COALESCE(SUM({col} > ?), 0), COALESCE(SUM({col} > ? AND {col} <= ?), 0) "
                        f"FROM {table} WHERE {where}", (now - WEEK, now - 2 * WEEK, now - WEEK)).fetchone()
        return int(r[0]), int(r[1]), int(r[2])
    except sqlite3.Error:
        return None
    finally:
        con.close()


def metrics(now=None):
    """[(icon, label, href, (total, this week, last week))] for every kind of data the tool collects."""
    from ui import overview
    from kol import store as kol_store
    from tg import store as tg_store
    now = now or time.time()
    try:
        series = overview._first_seen()
    except Exception:  # noqa: BLE001
        series = {}
    out = []
    for icon, label, href, key in (("🪙", "Tokeni analizirani", "/tokens", "Tokena analizirano"),
                                   ("👛", "Novčanici u registru", "/wallets", "Walleta u registru"),
                                   ("🛡", "Rug provjere", "/tokens", "Rug provjera")):
        if series.get(key):
            out.append((icon, label, href, _week_counts(series[key], now)))
    # kol.db keeps more than X accounts and their calls: Telegram channels ('tg:'), tracked wallets ('w:') and every
    # swap of a tracked wallet (kind 'buy' / 'sell', ~1,500 a round) live in the same tables. Until 4.11. the page
    # counted all of it as "Influenceri (X)" and "Pozivi influencera" (185,022 "calls", mostly wallet swaps).
    not_x = "handle NOT LIKE 'tg:%' AND handle NOT LIKE 'w:%'"
    for icon, label, href, path, table, col, where in (
            ("📣", "Influenceri (X)", "/kol", kol_store.DB, "kols", "first_seen", not_x),
            ("🗣", "Pozivi influencera (X + Telegram)", "/kol", kol_store.DB, "calls", "ts", "kind = 'call'"),
            ("👛", "Kupnje i prodaje praćenih novčanika", "/kol", kol_store.DB, "calls", "ts", "kind IN ('buy', 'sell')"),
            ("⚡", "Kupnje i prodaje u živom toku (PumpPortal, zadnjih 48 h)", "/izvori", hype_db_path(), "live_trades", "ts", "1=1"),
            ("🎓", "Tokeni koji su bondali (živi tok)", "/izvori", hype_db_path(), "live_launches", "ts", "pool = 'migration'"),
            # 5.11.: the same number /izvori shows as "aktivnih Telegram kanala" (status 'active'); the page counted
            # every known channel (22,462: candidates, dead, spam) while /izvori said 264
            ("💬", "Aktivni Telegram kanali", "/izvori", tg_store.DB, "channels", "found_ts", "status = 'active'"),
            ("✉️", "Telegram poruke", "/izvori", tg_store.DB, "posts", "seen_ts", "1=1")):
        c = _sql_counts(path, table, col, now, where)
        if c and c[0]:
            out.append((icon, label, href, c))
    return out


def _all_dbs():
    """Every SQLite file of the tool (the repo folder holds them, symlinked to the server disk)."""
    return sorted({os.path.realpath(p) for p in glob.glob(os.path.join(data.HERE, "*.db"))})


def _db_totals_now():
    rows = size = 0
    for p in _all_dbs():
        try:
            size += os.path.getsize(p)
        except OSError:
            continue
        con = _ro(p)
        if con is None:
            continue
        try:
            for (t,) in con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"):
                try:
                    # MAX(rowid) instead of COUNT(*): instant on a 600 MB table (COUNT reads it all); a few deleted
                    # rows make it slightly high, which is fine for "about how much data". Not for a table whose
                    # rowid IS a data column ("ts INTEGER PRIMARY KEY", "day INTEGER PRIMARY KEY"): there MAX(rowid)
                    # is a timestamp, and the page showed ~7 billion rows in 1.5 GB (4.11.). Those are counted.
                    rows += con.execute(f"SELECT {_count_expr(con, t)} FROM [{t}]").fetchone()[0]
                except sqlite3.Error:
                    pass
        except sqlite3.Error:
            pass
        finally:
            con.close()
    return rows, size, len(_all_dbs())


def _count_expr(con, table):
    """COUNT(*) when a single INTEGER column is the primary key (the rowid then holds its values: timestamps, days,
    ids from outside), else COALESCE(MAX(rowid), 0). AUTOINCREMENT ids stay on the fast path."""
    cols = con.execute(f"PRAGMA table_info([{table}])").fetchall()
    pk = [c for c in cols if c[5]]
    if len(pk) == 1 and (pk[0][2] or "").strip().upper() == "INTEGER":
        seq = con.execute("SELECT COUNT(*) FROM sqlite_master WHERE name = 'sqlite_sequence'").fetchone()[0]
        if not (seq and con.execute("SELECT COUNT(*) FROM sqlite_sequence WHERE name = ?", (table,)).fetchone()[0]):
            return "COUNT(*)"
    return "COALESCE(MAX(rowid), 0)"


def db_totals():
    """(rows in all databases, bytes on disk, number of databases); counted at most every 30 min."""
    return data.ttl_cache(f"pregled_db_totals:{data.HERE}", 1800, _db_totals_now)


def _growth_line(new, prev):
    if not new and not prev:
        return "<span class=mut>ništa novo ovaj tjedan</span>"
    if not prev:
        return f"<span class=pos>+{new:,}</span> ovaj tjedan <span class=mut>(prošli 0)</span>"
    r = new / prev - 1
    if abs(r) < 0.005:
        r = 0.0
    arrow = "▲" if r > 0.05 else "▼" if r < -0.05 else "≈"
    cls = "pos" if r > 0.05 else "neg" if r < -0.05 else "mut"
    pct = f"{r:+.0%}" if r else "0%"
    return (f"<b>+{new:,}</b> ovaj tjedan · <span class={cls}>{arrow} {pct}</span> "
            f"<span class=mut>vs prošli (+{prev:,})</span>")


def data_html(now=None):
    now = now or time.time()
    try:
        ms = metrics(now)
    except Exception as e:  # noqa: BLE001
        return f"<div class=card>Podaci se trenutno ne mogu prebrojati ({esc(type(e).__name__)}).</div>"
    try:
        rows, size, n_db = db_totals()
    except Exception:  # noqa: BLE001
        rows, size, n_db = 0, 0, 0
    tiles = []
    if rows:
        tiles.append(f'<div class=ov-t><div class=l>🗄 Ukupno zapisa</div><div class=v>~{rows:,}</div>'
                     f'<div class="d mut">{size / 1e9:.2f} GB u {n_db} baza</div></div>')
    for icon, label, href, (total, new, prev) in ms:
        tiles.append(f'<a class=ov-t href="{href}" style="text-decoration:none;color:inherit"><div class=l>{icon} {esc(label)}</div>'
                     f'<div class=v>{total:,}</div><div class=d>{_growth_line(new, prev)}</div></a>')
    new_w = sum(m[3][1] for m in ms)
    prev_w = sum(m[3][2] for m in ms)
    summary = ""
    if prev_w:
        r = new_w / prev_w - 1
        word = "više" if r >= 0 else "manje"
        summary = (f"<p class=s style='margin:2px 0 8px'>Ovaj tjedan alat je skupio <b>{new_w:,}</b> novih zapisa, "
                   f"<b class={'pos' if r >= 0 else 'neg'}>{abs(r):.0%} {word}</b> nego prošli tjedan ({prev_w:,}).</p>")
    elif new_w:
        summary = f"<p class=s style='margin:2px 0 8px'>Ovaj tjedan alat je skupio <b>{new_w:,}</b> novih zapisa.</p>"
    return summary + "<div class=ov-g>" + "".join(tiles) + "</div>"


# ---------- 3. worth a look right now ----------

def _hl(icon, title, body, href=None, more="Otvori"):
    link = f' <a class=more href="{href}">{esc(more)} →</a>' if href else ""
    return f"<li><span class=i>{icon}</span><span class=x><span class=tt>{esc(title)}</span>{body}{link}</span></li>"


def _hl_win():
    from ui import wins
    w = wins.collect(7, 1)
    if not w:
        return None
    w = w[0]
    who = "Demo bot" if w["who"] == "bot" else esc(w["who"])
    return _hl("🏆", "Najveći pogodak tjedna",
               f'{who}: {tlink(w["token"], w["symbol"])} <b class=pos>{w["ret"]:+.0%}</b> ({w["pnl"]:+,.0f} $), '
               f'na vrhu bi bilo {w["peak"]:+.0%}.', "/natjecanje", "Natjecanje")


def _hl_kol():
    from ui import core
    from ui.kol import klink
    con = core._con()
    if con is None:
        return None
    try:
        ks = core.top_kols(con, n=5)
    finally:
        con.close()
    if not ks:
        return None
    # 9.11. (audit P43): among the top accounts by call power, the one with the best +15 % before the stop on the
    # minute measure (kol/minute, the measure the real-money follows are chosen by); the 24-h fuse is the old measure
    from ui.kol import minute_stats
    ms, hot = minute_stats()
    k = max(ks, key=lambda x: ((ms.get(x["handle"]) or {}).get("hit15", -1), x["score"] or 0))
    s = k["s"]
    m = ms.get(k["handle"])
    minute = (f' Minutna provjera: +15 % prije stopa {m["hit15"]:.0%}, stop prvi {m["sl"]:.0%} na {m["n"]} poziva'
              + (" · 🔥 vruća lista" if k["handle"] in hot else "") + "." if m else
              " Minutna provjera još nema njegovih poziva.")
    return _hl("📣", "Najbolji influencer",
               f'{klink(k["handle"])}: od {s.get("measured", 0)} izmjerenih poziva {(s.get("hit_rate") or 0):.0%} '
               f'naraste +50 % u 24 h (stara mjera), medijan vrha u 24 h {_pct(s.get("med_max24"), 0)}.{minute}',
               "/kol", "Svi influenceri")


def _hl_converge(now):
    """The token that most independent sources (X, Telegram, on-chain) called together in the last 24 h."""
    from kol import converge, store as kol_store
    con = _ro(kol_store.DB)
    if con is None:
        return None
    skip = converge.majors()   # WBTC & co. are not "called"; they are what wallets trade through
    try:   # 9.11. (audit P71): rugged-and-archived tokens are out, like on every other page
        from rugfilter import archive
        gone = archive.blocked()
    except Exception:  # noqa: BLE001
        gone = frozenset()
    try:
        # 9.11. (audit P71): the same symbol rule as the Autopilot (kol/converge.not_a_memecoin: wrapped assets,
        # xStocks), so a COINx cannot be the page's hot token while the Autopilot refuses it; the 24-h window stays
        # (the page is pre-rendered for everyone and a 30-min window would mostly be empty)
        r = next((row for row in con.execute(
            "SELECT c.token, t.symbol, c.n_x, c.n_tg, c.n_chain, c.ts FROM converge c "
            "LEFT JOIN tokens t ON t.token = c.token WHERE c.ts >= ? "
            "ORDER BY (COALESCE(c.n_x,0) + COALESCE(c.n_tg,0) + COALESCE(c.n_chain,0)) DESC, c.score DESC LIMIT 20",
            (now - 86400,)) if row[0] not in skip and row[0] not in gone
            and not converge.not_a_memecoin(row[0], row[1])), None)
    except sqlite3.Error:
        return None
    finally:
        con.close()
    if not r:
        return None
    tok, sym, nx, ntg, nch, cts = r
    # n_chain counts every webhook wallet (kol/converge), not only the followed ones: say so
    parts = [f"{n} {w}" for n, w in ((nx, "na X-u"), (ntg, "na Telegramu"), (nch, "webhook novčanika")) if n]
    if not parts:
        return None
    from ui.html import ago
    when = f' <span class=mut>(zadnji poziv {ago(cts)[0]})</span>' if cts else ""
    return _hl("🔥", "Najviše izvora zove isti token (24 h)",
               f'{tlink(tok, sym)}: {", ".join(parts)}.{when}', f"/token/{tok}", "Analiza tokena")


def _hl_wallets(now):
    from ui import core
    con = core._con()
    if con is None:
        return None
    try:
        b, s = con.execute("SELECT COALESCE(SUM(kind='buy'),0), COALESCE(SUM(kind='sell'),0) FROM calls "
                           "WHERE kind IN ('buy','sell') AND ts >= ?", (now - 86400,)).fetchone()
    except sqlite3.Error:
        return None
    finally:
        con.close()
    if not b and not s:
        return None
    # 9.11. (audit P70): kol.db calls buy/sell are the swaps of ALL ~100 webhook wallets (data for the leaderboards);
    # the Autopilot's "praćeni" are only the wallets the real-money account follows plus the proven-twice list
    # (ui/pravitrade.followed_wallets), so the two populations get two names and two numbers
    extra = _followed_buys(now)
    return _hl("👛", "Svi webhook novčanici u zadnja 24 h",
               f"<b class=pos>{b:,}</b> kupnji i <b class=neg>{s:,}</b> prodaja (svih praćenih leaderboard novčanika)."
               + (f' Praćeni + dokazani (Autopilot): <b>{extra:,}</b> kupnji · <a href="/pravi-trade#zovu">Zovu sada</a>.'
                  if extra is not None else ""), "/wallets", "Tko je kupio")


def _followed_buys(now):
    """Buys in the last 24 h of the wallets the Autopilot counts as calls (follows + proven twice), from hype.db
    chain_trades like pravitrade.gather_callers; None when nothing is followed or the sources are missing."""
    try:
        from ui import pravitrade
        from league import copy
        followed = sorted(pravitrade.followed_wallets())
        if not followed:
            return None
        con = _ro(copy._paths()["hype"])
        if con is None:
            return None
        try:
            q = ",".join("?" * len(followed))
            return con.execute(f"SELECT COUNT(*) FROM chain_trades WHERE side = 'buy' AND ts >= ? AND wallet IN ({q})",
                               (int(now) - 86400, *followed)).fetchone()[0]
        finally:
            con.close()
    except Exception:  # noqa: BLE001 - the highlight works without the Autopilot number
        return None


def _hl_strategy_trade(now):
    """The best closed strategy trade of the last 7 days."""
    from strat import store
    con = store.ro()
    if con is None:
        return None
    try:
        r = con.execute("SELECT strat, token, symbol, pnl_usd, ret FROM positions WHERE status='closed' AND "
                        "closed_ts >= ? ORDER BY pnl_usd DESC LIMIT 1", (now - WEEK,)).fetchone()
    except sqlite3.Error:
        return None
    finally:
        con.close()
    if not r or not (r[3] or 0) > 0:
        return None
    from strat import run
    names = {s["key"]: f'{s["icon"]} {s["name"]}' for s in run.load_config()["strategies"]}
    return _hl("🎯", "Najbolji trade strategija (7 dana)",
               f'{esc(names.get(r[0], r[0]))}: {tlink(r[1], r[2])} <b class=pos>{(r[4] or 0):+.0%}</b> '
               f'({r[3]:+,.0f} $).', "/strategije#tradeovi", "Svi tradeovi")


def highlights_html(now=None):
    now = now or time.time()
    items = []
    for fn in (lambda: _hl_converge(now), _hl_win, lambda: _hl_strategy_trade(now), _hl_kol, lambda: _hl_wallets(now)):
        try:
            x = fn()
        except Exception:  # noqa: BLE001 - one broken highlight is just left out
            x = None
        if x:
            items.append(x)
    if not items:
        return "<div class=card>Još nema dovoljno podataka za zanimljivosti.</div>"
    return "<ul class=ov-hl>" + "".join(items) + "</ul>"


# ---------- 4. quick links ----------

QUICK = ["/tokens", "/kol", "/wallets", "/strategije", "/paper", "/events", "/natjecanje", "/pojmovnik"]


def links_html():
    from ui.html import SECTIONS, _role_cls
    pages = {p["href"]: p for _, items in SECTIONS for p in items}
    cards = [f'<a class="mapcard{_role_cls(h)}" href="{h}"><span class=mi>{pages[h]["icon"]}</span>'
             f'<b>{esc(pages[h]["name"])}</b><span class=mut>{esc(pages[h]["desc"])}</span></a>'
             for h in QUICK if h in pages]
    return "<div class=mapgrid>" + "".join(cards) + "</div>"


def page(qs=None):
    now = time.time()
    b = [CSS, "<h1>Pregled</h1>"]
    try:   # 7.11. (Jure): "u ovom trenutku bih uložio…": tokens, wallet, crew, expected return and exit
        from ui import prijedlog
        b.append(prijedlog.box("pregled", now))
    except Exception as e:  # noqa: BLE001
        print(f"pregled: prijedlog: {type(e).__name__}: {e}")
    t = time.time()
    b.append(strategy_html(now))
    t = data.stage("/pregled strategije", t)
    b.append("<h2 id=podaci>Koliko podataka alat ima</h2>" + data_html(now))
    t = data.stage("/pregled podaci", t)
    b.append("<h2 id=zanimljivo>Zanimljivo sada</h2>" + highlights_html(now))
    t = data.stage("/pregled zanimljivo", t)
    b.append("<h2 id=brzo>Brzi linkovi</h2>" + links_html())
    return "Pregled", "".join(b)
