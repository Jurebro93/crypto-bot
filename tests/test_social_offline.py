"""19.11.2026. (vlasnik: "From now on I want the tool to stop spending resources on scraping influencers and Telegram
channels. That can be refreshed once every 5 days. What I want every day is wallets."): ops/drustveni.py, offline.

  - the window: the first one at the first start, 6 h, then every 5 days; survives a restart; env overrides;
    SOCIAL_ALWAYS=1; no persistent place = open
  - every gated job asks the gate and makes no paid call outside the window (stubs at the call seams: twitterapi,
    Apify, the AI labels, the Telegram reader), and runs inside it; one line a day per job
  - the ungated jobs (wallets, holders, midcap candles, the exit loop, real money, the council) never ask it
  - the notice on the influencer and Telegram pages (app and public, both languages), the daily cost part, the board

    python3 -m unittest tests.test_social_offline
"""
import importlib
import io
import json
import os
import re
import sqlite3
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from ops import drustveni  # noqa: E402

T0 = 1_794_903_960          # 17.11.2026. 08:26 UTC (a fixed clock)
H, D = 3600, 86400
FORBIDDEN = re.compile(r"\b[A-Z][A-Z0-9]+(?:_[A-Z0-9]+)+\b|Helius|Apify|twitterapi|xquik|OpenAI|Anthropic|Claude|DATA_DIR|"
                       r"drustveni|\$|[1-9A-HJ-NP-Za-km-z]{32,44}|API|Render|SQLite|\.db\b|\.json\b", re.I)


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.state = os.path.join(self.tmp.name, "drustveni.json")
        env = mock.patch.dict(os.environ, {"SOCIAL_STATE": self.state, "FOKUS_MIDCAP_FORCE": "0",
                                          # 27.11.: the window is abolished by default; its mechanics stay testable
                                          "SOCIAL_WINDOW": "1"})
        env.start()
        self.addCleanup(env.stop)
        for k in ("SOCIAL_EVERY_D", "SOCIAL_WINDOW_H", "SOCIAL_ALWAYS"):
            os.environ.pop(k, None)

    def open_at(self, t=T0):
        """The first window starts at t (the first start after the deploy)."""
        self.assertTrue(drustveni.social_open(t))

    def closed(self, t=T0):
        self.open_at(t)
        return t + 7 * H          # inside the gap after the first window

    def quiet(self):
        return redirect_stdout(io.StringIO())


