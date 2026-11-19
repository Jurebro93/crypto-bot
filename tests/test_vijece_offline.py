"""Vijeće (the council), 18.11. (vlasnik: "Kad Grok pošalje prijedlog, Claude i OpenAI moraju biti kritični prema
njemu, doraditi ga i prihvatiti ako se slažu ... neka alat sam sebe popravlja i uči i odlučuje"): vijece/.

Offline: the OpenAI HTTP call is replaced (critic.openai_api._urlopen), the Claude call is replaced
(vijece.kriticari._claude_call; the SDK pattern itself is checked against a fake anthropic module), the brief's
sources are stand-ins, trade.db is a temporary file. Nothing reaches the network.

    python3 -m unittest tests.test_vijece_offline
"""
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import types
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from critic import notes as cnotes  # noqa: E402
from critic import openai_api  # noqa: E402
from stanja import provjera, registar  # noqa: E402
from trade import settings  # noqa: E402
from ui import assistnotes, mcpapi  # noqa: E402
from usage import daily  # noqa: E402
from vijece import kriticari, odluka, posao, sjeme, smjer, store  # noqa: E402
from vijece import mcp as vmcp  # noqa: E402
import vijece  # noqa: E402

GROK_KID = assistnotes.key_id("grok-mcp-kljuc")
OWNER_W = "4Nd1mBQtrMJVYVfKf2PJy9NZUZdTAsp7D4xWLs4gDB4T"
SLAZEM = {"verdict": "slazem", "critique": "Dokazi drže: n=308, −7,4 % nakon troška. Povratno je.", "refined_change": None,
          "kako_povecava_zaradu": "štedi oko 2 $ dnevno"}
PROTIV = {"verdict": "protiv", "critique": "Nema dokaza, uzorak je premalen (n=7).", "refined_change": None,
          "kako_povecava_zaradu": "ne povećava"}
SMJER_ODG = {"prijedlozi": [
    {"naslov": "Sve resurse na učenje dnevnog raspona", "obrazlozenje": "Jedino pravilo s mjerenjem na neviđenim danima.",
     "koraci": ["ugasiti KOL praćenje", "više svijeća", "provjera za 14 dana"], "sto_ugasiti": "makro klasifikaciju",
     "koji_podaci": "15-min svijeće; brzina nije važna", "kako_povecava_zaradu": "manji trošak, više naučenog po dolaru",
     "mjerenje": "EV odabranih tradeova na neviđenim danima iznad 0", "proposed_change": None},
    {"naslov": "Stroži prag rasta od prvog poziva", "obrazlozenje": "Kasni ulazi gube.", "koraci": ["prag 10 %"],
     "sto_ugasiti": "ništa", "koji_podaci": "ništa", "kako_povecava_zaradu": "manje kasnih ulaza",
     "mjerenje": "EV kopija", "proposed_change": "{\"key\": \"runup_max\", \"to\": 0.1}"}]}


def responses_answer(obj, tin=3000, tout=600, model="gpt-6-astra"):
    return {"id": "resp_1", "model": model, "status": "completed",
            "output": [{"type": "message", "content": [{"type": "output_text", "text": json.dumps(obj)}]}],
            "usage": {"input_tokens": tin, "output_tokens": tout}}


class FakeOpenAI:
    """Stands in for urllib: the review per note id (by default: agrees), the direction answer; records the bodies."""
    def __init__(self):
        self.calls, self.reviews, self.default, self.smjer = [], {}, SLAZEM, SMJER_ODG

    def __call__(self, req, timeout):
        body = json.loads(req.data)
        self.calls.append(body)
        if body["text"]["format"]["name"] == "vijece_smjer":
            data = self.smjer
        else:
            nid = int(re.search(r"PRIJEDLOG #(\d+)", body["input"]).group(1))
            data = self.reviews.get(nid, self.default)
        raw = json.dumps(responses_answer(data, model=body["model"])).encode()

        class R:
            def __enter__(self):
                return self

            def __exit__(self, *x):
                return False

            def read(self):
                return raw
        return R()

    def review_calls(self):
        return [b for b in self.calls if b["text"]["format"]["name"] == "vijece_ocjena"]


class FakeClaude:
    """Stands in for vijece.kriticari._claude_call."""
    def __init__(self):
        self.calls, self.reviews, self.default, self.smjer = [], {}, SLAZEM, {"prijedlozi": SMJER_ODG["prijedlozi"][:1]}

    def __call__(self, system, text, schema, max_tokens):
        self.calls.append({"system": system, "text": text, "schema": schema, "max_tokens": max_tokens})
        if "prijedlozi" in schema["properties"]:
            data = self.smjer
        else:
            nid = int(re.search(r"PRIJEDLOG #(\d+)", text).group(1))
            data = self.reviews.get(nid, self.default)
        return {"data": data, "model": "claude-opus-5-5", "usd": 0.02}


class Base(unittest.TestCase):
    KEYS = {"OPENAI_API_KEY": "sk-test-0123456789abcdefSECRET", "ANTHROPIC_API_KEY": "sk-ant-test-0123456789abcdef"}

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = os.path.join(self.tmp.name, "trade.db")
        self._db = settings.DB
        settings.DB = self.db
        env = {k: v for k, v in os.environ.items() if not k.startswith(("VIJECE", "OPENAI_", "ANTHROPIC_"))}
        env.update(self.KEYS)
        self.openai, self.claude = FakeOpenAI(), FakeClaude()
        self.lines = []
        self.log = lambda *a, **k: self.lines.append(" ".join(str(x) for x in a))
        for p in (mock.patch.dict(os.environ, env, clear=True),
                  mock.patch.object(openai_api, "_urlopen", self.openai),
                  mock.patch.object(kriticari, "_claude_call", self.claude),
                  mock.patch.object(smjer, "IZVORI", (("Učenje", lambda now, con: "presuda: nema dokazanog plusa; n=120"),
                                                      ("Moć poziva", lambda now, con: None))),
                  mock.patch.object(smjer, "presuda_ucenja", lambda: self.verdict),
                  mock.patch("builtins.print")):
            p.start()
            self.addCleanup(p.stop)
        self.verdict = None
        self.con = store.connect(self.db)
        self.now = int(time.time())
        self.seeded(True)

    def tearDown(self):
        self.con.close()
        settings.DB = self._db
        self.tmp.cleanup()

    def seeded(self, done):
        """Most tests start with the one-time work marked done (the seeds, the first direction session)."""
        if done:
            settings.put(self.con, sjeme.ONCE_KEY, 1, "test")
            settings.put(self.con, smjer.ONCE_KEY, self.now, "test")
            settings.put(self.con, smjer.ONCE_KEY_B, self.now, "test")
            settings.put(self.con, smjer.ONCE_KEY_C, self.now, "test")
        store.start_ts(self.con, self.now - 5)

    def note(self, kid=GROK_KID, title="Prijedlog", pc=None, evidence=None):
        d = assistnotes.submit_suggestion(self.con, kid, title, "Obrazloženje s brojevima: n=308.", "Što napraviti.",
                                          evidence, pc)
        return d["id"]

    def tick(self, now=None, **kw):
        return posao.tick(now or self.now, self.log, self.con, **kw)

    def status(self, nid):
        return self.con.execute("SELECT status FROM assistant_notes WHERE id=?", (nid,)).fetchone()[0]

    def decision(self, nid):
        return store.odluka(self.con, nid)

    def logged(self, needle):
        return [ln for ln in self.lines if needle in ln]


class Roles(Base):
    def test_proposer_is_read_from_the_key(self):
        self.assertEqual(store.predlagac(cnotes.KID), "openai")
        self.assertEqual(store.predlagac(assistnotes.key_id("claude-vijece")), "claude")
        self.assertEqual(store.predlagac(GROK_KID), "grok")
        self.assertEqual(store.predlagac("local"), "grok")
        self.assertEqual(store.predlagac(None), "grok")
        nid = self.note(cnotes.KID)
        self.assertEqual(store.note(self.con, nid)["predlagac"], "openai")

    def test_the_reviewers_are_the_other_two(self):
        self.assertEqual(set(store.ocjenjivaci("grok")), {"openai", "claude"})
        self.assertEqual(set(store.ocjenjivaci("openai")), {"claude", "grok"})
        self.assertEqual(set(store.ocjenjivaci("claude")), {"openai", "grok"})

    def test_only_the_missing_api_reviewer_is_asked(self):
        a, b, c = self.note(GROK_KID), self.note(cnotes.KID), self.note(store.CLAUDE_KID)
        self.tick()
        asked_o = {int(re.search(r"PRIJEDLOG #(\d+)", x["input"]).group(1)) for x in self.openai.review_calls()}
        asked_c = {int(re.search(r"PRIJEDLOG #(\d+)", x["text"]).group(1)) for x in self.claude.calls}
        self.assertEqual(asked_o, {a, c})     # never its own
        self.assertEqual(asked_c, {a, b})
        self.tick()                           # a second pass asks nobody again
        self.assertEqual(len(self.openai.review_calls()), 2)
        self.assertEqual(len(self.claude.calls), 2)


