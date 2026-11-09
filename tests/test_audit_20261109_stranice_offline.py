"""Audit 9.11.2026, group "stranice" (Pregled / Influenceri / Copy trading / Walleti / Tokeni): what the pages surface
from the Autopilot's data and how freshness and missing data are labelled. Offline, no network."""
import gzip
import json
import os
import sqlite3
import sys
import tempfile
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ui import confidence, copytrade, evidence, kol as uikol, overview, pagecache, pages, pocetna, tokens  # noqa: E402

NOW = int(time.time())
MINT = "M" * 43


def _minute_row(handle, token, ts, t10=3, t15=6, sl_min=None, lo60=-0.1):
    return (f"tw{token}{handle}{ts}", token, handle, ts, 1.0, 20, 80_000, 0.2, 0.3, 0.4, lo60, 0.1,
            1, t10, t15, None, None, sl_min, 1, None, ts)


class WebhookSet(unittest.TestCase):
    """P42: '⚡ uživo' comes from the X webhook rule set (kv 'xhook', kol/xhook.sync), not only the xquik monitor table."""

    def setUp(self):
        self.con = sqlite3.connect(":memory:")
        self.con.execute("CREATE TABLE kv (key TEXT PRIMARY KEY, value TEXT)")

    def test_rule_values_parse_to_handles(self):
        self.con.execute("INSERT INTO kv VALUES ('xhook', ?)",
                         (json.dumps({"ts": NOW, "values": ["from:HotGuy OR from:goodkol", "from:bigacct"], "handles": 3}),))
        self.assertEqual(uikol.hook_handles(self.con), {"hotguy", "goodkol", "bigacct"})

    def test_empty_without_a_sync_or_table(self):
        self.assertEqual(uikol.hook_handles(self.con), set())
        bare = sqlite3.connect(":memory:")
        self.assertEqual(uikol.hook_handles(bare), set())

    def test_speed_badge_names_the_channel(self):
        self.assertIn("webhook", uikol.speed_badge(True, False))
        self.assertIn("⚡ uživo", uikol.speed_badge(True, False))
        self.assertIn("xquik", uikol.speed_badge(False, True))
        self.assertIn("sporije", uikol.speed_badge(False, False))


class CopyTradeRows(unittest.TestCase):
    """P42/P43: a hot-list account in the webhook without a monitor row is fast, ranks first and carries the minute stats;
    'live' (monitor) keeps its meaning for the other readers (ui/autopilot.kol_recs)."""

    def setUp(self):
        d = tempfile.mkdtemp()
        self.old = {k: os.environ.get(k) for k in ("KOL_DB", "HYPE_DB", "TG_DB")}
        os.environ.update(KOL_DB=os.path.join(d, "kol.db"), HYPE_DB=os.path.join(d, "hype.db"), TG_DB=os.path.join(d, "tg.db"))
        k = sqlite3.connect(os.environ["KOL_DB"])
        k.executescript("""CREATE TABLE calls (token TEXT, handle TEXT, ts INTEGER, kind TEXT);
            CREATE TABLE kols (handle TEXT, followers INTEGER, score REAL, stats TEXT, bot INTEGER DEFAULT 0);
            CREATE TABLE monitor (handle TEXT);
            CREATE TABLE kv (key TEXT PRIMARY KEY, value TEXT);""")
        st = json.dumps({"measured": 8, "hit_rate": 0.6, "med_max24": 0.9, "rug_rate": 0.1})
        k.execute("INSERT INTO kols VALUES ('slowguy', 90000, 80, ?, 0)", (st,))     # best score, no fast channel
        k.execute("INSERT INTO kols VALUES ('monguy', 5000, 60, ?, 0)", (st,))       # xquik monitor only
        k.execute("INSERT INTO kols VALUES ('hotguy', 2000, 50, ?, 0)", (st,))       # webhook (hot list), no monitor row
        k.execute("INSERT INTO monitor VALUES ('monguy')")
        k.execute("INSERT INTO kv VALUES ('xhook', ?)", (json.dumps({"values": ["from:hotguy OR from:monguy"]}),))
        k.commit()
        k.close()
        copytrade._CACHE.clear()

    def tearDown(self):
        for k, v in self.old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        copytrade._CACHE.clear()

    def test_fast_hook_and_minute_columns(self):
        ms = {"hotguy": {"n": 4, "hit5": 1.0, "hit10": 0.75, "hit15": 0.5, "hit20": 0.25, "hit30": 0.0, "sl": 0.25,
                         "rug": 0.0, "med_t10": 4, "med_r60": 0.1, "med_hi15": 0.2, "n_posts": 6}}
        with mock.patch.object(copytrade, "minute_stats", return_value=(ms, {"hotguy"})):
            rows = copytrade.kol_rows(NOW)
        by = {r["handle"]: r for r in rows}
        self.assertEqual((by["hotguy"]["live"], by["hotguy"]["hook"], by["hotguy"]["fast"], by["hotguy"]["hot"]),
                         (False, True, True, True))
        self.assertEqual((by["monguy"]["live"], by["monguy"]["hook"], by["monguy"]["fast"]), (True, True, True))
        self.assertEqual((by["slowguy"]["live"], by["slowguy"]["fast"], by["slowguy"]["ms"]), (False, False, None))
        self.assertEqual([r["handle"] for r in rows], ["hotguy", "monguy", "slowguy"])   # fast, then hot, then score
        html = copytrade._kol_table(rows, {}, None, "")
        self.assertIn("🔥 vruća lista", html)
        self.assertIn("+15 % prije stopa", html)
        self.assertIn("stara mjera", html)
        hot_row = html[html.index("hotguy"):html.index("monguy")]
        self.assertIn("⚡ uživo", hot_row)
        self.assertIn("webhook", hot_row)
        slow_row = html[html.index("slowguy"):]
        self.assertIn("sporije", slow_row)

    def test_without_sync_the_monitor_still_counts(self):
        k = sqlite3.connect(os.environ["KOL_DB"])
        k.execute("DELETE FROM kv")
        k.commit()
        k.close()
        with mock.patch.object(copytrade, "minute_stats", return_value=({}, set())):
            by = {r["handle"]: r for r in copytrade.kol_rows(NOW)}
        self.assertTrue(by["monguy"]["fast"])
        self.assertFalse(by["hotguy"]["fast"])


