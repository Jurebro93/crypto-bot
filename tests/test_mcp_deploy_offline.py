"""10.11. (Grok MCP audit 11): while a deploy is in progress the MCP endpoint answers in JSON, not with the HTML page.

deploy_wait.py holds the port while run_ui.py loads; it served the "deploy u tijeku" page (503, text/html) to every
request, so an MCP client (Grok) got HTML it cannot read. Now /mcp gets a JSON-RPC 2.0 error with the request's id
and /api/mcp/* a JSON error, both 503 with Retry-After: 30; browsers keep the page. The app itself (run_ui) routes
/mcp and /api/mcp/* before any page logic, so it never answers them with a page either.
"""
import http.client
import http.server
import json
import threading
import unittest
from unittest import mock

import deploy_wait
from ui import deploypage

PAGE = b"<!doctype html><html><body>Deploy u tijeku</body></html>"


def serve(handler):
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True).start()
    return srv


class StandIn(unittest.TestCase):
    """The real deploy_wait.Wait handler on 127.0.0.1."""

    def setUp(self):
        p = mock.patch.object(deploy_wait.Wait, "body", PAGE)
        p.start()
        self.addCleanup(p.stop)
        self.srv = serve(deploy_wait.Wait)
        self.addCleanup(self.srv.server_close)
        self.addCleanup(self.srv.shutdown)

    def ask(self, method, path, body=None, headers=None):
        c = http.client.HTTPConnection("127.0.0.1", self.srv.server_address[1], timeout=5)
        try:
            c.request(method, path, body=body, headers=headers or {})
            r = c.getresponse()
            return r.status, {k.lower(): v for k, v in r.getheaders()}, r.read()
        finally:
            c.close()

    def test_mcp_post_is_a_json_rpc_error_with_the_request_id(self):
        body = json.dumps({"jsonrpc": "2.0", "id": 42, "method": "tools/call",
                           "params": {"name": "get_wallet_history", "arguments": {"address": "W" * 44}}})
        code, h, out = self.ask("POST", "/mcp", body, {"Content-Type": "application/json",
                                                       "Authorization": "Bearer x", "Accept": "application/json"})
        self.assertEqual(code, 503)
        self.assertEqual(h["content-type"], "application/json")
        self.assertEqual(h["retry-after"], "30")
        self.assertEqual(h["x-memesonar-deploy"], "1")   # ops/uptime still reads it as a deploy
        self.assertEqual(json.loads(out), {"jsonrpc": "2.0", "id": 42, "error": {
            "code": -32001, "message": "MemeSonar deploy in progress, retry later", "data": {"retry_after": 30}}})

    def test_string_id_and_unreadable_body(self):
        _, _, out = self.ask("POST", "/mcp", '{"jsonrpc":"2.0","id":"abc-1","method":"initialize"}')
        self.assertEqual(json.loads(out)["id"], "abc-1")
        for bad in ("{not json", "", "[]", '{"jsonrpc":"2.0","id":{"x":1},"method":"ping"}', '"text"'):
            code, h, out = self.ask("POST", "/mcp", bad, {"Content-Type": "application/json"})
            self.assertEqual((code, h["content-type"]), (503, "application/json"), bad)
            got = json.loads(out)
            self.assertIsNone(got["id"], bad)
            self.assertEqual(got["error"]["code"], -32001, bad)
        _, _, out = self.ask("POST", "/mcp", b"\xff\xfe\x00garbage")
        self.assertIsNone(json.loads(out)["id"])

    def test_batch_gets_one_error_per_request(self):
        batch = [{"jsonrpc": "2.0", "id": 1, "method": "ping"}, {"jsonrpc": "2.0", "method": "notifications/initialized"},
                 {"jsonrpc": "2.0", "id": "b", "method": "tools/list"}]
        _, _, out = self.ask("POST", "/mcp", json.dumps(batch))
        got = json.loads(out)
        self.assertEqual([e["id"] for e in got], [1, "b"])
        self.assertTrue(all(e["error"]["data"]["retry_after"] == 30 for e in got))

    def test_get_and_head_of_mcp_are_json_too(self):
        code, h, out = self.ask("GET", "/mcp", headers={"Accept": "text/event-stream"})
        self.assertEqual((code, h["content-type"], h["retry-after"]), (503, "application/json", "30"))
        self.assertIsNone(json.loads(out)["id"])
        code, h, out = self.ask("HEAD", "/mcp")
        self.assertEqual((code, h["content-type"], out), (503, "application/json", b""))

    def test_rest_data_endpoints(self):
        for method, path in (("GET", "/api/mcp/signals"), ("GET", "/api/mcp/token?address=abc"),
                             ("POST", "/api/mcp/trade")):
            code, h, out = self.ask(method, path, '{"token":"x"}' if method == "POST" else None)
            self.assertEqual((code, h["content-type"], h["retry-after"]), (503, "application/json", "30"), path)
            self.assertEqual(json.loads(out), {"error": "deploy in progress", "retry_after": 30}, path)

    def test_browser_keeps_the_html_page(self):
        for method, path in (("GET", "/"), ("GET", "/pravi-trade?x=1"), ("POST", "/prijava"), ("GET", "/mcp/"),
                             ("GET", "/api/mcpx"), ("GET", "/mcpdata")):
            code, h, out = self.ask(method, path, "a=1" if method == "POST" else None,
                                    {"Accept": "text/html", "Content-Type": "application/x-www-form-urlencoded"})
            self.assertEqual(code, 503, path)
            self.assertEqual(h["content-type"], "text/html; charset=utf-8", path)
            self.assertEqual(h["retry-after"], "15", path)
            self.assertEqual(out, PAGE, path)
        code, h, _ = self.ask("GET", "/healthz")
        self.assertEqual((code, h["content-type"]), (503, "text/plain; charset=utf-8"))
        code, h, _ = self.ask("GET", "/sw.js")
        self.assertEqual(code, 200)


