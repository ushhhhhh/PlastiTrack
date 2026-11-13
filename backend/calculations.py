"""
Plastic footprint calculations for PlastiTrack.

This module is a faithful Python port of the calculation logic in the
original frontend file ``script.js``. The dataset (item weights, default
quantities, alternatives, reduction fractions and tips) and every formula
are copied unchanged so that the backend and the browser produce the same
numbers.

Formulas (identical to script.js):
    weekly grams         = sum(quantity x grams per item)
    annual plastic (kg)  = weekly grams x 52 / 1000
    annual CO2e (kg)     = annual plastic kg x CO2E_PER_KG_PLASTIC
    eco score (0-100)    = max(0, round(100 - weekly grams / 10))
    potential saving     = item weekly grams x item reduction fraction ("cut")

Everything here is a simple rule-based model. Nothing in this module is
machine learning.
"""

import math
from decimal import ROUND_HALF_UP, Decimal

# Version tag stored with every saved footprint. Records are only compared
# with each other when they were produced by the same dataset/formulas, so
# if the dataset is ever changed this string must change too.
DATASET_VERSION = "v1-original-js"

# APPROXIMATE PROJECT ASSUMPTION - not a universal scientific constant.
# Copied from script.js (CO2_PER_KG = 3.0). Real life-cycle emissions vary
# widely by polymer type, manufacturing process and end-of-life treatment.
CO2E_PER_KG_PLASTIC = 3.0
CO2E_ASSUMPTION_NOTE = (
    "CO2e uses an approximate project assumption of 3.0 kg CO2e per kg of "
    "plastic. It is not a universal scientific constant; real values vary "
    "by plastic type, production and disposal."
)

WEEKS_PER_YEAR = 52

# Upper limit on a single weekly quantity. Used only to reject obviously
# mistyped input (e.g. 1e9 bottles); it does not change any calculation.
MAX_WEEKLY_QUANTITY = 10000

# Dataset copied verbatim from script.js (same order, same values).
# g   = approx. grams of plastic per item
# def = default weekly quantity shown in the frontend
# cut = fraction of that item's plastic avoided by switching to `alt`
ITEMS = [
    {"id": "bottle", "name": "Plastic water bottle (500ml)", "g": 12, "def": 7,
     "alt": "Reusable steel/copper bottle", "cut": 0.95,
     "tip": "Carry a refillable bottle; refill at water stations."},
    {"id": "bag", "name": "Plastic carry bag", "g": 6, "def": 5,
     "alt": "Cloth / jute bag", "cut": 0.9,
     "tip": "Keep a foldable cloth bag in your backpack."},
    {"id": "straw", "name": "Plastic straw", "g": 0.5, "def": 3,
     "alt": "Steel / bamboo straw or skip it", "cut": 1,
     "tip": "Just sip directly or use a steel straw."},
    {"id": "cutlery", "name": "Disposable cutlery set", "g": 4, "def": 2,
     "alt": "Personal steel cutlery set", "cut": 0.95,
     "tip": "Keep a spoon/fork set in your bag."},
    {"id": "box", "name": "Takeaway plastic container", "g": 15, "def": 2,
     "alt": "Steel tiffin / own container", "cut": 0.9,
     "tip": "Ask for food in your own tiffin box."},
    {"id": "cup", "name": "Disposable plastic/coated cup", "g": 10, "def": 4,
     "alt": "Reusable mug / kulhad", "cut": 0.9,
     "tip": "Use your own mug at the canteen or tea stall."},
    {"id": "wrap", "name": "Snack wrapper / sachet", "g": 3, "def": 6,
     "alt": "Bulk buying, paper or refill packs", "cut": 0.6,
     "tip": "Buy larger packs or loose snacks to cut wrappers."},
]

ITEMS_BY_ID = {item["id"]: item for item in ITEMS}
ITEM_IDS = [item["id"] for item in ITEMS]


class ValidationError(ValueError):
    """Raised when user input is invalid. Carries a dict of field errors."""

    def __init__(self, message, errors=None):
        super().__init__(message)
        self.message = message
        self.errors = errors or {}


def js_round(value):
    """Round like JavaScript's Math.round (halves round up towards +inf).

    Python's built-in round() uses banker's rounding (round(2.5) == 2),
    whereas Math.round(2.5) == 3, so we cannot use round() here.
    """
    return int(math.floor(value + 0.5))


def js_to_fixed(value, digits):
    """Format like JavaScript's Number.toFixed (ties round up), so text
    messages match the frontend exactly."""
    quantum = Decimal(1).scaleb(-digits)
    return str(Decimal(value).quantize(quantum, rounding=ROUND_HALF_UP))


def _clean(value, digits=4):
    """Round away floating-point noise (e.g. 0.30000000000000004)."""
    return round(value, digits)