class Decisions(Base):
    def test_both_agree_applies_an_allowed_setting_and_logs_it(self):
        nid = self.note(pc={"key": "dca_token_cap", "to": 0.2})
        out = self.tick()
        self.assertEqual((out["ocjena"], out["odluka"]), (2, 1))
        self.assertEqual(self.status(nid), "primijenjeno")
        self.assertEqual(settings.raw(self.con)["dca_token_cap"], 0.2)
        self.assertEqual(settings.flag("dca_cap", con=self.con), "shadow")       # a flag moves at most to shadow
        d = self.decision(nid)
        self.assertEqual(d["odluka"], "prihvaceno_primijenjeno")
        self.assertIn("dca_token_cap", d["primijenjeno"])
        self.assertEqual(assistnotes.applied(self.con)[0]["note_id"], nid)
        self.assertTrue(self.con.execute("SELECT owner_note FROM assistant_notes WHERE id=?", (nid,)).fetchone()[0]
                        .startswith("vijeće:"))
        line = self.logged(f"vijeće: odluka #{nid} ")[0]
        self.assertIn("(Grok): PRIHVAĆENO I PRIMIJENJENO", line)
        self.assertIn("OpenAI: slazem:", line)
        self.assertIn("Claude: slazem:", line)
        self.assertEqual(len(self.logged(f"vijeće: ocjena #{nid} ")), 2)
        self.assertIn("Neto zarada:", store.ocjene(self.con, nid)["openai"]["critique"])

    def test_one_refinement_is_the_change_in_force_and_the_original_is_kept(self):
        nid = self.note(pc={"key": "dca_token_cap", "to": 0.5}, evidence={"n": 12})
        self.openai.reviews[nid] = {**SLAZEM, "verdict": "doradi", "critique": "0,5 SOL je previše; 0,25.",
                                    "refined_change": json.dumps({"key": "dca_token_cap", "to": 0.25})}
        self.tick()
        self.assertEqual(settings.raw(self.con)["dca_token_cap"], 0.25)
        n = store.note(self.con, nid)
        self.assertEqual(n["status"], "primijenjeno")
        self.assertEqual(n["proposed_change"], {"key": "dca_token_cap", "to": 0.25})
        self.assertEqual(n["evidence"]["izvorni_prijedlog"], {"key": "dca_token_cap", "to": 0.5})
        self.assertEqual(n["evidence"]["n"], 12)
        self.assertEqual(self.decision(nid)["odluka"], "prihvaceno_primijenjeno")
        self.assertIn("0,5 SOL je previše; 0,25.", self.claude.calls[0]["text"])        # Claude sees OpenAI's review

    def test_two_different_refinements_go_to_the_owner(self):
        nid = self.note(pc={"key": "dca_token_cap", "to": 0.5})
        self.openai.reviews[nid] = {**SLAZEM, "verdict": "doradi", "refined_change": json.dumps({"key": "dca_token_cap", "to": 0.25})}
        self.claude.reviews[nid] = {**SLAZEM, "verdict": "doradi", "refined_change": json.dumps({"key": "dca_token_cap", "to": 0.3})}
        self.tick()
        d = self.decision(nid)
        self.assertEqual(d["odluka"], "vlasniku")
        self.assertIn("0.25", d["razlog"])
        self.assertIn("0.3", d["razlog"])
        self.assertEqual(self.status(nid), "novo")
        self.assertNotIn("dca_token_cap", settings.raw(self.con))

    def test_the_same_refinement_twice_is_applied(self):
        nid = self.note(pc={"key": "dca_token_cap", "to": 0.5})
        rc = json.dumps({"to": 0.25, "key": "dca_token_cap"})
        self.openai.reviews[nid] = {**SLAZEM, "verdict": "doradi", "refined_change": rc}
        self.claude.reviews[nid] = {**SLAZEM, "verdict": "doradi", "refined_change": json.dumps({"key": "dca_token_cap", "to": 0.25})}
        self.tick()
        self.assertEqual(self.decision(nid)["odluka"], "prihvaceno_primijenjeno")
        self.assertEqual(settings.raw(self.con)["dca_token_cap"], 0.25)

    def test_both_against_rejects(self):
        nid = self.note(pc={"key": "dca_token_cap", "to": 0.2})
        self.openai.default = self.claude.default = PROTIV
        self.tick()
        self.assertEqual(self.status(nid), "odbijeno")
        self.assertEqual(self.decision(nid)["odluka"], "odbijeno")
        self.assertNotIn("dca_token_cap", settings.raw(self.con))
        self.assertIn("ODBIJENO", self.logged(f"vijeće: odluka #{nid} ")[0])

    def test_a_split_goes_to_the_owner_and_the_note_stays_new(self):
        nid = self.note(pc={"key": "dca_token_cap", "to": 0.2})
        self.claude.default = PROTIV
        self.tick()
        d = self.decision(nid)
        self.assertEqual(d["odluka"], "vlasniku")
        self.assertIn("OpenAI: slazem", d["razlog"])
        self.assertIn("Claude: protiv", d["razlog"])
        self.assertEqual(self.status(nid), "novo")
        self.assertNotIn("dca_token_cap", settings.raw(self.con))
        self.tick()                                    # decided once: not reviewed or decided again
        self.assertEqual(len(self.logged(f"vijeće: odluka #{nid} ")), 1)

    def test_real_money_is_never_applied(self):
        before = dict(settings.raw(self.con))
        nid = self.note(pc={"key": "size_sol", "from": None, "to": 0.2})
        self.tick()
        d = self.decision(nid)
        self.assertEqual(d["odluka"], "vlasniku")
        self.assertTrue(d["razlog"].startswith("vijeće preporučuje prihvatiti, ali dira pravi novac"))
        self.assertEqual(self.status(nid), "novo")
        self.assertNotIn("size_sol", settings.raw(self.con))
        self.assertEqual({k: v for k, v in settings.raw(self.con).items() if k in before}, before)
        # a refinement cannot turn a harmless proposal into a real-money change, nor launder one
        n2 = self.note(pc={"key": "dca_token_cap", "to": 0.2})
        self.openai.reviews[n2] = {**SLAZEM, "verdict": "doradi", "refined_change": json.dumps({"key": "max_open", "to": 9})}
        n3 = self.note(pc={"key": "sl_default", "to": 20})
        self.openai.reviews[n3] = {**SLAZEM, "verdict": "doradi", "refined_change": json.dumps({"key": "dca_token_cap", "to": 0.2})}
        self.tick()
        for n in (n2, n3):
            self.assertEqual(self.decision(n)["odluka"], "vlasniku", n)
            self.assertEqual(self.status(n), "novo")
        self.assertNotIn("max_open", settings.raw(self.con))
        self.assertNotIn("dca_token_cap", settings.raw(self.con))

    def test_classes(self):
        for pc in ({"key": "size_sol", "to": 1}, {"key": "max_open", "to": 9}, {"key": "tp_default", "to": 30},
                   {"key": "sl_default", "to": 20}, {"key": "copy.max_per_day", "to": 50},
                   {"flag": "pravi_novac_veliki", "to": "paper"}, {"key": "grok_autotrade", "to": True},
                   {"key": "kill_switch", "to": False}, {"flag": "konsenzus", "to": "live"}, {"key": "LIVE_MAX_TRADES_DAY", "to": 9}):
            self.assertEqual(odluka.klasa(pc), "pravi_novac", pc)
        for pc in ({"key": "dca_token_cap", "to": 0.2}, {"key": "runup_max", "to": 0.1}, {"key": "require_signal", "to": True},
                   {"key": "auto_skip", "to": [["kol", "x"]]}, {"caller": "abc", "platform": "x", "weight": 0.5},
                   {"insider_label": {"wallet": "w", "label": "bot"}}, {"group_label": {"group_id": "g1", "label": "ekipa"}}):
            self.assertEqual(odluka.klasa(pc), "auto", pc)
        for pc in (None, {}, {"key": "nepoznato", "to": 1}, {"posao": "ugasiti"}, "tekst"):
            self.assertEqual(odluka.klasa(pc), "kod", pc)
        self.assertTrue(odluka.REAL_KEYS <= set(assistnotes.APPLY))

    def test_a_change_that_needs_code_is_accepted_for_the_coding_session(self):
        nid = self.note(title="Ugasiti tok tradeova novih tokena")
        self.claude.reviews[nid] = {**SLAZEM, "verdict": "doradi", "critique": "Ostaviti tradeove otvorenih pozicija."}
        self.tick()
        self.assertEqual(self.status(nid), "prihvaćeno")
        self.assertEqual(self.decision(nid)["odluka"], "prihvaceno_za_izvedbu")
        self.assertIn("(za izvedbu)", self.con.execute("SELECT owner_note FROM assistant_notes WHERE id=?", (nid,)).fetchone()[0])
        zi = vijece.za_izvedbu(self.con)
        self.assertEqual([z["id"] for z in zi], [nid])
        self.assertEqual(zi[0]["title"], "Ugasiti tok tradeova novih tokena")
        self.assertEqual(set(zi[0]["critiques"]), {"openai", "claude"})
        self.assertIn("Ostaviti tradeove", zi[0]["critiques"]["claude"]["critique"])
        self.assertIn("za izvedbu 1", self.logged("vijeće: stanje:")[-1])
        # once the coding session marks it applied it leaves the list
        assistnotes.record_applied(self.con, nid, "kod", None, "izvedeno")
        self.assertEqual(vijece.za_izvedbu(self.con), [])

    def test_an_apply_that_raises_goes_to_the_owner_with_the_error(self):
        nid = self.note(pc={"key": "dca_token_cap", "from": 0.9, "to": 0.2})      # "from" is not the value in force
        self.openai.reviews[nid] = {**SLAZEM, "verdict": "doradi", "refined_change": json.dumps({"key": "dca_token_cap", "from": 0.9, "to": 0.25})}
        self.tick()
        d = self.decision(nid)
        self.assertEqual(d["odluka"], "vlasniku")
        self.assertIn("primjena nije prošla", d["razlog"])
        n = store.note(self.con, nid)
        self.assertEqual(n["status"], "novo")
        self.assertEqual(n["proposed_change"], {"key": "dca_token_cap", "from": 0.9, "to": 0.2})   # the note as it was

    def test_log_lines_are_capped_and_prefixed(self):
        nid = self.note()
        long = "Vrlo duga kritika s brojevima. " * 150
        self.openai.reviews[nid] = {**SLAZEM, "critique": long}
        self.tick()
        mine = self.logged(f"#{nid}")
        self.assertGreater(len(self.logged(f"vijeće: ocjena #{nid} OpenAI (nastavak): ")), 1)
        for ln in self.lines:
            self.assertTrue(ln.startswith("vijeće: "), ln[:60])
            self.assertLessEqual(len(ln), 900)
        self.assertTrue(mine)


