"""Kritičar (OpenAI), 15.11. (vlasnik: "OpenAI kao kritičar algoritma ... otvorenih tradeova, analiza"): critic/.

Offline: the OpenAI HTTP call is replaced (critic.openai_api._urlopen), nothing reaches the network. Covers the
budget caps, no key, the owner switch, the change detection, the answer's validation, the notes (kind, key, the
card's line, Grok's lists without them), the measurement 30 / 60 min after and at the close, the privacy of the
outgoing payload, the daily review, prices, the schedule, the morning e-mail, the cost line and the MCP tool.

    python3 -m unittest tests.test_kriticar_offline
"""
import io
import json
import os
import sqlite3
import sys
import tempfile
import time
import unittest
import urllib.error
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from critic import daily as cdaily  # noqa: E402
from critic import deep as deep_mod  # noqa: E402
from critic import live as live_mod  # noqa: E402
from critic import notes as cnotes  # noqa: E402
from critic import openai_api, privacy, prompts  # noqa: E402
from critic import store as cstore  # noqa: E402
from critic import trades as ctrades  # noqa: E402
from trade import executor, settings  # noqa: E402
from ui import assistnotes  # noqa: E402

NOW = 1_763_200_000          # 15.11.2025 09:46 UTC: any fixed time works, all clocks are passed in
MINT = "7GCihgDB8fe6KNjn2MYtkzZcRjQy3t9GHdC8uHYmW2hr"
MINT2 = "HhJpBhRRn4g56VsyLuT8DL5Bv31HkXqsrahTTUCZeQb3"
WALLET = "9WzDXwBbmkg8ZTbNMqUxvQRAyrZzDsGYdLVL9zYtAWWM"      # a followed wallet in a position's source text
OWNER_W = "4Nd1mBQtrMJVYVfKf2PJy9NZUZdTAsp7D4xWLs4gDB4T"    # the owner's wallet (settings wallet_pub)
SECRET = "sk-test-0123456789abcdefSECRET"
PRIV = "5KQwrPbwdL6PhXujxW37FSSQZ1JiwsST4cqQzDeyXtP79zkvFD3"


class FakeHTTP:
    """Stands in for urllib: records every request, answers from a queue (a dict = 200 JSON, an int = that HTTP error)."""
    def __init__(self, answers):
        self.answers, self.calls = list(answers), []

    def __call__(self, req, timeout):
        self.calls.append({"url": req.full_url, "headers": dict(req.headers), "body": json.loads(req.data)})
        a = self.answers.pop(0) if self.answers else 500
        if isinstance(a, int):
            raise urllib.error.HTTPError(req.full_url, a, "err", {}, io.BytesIO(b'{"error":{"message":"boom"}}'))
        body = json.dumps(a).encode()

        class R:
            def __enter__(self):
                return self

            def __exit__(self, *x):
                return False

            def read(self):
                return body
        return R()


