"""25.11. (vlasnik): /pump-tokeni, lansiranje vlastitih pump.fun tokena bez kupnje (pumptokeni/, ui/pumptokeni.py).

Offline: privremene baze, lažni PumpPortal / IPFS / RPC / DexScreener odgovori, svježe generirani keypairi (nijedan
pravi ključ). Ništa ne ide na mrežu ni na lanac.

    python3 -m unittest tests.test_pump_tokeni_offline
"""
import base64
import importlib
import json
import os
import sqlite3
import stat
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.parse
import urllib.request
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from solders.hash import Hash  # noqa: E402
from solders.instruction import AccountMeta, Instruction  # noqa: E402
from solders.keypair import Keypair  # noqa: E402
from solders.message import MessageV0  # noqa: E402
from solders.pubkey import Pubkey  # noqa: E402
from solders.signature import Signature  # noqa: E402
from solders.transaction import VersionedTransaction  # noqa: E402

from pumptokeni import devwallet, guards, image, launch, outcomes, own, provjera, store  # noqa: E402
from trade import executor, settings  # noqa: E402

NOW = 1_795_000_000
PUMP = Pubkey.from_string(launch.PUMP_PROGRAM)
CB = Pubkey.from_string(launch.COMPUTE_BUDGET)


def fake_tx(payer, mint, price=0, limit=None, signers=None):
    ixs = []
    if limit is not None:
        ixs.append(Instruction(CB, bytes([2]) + int(limit).to_bytes(4, "little"), []))
    if price:
        ixs.append(Instruction(CB, bytes([3]) + int(price).to_bytes(8, "little"), []))
    metas = [AccountMeta(mint, True, True), AccountMeta(payer, True, True)]
    for s in signers or []:
        metas.append(AccountMeta(s, True, False))
    ixs.append(Instruction(PUMP, b"CreateV2", metas))
    msg = MessageV0.try_compile(payer, ixs, [], Hash.default())
    return bytes(VersionedTransaction.populate(msg, [Signature.default()] * msg.header.num_required_signatures))


class FakePost:
    """PumpPortal trade-local + IPFS (pump.fun i Pinata)."""

    def __init__(self, tx_fn=fake_tx, pp_status=200):
        self.calls, self.tx_fn, self.pp_status = [], tx_fn, pp_status

    def __call__(self, url, body, headers, timeout=30):
        self.calls.append((url, body, headers))
        if url == launch.PUMPPORTAL:
            if self.pp_status != 200:
                return self.pp_status, b'{"error":"bad"}'
            b = json.loads(body)
            return 200, self.tx_fn(Pubkey.from_string(b["publicKey"]), Pubkey.from_string(b["mint"]))
        if url == launch.PUMP_IPFS:
            return 200, json.dumps({"metadataUri": "https://ipfs.io/ipfs/bafymeta"}).encode()
        if url == launch.PINATA_UPLOAD:
            return 200, json.dumps({"data": {"cid": f"bafy{len(self.calls)}"}}).encode()
        raise AssertionError(url)


class FakeRpc:
    def __init__(self, sol=0.2, cost=0.009, sim_cost=None, status="confirmed", err=None, sim_err=None, toks=(),
                 tok_post=None, mint_ok=True):
        self.bal = int(sol * 1e9)
        self.cost, self.sim_cost = int(cost * 1e9), int((cost if sim_cost is None else sim_cost) * 1e9)
        self.status, self.err, self.sim_err, self.toks, self.tok_post = status, err, sim_err, list(toks), tok_post
        self.mint_ok = mint_ok
        self.calls = []

    def methods(self):
        return [c[0] for c in self.calls]

    def __call__(self, method, params):
        self.calls.append((method, params))
        if method == "getBalance":
            return {"value": self.bal}
        if method == "getLatestBlockhash":
            return {"value": {"blockhash": str(Hash.default())}}
        if method == "getTokenAccountsByOwner":
            if params[1]["programId"] != launch.TOKEN_PROGRAMS[0]:
                return {"value": []}
            return {"value": [{"pubkey": a, "account": {"data": {"parsed": {"info": {"tokenAmount": {"amount": str(n)}}}}}}
                              for a, n in self.toks]}
        if method == "simulateTransaction":
            if self.sim_err:
                return {"value": {"err": self.sim_err, "logs": ["x"], "accounts": None}}
            accs = [{"lamports": self.bal - self.sim_cost}]
            for a, n in self.toks:
                post = n if self.tok_post is None else self.tok_post
                accs.append({"data": {"parsed": {"info": {"tokenAmount": {"amount": str(post)}}}}})
            return {"value": {"err": None, "logs": [], "accounts": accs}}
        if method == "sendTransaction":
            tx = VersionedTransaction.from_bytes(base64.b64decode(params[0]))
            self.bal -= self.cost
            return str(tx.signatures[0])
        if method == "getSignatureStatuses":
            if self.status is None:
                return {"value": [None]}
            return {"value": [{"confirmationStatus": self.status, "err": self.err}]}
        if method == "getAccountInfo":
            return {"value": {"lamports": 1} if self.mint_ok else None}
        raise AssertionError(method)


