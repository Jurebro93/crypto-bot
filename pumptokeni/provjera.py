"""Provjera prije lansiranja (25.11., vlasnik): gumb na stranici i automatski pri otvaranju (najviše jednom u
AUTO_EVERY_S); rezultat u kv 'provjera' i jedan red u logu „pump tokeni provjera: ...”. Pilot se ne može odobriti dok
provjera nije cijela zelena (korak koji se izričito ne može provjeriti unaprijed nosi ok=None i tako je označen).

  1 novčanik   postoji i saldo ≥ broj nacrta × strop simulacije + rezerva
  2 RPC        getLatestBlockhash odgovara
  3 IPFS       Pinata: GET testAuthentication (bez učitavanja); pump.fun/api/ipfs se ne može provjeriti bez stvarnog
               učitavanja: „provjerit će se pri prvom lansiranju”
  4 PumpPortal create zahtjev za probni nacrt (prvi odabrani; probni mint, probni URI) vraća transakciju koja se
               deserijalizira i prolazi provjeru naloga (platitelj, 2 potpisa, pump.fun program, priority strop)
  5 suha proba ta transakcija potpisana (probni mint + novčanik) i poslana SAMO na simulateTransaction: uspjeh,
               promjena salda platitelja, programi koje poziva. Ništa ne ide na lanac (nikad sendTransaction).
  6 sigurnost  kill switch isključen, dnevni strop nije potrošen, čuvari imena prolaze za svaki odabrani nacrt
"""
import base64
import os
import time

from pumptokeni import guards, launch, store

AUTO_EVERY_S = 600
PINATA_TEST = "https://api.pinata.cloud/data/testAuthentication"
PROBE_URI = "https://ipfs.io/ipfs/bafkreiaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"   # samo za simulaciju


def _get(url, headers, timeout=15):
    import urllib.request
    req = urllib.request.Request(url, headers={"User-Agent": launch.UA, **headers})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code


def default_ids(con):
    return [d["id"] for d in store.drafts(con) if d["stanje"] in ("nacrt", "odbijen", "greska", "u_redu")]


