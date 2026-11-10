"""10.11. (Jure, prijedlog 3.1): the calm Pregled. One answer first ("Najbolji ulaz sada"), the compact "Prijedlog za
danas" (hero + rows, the full text in a pop-up), "Vrijedi pratiti" with the one influencer verdict (ui/kolsummary),
"Ovaj tjedan" with the Autopilot state, and the data tiles behind one line. No network, no real databases.

    python3 -m unittest tests.test_pregled_mirno_offline
"""
import os
import re
import sqlite3
import sys
import tempfile
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ui import pocetna, prijedlog, redak as R  # noqa: E402

NOW = 1_794_300_000.0     # utorak, 10. studenoga 2026., 09:20 u Zagrebu
T1, T2, T3 = "GIGA" + "1" * 36 + "pump", "ARIA" + "2" * 36 + "pump", "MOCH" + "3" * 36 + "pump"
EMOJI = re.compile("[\U0001F300-\U0001FAFF☀-➿⭐⬆↔-⇿Ⓜℹ]")


def pick(tok, sym, conf, mcap, why, ch_h1=18.0, razina="visoka"):
    return {"token": tok, "symbol": sym, "conf": conf, "mcap0": mcap, "why": [why], "protiv": [], "razina": razina,
            "chance": (0.65, 561), "live": {"ch_h1": ch_h1, "mcap": mcap}, "thesis": f"Teza: {why}"}


def parts(picks=None, near=None, note="", wallets=None):
    return {"now": NOW, "an": {"tokena": 21, "poziva": 1834, "kolova": 358, "novcanika": 24, "tradeova": 71},
            "status": {}, "picks": picks or [], "near": near or [], "note": note, "mak": "Makro: BTC raste", "rec": "",
            "wallets": wallets or [], "crew": None, "chances": {"100–300k": (0.66, 728)}}


PICKS = [pick(T1, "GIGAFROG", 94, 412_000, "Novac ulazi brzo: volumen u zadnjem satu je 3x ili više likvidnosti."),
         pick(T2, "ARIA", 83, 268_000, "3 provjerenih smart walleta je među prvim kupcima.", 6.0),
         pick(T3, "MOCHI", 76, 96_000, "1 provjerenih smart walleta je među prvim kupcima.", 4.0)]
WALLET = {"wallet": "VfdnxFG33CM2rVeYegb6ooV5xEPLuhKYGhBPa5aWAt74", "tier": "visoka", "proven": True, "copyable": True,
          "stats": {"closed": 31, "win_rate": 0.68, "closed_pnl_sol": 11.86, "median_hold_min": 264, "trades_per_day": 3},
          "last": None}


def _s(name, ret, closed=10):
    """A strategy row as strat/run.summary gives it (the same shape as tests/test_pocetna_strat_card_offline)."""
    value = 1000 * (1 + ret)
    return {"key": name, "name": name, "icon": "x", "ret": ret, "value": value, "closed": closed, "open": 0,
            "hit": 0.6, "p15": 0.1, "opis": "opis", "status": ("uci", "uči", "još uči"),
            "robust": {"total": value - 1000, "best": 1, "no_best": value - 1001, "no_top5": 0, "concentrated": False},
            "portfolio": {"value": value, "cash_low": 0, "taken": closed, "skipped": 0}}


def visible(html):
    """Text a reader sees on the page (no pop-ups, styles or scripts)."""
    s = re.sub(r"<style.*?</style>|<script.*?</script>|<dialog.*?</dialog>", " ", html, flags=re.S)
    return re.sub(r"[ \t\r\n]+", " ", re.sub(r"<[^>]+>", " ", s))   # keeps the no-break spaces of the numbers