class MinuteStats(unittest.TestCase):
    """P43: the minute measure (kol/minute.handle_stats) and the hot list reach the influencer tables; empty is safe."""

    def test_reads_minute_db_and_hot_list(self):
        from kol import minute
        path = os.path.join(tempfile.mkdtemp(), "minute.db")
        con = minute.connect(path)
        rows = [_minute_row("hotguy", f"T{i}", NOW - 3600 * (i + 2)) for i in range(3)]
        rows.append(_minute_row("hotguy", "T0", NOW - 600))                  # the same token again: one call, not two
        rows.append(_minute_row("one", "T9", NOW - 3600, t10=None, sl_min=5))
        con.executemany("INSERT INTO call_path VALUES (" + ",".join("?" * 21) + ")", rows)
        con.execute("INSERT INTO kv VALUES ('hot_list', ?)", (json.dumps({"ts": NOW, "x": ["hotguy"], "tg": ["chan"], "wallets": []}),))
        con.commit()
        con.close()
        ms, hot = uikol.minute_stats(NOW, path=path)
        self.assertEqual(set(ms), {"hotguy"})                               # 'one' has 1 call < MINUTE_MIN_N
        self.assertEqual((ms["hotguy"]["n"], ms["hotguy"]["hit10"], ms["hotguy"]["sl"]), (3, 1.0, 0.0))
        self.assertEqual(hot, {"hotguy", "tg:chan"})
        cells = uikol.minute_cells(ms["hotguy"])
        self.assertEqual(len(cells), len(uikol.MINUTE_HEAD))
        self.assertEqual(cells[0][0], "100%")
        self.assertEqual(uikol.minute_cells(None)[0][0], "–")

    def test_missing_db_is_empty(self):
        self.assertEqual(uikol.minute_stats(NOW, path="/nonexistent/minute.db"), ({}, set()))


