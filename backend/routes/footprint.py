"""Footprint calculation endpoints (no database writes)."""

from flask import Blueprint, jsonify

from ..calculations import (CO2E_ASSUMPTION_NOTE, CO2E_PER_KG_PLASTIC,
                            DATASET_VERSION, ITEMS, calculate_footprint)
from . import json_body

bp = Blueprint("footprint", __name__, url_prefix="/api")


@bp.get("/items")
def items():
    """The plastic item dataset (same values as script.js)."""
    return jsonify({
        "dataset_version": DATASET_VERSION,
        "co2e_per_kg_plastic": CO2E_PER_KG_PLASTIC,
        "co2e_note": CO2E_ASSUMPTION_NOTE,
        "items": [
            {"id": i["id"], "name": i["name"], "grams_per_item": i["g"],
             "default_weekly_quantity": i["def"], "alternative": i["alt"],
             "reduction_fraction": i["cut"], "tip": i["tip"]}
            for i in ITEMS
        ],
    })


@bp.post("/calculate")
def calculate():
    """Body: {"quantities": {"bottle": 7, "bag": 5, ...}}"""
    body = json_body()
    return jsonify(calculate_footprint(body.get("quantities")))