def no_search(q):
    return []


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = self.tmp.name
        self.env = {"DATA_DIR": d, "PUMP_TOKENI_DB": os.path.join(d, "pump_tokeni.db")}
        self.p_env = mock.patch.dict(os.environ, self.env)
        self.p_env.start()
        self.stop = os.path.join(d, "STOP")
        self.p_stop = mock.patch.object(executor, "STOP_FILE", self.stop)
        self.p_stop.start()
        self.old_db = settings.DB
        settings.DB = os.path.join(d, "trade.db")
        own.reset()
        self.con = store.connect()
        store.seed(self.con, NOW)
        self.logs = []

    def tearDown(self):
        self.con.close()
        settings.DB = self.old_db
        self.p_stop.stop()
        self.p_env.stop()
        own.reset()
        self.tmp.cleanup()

    def log(self, x):
        self.logs.append(x)

    def tool_wallet(self):
        addr = devwallet.create()
        store.put(self.con, "novcanik", launch.TOOL)
        return addr

    def green(self, ids, rpc=None, post=None, now=NOW):
        rpc, post = rpc or FakeRpc(), post or FakePost()
        steps = provjera.run(self.con, ids, now=now, rpc=rpc, post=post, search=no_search, log=self.log)
        return steps, rpc, post


# ---------- čuvari imena -----------------------------------------------------------------------------------------

def pair(name, sym, liq, chain="solana", addr="X1"):
    return {"chainId": chain, "baseToken": {"name": name, "symbol": sym, "address": addr}, "liquidity": {"usd": liq}}


class Guards(Base):
    def test_seed_drafts_pass(self):
        ds = store.drafts(self.con)
        self.assertEqual([d["simbol"] for d in ds], ["GOBBLE", "DOORB", "CARTGOB", "SRALLY", "Y2027"])
        for d in ds:
            r = guards.check(d, search=no_search, now=NOW)
            self.assertTrue(r["ok"], (d["simbol"], r))
            self.assertFalse(guards.has_url(d["opis"]))

    def test_known_token_same_name_or_symbol_refused(self):
        d = store.drafts(self.con)[0]
        r = guards.check(d, search=lambda q: [pair("Gobble", "GOB", 80_000)], now=NOW)
        self.assertFalse(r["ok"])
        self.assertIn(guards.SIMILAR, r["razlozi"])
        r = guards.check(d, search=lambda q: [pair("Other", "GOBBLE", 30_000, addr="A"),
                                               pair("Other", "GOBBLE", 30_000, addr="A")], now=NOW)
        self.assertFalse(r["ok"])   # zbroj po tokenu 60k
        r = guards.check(d, search=lambda q: [pair("Gobble", "GOBBLE", 49_000)], now=NOW)
        self.assertTrue(r["ok"])

    def test_search_failure_refuses(self):
        def boom(q):
            raise TimeoutError()
        r = guards.check(store.drafts(self.con)[0], search=boom, now=NOW)
        self.assertFalse(r["ok"])

    def test_banned_words_by_name_and_urls(self):
        d = dict(store.drafts(self.con)[0])
        for opis in ("The official coin", "Ovjeren token", "A coin by Elon", "Visit gobble.fun now",
                     "see https://x.com/a", "join t.me/abc", "100x guaranteed"):
            d["opis"] = opis
            self.assertFalse(guards.check(d, search=no_search, now=NOW)["ok"], opis)
        d["opis"] = "A meme about turkey"
        self.assertTrue(guards.check(d, search=no_search, now=NOW)["ok"])
        self.assertFalse(guards.check(d, extra=["turkey"], search=no_search, now=NOW)["ok"])   # vlasnikov popis
        d["ime"] = "Official Gobble"
        self.assertFalse(guards.check(d, search=no_search, now=NOW)["ok"])

    def test_field_limits(self):
        d = dict(store.drafts(self.con)[0], simbol="g")
        self.assertFalse(guards.check(d, search=no_search, now=NOW)["ok"])


class Topics(Base):
    def test_suggest_general_holidays_only(self):
        import datetime as dt
        from ui import pumptokeni
        sug = pumptokeni.suggest(self.con, dt.date(2026, 11, 25))
        titles = [t for t, _ in sug]
        self.assertIn("Christmas", titles)
        self.assertNotIn("Halloween", titles)
        self.assertFalse(any("birthday" in t.lower() for t in titles))


# ---------- slika --------------------------------------------------------------------------------------------------

class Images(unittest.TestCase):
    def test_png_512_deterministic(self):
        a, b = image.generate("Gobble", "GOBBLE"), image.generate("Gobble", "GOBBLE")
        self.assertEqual(a, b)
        self.assertTrue(image.is_png_512(a))
        self.assertNotEqual(a, image.generate("Doorbuster", "DOORB"))

    def test_normalize_owner_image(self):
        from PIL import Image
        import io
        buf = io.BytesIO()
        Image.new("RGB", (800, 300), (10, 20, 30)).save(buf, "JPEG")
        out = image.normalize(buf.getvalue())
        self.assertTrue(image.is_png_512(out))
        with self.assertRaises(ValueError):
            image.normalize(b"not an image")


# ---------- create zahtjev, IPFS, potpis, simulacija -------------------------------------------------------------

