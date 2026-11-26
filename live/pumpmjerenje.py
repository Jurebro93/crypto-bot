"""Pump mjerenje (25.11., vlasnik: „mjerenje da”, jednokratno, besplatno, 48 h): koliko naknade dobije dev (kreator)
pump.fun tokena, ovisno o tome je li sam kupio na lansiranju i koliko je tokena lansirao u zadnja 24 h. Ništa se ne
lansira, ne kupuje i ne objavljuje; ništa odavde ne čita nijedan posao koji odlučuje o trgovanju ili skenira tokene.

Prekidač: env PUMP_MJERENJE_DO=<unix ts kraja>. Zadano isključeno (nema varijable = ništa se ne događa). Rok dalji od
MAX_TRAJANJE_S od sada je greška u upisu: isključeno. Nakon roka: nema pretplate, nema upita; jedan završni sažetak;
7 dana nakon roka baza se briše (KEEP_AFTER_S).

  live/pumpportal.run   dok mjerenje traje, na POSTOJEĆOJ vezi šalje i subscribeNewToken (besplatno) unatoč fokusu
                        midcap; poruke `create` idu samo u vlastitu bazu (pump_mjerenje.db), nikad u live_launches
                        (skener, precall, teme, učenje), ako je fokus uključen
  tick (start.sh, 10 min)  ishod bez plaćenih podataka: DexScreener /tokens/v1 u serijama od 30 na kontrolnim točkama
                        +1 h i +12 h (zašto: dok je token mlađi od 24 h, DexScreenerov volume.h24 je CIJELI promet od
                        lansiranja; +12 h je najkasnija točka koja stane u 48 h prozor uz 36 h lansiranja s ishodom,
                        a +1 h hvata tokene koji umru odmah), red u logu svakih 6 h, završni sažetak na kraju roka
  sazetak()             tablica po razredima deva za dnevni izvještaj (report/collect.pump_mjerenje)

Naknada kreatoru: 0,30 % prometa na krivulji, POTVRĐENO s lanca 25.11.2026. (protokol 0,95 %, ukupno 1,25 %; službeni
izvor https://pump.fun/docs/fees nije bio dohvatljiv iz sandboxa). Sekundarni izvori (coinpaprika.com/education/launchpad-fees, rujan 2026.;
blockworks „dynamic fee model”) navode da na PumpSwapu nakon migracije stopa ovisi o mcapu: zato su migrirani tokeni
posebno označeni i njihova procjena je najnesigurnija.

Adrese devova su samo u bazi; ništa ovdje ih ne ispisuje.

    python3 -m live.pumpmjerenje tick        # posao iz start.sh (bez varijable i baze: odmah izlazi)
    python3 -m live.pumpmjerenje sazetak     # sažetak sada (samo čita bazu)
"""
import hashlib
import json
import math
import os
import sqlite3
import statistics
import sys
import time

ENV = "PUMP_MJERENJE_DO"
MAX_TRAJANJE_S = 72 * 3600          # rok dalji od ovoga od sada = greška u upisu (vlasnik je odobrio 48 h)
CHECKS = ((1, 3600, 3 * 3600), (12, 12 * 3600, 20 * 3600))   # (oznaka h, kada, najkasnije: kasnije = propušteno)
CREATOR_RATE = 0.003                # 0,30 % prometa na krivulji (potvrđeno s lanca 25.11.2026.)
RATE_NOTE = "0,30 % prometa na krivulji, potvrđeno s lanca 25.11.2026.; za bondane tokene procjena je gruba"
SLUZBENI_URL = "https://pump.fun/docs/fees"   # pokušano 25.11.2026., nedohvatljivo iz sandboxa
MAX_ROWS = int(os.environ.get("PUMP_MJERENJE_MAX_REDAKA", "150000"))   # tvrdi strop lansiranja u bazi
MAX_MB = float(os.environ.get("PUMP_MJERENJE_MAX_MB", "80"))           # tvrdi strop veličine baze (s WAL-om)
DEX_DAY = int(os.environ.get("PUMP_MJERENJE_DEX_DAN", "3000"))          # DexScreener zahtjeva dnevno (UTC)
DEX_PASS = int(os.environ.get("PUMP_MJERENJE_DEX_PROLAZ", "60"))       # zahtjeva po prolazu (10 min)
KEEP_AFTER_S = 7 * 86400            # čišćenje 7 dana nakon kraja
LINE_EVERY_S = 6 * 3600             # red u logu
MIN_N = 30                          # razred s manje tokena: „premalo”
THRESHOLDS = (5_000, 10_000, 30_000, 100_000)
FLUSH_S = 5.0
NO_BUY_SOL = 0.001                  # initial_sol ispod ovoga = bez vlastite kupnje