class PregledHighlights(unittest.TestCase):
    def _kol_con(self):
        con = sqlite3.connect(":memory:")
        con.execute("CREATE TABLE calls (handle TEXT, token TEXT, symbol TEXT, kind TEXT, ts INTEGER, max24 REAL)")
        return con

    def test_best_influencer_prefers_the_minute_measure(self):
        """P43: among the top accounts by call power the card picks by +15 % before the stop, and says the 24-h fuse
        is the old measure."""
        ks = [{"handle": "fuse", "score": 90, "s": {"measured": 20, "hit_rate": 0.7, "med_max24": 1.2}},
              {"handle": "steady", "score": 70, "s": {"measured": 12, "hit_rate": 0.4, "med_max24": 0.5}}]
        ms = {"steady": {"n": 5, "hit15": 0.8, "sl": 0.2}, "fuse": {"n": 4, "hit15": 0.25, "sl": 0.5}}
        with mock.patch("ui.core._con", return_value=self._kol_con()), \
                mock.patch("ui.core.top_kols", return_value=ks), \
                mock.patch("ui.kol.minute_stats", return_value=(ms, {"steady"})):
            html = pocetna._hl_kol()
        self.assertIn("steady", html)
        self.assertNotIn("fuse", html.split("Minutna")[0].split(">")[-1])
        self.assertIn("+15 % prije stopa 80%", html)
        self.assertIn("vruća lista", html)
        self.assertIn("stara mjera", html)

    def test_best_influencer_without_minute_data_keeps_call_power(self):
        ks = [{"handle": "fuse", "score": 90, "s": {"measured": 20, "hit_rate": 0.7, "med_max24": 1.2}},
              {"handle": "steady", "score": 70, "s": {"measured": 12, "hit_rate": 0.4, "med_max24": 0.5}}]
        with mock.patch("ui.core._con", return_value=self._kol_con()), \
                mock.patch("ui.core.top_kols", return_value=ks), \
                mock.patch("ui.kol.minute_stats", return_value=({}, set())):
            html = pocetna._hl_kol()
        self.assertIn("fuse", html)
        self.assertIn("još nema njegovih poziva", html)

    def test_wallet_highlight_names_both_populations(self):
        """P70: kol.db swaps are every webhook wallet; the Autopilot's followed + proven are a second number."""
        con = self._kol_con()
        con.executemany("INSERT INTO calls (handle, token, kind, ts) VALUES (?, ?, ?, ?)",
                        [("w:a", "T", "buy", NOW - 100), ("w:b", "T", "buy", NOW - 200), ("w:a", "T", "sell", NOW - 50)])
        with mock.patch("ui.core._con", return_value=con), mock.patch.object(pocetna, "_followed_buys", return_value=1):
            html = pocetna._hl_wallets(NOW)
        self.assertIn("Svi webhook novčanici", html)
        self.assertNotIn("Praćeni novčanici u zadnja", html)
        self.assertIn("<b class=pos>2</b> kupnji", html)
        self.assertIn("Praćeni + dokazani (Autopilot): <b>1</b>", html)
        self.assertIn("/pravi-trade#zovu", html)
        with mock.patch("ui.core._con", return_value=self._kol_con()), mock.patch.object(pocetna, "_followed_buys", return_value=None):
            con2 = self._kol_con()
            con2.execute("INSERT INTO calls (handle, token, kind, ts) VALUES ('w:a', 'T', 'buy', ?)", (NOW - 10,))
            with mock.patch("ui.core._con", return_value=con2):
                html = pocetna._hl_wallets(NOW)
        self.assertNotIn("Autopilot", html)       # nothing followed: no second number, no "0" that reads as a signal

    def test_followed_buys_counts_only_the_autopilot_wallets(self):
        d = tempfile.mkdtemp()
        hp = os.path.join(d, "hype.db")
        h = sqlite3.connect(hp)
        h.execute("CREATE TABLE chain_trades (wallet TEXT, mint TEXT, side TEXT, ts INTEGER, sol REAL)")
        h.executemany("INSERT INTO chain_trades VALUES (?, 'T', ?, ?, 1)",
                      [("F", "buy", NOW - 100), ("F", "sell", NOW - 90), ("F", "buy", NOW - 90000), ("X", "buy", NOW - 100)])
        h.commit()
        h.close()
        with mock.patch("ui.pravitrade.followed_wallets", return_value={"F"}), \
                mock.patch("league.copy._paths", return_value={"hype": hp, "kol": "", "tg": ""}):
            self.assertEqual(pocetna._followed_buys(NOW), 1)
        with mock.patch("ui.pravitrade.followed_wallets", return_value=set()):
            self.assertIsNone(pocetna._followed_buys(NOW))

    def test_converge_highlight_skips_xstocks_and_archived(self):
        """P71: the Pregled's hot token obeys kol/converge.not_a_memecoin and the rug archive like the Autopilot."""
        from kol import store as kstore
        path = os.path.join(tempfile.mkdtemp(), "kol.db")
        con = kstore.connect(path)
        con.execute("INSERT INTO tokens (token, symbol) VALUES ('STOCK', 'COINx')")
        con.execute("INSERT INTO tokens (token, symbol) VALUES ('RUGGED', 'RUG')")
        con.execute("INSERT INTO tokens (token, symbol) VALUES ('MEME', 'MEME')")
        for tok, n in (("STOCK", 40), ("RUGGED", 30), ("MEME", 3)):
            con.execute("INSERT INTO converge (token, ts, first_ts, score, n_x, n_tg, n_chain, n_other, platforms, "
                        "handles, kol_selling, updated) VALUES (?,?,?,?,?,?,?,?,'[]','[]',0,?)",
                        (tok, NOW - 100, NOW - 200, 90, 1, 0, n, 0, NOW))
        con.commit()
        con.close()
        old, kstore.DB = kstore.DB, path
        try:
            with mock.patch("rugfilter.archive.blocked", return_value=frozenset({"RUGGED"})):
                html = pocetna._hl_converge(NOW)
        finally:
            kstore.DB = old
        self.assertIn("MEME", html)
        self.assertNotIn("COINx", html)
        self.assertNotIn("RUGGED", html)
        self.assertIn("webhook novčanika", html)      # n_chain counts every webhook wallet, the label says so
        self.assertIn("zadnji poziv", html)           # data time, not render time