class Window(Base):
    def test_first_start_six_hours_then_every_five_days(self):
        self.assertIsNone(drustveni.first_start(T0, create=False))
        self.assertEqual(drustveni.state(T0)["mode"], "first")                 # nothing yet: the first is pending
        self.assertTrue(drustveni.social_open(T0))                              # the first start opens it
        self.assertEqual(drustveni.first_start(create=False), T0)
        self.assertTrue(drustveni.social_open(T0 + 6 * H - 1))
        self.assertFalse(drustveni.social_open(T0 + 6 * H))
        self.assertFalse(drustveni.social_open(T0 + 5 * D - 1))
        self.assertTrue(drustveni.social_open(T0 + 5 * D))
        self.assertTrue(drustveni.social_open(T0 + 5 * D + 5 * H))
        self.assertFalse(drustveni.social_open(T0 + 5 * D + 6 * H))
        self.assertTrue(drustveni.social_open(T0 + 10 * D + 60))
        st = drustveni.state(T0 + 7 * D)
        self.assertEqual((st["mode"], st["last"], st["end"], st["next"]), ("closed", T0 + 5 * D, T0 + 5 * D + 6 * H, T0 + 10 * D))

    def test_a_later_start_does_not_move_it_and_it_survives_a_restart(self):
        self.open_at(T0)
        self.assertFalse(drustveni.social_open(T0 + D))                         # a deploy a day later: still closed
        self.assertEqual(drustveni.first_start(T0 + D), T0)
        with open(self.state) as f:
            self.assertEqual(json.load(f)["prvi"], T0)                          # on the persistent disk
        importlib.reload(drustveni)                                             # a new process
        self.assertFalse(drustveni.social_open(T0 + D))
        self.assertTrue(drustveni.social_open(T0 + 5 * D + 60))

    def test_the_state_lives_on_the_data_disk(self):
        os.environ.pop("SOCIAL_STATE")
        with mock.patch.dict(os.environ, {"DATA_DIR": self.tmp.name}):
            self.assertEqual(drustveni.path(), os.path.join(self.tmp.name, "drustveni.json"))
            self.open_at(T0)
            self.assertTrue(os.path.exists(os.path.join(self.tmp.name, "drustveni.json")))
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("DATA_DIR", None)
            self.assertIsNone(drustveni.path())
            self.assertTrue(drustveni.social_open(T0 + D))                      # no persistent place: today's behaviour
            self.assertEqual(drustveni.state(T0 + D)["mode"], "nopersist")

    def test_env_overrides_and_always(self):
        self.open_at(T0)
        with mock.patch.dict(os.environ, {"SOCIAL_EVERY_D": "2", "SOCIAL_WINDOW_H": "1"}):
            self.assertFalse(drustveni.social_open(T0 + H))
            self.assertTrue(drustveni.social_open(T0 + 2 * D + 30 * 60))
            self.assertEqual(drustveni.days_word(), "2")
        with mock.patch.dict(os.environ, {"SOCIAL_EVERY_D": "nonsense", "SOCIAL_WINDOW_H": "-3"}):
            self.assertEqual((drustveni.every_d(), drustveni.window_h()), (5.0, 6.0))
        with mock.patch.dict(os.environ, {"SOCIAL_ALWAYS": "1"}):
            self.assertTrue(drustveni.social_open(T0 + 2 * D))
            self.assertEqual(drustveni.state(T0 + 2 * D)["mode"], "always")
        self.assertFalse(drustveni.social_open(T0 + 2 * D))

    def test_one_line_a_day_per_job(self):
        t = self.closed()
        lines = []
        for k in range(5):
            self.assertFalse(drustveni.gate("tg", t + k * 600, log=lines.append))
        self.assertEqual(lines, ["tg: osvježavanje influencera i Telegrama je jednom u 5 dana; sljedeće "
                                 + drustveni.when(T0 + 5 * D)])
        self.assertFalse(drustveni.gate("postai", t, log=lines.append))         # another job: its own line
        self.assertEqual(len(lines), 2)
        self.assertFalse(drustveni.gate("tg", t + D, log=lines.append))         # the next UTC day
        self.assertEqual(len(lines), 3)
        self.assertTrue(drustveni.gate("tg", T0 + 5 * D + 60, log=lines.append))   # open: no line
        self.assertEqual(len(lines), 3)
        buf = io.StringIO()
        with redirect_stdout(buf):
            drustveni.gate("makroinf", t)
        self.assertRegex(buf.getvalue(), r"^makroinf: osvježavanje influencera i Telegrama je jednom u 5 dana; sljedeće "
                                         r"\d\d\.\d\d\.\d{4}\. \d\d:\d\d UTC\n$")

    def test_an_unreadable_state_is_open(self):
        with mock.patch.object(drustveni, "state", side_effect=OSError("disk")):
            self.assertTrue(drustveni.gate("tg", T0))

    def test_start_line(self):
        self.open_at(T0)
        self.assertIn("prozor otvoren", drustveni.line(T0 + H))
        self.assertEqual(drustveni.line(T0 + 7 * H), "društveni izvori: prozor zatvoren (sljedeći 22.11.2026. 08:26 UTC)")