class CreateAndSign(Base):
    def test_create_request_fields(self):
        b = launch.create_request("P", "M", "Gobble", "GOBBLE", "https://ipfs.io/ipfs/x", 0.00005)
        self.assertEqual((b["action"], b["amount"], b["denominatedInSol"], b["pool"]), ("create", 0, "true", "pump"))
        self.assertEqual(b["tokenMetadata"], {"name": "Gobble", "symbol": "GOBBLE", "uri": "https://ipfs.io/ipfs/x"})

    def test_ipfs_pumpfun_and_pinata(self):
        post = FakePost()
        png = image.generate("Gobble", "GOBBLE")
        uri = launch.upload_metadata("Gobble", "GOBBLE", "desc", png, "pumpfun", post=post, env={})
        self.assertEqual(uri, "https://ipfs.io/ipfs/bafymeta")
        body = post.calls[0][1]
        self.assertIn(b'name="showName"', body)
        self.assertNotIn(b"twitter", body)
        uri = launch.upload_metadata("Gobble", "GOBBLE", "desc", png, "pinata", post=post, env={"PINATA_JWT": "j"})
        self.assertTrue(uri.startswith(launch.IPFS_GATEWAY))
        meta = post.calls[-1][1]
        self.assertIn(b'"image": "https://ipfs.io/ipfs/', meta)
        for _u, body, hdr in post.calls:
            self.assertNotIn(b"memesonar", body.lower())
            self.assertNotIn("memesonar", json.dumps(hdr).lower())
        with self.assertRaises(RuntimeError):
            launch.upload_metadata("a", "b", "c", png, "pinata", post=post, env={})

    def test_full_launch_with_fake_pumpportal_and_rpc(self):
        self.tool_wallet()
        rpc, post = FakeRpc(), FakePost()
        d = store.drafts(self.con)[0]
        res = launch.launch_one(self.con, d, NOW, rpc=rpc, post=post, search=no_search, log=self.log,
                                wait=lambda s: True)
        self.assertEqual(res["ishod"], "lansiran", res)
        a = store.attempts(self.con)[0]
        self.assertEqual(a["stanje"], "lansiran")
        self.assertAlmostEqual(a["trosak_sol"], 0.009, places=6)
        self.assertIn(a["mint"], own.mints(max_age_s=0))
        self.assertEqual(store.draft(self.con, d["id"])["stanje"], "lansiran")
        self.assertEqual(rpc.methods().count("sendTransaction"), 1)
        self.assertLess(rpc.methods().index("simulateTransaction"), rpc.methods().index("sendTransaction"))
        # potpisano mint keypairom i novčanikom
        sent = [p for m, p in rpc.calls if m == "sendTransaction"][0][0]
        tx = VersionedTransaction.from_bytes(base64.b64decode(sent))
        self.assertTrue(all(s != Signature.default() for s in tx.signatures))
        self.assertEqual(len(tx.signatures), 2)
        txt = "\n".join(self.logs)
        for phase in ("GOBBLE IPFS ok", "GOBBLE create ok", "GOBBLE simulacija ok (trošak", "GOBBLE poslano ",
                      f"GOBBLE potvrđeno, mint {a['mint']}, izmjereni trošak"):
            self.assertIn(phase, txt)
        body = json.loads([b for u, b, h in post.calls if u == launch.PUMPPORTAL][0])
        self.assertEqual((body["amount"], body["mint"]), (0, a["mint"]))

    def test_simulation_over_cap_is_not_sent(self):
        self.tool_wallet()
        rpc = FakeRpc(sim_cost=0.03)
        d = store.drafts(self.con)[0]
        res = launch.launch_one(self.con, d, NOW, rpc=rpc, post=FakePost(), search=no_search, log=self.log,
                                wait=lambda s: True)
        self.assertEqual(res["ishod"], "odbijen")
        self.assertNotIn("sendTransaction", rpc.methods())
        a = store.attempts(self.con)[0]
        self.assertEqual(a["stanje"], "odbijeno")
        self.assertIn("iznad stropa", a["greska"])
        self.assertEqual(store.draft(self.con, d["id"])["stanje"], "odbijen")
        self.assertIn("GOBBLE simulacija greška", "\n".join(self.logs))

    def test_simulation_error_token_debit_priority_and_extra_signer_refused(self):
        self.tool_wallet()
        cases = [(FakeRpc(sim_err={"InstructionError": [0, "x"]}), FakePost()),
                 (FakeRpc(toks=[("TokAcc1111", 500)], tok_post=100), FakePost()),
                 (FakeRpc(), FakePost(tx_fn=lambda p, m: fake_tx(p, m, price=10_000_000, limit=200_000))),
                 (FakeRpc(), FakePost(tx_fn=lambda p, m: fake_tx(p, m, signers=[Keypair().pubkey()])))]
        for rpc, post in cases:
            d = dict(store.drafts(self.con)[1], stanje="u_redu")
            res = launch.launch_one(self.con, d, NOW, rpc=rpc, post=post, search=no_search, log=self.log,
                                    wait=lambda s: True)
            self.assertEqual(res["ishod"], "odbijen", res)
            self.assertNotIn("sendTransaction", rpc.methods())

    def test_pumpportal_error_not_sent(self):
        self.tool_wallet()
        rpc = FakeRpc()
        res = launch.launch_one(self.con, store.drafts(self.con)[0], NOW, rpc=rpc, post=FakePost(pp_status=400),
                                search=no_search, log=self.log, wait=lambda s: True)
        self.assertEqual(res["ishod"], "neuspio")
        self.assertNotIn("sendTransaction", rpc.methods())

    def test_unknown_confirmation_not_resent_then_reconciled(self):
        self.tool_wallet()
        rpc = FakeRpc(status=None)
        d = store.drafts(self.con)[0]
        res = launch.launch_one(self.con, d, NOW, rpc=rpc, post=FakePost(), search=no_search, log=self.log,
                                wait=lambda s: None)
        self.assertEqual(res["ishod"], "nepoznato")
        self.assertEqual(store.draft(self.con, d["id"])["stanje"], "salje")
        self.assertEqual(store.attempts(self.con)[0]["stanje"], "nepoznato")
        with self.assertRaises(ValueError):   # ne može ponovno u pilot dok se potpis ne provjeri
            launch.approve_pilot(self.con, [d["id"]], "Jure", True, NOW)
        rpc.status = "confirmed"
        self.assertEqual(launch.reconcile(self.con, NOW + 300, rpc=rpc, log=self.log), 1)
        self.assertEqual(store.attempts(self.con)[0]["stanje"], "lansiran")
        self.assertEqual(store.draft(self.con, d["id"])["stanje"], "lansiran")

    def test_wait_confirmed_expires(self):
        t = [0.0]
        rpc = FakeRpc(status=None)
        self.assertIsNone(launch.wait_confirmed(rpc, "s", wait_s=5, clock=lambda: t[0],
                                                pause=lambda s: t.__setitem__(0, t[0] + s)))
        self.assertTrue(launch.wait_confirmed(FakeRpc(), "s", wait_s=5, pause=lambda s: None))
        self.assertFalse(launch.wait_confirmed(FakeRpc(err={"x": 1}), "s", wait_s=5, pause=lambda s: None))
        self.assertFalse(launch.mint_exists(FakeRpc(mint_ok=False), "m", pause=lambda s: None))


