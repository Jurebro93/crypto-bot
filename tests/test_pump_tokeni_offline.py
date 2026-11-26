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

from pumptokeni import devwallet, guards, image, launch, naknada, outcomes, own, posao, provjera, store  # noqa: E402
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
        self.last_amount = 0

    def creates(self):
        return [json.loads(b) for u, b, h in self.calls if u == launch.PUMPPORTAL]

    def __call__(self, url, body, headers, timeout=30):
        self.calls.append((url, body, headers))
        if url == launch.PUMPPORTAL:
            if self.pp_status != 200:
                return self.pp_status, b'{"error":"bad"}'
            b = json.loads(body)
            self.last_amount = float(b.get("amount") or 0)
            return 200, self.tx_fn(Pubkey.from_string(b["publicKey"]), Pubkey.from_string(b["mint"]))
        if url == launch.PUMP_IPFS:
            return 200, json.dumps({"metadataUri": "https://ipfs.io/ipfs/bafymeta"}).encode()
        if url == launch.PINATA_UPLOAD:
            return 200, json.dumps({"data": {"cid": f"bafy{len(self.calls)}"}}).encode()
        raise AssertionError(url)


class FakeRpc:
    def __init__(self, sol=0.2, cost=0.009, sim_cost=None, status="confirmed", err=None, sim_err=None, toks=(),
                 tok_post=None, mint_ok=True, buy_from=None):
        self.bal = int(sol * 1e9)
        self.cost, self.sim_cost = int(cost * 1e9), int((cost if sim_cost is None else sim_cost) * 1e9)
        self.status, self.err, self.sim_err, self.toks, self.tok_post = status, err, sim_err, list(toks), tok_post
        self.mint_ok = mint_ok
        self.buy_from = buy_from   # FakePost: kupnja iz zadnjeg create zahtjeva (× 1,0125) ide u simulaciju i slanje
        self.calls = []

    def _buy(self):
        return int((self.buy_from.last_amount if self.buy_from else 0) * (1 + launch.BUY_FEE) * 1e9)

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
            accs = [{"lamports": self.bal - self.sim_cost - self._buy()}]
            for a, n in self.toks:
                post = n if self.tok_post is None else self.tok_post
                accs.append({"data": {"parsed": {"info": {"tokenAmount": {"amount": str(post)}}}}})
            return {"value": {"err": None, "logs": [], "accounts": accs}}
        if method == "sendTransaction":
            tx = VersionedTransaction.from_bytes(base64.b64decode(params[0]))
            self.bal -= self.cost + self._buy()
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
        self.plain()
        self.logs = []

    def plain(self, termin=NOW):
        """Stari testovi: sjemenski nacrti bez kupnje, termin odmah (sjeme s večerašnjim rasporedom: SeedSchedule)."""
        self.con.execute("UPDATE nacrti SET kupnja_sol=0, termin_ts=?", (termin,))
        self.con.commit()

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
        self.assertIn("potvrđeno s lanca 25.11.2026.", csv)
        self.assertNotIn("NEPROVJERENO", csv)
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


# ---------- 26.11.: nadzorna ploča, snimci, opisi, slike iz datoteke, podizanje naknade, „Odobri pilot” -----------

def dex_pair(mint, vol24=20_000, vol1=1_000, vol5=50, buys=30, sells=10, mcap=9000, dex="pumpfun"):
    return {"baseToken": {"address": mint}, "quoteToken": {"address": outcomes.WSOL}, "priceUsd": "0.00001",
            "priceNative": "0.0000001", "dexId": dex, "liquidity": {"usd": 5000},
            "volume": {"m5": vol5, "h1": vol1, "h6": vol1 * 3, "h24": vol24},
            "txns": {"h1": {"buys": 3, "sells": 1}, "h24": {"buys": buys, "sells": sells}}, "marketCap": mcap,
            "priceChange": {"h1": -50}, "info": {"maker": "BUYERWALLET111"}}


class Dashboard(Base):
    def _launched(self, mint, ts, cost, did=1, payer=None):
        d = store.draft(self.con, did)
        aid = store.new_attempt(self.con, d, launch.TOOL, payer or str(Keypair().pubkey()), ts, mint=mint)
        store.update_attempt(self.con, aid, stanje="lansiran", potpis="sig" + mint, trosak_sol=cost)
        store.set_state(self.con, did, "lansiran", ts)

    def test_refresh_one_request_only_our_tokens_and_tiles(self):
        self._launched("MintA", NOW, 0.01, 1)
        self._launched("MintB", NOW, 0.008, 2)
        aid = store.new_attempt(self.con, store.draft(self.con, 3), launch.TOOL, "P", NOW, mint="MintFail",
                                stanje="neuspio")
        store.update_attempt(self.con, aid, trosak_sol=0.002)
        calls = []

        def fetch(m):
            calls.append(list(m))
            return [dex_pair("MintA"), dex_pair("MintB", vol24=0, vol1=0, vol5=0, buys=0, sells=0),
                    dex_pair("SomeoneElse", vol24=9e9)]
        n, pts = outcomes.refresh(self.con, NOW + 3 * 3600, fetch=fetch, log=self.log)
        self.assertEqual(calls, [["MintA", "MintB"]])           # jedan zahtjev, samo naši lansirani
        self.assertEqual((n, pts), (2, 2))                        # snimci + dospjela točka +1 h iz istog odgovora
        db = outcomes.dashboard(self.con, NOW + 3 * 3600)
        t = db["tiles"]
        self.assertEqual(t["lansirano"], 2)
        self.assertAlmostEqual(t["promet_usd"], 20_000)
        self.assertAlmostEqual(t["promet_sol"], 200.0)            # 100 $ po SOL-u
        self.assertEqual((t["kupnje"], t["prodaje"]), (30, 10))
        self.assertAlmostEqual(t["naknada_sol"], 0.6)             # 20k × 0,30 % / 100
        self.assertAlmostEqual(t["trosak_sol"], 0.02)             # i neuspjelo lansiranje se broji u trošak
        self.assertAlmostEqual(t["neto_sol"], 0.58)
        self.assertEqual(t["s_prometom"], 1)
        self.assertEqual(t["osvjezeno_ts"], NOW + 3 * 3600)
        a = next(r for r in db["rows"] if r["mint"] == "MintA")
        self.assertEqual((a["promet_m5"], a["promet_h1"], a["promet_h24"]), (50, 1000, 20_000))
        self.assertEqual(a["max_mcap_usd"], 18000)
        self.assertEqual(a["bondan"], 0)
        # drugi prolaz isti sat: novi snimak, nema novih točaka; ništa ne ide za tokene koji nisu naši
        outcomes.refresh(self.con, NOW + 3 * 3600 + 600, fetch=fetch, log=self.log)
        self.assertEqual(len(outcomes.snapshots(self.con, "MintA")), 2)
        self.assertEqual(self.con.execute("SELECT COUNT(*) FROM snimci WHERE mint='SomeoneElse'").fetchone()[0], 0)

    def test_old_tokens_once_a_day_and_cumulative(self):
        self._launched("MintOld", NOW, 0.01, 1)
        calls = []

        def fetch(m):
            calls.append(list(m))
            return [dex_pair("MintOld", vol24=1000, buys=5, sells=5)]
        t0 = NOW + 8 * 86400
        outcomes.refresh(self.con, t0, fetch=fetch, log=self.log)
        self.assertEqual(len(calls), 1)
        self.assertEqual(outcomes.refresh(self.con, t0 + 600, fetch=fetch, log=self.log), (0, 0))
        self.assertEqual(len(calls), 1)                            # stariji od 7 dana: jednom dnevno
        outcomes.refresh(self.con, t0 + 86400, fetch=fetch, log=self.log)
        self.assertEqual(len(calls), 2)
        sn = [{"ts": NOW + h * 3600, "promet_h24": v} for h, v in ((1, 10), (23, 100), (25, 300), (49, 200), (60, 50))]
        self.assertEqual(outcomes._cumulative(sn[:2], NOW, "promet_h24"), 100)   # mlađi od 24 h: zadnji
        self.assertEqual(outcomes._cumulative(sn, NOW, "promet_h24"), 500)       # dani 1 i 2 (donja granica)

    def test_snapshot_hard_cap(self):
        self._launched("MintA", NOW, 0.01, 1)
        with mock.patch.object(outcomes, "MAX_SNAPS", 3):
            for k in range(6):
                outcomes.refresh(self.con, NOW + 600 * (k + 1), fetch=lambda m: [dex_pair("MintA")], log=self.log)
        ts = [s["ts"] for s in outcomes.snapshots(self.con, "MintA")]
        self.assertEqual(ts, [NOW + 600 * 4, NOW + 600 * 5, NOW + 600 * 6])
        self.assertEqual(outcomes.MAX_SNAPS, 7 * 144)

    def test_job_refreshes_every_10_min_min_5(self):
        self._launched("MintA", NOW, 0.01, 1)
        self.assertEqual(outcomes.refresh_every_s({}), 600)
        self.assertEqual(outcomes.refresh_every_s({"PUMP_TOKENI_OSVJEZI_MIN": "2"}), 300)
        self.assertEqual(outcomes.refresh_every_s({"PUMP_TOKENI_OSVJEZI_MIN": "x"}), 600)
        calls = []
        self.con.commit()
        with mock.patch.object(outcomes, "_fetch", lambda m: calls.append(m) or [dex_pair("MintA")]), \
                mock.patch.object(outcomes, "read_vaults", lambda con, now, log=print: {}):
            for k in range(25):   # posao svake minute, 25 min
                posao.tick(NOW + 7200 + 60 * k, log=self.log)
        self.assertEqual(len(calls), 3)                            # 0., 10. i 20. minuta

    def test_vault_pda_and_reading(self):
        kp = Keypair()
        self._launched("MintA", NOW, 0.01, 1, payer=str(kp.pubkey()))
        v = outcomes.vault_pda(str(kp.pubkey()))
        exp = Pubkey.find_program_address([b"creator-vault", bytes(kp.pubkey())], PUMP)[0]
        self.assertEqual(v, str(exp))
        rpc = FakeRpc(sol=0.05)
        out = outcomes.read_vaults(self.con, NOW, rpc=rpc, log=self.log)
        self.assertAlmostEqual(out[str(kp.pubkey())]["za_podici_sol"], 0.05 - outcomes.RENT_EMPTY_LAMPORTS / 1e9)
        self.assertEqual([p[0] for m, p in rpc.calls if m == "getBalance"], [v])
        self.assertAlmostEqual(outcomes.dashboard(self.con, NOW)["tiles"]["za_podici_sol"], 0.04910912)

    def test_page_dashboard_on_top_from_db_without_network(self):
        self._launched("MintA", NOW, 0.01, 1)
        outcomes.refresh(self.con, NOW + 3600, fetch=lambda m: [dex_pair("MintA", dex="pumpswap")], log=self.log)
        outcomes.refresh(self.con, NOW + 4200, fetch=lambda m: [dex_pair("MintA", vol24=30_000, dex="pumpswap")],
                         log=self.log)
        from ui import pumptokeni
        with mock.patch.object(pumptokeni, "balance", lambda a, max_age=60: 0.2), \
                mock.patch.object(outcomes, "_fetch", side_effect=AssertionError("ploča ne zove mrežu")):
            _t, html = pumptokeni.page({}, "Jure", auto=False)
            frag = pumptokeni.dash_fragment()
        self.assertLess(html.index("Nadzorna ploča"), html.index("id=ptw"))
        self.assertNotIn("<ol class=pt-steps>", html)
        self.assertIn(frag[:200], html)
        self.assertIn("https://pump.fun/coin/MintA' target=_blank rel='noopener noreferrer'", frag)
        self.assertIn("https://dexscreener.com/solana/MintA' target=_blank rel='noopener noreferrer'", frag)
        self.assertIn("<polyline", frag)
        self.assertIn("procjena samo za krivulju", frag)            # bondan: druga ljestvica
        self.assertIn("Podigni naknadu", frag)
        self.assertIn("/pump-tokeni/ploca", html)                  # samo-osvježavanje fragmenta

    def test_page_before_wallet_shows_steps(self):
        from ui import pumptokeni
        with mock.patch.object(pumptokeni, "balance", lambda a, max_age=60: None):
            _t, html = pumptokeni.page({}, "Jure", auto=False)
        self.assertIn("<ol class=pt-steps>", html)
        self.assertNotIn("<section id=ptdash", html)
        self.assertIn("Stvori novčanik", html)
        self.assertIn("<details id=ptw class=card open>", html)    # novčanik proširen dok ne postoji
        for internal in ("SOLANA_PRIVATE_KEY", "PUMP_DEV_PRIVATE_KEY", "NEPROVJERENO"):
            self.assertNotIn(internal, html)


