"""Unit tests for backend/calculations.py.

Run from the project root:  python -m unittest discover -s backend/tests -t .
"""

import json
import os
import shutil
import subprocess
import unittest
from decimal import ROUND_HALF_UP, Decimal

from backend import calculations as calc
from backend.calculations import ValidationError, calculate_footprint

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(os.path.dirname(HERE))
SCRIPT_JS = os.path.join(PROJECT_ROOT, "script.js")
NODE = shutil.which("node")

DEFAULTS = {i["id"]: i["def"] for i in calc.ITEMS}


def to_fixed(value, digits):
    """Equivalent of JavaScript Number.prototype.toFixed."""
    q = Decimal(1).scaleb(-digits)
    return str(Decimal(value).quantize(q, rounding=ROUND_HALF_UP))


class DatasetTests(unittest.TestCase):
    def test_dataset_matches_original_script_js(self):
        """Every item value in calculations.ITEMS must appear in script.js."""
        with open(SCRIPT_JS, encoding="utf-8") as fh:
            source = fh.read()
        for item in calc.ITEMS:
            g = ("%g" % item["g"])
            expected = ('{id:"%s",name:"%s",g:%s,def:%d,alt:"%s",cut:%g,'
                        'tip:"%s"}' % (item["id"], item["name"], g,
                                       item["def"], item["alt"], item["cut"],
                                       item["tip"]))
            self.assertIn(expected, source)
        self.assertIn("var CO2_PER_KG=3.0;", source)
        self.assertEqual(len(calc.ITEMS), 7)


class FormulaTests(unittest.TestCase):
    def test_default_inputs_hand_calculated(self):
        r = calculate_footprint(DEFAULTS)
        # 7*12 + 5*6 + 3*0.5 + 2*4 + 2*15 + 4*10 + 6*3 = 211.5 g
        self.assertAlmostEqual(r["weekly_grams"], 211.5)
        self.assertAlmostEqual(r["annual_kg"], 211.5 * 52 / 1000)   # 10.998
        self.assertAlmostEqual(r["annual_co2e_kg"], 10.998 * 3.0)   # 32.994
        self.assertEqual(r["eco_score"], 79)  # round(100 - 21.15)
        ps = r["potential_savings"]
        self.assertAlmostEqual(ps["weekly_grams"], 189.7)
        self.assertAlmostEqual(ps["annual_kg"], 189.7 * 52 / 1000)
        order = [x["item_id"] for x in ps["recommendations"]]
        # bag and box tie at 27 g - stable sort keeps dataset order.
        self.assertEqual(order, ["bottle", "cup", "bag", "box", "wrap",
                                 "cutlery", "straw"])
        self.assertTrue(ps["recommendations"][0]["biggest_impact"])
        self.assertAlmostEqual(
            sum(c["share_percent"] for c in r["categories"]), 100.0, places=1)

    def test_zero_usage(self):
        r = calculate_footprint({})
        self.assertEqual(r["weekly_grams"], 0)
        self.assertEqual(r["eco_score"], 100)
        self.assertEqual(r["potential_savings"]["recommendations"], [])
        self.assertEqual(r["potential_savings"]["top_recommendation"], "")

    def test_eco_score_floor_and_js_rounding(self):
        self.assertEqual(calc.eco_score(5000), 0)
        self.assertEqual(calc.eco_score(1000), 0)
        # 100 - 15/10 = 98.5 -> Math.round gives 99 (Python round gives 98)
        self.assertEqual(calc.eco_score(15), 99)
        self.assertEqual(calc.js_round(-0.5), 0)  # Math.round(-0.5) === -0

    def test_co2_assumption_is_labelled(self):
        r = calculate_footprint(DEFAULTS)
        self.assertEqual(r["assumptions"]["co2e_per_kg_plastic"], 3.0)
        self.assertIn("approximate", r["assumptions"]["co2e_note"])
        self.assertIn("not a universal", r["assumptions"]["co2e_note"])

    def test_decimal_quantities_allowed(self):
        r = calculate_footprint({"bottle": 1.5})
        self.assertAlmostEqual(r["weekly_grams"], 18)


