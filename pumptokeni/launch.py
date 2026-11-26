"""Lansiranje na vlasnikov dodir: red čekanja, stropovi, IPFS metapodaci, create zahtjev, potpis, simulacija, slanje.

Raspored (26.11., vlasnik): svaki nacrt ima termin (CET). „Odobri pilot” odobrava RASPORED (okvir potvrde: termin,
vlastita kupnja, poveznice, ukupni trošak); razmak RAZMAK je samo donja granica između dva lansiranja (bliži termin se
pomiče i to se ispiše). Bez odobrenja se ništa ne lansira, ni kad termin prođe; termin koji je prošao više od
MISSED_S (15 min) prije odobrenja ili obrade se ne nadoknađuje: nacrt dobiva stanje 'propusten' i čeka novo odobrenje.

Tok jednog tokena (posao pumptokeni.posao, jedan po jedan, u terminu):
  1. kill switch (trade/STOP) → ništa; novčanik isključen / nema ključa → ništa (nacrt ostaje u redu)
  2. termin još nije došao → čeka; dnevni strop (DNEVNO, tvrdi max 20) i razmak od zadnjeg poslanog → čeka
  3. čuvari imena ponovno (DexScreener) i provjera poveznica → 'odbijen'
  4. saldo platitelja ≥ MIN_SOL; rezerva: nakon lansiranja mora ostati REZERVA_SOL (0,03); ako bi vlastita kupnja to
     prekršila, lansira se BEZ kupnje (upozorenje u pokušaju, logu i na stranici); ako ni bez kupnje ne ostaje → čeka
  5. slika + JSON na IPFS (Pinata uz PINATA_JWT, prema PumpPortal dokumentaciji 25.11.; inače stari pump.fun/api/ipfs);
     poveznice (twitter, telegram, website) idu u JSON metapodataka, jer ih pump.fun čita s URI-ja
  6. novi mint keypair; mint ZAPISAN u pokusaji prije ikakvog slanja (zabrana samotrgovanja ga vidi odmah)
  7. PumpPortal trade-local: action create, amount = vlastita kupnja (0 ili do 0,1 SOL), denominatedInSol "true",
     pool pump; kupnja je u istoj transakciji lansiranja (javno vidljiva kao devova)
  8. provjera naloga: platitelj prvi potpisnik, točno 2 potpisa (platitelj + mint), poziva pump.fun program,
     priority naknada ≤ PRIORITY_MAX_SOL
  9. potpis mint keypairom i novčanikom; simulateTransaction (sigVerify): mora uspjeti, promjena SOL salda
     platitelja (+ osnovna naknada) ≤ MAX_SOL + kupnja × 1,03, nijedan token račun platitelja ne smije izgubiti ni
     jedan token (smije ih primiti)
 10. slanje kroz isti RPC (trade/wallet.send), potvrda, izmjereni trošak = saldo prije − saldo poslije − kupnja (kupnja
     je vezan kapital u tokenima, ne trošak). Kupljene tokene alat nikad ne prodaje (nema puta prodaje).

Ključevi: PUMP_DEV_PRIVATE_KEY (zasebni novčanik pokusa, preporučeno) ili SOLANA_PRIVATE_KEY (trgovački, samo uz
vlasnikov prekidač trade/settings PUMP_TRGOVACKI potvrđen dodirom). Ključ se nikad ne ispisuje ni ne logira.
"""
import base64
import json
import os
import time
import urllib.request
import uuid

from pumptokeni import guards, own, store

PUMPPORTAL = "https://pumpportal.fun/api/trade-local"
PUMP_IPFS = "https://pump.fun/api/ipfs"
PINATA_UPLOAD = "https://uploads.pinata.cloud/v3/files"
IPFS_GATEWAY = "https://ipfs.io/ipfs/"
PUMP_PROGRAM = "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P"
COMPUTE_BUDGET = "ComputeBudget111111111111111111111111111111"
TOKEN_PROGRAMS = ("TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA", "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb")
UA = "Mozilla/5.0"   # generičan: ništa u zahtjevima za metapodatke ne upućuje na nas

HARD_MAX_DNEVNO = 20        # tvrdi maksimum ove verzije, env ga ne može podići
HARD_MAX_SOL = 0.05         # strop simulacije ni env ne može podići iznad ovoga
PRIORITY_MAX_SOL = 0.0002   # tvrdi strop priority naknade
BASE_FEE_LAMPORTS = 5000    # po potpisu
MAX_TOKEN_ACCOUNTS = 60     # više token računa od ovoga = simulacija ih ne može sve provjeriti: odbij
EXPECTED = (0.0075, 0.0113)   # izmjereno s lanca 25.11. (13 lansiranja bez kupnje): mrežna ~0,0002, ostalo najam računa

OFF, TOOL, SEPARATE, TRADING = "iskljuceno", "alat", "zasebni", "trgovacki"
CHOICES = {TOOL: "Novčanik pokusa stvoren u alatu (zadano)", SEPARATE: "Zasebni novčanik iz env PUMP_DEV_PRIVATE_KEY",
           TRADING: "Trgovački novčanik (SOLANA_PRIVATE_KEY)", OFF: "Isključeno"}