class SeedTextAndImages(Base):
    def test_new_descriptions_pass_guards_and_say_do_not_buy(self):
        want = {"GOBBLE": "A Thanksgiving turkey. No roadmap, no promises, just vibes.",
                "DOORB": "A Black Friday doorbuster with no discount and no pitch.",
                "CARTGOB": "The goblin who lives in your abandoned cart.",
                "SRALLY": "Named after the Santa rally. That is a seasonal story, not a promise.",
                "Y2027": "A New Year 2027 token, launched early. No promises."}
        for tema, datum, ime, sym, opis, *_rest in store.SEED:
            self.assertEqual(opis, want[sym])
            r = guards.check({"ime": ime, "simbol": sym, "opis": opis, "slika": b"x"}, search=no_search, now=NOW)
            self.assertTrue(r["ok"], (sym, r))
        self.assertEqual([d["opis"] for d in store.drafts(self.con)], [x[4] for x in store.SEED])

    def _old_db(self):
        p = os.path.join(self.tmp.name, "old.db")
        con = store.connect(p)
        for tema, datum, ime, sym, *_o in store.SEED:
            con.execute("INSERT INTO nacrti (tema, datum_teme, ime, simbol, opis, slika, skupina, stanje, napravljen_ts,"
                        " promijenjen_ts, provjera) VALUES (?,?,?,?,?,?,?,'nacrt',?,?,'{\"ok\":true}')",
                        (tema, datum, ime, sym, store.SEED_2511[sym], image.generate(ime, sym), store.SKUPINA_0, NOW, NOW))
        con.commit()
        store.put(con, "seed_2511", NOW)
        return con

    def test_migration_only_untouched_drafts_once(self):
        con = self._old_db()
        store.update_draft(con, 2, {"opis": "My own words."}, NOW)                # vlasnik uredio DOORB
        con.execute("UPDATE nacrti SET slika_vlastita=1 WHERE id=3")             # vlasnikova slika CARTGOB
        con.execute("UPDATE nacrti SET stanje='lansiran' WHERE id=4")             # SRALLY lansiran
        con.commit()
        self.assertEqual(store.seed(con, NOW + 10), 0)
        ds = {d["simbol"]: d for d in store.drafts(con)}
        new = {x[3]: x[4] for x in store.SEED}
        self.assertEqual(ds["GOBBLE"]["opis"], new["GOBBLE"])
        self.assertEqual(ds["Y2027"]["opis"], new["Y2027"])
        self.assertIsNone(ds["GOBBLE"]["provjera"])                              # nova provjera imena
        self.assertEqual(ds["DOORB"]["opis"], "My own words.")
        self.assertEqual(ds["CARTGOB"]["opis"], store.SEED_2511["CARTGOB"])
        self.assertIsNone(ds["CARTGOB"]["termin_ts"])                            # vlasnikova slika: ne dira se
        self.assertEqual(ds["SRALLY"]["opis"], store.SEED_2511["SRALLY"])
        before = [(d["opis"], d["promijenjen_ts"]) for d in store.drafts(con)]
        store.seed(con, NOW + 20)
        self.assertEqual([(d["opis"], d["promijenjen_ts"]) for d in store.drafts(con)], before)   # idempotentno
        con.close()

    def _png_with_metadata(self, path, color=(200, 30, 30)):
        from PIL import Image, PngImagePlugin
        info = PngImagePlugin.PngInfo()
        info.add_text("Author", "SECRETNAME")
        Image.new("RGB", (900, 600), color).save(path, "PNG", pnginfo=info)

    def test_seed_image_from_file_else_generator(self):
        d = os.path.join(self.tmp.name, "slike")
        os.makedirs(d)
        self._png_with_metadata(os.path.join(d, "GOBBLE.png"))
        self._png_with_metadata(os.path.join(d, "OTHER.png"))
        png = store.seed_image("Gobble", "GOBBLE", slike_dir=d)
        self.assertTrue(image.is_png_512(png))
        self.assertNotIn(b"SECRETNAME", png)
        self.assertNotEqual(png, image.generate("Gobble", "GOBBLE"))
        self.assertEqual(store.seed_image("Other", "OTHER", slike_dir=d), image.generate("Other", "OTHER"))
        self.assertEqual(store.seed_image("Doorbuster", "DOORB", slike_dir=d), image.generate("Doorbuster", "DOORB"))
        self.assertIsNone(image.file_bytes("../GOBBLE", d))
        # migracija: nedirani nacrt dobiva sliku iz datoteke jednom; vlasnikova slika ostaje
        store.set_image(self.con, 5, b"own", True)
        self.assertEqual(store.migrate_seed(self.con, NOW, slike_dir=d), 1)
        self.assertEqual(store.draft(self.con, 1)["slika"], png)
        self.assertEqual(store.migrate_seed(self.con, NOW, slike_dir=d), 0)
        self._png_with_metadata(os.path.join(d, "Y2027.png"))
        self.assertEqual(store.migrate_seed(self.con, NOW, slike_dir=d), 0)    # Y2027 ima vlasnikovu sliku
        self.assertEqual(store.draft(self.con, 5)["slika"], b"own")
        self.assertTrue(os.path.exists(os.path.join(ROOT, "pumptokeni", "slike", ".gitkeep")))