# ---------- novčanik ------------------------------------------------------------------------------------------------

class Wallets(Base):
    def test_default_is_tool_wallet_and_nothing_without_it(self):
        self.assertEqual(launch.wallet_choice(self.con), launch.TOOL)
        self.assertIsNone(launch.keypair(launch.TOOL))
        store.put(self.con, "pilot", {"odobren_ts": NOW})
        self.assertEqual(launch.blocked_reason(self.con, NOW), "novčanik pokusa nije stvoren")

    def test_off_choice_blocks(self):
        launch.set_wallet(self.con, launch.OFF, "Jure")
        self.assertEqual(launch.wallet_choice(self.con), launch.OFF)
        store.put(self.con, "pilot", {"odobren_ts": NOW})
        self.assertEqual(launch.blocked_reason(self.con, NOW), "novčanik je isključen")

    def test_trading_only_by_owner_tap(self):
        with self.assertRaises(ValueError):
            launch.set_wallet(self.con, launch.TRADING, "Jure", tap=False)
        with self.assertRaises(ValueError):
            launch.set_wallet(self.con, launch.TRADING, "Ivan", tap=True)
        tcon = settings.connect()
        with self.assertRaises(ValueError):
            settings.set_flag(tcon, settings.PUMP_TRGOVACKI, "live", "Ivan", tap=True)
        with self.assertRaises(ValueError):
            settings.set_flag(tcon, settings.PUMP_TRGOVACKI, "live", "Jure", tap=False)
        self.assertEqual(launch.wallet_choice(self.con, tcon), launch.TOOL)
        launch.set_wallet(self.con, launch.TRADING, "Jure", tap=True, tcon=tcon)
        self.assertEqual(launch.wallet_choice(self.con, tcon), launch.TRADING)
        settings.set_flag(tcon, settings.PUMP_TRGOVACKI, "off", "Jure")   # prekidač dolje = isključeno
        self.assertEqual(launch.wallet_choice(self.con, tcon), launch.OFF)
        tcon.close()

    def test_env_separate_wallet(self):
        kp = Keypair()
        store.put(self.con, "novcanik", launch.SEPARATE)
        self.assertEqual(launch.address(launch.SEPARATE, {"PUMP_DEV_PRIVATE_KEY": str(kp)}), str(kp.pubkey()))
        self.assertIsNone(launch.keypair(launch.SEPARATE, {"PUMP_DEV_PRIVATE_KEY": "garbage"}))

    def test_create_file_0600_no_overwrite_no_datadir(self):
        addr = devwallet.create()
        p = devwallet.path()
        self.assertEqual(stat.S_IMODE(os.stat(p).st_mode), 0o600)
        self.assertEqual(devwallet.address(), addr)
        with open(p) as f:
            before = f.read()
        with self.assertRaises(ValueError):
            devwallet.create()
        with open(p) as f:
            self.assertEqual(f.read(), before)
        with self.assertRaises(ValueError):
            devwallet.create(env={})

    def test_refund_simulates_then_sends_all_minus_fee(self):
        self.tool_wallet()
        rpc = FakeRpc(sol=0.15)
        dest = str(Keypair().pubkey())
        with self.assertRaises(ValueError):
            devwallet.refund(dest, "Ivan", True, rpc=rpc)
        with self.assertRaises(ValueError):
            devwallet.refund(dest, "Jure", False, rpc=rpc)
        with self.assertRaises(ValueError):
            devwallet.refund("nije-adresa", "Jure", True, rpc=rpc)
        r = devwallet.refund(dest, "Jure", True, rpc=rpc, confirm=lambda s: True, log=self.log)
        self.assertAlmostEqual(r["iznos_sol"], 0.15 - 0.000005, places=9)
        m = rpc.methods()
        self.assertLess(m.index("simulateTransaction"), m.index("sendTransaction"))
        bad = FakeRpc(sol=0.15, sim_err={"x": 1})
        with self.assertRaises(ValueError):
            devwallet.refund(dest, "Jure", True, rpc=bad)
        self.assertNotIn("sendTransaction", bad.methods())

    def test_secret_never_in_logs_or_page(self):
        self.tool_wallet()
        kp = devwallet.keypair()
        secret_b58, secret_bytes = str(kp), json.dumps(list(bytes(kp)))
        rpc = FakeRpc()
        launch.launch_one(self.con, store.drafts(self.con)[0], NOW, rpc=rpc, post=FakePost(), search=no_search,
                          log=self.log, wait=lambda s: True)
        provjera.run(self.con, [2], now=NOW, rpc=FakeRpc(), post=FakePost(), search=no_search, log=self.log)
        devwallet.refund(str(Keypair().pubkey()), "Jure", True, rpc=FakeRpc(), confirm=lambda s: True, log=self.log)
        from ui import pumptokeni
        with mock.patch.object(pumptokeni, "balance", lambda a, max_age=60: 0.2):
            _t, html = pumptokeni.page({}, "Jure", auto=False)
        blob = "\n".join(self.logs) + html + json.dumps(store.attempts(self.con)) + outcomes.csv_text(self.con)
        self.assertNotIn(secret_b58, blob)
        self.assertNotIn(secret_bytes, blob)
        self.assertNotIn(secret_b58[:40], blob)
        self.assertIn(str(kp.pubkey()), html)