class GatedCommands(Base):
    """The command lines started through ops.heavy / run_sched / directly end at once outside the window."""
    SOCIAL = (["run_learn.py", "postai"], ["-m", "kol.zadnjih5", "night"], ["run_konsenzus.py", "once"],
              ["run_makroinf.py", "krug"], ["run_makroinf.py", "noc"], ["run_veliki.py", "moc"],
              ["kol/backfill_calls.py", "--budget", "60"], ["run_kol.py", "search-round"], ["run_kol.py", "backfill"])
    KEPT = (["run_wallets.py", "score"], ["run_wallets.py", "kopija", "--night"], ["run_holderi.py", "pass"],
            ["run_veliki.py", "candles"], ["run_veliki.py", "once"], ["run_veliki.py", "night"],
            ["run_veliki.py", "midcap"], ["run_veliki.py", "replay"], ["run_veliki.py", "nauceno"],
            ["run_trade.py", "follow"], ["run_vijece.py", "tick"], ["run_critic.py", "trades"], ["run_kol.py", "loop"],
            ["run_kol.py", "once"], ["run_insajderi.py", "night"], ["run_usage.py", "dnevno"], ["run_web.py", "daily"])

    def test_heavy_main_skips_social_jobs_before_the_lock(self):
        from ops import heavy
        t = self.closed()
        with mock.patch.object(drustveni.time, "time", return_value=t), \
                mock.patch.object(heavy, "run") as run, mock.patch.object(heavy, "wait_for_night") as night, self.quiet():
            for argv in self.SOCIAL:
                self.assertEqual(heavy.main(["--night"] + argv), 0, argv)
            self.assertFalse(run.called)
            self.assertFalse(night.called)
        with mock.patch.object(drustveni.time, "time", return_value=T0 + 5 * D + 60), \
                mock.patch.object(heavy, "run") as run, mock.patch.object(heavy, "night_now", return_value=True):
            run.return_value.returncode = 0
            heavy.main(["run_veliki.py", "moc"])
            self.assertTrue(run.called)                                        # inside the window: as today

    def test_run_sched_skips_postai_and_kolfill(self):
        import run_sched
        from ops import heavy
        t = self.closed()
        with mock.patch.object(drustveni.time, "time", return_value=t), mock.patch.object(heavy, "run") as hrun, \
                mock.patch.object(run_sched.subprocess, "run") as srun, self.quiet():
            self.assertEqual(run_sched.run("postai", ["run_learn.py", "postai"], light=True), 0)
            self.assertEqual(run_sched.run("kolfill", ["kol/backfill_calls.py", "--budget", "60"]), 0)
            self.assertFalse(hrun.called or srun.called)
            srun.return_value.returncode = 0
            run_sched.run("usage", ["run_usage.py", "tick"], light=True)       # not a social job
            self.assertTrue(srun.called)

    def test_runners_exit_at_once(self):
        t = self.closed()
        with mock.patch.object(drustveni.time, "time", return_value=t), self.quiet():
            for argv in self.SOCIAL:
                with self.assertRaises(SystemExit) as e:
                    drustveni.gate_main(["python3"] + argv)
                self.assertEqual(e.exception.code, 0)
        for path in ("run_makroinf.py", "run_konsenzus.py", "kol/zadnjih5.py", "run_veliki.py", "kol/backfill_calls.py",
                     "run_learn.py", "run_kol.py"):   # 19.11.: run_tg.py is the weekly follower count, not gated
            src = open(os.path.join(ROOT, path), encoding="utf-8").read()
            self.assertIn("drustveni.gate_main()", src.split('if __name__ == "__main__":')[-1], path)

    def test_ungated_jobs_never_ask(self):
        t = self.closed()
        with mock.patch.object(drustveni, "gate") as g:
            for argv in self.KEPT:
                self.assertIsNone(drustveni.skip_cmd(["python3"] + argv, t), argv)
            self.assertFalse(g.called)
        for path in ("run_wallets.py", "run_holderi.py", "run_trade.py", "run_vijece.py", "league/auto.py", "run_critic.py",
                     "veliki/live.py", "veliki/replay.py", "veliki/nauceno.py", "wallets/kopija.py", "run_insajderi.py"):
            p = os.path.join(ROOT, path)
            if os.path.exists(p):
                self.assertNotIn("drustveni", open(p, encoding="utf-8").read(), path)


