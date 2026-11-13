"""Runs the Node.js test scripts for the frontend files (api.js,
integration.js). Skipped automatically if Node.js is not installed.

Run from the project root:  python -m unittest discover -s backend/tests -t .
"""

import os
import shutil
import subprocess
import sys
import tempfile
import unittest

from backend.tests.test_http import LiveServer

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(os.path.dirname(HERE))
JS_DIR = os.path.join(HERE, "js")
NODE = shutil.which("node")


@unittest.skipUnless(NODE, "Node.js not installed - frontend JS tests skipped")
class FrontendJavaScriptTests(unittest.TestCase):
    def run_script(self, name, *extra, env=None):
        result = subprocess.run(
            [NODE, os.path.join(JS_DIR, name), PROJECT_ROOT] + list(extra),
            capture_output=True, text=True, timeout=300,
            env=dict(os.environ, **(env or {})))
        self.assertEqual(result.returncode, 0,
                         "\n" + result.stdout + result.stderr)

    def test_api_js(self):
        self.run_script("api_js_test.js")

    def test_integration_js_against_real_server(self):
        """script.js + api.js + integration.js in one page, talking to a
        real Flask server on a temporary database."""
        tmp = tempfile.mkdtemp()
        db_path = os.path.join(tmp, "frontend.db")
        live = LiveServer(db_path)
        try:
            # PT_PYTHON / PT_DB let the JS test run the real sample-data
            # script against this temporary database.
            self.run_script("integration_js_test.js", live.base,
                            env={"PT_PYTHON": sys.executable, "PT_DB": db_path})
        finally:
            live.stop()
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