def claim_tx(payer, signers=(), program=PUMP, price=0, limit=None):
    ixs = []
    if limit is not None:
        ixs.append(Instruction(CB, bytes([2]) + int(limit).to_bytes(4, "little"), []))
    if price:
        ixs.append(Instruction(CB, bytes([3]) + int(price).to_bytes(8, "little"), []))
    metas = [AccountMeta(payer, True, True)] + [AccountMeta(s, True, False) for s in signers]
    ixs.append(Instruction(program, b"collect_creator_fee", metas))
    msg = MessageV0.try_compile(payer, ixs, [], Hash.default())
    return bytes(VersionedTransaction.populate(msg, [Signature.default()] * msg.header.num_required_signatures))


class ClaimPost:
    def __init__(self, tx_fn=claim_tx):
        self.calls, self.tx_fn = [], tx_fn

    def __call__(self, url, body, headers, timeout=30):
        self.calls.append((url, json.loads(body)))
        assert url == launch.PUMPPORTAL, url
        return 200, self.tx_fn(Pubkey.from_string(json.loads(body)["publicKey"]))


class ClaimFee(Base):
    def setUp(self):
        super().setUp()
        self.addr = self.tool_wallet()

    def test_claim_simulates_sends_and_measures(self):
        rpc, post = FakeRpc(sol=0.1, cost=-0.05, sim_cost=-0.05), ClaimPost()
        with self.assertRaises(ValueError):
            naknada.claim(self.con, "Ivan", True, NOW, rpc=rpc, post=post)
        with self.assertRaises(ValueError):
            naknada.claim(self.con, "Jure", False, NOW, rpc=rpc, post=post)
        self.assertEqual(post.calls, [])
        r = naknada.claim(self.con, "Jure", True, NOW, rpc=rpc, post=post, wait=lambda s: True, log=self.log)
        self.assertTrue(r["ok"])
        self.assertAlmostEqual(r["iznos_sol"], 0.05, places=9)
        self.assertEqual(post.calls[0][1], {"publicKey": self.addr, "action": "collectCreatorFee",
                                            "priorityFee": launch.cfg()["priority_sol"], "pool": "pump"})
        m = rpc.methods()
        self.assertLess(m.index("simulateTransaction"), m.index("sendTransaction"))
        self.assertAlmostEqual(outcomes.claimed_sol(self.con), 0.05, places=9)
        tx = VersionedTransaction.from_bytes(base64.b64decode([p for mm, p in rpc.calls if mm == "sendTransaction"][0][0]))
        self.assertEqual(len(tx.signatures), 1)
        self.assertNotEqual(tx.signatures[0], Signature.default())

    def test_claim_refusals_never_send(self):
        cases = [(FakeRpc(sim_cost=0.001), ClaimPost(), "iznad stropa"),                 # trošak iznad stropa
                 (FakeRpc(sim_cost=0.0), ClaimPost(), "ništa za podići"),                # ne bi dobio ništa
                 (FakeRpc(sim_cost=-0.05), ClaimPost(lambda p: claim_tx(p, signers=[Keypair().pubkey()])), "potpisa"),
                 (FakeRpc(sim_cost=-0.05), ClaimPost(lambda p: claim_tx(p, program=Keypair().pubkey())), "pump.fun"),
                 (FakeRpc(sim_cost=-0.05), ClaimPost(lambda p: claim_tx(p, price=10_000_000, limit=200_000)), "priority"),
                 (FakeRpc(sim_err={"x": 1}), ClaimPost(), "simulacija")]
        for rpc, post, word in cases:
            with self.assertRaises(ValueError) as e:
                naknada.claim(self.con, "Jure", True, NOW, rpc=rpc, post=post, wait=lambda s: True, log=self.log)
            self.assertIn(word, str(e.exception))
            self.assertNotIn("sendTransaction", rpc.methods())
        open(self.stop, "w").close()
        post = ClaimPost()
        with self.assertRaises(ValueError):
            naknada.claim(self.con, "Jure", True, NOW, rpc=FakeRpc(sim_cost=-0.05), post=post)
        self.assertEqual(post.calls, [])
        self.assertEqual(outcomes.claimed_sol(self.con), 0.0)

    def test_claim_post_owner_only_via_page(self):
        from ui import pumptokeni
        self.assertIn("err=", pumptokeni.post("/pump-tokeni/podigni", {"potvrda": "1"}, "Ivan"))
        with mock.patch.object(naknada, "claim", side_effect=AssertionError("ne smije")):
            self.assertIn("samo%20vlasnik", pumptokeni.post("/pump-tokeni/podigni", {"potvrda": "1"}, "Ana"))


class PilotButton(Base):
    def setUp(self):
        super().setUp()
        from ui import pumptokeni
        self.ui = pumptokeni
        self.p_bal = mock.patch.object(pumptokeni, "balance", lambda a, max_age=60: self.bal)
        self.p_bal.start()
        self.bal = 0.2

    def tearDown(self):
        self.p_bal.stop()
        super().tearDown()

    def gate(self):
        ws = self.ui.wallet_state(self.con, now=NOW)
        return self.ui.pilot_gate(self.con, ws, now=NOW)

    def test_reasons_until_everything_is_ready(self):
        g = self.gate()
        self.assertTrue(any("nema novčanika" in x for x in g), g)
        self.tool_wallet()
        self.bal = 0.01
        g = self.gate()
        self.assertTrue(any("treba još" in x for x in g), g)
        self.assertTrue(any("PINATA_JWT" in x for x in g), g)
        self.assertTrue(any("nije pokrenuta" in x for x in g), g)
        self.bal = 0.2
        with mock.patch.dict(os.environ, {"PINATA_JWT": "j"}):
            provjera.run(self.con, [1, 2], now=NOW, rpc=FakeRpc(), post=FakePost(), get=lambda u, h: 200,
                         search=no_search, log=self.log)
            with mock.patch("time.time", lambda: NOW):
                self.assertEqual(self.gate(), [])
                _t, html = self.ui.page({}, "Jure", auto=False)
            self.assertIn("<button class=pt-btn type=submit form=ptl>✅ Odobri pilot</button>", html)
            self.assertEqual(self.ui.pilot_gate(self.con, self.ui.wallet_state(self.con, now=NOW), now=NOW + 3600),
                             ["provjera je starija od 30 min: ponovi je"])
        _t, html = self.ui.page({}, "Jure", auto=False)
        self.assertIn("form=ptl disabled>✅ Odobri pilot", html)
        self.assertIn("PINATA_JWT", html)                           # samo u poruci što nedostaje



# ---------- 26.11. večer: vlastita kupnja, poveznice, raspored, objava, kupci u 10 min, suha proba ---------------

T19 = 1795716000   # 26.11.2026. 19:00 CET