def _data_dir():
    try:
        from ops import disk
        return disk.DATA_DIR
    except Exception:  # noqa: BLE001
        return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def db_path():
    return os.environ.get("PUMP_MJERENJE_DB") or os.path.join(_data_dir(), "pump_mjerenje.db")


def deadline(env=None):
    """Unix ts kraja iz PUMP_MJERENJE_DO, 0 = isključeno (nema, nečitljivo)."""
    env = os.environ if env is None else env
    try:
        return int(float((env.get(ENV) or "").strip() or 0))
    except ValueError:
        return 0


def active(now=None, env=None):
    """True dok mjerenje traje: rok postavljen, još nije prošao i nije dalji od MAX_TRAJANJE_S."""
    dl, now = deadline(env), now or time.time()
    return bool(dl) and now < dl <= now + MAX_TRAJANJE_S


def u_of(mint):
    """Deterministički broj 0..1 po mintu (uzorak: token je u uzorku kad je u < udio)."""
    return int(hashlib.sha1(mint.encode()).hexdigest()[:8], 16) / 2 ** 32


SCHEMA = """
CREATE TABLE IF NOT EXISTS launches (
    mint TEXT PRIMARY KEY, ts INTEGER, creator TEXT, initial_sol REAL, initial_tokens REAL, mcap_sol REAL, pool TEXT,
    mayhem INTEGER, dev_24h INTEGER, hist_s INTEGER, u REAL) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS launches_creator_ts ON launches (creator, ts);
CREATE INDEX IF NOT EXISTS launches_ts ON launches (ts);
CREATE TABLE IF NOT EXISTS ishod (
    mint TEXT, k INTEGER, ts INTEGER, found INTEGER, vol_usd REAL, txns INTEGER, mcap_usd REAL, max_mcap_usd REAL,
    migrated INTEGER, sol_usd REAL, PRIMARY KEY (mint, k)) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS stanje (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS imena (mint TEXT PRIMARY KEY, name TEXT, symbol TEXT, tema TEXT) WITHOUT ROWID;
"""
# 25.11. (vlasnik: teza da se tokeni kupuju zbog sezone i nadolazećih tema): ime i simbol svakog lansiranja i tema
# iz ključnih riječi, da se sezonska imena usporede s ostalima na tisućama TUĐIH lansiranja (bez ikakve promocije).
TEME = (("Dan zahvalnosti", ("thanksgiving", "turkey", "gobble", "pilgrim", "stuffing", "thankful")),
        ("Black Friday / Cyber Monday", ("black friday", "blackfriday", "cyber monday", "cybermonday", "doorbuster")),
        ("Božić", ("christmas", "xmas", "santa", "reindeer", "rudolph", "grinch", "noel", "navidad", "snowman",
                   "jingle", "mistletoe")),
        ("Nova godina", ("new year", "newyear", "2027")))
SEZONSKA, NIJE_SEZONSKA = "tema imena: sezonska (sve)", "tema imena: nije sezonska"


def tema(name, symbol=""):
    """Sezonska tema imena ili simbola (prva koja pogodi) ili "". Samo ključne riječi; bez mreže."""
    t = f"{name or ''} {symbol or ''}".lower()
    for naziv, rijeci in TEME:
        if any(w in t for w in rijeci):
            return naziv
    return ""

# found: 1 DexScreener zna token (promet u USD), 0 ne zna (bez prometa / nepoznat), 2 zna ali bez USD cijene
# (DexScreener ga zna, ali ne daje promet; uzrok nije utvrđen), -1 kontrolna točka propuštena (posao nije radio na vrijeme)