# ---------- stropovi, kill switch, red i pilot ------------------------------------------------------------------

class QueueAndPilot(Base):
    def setUp(self):
        super().setUp()
        self.tool_wallet()

    def test_caps_from_env_hard_max(self):
        self.assertEqual(launch.cfg({})["dnevno"], 5)
        self.assertEqual(launch.cfg({"PUMP_TOKENI_DNEVNO": "50"})["dnevno"], launch.HARD_MAX_DNEVNO)
        self.assertEqual(launch.cfg({})["max_sol"], 0.02)
        self.assertEqual(launch.cfg({"PUMP_TOKENI_MAX_SOL": "5"})["max_sol"], launch.HARD_MAX_SOL)
        self.assertEqual(launch.cfg({})["razmak_s"], 600)
        c = launch.cfg({})
        self.assertEqual((c["min_sol"][launch.TRADING], c["min_sol"][launch.TOOL]), (1.0, 0.03))
        self.assertEqual(launch.cfg({"PUMP_TOKENI_MIN_SOL": "0.5"})["min_sol"][launch.TRADING], 1.0)
        self.assertLessEqual(launch.cfg({"PUMP_TOKENI_PRIORITY_SOL": "1"})["priority_sol"], launch.PRIORITY_MAX_SOL)

    def test_pilot_needs_green_preflight_and_confirmation(self):
        ids = [1, 2]
        with self.assertRaises(ValueError):
            launch.approve_pilot(self.con, ids, "Jure", True, NOW)    # nema provjere
        steps, rpc, post = self.green(ids)
        self.assertTrue(store.get(self.con, "provjera")["zeleno"], steps)
        self.assertNotIn("sendTransaction", rpc.methods())            # suha proba: samo simulacija
        self.assertIn("simulateTransaction", rpc.methods())
        with self.assertRaises(ValueError):
            launch.approve_pilot(self.con, ids, "Jure", False, NOW)
        with self.assertRaises(ValueError):
            launch.approve_pilot(self.con, ids, "Ivan", True, NOW)
        with self.assertRaises(ValueError):
            launch.approve_pilot(self.con, [1, 3], "Jure", True, NOW)   # #3 nije bio u provjeri
        with self.assertRaises(ValueError):
            launch.approve_pilot(self.con, ids, "Jure", True, NOW + 3600)   # provjera zastarjela
        n, _ = launch.approve_pilot(self.con, ids, "Jure", True, NOW)
        self.assertEqual(n, 2)
        self.assertEqual([d["id"] for d in launch.queue(self.con)], [1, 2])

    def test_preflight_red_steps(self):
        open(self.stop, "w").close()
        steps, _, _ = self.green([1])
        self.assertFalse(store.get(self.con, "provjera")["zeleno"])
        self.assertIs(next(s for s in steps if s["k"] == 6)["ok"], False)
        os.remove(self.stop)
        steps, _, _ = self.green([1], rpc=FakeRpc(sol=0.01))
        self.assertIs(steps[0]["ok"], False)
        steps, _, _ = self.green([1], post=FakePost(pp_status=500))
        self.assertIs(next(s for s in steps if s["k"] == 4)["ok"], False)
        steps, _, _ = self.green([1], rpc=FakeRpc(sim_err={"e": 1}))
        self.assertIs(next(s for s in steps if s["k"] == 5)["ok"], False)
        steps, _, _ = self.green([1])
        ipfs = next(s for s in steps if s["k"] == 3)
        self.assertIsNone(ipfs["ok"])                                  # pump.fun IPFS: pri prvom lansiranju
        self.assertIn("pri prvom lansiranju", ipfs["tekst"])
        self.assertTrue(store.get(self.con, "provjera")["zeleno"])
        self.assertTrue(any(x.startswith("pump tokeni provjera: ZELENO") for x in self.logs))
        self.assertIn(launch.PUMP_PROGRAM, next(s for s in steps if s["k"] == 5)["tekst"])

    def _approve(self, ids, rpc=None):
        self.green(ids, rpc=rpc)
        launch.approve_pilot(self.con, ids, "Jure", True, NOW)

    def test_queue_one_at_a_time_with_spacing(self):
        self._approve([1, 2])
        rpc = FakeRpc(sol=0.2)
        kw = dict(rpc=rpc, post=FakePost(), search=no_search, log=self.log)
        with mock.patch.object(launch, "wait_confirmed", lambda r, s: True):
            self.assertEqual(launch.tick(self.con, NOW, **kw), "GOBBLE: lansiran")   # prvi odmah
            self.assertIn("razmak", launch.tick(self.con, NOW + 300, **kw))
            self.assertEqual(rpc.methods().count("sendTransaction"), 1)
            self.assertEqual(launch.tick(self.con, NOW + 601, **kw), "DOORB: lansiran")
            self.assertIsNone(launch.tick(self.con, NOW + 1300, **kw))
        self.assertEqual(rpc.methods().count("sendTransaction"), 2)

    def test_kill_switch_daily_cap_and_min_balance(self):
        self._approve([1, 2, 3])
        rpc = FakeRpc()
        kw = dict(rpc=rpc, post=FakePost(), search=no_search, log=self.log)
        open(self.stop, "w").close()
        self.assertIn("kill switch", launch.tick(self.con, NOW, **kw))
        os.remove(self.stop)
        with mock.patch.dict(os.environ, {"PUMP_TOKENI_DNEVNO": "0"}):
            self.assertIn("dnevni strop", launch.tick(self.con, NOW, **kw))
        rpc.bal = int(0.01e9)
        self.assertIn("ispod", launch.tick(self.con, NOW, **kw))
        self.assertNotIn("sendTransaction", rpc.methods())
        self.assertEqual(len(launch.queue(self.con)), 3)

    def test_first_failure_stops_queue(self):
        self._approve([1, 2])
        rpc = FakeRpc(err={"InstructionError": [0, "x"]})
        kw = dict(rpc=rpc, post=FakePost(), search=no_search, log=self.log)
        with mock.patch.object(launch, "wait_confirmed", lambda r, s: False):
            launch.tick(self.con, NOW, **kw)
            self.assertIn("red je zaustavljen", launch.tick(self.con, NOW + 700, **kw))
        self.assertEqual(rpc.methods().count("sendTransaction"), 1)
        self.assertIn("prvo lansiranje", launch.stopped(self.con)["razlog"])

    def test_first_cost_over_cap_stops_queue(self):
        self._approve([1, 2])
        rpc = FakeRpc(cost=0.03, sim_cost=0.009)
        kw = dict(rpc=rpc, post=FakePost(), search=no_search, log=self.log)
        with mock.patch.object(launch, "wait_confirmed", lambda r, s: True):
            launch.tick(self.con, NOW, **kw)
            self.assertIn("zaustavljen", launch.tick(self.con, NOW + 700, **kw))
        self.assertIn("iznad stropa", launch.stopped(self.con)["razlog"])

    def test_two_later_failures_in_a_row_stop(self):
        self._approve([1, 2, 3, 4])
        rpc = FakeRpc()
        kw = dict(rpc=rpc, post=FakePost(), search=no_search, log=self.log)
        res = iter([True, False, False, True])
        with mock.patch.object(launch, "wait_confirmed", lambda r, s: next(res)):
            launch.tick(self.con, NOW, **kw)
            launch.tick(self.con, NOW + 700, **kw)
            self.assertIsNone(launch.stopped(self.con))
            launch.tick(self.con, NOW + 1400, **kw)
            self.assertIn("dva lansiranja", launch.stopped(self.con)["razlog"])
            self.assertIn("zaustavljen", launch.tick(self.con, NOW + 2100, **kw))
        self.assertEqual(rpc.methods().count("sendTransaction"), 3)

    def test_stop_button_and_reapprove(self):
        self._approve([1])
        launch.stop_queue(self.con, "vlasnik: Zaustavi red", NOW, log=self.log)
        self.assertIn("zaustavljen", launch.blocked_reason(self.con, NOW))
        self._approve([1])
        self.assertIsNone(launch.stopped(self.con))