class OwnBuy(Base):
    def setUp(self):
        super().setUp()
        self.tool_wallet()
        self.con.execute("UPDATE nacrti SET kupnja_sol=0.04 WHERE id=1")
        self.con.commit()

    def test_parse_cap_and_request(self):
        self.assertEqual(store.parse_kupnja("0,04"), 0.04)
        self.assertEqual(store.parse_kupnja(""), 0.0)
        self.assertEqual(store.parse_kupnja("0.1"), 0.1)
        for bad in ("0.1001", "0,2", "-0.01", "abc", "nan", "inf"):
            with self.assertRaises(ValueError, msg=bad):
                store.parse_kupnja(bad)
        b = launch.create_request("P", "M", "Gobble", "GOBBLE", "u", 0.00005, 0.04)
        self.assertEqual((b["amount"], b["denominatedInSol"], b["action"]), (0.04, "true", "create"))
        self.assertEqual(set(b["tokenMetadata"]), {"name", "symbol", "uri"})
        with self.assertRaises(ValueError):
            launch.create_request("P", "M", "G", "G", "u", 0, 0.11)
        from ui import pumptokeni
        r = pumptokeni.post("/pump-tokeni/uredi", {"id": "2", "kupnja_sol": "0,15"}, "Jure")
        self.assertIn("err=", r)
        self.assertIn("tvrdog", urllib.parse.unquote(r))
        self.assertEqual(store.draft(self.con, 2)["kupnja_sol"], 0)
        self.assertIn("ok=", pumptokeni.post("/pump-tokeni/uredi", {"id": "2", "kupnja_sol": "0,04"}, "Jure"))
        self.assertEqual(store.draft(self.con, 2)["kupnja_sol"], 0.04)

    def test_launch_with_buy_cost_split_and_sim_cap(self):
        post = FakePost()
        rpc = FakeRpc(sol=0.2, buy_from=post)
        res = launch.launch_one(self.con, store.draft(self.con, 1), NOW, rpc=rpc, post=post, search=no_search,
                                log=self.log, wait=lambda s: True)
        self.assertEqual(res["ishod"], "lansiran", res)
        self.assertEqual(post.creates()[0]["amount"], 0.04)              # u istom create zahtjevu
        a = store.attempts(self.con)[0]
        self.assertAlmostEqual(a["ukupno_sol"], 0.009 + 0.04 * 1.0125, places=9)
        self.assertAlmostEqual(a["trosak_sol"], 0.009 + 0.04 * 0.0125, places=9)   # kupnja nije trošak
        self.assertEqual((a["kupnja_sol"], a["kupnja_trazena"], a["upozorenje"]), (0.04, 0.04, None))
        self.assertAlmostEqual(launch.sim_cap(launch.cfg(), 0.04), 0.02 + 0.04 * 1.03)
        self.assertIn("vlastita kupnja 0.04 SOL", "\n".join(self.logs))
        # simulacija iznad stropa trošak + kupnja × 1,03 → ne šalje
        self.con.execute("UPDATE nacrti SET stanje='nacrt' WHERE id=2")
        self.con.execute("UPDATE nacrti SET kupnja_sol=0.04 WHERE id=2")
        self.con.commit()
        post2 = FakePost()
        rpc2 = FakeRpc(sim_cost=0.022, buy_from=post2)   # 0,022 + 0,0405 = 0,0625 > 0,0612
        res = launch.launch_one(self.con, store.draft(self.con, 2), NOW, rpc=rpc2, post=post2, search=no_search,
                                log=self.log, wait=lambda s: True)
        self.assertEqual(res["ishod"], "odbijen")
        self.assertNotIn("sendTransaction", rpc2.methods())

    def test_token_account_may_receive_never_lose(self):
        for post_amt, want in ((600, "lansiran"), (400, "odbijen")):
            self.con.execute("UPDATE nacrti SET stanje='nacrt'")
            self.con.commit()
            post = FakePost()
            rpc = FakeRpc(toks=[("TokAcc1111", 500)], tok_post=post_amt, buy_from=post)
            res = launch.launch_one(self.con, store.draft(self.con, 1), NOW, rpc=rpc, post=post, search=no_search,
                                    log=self.log, wait=lambda s: True)
            self.assertEqual(res["ishod"], want)
            if want == "odbijen":
                self.assertNotIn("sendTransaction", rpc.methods())

    def test_reserve_skips_buy_with_warning_then_waits(self):
        post = FakePost()
        rpc = FakeRpc(sol=0.08, buy_from=post)            # 0,08 − (0,02 + 0,0412) < 0,03 → bez kupnje
        res = launch.launch_one(self.con, store.draft(self.con, 1), NOW, rpc=rpc, post=post, search=no_search,
                                log=self.log, wait=lambda s: True)
        self.assertEqual(res["ishod"], "lansiran")
        self.assertEqual(post.creates()[0]["amount"], 0)
        a = store.attempts(self.con)[0]
        self.assertEqual((a["kupnja_sol"], a["kupnja_trazena"], a["upozorenje"]), (0.0, 0.04, launch.BUY_SKIP_WARN))
        self.assertAlmostEqual(a["trosak_sol"], 0.009, places=9)
        self.assertIn("vlastita kupnja preskočena: rezerva", "\n".join(self.logs))
        from ui import pumptokeni
        with mock.patch.object(pumptokeni, "balance", lambda a, max_age=60: 0.07):
            _t, html = pumptokeni.page({}, "Jure", auto=False)
        self.assertIn("vlastita kupnja preskočena: rezerva", html)
        # ni bez kupnje ne ostaje rezerva → ne lansira (čeka), ništa ne ide PumpPortalu ni na lanac
        post, rpc = FakePost(), FakeRpc(sol=0.045)
        res = launch.launch_one(self.con, store.draft(self.con, 2), NOW, rpc=rpc, post=post, search=no_search,
                                log=self.log, wait=lambda s: True)
        self.assertEqual(res["ishod"], "ceka")
        self.assertIn("rezervu", res["tekst"])
        self.assertEqual(post.creates(), [])
        self.assertNotIn("sendTransaction", rpc.methods())
        self.assertEqual(launch.cfg({"PUMP_TOKENI_REZERVA_SOL": "0.05"})["rezerva_sol"], 0.05)
        self.assertEqual(launch.cfg({})["rezerva_sol"], 0.03)

    def test_preflight_cost_includes_buy(self):
        post = FakePost()
        steps, rpc, _ = self.green([1, 2], rpc=FakeRpc(buy_from=post), post=post)
        self.assertTrue(store.get(self.con, "provjera")["zeleno"], steps)
        self.assertIn("s vlastitim kupnjama", steps[0]["tekst"])
        per = {r["simbol"]: r for r in store.get(self.con, "provjera")["nacrti"]}
        fee = 2 * launch.BASE_FEE_LAMPORTS / 1e9                           # simulacija broji i osnovnu naknadu
        self.assertAlmostEqual(per["GOBBLE"]["sol"], 0.009 + 0.0405 + fee, places=9)
        self.assertAlmostEqual(per["DOORB"]["sol"], 0.009 + fee, places=9)
        self.assertEqual([c["amount"] for c in post.creates()], [0.04, 0])
        self.assertNotIn("sendTransaction", rpc.methods())

    def test_no_sell_path_and_refund_only_sol(self):
        import re
        srcs = [os.path.join(ROOT, "pumptokeni", f) for f in os.listdir(os.path.join(ROOT, "pumptokeni"))
                if f.endswith(".py")] + [os.path.join(ROOT, "ui", "pumptokeni.py")]
        for f in srcs:
            with open(f, encoding="utf-8") as fh:
                src = fh.read()
            self.assertIsNone(re.search(r"""["']action["']\s*:\s*["'](sell|buy)["']""", src), f)
            self.assertIsNone(re.search(r"""["'](sell|swap)["']""", src), f)
            for bad in ("executor.sell(", "executor.buy(", "jup.ag", "jupiter", "raydium", "/api/trade\"", "denominatedInSol\": \"false"):
                self.assertNotIn(bad, src, f)
        rpc = FakeRpc(sol=0.15)
        devwallet.refund(str(Keypair().pubkey()), "Jure", True, rpc=rpc, confirm=lambda s: True, log=self.log)
        tx = VersionedTransaction.from_bytes(base64.b64decode([p for m, p in rpc.calls if m == "sendTransaction"][0][0]))
        self.assertEqual(launch.programs(tx.message), [devwallet.SYSTEM_PROGRAM])   # samo SOL prijenos
        from ui import pumptokeni
        with mock.patch.object(pumptokeni, "balance", lambda a, max_age=60: 0.2):
            _t, html = pumptokeni.page({}, "Jure", auto=False)
        self.assertIn("kupljeni tokeni ostaju u novčaniku; alat ih ne prodaje", html)