class GrokWait(Base):
    def test_before_six_hours_it_waits_after_it_the_api_reviewer_decides(self):
        nid = self.note(cnotes.KID, pc={"key": "dca_token_cap", "to": 0.2})       # OpenAI's: Claude and Grok review
        self.tick()
        self.assertEqual(len(self.claude.calls), 1)
        self.assertEqual(self.openai.review_calls(), [])
        self.assertIsNone(self.decision(nid))
        self.tick(self.now + 6 * 3600 - 120)
        self.assertIsNone(self.decision(nid))
        self.assertEqual(self.status(nid), "novo")
        self.tick(self.now + 6 * 3600 + 120)
        d = self.decision(nid)
        self.assertEqual(d["odluka"], "prihvaceno_primijenjeno")
        self.assertIn("Grok nije odgovorio u 6 h", d["razlog"])
        self.assertIn("Grok nije odgovorio u 6 h", self.logged(f"vijeće: odluka #{nid} ")[0])
        self.assertEqual(settings.raw(self.con)["dca_token_cap"], 0.2)

    def test_a_lone_veto_while_grok_is_late_goes_to_the_owner(self):
        # 18.11. (review): one voice against, while the proposer is for and Grok is silent, is not a rejection
        nid = self.note(cnotes.KID)                                                # OpenAI's: Claude and Grok review
        self.claude.reviews[nid] = {**SLAZEM, "verdict": "protiv", "critique": "Nema dokaza."}
        self.tick()
        self.tick(self.now + 6 * 3600 + 120)
        d = self.decision(nid)
        self.assertEqual(d["odluka"], "vlasniku")
        self.assertEqual(self.status(nid), "novo")
        self.assertIn("Grok nije odgovorio u 6 h", d["razlog"])

    def test_labels_and_weights_stay_out_of_the_council(self):
        # Grok sends these by the dozen; they keep their own paths and their addresses do not leave the app
        w = "So11111111111111111111111111111111111111112"
        self.assertTrue(store.oznaka({"insider_label": {"wallet": w, "label": "insider"}}))
        self.assertTrue(store.oznaka({"group_label": {"group_id": "g1", "label": "ekipa"}}))
        self.assertTrue(store.oznaka({"caller": "x:abc", "weight": 0.5}))
        self.assertFalse(store.oznaka({"key": "dca_token_cap", "to": 0.2}))
        self.assertFalse(store.oznaka(None))
        n = {"kind": "suggestion", "status": "novo", "ts": self.now, "key_id": GROK_KID,
             "proposed_change": {"group_label": {"group_id": "g1", "label": "ekipa"}}}
        self.assertFalse(store.u_vijecu(n, self.now - 5))
        self.assertTrue(store.u_vijecu({**n, "proposed_change": None}, self.now - 5))

    def test_the_wait_is_an_env_setting(self):
        nid = self.note(store.CLAUDE_KID)
        with mock.patch.dict(os.environ, {"VIJECE_GROK_WAIT_S": "600"}):
            self.tick(self.now + 300)
            self.assertIsNone(self.decision(nid))
            self.tick(self.now + 700)
        self.assertEqual(self.decision(nid)["odluka"], "prihvaceno_za_izvedbu")

    def test_groks_review_decides_at_once(self):
        nid = self.note(cnotes.KID)
        self.tick()
        r = vmcp.submit_review({"note_id": nid, "verdict": "protiv", "critique": "Na X-u se vidi suprotno."}, GROK_KID,
                               self.now + 60, log=self.log)
        self.assertEqual(r["decision"], "vlasniku")                    # Claude agrees, Grok is against: a split
        self.assertEqual(self.status(nid), "novo")
        self.assertIn("Grok: protiv", self.logged(f"vijeće: odluka #{nid} ")[0])
        r = vmcp.submit_review({"note_id": nid, "verdict": "slazem", "critique": "x"}, GROK_KID, log=self.log)
        self.assertIn("already decided", r["error"])

    def test_grok_cannot_review_its_own_proposal(self):
        nid = self.note(GROK_KID)
        r = vmcp.submit_review({"note_id": nid, "verdict": "slazem", "critique": "Moj je i dobar je."}, GROK_KID, log=self.log)
        self.assertIn("your own proposal", r["error"])
        self.assertEqual(store.ocjene(self.con, nid), {})
        d, err = mcpapi._tool("submit_council_review", {"note_id": nid, "verdict": "slazem", "critique": "x"}, GROK_KID)
        self.assertTrue(err)


class Unavailable(Base):
    def test_budget_spent_waits_and_never_decides_on_one_voice(self):
        nid = self.note(pc={"key": "dca_token_cap", "to": 0.2})
        with mock.patch.dict(os.environ, {"VIJECE_OPENAI_DAY_USD": "0.0001"}):
            self.tick()
            self.tick(self.now + 900)
            self.tick(self.now + 3600)
        self.assertEqual(self.openai.calls, [])
        self.assertEqual(len(self.claude.calls), 1)
        self.assertIsNone(self.decision(nid))
        self.assertEqual(self.status(nid), "novo")
        said = self.logged("OpenAI danas ne može ocjenjivati")
        self.assertEqual(len(said), 1)                                 # said once a day
        self.assertIn("budžet", said[0])
        with mock.patch.dict(os.environ, {"VIJECE_OPENAI_DAY_USD": "0.0001"}):
            self.tick(self.now + 30 * 3600)                            # even a day later: Grok is no reviewer here
        self.assertIsNone(self.decision(nid))
        self.tick(self.now + 30 * 3600 + 900)                          # the budget is back: reviewed and decided
        self.assertEqual(self.decision(nid)["odluka"], "prihvaceno_primijenjeno")

    def test_the_spend_is_booked_and_the_cap_holds(self):
        ids = [self.note(title=f"P{i}") for i in range(12)]
        with mock.patch.dict(os.environ, {"VIJECE_CLAUDE_DAY_USD": "0.20"}):
            self.tick()
            self.tick(self.now + 900)
        t = store.trosak(self.con, self.now)
        self.assertLessEqual(t["claude"], 0.20)
        self.assertLessEqual(t["openai"], store.strop("openai"))
        self.assertGreater(t["openai"], 0)
        self.assertLess(len(self.claude.calls), len(ids))
        self.assertTrue(any(b["model"] == openai_api.MODEL_CHEAP for b in self.openai.review_calls()))   # the cheap model near the cap
        d = daily.vijece(self.now, {"trade": self.db})
        self.assertAlmostEqual(d["openai_usd"], round(t["openai"], 4))
        self.assertEqual(d["ocjena"], len(self.openai.review_calls()) + len(self.claude.calls))
        line = daily.line({"day": "2026-11-18", "vijece": d})
        self.assertRegex(line, r"vijeće OpenAI \$\d+,\d\d, Claude \$\d+,\d\d, \d+ ocjena, \d+ odluka, za izvedbu \d+")

    def test_no_key_means_unavailable_and_nothing_crashes(self):
        nid = self.note(pc={"key": "dca_token_cap", "to": 0.2})
        with mock.patch.dict(os.environ, {"OPENAI_API_KEY": "", "ANTHROPIC_API_KEY": ""}):
            out = self.tick()
            self.assertEqual(kriticari.nedostupan(self.con, "openai"), "nema ključa")
            self.assertEqual(kriticari.nedostupan(self.con, "claude"), "nema ključa")
            self.assertEqual(smjer.otvori(self.con, self.now, self.log), None)
            with self.assertRaises(kriticari.Nedostupan):
                kriticari.ocijeni_claude(store.note(self.con, nid), {})
            with self.assertRaises(kriticari.Nedostupan):
                kriticari.ocijeni_openai(store.note(self.con, nid), {})
        self.assertEqual((out["ocjena"], out["odluka"]), (0, 0))
        self.assertEqual(self.openai.calls + self.claude.calls, [])
        self.assertIsNone(self.decision(nid))
        self.assertEqual(len(self.logged("danas ne može ocjenjivati (nema ključa)")), 2)

    def test_one_key_missing_is_one_voice_and_one_voice_never_decides(self):
        nid = self.note()
        with mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": ""}):
            self.tick()
            self.tick(self.now + 8 * 3600)
        self.assertEqual(len(self.openai.review_calls()), 1)
        self.assertIsNone(self.decision(nid))

    def test_the_owner_switch_of_the_openai_critic_is_followed(self):
        settings.set_flag(self.con, "openai_kritika", "off", settings.owner())
        nid = self.note()
        self.tick()
        self.assertEqual(self.openai.calls, [])
        self.assertIsNone(self.decision(nid))

    def test_a_failed_call_is_logged_and_tried_again(self):
        nid = self.note()
        with mock.patch.object(kriticari, "_claude_call", side_effect=kriticari.Greska("APIConnectionError: mreža")):
            self.tick()
        self.assertIsNone(self.decision(nid))
        self.assertTrue(self.logged(f"vijeće: ocjena #{nid} (Claude) nije uspjela"))
        self.tick(self.now + 900)
        self.assertEqual(self.decision(nid)["odluka"], "prihvaceno_za_izvedbu")

    def test_an_unusable_answer_is_not_a_review(self):
        nid = self.note()
        self.claude.reviews[nid] = {"verdict": "možda", "critique": "x", "refined_change": None, "kako_povecava_zaradu": ""}
        self.tick()
        self.assertNotIn("claude", store.ocjene(self.con, nid))
        self.assertIsNone(self.decision(nid))
        self.assertGreater(store.trosak(self.con, self.now)["claude"], 0)       # it still cost