# ---------- knjiga ishoda ------------------------------------------------------------------------------------------

class Book(Base):
    def _launched(self, mint, ts, cost, skupina="A"):
        d = store.drafts(self.con)[0]
        aid = store.new_attempt(self.con, dict(d, skupina=skupina), launch.TOOL, "PAYER", ts, mint=mint)
        store.update_attempt(self.con, aid, stanje="lansiran", potpis="sig" + mint, trosak_sol=cost)

    def test_checkpoints_fee_net_groups_csv_and_daily_line(self):
        self._launched("MintA", NOW, 0.01)
        self._launched("MintB", NOW, 0.008, "B")
        self.assertEqual(outcomes.due(self.con, NOW + 10), [])
        pairs = [{"baseToken": {"address": "MintA"}, "quoteToken": {"address": outcomes.WSOL}, "priceUsd": "0.00001",
                  "priceNative": "0.0000001", "dexId": "pumpfun", "volume": {"h24": 20_000},
                  "txns": {"h24": {"buys": 30, "sells": 10}}, "marketCap": 9000, "priceChange": {"h1": -50},
                  "info": {"maker": "BUYERWALLET111"}}]
        n = outcomes.check_pass(self.con, NOW + 25 * 3600, fetch=lambda m: pairs, log=self.log)
        self.assertEqual(n, 6)   # 1h, 12h, 24h × 2
        rows, groups = outcomes.book(self.con)
        a = next(r for r in rows if r["mint"] == "MintA")
        # 20k $ × 0,3 % / 100 $ po SOL-u = 0,6 SOL
        self.assertAlmostEqual(a["naknada_sol"], 0.6, places=6)
        self.assertAlmostEqual(a["neto_sol"], 0.59, places=6)
        self.assertEqual(a["max_mcap_usd"], 18000)
        self.assertEqual(a["bondan"], 0)
        b = next(r for r in rows if r["mint"] == "MintB")
        self.assertIsNone(b["naknada_sol"])   # DexScreener ga nije našao: promet nepoznat
        self.assertAlmostEqual(groups["A"]["neto_sol"], 0.59, places=6)
        self.assertAlmostEqual(groups["B"]["neto_sol"], -0.008, places=6)
        csv = outcomes.csv_text(self.con)
        self.assertIn("NEPROVJERENO", csv)
        self.assertNotIn("BUYERWALLET", csv)
        self.assertNotIn("PAYER", csv)
        self.assertEqual(csv.splitlines()[0].split(","), list(outcomes.CSV_COLS))
        self.assertTrue(outcomes.daily_line(self.con, NOW + 26 * 3600, log=self.log))
        self.assertFalse(outcomes.daily_line(self.con, NOW + 26 * 3600 + 60, log=self.log))
        self.assertTrue(self.logs[-1].startswith("pump tokeni: lansirano 2"))
        self.assertEqual(outcomes.due(self.con, NOW + 8 * 86400), [("MintA", "7d"), ("MintB", "7d")])