class Links(Base):
    def test_link_rules(self):
        ok = [("twitter", "https://x.com/gobble"), ("twitter", "https://twitter.com/a_b"),
              ("twitter", "https://www.x.com/a"), ("telegram", "https://t.me/gobble"),
              ("website", "https://gobble.example.org/x?y=1")]
        for k, u in ok:
            self.assertIsNone(guards.link_reason(k, u), (k, u))
        bad = [("twitter", "http://x.com/a"), ("twitter", "https://evil.com/x"), ("twitter", "https://x.com.evil.io/a"),
               ("twitter", "https://x.com/"), ("telegram", "https://telegram.me/a"), ("telegram", "https://t.me"),
               ("website", "https://a b.com"), ("website", "https://a.com/\x07"), ("website", "https://" + "a" * 95 + ".com"),
               ("website", "https://user@evil.com/"), ("website", "https://a.com:8443/"), ("website", "ftp://a.com"),
               ("website", "javascript:alert(1)"), ("website", "https://localhost/")]
        for k, u in bad:
            self.assertIsNotNone(guards.link_reason(k, u), (k, u))
        for u in ("https://memesonar.app", "https://www.memesonar.app/x", "https://a.memesonar.app"):
            self.assertIn("kvačicu", guards.link_reason("website", u))
            self.assertIsNone(guards.link_reason("website", u, brand_ok=True))
        self.assertIsNone(guards.link_reason("website", "https://notmemesonar.app"))

    def test_defaults_inherit_and_description_still_without_url(self):
        store.set_link_defaults(self.con, {"twitter": "https://x.com/ourmemes", "website": ""})
        d1 = store.draft(self.con, 1)
        self.assertEqual(store.link_urls(self.con, d1), {"twitter": "https://x.com/ourmemes"})
        store.update_draft(self.con, 2, {"twitter": "-", "telegram": "https://t.me/doorb"})
        self.assertEqual(store.link_urls(self.con, store.draft(self.con, 2)), {"telegram": "https://t.me/doorb"})
        store.update_draft(self.con, 3, {"twitter": "https://x.com/cart"})
        self.assertEqual(store.link_urls(self.con, store.draft(self.con, 3))["twitter"], "https://x.com/cart")
        with self.assertRaises(ValueError):
            store.set_link_defaults(self.con, {"telegram": "https://evil.com/x"})
        with self.assertRaises(ValueError):
            store.update_draft(self.con, 4, {"website": "https://memesonar.app"})          # bez kvačice
        store.update_draft(self.con, 4, {"website": "https://memesonar.app", "brend_ok": "1"})
        self.assertEqual(store.links_reasons(self.con, store.draft(self.con, 4)), [])
        with self.assertRaises(ValueError):
            store.set_link_defaults(self.con, {"website": "https://memesonar.app"})
        store.set_link_defaults(self.con, {"website": "https://memesonar.app"}, brend_ok=True)
        self.assertEqual(store.links_reasons(self.con, store.draft(self.con, 1)), [])
        # opis i dalje bez poveznica, i kad nacrt ima polja poveznica
        d = dict(store.draft(self.con, 3), opis="Visit https://x.com/cart")
        self.assertFalse(guards.check(d, search=no_search, now=NOW)["ok"])

    def test_links_in_metadata_not_in_create(self):
        self.tool_wallet()
        store.update_draft(self.con, 1, {"twitter": "https://x.com/gobble", "telegram": "https://t.me/gobble",
                                         "website": "https://gobble.example.org"})
        post, rpc = FakePost(), FakeRpc()
        with mock.patch.dict(os.environ, {"PINATA_JWT": "j"}):
            res = launch.launch_one(self.con, store.draft(self.con, 1), NOW, rpc=rpc, post=post, search=no_search,
                                    log=self.log, wait=lambda s: True)
        self.assertEqual(res["ishod"], "lansiran", res)
        body = [b for u, b, h in post.calls if u == launch.PINATA_UPLOAD][-1]
        meta = json.loads(body.split(b'filename="metadata.json"', 1)[1].split(b"\r\n\r\n", 1)[1]
                          .rsplit(b"\r\n--", 1)[0])
        self.assertEqual((meta["twitter"], meta["telegram"], meta["website"]),
                         ("https://x.com/gobble", "https://t.me/gobble", "https://gobble.example.org"))
        self.assertEqual(set(post.creates()[0]["tokenMetadata"]), {"name", "symbol", "uri"})
        self.assertEqual(store.attempts(self.con)[0]["ima_poveznice"], 1)
        # pump.fun/api/ipfs: ista polja u obrascu; bez poveznica ih nema
        p2 = FakePost()
        launch.upload_metadata("G", "G", "d", b"png", "pumpfun", post=p2, env={}, links={"twitter": "https://x.com/g"})
        self.assertIn(b'name="twitter"\r\n\r\nhttps://x.com/g', p2.calls[0][1])
        p3 = FakePost()
        launch.upload_metadata("G", "G", "d", b"png", "pumpfun", post=p3, env={}, links={})
        self.assertNotIn(b"twitter", p3.calls[0][1])

    def test_bad_link_at_launch_refused(self):
        self.tool_wallet()
        self.con.execute("UPDATE nacrti SET website='https://memesonar.app', brend_ok=0 WHERE id=1")   # zaobiđen obrazac
        self.con.commit()
        rpc, post = FakeRpc(), FakePost()
        res = launch.launch_one(self.con, store.draft(self.con, 1), NOW, rpc=rpc, post=post, search=no_search,
                                log=self.log, wait=lambda s: True)
        self.assertEqual(res["ishod"], "odbijen")
        self.assertEqual(post.calls, [])

    def test_page_notes(self):
        from ui import pumptokeni
        with mock.patch.object(pumptokeni, "balance", lambda a, max_age=60: None):
            _t, html = pumptokeni.page({}, "Jure", auto=False)
        for x in ("Poveznice moraju voditi na tvoje stranice ili profile.",
                  "Ista poveznica na više tokena može pasti na filtre duplikata.",
                  "želim javno povezati MemeSonar s ovim tokenom", "Lansiraj u (CET)", "Vlastita kupnja (SOL",
                  "Zadane poveznice"):
            self.assertIn(x, html)
        self.assertNotIn("Mayhem", html)


class Schedule(Base):
    def setUp(self):
        super().setUp()
        self.tool_wallet()

    def test_default_and_parse(self):
        self.assertEqual(store.parse_termin("2026-11-26T19:00"), T19)
        self.assertEqual(store.parse_termin("2026-11-26 19:00"), T19)
        self.assertEqual(store.default_termin(T19 - 7 * 3600), T19)               # 12:00 → danas 19:00
        self.assertEqual(store.default_termin(T19 + 3600), T19 + 86400)           # 20:00 → sutra 19:00
        with self.assertRaises(ValueError):
            store.parse_termin("sutra")
        self.assertEqual(store.cet(T19), "26.11. 19:00")

    def _go(self, ids, now):
        self.green(ids, now=now)
        return launch.approve_pilot(self.con, ids, "Jure", True, now)

    def test_waits_for_termin_and_gap_shift(self):
        now = T19 - 3600
        self.con.execute("UPDATE nacrti SET termin_ts=? WHERE id=1", (T19,))
        self.con.execute("UPDATE nacrti SET termin_ts=? WHERE id=2", (T19 + 180,))   # 3 min kasnije
        self.con.commit()
        n, why = self._go([2, 1], now)
        self.assertEqual(n, 2)
        self.assertTrue(any("pomaknut 26.11. 19:03 → 26.11. 19:10" in x for x in why), why)
        self.assertEqual([x["termin"] for x in store.get(self.con, "pilot")["raspored"]], [T19, T19 + 600])
        rpc = FakeRpc()
        kw = dict(rpc=rpc, post=FakePost(), search=no_search, log=self.log)
        with mock.patch.object(launch, "wait_confirmed", lambda r, s: True):
            self.assertIn("čeka termin: GOBBLE u 26.11. 19:00", launch.tick(self.con, T19 - 60, **kw))
            self.assertNotIn("sendTransaction", rpc.methods())
            self.assertEqual(launch.tick(self.con, T19 + 5, **kw), "GOBBLE: lansiran")
            self.assertIsNotNone(launch.tick(self.con, T19 + 300, **kw))
            self.assertEqual(rpc.methods().count("sendTransaction"), 1)
            self.assertEqual(launch.tick(self.con, T19 + 610, **kw), "DOORB: lansiran")

    def test_missed_termin_not_caught_up(self):
        now = T19 + 1000                                  # prošlo 16 min prije odobrenja
        self.con.execute("UPDATE nacrti SET termin_ts=? WHERE id IN (1,2)", (T19,))
        self.con.execute("UPDATE nacrti SET termin_ts=? WHERE id=2", (T19 + 1800,))
        self.con.commit()
        n, why = self._go([1, 2], now)
        self.assertEqual(n, 1)
        self.assertEqual(store.draft(self.con, 1)["stanje"], "propusten")
        self.assertTrue(any("propušten" in x for x in why))
        # obrada: termin 19:30 prođe za više od 15 min (npr. zastoj servisa) → propušten, bez slanja
        rpc = FakeRpc()
        self.assertIsNone(launch.tick(self.con, T19 + 1800 + 901, rpc=rpc, post=FakePost(), search=no_search,
                                      log=self.log))
        self.assertEqual(store.draft(self.con, 2)["stanje"], "propusten")
        self.assertNotIn("sendTransaction", rpc.methods())
        self.assertIn("ne nadoknađuje", "\n".join(self.logs))
        # unutar 15 min: lansira se
        self.con.execute("UPDATE nacrti SET termin_ts=? WHERE id=3", (T19 + 7200,))
        self.con.commit()
        self._go([3], T19 + 7200 + 300)
        with mock.patch.object(launch, "wait_confirmed", lambda r, s: True):
            self.assertEqual(launch.tick(self.con, T19 + 7200 + 400, rpc=rpc, post=FakePost(), search=no_search,
                                         log=self.log), "CARTGOB: lansiran")

    def test_edit_after_approval_leaves_queue_and_needs_new_preflight(self):
        now = T19 - 3600
        self.con.execute("UPDATE nacrti SET termin_ts=?", (T19,))
        self.con.commit()
        self._go([1], now)
        store.update_draft(self.con, 1, {"kupnja_sol": "0,04"}, now)
        self.assertEqual(store.draft(self.con, 1)["stanje"], "nacrt")
        store.save_check(self.con, 1, guards.check(store.draft(self.con, 1), search=no_search, now=now), now)
        rpc = FakeRpc()
        self.assertIsNone(launch.tick(self.con, T19 + 10, rpc=rpc, post=FakePost(), search=no_search, log=self.log))
        self.assertNotIn("sendTransaction", rpc.methods())
        n, why = launch.approve_pilot(self.con, [1], "Jure", True, now + 60)        # provjera rađena bez kupnje
        self.assertEqual(n, 0)
        self.assertIn("ponovi provjeru", why[0])

    def test_stale_queue_without_schedule_is_not_launched(self):
        store.set_state(self.con, 1, "u_redu", NOW)
        store.put(self.con, "pilot", {"odobren_ts": NOW - 86400, "ids": [1], "poslano": 0})   # stari pilot bez rasporeda
        rpc = FakeRpc()
        self.assertIsNone(launch.tick(self.con, NOW, rpc=rpc, post=FakePost(), search=no_search, log=self.log))
        self.assertEqual(store.draft(self.con, 1)["stanje"], "propusten")
        self.assertNotIn("sendTransaction", rpc.methods())

    def test_approval_confirm_lists_schedule(self):
        from ui import pumptokeni
        with mock.patch.object(pumptokeni, "balance", lambda a, max_age=60: 0.2):
            _t, html = pumptokeni.page({}, "Jure", auto=False)
        self.assertIn("ODOBRI RASPORED", html)
        pt = json.loads(html.split("var PT=", 1)[1].split(";</script>", 1)[0])
        self.assertEqual(set(pt["d"]["1"]), {"s", "t", "tc", "k", "l"})
        self.assertIn("poveznice", html)


