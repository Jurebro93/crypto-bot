"""Hitno disk (12.11., Jure: "Disk je 80 % pun ... Oslobodi prostor sigurnim koracima, bez brisanja naših tradeova,
swapova, exit planova, bilješki ni povijesti praćenih novčanika"):
  a) VACUUM of events.db and hype.db once a night after 04:00 Zagreb, only with room (ops/retencija.compact_night);
  b) the HTTP cache: a file goes once no reader can use it (its TTL class), files from before after 24 h, paid Helius
     answers kept (event_calendar/http);
  c) live_trades_retention switched on by the owner's order (ui/assistnotes.OWNER_FLAG_ORDERS);
  d) log rotation: 7 days / 200 MB, gzip (ops/logrot);
  2) the disk guard: warning at 75 % or under 3 days, b) + d) by itself above 85 % (ops/diskguard).

    python3 -m unittest tests.test_disk_hitno_offline
"""
import datetime as dt
import gzip
import json
import os
import sys
import tempfile
import time
import unittest
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from event_calendar import http  # noqa: E402
from ops import diskguard, logrot, retencija  # noqa: E402

ZG = ZoneInfo("Europe/Zagreb")
T0 = 1_790_000_000.0


def zg(h, m=0):
    return int(dt.datetime(2026, 11, 13, h, m, tzinfo=ZG).timestamp())


def touch(path, data=b"x", age=0):
    with open(path, "wb") as f:
        f.write(data)
    t = time.time() - age
    os.utime(path, (t, t))
    return path


class Cache(unittest.TestCase):
    def setUp(self):
        self.saved = http.CACHE_DIR
        self.tmp = tempfile.TemporaryDirectory()
        http.CACHE_DIR = self.tmp.name

    def tearDown(self):
        http.CACHE_DIR = self.saved
        self.tmp.cleanup()

    def test_class_names_and_reads_of_the_old_name(self):
        self.assertEqual(http.ttl_class(20), "s")
        self.assertEqual(http.ttl_class(21600), "m")
        self.assertEqual(http.ttl_class(86400), "l")
        self.assertEqual(http.ttl_class(7 * 86400), "w")
        self.assertEqual(http.ttl_class(None), "s")
        http.cache_put("k", {"a": 1}, ttl=7 * 86400)
        self.assertEqual(os.listdir(http.CACHE_DIR)[0][:2], "w-")
        self.assertEqual(http.cache_get("k", 7 * 86400), {"a": 1})
        import hashlib
        legacy = os.path.join(http.CACHE_DIR, hashlib.sha1(b"old").hexdigest() + ".json")
        touch(legacy, b'{"b": 2}', age=10)
        self.assertEqual(http.cache_get("old", 60), {"b": 2})          # a file from before is still read

    def test_prune_by_what_a_reader_can_still_use(self):
        d = http.CACHE_DIR
        keep = [touch(os.path.join(d, "s-a.json"), age=1800),           # 20 s - 1 h TTL, 30 min old: still usable
                touch(os.path.join(d, "l-b.json"), age=20 * 3600),
                touch(os.path.join(d, "w-c.json"), age=3 * 86400),       # Helius first transactions: a week
                touch(os.path.join(d, "0" * 40 + ".json"), b'[{"signature": "x", "feePayer": "y"}]', age=3 * 86400),
                touch(os.path.join(d, "1" * 40 + ".json"), age=3600)]     # from before, under 6 h
        gone = [touch(os.path.join(d, "s-d.json"), age=2 * 3600),         # no reader takes it any more
                touch(os.path.join(d, "m-e.json"), age=7 * 3600),
                touch(os.path.join(d, "l-f.json"), age=25 * 3600),
                touch(os.path.join(d, "2" * 40 + ".json"), b'{"pairs": []}', age=7 * 3600),    # DexScreener, old
                touch(os.path.join(d, "rpc-g.json"), age=7200)]
        n, _mb = http.prune()
        self.assertEqual(n, len(gone))
        self.assertEqual(sorted(os.listdir(d)), sorted(os.path.basename(p) for p in keep))