class KolRound(Base):
    def test_outside_the_window_the_round_is_the_wallet_part(self):
        import run_kol
        self.assertEqual(run_kol.round_steps(full=False, social=False), run_kol.WALLET_DAY_STEPS)
        self.assertEqual(run_kol.round_steps(full=True, social=False), run_kol.WALLET_NIGHT_STEPS)
        self.assertEqual(run_kol.round_steps(full=False, social=True), run_kol.DAY_STEPS)
        self.assertEqual(run_kol.round_steps(full=True, social=True), run_kol.NIGHT_STEPS)
        for steps in (run_kol.WALLET_DAY_STEPS, run_kol.WALLET_NIGHT_STEPS):
            self.assertIn("cmd_chain", steps)                                   # the wallet webhook list stays
            for social in ("cmd_snap", "cmd_converge", "cmd_crew", "cmd_score", "cmd_measure", "cmd_deleted"):
                self.assertNotIn(social, steps)
        self.assertIn("cmd_flows", run_kol.WALLET_NIGHT_STEPS)

    def _loop(self, t):
        import run_kol
        from ops import heavy
        calls = []

        class Stop(Exception):
            pass

        def sleep(_s):
            raise Stop

        a = mock.Mock(verbose=False, every=20)
        with mock.patch.object(drustveni.time, "time", return_value=t), \
                mock.patch.object(heavy, "run", side_effect=lambda cmd, **k: calls.append(("heavy", cmd[-1]))), \
                mock.patch("subprocess.run", side_effect=lambda cmd, **k: calls.append(("plain", cmd[-1]))), \
                mock.patch.object(heavy, "night_now", return_value=False), mock.patch.object(run_kol.time, "sleep", sleep), \
                mock.patch.object(run_kol.store, "connect", return_value=mock.Mock()), \
                mock.patch.object(run_kol.store, "import_seed", return_value=0), self.quiet():
            with self.assertRaises(Stop):
                run_kol.cmd_loop(a)
        return calls

    def test_the_loop_skips_the_search_round_and_the_lock(self):
        t = self.closed()
        self.assertEqual(self._loop(t), [("plain", "once")])                   # no search round, no heavy lock by day
        self.assertEqual(self._loop(T0 + 5 * D + 60), [("heavy", "once"), ("plain", "search-round")])

    def test_x_push_rules_keep_only_the_real_money_follows(self):
        from kol import store as kstore, xhook
        con = kstore.connect(os.path.join(self.tmp.name, "kol.db"))
        self.addCleanup(con.close)
        con.execute("INSERT INTO kols (handle, score, followers, bot) VALUES ('top1', 80, 5000, 0)")
        con.execute("INSERT INTO watch (handle, score) VALUES ('top1', 80)")
        con.commit()
        calls, rules = [], {"rules": [{"rule_id": "R1", "tag": "memesonar-1", "value": "from:top1"}]}

        def api(method, path, body=None):
            calls.append((path, body))
            return rules if path == "get_rules" else {"status": "success"}
        cfg = json.load(open(os.path.join(ROOT, "kol", "config.json")))
        with mock.patch.dict(os.environ, {"RENDER_EXTERNAL_URL": "https://x.example", "KOL_HOOK_KEY": "k"}), \
                mock.patch.object(xhook, "followed", return_value=[]):
            self.assertTrue(xhook.sync(con, cfg, api=api, now=T0, log=lambda s: None, only_followed=True))
        self.assertEqual([c for c in calls if c[0] == "add_rule"], [])
        self.assertEqual([(c[1]["rule_id"], c[1]["is_effect"]) for c in calls if c[0] == "update_rule"], [("R1", 0)])
        calls.clear()
        with mock.patch.dict(os.environ, {"RENDER_EXTERNAL_URL": "https://x.example", "KOL_HOOK_KEY": "k"}), \
                mock.patch.object(xhook, "followed", return_value=["realfollow"]):
            xhook.sync(con, cfg, api=api, now=T0 + 60, log=lambda s: None, only_followed=True)
        values = [c[1]["value"] for c in calls if c[0] in ("add_rule", "update_rule") and c[1].get("is_effect", 1)]
        self.assertTrue(values and all(v == "from:realfollow" for v in values))
        import run_kol
        t = self.closed()
        with mock.patch.object(drustveni.time, "time", return_value=t), mock.patch.object(xhook, "sync") as sync, self.quiet():
            run_kol.cmd_xhook(None, con, cfg)
        self.assertTrue(sync.call_args.kwargs["only_followed"])

    def test_the_apify_monitor_is_stopped_once(self):
        from kol import live, store as kstore
        from hype import apify
        con = kstore.connect(os.path.join(self.tmp.name, "kol.db"))
        self.addCleanup(con.close)
        con.execute("INSERT INTO watch (handle, score) VALUES ('top1', 80)")
        con.execute("INSERT INTO monitor VALUES ('top1', ?, ?)", (T0 - 3600, T0 - 3600))
        con.commit()
        mon = mock.Mock()
        import run_kol
        t = self.closed()
        with mock.patch.object(live, "hook_url", return_value="https://x.example/hook/kol?key=k"), \
                mock.patch.object(apify, "enabled", return_value=True), \
                mock.patch("hype.sources.kol_monitor", mon), mock.patch.object(drustveni.time, "time", return_value=t), \
                self.quiet():
            run_kol.cmd_live(None, con, {"watch": {"resync_h": 6}})
            run_kol.cmd_live(None, con, {"watch": {"resync_h": 6}})
        self.assertEqual(mon.call_count, 1)                                     # stopped once, then nothing
        self.assertTrue(mon.call_args.kwargs["stop"])
        with mock.patch.object(live, "hook_url", return_value="https://x.example/hook/kol?key=k"), \
                mock.patch.object(apify, "enabled", return_value=True), \
                mock.patch("hype.sources.kol_monitor", mon), \
                mock.patch.object(drustveni.time, "time", return_value=T0 + 5 * D + 60), self.quiet():
            run_kol.cmd_live(None, con, {"watch": {"resync_h": 6}})
        self.assertEqual(mon.call_count, 2)                                     # the window: started again
        self.assertFalse(mon.call_args.kwargs.get("stop"))