def connect(path=None):
    con = sqlite3.connect(path or db_path(), timeout=30, isolation_level=None)
    con.execute("PRAGMA busy_timeout = 30000")
    con.execute("PRAGMA journal_mode = WAL")
    con.executescript(SCHEMA)
    return con


def get(con, key, default=None):
    r = con.execute("SELECT value FROM stanje WHERE key=?", (key,)).fetchone()
    return r[0] if r else default


def put(con, key, value):
    con.execute("INSERT OR REPLACE INTO stanje VALUES (?, ?)", (key, str(value)))


def size_mb(path=None):
    p = path or db_path()
    return sum(os.path.getsize(p + s) for s in ("", "-wal") if os.path.exists(p + s)) / 1e6


# ---------- bilježenje lansiranja (proces live) ------------------------------------------------------------------------

class Biljeznik:
    """Sakuplja poruke `create` i piše ih u vlastitu bazu (jednom u FLUSH_S). Nikad ne baca iznimku u tok."""

    def __init__(self, dl, path=None, log=print):
        self.dl, self.path, self.log = int(dl), path or db_path(), log
        self.rows, self.con, self.n, self.full, self.last = [], None, None, False, 0.0
        self.names = []   # (mint, ime, simbol, tema) uz self.rows
        self.n_new = 0

    @classmethod
    def iz_okoline(cls, log=print, env=None, now=None, path=None):
        """Bilježnik dok mjerenje traje, inače None (zadano: isključeno)."""
        return cls(deadline(env), path=path, log=log) if active(now, env) else None

    def active(self, now=None):
        return (now or time.time()) < self.dl

    def take(self, msg, now=None):
        """Jedna poruka toka; zapisuje samo `create` dok rok traje. True = uzeto."""
        now = int(now or time.time())
        if self.full or not self.active(now) or not isinstance(msg, dict) or msg.get("txType") != "create":
            return False
        mint = msg.get("mint")
        if not mint:
            return False

        def f(k):
            try:
                return float(msg.get(k) or 0)
            except (TypeError, ValueError):
                return 0.0
        self.rows.append((mint, now, msg.get("traderPublicKey"), round(f("solAmount"), 6), f("initialBuy"),
                          round(f("marketCapSol"), 4), (msg.get("pool") or "pump")[:20],
                          1 if msg.get("is_mayhem_mode") else 0))
        nm, sy = str(msg.get("name") or "")[:60], str(msg.get("symbol") or "")[:20]
        self.names.append((mint, nm, sy, tema(nm, sy)))
        if len(self.rows) > 20000:   # baza dugo zauzeta: ne rasti u memoriji
            self.rows, self.names = self.rows[-20000:], self.names[-20000:]
        return True

    def _open(self):
        if self.con is None:
            self.con = connect(self.path)
            put(self.con, "rok", self.dl)
            self.n = self.con.execute("SELECT COUNT(*) FROM launches").fetchone()[0]
        return self.con

    def flush(self, now=None, force=False):
        now = now or time.time()
        if not self.rows or (not force and now - self.last < FLUSH_S):
            return 0
        self.last = now
        try:
            con = self._open()
            if self.n >= MAX_ROWS or size_mb(self.path) >= MAX_MB:
                self.full, self.rows, self.names = True, [], []
                self.log(f"pump mjerenje: strop dosegnut ({self.n} lansiranja, {size_mb(self.path):.0f} MB); "
                         "nova lansiranja se više ne bilježe, ishod i sažetak rade dalje")
                return 0
            rows, self.rows = self.rows[:MAX_ROWS - self.n], []
            names, self.names = self.names, []
            con.execute("BEGIN IMMEDIATE")
            start = int(get(con, "start") or rows[0][1])
            put(con, "start", start)
            n = 0
            for r in rows:
                cur = con.execute("INSERT OR IGNORE INTO launches VALUES (?,?,?,?,?,?,?,?,NULL,?,?)",
                                  (*r, r[1] - start, u_of(r[0])))
                if cur.rowcount:
                    n += 1
                    if r[2]:
                        c = con.execute("SELECT COUNT(*) FROM launches WHERE creator=? AND ts BETWEEN ? AND ?",
                                        (r[2], r[1] - 86400, r[1])).fetchone()[0]
                        con.execute("UPDATE launches SET dev_24h=? WHERE mint=?", (c, r[0]))
            taken = {r[0] for r in rows}
            con.executemany("INSERT OR IGNORE INTO imena VALUES (?,?,?,?)", [x for x in names if x[0] in taken])
            con.commit()
            self.n += n
            self.n_new += n
            return n
        except sqlite3.Error as e:
            try:
                self.con and self.con.rollback()
            except sqlite3.Error:
                pass
            self.log(f"pump mjerenje: baza ({str(e)[:60]}), {len(self.rows)} redaka odbačeno")
            return 0

    def close(self):
        try:
            self.flush(force=True)
            if self.con is not None:
                self.con.close()
        except Exception:  # noqa: BLE001
            pass
        self.con = None