class ClaudeCall(unittest.TestCase):
    """The SDK pattern (report/ai.interpret's): JSON by schema, effort medium, the fallback beta first, the plain call
    on a 400, the refusal check; no thinking, temperature or tool_choice."""
    def fake_sdk(self, beta_raises=False, stop="end_turn", text=None):
        seen = {"beta": [], "plain": [], "client": []}

        class BadRequestError(Exception):
            pass

        def resp():
            return types.SimpleNamespace(
                stop_reason=stop, model="claude-opus-5-5",
                usage=types.SimpleNamespace(input_tokens=10_000, output_tokens=2_000),
                content=[types.SimpleNamespace(type="thinking", thinking="…"),
                         types.SimpleNamespace(type="text", text=text if text is not None else json.dumps(SLAZEM))])

        class Beta:
            def create(self, **kw):
                seen["beta"].append(kw)
                if beta_raises:
                    raise BadRequestError("unknown beta")
                return resp()

        class Plain:
            def create(self, **kw):
                seen["plain"].append(kw)
                return resp()

        class Anthropic:
            def __init__(self, **kw):
                seen["client"].append(kw)
                self.beta = types.SimpleNamespace(messages=Beta())
                self.messages = Plain()
        mod = types.ModuleType("anthropic")
        mod.Anthropic, mod.BadRequestError = Anthropic, BadRequestError
        return mod, seen

    def call(self, mod, env=None):
        with mock.patch.dict(sys.modules, {"anthropic": mod}), \
                mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-ant-x", **(env or {})}):
            return kriticari._claude_call("sustav", "tekst", kriticari.SCHEMA, 6000)

    def test_the_request(self):
        mod, seen = self.fake_sdk()
        res = self.call(mod)
        self.assertEqual(res["data"]["verdict"], "slazem")
        self.assertAlmostEqual(res["usd"], 10_000 * 4 / 1e6 + 2_000 * 20 / 1e6)
        kw = seen["beta"][0]
        self.assertEqual(kw["betas"], ["server-side-fallback-2026-07-01"])
        self.assertEqual(kw["fallbacks"], "default")
        self.assertEqual(kw["model"], "claude-opus-5-5")
        self.assertEqual(kw["output_config"], {"effort": "medium", "format": {"type": "json_schema", "schema": kriticari.SCHEMA}})
        self.assertEqual(kw["system"], "sustav")
        self.assertEqual(kw["messages"], [{"role": "user", "content": "tekst"}])
        for banned in ("thinking", "temperature", "tool_choice", "tools"):
            self.assertNotIn(banned, kw)
        self.assertEqual(seen["client"][0]["max_retries"], 2)
        self.assertEqual(seen["plain"], [])

    def test_a_400_falls_back_to_the_plain_call_and_the_model_is_an_env_setting(self):
        mod, seen = self.fake_sdk(beta_raises=True)
        res = self.call(mod, {"VIJECE_CLAUDE_MODEL": "claude-test-1"})
        self.assertEqual(res["data"]["verdict"], "slazem")
        self.assertEqual(seen["plain"][0]["model"], "claude-test-1")
        self.assertNotIn("betas", seen["plain"][0])

    def test_refusal_and_bad_json_are_errors_with_their_cost(self):
        for kw in ({"stop": "refusal"}, {"text": "nije json"}):
            mod, _seen = self.fake_sdk(**kw)
            with self.assertRaises(kriticari.Greska) as cm:
                self.call(mod)
            self.assertGreater(cm.exception.usd, 0)

    def test_no_key_or_no_sdk_is_unavailable(self):
        with mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": ""}):
            with self.assertRaises(kriticari.Nedostupan):
                kriticari._claude_call("s", "t", kriticari.SCHEMA, 100)
        with mock.patch.dict(sys.modules, {"anthropic": None}), mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": "k" * 20}):
            with self.assertRaises(kriticari.Nedostupan):
                kriticari._claude_call("s", "t", kriticari.SCHEMA, 100)


class Seeds(Base):
    def test_seeding_happens_once(self):
        self.con.execute("DELETE FROM settings WHERE k=?", (sjeme.ONCE_KEY,))
        self.con.commit()
        self.tick()
        rows = self.con.execute("SELECT id, title, key_id, proposed_change, evidence FROM assistant_notes ORDER BY id").fetchall()
        self.assertEqual(len(rows), 4)
        self.assertEqual({r[2] for r in rows}, {store.CLAUDE_KID})
        self.assertTrue(all(r[3] is None for r in rows))                              # class kod
        self.assertIn("400 KOL", rows[0][1])
        self.assertEqual(json.loads(rows[0][4])["n"], 308)
        self.assertEqual(json.loads(rows[2][4])["n"], 1043)
        self.assertEqual(len(self.openai.review_calls()), 4)                          # OpenAI reviews, Grok is waited for
        self.assertEqual(self.claude.calls, [])
        self.assertEqual(len(vmcp.ceka_groka(self.con)), 4)
        self.tick(self.now + 900)
        self.tick(self.now + 1800)
        self.assertEqual(self.con.execute("SELECT COUNT(*) FROM assistant_notes").fetchone()[0], 4)
        self.assertEqual(len(self.logged("vijeće: sjeme:")), 1)
        for p in sjeme.PRIJEDLOZI:
            self.assertLessEqual(len(p["title"]), assistnotes.TITLE_MAX)


class Backlog(Base):
    def test_notes_older_than_the_start_are_not_touched(self):
        old = self.note(pc={"key": "dca_token_cap", "to": 0.2})
        self.con.execute("UPDATE assistant_notes SET ts=? WHERE id=?", (self.now - 3600, old))
        self.con.commit()
        new = self.note()
        self.tick()
        self.assertEqual(self.status(old), "novo")
        self.assertIsNone(self.decision(old))
        self.assertEqual(store.ocjene(self.con, old), {})
        self.assertIsNotNone(self.decision(new))
        self.assertNotIn("dca_token_cap", settings.raw(self.con))
        old2 = self.note(cnotes.KID)
        self.con.execute("UPDATE assistant_notes SET ts=? WHERE id=?", (self.now - 3600, old2))
        self.con.commit()
        r = vmcp.submit_review({"note_id": old2, "verdict": "slazem", "critique": "x"}, GROK_KID, log=self.log)
        self.assertIn("does not wait for the council", r["error"])
        self.assertEqual(vmcp.ceka_groka(self.con), [])

    def test_the_first_run_sets_the_start_and_other_kinds_are_not_the_councils(self):
        con2_db = os.path.join(self.tmp.name, "t2.db")
        con = store.connect(con2_db)
        try:
            assistnotes.submit_suggestion(con, GROK_KID, "Stari prijedlog", "x")
            con.execute("UPDATE assistant_notes SET ts=ts-100")
            con.commit()
            self.assertEqual(store.red(con), [])                 # before the first pass: nothing is the council's
            posao.tick(self.now, self.log, con)
            self.assertEqual(settings.raw(con)[store.START_KEY], self.now)
            assistnotes.submit_daily_summary(con, GROK_KID, "Sažetak", "x")
            self.assertEqual({n["title"] for n in store.red(con)} & {"Stari prijedlog", "Sažetak"}, set())
        finally:
            con.close()

    def test_a_note_the_owner_decided_leaves_the_queue(self):
        nid = self.note()
        assistnotes.decide(self.con, nid, "odbijeno", "ne")
        self.tick()
        self.assertEqual(self.openai.calls, [])
        self.assertIsNone(self.decision(nid))