RESERVE_SOL = 0.03          # zadana PUMP_TOKENI_REZERVA_SOL: novčanik mora nakon lansiranja zadržati barem ovoliko
BUY_FEE = 0.0125            # naknada pump.funa na kupnju (protokol 0,95 % + kreator 0,30 %)
BUY_CAP_MULT = 1.03         # čuvar simulacije: kupnja smije stajati najviše kupnja × 1,03 (naknada + proklizavanje)
MISSED_S = 900              # termin prošao više od 15 min prije odobrenja ili obrade: ne nadoknađuje se
BUY_SKIP_WARN = "vlastita kupnja preskočena: rezerva"
PREFLIGHT_MAX_AGE_S = 1800  # pilot se odobrava samo uz zelenu provjeru mlađu od 30 min
CONFIRM_WAIT_S = 90         # čekanje potvrde (getSignatureStatuses do 'confirmed'), zatim 'nepoznato'


def _num(env, name, default, lo, hi, typ=float):
    try:
        v = typ(float((env.get(name) or "").strip() or default))
    except ValueError:
        v = typ(default)
    return max(lo, min(hi, v))


def cfg(env=None):
    env = os.environ if env is None else env
    min_env = (env.get("PUMP_TOKENI_MIN_SOL") or "").strip()
    zas = _num(env, "PUMP_TOKENI_MIN_SOL", 0.03, 0.02, 100.0) if min_env else 0.03
    return {"max_sol": _num(env, "PUMP_TOKENI_MAX_SOL", 0.02, 0.001, HARD_MAX_SOL),
            "dnevno": _num(env, "PUMP_TOKENI_DNEVNO", 5, 0, HARD_MAX_DNEVNO, int),
            "razmak_s": _num(env, "PUMP_TOKENI_RAZMAK_MIN", 10, 1, 24 * 60) * 60,
            "min_sol": {TOOL: zas, SEPARATE: zas, TRADING: max(1.0, _num(env, "PUMP_TOKENI_MIN_SOL", 1.0, 1.0, 100.0))},
            "priority_sol": _num(env, "PUMP_TOKENI_PRIORITY_SOL", 0.00005, 0.0, PRIORITY_MAX_SOL),
            "rezerva_sol": _num(env, "PUMP_TOKENI_REZERVA_SOL", RESERVE_SOL, 0.01, 10.0),
            "ipfs": (env.get("PUMP_TOKENI_IPFS") or ("pinata" if (env.get("PINATA_JWT") or "").strip() else "pumpfun"))
            .strip().lower()}


# ---------- novčanik ---------------------------------------------------------------------------------------------

def _trade_flag_live(tcon=None):
    from trade import settings
    own_con = tcon is None
    tcon = tcon or settings.connect()
    try:
        return settings.flag_state(tcon)[settings.PUMP_TRGOVACKI]["mode"] == "live"
    finally:
        if own_con:
            tcon.close()


def wallet_choice(con, tcon=None):
    """TOOL (zadano), SEPARATE, TRADING ili OFF. Trgovački vrijedi samo dok je vlasnikov prekidač PUMP_TRGOVACKI
    'live'."""
    ch = store.get(con, "novcanik", TOOL)
    if ch == TRADING:
        try:
            return TRADING if _trade_flag_live(tcon) else OFF
        except Exception:  # noqa: BLE001 - a switch that cannot be read is off
            return OFF
    return ch if ch in (TOOL, SEPARATE) else OFF


def set_wallet(con, choice, user, tap=False, tcon=None):
    """Vlasnikov izbor novčanika. Trgovački samo uz njegov potvrđeni dodir (set_flag tap=True)."""
    from trade import settings
    if not settings.is_owner(user):
        raise ValueError("novčanik bira samo vlasnik")
    if choice not in CHOICES:
        raise ValueError("nepoznat izbor novčanika")
    own_con = tcon is None
    tcon = tcon or settings.connect()
    try:
        if choice == TRADING:
            if tap is not True:
                raise ValueError("trgovački novčanik samo uz potvrdu (kvačica i potvrda u okviru)")
            settings.set_flag(tcon, settings.PUMP_TRGOVACKI, "live", user, tap=tap)   # the owner's own tap, passed through
        elif settings.flag_state(tcon)[settings.PUMP_TRGOVACKI]["mode"] != "off":
            settings.set_flag(tcon, settings.PUMP_TRGOVACKI, "off", user)
    finally:
        if own_con:
            tcon.close()
    store.put(con, "novcanik", choice)
    return choice


def _parse_secret(secret):
    from solders.keypair import Keypair
    secret = (secret or "").strip()
    if not secret:
        return None
    if secret.startswith("["):
        return Keypair.from_bytes(bytes(json.loads(secret)))
    return Keypair.from_base58_string(secret)


def keypair(choice, env=None):
    """Keypair izabranog novčanika ili None. Greška parsiranja → None (nikad ne ispisuje ključ)."""
    env = os.environ if env is None else env
    try:
        if choice == TOOL:
            from pumptokeni import devwallet
            return devwallet.keypair(env)
        if choice == SEPARATE:
            return _parse_secret(env.get("PUMP_DEV_PRIVATE_KEY"))
        if choice == TRADING:
            from trade import wallet
            return wallet._keypair()
    except Exception:  # noqa: BLE001 - the key's text never goes anywhere
        return None
    return None


def address(choice, env=None):
    kp = keypair(choice, env)
    return str(kp.pubkey()) if kp else None


# ---------- HTTP (zamjenjivo u testu) ---------------------------------------------------------------------------