class Helpers(unittest.TestCase):
    def test_plural(self):
        self.assertEqual([pocetna.plural(n, "kupnja", "kupnje", "kupnji") for n in (1, 2, 4, 5, 11, 12, 21, 22, 25, 0)],
                         ["kupnja", "kupnje", "kupnje", "kupnji", "kupnji", "kupnji", "kupnja", "kupnje", "kupnji", "kupnji"])

    def test_today_is_croatian_in_zagreb_time(self):
        self.assertEqual(pocetna.today(NOW), "Utorak, 10. studenoga")

    def test_kol_name_has_no_emoji(self):
        self.assertEqual(pocetna.kol_name("Humanevolvd"), "@Humanevolvd")
        self.assertEqual(pocetna.kol_name("tg:gemcalls"), "gemcalls (Telegram)")

    def test_wilson_prefers_more_evidence(self):
        self.assertLess(pocetna.wilson_low(4, 5), pocetna.wilson_low(22, 30))
        self.assertEqual(pocetna.wilson_low(0, 0), 0.0)
        self.assertGreater(pocetna.wilson_low(30, 30), 0.8)

    def test_smart_wallet_grammar(self):
        self.assertEqual(prijedlog.smart_fix("3 provjerenih smart walleta je među prvim kupcima."),
                         "3 provjerena smart walleta su među prvim kupcima.")
        self.assertEqual(prijedlog.smart_fix("1 provjerenih smart walleta je među prvim kupcima"),
                         "1 provjereni smart wallet je među prvim kupcima")
        self.assertEqual(prijedlog.smart_fix("5 provjerenih smart walleta je među prvim kupcima", short=True),
                         "5 smart walleta među prvim kupcima")
        self.assertEqual(prijedlog.smart_fix("Cijena raste: +40% u zadnjem satu"), "Cijena raste: +40% u zadnjem satu")
        # a row keeps the head of a long reason; the hero keeps the whole sentence
        p = PICKS[0]
        self.assertEqual(prijedlog._why1(p, short=True), "Novac ulazi brzo")
        self.assertTrue(prijedlog._why1(p).endswith("likvidnosti."))

    def test_counts_in_one_pass_equal_the_separate_counts(self):
        path = os.path.join(tempfile.mkdtemp(), "kol.db")
        con = sqlite3.connect(path)
        con.execute("CREATE TABLE calls (ts INTEGER, kind TEXT)")
        rows = [(NOW - 3600, "call"), (NOW - 8 * 86400, "call"), (NOW - 20 * 86400, "call"), (NOW - 60, "buy"),
                (NOW - 9 * 86400, "sell"), (NOW - 100, "brag"), (NOW - 100, None)]
        con.executemany("INSERT INTO calls VALUES (?, ?)", rows)
        con.commit()
        con.close()
        wheres = ["kind = 'call'", "kind IN ('buy', 'sell')"]
        self.assertEqual(pocetna._sql_counts_many(path, "calls", "ts", NOW, wheres),
                         [pocetna._sql_counts(path, "calls", "ts", NOW, w) for w in wheres])
        self.assertEqual(pocetna._sql_counts_many(path, "calls", "ts", NOW, wheres), [(3, 1, 1), (2, 1, 1)])
        self.assertEqual(pocetna._sql_counts_many(os.path.join(tempfile.mkdtemp(), "nema.db"), "calls", "ts", NOW, wheres),
                         [None, None])