# ---------- ishod (DexScreener, besplatno) -----------------------------------------------------------------------------

def _num(x):
    try:
        v = float(x)
        return v if math.isfinite(v) else None
    except (TypeError, ValueError):
        return None


WSOL = "So11111111111111111111111111111111111111112"


def aggregate(pairs, mints):
    """{mint: (found, vol_usd, txns, mcap_usd, max_mcap_usd, migrated)} + sol_usd iz parova (priceUsd / priceNative
    parova u SOL-u; bez dodatnog upita). Najviši viđeni mcap = najveći od trenutnog i onih izvedenih iz priceChange
    (m5, h1, h6): donja granica vrha, ne vrh."""
    by = {m: [] for m in mints}
    rates = []
    for p in pairs or []:
        m = ((p or {}).get("baseToken") or {}).get("address")
        if m in by:
            by[m].append(p)
        q = ((p or {}).get("quoteToken") or {}).get("address")
        pu, pn = _num(p.get("priceUsd")), _num(p.get("priceNative"))
        if q == WSOL and pu and pn:
            rates.append(pu / pn)
    out = {}
    for m, ps in by.items():
        if not ps:
            out[m] = (0, None, None, None, None, None)
            continue
        vols = [_num((p.get("volume") or {}).get("h24")) for p in ps]
        tx = sum(int(_num(((p.get("txns") or {}).get("h24") or {}).get(s)) or 0) for p in ps for s in ("buys", "sells"))
        mcaps, peaks = [], []
        for p in ps:
            mc = _num(p.get("marketCap")) or _num(p.get("fdv"))
            if not mc:
                continue
            mcaps.append(mc)
            peaks.append(mc)
            for w in ("m5", "h1", "h6"):
                pc = _num((p.get("priceChange") or {}).get(w))
                if pc is not None and pc > -99.9:
                    peaks.append(mc / (1 + pc / 100))
        mig = int(any((p.get("dexId") or "") != "pumpfun" for p in ps))
        known = [v for v in vols if v is not None]
        if not known:
            out[m] = (2, None, tx, max(mcaps) if mcaps else None, max(peaks) if peaks else None, mig)
        else:
            out[m] = (1, sum(known), tx, max(mcaps) if mcaps else None, max(peaks) if peaks else None, mig)
    return out, (statistics.median(rates) if rates else None)


def _dex_fetch(mints):
    from dexscreener import client   # isti put i limiter kao ostali (280/min, predmemorija, Retry-After)
    return client._get(f"/tokens/v1/solana/{','.join(mints)}", fast=True) or []


def _fallback_sol_usd():
    try:
        from trade import equity
        return (equity.rates() or {}).get("sol_usd")
    except Exception:  # noqa: BLE001
        return None


def _day(now):
    return time.strftime("%Y-%m-%d", time.gmtime(now))


def requests_today(con, now):
    try:
        st = json.loads(get(con, "dex_dan", "{}") or "{}")
    except ValueError:
        st = {}
    return st.get(_day(now), 0), st


