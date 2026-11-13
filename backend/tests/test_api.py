"""API, database and service tests. Each test uses its own temporary
SQLite file, so the real database/plastitrack.db is never touched.

Run from the project root:  python -m unittest discover -s backend/tests -t .
"""

import os
import shutil
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

from backend.app import create_app
from backend.database import get_db
from backend.services import footprint_service

DEFAULTS = {"bottle": 7, "bag": 5, "straw": 3, "cutlery": 2, "box": 2,
            "cup": 4, "wrap": 6}                       # 211.5 g/week
LOWER = {"bottle": 2, "bag": 1, "cup": 1}              #  40   g/week
HIGHER = dict(DEFAULTS, bottle=20)                     # 367.5 g/week


class ApiTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmp, "test.db")
        self.app = create_app({"TESTING": True, "DATABASE": self.db_path})
        self.client = self.app.test_client()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    # helpers ----------------------------------------------------------
    def save(self, user, quantities, status=201):
        r = self.client.post("/api/history",
                             json={"user_id": user, "quantities": quantities})
        self.assertEqual(r.status_code, status, r.get_json())
        return r.get_json()

    def save_at(self, user, quantities, when):
        """Save with a fixed timestamp (not possible through the API)."""
        with self.app.app_context():
            footprint_service.save_calculation(
                get_db(), user, quantities,
                recorded_at=when.isoformat(timespec="seconds"))

    def join_and_complete(self, user, challenge):
        self.assertIn(self.client.post("/api/challenges/join", json={
            "user_id": user, "challenge_id": challenge}).status_code,
            (200, 201))
        r = self.client.post("/api/challenges/complete", json={
            "user_id": user, "challenge_id": challenge})
        self.assertEqual(r.status_code, 200, r.get_json())
        return r.get_json()

    def make_team(self, name):
        r = self.client.post("/api/campus/teams", json={"name": name})
        self.assertEqual(r.status_code, 201, r.get_json())
        return r.get_json()["id"]

    def join_team(self, user, team_id, status=201):
        r = self.client.post("/api/campus/join",
                             json={"user_id": user, "team_id": team_id})
        self.assertEqual(r.status_code, status, r.get_json())
        return r.get_json()


class HealthAndFrontendTests(ApiTestCase):
    def test_health(self):
        r = self.client.get("/api/health")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.get_json()["database"], "ok")

    def test_tables_created_automatically(self):
        conn = sqlite3.connect(self.db_path)
        names = {row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        conn.close()
        self.assertTrue({"users", "footprints", "footprint_items",
                         "challenges", "user_challenges", "teams",
                         "team_members"} <= names)

    def test_original_frontend_served_unchanged(self):
        root = os.path.dirname(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))))
        for url, name in (("/", "index.html"), ("/style.css", "style.css"),
                          ("/script.js", "script.js")):
            r = self.client.get(url)
            self.assertEqual(r.status_code, 200)
            with open(os.path.join(root, name), "rb") as fh:
                self.assertEqual(r.data, fh.read())
            r.close()

    def test_private_files_not_served(self):
        for url in ("/backend/app.py", "/database/plastitrack.db",
                    "/.git/config", "/README.md"):
            r = self.client.get(url)
            self.assertEqual(r.status_code, 404, url)
            self.assertIn("error", r.get_json())


class CalculateApiTests(ApiTestCase):
    def test_calculate(self):
        r = self.client.post("/api/calculate", json={"quantities": DEFAULTS})
        self.assertEqual(r.status_code, 200)
        body = r.get_json()
        self.assertAlmostEqual(body["weekly_grams"], 211.5)
        self.assertEqual(body["eco_score"], 79)
        self.assertEqual(len(body["categories"]), 7)

    def test_calculate_does_not_save(self):
        self.client.post("/api/calculate", json={"quantities": DEFAULTS})
        conn = sqlite3.connect(self.db_path)
        self.assertEqual(conn.execute(
            "SELECT COUNT(*) FROM footprints").fetchone()[0], 0)
        conn.close()

    def test_negative_input_400(self):
        r = self.client.post("/api/calculate",
                             json={"quantities": {"bottle": -2}})
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.get_json()["details"]["bottle"],
                         "must not be negative")

    def test_missing_body_400(self):
        r = self.client.post("/api/calculate", data="not json",
                             content_type="text/plain")
        self.assertEqual(r.status_code, 400)

    def test_items_endpoint(self):
        body = self.client.get("/api/items").get_json()
        self.assertEqual(len(body["items"]), 7)
        self.assertEqual(body["co2e_per_kg_plastic"], 3.0)


