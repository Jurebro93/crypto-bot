"""Novčanik pokusa stvoren u alatu (25.11., vlasnik: „novčanik pokusa stvara se u alatu, vlasnik ga puni s 0,2 SOL”).

  create()   novi keypair (solders); tajna (base58) u datoteci DATA_DIR/pump_dev_wallet.key, prava 0600, otvorena s
             O_EXCL: postojeća datoteka se NIKAD ne prepisuje (prepisivanje bi zarobilo sredstva). Bez DATA_DIR se ne
             stvara (datoteka bi završila u repou).
  keypair()  keypair iz datoteke ili None; address() samo javna adresa.
  refund()   „Vrati ostatak”: sav SOL (minus mrežna naknada) na adresu koju vlasnik upiše; simulacija prije slanja.

Tajna se nikad ne ispisuje, ne logira i ne vraća nijednim HTTP ili MCP odgovorom: ovaj modul je ne vraća nikome osim
potpisivanju u launch.py i refund(). Datoteka nije baza (ne ide u /export ni u izvještaje). Mali iznosi: ako se disk
servisa izgubi, ključ je izgubljen (zato „Vrati ostatak” nakon svake faze).
"""
import base64
import os

FILE = "pump_dev_wallet.key"
BASE_FEE_LAMPORTS = 5000
SYSTEM_PROGRAM = "11111111111111111111111111111111"


def path(env=None):
    env = os.environ if env is None else env
    d = (env.get("DATA_DIR") or "").strip()
    return os.path.join(d, FILE) if d else None


def exists(env=None):
    p = path(env)
    return bool(p) and os.path.exists(p)


def create(env=None):
    """Javna adresa novog novčanika. ValueError kad datoteka već postoji ili nema DATA_DIR."""
    from solders.keypair import Keypair
    p = path(env)
    if not p:
        raise ValueError("DATA_DIR nije postavljen: novčanik se ne stvara (ključ ne smije u repo)")
    if os.path.exists(p):
        raise ValueError("novčanik pokusa već postoji: ne stvara se novi (stari bi ostao bez ključa)")
    kp = Keypair()
    try:
        fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        raise ValueError("novčanik pokusa već postoji: ne stvara se novi")
    with os.fdopen(fd, "w") as f:
        f.write(str(kp))   # base58 tajna (64 bajta), samo u ovoj datoteci
    os.chmod(p, 0o600)
    return str(kp.pubkey())


def keypair(env=None):
    p = path(env)
    if not p or not os.path.exists(p):
        return None
    try:
        from solders.keypair import Keypair
        with open(p, encoding="utf-8") as f:
            return Keypair.from_base58_string(f.read().strip())
    except Exception:  # noqa: BLE001 - nečitljiva datoteka: nema ključa (sadržaj se nikad ne ispisuje)
        return None


def address(env=None):
    kp = keypair(env)
    return str(kp.pubkey()) if kp else None


def refund_plan(rpc, env=None):
    """(od, iznos_lamporti) ili ValueError: sav saldo minus jedna mrežna naknada."""
    kp = keypair(env)
    if kp is None:
        raise ValueError("novčanik pokusa ne postoji")
    bal = int(rpc("getBalance", [str(kp.pubkey()), {"commitment": "confirmed"}])["value"])
    amount = bal - BASE_FEE_LAMPORTS
    if amount <= 0:
        raise ValueError("novčanik pokusa je prazan")
    return str(kp.pubkey()), amount


def refund(dest, user, confirmed, rpc=None, env=None, confirm=None, log=print):
    """Šalje sav SOL (minus naknada) s novčanika pokusa na `dest`. Samo vlasnik, samo uz potvrdu; simulacija prije
    slanja (mora uspjeti, platitelj ne smije izgubiti više od iznosa + naknade). Vraća {"potpis", "iznos_sol", "ok"}."""
    from solders.hash import Hash
    from solders.message import MessageV0
    from solders.pubkey import Pubkey
    from solders.system_program import TransferParams, transfer
    from solders.transaction import VersionedTransaction
    from trade import settings, wallet
    if not settings.is_owner(user):
        raise ValueError("ostatak vraća samo vlasnik")
    if not confirmed:
        raise ValueError("vraćanje samo uz potvrdu u okviru")
    rpc = rpc or wallet.rpc
    try:
        to = Pubkey.from_string((dest or "").strip())
    except Exception:  # noqa: BLE001
        raise ValueError("adresa nije ispravna Solana adresa")
    kp = keypair(env)
    if kp is None:
        raise ValueError("novčanik pokusa ne postoji")
    if to == kp.pubkey():
        raise ValueError("odredište je isti novčanik")
    src, amount = refund_plan(rpc, env)
    bh = Hash.from_string(rpc("getLatestBlockhash", [{"commitment": "confirmed"}])["value"]["blockhash"])
    ix = transfer(TransferParams(from_pubkey=kp.pubkey(), to_pubkey=to, lamports=amount))
    tx = VersionedTransaction(MessageV0.try_compile(kp.pubkey(), [ix], [], bh), [kp])
    b64 = base64.b64encode(bytes(tx)).decode()
    sim = rpc("simulateTransaction", [b64, {"encoding": "base64", "sigVerify": True, "replaceRecentBlockhash": False,
                                            "commitment": "confirmed",
                                            "accounts": {"encoding": "base64", "addresses": [src]}}])["value"]
    if sim.get("err") is not None:
        log(f"pump tokeni: vraćanje ostatka odbijeno, simulacija: {sim['err']}")
        raise ValueError(f"simulacija vraćanja nije uspjela: {sim['err']}")
    sig = str(rpc("sendTransaction", [b64, {"encoding": "base64", "maxRetries": 3}]))
    log(f"pump tokeni: vraćanje ostatka {amount / 1e9:.6f} SOL poslano {sig}")
    ok = (confirm or (lambda s: wallet.confirmed(s, wait_s=60)))(sig)
    log(f"pump tokeni: vraćanje ostatka {'potvrđeno' if ok else 'nije potvrđeno' if ok is None else 'palo na lancu'}")
    return {"potpis": sig, "iznos_sol": amount / 1e9, "ok": ok}