class SeedSchedule(unittest.TestCase):
    """Sjeme za večeras na bazi kakva je na produkciji (25.11. sjeme + satirični opisi od jutra)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.p = os.path.join(self.tmp.name, "pump_tokeni.db")
        con = sqlite3.connect(self.p)   # stara shema, bez novih kolona
        con.executescript(store.SCHEMA)
        for tema, datum, ime, sym, *_x in store.SEED:
            con.execute("INSERT INTO nacrti (tema, datum_teme, ime, simbol, opis, slika, skupina, stanje, napravljen_ts, "
                        "promijenjen_ts) VALUES (?,?,?,?,?,?,?,'nacrt',?,?)",
                        (tema, datum, ime, sym, store.SEED_2611_SAT[sym], b"png", store.SKUPINA_0, NOW, NOW))
        con.execute("INSERT INTO kv VALUES ('seed_2511', '1'), ('seed_2611', '1')")
        con.commit()
        con.close()

    def tearDown(self):
        self.tmp.cleanup()

    def test_migration_tonight_untouched_only_and_never_approves(self):
        con = store.connect(self.p)
        con.execute("UPDATE nacrti SET opis='Mine.' WHERE simbol='SRALLY'")        # vlasnik dirao
        con.execute("UPDATE nacrti SET stanje='lansiran' WHERE simbol='Y2027'")     # lansiran
        con.commit()
        store.seed(con, NOW, slike_dir=self.tmp.name)
        ds = {d["simbol"]: d for d in store.drafts(con)}
        exp = {"GOBBLE": (T19, 0.04, "tema-kupnja-0,04"), "DOORB": (T19 + 1500, 0.04, "tema-kupnja-0,04"),
               "CARTGOB": (T19 + 3000, 0.0, "tema-bez-kupnje")}
        for sym, (t, k, g) in exp.items():
            self.assertEqual((ds[sym]["termin_ts"], ds[sym]["kupnja_sol"], ds[sym]["skupina"]), (t, k, g), sym)
            self.assertEqual(ds[sym]["opis"], next(x[4] for x in store.SEED if x[3] == sym))
            self.assertEqual(ds[sym]["stanje"], "nacrt")
        self.assertEqual(ds["GOBBLE"]["opis"], "A Thanksgiving turkey. No roadmap, no promises, just vibes.")
        self.assertEqual((ds["SRALLY"]["opis"], ds["SRALLY"]["termin_ts"]), ("Mine.", None))
        self.assertEqual((ds["Y2027"]["opis"], ds["Y2027"]["termin_ts"]), (store.SEED_2611_SAT["Y2027"], None))
        self.assertIsNone(store.get(con, "pilot"))
        self.assertEqual(launch.queue(con), [])
        before = [dict(d) for d in store.drafts(con)]
        store.seed(con, NOW + 50, slike_dir=self.tmp.name)                          # idempotentno
        self.assertEqual([dict(d) for d in store.drafts(con)], before)
        con.close()
        # svježa baza: sjeme odmah s rasporedom; termini 19:00, 19:25, 19:50, 20:15, 20:40
        con = store.connect(os.path.join(self.tmp.name, "new.db"))
        store.seed(con, NOW)
        self.assertEqual([(d["termin_ts"] - T19) // 60 for d in store.drafts(con)], [0, 25, 50, 75, 100])
        self.assertEqual([d["kupnja_sol"] for d in store.drafts(con)], [0.04, 0.04, 0, 0, 0])
        con.close()

    def test_old_queue_without_termin_goes_back_to_drafts_with_tonights_plan(self):
        """26.11.: „Odobri pilot" na staroj verziji ostavio je nacrte 'u_redu' bez termina."""
        con = store.connect(self.p)
        con.execute("UPDATE nacrti SET stanje='u_redu', termin_ts=NULL, kupnja_sol=NULL, skupina=?", (store.SKUPINA_0,))
        con.execute("UPDATE nacrti SET stanje='lansiran' WHERE simbol='Y2027'")
        con.execute("DELETE FROM kv WHERE k='seed_2611c'")
        con.commit()
        self.assertEqual(store.seed(con, NOW, slike_dir=self.tmp.name), 0)
        ds = {d["simbol"]: d for d in store.drafts(con)}
        self.assertEqual((ds["GOBBLE"]["stanje"], ds["GOBBLE"]["termin_ts"], ds["GOBBLE"]["kupnja_sol"]), ("nacrt", T19, 0.04))
        self.assertEqual((ds["CARTGOB"]["stanje"], ds["CARTGOB"]["kupnja_sol"]), ("nacrt", 0.0))
        self.assertEqual(ds["Y2027"]["stanje"], "lansiran")
        self.assertEqual(launch.queue(con), [])                    # ništa nije odobreno
        before = [dict(d) for d in store.drafts(con)]
        store.seed(con, NOW + 60, slike_dir=self.tmp.name)         # jednokratno
        self.assertEqual([dict(d) for d in store.drafts(con)], before)
        con.close()

    def test_owner_chat_order_approves_once_only_after_green_dry_run(self):
        """26.11.: "smatraj da je odobren": jednom, samo za sjeme, samo uz zelenu suhu probu, samo do roka."""
        from unittest import mock
        from pumptokeni import posao
        con = store.connect(self.p)
        store.seed(con, NOW, slike_dir=self.tmp.name)
        now = T19 - 3600
        self.assertIsNone(posao.owner_order(con, now, log=lambda *_: None))            # provjera još nije zelena
        self.assertFalse(store.get(con, store.NALOG_2611)["gotovo"])                   # nalog upisan jednom
        self.assertTrue(store.get(con, "nalog_2611_upisan"))
        store.put(con, store.NALOG_2611, {"ts": now, "do": T19 + 6300, "gotovo": False})
        ids = provjera.scheduled_ids(con, now)
        self.assertEqual(len(ids), 5)
        with mock.patch.object(launch, "approve_pilot", return_value=(5, [])) as ap:
            self.assertIsNone(posao.owner_order(con, now, log=lambda *_: None))        # provjera nije zelena
            store.put(con, "provjera", {"ts": now, "ids": ids[:3], "zeleno": True})
            self.assertIsNone(posao.owner_order(con, now, log=lambda *_: None))        # ne pokriva sve
            store.put(con, "provjera", {"ts": now - 4000, "ids": ids, "zeleno": True})
            self.assertIsNone(posao.owner_order(con, now, log=lambda *_: None))        # stara provjera
            self.assertEqual(ap.call_count, 0)
            store.put(con, "provjera", {"ts": now, "ids": ids, "zeleno": True})
            self.assertIn("po nalogu vlasnika", posao.owner_order(con, now, log=lambda *_: None))
            self.assertEqual(ap.call_args[0][1], ids)
            self.assertIsNone(posao.owner_order(con, now + 60, log=lambda *_: None))   # samo jednom
            self.assertEqual(ap.call_count, 1)
            store.put(con, store.NALOG_2611, {"ts": now, "do": now - 1, "gotovo": False})
            self.assertIsNone(posao.owner_order(con, now, log=lambda *_: None))        # istekao
            self.assertEqual(ap.call_count, 1)
        con.close()

    def test_job_after_migration_with_passed_termins_sends_nothing(self):
        c0 = store.connect(self.p)   # opće pravilo bez vlasnikova naloga od 26.11. (nalog ima svoj test)
        store.put(c0, "nalog_2611_upisan", 1)
        c0.close()
        env = {"DATA_DIR": self.tmp.name, "PUMP_TOKENI_DB": self.p}
        with mock.patch.dict(os.environ, env), mock.patch.object(executor, "STOP_FILE",
                                                                 os.path.join(self.tmp.name, "STOP")):
            old = settings.DB
            settings.DB = os.path.join(self.tmp.name, "trade.db")
            try:
                devwallet.create()
                con = store.connect(self.p)
                store.seed(con, NOW)
                con.close()
                rpc, post = FakeRpc(), FakePost()
                from trade import wallet
                with mock.patch.object(wallet, "rpc", rpc), mock.patch.object(launch, "http_post", post), \
                        mock.patch.object(guards, "_search", no_search), \
                        mock.patch.object(provjera, "_get", lambda u, h, timeout=15: 200):
                    for k in range(0, 4 * 3600, 60):                              # 19:00–23:00, svake minute
                        posao.tick(T19 - 600 + k, log=lambda x: None, proc="p1")
                self.assertNotIn("sendTransaction", rpc.methods())
                self.assertFalse(any(u == launch.PINATA_UPLOAD or u == launch.PUMP_IPFS for u, _b, _h in post.calls))
                con = store.connect(self.p)
                self.assertTrue(all(d["stanje"] in ("nacrt", "propusten") for d in store.drafts(con)))
                con.close()
            finally:
                settings.DB = old