class HistoryTests(ApiTestCase):
    def test_save_and_retrieve(self):
        saved = self.save("riya_22", DEFAULTS)
        record = saved["record"]
        self.assertEqual(record["user_id"], "riya_22")
        self.assertAlmostEqual(record["weekly_grams"], 211.5)
        self.assertAlmostEqual(record["annual_co2e_kg"], 32.994)
        self.assertEqual(record["eco_score"], 79)
        bottle = next(c for c in record["categories"]
                      if c["item_id"] == "bottle")
        self.assertEqual(bottle["weekly_quantity"], 7)
        self.assertEqual(bottle["weekly_grams"], 84)

        self.save("riya_22", LOWER)
        body = self.client.get("/api/history?user_id=riya_22").get_json()
        self.assertEqual(body["total_records"], 2)
        self.assertAlmostEqual(body["records"][0]["weekly_grams"], 40)  # newest
        self.assertEqual(len(body["records"][1]["categories"]), 7)

    def test_server_recalculates_ignoring_client_results(self):
        r = self.client.post("/api/history", json={
            "user_id": "riya_22", "quantities": DEFAULTS,
            "weekly_grams": 1, "eco_score": 100})
        self.assertEqual(r.get_json()["record"]["eco_score"], 79)

    def test_history_is_per_user(self):
        self.save("riya_22", DEFAULTS)
        self.save("dev_01", LOWER)
        body = self.client.get("/api/history?user_id=dev_01").get_json()
        self.assertEqual(body["total_records"], 1)

    def test_limit(self):
        for _ in range(3):
            self.save("riya_22", DEFAULTS)
        body = self.client.get(
            "/api/history?user_id=riya_22&limit=2").get_json()
        self.assertEqual(body["returned"], 2)
        self.assertEqual(body["total_records"], 3)
        self.assertEqual(self.client.get(
            "/api/history?user_id=riya_22&limit=abc").status_code, 400)
        self.assertEqual(self.client.get(
            "/api/history?user_id=riya_22&limit=0").status_code, 400)

    def test_invalid_user_and_quantities(self):
        self.save("", DEFAULTS, status=400)
        self.save("a b c", DEFAULTS, status=400)
        self.save("riya_22", {"cup": -1}, status=400)
        self.save("riya_22", "lots", status=400)
        self.assertEqual(self.client.get("/api/history").status_code, 400)
        # Nothing invalid was stored.
        conn = sqlite3.connect(self.db_path)
        self.assertEqual(conn.execute(
            "SELECT COUNT(*) FROM footprints").fetchone()[0], 0)
        conn.close()

    def test_comparison_decreasing(self):
        self.save("riya_22", DEFAULTS)
        self.save("riya_22", LOWER)
        body = self.client.get(
            "/api/history/comparison?user_id=riya_22").get_json()
        self.assertEqual(body["trend"], "decreasing")
        self.assertAlmostEqual(body["change"]["weekly_grams"], -171.5)
        self.assertAlmostEqual(body["change"]["weekly_percent"], -81.09)
        self.assertEqual(body["change"]["eco_score"], 96 - 79)
        bottle = next(c for c in body["category_changes"]
                      if c["item_id"] == "bottle")
        self.assertEqual(bottle["change_weekly_grams"], -60)

    def test_comparison_increasing_and_unchanged(self):
        self.save("riya_22", DEFAULTS)
        self.save("riya_22", HIGHER)
        self.assertEqual(self.client.get(
            "/api/history/comparison?user_id=riya_22").get_json()["trend"],
            "increasing")
        self.save("riya_22", HIGHER)
        self.assertEqual(self.client.get(
            "/api/history/comparison?user_id=riya_22").get_json()["trend"],
            "unchanged")

    def test_comparison_insufficient_data(self):
        body = self.client.get(
            "/api/history/comparison?user_id=nobody").get_json()
        self.assertEqual(body["trend"], "insufficient_data")
        self.save("riya_22", DEFAULTS)
        body = self.client.get(
            "/api/history/comparison?user_id=riya_22").get_json()
        self.assertEqual(body["trend"], "insufficient_data")
        self.assertIsNone(body["previous"])


