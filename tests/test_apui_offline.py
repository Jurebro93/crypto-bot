"""The Autopilot page of 10.11. (Jure: "čista, minimalistička"; graf na vrhu; dnevnik na klik; "Zovu sada" i "Što
kupiti sada" na dno): ui/apchart.py, the header + chart, the decision log, the page order and the lazy sections, the
new /pravi-trade/graf, /pravi-trade/dnevnik and /pravi-trade/preporuke routes. trade/equity.py and trade/aplog.py
belong to another group; they are replaced here by small fakes with the exact keys of audit/2026-11-10/dizajn.md.

    python3 -m unittest tests.test_apui_offline
"""
import io
import json
import os
import re
import sqlite3
import sys
import tempfile
import time
import types
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from league import copy, store  # noqa: E402
from trade import executor, settings  # noqa: E402
from ui import apchart, pravitrade  # noqa: E402

NOW = int(time.time())
DAY = 86400
_WAKE = mock.patch.object(copy, "WAKE", os.path.join(tempfile.mkdtemp(), ".copy_wake"))


def setUpModule():   # follows and buys wake the copy loop; never the repo's own .copy_wake
    _WAKE.start()


def tearDownModule():
    _WAKE.stop()


def point(ts, value, net, src="live", sol_usd=170.0, usd_eur=0.86, flow=0.0, tokens=0.0):
    """One trade.equity.series() point with every key of the contract."""
    return {"ts": ts, "sol": value - tokens, "usdc": 0.0, "tokens_sol": tokens, "value_sol": value,
            "value_usd": value * sol_usd if sol_usd else None,
            "value_eur": value * sol_usd * usd_eur if sol_usd and usd_eur else None, "sol_usd": sol_usd,
            "usd_eur": usd_eur, "flow_sol": flow, "net_in_sol": net, "pnl_sol": value - net, "src": src}