class Direction(Base):
    def open_fresh(self):
        self.con.execute("DELETE FROM settings WHERE k=?", (smjer.ONCE_KEY,))
        self.con.commit()

    def test_the_session_stores_proposals_under_the_members_keys(self):
        self.open_fresh()
        self.tick()
        rows = self.con.execute("SELECT id, title, key_id, evidence, proposed_change, kind FROM assistant_notes ORDER BY id").fetchall()
        self.assertEqual([r[2] for r in rows], [cnotes.KID, cnotes.KID, store.CLAUDE_KID])
        for r in rows:
            self.assertTrue(r[1].startswith("Smjer: "), r[1])
            self.assertEqual(r[5], "suggestion")
            ev = json.loads(r[3])
            self.assertEqual((ev["vijece"], ev["sjednica"]), ("smjer", self.now))
        self.assertEqual(json.loads(rows[1][4]), {"key": "runup_max", "to": 0.1})
        body = [b for b in self.openai.calls if b["text"]["format"]["name"] == "vijece_smjer"][0]
        self.assertIn("Strategija NOVČANIKA", body["input"])
        self.assertIn("STANJE ALATA", body["input"])
        self.assertTrue(self.logged("vijeće: smjer: sjednica otvorena"))
        self.assertTrue(self.logged("vijeće: smjer: OpenAI predlaže"))
        # the proposals went through the normal cross-review in the same pass: OpenAI's by Claude, Claude's by OpenAI
        self.assertEqual(len(self.claude.calls), 1 + 2)
        self.assertEqual(len(self.openai.review_calls()), 1)
        self.assertEqual(settings.raw(self.con)[smjer.ONCE_KEY], self.now)

    def test_it_never_opens_twice_in_a_week_and_opens_in_the_next(self):
        self.open_fresh()
        monday = 1_794_787_200 + 3600                      # Mon 16.11.2026 01:00 UTC
        self.assertEqual(time.gmtime(monday).tm_wday, 0)
        store.start_ts(self.con, monday - 10)
        self.assertEqual(smjer.na_redu(self.con, monday), "prva sjednica nakon deploya")
        self.assertIsNotNone(smjer.otvori(self.con, monday, self.log, "prva"))
        n0 = self.con.execute("SELECT COUNT(*) FROM assistant_notes").fetchone()[0]
        for h in (1, 30, 80, 150):                          # the same week (through Sunday)
            self.assertIsNone(smjer.na_redu(self.con, monday + h * 3600), h)
            smjer.korak(self.con, monday + h * 3600, self.log)
        smjer.zakljuci(self.con, monday + 150 * 3600, self.log)
        self.assertIsNone(smjer.na_redu(self.con, monday + 160 * 3600))            # Sunday evening: still this week
        self.assertEqual(self.con.execute("SELECT COUNT(*) FROM assistant_notes").fetchone()[0], n0)
        self.assertEqual(smjer.na_redu(self.con, monday + 7 * 86400), "tjedna sjednica (ponedjeljak)")
        smjer.korak(self.con, monday + 7 * 86400, self.log)
        self.assertGreater(self.con.execute("SELECT COUNT(*) FROM assistant_notes").fetchone()[0], n0)
        self.assertIsNone(smjer.na_redu(self.con, monday + 7 * 86400 + 600))        # open: one at a time

    def test_a_changed_learner_verdict_opens_one(self):
        self.open_fresh()
        self.verdict = "premalo"
        s = smjer.otvori(self.con, self.now, self.log, "prva")
        self.assertEqual(s["presuda_ucenja"], "premalo")
        smjer.zakljuci(self.con, self.now + 3600, self.log, force=True)
        with mock.patch.object(smjer, "tjedan", lambda ts: 1):                       # the week rule out of the way
            self.assertIsNone(smjer.na_redu(self.con, self.now + 30 * 3600))
            self.verdict = "kandidat"
            self.assertIsNone(smjer.na_redu(self.con, self.now + 2 * 3600))          # not twice in a day
            self.assertEqual(smjer.na_redu(self.con, self.now + 30 * 3600), "presuda učenja se promijenila (premalo → kandidat)")

    def test_grok_gets_the_request_and_the_session_closes_with_its_lines(self):
        self.open_fresh()
        self.tick()
        q = vmcp.queue()
        req = q["direction_request"]
        self.assertEqual(req["session_ts"], self.now)
        self.assertIn("STANJE ALATA", req["brief"])
        self.assertTrue(req["answer_with"]["arguments"]["title"].startswith("Smjer: "))
        kinds = [t["kind"] for t in vmcp.grok_tasks(self.con, self.now)]
        self.assertEqual(kinds[0], "council_direction")
        self.assertEqual(kinds.count("council_review"), 3)
        d, err = mcpapi._tool("submit_suggestion", {"title": "Smjer: pratiti samo račune koji stvarno miču midcapove",
                                                    "interpretation": "Na X-u ih je desetak.\nKako povećava neto zaradu: manje šuma"},
                              GROK_KID)
        self.assertFalse(err)
        self.assertIsNone(vmcp.queue()["direction_request"])                          # Grok answered
        self.assertNotIn("council_direction", [t["kind"] for t in vmcp.grok_tasks(self.con, self.now)])
        self.assertIsNone(smjer.zakljuci(self.con, self.now + 600, self.log))         # proposals still wait
        self.tick(self.now + 6 * 3600 + 600)                                          # Grok's reviews timed out; its note reviewed
        res = smjer.zadnji(self.con)
        self.assertIsNotNone(res)
        self.assertEqual(len(res["prihvaceno"]), 4)
        self.assertEqual(res["ceka"], [])
        self.assertTrue(self.logged("vijeće: smjer: sjednica od"))
        acc = self.logged("vijeće: smjer: PRIHVAĆENO #")
        self.assertEqual(len(acc), 4)
        self.assertIn("kako povećava zaradu: manji trošak", acc[0])
        self.assertIn("mjerenje: EV odabranih", acc[0])
        self.assertIn("manje šuma", "".join(acc))
        self.assertEqual(vmcp.council()["last_direction"]["sjednica"], self.now)
        self.assertEqual(settings.raw(self.con).get("runup_max"), 0.1)                # the allow-listed one was applied
        self.assertEqual(self.status(d["id"]), "prihvaćeno")

    def test_a_session_closes_after_24_h_with_what_waits(self):
        self.open_fresh()
        with mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": ""}):
            self.tick()
            self.assertEqual(smjer.sjednica(self.con)["clanovi"]["claude"], "ceka: nema ključa")
            self.assertIsNone(smjer.zakljuci(self.con, self.now + 23 * 3600, self.log))
            res = smjer.zakljuci(self.con, self.now + 24 * 3600 + 1, self.log)
        self.assertEqual(len(res["ceka"]), 2)
        self.assertIn("Claude", res["ceka"][0]["razlog"])
        self.assertTrue(self.logged("vijeće: smjer: ČEKA OCJENU #"))
        self.assertIn("nisu odgovorili: Claude", self.logged("vijeće: smjer: sjednica od")[0])

    def test_a_member_that_owed_an_answer_is_asked_again(self):
        self.open_fresh()
        with mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": ""}):
            self.tick()
        self.assertEqual([c for c in self.claude.calls if "prijedlozi" in c["schema"]["properties"]], [])
        self.tick(self.now + 900)
        self.assertEqual(smjer.sjednica(self.con)["clanovi"], {"openai": "ok", "claude": "ok"})
        self.assertEqual(self.con.execute("SELECT COUNT(*) FROM assistant_notes WHERE key_id=?", (store.CLAUDE_KID,)).fetchone()[0], 1)