class ChallengeTests(ApiTestCase):
    def test_list_challenges(self):
        body = self.client.get("/api/challenges").get_json()
        self.assertEqual(len(body["challenges"]), 5)
        self.assertIn("self-reported", body["note"])

    def test_join_and_complete(self):
        r = self.client.post("/api/challenges/join",
                             json={"user_id": "riya_22", "challenge_id": 1})
        self.assertEqual(r.status_code, 201)
        self.assertEqual(r.get_json()["status"], "joined")
        # Joining twice is harmless.
        r = self.client.post("/api/challenges/join",
                             json={"user_id": "riya_22", "challenge_id": 1})
        self.assertEqual(r.status_code, 200)

        body = self.client.get("/api/challenges?user_id=riya_22").get_json()
        self.assertEqual(body["challenges"][0]["status"], "joined")
        self.assertEqual(body["challenges"][1]["status"], "not_joined")

        r = self.client.post("/api/challenges/complete",
                             json={"user_id": "riya_22", "challenge_id": 1})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.get_json()["entry"]["status"], "completed")
        self.assertEqual([b["code"] for b in r.get_json()["badges"]],
                         ["first-step"])

    def test_join_by_slug(self):
        r = self.client.post("/api/challenges/join", json={
            "user_id": "riya_22", "challenge_id": "reusable-shopping-bag"})
        self.assertEqual(r.status_code, 201)
        self.assertEqual(r.get_json()["challenge"]["id"], 2)

    def test_complete_errors(self):
        # Not joined yet -> 409
        r = self.client.post("/api/challenges/complete",
                             json={"user_id": "riya_22", "challenge_id": 1})
        self.assertEqual(r.status_code, 409)
        self.join_and_complete("riya_22", 1)
        # Completed twice -> 409; re-joining a completed one -> 409
        self.assertEqual(self.client.post("/api/challenges/complete", json={
            "user_id": "riya_22", "challenge_id": 1}).status_code, 409)
        self.assertEqual(self.client.post("/api/challenges/join", json={
            "user_id": "riya_22", "challenge_id": 1}).status_code, 409)
        # Unknown challenge -> 404; missing fields -> 400
        self.assertEqual(self.client.post("/api/challenges/join", json={
            "user_id": "riya_22", "challenge_id": 99}).status_code, 404)
        self.assertEqual(self.client.post("/api/challenges/join", json={
            "user_id": "riya_22"}).status_code, 400)
        self.assertEqual(self.client.post("/api/challenges/join", json={
            "challenge_id": 1}).status_code, 400)

    def test_badges_and_progress(self):
        for cid in range(1, 6):
            self.join_and_complete("riya_22", cid)
        body = self.client.get(
            "/api/challenges/progress?user_id=riya_22").get_json()
        self.assertEqual(body["completed_count"], 5)
        codes = [b["code"] for b in body["badges"]]
        self.assertEqual(codes, ["first-step", "habit-builder",
                                 "plastic-free-champion"])
        self.assertTrue(all(b["basis"] == "self_reported"
                            for b in body["badges"]))

    def test_measured_badges(self):
        self.save("riya_22", DEFAULTS)
        self.save("riya_22", LOWER)
        self.save("riya_22", LOWER)
        body = self.client.get(
            "/api/challenges/progress?user_id=riya_22").get_json()
        badges = {b["code"]: b["basis"] for b in body["badges"]}
        self.assertEqual(badges, {"footprint-tracker": "measured",
                                  "measured-reducer": "measured"})

    def test_completing_challenge_adds_no_savings(self):
        self.save("riya_22", DEFAULTS)
        before = self.client.get(
            "/api/passport?user_id=riya_22").get_json()["measured_footprint"]
        for cid in range(1, 6):
            self.join_and_complete("riya_22", cid)
        after = self.client.get(
            "/api/passport?user_id=riya_22").get_json()["measured_footprint"]
        self.assertEqual(before, after)