def _multipart(fields, file_field, filename, content, ctype):
    b = uuid.uuid4().hex
    out = []
    for k, v in fields.items():
        out.append(f'--{b}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode())
    out.append(f'--{b}\r\nContent-Disposition: form-data; name="{file_field}"; filename="{filename}"\r\n'
               f'Content-Type: {ctype}\r\n\r\n'.encode() + content + b"\r\n")
    out.append(f"--{b}--\r\n".encode())
    return b"".join(out), f"multipart/form-data; boundary={b}"


def http_post(url, body, headers, timeout=30):
    """(status, bytes). Ne baca na HTTP grešku."""
    req = urllib.request.Request(url, body, {"User-Agent": UA, **headers}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()[:500]


def upload_metadata(name, symbol, desc, png, backend="pumpfun", post=None, env=None, links=None):
    """URI JSON metapodataka na IPFS-u: ime, simbol, opis, slika i poveznice nacrta (links {twitter, telegram,
    website}, samo neprazne i već provjerene). Poveznice su polja JSON-a metapodataka (pump.fun ih čita s URI-ja), kao u
    primjeru PumpPortala za pump.fun/api/ipfs (form polja twitter/telegram/website); create zahtjev ih ne nosi."""
    links = {k: v for k, v in (links or {}).items() if k in ("twitter", "telegram", "website") and v}
    env = os.environ if env is None else env
    post = post or http_post
    if backend == "pinata":
        jwt = (env.get("PINATA_JWT") or "").strip()
        if not jwt:
            raise RuntimeError("IPFS: PINATA_JWT nije postavljen")
        auth = {"Authorization": f"Bearer {jwt}"}

        def pin(content, filename, ctype):
            body, ct = _multipart({"network": "public"}, "file", filename, content, ctype)
            st, data = post(PINATA_UPLOAD, body, {**auth, "Content-Type": ct})
            if st != 200:
                raise RuntimeError(f"IPFS (Pinata) {st}: {data[:120]!r}")
            cid = ((json.loads(data) or {}).get("data") or {}).get("cid")
            if not cid:
                raise RuntimeError("IPFS (Pinata): odgovor bez cid")
            return cid
        img = pin(png, "image.png", "image/png")
        meta = {"name": name, "symbol": symbol, "description": desc, "image": IPFS_GATEWAY + img, "showName": True,
                **links}
        return IPFS_GATEWAY + pin(json.dumps(meta, ensure_ascii=False).encode("utf-8"), "metadata.json",
                                  "application/json")
    body, ct = _multipart({"name": name, "symbol": symbol, "description": desc, **links, "showName": "true"}, "file",
                          "image.png", png, "image/png")
    st, data = post(PUMP_IPFS, body, {"Content-Type": ct})
    if st != 200:
        raise RuntimeError(f"IPFS (pump.fun) {st}: {data[:120]!r}")
    try:
        uri = (json.loads(data) or {}).get("metadataUri")
    except ValueError:
        uri = None
    if not uri:
        raise RuntimeError("IPFS (pump.fun): odgovor bez metadataUri")
    return uri


def create_request(payer, mint, name, symbol, uri, priority_sol, kupnja=0):
    """Tijelo create zahtjeva prema PumpPortal trade-local (pumpportal.fun/creation, 25.11.): amount = vlastita kupnja
    u SOL-u (denominatedInSol), u istoj transakciji; 0 = bez kupnje. tokenMetadata nosi samo name, symbol, uri."""
    k = float(kupnja or 0)
    if not 0 <= k <= store.HARD_MAX_KUPNJA + 1e-12:
        raise ValueError(f"vlastita kupnja {k:g} SOL izvan 0–{store.HARD_MAX_KUPNJA:g}")
    return {"publicKey": payer, "action": "create", "tokenMetadata": {"name": name, "symbol": symbol, "uri": uri},
            "mint": mint, "denominatedInSol": "true", "amount": round(k, 6) if k else 0, "slippage": 10,
            "priorityFee": priority_sol, "pool": "pump"}


def sim_cap(c, kupnja):
    """Dopuštena promjena SOL salda platitelja u simulaciji: trošak lansiranja + kupnja × 1,03."""
    return c["max_sol"] + float(kupnja or 0) * BUY_CAP_MULT


def plan_buy(pre, kupnja, c):
    """(kupnja, upozorenje, rezerva_ok) prema saldu prije lansiranja: nakon lansiranja (strop) i kupnje mora ostati
    rezerva; inače bez kupnje; ako ni bez kupnje ne ostaje, rezerva_ok=False (ne lansira se)."""
    k = float(kupnja or 0)
    warn = None
    if k > 0 and pre - sim_cap(c, k) < c["rezerva_sol"] - 1e-12:
        k, warn = 0.0, BUY_SKIP_WARN
    return k, warn, pre - c["max_sol"] >= c["rezerva_sol"] - 1e-12


def create_tx(body, post=None):
    post = post or http_post
    st, data = post(PUMPPORTAL, json.dumps(body).encode(), {"Content-Type": "application/json"})
    if st != 200 or not data or data[:1] in (b"{", b"["):
        raise RuntimeError(f"PumpPortal {st}: {data[:160]!r}")
    return data


# ---------- provjere naloga ---------------------------------------------------------------------------------------

def priority_sol(msg):
    """Priority naknada (SOL) iz ComputeBudget instrukcija poruke: cijena (µlamport/CU) × limit (zadano 200k po ix)."""
    keys = [str(k) for k in msg.account_keys]
    price, limit, n_ix = 0, None, 0
    for ix in msg.instructions:
        n_ix += 1
        if ix.program_id_index >= len(keys) or keys[ix.program_id_index] != COMPUTE_BUDGET:
            continue
        data = bytes(ix.data)
        if data[:1] == b"\x03" and len(data) >= 9:
            price = int.from_bytes(data[1:9], "little")
        elif data[:1] == b"\x02" and len(data) >= 5:
            limit = int.from_bytes(data[1:5], "little")
    limit = limit if limit is not None else 200_000 * n_ix
    return price * limit / 1e6 / 1e9


def check_message(tx, payer, mint, prio_max):
    """Razlog odbijanja (tekst) ili None."""
    msg = tx.message
    n = msg.header.num_required_signatures
    keys = [str(k) for k in msg.account_keys]
    if not keys or keys[0] != payer:
        return "platitelj naloga nije naš novčanik"
    if n != 2 or mint not in keys[:n]:
        return f"nalog traži {n} potpisa (očekivano 2: novčanik i mint)"
    if PUMP_PROGRAM not in keys:
        return "nalog ne poziva pump.fun program"
    p = priority_sol(msg)
    if p > prio_max + 1e-12:
        return f"priority naknada {p:.6f} SOL iznad stropa {prio_max:g}"
    return None


def _token_accounts(rpc, owner):
    out = []
    for prog in TOKEN_PROGRAMS:
        res = rpc("getTokenAccountsByOwner", [owner, {"programId": prog}, {"encoding": "jsonParsed",
                                                                             "commitment": "confirmed"}])
        for a in (res or {}).get("value") or []:
            ta = a["account"]["data"]["parsed"]["info"]["tokenAmount"]
            out.append((a["pubkey"], int(ta["amount"])))
    return out


def _acc_amount(acc):
    try:
        return int(acc["data"]["parsed"]["info"]["tokenAmount"]["amount"])
    except (KeyError, TypeError, ValueError):
        return None


def simulate(rpc, tx_b64, payer, n_sigs, max_sol):
    """{"ok", "why", "sol"}: simulateTransaction prije slanja. sol = saldo prije − saldo poslije simulacije + osnovna
    naknada (konzervativno: ako je simulacija naknadu već odbila, broji se dvaput)."""
    pre = rpc("getBalance", [payer, {"commitment": "confirmed"}])["value"]
    toks = _token_accounts(rpc, payer)
    if len(toks) > MAX_TOKEN_ACCOUNTS:
        return {"ok": False, "why": f"novčanik ima {len(toks)} token računa, provjera ih može najviše "
                                    f"{MAX_TOKEN_ACCOUNTS}", "sol": None}
    addrs = [payer] + [a for a, _ in toks]
    val = rpc("simulateTransaction", [tx_b64, {"encoding": "base64", "sigVerify": True, "replaceRecentBlockhash": False,
                                               "commitment": "confirmed",
                                               "accounts": {"encoding": "jsonParsed", "addresses": addrs}}])["value"]
    if val.get("err") is not None:
        logs = " | ".join((val.get("logs") or [])[-3:])
        return {"ok": False, "why": f"simulacija nije uspjela: {val['err']} {logs}"[:400], "sol": None}
    accs = val.get("accounts") or []
    if len(accs) != len(addrs) or not accs[0]:
        return {"ok": False, "why": "simulacija nije vratila stanje računa", "sol": None}
    sol = (pre - int(accs[0]["lamports"]) + n_sigs * BASE_FEE_LAMPORTS) / 1e9
    for (addr, amt), acc in zip(toks, accs[1:]):
        post = _acc_amount(acc) if acc else None
        if post is None or post < amt:
            return {"ok": False, "why": f"nalog tereti token račun platitelja ({addr[:4]}…)", "sol": sol}
    if sol > max_sol + 1e-12:
        return {"ok": False, "why": f"simulacija: promjena salda {sol:.5f} SOL iznad stropa {max_sol:g} SOL", "sol": sol}
    return {"ok": True, "why": None, "sol": sol}




def programs(msg):
    """Programi koje nalog poziva (statični ključevi poruke)."""
    keys = [str(k) for k in msg.account_keys]
    return sorted({keys[ix.program_id_index] for ix in msg.instructions if ix.program_id_index < len(keys)})


def wait_confirmed(rpc, sig, wait_s=CONFIRM_WAIT_S, sleep=2.0, clock=time.time, pause=time.sleep):
    """True (potvrđeno bez greške), False (palo na lancu), None (isteklo: nepoznato). Nikad ne šalje ponovno."""
    end = clock() + wait_s
    while True:
        try:
            st = rpc("getSignatureStatuses", [[sig], {"searchTransactionHistory": True}])["value"][0]
        except Exception:  # noqa: BLE001
            st = None
        if st and st.get("confirmationStatus") in ("confirmed", "finalized"):
            return st.get("err") is None
        if clock() >= end:
            return None
        pause(sleep)


def mint_exists(rpc, mint, tries=3, pause=time.sleep):
    for k in range(tries):
        try:
            if (rpc("getAccountInfo", [mint, {"encoding": "base64", "commitment": "confirmed"}]) or {}).get("value"):
                return True
        except Exception:  # noqa: BLE001
            pass
        if k + 1 < tries:
            pause(2)
    return False


# ---------- red i stropovi ---------------------------------------------------------------------------------------

def _day_start(now):
    import datetime as dt
    try:
        from zoneinfo import ZoneInfo
        tz = ZoneInfo("Europe/Zagreb")
    except Exception:  # noqa: BLE001
        tz = dt.timezone.utc
    d = dt.datetime.fromtimestamp(now, tz)
    return int(d.replace(hour=0, minute=0, second=0, microsecond=0).timestamp())


def sent_today(con, now):
    return con.execute("SELECT COUNT(*) FROM pokusaji WHERE potpis IS NOT NULL AND ts>=?", (_day_start(now),)).fetchone()[0]


def last_sent(con):
    r = con.execute("SELECT MAX(ts) FROM pokusaji WHERE potpis IS NOT NULL").fetchone()
    return r[0] if r and r[0] else 0


def queue(con):
    return [dict(r) for r in con.execute("SELECT * FROM nacrti WHERE stanje='u_redu' ORDER BY termin_ts, u_red_ts, id")]


def stop_queue(con, why, now=None, log=print):
    """Red stoji dok vlasnik ponovno ne odobri pilot („Zaustavi red” ili pravilo sigurnosti)."""
    store.put(con, "red_stop", {"ts": int(now or time.time()), "razlog": why})
    log(f"pump tokeni: red zaustavljen ({why})")


def stopped(con):
    return store.get(con, "red_stop")


def approve_pilot(con, ids, user, confirmed, now=None, env=None):
    """„Odobri pilot” (jedan dodir vlasnika) odobrava RASPORED: odabrani nacrti u red, svaki u svom terminu. Samo uz
    potvrdu iz okvira i uz cijelu zelenu provjeru prije lansiranja (mlađu od 30 min) koja je obuhvatila te nacrte s
    istom kupnjom i terminom. Razmak RAZMAK je donja granica: bliži termin se pomiče (i to se vraća u popisu). Termin
    koji je prošao više od 15 min → 'propusten', ne ide u red. Odobrenje zamjenjuje prethodni raspored (nacrti u redu
    koji nisu odabrani vraćaju se u 'nacrt'). (n, [napomene])."""
    from trade import settings
    if not settings.is_owner(user):
        raise ValueError("pilot odobrava samo vlasnik")
    if not confirmed:
        raise ValueError("pilot samo uz potvrdu u okviru")
    now = int(now or time.time())
    c = cfg(env)
    ids = list(dict.fromkeys(int(i) for i in ids))
    if not ids:
        raise ValueError("nijedan nacrt nije odabran")
    pf = store.get(con, "provjera") or {}
    if not pf.get("zeleno"):
        raise ValueError("provjera prije lansiranja nije zelena: najprije je pokreni i riješi crvene korake")
    if now - (pf.get("ts") or 0) > PREFLIGHT_MAX_AGE_S:
        raise ValueError("provjera prije lansiranja je starija od 30 min: ponovi je")
    missing = [i for i in ids if i not in (pf.get("ids") or [])]
    if missing:
        raise ValueError(f"provjera nije obuhvatila nacrte {missing}: ponovi je s tim odabirom")
    pfd = {x.get("id"): x for x in pf.get("nacrti") or []}
    items, why = [], []
    for did in ids:
        d = store.draft(con, did)
        if not d:
            continue
        sym = d["simbol"]
        if d["stanje"] not in ("nacrt", "odbijen", "greska", "u_redu", "propusten"):
            why.append(f"#{did}: stanje {d['stanje']}")
            continue
        if not guards.fresh_ok(store.check_of(d), now):
            why.append(f"#{did} {sym}: provjera imena ne prolazi")
            continue
        lw = store.links_reasons(con, d)
        if lw:
            why.append(f"#{did} {sym}: {'; '.join(lw)}")
            continue
        t = d.get("termin_ts") or store.default_termin(now)
        p = pfd.get(did) or {}
        if (abs(float(p.get("kupnja") or 0) - float(d.get("kupnja_sol") or 0)) > 1e-9 or p.get("termin") != t
                or p.get("ok") is not True):
            why.append(f"#{did} {sym}: provjera je rađena s drugom kupnjom ili terminom, ili suha proba nije prošla: "
                       "ponovi provjeru")
            continue
        if now - t > MISSED_S:
            store.set_state(con, did, "propusten", now)
            why.append(f"#{did} {sym}: termin {store.cet(t)} je prošao: propušten, ne ide u red")
            continue
        items.append((t, did, d))
    items.sort(key=lambda x: (x[0], x[1]))
    for d in queue(con):   # novi raspored zamjenjuje stari
        if d["id"] not in {i for _t, i, _d in items}:
            store.set_state(con, d["id"], "nacrt", now)
    plan, last = [], (last_sent(con) or None)
    for t, did, d in items:
        nt = t if last is None else max(t, last + int(c["razmak_s"]))
        if nt != t:
            why.append(f"#{did} {d['simbol']}: termin pomaknut {store.cet(t)} → {store.cet(nt)} (razmak "
                       f"{int(c['razmak_s'] // 60)} min)")
            store.set_termin(con, did, nt)
        if d["stanje"] != "u_redu":
            store.set_state(con, did, "u_redu", now)
        plan.append({"id": did, "simbol": d["simbol"], "termin": nt, "izvorni": t,
                     "kupnja": float(d.get("kupnja_sol") or 0), "poveznice": bool(store.link_urls(con, d))})
        last = nt
    if plan:
        store.put(con, "pilot", {"odobren_ts": now, "ids": [x["id"] for x in plan], "who": user, "poslano": 0,
                                 "uzastopno_neuspjelih": 0, "raspored": plan})
        store.put(con, "red_stop", None)
    return len(plan), why


def dequeue(con, did, now=None):
    d = store.draft(con, did)
    if d and d["stanje"] == "u_redu":
        store.set_state(con, did, "nacrt", now)


def blocked_reason(con, now, env=None, tcon=None):
    """Zašto red sada ne šalje (globalno), ili None."""
    from trade import executor
    c = cfg(env)
    if os.path.exists(executor.STOP_FILE):
        return "kill switch (trade/STOP) je aktivan"
    st = stopped(con)
    if st:
        return f"red je zaustavljen: {st.get('razlog')} (ponovno odobri pilot)"
    if not store.get(con, "pilot"):
        return "pilot nije odobren"
    ch = wallet_choice(con, tcon)
    if ch == OFF:
        return "novčanik je isključen"
    if keypair(ch, env) is None:
        return {TOOL: "novčanik pokusa nije stvoren", SEPARATE: "PUMP_DEV_PRIVATE_KEY nije upisan na Renderu",
                TRADING: "SOLANA_PRIVATE_KEY nije postavljen"}[ch]
    if sent_today(con, now) >= c["dnevno"]:
        return f"dnevni strop: danas već {sent_today(con, now)} od {c['dnevno']}"
    wait = last_sent(con) + c["razmak_s"] - now
    if wait > 0:
        return f"razmak između lansiranja: još {int(wait // 60)} min {int(wait % 60)} s"
    return None


def _note(con, text, now):
    store.put(con, "red_razlog", {"ts": int(now), "tekst": text})


def tick(con, now=None, env=None, rpc=None, post=None, search=None, tcon=None, log=print, wait=None):
    """Jedan prolaz reda: propušteni termini → 'propusten' (bez nadoknade), zatim najviše jedno lansiranje i to samo
    kad je termin prvog nacrta u odobrenom rasporedu došao; pa pravilo sigurnosti pilota. Tekst ishoda ili None."""
    now = int(now or time.time())
    q = queue(con)
    if not q:
        return None
    plan = {x.get("id"): x for x in (store.get(con, "pilot") or {}).get("raspored") or []}
    live = []
    for d in q:
        t, p = d.get("termin_ts"), plan.get(d["id"])
        if t is None or p is None or p.get("termin") != t or \
                abs(float(p.get("kupnja") or 0) - float(d.get("kupnja_sol") or 0)) > 1e-9:
            store.set_state(con, d["id"], "propusten", now)
            log(f"pump tokeni: {d['simbol']} nije u odobrenom rasporedu: ne lansira se, čeka novo odobrenje")
            continue
        if now - t > MISSED_S:
            store.set_state(con, d["id"], "propusten", now)
            log(f"pump tokeni: {d['simbol']} termin {store.cet(t)} propušten (više od 15 min): ne nadoknađuje se, "
                "čeka novo odobrenje")
            continue
        live.append(d)
    if not live:
        return None
    why = blocked_reason(con, now, env, tcon)
    if why:
        _note(con, why, now)
        return why
    head = live[0]
    if now < head["termin_ts"]:
        txt = f"čeka termin: {head['simbol']} u {store.cet(head['termin_ts'])} CET"
        _note(con, txt, now)
        return txt
    res = launch_one(con, head, now, env=env, rpc=rpc, post=post, search=search, tcon=tcon, log=log, wait=wait)
    _safety(con, res, now, env, log)
    return res["tekst"]


def _safety(con, res, now, env=None, log=print):
    """Pravilo sigurnosti (vlasnik 25.11.): prvo lansiranje pilota neuspjelo ili trošak iznad stropa → red stoji;
    kasnije: dva neuspjela zaredom → red stoji; potvrda nije stigla (nepoznato) → red stoji dok se potpis ne provjeri."""
    if res["ishod"] == "ceka":
        return
    pil = store.get(con, "pilot") or {}
    pil["poslano"] = pil.get("poslano", 0) + 1
    ok = res["ishod"] == "lansiran"
    pil["uzastopno_neuspjelih"] = 0 if ok else pil.get("uzastopno_neuspjelih", 0) + 1
    store.put(con, "pilot", pil)
    over = res.get("trosak") is not None and res["trosak"] > cfg(env)["max_sol"]
    if res["ishod"] == "nepoznato":
        stop_queue(con, f"{res['simbol']}: potvrda nije stigla, stanje nepoznato", now, log)
    elif pil["poslano"] == 1 and (not ok or over):
        stop_queue(con, f"prvo lansiranje pilota ({res['simbol']}) " + ("nije uspjelo" if not ok else
                                                                         f"stajalo {res['trosak']:.5f} SOL, iznad stropa"),
                   now, log)
    elif over:
        stop_queue(con, f"{res['simbol']}: izmjereni trošak {res['trosak']:.5f} SOL iznad stropa", now, log)
    elif pil["uzastopno_neuspjelih"] >= 2:
        stop_queue(con, "dva lansiranja zaredom nisu uspjela", now, log)


def _res(d, ishod, tekst, trosak=None):
    return {"simbol": d.get("simbol"), "ishod": ishod, "tekst": f"{d.get('simbol')}: {tekst}", "trosak": trosak}


def launch_one(con, d, now, env=None, rpc=None, post=None, search=None, tcon=None, log=print, wait=None):
    """Jedno lansiranje; {"simbol", "ishod": lansiran|neuspio|odbijen|nepoznato|ceka, "tekst", "trosak"}. Svaka faza
    jedan red u logu („pump tokeni: <simbol> ...”), bez tajni."""
    from solders.keypair import Keypair
    from solders.transaction import VersionedTransaction
    from trade import executor, wallet
    env = os.environ if env is None else env
    rpc = rpc or wallet.rpc
    wait = wait or (lambda s: wait_confirmed(rpc, s))
    c = cfg(env)
    sym = d.get("simbol")
    ch = wallet_choice(con, tcon)
    kp = keypair(ch, env)
    if ch == OFF or kp is None:
        return _res(d, "ceka", "novčanik nije spreman")
    payer = str(kp.pubkey())
    extra = store.get(con, "zabranjene", []) or []
    chk = guards.check(d, extra, search=search, now=now)
    store.save_check(con, d["id"], chk, now)
    if not chk["ok"]:
        txt = "; ".join(chk["razlozi"])
        store.new_attempt(con, d, ch, payer, now, stanje="odbijeno", greska="čuvar imena: " + txt)
        store.set_state(con, d["id"], "odbijen", now)
        log(f"pump tokeni: {sym} čuvar imena odbio: {txt}")
        return _res(d, "odbijen", f"odbijen ({txt})")
    lw = store.links_reasons(con, d)
    if lw:
        txt = "; ".join(lw)
        store.new_attempt(con, d, ch, payer, now, stanje="odbijeno", greska="poveznice: " + txt)
        store.set_state(con, d["id"], "odbijen", now)
        log(f"pump tokeni: {sym} poveznice odbijene: {txt}")
        return _res(d, "odbijen", f"odbijen ({txt})")
    links = store.link_urls(con, d)
    try:
        pre = rpc("getBalance", [payer, {"commitment": "confirmed"}])["value"] / 1e9
    except Exception as e:  # noqa: BLE001
        _note(con, f"saldo nečitljiv ({type(e).__name__})", now)
        log(f"pump tokeni: {sym} saldo nečitljiv ({type(e).__name__}), čeka")
        return _res(d, "ceka", "saldo nečitljiv")
    if pre < c["min_sol"][ch]:
        why = f"saldo {pre:.4f} SOL ispod {c['min_sol'][ch]:g} SOL"
        _note(con, why, now)
        log(f"pump tokeni: {sym} čeka: {why}")
        return _res(d, "ceka", why)
    want = float(d.get("kupnja_sol") or 0)
    kupnja, warn, reserve_ok = plan_buy(pre, want, c)
    if not reserve_ok:
        why = (f"saldo {pre:.4f} SOL ne ostavlja rezervu {c['rezerva_sol']:g} SOL ni bez vlastite kupnje "
               f"(lansiranje do {c['max_sol']:g} SOL)")
        _note(con, why, now)
        log(f"pump tokeni: {sym} čeka: {why}")
        return _res(d, "ceka", why)
    if warn:
        log(f"pump tokeni: {sym} {warn} (saldo {pre:.4f} SOL, kupnja {want:g} SOL bi ostavila manje od "
            f"{c['rezerva_sol']:g} SOL): lansira se bez kupnje")
    uri = d.get("meta_uri")
    if not uri:
        try:
            uri = upload_metadata(d["ime"], d["simbol"], d["opis"], d["slika"], c["ipfs"], post=post, env=env,
                                  links=links)
        except Exception as e:  # noqa: BLE001
            store.new_attempt(con, d, ch, payer, now, stanje="odbijeno", greska=f"IPFS: {str(e)[:200]}")
            store.set_state(con, d["id"], "greska", now)
            log(f"pump tokeni: {sym} IPFS greška: {str(e)[:200]}")
            return _res(d, "neuspio", "IPFS nije uspio")
        con.execute("UPDATE nacrti SET meta_uri=? WHERE id=?", (uri, d["id"]))
        con.commit()
    log(f"pump tokeni: {sym} IPFS ok")
    mint_kp = Keypair()
    mint = str(mint_kp.pubkey())
    aid = store.new_attempt(con, d, ch, payer, now, mint=mint)   # mint upisan prije bilo kakvog slanja
    own.reset()
    store.update_attempt(con, aid, saldo_prije=pre, kupnja_trazena=want, kupnja_sol=kupnja, upozorenje=warn,
                         ima_poveznice=1 if links else 0, termin_ts=d.get("termin_ts"))

    def refuse(text, state="odbijen", sim=None, phase=""):
        store.update_attempt(con, aid, stanje="odbijeno", greska=text[:400], **({"sim_sol": sim} if sim is not None else {}))
        store.set_state(con, d["id"], state, now)
        log(f"pump tokeni: {sym} {phase}greška: {text[:300]}")
        return _res(d, "odbijen" if state == "odbijen" else "neuspio", text)
    try:
        raw = create_tx(create_request(payer, mint, d["ime"], d["simbol"], uri, c["priority_sol"], kupnja), post=post)
        tx = VersionedTransaction.from_bytes(raw)
    except Exception as e:  # noqa: BLE001
        return refuse(f"create nalog nije dobiven: {str(e)[:200]}", "greska", phase="create ")
    why = check_message(tx, payer, mint, c["priority_sol"])
    if why:
        return refuse(why, phase="create ")
    log(f"pump tokeni: {sym} create ok")
    signed = VersionedTransaction(tx.message, [mint_kp, kp])
    b64 = base64.b64encode(bytes(signed)).decode()
    try:
        sim = simulate(rpc, b64, payer, tx.message.header.num_required_signatures, sim_cap(c, kupnja))
    except Exception as e:  # noqa: BLE001
        return refuse(f"simulacija nije uspjela ({type(e).__name__})", "greska", phase="simulacija ")
    if not sim["ok"]:
        return refuse(sim["why"], sim=sim["sol"], phase="simulacija ")
    log(f"pump tokeni: {sym} simulacija ok (trošak {sim['sol']:.5f} SOL" +
        (f", od toga vlastita kupnja {kupnja:g} SOL)" if kupnja else ")"))
    if os.path.exists(executor.STOP_FILE):   # još jednom, odmah prije slanja
        store.update_attempt(con, aid, stanje="odbijeno", greska="kill switch (trade/STOP)")
        log(f"pump tokeni: {sym} nije poslan: kill switch")
        return _res(d, "ceka", "kill switch")
    sig = str(signed.signatures[0])
    store.update_attempt(con, aid, potpis=sig, stanje="poslano", sim_sol=sim["sol"])
    store.set_state(con, d["id"], "salje", now)
    try:
        sent = rpc("sendTransaction", [b64, {"encoding": "base64", "maxRetries": 3}])
    except Exception as e:  # noqa: BLE001 - preflight / RPC refused: nothing landed under this signature
        store.update_attempt(con, aid, stanje="neuspio", greska=f"slanje: {str(e)[:300]}")
        store.set_state(con, d["id"], "greska", now)
        log(f"pump tokeni: {sym} slanje greška: {str(e)[:200]}")
        return _res(d, "neuspio", "slanje nije uspjelo")
    if sent and str(sent) != sig:
        sig = str(sent)
        store.update_attempt(con, aid, potpis=sig)
    log(f"pump tokeni: {sym} poslano {sig}")
    ok = wait(sig)
    if ok is None:   # isteklo: nepoznato; nacrt ostaje 'salje' (ne šalje se ponovno) dok reconcile() ne pročita potpis
        store.update_attempt(con, aid, stanje="nepoznato", greska="potvrda nije stigla do isteka")
        log(f"pump tokeni: {sym} potvrda nije stigla do isteka: stanje nepoznato, bez ponovnog slanja")
        return _res(d, "nepoznato", "nepoznato")
    try:
        post_bal = rpc("getBalance", [payer, {"commitment": "confirmed"}])["value"] / 1e9
    except Exception:  # noqa: BLE001
        post_bal = None
    total = round(pre - post_bal, 9) if post_bal is not None else None
    cost = total   # palo na lancu: kupnja se nije dogodila, sve je trošak
    if ok is False:
        store.update_attempt(con, aid, stanje="neuspio", saldo_poslije=post_bal, trosak_sol=cost, ukupno_sol=total,
                             greska="transakcija pala na lancu")
        store.set_state(con, d["id"], "greska", now)
        log(f"pump tokeni: {sym} greška: transakcija pala na lancu, trošak {cost if cost is not None else '?'} SOL")
        return _res(d, "neuspio", "palo na lancu", cost)
    cost = round(total - kupnja, 9) if total is not None else None   # kupnja = vezan kapital u tokenima, ne trošak
    if not mint_exists(rpc, mint):
        store.update_attempt(con, aid, stanje="nepoznato", saldo_poslije=post_bal, trosak_sol=cost, ukupno_sol=total,
                             greska="potvrđeno, ali mint račun još nije vidljiv")
        log(f"pump tokeni: {sym} potvrđeno, ali mint račun nije vidljiv: stanje nepoznato")
        return _res(d, "nepoznato", "mint nije vidljiv", cost)
    store.update_attempt(con, aid, stanje="lansiran", saldo_poslije=post_bal, trosak_sol=cost, ukupno_sol=total,
                         greska=None)
    store.set_state(con, d["id"], "lansiran", now)
    log(f"pump tokeni: {sym} potvrđeno, mint {mint}, izmjereni trošak {cost if cost is not None else '?'} SOL"
        + (f" (+ vlastita kupnja {kupnja:g} SOL u tokenima; alat ih ne prodaje)" if kupnja else ""))
    return _res(d, "lansiran", "lansiran", cost)


def reconcile(con, now=None, rpc=None, min_age_s=120, log=print):
    """Pokušaji 'poslano' / 'nepoznato' stariji od min_age_s: potpis s lanca (getSignatureStatuses) i mint račun →
    'lansiran' ili 'neuspio' (nacrt 'lansiran' / 'greska'). Broj razriješenih. Nikad ne šalje ništa."""
    from trade import wallet
    rpc = rpc or wallet.rpc
    now = int(now or time.time())
    rows = [dict(r) for r in con.execute("SELECT * FROM pokusaji WHERE stanje IN ('poslano','nepoznato') AND ts<=? "
                                         "AND potpis IS NOT NULL", (now - min_age_s,))]
    n = 0
    for a in rows:
        try:
            st = rpc("getSignatureStatuses", [[a["potpis"]], {"searchTransactionHistory": True}])["value"][0]
        except Exception:  # noqa: BLE001
            continue
        if st and st.get("confirmationStatus") in ("confirmed", "finalized"):
            ok = st.get("err") is None and mint_exists(rpc, a["mint"], tries=1)
            cols = {"stanje": "lansiran" if ok else "neuspio", "greska": None if ok else "transakcija pala na lancu"}
            if a.get("trosak_sol") is None and a.get("saldo_prije") is not None:
                try:
                    post_bal = rpc("getBalance", [a["platitelj"], {"commitment": "confirmed"}])["value"] / 1e9
                    total = round(a["saldo_prije"] - post_bal, 9)
                    cols.update(saldo_poslije=post_bal, ukupno_sol=total,
                                trosak_sol=round(total - ((a.get("kupnja_sol") or 0) if ok else 0), 9))
                except Exception:  # noqa: BLE001
                    pass
            store.update_attempt(con, a["id"], **cols)
            store.set_state(con, a["nacrt_id"], "lansiran" if ok else "greska", now)
            log(f"pump tokeni: {a['simbol']} provjera potpisa: {'potvrđeno, mint ' + a['mint'] if ok else 'nije uspjelo'}")
            n += 1
        elif st is None and now - a["ts"] > 3600:   # sat vremena bez traga: nalog je istekao (blockhash)
            store.update_attempt(con, a["id"], stanje="neuspio", greska="nalog nije stigao na lanac (istekao)")
            store.set_state(con, a["nacrt_id"], "greska", now)
            log(f"pump tokeni: {a['simbol']} nalog nije stigao na lanac (istekao)")
            n += 1
    return n