class ValidationTests(unittest.TestCase):
    def assertInvalid(self, quantities, field):
        with self.assertRaises(ValidationError) as ctx:
            calculate_footprint(quantities)
        self.assertIn(field, ctx.exception.errors)

    def test_negative_rejected(self):
        self.assertInvalid({"bottle": -1}, "bottle")

    def test_non_numbers_rejected(self):
        self.assertInvalid({"bag": "5"}, "bag")
        self.assertInvalid({"bag": True}, "bag")
        self.assertInvalid({"bag": [1]}, "bag")

    def test_nan_and_infinity_rejected(self):
        self.assertInvalid({"cup": float("nan")}, "cup")
        self.assertInvalid({"cup": float("inf")}, "cup")

    def test_too_large_rejected(self):
        self.assertInvalid({"wrap": calc.MAX_WEEKLY_QUANTITY + 1}, "wrap")

    def test_unknown_item_rejected(self):
        self.assertInvalid({"bottel": 3}, "bottel")

    def test_not_an_object_rejected(self):
        self.assertInvalid([1, 2, 3], "quantities")
        self.assertInvalid(None, "quantities")

    def test_all_errors_reported_together(self):
        with self.assertRaises(ValidationError) as ctx:
            calculate_footprint({"bottle": -1, "bag": "x", "foo": 1})
        self.assertEqual(set(ctx.exception.errors), {"bottle", "bag", "foo"})


CASES = [
    DEFAULTS,
    {},
    {"bottle": 1},
    {"straw": 1},
    {"straw": 3, "wrap": 1},
    {"bottle": 14, "bag": 10, "straw": 7, "cutlery": 5, "box": 6, "cup": 8,
     "wrap": 12},
    {"box": 50, "cup": 30},           # score floors at 0
    {"cup": 1.5, "wrap": 2.5, "straw": 0.5},
    {"bag": 3, "box": 1.2},           # tie between bag and box savings
    {"bottle": 100, "bag": 100, "straw": 100, "cutlery": 100, "box": 100,
     "cup": 100, "wrap": 100},
]


@unittest.skipUnless(NODE, "Node.js not installed - JS comparison skipped")
class MatchesOriginalJavaScriptTests(unittest.TestCase):
    """Runs the real, unmodified script.js in Node and compares outputs."""

    def run_js(self, quantities):
        out = subprocess.run(
            [NODE, os.path.join(HERE, "js_reference.js"), SCRIPT_JS,
             json.dumps(quantities)],
            capture_output=True, text=True, check=True, timeout=30)
        return json.loads(out.stdout)

    def test_backend_matches_frontend(self):
        for quantities in CASES:
            with self.subTest(quantities=quantities):
                js = self.run_js(quantities)
                py = calculate_footprint(quantities)
                ps = py["potential_savings"]
                self.assertEqual(to_fixed(py["weekly_grams"], 0), js["weekly"])
                self.assertEqual(to_fixed(py["annual_kg"], 1), js["yearly"])
                self.assertEqual(to_fixed(py["annual_co2e_kg"], 1), js["co2"])
                self.assertEqual(str(py["eco_score"]), js["score"])
                self.assertEqual(to_fixed(ps["annual_kg"], 1), js["savedKg"])
                self.assertEqual(to_fixed(ps["annual_co2e_kg"], 1),
                                 js["savedCo2"])
                self.assertEqual(ps["top_recommendation"], js["top"])
                self.assertEqual([r["name"] for r in ps["recommendations"]],
                                 js["recs"])
                for c in py["categories"]:
                    self.assertEqual(to_fixed(c["weekly_grams"], 0),
                                     js["bars"][c["name"]])


if __name__ == "__main__":
    unittest.main()