class Seams(Base):
    """The paid call seams: twitterapi.io (X momentum, deleted posts), the AI labels, the Telegram reader."""

    def test_x_momentum_twitterapi(self):
        from kol import twapi
        from scan import xmom
        from veliki import midcap
        con = midcap.connect(os.path.join(self.tmp.name, "midcap.db"))
        self.addCleanup(con.close)
        con.execute("INSERT INTO tokens (mint, symbol, member, vol24) VALUES ('M1', 'AAA', 1, 5e6)")
        con.commit()
        c = {"x_pass": 3, "x_every_min": 60}
        with mock.patch.object(twapi, "key", return_value="k"), \
                mock.patch.object(xmom, "measure", return_value={"usd": 0.01}) as m, \
                mock.patch.object(xmom, "known_handles", return_value=(set(), set())), \
                mock.patch("veliki.midcap.ROOT", self.tmp.name), self.quiet():
            t = self.closed()
            self.assertEqual(midcap.xmom_pass(con, c, t), 0.0)
            self.assertFalse(m.called)
            self.assertGreater(midcap.xmom_pass(con, c, T0 + 5 * D + 60), 0)
            self.assertTrue(m.called)
        from scan import market
        with mock.patch.object(twapi, "key", return_value="k"), self.quiet():
            self.assertEqual(market.x_momentum(None, {}, t, {}, None), 0.0)     # returns before reading anything

    def test_deleted_posts_twitterapi(self):
        from kol import deleted
        t = self.closed()
        seen = []

        class Stop(BaseException):
            pass

        for now, want in ((t, 0), (T0 + 5 * D + 60, 1)):
            seen.clear()
            deleted._THREAD["t"] = None
            with mock.patch.object(deleted, "flash_round", side_effect=lambda *a, **k: seen.append(1)), \
                    mock.patch("threading.excepthook", lambda args: None), \
                    mock.patch.object(drustveni.time, "time", return_value=now), self.quiet():
                th = deleted.start_flash_thread({}, log=lambda *a, **k: None,
                                                sleep=lambda s: (_ for _ in ()).throw(Stop()))
                th.join(5)
            self.assertEqual(len(seen), want)
        deleted._THREAD["t"] = None

    def test_ai_labels(self):
        import run_learn
        from learn import postai
        t = self.closed()
        with mock.patch.object(postai, "step", return_value={}) as step, \
                mock.patch.object(drustveni.time, "time", return_value=t), self.quiet():
            run_learn.cmd_postai(None)
            self.assertFalse(step.called)
        with mock.patch.object(postai, "step", return_value={}) as step, \
                mock.patch.object(drustveni.time, "time", return_value=T0 + 5 * D + 60), self.quiet():
            run_learn.cmd_postai(None)
            self.assertTrue(step.called)
        src = open(os.path.join(ROOT, "run_learn.py"), encoding="utf-8").read()
        self.assertIn('if drustveni.gate("detektiv"):\n                print(f"detektiv: {detektiv.propose()}")', src)

    def test_minute_candles_stop_but_the_autopilots_skips_stay(self):
        from kol import minute, preskoceni, store as kstore
        for now, want in ((self.closed(), 0), (T0 + 5 * D + 60, 1)):
            with mock.patch.object(kstore, "ro", return_value=mock.Mock()), \
                    mock.patch.object(minute, "connect", return_value=mock.Mock()), \
                    mock.patch.object(minute, "run", return_value=(0, 0, 0)) as run, \
                    mock.patch.object(minute, "hot", return_value={"x": [], "tg": [], "wallets": []}), \
                    mock.patch("kol.tpsl.save_pool"), \
                    mock.patch.object(preskoceni, "maybe_run") as skips, \
                    mock.patch.object(drustveni.time, "time", return_value=now), self.quiet():
                minute.loop({}, log=lambda *a, **k: None, once=True, fetch=lambda *a: [])
            self.assertEqual(run.call_count, want)
            self.assertEqual(skips.call_count, 1)


