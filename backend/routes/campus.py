"""Campus Sustainability Challenge endpoints."""

from flask import Blueprint, jsonify

from ..database import get_db
from ..services import campus_service
from . import bool_arg, json_body

bp = Blueprint("campus", __name__, url_prefix="/api/campus")


@bp.get("/teams")
def teams():
    return jsonify({"teams": campus_service.list_teams(get_db()),
                    "sample_note": campus_service.SAMPLE_NOTE})


@bp.post("/teams")
def create_team():
    """Body: {"name": "Green Warriors", "description": "..." (optional)}"""
    body = json_body()
    team = campus_service.create_team(get_db(), body.get("name"),
                                      body.get("description"))
    return jsonify(team), 201


@bp.post("/join")
def join():
    """Body: {"user_id": "riya_22", "team_id": 1,
              "display_name": "Riya" (optional)}"""
    body = json_body()
    membership, created = campus_service.join_team(
        get_db(), body.get("user_id"), body.get("team_id"),
        display_name=body.get("display_name"))
    return jsonify(membership), 201 if created else 200


@bp.get("/summary")
def summary():
    """Query: ?include_sample=false to hide sample-data teams."""
    return jsonify(campus_service.campus_summary(
        get_db(), include_sample=bool_arg("include_sample", True)))


@bp.get("/leaderboard")
def leaderboard():
    """Query: ?include_sample=false to hide sample-data teams."""
    return jsonify(campus_service.leaderboard(
        get_db(), include_sample=bool_arg("include_sample", True)))
