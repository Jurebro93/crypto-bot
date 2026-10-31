"""/watch: tokens tracked from ~14 days before their event, and whether volume and buyers rise as it nears.

Reads watch.db (written by run_watch.py). Kept in its own file so other dashboard work doesn't collide.
"""
import json
import os

from ui import data
from ui.html import badge, esc, ext_token, filt, num, signed, table, tdesc, tierb, tlink, ts, usd, wlink

WATCH_DB = os.environ.get("WATCH_DB", os.path.join(data.HERE, "watch.db"))

VERDICT_KIND = {"volumen i smart money rastu prema eventu": "good", "volumen raste prema eventu": "good",
                "ulaze loši walleti": "bad", "volumen pada (hype je možda već prošao)": "warn"}

INTRO = """<h1>Praćenje prije eventa</h1>
<p>Od oko <b>14 dana prije</b> svakog većeg eventa iz kalendara bot prati tokene vezane uz taj event (pravi token i
dvije najjače kopije s <a href=/events>Eventi</a>). <b>Svaki sat</b> sprema snimku s DexScreenera (cijena, likvidnost,
volumen, broj kupnji i prodaja), a <b>svakih 6 sati</b> preko Heliusa dohvati tko je kupio i usporedi te wallete s
<a href=/wallets>registrom walleta</a> (smart = tier A, B ili S; loši = bot, rugger, bundler, insider, sniper…).
Praćenje završava dan nakon eventa.</p>"""

CORR_HELP = "<h2>Korelacija s približavanjem eventa</h2>" + tdesc("""Jedan red po tokenu. Brojevi su Spearmanova korelacija od −1 do +1 između „koliko je event blizu” i
mjerene veličine kroz sve snimke: <b>+1</b> znači da stalno raste kako se event bliži, <b>0</b> da nema veze,
<b>−1</b> da pada. Treba barem 6 snimki (oko 6 sati) za zaključak; za stupce s walletima barem 4 provjere walleta
(oko jedan dan). <i>Volumen</i> je volumen zadnjeg sata, <i>Kupnje</i> broj kupnji u zadnjem satu, <i>Novi kupci</i>
walleti koji su prvi put kupili između dvije provjere, <i>Smart</i> koliko je od njih smart. <i>Promjena vol.</i> je
satni volumen sada naspram prve snimke. Klik na zaglavlje sortira.""")

SNAP_HELP = "<h2>Zadnje snimke</h2>" + tdesc("""Najnovija snimka svakog praćenog tokena. <i>Do eventa</i> je u danima (negativno = event je prošao).
Stupci s walletima su prazni dok Helius provjera ne prođe.""")

BUYER_HELP = "<h2>Kupci praćenih tokena</h2>" + tdesc("""Svaki wallet koji je kupio praćeni token, s tierom i oznakama iz registra walleta. <i>Dana prije eventa</i>
govori koliko je rano ušao. Smart walleti koji ulaze rano i u više tokena istog eventa najjači su signal.""")


def _q(sql, args=()):
    return data.q(WATCH_DB, sql, args)


def _verdict(v):
    return badge(v, VERDICT_KIND.get(v, "")) if v else "–"


def page(qs):
    corr = _q("SELECT * FROM watch_correlation ORDER BY event_date, corr_volume DESC")
    rows = [[esc(c["event"]), esc(c["event_date"]), tlink(c["token"], c["symbol"]), num(c["n"]),
             signed(c["corr_volume"]), signed(c["corr_buys"]), signed(c["corr_buyers"]), signed(c["corr_smart"]),
             signed(c["corr_price"]), signed(c["vol_change"], "{:+.0f}%"), num(c["buyers_total"]),
             num(c["smart_total"]), num(c["bad_total"]), _verdict(c["verdict"])] for c in corr]
    corr_t = table(["Event", "Datum", "Token", ("Snimki", "n"), ("Volumen", "n"), ("Kupnje", "n"),
                    ("Novi kupci", "n"), ("Smart", "n"), ("Cijena", "n"), ("Promjena vol.", "n"),
                    ("Kupaca", "n"), ("Smart kupaca", "n"), ("Loših", "n"), "Zaključak"], rows, "wc",
                   empty="Još nema praćenih tokena. Bot ih počinje pratiti sam kad u kalendaru ima eventa s tokenima.")

    snaps = _q("SELECT s.*, w.symbol, w.event, w.url FROM watch_snapshots s JOIN watch_tokens w "
               "ON w.token=s.token AND w.event_date=s.event_date "
               "WHERE s.ts = (SELECT MAX(ts) FROM watch_snapshots x WHERE x.token=s.token AND x.event_date=s.event_date) "
               "ORDER BY s.days_to_event")
    srows = [[esc(s["event"]), tlink(s["token"], s["symbol"]), num(s["days_to_event"], "{:.1f}"), usd(s["mcap"]),
              usd(s["liquidity"]), usd(s["vol_h1"]), usd(s["vol_h24"]), num(s["buys_h1"]), num(s["sells_h1"]),
              num(s["new_buyers"]), num(s["smart_buyers"]), num(s["bad_buyers"]), ts(s["ts"]),
              ext_token(s["token"], s["url"])] for s in snaps]
    snap_t = table(["Event", "Token", ("Do eventa", "n"), ("MCap", "n"), ("Likvidnost", "n"), ("Vol 1h", "n"),
                    ("Vol 24h", "n"), ("Kupnje 1h", "n"), ("Prodaje 1h", "n"), ("Novi kupci", "n"), ("Smart", "n"),
                    ("Loši", "n"), "Snimljeno", "Linkovi"], srows, "ws")

    buyers = _q("SELECT b.*, w.symbol FROM watch_buyers b LEFT JOIN (SELECT DISTINCT token, symbol FROM watch_tokens) w "
                "ON w.token=b.token ORDER BY (b.tier IN ('A','B','S')) DESC, b.days_to_event DESC LIMIT 500")
    brows = [[wlink(b["wallet"]), tierb(b["tier"]), esc(", ".join(json.loads(b["labels"] or "[]"))),
              tlink(b["token"], b["symbol"]), num(b["days_to_event"], "{:.1f}"), num(b["sol_in"], "{:.2f}"),
              num(b["buys"]), ts(b["first_ts"])] for b in buyers]
    buy_t = table(["Wallet", "Tier", "Oznake", "Token", ("Dana prije eventa", "n"), ("SOL uloženo", "n"),
                   ("Kupnji", "n"), "Prva kupnja"], brows, "wb")

    return "Praćenje prije eventa", (INTRO + CORR_HELP + filt("wc", "Filtriraj event, token…") + corr_t
                                     + SNAP_HELP + snap_t + BUYER_HELP + filt("wb", "Filtriraj wallet, token…") + buy_t)