class Notice(Base):
    def _check(self, html, lang, last, nxt):
        self.assertEqual(html.count("soc-note"), 1)
        if lang == "hr":
            self.assertIn("Od 19.11.2026. ovi se podaci osvježavaju jednom u 5 dana. Sve resurse usmjerili smo na "
                          "pronalaženje profitabilnih novčanika, jer smatramo da je tu najveća poluga koju ovi podaci daju. "
                          f"Zadnje osvježavanje: {last}. Sljedeće: {nxt}.", html)
        else:
            self.assertIn("Since 19 Nov 2026 this data is refreshed once every 5 days. All resources now go to finding "
                          "profitable wallets, because we believe that is where this data gives the most leverage. "
                          f"Last refresh: {last}. Next: {nxt}.", html)
        note = re.search(r'<div class="[^"]*soc-note"[^>]*>(.*?)</div>', html, re.S).group(1)
        self.assertIsNone(FORBIDDEN.search(note), note)

    def test_texts_and_first_refresh(self):
        self.assertIn("Prvo osvježavanje je u tijeku.", drustveni.notice_text("hr", T0))
        self.assertIn("First refresh in progress.", drustveni.notice_text("en", T0))
        self.open_at(T0)
        self.assertTrue(drustveni.notice_text("hr", T0 + D).endswith("Zadnje osvježavanje: 17.11.2026. Sljedeće: 22.11.2026."))
        self.assertTrue(drustveni.notice_text("en", T0 + D).endswith("Last refresh: 17 Nov 2026. Next: 22 Nov 2026."))
        self.assertIn('translate=no', drustveni.notice_html("en"))
        self.assertNotIn('translate=no', drustveni.notice_html("hr", notr=False))
        with mock.patch.object(drustveni, "notice_text", return_value="<script>x</script>"):
            self.assertIn("&lt;script&gt;", drustveni.notice_html("hr"))       # escaped

    def test_public_pages_both_languages(self):
        from tests import test_marketpub_offline as base
        from ui import marketpub as M, public
        self.open_at(T0)
        base.MarketPub.setUpClass()
        self.addCleanup(base.MarketPub.tearDownClass)
        from tests import test_public_offline as pub
        kol_lb = pub._db()                     # the leaderboard's own fixture (the market one has no kols.name)
        with mock.patch.object(drustveni.time, "time", return_value=T0 + D):
            # 19.11.: the Telegram pages are the weekly follower list now (no 5-day notice; tests/test_telegram_1911)
            for paths in (("/influencers", "/hr/influenceri"), M.PAGES["calls"]):
                for path, lang in zip(paths, ("en", "hr")):
                    public._cache.clear()
                    with mock.patch.dict(os.environ, {"KOL_DB": kol_lb} if "influencers" in path or "influenceri" in path
                                         else {}):
                        code, raw, _ct = public.route(path)
                    self.assertEqual(code, 200, path)
                    html = raw.decode()
                    if lang == "hr":
                        self._check(html, lang, "17.11.2026", "22.11.2026")
                    else:
                        self._check(html, lang, "17 Nov 2026", "22 Nov 2026")
        public._cache.clear()

    def test_app_pages_and_their_english(self):
        from ui import i18n, kol as kolpage
        self.open_at(T0)
        with mock.patch.object(drustveni.time, "time", return_value=T0 + D), \
                mock.patch.object(kolpage.store, "ro", return_value=None):
            _t, html_kol = kolpage.page({})
        for html in (html_kol,):   # 19.11.: /izvori redirects to /telegram-kanali (ui/tgkanali.py)
            self.assertEqual(html.count("soc-note"), 1)
            self.assertIn("Zadnje osvježavanje: 17.11.2026. Sljedeće: 22.11.2026.", html)
            note = re.search(r'<div class="[^"]*soc-note"[^>]*>(.*?)</div>', html, re.S).group(1)
            self.assertIsNone(FORBIDDEN.search(note), note)
        self.assertLess(html_kol.index("soc-note"), html_kol.index("još nema podataka"))   # at the top of the card
        tok = i18n.LANG.set("en")
        try:
            with mock.patch.object(i18n, "_start_worker"), mock.patch.object(drustveni.time, "time", return_value=T0 + D):
                en = i18n.translate(f"<html><body>{drustveni.notice_html('hr', notr=False)}</body></html>")
        finally:
            i18n.LANG.reset(tok)
        self.assertIn("Since 19.11.2026 this data is refreshed once every 5 days. All resources now go to finding "
                      "profitable wallets, because we believe that is where this data gives the most leverage. "
                      "Last refresh: 17.11.2026. Next: 22.11.2026.", en)


