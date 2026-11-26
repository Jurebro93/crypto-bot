"""„Podigni naknadu” (26.11., vlasnik): naknada kreatora skuplja se u JEDNOM trezoru po novčaniku kreatora (pump.fun
program, PDA ["creator-vault", kreator]; outcomes.vault_pda) i ne isplaćuje se sama. Samo vlasnikov dodir uz okvir
potvrde; nikad automatski.

Tok:
  1. samo vlasnik, samo uz potvrdu; kill switch (trade/STOP) → ništa; novčanik izabran i ima ključ
  2. PumpPortal trade-local: {"publicKey", "action": "collectCreatorFee", "priorityFee", "pool": "pump"} (pump.fun
     podiže sve naknade novčanika odjednom, mint nije potreban; prema PumpPortal dokumentaciji „Claim Creator Fees”,
     NIJE ponovno provjereno uživo 26.11.: pumpportal.fun nedohvatljiv iz sandboxa)
  3. provjera naloga: platitelj prvi i JEDINI potpisnik, samo dopušteni programi (pump.fun, PumpSwap, sustavni,
     token, ATA, ComputeBudget), priority ≤ strop
  4. simulateTransaction (sigVerify): mora uspjeti, platitelj mora DOBITI SOL (inače „ništa za podići”), a trošak
     naknade ne smije prijeći CLAIM_MAX_FEE_SOL; nijedan token račun ne gubi tokene
  5. slanje, potvrda, podignuto = izmjerena promjena salda (poslije − prije, već umanjena za mrežnu naknadu)
Ključ se nikad ne ispisuje ni ne logira.
"""
import base64
import os
import time

from pumptokeni import launch

PUMP_AMM = "pAMMBay6oceH9fJKBRHGP5D4bD4sWpmSwMn52FMfXEA"
ALLOWED = {launch.PUMP_PROGRAM, PUMP_AMM, launch.COMPUTE_BUDGET, "11111111111111111111111111111111",
           "ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL", *launch.TOKEN_PROGRAMS}
CLAIM_MAX_FEE_SOL = 0.00025   # tvrdi strop mrežne naknade podizanja (osnovna + priority, konzervativno dvaput osnovna)


def claim_request(payer, priority_sol):
    return {"publicKey": payer, "action": "collectCreatorFee", "priorityFee": priority_sol, "pool": "pump"}


def check_message(tx, payer, prio_max):
    """Razlog odbijanja ili None."""
    msg = tx.message
    keys = [str(k) for k in msg.account_keys]
    if not keys or keys[0] != payer:
        return "platitelj naloga nije naš novčanik"
    if msg.header.num_required_signatures != 1:
        return f"nalog traži {msg.header.num_required_signatures} potpisa (očekivan 1: novčanik)"
    progs = set(launch.programs(msg))
    if not progs & {launch.PUMP_PROGRAM, PUMP_AMM}:
        return "nalog ne poziva pump.fun program"
    bad = sorted(progs - ALLOWED)
    if bad:
        return f"nalog poziva nepoznat program {bad[0][:6]}…"
    p = launch.priority_sol(msg)
    if p > prio_max + 1e-12:
        return f"priority naknada {p:.6f} SOL iznad stropa {prio_max:g}"
    return None


def _row(con, now, ch, payer, stanje, **cols):
    cur = con.execute("INSERT INTO podizanja (ts, novcanik, platitelj, stanje) VALUES (?,?,?,?)", (now, ch, payer, stanje))
    con.commit()
    _upd(con, cur.lastrowid, **cols)
    return cur.lastrowid


def _upd(con, rid, **cols):
    if cols:
        con.execute(f"UPDATE podizanja SET {', '.join(f'{k}=?' for k in cols)} WHERE id=?", (*cols.values(), rid))
        con.commit()