def answer(obj, tin=4000, tout=2000, cached=0, status="completed", text=None, model="gpt-6-astra"):
    return {"id": "resp_1", "model": model, "status": status,
            "output": [{"type": "reasoning", "summary": []},
                       {"type": "message", "content": [{"type": "output_text",
                                                        "text": text if text is not None else json.dumps(obj)}]}],
            "usage": {"input_tokens": tin, "input_tokens_details": {"cached_tokens": cached}, "output_tokens": tout,
                      "output_tokens_details": {"reasoning_tokens": tout // 2}}}


def verdicts(*items, opce="portfelj je mali"):
    return {"pozicije": [{"id": pid, "verdict": v, "confidence": c, "razlozi": ["PnL +12 %, likvidnost pala 35 %"],
                          "promijenilo_bi": "rast likvidnosti", "predlozeni_sl_mc": 80000.0, "predlozeni_tp_mc": None}
                         for pid, v, c in items], "opce": opce}


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = os.path.join(self.tmp.name, "trade.db")
        self._db = settings.DB
        settings.DB = self.db
        settings._FLAG_CACHE.clear()
        self._env = {k: os.environ.get(k) for k in ("OPENAI_API_KEY", "SOLANA_PRIVATE_KEY", "HELIUS_API_KEY",
                                                     "SOLANA_PUBLIC_KEY", "RENDER_EXTERNAL_HOSTNAME", "OPENAI_PRICES")}
        for k in self._env:
            os.environ.pop(k, None)
        os.environ["SOLANA_PRIVATE_KEY"] = PRIV
        os.environ["HELIUS_API_KEY"] = "helius-secret-key-42"
        os.environ["RENDER_EXTERNAL_HOSTNAME"] = "memesonar-worker.onrender.com"
        self.con = executor.connect(self.db)
        cstore.ensure(self.con)
        assistnotes.ensure(self.con)
        self.logs = []
        self.log = lambda *a, **k: self.logs.append(" ".join(str(x) for x in a))
        self._sleep = mock.patch.object(openai_api.time, "sleep", lambda s: None)
        self._sleep.start()
        self._day = mock.patch.object(cstore, "DAY_USD", 100.0)   # the budget's own tests set it back to 1.00
        self._day.start()

    def tearDown(self):
        self._day.stop()
        self._sleep.stop()
        self.con.close()
        settings.DB = self._db
        settings._FLAG_CACHE.clear()
        for k, v in self._env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        self.tmp.cleanup()

    def key(self):
        os.environ["OPENAI_API_KEY"] = SECRET

    def add_pos(self, token=MINT, mode="live", reason="copy wallet " + WALLET, ts=NOW - 1200, status="open"):
        cur = self.con.execute("INSERT INTO positions (token, symbol, opened_ts, mode, status, reason, sol_in, qty_raw, "
                               "qty_left, sol_back) VALUES (?,?,?,?,?,?,?,?,?,?)",
                               (token, "TOK" if token == MINT else "TWO", ts, mode, status, reason, 0.1, 1000, 1000, 0))
        self.con.commit()
        return cur.lastrowid

    def pos(self, pid, token=MINT, mode="live", pnl=12.0, avg=100_000.0):
        mc = avg * (1 + pnl / 100)
        return {"pid": pid, "ids": [pid], "token": token, "sym": "TOK" if token == MINT else "TWO", "mode": mode,
                "paper": mode != "live", "avg_mc": avg, "mc_now": mc, "pnl_pct": pnl, "opened_ts": NOW - 1200,
                "sol_in": 0.1, "held": 1.0, "n_lots": 1, "lots": [[0.1, 1.0, avg, 0.0]], "tp_pct": None, "tp_mc": None,
                "sl_pct": -60, "sl_mc": avg * 0.4, "trail": None, "exit": "SL -60 %", "plan": None,
                "by": {"kind": "program", "what": "kopiranje", "tag": "program · kopiranje " + WALLET},
                "src": "auto", "grok": None}

    def positions_fn(self, plist, sol=150.0):
        live = {p["token"]: {"price": p["mc_now"] / 1e9, "liq": 30_000.0, "mcap": p["mc_now"],
                             "w": {"m5": {"ch": -2.0, "vol": 1200.0, "buys": 10, "sells": 14},
                                   "h1": {"ch": 8.0, "vol": 9000.0, "buys": 80, "sells": 70}}} for p in plist}
        return lambda tcon, now: (plist, live, sol)

    def run_trades(self, plist, answers, now=NOW, **kw):
        http = FakeHTTP(answers)
        with mock.patch.object(openai_api, "_urlopen", http):
            res = ctrades.run(now, log=self.log, tcon=self.con, positions_fn=self.positions_fn(plist),
                              live_fn=lambda toks: {}, series_fn=lambda tok, ts, now_: ([], []), **kw)
        return res, http


class Switch(Base):
    def test_default_on_and_in_the_owner_switches(self):
        self.assertEqual(settings.flag("openai_kritika", con=self.con), "live")
        self.assertIn("openai_kritika", settings.OWNER_SWITCHES)
        self.assertTrue(ctrades.enabled(self.con))
        from ui import apterm
        html = apterm.owner_switches_html(self.con, True)
        self.assertIn("openai_kritika", html)
        self.assertIn("Kritičar (OpenAI)", html)

    def test_flag_off_no_call(self):
        self.key()
        settings.set_flag(self.con, "openai_kritika", "off", "jure")
        pid = self.add_pos()
        res, http = self.run_trades([self.pos(pid)], [answer(verdicts((pid, "drzi", 0.7)))])
        self.assertEqual(res["skip"], "isključen")
        self.assertEqual(http.calls, [])
        with mock.patch.object(openai_api, "_urlopen", FakeHTTP([])) as h:
            self.assertEqual(cdaily.run(NOW, log=self.log, tcon=self.con, payload_fn=lambda c, n: {})["skip"], "isključen")
            self.assertEqual(h.calls, [])

    def test_no_key_one_line_an_hour_and_no_call(self):
        pid = self.add_pos()
        for t in (NOW, NOW + 300, NOW + 3700):
            res, http = self.run_trades([self.pos(pid)], [answer(verdicts((pid, "drzi", 0.7)))], now=t)
            self.assertEqual(res["skip"], "nema ključa")
            self.assertEqual(http.calls, [])
        self.assertEqual(self.logs, ["kritičar: nema OPENAI_API_KEY, preskačem"] * 2)


class OpenTrades(Base):
    def test_one_batched_call_verdicts_notes_and_the_card_line(self):
        self.key()
        p1, p2 = self.add_pos(), self.add_pos(MINT2, mode="dry", reason="momentum skok")
        res, http = self.run_trades([self.pos(p1), self.pos(p2, MINT2, "dry", pnl=-8)],
                                    [answer(verdicts((p1, "prodaj", 0.8), (p2, "drzi", 0.55)))])
        self.assertEqual(len(http.calls), 1)
        b = http.calls[0]["body"]
        self.assertEqual(http.calls[0]["url"], "https://api.openai.com/v1/responses")
        self.assertEqual(b["model"], "gpt-6-astra")
        self.assertEqual(b["reasoning"], {"effort": "low"})
        self.assertIs(b["store"], False)
        self.assertEqual(b["text"]["format"]["type"], "json_schema")
        self.assertTrue(b["text"]["format"]["strict"])
        self.assertEqual(b["instructions"], prompts.SYSTEM)
        self.assertTrue(b["input"].startswith(prompts.OPEN_TRADES))
        data = json.loads(b["input"].split("Podaci (JSON):\n", 1)[1])
        self.assertEqual([x["id"] for x in data["pozicije"]], [p1, p2])
        x = data["pozicije"][0]
        self.assertEqual((x["novac"], x["strategija"], x["ulaz_mc"], x["sada_mc"]), ("pravi", "kopiranje", 100000, 112000))
        self.assertLess(x["pnl_nakon_fija_pct"], x["pnl_bruto_pct"])
        self.assertEqual(x["protok"]["m5"]["prodaje"], 14)
        self.assertEqual(res["presude"], {"prodaj": 1, "drzi": 1})
        # cost: 4000 in x 10 + 2000 out x 50 per 1M (gpt-6-astra)
        row = self.con.execute("SELECT kind, model, tokens_in, tokens_out, cost_usd, ok, phash FROM critic_calls").fetchone()
        self.assertEqual(row[:4], ("trades", "gpt-6-astra", 4000, 2000))
        self.assertAlmostEqual(row[4], 0.14, places=6)
        self.assertEqual((row[5], len(row[6])), (1, 12))
        v = self.con.execute("SELECT pid, verdict, confidence, pnl_pct, mc0, value_usd FROM critic_verdicts ORDER BY id").fetchall()
        self.assertEqual(v[0][:3], (p1, "prodaj", 0.8))
        self.assertAlmostEqual(v[0][5], 0.1 * 1.12 * 150, places=2)
        notes = self.con.execute("SELECT kind, position_id, verdict, key_id, interpretation, evidence FROM assistant_notes "
                                 "ORDER BY id").fetchall()
        self.assertEqual([(n[0], n[1], n[2], n[3]) for n in notes],
                         [("trade_review", p1, "loš", cnotes.KID), ("trade_review", p2, "neutralan", cnotes.KID)])
        self.assertTrue(notes[0][4].startswith("PRODAJ · PnL +12 %"))
        self.assertEqual(json.loads(notes[0][5])["verdict"], "prodaj")
        # Grok's lists leave the critic out, the critic's own reader has it, the card shows its line
        self.assertEqual(assistnotes.latest_for(self.con, [p1, p2], [MINT, MINT2]), {})
        self.assertEqual(assistnotes.reviewed_positions(self.con), set())
        crit = assistnotes.latest_critic(self.con, [p1, p2])
        from ui import apterm
        html = apterm._critic_html(apterm._critic_slim(crit[p1]), NOW + 60)
        self.assertIn("Kritičar (OpenAI): prodaj · sigurnost 80 %", html)
        self.assertIn("PnL +12 %", html)
        self.assertNotIn("PRODAJ", html)
        self.assertTrue(any(line.startswith("kritičar: 2 pozicija") and "trošak 0.1400 $" in line for line in self.logs))

    def test_drzi_in_plus_maps_to_dobar(self):
        self.assertEqual(cnotes.review_verdict("drzi", 5), "dobar")
        self.assertEqual(cnotes.review_verdict("drzi", -5), "neutralan")
        self.assertEqual(cnotes.review_verdict("prodaj_dio", 5), "loš")
        self.assertEqual(cnotes.review_verdict("stegni_sl", 5), "neutralan")
        self.assertEqual(cnotes.review_verdict("prosiri_sl", -5), "neutralan")

    def test_change_detection(self):
        self.key()
        pid = self.add_pos()
        ok = answer(verdicts((pid, "drzi", 0.7)))
        self.run_trades([self.pos(pid, pnl=12)], [ok])
        res, http = self.run_trades([self.pos(pid, pnl=15)], [ok], now=NOW + 300)
        self.assertEqual((res["skip"], http.calls), ("ništa se nije promijenilo", []))
        res, http = self.run_trades([self.pos(pid, pnl=23)], [ok], now=NOW + 600)     # PnL +11 points
        self.assertEqual(len(http.calls), 1)
        res, http = self.run_trades([self.pos(pid, pnl=24)], [ok], now=NOW + 600 + 14 * 60)
        self.assertEqual(http.calls, [])
        res, http = self.run_trades([self.pos(pid, pnl=24)], [ok], now=NOW + 600 + 15 * 60)   # real money: 15 min
        self.assertEqual(len(http.calls), 1)
        # paper only: 30 min
        self.assertEqual(ctrades.due([self.pos(pid, mode="dry")], {pid: (NOW, 12.0, "drzi")}, NOW + 16 * 60)[0], False)
        self.assertEqual(ctrades.due([self.pos(pid, mode="dry")], {pid: (NOW, 12.0, "drzi")}, NOW + 30 * 60)[0], True)
        # a new position always
        self.assertEqual(ctrades.due([self.pos(pid + 1)], {pid: (NOW, 12.0, "drzi")}, NOW + 60)[0], True)
        # no open positions: no call
        self.con.execute("UPDATE positions SET status='closed'")
        self.con.commit()
        res, http = self.run_trades([], [ok], now=NOW + 7200)
        self.assertEqual((res["skip"], http.calls), ("nema otvorenih pozicija", []))

    def test_same_verdict_note_only_once_an_hour(self):
        self.key()
        pid = self.add_pos()
        ok = answer(verdicts((pid, "drzi", 0.7)))
        self.run_trades([self.pos(pid)], [ok])
        self.run_trades([self.pos(pid)], [ok], now=NOW + 1000, force=True)
        self.assertEqual(self.con.execute("SELECT COUNT(*) FROM critic_verdicts").fetchone()[0], 2)
        self.assertEqual(self.con.execute("SELECT COUNT(*) FROM assistant_notes").fetchone()[0], 1)
        self.run_trades([self.pos(pid)], [answer(verdicts((pid, "prodaj", 0.7)))], now=NOW + 1100, force=True)
        self.assertEqual(self.con.execute("SELECT COUNT(*) FROM assistant_notes").fetchone()[0], 2)


class Validation(Base):
    def test_invalid_answers_are_booked_and_paused(self):
        self.key()
        pid = self.add_pos()
        bad = {"pozicije": [{"id": pid, "verdict": "kupi_jos", "confidence": 0.7, "razlozi": ["x"], "promijenilo_bi": "",
                             "predlozeni_sl_mc": None, "predlozeni_tp_mc": None},
                            {"id": pid, "verdict": "drzi", "confidence": 1.5, "razlozi": ["x"], "promijenilo_bi": "",
                             "predlozeni_sl_mc": None, "predlozeni_tp_mc": None},
                            {"id": 999, "verdict": "drzi", "confidence": 0.5, "razlozi": ["x"], "promijenilo_bi": "",
                             "predlozeni_sl_mc": None, "predlozeni_tp_mc": None}], "opce": None}
        res, http = self.run_trades([self.pos(pid)], [answer(bad)])
        self.assertEqual(res["skip"], "neispravan odgovor")
        r = self.con.execute("SELECT ok, cost_usd, error FROM critic_calls").fetchone()
        self.assertEqual(r[0], 0)
        self.assertGreater(r[1], 0)                      # a bad answer still costs: booked
        self.assertIn("neispravan odgovor", r[2])
        self.assertEqual(self.con.execute("SELECT COUNT(*) FROM critic_verdicts").fetchone()[0], 0)
        res, http = self.run_trades([self.pos(pid)], [answer(verdicts((pid, "drzi", 0.7)))], now=NOW + 300)
        self.assertEqual((res["skip"], http.calls), ("pauza nakon neuspjelog poziva", []))
        res, http = self.run_trades([self.pos(pid)], [answer(verdicts((pid, "drzi", 0.7)))], now=NOW + 700)
        self.assertEqual(res["presude"], {"drzi": 1})

    def test_not_json_incomplete_refused_and_http_errors(self):
        self.key()
        pid = self.add_pos()
        res, _ = self.run_trades([self.pos(pid)], [answer(None, text="nije json")])
        self.assertEqual(res["skip"], "greška API-ja")
        self.assertIn("nije valjan JSON", res["greska"])
        res, _ = self.run_trades([self.pos(pid)], [answer(verdicts((pid, "drzi", 0.7)), status="incomplete")],
                                 now=NOW + 700)
        self.assertIn("nije dovršen", res["greska"])
        res, http = self.run_trades([self.pos(pid)], [500, 503], now=NOW + 1400)     # 5xx: one retry, then give up
        self.assertEqual((res["skip"], len(http.calls)), ("greška API-ja", 2))
        res, http = self.run_trades([self.pos(pid)], [400], now=NOW + 2100)          # 4xx: no retry
        self.assertEqual(len(http.calls), 1)
        self.assertNotIn(SECRET, res["greska"])
        res, http = self.run_trades([self.pos(pid)], [429, answer(verdicts((pid, "drzi", 0.7)))], now=NOW + 2800)
        self.assertEqual((len(http.calls), res["presude"]), (2, {"drzi": 1}))
        rows = self.con.execute("SELECT ok, cost_usd FROM critic_calls ORDER BY id").fetchall()
        self.assertEqual([r[0] for r in rows], [0, 0, 0, 0, 1])
        self.assertGreater(rows[0][1], 0)   # the non-JSON answer came with usage: its cost is booked
        self.assertEqual(rows[2][1], 0)     # an HTTP error costs nothing

    def test_daily_validation(self):
        with self.assertRaises(ValueError):
            cdaily.validate({"sazetak": "", "strategije": [], "nalazi": [], "nedostaje_mjerenje": []})
        s, st, nal, ned = cdaily.validate({"sazetak": "ok", "strategije": [{"ime": "range", "presuda": "ugasi", "razlog": "n=4"},
                                                                         {"ime": "x", "presuda": "kupi", "razlog": ""}],
                                           "nalazi": [{"naslov": f"n{i}", "ozbiljnost": "visoka", "dokaz": "n=12",
                                                       "prijedlog": "p", "kako_provjeriti": "k"} for i in range(9)]
                                           + [{"naslov": "bez", "ozbiljnost": "hitno", "dokaz": "d", "prijedlog": "",
                                               "kako_provjeriti": ""}],
                                           "nedostaje_mjerenje": ["holderi"]})
        self.assertEqual(([x["ime"] for x in st], len(nal), ned), (["range"], 7, ["holderi"]))


class Budget(Base):
    def setUp(self):
        super().setUp()
        self._day.stop()
        self._day = mock.patch.object(cstore, "DAY_USD", 1.0)
        self._day.start()

    def book(self, usd, kind="trades", ts=NOW - 60):
        cstore.book(self.con, kind, "gpt-6-astra", {"in": 1, "out": 1}, usd, True, now=ts)

    def test_day_cap_stops_calls_and_logs_once(self):
        self.key()
        pid = self.add_pos()
        self.book(0.995, kind="live")
        for t in (NOW, NOW + 900):
            res, http = self.run_trades([self.pos(pid)], [answer(verdicts((pid, "drzi", 0.7)))], now=t)
            self.assertEqual((res["skip"], http.calls), ("budžet", []))
        self.assertEqual(sum(1 for x in self.logs if "dnevni strop" in x), 1)

    def test_reserves_in_the_owners_order(self):
        # 1.00 a day: a re-check leaves 0.15 for live comments and 0.55 for the review until it ran
        self.book(0.29)
        self.assertIsNotNone(cstore.refusal(self.con, "trades", 0.02, NOW, self.log))
        self.assertIsNone(cstore.refusal(self.con, "daily", 0.50, NOW, self.log))
        self.assertIsNotNone(cstore.refusal(self.con, "daily", 0.60, NOW, self.log))   # leaves 0.15 for live
        self.assertIsNone(cstore.refusal(self.con, "live", 0.70, NOW, self.log))
        self.book(0.10, kind="daily")
        self.assertIsNone(cstore.refusal(self.con, "trades", 0.02, NOW, self.log))
        self.assertIsNotNone(cstore.refusal(self.con, "trades", 0.5, NOW, self.log))
        self.assertIsNone(cstore.refusal(self.con, "trades", 0.02, NOW + 86400, self.log))   # a new UTC day
        self.assertIsNone(cstore.refusal(self.con, "deep", 1.9, NOW, self.log))   # outside the day's cap

    def test_cheap_model_after_70_percent_and_when_the_strong_one_does_not_fit(self):
        m, _ = cstore.pick(self.con, "trades", "gpt-6-astra", 12_000, 4000, NOW, self.log)
        self.assertEqual(m, "gpt-6-astra")
        self.book(0.10, kind="daily")   # today's review ran: its reserve is free
        self.book(0.61, kind="live")
        for kind in ("trades", "live"):
            self.assertEqual(cstore.pick(self.con, kind, "gpt-6-astra", 12_000, 4000, NOW, self.log)[0], "gpt-5.4-mini")
        # the daily review keeps the strong model while it fits, the cheap one when it does not
        self.assertEqual(cstore.pick(self.con, "daily", "gpt-6-astra", 3_000, 1000, NOW, self.log)[0], "gpt-6-astra")
        self.assertEqual(cstore.pick(self.con, "daily", "gpt-6-astra", 40_000, 8000, NOW, self.log)[0], "gpt-5.4-mini")
        self.book(0.29, kind="live")
        self.assertEqual(cstore.pick(self.con, "trades", "gpt-6-astra", 12_000, 4000, NOW, self.log)[0], None)

    def test_month_cap_covers_everything_in_priority(self):
        self.assertIn("strop dubinske sesije", cstore.refusal(self.con, "deep", 2.5, NOW, self.log))
        self.book(35.5, kind="deep", ts=cstore.month_start(NOW) + 10)
        self.assertIn("mjesečni strop", cstore.refusal(self.con, "trades", 0.02, NOW, self.log))   # keeps 5 $
        self.assertIsNone(cstore.refusal(self.con, "daily", 0.5, NOW, self.log))                   # keeps 3 $
        self.assertIsNone(cstore.refusal(self.con, "deep", 1.9, NOW, self.log))                    # keeps 1 $
        self.assertIsNone(cstore.refusal(self.con, "live", 0.5, NOW, self.log))
        self.book(3.0, kind="deep", ts=cstore.month_start(NOW) + 20)
        self.assertIn("mjesečni strop", cstore.refusal(self.con, "deep", 0.6, NOW, self.log))
        self.assertIsNone(cstore.refusal(self.con, "live", 0.5, NOW, self.log))

    def test_estimate_counts_every_output_token(self):
        est = openai_api.max_cost("gpt-5-mini", 30_000, 6000)
        self.assertAlmostEqual(est, (10_000 * 0.25 + 6000 * 2.0) / 1e6)


class Measurement(Base):
    def verdict(self, pid, verdict, mc0=100_000.0, value=15.0, ts=NOW):
        pos = {"pid": pid, "token": MINT, "sym": "TOK", "mode": "live", "strategy": "kopiranje", "pnl_pct": 5.0,
               "mc_now": mc0, "value_usd": value}
        cstore.add_verdict(self.con, 1, None, pos, {"verdict": verdict, "confidence": 0.7}, now=ts)
        self.con.commit()

    def test_30_60_min_and_close_against_the_bot(self):
        pid = self.add_pos()
        self.verdict(pid, "prodaj")
        self.verdict(pid, "drzi")
        stored = {NOW + 1800: 80_000.0, NOW + 3600: 70_000.0}
        fn = lambda tok, ts: stored.get(ts)   # noqa: E731
        self.assertEqual(cstore.evaluate(self.con, NOW + 1000, mc_at_fn=fn), 0)          # nothing due yet
        self.assertEqual(cstore.evaluate(self.con, NOW + 1900, mc_at_fn=fn), 2)
        r = self.con.execute("SELECT mc30, mc60, done FROM critic_verdicts ORDER BY id").fetchall()
        self.assertEqual(r, [(80_000.0, None, 0), (80_000.0, None, 0)])
        cstore.evaluate(self.con, NOW + 3700, mc_at_fn=fn)
        s = cstore.stats(self.con, 7, NOW + 3700)
        p, d = s["presude"]["prodaj"], s["presude"]["drzi"]
        self.assertEqual((p["pogodak_30"], p["pogodak_60"], d["pogodak_60"]), (1.0, 1.0, 0.0))
        # prodaj at 100k, the bot held to 70k: the advice saved 30 % of $15
        self.assertAlmostEqual(p["usd_60min"], 4.5)
        self.assertAlmostEqual(d["usd_60min"], 0.0)        # drzi = what the bot did
        # the position closes at 60k: the close point, the rows are done
        self.con.execute("UPDATE positions SET status='closed', closed_ts=?", (NOW + 4000,))
        self.con.commit()
        stored[NOW + 4000] = 60_000.0
        cstore.evaluate(self.con, NOW + 4100, mc_at_fn=fn)
        r = self.con.execute("SELECT mc_close, closed_ts, done FROM critic_verdicts ORDER BY id").fetchall()
        self.assertEqual(r, [(60_000.0, NOW + 4000, 1)] * 2)
        s = cstore.stats(self.con, 7, NOW + 4100)
        self.assertEqual(s["presude"]["prodaj"]["pogodak_zatvaranje"], 1.0)
        self.assertAlmostEqual(s["presude"]["prodaj"]["usd_zatvaranje"], 6.0)   # -(-40 %) x $15
        self.assertIn("prodaj 1 (pogodak 60 min 100 %)", cstore.stats_line(s))

    def test_live_price_once_when_nothing_stored_and_given_up_late(self):
        pid = self.add_pos()
        self.verdict(pid, "prodaj_dio")
        asked = []

        def live_fn(toks):
            asked.append(list(toks))
            return {MINT: 120_000.0}
        cstore.evaluate(self.con, NOW + 1850, mc_at_fn=lambda t, ts: None, live_fn=live_fn)
        self.assertEqual(asked, [[MINT]])
        self.assertEqual(self.con.execute("SELECT mc30 FROM critic_verdicts").fetchone()[0], 120_000.0)
        cstore.evaluate(self.con, NOW + 3600 + cstore.EVAL_LATE_S + 60, mc_at_fn=lambda t, ts: None, live_fn=live_fn)
        self.assertEqual(self.con.execute("SELECT mc60 FROM critic_verdicts").fetchone()[0], 0.0)
        hit, delta = cstore.score("prodaj_dio", 100_000, 120_000)
        self.assertEqual(hit, False)
        self.assertAlmostEqual(delta, -0.1)   # half sold at 100k, the bot held all to +20 %: 10 % less

    def test_mc_at_nearest_stored_snapshot(self):
        snaps = [{"ts": NOW - 400, "mcap": 1.0}, {"ts": NOW + 100, "mcap": 2.0}, {"ts": NOW + 250, "mcap": 3.0}]
        self.assertEqual(cstore.mc_at(MINT, NOW, snaps), 2.0)
        self.assertIsNone(cstore.mc_at(MINT, NOW + 2000, snaps))


class Privacy(Base):
    def test_no_secret_env_name_wallet_or_host_leaves(self):
        self.key()
        settings.put(self.con, "wallet_pub", OWNER_W)
        pid = self.add_pos()
        p = self.pos(pid)
        p["by"]["tag"] = f"program · {OWNER_W} OPENAI_API_KEY {SECRET} /var/data/trade.db run_trade.py"
        res, http = self.run_trades([p], [answer(verdicts((pid, "drzi", 0.7)))])
        self.assertEqual(res["presude"], {"drzi": 1})
        body = json.dumps(http.calls[0]["body"], ensure_ascii=False)
        for bad in (SECRET, PRIV, "helius-secret-key-42", "OPENAI_API_KEY", "SOLANA_PRIVATE_KEY", "HELIUS_API_KEY",
                    WALLET, OWNER_W, "onrender.com", "/var/data", "trade.db", "run_trade.py"):
            self.assertNotIn(bad, body, bad)
        self.assertIn('"simbol":"TOK"', body.replace("\\", ""))   # the symbol is public
        self.assertEqual(http.calls[0]["headers"]["Authorization"], f"Bearer {SECRET}")   # only in the header

    def test_scrub_and_leaks(self):
        env = {"MY_API_KEY": "abcdef123456", "PATH": "/usr/bin"}
        t = f"x abcdef123456 MY_API_KEY {WALLET} {MINT} a.onrender.com /var/data/x.db"
        s = privacy.scrub(t, {MINT}, env=env)
        self.assertEqual(privacy.leaks(s, {MINT}, env=env), [])
        self.assertIn(MINT, s)
        self.assertEqual(set(privacy.leaks(t, {MINT}, env=env)), {"tajna vrijednost", "ime varijable okoline", "adresa", "host"})

    def test_daily_payload_is_scrubbed_too(self):
        self.key()
        ans = {"sazetak": "Edge nije dokazan (n=12).", "strategije": [], "nalazi": [], "nedostaje_mjerenje": []}
        http = FakeHTTP([answer(ans)])
        with mock.patch.object(openai_api, "_urlopen", http):
            cdaily.run(NOW, log=self.log, tcon=self.con,
                       payload_fn=lambda c, n: {"izvjestaji": {"top": [WALLET, MINT2], "env": "HELIUS_API_KEY",
                                                               "k": "helius-secret-key-42"}})
        body = json.dumps(http.calls[0]["body"], ensure_ascii=False)
        for bad in (WALLET, MINT2, "HELIUS_API_KEY", "helius-secret-key-42"):
            self.assertNotIn(bad, body)


class Daily(Base):
    ANS = {"sazetak": "Edge nije dokazan: range n=14, EV +1,2 % s intervalom -3 do +5 %.",
           "strategije": [{"ime": "range_dca", "presuda": "nedovoljno_podataka", "razlog": "n=14"}],
           "nalazi": [{"naslov": "Mali uzorak range", "ozbiljnost": "visoka", "dokaz": "n=14, lo90 -3 %",
                       "prijedlog": "zadrži u demu do n=50", "kako_provjeriti": "EV lo90 > 0 na 50 rundi"},
                      {"naslov": "Trošak X bez odluke", "ozbiljnost": "srednja", "dokaz": "6 $ tjedno, 0 tradeova",
                       "prijedlog": "smanji strop", "kako_provjeriti": "7 dana"}],
           "nedostaje_mjerenje": ["slippage pravih izlaza"]}

    def test_findings_and_summary_stored_once_a_day(self):
        self.key()
        http = FakeHTTP([answer(self.ANS, tin=12_000, tout=6000)])
        with mock.patch.object(openai_api, "_urlopen", http):
            res = cdaily.run(NOW, log=self.log, tcon=self.con, payload_fn=lambda c, n: {"strategije_30d": {}})
            again = cdaily.run(NOW + 3600, log=self.log, tcon=self.con, payload_fn=lambda c, n: {})
        self.assertEqual(res["nalaza"], 2)
        self.assertEqual(again["skip"], "danas već napravljen")
        self.assertEqual(len(http.calls), 1)
        b = http.calls[0]["body"]
        self.assertEqual((b["model"], b["reasoning"]), ("gpt-6-astra", {"effort": "medium"}))
        self.assertTrue(b["input"].startswith(prompts.DAILY))
        rows = self.con.execute("SELECT kind, title, key_id, proposed_change, status FROM assistant_notes ORDER BY id").fetchall()
        self.assertEqual([r[0] for r in rows], ["suggestion", "suggestion", "daily_summary"])
        self.assertEqual(rows[0][1], "Kritičar: Mali uzorak range")
        self.assertTrue(all(r[2] == cnotes.KID and r[3] is None and r[4] == "novo" for r in rows))
        self.assertTrue(rows[2][1].startswith("Kritičar (OpenAI): dnevni pregled"))
        c = self.con.execute("SELECT kind, cost_usd FROM critic_calls").fetchone()
        self.assertEqual(c[0], "daily")
        self.assertAlmostEqual(c[1], (12_000 * 10 + 6000 * 50) / 1e6)   # gpt-6-astra
        self.assertTrue(any(x.startswith("kritičar: dnevni pregled spremljen, 2 nalaza") for x in self.logs))
        # the owner rejects one: the next review gets its title in "odbijeni_prijedlozi"
        nid = self.con.execute("SELECT id FROM assistant_notes WHERE title='Kritičar: Trošak X bez odluke'").fetchone()[0]
        assistnotes.decide(self.con, nid, "odbijeno")
        self.assertEqual(cnotes.rejected_titles(self.con, now=NOW + 60), ["Trošak X bez odluke"])
        self.assertEqual(cstore.stats(self.con, 7, NOW + 60)["prijedlozi"], {"novo": 1, "odbijeno": 1})

    def test_build_payload_reads_what_exists(self):
        p = cdaily.build_payload(self.con, NOW)
        for k in ("strategije_30d", "pravila_i_stropovi", "promjene_postavki_7d", "makro", "trosak_podataka_7d",
                  "izvjestaji", "kriticar_sam_7d", "odbijeni_prijedlozi"):
            self.assertIn(k, p)
        self.assertEqual(p["pravila_i_stropovi"]["stropovi_pravog_novca"]["size_sol"], 0.1)
        json.dumps(p, default=str)

    def test_strategy_stats_real_money(self):
        for i, back in enumerate((0.12, 0.08, 0.15)):
            self.con.execute("INSERT INTO positions (token, opened_ts, mode, status, reason, sol_in, sol_back, closed_ts, "
                             "fees_sol) VALUES (?,?,?,?,?,?,?,?,?)",
                             (MINT, NOW - 9000 + i, "live", "closed", "momentum skok", 0.1, back, NOW - 8000 + i, 0.0))
        self.con.commit()
        from critic import data as cdata
        s = cdata.strategy_stats(self.con, NOW, detail=False)["momentum_scalp"]["pravi_novac"]
        self.assertEqual((s["n"], s["pogodak"]), (3, 0.667))
        self.assertAlmostEqual(s["ev_pct"], 16.67, places=1)
        full = cdata.summary([0.2, -0.1, 0.05, -0.3])
        self.assertEqual((full["max_dd_pp"], full["profit_factor"]), (35.0, 0.62))


class Prices(unittest.TestCase):
    def test_prices_by_prefix_unknown_high_and_override(self):
        self.assertEqual(openai_api.price("gpt-5-mini-2025-08-07"), openai_api.PRICES["gpt-5-mini"])
        self.assertEqual(openai_api.price("gpt-5.4-mini"), openai_api.PRICES["gpt-5.4-mini"])
        self.assertEqual(openai_api.price("gpt-5.4"), (2.50, 0.25, 15.00))
        self.assertEqual(openai_api.price("gpt-6-astra"), (10.00, 1.00, 50.00))
        self.assertEqual((openai_api.MODEL, openai_api.MODEL_LIVE, openai_api.MODEL_DEEP, openai_api.MODEL_CHEAP),
                         ("gpt-6-astra", "gpt-6-astra", "gpt-6-astra", "gpt-5.4-mini"))
        self.assertEqual(openai_api.price("neki-novi-model"), openai_api.UNKNOWN_PRICE)
        self.assertAlmostEqual(openai_api.cost("gpt-5-mini", {"in": 1000, "cached": 400, "out": 100}),
                               (600 * 0.25 + 400 * 0.025 + 100 * 2.0) / 1e6)
        with mock.patch.dict(os.environ, {"OPENAI_PRICES": '{"neki-novi-model": [1, 0.1, 4]}'}):
            self.assertEqual(openai_api.price("neki-novi-model"), (1.0, 0.1, 4.0))
        self.assertNotIn("reasoning", openai_api.body("gpt-4.1-mini", "s", "u", {}, "n", 10, "low"))
        self.assertEqual(openai_api.body("gpt-5-mini", "s", "u", {}, "n", 10, "low")["reasoning"], {"effort": "low"})


class Wiring(Base):
    def test_schedule_cpuguard_and_daily_after_a_start(self):
        import run_sched
        from ops import cpuguard
        jobs = {name: (fn.__name__, args) for name, fn, args in run_sched.JOBS}
        self.assertEqual(jobs["kriticar"], ("every", (["run_critic.py", "trades"], 5.0, True)))
        self.assertEqual(jobs["kriticar_dan"], ("daily_local_first", (["run_critic.py", "daily"], 6, True, 40)))
        self.assertEqual(jobs["kriticar_dubinski"], ("every", (["run_critic.py", "deep", "--auto"], 10.0, True)))
        with open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "start.sh")) as f:
            self.assertIn("low keep kriticar python3 run_critic.py loop", f.read())
        self.assertEqual(cpuguard.classify(["python3", "run_critic.py", "trades"])[:2], ("kriticar", cpuguard.JOBS))
        calls = []
        with mock.patch.object(run_sched, "run", side_effect=lambda n, a, light=False: calls.append(n) or 0), \
                mock.patch.object(run_sched, "_last_day", return_value=None), \
                mock.patch.object(run_sched, "_set_last_day"), \
                mock.patch.object(run_sched.time, "sleep", side_effect=[None, KeyboardInterrupt]), \
                mock.patch.object(run_sched, "daily_local", side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                run_sched.daily_local_first("kriticar_dan", ["run_critic.py", "daily"], 6, True, 40)
        self.assertEqual(calls, ["kriticar_dan"])   # at once after the start, not at 06:40

    def test_cli_exit_codes(self):
        import run_critic
        with mock.patch("critic.trades.run", return_value={"skip": "greška API-ja"}):
            self.assertEqual(run_critic.main(["trades"]), 1)
        with mock.patch("critic.daily.run", return_value={"skip": "nema ključa"}):
            self.assertEqual(run_critic.main(["daily"]), 0)

    def test_morning_report_section(self):
        from report import collect, render
        self.assertIn("Kritičar još nema pregleda", render.kriticar_body(None))
        self.key()
        pid = self.add_pos()
        self.run_trades([self.pos(pid)], [answer(verdicts((pid, "prodaj", 0.8)))])
        http = FakeHTTP([answer(Daily.ANS)])
        with mock.patch.object(openai_api, "_urlopen", http):
            cdaily.run(NOW, log=self.log, tcon=self.con, payload_fn=lambda c, n: {})
        with mock.patch.dict(os.environ, {"REPORT_DB_DIR": self.tmp.name}):
            k = collect.kriticar(NOW + 60)
        self.assertEqual(k["pozicije"][0]["verdict"], "prodaj")
        self.assertEqual(k["mjesec"]["poziva"], 2)
        html = render.kriticar_body(k)
        for part in ("dnevni pregled", "Mali uzorak range", "Presude za otvorene pozicije", "prodaj", "Trošak: jučer 0 poziva"):
            self.assertIn(part, html)

    def test_cost_line_and_week(self):
        from usage import daily
        cstore.book(self.con, "trades", "gpt-5-mini", {"in": 1000, "out": 500}, 0.0012, True, now=NOW)
        cstore.book(self.con, "daily", "gpt-5.4", {"in": 9000, "out": 3000}, 0.07, True, now=NOW)
        d = daily.openai(NOW + 10, {"trade": self.db})
        self.assertEqual((d["poziva"], d["usd"], d["po_vrsti"]), (2, 0.0712, {"daily": 0.07, "trades": 0.0012}))
        line = daily.line({"day": "x", "openai": d})
        self.assertIn("OpenAI kritičar 2 poziva, $0,07 (daily 0,07, trades 0,00), 0 presuda", line)
        self.assertIsNone(daily.openai(NOW, {}))

    def test_mcp_get_critic_stats(self):
        from ui import mcpapi
        self.assertIn("get_critic_stats", {t["name"] for t in mcpapi.TOOLS})
        d, err = mcpapi._tool("get_critic_stats", {"days": 3})
        self.assertFalse(err)
        self.assertEqual(d["poziva"], 0)
        self.assertIn("budzet", d)
        d, err = mcpapi._tool("get_critic_stats", {"days": "x"})
        self.assertTrue(err)

    def test_grok_unreviewed_list_ignores_the_critic(self):
        pid = self.add_pos(status="closed")
        self.con.execute("UPDATE positions SET closed_ts=? WHERE id=?", (NOW, pid))
        self.con.commit()
        assistnotes.submit_trade_review(self.con, cnotes.KID, pid, "loš", 0.5, "PRODAJ · x")
        self.assertEqual(assistnotes.reviewed_positions(self.con), set())
        assistnotes.submit_trade_review(self.con, assistnotes.key_id("grok"), pid, "dobar", 0.5, "ok")
        self.assertEqual(assistnotes.reviewed_positions(self.con), {pid})
        self.assertEqual(assistnotes.latest_for(self.con, [pid])[("p", pid)]["verdict"], "dobar")


class LiveComments(Base):
    def order(self, pid, side="buy", token=MINT, mode="live", status="ok", ts=NOW - 30, sol=0.1):
        lam = int(sol * 1e9)
        cur = self.con.execute("INSERT INTO orders (ts, position_id, token, side, mode, amount_in, amount_out, cost_pct, "
                               "status, reason, signature) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                               (ts, pid, token, side, mode, lam if side == "buy" else 1000, lam if side == "sell" else 1000,
                                0.8, status, "copy wallet " + WALLET, "5sig" + "x" * 80))
        self.con.commit()
        return cur.lastrowid

    def test_watcher_starts_at_the_newest_order_and_spawns_after_the_debounce(self):
        self.key()
        pid = self.add_pos()
        old = self.order(pid)
        spawned = []
        spawn = lambda a, b, log: spawned.append((a, b))   # noqa: E731
        self.assertIsNone(live_mod.loop(log=self.log, spawn=spawn, once=True, tcon=self.con))
        self.assertEqual(cstore.kv_get(self.con, "live_last_order"), old)   # history is not commented
        self.order(pid, status="failed")
        self.order(pid, mode="dry")
        self.assertIsNone(live_mod.loop(log=self.log, spawn=spawn, once=True, tcon=self.con))   # no live fill
        a = self.order(pid, side="sell")
        b = self.order(pid, side="buy")
        self.assertEqual(live_mod.loop(log=self.log, spawn=spawn, once=True, tcon=self.con), "čekam")
        self.assertEqual(live_mod.loop(log=self.log, spawn=spawn, once=True, tcon=self.con, debounce=0), "komentirao")
        self.assertEqual(spawned, [(old, b)])
        self.assertEqual(cstore.kv_get(self.con, "live_last_order"), b)
        self.assertGreater(b, a)
        settings.set_flag(self.con, "openai_kritika", "off", "jure")
        self.assertEqual(live_mod.loop(log=self.log, spawn=spawn, once=True, tcon=self.con), "mirujem")

    def test_buy_and_close_comments(self):
        self.key()
        p1 = self.add_pos()
        p2 = self.add_pos(MINT2, status="closed")
        self.con.execute("UPDATE positions SET sol_back=0.13, closed_ts=?, fees_sol=0.002 WHERE id=?", (NOW - 20, p2))
        self.con.commit()
        o1 = self.order(p1, "buy")
        o2 = self.order(p2, "sell", token=MINT2)
        ans = {"tradeovi": [{"id": o1, "ocjena": "los", "confidence": 0.7, "komentar": ["Ulaz +40 % iznad poziva"],
                             "verdict": "stegni_sl", "promijenilo_bi": "rast kupaca"},
                            {"id": o2, "ocjena": "dobar", "confidence": 0.8, "komentar": ["Izlaz +28 % nakon fija"],
                             "verdict": "zatvoreno", "promijenilo_bi": ""}], "opce": None}
        http = FakeHTTP([answer(ans, tin=3000, tout=1000)])
        with mock.patch.object(openai_api, "_urlopen", http):
            res = live_mod.run(0, o2, NOW, log=self.log, tcon=self.con, positions_fn=self.positions_fn([self.pos(p1)]),
                               series_fn=lambda tok, ts, now_: ([], []))
        self.assertEqual(res["komentara"], 2)
        b = http.calls[0]["body"]
        self.assertEqual((b["model"], b["reasoning"]), ("gpt-6-astra", {"effort": "low"}))
        self.assertTrue(b["input"].startswith(prompts.LIVE_TRADE))
        data = json.loads(b["input"].split("Podaci (JSON):\n", 1)[1])
        kinds = {x["id"]: x for x in data["tradeovi"]}
        self.assertEqual(kinds[o1]["vrsta"], "kupnja")
        self.assertEqual(kinds[o1]["pozicija"]["id"], p1)
        self.assertEqual(kinds[o2]["zatvorena_pozicija"]["ostvareni_pnl_pct"], 28.0)
        body = json.dumps(b, ensure_ascii=False)
        for bad in (WALLET, SECRET, "5sig"):
            self.assertNotIn(bad, body)
        notes = self.con.execute("SELECT position_id, verdict, key_id, interpretation, evidence FROM assistant_notes "
                                 "ORDER BY id").fetchall()
        self.assertEqual([(n[0], n[1], n[2]) for n in notes], [(p1, "loš", cnotes.KID), (p2, "dobar", cnotes.KID)])
        self.assertTrue(notes[0][3].startswith("KUPNJA: LOS · Ulaz +40 %"))
        self.assertEqual(json.loads(notes[1][4])["verdict"], "zatvoreno")
        # the open position's comment is a measured verdict (and resets the re-check's clock), the close is not
        self.assertEqual(self.con.execute("SELECT pid, verdict FROM critic_verdicts").fetchall(), [(p1, "stegni_sl")])
        self.assertEqual(self.con.execute("SELECT kind, ok FROM critic_calls").fetchall(), [("live", 1)])
        self.assertTrue(any(x.startswith("kritičar: live komentar TOK kupnja: los, dalje stegni SL") for x in self.logs))
        self.assertTrue(any(x.startswith("kritičar: live komentar TWO prodaja: dobar") for x in self.logs))
        self.assertEqual(cstore.kv_get(self.con, "live_last_order"), o2)
        from ui import apterm
        line = apterm._critic_html(apterm._critic_slim(assistnotes.latest_critic(self.con, [p1])[p1]), NOW)
        self.assertIn("Kritičar (OpenAI): stegni SL · sigurnost 70 % · kupnja los: Ulaz +40 %", line)

    def test_no_key_and_budget(self):
        pid = self.add_pos()
        o = self.order(pid)
        self.assertEqual(live_mod.run(0, o, NOW, log=self.log, tcon=self.con)["skip"], "nema ključa")
        self.key()
        with mock.patch.object(cstore, "DAY_USD", 0.0001), mock.patch.object(openai_api, "_urlopen", FakeHTTP([])) as h:
            r = live_mod.run(0, o, NOW, log=self.log, tcon=self.con, positions_fn=self.positions_fn([self.pos(pid)]),
                             series_fn=lambda tok, ts, now_: ([], []))
        self.assertEqual((r["skip"], h.calls), ("budžet", []))


class DeepReview(Base):
    def setUp(self):
        super().setUp()
        self.root = os.path.join(self.tmp.name, "dbs")
        os.makedirs(self.root)
        lg = sqlite3.connect(os.path.join(self.root, "league.db"))
        lg.executescript("CREATE TABLE trades (id INTEGER PRIMARY KEY, user TEXT, token TEXT, ret REAL, opened_ts INTEGER);"
                         "CREATE TABLE members (name TEXT); INSERT INTO members VALUES ('Marica');"
                         "CREATE TABLE copy_rank_kv (k TEXT, v TEXT);")
        lg.executemany("INSERT INTO trades (user, token, ret, opened_ts) VALUES (?,?,?,?)",
                       [("pravi-trade" if i % 3 else "Marica", MINT if i % 2 else MINT2, (i % 7 - 3) / 10, NOW - i * 600)
                        for i in range(260)])
        lg.commit()
        lg.close()
        tr = sqlite3.connect(os.path.join(self.root, "trade.db"))
        tr.executescript("CREATE TABLE settings (k TEXT, v TEXT); CREATE TABLE orders (id INTEGER PRIMARY KEY, token TEXT, "
                         "signature TEXT, status TEXT);")
        tr.execute("INSERT INTO settings VALUES ('mcp_key', ?)", (SECRET,))
        tr.execute("INSERT INTO orders (token, signature, status) VALUES (?, '5sigxxxx', 'ok')", (MINT,))
        tr.commit()
        tr.close()
        an = sqlite3.connect(os.path.join(self.root, "analytics.db"))
        an.execute("CREATE TABLE v (ip TEXT)")
        an.commit()
        an.close()
        self.dbs = deep_mod.databases(self.root)
        self.al = deep_mod.Aliases({"Marica"})

    def sql(self, db, q, **kw):
        return json.loads(deep_mod.run_sql(self.dbs, db, q, self.al, **kw))

    def test_read_only_whitelist_and_deny_list(self):
        self.assertEqual(sorted(self.dbs), ["league", "trade"])            # analytics.db is never offered
        ok = self.sql("league", "SELECT COUNT(*) AS n, AVG(ret) FROM trades")
        self.assertEqual(ok["rows"][0][0], 260)
        for q in ("DELETE FROM trades", "UPDATE trades SET ret=1", "PRAGMA table_list", "SELECT 1; DROP TABLE trades",
                  "ATTACH DATABASE 'x.db' AS x", "CREATE TABLE z (a)", "WITH x AS (SELECT 1) DELETE FROM trades"):
            self.assertIn("error", self.sql("league", q), q)
        for db, q in (("trade", "SELECT * FROM settings"), ("trade", "SELECT signature FROM orders"),
                      ("trade", "SELECT * FROM orders"), ("league", "SELECT * FROM copy_rank_kv"),
                      ("trade", "SELECT name FROM sqlite_master")):
            self.assertIn("error", self.sql(db, q), q)
        self.assertEqual(self.sql("trade", "SELECT id, token, status FROM orders")["rows"][0][2], "ok")
        self.assertIn("error", self.sql("nema", "SELECT 1"))
        c = sqlite3.connect(os.path.join(self.root, "league.db"))
        self.assertEqual(c.execute("SELECT COUNT(*) FROM trades").fetchone()[0], 260)   # nothing was changed
        c.close()
        slow = self.sql("league", "WITH RECURSIVE r(i) AS (SELECT 1 UNION ALL SELECT i + 1 FROM r) "
                                  "SELECT COUNT(*) FROM r", timeout=0.2)
        self.assertIn("prekinut", slow["error"])

    def test_rows_capped_addresses_aliased_and_mapped_back_names_hidden(self):
        r = self.sql("league", "SELECT user, token FROM trades ORDER BY id")
        self.assertEqual((len(r["rows"]), r["truncated"]), (200, True))
        text = json.dumps(r)
        self.assertNotIn(MINT, text)
        self.assertNotIn("Marica", text)
        alias = r["rows"][1][1]
        self.assertRegex(alias, r"^\[a:[0-9a-f]{8}\]$")
        back = self.sql("league", f"SELECT COUNT(*) FROM trades WHERE token = '{alias}'")
        self.assertEqual(back["rows"][0][0], 130)
        cat = deep_mod.catalog(self.dbs)
        self.assertNotIn("settings", cat["trade"])
        self.assertNotIn("copy_rank_kv", cat["league"])
        self.assertEqual(cat["trade"]["orders"]["stupci"], ["id", "token", "status"])
        self.assertEqual(cat["league"]["trades"]["redaka"], 260)

    def test_session_with_tool_calls_stores_findings_and_summary(self):
        self.key()
        calls = {"id": "resp_t", "model": "gpt-6-astra", "status": "completed",
                 "output": [{"type": "reasoning", "summary": []},
                            {"type": "function_call", "id": "fc_1", "call_id": "c1", "name": "sql",
                             "arguments": json.dumps({"db": "league", "query": "SELECT user, AVG(ret), COUNT(*) FROM trades GROUP BY user"})},
                            {"type": "function_call", "id": "fc_2", "call_id": "c2", "name": "sql",
                             "arguments": json.dumps({"db": "trade", "query": "SELECT * FROM settings"})}],
                 "usage": {"input_tokens": 9000, "output_tokens": 1500}}
        final = answer({"sazetak": "Efekt callera ne prolazi holdout (n=86 / 43).",
                        "nalazi": [{"naslov": "Caller efekt nestaje", "ozbiljnost": "visoka", "dokaz": "EV +6 pp prije, -1 pp poslije",
                                    "prijedlog": "ne povećavaj težinu", "kako_provjeriti": "14 dana, n 60"}],
                        "eksperimenti": [{"naziv": "Holdout callera", "hipoteza": "h", "kako": "k", "n_potreban": 60, "dana": 14}],
                        "koliko_cesto": {"preporuka": "svaka 3 dana", "razlog": "malo novih tradeova"},
                        "nedostaje_mjerenje": ["kašnjenje ulaza"]}, tin=14000, tout=3000)
        http = FakeHTTP([calls, final])
        with mock.patch.object(openai_api, "_urlopen", http), mock.patch.object(deep_mod.time, "sleep", lambda s: None):
            res = deep_mod.run(NOW, log=self.log, tcon=self.con, auto=True, root=self.root, night_fn=lambda: False,
                               sleep=lambda s: None)
        self.assertEqual((res["nalaza"], res["upita"], res["poziva"]), (1, 2, 2))
        b1, b2 = http.calls[0]["body"], http.calls[1]["body"]
        self.assertEqual((b1["model"], b1["tools"][0]["name"], b1["store"]), ("gpt-6-astra", "sql", False))
        outs = [x for x in b2["input"] if isinstance(x, dict) and x.get("type") == "function_call_output"]
        self.assertEqual([o["call_id"] for o in outs], ["c1", "c2"])
        self.assertIn("error", json.loads(outs[1]["output"]))            # settings refused
        self.assertTrue(all("id" not in x for x in b2["input"] if x.get("type") == "function_call"))
        body = json.dumps([c["body"] for c in http.calls], ensure_ascii=False)
        for bad in (SECRET, MINT, MINT2, "Marica", "HELIUS_API_KEY", "helius-secret-key-42", "5sigxxxx"):
            self.assertNotIn(bad, body, bad)
        rows = self.con.execute("SELECT kind, title FROM assistant_notes ORDER BY id").fetchall()
        self.assertEqual(rows[0], ("suggestion", "Kritičar: Caller efekt nestaje"))
        self.assertTrue(rows[1][1].startswith("Kritičar (OpenAI): Dubinski pregled"))
        self.assertEqual(self.con.execute("SELECT COUNT(*), SUM(cost_usd) FROM critic_calls WHERE kind='deep'").fetchone()[0], 2)
        self.assertEqual(cstore.kv_get(self.con, "deep_last")["upita"], 2)
        self.assertTrue(any(x.startswith("kritičar: dubinski pregled spremljen, 1 nalaza, upita 2, trošak") for x in self.logs))
        # once: the next look is not due (19.11.: daily, was 48 h; then only in the night window)
        self.assertEqual(deep_mod.EVERY_H, 24)
        self.assertEqual(deep_mod.due(self.con, NOW + 3600, lambda: True), (False, None))
        self.assertEqual(deep_mod.due(self.con, NOW + 22 * 3600, lambda: True), (False, None))
        self.assertEqual(deep_mod.due(self.con, NOW + 23 * 3600, lambda: False), (False, None))
        self.assertEqual(deep_mod.due(self.con, NOW + 23 * 3600, lambda: True)[0], True)   # no drift out of the window
        self.assertEqual(deep_mod.due(self.con, NOW + 25 * 3600, lambda: True)[0], True)

    def test_context_blocks_and_learned_exits(self):
        self.assertIsNone(deep_mod.learned_exits(self.con, NOW, self.dbs))
        c = sqlite3.connect(os.path.join(self.root, "league.db"))
        c.execute("CREATE TABLE learned_exits (source TEXT, sl REAL, grace_min INTEGER, tp1 REAL, sig TEXT)")
        c.execute("INSERT INTO learned_exits VALUES (?, 0.25, 8, 0.12, 'x')", ("wallet " + WALLET,))
        c.commit()
        c.close()
        le = deep_mod.learned_exits(self.con, NOW, self.dbs)
        self.assertEqual((le["baza"], le["redaka"], le["stupci"]), ("league", 1, ["source", "sl", "grace_min", "tp1"]))
        ctx = deep_mod.context(self.con, NOW, self.dbs, {}, self.log)
        self.assertIn("naucni_izlazi_po_izvoru", ctx)
        with mock.patch.object(deep_mod, "CONTEXT_BLOCKS", deep_mod.CONTEXT_BLOCKS + [("kvar", lambda *a: 1 / 0)]):
            self.assertNotIn("kvar", deep_mod.context(self.con, NOW, self.dbs, {}, self.log))
        self.assertIn("MAE", prompts.DEEP)
        self.assertIn("minute.call_path", prompts.DEEP)
        # 15.11.: once izlazi/ has learned (nightly), its own summary is the block
        from izlazi import report as izreport
        with mock.patch.object(izreport, "critic_summary", lambda top=30, path=None: {"available": True, "izvori": [1]}):
            self.assertEqual(deep_mod.learned_exits(self.con, NOW, self.dbs), {"available": True, "izvori": [1]})

    def test_session_cap(self):
        self.key()
        with mock.patch.object(cstore, "DEEP_USD", 0.05), mock.patch.object(openai_api, "_urlopen", FakeHTTP([])) as h:
            res = deep_mod.run(NOW, log=self.log, tcon=self.con, root=self.root, sleep=lambda s: None)
        self.assertEqual((res["skip"], h.calls), ("budžet", []))


if __name__ == "__main__":
    unittest.main()


class Order2711(unittest.TestCase):
    """27.11. (vlasnik: "isključi OpenAI kritičara"): jednom, samo na niže; vlasnik ga može ponovno uključiti."""

    def test_once_off_then_owner_can_turn_it_back_on(self):
        import sqlite3 as _sq
        import tempfile as _tf
        from trade import settings as st
        with _tf.TemporaryDirectory() as d:
            con = st.connect(os.path.join(d, "trade.db")) if hasattr(st, "connect") else _sq.connect(os.path.join(d, "t.db"))
            st._FLAG_CACHE.clear()
            self.assertEqual(st.flag_state(con)[st.KRITICAR]["mode"], "live")          # zadano uključen
            txt = st.kriticar_order_2711(con, now=1795730000)
            self.assertIn("live → off", txt)
            st._FLAG_CACHE.clear()
            self.assertEqual(st.flag_state(con)[st.KRITICAR]["mode"], "off")
            st.set_flag(con, st.KRITICAR, "live", st.owner(), now=1795730100)           # vlasnik ga vraća
            self.assertIsNone(st.kriticar_order_2711(con, now=1795730200))              # nalog se ne ponavlja
            st._FLAG_CACHE.clear()
            self.assertEqual(st.flag_state(con)[st.KRITICAR]["mode"], "live")
            con.close()