class CostLineAndBoard(Base):
    def test_daily_cost_part(self):
        from usage import daily
        self.open_at(T0)
        d = {"day": "2026-11-17", "drustveni": daily.drustveni(T0 + 7 * H)}
        self.assertIn("društveni izvori: prozor zatvoren (sljedeći 22.11.2026. 08:26 UTC)", daily.line(d))
        d = {"day": "2026-11-17", "drustveni": daily.drustveni(T0 + H)}
        self.assertIn("društveni izvori: prozor otvoren (do 17.11.2026. 14:26 UTC, sljedeći 22.11.2026. 08:26 UTC)",
                      daily.line(d))
        with mock.patch.object(daily, "_paths", return_value={}):
            self.assertIn("drustveni", daily.collect(T0 + 7 * H, {}))

    def test_the_board_and_the_registry(self):
        from stanja import ploca, provjera, registar
        self.assertIn("social_window", registar.BY_KEY)
        self.assertTrue(registar.BY_KEY["social_window"].board)
        self.assertEqual(provjera.drift(registar.MACHINES), [])
        self.open_at(T0)
        db = os.path.join(self.tmp.name, "trade.db")
        from trade import settings
        settings.connect(db).close()
        with mock.patch("veliki.makro.current", return_value=None), \
                mock.patch("veliki.live.btc_state", return_value={"state": "normalno", "known": True}):
            rows = {r["key"]: r for r in ploca.now(T0 + 7 * H, trade_db=db, env={})}
        r = rows["social_window"]
        self.assertEqual(r["state"], "<closed>")
        self.assertIn("sljedeći 22.11.2026. 08:26 UTC", r["detail"])
        self.assertEqual(r["since"], T0)


if __name__ == "__main__":
    unittest.main()