def history(n=40, start=NOW - 3 * DAY, step=1800):
    """1 SOL in at the start (opening deposit), 0.5 more half-way; the first quarter rebuilt from orders."""
    out = []
    for i in range(n):
        net = 1.0 if i < n // 2 else 1.5
        out.append(point(start + i * step, net + 0.002 * i, net, src="recon" if i < n // 4 else "live",
                         flow=1.0 if i == 0 else 0.5 if i == n // 2 else 0.0, tokens=0.05))
    return out


SUMMARY = {"value_sol": 1.815, "value_usd": 308.6, "value_eur": 265.4, "sol": 1.772, "usdc": 0.0, "tokens_sol": 0.043,
           "net_in_sol": 1.75, "pnl_sol": 0.065, "pnl_pct": 3.71, "pnl_24h_sol": 0.029, "first_ts": NOW - 10 * DAY,
           "last_ts": NOW - 60, "sol_usd": 170.0, "usd_eur": 0.86, "n": 2000}


def fake_equity(series=None, summary=None, deposits=None, rates=None, boom=False):
    m = types.SimpleNamespace(calls=[])

    def _series(con, since=None, max_points=600):
        m.calls.append(("series", since, max_points))
        if boom:
            raise RuntimeError("tablica equity je zaključana")
        return [dict(p) for p in (series or []) if since is None or p["ts"] >= since]

    def _summary(con, now=None):
        m.calls.append(("summary",))
        return dict(summary or {})

    def _deposits(con):
        return [dict(d) for d in (deposits or [])]

    def _rates(now=None):
        m.calls.append(("rates",))
        return dict(rates or {"sol_usd": None, "usd_eur": None, "ts": 0})
    m.series, m.summary, m.deposits, m.rates = _series, _summary, _deposits, _rates
    return m


ENTRIES = [
    {"ts": NOW - 60, "kind": "nije_proslo", "token": "TOKA", "symbol": "AAA", "source": "KOL ansem",
     "why": "HTTPError 429 https://mainnet.helius-rpc.com/?api-key=tajna", "why_short": "mreža", "sol": 0.05,
     "pnl_pct": None, "mode": "live", "stage": "pravi", "sig": None, "trebao": True, "side": "buy"},
    {"ts": NOW - 120, "kind": "preskocio", "token": "TOKB", "symbol": "BBB", "source": "wallet 7xKX…",
     "why": "signal star 4 min: kupnja samo dok je poziv svjež", "why_short": "signal star", "sol": None,
     "pnl_pct": None, "mode": "dry", "stage": "demo", "sig": None, "trebao": False, "side": "buy"},
    {"ts": NOW - 300, "kind": "prodao", "token": "TOKC", "symbol": "CCC", "source": "KOL ansem", "why": "TP +40 %",
     "why_short": "cilj", "sol": 0.071, "pnl_pct": 42.4, "mode": "live", "stage": "pravi", "sig": "SIG5", "trebao": None,
     "side": "sell"},
    {"ts": NOW - 400, "kind": "nije_proslo", "token": "TOKD", "symbol": "DDD", "source": None,
     "why": "transakcija nije stigla u blok", "why_short": "transakcija nije stigla na vrijeme", "sol": None,
     "pnl_pct": None, "mode": "live", "stage": "pravi", "sig": None, "trebao": True, "side": "sell"},
    {"ts": NOW - 900, "kind": "kupio", "token": "TOKC", "symbol": "CCC", "source": "KOL ansem", "why": None,
     "why_short": "", "sol": 0.05, "pnl_pct": None, "mode": "live", "stage": "pravi", "sig": "SIG1", "trebao": None,
     "side": "buy"},
]
DAY_SUMM = {"signali": 12, "kupio": 2, "prodao": 1, "preskocio": 9, "nije_proslo": 1,
            "razlozi": [("bez dokaza u demu", 5), ("signal star", 3), ("limit", 1)]}


def fake_aplog(entries=ENTRIES, summ=DAY_SUMM, day=True, boom=False):
    m = types.SimpleNamespace(calls=[])

    def _entries(tcon, lcon=None, limit=80, since=None, now=None):
        m.calls.append(("entries", limit, since))
        if boom:
            raise sqlite3.OperationalError("database is locked")
        return [dict(e) for e in entries][:limit]

    def _summary(rows, now=None):
        m.calls.append(("summary", len(rows)))
        return dict(summ)
    m.entries, m.summary = _entries, _summary
    if day:
        def _summary_24h(tcon, lcon=None, now=None, ttl=5):
            m.calls.append(("summary_24h",))
            return dict(summ)
        m.summary_24h = _summary_24h
    return m


class Chart(unittest.TestCase):
    def test_empty_says_when_the_chart_starts(self):
        html = apchart.chart_html([], {})
        self.assertIn("Graf kreće s prvom snimkom, za najviše 5 minuta.", html)
        self.assertNotIn("<svg", html)
        self.assertNotIn("data-n=", html)          # nothing for the script to draw

    def _data(self, html):
        return json.loads(re.search(r'<script type="application/json">(.*?)</script>', html).group(1))

    def test_points_units_deposits_and_the_rebuilt_part(self):
        s = history()
        html = apchart.chart_html(s, SUMMARY, [{"ts": s[0]["ts"], "sol": 1.0, "kind": "pocetni"},
                                               {"ts": s[20]["ts"], "sol": 0.5, "kind": "uplata"}])
        d = self._data(html)
        self.assertEqual(len(d["t"]), 40)
        self.assertEqual(d["t"], sorted(d["t"]))
        self.assertEqual(d["r"][:10], [1] * 10)             # src='recon' flagged, drawn dashed
        self.assertEqual(d["r"][10:], [0] * 30)
        self.assertEqual(d["d"], [[s[0]["ts"], 1.0], [s[20]["ts"], 0.5]])
        self.assertAlmostEqual(d["p"][-1], s[-1]["pnl_sol"], places=5)
        for unit in ('data-v=sol>SOL', 'data-v=usd>$', 'data-v=eur>€', 'data-v=1>24 h', 'data-v=0>sve'):
            self.assertIn(unit, html)
        self.assertIn("rekonstruirano iz naloga", html)
        self.assertIn("uplata ili isplata", html)
        # the summary, before the script draws; 10.11. (prijedlog dizajna, pravilo 8): decimal comma in Croatian
        self.assertIn("Vrijednost 1,815 SOL · PnL +0,065 SOL", html)
        self.assertIn("Value 1.815 SOL · PnL +0.065 SOL", apchart.chart_html(s, SUMMARY, lang="en"))   # English keeps the point
        self.assertNotIn('"now"', html)   # the browser's clock ends the range: same points = same HTML (45-s refresh)
        self.assertEqual(html, apchart.chart_html(s, SUMMARY, [{"ts": s[0]["ts"], "sol": 1.0},
                                                               {"ts": s[20]["ts"], "sol": 0.5}]))

    def test_no_rate_no_money_units_and_no_euro_without_its_rate(self):
        s = [point(NOW - 600 * i, 1.0, 1.0, sol_usd=None, usd_eur=None) for i in range(5)]
        html = apchart.chart_html(s, {})
        self.assertNotIn("data-k=u", html)
        self.assertIsNone(self._data(html)["u"])
        s = [point(NOW - 600 * i, 1.0, 1.0, usd_eur=None) for i in range(5)]
        html = apchart.chart_html(s, {})
        self.assertIn("data-v=usd>$", html)
        self.assertNotIn("data-v=eur", html)
        # a gap in the rate takes the last known one: dollars are the SOL amount at the rate of that moment
        s = [point(NOW - 600 * (5 - i), 1.0, 1.0, sol_usd=170.0 if i != 2 else None) for i in range(5)]
        self.assertEqual(self._data(apchart.chart_html(s, {}))["u"], [170.0] * 5)

    def test_compact_has_the_range_only(self):
        html = apchart.chart_html(history(), SUMMARY, compact=True, ident="pub")
        self.assertIn('id="apc-pub"', html)
        self.assertIn("apc-compact", html)
        self.assertNotIn("data-k=u", html)
        self.assertNotIn("<div class=apc-tbl", html)   # no table view in the compact one
        self.assertNotIn("class=apc-tb ", html)
        self.assertIn("data-k=r", html)

    def test_bad_rows_and_thinning(self):
        s = history() + [{"ts": "x", "value_sol": 1}, {"ts": NOW, "value_sol": float("nan")}, {"value_sol": 2.0}]
        self.assertEqual(len(self._data(apchart.chart_html(s, {}))["t"]), 40)   # broken rows left out, no exception
        many = [point(NOW - 60 * (4000 - i), 1.0, 1.0, flow=0.3 if i == 1234 else 0.0) for i in range(4000)]
        d = apchart.pack(many)
        self.assertLessEqual(len(d["t"]), apchart.MAX_POINTS + 1)
        self.assertEqual((d["t"][0], d["t"][-1]), (many[0]["ts"], many[-1]["ts"]))   # first and newest kept
        self.assertIn(many[1234]["ts"], d["t"])                                     # a deposit's point kept

    def test_public_safe_nothing_owner_only(self):
        """The public Autopilot page calls this too: no links, no forms, no routes, only the numbers given."""
        html = apchart.chart_html(history(), SUMMARY, [{"ts": NOW - DAY, "sol": 0.5}], lang="en")
        for bad in ("/pravi-trade", "<form", "<a ", "href=", "SOLANA", "api-key"):
            self.assertNotIn(bad, html)
        self.assertIn("Wallet value", html)
        # nothing in the embedded data can close its script tag
        self.assertNotIn("</script>", self._data(html).__repr__())


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = self.tmp.name
        self._saved = (settings.DB, store.DB, pravitrade.BG_REFRESH)
        settings.DB, store.DB = os.path.join(d, "trade.db"), os.path.join(d, "league.db")
        pravitrade.BG_REFRESH = False   # no side threads: the rate is asked in the request
        self.env = mock.patch.dict(os.environ, {"TRADE_OWNER": "Jure"})
        self.env.start()
        for k in ("TRADE_LIVE", "SOLANA_PRIVATE_KEY", "SOLANA_PUBLIC_KEY"):
            os.environ.pop(k, None)
        self.con = executor.connect(settings.DB)
        settings.put(self.con, "invited", ["Ivan"])
        self.lg = store.connect(store.DB)
        copy.ensure(self.lg)
        self._reset()

    def _reset(self):
        with pravitrade._LOCK:
            pravitrade._EQ.update(ts=0.0, key=None, val=None)
            pravitrade._RATES.update(ts=0.0, val=None, busy=False)
            pravitrade._DN.update(ts=0.0, key=None, rows=None)
            pravitrade._DN_LINE.update(ts=0.0, key=None, line=None)

    def tearDown(self):
        self._reset()
        settings.DB, store.DB, pravitrade.BG_REFRESH = self._saved
        self.env.stop()
        self.con.close()
        self.lg.close()
        self.tmp.cleanup()

    def mods(self, eq=None, ap=None):
        """Patch both module lookups (None = the module is not there)."""
        a = mock.patch.object(pravitrade, "_equity_mod", lambda: eq)
        b = mock.patch.object(pravitrade, "_aplog_mod", lambda: ap)
        a.start()
        b.start()
        self.addCleanup(a.stop)
        self.addCleanup(b.stop)


class Header(Base):
    def test_value_in_sol_dollars_euros_pnl_and_the_chart(self):
        eq = fake_equity(history(), SUMMARY, [{"ts": NOW - 3 * DAY, "sol": 1.0}],
                         rates={"sol_usd": 171.24, "usd_eur": 0.8623, "ts": NOW})
        self.mods(eq, None)
        html = pravitrade.head_fragment("Jure")
        # 10.11. (prijedlog dizajna 3.4, maketa autopilot.html): one big number in SOL with a decimal comma, under it
        # one line: dollars and euros, the last 24 h and the result in total; the rate of 1 SOL and the money put in
        # moved one tap away, into "Wallet i uplata" (checked on the page below)
        self.assertIn('<div class="ms-big">1,815<small>SOL</small></div>', html)
        self.assertIn("≈ 311 $ · 268 €", html)               # 1.815 x 171.24 = 310.8 $; x 0.8623 = 268.0 €, live rate
        self.assertIn('24 h <span class="pos">+0,029\u00a0SOL</span>', html)                # last 24 h
        self.assertIn('ukupno <span class="pos">+3,7\u00a0%</span>', html)   # in total, against the money put in
        self.assertNotIn("1 SOL =", html)
        _, page = pravitrade.page({}, "Jure")
        self.assertIn("1 SOL = 171 $ · 148 €", page)
        self.assertIn("Uplaćeno 1,750\u00a0SOL, rezultat", page)
        self.assertIn('<span class="pos">+0,065\u00a0SOL</span> (+3,7\u00a0%)', page)
        self.assertIn('id="apc-ap"', html)
        self.assertIn("Uključi Autopilot", html)             # the owner's switch
        self.assertIn('data-meta="#ap-dn-sum"', html)        # the closed log's line rides along
        guest = pravitrade.head_fragment("Ivan")             # invited: looks only
        self.assertIn("1,815<small>SOL</small>", guest)
        self.assertNotIn("/pravi-trade/switch", guest)
        self.assertNotIn("/pravi-trade/sellall", guest)
        self.assertIsNone(pravitrade.head_fragment("Nepoznat"))

    def test_the_rate_of_the_snapshot_until_a_live_one_comes(self):
        self.mods(fake_equity(history(), SUMMARY, rates={"sol_usd": None, "usd_eur": None, "ts": 0}), None)
        html = pravitrade.head_fragment("Jure")
        self.assertIn("≈ 309 $ · 265 €", html)               # 1.815 x the summary's sol_usd 170 and usd_eur 0.86
        _, page = pravitrade.page({}, "Jure")                 # 10.11.: the rate itself is in "Wallet i uplata"
        self.assertIn("1 SOL = 170 $ · 146 €", page)

    def test_one_read_per_ttl_for_every_viewer(self):
        eq = fake_equity(history(), SUMMARY)
        self.mods(eq, None)
        pravitrade.head_fragment("Jure")
        pravitrade.head_fragment("Ivan")
        self.assertEqual(sum(1 for c in eq.calls if c[0] == "summary"), 1)
        # the whole history thinned, then the last 24 h in full (the 24-h view is not a handful of dots)
        self.assertEqual([c[1:] for c in eq.calls if c[0] == "series"][0], (None, 600))
        self.assertEqual(len([c for c in eq.calls if c[0] == "series"]), 2)

    def test_without_trade_equity_the_plain_balance_and_no_promise_of_a_chart(self):
        self.mods(None, None)
        html = pravitrade.head_fragment("Jure")
        self.assertIn("–<small>SOL</small>", html)            # no wallet address in this test: no balance either
        self.assertNotIn("apc-", html)
        self.assertNotIn("Graf kreće", html)
        self.assertIn("<span>Isključen</span>", html)         # 10.11. (maketa): the word in the title row ...
        self.assertIn("Samo probno, bez novca", html)         # ... and the state after a dot, no capitals

    def test_a_failing_history_never_takes_the_header_down(self):
        self.mods(fake_equity(boom=True), fake_aplog(boom=True))
        with mock.patch("builtins.print"):
            html = pravitrade.head_fragment("Jure")
        self.assertIn("Uključi Autopilot", html)
        self.assertIn("Graf kreće s prvom snimkom", html)     # the module is there, its table is not readable yet

    def test_rate_thread_never_blocks_and_never_sticks(self):
        eq = fake_equity(history(), SUMMARY, rates={"sol_usd": 150.0, "usd_eur": 0.9, "ts": NOW})
        pravitrade.BG_REFRESH = True
        with mock.patch.object(pravitrade.threading, "Thread", side_effect=RuntimeError("can't start new thread")), \
                mock.patch.object(pravitrade, "_equity_mod", lambda: eq):
            r = pravitrade._rates(SUMMARY, NOW)
        self.assertEqual(r["sol_usd"], 170.0)                 # the snapshot's rate meanwhile
        self.assertFalse(pravitrade._RATES["busy"])           # a failed start does not block the next try


class Log(Base):
    def test_rows_reasons_and_should_it_have_bought(self):
        ap = fake_aplog()
        self.mods(None, ap)
        html = pravitrade.dnevnik_fragment("Jure")
        # 10.11. (prijedlog dizajna, pravilo 5): the decision is a word after a dot, no capitals
        for word in ("nije prošlo", "preskočio", "prodao", "kupio"):
            self.assertIn(f'aria-hidden="true"></span>{word}', html)
        self.assertNotIn("PRESKOČIO", html)
        self.assertLess(html.index("AAA"), html.index("BBB"))     # newest first, as aplog gives them
        self.assertIn("<b>Trebao je kupiti: da.</b> Sva pravila su prošla, ali nalog nije.", html)
        self.assertIn("Trebao je kupiti: ne, pravilo je reklo ne.", html)
        self.assertIn("Trebao je prodati: da. Prodaja nije prošla, bot pokušava ponovno.", html)   # a sell, not a buy
        self.assertEqual(html.count("Trebao je kupiti"), 2)
        self.assertIn('class="ms-v pos">+42,4\u00a0%', html)   # a sale's result is the row's number
        self.assertIn("https://solscan.io/tx/SIG5", html)
        self.assertIn('data-pop="/pravi-trade/token?m=TOKA"', html)   # every token row opens the token pop-up
        self.assertIn("signal star 4 min", html)                       # the owner reads the reason as written
        self.assertIn("Zadnja 24 h: 12 signala · 2 kupljeno · 9 preskočeno (5 bez dokaza u demu, 3 signal star) · "
                      "1 nije prošlo · 1 prodano", html)
        self.assertIsNone(pravitrade.dnevnik_fragment("Nepoznat"))

    def test_invited_viewer_gets_the_short_reason_never_the_raw_error(self):
        self.mods(None, fake_aplog())
        html = pravitrade.dnevnik_fragment("Ivan")
        self.assertNotIn("api-key", html)
        self.assertNotIn("helius", html)
        self.assertIn("mreža", html)
        self.assertNotIn("kupnja samo dok je poziv svjež", html)
        self.assertIn("signal star", html)

    def test_the_line_counts_the_whole_day_not_the_80_listed_rows(self):
        ap = fake_aplog(day=True)
        self.mods(None, ap)
        pravitrade.dnevnik_line(self.con, NOW)
        self.assertIn(("summary_24h",), ap.calls)
        self.assertFalse([c for c in ap.calls if c[0] == "entries"])
        self._reset()
        ap = fake_aplog(day=False)   # the contract's summary(rows) only: over the day's entries
        self.mods(None, ap)
        line = pravitrade.dnevnik_line(self.con, NOW)
        self.assertEqual([c for c in ap.calls if c[0] == "entries"], [("entries", pravitrade.DAY_ROWS, NOW - DAY)])
        self.assertTrue(line.startswith("Zadnja 24 h: 12 signala"))
        pravitrade.dnevnik_line(self.con, NOW + 5)   # cached: the page, the header and the open log share it
        self.assertEqual(len([c for c in ap.calls if c[0] == "entries"]), 1)

    def test_without_trade_aplog_the_order_list_and_a_bounded_count(self):
        self.mods(None, None)
        self.con.execute("INSERT INTO orders (ts, token, side, mode, amount_in, status) VALUES (?,?,?,?,?,?)",
                         (NOW - 60, "FRESH", "buy", "dry", 50_000_000, "dry"))
        self.con.commit()
        html = pravitrade.dnevnik_fragment("Jure")
        self.assertIn("FRESH", html)                          # log_html, the list that was here before
        self.assertIn("Zadnja 24 h: 1 naloga", html)
        self._reset()
        self.mods(None, fake_aplog(boom=True))                # aplog there but failing: the same fallback
        with mock.patch("builtins.print"):
            self.assertIn("FRESH", pravitrade.dnevnik_fragment("Jure"))

    def test_nothing_yet(self):
        self.mods(None, fake_aplog(entries=[], summ={"signali": 0, "kupio": 0, "prodao": 0, "preskocio": 0,
                                                     "nije_proslo": 0, "razlozi": []}))
        html = pravitrade.dnevnik_fragment("Jure")
        self.assertIn("Još nema nijedne odluke", html)
        self.assertIn("Zadnja 24 h: nijedan signal", html)


class Page(Base):
    def test_order_of_dizajn_and_closed_sections_compute_nothing(self):
        from ui import autopilot, zivo

        def boom(*a, **k):
            raise AssertionError("a closed section was computed while the page was built")
        self.mods(fake_equity(history(), SUMMARY), fake_aplog())
        with mock.patch.object(autopilot, "kol_recs", boom), mock.patch.object(autopilot, "wallet_recs", boom), \
                mock.patch.object(autopilot, "token_recs", boom), mock.patch.object(zivo, "rows", boom), \
                mock.patch.object(pravitrade, "gather_callers", boom), mock.patch.object(pravitrade, "dnevnik_data", boom):
            _, body = pravitrade.page({}, "Jure")
        # 10.11. (prijedlog dizajna 3.4, maketa autopilot.html): the title with the switch is inside the 45-s header;
        # "Kako trguje" = Koga prati, Pravila (cilj + limiti), Kupi ručno; "Još" = the two live lists, the
        # recommendations, Wallet i uplata (setup steps), who sees the page, safety
        # 10.11. (Jure): "Brza kupnja" (id=kupi-odmah) right under the chart, before the log
        keys = ("id=ap-head", "<h1 class=ms-h1>Autopilot</h1>", 'id="apc-ap"', "id=kupi-odmah", "id=dnevnik", "id=pozicije",
                "id=pratim", "id=pravila", "id=cilj", "id=limiti", "id=zovu", "id=ideje", "id=preporuke",
                "id=postavljanje", "id=pozivnice", "id=zastita")
        at = [body.index(k) for k in keys]
        self.assertEqual(at, sorted(at))
        for sid, src in (("dnevnik", "/pravi-trade/dnevnik"), ("preporuke", "/pravi-trade/preporuke"),
                         ("zovu", "/pravi-trade/zovu"), ("ideje", "/pravi-trade/ideje")):
            self.assertIn(f"<details class=ap-sec id={sid}><summary>", body)       # closed
            self.assertRegex(body, rf"data-src={src} data-every=\d+ data-lazy")      # fetched only once opened
        self.assertIn("data-src=/pravi-trade/graf data-every=45", body)             # header + chart every 45 s
        self.assertIn("Zadnja 24 h: 12 signala", body)                               # the closed log's one line
        # each list at the bottom says what it is
        self.assertIn("Tko sada zove koji token", body)
        self.assertIn("Što alat sada predlaže za kupnju", body)
        self.assertIn("Dodirni token za provjeru uživo i kupnju", body)
        self.assertEqual(body.count("<script>(()=>{if(window.apTick)return"), 1)     # one poller

    def test_invited_sees_no_owner_controls(self):
        self.mods(fake_equity(history(), SUMMARY), fake_aplog())
        _, body = pravitrade.page({}, "Ivan")
        for owner_only in ("/pravi-trade/switch", "/pravi-trade/sellall", "Spremi limite", "id=kupi-odmah",
                           "id=pozivnice", "Postavljanje walleta", "Prodaj 20 %", "Dovrši"):
            self.assertNotIn(owner_only, body)
        self.assertIn("1,815<small>SOL</small>", body)       # 10.11.: decimal comma (pravilo 8)
        self.assertIn("Dnevnik odluka", body)                 # 10.11.: the row's name in the mock-up

    def test_one_broken_part_never_costs_the_switch(self):
        self.mods(None, None)
        with mock.patch.object(pravitrade, "_follows", side_effect=RuntimeError("follow_results pukao")), \
                mock.patch("builtins.print"):
            _, body = pravitrade.page({}, "Jure")
        self.assertIn("Uključi Autopilot", body)
        self.assertIn("id=pozicije", body)
        self.assertNotIn("id=pratim", body)

    def test_no_emoji_in_front_of_warnings(self):
        self.mods(None, None)
        html = pravitrade._warnings(self.con, settings.merged({"size_sol": 0.01, "max_sol_per_day": 1, "max_open": 5,
                                                                "min_sol_reserve": 0.05, "max_loss_day": 0.3}, self.con),
                                    self.lg)
        self.assertIn("Bot nikoga ne prati", html)
        self.assertNotIn("⚠", html)
        self.assertNotIn("⛔", html)

    def test_recommendations_fragment_same_access_and_built_on_request(self):
        from ui import autopilot
        with mock.patch.object(autopilot, "kol_recs", lambda now=None: {14: []}), \
                mock.patch.object(autopilot, "wallet_recs", lambda now=None: {14: []}), \
                mock.patch.object(autopilot, "token_recs", lambda now=None: {"dugo": [], "moon": []}):
            self.assertEqual(pravitrade.recs_fragment("Jure"), "")   # nothing to offer: the box's own sentence
            self.assertIsNone(pravitrade.recs_fragment("Nepoznat"))
        with mock.patch.object(autopilot, "kol_recs", side_effect=RuntimeError("kol.db")), \
                mock.patch.object(autopilot, "wallet_recs", lambda now=None: {14: []}), \
                mock.patch.object(autopilot, "token_recs", lambda now=None: {"dugo": [], "moon": []}), \
                mock.patch("builtins.print"):
            self.assertEqual(pravitrade.recs_fragment("Ivan"), "")   # a broken list is left out, no 500

    def test_positions_poll_reads_only_the_listed_positions_orders(self):
        """10.11. (Jure: "sekundni poslovi ne čitaju cijelu bazu"): the 1-s positions fragment read every order ever made."""
        for i in range(3):
            pid = self.con.execute("INSERT INTO positions (token, symbol, mode, status, sol_in, sol_back, opened_ts, "
                                   "closed_ts) VALUES (?,?,?,?,?,?,?,?)",
                                   (f"T{i}", f"S{i}", "dry", "closed", 0.05, 0.06, NOW - 900, NOW - 600)).lastrowid
            self.con.execute("INSERT INTO orders (ts, position_id, side, status, signature) VALUES (?,?,?,?,?)",
                             (NOW - 600, pid, "sell", "dry", f"SIG{i}"))
        self.con.commit()
        seen = []

        def traced():
            c = executor.connect(settings.DB)
            c.set_trace_callback(seen.append)
            return c
        with mock.patch.object(pravitrade, "_tcon", traced):
            html = pravitrade.positions_fragment("Jure")
        self.assertIn("SIG2", html)
        q = [s for s in seen if "FROM orders" in s]
        self.assertTrue(q)
        self.assertTrue(all("position_id IN" in s for s in q), q)
        # with the index trade/aplog.py adds, the list must still walk the key newest first and stop at its LIMIT
        self.con.execute("CREATE INDEX IF NOT EXISTS positions_status ON positions (status, opened_ts)")
        listed = [s for s in seen if "FROM positions" in s and "ORDER BY id DESC" in s]
        self.assertTrue(listed)
        for sql in listed:
            plan = " ".join(r[3] for r in self.con.execute("EXPLAIN QUERY PLAN " + sql))
            self.assertNotIn("TEMP B-TREE", plan, sql)


class Refresher(Base):
    def test_an_open_popup_starts_the_refresher_not_a_stranger(self):
        """The live lists are closed sections now, so their polls no longer start the refresher on every page view;
        a pop-up (from a position or a log row) starts it, and its DexScreener state is renewed off the request."""
        started = []

        class T:
            def __init__(self, target=None, daemon=None, name=None):
                self.name = name

            def start(self):
                started.append(self.name)

            def is_alive(self):
                return True
        saved = pravitrade._BG["thread"]
        pravitrade.BG_REFRESH, pravitrade._BG["thread"] = True, None
        try:
            with mock.patch.object(pravitrade.threading, "Thread", T):
                self.assertIsNone(pravitrade.token_popup("Nepoznat", "x"))
                self.assertEqual(started, [])
                self.assertIn("nije Solana adresa", pravitrade.token_popup("Jure", "x"))
                self.assertEqual(started, ["autopilot-live"])
                pravitrade.crew_popup("Ivan", "")
                self.assertEqual(started, ["autopilot-live"])   # one refresher per process
        finally:
            pravitrade._BG["thread"] = saved


class Routes(Base):
    def _get(self, path, user="Jure"):
        import run_ui
        h = run_ui.Handler.__new__(run_ui.Handler)
        h.path, h.headers, h.wfile, h.user, h.role = path, {}, io.BytesIO(), user, "admin"
        h.sent = []
        h._send = lambda code, body=b"", ctype="text/html", gz=None, translated=False: h.sent.append((code, body))
        with mock.patch.object(run_ui, "AUTH", False):
            h.do_GET()
        return h.sent[0]

    def test_new_fragments_are_served_with_the_page_access(self):
        self.mods(fake_equity(history(), SUMMARY), fake_aplog())
        code, body = self._get("/pravi-trade/graf")
        self.assertEqual(code, 200)
        self.assertIn(b"apc-ap", body)
        code, body = self._get("/pravi-trade/dnevnik")
        self.assertEqual(code, 200)
        self.assertIn("preskočio".encode(), body)
        self.assertEqual(self._get("/pravi-trade/dnevnik", "Nepoznat")[0], 403)
        self.assertEqual(self._get("/pravi-trade/graf", "Nepoznat")[0], 403)
        with mock.patch.object(pravitrade, "recs_fragment", side_effect=RuntimeError("x")), \
                mock.patch("sys.stderr", io.StringIO()):
            self.assertEqual(self._get("/pravi-trade/preporuke"), (500, b""))   # no error text on the page


if __name__ == "__main__":
    unittest.main()
