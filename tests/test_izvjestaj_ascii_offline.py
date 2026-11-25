"""25.11. (vlasnik: the report attachment opened from the Gmail app on Android, content://com.google.android.gm...,
shows „nov?anika", „ka?njenja", „stop ?20 %"): every way the morning report's HTML leaves the service is plain ASCII
with numeric character references, <meta charset="utf-8"> kept; the plain-text part stays UTF-8. Offline.

  - run_report.build: the saved file output/report-YYYY-MM-DD.html and what it hands to the e-mail / the dump
  - report/dump: the REPORT-B64 lines, also for a file saved before this fix (the restart re-dump)
  - ui/reportpage.raw (/izvjestaj/raw/<day>: the iframe, a download or share), also for an old UTF-8 file
  - report/mail: the HTML part ASCII, the plain-text part UTF-8 letters (not &#269;)
  - a carrier that re-encodes the file as Latin-1 changes nothing: html.unescape of it gives the letters back

    python3 -m unittest tests.test_izvjestaj_ascii_offline
"""
import html
import os
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import run_report  # noqa: E402
from report import dump, mail  # noqa: E402

NOW = 1795593600   # 25.11.2026 15:00 UTC
TITLE = "Novčanici: kašnjenje, stop −20 %, ćevapi, đak, žaba, Šibenik"


class Ascii(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        for k, v in (("OUT", self.tmp.name), ("STATE", os.path.join(self.tmp.name, "s.json"))):
            p = mock.patch.object(run_report, k, v)
            p.start()
            self.addCleanup(p.stop)

    def build(self):
        data = {"ts": NOW, "fokus": True, "midcap": {}}
        with mock.patch.object(run_report.collect, "collect", return_value=data), \
                mock.patch.object(run_report.ai, "fallback", return_value={"naslov": TITLE}):
            return run_report.build(use_ai=False, now=NOW, weekly=False)

    def check(self, text):
        self.assertTrue(text.isascii())
        self.assertIn("&#269;", text)                                     # č
        self.assertIn("&#8722;", text)                                    # − (the minus of „stop −20 %")
        self.assertIn('<meta charset="utf-8">', text)
        # a carrier that turns it into Latin-1 bytes and a browser that reads them: the letters come back
        back = html.unescape(text.encode("latin-1").decode("latin-1"))
        self.assertIn(html.escape(TITLE, quote=False), back)
        self.assertIn("Jutarnji izvještaj", back)

    def test_the_saved_file_and_what_build_hands_on(self):
        day, path, out, _i, _s = self.build()
        self.check(out)
        with open(path, "rb") as f:
            raw = f.read()
        self.assertEqual(raw, out.encode("ascii"))
        self.check(raw.decode("ascii"))

    def test_the_dump_lines_also_for_an_old_utf8_file(self):
        _d, _p, out, _i, _s = self.build()
        for src in (out, html.unescape(out)):                             # today's ASCII, a pre-fix UTF-8 file
            lines = dump.lines("2026-11-25", src)
            self.assertTrue(all(x.isascii() for x in lines))
            body = dump.decode("".join(x.split(" ", 3)[3] for x in lines))
            self.check(body)

    def test_the_page_that_serves_it_also_for_an_old_utf8_file(self):
        from ui import reportpage
        _d, _p, out, _i, _s = self.build()
        with open(os.path.join(self.tmp.name, "report-2026-11-24.html"), "w", encoding="utf-8") as f:
            f.write(html.unescape(out))                                   # saved before 25.11.: raw UTF-8
        with mock.patch.object(reportpage, "OUT", self.tmp.name):
            for day in ("2026-11-24", "2026-11-25"):
                self.check(reportpage.raw(day).decode("ascii"))

    def test_the_mail_html_ascii_the_plain_text_utf8(self):
        _d, _p, out, _i, _s = self.build()
        self.assertEqual(mail.ascii_html(out), out)                        # idempotent
        txt = mail.plain(out)
        self.assertIn("Novčanici: kašnjenje, stop −20 %", txt)
        self.assertNotIn("&#269;", txt)
        sent = {}

        def fake(subject, h, to=None):
            sent["html"] = h
            return "smtp"
        with mock.patch.object(run_report.mail, "send", side_effect=fake), \
                mock.patch.object(run_report.collect, "collect", return_value={"ts": NOW, "fokus": True, "midcap": {}}), \
                mock.patch.object(run_report.ai, "fallback", return_value={"naslov": TITLE}), \
                mock.patch.object(run_report.tjedni, "due", return_value=(False, "")), \
                mock.patch.object(run_report.tjedni, "commit", return_value="x"):
            run_report.send_today(use_ai=False, now=NOW)
        self.check(sent["html"])


if __name__ == "__main__":
    unittest.main()