class CompactBox(unittest.TestCase):
    def test_one_answer_rows_and_the_full_text_in_a_pop_up(self):
        html = prijedlog.box("pregled", NOW, parts=parts(PICKS, wallets=[WALLET]))
        seen = visible(html)
        self.assertIn("Najbolji ulaz sada", seen)
        self.assertIn("GIGAFROG", seen)
        self.assertIn("pouzdanost 94 · 412k $ · 1 h", seen)
        self.assertIn("Ulog u demu 25–50 $", seen)
        self.assertIn("3 smart walleta među prvim kupcima", seen)       # the row, in the maketa's words
        self.assertIn("1 smart wallet među prvim kupcima", seen)
        self.assertIn("Izlaz: pola na +15 %", seen)
        self.assertIn("Cijeli prijedlog za danas", seen)
        self.assertNotIn("Teza:", seen)                                 # the thesis is one tap away
        self.assertNotIn("Analizirao sam", seen)
        self.assertLess(len(seen.split()), 80)
        self.assertIsNone(EMOJI.search(seen))
        # the pop-up keeps the whole old text, the wallet and the exit rule
        full = html[html.index('<dialog id="pdj-full"'):html.index("</dialog>")]
        for s in ("Teza:", "Analizirao sam u zadnja 24 h", "Pratio bih novčanik", "Očekivanje i izlaz", "pričekaj"):
            self.assertIn(s, full)
        self.assertIsNone(EMOJI.search(visible(full.replace("<dialog", "<div").replace("</dialog>", "</div>"))))
        # the live zone check and the minute reload still work on the compact box
        self.assertIn('id=pdj data-kind=pregled', html)
        self.assertEqual(html.count("data-p="), 6)                     # hero, two rows, three items in the pop-up
        self.assertIn(f'data-m0="412000" data-z="hero"', html)
        self.assertIn("/api/prijedlog?t=", html)
        self.assertIn("setInterval(reload,60000)", html)
        self.assertIn("pričekaj povlačenje", html)
        self.assertIn(str(prijedlog.PULL_X), html)
        self.assertIn(f'href="/token/{T1}"', html)
        self.assertTrue(html.rstrip().endswith("</script>"))
        self.assertNotIn("<script>", html.split('<div class=pdj-c')[1].split("</dialog>")[0])   # api() cuts at <script>

    def test_nothing_passes(self):
        near = [(pick(T2, "ARIA", 83, 268_000, "x"), "samo 4 transakcija u zadnjem satu (treba 10+)")]
        html = prijedlog.box("pregled", NOW, parts=parts(near=near))
        seen = visible(html)
        self.assertIn("Danas ništa", seen)
        self.assertIn("Bolje ništa nego najmanje loš", seen)
        self.assertIn("ne kupuj: samo 4 transakcija", seen)
        self.assertIn("nijedan token ne prolazi sve provjere", html)        # the full text in the pop-up
        note = prijedlog.box("pregled", NOW, parts=parts(note="provjera trenutnog prometa (DexScreener) nije uspjela"))
        self.assertIn("Provjera trenutnog prometa (DexScreener) nije uspjela.", visible(note))

    def test_api_returns_the_compact_box_without_script(self):
        with mock.patch.object(prijedlog, "pregled_parts", return_value=parts(PICKS)):
            out = prijedlog.api({"box": "pregled"})
        self.assertIn("id=pdj ", out)
        self.assertIn("Najbolji ulaz sada", out)
        self.assertNotIn("<script>", out)

    def test_other_variants_still_work(self):
        live = {T1: {"price": 0.001, "liq": 60_000.0, "mcap": 160_000.0, "vol_h1": 5_000.0, "vol_h24": 40_000.0,
                     "txns_h1": 40, "buys_h1": 25, "txns_h24": 400, "ch_h1": 6.0, "ch_h24": 15.0}}
        for kind in ("tokeni", "influenceri", "novcanici"):
            with mock.patch.object(prijedlog, "token_picks_ex", return_value=([], [], "")):
                html = prijedlog.box(kind, NOW, rows=[], live=live)
            self.assertIn("Prijedlog za danas", html)
            self.assertIn(f'data-kind="{kind}"', html)


VERDICTS = {
    "Humanevolvd": {"n": 30, "n1": 30, "h1": 0.70, "hits1": 21, "n24": 30, "plus24": 2, "d24": 0.07, "key": "samo_brzo",
                    "word": "samo brzo", "sentence": "U prvom satu 70 % poziva dođe do +10 %.", "dot": "warn"},
    "lucky": {"n": 5, "n1": 5, "h1": 0.80, "hits1": 4, "n24": 5, "plus24": 3, "d24": 0.6, "key": "drzi_se",
              "word": "drži se", "sentence": "x", "dot": "good"},
    "alertbot": {"n": 90, "n1": 90, "h1": 0.9, "hits1": 81, "n24": 90, "plus24": 50, "d24": 0.55, "key": "drzi_se",
                 "word": "drži se", "sentence": "x", "dot": "good"},
    "slab": {"n": 40, "n1": 40, "h1": 0.2, "hits1": 8, "n24": 40, "plus24": 5, "d24": 0.12, "key": "ne_isplati_se",
             "word": "ne isplati se", "sentence": "x", "dot": "bad"},
}