# ---------- zabrana samotrgovanja ---------------------------------------------------------------------------------

class SelfTrade(Base):
    MINT = "OurMint1111111111111111111111111111111111111"

    def setUp(self):
        super().setUp()
        d = store.drafts(self.con)[0]
        store.new_attempt(self.con, d, launch.TOOL, "P", NOW, mint=self.MINT, stanje="priprema")
        own.reset()

    def test_executor_buy_and_sell(self):
        tcon = executor.connect(os.path.join(self.tmp.name, "trade.db"))
        cfg = executor.load_config()
        first = next(executor.buy_checks(tcon, cfg, 0.1, NOW, False, token=self.MINT, manual=True))
        self.assertEqual(first[:2], (executor.HARD, "vlastiti"))
        res = executor.buy(tcon, cfg, self.MINT, "GOBBLE", size_sol=0.1, now=NOW, manual=True)
        self.assertEqual(res["status"], "blocked")
        self.assertIn("vlastiti token pokusa", res["error"])
        other = list(executor.buy_checks(tcon, cfg, 0.1, NOW, False, token="OtherMint"))
        self.assertFalse(any(k == "vlastiti" for _h, k, _t in other))
        tcon.execute("INSERT INTO positions (token, symbol, opened_ts, mode, status, reason, sol_in, qty_raw, qty_left, "
                     "sol_back, fees_sol) VALUES (?,?,?,?,?,?,0,10,10,0,0)", (self.MINT, "G", NOW, "dry", "open", "x"))
        pid = tcon.execute("SELECT MAX(id) FROM positions").fetchone()[0]
        self.assertEqual(executor.sell(tcon, cfg, pid, close=True, now=NOW)["status"], "blocked")
        tcon.close()

    def test_demo_accounts(self):
        from league import store as lstore
        with self.assertRaises(ValueError) as e:
            lstore.buy(None, "demo", self.MINT, "G", 10, 1.0, 50_000)
        self.assertIn("vlastiti token pokusa", str(e.exception))

    def test_shadow_book_and_scanner_shadow(self):
        from veliki import sjena
        from scan import shadow
        with mock.patch.object(sjena, "on", lambda: True), \
                mock.patch.object(sjena, "_load", side_effect=AssertionError("ne smije doći do knjige")):
            self.assertEqual(sjena.consider(None, self.MINT, (1.0, 1e6), NOW, None, None), 0)
        self.assertFalse(shadow.enter(None, self.MINT, "src", "s", True, NOW, 1.0))

    def test_candidate_lists_and_token_page(self):
        from veliki import midcap, universe
        g = {"mint": self.MINT, "symbol": "GOB", "name": "Gobble", "mcap": 5e7, "liq": 1e6, "vol24": 1e7}
        self.assertEqual(universe.judge(g, NOW), universe.OWN_REASON)
        self.assertEqual(universe.data_judge(g), universe.OWN_REASON)
        p = os.path.join(self.tmp.name, "midcap.db")
        c = sqlite3.connect(p)
        c.execute("CREATE TABLE tokens (mint, symbol, mcap, liq, vol24, trend, pool, src, member)")
        c.executemany("INSERT INTO tokens VALUES (?,?,?,?,?,?,?,?,1)", [(self.MINT, "GOB", 1, 1, 2, 0, "", ""),
                                                                       ("Other", "OTH", 1, 1, 1, 0, "", "")])
        c.commit()
        c.close()
        self.assertEqual([r["mint"] for r in midcap.members(p)], ["Other"])
        from ui import pages
        title, body = pages.token(self.MINT, {})
        self.assertEqual(title, "Vlastiti token pokusa")

    def test_no_module_trades_our_tokens(self):
        """Ništa u pumptokeni/ ne kupuje ni ne prodaje (nema buy/sell akcije prema PumpPortalu ni swapa)."""
        for f in os.listdir(os.path.join(ROOT, "pumptokeni")):
            if f.endswith(".py"):
                with open(os.path.join(ROOT, "pumptokeni", f), encoding="utf-8") as fh:
                    src = fh.read()
                self.assertNotIn('"action": "buy"', src, f)
                self.assertNotIn('"action": "sell"', src, f)
                self.assertNotIn("executor.buy(", src, f)
                self.assertNotIn("jupiter", src.lower(), f)