class DryRunJob(Base):
    def setUp(self):
        super().setUp()
        self.tool_wallet()
        self.plain(T19)

    def _tick(self, now, proc, rpc, post, gets):
        with mock.patch.object(launch, "http_post", post), mock.patch.object(guards, "_search", no_search):
            return posao.tick(now, log=self.log, proc=proc,
                              dry_kw={"rpc": rpc, "post": post, "search": no_search,
                                      "get": lambda u, h: gets.append(u) or 200})

    def test_once_per_process_then_every_30_min_never_sends(self):
        c0 = store.connect()   # opće pravilo bez vlasnikova naloga od 26.11. (nalog ima svoj test)
        store.put(c0, "nalog_2611_upisan", 1)
        c0.close()
        rpc, post, gets = FakeRpc(), FakePost(), []
        from trade import wallet
        with mock.patch.dict(os.environ, {"PINATA_JWT": "j"}), mock.patch.object(wallet, "rpc", rpc):
            t = T19 - 7200
            self._tick(t, "A", rpc, post, gets)
            n1 = rpc.methods().count("simulateTransaction")
            self.assertEqual(n1, 5)                                              # svaki nacrt rasporeda
            self._tick(t + 60, "A", rpc, post, gets)
            self._tick(t + 1700, "A", rpc, post, gets)
            self.assertEqual(rpc.methods().count("simulateTransaction"), 5)      # isti proces, < 30 min
            self._tick(t + 1800, "A", rpc, post, gets)
            self.assertEqual(rpc.methods().count("simulateTransaction"), 10)     # 30 min
            self._tick(t + 1860, "B", rpc, post, gets)
            self.assertEqual(rpc.methods().count("simulateTransaction"), 15)     # novi proces (restart)
            self._tick(T19 + 7200, "C", rpc, post, gets)                          # nema zakazanih: ništa
            self.assertEqual(rpc.methods().count("simulateTransaction"), 15)
        self.assertNotIn("sendTransaction", rpc.methods())
        self.assertFalse(any(u in (launch.PINATA_UPLOAD, launch.PUMP_IPFS) for u, _b, _h in post.calls))
        self.assertEqual(set(gets), {provjera.PINATA_TEST})                      # Pinata samo autentifikacija
        lines = [x for x in self.logs if x.startswith("pump tokeni suha proba: ")]
        self.assertEqual(len(lines), 15)
        self.assertIn("pump tokeni suha proba: GOBBLE termin 26.11. 19:00 CET, kupnja 0 SOL, simulacija ok, promjena "
                      "salda −0.00901 SOL, rezerva ok", lines[0])
        self.assertTrue(any(x.startswith("pump tokeni provjera: ZELENO") for x in self.logs))
        self.assertIsNone(store.get(self.con, "pilot"))                           # suha proba ništa ne odobrava

    def test_tonight_schedule_numbers(self):
        """Večerašnji raspored (2 × 0,04 SOL kupnje): suha proba s lažnim RPC-om (lansiranje 0,009 SOL)."""
        self.con.execute("DELETE FROM nacrti")
        self.con.commit()
        for tema, datum, ime, sym, opis, termin, k, g in store.SEED:
            store.add_draft(self.con, {"tema": tema, "datum_teme": datum, "ime": ime, "simbol": sym, "opis": opis,
                                       "skupina": g, "kupnja_sol": str(k), "termin": termin}, b"png")
        post = FakePost()
        rpc = FakeRpc(sol=0.2, buy_from=post)
        provjera.run(self.con, None, now=T19 - 3600, rpc=rpc, post=post, search=no_search, log=self.log)
        pf = store.get(self.con, "provjera")
        self.assertTrue(pf["zeleno"], pf["koraci"])
        self.assertAlmostEqual(pf["zbroj"]["sol"], 5 * (0.009 + 0.00001) + 2 * 0.04 * 1.0125, places=9)   # 0,12605
        self.assertAlmostEqual(pf["zbroj"]["ostaje"], 0.2 - pf["zbroj"]["sol"], places=6)
        self.assertEqual([r["simbol"] for r in pf["nacrti"]], ["GOBBLE", "DOORB", "CARTGOB", "SRALLY", "Y2027"])
        # saldo 0,10: kupnja DOORB bi probila rezervu → bez kupnje; SRALLY ni bez kupnje ne ostavlja 0,03 → crveno
        post = FakePost()
        provjera.run(self.con, None, now=T19 - 3600, rpc=FakeRpc(sol=0.10, buy_from=post), post=post,
                     search=no_search, log=self.log)
        pf = store.get(self.con, "provjera")
        per = {r["simbol"]: r for r in pf["nacrti"]}
        self.assertEqual((per["GOBBLE"]["bez_kupnje"], per["DOORB"]["bez_kupnje"]), (False, True))
        self.assertEqual((per["CARTGOB"]["rezerva_ok"], per["SRALLY"]["rezerva_ok"]), (True, False))
        self.assertFalse(pf["zeleno"])
        self.assertTrue(any("DOORB" in x and "rezerva ok (bez kupnje)" in x for x in self.logs))
        self.assertTrue(any("SRALLY" in x and "rezerva ne" in x for x in self.logs))


class PostBlock(Base):
    def test_post_text_copy_download_and_no_autopost(self):
        mint = "MintPost111111111111111111111111111111111111"
        aid = store.new_attempt(self.con, store.draft(self.con, 1), launch.TOOL, "P", NOW, mint=mint)
        store.update_attempt(self.con, aid, stanje="lansiran", potpis="s", trosak_sol=0.01)
        store.set_state(self.con, 1, "lansiran", NOW)
        from ui import pumptokeni
        with mock.patch.object(pumptokeni, "balance", lambda a, max_age=60: 0.2), \
                mock.patch("urllib.request.urlopen", side_effect=AssertionError("stranica ne zove mrežu")):
            _t, html = pumptokeni.page({}, "Jure", auto=False)
        d = store.draft(self.con, 1)
        txt = f"Gobble ($GOBBLE)\n{d['opis']}\nCA: {mint}\nhttps://pump.fun/coin/{mint}"
        self.assertEqual(pumptokeni.post_text("Gobble", "GOBBLE", d["opis"], mint), txt)
        self.assertIn("Objava za kopiranje", html)
        from ui.html import esc
        self.assertIn(esc(txt), html)
        self.assertIn("📋 Kopiraj", html)
        self.assertIn("prompt('Kopiraj:'", html)                                  # zamjensko rješenje
        self.assertIn("href='/pump-tokeni/slika/1' download='gobble.png'>⬇ Preuzmi sliku", html)

    def test_module_calls_no_posting_service(self):
        import re
        srcs = [os.path.join(ROOT, "pumptokeni", f) for f in os.listdir(os.path.join(ROOT, "pumptokeni"))
                if f.endswith(".py")] + [os.path.join(ROOT, "ui", "pumptokeni.py")]
        for f in srcs:
            with open(f, encoding="utf-8") as fh:
                src = fh.read()
            for host in ("api.twitter.com", "api.x.com", "upload.twitter", "buffer.com", "bufferapp", "api.telegram.org",
                         "graph.facebook", "sendMessage", "create_post", "novosti.json"):
                self.assertNotIn(host, src, (f, host))
            self.assertIsNone(re.search(r"^\s*(from|import)\s+(ops|social|kol|makroinf|hype|share)\b", src, re.M), f)
        hosts = set()
        for f in srcs:
            with open(f, encoding="utf-8") as fh:
                hosts |= set(re.findall(r"https://([a-z0-9.-]+)/", fh.read()))
        self.assertLessEqual(hosts - {"pumpportal.fun", "pump.fun", "uploads.pinata.cloud", "ipfs.io", "api.pinata.cloud",
                                      "dexscreener.com", "solscan.io", "x.com", "t.me"}, set(), hosts)


