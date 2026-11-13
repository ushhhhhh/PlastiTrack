"""Real-HTTP regression tests.

These start an actual multi-threaded Werkzeug HTTP server (the same server
`python -m backend.app` uses) on a free local port and talk to it with
urllib, so they cover things the Flask test client cannot: concurrent
requests, persistence across a server restart, request-size limits and
static file delivery.

Run from the project root:  python -m unittest discover -s backend/tests -t .
"""

import json
import logging
import os
import shutil
import tempfile
import threading
import unittest
import urllib.error
import urllib.request

from werkzeug.serving import make_server

from backend.app import create_app

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))
DEFAULTS = {"bottle": 7, "bag": 5, "straw": 3, "cutlery": 2, "box": 2,
            "cup": 4, "wrap": 6}


class LiveServer:
    def __init__(self, db_path):
        # Keep test output readable: no per-request access log lines.
        logging.getLogger("werkzeug").setLevel(logging.ERROR)
        self.app = create_app({"DATABASE": db_path})
        self.server = make_server("127.0.0.1", 0, self.app, threaded=True)
        self.base = "http://127.0.0.1:%d" % self.server.server_port
        self.thread = threading.Thread(target=self.server.serve_forever,
                                       daemon=True)
        self.thread.start()

    def stop(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(5)

    def request(self, method, path, body=None, raw=None,
                content_type="application/json"):
        data = raw if raw is not None else (
            json.dumps(body).encode() if body is not None else None)
        req = urllib.request.Request(self.base + path, data=data,
                                     method=method)
        if data is not None:
            req.add_header("Content-Type", content_type)
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                return resp.status, dict(resp.headers), resp.read()
        except urllib.error.HTTPError as exc:
            return exc.code, dict(exc.headers), exc.read()

    def json(self, method, path, body=None, **kw):
        status, _headers, content = self.request(method, path, body, **kw)
        return status, json.loads(content) if content else None


def burst(fn, n=12):
    """Call fn from n threads released at the same instant."""
    results, barrier = [], threading.Barrier(n)
    lock = threading.Lock()

    def run():
        barrier.wait()
        value = fn()
        with lock:
            results.append(value)

    threads = [threading.Thread(target=run) for _ in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(30)
    return sorted(results)


class LiveServerTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        # Folder deliberately does not exist yet.
        self.db_path = os.path.join(self.tmp, "new", "folder", "pt.db")
        self.live = LiveServer(self.db_path)

    def tearDown(self):
        self.live.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)


class DatabaseLifecycleTests(LiveServerTestCase):
    def test_database_created_in_missing_folder(self):
        self.assertTrue(os.path.exists(self.db_path))
        status, body = self.live.json("GET", "/api/health")
        self.assertEqual((status, body["database"]), (200, "ok"))

    def test_data_persists_across_server_restart(self):
        self.live.json("POST", "/api/history",
                       {"user_id": "riya_22", "quantities": DEFAULTS})
        self.live.json("POST", "/api/challenges/join",
                       {"user_id": "riya_22", "challenge_id": 1})
        self.live.json("POST", "/api/challenges/complete",
                       {"user_id": "riya_22", "challenge_id": 1})
        _, team = self.live.json("POST", "/api/campus/teams",
                                 {"name": "Persist Team"})
        self.live.json("POST", "/api/campus/join",
                       {"user_id": "riya_22", "team_id": team["id"]})
        _, before = self.live.json("GET", "/api/passport?user_id=riya_22")

        self.live.stop()                       # "restart Flask"
        self.live = LiveServer(self.db_path)

        _, after = self.live.json("GET", "/api/passport?user_id=riya_22")
        self.assertEqual(before, after)
        self.assertEqual(after["measured_footprint"]["total_records"], 1)
        self.assertEqual(after["self_reported_actions"]
                         ["completed_challenges"], 1)
        self.assertEqual(after["team"]["team_name"], "Persist Team")


class ConcurrencyRegressionTests(LiveServerTestCase):
    """Before the audit fixes these returned HTTP 500 (UNIQUE constraint
    failed) or let the same challenge be completed several times."""

    def test_concurrent_duplicate_challenge_join(self):
        codes = burst(lambda: self.live.json(
            "POST", "/api/challenges/join",
            {"user_id": "racer_1", "challenge_id": 3})[0])
        self.assertNotIn(500, codes)
        self.assertEqual(codes.count(201), 1, codes)

    def test_concurrent_duplicate_challenge_completion(self):
        self.live.json("POST", "/api/challenges/join",
                       {"user_id": "racer_1", "challenge_id": 3})
        codes = burst(lambda: self.live.json(
            "POST", "/api/challenges/complete",
            {"user_id": "racer_1", "challenge_id": 3})[0])
        self.assertEqual(codes.count(200), 1, codes)
        self.assertEqual(codes.count(409), len(codes) - 1, codes)

    def test_concurrent_duplicate_team_creation(self):
        codes = burst(lambda: self.live.json(
            "POST", "/api/campus/teams", {"name": "Race Team"})[0])
        self.assertNotIn(500, codes)
        self.assertEqual(codes.count(201), 1, codes)

    def test_concurrent_duplicate_team_join(self):
        _, team = self.live.json("POST", "/api/campus/teams",
                                 {"name": "Race Team"})
        codes = burst(lambda: self.live.json(
            "POST", "/api/campus/join",
            {"user_id": "racer_2", "team_id": team["id"]})[0])
        self.assertNotIn(500, codes)
        self.assertEqual(codes.count(201), 1, codes)
        _, teams = self.live.json("GET", "/api/campus/teams")
        self.assertEqual(teams["teams"][0]["member_count"], 1)

    def test_concurrent_first_saves_for_new_user(self):
        codes = burst(lambda: self.live.json(
            "POST", "/api/history",
            {"user_id": "racer_3", "quantities": DEFAULTS})[0])
        self.assertEqual(codes, [201] * 12)
        _, body = self.live.json("GET", "/api/history?user_id=racer_3")
        self.assertEqual(body["total_records"], 12)


class HttpBehaviourTests(LiveServerTestCase):
    def test_oversized_body_rejected_with_json_413(self):
        raw = json.dumps({"quantities": DEFAULTS,
                          "pad": "x" * 200_000}).encode()
        status, body = self.live.json("POST", "/api/calculate", raw=raw)
        self.assertEqual(status, 413)
        self.assertIn("error", body)

    def test_static_files_served_with_correct_types(self):
        for path, name, ctype in (("/", "index.html", "text/html"),
                                  ("/style.css", "style.css", "text/css"),
                                  ("/script.js", "script.js", "javascript")):
            status, headers, content = self.live.request("GET", path)
            self.assertEqual(status, 200, path)
            self.assertIn(ctype, headers["Content-Type"])
            with open(os.path.join(PROJECT_ROOT, name), "rb") as fh:
                self.assertEqual(content, fh.read(), name)

    def test_wrong_method_with_body_returns_json_405(self):
        for method, path in (("PUT", "/api/history"),
                             ("DELETE", "/api/history"),
                             ("POST", "/api/passport")):
            status, body = self.live.json(method, path, {})
            self.assertEqual(status, 405, (method, path))
            self.assertIn("error", body)


if __name__ == "__main__":
    unittest.main()