class StrategyCardLedger(unittest.TestCase):
    """P69: the 24 h / 7 d change is the research ledger's and is labelled so next to the no-borrowing replay."""

    def _st(self, **extra):
        s = {"key": "A", "name": "A", "icon": "x", "ret": 0.2, "value": 1200, "closed": 10, "open": 0, "hit": 0.3,
             "p15": 0.1, "opis": "opis", "status": ("uci", "uči", "još uči"), "robust": {}, "portfolio": {"value": 1150, "skipped": 0}}
        s.update(extra)
        return {"cfg": {"bankroll_usd": 1000}, "days": 8.0, "rank": [s]}

    def test_label_only_with_a_change(self):
        with mock.patch.object(pocetna, "strategies", return_value=self._st(d24=0.05)):
            html = pocetna.strategy_html()
        self.assertIn("zadnja 24 h", html)
        self.assertIn("(istraživačka knjiga)", html)
        self.assertIn("$1,150", html)                      # the main number stays the replay
        with mock.patch.object(pocetna, "strategies", return_value=self._st()):
            html = pocetna.strategy_html()
        self.assertNotIn("istraživačka knjiga)", html.split("<dialog")[0])


class TokensMarketAge(unittest.TestCase):
    """P83/P84: Mcap/Likv. from hype/tokenstatus (6-h job) show the age of the check and the 30k rule."""

    def test_stale_check_shows_its_age(self):
        st = {"has_pair": 1, "mcap": 80_000, "liq": 20_000, "checked_ts": NOW - 4 * 3600}
        txt, val, _ = tokens.market(st, 50_000, NOW)
        self.assertEqual(val, 80_000)
        self.assertIn("$80.0k", txt)
        self.assertIn("prije 4.0 h", txt)
        self.assertIn("Tržišna provjera", txt)
        self.assertNotIn("ispod 30k", txt)

    def test_fresh_check_has_no_age(self):
        txt, _, _ = tokens.market({"has_pair": 1, "mcap": 80_000, "checked_ts": NOW - 120}, 50_000, NOW)
        self.assertNotIn("<small", txt)

    def test_known_small_mcap_is_marked_unknown_is_not(self):
        txt, val, _ = tokens.market({"has_pair": 1, "mcap": 12_000, "checked_ts": NOW - 60}, 50_000, NOW)
        self.assertIn("ispod 30k", txt)
        self.assertEqual(val, 12_000)
        txt, _, _ = tokens.market(None, 25_000, NOW)        # the signal's own mcap, also known
        self.assertIn("ispod 30k", txt)
        txt, val, _ = tokens.market(None, None, NOW)
        self.assertEqual((txt, val), ("–", -1))
        txt, _, _ = tokens.market({"has_pair": 0, "checked_ts": NOW - 60}, 20_000, NOW)   # no pair: no mcap known
        self.assertIn("nema para", txt)
        self.assertNotIn("ispod 30k", txt)

    def test_table_says_last_signal(self):
        row = {"token": MINT, "symbol": "S", "conf": 40, "mcap": 50_000, "liq": 1000, "features": {}, "det": {},
               "conf_parts": [], "checks": [], "rug": None, "collapse": None, "last_seen": NOW - 60}
        with mock.patch.object(tokens, "_status", return_value={}):
            html = tokens._main_table([row], "tt", "", {}, NOW)
        self.assertIn("Zadnji signal", html)