class Logs(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.out = os.path.join(self.tmp.name, "output")
        os.makedirs(os.path.join(self.out, "paper"))
        self.st = os.path.join(self.tmp.name, "data")
        os.makedirs(self.st)

    def tearDown(self):
        self.tmp.cleanup()

    def test_rotate_gzip_truncate_delete_old_keep_journal(self):
        big = os.path.join(self.out, "job-x.log")
        with open(big, "wb") as f:
            f.write(b"line\n" * 300_000)                                  # 1.5 MB: rotated on the first pass
        journal = os.path.join(self.out, "paper", "journal.log")
        touch(journal, b"KUPI demo\n")
        old = touch(os.path.join(self.out, "job-y.log.20261101-0000.gz"), b"z", age=8 * 86400)
        old_j = touch(os.path.join(self.out, "paper", "journal.log.20261101-0000.gz"), b"z", age=30 * 86400)
        out = logrot.rotate(dirs=(self.out,), data_dir=self.st, log=lambda s: None)
        self.assertEqual(out["rotated"], 1)
        self.assertEqual(os.path.getsize(big), 0)                         # truncated in place: the writer goes on
        arc = [n for n in os.listdir(self.out) if n.startswith("job-x.log.") and n.endswith(".gz")]
        self.assertEqual(len(arc), 1)
        with gzip.open(os.path.join(self.out, arc[0])) as f:
            self.assertEqual(f.read().count(b"line\n"), 300_000)
        self.assertFalse(os.path.exists(old))                             # older than 7 days
        self.assertTrue(os.path.exists(old_j))                            # demo journal archives stay
        self.assertTrue(os.path.getsize(journal) > 0)                     # small log: its day starts now
        out = logrot.rotate(now=time.time() + 86400 + 60, dirs=(self.out,), data_dir=self.st, log=lambda s: None)
        self.assertEqual(out["rotated"], 1)                               # a day later: the journal is rotated
        self.assertEqual(os.path.getsize(journal), 0)

    def test_size_cap(self):
        saved = logrot.MAX_MB
        logrot.MAX_MB = 0.001
        try:
            a = touch(os.path.join(self.out, "a.log.20261110-0000.gz"), b"x" * 800, age=2 * 86400)
            b = touch(os.path.join(self.out, "a.log.20261111-0000.gz"), b"x" * 800, age=86400)
            logrot.rotate(dirs=(self.out,), data_dir=self.st, log=lambda s: None)
            self.assertFalse(os.path.exists(a))                          # the oldest first
            self.assertTrue(os.path.exists(b))
        finally:
            logrot.MAX_MB = saved


class Guard(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.lines, self.cleaned, self.tg = [], [], []

    def tearDown(self):
        self.tmp.cleanup()

    def run_check(self, used_pct, growth=None, now=T0):
        total = 5_000_000_000
        used = int(total * used_pct / 100)
        return diskguard.check(now=now, log=self.lines.append, data_dir=self.tmp.name, use=(used, total - used, total),
                               growth=growth, clean=lambda log: self.cleaned.append(1) or (120.0, 3.0),
                               telegram=lambda t: self.tg.append(t) or True)

    def test_quiet_below_thresholds(self):
        out = self.run_check(60, growth=100)                             # 2 GB free / 100 MB a day = 20 days
        self.assertFalse(out["warn"])
        self.assertEqual(self.lines, [])

    def test_warning_at_75_or_under_3_days_once_an_hour(self):
        out = self.run_check(75)
        self.assertTrue(out["warn"])
        self.assertIn("disk UPOZORENJE", self.lines[0])
        self.assertEqual(len(self.tg), 1)
        self.run_check(75, now=T0 + 600)                               # 10 min later: no second line
        self.assertEqual(len(self.lines), 1)
        self.lines.clear()
        out = self.run_check(50, growth=1000, now=T0 + 7200)           # 2.5 GB free at 1 GB a day: 2.5 days
        self.assertTrue(out["warn"])
        self.assertIn("pun za ~2.5 dana", self.lines[0])
        self.assertEqual(self.cleaned, [])                               # only a warning under 85 %

    def test_auto_clean_above_85_every_half_hour(self):
        out = self.run_check(86)
        self.assertEqual(out["auto"], {"cache_mb": 120.0, "logs_mb": 3.0})
        self.assertEqual(len(self.cleaned), 1)
        self.run_check(86, now=T0 + 600)
        self.assertEqual(len(self.cleaned), 1)
        self.run_check(86, now=T0 + 1900)
        self.assertEqual(len(self.cleaned), 2)
        self.assertTrue(any("automatski očišćen cache" in ln for ln in self.lines))


class NightCompact(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.p = {}
        for k in ("events", "hype"):
            self.p[k] = touch(os.path.join(self.tmp.name, f"{k}.db"), b"x")
        self.calls, self.lines = [], []

    def tearDown(self):
        self.tmp.cleanup()

    def fake(self, path, min_waste, margin_mb, why):
        self.calls.append((os.path.basename(path), min_waste, margin_mb))
        if path.endswith("hype.db"):
            why.append("premalo mjesta: treba 1445 MB slobodno, ima 1300")
            return None
        return "events.db 664->600 MB (40 s)"

    def test_once_a_night_after_four_with_room_and_reason(self):
        from unittest import mock
        with mock.patch.object(retencija, "in_night", lambda now=None, default=True: True):
            st = {}
            self.assertFalse(retencija.compact_due(st, zg(2, 30)))      # before the events night batch is done
            self.assertTrue(retencija.compact_due(st, zg(4, 5)))
            self.assertFalse(retencija.compact_due(st, zg(5, 45)))      # too close to 06:00
            out = retencija.compact_night(self.p, zg(4, 5), self.lines.append, st, compact=self.fake)
            self.assertEqual(self.calls, [("events.db", 0.10, 250.0), ("hype.db", 0.10, 250.0)])
            self.assertIn("600 MB", out["events"])
            self.assertIn("premalo mjesta", out["hype"])
            self.assertIn("noćno sažimanje", self.lines[0])
            self.assertFalse(retencija.compact_due(st, zg(4, 30)))      # once a night

    def test_compact_margin_and_reason(self):
        from ops import dbs
        from unittest import mock
        why = []
        with mock.patch.object(dbs, "waste", lambda p: 0.2), mock.patch.object(dbs.os.path, "getsize",
                                                                             lambda p: 1_000_000_000), \
                mock.patch.object(dbs.disk, "free_mb", lambda *a: 900.0):
            self.assertIsNone(dbs.compact("/x/hype.db", min_waste=0.10, margin_mb=250, why=why))
        self.assertIn("treba 1050 MB", why[0])                           # 800 MB packed + 250 margin


class OwnerOrder(unittest.TestCase):
    def test_live_trades_retention_goes_live_by_the_owners_order(self):
        from ui import assistnotes
        self.assertIn(("live_trades_retention", "live"), [(n, m) for n, m, _w in assistnotes.OWNER_FLAG_ORDERS])
        from trade import settings
        self.assertIn("live_trades_retention", settings.OWNER_SWITCHES)  # "live" is allowed only for owner switches
        self.assertNotIn(("tg_text_retention", "live"), [(n, m) for n, m, _w in assistnotes.OWNER_FLAG_ORDERS])
        self.assertNotIn(("rug_labels_v2_ok", "live"), [(n, m) for n, m, _w in assistnotes.OWNER_FLAG_ORDERS])


if __name__ == "__main__":
    unittest.main()