class Follow(unittest.TestCase):
    def test_influencer_by_the_one_verdict(self):
        with mock.patch.object(pocetna, "_kol_meta", return_value=({"Humanevolvd": 58}, {"alertbot"})):
            h, r, score = pocetna.kol_pick(VERDICTS)
            html = pocetna.kol_row(VERDICTS)
        self.assertEqual(h, "Humanevolvd")       # not the bot, not the 4-of-5, never "ne isplati se"
        self.assertEqual(score, 58)
        seen = visible(html)
        self.assertIn("@Humanevolvd", seen)
        self.assertIn("samo brzo · 70 % u 1 h", seen)                     # prijedlog 4.4
        self.assertIn("30", seen)
        self.assertIn("poziva", seen)
        self.assertIn('class="ms-dot warn"', html)
        self.assertIn('href="/kol/Humanevolvd"', html)
        self.assertNotIn("pogodak", seen)

    def test_no_verdict_yet_is_said_honestly(self):
        html = pocetna.kol_row({"slab": VERDICTS["slab"]})
        self.assertIn("još nijedan nema presudu", visible(html))
        self.assertIn('href="/kol"', html)
        self.assertIn("još nijedan nema presudu", visible(pocetna.kol_row({})))

    def test_wallet_row(self):
        html = pocetna.wallet_row([WALLET])
        seen = visible(html)
        self.assertIn("Vfdn…At74", seen)
        self.assertIn("dokazan dvaput · 68 % dobitnih od 31", seen)
        self.assertIn("visoka", seen)
        self.assertIn('href="/wallet/VfdnxFG33CM2rVeYegb6ooV5xEPLuhKYGhBPa5aWAt74"', html)
        self.assertIsNone(pocetna.wallet_row([]))


class Week(unittest.TestCase):
    def test_autopilot_row(self):
        live = {"state": {"live": True, "on": True}, "eq": {"value_sol": 2.0}, "stats": {"n": 8, "pnl": -0.042}}
        seen = visible(pocetna.autopilot_row(live))
        self.assertIn("uživo, pravi novac", seen)
        self.assertIn("2,000\u00a0SOL", seen)
        self.assertIn("−0,042\u00a0SOL", seen)
        dry = {"state": {"live": False, "on": True}, "eq": {}, "stats": {"n": 8, "pnl": 0.014}}
        html = pocetna.autopilot_row(dry)
        self.assertIn("probno, bez pravog novca", visible(html))
        self.assertIn("+0,014\u00a0SOL", visible(html))
        self.assertIn("8 zatvorenih", visible(html))
        self.assertIn('class="ms-dot warn"', html)                       # pravilo 4: "probno" is the warning colour
        self.assertIn('href="/autopilot"', html)
        off = {"state": {"live": False, "on": False}, "eq": {}, "stats": {"n": 0, "pnl": 0}}
        self.assertIn("isključen", visible(pocetna.autopilot_row(off)))
        self.assertIsNone(pocetna.autopilot_row({}))

    def test_strategy_row_says_the_verdict_with_the_number(self):
        lead = _s("Insajderi", 0.096, closed=36)
        lead["status"] = ("zamrznuto", "zamrznuto", "bez novih ulaza")
        st = {"cfg": {"bankroll_usd": 1000}, "days": 9.0, "rank": [lead, _s("KOL pozivi", 0.01)]}
        seen = visible(pocetna.strategy_row(st=st))
        self.assertIn("Vodi Insajderi, ali je zamrznuta", seen)
        self.assertIn("+9,6 %", seen)
        self.assertIn("9 dana", seen)
        lead["status"] = ("uci", "uči", "x")
        lead["robust"]["concentrated"] = False
        self.assertIn("Vodi Insajderi, još uči", visible(pocetna.strategy_row(st=st)))
        empty = {"cfg": {"bankroll_usd": 1000}, "days": 0.2, "rank": [_s("A", 0.0, closed=0)]}
        self.assertIn("još nema nijednog tradea", visible(pocetna.strategy_row(st=empty)))

    def test_win_row(self):
        w = [{"who": "Jure", "symbol": "GIGAFROG", "token": T1, "ret": 0.64, "pnl": 77.0, "peak": 0.9, "closed_ts": NOW}]
        with mock.patch("ui.wins.collect", return_value=w):
            seen = visible(pocetna.win_row())
        self.assertIn("Jure, GIGAFROG · Natjecanje", seen)
        self.assertIn("+64 %", seen)
        self.assertIn("+77 $", seen)

    def test_wallets_row_names_both_populations(self):
        con = sqlite3.connect(":memory:")
        con.execute("CREATE TABLE calls (ts INTEGER, kind TEXT)")
        con.executemany("INSERT INTO calls VALUES (?, ?)", [(NOW - 60, "buy")] * 10 + [(NOW - 60, "sell")])
        with mock.patch("ui.core._con", return_value=con), mock.patch.object(pocetna, "_followed_buys", return_value=7):
            seen = visible(pocetna.wallets_row(NOW))
        self.assertIn("10 kupnji", seen)
        self.assertIn("1 prodaja", seen)
        self.assertIn("Autopilot: 7 kupnji", seen)

    def test_data_line_and_pop_up(self):
        ms = [("🪙", "Tokeni analizirani", "/tokens", (24, 20, 4)), ("📣", "Influenceri (X)", "/kol", (358, 3618, 983))]
        with mock.patch.object(pocetna, "metrics", return_value=ms), \
                mock.patch.object(pocetna, "db_totals", return_value=(25_790, 12_000_000, 11)):
            html = pocetna.data_foot(NOW)
        self.assertIn("Podaci alata: 3 638 novih zapisa ovaj tjedan", visible(html))
        self.assertIn('data-dlg="pg-data"', html)
        dlg = html[html.index("<dialog"):]
        self.assertIn("Tokeni analizirani", dlg)
        self.assertIn("+20 ovaj tjedan · prošli +4", dlg)
        self.assertIn("~25 790", dlg)
        self.assertNotIn("🪙", html)                                        # no emoji in the new rows


