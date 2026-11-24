"""/izvori until 19.11.2026: Telegram channels, KOL wallets and the convergence of sources. 19.11. (vlasnik: "Makni
Telegram KOL-ove iz izračuna ... samo informativni popis"): the page redirects to /telegram-kanali (ui/tgkanali.py,
run_ui.py); what stays here is the free / paid sources table that /usage shows (admins only)."""
import json
import os
import sqlite3

from ui.html import badge, table, tdesc

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _ro(name):
    path = os.path.join(HERE, name)
    if not os.path.exists(path) or not os.path.getsize(path):
        return None
    return sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=10)


def _q(con, sql, args=()):
    if con is None:
        return []
    try:
        return con.execute(sql, args).fetchall()
    except sqlite3.OperationalError:
        return []


def paid_section():
    """Free and paid sources with which keys are set: shown on /usage (admins only)."""
    kcon = _ro("kol.db")
    try:
        return ("<h2 id=placeni>Besplatni i plaćeni izvori</h2>" + tdesc(
            "Kombiniramo oboje: besplatni daju širinu, plaćeni brzinu i doseg. Plaćeni se uključuju samim postavljanjem "
            "ključa na Renderu.") + paid_sources(kcon))
    finally:
        if kcon:
            kcon.close()


def paid_sources(kcon):
    """Free and paid sources side by side, what each adds and whether it is on."""
    on = lambda k: bool(os.environ.get(k))
    hook = json.loads((_q(kcon, "SELECT value FROM kv WHERE key='chain_hook'") or [("{}",)])[0][0])
    rows = [
        ["Telegram web prikaz (t.me/s)", badge("besplatno", "good"), badge("jednom tjedno", "good"),
         "Od 19.11. samo broj pratitelja kanala s popisa (zaglavlje stranice), jednom tjedno; poruke se ne čitaju"],
        ["KOLscan lista", badge("besplatno", "good"), badge("uključeno", "good"), "KOL novčanici s X i Telegram imenom"],
        ["Solana Tracker KOL API", badge("plaćeno"), badge("uključeno", "good") if on("SOLANATRACKER_API_KEY") else badge("čeka SOLANATRACKER_API_KEY", "warn"),
         "Svi praćeni KOL novčanici s PnL-om, ne samo dnevni top"],
        ["Helius webhook KOL novčanika", badge("Helius krediti"),
         badge(f"prati {len(hook.get('wallets', []))}", "good") if hook.get("id") else badge("čeka prvi krug", "warn"),
         "Kupnje i prodaje KOL novčanika u sekundi, prije objave"],
        ["PumpPortal živi tok (pump.fun, PumpSwap)", badge("besplatno", "good"), _live_badge(),
         "Svaka kupnja i prodaja gledanih tokena i praćenih novčanika u sekundi, svaki novi token; demo prodaje na dump u sekundama"],
        ["FOMO top traderi (Apify)", badge("plaćeno"), badge("uključeno", "good") if on("APIFY_TOKEN") else badge("nema APIFY_TOKEN", "bad"),
         "Najbolji traderi koje FOMO korisnici kopiraju, tjedno; njihove kupnje prati webhook"],
        ["pump.fun live i KOL boardovi (Apify)", badge("plaćeno"), badge("uključeno", "good") if on("APIFY_TOKEN") else badge("nema APIFY_TOKEN", "bad"),
         "Tokeni koji se upravo streamaju i koje trguju poznati KOL novčanici"],
    ]
    return table(["Izvor", "Cijena", "Stanje", "Što daje"], rows)


def _live_badge():
    try:
        from live import pulse, store as lstore
        con = lstore.ro()
        if con is None:
            return badge("čeka prvi trade", "warn")
        try:
            st = pulse.status(con)
        finally:
            con.close()
    except Exception:  # noqa: BLE001
        return badge("?", "warn")
    age = st["last_trade_age_s"]
    if age is None:
        return badge("čeka prvi trade", "warn")
    if age > 600:
        return badge(f"zadnji trade prije {age / 60:.0f} min", "bad")
    return badge(f"živ, {st['trades_24h']:,} tradeova u 24 h, {st['tokens']} tokena", "good")


def _tg_history():
    """kol/tg_history.json rows by channel (Nicholas's Call Analyser + SpyDefi exports), {} if missing. Kept only for
    ui/kol.py (/kol/tg:<chan>, the navigation agent's file) until that page drops its Telegram history; listed in the
    cleanup inventory (19.11.)."""
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "kol", "tg_history.json")
    try:
        with open(path) as f:
            return {r["chan"].lower(): r for r in json.load(f).get("rows") or []}
    except (OSError, ValueError):
        return {}

