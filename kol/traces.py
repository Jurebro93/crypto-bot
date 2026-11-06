"""5.11. (Nicholas): suspicious transfers around influencers. The Helius webhook now also delivers TRANSFER
transactions of the tracked wallets (kol/chainwatch, hype.db chain_transfers). Rules, each a row in kol.db traces:
  primio_pa_zvao   a tracked wallet RECEIVED tokens of a mint (did not buy them) and its account called that
                   token within 24 h: allotted supply / paid promotion
  veza             a token or SOL transfer between two tracked wallets: the same crew behind two accounts
  supply           one transfer of >= supply_pct % of a token's supply into a tracked wallet
Shown on the KOL page ("Tragovi") and, for the token, as a confidence part ("primio supply, nije kupio").
"""
import json
import sqlite3
import time

DEFAULT = {"supply_pct": 2.0, "call_window_h": 24, "lookback_h": 48}
SCHEMA = """CREATE TABLE IF NOT EXISTS traces (
    id TEXT PRIMARY KEY, kind TEXT, wallet TEXT, handle TEXT, mint TEXT, other TEXT, amount REAL, share REAL,
    ts INTEGER, detail TEXT);
CREATE INDEX IF NOT EXISTS traces_handle ON traces (handle, ts);
CREATE INDEX IF NOT EXISTS traces_mint ON traces (mint, ts)"""


def config(cfg):
    return {**DEFAULT, **((cfg or {}).get("traces") or {})}


def ensure(con):
    con.executescript(SCHEMA)


def _wallet_handles(con):
    """{wallet: handle} for tracked wallets with a public name (kol_ids) or the 'w:<prefix>' handle."""
    out = {}
    try:
        for w, tw, name in con.execute("SELECT wallet, twitter, name FROM kol_ids"):
            out[w] = tw or name or f"w:{w[:6]}"
    except sqlite3.OperationalError:
        pass
    return out


def run(con, hype_db, cfg=None, now=None, tracked=None):
    """Scan recent chain_transfers (hype.db) against calls and tracked wallets; write new traces. Returns count."""
    ensure(con)
    c = config(cfg)
    now = now or int(time.time())
    try:
        h = sqlite3.connect(f"file:{hype_db}?mode=ro", uri=True, timeout=5)
    except sqlite3.Error:
        return 0
    try:
        try:
            rows = h.execute("SELECT sig, src, dst, mint, amount, ts FROM chain_transfers WHERE ts >= ? ORDER BY ts",
                             (now - c["lookback_h"] * 3600,)).fetchall()
        except sqlite3.OperationalError:
            return 0
    finally:
        h.close()
    if not rows:
        return 0
    names = _wallet_handles(con)
    tracked = set(tracked if tracked is not None else names)
    supply = dict(con.execute("SELECT token, supply FROM tokens WHERE supply IS NOT NULL"))
    n = 0
    for sig, src, dst, mint, amount, ts in rows:
        amount = amount or 0
        if src in tracked and dst in tracked and src != dst:
            n += _put(con, f"veza:{sig}", "veza", src, names.get(src), mint, dst, amount, None, ts,
                      {"to_handle": names.get(dst)})
        if dst in tracked and mint and mint != "SOL":
            sup = supply.get(mint)
            share = (amount / sup * 100) if sup else None
            if share is not None and share >= c["supply_pct"]:
                n += _put(con, f"supply:{sig}:{dst}", "supply", dst, names.get(dst), mint, src, amount, round(share, 2), ts, {})
            handle = names.get(dst)
            if handle and not handle.startswith("w:"):
                call = con.execute("SELECT MIN(ts) FROM calls WHERE LOWER(handle)=LOWER(?) AND token=? AND kind='call' AND ts>=? AND ts<=?",
                                   (handle, mint, ts, ts + c["call_window_h"] * 3600)).fetchone()[0]
                if call:
                    n += _put(con, f"primio:{sig}:{dst}", "primio_pa_zvao", dst, handle, mint, src, amount, share, ts,
                              {"call_ts": call, "minutes_to_call": round((call - ts) / 60)})
    con.commit()
    return n


def _put(con, tid, kind, wallet, handle, mint, other, amount, share, ts, detail):
    return con.execute("INSERT OR IGNORE INTO traces VALUES (?,?,?,?,?,?,?,?,?,?)",
                       (tid, kind, wallet, handle, mint, other, amount, share, int(ts), json.dumps(detail))).rowcount


def for_handle(con, handle, limit=20):
    ensure(con)
    return con.execute("SELECT kind, mint, other, amount, share, ts, detail FROM traces WHERE LOWER(handle)=LOWER(?) "
                       "ORDER BY ts DESC LIMIT ?", (handle, limit)).fetchall()


def for_token(con, mint, since=None):
    ensure(con)
    return con.execute("SELECT kind, handle, wallet, share, ts FROM traces WHERE mint=? AND ts>=? ORDER BY ts DESC",
                       (mint, int(since or 0))).fetchall()


def token_flags(kol_db, mints, since):
    """{mint: {primio: n, supply: n}} for the scan (hype feature 'primio_supply')."""
    try:
        con = sqlite3.connect(f"file:{kol_db}?mode=ro", uri=True, timeout=5)
    except sqlite3.Error:
        return {}
    out = {}
    try:
        q = ",".join("?" * len(mints)) if mints else "''"
        for mint, kind, n in con.execute(f"SELECT mint, kind, COUNT(*) FROM traces WHERE ts>=? AND mint IN ({q}) GROUP BY mint, kind",
                                         [int(since), *mints]):
            out.setdefault(mint, {})[kind] = n
    except sqlite3.OperationalError:
        return {}
    finally:
        con.close()
    return out


def html(con, handle):
    from ui.html import esc
    rows = for_handle(con, handle)
    if not rows:
        return ""
    names = {"primio_pa_zvao": "primio tokene, pa ih zvao", "veza": "transfer na drugi praćeni novčanik", "supply": "primio velik dio supplya"}
    items = []
    for kind, mint, other, amount, share, ts, detail in rows:
        d = json.loads(detail or "{}")
        extra = (f", poziv {d['minutes_to_call']} min kasnije" if kind == "primio_pa_zvao" else
                 f" (→ {esc(d.get('to_handle') or (other or '')[:6])})" if kind == "veza" else "")
        items.append(f"<li><b>{names.get(kind, kind)}</b>: <a href='/token/{esc(mint or '')}'>{esc((mint or '')[:8])}…</a>"
                     + (f", {share:.1f} % supplya" if share else "") + extra
                     + f" <small class=mut>{time.strftime('%d.%m. %H:%M', time.gmtime(ts))} UTC</small></li>")
    return ("<h2>Tragovi</h2><p class=mut>Transferi oko ovog računa (Helius): tokeni koje je primio, a nije kupio, pa ih zvao; "
            "transferi prema drugim praćenim novčanicima; veliki dijelovi supplya. Dokaz plaćene promocije ili iste ekipe iza više računa.</p>"
            f"<ul class=r>{''.join(items)}</ul>")