class Answer(unittest.TestCase):
    def test_only_the_mcp_addresses(self):
        self.assertIsNone(deploypage.api_answer("/", b""))
        self.assertIsNone(deploypage.api_answer("/cekamo-deploy", b""))
        self.assertIsNone(deploypage.api_answer("/hook/chain", b"{}"))
        code, headers, out = deploypage.api_answer("/mcp?x=1", b'{"jsonrpc":"2.0","id":0,"method":"ping"}')
        self.assertEqual((code, headers["Retry-After"]), (503, "30"))
        self.assertEqual(json.loads(out)["id"], 0)
        self.assertIsNone(json.loads(deploypage.api_answer("/mcp", b'{"id":true}')[2])["id"])   # a bool is no id


class AppItself(unittest.TestCase):
    """run_ui answers /mcp and /api/mcp/* before any page logic: JSON whatever happens, never _last_copy's page."""

    def test_app_answers_mcp_in_json_without_building_a_page(self):
        import run_ui
        from ui import mcpapi
        no_page = mock.Mock(side_effect=AssertionError("page logic for /mcp"))
        with mock.patch.object(run_ui, "build_in_child", no_page), mock.patch.object(run_ui, "_last_copy", no_page):
            srv = serve(run_ui.Handler)
            srv.verbose = False
            self.addCleanup(srv.server_close)
            self.addCleanup(srv.shutdown)
            port = srv.server_address[1]

            def ask(method, path, body=None):
                c = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
                try:
                    c.request(method, path, body=body, headers={"Authorization": "Bearer k"})
                    r = c.getresponse()
                    return r.status, r.getheader("Content-Type") or "", r.read()
                finally:
                    c.close()
            with mock.patch.object(mcpapi, "authorized", return_value=False):
                code, ctype, out = ask("POST", "/mcp", b'{"jsonrpc":"2.0","id":1,"method":"ping"}')
                self.assertEqual(code, 401)
                self.assertTrue(ctype.startswith("application/json"))
                json.loads(out)
            with mock.patch.object(mcpapi, "authorized", return_value=None):   # MCP not set up: 404 in JSON
                code, ctype, out = ask("GET", "/api/mcp/signals")
                self.assertEqual(code, 404)
                self.assertTrue(ctype.startswith("application/json"))
            with mock.patch.object(mcpapi, "authorized", return_value=True), \
                    mock.patch.object(mcpapi, "rpc", return_value=(200, '{"jsonrpc":"2.0","id":1,"result":{}}')):
                code, ctype, out = ask("POST", "/mcp", b'{"jsonrpc":"2.0","id":1,"method":"ping"}')
                self.assertEqual((code, json.loads(out)["id"]), (200, 1))
                self.assertTrue(ctype.startswith("application/json"))
        no_page.assert_not_called()


if __name__ == "__main__":
    unittest.main()
