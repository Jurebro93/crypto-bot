"""Provjera prije lansiranja (25.11., vlasnik; 26.11.: cijeli raspored): gumb na stranici, automatski pri otvaranju
(najviše jednom u AUTO_EVERY_S) i iz posla (pumptokeni.posao: jednom nakon pokretanja procesa, zatim najviše jednom u
30 min dok postoji zakazan a nelansiran nacrt). Rezultat u kv 'provjera' i u logu jedan red „pump tokeni provjera: ...”
te po nacrtu „pump tokeni suha proba: ...”. Pilot se ne može odobriti dok provjera nije cijela zelena (korak koji se
izričito ne može provjeriti unaprijed nosi ok=None i tako je označen).

  1 novčanik   postoji, saldo ≥ MIN_SOL i ≥ broj nacrta × strop lansiranja + rezerva (kupnje se same preskaču kad bi
               probile rezervu; zbroj s kupnjama je u tekstu)
  2 RPC        getLatestBlockhash odgovara
  3 IPFS       Pinata: GET testAuthentication (SAMO autentifikacija, bez učitavanja); pump.fun/api/ipfs se ne može
               provjeriti bez stvarnog učitavanja: „provjerit će se pri prvom lansiranju”
  4 PumpPortal za SVAKI nacrt rasporeda create zahtjev s njegovom kupnjom (probni mint; URI spremljeni ili probni)
               vraća transakciju koja se deserijalizira i prolazi provjeru naloga (platitelj, 2 potpisa, pump.fun, prioritet)
  5 suha proba svaka ta transakcija potpisana (probni mint + novčanik) i poslana SAMO na simulateTransaction: uspjeh,
               promjena salda platitelja (trošak + kupnja, strop MAX_SOL + kupnja × 1,03), programi, rezerva nakon
               svakog lansiranja redom (ako je kupnja probija: „bez kupnje”), zbroj rasporeda prema saldu.
               Ništa ne ide na lanac (nikad sendTransaction) i ništa se ne učitava na IPFS.
  6 sigurnost  kill switch isključen, dnevni strop nije potrošen, čuvari imena i poveznica prolaze za svaki nacrt
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
    return [d["id"] for d in store.drafts(con) if d["stanje"] in store.UNSENT]


def scheduled_ids(con, now=None):
    """Zakazani a nelansirani nacrti (termin nije prošao više od 15 min)."""
    now = int(now or time.time())
    return [d["id"] for d in store.drafts(con) if d["stanje"] in store.UNSENT and d.get("termin_ts")
            and now - d["termin_ts"] <= launch.MISSED_S]


def run(con, ids=None, now=None, env=None, rpc=None, post=None, get=None, search=None, tcon=None, log=print):
    """[{"k", "naziv", "ok": True|False|None, "tekst"}], zapisano u kv 'provjera' {ts, ids, koraci, zeleno, nacrti,
    zbroj}. Nikad ne šalje transakciju i nikad ne učitava na IPFS (post se zove samo za PumpPortal create)."""
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
    for d in drafts:
        d["_termin"] = d.get("termin_ts") or store.default_termin(now)
    drafts.sort(key=lambda d: (d["_termin"], d["id"]))
    steps = []
    rez = c["rezerva_sol"]

    def step(k, naziv, ok, tekst):
        steps.append({"k": k, "naziv": naziv, "ok": ok, "tekst": tekst})

    # 1 novčanik
    ch = launch.wallet_choice(con, tcon)
    kp = launch.keypair(ch, env) if ch != launch.OFF else None
    payer = str(kp.pubkey()) if kp else None
    buys = sum(float(d.get("kupnja_sol") or 0) for d in drafts)
    need = len(drafts) * c["max_sol"] + rez
    need_buy = need + buys * launch.BUY_CAP_MULT
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
                                            f"rezerva {rez:g}); s vlastitim kupnjama ({buys:g} SOL × "
                                            f"{launch.BUY_CAP_MULT:g}) {need_buy:.4f}")
        except Exception as e:  # noqa: BLE001
            step(1, "Novčanik i saldo", False, f"saldo nečitljiv ({type(e).__name__})")
    # 2 RPC
    try:
        bh = rpc("getLatestBlockhash", [{"commitment": "confirmed"}])["value"]["blockhash"]
        step(2, "RPC", bool(bh), "getLatestBlockhash odgovara" if bh else "prazan odgovor")
    except Exception as e:  # noqa: BLE001
        step(2, "RPC", False, f"ne odgovara ({type(e).__name__})")
    # 3 IPFS (samo autentifikacija, nikad učitavanje)
    if c["ipfs"] == "pinata":
        try:
            st = get(PINATA_TEST, {"Authorization": f"Bearer {(env.get('PINATA_JWT') or '').strip()}"})
            step(3, "IPFS (Pinata)", st == 200, "ključ prihvaćen (bez učitavanja)" if st == 200 else f"odgovor {st}")
        except Exception as e:  # noqa: BLE001
            step(3, "IPFS (Pinata)", False, f"nedohvatljivo ({type(e).__name__})")
    else:
        step(3, "IPFS (pump.fun)", None, "ne može se provjeriti bez stvarnog učitavanja: provjerit će se pri prvom "
                                         "lansiranju (PumpPortal dokumentacija 25.11. kaže da pump.fun/api/ipfs više "
                                         "nije podržan; preporuka PINATA_JWT)")
    # 4 + 5 create i suha proba za svaki nacrt rasporeda
    per, progs_all = [], set()
    run_bal = bal
    if not (drafts and kp):
        step(4, "PumpPortal create", False, "nema nacrta ili novčanika")
        step(5, "Suha proba (simulacija)", False, "preskočeno")
    else:
        for d in drafts:
            k = float(d.get("kupnja_sol") or 0)
            r = {"id": d["id"], "simbol": d["simbol"], "termin": d["_termin"], "kupnja": k, "ok": False,
                 "create_ok": False, "sol": None, "programi": [], "rezerva_ok": None, "bez_kupnje": False,
                 "poveznice": bool(store.link_urls(con, d)), "why": None}
            per.append(r)
            mint_kp = Keypair()
            try:
                raw = launch.create_tx(launch.create_request(payer, str(mint_kp.pubkey()), d["ime"], d["simbol"],
                                                             d.get("meta_uri") or PROBE_URI, c["priority_sol"], k),
                                       post=post)
                tx = VersionedTransaction.from_bytes(raw)
                why = launch.check_message(tx, payer, str(mint_kp.pubkey()), c["priority_sol"])
            except Exception as e:  # noqa: BLE001
                tx, why = None, str(e)[:200]
            if why:
                r["why"] = why
                continue
            r["create_ok"] = True
            r["programi"] = launch.programs(tx.message)
            progs_all.update(r["programi"])
            try:
                signed = VersionedTransaction(tx.message, [mint_kp, kp])
                sim = launch.simulate(rpc, base64.b64encode(bytes(signed)).decode(), payer,
                                      tx.message.header.num_required_signatures, launch.sim_cap(c, k))
            except Exception as e:  # noqa: BLE001
                sim = {"ok": False, "why": f"nije uspjela ({type(e).__name__})", "sol": None}
            r["sol"] = sim["sol"]
            if not sim["ok"]:
                r["why"] = sim["why"]
                continue
            r["ok"] = True
            if run_bal is not None:
                if run_bal - sim["sol"] >= rez - 1e-12:
                    r["rezerva_ok"] = True
                    run_bal -= sim["sol"]
                elif k > 0 and run_bal - (sim["sol"] - k * (1 + launch.BUY_FEE)) >= rez - 1e-12:
                    r["rezerva_ok"], r["bez_kupnje"] = True, True
                    run_bal -= sim["sol"] - k * (1 + launch.BUY_FEE)
                else:
                    r["rezerva_ok"] = False
        bad_c = [r for r in per if not r["create_ok"]]
        step(4, "PumpPortal create", not bad_c,
             "; ".join(f"{r['simbol']}: {r['why']}" for r in bad_c) if bad_c else
             f"{len(per)} transakcija deserijalizirano i provjereno (platitelj, 2 potpisa, pump.fun, prioritet)")
        bad = [r for r in per if r["create_ok"] and not r["ok"]] + [r for r in per if r["rezerva_ok"] is False]
        tot = sum(r["sol"] or 0 for r in per if r["ok"])
        summ = (f"raspored {len(per)}: ukupno −{tot:.5f} SOL u simulaciji" +
                (f", saldo {bal:.4f} → ostaje {run_bal:.4f} SOL (rezerva {rez:g})" if bal is not None else ""))
        if bad_c and not bad:
            step(5, "Suha proba (simulacija)", False, "preskočeno za nacrte bez transakcije; " + summ)
        else:
            step(5, "Suha proba (simulacija)", not bad,
                 ("; ".join(f"{r['simbol']}: {r['why'] or 'ne ostavlja rezervu ni bez kupnje'}" for r in bad) + "; "
                  if bad else "uspjela za sve; ") + summ + f"; programi: {', '.join(sorted(progs_all))}")
    # 6 sigurnost
    bad6 = []
    if os.path.exists(executor.STOP_FILE):
        bad6.append("kill switch je aktivan")
    left = c["dnevno"] - launch.sent_today(con, now)
    if left <= 0:
        bad6.append("dnevni strop je potrošen")
    elif len(drafts) > left:
        bad6.append(f"odabrano {len(drafts)}, a danas je ostalo {left}")
    extra = store.get(con, "zabranjene", []) or []
    for d in drafts:
        r = guards.check(d, extra, search=search, now=now)
        store.save_check(con, d["id"], r, now)
        if not r["ok"]:
            bad6.append(f"{d['simbol'] or '#' + str(d['id'])}: {'; '.join(r['razlozi'])}")
        lw = store.links_reasons(con, d)
        if lw:
            bad6.append(f"{d['simbol'] or '#' + str(d['id'])}: {'; '.join(lw)}")
    step(6, "Kill switch, dnevni strop, čuvari imena i poveznica", not bad6, "; ".join(bad6) if bad6 else
         f"kill switch isključen, danas ostalo {left}, imena i poveznice prolaze ({len(drafts)})")
    green = all(s["ok"] is not False for s in steps)
    zbroj = {"sol": sum(r["sol"] or 0 for r in per if r["ok"]), "saldo": bal, "ostaje": run_bal, "rezerva": rez}
    store.put(con, "provjera", {"ts": now, "ids": ids, "koraci": steps, "zeleno": green, "nacrti": per,
                                "zbroj": zbroj})
    log("pump tokeni provjera: " + ("ZELENO" if green else "NIJE ZELENO") + "; " + "; ".join(
        f"{s['k']} {s['naziv']}: {'radi' if s['ok'] else 'ne radi' if s['ok'] is False else 'pri prvom lansiranju'}"
        + ("" if s["ok"] else f" ({s['tekst'][:120]})") for s in steps))
    for r in per:
        log(dry_line(r))
    return steps


def dry_line(r):
    """„pump tokeni suha proba: <simbol> termin <CET>, kupnja X SOL, simulacija ok/greška, promjena salda −Y SOL,
    rezerva ok/ne”."""
    sol = f"−{r['sol']:.5f} SOL" if r.get("sol") is not None else "–"
    rz = {True: "ok", False: "ne", None: "?"}[r.get("rezerva_ok")] + (" (bez kupnje)" if r.get("bez_kupnje") else "")
    return (f"pump tokeni suha proba: {r['simbol']} termin {store.cet(r['termin'])} CET, kupnja {r['kupnja']:g} SOL, "
            f"simulacija {'ok' if r['ok'] else 'greška'}, promjena salda {sol}, rezerva {rz}"
            + ("" if r["ok"] else f" ({(r.get('why') or '')[:120]})"))


def due(con, now=None):
    pf = store.get(con, "provjera") or {}
    return (now or time.time()) - (pf.get("ts") or 0) >= AUTO_EVERY_S
