"""WhatsApp digest: message text, app news shown once, page, gateway requests. No network."""
import json
import os
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from league import store  # noqa: E402
from share import digest, send as gateway  # noqa: E402

MINT = "So11111111111111111111111111111111111111112"
NOW = time.time()


class WhatsApp(unittest.TestCase):
    def setUp(self):
        d = tempfile.mkdtemp()
        store.DB = os.path.join(d, "league.db")
        digest.STATE = os.path.join(d, "whatsapp-state.json")
        self.news = os.path.join(d, "novosti.json")
        today = time.strftime("%Y-%m-%d", time.localtime(NOW))
        with open(self.news, "w") as f:
            json.dump([{"datum": today, "naslov": "Copy trading", "tekst": "prati wallet."},
                       {"datum": "2020-01-01", "tekst": "staro"}], f)
        digest.NEWS = self.news
        import ui.paper
        self._market = ui.paper.market
        self.addCleanup(setattr, ui.paper, "market", self._market)
        ui.paper.market = lambda mints: {m: (2.0, 1e6, None, 2e6) for m in mints}
        con = store.connect()
        store.buy(con, "Ivan", MINT, "SOL", 100, 1.0, 1e6, mcap=1e6)
        con.close()
        for k in list(os.environ):
            if k.startswith("WHATSAPP_"):
                del os.environ[k]

    def test_text_and_news_once(self):
        d = digest.collect(NOW, with_tokens=False)
        txt = digest.text(d)
        self.assertIn("*ŠTO JE NOVO*", txt)
        self.assertIn("▪️ *Copy trading*: prati wallet.", txt)
        self.assertNotIn("staro", txt)
        self.assertIn("🥇 Ivan", txt)
        self.assertIn("🚀 Najbolji: Ivan · *SOL*", txt)
        self.assertIn("\n\n", txt)
        digest.mark_shared("copied", NOW)
        self.assertNotIn("ŠTO JE NOVO", digest.build(NOW, with_tokens=False))      # already went to the group
        self.assertIn("Copy trading", digest.text(digest.collect(NOW, with_tokens=False, repeat=True)))

    def test_page(self):
        from ui import whatsapp
        title, body = whatsapp.page({})
        self.assertEqual(title, "Za WhatsApp")
        self.assertIn("Pošalji u WhatsApp", body)
        self.assertIn("<b>Copy trading</b>", body)
        self.assertIn('id=wadata>{"date"', body)
        self.assertIn("Whapi.cloud", body)                      # paid option explained while sending is off
        whatsapp.post_shared()
        self.assertTrue(digest.load_state().get("copied_ts"))

    def test_gateways(self):
        self.assertIn("WHATSAPP_PROVIDER", gateway.missing())
        with self.assertRaises(RuntimeError):
            gateway.send("x")
        os.environ.update(WHATSAPP_PROVIDER="whapi", WHATSAPP_TOKEN="t", WHATSAPP_GROUP_ID="1@g.us")
        url, h, body = gateway.request("hi")
        self.assertEqual((url, h["Authorization"], body), ("https://gate.whapi.cloud/messages/text", "Bearer t",
                                                          {"to": "1@g.us", "body": "hi"}))
        os.environ["WHATSAPP_PROVIDER"] = "green-api"
        self.assertEqual(gateway.missing(), ["WHATSAPP_INSTANCE_ID"])
        os.environ["WHATSAPP_INSTANCE_ID"] = "77"
        url, _, body = gateway.request("hi")
        self.assertEqual(url, "https://api.green-api.com/waInstance77/sendMessage/t")
        self.assertEqual(body, {"chatId": "1@g.us", "message": "hi"})


if __name__ == "__main__":
    unittest.main()