class PassportTests(ApiTestCase):
    def test_unknown_user_404(self):
        self.assertEqual(self.client.get(
            "/api/passport?user_id=ghost").status_code, 404)
        self.assertEqual(self.client.get("/api/passport").status_code, 400)

    def test_passport_values(self):
        t0 = datetime(2026, 9, 1, tzinfo=timezone.utc)
        # 211.5 g -> 211.5 g (2 weeks) -> 40 g (2 weeks)
        self.save_at("riya_22", DEFAULTS, t0)
        self.save_at("riya_22", DEFAULTS, t0 + timedelta(weeks=2))
        self.save_at("riya_22", LOWER, t0 + timedelta(weeks=4))
        self.join_and_complete("riya_22", 1)

        p = self.client.get("/api/passport?user_id=riya_22").get_json()
        m = p["measured_footprint"]
        self.assertEqual(m["total_records"], 3)
        self.assertEqual(m["latest_eco_score"], 96)  # round(100 - 4)
        self.assertEqual(m["change_since_baseline"]["trend"], "decreasing")
        self.assertAlmostEqual(m["change_since_baseline"]["weekly_grams"],
                               -171.5)
        self.assertAlmostEqual(
            m["change_since_baseline"]["annualised_reduction_kg_if_sustained"],
            171.5 * 52 / 1000)

        est = m["estimated_cumulative_reduction"]
        self.assertTrue(est["sufficient_data"])
        self.assertAlmostEqual(est["weeks_covered"], 4)
        # Period 1: no change -> 0. Period 2: average use (211.5+40)/2 =
        # 125.75 g, i.e. 85.75 g/week below baseline for 2 weeks = 171.5 g.
        self.assertAlmostEqual(est["estimated_kg"], 0.1715)
        self.assertAlmostEqual(est["estimated_co2e_kg"], 0.5145)

        s = p["self_reported_actions"]
        self.assertEqual(s["completed_challenges"], 1)
        self.assertIn("first-step", [b["code"] for b in p["badges"]])

    def test_cumulative_negative_when_usage_rises(self):
        t0 = datetime(2026, 9, 1, tzinfo=timezone.utc)
        self.save_at("dev_01", DEFAULTS, t0)
        self.save_at("dev_01", HIGHER, t0 + timedelta(weeks=1))
        est = self.client.get("/api/passport?user_id=dev_01").get_json()[
            "measured_footprint"]["estimated_cumulative_reduction"]
        # -(367.5 - 211.5) / 2 g/week for 1 week = -78 g
        self.assertAlmostEqual(est["estimated_kg"], -0.078)

    def test_insufficient_data(self):
        self.save("riya_22", DEFAULTS)
        m = self.client.get("/api/passport?user_id=riya_22").get_json()[
            "measured_footprint"]
        self.assertFalse(m["estimated_cumulative_reduction"][
            "sufficient_data"])
        self.assertIsNone(m["estimated_cumulative_reduction"]["estimated_kg"])
        self.assertEqual(m["change_since_baseline"]["trend"],
                         "insufficient_data")


