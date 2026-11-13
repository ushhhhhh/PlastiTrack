"""
Footprint history, comparison and Plastic Impact Passport logic.

Measured vs. self-reported
--------------------------
Everything in this module is based on *measured footprint records*: weekly
usage that the user entered and the backend calculated. Challenge
completions (self-reported actions) never change these numbers.
"""

from .. import models
from ..calculations import (DATASET_VERSION, ValidationError, annual_kg,
                            calculate_footprint, co2e_kg)

# Changes smaller than this (in grams/week) are treated as "unchanged" so
# floating-point noise never shows up as a trend.
TREND_TOLERANCE_GRAMS = 0.001

CUMULATIVE_METHOD = (
    "Baseline = your first saved footprint. For every period between two "
    "consecutive saved records, weekly usage is assumed to change linearly "
    "from one record to the next, and the difference from the baseline is "
    "multiplied by the number of weeks in that period (trapezoidal "
    "estimate). Each week is counted once against one fixed baseline, so "
    "nothing is double-counted. Nothing is extrapolated beyond your latest "
    "record, and challenge completions are NOT included. A negative value "
    "means more plastic was used than at the baseline."
)


def trend_of(change):
    if change is None:
        return "insufficient_data"
    if change > TREND_TOLERANCE_GRAMS:
        return "increasing"
    if change < -TREND_TOLERANCE_GRAMS:
        return "decreasing"
    return "unchanged"


def percent_change(old, new):
    if old is None or new is None or old == 0:
        return None
    return round((new - old) / old * 100, 2)


# ------------------------------------------------------------- history ----

def _is_sample(db, user_id):
    user = models.get_user(db, user_id)
    return bool(user and user["is_sample"])


def save_calculation(db, user_id, quantities, display_name=None,
                     recorded_at=None, sample=False):
    """Validate, recalculate on the server, and store a footprint.

    The client never sends the results - they are always recalculated here
    so stored values cannot be tampered with or drift from the formulas.
    ``recorded_at`` and ``sample=True`` are only used by tests and the
    sample-data script (the API always saves real data).
    """
    user_id = models.validate_user_id(user_id, sample=sample)
    display_name = models.validate_display_name(display_name)
    result = calculate_footprint(quantities)
    models.ensure_user(db, user_id, display_name, is_sample=sample)
    footprint_id = models.insert_footprint(db, user_id, result, recorded_at)
    db.commit()
    record = models.get_footprint(db, footprint_id)
    return record, result


def parse_limit(raw, default=50, maximum=500):
    if raw is None or raw == "":
        return default
    try:
        value = int(raw)
    except (TypeError, ValueError):
        raise ValidationError("Invalid 'limit'.",
                              {"limit": "must be a whole number"})
    if value < 1 or value > maximum:
        raise ValidationError("Invalid 'limit'.",
                              {"limit": "must be between 1 and %d" % maximum})
    return value


def get_history(db, user_id, limit=None):
    user_id = models.validate_user_id(user_id)
    limit = parse_limit(limit)
    total = models.count_footprints(db, user_id)
    records = models.list_footprints(db, user_id, limit=limit)
    return {"user_id": user_id, "is_sample": _is_sample(db, user_id),
            "total_records": total, "returned": len(records),
            "records": records}


def compare_latest(db, user_id):
    """Compare the latest footprint with the previous comparable one."""
    user_id = models.validate_user_id(user_id)
    # Summary rows only; categories are loaded for the two records used.
    records = models.list_footprints(db, user_id, with_items=False)
    response = {"user_id": user_id, "is_sample": _is_sample(db, user_id),
                "total_records": len(records)}
    if not records:
        response.update(trend="insufficient_data", latest=None, previous=None,
                        message="No saved footprints yet.")
        return response

    latest = models.get_footprint(db, records[0]["id"])
    previous = next((r for r in records[1:]
                     if r["dataset_version"] == latest["dataset_version"]),
                    None)
    if previous is not None:
        previous = models.get_footprint(db, previous["id"])
    response["latest"] = latest
    response["previous"] = previous
    if previous is None:
        response.update(
            trend="insufficient_data",
            message="Save at least two footprints to see a comparison.")
        return response

    change = round(latest["weekly_grams"] - previous["weekly_grams"], 4)
    trend = trend_of(change)
    prev_items = {c["item_id"]: c for c in previous["categories"]}
    category_changes = []
    for c in latest["categories"]:
        before = prev_items.get(c["item_id"], {}).get("weekly_grams", 0.0)
        diff = round(c["weekly_grams"] - before, 4)
        category_changes.append({
            "item_id": c["item_id"], "name": c["name"],
            "previous_weekly_grams": before,
            "latest_weekly_grams": c["weekly_grams"],
            "change_weekly_grams": diff, "trend": trend_of(diff),
        })

    messages = {
        "decreasing": "Your weekly plastic use went down. Well done!",
        "increasing": "Your weekly plastic use went up since last time.",
        "unchanged": "Your weekly plastic use is the same as last time.",
    }
    response.update({
        "trend": trend,
        "message": messages[trend],
        "change": {
            "weekly_grams": change,
            "weekly_percent": percent_change(previous["weekly_grams"],
                                             latest["weekly_grams"]),
            "annual_kg": round(latest["annual_kg"] - previous["annual_kg"], 4),
            "annual_co2e_kg": round(latest["annual_co2e_kg"]
                                    - previous["annual_co2e_kg"], 4),
            "eco_score": latest["eco_score"] - previous["eco_score"],
        },
        "category_changes": category_changes,
    })
    return response