class Learner(Base):
    """18.11.: the council sees the learner's variants and its forward test, and deliberates once more."""

    def test_the_learner_block_carries_the_variants_and_the_demo_line(self):
        from veliki import nauceno, ucenik
        st = {"n": 111, "clusters": 71, "ev": 0.049, "ev_trade": 0.04, "hit": 0.6, "lo": 0.017, "hi": 0.082}
        summ = {"verdict": "nema_plusa", "verdict_text": "nema dokazanog plusa", "rows": 9000, "days": 46, "test_days": 39,
                "picked": {**st, "ev": 0.008, "lo": -0.015, "hi": 0.032}, "all": {**st, "ev": -0.045}, "helps": ["a"],
                "hurts": ["b"], "variants": {"thr": {"0.01": st, "0.02": {**st, "n": 49, "ev": 0.071}, "0.03": {"n": 0}},
                                             "rt": {"0.020": st, "0.015": st}, "fixed": {"ispod × siroko": st}}}
        demo = ("veliki naučeno (demo): pravilo od 18.11.: ulaz samo uz prognozu iznad +1 %; otvoreno 2; zatvoreno 0; "
                "presuda nakon 21 dana ili 60 token-dana: još se mjeri")
        with mock.patch.object(nauceno, "summary", lambda: summ), mock.patch.object(ucenik, "line_ro", lambda now: demo):
            txt = smjer._ucenje(self.now, self.con)
            mock.patch.stopall()                                  # the real IZVORI: the block inside the whole brief
            self.addCleanup(mock.patch.stopall)
            with mock.patch.object(nauceno, "summary", lambda: summ), mock.patch.object(ucenik, "line_ro", lambda now: demo), \
                    mock.patch("veliki.makro.current", return_value=None), mock.patch("builtins.print"), \
                    mock.patch("veliki.live.btc_state", return_value={"state": "normalno", "why": "mirno", "known": True,
                                                                      "last_end": self.now - 600}):
                brief = smjer.brief(self.now, self.con)
        self.assertEqual(len(txt.splitlines()), 3)
        self.assertIn("prognoza iznad +1%: +4.9% [+1.7%; +8.2%], n=111 (71 token-dana)", txt)
        self.assertIn("prognoza iznad +2%: +7.1%", txt)
        self.assertIn("prognoza iznad +3%: nema tradeova", txt)
        self.assertIn("uz trošak runde 2.0%: +4.9%", txt)
        self.assertIn("uz trošak runde 1.5%: +4.9%", txt)
        self.assertIn("gledani su na ISTIM neviđenim danima kao i rezultat: to su hipoteze za nove dane, nisu dokaz", txt)
        self.assertIn("pravilo od 18.11.: ulaz samo uz prognozu iznad +1 %; otvoreno 2; zatvoreno 0", txt)
        self.assertNotIn("ispod × siroko", txt)                   # the plain rules stay in the learner's own line
        self.assertIn("prognoza iznad +1%: +4.9% [+1.7%; +8.2%], n=111 (71 token-dana)", brief)   # not cut by the cap
        self.assertIn("presuda nakon 21 dana ili 60 token-dana: još se mjeri", brief)
        self.assertLessEqual(len(brief), smjer.BRIEF_MAX)

    def test_without_a_result_only_the_demo_line_and_without_both_nothing(self):
        from veliki import nauceno, ucenik
        with mock.patch.object(nauceno, "summary", lambda: None), mock.patch.object(ucenik, "line_ro", lambda now: None):
            self.assertIsNone(smjer._ucenje(self.now, self.con))
        with mock.patch.object(nauceno, "summary", lambda: None), \
                mock.patch.object(ucenik, "line_ro", lambda now: ucenik.PREFIX + "isključen"):
            self.assertIn("isključen", smjer._ucenje(self.now, self.con))

    def test_the_second_one_time_session_opens_once(self):
        self.con.execute("DELETE FROM settings WHERE k=?", (smjer.ONCE_KEY_B,))   # the deploy: the first one is done
        self.con.commit()
        self.assertEqual(smjer.ONCE_KEY_B, "vijece_smjer_1811b")
        from veliki import nauceno
        for leaky in ({}, {"ts": 1, "verdict": "kandidat"}, {"ts": 1, "purge": "true"}):
            with mock.patch.object(nauceno, "latest", lambda: leaky):
                self.assertIsNone(smjer.na_redu(self.con, self.now))                # never on the leaky result
        p = mock.patch.object(nauceno, "latest", lambda: {"ts": 1, "purge": True})  # the corrected result arrived
        p.start()
        self.addCleanup(p.stop)
        why = smjer.na_redu(self.con, self.now)
        self.assertEqual(why, "nova sjednica: stigao rezultat učenja po pragu prognoze")
        s = smjer.korak(self.con, self.now, self.log)
        self.assertEqual(s["razlog"], why)
        self.assertEqual(settings.raw(self.con)[smjer.ONCE_KEY_B], self.now)
        self.assertTrue(self.logged("vijeće: smjer: sjednica otvorena (nova sjednica: stigao rezultat učenja"))
        smjer.zakljuci(self.con, self.now + 3600, self.log, force=True)
        with mock.patch.object(smjer, "tjedan", lambda ts: 1):                      # the week rule out of the way
            self.assertIsNone(smjer.na_redu(self.con, self.now + 2 * 3600))         # once
            self.assertIsNone(smjer.korak(self.con, self.now + 2 * 3600, self.log))

    def test_it_waits_for_an_open_session_and_any_new_session_uses_it_up(self):
        from veliki import nauceno
        s = smjer.otvori(self.con, self.now, self.log, "tjedna")                    # open before the deploy
        self.con.execute("DELETE FROM settings WHERE k=?", (smjer.ONCE_KEY_B,))
        self.con.commit()
        self.assertNotIn(smjer.ONCE_KEY_B, settings.raw(self.con))                  # no corrected result: not used up
        p = mock.patch.object(nauceno, "latest", lambda: {"ts": 1, "purge": True})
        p.start()
        self.addCleanup(p.stop)
        self.assertIsNone(smjer.na_redu(self.con, self.now + 600))                  # one at a time
        self.assertEqual(smjer.korak(self.con, self.now + 600, self.log)["ts"], s["ts"])
        smjer.zakljuci(self.con, self.now + 3600, self.log, force=True)
        self.assertEqual(smjer.na_redu(self.con, self.now + 3700), smjer.RAZLOG_B)  # opens when that one closed
        self.con.execute("DELETE FROM settings WHERE k IN (?, ?)", (smjer.ONCE_KEY, smjer.ONCE_KEY_B))
        self.con.commit()
        self.assertEqual(smjer.na_redu(self.con, self.now + 3800), "prva sjednica nakon deploya")
        smjer.otvori(self.con, self.now + 3800, self.log, "prva")                   # a new install: one session, both keys
        raw = settings.raw(self.con)
        self.assertTrue(raw[smjer.ONCE_KEY] and raw[smjer.ONCE_KEY_B])


class WalletDirection(Base):
    """19.11. (vlasnik: "I want OpenAI and Grok bot to focus on working out the strategy for finding such wallets ...
    and which APIs to include"): the decision of 19.11., the wallet question, one more session once, Grok's task."""

    def test_the_decision_of_19_11_leads_the_brief(self):
        txt = smjer.brief(self.now, self.con)
        self.assertIn("19.11.: prvi fokus su NOVČANICI: naći novčanike koji kupuju prije pumpe / prije poziva influencera i "
                      "prodaju u pumpu (insajderski novčanici), dokazati na povijesti da se kopiranje isplati nakon troška i "
                      "kašnjenja, pa ih kopirati unutar sekunde. Drugi fokus: strategija ulaza i izlaza za midcapove od 15 M $ "
                      "naviše. Influenceri i Telegram osvježavaju se jednom u 5 dana i ne dobivaju druge resurse.", txt)
        self.assertLess(txt.index("prvi fokus su NOVČANICI"), txt.index("STANJE ALATA"))
        self.assertLessEqual(len(txt), smjer.BRIEF_MAX)

    def test_the_question_is_the_wallet_strategy_and_the_schema_stays(self):
        q = smjer.PITANJE
        for part in ("NAĆI", "Heliusa", "koliko koštaju", "definicija pumpe", "botove, market makere, novčanike tima",
                     "svježe jednokratne", "financirao", "DOKAZATI", "do trenutka odluke", "izvan uzorka", "1-2 s",
                     "stvarni trošak", "KOPIRATI unutar sekunde", "vanjski alat", "naknade", "čuvanje ključa",
                     "prva tri koraka", "pravim novcem", "14 dana"):
            self.assertIn(part, q)
        self.assertEqual(smjer.SCHEMA["properties"]["prijedlozi"]["items"]["required"],
                         ["naslov", "obrazlozenje", "koraci", "sto_ugasiti", "koji_podaci", "kako_povecava_zaradu",
                          "mjerenje", "proposed_change"])
        smjer.otvori(self.con, self.now, self.log, "test")
        body = [b for b in self.openai.calls if b["text"]["format"]["name"] == "vijece_smjer"][0]
        self.assertIn("Strategija NOVČANIKA", body["input"])
        self.assertTrue(self.logged("pitanje: Strategija NOVČANIKA"))

    def test_the_19_11_session_opens_once_after_the_deploy(self):
        self.con.execute("DELETE FROM settings WHERE k=?", (smjer.ONCE_KEY_C,))   # the deploy: the earlier ones are done
        self.con.commit()
        self.assertEqual(smjer.ONCE_KEY_C, "vijece_smjer_1911")
        why = smjer.na_redu(self.con, self.now)
        self.assertEqual(why, "nova sjednica: vlasnikov smjer 19.11. (novčanici)")
        s = smjer.korak(self.con, self.now, self.log)
        self.assertEqual(s["razlog"], why)
        self.assertEqual(settings.raw(self.con)[smjer.ONCE_KEY_C], self.now)
        self.assertTrue(self.logged("vijeće: smjer: sjednica otvorena (nova sjednica: vlasnikov smjer 19.11."))
        smjer.zakljuci(self.con, self.now + 3600, self.log, force=True)
        with mock.patch.object(smjer, "tjedan", lambda ts: 1):                      # the week rule out of the way
            self.assertIsNone(smjer.na_redu(self.con, self.now + 2 * 3600))         # once
            self.assertIsNone(smjer.korak(self.con, self.now + 2 * 3600, self.log))

    def test_it_waits_for_an_open_session_and_any_new_session_uses_it_up(self):
        s = smjer.otvori(self.con, self.now, self.log, "tjedna")                    # open before the deploy
        self.con.execute("DELETE FROM settings WHERE k=?", (smjer.ONCE_KEY_C,))
        self.con.commit()
        self.assertIsNone(smjer.na_redu(self.con, self.now + 600))                  # one at a time
        self.assertEqual(smjer.korak(self.con, self.now + 600, self.log)["ts"], s["ts"])
        smjer.zakljuci(self.con, self.now + 3600, self.log, force=True)
        self.assertEqual(smjer.na_redu(self.con, self.now + 3700), smjer.RAZLOG_C)  # opens when that one closed
        self.con.execute("DELETE FROM settings WHERE k IN (?, ?, ?)", (smjer.ONCE_KEY, smjer.ONCE_KEY_B, smjer.ONCE_KEY_C))
        self.con.commit()
        self.assertEqual(smjer.na_redu(self.con, self.now + 3800), "prva sjednica nakon deploya")
        smjer.otvori(self.con, self.now + 3800, self.log, "prva")                   # a new install: one session
        raw = settings.raw(self.con)
        self.assertTrue(raw[smjer.ONCE_KEY] and raw[smjer.ONCE_KEY_C])

    def test_grok_task_carries_the_wallet_question(self):
        smjer.otvori(self.con, self.now, self.log, "test")
        task = [t for t in vmcp.grok_tasks(self.con, self.now) if t["kind"] == "council_direction"][0]
        for part in ("WALLETS", "before influencer calls", "sell into the pump", "APIs to add or drop besides Helius",
                     "clustering by funder", "point-in-time", "1-2 s delay", "within a second", "custody", "14 days"):
            self.assertIn(part, task["instruction"])
        self.assertIn("Strategija NOVČANIKA", vmcp.queue()["direction_request"]["question"])
        self.assertIn("how to find, prove and copy the wallets", task["answer_with"]["arguments"]["title"])