class CampusTests(ApiTestCase):
    def test_team_registration(self):
        tid = self.make_team("Green Warriors")
        self.assertEqual(self.client.post("/api/campus/teams", json={
            "name": "green warriors"}).status_code, 409)  # case-insensitive
        self.assertEqual(self.client.post("/api/campus/teams", json={
            "name": "x"}).status_code, 400)
        self.join_team("riya_22", tid)
        self.join_team("riya_22", tid, status=200)  # idempotent
        other = self.make_team("Eco Rangers")
        self.join_team("riya_22", other, status=409)  # one team per user
        self.join_team("dev_01", 999, status=404)
        self.join_team("dev_01", "abc", status=400)
        teams = self.client.get("/api/campus/teams").get_json()["teams"]
        self.assertEqual({t["name"]: t["member_count"] for t in teams},
                         {"Green Warriors": 1, "Eco Rangers": 0})

    def test_leaderboard_and_summary(self):
        a = self.make_team("Alpha")
        b = self.make_team("Beta")
        c = self.make_team("Gamma")
        # Alpha: riya 211.5 -> 40 (-81.09 %), dev 211.5 -> 211.5 (0 %)
        for user in ("riya_22", "dev_01"):
            self.join_team(user, a)
        self.save("riya_22", DEFAULTS)
        self.save("riya_22", LOWER)
        self.save("dev_01", DEFAULTS)
        self.save("dev_01", DEFAULTS)
        # Beta: sam 211.5 -> 105.75 (-50 %)
        self.join_team("sam_9", b)
        self.save("sam_9", DEFAULTS)
        self.save("sam_9", {"bottle": 3.5, "bag": 2.5, "straw": 1.5,
                            "cutlery": 1, "box": 1, "cup": 2, "wrap": 3})
        # Gamma: one record only -> unranked
        self.join_team("lee_7", c)
        self.save("lee_7", DEFAULTS)
        # Completed challenges must not affect the ranking.
        for cid in range(1, 6):
            self.join_and_complete("lee_7", cid)

        board = self.client.get("/api/campus/leaderboard").get_json()
        ranked = [(e["team_name"], e["rank"], e["average_reduction_percent"])
                  for e in board["leaderboard"]]
        # Beta 50 % beats Alpha's average of (81.09 + 0) / 2 = 40.54 %.
        self.assertEqual(ranked, [("Beta", 1, 50.0), ("Alpha", 2, 40.54)])
        self.assertEqual([t["team_name"] for t in board["unranked"]],
                         ["Gamma"])
        self.assertFalse(board["contains_sample_data"])

        summary = self.client.get("/api/campus/summary").get_json()
        totals = summary["totals"]
        self.assertEqual(totals["teams"], 3)
        self.assertEqual(totals["participants"], 4)
        self.assertEqual(totals["participants_with_comparable_data"], 3)
        self.assertEqual(totals["footprint_records"], 7)
        self.assertEqual(totals["self_reported_challenges_completed"], 5)
        self.assertAlmostEqual(
            totals["total_measured_weekly_reduction_grams"], 171.5 + 105.75)
        alpha = next(t for t in summary["teams"] if t["team_name"] == "Alpha")
        self.assertEqual(alpha["average_latest_weekly_grams"],
                         round((40 + 211.5) / 2, 2))

    def test_sample_data_flagged_and_filterable(self):
        from backend.services import campus_service
        with self.app.app_context():
            db = get_db()
            team = campus_service.create_team(db, "[SAMPLE] Demo",
                                              is_sample=True)
            campus_service.join_team(db, "sample_x", team["id"],
                                     is_sample=True)
        self.make_team("Real Team")
        board = self.client.get("/api/campus/summary").get_json()
        self.assertTrue(board["contains_sample_data"])
        flagged = {t["team_name"]: t["is_sample"] for t in board["teams"]}
        self.assertEqual(flagged, {"[SAMPLE] Demo": True, "Real Team": False})
        filtered = self.client.get(
            "/api/campus/summary?include_sample=false").get_json()
        self.assertEqual([t["team_name"] for t in filtered["teams"]],
                         ["Real Team"])
        self.assertEqual(self.client.get(
            "/api/campus/leaderboard?include_sample=maybe").status_code, 400)