class HoldersUnknown(unittest.TestCase):
    """Handoff izvori P56: a missing holder share is 'nepoznato', never a pass or +6 'zdravi holderi'."""

    def test_confidence_never_rewards_unknown(self):
        keys = {k: (p, t) for k, p, t in confidence.parts_keyed(50, {}, {"pumpfun": {"top10HoldersPercent": None,
                                                                                      "bundlerOwnedPercent": None}})}
        self.assertNotIn("holders_ok", keys)
        self.assertEqual(keys["holders_nepoznato"][0], 0)
        self.assertIn("nepoznato", keys["holders_nepoznato"][1])
        keys = {k: (p, t) for k, p, t in confidence.parts_keyed(50, {}, {"pumpfun": {"top10HoldersPercent": 20,
                                                                                      "bundlerOwnedPercent": None}})}
        self.assertIn("holders_nepoznato", keys)            # one share small, the other unknown: still no +6
        keys = {k: (p, t) for k, p, t in confidence.parts_keyed(50, {}, {"pumpfun": {"top10HoldersPercent": 60,
                                                                                      "bundlerOwnedPercent": None}})}
        self.assertIn("holders_conc", keys)                 # a known bad share is noted
        self.assertIn("bundleri nepoznato", keys["holders_conc"][1])
        keys = {k: (p, t) for k, p, t in confidence.parts_keyed(50, {}, {"pumpfun": {"top10HoldersPercent": 20,
                                                                                      "bundlerOwnedPercent": 5}})}
        self.assertEqual(keys["holders_ok"][0], 6)          # both known and small: as before

    def test_evidence_check_is_none_not_pass(self):
        self.assertIsNone(evidence._holders_ok({}))
        self.assertIsNone(evidence._holders_ok({"top10HoldersPercent": None, "bundlerOwnedPercent": None}))
        self.assertIsNone(evidence._holders_ok({"top10HoldersPercent": 20, "bundlerOwnedPercent": None}))
        self.assertFalse(evidence._holders_ok({"top10HoldersPercent": 50, "bundlerOwnedPercent": None}))
        self.assertTrue(evidence._holders_ok({"top10HoldersPercent": 20, "bundlerOwnedPercent": 5}))
        self.assertEqual(evidence._holders_txt({}), "nema podatka o holderima")
        self.assertIn("bundleri nepoznato", evidence._holders_txt({"top10HoldersPercent": 20, "bundlerOwnedPercent": None,
                                                                   "izvor": "RugCheck"}))
        self.assertIn("(RugCheck)", evidence._holders_txt({"top10HoldersPercent": 20, "izvor": "RugCheck"}))
        cs = dict((lab, ok) for lab, ok, _ in evidence.checks(MINT, {"score": 60, "features": "{}"},
                                                              {"pumpfun": {"top10HoldersPercent": None}}))
        self.assertIsNone(cs["Holderi"])

    def test_overview_fills_the_shape_from_topcheck_and_rug(self):
        tops = {"A": {"rc": json.dumps({"top10": 22.0, "dev_pct": 1.0, "insiders": 3.0})}}
        rugs = {"B": {"bundle_pct": 18.0, "sniper_pct": 4.0, "top10_pct": 40.0}, "C": {"bundle_pct": None, "sniper_pct": None, "top10_pct": None}}
        shape = overview._holder_shape(tops, rugs)
        self.assertEqual(shape["A"]["top10HoldersPercent"], 22.0)
        self.assertIsNone(shape["A"]["bundlerOwnedPercent"])       # unknown stays None
        self.assertEqual((shape["B"]["top10HoldersPercent"], shape["B"]["bundlerOwnedPercent"]), (40.0, 18.0))
        self.assertNotIn("C", shape)
        self.assertEqual(overview._holder_shape({}, {}), {})


