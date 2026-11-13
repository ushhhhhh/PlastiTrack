"""Weekly footprint history endpoints."""

from flask import Blueprint, jsonify, request

from ..database import get_db
from ..services import footprint_service
from . import json_body

bp = Blueprint("history", __name__, url_prefix="/api/history")


@bp.post("")
def save():
    """Body: {"user_id": "riya_22", "display_name": "Riya" (optional),
              "quantities": {...}}
    The server recalculates the footprint itself before saving."""
    body = json_body()
    record, result = footprint_service.save_calculation(
        get_db(), body.get("user_id"), body.get("quantities"),
        display_name=body.get("display_name"))
    return jsonify({"record": record, "calculation": result}), 201


@bp.get("")
def history():
    """Query: ?user_id=riya_22&limit=50 (newest first)."""
    return jsonify(footprint_service.get_history(
        get_db(), request.args.get("user_id"), request.args.get("limit")))


@bp.get("/comparison")
def comparison():
    """Query: ?user_id=riya_22 - latest vs. previous footprint."""
    return jsonify(footprint_service.compare_latest(
        get_db(), request.args.get("user_id")))