class SampleSeparationRegressionTests(ApiTestCase):
    """Before the audit fixes, real users could take sample ids, create
    '[SAMPLE]' teams and join sample teams, and the seed script would then
    mix sample records into real accounts."""

    def test_api_cannot_use_reserved_sample_user_ids(self):
        for user in ("sample_aarav", "SAMPLE_x1"):
            self.save(user, DEFAULTS, status=400)
            self.assertEqual(self.client.post("/api/challenges/join", json={
                "user_id": user, "challenge_id": 1}).status_code, 400)
        tid = self.make_team("Real Team")
        self.join_team("sample_aarav", tid, status=400)
        # Reading sample users is still allowed (to inspect demo data).
        self.assertEqual(self.client.get(
            "/api/history?user_id=sample_aarav").status_code, 200)

    def test_api_cannot_create_sample_named_team(self):
        for name in ("[SAMPLE] Fake", "[sample] fake"):
            r = self.client.post("/api/campus/teams", json={"name": name})
            self.assertEqual(r.status_code, 400, name)

    def test_real_and_sample_users_cannot_share_teams(self):
        from backend.services import campus_service
        with self.app.app_context():
            sample_team = campus_service.create_team(
                get_db(), "[SAMPLE] Demo", is_sample=True)
        self.join_team("riya_22", sample_team["id"], status=409)
        real_team = self.make_team("Real Team")
        with self.app.app_context():
            with self.assertRaises(Exception):
                campus_service.join_team(get_db(), "sample_x", real_team,
                                         is_sample=True)

    def test_history_and_comparison_report_is_sample(self):
        self.save("riya_22", DEFAULTS)
        for url in ("/api/history?user_id=riya_22",
                    "/api/history/comparison?user_id=riya_22"):
            self.assertIs(self.client.get(url).get_json()["is_sample"], False)
        with self.app.app_context():
            footprint_service.save_calculation(get_db(), "sample_x", DEFAULTS,
                                               sample=True)
        body = self.client.get("/api/history?user_id=sample_x").get_json()
        self.assertIs(body["is_sample"], True)

    def test_seed_refuses_to_touch_legacy_real_user_with_sample_id(self):
        # Simulate a database created before ids were reserved.
        conn = sqlite3.connect(self.db_path)
        conn.execute("INSERT INTO users (id, is_sample, created_at) VALUES "
                     "('sample_aarav', 0, '2026-01-01T00:00:00+00:00')")
        conn.commit()
        conn.close()
        from unittest import mock
        import io
        import contextlib
        from backend import seed_sample_data
        out = io.StringIO()
        with mock.patch.dict(os.environ, {"PLASTITRACK_DB": self.db_path}), \
                contextlib.redirect_stdout(out):
            with self.assertRaises(SystemExit) as ctx:
                seed_sample_data.seed()
        self.assertEqual(ctx.exception.code, 1)
        self.assertIn("NOT loaded", out.getvalue())
        conn = sqlite3.connect(self.db_path)
        self.assertEqual(conn.execute(
            "SELECT COUNT(*) FROM footprints WHERE user_id = 'sample_aarav'"
        ).fetchone()[0], 0)
        self.assertEqual(conn.execute(
            "SELECT COUNT(*) FROM users WHERE is_sample = 1").fetchone()[0], 0)
        self.assertEqual(conn.execute(
            "SELECT COUNT(*) FROM teams").fetchone()[0], 0)
        conn.close()

    def test_seed_and_remove_leave_real_data_intact(self):
        from unittest import mock
        import io
        import contextlib
        from backend import seed_sample_data
        self.save("riya_22", DEFAULTS)
        tid = self.make_team("Real Team")
        self.join_team("riya_22", tid)
        with mock.patch.dict(os.environ, {"PLASTITRACK_DB": self.db_path}), \
                contextlib.redirect_stdout(io.StringIO()):
            seed_sample_data.seed()
        summary = self.client.get("/api/campus/summary").get_json()
        self.assertTrue(summary["contains_sample_data"])
        conn = sqlite3.connect(self.db_path)
        seed_sample_data.remove(conn)
        conn.close()
        summary = self.client.get("/api/campus/summary").get_json()
        self.assertFalse(summary["contains_sample_data"])
        self.assertEqual([t["team_name"] for t in summary["teams"]],
                         ["Real Team"])
        self.assertEqual(self.client.get("/api/history?user_id=riya_22")
                         .get_json()["total_records"], 1)


