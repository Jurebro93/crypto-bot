"""KOL wallets, convergence and exploration arms, all offline (19.11.: the Telegram reader tests went with it).

    python3 -m unittest tests.test_social_sources_offline
"""
import json
import os
import random
import sqlite3
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from kol import chainwatch, collect, converge, idents, store as kstore  # noqa: E402
from paper import arms  # noqa: E402

CA1 = "7xKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU"
CA2 = "HgxEGTZ1Epb64RrYqcuHkqb1gGWWnF5WcPTCDWzApump"


def page(channel, posts, public=True, subs="12.5K"):
    head = ('<div class="tgme_channel_info"><div class="tgme_channel_info_header_title"><span>Gem Calls</span></div>'
            f'<span class="counter_value">{subs}</span> <span class="counter_type">subscribers</span></div>') if public else ""
    body = ""
    for pid, iso, text, views, fwd in posts:
        f = (f'<a class="tgme_widget_message_forwarded_from_name" href="https://t.me/{fwd}/9">x</a>') if fwd else ""
        body += (f'<div class="tgme_widget_message_wrap js-widget_message_wrap"><div class="tgme_widget_message" '
                 f'data-post="{channel}/{pid}">{f}<div class="tgme_widget_message_text js-message_text" dir="auto">{text}'
                 f'</div><span class="tgme_widget_message_views">{views}</span>'
                 f'<time datetime="{iso}" class="time">x</time></div></div>')
    return head + body


class Wallets(unittest.TestCase):
    def test_kolscan_payload(self):
        rows = [{"wallet_address": "W1", "name": "slingoor", "telegram": "https://t.me/slingdeez",
                 "twitter": "https://x.com/slingoorio", "profit": 10.5, "wins": 3, "losses": 1}]
        payload = json.dumps('5:["$","$L11",null,{"initLeaderboard":' + json.dumps(rows) + '}]')
        html = f'<script>self.__next_f.push([1,{payload}])</script>'
        out = idents.parse_kolscan(html)
        self.assertEqual(out[0]["twitter"], "slingoorio")
        self.assertEqual(out[0]["wallet"], "W1")

    def test_webhook_parse(self):
        tx = {"feePayer": "W1", "signature": "S1", "timestamp": 100, "tokenTransfers": [
            {"mint": chainwatch.SOL, "fromUserAccount": "W1", "toUserAccount": "P", "tokenAmount": 1.5},
            {"mint": CA1, "fromUserAccount": "P", "toUserAccount": "W1", "tokenAmount": 1e6}]}
        self.assertEqual(chainwatch.parse([tx]), [("S1", "W1", CA1, "buy", 100, 1.5)])
        tx2 = {"feePayer": "W1", "signature": "S2", "timestamp": 200, "tokenTransfers": [
            {"mint": CA1, "fromUserAccount": "W1", "toUserAccount": "P", "tokenAmount": 1e6}]}
        self.assertEqual(chainwatch.parse([tx2])[0][3], "sell")

    def test_sync_webhook(self):
        tmp = tempfile.mkdtemp()
        con = kstore.connect(os.path.join(tmp, "kol.db"))
        idents.save(con, [{"wallet": "W1", "name": "a", "twitter": "a", "telegram": None, "pnl": 1, "wins": 1,
                           "losses": 0, "rank": 1}], "kolscan")
        calls = []
        api = lambda m, p="", b=None: calls.append((m, p, b)) or ([] if m == "GET" else {"webhookID": "H1"})
        os.environ["RENDER_EXTERNAL_URL"], os.environ["KOL_HOOK_KEY"] = "https://x.example", "k"
        try:
            self.assertTrue(chainwatch.sync(con, {"max_wallets": 10, "resync_h": 24}, 1000, api, log=lambda *a: None))
            self.assertFalse(chainwatch.sync(con, {"max_wallets": 10, "resync_h": 24}, 2000, api, log=lambda *a: None))
        finally:
            del os.environ["RENDER_EXTERNAL_URL"], os.environ["KOL_HOOK_KEY"]
        self.assertEqual([c[0] for c in calls], ["GET", "POST"])
        self.assertEqual(calls[1][2]["accountAddresses"], ["W1"])