class OwnerDecisions(Base):
    """18.11.: the owner's standing decisions lead every brief and every review; a proposal against them is refused."""

    def test_they_lead_the_brief_and_the_session(self):
        txt = smjer.brief(self.now, self.con)
        self.assertTrue(txt.startswith("ODLUKE VLASNIKA"))
        self.assertLess(txt.index("pravi novac se NE pauzira"), txt.index("STANJE ALATA"))
        self.assertIn("18.11.: pravi novac se NE pauzira; cilj svih resursa je da tradeovi pravim novcem budu profitabilni. "
                      "Prijedlozi 'pauzirati pravi novac' nisu prihvatljivi; prihvatljivi su prijedlozi koji mijenjaju ŠTO "
                      "pravi novac kupuje i kako izlazi, uz dokaz.", txt)
        self.assertIn("18.11.: vlasnik je odobrio jednokratno mjerenje troška jednim stvarnim krugom pri 0,3 i 0,5 SOL.", txt)
        self.assertEqual(len(smjer.ODLUKE_VLASNIKA), 3)
        smjer.otvori(self.con, self.now, self.log, "prva")
        body = [b for b in self.openai.calls if b["text"]["format"]["name"] == "vijece_smjer"][0]
        self.assertIn("pravi novac se NE pauzira", body["input"])
        self.assertIn("ODLUKE VLASNIKA", body["instructions"])
        self.assertIn("proturječi", smjer.SYSTEM)

    def test_the_reviewers_get_them_and_are_told_to_refuse_what_contradicts_them(self):
        self.note(title="Pauzirati pravi novac dok demo ne dokaže plus")
        self.tick()
        for sent, system in ((self.openai.review_calls()[0]["input"], self.openai.review_calls()[0]["instructions"]),
                             (self.claude.calls[0]["text"], self.claude.calls[0]["system"])):
            self.assertEqual(sent.count("pravi novac se NE pauzira"), 1)            # once, not doubled
            self.assertLess(sent.index("ODLUKE VLASNIKA"), sent.index("presuda: nema dokazanog plusa"))
            self.assertIn("ODLUKE VLASNIKA u\nkontekstu su njegove trajne odluke", system)
            self.assertIn('odbij ("protiv") ili ga doradi', system)

    def test_a_brief_stored_before_the_decisions_still_gets_them(self):
        note = {"id": 7, "predlagac": "grok", "title": "x", "interpretation": "y"}
        txt = kriticari.korisnik_tekst(note, {"stanje": "STANJE ALATA, staro: bez odluka"}, self.con)
        self.assertEqual(txt.count("pravi novac se NE pauzira"), 1)
        self.assertLess(txt.index("ODLUKE VLASNIKA"), txt.index("STANJE ALATA, staro"))
        new = kriticari.korisnik_tekst(note, {"stanje": smjer.brief(self.now, self.con)}, self.con)
        self.assertEqual(new.count("pravi novac se NE pauzira"), 1)

    def test_the_new_real_money_switch_is_never_the_councils(self):
        for pc in ({"key": "pravi_novac_nauceno", "from": "off", "to": "live"},
                   {"flag": "pravi_novac_nauceno", "mode": "off"}, {"key": "flag:pravi_novac_nauceno", "to": "live"}):
            self.assertEqual(odluka.klasa(pc), "pravi_novac", pc)


class Brief(Base):
    def test_nothing_private_and_under_the_cap(self):
        settings.put(self.con, "wallet_pub", OWNER_W, "test")
        srcs = (("Učenje", lambda now, con: "presuda: nema plusa; ključ sk-proj-AbCdEf0123456789AbCdEf0123 i OPENAI_API_KEY, "
                                           "HELIUS_API_KEY=abc, novčanik " + OWNER_W + ", datoteka run_insajderi.py"),
                ("Trošak", lambda now, con: "X 14.00 $; token " + "A" * 64 + " na memesonar-xyz.onrender.com /var/data/trade.db"),
                ("Dugo", lambda now, con: "brojevi " * 5000),
                ("Ploča", lambda now, con: "- red jedan\n- red dva"),
                ("Pada", lambda now, con: 1 / 0),
                ("Prazno", lambda now, con: None))
        with mock.patch.dict(os.environ, {"TAJNI_TOKEN": "vrijednost-tajne-12345"}):
            txt = smjer.brief(self.now, self.con, srcs + (("Env", lambda now, con: "vrijednost-tajne-12345"),))
        self.assertLessEqual(len(txt), smjer.BRIEF_MAX)
        for bad in ("sk-proj", "OPENAI_API_KEY", "HELIUS_API_KEY", OWNER_W, "run_insajderi.py", "A" * 40, "onrender.com",
                    "/var/data", "vrijednost-tajne-12345", "sk-test", "sk-ant"):
            self.assertNotIn(bad, txt, bad)
        self.assertIsNone(re.search(r"\b[A-Z][A-Z0-9]+(?:_[A-Z0-9]+)+\b", txt))
        self.assertIsNone(re.search(r"[A-Za-z0-9_\-]{40,}", txt))
        self.assertIn("presuda: nema plusa", txt)
        self.assertIn("X 14.00 $", txt)
        self.assertIn("NEDOSTAJE", txt)
        self.assertIn("Pada (ne može se pročitati: ZeroDivisionError)", txt)
        self.assertIn("Prazno (još nema spremljenog rezultata)", txt)

    def test_the_real_sources_never_raise(self):
        mock.patch.stopall()                                  # the real IZVORI; setUp's stand-ins off
        self.addCleanup(mock.patch.stopall)
        with mock.patch("veliki.makro.current", return_value=None), mock.patch("builtins.print"), \
                mock.patch("veliki.live.btc_state", return_value={"state": "normalno", "why": "mirno", "known": True,
                                                                  "last_end": self.now - 600}):
            txt = smjer.brief(self.now, self.con)
        self.assertLessEqual(len(txt), smjer.BRIEF_MAX)
        self.assertIn("STANJE ALATA", txt)
        self.assertIn("nikad ispod 3.0 %", txt)
        self.assertIsNone(re.search(r"\b[A-Z][A-Z0-9]+(?:_[A-Z0-9]+)+\b", txt))

    def test_what_is_sent_to_the_reviewers_is_scrubbed(self):
        settings.put(self.con, "wallet_pub", OWNER_W, "test")
        nid = self.note(title="Promijeniti HELIUS_API_KEY i novčanik", evidence={"wallet": OWNER_W, "datoteka": "start.sh"})
        self.tick()
        sent = self.openai.review_calls()[0]["input"] + self.claude.calls[0]["text"]
        for bad in (OWNER_W, "HELIUS_API_KEY", "start.sh", "sk-test"):
            self.assertNotIn(bad, sent)
        self.assertIn(f"PRIJEDLOG #{nid}", sent)
        self.assertIn("presuda: nema dokazanog plusa", sent)              # the state block
        self.assertIn("KRITIČNA", self.claude.calls[0]["system"])
        self.assertEqual(self.claude.calls[0]["system"], self.openai.review_calls()[0]["instructions"])