def run(con, ids=None, now=None, env=None, rpc=None, post=None, get=None, search=None, tcon=None, log=print):
    """[{"k", "naziv", "ok": True|False|None, "tekst"}], zapisano u kv 'provjera' {ts, ids, koraci, zeleno}."""
    from solders.keypair import Keypair
    from solders.transaction import VersionedTransaction
    from trade import executor, wallet
    env = os.environ if env is None else env
    rpc = rpc or wallet.rpc
    get = get or _get
    now = int(now or time.time())
    c = launch.cfg(env)
    ids = [int(i) for i in (ids if ids is not None else default_ids(con))]
    drafts = [d for d in (store.draft(con, i) for i in ids) if d]
    steps = []

    def step(k, naziv, ok, tekst):
        steps.append({"k": k, "naziv": naziv, "ok": ok, "tekst": tekst})

    # 1 novčanik
    ch = launch.wallet_choice(con, tcon)
    kp = launch.keypair(ch, env) if ch != launch.OFF else None
    payer = str(kp.pubkey()) if kp else None
    need = len(drafts) * c["max_sol"] + launch.RESERVE_SOL
    bal = None
    if not drafts:
        step(1, "Novčanik i saldo", False, "nijedan nacrt nije odabran")
    elif ch == launch.OFF:
        step(1, "Novčanik i saldo", False, "novčanik je isključen")
    elif kp is None:
        step(1, "Novčanik i saldo", False, "novčanik pokusa nije stvoren" if ch == launch.TOOL else "nema ključa")
    else:
        try:
            bal = rpc("getBalance", [payer, {"commitment": "confirmed"}])["value"] / 1e9
            ok = bal >= need and bal >= c["min_sol"][ch]
            step(1, "Novčanik i saldo", ok, f"{launch.CHOICES[ch]} {payer[:4]}…{payer[-4:]}: saldo {bal:.4f} SOL, treba "
                                            f"{max(need, c['min_sol'][ch]):.4f} ({len(drafts)} × {c['max_sol']:g} + "
                                            f"rezerva {launch.RESERVE_SOL:g})")
        except Exception as e:  # noqa: BLE001
            step(1, "Novčanik i saldo", False, f"saldo nečitljiv ({type(e).__name__})")
    # 2 RPC
    blockhash_ok = False
    try:
        bh = rpc("getLatestBlockhash", [{"commitment": "confirmed"}])["value"]["blockhash"]
        blockhash_ok = bool(bh)
        step(2, "RPC", blockhash_ok, "getLatestBlockhash odgovara" if bh else "prazan odgovor")
    except Exception as e:  # noqa: BLE001
        step(2, "RPC", False, f"ne odgovara ({type(e).__name__})")
    # 3 IPFS
    if c["ipfs"] == "pinata":
        try:
            st = get(PINATA_TEST, {"Authorization": f"Bearer {(env.get('PINATA_JWT') or '').strip()}"})
            step(3, "IPFS (Pinata)", st == 200, "ključ prihvaćen" if st == 200 else f"odgovor {st}")
        except Exception as e:  # noqa: BLE001
            step(3, "IPFS (Pinata)", False, f"nedohvatljivo ({type(e).__name__})")
    else:
        step(3, "IPFS (pump.fun)", None, "ne može se provjeriti bez stvarnog učitavanja: provjerit će se pri prvom "
                                         "lansiranju (PumpPortal dokumentacija 25.11. kaže da pump.fun/api/ipfs više "
                                         "nije podržan; preporuka PINATA_JWT)")
    # 4 + 5 create i suha proba
    tx = None
    probe = drafts[0] if drafts else None
    if not (probe and kp):
        step(4, "PumpPortal create", False, "nema probnog nacrta ili novčanika")
        step(5, "Suha proba (simulacija)", False, "preskočeno")
    else:
        mint_kp = Keypair()
        try:
            raw = launch.create_tx(launch.create_request(payer, str(mint_kp.pubkey()), probe["ime"], probe["simbol"],
                                                         PROBE_URI, c["priority_sol"]), post=post)
            tx = VersionedTransaction.from_bytes(raw)
            why = launch.check_message(tx, payer, str(mint_kp.pubkey()), c["priority_sol"])
            step(4, "PumpPortal create", why is None, why or f"transakcija za {probe['simbol']} deserijalizirana, "
                                                             f"{len(raw)} B, prioritet "
                                                             f"{launch.priority_sol(tx.message):.6f} SOL")
            if why:
                tx = None
        except Exception as e:  # noqa: BLE001
            step(4, "PumpPortal create", False, f"{str(e)[:200]}")
        if tx is None:
            step(5, "Suha proba (simulacija)", False, "preskočeno (nema transakcije)")
        else:
            try:
                signed = VersionedTransaction(tx.message, [mint_kp, kp])
                sim = launch.simulate(rpc, base64.b64encode(bytes(signed)).decode(), payer,
                                      tx.message.header.num_required_signatures, c["max_sol"])
                progs = ", ".join(launch.programs(tx.message))
                step(5, "Suha proba (simulacija)", sim["ok"],
                     (f"uspjela; promjena salda {sim['sol']:.5f} SOL; programi: {progs}" if sim["ok"] else
                      f"{sim['why']}; programi: {progs}"))
            except Exception as e:  # noqa: BLE001
                step(5, "Suha proba (simulacija)", False, f"nije uspjela ({type(e).__name__})")
    # 6 sigurnost
    bad = []
    if os.path.exists(executor.STOP_FILE):
        bad.append("kill switch je aktivan")
    left = c["dnevno"] - launch.sent_today(con, now)
    if left <= 0:
        bad.append("dnevni strop je potrošen")
    elif len(drafts) > left:
        bad.append(f"odabrano {len(drafts)}, a danas je ostalo {left}")
    extra = store.get(con, "zabranjene", []) or []
    for d in drafts:
        r = guards.check(d, extra, search=search, now=now)
        store.save_check(con, d["id"], r, now)
        if not r["ok"]:
            bad.append(f"{d['simbol'] or '#' + str(d['id'])}: {'; '.join(r['razlozi'])}")
    step(6, "Kill switch, dnevni strop, čuvari imena", not bad, "; ".join(bad) if bad else
         f"kill switch isključen, danas ostalo {left}, imena prolaze ({len(drafts)})")
    green = all(s["ok"] is not False for s in steps)
    store.put(con, "provjera", {"ts": now, "ids": ids, "koraci": steps, "zeleno": green})
    log("pump tokeni provjera: " + ("ZELENO" if green else "NIJE ZELENO") + "; " + "; ".join(
        f"{s['k']} {s['naziv']}: {'radi' if s['ok'] else 'ne radi' if s['ok'] is False else 'pri prvom lansiranju'}"
        + ("" if s["ok"] else f" ({s['tekst'][:120]})") for s in steps))
    return steps


def due(con, now=None):
    pf = store.get(con, "provjera") or {}
    return (now or time.time()) - (pf.get("ts") or 0) >= AUTO_EVERY_S