# ------------------------------------------------------------ passport ----

def comparable_records(db, user_id):
    """Oldest-first records produced by the current dataset version."""
    return [r for r in models.list_footprints(db, user_id, newest_first=False,
                                              with_items=False)
            if r["dataset_version"] == DATASET_VERSION]


def estimate_cumulative_reduction(records):
    """Trapezoidal estimate of plastic avoided vs. the first record.

    ``records`` must be oldest-first and comparable. Returns a dict that
    explains the result; ``estimated_kg`` is None when data is insufficient.
    """
    result = {"method": CUMULATIVE_METHOD, "sufficient_data": False,
              "estimated_kg": None, "estimated_co2e_kg": None,
              "weeks_covered": 0.0, "period_start": None, "period_end": None}
    if len(records) < 2:
        result["reason"] = "At least two comparable footprints are needed."
        return result

    baseline = records[0]["weekly_grams"]
    total_grams = 0.0
    total_weeks = 0.0
    for current, nxt in zip(records, records[1:]):
        seconds = (models.parse_iso(nxt["recorded_at"])
                   - models.parse_iso(current["recorded_at"])).total_seconds()
        weeks = max(0.0, seconds / (7 * 24 * 3600))
        average_use = (current["weekly_grams"] + nxt["weekly_grams"]) / 2
        total_grams += (baseline - average_use) * weeks
        total_weeks += weeks

    kg = round(total_grams / 1000, 4)
    result.update(sufficient_data=True, estimated_kg=kg,
                  estimated_co2e_kg=round(co2e_kg(kg), 4),
                  weeks_covered=round(total_weeks, 4),
                  period_start=records[0]["recorded_at"],
                  period_end=records[-1]["recorded_at"])
    if total_weeks < 1:
        result["note"] = ("Your records span less than one week, so this "
                          "estimate is very small and not yet meaningful.")
    return result


def footprint_overview(db, user_id):
    """Measured part of the passport (no challenge data)."""
    total = models.count_footprints(db, user_id)
    records = comparable_records(db, user_id)
    latest_any = models.list_footprints(db, user_id, limit=1,
                                        with_items=False)
    latest_any = latest_any[0] if latest_any else None

    overview = {
        "total_records": total,
        "comparable_records": len(records),
        "latest_eco_score": latest_any["eco_score"] if latest_any else None,
        "latest": latest_any,
        "baseline": records[0] if records else None,
    }
    if len(records) >= 2:
        first, last = records[0], records[-1]
        change = round(last["weekly_grams"] - first["weekly_grams"], 4)
        overview["change_since_baseline"] = {
            "weekly_grams": change,
            "weekly_percent": percent_change(first["weekly_grams"],
                                             last["weekly_grams"]),
            "eco_score": last["eco_score"] - first["eco_score"],
            "trend": trend_of(change),
            "annualised_reduction_kg_if_sustained": round(
                annual_kg(-change), 4),
            "note": ("'annualised_reduction_kg_if_sustained' is a yearly "
                     "RATE (what you would avoid in a year if your latest "
                     "weekly usage continued). Do not add it to the "
                     "cumulative estimate."),
        }
    else:
        overview["change_since_baseline"] = {
            "trend": "insufficient_data",
            "note": "At least two comparable footprints are needed.",
        }
    overview["estimated_cumulative_reduction"] = \
        estimate_cumulative_reduction(records)
    return overview