class Page(unittest.TestCase):
    def test_order_and_no_repeated_blocks(self):
        row = R.row
        with mock.patch.object(prijedlog, "pregled_parts", return_value=parts(PICKS, wallets=[WALLET])), \
                mock.patch.object(pocetna, "kol_row", return_value=row("@Humanevolvd")), \
                mock.patch.object(pocetna, "autopilot_row", return_value=row("Autopilot")), \
                mock.patch.object(pocetna, "win_row", return_value=row("Najveći pogodak")), \
                mock.patch.object(pocetna, "strategy_row", return_value=row("Strategije u demu")), \
                mock.patch.object(pocetna, "wallets_row", return_value=row("Novčanici")), \
                mock.patch.object(pocetna, "data_foot", return_value='<a class=ms-footlink>Podaci alata: 1 novi zapis</a>'):
            title, body = pocetna.page({})
        self.assertEqual(title, "Pregled")
        seen = visible(body)
        order = ["Pregled", "osvježeno", "Najbolji ulaz sada", "Vrijedi pratiti",
                 "@Humanevolvd", "Vfdn…At74", "Ovaj tjedan", "Autopilot", "Najveći pogodak", "Strategije u demu",
                 "Novčanici", "Podaci alata"]
        idx = [seen.index(s) for s in order]
        self.assertEqual(idx, sorted(idx), order)
        self.assertIn('<div class="ms-page pg">', body)
        for gone in ("Brzi linkovi", "Zanimljivo sada", "Koliko podataka alat ima", "Najprofitabilnija strategija", "ⓘ"):
            self.assertNotIn(gone, seen)
        self.assertEqual(body.count('id=pdj '), 1)                         # the box once, only here
        self.assertEqual(seen.lower().count("prijedlog za danas"), 1)      # the link to the pop-up, not a block
        self.assertIsNone(EMOJI.search(seen))
        self.assertIn("id=pdj-age", body)

    def test_a_broken_part_does_not_take_the_page_down(self):
        with mock.patch.object(prijedlog, "pregled_parts", side_effect=RuntimeError("x")), \
                mock.patch.object(pocetna, "kol_row", side_effect=RuntimeError("y")), \
                mock.patch.object(pocetna, "autopilot_row", return_value=None), \
                mock.patch.object(pocetna, "win_row", return_value=None), \
                mock.patch.object(pocetna, "strategy_row", side_effect=sqlite3.OperationalError("z")), \
                mock.patch.object(pocetna, "wallets_row", return_value=None), \
                mock.patch.object(pocetna, "data_foot", return_value=""):
            _t, body = pocetna.page({})
        self.assertIn("Prijedlog se trenutno ne može složiti", body)
        self.assertNotIn("Ovaj tjedan", body)
        self.assertIn("ms-dlg", body)                                       # the pop-up look is still there


if __name__ == "__main__":
    unittest.main()
