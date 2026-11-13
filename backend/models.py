"""
Data-access helpers ("models") for PlastiTrack.

These functions contain the SQL for reading and writing users and footprint
records. Business rules (comparisons, badges, leaderboards...) live in the
``services`` package and call into these helpers.
"""

import re
from datetime import datetime, timezone

from .calculations import ITEMS_BY_ID
from .errors import ConflictError, ValidationError

USER_ID_PATTERN = re.compile(r"^[A-Za-z0-9_.-]{3,40}$")


def now_iso():
    """Current UTC time as an ISO 8601 string, e.g. 2026-11-13T10:15:00+00:00."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def parse_iso(value):
    return datetime.fromisoformat(value)


# User ids starting with this prefix are reserved for the sample-data
# script, so real users can never be mixed up with (or deleted as) samples.
SAMPLE_USER_PREFIX = "sample_"


def is_sample_user_id(user_id):
    return user_id.lower().startswith(SAMPLE_USER_PREFIX)


def validate_user_id(value, field="user_id", sample=None):
    """Validate a user id.

    sample=None  -> reading: any valid id (including sample ids) is fine.
    sample=False -> writing real data: reserved 'sample_' ids are rejected.
    sample=True  -> writing sample data: the id MUST use the 'sample_' prefix.
    """
    if value is None or (isinstance(value, str) and not value.strip()):
        raise ValidationError("'%s' is required." % field,
                              {field: "required"})
    if not isinstance(value, str) or not USER_ID_PATTERN.match(value.strip()):
        raise ValidationError(
            "Invalid '%s'." % field,
            {field: "3-40 characters: letters, digits, '_', '-' or '.'"},
        )
    value = value.strip()
    if sample is False and is_sample_user_id(value):
        raise ValidationError(
            "Invalid '%s'." % field,
            {field: "ids starting with '%s' are reserved for sample data"
                    % SAMPLE_USER_PREFIX})
    if sample is True and not is_sample_user_id(value):
        raise ValidationError(
            "Sample user ids must start with '%s'." % SAMPLE_USER_PREFIX,
            {field: "must start with '%s'" % SAMPLE_USER_PREFIX})
    return value


def validate_display_name(value):
    if value is None:
        return None
    if not isinstance(value, str) or len(value.strip()) > 80:
        raise ValidationError("Invalid 'display_name'.",
                              {"display_name": "text of at most 80 characters"})
    return value.strip() or None


# ---------------------------------------------------------------- users ----

def get_user(db, user_id):
    row = db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    return dict(row) if row else None


def ensure_user(db, user_id, display_name=None, is_sample=False):
    """Create the user if it does not exist yet; return the user dict.

    INSERT OR IGNORE makes this safe when two requests create the same new
    user at the same moment (no UNIQUE-constraint crash).
    """
    db.execute(
        "INSERT OR IGNORE INTO users (id, display_name, is_sample, "
        "created_at) VALUES (?, ?, ?, ?)",
        (user_id, display_name, 1 if is_sample else 0, now_iso()),
    )
    user = get_user(db, user_id)
    if bool(user["is_sample"]) != bool(is_sample):
        # Only reachable with data created before the reserved prefix rule.
        raise ConflictError(
            "User '%s' is %s user; sample and real data cannot be mixed."
            % (user_id, "a sample" if user["is_sample"] else "a real"))
    if display_name and display_name != user["display_name"]:
        db.execute("UPDATE users SET display_name = ? WHERE id = ?",
                   (display_name, user_id))
        user["display_name"] = display_name
    return user


def user_to_dict(user):
    return {
        "user_id": user["id"],
        "display_name": user["display_name"],
        "is_sample": bool(user["is_sample"]),
        "created_at": user["created_at"],
    }


# ----------------------------------------------------------- footprints ----

def insert_footprint(db, user_id, result, recorded_at=None):
    """Store a calculation result (from calculations.calculate_footprint)."""
    recorded_at = recorded_at or now_iso()
    cur = db.execute(
        """INSERT INTO footprints
               (user_id, recorded_at, weekly_grams, annual_kg,
                annual_co2e_kg, eco_score, dataset_version)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (user_id, recorded_at, result["weekly_grams"], result["annual_kg"],
         result["annual_co2e_kg"], result["eco_score"],
         result["dataset_version"]),
    )
    footprint_id = cur.lastrowid
    db.executemany(
        """INSERT INTO footprint_items
               (footprint_id, item_id, weekly_quantity, weekly_grams)
           VALUES (?, ?, ?, ?)""",
        [(footprint_id, c["item_id"], c["weekly_quantity"], c["weekly_grams"])
         for c in result["categories"]],
    )
    return footprint_id


def _attach_items(db, records):
    if not records:
        return records
    ids = [r["id"] for r in records]
    placeholders = ",".join("?" * len(ids))
    rows = db.execute(
        "SELECT * FROM footprint_items WHERE footprint_id IN (%s)"
        % placeholders, ids).fetchall()
    by_fp = {}
    for row in rows:
        by_fp.setdefault(row["footprint_id"], {})[row["item_id"]] = row
    for record in records:
        items = by_fp.get(record["id"], {})
        record["categories"] = [
            {
                "item_id": item_id,
                "name": ITEMS_BY_ID[item_id]["name"]
                if item_id in ITEMS_BY_ID else item_id,
                "weekly_quantity": items[item_id]["weekly_quantity"],
                "weekly_grams": items[item_id]["weekly_grams"],
            }
            for item_id in (list(ITEMS_BY_ID) + sorted(
                k for k in items if k not in ITEMS_BY_ID))
            if item_id in items
        ]
    return records


def footprint_to_dict(row):
    return {
        "id": row["id"],
        "user_id": row["user_id"],
        "recorded_at": row["recorded_at"],
        "weekly_grams": row["weekly_grams"],
        "annual_kg": row["annual_kg"],
        "annual_co2e_kg": row["annual_co2e_kg"],
        "eco_score": row["eco_score"],
        "dataset_version": row["dataset_version"],
    }


def list_footprints(db, user_id, limit=None, newest_first=True,
                    with_items=True):
    order = "DESC" if newest_first else "ASC"
    sql = ("SELECT * FROM footprints WHERE user_id = ? "
           "ORDER BY recorded_at %s, id %s" % (order, order))
    params = [user_id]
    if limit is not None:
        sql += " LIMIT ?"
        params.append(limit)
    records = [footprint_to_dict(r) for r in db.execute(sql, params)]
    return _attach_items(db, records) if with_items else records


def get_footprint(db, footprint_id):
    row = db.execute("SELECT * FROM footprints WHERE id = ?",
                     (footprint_id,)).fetchone()
    if row is None:
        return None
    return _attach_items(db, [footprint_to_dict(row)])[0]


def count_footprints(db, user_id):
    return db.execute("SELECT COUNT(*) FROM footprints WHERE user_id = ?",
                      (user_id,)).fetchone()[0]
