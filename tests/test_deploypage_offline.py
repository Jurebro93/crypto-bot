import os
import subprocess
import unittest
from unittest import mock

from ui import deploypage


class DeployPageTest(unittest.TestCase):
    def test_page_is_self_contained_and_bilingual(self):
        h = deploypage.html()
        for s in ("Radimo super cool deploy", "Shipping a super cool deploy", "Pumpaj", "X-MemeSonar-Deploy",
                  "noindex", "Zadnje dodano", "viewport"):
            self.assertIn(s, h)
        self.assertNotIn("<link rel=stylesheet", h)   # nothing from outside: the server is down when it shows
        self.assertNotIn("src=\"http", h)

    def test_own_address_never_reloads_itself(self):
        # /cekamo-deploy always answers 200 with this page: opened there, it must check and go to "/" instead
        h = deploypage.html()
        self.assertIn("location.pathname==='/cekamo-deploy'?'/'", h)
        self.assertIn("fetch(target,", h)
        self.assertNotIn("onclick=function(){location.reload()}", h)

    def test_service_worker_only_touches_page_loads(self):
        js = deploypage.sw_js()
        self.assertIn("r.mode!=='navigate'", js)
        self.assertIn("[502,503,504]", js)
        self.assertIn(deploypage.PATH, js)
        self.assertIn("serviceWorker.register('/sw.js')", deploypage.register_tag())

    def test_kill_switch(self):
        with mock.patch.dict(os.environ, {"DEPLOY_SW": "0"}):
            self.assertIn("unregister", deploypage.sw_js())
            self.assertIn("unregister", deploypage.register_tag())
            self.assertNotIn("register('/sw.js')", deploypage.register_tag())

    def test_pages_register_the_worker(self):
        from ui import loginpage
        self.assertIn("/sw.js", loginpage.html("/", "", "", (), "", "hr"))

    def test_shared_paths_never_redirect(self):
        import run_ui
        with mock.patch.object(run_ui, "SITE_URL", "https://memesonar.app"), \
                mock.patch.object(run_ui, "APP_URL", "https://app.memesonar.app"):
            for host in ("memesonar.app", "app.memesonar.app"):
                for p in ("/sw.js", "/cekamo-deploy", "/healthz"):
                    self.assertIsNone(run_ui.moved_to_site(host, p, False), (host, p))

    def test_start_sh_disowns_the_stand_in(self):
        sh = open(os.path.join(os.path.dirname(__file__), "..", "start.sh")).read()
        self.assertIn('deploy_wait.py --port "$PORT" & disown', sh)
        self.assertLess(sh.index("deploy_wait.py"), sh.index("ops.health --startup"))
        subprocess.run(["bash", "-n", os.path.join(os.path.dirname(__file__), "..", "start.sh")], check=True)


if __name__ == "__main__":
    unittest.main()