def sig(n, t, err=None):
    return {"signature": f"S{n}", "blockTime": t, "err": err}


def tok(owner, mint, amt):
    return {"owner": owner, "mint": mint, "uiTokenAmount": {"amount": str(amt)}}


class BuyersRpc:
    def __init__(self, mint, t0, creator, fail=False):
        self.calls, self.fail = [], fail
        curve = outcomes.curve_pda(mint)
        self.sigs = [sig(0, t0), sig(1, t0 + 30), sig(2, t0 + 60), sig(3, t0 + 90, err={"x": 1}), sig(4, t0 + 200),
                     sig(5, t0 + 590), sig(6, t0 + 700)]
        bal = lambda pre, post: {"meta": {"err": None, "preTokenBalances": pre, "postTokenBalances": post}}   # noqa: E731
        self.txs = {
            "S0": bal([], [tok(curve, mint, 10**15), tok(creator, mint, 0)]),                   # create
            "S1": bal([tok(curve, mint, 1000)], [tok(curve, mint, 900), tok("A", mint, 100)]),
            "S2": bal([tok("A", mint, 100)], [tok("A", mint, 150)]),                            # A drugi put
            "S4": bal([tok("B", mint, 0), tok(creator, mint, 5)], [tok("B", mint, 7), tok(creator, mint, 9)]),
            "S5": bal([tok("C", mint, 9), tok(curve, mint, 1)], [tok("C", mint, 1), tok(curve, mint, 9)]),   # prodaja
            "S6": bal([], [tok("D", mint, 5)]),                                                 # nakon 10 min
        }

    def __call__(self, method, params):
        self.calls.append(method)
        if self.fail:
            raise TimeoutError()
        if method == "getSignaturesForAddress":
            return list(reversed(self.sigs))
        if method == "getTransaction":
            return self.txs.get(params[0])
        raise AssertionError(method)


class BuyersTenMin(Base):
    MINT = "So11111111111111111111111111111111111111112"   # bilo koja ispravna adresa za PDA

    def _launched(self, ts=NOW):
        aid = store.new_attempt(self.con, store.draft(self.con, 1), launch.TOOL, str(self.creator), ts, mint=self.MINT)
        store.update_attempt(self.con, aid, stanje="lansiran", potpis="s", trosak_sol=0.01, kupnja_sol=0.04,
                             ima_poveznice=1)
        return aid

    def setUp(self):
        super().setUp()
        self.creator = str(Keypair().pubkey())

    def test_distinct_buyers_without_creator_and_cap(self):
        rpc = BuyersRpc(self.MINT, NOW + 3, self.creator)
        n, src, calls = outcomes.count_buyers(rpc, self.MINT, NOW, self.creator)
        self.assertEqual((n, src), (2, "rpc"))                                     # A i B; ne kreator, krivulja, D
        self.assertEqual(calls, 1 + 5)                                              # 1 + uspješne u 600 s
        rpc = BuyersRpc(self.MINT, NOW + 3, self.creator)
        n, src, calls = outcomes.count_buyers(rpc, self.MINT, NOW, self.creator, max_calls=3)
        self.assertEqual((src, calls), ("rpc_strop", 3))
        self.assertEqual(outcomes.buyers_text({"kupci_10m": n, "kupci_10m_izvor": src}), f"≥ {n}")

    def test_measure_once_after_11_min_and_fallback(self):
        self._launched()
        rpc = BuyersRpc(self.MINT, NOW + 3, self.creator)
        self.assertEqual(outcomes.measure_buyers(self.con, NOW + 600, rpc=rpc, log=self.log), 0)   # prerano
        self.assertEqual(rpc.calls, [])
        self.assertEqual(outcomes.measure_buyers(self.con, NOW + 700, rpc=rpc, log=self.log), 1)
        self.assertEqual(outcomes.measure_buyers(self.con, NOW + 800, rpc=rpc, log=self.log), 0)   # jednom
        a = store.attempts(self.con)[0]
        self.assertEqual((a["kupci_10m"], a["kupci_10m_izvor"], a["kupci_10m_poziva"]), (2, "rpc", 6))
        # RPC bez podataka: kupnje iz DexScreener snimka, označene kao kupnje
        self.con.execute("UPDATE pokusaji SET kupci_10m=NULL, kupci_10m_izvor=NULL")
        self.con.execute("INSERT INTO snimci (mint, ts, nadjen, kupnje_h1) VALUES (?,?,1,?)", (self.MINT, NOW + 650, 11))
        self.con.commit()
        outcomes.measure_buyers(self.con, NOW + 900, rpc=BuyersRpc(self.MINT, NOW, self.creator, fail=True),
                                log=self.log)
        a = store.attempts(self.con)[0]
        self.assertEqual((a["kupci_10m"], a["kupci_10m_izvor"]), (11, "dex_kupnji"))
        self.assertEqual(outcomes.buyers_text(a), "11 kupnji")

    def test_book_csv_new_columns_and_fee_without_own_buy(self):
        self._launched(T19)
        store.update_attempt(self.con, 1, kupci_10m=7, kupci_10m_izvor="rpc")
        pairs = [dex_pair(self.MINT)]
        outcomes.check_pass(self.con, T19 + 25 * 3600, fetch=lambda m: pairs, log=self.log)
        rows, groups = outcomes.book(self.con)
        r = rows[0]
        self.assertAlmostEqual(r["naknada_sol"], 0.6 - 0.003 * 0.04, places=9)     # bez naknade od vlastite kupnje
        self.assertAlmostEqual(r["neto_sol"], 0.6 - 0.00012 - 0.01, places=9)       # kupnja nije gubitak
        self.assertEqual(r["u_tokenima_sol"], 0.04)
        csv = outcomes.csv_text(self.con)
        head = csv.splitlines()[0].split(",")
        for col in ("skupina", "vlastita_kupnja_sol", "ima_poveznice", "sat_lansiranja_cet", "kupaca_10min",
                    "u_tokenima_sol", "naknada_bez_vlastite_kupnje_sol"):
            self.assertIn(col, head)
        import csv as csvmod
        row = dict(zip(head, next(csvmod.reader(csv.splitlines()[1:]))))
        self.assertEqual((row["vlastita_kupnja_sol"], row["ima_poveznice"], row["sat_lansiranja_cet"], row["kupaca_10min"]),
                         ("0.040000", "da", "2026-11-26 19:00", "7"))
        self.assertEqual(row["skupina"], "tema-kupnja-0,04")
        from ui import pumptokeni
        with mock.patch.object(pumptokeni, "balance", lambda a, max_age=60: 0.2):
            _t, html = pumptokeni.page({}, "Jure", auto=False)
        for x in ("Kupaca u 10 min", "Ima poveznice", "Sat (CET)", "Naknada bez vlastite kupnje SOL", "U tokenima SOL"):
            self.assertIn(x, html)

    def test_job_measures_through_rpc(self):
        self._launched()
        rpc = BuyersRpc(self.MINT, NOW + 3, self.creator)
        from trade import wallet
        with mock.patch.object(wallet, "rpc", rpc), \
                mock.patch.object(outcomes, "refresh", lambda con, now, log=print: (0, 0)), \
                mock.patch.object(outcomes, "read_vaults", lambda con, now, log=print: {}):
            posao.tick(NOW + 700, log=self.log, proc="x")
        self.assertEqual(store.attempts(self.con)[0]["kupci_10m"], 2)
        self.assertIn("kupaca u prvih 10 min 2 (6 RPC poziva)", "\n".join(self.logs))


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
            self.assertEqual(self.call("/pump-tokeni/ploca", who)[0], 403)
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
        code, frag, _ = self.call("/pump-tokeni/ploca", jure)
        self.assertEqual(code, 200)
        self.assertIn("id=ptdash", frag)
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