class Converge(unittest.TestCase):
    def test_score(self):
        cfg = converge.DEFAULT
        now = 10_000
        scores = {"goodx": 70, "goodtg": 60, "tg:goodtg": 60, "meh": 10}
        evs = [(CA1, now - 300, "x", "goodx", "call"), (CA1, now - 200, "tg", "tg:goodtg", "call"),
               (CA1, now - 100, "chain", "kolA", "buy"), (CA1, now - 50, "x", "meh", "call")]
        r = converge.score_token(evs, scores, {}, cfg, 50, now)
        self.assertEqual((r["n_x"], r["n_tg"], r["n_chain"], r["n_other"]), (1, 1, 1, 1))
        self.assertEqual(r["platforms"], ["x", "tg", "chain"])
        self.assertEqual(r["score"], 18 + 18 + 22 + 3 + 24)
        sold = converge.score_token(evs + [(CA1, now, "chain", "kolA", "sell")], scores, {}, cfg, 50, now)
        self.assertLess(sold["score"], r["score"] * 0.5)
        promo = [(CA2, now - 100 + i, "tg", f"tg:c{i}", "call") for i in range(6)]
        p = converge.score_token(promo, scores, {}, cfg, 50, now)
        self.assertTrue(p["promo"])


class Arms(unittest.TestCase):
    def test_arm_and_sampling(self):
        c = {"sources": {"telegram", "pumpfun:live"}, "features": {"kol_x": 0.5}}
        self.assertEqual(arms.platforms_of(c, {"platforms": ["chain"]}), ["chain", "pump", "tg", "x"])
        st = {"bad": [0, 30], "good": [20, 5]}
        rng = random.Random(1)
        self.assertTrue(arms.allow("new", st, rng=rng)[0])
        self.assertTrue(all(arms.allow("good", st, rng=rng)[0] for _ in range(20)))
        bad = sum(arms.allow("bad", st, rng=rng)[0] for _ in range(200))
        self.assertLess(bad, 60)   # mostly skipped, never zero chance
        self.assertEqual(arms.loss_reason("stop_loss", 0.01, -0.4, -0.35), "kasni ulaz (odmah pad)")
        self.assertIsNone(arms.loss_reason("trailing", 0.5, 0, 0.2))


