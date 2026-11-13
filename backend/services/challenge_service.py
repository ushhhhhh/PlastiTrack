"""
Eco Challenge logic: listing, joining, completing and badges.

IMPORTANT: completing a challenge is a SELF-REPORTED action. It never adds
plastic savings to anybody's footprint. Only saved footprint calculations
(measured data) can show a reduction.
"""

from .. import models
from ..errors import ConflictError, NotFoundError, ValidationError
from . import footprint_service

SELF_REPORTED_NOTE = (
    "Challenge completion is self-reported. It earns badges but does not "
    "add any plastic savings; reductions are only shown from your saved "
    "footprint calculations."
)


def _challenge_to_dict(row):
    return {
        "id": row["id"], "slug": row["slug"], "title": row["title"],
        "description": row["description"],
        "related_item": row["related_item"],
        "duration_days": row["duration_days"],
    }


def _parse_challenge_id(raw):
    if raw is None:
        raise ValidationError("'challenge_id' is required.",
                              {"challenge_id": "required"})
    if isinstance(raw, bool) or not isinstance(raw, (int, str)):
        raise ValidationError("Invalid 'challenge_id'.",
                              {"challenge_id": "must be an id or slug"})
    return raw


def get_challenge(db, challenge_ref):
    """Look a challenge up by numeric id or slug."""
    challenge_ref = _parse_challenge_id(challenge_ref)
    if isinstance(challenge_ref, int) or str(challenge_ref).isdigit():
        row = db.execute("SELECT * FROM challenges WHERE id = ?",
                         (int(challenge_ref),)).fetchone()
    else:
        row = db.execute("SELECT * FROM challenges WHERE slug = ?",
                         (challenge_ref,)).fetchone()
    if row is None:
        raise NotFoundError("Challenge '%s' not found." % challenge_ref)
    return _challenge_to_dict(row)


def _user_rows(db, user_id):
    rows = db.execute("SELECT * FROM user_challenges WHERE user_id = ?",
                      (user_id,)).fetchall()
    return {r["challenge_id"]: dict(r) for r in rows}


def list_challenges(db, user_id=None):
    challenges = [_challenge_to_dict(r) for r in
                  db.execute("SELECT * FROM challenges ORDER BY id")]
    if user_id:
        user_id = models.validate_user_id(user_id)
        progress = _user_rows(db, user_id)
        for c in challenges:
            p = progress.get(c["id"])
            c["status"] = p["status"] if p else "not_joined"
            c["joined_at"] = p["joined_at"] if p else None
            c["completed_at"] = p["completed_at"] if p else None
    return {"challenges": challenges, "note": SELF_REPORTED_NOTE}


def join_challenge(db, user_id, challenge_ref):
    """Join a challenge. Returns (entry, created)."""
    user_id = models.validate_user_id(user_id, sample=False)
    challenge = get_challenge(db, challenge_ref)
    models.ensure_user(db, user_id)
    # Atomic: if two identical requests arrive together, exactly one row is
    # inserted and the other request simply sees it (no crash).
    cur = db.execute(
        "INSERT INTO user_challenges (user_id, challenge_id, status, "
        "joined_at) VALUES (?, ?, 'joined', ?) "
        "ON CONFLICT(user_id, challenge_id) DO NOTHING",
        (user_id, challenge["id"], models.now_iso()))
    created = cur.rowcount == 1
    db.commit()
    row = _user_rows(db, user_id)[challenge["id"]]
    if not created and row["status"] == "completed":
        raise ConflictError("You have already completed this challenge.")
    return _entry(challenge, row), created


def complete_challenge(db, user_id, challenge_ref, completed_at=None):
    user_id = models.validate_user_id(user_id, sample=False)
    challenge = get_challenge(db, challenge_ref)
    # Atomic state change joined -> completed. Only one request can win; a
    # duplicate (even sent at the same instant) updates 0 rows.
    cur = db.execute(
        "UPDATE user_challenges SET status = 'completed', completed_at = ? "
        "WHERE user_id = ? AND challenge_id = ? AND status = 'joined'",
        (completed_at or models.now_iso(), user_id, challenge["id"]))
    db.commit()
    if cur.rowcount != 1:
        existing = _user_rows(db, user_id).get(challenge["id"])
        if existing is None:
            raise ConflictError(
                "Join the challenge before marking it complete.")
        raise ConflictError("This challenge is already completed.")
    entry = _entry(challenge, _user_rows(db, user_id)[challenge["id"]])
    progress = get_progress(db, user_id)
    return entry, progress


def _entry(challenge, row):
    return {
        "challenge": challenge, "status": row["status"],
        "joined_at": row["joined_at"], "completed_at": row["completed_at"],
        "self_reported": True,
    }


# --------------------------------------------------------------- badges ----

def compute_badges(db, user_id):
    """Badges are derived from stored data, so they can never get out of
    sync. Each badge says whether it is based on self-reported or measured
    data."""
    completed = db.execute(
        "SELECT completed_at FROM user_challenges WHERE user_id = ? AND "
        "status = 'completed' ORDER BY completed_at", (user_id,)).fetchall()
    completed_times = [r["completed_at"] for r in completed]
    total_challenges = db.execute(
        "SELECT COUNT(*) FROM challenges").fetchone()[0]

    badges = []

    def add(code, name, description, basis, earned_at):
        badges.append({"code": code, "name": name,
                       "description": description, "basis": basis,
                       "earned_at": earned_at})

    if len(completed_times) >= 1:
        add("first-step", "First Step", "Completed your first eco challenge.",
            "self_reported", completed_times[0])
    if len(completed_times) >= 3:
        add("habit-builder", "Habit Builder", "Completed 3 eco challenges.",
            "self_reported", completed_times[2])
    if total_challenges and len(completed_times) >= total_challenges:
        add("plastic-free-champion", "Plastic-Free Champion",
            "Completed every eco challenge.", "self_reported",
            completed_times[total_challenges - 1])

    records = footprint_service.comparable_records(db, user_id)
    if len(records) >= 3:
        add("footprint-tracker", "Footprint Tracker",
            "Saved 3 footprint calculations.", "measured",
            records[2]["recorded_at"])
    if records:
        baseline = records[0]["weekly_grams"]
        first_lower = next(
            (r for r in records[1:] if r["weekly_grams"]
             < baseline - footprint_service.TREND_TOLERANCE_GRAMS), None)
        if first_lower:
            add("measured-reducer", "Measured Reducer",
                "A saved footprint showed lower weekly plastic use than "
                "your first one.", "measured", first_lower["recorded_at"])
    return badges


def get_progress(db, user_id):
    user_id = models.validate_user_id(user_id)
    rows = db.execute(
        """SELECT uc.*, c.slug, c.title, c.description, c.related_item,
                  c.duration_days, c.id AS cid
           FROM user_challenges uc JOIN challenges c ON c.id = uc.challenge_id
           WHERE uc.user_id = ? ORDER BY uc.joined_at, c.id""",
        (user_id,)).fetchall()
    joined, completed = [], []
    for r in rows:
        challenge = {"id": r["cid"], "slug": r["slug"], "title": r["title"],
                     "description": r["description"],
                     "related_item": r["related_item"],
                     "duration_days": r["duration_days"]}
        entry = _entry(challenge, r)
        (completed if r["status"] == "completed" else joined).append(entry)
    return {
        "user_id": user_id,
        "completed_count": len(completed),
        "in_progress_count": len(joined),
        "completed": completed,
        "in_progress": joined,
        "badges": compute_badges(db, user_id),
        "note": SELF_REPORTED_NOTE,
    }
