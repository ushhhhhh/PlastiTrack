"""Plastic Impact Passport endpoint."""

from flask import Blueprint, jsonify, request

from ..database import get_db
from ..services import passport_service

bp = Blueprint("passport", __name__, url_prefix="/api")


@bp.get("/passport")
def passport():
    """Query: ?user_id=riya_22"""
    return jsonify(passport_service.get_passport(
        get_db(), request.args.get("user_id")))