class WalletsAutopilotMarks(unittest.TestCase):
    """P44: /wallets shows and sorts by the lists the bot copies by (proven twice, followed, Autopilot 14 d)."""

    def test_mark_cells(self):
        marks = {"proven": {"P": {"bags": 2, "as_of": NOW}}, "followed": {"F"},
                 "recs": {"P": {"roi": 0.4, "win": 0.6, "closed": 5}}, "as_of": NOW}
        p = pages._mark_cells("P", marks)
        self.assertIn("DA", p[0][0])
        self.assertIn("2 bagova", p[0][0])
        self.assertIn("ne", p[1][0])
        self.assertIn("+40%", p[2][0])
        self.assertIn("5 zatv.", p[2][0])
        f = pages._mark_cells("F", marks)
        self.assertEqual((f[0][1], f[1][1], f[2][0]), (0, 1, "–"))

    def test_marks_survive_missing_sources(self):
        with mock.patch("wallets.dokazani.latest", side_effect=OSError("no db")), \
                mock.patch("ui.pravitrade.followed_wallets", return_value={"F"}), \
                mock.patch("ui.autopilot.wallet_recs", return_value={}):
            m = pages.autopilot_marks()
        self.assertEqual((m["proven"], m["followed"], m["recs"], m["as_of"]), ({}, {"F"}, {}, None))

    def test_page_sorts_proven_and_followed_first(self):
        def w(addr, cs):
            return {"wallet": addr, "copy_score": cs, "score": cs, "tier": 1, "sources": {}, "labels": [],
                    "stats": {"closed_pnl_sol": 1.0, "win_rate": 0.5, "closed": 12, "median_hold_min": 30, "last_trade_days": 1}}
        ws = [w("BEST", 90), w("PROVEN", 60), w("FOLLOWED", 55)]
        marks = {"proven": {"PROVEN": {"as_of": NOW - 3600}}, "followed": {"FOLLOWED", "PROVEN"}, "recs": {}, "as_of": NOW - 3600}
        with mock.patch("ui.data.wallets", return_value=ws), mock.patch("ui.explain.shortlist", return_value=(True, [])), \
                mock.patch("ui.prijedlog.box", return_value=""), mock.patch("ui.preporuka.wallets_box", return_value=""), \
                mock.patch("ui.preporuka.copies_from_strat", return_value=[]), mock.patch("ui.jobs.status", return_value=(None, None, "")), \
                mock.patch.object(pages, "autopilot_marks", return_value=marks):
            title, html = pages.wallets({})
            _, html_all = pages.wallets({"v": "svi"})
        self.assertEqual(title, "Novčanici")
        self.assertIn("Dokazani dvaput", html)
        self.assertIn("Prati Autopilot", html)
        self.assertIn("lista iz prije 1.0 h", html)                                 # data time of the proven list
        self.assertLess(html.index("PROVEN"), html.index("FOLLOWED"))
        self.assertLess(html.index("FOLLOWED"), html.index("BEST"))
        self.assertLess(html_all.index("BEST"), html_all.index("PROVEN"))           # "Svi" keeps the copy_score order
        self.assertIn("Dokazani dvaput", html_all)


class SnapshotAge(unittest.TestCase):
    """Handoff pogon P33: a served-again old copy is not re-saved, so its age (SNAP_MAX_S) keeps counting."""

    def setUp(self):
        self.saved = (pagecache.SNAP_DIR, set(pagecache._snap_paths))
        pagecache.SNAP_DIR = tempfile.mkdtemp()
        pagecache._snap_paths.clear()
        pagecache._snap_paths.add("/pregled")

    def tearDown(self):
        pagecache.SNAP_DIR, paths = self.saved
        pagecache._snap_paths.clear()
        pagecache._snap_paths.update(paths)

    def test_same_content_keeps_the_old_mtime(self):
        key = ("/pregled", "", None)
        pagecache._save_snap(key, gzip.compress(b"<p>v1</p>", 5))
        f = pagecache._snap_file(key)
        old = time.time() - 6 * 3600
        os.utime(f, (old, old))
        pagecache._save_snap(key, gzip.compress(b"<p>v1</p>", 5, mtime=1))   # same page, different gzip header
        self.assertAlmostEqual(os.path.getmtime(f), old, delta=2)
        pagecache._save_snap(key, gzip.compress(b"<p>v2</p>", 5))
        self.assertGreater(os.path.getmtime(f), old + 3600)


if __name__ == "__main__":
    unittest.main()