# ---------- pristup i izbornik (HTTP) -----------------------------------------------------------------------------

class Access(unittest.TestCase):
    def setUp(self):
        from league import roles, store as lstore
        self.roles = roles
        self.old_env = dict(os.environ)
        d = tempfile.mkdtemp()
        self.d = d
        self.old_db = (settings.DB, lstore.DB)
        self.lstore = lstore
        settings.DB, lstore.DB = os.path.join(d, "trade.db"), os.path.join(d, "league.db")
        os.environ.update(DATA_DIR=d, UI_USERS="Ivan,Jure,Ana", UI_PASS_IVAN="ivanpw", UI_PASS_JURE="jurepw",
                          UI_PASS_ANA="anapw", TRADE_OWNER="Jure", UI_ADMINS="Jure,Ana",
                          PUMP_TOKENI_DB=os.path.join(d, "pump_tokeni.db"), PUMP_TOKENI_AUTO_PROVJERA="0",
                          UI_SNAP_DIR=os.path.join(d, "snap"))
        roles.reset_cache()
        import run_ui
        importlib.reload(run_ui)
        self.ui = run_ui
        self.srv = run_ui.ThreadingHTTPServer(("127.0.0.1", 0), run_ui.Handler)
        self.srv.verbose = False
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.srv.server_address[1]}"

    def tearDown(self):
        self.srv.shutdown()
        self.srv.server_close()
        settings.DB, self.lstore.DB = self.old_db
        os.environ.clear()
        os.environ.update(self.old_env)
        self.roles.reset_cache()
        importlib.reload(self.ui)

    def call(self, path, cookie="", data=None):
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *a):
                return None
        hdr = {"Cookie": cookie} if cookie else {}
        if data is not None:
            hdr["Origin"] = self.base
        req = urllib.request.Request(self.base + path, data=data, headers=hdr)
        try:
            r = urllib.request.build_opener(NoRedirect).open(req)
        except urllib.error.HTTPError as e:
            r = e
        return r.code, r.read().decode("utf-8", "replace"), r.headers

    def login(self, name, pw):
        data = urllib.parse.urlencode({"name": name, "pw": pw, "next": "/"}).encode()
        req = urllib.request.Request(self.base + "/prijava", data=data, headers={"Origin": self.base})

        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *a):
                return None
        try:
            r = urllib.request.build_opener(NoRedirect).open(req)
        except urllib.error.HTTPError as e:
            r = e
        return r.headers["Set-Cookie"].split(";")[0]

    def test_owner_only_page_and_menu(self):
        jure, ana, ivan = self.login("Jure", "jurepw"), self.login("Ana", "anapw"), self.login("Ivan", "ivanpw")
        with mock.patch("ui.pumptokeni.balance", lambda a, max_age=60: None):
            code, html, hdr = self.call("/pump-tokeni", jure)
        self.assertEqual(code, 200, html[:500])
        self.assertIn("Pump Fun tokeni", html)
        self.assertIn("GOBBLE", html)
        self.assertIn("noindex", hdr.get("X-Robots-Tag", ""))
        for who in (ana, ivan):
            code, html, _ = self.call("/pump-tokeni", who)
            self.assertEqual(code, 403)
            self.assertNotIn("GOBBLE", html)
            self.assertEqual(self.call("/pump-tokeni/csv", who)[0], 403)
            self.assertEqual(self.call("/pump-tokeni/slika/1", who)[0], 403)
        self.assertEqual(self.call("/pump-tokeni")[0], 401)
        code, html, _ = self.call("/vise", jure)
        self.assertIn('href="/pump-tokeni"', html)
        for who in (ana, ivan):
            code, html, _ = self.call("/vise", who)
            self.assertEqual(code, 200)
            self.assertNotIn("/pump-tokeni", html)
            self.assertNotIn("/pump-tokeni", self.call("/vise/sustav", who)[1])
        # slika i CSV vlasniku
        code, png, hdr = self.call("/pump-tokeni/slika/1", jure)
        self.assertEqual((code, hdr.get("Content-Type", "")[:9]), (200, "image/png"))
        code, csv, _ = self.call("/pump-tokeni/csv", jure)
        self.assertEqual(code, 200)
        self.assertTrue(csv.startswith("nacrt_id,"))
        # POST drugih računa odbijen
        code, _, _ = self.call("/pump-tokeni/stvori", ana, data=b"potvrda=1")
        self.assertIn(code, (403,))
        self.assertFalse(devwallet.exists())
        self.assertIsNone(self.ui.PUBLIC_PATH.match("/pump-tokeni"))
        from ui import html as uh
        self.assertNotIn("/pump-tokeni", uh._pages_json())   # nije u pretrazi ni na karti za sve

    def test_secret_not_in_owner_page(self):
        jure = self.login("Jure", "jurepw")
        addr = devwallet.create()
        kp = devwallet.keypair()
        with mock.patch("ui.pumptokeni.balance", lambda a, max_age=60: 0.2):
            code, html, _ = self.call("/pump-tokeni", jure)
        self.assertEqual(code, 200)
        self.assertIn(addr, html)
        self.assertNotIn(str(kp), html)
        self.assertNotIn(json.dumps(list(bytes(kp))), html)


if __name__ == "__main__":
    unittest.main()