def adapt_rate(con, now, log=print):
    """Udio uzorka: 1 dok procijenjeni zahtjevi dnevno (2 točke × lansiranja / 30) stanu u DEX_DAY, inače manji.
    Samo pada (ugniježđeni uzorak: u < udio), pa tokeni ranije u uzorku ostaju dosljedni."""
    rate = float(get(con, "udio", "1") or 1)
    n6 = con.execute("SELECT COUNT(*) FROM launches WHERE ts >= ?", (int(now) - 6 * 3600,)).fetchone()[0]
    per_day = n6 * 4
    need = len(CHECKS) * per_day * rate / 30
    if per_day and need > DEX_DAY:
        new = max(0.01, round(DEX_DAY * 30 / (len(CHECKS) * per_day) * 0.9, 3))
        if new < rate:
            log(f"pump mjerenje: ~{per_day} lansiranja dnevno traži {need:.0f} DexScreener zahtjeva > {DEX_DAY}: "
                f"uzorak {rate:.0%} → {new:.0%} (slučajno po mintu)")
            rate = new
            put(con, "udio", rate)
    return rate


def check_pass(con, now, fetch=None, log=print):
    """Jedan prolaz kontrolnih točaka. Vraća broj DexScreener zahtjeva."""
    fetch = fetch or _dex_fetch
    rate = adapt_rate(con, now, log)
    done, _ = requests_today(con, now)
    n_req = 0
    for k, off, late in sorted(CHECKS, key=lambda c: -c[1]):   # +12 h prvi (važniji)
        # propuštene (posao nije radio na vrijeme): zabilježi da se ne pokušavaju i broje posebno
        con.execute("""INSERT OR IGNORE INTO ishod (mint, k, ts, found) SELECT l.mint, ?, ?, -1 FROM launches l
                       LEFT JOIN ishod i ON i.mint = l.mint AND i.k = ? WHERE i.mint IS NULL AND l.u < ? AND l.ts < ?""",
                    (k, int(now), k, rate, int(now) - late))
        while n_req < DEX_PASS and done + n_req < DEX_DAY:
            mints = [r[0] for r in con.execute(
                """SELECT l.mint FROM launches l LEFT JOIN ishod i ON i.mint = l.mint AND i.k = ?
                   WHERE i.mint IS NULL AND l.u < ? AND l.ts <= ? ORDER BY l.ts LIMIT 30""",
                (k, rate, int(now) - off))]
            if not mints:
                break
            try:
                pairs = fetch(mints)
            except Exception as e:  # noqa: BLE001 - sljedeći prolaz
                log(f"pump mjerenje: DexScreener {type(e).__name__}: {str(e)[:80]}")
                n_req += 1
                break
            n_req += 1
            res, sol_usd = aggregate(pairs, mints)
            con.executemany("INSERT OR IGNORE INTO imena VALUES (?,?,?,?)", _names_of(pairs, mints))
            sol_usd = sol_usd or _fallback_sol_usd()
            con.executemany("INSERT OR REPLACE INTO ishod VALUES (?,?,?,?,?,?,?,?,?,?)",
                            [(m, k, int(now), *res[m][:3], res[m][3], res[m][4], res[m][5], sol_usd) for m in mints])
    put(con, "dex_dan", json.dumps({_day(now): done + n_req}))   # samo današnji dan
    tot = json.loads(get(con, "dex_ukupno", "{}") or "{}")
    tot[_day(now)] = tot.get(_day(now), 0) + n_req
    put(con, "dex_ukupno", json.dumps(tot))
    return n_req


def _names_of(pairs, mints):
    """Ime i simbol iz DexScreener parova, za lansiranja zabilježena prije nego što je mjerenje pamtilo imena."""
    want, out = set(mints), {}
    for p in pairs or []:
        b = (p or {}).get("baseToken") or {}
        m = b.get("address")
        if m in want and m not in out and (b.get("name") or b.get("symbol")):
            nm, sy = str(b.get("name") or "")[:60], str(b.get("symbol") or "")[:20]
            out[m] = (m, nm, sy, tema(nm, sy))
    return list(out.values())


# ---------- sažetak -----------------------------------------------------------------------------------------------------

def _cls(name, fees, peaks, mig, unknown, nousd):
    n = len(fees)
    tot = sum(fees)
    top = sorted(fees, reverse=True)[:max(1, math.ceil(n * 0.01))] if n else []
    return {"razred": name, "n": n, "premalo": n < MIN_N, "medijan_sol": statistics.median(fees) if n else None,
            "prosjek_sol": tot / n if n else None, "ukupno_sol": tot,
            "iznad": {t: (sum(1 for p in peaks if p >= t) / n if n else None) for t in THRESHOLDS},
            "migrirao": (sum(mig) / n) if n else None,
            "gornjih_1_posto": (sum(top) / tot if tot > 0 else None), "nepoznato": unknown, "bez_usd": nousd}