class Mcp(Base):
    def test_the_tools_are_declared(self):
        names = {t["name"]: t for t in mcpapi.TOOLS}
        for n in ("get_council_queue", "submit_council_review", "get_council"):
            self.assertIn(n, names)
        self.assertTrue(names["get_council_queue"]["annotations"]["readOnlyHint"])
        self.assertTrue(names["get_council"]["annotations"]["readOnlyHint"])
        self.assertFalse(names["submit_council_review"]["annotations"]["readOnlyHint"])
        self.assertEqual(names["submit_council_review"]["inputSchema"]["properties"]["verdict"]["enum"], list(store.VERDIKTI))
        self.assertIn("council_review", mcpapi.INSTRUCTIONS)
        json.dumps(mcpapi.TOOLS)

    def test_the_queue_lists_what_waits_for_grok(self):
        mine, oa, cl = self.note(GROK_KID), self.note(cnotes.KID, "OpenAI predlaže"), self.note(store.CLAUDE_KID, "Claude predlaže")
        self.tick()
        d, err = mcpapi._tool("get_council_queue", {}, GROK_KID)
        self.assertFalse(err)
        self.assertEqual([r["note_id"] for r in d["reviews"]], [oa, cl])       # not its own
        self.assertEqual(d["reviews"][0]["proposer"], "openai")
        self.assertEqual(d["reviews"][0]["other_reviews"]["claude"]["verdict"], "slazem")
        self.assertEqual(d["reviews"][0]["review_by_ts"], store.note(self.con, oa)["ts"] + 6 * 3600)
        self.assertIsNone(d["direction_request"])
        self.assertIn("error", mcpapi._tool("get_council_queue", {"limit": "puno"}, GROK_KID)[0])
        tasks = vmcp.grok_tasks(self.con, self.now)
        self.assertEqual([(t["kind"], t["note_id"]) for t in tasks], [("council_review", oa), ("council_review", cl)])
        self.assertEqual(tasks[0]["answer_with"]["tool"], "submit_council_review")
        self.assertEqual(tasks[0]["priority"], 1)
        self.assertEqual(self.decision(mine)["odluka"], "prihvaceno_za_izvedbu")

    def test_the_review_tool_validates_its_input(self):
        nid = self.note(cnotes.KID)
        ok = {"note_id": nid, "verdict": "doradi", "critique": "Bolje ovako."}
        for bad, word in (({**ok, "verdict": "možda"}, "verdict must be one of"),
                          ({**ok, "critique": ""}, "critique is required"),
                          ({**ok, "critique": "x" * 4001}, "longer than 4000"),
                          ({**ok, "refined_change": [1, 2]}, "one JSON object"),
                          ({**ok, "refined_change": "nije json"}, "JSON"),
                          ({**ok, "verdict": "slazem", "refined_change": {"key": "runup_max", "to": 0.1}}, "only with verdict doradi"),
                          ({**ok, "note_id": "abc"}, "note_id"),
                          ({**ok, "note_id": 9999}, "not a suggestion"),
                          ({"verdict": "slazem", "critique": "x"}, "note_id")):
            d, err = mcpapi._tool("submit_council_review", bad, GROK_KID)
            self.assertTrue(err, bad)
            self.assertIn(word, d["error"], bad)
        self.assertEqual(store.ocjene(self.con, nid), {})
        d, err = mcpapi._tool("submit_council_review", {**ok, "verdict": "agree", "critique": "Ima smisla."}, GROK_KID)
        self.assertFalse(err, d)
        self.assertEqual((d["verdict"], d["status"], d["decision"]), ("slazem", "stored", None))
        d, err = mcpapi._tool("submit_council_review", ok, GROK_KID)
        self.assertTrue(err)                                                    # one review per note
        self.assertIn("već ocijenio", d["error"])
        o = store.ocjene(self.con, nid)["grok"]
        self.assertEqual((o["verdict"], o["usd"]), ("slazem", 0.0))

    def test_groks_refinement_is_stored_and_applied(self):
        nid = self.note(cnotes.KID, pc={"key": "dca_token_cap", "to": 0.5})
        self.tick()
        d, err = mcpapi._tool("submit_council_review", {"note_id": nid, "verdict": "doradi", "critique": "0,3 je dosta.",
                                                        "refined_change": {"key": "dca_token_cap", "to": 0.3}}, GROK_KID)
        self.assertFalse(err, d)
        self.assertEqual(d["decision"], "prihvaceno_primijenjeno")
        self.assertEqual(settings.raw(self.con)["dca_token_cap"], 0.3)

    def test_get_council_shows_the_picture(self):
        a, b = self.note(pc={"key": "dca_token_cap", "to": 0.2}), self.note(cnotes.KID)
        self.tick()
        d, err = mcpapi._tool("get_council", {}, "local")
        self.assertFalse(err)
        self.assertEqual([q["note_id"] for q in d["queue"]], [b])
        self.assertEqual(d["queue"][0]["waits_for"], ["grok"])
        self.assertEqual(d["decisions"][0]["note_id"], a)
        self.assertEqual(d["decisions"][0]["decision"], "prihvaceno_primijenjeno")
        self.assertEqual(set(d["decisions"][0]["reviews"]), {"openai", "claude"})
        self.assertEqual(d["za_izvedbu"], [])
        self.assertEqual(d["today"]["ocjena"], 3)
        json.dumps(d)

    def test_the_task_queue_of_grok_carries_the_councils_work(self):
        from ui import kandidati
        nid = self.note(cnotes.KID)

        class Src(kandidati.Sources):
            def __init__(s):
                s.trade_db = self.db
        with mock.patch.object(kandidati, "_cached", return_value=([], {})):
            d = kandidati.tasks(20, self.now, Src())
        mine = [t for t in d["tasks"] if t["kind"] == "council_review"]
        self.assertEqual([t["note_id"] for t in mine], [nid])
        self.assertEqual(d["tasks"][0]["kind"], "council_review")              # first in the queue Grok reads first


class Off(Base):
    def test_vijece_0_does_nothing(self):
        nid = self.note(pc={"key": "dca_token_cap", "to": 0.2})
        self.con.execute("DELETE FROM settings WHERE k IN (?, ?)", (sjeme.ONCE_KEY, smjer.ONCE_KEY))
        self.con.commit()
        with mock.patch.dict(os.environ, {"VIJECE": "0"}):
            out = self.tick()
            self.assertEqual(out, {"skip": "isključeno"})
            self.assertEqual(self.lines, ["vijeće: isključeno (VIJECE=0), ništa ne radim"])
            self.assertEqual(vmcp.queue(), vmcp.OFF)
            self.assertEqual(vmcp.council(), vmcp.OFF)
            self.assertIn("error", vmcp.submit_review({"note_id": nid, "verdict": "slazem", "critique": "x"}, GROK_KID))
            self.assertEqual(vmcp.grok_tasks(self.con, self.now), [])
        self.assertEqual(self.openai.calls + self.claude.calls, [])
        self.assertEqual(self.con.execute("SELECT COUNT(*) FROM assistant_notes").fetchone()[0], 1)
        self.assertEqual(self.status(nid), "novo")
        self.assertEqual(self.con.execute("SELECT COUNT(*) FROM vijece_ocjene").fetchone()[0], 0)

    def test_the_run_script(self):
        import run_vijece
        with mock.patch.dict(os.environ, {"VIJECE": "0"}), mock.patch("ops.sentry.init"):
            self.assertEqual(run_vijece.main(["tick"]), 0)
            self.assertEqual(run_vijece.main(["stanje"]), 0)
        with open(os.path.join(ROOT, "start.sh"), encoding="utf-8") as f:
            sh = f.read()
        self.assertIn('low python3 run_vijece.py tick || echo "vijeće nije uspjelo"', sh)
        self.assertNotIn("ops.heavy run_vijece", sh)


class Page(Base):
    def test_the_line_under_a_note_is_escaped(self):
        from ui.html import esc
        nid = self.note(cnotes.KID, pc={"key": "dca_token_cap", "to": 0.2})
        self.claude.reviews[nid] = {**SLAZEM, "verdict": "doradi", "critique": "<script>alert(1)</script> \"x\""}
        self.tick()
        plain = self.note()
        self.con.execute("INSERT INTO assistant_notes (ts, kind, title, key_id) VALUES (?, 'suggestion', 'bez vijeća', 'x')", (1,))
        html = posao.ui_linije(self.con, [nid, plain, plain + 1], esc)
        self.assertEqual(set(html), {nid})                                     # only notes the council has reviewed
        self.assertIn("Vijeće: ", html[nid])
        self.assertIn("Claude ✎", html[nid])
        self.assertIn("Grok …", html[nid])
        self.assertNotIn("<script>", html[nid])
        self.assertIn("&lt;script&gt;", html[nid])
        self.tick(self.now + 7 * 3600)
        html = posao.ui_linije(self.con, [nid, plain], esc)
        self.assertIn("→ prihvaćeno i primijenjeno", html[nid])
        self.assertIn("OpenAI ✔", html[plain])
        self.assertIn("→ prihvaćeno za izvedbu", html[plain])

    def test_the_autopilot_list_shows_it(self):
        from ui import pravitrade
        nid = self.note(cnotes.KID, "Prijedlog kritičara")
        self.claude.reviews[nid] = PROTIV
        self.tick()
        page = str(pravitrade._suggest_section(self.con, True, "openai"))
        self.assertIn("Prijedlog kritičara", page)
        self.assertIn("Vijeće: ", page)
        self.assertIn("Claude ✘", page)

    def test_the_state_command_prints_the_queue_and_the_decisions(self):
        a, b = self.note(), self.note(cnotes.KID)
        self.tick()
        out = []
        posao.ispis(self.now, lambda *x, **k: out.append(" ".join(map(str, x))), self.con)
        txt = "\n".join(out)
        self.assertIn(f"red #{b}", txt)
        self.assertIn(f"odluka #{a}", txt)
        self.assertIn(f"za izvedbu #{a}", txt)


class States(unittest.TestCase):
    def test_the_two_state_sets_are_registered_and_the_drift_is_zero(self):
        self.assertEqual(set(registar.BY_KEY["council_review"].states), set(store.VERDIKTI))
        self.assertEqual(set(registar.BY_KEY["council_decision"].states), set(store.ODLUKE))
        self.assertEqual(provjera.drift(registar.MACHINES), [])
        r = subprocess.run([sys.executable, "-m", "stanja"], cwd=ROOT, capture_output=True, text=True, timeout=120)
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertIn("odstupanja 0", r.stdout)

    def test_the_rule_is_in_the_rules_file(self):
        with open(os.path.join(ROOT, "CLAUDE.md"), encoding="utf-8") as f:
            txt = f.read()
        self.assertIn("- Vijeće (18.11.", txt)
        self.assertIn("0,60 $", txt)


if __name__ == "__main__":
    unittest.main()