class KonvEntry(unittest.TestCase):
    def test_convergence_trade(self):
        import run_paper
        from paper import sim, store
        tmp = tempfile.mkdtemp()
        saved = {k: getattr(run_paper, k) for k in ("DB", "hype_signals", "event_tokens", "market", "rug_verdict",
                                                     "klasa_of", "notify", "t0_of")}
        from learn import weights
        saved_ld = weights.LEARNED_DIR
        saved_conv = kstore.converge
        now = time.time()
        try:
            run_paper.DB = os.path.join(tmp, "paper.db")
            run_paper.hype_signals = lambda now=None: [{"token": "K", "symbol": "K", "ts": now, "score": 15,
                                                        "features": {}, "sources": {"konv"}, "url": None,
                                                        "origin": "hype"}]
            run_paper.event_tokens = lambda c, n=None: []
            run_paper.market = lambda toks: {t: (0.0001, 20_000, 100_000, None) for t in toks}
            run_paper.t0_of = lambda toks, col="t0": {t: "prolaz" for t in toks} if col == "t0" else {}
            from learn import weights
            weights.LEARNED_DIR = tmp
            run_paper.rug_verdict = lambda con, t, cfg, now, paid=True: (None, None, [])
            run_paper.klasa_of = lambda toks: {}
            run_paper.notify = lambda *a, **k: None
            kstore.converge = lambda tokens=None, max_age_min=60, path=None: {"K": {
                "score": 80, "first_ts": now - 120, "platforms": ["x", "tg"], "n_x": 2, "n_tg": 1, "n_chain": 0,
                "kol_selling": 0}}
            opened = run_paper.intake(sim.load_config(), now=now, quiet=True)
            self.assertEqual([c["token"] for c in opened], ["K"])
            con = store.connect(run_paper.DB)
            conf = json.loads(con.execute("SELECT config FROM trades").fetchone()[0])
            self.assertEqual(conf["entry_mode"], "konv")
            self.assertTrue(conf["arm"].startswith("tg+x|"))
            self.assertEqual(conf["tp"][0], [0.4, 0.6])
        finally:
            for k, v in saved.items():
                setattr(run_paper, k, v)
            kstore.converge = saved_conv
            weights.LEARNED_DIR = saved_ld

    def test_skipped_token_reconsidered_when_convergence_grows(self):
        """31.10.: a token first seen with one wallet buy was decided once (skipped) and never looked at again when
        two more KOL wallets bought; now it gets a convergence entry."""
        import run_paper
        from paper import sim, store
        tmp = tempfile.mkdtemp()
        saved = {k: getattr(run_paper, k) for k in ("DB", "hype_signals", "event_tokens", "market", "rug_verdict",
                                                     "klasa_of", "notify", "konv_now", "t0_of")}
        from learn import weights
        saved_ld = weights.LEARNED_DIR
        now = time.time()
        try:
            run_paper.DB = os.path.join(tmp, "paper.db")
            con = store.connect(run_paper.DB)
            store.add_candidate(con, {"token": "W", "ts": now - 600, "origin": "hype", "score": 10,
                                      "decision": "ignored"})
            con.commit()
            con.close()
            run_paper.hype_signals = lambda now=None: [{"token": "W", "symbol": "W", "ts": now, "score": 12,
                                                        "features": {}, "sources": {"konv"}, "url": None,
                                                        "origin": "hype"}]
            run_paper.event_tokens = lambda c, n=None: []
            run_paper.market = lambda toks: {t: (0.0001, 20_000, 100_000, None) for t in toks}
            run_paper.t0_of = lambda toks, col="t0": {t: "prolaz" for t in toks} if col == "t0" else {}
            from learn import weights
            weights.LEARNED_DIR = tmp
            run_paper.rug_verdict = lambda con, t, cfg, now, paid=True: (None, None, [])
            run_paper.klasa_of = lambda toks: {}
            run_paper.notify = lambda *a, **k: None
            run_paper.konv_now = lambda toks, now: {"W": {"score": 68, "first_ts": now - 900, "last_ts": now - 60,
                                                          "platforms": ["chain", "x"], "n_x": 1, "n_tg": 0, "n_chain": 3,
                                                          "kol_selling": 0}} if "W" in toks else {}
            opened = run_paper.intake(sim.load_config(), now=now, quiet=True)
            self.assertEqual([c["token"] for c in opened], ["W"])
        finally:
            for k, v in saved.items():
                setattr(run_paper, k, v)
            weights.LEARNED_DIR = saved_ld

    def test_konv_fresh(self):
        import run_paper
        kc = {"min_score": 55, "max_age_min": 10, "window_min": 30}
        now = 10_000
        self.assertTrue(run_paper.konv_fresh({"score": 68, "first_ts": now - 900, "last_ts": now - 60, "n_x": 1}, kc, now))
        # wallets only, not one post: needs chain_only_min (6) wallets (1.11.: 11 such entries at -100%)
        self.assertFalse(run_paper.konv_fresh({"score": 68, "first_ts": now - 900, "last_ts": now - 60, "n_chain": 4}, kc, now))
        self.assertTrue(run_paper.konv_fresh({"score": 68, "first_ts": now - 900, "last_ts": now - 60, "n_chain": 6}, kc, now))
        self.assertFalse(run_paper.konv_fresh({"score": 68, "first_ts": now - 900, "last_ts": now - 700}, kc, now))
        self.assertFalse(run_paper.konv_fresh({"score": 68, "first_ts": now - 3600, "last_ts": now - 60}, kc, now))
        self.assertFalse(run_paper.konv_fresh({"score": 40, "first_ts": now - 60, "last_ts": now - 60}, kc, now))
        self.assertFalse(run_paper.konv_fresh({"score": 90, "first_ts": now - 60, "last_ts": now, "kol_selling": 1},
                                              kc, now))
        self.assertTrue(run_paper.konv_fresh({"score": 80, "first_ts": now - 120, "n_tg": 1}, kc, now))  # stored copy, no last_ts


if __name__ == "__main__":
    unittest.main()