def claim(con, user, confirmed, now=None, env=None, rpc=None, post=None, tcon=None, wait=None, log=print):
    """{"ok": True|False|None, "potpis", "iznos_sol", "tekst"}. ValueError kad se ništa nije poslalo."""
    from solders.transaction import VersionedTransaction
    from trade import executor, settings, wallet
    if not settings.is_owner(user):
        raise ValueError("naknadu podiže samo vlasnik")
    if not confirmed:
        raise ValueError("podizanje samo uz potvrdu u okviru")
    env = os.environ if env is None else env
    now = int(now or time.time())
    rpc = rpc or wallet.rpc
    wait = wait or (lambda s: launch.wait_confirmed(rpc, s))
    if os.path.exists(executor.STOP_FILE):
        raise ValueError("kill switch (trade/STOP) je aktivan")
    ch = launch.wallet_choice(con, tcon)
    kp = launch.keypair(ch, env) if ch != launch.OFF else None
    if kp is None:
        raise ValueError("novčanik nije spreman")
    payer = str(kp.pubkey())
    c = launch.cfg(env)

    def refuse(text):
        _row(con, now, ch, payer, "odbijeno", greska=text[:400])
        log(f"pump tokeni: podizanje naknade odbijeno: {text[:300]}")
        raise ValueError(text)
    try:
        pre = rpc("getBalance", [payer, {"commitment": "confirmed"}])["value"] / 1e9
        raw = launch.create_tx(claim_request(payer, c["priority_sol"]), post=post)
        tx = VersionedTransaction.from_bytes(raw)
    except ValueError:
        raise
    except Exception as e:  # noqa: BLE001
        refuse(f"nalog nije dobiven: {str(e)[:200]}")
    why = check_message(tx, payer, c["priority_sol"])
    if why:
        refuse(why)
    signed = VersionedTransaction(tx.message, [kp])
    b64 = base64.b64encode(bytes(signed)).decode()
    try:
        sim = launch.simulate(rpc, b64, payer, 1, CLAIM_MAX_FEE_SOL)
    except Exception as e:  # noqa: BLE001
        refuse(f"simulacija nije uspjela ({type(e).__name__})")
    if not sim["ok"]:
        refuse(sim["why"].replace("promjena salda", "trošak podizanja"))
    if sim["sol"] is None or sim["sol"] >= 0:
        refuse("simulacija: novčanik ne bi dobio ništa (nema ništa za podići)")
    if os.path.exists(executor.STOP_FILE):
        refuse("kill switch (trade/STOP)")
    sig = str(signed.signatures[0])
    rid = _row(con, now, ch, payer, "poslano", potpis=sig, saldo_prije=pre, sim_sol=-sim["sol"])
    log(f"pump tokeni: podizanje naknade, simulacija +{-sim['sol']:.6f} SOL")
    try:
        sent = rpc("sendTransaction", [b64, {"encoding": "base64", "maxRetries": 3}])
    except Exception as e:  # noqa: BLE001
        _upd(con, rid, stanje="neuspio", greska=f"slanje: {str(e)[:300]}")
        raise ValueError("slanje nije uspjelo")
    if sent and str(sent) != sig:
        sig = str(sent)
        _upd(con, rid, potpis=sig)
    log(f"pump tokeni: podizanje naknade poslano {sig}")
    ok = wait(sig)
    try:
        post_bal = rpc("getBalance", [payer, {"commitment": "confirmed"}])["value"] / 1e9
    except Exception:  # noqa: BLE001
        post_bal = None
    got = round(post_bal - pre, 9) if (post_bal is not None and ok) else None
    _upd(con, rid, stanje={True: "potvrdeno", False: "neuspio", None: "nepoznato"}[ok], saldo_poslije=post_bal,
         iznos_sol=got)
    log(f"pump tokeni: podizanje naknade {'potvrđeno, +' + format(got or 0, '.6f') + ' SOL' if ok else 'nije potvrđeno' if ok is None else 'palo na lancu'}")
    return {"ok": ok, "potpis": sig, "iznos_sol": got,
            "tekst": (f"podignuto {got:+.6f} SOL" if ok and got is not None else
                      "poslano, potvrda još nije stigla" if ok is None else "palo na lancu")}