SPECIAL = "nepoznat dev, bez kupnje, prvi token"
OSTAVLJEN = "bez kupnje deva, nije bondan (ostavljen token)"


def sazetak(con, now=None, final=False):
    """Statistika po razredima deva. Konačno (final): samo tokeni s ishodom +12 h. Privremeno: najkasniji dostupni
    ishod po tokenu. Iterira kursorom; u memoriji drži samo liste brojeva po razredu (za medijan i gornjih 1 %)."""
    now = int(now or time.time())
    rate = float(get(con, "udio", "1") or 1)
    start = int(get(con, "start") or 0)
    rok = int(get(con, "rok") or 0)
    sol_fb = None
    n_all = con.execute("SELECT COUNT(*) FROM launches").fetchone()[0]
    ks = (12,) if final else (12, 1)
    groups = {}
    missed = con.execute("SELECT COUNT(*) FROM ishod WHERE found = -1 AND k = 12").fetchone()[0]
    seen = 0
    for ini, dev, hist, mcap_sol, k, found, vol, peak, mig, sol_usd, tm, mayhem in _rows(con, ks, rate):
        seen += 1
        if sol_usd is None:
            sol_fb = sol_fb or _fallback_sol_usd() or 0
            sol_usd = sol_fb
        dev = dev or 1
        buy = "bez kupnje" if (ini or 0) < NO_BUY_SOL else "do 0,5 SOL" if ini <= 0.5 else "0,5–2 SOL" if ini <= 2 \
            else "iznad 2 SOL"
        cnt = "1 (prvi u 24 h)" if dev <= 1 else "2–9" if dev < 10 else "10+"
        names = ["svi", f"vlastita kupnja: {buy}", f"tokena deva u 24 h: {cnt}"]
        if dev <= 1 and (ini or 0) < NO_BUY_SOL:
            names.append(SPECIAL)
            if (hist or 0) >= 86400:
                names.append(SPECIAL + " (puna 24 h povijest)")
        if tm is not None:   # ime poznato (iz toka ili s DexScreenera)
            names += [SEZONSKA, f"tema imena: {tm}"] if tm else [NIJE_SEZONSKA]
            if (ini or 0) < NO_BUY_SOL and not mig:
                names.append(f"{OSTAVLJEN}, {SEZONSKA if tm else NIJE_SEZONSKA}")
        names.append("Mayhem Mode: da" if mayhem else "Mayhem Mode: ne")
        if (ini or 0) < NO_BUY_SOL and not mig:
            # 25.11. (vlasnik: "nemoj mjeriti bondane ... token launcham besplatno iz nule i ako ga se ostavi")
            names += [OSTAVLJEN, f"{OSTAVLJEN}, tokena deva u 24 h: {cnt}"]
        for nm in names:
            g = groups.setdefault(nm, {"fees": [], "peaks": [], "mig": [], "unknown": 0, "nousd": 0})
            if found == 2:
                g["nousd"] += 1
                continue
            if found == 0:
                g["unknown"] += 1
            fee = (vol or 0) * CREATOR_RATE / sol_usd if sol_usd else 0.0
            g["fees"].append(fee)
            g["peaks"].append(max(peak or 0, (mcap_sol or 0) * (sol_usd or 0)))
            g["mig"].append(mig or 0)
    order = ["svi", OSTAVLJEN, f"{OSTAVLJEN}, tokena deva u 24 h: 1 (prvi u 24 h)",
             f"{OSTAVLJEN}, tokena deva u 24 h: 2–9", f"{OSTAVLJEN}, tokena deva u 24 h: 10+",
             SEZONSKA, NIJE_SEZONSKA, *[f"tema imena: {t[0]}" for t in TEME],
             f"{OSTAVLJEN}, {SEZONSKA}", f"{OSTAVLJEN}, {NIJE_SEZONSKA}", "Mayhem Mode: da", "Mayhem Mode: ne",
             SPECIAL, SPECIAL + " (puna 24 h povijest)",
             "tokena deva u 24 h: 1 (prvi u 24 h)", "tokena deva u 24 h: 2–9", "tokena deva u 24 h: 10+",
             "vlastita kupnja: bez kupnje", "vlastita kupnja: do 0,5 SOL", "vlastita kupnja: 0,5–2 SOL",
             "vlastita kupnja: iznad 2 SOL"]
    rows = [_cls(nm, groups[nm]["fees"], groups[nm]["peaks"], groups[nm]["mig"], groups[nm]["unknown"],
                 groups[nm]["nousd"]) for nm in order if nm in groups]
    tot = json.loads(get(con, "dex_ukupno", "{}") or "{}")
    days = max(1.0, (min(now, rok or now) - start) / 86400) if start else 1.0
    return {"final": final, "ts": now, "start": start, "rok": rok, "lansiranja": n_all, "udio": rate,
            "s_ishodom": seen, "propusteno_12h": missed, "razredi": rows,
            "dex_zahtjeva": sum(tot.values()), "dex_dnevno": round(sum(tot.values()) / days),
            "lansiranja_dnevno": round(n_all / days) if start else None, "mb": round(_con_mb(con), 1),
            "stopa": RATE_NOTE, "izvor": SLUZBENI_URL}