def validate_quantities(quantities):
    """Validate a ``{item_id: weekly_quantity}`` mapping.

    Rules:
      * must be a JSON object;
      * keys must be one of the seven known item ids (unknown keys are
        rejected so that typos are not silently ignored);
      * values must be finite, non-negative numbers (booleans and numeric
        strings are rejected) no larger than MAX_WEEKLY_QUANTITY;
      * a missing item is treated as 0, exactly like an empty input box in
        the original frontend.

    Returns a new dict containing all seven ids with float quantities.
    """
    if not isinstance(quantities, dict):
        raise ValidationError(
            "'quantities' must be an object mapping item ids to weekly "
            "quantities.",
            {"quantities": "expected an object"},
        )

    errors = {}
    for key in quantities:
        if key not in ITEMS_BY_ID:
            errors[str(key)] = (
                "unknown item id; expected one of: " + ", ".join(ITEM_IDS)
            )

    cleaned = {}
    for item_id in ITEM_IDS:
        raw = quantities.get(item_id, 0)
        if raw is None:
            raw = 0
        # bool is a subclass of int in Python, so exclude it explicitly.
        if isinstance(raw, bool) or not isinstance(raw, (int, float)):
            errors[item_id] = "must be a number"
            continue
        if math.isnan(raw) or math.isinf(raw):
            errors[item_id] = "must be a finite number"
            continue
        if raw < 0:
            errors[item_id] = "must not be negative"
            continue
        if raw > MAX_WEEKLY_QUANTITY:
            errors[item_id] = (
                "must not exceed %d items per week" % MAX_WEEKLY_QUANTITY
            )
            continue
        cleaned[item_id] = float(raw)

    if errors:
        raise ValidationError("Invalid weekly quantities.", errors)
    return cleaned


def eco_score(weekly_grams):
    """Eco score: 100 at 0 g/week, falling linearly to 0 at 1000 g/week."""
    return max(0, js_round(100 - weekly_grams / 10))


def annual_kg(weekly_grams):
    return weekly_grams * WEEKS_PER_YEAR / 1000


def co2e_kg(annual_plastic_kg):
    return annual_plastic_kg * CO2E_PER_KG_PLASTIC


def calculate_footprint(quantities):
    """Calculate the full footprint for validated or raw quantities.

    Mirrors the ``#go`` click handler in script.js and returns a JSON-ready
    dict. Raises ValidationError on bad input.
    """
    q = validate_quantities(quantities)

    categories = []
    for item in ITEMS:
        quantity = q[item["id"]]
        weekly = quantity * item["g"]
        categories.append({
            "item_id": item["id"],
            "name": item["name"],
            "grams_per_item": item["g"],
            "weekly_quantity": quantity,
            "weekly_grams": _clean(weekly),
            "annual_kg": _clean(annual_kg(weekly)),
        })

    weekly_total = sum(c["weekly_grams"] for c in categories)
    for c in categories:
        c["share_percent"] = (
            _clean(c["weekly_grams"] / weekly_total * 100, 2)
            if weekly_total > 0 else 0.0
        )

    yearly = annual_kg(weekly_total)
    co2 = co2e_kg(yearly)

    # Recommendation engine (rule-based, same as script.js): every item with
    # usage > 0, potential saving = weekly grams x cut, biggest saving first.
    # sorted() is stable, matching Array.prototype.sort in modern browsers.
    recs = []
    for c in categories:
        if c["weekly_grams"] > 0:
            item = ITEMS_BY_ID[c["item_id"]]
            save_week = c["weekly_grams"] * item["cut"]
            recs.append({
                "item_id": item["id"],
                "name": item["name"],
                "alternative": item["alt"],
                "tip": item["tip"],
                "reduction_fraction": item["cut"],
                "weekly_grams_saved": _clean(save_week),
                "annual_kg_saved": _clean(annual_kg(save_week)),
            })
    recs.sort(key=lambda r: r["weekly_grams_saved"], reverse=True)
    for index, rec in enumerate(recs):
        rec["rank"] = index + 1
        rec["biggest_impact"] = index == 0

    save_week_total = sum(r["weekly_grams_saved"] for r in recs)
    save_year = annual_kg(save_week_total)

    top_message = ""
    if recs:
        top_message = (
            "Start with your biggest saving: replacing %s alone cuts %s kg "
            "of plastic a year." % (
                recs[0]["name"].lower(),
                js_to_fixed(annual_kg(recs[0]["weekly_grams_saved"]), 1))
        )

    return {
        "dataset_version": DATASET_VERSION,
        "weekly_grams": _clean(weekly_total),
        "annual_kg": _clean(yearly),
        "annual_co2e_kg": _clean(co2),
        "eco_score": eco_score(weekly_total),
        "categories": categories,
        "potential_savings": {
            "description": (
                "Estimated plastic you COULD avoid by switching to the "
                "suggested alternatives. This is a potential, not a "
                "measured, reduction."
            ),
            "weekly_grams": _clean(save_week_total),
            "annual_kg": _clean(save_year),
            "annual_co2e_kg": _clean(co2e_kg(save_year)),
            "top_recommendation": top_message,
            "recommendations": recs,
        },
        "assumptions": {
            "co2e_per_kg_plastic": CO2E_PER_KG_PLASTIC,
            "co2e_note": CO2E_ASSUMPTION_NOTE,
            "weeks_per_year": WEEKS_PER_YEAR,
            "eco_score_rule": "max(0, round(100 - weekly grams / 10))",
            "method": "Rule-based calculation over a fixed item dataset "
                      "(not machine learning).",
        },
    }
