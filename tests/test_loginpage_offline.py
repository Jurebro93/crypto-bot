import unittest

from ui import loginpage


class LoginPageTest(unittest.TestCase):
    def test_croatian(self):
        h = loginpage.html("/natjecanje", "", "", (), "https://memesonar.app", "hr")
        for s in ("Dobro došao natrag", "Prijavi se", "Samo za gledanje", "60 dana", "Zatraži pristup",
                  "https://memesonar.app/hr#pristup", 'name=next value="/natjecanje"', "action=/prijava",
                  "autocomplete=current-password", "translate=no", "/jezik?l=en"):
            self.assertIn(s, h)

    def test_english_error_and_escaping(self):
        h = loginpage.html("/", '"><x>', "Pogrešno ime ili lozinka.", ("Ivan",), "", "en")
        for s in ("Welcome back", "Wrong name or password.", "View only", "Request access", "/#pristup",
                  "Passwords are not set yet for: Ivan", "<html lang=en"):
            self.assertIn(s, h)
        self.assertNotIn('"><x>', h)


if __name__ == "__main__":
    unittest.main()
