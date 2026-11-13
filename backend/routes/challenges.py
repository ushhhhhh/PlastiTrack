"""Eco Challenge endpoints."""

from flask import Blueprint, jsonify, request

from ..database import get_db
from ..services import challenge_service
from . import json_body

bp = Blueprint("challenges", __name__, url_prefix="/api/challenges")


@bp.get("")
def list_all():
    """Query: ?user_id=riya_22 (optional - adds that user's status)."""
    return jsonify(challenge_service.list_challenges(
        get_db(), request.args.get("user_id")))


@bp.post("/join")
def join():
    """Body: {"user_id": "riya_22", "challenge_id": 1 or "slug"}"""
    body = json_body()
    entry, created = challenge_service.join_challenge(
        get_db(), body.get("user_id"), body.get("challenge_id"))
    return jsonify(entry), 201 if created else 200


@bp.post("/complete")
def complete():
    """Body: {"user_id": "riya_22", "challenge_id": 1 or "slug"}"""
    body = json_body()
    entry, progress = challenge_service.complete_challenge(
        get_db(), body.get("user_id"), body.get("challenge_id"))
    return jsonify({"entry": entry, "badges": progress["badges"],
                    "completed_count": progress["completed_count"],
                    "note": challenge_service.SELF_REPORTED_NOTE})


@bp.get("/progress")
def progress():
    """Query: ?user_id=riya_22 - joined/completed challenges and badges."""
    return jsonify(challenge_service.get_progress(
        get_db(), request.args.get("user_id")))