def _con_mb(con):
    try:
        f = con.execute("PRAGMA database_list").fetchone()[2]
        return size_mb(f) if f else 0.0
    except (sqlite3.Error, OSError):
        return 0.0


def _rows(con, ks, rate):
    """Po tokenu jedan red: najkasniji dostupni ishod (k silazno)."""
    sql = f"""SELECT l.mint, l.initial_sol, l.dev_24h, l.hist_s, l.mcap_sol, i.k, i.found, i.vol_usd, i.max_mcap_usd,
                     i.migrated, i.sol_usd, n.tema, l.mayhem
              FROM launches l JOIN ishod i ON i.mint = l.mint AND i.k IN ({",".join("?" * len(ks))}) AND i.found >= 0
              LEFT JOIN imena n ON n.mint = l.mint
              WHERE l.u < ? ORDER BY l.mint, i.k DESC"""
    last = None
    for r in con.execute(sql, (*ks, rate)):
        if r[0] == last:
            continue
        last = r[0]
        yield r[1:]


def _pct(x):
    return "–" if x is None else f"{x * 100:.1f} %".replace(".", ",")


def _sol(x):
    return "–" if x is None else f"{x:.4f}".replace(".", ",")


def line(s):
    """Jedan red za log: „pump mjerenje: ...” (bez adresa)."""
    head = "pump mjerenje" + (" (završno)" if s["final"] else "") + ": "
    rs = {r["razred"]: r for r in s["razredi"]}
    a = rs.get("svi")
    sp = rs.get(SPECIAL)
    out = (f"{head}{s['lansiranja']} lansiranja (uzorak {_pct(s['udio'])}, s ishodom {s['s_ishodom']}"
           + (", samo +12 h" if s["final"] else ", najkasniji ishod") + ")")
    if a and a["n"]:
        out += (f"; naknada kreatoru po tokenu medijan {_sol(a['medijan_sol'])} SOL, prosjek {_sol(a['prosjek_sol'])} "
                f"SOL (n={a['n']}); iznad 10k $ {_pct(a['iznad'][10_000])}, iznad 30k $ {_pct(a['iznad'][30_000])}; "
                f"gornjih 1 % tokena nosi {_pct(a['gornjih_1_posto'])} naknade; DexScreener ne zna {a['nepoznato']}"
                f"; bez USD prometa (DexScreener ne daje promet, izvan brojki) {a['bez_usd']}")
    if sp and sp["n"]:
        out += (f"; {SPECIAL}: n={sp['n']}{' (premalo)' if sp['premalo'] else ''}, medijan {_sol(sp['medijan_sol'])} "
                f"SOL, prosjek {_sol(sp['prosjek_sol'])} SOL")
    for nm in (SEZONSKA, NIJE_SEZONSKA, "Mayhem Mode: da", "Mayhem Mode: ne"):
        o = rs.get(nm)
        if o and o["n"]:
            out += (f"; {nm}: n={o['n']}{' (premalo)' if o['premalo'] else ''}, medijan {_sol(o['medijan_sol'])} SOL, "
                    f"prosjek {_sol(o['prosjek_sol'])} SOL, iznad 10k $ {_pct(o['iznad'][10_000])}")
    for nm in (OSTAVLJEN, f"{OSTAVLJEN}, tokena deva u 24 h: 10+"):
        o = rs.get(nm)
        if o and o["n"]:
            out += (f"; {nm}: n={o['n']}{' (premalo)' if o['premalo'] else ''}, medijan {_sol(o['medijan_sol'])} SOL, "
                    f"prosjek {_sol(o['prosjek_sol'])} SOL po tokenu (na 100 tokena {_sol(o['prosjek_sol'] * 100)} SOL "
                    "bruto, prije troška lansiranja)")
    out += f"; DexScreener ~{s['dex_dnevno']} zahtjeva dnevno; baza {str(s['mb']).replace('.', ',')} MB; {s['stopa']}"
    return out