class TransactionAndIsolationTests(ApiTestCase):
    def test_failed_save_leaves_no_partial_data(self):
        from unittest import mock
        from backend import models
        original = models.insert_footprint

        def insert_then_fail(*args, **kwargs):
            original(*args, **kwargs)
            raise RuntimeError("simulated crash after insert")

        app = create_app({"TESTING": False, "DATABASE": self.db_path})
        with mock.patch.object(models, "insert_footprint", insert_then_fail):
            r = app.test_client().post("/api/history", json={
                "user_id": "riya_22", "quantities": DEFAULTS})
        self.assertEqual(r.status_code, 500)
        conn = sqlite3.connect(self.db_path)
        for table in ("users", "footprints", "footprint_items"):
            self.assertEqual(conn.execute(
                "SELECT COUNT(*) FROM %s" % table).fetchone()[0], 0, table)
        conn.close()

    def test_users_cannot_see_each_others_data(self):
        self.save("riya_22", DEFAULTS)
        self.save("riya_22", LOWER)
        self.join_and_complete("riya_22", 1)
        self.save("dev_01", HIGHER)
        dev = self.client.get("/api/history?user_id=dev_01").get_json()
        self.assertEqual([r["user_id"] for r in dev["records"]], ["dev_01"])
        cmp_ = self.client.get(
            "/api/history/comparison?user_id=dev_01").get_json()
        self.assertEqual(cmp_["trend"], "insufficient_data")
        prog = self.client.get(
            "/api/challenges/progress?user_id=dev_01").get_json()
        self.assertEqual(prog["completed_count"], 0)
        self.assertEqual(prog["badges"], [])
        passport = self.client.get("/api/passport?user_id=dev_01").get_json()
        self.assertEqual(passport["measured_footprint"]["total_records"], 1)
        self.assertEqual(passport["self_reported_actions"]
                         ["completed_challenges"], 0)

    def test_user_ids_are_case_sensitive(self):
        self.save("riya_22", DEFAULTS)
        body = self.client.get("/api/history?user_id=RIYA_22").get_json()
        self.assertEqual(body["total_records"], 0)

    def test_complete_for_unknown_user_is_409(self):
        r = self.client.post("/api/challenges/complete",
                             json={"user_id": "ghost_1", "challenge_id": 1})
        self.assertEqual(r.status_code, 409)

    def test_health_reports_missing_tables(self):
        conn = sqlite3.connect(self.db_path)
        conn.execute("DROP TABLE team_members")
        conn.commit()
        conn.close()
        r = self.client.get("/api/health")
        self.assertEqual(r.status_code, 503)
        self.assertEqual(r.get_json()["database"], "missing_tables")

    def test_restart_recreates_missing_tables(self):
        conn = sqlite3.connect(self.db_path)
        conn.execute("DROP TABLE team_members")
        conn.commit()
        conn.close()
        app = create_app({"TESTING": True, "DATABASE": self.db_path})
        self.assertEqual(app.test_client().get(
            "/api/health").get_json()["database"], "ok")


class ErrorHandlingTests(ApiTestCase):
    def test_unknown_api_route_404_json(self):
        r = self.client.get("/api/does-not-exist")
        self.assertEqual(r.status_code, 404)
        self.assertEqual(r.get_json()["status"], 404)

    def test_wrong_method_405_json(self):
        r = self.client.get("/api/calculate")
        self.assertEqual(r.status_code, 405)
        self.assertIn("error", r.get_json())

    def test_json_array_body_400(self):
        r = self.client.post("/api/history", json=[1, 2])
        self.assertEqual(r.status_code, 400)

    def test_unexpected_error_500_json(self):
        app = create_app({"TESTING": False, "DATABASE": self.db_path})

        @app.get("/api/boom")
        def boom():
            raise RuntimeError("boom")

        r = app.test_client().get("/api/boom")
        self.assertEqual(r.status_code, 500)
        self.assertEqual(r.get_json()["error"], "Internal server error.")


if __name__ == "__main__":
    unittest.main()
