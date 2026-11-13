"""
Plastic Impact Passport: one personal sustainability record per user.

The passport keeps MEASURED footprint data and SELF-REPORTED challenge data
in separate sections, so challenge completions can never be mistaken for
(or double-counted as) plastic reductions.
"""

from .. import models
from ..errors import NotFoundError
from . import campus_service, challenge_service, footprint_service


def get_passport(db, user_id):
    user_id = models.validate_user_id(user_id)
    user = models.get_user(db, user_id)
    if user is None:
        raise NotFoundError("No data found for user '%s'. Save a footprint "
                            "or join a challenge first." % user_id)

    progress = challenge_service.get_progress(db, user_id)
    return {
        "user": models.user_to_dict(user),
        "team": campus_service.get_membership(db, user_id),
        "measured_footprint": footprint_service.footprint_overview(
            db, user_id),
        "self_reported_actions": {
            "completed_challenges": progress["completed_count"],
            "challenges_in_progress": progress["in_progress_count"],
            "completed": [
                {"title": c["challenge"]["title"],
                 "completed_at": c["completed_at"]}
                for c in progress["completed"]],
            "note": challenge_service.SELF_REPORTED_NOTE,
        },
        "badges": progress["badges"],
    }