def table_rows(s):
    """[(razred, n, medijan, prosjek, ≥5k, ≥10k, ≥30k, ≥100k, migrirao, gornjih 1 %, nepoznato, bez USD)]."""
    out = []
    for r in s["razredi"]:
        nm = r["razred"] + (" — premalo" if r["premalo"] else "")
        out.append((nm, str(r["n"]), _sol(r["medijan_sol"]), _sol(r["prosjek_sol"]),
                    *[_pct(r["iznad"][t]) for t in THRESHOLDS], _pct(r["migrirao"]), _pct(r["gornjih_1_posto"]),
                    str(r["nepoznato"]), str(r["bez_usd"])))
    return out


def report(now=None, path=None):
    """Za report/collect: sažetak ili None (nema baze). Samo čita."""
    p = path or db_path()
    if not os.path.exists(p):
        return None
    try:
        con = sqlite3.connect(f"file:{p}?mode=ro", uri=True, timeout=10)
        try:
            now = int(now or time.time())
            rok = int(get(con, "rok") or 0)
            return sazetak(con, now, final=bool(rok) and now >= rok)
        finally:
            con.close()
    except sqlite3.Error:
        return None


# ---------- posao (start.sh, svakih 10 min) ----------------------------------------------------------------------------

def tick(now=None, fetch=None, log=print, env=None, path=None):
    """Ishod, red u logu svakih 6 h, završni sažetak, čišćenje 7 dana nakon roka. Bez varijable i bez baze: ništa."""
    now = int(now or time.time())
    p = path or db_path()
    on = active(now, env)
    if not on and not os.path.exists(p):
        return 0
    con = connect(p)
    try:
        rok = deadline(env) if on else int(get(con, "rok") or deadline(env) or 0)
        if on:
            put(con, "rok", rok)
            check_pass(con, now, fetch, log)
            if now - int(get(con, "zadnji_red") or 0) >= LINE_EVERY_S:
                log(line(sazetak(con, now)))
                put(con, "zadnji_red", now)
            return 0
        if rok and now >= rok and not get(con, "kraj"):
            s = sazetak(con, now, final=True)
            log(line(s))
            log("pump mjerenje: rok istekao; nema više pretplate ni upita; baza se briše "
                + time.strftime("%d.%m.%Y. %H:%M UTC", time.gmtime(rok + KEEP_AFTER_S)))
            put(con, "kraj", now)
            put(con, "zavrsni", json.dumps(s))
        if rok and now >= rok + KEEP_AFTER_S:
            con.close()
            con = None
            for suf in ("", "-wal", "-shm"):
                try:
                    os.remove(p + suf)
                except OSError:
                    pass
            log("pump mjerenje: 7 dana nakon kraja, baza obrisana")
        return 0
    finally:
        if con is not None:
            con.close()


def main(argv=None):
    a = list(sys.argv[1:] if argv is None else argv)
    cmd = a[0] if a else "tick"
    log = lambda s: print(s, flush=True)   # noqa: E731
    if cmd == "tick":
        return tick(log=log)
    if cmd == "sazetak":
        s = report()
        log(line(s) if s else "pump mjerenje: nema baze")
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main())
